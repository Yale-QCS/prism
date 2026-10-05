"""Size the measurement-commutation rewrite: a qubit whose remaining gates are all diagonal and end in
a Z measurement can be measured at its last non-diagonal gate; every later CRZ on it becomes a
classically controlled RZ on the other operand (free). Counts removable CRZs and routes the reduced
circuit (CRZs deleted, measure kept) to size swaps/depth/duration."""
import sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates")
from qiskit import qpy
from qiskit.converters import circuit_to_dag, dag_to_circuit
from prism.encodings import DualRail
from prism.pipeline import build_pm
from prism_gate import CORE, MARABBECCA, topologies
DIAG = {"rz", "crz", "barrier"}
def rewrite(qc):
    dag = circuit_to_dag(qc)
    nodes = list(dag.topological_op_nodes())
    # per qubit: index of last non-diagonal, non-measure op; and whether it ends in measure
    last_nd, ends_meas = {q: -1 for q in qc.qubits}, {q: False for q in qc.qubits}
    for i, n in enumerate(nodes):
        for q in n.qargs:
            if n.op.name == "measure": ends_meas[q] = True
            elif n.op.name not in DIAG: last_nd[q] = i; ends_meas[q] = False
    early = {q for q in qc.qubits if ends_meas[q]}
    removed = 0
    for i, n in enumerate(nodes):
        if n.op.name == "crz" and any(q in early and i > last_nd[q] for q in n.qargs):
            dag.remove_op_node(n); removed += 1
    return dag_to_circuit(dag), removed, len(early)
tot = {k: [0, 0, 0.0] for k in ("base", "rewritten")}
crz_tot = rem_tot = 0
print(f"{'circuit':24} crz removed early_q | topo base -> rewritten")
for name in CORE:
    with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f:
        qc = qpy.load(f)[0]
    logical = DualRail.logical_pm().run(qc)
    new, removed, n_early = rewrite(logical)
    n_crz = logical.count_ops().get("crz", 0); crz_tot += n_crz; rem_tot += removed
    for topo, cmap in topologies(8).items():
        rows = []
        for key, circ in (("base", qc), ("rewritten", new)):
            pm = build_pm(cmap, enc=DualRail, seed=0); pm.run(circ); m = pm.property_set["circuit_metrics"]
            r = (m.swaps, m.depth, round(m.duration / 1000, 1)); rows.append(r)
            for i in range(3): tot[key][i] += r[i]
        print(f"{name:24} {n_crz:3} {removed:3} {n_early:2} | {topo:11} {rows[0]} -> {rows[1]}", flush=True)
b, r = tot["base"], tot["rewritten"]
print(f"CRZ total {crz_tot}, removable {rem_tot} ({100*rem_tot/crz_tot:.0f}%)")
print(f"swaps {b[0]} -> {r[0]} ({100*(r[0]-b[0])/b[0]:+.1f}%) depth {b[1]} -> {r[1]} ({100*(r[1]-b[1])/b[1]:+.1f}%) duration {b[2]:.0f} -> {r[2]:.0f} ({100*(r[2]-b[2])/b[2]:+.1f}%)")
