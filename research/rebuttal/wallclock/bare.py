"""Bare-transmon arm of the break-even evaluation (`BARE_PREREG.md`): parameters, compile and fidelity model.

  .venv/bin/python research/rebuttal/wallclock/bare.py --width 8 --workers 2

For each (workload, topology, seed) cell this compiles the circuit for a fixed-frequency transmon chip
of 2(n+1) qubits (the dual-rail chip), keeps the best of K = 40 transpiler seeds by ESP, and walks the
ideal statevector of the compiled circuit once. At every noise location (each gate, each idle or
gate-duration interval of each qubit, each readout) it records the exact fidelity of the local channel
applied to the ideal state there. The model fidelity is the product over locations; it is exact to first
order in the error rates and is checked against `sim.simulate_bare` by `validate_bare.py`. Because the
recorded quantities depend only on the circuit, every transmon parameter is a closed-form sweep.

Rows go to `data/bare_n<width>.jsonl`: one row per cell and compile arm (`best40`, `best1`, and
`all_to_all` once per workload), with ln F of the program qubits on the CZ-error grid `R_GRID` for each
transmon variant in `VARIANTS`.
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import argparse
import dataclasses
import json
import math
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from qiskit.quantum_info import Operator

import run  # noqa: F401  (puts src/ and scripts/paper on the path and makes CZ a diagonal for rescheduling)
import sim

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
BASIS = ["cz", "sx", "x", "rz"]
# Fastest sourced gate times (Willow, arXiv:2408.13687 SI: CZ 42 ns, XY 25 ns), the transmon-favourable end.
DURATIONS = {"cz": 0.042, "sx": 0.025, "x": 0.025, "rz": 0.0}
K = 40
R_GRID = np.geomspace(1e-4, 3e-2, 81)


@dataclass(frozen=True)
class Transmon:
    """Published transmon numbers: RB average gate errors, T1 and T2 (us), and readout flip probability."""

    cz: float = 3e-3
    sq: float = 2.88e-4
    t1: float = 136.5
    t2: float = 89.0
    readout: float = 7.7e-3

    @property
    def p2(self) -> float:
        """Two-qubit depolarizing probability; RB average error r = 3p/4."""
        return 4 * self.cz / 3

    @property
    def p1(self) -> float:
        """Single-qubit depolarizing probability; r = p/2."""
        return 2 * self.sq

    @property
    def dephasing(self) -> float:
        """Pure-dephasing rate 1/T_phi = 1/T2 - 1/(2 T1)."""
        return 1 / self.t2 - 1 / (2 * self.t1)

    def device(self) -> sim.Device:
        """The same transmon as a `sim.Device` for the exact simulator."""
        return sim.Device("transmon", self.t1, self.dephasing, DURATIONS, depolarizing={"cz": self.p2, "sx": self.p1, "x": self.p1})


CENTRAL = Transmon()
# One-at-a-time ranges (BARE_PREREG.md section 2), and the corners with every parameter at its best or worst.
VARIANTS = {
    "central": CENTRAL,
    "sq_lo": dataclasses.replace(CENTRAL, sq=1.5e-4),
    "sq_hi": dataclasses.replace(CENTRAL, sq=3.5e-4),
    "t1_lo": dataclasses.replace(CENTRAL, t1=68.0),
    "t1_hi": dataclasses.replace(CENTRAL, t1=262.7),
    "t2_lo": dataclasses.replace(CENTRAL, t2=78.6),
    "t2_hi": dataclasses.replace(CENTRAL, t2=2 * CENTRAL.t1),
    "ro_lo": dataclasses.replace(CENTRAL, readout=3.4e-3),
    "ro_hi": dataclasses.replace(CENTRAL, readout=1.63e-2),
    "best": Transmon(sq=1.5e-4, t1=262.7, t2=2 * 262.7, readout=3.4e-3),
    "worst": Transmon(sq=3.5e-4, t1=68.0, t2=78.6, readout=1.63e-2),
}


def schedule(qc):
    """ASAP schedule: (instruction, qubit indices, start) per non-barrier instruction, and the duration."""
    clock = defaultdict(float)
    out = []
    for ins in qc.data:
        if ins.operation.name == "barrier":
            continue
        qubits = [qc.find_bit(q).index for q in ins.qubits]
        start = max(clock[q] for q in qubits)
        out.append((ins.operation, qubits, start))
        for q in qubits:
            clock[q] = start + DURATIONS[ins.operation.name]
    return out, max(clock.values(), default=0.0)


def log_esp(qc, t: Transmon = CENTRAL) -> float:
    """ln ESP: every gate succeeds, and every active qubit's idle time decays at 1/T1 + 1/T_phi."""
    ops, end = schedule(qc)
    busy = defaultdict(float)
    for op, qubits, _ in ops:
        for q in qubits:
            busy[q] += DURATIONS[op.name]
    gates = sum(math.log(1 - (t.cz if op.name == "cz" else t.sq)) for op, _, _ in ops if op.name != "rz")
    return gates - sum(end - b for b in busy.values()) * (1 / t.t1 + t.dephasing)


