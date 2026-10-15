"""Codespace faithfulness tests for dual-rail realizations.

Convention (source of truth: src/prism/encodings/dualrail.py):

    |0_L> = |q_0=0, q_1=1>  (lo rail unexcited, hi rail excited)
    |1_L> = |q_0=1, q_1=0>  (lo rail excited, hi rail unexcited)

  In wire-0-first notation these are |0_L>=|01>, |1_L>=|10>.
  Qiskit uses little-endian statevectors: index = q_0 + 2*q_1 + 4*q_2 + ...
  so |0_L> sits at index 2 and |1_L> at index 1 (for a 2-wire system).

  Qiskit CRZ(theta) gate (used throughout the encoding):
    RZ(theta) = diag(e^{-i theta/2}, e^{+i theta/2})
    CRZ(theta, ctrl, tgt) applies RZ(theta) to tgt when ctrl=1
    Logical-space matrix: diag(1, 1, e^{-i theta/2}, e^{+i theta/2})
      in the (|00_L>, |01_L>, |10_L>, |11_L>) ordering.

  Qiskit CRZ differs from CP(theta) = diag(1,1,1,e^{i theta}).
  This module tests the Qiskit CRZ convention as implemented in the code.

CODE/COMMENT MISMATCH (reported in artifacts/hpca/results/C03_RESULT.md):
  DualRail.initialize() calls the CRZ(pi) herald '(codespace-identity)', but
  the actual logical action is diag(1, -i) = S_dagger.  The code space is
  invariant under the herald (no leakage), but the gate is NOT the identity
  matrix on the code space.  See test_init_herald_is_sdagger.
"""

import math

import numpy as np
import pytest
from qiskit.circuit import QuantumCircuit
from qiskit.circuit.library import CRZGate, RXGate, RZGate, SwapGate, XGate
from qiskit.quantum_info import Operator, Statevector

from prism.encodings.dualrail import DualRail

TOL = 1e-10
ANGLES = [0.0, math.pi / 7, math.pi / 2, math.pi, -math.pi / 3]

# ---------------------------------------------------------------------------
# Helpers: isometry, logical action, comparison, sector analysis
# ---------------------------------------------------------------------------


def _isometry(n_wires, pairs):
    """Build the code-space isometry V (2^n x 2^k); columns = physical basis states.

    pairs = [(lo_wire, hi_wire), ...].  |0_L>=X(hi), |1_L>=X(lo).
    """
    k = len(pairs)
    cols = []
    for idx in range(2**k):
        bits = [
            (idx >> (k - 1 - j)) & 1 for j in range(k)
        ]  # big-endian over logical qubits
        qc = QuantumCircuit(n_wires)
        for (lo, hi), b in zip(pairs, bits):
            qc.x(lo if b == 1 else hi)
        cols.append(Statevector(qc).data)
    return np.column_stack(cols)


def _logical(qc, pairs):
    """Return V^dag U V: the 2^k x 2^k logical matrix of qc on the code space."""
    V = _isometry(qc.num_qubits, pairs)
    U = Operator(qc).data
    return V.conj().T @ U @ V


def _phase_eq(M, target, tol=TOL):
    """True if M == target * e^{i phi} for some global phase phi."""
    i, j = np.unravel_index(np.argmax(np.abs(target)), target.shape)
    if abs(target[i, j]) < 1e-12 or abs(M[i, j]) < 1e-12:
        return False
    phase = target[i, j] / M[i, j]
    return bool(np.allclose(M * phase, target, atol=tol))


def _codespace_indices(n_wires, pairs):
    """Frozenset of statevector indices with exactly one excitation per pair."""
    cs = set(range(2**n_wires))
    for lo, hi in pairs:
        cs = {idx for idx in cs if ((idx >> lo) & 1) + ((idx >> hi) & 1) == 1}
    return frozenset(cs)


def _erasure_safe(qc, pairs):
    """True if qc's unitary is block-diagonal w.r.t. photon-number sectors of each pair.

    Checks that no column of U from the code space has nonzero amplitude in any
    leakage row (0-excitation or 2-excitation sector of any pair).
    """
    n = qc.num_qubits
    U = Operator(qc).data
    cs = _codespace_indices(n, pairs)
    leakage = frozenset(range(2**n)) - cs
    for col in cs:
        for row in leakage:
            if abs(U[row, col]) > TOL:
                return False
    return True


