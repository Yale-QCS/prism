"""Qubit reuse + prism: compile each circuit as-is and after measure-and-reset reuse, each on the
smallest grid / hex lattice for its own width. Reports rails, swaps, physical depth, duration.

Usage: .venv/bin/python research/scripts/qec/reuse_experiment.py [budget] [seed]
"""

from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
HERE = Path(__file__).absolute().parent
sys.path.insert(0, str(HERE.parents[2] / "src"))
sys.path.insert(0, str(HERE))

from mqt.bench import get_benchmark_alg  # noqa: E402
from qiskit import transpile  # noqa: E402
from qiskit.transpiler import PassManager  # noqa: E402
from qiskit.transpiler.passes import RemoveBarriers  # noqa: E402

from prism.encodings import DualRail  # noqa: E402
from prism.lowering.commit import SearchBudget  # noqa: E402
from prism.pipeline import build_pm  # noqa: E402
from qec_quick import CIRCUITS, make_topologies  # noqa: E402
from qubit_reuse import check_dependencies, qubit_reuse  # noqa: E402


def mqt(name: str, n: int):
    """Alg-level benchmark, barriers removed, decomposed to 1q/2q so reuse can see the structure."""
    qc = PassManager([RemoveBarriers()]).run(get_benchmark_alg(benchmark=name, circuit_size=n))
    return transpile(qc, basis_gates=["u", "cx", "measure", "reset"], optimization_level=0)


def compile_prism(qc, cmap, seed, budget):
    pm = build_pm(cmap, enc=DualRail, seed=seed, budget=budget)
    t0 = time.time()
    pm.run(qc)
    m = pm.property_set["circuit_metrics"]
    return {"swaps": m.swaps, "depth": m.depth, "duration_us": round(m.duration / 1000, 1), "sec": round(time.time() - t0, 1)}


def main() -> None:
    scale = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    budget = SearchBudget(layout_starts=scale, refinement_iterations=max(2, scale // 2), swap_trials=scale)
    cases = {n: CIRCUITS[n]() for n in ("surface_d3", "bb_18_4_4", "steane_cnot", "honeycomb_2x2", "ls_merge_d3", "surface_d5")}
    for n in ("ghz", "bv", "dj", "wstate", "qft", "ae"):
        cases[f"{n}8"] = mqt(n, 8)
    rows = []
    print(f"{'circuit':14} {'topo':11} {'variant':8} {'q':>3} {'rails':>5} {'ldepth':>6} {'swaps':>5} {'depth':>5} {'dur_us':>7} {'sec':>5}", flush=True)
    for name, qc in cases.items():
        reused = qubit_reuse(qc)
        assert check_dependencies(qc, reused)
        for topo in ("grid", "hex_lattice"):
            for variant, circ in (("original", qc), ("reuse", reused)):
                if variant == "reuse" and reused.num_qubits == qc.num_qubits:
                    continue
                cmap = make_topologies(circ.num_qubits)[topo]
                r = compile_prism(circ, cmap, seed, budget)
                row = {"circuit": name, "topo": topo, "variant": variant, "logical_qubits": circ.num_qubits, "rails": cmap.size(), "logical_depth": circ.depth(), **r}
                rows.append(row)
                print(f"{name:14} {topo:11} {variant:8} {circ.num_qubits:3} {cmap.size():5} {circ.depth():6} {r['swaps']:5} {r['depth']:5} {r['duration_us']:7} {r['sec']:5}", flush=True)
    (HERE / f"reuse_experiment_b{scale}_s{seed}.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
