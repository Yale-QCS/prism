"""Both paper arms with periodic mid-circuit erasure checks: a joint herald (rails co-located) on every
qubit after every D layers of the input circuit. Paper deps, seed 0, paper budget, grid 5x4 + paper hex."""
import sys, warnings; warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/worktrees/hpca-r2/src"); sys.path.insert(0, "/home/evm9/prism/worktrees/hpca-r2/scripts/hpca")
from qiskit import qpy, QuantumCircuit
from qiskit.circuit import Instruction
from qiskit.converters import circuit_to_dag
from marabbecca.encodings import DualRail
from marabbecca.lowering.commit import SearchBudget
from marabbecca.lowering.commit_policies.prism_routing import PrismRouting
from marabbecca.lowering.ir import LoweredOp
from marabbecca.synthesis.preparation import JointHeraldGate
from marabbecca.staged_pms import build_pm
from run_fairness import make_topologies
CORE = ["dj","qaoa","draper_qft_adder","modular_adder","qft","qpeexact","qpeinexact","qftentangled","bmw_quark_copula","hhl","ae","cdkm_ripple_carry_adder","full_adder","vqe_two_local","rg_qft_multiplier","multiplier"]
PrismRouting.COMMUTE_DIAGONAL = False
PERIODS = [int(x) for x in (sys.argv[1] if len(sys.argv) > 1 else "0,8,4").split(",")]
SEEDS = [int(x) for x in (sys.argv[2] if len(sys.argv) > 2 else "0").split(",")]
OBJ = sys.argv[3] if len(sys.argv) > 3 else "swaps"

class ErasureCheck(Instruction):
    def __init__(self): super().__init__("erasure_check", 1, 0, [])

def erasure_check(cls, _op):
    qc = QuantumCircuit(2); qc.append(JointHeraldGate(), [0, 1])
    return LoweredOp.fixed(qc, name="erasure_check")
DualRail.LOGICAL_ISA = DualRail.LOGICAL_ISA | {"erasure_check"}
DualRail.erasure_check = classmethod(erasure_check)
import marabbecca.staged_pms as sp
sp.NON_GATE_ISA_NAMES = frozenset(sp.NON_GATE_ISA_NAMES) | {"erasure_check"}

def with_checks(qc, period):
    if period == 0: return qc
    dag = circuit_to_dag(qc); out = QuantumCircuit(*qc.qregs, *qc.cregs)
    for i, layer in enumerate(dag.layers()):
        if i and i % period == 0:
            for q in qc.qubits: out.append(ErasureCheck(), [q])
        for node in layer["graph"].op_nodes():
            out.append(node.op, node.qargs, node.cargs)
    return out

B = SearchBudget(objective=OBJ, heuristic_config="qiskit_sabre", tie_break="load", layout_starts=40, refinement_iterations=16, prism_swap_trials=40)
tot = {(p, t, a): [0, 0, 0.0] for p in PERIODS for t in ("grid", "hex_lattice") for a in ("greedy_boundary", "prism")}
for name in CORE:
    with open(f"/home/evm9/prism/worktrees/hpca-r2/artifacts/hpca/manifests/circuits/{name}_n8.qpy", "rb") as f: qc = qpy.load(f)[0]
    row = f"{name:24}"
    for p in PERIODS:
        qcp = with_checks(qc, p); row += f" [D{p}: {qcp.count_ops().get('erasure_check', 0)} checks]"
        for topo in ("grid", "hex_lattice"):
            cmap = make_topologies(8)[topo]
            for arm in ("greedy_boundary", "prism"):
                acc = [0, 0, 0.0]
                for seed in SEEDS:
                    pm = build_pm(cmap, enc=DualRail, strategy=arm, seed=seed, objective=OBJ, budget=B); pm.run(qcp)
                    m = pm.property_set["circuit_metrics"]
                    for i, v in enumerate((m.swaps, m.depth, m.duration / 1000)): acc[i] += v / len(SEEDS)
                for i in range(3): tot[(p, topo, arm)][i] += acc[i]
                row += f" D{p}/{topo[:3]}/{arm[:6]}={acc[0]:5.1f}"
    print(row, flush=True)
for p in PERIODS:
    for topo in ("grid", "hex_lattice"):
        g, pr = tot[(p, topo, "greedy_boundary")], tot[(p, topo, "prism")]
        print(f"obj={OBJ} seeds={SEEDS} period={p} {topo:11}: greedy swaps {g[0]:.0f} depth {g[1]:.0f} dur {g[2]:.0f} | prism swaps {pr[0]:.0f} depth {pr[1]:.0f} dur {pr[2]:.0f} | prism vs greedy swaps {100*(g[0]-pr[0])/g[0]:+.1f}% depth {100*(g[1]-pr[1])/g[1]:+.1f}% duration {100*(g[2]-pr[2])/g[2]:+.1f}%")
