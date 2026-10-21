"""The physical stage: stock passes over ``enc.PHYSICAL_ISA``, then prism's."""

from __future__ import annotations

from typing import TYPE_CHECKING

from qiskit.circuit import Barrier, IfElseOp
from qiskit.dagcircuit import DAGCircuit
from qiskit.passmanager import ConditionalController
from qiskit.transpiler import CouplingMap, PassManager, Target, TransformationPass
from qiskit.transpiler.passes import (
    CommutativeCancellation,
    CommutativeOptimization,
    ContractIdleWiresInControlFlow,
    InverseCancellation,
    RemoveBarriers,
    RemoveDiagonalGatesBeforeMeasure,
    RemoveIdentityEquivalent,
    SabreSwap,
    TrivialLayout,
)
from qiskit.transpiler.preset_passmanagers.common import (
    generate_embed_passmanager,
    generate_routing_passmanager,
)

from prism.ir import DIAGONAL_GATES, commuting_predecessors, list_schedule
from prism.metrics import RecordCircuitMetrics, is_free, only_ops

if TYPE_CHECKING:
    from prism.encodings.base import QubitEncoding


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


def _physical_target(enc: type[QubitEncoding], coupling_map: CouplingMap) -> Target:
    target = Target.from_configuration(
        basis_gates=sorted(enc.PHYSICAL_ISA | {"measure"}),
        custom_name_mapping=enc.CUSTOM_GATES,
        coupling_map=coupling_map,
    )
    target.add_instruction(IfElseOp, name="if_else")
    return target


def physical_pm(
    coupling_map: CouplingMap,
    enc: type[QubitEncoding],
    *,
    seed: int = 42,
) -> PassManager:
    """Stock cleanups, stock layout and routing for whatever is unplaced or off the edges, then prism's passes."""
    target = _physical_target(enc, coupling_map)
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
