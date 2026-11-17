"""Pre-registered tests (README.md): Spearman of each feature with the per-cell SWAP reduction, workload-cluster bootstrap.

Usage: .venv/bin/python research/rebuttal/mechanism/analyze.py
"""

import json
import subprocess
from collections import defaultdict
from pathlib import Path

import lusca  # noqa: F401
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import rankdata, spearmanr

HERE = Path(__file__).parent
ROOT = HERE.parents[2]
TOPOLOGIES = ("grid", "hex_lattice", "heavy_hex")
B_SAMPLES = 2000
rng = np.random.default_rng(0)


def reductions(rows):
    tot = defaultdict(lambda: [0.0, 0.0])
    for r in rows:
        if r["strategy"] in ("greedy", "prism"):
            tot[(r["circuit_name"], r["topology_name"])][r["strategy"] == "prism"] += r["router_inserted_swaps"]
    return {k: (1 - p / g, g) for k, (g, p) in tot.items() if g > 0}


def spearman(x, y):
    return spearmanr(x, y).statistic


def partial(x, y, z):
    rx, ry, rz = (rankdata(a) for a in (x, y, z))
    res = lambda a: a - np.polyval(np.polyfit(rz, a, 1), rz)
    return np.corrcoef(res(rx), res(ry))[0, 1]


def cluster_ci(cells, fx, levels=(95, 99)):
    """Bootstrap over workloads, each carrying all its cells."""
    work = sorted({c for c, _ in cells})
    by = defaultdict(list)
    for i, (c, _) in enumerate(cells):
        by[c].append(i)
    stats = []
    for _ in range(B_SAMPLES):
        idx = [i for w in rng.choice(work, len(work)) for i in by[w]]
        stats.append(fx(idx))
    stats = np.array(stats)
    stats = stats[np.isfinite(stats)]
    return {lv: tuple(np.percentile(stats, [(100 - lv) / 2, 100 - (100 - lv) / 2])) for lv in levels}


