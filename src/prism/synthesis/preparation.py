"""Routing-only operation for a joint dual-rail preparation check."""

from __future__ import annotations

import math

from qiskit.circuit import Gate, QuantumCircuit

SYNTHETIC_PREPARATION_LABEL = "dualrail_synthetic_preparation"


class JointHeraldGate(Gate):
    """Two-rail connectivity placeholder excluded from program-body metrics."""

    def __init__(self) -> None:
        """Create the routing-only joint-herald operation."""
        super().__init__("joint_herald", 2, [])

    def _define(self) -> None:
        circuit = QuantumCircuit(2)
        circuit.crz(math.pi, 0, 1)
        self.definition = circuit
