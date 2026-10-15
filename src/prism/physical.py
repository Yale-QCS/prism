"""Physical stage: the preset O3 pipeline over ``enc.PHYSICAL_ISA`` and prism's passes on it."""

from __future__ import annotations

import contextlib
import os
from typing import TYPE_CHECKING

import numpy as np
from qiskit.circuit import Measure
from qiskit.circuit.controlflow import (
    ForLoopOp,
    IfElseOp,
    SwitchCaseOp,
    WhileLoopOp,
)
from qiskit.circuit.library import (
    CRZGate,
    RZGate,
    SwapGate,
    XGate,
)
from qiskit.dagcircuit import DAGCircuit, DAGOpNode, DAGOutNode
from qiskit.passmanager import MultiStagePassManager
from qiskit.transpiler import (
    AnalysisPass,
    CouplingMap,
    Layout,
    PassManager,
    StagedPassManager,
    Target,
    TransformationPass,
)
from qiskit.transpiler.passes import CommutativeCancellation
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

from prism.synthesis.reschedule import RescheduleCommutingDiagonals
from prism.utils.metrics import (
    RecordCircuitMetrics,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from qiskit.circuit import Qubit

    from prism.encodings.base import QubitEncoding


# Qiskit 2.5 runs CommutationAnalysis on rayon workers while holding the GIL; the
# checker's Python fallback for custom gates then deadlocks (Qiskit/qiskit#16937,
# fixed upstream in Qiskit/qiskit#16963 for 2.6.0; drop this once the pin moves).
# Boundary ops are namespaced (``_L``) so CommutativeCancellation skips them, and
# the instances the preset carries run serially anyway.
@contextlib.contextmanager
def serial_commutation() -> Iterator[None]:
    """Force Qiskit's serial code paths (``QISKIT_IN_PARALLEL=TRUE``) inside the block."""
    old = os.environ.get("QISKIT_IN_PARALLEL")
    os.environ["QISKIT_IN_PARALLEL"] = "TRUE"
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("QISKIT_IN_PARALLEL", None)
        else:
            os.environ["QISKIT_IN_PARALLEL"] = old


class SerialCommutativeCancellation(CommutativeCancellation):
    """``CommutativeCancellation`` whose commutation analysis runs serially."""

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Run the stock pass inside ``serial_commutation``."""
        with serial_commutation():
            return super().run(dag)


def guard_commutation_passes(pm: object) -> int:
    """Swap every ``CommutativeCancellation`` in ``pm`` for the serial variant; return the count."""
    n = 0
    if isinstance(pm, MultiStagePassManager):
        for stage in pm.stages:
            n += guard_commutation_passes(getattr(pm, stage))
        return n
    if isinstance(pm, StagedPassManager):
        for stage in pm.expanded_stages:
            sub = getattr(pm, stage, None)
            if sub is not None:
                n += guard_commutation_passes(sub)
        return n
    if isinstance(pm, PassManager):
        for task in pm._tasks:
            n += _guard_task(task)
        return n
    return _guard_task(pm)


def _guard_task(task: object) -> int:
    if type(task) is CommutativeCancellation:
        task.__class__ = SerialCommutativeCancellation
        return 1
    if isinstance(
        task, (list, tuple)
    ):  # ``PassManager.append(list)`` stores lists as-is
        return sum(_guard_task(t) for t in task)
    tasks = getattr(task, "tasks", None)  # flow controllers
    return 0 if tasks is None else sum(_guard_task(t) for t in tasks)


class SwapBeforeMeasureToLayout(TransformationPass):
    """Remove a SWAP that only feeds final measurements; re-target them and update ``final_layout``.

    A SWAP qualifies when each of its wires next reaches a final measurement or
    the circuit's end, and at least one is measured. The measurements move to
    the other wire and ``final_layout`` absorbs the exchange, so the output keeps
    the measurement outcomes and, under ``final_layout``, every unmeasured state.
    Stock ``OptimizeSwapBeforeMeasure`` also removes a SWAP before two output
    nodes and updates no layout.
    """

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Remove qualifying SWAPs, last first, so a chain of them before a measurement goes too."""
        final = self.property_set["final_layout"] or Layout(
            {q: i for i, q in enumerate(dag.qubits)}
        )
        removed = False
        for swap in reversed(list(dag.topological_op_nodes())):
            if not isinstance(swap.op, SwapGate):
                continue
            succ = list(dag.quantum_successors(swap))
            measures = [n for n in succ if isinstance(n, DAGOpNode)]
            if not measures or not all(_is_final_measure(dag, n) for n in measures):
                continue
            a, b = swap.qargs
            for m in measures:
                dag.remove_op_node(m)
            dag.remove_op_node(swap)
            for m in measures:
                other = b if m.qargs[0] == a else a
                dag.apply_operation_back(m.op, (other,), m.cargs, check=False)
            ia, ib = dag.find_bit(a).index, dag.find_bit(b).index
            final = Layout(
                {
                    q: {ia: ib, ib: ia}.get(p, p)
                    for q, p in final.get_virtual_bits().items()
                }
            )
            removed = True
        if removed:
            self.property_set["final_layout"] = final
        return dag


def _is_final_measure(dag: DAGCircuit, node: DAGOpNode) -> bool:
    """``node`` is a measurement and nothing follows it on any wire."""
    return isinstance(node.op, Measure) and all(
        isinstance(s, DAGOutNode) for s in dag.successors(node)
    )


class SeedVF2ErrorMap(AnalysisPass):
    """Publish a deterministic ``vf2_avg_error_map`` so VF2PostLayout replays."""

    def __init__(self, coupling_map: CouplingMap) -> None:
        """Store the coupling map whose degrees seed the error map."""
        super().__init__()
        self._coupling_map = coupling_map

    def run(self, _dag: DAGCircuit) -> None:
        """Publish the deterministic degree-proxy ``vf2_avg_error_map``."""
        from qiskit.transpiler.passes.layout.vf2_utils import ErrorMap

        n = self._coupling_map.size()
        edges = sorted({tuple(sorted(e)) for e in self._coupling_map.get_edges()})
        degree = dict.fromkeys(range(n), 0)
        for a, b in edges:
            degree[a] += 1
            degree[b] += 1
        error_map = ErrorMap(n + 2 * len(edges))
        for q in range(n):
            error_map.add_error((q, q), degree[q] / n * 1e-3 + q * 1e-9)
        for a, b in edges:
            err = (degree[a] + degree[b]) / (2 * n) * 1e-2 + (a * n + b) * 1e-9
            error_map.add_error((a, b), err)
            error_map.add_error((b, a), err)
        self.property_set["vf2_avg_error_map"] = error_map


class CancelRailX(TransformationPass):
    """Cancel spurious ``rx(π)`` (X-on-rail) by propagating it as an X-frame."""

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Propagate ``rx(π)`` frames rightward and cancel matching pairs."""
        new = dag.copy_empty_like()
        frame: dict = {}

        def materialize(w: Qubit) -> None:
            if frame.get(w):
                new.apply_operation_back(XGate(), (w,))
                frame[w] = False

        for node in dag.topological_op_nodes():
            op, qa, name = node.op, node.qargs, node.op.name
            if name == "rx" and abs(float(op.params[0]) % (2 * np.pi) - np.pi) < 1e-9:
                frame[qa[0]] = not frame.get(qa[0], False)
                new.global_phase -= float(op.params[0]) / 2  # rx(θ≡π) = e^{-iθ/2} X
            elif name == "rz":
                th = float(op.params[0])
                new.apply_operation_back(
                    RZGate(-th if frame.get(qa[0]) else th), (qa[0],)
                )
            elif name == "crz":
                c, t = qa
                th, fc, ft = (
                    float(op.params[0]),
                    frame.get(c, False),
                    frame.get(t, False),
                )
                new.apply_operation_back(CRZGate(-th if fc ^ ft else th), (c, t))
                if fc:  # X on control leaves an Rz on the target
                    new.apply_operation_back(RZGate(th if not ft else -th), (t,))
            elif name == "swap":
                a, b = qa
                frame[a], frame[b] = frame.get(b, False), frame.get(a, False)
                new.apply_operation_back(SwapGate(), (a, b))
            else:  # prep x, rswap, measure, barrier: materialize then emit
                for w in qa:
                    materialize(w)
                new.apply_operation_back(op, qa, node.cargs)
        for w in list(frame):
            materialize(w)
        return new


def _physical_target(enc: type[QubitEncoding], coupling_map: CouplingMap) -> Target:
    """Build the physical-stage Target with Measure + control-flow ops registered opaquely."""
    target = Target.from_configuration(
        basis_gates=sorted(enc.PHYSICAL_ISA),
        custom_name_mapping=enc.custom_name_mapping(),
        coupling_map=coupling_map,
    )
    target.add_instruction(Measure(), name="measure")
    target.add_instruction(IfElseOp, name="if_else")
    target.add_instruction(WhileLoopOp, name="while_loop")
    target.add_instruction(ForLoopOp, name="for_loop")
    target.add_instruction(SwitchCaseOp, name="switch_case")
    return target


def physical_pm(
    coupling_map: CouplingMap,
    enc: type[QubitEncoding],
    *,
    seed: int = 42,
) -> StagedPassManager:
    """Preset O3 over the retained route.

    Built with ``routing_method="none"``: the lowering search already placed
    and routed, so the layout stage is empty and Qiskit's ``CheckMap`` certifies
    the route. The init stage of that preset omits ``ElidePermutations``, which
    would turn a committed rail exchange (a real beamsplitter SWAP) into a free
    virtual permutation.
    """
    preset = generate_preset_pass_manager(
        optimization_level=3,
        target=_physical_target(enc, coupling_map),
        seed_transpiler=seed,
        routing_method="none",
    )
    preset.layout = PassManager()
    preset.pre_routing = PassManager([SeedVF2ErrorMap(coupling_map)])
    preset.post_routing = PassManager([SwapBeforeMeasureToLayout()])
    # ``CancelRailX`` strips the X-on-rail that O3's 2Q resynthesis leaves behind.
    preset.post_optimization = PassManager(
        [CancelRailX(), RescheduleCommutingDiagonals(), RecordCircuitMetrics()]
    )
    return preset
