"""The dual-rail encoding: ``|0_L> = |01>`` and ``|1_L> = |10>`` on a pair of rails.

The logical stage translates to ``LOGICAL_ISA`` with ``equivalence_library()``.
``lower`` turns each logical operation into a ``MultiRealizationOp`` on its rails,
whose candidates use ``PHYSICAL_ISA``. In dual rail an RX is an RSWAP and an RZ is
free, so the templates keep every RX on a gate's target.
"""

from __future__ import annotations

import numpy as np
from qiskit.circuit import (
    Clbit,
    EquivalenceLibrary,
    Gate,
    Instruction,
    Measure,
    Parameter,
    ParameterExpression,
    QuantumCircuit,
    QuantumRegister,
)
from qiskit.circuit.controlflow import IfElseOp
from qiskit.circuit.equivalence_library import SessionEquivalenceLibrary
from qiskit.circuit.library import (
    CCXGate,
    CPhaseGate,
    CSdgGate,
    CSGate,
    CUGate,
    Initialize,
    PauliProductMeasurement,
    RXXGate,
    RYYGate,
    RZZGate,
    iSwapGate,
)
from qiskit.quantum_info import Pauli
from qiskit.transpiler import TranspilerError

from prism.ir import RAILS, MultiRealizationOp


class RSwapGate(Gate):
    """Fractional SWAP, ``SwapGate().power(theta / pi)``."""

    def __init__(self, theta: float | ParameterExpression) -> None:
        super().__init__("rswap", 2, [theta])

    def __array__(self, dtype=None, copy=None) -> np.ndarray:
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


#: Logical operations ``lower`` takes, which the logical stage translates to.
LOGICAL_ISA = frozenset(
    {"x", "rx", "rz", "crz", "swap", "measure", "reset", "if_else", "erasure_check"}
)
#: Operations of the candidates, which the physical stage keeps.
PHYSICAL_ISA = frozenset(
    {"rz", "crz", "swap", "rswap", "initialize", "pauli_product_measurement"}
)
#: The non-standard gates of ``PHYSICAL_ISA``, for ``Target.from_configuration``.
CUSTOM_GATES = {
    "rswap": RSwapGate(Parameter("theta")),
    "initialize": Initialize("10"),  # little-endian: rail 1 holds the photon
    "pauli_product_measurement": PauliProductMeasurement(Pauli("ZZ")),
}


def initialize() -> QuantumCircuit:
    """Prepare ``|0_L>`` on a pair of rails."""
    qc = QuantumCircuit(RAILS)
    qc.append(Initialize("10"), [0, 1])
    return qc


def lower(op: Instruction, clbits: tuple[Clbit, ...] = ()) -> MultiRealizationOp:
    """``op`` as a ``MultiRealizationOp``; wire ``RAILS * k + w`` is rail ``w`` of qubit ``k``.

    ``clbits`` are the clbits of an ``if_else``.
    """
    if op.name not in LOGICAL_ISA:
        raise TranspilerError(f"dual rail does not support {op.name!r}")
    if op.name == "if_else":
        return _if_else(op, clbits)
    return _RULES[op.name](op)


def _x(op: Instruction) -> MultiRealizationOp:
    """Exchange the rails."""
    qc = QuantumCircuit(2)
    qc.swap(0, 1)
    return MultiRealizationOp("x", (qc,))


def _rx(op: Instruction) -> MultiRealizationOp:
    qc = QuantumCircuit(2)
    qc.append(RSwapGate(op.params[0]), [0, 1])
    return MultiRealizationOp("rx", (qc,))


def _rz(op: Instruction) -> MultiRealizationOp:
    qc = QuantumCircuit(2)
    qc.append(op, [0])
    return MultiRealizationOp("rz", (qc,), diagonal=True)


def _crz(op: Instruction) -> MultiRealizationOp:
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
    return MultiRealizationOp("crz", tuple(candidates), default_index=2, diagonal=True)


def _swap(op: Instruction) -> MultiRealizationOp:
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


