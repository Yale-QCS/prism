"""Commutation window sweep (prism, paper set, seed 0, grid+hex) under swaps and depth objectives."""
import sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates")
from qiskit import qpy
from prism.encodings import DualRail
from prism.lowering.commit import SearchBudget
from prism.lowering.commit_policies.prism_routing import PrismRouting
from prism.pipeline import build_pm
from prism_gate import CORE, MARABBECCA, topologies
DualRail.early_measure = False; PrismRouting.COMMUTE_DIAGONAL = True
WINDOWS = [1, 2, 3, 4, None]
cases = []
for name in CORE:
    with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f: cases.append(qpy.load(f)[0])
for obj in ("swaps", "depth"):
    tot = {w: [0, 0, 0.0] for w in WINDOWS}
    for qc in cases:
        for topo, cmap in topologies(8).items():
            for w in WINDOWS:
                PrismRouting.COMMUTE_WINDOW = w
                pm = build_pm(cmap, enc=DualRail, seed=0, budget=SearchBudget(objective=obj)); pm.run(qc)
                m = pm.property_set["circuit_metrics"]
                for i, v in enumerate((m.swaps, m.depth, m.duration / 1000)): tot[w][i] += v
    b = tot[1]
    for w in WINDOWS:
        r = tot[w]
        print(f"objective={obj:6} window={str(w):4}: swaps {r[0]} ({100*(r[0]-b[0])/b[0]:+.1f}%) depth {r[1]} ({100*(r[1]-b[1])/b[1]:+.1f}%) dur {r[2]:.0f} ({100*(r[2]-b[2])/b[2]:+.1f}%)", flush=True)
PrismRouting.COMMUTE_WINDOW = None
