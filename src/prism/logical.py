"""Logical stage: input circuit to ``enc.LOGICAL_ISA``."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

import numpy as np
from qiskit.circuit import (
    AncillaRegister,
    Gate,
    IfElseOp,
    Measure,
    QuantumCircuit,
    Qubit,
)
from qiskit.circuit.controlflow import CONTROL_FLOW_OP_NAMES
from qiskit.circuit.library import MCPhaseGate, MCXGate
from qiskit.converters import circuit_to_dag
from qiskit.dagcircuit import DAGCircuit, DAGOpNode
from qiskit.passmanager import DoWhileController
from qiskit.transpiler import PassManager, TransformationPass
from qiskit.transpiler.passes import (
    BasisTranslator,
    Decompose,
    ElidePermutations,
    FixedPoint,
    HighLevelSynthesis,
    HLSConfig,
    Optimize1qGatesDecomposition,
    RemoveBarriers,
    RemoveDiagonalGatesBeforeMeasure,
    Size,
    Unroll3qOrMore,
)

if TYPE_CHECKING:
    from qiskit.circuit import Clbit, EquivalenceLibrary
    from qiskit.transpiler import BasePass

    from prism.encodings.base import QubitEncoding


NON_GATE_ISA_NAMES: frozenset[str] = CONTROL_FLOW_OP_NAMES | {
    "measure",
    "reset",
    "erasure_check",
}


def basic_logical_pm(
    enc: type[QubitEncoding],
    *,
    eq_library: EquivalenceLibrary,
    reshape_passes: tuple[BasePass, ...] = (),
) -> PassManager:
    """Standard cleanup, translate to ``enc.LOGICAL_ISA``, split ``if_else`` per qubit, elide SWAPs, fold constant qubits, drop diagonals before measures, measure early."""
    isa_basis = sorted(enc.LOGICAL_ISA - NON_GATE_ISA_NAMES)
    return PassManager(
        [
            RemoveBarriers(),
            MCPrepare(),
            # High-level gates (QFT, MCMT, ...) by their default plugins; mcx
            # with one clean ancilla.
            HighLevelSynthesis(hls_config=HLSConfig(mcx=["1_clean_kg24"])),
            Decompose(["c-unitary", "unitary"]),
            # Unroll every 3+-qubit gate but CCX (the equivalence library has CCX).
            Unroll3qOrMore(basis_gates=["ccx"]),
            *reshape_passes,
            BasisTranslator(
                eq_library, sorted(enc.LOGICAL_ISA | CONTROL_FLOW_OP_NAMES)
            ),
            SplitIfElse(),
            # Before layout a SWAP only relabels logical qubits.
            ElideLogicalPermutations(),
            FoldConstantQubits(),
            # After the fold, which joins the 1q runs around each removed crz.
            Optimize1qGatesDecomposition(basis=isa_basis),
            # A diagonal gate right before a final measurement does not change its
            # outcome; removing it here keeps routing from spending SWAPs on it. One
            # sweep can expose another (rz after crz), hence the fixed point.
            DoWhileController(
                [
                    RemoveDiagonalGatesBeforeMeasure(),
                    Size(recurse=True),
                    FixedPoint("size"),
                ],
                do_while=lambda property_set: not property_set["size_fixed_point"],
            ),
            EarlyMeasurement(),
        ]
    )


class MCPrepare(TransformationPass):
    """Prepare multi-controlled gates for ``HighLevelSynthesis`` with ``mcx=["1_clean_kg24"]``.

    Rewrites ``mcphase(pi)`` with 4+ controls as ``H_t . mcx . H_t`` (``mcphase``
    has no synthesis plugin). If an ``mcx`` remains and no qubit is idle, adds one
    clean ancilla qubit (register ``mcd_anc``) for the synthesis to share.
    """

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Rewrite ``mcphase(pi)`` and add the ancilla if needed."""
        for node in dag.op_nodes(MCPhaseGate):
            n = node.op.num_ctrl_qubits
            if n >= 4 and _is_pi(float(node.op.params[0])):
                sub = QuantumCircuit(n + 1)
                sub.h(n)
                sub.append(MCXGate(n, ctrl_state=node.op.ctrl_state), range(n + 1))
                sub.h(n)
                dag.substitute_node_with_dag(node, circuit_to_dag(sub))
        if "mcx" in dag.count_ops() and not any(
            isinstance(w, Qubit) for w in dag.idle_wires()
        ):
            dag.add_qreg(AncillaRegister(1, name="mcd_anc"))
        return dag


