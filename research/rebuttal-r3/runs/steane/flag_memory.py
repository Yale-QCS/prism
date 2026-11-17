"""Steane memories with delayed erasure flags and compiled per-round joint checks (revision 3, W2).

Usage: flag_memory.py PROTOCOL BASIS ARM SEED [--noise full|table4|published|off] [--shots N] [--out DIR]
PROTOCOL: ideal (published per-site flags), readout (flags at readout only), checks (a compiled joint check
on each data pair in rounds 1 and 2, the final readout being the third), checks3 (a check in all three rounds).
NOISE: full (adds an independent Z on every CR_z target), table4 (instead places half of each CR_z control
loss before the gate, so that the target is dephased only when the control is lost), published, off.
"""
from __future__ import annotations

import argparse
import dataclasses
from functools import lru_cache
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "rebuttal" / "outer_qec"))

import numpy as np  # noqa: E402
import stim  # noqa: E402
from qiskit import QuantumCircuit, qpy  # noqa: E402
from qiskit.quantum_info import Operator  # noqa: E402

import mehta_memory as mm  # noqa: E402
from erasure_pilot import complete_readout_checks, signatures, validate_signatures, with_heralds  # noqa: E402
from to_stim import _OPS, _logical_circuit  # noqa: E402
from marabbecca.synthesis.preparation import ErasureCheckGate  # noqa: E402

TOPO, N_DATA, ROUNDS, SHOTS = "hex_lattice", 7, 3, 50_000
# Added to every dual-rail protocol: Z on the CR_z target, Mehta et al. (arXiv:2503.10935) 0.094(2)% per gate.
CRZ_TARGET_Z = 9.4e-4
# Joint erasure check of de Graaf et al. (arXiv:2406.14621), a different device: 1.82 us pulse, 0.12 us
# beamsplitter ramp, 1 us readout (assumed); 0.51% false positives; 3.7% false negatives; at most 0.12%
# transmon-induced Pauli error, applied as depolarizing. Loss and dephasing over the check use this device's rates.
CHECK_US, CHECK_FP, CHECK_FN, CHECK_DEPOL = 2.94, 5.1e-3, 3.7e-2, 1.2e-3


def xor(a, b):
    """Probability that exactly one of two independent flips occurs."""
    return a + b - 2 * a * b


def device(noise, checks=False):
    """Return the shared Mehta device, with the added CR_z target error and the check channel."""
    d = mm.DEVICE
    if noise in ("full", "off"):
        cz, tz = d.pauli_z["crz"]
        d = dataclasses.replace(d, name="mehta_idle_r3", pauli_z={**d.pauli_z, "crz": (cz, xor(tz, CRZ_TARGET_Z))})
    if checks:
        loss = -math.expm1(-CHECK_US / d.t1)
        d = dataclasses.replace(
            d, name=d.name + "_checks", durations={**d.durations, "joint_check": CHECK_US},
            erasure={**d.erasure, "joint_check": (loss, loss)},
            pauli_z={**d.pauli_z, "joint_check": (-math.expm1(-2 * d.dephasing * CHECK_US) / 2,)})
    return d


def with_checks(qc, rounds):
    """Insert one erasure check on each data qubit after its last two-qubit gate of the given rounds."""
    def data(ins):
        return [i for i in (qc.find_bit(q).index for q in ins.qubits) if i < N_DATA] if ins.operation.name in ("cx", "cz") else []
    total = {}
    for ins in qc.data:
        for i in data(ins):
            total[i] = total.get(i, 0) + 1
    assert all(count % ROUNDS == 0 for count in total.values())
    out, seen = QuantumCircuit(*qc.qregs, *qc.cregs), {}
    for ins in qc.data:
        out.append(ins.operation, ins.qubits, ins.clbits)
        for i in data(ins):
            seen[i] = seen.get(i, 0) + 1
            per_round = total[i] // ROUNDS
            if seen[i] % per_round == 0 and seen[i] // per_round in rounds:
                out.append(ErasureCheckGate(), [i])
    return out


