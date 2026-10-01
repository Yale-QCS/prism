"""``RSwapGate``: fractional-power SWAP; ``RSwapGate(θ) ≡ SwapGate().power(θ/π)``."""

from __future__ import annotations

import numpy as np
from qiskit.circuit import Gate, ParameterExpression


class RSwapGate(Gate):
    """Fractional SWAP; exactly ``SwapGate().power(theta/pi)``."""

    def __init__(self, theta: float | ParameterExpression) -> None:
        """Create an rswap gate with angle ``theta``."""
        super().__init__("rswap", 2, [theta])

    def __array__(
        self, dtype: np.dtype | None = None, copy: bool | None = None
    ) -> np.ndarray:
        theta = float(self.params[0])
        p = np.exp(1j * theta / 2)
        c, s = np.cos(theta / 2), np.sin(theta / 2)
        return np.array(
            [
                [1, 0, 0, 0],
                [0, p * c, -1j * p * s, 0],
                [0, -1j * p * s, p * c, 0],
                [0, 0, 0, 1],
            ],
            dtype=dtype or complex,
        )

    def _define(self) -> None:
        """Exact standard-gate form (execution/simulation boundary only).

        SWAP^(θ/π) = e^{iθ/4}·rxx(θ/2)·ryy(θ/2)·rzz(θ/2).
        """
        from qiskit.circuit import QuantumCircuit

        theta = self.params[0]
        qc = QuantumCircuit(2, global_phase=theta / 4)
        qc.rxx(theta / 2, 0, 1)
        qc.ryy(theta / 2, 0, 1)
        qc.rzz(theta / 2, 0, 1)
        self.definition = qc
