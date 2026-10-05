"""How much of prism's swap count is driven by RX joins: route the lowered circuit with a random
fraction of logical RX gates deleted (semantics ignored; routing cost only)."""
import sys, warnings, random
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates")
from qiskit import qpy
from qiskit.converters import circuit_to_dag, dag_to_circuit
from prism.encodings import DualRail
from prism.pipeline import build_pm
from prism import logical as lg
from prism_gate import CORE, MARABBECCA, topologies
FRACS = [0.0, 0.25, 0.5, 1.0]
orig = DualRail.logical_pm
def drop_rx(qc, frac, seed=0):
    rng = random.Random(seed); dag = circuit_to_dag(qc)
    for n in list(dag.op_nodes()):
        if n.op.name == "rx" and rng.random() < frac:
            dag.remove_op_node(n)
    return dag_to_circuit(dag)
tot = {f: [0, 0, 0.0, 0] for f in FRACS}
for name in CORE:
    with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f:
        qc = qpy.load(f)[0]
    logical = orig().run(qc)
    for topo, cmap in topologies(8).items():
        row = f"{name:24} {topo:11}"
        for fr in FRACS:
            lq = drop_rx(logical, fr)
            # run the pipeline from the already-optimized logical circuit; logical stage is idempotent
            pm = build_pm(cmap, enc=DualRail, seed=0); pm.run(lq); m = pm.property_set["circuit_metrics"]
            r = (m.swaps, m.depth, round(m.duration / 1000, 1), lq.count_ops().get("rx", 0))
            for i in range(4): tot[fr][i] += r[i]
            row += f" {str(r):>20}"
        print(row, flush=True)
b = tot[0.0]
for fr in FRACS:
    t = tot[fr]
    print(f"drop_rx={fr}: rx {t[3]} swaps {t[0]} ({100*(t[0]-b[0])/b[0]:+.1f}%) depth {t[1]} ({100*(t[1]-b[1])/b[1]:+.1f}%) duration {t[2]:.0f} ({100*(t[2]-b[2])/b[2]:+.1f}%)")
