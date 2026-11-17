"""3-stage ``StagedPassManager`` builder.

Stages: ``logical`` (input → ``enc.LOGICAL_ISA``), ``lowering`` (``LOGICAL_ISA``
→ routed wire-level circuit), ``physical`` (layout + route + opt on the chip).
``build_pm`` is the entrypoint; ``basic_logical_pm`` and ``physical_pm`` are
the reusable stage builders the encoding's default ``logical_pm`` /
``physical_pm`` methods call (and subclasses can call with custom args).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

import numpy as np
from qiskit.circuit import Measure
from qiskit.circuit.controlflow import (
    ControlFlowOp,
    ForLoopOp,
    IfElseOp,
    SwitchCaseOp,
    WhileLoopOp,
)
from qiskit.circuit.library import (
    CRZGate,
    MCPhaseGate,
    MCXGate,
    PermutationGate,
    RZGate,
    SwapGate,
    XGate,
)
from qiskit.dagcircuit import DAGCircuit
from qiskit.transpiler import (
    AnalysisPass,
    CouplingMap,
    DoWhileController,
    PassManager,
    StagedPassManager,
    Target,
    TransformationPass,
)
from qiskit.transpiler.passes import (
    BasisTranslator,
    ConsolidateBlocks,
    Decompose,
    ElidePermutations,
    HighLevelSynthesis,
    HLSConfig,
    Optimize1qGatesDecomposition,
    OptimizeSwapBeforeMeasure,
    RemoveBarriers,
    SabreLayout,
    SabreSwap,
    SetLayout,
    Unroll3qOrMore,
)
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

from marabbecca.lowering.commit import (
    SABRE_TRIALS,
    ApplyCommits,
    SearchBudget,
)
from marabbecca.lowering.commit_policies import (
    DirectCommit,
    PrismRouting,
    TrivialCommit,
)
from marabbecca.lowering.expansion import LowerExpansion
from marabbecca.synthesis.delocal_decomp import MCDecomposeWithAncilla
from marabbecca.synthesis.reschedule import RescheduleCommutingDiagonals
from marabbecca.utils.metrics import (
    RecordCircuitMetrics,
)
from marabbecca.utils.quotient import make_placement

if TYPE_CHECKING:
    from qiskit.circuit import EquivalenceLibrary, QuantumCircuit, Qubit

    from marabbecca.encodings.base import QubitEncoding


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CONTROL_FLOW_OPS: frozenset[str] = frozenset(
    {"if_else", "while_loop", "for_loop", "switch_case"}
)
NON_GATE_ISA_NAMES: frozenset[str] = CONTROL_FLOW_OPS | {
    "measure",
    "barrier",
    "reset",
    "erasure_check",
}

Strategy = Literal["trivial", "logical", "greedy", "prism"]


# ---------------------------------------------------------------------------
# Logical stage
# ---------------------------------------------------------------------------
def _unroll_target(enc: type[QubitEncoding], *, keep_mc: bool) -> Target:
    """Target for ``Unroll3qOrMore``: preserve 3Q+ gates we have downstream templates for."""
    # ``Unroll3qOrMore`` only unrolls 3Q+ gates not in the target. ``ccx`` is the
    # only 3Q gate we want to keep — DR's eq library has a 4-RX CCX template;
    # other 3Q+ inputs get unrolled. ``mcx``/``mcphase`` (when ``keep_mc=True``)
    # are added separately because they're parameterized.
    isa_gates = {n for n in enc.LOGICAL_ISA if n not in NON_GATE_ISA_NAMES}
    target = Target.from_configuration(basis_gates=sorted(isa_gates | {"ccx"}))
    target.add_instruction(Measure(), name="measure")
    if keep_mc:
        target.add_instruction(MCXGate(num_ctrl_qubits=4), name="mcx")
        target.add_instruction(MCPhaseGate(np.pi, num_ctrl_qubits=5), name="mcphase")
    return target


def basic_logical_pm(
    enc: type[QubitEncoding],
    *,
    eq_library: EquivalenceLibrary,
    reshape_passes: tuple = (),
) -> PassManager:
    """Standard cleanup → translate to ``enc.LOGICAL_ISA``.

    ``reshape_passes`` inserts encoding-specific reshapes between MC-ancilla
    expansion and ``BasisTranslator``; ``eq_library`` parameterizes translation.
    """
    isa_basis = sorted(enc.LOGICAL_ISA - NON_GATE_ISA_NAMES)
    return PassManager(
        [
            RemoveBarriers(),
            OptimizeSwapBeforeMeasure(),
            HighLevelSynthesis(hls_config=HLSConfig(mcx=[], mcphase=[])),
            Decompose(["c-unitary", "unitary"]),
            Unroll3qOrMore(target=_unroll_target(enc, keep_mc=True)),
            MCDecomposeWithAncilla(),
            Decompose(["rccx", "rccx_dg"]),
            Unroll3qOrMore(target=_unroll_target(enc, keep_mc=False)),
            *reshape_passes,
            BasisTranslator(eq_library, sorted(enc.LOGICAL_ISA | CONTROL_FLOW_OPS)),
            Optimize1qGatesDecomposition(basis=isa_basis),
        ]
    )


class ElideLogicalPermutations(ElidePermutations):
    """Elide semantic permutations without leaking a logical-width layout.

    Qiskit's :class:`ElidePermutations` records the removed permutation as a
    virtual layout.  That layout cannot cross an encoding boundary that
    replaces each logical qubit with several physical wires.  Preserve the
    logical input-to-output permutation explicitly, attach it to the circuit
    metadata, and clear only the incompatible Qiskit layout bookkeeping.

    ``logical_output_permutation[i] = j`` means that the state entering on
    logical wire ``i`` leaves on logical wire ``j``.
    """

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Remove logical permutation operations and preserve their net effect."""
        permutation_ops = sum(
            isinstance(node.op, (SwapGate, PermutationGate)) for node in dag.op_nodes()
        )
        out_dag = super().run(dag)

        virtual_layout = self.property_set.get("virtual_permutation_layout")
        if virtual_layout is None:
            permutation = tuple(range(len(out_dag.qubits)))
        else:
            permutation = tuple(virtual_layout[q] for q in out_dag.qubits)

        self.property_set["logical_output_permutation"] = permutation
        self.property_set["logical_permutation_ops_elided"] = permutation_ops
        out_dag.metadata = dict(out_dag.metadata or {})
        out_dag.metadata["logical_output_permutation"] = list(permutation)

        # These layouts are keyed by logical qubit objects.  Leaving them in
        # the property set makes the physical ApplyLayout pass try to compose
        # them with the expanded rail-level DAG.
        self.property_set["virtual_permutation_layout"] = None
        self.property_set["original_layout"] = None
        return out_dag


