"""Device-parameter sensitivity figure (reviewers B-2, D-5): PRISM's expected losses relative to Greedy at n = 16 on the hexagonal
lattice over cavity lifetime T1 and beamsplitter duration t_bs, with e_bs = t_bs/T1 + c_bs and the schedules re-timed for t_bs.
One column; a single-hue heatmap (darker is a larger PRISM margin), labelled contours, the measured device marked, literature
ranges as brackets along the axes. Reads only data/sweep.json (analyze.py).

Usage: .venv/bin/python research/rebuttal/sensitivity/figure.py  -> figures/sensitivity.{pdf,png}, figures/collapse.png (diagnostic)
"""
import json
from pathlib import Path

import lusca  # noqa: F401
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

HERE = Path(__file__).resolve().parent
OUT = HERE / "figures"
PREVIEW = Path("/tmp/claude-1000/-home-evm9-prism/2dd78e49-579d-43eb-a274-3feb5ac1a43d/scratchpad/sensitivity2")  # 100 dpi legibility check
D = json.loads((HERE / "data" / "sweep.json").read_text())
M = D["model"]
F = next(f for f in D["field"] if f["n"] == 16 and f["topology"] == "hex_lattice")
T1, TBS, Z = np.array(F["t1_us"]), np.array(F["tbs_ns"]), np.array(F["ratio"])  # Z[t_bs, T1]
BASE = next(c for c in D["baseline"] if c["n"] == 16 and c["topology"] == "hex_lattice")

INK = "#303030"
CMAP = LinearSegmentedColormap.from_list("prism", ["#f2f7f6", "#8fbfb8", "#39877f", "#1d4f49"])  # one hue, light to dark
LEVELS = np.arange(0.82, 0.981, 0.02)
# Literature anchors (README): T1 along the top edge, t_bs along the right edge.
T1_ANCHORS = (("Mehta", 231, 652), ("ms-class 3D", 1000, 2000))  # Chou (about 500 us) lies inside Mehta's range
TBS_ANCHORS = (("Teoh", 50, 100), ("Mehta", 136, 208))

