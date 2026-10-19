"""``MultiRealization -> MultiRealization`` passes of the ``multi_realization`` stage.

``PrismRouting`` (``prism.routing``) is the stage's required pass; the passes here
run before or after it.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, replace
from itertools import permutations
from typing import TYPE_CHECKING, NamedTuple

from qiskit.circuit.library import PermutationGate
from qiskit.exceptions import QiskitError
from qiskit.passmanager import GenericPass
from qiskit.quantum_info import Operator
from qiskit.transpiler import TranspilerError

from prism.ir import (
    MultiRealization,
    MultiRealizationInstruction,
    MultiRealizationOp,
    commuting_predecessors,
    list_schedule,
)
from prism.metrics import is_free

if TYPE_CHECKING:
    from collections.abc import Hashable, Sequence

    from qiskit.circuit import QuantumCircuit

__all__ = ["ElideRailExchanges", "RetimeDiagonals"]


class ElideRailExchanges(GenericPass[MultiRealization, MultiRealization]):
    """Drop every op that only permutes its qubit's rails, and relabel the rails after it.

    The rail-level ``ElideLogicalPermutations``: in dual rail, logical X (and
    ``rx(pi)``) is the exchange of the two rails. An op is elided when every
    candidate is the same permutation of the rails of one logical qubit, up to
    global phase. Later instructions, measurements included, act on the
    relabelled rails, and the net permutation goes into ``output_permutation``,
    hence into the output's final layout. Runs before routing.
    """

    def run(self, passmanager_ir: MultiRealization) -> MultiRealization:
        """Elide the rail permutations of the unplaced ``passmanager_ir``."""
        ir = passmanager_ir
        if ir.placement is not None:
            raise TranspilerError("ElideRailExchanges runs before routing")
        wpl = ir.enc.WIRES_PER_LOGICAL
        cur = list(range(len(ir.rails)))  # IR rail -> rail it now sits on
        data = []
        for ins in ir.data:
            perm = (
                _rail_permutation(ins.operation, wpl)
                if isinstance(ins.operation, MultiRealizationOp)
                else None
            )
            if perm is None:
                data.append(ins._replace(qubits=tuple(cur[q] for q in ins.qubits)))
                continue
            # Local wire k receives local wire perm[k]'s content.
            moved = [cur[q] for q in ins.qubits]
            for k, q in enumerate(ins.qubits):
                cur[q] = moved[perm[k]]
        out = list(ir.output_permutation)
        for r, c in enumerate(cur):
            out[c] = ir.output_permutation[r]
        ir.data = data
        ir.output_permutation = tuple(out)
        return ir


def _rail_permutation(op: MultiRealizationOp, wpl: int) -> tuple[int, ...] | None:
    """The ``PermutationGate`` pattern every candidate equals up to global phase, or ``None``.

    Only for an op on one logical qubit, with no clbits, whose candidates are unitary.
    """
    if op.diagonal or op.num_qubits != wpl or op.num_clbits:
        return None
    try:
        ops = [Operator(qc) for qc in op.candidates]
    except (QiskitError, TypeError):  # non-unitary, control flow, or unbound
        return None
    perms = {
        next((p for p in permutations(range(wpl)) if u.equiv(PermutationGate(p))), None)
        for u in ops
    }
    return perms.pop() if len(perms) == 1 else None


#: One gate as depth counts it: the wires it orders, and 1 unless it is free.
Gate = tuple[tuple["Hashable", ...], int]
#: A candidate's gates as ``Gate`` s on its local wires: qubit indices, clbit indices, weight.
Template = tuple[tuple[tuple[int, ...], tuple[int, ...], int], ...]


def _template(real: QuantumCircuit) -> Template:
    """The gates of candidate ``real`` on its local wires.

    Free one-qubit gates neither take a layer nor order wires, so they are left out.
    """
    return tuple(
        (
            tuple(real.find_bit(q).index for q in ci.qubits),
            tuple(real.find_bit(c).index for c in ci.clbits),
            0 if is_free(ci.operation) else 1,
        )
        for ci in real.data
        if len(ci.qubits) + len(ci.clbits) > 1 or not is_free(ci.operation)
    )


def _times(
    program: Sequence[Sequence[Gate]],
) -> tuple[list[dict], list[dict], list[bool], int]:
    """Heads and tails of each instruction of ``program``, and its depth.

    Per instruction: the time each of its wires is free after it (ASAP), the
    longest path from each of its wires to the end, and whether one of its gates
    is on a critical path. The depth is ``CircuitMetrics.depth``.
    """
    ends, tails, crit = [], [{}] * len(program), [False] * len(program)
    end: dict = {}
    starts = []
    for gates in program:
        ss = []
        for ws, w in gates:
            s = max((end.get(x, 0) for x in ws), default=0)
            ss.append(s)
            for x in ws:
                end[x] = s + w
        starts.append(ss)
        ends.append({x: end[x] for ws, _ in gates for x in ws})
    depth = max(end.values(), default=0)
    nxt: dict = {}
    for k in range(len(program) - 1, -1, -1):
        for (ws, w), s in zip(reversed(program[k]), reversed(starts[k])):
            q = w + max((nxt.get(x, 0) for x in ws), default=0)
            crit[k] |= bool(w) and s + q == depth
            for x in ws:
                nxt[x] = q
        tails[k] = {x: nxt[x] for ws, _ in program[k] for x in ws}
    return ends, tails, crit, depth


def _list_schedule(
    data: Sequence[MultiRealizationInstruction],
    gates: Sequence[Sequence[Gate]],
    movable: set[int],
    vpreds: dict[int, list[int]],
) -> list[int]:
    """An order of ``data`` by critical-path list scheduling, as ``RescheduleCommutingDiagonals``.

    Diagonal ``MultiRealizationOp`` s commute on their physical wires: the
    ``movable`` ones on their gate's two qubits, the others on all their rails.
    ``vpreds`` adds the dependencies on virtual wires. Routing SWAPs keep their
    order, so the layout after ``t`` SWAPs is unchanged.
    """
    wires = [
        {x for ws, _ in gates[k] for x in ws}
        if k in movable
        else {*ins.qubits, *ins.clbits}
        for k, ins in enumerate(data)
    ]
    preds = commuting_predecessors(
        wires,
        [
            isinstance(ins.operation, MultiRealizationOp) and ins.operation.diagonal
            for ins in data
        ],
    )
    swaps = [k for k, ins in enumerate(data) if _is_swap(ins)]
    for a, b in zip(swaps, swaps[1:]):
        preds[b].add(a)
    for k, ps in vpreds.items():
        preds[k].update(ps)
    return list_schedule(
        preds, wires, [max((w for _, w in g), default=0) for g in gates]
    )


def _is_swap(ins: MultiRealizationInstruction) -> bool:
    return (
        not isinstance(ins.operation, MultiRealizationOp)
        and ins.operation.name == "swap"
    )


@dataclass
class _Schedule:
    """An order of the instructions, with the physical qubits, choice and gates of each."""

    order: list[int]
    qubits: list[tuple[int, ...]]
    choice: list[int | None]
    gates: list[tuple[Gate, ...]]


class _Analysis(NamedTuple):
    """``_times`` of a schedule, and where each of its ops sits."""

    ends: list[dict]
    tails: list[dict]
    crit: list[bool]
    depth: int
    on_wire: dict[Hashable, list[int]]  # wire -> slots of the ops on it
    n_swaps: list[int]  # slot -> routing SWAPs before it
    pos: dict[int, int]  # instruction -> slot


class RetimeDiagonals(GenericPass[MultiRealization, MultiRealization]):
    """Move diagonal ``MultiRealizationOp`` s off the critical path, across routing SWAPs.

    Reads a placed program. Routing SWAPs, the other ops, the order of the
    SWAPs and the placement stay. A diagonal op whose every candidate is one
    two-qubit gate (plus free one-qubit gates) may move to any slot between its
    predecessors and successors under ``commuting_predecessors`` on virtual
    wires, at the physical qubits its rails occupy there, with a candidate whose
    gate sits on a device edge.

    The search is critical-path reinsertion with heads and tails, as in
    job-shop local search. With the ASAP head and the tail (longest path to the
    end) of each op, a critical diagonal op is reinserted at the (slot,
    candidate) of the least path ``head + 1 + tail`` through it, which is exact
    for one move; the move is kept if (depth, number of critical ops) drops.
    It runs from two starts, the routed order and a critical-path list
    schedule of it, and keeps the shallower. Depth is ``CircuitMetrics.depth``.
    """

    def run(self, passmanager_ir: MultiRealization) -> MultiRealization:
        """Retime the diagonal ops; the result passes ``verify``."""
        ir = passmanager_ir
        if ir.placement is None:
            raise TranspilerError(
                "RetimeDiagonals needs a placed program; run PrismRouting first"
            )
        rt = _Retime(ir)
        routed = rt.schedule(list(range(len(ir.data))))
        order = _list_schedule(ir.data, routed.gates, rt.movable, rt.preds)
        listed = rt.schedule(order)
        routed_depth, listed_depth = rt.polish(routed).depth, rt.polish(listed).depth
        best = routed if routed_depth <= listed_depth else listed
        out = []
        for k in best.order:
            ins = ir.data[k]
            if k in rt.movable:
                op = replace(ins.operation, choice=best.choice[k])
                ins = ins._replace(operation=op, qubits=best.qubits[k])
            out.append(ins)
        return replace(ir, data=out)


class _Retime:
    """One ``RetimeDiagonals`` run: the placed program's fixed facts, and the local search."""

    def __init__(self, ir: MultiRealization) -> None:
        self.data = data = ir.data
        self.edges = ir.placement.edges
        self.swap = [_is_swap(ins) for ins in data]
        # The layout (v2p) after t routing SWAPs, and the virtual wires of each instruction.
        v2p = list(ir.placement.initial)
        p2v = [0] * len(v2p)
        for v, p in enumerate(v2p):
            p2v[p] = v
        self.layouts, self.virt = [tuple(v2p)], []
        for ins, s in zip(data, self.swap):
            self.virt.append(tuple(p2v[q] for q in ins.qubits))
            if s:
                a, b = ins.qubits
                p2v[a], p2v[b] = p2v[b], p2v[a]
                v2p[p2v[a]], v2p[p2v[b]] = a, b
                self.layouts.append(tuple(v2p))
        rest = [k for k in range(len(data)) if not self.swap[k]]
        deps = commuting_predecessors(
            [(*self.virt[k], *data[k].clbits) for k in rest],
            [
                isinstance(data[k].operation, MultiRealizationOp)
                and data[k].operation.diagonal
                for k in rest
            ],
        )
        self.preds = {k: [rest[j] for j in ds] for k, ds in zip(rest, deps)}
        self.succs: dict[int, list[int]] = {k: [] for k in rest}
        for k, ps in self.preds.items():
            for p in ps:
                self.succs[p].append(k)
        self.templates = [
            [_template(real) for real in op.candidates]
            if isinstance(op := ins.operation, MultiRealizationOp)
            else None
            for ins in data
        ]
        self.movable = {
            k
            for k in rest
            if isinstance(op := data[k].operation, MultiRealizationOp)
            and op.diagonal
            and all(len(t) == 1 and len(t[0][0]) == 2 for t in self.templates[k])
        }

    def schedule(self, order: list[int]) -> _Schedule:
        """``order`` with the routed choices, each movable op on the rails' qubits at its slot.

        A movable op crosses only SWAPs off its gate's qubits, so its gates stay.
        """
        qubits = [ins.qubits for ins in self.data]
        t = 0
        for k in order:
            t += self.swap[k]
            if k in self.movable:
                qubits[k] = tuple(self.layouts[t][v] for v in self.virt[k])
        choice = [getattr(ins.operation, "choice", None) for ins in self.data]
        gates = [self.gates(k, q, r) for k, (q, r) in enumerate(zip(qubits, choice))]
        return _Schedule(order, qubits, choice, gates)

    def gates(self, k: int, qubits: Sequence[int], r: int | None) -> tuple[Gate, ...]:
        """The gates of instruction ``k`` on physical ``qubits`` with choice ``r``."""
        ins, templates = self.data[k], self.templates[k]
        if templates is None:
            return (((*qubits, *ins.clbits), 0 if is_free(ins.operation) else 1),)
        return tuple(
            ((*(qubits[i] for i in qs), *(ins.clbits[i] for i in cs)), w)
            for qs, cs, w in templates[r]
        )

    def analyse(self, sch: _Schedule) -> _Analysis:
        """``_times`` of ``sch``, and where each of its ops sits."""
        ends, tails, crit, depth = _times([sch.gates[k] for k in sch.order])
        on_wire: dict = {}
        for j, e in enumerate(ends):
            for x in e:
                on_wire.setdefault(x, []).append(j)
        n_swaps = [0]
        for k in sch.order:
            n_swaps.append(n_swaps[-1] + self.swap[k])
        pos = {k: j for j, k in enumerate(sch.order)}
        return _Analysis(ends, tails, crit, depth, on_wire, n_swaps, pos)

    def best_slot(
        self, sch: _Schedule, i: int, a: _Analysis
    ) -> tuple[int, int, tuple[int, ...], int]:
        """``(path, slot, qubits, choice)`` of the least path through ``sch.order[i]``, moved."""
        k = sch.order[i]
        lo = max((a.pos[p] for p in self.preds[k]), default=-1) + 1
        hi = min((a.pos[s] for s in self.succs[k]), default=len(sch.order))
        best = None
        # ponytail: scans every slot of the window, O(window * candidates * log n) per move
        for j in range(lo, hi + 1):
            qubits = tuple(self.layouts[a.n_swaps[j]][v] for v in self.virt[k])
            for r in range(len(self.templates[k])):
                ((ws, w),) = self.gates(k, qubits, r)
                if ws not in self.edges:
                    continue
                head = tail = 0
                for x in ws:  # the neighbours of slot j on wire x, other than k itself
                    lst = a.on_wire.get(x, ())
                    b = bisect_left(lst, j)
                    p = b - 1 - (b > 0 and lst[b - 1] == i)
                    if p >= 0:
                        head = max(head, a.ends[lst[p]][x])
                    c = b + (b < len(lst) and lst[b] == i)
                    if c < len(lst):
                        tail = max(tail, a.tails[lst[c]][x])
                if best is None or head + w + tail < best[0]:
                    best = (head + w + tail, j, qubits, r)
        return best

    def polish(self, sch: _Schedule) -> _Analysis:
        """Reinsert critical diagonal ops of ``sch`` while (depth, critical ops) drops."""
        a = self.analyse(sch)
        tried: set[int] = set()
        while True:
            for i, k in enumerate(sch.order):
                if not a.crit[i] or k not in self.movable or k in tried:
                    continue
                tried.add(k)
                path, j, qubits, r = self.best_slot(sch, i, a)
                if path >= a.depth:
                    continue
                saved = sch.order[:], sch.qubits[k], sch.choice[k], sch.gates[k]
                sch.order.insert(j - (j > i), sch.order.pop(i))
                sch.qubits[k], sch.choice[k] = qubits, r
                sch.gates[k] = self.gates(k, qubits, r)
                new = self.analyse(sch)
                if (new.depth, sum(new.crit)) < (a.depth, sum(a.crit)):
                    a = new
                    tried.clear()
                    break
                sch.order, sch.qubits[k], sch.choice[k], sch.gates[k] = saved
            else:
                return a
