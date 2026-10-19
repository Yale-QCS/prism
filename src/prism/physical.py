"""Physical stage: the preset O3 pipeline over ``enc.PHYSICAL_ISA`` and prism's passes on it."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import TYPE_CHECKING

from qiskit.circuit import (
    Barrier,
    Instruction,
    Measure,
    ParameterExpression,
    QuantumCircuit,
)
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
from qiskit.transpiler.passes import (
    CommutativeOptimization,
    ConsolidateBlocks,
    RemoveBarriers,
    SabreSwap,
    Split2QUnitaries,
)
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit.transpiler.preset_passmanagers.common import generate_routing_passmanager

from prism.ir import DIAGONAL_GATES, commuting_predecessors, list_schedule
from prism.metrics import RecordCircuitMetrics, is_free

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    from qiskit.circuit import Clbit, Qubit
    from qiskit.transpiler import InstructionDurations

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


#: Operations that commute with a pending ``rz`` on their rails: they need not wait for it.
_FRAME_FREE = DIAGONAL_GATES | {
    "swap",
    "measure",
    "initialize",
    "pauli_product_measurement",
}


def _scheduled_duration(
    instructions: Iterable[tuple[Instruction, Sequence[Qubit], Sequence[Clbit]]],
    duration: Callable[[Instruction, Sequence[Qubit]], float],
) -> float:
    """The ASAP finish time of ``instructions``, with ``rz`` as a frame update.

    ``duration(op, qubits)`` is the caller's duration of each operation. An ``rz``,
    and an ``if_else`` whose bodies are diagonal, update the rail's phase frame:
    they hold no wire. The frame of an ``if_else`` is known ``duration(if_else)``
    (the feed-forward latency) after its clbits are written, and only the next
    operation on that content outside ``_FRAME_FREE`` (an ``rswap``) waits for it;
    a ``swap`` carries it and an ``initialize`` drops it. Another ``if_else``
    waits for its clbits plus that latency and runs its longest body.
    """
    ready: dict[Qubit | Clbit, float] = {}
    frame: dict[Qubit, float] = {}
    for op, qargs, cargs in instructions:
        if op.name == "rz":
            continue
        start = max((ready.get(w, 0) for w in (*qargs, *cargs)), default=0)
        if op.name == "if_else":
            known = max((ready.get(c, 0) for c in cargs), default=0)
            known += duration(op, qargs)
            if _is_diagonal(op):
                for q in qargs:
                    frame[q] = max(frame.get(q, 0), known)
                continue
            start = max([start, known, *(frame.pop(q) for q in qargs if q in frame)])
            length = max(
                _scheduled_duration(
                    (
                        (
                            ci.operation,
                            [qargs[body.find_bit(q).index] for q in ci.qubits],
                            [cargs[body.find_bit(c).index] for c in ci.clbits],
                        )
                        for ci in body.data
                    ),
                    duration,
                )
                for body in op.blocks
            )
        else:
            if op.name not in _FRAME_FREE:
                start = max([start, *(frame.pop(q) for q in qargs if q in frame)])
            elif op.name == "swap":
                a, b = qargs
                held = {b: frame.pop(a, None), a: frame.pop(b, None)}
                frame.update((q, t) for q, t in held.items() if t is not None)
            elif op.name == "initialize":
                for q in qargs:
                    frame.pop(q, None)
            length = duration(op, qargs)
        for w in (*qargs, *cargs):
            ready[w] = start + length
    return max(ready.values(), default=0)


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

    With ``durations`` (the caller's; an ``if_else`` entry is the feed-forward
    latency), a measurement moves only if the circuit's duration does not grow:
    from the last measurement to the first, each move is kept if the finish time
    of ``_scheduled_duration`` does not increase. Without, every measurement moves.

    Without durations ``prism_stages`` also runs it at the end of the logical
    stage, on logical qubits, so routing spends no SWAP on the gates it removes.
    """

    def __init__(self, durations: InstructionDurations | None = None) -> None:
        """Move every measurement, or with ``durations`` those that do not lengthen the circuit."""
        super().__init__()
        self.durations = durations

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Move the measurements in ``dag`` early and rewrite the gates they pass."""
        nodes = list(dag.topological_op_nodes())
        emitted, moved = _move_measurements(nodes, None)
        if not moved:
            return dag
        if self.durations is not None:
            emitted, moved = self._shortest(dag, nodes, moved)
            if not moved:
                return dag
        out = dag.copy_empty_like()
        for op, qargs, cargs in emitted:
            out.apply_operation_back(op, qargs, cargs)
        return out

    def _shortest(
        self, dag: DAGCircuit, nodes: list[DAGOpNode], movable: set[int]
    ) -> tuple[
        list[tuple[Instruction, tuple[Qubit, ...], tuple[Clbit, ...]]], set[int]
    ]:
        """Keep each move, last measurement first, if the duration does not grow."""
        durations = self.durations
        unit = (
            "dt" if durations.dt is None and durations.units_used() <= {"dt"} else "s"
        )
        cache: dict[tuple[str, tuple[int, ...]], float] = {}

        def duration(op: Instruction, qargs: Sequence[Qubit]) -> float:
            key = (op.name, tuple(dag.find_bit(q).index for q in qargs))
            if key not in cache:
                cache[key] = durations.get(op.name, list(key[1]), unit=unit)
            return cache[key]

        kept: set[int] = set()
        best, _ = _move_measurements(nodes, kept)
        best_time = _scheduled_duration(best, duration)
        for m in sorted(movable, reverse=True):
            trial, moved = _move_measurements(nodes, kept | {m})
            if (time := _scheduled_duration(trial, duration)) <= best_time:
                kept, best, best_time = moved, trial, time
        return best, kept


def _move_measurements(
    nodes: list[DAGOpNode], movable: set[int] | None
) -> tuple[list[tuple[Instruction, tuple[Qubit, ...], tuple[Clbit, ...]]], set[int]]:
    """``nodes`` with the measurements in ``movable`` (all if ``None``) moved early.

    Returns the instructions and the measurements that moved.
    """
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
            rewritten[k] = _classical_rz(node, {q: nodes[pending[q]] for q in measured})
            moved.update(pending[q] for q in measured)
        elif node.op.name == "swap":
            a, b = node.qargs
            held = {b: pending.pop(a, None), a: pending.pop(b, None)}
            pending.update((w, m) for w, m in held.items() if m is not None)
        else:
            blocked += [q for q in node.qargs if q in pending]
        for w in dict.fromkeys(blocked):
            reach[pending.pop(w)] = (k, w)
        if isinstance(node.op, Measure) and (movable is None or k in movable):
            pending[node.qargs[0]] = k
    reach.update((m, (-1, w)) for w, m in pending.items())

    after: dict[int, list[tuple[DAGOpNode, Qubit]]] = defaultdict(list)
    for m in moved:
        k, w = reach[m]
        after[k].append((nodes[m], w))
    out = [(m.op, (w,), m.cargs) for m, w in after.get(-1, ())]
    for k, node in enumerate(nodes):
        if k in rewritten:
            if (rz := rewritten[k]) is not None:
                op, q, bit = rz
                out.append((op, (q,), (bit,)))
        elif k not in moved:
            out.append((node.op, node.qargs, node.cargs))
        out.extend((m.op, (w,), m.cargs) for m, w in after.get(k, ()))
    return out, moved


class FenceErasureChecks(TransformationPass):
    """Put a ``Barrier`` on each side of every erasure check (``pauli_product_measurement``).

    The user places each check, so no gate may cross it. Qiskit's commutation
    checker finds that the ZZ check commutes with ``rz`` and ``crz``, so
    ``CommutativeOptimization`` would merge gates across it; a barrier commutes
    with nothing. The logical stage removes barriers, so ``RemoveBarriers``
    after the commutation passes removes only these.
    """

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Fence each check of ``dag`` on its qubits."""
        for node in dag.named_nodes("pauli_product_measurement"):
            block = DAGCircuit()
            block.add_qubits(node.qargs)
            block.add_clbits(node.cargs)
            fence = Barrier(len(node.qargs))
            block.apply_operation_back(fence, node.qargs)
            block.apply_operation_back(node.op, node.qargs, node.cargs)
            block.apply_operation_back(fence, node.qargs)
            dag.substitute_node_with_dag(node, block)
        return dag


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
    circuit in the order of ``list_schedule`` over the commutation-relaxed
    dependency graph. List scheduling is a heuristic: it usually shortens the
    circuit but does not guarantee it.
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


