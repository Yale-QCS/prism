"""Steane memories with the shared MEHTA_IDLE device, Stim and ldpc decoding."""
from __future__ import annotations

import argparse
import dataclasses
from functools import lru_cache
import hashlib
from importlib.metadata import version
import itertools
import json
import math
import os
from pathlib import Path
import subprocess
import time

os.environ.setdefault("NUMBA_CACHE_DIR", "/tmp/prism-qec-numba")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("RAYON_NUM_THREADS", "1")
os.environ.setdefault("QISKIT_PARALLEL", "FALSE")

import numpy as np
import stim
from ldpc import BpOsdDecoder
from qiskit import qpy
from qiskit.quantum_info import Operator

from erasure_pilot import (memory, complete_readout_checks, signatures,
                           validate_signatures, with_heralds, SEEDS)
from route import REPO, BUDGET, make_topologies, build_pm, SearchBudget, DualRail
from to_stim import _logical_circuit, _OPS, sim
from marabbecca.utils.metrics import is_synthetic_preparation

DEVICE = sim.MEHTA_IDLE
DIRECTORY = Path(__file__).resolve().parent
OUTPUT = DIRECTORY / "data" / "mehta_memory"
SHOTS = 50_000
ARMS = ("greedy", "prism")


@dataclasses.dataclass
class Event:
    """An encoded action or a channel at a physical schedule boundary."""
    time: float
    order: int
    name: str
    wires: tuple = ()
    op: object = None
    clbit: int | None = None
    qubit: int | None = None
    erasure: float = 0.0
    pauli_z: float = 0.0
    idle_us: float = 0.0


def schedule(qc, device=DEVICE):
    """Build the same gate and idle channels for route scoring and simulation."""
    assert device.idle_dephasing and device.erasure and not device.loss
    at = [None] * qc.num_qubits
    clock = [0.0] * qc.num_qubits
    current, epochs, actions, gate_noise = {}, [], [], []
    n_pairs = 0
    for i, ins in enumerate(qc.data):
        op, name = ins.operation, ins.operation.name
        if name == "barrier":
            continue
        rails = [qc.find_bit(q).index for q in ins.qubits]
        start = max(clock[r] for r in rails)
        synthetic = is_synthetic_preparation(op)
        if synthetic and name != "joint_herald":
            continue
        duration = 0.0 if synthetic or name == "measure" else device.durations[name]
        end = start + duration
        for r in rails:
            clock[r] = end
        wires = tuple(at[r] for r in rails)
        if name == "joint_herald":
            a, b = wires
            if a is None and b is None:
                p = n_pairs
                n_pairs += 1
            else:
                assert a is not None and b is not None and a[0] == b[0], wires
                p = a[0]
                current[p]["end"] = current[p]["measured"] if current[p]["measured"] is not None else start
            epoch = dict(qubit=p, start=start, end=None, measured=None, busy=[])
            epochs.append(epoch)
            current[p] = epoch
            at[rails[0]], at[rails[1]] = (p, 0), (p, 1)
            actions.append(Event(end, 4*i+2, "R", qubit=p))
            continue
        touched = {w[0] for w in wires if w is not None}
        if name == "measure":
            p = wires[0][0]
            current[p]["measured"] = max(end, current[p]["measured"] or end)
            actions.append(Event(end, 4*i+2, "M", qubit=p,
                                 clbit=qc.find_bit(ins.clbits[0]).index))
            continue
        actions.append(Event(end, 4*i+2, name, wires=wires, op=op))
        for p in touched:
            if duration:
                current[p]["busy"].append((start, end))
        if name == "swap":
            a, b = rails
            at[a], at[b] = at[b], at[a]
        # Match the shared simulator: gate residuals attach to the output rails.
        erasures, phases = {}, {}
        for r, prob in zip(rails, device.erasure.get(name, ())):
            if at[r] is not None:
                erasures.setdefault(at[r][0], prob)
        for r, prob in zip(rails, device.pauli_z.get(name, ())):
            if at[r] is not None:
                p = at[r][0]
                old = phases.get(p, 0.0)
                phases[p] = old + prob - 2 * old * prob
        for p in erasures.keys() | phases.keys():
            gate_noise.append((current[p], Event(end, 4*i+3, f"gate:{name}", qubit=p,
                                                erasure=erasures.get(p, 0.0),
                                                pauli_z=phases.get(p, 0.0))))
    finish = max(clock, default=0.0)
    for epoch in epochs:
        if epoch["end"] is None:
            epoch["end"] = epoch["measured"] if epoch["measured"] is not None else finish
    for epoch, event in gate_noise:
        if event.time <= epoch["end"] + 1e-10:
            actions.append(event)
    for epoch in epochs:
        start, end = epoch["start"], epoch["end"]
        reach = start
        gaps = []
        for a, b in sorted(epoch["busy"]):
            a, b = max(start, a), min(end, b)
            if a > end or b < start:
                continue
            if a > reach:
                gaps.append((reach, a))
            reach = max(reach, b)
        if reach < end:
            gaps.append((reach, end))
        for a, b in gaps:
            dt = b-a
            actions.append(Event(b, -1, "idle", qubit=epoch["qubit"], idle_us=dt,
                                 erasure=-math.expm1(-dt/device.t1),
                                 pauli_z=-math.expm1(-2*device.dephasing*dt)/2))
    return sorted(actions, key=lambda e: (e.time, e.order)), finish


