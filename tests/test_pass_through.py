"""Ops the router cannot route as one edge are passed through; the physical stage routes them."""

import warnings

import numpy as np
import pytest
from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector
from qiskit.transpiler import CouplingMap, PassManager

from prism.encodings import DualRail
from prism.pipeline import SearchBudget, build_pm, prism_stages

BUDGET = SearchBudget(layout_starts=4, refinement_iterations=2, swap_trials=4)


def _logical() -> QuantumCircuit:
    qc = QuantumCircuit(3)
    qc.rx(0.3, 0)
    qc.rx(1.1, 1)
    qc.crz(0.5, 0, 1)
    qc.swap(0, 2)
    qc.crz(0.9, 2, 1)
    qc.rx(0.7, 0)
    return qc


def _overlap(qc: QuantumCircuit, out: QuantumCircuit) -> float:
    """Overlap of ``out`` with the dual-rail encoding of ``qc``'s state, rail ``v`` on ``final_index_layout()[v]``."""
    final = out.layout.final_index_layout()
    expected = np.zeros(2**out.num_qubits, dtype=complex)
    for idx, amp in enumerate(Statevector(qc).data):
        bits = ((idx >> i) & 1 for i in range(qc.num_qubits))
        rails = (2 * i + (0 if b else 1) for i, b in enumerate(bits))
        expected[sum(1 << final[v] for v in rails)] += amp
    return abs(np.vdot(expected, Statevector(out).data))


def test_fully_routed_program_gets_no_physical_swaps():
    pm = build_pm(CouplingMap.from_grid(2, 4), DualRail, seed=0, budget=BUDGET)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = pm.run(_logical())
    # CheckMap finds every gate on an edge, so the physical stage's SabreSwap never runs.
    assert pm.property_set["routing_not_needed"]
    assert _overlap(_logical(), out) == pytest.approx(1.0, abs=1e-6)


def test_multi_edge_op_is_passed_through_and_routed_by_the_physical_stage():
    """With no logical stage the SWAP stays, and its candidates each span two rail pairs."""
    stages = prism_stages(CouplingMap.from_grid(2, 4), DualRail, seed=0, budget=BUDGET)
    stages.logical = PassManager()
    pm = PassManager([stages.to_flow_controller()])
    with pytest.warns(UserWarning, match="passed 1 operation"):
        out = pm.run(_logical())
    assert not pm.property_set["routing_not_needed"]
    assert _overlap(_logical(), out) == pytest.approx(1.0, abs=1e-6)
