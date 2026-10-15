"""``PrismRouting``: place a ``MultiRealization`` and choose every realization.

SABRE layout-and-routing over retained realization sets. The outer loop
follows Qiskit's O3 ``SabreLayout``: random and standard starting layouts
undergo alternating forward/backward refinement, then one multi-trial forward
route is kept per start. The best final route by ``SearchBudget.objective``
gives the placement and the choices. The kernel is
``crates/src/prism_routing/layout.rs``.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

from qiskit import QuantumCircuit
from qiskit.circuit import Clbit
from qiskit.circuit.library import SwapGate
from qiskit.passmanager import GenericPass
from qiskit.passmanager.compilation_status import PassManagerState, RunState
from qiskit.transpiler import CouplingMap, TranspilerError

from prism._accelerate import (
    BasicHeuristic,
    DecayHeuristic,
    Heuristic,
    LookaheadHeuristic,
    RoutingTarget,
    SetScaling,
    prism_layout_and_routing,
)
from prism.ir import (
    MultiRealization,
    MultiRealizationInstruction,
    MultiRealizationOp,
    Placement,
)
from prism.metrics import active_gate_count, physical_depth

__all__ = ["PrismRouting", "SearchBudget"]

OBJECTIVES: frozenset[str] = frozenset({"swaps", "depth"})

# Rust event kinds (crates/src/prism_routing/input.rs).
_COMMIT, _SWAP, _SUB_GATE = 0, 1, 2

Pairs = tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class SearchBudget:
    """Search effort and route-selection objective.

    Args:
        layout_starts: Random starting layouts (Qiskit's dense, identity and
            reverse layouts are always added).
        refinement_iterations: Forward/backward refinement rounds per start.
        swap_trials: Routing trials per start in the final forward pass.
        objective: ``"swaps"`` (fewest inserted SWAPs, then depth, then gates) or
            ``"depth"`` (critical-path depth in non-free gates, then gates, then size).
    """

    layout_starts: int = 40
    refinement_iterations: int = 16
    swap_trials: int = 40
    objective: str = "swaps"

    def __post_init__(self) -> None:
        if self.objective not in OBJECTIVES:
            raise ValueError(
                f"objective must be one of {sorted(OBJECTIVES)}, got {self.objective!r}"
            )
        for name in ("layout_starts", "refinement_iterations", "swap_trials"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be >= 1, got {getattr(self, name)}")


Score = tuple[float, int, int]


def score(qc: QuantumCircuit, objective: str = "swaps") -> Score:
    """Post-selection score for ``qc`` under ``objective``; lower is better."""
    d, g, sz = physical_depth(qc), active_gate_count(qc), qc.size()
    if objective == "swaps":
        return (qc.count_ops().get("swap", 0), d, g)
    return (d, g, sz)


@dataclass(frozen=True)
class _Ctx:
    """The router's view of an unplaced program: one entry per instruction."""

    data: list[MultiRealizationInstruction]
    candidates: list[tuple[QuantumCircuit, ...]]
    virt_pairs: list[tuple[Pairs, ...]]
    virts_used: list[frozenset[int]]
    diagonal: list[bool]
    cl_used: list[frozenset[Clbit]]
    local_default: list[int]
    succ: list[list[int]]
    pred_count: list[int]
    n_phys: int
    n_virt: int


