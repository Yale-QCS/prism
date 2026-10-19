"""Logical stage: input circuit to ``enc.LOGICAL_ISA``."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from qiskit.circuit import AncillaRegister, IfElseOp, QuantumCircuit
from qiskit.circuit.controlflow import CONTROL_FLOW_OP_NAMES
from qiskit.circuit.library import MCPhaseGate, MCXGate
from qiskit.converters import circuit_to_dag
from qiskit.dagcircuit import DAGCircuit
from qiskit.passmanager import DoWhileController
from qiskit.synthesis import synth_mcx_1_clean_kg24
from qiskit.transpiler import (
    PassManager,
    Target,
    TransformationPass,
)
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
    # Unroll every 3+-qubit gate but CCX (the equivalence library has CCX) and
    # the multi-controlled gates MCDecomposeWithAncilla rewrites.
    keep_mc = Target.from_configuration(["ccx"])
    keep_mc.add_instruction(MCXGate, name="mcx")
    keep_mc.add_instruction(MCPhaseGate, name="mcphase")
    return PassManager(
        [
            RemoveBarriers(),
            # High-level gates (QFT, MCMT, ...) by their default plugins, except
            # mcx and mcphase.
            HighLevelSynthesis(hls_config=HLSConfig(mcx=[], mcphase=[])),
            Decompose(["c-unitary", "unitary"]),
            Unroll3qOrMore(target=keep_mc),
            MCDecomposeWithAncilla(),
            Decompose(["rccx", "rccx_dg"]),
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


class MCDecomposeWithAncilla(TransformationPass):
    """Rewrite ``mcx`` with 3+ controls and ``mcphase(pi)`` with 4+ by ``synth_mcx_1_clean_kg24``.

    Stock ``HighLevelSynthesis`` uses only idle qubits of the circuit as
    ancillas; this pass adds one clean ancilla qubit (register ``mcd_anc``),
    shared by every rewrite, if some gate qualifies. ``mcphase(pi)`` is
    ``H_t . mcx . H_t``; other ``mcphase`` angles are left to ``Unroll3qOrMore``.
    """

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Substitute each qualifying gate by its one-ancilla form."""
        targets = {
            node
            for node in dag.op_nodes()
            if (node.name == "mcx" and node.op.num_ctrl_qubits >= 3)
            or (
                node.name == "mcphase"
                and node.op.num_ctrl_qubits >= 4
                and _is_pi(float(node.op.params[0]))
            )
        }
        if not targets:
            return dag
        anc = AncillaRegister(1, name="mcd_anc")
        dag.add_qreg(anc)
        new_dag = dag.copy_empty_like()
        for node in dag.topological_op_nodes():
            if node not in targets:
                new_dag.apply_operation_back(node.op, node.qargs, node.cargs)
                continue
            n_ctrl = node.op.num_ctrl_qubits
            sub = synth_mcx_1_clean_kg24(num_ctrl_qubits=n_ctrl)
            if node.name == "mcphase":
                mcx, sub = sub, QuantumCircuit(n_ctrl + 2)
                sub.h(n_ctrl)
                sub.compose(mcx, inplace=True)
                sub.h(n_ctrl)
            new_dag.compose(circuit_to_dag(sub), qubits=[*node.qargs, anc[0]])
        return new_dag


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
