"""PRISM/Greedy ratio of the expected loss exponent -ln P_keep on the (cavity T1, beamsplitter duration t_bs) grid,
from data/parts_n{n}.jsonl (extract.py). Model: e_bs = t_bs/T1 + c_bs on every beamsplitter pair-touch (routing swap and
intra-pair rswap alike), idle loss I(t_bs)/T1 with the schedule re-timed for t_bs, CR_z fixed at its measured 500 ns and
erasures (transmon-limited). Routes fixed. Tests whether the ratio collapses onto rho = t_bs/T1.
Writes data/sweep.json (read by figure.py; includes a dense point-estimate field for the heatmap) and prints the key numbers.
Usage: .venv/bin/python -W ignore research/rebuttal/sensitivity/analyze.py"""
import json, math, sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
sys.path.insert(0, str(HERE))
from extract import ANCHORS, C_BS, DEV, E_BS, RHO_MEAS, RHO_SET, T1_GRID, T1_US, TBS_GRID, tbs_points  # noqa: E402

NS, TOPOS = (8, 12, 16), ("grid", "hex_lattice")
SHORT = {"grid": "grid", "hex_lattice": "hex"}
E_C, E_T = DEV.erasure["crz"]
K_CZ = -math.log1p(-E_C) - math.log1p(-E_T)
NBOOT = 1000
RNG = np.random.default_rng(0)
PICKS = None  # one set of paired seed resamples for every cell, so differences between cells are paired too


def nl(e):
    return -math.log1p(-e)


def load(n):
    rows = [json.loads(l) for l in (DATA / f"parts_n{n}.jsonl").open()]
    tbs = rows[0]["tbs_ns"]
    out = {}
    for t in TOPOS:
        by = defaultdict(lambda: defaultdict(dict))
        for r in rows:
            if r["topology"] == t:
                by[r["circuit"]][r["arm"]][r["seed"]] = r
        circuits = sorted(by)
        seeds = sorted(by[circuits[0]]["prism"])
        pick = lambda arm, key: np.array([[by[c][arm][s][key] for s in seeds] for c in circuits], float)
        out[t] = {"circuits": circuits, "tbs": tbs,
                  **{arm: {"I": pick(arm, "I_tbs"), "crz": pick(arm, "crz"), "B": pick(arm, "B"), "I0": pick(arm, "I")} for arm in ("prism", "greedy")}}
    return out


PARTS = {n: load(n) for n in NS}


def exponent(tab, arm, t1_us, tbs_ns):
    """-ln P_keep per (circuit, seed) at cavity T1 and beamsplitter duration t_bs."""
    j = tab["tbs"].index(tbs_ns)
    a = tab[arm]
    e_bs = tbs_ns / 1e3 / t1_us + C_BS
    return a["I"][:, :, j] / t1_us + a["crz"] * K_CZ + a["B"] * nl(e_bs)


def ratio(vp, vg):
    """Equal-weight-over-workloads PRISM/Greedy ratio of seed means, 95% paired seed bootstrap interval."""
    global PICKS
    nseed = vp.shape[1]
    if PICKS is None:
        PICKS = np.vstack([np.arange(nseed)[None, :], RNG.integers(0, nseed, (NBOOT, nseed))])
    ln = np.log(vp[:, PICKS].mean(axis=2)).mean(axis=0) - np.log(vg[:, PICKS].mean(axis=2)).mean(axis=0)
    return float(math.exp(ln[0])), float(math.exp(np.percentile(ln[1:], 2.5))), float(math.exp(np.percentile(ln[1:], 97.5)))


def ratio_point(vp, vg):
    return float(math.exp(np.mean(np.log(vp.mean(axis=1)) - np.log(vg.mean(axis=1)))))


