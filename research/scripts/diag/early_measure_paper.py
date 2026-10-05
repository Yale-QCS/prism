"""Paper set with the EarlyMeasurement pass on (tool default) vs off, prism, seed 0, grid+hex."""
import sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates")
from qiskit import qpy
from prism.encodings import DualRail
from prism.pipeline import build_pm
from prism_gate import CORE, MARABBECCA, topologies
tot = {False: [0, 0, 0.0, 0], True: [0, 0, 0.0, 0]}
print(f"{'circuit':24} {'topo':11} {'off (swaps, depth, us, crz)':>30} {'on':>30}")
for name in CORE:
    with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f:
        qc = qpy.load(f)[0]
    for topo, cmap in topologies(8).items():
        row = f"{name:24} {topo:11}"
        for em in (False, True):
            DualRail.early_measure = em
            pm = build_pm(cmap, enc=DualRail, seed=0); out = pm.run(qc); m = pm.property_set["circuit_metrics"]
            r = (m.swaps, m.depth, round(m.duration / 1000, 1), out.count_ops().get("crz", 0))
            for i in range(4): tot[em][i] += r[i]
            row += f" {str(r):>30}"
        print(row, flush=True)
b, r = tot[False], tot[True]
print(f"early_measure off: swaps {b[0]} depth {b[1]} duration {b[2]:.0f} crz {b[3]}")
print(f"early_measure on:  swaps {r[0]} ({100*(r[0]-b[0])/b[0]:+.1f}%) depth {r[1]} ({100*(r[1]-b[1])/b[1]:+.1f}%) duration {r[2]:.0f} ({100*(r[2]-b[2])/b[2]:+.1f}%) crz {r[3]} ({100*(r[3]-b[3])/b[3]:+.1f}%)")
