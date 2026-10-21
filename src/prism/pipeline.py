"""prism's pass managers: the stages, and ``dualrail_pm`` that runs them."""

from __future__ import annotations

from qiskit.circuit import IfElseOp
from qiskit.circuit.controlflow import CONTROL_FLOW_OP_NAMES
from qiskit.dagcircuit import DAGCircuit
from qiskit.passmanager import (
    ConditionalController,
    DoWhileController,
    MultiStagePassManager,
)
from qiskit.transpiler import CouplingMap, PassManager, Target
from qiskit.transpiler.passes import (
    BasisTranslator,
    CommutativeCancellation,
    CommutativeOptimization,
    ContractIdleWiresInControlFlow,
    Decompose,
    FixedPoint,
    HighLevelSynthesis,
    HLSConfig,
    InverseCancellation,
    Optimize1qGatesDecomposition,
    RemoveBarriers,
    RemoveDiagonalGatesBeforeMeasure,
    RemoveIdentityEquivalent,
    SabreSwap,
    Size,
    TrivialLayout,
    Unroll3qOrMore,
)
from qiskit.transpiler.preset_passmanagers.common import (
    generate_embed_passmanager,
    generate_routing_passmanager,
)

from prism import dualrail
from prism.passes import (
    DAGToMultiRealization,
    EarlyMeasurement,
    ElideLogicalPermutations,
    ElideRailExchanges,
    FenceErasureChecks,
    MCPrepare,
    MinRXCliffords,
    MultiRealizationToDAG,
    PrismRouting,
    RecordCircuitMetrics,
    RescheduleCommutingDiagonals,
    RetimeDiagonals,
    SearchBudget,
    SplitIfElse,
)


def logical_pm() -> PassManager:
    """Translate to ``dualrail.LOGICAL_ISA`` and simplify."""
    lib = dualrail.equivalence_library()
    gates = sorted(
        dualrail.LOGICAL_ISA
        - CONTROL_FLOW_OP_NAMES
        - {"measure", "reset", "erasure_check"}
    )
    return PassManager(
        [
            RemoveBarriers(),
            MCPrepare(),
            HighLevelSynthesis(hls_config=HLSConfig(mcx=["1_clean_kg24"])),
            Decompose(["c-unitary", "unitary"]),
            Unroll3qOrMore(basis_gates=["ccx"]),
            MinRXCliffords(lib, gates),
            BasisTranslator(lib, sorted(dualrail.LOGICAL_ISA | CONTROL_FLOW_OP_NAMES)),
            SplitIfElse(),
            # Before layout a SWAP only relabels logical qubits.
            ElideLogicalPermutations(),
            Optimize1qGatesDecomposition(basis=gates),
            # Removing an rz can expose a crz before a measurement.
            DoWhileController(
                [
                    RemoveDiagonalGatesBeforeMeasure(),
                    Size(recurse=True),
                    FixedPoint("size"),
                ],
                do_while=lambda property_set: not property_set["size_fixed_point"],
            ),
            EarlyMeasurement(),
        ]
    )


def physical_pm(coupling_map: CouplingMap, *, seed: int = 42) -> PassManager:
    """Stock cleanups, stock layout and routing for whatever is unplaced or off the edges, then prism's passes."""
    target = Target.from_configuration(
        basis_gates=sorted(dualrail.PHYSICAL_ISA | {"measure"}),
        custom_name_mapping=dualrail.CUSTOM_GATES,
        coupling_map=coupling_map,
    )
    target.add_instruction(IfElseOp, name="if_else")
    return PassManager(
        [
            FenceErasureChecks(),
            # The stock O3 init passes that apply to this ISA.
            RemoveDiagonalGatesBeforeMeasure(),
            RemoveIdentityEquivalent(),
            InverseCancellation(),
            ContractIdleWiresInControlFlow(),
            CommutativeCancellation(),
            ConditionalController(
                [
                    TrivialLayout(target),
                    *generate_embed_passmanager(target).to_flow_controller().tasks,
                ],
                condition=lambda ps: ps["layout"] is None,
            ),
            generate_routing_passmanager(
                SabreSwap(target, heuristic="decay", seed=seed, trials=20), target
            ).to_flow_controller(),
            CommutativeOptimization(),
            RemoveBarriers(),
            RescheduleCommutingDiagonals(),
            RecordCircuitMetrics(),
        ]
    )


def prism_stages(
    coupling_map: CouplingMap,
    *,
    seed: int = 42,
    budget: SearchBudget | None = None,
) -> MultiStagePassManager[DAGCircuit, DAGCircuit]:
    """Prism's stages on ``coupling_map``, a connected, undirected device graph.

    Replace a stage, then run ``PassManager([stages.to_flow_controller()])``.
    """
    routing = PrismRouting(coupling_map, seed=seed, budget=budget)
    return MultiStagePassManager(
        logical=logical_pm(),
        dag_to_multi_realization=DAGToMultiRealization(),
        multi_realization=[ElideRailExchanges(), routing, RetimeDiagonals()],
        multi_realization_to_dag=MultiRealizationToDAG(),
        physical=physical_pm(routing.coupling_map, seed=seed),
    )


def dualrail_pm(
    coupling_map: CouplingMap,
    *,
    seed: int = 42,
    budget: SearchBudget | None = None,
) -> PassManager:
    """A ``PassManager`` compiling circuits to dual-rail qubits on ``coupling_map``."""
    stages = prism_stages(coupling_map, seed=seed, budget=budget)
    return PassManager([stages.to_flow_controller()])
