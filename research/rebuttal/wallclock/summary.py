"""Print fidelity and wall-clock per kept shot for dual-rail (Greedy, PRISM) against the bare devices.

  python3 research/rebuttal/wallclock/summary.py [--width 8] [--overhead 0 2 10]

Wall-clock per kept shot is (duration + per-shot overhead) / P_keep; the
overhead stands for readout and reset and is the same on every device.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARMS = ("logical", "greedy", "prism", "bare_transmon")


def _gmean(values: list[float]) -> float:
    return math.exp(sum(map(math.log, values)) / len(values))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--width", type=int, default=8)
    parser.add_argument("--overhead", type=float, nargs="+", default=[0.0, 2.0, 10.0])
    args = parser.parse_args()
    rows = [json.loads(line) for line in (HERE / "data/legacy" / f"rows_n{args.width}.jsonl").open()]
    cells: dict[tuple, dict] = defaultdict(dict)
    for r in rows:
        cells[(r["circuit"], r["topology"], r["seed"])][r["arm"]] = r
    by_topology = sorted({key[1] for key in cells})
    for topology in [*by_topology, "all"]:
        chosen = {k: v for k, v in cells.items() if topology in ("all", k[1])}
        by_workload: dict[str, list[dict]] = defaultdict(list)
        for (circuit, _, _), arms in chosen.items():
            by_workload[circuit].append(arms)
        print(f"\n== {topology}: {len(chosen)} cells; per-workload means over seeds")
        print(f"{'workload':24s}" + "".join(f"{a + ' F':>16s}" for a in ARMS) + f"{'prism keep':>12s}"
              + "".join(f"{'T/T_tr o=' + format(o, 'g'):>14s}" for o in args.overhead))
        ratios: dict[float, list[float]] = defaultdict(list)
        infidelity_gain: list[float] = []
        for circuit, group in sorted(by_workload.items()):
            mean = {a: {k: sum(g[a][k] for g in group) / len(group) for k in ("fidelity", "p_keep", "duration_us")} for a in ARMS}
            line = f"{circuit:24s}" + "".join(f"{mean[a]['fidelity']:16.4f}" for a in ARMS) + f"{mean['prism']['p_keep']:12.3f}"
            for o in args.overhead:
                per_shot = {a: (mean[a]["duration_us"] + o) / mean[a]["p_keep"] for a in ARMS}
                ratios[o].append(per_shot["prism"] / per_shot["bare_transmon"])
                line += f"{ratios[o][-1]:14.2f}"
            infidelity_gain.append((1 - mean["bare_transmon"]["fidelity"]) / (1 - mean["prism"]["fidelity"]))
            print(line)
        print("geometric means over workloads:")
        print(f"  transmon infidelity / PRISM conditional infidelity: {_gmean(infidelity_gain):.1f}x")
        for o in args.overhead:
            print(f"  overhead {o:g} us: PRISM wall-clock per kept shot vs transmon {_gmean(ratios[o]):.2f}x "
                  f"(max {max(ratios[o]):.2f}x)")


if __name__ == "__main__":
    main()
