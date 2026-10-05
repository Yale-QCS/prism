"""CP-SAT improvement search from prism's route (transition model, windowed).

Prism's event stream is cut into blocks (maximal runs of disjoint SWAPs form one transition);
every op may move within +-W blocks of its prism block and change realization; mappings and
swap sets are free. Hints seed the search with prism's solution, so the first incumbent equals
prism's swap count and any improvement is a real gap. Usage:
exact_rails_hint.py instances.json [time_limit_s] [window] [only_circuit,...]
"""

import json
import sys
import time
from collections import defaultdict

from ortools.sat.python import cp_model


def blocks_from_events(inst):
    op_kinds = {inst["kinds"]["commit"], inst["kinds"]["sub"]}
    v2p = list(inst["v2p0"])
    p2v = {p: v for v, p in enumerate(v2p)}
    maps = [list(v2p)]
    b, in_tr, touched = 0, False, set()
    op_block, swaps = {}, defaultdict(list)

    def close():
        nonlocal b, in_tr, touched
        maps.append(list(v2p))
        b += 1
        in_tr, touched = False, set()

    for kind, a, c in inst["events"]:
        if kind not in op_kinds:
            if in_tr and (a in touched or c in touched):
                close()
            in_tr = True
            touched.update((a, c))
            swaps[b].append((min(a, c), max(a, c)))
            va, vb = p2v[a], p2v[c]
            v2p[va], v2p[vb] = c, a
            p2v[a], p2v[c] = vb, va
        else:
            if in_tr:
                close()
            op_block.setdefault(a, b)
    if in_tr:
        close()
    return maps, op_block, swaps, b + 1


def solve(inst, time_limit, W, log):
    n_phys, n_virt, edges = inst["n_phys"], inst["n_virt"], [tuple(e) for e in inst["edges"]]
    maps, op_block, hint_swaps, B = blocks_from_events(inst)
    ops = [(k, o) for k, o in enumerate(inst["ops"]) if o["pairs"] and o["pairs"][0]]
    m = cp_model.CpModel()
    pos = [[[m.NewBoolVar(f"pos{b}_{v}_{p}") for p in range(n_phys)] for v in range(n_virt)] for b in range(B)]
    for b in range(B):
        for v in range(n_virt):
            m.AddExactlyOne(pos[b][v])
            for p in range(n_phys):
                m.AddHint(pos[b][v][p], int(maps[b][v] == p))
        for p in range(n_phys):
            m.AddAtMostOne(pos[b][v][p] for v in range(n_virt))
    adj = {}

    def adjacent(b, va, vb):
        key = (b, min(va, vb), max(va, vb))
        if key in adj:
            return adj[key]
        lit = m.NewBoolVar(f"adj{key}")
        terms = []
        for (p, q) in edges:
            for (x, y) in ((p, q), (q, p)):
                t = m.NewBoolVar("")
                m.AddBoolAnd([pos[b][va][x], pos[b][vb][y]]).OnlyEnforceIf(t)
                m.AddBoolOr([pos[b][va][x].Not(), pos[b][vb][y].Not()]).OnlyEnforceIf(t.Not())
                terms.append(t)
        m.AddBoolOr(terms).OnlyEnforceIf(lit)
        m.AddBoolAnd([t.Not() for t in terms]).OnlyEnforceIf(lit.Not())
        adj[key] = lit
        return lit

    n_ops = len(inst["ops"])
    tv = {}
    for k in range(n_ops):
        hb = op_block.get(k, 0)
        lo, hi = max(0, hb - W), min(B - 1, hb + W)
        tv[k] = m.NewIntVar(lo, hi, f"t{k}")
        m.AddHint(tv[k], hb)
    for k, o in ops:
        hb = op_block[k]
        choice = []
        for b in range(max(0, hb - W), min(B - 1, hb + W) + 1):
            for r, pairs in enumerate(o["pairs"]):
                x = m.NewBoolVar(f"x{k}_{b}_{r}")
                choice.append(x)
                m.Add(tv[k] == b).OnlyEnforceIf(x)
                for (va, vb) in pairs:
                    m.AddImplication(x, adjacent(b, va, vb))
                hinted = b == hb and all((maps[b][va], maps[b][vb]) in edges or (maps[b][vb], maps[b][va]) in edges
                                          for va, vb in pairs)
                m.AddHint(x, int(hinted))
        m.AddExactlyOne(choice)
    for k in range(n_ops):
        for s in inst["succ"][k]:
            m.Add(tv[k] <= tv[s])
    swaps = []
    for b in range(B - 1):
        s_e = {e: m.NewBoolVar(f"s{b}_{e}") for e in edges}
        hs = set(hint_swaps.get(b, []))
        for e, var in s_e.items():
            m.AddHint(var, int(e in hs))
        swaps.extend(s_e.values())
        for p in range(n_phys):
            m.AddAtMostOne(s_e[e] for e in edges if p in e)
        for v in range(n_virt):
            for q in range(n_phys):
                inc = [e for e in edges if q in e]
                stay = m.NewBoolVar("")
                m.AddBoolAnd([pos[b][v][q]] + [s_e[e].Not() for e in inc]).OnlyEnforceIf(stay)
                m.AddBoolOr([pos[b][v][q].Not()] + [s_e[e] for e in inc]).OnlyEnforceIf(stay.Not())
                moves = []
                for e in inc:
                    o_ = e[0] if e[1] == q else e[1]
                    mv = m.NewBoolVar("")
                    m.AddBoolAnd([pos[b][v][o_], s_e[e]]).OnlyEnforceIf(mv)
                    m.AddBoolOr([pos[b][v][o_].Not(), s_e[e].Not()]).OnlyEnforceIf(mv.Not())
                    moves.append(mv)
                m.AddBoolOr([stay] + moves).OnlyEnforceIf(pos[b + 1][v][q])
                m.AddBoolAnd([stay.Not()] + [mv.Not() for mv in moves]).OnlyEnforceIf(pos[b + 1][v][q].Not())
    m.Minimize(sum(swaps))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 8

    class First(cp_model.CpSolverSolutionCallback):
        def __init__(self):
            super().__init__()
            self.first = None
            self.n = 0

        def on_solution_callback(self):
            self.n += 1
            if self.first is None:
                self.first = self.ObjectiveValue()

    cb = First()
    t0 = time.time()
    st = solver.Solve(m, cb)
    val = solver.ObjectiveValue() if st in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None
    return solver.StatusName(st), val, cb.first, solver.BestObjectiveBound(), time.time() - t0, B


def main():
    insts = json.load(open(sys.argv[1]))
    limit = float(sys.argv[2]) if len(sys.argv) > 2 else 120
    W = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    only = sys.argv[4].split(",") if len(sys.argv) > 4 else None
    tp = tb = 0
    for inst in insts:
        if only and inst["circuit"] not in only:
            continue
        if inst["prism_swaps"] == 0:
            print(f"{inst['circuit']:24} {inst['topo']:11} prism=0", flush=True)
            continue
        status, val, first, bound, dt, B = solve(inst, limit, W, False)
        best = min(val, inst["prism_swaps"]) if val is not None else inst["prism_swaps"]
        tp += inst["prism_swaps"]
        tb += best
        print(f"{inst['circuit']:24} {inst['topo']:11} prism={inst['prism_swaps']:3} first={first} best={val} "
              f"bound={bound:.0f} status={status} blocks={B} {dt:.0f}s", flush=True)
    print(f"TOTAL prism={tp} best={tb} improvement={100*(tp-tb)/max(tp,1):.1f}%")


if __name__ == "__main__":
    main()
