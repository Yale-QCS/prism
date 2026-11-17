"""P1 figure: (a) break-even transmon plane, (b) PRISM against Greedy across widths.

  .venv/bin/python research/rebuttal/wallclock/breakeven_figure.py --plane-width 8 --widths 8 12

(a) reads `data/legacy/breakeven_n<w>_contours.json` from `breakeven_plane.py`. For each dual-rail
arm, the transmon CZ error r* at which a transmon matches it, on each T1 line: equal
fidelity (heavy solid, no noise-model assumption) and equal cost (thin dashed, 1/F^2
model). A transmon left of a line beats that arm on that measure. Devices are placed at
T1_eff = T1 * 68 ns / t_CZ, our approximation.
(b) PRISM/Greedy ratios of shots per kept shot (1/P_keep), duration and sampling cost,
geometric means over workloads with 95% seed-resample intervals (paired arms).
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
ARMS = ("prism", "greedy", "logical")
COL = {"logical": "#8a9096", "greedy": "#d69b32", "prism": "#008f7e"}
NAME = {"logical": "Logical-SABRE", "greedy": "Greedy", "prism": "PRISM"}
INK, MUTED, GRIDC = "#2b2b2b", "#6b6b6b", "#e3e3e3"
TOPOLOGIES = ("grid", "hex_lattice")
OVERHEAD_US = 2.0
RATIOS = {
    "1 / P_keep": lambda r: 1 / r["p_keep"],
    "Duration": lambda r: r["duration_us"],
    "Sampling cost": lambda r: (r["duration_us"] + OVERHEAD_US) / (r["p_keep"] * r["fidelity"] ** 2),
}
DEVICES = [  # (label, r, T1_eff in us); README table
    ("IBM Heron r2 (median)", 2.848e-3, 136.5),
    ("Google Willow chip 1 (mean)", 3.3e-3, 68.0 * 68 / 42),
    ("DTC, single pair", 1.0e-3, (228.6 + 205.3) / 2 * 68 / 48),
]
RATIO_COL = {"1 / P_keep": "#3b6ea5", "Duration": "#8a9096", "Sampling cost": "#008f7e"}

parser = argparse.ArgumentParser()
parser.add_argument("--plane-width", type=int, default=8)
parser.add_argument("--widths", type=int, nargs="+", default=[8, 12])
args = parser.parse_args()
rng = np.random.default_rng(0)

plane = json.loads((HERE / "data/legacy" / f"breakeven_n{args.plane_width}_contours.json").read_text())


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
    for name, f in RATIOS.items():
        v = {a: np.array([[np.mean([f(x) for x in rows[(a, c)][s]]) for s in seeds] for c in circuits]) for a in ("prism", "greedy")}
        ln = np.log(v["prism"][:, picks].mean(axis=2)).mean(axis=0) - np.log(v["greedy"][:, picks].mean(axis=2)).mean(axis=0)
        out[name] = (math.exp(ln[0]), *np.exp(np.percentile(ln[1:], [2.5, 97.5])))
    return out


ratios = {w: ratio_stats(w) for w in args.widths}


def plain(value, _):
    return f"{value:g}"


with plt.style.context("lusca"):
    plt.rcParams.update({"font.size": 7.0, "axes.labelsize": 7.0, "xtick.labelsize": 6.4, "ytick.labelsize": 6.4, "pdf.fonttype": 42,
                         "axes.edgecolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED, "axes.labelcolor": INK})
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(7.0, 2.7), gridspec_kw={"width_ratios": [1.35, 1]})

    errors, t1s = plane["errors"], plane["t1"]
    ax.add_patch(plt.Rectangle((errors[0], t1s[0]), errors[-1] - errors[0], t1s[-1] - t1s[0], fill=False, ec=GRIDC, lw=0.8, zorder=0))
    notes = []
    for metric, style in (("infidelity", dict(lw=2.0, ls="-")), ("cost", dict(lw=0.9, ls="--"))):
        for arm in ARMS:
            entries = plane["contours"][metric][arm]
            pts = [(v[0], float(t), v[1], v[2]) for t, v in entries.items() if 0 < v[0] < math.inf]
            if pts:
                x, y, lo, hi = map(np.array, zip(*sorted(pts, key=lambda p: p[1])))
                ax.plot(x, y, color=COL[arm], **style, zorder=3)
                ax.errorbar(x, y, xerr=[x - np.nan_to_num(lo, nan=x), np.nan_to_num(hi, nan=x) - x], fmt="none", ecolor=COL[arm], elinewidth=0.6, capsize=1.2, zorder=3)
            if not pts or len(pts) < len(entries):
                below = [float(t) for t, v in entries.items() if v[0] == 0]
                if below:
                    notes.append((metric, arm, max(below)))
    for label, r, t1 in DEVICES:
        ax.plot(r, t1, marker="*" if "pair" in label else "D", color=INK, markersize=5 if "pair" in label else 3.6, zorder=4)
        ax.annotate(label, (r, t1), xytext=(4, -2), textcoords="offset points", fontsize=5.6, color=INK, va="top")
    off = [m for m, _, _ in notes]
    if "infidelity" in off:
        worst = {a: t for m, a, t in notes if m == "infidelity"}
        ax.text(0.03, 0.03, "Equal fidelity needs r < %g\nup to T1 = %g µs (all arms)" % (errors[0], min(worst.values())) if len(worst) == len(ARMS) else
                "Equal fidelity below grid for " + ", ".join(NAME[a] for a in worst),
                transform=ax.transAxes, fontsize=5.6, color=INK, va="bottom")
    ax.set_xscale("log")
    ax.set_yscale("log")
    for axis in (ax.xaxis, ax.yaxis):
        axis.set_major_formatter(FuncFormatter(plain))
        axis.set_minor_formatter(NullFormatter())
    ax.set_xlim(errors[0] / 1.6, errors[-1] * 1.6)
    ax.set_ylim(t1s[0] / 1.4, t1s[-1] * 1.4)
    ax.set_xlabel("Transmon CZ average error r")
    ax.set_ylabel("Transmon T1 = T2, µs")
    ax.set_title(f"(a) Break-even transmon, n = {args.plane_width}", fontsize=7.4, color=INK, loc="left")
    ax.grid(color=GRIDC, lw=0.5, zorder=0)
    arm_handles = [plt.Line2D([], [], color=COL[a], lw=1.6, label=NAME[a]) for a in ARMS]
    style_handles = [plt.Line2D([], [], color=INK, lw=2.0, label="Equal fidelity"),
                     plt.Line2D([], [], color=INK, lw=0.9, ls="--", label="Equal cost (1/F² model)")]
    first = ax.legend(handles=arm_handles, frameon=False, fontsize=5.8, loc="upper left", title="Dual rail", title_fontsize=5.8)
    ax.add_artist(first)
    ax.legend(handles=style_handles, frameon=False, fontsize=5.8, loc="upper right")

    widths = args.widths
    for k, (name, col) in enumerate(RATIO_COL.items()):
        xs = [w + (k - 1) * 0.35 for w in widths]
        pts = [ratios[w][name] for w in widths]
        bx.errorbar(xs, [p[0] for p in pts], yerr=[[p[0] - p[1] for p in pts], [p[2] - p[0] for p in pts]], color=col, marker="o",
                    markersize=3.8, lw=1.0, elinewidth=0.7, capsize=1.5, label=name, zorder=3)
    bx.axhline(1, color=MUTED, lw=0.7, zorder=1)
    bx.set_xticks(widths)
    bx.set_xlim(widths[0] - 1.5, widths[-1] + 1.5)
    bx.set_xlabel("Logical qubits")
    bx.set_ylabel("PRISM / Greedy")
    bx.set_title("(b) PRISM against Greedy on dual rail", fontsize=7.4, color=INK, loc="left")
    bx.grid(color=GRIDC, lw=0.5, zorder=0)
    bx.legend(frameon=False, fontsize=5.8, loc="lower left")
    fig.tight_layout(w_pad=1.2)
    fig.savefig(OUT / "p1_breakeven.png", dpi=220)
    fig.savefig(OUT / "p1_breakeven.pdf")

for w in widths:
    print(w, {k: tuple(round(float(v), 4) for v in vals) for k, vals in ratios[w].items()})