def mehta_score(qc):
    """Negative log probability of no erasure or Z event in the simulated channel."""
    events, _ = schedule(qc)
    return sum(-math.log1p(-e.erasure)-math.log1p(-e.pauli_z) for e in events)


def circuit(mem, qc):
    """Translate the routed Clifford circuit, retaining timed noise locations."""
    assert not mem.pre and not mem.post and not mem.tags
    events, duration = schedule(qc)
    out = stim.Circuit()
    measurements, sites = {}, []
    for e in events:
        if e.erasure or e.pauli_z:
            sites.append(dict(tick=out.num_ticks, qubit=e.qubit, kind=e.name,
                              erasure=e.erasure, pauli_z=e.pauli_z, time_us=e.time,
                              idle_us=e.idle_us))
            out.append("TICK")
        elif e.name == "R":
            out.append("R", [e.qubit])
        elif e.name == "M":
            measurements[e.clbit] = out.num_measurements
            out.append("M", [e.qubit])
        elif e.name != "swap":
            touched = list(dict.fromkeys(w[0] for w in e.wires if w is not None))
            local = {p: i for i, p in enumerate(touched)}
            wires = tuple(None if w is None else (local[w[0]], w[1]) for w in e.wires)
            key = (e.name, tuple(round(float(x), 9) for x in e.op.params))
            _OPS.setdefault(key, Operator(e.op))
            for ins in _logical_circuit(key, len(touched), wires):
                out.append(ins.name, [touched[t.value] for t in ins.targets_copy()])
    count = out.num_measurements
    for recs in mem.detectors:
        out.append("DETECTOR", [stim.target_rec(measurements[2*k]-count) for k in recs])
    for i, recs in sorted(mem.observables.items()):
        out.append("OBSERVABLE_INCLUDE", [stim.target_rec(measurements[2*k]-count) for k in recs], i)
    out = complete_readout_checks(out, expected_measurements=mem.n_meas)
    points = [(s["tick"], s["qubit"], s["kind"]) for s in sites]
    noisy = with_heralds(out, points, [s["erasure"] for s in sites], [s["pauli_z"] for s in sites])
    cost = sum(-math.log1p(-s["erasure"])-math.log1p(-s["pauli_z"]) for s in sites)
    assert math.isclose(cost, mehta_score(qc), rel_tol=1e-12)
    return out, noisy, points, sites, duration, cost


class Decoder:
    """ldpc BP+OSD with per-shot erasure priors and shared-device residual errors."""
    def __init__(self, columns, n_detectors, phase_probs):
        self.columns = columns
        values = np.array(sorted(set(columns.flat)-{0}), dtype=np.int64)
        index = {int(v): i for i, v in enumerate(values)}
        self.site_columns = np.array([[index.get(int(v), -1) for v in pair] for pair in columns])
        self.checks = ((values[None, :] >> np.arange(1, n_detectors+1)[:, None]) & 1).astype(np.uint8)
        self.logical = (values & 1).astype(np.uint8)
        self.priors = np.zeros(len(values))
        for pair, pz in zip(columns, phase_probs):
            if pair[1]:
                i = index[int(pair[1])]
                old = self.priors[i]
                self.priors[i] = old + pz - 2*old*pz
        # Use the serial BP/OSD example from ldpc's quantum-decoder documentation.
        self.decoder = BpOsdDecoder(self.checks, error_channel=self.priors.tolist(), max_iter=7,
                                   bp_method="product_sum", schedule="serial",
                                   osd_method="OSD_CS", osd_order=2)
        self.predict = lru_cache(maxsize=65_536)(self._predict)

    def _predict(self, syndrome_bytes, flags_bytes):
        syndrome = np.frombuffer(syndrome_bytes, dtype=np.uint8)
        flags = np.unpackbits(np.frombuffer(flags_bytes, dtype=np.uint8), count=len(self.columns))
        priors = self.priors.copy()
        active = self.site_columns[np.flatnonzero(flags)].ravel()
        priors[active[active >= 0]] = 0.5
        self.decoder.update_channel_probs(priors)
        correction = self.decoder.decode(syndrome)
        assert not correction[priors == 0].any()
        assert np.array_equal(self.checks @ correction % 2, syndrome)
        return int(self.logical @ correction % 2)

    def decode(self, syndromes, flags):
        result = np.zeros(len(syndromes), dtype=np.bool_)
        packed = np.packbits(flags, axis=1)
        for i in np.flatnonzero(syndromes.any(axis=1)):
            result[i] = self.predict(syndromes[i].astype(np.uint8).tobytes(), packed[i].tobytes())
        return result

    def check_single_residuals(self, phase_probs):
        """Require every supported single residual fault to be distinguishable and corrected."""
        supported = np.asarray(phase_probs) > 0
        possible = {0} | {int(v) for v in self.columns[supported, 1]}
        assert not any(v^1 in possible for v in possible)
        syndrome = ((self.columns[:, 1, None] >> np.arange(1, len(self.checks)+1)) & 1).astype(bool)
        flags = np.zeros((len(self.columns), len(self.columns)), dtype=bool)
        wrong = self.decode(syndrome, flags) != (self.columns[:, 1] & 1)
        assert not wrong[supported].any()
        return int(supported.sum())


