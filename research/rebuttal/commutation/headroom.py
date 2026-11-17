"""Routing-free depth headroom: dependency rule x realization policy, all-to-all connectivity."""
import warnings; warnings.filterwarnings("ignore")
from qiskit import qpy
from qiskit.converters import circuit_to_dag
from marabbecca.encodings import DualRail
from marabbecca.lowering.expansion import LowerExpansion
import sys; sys.path.insert(0, "scripts/paper"); from paper_common import *  # noqa
BENCH = ["dj","qaoa","draper_qft_adder","modular_adder","qft","qpeexact","qpeinexact","qftentangled","bmw_quark_copula","hhl","ae","cdkm_ripple_carry_adder","full_adder","vqe_two_local","rg_qft_multiplier","multiplier"]
DIAG = {"crz", "rz"}; FREE = {"rz", "joint_herald"}

def lowered(name):
    qc = qpy.load(open(f"artifacts/paper/manifests/circuits/{name}_n8.qpy", "rb"))[0]
    dag = LowerExpansion(enc=DualRail).run(circuit_to_dag(DualRail.logical_pm().run(qc)))
    idx = {q: i for i, q in enumerate(dag.qubits)}
    ops = []
    for n in dag.topological_op_nodes():
        wires = [idx[q] for q in n.qargs]
        reals = [sorted({wires[r.find_bit(q).index] for g in r.data if g.operation.name not in FREE for q in g.qubits}) for r in n.op.realizations]
        ops.append((n.op.name, wires, reals, n.op.default_index))
    return ops

def deps(ops, commute):
    last_nd, since, pred = {}, {}, [set() for _ in ops]
    for k, (name, wires, _, _) in enumerate(ops):
        d = commute and name in DIAG
        for w in wires:
            if w in last_nd: pred[k].add(last_nd[w])
            if not d: pred[k].update(since.get(w, ()))
        for w in wires:
            if d: since.setdefault(w, []).append(k)
            else: last_nd[w] = k; since[w] = []
    return pred

def schedule(ops, pred, free_choice):
    done, layer, n = set(), 0, len(ops)
    remaining = set(range(n))
    while remaining:
        progressed = True
        while progressed:  # zero-duration ops run as soon as ready
            progressed = False
            for k in sorted(remaining):
                if ops[k][0] in FREE and pred[k] <= done:
                    done.add(k); remaining.discard(k); progressed = True
        if not remaining: break
        busy, ran = set(), []
        for k in sorted(remaining):
            if not pred[k] <= done: continue
            name, wires, reals, di = ops[k]
            cands = reals if free_choice else [reals[di]]
            for r in sorted(cands, key=len):
                if not busy & set(r):
                    busy |= set(r); ran.append(k); break
        if not ran: raise RuntimeError("stuck")
        layer += 1; done |= set(ran); remaining -= set(ran)
    return layer

tot = {}
for b in BENCH:
    ops = lowered(b)
    row = {
        "order, fixed": schedule(ops, deps(ops, False), False),
        "order, free rail": schedule(ops, deps(ops, False), True),
        "commute, fixed": schedule(ops, deps(ops, True), False),
        "commute, free rail": schedule(ops, deps(ops, True), True),
    }
    for k, v in row.items(): tot[k] = tot.get(k, 0) + v
    print(f"{b:24s}", "  ".join(f"{v:4d}" for v in row.values()))
print("TOTAL", tot)
