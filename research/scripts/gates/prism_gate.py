"""Same-seed gate for the tool: the 16 core mqt.bench circuits (frozen qpy in marabbecca), paper
budget, grid + hex, seed 0, prism only. Expected values are the 2.5.2 numbers recorded on 2026-09-04
(paper_gate_2026-09-04.log, "new=" column) before the single-policy cut.

Usage: .venv/bin/python research/scripts/gates/prism_gate.py
"""

import math
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
HERE = Path(__file__).absolute().parent
sys.path.insert(0, str(HERE.parents[2] / "src"))

from qiskit import qpy  # noqa: E402
from qiskit.transpiler import CouplingMap  # noqa: E402

from prism.encodings import DualRail  # noqa: E402
from prism.lowering.commit_policies.prism_routing import PrismRouting  # noqa: E402
from prism.pipeline import build_pm  # noqa: E402

# The paper arm routed with whole-qubit dependencies; commutation-aware deps (2026-09-09) are
# a post-paper improvement, so the reproduction gate runs with them off.
PrismRouting.COMMUTE_DIAGONAL = False
# Early measurement (2026-09-10) rewrites the circuits themselves; off for the reproduction.
DualRail.early_measure = False
DualRail.reschedule = False

MARABBECCA = Path("/home/evm9/prism/worktrees/hpca-r2")
CORE = ["dj", "qaoa", "draper_qft_adder", "modular_adder", "qft", "qpeexact", "qpeinexact", "qftentangled",
        "bmw_quark_copula", "hhl", "ae", "cdkm_ripple_carry_adder", "full_adder", "vqe_two_local",
        "rg_qft_multiplier", "multiplier"]


def topologies(n_logical: int) -> dict[str, CouplingMap]:
    """The paper's sizing: 2*(n+1) rails, smallest grid / hex that holds them."""
    n_phys = 2 * (n_logical + 1)
    rows = math.ceil(math.sqrt(n_phys))
    side = math.ceil(math.sqrt(n_phys / 2))
    while CouplingMap.from_hexagonal_lattice(side, side).size() < n_phys:
        side += 1
    return {"grid": CouplingMap.from_grid(rows, math.ceil(n_phys / rows)),
            "hex_lattice": CouplingMap.from_hexagonal_lattice(side, side)}


def expected() -> dict[tuple[str, str], tuple[int, int, float]]:
    out = {}
    for line in (HERE / "paper_gate_2026-09-04.log").read_text().splitlines():
        m = re.match(r"(\S+)\s+(\S+)\s+s0 prism_retained_set\s+old=.*? new=\s*(\d+),\s*(\d+),\s*([\d.]+) ", line)
        if m:
            out[(m[1], m[2])] = (int(m[3]), int(m[4]), float(m[5]))
    return out


def main() -> None:
    exp = expected()
    bad = 0
    for name in CORE:
        with (MARABBECCA / "artifacts/hpca/manifests/circuits" / f"{name}_n8.qpy").open("rb") as f:
            qc = qpy.load(f)[0]
        for topo, cmap in topologies(8).items():
            pm = build_pm(cmap, enc=DualRail, seed=0)
            pm.run(qc)
            m = pm.property_set["circuit_metrics"]
            got = (m.swaps, m.depth, round(m.duration, 1))
            ok = got == exp[(name, topo)]
            bad += not ok
            print(f"{name:24} {topo:11} got={got} exp={exp[(name, topo)]} {'ok' if ok else 'MISMATCH'}", flush=True)
    print("MISMATCHES:", bad, "of", 2 * len(CORE))


if __name__ == "__main__":
    main()
