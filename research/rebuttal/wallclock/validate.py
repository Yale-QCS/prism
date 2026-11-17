"""Validate the dual-rail simulator before every batch (MODEL.md section 4). Under 2 minutes.

  .venv/bin/python research/rebuttal/wallclock/validate.py

Uses saved circuits from `run.py` (`data/circuits_n8/`) and compiles a few small ones:
1. Noiseless: the codespace state equals `Statevector` of the routed rail circuit
   (3 saved n = 8 grid circuits, one per arm; idle-pair preparations, which the
   engine skips, are dropped from the reference).
2. Noisy: P_keep and kept-shot fidelity equal a full rail-level density matrix with
   loss as explicit Kraus jumps, projected on the shots that keep every photon.
   All three devices with every noise rate x25, 3 random 3-qubit circuits on 8 rails.
   Tolerance 1e-6. Under MEHTA_IDLE the reference dephases both rails of a pair
   over the pair's idle time, where sim.py dephases one mask bit at twice the rate.
3. P_keep equals its closed form, exp(-sum over pairs of idle time / T1) times the
   survival factors, with idle time and touches counted here, independently of
   sim.py (for LEGACY without coupler loss, exp(-n D / T1)). 20 saved circuits,
   tolerance 1e-12. MEHTA and MEHTA_IDLE give the same P_keep.
4. Trajectories (1000) against exact at n = 8: fidelity within 3 standard errors
   and P_keep equal, on 4 saved circuits, MEHTA and MEHTA_IDLE.
Exits non-zero if any check fails.
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import dataclasses
import math
import sys
import tomllib
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path[:0] = [str(REPO / "scripts/paper"), str(REPO / "src"), str(HERE), str(REPO / "tests")]

import run_fairness  # noqa: E402
import sim  # noqa: E402
from qiskit.quantum_info import DensityMatrix, Kraus, Operator, Statevector  # noqa: E402
from qiskit.transpiler import CouplingMap  # noqa: E402
from test_encoded_equivalence import _logical  # noqa: E402

CFG = tomllib.loads((REPO / "configs/paper/core.toml").read_text())
ARMS = ("logical", "greedy", "prism")


def compile_arm(qc, arm, cmap, seed=0):
    pm = run_fairness._build_arm_pm(run_fairness._arm_spec_for_config(CFG, arm), cmap, seed, CFG["objective"])
    return pm.run(qc)


class Captured(sim.CodespaceState):
    last = None

    def __init__(self, live):
        super().__init__(live)
        Captured.last = self


def ideal_rail_vector(qc):
    """Run the engine noiselessly and return its ideal state on the rail basis (qiskit order)."""
    original = sim.CodespaceState
    sim.CodespaceState = Captured
    try:
        sim.simulate_dualrail(qc, dataclasses.replace(sim.LEGACY, t1=math.inf, dephasing=0.0, pauli_z={}))
    finally:
        sim.CodespaceState = original
    s = Captured.last
    index = sum(((s.masks >> b) & 1) << r for r, b in s.bit.items())
    out = np.zeros(2**qc.num_qubits, dtype=complex)
    np.add.at(out, index, s.ideal)
    return out


def damping(gamma):
    return Kraus([np.array([[1, 0], [0, math.sqrt(1 - gamma)]]), np.array([[0, math.sqrt(gamma)], [0, 0]])])


def dephase(p):
    return Kraus([math.sqrt(1 - p) * np.eye(2), math.sqrt(p) * np.diag([1.0, -1.0])])


def pair_loss(survival):
    """Loss of the one photon in a pair with probability 1 - survival, whichever rail holds it."""
    k0 = np.diag([1.0, math.sqrt(survival), math.sqrt(survival), math.sqrt(survival)])
    k1, k2 = np.zeros((4, 4)), np.zeros((4, 4))
    k1[0, 1] = k2[0, 2] = math.sqrt(1 - survival)
    return Kraus([k0, k1, k2])


def union_length(intervals):
    covered, reach = 0.0, 0.0
    for a, b in sorted(intervals):
        covered += max(0.0, b - max(a, reach))
        reach = max(reach, b)
    return covered


def reference(qc, device):
    """Full rail density matrix with loss jumps; return P_keep and the kept state's fidelity to the ideal."""
    live, idle, pair = sim.live_pairs(qc)
    where = list(range(qc.num_qubits))  # position -> original rail of its content
    rho = DensityMatrix.from_label("0" * qc.num_qubits)
    clock = [0.0] * qc.num_qubits
    busy = {p: [] for p in pair.values()}

    dephased = {p: 0.0 for p in pair.values()}

    def relax(rho, r, t):
        if t <= 0:
            return rho
        if not device.erasure:
            rho = rho.evolve(damping(1 - math.exp(-t / device.t1)), [r])
        if device.idle_dephasing:
            return rho
        return rho.evolve(dephase((1 - math.exp(-device.dephasing * t)) / 2), [r])

    def pair_of(r):
        return pair[live[where[r]]] if where[r] in live else None

    def idle_dephase(rho, p, until):
        """Dephase both rails of pair ``p`` at the background rate over its idle time up to ``until``."""
        t = until - dephased[p] - union_length([(max(a, dephased[p]), min(b, until)) for a, b in busy[p] if b > dephased[p] and a < until])
        dephased[p] = until
        for r in range(qc.num_qubits):
            if pair_of(r) == p:
                rho = rho.evolve(dephase((1 - math.exp(-device.dephasing * t)) / 2), [r])
        return rho

    for i, ins in enumerate(qc.data):
        op = ins.operation
        if op.name == "barrier" or i in idle:
            continue
        rails = [qc.find_bit(q).index for q in ins.qubits]
        start = max(clock[r] for r in rails)
        for r in rails:
            rho = relax(rho, r, start - clock[r])
        if device.idle_dephasing and op.name not in sim._Z_COMMUTING:
            for p in {pair_of(r) for r in rails} - {None}:
                rho = idle_dephase(rho, p, start)
        synthetic = sim.is_synthetic_preparation(op)
        if op.name != "joint_herald":
            rho = rho.evolve(Operator(op), rails)
        if op.name == "swap":
            a, b = rails
            where[a], where[b] = where[b], where[a]
        duration = 0.0 if synthetic else device.durations[op.name]
        for r in rails:
            rho = relax(rho, r, duration)
        if not synthetic:
            for r, p in zip(rails, device.pauli_z.get(op.name, ())):
                rho = rho.evolve(dephase(p), [r])
            if op.name in device.loss and not device.erasure:
                rho = rho.evolve(damping(device.loss[op.name]), [rails[0]])
            touched = {}
            for r, e in zip(rails, device.erasure.get(op.name, ())):
                if pair_of(r) is not None:
                    touched.setdefault(pair_of(r), e)
            for p, e in touched.items():
                positions = [r for r in range(qc.num_qubits) if pair_of(r) == p]
                rho = rho.evolve(pair_loss(1 - e), positions)
                busy[p].append((start, start + duration))
        for r in rails:
            clock[r] = start + duration
    end = max(clock)
    for r in range(qc.num_qubits):
        rho = relax(rho, r, end - clock[r])
    if device.erasure:
        for p, intervals in busy.items():
            positions = [r for r in range(qc.num_qubits) if pair_of(r) == p]
            rho = rho.evolve(pair_loss(math.exp(-(end - union_length(intervals)) / device.t1)), positions)
    if device.idle_dephasing:
        for p in busy:
            rho = idle_dephase(rho, p, end)
    photons = np.array([bin(k).count("1") for k in range(2**qc.num_qubits)])
    keep = photons == len(set(pair.values()))
    kept = rho.data[np.ix_(keep, keep)]
    psi = ideal_rail_vector(qc)[keep]
    p_keep = float(np.trace(kept).real)
    return p_keep, float((psi.conj() @ kept @ psi).real) / p_keep


