"""``MultiRealization -> MultiRealization`` passes of the ``multi_realization`` stage.

``PrismRouting`` (``prism.routing``) is the stage's required pass; the passes here
run before or after it.
"""

from __future__ import annotations

import numpy as np
from qiskit.exceptions import QiskitError
from qiskit.passmanager import GenericPass
from qiskit.quantum_info import Operator
from qiskit.transpiler import TranspilerError

from prism.ir import MultiRealization, MultiRealizationOp

__all__ = ["ElideRailExchanges"]


class ElideRailExchanges(GenericPass[MultiRealization, MultiRealization]):
    """Drop every op that only permutes its qubit's rails, and relabel the rails after it.

    The rail-level ``ElideLogicalPermutations``: in dual rail, logical X (and
    ``rx(pi)``) is the exchange of the two rails. An op is elided when every
    candidate is the same permutation of the rails of one logical qubit, up to
    global phase. Later instructions, measurements included, act on the
    relabelled rails, and the net permutation goes into ``output_permutation``,
    hence into the output's final layout. Runs before routing.
    """

    def run(self, passmanager_ir: MultiRealization) -> MultiRealization:
        """Elide the rail permutations of the unplaced ``passmanager_ir``."""
        ir = passmanager_ir
        if ir.placement is not None:
            raise TranspilerError("ElideRailExchanges runs before routing")
        wpl = ir.enc.WIRES_PER_LOGICAL
        cur = list(range(len(ir.rails)))  # IR rail -> rail it now sits on
        data = []
        for ins in ir.data:
            perm = (
                _rail_permutation(ins.operation, wpl)
                if isinstance(ins.operation, MultiRealizationOp)
                else None
            )
            if perm is None:
                data.append(ins._replace(qubits=tuple(cur[q] for q in ins.qubits)))
                continue
            # Local wire k's content moves to local wire perm[k].
            moved = [cur[q] for q in ins.qubits]
            for k, q in enumerate(ins.qubits):
                cur[ins.qubits[perm[k]]] = moved[k]
        out = list(ir.output_permutation)
        for r, c in enumerate(cur):
            out[c] = ir.output_permutation[r]
        ir.data = data
        ir.output_permutation = tuple(out)
        return ir


def _rail_permutation(op: MultiRealizationOp, wpl: int) -> tuple[int, ...] | None:
    """The permutation ``k -> perm[k]`` of local wires shared by every candidate, or ``None``.

    Only for an op on one logical qubit, with no clbits, whose candidates are
    unitary circuits equal to one wire permutation up to global phase.
    """
    if op.diagonal or op.num_qubits != wpl or op.num_clbits:
        return None
    perms = set()
    for qc in op.candidates:
        try:
            u = Operator(qc).data
        except (QiskitError, TypeError):  # non-unitary, control flow, or unbound
            return None
        cols = np.abs(u[:, [1 << k for k in range(wpl)]]).argmax(axis=0)
        perm = tuple(int(c).bit_length() - 1 for c in cols)
        if sorted(perm) != list(range(wpl)):
            return None
        rows = [
            sum(1 << perm[k] for k in range(wpl) if x >> k & 1) for x in range(1 << wpl)
        ]
        diag = u[rows, range(1 << wpl)]
        if not np.allclose(diag, diag[0]) or not np.isclose(abs(diag[0]), 1):
            return None
        perms.add(perm)
    return perms.pop() if len(perms) == 1 else None
