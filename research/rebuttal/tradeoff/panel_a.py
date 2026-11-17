"""Route-selection objective study: SWAPs against duration at n = 16, every topology normalized to Greedy's error-selected route.

Usage: .venv/bin/python research/rebuttal/tradeoff/panel_a.py  -> figures/panel_a.{pdf,png}
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
G, P = "greedy", "prism"
COL = {G: "#d69b32", P: "#39877f"}
NAME = {G: "Greedy", P: "PRISM"}
TOPO = {"grid": ("Grid", "o", "-"), "hex_lattice": ("Hex", "^", "--"), "heavy_hex": ("Heavy-hex", "s", ":")}
INK, MUTED, GRIDC = "#2b2b2b", "#6b6b6b", "#e3e3e3"
METRICS = ("router_inserted_swaps", "duration_ns")

rows = defaultdict(lambda: defaultdict(dict))  # (objective, topology, arm) -> seed -> circuit -> row
for o in OBJ:
    for r in map(json.loads, open(DATA / f"w16_{o}.jsonl")):
        rows[(o, r["topology_name"], r["strategy"])][r["outer_seed"]][r["circuit_name"]] = r


def totals(o, t, a):
    """(seeds, metrics) array of suite sums per seed."""
    by_seed = rows[(o, t, a)]
    return np.array([[sum(by_seed[s][c][m] for c in by_seed[s]) for m in METRICS] for s in sorted(by_seed)], float)


picks = np.random.default_rng(0).integers(0, 5, (2000, 5))
OUT.mkdir(exist_ok=True)
with plt.style.context("lusca"):
    plt.rcParams.update({"font.size": 6.4, "axes.labelsize": 6.8, "xtick.labelsize": 6.0, "ytick.labelsize": 6.0, "pdf.fonttype": 42,
                         "axes.edgecolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED, "axes.labelcolor": INK})
    fig, ax = plt.subplots(figsize=(3.4, 2.4))
    report = {}
    for t, (label, marker, ls) in TOPO.items():
        ref = totals("error", t, G)  # Greedy's error-selected point is (1, 1) on every topology
        for a in (G, P):
            pts = {}
            for o in OBJ:
                tot = totals(o, t, a)
                mean = tot.sum(0) / ref.sum(0)
                ci = np.percentile(tot[picks].sum(1) / ref[picks].sum(1), [2.5, 97.5], axis=0)  # paired seed resample
                pts[o] = (mean, ci)
            order = sorted(OBJ, key=lambda o: pts[o][0][0])
            ax.plot([pts[o][0][0] for o in order], [pts[o][0][1] for o in order], color=COL[a], ls=ls, lw=0.9, zorder=2)
            for o in OBJ:
                (x, y), ((xl, yl), (xh, yh)) = pts[o]
                big = o == "error"
                ax.errorbar(x, y, xerr=[[x - xl], [xh - x]], yerr=[[y - yl], [yh - y]], fmt="none", ecolor=COL[a], elinewidth=0.5, alpha=0.6, zorder=2)
                ax.scatter([x], [y], s=30 if big else 13, marker=marker, color=COL[a], edgecolor=INK if big else "white", linewidth=0.7 if big else 0.4, zorder=4)
            report[(t, a)] = {o: tuple(round(float(v), 3) for v in pts[o][0]) for o in OBJ}
    ax.axhline(1, color=GRIDC, lw=0.6, zorder=1)
    ax.axvline(1, color=GRIDC, lw=0.6, zorder=1)
    ax.set_xlabel("Routing SWAPs (Greedy, error-selected = 1)")
    ax.set_ylabel("Duration (Greedy, error-selected = 1)")
    ax.grid(color=GRIDC, lw=0.4, zorder=0)
    ax.tick_params(top=False, right=False)
    h = [plt.Line2D([], [], color=COL[a], lw=1.1, label=NAME[a]) for a in (G, P)]
    h += [plt.Line2D([], [], color=MUTED, marker=m, ls=ls, lw=0.9, markersize=3.5, label=lab) for lab, m, ls in TOPO.values()]
    h += [plt.Line2D([], [], color=MUTED, marker="o", lw=0, markersize=5, markeredgecolor=INK, label="error-selected")]
    ax.legend(handles=h, frameon=False, fontsize=5.6, loc="upper left", ncol=2, handlelength=2.2, columnspacing=0.9)
    lo, hi = ax.get_ylim()
    ax.set_ylim(lo, hi + 0.35 * (hi - lo))
    fig.tight_layout(pad=0.3)
    fig.savefig(OUT / "panel_a.pdf")
    fig.savefig(OUT / "panel_a.png", dpi=300)
for k, v in report.items():
    print(k, v)