def _pair_schedule(qc, device):
    """From the schedule alone: duration D, each pair's busy intervals and summed ln(1 - e) of its erasures."""
    live, idle, pair = sim.live_pairs(qc)
    where = list(range(qc.num_qubits))
    clock = [0.0] * qc.num_qubits
    busy = {p: [] for p in pair.values()}
    log_keep = {p: 0.0 for p in pair.values()}
    for i, ins in enumerate(qc.data):
        op = ins.operation
        if op.name == "barrier" or i in idle:
            continue
        rails = [qc.find_bit(q).index for q in ins.qubits]
        start = max(clock[r] for r in rails)
        duration = 0.0 if sim.is_synthetic_preparation(op) else device.durations[op.name]
        if duration and op.name in device.erasure:
            pairs = {}
            for r, e in zip(rails, device.erasure[op.name]):
                if where[r] in live:
                    pairs.setdefault(pair[live[where[r]]], e)
            for p, e in pairs.items():
                log_keep[p] += math.log1p(-e)
                busy[p].append((start, start + duration))
        if op.name == "swap":
            a, b = rails
            where[a], where[b] = where[b], where[a]
        for r in rails:
            clock[r] = start + duration
    return max(clock), busy, log_keep


def loss_parts(qc, device):
    """From the schedule alone: live pairs n, duration D, summed pair idle time and summed ln(1 - e) of erasures."""
    end, busy, log_keep = _pair_schedule(qc, device)
    return len(busy), end, sum(end - union_length(v) for v in busy.values()), sum(log_keep.values())


def pair_losses(qc, device):
    """Each live pair's expected photon losses, (idle time) / T1 - sum ln(1 - e); they sum to -ln P_keep."""
    end, busy, log_keep = _pair_schedule(qc, device)
    return [(end - union_length(busy[p])) / device.t1 - log_keep[p] for p in busy]


