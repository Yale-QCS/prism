"""End-to-end check: every lowering strategy runs on a small circuit."""

import pytest
from qiskit.circuit import QuantumCircuit
from qiskit.circuit.library import QFTGate
from qiskit.transpiler import CouplingMap

from marabbecca.encodings import DualRail
from marabbecca.staged_pms import build_pm


@pytest.mark.parametrize("strategy", ["trivial", "logical", "greedy", "prism"])
def test_build_pm_runs(strategy):
    n = 4
    qc = QuantumCircuit(n)
    qc.append(QFTGate(n), range(n))
    cm = CouplingMap.from_grid(2, n)
    pm = build_pm(cm, enc=DualRail, strategy=strategy, seed=0)
    out = pm.run(qc)
    assert out is not None
    assert "circuit_metrics" in pm.property_set


@pytest.mark.parametrize("strategy", ["trivial", "logical", "greedy", "prism"])
def test_conditional_logical_x_survives_physical_optimization(strategy):
    """A control-flow block must retain the rail SWAP that implements X_L."""
    qc = QuantumCircuit(2, 1)
    with qc.if_test((qc.clbits[0], True)):
        qc.x(0)
    qc.crz(0.3, 0, 1)

    pm = build_pm(
        CouplingMap.from_grid(2, 2),
        enc=DualRail,
        strategy=strategy,
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
    assert pm.property_set["swap_before_measure_skipped_for_control_flow"] is True


@pytest.mark.parametrize("seed", [0, 1, 42, 2**32 - 1, 2**64 - 1])
def test_prism_seed_boundaries(seed):
    """Every Python-to-Rust seed derivation stays in u64 range."""
    n = 4
    qc = QuantumCircuit(n)
    qc.append(QFTGate(n), range(n))
    cm = CouplingMap.from_grid(2, n)
    pm = build_pm(cm, enc=DualRail, strategy="prism", seed=seed)
    pm.run(qc)
    assert "circuit_metrics" in pm.property_set


def test_prism_same_seed_repeats():
    n = 4
    qc = QuantumCircuit(n)
    qc.append(QFTGate(n), range(n))
    cm = CouplingMap.from_grid(2, n)
    metrics = []
    for _ in range(2):
        pm = build_pm(cm, enc=DualRail, strategy="prism", seed=7)
        pm.run(qc)
        metrics.append(pm.property_set["circuit_metrics"])
    assert metrics[0] == metrics[1]
