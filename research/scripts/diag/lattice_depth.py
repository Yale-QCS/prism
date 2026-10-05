"""Prism on triangular/king (non-bipartite) vs grid: commute x rescheduler x objective."""
import sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates"); sys.path.insert(0, "/tmp/claude-1000/-home-evm9-prism/1ae99356-0e84-472f-8923-fc3178a9233e/scratchpad")
from qiskit import qpy
from prism.encodings import DualRail
from prism.lowering.commit import SearchBudget
from prism.lowering.commit_policies.prism_routing import PrismRouting
from prism.pipeline import build_pm
from prism_gate import CORE, MARABBECCA
from lattices import lattices
DualRail.early_measure = False
cases = []
for name in CORE:
    with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f: cases.append(qpy.load(f)[0])
LATS = {k: v for k, v in lattices(8).items() if k in ("grid", "triangular", "king")}
for obj in ("swaps", "depth"):
    for lat, cmap in LATS.items():
        tot = {(c, r): [0, 0, 0.0] for c in (False, True) for r in (False, True)}
        for qc in cases:
            for c in (False, True):
                for r in (False, True):
                    PrismRouting.COMMUTE_DIAGONAL = c; DualRail.reschedule = r
                    pm = build_pm(cmap, enc=DualRail, seed=0, budget=SearchBudget(objective=obj)); pm.run(qc)
                    m = pm.property_set["circuit_metrics"]
                    for i, v in enumerate((m.swaps, m.depth, m.duration / 1000)): tot[(c, r)][i] += v
        b = tot[(False, False)]
        for (c, r), t in tot.items():
            print(f"obj={obj:6} {lat:10} commute={c!s:5} resched={r!s:5}: swaps {t[0]:4} ({100*(t[0]-b[0])/b[0]:+.1f}%) depth {t[1]:4} ({100*(t[1]-b[1])/b[1]:+.1f}%) dur {t[2]:4.0f} ({100*(t[2]-b[2])/b[2]:+.1f}%)", flush=True)
PrismRouting.COMMUTE_DIAGONAL = True; DualRail.reschedule = True
