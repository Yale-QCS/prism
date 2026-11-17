"""Compile the core suite for dual-rail (Greedy, PRISM) and bare devices, then simulate each circuit.

  .venv/bin/python research/rebuttal/wallclock/run.py --width 8 --seeds 0 100 200 300 400 --workers 6
  .venv/bin/python research/rebuttal/wallclock/run.py --width 16 --seeds 0 100 --shots 1000 --bare-shots 128 --workers 8

Dual-rail arms (Logical-SABRE, Greedy, PRISM) use the `core` router settings; bare arms use stock Qiskit O3 on
the same coupling map. One row per (circuit, topology, seed, arm) in
`data/legacy/rows_n<width>.jsonl`.
"""

from __future__ import annotations

import os

# One BLAS thread per worker; otherwise every process spawns one per core and the pool oversubscribes.
for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import argparse
import dataclasses
import json
import sys
import tomllib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path[:0] = [str(REPO / "scripts/paper"), str(REPO / "src"), str(HERE)]

import run_fairness  # noqa: E402
import sim  # noqa: E402
from paper_common import make_topologies  # noqa: E402

import marabbecca.synthesis.reschedule as reschedule  # noqa: E402

# CZ is diagonal too; dual-rail circuits contain none, so their arms are unaffected.
reschedule.DIAGONAL = reschedule.DIAGONAL | {"cz"}

# Router settings: the SWAP-selected suite configuration of 2026-10-11 (objective = "swaps", as the submission).
CFG = tomllib.loads((REPO / "research/rebuttal/suite/swaps/core_swaps.toml").read_text())
TRANSMONS = {"representative": sim.BARE_TRANSMON, "strong": sim.STRONG_TRANSMON}


def _bare_compile(qc, cmap, device, basis, seed):
    """Shorter of stock O3 and the dual-rail logical optimizer then O3, each rescheduled like the dual-rail arms."""
    from qiskit import transpile
    from qiskit.transpiler import PassManager

    from marabbecca.encodings import DualRail

    candidates = [
        PassManager([reschedule.RescheduleCommutingDiagonals()]).run(
            transpile(src, coupling_map=cmap, basis_gates=basis, optimization_level=3, seed_transpiler=seed)
        )
        for src in (qc, DualRail.logical_pm().run(qc))
    ]
    return min(candidates, key=lambda c: sim.schedule_duration(c, device))


def _save(qc, path: Path) -> None:
    """Save the instructions of a compiled circuit (QPY cannot serialize its routing layout)."""
    from qiskit import QuantumCircuit, qpy

    bare = QuantumCircuit(qc.num_qubits)
    bare.compose(qc, inplace=True)
    with path.open("wb") as f:
        qpy.dump(bare, f)


def _unmeasured(qc):
    """A routed circuit without its measurements. The workload measures only at its end, but the router may still
    move other qubits through a measured rail, so the measurements are not all final."""
    from qiskit import QuantumCircuit

    out = QuantumCircuit(qc.num_qubits)
    for ins in qc.data:
        if ins.operation.name != "measure":
            out.append(ins.operation, [qc.find_bit(q).index for q in ins.qubits])
    return out


