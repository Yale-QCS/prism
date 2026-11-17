"""Recompute the §5.1 exclusion, §5.2 per-run and §5.3 ablation numbers from the raw rows."""
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

RAW = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "artifacts/paper/raw"
# Row-file suffix: "_swaps" reads the SWAP-selected re-run of 2026-10-11 (research/rebuttal/suite/swaps/), "" the J-selected rows.
SUFFIX = sys.argv[2] if len(sys.argv) > 2 else "_swaps"
TOPOS = ("grid", "hex_lattice")
CORE_TOPOS = (*TOPOS, "heavy_hex")
SEEDS = range(0, 2000, 100)


def load(name):
    rows = {}
    for line in open(RAW / f"{name}{SUFFIX}.jsonl"):
        r = json.loads(line)
        rows[(r["strategy"], r["circuit_name"], r["topology_name"], r["outer_seed"])] = r
    return rows


def swaps(rows, arm, c, topo, s, metric="router_inserted_swaps"):
    return rows[(arm, c, topo, s)][metric]


def cell_means(rows, arm, circs, topo, metric="router_inserted_swaps"):
    return {c: statistics.mean(swaps(rows, arm, c, topo, s, metric) for s in SEEDS) for c in circs}


def reduction(base, new):
    return 100 * (1 - sum(new.values()) / sum(base.values()))


def wtl(base, new):
    return Counter("W" if new[c] < base[c] else "T" if new[c] == base[c] else "L" for c in base)


core = load("core")
circs = sorted({k[1] for k in core})

# §5.1: randomcircuit and the nine excluded workloads
rc = load("randomcircuit")
for topo in TOPOS:
    g = cell_means(rc, "greedy", ["randomcircuit"], topo)
    p = cell_means(rc, "prism", ["randomcircuit"], topo)
    print(f"randomcircuit {topo}: greedy {g['randomcircuit']:.1f} prism {p['randomcircuit']:.1f} reduction {reduction(g, p):.1f}%")
ex = load("excluded")
by_arm = defaultdict(list)
for (arm, _, _, _), r in ex.items():
    by_arm[arm].append(r["router_inserted_swaps"])
for arm, v in sorted(by_arm.items()):
    print(f"excluded nine {arm}: {sum(x > 0 for x in v)} of {len(v)} runs nonzero, max {max(v)}")

# §5.2: per-run SWAP regressions of PRISM against Greedy
deltas = [swaps(core, "prism", c, t, s) - swaps(core, "greedy", c, t, s) for c in circs for t in CORE_TOPOS for s in SEEDS]
worse = [d for d in deltas if d > 0]
print(f"core runs: PRISM more SWAPs in {len(worse)} of {len(deltas)} (max +{max(worse, default=0)})")
sc = {(r["strategy"], r["circuit_name"], r["requested_n"], r["topology_name"], r["outer_seed"]): r["router_inserted_swaps"] for r in map(json.loads, open(RAW / "scale.jsonl"))}
worse = [v - sc[("greedy", *k[1:])] for k, v in sc.items() if k[0] == "prism" and v > sc[("greedy", *k[1:])]]
print(f"scale runs: PRISM more SWAPs in {len(worse)} of {len(sc) // 2} (max +{max(worse, default=0)})")
for topo in CORE_TOPOS:
    g = cell_means(core, "greedy", circs, topo, "physical_depth")
    p = cell_means(core, "prism", circs, topo, "physical_depth")
    reg = {c: p[c] - g[c] for c in circs if p[c] > g[c]}
    print(f"core depth {topo}: regressions {', '.join(f'{c} +{d:.2f}' for c, d in reg.items()) or 'none'}")

# §5.3: front-layer commit
fc = load("front_commit")
pairs = [(c, t, s) for c in circs for t in TOPOS for s in SEEDS]
for topo in TOPOS:
    g = cell_means(core, "greedy", circs, topo)
    a = cell_means(fc, "prism_front_commit", circs, topo)
    p = cell_means(core, "prism", circs, topo)
    print(f"front_commit {topo}: ablated-vs-greedy {reduction(g, a):.1f}%  full-vs-ablated {reduction(a, p):.1f}%  "
          f"ablated-vs-greedy means {dict(wtl(g, a))}  full-vs-greedy means {dict(wtl(g, p))}")
