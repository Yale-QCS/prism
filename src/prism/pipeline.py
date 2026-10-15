"""``build_pm``: the end-to-end ``MultiStagePassManager``.

Stages and their IRs::

    input     QuantumCircuit -> DAGCircuit
    logical   DAGCircuit -> DAGCircuit         enc.logical_pm()
    expand    DAGCircuit -> LoweredProgram     ExpandStage
    commit    LoweredProgram -> LoweredProgram PrismRouting: place, route, pick realizations
    lower     LoweredProgram -> DAGCircuit     the retained route
    physical  DAGCircuit -> DAGCircuit         enc.physical_pm(): stock O3 on the routed circuit
    output    DAGCircuit -> QuantumCircuit     attaches TranspileLayout
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qiskit.converters import circuit_to_dag, dag_to_circuit
from qiskit.dagcircuit import DAGCircuit
from qiskit.passmanager import GenericPass, MultiStagePassManager
from qiskit.transpiler import CouplingMap, TranspileLayout

from prism.lowering.commit import CommitStage, SearchBudget
from prism.lowering.commit_policies import PrismRouting
from prism.lowering.expansion import ExpandStage
from prism.lowering.ir import LoweredProgram

if TYPE_CHECKING:
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


def build_pm(
    coupling_map: CouplingMap,
    enc: type[QubitEncoding],
    *,
    seed: int = 42,
    budget: SearchBudget | None = None,
) -> MultiStagePassManager:
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
    pm = MultiStagePassManager(
        input=CircuitToDAG(),
        logical=enc.logical_pm(),
        expand=ExpandStage(enc=enc),
        commit=CommitStage(policy),
        lower=InstallLoweringRoute(),
        physical=enc.physical_pm(coupling_map, seed=seed),
        output=DAGToCircuit(),
    )
    return pm
