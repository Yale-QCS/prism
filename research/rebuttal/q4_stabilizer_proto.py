"""Q4 prototype: route a rep-code stabilization schedule, greedy vs prism.

Two circuit variants: `reuse` measures+resets each ancilla between rounds
(faithful schedule, needs mid-circuit measure through the pipeline); `fresh`
allocates new ancillas per round (coherent-only fallback).
"""

from __future__ import annotations

import math
import sys

from qiskit import QuantumCircuit
from qiskit.transpiler import CouplingMap

from marabbecca.encodings import DualRail
from marabbecca.staged_pms import build_pm


def rep_code_reuse(d: int, rounds: int) -> QuantumCircuit:
    n = 2 * d - 1
    qc = QuantumCircuit(n, (d - 1) * rounds)
    data, anc = list(range(d)), list(range(d, n))
    for r in range(rounds):
        for a in anc:
            qc.h(a)
        for i, a in enumerate(anc):
            qc.crz(math.pi, data[i], a)
        for i, a in enumerate(anc):
            qc.crz(math.pi, data[i + 1], a)
        for i, a in enumerate(anc):
            qc.h(a)
            qc.measure(a, r * (d - 1) + i)
        # DualRail.reset is unimplemented; without it the ancilla carries its
        # post-measurement state into the next round. Routing structure (the
        # meetings and CZ ladders) is identical to the reset schedule.
    return qc


def rep_code_fresh(d: int, rounds: int) -> QuantumCircuit:
    n = d + (d - 1) * rounds
    qc = QuantumCircuit(n)
    data = list(range(d))
    for r in range(rounds):
        anc = [d + r * (d - 1) + i for i in range(d - 1)]
        for a in anc:
            qc.h(a)
        for i, a in enumerate(anc):
            qc.crz(math.pi, data[i], a)
        for i, a in enumerate(anc):
            qc.crz(math.pi, data[i + 1], a)
        for a in anc:
            qc.h(a)
    return qc


def surface_d3(rounds: int) -> QuantumCircuit:
    """Rotated d=3 surface code: 9 data (3x3 row-major) + 8 ancillas."""
    x_checks = [(0, 1, 3, 4), (4, 5, 7, 8), (2, 5), (3, 6)]
    z_checks = [(1, 2, 4, 5), (3, 4, 6, 7), (0, 1), (7, 8)]
    n = 9 + len(x_checks) + len(z_checks)
    qc = QuantumCircuit(n, 8 * rounds)
    x_anc = list(range(9, 9 + len(x_checks)))
    z_anc = list(range(13, 13 + len(z_checks)))
    for r in range(rounds):
        for a in x_anc + z_anc:
            qc.h(a)
        for step in range(4):
            for a, ds in zip(x_anc, x_checks):
                if step < len(ds):
                    qc.cx(a, ds[step])
            for a, ds in zip(z_anc, z_checks):
                if step < len(ds):
                    qc.crz(math.pi, ds[step], a)
        for i, a in enumerate(x_anc + z_anc):
            qc.h(a)
            qc.measure(a, r * 8 + i)
    return qc


def grid_for(n_logical: int) -> tuple[str, CouplingMap]:
    n_phys = 2 * n_logical
    side = math.ceil(math.sqrt(n_phys))
    rows = math.ceil(n_phys / side)
    return f"grid_{side}x{rows}", CouplingMap.from_grid(side, rows)


def run(qc: QuantumCircuit, label: str, seeds: range) -> None:
    topo_name, cmap = grid_for(qc.num_qubits)
    print(f"\n== {label}: n={qc.num_qubits} logical on {topo_name}, "
          f"{qc.count_ops()} ==")
    print(f"{'seed':>4s} {'greedy sw/dep':>14s} {'prism sw/dep':>14s}")
    totals = {"greedy": [0, 0], "prism": [0, 0]}
    for seed in seeds:
        row = {}
        for strat in ("greedy", "prism"):
            pm = build_pm(cmap, enc=DualRail, strategy=strat, seed=seed)
            pm.run(qc)
            m = pm.property_set["circuit_metrics"]
            row[strat] = (m.swaps, m.depth)
            totals[strat][0] += m.swaps
            totals[strat][1] += m.depth
        print(f"{seed:>4d} {row['greedy'][0]:>6d}/{row['greedy'][1]:<6d}"
              f" {row['prism'][0]:>6d}/{row['prism'][1]:<6d}")
    g, p = totals["greedy"], totals["prism"]
    dsw = 100 * (g[0] - p[0]) / g[0] if g[0] else float("nan")
    ddep = 100 * (g[1] - p[1]) / g[1] if g[1] else float("nan")
    print(f" sum {g[0]:>6d}/{g[1]:<6d} {p[0]:>6d}/{p[1]:<6d}"
          f"   swaps -{dsw:.1f}%  depth -{ddep:.1f}%")


if __name__ == "__main__":
    variant = sys.argv[1] if len(sys.argv) > 1 else "fresh"
    seeds = range(5)
    if variant == "reuse":
        run(rep_code_reuse(3, 3), "rep3 x3 rounds (ancilla reuse)", seeds)
    elif variant == "fresh":
        run(rep_code_fresh(3, 3), "rep3 x3 rounds (fresh ancillas)", seeds)
    elif variant == "surface":
        run(surface_d3(2), "surface d3 x2 rounds", range(3))
    else:
        raise NotImplementedError(variant)
