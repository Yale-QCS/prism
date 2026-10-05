"""Both paper arms with and without the EarlyMeasurement rewrite (applied to marabbecca's logical circuit,
then fed back through the full pipeline). Paper deps, seed 0, paper budget, grid 5x4 + paper hex.
Caveat: marabbecca's lowering predates the clbit fixes, so the routed circuits' feedforward wiring is not
semantically checked here; the rewrite's routing effect (fewer CRZs, earlier measures) is faithful."""
import sys, warnings, importlib.util; warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/worktrees/hpca-r2/src"); sys.path.insert(0, "/home/evm9/prism/worktrees/hpca-r2/scripts/hpca")
from qiskit import qpy, QuantumCircuit, ClassicalRegister
def rename_cregs(qc):
    """marabbecca's expansion drops an input creg named 'meas'; give the input creg a distinct name."""
    cr = ClassicalRegister(qc.num_clbits, "c"); out = QuantumCircuit(*qc.qregs, cr)
    cmap = {c: cr[i] for i, c in enumerate(qc.clbits)}
    for ins in qc.data: out.append(ins.operation, ins.qubits, [cmap[c] for c in ins.clbits])
    return out
from qiskit.converters import circuit_to_dag, dag_to_circuit
from marabbecca.encodings import DualRail
from marabbecca.lowering.commit import SearchBudget
from marabbecca.lowering.commit_policies.prism_routing import PrismRouting
from marabbecca.staged_pms import build_pm
from run_fairness import make_topologies
spec = importlib.util.spec_from_file_location("em", "/tmp/claude-1000/-home-evm9-prism/fefda55f-7354-4d70-90b1-dffd9eb13c71/scratchpad/early_measure_port.py")
em = importlib.util.module_from_spec(spec); spec.loader.exec_module(em)
CORE = ["dj","qaoa","draper_qft_adder","modular_adder","qft","qpeexact","qpeinexact","qftentangled","bmw_quark_copula","hhl","ae","cdkm_ripple_carry_adder","full_adder","vqe_two_local","rg_qft_multiplier","multiplier"]
PrismRouting.COMMUTE_DIAGONAL = False
B = SearchBudget(objective="swaps", heuristic_config="qiskit_sabre", tie_break="load", layout_starts=40, refinement_iterations=16, prism_swap_trials=40)
ARMS = ("greedy_boundary", "prism")
tot = {(e, t, a): [0, 0, 0.0] for e in (False, True) for t in ("grid", "hex_lattice") for a in ARMS}
wins = {t: [0, 0, 0] for t in ("grid", "hex_lattice")}  # prism fewer / tie / more, with EM
for name in CORE:
    with open(f"/home/evm9/prism/worktrees/hpca-r2/artifacts/hpca/manifests/circuits/{name}_n8.qpy", "rb") as f: qc = rename_cregs(qpy.load(f)[0])
    logical = DualRail.logical_pm().run(qc)
    rewritten = dag_to_circuit(em.EarlyMeasurement().run(circuit_to_dag(logical)))
    row = f"{name:24} crz {logical.count_ops().get('crz',0):3}->{rewritten.count_ops().get('crz',0):3}"
    for topo in ("grid", "hex_lattice"):
        cmap = make_topologies(8)[topo]; res = {}
        for e, circ in ((False, qc), (True, rewritten)):
            for arm in ARMS:
                pm = build_pm(cmap, enc=DualRail, strategy=arm, seed=0, objective="swaps", budget=B); pm.run(circ)
                m = pm.property_set["circuit_metrics"]; res[(e, arm)] = m.swaps
                for i, v in enumerate((m.swaps, m.depth, m.duration / 1000)): tot[(e, topo, arm)][i] += v
        g, p = res[(True, "greedy_boundary")], res[(True, "prism")]
        wins[topo][0 if p < g else (1 if p == g else 2)] += 1
        row += f" | {topo[:3]} off g/p={res[(False,'greedy_boundary')]}/{res[(False,'prism')]} on g/p={g}/{p}"
    print(row, flush=True)
for e in (False, True):
    for topo in ("grid", "hex_lattice"):
        g, p = tot[(e, topo, "greedy_boundary")], tot[(e, topo, "prism")]
        print(f"EM={e!s:5} {topo:11}: greedy swaps {g[0]} depth {g[1]} dur {g[2]:.0f} | prism swaps {p[0]} depth {p[1]} dur {p[2]:.0f} | prism vs greedy swaps {100*(g[0]-p[0])/max(g[0],1):+.1f}% depth {100*(g[1]-p[1])/g[1]:+.1f}% duration {100*(g[2]-p[2])/g[2]:+.1f}%")
print("with EM, prism fewer/tie/more swaps than greedy per circuit:", wins)