def build(mem, qc, dev, split=False, items=None):
    """Translate a routed circuit to Stim with one TICK per noise site; `items` collects each event (skipgate.py)."""
    items = [] if items is None else items
    events, duration = mm.schedule(qc, dev)
    out, measurements, sites = stim.Circuit(), {}, []
    halved = set()  # (schedule order of the gate's noise event, control pair)
    for e in events:
        if split and e.name == "crz":
            # Mehta et al. Fig. 4b: a control lost during the gate acts as lost before it or after it.
            sites.append(dict(tick=out.num_ticks, qubit=e.wires[0][0], kind="before:crz",
                              erasure=dev.erasure["crz"][0] / 2, pauli_z=0.0, time_us=e.time))
            items.append(("site", len(sites) - 1))
            out.append("TICK")
            halved.add((e.order + 1, e.wires[0][0]))
        if e.erasure or e.pauli_z:
            half = e.name == "gate:crz" and (e.order, e.qubit) in halved
            sites.append(dict(tick=out.num_ticks, qubit=e.qubit, kind=e.name, erasure=e.erasure / (1 + half),
                              pauli_z=e.pauli_z, time_us=e.time))
            items.append(("site", len(sites) - 1))
            out.append("TICK")
        elif e.name == "R":
            items.append(("R", e.qubit))
            out.append("R", [e.qubit])
        elif e.name == "M":
            measurements[e.clbit] = out.num_measurements
            items.append(("M", e.qubit))
            out.append("M", [e.qubit])
        elif e.name not in ("swap", "joint_check"):
            touched = list(dict.fromkeys(w[0] for w in e.wires if w is not None))
            local = {p: i for i, p in enumerate(touched)}
            wires = tuple(None if w is None else (local[w[0]], w[1]) for w in e.wires)
            key = (e.name, tuple(round(float(x), 9) for x in e.op.params))
            _OPS.setdefault(key, Operator(e.op))
            lowered = stim.Circuit()
            for ins in _logical_circuit(key, len(touched), wires):
                lowered.append(ins.name, [touched[t.value] for t in ins.targets_copy()])
            items.append(("ops", lowered, frozenset(touched)))
            out += lowered
    count = out.num_measurements
    for recs in mem.detectors:
        out.append("DETECTOR", [stim.target_rec(measurements[2 * k] - count) for k in recs])
    for i, recs in sorted(mem.observables.items()):
        out.append("OBSERVABLE_INCLUDE", [stim.target_rec(measurements[2 * k] - count) for k in recs], i)
    return complete_readout_checks(out, expected_measurements=mem.n_meas), sites, duration


def score(sites):
    """Published route objective: negative log probability of no erasure or Z event."""
    return sum(-math.log1p(-s["erasure"]) - math.log1p(-s["pauli_z"]) for s in sites)


def with_residuals(base, sites, depol):
    """Add the unflagged Pauli channels after each site's TICK; erasures are left to the sampler."""
    out, k = stim.Circuit(), 0
    for ins in base:
        out.append(ins)
        if ins.name == "TICK":
            s, k = sites[k], k + 1
            if s["pauli_z"]:
                out.append("Z_ERROR", [s["qubit"]], s["pauli_z"])
            if depol and s["kind"] == "gate:joint_check":
                out.append("DEPOLARIZE1", [s["qubit"]], depol)
    return out


