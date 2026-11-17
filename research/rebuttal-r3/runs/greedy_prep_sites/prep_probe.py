"""U3 probe: pre-preparation SWAPs, Greedy entry-layout commits, and prep ordering after scheduling.

Re-runs one published cell (circuit, topology, seed, arm) through the repository's own
pipeline (run_fairness._build_arm_pm) and observes the winning route by wrapping two
PrismRouting methods. Nothing in the repository is modified.

usage: prep_probe.py CONFIG CIRCUIT WIDTH TOPOLOGY SEED ARM  -> one JSON line on stdout
"""
import os as _os
HERE = _os.path.dirname(_os.path.abspath(__file__)) + "/"
ROOT = _os.path.abspath(_os.path.join(HERE, "../../../..")) + "/"

import json
import sys
import tomllib
from pathlib import Path

import os
REPO = Path(ROOT.rstrip("/"))
CODE = Path(os.environ.get("PROBE_TREE", str(REPO)))
sys.path.insert(0, str(CODE / "scripts/paper"))
sys.path.insert(0, str(CODE / "src"))

import run_fairness as rf  # noqa: E402
from paper_common import make_topologies  # noqa: E402
from qiskit import qpy  # noqa: E402
from qiskit.converters import circuit_to_dag, dag_to_circuit  # noqa: E402

from marabbecca.lowering.commit_policies.prism_routing import PrismRouting  # noqa: E402
from marabbecca.synthesis.reschedule import RescheduleCommutingDiagonals  # noqa: E402
from marabbecca.utils.metrics import physical_depth, physical_duration  # noqa: E402

cfg_path, circuit, width, topology, seed, arm = sys.argv[1:7]
width, seed = int(width), int(seed)
cfg = tomllib.loads(Path(cfg_path).read_text())
if os.environ.get("GREEDY_PREP_SITES"):
    cfg["greedy_prep_sites"] = True

# ---- observe the winning route ------------------------------------------------
traces = {}
captured = {}
_orig_emit = PrismRouting._emit_circuit_from_trace
_orig_build = PrismRouting._build_result


def _emit(self, trace, ctx, v2p_initial):
    qc = _orig_emit(self, trace, ctx, v2p_initial)
    traces[id(qc)] = (trace, ctx, list(v2p_initial))
    return qc


def _build(self, dag, ctx, out_qc, payload, v2p):
    trace, ctx2, v0 = traces[id(out_qc)]
    captured.update(policy=self, trace=trace, ctx=ctx2, v2p0=v0, out_qc=out_qc)
    return _orig_build(self, dag, ctx, out_qc, payload, v2p)


_orig_pre = PrismRouting._precompute


def _pre(self, dag):
    c = _orig_pre(self, dag)
    captured["ctx_full"] = c
    return c


PrismRouting._precompute = _pre
PrismRouting._emit_circuit_from_trace = _emit
PrismRouting._build_result = _build

with (REPO / "artifacts/paper/manifests/circuits" / f"{circuit}_n{width}.qpy").open("rb") as f:
    qc = qpy.load(f)[0]
cmap = make_topologies(width)[topology]
spec = rf._arm_spec_for_config(cfg, arm)
pm = rf._build_arm_pm(spec, cmap, seed, cfg["objective"])
final = pm.run(qc)
ps = pm.property_set

pol, (events, final_v2p, n_swaps) = captured["policy"], captured["trace"]
ctx, v2p0, out_qc = captured["ctx"], captured["v2p0"], captured["out_qc"]
n_virt, n_phys = ctx.n_virt, ctx.n_phys
dist = cmap.distance_matrix
names = [n.op.name for n in ctx.op_nodes]
EVC, EVS, EVG = PrismRouting._EVENT_COMMIT, PrismRouting._EVENT_SWAP, PrismRouting._EVENT_SUB_GATE


def logical(v):
    return v // 2 if v < n_virt else None  # q_to_virt follows registers q0..q{n-1}, two wires each


# ---- replay: classify each router SWAP and locate it in out_qc ------------------
v2p = list(v2p0)
p2v = [0] * n_phys
for v, p in enumerate(v2p):
    p2v[p] = v
lam = list(v2p0)  # entry layout with absorbable SWAPs folded in
prepared = set()
lam_prep = list(v2p0)  # each rail's site when its pair is prepared
active = set()  # logical qubits that have had a program gate (not just their preparation)
cat = {}
absorb_idx = []  # out_qc instruction indices of absorbable SWAPs
pos = 0
for kind, a, b in events:
    if kind == EVS:
        u, w = p2v[a], p2v[b]
        st = []
        for v in (u, w):
            l = logical(v)
            st.append("E" if l is None else ("A" if l in active else ("P" if l in prepared else "U")))
        key = "".join(sorted(st, key="APUE".index))
        cat[key] = cat.get(key, 0) + 1
        if "P" not in st and "A" not in st:
            absorb_idx.append(pos)
            lam[u], lam[w] = lam[w], lam[u]
        assert out_qc.data[pos].operation.name == "swap"
        pos += 1
        v2p[u], v2p[w] = v2p[w], v2p[u]
        p2v[a], p2v[b] = p2v[b], p2v[a]
        continue
    node = ctx.op_nodes[a]
    if kind == EVC:
        real = node.op.realizations[ctx.real_idx_map[a][b]]
        pos += len(real.data)
    else:
        real = node.op.realizations[ctx.real_idx_map[a][(b >> 16) & 0xFFFF]]
        twoq = [i for i, ci in enumerate(real.data) if len(ci.qubits) == 2]
        s = b & 0xFFFF
        start = twoq[s - 1] + 1 if s else 0
        end = len(real.data) if s == len(twoq) - 1 else twoq[s] + 1
        pos += end - start
    if names[a] == "joint_herald":
        prepared.add(logical(ctx.q_to_virt[node.qargs[0]]))
        for q in node.qargs:
            lam_prep[ctx.q_to_virt[q]] = v2p[ctx.q_to_virt[q]]
    elif not (names[a] == "x" and len(node.qargs) == 1):
        active.update(logical(ctx.q_to_virt[q]) for q in node.qargs)
