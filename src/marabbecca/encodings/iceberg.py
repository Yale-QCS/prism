"""[[4,1,2]] iceberg encoding (downgrade of [[4,2,2]] with one logical per block).

[[4,2,2]] would have 4 wires per 2 logicals (block-level coupling); the
``QubitEncoding`` contract assumes 1 logical per block, so we pin iceberg-
logical-2 to ``|0⟩``
and use only one of the two logicals per 4-wire block.

Codewords (one logical per 4-wire block):
    |0⟩_L = (|0000⟩ + |1111⟩) / √2
    |1⟩_L = (|0101⟩ + |1010⟩) / √2

Stabilizers (inherited from [[4,2,2]]): ``X⊗X⊗X⊗X``, ``Z⊗Z⊗Z⊗Z``.
Multi-realization: x has 2 pair realizations, z has 4, cx has 8 wire-permutation
realizations (the partition-preserving subgroup of S_4 on {{0,2},{1,3}}).

PoC encoding for the multi-realization story beyond DualRail; see
``notebooks/01_repcode_poc.ipynb`` for an exploration.
"""

from __future__ import annotations

from typing import ClassVar

from qiskit.circuit import Instruction, QuantumCircuit

from marabbecca.encodings.base import QubitEncoding
from marabbecca.lowering.ir import LoweredOp

# Wire pairings φ: A_i → B_φ(i) that preserve the [[4,1,2]] subspace.
# These are exactly the partition-preserving subgroup of S_4 on {{0,2},{1,3}};
# brute-forced over all 24 permutations.
_CX_PERMS: tuple[tuple[int, int, int, int], ...] = (
    (0, 1, 2, 3),
    (0, 3, 2, 1),
    (1, 0, 3, 2),
    (1, 2, 3, 0),
    (2, 1, 0, 3),
    (2, 3, 0, 1),
    (3, 0, 1, 2),
    (3, 2, 1, 0),
)


class Iceberg412(QubitEncoding):
    """[[4,1,2]] downgrade of [[4,2,2]]: 4 wires per logical, iceberg-logical-2 pinned to ``|0⟩``."""

    WIRES_PER_LOGICAL: ClassVar[int] = 4
    LOGICAL_ISA: ClassVar[frozenset[str]] = frozenset(
        {"x", "z", "cx", "measure", "barrier"}
    )
    # ``h`` is needed by the codeword prep (``initialize``); the logical Cliffords
    # we route stay in {x,z,cx,swap}.
    PHYSICAL_ISA: ClassVar[frozenset[str]] = frozenset({"x", "z", "cx", "swap", "h"})
    # Non-universal ISA: preset O3 would emit ``u`` and collapse the transversal
    # structure. Route without 2Q resynthesis.
    PHYSICAL_RESYNTHESIS: ClassVar[bool] = False

    @classmethod
    def initialize(cls) -> QuantumCircuit:
        """Prep ``|0⟩_L = (|0000⟩ + |1111⟩) / √2`` via H on wire 0 + 3 CXs.

        Not fault-tolerant: a single X fault on wire 0 between the H and the
        last CX propagates to all 4 wires, flipping |0⟩_L → |1⟩_L. FT prep
        would verify with an ancilla (CX from two wires into |0⟩-ancilla,
        measure, post-select on 0) to detect propagated weight-2+ errors.
        """
        qc = QuantumCircuit(4)
        qc.h(0)
        for w in (1, 2, 3):
            qc.cx(0, w)
        return qc

    @classmethod
    def x(cls, _op: Instruction) -> LoweredOp:
        """X̄ = X_0X_2 (default) ~ X_1X_3 (modulo X⊗4 stabilizer). 2 realizations."""
        candidates = []
        for pair in [(0, 2), (1, 3)]:
            qc = QuantumCircuit(4)
            for w in pair:
                qc.x(w)
            candidates.append(qc)
        return LoweredOp.decision(tuple(candidates), name="x")

    @classmethod
    def z(cls, _op: Instruction) -> LoweredOp:
        """Z̄ = Z_0Z_1 (default), Z_2Z_3, Z_1Z_2, Z_0Z_3. 4 realizations from absorbing Z⊗4 and Z̄_2."""
        candidates = []
        for pair in [(0, 1), (2, 3), (1, 2), (0, 3)]:
            qc = QuantumCircuit(4)
            for w in pair:
                qc.z(w)
            candidates.append(qc)
        return LoweredOp.decision(tuple(candidates), name="z")

    @classmethod
    def cx(cls, _op: Instruction) -> LoweredOp:
        """Transversal-with-permutation CX between two 4-wire blocks: 8 valid wire pairings."""
        candidates = []
        for phi in _CX_PERMS:
            qc = QuantumCircuit(8)
            for i in range(4):
                qc.cx(i, 4 + phi[i])
            candidates.append(qc)
        return LoweredOp.decision(tuple(candidates), name="cx")