def cell(n, t, t1_us, tbs_ns):
    tab = PARTS[n][t]
    vp, vg = exponent(tab, "prism", t1_us, tbs_ns), exponent(tab, "greedy", t1_us, tbs_ns)
    r, lo, hi = ratio(vp, vg)
    pw = vp.mean(axis=1) / vg.mean(axis=1)
    return {"n": n, "topology": t, "t1_us": t1_us, "tbs_ns": tbs_ns, "rho": tbs_ns / 1e3 / t1_us, "e_bs": tbs_ns / 1e3 / t1_us + C_BS,
            "ratio": r, "lo": lo, "hi": hi, "n_worse": int((pw > 1).sum())}


def fmt(c):
    return f"{c['ratio']:.3f} [{c['lo']:.3f}, {c['hi']:.3f}]"


def main():
    pts, _ = tbs_points()
    cells = {}
    total = len(pts) * len(NS) * len(TOPOS)
    k = 0
    for t1, tb in pts:
        for n in NS:
            for t in TOPOS:
                cells[(t1, tb, n, t)] = cell(n, t, t1, tb)
                k += 1
                if k % 60 == 0 or k == total:
                    print(f"{k}/{total}", flush=True)

    # 0. Baseline: the measured point must reproduce the v2 report (9.6% grid, 11.0% hex at n = 16).
    print("\nBaseline (T1 = 356.5 us, t_bs = 200 ns, e_bs = %.3e): reduction in expected losses PRISM vs Greedy" % (RHO_MEAS + C_BS))
    baseline = []
    for n in NS:
        for t in TOPOS:
            c = cells[(T1_US, 200.0, n, t)]
            baseline.append(c)
            print(f"  n={n} {SHORT[t]}: ratio {fmt(c)} -> {1-c['ratio']:.1%} fewer losses")

    # 1. Grid.
    grid = [cells[(t1, tb, n, t)] for t1 in T1_GRID for tb in TBS_GRID for n in NS for t in TOPOS]
    print(f"\nGrid: {len(T1_GRID)} T1 x {len(TBS_GRID)} t_bs. Ratio range per cell group:")
    for n in NS:
        for t in TOPOS:
            rs = [c["ratio"] for c in grid if c["n"] == n and c["topology"] == t]
            worse = sum(c["n_worse"] > 0 for c in grid if c["n"] == n and c["topology"] == t)
            print(f"  n={n} {SHORT[t]}: ratio {min(rs):.3f} (rho {max(c['rho'] for c in grid if c['ratio']==min(rs)):.1e}) to {max(rs):.3f}; "
                  f"cells with a workload against PRISM: {worse}/{len(rs)}")

    # 2. Collapse onto rho = t_bs/T1: points at equal rho from different (T1, t_bs).
    collapse, spread = [], []
    print("\nCollapse test: at each rho, ratios from different (T1, t_bs) with t_bs = rho T1")
    for rho in RHO_SET:
        group = [(t1, tb) for t1, tb in pts if abs(tb / 1e3 / t1 - rho) < 1e-9 * max(rho, 1e-9) + 1e-12]
        if len(group) < 2:
            continue
        for n in NS:
            for t in TOPOS:
                cs = [cells[(t1, tb, n, t)] for t1, tb in group]
                for c in cs:
                    collapse.append({**c, "rho_nominal": rho})
                r = np.array([c["ratio"] for c in cs])
                half = np.array([(c["hi"] - c["lo"]) / 2 for c in cs])
                # every point lies inside every other point's interval
                mutual = all(c2["lo"] <= c1["ratio"] <= c2["hi"] for c1 in cs for c2 in cs)
                spread.append({"rho": rho, "n": n, "topology": t, "points": len(cs), "t1_us": [g[0] for g in group],
                               "spread": float(r.max() - r.min()), "min_half_width": float(half.min()), "mean_half_width": float(half.mean()),
                               "within_intervals": bool(mutual), "ratio_lowT1": float(r[0]), "ratio_highT1": float(r[-1])})
        s_n16 = [s for s in spread if s["rho"] == rho and s["n"] == 16]
        print(f"  rho={rho:.1e}: {len(group)} points (T1 {min(g[0] for g in group):.0f} to {max(g[0] for g in group):.0f} us); "
              + "; ".join(f"n=16 {SHORT[s['topology']]} spread {s['spread']:.4f} (half-width {s['min_half_width']:.4f}, {'inside' if s['within_intervals'] else 'OUTSIDE'})" for s in s_n16))
    worst = max(spread, key=lambda s: s["spread"])
    print(f"  max spread over all rho, n, topology: {worst['spread']:.4f} at rho={worst['rho']:.1e} n={worst['n']} {SHORT[worst['topology']]} "
          f"(interval half-width {worst['min_half_width']:.4f}); cells outside intervals: {sum(not s['within_intervals'] for s in spread)}/{len(spread)}")
    worst_rel = max(spread, key=lambda s: s["spread"] / s["min_half_width"])
    print(f"  max spread / half-width: {worst_rel['spread']/worst_rel['min_half_width']:.2f} at rho={worst_rel['rho']:.1e} n={worst_rel['n']} {SHORT[worst_rel['topology']]}")

    # Why: at fixed rho the exponent is rho * I(t_bs)/t_bs + K_cz N_crz + B nl(rho + c_bs); only I/t_bs moves with T1.
    print("\nI(t_bs)/t_bs (summed idle time in beamsplitter units, seed and workload mean), n = 16:")
    for t in TOPOS:
        tab = PARTS[16][t]
        for arm in ("greedy", "prism"):
            vals = [tab[arm]["I"][:, :, tab["tbs"].index(tb)].mean() / (tb / 1e3) for tb in (50.0, 200.0, 500.0)]
            print(f"  {SHORT[t]} {arm}: " + ", ".join(f"{tb:.0f} ns: {v:.0f}" for tb, v in zip((50, 200, 500), vals)))

    # 3. Anchor corners.
    anchors = []
    print("\nLiterature corners:")
    for t1, tb in ANCHORS:
        for n in NS:
            for t in TOPOS:
                c = cells[(t1, tb, n, t)]
                anchors.append(c)
                if n == 16:
                    print(f"  T1={t1:.0f} us, t_bs={tb:.0f} ns (rho {c['rho']:.1e}, e_bs {c['e_bs']:.2e}) n=16 {SHORT[t]}: {fmt(c)} -> {1-c['ratio']:.1%} fewer losses")

    # 4. Dense point-estimate field for the heatmap: exact in T1 (analytic), on the 27 scheduled t_bs values.
    t1_dense = sorted(set(np.geomspace(100.0, 2000.0, 49).round(3)) | set(T1_GRID))
    tbs_all = PARTS[16]["grid"]["tbs"]
    field = []
    for n in NS:
        for t in TOPOS:
            tab = PARTS[n][t]
            z = [[ratio_point(exponent(tab, "prism", t1, tb), exponent(tab, "greedy", t1, tb)) for t1 in t1_dense] for tb in tbs_all]
            field.append({"n": n, "topology": t, "t1_us": t1_dense, "tbs_ns": tbs_all, "ratio": z})

    (DATA / "sweep.json").write_text(json.dumps({
        "model": {"t1_us_measured": T1_US, "tbs_ns_measured": 200.0, "e_bs_measured": E_BS, "c_bs": C_BS, "rho_measured": RHO_MEAS,
                  "e_crz_control": E_C, "e_crz_target": E_T, "crz_ns": 500.0, "t1_grid_us": T1_GRID, "tbs_grid_ns": TBS_GRID,
                  "rho_set": RHO_SET, "anchors": ANCHORS, "rho_anchor_band": [50e-3 / 2000.0, 208e-3 / 231.0], "nboot": NBOOT,
                  "formula": "-ln P_keep = I(t_bs)/T1 + N_crz [-ln(1-e_c) - ln(1-e_t)] + B [-ln(1 - t_bs/T1 - c_bs)]"},
        "baseline": baseline, "grid": grid, "collapse": collapse, "spread": spread, "anchors": anchors, "field": field}, indent=1))
    print(f"\nwrote {DATA / 'sweep.json'}")


if __name__ == "__main__":
    main()