class RecordQuotientPartition(AnalysisPass):
    """Publish the fixed physical pairs and induced logical graph."""

    def __init__(
        self,
        pairs: list[tuple[int, int]],
        quotient_coupling_map: CouplingMap,
    ) -> None:
        """Store the physical pairs and the quotient graph's edges and size."""
        super().__init__()
        self.pairs = tuple(tuple(pair) for pair in pairs)
        self.quotient_edges = tuple(
            sorted({tuple(sorted(edge)) for edge in quotient_coupling_map.get_edges()})
        )
        self.quotient_size = quotient_coupling_map.size()

    def run(self, _dag: DAGCircuit) -> None:
        """Publish the stored partition to the property set."""
        self.property_set["quotient_partition_pairs"] = self.pairs
        self.property_set["quotient_graph_edges"] = self.quotient_edges
        self.property_set["quotient_graph_size"] = self.quotient_size


class SafeOptimizeSwapBeforeMeasure(TransformationPass):
    """Run terminal-SWAP cleanup only when the circuit has no control flow.

    Qiskit 2.4.1 recursively removes a trailing SWAP from a control-flow block
    even when the parent circuit continues to use the qubits. In dual-rail
    circuits this can erase a conditional logical-X correction.
    """

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Run ``OptimizeSwapBeforeMeasure`` unless the DAG has control flow."""
        if any(isinstance(node.op, ControlFlowOp) for node in dag.op_nodes()):
            self.property_set["swap_before_measure_skipped_for_control_flow"] = True
            return dag
        cleanup = OptimizeSwapBeforeMeasure()
        cleanup.property_set = self.property_set
        return cleanup.run(dag)


# ---------------------------------------------------------------------------
# Physical stage
# ---------------------------------------------------------------------------
class CountRouterSwaps(AnalysisPass):
    """Add the SWAPs that the physical stage's layout and routing insert to ``routing_swaps``.

    ``physical_pm`` runs one instance before layout (``sign=-1``) and one after
    routing (``sign=1``), so their net change is the inserted SWAP count. Both
    run after O3 init, which may cancel adjacent semantic SWAP bodies.
    """

    def __init__(self, sign: int) -> None:
        """Store the sign applied to the current SWAP count."""
        super().__init__()
        self.sign = sign

    def run(self, dag: DAGCircuit) -> None:
        """Add ``sign`` times the DAG's SWAP count to ``routing_swaps``."""
        swaps = dag.count_ops(recurse=False).get("swap", 0)
        self.property_set["routing_swaps"] += self.sign * swaps


