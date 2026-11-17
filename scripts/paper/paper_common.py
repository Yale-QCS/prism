"""Shared pieces of the evaluation pipeline: topologies, run IDs and seed intervals."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
from qiskit.transpiler import CouplingMap

CODE_REPO = Path(__file__).resolve().parents[2]

#: Physical-capacity policy: topologies are sized for 2*(n+1) rails so kg-ancilla
#: circuits (grover, qwalk) and one spare pair fit.
SPARE_PAIRS = 1


def make_topologies(n_logical: int) -> dict[str, CouplingMap]:
    """Deterministic named topologies sized for ``2*(n_logical + SPARE_PAIRS)`` rails.

    ``grid_25`` and ``grid_36`` are fixed 5x5 and 6x6 grids for the
    device-slack ablation (56% and 125% spare sites at n = 8).
    """
    n_phys = 2 * (n_logical + SPARE_PAIRS)
    grid_rows = math.ceil(math.sqrt(n_phys))
    grid_cols = math.ceil(n_phys / grid_rows)
    hh_d = 3
    while CouplingMap.from_heavy_hex(hh_d).size() < n_phys:
        hh_d += 2
    hex_side = math.ceil(math.sqrt(n_phys / 2))
    while CouplingMap.from_hexagonal_lattice(hex_side, hex_side).size() < n_phys:
        hex_side += 1
    return {
        "chain": CouplingMap.from_line(n_phys),
        "grid": CouplingMap.from_grid(grid_rows, grid_cols),
        "heavy_hex": CouplingMap.from_heavy_hex(hh_d),
        "hex_lattice": CouplingMap.from_hexagonal_lattice(hex_side, hex_side),
        "grid_25": CouplingMap.from_grid(5, 5),
        "grid_36": CouplingMap.from_grid(6, 6),
    }


def run_id(experiment_id: str, **cell) -> str:
    """Deterministic run identifier from the cell coordinates."""
    payload = json.dumps({"experiment_id": experiment_id, **cell}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


BOOTSTRAP_SAMPLES = 2000


def bootstrap_interval(greedy: np.ndarray, prism: np.ndarray) -> tuple[float, float]:
    """95% interval of ``1 - sum(prism) / sum(greedy)`` over (workload, seed) arrays, resampling seeds in pairs."""
    picks = np.random.default_rng(0).integers(
        0, greedy.shape[-1], (BOOTSTRAP_SAMPLES, greedy.shape[-1])
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        samples = 1.0 - prism[..., picks].sum(axis=(0, -1)) / greedy[..., picks].sum(
            axis=(0, -1)
        )
    low, high = np.nanpercentile(samples, [2.5, 97.5])
    return float(low), float(high)
