"""R3 trade-off figure: routing SWAPs against duration per route-selection objective (pass --w16 for the 16-qubit rows)."""
import json
import sys
from collections import defaultdict
from pathlib import Path
import lusca  # noqa: F401
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts/paper"))
from paper_common import bootstrap_interval  # noqa: E402

RAW = Path(__file__).resolve().parents[3] / "artifacts/paper/raw"
OUT = Path(__file__).parent / "figures"; OUT.mkdir(exist_ok=True)
G, P = "greedy", "prism"
COL = {G: "#d69b32", P: "#39877f"}; MARK = {G: "s", P: "o"}; NAME = {G: "Greedy", P: "PRISM"}
OBJ = {"swaps": "objective_swaps", "depth": "objective_depth", "duration": "objective_duration", "error": "core"}
W16 = "--w16" in sys.argv
COLUMN = "--column" in sys.argv  # one-column layout for the paper (3.4 in wide)
if W16:
    RAW = Path(__file__).resolve().parents[1] / "tradeoff/data"
    OBJ = {o: f"w16_{o}" for o in OBJ}
TOPO = {"grid": "Square grid", "hex_lattice": "Hexagonal lattice", "heavy_hex": "Heavy-hex"}
INK, MUTED, GRIDC = "#2b2b2b", "#6b6b6b", "#e3e3e3"
rng = np.random.default_rng(0)

def load(name):
    out = defaultdict(lambda: defaultdict(dict))  # (topo, arm) -> seed -> circuit -> row
    for r in map(json.loads, open(RAW / f"{name}.jsonl")):
        if r["success"]:
            out[(r["topology_name"], r["strategy"])][r["outer_seed"]][r["circuit_name"]] = r
    return out

def point(rows, topo, arm):
    by_seed = rows[(topo, arm)]
    seeds = sorted(by_seed)
    x = np.array([[by_seed[s][c]["router_inserted_swaps"] for c in sorted(by_seed[s])] for s in seeds], float)
    y = np.array([[by_seed[s][c]["duration_ns"] / 1e3 for c in sorted(by_seed[s])] for s in seeds], float)
    picks = rng.integers(0, len(seeds), (2000, len(seeds)))
    ci = lambda a: np.percentile(a[picks].mean(axis=(1, 2)), [2.5, 97.5])
    return x.mean(), y.mean(), ci(x), ci(y)

def reduction_ci(rows, topo, metric):
    """95% paired seed-bootstrap interval of PRISM's pooled reduction against Greedy (in %)."""
    g, p = rows[(topo, G)], rows[(topo, P)]
    seeds = sorted(set(g) & set(p))
    circuits = sorted(set.intersection(*(set(g[s]) & set(p[s]) for s in seeds)))
    arr = lambda side: np.array([[side[s][c][metric] for s in seeds] for c in circuits], float)
    lo, hi = bootstrap_interval(arr(g), arr(p))
    return 100 * lo, 100 * hi, len(seeds)


