"""Commutation deps x rescheduler, prism, paper set, seed 0, grid+hex, swaps and depth objectives."""
import sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates")
from qiskit import qpy
from prism.encodings import DualRail
from prism.lowering.commit import SearchBudget
from prism.lowering.commit_policies.prism_routing import PrismRouting
from prism.pipeline import build_pm
from prism_gate import CORE, MARABBECCA, topologies
DualRail.early_measure = False
cases = []
for name in CORE:
    with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f: cases.append(qpy.load(f)[0])
for obj in ("swaps", "depth"):
    tot = {(c, r): [0, 0, 0.0] for c in (False, True) for r in (False, True)}
    for qc in cases:
        for topo, cmap in topologies(8).items():
            for c in (False, True):
                for r in (False, True):
                    PrismRouting.COMMUTE_DIAGONAL = c; DualRail.reschedule = r
                    pm = build_pm(cmap, enc=DualRail, seed=0, budget=SearchBudget(objective=obj)); pm.run(qc)
                    m = pm.property_set["circuit_metrics"]
                    for i, v in enumerate((m.swaps, m.depth, m.duration / 1000)): tot[(c, r)][i] += v
    b = tot[(False, False)]
    for c in (False, True):
        for r in (False, True):
            t = tot[(c, r)]
            print(f"objective={obj:6} commute={c!s:5} reschedule={r!s:5}: swaps {t[0]} ({100*(t[0]-b[0])/b[0]:+.1f}%) depth {t[1]} ({100*(t[1]-b[1])/b[1]:+.1f}%) dur {t[2]:.0f} ({100*(t[2]-b[2])/b[2]:+.1f}%)", flush=True)
PrismRouting.COMMUTE_DIAGONAL = True; DualRail.reschedule = True