assert pos == len(out_qc.data), (pos, len(out_qc.data))
assert sum(cat.values()) == n_swaps == ps["routing_swaps"]

# ---- depth with the absorbable SWAPs deleted (routing-stage circuit, rescheduled) ----
def resched(c):
    return dag_to_circuit(RescheduleCommutingDiagonals().run(circuit_to_dag(c)))


trimmed = out_qc.copy_empty_like()
drop = set(absorb_idx)
for i, ci in enumerate(out_qc.data):
    if i not in drop:
        trimmed.append(ci)
base_r, trim_r = resched(out_qc), resched(trimmed)

# ---- Greedy / PRISM entry layout: separated pairs, and commits under the folded layout ----
n_log = n_virt // 2
sep0 = [l for l in range(n_log) if dist[v2p0[2 * l]][v2p0[2 * l + 1]] > 1]
full = captured["ctx_full"]
crz_ops = [k for k, nm in enumerate(names) if nm == "crz" and len(full.virt_pairs[k]) > 1]
crz_sep = [k for k in crz_ops if any(logical(v) in sep0 for p in full.virt_pairs[k][0] for v in p)]
_, ch0 = pol._greedy_commit_ctx(full, v2p0)
_, ch1 = pol._greedy_commit_ctx(full, lam)
diff = sum(ch0[k] != ch1[k] for k in crz_ops)
_, ch2 = pol._greedy_commit_ctx(full, lam_prep)
diff_prep = sum(ch0[k] != ch2[k] for k in crz_ops)
diff_prep_sep = sum(ch0[k] != ch2[k] for k in crz_sep)
# distance of each Greedy-chosen realization at the layout when its operands are prepared (folded)
def rdist(k, choice, lay):
    local = full.real_idx_map[k].index(choice)
    return sum(dist[lay[u]][lay[v]] for u, v in full.virt_pairs[k][local])


# ---- (c) final circuit: does any program gate touch a rail before its pair's herald? ----
def prep_order_violations(c, v_start):
    p2v_ = [0] * n_phys
    for v, p in enumerate(v_start):
        p2v_[p] = v
    prep = set()
    bad = 0
    t = [0] * n_phys
    herald_t = {}
    early = 0
    for ci in c.data:
        qs = [c.find_bit(q).index for q in ci.qubits]
        nm = ci.operation.name
        free = nm in ("rz", "joint_herald") or getattr(ci.operation, "label", None) == "dualrail_synthetic_preparation"
        start = max(t[p] for p in qs)
        for p in qs:
            t[p] = start + (0 if free else 1)
        ls = {logical(p2v_[p]) for p in qs}
        if nm == "joint_herald":
            if len(ls) != 1 or None in ls:
                return "mapping-mismatch"
            (l,) = ls
            prep.add(l)
            herald_t[l] = start
        elif nm == "swap":
            a_, b_ = qs
            p2v_[a_], p2v_[b_] = p2v_[b_], p2v_[a_]
        elif nm == "x" and getattr(ci.operation, "label", None) == "dualrail_synthetic_preparation":
            pass
        else:
            if any(l is None or l not in prep for l in ls):
                bad += 1
            if any(start < herald_t.get(l, 10**9) for l in ls if l is not None):
                early += 1
    return bad, early


viol_route = prep_order_violations(base_r, v2p0)
final_v0 = list(v2p0)
viol_final = prep_order_violations(final, final_v0) if final.num_qubits == n_phys else None

m = ps["circuit_metrics"]
print(json.dumps({"code": PrismRouting.__module__ and __import__("marabbecca").__file__, "prep_flag": bool(os.environ.get("GREEDY_PREP_SITES")),
    "circuit": circuit, "width": width, "topology": topology, "seed": seed, "arm": arm,
    "router_swaps": n_swaps, "final_depth": m.depth, "final_duration": m.duration,
    "swap_cat": cat, "absorbable": len(absorb_idx),
    "route_depth_resched": physical_depth(base_r), "route_depth_resched_absorbed": physical_depth(trim_r),
    "route_dur_resched": physical_duration(base_r), "route_dur_resched_absorbed": physical_duration(trim_r),
    "n_logical": n_log, "sep_pairs_at_entry": len(sep0), "n_crz_decisions": len(crz_ops),
    "crz_with_separated_operand": len(crz_sep), "greedy_choice_differs_folded": diff, "greedy_choice_differs_at_prep_sites": diff_prep, "greedy_choice_differs_at_prep_sites_sep": diff_prep_sep,
    "greedy_dist_entry_vs_folded": [sum(rdist(k, ch0[k], lam) for k in crz_ops), sum(rdist(k, ch1[k], lam) for k in crz_ops)],
    "prep_order_violations_route": viol_route, "prep_order_violations_final": viol_final,
}), flush=True)
