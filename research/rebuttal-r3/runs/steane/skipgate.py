"""Steane memories under skip-gate leakage (Pavlovich et al., arXiv:2607.29443, Secs. II.1-II.2).

Usage: skipgate.py PROTOCOL BASIS ARM SEED [--shots N] [--out DIR]
A lost pair stays empty until a joint check detects it (missing it with probability 3.7%) or until its readout.
While empty, every event on it does nothing (a CR_z or R_SWAP touching it, and its noise); at detection it
returns completely mixed. Loss sites, rates and the table4 control split are those of flag_memory.py.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import time

import numpy as np
import stim

import flag_memory as fm
from erasure_pilot import signatures, validate_signatures

BLOCK = 10_000


@dataclasses.dataclass
class Cell:
    """One routed memory with its Stim circuit, events, noise sites and flag groups."""
    base: stim.Circuit
    items: list
    sites: list
    groups: list
    duration: float


def cell(protocol, basis, arm, seed, out=fm.HERE):
    """Build the table4 circuit with its event list and flag groups."""
    mem, qc = fm.routed(protocol, basis, arm, seed, out)
    items = []
    base, sites, duration = fm.build(mem, qc, fm.device("table4", checks=protocol.startswith("checks")), True, items)
    return Cell(base, items, sites, fm.intervals(base, sites), duration)


def detector_bits(c, shots):
    """Pack detection events and the observable as columns are packed: L0 in bit 0, detector d in bit d + 1."""
    det, obs = c.base.compile_m2d_converter().convert(measurements=shots, separate_observables=True)
    weights = 1 << np.arange(1, det.shape[1] + 1, dtype=np.int64)
    return (det.astype(np.int64) @ weights) | obs[:, 0].astype(np.int64)


def removed(c, losses):
    """The Stim circuit in which each (site, qubit, check) loss empties its pair: the pair's events are removed until
    the check site `check` (or, with None, the pair's next readout or reset), where it is reset completely mixed."""
    out, empty = stim.Circuit(), {}
    for item in c.items:
        kind = item[0]
        if kind == "site":
            out.append("TICK")
            empty.update({q: check for site, q, check in losses if site == item[1]})
            for q in [q for q, check in empty.items() if check == item[1]]:
                out.append("DEPOLARIZE1", [q], 0.75)
                empty.pop(q)
        elif kind == "ops":
            if not item[2] & empty.keys():
                out += item[1]
        else:
            if item[1] in empty:
                if kind == "M":
                    out.append("DEPOLARIZE1", [item[1]], 0.75)
                empty.pop(item[1])
            out.append(kind, [item[1]])
    return out


def envelopes(c):
    """Per flag group, the Pauli envelope columns of every leak location it can report.

    For a group and each site of its chain (its own sites and those of earlier groups whose checks it follows),
    `removed` gives the circuit with the pair's events deleted from the site to the group's detection point.
    Stim's detector error model of that circuit, under the routed circuit's detectors and with the observable as
    one more detector (`allow_gauge_detectors=True`), lists its fault and gauge mechanisms; the routed circuit's
    converter applied to its reference sample gives the offset. Each distinct vector is a column, returned with the
    chain positions whose envelope contains it. No basis is chosen, so nothing depends on a seed.
    """
    nd = c.base.num_detectors
    tail = stim.Circuit()
    for name in ("DETECTOR", "OBSERVABLE_INCLUDE"):  # the observable last, as detector nd (readout checks follow it)
        for ins in c.base:
            if ins.name == name:
                tail.append("DETECTOR", ins.targets_copy())
    out = []
    for k, g in enumerate(c.groups):
        chain = [i for j in g["earlier"] for i in c.groups[j]["sites"]] + g["sites"]
        check = g["sites"][-1] if g["check"] else None
        where = {}
        for pos in range(len(chain)):
            circuit = removed(c, [(chain[pos], g["qubit"], check)])
            values = [sum(1 << (0 if t.val == nd else t.val + 1) for t in ins.targets_copy() if t.is_relative_detector_id())
                      for ins in (circuit + tail).detector_error_model(allow_gauge_detectors=True) if ins.type == "error"]
            values.append(int(detector_bits(c, np.array([circuit.reference_sample()], dtype=bool))[0]))
            for v in set(values) - {0}:
                where.setdefault(v, []).append(pos)
        out.append(dict(chain=chain, columns=sorted(where.items())))
    return out


def sample(c, erasure, phase, depol, fp, fn, shots, seed):
    """Sample skip-gate leakage shot by shot with Stim's TableauSimulator.

    No maintained library runs this model. Stim 1.16 has no leakage state; its frame simulators apply Pauli
    errors to a fixed circuit, and skipping a gate is not one. deltakit-stim 0.2.7 randomizes a leaked
    qubit's CZ partner (research/rebuttal-r3/audit/steane-check.md section 6). leakysim 0.5.0 skips only the
    two-qubit instruction with a leaked operand: when the CR_z target is leaked, the lowering's S on the intact
    control still runs, a non-Pauli error that no leakysim Pauli channel can undo
    (scratch/skipgate-review/p6.py: 1012/2000 control X-basis flips where the skipped event gives 0).
    So this loop applies each event (`build` items) unless it touches an empty pair. Every flag, true or false,
    resets its pair completely mixed. Shots with no fault and no false flag give no detection events.
    Returns detection events, observables and flags (one per group, in `intervals` order).
    """
    n, groups = len(c.sites), c.groups
    qubit = np.array([s["qubit"] for s in c.sites])
    is_check = np.array([s["kind"] == "gate:joint_check" for s in c.sites])
    group_of, after = {}, {}
    for k, g in enumerate(groups):
        group_of.update({i: k for i in g["sites"]})
        later = [j for j in range(k + 1, len(groups)) if groups[j]["qubit"] == g["qubit"]]
        after[k] = later[0] if later else None
    ticks = [i for i, ins in enumerate(c.base) if ins.name == "TICK"]
    stop = next(i for i, ins in enumerate(c.base) if ins.name in ("DETECTOR", "OBSERVABLE_INCLUDE"))
    bounds = [0] + [t + 1 for t in ticks], ticks + [stop]  # gap j runs up to site j
    gaps, touched, j = [[] for _ in range(n + 1)], [set() for _ in range(n + 1)], 0
    for item in c.items:
        if item[0] == "site":
            j += 1
        else:
            gaps[j].append(item)
            touched[j] |= item[2] if item[0] == "ops" else {item[1]}
    depol = np.where(is_check, depol, 0.0)
    rng = np.random.default_rng(seed)
    det = np.zeros((shots, c.base.num_detectors), dtype=bool)
    obs = np.zeros((shots, 1), dtype=bool)
    flags = np.zeros((shots, len(groups)), dtype=bool)
    paulis = (None, "x", "y", "z")
    for start in range(0, shots, BLOCK):
        size = min(BLOCK, shots - start)
        lost = rng.random((size, n)) < erasure
        flip_z = rng.random((size, n)) < phase
        flip_d = rng.integers(1, 4, (size, n)) * (rng.random((size, n)) < depol)
        missed = rng.random((size, len(groups))) < fn
        false = rng.random((size, len(groups))) < fp
        mixed = rng.integers(0, 4, (size, n + c.base.num_measurements))
        seeds = rng.integers(0, 2**63, size)
        for k, g in enumerate(groups):
            if g["check"]:
                flags[start:start + size, k] = false[:, k]  # replaced below where the pair is empty
        records, rows = [], []
        false_at = np.zeros((size, n), dtype=bool)
        for k, g in enumerate(groups):
            if g["check"]:
                false_at[:, g["sites"][-1]] = false[:, k]
        for b in np.flatnonzero((lost | flip_z | (flip_d > 0) | false_at).any(axis=1)):
            sim = stim.TableauSimulator(seed=int(seeds[b]))
            sim.set_num_qubits(c.base.num_qubits)
            empty, row = set(), start + b

            def reset(q, k):
                if paulis[mixed[b, k]]:
                    getattr(sim, paulis[mixed[b, k]])(q)
                empty.discard(q)

            def run(lo, hi):
                if lo >= hi:
                    return
                if not empty:
                    sim.do_circuit(c.base[bounds[0][lo]:bounds[1][hi - 1]])
                    return
                for gap in range(lo, hi):
                    if not touched[gap] & empty:
                        sim.do_circuit(c.base[bounds[0][gap]:bounds[1][gap]])
                        continue
                    for item in gaps[gap]:
                        if item[0] == "ops":
                            if not item[2] & empty:
                                sim.do_circuit(item[1])
                        elif item[0] == "M":
                            if item[1] in empty:
                                reset(item[1], n + len(sim.current_measurement_record()))
                            sim.do_circuit(stim.Circuit(f"M {item[1]}"))
                        else:
                            empty.discard(item[1])
                            sim.do_circuit(stim.Circuit(f"R {item[1]}"))

            at = 0
            events = np.flatnonzero(lost[b] | flip_z[b] | (flip_d[b] > 0) | is_check)
            for k in events:
                run(at, k + 1)
                at, q = k + 1, int(qubit[k])
                if lost[b, k] and q not in empty:
                    empty.add(q)
                    if not groups[group_of[k]]["check"]:
                        flags[row, group_of[k]] = True  # a readout always finds an empty pair
                if is_check[k] and q in empty:
                    g = group_of[k]
                    flags[row, g] = not missed[b, g]
                    if missed[b, g]:
                        if after[g] is not None and not groups[after[g]]["check"]:
                            flags[row, after[g]] = True
                    else:
                        reset(q, k)
                elif is_check[k] and false[b, group_of[k]]:
                    reset(q, k)  # the hardware cannot tell a false flag from a true one
                if q not in empty:
                    if flip_z[b, k]:
                        sim.z(q)
                    if flip_d[b, k]:
                        getattr(sim, paulis[flip_d[b, k]])(q)
            run(at, n + 1)
            records.append(sim.current_measurement_record())
            rows.append(row)
        if rows:
            d, o = c.base.compile_m2d_converter().convert(measurements=np.array(records, dtype=bool),
                                                          separate_observables=True)
            det[rows], obs[rows] = d, o
    return det, obs, flags


class SkipDecoder(fm.IntervalDecoder):
    """IntervalDecoder whose flagged groups open their envelope columns with a disjoint first-loss prior."""

    def __init__(self, columns, envelope, n_detectors, sites, groups, fp, fn, depol):
        values = [v for e in envelope for v, _ in e["columns"]]
        extra = np.array([[v, 0] for v in values], dtype=np.int64).reshape(-1, 2)
        pad = [dict(pauli_z=0.0, kind="envelope", erasure=0.0)] * len(values)
        super().__init__(np.vstack([columns, extra]), n_detectors, sites + pad, groups, fp, fn, depol)
        self.envelope, offset = envelope, len(sites)
        for e in envelope:
            e["index"] = [self.site_columns[offset + i, 0] for i in range(len(e["columns"]))]
            offset += len(e["columns"])

    def _predict(self, syndrome_bytes, flags_bytes):
        syndrome = np.frombuffer(syndrome_bytes, dtype=np.uint8)
        flags = np.unpackbits(np.frombuffer(flags_bytes, dtype=np.uint8), count=len(self.groups))
        priors = self.priors.copy()
        for k in np.flatnonzero(flags):
            # The pair is lost at most once before this flag. The window runs back over earlier intervals whose
            # checks all missed (factor fn each), to the last one that raised a flag.
            g, e = self.groups[k], self.envelope[k]
            window = [(0, k)]
            for age, j in enumerate(reversed(g["earlier"]), 1):
                if flags[j]:
                    break
                window.append((age, j))
            share, survive = {}, 1.0
            for age, j in reversed(window):
                for i in self.groups[j]["sites"]:
                    share[i] = self.erasure[i] * survive * self.fn**age
                    survive *= 1 - self.erasure[i]
            total = sum(share.values()) + (self.fp / (1 - self.fn) if g["check"] else 0.0)
            # The pair was lost at one location of the window (disjoint), and each mechanism of that location's
            # envelope is present with probability 1/2. Every flag resets the pair, so the check site's own
            # mechanisms (the reset, last in the chain) also carry the false-positive weight.
            weight = [share.get(i, 0.0) for i in e["chain"]]
            if g["check"]:
                weight[-1] += self.fp / (1 - self.fn)
            for (_, positions), c in zip(e["columns"], e["index"]):
                q = sum(weight[pos] for pos in positions)
                if total and q:
                    priors[c] = fm.xor(priors[c], q / total / 2)
        self.decoder.update_channel_probs(priors)
        correction = self.decoder.decode(syndrome)
        if correction[priors == 0].any() or not np.array_equal(self.checks @ correction % 2, syndrome):
            return 2  # no explanation within the model: scored as a logical error
        return int(self.logical @ correction % 2)


def run(protocol, basis, arm, seed, shots, out, noise=True):
    """Decode one cell under skip-gate leakage and write its row."""
    started = time.monotonic()
    path = out / ("rows_skipgate" if noise else "rows_skipgate_off") / f"{protocol}_{basis}_{arm}_{seed}.json"
    if path.exists():
        return
    c = cell(protocol, basis, arm, seed, out)
    points = [(s["tick"], s["qubit"], s["kind"]) for s in c.sites]
    columns = signatures(c.base, points)
    validate_signatures(c.base, points, columns)
    envelope = envelopes(c)
    compiled = time.monotonic() - started
    nd = c.base.num_detectors
    erasure = np.array([s["erasure"] for s in c.sites]) * noise
    phase = np.array([s["pauli_z"] for s in c.sites]) * noise
    fp, fn, depol = (fm.CHECK_FP, fm.CHECK_FN, fm.CHECK_DEPOL) if noise else (0.0, 0.0, 0.0)
    rng = int.from_bytes(hashlib.sha256(f"r3_{basis}_{seed}".encode()).digest()[:8], "little")
    det, obs, flags = sample(c, erasure, phase, depol, fp, fn, shots, rng)
    simulated = time.monotonic() - started - compiled
    decoder = SkipDecoder(columns, envelope, nd, c.sites, c.groups, fm.CHECK_FP, fm.CHECK_FN, fm.CHECK_DEPOL)
    prediction = decoder.decode(det, flags)
    errors = int(np.count_nonzero(prediction != obs[:, 0]))
    row = dict(protocol=protocol, noise="skipgate" if noise else "off", basis=basis, topo=fm.TOPO, arm=arm, seed=seed,
               shots=shots, errors=errors, logical_error=errors / shots,
               flagged_shots=int(np.count_nonzero(flags.any(axis=1))),
               unexplained=int(np.count_nonzero(prediction == 2)), n_sites=len(c.sites), n_flags=len(c.groups),
               envelope_columns=sum(len(e["columns"]) for e in envelope),
               swaps=None, duration_us=c.duration, score=fm.score(c.sites), rng_seed=rng,
               check=dict(us=fm.CHECK_US, fp=fm.CHECK_FP, fn=fm.CHECK_FN, depol=fm.CHECK_DEPOL),
               decoder="ldpc.BpOsdDecoder/OSD_CS/serial, 7 iterations, order 2; Stim DEM envelope columns",
               versions={pkg: version(pkg) for pkg in ("qiskit", "stim", "ldpc", "numpy")},
               compile_seconds=compiled, sample_seconds=simulated, seconds=time.monotonic() - started)
    mem, qc = fm.routed(protocol, basis, arm, seed, out)
    ops = qc.count_ops()
    row.update(swaps=ops.get("swap", 0), joint_checks=ops.get("joint_check", 0), crz=ops.get("crz", 0),
               rswap=ops.get("rswap", 0))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol", choices=("readout", "checks", "checks3"))
    parser.add_argument("basis", choices=("X", "Z"))
    parser.add_argument("arm", choices=fm.mm.ARMS)
    parser.add_argument("seed", type=int)
    parser.add_argument("--shots", type=int, default=fm.SHOTS)
    parser.add_argument("--out", type=Path, default=fm.HERE)
    parser.add_argument("--off", action="store_true", help="all noise off (sanity)")
    args = parser.parse_args()
    run(args.protocol, args.basis, args.arm, args.seed, args.shots, args.out, noise=not args.off)
