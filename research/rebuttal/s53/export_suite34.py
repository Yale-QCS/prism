"""Option (b), s53/README.md §5: the suite export over 34 workloads (the 25 plus the nine excluded MQT workloads).

Runs scripts/paper/export_suite.py unchanged. Its row files are linked into a temporary directory, with the nine's
Greedy/PRISM and Logical-SABRE rows added and MQT `bv` (eight logical qubits) renamed `bv_n8`, so that it does not
merge with QASMBench `bv`. Then the error objective (−log F_cond, equal weight) is computed for 25 and 34 workloads.

Usage: .venv/bin/python research/rebuttal/s53/export_suite34.py  -> artifacts/paper/paper_export/suite34/
"""
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/paper"))
import export_suite  # noqa: E402
from marabbecca.utils.metrics import device_success  # noqa: E402

RAW = ROOT / "artifacts/paper/raw"
OUT = ROOT / "artifacts/paper/paper_export/suite34"


def renamed(src: Path, dst: Path) -> None:
    with dst.open("w") as f:
        for row in map(json.loads, src.open()):
            if row["circuit_name"] == "bv":
                row["circuit_name"] = "bv_n8"
            f.write(json.dumps(row) + "\n")


def error_objective(raw: Path, sources: list) -> dict:
    """Equal-weight reduction of −log F_cond of the selected route, and cells lower, per graph."""
    cell: dict = {}
    for name in sources:
        for r in map(json.loads, (raw / name).open()):
            if r["strategy"] in ("greedy", "prism") and r["duration_ns"] is not None:  # classically controlled: no duration
                _, f = device_success(r["actual_n_logical"], r["duration_ns"], r["program_body_op_counts"])
                cell.setdefault((r["circuit_name"], r["topology_name"]), {}).setdefault(r["strategy"], []).append(-np.log(f))
    out = {}
    for t in export_suite.TOPOLOGIES:
        pairs = [(np.mean(v["greedy"]), np.mean(v["prism"])) for (w, tt), v in cell.items() if tt == t]
        out[t] = {"workloads": len(pairs), "equal_weight": float(np.mean([1 - p / g for g, p in pairs])),
                  "lower": int(sum(p < g for g, p in pairs))}
    return out


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    for name in ("core.jsonl", "breadth.jsonl", "logical.jsonl", "logical_qasmbench.jsonl", "randomcircuit.jsonl"):
        (tmp / name).symlink_to(RAW / name)
    renamed(RAW / "s53_excluded.jsonl", tmp / "excluded.jsonl")
    renamed(RAW / "s53_excluded_logical.jsonl", tmp / "logical_excluded.jsonl")
    export_suite.RAW, export_suite.OUT = tmp, OUT
    export_suite.SOURCES = {"core.jsonl": "mqt", "excluded.jsonl": "mqt", "breadth.jsonl": "qasmbench"}
    export_suite.LOGICAL = (*export_suite.LOGICAL, "logical_excluded.jsonl")
    # Fig. 9 cannot draw an undefined reduction (Greedy mean 0), and the table does not need it.
    export_suite._render_per_benchmark_by_topology = lambda *a, **k: None
    export_suite.main()
    summary = json.loads((OUT / "summary.json").read_text())
    summary["error_objective"] = {"25": error_objective(RAW, ["core.jsonl", "breadth.jsonl"]),
                                  "34": error_objective(tmp, ["core.jsonl", "excluded.jsonl", "breadth.jsonl"])}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))
