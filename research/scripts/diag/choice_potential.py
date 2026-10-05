"""At each CRZ commit in prism's chosen route, how many of the 4 realizations were adjacent (executable)?
Also: for consecutive commuting CRZs on one logical qubit, could the second have used the other rail?"""
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
    BEST["trace"], BEST["ctx"] = trace, ctx; return orig(trace, ctx)
PrismRouting._trace_to_payload = staticmethod(spy)
orig_build = PrismRouting._build_result
def spy2(self, dag, ctx, out_qc, payload, refined_v2p):
    BEST["v2p0"] = list(refined_v2p); return orig_build(self, dag, ctx, out_qc, payload, refined_v2p)
PrismRouting._build_result = spy2

def analyze(trace, ctx, v2p, edges):
    events, _, _ = trace
    v2p = list(v2p); p2v = {p: v for v, p in enumerate(v2p)}
    n_exec = collections.Counter(); alt = collections.Counter()
    last_rail = {}  # logical qubit -> (rail used by last diagonal op, could_have_differed)
    for kind, a, b in events:
        if kind == PrismRouting._EVENT_COMMIT and ctx.op_nodes[a].op.logical_name == "crz":
            opts = ctx.virt_pairs[a]  # per realization: tuple of (va, vb) pairs
            ex = [i for i, pairs in enumerate(opts) if all((v2p[x], v2p[y]) in edges for x, y in pairs)]
            n_exec[len(ex)] += 1
            chosen = ctx.real_idx_map[a].index(ctx.real_idx_map[a][b]) if False else b
            used = ctx.virts_used[a]
            for lq in {v // 2 for v in used}:
                rails_avail = {v for i in ex for pr in opts[i] for v in pr if v // 2 == lq}
                rail_used = [v for pr in opts[chosen] for v in pr if v // 2 == lq][0]
                if lq in last_rail:
                    prev = last_rail[lq]
                    if rail_used == prev:
                        alt["same_rail_forced" if len(rails_avail) == 1 else "same_rail_by_choice"] += 1
                    else:
                        alt["different_rail"] += 1
                last_rail[lq] = rail_used
        elif kind == PrismRouting._EVENT_COMMIT or kind == PrismRouting._EVENT_SUB_GATE:
            for v in ctx.virts_used[a]:
                last_rail.pop(v // 2, None)  # non-diagonal op resets the run
        else:
            va, vb = p2v[a], p2v[b]; v2p[va], v2p[vb] = b, a; p2v[a], p2v[b] = vb, va
    return n_exec, alt
T1, T2 = collections.Counter(), collections.Counter()
for name in CORE:
    with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f:
        qc = qpy.load(f)[0]
    for topo, cmap in topologies(8).items():
        pm = build_pm(cmap, enc=DualRail, seed=0); pm.run(qc)
        edges = set(map(tuple, cmap.get_edges()))
        n_exec, alt = analyze(BEST["trace"], BEST["ctx"], BEST["v2p0"], edges)
        T1.update(n_exec); T2.update(alt)
        print(f"{name:24} {topo:11} executable={dict(sorted(n_exec.items()))} {dict(alt)}", flush=True)
print("EXECUTABLE REALIZATIONS AT COMMIT:", dict(sorted(T1.items())))
n = sum(T2.values()); print("SIBLING RAIL:", {k: f"{v} ({100*v/n:.0f}%)" for k, v in T2.items()})
