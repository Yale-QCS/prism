"""Compare the success-selected probe rows with the error-selected baseline at the same seed (mehta Eq. 1, export_device aggregation)."""
import collections, json, math, sys
import numpy as np
from marabbecca.utils.metrics import device_success

T1 = 4 / (1 / 231 + 1 / 411 + 1 / 652 + 1 / 342)
E = {"crz_control": 4.00e-3, "crz_target": 0.96e-3, "rswap": 7.24e-4, "swap": 7.24e-4, "rx": 7.24e-4}


def load(path, n, seed):
    out = {}
    for line in open(path):
        r = json.loads(line)
        if r.get("success") and r["requested_n"] == n and r["outer_seed"] == seed:
            keep = math.exp(-r["pair_idle_us"] / T1 + sum(c * math.log1p(-E[k]) for k, c in r["pair_touches"].items()))
            _, f = device_success(r["actual_n_logical"], r["duration_ns"], r["program_body_op_counts"])
            out[(r["circuit_name"], r["topology_name"], r["strategy"])] = (1 / keep, keep * f, r["router_inserted_swaps"], r["duration_ns"])
    return out


base = load("artifacts/paper/raw/scale.jsonl", 16, 0)
new = load(sys.argv[1], 16, 0)
keys = sorted(set(base) & set(new))
for topo in ("grid", "hex_lattice"):
    print(topo)
    for arm in ("greedy", "prism"):
        ks = [k for k in keys if k[1] == topo and k[2] == arm]
        for i, name in enumerate(("1/P_keep", "P_keep*F", "SWAPs", "duration")):
            r = math.exp(np.mean([math.log(new[k][i] / base[k][i]) for k in ks if base[k][i] > 0 and new[k][i] > 0]))
            print(f"  {arm:6s} {name:9s} new/old {r:.3f}  ({len(ks)} workloads)")
    for label, d in (("error-selected", base), ("success-selected", new)):
        c = [k[0] for k in keys if k[1] == topo and k[2] == "prism" and (k[0], topo, "greedy") in d]
        r = math.exp(np.mean([math.log(d[(x, topo, "prism")][0] / d[(x, topo, "greedy")][0]) for x in c]))
        print(f"  {label}: PRISM/Greedy 1/P_keep {r:.3f}")
