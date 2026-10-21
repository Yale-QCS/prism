"""``multi_realization`` passes that run before and after ``PrismRouting``."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import replace
from itertools import permutations
from typing import TYPE_CHECKING, NamedTuple

from qiskit.circuit.library import PermutationGate
from qiskit.exceptions import QiskitError
from qiskit.passmanager import GenericPass
from qiskit.quantum_info import Operator
from qiskit.transpiler import TranspilerError

from prism.ir import (
    RAILS,
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


class ElideRailExchanges(GenericPass[MultiRealization, MultiRealization]):
    """Drop ops that only permute one qubit's rails, such as dual-rail X, and relabel the rails.

    The net permutation goes into ``output_permutation``, and so into the final layout.
    """

    def run(self, passmanager_ir: MultiRealization) -> MultiRealization:
        ir = passmanager_ir
        if ir.placement is not None:
            raise TranspilerError("ElideRailExchanges runs before routing")
        cur = list(range(len(ir.rails)))  # IR rail -> rail it now sits on
        data = []
        for ins in ir.data:
            perm = (
                _rail_permutation(ins.operation)
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


def _rail_permutation(op: MultiRealizationOp) -> tuple[int, ...] | None:
    """The rail permutation every candidate equals up to global phase, if any."""
    if op.diagonal or op.num_qubits != RAILS or op.num_clbits:
        return None
    try:
        ops = [Operator(qc) for qc in op.candidates]
    except (QiskitError, TypeError):  # non-unitary, control flow, or unbound
        return None
    perms = {
        next(
            (p for p in permutations(range(RAILS)) if u.equiv(PermutationGate(p))), None
        )
        for u in ops
    }
    return perms.pop() if len(perms) == 1 else None


def _template(
    real: QuantumCircuit,
) -> tuple[tuple[tuple[int, ...], tuple[int, ...], int], ...]:
    """``(qubit indices, clbit indices, depth weight)`` per gate of ``real``.

    Free 1-qubit gates are left out: they neither take time nor order wires.
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


def _is_swap(ins: MultiRealizationInstruction) -> bool:
    return (
        not isinstance(ins.operation, MultiRealizationOp)
        and ins.operation.name == "swap"
    )


class _Times(NamedTuple):
    """The timing of an instruction order, by slot.

    A gate is ``(wires, weight)``; a wire is a physical qubit or a clbit.
    """

    ends: list[dict]  # slot -> wire -> when the slot's last gate on it ends
    tails: list[dict]  # slot -> wire -> longest path from the slot's first gate on it
    crit: list[bool]  # slot is on a longest path
    depth: int
    on_wire: dict[Hashable, list[int]]  # wire -> the slots on it
    n_swaps: list[int]  # slot -> routing SWAPs before it
    pos: dict[int, int]  # instruction -> slot


class RetimeDiagonals(GenericPass[MultiRealization, MultiRealization]):
    """Move diagonal two-qubit ops off the critical path, across routing SWAPs.

    Routing SWAPs and the placement stay. A critical diagonal op moves to the
    slot and candidate with the shortest path through it, as in job-shop local
    search, while the depth or the number of critical ops drops. The search
    starts from the routed order and from a list schedule of it, and keeps the
    shallower result.
    """

    def run(self, passmanager_ir: MultiRealization) -> MultiRealization:
        ir = passmanager_ir
        if ir.placement is None:
            raise TranspilerError(
                "RetimeDiagonals needs a placed program; run PrismRouting first"
            )
        search = _Retime(ir)
        routed = search.polish(range(len(ir.data)))
        listed = search.polish(search.list_schedule())
        _, order, qubits, choice = min(routed, listed, key=lambda result: result[0])
        out = []
        for k in order:
            ins = ir.data[k]
            if k in search.movable:
                op = replace(ins.operation, choice=choice[k])
                ins = ins._replace(operation=op, qubits=qubits[k])
            out.append(ins)
        return replace(ir, data=out)


