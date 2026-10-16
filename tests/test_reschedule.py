"""Rescheduling commuting diagonals keeps the unitary and never deepens the circuit."""

import numpy as np
from qiskit import QuantumCircuit
from qiskit.converters import circuit_to_dag, dag_to_circuit
from qiskit.quantum_info import Operator

from prism.metrics import CircuitMetrics
from prism.physical import RescheduleCommutingDiagonals


def _circuit(seed: int) -> QuantumCircuit:
    rng = np.random.default_rng(seed)
    qc = QuantumCircuit(5)
    for _ in range(40):
        kind = rng.integers(4)
        a, b = (int(x) for x in rng.choice(5, 2, replace=False))
        if kind == 0:
            qc.crz(float(rng.uniform(0.1, 3)), a, b)
        elif kind == 1:
            qc.rz(float(rng.uniform(0.1, 3)), a)
        elif kind == 2:
            qc.rx(float(rng.uniform(0.1, 3)), a)
        else:
            qc.swap(a, b)
    return qc


def test_reschedule_preserves_unitary_and_depth_does_not_grow():
    for seed in range(5):
        qc = _circuit(seed)
        out = dag_to_circuit(RescheduleCommutingDiagonals().run(circuit_to_dag(qc)))
        assert Operator(out).equiv(Operator(qc))
        assert CircuitMetrics.of(out).depth <= CircuitMetrics.of(qc).depth
        assert out.count_ops() == qc.count_ops()
