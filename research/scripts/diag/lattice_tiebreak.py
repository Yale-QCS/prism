"""The paper's load tie-break among executable realizations (vs neutral) across lattices: it can only act
where a commit has >= 2 executable realizations, which needs triangles in the coupling graph."""
import sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates"); sys.path.insert(0, "/tmp/claude-1000/-home-evm9-prism/1ae99356-0e84-472f-8923-fc3178a9233e/scratchpad")
from qiskit import qpy
from prism.encodings import DualRail
from prism.lowering.commit import SearchBudget
from prism.lowering.commit_policies.prism_routing import PrismRouting, Heuristic, BasicHeuristic, LookaheadHeuristic, DecayHeuristic, SetScaling
from prism.pipeline import build_pm
from prism_gate import CORE, MARABBECCA
from lattices import lattices
DualRail.early_measure = False; DualRail.reschedule = True
TIE = True
def make_heuristic(self, n_phys):
    return Heuristic(basic=BasicHeuristic(1.0, SetScaling.Constant), lookahead=LookaheadHeuristic(0.5, 20, SetScaling.Size),
                     decay=DecayHeuristic(0.001, 5), attempt_limit=10 * n_phys, best_epsilon=self.BEST_EPSILON,
                     phys_load_decay=self.PHYS_LOAD_DECAY, multi_tie_break_load=TIE, multi_sticky_witness=False)
PrismRouting._make_heuristic = make_heuristic
cases = []
for name in CORE:
    with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f: cases.append(qpy.load(f)[0])
for commute in (False, True):
    PrismRouting.COMMUTE_DIAGONAL = commute
    for lat, cmap in lattices(8).items():
        tot = {True: [0, 0, 0.0], False: [0, 0, 0.0]}
        for qc in cases:
            for tie in (False, True):
                TIE = tie
                pm = build_pm(cmap, enc=DualRail, seed=0, budget=SearchBudget(objective="swaps")); pm.run(qc)
                m = pm.property_set["circuit_metrics"]
                for i, v in enumerate((m.swaps, m.depth, m.duration / 1000)): tot[tie][i] += v
        b, t = tot[False], tot[True]
        print(f"commute={commute!s:5} {lat:10}: neutral tie-break swaps {b[0]:4} depth {b[1]:4} dur {b[2]:4.0f} | load tie-break swaps {t[0]:4} ({100*(t[0]-b[0])/b[0]:+.1f}%) depth {t[1]:4} ({100*(t[1]-b[1])/b[1]:+.1f}%) dur {t[2]:4.0f} ({100*(t[2]-b[2])/b[2]:+.1f}%)", flush=True)
PrismRouting.COMMUTE_DIAGONAL = True
