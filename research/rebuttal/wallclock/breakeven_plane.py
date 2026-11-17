"""Break-even contours on the transmon plane, the separability check, and the figure.

  .venv/bin/python research/rebuttal/wallclock/breakeven_plane.py --width 8 [--fit]

For each dual-rail arm (coupler loss 2e-3), r*(T1) is the transmon CZ average error at
which the transmon matches the arm, on each T1 line of `data/legacy/breakeven_n<width>.jsonl`:
- equal fidelity: geometric-mean 1 - F (no noise-model assumption);
- equal cost: geometric-mean (D + 2 us) / (P_keep F^2) (1/F^2 model).
Geometric means are over workloads of per-workload means over grid, hex_lattice and
seeds, as in `costs.py`. ln(metric) is interpolated linearly in ln r. Intervals are 95%
from 1000 seed resamples, paired between the dual-rail and transmon rows; with
trajectories each resample also redraws every transmon F from its standard error.
`--fit` runs the pre-registered separability check (README, "Break-even transmon").
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ARMS = ("prism", "greedy", "logical")
TOPOLOGIES = ("grid", "hex_lattice")
OVERHEAD_US = 2.0
F_MIN = 1e-6
METRICS = ("infidelity", "cost")

parser = argparse.ArgumentParser()
parser.add_argument("--width", type=int, required=True)
parser.add_argument("--fit", action="store_true", help="separability check")
parser.add_argument("--resamples", type=int, default=1000)
args = parser.parse_args()
rng = np.random.default_rng(0)


def metric_values(f, duration, p_keep=1.0):
    f = np.maximum(f, F_MIN)
    return {"infidelity": 1 - f, "cost": (duration + OVERHEAD_US) / (p_keep * f**2)}


# Dual-rail arms: arm -> metric -> array (circuit, seed)
dual = defaultdict(lambda: defaultdict(list))
for line in (HERE / "data/legacy" / f"rows_n{args.width}_loss0.002.jsonl").open():
    r = json.loads(line)
    if r["topology"] in TOPOLOGIES and r["arm"] in ARMS:
        dual[r["arm"]][(r["circuit"], r["seed"])].append(r)
circuits = sorted({c for c, _ in dual["prism"]})
seeds = sorted({s for _, s in dual["prism"]})

# Transmon plane: (r, t1, t2) -> (circuit, seed) -> rows
plane = defaultdict(lambda: defaultdict(list))
for line in (HERE / "data/legacy" / f"breakeven_n{args.width}.jsonl").open():
    r = json.loads(line)
    plane[(r["r"], r["t1"], r["t2"])][(r["circuit"], r["seed"])].append(r)
points = sorted(plane)
complete = [p for p in points if all(len(plane[p][(c, s)]) == len(TOPOLOGIES) for c in circuits for s in seeds)]
errors = sorted({p[0] for p in complete})
t1s = sorted({p[1] for p in complete if p[1] == p[2]})


def dual_array(arm, metric):
    return np.array([[np.mean([metric_values(x["fidelity"], x["duration_us"], x["p_keep"])[metric] for x in dual[arm][(c, s)]])
                      for s in seeds] for c in circuits])


def plane_arrays(point, fidelity=None):
    """(circuit, seed, topology) fidelity and duration arrays at one point."""
    rows = [[sorted(plane[point][(c, s)], key=lambda x: x["topology"]) for s in seeds] for c in circuits]
    f = np.array([[[x["fidelity"] for x in cell] for cell in row] for row in rows]) if fidelity is None else fidelity
    se = np.array([[[x["fidelity_se"] for x in cell] for cell in row] for row in rows])
    d = np.array([[[x["duration_us"] for x in cell] for cell in row] for row in rows])
    return f, se, d


def gmean_seeds(values, picks):
    """values (circuit, seed[, ...]) already averaged to (circuit, seed); picks (B, seeds) -> (B,) ln geometric mean."""
    return np.log(values[:, picks].mean(axis=2)).mean(axis=0)


def crossing(ln_metric_by_r, target):
    """ln r* where ln metric (increasing in r) crosses target; -inf/inf if outside the grid."""
    ln_r = np.log(errors)
    y = np.asarray(ln_metric_by_r)
    if target < y[0]:
        return -math.inf
    if target > y[-1]:
        return math.inf
    i = int(np.searchsorted(y, target))
    i = max(1, min(i, len(y) - 1))
    return ln_r[i - 1] + (target - y[i - 1]) * (ln_r[i] - ln_r[i - 1]) / (y[i] - y[i - 1])


STARS = {}  # (metric, arm, T1) -> ln r* per resample (index 0: the data) from the last contours() call


def contours(fidelity_by_point=None, resample=True):
    """metric -> arm -> T1 -> (r* point, lo, hi, fraction of resamples inside the grid)."""
    identity = np.arange(len(seeds))[None, :]
    picks = np.vstack([identity, rng.integers(0, len(seeds), (args.resamples, len(seeds)))]) if resample else identity
    trajectories = any(x["shots"] for p in complete[:1] for x in plane[p][(circuits[0], seeds[0])])
    out = {m: {a: {} for a in ARMS} for m in METRICS}
    dual_ln = {(a, m): gmean_seeds(dual_array(a, m), picks) for a in ARMS for m in METRICS}
    for t1 in t1s:
        ln_t = {m: [] for m in METRICS}
        for r in errors:
            f, se, d = plane_arrays((r, t1, t1), None if fidelity_by_point is None else fidelity_by_point[(r, t1, t1)])
            per_b = {m: [] for m in METRICS}
            draws = [f] + ([np.clip(f + se * rng.standard_normal(f.shape), F_MIN, 1) for _ in range(len(picks) - 1)]
                           if trajectories and fidelity_by_point is None and resample else [f] * (len(picks) - 1))
            for b, fb in enumerate(draws):
                vals = metric_values(fb, d)
                for m in METRICS:
                    per_b[m].append(gmean_seeds(vals[m].mean(axis=2), picks[b:b + 1])[0])
            for m in METRICS:
                ln_t[m].append(per_b[m])
        for m in METRICS:
            y = np.array(ln_t[m])  # (errors, B)
            for a in ARMS:
                stars = np.array([crossing(y[:, b], dual_ln[(a, m)][b]) for b in range(len(picks))])
                inside = np.isfinite(stars[1:])
                lo, hi = (np.exp(np.percentile(stars[1:][inside], [2.5, 97.5])) if inside.mean() > 0.5 else (math.nan, math.nan))
                out[m][a][t1] = (float(np.exp(stars[0])), float(lo), float(hi), float(inside.mean()) if resample else 1.0)
                STARS[(m, a, t1)] = stars
    return out


def fmt(entry):
    r, lo, hi, frac = entry
    if r == 0:
        return f"< {errors[0]:.3g}"
    if math.isinf(r):
        return f"> {errors[-1]:.3g}"
    return f"{r:.3g} [{lo:.3g}, {hi:.3g}]" + ("" if frac > 0.97 else f" ({frac:.0%} in grid)")


grid = contours()
summary = {"width": args.width, "errors": errors, "t1": t1s, "contours": {m: {a: {str(t): v for t, v in grid[m][a].items()} for a in ARMS} for m in METRICS}}
for m in METRICS:
    print(f"\n{m} contour r*(T1), n = {args.width}")
    print(f"{'T1 us':>8s} " + " ".join(f"{a:>28s}" for a in ARMS) + f" {'PRISM/Greedy':>13s} {'PRISM/Logical':>14s}")
    for t1 in t1s:
        p, g, l = (grid[m][a][t1][0] for a in ARMS)
        ratio = lambda x, y: f"{x / y:.3f}" if 0 < x < math.inf and 0 < y < math.inf else "—"
        print(f"{t1:8g} " + " ".join(f"{fmt(grid[m][a][t1]):>28s}" for a in ARMS) + f" {ratio(p, g):>13s} {ratio(p, l):>14s}")

# PRISM's contribution: r*_PRISM / r*_other per T1, with the interval from the same paired resamples.
stars = dict(STARS)
summary["prism_ratio"] = {}
for m in METRICS:
    print(f"\nPRISM's shift of the {m} contour, r*_PRISM / r*_other")
    for t1 in t1s:
        cells = []
        for other in ("greedy", "logical"):
            x, y = stars[(m, "prism", t1)], stars[(m, other, t1)]
            both = np.isfinite(x) & np.isfinite(y)
            if not both[0] or both[1:].mean() < 0.5:
                cells.append(f"{other}: —")
                continue
            lo, hi = np.exp(np.percentile((x - y)[1:][both[1:]], [2.5, 97.5]))
            point = float(np.exp(x[0] - y[0]))
            summary["prism_ratio"][f"{m}/{other}/{t1:g}"] = (point, float(lo), float(hi))
            cells.append(f"{other}: {point:.3f} [{lo:.3f}, {hi:.3f}]")
        print(f"  T1 = {t1:6g}: " + ", ".join(cells))

# Dephasing sensitivity at T1 = 200 us: transmon metric at the three r for each T2/T1, against T2 = T1.
sens = [p for p in complete if p[1] == 200.0 and p[1] != p[2]]
if sens:
    print("\nDephasing sensitivity at T1 = 200 us: geometric-mean transmon F")
    for r in sorted({p[0] for p in sens}):
        line = []
        for point in sorted(p for p in complete if p[0] == r and p[1] == 200.0):
            f, _, _ = plane_arrays(point)
            line.append(f"T2={point[2]:g}: {math.exp(np.log(f.mean(axis=(1, 2))).mean()):.4f}")
        print(f"  r = {r:g}: " + ", ".join(line))

if args.fit:
    # ln F = c + a r + b / T1 per transmon circuit (circuit, seed, topology), on the T2 = T1 points.
    fit_points = [(r, t1, t1) for t1 in t1s for r in errors]
    stack = np.array([plane_arrays(p)[0] for p in fit_points])  # (points, circuit, seed, topology)
    design = np.array([[1.0, r, 1 / t1] for r, t1, _ in fit_points])
    ln_f = np.log(np.maximum(stack, F_MIN)).reshape(len(fit_points), -1)
    coef, *_ = np.linalg.lstsq(design, ln_f, rcond=None)
    model = np.exp(design @ coef).reshape(stack.shape)
    resid = (np.log(np.maximum(stack, F_MIN)) - np.log(model)).reshape(len(fit_points), -1)
    print(f"\nSeparability fit: RMS residual of ln F over all {len(fit_points)} points: {np.sqrt((resid**2).mean()):.4f}")
    fitted = contours({p: model[i] for i, p in enumerate(fit_points)}, resample=False)
    verdict = True
    for m in METRICS:
        for a in ARMS:
            for t1 in t1s:
                r, lo, hi, _ = grid[m][a][t1]
                rm = fitted[m][a][t1][0]
                if 0 < r < math.inf and not math.isnan(lo):
                    near = [i for i, p in enumerate(fit_points) if p[1] == t1 and r / 2 <= p[0] <= 2 * r]
                    rms_near = np.sqrt((resid[near] ** 2).mean()) if near else math.nan
                    ok = abs(rm - r) <= (hi - lo) / 2
                    verdict &= ok
                    print(f"  {m:10s} {a:8s} T1={t1:6g}: grid {r:.3g} [{lo:.3g}, {hi:.3g}], model {rm:.3g}, "
                          f"RMS ln F near contour {rms_near:.4f} {'ok' if ok else 'FAIL'}")
    print(f"Separability check: {'ACCEPTED' if verdict else 'REJECTED'}")
    summary["fit"] = {"accepted": bool(verdict), "rms_ln_f": float(np.sqrt((resid**2).mean()))}

(HERE / "data/legacy" / f"breakeven_n{args.width}_contours.json").write_text(json.dumps(summary, indent=1))
