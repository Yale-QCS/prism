"""Section V-C figure: (a) front-commit ablation as stacked bars, (b) route-selection objective as compact arrows.

(a) reads the SWAP-selected core and front-commit rows for the 16 MQT workloads at width 8 (seeds 0..1900);
(b) reads the n = 16 objective rows. Prints the numbers the Section V-C text quotes.
Usage: .venv/bin/python research/rebuttal/tradeoff/ablation_objectives_figure.py [--core F] [--ablation F ...] [--objectives DIR] [--seeds N] [--metric M]
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

import lusca  # noqa: F401
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "artifacts/paper/raw"
ap = argparse.ArgumentParser()
ap.add_argument("--core", default=str(RAW / "core_swaps.jsonl"))
ap.add_argument("--ablation", nargs="+", default=[str(RAW / "front_commit_swaps.jsonl"), str(RAW / "front_commit_swaps_heavyhex.jsonl")])
ap.add_argument("--objectives", default=str(Path(__file__).parent / "data"))
ap.add_argument("--seeds", type=int, default=20, help="seeds 0, 100, ... used for panel (a)")
ap.add_argument("--metric", default="router_inserted_swaps", help="row field panel (a) and the printed numbers compare, e.g. physical_depth")
ap.add_argument("--out", default=str(Path(__file__).parent / "figures/ablation_objectives"))
a = ap.parse_args()

G, P, L = "#d69b32", "#39877f", "#9fcdc5"
TOP = {"grid": "Grid", "hex_lattice": "Hex", "heavy_hex": "Heavy-hex"}
SEEDS = set(range(0, 100 * a.seeds, 100))
runs = defaultdict(dict)  # (arm, topology) -> (circuit, seed) -> metric
for f in [a.core, *a.ablation]:
    for r in map(json.loads, open(f)):
        if r["success"] and r["outer_seed"] in SEEDS and r["topology_name"] in TOP:
            runs[(r["strategy"], r["topology_name"])][(r["circuit_name"], r["outer_seed"])] = r[a.metric]
F = "prism_front_commit"
stats = {}
for t in TOP:
    g, p, f = (runs[(arm, t)] for arm in ("greedy", "prism", F))
    keys = sorted(set(g) & set(p) & set(f))
    tg, tp, tf = (sum(d[k] for k in keys) for d in (g, p, f))
    wl = sorted({k[0] for k in keys})
    mean = lambda d, c: np.mean([d[k] for k in keys if k[0] == c])
    stats[t] = dict(runs=len(keys), front=100 * (1 - tf / tg), prism=100 * (1 - tp / tg), further=100 * (1 - tp / tf),
                    front_mean_losses=[c for c in wl if mean(f, c) > mean(g, c)], prism_mean_losses=[c for c in wl if mean(p, c) > mean(g, c)])
for t, s in stats.items():
    print(t, {k: (round(v, 1) if isinstance(v, float) else v) for k, v in s.items()})

rows = defaultdict(lambda: defaultdict(dict))
for o in ("swaps", "duration"):
    for r in map(json.loads, open(Path(a.objectives) / f"w16_{o}.jsonl")):
        if r["success"]:
            rows[(o, r["topology_name"], r["strategy"])][r["outer_seed"]][r["circuit_name"]] = r
M = ("router_inserted_swaps", "duration_ns")
tot = {k: [sum(v[s][c][m] for s in v for c in v[s]) for m in M] for k, v in rows.items()}
rel = {k: [x / y for x, y in zip(v, tot[("swaps", k[1], "greedy")])] for k, v in tot.items()}

# Panel titles sit above the legends, as in Figs. 9, 10 and 12; the extra height keeps
# the axes the same size in inches as before (bottom 0.384 in, top 1.28 in).
FIG_H = 1.78
FRONT = "#c3c8cd"  # neutral grey with hatching: the front-layer-commit ablation; PRISM's teal is the part delayed commitment adds
SHAPES = {"swaps": ("o", "SWAP-selected", 3.0), "duration": ("*", "Duration-selected", 5.2)}
with plt.style.context("lusca"):
    plt.rcParams.update({"font.size": 7.0, "axes.labelsize": 6.8, "xtick.labelsize": 6.2, "ytick.labelsize": 6.2, "legend.fontsize": 5.8, "pdf.fonttype": 42, "hatch.linewidth": 0.4})
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(3.35, FIG_H))
    y = np.arange(len(TOP))[::-1]
    for yy, t in zip(y, TOP):
        s = stats[t]
        ax1.barh(yy, s["front"], color=FRONT, hatch="////", edgecolor="#606060", linewidth=0.3, height=0.42, zorder=2)
        ax1.barh(yy, s["prism"] - s["front"], left=s["front"], color=P, edgecolor="#303030", linewidth=0.3, height=0.42, zorder=2)
        ax1.text(s["prism"] + 0.8, yy, f"{s['prism']:.0f}%", va="center", fontsize=6)
        ax1.text(0.5, yy + 0.33, TOP[t], va="bottom", ha="left", fontsize=6)
    ax1.set_yticks([]); ax1.set_xlim(0, 36); ax1.set_xticks((0, 10, 20, 30)); ax1.set_ylim(-0.45, len(TOP) - 0.15)
    ax1.set_xlabel("Fewer SWAPs than Greedy (%)" if a.metric == "router_inserted_swaps" else f"Lower {a.metric} than Greedy (%)")
    ax1.legend(handles=[plt.Rectangle((0, 0), 1, 1, facecolor=FRONT, hatch="////", edgecolor="#606060", linewidth=0.3, label="Layout-aware choice"),
                        plt.Rectangle((0, 0), 1, 1, facecolor=P, edgecolor="#303030", linewidth=0.3, label="Choice kept open")],
               frameon=False, loc="lower left", bbox_to_anchor=(-0.02, 1.0), handlelength=1.1, handletextpad=0.35, borderaxespad=0.1, labelspacing=0.2)
    ax1.set_title("(a) Ablation, $n$ = 8", loc="left", fontsize=7.0, pad=17)
    for arm, col in (("greedy", G), ("prism", P)):
        for t in TOP:
            s, d = rel[("swaps", t, arm)], rel[("duration", t, arm)]
            ax2.annotate("", xy=d, xytext=s, arrowprops=dict(arrowstyle="-|>", color=col, lw=0.7, mutation_scale=5, shrinkA=2.6, shrinkB=2.6), zorder=2)
            for o, pt in (("swaps", s), ("duration", d)):
                ax2.plot(*pt, SHAPES[o][0], ms=SHAPES[o][2], mfc=col, mec="#303030", mew=0.3, zorder=3)
    ax2.text(0.70, 0.89, "PRISM", ha="center", fontsize=6.2, color=P); ax2.text(1.03, 1.025, "Greedy", ha="center", fontsize=6.2, color="#a8741f")
    ax2.set_xlim(0.6, 1.17); ax2.set_ylim(0.72, 1.08); ax2.set_xticks((0.7, 0.9, 1.1)); ax2.set_yticks((0.8, 0.9, 1.0))
    ax2.set_xlabel("SWAPs (relative)"); ax2.set_ylabel("Duration (relative)")
    ax2.legend(handles=[plt.Line2D([], [], marker=m, ls="none", ms=ms, mfc="#9a9a9a", mec="#303030", mew=0.3, label=lab) for m, lab, ms in SHAPES.values()],
               frameon=False, loc="lower left", bbox_to_anchor=(-0.02, 1.0), handletextpad=0.2, borderaxespad=0.1, labelspacing=0.2)
    ax2.set_title("(b) Objective, $n$ = 16", loc="left", fontsize=7.0, pad=17)
    for ax in (ax1, ax2):
        ax.grid(color="#e1e1e1", linewidth=0.45, zorder=0); ax.set_axisbelow(True)
    fig.subplots_adjust(left=0.06, right=0.985, bottom=0.384 / FIG_H, top=1.28 / FIG_H, wspace=0.42)
    Path(a.out).parent.mkdir(exist_ok=True)
    fig.savefig(a.out + ".pdf"); fig.savefig(a.out + ".png", dpi=300)
print("wrote", a.out + ".{pdf,png}")
