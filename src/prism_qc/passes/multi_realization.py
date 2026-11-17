"""Passes on ``MultiRealization`` that run before and after ``PrismRouting``."""

from __future__ import annotations

from qiskit.circuit import Operation
from qiskit.circuit.library import PermutationGate
from qiskit.exceptions import QiskitError
from qiskit.passmanager import GenericPass
from qiskit.quantum_info import Operator
from qiskit.transpiler import TranspilerError

from prism_qc.ir import RAILS, MultiRealization, MultiRealizationOp


class ElideRailExchanges(GenericPass[MultiRealization, MultiRealization]):
    """Drop ops that only permute one qubit's rails, such as dual-rail X, and relabel the rails.

    The net permutation goes into ``output_permutation``, and so into the final layout.
    """

    def run(self, ir: MultiRealization) -> MultiRealization:
        if ir.placement is not None:
            raise TranspilerError("ElideRailExchanges runs before routing")
        cur = list(range(len(ir.rails)))  # IR rail -> rail it now sits on
        data = []
        for ins in ir.data:
            perm = _rail_permutation(ins.operation)
            if perm is None:
                data.append(ins._replace(qubits=tuple(cur[q] for q in ins.qubits)))
            else:
                # Local wire k receives local wire perm[k]'s content.
                moved = [cur[q] for q in ins.qubits]
                for k, q in enumerate(ins.qubits):
                    cur[q] = moved[perm[k]]
        out = list(ir.output_permutation)
        for r, c in enumerate(cur):
            out[c] = ir.output_permutation[r]
        ir.data = data
        ir.output_permutation = tuple(out)
        return ir


def _rail_permutation(op: Operation | MultiRealizationOp) -> tuple[int, ...] | None:
    """The rail permutation every candidate equals up to global phase, if any."""
    if (
        not isinstance(op, MultiRealizationOp)
        or op.diagonal
        or op.num_qubits != RAILS
        or op.num_clbits
    ):
        return None
    try:
        ops = [Operator(qc) for qc in op.candidates]
    except (QiskitError, TypeError):  # non-unitary, control flow, or unbound
        return None
    for perm in ((1, 0), (0, 1)):
        if all(u.equiv(PermutationGate(perm)) for u in ops):
            return perm
    return None
