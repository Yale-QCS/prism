"""The routing pass through its public interface."""

from qiskit import QuantumCircuit, QuantumRegister
from qiskit.circuit.library import CRZGate
from qiskit.converters import circuit_to_dag
from qiskit.transpiler import CouplingMap
from qiskit.transpiler.passes import DenseLayout

from prism import routing as prism_module
from prism.encodings import DualRail
from prism.ir import (
    MultiRealization,
    MultiRealizationInstruction,
    commuting_predecessors,
)
from prism.routing import PrismRouting, SearchBudget


def _program(n_logical: int, data) -> MultiRealization:
    return MultiRealization(
        enc=DualRail,
        qregs=[QuantumRegister(2, f"q{i}") for i in range(n_logical)],
        cregs=[],
        clbits=[],
        data=list(data),
        logical_output_permutation=tuple(range(n_logical)),
    )


def test_default_search_budget_is_explicit():
    assert PrismRouting(CouplingMap.from_line(4)).budget == SearchBudget(
        40, 16, 40, "swaps"
    )


def test_diagonal_ops_commute_and_others_wait():
    """Two diagonals on a wire follow the earlier non-diagonal only; the next non-diagonal follows both."""
    wires = [{0}, {0, 1}, {0}, {0}]
    diagonal = [False, True, True, False]
    assert commuting_predecessors(wires, diagonal) == [set(), {0}, {0}, {0, 1, 2}]


def test_available_crz_routes_without_swaps_on_its_default():
    """A CRZ whose default candidate is adjacent commits it whole, with its local RZ."""
    prog = _program(
        2, [MultiRealizationInstruction(DualRail.crz(CRZGate(0.3)), (0, 1, 2, 3))]
    )
    placed = PrismRouting(CouplingMap.from_line(4), seed=0).run(prog)

    [ins] = placed.data
    assert ins.operation.choice == ins.operation.default_index == 2
    assert placed.to_circuit().count_ops() == {"crz": 1, "rz": 1}


def test_dense_start_is_qiskits_dense_layout():
    """The dense start occupies the subgraph Qiskit's ``DenseLayout`` picks (in BFS order)."""
    for cmap in (CouplingMap.from_heavy_hex(3), CouplingMap.from_grid(3, 4)):
        target = prism_module.RoutingTarget.from_coupling_list(
            list(cmap.get_edges()), cmap.size()
        )
        for k in (1, 5, cmap.size()):
            qc = QuantumCircuit(k)
            dense = DenseLayout(cmap)
            dense.run(circuit_to_dag(qc))
            layout = dense.property_set["layout"]
            v2p = target.dense_layout(k)
            assert sorted(v2p[:k]) == sorted(layout[q] for q in qc.qubits)
            assert sorted(v2p) == list(range(cmap.size()))
        assert target.dense_layout(0) == list(range(cmap.size()))
