"""SABRE layout-and-routing over retained realization sets.

The outer loop follows Qiskit's O3 ``SabreLayout``: random and standard starting
layouts undergo alternating forward/backward refinement, then one multi-trial
forward route is retained per start. The best final route supplies the layout,
the routed circuit, and the output permutation. The kernel is
``crates/src/prism_routing/layout.rs``.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from dataclasses import replace as _dc_replace
from typing import TYPE_CHECKING

import numpy as np
import rustworkx
from qiskit import QuantumCircuit, QuantumRegister
from qiskit._accelerate.dense_layout import best_subset
from qiskit.circuit.library import SwapGate
from qiskit.converters import circuit_to_dag
from qiskit.dagcircuit import DAGCircuit, DAGOpNode
from qiskit.transpiler import CouplingMap, Layout, TranspilerError

from prism._accelerate import (
    BasicHeuristic,
    DecayHeuristic,
    Heuristic,
    LookaheadHeuristic,
    RoutingTarget,
    SetScaling,
    prism_layout_and_routing,
)
from prism.lowering.commit import (
    OBJECTIVES,
    SABRE_ITERATIONS,
    SABRE_TRIALS,
    CommitPolicy,
    CommitResult,
)
from prism.lowering.ir import LoweredOp
from prism.utils.metrics import active_gate_count, physical_depth

if TYPE_CHECKING:
    from prism.encodings.base import QubitEncoding


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
    diagonal: list[bool]
    n_phys: int
    n_virt: int
    cl_used: list[frozenset[int]]


Score = tuple[float, int, int]
"""Lexicographic post-selection score; lower is better. ``< Score`` compares as
expected. The field order depends on the objective (see ``score``): ``"swaps"``
sorts (swaps, depth, gates), ``"depth"`` sorts (depth, gates, size)."""


def score(qc: QuantumCircuit, objective: str = "swaps") -> Score:
    """Post-selection score for ``qc`` under ``objective``; lower is better.

    ``"swaps"`` minimizes the inserted SWAP count (the SABRE objective and the
    default), depth then gates as tiebreaks; ``"depth"`` minimizes the
    critical-path depth in non-free operations, then gates, then size.
    """
    d, g, sz = physical_depth(qc), active_gate_count(qc), qc.size()
    if objective == "swaps":
        return (qc.count_ops().get("swap", 0), d, g)
    return (d, g, sz)


class PrismRouting(CommitPolicy):
    """PRISM commit policy. Score: ``(basic_avg + 0.5 * ext_avg) * max(decay)`` with ``min``-over-candidates per op."""

    BEST_EPSILON = 1e-10
    # Diagonal ops commute with each other: route them as independent (per-rail) work.
    DIAGONAL_OPS = frozenset({"crz", "rz"})

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
    ) -> None:
        """Bind connectivity, search effort, and the route-selection ``objective``."""
        if coupling_map is None:
            raise ValueError("PrismRouting requires coupling_map")
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
        if objective not in OBJECTIVES:
            raise ValueError(
                f"objective must be one of {sorted(OBJECTIVES)}, got {objective!r}"
            )
        super().__init__(enc=enc)
        self.coupling_map = coupling_map
        self.seed = seed
        self.max_iterations = max(1, max_iterations)
        self.num_trials = max(1, num_trials)
        self.swap_trials = max(1, swap_trials)
        self.objective = objective

    @property
    def num_starts(self) -> int:
        """Random starts plus Qiskit's dense, identity, and reverse layouts."""
        return self.num_trials + 3

    def commit(self, dag: DAGCircuit) -> CommitResult:
        """Refine every start in the kernel, then keep the best final route by objective."""
        self.property_set["prism_objective"] = self.objective
        ctx = self._precompute(dag)
        base_seed = (
            self.seed
            if self.seed is not None
            else random.SystemRandom().getrandbits(64)
        )
        starts = self._starting_layouts(ctx, base_seed)
        results = prism_layout_and_routing(
            self._flatten_ctx(ctx),
            self._flatten_ctx(self._reversed_ctx(ctx)),
            RoutingTarget.from_coupling_list(
                list(self.coupling_map.get_edges()), ctx.n_phys
            ),
            self._make_heuristic(ctx.n_phys),
            [(int(seed) % (1 << 64), list(v2p)) for _kind, seed, v2p in starts],
            self.max_iterations,
            self.swap_trials,
        )
        best = None  # (score, out_qc, trace, refined_v2p); first start wins ties
        for events, final_v2p, n_swaps, refined_v2p in results:
            trace = (events, final_v2p, n_swaps)
            out_qc = self._emit_circuit_from_trace(trace, ctx, refined_v2p)
            final_score = score(out_qc, self.objective)
            if best is None or final_score < best[0]:
                best = (final_score, out_qc, trace, list(refined_v2p))
        payload = self._trace_to_payload(best[2], ctx)
        return self._build_result(dag, ctx, best[1], payload, best[3])

    def _make_heuristic(self, n_phys: int) -> Heuristic:
        """Qiskit's O3 ``"decay"`` heuristic, plus prism's load-balanced realization tie-break."""
        return Heuristic(
            basic=BasicHeuristic(1.0, SetScaling.Constant),
            lookahead=LookaheadHeuristic(0.5, 20, SetScaling.Size),
            decay=DecayHeuristic(0.001, 5),
            attempt_limit=10 * n_phys,
            best_epsilon=self.BEST_EPSILON,
        )

    @staticmethod
    def _flatten_ctx(ctx: "_Ctx") -> tuple:
        """Convert ``ctx`` to the flat precompute arrays passed to ``prism_layout_and_routing``."""
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

    def _starting_layouts(
        self, ctx: _Ctx, base_seed: int
    ) -> list[tuple[str, int, list[int]]]:
        """Build the deterministic layout pool for one compilation.

        ``num_trials`` seeded random layouts, then Qiskit's dense, identity,
        and reverse layouts.
        """
        starts: list[tuple[str, int, list[int]]] = []
        for trial in range(self.num_trials):
            seed = base_seed + trial
            v2p = list(range(ctx.n_phys))
            random.Random(seed).shuffle(v2p)
            starts.append(("random", seed, v2p))

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
        diagonal_rev = list(reversed(ctx.diagonal))
        cl_used_rev = list(reversed(ctx.cl_used))
        succ_rev, pred_count_rev = self._build_deps(
            virts_used_rev, diagonal_rev, cl_used_rev
        )
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
            cl_used=cl_used_rev,
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
        """Per-DAG precomputation: op caches and the dependency graph."""
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
            raise TranspilerError(
                f"the circuit needs {n_virt} physical qubits ({len(regs)} logical "
                f"x {self.enc.WIRES_PER_LOGICAL} wires) but the coupling map has "
                f"{n_phys}. Use a larger coupling map or fewer qubits."
            )
        virt_pairs, virts_used = self._precompute_op_data(op_nodes, q_to_virt)
        real_idx_map = [tuple(range(len(n.op.realizations))) for n in op_nodes]
        diagonal = [n.op.logical_name in self.DIAGONAL_OPS for n in op_nodes]
        c_to_idx = {c: i for i, c in enumerate(dag.clbits)}
        cl_used = [frozenset(c_to_idx[c] for c in n.cargs) for n in op_nodes]
        succ, pred_count = self._build_deps(virts_used, diagonal, cl_used)
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
            cl_used=cl_used,
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
        diagonal: list[bool],
        cl_used: list[frozenset[int]],
    ) -> tuple[list[list[int]], list[int]]:
        """Successor list + initial pred counts from per-op virt-usage sets.

        Ops flagged in ``diagonal`` (diagonal on every wire they touch: CRZ, RZ)
        commute with each other, so a diagonal op depends only on the last
        non-diagonal op per wire, and a non-diagonal op on everything since.
        ``cl_used`` adds classical bits as extra wires (measure writes, control
        flow reads), which only non-diagonal ops touch.
        """
        n_ops = len(virts_used)
        succ: list[list[int]] = [[] for _ in range(n_ops)]
        pred_count = [0] * n_ops
        last_nondiag: dict = {}
        diags_since: dict = {}
        for k, qs in enumerate(virts_used):
            vs = set(qs) | {("c", c) for c in cl_used[k]}
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

    # ---- Emission ----------------------------------------------------------

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
        """Emit the ``sub_idx``-th 2Q sub-gate of ``node.op.realizations[idx]``, together with any 1Q gates that fall between the previous 2Q sub-gate and this one.

        The Rust mini-SabreDAG only routes 2Q sub-gates, so ``sub_idx`` counts
        only those; intervening 1Q gates are emitted here at the current
        (post-swaps_before) layout. For the final 2Q sub-gate we also emit any
        trailing 1Q gates so the entire realization circuit appears exactly
        once across the sequence of SUB_GATE events.
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
