import sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates")
from qiskit import qpy
from prism.encodings import DualRail
from prism.pipeline import build_pm
from prism_gate import CORE, MARABBECCA, topologies
tot = {False: [0, 0, 0.0], True: [0, 0, 0.0]}
for name in CORE:
    with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f:
        qc = qpy.load(f)[0]
    for topo, cmap in topologies(8).items():
        for li in (False, True):
            DualRail.local_init = li
            pm = build_pm(cmap, enc=DualRail, seed=0); pm.run(qc); m = pm.property_set["circuit_metrics"]
            for i, v in enumerate((m.swaps, m.depth, m.duration / 1000)): tot[li][i] += v
DualRail.local_init = False
b = tot[False]
for li in (False, True):
    t = tot[li]
    print(f"local_init={li}: swaps {t[0]} ({100*(t[0]-b[0])/b[0]:+.1f}%) depth {t[1]} ({100*(t[1]-b[1])/b[1]:+.1f}%) duration {t[2]:.0f} ({100*(t[2]-b[2])/b[2]:+.1f}%)")
