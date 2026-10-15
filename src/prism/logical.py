"""Logical stage: input circuit to ``enc.LOGICAL_ISA``."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from qiskit.circuit import IfElseOp, Measure, QuantumCircuit
from qiskit.circuit.library import (
    MCPhaseGate,
    MCXGate,
)
from qiskit.dagcircuit import DAGCircuit
from qiskit.passmanager import DoWhileController
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

from prism.synthesis.delocal_decomp import MCDecomposeWithAncilla

if TYPE_CHECKING:
    from qiskit.circuit import EquivalenceLibrary

    from prism.encodings.base import QubitEncoding


CONTROL_FLOW_OPS: frozenset[str] = frozenset(
    {"if_else", "while_loop", "for_loop", "switch_case"}
)


NON_GATE_ISA_NAMES: frozenset[str] = CONTROL_FLOW_OPS | {"measure", "reset"}


def _unroll_target(enc: type[QubitEncoding], *, keep_mc: bool) -> Target:
    """Target for ``Unroll3qOrMore``: preserve 3Q+ gates we have downstream templates for."""
    # ``Unroll3qOrMore`` only unrolls 3Q+ gates not in the target. ``ccx`` is the
    # only 3Q gate we want to keep — DR's eq library has a 4-RX CCX template;
    # other 3Q+ inputs get unrolled. ``mcx``/``mcphase`` (when ``keep_mc=True``)
    # are added separately because they're parameterized.
    isa_gates = {n for n in enc.LOGICAL_ISA if n not in NON_GATE_ISA_NAMES}
    target = Target.from_configuration(basis_gates=sorted(isa_gates | {"ccx"}))
    target.add_instruction(Measure(), name="measure")
    if keep_mc:
        target.add_instruction(MCXGate(num_ctrl_qubits=4), name="mcx")
        target.add_instruction(MCPhaseGate(np.pi, num_ctrl_qubits=5), name="mcphase")
    return target


def basic_logical_pm(
    enc: type[QubitEncoding],
    *,
    eq_library: EquivalenceLibrary,
    reshape_passes: tuple = (),
) -> PassManager:
    """Standard cleanup, translate to ``enc.LOGICAL_ISA``, split ``if_else`` per qubit, elide SWAPs, drop diagonals before measures."""
    isa_basis = sorted(enc.LOGICAL_ISA - NON_GATE_ISA_NAMES)
    return PassManager(
        [
            RemoveBarriers(),
            HighLevelSynthesis(hls_config=HLSConfig(mcx=[], mcphase=[])),
            Decompose(["c-unitary", "unitary"]),
            Unroll3qOrMore(target=_unroll_target(enc, keep_mc=True)),
            MCDecomposeWithAncilla(),
            Decompose(["rccx", "rccx_dg"]),
            Unroll3qOrMore(target=_unroll_target(enc, keep_mc=False)),
            *reshape_passes,
            BasisTranslator(eq_library, sorted(enc.LOGICAL_ISA | CONTROL_FLOW_OPS)),
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
