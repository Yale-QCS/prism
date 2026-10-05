"""Ceiling of a hybrid CRZ realization set {4 rail pairs, classical feedforward}: on prism's routes
(early measurement off), charge each SWAP to the op it serves; a CRZ is 'eligible' when one operand's
remaining program is diagonal to measurement. Report swaps charged to eligible CRZs (what converting
them would save, upper bound) and, if only CRZs charged >= k swaps are converted, the swaps saved and
sequential feedforward rounds created."""
import sys, warnings, collections
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates")
from qiskit import qpy
from prism.encodings import DualRail
from prism.lowering.commit_policies.prism_routing import PrismRouting
from prism.pipeline import build_pm
from prism_gate import CORE, MARABBECCA, topologies
DualRail.early_measure = False
BEST = {}
orig = PrismRouting._trace_to_payload
def spy(trace, ctx):
    BEST["trace"], BEST["ctx"] = trace, ctx; return orig(trace, ctx)
PrismRouting._trace_to_payload = staticmethod(spy)
orig_build = PrismRouting._build_result
def spy2(self, dag, ctx, out_qc, payload, refined_v2p):
    BEST["v2p0"] = list(refined_v2p); return orig_build(self, dag, ctx, out_qc, payload, refined_v2p)
PrismRouting._build_result = spy2
DIAG = {"rz", "crz", "barrier"}
def eligible_ops(ctx):
    """op index -> which logical operands (0=control,1=target) are early-measurable at that op."""
    ops = ctx.op_nodes; last_nd = {}; ends = {}
    for i, n in enumerate(ops):
        name = n.op.logical_name
        for lq in {v // 2 for v in ctx.virts_used[i]}:
            if name == "measure": ends[lq] = True
            elif name in DIAG or name in ("joint_herald", "x") and i < 3 * len(ends) + 40 and n.op.logical_name != "x": pass
            if name not in DIAG and name != "measure": last_nd[lq] = i; ends[lq] = False
    elig = {}
    for i, n in enumerate(ops):
        if n.op.logical_name == "crz":
            lqs = sorted({v // 2 for v in ctx.virts_used[i]})
            e = [lq for lq in lqs if ends.get(lq) and i > last_nd.get(lq, -1)]
            if e: elig[i] = (lqs, e)
    return elig, last_nd
tot = collections.Counter()
for name in CORE:
    with (MARABBECCA / f"artifacts/hpca/manifests/circuits/{name}_n8.qpy").open("rb") as f:
        qc = qpy.load(f)[0]
    for topo, cmap in topologies(8).items():
        pm = build_pm(cmap, enc=DualRail, seed=0); pm.run(qc)
        ctx, (events, _, n_swaps) = BEST["ctx"], BEST["trace"]
        elig, last_nd = eligible_ops(ctx)
        p2v = {p: v for v, p in enumerate(BEST["v2p0"])}; pending = []; charged = collections.Counter()
        for kind, a, b in events:
            if kind in (PrismRouting._EVENT_COMMIT, PrismRouting._EVENT_SUB_GATE):
                used = ctx.virts_used[a]; keep = []
                for mv in pending:
                    if mv & used: charged[a] += 1
                    else: keep.append(mv)
                pending = keep
            else:
                va, vb = p2v[a], p2v[b]; p2v[a], p2v[b] = vb, va; pending.append(frozenset((va, vb)))
        elig_swaps = sum(c for k, c in charged.items() if k in elig)
        row = f"{name:24} {topo:11} swaps={n_swaps:3} charged_to_eligible_crz={elig_swaps:3} eligible_crz={len(elig):3}"
        tot["swaps"] += n_swaps; tot["elig"] += elig_swaps
        for k in (1, 2, 3):
            conv = {i for i in elig if charged.get(i, 0) >= k}
            saved = sum(charged[i] for i in conv)
            # rounds: chain of converted CRZs where the target of one is (later) the measured operand of another
            rounds = 0; depth = {}
            for i in sorted(conv):
                lqs, e = elig[i]; other = [q for q in lqs if q not in e]
                d = max([depth.get(q, 0) for q in e], default=0) + 1
                for q in other: depth[q] = max(depth.get(q, 0), d)
                rounds = max(rounds, d)
            tot[f"saved{k}"] += saved; tot[f"rounds{k}"] = max(tot[f"rounds{k}"], rounds)
            row += f" | k>={k}: conv={len(conv):2} saved={saved:3} rounds={rounds}"
        print(row, flush=True)
print(f"TOTAL swaps={tot['swaps']} charged to eligible CRZs={tot['elig']} ({100*tot['elig']/tot['swaps']:.0f}%)")
for k in (1, 2, 3): print(f"convert CRZs charged >= {k}: saved {tot[f'saved{k}']} ({100*tot[f'saved{k}']/tot['swaps']:.0f}%), max rounds {tot[f'rounds{k}']}")
