"""Physical stage: the preset O3 pipeline over ``enc.PHYSICAL_ISA`` and prism's passes on it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from qiskit.circuit import Measure
from qiskit.circuit.controlflow import (
    ForLoopOp,
    IfElseOp,
    SwitchCaseOp,
    WhileLoopOp,
)
from qiskit.dagcircuit import DAGCircuit
from qiskit.transpiler import (
    CouplingMap,
    PassManager,
    StagedPassManager,
    Target,
    TransformationPass,
)
from qiskit.transpiler.passes import CommutativeOptimization, SabreSwap
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit.transpiler.preset_passmanagers.common import generate_routing_passmanager

from prism.ir import DIAGONAL_GATES, commuting_predecessors
from prism.metrics import RecordCircuitMetrics, is_free

if TYPE_CHECKING:
    from prism.encodings.base import QubitEncoding


class RescheduleCommutingDiagonals(TransformationPass):
    """Critical-path list scheduling over a dependency graph where diagonal gates commute.

    Routing emits gates in commit order. Physical diagonal gates on shared
    rails commute, so the emitted order is one of many; this pass re-emits the
    circuit by critical-path list scheduling over the commutation-relaxed
    dependency graph, which only shortens the circuit.
    """

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Re-emit ``dag`` in a depth-minimizing order that respects the relaxed dependencies."""
        nodes = list(dag.topological_op_nodes())
        n = len(nodes)
        preds = commuting_predecessors(
            [(*node.qargs, *node.cargs) for node in nodes],
            [node.op.name in DIAGONAL_GATES for node in nodes],
        )
        succs: list[list[int]] = [[] for _ in range(n)]
        for k, ps in enumerate(preds):
            for p in ps:
                succs[p].append(k)
        weight = [0 if is_free(node.op) else 1 for node in nodes]
        cp = [0] * n
        for k in range(n - 1, -1, -1):
            cp[k] = weight[k] + max((cp[s] for s in succs[k]), default=0)
        done: dict[int, int] = {}
        wire_free: dict = {}
        remaining = set(range(n))
        out = dag.copy_empty_like()
        while remaining:
            ready = [k for k in remaining if all(p in done for p in preds[k])]
            ready.sort(key=lambda k: (-cp[k], k))
            for k in ready:
                node = nodes[k]
                wires = list(node.qargs) + list(node.cargs)
                start = max(
                    [done[p] for p in preds[k]]
                    + [wire_free.get(w, 0) for w in wires]
                    + [0]
                )
                done[k] = start + weight[k]
                for w in wires:
                    wire_free[w] = done[k]
                remaining.discard(k)
            # emit this wave in start-time order so the linear order is a valid schedule
            for k in sorted(ready, key=lambda k: (done[k] - weight[k], k)):
                node = nodes[k]
                out.apply_operation_back(node.op, node.qargs, node.cargs)
        return out


def _physical_target(enc: type[QubitEncoding], coupling_map: CouplingMap) -> Target:
    """``enc.PHYSICAL_ISA`` on each qubit or edge, plus measure and control flow.

    For dual rail that is ``rz`` on one rail and ``crz``, ``swap``, ``rswap``,
    ``prep`` on an edge: no gate leaves the code space, so stock O3 cannot
    produce one, and with no complete one-qubit basis it does not resynthesize.
    """
    target = Target.from_configuration(
        basis_gates=sorted(enc.PHYSICAL_ISA),
        custom_name_mapping=enc.CUSTOM_GATES,
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

    Built with ``routing_method="none"``, whose init stage omits
    ``ElidePermutations``: that pass would turn a committed rail exchange (a
    real beamsplitter SWAP) into a free virtual permutation. The layout stage is
    empty, because ``PrismRouting`` placed the program; ``layout_method="trivial"``
    says so, which also leaves ``VF2PostLayout`` out of the optimization stage.
    The routing stage is O3's ``SabreSwap`` stage without ``VF2PostLayout``, so
    it keeps the layout: it routes only if ``CheckMap`` finds a gate off the
    device edges, i.e. in an operation that ``PrismRouting`` passed through.
    ``CommutativeOptimization`` merges the CRZ runs on an edge that O3 cannot
    resynthesize without a one-qubit basis.
    """
    target = _physical_target(enc, coupling_map)
    preset = generate_preset_pass_manager(
        optimization_level=3,
        target=target,
        seed_transpiler=seed,
        layout_method="trivial",
        routing_method="none",
    )
    preset.layout = PassManager()
    preset.routing = generate_routing_passmanager(
        SabreSwap(target, heuristic="decay", seed=seed, trials=20), target
    )
    preset.post_optimization = PassManager(
        [
            CommutativeOptimization(),
            RescheduleCommutingDiagonals(),
            RecordCircuitMetrics(),
        ]
    )
    return preset
