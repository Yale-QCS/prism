"""Aggregate the rows of flag_memory.py with paired seed-bootstrap intervals. Usage: report.py NOISE [NOISE ...]"""
import json
from pathlib import Path
import sys

import numpy as np
from scipy.stats import bootstrap

HERE = Path(__file__).resolve().parent
PUBLISHED = HERE.parents[2] / "rebuttal" / "outer_qec" / "data" / "mehta_memory"
SEEDS = range(0, 2000, 100)
NAMES = dict(ideal="(a) ideal per-site flags", readout="(b) flags at readout only",
             checks="(c) compiled checks, rounds 1-2", checks3="(c') compiled checks, all 3 rounds")


def line(label, greedy, prism):
    """One table row: pooled P_L per arm and the paired relative reduction with its 95% bootstrap interval."""
    a, b = (np.array([r["errors"] / r["shots"] for r in arm]) for arm in (greedy, prism))
    interval = bootstrap((a, b), lambda x, y, axis=-1: 1 - y.mean(axis) / x.mean(axis), paired=True, vectorized=True,
                         n_resamples=20_000, method="percentile", rng=np.random.default_rng(745)).confidence_interval
    low, high = interval.low, interval.high  # resamples routing seeds, both arms together
    mean = lambda rows, key: np.mean([r[key] for r in rows])
    return (f"| {label} | {100 * a.mean():.4f} | {100 * b.mean():.4f} | {100 * (1 - b.mean() / a.mean()):.1f} "
            f"[{100 * low:.1f}, {100 * high:.1f}] | {int((b < a).sum())}/{int((b == a).sum())}/{int((b > a).sum())} "
            f"| {mean(greedy, 'swaps'):.2f} → {mean(prism, 'swaps'):.2f} "
            f"| {mean(greedy, 'duration_us'):.2f} → {mean(prism, 'duration_us'):.2f} "
            f"| {mean(greedy, 'score'):.4f} → {mean(prism, 'score'):.4f} | {greedy[0]['shots']:,} |")


HEADER = ("| Protocol | Greedy P_L (%) | PRISM P_L (%) | Relative reduction (%) [95%] | Seeds PRISM lower/equal/higher "
          "| SWAPs G → P | Duration (µs) G → P | Route score G → P | Shots per route |\n|---|---|---|---|---|---|---|---|---|")

for basis in "XZ":
    print(f"\n**{basis} memory, hexagonal lattice**\n\n{HEADER}")
    old = [[json.loads((PUBLISHED / f"{basis}_hex_lattice_{arm}_{s}.json").read_text()) for s in SEEDS] for arm in ("greedy", "prism")]
    for rows in old:
        for r in rows:
            r["swaps"] = r["metrics"]["swaps"]
    print(line("published Table II", *old))
    for noise in sys.argv[1:]:
        for protocol, name in NAMES.items():
            paths = [[HERE / f"rows_{noise}" / f"{protocol}_{basis}_{arm}_{s}.json" for s in SEEDS] for arm in ("greedy", "prism")]
            if all(p.exists() for arm in paths for p in arm):
                print(line(f"{name}, noise `{noise}`", *([json.loads(p.read_text()) for p in arm] for arm in paths)))