class _Retime:
    """The local search of one ``RetimeDiagonals`` run.

    A schedule is an instruction order with each instruction's physical qubits
    and choice, both indexed by instruction.
    """

    def __init__(self, ir: MultiRealization) -> None:
        self.data = data = ir.data
        self.edges = ir.placement.edges
        self.swap = [_is_swap(ins) for ins in data]
        # The layout after t routing SWAPs, and each instruction's virtual wires.
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
            [data[k].diagonal for k in rest],
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
            if data[k].diagonal
            and all(len(t) == 1 and len(t[0][0]) == 2 for t in self.templates[k])
        }

    def gates(self, k: int, qubits: Sequence[int], r: int | None) -> tuple:
        """Instruction ``k``'s gates with choice ``r`` on ``qubits``."""
        ins, templates = self.data[k], self.templates[k]
        if templates is None:
            return (((*qubits, *ins.clbits), 0 if is_free(ins.operation) else 1),)
        return tuple(
            ((*(qubits[i] for i in qs), *(ins.clbits[i] for i in cs)), w)
            for qs, cs, w in templates[r]
        )

    def start(self, order: Sequence[int]) -> tuple[list, list, list]:
        """Qubits, choices and gates of ``order``, each movable op on its rails' qubits at its slot."""
        qubits = [ins.qubits for ins in self.data]
        t = 0
        for k in order:
            t += self.swap[k]
            if k in self.movable:
                qubits[k] = tuple(self.layouts[t][v] for v in self.virt[k])
        choice = [getattr(ins.operation, "choice", None) for ins in self.data]
        gates = [self.gates(k, q, r) for k, (q, r) in enumerate(zip(qubits, choice))]
        return qubits, choice, gates

    def list_schedule(self) -> list[int]:
        """``list_schedule`` of the routed order, keeping routing SWAPs in order and ``preds``."""
        _, _, gates = self.start(range(len(self.data)))
        wires = [
            {x for ws, _ in gates[k] for x in ws}
            if k in self.movable
            else {*ins.qubits, *ins.clbits}
            for k, ins in enumerate(self.data)
        ]
        preds = commuting_predecessors(wires, [ins.diagonal for ins in self.data])
        swaps = [k for k, s in enumerate(self.swap) if s]
        for a, b in zip(swaps, swaps[1:]):
            preds[b].add(a)
        for k, ps in self.preds.items():
            preds[k].update(ps)
        return list_schedule(
            preds, wires, [max((w for _, w in g), default=0) for g in gates]
        )

    def times(self, order: list[int], gates: list[tuple]) -> _Times:
        program = [gates[k] for k in order]
        ends, tails, crit = [], [{}] * len(program), [False] * len(program)
        end: dict = {}
        starts = []
        for slot in program:
            ss = []
            for ws, w in slot:
                s = max((end.get(x, 0) for x in ws), default=0)
                ss.append(s)
                for x in ws:
                    end[x] = s + w
            starts.append(ss)
            ends.append({x: end[x] for ws, _ in slot for x in ws})
        depth = max(end.values(), default=0)
        nxt: dict = {}
        for j in range(len(program) - 1, -1, -1):
            for (ws, w), s in zip(reversed(program[j]), reversed(starts[j])):
                q = w + max((nxt.get(x, 0) for x in ws), default=0)
                crit[j] |= bool(w) and s + q == depth
                for x in ws:
                    nxt[x] = q
            tails[j] = {x: nxt[x] for ws, _ in program[j] for x in ws}
        on_wire: dict = {}
        for j, e in enumerate(ends):
            for x in e:
                on_wire.setdefault(x, []).append(j)
        n_swaps = [0]
        for k in order:
            n_swaps.append(n_swaps[-1] + self.swap[k])
        pos = {k: j for j, k in enumerate(order)}
        return _Times(ends, tails, crit, depth, on_wire, n_swaps, pos)

    def best_slot(
        self, order: list[int], i: int, a: _Times
    ) -> tuple[int, int, tuple[int, ...], int]:
        """``(path, slot, qubits, choice)`` of the shortest path through ``order[i]`` when moved."""
        k = order[i]
        lo = max((a.pos[p] for p in self.preds[k]), default=-1) + 1
        hi = min((a.pos[s] for s in self.succs[k]), default=len(order))
        best = None
        for j in range(lo, hi + 1):
            qubits = tuple(self.layouts[a.n_swaps[j]][v] for v in self.virt[k])
            for r in range(len(self.templates[k])):
                ((ws, w),) = self.gates(k, qubits, r)
                if ws not in self.edges:
                    continue
                head = tail = 0
                for x in ws:  # neighbours of slot j on wire x, skipping k itself
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

    def polish(self, order: Sequence[int]) -> tuple[int, list[int], list, list]:
        """``(depth, order, qubits, choices)`` after moving critical ops while (depth, critical ops) drops."""
        order = list(order)
        qubits, choice, gates = self.start(order)
        a = self.times(order, gates)
        tried: set[int] = set()
        while True:
            for i, k in enumerate(order):
                if not a.crit[i] or k not in self.movable or k in tried:
                    continue
                tried.add(k)
                path, j, q, r = self.best_slot(order, i, a)
                if path >= a.depth:
                    continue
                saved = order[:], qubits[k], choice[k], gates[k]
                order.insert(j - (j > i), order.pop(i))
                qubits[k], choice[k], gates[k] = q, r, self.gates(k, q, r)
                new = self.times(order, gates)
                if (new.depth, sum(new.crit)) < (a.depth, sum(a.crit)):
                    a = new
                    tried.clear()
                    break
                order[:], qubits[k], choice[k], gates[k] = saved
            else:
                return a.depth, order, qubits, choice