def _has_xonrail(qc):
    """True if qc contains a bare X or RX(pi) on a single qubit (X-on-rail violation)."""
    for inst in qc.data:
        gate = inst.operation
        if gate.name == "x":
            return True
        if gate.name == "rx" and abs(abs(float(gate.params[0])) - math.pi) < 1e-9:
            return True
    return False


# ---------------------------------------------------------------------------
# Reference logical matrices
# ---------------------------------------------------------------------------

_X_L = np.array([[0, 1], [1, 0]], dtype=complex)
_SWAP_L = np.array(
    [[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=complex
)
_SDAGGER = np.diag([1.0 + 0j, -1j])


def _rz_mat(theta):
    return np.diag([np.exp(-1j * theta / 2), np.exp(1j * theta / 2)])


def _rx_mat(theta):
    c, s = math.cos(theta / 2), math.sin(theta / 2)
    return np.array([[c, -1j * s], [-1j * s, c]], dtype=complex)


def _crz_mat(theta):
    """Logical CRZ(theta) in the (|00_L>, |01_L>, |10_L>, |11_L>) basis."""
    return np.diag([1.0, 1.0, np.exp(-1j * theta / 2), np.exp(1j * theta / 2)]).astype(
        complex
    )


# ===========================================================================
# 1. Isometry convention
# ===========================================================================


def test_isometry_convention():
    """V[:,0]=physical |0_L> (index 2); V[:,1]=physical |1_L> (index 1)."""
    V = _isometry(2, [(0, 1)])
    exp_0L = np.zeros(4, dtype=complex)
    exp_0L[2] = 1.0  # X on hi=wire1: q_0=0, q_1=1 -> index 0+2=2
    exp_1L = np.zeros(4, dtype=complex)
    exp_1L[1] = 1.0  # X on lo=wire0: q_0=1, q_1=0 -> index 1+0=1
    np.testing.assert_allclose(V[:, 0], exp_0L, atol=TOL)
    np.testing.assert_allclose(V[:, 1], exp_1L, atol=TOL)


# ===========================================================================
# 2. CRZ: four rail-pairing candidates
# ===========================================================================


@pytest.mark.parametrize("theta", ANGLES)
def test_crz_candidates_equivalent_and_correct(theta):
    """All 4 CRZ candidates implement the same logical CRZ(theta) up to global phase.

    Each of the 4 candidates uses a different (ra, rb) physical rail pairing with
    the open-control identity CRZ(-α)·RZ(α)_t applied when ra=1 (hi-rail control).
    """
    op = DualRail.crz(CRZGate(theta))
    assert len(op.candidates) == 4, "Expected exactly 4 CRZ rail-pairing candidates"
    pairs2 = [(0, 1), (2, 3)]
    mats = [_logical(c, pairs2) for c in op.candidates]
    ref = _crz_mat(theta)

    # Find a stable phase anchor from candidate 0.
    anchor = np.unravel_index(np.argmax(np.abs(mats[0])), mats[0].shape)
    anchor_val = mats[0][anchor]
    assert abs(anchor_val) > 1e-12, (
        f"CRZ candidate 0 has no non-zero anchor for theta={theta:.5f}"
    )

    for k, M in enumerate(mats):
        assert abs(M[anchor]) > 1e-12, (
            f"CRZ candidate {k} has zero at phase anchor for theta={theta:.5f}"
        )
        phase = anchor_val / M[anchor]
        np.testing.assert_allclose(
            M * phase,
            mats[0],
            atol=TOL,
            err_msg=(
                f"CRZ candidate {k} diverges from candidate 0"
                f" at theta={theta:.5f}; logical diag={np.round(np.diag(M), 5)}"
            ),
        )

    assert _phase_eq(mats[0], ref, tol=TOL), (
        f"CRZ logical matrix does not match CRZ(theta={theta:.5f});"
        f" got diag={np.round(np.diag(mats[0]), 5)}"
    )


# ===========================================================================
# 3. SWAP: two partition candidates
# ===========================================================================


def test_swap_realizations():
    """Both SWAP candidates (straight and crossed) implement logical SWAP."""
    op = DualRail.swap(SwapGate())
    assert len(op.candidates) == 2
    pairs2 = [(0, 1), (2, 3)]
    for k, qc in enumerate(op.candidates):
        M = _logical(qc, pairs2)
        assert _phase_eq(M, _SWAP_L, tol=TOL), (
            f"SWAP candidate {k} does not implement logical SWAP; got\n{np.round(M, 4)}"
        )


# ===========================================================================
# 4. Single-qubit gates
# ===========================================================================


def test_x_realization():
    """Logical X -> physical SWAP(0,1) implements logical X on the code space."""
    op = DualRail.x(XGate())
    M = _logical(op.candidates[0], [(0, 1)])
    assert _phase_eq(M, _X_L, tol=TOL), (
        f"X realization not logical X; got\n{np.round(M, 4)}"
    )


@pytest.mark.parametrize("theta", ANGLES)
def test_rx_realization(theta):
    """Logical RX(theta) -> RSwapGate(theta) implements logical RX(theta).

    RSwapGate = SWAP^(theta/pi): acts on {|01>,|10>} as e^{i theta/2}[[cos,−i sin],[−i sin,cos]]
    which is RX(theta) up to logical global phase in the (|0_L>, |1_L>) basis.
    """
    op = DualRail.rx(RXGate(theta))
    M = _logical(op.candidates[0], [(0, 1)])
    assert _phase_eq(M, _rx_mat(theta), tol=TOL), (
        f"RX({theta:.5f}) realization not logical RX; got\n{np.round(M, 4)}"
    )


@pytest.mark.parametrize("theta", ANGLES)
def test_rz_realization(theta):
    """Logical RZ(theta) -> physical RZ(theta) on wire 0 (lo rail) implements logical RZ(theta).

    Z_L = Z_a: the lo rail carries the logical Z eigenvalue because |1_L>=|10> has lo-rail
    excitation.  Applying RZ(theta) to wire 0 gives phase e^{-i theta/2} to |0_L> (lo=0)
    and e^{+i theta/2} to |1_L> (lo=1), matching the logical RZ matrix.
    """
    op = DualRail.rz(RZGate(theta))
    M = _logical(op.candidates[0], [(0, 1)])
    assert _phase_eq(M, _rz_mat(theta), tol=TOL), (
        f"RZ({theta:.5f}) realization not logical RZ; got\n{np.round(M, 4)}"
    )


# ===========================================================================
# 5. Erasure safety: code space never leaks into 0- or 2-excitation sectors
# ===========================================================================


def test_erasure_safety_x():
    """X realization (SWAP) is block-diagonal w.r.t. photon-number sectors."""
    op = DualRail.x(XGate())
    assert _erasure_safe(op.candidates[0], [(0, 1)])


@pytest.mark.parametrize("theta", ANGLES)
def test_erasure_safety_rx(theta):
    """RX(theta) realization (RSwap) preserves photon-number sector of the rail pair."""
    op = DualRail.rx(RXGate(theta))
    assert _erasure_safe(op.candidates[0], [(0, 1)]), (
        f"RX({theta:.5f}) realization leaks outside code space"
    )


@pytest.mark.parametrize("theta", ANGLES)
def test_erasure_safety_rz(theta):
    """RZ(theta) realization is diagonal; never maps code space to leakage sector."""
    op = DualRail.rz(RZGate(theta))
    assert _erasure_safe(op.candidates[0], [(0, 1)]), (
        f"RZ({theta:.5f}) realization leaks outside code space"
    )


@pytest.mark.parametrize("theta", ANGLES)
def test_erasure_safety_crz_candidates(theta):
    """All 4 CRZ candidates are erasure-safe: block-diagonal per-pair photon sectors."""
    op = DualRail.crz(CRZGate(theta))
    pairs2 = [(0, 1), (2, 3)]
    for k, qc in enumerate(op.candidates):
        assert _erasure_safe(qc, pairs2), (
            f"CRZ candidate {k} at theta={theta:.5f} leaks outside code space"
        )


def test_erasure_safety_swap_candidates():
    """Both SWAP candidates are erasure-safe (preserve excitation per pair)."""
    op = DualRail.swap(SwapGate())
    pairs2 = [(0, 1), (2, 3)]
    for k, qc in enumerate(op.candidates):
        assert _erasure_safe(qc, pairs2), f"SWAP candidate {k} leaks outside code space"


# ===========================================================================
# 6. Structural X-on-rail check
# ===========================================================================


def test_xonrail_absent_x_realization():
    """Logical X is implemented as SWAP, not a bare X gate on one rail."""
    op = DualRail.x(XGate())
    assert not _has_xonrail(op.candidates[0])


@pytest.mark.parametrize("theta", ANGLES)
def test_xonrail_absent_rx(theta):
    """RX candidate uses RSwapGate; no bare X or RX(pi) on a single rail."""
    op = DualRail.rx(RXGate(theta))
    assert not _has_xonrail(op.candidates[0]), (
        f"RX({theta:.5f}) candidate contains X-on-rail"
    )


def test_xonrail_absent_rz():
    """RZ candidate uses a phase gate only; no X-on-rail."""
    op = DualRail.rz(RZGate(math.pi / 4))
    assert not _has_xonrail(op.candidates[0])


@pytest.mark.parametrize("theta", ANGLES)
def test_xonrail_absent_crz(theta):
    """No CRZ candidate contains a bare X or RX(pi) on a single rail."""
    op = DualRail.crz(CRZGate(theta))
    for k, qc in enumerate(op.candidates):
        assert not _has_xonrail(qc), (
            f"CRZ candidate {k} at theta={theta:.5f} contains X-on-rail"
        )


def test_xonrail_absent_swap():
    """Neither SWAP candidate contains a bare X or RX(pi) on a single rail."""
    op = DualRail.swap(SwapGate())
    for k, qc in enumerate(op.candidates):
        assert not _has_xonrail(qc), f"SWAP candidate {k} contains X-on-rail"


# ===========================================================================
# 7. Initialization: entangling init (joint herald)
# ===========================================================================


def test_init_prepares_0L():
    """DualRail.initialize() on |00> yields |0_L>: amplitude 1 at statevector index 2."""
    qc = DualRail.initialize()
    sv = Statevector(qc).data
    exp = np.zeros(4, dtype=complex)
    exp[2] = 1.0  # |0_L>=|q_0=0,q_1=1> -> index 0+2=2
    np.testing.assert_allclose(sv, exp, atol=TOL)


def test_init_herald_is_sdagger():
    """The CRZ(pi) herald acts as S_dagger = diag(1, -i) on the code space, NOT identity.

    DualRail.initialize() comment says '(codespace-identity)' for the herald, but:
      |0_L> = |q_0=0, q_1=1>: control q_0=0 -> CRZ inactive -> phase 1
      |1_L> = |q_0=1, q_1=0>: control q_0=1 -> RZ(pi) on q_1=0 -> phase e^{-i pi/2} = -i

    The logical action is diag(1, -i) = S_dagger.  The code space is invariant
    (no amplitude leaks), but the gate is not the identity matrix.
    This mismatch between the 'codespace-identity' label and the actual S_dagger
    action is reported in C03_RESULT.md.
    """
    qc = QuantumCircuit(2)
    qc.crz(math.pi, 0, 1)
    M = _logical(qc, [(0, 1)])
    np.testing.assert_allclose(
        M,
        _SDAGGER,
        atol=TOL,
        err_msg=(
            "CRZ(pi) herald is not S_dagger on the code space; "
            f"expected diag(1,-i), got diag={np.round(np.diag(M), 6)}"
        ),
    )
    # Explicitly assert NOT identity, documenting the comment mismatch.
    assert not np.allclose(M, np.eye(2), atol=1e-6), (
        "Unexpected: CRZ(pi) herald acts as identity; "
        "the code comment would then be accidentally correct"
    )


def test_init_herald_erasure_safe():
    """CRZ(pi) herald is block-diagonal: code space is invariant (no population leakage)."""
    qc = QuantumCircuit(2)
    qc.crz(math.pi, 0, 1)
    assert _erasure_safe(qc, [(0, 1)])


# ===========================================================================
# 8. Reset: in-place re-preparation
# ===========================================================================


def test_reset_is_in_place_reprep():
    """DualRail.reset lowers to the ``initialize`` template on the same two rails."""
    op = DualRail.reset(None)  # _op is intentionally unused (prefixed _)
    assert len(op.candidates) == 1 and op.num_qubits == 2
    names = [ins.operation.name for ins in op.candidates[0].data]
    assert names == ["x", "joint_herald"]
