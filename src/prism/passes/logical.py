"""Passes of the ``logical`` stage, on ``DAGCircuit``."""

from __future__ import annotations

from collections import defaultdict
from functools import partial

import numpy as np
from qiskit.circuit import (
    AncillaRegister,
    Clbit,
    EquivalenceLibrary,
    Gate,
    IfElseOp,
    Measure,
    QuantumCircuit,
    Qubit,
)
from qiskit.circuit.library import MCPhaseGate, MCXGate
from qiskit.converters import circuit_to_dag
from qiskit.dagcircuit import DAGCircuit, DAGOpNode
from qiskit.quantum_info import Clifford
from qiskit.synthesis import synth_clifford_ag, synth_clifford_greedy
from qiskit.transpiler import PassManager, TransformationPass
from qiskit.transpiler.passes import (
    BasisTranslator,
    CollectCliffords,
    ElidePermutations,
    Optimize1qGatesDecomposition,
)
from qiskit.transpiler.passes.optimization.collect_and_collapse import (
    collapse_to_operation,
)


class MCPrepare(TransformationPass):
    """Rewrite ``mcphase(pi)`` as ``mcx`` and give ``mcx`` synthesis a clean ancilla.

    ``mcphase`` has no ancilla-using synthesis plugin. The ancilla is an idle
    qubit if there is one, else a new register ``mcd_anc``.
    """

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        for node in dag.op_nodes(MCPhaseGate):
            n = node.op.num_ctrl_qubits
            if n >= 4 and _is_pi(float(node.op.params[0])):
                sub = QuantumCircuit(n + 1)
                sub.h(n)
                sub.append(MCXGate(n, ctrl_state=node.op.ctrl_state), range(n + 1))
                sub.h(n)
                dag.substitute_node_with_dag(node, circuit_to_dag(sub))
        if "mcx" in dag.count_ops() and not any(
            isinstance(w, Qubit) for w in dag.idle_wires()
        ):
            dag.add_qreg(AncillaRegister(1, name="mcd_anc"))
        return dag


def _is_pi(theta: float) -> bool:
    return abs(abs((theta + np.pi) % (2 * np.pi) - np.pi) - np.pi) <= 1e-9


class ElideLogicalPermutations(ElidePermutations):
    """``ElidePermutations`` that also sets ``property_set["logical_output_permutation"]``."""

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        out_dag = super().run(dag)
        virtual_layout = self.property_set["virtual_permutation_layout"]
        self.property_set["logical_output_permutation"] = (
            tuple(range(len(out_dag.qubits)))
            if virtual_layout is None
            else tuple(virtual_layout[q] for q in out_dag.qubits)
        )
        return out_dag


class SplitIfElse(TransformationPass):
    """Split an ``if_else`` of 1-qubit gates into one ``if_else`` per qubit."""

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        for node in dag.op_nodes(IfElseOp):
            op = node.op
            if op.num_qubits < 2 or not _splittable(op):
                continue
            split = DAGCircuit()
            split.add_qubits(node.qargs)
            split.add_clbits(node.cargs)
            for i, qubit in enumerate(node.qargs):
                blocks = [_restrict(block, i) for block in op.blocks]
                split.apply_operation_back(
                    IfElseOp(op.condition, *blocks), (qubit,), node.cargs, check=False
                )
            dag.substitute_node_with_dag(node, split)
        return dag


def _splittable(op: IfElseOp) -> bool:
    return all(
        instr.operation.num_qubits == 1 and not instr.clbits
        for block in op.blocks
        for instr in block.data
    )


def _restrict(block: QuantumCircuit, i: int) -> QuantumCircuit:
    sub = QuantumCircuit([block.qubits[i]], *block.cregs)
    sub.add_bits([c for c in block.clbits if not block.find_bit(c).registers])
    for instr in block.data:
        if instr.qubits == (block.qubits[i],):
            sub.append(instr)
    return sub


