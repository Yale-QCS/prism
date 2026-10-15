"""The pipeline's shape: stage order, declared IRs, guards, and IR bookkeeping."""

from typing import Any, TypeVar, get_args, get_origin

import pytest
from qiskit import QuantumCircuit
from qiskit.dagcircuit import DAGCircuit
from qiskit.passmanager import FlowControllerLinear, GenericPass, PropertySet
from qiskit.passmanager.base_tasks import Task
from qiskit.transpiler import CouplingMap, PassManager, TranspilerError
from qiskit.transpiler.passes import Size

from prism.encodings import DualRail
from prism.ir import MultiRealization
from prism.pipeline import (
    DAGToMultiRealization,
    MultiRealizationToDAG,
    build_pm,
)
from prism.routing import PrismRouting


def ir_types(cls: type) -> tuple[type, type]:
    """``(IN, OUT)`` from the first concrete ``Task[IN, OUT]`` base of ``cls``."""
    for klass in cls.__mro__:
        for base in klass.__dict__.get("__orig_bases__", ()):
            origin, args = get_origin(base), get_args(base)
            if (
                isinstance(origin, type)
                and issubclass(origin, Task)
                and len(args) == 2
                and not any(isinstance(a, TypeVar) for a in args)
            ):
                return args
    raise TypeError(f"{cls.__qualname__} is not a subscripted GenericPass[IN, OUT]")


def stage_irs(stage: Any) -> tuple[type, type]:
    """IRs a stage takes and returns; a pass manager is a ``DAGCircuit`` region."""
    if isinstance(stage, PassManager):
        return DAGCircuit, DAGCircuit
    if isinstance(stage, FlowControllerLinear):
        stage = stage.tasks
    if isinstance(stage, Task):
        return ir_types(type(stage))
    irs = [stage_irs(task) for task in stage]
    for (_, out), (nxt, _) in zip(irs, irs[1:]):
        assert out is nxt, f"{out.__name__} feeds {nxt.__name__} inside a stage"
    return irs[0][0], irs[-1][1]


def check_ir_chain(pm: Any) -> None:
    ir = QuantumCircuit
    for name in pm.stages:
        stage_in, stage_out = stage_irs(getattr(pm, name))
        assert stage_in is ir, (
            f"stage {name!r} takes {stage_in.__name__}, gets {ir.__name__}"
        )
        ir = stage_out
    assert ir is QuantumCircuit


def test_stages_are_typed_and_adjacent():
    pm = build_pm(CouplingMap.from_grid(3, 3), DualRail)
    assert pm.stages == (
        "input",
        "logical",
        "dag_to_multi_realization",
        "routing",
        "multi_realization_to_dag",
        "physical",
        "output",
    )
    check_ir_chain(pm)


def test_miswired_stage_is_caught():
    pm = build_pm(CouplingMap.from_grid(3, 3), DualRail)
    pm.routing = MultiRealizationToDAG()
    with pytest.raises(AssertionError, match="takes MultiRealization, gets DAGCircuit"):
        check_ir_chain(pm)


def test_unsubscripted_pass_is_rejected():
    class Bare(GenericPass):
        def run(self, passmanager_ir):
            return passmanager_ir

    with pytest.raises(TypeError, match="subscripted"):
        ir_types(Bare)


def test_boundary_passes_guard_their_input_type():
    with pytest.raises(TypeError, match="takes a DAGCircuit, got QuantumCircuit"):
        DAGToMultiRealization(DualRail).run(QuantumCircuit(1))
    with pytest.raises(TypeError, match="takes a MultiRealization, got DAGCircuit"):
        MultiRealizationToDAG().run(DAGCircuit())


def _bell():
    qc = QuantumCircuit(2)
    qc.h(0)
    qc.cx(0, 1)
    return qc


def test_exit_needs_placement_and_choices():
    pm = build_pm(CouplingMap.from_grid(2, 3), DualRail)
    pm.routing = []
    with pytest.raises(TranspilerError, match="needs a placed program"):
        pm.run(_bell())

    class Undecide(GenericPass[MultiRealization, MultiRealization]):
        def run(self, passmanager_ir: MultiRealization) -> MultiRealization:
            from dataclasses import replace

            from prism.ir import MultiRealizationOp

            for k, ins in enumerate(passmanager_ir.data):
                if isinstance(ins.operation, MultiRealizationOp):
                    passmanager_ir.data[k] = ins._replace(
                        operation=replace(ins.operation, choice=None)
                    )
            return passmanager_ir

    pm.routing = [PrismRouting(CouplingMap.from_grid(2, 3)), Undecide()]
    with pytest.raises(
        TranspilerError,
        match=r"instruction \d+ \(\w+ on wires .*\) has no realization choice",
    ):
        pm.run(_bell())


def test_ir_changing_passes_reset_completed_analyses():
    """An analysis equal to one that ran before an IR change runs again after it."""
    pm = build_pm(CouplingMap.from_grid(2, 3), DualRail)
    pm.logical = [*pm.logical.to_flow_controller().tasks, Size()]
    pm.physical = [Size()]
    ps = PropertySet()
    out = pm.run(_bell(), property_set=ps)
    assert ps["size"] == out.size() > 0


def test_several_circuits_run_serially():
    outs = build_pm(CouplingMap.from_grid(2, 3), DualRail).run([_bell(), _bell()])
    assert len(outs) == 2
