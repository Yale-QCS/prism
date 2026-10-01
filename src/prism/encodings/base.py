"""``QubitEncoding`` contract: per-logical-qubit map to a block of physical wires.

Each subclass declares ``WIRES_PER_LOGICAL`` + ``LOGICAL_ISA`` and provides one
classmethod per logical op, each returning a ``LoweredOp``. The mathematical
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
    QuantumCircuit,
    QuantumRegister,
)
from qiskit.circuit.controlflow import ControlFlowOp, IfElseOp
from qiskit.circuit.equivalence_library import SessionEquivalenceLibrary
from qiskit.transpiler import CouplingMap, PassManager

from prism.lowering.ir import LoweredOp
from prism.logical import basic_logical_pm
from prism.physical import physical_pm as _physical_pm


class QubitEncoding:
    """Per-logical-qubit encoding into a block of physical wires."""

    WIRES_PER_LOGICAL: ClassVar[int]
    # Re-emit the routed circuit with commuting diagonal gates ordered by critical path.
    reschedule: ClassVar[bool] = True
    LOGICAL_ISA: ClassVar[frozenset[str]]
    # Gates the lowering stage can emit on physical wires. Subclasses set
    # this; usually equals ``LOGICAL_ISA`` filtered of measure/barrier/reset/
    # control-flow, plus any non-standard primitives the encoding's lowering
    # introduces (e.g. DR's ``rswap``).
    PHYSICAL_ISA: ClassVar[frozenset[str]]
    # Whether the physical stage may resynthesize 2Q blocks (preset O3). True
    # for universal-ISA codes (DualRail). Restricted-Clifford codes set False:
    # their non-universal PHYSICAL_ISA breaks O3's UnitarySynthesis, and
    # resynthesis would collapse the transversal structure
    # (see ``physical.physical_pm``). False ⇒ layout + route only.
    PHYSICAL_RESYNTHESIS: ClassVar[bool] = True

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
    def physical_pm(cls, coupling_map: CouplingMap, *, seed: int = 42) -> PassManager:
        """Compile the retained route over ``cls.PHYSICAL_ISA``."""
        return _physical_pm(
            coupling_map, cls, seed=seed, resynthesize=cls.PHYSICAL_RESYNTHESIS
        )

    @classmethod
    def lower(cls, op: Instruction, clbits: tuple[Clbit, ...] = ()) -> LoweredOp:
        """Dispatch to ``cls.<op.name>``. ``clbits`` is forwarded only for ``ControlFlowOp``."""
        name = op.name
        if name not in cls.LOGICAL_ISA:
            raise ValueError(
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
    def barrier(cls, op: Instruction) -> LoweredOp:
        """Logical barrier → physical barrier covering all rails of the spanned qubits."""
        n_wires = op.num_qubits * cls.WIRES_PER_LOGICAL
        qc = QuantumCircuit(n_wires)
        qc.barrier(range(n_wires))
        return LoweredOp.fixed(qc, name="barrier")

    @classmethod
    def measure(cls, op: Instruction) -> LoweredOp:
        """Per-wire Z-basis measurement; ``num_clbits = num_qubits`` (bound at apply)."""
        n_wires = op.num_qubits * cls.WIRES_PER_LOGICAL
        qc = QuantumCircuit(n_wires, n_wires)
        for w in range(n_wires):
            qc.measure(w, w)
        return LoweredOp.fixed(qc, name="measure")

    @classmethod
    def if_else(cls, op: Instruction, clbits: tuple[Clbit, ...]) -> LoweredOp:
        """Wire-level ``IfElseOp`` over recursively-lowered blocks. Blocks must lower to fixed ops."""
        new_blocks: list[QuantumCircuit | None] = []
        for block in op.blocks:
            if block is None:
                new_blocks.append(None)
                continue
            new_blocks.append(cls._lower_block(block))
        if len(new_blocks) == 1:
            new_op = IfElseOp(op.condition, new_blocks[0], None)
        else:
            new_op = IfElseOp(op.condition, new_blocks[0], new_blocks[1])

        n_wires = op.num_qubits * cls.WIRES_PER_LOGICAL
        qc = QuantumCircuit(n_wires)
        # Add the exact clbits the op references as loose bits — adding the
        # parent register would inflate ``qc.num_clbits`` past ``len(clbits)``
        # and break ``substitute_node_with_dag``'s positional bit mapping
        # (the node has ``len(clbits)`` cargs, not the full register).
        qc.add_bits(clbits)
        qc.append(new_op, range(n_wires), clbits)
        return LoweredOp.fixed(qc, name="if_else")

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
            logical_qubits = tuple(block_q_to_logical[q] for q in instr.qubits)
            lowered = cls.lower(instr.operation, tuple(instr.clbits))
            if not lowered.is_fixed:
                raise ValueError(
                    f"Op {instr.operation.name!r} inside a control-flow block "
                    f"lowered to a multi-realization. Conditional 2Q gates aren't "
                    f"supported by the default if_else rule; move the op out of "
                    f"the block or override if_else in your encoding."
                )
            sub_qc = lowered.realizations[0]
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
