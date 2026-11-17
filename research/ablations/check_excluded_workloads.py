"""Reviewer W4: routing SWAPs of the 10 excluded MQT workloads under trivial, Greedy and PRISM (grid, hex_lattice).

Compiles each excluded workload at n=8 with the default-realization (trivial) compiler and with both search arms,
and records the routing SWAPs. It does not show that trivial inserts none: its 2026-08 output (9f9b679) had trivial
at 7 and 9 SWAPs on wstate (grid, hex), 4 on graphstate (hex) and 1 on bv (hex). The current check, on three graphs,
is research/rebuttal/s53/check_exclusion.py.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/paper"))

from qiskit import qpy

from paper_common import make_topologies
from marabbecca.encodings import DualRail
from marabbecca.lowering.commit import SearchBudget
from marabbecca.staged_pms import build_pm

EXCLUDED = ["bmw_quark_cardinality", "bv", "ghz", "ghz_dynamic", "graphstate",
            "qnn", "randomcircuit", "vqe_real_amp", "vqe_su2", "wstate"]
SEEDS = [0, 1, 2]
topos = {k: v for k, v in make_topologies(8).items() if k in ("grid", "hex_lattice")}

results = []
for name in EXCLUDED:
    with open(f"{ROOT}/artifacts/paper/manifests/circuits/{name}_n8.qpy", "rb") as f:
        qc = qpy.load(f)[0]
    for topo, cmap in topos.items():
        for strategy in ("trivial", "greedy", "prism"):
            for seed in SEEDS if strategy != "trivial" else SEEDS[:1]:
                budget = None
                if strategy != "trivial":
                    budget = SearchBudget(
                        layout_starts=40, refinement_iterations=16,
                        prism_swap_trials=40, heuristic_config="qiskit_sabre",
                        tie_break="load",
                    )
                pm = build_pm(cmap, enc=DualRail, strategy=strategy, seed=seed,
                              budget=budget)
                pm.run(qc)
                swaps = pm.property_set["routing_swaps"]
                results.append({"circuit": name, "topology": topo,
                                "strategy": strategy, "seed": seed,
                                "router_inserted_swaps": int(swaps)})
                print(results[-1], flush=True)

nonzero = [r for r in results if r["router_inserted_swaps"] > 0]
print(f"\n{len(results)} compiles; nonzero-SWAP rows: {len(nonzero)}")
for r in nonzero:
    print("  NONZERO:", r)
with open(f"{ROOT}/artifacts/paper/raw/rr_excluded_workloads_check.json", "w") as f:
    json.dump(results, f, indent=1)
