"""Attribute each routing SWAP in prism's chosen route to the first later committed op that uses a rail
the SWAP moved. Buckets by logical op name (rx = rejoin, crz = reach a partner, init/measure)."""
import sys, warnings, collections
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
    BEST["trace"], BEST["ctx"] = trace, ctx
    return orig(trace, ctx)
PrismRouting._trace_to_payload = staticmethod(spy)
orig_build = PrismRouting._build_result
def spy2(self, dag, ctx, out_qc, payload, refined_v2p):
    BEST["v2p0"] = list(refined_v2p)
    return orig_build(self, dag, ctx, out_qc, payload, refined_v2p)
PrismRouting._build_result = spy2

def attribute(trace, ctx, v2p0):
    events, _, _ = trace
    p2v = {p: v for v, p in enumerate(v2p0)}
    pending, buckets = [], collections.Counter()
    for kind, a, b in events:
        if kind == PrismRouting._EVENT_COMMIT or kind == PrismRouting._EVENT_SUB_GATE:
            used = ctx.virts_used[a]; name = ctx.op_nodes[a].op.logical_name
            keep = []
            for moved in pending:
                if moved & used: buckets[name] += 1
                else: keep.append(moved)
            pending = keep
        else:
            va, vb = p2v[a], p2v[b]
            p2v[a], p2v[b] = vb, va
            pending.append(frozenset((va, vb)))
    buckets["unattributed"] += len(pending)
    return buckets
total = collections.Counter()
for name in CORE:
    with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f:
        qc = qpy.load(f)[0]
    for topo, cmap in topologies(8).items():
        pm = build_pm(cmap, enc=DualRail, seed=0); pm.run(qc)
        v2p0 = BEST["v2p0"]
        b = attribute(BEST["trace"], BEST["ctx"], v2p0)
        total.update(b)
        print(f"{name:24} {topo:11} {dict(b)}", flush=True)
n = sum(total.values())
print("TOTAL", {k: f"{v} ({100*v/n:.0f}%)" for k, v in total.most_common()})
