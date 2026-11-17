import json, sys, os
H = "/tmp/claude-1000/-home-evm9-prism/5efc2ab2-68ef-49d4-b0b2-ec2bcc700896/scratchpad/hyp"
D = "research/rebuttal/commutation/data"
def load(p):
    return {(r["circuit_name"], r["topology_name"], r["strategy"], r["outer_seed"]): r for r in map(json.loads, open(p)) if r["success"] and r["outer_seed"] in (0, 1, 2)}
for obj in ("swaps", "depth"):
    runs = {"order": f"{D}/{obj}_ord.jsonl", "commute": f"{D}/{obj}_com.jsonl", "window2": f"{D}/{obj}_window2.jsonl"}
    for m in sys.argv[1:]:
        if os.path.exists(f"{H}/{obj}_{m}.jsonl"): runs[m] = f"{H}/{obj}_{m}.jsonl"
    print(f"\n=== select by {obj}: PRISM SWAPs / depth / duration us  (edge vs Greedy)")
    for name, p in runs.items():
        d = load(p); out = f"  {name:9s}"
        for topo in ("grid", "hex_lattice"):
            f = lambda s, m: sum(r[m] for k, r in d.items() if k[1] == topo and k[2] == s)
            P = [f("prism", m) for m in ("router_inserted_swaps", "physical_depth", "duration_ns")]
            G = [f("greedy", m) for m in ("router_inserted_swaps", "physical_depth", "duration_ns")]
            out += f" | {topo[:4]} {P[0]:5d}/{P[1]:5d}/{P[2]/1e3:4.0f} ({100*(1-P[0]/G[0]):4.1f}/{100*(1-P[1]/G[1]):4.1f}/{100*(1-P[2]/G[2]):4.1f}%)"
        print(out)
