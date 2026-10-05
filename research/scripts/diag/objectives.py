import sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates")
from qiskit import qpy
from prism.encodings import DualRail
from prism.lowering.commit import SearchBudget
from prism.pipeline import build_pm
from prism_gate import CORE, MARABBECCA, topologies
OBJ = ["swaps", "depth", "duration"]
tot = {o: [0, 0, 0.0] for o in OBJ}
for name in CORE:
    with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f:
        qc = qpy.load(f)[0]
    for topo, cmap in topologies(8).items():
        for o in OBJ:
            pm = build_pm(cmap, enc=DualRail, seed=0, budget=SearchBudget(objective=o)); pm.run(qc)
            m = pm.property_set["circuit_metrics"]
            for i, v in enumerate((m.swaps, m.depth, m.duration / 1000)): tot[o][i] += v
b = tot["swaps"]
for o in OBJ:
    t = tot[o]
    print(f"objective={o}: swaps {t[0]} ({100*(t[0]-b[0])/b[0]:+.1f}%) depth {t[1]} ({100*(t[1]-b[1])/b[1]:+.1f}%) duration {t[2]:.0f} ({100*(t[2]-b[2])/b[2]:+.1f}%)")