def _is_pi(theta: float) -> bool:
    """``theta`` is ``pi`` modulo ``2 pi``."""
    return abs(abs((theta + np.pi) % (2 * np.pi) - np.pi) - np.pi) <= 1e-9


class FoldConstantQubits(TransformationPass):
    """Fold ``rz`` and ``crz`` on qubits in a known computational basis state.

    A qubit is known from the start (``|0>``) or a ``reset``, flips on ``x``, and
    stays known through ``rz`` and ``crz`` (diagonal) until any other operation.
    On a known qubit ``rz`` is a global phase. A ``crz`` with a known control is
    ``rz`` on the target or nothing; with a known target it is an ``rz`` on the
    control and a global phase.
    """

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Fold every ``rz`` and ``crz`` that touches a known qubit."""
        known = dict.fromkeys(dag.qubits, 0)
        for node in list(dag.topological_op_nodes()):
            bits = [known.get(q) for q in node.qargs]
            if node.name == "x" and bits != [None]:
                known[node.qargs[0]] ^= 1
            elif node.name == "reset":
                known[node.qargs[0]] = 0
            elif node.name in ("rz", "crz") and bits != [None] * len(bits):
                dag.substitute_node_with_dag(node, circuit_to_dag(_fold(node.op, bits)))
            else:
                for q in node.qargs:
                    known.pop(q, None)
        return dag


def _fold(op: Gate, bits: list[int | None]) -> QuantumCircuit:
    """``rz`` or ``crz`` ``op`` with its known qubits (``bits``, ``None`` if unknown) fixed."""
    (theta,) = op.params
    *ctrl, t = bits
    qc = QuantumCircuit(len(bits))
    if ctrl == [None]:  # crz with known target: diag(1, e^{-+i theta/2}) on the control
        sign = 2 * t - 1
        qc.global_phase = sign * theta / 4
        qc.rz(sign * theta / 2, 0)
    elif ctrl != [0] and t is None:
        qc.rz(theta, len(bits) - 1)
    elif ctrl != [0]:
        qc.global_phase = (2 * t - 1) * theta / 2
    return qc


class ElideLogicalPermutations(ElidePermutations):
    """``ElidePermutations`` that also records ``logical_output_permutation`` in the property set."""

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Remove logical permutation operations and record their net effect."""
        out_dag = super().run(dag)
        virtual_layout = self.property_set["virtual_permutation_layout"]
        self.property_set["logical_output_permutation"] = (
            tuple(range(len(out_dag.qubits)))
            if virtual_layout is None
            else tuple(virtual_layout[q] for q in out_dag.qubits)
        )
        return out_dag


