"""H1 sensitivity sweep: re-simulate the saved n=8 dual-rail circuits under one-at-a-time device variants.

  .venv/bin/python research/rebuttal/wallclock/sweep.py --workers 2
  .venv/bin/python research/rebuttal/wallclock/sweep.py --device mehta --workers 10

Uses `data/circuits_n8/*_{logical,greedy,prism,bare_transmon}.qpy` (grid and hex_lattice)
from `run.py`; nothing is recompiled. Durations follow the variant, so slower
beamsplitters lengthen the schedule. The bare transmon circuits are re-simulated at
a stronger device point. Rows in `data/legacy/sweep_n8.jsonl`.
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

BEAMSPLITTER = ("rswap", "swap", "x", "rx")
D = sim.LEGACY


def _scaled(mapping: dict, names, factor: float) -> dict:
    return {k: (tuple(p * factor for p in v) if isinstance(v, tuple) else v * factor) if k in names else v for k, v in mapping.items()}


VARIANTS = [("default", 1.0, D)]
VARIANTS += [("t1_us", t, dataclasses.replace(D, t1=t)) for t in (100.0, 231.0, 652.0, 1000.0, 2000.0)]
VARIANTS += [("crz_coupler_loss", g, dataclasses.replace(D, loss={"crz": g})) for g in (1e-3, 2e-3, 5e-3)]
VARIANTS += [("beamsplitter_time_x", f, dataclasses.replace(D, durations=_scaled(D.durations, BEAMSPLITTER, f))) for f in (0.5, 2.0, 4.0)]
VARIANTS += [("beamsplitter_error_x", f, dataclasses.replace(D, pauli_z=_scaled(D.pauli_z, BEAMSPLITTER, f))) for f in (3.0, 10.0)]
VARIANTS += [("crz_error_x", f, dataclasses.replace(D, pauli_z=_scaled(D.pauli_z, ("crz",), f))) for f in (0.3, 3.0)]
VARIANTS += [("dephasing_x", f, dataclasses.replace(D, dephasing=D.dephasing * f)) for f in (0.3, 3.0)]

BARE_VARIANTS = [("default", 1.0, sim.BARE_TRANSMON), ("strong_transmon", 1.0, sim.STRONG_TRANSMON)]

# Around the MEHTA point (prism-66's ranges, 2026-10-07). T1: Table 2's extremes plus 100 and 2000 us.
# Dephasing: the logical coherence time T (ms) read from Ramsey (1.5, 3.1) or echo (4.0, 4.8);
# a per-rail rate gamma gives T = 1 / (2 gamma). Erasure scales every operation's erasure.
M = sim.MEHTA
MEHTA_VARIANTS = [("default", 1.0, M)]
MEHTA_VARIANTS += [("t1_us", t, dataclasses.replace(M, t1=t)) for t in (100.0, 231.0, 652.0, 2000.0)]
MEHTA_VARIANTS += [("erasure_x", f, dataclasses.replace(M, erasure=_scaled(M.erasure, M.erasure, f))) for f in (0.5, 2.0)]
MEHTA_VARIANTS += [("residual_x", f, dataclasses.replace(M, pauli_z=_scaled(M.pauli_z, M.pauli_z, f))) for f in (0.3, 3.0)]
MEHTA_VARIANTS += [("coherence_ms", t, dataclasses.replace(M, dephasing=1 / (2 * t * 1000))) for t in (1.5, 3.1, 4.0, 4.8)]
MEHTA_VARIANTS += [("beamsplitter_time_x", f, dataclasses.replace(M, durations=_scaled(M.durations, BEAMSPLITTER, f))) for f in (0.5, 2.0)]


def _one(task: tuple) -> list[dict]:
    from qiskit import qpy

    path, variants = task

    with path.open("rb") as f:
        qc = qpy.load(f)[0]
    circuit, rest = path.stem.split("_grid_") if "_grid_" in path.stem else path.stem.split("_hex_lattice_")
    topology = "grid" if "_grid_" in path.stem else "hex_lattice"
    seed, arm = rest.split("_", 1)
    if arm == "bare_transmon":
        return [
            {"circuit": circuit, "topology": topology, "seed": int(seed), "arm": arm, "variant": name, "value": value}
            | sim.simulate_bare(qc, device)
            for name, value, device in BARE_VARIANTS
        ]
    return [
        {"circuit": circuit, "topology": topology, "seed": int(seed), "arm": arm, "variant": name, "value": value}
        | sim.simulate_dualrail(qc, device)
        for name, value, device in variants
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--device", choices=("legacy", "mehta"), default="legacy", help="mehta: dual-rail arms only, rows in v2_sweep_n8.jsonl")
    args = parser.parse_args()
    mehta = args.device == "mehta"
    paths = sorted(
        p for p in (HERE / "data/circuits_n8").glob("*.qpy")
        if ((p.stem.endswith("_bare_transmon") and not mehta) or p.stem.rsplit("_", 1)[-1] in ("logical", "greedy", "prism"))
        and ("_grid_" in p.stem or "_hex_lattice_" in p.stem)
    )
    variants = MEHTA_VARIANTS if mehta else VARIANTS
    with (HERE / "data" / ("v2_sweep_n8.jsonl" if mehta else "legacy/sweep_n8.jsonl")).open("w") as f, ProcessPoolExecutor(args.workers) as pool:
        for rows in pool.map(_one, [(p, variants) for p in paths]):
            for row in rows:
                f.write(json.dumps(row) + "\n")
    print(f"{len(paths)} circuits x {len(variants)} variants")


if __name__ == "__main__":
    main()
