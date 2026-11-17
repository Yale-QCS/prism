"""E03: routing-SWAP accounting separates semantic swaps from routing ones."""

import pytest
from qiskit.circuit import QuantumCircuit
from qiskit.transpiler import CouplingMap

from marabbecca.encodings import DualRail
from marabbecca.staged_pms import build_pm

STRATEGIES = ["trivial", "logical", "greedy", "prism"]
ALL_PAIRS_4 = [(0, 1), (1, 2), (2, 3), (0, 3), (0, 2), (1, 3)]


def _swaps(qc, cm, strategy, seed=0):
    """Return ``(routing_swaps, semantic_swaps)`` after a full compile."""
    pm = build_pm(cm, enc=DualRail, strategy=strategy, seed=seed)
    pm.run(qc)
    return pm.property_set["routing_swaps"], pm.property_set["semantic_swaps"]


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_crz_only_has_no_semantic_swaps(strategy):
    """A crz-only circuit lowers with zero swap bodies; every swap is routing."""
    qc = QuantumCircuit(3)
    qc.crz(0.3, 0, 1)
    qc.crz(0.5, 1, 2)
    qc.crz(0.7, 0, 2)
    routing, semantic = _swaps(qc, CouplingMap.from_grid(2, 4), strategy)
    assert semantic == 0
    assert routing >= 0


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_logical_x_is_semantic_swap(strategy):
    """A logical X materializes as at least one semantic rail swap."""
    qc = QuantumCircuit(3)
    qc.crz(0.3, 0, 2)
    qc.x(1)
    routing, semantic = _swaps(qc, CouplingMap.from_line(8), strategy, seed=1)
    assert semantic >= 1
    assert routing >= 0


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_movement_required_on_line_is_counted_as_routing(strategy):
    """All-pairs crz at n=4 on a line cannot route free."""
    qc = QuantumCircuit(4)
    for a, b in ALL_PAIRS_4:
        qc.crz(0.4, a, b)
    routing, semantic = _swaps(qc, CouplingMap.from_line(10), strategy)
    assert semantic == 0
    assert routing > 0
