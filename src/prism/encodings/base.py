"""``QubitEncoding``: what prism needs from an encoding of logical qubits in physical wires.

A subclass sets the class attributes, defines ``initialize`` (a circuit on
``WIRES_PER_LOGICAL`` wires that prepares ``|0_L>``), and defines one classmethod
per name in ``LOGICAL_ISA`` that takes the logical operation and returns its
``MultiRealizationOp``. ``measure`` and ``if_else`` have rules here.
For an operation on ``m`` logical qubits, candidate qubit ``k * WIRES_PER_LOGICAL + w``
is wire ``w`` of the ``k``-th logical qubit.
"""

from __future__ import annotations

from typing import ClassVar

from qiskit.circuit import (
    Clbit,
    Instruction,
    Measure,
    QuantumCircuit,
    QuantumRegister,
)
from qiskit.circuit.controlflow import ControlFlowOp, IfElseOp
from qiskit.circuit.equivalence_library import SessionEquivalenceLibrary
from qiskit.transpiler import PassManager, TranspilerError

from prism.ir import MultiRealizationOp
from prism.logical import basic_logical_pm


class QubitEncoding:
    """Per-logical-qubit encoding into a block of ``WIRES_PER_LOGICAL`` physical wires."""

    WIRES_PER_LOGICAL: ClassVar[int]
    # Names the logical stage translates to; each needs a rule.
    LOGICAL_ISA: ClassVar[frozenset[str]]
    # Names the rules and ``initialize`` emit on wires.
    PHYSICAL_ISA: ClassVar[frozenset[str]]
    # The non-standard gates in ``PHYSICAL_ISA``, by name (Target.from_configuration's mapping).
    CUSTOM_GATES: ClassVar[dict[str, Instruction]] = {}

    @classmethod
    def logical_pm(cls) -> PassManager:
        """The logical stage: stock passes and the session equivalence library."""
        return basic_logical_pm(cls, eq_library=SessionEquivalenceLibrary)

    @classmethod
    def lower(
        cls, op: Instruction, clbits: tuple[Clbit, ...] = ()
    ) -> MultiRealizationOp:
        """The rule ``cls.<op.name>`` applied to ``op``; a control-flow rule also gets ``clbits``."""
        if op.name not in cls.LOGICAL_ISA:
            raise TranspilerError(
                f"{cls.__name__} does not support {op.name!r}; it lowers "
                f"{sorted(cls.LOGICAL_ISA)}."
            )
        rule = getattr(cls, op.name)
        return rule(op, clbits) if isinstance(op, ControlFlowOp) else rule(op)

    @classmethod
    def measure(cls, op: Instruction) -> MultiRealizationOp:
        """Measure every wire; wire ``w`` writes clbit ``w``."""
        n = op.num_qubits * cls.WIRES_PER_LOGICAL
        qc = QuantumCircuit(n, n)
        qc.measure(range(n), range(n))
        return MultiRealizationOp("measure", (qc,))

    @classmethod
    def if_else(cls, op: IfElseOp, clbits: tuple[Clbit, ...]) -> MultiRealizationOp:
        """An ``if_else`` on one logical qubit's wires, its blocks lowered rule by rule.

        The logical stage's ``SplitIfElse`` turns an ``if_else`` over several
        qubits into one per qubit, so that each is routed on its own rails.
        """
        if op.num_qubits > 1:
            raise TranspilerError(
                f"{cls.__name__} cannot lower an if_else over {op.num_qubits} "
                "qubits: it lowers one if_else per qubit, which needs every block "
                "instruction to act on one qubit and write no classical bit. Write "
                "one if_test per qubit, or move the instruction out of the block."
            )
        # The candidate's clbits bind positionally to the instruction's clbits.
        qc = QuantumCircuit(cls.WIRES_PER_LOGICAL)
        qc.add_bits(clbits)
        blocks = [cls._lower_block(b) for b in op.blocks]
        qc.append(IfElseOp(op.condition, *blocks), qc.qubits, clbits)
        return MultiRealizationOp("if_else", (qc,))

    @classmethod
    def _lower_block(cls, block: QuantumCircuit) -> QuantumCircuit:
        """``block`` on wires: each instruction replaced by its rule's only candidate."""
        regs = [
            QuantumRegister(cls.WIRES_PER_LOGICAL, f"q{i}")
            for i in range(block.num_qubits)
        ]
        out = QuantumCircuit(*regs, *block.cregs)
        out.add_bits([c for c in block.clbits if not block.find_bit(c).registers])
        for instr in block.data:
            if isinstance(instr.operation, Measure):
                raise TranspilerError(
                    f"{cls.__name__} cannot lower a measurement inside a control-flow "
                    "block: herald bits are allocated for top-level measurements only. "
                    "Move the measurement out of the block."
                )
            lowered = cls.lower(instr.operation, instr.clbits)
            if len(lowered.candidates) != 1:
                raise TranspilerError(
                    f"{cls.__name__} lowers {instr.operation.name!r} to several "
                    "realizations, which an if_else block cannot hold; move it out "
                    "of the block."
                )
            wires = [w for q in instr.qubits for w in regs[block.find_bit(q).index]]
            out.compose(lowered.candidates[0], wires, instr.clbits, inplace=True)
        return out
