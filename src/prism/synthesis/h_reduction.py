"""Hadamard-reduction peephole (Nam-Maslov 1710.07345 §4.4): drop H pairs that sandwich a CX.

Patterns: ``(H⊗H) · CX(c,t) · (H⊗H) → CX(t,c)`` and ``H_t · CX(c,t) · H_t → CZ(c,t)``.
Each is unitarity-preserving up to global phase. Reduces RX after BasisTranslator.
"""

from __future__ import annotations

from qiskit import QuantumCircuit
from qiskit.circuit import Qubit
from qiskit.circuit.library import CZGate
from qiskit.converters import circuit_to_dag
from qiskit.dagcircuit import DAGCircuit, DAGOpNode
from qiskit.transpiler import TransformationPass


def _single_qubit_pred(dag: DAGCircuit, node: DAGOpNode, q: Qubit) -> DAGOpNode | None:
    """Immediate 1Q predecessor of ``node`` on wire ``q``, or ``None``."""
    q_idx = dag.find_bit(q).index
    for p in dag.predecessors(node):
        if isinstance(p, DAGOpNode) and len(p.qargs) == 1:
            if dag.find_bit(p.qargs[0]).index == q_idx:
                return p
    return None


def _single_qubit_succ(dag: DAGCircuit, node: DAGOpNode, q: Qubit) -> DAGOpNode | None:
    """Immediate 1Q successor of ``node`` on wire ``q``, or ``None``."""
    q_idx = dag.find_bit(q).index
    for s in dag.successors(node):
        if isinstance(s, DAGOpNode) and len(s.qargs) == 1:
            if dag.find_bit(s.qargs[0]).index == q_idx:
                return s
    return None


class HadamardReduction(TransformationPass):
    """Apply the two Nam-Maslov H-reduction patterns to ``CX`` nodes."""

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Apply local Hadamard rewrites where patterns match."""
        m1 = 0
        m4 = 0
        # Snapshot to avoid mutation-during-iteration issues.
        for cx in list(dag.op_nodes()):
            if cx.op.name != "cx":
                continue
            # Note: this CX might have been substituted-out earlier; skip if so.
            if cx not in dag.op_nodes():
                continue
            c, t = cx.qargs
            pre_c = _single_qubit_pred(dag, cx, c)
            pre_t = _single_qubit_pred(dag, cx, t)
            suc_c = _single_qubit_succ(dag, cx, c)
            suc_t = _single_qubit_succ(dag, cx, t)

            def n(x: DAGOpNode | None) -> str | None:
                return None if x is None else x.op.name

            # Pattern 1: (H⊗H) · CX · (H⊗H)  →  CX(t, c)
            if (
                n(pre_c) == "h"
                and n(pre_t) == "h"
                and n(suc_c) == "h"
                and n(suc_t) == "h"
            ):
                dag.remove_op_node(pre_c)
                dag.remove_op_node(pre_t)
                dag.remove_op_node(suc_c)
                dag.remove_op_node(suc_t)
                # Wire mapping: when we replace cx(c, t) by sub_dag, the sub_dag
                # qubits 0 and 1 map to c and t respectively. To realize CX(t, c)
                # in that mapping, the sub_dag should have cx(1, 0).
                flipped = QuantumCircuit(2)
                flipped.cx(1, 0)
                dag.substitute_node_with_dag(cx, circuit_to_dag(flipped), wires=[c, t])
                m1 += 1
                continue

            # Pattern 4: H_t · CX(c, t) · H_t  →  CZ(c, t)
            if (
                n(pre_t) == "h"
                and n(suc_t) == "h"
                and n(pre_c) != "h"
                and n(suc_c) != "h"
            ):
                dag.remove_op_node(pre_t)
                dag.remove_op_node(suc_t)
                dag.substitute_node(cx, CZGate(), inplace=True)
                m4 += 1
                continue

        self.property_set["h_reduction_matches_pattern1"] = m1
        self.property_set["h_reduction_matches_pattern4"] = m4
        return dag
