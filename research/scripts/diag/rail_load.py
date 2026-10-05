"""Same-rail serialization: per logical qubit, the share of its CRZs executed on its busier rail, and the
max consecutive run of CRZs on one rail, commutation deps off vs on (prism, swaps objective)."""
import sys, warnings, collections
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates")
from qiskit import qpy
from prism.encodings import DualRail
from prism.lowering.commit_policies.prism_routing import PrismRouting
from prism.pipeline import build_pm
from prism_gate import CORE, MARABBECCA, topologies
DualRail.early_measure = False
BEST = {}
orig = PrismRouting._trace_to_payload
def spy(trace, ctx):
    BEST["trace"], BEST["ctx"] = trace, ctx; return orig(trace, ctx)
PrismRouting._trace_to_payload = staticmethod(spy)
T = {False: [0, 0, 0], True: [0, 0, 0]}  # crz on busier rail, crz total, sum of max runs
for name in CORE:
    with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f: qc = qpy.load(f)[0]
    for topo, cmap in topologies(8).items():
        for flag in (False, True):
            PrismRouting.COMMUTE_DIAGONAL = flag
            pm = build_pm(cmap, enc=DualRail, seed=0); pm.run(qc)
            ctx, (events, _, _) = BEST["ctx"], BEST["trace"]
            per_q = collections.defaultdict(lambda: collections.Counter()); runs = collections.defaultdict(list); last = {}
            for kind, a, b in events:
                if kind == PrismRouting._EVENT_COMMIT and ctx.op_nodes[a].op.logical_name == "crz":
                    for (va, vb) in ctx.virt_pairs[a][b]:
                        for v in (va, vb):
                            lq = v // 2; per_q[lq][v] += 1
                            if last.get(lq) == v: runs[lq][-1] += 1
                            else: runs[lq].append(1); last[lq] = v
                elif kind != 1:
                    for v in ctx.virts_used[a]:
                        if ctx.op_nodes[a].op.logical_name not in ("crz", "rz"): last.pop(v // 2, None)
            busy = sum(max(c.values()) for c in per_q.values()); total = sum(sum(c.values()) for c in per_q.values())
            mx = sum(max(r) for r in runs.values())
            T[flag][0] += busy; T[flag][1] += total; T[flag][2] += mx
PrismRouting.COMMUTE_DIAGONAL = True
for flag in (False, True):
    t = T[flag]; print(f"commute={flag!s:5}: share of a qubit's CRZs on its busier rail {100*t[0]/t[1]:.1f}%  sum of longest same-rail runs {t[2]}")
