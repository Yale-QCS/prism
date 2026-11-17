"""Eqs. 17-19 per saved circuit at n = 8, 12, 16, aggregates, and proxy-vs-exact checks.

Reads only. Run from anywhere with the repository .venv:
  .venv/bin/python compute.py
Writes rows.jsonl and results.json next to this file.
"""
import json, math, statistics, sys
from collections import defaultdict
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent / "out"; OUT.mkdir(exist_ok=True)
REPO = Path(__file__).resolve().parents[3]
WC = REPO / "research/rebuttal/wallclock"
sys.path[:0] = [str(WC), str(REPO / "src")]
import sim  # noqa: E402
import validate  # noqa: E402  (loss_parts/_pair_schedule)
import bare  # noqa: E402
from qiskit import qpy  # noqa: E402

DEV = sim.MEHTA_IDLE
GAMMA = DEV.dephasing                       # per rail; logical phase-flip prob (1-exp(-2 gamma t))/2 ~ gamma t
EPS = {"crz_c": 3.9e-4, "crz_t": 1.1e-4, "bs": 9.9e-5}
WIDTHS = (8, 12, 16)
TOPOS = ("grid", "hex_lattice")
ARMS = ("greedy", "prism")


def z_counts(qc):
    """Residual-Z events that sim.py applies: CR_z control/target on live content, beamsplitter on rails[0] if live."""
    live, idle, _ = sim.live_pairs(qc)
    where = list(range(qc.num_qubits))
    n = {"crz_c": 0, "crz_t": 0, "bs": 0}
    for i, ins in enumerate(qc.data):
        op = ins.operation
        if op.name == "barrier" or i in idle or sim.is_synthetic_preparation(op):
            continue
        rails = [qc.find_bit(q).index for q in ins.qubits]
        if op.name == "crz":
            n["crz_c"] += where[rails[0]] in live
            n["crz_t"] += where[rails[1]] in live
        elif op.name in ("rswap", "swap", "rx"):
            n["bs"] += where[rails[0]] in live
        if op.name == "swap":
            a, b = rails
            where[a], where[b] = where[b], where[a]
    return n


def dualrail_rows():
    files = [(n, p) for n in WIDTHS for p in sorted((WC / f"data/swaps/circuits_n{n}").glob("*.qpy"))]
    rows = []
    for k, (n, p) in enumerate(files, 1):
        with p.open("rb") as f:
            qc = qpy.load(f)[0]
        stem = p.stem
        topo = "hex_lattice" if "_hex_lattice_" in stem else "grid"
        name, rest = stem.split(f"_{topo}_")
        seed, arm = rest.split("_")
        live, D, I, logk = validate.loss_parts(qc, DEV)
        z = z_counts(qc)
        p17 = math.exp(logk - I / DEV.t1)
        f18 = math.exp(-GAMMA * I + sum(z[g] * math.log1p(-EPS[g]) for g in EPS))
        rows.append({"n": n, "circuit": name, "topology": topo, "seed": int(seed), "arm": arm, "pairs": live,
                     "D_us": D, "I_us": I, **{f"N_{g}": v for g, v in z.items()}, "eq17": p17, "eq18": f18})
        if k % 40 == 0 or k == len(files):
            print(f"{k}/{len(files)}", flush=True)
    return rows


def transmon_rows():
    """Eq. 19 from the best40 rows (op counts, n_active, D): the bare.log_esp form at each CZ error."""
    t = bare.CENTRAL
    rate = 1 / (4 * t.t1) + 1 / (2 * t.t2)  # process-fidelity idle factor (Eq. 19, a lower bound)
    out = []
    for n in WIDTHS:
        for line in (WC / f"data/bare_n{n}.jsonl").open():
            r = json.loads(line)
            if r["arm"] != "best40" or r["topology"] not in TOPOS:
                continue
            c = r["op_counts"]
            busy = sum(c.get(g, 0) * k * bare.DURATIONS[g] for g, k in (("cz", 2), ("sx", 1), ("x", 1)))
            idle = r["n_active"] * r["duration_us"] - busy
            n1 = c.get("sx", 0) + c.get("x", 0)
            base = {"n": n, "circuit": r["circuit"], "topology": r["topology"], "seed": r["seed"], "n_active": r["n_active"],
                    "D_us": r["duration_us"], "idle_us": idle, "N_cz": c.get("cz", 0), "N_1q": n1}
            for cz in (0.001, 0.003):
                lf = c.get("cz", 0) * math.log1p(-1.25 * cz) + n1 * math.log1p(-1.5 * t.sq) - idle * rate
                out.append(base | {"cz_error": cz, "eq19": math.exp(lf)})
    return out


