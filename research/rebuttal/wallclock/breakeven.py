"""Break-even transmon plane: re-simulate the saved transmon circuits over (CZ error, T1).

  .venv/bin/python research/rebuttal/wallclock/breakeven.py --width 8 --workers 4
  .venv/bin/python research/rebuttal/wallclock/breakeven.py --width 12 --shots 64 --workers 10

Uses `data/circuits_n<width>/*_bare_transmon.qpy` (grid and hex_lattice) from
`run.py`; nothing is recompiled. Each point sets the CZ average gate error r
(depolarizing p = 4r/3), single-qubit error r/10 (p = r/5), T1 and T2. The
grid and the rules are pre-registered in README.md ("Break-even transmon").
Rows are appended to `data/legacy/breakeven_n<width>.jsonl`; a rerun skips rows
already there. Trajectories use one seed per circuit at every point.
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import argparse
import dataclasses
import json
import sys
import zlib
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[2] / "src"), str(HERE)]

import sim  # noqa: E402

ERRORS = (1.25e-4, 2.5e-4, 5e-4, 1e-3, 2e-3, 4e-3)
T1S = (50.0, 100.0, 200.0, 400.0, 800.0, 1600.0)
POINTS = [(r, t1, t1) for t1 in T1S for r in ERRORS]
POINTS += [(r, 200.0, 200.0 * ratio) for ratio in (0.58, 2.0) for r in (5e-4, 1e-3, 2e-3)]


def device(r: float, t1: float, t2: float) -> sim.Device:
    p2, p1 = 4 * r / 3, r / 5
    return dataclasses.replace(
        sim.BARE_TRANSMON,
        name="plane",
        t1=t1,
        dephasing=1 / t2 - 1 / (2 * t1),
        depolarizing={"cz": p2, "sx": p1, "x": p1, "swap": 1 - (1 - p2) ** 3},
    )


def _one(task: tuple) -> dict:
    from qiskit import qpy

    path, (r, t1, t2), shots = task
    with path.open("rb") as f:
        qc = qpy.load(f)[0]
    topology = "grid" if "_grid_" in path.stem else "hex_lattice"
    circuit, rest = path.stem.split(f"_{topology}_")
    seed = int(rest.split("_", 1)[0])
    out = sim.simulate_bare(qc, device(r, t1, t2), shots=shots, seed=zlib.crc32(path.stem.encode()))
    return {"circuit": circuit, "topology": topology, "seed": seed, "r": r, "t1": t1, "t2": t2, "shots": shots} | out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--shots", type=int, default=None, help="trajectories per circuit; exact if omitted")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    paths = sorted(
        p for p in (HERE / f"data/circuits_n{args.width}").glob("*_bare_transmon.qpy")
        if "_grid_" in p.stem or "_hex_lattice_" in p.stem
    )
    out = HERE / f"data/legacy/breakeven_n{args.width}.jsonl"
    done = set()
    if out.exists():
        for line in out.open():
            row = json.loads(line)
            done.add((row["circuit"], row["topology"], row["seed"], row["r"], row["t1"], row["t2"]))

    def key(path, point):
        topology = "grid" if "_grid_" in path.stem else "hex_lattice"
        circuit, rest = path.stem.split(f"_{topology}_")
        return (circuit, topology, int(rest.split("_", 1)[0]), *point)

    tasks = [(p, point, args.shots) for p in paths for point in POINTS if key(p, point) not in done]
    print(f"{len(paths)} circuits x {len(POINTS)} points, {len(tasks)} to run", flush=True)
    with out.open("a") as f, ProcessPoolExecutor(args.workers) as pool:
        for i, future in enumerate(as_completed([pool.submit(_one, t) for t in tasks]), 1):
            f.write(json.dumps(future.result()) + "\n")
            f.flush()
            if i % 100 == 0:
                print(f"{i}/{len(tasks)}", flush=True)


if __name__ == "__main__":
    main()
