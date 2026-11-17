"""Every dual-rail candidate implements its logical gate on the code space.

Rail ``2j`` and ``2j + 1`` hold logical qubit ``j``; |0_L> = |01> (rail 1 excited), |1_L> = |10>.
"""

import numpy as np
import pytest
from qiskit.circuit import QuantumCircuit
from qiskit.circuit.library import CRZGate, RXGate, RZGate, SwapGate, XGate
from qiskit.quantum_info import Operator, Statevector

from prism_qc import dualrail


def _code_space(k: int) -> np.ndarray:
    """Isometry from ``k`` logical qubits to ``2k`` rails, little-endian like Qiskit."""
    cols = []
    for idx in range(2**k):
        qc = QuantumCircuit(2 * k)
        for j in range(k):
            qc.x(2 * j + (0 if (idx >> j) & 1 else 1))
        cols.append(Statevector(qc).data)
    return np.column_stack(cols)


@pytest.mark.parametrize(
    "gate",
    [
        CRZGate(0.7),
        CRZGate(-2.1),
        SwapGate(),
        XGate(),
        RXGate(0.7),
        RZGate(0.7),
    ],
)
def test_every_candidate_implements_the_logical_gate(gate):
    """``V^dag U V`` equals the gate up to global phase; being unitary, ``U`` cannot leak."""
    v = _code_space(gate.num_qubits)
    for candidate in dualrail.lower(gate).candidates:
        logical = v.conj().T @ Operator(candidate).data @ v
        assert Operator(logical).equiv(Operator(gate))
