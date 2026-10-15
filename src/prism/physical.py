"""Physical stage: the preset O3 pipeline over ``enc.PHYSICAL_ISA`` and prism's passes on it."""

from __future__ import annotations

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
from qiskit.dagcircuit import DAGCircuit
from qiskit.transpiler import (
    AnalysisPass,
    CouplingMap,
    PassManager,
    StagedPassManager,
    Target,
    TransformationPass,
)
from qiskit.transpiler.passes.layout.vf2_utils import ErrorMap
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

from prism.metrics import (
    RecordCircuitMetrics,
)
from prism.synthesis.reschedule import RescheduleCommutingDiagonals

if TYPE_CHECKING:
    from qiskit.circuit import Qubit

    from prism.encodings.base import QubitEncoding


class SeedVF2ErrorMap(AnalysisPass):
    """Publish a deterministic ``vf2_avg_error_map`` so VF2PostLayout replays."""

    def __init__(self, coupling_map: CouplingMap) -> None:
        """Store the coupling map whose degrees seed the error map."""
        super().__init__()
        self._coupling_map = coupling_map

    def run(self, _dag: DAGCircuit) -> None:
        """Publish the deterministic degree-proxy ``vf2_avg_error_map``."""
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

    Built with ``routing_method="none"``: the routing stage already placed
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
    # ``CancelRailX`` strips the X-on-rail that O3's 2Q resynthesis leaves behind.
    preset.post_optimization = PassManager(
        [CancelRailX(), RescheduleCommutingDiagonals(), RecordCircuitMetrics()]
    )
    return preset