class SeedVF2ErrorMap(AnalysisPass):
    """Publish a deterministic ``vf2_avg_error_map`` so VF2PostLayout replays.

    The target carries no error rates, so the Rust vf2 pass builds its own
    average error map with per-process iteration order and the accepted
    post-layout is not same-seed reproducible across processes (metrics are
    unaffected; only the final placement of tail ops wanders). A degree-proxy
    map with a strictly unique score per qubit and per edge makes the
    selection deterministic. Scoped to ``pre_routing`` so the layout stage
    (``VF2Layout`` for strategies that publish no layout) keeps stock scoring.
    """

    def __init__(self, coupling_map: CouplingMap) -> None:
        """Store the coupling map used to build the error map."""
        super().__init__()
        self._coupling_map = coupling_map

    def run(self, _dag: DAGCircuit) -> None:
        """Publish a degree-proxy ``vf2_avg_error_map``."""
        from qiskit.transpiler.passes.layout.vf2_utils import ErrorMap

        n = self._coupling_map.size()
        edges = sorted({tuple(sorted(e)) for e in self._coupling_map.get_edges()})
        degree = dict.fromkeys(range(n), 0)
        for a, b in edges:
            degree[a] += 1
            degree[b] += 1
        error_map = ErrorMap(n + 2 * len(edges))
        for q in range(n):
            error_map.add_error((q, q), degree[q] / n * 1e-3 + q * 1e-9)
        for a, b in edges:
            err = (degree[a] + degree[b]) / (2 * n) * 1e-2 + (a * n + b) * 1e-9
            error_map.add_error((a, b), err)
            error_map.add_error((b, a), err)
        self.property_set["vf2_avg_error_map"] = error_map


