"""Summarize data/swaps/dephasing_n16.jsonl per dephasing point: the median workload-mean retained infidelity 1 - F
of each compiler, and PRISM's infidelity reduction vs Greedy (equal workload weight, mean of the per-workload
1 - mean_P / mean_G) with the 95% paired seed-bootstrap interval, per topology and pooled.
Writes data/swaps/dephasing_n16_summary.json."""
import json, statistics
from collections import defaultdict
from pathlib import Path

import numpy as np

DATA = Path(__file__).resolve().parent / "data/swaps"
rows = [json.loads(line) for line in (DATA / "dephasing_n16.jsonl").open()]
cells = defaultdict(dict)  # (tphi, topology, circuit) -> {seed: {arm: 1 - F}}
for r in rows:
    cells[(round(r["tphi_ms"], 3), r["topology"], r["circuit"])].setdefault(r["seed"], {})[r["arm"]] = 1 - r["fidelity"]


def reduction(groups, rng=None):
    out = []
    for seeds in groups:
        pick = seeds if rng is None else [seeds[i] for i in rng.integers(len(seeds), size=len(seeds))]
        g = np.mean([s["greedy"] for s in pick])
        p = np.mean([s["prism"] for s in pick])
        out.append(1 - p / g)
    return 100 * float(np.mean(out))


summary = []
for tphi in sorted({k[0] for k in cells}):
    for topos in (("grid",), ("hex_lattice",), ("grid", "hex_lattice")):
        groups = [[v for v in cells[k].values() if len(v) == 2] for k in cells if k[0] == tphi and k[1] in topos]
        groups = [g for g in groups if g]
        if not groups:
            continue
        rng = np.random.default_rng(0)
        boot = [reduction(groups, rng) for _ in range(2000)]
        lo, hi = np.percentile(boot, [2.5, 97.5])
        point = reduction(groups)
        summary.append({
            "tphi_ms": tphi, "topology": "+".join(topos), "workloads": len(groups), "pairs": sum(map(len, groups)),
            "median_infidelity_greedy": statistics.median(np.mean([s["greedy"] for s in g]) for g in groups),
            "median_infidelity_prism": statistics.median(np.mean([s["prism"] for s in g]) for g in groups),
            "reduction_pct": point, "ci_low": float(lo), "ci_high": float(hi), "half_width": float((hi - lo) / 2),
        })
        s = summary[-1]
        print(f"T_phi {tphi:5} ms {s['topology']:16} n={s['pairs']:3}  1-F greedy {s['median_infidelity_greedy']:.4f} prism {s['median_infidelity_prism']:.4f}  "
              f"reduction {point:.1f} ± {s['half_width']:.1f}% [{lo:.1f}, {hi:.1f}]")
(DATA / "dephasing_n16_summary.json").write_text(json.dumps(summary, indent=1))
