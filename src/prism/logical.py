"""Logical stage: input circuit to ``enc.LOGICAL_ISA``."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

import numpy as np
from qiskit.circuit import (
    AncillaRegister,
    IfElseOp,
    Measure,
    QuantumCircuit,
    Qubit,
)
from qiskit.circuit.controlflow import CONTROL_FLOW_OP_NAMES
from qiskit.circuit.library import MCPhaseGate, MCXGate
from qiskit.converters import circuit_to_dag
from qiskit.dagcircuit import DAGCircuit, DAGOpNode
from qiskit.passmanager import DoWhileController
from qiskit.transpiler import PassManager, TransformationPass
from qiskit.transpiler.passes import (
    BasisTranslator,
    Decompose,
    ElidePermutations,
    FixedPoint,
    HighLevelSynthesis,
    HLSConfig,
    Optimize1qGatesDecomposition,
    RemoveBarriers,
    RemoveDiagonalGatesBeforeMeasure,
    Size,
    Unroll3qOrMore,
)

if TYPE_CHECKING:
    from qiskit.circuit import Clbit, EquivalenceLibrary
    from qiskit.transpiler import BasePass

    from prism.encodings.base import QubitEncoding


NON_GATE_ISA_NAMES: frozenset[str] = CONTROL_FLOW_OP_NAMES | {
    "measure",
    "reset",
    "erasure_check",
}


def basic_logical_pm(
    enc: type[QubitEncoding],
    *,
    eq_library: EquivalenceLibrary,
    reshape_passes: tuple[BasePass, ...] = (),
) -> PassManager:
    """Translate to ``enc.LOGICAL_ISA`` and simplify."""
    isa_basis = sorted(enc.LOGICAL_ISA - NON_GATE_ISA_NAMES)
    return PassManager(
        [
            RemoveBarriers(),
            MCPrepare(),
            HighLevelSynthesis(hls_config=HLSConfig(mcx=["1_clean_kg24"])),
            Decompose(["c-unitary", "unitary"]),
            Unroll3qOrMore(basis_gates=["ccx"]),
            *reshape_passes,
            BasisTranslator(
                eq_library, sorted(enc.LOGICAL_ISA | CONTROL_FLOW_OP_NAMES)
            ),
            SplitIfElse(),
            # Before layout a SWAP only relabels logical qubits.
            ElideLogicalPermutations(),
            Optimize1qGatesDecomposition(basis=isa_basis),
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
