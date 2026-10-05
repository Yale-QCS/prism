"""Latency sweep: critical path and rail exposure of prism's routed paper set, EarlyMeasurement off vs on,
as a function of feedforward round latency. Measure duration M, feedforward latency F: an if_else starts
no earlier than (finish of the measurement writing its condition clbit) + F. Exposure = sum over logical
qubits of time until its logical measurement starts (qubit-us)."""
import sys, warnings, json
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates")
from qiskit import qpy
from qiskit.converters import circuit_to_dag
from prism.encodings import DualRail
from prism.pipeline import build_pm
from prism.utils.metrics import GATE_DURATIONS, is_synthetic_preparation
from prism_gate import CORE, MARABBECCA, topologies

def schedule(qc, M, F):
    finish, meas_fin, meas_start = {}, {}, {}
    for node in circuit_to_dag(qc).topological_op_nodes():
        start = max((finish.get(q, 0.0) for q in node.qargs), default=0.0)
        name = node.op.name
        if name == "if_else":
            cl, _ = node.op.condition
            start = max(start, meas_fin.get(cl, 0.0) + F)
            dur = 0.0  # body is rz only (free)
        elif name == "measure":
            dur = M
        else:
            dur = 0.0 if is_synthetic_preparation(node.op) else GATE_DURATIONS.get(name, 0.0)
        for q in node.qargs: finish[q] = start + dur
        if name == "measure":
            c = node.cargs[0]; meas_fin[c] = start + dur
            if c._register.name != "herald": meas_start[c] = start
    return max(finish.values()) / 1000, sum(meas_start.values()) / 1000

M = 1000.0
FS = [0, 500, 1000, 2000, 5000, 12000, 24000]
routed = {}
for name in CORE:
    with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f:
        qc = qpy.load(f)[0]
    for topo, cmap in topologies(8).items():
        for em in (False, True):
            DualRail.early_measure = em
            pm = build_pm(cmap, enc=DualRail, seed=0)
            routed[(name, topo, em)] = pm.run(qc)
            print("routed", name, topo, em, file=sys.stderr, flush=True)
DualRail.early_measure = False
rows = []
for F in FS:
    for name in CORE:
        for topo in ("grid", "hex_lattice"):
            for em in (False, True):
                cp, ex = schedule(routed[(name, topo, em)], M, F)
                rows.append(dict(F=F, name=name, topo=topo, em=em, cp=cp, ex=ex))
json.dump(rows, open(sys.argv[1], "w"))
print(f"M={M/1000:.1f} us; F (us) | critical path off/on (us, sum of 32) | exposure off/on (qubit-us)")
for F in FS:
    r = [x for x in rows if x["F"] == F]
    cp0 = sum(x["cp"] for x in r if not x["em"]); cp1 = sum(x["cp"] for x in r if x["em"])
    ex0 = sum(x["ex"] for x in r if not x["em"]); ex1 = sum(x["ex"] for x in r if x["em"])
    wins = sum(1 for a in r if a["em"] and a["cp"] < next(b["cp"] for b in r if not b["em"] and b["name"]==a["name"] and b["topo"]==a["topo"]))
    print(f"F={F/1000:5.1f} | cp {cp0:7.0f} -> {cp1:7.0f} ({100*(cp1-cp0)/cp0:+6.1f}%) | ex {ex0:7.0f} -> {ex1:7.0f} ({100*(ex1-ex0)/ex0:+6.1f}%) | on wins cp in {wins}/32")
print("\nper circuit, crossover F (us) where EM-on critical path stops beating off (grid):")
for name in CORE:
    line = []
    for F in FS:
        a = next(x for x in rows if x["F"]==F and x["name"]==name and x["topo"]=="grid" and x["em"])
        b = next(x for x in rows if x["F"]==F and x["name"]==name and x["topo"]=="grid" and not x["em"])
        line.append(f"{100*(a['cp']-b['cp'])/b['cp']:+5.0f}%")
    print(f"{name:24} " + " ".join(line))