def intervals(base, sites):
    """Group each pair's sites by the joint check or readout that next observes the pair."""
    pending, chain, read, out, k = {}, {}, {}, [], 0

    def close(q, at, check):
        out.append(dict(qubit=q, sites=pending.pop(q, []), check=check, at=at, earlier=list(chain.get(q, []))))
        # A readout sees every earlier loss, so nothing carries past it.
        chain[q] = chain.get(q, []) + [len(out) - 1] if check else []

    for at, ins in enumerate(base):
        if ins.name == "TICK":
            q = sites[k]["qubit"]
            pending.setdefault(q, []).append(k)
            if sites[k]["kind"] == "gate:joint_check":
                close(q, at, True)
            k += 1
        elif ins.name == "M":
            read.update({t.value: at for t in ins.targets_copy()})
        elif ins.name == "R":
            # Every readout closes a group, even one with no site. The two rails of a pair can be read at
            # different times; sites up to the later rail belong to that one readout.
            for q in (t.value for t in ins.targets_copy()):
                assert q in read or q not in pending
                if q in read:
                    close(q, read.pop(q), False)
    assert set(pending) <= set(read)
    for q, at in read.items():
        close(q, at, False)
    return out


def sample_flags(noisy, sites, groups, erasure, fp, fn, shots, seed):
    """Sample losses with Stim and report each only at the pair's next joint check or readout.

    Stim does the simulation: `with_heralds` puts a `HERALDED_ERASE` at every loss site, and every joint
    check gets a false-positive herald that leaves the qubit alone, `HERALDED_PAULI_CHANNEL_1(fp,0,0,0)`
    (`HERALDED_ERASE` would also depolarize it: scratch/r3-review2/p1_fp_channel.py). The numpy below ORs
    the heralds of each (pair, interval) group, drops a check's flag with probability `fn`, and carries a
    dropped flag to the pair's next group. No maintained library does that step
    (research/rebuttal-r3/audit/steane-check.md section 6, probes in scratch/r3-audit/steane-check/q6/):
    Stim 1.16 writes a herald at the loss and has no instruction that postpones or drops one
    (stim_probe.py), and a Stim detector is an XOR of records, so it cannot express the OR of an interval's
    heralds or a random miss of that OR. deltakit-stim 0.2.7 has a delayed herald with a miss probability
    (`HERALD_LEAKAGE_EVENT`), but its CZ randomizes the partner of a leaked qubit and it has no
    false-positive argument (deltakit_probe*.py).
    """
    checks = [g["sites"][-1] for g in groups if g["check"]]
    points = [(s["tick"], s["qubit"], s["kind"]) for s in sites]
    points += [points[i] for i in checks]
    nd = noisy.num_detectors
    # with_heralds writes herald detectors in tick order, not list order (erasure_pilot.py:197-201).
    column = {i: nd + j for j, i in enumerate(sorted(range(len(points)), key=lambda i: points[i][0]))}
    false = {i: column[len(sites) + j] for j, i in enumerate(checks)}
    circuit, herald = stim.Circuit(), nd
    for ins in with_heralds(noisy, points, list(erasure) + [fp] * len(checks)):
        pure = ins.name == "HERALDED_ERASE" and herald in false.values()
        herald += ins.name == "HERALDED_ERASE"
        circuit.append("HERALDED_PAULI_CHANNEL_1" if pure else ins.name, ins.targets_copy(), ins.gate_args_copy() + [0, 0, 0] * pure)
    det, obs = circuit.compile_detector_sampler(seed=seed).sample(shots, separate_observables=True)
    rng, carry = np.random.default_rng(seed), {}
    flags = np.zeros((shots, len(groups)), dtype=bool)
    for k, g in enumerate(groups):
        lost = det[:, [column[i] for i in g["sites"]]].any(axis=1) | carry.get(g["qubit"], False)
        flags[:, k] = np.where(lost, rng.random(shots) >= fn, det[:, false[g["sites"][-1]]]) if g["check"] else lost
        carry[g["qubit"]] = lost & ~flags[:, k]
    return det[:, :nd], obs, flags


