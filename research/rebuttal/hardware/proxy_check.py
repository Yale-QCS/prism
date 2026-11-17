"""Adopt one Eq. 19 (process-fidelity form, a lower bound) and recompute the proxy checks.
Eq. 19: F_T = exp[-I_T (1/(4 T1) + 1/(2 T2))] * (1 - 5/4 r_cz)^N_cz * (1 - 3/2 r_1q)^N_1q, I_T = n_active*D - busy.
Also: Eq. 18 vs n = 16 trajectories, per circuit."""
import json, math, statistics as st, sys
from pathlib import Path
R = Path(__file__).resolve().parents[3] / "research/rebuttal"
sys.path.insert(0, str(R / "wallclock"))
import bare  # noqa: E402
OUT = Path(__file__).parent
t = bare.CENTRAL
RATE = 1 / (4 * t.t1) + 1 / (2 * t.t2)

def eq19(r, cz):
    c = r["op_counts"]
    busy = sum(c.get(g, 0) * k * bare.DURATIONS[g] for g, k in (("cz", 2), ("sx", 1), ("x", 1)))
    idle = r["n_active"] * r["duration_us"] - busy
    n1 = c.get("sx", 0) + c.get("x", 0)
    return math.exp(-idle * RATE) * (1 - 1.25 * cz) ** c.get("cz", 0) * (1 - 1.5 * t.sq) ** n1

key = lambda r: (r["circuit"], r["topology"], r["seed"])
best = {n: {key(r): r for r in map(json.loads, open(R / f"wallclock/data/bare_n{n}.jsonl")) if r["arm"] == "best40"} for n in (8, 12, 16)}

# 1. Eq. 19 vs exact transmon at n = 8
out = {}
for cz in (0.001, 0.003):
    ratios, mins, dur = [], [], 0
    for r in map(json.loads, open(R / "wallclock/data/bare_direct_n8.jsonl")):
        if r["cz_error"] != cz: continue
        b = best[8][key(r)]
        dur = max(dur, abs(b["duration_us"] - r["duration_us"]))
        p = eq19(b, cz)
        ratios.append((1 - p) / (1 - r["fidelity"]))
    out[f"eq19_n8_cz{cz}"] = dict(n=len(ratios), median_infid_ratio=st.median(ratios), min_ratio=min(ratios), bound_on_all=min(ratios) >= 1, max_duration_mismatch_us=dur)

# 2. Eq. 18 vs trajectories at n = 16
rows = [json.loads(l) for l in open(OUT / "out/rows.jsonl")]
e18 = {(r["circuit"], r["topology"], r["seed"], r["arm"]): r["eq18"] for r in rows if r["n"] == 16 and "eq18" in r and "arm" in r}
tr = [r for r in map(json.loads, open(R / "sensitivity/data/swaps/dephasing_n16.jsonl")) if abs(r["tphi_ms"] - 2.1818) < 0.01]
ratios, below = [], 0
for r in tr:
    p = e18[(r["circuit"], r["topology"], r["seed"], r["arm"])]
    ratios.append((1 - p) / (1 - r["fidelity"]))
    below += p <= r["fidelity"] + 2 * r.get("fidelity_se", 0)
out["eq18_n16_traj"] = dict(n=len(ratios), median_infid_ratio=st.median(ratios), min_ratio=min(ratios), proxy_below_sim_within_2se=below)

# 3. Eq. 19 over widths for Fig. 12(b): median of workload means per width and CZ point
by = {}
for n in (8, 12, 16):
    for cz in (0.001, 0.003):
        wl = {}
        for k, r in best[n].items():
            wl.setdefault(k[0], []).append(eq19(r, cz))
        by[f"n{n}_cz{cz}"] = st.median(st.mean(v) for v in wl.values())
out["eq19_by_width_median_workload_mean"] = by
json.dump(out, open(OUT / "out/proxy_check.json", "w"), indent=1)
print(json.dumps(out, indent=1))
