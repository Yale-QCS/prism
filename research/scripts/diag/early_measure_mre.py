"""RemoveDiagonalGatesBeforeMeasure vs EarlyMeasurement on the smallest case that separates them."""
from qiskit import QuantumCircuit
from qiskit.converters import circuit_to_dag, dag_to_circuit
from qiskit.transpiler.passes import RemoveDiagonalGatesBeforeMeasure
from qiskit.quantum_info import Statevector
from prism.synthesis.early_measure import EarlyMeasurement

theta = 0.7
qc = QuantumCircuit(2, 2)
qc.h(0); qc.h(1)
qc.crz(theta, 0, 1)   # diagonal; control q0 goes straight to measure, target q1 does NOT
qc.rx(0.3, 1)         # non-diagonal on q1 after the crz
qc.measure([0, 1], [0, 1])
print("input\n", qc)

qk = RemoveDiagonalGatesBeforeMeasure()(qc)
print("Qiskit RemoveDiagonalGatesBeforeMeasure: crz kept =", "crz" in qk.count_ops())

em = EarlyMeasurement()(qc)
print("EarlyMeasurement\n", em)

# distribution check (branch enumeration, since Statevector cannot run if_test)
def probs_orig():
    sv = Statevector.from_instruction(qc.remove_final_measurements(inplace=False))
    return sv.probabilities_dict()

def probs_early():
    out = {}
    for m0 in (0, 1):
        pre = QuantumCircuit(2); pre.h(0); pre.h(1)
        sv = Statevector.from_instruction(pre)
        # project q0 onto m0 (the early measurement)
        proj = QuantumCircuit(2)
        sv = sv.evolve(proj)
        d = sv.data.copy()
        for idx in range(4):
            if (idx >> 0) & 1 != m0:
                d[idx] = 0
        p0 = (abs(d) ** 2).sum()
        d /= p0 ** 0.5
        rest = QuantumCircuit(2)
        if m0: rest.rz(theta, 1)     # the feedforward rz replaces the crz
        rest.rx(0.3, 1)
        sv = Statevector(d).evolve(rest)
        for k, v in sv.probabilities_dict().items():
            out[k] = out.get(k, 0) + p0 * v
    return out

a, b = probs_orig(), probs_early()
print("max |p_orig - p_early| =", max(abs(a.get(k, 0) - b.get(k, 0)) for k in set(a) | set(b)))

# --- physical view: lower + route both versions on a 2x2 grid (4 rails = 2 dual-rail qubits) ---
from qiskit.transpiler import CouplingMap
from prism.encodings import DualRail
from prism.pipeline import build_pm
from prism.utils.metrics import physical_duration, physical_depth
cmap = CouplingMap.from_grid(2, 3)
for label, flag in (("early_measure off", False), ("early_measure on", True)):
    DualRail.early_measure = flag
    pm = build_pm(cmap, enc=DualRail, seed=0)
    phys = pm.run(qc)
    print(f"\n=== {label} ===")
    print(phys)
    print("ops", dict(phys.count_ops()), "| depth(non-free)", physical_depth(phys), "| duration ns", physical_duration(phys))
DualRail.early_measure = False
