"""Replace CCX pairs that bracket a D-commuting region with Margolus relative-phase Toffolis.

``RTOF(a,b,t) = CCX(a,b,t) · D`` where ``D = diag(1,1,1,-1,1,1,1,1)`` on ``(a,b,t)``.
3-CX form (vs 6-CX for exact CCX). When the region between two same-triple CCXs
commutes with ``D``, both ``D`` factors cancel and the substitution is exact.
Conservative: any non-diagonal action on the trio blocks the rewrite.
"""

from __future__ import annotations

import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit import Gate, QuantumRegister
from qiskit.dagcircuit import DAGCircuit, DAGOpNode
from qiskit.transpiler import TransformationPass

# ----------------------------------------------------------------------------
# Margolus relative-phase Toffoli gate definition
# ----------------------------------------------------------------------------


class RTOFGate(Gate):
    """Margolus relative-phase Toffoli on (a, b, t); 3-CX target-asymmetric form."""

    def __init__(self) -> None:
        """Create the parameterless 3-qubit rtof gate."""
        super().__init__("rtof", 3, [])

    def _define(self) -> None:
        qr = QuantumRegister(3, "q")
        a, b, t = 0, 1, 2
        qc = QuantumCircuit(qr, name="rtof")
        qc.ry(np.pi / 4, qr[t])
        qc.cx(qr[b], qr[t])
        qc.ry(np.pi / 4, qr[t])
        qc.cx(qr[a], qr[t])
        qc.ry(-np.pi / 4, qr[t])
        qc.cx(qr[b], qr[t])
        qc.ry(-np.pi / 4, qr[t])
        self.definition = qc


# ----------------------------------------------------------------------------
# D-commutation test
# ----------------------------------------------------------------------------


# Single-qubit gates known to be diagonal in computational basis.
_DIAGONAL_1Q = frozenset({"rz", "p", "u1", "z", "s", "sdg", "t", "tdg", "id"})

# Multi-qubit gates known to be fully diagonal in computational basis.
_DIAGONAL_NQ = frozenset(
    {
        "crz",
        "cp",
        "cz",
        "rzz",  # 2Q diagonal
        "cs",
        "csdg",  # 2Q diagonal (controlled-S/S-dagger)
        "ccz",
        "rccx",  # 3Q diagonal (CCZ is diagonal)
    }
)


def _gate_commutes_with_D_at(node: DAGOpNode, trio: set[int], qmap: dict) -> bool:
    """True if ``node``'s action commutes with the ``D`` factor on ``trio``."""
    name = node.op.name
    indices = [qmap[q] for q in node.qargs]
    touches = [i for i in indices if i in trio]
    # Disjoint from trio → trivially commutes.
    if not touches:
        return True
    # 1Q gate on a trio qubit:
    if node.op.num_qubits == 1:
        return name in _DIAGONAL_1Q
    # nQ gate that touches trio:
    if name in _DIAGONAL_NQ:
        return True
    # Controlled gates: target is the LAST qarg by Qiskit convention for
    # CXGate, CCXGate, CnXGate, MCXGate. Controls are diagonal action on
    # those qubits; target is off-diagonal X-action, so must not be in trio.
    controlled_x_like = {"cx", "ccx", "cy", "ch", "mcx", "mcphase", "rcccx"}
    if name in controlled_x_like:
        target_idx = indices[-1]
        if target_idx in trio:
            # Target hits the trio → off-diagonal there → does NOT commute.
            return False
        # Controls hit the trio: diagonal action, OK.
        # But ALSO the target's qubit (outside trio) is irrelevant.
        return True
    # Unknown gate touching trio → conservatively report not commuting.
    return False


# ----------------------------------------------------------------------------
# The pass
# ----------------------------------------------------------------------------


class MargolusPairOptimizer(TransformationPass):
    """Replace pairs of same-trio CCXs bracketing a D-commuting region with RTOFs."""

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Walk the DAG, replace eligible CCX pairs with RTOF·U·RTOF."""
        qmap = {q: i for i, q in enumerate(dag.qubits)}
        # Topologically ordered op nodes — Qiskit DAGs maintain insertion order.
        op_nodes = list(dag.topological_op_nodes())
        # Find all CCX nodes by triple.
        from collections import defaultdict

        ccxs_by_trio: dict[frozenset, list[int]] = defaultdict(list)
        for k, node in enumerate(op_nodes):
            if node.op.name == "ccx":
                trio = frozenset(qmap[q] for q in node.qargs)
                ccxs_by_trio[trio].append(k)

        # Greedily pair CCXs: for each trio, sort by position and consider
        # consecutive pairs (innermost first).
        replacement_indices: set[int] = set()
        n_pairs_replaced = 0
        for trio, positions in ccxs_by_trio.items():
            # Pair adjacent occurrences as candidates: (positions[0], positions[1]),
            # then (positions[2], positions[3]), etc. Innermost pairs first.
            unused = list(positions)
            while len(unused) >= 2:
                i = unused[0]
                j = unused[1]
                # Check if region [i+1, j) commutes with D on this trio.
                trio_set = set(trio)
                ok = True
                for k in range(i + 1, j):
                    inner = op_nodes[k]
                    if not _gate_commutes_with_D_at(inner, trio_set, qmap):
                        ok = False
                        break
                if ok:
                    replacement_indices.add(i)
                    replacement_indices.add(j)
                    n_pairs_replaced += 1
                    # Drop both used positions.
                    unused = unused[2:]
                else:
                    # Can't pair (i, j). Drop just i and try again with j as next.
                    unused = unused[1:]

        # Apply replacements.
        rtof = RTOFGate()
        for k in replacement_indices:
            node = op_nodes[k]
            dag.substitute_node(node, rtof, inplace=True)

        n_remaining = sum(
            1
            for k, n in enumerate(op_nodes)
            if n.op.name == "ccx" and k not in replacement_indices
        )
        self.property_set["margolus_pairs_replaced"] = n_pairs_replaced
        self.property_set["margolus_unpaired_ccx"] = n_remaining
        return dag
