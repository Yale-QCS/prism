"""Logical stage: input circuit to ``enc.LOGICAL_ISA``."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from qiskit.circuit import Measure
from qiskit.circuit.library import (
    MCPhaseGate,
    MCXGate,
    PermutationGate,
    SwapGate,
)
from qiskit.dagcircuit import DAGCircuit
from qiskit.transpiler import (
    PassManager,
    Target,
)
from qiskit.transpiler.passes import (
    BasisTranslator,
    Decompose,
    ElidePermutations,
    HighLevelSynthesis,
    HLSConfig,
    Optimize1qGatesDecomposition,
    RemoveBarriers,
    Unroll3qOrMore,
)

from prism.synthesis.delocal_decomp import MCDecomposeWithAncilla

if TYPE_CHECKING:
    from qiskit.circuit import EquivalenceLibrary

    from prism.encodings.base import QubitEncoding


CONTROL_FLOW_OPS: frozenset[str] = frozenset(
    {"if_else", "while_loop", "for_loop", "switch_case"}
)


NON_GATE_ISA_NAMES: frozenset[str] = CONTROL_FLOW_OPS | {"measure", "barrier", "reset"}


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
    """Standard cleanup → translate to ``enc.LOGICAL_ISA``."""
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
        ]
    )


class ElideLogicalPermutations(ElidePermutations):
    """Elide semantic permutations without leaking a logical-width layout."""

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Remove logical permutation operations and preserve their net effect."""
        permutation_ops = sum(
            isinstance(node.op, (SwapGate, PermutationGate)) for node in dag.op_nodes()
        )
        out_dag = super().run(dag)

        virtual_layout = self.property_set.get("virtual_permutation_layout")
        if virtual_layout is None:
            permutation = tuple(range(len(out_dag.qubits)))
        else:
            permutation = tuple(virtual_layout[q] for q in out_dag.qubits)

        self.property_set["logical_output_permutation"] = permutation
        self.property_set["logical_permutation_ops_elided"] = permutation_ops
        out_dag.metadata = dict(out_dag.metadata or {})
        out_dag.metadata["logical_output_permutation"] = list(permutation)

        # These layouts are keyed by logical qubit objects.  Leaving them in
        # the property set makes the physical ApplyLayout pass try to compose
        # them with the expanded rail-level DAG.
        self.property_set["virtual_permutation_layout"] = None
        self.property_set["original_layout"] = None
        return out_dag
