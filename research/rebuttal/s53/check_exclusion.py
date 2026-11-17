"""§5.1 exclusion rule on the current build: does the fixed-default-realization compiler insert routing SWAPs?

The rule (research/ablations/check_excluded_workloads.py): an MQT workload at eight logical qubits is kept if `trivial`,
which takes every default realization, inserts routing SWAPs. Checked on all three graphs for the nine excluded and the
16 kept workloads, seeds 0, 100, 200.

Usage: .venv/bin/python research/rebuttal/s53/check_exclusion.py  -> data/exclusion_check.jsonl
"""
import json
import sys
import tomllib
from pathlib import Path

from qiskit import qpy

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/paper"))
from paper_common import make_topologies  # noqa: E402
from marabbecca.encodings import DualRail  # noqa: E402
from marabbecca.staged_pms import build_pm  # noqa: E402

EXCLUDED = tomllib.loads((Path(__file__).parent / "excluded.toml").read_text())["circuits"]
KEPT = tomllib.loads((ROOT / "configs/paper/core.toml").read_text())["circuits"]
OUT = Path(__file__).parent / "data/exclusion_check.jsonl"
OUT.parent.mkdir(exist_ok=True)

topologies = make_topologies(8)
with OUT.open("w") as f:
    for group, names in (("excluded", EXCLUDED), ("kept", KEPT)):
        for name in names:
            with open(ROOT / f"artifacts/paper/manifests/circuits/{name}_n8.qpy", "rb") as q:
                circuit = qpy.load(q)[0]
            for topology in ("grid", "hex_lattice", "heavy_hex"):
                for seed in (0, 100, 200):
                    pm = build_pm(topologies[topology], enc=DualRail, strategy="trivial", seed=seed)
                    pm.run(circuit)
                    row = {"group": group, "circuit": name, "topology": topology, "seed": seed,
                           "router_inserted_swaps": int(pm.property_set["routing_swaps"])}
                    f.write(json.dumps(row) + "\n")
                    print(row, flush=True)