def _cell(task: tuple) -> list[dict]:
    """Compile and simulate every arm of one (circuit, width, topology, seed) cell; save the compiled circuits."""
    from qiskit import qpy

    from marabbecca.utils.metrics import device_success, physical_duration

    circuit, width, topology, seed, shots, bare_shots, loss, transmon, device_name, data_dir, measured, arms = task
    if device_name == "mehta":
        device = sim.MEHTA
    else:
        device = dataclasses.replace(sim.LEGACY, loss={"crz": loss}) if loss else sim.LEGACY
    saved = data_dir / f"circuits_n{width}"
    saved.mkdir(parents=True, exist_ok=True)
    with (REPO / f"artifacts/paper/manifests/circuits/{circuit}_n{width}.qpy").open("rb") as f:
        source = qpy.load(f)[0]
    qc = source.remove_final_measurements(inplace=False)
    cmap = make_topologies(width)[topology]
    base = {"circuit": circuit, "n_logical": qc.num_qubits, "topology": topology, "seed": seed}
    rows = []
    for arm in arms:
        pm = run_fairness._build_arm_pm(run_fairness._arm_spec_for_config(CFG, arm), cmap, seed, CFG["objective"])
        # measured: route the workload with its terminal measurements, as run_fairness does, then drop them.
        out = _unmeasured(pm.run(source)) if measured else pm.run(qc)
        _save(out, saved / f"{circuit}_{topology}_{seed}_{arm}.qpy")
        counts = dict(out.count_ops())
        analytic_keep, analytic_fidelity = device_success(qc.num_qubits, physical_duration(out), counts)
        rows.append(
            base
            | {"arm": arm, "op_counts": counts, "analytic_p_keep": analytic_keep, "analytic_fidelity": analytic_fidelity, "shots": shots}
            | ({} if device_name == "mehta" else {"coupler_loss": loss})
            | sim.simulate_dualrail(out, device, shots=shots, seed=seed)
        )
    if transmon == "none":
        return rows
    bare = TRANSMONS[transmon]
    out = _bare_compile(qc, cmap, bare, sim.BARE_TRANSMON_BASIS, seed)
    _save(out, saved / f"{circuit}_{topology}_{seed}_bare_transmon.qpy")
    rows.append(
        base
        | {"arm": bare.name, "op_counts": dict(out.count_ops()), "shots": bare_shots}
        | sim.simulate_bare(out, bare, shots=bare_shots, seed=seed)
    )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--width", type=int, default=8)
    parser.add_argument("--seeds", type=int, nargs="+", default=[0])
    parser.add_argument("--topologies", nargs="+", default=["grid", "hex_lattice"])
    parser.add_argument("--circuits", nargs="+", default=CFG["circuits"])
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--shots", type=int, default=None, help="dual-rail trajectories (default: exact)")
    parser.add_argument("--bare-shots", type=int, default=None, help="bare trajectories (default: exact)")
    parser.add_argument("--loss", type=float, default=0.0, help="SWS coupler loss per CR_z on the dual-rail arms")
    parser.add_argument("--transmon", choices=[*sorted(TRANSMONS), "none"], default="representative", help="transmon point to simulate")
    parser.add_argument("--device", choices=("legacy", "mehta"), default="legacy", help="mehta: rows in v2_n<width>.jsonl, no coupler loss")
    parser.add_argument("--resume", action="store_true", help="append to the row file, skipping cells already on it")
    parser.add_argument("--data-dir", type=Path, default=HERE / "data", help="where circuits_n<width>/ and the rows go")
    parser.add_argument("--measured", action="store_true", help="route with the terminal measurements (same circuits as run_fairness rows)")
    parser.add_argument("--arms", nargs="+", default=["logical", "greedy", "prism"], help="dual-rail arms to compile")
    args = parser.parse_args()
    tasks = [
        (c, args.width, t, s, args.shots, args.bare_shots, args.loss, args.transmon, args.device, args.data_dir.resolve(), args.measured, args.arms)
        for c in args.circuits
        for t in args.topologies
        for s in args.seeds
    ]
    if args.device == "mehta":
        path = args.data_dir / f"v2_n{args.width}.jsonl"
    else:
        path = args.data_dir / "legacy" / f"rows_n{args.width}{f'_loss{args.loss:g}' if args.loss else ''}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    if args.resume and path.exists():
        done = {(r["circuit"], r["topology"], r["seed"]) for r in map(json.loads, path.open())}
        tasks = [t for t in tasks if (t[0], t[2], t[3]) not in done]
        print(f"resuming: {len(done)} cells on file, {len(tasks)} to run", flush=True)
    with path.open("a" if args.resume else "w") as f, ProcessPoolExecutor(args.workers) as pool:
        for i, rows in enumerate(pool.map(_cell, tasks), 1):
            for row in rows:
                f.write(json.dumps(row) + "\n")
            f.flush()
            print(f"{i}/{len(tasks)}", rows[0]["circuit"], rows[0]["topology"], rows[0]["seed"], flush=True)


if __name__ == "__main__":
    main()
