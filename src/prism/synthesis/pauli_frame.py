"""Pauli-frame propagation: push ``P · Z^z · X^x · H^h`` through Clifford+RZ, settle at boundaries.

Per-qubit canonical frame with ``P = diag(1, e^{i·phase·π/4})``, ``phase ∈ Z/8Z``.
Settles at H, RX, CX-target, measurement, control-flow. Up to global phase.
"""

from __future__ import annotations

import math

from qiskit.circuit import Qubit
from qiskit.circuit.library import (
    CXGate,
    CZGate,
    HGate,
    RXGate,
    RZGate,
    XGate,
    ZGate,
)
from qiskit.dagcircuit import DAGCircuit
from qiskit.transpiler import TransformationPass

# Names of single-qubit phase-only gates handled by the phase frame.
# Maps gate name -> phase delta (mod 8), where one unit = π/4.
_PHASE_DELTA = {
    "t": 1,
    "tdg": 7,  # -1 mod 8
    "s": 2,
    "sdg": 6,  # -2 mod 8
}


class PauliFramePropagation(TransformationPass):
    """Push (h, x, z, phase) frames through Clifford+rotation ops; settle on incompatible gates."""

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Walk topologically; per-qubit (h, x, z, phase); emit at boundaries."""
        new_dag = dag.copy_empty_like()
        h_f: dict = {q: 0 for q in dag.qubits}
        x_f: dict = {q: 0 for q in dag.qubits}
        z_f: dict = {q: 0 for q in dag.qubits}
        phase_f: dict = {q: 0 for q in dag.qubits}

        diag = {
            "pauli_frame_x_pushed": 0,
            "pauli_frame_x_emitted": 0,
            "pauli_frame_z_emitted": 0,
            "pauli_frame_h_pushed": 0,
            "pauli_frame_h_emitted": 0,
            "pauli_frame_h_absorbed": 0,
            "pauli_frame_rz_flipped": 0,
            "pauli_frame_cx_to_cz": 0,
            "pauli_frame_cz_to_cx": 0,
            "pauli_frame_cx_flipped": 0,
            "pauli_frame_rx_to_rz": 0,
            "pauli_frame_phase_pushed": 0,
            "pauli_frame_phase_merged": 0,
            "pauli_frame_phase_emitted": 0,
        }

        def settle_h(q: Qubit) -> None:
            """Emit H on q if h-frame is set; clear it."""
            if h_f[q]:
                new_dag.apply_operation_back(HGate(), [q], [])
                h_f[q] = 0
                diag["pauli_frame_h_emitted"] += 1

        def settle_phase(q: Qubit) -> None:
            """Emit RZ(phase·π/4) on q; clear phase. Settles h first if set."""
            if not phase_f[q]:
                return
            # P sits to the LEFT of Z^z · X^x · H^h in canonical form. To
            # emit P as the rightmost gate appended to new_dag, P must
            # commute through everything to its right. P commutes with Z;
            # P · X^x = ω^{p·x} · X^x · P^{(-1)^x}, so we get a sign flip
            # on the angle if x is set (global phase ω^{p·x} discarded).
            # P does NOT commute with H — if h=1 we must settle H first.
            if h_f[q]:
                settle_h(q)
            p = phase_f[q]
            angle_units = (-p) % 8 if x_f[q] else p
            new_dag.apply_operation_back(RZGate(angle_units * math.pi / 4), [q], [])
            phase_f[q] = 0
            diag["pauli_frame_phase_emitted"] += 1

        def settle_all(qubits: list[Qubit]) -> None:
            """Materialize all frame components in order H, X, Z, RZ(phase)."""
            for q in qubits:
                if h_f[q]:
                    new_dag.apply_operation_back(HGate(), [q], [])
                    h_f[q] = 0
                    diag["pauli_frame_h_emitted"] += 1
                if x_f[q]:
                    new_dag.apply_operation_back(XGate(), [q], [])
                    x_f[q] = 0
                    diag["pauli_frame_x_emitted"] += 1
                if z_f[q]:
                    new_dag.apply_operation_back(ZGate(), [q], [])
                    z_f[q] = 0
                    diag["pauli_frame_z_emitted"] += 1
                if phase_f[q]:
                    # x_f[q] is now 0; no angle sign-flip needed.
                    new_dag.apply_operation_back(
                        RZGate(phase_f[q] * math.pi / 4), [q], []
                    )
                    phase_f[q] = 0
                    diag["pauli_frame_phase_emitted"] += 1

        for node in dag.topological_op_nodes():
            name = node.op.name
            qs = list(node.qargs)

            if name in _PHASE_DELTA and len(qs) == 1:
                q = qs[0]
                # T (and S/Sdg/Tdg) is diagonal: T · P = P · T, and T commutes
                # past Z^z · X^x · H^h to merge into P from the left (just by
                # associativity of the canonical-form composition). Absorbed
                # as phase += delta (mod 8). No interaction with h, x, z.
                delta = _PHASE_DELTA[name]
                old = phase_f[q]
                phase_f[q] = (phase_f[q] + delta) % 8
                diag["pauli_frame_phase_pushed"] += 1
                if old != 0 and phase_f[q] == 0:
                    diag["pauli_frame_phase_merged"] += 1
                continue

            if name == "h" and len(qs) == 1:
                q = qs[0]
                # H · P does not reduce to P' · H; settle phase first.
                if phase_f[q]:
                    settle_phase(q)
                if h_f[q]:
                    diag["pauli_frame_h_absorbed"] += 1
                # H · Z^z X^x H^h = Z^x X^z H^{h+1}  (up to global phase).
                x_f[q], z_f[q] = z_f[q], x_f[q]
                h_f[q] ^= 1
                diag["pauli_frame_h_pushed"] += 1
                continue

            if name == "x" and len(qs) == 1:
                q = qs[0]
                # X · P = ω^p · P^{-1} · X up to global phase: absorbing X
                # negates the phase (and toggles x as in v2).
                if phase_f[q]:
                    phase_f[q] = (-phase_f[q]) % 8
                x_f[q] ^= 1
                diag["pauli_frame_x_pushed"] += 1
                continue

            if name == "z" and len(qs) == 1:
                q = qs[0]
                # Z commutes with P (both diagonal); just toggle z parity.
                z_f[q] ^= 1
                continue

            if name == "cx" and len(qs) == 2:
                c, t = qs
                # Phase on control commutes through CX; phase on target does
                # not (target's X-action interferes). Settle phase_t first.
                if phase_f[t]:
                    settle_phase(t)
                hc, ht = h_f[c], h_f[t]
                if hc and not ht:
                    # H on control alone: no clean push; settle h_c then fall through.
                    settle_h(c)
                    hc = 0
                if hc and ht:
                    # (H⊗H) · CX(c,t) · (H⊗H) = CX(t,c) ⇒ emit reversed CX, h's stay.
                    new_dag.apply_operation_back(CXGate(), [t, c], [])
                    diag["pauli_frame_cx_flipped"] += 1
                elif ht and not hc:
                    # CX · H_t = H_t · CZ ⇒ emit CZ, h_t stays.
                    new_dag.apply_operation_back(CZGate(), [c, t], [])
                    diag["pauli_frame_cx_to_cz"] += 1
                else:
                    new_dag.apply_operation_back(CXGate(), [c, t], [])
                # Pauli propagation follows ORIGINAL CX(c,t): x_t ^= x_c, z_c ^= z_t.
                x_f[t] ^= x_f[c]
                z_f[c] ^= z_f[t]
                continue

            if name == "cz" and len(qs) == 2:
                c, t = qs
                # CZ is diagonal on both wires → commutes with phase on each.
                hc, ht = h_f[c], h_f[t]
                if hc and ht:
                    # Sandwiching CZ by H⊗H gives a non-Clifford; settle one h.
                    settle_h(c)
                    hc = 0
                if ht and not hc:
                    # CZ · H_t = H_t · CX ⇒ emit CX(c,t), h_t stays.
                    new_dag.apply_operation_back(CXGate(), [c, t], [])
                    diag["pauli_frame_cz_to_cx"] += 1
                elif hc and not ht:
                    # CZ symmetric: CZ · H_c = H_c · CX(t,c).
                    new_dag.apply_operation_back(CXGate(), [t, c], [])
                    diag["pauli_frame_cz_to_cx"] += 1
                else:
                    new_dag.apply_operation_back(CZGate(), [c, t], [])
                # Pauli propagation follows ORIGINAL CZ(c,t): z_c ^= x_t, z_t ^= x_c.
                x_c_in = x_f[c]
                z_f[c] ^= x_f[t]
                z_f[t] ^= x_c_in
                continue

            if name == "rz" and len(qs) == 1:
                q = qs[0]
                if h_f[q]:
                    # Pushing through H would force an RX emit (expensive). Settle h.
                    settle_h(q)
                # RZ commutes with phase; no need to settle phase.
                theta = float(node.op.params[0])
                if x_f[q]:
                    new_dag.apply_operation_back(RZGate(-theta), [q], [])
                    diag["pauli_frame_rz_flipped"] += 1
                else:
                    new_dag.apply_operation_back(node.op, qs, node.cargs)
                continue

            if name == "rx" and len(qs) == 1:
                q = qs[0]
                # RX does not commute with phase; settle phase first (settles
                # h if needed). After settle, phase=0 and (possibly) h=0.
                if phase_f[q]:
                    settle_phase(q)
                theta = float(node.op.params[0])
                if h_f[q]:
                    # H · RX(θ) = RZ(θ) · H  ⇒ emit RZ, h stays. Z-frame flips angle sign.
                    sign_theta = -theta if z_f[q] else theta
                    new_dag.apply_operation_back(RZGate(sign_theta), [q], [])
                    diag["pauli_frame_rx_to_rz"] += 1
                else:
                    # X commutes with RX; Z anticommutes with RX (flips angle sign).
                    sign_theta = -theta if z_f[q] else theta
                    new_dag.apply_operation_back(RXGate(sign_theta), [q], [])
                continue

            # Default: settle all frames on touched qubits, then emit original op.
            settle_all(qs)
            new_dag.apply_operation_back(node.op, qs, node.cargs)

        # End of DAG: settle any residual frame.
        settle_all(list(dag.qubits))

        for k, v in diag.items():
            self.property_set[k] = v
        return new_dag
