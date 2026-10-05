"""Both paper arms x {commutation deps off/on} x {rescheduler off/on}. Greedy takes relaxed deps by
duplicating its fixed realization for diagonal ops (identical realizations keep the node on the
multi-realization front layer, which tolerates shared front-layer qubits; the stock fast path asserts).
Rescheduler = prism's RescheduleCommutingDiagonals applied to marabbecca's output circuit.
Usage: marab_commute_resched.py seeds(csv) objective"""
import sys, warnings, importlib.util; warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/worktrees/hpca-r2/src"); sys.path.insert(0, "/home/evm9/prism/worktrees/hpca-r2/scripts/hpca")
from qiskit import qpy
from qiskit.converters import circuit_to_dag, dag_to_circuit
from marabbecca.encodings import DualRail
from marabbecca.lowering.commit import SearchBudget
from marabbecca.lowering.commit_policies import prism_routing as pr
from marabbecca.lowering.commit_policies.prism_routing import PrismRouting
from marabbecca.staged_pms import build_pm
from marabbecca.utils.metrics import physical_depth, physical_duration
from run_fairness import make_topologies
SEEDS = [int(x) for x in (sys.argv[1] if len(sys.argv) > 1 else "0").split(",")]
OBJ = sys.argv[2] if len(sys.argv) > 2 else "swaps"
spec = importlib.util.spec_from_file_location("resched", "/home/evm9/prism/main/src/prism/synthesis/reschedule.py")
import types; fake = types.ModuleType("prism.utils.metrics")
from marabbecca.utils.metrics import FREE_GATES, is_synthetic_preparation
fake.is_free = lambda op: op.name in FREE_GATES or is_synthetic_preparation(op)
sys.modules["prism"] = types.ModuleType("prism"); sys.modules["prism.utils"] = types.ModuleType("prism.utils"); sys.modules["prism.utils.metrics"] = fake
resched = importlib.util.module_from_spec(spec); spec.loader.exec_module(resched)
CORE = ["dj","qaoa","draper_qft_adder","modular_adder","qft","qpeexact","qpeinexact","qftentangled","bmw_quark_copula","hhl","ae","cdkm_ripple_carry_adder","full_adder","vqe_two_local","rg_qft_multiplier","multiplier"]
orig_greedy = PrismRouting._greedy_commit_ctx
def greedy_dup(self, ctx, v2p):
    fixed, choices = orig_greedy(self, ctx, v2p)
    if not PrismRouting.COMMUTE_DIAGONAL: return fixed, choices
    vp = [(p[0], p[0]) if d and len(p) == 1 and len(p[0]) == 1 else p for p, d in zip(fixed.virt_pairs, fixed.diagonal)]
    rm = [(m[0], m[0]) if d and len(m) == 1 and len(fixed.virt_pairs[k][0]) == 1 else m for k, (m, d) in enumerate(zip(fixed.real_idx_map, fixed.diagonal))]
    return pr._dc_replace(fixed, virt_pairs=vp, real_idx_map=rm), choices
PrismRouting._greedy_commit_ctx = greedy_dup
B = SearchBudget(objective=OBJ, heuristic_config="qiskit_sabre", tie_break="load", layout_starts=40, refinement_iterations=16, prism_swap_trials=40)
keys = [(c, r) for c in (False, True) for r in (False, True)]
tot = {(k, a): [0.0, 0.0, 0.0] for k in keys for a in ("greedy_boundary", "prism")}
for name in CORE:
    with open(f"/home/evm9/prism/worktrees/hpca-r2/artifacts/hpca/manifests/circuits/{name}_n8.qpy", "rb") as f: qc = qpy.load(f)[0]
    row = f"{name:24}"
    for topo in ("grid", "hex_lattice"):
        cmap = make_topologies(8)[topo]
        for c in (False, True):
            PrismRouting.COMMUTE_DIAGONAL = c
            for arm in ("greedy_boundary", "prism"):
                for seed in SEEDS:
                    pm = build_pm(cmap, enc=DualRail, strategy=arm, seed=seed, objective=OBJ, budget=B); out = pm.run(qc)
                    m = pm.property_set["circuit_metrics"]
                    tot[((c, False), arm)][0] += m.swaps / len(SEEDS); tot[((c, False), arm)][1] += m.depth / len(SEEDS); tot[((c, False), arm)][2] += m.duration / 1000 / len(SEEDS)
                    rs = dag_to_circuit(resched.RescheduleCommutingDiagonals().run(circuit_to_dag(out)))
                    tot[((c, True), arm)][0] += m.swaps / len(SEEDS); tot[((c, True), arm)][1] += physical_depth(rs) / len(SEEDS); tot[((c, True), arm)][2] += physical_duration(rs) / 1000 / len(SEEDS)
                row += f" {topo[:3]}/c{int(c)}/{arm[:6]}={m.swaps:3}"
    print(row, flush=True)
for (c, r) in keys:
    g, p = tot[((c, r), "greedy_boundary")], tot[((c, r), "prism")]
    print(f"obj={OBJ} seeds={SEEDS} commute={c!s:5} resched={r!s:5}: greedy swaps {g[0]:.0f} depth {g[1]:.0f} dur {g[2]:.0f} | prism swaps {p[0]:.0f} depth {p[1]:.0f} dur {p[2]:.0f} | prism vs greedy swaps {100*(g[0]-p[0])/g[0]:+.1f}% depth {100*(g[1]-p[1])/g[1]:+.1f}% duration {100*(g[2]-p[2])/g[2]:+.1f}%")
