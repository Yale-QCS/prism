"""Target-asymmetric equivalence-library templates: every RX lands on the target wire.

Under dual-rail, RX is expensive (RSWAP) and RZ is free. Stock Qiskit's
``{p, u, cx}`` decomposition leaks RX onto control wires because
BasisTranslator walks each leg independently. These hand-pinned templates
(cu, rzz, cp, cs, csdg, rxx, ryy, iswap, ccx, rtof) keep RX target-side.

Identities used: ``cx(c,t) ≡ H_t · S_c · CRz(π) · H_t``, ``H ≡ Rz·Rx·Rz``,
``U(θ,φ,λ) ≡ Rz·Rx·Rz``, ``P(α) ≡ Rz(α)``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit import AncillaRegister, EquivalenceLibrary, Parameter
from qiskit.circuit.equivalence_library import SessionEquivalenceLibrary
from qiskit.circuit.library import (
    CCXGate,
    CPhaseGate,
    CSdgGate,
    CSGate,
    CUGate,
    RXXGate,
    RYYGate,
    RZZGate,
    iSwapGate,
)
from qiskit.converters import circuit_to_dag
from qiskit.dagcircuit import DAGCircuit
from qiskit.synthesis import synth_mcx_1_clean_kg24
from qiskit.transpiler import TransformationPass

if TYPE_CHECKING:
    from qiskit.circuit.parameterexpression import ParameterValueType

    from marabbecca.synthesis.margolus import RTOFGate


def _h_target(qc: QuantumCircuit, q: int) -> None:
    """``H`` on target via ``Rz · Rx · Rz`` (one RX, target-side)."""
    qc.rz(np.pi / 2, q)
    qc.rx(np.pi / 2, q)
    qc.rz(np.pi / 2, q)


def _u_target(
    qc: QuantumCircuit,
    theta: ParameterValueType,
    phi: ParameterValueType,
    lam: ParameterValueType,
    q: int,
) -> None:
    """``U(θ,φ,λ)`` on target via ``Rz(λ-π/2) · Rx(θ) · Rz(φ+π/2)``."""
    qc.rz(lam - np.pi / 2, q)
    qc.rx(theta, q)
    qc.rz(phi + np.pi / 2, q)


def _cx_target_asymmetric(qc: QuantumCircuit, c: int, t: int) -> None:
    """``CX(c,t) ≡ H_t · S_c · CRz(π) · H_t``, with ``H`` expanded target-side."""
    _h_target(qc, t)
    qc.rz(np.pi / 2, c)  # S_c (drops global phase)
    qc.crz(np.pi, c, t)
    _h_target(qc, t)


def cu_template() -> tuple[CUGate, QuantumCircuit]:
    """``CUGate`` template in ``{rx, rz, crz}`` with every ``rx`` on the target wire."""
    theta = Parameter("θ")
    phi = Parameter("φ")
    lam = Parameter("λ")
    gamma = Parameter("γ")

    qc = QuantumCircuit(2, name="cu_target_asym")
    c, t = 0, 1

    # Diagonal phases (Qiskit's CU.definition prefix).
    qc.rz(gamma, c)
    qc.rz((lam + phi) / 2, c)
    qc.rz((lam - phi) / 2, t)

    # CX #1
    _cx_target_asymmetric(qc, c, t)

    # U(-θ/2, 0, -(λ+φ)/2) on target
    _u_target(qc, -theta / 2, 0, -(lam + phi) / 2, t)

    # CX #2
    _cx_target_asymmetric(qc, c, t)

    # U(θ/2, φ, 0) on target
    _u_target(qc, theta / 2, phi, 0, t)

    return CUGate(theta, phi, lam, gamma), qc


def rzz_template() -> tuple[RZZGate, QuantumCircuit]:
    """``RZZ(θ) ≡ CRZ(-2θ) · (I ⊗ Rz(θ))`` (up to global phase). Zero RX."""
    theta = Parameter("θ")
    qc = QuantumCircuit(2, name="rzz_dr_native")
    qc.crz(-2 * theta, 0, 1)
    qc.rz(theta, 1)
    return RZZGate(theta), qc


def cphase_template() -> tuple[CPhaseGate, QuantumCircuit]:
    """``CP(θ) ≡ Rz_c(θ/2) · CRZ(θ)`` (up to global phase). Zero RX."""
    theta = Parameter("θ")
    qc = QuantumCircuit(2, name="cp_dr_native")
    qc.rz(theta / 2, 0)
    qc.crz(theta, 0, 1)
    return CPhaseGate(theta), qc


def cs_template() -> tuple[CSGate, QuantumCircuit]:
    """``CS ≡ CP(π/2)``. Zero RX."""
    qc = QuantumCircuit(2, name="cs_dr_native")
    qc.rz(np.pi / 4, 0)
    qc.crz(np.pi / 2, 0, 1)
    return CSGate(), qc


def csdg_template() -> tuple[CSdgGate, QuantumCircuit]:
    """``CSdg ≡ CP(-π/2)``. Zero RX."""
    qc = QuantumCircuit(2, name="csdg_dr_native")
    qc.rz(-np.pi / 4, 0)
    qc.crz(-np.pi / 2, 0, 1)
    return CSdgGate(), qc


def rxx_template() -> tuple[RXXGate, QuantumCircuit]:
    """``RXX(θ) ≡ H_0 · CZ · RX(θ)_1 · CZ · H_0`` (up to global phase). 3 RX."""
    theta = Parameter("θ")
    qc = QuantumCircuit(2, name="rxx_dr_native")
    # H on q0
    qc.rz(np.pi / 2, 0)
    qc.rx(np.pi / 2, 0)
    qc.rz(np.pi / 2, 0)
    # CZ via CRZ(π) + RZ(π/2) on control
    qc.crz(np.pi, 0, 1)
    qc.rz(np.pi / 2, 0)
    # RX(θ) on q1
    qc.rx(theta, 1)
    # CZ
    qc.crz(np.pi, 0, 1)
    qc.rz(np.pi / 2, 0)
    # H on q0
    qc.rz(np.pi / 2, 0)
    qc.rx(np.pi / 2, 0)
    qc.rz(np.pi / 2, 0)
    return RXXGate(theta), qc


def ryy_template() -> tuple[RYYGate, QuantumCircuit]:
    """``RYY(θ) ≡ (S†⊗S†) · RXX(θ) · (S⊗S)`` (up to global phase). 3 RX (S/S† are free RZ)."""
    theta = Parameter("θ")
    qc = QuantumCircuit(2, name="ryy_dr_native")
    # S† ⊗ S† (basis change Y -> X on each rail)
    qc.rz(-np.pi / 2, 0)
    qc.rz(-np.pi / 2, 1)
    # --- RXX(θ) body, inlined ---
    qc.rz(np.pi / 2, 0)
    qc.rx(np.pi / 2, 0)
    qc.rz(np.pi / 2, 0)
    qc.crz(np.pi, 0, 1)
    qc.rz(np.pi / 2, 0)
    qc.rx(theta, 1)
    qc.crz(np.pi, 0, 1)
    qc.rz(np.pi / 2, 0)
    qc.rz(np.pi / 2, 0)
    qc.rx(np.pi / 2, 0)
    qc.rz(np.pi / 2, 0)
    # --- end RXX body ---
    # S ⊗ S (undo the basis change)
    qc.rz(np.pi / 2, 0)
    qc.rz(np.pi / 2, 1)
    return RYYGate(theta), qc


def iswap_template() -> tuple[iSwapGate, QuantumCircuit]:
    """``iSwap ≡ SWAP · RZZ(π/2)`` (up to global phase). Zero RX."""
    qc = QuantumCircuit(2, name="iswap_dr_native")
    qc.swap(0, 1)
    qc.rzz(np.pi / 2, 0, 1)
    return iSwapGate(), qc


def rtof_template() -> tuple[RTOFGate, QuantumCircuit]:
    """``RTOFGate`` template (3-CX target-asymmetric). Used by ``MargolusPairOptimizer``."""
    from marabbecca.synthesis.margolus import RTOFGate

    qc = QuantumCircuit(3, name="rtof_3cx")
    a, b, t = 0, 1, 2
    qc.ry(np.pi / 4, t)
    qc.cx(b, t)
    qc.ry(np.pi / 4, t)
    qc.cx(a, t)
    qc.ry(-np.pi / 4, t)
    qc.cx(b, t)
    qc.ry(-np.pi / 4, t)
    return RTOFGate(), qc


def ccx_template() -> tuple[CCXGate, QuantumCircuit]:
    """``CCX(a,b,t) ≡ H_t · CS(a,t) · CX(b,t) · CSdg(a,t) · CX(b,t) · CS(a,b) · H_t``. 4 RX after Opt1q."""
    qc = QuantumCircuit(3, name="ccx_dr_native")
    a, b, t = 0, 1, 2
    qc.h(t)
    qc.cs(a, t)
    qc.cx(b, t)
    qc.csdg(a, t)
    qc.cx(b, t)
    qc.cs(a, b)
    qc.h(t)
    return CCXGate(), qc


def build_equivalence_library() -> EquivalenceLibrary:
    """Project templates layered on the session lib. Uses ``add_equivalence`` so Dijkstra picks the shortest path."""
    lib = EquivalenceLibrary(base=SessionEquivalenceLibrary)
    for gate, template in (
        cu_template(),
        rzz_template(),
        cphase_template(),
        cs_template(),
        csdg_template(),
        rxx_template(),
        ryy_template(),
        iswap_template(),
        ccx_template(),
        rtof_template(),
    ):
        lib.add_equivalence(gate, template)
    return lib


# Qiskit's EquivalenceLibrary is fixed-arity, so MCX/MCPhase can't be templated
# with an ancilla. The kg24 form (Khattar/Gidney 2024, synth_mcx_1_clean_kg24)
# uses one clean ancilla and is much cheaper than the ancilla-free Gray-code
# alternative for grover-class circuits.


class MCDecomposeWithAncilla(TransformationPass):
    """Rewrite ``MCXGate(>=3 ctrls)`` / ``MCPhaseGate(theta=π, >=4 ctrls)`` via kg24 + one clean ancilla.

    Adds an ``AncillaRegister(1, 'mcd_anc')`` only if a target gate is found
    (and reuses it across substitutions). ``mcphase(π)`` is rewritten as
    ``H_t · MCX · H_t``. Other-theta ``mcphase`` falls through to the
    default decomposition. Place between ``Unroll3qOrMore`` (with mcx/mcphase
    kept) and ``BasisTranslator``, followed by ``Decompose(['rccx', 'rccx_dg'])``.
    """

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Substitute each eligible mcx/mcphase node with its kg24 form."""
        targets = []
        for node in dag.op_nodes():
            if node.name == "mcx" and node.op.num_ctrl_qubits >= 3:
                targets.append(node)
                continue
            if node.name == "mcphase" and node.op.num_ctrl_qubits >= 4:
                # Skip non-pi mcphase here so the ancilla register isn't
                # allocated for a circuit that has nothing actionable.
                theta = float(node.op.params[0])
                wrapped = (theta + np.pi) % (2 * np.pi) - np.pi
                if abs(abs(wrapped) - np.pi) <= 1e-9:
                    targets.append(node)
        if not targets:
            return dag

        anc_reg = AncillaRegister(1, name="mcd_anc")
        dag.add_qreg(anc_reg)
        anc_qubit = dag.qubits[-1]

        new_dag = dag.copy_empty_like()
        target_set = set(targets)
        for node in dag.topological_op_nodes():
            if node not in target_set:
                new_dag.apply_operation_back(node.op, node.qargs, node.cargs)
                continue
            n_ctrl = node.op.num_ctrl_qubits
            qubits = list(node.qargs)
            if node.name == "mcx":
                sub = synth_mcx_1_clean_kg24(num_ctrl_qubits=n_ctrl)
            else:  # mcphase (theta = pi mod 2pi, already filtered)
                sub = QuantumCircuit(n_ctrl + 2, name=f"mcphase_kg24_{n_ctrl}")
                sub.h(n_ctrl)  # H on target wire
                sub.compose(
                    synth_mcx_1_clean_kg24(num_ctrl_qubits=n_ctrl),
                    qubits=list(range(n_ctrl + 2)),
                    inplace=True,
                )
                sub.h(n_ctrl)
            wires = qubits + [anc_qubit]
            new_dag.compose(circuit_to_dag(sub), qubits=wires)
        return new_dag