def _physical_target(
    enc: type[QubitEncoding],
    coupling_map: CouplingMap,
    durations: InstructionDurations | None = None,
) -> Target:
    """``enc.PHYSICAL_ISA`` on each qubit or edge, plus measure and ``if_else``.

    For dual rail that is ``rz`` on one rail and ``crz``, ``swap``, ``rswap``,
    ``initialize``, ``pauli_product_measurement`` on an edge: no gate leaves
    the code space, so stock O3 cannot produce one, and with no complete
    one-qubit basis it does not resynthesize. ``durations`` fill the
    ``InstructionProperties``; without them the Target has none.
    """
    target = Target.from_configuration(
        basis_gates=sorted(enc.PHYSICAL_ISA | {"measure"}),
        custom_name_mapping=enc.CUSTOM_GATES,
        coupling_map=coupling_map,
        instruction_durations=durations,
        dt=None if durations is None else durations.dt,
    )
    target.add_instruction(IfElseOp, name="if_else")
    return target


def physical_pm(
    coupling_map: CouplingMap,
    enc: type[QubitEncoding],
    *,
    seed: int = 42,
    durations: InstructionDurations | None = None,
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
    into classical control (with ``durations``, only where the duration does
    not grow), and ``DropMeasuredSwaps`` drops the SWAPs it leaves
    after both their rails are measured. ``RescheduleCommutingDiagonals`` then
    reorders the commuting diagonal gates for depth, and ``RecordCircuitMetrics``
    sets ``circuit_metrics``. ``FenceErasureChecks`` runs first and
    ``RemoveBarriers`` after the commutation passes, so no gate crosses an
    erasure check.

    The init stage leaves out ``ConsolidateBlocks`` and ``Split2QUnitaries``.
    Before layout, ``ConsolidateBlocks`` has no Target: it turns every block of
    more than 20 gates on two wires (a long ``rswap``/``rz`` run on one rail
    pair) into a ``UnitaryGate``. With only ``rz`` on one wire, no unitary
    synthesis reaches this Target, so ``UnitarySynthesis`` keeps the unitary
    and ``HighLevelSynthesis`` expands it by its definition to ``u``/``cx``,
    which the translation stage then cannot translate.

    ``durations`` are the caller's ``InstructionDurations``; prism assumes none.
    They fill the Target's ``InstructionProperties``, and ``EarlyMeasurement``
    also reads their ``if_else`` entry, the feed-forward latency.
    """
    target = _physical_target(enc, coupling_map, durations)
    preset = generate_preset_pass_manager(
        optimization_level=3,
        target=target,
        seed_transpiler=seed,
        layout_method="trivial",
        routing_method="none",
    )
    preset.pre_init = PassManager([FenceErasureChecks()])
    preset.init = PassManager(
        [
            p
            for p in preset.init.to_flow_controller().passes
            if not isinstance(p, (ConsolidateBlocks, Split2QUnitaries))
        ]
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
            RemoveBarriers(),
            EarlyMeasurement(durations),
            DropMeasuredSwaps(),
            RescheduleCommutingDiagonals(),
            RecordCircuitMetrics(),
        ]
    )
    return preset
