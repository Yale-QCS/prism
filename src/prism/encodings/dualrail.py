"""Dual-rail encoding rules. Convention ``|0_L⟩ = |01⟩, |1_L⟩ = |10⟩``."""

from __future__ import annotations

from typing import ClassVar

import numpy as np
from qiskit.circuit import Gate, Instruction, ParameterExpression, QuantumCircuit
from qiskit.circuit.library import XGate
from qiskit.transpiler import PassManager

from prism.encodings.base import QubitEncoding
from prism.encodings.dualrail_logical import (
    MargolusPairOptimizer,
    equivalence_library,
)
from prism.ir import MultiRealizationOp
from prism.logical import basic_logical_pm
from prism.synthesis.preparation import (
    SYNTHETIC_PREPARATION_LABEL,
    JointHeraldGate,
)


class RSwapGate(Gate):
    """Fractional SWAP; exactly ``SwapGate().power(theta/pi)``."""

    def __init__(self, theta: float | ParameterExpression) -> None:
        """Create an rswap gate with angle ``theta``."""
        super().__init__("rswap", 2, [theta])

    def __array__(
        self, dtype: np.dtype | None = None, copy: bool | None = None
    ) -> np.ndarray:
        theta = float(self.params[0])
        p = np.exp(1j * theta / 2)
        c, s = np.cos(theta / 2), np.sin(theta / 2)
        return np.array(
            [
                [1, 0, 0, 0],
                [0, p * c, -1j * p * s, 0],
                [0, -1j * p * s, p * c, 0],
                [0, 0, 0, 1],
            ],
            dtype=dtype or complex,
        )

    def _define(self) -> None:
        """Exact standard-gate form (execution/simulation boundary only).

        SWAP^(θ/π) = e^{iθ/4}·rxx(θ/2)·ryy(θ/2)·rzz(θ/2).
        """
        theta = self.params[0]
        qc = QuantumCircuit(2, global_phase=theta / 4)
        qc.rxx(theta / 2, 0, 1)
        qc.ryy(theta / 2, 0, 1)
        qc.rzz(theta / 2, 0, 1)
        self.definition = qc


class DualRail(QubitEncoding):
    """Dual-rail encoding. Stateless — pass the class itself, not an instance."""

    WIRES_PER_LOGICAL: ClassVar[int] = 2
    LOGICAL_ISA: ClassVar[frozenset[str]] = frozenset(
        {"x", "rx", "rz", "crz", "swap", "measure", "reset", "if_else"}
    )
    # Adds ``rswap`` (post-lowering RX(theta) → RSwapGate on a rail pair).
    PHYSICAL_ISA: ClassVar[frozenset[str]] = frozenset(
        {"x", "rx", "rz", "crz", "swap", "rswap", "joint_herald"}
    )
    CUSTOM_GATES: ClassVar[dict[str, type]] = {
        "rswap": RSwapGate,
        "joint_herald": JointHeraldGate,
    }

    @classmethod
    def initialize(cls) -> QuantumCircuit:
        """Create the routing placeholder for dual-rail preparation.

        The labeled X and joint-herald operation expose the preparation
        connectivity to the boundary router. Hardware-facing program metrics
        exclude both labeled operations because prism does not model the
        preparation circuit or erasure-check implementation.
        """
        qc = QuantumCircuit(2)
        qc.append(XGate(label=SYNTHETIC_PREPARATION_LABEL), [1])
        qc.append(JointHeraldGate(), [0, 1])
        return qc

    @classmethod
    def logical_pm(cls) -> PassManager:
        """Basic cleanup with Margolus pairs and the dual-rail equivalence library."""
        return basic_logical_pm(
            cls,
            eq_library=equivalence_library(),
            # CCX compute/uncompute pairs → RTOF (DR has a 4-RX CCX template
            # but RTOF is cheaper; phases cancel pairwise).
            reshape_passes=(MargolusPairOptimizer(),),
        )

    # ---- Encoding-specific lowering rules --------------------------------
    @classmethod
    def x(cls, op: Instruction) -> MultiRealizationOp:
        """Logical X → physical SWAP(0,1). Single realization."""
        qc = QuantumCircuit(2)
        qc.swap(0, 1)
        return MultiRealizationOp("x", (qc,))

    @classmethod
    def rx(cls, op: Instruction) -> MultiRealizationOp:
        """Logical RX(θ) → rejoin (RSwap on the rails)."""
        (theta,) = op.params
        qc = QuantumCircuit(2)
        qc.append(RSwapGate(theta), [0, 1])
        return MultiRealizationOp("rx", (qc,))

    @classmethod
    def rz(cls, op: Instruction) -> MultiRealizationOp:
        """Logical RZ(θ) → physical RZ(θ) on wire 0. Single realization (either rail works; convention is wire 0)."""
        qc = QuantumCircuit(2)
        qc.append(op, [0])
        return MultiRealizationOp("rz", (qc,), diagonal=True)

    @classmethod
    def crz(cls, op: Instruction) -> MultiRealizationOp:
        """Logical CRZ(θ) → 4 candidates over wire pairs ``(ra, rb)`` of (control, target).

        ``Z_L = Z_a = -Z_b``, so b-rail target flips the sign. b-rail control is
        anti-control at the logical level; absorbed via the codespace-safe identity
        ``open-control CRZ(α) ≡ CRZ(-α) · RZ(α)_t`` (the X-sandwich alternative
        would drop an unpaired X on ``b_c``, breaking dual-rail).
        """
        (theta,) = op.params
        candidates = []
        for ra in (0, 1):
            for rb in (0, 1):
                qc = QuantumCircuit(4)
                target_sign = (-1) ** rb
                crz_sign = -target_sign if ra == 1 else target_sign
                qc.crz(crz_sign * theta, ra, 2 + rb)
                if ra == 1:
                    qc.rz(target_sign * theta, 2 + rb)
                candidates.append(qc)
        return MultiRealizationOp(
            "crz", tuple(candidates), default_index=2, diagonal=True
        )

    @classmethod
    def swap(cls, _op: Instruction) -> MultiRealizationOp:
        """Logical SWAP → 2 partition options over wire-pair edges.

        A (2 SWAPs): bare ``swap(0,2)+swap(1,3)``.
        B (4 SWAPs): crossover ``swap(0,3)+swap(1,2)`` realizes ``SWAP_L · (X_L⊗X_L)``,
        corrected by intra-pair ``swap(0,1)+swap(2,3)``. Intra-pair SWAP is
        leakage-safe (preserves ``|00⟩/|11⟩``); ``X⊗X`` would scramble them.
        """
        qc0 = QuantumCircuit(4)
        qc0.swap(0, 2)
        qc0.swap(1, 3)

        qc1 = QuantumCircuit(4)
        qc1.swap(0, 3)
        qc1.swap(1, 2)
        qc1.swap(0, 1)
        qc1.swap(2, 3)

        return MultiRealizationOp("swap", (qc0, qc1))

    @classmethod
    def reset(cls, _op: Instruction) -> MultiRealizationOp:
        """Logical reset → in-place re-preparation on the same rails (the ``initialize`` template).

        Models pump-to-vacuum plus a fresh ``|0_L⟩`` prep; the joint herald is
        the only routing constraint (rails co-located at reset time). Re-hosting
        the reset qubit on other free rails is not expressed here.
        """
        return MultiRealizationOp("reset", (cls.initialize(),))
