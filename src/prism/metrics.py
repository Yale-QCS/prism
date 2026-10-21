"""``CircuitMetrics``: the SWAP count and depth prism's routing ranks routes by."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from qiskit.circuit import Operation, QuantumCircuit

_FREE_GATES = frozenset({"rz", "u1", "p", "z", "initialize"})


def only_ops(operation: Operation, names: Collection[str]) -> bool:
    """``operation`` is in ``names``, or is control flow holding only such operations."""
    if operation.name in names:
        return True
    blocks = getattr(operation, "blocks", None)
    return blocks is not None and all(
        only_ops(instr.operation, names) for block in blocks for instr in block.data
    )


def is_free(operation: Operation) -> bool:
    """Z rotations and preparation take no time; depth does not count them."""
    return only_ops(operation, _FREE_GATES)


@dataclass(frozen=True)
class CircuitMetrics:
    """SWAPs, depth and gate counts; ``depth`` and ``active_gates`` skip free gates."""

    swaps: int
    depth: int
    active_gates: int
    size: int

    @classmethod
    def of(cls, qc: QuantumCircuit) -> CircuitMetrics:
        return cls(
            swaps=qc.count_ops().get("swap", 0),
            depth=qc.depth(lambda instr: not is_free(instr.operation)),
            active_gates=sum(not is_free(instr.operation) for instr in qc.data),
            size=qc.size(),
        )
