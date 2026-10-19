"""Physical stage: the preset O3 pipeline over ``enc.PHYSICAL_ISA`` and prism's passes on it."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import TYPE_CHECKING

from qiskit.circuit import Instruction, Measure, ParameterExpression, QuantumCircuit
from qiskit.circuit.controlflow import IfElseOp
from qiskit.circuit.library import CRZGate, RZGate
from qiskit.dagcircuit import DAGCircuit, DAGOpNode, DAGOutNode
from qiskit.passmanager import ConditionalController
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

from prism.ir import DIAGONAL_GATES, commuting_predecessors, list_schedule
from prism.metrics import RecordCircuitMetrics, is_free

if TYPE_CHECKING:
    from qiskit.circuit import Clbit, Qubit

    from prism.encodings.base import QubitEncoding


def _classical_rz(
    node: DAGOpNode, measured: dict[Qubit, DAGOpNode]
) -> tuple[IfElseOp, Qubit, Clbit] | None:
    """The ``crz`` in ``node`` with one rail measured, as an ``rz`` conditioned on its bit.

    ``measured`` maps each measured rail of ``node`` to its measurement. ``None``
    for an ``rz`` or a ``crz`` with both rails measured: a phase.
    """
    if len(measured) == len(node.qargs):
        return None
    (theta,) = node.op.params
    control, target = node.qargs
    if control in measured:
        rail, bit, angles = target, measured[control].cargs[0], (theta,)
    else:
        rail, bit, angles = control, measured[target].cargs[0], (theta / 2, -theta / 2)
    blocks = []
    for angle in angles:
        block = QuantumCircuit([rail], [bit])
        block.rz(angle, rail)
        blocks.append(block)
    return IfElseOp((bit, True), *blocks), rail, bit


class EarlyMeasurement(TransformationPass):
    """Measure each rail before its diagonal tail, which becomes classical control.

    A Z measurement commutes with ``rz`` and ``crz`` on its wire and follows the
    wire's content back through a ``swap`` (Rovara, Burgholzer and Wille,
    arXiv:2511.22712). A measurement with a diagonal gate behind it moves to just
    after the last other operation on that content, or on its clbit. The rail is
    then in a Fock state with a known photon number: an ``rz`` on it is a phase
    and goes, a ``crz`` it controls becomes ``rz`` on the target if its bit is 1,
    a ``crz`` it is the target of becomes ``rz(±θ/2)`` on the control, and a
    ``crz`` between two measured rails goes. The phases dropped are global within
    each measurement branch.
    """

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Move the measurements in ``dag`` early and rewrite the gates they pass."""
        nodes = list(dag.topological_op_nodes())
        # wire -> the measurement that reads the content the wire holds here
        pending: dict[Qubit, int] = {}
        # measurement -> the operation it can follow (-1: the start) and its wire there
        reach: dict[int, tuple[int, Qubit]] = {}
        rewritten: dict[int, tuple[IfElseOp, Qubit, Clbit] | None] = {}
        moved: set[int] = set()
        for k in range(len(nodes) - 1, -1, -1):
            node = nodes[k]
            blocked = [w for w, m in pending.items() if nodes[m].cargs[0] in node.cargs]
            if node.op.name in ("rz", "crz") and (
                measured := [q for q in node.qargs if q in pending]
            ):
                rewritten[k] = _classical_rz(
                    node, {q: nodes[pending[q]] for q in measured}
                )
                moved.update(pending[q] for q in measured)
            elif node.op.name == "swap":
                a, b = node.qargs
                held = {b: pending.pop(a, None), a: pending.pop(b, None)}
                pending.update((w, m) for w, m in held.items() if m is not None)
            else:
                blocked += [q for q in node.qargs if q in pending]
            for w in dict.fromkeys(blocked):
                reach[pending.pop(w)] = (k, w)
            if isinstance(node.op, Measure):
                pending[node.qargs[0]] = k
        if not rewritten:
            return dag
        reach.update((m, (-1, w)) for w, m in pending.items())

        after: dict[int, list[tuple[DAGOpNode, Qubit]]] = defaultdict(list)
        for m in moved:
            k, w = reach[m]
            after[k].append((nodes[m], w))
        out = dag.copy_empty_like()

        def measure_after(k: int) -> None:
            for m, w in after.get(k, ()):
                out.apply_operation_back(m.op, (w,), m.cargs)

        measure_after(-1)
        for k, node in enumerate(nodes):
            if k in rewritten:
                if (rz := rewritten[k]) is not None:
                    op, q, bit = rz
                    out.apply_operation_back(op, (q,), (bit,))
            elif k not in moved:
                out.apply_operation_back(node.op, node.qargs, node.cargs)
            measure_after(k)
        return out


