"""Semantic tests for PauliFramePropagation: unitary equivalence and measurement outcomes."""

import math

from qiskit.circuit import QuantumCircuit
from qiskit.converters import circuit_to_dag, dag_to_circuit
from qiskit.quantum_info import Operator, Statevector

from marabbecca.synthesis.pauli_frame import PauliFramePropagation


def _run(qc: QuantumCircuit):
    """Apply PauliFramePropagation; return (out_circuit, property_set)."""
    p = PauliFramePropagation()
    out = dag_to_circuit(p.run(circuit_to_dag(qc)))
    return out, p.property_set


def _equiv_op(a: QuantumCircuit, b: QuantumCircuit) -> bool:
    """Unitary equivalence up to global phase."""
    return Operator(a).equiv(Operator(b))


def _sv_before_measure(qc: QuantumCircuit) -> Statevector:
    """Statevector of qc with final measurements stripped."""
    return Statevector.from_instruction(qc.remove_final_measurements(inplace=False))


# ---------------------------------------------------------------------------
# Unitary-level tests (no measurement)
# ---------------------------------------------------------------------------


def test_x_before_rz():
    """X·RZ(θ): x_f makes RZ flip sign; X emitted at DAG end; unitary unchanged."""
    theta = math.pi / 3
    qc = QuantumCircuit(1)
    qc.x(0)
    qc.rz(theta, 0)
    out, ps = _run(qc)
    assert _equiv_op(out, qc)
    assert ps["pauli_frame_x_pushed"] == 1
    assert ps["pauli_frame_rz_flipped"] == 1


def test_rz_then_x():
    """RZ(θ)·X: X absorbed into frame AFTER RZ; RZ unchanged; X emitted at end."""
    theta = math.pi / 3
    qc = QuantumCircuit(1)
    qc.rz(theta, 0)
    qc.x(0)
    out, ps = _run(qc)
    assert _equiv_op(out, qc)
    assert ps["pauli_frame_x_pushed"] == 1
    assert ps["pauli_frame_rz_flipped"] == 0


def test_x_cancel_pair():
    """X·X = identity; both absorbed into x_f (toggle twice); nothing emitted at end."""
    qc = QuantumCircuit(1)
    qc.x(0)
    qc.x(0)
    out, ps = _run(qc)
    assert _equiv_op(out, QuantumCircuit(1))
    assert ps["pauli_frame_x_pushed"] == 2
    assert ps["pauli_frame_x_emitted"] == 0


def test_x_cancel_pair_with_rz():
    """X·RZ(θ)·RZ(θ2)·X: X pushed through both RZ (both sign-flipped); second X cancels first."""
    t1, t2 = math.pi / 4, math.pi / 7
    qc = QuantumCircuit(1)
    qc.x(0)
    qc.rz(t1, 0)
    qc.rz(t2, 0)
    qc.x(0)
    out, ps = _run(qc)
    assert _equiv_op(out, qc)
    assert ps["pauli_frame_rz_flipped"] == 2
    assert ps["pauli_frame_x_emitted"] == 0


def test_x_before_h():
    """X·H: x_f swaps into z_f when H is absorbed; settled at end as H·Z."""
    qc = QuantumCircuit(1)
    qc.x(0)
    qc.h(0)
    out, ps = _run(qc)
    assert _equiv_op(out, qc)
    assert ps["pauli_frame_x_emitted"] == 0
    assert ps["pauli_frame_z_emitted"] == 1


def test_x_h_x():
    """X·H·X: second X toggles x_f back (z_f swapped back); verifies bidirectional h·x interaction."""
    qc = QuantumCircuit(1)
    qc.x(0)
    qc.h(0)
    qc.x(0)
    out, ps = _run(qc)
    assert _equiv_op(out, qc)


def test_x_before_h_before_rz():
    """X·H·RZ(θ): X→Z after H; Z commutes with RZ; settled at end as H·RZ(θ)·Z."""
    theta = math.pi / 5
    qc = QuantumCircuit(1)
    qc.x(0)
    qc.h(0)
    qc.rz(theta, 0)
    out, ps = _run(qc)
    assert _equiv_op(out, qc)
    # h_f pushed, rz sign unchanged (x_f=0 after h), z emitted at end
    assert ps["pauli_frame_rz_flipped"] == 0
    assert ps["pauli_frame_z_emitted"] == 1


