"""Trade-off figure (reviewer A-Q3): PRISM's reduction against Greedy when both select routes by the same objective, n = 16.

Usage: .venv/bin/python research/rebuttal/tradeoff/objectives_bars.py  -> figures/objectives_bars.{pdf,png}
"""
import json
from collections import defaultdict
from pathlib import Path

import lusca  # noqa: F401
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

DATA, OUT = Path(__file__).parent / "data", Path(__file__).parent / "figures"
OBJ = {"swaps": "SWAPs", "depth": "Depth", "duration": "Duration", "error": "Infidelity"}
METRICS = {"router_inserted_swaps": "(a) Routing SWAPs", "physical_depth": "(b) Physical depth", "duration_ns": "(c) Duration"}
TOPO = {"grid": ("Square grid", "#4c78a8"), "hex_lattice": ("Hexagonal lattice", "#d9902f"), "heavy_hex": ("Heavy-hex", "#7f6aa8")}

rows = defaultdict(lambda: defaultdict(dict))  # (objective, topology, arm) -> seed -> circuit -> row
for o in OBJ:
    for r in map(json.loads, open(DATA / f"w16_{o}.jsonl")):
        rows[(o, r["topology_name"], r["strategy"])][r["outer_seed"]][r["circuit_name"]] = r


def sums(o, t, a, m):
    """Per-seed suite totals of metric m."""
    by_seed = rows[(o, t, a)]
    return np.array([sum(row[m] for row in by_seed[s].values()) for s in sorted(by_seed)], float)


picks = np.random.default_rng(0).integers(0, 5, (2000, 5))  # paired seed resamples
OUT.mkdir(exist_ok=True)
with plt.style.context("lusca"):
    plt.rcParams.update({"font.size": 6.4, "axes.labelsize": 6.6, "xtick.labelsize": 6.0, "ytick.labelsize": 6.0, "pdf.fonttype": 42})
    fig, axes = plt.subplots(1, 3, figsize=(7.0, 1.6), sharey=False, gridspec_kw={"wspace": 0.18})
    x = np.arange(len(OBJ))
    width = 0.26
    for ax, (m, title) in zip(axes, METRICS.items()):
        for k, (t, (label, color)) in enumerate(TOPO.items()):
            vals, lo, hi = [], [], []
            for o in OBJ:
                g, p = sums(o, t, "greedy", m), sums(o, t, "prism", m)
                vals.append(100 * (1 - p.sum() / g.sum()))
                boot = 100 * (1 - p[picks].sum(1) / g[picks].sum(1))
                lo.append(np.percentile(boot, 2.5))
                hi.append(np.percentile(boot, 97.5))
            vals, lo, hi = map(np.array, (vals, lo, hi))
            ax.bar(x + (k - 1) * width, vals, width, color=color, label=label, zorder=3)
            ax.errorbar(x + (k - 1) * width, vals, yerr=(vals - lo, hi - vals), fmt="none", ecolor="#303030", elinewidth=0.5, capsize=1.2, zorder=4)
            print(m, t, [f"{v:.1f} [{a:.1f}, {b:.1f}]" for v, a, b in zip(vals, lo, hi)])
        ax.set_title(title, loc="left", fontsize=7.0)
        ax.set_xticks(x, list(OBJ.values()))
        ax.set_ylim(0, None)
        ax.grid(axis="y", color="#e1e1e1", linewidth=0.45, zorder=0)
        ax.set_axisbelow(True)
        ax.tick_params(top=False, right=False)
    axes[0].set_ylabel("PRISM reduction\nvs. Greedy (%)")
    fig.supxlabel("Route-selection objective, the same for both compilers", fontsize=6.6, y=0.0)
    axes[0].legend(frameon=False, fontsize=5.8, loc="upper left", bbox_to_anchor=(0.0, 1.36), ncol=3, columnspacing=1.0, handlelength=1.2)
    fig.subplots_adjust(left=0.075, right=0.995, bottom=0.2, top=0.8)
    fig.savefig(OUT / "objectives_bars.pdf")
    fig.savefig(OUT / "objectives_bars.png", dpi=300)