def wmean(rows, key, f):
    g = defaultdict(list)
    for r in rows:
        g[r["circuit"]].append(f(r))
    return {c: float(np.mean(v)) for c, v in g.items()}


def mrange(d):
    v = list(d.values())
    return {"median": float(np.median(v)), "min": float(min(v)), "max": float(max(v)), "workloads": len(v)}


def aggregate(dr, tm):
    res = {}
    for n in WIDTHS:
        for scope in ("both",) + TOPOS:
            sel = [r for r in dr if r["n"] == n and (scope == "both" or r["topology"] == scope)]
            if not sel:
                continue
            s = {}
            for arm in ARMS:
                a = [r for r in sel if r["arm"] == arm]
                s[arm] = {"pkeep_eq17": mrange(wmean(a, "c", lambda r: r["eq17"])),
                          "attempts": mrange(wmean(a, "c", lambda r: 1 / r["eq17"])),
                          "F_eq18": mrange(wmean(a, "c", lambda r: r["eq18"])),
                          "circuits": len(a)}
            ag = wmean([r for r in sel if r["arm"] == "greedy"], "c", lambda r: 1 / r["eq17"])
            ap = wmean([r for r in sel if r["arm"] == "prism"], "c", lambda r: 1 / r["eq17"])
            s["attempt_reduction_pct"] = mrange({c: 100 * (1 - ap[c] / ag[c]) for c in ag})
            fg = wmean([r for r in sel if r["arm"] == "greedy"], "c", lambda r: r["eq18"])
            fp = wmean([r for r in sel if r["arm"] == "prism"], "c", lambda r: r["eq18"])
            s["F_eq18_prism_minus_greedy"] = mrange({c: fp[c] - fg[c] for c in fg})
            for cz in (0.001, 0.003):
                t = [r for r in tm if r["n"] == n and r["cz_error"] == cz and (scope == "both" or r["topology"] == scope)]
                s[f"transmon_cz{cz:g}_F_eq19"] = mrange(wmean(t, "c", lambda r: r["eq19"]))
            res[f"n{n}_{scope}"] = s
    return res


def relerr(pairs):
    e = np.array([abs(a - b) / b for a, b in pairs])
    s = np.array([(a - b) / b for a, b in pairs])
    return {"circuits": len(e), "max_rel": float(e.max()), "median_rel": float(np.median(e)),
            "mean_signed_rel": float(s.mean())}


def infid_err(pairs):
    """Relative error in infidelity 1-F (the quantity a fidelity proxy should get right)."""
    e = np.array([((1 - a) - (1 - b)) / (1 - b) for a, b in pairs])
    return {"median_rel": float(np.median(e)), "min_rel": float(e.min()), "max_rel": float(e.max())}


