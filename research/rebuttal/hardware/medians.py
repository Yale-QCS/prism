"""Section V-D median-workload numbers at n = 16 over three graphs (the statistic of Fig. 12c): attempts per retained shot for PRISM and Greedy under each hardware variation, and retained-shot fidelity under imperfect erasure detection. Writes out/medians.json.
Usage: .venv/bin/python research/rebuttal/hardware/medians.py"""
import json, math, sys
from collections import defaultdict
from pathlib import Path
import numpy as np
REPO = Path(__file__).resolve().parents[3]; WC = REPO / "research/rebuttal/wallclock"; HW = REPO / "research/rebuttal/hardware"
HH = WC / "data/swaps/heavy_hex"
sys.path[:0] = [str(WC), str(REPO / "src"), str(HW)]
import sim, validate
from equations import z_counts, EPS
from qiskit import qpy
DEV = sim.MEHTA_IDLE
T1, EC, ET, EBS, TBS = 356.512171, 4.0e-3, 9.6e-4, 7.24e-4, 200.0
TOPOS = ("grid", "hex_lattice", "heavy_hex")
parts = [json.loads(l) for f in (REPO / "research/rebuttal/sensitivity/data/swaps/parts_n16.jsonl", REPO / "research/rebuttal/sensitivity/data/swaps/heavy_hex/parts_n16.jsonl") for l in open(f)]
def lnatt(r, t1=T1, tbs=TBS, ebs=EBS):
    I = float(np.interp(tbs, r["tbs_ns"], r["I_tbs"]))
    return I / t1 - r["crz"] * (math.log1p(-EC) + math.log1p(-ET)) - r["B"] * math.log1p(-ebs)
def med(vals):  # vals: {(circuit, ...): value}; per-workload mean, then median over workloads
    by = defaultdict(list)
    for k, v in vals.items(): by[k[0]].append(v)
    return float(np.median([np.mean(v) for v in by.values()]))
key = lambda r: (r["circuit"], r["topology"], r["seed"], r["arm"])
out = {}
for name, kw in (("measured", {}), ("T1_2x", dict(t1=2 * T1)), ("bs_2x_faster", dict(tbs=TBS / 2)), ("bs_half_erasure", dict(ebs=EBS / 2))):
    for arm in ("greedy", "prism"):
        rows = {key(r): math.exp(-lnatt(r, **kw)) for r in parts if r["arm"] == arm}
        out[f"{name}_{arm}_keep"] = med(rows)
        out[f"{name}_{arm}_attempts"] = med({k: 1 / v for k, v in rows.items()})
lnP = {key(r): -lnatt(r) for r in parts}
files = [p for d in (WC / "data/swaps/circuits_n16", HH / "circuits_n16") for p in sorted(d.glob("*.qpy"))]
eq18 = {}
for i, p in enumerate(files):
    topo = next(k for k in TOPOS if f"_{k}_" in p.stem)
    name, rest = p.stem.split(f"_{topo}_"); seed, arm = rest.split("_")
    if arm not in ("greedy", "prism"): continue
    with p.open("rb") as f: qc = qpy.load(f)[0]
    _, _, I, _ = validate.loss_parts(qc, DEV); z = z_counts(qc)
    eq18[(name, topo, int(seed), arm)] = math.exp(-DEV.dephasing * I + sum(z[g] * math.log1p(-EPS[g]) for g in EPS))
    if (i + 1) % 60 == 0 or i + 1 == len(files): print(f"{i+1}/{len(files)}", flush=True)
for arm in ("greedy", "prism"):
    out[f"F_{arm}"] = med({k: v for k, v in eq18.items() if k[3] == arm})
    for eta in (0.996, 0.963):
        out[f"F_{arm}_eta{eta}"] = med({k: v * math.exp((1 - eta) * lnP[k]) for k, v in eq18.items() if k[3] == arm and k in lnP})
        out[f"keep_{arm}_eta{eta}"] = med({k: math.exp(eta * lnP[k]) for k in eq18 if k[3] == arm and k in lnP})
print(json.dumps(out, indent=1))
(Path(__file__).resolve().parent / "out" / "medians.json").write_text(json.dumps(out, indent=1))