fa = {k: swaps(fc, "prism_front_commit", *k) for k in pairs}
pr = {k: swaps(core, "prism", *k) for k in pairs}
gr = {k: swaps(core, "greedy", *k) for k in pairs}
print(f"front_commit runs: PRISM fewer than ablated in {sum(pr[k] < fa[k] for k in pairs)}, more in {sum(pr[k] > fa[k] for k in pairs)} of {len(pairs)}")
abl_reg = {k for k in pairs if fa[k] > gr[k]}
pr_reg = {k for k in pairs if pr[k] > gr[k]}
print(f"front_commit runs: ablated more than Greedy in {len(abl_reg)}; PRISM removes {len(abl_reg - pr_reg)} of them and adds {len(pr_reg - abl_reg)}")

# §5.3: tie-break
tb = load("tiebreak")
same = sum(swaps(tb, "prism", *k) == pr[k] for k in pairs)
print(f"tiebreak: SWAP count identical to core PRISM in {same} of {len(pairs)} runs")
for topo in TOPOS:
    g = cell_means(core, "greedy", circs, topo, "physical_depth")
    p = cell_means(core, "prism", circs, topo, "physical_depth")
    d = cell_means(tb, "prism", circs, topo, "physical_depth")
    print(f"tiebreak {topo}: depth reduction {reduction(g, p):.1f}% -> {reduction(g, d):.1f}%")

# §5.3: device slack
sl = load("slack")
for rows, topo in ((core, "grid"), (sl, "grid_25"), (sl, "grid_36")):
    g = cell_means(rows, "greedy", circs, topo)
    p = cell_means(rows, "prism", circs, topo)
    print(f"slack {topo}: greedy mean {statistics.mean(g.values()):.2f}  reduction {reduction(g, p):.1f}%  {dict(wtl(g, p))}")

# §5.2 and §5.4 numbers the exporters leave as arithmetic on their CSVs
EXPORT = RAW.parent / "paper_export"
if (EXPORT / "core/absolute_metrics.csv").exists():
    import csv

    absolute = {(r["topology"], r["metric"], r["strategy"]): float(r["mean"]) for r in csv.DictReader(open(EXPORT / "core/absolute_metrics.csv"))}
    for topo in CORE_TOPOS:
        lo = {m: absolute[(topo, m, "logical")] for m in ("router_inserted_swaps", "physical_depth")}
        out = [f"{arm} {m.split('_')[-1]} {100 * (1 - absolute[(topo, m, arm)] / lo[m]):.1f}%" for arm in ("greedy", "prism") for m in lo]
        print(f"vs Logical-SABRE {topo}: {', '.join(out)}")
    for r in csv.DictReader(open(EXPORT / "core/controlled_comparison.csv")):
        print(f"core {r['topology']} {r['metric']}: {100 * float(r['suite_total_reduction']):.1f}% "
              f"(95% CI {100 * float(r['suite_ci_low']):.1f}-{100 * float(r['suite_ci_high']):.1f}%)")
    scaling = [r for r in csv.DictReader(open(EXPORT / "scaling/scaling_summary.csv")) if r["metric"] == "router_inserted_swaps"]
    print(f"scale runs: PRISM more SWAPs in {sum(int(r['runs_worse']) for r in scaling)} of {sum(int(r['runs']) for r in scaling)}")
    for r in scaling:
        if r["width"] == "32":
            print(f"scale n=32 {r['topology']}: {100 * float(r['suite_total_reduction']):.1f}% "
                  f"(95% CI {100 * float(r['suite_ci_low']):.1f}-{100 * float(r['suite_ci_high']):.1f}%)")
    summary = [r for r in csv.DictReader(open(EXPORT / "device/summary.csv")) if r["width"] == "16"]
    per_workload = [r for r in csv.DictReader(open(EXPORT / "device/per_workload.csv")) if r["width"] == "16"]
    for r in summary:
        topo = r["topology"]
        rswap = {arm: statistics.mean(float(w["mean_n_routing_rswap"]) for w in per_workload if w["topology"] == topo and w["strategy"] == arm) for arm in ("greedy", "prism")}
        print(f"device n=16 {topo}: {rswap['greedy'] - rswap['prism']:.1f} fewer routing exchanges, "
              f"Greedy needs {100 / (1 - float(r['duration_geomean_ratio_reduction'])) - 100:.1f}% longer lifetime, "
              f"keep greedy {float(r['greedy_keep_probability_mean']):.3f} prism {float(r['prism_keep_probability_mean']):.3f}")