def _transpile(qc, cmap, seed):
    """Compile one candidate pair (stock O3, logical optimizer then O3), rescheduled like the dual-rail arms."""
    from qiskit import transpile
    from qiskit.transpiler import PassManager

    from marabbecca.encodings import DualRail
    from marabbecca.synthesis.reschedule import RescheduleCommutingDiagonals

    out = []
    for src in (qc, DualRail.logical_pm().run(qc)):
        c = transpile(src, coupling_map=cmap, basis_gates=BASIS, optimization_level=3, seed_transpiler=seed)
        logical = c.layout.final_index_layout() if c.layout is not None else list(range(qc.num_qubits))
        out.append((PassManager([RescheduleCommutingDiagonals()]).run(c), logical))
    return out


def compile_cell(qc, cmap, seed: int, k: int) -> dict:
    """Best of 2k candidates by ESP (transpiler seeds seed .. seed + k - 1), and the best of the first pair."""
    scored = [(log_esp(c), j, c, logical) for j in range(k) for c, logical in _transpile(qc, cmap, seed + j)]
    return {"best1": max(scored[:2], key=lambda s: s[0]), f"best{k}": max(scored, key=lambda s: s[0])}


def _rdm(psi: np.ndarray, n: int, qubits: list[int]) -> np.ndarray:
    """Reduced density matrix of ``qubits`` (little-endian, qubits[0] the low bit) of an n-qubit vector."""
    t = np.moveaxis(psi.reshape([2] * n), [n - 1 - q for q in reversed(qubits)], range(len(qubits)))
    m = t.reshape(2 ** len(qubits), -1)
    return m @ m.conj().T


def fingerprint(qc, logical: list[int]) -> dict:
    """Walk the ideal state once and record the per-location quantities the fidelity model needs.

    Locations on a qubit whose content ends outside the program (an ancilla, never touched by a CZ again)
    cannot change the program qubits' state and are skipped, as are their halves of a CZ error.
    """
    ops, end = schedule(qc)
    active = sorted({q for _, qubits, _ in ops for q in qubits})
    index = {p: i for i, p in enumerate(active)}
    n = len(active)
    program = {index[p] for p in logical}
    last2q = defaultdict(lambda: -1)
    for i, (op, qubits, _) in enumerate(ops):
        if len(qubits) == 2:
            for q in qubits:
                last2q[index[q]] = i
    psi = np.zeros(2**n, dtype=complex)
    psi[0] = 1
    clock = [0.0] * n
    bloch = [(1.0, 0.0)] * n  # (<Z>, <X>^2 + <Y>^2) after each qubit's last gate
    cz_h, sq_h, seg = [], [], []  # seg: (duration, <Z>, <X>^2 + <Y>^2)

    def benign(q: int, i: int) -> bool:
        return q not in program and i >= last2q[q]

    def single(q: int) -> tuple[float, float]:
        r = _rdm(psi, n, [q])
        z = float((r[0, 0] - r[1, 1]).real)
        return z, float(4 * abs(r[0, 1]) ** 2)

    for i, (op, qubits, start) in enumerate(ops):
        qs = [index[q] for q in qubits]
        for q in qs:
            if start > clock[q] and (q in program or i <= last2q[q]):
                seg.append((start - clock[q], *bloch[q]))
        m = Operator(op).data
        if len(qs) == 1:
            t = np.moveaxis(psi.reshape([2] * n), n - 1 - qs[0], 0)
            psi = np.moveaxis(np.tensordot(m, t, axes=(1, 0)), 0, n - 1 - qs[0]).reshape(-1)
        else:
            psi = psi * np.diag(m)[sum(((np.arange(2**n) >> q) & 1) << k for k, q in enumerate(qs))]
        if op.name == "rz":
            continue
        for q in qs:
            bloch[q] = single(q)
        if op.name == "cz":
            a, b = qs
            if benign(a, i) and benign(b, i):
                pass
            elif benign(a, i) or benign(b, i):
                z, w = bloch[b if benign(a, i) else a]
                cz_h.append((3 - (z * z + w)) / 4)
            else:
                r = _rdm(psi, n, qs)
                cz_h.append((15 - (4 * float(np.trace(r @ r).real) - 1)) / 16)
        elif not benign(qs[0], i):
            z, w = bloch[qs[0]]
            sq_h.append((3 - (z * z + w)) / 4)
        for q in qs:
            if not benign(q, i):
                seg.append((DURATIONS[op.name], *bloch[q]))
            clock[q] = start + DURATIONS[op.name]
    for q in program:
        if end > clock[q]:
            seg.append((end - clock[q], *bloch[q]))
    ro_x2 = []
    for q in sorted(program):
        r = _rdm(psi, n, [q])
        ro_x2.append(float(4 * r[0, 1].real ** 2))
    seg = np.array(seg) if seg else np.zeros((0, 3))
    return {"cz_h": np.array(cz_h), "sq_h": np.array(sq_h), "seg": seg, "ro_x2": np.array(ro_x2),
            "n_active": n, "duration_us": end}


