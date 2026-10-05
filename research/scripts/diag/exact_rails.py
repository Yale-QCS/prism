"""Exact swap minimum for a lowered rail circuit with realization sets (transition-based, OLSQ2-style).

Blocks b = 0..B-1 hold a fixed rail->site mapping; between blocks any matching of edge SWAPs.
Each 2-rail op picks a block and a realization whose rail pair is adjacent there; dependencies
order blocks (same block allowed, circuit order kept). Minimizes total SWAPs; reports the bound
when the time limit hits. Usage: exact_rails.py instances.json [time_limit_s] [max_blocks]
"""

import json
import sys
import time

from ortools.sat.python import cp_model


def solve(inst, time_limit, max_blocks):
    n_phys, n_virt, edges = inst["n_phys"], inst["n_virt"], [tuple(e) for e in inst["edges"]]
    ops = [(k, o) for k, o in enumerate(inst["ops"]) if o["pairs"] and o["pairs"][0]]
    two_q = {k: o for k, o in ops}
    B = min(max_blocks, inst["prism_swaps"] + 1)
    m = cp_model.CpModel()
    pos = [[[m.NewBoolVar(f"pos{b}_{v}_{p}") for p in range(n_phys)] for v in range(n_virt)] for b in range(B)]
    for b in range(B):
        for v in range(n_virt):
            m.AddExactlyOne(pos[b][v])
        for p in range(n_phys):
            m.AddAtMostOne(pos[b][v][p] for v in range(n_virt))
    adj = {}
    # adjacency indicator per (block, rail a, rail b): a and b sit on some edge
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
    t_of = {}
    for k, o in ops:
        t = m.NewIntVar(0, B - 1, f"t{k}")
        t_of[k] = t
        choice = []
        for b in range(B):
            for r, pairs in enumerate(o["pairs"]):
                x = m.NewBoolVar(f"x{k}_{b}_{r}")
                choice.append(x)
                m.Add(t == b).OnlyEnforceIf(x)
                for (va, vb) in pairs:
                    m.AddImplication(x, adjacent(b, va, vb))
        m.AddExactlyOne(choice)
    # dependencies: pred block <= succ block, through 0-pair ops transitively
    succ = inst["succ"]
    n_ops = len(inst["ops"])
    # earliest-block variable for every op (0-pair ops get a free int var)
    tv = {k: (t_of[k] if k in t_of else m.NewIntVar(0, B - 1, f"t{k}")) for k in range(n_ops)}
    for k in range(n_ops):
        for s in succ[k]:
            m.Add(tv[k] <= tv[s])
    # swaps between blocks
    swaps = []
    for b in range(B - 1):
        s_e = {e: m.NewBoolVar(f"s{b}_{e}") for e in edges}
        swaps.extend(s_e.values())
        for p in range(n_phys):
            m.AddAtMostOne(s_e[e] for e in edges if p in e)
        for v in range(n_virt):
            for q in range(n_phys):
                inc = [e for e in edges if q in e]
                # pos[b+1][v][q] <-> (pos[b][v][q] and no swap at q) or OR_e (pos[b][v][other(e)] and s_e)
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
    t0 = time.time()
    st = solver.Solve(m)
    status = solver.StatusName(st)
    val = solver.ObjectiveValue() if st in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None
    return status, val, solver.BestObjectiveBound(), time.time() - t0, B


def main():
    insts = json.load(open(sys.argv[1]))
    limit = float(sys.argv[2]) if len(sys.argv) > 2 else 120
    max_blocks = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    tp = te = 0
    for inst in insts:
        if inst["prism_swaps"] == 0:
            print(f"{inst['circuit']:20} {inst['topo']:11} prism=0 optimal=0", flush=True)
            continue
        status, val, bound, dt, B = solve(inst, limit, max_blocks)
        if val is not None:
            tp += inst["prism_swaps"]; te += min(val, inst["prism_swaps"])
        print(f"{inst['circuit']:20} {inst['topo']:11} prism={inst['prism_swaps']:3} exact={val} bound={bound:.0f} "
              f"status={status} blocks={B} {dt:.0f}s", flush=True)
    print(f"TOTAL prism={tp} best_known={te:.0f} gap>={100*(tp-te)/max(tp,1):.1f}%")


if __name__ == "__main__":
    main()