class SplitIfElse(TransformationPass):
    """Replace an ``if_else`` over several qubits by one ``if_else`` per qubit.

    Exact when every block instruction acts on one qubit and writes no classical
    bit: the per-qubit branches then commute and read the same condition. Other
    ``if_else`` operations are left alone.
    """

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Split every splittable multi-qubit ``if_else`` in ``dag``."""
        for node in dag.op_nodes(IfElseOp):
            op = node.op
            if op.num_qubits < 2 or not _splittable(op):
                continue
            split = DAGCircuit()
            split.add_qubits(node.qargs)
            split.add_clbits(node.cargs)
            for i, qubit in enumerate(node.qargs):
                blocks = [_restrict(block, i) for block in op.blocks]
                split.apply_operation_back(
                    IfElseOp(op.condition, *blocks), (qubit,), node.cargs, check=False
                )
            dag.substitute_node_with_dag(node, split)
        return dag


def _splittable(op: IfElseOp) -> bool:
    """Every block instruction of ``op`` acts on one qubit and writes no classical bit."""
    return all(
        instr.operation.num_qubits == 1 and not instr.clbits
        for block in op.blocks
        for instr in block.data
    )


def _restrict(block: QuantumCircuit, i: int) -> QuantumCircuit:
    """``block`` with only qubit ``i`` and the instructions on it; classical bits kept."""
    sub = QuantumCircuit([block.qubits[i]], *block.cregs)
    sub.add_bits([c for c in block.clbits if not block.find_bit(c).registers])
    for instr in block.data:
        if instr.qubits == (block.qubits[i],):
            sub.append(instr)
    return sub


class EarlyMeasurement(TransformationPass):
    """Measure each qubit before its diagonal tail, which becomes classical control.

    A Z measurement commutes with ``rz`` and ``crz`` on its qubit (Rovara,
    Burgholzer and Wille, arXiv:2511.22712), so a measurement with a diagonal
    gate behind it moves to just after the last other operation on its qubit or
    its clbit. The qubit is then in a known basis state: an ``rz`` on it is a
    phase and goes, a ``crz`` it controls becomes ``rz`` on the target if its bit
    is 1, a ``crz`` it is the target of becomes ``rz(±θ/2)`` on the control, and
    a ``crz`` between two measured qubits goes. The phases dropped are global
    within each measurement branch. Routing then spends no SWAP on these gates.
    """

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Move the measurements in ``dag`` early and rewrite the gates they pass."""
        nodes = list(dag.topological_op_nodes())
        pending: dict[Qubit, int] = {}  # qubit -> the measurement that reads it later
        reach: dict[int, int] = {}  # measurement -> the op it follows (-1: the start)
        rewritten: dict[int, tuple[IfElseOp, Qubit, Clbit] | None] = {}
        moved: set[int] = set()
        for k in range(len(nodes) - 1, -1, -1):
            node = nodes[k]
            blocked = [q for q, m in pending.items() if nodes[m].cargs[0] in node.cargs]
            if node.name in ("rz", "crz") and (
                measured := [q for q in node.qargs if q in pending]
            ):
                rewritten[k] = _classical_rz(
                    node, {q: nodes[pending[q]] for q in measured}
                )
                moved.update(pending[q] for q in measured)
            else:
                blocked += [q for q in node.qargs if q in pending]
            for q in dict.fromkeys(blocked):
                reach[pending.pop(q)] = k
            if isinstance(node.op, Measure):
                pending[node.qargs[0]] = k
        if not moved:
            return dag
        reach.update((m, -1) for m in pending.values())
        after: dict[int, list[DAGOpNode]] = defaultdict(list)
        for m in moved:
            after[reach[m]].append(nodes[m])
        out = dag.copy_empty_like()
        for m in after[-1]:
            out.apply_operation_back(m.op, m.qargs, m.cargs)
        for k, node in enumerate(nodes):
            if k in rewritten:
                if (rz := rewritten[k]) is not None:
                    op, q, bit = rz
                    out.apply_operation_back(op, (q,), (bit,))
            elif k not in moved:
                out.apply_operation_back(node.op, node.qargs, node.cargs)
            for m in after[k]:
                out.apply_operation_back(m.op, m.qargs, m.cargs)
        return out


def _classical_rz(
    node: DAGOpNode, measured: dict[Qubit, DAGOpNode]
) -> tuple[IfElseOp, Qubit, Clbit] | None:
    """The ``crz`` in ``node`` with one qubit measured, as an ``rz`` conditioned on its bit.

    ``measured`` maps each measured qubit of ``node`` to its measurement. ``None``
    for an ``rz`` or a ``crz`` with both qubits measured: a phase.
    """
    if len(measured) == len(node.qargs):
        return None
    (theta,) = node.op.params
    control, target = node.qargs
    if control in measured:
        qubit, bit, angles = target, measured[control].cargs[0], (theta,)
    else:
        qubit, bit, angles = control, measured[target].cargs[0], (theta / 2, -theta / 2)
    blocks = []
    for angle in angles:
        block = QuantumCircuit([qubit], [bit])
        block.rz(angle, qubit)
        blocks.append(block)
    return IfElseOp((bit, True), *blocks), qubit, bit
