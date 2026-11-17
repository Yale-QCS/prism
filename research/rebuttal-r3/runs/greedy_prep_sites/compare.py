"""Greedy (published) vs Greedy with greedy_prep_sites, and PRISM's reduction against each, on the 240-run sample."""
import os as _os
HERE = _os.path.dirname(_os.path.abspath(__file__)) + "/"
ROOT = _os.path.abspath(_os.path.join(HERE, "../../../..")) + "/"
import json, sys, collections
import numpy as np
sys.path.insert(0, ROOT + "scripts/paper")
from paper_common import bootstrap_interval
D = HERE + ""
base = [json.loads(l) for l in open(D + "probe.jsonl")]
new = [json.loads(l) for l in open(D + "probe_prepsites.jsonl")]
assert all(x["prep_flag"] for x in new) and len(new) == 120
K = lambda x: (x["circuit"], x["topology"], x["seed"])
G = {K(x): x for x in base if x["arm"] == "greedy"}
P = {K(x): x for x in base if x["arm"] == "prism"}
N = {K(x): x for x in new}
work = sorted({k[0] for k in G}); seeds = sorted({k[2] for k in G})
tops = ["grid", "hex_lattice", "heavy_hex"]
def arr(src, m, ts):
    return np.array([[src[(w, t, s)][m] for s in seeds] for t in ts for w in work], float)
for m, lab in (("router_swaps", "routing SWAPs"), ("final_depth", "physical depth"), ("final_duration", "duration ns")):
    print(f"\n== {lab} ==")
    print("graph | Greedy pub mean | Greedy prep-sites mean | change | PRISM mean | PRISM red. vs pub [95%] | vs prep-sites [95%] | equal-wt vs pub | vs prep-sites | runs better/tie/worse")
    for ts, name in [([t], t) for t in tops] + [(tops, "pooled")]:
        g, n, p = arr(G, m, ts), arr(N, m, ts), arr(P, m, ts)
        lo1, hi1 = bootstrap_interval(g, p); lo2, hi2 = bootstrap_interval(n, p)
        ew = lambda a: np.mean([1 - p[i].sum() / a[i].sum() for i in range(len(a)) if a[i].sum() > 0])
        b = int((n < g).sum()); t_ = int((n == g).sum()); wv = int((n > g).sum())
        print(f"{name} | {g.mean():.2f} | {n.mean():.2f} | {100*(n.sum()/g.sum()-1):+.2f}% | {p.mean():.2f} | {100*(1-p.sum()/g.sum()):.1f}% [{100*lo1:.1f}, {100*hi1:.1f}] | {100*(1-p.sum()/n.sum()):.1f}% [{100*lo2:.1f}, {100*hi2:.1f}] | {100*ew(g):.1f}% | {100*ew(n):.1f}% | {b}/{t_}/{wv}")
print("\n== per workload, routing SWAPs summed over 3 graphs x 5 seeds (Greedy pub -> prep-sites, PRISM) ==")
for w in work:
    f = lambda src: sum(src[(w, t, s)]["router_swaps"] for t in tops for s in seeds)
    print(f"{w}: {f(G)} -> {f(N)}  (PRISM {f(P)})")
S = sum(x["router_swaps"] for x in new); ab = sum(x["absorbable"] for x in new)
tu = sum(v for x in new for k, v in x["swap_cat"].items() if "U" in k)
print(f"\nU3a with prep-sites Greedy: {S} SWAPs, absorbable {ab} = {100*ab/S:.2f}% ({sum(x['absorbable']>0 for x in new)} runs), touch-U {tu} = {100*tu/S:.2f}%")
print("prep-order violations", sum(sum(x["prep_order_violations_route"]) for x in new), collections.Counter(json.dumps(x["prep_order_violations_final"]) for x in new))