def main():
    core = reductions(map(json.loads, open(ROOT / "artifacts/paper/raw/core.jsonl")))
    old = subprocess.run(["git", "show", "41fabb1:artifacts/paper/raw/scale.jsonl"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    y32 = reductions(r for r in map(json.loads, old.splitlines()) if r["requested_n"] == 32)
    pred = {r["circuit"]: r for r in json.loads((HERE / "data/predictors.json").read_text())}
    med = defaultdict(lambda: defaultdict(list))
    for r in map(json.loads, open(HERE / "data/mediators.jsonl")):
        key = (r["circuit"], r["topology"])
        med[key]["B"].append(r["prism"]["B"])
        med[key]["D"].append(r["greedy"]["D"])
        med[key]["C"].append(r["greedy"]["C"])
        med[key]["B_G"].append(r["greedy"]["B"])
        med[key]["D_P"].append(r["prism"]["D"])
    cells = sorted(k for k in core if k in med)
    Y = np.array([core[k][0] for k in cells])
    G = np.log([core[k][1] for k in cells])
    feats = {
        "A": np.array([pred[c]["A"] for c, _ in cells]),
        "A_prime": np.array([pred[c]["A_prime"] for c, _ in cells]),
        "B": np.array([np.mean(med[k]["B"]) for k in cells]),
        "D": np.array([np.mean(med[k]["D"]) for k in cells]),
        "C": np.array([np.mean(med[k]["C"]) for k in cells]),
    }
    report = {"n_cells": len(cells), "tests": {}, "reported_only": {}}
    sign = {"A": 1, "A_prime": 1, "B": 1, "D": 1, "C": -1}
    keep = np.array([core[k][1] >= 40 for k in cells])
    for name, x in feats.items():
        rho = spearman(x, Y)
        ci = cluster_ci(cells, lambda i, x=x: spearman(x[i], Y[i]))
        lo, hi = ci[95]
        right = sign[name] * rho > 0 and (lo > 0 if sign[name] > 0 else hi < 0)
        verdict = "supported" if right and abs(rho) >= 0.5 else ("falsified" if not right else "not supported (|rho| < 0.5)")
        if verdict == "supported":
            lo99, hi99 = ci[99]
            if not (lo99 > 0 if sign[name] > 0 else hi99 < 0):
                verdict = "supported (weak: fails Bonferroni 99%)"
        report["tests"][name] = {
            "rho": rho, "ci95": ci[95], "ci99": ci[99], "verdict": verdict,
            "per_graph": {t: spearman(x[[k[1] == t for k in cells]], Y[[k[1] == t for k in cells]]) for t in TOPOLOGIES},
            "partial_given_log_greedy_swaps": partial(x, Y, G),
            "rho_without_low_count_cells": spearman(x[keep], Y[keep]),
        }
        c32 = [k for k in cells if k in y32]
        if name in ("A", "A_prime"):
            x32 = np.array([pred[c][name] for c, _ in c32])
        else:
            x32 = np.array([np.mean(med[k][name]) for k in c32])
        report["tests"][name]["rho_Y32"] = spearman(x32, np.array([y32[k][0] for k in c32]))
    pooled_B = float(np.mean([v for k in cells for v in med[k]["B"]]))
    report["H-d(ii)"] = {"pooled_B": pooled_B, "rho_B_Y": report["tests"]["B"]["rho"],
                        "verdict": "supported" if pooled_B <= 0.2 and abs(report["tests"]["B"]["rho"]) < 0.3 else "falsified"}
    report["seed_spread"] = {
        m: {"median_sd": float(np.median([np.std(med[k][m]) for k in cells])), "max_sd": float(max(np.std(med[k][m]) for k in cells))}
        for m in ("B", "C", "D")
    }
    for m in ("B_G", "D_P"):
        report["reported_only"][m] = {"rho": spearman(np.array([np.mean(med[k][m]) for k in cells]), Y), "mean": float(np.mean([np.mean(med[k][m]) for k in cells]))}
    # Outliers on the best-supported predictor or mediator (largest |rho| among supported, else largest |rho|).
    best = max(feats, key=lambda n: (report["tests"][n]["verdict"].startswith("supported"), abs(report["tests"][n]["rho"])))
    rx, ry = rankdata(feats[best]), rankdata(Y)
    resid = ry - np.polyval(np.polyfit(rx, ry, 1), rx)
    z = resid / resid.std()
    report["outliers"] = {"feature": best, "cells": [{"cell": cells[i], "Y": Y[i], best: feats[best][i], "z": z[i]} for i in np.argsort(-abs(z)) if abs(z[i]) > 2]}
    report["cells"] = [{"cell": k, "Y": Y[i], "greedy_swaps": core[k][1], **{n: feats[n][i] for n in feats}} for i, k in enumerate(cells)]
    (HERE / "data/report.json").write_text(json.dumps(report, indent=1, default=float))
    # Figure: one panel per feature, Y on the y-axis, one color per device graph.
    with plt.style.context("lusca"):
        fig, axes = plt.subplots(1, len(feats), figsize=(12, 2.6), sharey=True)
        for ax, (name, x) in zip(axes, feats.items()):
            for t, col in zip(TOPOLOGIES, ("#39877f", "#d69b32", "#6b6bb0")):
                m = np.array([k[1] == t for k in cells])
                ax.scatter(x[m], 100 * Y[m], s=14, color=col, label=t)
            r = report["tests"][name]
            ax.set_title(f"{name}: ρ={r['rho']:.2f} [{r['ci95'][0]:.2f}, {r['ci95'][1]:.2f}]", fontsize=8)
        axes[0].set_ylabel("SWAP reduction vs Greedy (%)")
        axes[0].legend(fontsize=6, frameon=False)
        fig.tight_layout()
        (HERE / "figures").mkdir(exist_ok=True)
        fig.savefig(HERE / "figures/features.png", dpi=180)
    print(json.dumps({k: v for k, v in report.items() if k != "cells"}, indent=1, default=float))


if __name__ == "__main__":
    main()
