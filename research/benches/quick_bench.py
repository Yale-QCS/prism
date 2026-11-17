"""Smoketest: three-method ladder on a 5-circuit suite at n=8, <60s.

Prints per-strategy ``Σdepth`` / ``≤greedy depth`` / ``Σswaps``; returns raw
rows. Use after lowering-pipeline edits; ``full_bench.py`` for the wider suite.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from functools import partial

from qiskit.transpiler import CouplingMap, PassManager

from marabbecca.encodings import DualRail
from marabbecca.staged_pms import build_pm
from marabbecca.utils.benchmarks import run_suite

PMFactory = Callable[[CouplingMap], PassManager]


def quick_eval(
    strategies: dict[str, PMFactory] | None = None,
    *,
    n_qubits: int = 8,
    topology: CouplingMap | None = None,
    circuits: Iterable[str] = ("qft", "qaoa", "vqe_su2", "modular_adder", "hhl"),
    verbose: bool = True,
) -> dict:
    """Run each strategy over ``circuits`` on a single topology; return rows + summary."""
    if strategies is None:
        strategies = {
            name: partial(build_pm, enc=DualRail, strategy=name)
            for name in ("logical", "greedy", "prism")
        }
    if topology is None:
        n_phys = 2 * n_qubits
        side = math.ceil(math.sqrt(n_phys))
        rows_n = math.ceil(n_phys / side)
        topology = CouplingMap.from_grid(side, rows_n)
        topo_name = f"grid_{side}x{rows_n}"
    else:
        topo_name = "grid"
    suite = [(name, n_qubits) for name in circuits]
    rows = run_suite(
        topologies={topo_name: topology},
        strategies=strategies,
        suite=suite,
        verbose=verbose,
    )

    greedy_depth = {r["circuit"]: r["depth"] for r in rows if r["strategy"] == "greedy"}
    summary: dict[str, dict] = {}
    for strat in strategies:
        srows = [r for r in rows if r["strategy"] == strat]
        wins = (
            sum(
                1
                for r in srows
                if r["circuit"] in greedy_depth
                and r["depth"] <= greedy_depth[r["circuit"]]
            )
            if greedy_depth and strat != "greedy"
            else None
        )
        summary[strat] = {
            "total_swaps": sum(r["swaps"] for r in srows),
            "total_depth": sum(r["depth"] for r in srows),
            "depth_wins_vs_greedy": wins,
            "n_circuits": len(srows),
        }

    if verbose:
        print()
        print(
            f"{'strategy':<14s} {'Σdepth':>8s} {'≤greedy depth':>16s} {'(Σswaps)':>10s}"
        )
        for strat, s in summary.items():
            wins = (
                "-"
                if s["depth_wins_vs_greedy"] is None
                else f"{s['depth_wins_vs_greedy']}/{s['n_circuits']}"
            )
            print(
                f"{strat:<14s} {s['total_depth']:>8d} {wins:>16s} "
                f"{s['total_swaps']:>10d}"
            )
    return {"rows": rows, "summary": summary}


if __name__ == "__main__":
    quick_eval()
