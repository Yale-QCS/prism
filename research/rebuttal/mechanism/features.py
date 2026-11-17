"""Mechanism features (pre-registered in README.md): A, A' from logical circuits; B, C, D from routed lowering-stage circuits.

Usage: .venv/bin/python research/rebuttal/mechanism/features.py [--workers N]
Writes data/predictors.json (one row per workload) and data/mediators.jsonl (one row per cell and seed).
"""

import argparse
import json
import sys
import tomllib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/paper"))
OUT = Path(__file__).parent / "data"
SEEDS = (0, 100, 200)
TOPOLOGIES = ("grid", "hex_lattice", "heavy_hex")
CFG = tomllib.loads((ROOT / "configs/paper/core.toml").read_text())


def load(circuit):
    from qiskit import qpy

    with open(ROOT / f"artifacts/paper/manifests/circuits/{circuit}_n8.qpy", "rb") as f:
        return qpy.load(f)[0]


def predictors(circuit):
    """A and A' from the dual-rail logical-stage circuit: CR_z incidences and distinct partners per separated-rail interval."""
    from marabbecca.encodings import DualRail

    qc = DualRail.logical_pm().run(load(circuit))
    incidences, partners = {}, {}  # (qubit, interval) -> count, set
    interval = [0] * qc.num_qubits
    for inst in qc.data:
        qs = [qc.find_bit(q).index for q in inst.qubits]
        if inst.operation.name in ("rx", "x"):
            interval[qs[0]] += 1
        elif inst.operation.name == "crz":
            for q, other in ((qs[0], qs[1]), (qs[1], qs[0])):
                key = (q, interval[q])
                incidences[key] = incidences.get(key, 0) + 1
                partners.setdefault(key, set()).add(other)
    n = len(incidences)
    return {
        "circuit": circuit,
        "A": sum(incidences.values()) / n,
        "A_prime": sum(len(p) for p in partners.values()) / n,
        "n_crz": sum(incidences.values()) // 2,
        "n_intervals": n,
    }


def replay(out, layout):
    """Walk a routed circuit; yield (op name, physical qubits, rail->physical map before the op)."""
    rail_at = {}  # physical -> (logical, rail)
    for phys, virt in layout.get_physical_bits().items():
        if virt._register is not None and virt._register.name.startswith("q"):
            rail_at[phys] = (int(virt._register.name[1:]), virt._index)
    for inst in out.data:
        qs = tuple(out.find_bit(q).index for q in inst.qubits)
        yield inst.operation.name, qs, dict(rail_at)
        if inst.operation.name == "swap":
            a, b = qs
            ra, rb = rail_at.pop(a, None), rail_at.pop(b, None)
            if ra is not None:
                rail_at[b] = ra
            if rb is not None:
                rail_at[a] = rb


def mediators(task):
    """B (PRISM), D (Greedy) and C (Greedy) for one cell and seed, plus the same-named quantities on the other arm."""
    import run_fairness as rf
    from qiskit.transpiler import PassManager

    circuit, topo, seed = task
    cmap = rf.make_topologies(8)[topo]
    dist = np.asarray(cmap.distance_matrix)
    row = {"circuit": circuit, "topology": topo, "seed": seed}
    for arm in ("greedy", "prism"):
        pm = rf._build_arm_pm(rf._arm_spec_for_config(CFG, arm), cmap, seed, CFG["objective"])
        pm.physical = PassManager([])
        out = pm.run(load(circuit))
        events = list(replay(out, pm.property_set["layout"]))
        pos = lambda m: {r: p for p, r in m.items()}  # (logical, rail) -> physical
        last = {}  # (logical, rail) -> index of its last op
        choice, gaps, attributed = [], [], {"reach": 0, "rejoin": 0, "herald": 0}
        router_swaps = []
        for i, (name, qs, m) in enumerate(events):
            rails = [m.get(q) for q in qs]
            if name == "crz":
                (u, _), (v, _) = rails
                where = pos(m)
                adjacent = sum(dist[where[(u, a)], where[(v, b)]] == 1 for a in (0, 1) for b in (0, 1))
                choice.append(adjacent >= 2)
                t0 = max(last.get(r, -1) for r in ((u, 0), (u, 1), (v, 0), (v, 1)))
                then = pos(events[t0 + 1][2]) if t0 + 1 < len(events) else where
                bound = dist[then[rails[0]], then[rails[1]]]
                gaps.append(bound - min(dist[then[(u, a)], then[(v, b)]] for a in (0, 1) for b in (0, 1)))
            if name == "swap" and not (rails[0] and rails[1] and rails[0][0] == rails[1][0]):
                router_swaps.append(i)
                continue  # router SWAPs move rails but are not program predecessors
            for r in rails:
                if r is not None:
                    last[r] = i
        for i in router_swaps:
            touched = set(events[i][1])
            for name, qs, m in events[i + 1 :]:
                if len(qs) == 2 and touched & set(qs):
                    rails = [m.get(q) for q in qs]
                    semantic = name == "swap" and rails[0] and rails[1] and rails[0][0] == rails[1][0]
                    if name == "crz":
                        attributed["reach"] += 1
                    elif name == "rswap" or semantic:
                        attributed["rejoin"] += 1
                    elif name == "joint_herald":
                        attributed["herald"] += 1
                    else:
                        continue  # another router swap; keep looking past it
                    break
        total = sum(attributed.values())
        row[arm] = {
            "router_swaps": len(router_swaps),
            "B": float(np.mean(choice)) if choice else 0.0,
            "D": float(np.mean(gaps)) if gaps else 0.0,
            "C": attributed["rejoin"] / total if total else 0.0,
            "attributed": attributed,
            "n_crz": len(choice),
        }
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--out", type=Path, default=OUT / "mediators.jsonl", help="write to an untracked path while running")
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    circuits = CFG["circuits"]
    (OUT / "predictors.json").write_text(json.dumps([predictors(c) for c in circuits], indent=1))
    path = args.out
    done = {(r["circuit"], r["topology"], r["seed"]) for r in map(json.loads, path.open())} if path.exists() else set()
    tasks = [(c, t, s) for c in circuits for t in TOPOLOGIES for s in SEEDS if (c, t, s) not in done]
    with ProcessPoolExecutor(args.workers) as pool, path.open("a") as f:
        for row in pool.map(mediators, tasks):
            f.write(json.dumps(row) + "\n")
            f.flush()
            print(row["circuit"], row["topology"], row["seed"], flush=True)


if __name__ == "__main__":
    main()
