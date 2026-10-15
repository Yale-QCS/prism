"""``build_pm``: the end-to-end ``MultiStagePassManager``.

Stages and their IRs::

    input     QuantumCircuit -> DAGCircuit
    logical   DAGCircuit -> DAGCircuit         enc.logical_pm()
    expand    DAGCircuit -> LoweredProgram     ExpandStage
    commit    LoweredProgram -> LoweredProgram PrismRouting: place, route, pick realizations
    lower     LoweredProgram -> DAGCircuit     lowering metrics, then the retained route
    physical  DAGCircuit -> DAGCircuit         enc.physical_pm(): stock O3 on the routed circuit
    output    DAGCircuit -> QuantumCircuit     attaches TranspileLayout
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qiskit.converters import circuit_to_dag, dag_to_circuit
from qiskit.dagcircuit import DAGCircuit
from qiskit.passmanager import GenericPass, MultiStagePassManager, PropertySet
from qiskit.transpiler import CouplingMap, TranspileLayout

from prism.lowering.commit import CommitStage, SearchBudget
from prism.lowering.commit_policies import PrismRouting
from prism.lowering.expansion import ExpandStage
from prism.lowering.ir import LoweredProgram
from prism.physical import guard_commutation_passes
from prism.utils.metrics import RecordCircuitMetrics

if TYPE_CHECKING:
    from collections.abc import Callable

    from qiskit.circuit import QuantumCircuit

    from prism.encodings.base import QubitEncoding


class InstallLoweringRoute(GenericPass):
    """``LoweredProgram -> DAGCircuit``: the physical DAG is the route the search retained."""

    def run(self, passmanager_ir: LoweredProgram) -> DAGCircuit:
        """Install the retained route and its output permutation."""
        prog = passmanager_ir
        if prog.routed_dag is None:
            raise RuntimeError("combined layout-and-routing produced no routed DAG")
        if prog.layout is not None:
            self.property_set["layout"] = prog.layout
        self.property_set["final_layout"] = prog.routed_final_layout
        return prog.routed_dag


class RecordProgramMetrics(GenericPass):
    """``LoweredProgram -> LoweredProgram``: ``RecordCircuitMetrics`` over the committed DAG."""

    def __init__(self, key: str = "circuit_metrics") -> None:
        """Store the property-set key the metrics are published under."""
        super().__init__()
        self.key = key

    def run(self, passmanager_ir: LoweredProgram) -> LoweredProgram:
        """Publish metrics of the committed rail-wire DAG; the program is unchanged."""
        rec = RecordCircuitMetrics(key=self.key)
        rec.property_set = self.property_set
        rec.run(passmanager_ir.committed_dag())
        return passmanager_ir


class CircuitToDAG(GenericPass):
    """``QuantumCircuit -> DAGCircuit``; records what ``TranspileLayout`` needs at the end."""

    def run(self, passmanager_ir: QuantumCircuit) -> DAGCircuit:
        """Convert the input circuit and remember its qubit identities."""
        self.property_set["original_qubit_indices"] = {
            bit: i for i, bit in enumerate(passmanager_ir.qubits)
        }
        self.property_set["num_input_qubits"] = passmanager_ir.num_qubits
        return circuit_to_dag(passmanager_ir, copy_operations=True)


class DAGToCircuit(GenericPass):
    """``DAGCircuit -> QuantumCircuit`` with the ``TranspileLayout`` attached."""

    def run(self, passmanager_ir: DAGCircuit) -> QuantumCircuit:
        """Convert the final DAG and attach the layout the physical stage produced."""
        qc = dag_to_circuit(passmanager_ir, copy_operations=False)
        qc._layout = TranspileLayout.from_property_set(
            passmanager_ir, self.property_set
        )
        return qc


class PrismPassManager(MultiStagePassManager):
    """``build_pm``'s pipeline. Keeps a ``property_set`` attribute callers read after ``run``."""

    def __init__(self, **stages) -> None:
        """Create the named stages and an empty property set."""
        super().__init__(**stages)
        self.property_set = PropertySet()

    def run(
        self,
        circuit: QuantumCircuit,
        callback: Callable | None = None,
        *,
        property_set: PropertySet | None = None,
    ) -> QuantumCircuit:
        """Compile one circuit; the property set used is left on ``self.property_set``."""
        self.property_set = PropertySet() if property_set is None else property_set
        return super().run(circuit, callback, property_set=self.property_set)


def build_pm(
    coupling_map: CouplingMap,
    enc: type[QubitEncoding],
    *,
    seed: int = 42,
    budget: SearchBudget | None = None,
) -> PrismPassManager:
    """Pipeline compiling ``enc``-encoded circuits onto ``coupling_map``.

    ``budget`` sets the search effort and the route-selection objective
    (``swaps`` or ``depth``); ``None`` uses the ``SearchBudget`` defaults.
    """
    b = budget or SearchBudget()
    policy = PrismRouting(
        coupling_map,
        enc=enc,
        seed=seed,
        objective=b.objective,
        num_trials=b.layout_starts,
        max_iterations=b.refinement_iterations,
        swap_trials=b.swap_trials,
    )
    pm = PrismPassManager(
        input=CircuitToDAG(),
        logical=enc.logical_pm(),
        expand=ExpandStage(enc=enc),
        commit=CommitStage(policy),
        lower=[
            RecordProgramMetrics(key="lowering_circuit_metrics"),
            InstallLoweringRoute(),
        ],
        physical=enc.physical_pm(coupling_map, seed=seed),
        output=DAGToCircuit(),
    )
    guard_commutation_passes(pm)
    return pm
