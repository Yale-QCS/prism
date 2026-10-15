"""End-to-end checks on small circuits."""

import numpy as np
import pytest
from qiskit.circuit import QuantumCircuit
from qiskit.circuit.library import QFTGate
from qiskit.transpiler import CouplingMap, TranspilerError

from prism.encodings import DualRail
from prism.pipeline import build_pm


def test_build_pm_runs():
    n = 4
    qc = QuantumCircuit(n)
    qc.append(QFTGate(n), range(n))
    cm = CouplingMap.from_grid(2, n)
    pm = build_pm(cm, enc=DualRail, seed=0)
    out = pm.run(qc)
    assert out is not None
    assert "circuit_metrics" in pm.property_set


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


@pytest.mark.parametrize("seed", [0, 1, 42, 2**32 - 1, 2**64 - 1])
def test_prism_seed_boundaries(seed):
    """Every Python-to-Rust seed derivation stays in u64 range."""
    n = 4
    qc = QuantumCircuit(n)
    qc.append(QFTGate(n), range(n))
    cm = CouplingMap.from_grid(2, n)
    pm = build_pm(cm, enc=DualRail, seed=seed)
    pm.run(qc)
    assert "circuit_metrics" in pm.property_set


def test_prism_same_seed_repeats():
    n = 4
    qc = QuantumCircuit(n)
    qc.append(QFTGate(n), range(n))
    cm = CouplingMap.from_grid(2, n)
    metrics = []
    for _ in range(2):
        pm = build_pm(cm, enc=DualRail, seed=7)
        pm.run(qc)
        metrics.append(pm.property_set["circuit_metrics"])
    assert metrics[0] == metrics[1]
