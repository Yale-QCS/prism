"""``MultiRealization``, prism's IR between the logical and the physical stage.

An ordered list of instructions, each a Qiskit ``Operation`` or a
``MultiRealizationOp``: a logical operation with candidate realizations, of which
a pass picks one (``choice``). Before ``placement`` is set, wire
``WIRES_PER_LOGICAL * i + w`` is rail ``w`` of logical qubit ``i``; after, wires
are physical qubits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, NamedTuple, NoReturn

from qiskit.circuit import (
    ClassicalRegister,
    Clbit,
    ControlFlowOp,
    Operation,
    QuantumCircuit,
    QuantumRegister,
    Qubit,
)
from qiskit.passmanager import IR
from qiskit.transpiler import TranspilerError

if TYPE_CHECKING:
    from collections.abc import Collection, Hashable, Sequence

    from prism.encodings.base import QubitEncoding

__all__ = [
    "DIAGONAL_GATES",
    "MultiRealization",
    "MultiRealizationInstruction",
    "MultiRealizationOp",
    "Placement",
    "commuting_predecessors",
    "list_schedule",
]

DIAGONAL_GATES = frozenset(
    {
        "rz",
        "crz",
        "z",
        "s",
        "sdg",
        "t",
        "tdg",
        "p",
        "u1",
        "id",
        "cp",
        "cz",
        "rzz",
        "cs",
        "csdg",
    }
)


def commuting_predecessors(
    wires: Sequence[Collection[Hashable]], diagonal: Sequence[bool]
) -> list[set[int]]:
    """The earlier ops each op must follow, where diagonal ops commute with each other."""
    preds: list[set[int]] = []
    last_nondiag: dict[Hashable, int] = {}
    diags_since: dict[Hashable, list[int]] = {}
    for k, ws in enumerate(wires):
        deps: set[int] = set()
        for w in ws:
            if w in last_nondiag:
                deps.add(last_nondiag[w])
            if not diagonal[k]:
                deps.update(diags_since.get(w, ()))
        for w in ws:
            if diagonal[k]:
                diags_since.setdefault(w, []).append(k)
            else:
                last_nondiag[w] = k
                diags_since[w] = []
        preds.append(deps)
    return preds


def list_schedule(
    preds: Sequence[Collection[int]],
    wires: Sequence[Collection[Hashable]],
    weight: Sequence[int],
) -> list[int]:
    """The ops in start order of a critical-path list schedule.

    At each time step the ready ops whose wires are free start, longest tail
    first, and hold their wires for ``weight`` steps.
    """
    n = len(preds)
    succs: list[list[int]] = [[] for _ in range(n)]
    for k, ps in enumerate(preds):
        for p in ps:
            succs[p].append(k)
    cp = [0] * n
    for k in range(n - 1, -1, -1):
        cp[k] = weight[k] + max((cp[s] for s in succs[k]), default=0)
    missing = [len(ps) for ps in preds]
    release = [0] * n
    wire_free: dict[Hashable, int] = {}
    pending = [k for k in range(n) if not missing[k]]
    order: list[int] = []
    t = 0
    while pending:
        started = True
        while started:
            started = False
            pending.sort(key=lambda k: (-cp[k], k))
            waiting = []
            for k in pending:
                if release[k] > t or any(wire_free.get(w, 0) > t for w in wires[k]):
                    waiting.append(k)
                    continue
                end = t + weight[k]
                for w in wires[k]:
                    wire_free[w] = end
                order.append(k)
                for s in succs[k]:
                    release[s] = max(release[s], end)
                    missing[s] -= 1
                    if not missing[s]:
                        waiting.append(s)
                        started = True
            pending = waiting
        if pending:
            t = min(
                max([release[k], *(wire_free.get(w, 0) for w in wires[k])])
                for k in pending
            )
    return order


@dataclass(eq=False)
class MultiRealizationOp:
    """A logical operation with candidate realizations.

    Args:
        name: The logical operation's name.
        candidates: Equal-width circuits; wire ``WIRES_PER_LOGICAL * k + w`` is
            rail ``w`` of the op's ``k``-th qubit. Replace the tuple to drop
            candidates; never edit a circuit in place.
        default_index: The candidate used when the router has no preference.
        diagonal: Every candidate is diagonal, so the op commutes with other
            diagonal ops.
        choice: The chosen candidate, ``None`` while undecided.
    """

    name: str
    candidates: tuple[QuantumCircuit, ...]
    default_index: int = 0
    diagonal: bool = False
    choice: int | None = None

    def __post_init__(self) -> None:
        self.check()

    def check(self) -> None:
        """Raise ``ValueError`` if the fields are inconsistent."""
        if not self.candidates:
            raise ValueError(f"{self.name}: a MultiRealizationOp needs a candidate")
        widths = {(qc.num_qubits, qc.num_clbits) for qc in self.candidates}
        if len(widths) != 1:
            raise ValueError(
                f"{self.name}: candidates differ in width: {sorted(widths)}"
            )
        if not 0 <= self.default_index < len(self.candidates):
            raise ValueError(
                f"{self.name}: default_index {self.default_index} out of range"
            )
        if self.choice is not None and not 0 <= self.choice < len(self.candidates):
            raise ValueError(f"{self.name}: choice {self.choice} out of range")

    @property
    def single_edge(self) -> bool:
        """Some candidate has all its 2-qubit gates on one pair of wires, so it fits one edge."""
        return any(
            len({frozenset(ci.qubits) for ci in real.data if len(ci.qubits) == 2}) <= 1
            for real in self.candidates
        )

    @property
    def num_qubits(self) -> int:
        return self.candidates[0].num_qubits

    @property
    def num_clbits(self) -> int:
        return self.candidates[0].num_clbits


class MultiRealizationInstruction(NamedTuple):
    """The ``CircuitInstruction`` of a ``MultiRealization``; ``qubits`` are wire indices."""

    operation: Operation | MultiRealizationOp
    qubits: tuple[int, ...]
    clbits: tuple[Clbit, ...] = ()


class Placement(NamedTuple):
    """Virtual wire ``v`` (rails, then ancillas) starts on ``initial[v]``, ends on ``final[v]``.

    ``edges`` holds the device's coupled pairs in both orientations.
    """

    initial: tuple[int, ...]
    final: tuple[int, ...]
    edges: frozenset[tuple[int, int]]


@dataclass(eq=False)
class MultiRealization(IR):
    """A program whose operations may have several candidate realizations.

    Args:
        enc: The qubit encoding.
        qregs: One register of rails per logical qubit.
        cregs: The input's classical registers, each followed by a register per
            other rail if it is measured.
        clbits: Every classical bit.
        data: The instructions, in execution order.
        output_permutation: Output rail ``v`` holds input rail ``output_permutation[v]``.
        metadata: Circuit metadata.
        placement: Set by routing.
    """

    enc: type[QubitEncoding]
    qregs: list[QuantumRegister]
    cregs: list[ClassicalRegister]
    clbits: list[Clbit]
    data: list[MultiRealizationInstruction]
    output_permutation: tuple[int, ...]
    metadata: dict[str, Any] = field(default_factory=dict)
    placement: Placement | None = None

    @property
    def rails(self) -> list[Qubit]:
        return [q for reg in self.qregs for q in reg]

    @property
    def num_wires(self) -> int:
        return (
            len(self.rails) if self.placement is None else len(self.placement.initial)
        )

    def to_circuit(self) -> QuantumCircuit:
        """The circuit with every ``MultiRealizationOp`` replaced by its chosen candidate."""
        qregs = (
            self.qregs
            if self.placement is None
            else [QuantumRegister(self.num_wires, "q")]
        )
        out = QuantumCircuit(*qregs, *self.cregs)
        out.add_bits([b for b in self.clbits if b not in set(out.clbits)])
        out.metadata = dict(self.metadata)
        wires = out.qubits
        for k, ins in enumerate(self.data):
            op = ins.operation
            if not isinstance(op, MultiRealizationOp):
                out.append(op, [wires[q] for q in ins.qubits], ins.clbits)
                continue
            if op.choice is None:
                raise TranspilerError(
                    f"instruction {k} ({op.name}) has no realization choice"
                )
            real = op.candidates[op.choice]
            for ci in real.data:
                out.append(
                    ci.operation,
                    [wires[ins.qubits[real.find_bit(q).index]] for q in ci.qubits],
                    [ins.clbits[real.find_bit(c).index] for c in ci.clbits],
                )
        return out

    def verify(self) -> None:
        """Raise ``TranspilerError`` on the first broken invariant a pass may rely on."""
        wpl = self.enc.WIRES_PER_LOGICAL
        n_logical = len(self.qregs)
        if any(reg.size != wpl for reg in self.qregs):
            _fail(f"every logical qubit needs {wpl} rails")
        if sorted(self.output_permutation) != list(range(wpl * n_logical)):
            _fail(f"output_permutation {self.output_permutation} is not a permutation")
        n = self.num_wires
        if self.placement is not None:
            if n < len(self.rails) or any(
                sorted(m) != list(range(n))
                for m in (self.placement.initial, self.placement.final)
            ):
                _fail(f"placement is not a pair of permutations of {n} physical qubits")
        clbits = set(self.clbits)
        for k, ins in enumerate(self.data):
            op = ins.operation
            where = f"instruction {k} ({op.name})"
            if (len(ins.qubits), len(ins.clbits)) != (op.num_qubits, op.num_clbits):
                _fail(
                    f"{where}: bound to {len(ins.qubits)} qubits, {len(ins.clbits)} clbits"
                )
            if len(set(ins.qubits)) != len(ins.qubits) or not all(
                0 <= q < n for q in ins.qubits
            ):
                _fail(f"{where}: bad wires {ins.qubits}")
            if not clbits.issuperset(ins.clbits):
                _fail(f"{where}: clbits outside the program")
            if not isinstance(op, MultiRealizationOp):
                _check_routable(op, len(ins.qubits), where)
                if len(ins.qubits) == 2:
                    self._check_on_edge(ins.qubits, where)
                continue
            try:
                op.check()
            except ValueError as e:
                _fail(f"{where}: {e}")
            if op.choice is not None and op.single_edge:
                real = op.candidates[op.choice]
                for ci in real.data:
                    if len(ci.qubits) == 2:
                        pair = tuple(
                            ins.qubits[real.find_bit(q).index] for q in ci.qubits
                        )
                        self._check_on_edge(pair, f"{where} choice {op.choice}")
            for r, real in enumerate(op.candidates):
                for ci in real.data:
                    _check_routable(
                        ci.operation, len(ci.qubits), f"{where} candidate {r}"
                    )
                    if op.diagonal and (
                        ci.operation.name not in DIAGONAL_GATES or ci.clbits
                    ):
                        _fail(
                            f"{where}: marked diagonal, candidate {r} has {ci.operation.name!r}"
                        )

    def _check_on_edge(self, pair: tuple[int, ...], where: str) -> None:
        if self.placement is not None and pair not in self.placement.edges:
            _fail(f"{where}: {pair} is not a device edge")


def _check_routable(op: Operation, width: int, where: str) -> None:
    """The router sees gates on at most 2 wires; a wider op may only be control flow of 1-qubit gates."""
    if width <= 2:
        return
    if not isinstance(op, ControlFlowOp) or any(
        len(ci.qubits) >= 2 or isinstance(ci.operation, ControlFlowOp)
        for block in op.blocks
        for ci in block.data
    ):
        _fail(f"{where}: {width}-qubit {op.name!r} hides gates from the router")


def _fail(msg: str) -> NoReturn:
    raise TranspilerError(f"invalid MultiRealization: {msg}")