class PrismRouting(GenericPass[MultiRealization, MultiRealization]):
    """Place the program and choose a realization for every ``MultiRealizationOp``.

    Reads a ``MultiRealization`` with no placement; returns one with a
    placement, physical-qubit instructions, routing SWAPs, and a choice on
    every ``MultiRealizationOp``. Publishes ``realization_choices`` (the chosen
    index of each op with several candidates, in program order) and
    ``online_n_swaps`` (routing SWAPs) to the property set.

    Args:
        coupling_map: Connected, symmetric device graph.
        seed: Seed of the layout search; ``None`` draws one.
        budget: Search effort and objective.

    Raises:
        ValueError: if ``coupling_map`` is disconnected or directed.
    """

    BEST_EPSILON = 1e-10
    LOOKAHEAD_LAYERS = 4

    def __init__(
        self,
        coupling_map: CouplingMap,
        *,
        seed: int | None = None,
        budget: SearchBudget | None = None,
    ) -> None:
        """Check the coupling map and keep the search configuration."""
        if not coupling_map.is_connected():
            raise ValueError(
                "coupling_map is disconnected; prism routes on one connected "
                "component. Pass the component to use, e.g. "
                "coupling_map.connected_components()[0]."
            )
        if not coupling_map.is_symmetric:
            raise ValueError(
                "coupling_map is directed; prism needs every edge in both "
                "directions. Call coupling_map.make_symmetric() first."
            )
        super().__init__()
        self.coupling_map = coupling_map
        self.seed = seed
        self.budget = budget or SearchBudget()

    def run(self, passmanager_ir: MultiRealization) -> MultiRealization:
        """Refine every start in the kernel, then keep the best final route by objective."""
        ir = passmanager_ir
        if ir.placement is not None:
            raise TranspilerError("PrismRouting got a program that is already placed")
        ctx = self._precompute(ir)
        base_seed = (
            self.seed
            if self.seed is not None
            else random.SystemRandom().getrandbits(64)
        )
        target = RoutingTarget.from_coupling_list(
            list(self.coupling_map.get_edges()), ctx.n_phys
        )
        starts = self._starting_layouts(ctx, base_seed, target)
        results = prism_layout_and_routing(
            self._flatten_ctx(ctx),
            self._flatten_ctx(self._reversed_ctx(ctx)),
            target,
            self._make_heuristic(ctx.n_phys),
            [(int(seed) % (1 << 64), list(v2p)) for seed, v2p in starts],
            self.budget.refinement_iterations,
            self.budget.swap_trials,
        )
        best = None  # (score, placed program, choices, n_swaps); first start wins ties
        for events, final_v2p, n_swaps, refined_v2p in results:
            data, chosen = self._replay(events, ctx, list(refined_v2p))
            placed = replace(
                ir, data=data, placement=Placement(tuple(refined_v2p), tuple(final_v2p))
            )
            s = score(placed.to_circuit(), self.budget.objective)
            if best is None or s < best[0]:
                best = (s, placed, chosen, n_swaps)
        assert best is not None
        _, placed, chosen, n_swaps = best
        self.property_set["realization_choices"] = tuple(
            chosen[k] for k, cands in enumerate(ctx.candidates) if len(cands) > 1
        )
        self.property_set["online_n_swaps"] = int(n_swaps)
        return placed

    def update_status(
        self, state: PassManagerState, run_state: RunState
    ) -> PassManagerState:
        """A new program: no earlier analysis holds (as ``TransformationPass`` does)."""
        state = super().update_status(state, run_state)
        if run_state == RunState.SUCCESS:
            state.workflow_status.completed_passes.clear()
        return state

    def _make_heuristic(self, n_phys: int) -> Heuristic:
        """Qiskit 2.6 ``SabreLayout``'s heuristic, with ``LOOKAHEAD_LAYERS`` lookahead layers.

        Stock looks one layer ahead at weight ``0.5 / n_phys``. That is too
        shallow for prism, whose commits route gates in cascades; four layers at
        the stock weight route about as well as Qiskit 2.3's 20-gate extended set.
        """
        return Heuristic(
            basic=BasicHeuristic(1.0, SetScaling.Constant),
            lookahead=LookaheadHeuristic(
                [0.5 / n_phys] * self.LOOKAHEAD_LAYERS, SetScaling.Constant
            ),
            decay=DecayHeuristic(0.001, 5),
            attempt_limit=10 * n_phys,
            best_epsilon=self.BEST_EPSILON,
        )

    @staticmethod
    def _flatten_ctx(ctx: _Ctx) -> tuple:
        """The flat arrays ``prism_layout_and_routing`` takes."""
        virt_pairs = [[[list(p) for p in real] for real in op] for op in ctx.virt_pairs]
        return (virt_pairs, ctx.succ, ctx.pred_count, ctx.local_default)

    @staticmethod
    def _replay(
        events: list[tuple[int, int, int]], ctx: _Ctx, v2p: list[int]
    ) -> tuple[list[MultiRealizationInstruction], dict[int, int]]:
        """Turn a kernel trace into placed instructions and the chosen candidate per instruction.

        ``COMMIT(k, r)`` places instruction ``k`` with choice ``r``. ``SWAP(p, q)``
        is a routing SWAP. ``SUB_GATE(k, r << 16 | j)`` emits the ``j``-th 2-qubit
        gate of candidate ``r`` (with the 1-qubit gates before it, and after it
        for the last one) as regular operations.
        """
        p2v = [0] * ctx.n_phys
        for v, p in enumerate(v2p):
            p2v[p] = v
        data: list[MultiRealizationInstruction] = []
        chosen: dict[int, int] = {}
        for kind, a, b in events:
            if kind == _SWAP:
                data.append(MultiRealizationInstruction(SwapGate(), (a, b)))
                v_a, v_b = p2v[a], p2v[b]
                v2p[v_a], v2p[v_b] = v2p[v_b], v2p[v_a]
                p2v[a], p2v[b] = p2v[b], p2v[a]
                continue
            ins = ctx.data[a]
            qubits = tuple(v2p[v] for v in ins.qubits)
            if kind == _COMMIT:
                chosen[a] = b
                op = ins.operation
                if isinstance(op, MultiRealizationOp):
                    op = replace(op, choice=b)
                data.append(MultiRealizationInstruction(op, qubits, ins.clbits))
                continue
            r, sub = b >> 16, b & 0xFFFF
            chosen.setdefault(a, r)
            real = ctx.candidates[a][r]
            twoq = [i for i, ci in enumerate(real.data) if len(ci.qubits) == 2]
            start = twoq[sub - 1] + 1 if sub else 0
            end = len(real.data) if sub == len(twoq) - 1 else twoq[sub] + 1
            for ci in real.data[start:end]:
                data.append(
                    MultiRealizationInstruction(
                        ci.operation,
                        tuple(qubits[real.find_bit(q).index] for q in ci.qubits),
                        tuple(ins.clbits[real.find_bit(c).index] for c in ci.clbits),
                    )
                )
        return data, chosen

    def _starting_layouts(
        self, ctx: _Ctx, base_seed: int, target: RoutingTarget
    ) -> list[tuple[int, list[int]]]:
        """``layout_starts`` seeded random layouts, then Qiskit's dense, identity and reverse layouts."""
        starts = []
        for trial in range(self.budget.layout_starts):
            v2p = list(range(ctx.n_phys))
            random.Random(base_seed + trial).shuffle(v2p)
            starts.append((base_seed + trial, v2p))
        seed = base_seed + self.budget.layout_starts
        return starts + [
            (seed, target.dense_layout(ctx.n_virt)),
            (seed + 1, list(range(ctx.n_phys))),
            (seed + 2, list(reversed(range(ctx.n_phys)))),
        ]

    def _reversed_ctx(self, ctx: _Ctx) -> _Ctx:
        """The context of the reversed program, for backward refinement."""
        rev = replace(
            ctx,
            data=ctx.data[::-1],
            candidates=ctx.candidates[::-1],
            virt_pairs=ctx.virt_pairs[::-1],
            virts_used=ctx.virts_used[::-1],
            diagonal=ctx.diagonal[::-1],
            cl_used=ctx.cl_used[::-1],
            local_default=ctx.local_default[::-1],
        )
        succ, pred_count = _dependencies(rev.virts_used, rev.diagonal, rev.cl_used)
        return replace(rev, succ=succ, pred_count=pred_count)

    def _precompute(self, ir: MultiRealization) -> _Ctx:
        """Candidate 2-qubit pairs, touched wires and dependencies per instruction."""
        n_phys = self.coupling_map.size()
        n_virt = len(ir.qubits)
        if n_virt > n_phys:
            raise TranspilerError(
                f"the circuit needs {n_virt} physical qubits ({len(ir.qregs)} logical "
                f"x {ir.enc.WIRES_PER_LOGICAL} wires) but the coupling map has "
                f"{n_phys}. Use a larger coupling map or fewer qubits."
            )
        candidates, virt_pairs, virts_used, diagonal, local_default = [], [], [], [], []
        for ins in ir.data:
            op = ins.operation
            if isinstance(op, MultiRealizationOp):
                cands = op.candidates
                diagonal.append(op.diagonal)
                local_default.append(op.default_index)
            else:
                qc = QuantumCircuit(len(ins.qubits), len(ins.clbits))
                qc.append(op, qc.qubits, qc.clbits)
                cands = (qc,)
                diagonal.append(False)
                local_default.append(0)
            candidates.append(cands)
            pairs, used = [], set()
            for real in cands:
                wires = [
                    [ins.qubits[real.find_bit(q).index] for q in ci.qubits]
                    for ci in real.data
                ]
                used.update(v for w in wires for v in w)
                pairs.append(tuple((w[0], w[1]) for w in wires if len(w) == 2))
            virt_pairs.append(tuple(pairs))
            virts_used.append(frozenset(used))
        cl_used = [frozenset(ins.clbits) for ins in ir.data]
        succ, pred_count = _dependencies(virts_used, diagonal, cl_used)
        return _Ctx(
            data=ir.data,
            candidates=candidates,
            virt_pairs=virt_pairs,
            virts_used=virts_used,
            diagonal=diagonal,
            cl_used=cl_used,
            local_default=local_default,
            succ=succ,
            pred_count=pred_count,
            n_phys=n_phys,
            n_virt=n_virt,
        )


def _dependencies(
    virts_used: list[frozenset[int]],
    diagonal: list[bool],
    cl_used: list[frozenset[Clbit]],
) -> tuple[list[list[int]], list[int]]:
    """Successor lists and predecessor counts under wire order and diagonal commutation.

    Diagonal ops commute with each other: a diagonal op depends only on the last
    non-diagonal op on each of its wires, and a non-diagonal op on everything
    since. Classical bits are extra wires.
    """
    succ: list[list[int]] = [[] for _ in virts_used]
    pred_count = [0] * len(virts_used)
    last_nondiag: dict[int | Clbit, int] = {}
    diags_since: dict[int | Clbit, list[int]] = {}
    for k, qs in enumerate(virts_used):
        wires: set[int | Clbit] = set(qs) | cl_used[k]
        deps: set[int] = set()
        for w in wires:
            if w in last_nondiag:
                deps.add(last_nondiag[w])
            if not diagonal[k]:
                deps.update(diags_since.get(w, ()))
        for j in sorted(deps):
            succ[j].append(k)
            pred_count[k] += 1
        for w in wires:
            if diagonal[k]:
                diags_since.setdefault(w, []).append(k)
            else:
                last_nondiag[w] = k
                diags_since[w] = []
    return succ, pred_count
