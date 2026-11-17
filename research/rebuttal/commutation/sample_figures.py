"""Sample objective-trade-off figures A-D from the 3-seed commutation study rows (old suite)."""
import json, statistics as st, sys
from collections import defaultdict
from pathlib import Path
import lusca  # noqa: F401
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from marabbecca.utils.metrics import device_success

D = Path(__file__).resolve().parents[3] / "research/rebuttal/commutation/data"
OUT = Path(__file__).parent / "sample_figures"
G, P = "greedy", "prism"
COL = {G: "#d69b32", P: "#39877f"}; MARK = {G: "s", P: "o"}; NAME = {G: "Greedy", P: "PRISM"}
OBJ = ("swaps", "depth", "duration"); OBJ_NAME = {"swaps": "SWAPs", "depth": "depth", "duration": "duration"}
TOPO = {"grid": "Square grid", "hex_lattice": "Hexagonal lattice"}
INK, MUTED, GRID = "#2b2b2b", "#6b6b6b", "#e3e3e3"

def rows(name):
    return [r for r in map(json.loads, open(D / f"{name}.jsonl")) if r["success"]]

def mean(rs, topo, arm, key):
    v = [r[key] for r in rs if r["topology_name"] == topo and r["strategy"] == arm]
    return sum(v) / len(v)

def style():
    plt.rcParams.update({"font.size": 7.2, "axes.labelsize": 7.4, "xtick.labelsize": 6.6, "ytick.labelsize": 6.6, "pdf.fonttype": 42,
                         "axes.edgecolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED, "axes.labelcolor": INK})

def pareto(ax, topo, refined=True):
    for arm in (G, P):
        pts = [(mean(rows(f"{o}_ord"), topo, arm, "router_inserted_swaps"), mean(rows(f"{o}_ord"), topo, arm, "duration_ns") / 1e3) for o in OBJ]
        xs, ys = zip(*pts)
        ax.plot(xs, ys, color=COL[arm], lw=1.2, zorder=2)
        ax.scatter(xs, ys, s=34, marker=MARK[arm], color=COL[arm], edgecolor="white", linewidth=1.2, zorder=3, label=f"{NAME[arm]}")
        if arm == P:
            offsets = {"swaps": (6, 2), "depth": (-6, 5), "duration": (6, 4)}
            align = {"swaps": "left", "depth": "right", "duration": "left"}
            for (x, y), o in zip(pts, OBJ):
                ax.annotate(f"by {OBJ_NAME[o]}", (x, y), xytext=offsets[o], textcoords="offset points", fontsize=6.2, color=INK, ha=align[o])
        if refined:
            for o in ("swaps", "depth"):
                r = rows(f"{o}_level1")
                ax.scatter([mean(r, topo, arm, "router_inserted_swaps")], [mean(r, topo, arm, "duration_ns") / 1e3], s=30, marker=MARK[arm],
                           facecolor="none", edgecolor=COL[arm], linewidth=1.1, zorder=3)
    ax.set_xlabel("Routing SWAPs per run"); ax.set_ylabel("Duration per run (µs)")
    ax.set_title(TOPO[topo], fontsize=7.4, color=INK, loc="left")
    ax.grid(color=GRID, lw=0.5, zorder=0)

def fig_a():
    fig, axes = plt.subplots(1, 2, figsize=(7.15, 2.4))
    for ax, topo in zip(axes, TOPO): pareto(ax, topo)
    h = [plt.Line2D([], [], color=COL[a], marker=MARK[a], lw=1.2, label=f"{NAME[a]}, program order") for a in (G, P)]
    h += [plt.Line2D([], [], color=MUTED, marker="o", lw=0, markerfacecolor="none", label="commutation-aware (level window)")]
    fig.legend(handles=h, frameon=False, fontsize=6.4, loc="upper center", ncol=3, bbox_to_anchor=(0.5, 1.02))
    fig.tight_layout(rect=(0, 0, 1, 0.9)); fig.savefig(OUT / "A_pareto.png", dpi=220); plt.close(fig)

def reductions(name, topo, key):
    by_seed = defaultdict(lambda: [0, 0])
    for r in rows(name):
        if r["topology_name"] != topo: continue
        by_seed[r["outer_seed"]][0 if r["strategy"] == G else 1] += r[key]
    per_seed = [100 * (1 - p / g) for g, p in by_seed.values()]
    g = sum(v[0] for v in by_seed.values()); p = sum(v[1] for v in by_seed.values())
    return 100 * (1 - p / g), min(per_seed), max(per_seed)

def fig_b():
    metrics = (("router_inserted_swaps", "SWAPs"), ("physical_depth", "Depth"), ("duration_ns", "Duration"))
    shades = ("#1f5f59", "#39877f", "#8cc1b9")
    fig, axes = plt.subplots(1, 2, figsize=(7.15, 2.2), sharey=True)
    for ax, topo in zip(axes, TOPO):
        x = np.arange(len(OBJ)); w = 0.26
        for i, ((key, label), c) in enumerate(zip(metrics, shades)):
            vals = [reductions(f"{o}_ord", topo, key) for o in OBJ]
            mid = [v[0] for v in vals]; lo = [v[0] - v[1] for v in vals]; hi = [v[2] - v[0] for v in vals]
            ax.bar(x + (i - 1) * w, mid, w * 0.92, color=c, label=label, zorder=2)
            ax.errorbar(x + (i - 1) * w, mid, yerr=[lo, hi], fmt="none", ecolor=INK, elinewidth=0.7, capsize=1.5, zorder=3)
        ax.set_xticks(x, [f"selected by\n{OBJ_NAME[o]}" for o in OBJ])
        ax.axhline(0, color=MUTED, lw=0.6); ax.grid(axis="y", color=GRID, lw=0.5, zorder=0)
        ax.set_title(TOPO[topo], fontsize=7.4, color=INK, loc="left")
    axes[0].set_ylabel("PRISM reduction vs Greedy (%)")
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, frameon=False, fontsize=6.4, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.02))
    fig.tight_layout(rect=(0, 0, 1, 0.9)); fig.savefig(OUT / "B_bars.png", dpi=220); plt.close(fig)

