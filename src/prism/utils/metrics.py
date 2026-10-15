"""Compile-time circuit metrics for the routed program body."""

from __future__ import annotations

from dataclasses import dataclass

from qiskit import QuantumCircuit
from qiskit.circuit import Instruction
from qiskit.converters import dag_to_circuit
from qiskit.dagcircuit import DAGCircuit
from qiskit.transpiler import AnalysisPass

from prism.synthesis.preparation import SYNTHETIC_PREPARATION_LABEL

FREE_GATES: frozenset[str] = frozenset({"rz", "u1", "p", "z"})


def is_synthetic_preparation(operation: Instruction) -> bool:
    """Return whether an operation is a routing-only preparation placeholder."""
    return (
        operation.name == "joint_herald"
        or getattr(operation, "label", None) == SYNTHETIC_PREPARATION_LABEL
    )


def is_free(operation: Instruction) -> bool:
    """Free: diagonal-Z ops, preparation placeholders, and control flow whose bodies are free."""
    if operation.name in FREE_GATES or is_synthetic_preparation(operation):
        return True
    blocks = getattr(operation, "blocks", None)
    return blocks is not None and all(
        is_free(instr.operation)
        for block in blocks
        if block is not None
        for instr in block.data
    )


def physical_depth(qc: QuantumCircuit) -> int:
    """Return program-body depth in non-free physical operations."""
    return qc.depth(
        filter_function=lambda instruction: not is_free(instruction.operation)
    )


def active_gate_count(qc: QuantumCircuit) -> int:
    """Return the number of non-free program-body operations."""
    return sum(1 for instruction in qc.data if not is_free(instruction.operation))


@dataclass(frozen=True)
class CircuitMetrics:
    """Standardized circuit metrics published to ``property_set["circuit_metrics"]``."""

    swaps: int
    depth: int
    active_gates: int
    size: int


class RecordCircuitMetrics(AnalysisPass):
    """Publish/refresh ``property_set[key]`` metrics from the current DAG.

    Run at the end of the lowering stage (``key="lowering_circuit_metrics"``:
    semantic content, pre-routing) and at the end of the physical stage (the
    default key, final).
    """

    def __init__(self, key: str = "circuit_metrics") -> None:
        """Store the property-set key the metrics are published under."""
        super().__init__()
        self.key = key

    def run(self, dag: DAGCircuit) -> None:
        """Compute ``CircuitMetrics`` for ``dag`` and publish them under ``self.key``."""
        qc = dag_to_circuit(dag)
        self.property_set[self.key] = CircuitMetrics(
            swaps=int(qc.count_ops().get("swap", 0)),
            depth=int(physical_depth(qc)),
            active_gates=int(active_gate_count(qc)),
            size=int(qc.size()),
        )
