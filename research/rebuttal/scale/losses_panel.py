"""Loss exponent against width.

The plotted quantity is -ln P_keep under the recalibrated Eq. 1 (scripts/paper/export_device.py). A workload counts while Greedy keeps at
least 1% of its shots, with keep = 1/mean(1/P) over seeds, as in by_width.csv (HEADLINE.md).
- losses_by_width: each workload's mean losses over seeds, PRISM and Greedy, log axis (appendix candidate).
- losses_ratio_by_width: PRISM/Greedy losses per workload, and the geomean with its paired seed interval from by_width.csv.

Usage: .venv/bin/python research/rebuttal/scale/losses_panel.py [rows.jsonl]  -> figures/losses_{,ratio_}by_width.{pdf,png}
"""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import lusca  # noqa: F401
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/paper"))
import export_device  # noqa: E402
from export_device import BENCHMARKS, ERASURE, T1_US, VIABLE_KEEP  # noqa: E402

RAW = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "artifacts/paper/raw/scale.jsonl"
OUT = Path(__file__).parent / "figures"
COL = {"greedy": "#d69b32", "prism": "#39877f"}
NAME = {"greedy": "Greedy", "prism": "PRISM"}
TOPO = {"grid": ("(a) Square grid", "#4c78a8"), "hex_lattice": ("(b) Hexagonal lattice", "#d9902f")}
MARK = {"grid": "o", "hex_lattice": "s"}  # as in the scaling figure (export_scaling.py)
INK, MUTED, GRIDC, THIN = "#2b2b2b", "#6b6b6b", "#e3e3e3", "#b5b5b5"

seeds = defaultdict(dict)  # (topology, arm, workload, width) -> seed -> losses
for row in map(json.loads, RAW.open()):
    if row.get("success") and row["circuit_name"] in BENCHMARKS and row["topology_name"] in TOPO:
        loss = row["pair_idle_us"] / T1_US - sum(n * math.log1p(-ERASURE[k]) for k, n in row["pair_touches"].items())
        seeds[(row["topology_name"], row["strategy"], row["circuit_name"], int(row["requested_n"]))][row["outer_seed"]] = loss
n_seeds = len({s for v in seeds.values() for s in v})
WIDTHS = sorted({w for *_, w in seeds})
# (topology, workload, width) -> (Greedy mean losses, PRISM mean losses, Greedy keep), complete cells only
cell = {}
for (t, a, b, w), v in seeds.items():
    g, p = seeds.get((t, "greedy", b, w), {}), seeds.get((t, "prism", b, w), {})
    if a == "greedy" and len(g) == len(p) == n_seeds:
        g, p = np.array(list(g.values())), np.array(list(p.values()))
        cell[(t, b, w)] = (g.mean(), p.mean(), 1 / np.exp(g).mean())
export_device.RAW = RAW
export_device.SEEDS = tuple(sorted({s for v in seeds.values() for s in v}))
table = {(r["width"], r["topology"]): r for r in export_device._by_width()}


def traces(t: str, b: str) -> tuple[list, list]:
    """Widths where Greedy keeps at least 1%, and the rest, each with a one-point overlap so the line is continuous."""
    ws = [w for w in WIDTHS if (t, b, w) in cell]
    viable = [w for w in ws if cell[(t, b, w)][2] >= VIABLE_KEEP]
    cut = len(viable) if viable == ws[: len(viable)] else 0  # viability only ends once as width grows
    return ws[:cut], ws[max(cut - 1, 0):]


