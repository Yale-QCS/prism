"""Static port assignment: within each run of commuting CRZs on a logical qubit, alternate the rail the
qubit offers (realizations restricted accordingly), so partners must be brought to both rails.
Measures the swaps-vs-depth trade of forcing two-port concurrency. Prism, paper set, seed 0."""
import sys, warnings, collections
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates")
from qiskit import qpy
from prism.encodings import DualRail
from prism.lowering.commit import SearchBudget
from prism.lowering.commit_policies import prism_routing as pr
from prism.lowering.commit_policies.prism_routing import PrismRouting
from prism.pipeline import build_pm
from prism_gate import CORE, MARABBECCA, topologies
DualRail.early_measure = False; PrismRouting.COMMUTE_DIAGONAL = True
MODE = "off"
orig_pre = PrismRouting._precompute
def precompute(self, dag):
    ctx = orig_pre(self, dag)
    if MODE == "off": return ctx
    counter = collections.Counter(); virt_pairs = list(ctx.virt_pairs); rim = list(ctx.real_idx_map); ld = list(ctx.local_default)
    for k, n in enumerate(ctx.op_nodes):
        name = n.op.logical_name
        lqs = sorted({v // 2 for v in ctx.virts_used[k]})
        if name == "crz" and len(virt_pairs[k]) == 4:
            # realization index r = 2*ra + rb; control = qargs[0] logical, target = qargs[1]
            c_lq, t_lq = (n.qargs[0]._register.name, n.qargs[2]._register.name)
            c_lq, t_lq = int(c_lq[1:]), int(t_lq[1:])
            pc, pt = counter[c_lq] % 2, counter[t_lq] % 2
            counter[c_lq] += 1; counter[t_lq] += 1
            if MODE == "control":  # only the control alternates
                keep = [r for r in range(4) if r // 2 == pc]
            else:  # both operands alternate
                keep = [r for r in range(4) if r // 2 == pc and r % 2 == pt]
            if len(keep) == 1: keep = keep * 2  # duplicate: keeps the node on the multi-realization front layer
            virt_pairs[k] = tuple(virt_pairs[k][r] for r in keep); rim[k] = tuple(rim[k][r] for r in keep); ld[k] = 0
        elif name not in ("crz", "rz"):
            for lq in lqs: counter[lq] = 0
    return pr._dc_replace(ctx, virt_pairs=virt_pairs, real_idx_map=rim, local_default=ld)
PrismRouting._precompute = precompute
cases = []
for name in CORE:
    with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f: cases.append(qpy.load(f)[0])
for obj in ("swaps", "depth"):
    tot = {m: [0, 0, 0.0] for m in ("off", "control", "both")}
    for qc in cases:
        for topo, cmap in topologies(8).items():
            for m in tot:
                MODE = m
                pm = build_pm(cmap, enc=DualRail, seed=0, budget=SearchBudget(objective=obj)); pm.run(qc)
                mt = pm.property_set["circuit_metrics"]
                for i, v in enumerate((mt.swaps, mt.depth, mt.duration / 1000)): tot[m][i] += v
    b = tot["off"]
    for m, t in tot.items():
        print(f"objective={obj:6} ports={m:8}: swaps {t[0]} ({100*(t[0]-b[0])/b[0]:+.1f}%) depth {t[1]} ({100*(t[1]-b[1])/b[1]:+.1f}%) dur {t[2]:.0f} ({100*(t[2]-b[2])/b[2]:+.1f}%)", flush=True)
