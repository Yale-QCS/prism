"""Report rail circuits whose noiseless state leaves the one-photon-per-pair space after preparation.

  .venv/bin/python research/rebuttal/wallclock/check.py data/circuits_n8/*_greedy.qpy ...

A circuit passes when, once every pair is prepared, every basis mask carrying
amplitude holds exactly n photons, before and after every instruction.
"""

import sys
from pathlib import Path

import numpy as np
from qiskit import qpy

sys.path[:0] = [str(Path(__file__).resolve().parents[3] / "src"), str(Path(__file__).resolve().parent)]
import sim  # noqa: E402

from marabbecca.utils.metrics import is_synthetic_preparation  # noqa: E402


def leaks(qc) -> list[tuple[int, str, list[int]]]:
    """Return (index, name, rails) for every instruction after which some amplitude has the wrong photon count."""
    live, idle, _ = sim.live_pairs(qc)
    state = sim.CodespaceTrajectories(live, 1, np.random.default_rng(0))
    n = sum(1 for i, ins in enumerate(qc.data) if is_synthetic_preparation(ins.operation) and ins.operation.name == "x" and i not in idle)
    prepared, bad = 0, []
    for i, ins in enumerate(qc.data):
        if ins.operation.name == "barrier" or i in idle:
            continue
        rails = [qc.find_bit(q).index for q in ins.qubits]
        sim.apply_gate(state, ins.operation, rails)
        prepared += is_synthetic_preparation(ins.operation) and ins.operation.name == "x"
        if prepared == n:
            live = np.abs(state.ideal) > 1e-9
            photons = np.array([bin(int(m)).count("1") for m in state.masks[live]])
            if (photons != n).any():
                bad.append((i, ins.operation.name, rails))
    return bad


def main() -> None:
    for path in map(Path, sys.argv[1:]):
        with path.open("rb") as f:
            qc = qpy.load(f)[0]
        bad = leaks(qc)
        if bad:
            print(f"{path.name}: {len(bad)} instructions leave the code space, first {bad[:3]}")
    print(f"checked {len(sys.argv) - 1} circuits")


if __name__ == "__main__":
    main()
