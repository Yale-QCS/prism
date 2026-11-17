"""Numbers for Section V-D over all three graphs (Eq. 17/18 on saved SWAP-selected circuits)."""
import json, math, statistics as st
from collections import defaultdict
from pathlib import Path
import numpy as np
REPO = Path(__file__).resolve().parents[3]; HH = REPO / "research/rebuttal/sensitivity/data/swaps/heavy_hex"
T1, EC, ET, EBS, TBS = 356.512171, 4.0e-3, 9.6e-4, 7.24e-4, 200.0
W = (8, 12, 16)
parts = {n: [json.loads(l) for f in (REPO / f"research/rebuttal/sensitivity/data/swaps/parts_n{n}.jsonl", HH / f"parts_n{n}.jsonl") for l in open(f)] for n in W}
def lnatt(r, t1=T1, tbs=TBS, ebs=EBS):
    I = float(np.interp(tbs, r["tbs_ns"], r["I_tbs"]))
    return I / t1 - r["crz"] * (math.log1p(-EC) + math.log1p(-ET)) - r["B"] * math.log1p(-ebs)
def cells(n, topo=None, **kw):
    by = defaultdict(lambda: defaultdict(list))
    for r in parts[n]:
        if topo is None or r["topology"] == topo: by[(r["topology"], r["circuit"])][r["arm"]].append((math.exp(lnatt(r, **kw)), r["D"], r["swap2"] + r["swap1"]))
    return by
def summary(n, topo=None, **kw):
    by = cells(n, topo, **kw)
    ratio = [np.mean([x[0] for x in v["prism"]]) / np.mean([x[0] for x in v["greedy"]]) for v in by.values()]
    geo = 100 * (1 - math.exp(np.mean(np.log(ratio)))); med = 100 * (1 - np.median(ratio))
    dg = sum(np.mean([x[1] for x in v["greedy"]]) for v in by.values()); dp = sum(np.mean([x[1] for x in v["prism"]]) for v in by.values())
    eqw = 100 * np.mean([1 - np.mean([x[1] for x in v["prism"]]) / np.mean([x[1] for x in v["greedy"]]) for v in by.values()])
    sw = np.mean([np.mean([x[2] for x in v["greedy"]]) - np.mean([x[2] for x in v["prism"]]) for v in by.values()])
    keep = np.mean([np.mean([1 / x[0] for x in v["prism"]]) for v in by.values()])
    up = sum(r > 1 for r in ratio)
    return dict(geo=geo, median=med, dur_total=100 * (1 - dp / dg), dur_eqw=eqw, fewer_exchanges=sw, keep_prism=keep, workloads_up=up, cells=len(ratio))
out = {f"n{n}_all": summary(n) for n in W}
for t in ("grid", "hex_lattice", "heavy_hex"): out[f"n16_{t}"] = summary(16, t)
for k, kw in (("bs_speed_2x_better", dict(tbs=TBS / 2)), ("bs_speed_2x_worse", dict(tbs=TBS * 2)), ("bs_erasure_2x_better", dict(ebs=EBS / 2)), ("bs_erasure_2x_worse", dict(ebs=EBS * 2)), ("T1_2x_better", dict(t1=T1 * 2))):
    out[f"n16_all_{k}"] = summary(16, **kw)["geo"]
for k, v in out.items(): print(k, {a: (round(b, 3) if isinstance(b, float) else b) for a, b in v.items()} if isinstance(v, dict) else round(v, 1))
json.dump(out, open(Path(__file__).parent / "out/numbers.json", "w"), indent=1, default=float)
