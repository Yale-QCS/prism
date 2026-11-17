"""Verify the gate-set theorem (paper §3.2, the placement-dependent-ISA headline):
the only logical 1Q gates B with a SEPARABLE (delocalizable) physical completion
M(A,B) are O(2) = {Rz(theta)} u {Rz(theta) X}; H, sqrt(X), and any pole-moving
rotation are perfect entanglers in every completion (no A makes them local).

A logical gate is applicable to a DELOCALIZED (separated) rail pair iff some
completion M(A,B) is a local (non-entangling) 2-qubit gate, i.e. sits at the Weyl
origin. We sweep A over U(2) and read the Weyl coordinates of M(A,B).
"""
import numpy as np
from qiskit.quantum_info import random_unitary, Operator
from qiskit.synthesis import TwoQubitWeylDecomposition
from qiskit.circuit.library import RZGate, RXGate, RYGate, HGate, SXGate

rng = np.random.default_rng(0)


def M(A, B):
    """Parity-preserving matchgate (paper Eq. GAB): A on {|00>,|11>}, B on {|01>,|10>}."""
    G = np.zeros((4, 4), dtype=complex)
    G[0, 0], G[0, 3], G[3, 0], G[3, 3] = A[0, 0], A[0, 1], A[1, 0], A[1, 1]
    G[1, 1], G[1, 2], G[2, 1], G[2, 2] = B[0, 0], B[0, 1], B[1, 0], B[1, 1]
    return G


def min_locality(B, n_random=400):
    """Min over A of the Weyl-coordinate magnitude a+b+c; ~0 => some completion is local."""
    best = np.inf
    # structured A candidates (diagonal, anti-diagonal) + random U(2)
    cand = [np.eye(2, dtype=complex),
            np.array([[1, 0], [0, -1]], complex), np.array([[1j, 0], [0, -1j]], complex),
            np.array([[0, 1], [1, 0]], complex), np.array([[0, 1j], [1j, 0]], complex)]
    cand += [random_unitary(2, seed=int(rng.integers(1 << 30))).data for _ in range(n_random)]
    for A in cand:
        G = M(A, B)
        # skip if not unitary (shouldn't happen for unitary A,B)
        w = TwoQubitWeylDecomposition(Operator(G))
        best = min(best, abs(w.a) + abs(w.b) + abs(w.c))
    return best


gates = {
    "Rz(0.7)  [diagonal]": RZGate(0.7).to_matrix(),
    "Rz(0.7)X [anti-diag]": RZGate(0.7).to_matrix() @ np.array([[0, 1], [1, 0]], complex),
    "X        [pole flip]": np.array([[0, 1], [1, 0]], complex),
    "H": HGate().to_matrix(),
    "sqrt(X)": SXGate().to_matrix(),
    "Ry(0.7)": RYGate(0.7).to_matrix(),
    "Rx(0.7)": RXGate(0.7).to_matrix(),
}

print("gate-set theorem: which logical 1Q gates have a LOCAL (delocalizable) completion?")
print("=" * 74)
for name, B in gates.items():
    d = min_locality(B)
    verdict = "DELOCALIZABLE (local completion exists)" if d < 1e-6 else "perfect entangler (no local completion)"
    print(f"  B = {name:22s} min Weyl |a|+|b|+|c| over A = {d:.2e}   {verdict}")
print("=" * 74)
print("Expected by the theorem: Rz, RzX, X delocalizable; H, sqrt(X), Ry, Rx are")
print("perfect entanglers => delocalized 1Q ISA = O(2) = {Rz} u {Rz X}. (X is the")
print("anti-diagonal pole flip, erasure-rejected in practice, leaving the phase set.)")
