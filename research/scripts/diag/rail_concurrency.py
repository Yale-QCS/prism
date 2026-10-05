"""Achieved rail concurrency: for consecutive commuting CRZs on one logical qubit (no non-diagonal
op between them on that qubit), did the router put them on different rails? Read off the committed
realization per op (which rail wires the chosen realization touches)."""
import sys, warnings; warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/qec"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates")
from qiskit import qpy
from qiskit.converters import circuit_to_dag
from prism.encodings import DualRail
from prism.lowering.commit import SearchBudget
from prism.lowering.commit_policies.prism_routing import PrismRouting
from prism.lowering.expansion import expand
from prism.lowering.ir import LoweredOp
from prism.pipeline import build_pm
from prism_gate import CORE, MARABBECCA, topologies
from qec_quick import CIRCUITS

def analyze(qc, cmap, commute, weight=0.0, objective="swaps"):
    PrismRouting.COMMUTE_DIAGONAL = commute; PrismRouting.SIBLING_WEIGHT = weight
    pm = build_pm(cmap, enc=DualRail, seed=0, budget=SearchBudget(objective=objective)); pm.run(qc)
    choices = iter(pm.property_set["realization_choices"])
    prog = expand(circuit_to_dag(DualRail.logical_pm().run(qc)), DualRail)
    wire_index = {q: i for i, q in enumerate(prog.dag.qubits)}  # virtual rail index; logical = idx // 2
    last = {}   # logical qubit -> ("crz", rail) of the last op on it, or ("other", None)
    same = diff = 0
    for node in prog.dag.topological_op_nodes():
        op = node.op
        if not isinstance(op, LoweredOp): continue
        idx = next(choices) if op.is_decision else 0
        real = op.realizations[idx]
        touched = [wire_index[node.qargs[real.find_bit(q).index]] for ins in real.data for q in ins.qubits]
        logical_rails = {}
        for w in touched: logical_rails.setdefault(w // 2, set()).add(w % 2)
        for lq, rails in logical_rails.items():
            if op.logical_name == "crz" and len(rails) == 1:
                rail = next(iter(rails))
                prev = last.get(lq)
                if prev and prev[0] == "crz":
                    if prev[1] == rail: same += 1
                    else: diff += 1
                last[lq] = ("crz", rail)
            elif op.logical_name == "rz":
                continue  # free, diagonal: does not break the run
            else:
                last[lq] = ("other", None)
    m = pm.property_set["circuit_metrics"]
    return same, diff, m.swaps, m.depth

cases = []
for name in CORE:
    with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f: cases.append((name, qpy.load(f)[0]))
for name in ("surface_d3", "bb_18_4_4", "steane_cnot"): cases.append((name, CIRCUITS[name]()))
print(f"{'circuit':24} {'topo':11} {'off: diff/pairs':>16} {'on: diff/pairs':>16} {'on sib w=1':>16}")
T = {k: [0, 0] for k in ("off", "on", "w25")}
for name, qc in cases:
    for topo, cmap in topologies(qc.num_qubits).items():
        r = {"off": analyze(qc, cmap, False), "on": analyze(qc, cmap, True), "w25": analyze(qc, cmap, True, 1.0)}
        for k, (s, d, *_) in r.items(): T[k][0] += d; T[k][1] += s + d
        f = lambda k: f"{r[k][1]}/{r[k][0]+r[k][1]} ({100*r[k][1]/max(1,r[k][0]+r[k][1]):.0f}%)"
        print(f"{name:24} {topo:11} {f('off'):>16} {f('on'):>16} {f('w25'):>16}", flush=True)
for k in T: print(f"{k}: sibling pairs on different rails {T[k][0]}/{T[k][1]} = {100*T[k][0]/T[k][1]:.1f}%")
