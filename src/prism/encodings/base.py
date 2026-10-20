"""``QubitEncoding``: logical qubits encoded in blocks of physical wires.

A subclass sets the class attributes, defines ``initialize`` (a circuit on
``WIRES_PER_LOGICAL`` wires preparing ``|0_L>``), and defines one classmethod per
name in ``LOGICAL_ISA`` that maps the logical operation to a ``MultiRealizationOp``.
In a candidate, wire ``WIRES_PER_LOGICAL * k + w`` is wire ``w`` of the op's
``k``-th qubit.
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
    """An encoding of each logical qubit in ``WIRES_PER_LOGICAL`` physical wires."""

    WIRES_PER_LOGICAL: ClassVar[int]
    #: What the logical stage translates to; each name needs a rule.
    LOGICAL_ISA: ClassVar[frozenset[str]]
    #: What the rules and ``initialize`` emit.
    PHYSICAL_ISA: ClassVar[frozenset[str]]
    #: The non-standard gates of ``PHYSICAL_ISA``, for ``Target.from_configuration``.
    CUSTOM_GATES: ClassVar[dict[str, Instruction]] = {}

    @classmethod
    def logical_pm(cls) -> PassManager:
        return basic_logical_pm(cls, eq_library=SessionEquivalenceLibrary)

    @classmethod
    def lower(
        cls, op: Instruction, clbits: tuple[Clbit, ...] = ()
    ) -> MultiRealizationOp:
        """Apply the rule named ``op.name``; a control-flow rule also gets ``clbits``."""
        if op.name not in cls.LOGICAL_ISA:
            raise TranspilerError(f"{cls.__name__} does not support {op.name!r}")
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
        """An ``if_else`` on one qubit's wires, its blocks lowered rule by rule."""
        if op.num_qubits > 1:
            raise TranspilerError(
                f"{cls.__name__} lowers one if_else per qubit: every block instruction "
                "must act on one qubit and write no clbit"
            )
        qc = QuantumCircuit(cls.WIRES_PER_LOGICAL)
        qc.add_bits(clbits)
        blocks = [cls._lower_block(b) for b in op.blocks]
        qc.append(IfElseOp(op.condition, *blocks), qc.qubits, clbits)
        return MultiRealizationOp("if_else", (qc,))

    @classmethod
    def _lower_block(cls, block: QuantumCircuit) -> QuantumCircuit:
        regs = [
            QuantumRegister(cls.WIRES_PER_LOGICAL, f"q{i}")
            for i in range(block.num_qubits)
        ]
        out = QuantumCircuit(*regs, *block.cregs)
        out.add_bits([c for c in block.clbits if not block.find_bit(c).registers])
        for instr in block.data:
            if isinstance(instr.operation, Measure):
                raise TranspilerError(
                    f"{cls.__name__} does not support a measurement inside a control-flow block"
                )
            lowered = cls.lower(instr.operation, instr.clbits)
            if len(lowered.candidates) != 1:
                raise TranspilerError(
                    f"{cls.__name__} cannot put {instr.operation.name!r}, which has "
                    "several realizations, in an if_else block"
                )
            wires = [w for q in instr.qubits for w in regs[block.find_bit(q).index]]
            out.compose(lowered.candidates[0], wires, instr.clbits, inplace=True)
        return out
