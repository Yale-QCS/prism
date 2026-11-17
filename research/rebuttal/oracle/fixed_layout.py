"""Fixed-initial-layout oracle follow-up (pre-registered in README.md): S4, SG, PRISM and Greedy from the same layouts.

Usage: .venv/bin/python research/rebuttal/oracle/fixed_layout.py
Writes data/fixed_layout.jsonl (one row per instance and layout).
"""

import json
import math
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/paper"))
import oracle as O  # noqa: E402
from qiskit import QuantumCircuit  # noqa: E402
from qiskit.converters import circuit_to_dag  # noqa: E402
from qiskit.transpiler import CouplingMap  # noqa: E402

from marabbecca.encodings import DualRail  # noqa: E402
from marabbecca.lowering.commit_policies.prism_routing import PrismRouting  # noqa: E402
from marabbecca.lowering.expansion import LowerExpansion  # noqa: E402

K, SEED, TIMEOUT, SWAP_TRIALS = 5, 2026, 600.0, 40
OUT = Path(__file__).parent / "data/fixed_layout.jsonl"


class LocalInit(DualRail):
    """DualRail with local initialization: no co-location herald (as in oracle._run_compiler)."""

    local_init = True


def lowered(gate_pairs, n_logical):
    qc = QuantumCircuit(n_logical)
    for ctrl, tgt in gate_pairs:
        qc.crz(math.pi / 4, ctrl, tgt)
    logical = LocalInit.logical_pm().run(qc)
    return LowerExpansion(enc=LocalInit).run(circuit_to_dag(logical))


def heuristic(dag, cmap, layout, binding):
    """One route from the fixed layout (no layout search); returns (SWAPs, Greedy's choice per op node)."""
    policy = PrismRouting(cmap, enc=LocalInit, seed=0, binding_mode=binding)
    ctx = policy._precompute(dag)
    v2p = [0] * ctx.n_virt
    for q, virt in ctx.q_to_virt.items():
        reg = next(r for r in dag.qregs.values() if q in r)
        v2p[virt] = layout[2 * int(reg.name[1:]) + list(reg).index(q)]
    v2p += [p for p in range(ctx.n_phys) if p not in set(v2p)]  # the kernel takes a full permutation
    trace, _, _ = policy._route(ctx, v2p, 0, SWAP_TRIALS)
    _, choices = policy._greedy_commit_ctx(ctx, v2p)
    return int(trace[2]), ctx, choices


def greedy_instance(inst, dag, ctx, choices):
    """The instance with each CR_z's support fixed to Greedy's binding at the layout."""
    seen, picks = Counter(), {}
    for node, choice in zip(ctx.op_nodes, choices):
        if node.op.name != "crz":
            continue
        logical = [int(next(r for r in dag.qregs.values() if q in r).name[1:]) for q in node.qargs[::2]]
        key = (logical[0], logical[1])
        picks[(key, seen[key])] = choice
        seen[key] += 1
    seen, gates = Counter(), []
    for g in inst.gates:
        key = (g.ctrl, g.tgt)
        r = picks[(key, seen[key])]
        seen[key] += 1
        gates.append(O.Gate(ctrl=g.ctrl, tgt=g.tgt, supports=frozenset({(2 * g.ctrl + r // 2, 2 * g.tgt + r % 2)})))
    return O.Instance(n_logical=inst.n_logical, n_phys=inst.n_phys, adj=inst.adj, gates=tuple(gates),
                      predecessors=inst.predecessors, label=inst.label + "_greedy")


def main():
    certified = {r["instance_name"] for r in map(json.loads, open(Path(__file__).parent / "data/oracle.jsonl"))
                 if r["status_multi"] == "exact" and r["status_single"] == "exact"}
    done = {(r["instance"], r["layout_index"]) for r in map(json.loads, OUT.open())} if OUT.exists() else set()
    with OUT.open("a") as f:
        for name, builder in O.INSTANCE_CATALOG:
            if name not in certified:
                continue
            inst, gate_pairs, edges = builder(True)
            cmap = CouplingMap(edges + [(b, a) for a, b in edges])
            dag = lowered(gate_pairs, inst.n_logical)
            rng = random.Random(f"{SEED}:{name}")
            layouts = [tuple(rng.sample(range(inst.n_phys), inst.n_rails)) for _ in range(K)]
            for i, layout in enumerate(layouts):
                if (name, i) in done:
                    continue
                prism, _, _ = heuristic(dag, cmap, layout, "retained")
                greedy, ctx, choices = heuristic(dag, cmap, layout, "greedy")
                s4 = O.solve(inst, timeout=TIMEOUT, init_layout=layout)
                sg = O.solve(greedy_instance(inst, dag, ctx, choices), timeout=TIMEOUT, init_layout=layout)
                row = {"instance": name, "n_logical": inst.n_logical, "n_phys": inst.n_phys, "n_gates": inst.n_gates,
                       "layout_index": i, "layout": layout, "S4": s4.swap_count, "S4_status": s4.status,
                       "SG": sg.swap_count, "SG_status": sg.status, "PRISM": prism, "Greedy": greedy}
                f.write(json.dumps(row) + "\n")
                f.flush()
                print(name, i, "S4", s4.swap_count, s4.status, "SG", sg.swap_count, sg.status, "PRISM", prism, "Greedy", greedy, flush=True)


if __name__ == "__main__":
    main()
