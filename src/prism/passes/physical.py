"""Passes of the ``physical`` stage, on ``DAGCircuit``."""

from __future__ import annotations

from qiskit.circuit import Barrier
from qiskit.converters import dag_to_circuit
from qiskit.dagcircuit import DAGCircuit
from qiskit.transpiler import AnalysisPass, TransformationPass

from prism.ir import DIAGONAL_GATES, commuting_predecessors, list_schedule
from prism.metrics import CircuitMetrics, is_free, only_ops


class FenceErasureChecks(TransformationPass):
    """Put a barrier on each side of every erasure check, so that no gate crosses it.

    The ZZ check commutes with ``rz`` and ``crz``, so ``CommutativeOptimization``
    would otherwise merge gates across a check the user placed.
    """

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        for node in dag.named_nodes("pauli_product_measurement"):
            block = DAGCircuit()
            block.add_qubits(node.qargs)
            block.add_clbits(node.cargs)
            fence = Barrier(len(node.qargs))
            block.apply_operation_back(fence, node.qargs)
            block.apply_operation_back(node.op, node.qargs, node.cargs)
            block.apply_operation_back(fence, node.qargs)
            dag.substitute_node_with_dag(node, block)
        return dag


class RescheduleCommutingDiagonals(TransformationPass):
    """Reorder commuting diagonal gates by critical-path list scheduling, for depth."""

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        nodes = list(dag.topological_op_nodes())
        wires = [(*node.qargs, *node.cargs) for node in nodes]
        preds = commuting_predecessors(
            wires, [only_ops(node.op, DIAGONAL_GATES) for node in nodes]
        )
        weight = [0 if is_free(node.op) else 1 for node in nodes]
        out = dag.copy_empty_like()
        for k in list_schedule(preds, wires, weight):
            out.apply_operation_back(nodes[k].op, nodes[k].qargs, nodes[k].cargs)
        return out


class RecordCircuitMetrics(AnalysisPass):
    """Set ``property_set["circuit_metrics"]``."""

    def run(self, dag: DAGCircuit) -> None:
        self.property_set["circuit_metrics"] = CircuitMetrics.of(dag_to_circuit(dag))
