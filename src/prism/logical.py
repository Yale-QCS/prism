"""Logical stage: input circuit to ``enc.LOGICAL_ISA``."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from qiskit.circuit import AncillaRegister, IfElseOp, QuantumCircuit, Qubit
from qiskit.circuit.controlflow import CONTROL_FLOW_OP_NAMES
from qiskit.circuit.library import MCPhaseGate, MCXGate
from qiskit.converters import circuit_to_dag
from qiskit.dagcircuit import DAGCircuit
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
    from qiskit.circuit import EquivalenceLibrary
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
    """Standard cleanup, translate to ``enc.LOGICAL_ISA``, split ``if_else`` per qubit, elide SWAPs, drop diagonals before measures."""
    isa_basis = sorted(enc.LOGICAL_ISA - NON_GATE_ISA_NAMES)
    return PassManager(
        [
            RemoveBarriers(),
            MCPrepare(),
            # High-level gates (QFT, MCMT, ...) by their default plugins; mcx
            # with one clean ancilla.
            HighLevelSynthesis(hls_config=HLSConfig(mcx=["1_clean_kg24"])),
            Decompose(["c-unitary", "unitary"]),
            # Unroll every 3+-qubit gate but CCX (the equivalence library has CCX).
            Unroll3qOrMore(basis_gates=["ccx"]),
            *reshape_passes,
            BasisTranslator(
                eq_library, sorted(enc.LOGICAL_ISA | CONTROL_FLOW_OP_NAMES)
            ),
            Optimize1qGatesDecomposition(basis=isa_basis),
            SplitIfElse(),
            # Before layout a SWAP only relabels logical qubits.
            ElideLogicalPermutations(),
            # A diagonal gate right before a final measurement does not change its
            # outcome; removing it here keeps routing from spending SWAPs on it. One
            # sweep can expose another (rz after crz), hence the fixed point.
            DoWhileController(
                [
                    RemoveDiagonalGatesBeforeMeasure(),
                    Size(recurse=True),
                    FixedPoint("size"),
                ],
                do_while=lambda property_set: not property_set["size_fixed_point"],
            ),
        ]
    )


class MCPrepare(TransformationPass):
    """Prepare multi-controlled gates for ``HighLevelSynthesis`` with ``mcx=["1_clean_kg24"]``.

    Rewrites ``mcphase(pi)`` with 4+ controls as ``H_t . mcx . H_t`` (``mcphase``
    has no synthesis plugin). If an ``mcx`` remains and no qubit is idle, adds one
    clean ancilla qubit (register ``mcd_anc``) for the synthesis to share.
    """

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Rewrite ``mcphase(pi)`` and add the ancilla if needed."""
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
    """``theta`` is ``pi`` modulo ``2 pi``."""
    return abs(abs((theta + np.pi) % (2 * np.pi) - np.pi) - np.pi) <= 1e-9


class ElideLogicalPermutations(ElidePermutations):
    """``ElidePermutations`` that also records ``logical_output_permutation`` in the property set."""

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Remove logical permutation operations and record their net effect."""
        out_dag = super().run(dag)
        virtual_layout = self.property_set["virtual_permutation_layout"]
        self.property_set["logical_output_permutation"] = (
            tuple(range(len(out_dag.qubits)))
            if virtual_layout is None
            else tuple(virtual_layout[q] for q in out_dag.qubits)
        )
        return out_dag


class SplitIfElse(TransformationPass):
    """Replace an ``if_else`` over several qubits by one ``if_else`` per qubit.

    Exact when every block instruction acts on one qubit and writes no classical
    bit: the per-qubit branches then commute and read the same condition. Other
    ``if_else`` operations are left alone.
    """

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Split every splittable multi-qubit ``if_else`` in ``dag``."""
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
    """Every block instruction of ``op`` acts on one qubit and writes no classical bit."""
    return all(
        instr.operation.num_qubits == 1 and not instr.clbits
        for block in op.blocks
        for instr in block.data
    )


def _restrict(block: QuantumCircuit, i: int) -> QuantumCircuit:
    """``block`` with only qubit ``i`` and the instructions on it; classical bits kept."""
    sub = QuantumCircuit([block.qubits[i]], *block.cregs)
    sub.add_bits([c for c in block.clbits if not block.find_bit(c).registers])
    for instr in block.data:
        if instr.qubits == (block.qubits[i],):
            sub.append(instr)
    return sub
