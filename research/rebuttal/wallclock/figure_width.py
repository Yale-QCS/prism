"""P1 width figures: kept-shot infidelity, shot overhead and sampling cost against width, every arm.

  .venv/bin/python research/rebuttal/wallclock/figure_width.py [--tag _loss0.002]

Writes `p1_width` (three panels, for the rebuttal and the artifact) and
`p1_width_paper` (panels a and c, one column). Points are geometric means over
workloads of per-workload means over grid, hex_lattice and seeds; error bars
are 95% intervals from resampling seeds.
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
from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter

HERE = Path(__file__).resolve().parent
OUT = HERE / "data/legacy/figures"
OUT.mkdir(exist_ok=True)
ARMS = ("logical", "greedy", "prism", "bare_transmon", "strong_transmon")
DUAL_RAIL = ("logical", "greedy", "prism")
COL = {"logical": "#8a9096", "greedy": "#d69b32", "prism": "#008f7e", "bare_transmon": "#c2543c", "strong_transmon": "#c2543c"}
MARK = {"logical": "v", "greedy": "s", "prism": "o", "bare_transmon": "^", "strong_transmon": "^"}
NAME = {"logical": "Dual-rail, Logical-SABRE", "greedy": "Dual-rail, Greedy", "prism": "Dual-rail, PRISM",
        "bare_transmon": "Transmon, representative", "strong_transmon": "Transmon, best case"}
INK, MUTED, GRIDC = "#2b2b2b", "#6b6b6b", "#e3e3e3"
TOPOLOGIES = ("grid", "hex_lattice")
OVERHEAD_US = 2.0
FLOOR = 1e-3  # infidelity shown as at least this, so a near-zero fidelity stays on a log axis
METRICS = {
    "infidelity": lambda m: max(1 - m["fidelity"], FLOOR),
    "overhead": lambda m: 1 / m["p_keep"],
    "cost": lambda m: (m["duration_us"] + OVERHEAD_US) / (m["p_keep"] * m["fidelity"] ** 2),
}

parser = argparse.ArgumentParser()
parser.add_argument("--tag", default="_loss0.002", help="row-file suffix")
parser.add_argument("--widths", type=int, nargs="+", default=[8, 12])
args = parser.parse_args()


def load(width: int) -> dict:
    """arm -> circuit -> seed -> rows (one per topology). The strong transmon comes from the sweep at n = 8."""
    out = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for line in (HERE / "data/legacy" / f"rows_n{width}{args.tag}.jsonl").open():
        r = json.loads(line)
        if r["topology"] in TOPOLOGIES and r["arm"] in ARMS:
            out[r["arm"]][r["circuit"]][r["seed"]].append(r)
    if out["strong_transmon"]:
        strong = []  # simulated in the same run (n = 16)
    elif width == 8:
        strong = (r for r in map(json.loads, (HERE / "data/legacy/sweep_n8.jsonl").open()) if r["arm"] == "bare_transmon" and r["variant"] == "strong_transmon")
    else:
        strong = map(json.loads, (HERE / "data/legacy" / f"rows_n{width}_strong_transmon.jsonl").open())
    for r in strong:
        if r["topology"] in TOPOLOGIES:
            out["strong_transmon"][r["circuit"]][r["seed"]].append(r | {"p_keep": 1.0})
    return out


def summary(arm_rows: dict, metric, rng) -> tuple[float, float, float]:
    """Geometric mean over workloads, and its 95% interval from resampling seeds."""
    seeds = sorted({s for per in arm_rows.values() for s in per})
    values = np.array([[np.mean([metric(r) for r in arm_rows[c][s]]) for s in seeds] for c in sorted(arm_rows)])
    point = math.exp(np.mean(np.log(values.mean(axis=1))))
    picks = rng.integers(0, len(seeds), (1000, len(seeds)))
    boot = np.exp(np.log(values[:, picks].mean(axis=2)).mean(axis=0))
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return point, lo, hi


rng = np.random.default_rng(0)
widths = args.widths
rows = {w: load(w) for w in widths}
# The representative transmon is omitted at n = 16, where its F is near 0.
stats = {(w, a, k): summary(rows[w][a], f, rng) for w in widths for a in ARMS if rows[w][a] for k, f in METRICS.items()}


def plain(value, _):
    return f"{value:g}"


def draw(ax, key, arms, ylabel, title, note):
    for arm in arms:
        xs = [w for w in widths if (w, arm, key) in stats]
        pts = [stats[(w, arm, key)] for w in xs]
        y = [p[0] for p in pts]
        err = [[p[0] - p[1] for p in pts], [p[2] - p[0] for p in pts]]
        hollow = arm == "strong_transmon"
        ax.errorbar(xs, y, yerr=err, color=COL[arm], marker=MARK[arm], lw=1.1, ls="--" if hollow else "-", markersize=4.2,
                    markerfacecolor="white" if hollow else COL[arm], markeredgecolor=COL[arm] if hollow else "white",
                    markeredgewidth=0.7, elinewidth=0.7, capsize=1.5, zorder=3)
    ax.set_yscale("log")
    ax.yaxis.set_major_locator(LogLocator(subs=(1.0, 2.0, 5.0)))
    ax.yaxis.set_major_formatter(FuncFormatter(plain))
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.set_xticks(widths)
    ax.set_xlim(widths[0] - 1, widths[-1] + 1)
    ax.set_xlabel("Logical qubits")
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=7.4, color=INK, loc="left")
    ax.grid(color=GRIDC, lw=0.5, zorder=0)
    if note:
        w = widths[-1]
        cut = 1 - stats[(w, "prism", key)][0] / stats[(w, "greedy", key)][0]
        ax.text(0.09, 0.96, f"n = {w}: PRISM {cut:.0%}\nbelow Greedy", transform=ax.transAxes, ha="left", va="top", fontsize=5.8, color=INK)


def legend(fig, arms, ncol, y):
    handles = [plt.Line2D([], [], color=COL[a], marker=MARK[a], lw=1.1, ls="--" if a == "strong_transmon" else "-", markersize=4.2,
                          markerfacecolor="white" if a == "strong_transmon" else COL[a],
                          markeredgecolor=COL[a] if a == "strong_transmon" else "white", label=NAME[a]) for a in arms]
    fig.legend(handles=handles, frameon=False, fontsize=6.0, ncol=ncol, loc="upper center", bbox_to_anchor=(0.5, y))


with plt.style.context("lusca"):
    plt.rcParams.update({"font.size": 7.0, "axes.labelsize": 7.0, "xtick.labelsize": 6.4, "ytick.labelsize": 6.4, "pdf.fonttype": 42,
                         "axes.edgecolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED, "axes.labelcolor": INK})
    infidelity = ("infidelity", ARMS, "Infidelity of kept shots, 1 − F", "(a) Error in the shots kept", False)
    overhead = ("overhead", DUAL_RAIL, "Shots run per kept shot, 1 / P_keep", "(b) Postselection overhead", True)
    cost = ("cost", ARMS, "Time to fixed precision, µs", "(c) Sampling cost", True)

    fig, axes = plt.subplots(1, 3, figsize=(7.15, 2.5))
    for ax, panel in zip(axes, (infidelity, overhead, cost)):
        draw(ax, *panel)
    legend(fig, ARMS, 5, 1.0)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    fig.savefig(OUT / "p1_width.png", dpi=220)
    fig.savefig(OUT / "p1_width.pdf")

    fig, axes = plt.subplots(1, 2, figsize=(3.4, 2.2))
    draw(axes[0], "infidelity", ARMS, "Kept-shot infidelity, 1 − F", "(a) Error", False)
    draw(axes[1], "cost", ARMS, "Time to fixed precision, µs", "(b) Sampling cost", True)
    legend(fig, ARMS, 2, 1.01)
    fig.tight_layout(rect=(0, 0, 1, 0.78), w_pad=0.8)
    fig.savefig(OUT / "p1_width_paper.png", dpi=300)
    fig.savefig(OUT / "p1_width_paper.pdf")

for w in widths:
    print(w, {a: {k: tuple(round(float(v), 4) for v in stats[(w, a, k)]) for k in METRICS} for a in ARMS if (w, a, "cost") in stats})
