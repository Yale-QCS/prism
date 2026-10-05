"""Both paper arms at 5x layout starts (paper deps, seed 0): does extra search budget change the gap?"""
import sys, json, warnings; warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/worktrees/hpca-r2/src"); sys.path.insert(0, "/home/evm9/prism/worktrees/hpca-r2/scripts/hpca")
from pathlib import Path
from qiskit import qpy
from marabbecca.encodings import DualRail
from marabbecca.lowering.commit import SearchBudget
from marabbecca.lowering.commit_policies.prism_routing import PrismRouting
from marabbecca.staged_pms import build_pm
from run_fairness import make_topologies
CORE = ["dj","qaoa","draper_qft_adder","modular_adder","qft","qpeexact","qpeinexact","qftentangled","bmw_quark_copula","hhl","ae","cdkm_ripple_carry_adder","full_adder","vqe_two_local","rg_qft_multiplier","multiplier"]
PrismRouting.COMMUTE_DIAGONAL = False
frozen = {}
for line in Path("/home/evm9/prism/worktrees/hpca-r2/artifacts/hpca/raw/core_v22_ordered_depth_tie_seed20_n8.jsonl").read_text().splitlines():
    r = json.loads(line)
    if r["outer_seed"] == 0: frozen[(r["circuit_name"], r["topology_name"], r["arm_kind"])] = (r["router_inserted_swaps"], r["physical_depth"])
tot = {(a, s): [0, 0] for a in ("greedy_boundary", "prism") for s in (40, 200)}
for name in CORE:
    with open(f"/home/evm9/prism/worktrees/hpca-r2/artifacts/hpca/manifests/circuits/{name}_n8.qpy", "rb") as f: qc = qpy.load(f)[0]
    for topo in ("grid", "hex_lattice"):
        cmap = make_topologies(8)[topo]; row = f"{name:24} {topo:11}"
        for arm in ("greedy_boundary", "prism"):
            fz = frozen[(name, topo, arm)]
            for i in range(2): tot[(arm, 40)][i] += fz[i]
            b = SearchBudget(objective="swaps", heuristic_config="qiskit_sabre", tie_break="load", layout_starts=200, refinement_iterations=16, prism_swap_trials=40)
            pm = build_pm(cmap, enc=DualRail, strategy=arm, seed=0, objective="swaps", budget=b); pm.run(qc)
            m = pm.property_set["circuit_metrics"]
            tot[(arm, 200)][0] += m.swaps; tot[(arm, 200)][1] += m.depth
            row += f"  {arm[:6]} 40={fz} 200={(m.swaps, m.depth)}"
        print(row, flush=True)
for s in (40, 200):
    g, p = tot[("greedy_boundary", s)], tot[("prism", s)]
    print(f"starts={s}: greedy swaps {g[0]} depth {g[1]} | prism swaps {p[0]} depth {p[1]} | prism vs greedy swaps {100*(g[0]-p[0])/g[0]:+.1f}% depth {100*(g[1]-p[1])/g[1]:+.1f}%")
