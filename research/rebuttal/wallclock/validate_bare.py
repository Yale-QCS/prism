"""Check the transmon fidelity model of `bare.py` against `sim.simulate_bare`.

  .venv/bin/python research/rebuttal/wallclock/validate_bare.py --width 8 --workers 2

For every core workload on the grid at seed 0 (best of one transpiler pair), it compares the model's
program-qubit fidelity with the simulator's at five transmon points: the central point at CZ errors
1e-3, 3e-3 and 1e-2, the all-best corner, and the low-T1 point with high readout error. The simulator is
the exact density matrix at n <= 8 and `--shots` trajectories above. Output: one line per circuit and point,
the calibration constant c of ln F = ln F_model + c (ln F_model)^2 (weighted least squares, the form
the historical crossover report applied per width), then the median and extreme of ln F_model - ln F_sim. Rows in
`data/validate_bare_n<width>.jsonl`.
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import argparse
import dataclasses
import json
import math
from concurrent.futures import ProcessPoolExecutor

import numpy as np

import bare
import sim

POINTS = {
    "central cz 1e-3": dataclasses.replace(bare.CENTRAL, cz=1e-3),
    "central cz 3e-3": bare.CENTRAL,
    "central cz 1e-2": dataclasses.replace(bare.CENTRAL, cz=1e-2),
    "best corner": bare.VARIANTS["best"],
    "t1 68, readout 1.63e-2": dataclasses.replace(bare.CENTRAL, t1=68.0, readout=1.63e-2),
}


def _one(task: tuple) -> list[dict]:
    from qiskit import qpy

    from paper_common import make_topologies

    circuit, width, shots, points = task
    with (bare.REPO / f"artifacts/paper/manifests/circuits/{circuit}_n{width}.qpy").open("rb") as f:
        qc = qpy.load(f)[0].remove_final_measurements(inplace=False)
    _, _, c, logical = bare.compile_cell(qc, make_topologies(width)["grid"], 0, 1)["best1"]
    fp = bare.fingerprint(c, logical)
    out = []
    for label in points:
        t = POINTS[label]
        r = sim.simulate_bare(c, t.device(), shots=shots, seed=1, logical=logical, readout=t.readout)
        out.append({"circuit": circuit, "width": width, "point": label, "n_active": fp["n_active"],
                    "model": math.exp(bare.log_fidelity(fp, t)), "sim": r["fidelity"], "sim_se": r["fidelity_se"]})
    return out


def calibration(rows: list[dict]) -> tuple[float, float]:
    """Weighted least-squares c in ln F_sim - ln F_model = c (ln F_model)^2, and its standard error."""
    m = np.log([r["model"] for r in rows])
    d = np.log([r["sim"] for r in rows]) - m
    se = np.maximum([r["sim_se"] / r["sim"] for r in rows], 1e-3)
    x, wt = m**2, 1 / se**2
    c = (wt * x * d).sum() / (wt * x * x).sum()
    return float(c), float(1 / math.sqrt((wt * x * x).sum()))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--shots", type=int, default=None)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--circuits", nargs="+", default=bare.run.CFG["circuits"])
    parser.add_argument("--points", nargs="+", default=list(POINTS), help="labels in POINTS")
    args = parser.parse_args()
    circuits = [c for c in args.circuits if (bare.REPO / f"artifacts/paper/manifests/circuits/{c}_n{args.width}.qpy").exists()]
    rows = []
    with ProcessPoolExecutor(args.workers) as pool:
        for part in pool.map(_one, [(c, args.width, args.shots, args.points) for c in circuits]):
            for r in part:
                print(f"{r['circuit']:24s} {r['point']:24s} active {r['n_active']:2d}  model {r['model']:.4f}  sim {r['sim']:.4f} ± {r['sim_se']:.4f}", flush=True)
            rows += part
    (bare.HERE / "data" / f"validate_bare_n{args.width}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"calibration c (ln F_sim = ln F_model + c ln F_model^2, weighted): {calibration(rows)[0]:.4f} ± {calibration(rows)[1]:.4f}")
    for label in args.points:
        d = np.array([math.log(r["model"]) - math.log(r["sim"]) for r in rows if r["point"] == label])
        rel = np.array([math.log(r["model"]) / math.log(r["sim"]) - 1 for r in rows if r["point"] == label and r["sim"] < 0.999])
        print(f"{label:24s} ln F_model - ln F_sim: median {np.median(d):+.4f}, min {d.min():+.4f}, max {d.max():+.4f};"
              f" relative error of ln F: median {np.median(rel):+.3f}, range [{rel.min():+.3f}, {rel.max():+.3f}]")


if __name__ == "__main__":
    main()