class DropMeasuredSwaps(TransformationPass):
    """Drop each ``swap`` that ends both its wires right after both were measured.

    A measured rail holds a known Fock state that nothing reads afterwards, so
    exchanging two of them changes no outcome. As in Qiskit's
    ``OptimizeSwapBeforeMeasure``, the final layout is left as it is.
    ``EarlyMeasurement`` leaves these behind: it moves measurements ahead of the
    routing SWAPs that followed the diagonal gates it removed.
    """

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Remove the trailing measured ``swap`` gates of ``dag``, last first."""
        for node in reversed(list(dag.topological_op_nodes())):
            if node.op.name != "swap":
                continue
            preds = list(dag.predecessors(node))
            if (
                all(isinstance(s, DAGOutNode) for s in dag.successors(node))
                and all(
                    isinstance(p, DAGOpNode) and isinstance(p.op, Measure)
                    for p in preds
                )
                and {q for p in preds for q in p.qargs} >= set(node.qargs)
            ):
                dag.remove_op_node(node)
        return dag


def _is_diagonal(operation: Instruction) -> bool:
    """A diagonal gate, or control flow whose bodies are diagonal: reading a clbit commutes."""
    if operation.name in DIAGONAL_GATES:
        return True
    blocks = getattr(operation, "blocks", None)
    return blocks is not None and all(
        _is_diagonal(instr.operation) for block in blocks for instr in block.data
    )


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
        wires = [(*node.qargs, *node.cargs) for node in nodes]
        preds = commuting_predecessors(wires, [_is_diagonal(node.op) for node in nodes])
        weight = [0 if is_free(node.op) else 1 for node in nodes]
        out = dag.copy_empty_like()
        for k in list_schedule(preds, wires, weight):
            out.apply_operation_back(nodes[k].op, nodes[k].qargs, nodes[k].cargs)
        return out


class FoldCRZAngles(TransformationPass):
    """Fold each ``crz`` angle into ``[0, 2π)``, the phase an SWS gate waits for.

    The SWS conditional phase builds up while the photon waits in the coupler,
    with one sign, so ``crz(θ)`` waits for ``θ mod 2π``. Since ``crz(θ + 2π)``
    is ``crz(θ)`` times ``Z = i·rz(π)`` on the control, each angle folds into
    that range with at most one free ``rz(π)``, and ``crz(2πk)`` is no SWS at all.
    """

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Replace each bound ``crz`` angle outside ``[0, 2π)``."""
        for node in dag.named_nodes("crz"):
            theta = node.op.params[0]
            if isinstance(theta, ParameterExpression):
                continue
            turns, folded = divmod(theta, 2 * math.pi)
            if math.isclose(folded, 2 * math.pi):
                turns, folded = turns + 1, 0.0
            if folded == theta:
                continue
            block = DAGCircuit()
            block.add_qubits(node.qargs)
            if folded:
                block.apply_operation_back(CRZGate(folded), node.qargs)
            if turns % 2:
                block.apply_operation_back(RZGate(math.pi), node.qargs[:1])
                block.global_phase = math.pi / 2
            dag.substitute_node_with_dag(node, block)
        return dag


def _physical_target(enc: type[QubitEncoding], coupling_map: CouplingMap) -> Target:
    """``enc.PHYSICAL_ISA`` on each qubit or edge, plus measure and ``if_else``.

    For dual rail that is ``rz`` on one rail and ``crz``, ``swap``, ``rswap``,
    ``initialize``, ``pauli_product_measurement`` on an edge: no gate leaves
    the code space, so stock O3 cannot produce one, and with no complete
    one-qubit basis it does not resynthesize.
    """
    target = Target.from_configuration(
        basis_gates=sorted(enc.PHYSICAL_ISA),
        custom_name_mapping=enc.CUSTOM_GATES,
        coupling_map=coupling_map,
    )
    target.add_instruction(Measure(), name="measure")
    target.add_instruction(IfElseOp, name="if_else")
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
    real beamsplitter SWAP) into a free virtual permutation. The layout stage
    runs only on a program no ``multi_realization`` pass placed, as the stock
    trivial layout; ``layout_method="trivial"`` also leaves ``VF2PostLayout`` out
    of the optimization stage. The routing stage is O3's ``SabreSwap`` stage
    without ``VF2PostLayout``, so it keeps the layout: it routes only if
    ``CheckMap`` finds a gate off the device edges, i.e. in an unplaced program
    or an operation that ``PrismRouting`` passed through.
    ``CommutativeOptimization`` merges the CRZ runs on an edge that O3 cannot
    resynthesize without a one-qubit basis. ``FoldCRZAngles`` then folds each
    merged angle to its SWS wait, and a second ``CommutativeOptimization``
    merges the ``rz(π)`` that adds into the control's other ``rz``.
    ``EarlyMeasurement`` then turns the diagonal gates behind each measurement
    into classical control, and ``DropMeasuredSwaps`` drops the SWAPs it leaves
    after both their rails are measured.
    """
    target = _physical_target(enc, coupling_map)
    preset = generate_preset_pass_manager(
        optimization_level=3,
        target=target,
        seed_transpiler=seed,
        layout_method="trivial",
        routing_method="none",
    )
    preset.layout = PassManager(
        ConditionalController(
            preset.layout.to_flow_controller(),
            condition=lambda ps: ps["layout"] is None,
        )
    )
    preset.routing = generate_routing_passmanager(
        SabreSwap(target, heuristic="decay", seed=seed, trials=20), target
    )
    preset.post_optimization = PassManager(
        [
            CommutativeOptimization(),
            FoldCRZAngles(),
            CommutativeOptimization(),
            EarlyMeasurement(),
            DropMeasuredSwaps(),
            RescheduleCommutingDiagonals(),
            RecordCircuitMetrics(),
        ]
    )
    return preset
