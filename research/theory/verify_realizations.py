"""Verify the paper's load-bearing claim: every dual-rail realization candidate
implements the IDENTICAL logical gate (audit T1.8, punted to 'the artifact').

Method: build the dual-rail isometry V per logical qubit by simulating the prep
(|0_L>=|01> = X on the high wire), embed each candidate's physical unitary back to
the logical space as V_full^dag U V_full, and check all candidates of a gate agree
up to a single global phase (relative phases preserved), and match the intended
logical operator.
"""
import numpy as np
from qiskit.circuit import QuantumCircuit
from qiskit.quantum_info import Operator, Statevector
from marabbecca.encodings.dualrail import DualRail

np.set_printoptions(precision=3, suppress=True, linewidth=140)


def rail_basis(nwires, pairs):
    """16x(2^k) isometry: columns = physical statevecs of logical basis states.
    pairs = list of (lo_wire, hi_wire) per logical qubit; |0_L>=X(hi), |1_L>=X(lo)."""
    k = len(pairs)
    cols = []
    for idx in range(2 ** k):
        bits = [(idx >> (k - 1 - j)) & 1 for j in range(k)]  # big-endian logical
        qc = QuantumCircuit(nwires)
        for (lo, hi), b in zip(pairs, bits):
            qc.x(lo if b == 1 else hi)   # |1_L>=|10>=X(lo); |0_L>=|01>=X(hi)
        cols.append(Statevector(qc).data)
    return np.column_stack(cols)


def logical_of(qc, pairs):
    nwires = qc.num_qubits
    V = rail_basis(nwires, pairs)
    U = Operator(qc).data
    return V.conj().T @ U @ V


def same_up_to_phase(mats, tol=1e-9):
    base = mats[0]
    # pick a reference entry with largest magnitude
    i, j = np.unravel_index(np.argmax(np.abs(base)), base.shape)
    out = []
    for M in mats:
        if abs(M[i, j]) < tol:
            return False, None
        phase = base[i, j] / M[i, j]
        out.append(np.allclose(M * phase, base, atol=1e-7))
    return all(out), None


def matches(M, target, tol=1e-7):
    i, j = np.unravel_index(np.argmax(np.abs(target)), target.shape)
    if abs(M[i, j]) < 1e-9:
        return False
    return np.allclose(M * (target[i, j] / M[i, j]), target, atol=tol)


theta = 0.7  # generic angle

print("=" * 70)
print("CRZ: 4 rail-pairing candidates must all equal logical CRZ(theta)")
print("=" * 70)
from qiskit.circuit.library import CRZGate, RZGate

crz_op = DualRail.crz(CRZGate(theta))
pairs2 = [(0, 1), (2, 3)]  # control logical = wires 0,1 ; target = wires 2,3
logical_mats = [logical_of(c, pairs2) for c in crz_op.realizations]
ok_equal, _ = same_up_to_phase(logical_mats)
# reference logical CRZ in (c,t) big-endian basis (c,t)=(00,01,10,11):
ref_crz = np.diag([1, 1, np.exp(-1j * theta / 2), np.exp(1j * theta / 2)])
ok_ref = matches(logical_mats[0], ref_crz)
print(f"  candidates: {len(crz_op.realizations)}")
print(f"  all 4 identical up to global phase : {ok_equal}")
print(f"  common gate == logical CRZ(theta)  : {ok_ref}")
print("  logical of candidate 0 (diag):", np.round(np.diag(logical_mats[0]), 3))
print("  logical of candidate 3 (diag):", np.round(np.diag(logical_mats[3]), 3))

print("=" * 70)
print("SWAP: 2 partition candidates must both equal logical SWAP")
print("=" * 70)
from qiskit.circuit.library import SwapGate

sw_op = DualRail.swap(SwapGate())
sw_mats = [logical_of(c, pairs2) for c in sw_op.realizations]
ref_swap = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=complex)
ok_sw_equal, _ = same_up_to_phase(sw_mats)
ok_sw_ref = all(matches(M, ref_swap) for M in sw_mats)
print(f"  candidates: {len(sw_op.realizations)}")
print(f"  both identical up to global phase : {ok_sw_equal}")
print(f"  common gate == logical SWAP       : {ok_sw_ref}")

print("=" * 70)
print("Single-qubit + init herald")
print("=" * 70)
from qiskit.circuit.library import XGate

x_op = DualRail.x(XGate())
xL = logical_of(x_op.realizations[0], [(0, 1)])
print("  X  -> logical X :", matches(xL, np.array([[0, 1], [1, 0]], dtype=complex)))

rz_op = DualRail.rz(RZGate(theta))
rzL = logical_of(rz_op.realizations[0], [(0, 1)])
ref_rz = np.diag([np.exp(-1j * theta / 2), np.exp(1j * theta / 2)])
print("  RZ -> logical RZ:", matches(rzL, ref_rz), " | also -RZ?", matches(rzL, ref_rz.conj()))

# init herald CRZ(pi): codespace identity
qc_h = QuantumCircuit(2)
qc_h.crz(np.pi, 0, 1)
hL = logical_of(qc_h, [(0, 1)])
print("  CRZ(pi) herald == codespace identity:", matches(hL, np.eye(2, dtype=complex)))
print("  (logical of herald):", np.round(np.diag(hL), 3))

# The corrected crossed SWAP has a cycle, so no fixed layout embeds it in a line.
from itertools import permutations

line_embeddings = []
for circuit in sw_op.realizations:
    edges = {tuple(sorted(circuit.find_bit(q).index for q in inst.qubits))
             for inst in circuit.data if len(inst.qubits) == 2}
    line_embeddings.append(sum(all(abs(p[a] - p[b]) == 1 for a, b in edges)
                               for p in permutations(range(4))))
    if len(edges) == 4:
        assert all(sum(q in edge for edge in edges) == 2 for q in range(4))
assert edges == {(0, 1), (0, 3), (1, 2), (2, 3)}
assert line_embeddings == [8, 0]
print("Logical SWAP line embeddings: aligned 8, corrected crossed 0 (C4 pattern).")
