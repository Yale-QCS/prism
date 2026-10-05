import sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates")
from qiskit import qpy
from qiskit.converters import circuit_to_dag
from prism.encodings import DualRail
from prism_gate import CORE, MARABBECCA
DIAG = {"rz", "crz", "barrier"}
T = [0, 0, 0]
for name in CORE:
    with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f:
        qc = qpy.load(f)[0]
    lg = DualRail.logical_pm().run(qc); dag = circuit_to_dag(lg); nodes = list(dag.topological_op_nodes())
    last_nd, ends = {q: -1 for q in lg.qubits}, {q: False for q in lg.qubits}
    for i, n in enumerate(nodes):
        for q in n.qargs:
            if n.op.name == "measure": ends[q] = True
            elif n.op.name not in DIAG: last_nd[q] = i; ends[q] = False
    classical_regs = [q for q in lg.qubits if ends[q] and last_nd[q] == -1]
    trivial = tail = 0
    for i, n in enumerate(nodes):
        if n.op.name != "crz": continue
        ops = [q for q in n.qargs if ends[q] and i > last_nd[q]]
        if not ops: continue
        if any(last_nd[q] == -1 for q in ops): trivial += 1
        else: tail += 1
    T[0] += lg.count_ops().get("crz", 0); T[1] += trivial; T[2] += tail
    print(f"{name:24} crz={lg.count_ops().get('crz',0):3} classical_input_qubits={len(classical_regs)} removable_via_classical_input={trivial:3} removable_via_measure_tail={tail:3}")
print(f"TOTAL crz={T[0]} classical-input={T[1]} ({100*T[1]/T[0]:.0f}%) measure-tail={T[2]} ({100*T[2]/T[0]:.0f}%)")