def _measure(op: Instruction) -> MultiRealizationOp:
    """Measure both rails; rail ``w`` writes clbit ``w``."""
    qc = QuantumCircuit(RAILS, RAILS)
    qc.measure(range(RAILS), range(RAILS))
    return MultiRealizationOp("measure", (qc,))


def _reset(op: Instruction) -> MultiRealizationOp:
    return MultiRealizationOp("reset", (initialize(),))


def _erasure_check(op: Instruction) -> MultiRealizationOp:
    """ZZ of the rails: -1 on both code states, +1 once the photon is lost."""
    qc = QuantumCircuit(2, 1)
    qc.append(CUSTOM_GATES["pauli_product_measurement"], [0, 1], [0])
    return MultiRealizationOp("erasure_check", (qc,))


def _if_else(op: IfElseOp, clbits: tuple[Clbit, ...]) -> MultiRealizationOp:
    """An ``if_else`` on one qubit's rails, its blocks lowered gate by gate."""
    if op.num_qubits > 1:
        raise TranspilerError(
            "dual rail lowers one if_else per qubit: every block instruction "
            "must act on one qubit and write no clbit"
        )
    qc = QuantumCircuit(RAILS)
    qc.add_bits(clbits)
    blocks = [_lower_block(b) for b in op.blocks]
    qc.append(IfElseOp(op.condition, *blocks), qc.qubits, clbits)
    return MultiRealizationOp("if_else", (qc,))


def _lower_block(block: QuantumCircuit) -> QuantumCircuit:
    regs = [QuantumRegister(RAILS, f"q{i}") for i in range(block.num_qubits)]
    out = QuantumCircuit(*regs, *block.cregs)
    out.add_bits([c for c in block.clbits if not block.find_bit(c).registers])
    for instr in block.data:
        if isinstance(instr.operation, Measure):
            raise TranspilerError(
                "dual rail does not support a measurement inside a control-flow block"
            )
        lowered = lower(instr.operation, instr.clbits)
        if len(lowered.candidates) != 1:
            raise TranspilerError(
                f"dual rail cannot put {instr.operation.name!r}, which has several "
                "realizations, in an if_else block"
            )
        wires = [w for q in instr.qubits for w in regs[block.find_bit(q).index]]
        out.compose(lowered.candidates[0], wires, instr.clbits, inplace=True)
    return out


_RULES = {
    "x": _x,
    "rx": _rx,
    "rz": _rz,
    "crz": _crz,
    "swap": _swap,
    "measure": _measure,
    "reset": _reset,
    "erasure_check": _erasure_check,
}


def _h(qc: QuantumCircuit, q: int) -> None:
    """``H`` as ``Rz . Rx . Rz``: one RX."""
    qc.rz(np.pi / 2, q)
    qc.rx(np.pi / 2, q)
    qc.rz(np.pi / 2, q)


def _u(
    qc: QuantumCircuit,
    theta: float | ParameterExpression,
    phi: float | ParameterExpression,
    lam: float | ParameterExpression,
    q: int,
) -> None:
    """``U(theta, phi, lam)`` as ``Rz(lam - pi/2) . Rx(theta) . Rz(phi + pi/2)``."""
    qc.rz(lam - np.pi / 2, q)
    qc.rx(theta, q)
    qc.rz(phi + np.pi / 2, q)


def _cx(qc: QuantumCircuit, c: int, t: int) -> None:
    """``CX(c, t) = H_t . S_c . CRz(pi) . H_t``, up to global phase."""
    _h(qc, t)
    qc.rz(np.pi / 2, c)
    qc.crz(np.pi, c, t)
    _h(qc, t)


def _cz(qc: QuantumCircuit) -> None:
    """``CZ(0, 1) = CRz(pi) . Rz(pi/2)_0``, up to global phase."""
    qc.crz(np.pi, 0, 1)
    qc.rz(np.pi / 2, 0)


