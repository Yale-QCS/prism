"""P1 draft figure: kept-shot infidelity and wall-clock per kept shot, dual-rail PRISM against bare devices."""

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

import lusca  # noqa: F401
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
OUT = HERE / "data/legacy/figures"
OUT.mkdir(exist_ok=True)
ARMS = ("logical", "greedy", "prism", "bare_transmon")
COL = {"logical": "#8a9096", "greedy": "#d69b32", "prism": "#008f7e", "bare_transmon": "#c2543c"}
MARK = {"logical": "v", "greedy": "s", "prism": "o", "bare_transmon": "^"}
NAME = {"logical": "Dual-rail, Logical-SABRE", "greedy": "Dual-rail, Greedy", "prism": "Dual-rail, PRISM", "bare_transmon": "Bare transmon"}
INK, MUTED, GRIDC = "#2b2b2b", "#6b6b6b", "#e3e3e3"
OVERHEAD_US = (0.0, 2.0, 10.0)

parser = argparse.ArgumentParser()
parser.add_argument("--rows", default="legacy/rows_n8.jsonl", help="row file under data/")
parser.add_argument("--arms", nargs="+", default=list(ARMS), help="arms to draw")
args = parser.parse_args()
ARMS = tuple(a for a in ARMS if a in args.arms)
rows = [r for r in map(json.loads, (HERE / "data" / args.rows).open()) if r["topology"] in ("grid", "hex_lattice")]
acc = defaultdict(lambda: defaultdict(list))
for r in rows:
    acc[r["circuit"]][r["arm"]].append(r)
mean = {c: {a: {k: sum(r[k] for r in v[a]) / len(v[a]) for k in ("fidelity", "p_keep", "duration_us")} for a in ARMS} for c, v in acc.items()}
order = sorted(mean, key=lambda c: 1 - mean[c]["bare_transmon"]["fidelity"])
y = range(len(order))


def per_kept_shot(c: str, arm: str, overhead: float) -> float:
    return (mean[c][arm]["duration_us"] + overhead) / mean[c][arm]["p_keep"]


with plt.style.context("lusca"):
    plt.rcParams.update({"font.size": 7.2, "axes.labelsize": 7.4, "xtick.labelsize": 6.6, "ytick.labelsize": 6.6, "pdf.fonttype": 42,
                         "axes.edgecolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED, "axes.labelcolor": INK})
    fig, (ax_f, ax_t) = plt.subplots(1, 2, figsize=(7.15, 3.4), sharey=True, gridspec_kw={"width_ratios": [1.15, 1]})

    # Dual-rail arms sit just above and below the row so Greedy and PRISM stay apart.
    offset = {"logical": 0.25, "greedy": 0.0, "prism": -0.25, "bare_transmon": 0.0}
    for arm in ARMS:
        ax_f.scatter([1 - mean[c][arm]["fidelity"] for c in order], [i + offset[arm] for i in y], s=26, marker=MARK[arm], color=COL[arm],
                     edgecolor="white", linewidth=0.7, zorder=3, label=NAME[arm])
    for i, c in enumerate(order):
        lo, hi = 1 - mean[c]["prism"]["fidelity"], 1 - mean[c]["bare_transmon"]["fidelity"]
        ax_f.plot([lo, hi], [i, i], color=GRIDC, lw=1.6, zorder=1)
    ax_f.set_xscale("log")
    ax_f.set_xlabel("Infidelity of kept shots, 1 − F")
    ax_f.set_yticks(list(y), order)
    ax_f.set_title("(a) Error in the shots kept", fontsize=7.4, color=INK, loc="left")

    ax_t.axvspan(1, 10, color="#f1f1ef", zorder=0)
    ax_t.axvline(1, color=MUTED, lw=0.8, zorder=1)
    ax_t.text(1.06, -1.25, "bare transmon", fontsize=6.0, color=MUTED, va="center")
    ax_t.text(9.4, -1.25, "within 10×", fontsize=6.0, color=MUTED, ha="right", va="center")
    for arm, dy in [(a, dy) for a, dy in (("logical", 0.25), ("greedy", 0.0), ("prism", -0.25)) if a in ARMS]:
        for i, c in enumerate(order):
            i += dy
            ratios = [per_kept_shot(c, arm, o) / per_kept_shot(c, "bare_transmon", o) for o in OVERHEAD_US]
            ax_t.plot([min(ratios), max(ratios)], [i, i], color=COL[arm], lw=1.4, alpha=0.45, zorder=2, solid_capstyle="round")
            ax_t.scatter([ratios[1]], [i], s=26, marker=MARK[arm], color=COL[arm], edgecolor="white", linewidth=0.7, zorder=3)
    ax_t.set_xscale("log")
    ax_t.set_xlim(0.3, 12)
    ax_t.set_xticks([0.5, 1, 2, 5, 10], ["0.5×", "1×", "2×", "5×", "10×"])
    ax_t.set_xlabel("Wall-clock per kept shot, relative to bare transmon")
    ax_t.set_title("(b) Time cost, including discarded shots", fontsize=7.4, color=INK, loc="left")

    for ax in (ax_f, ax_t):
        ax.grid(axis="x", color=GRIDC, lw=0.5, zorder=0)
        ax.set_ylim(-1.7, len(order) - 0.4)
    handles = [plt.Line2D([], [], color=COL[a], marker=MARK[a], lw=0, markersize=5.5, markerfacecolor=COL[a], markeredgecolor="white", label=NAME[a]) for a in ARMS]
    handles.append(plt.Line2D([], [], color=MUTED, lw=1.4, alpha=0.5, label="(b) bar: 0–10 µs overhead per shot; marker: 2 µs"))
    fig.legend(handles=handles, frameon=False, fontsize=6.4, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.0))
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    fig.savefig(OUT / "p1_fidelity_wallclock.png", dpi=220)
    fig.savefig(OUT / "p1_fidelity_wallclock.pdf")
