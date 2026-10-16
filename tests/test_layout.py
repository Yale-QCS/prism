"""The output's ``TranspileLayout`` is rail-level and complete."""

from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector
from qiskit.transpiler import CouplingMap

from prism.encodings import DualRail
from prism.pipeline import build_pm


def _compile(qc: QuantumCircuit):
    pm = build_pm(CouplingMap.from_grid(3, 3), DualRail, seed=0)
    return pm.run(qc), pm.property_set


def test_every_accessor_works_on_rails_and_ancillas():
    qc = QuantumCircuit(3)
    qc.h(0)
    qc.cx(0, 1)
    qc.cx(1, 2)
    out, _ = _compile(qc)
    lay = out.layout
    initial = lay.initial_index_layout()
    assert sorted(initial) == list(range(9))
    assert len(lay.initial_index_layout(filter_ancillas=True)) == 6
    assert sorted(lay.final_index_layout(filter_ancillas=False)) == list(range(9))
    assert sorted(lay.routing_permutation()) == list(range(9))
    names = {reg.name for reg in lay.initial_layout.get_registers()}
    assert names == {"q0", "q1", "q2", "ancilla"}
    rails = lay.initial_virtual_layout(filter_ancillas=True)
    (q0,) = [reg for reg in lay.initial_layout.get_registers() if reg.name == "q0"]
    assert [rails[p] for p in initial[:2]] == list(
        q0
    )  # virtual 2i + w is rail w of q<i>


def test_elided_logical_swap_is_in_the_final_layout():
    """``x(0); swap(0, 1)``: logical 1 ends in |1_L> = |10> on its rails, read through ``final_index_layout``."""
    qc = QuantumCircuit(2)
    qc.x(0)
    qc.swap(0, 1)
    out, ps = _compile(qc)
    assert ps["logical_output_permutation"] == (1, 0)
    final = out.layout.final_index_layout()
    (index,) = [i for i, p in enumerate(Statevector(out).probabilities()) if p > 0.5]
    excited = [(index >> final[v]) & 1 for v in range(4)]
    assert excited == [0, 1, 1, 0]  # logical 0: |01> = |0_L>; logical 1: |10> = |1_L>
