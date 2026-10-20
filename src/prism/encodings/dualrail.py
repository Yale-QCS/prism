"""Dual-rail encoding: ``|0_L> = |01>``, ``|1_L> = |10>`` on a pair of rails."""

from __future__ import annotations

from typing import ClassVar

import numpy as np
from qiskit.circuit import (
    Gate,
    Instruction,
    Parameter,
    ParameterExpression,
    QuantumCircuit,
)
from qiskit.circuit.library import Initialize, PauliProductMeasurement
from qiskit.quantum_info import Pauli
from qiskit.transpiler import PassManager

from prism.encodings.base import QubitEncoding
from prism.encodings.dualrail_logical import (
    MargolusPairOptimizer,
    MinRXCliffords,
    equivalence_library,
)
from prism.ir import MultiRealizationOp
from prism.logical import NON_GATE_ISA_NAMES, basic_logical_pm


class RSwapGate(Gate):
    """Fractional SWAP, ``SwapGate().power(theta / pi)``."""

    def __init__(self, theta: float | ParameterExpression) -> None:
        super().__init__("rswap", 2, [theta])

    def __array__(
        self, dtype: np.dtype | None = None, copy: bool | None = None
    ) -> np.ndarray:
        if copy is False:
            raise ValueError(
                "unable to avoid copy while creating an array as requested"
            )
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
        theta = self.params[0]
        qc = QuantumCircuit(2, global_phase=theta / 4)
        qc.rxx(theta / 2, 0, 1)
        qc.ryy(theta / 2, 0, 1)
        qc.rzz(theta / 2, 0, 1)
        self.definition = qc


class ErasureCheck(Instruction):
    """Erasure check of one qubit: its clbit reads 1 if the photon is there, 0 if lost.

    It does not disturb the logical state. ``qc.append(ErasureCheck(), [q], [c])``.
    """

    def __init__(self) -> None:
        super().__init__("erasure_check", 1, 1, [])


class DualRail(QubitEncoding):
    """The dual-rail encoding."""

    WIRES_PER_LOGICAL: ClassVar[int] = 2
    LOGICAL_ISA: ClassVar[frozenset[str]] = frozenset(
        {"x", "rx", "rz", "crz", "swap", "measure", "reset", "if_else", "erasure_check"}
    )
    PHYSICAL_ISA: ClassVar[frozenset[str]] = frozenset(
        {"rz", "crz", "swap", "rswap", "initialize", "pauli_product_measurement"}
    )
    CUSTOM_GATES: ClassVar[dict[str, Instruction]] = {
        "rswap": RSwapGate(Parameter("theta")),
        "initialize": Initialize("10"),  # little-endian: rail 1 holds the photon
        "pauli_product_measurement": PauliProductMeasurement(Pauli("ZZ")),
    }

    @classmethod
    def initialize(cls) -> QuantumCircuit:
        qc = QuantumCircuit(2)
        qc.append(Initialize("10"), [0, 1])
        return qc

    @classmethod
    def logical_pm(cls) -> PassManager:
        lib = equivalence_library()
        return basic_logical_pm(
            cls,
            eq_library=lib,
            reshape_passes=(
                MargolusPairOptimizer(),
                MinRXCliffords(lib, sorted(cls.LOGICAL_ISA - NON_GATE_ISA_NAMES)),
            ),
        )

    @classmethod
    def x(cls, op: Instruction) -> MultiRealizationOp:
        """Exchange the rails."""
        qc = QuantumCircuit(2)
        qc.swap(0, 1)
        return MultiRealizationOp("x", (qc,))

    @classmethod
    def rx(cls, op: Instruction) -> MultiRealizationOp:
        qc = QuantumCircuit(2)
        qc.append(RSwapGate(op.params[0]), [0, 1])
        return MultiRealizationOp("rx", (qc,))

    @classmethod
    def rz(cls, op: Instruction) -> MultiRealizationOp:
        qc = QuantumCircuit(2)
        qc.append(op, [0])
        return MultiRealizationOp("rz", (qc,), diagonal=True)

    @classmethod
    def crz(cls, op: Instruction) -> MultiRealizationOp:
        """A ``crz`` from either rail of the control to either rail of the target.

        ``Z_L = Z_0 = -Z_1``, so a rail-1 target flips the angle, and a rail-1
        control is an open control: ``crz(-a) . rz(a)_t``.
        """
        (theta,) = op.params
        candidates = []
        for rc in (0, 1):
            for rt in (0, 1):
                sign = (-1) ** rt
                qc = QuantumCircuit(4)
                qc.crz(-sign * theta if rc else sign * theta, rc, 2 + rt)
                if rc:
                    qc.rz(sign * theta, 2 + rt)
                candidates.append(qc)
        return MultiRealizationOp(
            "crz", tuple(candidates), default_index=2, diagonal=True
        )

    @classmethod
    def swap(cls, op: Instruction) -> MultiRealizationOp:
        """Swap the rail pairs straight, or crossed and then exchanged within each pair."""
        straight = QuantumCircuit(4)
        straight.swap(0, 2)
        straight.swap(1, 3)
        crossed = QuantumCircuit(4)
        crossed.swap(0, 3)
        crossed.swap(1, 2)
        crossed.swap(0, 1)
        crossed.swap(2, 3)
        return MultiRealizationOp("swap", (straight, crossed))

    @classmethod
    def reset(cls, op: Instruction) -> MultiRealizationOp:
        return MultiRealizationOp("reset", (cls.initialize(),))

    @classmethod
    def erasure_check(cls, op: Instruction) -> MultiRealizationOp:
        """ZZ of the rails: -1 on both code states, +1 once the photon is lost."""
        qc = QuantumCircuit(2, 1)
        qc.append(cls.CUSTOM_GATES["pauli_product_measurement"], [0, 1], [0])
        return MultiRealizationOp("erasure_check", (qc,))
