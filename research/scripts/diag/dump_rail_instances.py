"""Dump small lowered instances (rail ops with realization sets, deps) as JSON for the exact solver,
plus prism's swap count on each, so the solver venv needs no qiskit."""
import sys, json, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/evm9/prism/main/src"); sys.path.insert(0, "/home/evm9/prism/main/research/scripts/gates")
from mqt.bench import get_benchmark, BenchmarkLevel
from qiskit.converters import circuit_to_dag
from qiskit.transpiler import CouplingMap
from prism.encodings import DualRail
from prism.lowering.commit_policies.prism_routing import PrismRouting
from prism.lowering.expansion import expand
from prism.pipeline import build_pm
from prism_gate import topologies
N = int(sys.argv[1]) if len(sys.argv) > 1 else 4
NAMES = ["dj", "qaoa", "qft", "draper_qft_adder", "qftentangled", "ae", "vqe_two_local", "hhl"]
out = []
for name in NAMES:
    try:
        qc = get_benchmark(name, level=BenchmarkLevel.INDEP, circuit_size=N)
    except Exception as e:
        print("skip", name, e); continue
    qc = qc.decompose(reps=4)
    logical = DualRail.logical_pm().run(qc)
    prog = expand(circuit_to_dag(logical), DualRail)
    pol = PrismRouting(CouplingMap.from_grid(4, 4), enc=DualRail, seed=0)  # only for _precompute
    ctx = pol._precompute(prog.dag)
    ops = [{"name": n.op.logical_name, "pairs": [[list(p) for p in real] for real in ctx.virt_pairs[k]]}
           for k, n in enumerate(ctx.op_nodes)]
    for topo, cmap in topologies(N).items():
        pm = build_pm(cmap, enc=DualRail, seed=0); pm.run(qc)
        m = pm.property_set["circuit_metrics"]
        out.append({"circuit": name, "n": N, "topo": topo, "n_phys": cmap.size(), "n_virt": ctx.n_virt,
                    "edges": [list(map(int, e)) for e in cmap.get_edges() if e[0] < e[1]],
                    "ops": ops, "succ": ctx.succ, "prism_swaps": m.swaps, "prism_depth": m.depth})
        print(name, topo, "ops", len(ops), "prism swaps", m.swaps, flush=True)
json.dump(out, open(f"/home/evm9/.claude/jobs/1ae99356/tmp/instances_n{N}.json", "w"))
