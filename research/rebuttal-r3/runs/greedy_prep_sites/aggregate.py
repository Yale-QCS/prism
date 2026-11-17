"""Aggregate probe.jsonl and check each re-run against its published row."""
import os as _os
HERE = _os.path.dirname(_os.path.abspath(__file__)) + "/"
ROOT = _os.path.abspath(_os.path.join(HERE, "../../../..")) + "/"
import json, collections
R = ROOT + "artifacts/paper/raw/"
pub = {}
for f in ("core_swaps", "breadth_swaps"):
    for l in open(R + f + ".jsonl"):
        r = json.loads(l)
        pub[(r["circuit_name"], r["topology_name"], r["outer_seed"], r["strategy"])] = r
rows = [json.loads(l) for l in open(HERE + "probe.jsonl")]
mism = 0
for x in rows:
    p = pub[(x["circuit"], x["topology"], x["seed"], x["arm"])]
    if (p["router_inserted_swaps"], p["physical_depth"], p["duration_ns"]) != (x["router_swaps"], x["final_depth"], x["final_duration"]):
        mism += 1
print("runs", len(rows), "mismatches vs published rows", mism)
for arm in ("greedy", "prism"):
    xs = [x for x in rows if x["arm"] == arm]
    S = sum(x["router_swaps"] for x in xs)
    cat = collections.Counter()
    for x in xs:
        cat.update(x["swap_cat"])
    absorb = sum(x["absorbable"] for x in xs)
    touchU = sum(v for k, v in cat.items() if "U" in k)
    print(f"\n[{arm}] runs {len(xs)} routing SWAPs {S}")
    print("  categories", dict(sorted(cat.items())))
    print(f"  absorbable (no prepared rail: UU/UE): {absorb} = {100*absorb/S:.2f}%  in {sum(x['absorbable']>0 for x in xs)} runs")
    print(f"  touch an unprepared rail (any U): {touchU} = {100*touchU/S:.2f}%  in {sum(any('U' in k for k in x['swap_cat']) for x in xs)} runs")
    print("    of which partner prepared-idle (PU)", cat.get("PU", 0), " partner active (AU)", cat.get("AU", 0))
    dd = [x["route_depth_resched"] - x["route_depth_resched_absorbed"] for x in xs]
    du = [x["route_dur_resched"] - x["route_dur_resched_absorbed"] for x in xs]
    print(f"  deleting absorbable: depth saved total {sum(dd)} (runs changed {sum(d>0 for d in dd)}), duration saved {sum(du)} ns")
    print(f"  rescheduled routing-stage depth == final depth in {sum(x['route_depth_resched']==x['final_depth'] for x in xs)}/{len(xs)}")
    sep = [x["sep_pairs_at_entry"] for x in xs]
    print(f"  entry layout: runs with a separated pair {sum(s>0 for s in sep)}/{len(xs)}, separated pairs {sum(sep)} of {sum(x['n_logical'] for x in xs)} logical qubits")
    nd = sum(x["n_crz_decisions"] for x in xs); ns = sum(x["crz_with_separated_operand"] for x in xs)
    print(f"  CRZ decisions {nd}, with an operand separated at entry {ns} = {100*ns/nd:.1f}%")
    if arm == "greedy":
        diff = sum(x["greedy_choice_differs_folded"] for x in xs)
        a = sum(x["greedy_dist_entry_vs_folded"][0] for x in xs); b = sum(x["greedy_dist_entry_vs_folded"][1] for x in xs)
        print(f"  Greedy commits that change if made at the folded layout: {diff} = {100*diff/nd:.2f}% of decisions, in {sum(x['greedy_choice_differs_folded']>0 for x in xs)} runs; summed realization distance at folded layout {a} -> {b}")
    v = [tuple(x["prep_order_violations_route"]) for x in xs]; vf = [x["prep_order_violations_final"] for x in xs]
    print("  prep-order violations: route+reschedule", sum(a for a, _ in v), sum(b for _, b in v), " final circuit", collections.Counter(json.dumps(z) for z in vf))
by = collections.defaultdict(lambda: [0, 0, 0])
for x in rows:
    k = (x["circuit"], x["arm"]); by[k][0] += x["router_swaps"]; by[k][1] += x["absorbable"]; by[k][2] += sum(v for kk, v in x["swap_cat"].items() if "U" in kk)
print("\nper workload (swaps, absorbable, touch-U):")
for k in sorted(by): print(" ", k, by[k])