def check():
    """Compare the scheduled channels with the existing exact device simulator."""
    from qiskit import QuantumCircuit
    from qiskit.quantum_info import DensityMatrix, Statevector
    from marabbecca.synthesis.rswap import RSwapGate

    differences = []
    for seed in range(12):
        rng = np.random.default_rng(seed)
        qc = QuantumCircuit(8)
        where = list(range(8))
        for p in range(3):
            qc.compose(DualRail.initialize(), [2*p, 2*p+1], inplace=True)
            qc.append(RSwapGate(math.pi/2), [2*p, 2*p+1])
        for _ in range(24):
            kind = rng.integers(3)
            if kind == 0:
                p, q = rng.choice(3, 2, replace=False)
                qc.crz(math.pi, where[2*p+rng.integers(2)], where[2*q+rng.integers(2)])
            elif kind == 1:
                p = rng.integers(3)
                qc.append(RSwapGate(math.pi/2), [where[2*p], where[2*p+1]])
            else:
                a, b = rng.choice(8, 2, replace=False)
                qc.swap(where[a], where[b])
                where[a], where[b] = where[b], where[a]
        events, duration = schedule(qc)
        ideal = Statevector.from_label('000')
        rho = DensityMatrix(ideal)
        keep = 1.0
        for e in events:
            if e.erasure or e.pauli_z:
                keep *= 1-e.erasure
                if e.pauli_z:
                    zrho = rho.evolve(Operator(np.diag([1., -1.])), [e.qubit])
                    rho = DensityMatrix((1-e.pauli_z)*rho.data + e.pauli_z*zrho.data)
            elif e.name not in ('R', 'swap'):
                touched = list(dict.fromkeys(w[0] for w in e.wires if w is not None))
                local = {p: i for i, p in enumerate(touched)}
                wires = tuple(None if w is None else (local[w[0]], w[1]) for w in e.wires)
                key = (e.name, tuple(round(float(x), 9) for x in e.op.params))
                _OPS.setdefault(key, Operator(e.op))
                unitary = stim.Tableau.from_circuit(_logical_circuit(key, len(touched), wires))
                op = Operator(unitary.to_unitary_matrix(endian='little'))
                rho = rho.evolve(op, touched)
                ideal = ideal.evolve(op, touched)
        fidelity = float((ideal.data.conj() @ rho.data @ ideal.data).real)
        reference = sim.simulate_dualrail(qc, DEVICE)
        delta = max(abs(keep-reference['p_keep']), abs(fidelity-reference['fidelity']),
                    abs(duration-reference['duration_us']))
        assert delta < 3e-6, (seed, delta, keep, fidelity, reference)
        differences.append(delta)
    result = dict(circuits=12, device=dataclasses.asdict(DEVICE),
                  max_exact_difference=max(differences), tolerance=3e-6)
    print(json.dumps(result), flush=True)
    return result


