"""Opaque two-rail operations: the routing-only preparation herald and the timed erasure check."""

from __future__ import annotations

from qiskit.circuit import Instruction


class JointHeraldGate(Instruction):
    """Two-rail connectivity placeholder excluded from program-body metrics.

    Opaque (no definition, not a unitary): it only requires the two rails to
    be adjacent, and optimization passes must not fuse gates through it.
    """

    def __init__(self) -> None:
        """Create the routing-only joint-herald operation."""
        super().__init__("joint_herald", 2, 0, [])


class ErasureCheckGate(Instruction):
    """Logical mid-circuit erasure check of one encoded qubit (opaque, not a unitary)."""

    def __init__(self) -> None:
        """Create the logical erasure-check operation."""
        super().__init__("erasure_check", 1, 0, [])


class JointCheckGate(Instruction):
    """Timed joint erasure check of one rail pair; requires the two rails to be adjacent."""

    def __init__(self) -> None:
        """Create the two-rail joint erasure-check operation."""
        super().__init__("joint_check", 2, 0, [])