def _cu() -> tuple[CUGate, QuantumCircuit]:
    """``CU`` as Qiskit's definition with each CX and U expanded target-side."""
    theta, phi, lam, gamma = (Parameter(s) for s in ("θ", "φ", "λ", "γ"))
    qc = QuantumCircuit(2)
    qc.rz(gamma, 0)
    qc.rz((lam + phi) / 2, 0)
    qc.rz((lam - phi) / 2, 1)
    _cx(qc, 0, 1)
    _u(qc, -theta / 2, 0, -(lam + phi) / 2, 1)
    _cx(qc, 0, 1)
    _u(qc, theta / 2, phi, 0, 1)
    return CUGate(theta, phi, lam, gamma), qc


def _rzz() -> tuple[RZZGate, QuantumCircuit]:
    """``RZZ(theta) = CRZ(-2 theta) . Rz(theta)_1``, up to global phase."""
    theta = Parameter("θ")
    qc = QuantumCircuit(2)
    qc.crz(-2 * theta, 0, 1)
    qc.rz(theta, 1)
    return RZZGate(theta), qc


def _cp() -> tuple[CPhaseGate, QuantumCircuit]:
    """``CP(theta) = Rz(theta/2)_0 . CRZ(theta)``, up to global phase."""
    theta = Parameter("θ")
    qc = QuantumCircuit(2)
    qc.rz(theta / 2, 0)
    qc.crz(theta, 0, 1)
    return CPhaseGate(theta), qc


def _cs(gate: CSGate | CSdgGate, sign: int) -> tuple[Gate, QuantumCircuit]:
    """``CS`` (``sign=1``) or ``CSdg`` (``sign=-1``) as ``CP(sign pi/2)``."""
    qc = QuantumCircuit(2)
    qc.rz(sign * np.pi / 4, 0)
    qc.crz(sign * np.pi / 2, 0, 1)
    return gate, qc


def _rxx_body(qc: QuantumCircuit, theta: Parameter) -> None:
    """``RXX(theta) = H_0 . CZ . RX(theta)_1 . CZ . H_0``, up to global phase. 3 RX."""
    _h(qc, 0)
    _cz(qc)
    qc.rx(theta, 1)
    _cz(qc)
    _h(qc, 0)


def _rxx() -> tuple[RXXGate, QuantumCircuit]:
    """``RXX`` with 3 RX."""
    theta = Parameter("θ")
    qc = QuantumCircuit(2)
    _rxx_body(qc, theta)
    return RXXGate(theta), qc


def _ryy() -> tuple[RYYGate, QuantumCircuit]:
    """``RYY(theta) = (Sdg x Sdg) . RXX(theta) . (S x S)``, up to global phase. 3 RX."""
    theta = Parameter("θ")
    qc = QuantumCircuit(2)
    qc.rz(-np.pi / 2, 0)
    qc.rz(-np.pi / 2, 1)
    _rxx_body(qc, theta)
    qc.rz(np.pi / 2, 0)
    qc.rz(np.pi / 2, 1)
    return RYYGate(theta), qc


def _iswap() -> tuple[iSwapGate, QuantumCircuit]:
    """``iSwap = SWAP . RZZ(pi/2)``, up to global phase. No RX."""
    qc = QuantumCircuit(2)
    qc.swap(0, 1)
    qc.rzz(np.pi / 2, 0, 1)
    return iSwapGate(), qc


def _ccx() -> tuple[CCXGate, QuantumCircuit]:
    """``CCX(a,b,t) = H_t . CS(a,t) . CX(b,t) . CSdg(a,t) . CX(b,t) . CS(a,b) . H_t``. 4 RX after Opt1q."""
    qc = QuantumCircuit(3)
    qc.h(2)
    qc.cs(0, 2)
    qc.cx(1, 2)
    qc.csdg(0, 2)
    qc.cx(1, 2)
    qc.cs(0, 1)
    qc.h(2)
    return CCXGate(), qc


def equivalence_library() -> EquivalenceLibrary:
    """The templates on top of the session library; ``BasisTranslator`` takes the shortest path."""
    lib = EquivalenceLibrary(base=SessionEquivalenceLibrary)
    for gate, template in (
        _cu(),
        _rzz(),
        _cp(),
        _cs(CSGate(), 1),
        _cs(CSdgGate(), -1),
        _rxx(),
        _ryy(),
        _iswap(),
        _ccx(),
    ):
        lib.add_equivalence(gate, template)
    return lib
