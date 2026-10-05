"""Both paper arms vs the number of spare rails: grids of 16 (zero spares), 18 (2x9), 20 (paper 5x4), 24 sites.
Paper deps, seed 0, paper budget."""
import sys, warnings; warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/worktrees/hpca-r2/src"); sys.path.insert(0, "/home/evm9/prism/worktrees/hpca-r2/scripts/hpca")
from qiskit import qpy
from qiskit.transpiler import CouplingMap
from marabbecca.encodings import DualRail
from marabbecca.lowering.commit import SearchBudget
from marabbecca.lowering.commit_policies.prism_routing import PrismRouting
from marabbecca.staged_pms import build_pm
CORE = ["dj","qaoa","draper_qft_adder","modular_adder","qft","qpeexact","qpeinexact","qftentangled","bmw_quark_copula","hhl","ae","cdkm_ripple_carry_adder","full_adder","vqe_two_local","rg_qft_multiplier","multiplier"]
PrismRouting.COMMUTE_DIAGONAL = False
GRIDS = {"4x4": (4, 4), "3x6": (3, 6), "5x4": (5, 4), "6x4": (6, 4)}
B = SearchBudget(objective="swaps", heuristic_config="qiskit_sabre", tie_break="load", layout_starts=40, refinement_iterations=16, prism_swap_trials=40)
tot = {(g, a): [0, 0, 0.0] for g in GRIDS for a in ("greedy_boundary", "prism")}
for name in CORE:
    with open(f"/home/evm9/prism/worktrees/hpca-r2/artifacts/hpca/manifests/circuits/{name}_n8.qpy", "rb") as f: qc = qpy.load(f)[0]
    row = f"{name:24}"
    for g, (r, c) in GRIDS.items():
        cmap = CouplingMap.from_grid(r, c)
        for arm in ("greedy_boundary", "prism"):
            pm = build_pm(cmap, enc=DualRail, strategy=arm, seed=0, objective="swaps", budget=B); pm.run(qc)
            m = pm.property_set["circuit_metrics"]
            for i, v in enumerate((m.swaps, m.depth, m.duration / 1000)): tot[(g, arm)][i] += v
            row += f" {g}/{arm[:6]}={m.swaps:3}"
    print(row, flush=True)
for g in GRIDS:
    gr, pr = tot[(g, "greedy_boundary")], tot[(g, "prism")]
    print(f"grid {g}: greedy swaps {gr[0]} depth {gr[1]} dur {gr[2]:.0f} | prism swaps {pr[0]} depth {pr[1]} dur {pr[2]:.0f} | prism vs greedy swaps {100*(gr[0]-pr[0])/gr[0]:+.1f}% depth {100*(gr[1]-pr[1])/gr[1]:+.1f}% duration {100*(gr[2]-pr[2])/gr[2]:+.1f}%")
