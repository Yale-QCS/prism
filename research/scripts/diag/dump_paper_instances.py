"""Dump the 16 paper circuits (n=8, frozen qpy) as rail instances with prism's chosen route
(initial layout + event stream) so the CP-SAT solver can start from prism's solution."""
import sys, json, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates")
from qiskit import qpy
from prism.encodings import DualRail
from prism.lowering.commit_policies.prism_routing import PrismRouting
from prism.pipeline import build_pm
from prism_gate import CORE, MARABBECCA, topologies
BEST = {}
orig = PrismRouting._trace_to_payload
def spy(trace, ctx):
    BEST["trace"], BEST["ctx"] = trace, ctx; return orig(trace, ctx)
PrismRouting._trace_to_payload = staticmethod(spy)
orig_build = PrismRouting._build_result
def spy2(self, dag, ctx, out_qc, payload, refined_v2p):
    BEST["v2p0"] = list(refined_v2p); return orig_build(self, dag, ctx, out_qc, payload, refined_v2p)
PrismRouting._build_result = spy2
only = sys.argv[1].split(",") if len(sys.argv) > 1 else CORE
out = []
for name in only:
    with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f:
        qc = qpy.load(f)[0]
    for topo, cmap in topologies(8).items():
        pm = build_pm(cmap, enc=DualRail, seed=0); pm.run(qc); m = pm.property_set["circuit_metrics"]
        ctx = BEST["ctx"]; events = BEST["trace"][0]
        ops = [{"name": n.op.logical_name, "pairs": [[list(p) for p in real] for real in ctx.virt_pairs[k]]}
               for k, n in enumerate(ctx.op_nodes)]
        out.append({"circuit": name, "n": 8, "topo": topo, "n_phys": cmap.size(), "n_virt": ctx.n_virt,
                    "edges": [list(map(int, e)) for e in cmap.get_edges() if e[0] < e[1]],
                    "ops": ops, "succ": ctx.succ, "prism_swaps": m.swaps, "prism_depth": m.depth,
                    "v2p0": [int(p) for p in BEST["v2p0"]],
                    "events": [[int(k), int(a), int(b)] for k, a, b in events],
                    "kinds": {"commit": PrismRouting._EVENT_COMMIT, "sub": PrismRouting._EVENT_SUB_GATE}})
        print(name, topo, "ops", len(ops), "swaps", m.swaps, "events", len(events), flush=True)
json.dump(out, open("/home/evm9/.claude/jobs/1ae99356/tmp/instances_n8.json", "w"))
