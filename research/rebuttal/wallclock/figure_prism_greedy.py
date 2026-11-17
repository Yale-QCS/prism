"""PRISM against Greedy on dual rail across widths: shots per kept shot and duration.

  .venv/bin/python research/rebuttal/wallclock/figure_prism_greedy.py [--widths 8 12]

Both ratios are assumption-free: P_keep is measured in simulation and the duration is
derived from the schedule. Sampling cost is left out (its 1/F^2 model and per-shot
overhead are assumptions; see REDTEAM.md). Points are PRISM/Greedy ratios of geometric
means over workloads of per-workload means over grid, hex_lattice and seeds, with 95%
intervals from 1000 seed resamples paired between the arms. Coupler loss 2e-3.
"""

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

import lusca  # noqa: F401
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
OUT = HERE / "data/legacy/figures"
OUT.mkdir(exist_ok=True)
TOPOLOGIES = ("grid", "hex_lattice")
RATIOS = {
    "Shots run per kept shot, 1 / P_keep": (lambda r: 1 / r["p_keep"], "#3b6ea5", "o"),
    "Duration": (lambda r: r["duration_us"], "#8a9096", "s"),
}
INK, MUTED, GRIDC = "#2b2b2b", "#6b6b6b", "#e3e3e3"

parser = argparse.ArgumentParser()
parser.add_argument("--widths", type=int, nargs="+", default=[8, 12])
args = parser.parse_args()
rng = np.random.default_rng(0)


def ratio_stats(width):
    rows = defaultdict(lambda: defaultdict(list))  # (arm, circuit) -> seed -> rows
    for line in (HERE / "data/legacy" / f"rows_n{width}_loss0.002.jsonl").open():
        r = json.loads(line)
        if r["topology"] in TOPOLOGIES and r["arm"] in ("prism", "greedy"):
            rows[(r["arm"], r["circuit"])][r["seed"]].append(r)
    circuits = sorted({c for _, c in rows})
    seeds = sorted({s for per in rows.values() for s in per})
    picks = np.vstack([np.arange(len(seeds))[None, :], rng.integers(0, len(seeds), (1000, len(seeds)))])
    out = {}
    for name, (f, _, _) in RATIOS.items():
        v = {a: np.array([[np.mean([f(x) for x in rows[(a, c)][s]]) for s in seeds] for c in circuits]) for a in ("prism", "greedy")}
        ln = np.log(v["prism"][:, picks].mean(axis=2)).mean(axis=0) - np.log(v["greedy"][:, picks].mean(axis=2)).mean(axis=0)
        out[name] = (math.exp(ln[0]), *np.exp(np.percentile(ln[1:], [2.5, 97.5])))
    return out


widths = args.widths
stats = {w: ratio_stats(w) for w in widths}

with plt.style.context("lusca"):
    plt.rcParams.update({"font.size": 7.0, "axes.labelsize": 7.0, "xtick.labelsize": 6.4, "ytick.labelsize": 6.4, "pdf.fonttype": 42,
                         "axes.edgecolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED, "axes.labelcolor": INK})
    fig, ax = plt.subplots(figsize=(3.4, 2.2))
    for k, (name, (_, col, mark)) in enumerate(RATIOS.items()):
        xs = [w + (k - 0.5) * 0.3 for w in widths]
        pts = [stats[w][name] for w in widths]
        ax.errorbar(xs, [p[0] for p in pts], yerr=[[p[0] - p[1] for p in pts], [p[2] - p[0] for p in pts]], color=col, marker=mark,
                    markersize=3.8, lw=1.0, elinewidth=0.7, capsize=1.5, label=name, zorder=3)
    ax.axhline(1, color=MUTED, lw=0.7, zorder=1)
    ax.set_xticks(widths)
    ax.set_xlim(widths[0] - 1.5, widths[-1] + 1.5)
    ax.set_xlabel("Logical qubits")
    ax.set_ylabel("PRISM / Greedy")
    ax.grid(color=GRIDC, lw=0.5, zorder=0)
    ax.legend(frameon=False, fontsize=5.8, loc="lower left")
    fig.tight_layout()
    fig.savefig(OUT / "p1_prism_greedy.png", dpi=300)
    fig.savefig(OUT / "p1_prism_greedy.pdf")

for w in widths:
    print(w, {k: tuple(round(float(v), 4) for v in vals) for k, vals in stats[w].items()})
