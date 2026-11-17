"""§5.3 ablations on the final settings (s53/README.md §3): one statistic per restated sentence.

Greedy and PRISM rows are the §5.2 suite rows (export_suite.load). The ablation arms come from
raw/s53_{front_commit,tiebreak,slack,excluded}.jsonl.

Usage: .venv/bin/python research/rebuttal/s53/export.py  -> artifacts/paper/paper_export/s53/{summary.json,per_cell.csv}
"""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/paper"))
from export_suite import RAW, TOPOLOGIES, bootstrap_interval, equal_weight_interval, load, values  # noqa: E402

OUT = ROOT / "artifacts/paper/paper_export/s53"
SW, DEPTH, DUR = "router_inserted_swaps", "physical_depth", "duration_ns"
GRIDS = ("grid", "grid_25", "grid_36")


def rows(name: str) -> list:
    return [r for r in map(json.loads, (RAW / name).open()) if r["success"]]


def aggregate(runs: dict, seeds: list, a: str, b: str, metric: str, t: str, members: list) -> dict:
    """Reduction of arm b against arm a: equal weight over workloads (headline) and summed, with paired seed intervals."""
    pairs = [(values(runs[(w, t)], seeds, a, metric), values(runs[(w, t)], seeds, b, metric)) for w in members]
    pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
    A, B = np.array([x for x, _ in pairs]), np.array([y for _, y in pairs])
    sa, sb = A.mean(1), B.mean(1)
    return {
        "workloads": len(pairs),
        "equal_weight": float(np.mean([1 - y / x for x, y in zip(sa, sb) if x > 0])),
        "equal_weight_ci": equal_weight_interval(A, B),
        "sum": float(1 - sb.sum() / sa.sum()),
        "sum_ci": bootstrap_interval(A, B),
        "a_sum_of_means": float(sa.sum()),
    }


def kept(row: dict) -> int:
    """Index of the start route selection keeps: lowest (score, active gates, size)."""
    scores = row["search_trace"]["final_scores"]
    return min(range(len(scores)), key=lambda i: tuple(scores[i]))


runs, source, width, seeds = load()
workloads = sorted(width, key=lambda w: (source[w] != "mqt", width[w], w))
mqt = [w for w in workloads if source[w] == "mqt"]
for name, arm in (("s53_front_commit.jsonl", "front"), ("s53_tiebreak.jsonl", "tiebreak")):
    for r in rows(name):
        runs[(r["circuit_name"], r["topology_name"])][(r["outer_seed"], arm)] = r
for r in rows("s53_slack.jsonl"):
    runs[(r["circuit_name"], r["topology_name"])][(r["outer_seed"], r["strategy"])] = r
cells = [(w, t) for w in workloads for t in TOPOLOGIES]
missing = [(w, t, s, a) for w, t in cells for s in seeds for a in ("front", "tiebreak") if (s, a) not in runs[(w, t)]]
missing += [(w, t, s, a) for w in mqt for t in GRIDS[1:] for s in seeds for a in ("greedy", "prism") if (s, a) not in runs[(w, t)]]
if missing:
    raise SystemExit(f"{len(missing)} runs missing, e.g. {missing[:4]}")

summary: dict = {"workloads": len(workloads), "seeds": len(seeds), "paired_runs": len(cells) * len(seeds)}
per_cell = []
for w, t in cells:
    entry = {"workload": w, "topology": t}
    for a, b in (("greedy", "front"), ("front", "prism"), ("greedy", "prism"), ("greedy", "tiebreak")):
        for m in (SW, DEPTH, DUR):
            x, y = values(runs[(w, t)], seeds, a, m), values(runs[(w, t)], seeds, b, m)
            if x is None or y is None:
                continue
            low, high = bootstrap_interval(x[None], y[None])
            entry |= {f"{a}_{m}": x.mean(), f"{b}_{m}": y.mean(), f"{b}_vs_{a}_{m}": 1 - y.sum() / x.sum() if x.sum() else 0.0,
                      f"{b}_vs_{a}_{m}_low": low, f"{b}_vs_{a}_{m}_high": high}
    per_cell.append(entry)