def closed_form(qc, device):
    """P_keep from the schedule alone."""
    n, end, idle_time, log_erasure = loss_parts(qc, device)
    if not device.erasure:
        return math.exp(-n * end / device.t1)
    return math.exp(log_erasure - idle_time / device.t1)


def saved(names):
    from qiskit import qpy

    out = []
    for name in names:
        with (HERE / "data/circuits_n8" / f"{name}.qpy").open("rb") as f:
            out.append(qpy.load(f)[0])
    return out


def scaled(device, k):
    """Every noise rate of ``device`` times ``k``."""
    return dataclasses.replace(
        device, name=f"{device.name}_x{k:g}", t1=device.t1 / k, dephasing=device.dephasing * k,
        pauli_z={g: tuple(k * p for p in v) for g, v in device.pauli_z.items()},
        loss={g: k * p for g, p in device.loss.items()},
        erasure={g: tuple(k * e for e in v) for g, v in device.erasure.items()},
    )


def main() -> None:
    failed = []

    def report(name, value, tolerance):
        ok = value <= tolerance
        failed.extend([] if ok else [name])
        print(f"{name}: {value:.1e} (tolerance {tolerance:g}) {'pass' if ok else 'FAIL'}")

    # 1. Noiseless engine against Statevector.
    worst = 0.0
    for qc in saved(["qft_grid_0_prism", "dj_grid_100_greedy", "qaoa_grid_200_logical"]):
        # The engine skips idle-pair preparations (sim.live_pairs) and heralds, so the reference drops them too.
        _, idle, _ = sim.live_pairs(qc)
        live_only = qc.copy_empty_like()
        for i, ins in enumerate(qc.data):
            if i not in idle and ins.operation.name != "joint_herald":
                live_only.append(ins)
        worst = max(worst, 1 - abs(np.vdot(ideal_rail_vector(qc), Statevector(live_only).data)))
    report("1. noiseless engine vs Statevector, 3 saved circuits, 1 - |overlap|", worst, 1e-12)

    # 2. Noisy engine against the full rail density matrix, both devices, noise x25.
    legacy = dataclasses.replace(sim.LEGACY, loss={"crz": 2e-3})
    cmap = CouplingMap.from_grid(2, 4)
    circuits = [compile_arm(_logical(seed, 3), arm, cmap, seed) for seed, arm in enumerate(ARMS)]
    for device in (scaled(legacy, 25), scaled(sim.MEHTA, 25), scaled(sim.MEHTA_IDLE, 25)):
        worst = 0.0
        for out in circuits:
            engine = sim.simulate_dualrail(out, device)
            p_keep, fidelity = reference(out, device)
            worst = max(worst, abs(engine["p_keep"] - p_keep), abs(engine["fidelity"] - fidelity))
        report(f"2. {device.name}: engine vs full rail density matrix, 3 circuits, max |dP_keep|, |dF|", worst, 1e-6)

    # 3. P_keep against the closed form on 20 saved circuits.
    names = [f"{c}_{t}_{s}_{a}" for c, t, s, a in zip(
        ["qft", "ae", "dj", "hhl", "qaoa", "multiplier", "vqe_two_local", "draper_qft_adder", "qpeexact", "modular_adder"] * 2,
        ["grid"] * 10 + ["hex_lattice"] * 10, [0, 100, 200, 300, 400] * 4, list(ARMS) * 6 + list(ARMS[:2]))]
    circuits = saved(names)
    for device in (dataclasses.replace(sim.LEGACY, loss={}), sim.MEHTA, sim.MEHTA_IDLE):
        worst = max(abs(sim.simulate_dualrail(qc, device)["p_keep"] / closed_form(qc, device) - 1) for qc in circuits)
        report(f"3. {device.name}: P_keep vs closed form, 20 saved circuits, relative", worst, 1e-12)

    # 4. Trajectories against exact at n = 8.
    circuits = saved(["qft_grid_0_prism", "hhl_hex_lattice_100_greedy", "vqe_two_local_grid_200_logical", "ae_hex_lattice_300_prism"])
    for device in (sim.MEHTA, sim.MEHTA_IDLE):
        worst_z = worst_p = 0.0
        for qc in circuits:
            exact = sim.simulate_dualrail(qc, device)
            sampled = sim.simulate_dualrail(qc, device, shots=1000, seed=1)
            worst_z = max(worst_z, abs(sampled["fidelity"] - exact["fidelity"]) / sampled["fidelity_se"])
            worst_p = max(worst_p, abs(sampled["p_keep"] / exact["p_keep"] - 1))
        report(f"4. {device.name}: trajectories vs exact, 4 saved circuits, |dF| / SE", worst_z, 3.0)
        report(f"4. {device.name}: trajectories vs exact, 4 saved circuits, relative dP_keep", worst_p, 1e-12)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
