"""Routing-stage (lowering) wall time per arm against n, single process, for the R6 before/after comparison.

Usage: .venv/bin/python research/rebuttal/time_aware/route_timing.py <label>
Appends rows to data/route_timing.jsonl. Run once before and once after the kernel change, on a quiet machine.
"""

import json
import sys
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/paper"))
import run_fairness as rf  # noqa: E402
from qiskit import qpy  # noqa: E402
from qiskit.transpiler import PassManager  # noqa: E402

CIRCUITS = ("qft", "multiplier", "qaoa", "draper_qft_adder")
WIDTHS = (8, 16, 24)
label = sys.argv[1]
cfg = tomllib.loads((ROOT / "configs/paper/core.toml").read_text())
out = Path(__file__).parent / "data/route_timing.jsonl"
out.parent.mkdir(exist_ok=True)
with out.open("a") as f:
    for width in WIDTHS:
        for circuit in CIRCUITS:
            path = ROOT / f"artifacts/paper/manifests/circuits/{circuit}_n{width}.qpy"
            if not path.exists():
                continue
            with path.open("rb") as fh:
                qc = qpy.load(fh)[0]
            cmap = rf.make_topologies(width)["grid"]
            for arm in ("greedy", "prism"):
                pm = rf._build_arm_pm(rf._arm_spec_for_config(cfg, arm), cmap, 0, cfg["objective"])
                pm.physical = PassManager([])
                t0 = time.perf_counter()
                pm.run(qc)
                row = {"label": label, "circuit": circuit, "n": width, "arm": arm,
                       "lowering_s": time.perf_counter() - t0, "routing_swaps": pm.property_set["routing_swaps"],
                       "choices": pm.property_set.get("realization_choices")}
                f.write(json.dumps(row) + "\n")
                f.flush()
                print(label, circuit, width, arm, round(row["lowering_s"], 1), row["routing_swaps"], flush=True)
