"""SWAP_TIE_BREAK_LOAD off vs on (commute on, rescheduler on), prism, paper set, both objectives, plus
same-rail run statistics."""
import sys, warnings, collections
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates")
from qiskit import qpy
from prism.encodings import DualRail
from prism.lowering.commit import SearchBudget
from prism.lowering.commit_policies.prism_routing import PrismRouting
from prism.pipeline import build_pm
from prism_gate import CORE, MARABBECCA, topologies
DualRail.early_measure = False; DualRail.reschedule = True; PrismRouting.COMMUTE_DIAGONAL = True
SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 0
BEST = {}
orig = PrismRouting._trace_to_payload
def spy(trace, ctx):
    BEST["trace"], BEST["ctx"] = trace, ctx; return orig(trace, ctx)
PrismRouting._trace_to_payload = staticmethod(spy)
def runs_stat():
    ctx, (events, _, _) = BEST["ctx"], BEST["trace"]; runs = collections.defaultdict(list); last = {}
    for kind, a, b in events:
        if kind == PrismRouting._EVENT_COMMIT and ctx.op_nodes[a].op.logical_name == "crz":
            for (va, vb) in ctx.virt_pairs[a][b]:
                for v in (va, vb):
                    lq = v // 2
                    if last.get(lq) == v: runs[lq][-1] += 1
                    else: runs[lq].append(1); last[lq] = v
        elif kind != 1 and ctx.op_nodes[a].op.logical_name not in ("crz", "rz"):
            for v in ctx.virts_used[a]: last.pop(v // 2, None)
    return sum(max(r) for r in runs.values())
cases = []
for name in CORE:
    with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f: cases.append(qpy.load(f)[0])
for obj in ("swaps", "depth"):
    tot = {False: [0, 0, 0.0, 0], True: [0, 0, 0.0, 0]}
    for qc in cases:
        for topo, cmap in topologies(8).items():
            for tb in (False, True):
                PrismRouting.SWAP_TIE_BREAK_LOAD = tb
                pm = build_pm(cmap, enc=DualRail, seed=SEED, budget=SearchBudget(objective=obj)); pm.run(qc)
                m = pm.property_set["circuit_metrics"]
                for i, v in enumerate((m.swaps, m.depth, m.duration / 1000, runs_stat())): tot[tb][i] += v
    b = tot[False]
    for tb in (False, True):
        t = tot[tb]
        print(f"seed={SEED} objective={obj:6} swap_tiebreak={tb!s:5}: swaps {t[0]} ({100*(t[0]-b[0])/b[0]:+.1f}%) depth {t[1]} ({100*(t[1]-b[1])/b[1]:+.1f}%) dur {t[2]:.0f} ({100*(t[2]-b[2])/b[2]:+.1f}%) same-rail runs {t[3]}", flush=True)
PrismRouting.SWAP_TIE_BREAK_LOAD = False
