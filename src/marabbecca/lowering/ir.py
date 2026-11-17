"""``LoweredOp``: an ``Operation`` carrying candidate physical realizations.

Lives in a ``DAGCircuit`` over physical wires; its ``num_qubits`` is the union
of wires any realization could touch (for dependency tracking). ``commit``
picks a realization and substitutes it via ``substitute_node_with_dag``.
"""

from __future__ import annotations

from collections.abc import Sequence

from qiskit.circuit import Operation, QuantumCircuit


class LoweredOp(Operation):
    """A logical op paired with its candidate physical realizations."""

    def __init__(
        self,
        realizations: Sequence[QuantumCircuit],
        *,
        default_index: int = 0,
        name: str = "lowered",
    ) -> None:
        """Store ``realizations`` and validate their widths and ``default_index``."""
        reals = tuple(realizations)
        if not reals:
            raise ValueError("LoweredOp must have at least one realization")
        widths = {qc.num_qubits for qc in reals}
        if len(widths) != 1:
            raise ValueError(
                f"All realizations must have identical num_qubits; got {sorted(widths)}"
            )
        clwidths = {qc.num_clbits for qc in reals}
        if len(clwidths) != 1:
            raise ValueError(
                f"All realizations must have identical num_clbits; got {sorted(clwidths)}"
            )
        if not 0 <= default_index < len(reals):
            raise ValueError(
                f"default_index {default_index} out of range for {len(reals)} realizations"
            )
        self.realizations = reals
        self.default_index = default_index
        self._name = name
        self._num_qubits = reals[0].num_qubits
        self._num_clbits = reals[0].num_clbits

    @classmethod
    def fixed(cls, qc: QuantumCircuit, *, name: str = "lowered") -> LoweredOp:
        """Single-realization ``LoweredOp``."""
        return cls((qc,), name=name)

    @classmethod
    def decision(
        cls,
        candidates: Sequence[QuantumCircuit],
        *,
        default_index: int = 0,
        name: str = "lowered",
    ) -> LoweredOp:
        """Multi-realization ``LoweredOp`` with the encoding's canonical pick."""
        cands = tuple(candidates)
        if len(cands) < 2:
            raise ValueError(
                f"decision() expects 2+ candidates; got {len(cands)} — use fixed() instead"
            )
        return cls(cands, default_index=default_index, name=name)

    @property
    def name(self) -> str:
        """Operation name."""
        return self._name

    @property
    def num_qubits(self) -> int:
        """Number of physical wires the op spans."""
        return self._num_qubits

    @property
    def num_clbits(self) -> int:
        """Number of classical bits the op spans."""
        return self._num_clbits

    @property
    def is_fixed(self) -> bool:
        """Whether the op has exactly one realization."""
        return len(self.realizations) == 1

    @property
    def is_decision(self) -> bool:
        """Whether the op has two or more realizations."""
        return len(self.realizations) > 1
