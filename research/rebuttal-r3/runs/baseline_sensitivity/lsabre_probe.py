"""Instrumented Logical-SABRE runs through the repository's own run_fairness._run_one.

Nothing is reimplemented: the wrappers below call the original DirectCommit.commit and
SabreSwap.run and only read their inputs/outputs.
"""
import os as _os
HERE = _os.path.dirname(_os.path.abspath(__file__)) + "/"
ROOT = _os.path.abspath(_os.path.join(HERE, "../../../..")) + "/"
import sys, warnings, json, collections, random
warnings.simplefilter("ignore")
REPO = ROOT.rstrip("/")
sys.path.insert(0, REPO + "/scripts/paper")
import networkx as nx
from qiskit import qpy
from qiskit.transpiler.passes import SabreSwap
import run_fairness
from paper_common import make_topologies
from marabbecca.lowering.commit_policies.direct import DirectCommit
from marabbecca.lowering.ir import LoweredOp

REC = {}
_orig_commit = DirectCommit.commit
_orig_sabre_run = SabreSwap.run
_orig_mwm = nx.max_weight_matching
MATCH_SEED = None  # None = repository default matching


def _commit(self, dag):
    res = _orig_commit(self, dag)
    flat = {q: i for i, q in enumerate(dag.qubits)}
    cm, pairs = self.coupling_map, self.pairs
    adj = lambda a, b: cm.distance(a, b) == 1
    it = iter(res.choices)
    cats = collections.Counter()
    for node in dag.topological_op_nodes():
        lop = node.op
        if not isinstance(lop, LoweredOp) or not lop.is_decision:
            continue
        idx = next(it)
        if lop.name != "swap":
            continue
        A = pairs[flat[node.qargs[0]] // 2]; B = pairs[flat[node.qargs[2]] // 2]
        aligned = adj(A[0], B[0]) and adj(A[1], B[1])
        crossed = adj(A[0], B[1]) and adj(A[1], B[0])
        n_edges = sum(adj(a, b) for a in A for b in B)
        cats["aligned" if aligned else "crossed_only" if crossed else "neither"] += 1
        cats[f"chosen{idx}"] += 1
        cats[f"edges{n_edges}"] += 1
    REC["logical_swaps"] = dict(cats)
    REC["direct_n_swaps"] = res.n_swaps
    REC["pairs"] = [list(p) for p in pairs]
    return res


def _edges(dag, name):
    idx = {q: i for i, q in enumerate(dag.qubits)}
    return collections.Counter(tuple(sorted(idx[q] for q in n.qargs)) for n in dag.op_nodes() if n.op.name == name)


def _sabre_run(self, dag):
    out = _orig_sabre_run(self, dag)
    if "direct_n_swaps" not in REC:  # quotient-level call (before expansion)
        REC["quotient_sabreswap_added"] = out.count_ops().get("swap", 0) - dag.count_ops().get("swap", 0)
        return out
    pairset = {tuple(sorted(p)) for p in REC["pairs"]}
    d = {}
    for name in ("crz", "rswap"):
        a, b = _edges(dag, name), _edges(out, name)
        d[f"{name}_total"] = sum(a.values())
        d[f"{name}_off_committed_edge"] = sum((a - b).values())
    d["rswap_off_matched_pair"] = sum(c for e, c in _edges(out, "rswap").items() if e not in pairset)
    d["phys_added"] = out.count_ops().get("swap", 0) - dag.count_ops().get("swap", 0)
    REC["physical_sabreswap"] = d
    return out


def _mwm(G, *a, **k):
    if MATCH_SEED is None:
        return _orig_mwm(G, *a, **k)
    rng = random.Random(MATCH_SEED)
    nodes = list(G.nodes()); rng.shuffle(nodes)
    edges = [tuple(rng.sample(e, 2)) for e in G.edges()]; rng.shuffle(edges)
    H = nx.Graph(); H.add_nodes_from(nodes); H.add_edges_from(edges)
    return _orig_mwm(H, *a, **k)


DirectCommit.commit = _commit
SabreSwap.run = _sabre_run
nx.max_weight_matching = _mwm


def run(circuit, width, topology, seed, match_seed=None):
    global MATCH_SEED
    MATCH_SEED = match_seed
    REC.clear()
    with open(f"{REPO}/artifacts/paper/manifests/circuits/{circuit}_n{width}.qpy", "rb") as f:
        qc = qpy.load(f)[0]
    cmap = make_topologies(width)[topology]
    spec = {"strategy": "logical", "reschedule": True}  # run_fairness._arm_spec_for_config for logical.toml
    row = dict(circuit=circuit, width=width, topology=topology, seed=seed, match_seed=match_seed)
    try:
        p = run_fairness._run_one(spec, qc, cmap, seed, "error")
        row.update(ok=True, router_inserted_swaps=p["router_inserted_swaps"], final_swap_instructions=p["final_swap_instructions"],
                   physical_depth=p["physical_depth"], perm_identity=p["physical_routing_permutation"] == list(range(cmap.size())),
                   pairs=p["quotient_partition_pairs"], qedges=p["quotient_graph_edges"], **{k: v for k, v in REC.items() if k != "pairs"})
    except Exception as e:  # noqa: BLE001
        row.update(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}")
    return row


def _task(t):
    return run(*t)