OUT.mkdir(exist_ok=True)
with plt.style.context("lusca"):
    plt.rcParams.update({"font.size": 7.0, "axes.labelsize": 7.2, "xtick.labelsize": 6.5, "ytick.labelsize": 6.5, "pdf.fonttype": 42})
    fig = plt.figure(figsize=(3.35, 2.9))
    ax = fig.add_axes([0.16, 0.13, 0.69, 0.60])
    cax = fig.add_axes([0.16, 0.845, 0.69, 0.03])
    X, Y = np.meshgrid(T1, TBS)
    cf = ax.contourf(X, Y, Z, levels=np.linspace(0.82, 0.98, 33), cmap=CMAP.reversed(), vmin=0.82, vmax=0.98, antialiased=False)
    cs = ax.contour(X, Y, Z, levels=LEVELS, colors=INK, linewidths=0.5)
    ax.clabel(cs, levels=LEVELS[LEVELS > 0.85], fmt=lambda v: f"{v:.2f}", fontsize=6.0, inline=True, inline_spacing=2, colors=INK)  # 0.84 only clips the top-left corner
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(T1.min(), T1.max())
    ax.set_ylim(TBS.min(), TBS.max())
    ax.set_xticks((100, 200, 500, 1000, 2000))
    ax.set_xticklabels(("100", "200", "500", "1000", "2000"))
    ax.set_yticks((50, 100, 200, 500))
    ax.set_yticklabels(("50", "100", "200", "500"))
    ax.minorticks_off()
    ax.set_xlabel("Cavity lifetime $T_1$ ($\\mu$s)")
    ax.set_ylabel("Beamsplitter duration $t_{\\mathrm{bs}}$ (ns)")
    # Measured device.
    ax.plot(M["t1_us_measured"], M["tbs_ns_measured"], marker="*", ms=7, mfc="white", mec=INK, mew=0.8, ls="", zorder=5)
    ax.annotate(f"measured\n{BASE['ratio']:.2f}", (M["t1_us_measured"], M["tbs_ns_measured"]), xytext=(-5, -4), textcoords="offset points",
                fontsize=6.2, ha="right", va="top", color=INK)
    ax.text(0.97, 0.04, "$n$ = 16, hexagonal lattice", transform=ax.transAxes, fontsize=6.5, ha="right", va="bottom", color=INK)
    # Literature brackets outside the axes.
    for label, lo, hi in T1_ANCHORS:
        y = 1.05
        ax.plot([lo, hi], [y, y], transform=ax.get_xaxis_transform(), color=INK, lw=0.7, marker="|", ms=4, mew=0.7, clip_on=False)
        ax.annotate(label, (np.sqrt(lo * hi), y), xycoords=ax.get_xaxis_transform(), xytext=(0, 3), textcoords="offset points", fontsize=6.0, ha="center", va="bottom", color=INK)
    for label, lo, hi in TBS_ANCHORS:
        x = 1.03
        ax.plot([x, x], [lo, hi], transform=ax.get_yaxis_transform(), color=INK, lw=0.7, marker="_", ms=4, mew=0.7, clip_on=False)
        ax.annotate(label, (x, np.sqrt(lo * hi)), xycoords=ax.get_yaxis_transform(), xytext=(4, 0), textcoords="offset points", fontsize=6.0, ha="left", va="center", color=INK, rotation=90)
    cb = fig.colorbar(cf, cax=cax, orientation="horizontal", ticks=(0.82, 0.86, 0.90, 0.94, 0.98))
    cb.ax.xaxis.set_ticks_position("top")
    cb.ax.xaxis.set_label_position("top")
    cb.ax.tick_params(labelsize=6.5, length=2, pad=1)
    cb.outline.set_linewidth(0.5)
    cb.set_label("PRISM expected losses relative to Greedy", fontsize=7.0, labelpad=3)
    fig.savefig(OUT / "sensitivity.pdf")
    fig.savefig(OUT / "sensitivity.png", dpi=300)
    fig.savefig(PREVIEW / "sensitivity_100dpi.png", dpi=100)

    # Diagnostic (not for the paper): every grid cell against rho = t_bs/T1. The vertical thickness of each cloud is the
    # departure from a pure rho dependence (README: the fixed 500 ns CR_z keeps idle time from scaling with t_bs).
    TOPO = {"grid": ("Square grid", "#4c78a8", "o"), "hex_lattice": ("Hexagonal lattice", "#d9902f", "s")}
    MS = {8: 2.0, 12: 3.0, 16: 4.0}
    fig2, ax2 = plt.subplots(figsize=(3.35, 2.4))
    lo_b, hi_b = M["rho_anchor_band"]
    ax2.axvspan(lo_b, hi_b, color="#efefef", zorder=0)
    ax2.axvline(M["rho_measured"], color=INK, lw=0.6, ls=":", zorder=1)
    for n in (8, 12, 16):
        for t, (_, color, marker) in TOPO.items():
            cells = [c for c in D["grid"] if c["n"] == n and c["topology"] == t]
            ax2.plot([c["rho"] for c in cells], [c["ratio"] for c in cells], ls="", marker=marker, ms=MS[n], mfc=color, mec=color, mew=0, alpha=0.75, zorder=3)
    ax2.set_xscale("log")
    ax2.set_xlabel("$\\rho = t_{\\mathrm{bs}} / T_1$")
    ax2.set_ylabel("PRISM expected losses\nrelative to Greedy")
    ax2.grid(color="#dedede", lw=0.5, zorder=0)
    handles = [plt.Line2D([], [], ls="", marker=m, ms=3.6, mfc=c, mec=c, mew=0, label=name) for name, c, m in TOPO.values()]
    handles += [plt.Line2D([], [], ls="", marker="o", ms=MS[n], mfc="#7a7a7a", mec="#7a7a7a", mew=0, label=f"$n$ = {n}") for n in MS]
    fig2.legend(handles=handles[:2], loc="upper center", ncol=2, frameon=False, bbox_to_anchor=(0.56, 1.0), handletextpad=0.3, columnspacing=1.2, fontsize=6.2)
    fig2.legend(handles=handles[2:], loc="upper center", ncol=3, frameon=False, bbox_to_anchor=(0.56, 0.93), handletextpad=0.3, columnspacing=1.2, fontsize=6.2)
    fig2.subplots_adjust(left=0.17, right=0.98, top=0.80, bottom=0.18)
    fig2.savefig(OUT / "collapse.png", dpi=300)
print("measured", BASE["ratio"], "field range", Z.min(), Z.max())
