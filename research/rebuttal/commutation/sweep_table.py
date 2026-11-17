import json, sys, glob, os, math
from collections import defaultdict
from marabbecca.utils.metrics import device_success
SP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
def load(path):
    d = defaultdict(list)
    for l in open(path):
        r = json.loads(l)
        if r["success"] and r["outer_seed"] in (0, 1, 2):
            d[(r["topology_name"], r["strategy"])].append(r)
    return d
runs = {"paper (swaps, order, no resched)": "artifacts/paper/raw/core.jsonl"}
for p in sorted(glob.glob(f"{SP}/*.jsonl")):
    runs[os.path.basename(p)[:-6]] = p
for topo in ("grid", "hex_lattice"):
    print(f"\n== {topo}: Greedy / PRISM sums over 16 workloads x 3 seeds; reduction = PRISM vs Greedy")
    print(f"{'config':34s} {'SWAPs G/P':>13s} {'red':>6s} {'depth G/P':>13s} {'red':>6s} {'duration us G/P':>17s} {'red':>6s}")
    for name, path in runs.items():
        d = load(path); g, p = d[(topo, "greedy")], d[(topo, "prism")]
        if not g or not p: continue
        s = lambda rows, k: sum(r[k] for r in rows)
        out = f"{name:34s}"
        for k, sc in (("router_inserted_swaps", 1), ("physical_depth", 1), ("duration_ns", 1e-3)):
            G, P = s(g, k) * sc, s(p, k) * sc
            out += f" {G:6.0f}/{P:<6.0f} {100*(1-P/G):5.1f}%"
        print(out)
