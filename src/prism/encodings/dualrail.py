"""Dual-rail encoding rules. Convention ``|0_L⟩ = |01⟩, |1_L⟩ = |10⟩`` (paper §1 Eq. 3)."""

from __future__ import annotations

import math
from typing import ClassVar

from qiskit.circuit import Instruction, QuantumCircuit
from qiskit.circuit.library import XGate
from qiskit.transpiler import PassManager

from prism.encodings.base import QubitEncoding
from prism.lowering.ir import LoweredOp
from prism.logical import ElideLogicalPermutations, basic_logical_pm
from prism.synthesis.delocal_decomp import build_equivalence_library
from prism.synthesis.early_measure import EarlyMeasurement
from prism.synthesis.h_reduction import HadamardReduction
from prism.synthesis.margolus import MargolusPairOptimizer
from prism.synthesis.pauli_frame import PauliFramePropagation
from prism.synthesis.preparation import JointHeraldGate
from prism.synthesis.rswap import RSwapGate


class DualRail(QubitEncoding):
    """Dual-rail encoding. Stateless — pass the class itself, not an instance."""

    WIRES_PER_LOGICAL: ClassVar[int] = 2
    LOGICAL_ISA: ClassVar[frozenset[str]] = frozenset(
        {"x", "rx", "rz", "crz", "swap", "measure", "barrier", "reset", "if_else"}
    )
    # Adds ``rswap`` (post-lowering RX(theta) → RSwapGate on a rail pair).
    PHYSICAL_ISA: ClassVar[frozenset[str]] = frozenset(
        {"x", "rx", "rz", "crz", "swap", "rswap", "joint_herald"}
    )
    # Initialization model. Default is a heralded prep whose joint erasure check
    # (a QND occupation measurement on the rail pair) requires the two rails
    # co-located at t=0. A routing-only joint-herald operation supplies this 2Q
    # constraint without assigning a hardware implementation. Set ``local_init
    # = True`` for a single-wire prep that imposes no co-location.
    local_init: ClassVar[bool] = False
    # Measure a qubit at its last non-diagonal gate and turn the diagonal tail
    # into feedforward RZs (see ``synthesis.early_measure``).
    early_measure: ClassVar[bool] = False
    SYNTHETIC_PREPARATION_LABEL: ClassVar[str] = "dualrail_synthetic_preparation"

    @classmethod
    def initialize(cls) -> QuantumCircuit:
        """Create the routing placeholder for dual-rail preparation.

        The labeled X and joint-herald operation expose the preparation
        connectivity to the boundary router. Hardware-facing program metrics
        exclude both labeled operations because the paper does not model the
        preparation circuit or erasure-check implementation. ``local_init =
        True`` removes the joint-herald constraint.
        """
        qc = QuantumCircuit(2)
        qc.append(XGate(label=cls.SYNTHETIC_PREPARATION_LABEL), [1])
        if not cls.local_init:
            qc.append(JointHeraldGate(), [0, 1])
        return qc

    @classmethod
    def logical_pm(cls) -> PassManager:
        """DR rich pre-lowering: basic cleanup + DR-specific reshape + DR equivalence library."""
        pm = basic_logical_pm(
            cls,
            eq_library=build_equivalence_library(),
            reshape_passes=(
                # CCX compute/uncompute pairs → RTOF (DR has a 4-RX CCX template
                # but RTOF is cheaper; phases cancel pairwise).
                MargolusPairOptimizer(),
                # Clifford + RZ frame propagation; settles at H, RX, CX-target.
                PauliFramePropagation(),
                # Local H-reduction (Nam-Maslov 1710.07345 patterns 1 & 4).
                HadamardReduction(),
            ),
        )
        # Input SWAPs express a permutation of logical identities.  Remove
        # them before code expansion; routing SWAPs inserted in later stages
        # remain physical operations.
        pm.append(ElideLogicalPermutations())
        if cls.early_measure:
            pm.append(EarlyMeasurement())
        return pm

    @classmethod
    def custom_name_mapping(cls) -> dict:
        """Register ``rswap`` opaquely so the physical Target accepts it post-lowering."""
        return {
            "rswap": RSwapGate,
            "joint_herald": JointHeraldGate,
        }

    # ---- Encoding-specific lowering rules --------------------------------
    @classmethod
    def x(cls, op: Instruction) -> LoweredOp:
        """Logical X → physical SWAP(0,1). Single realization."""
        qc = QuantumCircuit(2)
        qc.swap(0, 1)
        return LoweredOp.fixed(qc, name="x")

    @classmethod
    def rx(cls, op: Instruction) -> LoweredOp:
        """Logical RX(θ) → rejoin (RSwap on the rails)."""
        (theta,) = op.params
        qc = QuantumCircuit(2)
        qc.append(RSwapGate(theta), [0, 1])
        return LoweredOp.fixed(qc, name="rx")

    @classmethod
    def rz(cls, op: Instruction) -> LoweredOp:
        """Logical RZ(θ) → physical RZ(θ) on wire 0. Single realization (either rail works; convention is wire 0)."""
        qc = QuantumCircuit(2)
        qc.append(op, [0])
        return LoweredOp.fixed(qc, name="rz")

    @classmethod
    def crz(cls, op: Instruction) -> LoweredOp:
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
        return LoweredOp.decision(tuple(candidates), default_index=2, name="crz")

    @classmethod
    def swap(cls, _op: Instruction) -> LoweredOp:
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

        return LoweredOp.decision((qc0, qc1), name="swap")

    @classmethod
    def reset(cls, _op: Instruction) -> LoweredOp:
        """Logical reset → in-place re-preparation on the same rails (the ``initialize`` template).

        Models pump-to-vacuum plus a fresh ``|0_L⟩`` prep; the joint herald is
        the only routing constraint (rails co-located at reset time). Re-hosting
        the reset qubit on other free rails is not expressed here.
        """
        return LoweredOp.fixed(cls.initialize(), name="reset")