data = {o: load(n) for o, n in OBJ.items()}
off = None if W16 else load("reschedule_off")
with plt.style.context("lusca"):
    small = {"font.size": 5.8, "axes.labelsize": 6.0, "xtick.labelsize": 5.4, "ytick.labelsize": 5.4} if COLUMN else {}
    plt.rcParams.update({"font.size": 7.2, "axes.labelsize": 7.4, "xtick.labelsize": 6.6, "ytick.labelsize": 6.6, "pdf.fonttype": 42, **small,
                         "axes.edgecolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED, "axes.labelcolor": INK})
    fig, axes = plt.subplots(1, 3, figsize=(3.4, 1.9) if COLUMN else (7.15, 2.35))
    for ax, topo in zip(axes, TOPO):
        main = {}
        for arm in (G, P):
            pts = {o: point(data[o], topo, arm) for o in OBJ}
            order = sorted(OBJ, key=lambda o: pts[o][0])
            ax.plot([pts[o][0] for o in order], [pts[o][1] for o in order], color=COL[arm], lw=1.1, zorder=2)
            for o in OBJ:
                x, y, cx, cy = pts[o]
                ax.errorbar(x, y, xerr=[[x - cx[0]], [cx[1] - x]], yerr=[[y - cy[0]], [cy[1] - y]], fmt="none", ecolor=COL[arm], elinewidth=0.6, alpha=0.7, zorder=2)
                big = o == "error"
                ax.scatter([x], [y], s=46 if big else 26, marker=MARK[arm], color=COL[arm], edgecolor=INK if big else "white", linewidth=0.9, zorder=4)
                if arm == P and o == "swaps" and not COLUMN:
                    ax.annotate("selected by SWAPs", (x, y), xytext=(5, 3), textcoords="offset points", fontsize=6.0, color=INK)
                if arm == P and o == "error" and not COLUMN:
                    ax.annotate("by depth, duration or error", (x, y), xytext=(4, -9), textcoords="offset points", fontsize=6.0, color=INK, ha="left", va="top")
            x, y, _, _ = point(off, topo, arm) if off else (np.nan,) * 4
            ax.scatter([x], [y], s=22, marker=MARK[arm], facecolor="none", edgecolor=COL[arm], linewidth=0.8, alpha=0.6, zorder=3)
            main[arm] = pts["error"][:2]
        (gx, gy), (px, py) = main[G], main[P]
        ax.annotate("", xy=(px, py), xytext=(gx, gy), arrowprops=dict(arrowstyle="->", color=MUTED, lw=0.7, shrinkA=6, shrinkB=6), zorder=1)
        (sl, sh, n_seeds), (dl, dh, _) = (reduction_ci(data["error"], topo, m) for m in ("router_inserted_swaps", "duration_ns"))
        band = (lambda lo, hi: f" [{lo:.0f}, {hi:.0f}]") if n_seeds > 1 else (lambda lo, hi: "")
        ax.text(0.04 if COLUMN else 0.97, 0.96 if COLUMN else 0.36, f"−{100 * (1 - px / gx):.0f}%{band(sl, sh)} SWAPs\n−{100 * (1 - py / gy):.0f}%{band(dl, dh)} duration", transform=ax.transAxes,
                fontsize=4.5 if COLUMN else 6.4, color=INK, ha="left" if COLUMN else "right", va="top" if COLUMN else "center", linespacing=1.2)
        lo, hi = ax.get_ylim(); ax.set_ylim(lo - 0.16 * (hi - lo), hi + (0.42 * (hi - lo) if COLUMN else 0))
        ax.set_title({"grid": "Grid", "hex_lattice": "Hex", "heavy_hex": "Heavy-hex"}[topo] if COLUMN else TOPO[topo], fontsize=6.4 if COLUMN else 7.4, color=INK, loc="left")
        ax.set_xlabel("" if COLUMN and ax is not axes[1] else "Routing SWAPs per run"); ax.grid(color=GRIDC, lw=0.5, zorder=0)
        if COLUMN:
            ax.tick_params(top=False, right=False)
    axes[0].set_ylabel("Duration (µs)" if COLUMN else "Duration per run (µs)")
    h = [plt.Line2D([], [], color=COL[a], marker=MARK[a], lw=1.1, label=NAME[a]) for a in (G, P)]
    h += [plt.Line2D([], [], color=MUTED, marker="o", lw=0, markersize=6, markeredgecolor=INK, label="selected by error (main results)"),
          plt.Line2D([], [], color=MUTED, marker="o", lw=0, markerfacecolor="none", label="error, without rescheduling")]
    h = h[:3] if W16 else h
    fig.legend(handles=h, frameon=False, fontsize=5.6 if COLUMN else 6.4, ncol=4, loc="upper center", bbox_to_anchor=(0.5, 1.02), handlelength=1.4, columnspacing=0.8)
    fig.tight_layout(rect=(0, 0, 1, 0.9)); stem = ("objectives_w16" if W16 else "objectives") + ("_column" if COLUMN else ""); fig.savefig(OUT / f"{stem}.png", dpi=220); fig.savefig(OUT / f"{stem}.pdf")
for topo in TOPO:
    print(topo, {o: tuple(round(v, 2) for v in point(data[o], topo, a)[:2]) for o in OBJ for a in (P,)}, "greedy:", {o: tuple(round(v, 2) for v in point(data[o], topo, G)[:2]) for o in OBJ})