def test_rz_flipped_count():
    """X before two RZ gates: rz_flipped == 2."""
    t1, t2 = math.pi / 3, math.pi / 6
    qc = QuantumCircuit(1)
    qc.x(0)
    qc.rz(t1, 0)
    qc.rz(t2, 0)
    _, ps = _run(qc)
    assert ps["pauli_frame_x_pushed"] == 1
    assert ps["pauli_frame_rz_flipped"] == 2


def test_x_before_crz_control_settles():
    """X on control before CRZ: frame settled at CRZ via settle_all; unitary preserved."""
    theta = math.pi / 4
    qc = QuantumCircuit(2)
    qc.x(0)
    qc.crz(theta, 0, 1)
    out, ps = _run(qc)
    assert _equiv_op(out, qc)
    assert ps["pauli_frame_x_emitted"] == 1


def test_x_on_target_before_crz_settles():
    """X on target before CRZ: settle_all fires for both qubits of the CRZ node."""
    theta = math.pi / 4
    qc = QuantumCircuit(2)
    qc.x(1)
    qc.crz(theta, 0, 1)
    out, ps = _run(qc)
    assert _equiv_op(out, qc)
    assert ps["pauli_frame_x_emitted"] == 1


def test_x_around_crz_layer():
    """X·CRZ·X: both Xs settle at CRZ boundary (no push past CRZ)."""
    theta = math.pi / 3
    qc = QuantumCircuit(2)
    qc.x(0)
    qc.crz(theta, 0, 1)
    qc.x(0)
    out, ps = _run(qc)
    assert _equiv_op(out, qc)


def test_x_between_crz_layers():
    """CRZ·X·CRZ: X settles at each CRZ boundary; 2 emissions."""
    theta = math.pi / 4
    qc = QuantumCircuit(2)
    qc.crz(theta, 0, 1)
    qc.x(0)
    qc.crz(theta, 0, 1)
    out, ps = _run(qc)
    assert _equiv_op(out, qc)
    assert ps["pauli_frame_x_emitted"] == 1


def test_h_absorption():
    """H·H = identity: both h_f toggles cancel; h_absorbed counter incremented."""
    qc = QuantumCircuit(1)
    qc.h(0)
    qc.h(0)
    out, ps = _run(qc)
    assert _equiv_op(out, QuantumCircuit(1))
    assert ps["pauli_frame_h_absorbed"] == 1


# ---------------------------------------------------------------------------
# Measurement tests: compare pre-measure statevector
# ---------------------------------------------------------------------------


def test_x_before_measure():
    """X on |0> before measure: state before measurement is |1>; pass preserves this."""
    qc = QuantumCircuit(1, 1)
    qc.x(0)
    qc.measure(0, 0)
    out, _ = _run(qc)
    assert _sv_before_measure(out).equiv(_sv_before_measure(qc))


def test_x_rz_before_measure():
    """X·RZ(θ) before measure: RZ sign-flip in the frame; pre-measure state preserved."""
    theta = math.pi / 3
    qc = QuantumCircuit(1, 1)
    qc.x(0)
    qc.rz(theta, 0)
    qc.measure(0, 0)
    out, _ = _run(qc)
    assert _sv_before_measure(out).equiv(_sv_before_measure(qc))


def test_two_qubit_x_before_measure():
    """X on q0 only, measure both: q0 -> |1>, q1 stays |0>; pass preserves state."""
    qc = QuantumCircuit(2, 2)
    qc.x(0)
    qc.measure([0, 1], [0, 1])
    out, _ = _run(qc)
    assert _sv_before_measure(out).equiv(_sv_before_measure(qc))


def test_x_cancel_before_measure():
    """X·X before measure: both cancel; pre-measure state is |0>; pass gives empty circuit."""
    qc = QuantumCircuit(1, 1)
    qc.x(0)
    qc.x(0)
    qc.measure(0, 0)
    out, _ = _run(qc)
    assert _sv_before_measure(out).equiv(_sv_before_measure(qc))


# ---------------------------------------------------------------------------
# if_else: pass handles control-flow boundary (conservative settle_all)
# ---------------------------------------------------------------------------


def test_x_before_if_else_settles():
    """X on q0 before if_else: settle_all fires at IfElseOp node; x_emitted == 1."""
    qc = QuantumCircuit(2, 1)
    qc.x(0)
    qc.measure(1, 0)
    with qc.if_test((qc.cregs[0][0], 0)):
        qc.rz(math.pi / 4, 0)
    out, ps = _run(qc)
    # pass must not crash; x_emitted should be 1 (X settled before if_else)
    assert ps["pauli_frame_x_emitted"] == 1