OUT.mkdir(exist_ok=True)
STYLE = {"font.size": 6.4, "axes.labelsize": 6.8, "xtick.labelsize": 6.0, "ytick.labelsize": 6.0, "pdf.fonttype": 42,
         "axes.edgecolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED, "axes.labelcolor": INK}


def finish(ax: plt.Axes, label: str) -> None:
    ax.set_title(label, loc="left", fontsize=6.8)
    ax.set_xlabel("Logical qubits")
    ax.set_xticks(WIDTHS)
    ax.grid(color=GRIDC, lw=0.4, zorder=0)
    ax.tick_params(top=False, right=False)


with plt.style.context("lusca"):
    plt.rcParams.update(STYLE)

    # Appendix candidate: absolute losses, log axis.
    fig, axes = plt.subplots(1, 2, figsize=(3.4, 2.0), sharey=True)
    for ax, (t, (label, _)) in zip(axes, TOPO.items()):
        for b in BENCHMARKS:
            for i, a in enumerate(("greedy", "prism")):
                ws = [w for w in WIDTHS if (t, b, w) in cell]
                ax.plot(ws, [cell[(t, b, w)][i] for w in ws], color=COL[a], lw=0.6, alpha=0.75, zorder=2)
        ax.axhline(math.log(100), color=INK, lw=0.6, ls="--", zorder=3)
        ax.set_yscale("log")
        finish(ax, label)
    axes[0].set_ylabel(r"Photon losses per shot ($-\ln P_\mathrm{keep}$)")
    axes[1].annotate("1% of shots kept", (axes[1].get_xlim()[0], math.log(100)), xytext=(2, 2), textcoords="offset points",
                     fontsize=5.6, color=INK, va="bottom", bbox={"fc": "white", "ec": "none", "pad": 0.5})
    axes[0].legend(handles=[plt.Line2D([], [], color=COL[a], lw=1.1, label=NAME[a]) for a in COL], frameon=False, fontsize=5.6, loc="upper left")
    fig.tight_layout(pad=0.3, w_pad=0.5)
    fig.savefig(OUT / "losses_by_width.pdf")
    fig.savefig(OUT / "losses_by_width.png", dpi=300)
    plt.close(fig)

    # Panel (b) candidate: PRISM/Greedy losses, linear axis, styled as the scaling figure. Dotted past the width where Greedy keeps under 1%.
    plt.rcParams.update({"font.size": 7.0, "axes.labelsize": 7.2, "xtick.labelsize": 6.5, "ytick.labelsize": 6.5, "legend.fontsize": 6.0,
                         "axes.edgecolor": "black", "xtick.color": "black", "ytick.color": "black", "axes.labelcolor": "black"})
    fig, axes = plt.subplots(1, 2, figsize=(3.35, 2.0), sharey=True)
    for ax, (t, (label, color)) in zip(axes, TOPO.items()):
        for b in BENCHMARKS:
            for ws, ls in zip(traces(t, b), ("-", ":")):
                if len(ws) > 1 or (ls == "-" and ws):
                    ax.plot(ws, [cell[(t, b, w)][1] / cell[(t, b, w)][0] for w in ws], color=THIN, lw=0.5, ls=ls, zorder=2)
        ws = [w for w in WIDTHS if (w, t) in table]
        mean = [1 - table[(w, t)]["loss_reduction"] for w in ws]
        ax.fill_between(ws, [1 - table[(w, t)]["loss_reduction_ci_high"] for w in ws],
                        [1 - table[(w, t)]["loss_reduction_ci_low"] for w in ws], color=color, alpha=0.2, lw=0, zorder=3)
        ax.plot(ws, mean, color=color, lw=1.35, marker=MARK[t], markersize=3.2, zorder=4)
        ax.axhline(1, color="#303030", lw=0.6, zorder=3)
        ax.set_title(label, loc="left", fontsize=7.3)
        ax.set_xlabel("Logical qubits")
        ax.set_xticks((8, 16, 24, 32))
        ax.grid(color="#dedede", lw=0.5, zorder=0)
    axes[0].set_ylabel("PRISM / Greedy\nphoton losses per shot")
    fig.legend(handles=[plt.Line2D([], [], color="#303030", lw=1.35, label="Geomean, 95% CI"),
                            plt.Line2D([], [], color=THIN, lw=0.6, label="Workload"),
                            plt.Line2D([], [], color=THIN, lw=0.6, ls=":", label="Greedy keeps <1%")],
                   frameon=False, loc="upper center", ncol=3, handlelength=1.6, bbox_to_anchor=(0.5, 1.0))
    fig.tight_layout(pad=0.3, w_pad=0.6, rect=(0, 0, 1, 0.91))
    fig.savefig(OUT / "losses_ratio_by_width.pdf")
    fig.savefig(OUT / "losses_ratio_by_width.png", dpi=300)

for t in TOPO:
    for w in WIDTHS:
        ks = [cell[(t, b, w)] for b in BENCHMARKS if (t, b, w) in cell]
        r = table[(w, t)]
        print(t, w, f"n={len(ks)} viable={sum(k[2] >= VIABLE_KEEP for k in ks)} (table {r['n_viable']})",
              f"ratio {1 - r['loss_reduction']:.3f} workloads {min(k[1] / k[0] for k in ks):.3f}-{max(k[1] / k[0] for k in ks):.3f}")
