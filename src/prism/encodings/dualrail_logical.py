"""The dual-rail logical stage's equivalence library and passes.

In dual rail an RX is an RSWAP and an RZ is free. The session library puts RX
on control wires; these templates keep every RX on the target.
"""

from __future__ import annotations

from functools import partial

import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit import (
    EquivalenceLibrary,
    Gate,
    Parameter,
    ParameterExpression,
)
from qiskit.circuit.equivalence_library import SessionEquivalenceLibrary
from qiskit.circuit.library import (
    CCXGate,
    CPhaseGate,
    CSdgGate,
    CSGate,
    CUGate,
    RXXGate,
    RYYGate,
    RZZGate,
    iSwapGate,
)
from qiskit.converters import circuit_to_dag
from qiskit.dagcircuit import DAGCircuit
from qiskit.quantum_info import Clifford
from qiskit.synthesis import synth_clifford_ag, synth_clifford_greedy
from qiskit.transpiler import PassManager
from qiskit.transpiler.passes import (
    BasisTranslator,
    CollectCliffords,
    Optimize1qGatesDecomposition,
)
from qiskit.transpiler.passes.optimization.collect_and_collapse import (
    collapse_to_operation,
)


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


class MinRXCliffords(CollectCliffords):
    """Resynthesize each Clifford block with the fewest ``rx``, then ``crz``, in ``isa``.

    The candidates are the block itself and its greedy and Aaronson-Gottesman syntheses.
    A synthesis that couples a new pair of qubits, or holds a SWAP, is skipped:
    routing the new pair costs more than the gates saved.
    """

    def __init__(self, eq_library: EquivalenceLibrary, isa: list[str]) -> None:
        super().__init__()
        translate = PassManager(
            [BasisTranslator(eq_library, isa), Optimize1qGatesDecomposition(basis=isa)]
        )

        def score(qc: QuantumCircuit) -> tuple[int, int]:
            ops = translate.run(qc).count_ops()
            return ops.get("rx", 0), ops.get("crz", 0)

        def pairs(qc: QuantumCircuit) -> set[frozenset]:
            # A SWAP is elided into a relabelling of every later gate: never a subset.
            return {
                frozenset(ci.qubits) if ci.operation.name != "swap" else ci.qubits
                for ci in qc.data
                if len(ci.qubits) == 2
            }

        def best(block: QuantumCircuit) -> Gate:
            cliff = Clifford(block)
            cands = (block, synth_clifford_greedy(cliff), synth_clifford_ag(cliff))
            qc = min((c for c in cands if pairs(c) <= pairs(block)), key=score)
            return qc.to_gate(label="min_rx_clifford")

        self.collapse_function = partial(collapse_to_operation, collapse_function=best)

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        dag = super().run(dag)
        for node in dag.op_nodes():
            if node.op.label == "min_rx_clifford":
                dag.substitute_node_with_dag(node, circuit_to_dag(node.op.definition))
        return dag
