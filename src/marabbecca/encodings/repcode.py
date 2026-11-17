"""3-qubit bit-flip repetition code. Convention ``|0_L⟩ = |000⟩, |1_L⟩ = |111⟩``."""

from __future__ import annotations

import itertools
from typing import ClassVar

from qiskit.circuit import Instruction, QuantumCircuit

from marabbecca.encodings.base import QubitEncoding
from marabbecca.lowering.ir import LoweredOp


class RepCode(QubitEncoding):
    """3-qubit bit-flip repetition code. |0_L⟩ = |000⟩, |1_L⟩ = |111⟩."""

    WIRES_PER_LOGICAL: ClassVar[int] = 3
    LOGICAL_ISA: ClassVar[frozenset[str]] = frozenset(
        {"x", "z", "cx", "measure", "barrier"}
    )
    PHYSICAL_ISA: ClassVar[frozenset[str]] = frozenset({"x", "z", "cx", "swap"})
    # {x,z,cx,swap} is non-universal; preset O3 would emit ``u`` and collapse the
    # transversal structure. Route without 2Q resynthesis.
    PHYSICAL_RESYNTHESIS: ClassVar[bool] = False

    @classmethod
    def initialize(cls) -> QuantumCircuit:
        """Hardware boots in |000⟩ = |0_L⟩, so this is a no-op."""
        return QuantumCircuit(3)

    @classmethod
    def x(cls, _op: Instruction) -> LoweredOp:
        """Transversal X on all 3 wires."""
        qc = QuantumCircuit(3)
        qc.x(range(3))
        return LoweredOp.fixed(qc, name="x")

    @classmethod
    def z(cls, _op: Instruction) -> LoweredOp:
        """Z on any single wire realizes logical Z. Three candidates."""
        candidates = []
        for w in range(3):
            qc = QuantumCircuit(3)
            qc.z(w)
            candidates.append(qc)
        return LoweredOp.decision(tuple(candidates), name="z")

    @classmethod
    def cx(cls, _op: Instruction) -> LoweredOp:
        """CX(a_i, b_σ(i)) for any σ ∈ S_3. Six permutation realizations; default is transversal."""
        candidates = []
        for sigma in itertools.permutations(range(3)):
            qc = QuantumCircuit(6)
            for i in range(3):
                qc.cx(i, 3 + sigma[i])
            candidates.append(qc)
        return LoweredOp.decision(tuple(candidates), name="cx")