class EarlyMeasurement(TransformationPass):
    """Measure a qubit before the ``rz`` and ``crz`` gates on it, which become classical control.

    A Z measurement commutes with diagonal gates (Rovara, Burgholzer and Wille,
    arXiv:2511.22712). Once measured, the qubit is in a basis state: an ``rz`` on
    it is a phase, a ``crz`` it controls becomes ``if c: rz`` on the target, and a
    ``crz`` it targets becomes ``rz(±θ/2)`` on the control, chosen by its bit.
    """

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        nodes = list(dag.topological_op_nodes())
        pending: dict[Qubit, int] = {}  # qubit -> the measurement that reads it later
        reach: dict[int, int] = {}  # measurement -> the op it follows (-1: the start)
        rewritten: dict[int, tuple[IfElseOp, Qubit, Clbit] | None] = {}
        moved: set[int] = set()
        for k in range(len(nodes) - 1, -1, -1):
            node = nodes[k]
            blocked = [q for q, m in pending.items() if nodes[m].cargs[0] in node.cargs]
            if node.name in ("rz", "crz") and (
                measured := [q for q in node.qargs if q in pending]
            ):
                rewritten[k] = _classical_rz(
                    node, {q: nodes[pending[q]] for q in measured}
                )
                moved.update(pending[q] for q in measured)
            else:
                blocked += [q for q in node.qargs if q in pending]
            for q in dict.fromkeys(blocked):
                reach[pending.pop(q)] = k
            if isinstance(node.op, Measure):
                pending[node.qargs[0]] = k
        if not moved:
            return dag
        reach.update((m, -1) for m in pending.values())
        after: dict[int, list[DAGOpNode]] = defaultdict(list)
        for m in moved:
            after[reach[m]].append(nodes[m])
        out = dag.copy_empty_like()
        for m in after[-1]:
            out.apply_operation_back(m.op, m.qargs, m.cargs)
        for k, node in enumerate(nodes):
            if k in rewritten:
                if (rz := rewritten[k]) is not None:
                    op, q, bit = rz
                    out.apply_operation_back(op, (q,), (bit,))
            elif k not in moved:
                out.apply_operation_back(node.op, node.qargs, node.cargs)
            for m in after[k]:
                out.apply_operation_back(m.op, m.qargs, m.cargs)
        return out


def _classical_rz(
    node: DAGOpNode, measured: dict[Qubit, DAGOpNode]
) -> tuple[IfElseOp, Qubit, Clbit] | None:
    """``node`` as an ``rz`` conditioned on the measured qubit's bit; ``None`` if it is only a phase."""
    if len(measured) == len(node.qargs):
        return None
    (theta,) = node.op.params
    control, target = node.qargs
    if control in measured:
        qubit, bit, angles = target, measured[control].cargs[0], (theta,)
    else:
        qubit, bit, angles = control, measured[target].cargs[0], (theta / 2, -theta / 2)
    blocks = []
    for angle in angles:
        block = QuantumCircuit([qubit], [bit])
        block.rz(angle, qubit)
        blocks.append(block)
    return IfElseOp((bit, True), *blocks), qubit, bit


class MinRXCliffords(CollectCliffords):
    """Resynthesize each Clifford block with the fewest ``rx``, then ``crz``, in ``isa``.

    The candidates are the block itself and its greedy and Aaronson-Gottesman syntheses.
    A synthesis that couples a new pair of qubits, or holds a SWAP, is skipped:
    routing the new pair costs more than the gates saved.
    """

    def __init__(self, eq_library: EquivalenceLibrary, isa: list[str]) -> None:
        super().__init__()
        translate = PassManager(
            [BasisTranslator(eq_library, isa), Optimize1qGatesDecomposition(basis=isa)]
        )

        def score(qc: QuantumCircuit) -> tuple[int, int]:
            ops = translate.run(qc).count_ops()
            return ops.get("rx", 0), ops.get("crz", 0)

        def pairs(qc: QuantumCircuit) -> set[frozenset]:
            # A SWAP is elided into a relabelling of every later gate: never a subset.
            return {
                frozenset(ci.qubits) if ci.operation.name != "swap" else ci.qubits
                for ci in qc.data
                if len(ci.qubits) == 2
            }

        def best(block: QuantumCircuit) -> Gate:
            cliff = Clifford(block)
            cands = (block, synth_clifford_greedy(cliff), synth_clifford_ag(cliff))
            qc = min((c for c in cands if pairs(c) <= pairs(block)), key=score)
            return qc.to_gate(label="min_rx_clifford")

        self.collapse_function = partial(collapse_to_operation, collapse_function=best)

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        dag = super().run(dag)
        for node in dag.op_nodes():
            if node.op.label == "min_rx_clifford":
                dag.substitute_node_with_dag(node, circuit_to_dag(node.op.definition))
        return dag
