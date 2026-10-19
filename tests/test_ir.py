"""The contract user passes rely on: ``verify`` and the exit reject a bad IR, analyses rerun."""

from dataclasses import replace

import pytest
from qiskit import QuantumCircuit
from qiskit.converters import circuit_to_dag
from qiskit.transpiler import CouplingMap, PassManager, TranspilerError
from qiskit.transpiler.passes import Size

from prism.encodings import DualRail
from prism.ir import MultiRealization, MultiRealizationOp, Placement
from prism.pipeline import DAGToMultiRealization, prism_stages
from prism.routing import PrismRouting


def _bell() -> QuantumCircuit:
    qc = QuantumCircuit(2, 2)
    qc.h(0)
    qc.cx(0, 1)
    qc.measure([0, 1], [0, 1])
    return qc


def _placed() -> MultiRealization:
    ir = DAGToMultiRealization(DualRail).run(
        circuit_to_dag(DualRail.logical_pm().run(_bell()))
    )
    placed = PrismRouting(CouplingMap.from_line(4), seed=0).run(ir)
    placed.verify()
    return placed


def test_verify_rejects_a_bad_placement():
    placed = _placed()
    placed.placement = Placement((0, 0, 1, 2), (0, 1, 2, 3), placed.placement.edges)
    with pytest.raises(TranspilerError, match="not a pair of permutations"):
        placed.verify()


def test_verify_rejects_a_choice_off_the_device_edges():
    """A pass after routing may revise a choice, but only to one the device can run."""
    placed = _placed()
    edges = placed.placement.edges
    for k, ins in enumerate(placed.data):
        op = ins.operation
        if not isinstance(op, MultiRealizationOp):
            continue
        for r, real in enumerate(op.candidates):
            pairs = [
                tuple(ins.qubits[real.find_bit(q).index] for q in ci.qubits)
                for ci in real.data
                if len(ci.qubits) == 2
            ]
            if any(p not in edges for p in pairs):
                placed.data[k] = ins._replace(operation=replace(op, choice=r))
                with pytest.raises(TranspilerError, match="not a device edge"):
                    placed.verify()
                return
    pytest.fail("every candidate is on an edge; pick a sparser coupling map")


def test_exit_needs_choices():
    stages = prism_stages(CouplingMap.from_grid(2, 3), DualRail)
    stages.multi_realization = []
    with pytest.raises(TranspilerError, match="has no realization choice"):
        PassManager([stages.to_flow_controller()]).run(_bell())


def test_ir_changing_passes_reset_completed_analyses():
    """An analysis equal to one that ran before an IR change runs again after it."""
    stages = prism_stages(CouplingMap.from_grid(2, 3), DualRail)
    stages.logical = [*stages.logical.to_flow_controller().tasks, Size()]
    stages.physical = [Size()]
    pm = PassManager([stages.to_flow_controller()])
    out = pm.run(_bell().remove_final_measurements(inplace=False))
    assert pm.property_set["size"] == out.size() > 0


def test_routing_takes_commuting_ops_left_with_one_pair():
    """A pass may drop candidates: diagonal ops left on one rail pair still route."""
    qc = QuantumCircuit(3)
    for theta, (a, b) in zip((0.3, 0.5, 0.7, 0.2), [(0, 1), (0, 1), (1, 2), (0, 1)]):
        qc.crz(theta, a, b)
    ir = DAGToMultiRealization(DualRail).run(
        circuit_to_dag(DualRail.logical_pm().run(qc))
    )
    for k, ins in enumerate(ir.data):
        op = ins.operation
        if isinstance(op, MultiRealizationOp):
            op = replace(op, candidates=op.candidates[:1], default_index=0)
            ir.data[k] = ins._replace(operation=op)
    PrismRouting(CouplingMap.from_line(6), seed=0).run(ir).verify()
