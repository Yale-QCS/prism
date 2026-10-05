"""Both paper arms on bipartite (grid, hex) vs non-bipartite (triangular, king) lattices, paper deps and
relaxed deps (greedy via realization duplication), 16 rails + 2 spares sizing. Usage: seeds(csv)"""
import sys, warnings; warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/worktrees/hpca-r2/src"); sys.path.insert(0, "/home/evm9/prism/worktrees/hpca-r2/scripts/hpca"); sys.path.insert(0, "/tmp/claude-1000/-home-evm9-prism/1ae99356-0e84-472f-8923-fc3178a9233e/scratchpad")
from qiskit import qpy
from marabbecca.encodings import DualRail
from marabbecca.lowering.commit import SearchBudget
from marabbecca.lowering.commit_policies import prism_routing as pr
from marabbecca.lowering.commit_policies.prism_routing import PrismRouting
from marabbecca.staged_pms import build_pm
from lattices import lattices
SEEDS = [int(x) for x in (sys.argv[1] if len(sys.argv) > 1 else "0").split(",")]
CORE = ["dj","qaoa","draper_qft_adder","modular_adder","qft","qpeexact","qpeinexact","qftentangled","bmw_quark_copula","hhl","ae","cdkm_ripple_carry_adder","full_adder","vqe_two_local","rg_qft_multiplier","multiplier"]
orig_greedy = PrismRouting._greedy_commit_ctx
def greedy_dup(self, ctx, v2p):
    fixed, choices = orig_greedy(self, ctx, v2p)
    if not PrismRouting.COMMUTE_DIAGONAL: return fixed, choices
    vp = [(p[0], p[0]) if d and len(p) == 1 and len(p[0]) == 1 else p for p, d in zip(fixed.virt_pairs, fixed.diagonal)]
    rm = [(m[0], m[0]) if d and len(m) == 1 and len(fixed.virt_pairs[k][0]) == 1 else m for k, (m, d) in enumerate(zip(fixed.real_idx_map, fixed.diagonal))]
    return pr._dc_replace(fixed, virt_pairs=vp, real_idx_map=rm), choices
PrismRouting._greedy_commit_ctx = greedy_dup
B = SearchBudget(objective="swaps", heuristic_config="qiskit_sabre", tie_break="load", layout_starts=40, refinement_iterations=16, prism_swap_trials=40)
LATS = lattices(8)
tot = {(c, l, a): [0.0, 0.0, 0.0] for c in (False, True) for l in LATS for a in ("greedy_boundary", "prism")}
for name in CORE:
    with open(f"/home/evm9/prism/worktrees/hpca-r2/artifacts/hpca/manifests/circuits/{name}_n8.qpy", "rb") as f: qc = qpy.load(f)[0]
    row = f"{name:24}"
    for c in (False, True):
        PrismRouting.COMMUTE_DIAGONAL = c
        for l, cmap in LATS.items():
            for arm in ("greedy_boundary", "prism"):
                for seed in SEEDS:
                    pm = build_pm(cmap, enc=DualRail, strategy=arm, seed=seed, objective="swaps", budget=B); pm.run(qc)
                    m = pm.property_set["circuit_metrics"]
                    for i, v in enumerate((m.swaps, m.depth, m.duration / 1000)): tot[(c, l, arm)][i] += v / len(SEEDS)
                row += f" c{int(c)}/{l[:4]}/{arm[:6]}={m.swaps:3}"
    print(row, flush=True)
for c in (False, True):
    for l in LATS:
        g, p = tot[(c, l, "greedy_boundary")], tot[(c, l, "prism")]
        print(f"seeds={SEEDS} commute={c!s:5} {l:10}: greedy swaps {g[0]:.0f} depth {g[1]:.0f} dur {g[2]:.0f} | prism swaps {p[0]:.0f} depth {p[1]:.0f} dur {p[2]:.0f} | prism vs greedy swaps {100*(g[0]-p[0])/g[0]:+.1f}% depth {100*(g[1]-p[1])/g[1]:+.1f}% duration {100*(g[2]-p[2])/g[2]:+.1f}%")