class IntervalDecoder(mm.Decoder):
    """ldpc BP+OSD told only which pair was found empty and by which check or readout."""

    def __init__(self, columns, n_detectors, sites, groups, fp, fn, depol):
        super().__init__(columns, n_detectors, [s["pauli_z"] for s in sites])
        for i, s in enumerate(sites):
            if depol and s["kind"] == "gate:joint_check":
                for c in self.site_columns[i]:
                    if c >= 0:
                        self.priors[c] = xor(self.priors[c], 2 * depol / 3)
        self.groups, self.fp, self.fn = groups, fp, fn
        self.erasure = [s["erasure"] for s in sites]
        self.predict = lru_cache(maxsize=1 << 18)(self._predict)

    def _predict(self, syndrome_bytes, flags_bytes):
        syndrome = np.frombuffer(syndrome_bytes, dtype=np.uint8)
        flags = np.unpackbits(np.frombuffer(flags_bytes, dtype=np.uint8), count=len(self.groups))
        priors = self.priors.copy()
        for k in np.flatnonzero(flags):
            # A flag means one loss in this interval, a false positive of its check (no fault), or a loss in
            # an earlier interval that every check since then missed (so none of those checks raised a flag).
            g = self.groups[k]
            share = {i: self.erasure[i] for i in g["sites"]}
            for age, j in enumerate(reversed(g["earlier"]), 1):
                if flags[j]:
                    break
                share.update({i: self.erasure[i] * self.fn**age for i in self.groups[j]["sites"]})
            # The (1 - fn) chance that a check sees a loss scales every loss term against its false positives.
            total = sum(share.values()) + (self.fp / (1 - self.fn) if g["check"] else 0.0)
            for i, e in share.items():
                for c in self.site_columns[i]:
                    if c >= 0 and total:
                        priors[c] = xor(priors[c], e / total / 2)
        self.decoder.update_channel_probs(priors)
        correction = self.decoder.decode(syndrome)
        if correction[priors == 0].any() or not np.array_equal(self.checks @ correction % 2, syndrome):
            return 2  # no explanation within the model: scored as a logical error
        return int(self.logical @ correction % 2)

    def decode(self, syndromes, flags):
        result = np.zeros(len(syndromes), dtype=np.int8)
        packed = np.packbits(flags, axis=1)
        for i in np.flatnonzero(syndromes.any(axis=1)):
            result[i] = self.predict(syndromes[i].astype(np.uint8).tobytes(), packed[i].tobytes())
        return result


def routed(protocol, basis, arm, seed, out):
    """Return the published route, or compile (once) the route with per-round checks."""
    mem = mm.memory(basis)
    checks = protocol.startswith("checks")
    path = out / f"routes_{protocol}" / f"{basis}_{arm}_{seed}.qpy" if checks else mm.OUTPUT / f"{basis}_{TOPO}_{arm}_{seed}.qpy"
    if not path.exists():
        dev = device("full", checks=True)
        pm = mm.build_pm(mm.make_topologies(mem.qc.num_qubits)[TOPO], enc=mm.DualRail, strategy=arm, seed=seed,
                         budget=mm.SearchBudget(objective="custom", **mm.BUDGET), objective="custom",
                         route_score=lambda qc: sum(-math.log1p(-e.erasure) - math.log1p(-e.pauli_z)
                                                    for e in mm.schedule(qc, dev)[0]),
                         reschedule=False)
        qc = pm.run(with_checks(mem.qc, (1, 2, 3) if protocol == "checks3" else (1, 2)))
        qc._layout = None  # QPY cannot serialize the encoded virtual-register layout.
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as stream:
            qpy.dump(qc, stream)
    with path.open("rb") as stream:
        return mem, qpy.load(stream)[0]


