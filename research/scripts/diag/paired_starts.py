"""Start-pool experiment: random rail starts (paper) vs pair-aware starts, where each logical qubit's
two rails begin on a coupling-map edge (random maximal matching). Same budget (40 starts + 3 standard)."""
import sys, warnings, random
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates")
from qiskit import qpy
from prism.encodings import DualRail
from prism.lowering.commit import SearchBudget
from prism.lowering.commit_policies.prism_routing import PrismRouting
from prism.pipeline import build_pm
from prism_gate import CORE, MARABBECCA, topologies

MODES = sys.argv[1].split(",") if len(sys.argv) > 1 else ["random", "paired", "half"]
orig_starts = PrismRouting._starting_layouts

def paired_v2p(self, ctx, seed):
    rng = random.Random(seed)
    edges = [tuple(e) for e in self.coupling_map.get_edges() if e[0] < e[1]]
    rng.shuffle(edges)
    used, matching = set(), []
    for a, b in edges:
        if a not in used and b not in used:
            matching.append((a, b)); used.update((a, b))
    n_log = ctx.n_virt // 2
    v2p = [None] * ctx.n_phys
    free = [p for p in range(ctx.n_phys) if p not in used]
    rng.shuffle(free)
    for i in range(n_log):
        if matching:
            a, b = matching.pop()
            if rng.random() < 0.5: a, b = b, a
        else:
            a, b = free.pop(), free.pop()
        v2p[2 * i], v2p[2 * i + 1] = a, b
    rest = [p for p in range(ctx.n_phys) if p not in v2p[:ctx.n_virt]]
    rng.shuffle(rest)
    v2p[ctx.n_virt:] = rest
    return v2p

def starts(self, ctx, base_seed):
    out = orig_starts(self, ctx, base_seed)
    mode = PrismRouting.START_MODE
    if mode == "random":
        return out
    n = self.num_trials if mode == "paired" else self.num_trials // 2
    for k in range(n):
        seed = base_seed + k
        out[k] = ("paired", seed, paired_v2p(self, ctx, seed))
    return out
PrismRouting._starting_layouts = starts

cases = []
for name in CORE:
    with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f:
        cases.append((name, qpy.load(f)[0]))
tot = {m: [0, 0, 0.0] for m in MODES}
print(f"{'circuit':24} {'topo':11} " + " ".join(f"{m:>16}" for m in MODES), flush=True)
for name, qc in cases:
    for topo, cmap in topologies(8).items():
        row = f"{name:24} {topo:11} "
        for m in MODES:
            PrismRouting.START_MODE = m
            pm = build_pm(cmap, enc=DualRail, seed=0); pm.run(qc); mt = pm.property_set["circuit_metrics"]
            r = (mt.swaps, mt.depth, round(mt.duration / 1000, 1))
            for i in range(3): tot[m][i] += r[i]
            row += f" {str(r):>16}"
        print(row, flush=True)
b = tot[MODES[0]]
for m in MODES:
    t = tot[m]
    print(f"{m}: swaps {t[0]} ({100*(t[0]-b[0])/b[0]:+.1f}%) depth {t[1]} ({100*(t[1]-b[1])/b[1]:+.1f}%) duration {t[2]:.0f} ({100*(t[2]-b[2])/b[2]:+.1f}%)")
