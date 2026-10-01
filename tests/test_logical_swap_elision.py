"""Semantic logical SWAPs are elided before dual-rail expansion."""

from qiskit import QuantumCircuit
from qiskit.transpiler import CouplingMap

from prism.encodings import DualRail
from prism.pipeline import build_pm


def test_logical_stage_elides_swaps_and_records_output_permutation():
    qc = QuantumCircuit(3)
    qc.swap(0, 2)
    qc.swap(1, 2)
    qc.crz(0.25, 0, 1)

    pm = DualRail.logical_pm()
    out = pm.run(qc)

    assert "swap" not in out.count_ops()
    assert pm.property_set["logical_permutation_ops_elided"] == 2
    assert pm.property_set["logical_output_permutation"] == (1, 2, 0)
    assert out.metadata["logical_output_permutation"] == [1, 2, 0]


def test_full_pipeline_preserves_logical_output_permutation_metadata():
    qc = QuantumCircuit(2)
    qc.swap(0, 1)
    qc.crz(0.25, 0, 1)

    pm = build_pm(
        CouplingMap.from_grid(2, 2),
        enc=DualRail,
        seed=0,
    )
    out = pm.run(qc)

    assert pm.property_set["logical_output_permutation"] == (1, 0)
    assert out.metadata["logical_output_permutation"] == [1, 0]
