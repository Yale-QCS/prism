"""Abstract imperfect-check sensitivity, not a calibrated SPAM protocol.

  .venv/bin/python research/rebuttal/wallclock/detection.py --widths 8 12 16

Reads `data/v2_n<width>.jsonl` and the saved circuits; nothing is re-simulated. Each live pair p
has expected losses lambda_p (`validate.pair_losses`; they sum to -ln P_keep). Every scenario
adds an exposure tau per pair for its preparation herald and terminal check, so the photon
survives with s_p = exp(-lambda_p - tau / T1). The check then flags

  - a lost photon with probability eta (detection efficiency);
  - a present photon with probability f (false positive).

A shot is kept if no pair is flagged, with probability prod_p a_p, a_p = (1 - f) s_p + (1 - eta)(1 - s_p).
A kept shot with an undetected loss is counted as wrong, so the kept-shot fidelity is the
simulated F times prod_p (1 - f) s_p / a_p. Dephasing during tau adds a phase flip with
probability (1 - exp(-2 gamma tau)) / 2 per pair, counted as an error.

For each scenario, width and topology this prints PRISM against Greedy:

  - the reduction in the rejection exponent -ln P_keep, the quantity the losses table reports
    when eta = 1, f = 0 and tau = 0;
  - baseline / PRISM shots and 1 - F over the workloads where Greedy keeps at least 1% of its
    shots with ideal checks (one fixed set per width and topology, so that a ratio change is
    the scenario's effect, not a change of workloads), and how many of them stay above 1%;
  - PRISM's geometric-mean P_keep and 1 - F over all workloads.

Ratios are geometric means over workloads of seed means, with a 95% interval from 1000 seed
resamples paired between the arms, as in `v2_report.py`.

Source audit (2026-10-08; see `README.md`):
  - eta 0.996: Mehta et al. Table 3, leakage detection error 3.5e-3 and 3.9e-3.
  - eta 0.99: Chou et al. (arXiv:2307.03169), over 99% of cavity decays detected.
  - eta 0.963: de Graaf et al. (arXiv:2406.14621), one mid-circuit check, false negative 3.7%.
  - eta 0.9: the floor prism-66 set.
  - f = 6.4% and 6.8% below are hypothetical. Mehta Table 3 reports total SPAM
    erasure assignment, which does not identify this conditional false-positive rate.
  - tau is assumed exposure, not a measured complete check duration. A check pulse
    alone does not include readout and reset.
  - Existing detection.txt/data/detection.json predate this source correction.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
from qiskit import qpy

import sim
import validate

HERE = Path(__file__).resolve().parent
TOPOLOGIES = ("grid", "hex_lattice")
VIABLE = 0.01
D = sim.MEHTA
SCENARIOS = [  # (label, eta, f, tau_us)
    ("ideal checks", 1.0, 0.0, 0.0),
    ("eta 0.996 (Mehta)", 0.996, 0.0, 0.0),
    ("eta 0.99 (Chou)", 0.99, 0.0, 0.0),
    ("eta 0.963 (de Graaf)", 0.963, 0.0, 0.0),
    ("eta 0.9", 0.9, 0.0, 0.0),
    ("hypothetical f 0.064", 1.0, 0.064, 0.0),
    ("hypothetical f 0.068", 1.0, 0.068, 0.0),
    ("tau 2 us", 1.0, 0.0, 2.0),
    ("tau 5 us", 1.0, 0.0, 5.0),
    ("tau 10 us", 1.0, 0.0, 10.0),
    ("hypothetical eta .996 f .066 tau 5", 0.996, 0.066, 5.0),
    ("hypothetical eta .9 f .068 tau 10", 0.9, 0.068, 10.0),
]

rng = np.random.default_rng(0)


def apply(losses, fidelity, eta, f, tau):
    """P_keep and kept-shot 1 - F of one row under imperfect checks and per-pair overhead tau."""
    s = np.exp(-np.asarray(losses) - tau / D.t1)
    a = (1 - f) * s + (1 - eta) * (1 - s)
    flip = (1 - math.exp(-2 * D.dephasing * tau)) / 2
    clean = np.prod((1 - f) * s / a) * (1 - flip) ** len(s)
    return float(np.prod(a)), 1 - fidelity * clean


def load(width):
    """(topology, arm, circuit) -> seed -> (pair losses, F)."""
    out = defaultdict(dict)
    for line in (HERE / "data" / f"v2_n{width}.jsonl").open():
        r = json.loads(line)
        if r["topology"] not in TOPOLOGIES:
            continue
        with (HERE / "data" / f"circuits_n{width}" / f"{r['circuit']}_{r['topology']}_{r['seed']}_{r['arm']}.qpy").open("rb") as f:
            losses = validate.pair_losses(qpy.load(f)[0], D)
        out[(r["topology"], r["arm"], r["circuit"])][r["seed"]] = (losses, r["fidelity"])
    return out


def ratio(value, a, b, circuits, seeds):
    """Geomean over circuits of seed-mean a / seed-mean b, with the paired seed 95% interval."""
    picks = np.vstack([np.arange(len(seeds))[None, :], rng.integers(0, len(seeds), (1000, len(seeds)))])
    x = {arm: np.array([[value[(arm, c)][s] for s in seeds] for c in circuits]) for arm in (a, b)}
    ln = np.log(x[a][:, picks].mean(axis=2)).mean(axis=0) - np.log(x[b][:, picks].mean(axis=2)).mean(axis=0)
    return math.exp(ln[0]), *np.exp(np.percentile(ln[1:], [2.5, 97.5]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--widths", type=int, nargs="+", default=[8, 12, 16])
    args = parser.parse_args()
    summary = {}
    print("PRISM against Greedy under imperfect erasure checks. Columns: rejection exponent -ln P_keep reduced [95%];"
          " viable workloads with ideal checks (how many stay viable); Greedy / PRISM shots and 1 - F on them [95%]; PRISM geomean P_keep and 1 - F")
    for w in args.widths:
        rows = load(w)
        seeds = sorted({s for per in rows.values() for s in per})
        for topology in TOPOLOGIES:
            circuits = sorted({c for (t, a, c) in rows if t == topology and a == "prism"})
            print(f"\nn = {w}, {topology}")
            viable = None
            for label, eta, f, tau in SCENARIOS:
                value = defaultdict(dict)  # quantity -> (arm, circuit) -> seed -> value
                for arm in ("prism", "greedy"):
                    for c in circuits:
                        for s in seeds:
                            losses, fidelity = rows[(topology, arm, c)][s]
                            keep, infidelity = apply(losses, fidelity, eta, f, tau)
                            value["exponent"].setdefault((arm, c), {})[s] = -math.log(keep)
                            value["shots"].setdefault((arm, c), {})[s] = 1 / keep
                            value["1 - F"].setdefault((arm, c), {})[s] = infidelity
                exponent = ratio(value["exponent"], "prism", "greedy", circuits, seeds)
                above = [c for c in circuits if 1 / np.mean(list(value["shots"][("greedy", c)].values())) >= VIABLE]
                viable = viable or above
                shots = ratio(value["shots"], "greedy", "prism", viable, seeds)
                infidelity = ratio(value["1 - F"], "greedy", "prism", viable, seeds)
                keep = math.exp(-np.mean([np.mean(list(value["exponent"][("prism", c)].values())) for c in circuits]))
                prism_infidelity = math.exp(np.mean([math.log(np.mean(list(value["1 - F"][("prism", c)].values()))) for c in circuits]))
                print(f"  {label:34s} {1 - exponent[0]:6.1%} [{1 - exponent[2]:5.1%}, {1 - exponent[1]:5.1%}]  {len(viable):2d} ({len(set(above) & set(viable)):2d})  "
                      f"shots {shots[0]:.3f} [{shots[1]:.3f}, {shots[2]:.3f}]  1-F {infidelity[0]:.3f} [{infidelity[1]:.3f}, {infidelity[2]:.3f}]  "
                      f"PRISM P_keep {keep:.3g}  1-F {prism_infidelity:.4f}")
                summary[f"n{w}/{topology}/{label}"] = {
                    "exponent_reduction": (1 - exponent[0], 1 - exponent[2], 1 - exponent[1]),
                    "viable": len(viable), "still_above_1pct": len(set(above) & set(viable)), "shots": shots, "1 - F": infidelity,
                    "prism_keep": keep, "prism_infidelity": prism_infidelity,
                }
    (HERE / "data" / "detection.json").write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