def run(protocol, basis, arm, seed, noise, shots, out):
    """Decode one cell and write its row."""
    started = time.monotonic()
    path = out / f"rows_{noise}" / f"{protocol}_{basis}_{arm}_{seed}.json"
    if path.exists():
        return
    mem, qc = routed(protocol, basis, arm, seed, out)
    compiled = time.monotonic() - started
    dev = device(noise, checks=protocol.startswith("checks"))
    base, sites, duration = build(mem, qc, dev, split=noise == "table4")
    det, obs = base.compile_detector_sampler(seed=0).sample(256, separate_observables=True)
    assert not det.any() and not obs.any()
    points = [(s["tick"], s["qubit"], s["kind"]) for s in sites]
    columns = signatures(base, points)
    validate_signatures(base, points, columns)
    nd, on = base.num_detectors, noise != "off"
    erasure = [s["erasure"] if on else 0.0 for s in sites]
    phase = [s["pauli_z"] if on else 0.0 for s in sites]
    # "published" keeps the published per-arm Stim seed; otherwise both arms of a routing seed share one.
    name = f"{basis}_{TOPO}_{arm}_{seed}" if noise == "published" else f"r3_{basis}_{seed}"
    rng = int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "little")
    errors = flagged = unexplained = 0
    if protocol == "ideal":
        decoder = mm.Decoder(columns, nd, [s["pauli_z"] for s in sites])
        sampler = with_heralds(base, points, erasure, phase).compile_detector_sampler(seed=rng)
        for start in range(0, shots, 10_000):
            det, obs = sampler.sample(min(10_000, shots - start), separate_observables=True)
            errors += int(np.count_nonzero(decoder.decode(det[:, :nd], det[:, nd:]) != obs[:, 0]))
            flagged += int(np.count_nonzero(det[:, nd:].any(axis=1)))
        n_flags = len(sites)
    else:
        fp, fn, depol = (CHECK_FP, CHECK_FN, CHECK_DEPOL) if on else (0.0, 0.0, 0.0)
        groups = intervals(base, sites)
        decoder = IntervalDecoder(columns, nd, sites, groups, CHECK_FP, CHECK_FN, CHECK_DEPOL)
        noisy = with_residuals(base, [dict(s, pauli_z=p) for s, p in zip(sites, phase)], depol)
        det, obs, flags = sample_flags(noisy, sites, groups, erasure, fp, fn, shots, rng % 2**63)
        prediction = decoder.decode(det, flags)
        errors = int(np.count_nonzero(prediction != obs[:, 0]))
        unexplained = int(np.count_nonzero(prediction == 2))
        flagged = int(np.count_nonzero(flags.any(axis=1)))
        n_flags = len(groups)
    ops = qc.count_ops()
    row = dict(protocol=protocol, noise=noise, basis=basis, topo=TOPO, arm=arm, seed=seed, shots=shots, errors=errors,
               logical_error=errors / shots, flagged_shots=flagged, unexplained=unexplained, n_sites=len(sites),
               n_flags=n_flags, swaps=ops.get("swap", 0), joint_checks=ops.get("joint_check", 0),
               crz=ops.get("crz", 0), rswap=ops.get("rswap", 0), duration_us=duration, score=score(sites),
               rng_seed=rng, device=dataclasses.asdict(dev),
               check=dict(us=CHECK_US, fp=CHECK_FP, fn=CHECK_FN, depol=CHECK_DEPOL) if protocol.startswith("checks") else None,
               decoder="ldpc.BpOsdDecoder/OSD_CS/serial, 7 iterations, order 2",
               versions={pkg: version(pkg) for pkg in ("qiskit", "qldpc", "stim", "ldpc", "numpy")},
               compile_seconds=compiled, seconds=time.monotonic() - started)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol", choices=("ideal", "readout", "checks", "checks3"))
    parser.add_argument("basis", choices=("X", "Z"))
    parser.add_argument("arm", choices=mm.ARMS)
    parser.add_argument("seed", type=int)
    parser.add_argument("--noise", choices=("full", "table4", "published", "off"), default="full")
    parser.add_argument("--shots", type=int, default=SHOTS)
    parser.add_argument("--out", type=Path, default=HERE)
    args = parser.parse_args()
    run(args.protocol, args.basis, args.arm, args.seed, args.noise, args.shots, args.out)
