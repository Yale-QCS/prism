"""Where does depth go with commutation-aware deps? For each routed circuit (swaps objective):
depth, swap-free depth (swaps deleted, emitted order kept), and rescheduled depth (physical diagonal
gates on shared rails may reorder: critical-path list scheduling over the commutation-relaxed DAG)."""
import sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates")
from qiskit import qpy
from qiskit.converters import circuit_to_dag
from prism.encodings import DualRail
from prism.lowering.commit_policies.prism_routing import PrismRouting
from prism.pipeline import build_pm
from prism.utils.metrics import is_free
from prism_gate import CORE, MARABBECCA, topologies
DualRail.early_measure = False
DIAG = {"rz", "crz"}
def swap_free_depth(qc):
    return qc.depth(filter_function=lambda i: not is_free(i.operation) and i.operation.name != "swap")
def rescheduled_depth(qc, keep_swaps=True):
    nodes = [n for n in circuit_to_dag(qc).topological_op_nodes() if not is_free(n.op) and (keep_swaps or n.op.name != "swap")]
    # relaxed DAG: op depends on last non-diagonal per qubit, plus all diagonals since if it is non-diagonal
    last_nd, diags = {}, {}; preds = [set() for _ in nodes]
    for k, n in enumerate(nodes):
        d = n.op.name in DIAG
        for q in n.qargs:
            if q in last_nd: preds[k].add(last_nd[q])
            if not d: preds[k].update(diags.get(q, ()))
        for q in n.qargs:
            if d: diags.setdefault(q, []).append(k)
            else: last_nd[q] = k; diags[q] = []
    succs = [[] for _ in nodes]
    for k, ps in enumerate(preds):
        for p in ps: succs[p].append(k)
    # critical path priority (longest path to sink, unit weights)
    cp = [0] * len(nodes)
    for k in range(len(nodes) - 1, -1, -1): cp[k] = 1 + max((cp[s] for s in succs[k]), default=0)
    # list schedule: unit-time ops, one op per qubit per step, deps respected
    ready_t = [0] * len(nodes); done_t = [None] * len(nodes); qubit_free = {}
    order = sorted(range(len(nodes)), key=lambda k: (-cp[k], k))
    remaining = set(range(len(nodes))); t_of = {}
    import heapq
    while remaining:
        cand = [k for k in remaining if all(done_t[p] is not None for p in preds[k])]
        cand.sort(key=lambda k: (-cp[k], k))
        for k in cand:
            start = max([done_t[p] for p in preds[k]] + [qubit_free.get(q, 0) for q in nodes[k].qargs] + [0])
            done_t[k] = start + 1
            for q in nodes[k].qargs: qubit_free[q] = start + 1
            remaining.discard(k)
    return max(done_t)
tot = {False: [0, 0, 0, 0], True: [0, 0, 0, 0]}
for name in CORE:
    with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f: qc = qpy.load(f)[0]
    for topo, cmap in topologies(8).items():
        row = f"{name:24} {topo:11}"
        for flag in (False, True):
            PrismRouting.COMMUTE_DIAGONAL = flag
            pm = build_pm(cmap, enc=DualRail, seed=0); out = pm.run(qc); m = pm.property_set["circuit_metrics"]
            r = (m.depth, swap_free_depth(out), rescheduled_depth(out), rescheduled_depth(out, keep_swaps=False))
            for i in range(4): tot[flag][i] += r[i]
            row += f" | commute={flag!s:5} depth={r[0]:3} swapfree={r[1]:3} resched={r[2]:3} resched_swapfree={r[3]:3}"
        print(row, flush=True)
PrismRouting.COMMUTE_DIAGONAL = True
for flag in (False, True):
    t = tot[flag]; print(f"commute={flag!s:5}: depth {t[0]} swap-free depth {t[1]} rescheduled depth {t[2]} rescheduled swap-free {t[3]}")