def log_fidelity(fp: dict, t: Transmon, cz: np.ndarray | float | None = None) -> np.ndarray | float:
    """Model ln F of the program qubits: the product over locations of each local channel's fidelity."""
    cz = np.atleast_1d(t.cz if cz is None else cz)
    out = np.log1p(-np.outer(4 * cz / 3, fp["cz_h"])).sum(axis=1)
    out += np.log1p(-t.p1 * fp["sq_h"]).sum()
    dt, z, w = fp["seg"].T
    gamma = -np.expm1(-dt / t.t1)
    s = np.sqrt(1 - gamma)
    amplitude = ((1 + s) / 2 + (1 - s) / 2 * z) ** 2 + gamma * w / 4
    pz = -np.expm1(-dt * t.dephasing) / 2
    out += np.log(amplitude).sum() + np.log1p(-pz * (1 - z * z)).sum()
    out += np.log1p(-t.readout * (1 - fp["ro_x2"])).sum()
    return out if out.size > 1 else float(out[0])


def _cell(task: tuple) -> list[dict]:
    """Compile one (workload, topology, seed) cell, fingerprint its arms, and return one row per arm."""
    from qiskit import qpy

    from paper_common import make_topologies

    circuit, width, topology, seed, k = task
    with (REPO / f"artifacts/paper/manifests/circuits/{circuit}_n{width}.qpy").open("rb") as f:
        qc = qpy.load(f)[0].remove_final_measurements(inplace=False)
    arms = {"all_to_all": max(((log_esp(c), 0, c, lg) for c, lg in _transpile(qc, None, 0)), key=lambda s: s[0])} if topology == "all_to_all" \
        else compile_cell(qc, make_topologies(width)[topology], seed, k)
    rows = []
    for arm, (esp, j, c, logical) in arms.items():
        fp = fingerprint(c, logical)
        rows.append({
            "circuit": circuit, "n_logical": qc.num_qubits, "topology": topology, "seed": seed, "arm": arm, "transpiler_seed": seed + j,
            "op_counts": dict(c.count_ops()), "n_active": fp["n_active"], "duration_us": fp["duration_us"], "log_esp": esp,
            "log_fidelity": {v: np.round(log_fidelity(fp, t, R_GRID), 7).tolist() for v, t in VARIANTS.items()},
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 100, 200, 300, 400])
    parser.add_argument("--circuits", nargs="+", default=run.CFG["circuits"])
    parser.add_argument("--k", type=int, default=K)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    circuits = [c for c in args.circuits if (REPO / f"artifacts/paper/manifests/circuits/{c}_n{args.width}.qpy").exists()]
    tasks = [(c, args.width, t, s, args.k) for c in circuits for t in ("grid", "hex_lattice") for s in args.seeds]
    tasks += [(c, args.width, "all_to_all", 0, 1) for c in circuits]
    path = Path(args.out) if args.out else HERE / "data" / f"bare_n{args.width}.jsonl"
    with path.open("w") as f, ProcessPoolExecutor(args.workers) as pool:
        for rows in pool.map(_cell, tasks):
            for row in rows:
                f.write(json.dumps(row) + "\n")
            f.flush()
            print(rows[0]["circuit"], rows[0]["topology"], rows[0]["seed"], flush=True)


if __name__ == "__main__":
    main()