def checks(dr, tm):
    out = {}
    idx = {(r["n"], r["circuit"], r["topology"], r["seed"], r["arm"]): r for r in dr}
    v3 = [json.loads(l) for l in (WC / "data/swaps/v3_n8.jsonl").open()]
    pk = [(idx[(8, r["circuit"], r["topology"], r["seed"], r["arm"])]["eq17"], r["p_keep"]) for r in v3]
    ff = [(idx[(8, r["circuit"], r["topology"], r["seed"], r["arm"])]["eq18"], r["fidelity"]) for r in v3]
    out["n8_eq17_vs_exact_pkeep"] = relerr(pk)
    out["n8_eq18_vs_exact_F"] = relerr(ff) | {"infidelity": infid_err(ff)}
    tidx = {(r["circuit"], r["topology"], r["seed"], r["cz_error"]): r for r in tm if r["n"] == 8}
    ex = [json.loads(l) for l in (WC / "data/bare_direct_n8.jsonl").open()]
    for cz in (0.001, 0.003):
        pr = [(tidx[(r["circuit"], r["topology"], r["seed"], cz)]["eq19"], r["fidelity"]) for r in ex if r["cz_error"] == cz]
        # duration must match the row the proxy used (same reconstructed best40 winner)
        assert all(abs(tidx[(r["circuit"], r["topology"], r["seed"], cz)]["D_us"] - r["duration_us"]) < 1e-9 for r in ex)
        out[f"n8_eq19_vs_exact_F_cz{cz:g}"] = relerr(pr) | {"infidelity": infid_err(pr)}
    tr = [json.loads(l) for l in (REPO / "research/rebuttal/sensitivity/data/swaps/dephasing_n16.jsonl").open() if l.strip()]
    tr = [r for r in tr if abs(r["tphi_ms"] - 1 / (2 * GAMMA) / 1000) < 1e-6]
    pr = [(idx[(16, r["circuit"], r["topology"], r["seed"], r["arm"])]["eq18"], r["fidelity"], r["fidelity_se"]) for r in tr]
    pk16 = [(idx[(16, r["circuit"], r["topology"], r["seed"], r["arm"])]["eq17"], r["p_keep"]) for r in tr]
    z = np.array([(a - b) / s for a, b, s in pr if s > 0])
    out["n16_eq17_vs_traj_pkeep"] = relerr(pk16)
    out["n16_eq18_vs_traj_F"] = relerr([(a, b) for a, b, _ in pr]) | {
        "infidelity": infid_err([(a, b) for a, b, _ in pr]), "shots": tr[0]["shots"],
        "z_median": float(np.median(z)), "z_mean": float(z.mean()), "frac_abs_z_gt_2": float(np.mean(abs(z) > 2))}
    # workload-mean level comparison at n=16 (what the figure plots)
    for arm in ARMS:
        a = [(p[0], p[1]) for p, r in zip(pr, tr) if r["arm"] == arm]
        out[f"n16_{arm}_workload_median_eq18_vs_traj"] = {
            "eq18": float(np.median(list(wmean([{"circuit": r["circuit"], "v": p[0]} for p, r in zip(pr, tr) if r["arm"] == arm], "c", lambda x: x["v"]).values()))),
            "traj": float(np.median(list(wmean([{"circuit": r["circuit"], "v": p[1]} for p, r in zip(pr, tr) if r["arm"] == arm], "c", lambda x: x["v"]).values())))}
    out["_scatter_n8"] = {"eq18": ff, "eq19_cz0.001": [(tidx[(r["circuit"], r["topology"], r["seed"], 0.001)]["eq19"], r["fidelity"]) for r in ex if r["cz_error"] == 0.001],
                          "eq19_cz0.003": [(tidx[(r["circuit"], r["topology"], r["seed"], 0.003)]["eq19"], r["fidelity"]) for r in ex if r["cz_error"] == 0.003]}
    return out


if __name__ == "__main__":
    dr = dualrail_rows()
    tm = transmon_rows()
    with (OUT / "rows.jsonl").open("w") as f:
        for r in dr + tm:
            f.write(json.dumps(r) + "\n")
    chk = checks(dr, tm)
    scatter = chk.pop("_scatter_n8")
    res = {"model": {"gamma_per_us_per_rail": GAMMA, "eq18_idle_factor": "exp(-gamma*I)", "eps": EPS, "T1_us": DEV.t1,
                     "transmon": {"t1": bare.CENTRAL.t1, "t2": bare.CENTRAL.t2, "sq": bare.CENTRAL.sq, "durations": bare.DURATIONS,
                                  "eq19": "exp(-idle*(1/(4T1)+1/(2T2))) * (1-5/4 r_cz)^N_cz (1-3/2 r_1q)^N_1q, idle = n_active*D - busy (process fidelities, a lower bound)",
                                  "source_rows": "wallclock/data/bare_n{8,12,16}.jsonl arm best40"}},
           "aggregates": aggregate(dr, tm), "checks": chk}
    (OUT / "results.json").write_text(json.dumps(res, indent=1))
    (OUT / "scatter_n8.json").write_text(json.dumps(scatter))
    print(json.dumps(res["checks"], indent=1))
