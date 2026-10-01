"""Compile-time circuit metrics for the routed program body."""

from __future__ import annotations

from dataclasses import dataclass

from qiskit import QuantumCircuit
from qiskit.circuit import Instruction
from qiskit.converters import circuit_to_dag, dag_to_circuit
from qiskit.dagcircuit import DAGCircuit
from qiskit.transpiler import AnalysisPass, PropertySet

FREE_GATES: frozenset[str] = frozenset({"rz", "u1", "p", "z"})
SYNTHETIC_PREPARATION_LABEL = "dualrail_synthetic_preparation"

# Gate durations (ns) from Liu et al.'s hardware model. We use the reported
# 200 ns beamsplitter-SWAP duration for every beamsplitter rotation because
# Liu et al. do not specify a shorter duration for fractional rotations.
# Free diagonal-Z operations and synthetic preparation placeholders cost zero.
GATE_DURATIONS: dict[str, float] = {
    "joint_herald": 0.0,
    "crz": 500.0,
    "rswap": 200.0,
    "swap": 200.0,
    "x": 200.0,
    "rx": 200.0,
    "sx": 200.0,
}


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


def physical_duration(qc: QuantumCircuit) -> float:
    """Return the Liu-model critical-path duration in nanoseconds."""
    finish: dict = {}
    for node in circuit_to_dag(qc).topological_op_nodes():
        start = max((finish.get(q, 0.0) for q in node.qargs), default=0.0)
        duration = (
            0.0
            if is_synthetic_preparation(node.op)
            else GATE_DURATIONS.get(node.op.name, 0.0)
        )
        for q in node.qargs:
            finish[q] = start + duration
    return max(finish.values(), default=0.0)


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
    duration: float = 0.0
    n_evaluated: int = 1


class RecordCircuitMetrics(AnalysisPass):
    """Publish/refresh ``property_set[key]`` metrics from the current DAG.

    Run at the end of the lowering stage (``key="lowering_circuit_metrics"``:
    semantic content, pre-routing), after the physical routing stage
    (``key="postrouting_circuit_metrics"``: pre-optimization, so the
    routing-inserted delta is exact), and the end of the physical stage (the
    default key, final). Preserves ``n_evaluated`` across refresh if it was set.
    """

    def __init__(self, key: str = "circuit_metrics") -> None:
        """Store the property-set key the metrics are published under."""
        super().__init__()
        self.key = key

    def run(self, dag: DAGCircuit) -> None:
        """Compute ``CircuitMetrics`` for ``dag`` and publish them under ``self.key``."""
        qc = dag_to_circuit(dag)
        existing = self.property_set.get(self.key)
        self.property_set[self.key] = CircuitMetrics(
            swaps=int(qc.count_ops().get("swap", 0)),
            depth=int(physical_depth(qc)),
            active_gates=int(active_gate_count(qc)),
            size=int(qc.size()),
            duration=physical_duration(qc),
            n_evaluated=existing.n_evaluated if existing else 1,
        )
