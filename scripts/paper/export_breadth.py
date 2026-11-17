"""Export the breadth experiment: PRISM vs Greedy per QASMBench circuit and topology."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from export_core import _write_csv
from paper_common import bootstrap_interval

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "artifacts/paper/raw/breadth.jsonl"
OUT = ROOT / "artifacts/paper/paper_export/breadth"
TOPOLOGIES = ("grid", "hex_lattice", "heavy_hex")
METRICS = ("router_inserted_swaps", "physical_depth", "duration_ns")


def main() -> None:
    global RAW, OUT  # noqa: PLW0603

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--quick", action="store_true", help="export the quick-profile rows"
    )
    if parser.parse_args().quick:
        RAW = ROOT / "artifacts/paper/quick/breadth.jsonl"
        OUT = ROOT / "artifacts/paper/quick_export/breadth"
    OUT.mkdir(parents=True, exist_ok=True)

    cells: dict = defaultdict(dict)
    widths = {}
    for row in map(json.loads, RAW.open()):
        if not row["success"]:
            raise RuntimeError(f"failed breadth row: {row['run_id']}")
        key = (row["circuit_name"], row["topology_name"])
        cells[key][(row["outer_seed"], row["strategy"])] = row
        widths[row["circuit_name"]] = row["actual_n_logical"]
    circuits = sorted(widths, key=lambda c: (widths[c], c))

    out = []
    for circuit in circuits:
        for topology in TOPOLOGIES:
            runs = cells[(circuit, topology)]
            seeds = sorted({seed for seed, _ in runs})
            entry = {
                "circuit": circuit,
                "n_logical": widths[circuit],
                "topology": topology,
                "seeds": len(seeds),
            }
            for metric in METRICS:
                greedy = np.array([[runs[(s, "greedy")][metric] for s in seeds]], float)
                prism = np.array([[runs[(s, "prism")][metric] for s in seeds]], float)
                low, high = (
                    bootstrap_interval(greedy, prism)
                    if len(seeds) > 1
                    else (np.nan, np.nan)
                )
                entry[f"greedy_{metric}"] = greedy.mean()
                entry[f"prism_{metric}"] = prism.mean()
                entry[f"reduction_{metric}"] = 1.0 - prism.sum() / greedy.sum()
                entry[f"low_{metric}"], entry[f"high_{metric}"] = low, high
            entry["prism_more_swap_runs"] = int(
                sum(
                    runs[(s, "prism")]["router_inserted_swaps"]
                    > runs[(s, "greedy")]["router_inserted_swaps"]
                    for s in seeds
                )
            )
            out.append(entry)
    _write_csv(OUT / "per_circuit.csv", out)

    # LaTeX table body: one row per circuit, routing-SWAP reduction [95% interval] per topology.
    def cell(entry: dict) -> str:
        r, lo, hi = (
            100 * entry[f"{k}_router_inserted_swaps"]
            for k in ("reduction", "low", "high")
        )
        return f"{r:.1f}" if np.isnan(lo) else f"{r:.1f} [{lo:.1f}, {hi:.1f}]"

    by_key = {(e["circuit"], e["topology"]): e for e in out}
    lines = [
        f"{circuit} & {widths[circuit]} & "
        + " & ".join(cell(by_key[(circuit, t)]) for t in TOPOLOGIES)
        + r" \\"
        for circuit in circuits
    ]
    (OUT / "breadth_table.tex").write_text("\n".join(lines) + "\n")
    print(
        json.dumps(
            {
                "rows": sum(len(v) for v in cells.values()),
                "circuits": circuits,
                "output": str(OUT),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
