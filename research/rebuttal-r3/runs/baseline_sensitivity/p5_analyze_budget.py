"""Aggregate p2_suite.jsonl (Q3) and p3_matchings_*.jsonl (Q1); compare with the raw Logical-SABRE rows."""
import os as _os
HERE = _os.path.dirname(_os.path.abspath(__file__)) + "/"
ROOT = _os.path.abspath(_os.path.join(HERE, "../../../..")) + "/"
import json, collections, statistics as st, os
D = HERE + ""
RAW = ROOT + "research/rebuttal-r3/runs/logical_budget/"
rows = [json.loads(l) for l in open(HERE + "p2_suite_budget.jsonl")]
raw = {}
for f in ("logical_budget.jsonl", "logical_qasmbench_budget.jsonl", "logical_added_budget.jsonl", "logical_seeds64_budget.jsonl", "logical_randomcircuit_budget.jsonl"):
    for l in open(RAW + f):
        r = json.loads(l)
        raw[(r["circuit_name"], r["topology_name"], r["outer_seed"])] = r
# reproduction of the raw rows
same = diff = 0
for r in rows:
    q = raw[(r["circuit"], r["topology"], r["seed"])]
    if not r["ok"]:
        assert not q["success"]; continue
    ok = (q["router_inserted_swaps"], q["physical_depth"], q["quotient_partition_pairs"]) == (r["router_inserted_swaps"], r["physical_depth"], r["pairs"])
    same += ok; diff += not ok
print("re-run rows identical to raw rows (router SWAPs, depth, pairs):", same, "different:", diff)
print("failed:", collections.Counter((r["circuit"], r["topology"], r.get("error", "")[:60]) for r in rows if not r["ok"]))
print("quotient-level second SabreSwap added SWAPs in", sum(r["quotient_sabreswap_added"] != 0 for r in rows if r["ok"]), "runs")
print("VBE device sizes:", {t: len(raw[("vbe_ripple_carry_adder", t, 0)]["physical_routing_permutation"]) for t in ("grid", "hex_lattice", "heavy_hex")}, "n_logical", raw[("vbe_ripple_carry_adder", "grid", 0)]["actual_n_logical"])
# raw 64-seed totals per family (sum over workloads of seed means)
for t in ("grid", "hex_lattice", "heavy_hex"):
    by = collections.defaultdict(list)
    for (c, tt, s), q in raw.items():
        if tt == t and q["success"] and c != "gcm_h6" and s <= 6300:
            by[c].append(q["router_inserted_swaps"])
    print("raw", t, "workloads", len(by), "seeds", {len(v) for v in by.values()}, "sum of means", round(sum(st.mean(v) for v in by.values()), 2))
print()
print("family | workloads | L-SABRE SWAPs (sum of means) | lowered logical-SWAP part | router-added part | added share | logical SWAPs: aligned / crossed-only / neither (share two-disjoint) | variant chosen a/b | added per 'neither' SWAP | CRz off committed edge | rswap off matched pair | runs with any CRz moved | runs ending permuted")
for t in ("grid", "hex_lattice", "heavy_hex"):
    R = [r for r in rows if r["topology"] == t and r["ok"]]
    by = collections.defaultdict(list)
    for r in R: by[r["circuit"]].append(r)
    tot = sum(st.mean(x["router_inserted_swaps"] for x in v) for v in by.values())
    dirc = sum(st.mean(x["direct_n_swaps"] for x in v) for v in by.values())
    cat = collections.Counter()
    for r in R: cat.update(r["logical_swaps"])
    nsw = cat["aligned"] + cat["crossed_only"] + cat["neither"]
    add = sum(r["router_inserted_swaps"] - r["direct_n_swaps"] for r in R)
    phys = [r.get("physical_sabreswap") for r in R]
    crz_off = sum(p["crz_off_committed_edge"] for p in phys if p); crz = sum(p["crz_total"] for p in phys if p)
    rs_off = sum(p["rswap_off_matched_pair"] for p in phys if p); rs = sum(p["rswap_total"] for p in phys if p)
    anymove = sum(1 for p in phys if p and p["crz_off_committed_edge"] > 0)
    print(f"{t} | {len(by)} | {tot:.1f} | {dirc:.1f} | {tot-dirc:.1f} | {100*(tot-dirc)/tot:.1f}% | {cat['aligned']} / {cat['crossed_only']} / {cat['neither']} ({100*(cat['aligned']+cat['crossed_only'])/max(nsw,1):.1f}%) | {cat['chosen0']}/{cat['chosen1']} | {add/max(cat['neither'],1):.2f} | {crz_off}/{crz} ({100*crz_off/crz:.1f}%) | {rs_off}/{rs} ({100*rs_off/rs:.1f}%) | {anymove}/{len(R)} | {sum(not r['perm_identity'] for r in R)}/{len(R)}")
    # runs with no unavailable logical SWAP must have zero router-added SWAPs
    clean = [r for r in R if r["logical_swaps"].get("neither", 0) == 0]
    print("   runs with no 'neither' SWAP:", len(clean), "of which router added >0:", sum(r["router_inserted_swaps"] != r["direct_n_swaps"] for r in clean),
          "| physical SabreSwap skipped (no record):", sum(p is None for p in phys),
          "| edges-between-pairs histogram:", {k: v for k, v in sorted(cat.items()) if k.startswith("edges")})
    mq = [c for c in by if raw[(c, t, 0)]["requested_n"] == 8]
    print(f"   n=8 MQT17 only: total {sum(st.mean(x['router_inserted_swaps'] for x in by[c]) for c in mq):.1f}, added {sum(st.mean(x['router_inserted_swaps']-x['direct_n_swaps'] for x in by[c]) for c in mq):.1f}")
