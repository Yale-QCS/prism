"""R4 matrix (pre-registered reading in README.md): totals per arm and config, each arm against its own off row.

Usage: .venv/bin/python research/rebuttal/time_aware/matrix.py
Reads the quick rows (off = the default quick core and breadth rows; the others = ta_* experiments).
"""

import json
import math
from collections import defaultdict
from pathlib import Path

from marabbecca.utils.metrics import device_success

QUICK = Path(__file__).resolve().parents[3] / "artifacts/paper/quick"
CONFIGS = {
    "off": ("core.jsonl", "breadth.jsonl"),
    "swap": ("ta_core_swap.jsonl", "ta_breadth_swap.jsonl"),
    "both": ("ta_core_both.jsonl", "ta_breadth_both.jsonl"),
    "both_half": ("ta_core_both_half.jsonl", "ta_breadth_both_half.jsonl"),
    "both_double": ("ta_core_both_double.jsonl", "ta_breadth_both_double.jsonl"),
    "lexicographic": ("ta_core_lex.jsonl", "ta_breadth_lex.jsonl"),
}
METRICS = ("swaps", "depth", "duration_us", "neg_log_f")


def rows(path, keep):
    if not (QUICK / path).exists():
        return {}
    return {(r["circuit_name"], r["topology_name"], r["outer_seed"], r["strategy"]): r
            for r in map(json.loads, open(QUICK / path)) if keep(r) and r["strategy"] in ("greedy", "prism")}


def totals(table, keys):
    out = defaultdict(lambda: defaultdict(float))
    n = defaultdict(int)
    for k in keys:
        r = table[k]
        _, f = device_success(r["actual_n_logical"], r["duration_ns"], r["final_op_counts"])
        t = out[r["strategy"]]
        t["swaps"] += r["router_inserted_swaps"]
        t["depth"] += r["physical_depth"]
        t["duration_us"] += r["duration_ns"] / 1e3
        t["neg_log_f"] += -math.log(f)
        n[r["strategy"]] += 1
    return out, n


def main():
    report = {}
    for suite, idx, keep in (("core", 0, lambda r: True), ("gcm_h6", 1, lambda r: r["circuit_name"] == "gcm_h6")):
        off = rows(CONFIGS["off"][idx], keep)
        print(f"\n{suite}")
        for name, files in CONFIGS.items():
            table = rows(files[idx], keep)
            keys = table.keys() & off.keys()  # matched runs only, so a partial file compares fairly
            if not keys:
                print(f"  {name:12s} missing")
                continue
            base, _ = totals(off, keys)
            t, n = totals(table, keys)
            row = {}
            for arm in ("greedy", "prism"):
                row[arm] = {m: t[arm][m] for m in METRICS} | {"runs": n[arm]}
                row[arm]["vs_off_%"] = {m: 100 * (t[arm][m] / base[arm][m] - 1) for m in METRICS}
            row["prism_edge_%"] = {m: 100 * (1 - t["prism"][m] / t["greedy"][m]) for m in METRICS}
            report[f"{suite}/{name}"] = row
            fmt = lambda d: " ".join(f"{m} {d[m]:+6.1f}" for m in METRICS)
            print(f"  {name:12s} greedy vs off: {fmt(row['greedy']['vs_off_%'])}")
            print(f"  {'':12s} prism  vs off: {fmt(row['prism']['vs_off_%'])}")
            edge = row["prism_edge_%"]
            print(f"  {'':12s} PRISM edge:    {fmt(edge)}")
    (Path(__file__).parent / "data/matrix.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
