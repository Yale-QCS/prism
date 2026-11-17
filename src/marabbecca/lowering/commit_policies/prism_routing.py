"""SABRE layout-and-routing over retained or early-committed realizations.

The outer loop follows Qiskit 2.4.1 O3 ``SabreLayout``: random and standard
starting layouts undergo alternating single-trial forward/backward refinement,
then one multi-trial forward route is retained for each start.  The best final
route supplies the initial layout, routed circuit, and output permutation.

``binding_mode="retained"`` is PRISM.  ``binding_mode="greedy"`` selects a
complete nearest-realization assignment at the entry to each routing
invocation and holds it fixed for that invocation.  The two modes therefore
share the complete placement and routing schedule; only commitment timing
differs.  The routing kernel is in ``crates/src/prism_routing/routing.rs``.
"""

from __future__ import annotations

import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import replace as _dc_replace
from typing import TYPE_CHECKING

import numpy as np
import rustworkx
from qiskit import QuantumCircuit, QuantumRegister
from qiskit._accelerate.dense_layout import best_subset
from qiskit.circuit.library import SwapGate
from qiskit.converters import circuit_to_dag, dag_to_circuit
from qiskit.dagcircuit import DAGCircuit, DAGOpNode
from qiskit.transpiler import CouplingMap, Layout
from qiskit.transpiler.passes.layout import disjoint_utils

from marabbecca._accelerate import (
    BasicHeuristic,
    DecayHeuristic,
    Heuristic,
    LookaheadHeuristic,
    RoutingTarget,
    SetScaling,
    prism_routing,
)
from marabbecca.lowering.commit import (
    SABRE_ITERATIONS,
    SABRE_TRIALS,
    CommitPolicy,
    CommitResult,
)
from marabbecca.lowering.ir import LoweredOp
from marabbecca.synthesis.reschedule import RescheduleCommutingDiagonals
from marabbecca.utils.metrics import (
    BIT_FLIP_RATE_PER_US,
    DEPHASING_RATE_PER_US,
    GATE_DURATIONS,
    RSWAP_ERROR,
    active_gate_count,
    device_success,
    physical_depth,
    physical_duration,
)

if TYPE_CHECKING:
    from marabbecca.encodings.base import QubitEncoding


@dataclass
class _Ctx:
    """Per-DAG precomputation reused across trials and forward/backward passes."""

    op_nodes: list[DAGOpNode]
    regs: list
    q_to_virt: dict
    virt_pairs: list[tuple[tuple[tuple[int, int], ...], ...]]
    virts_used: list[frozenset[int]]
    succ: list[list[int]]
    pred_count: list[int]
    real_idx_map: list[tuple[int, ...]]
    local_default: list[int]
    n_phys: int
    n_virt: int
    diagonal: tuple[bool, ...] = ()
    durations: tuple[float, ...] = ()


Score = tuple[float, int, int]
"""Lexicographic post-selection score; lower is better. ``< Score`` compares as
expected. The field order depends on the objective (see ``score``): ``"swaps"``
sorts (swaps, depth, gates), ``"depth"`` sorts (depth, gates, size), ``"gates"``
sorts (gates, depth, size), ``"duration"`` sorts (duration_ns, gates, size)."""

OBJECTIVES: frozenset[str] = frozenset(
    {"swaps", "depth", "gates", "duration", "error", "custom"}
)


def score(qc: QuantumCircuit, objective: str = "swaps", n_logical: int = 0) -> Score:
    """Post-selection score for ``qc`` under ``objective``; lower is better.

    ``"swaps"`` minimizes the inserted SWAP count (the SABRE objective and the
    default), depth then gates as tiebreaks; ``"depth"`` minimizes physical depth
    (parallelism), gates as tiebreak; ``"gates"`` minimizes active (non-free) gate
    count, depth as tiebreak; ``"duration"`` minimizes the Liu-model critical
    path (500 ns SWS and 200 ns beamsplitter operations), then gates; ``"error"``
    minimizes the device-model conditional infidelity ``-log F_cond`` of
    ``n_logical`` qubits (``metrics.device_success``; loss is left out because
    more shots recover it), then gates. All keep a final size tiebreak.
    """
    if objective not in OBJECTIVES - {"custom"}:
        raise ValueError(f"no built-in score for objective {objective!r}")
    d, g, sz = physical_depth(qc), active_gate_count(qc), qc.size()
    if objective == "swaps":
        # ponytail: also counts the one-SWAP lowering of each fixed logical X, a
        # per-circuit constant across routes, so argmin matches router-inserted
        # SWAPs. Logical SWAPs (2- or 4-SWAP realizations) would break that, but
        # ElidePermutations removes them before lowering.
        return (qc.count_ops().get("swap", 0), d, g)
    if objective == "gates":
        return (g, d, sz)
    if objective == "duration":
        return (physical_duration(qc), g, sz)
    if objective == "error":
        _, fidelity = device_success(n_logical, physical_duration(qc), qc.count_ops())
        return (-math.log(fidelity), g, sz)
    return (d, g, sz)


