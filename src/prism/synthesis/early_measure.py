"""Measure early: a Z-measurement commutes with every diagonal gate before it.

A qubit whose remaining gates are all diagonal (``rz``, ``crz``) and end in a
measurement is measured right after its last non-diagonal gate. Each later
``rz`` on it disappears; each later ``crz`` becomes a classically controlled
``rz`` on the other operand, which is free in dual-rail. This is the
semiclassical-QFT construction (Griffiths and Niu, 1996) applied wherever the
tail of a qubit's program is diagonal.
"""

from qiskit.circuit import QuantumCircuit, Qubit
from qiskit.converters import circuit_to_dag, dag_to_circuit
from qiskit.dagcircuit import DAGCircuit
from qiskit.transpiler import TransformationPass

DIAGONAL = frozenset({"rz", "crz"})


class EarlyMeasurement(TransformationPass):
    """Pull final Z-measurements past diagonal tails; turn the tail's CRZs into feedforward RZs."""

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Rewrite every qubit whose program ends in a diagonal tail plus measurement."""
        qc = dag_to_circuit(dag)
        nodes = list(dag.topological_op_nodes())
        last_nd = {q: -1 for q in qc.qubits}  # index of the last non-diagonal op
        final_measure = {}  # qubit -> (node index, clbit) when a measure ends the qubit
        for i, node in enumerate(nodes):
            name = node.op.name
            for q in node.qargs:
                if name == "measure":
                    final_measure[q] = (i, node.cargs[0])
                elif name == "barrier":
                    continue
                elif name in DIAGONAL:
                    continue
                else:
                    last_nd[q] = i
                    final_measure.pop(q, None)
        if not final_measure:
            return dag
        out = QuantumCircuit(*qc.qregs, *qc.cregs)
        out.add_bits([b for b in qc.qubits if b._register is None])
        out.add_bits([b for b in qc.clbits if b._register is None])
        out.metadata = qc.metadata
        out.global_phase = qc.global_phase
        early = {q: c for q, (_, c) in final_measure.items()}
        measured = set()

        def measure_now(q: Qubit) -> None:
            out.measure(q, early[q])
            measured.add(q)

        for q, i in last_nd.items():
            if q in early and i == -1:
                measure_now(q)
        for i, node in enumerate(nodes):
            name, qs, cs = node.op.name, list(node.qargs), list(node.cargs)
            if name == "measure" and qs[0] in early:
                continue  # emitted at its last non-diagonal op
            if name == "rz" and qs[0] in measured:
                continue
            if name == "crz" and any(q in measured for q in qs):
                (theta,) = node.op.params
                c, t = qs
                if c in measured and t in measured:
                    continue
                if c in measured:
                    with out.if_test((early[c], 1)):
                        out.rz(theta, t)
                else:  # target measured to m: phase exp(i theta (2m-1)/2) on the control's |1>
                    out.rz(-theta / 2, c)
                    with out.if_test((early[t], 1)):
                        out.rz(theta, c)
                continue
            out.append(node.op, qs, cs)
            for q in qs:
                if q in early and last_nd[q] == i:
                    measure_now(q)
        return circuit_to_dag(out)
