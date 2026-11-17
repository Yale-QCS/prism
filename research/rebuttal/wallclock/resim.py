"""Re-simulate the saved dual-rail circuits on the MEHTA or MEHTA_IDLE device, or on LEGACY with SWS coupler loss.

  .venv/bin/python research/rebuttal/wallclock/resim.py --width 8 --device mehta_idle --workers 4
  .venv/bin/python research/rebuttal/wallclock/resim.py --width 12 --device mehta --shots 1000 --workers 10
  .venv/bin/python research/rebuttal/wallclock/resim.py --width 12 --loss 2e-3 --shots 1000 --workers 2

MEHTA: dual-rail arms only, rows in `v2_n<width>.jsonl`, each with its device name.
MEHTA_IDLE (background dephasing only while a pair idles): the same rows in `v3_n<width>.jsonl`.
LEGACY: the SWS moves the control-rail photon into the transmon coupler for part of the
gate, and a photon lost there is flagged like any other loss. The bare-transmon
rows are copied from `rows_n<width>.jsonl`; bare-cavity rows there are dropped.
Rows in `rows_n<width>_loss<loss>.jsonl`.
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import argparse
import dataclasses
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[2] / "src"), str(HERE)]

import sim  # noqa: E402


def qc_load(path: Path):
    from qiskit import qpy

    with path.open("rb") as f:
        return qpy.load(f)[0]


def _one(task: tuple) -> dict:
    from qiskit import qpy

    row, path, loss, shots = task
    if loss is None:
        device = {"mehta": sim.MEHTA, "mehta_idle": sim.MEHTA_IDLE}[row.pop("device")]
        return row | sim.simulate_dualrail(qc_load(path), device, shots=shots, seed=row["seed"]) | {"shots": shots}
    with path.open("rb") as f:
        qc = qpy.load(f)[0]
    if row["arm"] == "bare_transmon":
        return row | sim.simulate_bare(qc, sim.STRONG_TRANSMON, shots=shots, seed=row["seed"]) | {"device": sim.STRONG_TRANSMON.name}
    result = sim.simulate_dualrail(qc, dataclasses.replace(sim.LEGACY, loss={"crz": loss}), shots=shots, seed=row["seed"])
    return row | result | {"coupler_loss": loss}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--device", choices=("legacy", "mehta", "mehta_idle"), default="legacy")
    parser.add_argument("--loss", type=float, default=0.0, help="LEGACY coupler loss per CR_z")
    parser.add_argument("--shots", type=int, default=None)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--data-dir", type=Path, default=HERE / "data", help="holds legacy/rows_n<width>.jsonl and circuits_n<width>/; rows are written here")
    parser.add_argument("--strong-transmon", action="store_true", help="re-simulate only the transmon rows at the strong point")
    args = parser.parse_args()
    if args.strong_transmon:
        rows = [json.loads(line) for line in (args.data_dir / "legacy" / f"rows_n{args.width}.jsonl").open()]
        saved = args.data_dir / f"circuits_n{args.width}"
        tasks = [(r, saved / f"{r['circuit']}_{r['topology']}_{r['seed']}_bare_transmon.qpy", 0.0, args.shots) for r in rows if r["arm"] == "bare_transmon" and r["topology"] in ("grid", "hex_lattice")]
        with (args.data_dir / "legacy" / f"rows_n{args.width}_strong_transmon.jsonl").open("w") as f, ProcessPoolExecutor(args.workers) as pool:
            for row in pool.map(_one, tasks):
                f.write(json.dumps(row) + "\n")
        print(f"{len(tasks)} transmon circuits re-simulated at the strong point")
        return
    rows = [json.loads(line) for line in (args.data_dir / "legacy" / f"rows_n{args.width}.jsonl").open()]
    rows = [r for r in rows if r["topology"] in ("grid", "hex_lattice")]
    saved = args.data_dir / f"circuits_n{args.width}"
    if args.device != "legacy":
        keep = ("circuit", "n_logical", "topology", "seed", "arm", "op_counts")
        tasks = [({k: r[k] for k in keep} | {"device": args.device}, saved / f"{r['circuit']}_{r['topology']}_{r['seed']}_{r['arm']}.qpy", None, args.shots)
                 for r in rows if r["arm"] in ("logical", "greedy", "prism")]
        version = {"mehta": "v2", "mehta_idle": "v3"}[args.device]
        with (args.data_dir / f"{version}_n{args.width}.jsonl").open("w") as f, ProcessPoolExecutor(args.workers) as pool:
            for i, row in enumerate(pool.map(_one, tasks), 1):
                f.write(json.dumps(row) + "\n")
                f.flush()
                print(f"{i}/{len(tasks)}", flush=True)
        print(f"{len(tasks)} circuits re-simulated on {args.device}")
        return
    tasks = [
        (r, saved / f"{r['circuit']}_{r['topology']}_{r['seed']}_{r['arm']}.qpy", args.loss, args.shots)
        for r in rows
        if r["arm"] in ("logical", "greedy", "prism")
    ]
    with (args.data_dir / "legacy" / f"rows_n{args.width}_loss{args.loss:g}.jsonl").open("w") as f, ProcessPoolExecutor(args.workers) as pool:
        for row in rows:
            if row["arm"] == "bare_transmon":
                f.write(json.dumps(row | {"coupler_loss": 0.0}) + "\n")
        for row in pool.map(_one, tasks):
            f.write(json.dumps(row) + "\n")
    print(f"{len(tasks)} circuits re-simulated at coupler loss {args.loss:g}")


if __name__ == "__main__":
    main()
