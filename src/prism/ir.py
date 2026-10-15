"""``MultiRealization``: prism's IR between the logical and the physical DAG stages.

A ``MultiRealization`` is an ordered instruction list, like a ``QuantumCircuit``.
Each instruction's operation is either a regular Qiskit ``Operation`` or a
``MultiRealizationOp``: one logical operation with several candidate
realizations. Passes narrow ``candidates`` (constraints) and set ``choice``
(the decision). The ``placement`` annotation says where the program sits on
the device.

Wire convention: rail ``w`` of logical qubit ``i`` is wire ``WIRES_PER_LOGICAL * i + w``.
While ``placement`` is ``None``, instruction qubits are those rail indices. Once
placed, they are physical qubits: a routing SWAP is then a regular ``swap``, and
a sub-routed gate is its chosen realization's regular operations with SWAPs
between them.
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
    from prism.encodings.base import QubitEncoding

__all__ = [
    "MultiRealization",
    "MultiRealizationInstruction",
    "MultiRealizationOp",
    "Placement",
]

#: Gate names a ``diagonal`` realization may contain.
DIAGONAL_GATES = frozenset(
    {"rz", "crz", "z", "s", "sdg", "t", "tdg", "p", "cp", "cz", "rzz"}
)


@dataclass(frozen=True, eq=False)
class MultiRealizationOp:
    """A logical operation with its candidate realizations.

    Not a Qiskit ``Operation``: no stock pass can take it.

    Args:
        name: The logical operation's name.
        candidates: Circuits on block-local wires; local wire
            ``WIRES_PER_LOGICAL * k + w`` is rail ``w`` of the op's ``k``-th
            logical qubit. All have the same width. Treat them as immutable.
        default_index: The encoding's canonical candidate; the router's fallback.
        diagonal: Every candidate is diagonal, so the op commutes with every other
            diagonal op. The router reorders such ops.
        choice: Index of the chosen candidate, or ``None`` while undecided.
    """

    name: str
    candidates: tuple[QuantumCircuit, ...]
    default_index: int = 0
    diagonal: bool = False
    choice: int | None = None

    def __post_init__(self) -> None:
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

    @property
    def num_qubits(self) -> int:
        """Block-local width every candidate shares."""
        return self.candidates[0].num_qubits

    @property
    def num_clbits(self) -> int:
        """Classical width every candidate shares."""
        return self.candidates[0].num_clbits


class MultiRealizationInstruction(NamedTuple):
    """An operation bound to wires: the ``CircuitInstruction`` of a ``MultiRealization``.

    Args:
        operation: A regular Qiskit operation or a ``MultiRealizationOp``.
        qubits: Wire indices (rails, or physical qubits once placed).
        clbits: The program's classical bits, positional against the operation's.
    """

    operation: Operation | MultiRealizationOp
    qubits: tuple[int, ...]
    clbits: tuple[Clbit, ...] = ()


class Placement(NamedTuple):
    """Where a program sits on the device.

    Virtual wire ``v`` (the rails, then ancillas) starts on physical qubit
    ``initial[v]`` and ends on ``final[v]``. Both have one entry per physical qubit.
    """

    initial: tuple[int, ...]
    final: tuple[int, ...]


@dataclass(eq=False)
class MultiRealization(IR):
    """Program with candidate realizations per operation.

    Args:
        enc: The qubit encoding.
        qregs: One register of ``WIRES_PER_LOGICAL`` rails per logical qubit.
        cregs: The input's classical registers, then the herald register.
        clbits: Every classical bit, register or loose.
        data: The instructions, in a valid execution order.
        logical_output_permutation: Output logical position ``i`` holds input
            qubit ``logical_output_permutation[i]`` (SWAPs elided before expansion).
        metadata: Circuit metadata, carried to the output.
        placement: Set by routing; ``None`` before.
    """

    enc: type[QubitEncoding]
    qregs: list[QuantumRegister]
    cregs: list[ClassicalRegister]
    clbits: list[Clbit]
    data: list[MultiRealizationInstruction]
    logical_output_permutation: tuple[int, ...]
    metadata: dict[str, Any] = field(default_factory=dict)
    placement: Placement | None = None

    @property
    def qubits(self) -> list[Qubit]:
        """The rails; rail index ``v`` is ``qubits[v]``."""
        return [q for reg in self.qregs for q in reg]

    @property
    def num_wires(self) -> int:
        """Rails before placement, physical qubits after."""
        return (
            len(self.qubits) if self.placement is None else len(self.placement.initial)
        )

    def __repr__(self) -> str:
        decided = sum(
            isinstance(ins.operation, MultiRealizationOp)
            and ins.operation.choice is not None
            for ins in self.data
        )
        multi = sum(isinstance(ins.operation, MultiRealizationOp) for ins in self.data)
        return (
            f"<MultiRealization {self.enc.__name__} logical={len(self.qregs)} "
            f"instructions={len(self.data)} decided={decided}/{multi} "
            f"placed={self.placement is not None}>"
        )

    def to_circuit(self) -> QuantumCircuit:
        """The circuit with every ``MultiRealizationOp`` replaced by its chosen candidate.

        Wires are the rails (unplaced) or ``QuantumRegister(num_physical, "q")``
        (placed). Classical registers and loose bits appear in order of first use.

        Raises:
            TranspilerError: if a ``MultiRealizationOp`` has no choice.
        """
        qregs = (
            self.qregs
            if self.placement is None
            else [QuantumRegister(self.num_wires, "q")]
        )
        out = QuantumCircuit(*qregs)
        out.metadata = dict(self.metadata)
        wires = out.qubits
        emitted: list[tuple[Operation, list[Qubit], tuple[Clbit, ...]]] = []
        for k, ins in enumerate(self.data):
            op = ins.operation
            if not isinstance(op, MultiRealizationOp):
                emitted.append((op, [wires[q] for q in ins.qubits], ins.clbits))
                continue
            if op.choice is None:
                raise TranspilerError(
                    f"instruction {k} ({op.name} on wires {ins.qubits}) has no realization "
                    "choice; run a pass that decides it (PrismRouting) first"
                )
            real = op.candidates[op.choice]
            for ci in real.data:
                emitted.append(
                    (
                        ci.operation,
                        [wires[ins.qubits[real.find_bit(q).index]] for q in ci.qubits],
                        tuple(ins.clbits[real.find_bit(c).index] for c in ci.clbits),
                    )
                )
        creg_of: dict[Clbit, ClassicalRegister] = {}
        for creg in self.cregs:
            for bit in creg:
                creg_of.setdefault(bit, creg)
        seen: set[Clbit | ClassicalRegister] = set()
        for _, _, clbits in emitted:
            for bit in clbits:
                reg = creg_of.get(bit)
                if reg is None and bit not in seen:
                    out.add_bits([bit])
                    seen.add(bit)
                elif reg is not None and reg not in seen:
                    out.add_register(reg)
                    seen.add(reg)
        for op, qubits, clbits in emitted:
            out.append(op, qubits, clbits)
        return out

    def verify(self) -> None:
        """Check the invariants every pass may rely on.

        Raises:
            TranspilerError: naming the first broken invariant.
        """
        wpl = self.enc.WIRES_PER_LOGICAL
        n_logical = len(self.qregs)
        if any(reg.size != wpl for reg in self.qregs):
            _fail(f"every logical qubit needs {wpl} rails")
        if sorted(self.logical_output_permutation) != list(range(n_logical)):
            _fail(
                f"logical_output_permutation {self.logical_output_permutation} is not a permutation"
            )
        n = self.num_wires
        if self.placement is not None:
            if n < len(self.qubits) or any(
                sorted(m) != list(range(n)) for m in self.placement
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
                continue
            if op.choice is not None and not 0 <= op.choice < len(op.candidates):
                _fail(f"{where}: choice {op.choice} out of range")
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


def _check_routable(op: Operation, width: int, where: str) -> None:
    """The router sees 2-qubit gates only: wider operations must hold none."""
    if width <= 2 or op.name == "barrier":
        return
    if not isinstance(op, ControlFlowOp):
        _fail(
            f"{where}: {width}-qubit {op.name!r}; the router needs gates on at most 2 wires"
        )
    for block in op.blocks:
        for ci in block.data:
            if (
                len(ci.qubits) >= 2
                and ci.operation.name != "barrier"
                or isinstance(ci.operation, ControlFlowOp)
            ):
                _fail(
                    f"{where}: {op.name!r} over {width} wires holds gates the router cannot see"
                )


def _fail(msg: str) -> NoReturn:
    raise TranspilerError(f"invalid MultiRealization: {msg}")
