"""Plot every workload's exact circuit infidelity and postselection cost from bare_report.py."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
report = json.loads((HERE / "data/bare_report.json").read_text())
workloads = report["workloads"]
labels = {
    "draper_qft_adder": "Draper", "modular_adder": "mod. adder", "bmw_quark_copula": "copula",
    "cdkm_ripple_carry_adder": "CDKM", "vbe_ripple_carry_adder": "VBE", "vqe_two_local": "VQE",
    "rg_qft_multiplier": "RG mult.", "multiplier": "multiplier", "qftentangled": "QFT ent.",
    "qpeexact": "QPE exact", "qpeinexact": "QPE inexact",
}
arms = {
    "bare_0.001": ("Bare, CZ 0.1%", "#53657c", "v"),
    "bare_0.003": ("Bare, CZ 0.3%", "#334155", "^"),
    "greedy": ("Dual rail, Greedy", "#bd7b1f", "s"),
    "prism": ("Dual rail, PRISM", "#087f73", "o"),
}
plt.rcParams.update({"font.size": 7, "axes.spines.top": False, "axes.spines.right": False,
                     "pdf.fonttype": 42, "ps.fonttype": 42})
fig, (quality, cost) = plt.subplots(2, 1, figsize=(3.45, 3.55), sharex=True)
x = np.arange(len(workloads))
for i, (arm, (label, color, marker)) in enumerate(arms.items()):
    offset = (i - 1.5) * 0.18
    quality.plot(x + offset, [1-w[arm]["fidelity"] for w in workloads.values()],
                 linestyle="", marker=marker, markersize=3, color=color, label=label)
    if arm.startswith("bare"):
        continue
    cost.plot(x + offset, [w[arm]["time_slope"] for w in workloads.values()],
              linestyle="", marker=marker, markersize=3, color=color)
cost.axhline(1, color=arms["bare_0.003"][1], lw=0.8)
cost.text(0.015, 0.96, "Bare: every shot retained", transform=cost.transAxes, color="#334155", fontsize=6, va="top")
quality.set_ylabel("Conditional\ninfidelity 1 − F")
cost.set_ylabel("Attempts per\nretained sample")
quality.set_title("Ideal preparation and terminal checks", fontsize=7)
quality.legend(loc="upper left", bbox_to_anchor=(-0.16, 1.55), ncol=2, frameon=False,
               handletextpad=0.4, columnspacing=1, fontsize=6.4)
cost.set_xticks(x, [labels.get(c, c.upper()) for c in workloads], rotation=60, ha="right", fontsize=6)
for ax in (quality, cost):
    ax.grid(axis="y", color="#dedede", lw=0.5)
    ax.set_xlim(-0.65, len(x)-0.35)
    ax.tick_params(axis="x", length=2)
quality.set_yscale("log")
cost.set_ylim(0.9, 2.95)
cost.set_yticks([1, 1.5, 2, 2.5])
fig.subplots_adjust(left=0.19, right=0.99, bottom=0.24, top=0.79, hspace=0.22)
out = HERE / "data/figures"
out.mkdir(exist_ok=True)
fig.savefig(out / "bare_comparison.pdf")
fig.savefig(out / "bare_comparison.png", dpi=220)
print(out / "bare_comparison.pdf")
