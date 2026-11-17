"""Trade-off figure (reviewer A-Q3): SWAPs against duration at n = 16 when both compilers select routes by SWAP count and by duration; one column, broken SWAP axis.

Depth- and infidelity-selected routes land within 0.02 of the duration-selected point on both axes (printed below), so the figure shows the two ends.
Usage: .venv/bin/python research/rebuttal/tradeoff/pareto.py  -> figures/pareto.{pdf,png}
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
OBJ = ("swaps", "depth", "duration", "error")
ARM = {"greedy": ("Greedy", "#d69b32"), "prism": ("PRISM", "#39877f")}
TOPO = {"grid": ("Square grid", "o"), "hex_lattice": ("Hexagonal lattice", "s"), "heavy_hex": ("Heavy-hex", "^")}
METRICS = ("router_inserted_swaps", "duration_ns")

rows = defaultdict(lambda: defaultdict(dict))  # (objective, topology, arm) -> seed -> circuit -> row
for o in OBJ:
    for r in map(json.loads, open(DATA / f"w16_{o}.jsonl")):
        rows[(o, r["topology_name"], r["strategy"])][r["outer_seed"]][r["circuit_name"]] = r


def totals(o, t, a):
    """(seeds, metrics) array of suite sums per seed."""
    by_seed = rows[(o, t, a)]
    return np.array([[sum(by_seed[s][c][m] for c in by_seed[s]) for m in METRICS] for s in sorted(by_seed)], float)


pts = {(t, a, o): totals(o, t, a).sum(0) / totals("duration", t, "greedy").sum(0) for t in TOPO for a in ARM for o in OBJ}
for (t, a, o), p in pts.items():
    if o in ("depth", "error"):
        print(t, a, o, "distance from duration point", np.round(np.abs(p - pts[(t, a, "duration")]).max(), 3))

xs = {a: [pts[(t, a, o)][0] for t in TOPO for o in ("swaps", "duration")] for a in ARM}
ys = [pts[(t, a, o)][1] for t in TOPO for a in ARM for o in ("swaps", "duration")]
OUT.mkdir(exist_ok=True)
with plt.style.context("lusca"):
    plt.rcParams.update({"font.size": 7.0, "axes.labelsize": 7.2, "xtick.labelsize": 6.5, "ytick.labelsize": 6.5, "legend.fontsize": 6.2, "pdf.fonttype": 42})
    fig, (axl, axr) = plt.subplots(1, 2, figsize=(3.35, 2.45), sharey=True,
                                   gridspec_kw={"width_ratios": [np.ptp(xs["prism"]) + 0.03, np.ptp(xs["greedy"]) + 0.03], "wspace": 0.06})
    for ax, a in ((axl, "prism"), (axr, "greedy")):
        color = ARM[a][1]
        for t, (_, marker) in TOPO.items():
            (x0, y0), (x1, y1) = pts[(t, a, "swaps")], pts[(t, a, "duration")]
            ax.annotate("", (x1, y1), (x0, y0), arrowprops={"arrowstyle": "-|>", "color": color, "lw": 0.9, "shrinkA": 3.5, "shrinkB": 3.5, "mutation_scale": 6})
            ax.plot(x0, y0, marker=marker, ms=4.6, mfc="white", mec=color, mew=1.1, ls="", zorder=3)
            ax.plot(x1, y1, marker=marker, ms=4.6, mfc=color, mec=color, mew=1.1, ls="", zorder=3)
        ax.set_xlim(min(xs[a]) - 0.015, max(xs[a]) + 0.015)
        ax.grid(color="#dedede", lw=0.5, zorder=0)
        ax.set_title(ARM[a][0], loc="left", fontsize=7.3, color=color)
    axl.set_ylim(min(ys) - 0.03, max(ys) + 0.03)
    axl.set_ylabel("Duration\n(relative to Greedy)")
    axr.tick_params(left=False)
    axl.spines["right"].set_visible(False)
    axr.spines["left"].set_visible(False)
    for ax, x in ((axl, 1), (axr, 0)):
        for y in (0, 1):
            ax.plot([x - 0.02, x + 0.02], [y - 0.025, y + 0.025], transform=ax.transAxes, color="black", lw=0.7, clip_on=False)
    fig.supxlabel("Routing SWAPs (relative to Greedy)", fontsize=7.2, y=0.02)
    handles = [plt.Line2D([], [], ls="", marker=m, ms=4.2, mfc="#7a7a7a", mec="#7a7a7a", label=n) for n, m in TOPO.values()]
    handles += [plt.Line2D([], [], ls="", marker="o", ms=4.2, mfc="white", mec="#7a7a7a", mew=1.1, label="Selected by SWAPs"),
                plt.Line2D([], [], ls="", marker="o", ms=4.2, mfc="#7a7a7a", mec="#7a7a7a", label="Selected by duration")]
    fig.legend(handles=handles, loc="upper center", ncol=2, frameon=False, bbox_to_anchor=(0.56, 1.0), handletextpad=0.2, columnspacing=1.6)
    fig.subplots_adjust(left=0.17, right=0.98, top=0.72, bottom=0.19)
    fig.savefig(OUT / "pareto.pdf")
    fig.savefig(OUT / "pareto.png", dpi=300)
