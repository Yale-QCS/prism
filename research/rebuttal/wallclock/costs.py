"""Sampling cost per width: wall-clock to a fixed estimator precision, every arm against the bare transmon.

  .venv/bin/python research/rebuttal/wallclock/costs.py [--overhead 2] [--tag _loss0.002]

The cost of one workload on one arm is (duration + per-shot overhead) / (P_keep * F^2):
shots per kept shot, times time per shot, times the 1/F^2 shot-count penalty of
estimating an expectation value whose signal the noise shrinks by F (global
depolarizing approximation; bare arms have P_keep = 1). Each workload is
averaged over topologies (grid, hex_lattice) and seeds; arms are compared by the
geometric mean of per-workload cost ratios, with a 95% interval from resampling
seeds in pairs across arms. The second criterion needs no error-mitigation
model: the number of workloads whose kept-shot fidelity stays above 0.5.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ARMS = ("logical", "greedy", "prism")
THRESHOLD = 0.5


def load(path: Path) -> dict:
    """circuit -> seed -> arm -> list of rows (one per topology)."""
    out = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for line in path.open():
        r = json.loads(line)
        if r["topology"] in ("grid", "hex_lattice"):
            out[r["circuit"]][r["seed"]][r["arm"]].append(r)
    return out


def cost(rows: list[dict], overhead: float) -> float:
    return float(np.mean([(r["duration_us"] + overhead) / (r["p_keep"] * max(r["fidelity"], 1e-6) ** 2) for r in rows]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overhead", type=float, default=2.0)
    parser.add_argument("--tag", default="", help="row-file suffix, e.g. _loss0.002")
    args = parser.parse_args()
    rng = np.random.default_rng(0)
    for width in (8, 12, 16):
        path = HERE / "data/legacy" / f"rows_n{width}{args.tag}.jsonl"
        if not path.exists():
            continue
        data = load(path)
        circuits = sorted(c for c in data if all(len(data[c][s][a]) == 2 for s in data[c] for a in ARMS))
        if not circuits:
            continue
        seeds = sorted(set.intersection(*(set(data[c]) for c in circuits)))
        picks = rng.integers(0, len(seeds), (2000, len(seeds)))
        # The representative transmon is not simulated at every width (at n = 16 its F is near 0).
        representative = all(len(data[c][s]["bare_transmon"]) == 2 for c in circuits for s in seeds)
        print(f"n={width}: {len(circuits)} workloads, seeds {seeds}; cost relative to the representative transmon (geometric mean, 95% interval)")
        if not representative:
            print("  representative transmon not simulated at this width")
        # log cost ratio arm / transmon, per circuit and seed
        logr = {a: np.array([[math.log(cost(data[c][s][a], args.overhead) / cost(data[c][s]["bare_transmon"], args.overhead)) for s in seeds] for c in circuits]) for a in ARMS} if representative else {}
        for a in logr:
            point = math.exp(logr[a].mean())
            boot = np.exp(logr[a][:, picks].mean(axis=(0, 2)))
            lo, hi = np.percentile(boot, [2.5, 97.5])
            wins = int((logr[a].mean(axis=1) < 0).sum())
            print(f"  {a:12s} {point:8.3f}  [{lo:.3f}, {hi:.3f}]  cheaper than transmon on {wins}/{len(circuits)} workloads")
        # What detection buys on the same schedule (computed, not yet reported): a lost photon leaves its pair in |00>, orthogonal to the ideal state,
        # so dual-rail without detection (same schedule, every shot kept) has fidelity P_keep * F exactly.
        def gm(a, f):
            return math.exp(np.mean([math.log(np.mean([f(r) for s in seeds for r in data[c][s][a]])) for c in circuits]))

        print("  decomposition (geometric means over workloads): fidelity | duration us")
        for a in ("greedy", "prism"):
            print(f"    {a:6s} no detection (P_keep * F)     F {gm(a, lambda r: r['p_keep'] * r['fidelity']):.3f} | D {gm(a, lambda r: r['duration_us']):6.1f}")
            print(f"    {a:6s} with detection (kept shots)   F {gm(a, lambda r: r['fidelity']):.3f} | shots per kept shot {gm(a, lambda r: 1 / r['p_keep']):.3f}")
        # Second transmon point: strong rows at n = 12 from resim.py --strong-transmon, at n = 8 from the sweep.
        strong = defaultdict(list)
        for c in circuits:
            for s in seeds:
                strong[(c, s)] += data[c][s]["strong_transmon"]
        if any(strong.values()):
            pass
        elif width == 8 and (HERE / "data/legacy/sweep_n8.jsonl").exists():
            for line in (HERE / "data/legacy/sweep_n8.jsonl").open():
                r = json.loads(line)
                if r["arm"] == "bare_transmon" and r["variant"] == "strong_transmon":
                    strong[(r["circuit"], r["seed"])].append(r)
        elif (HERE / "data/legacy" / f"rows_n{width}_strong_transmon.jsonl").exists():
            for line in (HERE / "data/legacy" / f"rows_n{width}_strong_transmon.jsonl").open():
                r = json.loads(line)
                strong[(r["circuit"], r["seed"])].append(r)
        if all(len(strong[(c, s)]) == 2 for c in circuits for s in seeds):
            print("  cost relative to the strong transmon (T1 = T2 = 300 us, CZ 1e-3):")
            for a in ARMS:
                lr = np.array([[math.log(cost(data[c][s][a], args.overhead) / cost(strong[(c, s)], args.overhead)) for s in seeds] for c in circuits])
                boot = np.exp(lr[:, picks].mean(axis=(0, 2)))
                lo, hi = np.percentile(boot, [2.5, 97.5])
                print(f"  {a:12s} {math.exp(lr.mean()):8.3f}  [{lo:.3f}, {hi:.3f}]  cheaper on {int((lr.mean(axis=1) < 0).sum())}/{len(circuits)} workloads")
        print(f"  kept-shot fidelity above {THRESHOLD} (workloads, mean over seeds and topologies):")
        for a in (*ARMS, "bare_transmon") if representative else ARMS:
            fids = [np.mean([r["fidelity"] for s in seeds for r in data[c][s][a]]) for c in circuits]
            print(f"  {a:12s} {sum(f > THRESHOLD for f in fids):2d}/{len(circuits)}   suite geometric mean F {math.exp(np.mean(np.log(fids))):.3f}")


if __name__ == "__main__":
    main()
