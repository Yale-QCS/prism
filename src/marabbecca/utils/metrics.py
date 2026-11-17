"""Compile-time circuit metrics for the routed program body."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from qiskit import QuantumCircuit
from qiskit.converters import circuit_to_dag, dag_to_circuit
from qiskit.dagcircuit import DAGCircuit
from qiskit.transpiler import AnalysisPass

if TYPE_CHECKING:
    from qiskit.circuit import Operation

FREE_GATES: frozenset[str] = frozenset({"rz", "u1", "p", "z"})
SYNTHETIC_PREPARATION_LABEL = "dualrail_synthetic_preparation"

# Gate durations (ns) from Mehta et al. (arXiv:2503.10935). We use the reported
# 200 ns beamsplitter-SWAP duration for every beamsplitter rotation because
# Mehta et al. do not specify a shorter duration for fractional rotations.
# Free diagonal-Z operations and synthetic preparation placeholders cost zero.
# The joint erasure check is from another device, de Graaf et al. (arXiv:2406.14621):
# 1.82 us pulse, 0.12 us beamsplitter ramp and an assumed 1 us readout.
GATE_DURATIONS: dict[str, float] = {
    "joint_herald": 0.0,
    "joint_check": 2940.0,
    "crz": 500.0,
    "rswap": 200.0,
    "swap": 200.0,
    "x": 200.0,
    "rx": 200.0,
    "sx": 200.0,
}


def is_synthetic_preparation(operation: Operation) -> bool:
    """Return whether an operation is a routing-only preparation placeholder."""
    return (
        operation.name == "joint_herald"
        or getattr(operation, "label", None) == SYNTHETIC_PREPARATION_LABEL
    )


def is_free(operation: Operation) -> bool:
    """Return whether an operation costs no time: diagonal-Z gates and preparation placeholders."""
    return operation.name in FREE_GATES or is_synthetic_preparation(operation)


def physical_depth(qc: QuantumCircuit) -> int:
    """Return program-body depth in non-free physical operations."""
    return qc.depth(
        filter_function=lambda instruction: (
            instruction.operation.name not in FREE_GATES
            and not is_synthetic_preparation(instruction.operation)
        )
    )


def physical_duration(qc: QuantumCircuit) -> float:
    """Return the device-model critical-path duration in nanoseconds."""
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


# Dual-rail cavity device of Mehta et al. (arXiv:2503.10935), in microseconds.
# The two characterized transmon roles (control, target) are averaged by rate
# into one ISA-independent hardware point. The target-role R_SWAP error is the
# Fig. 5 caption's 1.08(1)e-4; Table III prints 1.08e-5, a typo.
T1_CAVITY_US = 500.0
SWS_ERROR = 2.8e-6 + 3.9e-4 + 0.5e-6 + 1.1e-4
DEPHASING_RATE_PER_US = (1.0 / 4_000.0 + 1.0 / 4_800.0) / 2
BIT_FLIP_RATE_PER_US = (1.0 / 520_000.0 + 1.0 / 1_100_000.0) / 2
RSWAP_ERROR = (9.0e-5 + 1.08e-4) / 2
BEAMSPLITTER_OPS = ("rswap", "rx", "sx", "swap")


def device_success(
    n_logical: int,
    duration_ns: float,
    op_counts: Mapping[str, int],
    *,
    rswap_error: float = RSWAP_ERROR,
) -> tuple[float, float]:
    """Return the device-model keep probability and conditional fidelity.

    Every logical qubit's cavity decays for the whole program and a terminal
    loss check discards lost shots, so ``P_keep = exp(-n t / T1_cavity)``.
    Kept shots dephase and bit-flip over the same exposure, and each SWS
    (``crz``) and beamsplitter operation fails independently. ``op_counts``
    are program-body counts (no synthetic preparation).
    """
    exposure_us = n_logical * (duration_ns / 1_000.0)
    n_sws = int(op_counts.get("crz", 0))
    n_beamsplitter = sum(int(op_counts.get(name, 0)) for name in BEAMSPLITTER_OPS)
    log_fidelity = (
        -exposure_us * (DEPHASING_RATE_PER_US + BIT_FLIP_RATE_PER_US)
        + n_sws * math.log1p(-SWS_ERROR)
        + n_beamsplitter * math.log1p(-rswap_error)
    )
    return math.exp(-exposure_us / T1_CAVITY_US), math.exp(log_fidelity)


def pair_exposure(qc: QuantumCircuit) -> tuple[float, dict[str, int]]:
    """Summed idle time (us) of the live rail pairs and their pair-touch counts by op and role (P_keep's exposure terms)."""
    rail = {q: i for i, q in enumerate(qc.qubits)}
    ops = [
        (ins.operation, [rail[q] for q in ins.qubits])
        for ins in qc.data
        if ins.operation.name != "barrier"
    ]
    # Pair identity: the two contents a joint herald joins, followed through swaps. A pair is live
    # if any op other than swap or a preparation touches it.
    where, parent, used = list(range(qc.num_qubits)), list(range(qc.num_qubits)), set()

    def root(r: int) -> int:
        while parent[r] != r:
            parent[r] = parent[parent[r]]
            r = parent[r]
        return r

    for op, rails in ops:
        if op.name == "swap":
            a, b = rails
            where[a], where[b] = where[b], where[a]
        elif op.name == "joint_herald":
            parent[root(where[rails[0]])] = root(where[rails[1]])
        elif not is_synthetic_preparation(op):
            used.update(where[r] for r in rails)
    live = {root(r) for r in used}
    where, clock = list(range(qc.num_qubits)), [0.0] * qc.num_qubits
    busy, touches = {p: [] for p in live}, {}
    for op, rails in ops:
        if is_synthetic_preparation(op) and root(where[rails[0]]) not in live:
            continue  # an idle pair's preparation is not scheduled
        start = max(clock[r] for r in rails)
        duration = (
            0.0
            if is_synthetic_preparation(op)
            else GATE_DURATIONS.get(op.name, 0.0) / 1_000.0
        )
        if duration:
            roles = ("control", "target") if op.name == "crz" else ("pair", "pair")
            hit = {}
            for r, role in zip(rails, roles):
                if root(where[r]) in live:
                    hit.setdefault(root(where[r]), role)
            for p, role in hit.items():
                busy[p].append((start, start + duration))
                key = f"{op.name}_{role}" if op.name == "crz" else op.name
                touches[key] = touches.get(key, 0) + 1
        if op.name == "swap":
            a, b = rails
            where[a], where[b] = where[b], where[a]
        for r in rails:
            clock[r] = start + duration
    end = max(clock, default=0.0)
    idle = 0.0
    for intervals in busy.values():
        covered = reach = 0.0
        for a, b in sorted(intervals):
            covered += max(0.0, b - max(a, reach))
            reach = max(reach, b)
        idle += end - covered
    return idle, touches


def active_gate_count(qc: QuantumCircuit) -> int:
    """Return the number of non-free program-body operations."""
    return sum(
        1
        for instruction in qc.data
        if instruction.operation.name not in FREE_GATES
        and not is_synthetic_preparation(instruction.operation)
    )


@dataclass(frozen=True)
class CircuitMetrics:
    """Standardized circuit metrics published to ``property_set["circuit_metrics"]``."""

    swaps: int
    depth: int
    active_gates: int
    size: int
    duration: float = 0.0
    n_evaluated: int = 1
    # Every live pair is exposed from 0 to the schedule end; idle time is that span minus its busy intervals.
    pair_idle_us: float = 0.0
    # Keys: crz_control, crz_target, and each beamsplitter op (one per live pair it touches).
    pair_touches: dict[str, int] = field(default_factory=dict)


class RecordCircuitMetrics(AnalysisPass):
    """Publish ``property_set["circuit_metrics"]`` from the final physical DAG.

    Preserves ``n_evaluated`` across refresh if it was set.
    """

    def run(self, dag: DAGCircuit) -> None:
        """Compute metrics for ``dag`` and publish them to ``property_set["circuit_metrics"]``."""
        qc = dag_to_circuit(dag)
        existing = self.property_set.get("circuit_metrics")
        pair_idle_us, pair_touches = pair_exposure(qc)
        self.property_set["circuit_metrics"] = CircuitMetrics(
            swaps=int(qc.count_ops().get("swap", 0)),
            depth=int(physical_depth(qc)),
            active_gates=int(active_gate_count(qc)),
            size=int(qc.size()),
            duration=physical_duration(qc),
            n_evaluated=existing.n_evaluated if existing else 1,
            pair_idle_us=pair_idle_us,
            pair_touches=pair_touches,
        )
