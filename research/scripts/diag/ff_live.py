"""Of EarlyMeasurement's feedforward RZs, how many must be applied live (target has a later
non-diagonal gate) vs deferred to classical post-processing (target's remaining program is diagonal
to measurement)? Also count feedforward rounds per circuit (distinct measure->live-RZ dependency depth)."""
import sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates")
from qiskit import qpy
from qiskit.converters import circuit_to_dag
from prism.encodings import DualRail
from prism_gate import CORE, MARABBECCA
DIAG = {"rz", "crz", "barrier", "measure", "if_else"}
DualRail.early_measure = True
T = [0, 0]
for name in CORE:
    with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f:
        qc = qpy.load(f)[0]
    lg = DualRail.logical_pm().run(qc); nodes = list(circuit_to_dag(lg).topological_op_nodes())
    live = deferred = 0; rounds = 0
    # per qubit: index of last non-diagonal op
    last_nd = {q: -1 for q in lg.qubits}
    for i, n in enumerate(nodes):
        if n.op.name not in DIAG:
            for q in n.qargs: last_nd[q] = i
    # feedforward chain depth: a live RZ waits for a measurement; count max nesting via measure index order
    for i, n in enumerate(nodes):
        if n.op.name == "if_else":
            t = n.qargs[0]
            if last_nd[t] > i: live += 1
            else: deferred += 1
    T[0] += live; T[1] += deferred
    print(f"{name:24} feedforward rz: live={live:3} deferred_to_postprocessing={deferred:3}")
print(f"TOTAL live={T[0]} deferred={T[1]}")
