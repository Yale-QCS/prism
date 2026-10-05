"""Rail exposure: sum over logical qubits of the time (Liu model) until that qubit's measurement in the
routed circuit, early measurement off vs on. Postselection overhead in dual-rail scales with integrated
occupation time, not only with the critical path."""
import sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates")
from qiskit import qpy
from qiskit.converters import circuit_to_dag
from prism.encodings import DualRail
from prism.pipeline import build_pm
from prism.utils.metrics import GATE_DURATIONS, is_synthetic_preparation
from prism_gate import CORE, MARABBECCA, topologies
def exposure(qc):
    finish = {}; meas_t = {}
    for node in circuit_to_dag(qc).topological_op_nodes():
        start = max((finish.get(q, 0.0) for q in node.qargs), default=0.0)
        dur = 0.0 if is_synthetic_preparation(node.op) else GATE_DURATIONS.get(node.op.name, 0.0)
        for q in node.qargs: finish[q] = start + dur
        if node.op.name == "measure":
            c = node.cargs[0]
            if c._register.name != "herald": meas_t[c] = start
    return sum(meas_t.values()) / 1000, max(finish.values()) / 1000
tot = {False: [0.0, 0.0], True: [0.0, 0.0]}
for name in CORE:
    with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f:
        qc = qpy.load(f)[0]
    for topo, cmap in topologies(8).items():
        for em in (False, True):
            DualRail.early_measure = em
            pm = build_pm(cmap, enc=DualRail, seed=0); out = pm.run(qc)
            e, d = exposure(out); tot[em][0] += e; tot[em][1] += d
b, r = tot[False], tot[True]
print(f"exposure (qubit-us summed over measured logical qubits): off {b[0]:.0f}  on {r[0]:.0f} ({100*(r[0]-b[0])/b[0]:+.1f}%)")
print(f"critical path (us): off {b[1]:.0f}  on {r[1]:.0f} ({100*(r[1]-b[1])/b[1]:+.1f}%)")
