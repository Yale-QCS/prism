"""Prism on bipartite vs non-bipartite lattices: swaps/depth and the executable-realization count at CRZ
commit (choice exists only if a partner rail neighbors both rails of the pair)."""
import sys, warnings, collections
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates"); sys.path.insert(0, "/tmp/claude-1000/-home-evm9-prism/1ae99356-0e84-472f-8923-fc3178a9233e/scratchpad")
from qiskit import qpy
from prism.encodings import DualRail
from prism.lowering.commit_policies.prism_routing import PrismRouting
from prism.pipeline import build_pm
from prism_gate import CORE, MARABBECCA
from lattices import lattices
DualRail.early_measure = False
BEST = {}
orig = PrismRouting._trace_to_payload
def spy(trace, ctx):
    BEST["trace"], BEST["ctx"] = trace, ctx; return orig(trace, ctx)
PrismRouting._trace_to_payload = staticmethod(spy)
orig_build = PrismRouting._build_result
def spy2(self, dag, ctx, out_qc, payload, refined_v2p):
    BEST["v2p0"] = list(refined_v2p); return orig_build(self, dag, ctx, out_qc, payload, refined_v2p)
PrismRouting._build_result = spy2
def n_exec(edges):
    ctx, (events, _, _) = BEST["ctx"], BEST["trace"]; v2p = list(BEST["v2p0"]); p2v = {p: v for v, p in enumerate(v2p)}
    c = collections.Counter(); diff = same = 0; last = {}
    for kind, a, b in events:
        if kind == PrismRouting._EVENT_COMMIT and ctx.op_nodes[a].op.logical_name == "crz":
            opts = ctx.virt_pairs[a]
            ex = [i for i, pairs in enumerate(opts) if all((v2p[x], v2p[y]) in edges for x, y in pairs)]
            c[min(len(ex), 2)] += 1
            for (va, vb) in opts[b]:
                for v in (va, vb):
                    lq = v // 2
                    if lq in last: (diff, same) = (diff + 1, same) if last[lq] != v else (diff, same + 1)
                    last[lq] = v
        elif kind == 1:
            va, vb = p2v[a], p2v[b]; v2p[va], v2p[vb] = b, a; p2v[a], p2v[b] = vb, va
        elif ctx.op_nodes[a].op.logical_name not in ("crz", "rz"):
            for v in ctx.virts_used[a]: last.pop(v // 2, None)
    return c, diff, same
for flag in (False, True):
    PrismRouting.COMMUTE_DIAGONAL = flag
    tot = collections.defaultdict(lambda: [0, 0, 0.0, collections.Counter(), 0, 0])
    for name in CORE:
        with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f: qc = qpy.load(f)[0]
        for lat, cmap in lattices(8).items():
            pm = build_pm(cmap, enc=DualRail, seed=0); pm.run(qc); m = pm.property_set["circuit_metrics"]
            edges = set(map(tuple, cmap.get_edges())); c, diff, same = n_exec(edges)
            t = tot[lat]; t[0] += m.swaps; t[1] += m.depth; t[2] += m.duration / 1000; t[3].update(c); t[4] += diff; t[5] += same
    for lat, t in tot.items():
        n = sum(t[3].values())
        print(f"commute={flag!s:5} {lat:10}: swaps {t[0]:4} depth {t[1]:5} dur {t[2]:4.0f} | commits with >=2 executable realizations {100*t[3][2]/n:4.1f}% | sibling on different rail {100*t[4]/max(t[4]+t[5],1):4.1f}%", flush=True)
PrismRouting.COMMUTE_DIAGONAL = True