def overhead(name, topo, arm):
    v = []
    for r in rows(name):
        if r["topology_name"] == topo and r["strategy"] == arm:
            keep, _ = device_success(8, r["duration_ns"], r["final_op_counts"])
            v.append(1 / keep)
    return st.mean(v)

def fig_c():
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.15, 2.3), gridspec_kw={"width_ratios": [1.25, 1]})
    pareto(a, "grid", refined=False)
    fig.legend(handles=[plt.Line2D([], [], color=COL[x], marker=MARK[x], lw=1.2, label=NAME[x]) for x in (G, P)], frameon=False, fontsize=6.4, ncol=2, loc="upper center", bbox_to_anchor=(0.5, 1.02))
    x = np.arange(len(OBJ)); w = 0.36
    for i, arm in enumerate((G, P)):
        vals = [overhead(f"{o}_ord", "grid", arm) for o in OBJ]
        b.bar(x + (i - 0.5) * w, vals, w * 0.92, color=COL[arm], label=NAME[arm], zorder=2, hatch="//" if arm == G else None, edgecolor="white", linewidth=0.5)
    b.set_xticks(x, [f"by {OBJ_NAME[o]}" for o in OBJ]); b.set_ylabel("Shots per kept shot (1/P_keep)")
    b.set_ylim(1.0, None); b.grid(axis="y", color=GRID, lw=0.5, zorder=0)
    b.set_title("Square grid, 8 logical qubits", fontsize=7.4, color=INK, loc="left")
    fig.tight_layout(rect=(0, 0, 1, 0.9)); fig.savefig(OUT / "C_pareto_overhead.png", dpi=220); plt.close(fig)

def fig_d():
    fig, axes = plt.subplots(1, 2, figsize=(7.15, 2.6))
    for ax, topo in zip(axes, TOPO):
        rs = {(r["circuit_name"], r["outer_seed"], r["strategy"]): r["duration_ns"] / 1e3 for r in rows("duration_ord") if r["topology_name"] == topo}
        keys = sorted({(c, s) for c, s, _ in rs})
        g = np.array([rs[(c, s, G)] for c, s in keys]); p = np.array([rs[(c, s, P)] for c, s in keys])
        lo, hi = min(g.min(), p.min()) * 0.8, max(g.max(), p.max()) * 1.2
        ax.plot([lo, hi], [lo, hi], color=MUTED, lw=0.8, ls="--", zorder=1)
        win = p < g
        ax.scatter(g[win], p[win], s=14, color=COL[P], edgecolor="white", linewidth=0.6, zorder=3, label="PRISM shorter")
        ax.scatter(g[~win], p[~win], s=16, marker="^", color="#b55a55", edgecolor="white", linewidth=0.6, zorder=3, label="PRISM longer or equal")
        ax.set_xscale("log"); ax.set_yscale("log"); ax.set_xlim(lo, hi); ax.set_ylim(lo, hi)
        ticks = [t for t in (2, 5, 10, 20, 50) if lo <= t <= hi]
        for axis in (ax.xaxis, ax.yaxis):
            axis.set_major_locator(matplotlib.ticker.FixedLocator(ticks))
            axis.set_major_formatter(matplotlib.ticker.FormatStrFormatter("%g"))
            axis.set_minor_formatter(matplotlib.ticker.NullFormatter())
        ax.set_xlabel("Greedy duration (µs)"); ax.set_ylabel("PRISM duration (µs)")
        ax.set_title(f"{TOPO[topo]}: {win.sum()} of {len(win)} runs shorter", fontsize=7.4, color=INK, loc="left")
        ax.grid(color=GRID, lw=0.5, zorder=0)
    axes[0].legend(frameon=False, fontsize=6.2, loc="upper left")
    fig.tight_layout(); fig.savefig(OUT / "D_paired.png", dpi=220); plt.close(fig)

with plt.style.context("lusca"):
    style(); fig_a(); fig_b(); fig_c(); fig_d()
print("done")
