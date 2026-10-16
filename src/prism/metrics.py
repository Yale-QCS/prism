"""Compile-time circuit metrics for the routed program body."""

from __future__ import annotations

from dataclasses import dataclass

from qiskit import QuantumCircuit
from qiskit.circuit import Instruction
from qiskit.converters import dag_to_circuit
from qiskit.dagcircuit import DAGCircuit
from qiskit.transpiler import AnalysisPass

__all__ = ["CircuitMetrics", "RecordCircuitMetrics"]

_FREE_GATES = frozenset({"rz", "u1", "p", "z", "initialize"})


def is_free(operation: Instruction) -> bool:
    """Single-wire Z rotations, preparation, and control flow whose bodies are free."""
    if operation.name in _FREE_GATES:
        return True
    blocks = getattr(operation, "blocks", None)
    return blocks is not None and all(
        is_free(instr.operation) for block in blocks for instr in block.data
    )


@dataclass(frozen=True)
class CircuitMetrics:
    """Metrics of a circuit; ``depth`` and ``active_gates`` count non-free ops only."""

    swaps: int
    depth: int
    active_gates: int
    size: int

    @classmethod
    def of(cls, qc: QuantumCircuit) -> CircuitMetrics:
        """The metrics of ``qc``."""
        return cls(
            swaps=qc.count_ops().get("swap", 0),
            depth=qc.depth(lambda instr: not is_free(instr.operation)),
            active_gates=sum(not is_free(instr.operation) for instr in qc.data),
            size=qc.size(),
        )


class RecordCircuitMetrics(AnalysisPass):
    """Publish ``property_set["circuit_metrics"]``; runs at the end of the physical stage."""

    def run(self, dag: DAGCircuit) -> None:
        """Compute ``CircuitMetrics`` of ``dag``."""
        self.property_set["circuit_metrics"] = CircuitMetrics.of(dag_to_circuit(dag))
