"""End-to-end checks on small circuits."""

import os
import subprocess
import sys

import numpy as np
import pytest
from qiskit.circuit import QuantumCircuit
from qiskit.circuit.library import QFTGate
from qiskit.passmanager import PropertySet
from qiskit.transpiler import CouplingMap, TranspilerError

from prism.encodings import DualRail
from prism.pipeline import build_pm


def test_build_pm_runs():
    n = 4
    qc = QuantumCircuit(n)
    qc.append(QFTGate(n), range(n))
    cm = CouplingMap.from_grid(2, n)
    pm = build_pm(cm, enc=DualRail, seed=0)
    ps = PropertySet()
    out = pm.run(qc, property_set=ps)
    assert out is not None
    assert "circuit_metrics" in ps


def test_conditional_logical_x_survives_physical_optimization():
    """A control-flow block must retain the rail SWAP that implements X_L."""
    qc = QuantumCircuit(2, 1)
    with qc.if_test((qc.clbits[0], True)):
        qc.x(0)
    qc.crz(0.3, 0, 1)

    pm = build_pm(
        CouplingMap.from_grid(2, 2),
        enc=DualRail,
        seed=0,
    )
    out = pm.run(qc)
    blocks = [
        block
        for instruction in out.data
        if instruction.operation.name == "if_else"
        for block in instruction.operation.blocks
    ]

    assert blocks
    assert sum(block.count_ops().get("swap", 0) for block in blocks) == 1


def test_multi_qubit_if_else_is_routed():
    """An if_else over several qubits is routed: one if_else per qubit, on adjacent rails."""
    rng = np.random.default_rng(0)
    qc = QuantumCircuit(6, 1)
    for _ in range(40):
        a, b = rng.choice(6, 2, replace=False)
        qc.crz(float(rng.uniform(0.1, 3)), int(a), int(b))
    qc.h(0)
    qc.measure(0, 0)
    with qc.if_test((qc.clbits[0], True)):
        for q in range(1, 6):
            qc.rx(0.3 * q, q)
    cmap = CouplingMap.from_heavy_hex(3)
    out = build_pm(cmap, enc=DualRail, seed=0).run(qc)
    pairs = [
        tuple(out.find_bit(q).index for q in ins.qubits)
        for ins in out.data
        if ins.operation.name == "if_else"
    ]
    assert len(pairs) == 5
    assert all(cmap.graph.has_edge(*p) or cmap.graph.has_edge(*p[::-1]) for p in pairs)


def test_if_else_with_multi_qubit_body_raises():
    qc = QuantumCircuit(2, 1)
    qc.measure(0, 0)
    with qc.if_test((qc.clbits[0], True)):
        qc.cx(0, 1)
    with pytest.raises(TranspilerError, match="one if_else per qubit"):
        build_pm(CouplingMap.from_grid(2, 3), enc=DualRail, seed=0).run(qc)


def test_measure_inside_if_else_raises():
    qc = QuantumCircuit(2, 2)
    qc.measure(0, 0)
    with qc.if_test((qc.clbits[0], True)):
        qc.measure(1, 1)
    with pytest.raises(
        TranspilerError, match="measurement inside a control-flow block"
    ):
        build_pm(CouplingMap.from_grid(2, 3), enc=DualRail, seed=0).run(qc)


@pytest.mark.parametrize("seed", [0, 1, 42, 2**32 - 1, 2**64 - 1])
def test_prism_seed_boundaries(seed):
    """Every Python-to-Rust seed derivation stays in u64 range."""
    n = 4
    qc = QuantumCircuit(n)
    qc.append(QFTGate(n), range(n))
    cm = CouplingMap.from_grid(2, n)
    pm = build_pm(cm, enc=DualRail, seed=seed)
    ps = PropertySet()
    pm.run(qc, property_set=ps)
    assert "circuit_metrics" in ps


def test_prism_same_seed_repeats():
    n = 4
    qc = QuantumCircuit(n)
    qc.append(QFTGate(n), range(n))
    cm = CouplingMap.from_grid(2, n)
    metrics = []
    for _ in range(2):
        pm = build_pm(cm, enc=DualRail, seed=7)
        ps = PropertySet()
        pm.run(qc, property_set=ps)
        metrics.append(ps["circuit_metrics"])
    assert metrics[0] == metrics[1]


def test_disconnected_coupling_map_is_rejected():
    cmap = CouplingMap([[0, 1], [1, 0], [2, 3], [3, 2]])
    with pytest.raises(ValueError, match="disconnected"):
        build_pm(cmap, enc=DualRail)


def test_directed_coupling_map_is_rejected():
    with pytest.raises(ValueError, match="make_symmetric"):
        build_pm(CouplingMap.from_line(6, bidirectional=False), enc=DualRail)


def test_too_many_qubits_raises():
    qc = QuantumCircuit(4)
    qc.crz(0.3, 0, 3)
    pm = build_pm(CouplingMap.from_grid(2, 3), enc=DualRail)
    with pytest.raises(TranspilerError, match="needs 8 physical qubits"):
        pm.run(qc)


def test_unsupported_control_flow_raises():
    qc = QuantumCircuit(2, 1)
    qc.measure(0, 0)
    with qc.while_loop((qc.clbits[0], True)):
        qc.x(1)
    pm = build_pm(CouplingMap.from_grid(2, 3), enc=DualRail)
    with pytest.raises(TranspilerError, match="does not support 'while_loop'"):
        pm.run(qc)


_NO_HANG = """
from qiskit import QuantumCircuit
from qiskit.transpiler import CouplingMap
from prism.encodings import DualRail
from prism.pipeline import build_pm
qc = QuantumCircuit(4, 1)
for q in range(4):
    qc.rx(0.3 + q, q)
for a, b in [(0, 1), (1, 2), (2, 3), (0, 2), (1, 3)]:
    qc.crz(0.7, a, b)
    qc.rz(0.2, b)
qc.measure(0, 0)
with qc.if_test((qc.clbits[0], True)):
    qc.x(1)
qc.reset(2)
qc.crz(0.4, 2, 3)
build_pm(CouplingMap.from_grid(3, 4), DualRail, seed=1).run(qc)
"""


def test_physical_stage_commutation_does_not_hang():
    """Stock commutation passes on rswap/joint_herald/if_else and diagonal runs finish (Qiskit/qiskit#16937)."""
    env = {**os.environ, "QISKIT_IN_PARALLEL": "FALSE", "RAYON_NUM_THREADS": "4"}
    subprocess.run([sys.executable, "-c", _NO_HANG], env=env, check=True, timeout=120)
