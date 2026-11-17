"""Sum over the 17 workloads of the 5-seed mean router_inserted_swaps per matching, for the old (baseline-check) and budget probes."""
import os as _os
HERE = _os.path.dirname(_os.path.abspath(__file__)) + "/"
ROOT = _os.path.abspath(_os.path.join(HERE, "../../../..")) + "/"
import json, collections, sys
import numpy as np
for name, path in [("old 20/4/20", HERE + "p3_matchings_{}.jsonl"), ("new 40/16/40", HERE + "p3_matchings_budget.jsonl")]:
    rows = []
    for t in ("grid", "heavy_hex"):
        rows += [r for r in map(json.loads, open(path.format(t)))] if "{}" in path else []
    if "{}" not in path:
        rows = list(map(json.loads, open(path)))
    print("==", name)
    for t in ("grid", "heavy_hex"):
        by = collections.defaultdict(lambda: collections.defaultdict(list)); fails = collections.Counter()
        for r in rows:
            if r["topology"] != t: continue
            if r["ok"]: by[r["match_seed"]][r["circuit"]].append(r["router_inserted_swaps"])
            else: fails[r["match_seed"]] += 1
        sums = {}
        for ms, d in by.items():
            if len(d) == 17 and all(len(v) == 5 for v in d.values()):
                sums[ms] = sum(np.mean(v) for v in d.values())
        dflt = sums[None]; alts = {k: v for k, v in sums.items() if k is not None}
        lo, hi = min(alts.values()), max(alts.values())
        print(t, f"default {dflt:.1f}", f"alts {lo:.1f}..{hi:.1f} ({100*(lo/dflt-1):+.1f}% .. {100*(hi/dflt-1):+.1f}%)",
              f"lower than default {sum(v < dflt for v in alts.values())} of {len(alts)}", "unplaceable matchings", sorted(k for k in fails if fails[k] == 85), "failed runs", dict(fails))
        print("   per matching:", {k: round(v, 1) for k, v in sums.items()})
