"""Broader regression check: three-method ladder on the full standard suite.

Slower than ``quick_bench.py`` (~30-60s vs 3s) but catches regressions on
circuits the smoketest doesn't exercise (e.g., ``qwalk``, ``grover``,
``randomcircuit``, adders, multipliers).

Use after stage-completion edits; ``quick_bench.py`` for fast iteration.

Topology is sized for 2*(num_qubits + 1) rails so kg24-ancilla circuits
(grover, qwalk) fit.
"""

from __future__ import annotations

import math
import sys
from functools import partial

from qiskit.transpiler import CouplingMap

from marabbecca.encodings import DualRail
from marabbecca.staged_pms import build_pm
from marabbecca.utils.benchmarks import CIRCUIT_CLASS, run_suite


def main(n_qubits: int = 8) -> None:
    """Run the three-method ladder over every circuit in ``CIRCUIT_CLASS`` at ``n_qubits``."""
    n_phys = 2 * (n_qubits + 1)
    side = math.ceil(math.sqrt(n_phys))
    rows = math.ceil(n_phys / side)
    cols = side
    topology = CouplingMap.from_grid(rows, cols)
    suite = [(name, n_qubits) for name in CIRCUIT_CLASS]
    strategies = {
        name: partial(build_pm, enc=DualRail, strategy=name)
        for name in ("logical", "greedy", "prism")
    }

    rows_out = run_suite(
        topologies={f"grid_{rows}x{cols}": topology},
        strategies=strategies,
        suite=suite,
        verbose=True,
    )

    greedy_depth = {
        r["circuit"]: r["depth"] for r in rows_out if r["strategy"] == "greedy"
    }
    print()
    print(f"{'strategy':<14s} {'Σdepth':>8s} {'≤greedy depth':>16s} {'(Σswaps)':>10s}")
    for strat in strategies:
        srows = [r for r in rows_out if r["strategy"] == strat]
        wins = (
            sum(
                1
                for r in srows
                if r["circuit"] in greedy_depth
                and r["depth"] <= greedy_depth[r["circuit"]]
            )
            if strat != "greedy"
            else None
        )
        wins_str = "-" if wins is None else f"{wins}/{len(srows)}"
        total_depth = sum(r["depth"] for r in srows)
        total_swaps = sum(r["swaps"] for r in srows)
        print(f"{strat:<14s} {total_depth:>8d} {wins_str:>16s} {total_swaps:>10d}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    main(n_qubits=n)
