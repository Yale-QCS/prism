"""``MultiRealization -> MultiRealization`` passes of the ``multi_realization`` stage.

``PrismRouting`` (``prism.routing``) is the stage's required pass; the passes here
run before or after it.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import numpy as np
from qiskit.exceptions import QiskitError
from qiskit.passmanager import GenericPass
from qiskit.quantum_info import Operator
from qiskit.transpiler import TranspilerError

from prism.ir import (
    MultiRealization,
    MultiRealizationInstruction,
    MultiRealizationOp,
    commuting_predecessors,
)
from prism.metrics import is_free

if TYPE_CHECKING:
    from collections.abc import Hashable, Sequence

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
            # Local wire k's content moves to local wire perm[k].
            moved = [cur[q] for q in ins.qubits]
            for k, q in enumerate(ins.qubits):
                cur[ins.qubits[perm[k]]] = moved[k]
        out = list(ir.output_permutation)
        for r, c in enumerate(cur):
            out[c] = ir.output_permutation[r]
        ir.data = data
        ir.output_permutation = tuple(out)
        return ir


def _rail_permutation(op: MultiRealizationOp, wpl: int) -> tuple[int, ...] | None:
    """The permutation ``k -> perm[k]`` of local wires shared by every candidate, or ``None``.

    Only for an op on one logical qubit, with no clbits, whose candidates are
    unitary circuits equal to one wire permutation up to global phase.
    """
    if op.diagonal or op.num_qubits != wpl or op.num_clbits:
        return None
    perms = set()
    for qc in op.candidates:
        try:
            u = Operator(qc).data
        except (QiskitError, TypeError):  # non-unitary, control flow, or unbound
            return None
        cols = np.abs(u[:, [1 << k for k in range(wpl)]]).argmax(axis=0)
        perm = tuple(int(c).bit_length() - 1 for c in cols)
        if sorted(perm) != list(range(wpl)):
            return None
        rows = [
            sum(1 << perm[k] for k in range(wpl) if x >> k & 1) for x in range(1 << wpl)
        ]
        diag = u[rows, range(1 << wpl)]
        if not np.allclose(diag, diag[0]) or not np.isclose(abs(diag[0]), 1):
            return None
        perms.add(perm)
    return perms.pop() if len(perms) == 1 else None


#: One gate as depth counts it: the wires it orders, and 1 unless it is free.
Gate = tuple[tuple["Hashable", ...], int]


def _gates(
    ins: MultiRealizationInstruction, qubits: Sequence[int], r: int | None
) -> tuple[Gate, ...]:
    """The gates of ``ins`` on physical ``qubits`` with choice ``r``.

    Free one-qubit gates neither take a layer nor order wires, so they are left out.
    """
    op = ins.operation
    if not isinstance(op, MultiRealizationOp):
        return (((*qubits, *ins.clbits), 0 if is_free(op) else 1),)
    real = op.candidates[r]
    return tuple(
        (
            (
                *(qubits[real.find_bit(q).index] for q in ci.qubits),
                *(ins.clbits[real.find_bit(c).index] for c in ci.clbits),
            ),
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
    n = len(data)
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
    succs: list[list[int]] = [[] for _ in range(n)]
    for k, ps in enumerate(preds):
        for p in ps:
            succs[p].append(k)
    weight = [max((w for _, w in g), default=0) for g in gates]
    cp = [0] * n
    for k in range(n - 1, -1, -1):
        cp[k] = weight[k] + max((cp[s] for s in succs[k]), default=0)
    done: dict[int, int] = {}
    wire_free: dict = {}
    remaining = set(range(n))
    order: list[int] = []
    while remaining:
        ready = sorted(
            (k for k in remaining if preds[k] <= done.keys()), key=lambda k: (-cp[k], k)
        )
        for k in ready:
            start = max(
                [done[p] for p in preds[k]]
                + [wire_free.get(w, 0) for w in wires[k]]
                + [0]
            )
            done[k] = start + weight[k]
            for w in wires[k]:
                wire_free[w] = done[k]
            remaining.discard(k)
        order += sorted(ready, key=lambda k: (done[k] - weight[k], k))
    return order


def _is_swap(ins: MultiRealizationInstruction) -> bool:
    return (
        not isinstance(ins.operation, MultiRealizationOp)
        and ins.operation.name == "swap"
    )


class _Schedule:
    """An order of the instructions, with the physical qubits and choice of each."""

    def __init__(
        self, data: Sequence[MultiRealizationInstruction], order: list[int]
    ) -> None:
        self.order = order
        self.qubits = [ins.qubits for ins in data]
        self.choice = [getattr(ins.operation, "choice", None) for ins in data]
        self.gates = [_gates(ins, ins.qubits, r) for ins, r in zip(data, self.choice)]


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
        self.movable = {
            k
            for k in rest
            if isinstance(op := data[k].operation, MultiRealizationOp)
            and op.diagonal
            and all(
                len(g := _gates(data[k], data[k].qubits, r)) == 1 and len(g[0][0]) == 2
                for r in range(len(op.candidates))
            )
        }
        routed = _Schedule(data, list(range(len(data))))
        listed = _Schedule(data, [])
        listed.order = _list_schedule(data, listed.gates, self.movable, self.preds)
        t = 0
        for k in listed.order:
            t += self.swap[k]
            if k in self.movable:
                listed.qubits[k] = tuple(self.layouts[t][v] for v in self.virt[k])
        best = min((routed, listed), key=self._polish)
        out = []
        for k in best.order:
            ins = data[k]
            if k in self.movable:
                op = replace(ins.operation, choice=best.choice[k])
                ins = ins._replace(operation=op, qubits=best.qubits[k])
            out.append(ins)
        return replace(ir, data=out)

    def _analyse(self, sch: _Schedule) -> tuple[Any, ...]:
        """``_times`` of ``sch``, the positions on each wire, and the SWAPs before each slot."""
        ends, tails, crit, depth = _times([sch.gates[k] for k in sch.order])
        on_wire: dict = {}
        for j, e in enumerate(ends):
            for x in e:
                on_wire.setdefault(x, []).append(j)
        n_swaps = [0]
        for k in sch.order:
            n_swaps.append(n_swaps[-1] + self.swap[k])
        return ends, tails, crit, depth, on_wire, n_swaps

    def _best_slot(
        self, sch: _Schedule, i: int, a: tuple[Any, ...]
    ) -> tuple[int, int, tuple[int, ...], int]:
        """``(path, slot, qubits, choice)`` of the least path through ``sch.order[i]``, moved."""
        ends, tails, _, _, on_wire, n_swaps = a
        k = sch.order[i]
        pos = {kk: j for j, kk in enumerate(sch.order)}
        lo = max((pos[p] for p in self.preds[k]), default=-1) + 1
        hi = min((pos[s] for s in self.succs[k]), default=len(sch.order))
        ins = self.data[k]
        best = None
        # ponytail: scans every slot of the window, O(window * candidates * log n) per move
        for j in range(lo, hi + 1):
            qubits = tuple(self.layouts[n_swaps[j]][v] for v in self.virt[k])
            for r in range(len(ins.operation.candidates)):
                ((ws, w),) = _gates(ins, qubits, r)
                if ws not in self.edges:
                    continue
                head = tail = 0
                for x in ws:  # the neighbours of slot j on wire x, other than k itself
                    lst = on_wire.get(x, ())
                    b = bisect_left(lst, j)
                    p = b - 1 - (b > 0 and lst[b - 1] == i)
                    if p >= 0:
                        head = max(head, ends[lst[p]][x])
                    c = b + (b < len(lst) and lst[b] == i)
                    if c < len(lst):
                        tail = max(tail, tails[lst[c]][x])
                if best is None or head + w + tail < best[0]:
                    best = (head + w + tail, j, qubits, r)
        return best

    def _polish(self, sch: _Schedule) -> int:
        """Reinsert critical diagonal ops of ``sch`` while (depth, critical ops) drops; the depth."""
        a = self._analyse(sch)
        tried: set[int] = set()
        while True:
            n_crit = sum(a[2])
            for i, k in enumerate(sch.order):
                if not a[2][i] or k not in self.movable or k in tried:
                    continue
                tried.add(k)
                path, j, qubits, r = self._best_slot(sch, i, a)
                if path >= a[3]:
                    continue
                saved = sch.order[:], sch.qubits[k], sch.choice[k], sch.gates[k]
                sch.order.insert(j - (j > i), sch.order.pop(i))
                sch.qubits[k], sch.choice[k] = qubits, r
                sch.gates[k] = _gates(self.data[k], qubits, r)
                new = self._analyse(sch)
                if (new[3], sum(new[2])) < (a[3], n_crit):
                    a = new
                    tried.clear()
                    break
                sch.order, sch.qubits[k], sch.choice[k], sch.gates[k] = saved
            else:
                return a[3]