def run(basis, topo, arm, seed, output=OUTPUT, shots=SHOTS):
    """Compile and decode one prescribed circuit at the shared nominal device point."""
    started = time.monotonic()
    cell = f"{basis}_{topo}_{arm}_{seed}"
    output.mkdir(parents=True, exist_ok=True)
    path = output / f"{cell}.json"
    if path.exists():
        raise FileExistsError(path)
    mem = memory(basis)
    cmap = make_topologies(mem.qc.num_qubits)[topo]
    pm = build_pm(cmap, enc=DualRail, strategy=arm, seed=seed,
                  budget=SearchBudget(objective="custom", **BUDGET), objective="custom",
                  route_score=mehta_score, reschedule=False)
    qc = pm.run(mem.qc)
    base, noisy, points, sites, duration, cost = circuit(mem, qc)
    trace = pm.property_set["search_trace"]
    winning_score = trace["starts"][trace["winning"]["trial"]]["final_score"]
    assert math.isclose(cost, winning_score[0], rel_tol=1e-12)
    base.detector_error_model()
    det, obs = base.compile_detector_sampler(seed=0).sample(256, separate_observables=True)
    assert not det.any() and not obs.any()
    columns = signatures(base, points)
    validate_signatures(base, points, columns)
    decoder = Decoder(columns, base.num_detectors, [s["pauli_z"] for s in sites])
    single_checks = decoder.check_single_residuals([s["pauli_z"] for s in sites])
    rng = int.from_bytes(hashlib.sha256(cell.encode()).digest()[:8], "little")
    sampler = noisy.compile_detector_sampler(seed=rng)
    errors, heralded = 0, 0
    for start in range(0, shots, 10_000):
        det, obs = sampler.sample(min(10_000, shots-start), separate_observables=True)
        nd = base.num_detectors
        prediction = decoder.decode(det[:, :nd], det[:, nd:])
        errors += int(np.count_nonzero(prediction != obs[:, 0]))
        heralded += int(np.count_nonzero(det[:, nd:].any(axis=1)))
    row = dict(protocol="mehta-memory-v2", code="steane", rounds=3, basis=basis,
               topo=topo, arm=arm, seed=seed, shots=shots, errors=errors,
               logical_error=errors/shots, heralded_shots=heralded,
               objective="mehta_no_fault", score=cost, budget=BUDGET, reschedule=False,
               device=dataclasses.asdict(DEVICE), duration_us=duration,
               metrics=dataclasses.asdict(pm.property_set["circuit_metrics"]),
               winning_score=winning_score,
               sites=sites, columns=columns.tolist(), n_detectors=base.num_detectors,
               decoder="ldpc.BpOsdDecoder/OSD_CS/serial", bp_iterations=7, osd_order=2,
               single_residual_faults_checked=single_checks, single_residual_faults_failed=0,
               versions={pkg: version(pkg) for pkg in ("qiskit", "qldpc", "stim", "ldpc")},
               rng_seed=rng, checked_fault_columns=2*len(sites), noiseless_shots=256,
               commit=subprocess.check_output(["git", "rev-parse", "HEAD"],cwd=REPO,text=True).strip(),
               source_sha256={str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in [Path(__file__), DIRECTORY/'erasure_pilot.py', DIRECTORY/'to_stim.py', DIRECTORY/'route.py',
                                        DIRECTORY/'qec_circuits.py', Path(sim.__file__),
                                        REPO/'src/marabbecca/lowering/commit.py',
                                        REPO/'src/marabbecca/lowering/commit_policies/prism_routing.py',
                                        REPO/'src/marabbecca/staged_pms.py']},
               seconds=time.monotonic()-started)
    (output/f"{cell}.stim").write_text(str(noisy)+"\n")
    (output/f"{cell}.ideal.stim").write_text(str(base)+"\n")
    with (output/f"{cell}.qpy").open('wb') as stream:
        saved = qc.copy()
        saved._layout = None  # QPY cannot serialize the encoded virtual-register layout.
        qpy.dump(saved, stream)
    path.write_text(json.dumps(row, indent=2)+"\n")
    print(json.dumps({k: row[k] for k in ('basis','topo','arm','seed','shots','errors','logical_error','score','seconds')}),flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--basis', choices=('X','Z'))
    parser.add_argument('--topo', choices=('grid','hex_lattice'))
    parser.add_argument('--arm', choices=ARMS)
    parser.add_argument('--seed', type=int, choices=SEEDS)
    parser.add_argument('--shots', type=int, default=SHOTS)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--tasks', action='store_true')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.check:
        check()
    elif args.tasks:
        for basis, topo, arm, seed in itertools.product(('X','Z'),('grid','hex_lattice'),ARMS,SEEDS):
            if not (args.output/f'{basis}_{topo}_{arm}_{seed}.json').exists():
                print(f'--basis {basis} --topo {topo} --arm {arm} --seed {seed}')
    else:
        if None in (args.basis,args.topo,args.arm,args.seed):
            parser.error('provide --basis, --topo, --arm and --seed, or --tasks')
        run(args.basis,args.topo,args.arm,args.seed,args.output,args.shots)