class CancelRailX(TransformationPass):
    """Cancel spurious ``rx(π)`` (X-on-rail) by propagating it as an X-frame.

    O3's 2Q-block consolidation legitimately shrinks the circuit, but its generic
    KAK synthesis straddles the entangler with ``rx(π)`` 1Q frames (X-on-rail)
    with no preference for the X-free form. On a delocalized rail that ``rx(π)``
    is a forbidden single-rail X: a leakage window, and it mis-types an inter-rail
    ``crz`` as a cheap intra-rail ``rx`` in the noise model. The frames come in
    cancelling pairs, so we push each ``rx(π)`` rightward as a Pauli-X frame
    (``X·rz(θ) = rz(-θ)·X``; ``X_t·crz(θ) = crz(-θ)·X_t``; ``X_c·crz(θ) =
    rz(θ)_t·crz(-θ)·X_c``; X rides through ``swap``) until pairs annihilate. Exact
    (global phase tracked); the prep ``x`` and any frame that survives to a
    measurement / non-diagonal gate are materialized as ``x`` and left.
    """

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Propagate ``rx(π)`` frames rightward and emit the reduced DAG."""
        new = dag.copy_empty_like()
        frame: dict = {}

        def materialize(w: Qubit) -> None:
            if frame.get(w):
                new.apply_operation_back(XGate(), (w,))
                frame[w] = False

        for node in dag.topological_op_nodes():
            op, qa, name = node.op, node.qargs, node.op.name
            if name == "rx" and abs(float(op.params[0]) % (2 * np.pi) - np.pi) < 1e-9:
                frame[qa[0]] = not frame.get(qa[0], False)
                new.global_phase -= float(op.params[0]) / 2  # rx(θ≡π) = e^{-iθ/2} X
            elif name == "rz":
                th = float(op.params[0])
                new.apply_operation_back(
                    RZGate(-th if frame.get(qa[0]) else th), (qa[0],)
                )
            elif name == "crz":
                c, t = qa
                th, fc, ft = (
                    float(op.params[0]),
                    frame.get(c, False),
                    frame.get(t, False),
                )
                new.apply_operation_back(CRZGate(-th if fc ^ ft else th), (c, t))
                if fc:  # X on control leaves an Rz on the target
                    new.apply_operation_back(RZGate(th if not ft else -th), (t,))
            elif name == "swap":
                a, b = qa
                frame[a], frame[b] = frame.get(b, False), frame.get(a, False)
                new.apply_operation_back(SwapGate(), (a, b))
            else:  # prep x, rswap, measure, barrier: materialize then emit
                for w in qa:
                    materialize(w)
                new.apply_operation_back(op, qa, node.cargs)
        for w in list(frame):
            materialize(w)
        return new


def _physical_target(enc: type[QubitEncoding], coupling_map: CouplingMap) -> Target:
    """Build the physical-stage Target with Measure + control-flow ops registered opaquely."""
    target = Target.from_configuration(
        basis_gates=sorted(enc.PHYSICAL_ISA),
        custom_name_mapping=enc.custom_name_mapping(),
        coupling_map=coupling_map,
    )
    target.add_instruction(Measure(), name="measure")
    target.add_instruction(IfElseOp, name="if_else")
    target.add_instruction(WhileLoopOp, name="while_loop")
    target.add_instruction(ForLoopOp, name="for_loop")
    target.add_instruction(SwitchCaseOp, name="switch_case")
    return target


def physical_pm(
    coupling_map: CouplingMap,
    enc: type[QubitEncoding],
    *,
    seed: int = 42,
    resynthesize: bool = True,
    use_lowering_route: bool = False,
    reschedule: bool = False,
) -> PassManager:
    """Preset layout+route+opt over ``enc.PHYSICAL_ISA``, plus final metrics.

    ``use_lowering_route=True`` keeps the layout and route the lowering stage
    produced and skips the preset layout and routing stages.

    ``resynthesize=True`` (universal-ISA codes, e.g. DualRail) runs preset O3,
    whose 2Q-block consolidation + ``UnitarySynthesis`` re-optimize freely.
    ``resynthesize=False`` (restricted-Clifford codes, e.g. RepCode/Iceberg)
    drops to level 0 (pure layout + route + translate): O3's resynthesis would
    both emit gates outside a non-universal ISA (``u`` ∉ {x,z,cx,swap}) and
    re-derive the logical unitary across the code boundary, collapsing the
    transversal structure we are routing.

    ``reschedule=True`` re-emits the final circuit by critical-path order over
    a dependency graph where diagonal gates commute, before the final metrics.
    """
    preset = generate_preset_pass_manager(
        optimization_level=3 if resynthesize else 0,
        target=_physical_target(enc, coupling_map),
        seed_transpiler=seed,
    )
    # Strip ``ElidePermutations`` (init) and ``SetLayout(None)`` (layout):
    # both no-op once a layout is set, and commit policies that publish a
    # layout write straight to ``property_set["layout"]``. ElidePermutations
    # also can't be moved earlier, its ``virtual_permutation_layout`` would be
    # keyed on the lowering DAG's qubits while ``original_qubit_indices`` is
    # frozen to the original input's qregs, breaking ``ApplyLayout``'s
    # composition.
    preset.init = PassManager(
        [
            t
            for t in preset.init.to_flow_controller().tasks
            if not isinstance(t, ElidePermutations | ConsolidateBlocks)
        ]
    )
    # Drop O3's 2Q-block consolidation: generic KAK resynthesis of a rail-pair
    # block puts rx(±π/2) on single rails, which the X-free lowering forbids.
    # Without consolidated blocks, the loop's UnitarySynthesis has nothing to do.
    loop = preset.optimization.to_flow_controller().tasks
    for task in loop:
        if isinstance(task, DoWhileController):
            task.tasks = tuple(
                t for t in task.tasks if not isinstance(t, ConsolidateBlocks)
            )
    preset.optimization = PassManager(list(loop))
    post_routing = [SafeOptimizeSwapBeforeMeasure()]
    if use_lowering_route:
        # The lowering stage already laid out and routed the circuit. Running
        # the preset's layout or routing stage again would spend another SABRE
        # budget and discard the route associated with that layout.
        preset.layout = PassManager()
        preset.routing = PassManager()
    else:
        preset.layout = PassManager(
            [
                t
                for t in preset.layout.to_flow_controller().tasks
                if not isinstance(t, SetLayout)
            ]
        )
        # The count starts before the LAYOUT stage because a strategy that
        # publishes no layout (trivial) is routed inside O3's SabreLayout.
        preset.pre_layout = PassManager([CountRouterSwaps(sign=-1)])
        preset.pre_routing = PassManager([SeedVF2ErrorMap(coupling_map)])
        post_routing.insert(0, CountRouterSwaps(sign=1))
    preset.post_routing = PassManager(post_routing)
    # Level 0 has no optimization stage; record after translation instead.
    # ``CancelRailX`` strips the X-on-rail that O3's 2Q resynthesis leaves behind
    # (no-op at level 0, which does no resynthesis).
    tail = [RescheduleCommutingDiagonals()] if reschedule else []
    if resynthesize:
        preset.post_optimization = PassManager(
            [CancelRailX(), *tail, RecordCircuitMetrics()]
        )
    else:
        preset.post_translation = PassManager([*tail, RecordCircuitMetrics()])
    return preset


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------
def build_pm(
    coupling_map: CouplingMap,
    enc: type[QubitEncoding],
    *,
    strategy: Strategy = "prism",
    seed: int = 42,
    objective: str = "swaps",
    budget: SearchBudget | None = None,
    commute_diagonal: bool | str = False,
    reschedule: bool = False,
    front_commit: bool = False,
    front_commit_witness: bool = True,
    wait_scale: float = 0.0,
    wait_realizations: bool = True,
    wait_mode: str = "additive",
    route_score: Callable[[QuantumCircuit], float] | None = None,
) -> StagedPassManager:
    """3-stage PM for ``enc`` on ``coupling_map``. ``strategy`` selects the lowering algorithm.

    ``greedy`` and ``prism`` are the paper's Greedy and PRISM arms: the same
    ``PrismRouting`` layout-and-routing search, with realizations fixed at
    each routing call's entry layout (``greedy``) or retained (``prism``).
    ``logical`` is Logical-SABRE and ``trivial`` takes every default.

    ``objective`` tunes retained-route selection for ``greedy`` and
    ``prism``: ``"swaps"`` (the default, matching SABRE) or the
    yield-oriented ``"depth"`` / ``"duration"`` knob. Other strategies do not
    perform this outer trial selection. ``budget`` (a ``SearchBudget``) sets
    the start/iteration counts, heuristic config, and tie-break of those two
    strategies; ``None`` means ``SearchBudget()``, the stock O3 effort (20
    starts, 4 refinement iterations, 20 final-route trials, ``qiskit_sabre``,
    ``default`` tie-break). The paper's evaluation budget (40/16/40, ``load``
    tie-break) is passed explicitly by ``scripts/paper/run_fairness.py``. Both
    strategies retain the final route returned by their combined layout search
    and do not run an independent physical router. For ``logical`` the budget's
    three counts set the quotient-graph ``SabreLayout`` (``layout_starts``
    random starts plus Qiskit's dense, identity and reverse ones,
    ``refinement_iterations`` forward-backward pairs, ``prism_swap_trials``
    trials per start's final route); ``None`` keeps the stock 20/4/20 of the
    submitted rows. The quotient ``SabreSwap`` after it adds no SWAPs, since
    ``SabreLayout`` already routes.

    ``commute_diagonal`` lets commuting diagonal gates (CRZ, RZ) leave program
    order in the routing dependency graph; only ``greedy`` and ``prism``
    support it. ``reschedule`` re-emits the final physical circuit by
    critical-path order over the same relaxed dependencies, for any strategy.
    Both default off, which reproduces the revision r2 results.

    ``front_commit`` (``prism`` only) is the front-layer-commit ablation: each
    retained set freezes to its closest realization when it enters the front
    layer. Like ``greedy`` and ``prism`` it keeps its own final route.
    ``front_commit_witness=False`` drops its second change, scoring lookahead-set
    gates on one witness realization, so only the commit time differs from ``prism``.

    ``objective="custom"`` uses ``route_score(qc)`` to select the final route,
    with active gate count and size as tie breakers. It supports both kernel
    strategies and leaves their routing search and effort unchanged.
    """
    kernel = strategy in ("greedy", "prism")
    if (objective == "custom") != (route_score is not None):
        raise ValueError(
            "objective='custom' requires route_score; other objectives do not accept it"
        )
    if route_score is not None and not kernel:
        raise ValueError("route_score requires strategy 'greedy' or 'prism'")
    if commute_diagonal and not kernel:
        raise ValueError(
            f"commute_diagonal needs the PRISM routing kernel; strategy {strategy!r}"
        )
    if front_commit and strategy != "prism":
        raise ValueError(f"front_commit needs strategy 'prism', got {strategy!r}")
    if budget is not None and budget.objective != objective:
        raise ValueError(
            f"budget.objective {budget.objective!r} != objective {objective!r}"
        )
    if strategy == "trivial":
        lowering = [
            LowerExpansion(enc=enc),
            TrivialCommit(enc=enc, seed=seed),
        ]
    elif strategy == "logical":
        b = budget or SearchBudget(objective=objective)
        if (b.heuristic_config, b.tie_break) != ("qiskit_sabre", "default"):
            raise ValueError("Logical-SABRE takes only the budget's three counts")
        pairs, quotient_cm = make_placement(coupling_map)
        lowering = [
            RecordQuotientPartition(pairs, quotient_cm),
            SabreLayout(
                quotient_cm,
                seed=seed,
                max_iterations=b.refinement_iterations,
                layout_trials=b.layout_starts,
                swap_trials=b.prism_swap_trials,
            ),
            SabreSwap(quotient_cm, heuristic="decay", seed=seed, trials=SABRE_TRIALS),
            LowerExpansion(enc=enc),
            DirectCommit(coupling_map, pairs=pairs, enc=enc),
        ]
    elif kernel:
        b = budget or SearchBudget(objective=objective)
        lowering = [
            LowerExpansion(enc=enc),
            PrismRouting(
                coupling_map,
                enc=enc,
                seed=seed,
                objective=objective,
                num_trials=b.layout_starts,
                max_iterations=b.refinement_iterations,
                swap_trials=b.prism_swap_trials,
                heuristic_config=b.heuristic_config,
                tie_break=b.tie_break,
                binding_mode="greedy" if strategy == "greedy" else "retained",
                start_mode="qiskit_o3",
                commute_diagonal=commute_diagonal,
                reschedule=reschedule,
                front_commit=front_commit,
                front_commit_witness=front_commit_witness,
                wait_scale=wait_scale,
                wait_realizations=wait_realizations,
                wait_mode=wait_mode,
                route_score=route_score,
            ),
        ]
    else:
        raise ValueError(
            f"unknown strategy {strategy!r}; "
            "expected 'trivial', 'logical', 'greedy', or 'prism'"
        )
    return StagedPassManager(
        stages=["logical", "lowering", "physical"],
        logical=enc.logical_pm(),
        lowering=PassManager([*lowering, ApplyCommits()]),
        physical=enc.physical_pm(
            coupling_map,
            seed=seed,
            use_lowering_route=kernel,
            reschedule=reschedule,
        ),
    )
