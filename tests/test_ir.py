"""The ``MultiRealization`` IR: what the entrance builds, ``verify``, ``to_circuit``, and a user pass."""

from dataclasses import replace

import pytest
from qiskit import QuantumCircuit
from qiskit.circuit import Clbit
from qiskit.circuit.library import CXGate
from qiskit.converters import circuit_to_dag
from qiskit.passmanager import GenericPass, PropertySet
from qiskit.transpiler import CouplingMap, TranspilerError

from prism.encodings import DualRail
from prism.ir import MultiRealization, MultiRealizationInstruction, MultiRealizationOp
from prism.pipeline import DAGToMultiRealization, build_pm
from prism.routing import PrismRouting


def _program(qc: QuantumCircuit) -> MultiRealization:
    return DAGToMultiRealization(DualRail).run(
        circuit_to_dag(DualRail.logical_pm().run(qc))
    )


def _bell() -> QuantumCircuit:
    qc = QuantumCircuit(2, 2)
    qc.h(0)
    qc.cx(0, 1)
    qc.measure([0, 1], [0, 1])
    return qc


def test_entrance_binds_rails_and_heralds():
    ir = _program(_bell())
    assert [reg.name for reg in ir.qregs] == ["q0", "q1"]
    assert ir.logical_output_permutation == (0, 1)
    assert ir.placement is None
    # preparation first, as plain ops: (x, joint_herald) per logical qubit
    prep, lowered = ir.data[:4], ir.data[4:]
    assert [ins.operation.name for ins in prep] == ["x", "joint_herald"] * 2
    assert not any(isinstance(ins.operation, MultiRealizationOp) for ins in prep)
    assert all(isinstance(ins.operation, MultiRealizationOp) for ins in lowered)
    crz = [ins for ins in ir.data if ins.operation.name == "crz"]
    assert crz and all(
        ins.operation.diagonal and len(ins.operation.candidates) == 4 for ins in crz
    )
    measures = [ins for ins in ir.data if ins.operation.name == "measure"]
    assert [ins.qubits for ins in measures] == [(0, 1), (2, 3)]
    assert [ins.clbits[0] for ins in measures] == ir.clbits[
        :2
    ]  # logical bits read rail 0
    assert ir.cregs[-1].name == "herald" and len(ir.cregs[-1]) == 2


def test_to_circuit_materializes_choices_on_rails():
    ir = _program(_bell())
    with pytest.raises(TranspilerError, match="has no realization choice"):
        ir.to_circuit()
    for k, ins in enumerate(ir.data):
        if isinstance(ins.operation, MultiRealizationOp):
            ir.data[k] = ins._replace(
                operation=replace(ins.operation, choice=ins.operation.default_index)
            )
    qc = ir.to_circuit()
    assert qc.num_qubits == 4 and [r.name for r in qc.qregs] == ["q0", "q1"]
    assert qc.count_ops()["measure"] == 4 and qc.count_ops()["crz"] >= 1


@pytest.mark.parametrize(
    ("break_it", "message"),
    [
        (
            lambda ir: setattr(ir, "logical_output_permutation", (0, 0)),
            "not a permutation",
        ),
        (
            lambda ir: ir.data.append(MultiRealizationInstruction(CXGate(), (0, 9))),
            "bad wires",
        ),
        (
            lambda ir: ir.data.append(
                MultiRealizationInstruction(
                    MultiRealizationOp("ccx", (_ccx(),)), (0, 1, 2)
                )
            ),
            "the router needs gates on at most 2 wires",
        ),
        (
            lambda ir: ir.data.append(
                MultiRealizationInstruction(
                    MultiRealizationOp("cx", (_cx(),), diagonal=True), (0, 2)
                )
            ),
            "marked diagonal",
        ),
        (
            lambda ir: ir.data.append(
                MultiRealizationInstruction(
                    MultiRealizationOp("cx", (_cx(),), choice=3), (0, 2)
                )
            ),
            "choice 3 out of range",
        ),
        (
            lambda ir: ir.data.append(
                MultiRealizationInstruction(CXGate(), (0, 2), (Clbit(),))
            ),
            "bound to 2 qubits, 1 clbits",
        ),
    ],
)
def test_verify_rejects(break_it, message):
    ir = _program(_bell())
    ir.verify()
    break_it(ir)
    with pytest.raises(TranspilerError, match=message):
        ir.verify()


def test_verify_rejects_wide_control_flow_with_two_qubit_gates():
    body = QuantumCircuit(4, 1)
    body.cx(0, 2)
    qc = QuantumCircuit(4, 1)
    qc.if_else((qc.clbits[0], True), body, None, range(4), [0])
    op = MultiRealizationOp("if_else", (qc,))
    ir = _program(_bell())
    ir.data.append(MultiRealizationInstruction(op, (0, 1, 2, 3), (ir.clbits[0],)))
    with pytest.raises(TranspilerError, match="holds gates the router cannot see"):
        ir.verify()


def _cx() -> QuantumCircuit:
    qc = QuantumCircuit(2)
    qc.cx(0, 1)
    return qc


def _ccx() -> QuantumCircuit:
    qc = QuantumCircuit(3)
    qc.ccx(0, 1, 2)
    return qc


class PinDefaultCRZ(GenericPass[MultiRealization, MultiRealization]):
    """Keep only the encoding's default candidate of every ``crz``."""

    def run(self, passmanager_ir: MultiRealization) -> MultiRealization:
        for k, ins in enumerate(passmanager_ir.data):
            op = ins.operation
            if isinstance(op, MultiRealizationOp) and op.name == "crz":
                pinned = replace(
                    op, candidates=(op.candidates[op.default_index],), default_index=0
                )
                passmanager_ir.data[k] = ins._replace(operation=pinned)
        return passmanager_ir


def test_user_pass_narrows_candidates_before_routing():
    cmap = CouplingMap.from_grid(2, 3)
    pm = build_pm(cmap, DualRail, seed=0)
    pm.routing = [PinDefaultCRZ(), PrismRouting(cmap, seed=0)]
    seen = []

    def watch(*, task, passmanager_ir, **_):
        if isinstance(task, PrismRouting):
            seen.append(passmanager_ir)

    ps = PropertySet()
    pm.run(_bell(), callback=watch, property_set=ps)
    (placed,) = seen
    crz = [
        ins.operation
        for ins in placed.data
        if getattr(ins.operation, "name", None) == "crz"
    ]
    assert crz and all(len(op.candidates) == 1 and op.choice == 0 for op in crz)
    # the default candidate (control on rail 1) carries the open-control RZ
    assert all(dict(op.candidates[0].count_ops()) == {"crz": 1, "rz": 1} for op in crz)
    assert ps["realization_choices"] == ()  # nothing left to decide


def test_loose_clbit_condition_compiles():
    bit = Clbit()
    qc = QuantumCircuit(2)
    qc.add_bits([bit])
    qc.h(0)
    qc.measure(0, bit)
    with qc.if_test((bit, True)):
        qc.x(1)
    out = build_pm(CouplingMap.from_grid(2, 3), DualRail, seed=0).run(qc)
    assert bit in out.clbits
    assert out.count_ops()["if_else"] == 1
