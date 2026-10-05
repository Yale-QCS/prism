"""Budget-scaling headroom: paper set, seed 0, grid+hex, commutation-aware deps. Per config: totals of
swaps/depth/duration and the spread (min/median/max swaps over starts) for the default config."""
import sys, warnings, time
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates")
from qiskit import qpy
from prism.encodings import DualRail
from prism.lowering.commit import SearchBudget
from prism.pipeline import build_pm
from prism_gate import CORE, MARABBECCA, topologies
CONFIGS = {"default": dict(), "starts200": dict(layout_starts=200), "iters64": dict(refinement_iterations=64),
           "swaptrials200": dict(swap_trials=200), "starts200_iters64": dict(layout_starts=200, refinement_iterations=64)}
names = sys.argv[1].split(",") if len(sys.argv) > 1 else list(CONFIGS)
cases = []
for name in CORE:
    with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f:
        cases.append((name, qpy.load(f)[0]))
tot = {c: [0, 0, 0.0, 0.0] for c in names}
print(f"{'circuit':24} {'topo':11} " + " ".join(f"{c:>20}" for c in names), flush=True)
for name, qc in cases:
    for topo, cmap in topologies(8).items():
        row = f"{name:24} {topo:11} "
        for c in names:
            t0 = time.time()
            pm = build_pm(cmap, enc=DualRail, seed=0, budget=SearchBudget(**CONFIGS[c]))
            pm.run(qc); m = pm.property_set["circuit_metrics"]
            r = (m.swaps, m.depth, round(m.duration / 1000, 1)); dt = time.time() - t0
            for i in range(3): tot[c][i] += r[i]
            tot[c][3] += dt
            row += f" {str(r):>16}{dt:4.0f}s"
        print(row, flush=True)
b = tot[names[0]]
for c in names:
    t = tot[c]
    print(f"{c}: swaps {t[0]} ({100*(t[0]-b[0])/b[0]:+.1f}%) depth {t[1]} ({100*(t[1]-b[1])/b[1]:+.1f}%) duration {t[2]:.0f} ({100*(t[2]-b[2])/b[2]:+.1f}%) time {t[3]:.0f}s")
