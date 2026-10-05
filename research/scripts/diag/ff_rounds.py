"""Sequential feedforward rounds after EarlyMeasurement: longest path through the logical DAG counting
mid-circuit measurements (a measure followed by later ops on other qubits through if_else edges)."""
import sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates")
from qiskit import qpy
from qiskit.converters import circuit_to_dag
from prism.encodings import DualRail
from prism_gate import CORE, MARABBECCA
DualRail.early_measure = True
for name in CORE:
    with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f:
        qc = qpy.load(f)[0]
    lg = DualRail.logical_pm().run(qc); dag = circuit_to_dag(lg)
    nodes = list(dag.topological_op_nodes()); idx = {n: i for i, n in enumerate(nodes)}
    # measure is "mid-circuit" if any if_else later reads its clbit
    readers = {}
    for n in nodes:
        if n.op.name == "if_else": readers.setdefault(n.op.condition[0], []).append(n)
    mid = {n for n in nodes if n.op.name == "measure" and n.cargs[0] in readers}
    longest = {}
    for n in nodes:  # DAG edges: wire successors + clbit reads
        preds = [p for p in dag.predecessors(n) if p in idx]
        if n.op.name == "if_else":
            preds += [m for m in mid if m.cargs[0] == n.op.condition[0]]
        longest[n] = max([longest[p] for p in preds], default=0) + (1 if n in mid else 0)
    print(f"{name:24} mid-circuit measures={len(mid):2} sequential feedforward rounds={max(longest.values(), default=0)}")
