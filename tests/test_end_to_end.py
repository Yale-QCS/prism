"""What a compiled circuit looks like to a user: device gates on device edges, documented errors."""

import math

import pytest
from qiskit.circuit import Clbit, QuantumCircuit
from qiskit.circuit.library import QFTGate
from qiskit.quantum_info import Statevector
from qiskit.transpiler import CouplingMap, TranspilerError

from prism import ErasureCheck, dualrail_pm
from prism.encodings import DualRail


def _mixed() -> QuantumCircuit:
    """QFT, RX, CCX, a distant CRZ and an if_else over five qubits."""
    qc = QuantumCircuit(6, 6)
    qc.append(QFTGate(4), range(4))
    qc.rx(0.4, 1)
    qc.ccx(0, 1, 2)
    qc.crz(0.5, 0, 5)
    qc.measure(0, 0)
    with qc.if_test((qc.clbits[0], True)):
        for q in range(1, 6):
            qc.rx(0.3 * q, q)
    qc.measure(range(6), range(6))
    return qc


def _ripple_adder() -> QuantumCircuit:
    """CDKM-style MAJ/UMA chain: CX and CCX runs that O3 would resynthesize into any 1q basis."""
    qc = QuantumCircuit(5)
    for i in (0, 2):
        qc.cx(i + 2, i + 1)
        qc.cx(i + 2, i)
        qc.ccx(i, i + 1, i + 2)
    for i in (2, 0):
        qc.ccx(i, i + 1, i + 2)
        qc.cx(i + 2, i)
        qc.cx(i, i + 1)
    return qc


@pytest.mark.parametrize(
    ("make", "cmap"),
    [
        (_mixed, CouplingMap.from_heavy_hex(3)),
        (_ripple_adder, CouplingMap.from_line(10)),
    ],
)
def test_output_is_physical_isa_on_device_edges(make, cmap):
    """Device gates only, multi-qubit ops and if_else on edges, ``crz`` angles in ``[0, 2π)``."""
    # The largest seed checks that every seed derived from it stays in the router's u64 range.
    out = dualrail_pm(cmap, seed=2**64 - 1).run(make())
    edges = set(cmap.get_edges())
    for ins in out.data:
        if len(ins.qubits) == 2:
            assert tuple(out.find_bit(q).index for q in ins.qubits) in edges, ins.name
        if ins.name == "crz":
            assert 0 <= ins.operation.params[0] < 2 * math.pi
    ops = set(out.count_ops()) - {"if_else"}
    for ins in out.data:
        for block in getattr(ins.operation, "blocks", ()):
            ops |= set(block.count_ops())
    assert ops <= DualRail.PHYSICAL_ISA | {"measure"}


def _measure_in_if_else():
    qc = QuantumCircuit(2, 2)
    qc.measure(0, 0)
    with qc.if_test((qc.clbits[0], True)):
        qc.measure(1, 1)
    return qc


def _two_qubit_if_else():
    qc = QuantumCircuit(2, 1)
    qc.measure(0, 0)
    with qc.if_test((qc.clbits[0], True)):
        qc.cx(0, 1)
    return qc


def _while_loop():
    qc = QuantumCircuit(2, 1)
    qc.measure(0, 0)
    with qc.while_loop((qc.clbits[0], True)):
        qc.x(1)
    return qc


def _four_qubits():
    qc = QuantumCircuit(4)
    qc.crz(0.3, 0, 3)
    return qc


@pytest.mark.parametrize(
    ("make", "message"),
    [
        (_two_qubit_if_else, "one if_else per qubit"),
        (_measure_in_if_else, "measurement inside a control-flow block"),
        (_while_loop, "does not support 'while_loop'"),
        (_four_qubits, "needs 8 physical qubits"),
    ],
)
def test_unsupported_circuit_raises(make, message):
    pm = dualrail_pm(CouplingMap.from_grid(2, 3), seed=0)
    with pytest.raises(TranspilerError, match=message):
        pm.run(make())


def test_disconnected_coupling_map_raises():
    with pytest.raises(ValueError, match="disconnected"):
        dualrail_pm(CouplingMap([[0, 1], [2, 3]]))


def _shot(qc: QuantumCircuit, seed: int, lost: int | None = None) -> dict[Clbit, int]:
    """One shot of ``qc`` by statevector, with mid-circuit measurements: clbit -> outcome.

    Logical qubit ``lost`` never gets its photon: its rails are not prepared and stay |00>.
    """
    if lost is not None:
        # Follow routing SWAPs to find the rails of ``lost`` where they are prepared.
        holds = {p: v for v, p in enumerate(qc.layout.initial_index_layout())}
        prepared = qc.copy_empty_like()
        for ci in qc.data:
            phys = [qc.find_bit(q).index for q in ci.qubits]
            if ci.name == "swap":
                a, b = phys
                holds[a], holds[b] = holds[b], holds[a]
            if not (
                ci.name == "initialize" and {holds[p] // 2 for p in phys} == {lost}
            ):
                prepared.append(ci)
        qc = prepared
    sv, bits = Statevector.from_int(0, 2**qc.num_qubits), {}
    sv.seed(seed)
    for ci in qc.decompose(["pauli_product_measurement", "initialize"]).data:
        qargs = [qc.find_bit(q).index for q in ci.qubits]
        if ci.operation.name == "measure":
            outcome, sv = sv.measure(qargs)
            bits[ci.clbits[0]] = int(outcome)
        else:
            sv = sv.evolve(ci.operation, qargs)
    return bits


def test_erasure_check_is_local_flags_its_own_qubit_and_keeps_the_state():
    """Each check is on a device edge, reads 1 (photon present), and leaves a superposition intact.

    A qubit that lost its photon reads 0 on its own check and on no other.
    """
    body = QuantumCircuit(3)
    body.h(range(3))
    body.crz(1.0, 0, 1)
    body.crz(0.7, 1, 2)
    body.crz(0.5, 0, 2)
    qc = QuantumCircuit(3, 6)
    qc.compose(body, inplace=True)
    for q in range(3):
        qc.append(ErasureCheck(), [q], [3 + q])
    qc.compose(body.inverse(), inplace=True)
    qc.measure(range(3), range(3))  # entangle, check, undo: the logical outcome is 000

    cmap = CouplingMap.from_line(6)
    pm = dualrail_pm(cmap, seed=0)
    out = pm.run(qc)
    assert pm.property_set["online_n_swaps"] > 0  # the checks sit between routed gates
    checks = [ci for ci in out.data if ci.name == "pauli_product_measurement"]
    assert len(checks) == 3
    edges = set(cmap.get_edges())
    assert all(
        tuple(out.find_bit(q).index for q in ci.qubits) in edges for ci in checks
    )
    for seed in range(8):
        bits = _shot(out, seed)
        assert [bits[out.clbits[i]] for i in range(6)] == [0, 0, 0, 1, 1, 1]
    for lost in range(3):
        bits = _shot(out, 0, lost)
        assert [bits[out.clbits[3 + q]] for q in range(3)] == [
            int(q != lost) for q in range(3)
        ]
