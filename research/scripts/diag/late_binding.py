"""Late binding potential: the route fixes the SWAP sequence; each CRZ may move within its window
(between the barriers on its logical qubits) and take any realization adjacent under the layout at the
chosen position. Greedy list scheduling over positions with realization choice vs fixed choice.
Reports depth in unit-time non-free ops. Prism routes, paper set, seed 0."""
import sys, warnings, collections
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates"); sys.path.insert(0, "/tmp/claude-1000/-home-evm9-prism/1ae99356-0e84-472f-8923-fc3178a9233e/scratchpad")
from qiskit import qpy
from prism.encodings import DualRail
from prism.lowering.commit_policies.prism_routing import PrismRouting
from prism.pipeline import build_pm
from prism_gate import CORE, MARABBECCA
from lattices import lattices
DualRail.early_measure = False; DualRail.reschedule = False
LATS = [a for a in (sys.argv[1] if len(sys.argv) > 1 else "grid,hex").split(",")]
BEST = {}
orig = PrismRouting._trace_to_payload
def spy(trace, ctx):
    BEST["trace"], BEST["ctx"] = trace, ctx; return orig(trace, ctx)
PrismRouting._trace_to_payload = staticmethod(spy)
orig_build = PrismRouting._build_result
def spy2(self, dag, ctx, out_qc, payload, refined_v2p):
    BEST["v2p0"] = list(refined_v2p); return orig_build(self, dag, ctx, out_qc, payload, refined_v2p)
PrismRouting._build_result = spy2
FREE = {"rz"}
def analyze(edges, choice):
    ctx, (events, _, _) = BEST["ctx"], BEST["trace"]; v2p = list(BEST["v2p0"]); p2v = {p: v for v, p in enumerate(v2p)}
    # sequence: list of (kind, payload, layout-before) ; layout snapshot per position
    seq = []; layouts = []
    for kind, a, b in events:
        layouts.append(list(v2p))
        if kind == 1:
            seq.append(("swap", (a, b))); va, vb = p2v[a], p2v[b]; v2p[va], v2p[vb] = b, a; p2v[a], p2v[b] = vb, va
        else:
            seq.append(("op", (a, b)))
    N = len(seq)
    # windows for crz ops: positions between last non-diagonal op touching its logical qubits and the next
    name_of = lambda k: ctx.op_nodes[k].op.logical_name
    lq_of = lambda k: {v // 2 for v in ctx.virts_used[k]}
    last_nd = {}; window = {}
    for i, (kind, pl) in enumerate(seq):
        if kind != "op": continue
        k, b = pl; nm = name_of(k)
        if nm == "crz": window[i] = [max([last_nd.get(q, -1) for q in lq_of(k)]) + 1, N - 1]
        elif nm != "rz":
            for q in lq_of(k):
                last_nd[q] = i
                for j, w in window.items():
                    if q in lq_of(seq[j][1][0]) and w[1] == N - 1 and j < i: w[1] = i - 1
    # schedule: unit time for non-free ops; sites free times; rz free
    site_free = collections.defaultdict(int); placed = {}; finish = 0
    pending = []  # crz positions not yet placed
    for i in range(N):
        kind, pl = seq[i]
        if kind == "op" and name_of(pl[0]) == "crz":
            pending.append(i)
        # place pending crzs: lookahead over the remaining window; place now only if now is the best start
        for j in list(pending):
            lo, hi = window[j]
            if i < lo: continue
            k, b0 = seq[j][1]; opts = ctx.virt_pairs[k]
            best = None
            for p in range(max(i, lo), hi + 1):
                lay = layouts[p]
                rs = range(len(opts)) if choice else [b0]
                for r in rs:
                    if not all((lay[x], lay[y]) in edges for x, y in opts[r]): continue
                    sites = [lay[x] for pr in opts[r] for x in pr]
                    st = max(site_free[sv] for sv in sites)
                    if best is None or (st, p) < (best[0], best[1]): best = (st, p, r, sites)
            if best is None: continue
            st, p, r, sites = best
            if p == i or i == hi:
                if p != i:  # forced at the window end with a layout that fits there
                    lay = layouts[i]; cands = [rr for rr in (range(len(opts)) if choice else [b0]) if all((lay[x], lay[y]) in edges for x, y in opts[rr])]
                    if not cands: continue
                    r = min(cands, key=lambda rr: max(site_free[lay[x]] for pr in opts[rr] for x in pr)); sites = [lay[x] for pr in opts[r] for x in pr]; st = max(site_free[sv] for sv in sites)
                for sv in sites: site_free[sv] = st + 1
                finish = max(finish, st + 1); placed[j] = (i, r); pending.remove(j)
        if kind == "swap":
            a, b = pl; st = max(site_free[a], site_free[b]); site_free[a] = site_free[b] = st + 1; finish = max(finish, st + 1)
        elif name_of(pl[0]) != "crz":
            k, b = pl; nm = name_of(k)
            if nm == "rz": continue
            lay = layouts[i]; sites = [lay[v] for v in ctx.virts_used[k]]
            st = max(site_free[s] for s in sites); w = 0 if nm in ("joint_herald",) else 1
            for s in sites: site_free[s] = st + w
            finish = max(finish, st + w)
    assert not pending, pending[:3]
    moved = sum(1 for j, (i, r) in placed.items() if i != j); rechosen = sum(1 for j, (i, r) in placed.items() if r != seq[j][1][1])
    return finish, moved, rechosen, len(placed)
for lat in LATS:
    cmap = lattices(8)[lat]; edges = set(map(tuple, cmap.get_edges()))
    T = [0, 0, 0, 0, 0, 0]
    for name in CORE:
        with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f: qc = qpy.load(f)[0]
        pm = build_pm(cmap, enc=DualRail, seed=0); pm.run(qc); m = pm.property_set["circuit_metrics"]
        d_fixed, _, _, n = analyze(edges, False); d_late, moved, rechosen, _ = analyze(edges, True)
        T[0] += m.depth; T[1] += d_fixed; T[2] += d_late; T[3] += moved; T[4] += rechosen; T[5] += n
    print(f"{lat:10}: metric depth {T[0]} | list-scheduled, fixed realizations {T[1]} | late binding {T[2]} ({100*(T[2]-T[1])/T[1]:+.1f}% vs fixed) | crz moved {T[3]}/{T[5]} rechosen {T[4]}/{T[5]}", flush=True)
