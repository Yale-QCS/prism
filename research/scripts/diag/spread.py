"""Per-start spread for the default budget: min/median/max final swaps over the 43 starts, and how
often the best start is a random one vs dense/identity/reverse."""
import sys, warnings, statistics
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates")
from qiskit import qpy
from prism.encodings import DualRail
from prism.lowering.commit_policies import prism_routing as pr
from prism.pipeline import build_pm
from prism_gate import CORE, MARABBECCA, topologies
orig = pr.prism_layout_and_routing
LAST = {}
def spy(*a, **k):
    res = orig(*a, **k); LAST["swaps"] = [r[2] for r in res]; return res
pr.prism_layout_and_routing = spy
for name in CORE:
    with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f:
        qc = qpy.load(f)[0]
    for topo, cmap in topologies(8).items():
        pm = build_pm(cmap, enc=DualRail, seed=0); pm.run(qc)
        s = LAST["swaps"]; rnd, std = s[:-3], s[-3:]
        print(f"{name:24} {topo:11} min={min(s):4} med={statistics.median(s):6.1f} max={max(s):4} "
              f"best_idx={s.index(min(s)):2} dense/id/rev={std} n_at_min={s.count(min(s))}", flush=True)
