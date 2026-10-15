"""``QubitEncoding`` contract: per-logical-qubit map to a block of physical wires.

Each subclass declares ``WIRES_PER_LOGICAL`` + ``LOGICAL_ISA`` and provides one
classmethod per logical op, each returning a ``MultiRealizationOp``. The mathematical
content is an isometry ``V: H_logical → H_physical`` (one logical qubit per
``WIRES_PER_LOGICAL``-qubit block), with logical operations admitting one or
more physical realizations.

Local-qubit convention: for an op spanning ``m`` logical qubits, local qubit
``k * WIRES_PER_LOGICAL + w`` is wire ``w`` of the ``k``-th logical qubit.
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
from qiskit.transpiler import (
    CouplingMap,
    PassManager,
    StagedPassManager,
    TranspilerError,
)

from prism.ir import MultiRealizationOp
from prism.logical import CONTROL_FLOW_OPS, basic_logical_pm
from prism.physical import physical_pm as _physical_pm


class QubitEncoding:
    """Per-logical-qubit encoding into a block of physical wires."""

    WIRES_PER_LOGICAL: ClassVar[int]
    LOGICAL_ISA: ClassVar[frozenset[str]]
    # Gates the lowering stage can emit on physical wires. Subclasses set
    # this; usually equals ``LOGICAL_ISA`` filtered of measure/reset/
    # control-flow, plus any non-standard primitives the encoding's lowering
    # introduces (e.g. DR's ``rswap``).
    PHYSICAL_ISA: ClassVar[frozenset[str]]

    @classmethod
    def initialize(cls) -> QuantumCircuit:
        """Prep ``|0_L⟩`` on one logical qubit's wires; ``WIRES_PER_LOGICAL`` qubits."""
        raise NotImplementedError(f"{cls.__name__}.initialize not implemented")

    @classmethod
    def logical_pm(cls) -> PassManager:
        """Pre-lower the input to ``cls.LOGICAL_ISA``. Default: standard cleanup + session equiv-lib translation."""
        return basic_logical_pm(cls, eq_library=SessionEquivalenceLibrary)

    @classmethod
    def custom_name_mapping(cls) -> dict:
        """Custom gate name → class for non-standard primitives in ``PHYSICAL_ISA``. Default: empty."""
        return {}

    @classmethod
    def physical_pm(
        cls, coupling_map: CouplingMap, *, seed: int = 42
    ) -> StagedPassManager:
        """Compile the retained route over ``cls.PHYSICAL_ISA``."""
        return _physical_pm(coupling_map, cls, seed=seed)

    @classmethod
    def lower(
        cls, op: Instruction, clbits: tuple[Clbit, ...] = ()
    ) -> MultiRealizationOp:
        """Dispatch to ``cls.<op.name>``. ``clbits`` is forwarded only for ``ControlFlowOp``."""
        name = op.name
        if isinstance(op, ControlFlowOp) and name not in cls.LOGICAL_ISA:
            supported = sorted(cls.LOGICAL_ISA & CONTROL_FLOW_OPS) or "none"
            raise TranspilerError(
                f"{cls.__name__} does not support {name!r}; supported control "
                f"flow: {supported}. Unroll or remove the {name!r} first."
            )
        if name not in cls.LOGICAL_ISA:
            raise TranspilerError(
                f"Op {name!r} not in {cls.__name__}'s LOGICAL_ISA "
                f"{sorted(cls.LOGICAL_ISA)}; transpile to the logical basis first."
            )
        rule = getattr(cls, name, None)
        if rule is None:
            raise ValueError(
                f"{cls.__name__} declares {name!r} in LOGICAL_ISA but has no "
                f"classmethod named {name!r}."
            )
        if isinstance(op, ControlFlowOp):
            return rule(op, clbits)
        return rule(op)

    # ---- Generic plumbing rules (defaults; subclasses override if needed) -----

    @classmethod
    def measure(cls, op: Instruction) -> MultiRealizationOp:
        """Per-wire Z-basis measurement; ``num_clbits = num_qubits`` (bound at apply)."""
        n_wires = op.num_qubits * cls.WIRES_PER_LOGICAL
        qc = QuantumCircuit(n_wires, n_wires)
        for w in range(n_wires):
            qc.measure(w, w)
        return MultiRealizationOp("measure", (qc,))

    @classmethod
    def if_else(cls, op: IfElseOp, clbits: tuple[Clbit, ...]) -> MultiRealizationOp:
        """A wire-level ``IfElseOp`` on one logical qubit's rails, over recursively-lowered blocks.

        Blocks must lower to fixed ops. The logical stage's ``SplitIfElse`` turns
        an ``if_else`` over several qubits into one per qubit, so that each is
        routed on its own rails.
        """
        if op.num_qubits > 1:
            raise TranspilerError(
                f"{cls.__name__} cannot lower an if_else over {op.num_qubits} "
                "qubits: it lowers one if_else per qubit, which needs every block "
                "instruction to act on one qubit and write no classical bit. Write "
                "one if_test per qubit, or move the instruction out of the block."
            )
        qc = QuantumCircuit(cls.WIRES_PER_LOGICAL)
        # The exact clbits the op references, as loose bits: candidate clbits
        # bind positionally to the instruction's clbits, so the widths match.
        qc.add_bits(clbits)
        blocks = [cls._lower_block(b) for b in op.blocks]
        qc.append(IfElseOp(op.condition, *blocks), qc.qubits, clbits)
        return MultiRealizationOp("if_else", (qc,))

    @classmethod
    def _lower_block(cls, block: QuantumCircuit) -> QuantumCircuit:
        """Recursively lower a control-flow block; rejects multi-realization ops."""
        block_regs = [
            QuantumRegister(cls.WIRES_PER_LOGICAL, f"q{i}")
            for i in range(block.num_qubits)
        ]
        new_block = QuantumCircuit(*block_regs)
        for cr in block.cregs:
            new_block.add_register(cr)
        covered = {c for cr in block.cregs for c in cr}
        loose = [c for c in block.clbits if c not in covered]
        if loose:
            new_block.add_bits(loose)

        block_q_to_logical = {q: i for i, q in enumerate(block.qubits)}
        for instr in block.data:
            if isinstance(instr.operation, Measure):
                raise TranspilerError(
                    f"{cls.__name__} cannot lower a measurement inside a control-flow "
                    "block: herald bits are allocated for top-level measurements only. "
                    "Move the measurement out of the block."
                )
            logical_qubits = tuple(block_q_to_logical[q] for q in instr.qubits)
            lowered = cls.lower(instr.operation, tuple(instr.clbits))
            if len(lowered.candidates) != 1:
                raise TranspilerError(
                    f"Op {instr.operation.name!r} inside a control-flow block "
                    f"lowered to a multi-realization. Conditional 2Q gates aren't "
                    f"supported by the default if_else rule; move the op out of "
                    f"the block or override if_else in your encoding."
                )
            sub_qc = lowered.candidates[0]
            wire_map = [
                block_regs[logical_qubits[k]][w]
                for k in range(len(logical_qubits))
                for w in range(cls.WIRES_PER_LOGICAL)
            ]
            for sub_ci in sub_qc.data:
                local_indices = [sub_qc.find_bit(q).index for q in sub_ci.qubits]
                new_qubits = [wire_map[idx] for idx in local_indices]
                new_block.append(sub_ci.operation, new_qubits, sub_ci.clbits)
        return new_block
