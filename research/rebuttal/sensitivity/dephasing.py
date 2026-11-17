"""Retained-shot fidelity of the saved width-16 SWAP-selected circuits (Greedy/PRISM, 16 MQT x grid/hex x 5 seeds)
on MEHTA_IDLE at several background dephasing rates, everything else at the measured values.
T_phi is the dual-rail logical coherence time 1/(2 gamma); the measured device has 2.2 ms.
Rows go to data/swaps/dephasing_n16.jsonl (resumable); summarize with dephasing_report.py.
Usage: .venv/bin/python research/rebuttal/sensitivity/dephasing.py [--shots 200 --workers 6]"""
import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import argparse, dataclasses, json, sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
WC = REPO / "research/rebuttal/wallclock"
sys.path[:0] = [str(WC), str(REPO / "src")]
import sim  # noqa: E402
from resim import qc_load  # noqa: E402

CIRCUITS = WC / "data/swaps/circuits_n16"
OUT = Path(__file__).resolve().parent / "data/swaps/dephasing_n16.jsonl"
# In run order, the measured point first. At 0.05 ms the n = 16 circuits keep almost no fidelity (ae about 0.01).
TPHI_MS = (1 / (2 * sim.MEHTA_IDLE.dephasing) / 1000, 0.3, 1.0, 0.1, 5.0)


def _one(task):
    path, tphi_ms, shots = task
    arm = path.stem.rsplit("_", 1)[1]
    name, topology, seed = _parse(path.stem)
    device = dataclasses.replace(sim.MEHTA_IDLE, dephasing=1 / (2 * tphi_ms * 1000))
    result = sim.simulate_dualrail(qc_load(path), device, shots=shots, seed=seed)
    return {"circuit": name, "topology": topology, "seed": seed, "arm": arm, "tphi_ms": tphi_ms, "shots": shots} | result


def _parse(stem):
    body = stem.rsplit("_", 1)[0]
    for topology in ("hex_lattice", "grid"):
        head, sep, seed = body.rpartition(f"_{topology}_")
        if sep:
            return head, topology, int(seed)
    raise ValueError(stem)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shots", type=int, default=200)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    done = set()
    if OUT.exists():
        for line in OUT.open():
            r = json.loads(line)
            done.add((r["circuit"], r["topology"], r["seed"], r["arm"], round(r["tphi_ms"], 6)))
    # Largest circuits first within each point, so the pool does not end on one long simulation.
    paths = sorted(CIRCUITS.glob("*.qpy"), key=lambda p: -p.stat().st_size)
    tasks = []
    for tphi in TPHI_MS:
        for p in paths:
            name, topology, seed = _parse(p.stem)
            if (name, topology, seed, p.stem.rsplit("_", 1)[1], round(tphi, 6)) not in done:
                tasks.append((p, tphi, args.shots))
    total = len(tasks)
    print(f"0/{total} simulations ({len(done)} already done)", flush=True)
    with OUT.open("a") as f, ProcessPoolExecutor(args.workers) as pool:
        futures = [pool.submit(_one, t) for t in tasks]
        for i, fut in enumerate(as_completed(futures), 1):
            f.write(json.dumps(fut.result()) + "\n")
            f.flush()
            print(f"{i}/{total} simulations", flush=True)


if __name__ == "__main__":
    main()
