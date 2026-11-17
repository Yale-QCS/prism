"""X09 feasibility probe: ERADO acceptance cross-check on ISA-form compiled circuits.

Runs in a SEPARATE venv (erado pins qiskit-aer-gpu-cu11 on linux; install with
--no-deps + cpu qiskit-aer): see README.md. Circuits stay in the dual-rail
PHYSICAL_ISA (crz/swap/rswap/x/rz); erasure sampling keys on ISA gate names with
duration-faithful per-op probabilities, and translation to Aer's basis happens
only at the execution boundary (RSwapGate carries an exact rxx/ryy definition).
"""

import time

import numpy as np
from qiskit import qpy, transpile
from qiskit_aer import AerSimulator

from erado.frontend import ErasureSimFrontend
from erado.models import ErasureCircuitSampler

DURATIONS = {"crz": 500.0, "rswap": 170.0, "swap": 170.0, "x": 170.0, "rx": 170.0, "sx": 170.0}
GAMMA = 1e-5  # loss rate per ns


class DurationErasureSampler(ErasureCircuitSampler):
    """Per-op erasure probability from the SWS duration model; rz is free."""

    def __init__(self, circuit):
        super().__init__(circuit=circuit, erasure_rate=0.0)
        self._p = np.array(
            [1 - np.exp(-GAMMA * DURATIONS.get(g.name, 0.0)) for g in circuit.data]
        )

    def sample(self, erasure_events=None):
        if erasure_events is None:
            erasure_events = (self._rng.random(self.n_gates()) < self._p).astype(np.int64)
        return super().sample(erasure_events)


class TranspilingBackend:
    """Execution-boundary shim: lower ISA gates (rswap via its definition) for Aer."""

    def __init__(self, backend):
        self._backend = backend

    def run(self, circuits, **kwargs):
        return self._backend.run(
            transpile(circuits, self._backend, optimization_level=0), **kwargs
        )

    def __getattr__(self, name):
        return getattr(self._backend, name)


def main() -> None:
    backend = TranspilingBackend(AerSimulator(method="statevector"))
    shots = 300
    for strat in ("greedy", "prism"):
        with open(f"qft8_{strat}.qpy", "rb") as f:
            qc = qpy.load(f)[0]
        total_ns = sum(DURATIONS.get(g.name, 0.0) for g in qc.data)
        analytic = np.exp(-GAMMA * total_ns)
        DurationErasureSampler.seed(0)
        frontend = ErasureSimFrontend(
            model=DurationErasureSampler(qc),
            false_positive_rate=0.0,
            false_negative_rate=0.0,
        )
        ErasureSimFrontend.seed(0)
        t0 = time.time()
        res = frontend.run(backend, shots, postselect=True)
        print(
            f"{strat}: simulated acceptance={1 - res.rejection_rate:.3f}  "
            f"analytic exp(-G*sum_T)={analytic:.3f}  qubit-time={total_ns:.0f} ns  "
            f"wall={time.time() - t0:.0f}s"
        )


if __name__ == "__main__":
    main()
