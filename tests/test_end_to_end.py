"""What a compiled circuit looks like to a user: device gates on device edges, documented errors."""

import pytest
from qiskit.circuit import Clbit, QuantumCircuit
from qiskit.circuit.library import QFTGate
from qiskit.quantum_info import Statevector
from qiskit.transpiler import CouplingMap, TranspilerError

from prism.encodings import DualRail, ErasureCheck
from prism.pipeline import build_pm


def test_output_is_physical_isa_on_device_edges():
    """No gate leaves the code space, and every multi-qubit op, if_else included, is on an edge."""
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
    cmap = CouplingMap.from_heavy_hex(3)
    # The largest seed checks that every seed derived from it stays in the router's u64 range.
    out = build_pm(cmap, enc=DualRail, seed=2**64 - 1).run(qc)
    edges = set(cmap.get_edges())
    for ins in out.data:
        if len(ins.qubits) == 2:
            assert tuple(out.find_bit(q).index for q in ins.qubits) in edges, ins.name
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
    pm = build_pm(CouplingMap.from_grid(2, 3), enc=DualRail, seed=0)
    with pytest.raises(TranspilerError, match=message):
        pm.run(make())


@pytest.mark.parametrize(
    ("cmap", "message"),
    [
        (CouplingMap([[0, 1], [1, 0], [2, 3], [3, 2]]), "disconnected"),
        (CouplingMap.from_line(6, bidirectional=False), "make_symmetric"),
    ],
)
def test_unsupported_coupling_map_raises(cmap, message):
    with pytest.raises(ValueError, match=message):
        build_pm(cmap, enc=DualRail)


def _shot(qc: QuantumCircuit, seed: int) -> dict[Clbit, int]:
    """One shot of ``qc`` by statevector, with mid-circuit measurements: clbit -> outcome."""
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


def test_erasure_check_is_local_reads_no_loss_and_keeps_the_state():
    """Each check is on a device edge, reads 1 (photon present), and leaves a superposition intact."""
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
    pm = build_pm(cmap, enc=DualRail, seed=0)
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