# l.66: front-commit against Greedy, PRISM against front-commit, regressions.
l66 = {}
for t in TOPOLOGIES:
    run = [(runs[(w, t)][(s, "greedy")][SW], runs[(w, t)][(s, "front")][SW], runs[(w, t)][(s, "prism")][SW]) for w in workloads for s in seeds]
    regress = [(g, p) for g, f, p in run if f > g]
    tc = [c for c in per_cell if c["topology"] == t]
    cell_regress = [c for c in tc if c[f"front_{SW}"] > c[f"greedy_{SW}"]]
    l66[t] = {
        "front_vs_greedy": aggregate(runs, seeds, "greedy", "front", SW, t, workloads),
        "prism_vs_front": aggregate(runs, seeds, "front", "prism", SW, t, workloads),
        "prism_vs_greedy": aggregate(runs, seeds, "greedy", "prism", SW, t, workloads),
        "runs": len(run),
        "prism_fewer_than_front": sum(p < f for _, f, p in run),
        "prism_more_than_front": sum(p > f for _, f, p in run),
        "front_regress_runs": len(regress),
        "removed_runs": sum(p <= g for g, p in regress),
        "added_runs": sum(p > g and f <= g for g, f, p in run),
        "front_regress_cells": [c["workload"] for c in cell_regress],
        "front_regress_cells_ci_below_zero": [c["workload"] for c in cell_regress if c[f"front_vs_greedy_{SW}_high"] < 0],
        "removed_cells": [c["workload"] for c in cell_regress if c[f"prism_{SW}"] <= c[f"greedy_{SW}"]],
        "added_cells": [c["workload"] for c in tc if c[f"prism_{SW}"] > c[f"greedy_{SW}"] and c[f"front_{SW}"] <= c[f"greedy_{SW}"]],
    }
summary["l66"] = l66

# l.68: PRISM with Greedy's tie-break. Per start, the lowering fixes CR_z and RSWAP counts, so active gates track SWAPs.
l68 = {t: {"start_pairs": 0, "start_pairs_equal_swaps": 0, "runs_kept_start_differs": 0, "runs_swaps_differ": 0} for t in TOPOLOGIES}
for (w, t) in cells:
    for s in seeds:
        p, q = runs[(w, t)][(s, "prism")], runs[(w, t)][(s, "tiebreak")]
        a, b = p["search_trace"]["final_scores"], q["search_trace"]["final_scores"]
        l68[t]["start_pairs"] += len(a)
        l68[t]["start_pairs_equal_swaps"] += sum(x[1] == y[1] for x, y in zip(a, b))
        l68[t]["runs_kept_start_differs"] += kept(p) != kept(q)
        l68[t]["runs_swaps_differ"] += p[SW] != q[SW]
for t in TOPOLOGIES:
    l68[t] |= {f"{arm}_{m}": aggregate(runs, seeds, "greedy", arm, m, t, workloads) for arm in ("prism", "tiebreak") for m in (DEPTH, DUR)}
summary["l68"] = l68

# l.70: larger grids, the 16 MQT workloads; the 20-site grid is the core rows.
l70 = {}
for t in GRIDS:
    tc = [(values(runs[(w, t)], seeds, "greedy", SW), values(runs[(w, t)], seeds, "prism", SW)) for w in mqt]
    ci = [bootstrap_interval(g[None], p[None]) for g, p in tc]
    l70[t] = aggregate(runs, seeds, "greedy", "prism", SW, t, mqt) | {
        "lower": sum(p.mean() < g.mean() for g, p in tc),
        "tied": sum(p.mean() == g.mean() for g, p in tc),
        "higher": sum(p.mean() > g.mean() for g, p in tc),
        "ci_above_zero": sum(lo > 0 for lo, _ in ci),
    }
for t in GRIDS[1:]:
    l70[t]["greedy_change_from_grid"] = l70[t]["a_sum_of_means"] / l70["grid"]["a_sum_of_means"] - 1
summary["l70"] = l70

# §5.1: the nine excluded workloads.
exc = defaultdict(lambda: defaultdict(list))
for r in rows("s53_excluded.jsonl"):
    exc[r["topology_name"]][r["strategy"]].append(r[SW])
summary["excluded"] = {t: {a: {"runs": len(v), "max_swaps": max(v), "nonzero_runs": sum(x > 0 for x in v)} for a, v in d.items()} for t, d in exc.items()}
# Adding the nine to the suite's summed SWAP totals: sum of per-workload seed means, Greedy and PRISM.
for t in TOPOLOGIES:
    g, p = (sum(values(runs[(w, t)], seeds, a, SW).mean() for w in workloads) for a in ("greedy", "prism"))
    eg, ep = (sum(exc[t][a]) / len(seeds) for a in ("greedy", "prism"))
    summary["excluded"][t] |= {"greedy_added_swaps": eg, "prism_added_swaps": ep, "suite_greedy_swaps": g,
                               "sum_reduction": 1 - p / g, "sum_reduction_with_excluded": 1 - (p + ep) / (g + eg)}

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "summary.json").write_text(json.dumps(summary, indent=1, default=lambda o: o.item()))
keys = list(dict.fromkeys(k for c in per_cell for k in c))
with (OUT / "per_cell.csv").open("w", newline="") as f:
    writer = csv.DictWriter(f, keys)
    writer.writeheader()
    writer.writerows(per_cell)
print(json.dumps(summary, indent=1, default=lambda o: o.item()))