class PrismRouting(CommitPolicy):
    """PRISM commit policy. Score: ``(basic_avg + 0.5 * ext_avg) * max(decay)`` with ``min``-over-candidates per op."""

    EXTENDED_SET_SIZE = 40
    EXTENDED_SET_WEIGHT = 0.5
    DECAY_INCREMENT = 0.01
    DECAY_RESET_INTERVAL = 5
    BEST_EPSILON = 1e-10
    DIAGONAL_OPS = frozenset({"crz", "rz"})
    PHYS_LOAD_DECAY = 0.9

    HEURISTIC_CONFIGS = ("tuned", "qiskit_sabre")
    TIE_BREAKS = ("load", "default")
    BINDING_MODES = ("retained", "greedy")
    START_MODES = ("qiskit_o3", "legacy_identity")

    def __init__(
        self,
        coupling_map: CouplingMap,
        *,
        enc: type[QubitEncoding],
        seed: int | None = None,
        max_iterations: int = SABRE_ITERATIONS,
        num_trials: int = SABRE_TRIALS,
        swap_trials: int = SABRE_TRIALS,
        objective: str = "swaps",
        heuristic_config: str = "qiskit_sabre",
        tie_break: str = "default",
        binding_mode: str = "retained",
        start_mode: str = "qiskit_o3",
        include_identity: bool = True,
        commute_diagonal: bool | str = False,
        reschedule: bool = False,
        front_commit: bool = False,
        front_commit_witness: bool = True,
        wait_scale: float = 0.0,
        wait_realizations: bool = True,
        wait_mode: str = "additive",
        route_score: Callable[[QuantumCircuit], float] | None = None,
    ) -> None:
        """Bind connectivity and iteration/trial budgets.

        ``seed=None`` draws a random base seed at ``run`` time; pass an int
        for reproducibility. ``objective`` selects
        the post-selection key across trials/iterations: ``"swaps"`` (default,
        min inserted SWAPs, the SABRE objective) or ``"depth"`` / ``"duration"``
        (the yield-oriented knob). ``heuristic_config`` names the parameter
        set (``"qiskit_sabre"`` = the stock Qiskit 2.4.1 ``"decay"`` build,
        which is the default; ``"tuned"`` = the optional research
        configuration); ``tie_break`` selects the executable-realization tie
        rule (``"default"`` = default-then-index, which is the default;
        ``"load"`` = the optional physical-load-balanced rule).
        ``binding_mode="greedy"`` fixes the nearest realization at each route
        entry; ``"retained"`` keeps all realizations available during routing.
        ``start_mode="qiskit_o3"`` adds Qiskit's dense, identity, and reverse
        layouts to ``num_trials`` random layouts. ``"legacy_identity"`` keeps
        the historical random-plus-identity schedule for artifact replay.
        ``commute_diagonal=True`` lets the gates in ``DIAGONAL_OPS`` commute
        with each other in the routing dependency graph instead of keeping
        program order on shared wires; ``"best"`` runs the search under both
        rules and keeps the route the objective scores better. ``reschedule``
        scores each candidate after the rescheduling the physical stage will
        apply, so depth, duration and error compare the circuits as emitted. ``front_commit=True`` (the
        front-layer-commit ablation) freezes each retained set to its closest
        realization when it enters the front layer and scores candidate SWAPs
        against that one witness; it also scores each lookahead-set gate on one
        witness, its nearest realization when the set is built, unless
        ``front_commit_witness=False`` keeps PRISM's minimum over realizations there.
        ``wait_scale`` turns on the time-aware SWAP
        term for every binding mode: a candidate SWAP also pays for how long
        its rails stay busy, at ``wait_scale`` times the device-model weight
        (``_wait_weight``); ``0.0`` is stock SABRE scoring.
        ``wait_realizations`` also prices each realization by its rails' wait,
        in scoring and at commit; ``False`` keeps only the SWAP term.
        ``wait_mode="lexicographic"`` keeps distance primary: wait only breaks
        ties among SABRE's best SWAPs and picks the executable realization whose
        rails are free soonest, with no weight.
        ``objective="custom"`` selects the final route by ``route_score(qc)``,
        followed by active gate count and size, without changing route search.
        """
        if coupling_map is None:
            raise ValueError("PrismRouting requires coupling_map")
        if objective not in OBJECTIVES:
            raise ValueError(
                f"objective must be one of {sorted(OBJECTIVES)}, got {objective!r}"
            )
        if (objective == "custom") != (route_score is not None):
            raise ValueError(
                "objective='custom' requires route_score; other objectives do not accept it"
            )
        if heuristic_config not in self.HEURISTIC_CONFIGS:
            raise ValueError(
                f"heuristic_config must be one of {self.HEURISTIC_CONFIGS}, got {heuristic_config!r}"
            )
        if tie_break not in self.TIE_BREAKS:
            raise ValueError(
                f"tie_break must be one of {self.TIE_BREAKS}, got {tie_break!r}"
            )
        if binding_mode not in self.BINDING_MODES:
            raise ValueError(
                f"binding_mode must be one of {self.BINDING_MODES}, got {binding_mode!r}"
            )
        if start_mode not in self.START_MODES:
            raise ValueError(
                f"start_mode must be one of {self.START_MODES}, got {start_mode!r}"
            )
        super().__init__(enc=enc)
        self.coupling_map = coupling_map
        self.seed = seed
        self.max_iterations = max(1, max_iterations)
        self.num_trials = max(1, num_trials)
        self.swap_trials = max(1, swap_trials)
        self.objective = objective
        self.route_score = route_score
        self.heuristic_config = heuristic_config
        self.tie_break = tie_break
        self.binding_mode = binding_mode
        self.start_mode = start_mode
        self.include_identity = include_identity
        self.commute_diagonal = (
            "best" if commute_diagonal == "best" else bool(commute_diagonal)
        )
        self.front_commit = bool(front_commit)
        self.front_commit_witness = bool(front_commit_witness)
        self.reschedule = bool(reschedule)
        self.wait_scale = float(wait_scale)
        self.wait_realizations = bool(wait_realizations)
        if wait_mode not in ("additive", "lexicographic"):
            raise ValueError(
                f"wait_mode must be 'additive' or 'lexicographic', got {wait_mode!r}"
            )
        self.wait_mode = wait_mode

    @property
    def num_starts(self) -> int:
        """Total starts under the selected layout-pool policy."""
        if self.start_mode == "qiskit_o3":
            return self.num_trials + 3
        return self.num_trials + int(self.include_identity)

    # ---- Algorithm (mirrors qiskit.transpiler.passes.SabreLayout) ---------

    def commit(self, dag: DAGCircuit) -> CommitResult:
        """Run Qiskit-style layout refinement and retain the best final route."""
        if self.commute_diagonal == "best":
            results = []
            for commute in (False, True):
                self.commute_diagonal = commute
                results.append(self.commit(dag))
            self.commute_diagonal = "best"

            def winning_score(result: CommitResult) -> tuple:
                trace = result.search_trace
                return tuple(trace["starts"][trace["winning"]["trial"]]["final_score"])

            best = min(results, key=winning_score)
            trace = {**best.search_trace, "commute_won": best is results[1]}
            return _dc_replace(best, search_trace=trace)
        t_start = time.perf_counter()
        disjoint_utils.require_layout_isolated_to_component(dag, self.coupling_map)
        ctx_fwd = self._precompute(dag)
        n_logical = dag.num_qubits() // self.enc.WIRES_PER_LOGICAL
        ctx_rev = self._reversed_ctx(ctx_fwd)

        base_seed = (
            self.seed
            if self.seed is not None
            else random.SystemRandom().getrandbits(64)
        )
        # (score, out_qc, final_trace, final_ctx, final_initial_v2p)
        best: tuple | None = None
        best_ref: dict | None = None
        starts: list[dict] = []
        calls = {
            "refinement_forward_attempted": 0,
            "refinement_forward_completed": 0,
            "refinement_backward_attempted": 0,
            "refinement_backward_completed": 0,
            "final_attempted": 0,
            "final_completed": 0,
            "routing_invocations": 0,
            "route_trial_executions": 0,
        }
        n_failed_trials = 0
        start_layouts = self._starting_layouts(ctx_fwd, base_seed)
        for trial, (start_kind, trial_seed, initial_v2p) in enumerate(start_layouts):
            v2p = list(initial_v2p)
            entry = {
                "trial": trial,
                "kind": start_kind,
                "seed": int(trial_seed),
                "initial_v2p": list(v2p),
                "iterations": [],
            }
            t_trial = time.perf_counter()
            try:
                for it in range(self.max_iterations):
                    calls["refinement_forward_attempted"] += 1
                    fwd_trace, fwd_ctx, fwd_choices = self._route(
                        ctx_fwd, v2p, (trial_seed * 1000 + 2 * it) % (1 << 64), 1
                    )
                    calls["refinement_forward_completed"] += 1
                    calls["routing_invocations"] += 1
                    calls["route_trial_executions"] += 1
                    v2p = list(fwd_trace[1])

                    calls["refinement_backward_attempted"] += 1
                    back_trace, _back_ctx, back_choices = self._route(
                        ctx_rev, v2p, (trial_seed * 1000 + 2 * it + 1) % (1 << 64), 1
                    )
                    calls["refinement_backward_completed"] += 1
                    calls["routing_invocations"] += 1
                    calls["route_trial_executions"] += 1
                    v2p = list(back_trace[1])
                    entry["iterations"].append(
                        {
                            "iteration": it,
                            "forward_swaps": int(fwd_trace[2]),
                            "backward_swaps": int(back_trace[2]),
                            **(
                                {
                                    "forward_choices": fwd_choices,
                                    "backward_choices": back_choices,
                                }
                                if self.binding_mode == "greedy"
                                else {}
                            ),
                        }
                    )

                final_initial_v2p = list(v2p)
                calls["final_attempted"] += 1
                final_trace, final_ctx, final_choices = self._route(
                    ctx_fwd,
                    final_initial_v2p,
                    (trial_seed * 1000 + 2 * self.max_iterations) % (1 << 64),
                    self.swap_trials,
                )
                calls["final_completed"] += 1
                calls["routing_invocations"] += 1
                calls["route_trial_executions"] += self.swap_trials
                out_qc = self._emit_circuit_from_trace(
                    final_trace, final_ctx, final_initial_v2p
                )
                scored = out_qc
                if self.reschedule and self.objective != "swaps":
                    scored = dag_to_circuit(
                        RescheduleCommutingDiagonals().run(circuit_to_dag(out_qc))
                    )
                if self.route_score is None:
                    final_score = score(scored, self.objective, n_logical)
                else:
                    cost = float(self.route_score(scored))
                    if not math.isfinite(cost):
                        raise ValueError("route_score must return a finite cost")
                    final_score = (cost, active_gate_count(scored), scored.size())
                entry["refined_v2p"] = final_initial_v2p
                entry["final_score"] = list(final_score)
                entry["final_swaps"] = int(final_trace[2])
                if self.binding_mode == "greedy":
                    entry["final_choices"] = final_choices
                if best is None or final_score < best[0]:
                    best = (
                        final_score,
                        out_qc,
                        final_trace,
                        final_ctx,
                        final_initial_v2p,
                    )
                    best_ref = {"trial": trial, "kind": start_kind}
            except RuntimeError as e:
                entry["failed"] = f"{type(e).__name__}: {e}"[:200]
                n_failed_trials += 1
            entry["trial_s"] = round(time.perf_counter() - t_trial, 4)
            starts.append(entry)

        if best is None:
            raise RuntimeError(f"PrismRouting: all {self.num_starts} starts got stuck")
        trace = {
            "binding_mode": self.binding_mode,
            "objective": self.objective,
            **(
                {
                    "route_score": getattr(
                        self.route_score,
                        "__qualname__",
                        type(self.route_score).__qualname__,
                    )
                }
                if self.route_score is not None
                else {}
            ),
            "heuristic_config": self.heuristic_config,
            "tie_break": self.tie_break,
            "heuristic_repr": repr(self._make_heuristic(self.coupling_map.size())),
            "phys_load_decay": self.PHYS_LOAD_DECAY,
            "multi_tie_break_load": self.tie_break == "load",
            "front_commit": self.front_commit,
            "multi_sticky_witness": self.front_commit and self.front_commit_witness,
            "num_trials": self.num_trials,
            "start_mode": self.start_mode,
            "standard_layouts": (
                ["dense", "identity", "reverse"]
                if self.start_mode == "qiskit_o3"
                else (["identity"] if self.include_identity else [])
            ),
            "include_identity": self.include_identity,
            "final_swap_trials": self.swap_trials,
            "refinement_swap_trials": 1,
            "max_iterations": self.max_iterations,
            "base_seed": int(base_seed),
            "seed_schedule": (
                "start s: base+s; refinement route seed: "
                "start_seed*1000+2*iteration (+1 backward); "
                "final route seed: start_seed*1000+2*max_iterations"
            ),
            "starts": starts,
            "winning": best_ref,
            "route_calls": calls,
            "n_failed_starts": n_failed_trials,
            "wall_s": round(time.perf_counter() - t_start, 4),
        }
        payload = self._trace_to_payload(best[2], best[3])
        result = self._build_result(dag, best[3], best[1], payload, best[4])
        return _dc_replace(result, search_trace=trace)

    def _wait_weight(self, n_logical: int) -> float:
        """Price one SWAP duration of rail wait against one serial SWAP, both in -log F_cond.

        A serial SWAP costs its beamsplitter error plus the dephasing and bit flips
        of all ``n_logical`` qubits over its duration; a wait of one SWAP duration
        costs only the latter. The ratio puts the wait term in the distance term's
        units (about one SWAP per unit distance).
        """
        delay = (
            n_logical
            * (DEPHASING_RATE_PER_US + BIT_FLIP_RATE_PER_US)
            * GATE_DURATIONS["swap"]
            / 1_000.0
        )
        return self.wait_scale * delay / (-math.log1p(-RSWAP_ERROR) + delay)

    def _make_heuristic(self, n_phys: int, n_logical: int = 0) -> "Heuristic":
        """Build the named heuristic config."""
        tie_load = self.tie_break == "load"
        lexicographic = self.wait_mode == "lexicographic" and self.wait_scale > 0
        wait_weight = 0.0 if lexicographic else self._wait_weight(n_logical)
        if self.heuristic_config == "qiskit_sabre":
            # The stock Qiskit 2.4.1 ``"decay"`` build (verified against the
            # installed source 2026-07-28): basic 1.0 Constant, lookahead
            # 0.5/20 Size, decay 0.001/5, attempt_limit 10*n.
            return Heuristic(
                basic=BasicHeuristic(1.0, SetScaling.Constant),
                lookahead=LookaheadHeuristic(0.5, 20, SetScaling.Size),
                decay=DecayHeuristic(0.001, 5),
                attempt_limit=10 * n_phys,
                best_epsilon=self.BEST_EPSILON,
                phys_load_decay=self.PHYS_LOAD_DECAY,
                multi_tie_break_load=tie_load,
                multi_sticky_witness=self.front_commit and self.front_commit_witness,
                multi_front_commit=self.front_commit,
                wait_weight=wait_weight,
                wait_realizations=self.wait_realizations,
                wait_lexicographic=lexicographic,
            )
        return Heuristic(
            basic=BasicHeuristic(1.0, SetScaling.Size),
            lookahead=LookaheadHeuristic(
                self.EXTENDED_SET_WEIGHT, self.EXTENDED_SET_SIZE, SetScaling.Size
            ),
            decay=DecayHeuristic(self.DECAY_INCREMENT, self.DECAY_RESET_INTERVAL),
            attempt_limit=max(20, 8 * n_phys),
            best_epsilon=self.BEST_EPSILON,
            phys_load_decay=self.PHYS_LOAD_DECAY,
            multi_tie_break_load=tie_load,
            multi_sticky_witness=self.front_commit and self.front_commit_witness,
            multi_front_commit=self.front_commit,
            wait_weight=wait_weight,
            wait_realizations=self.wait_realizations,
            wait_lexicographic=lexicographic,
        )

    def _route(
        self, ctx: "_Ctx", v2p: list[int], seed: int, swap_trials: int
    ) -> tuple[tuple, "_Ctx", list[int] | None]:
        """Route once, fixing all realizations at the entry layout under greedy binding."""
        choices = None
        if self.binding_mode == "greedy":
            ctx, choices = self._greedy_commit_ctx(ctx, v2p)
        trace = prism_routing(
            *self._flatten_ctx(ctx),
            RoutingTarget.from_coupling_list(
                list(self.coupling_map.get_edges()), ctx.n_phys
            ),
            self._make_heuristic(ctx.n_phys, ctx.n_virt // self.enc.WIRES_PER_LOGICAL),
            list(v2p),
            swap_trials,
            seed,
            op_durations=list(ctx.durations) if self.wait_scale else None,
        )
        return trace, ctx, choices

    # ---- Rust-boundary helpers --------------------------------------------

    @staticmethod
    def _flatten_ctx(ctx: "_Ctx") -> tuple:
        """Convert ``ctx`` to the flat precompute arrays passed to ``prism_routing``."""
        virt_pairs = [
            [[[int(p[0]), int(p[1])] for p in real] for real in op_pairs]
            for op_pairs in ctx.virt_pairs
        ]
        succ = [[int(s) for s in succs] for succs in ctx.succ]
        pred_count = [int(c) for c in ctx.pred_count]
        local_default = [int(d) for d in ctx.local_default]
        return (virt_pairs, succ, pred_count, local_default)

    # Rust event-kind constants (must match input.rs).
    _EVENT_COMMIT = 0
    _EVENT_SWAP = 1
    _EVENT_SUB_GATE = 2

    def _emit_circuit_from_trace(
        self,
        trace: tuple,
        ctx: "_Ctx",
        v2p_initial: list[int],
    ) -> QuantumCircuit:
        """Replay the Rust event stream ``(events, final_v2p, n_swaps)`` into a routed QuantumCircuit.

        Event kinds:

        - ``COMMIT(op_idx, real_idx)``: atomic — emit the entire realization
          circuit at the current layout.
        - ``SWAP(q1, q2)``: physical swap; update v2p / p2v.
        - ``SUB_GATE(op_idx, packed)``: sub-routed — fire one sub-gate of the
          op's chosen realization at the current layout. ``packed`` carries
          ``(real_idx << 16) | sub_idx``.
        """
        events, _, _ = trace
        emitted: list[tuple] = []
        v2p = list(v2p_initial)
        p2v = self._invert(v2p, ctx.n_phys)
        for kind, a, b in events:
            if kind == self._EVENT_COMMIT:
                real_idx = ctx.real_idx_map[a][b]
                self._emit_realization(
                    ctx.op_nodes[a], real_idx, v2p, ctx.q_to_virt, emitted
                )
            elif kind == self._EVENT_SUB_GATE:
                rust_real_idx = (b >> 16) & 0xFFFF
                sub_idx = b & 0xFFFF
                real_idx = ctx.real_idx_map[a][rust_real_idx]
                self._emit_sub_gate(
                    ctx.op_nodes[a], real_idx, sub_idx, v2p, ctx.q_to_virt, emitted
                )
            else:  # SWAP
                emitted.append((SwapGate(), [a, b], ()))
                v_a, v_b = p2v[a], p2v[b]
                v2p[v_a], v2p[v_b] = v2p[v_b], v2p[v_a]
                p2v[a], p2v[b] = p2v[b], p2v[a]
        return self._emit_circuit(emitted, ctx.n_phys)

    @staticmethod
    def _trace_to_payload(trace: tuple, ctx: "_Ctx") -> dict:
        """Convert a Rust trace tuple into the payload shape _finalize expects."""
        events, final_v2p, n_swaps = trace
        chosen: dict[int, int] = {}
        for kind, a, b in events:
            # ``a`` is an op index only for COMMIT / SUB_GATE; for SWAP it is a
            # physical qubit, so guard the virt_pairs lookup by kind (a SWAP's
            # qubit can exceed the op count on a circuit smaller than the map).
            if kind == PrismRouting._EVENT_COMMIT:
                if len(ctx.virt_pairs[a]) > 1:
                    chosen[a] = b
            elif kind == PrismRouting._EVENT_SUB_GATE:
                # Multiple SUB_GATE events for the same op all share the same
                # real_idx (the high 16 bits of `b`); record once.
                if len(ctx.virt_pairs[a]) > 1:
                    chosen.setdefault(a, (b >> 16) & 0xFFFF)
        return {
            "chosen_realizations": chosen,
            "final_v2p": [int(p) for p in final_v2p],
            "n_swaps": int(n_swaps),
        }

    def _initial_v2p(
        self, ctx: _Ctx, trial: int, seed: int
    ) -> tuple[list[int], list[int]]:
        """Historical random/identity layout constructor."""
        v2p = list(range(ctx.n_phys))
        if trial >= 0:
            random.Random(seed).shuffle(v2p)
        return v2p, self._invert(v2p, ctx.n_phys)

    def _starting_layouts(
        self, ctx: _Ctx, base_seed: int
    ) -> list[tuple[str, int, list[int]]]:
        """Build the deterministic layout pool for one compilation.

        Qiskit 2.4.1 O3 uses 20 random layouts plus dense, identity, and
        reverse layouts on targets other than the special 127/133/156-site
        devices.  The target families in this study never use those sizes.
        """
        starts: list[tuple[str, int, list[int]]] = []
        for trial in range(self.num_trials):
            seed = base_seed + trial
            v2p = list(range(ctx.n_phys))
            random.Random(seed).shuffle(v2p)
            starts.append(("random", seed, v2p))

        if self.start_mode == "legacy_identity":
            if self.include_identity:
                starts.append(
                    ("identity", base_seed + self.num_trials, list(range(ctx.n_phys)))
                )
            return starts

        standard_seed = base_seed + self.num_trials
        starts.extend(
            [
                ("dense", standard_seed, self._dense_v2p(ctx)),
                ("identity", standard_seed + 1, list(range(ctx.n_phys))),
                ("reverse", standard_seed + 2, list(reversed(range(ctx.n_phys)))),
            ]
        )
        return starts

    def _dense_v2p(self, ctx: _Ctx) -> list[int]:
        """Return Qiskit's dense-subgraph placement, completed with ancillas."""
        if ctx.n_virt == 0:
            return list(range(ctx.n_phys))
        adjacency = rustworkx.adjacency_matrix(self.coupling_map.graph)
        _rows, _cols, best_map = best_subset(
            ctx.n_virt,
            adjacency,
            0,
            0,
            False,
            self.coupling_map.is_symmetric,
            np.asarray([[0.0]]),
        )
        assigned = [int(p) for p in best_map]
        used = set(assigned)
        return assigned + [p for p in range(ctx.n_phys) if p not in used]

    def _greedy_commit_ctx(self, ctx: _Ctx, v2p: list[int]) -> tuple[_Ctx, list[int]]:
        """Collapse every realization set under the route-entry layout.

        The distance key matches the paper definition.  Exact ties prefer the
        operation's default realization and then its original candidate index.
        Dependencies remain those of the unresolved boundary DAG so the two
        paper arms differ only in the candidates visible to routing.

        A diagonal gate whose fixed realization is one 2Q interaction is listed
        twice: the multi-realization front layer tolerates commuting gates that
        share a qubit, while the single-realization fast path does not.
        """
        distance = self.coupling_map.distance_matrix
        diagonal = ctx.diagonal or (False,) * len(ctx.virt_pairs)
        fixed_pairs = []
        fixed_maps = []
        choices = []
        for op_pairs, real_map, default_local, diag in zip(
            ctx.virt_pairs, ctx.real_idx_map, ctx.local_default, diagonal
        ):
            if len(op_pairs) == 1:
                chosen_local = 0
            else:
                chosen_local = min(
                    range(len(op_pairs)),
                    key=lambda local: (
                        sum(distance[v2p[u]][v2p[v]] for u, v in op_pairs[local]),
                        0 if local == default_local else 1,
                        real_map[local],
                    ),
                )
            if diag and len(op_pairs[chosen_local]) == 1:
                fixed_pairs.append((op_pairs[chosen_local],) * 2)
                fixed_maps.append((real_map[chosen_local],) * 2)
            else:
                fixed_pairs.append((op_pairs[chosen_local],))
                fixed_maps.append((real_map[chosen_local],))
            choices.append(real_map[chosen_local])
        return (
            _dc_replace(
                ctx,
                virt_pairs=fixed_pairs,
                real_idx_map=fixed_maps,
                local_default=[0] * len(fixed_pairs),
            ),
            choices,
        )

    @staticmethod
    def _invert(v2p: list[int], n_phys: int) -> list[int]:
        """Inverse of v2p as a p2v list."""
        p2v = [0] * n_phys
        for v, p in enumerate(v2p):
            p2v[p] = v
        return p2v

    def _reversed_ctx(self, ctx: _Ctx) -> _Ctx:
        """Build the reversed-op-order ctx for backward PRISM passes."""
        op_nodes_rev = list(reversed(ctx.op_nodes))
        virt_pairs_rev = list(reversed(ctx.virt_pairs))
        virts_used_rev = list(reversed(ctx.virts_used))
        diagonal_rev = tuple(reversed(ctx.diagonal))
        succ_rev, pred_count_rev = self._build_deps(virts_used_rev, diagonal_rev)
        # real_idx_map / local_default are indexed by op-node order; reverse to match.
        real_idx_map_rev = list(reversed(ctx.real_idx_map))
        local_default_rev = list(reversed(ctx.local_default))
        return _dc_replace(
            ctx,
            op_nodes=op_nodes_rev,
            virt_pairs=virt_pairs_rev,
            virts_used=virts_used_rev,
            succ=succ_rev,
            pred_count=pred_count_rev,
            real_idx_map=real_idx_map_rev,
            local_default=local_default_rev,
            diagonal=diagonal_rev,
        )

    def _build_result(
        self,
        dag: DAGCircuit,
        ctx: _Ctx,
        out_qc: QuantumCircuit,
        payload: dict,
        v2p: list[int],
    ) -> CommitResult:
        """Build the ``CommitResult`` from the winning trial's outputs."""
        out_qc.metadata = dict(dag.metadata or {})
        # Picks: full op-nodes order (fixed ops use 0; decisions use payload's chosen).
        picks = []
        for k, node in enumerate(ctx.op_nodes):
            lop: LoweredOp = node.op
            if lop.is_fixed:
                picks.append(0)
            elif k in payload["chosen_realizations"]:
                router_pick = payload["chosen_realizations"][k]
                picks.append(ctx.real_idx_map[k][router_pick])
            elif len(ctx.real_idx_map[k]) == 1:
                picks.append(ctx.real_idx_map[k][0])
            else:
                picks.append(lop.default_index)
        choices = tuple(
            picks[k] for k, n in enumerate(ctx.op_nodes) if n.op.is_decision
        )

        # Map every virtual wire to its physical qubit.
        layout_dict = {dag.qubits[v]: v2p[v] for v in range(ctx.n_virt)}
        # The routed circuit is in physical coordinates. Its wire at the
        # winning initial position v2p[v] carries virtual state v, which ends
        # at final_v2p[v]. This is the exact final-layout convention used by
        # Qiskit's routing passes.
        final_v2p = payload["final_v2p"]
        routed_final_layout = Layout(
            {out_qc.qubits[v2p[v]]: final_v2p[v] for v in range(ctx.n_phys)}
        )
        return CommitResult(
            choices=choices,
            layout=Layout(layout_dict),
            routed_dag=circuit_to_dag(out_qc),
            routed_final_layout=routed_final_layout,
            n_swaps=int(payload["n_swaps"]),
        )

    # ---- Precompute --------------------------------------------------------

    def _precompute(self, dag: DAGCircuit) -> _Ctx:
        """Per-DAG precomputation: op caches, dep graph, freeze collapse."""
        regs = list(dag.qregs.values())
        # Lowering emits an all-LoweredOp DAG (init wrapped like every op), so
        # this captures every node.
        op_nodes = [
            n for n in dag.topological_op_nodes() if isinstance(n.op, LoweredOp)
        ]
        q_to_virt = {q: i for i, q in enumerate(dag.qubits)}
        n_phys = self.coupling_map.size()
        n_virt = sum(reg.size for reg in regs)
        if n_virt > n_phys:
            raise ValueError(
                f"Coupling map has {n_phys} qubits, lowered circuit needs {n_virt}"
            )
        virt_pairs, virts_used = self._precompute_op_data(op_nodes, q_to_virt)
        real_idx_map = [tuple(range(len(n.op.realizations))) for n in op_nodes]
        diagonal = tuple(
            self.commute_diagonal and n.op.name in self.DIAGONAL_OPS for n in op_nodes
        )
        succ, pred_count = self._build_deps(virts_used, diagonal)
        local_default: list[int] = []
        for k, node in enumerate(op_nodes):
            di = node.op.default_index
            rim = real_idx_map[k]
            local_default.append(rim.index(di) if di in rim else 0)
        return _Ctx(
            op_nodes=op_nodes,
            regs=regs,
            q_to_virt=q_to_virt,
            virt_pairs=virt_pairs,
            virts_used=virts_used,
            succ=succ,
            pred_count=pred_count,
            real_idx_map=real_idx_map,
            local_default=local_default,
            diagonal=diagonal,
            n_phys=n_phys,
            n_virt=n_virt,
            # Default-realization durations in SWAP units, for the time-aware SWAP term.
            durations=tuple(
                physical_duration(n.op.realizations[n.op.default_index])
                / GATE_DURATIONS["swap"]
                for n in op_nodes
            )
            if self.wait_scale
            else (),
        )

    @staticmethod
    def _precompute_op_data(
        op_nodes: list[DAGOpNode],
        q_to_virt: dict,
    ) -> tuple[list[tuple[tuple[tuple[int, int], ...], ...]], list[frozenset[int]]]:
        """Per-op caches: ``virt_pairs[k][r]`` (2Q pairs for scoring), ``virts_used[k]`` (deps)."""
        virt_pairs: list[tuple[tuple[tuple[int, int], ...], ...]] = []
        virts_used: list[frozenset[int]] = []
        for node in op_nodes:
            qargs = node.qargs
            pairs_per_real = []
            virts: set[int] = set()
            for real in node.op.realizations:
                qb = real.qubits
                pairs = []
                for ci in real.data:
                    qubit_local = [qb.index(q) for q in ci.qubits]
                    virt_qs = [q_to_virt[qargs[lq]] for lq in qubit_local]
                    virts.update(virt_qs)
                    if len(virt_qs) == 2:
                        pairs.append((virt_qs[0], virt_qs[1]))
                pairs_per_real.append(tuple(pairs))
            virt_pairs.append(tuple(pairs_per_real))
            virts_used.append(frozenset(virts))
        return virt_pairs, virts_used

    @staticmethod
    def _build_deps(
        virts_used: list[frozenset[int]],
        diagonal: tuple[bool, ...] = (),
    ) -> tuple[list[list[int]], list[int]]:
        """Successor list + initial pred counts; diagonal ops commute with each other."""
        n_ops = len(virts_used)
        diagonal = diagonal or (False,) * n_ops
        succ: list[list[int]] = [[] for _ in range(n_ops)]
        pred_count = [0] * n_ops
        last_nondiag: dict[int, int] = {}
        diags_since: dict[int, list[int]] = {}
        for k, vs in enumerate(virts_used):
            deps: set[int] = set()
            for v in vs:
                if v in last_nondiag:
                    deps.add(last_nondiag[v])
                if not diagonal[k]:
                    deps.update(diags_since.get(v, ()))
            for j in sorted(deps):
                succ[j].append(k)
                pred_count[k] += 1
            for v in vs:
                if diagonal[k]:
                    diags_since.setdefault(v, []).append(k)
                else:
                    last_nondiag[v] = k
                    diags_since[v] = []
        return succ, pred_count

    # ---- Trial helpers (unchanged) -----------------------------------------

    @staticmethod
    def _emit_realization(
        node: DAGOpNode,
        idx: int,
        v2p: list[int],
        q_to_virt: dict,
        emitted: list[tuple],
    ) -> None:
        """Walk ``node.op.realizations[idx]``, emit ``(op, phys_qs, cl_refs)`` triples."""
        real = node.op.realizations[idx]
        qb = real.qubits
        cb = real.clbits
        qargs = node.qargs
        cargs = node.cargs
        for ci in real.data:
            local_q = [qb.index(q) for q in ci.qubits]
            virt_qs = [q_to_virt[qargs[lq]] for lq in local_q]
            phys_qs = [v2p[v] for v in virt_qs]
            if ci.clbits:
                cl_refs = tuple(cargs[cb.index(c)] for c in ci.clbits)
            else:
                cl_refs = ()
            emitted.append((ci.operation, phys_qs, cl_refs))

    @staticmethod
    def _emit_sub_gate(
        node: DAGOpNode,
        idx: int,
        sub_idx: int,
        v2p: list[int],
        q_to_virt: dict,
        emitted: list[tuple],
    ) -> None:
        """Emit the ``sub_idx``-th 2Q sub-gate of ``node.op.realizations[idx]``.

        Also emits any 1Q gates that fall between the previous 2Q sub-gate
        and this one. The Rust mini-SabreDAG only routes 2Q sub-gates, so
        ``sub_idx`` counts only those; intervening 1Q gates are emitted here
        at the current (post-swaps_before) layout. For the final 2Q sub-gate
        we also emit any trailing 1Q gates so the entire realization circuit
        appears exactly once across the sequence of SUB_GATE events.
        """
        real = node.op.realizations[idx]
        data = real.data
        twoq_indices = [i for i, ci in enumerate(data) if len(ci.qubits) == 2]
        if sub_idx >= len(twoq_indices):
            raise IndexError(
                f"sub_idx={sub_idx} out of range (realization {idx} has "
                f"{len(twoq_indices)} 2Q sub-gates) on op {node}"
            )
        twoq_pos = twoq_indices[sub_idx]
        start = (twoq_indices[sub_idx - 1] + 1) if sub_idx > 0 else 0
        end = len(data) if sub_idx == len(twoq_indices) - 1 else twoq_pos + 1
        qb = real.qubits
        cb = real.clbits
        qargs = node.qargs
        cargs = node.cargs
        for ci in data[start:end]:
            local_q = [qb.index(q) for q in ci.qubits]
            virt_qs = [q_to_virt[qargs[lq]] for lq in local_q]
            phys_qs = [v2p[v] for v in virt_qs]
            cl_refs = tuple(cargs[cb.index(c)] for c in ci.clbits) if ci.clbits else ()
            emitted.append((ci.operation, phys_qs, cl_refs))

    @staticmethod
    def _emit_circuit(emitted: list[tuple], n_phys: int) -> QuantumCircuit:
        """Build a routed ``QuantumCircuit`` from the emitted ``(op, phys_qs, cl_refs)`` stream."""
        qreg = QuantumRegister(n_phys, "q")
        out_qc = QuantumCircuit(qreg)
        # Qiskit's Rust DAG returns a fresh-but-equal ClassicalRegister on each
        # ``Clbit._register`` access, so dedupe by (name, size) — register names
        # are unique within a circuit. ``out_qc.append`` rebinds foreign clbits
        # to the registered creg by name+index.
        seen_cregs: set[tuple[str, int]] = set()
        for _, _, clbit_refs in emitted:
            for cb in clbit_refs:
                creg = cb._register if hasattr(cb, "_register") else None
                if creg is None:
                    continue
                key = (creg.name, creg.size)
                if key in seen_cregs:
                    continue
                out_qc.add_register(creg)
                seen_cregs.add(key)
        for op, phys_qs, clbit_refs in emitted:
            qubits = [qreg[p] for p in phys_qs]
            if clbit_refs:
                out_qc.append(op, qubits, list(clbit_refs))
            else:
                out_qc.append(op, qubits)
        return out_qc
