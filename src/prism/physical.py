"""Physical stage over ``enc.PHYSICAL_ISA``: stock cleanups, layout and routing, then prism's passes."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from qiskit.circuit import Barrier, IfElseOp, ParameterExpression
from qiskit.circuit.library import CRZGate, RZGate
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
    """Put a ``Barrier`` on each side of every erasure check (``pauli_product_measurement``).

    The user places each check, so no gate may cross it. Qiskit's commutation
    checker finds that the ZZ check commutes with ``rz`` and ``crz``, so
    ``CommutativeOptimization`` would merge gates across it; a barrier commutes
    with nothing. The logical stage removes barriers, so ``RemoveBarriers``
    after the commutation passes removes only these.
    """

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Fence each check of ``dag`` on its qubits."""
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
    """Critical-path list scheduling over a dependency graph where diagonal gates commute.

    Routing emits gates in commit order. Physical diagonal gates on shared
    rails commute, so the emitted order is one of many; this pass re-emits the
    circuit in the order of ``list_schedule`` over the commutation-relaxed
    dependency graph. List scheduling is a heuristic: it usually shortens the
    circuit but does not guarantee it.
    """

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Re-emit ``dag`` in a depth-minimizing order that respects the relaxed dependencies."""
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


class FoldCRZAngles(TransformationPass):
    """Fold each ``crz`` angle into ``[0, 2π)``, the phase an SWS gate waits for.

    The SWS conditional phase builds up while the photon waits in the coupler,
    with one sign, so ``crz(θ)`` waits for ``θ mod 2π``. Since ``crz(θ + 2π)``
    is ``crz(θ)`` times ``Z = i·rz(π)`` on the control, each angle folds into
    that range with at most one free ``rz(π)``, and ``crz(2πk)`` is no SWS at all.
    """

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Replace each bound ``crz`` angle outside ``[0, 2π)``."""
        for node in dag.named_nodes("crz"):
            theta = node.op.params[0]
            if isinstance(theta, ParameterExpression):
                continue
            turns, folded = divmod(theta, 2 * math.pi)
            if math.isclose(folded, 2 * math.pi):
                turns, folded = turns + 1, 0.0
            if folded == theta:
                continue
            block = DAGCircuit()
            block.add_qubits(node.qargs)
            if folded:
                block.apply_operation_back(CRZGate(folded), node.qargs)
            if turns % 2:
                block.apply_operation_back(RZGate(math.pi), node.qargs[:1])
                block.global_phase = math.pi / 2
            dag.substitute_node_with_dag(node, block)
        return dag


def _physical_target(enc: type[QubitEncoding], coupling_map: CouplingMap) -> Target:
    """``enc.PHYSICAL_ISA`` on each qubit or edge, plus measure and ``if_else``."""
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
    """The physical stage: stock cleanups, layout and routing for what is left, then prism's passes.

    An unplaced program gets the stock trivial layout; ``SabreSwap`` routes only
    if ``CheckMap`` finds a gate off the device edges.
    """
    target = _physical_target(enc, coupling_map)
    return PassManager(
        [
            FenceErasureChecks(),
            # The passes of the stock O3 init stage that act on this ISA.
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
            FoldCRZAngles(),
            CommutativeOptimization(),
            RemoveBarriers(),
            RescheduleCommutingDiagonals(),
            RecordCircuitMetrics(),
        ]
    )
