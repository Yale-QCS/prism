"""H1 table: does PRISM's advantage over Greedy depend on the device parameters?

  python3 research/rebuttal/wallclock/sweep_table.py

Reads `data/legacy/sweep_n8.jsonl` (n = 8, grid and hex_lattice, five seeds). For each
one-at-a-time variant it prints PRISM/Greedy ratios of shot overhead (1/P_keep)
and of conditional infidelity (1 - F), as geometric means over workloads of
per-workload means over seeds and topologies, and PRISM's absolute P_keep.

Detection efficiency eta and the false-positive rate e are applied to the
default rows afterwards. Each of the n pairs survives with s = P_keep^(1/n)
(uniform exposure, an approximation); a missed loss is kept and has zero overlap
with the ideal state, and a false positive discards a good shot:
  kept = prod_i (s + (1 - eta)(1 - s)) * (1 - e)^n,   F_kept = F * P_keep * (1 - e)^n / kept.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
N = 8


def gmean(values):
    return math.exp(sum(math.log(v) for v in values) / len(values))


rows = defaultdict(lambda: defaultdict(list))  # (variant, value) -> (circuit, arm) -> rows
for line in (HERE / "data/legacy/sweep_n8.jsonl").open():
    r = json.loads(line)
    if r["arm"] in ("greedy", "prism"):
        rows[(r["variant"], r["value"])][(r["circuit"], r["arm"])].append(r)


def table(key_rows, transform=lambda r: (r["p_keep"], r["fidelity"])):
    """Return (overhead ratio, infidelity ratio, PRISM P_keep), each a geometric mean over workloads."""
    circuits = sorted({c for c, _ in key_rows})
    circuits = [c for c in circuits if len(key_rows[(c, "greedy")]) == len(key_rows[(c, "prism")]) > 0]
    mean = {(c, a): [sum(v) / len(v) for v in zip(*(transform(r) for r in key_rows[(c, a)]))] for c in circuits for a in ("greedy", "prism")}
    overhead = gmean([mean[(c, "greedy")][0] / mean[(c, "prism")][0] for c in circuits])
    infidelity = gmean([(1 - mean[(c, "prism")][1]) / (1 - mean[(c, "greedy")][1]) for c in circuits])
    return overhead, infidelity, gmean([mean[(c, "prism")][0] for c in circuits]), len(circuits)


print(f"{'parameter':24s} {'value':>8s} {'overhead P/G':>13s} {'infid. P/G':>11s} {'PRISM P_keep':>13s} {'workloads':>10s}")
for (variant, value), key_rows in sorted(rows.items(), key=lambda kv: (kv[0][0] != "default", kv[0])):
    o, i, k, n = table(key_rows)
    print(f"{variant:24s} {value:8g} {o:13.3f} {i:11.3f} {k:13.3f} {n:10d}")

default = rows[("default", 1.0)]
for eta, e in ((0.999, 0.0), (0.99, 0.0), (1.0, 0.005), (1.0, 0.01), (0.99, 0.005)):
    def detect(r, eta=eta, e=e):
        s = r["p_keep"] ** (1 / N)
        kept = (s + (1 - eta) * (1 - s)) ** N * (1 - e) ** N
        return kept, r["fidelity"] * r["p_keep"] * (1 - e) ** N / kept
    o, i, k, n = table(default, detect)
    print(f"{'detection eta, e_fp':24s} {f'{eta:g},{e:g}':>8s} {o:13.3f} {i:11.3f} {k:13.3f} {n:10d}")
