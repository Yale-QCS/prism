"""Section V-D time-to-precision comparison (reviewer B-1/B-Q1): the time to estimate an expectation value to fixed
precision is D / (P_keep F^2) for dual rail (Eqs. 17, 18) and D / F^2 for the transmon (Eq. 19), per paired
(workload, graph, seed). Reports the geometric mean of dual-rail/transmon ratios per width and the circuits where dual
rail is faster. Reads out/rows.jsonl (equations.py), writes out/wallclock.json.
Usage: .venv/bin/python research/rebuttal/hardware/wallclock_cost.py"""
import json, math
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"
rows = [json.loads(l) for l in (OUT / "rows.jsonl").open()]
dr = {(x["n"], x["circuit"], x["topology"], x["seed"], x["arm"]): x for x in rows if x.get("arm")}
tm = {(x["n"], x["circuit"], x["topology"], x["seed"], x["cz_error"]): x for x in rows if x.get("arm") is None}

res = []
for cz in (0.001, 0.003):
    for n in (8, 12, 16):
        for arm in ("greedy", "prism"):
            lr = []
            for (nn, c, t, s, a), x in dr.items():
                y = tm.get((nn, c, t, s, cz))
                if nn == n and a == arm and y:
                    lr.append(math.log((x["D_us"] / (x["eq17"] * x["eq18"] ** 2)) / (y["D_us"] / y["eq19"] ** 2)))
            res.append({"cz_error": cz, "n": n, "arm": arm, "ratio": math.exp(sum(lr) / len(lr)),
                        "dual_rail_faster": sum(v < 0 for v in lr), "circuits": len(lr)})
            print(f"cz {cz} n {n} {arm}: {res[-1]['ratio']:.2f} ({res[-1]['dual_rail_faster']}/{len(lr)})", flush=True)
(OUT / "wallclock.json").write_text(json.dumps(res, indent=1))
