"""Rail-X bug, option (a): what the physical stage's 2Q resynthesis buys, and whether removing it removes the leak.

  .venv/bin/python research/rebuttal/railx/option_a.py --workers 2

Compiles each cell twice with the `core` settings: as is, and with
`ConsolidateBlocks` disabled in-process (the logical stage does not use it, so
only the physical O3 stage's 2Q-block resynthesis is removed). Rows in
`data/option_a.jsonl`.

The recorded rows were compiled with the fix of 9cb6c53 already in place (it
removes ConsolidateBlocks in src/), so both variants are identical there and
the rows serve as its verification: 276 rows, 0 with rx, unlabeled x or any
instruction that leaves the one-photon-per-pair space.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path[:0] = [str(REPO / "scripts/paper"), str(REPO / "src"), str(REPO / "research/rebuttal/wallclock")]

import check  # noqa: E402
import run  # noqa: E402
import run_fairness  # noqa: E402
from paper_common import make_topologies  # noqa: E402
from qiskit.transpiler.passes import ConsolidateBlocks  # noqa: E402

RESYNTHESIZE = ConsolidateBlocks.run


def _cell(task: tuple) -> list[dict]:
    from qiskit import qpy

    from marabbecca.utils.metrics import physical_depth, physical_duration

    circuit, width, topology, seed = task
    with (REPO / f"artifacts/paper/manifests/circuits/{circuit}_n{width}.qpy").open("rb") as f:
        qc = qpy.load(f)[0].remove_final_measurements(inplace=False)
    rows = []
    for variant in ("o3", "no_2q_resynthesis"):
        ConsolidateBlocks.run = RESYNTHESIZE if variant == "o3" else (lambda self, dag: dag)
        for arm in ("greedy", "prism"):
            pm = run_fairness._build_arm_pm(run_fairness._arm_spec_for_config(run.CFG, arm), make_topologies(width)[topology], seed, "error")
            out = pm.run(qc)
            counts = out.count_ops()
            rows.append({
                "circuit": circuit, "width": width, "topology": topology, "seed": seed, "variant": variant, "arm": arm,
                "routing_swaps": int(pm.property_set["routing_swaps"]), "depth": physical_depth(out),
                "duration_us": physical_duration(out) / 1e3, "rx": int(counts.get("rx", 0)),
                "extra_x": int(counts.get("x", 0)) - qc.num_qubits, "leaking_instructions": len(check.leaks(out)),
            })
    ConsolidateBlocks.run = RESYNTHESIZE
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    tasks = [(c, 8, t, s) for c in run.CFG["circuits"] for t in ("grid", "hex_lattice") for s in (0, 100)]
    tasks += [("multiplier", 8, "hex_lattice", 900)]
    tasks += [(c, 16, "grid", 0) for c in ("multiplier", "rg_qft_multiplier", "qft", "hhl")]
    path = HERE / "data" / "option_a.jsonl"
    path.parent.mkdir(exist_ok=True)
    with path.open("w") as f, ProcessPoolExecutor(args.workers) as pool:
        for rows in pool.map(_cell, tasks):
            for row in rows:
                f.write(json.dumps(row) + "\n")
            f.flush()
            print(rows[0]["circuit"], rows[0]["width"], rows[0]["topology"], rows[0]["seed"], flush=True)


if __name__ == "__main__":
    main()
