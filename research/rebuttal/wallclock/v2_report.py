"""PRISM against Greedy and Logical-SABRE on the MEHTA device, per width.

  .venv/bin/python research/rebuttal/wallclock/v2_report.py --widths 8 12

Reads `data/v2_n<width>.jsonl` and the saved circuits. For each width it prints PRISM/Greedy
and PRISM/Logical-SABRE ratios of shots run per kept shot (1/P_keep), duration and
kept-shot infidelity (1 - F), each the geometric mean over workloads of per-workload means
over grid, hex_lattice and seeds, with a 95% interval from 1000 seed resamples paired
between the arms.

1/P_keep = exp(idle / T1) * prod 1/(1 - e) splits into the pairs' idle exposure and the
per-operation erasures (`validate.loss_parts`, counted from the schedule). The
decomposition gives each factor's ratio with the same aggregation, and its share of
ln(1/P_keep ratio). "Duration only" is exp(n D / T1), the ratio if every pair were exposed
for the whole schedule and no operation erased.

The Eq. 2 proxy (`metrics.device_success`, conditional fidelity from the duration and op
counts) is set against the simulated kept-shot infidelity: the median over rows of
simulated / proxy infidelity, and the PRISM ratios computed from each.

Per topology, as in research/rebuttal/scale/HEADLINE.md: each workload's baseline P_keep and
expected photon losses per shot (-ln P_keep, seed mean) for both arms; the reduction PRISM
makes in expected losses over every workload; and baseline / PRISM shots, kept-shot
infidelity and the median simulated / proxy infidelity over the workloads where the baseline
keeps at least 1% of its shots.

Row sources. These rows are the `run.py` compiles in `data/circuits_n<width>/`, simulated on MEHTA
(`data/v2_n<width>.jsonl`: `resim.py --device mehta` at n = 8 and 12, `run.py --device mehta` at 16). The Eq. 1 numbers in research/rebuttal/scale/HEADLINE.md and
`by_width.csv` come from the scale run's own compiles (`artifacts/paper/raw/scale.jsonl`,
quick export `final_scale.jsonl`). Eq. 1 equals the simulated P_keep to 1e-13 on every circuit
(`validate.py` check 3), so any gap between the two tables is a difference in compiled circuits,
not in the model.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

import sim
import validate
from marabbecca.utils.metrics import device_success

HERE = Path(__file__).resolve().parent
TOPOLOGIES = ("grid", "hex_lattice")
PAIRS = (("prism", "greedy"), ("prism", "logical"))
NAME = {"greedy": "Greedy", "logical": "Logical-SABRE"}
VIABLE = 0.01

parser = argparse.ArgumentParser()
parser.add_argument("--widths", type=int, nargs="+", default=[8, 12])
args = parser.parse_args()
rng = np.random.default_rng(0)


def load(width):
    """(arm, circuit) -> seed -> list of per-topology quantity dicts."""
    from qiskit import qpy

    out = defaultdict(lambda: defaultdict(list))
    device = sim.MEHTA
    for line in (HERE / "data" / f"v2_n{width}.jsonl").open():
        r = json.loads(line)
        if r["topology"] not in TOPOLOGIES or r["device"] != device.name:
            continue
        with (HERE / "data" / f"circuits_n{width}" / f"{r['circuit']}_{r['topology']}_{r['seed']}_{r['arm']}.qpy").open("rb") as f:
            n, end, idle, log_erasure = validate.loss_parts(qpy.load(f)[0], device)
        out[(r["arm"], r["circuit"])][r["seed"]].append({
            "topology": r["topology"],
            "P_keep": r["p_keep"],
            "1/P_keep": 1 / r["p_keep"],
            "losses": -math.log(r["p_keep"]),
            "duration": r["duration_us"],
            "1 - F": 1 - r["fidelity"],
            "idle part": math.exp(idle / device.t1),
            "erasure part": math.exp(-log_erasure),
            "duration only": math.exp(n * end / device.t1),
            "proxy 1 - F": 1 - device_success(r["n_logical"], r["duration_us"] * 1000, r["op_counts"])[1],
        })
    return out


def ratio(rows, a, b, key, topology=None, circuits=None):
    """Point ratio a/b and its paired-seed 95% interval, and the per-resample ln ratios.

    `topology` keeps one topology's rows; `circuits` keeps a subset of workloads.
    """
    circuits = sorted(circuits or {c for arm, c in rows if arm == a})
    seeds = sorted({s for per in rows.values() for s in per})
    picks = np.vstack([np.arange(len(seeds))[None, :], rng.integers(0, len(seeds), (1000, len(seeds)))])
    value = {arm: np.array([[np.mean([x[key] for x in rows[(arm, c)][s] if topology in (None, x.get("topology"))]) for s in seeds] for c in circuits]) for arm in (a, b)}
    ln = np.log(value[a][:, picks].mean(axis=2)).mean(axis=0) - np.log(value[b][:, picks].mean(axis=2)).mean(axis=0)
    return math.exp(ln[0]), *np.exp(np.percentile(ln[1:], [2.5, 97.5])), ln


def workload_mean(rows, arm, key, topology):
    """circuit -> mean of `key` over seeds on one topology."""
    return {c: np.mean([x[key] for xs in per.values() for x in xs if x["topology"] == topology])
            for (a, c), per in rows.items() if a == arm}


def viable_report(w, rows):
    """Per topology: the loss-exponent reduction over every workload, and baseline / PRISM shots,
    kept-shot infidelity and simulated / proxy infidelity over the workloads whose baseline keeps
    at least VIABLE of its shots. A workload's keep fraction is 1 / (seed mean of 1/P_keep) and its
    shot ratio the ratio of seed means of 1/P_keep, as in `export_device._by_width` (by_width.csv)."""
    for topology in TOPOLOGIES:
        print(f"\n  n = {w}, {topology}: per workload, baseline P_keep and baseline / PRISM expected losses (-ln P_keep) and shots")
        for b in ("greedy", "logical"):
            shots_per = {arm: workload_mean(rows, arm, "1/P_keep", topology) for arm in ("prism", b)}
            losses = {arm: workload_mean(rows, arm, "losses", topology) for arm in ("prism", b)}
            for c in sorted(shots_per[b]):
                print(f"    {NAME[b]:13s} {c:28s} P_keep {1 / shots_per[b][c]:9.2e}  losses {losses[b][c]:6.2f} / {losses['prism'][c]:6.2f}  "
                      f"shots {shots_per[b][c] / shots_per['prism'][c]:6.3f}")
        for b in ("greedy", "logical"):
            shots_per = {arm: workload_mean(rows, arm, "1/P_keep", topology) for arm in ("prism", b)}
            keep = {c: 1 / v for c, v in shots_per[b].items()}
            losses = {arm: workload_mean(rows, arm, "losses", topology) for arm in ("prism", b)}
            fewer = int(sum(losses["prism"][c] < losses[b][c] for c in keep))
            point, lo, hi, _ = ratio(rows, "prism", b, "losses", topology)
            viable = sorted(c for c in keep if keep[c] >= VIABLE)
            print(f"  n = {w}, {topology}, PRISM against {NAME[b]}")
            print(f"    expected losses reduced {1 - point:.1%} [{1 - hi:.1%}, {1 - lo:.1%}], fewer on {fewer}/{len(keep)} workloads")
            out = {"loss_reduction": (1 - point, 1 - hi, 1 - lo), "fewer_losses": (fewer, len(keep)), "viable": viable}
            if viable:
                shots = {c: shots_per[b][c] / shots_per["prism"][c] for c in viable}
                point, lo, hi, _ = ratio(rows, b, "prism", "1/P_keep", topology, viable)
                f_point, f_lo, f_hi, _ = ratio(rows, b, "prism", "1 - F", topology, viable)
                cells = [x for (a, c), per in rows.items() if a in ("prism", b) and c in viable for xs in per.values() for x in xs if x["topology"] == topology]
                median = float(np.median([x["1 - F"] / x["proxy 1 - F"] for x in cells]))
                print(f"    on {len(viable)} workloads with {NAME[b]} P_keep >= {VIABLE:g}: shots {point:.3f} [{lo:.3f}, {hi:.3f}], "
                      f"median {np.median(list(shots.values())):.3f}, max {max(shots.values()):.3f}; 1 - F {f_point:.3f} [{f_lo:.3f}, {f_hi:.3f}]{' (interval includes 1: not significant)' if f_lo <= 1 <= f_hi else ''}; simulated / proxy 1 - F median {median:.2f}")
                out |= {"shots": (point, lo, hi), "shots_median": float(np.median(list(shots.values()))), "shots_max": max(shots.values()), "1 - F": (f_point, f_lo, f_hi), "sim_over_proxy_median": median}
            summary[f"n{w}/{topology}/{b}_over_prism"] = out


summary = {}
for w in args.widths:
    rows = load(w)
    cells = [x for per in rows.values() for xs in per.values() for x in xs]
    ratios = np.array([x["1 - F"] / x["proxy 1 - F"] for x in cells])
    print(f"\nn = {w}: simulated / Eq. 2 proxy infidelity over {len(cells)} rows: median {np.median(ratios):.2f}, "
          f"range {ratios.min():.2f} to {ratios.max():.2f}, above 1 in {int((ratios > 1).sum())}")
    summary[f"n{w}/sim_over_proxy"] = (float(np.median(ratios)), float(ratios.min()), float(ratios.max()))
    print(f"\nn = {w} (MEHTA; {len({c for _, c in rows})} workloads, grid and hex_lattice, seeds {sorted({s for per in rows.values() for s in per})})")
    for a, b in PAIRS:
        print(f"  PRISM / {NAME[b]}")
        result = {}
        for key in ("1/P_keep", "duration", "1 - F", "proxy 1 - F", "idle part", "erasure part", "duration only"):
            point, lo, hi, ln = ratio(rows, a, b, key)
            result[key] = (point, lo, hi, ln)
            print(f"    {key:14s} {point:.4f} [{lo:.4f}, {hi:.4f}]")
        total = result["1/P_keep"][3]
        for key in ("idle part", "erasure part", "duration only"):
            share = result[key][3] / total
            lo, hi = np.percentile(share[1:], [2.5, 97.5])
            print(f"    share of ln(1/P_keep ratio) from {key:13s} {share[0]:.2f} [{lo:.2f}, {hi:.2f}]")
        summary[f"n{w}/prism_over_{b}"] = {k: v[:3] for k, v in result.items()}
    viable_report(w, rows)

(HERE / "data" / "v2_report.json").write_text(json.dumps(summary, indent=1))

# H1 one-at-a-time sweep around MEHTA at n = 8 (`sweep.py --device mehta`): PRISM/Greedy per variant.
sweep = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))  # (variant, value) -> (arm, circuit) -> seed -> rows
path = HERE / "data" / "v2_sweep_n8.jsonl"
if path.exists():
    for line in path.open():
        r = json.loads(line)
        if r["arm"] in ("prism", "greedy", "logical"):
            sweep[(r["variant"], r["value"])][(r["arm"], r["circuit"])][r["seed"]].append(
                {"1/P_keep": 1 / r["p_keep"], "losses": -math.log(r["p_keep"]), "duration": r["duration_us"], "1 - F": 1 - r["fidelity"]})
    print("\nH1 sweep at n = 8, PRISM / Greedy [95% paired seed interval]; PRISM's absolute P_keep and 1 - F")
    for (variant, value), rows in sorted(sweep.items(), key=lambda kv: (kv[0][0] != "default", kv[0])):
        cells = [f"{k} {p:.3f} [{lo:.3f}, {hi:.3f}]" for k in ("1/P_keep", "duration", "1 - F") for p, lo, hi, _ in [ratio(rows, "prism", "greedy", k)]]
        p, lo, hi, _ = ratio(rows, "prism", "greedy", "losses")
        cells.append(f"losses reduced {1 - p:.1%} [{1 - hi:.1%}, {1 - lo:.1%}]")
        prism = [x for (a, _), per in rows.items() if a == "prism" for xs in per.values() for x in xs]
        keep = math.exp(np.mean([math.log(1 / x["1/P_keep"]) for x in prism]))
        infid = math.exp(np.mean([math.log(x["1 - F"]) for x in prism]))
        print(f"  {variant:20s} {value:7g}  " + "  ".join(cells) + f"  P_keep {keep:.3f}  1-F {infid:.4f}")
        summary[f"sweep/{variant}/{value:g}"] = {k: ratio(rows, "prism", "greedy", k)[:3] for k in ("1/P_keep", "losses", "duration", "1 - F")}
    (HERE / "data" / "v2_report.json").write_text(json.dumps(summary, indent=1))
