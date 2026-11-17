"""Three-round Steane compiler diagnostic with ideal heralded erasures."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import subprocess
import time

os.environ.setdefault("NUMBA_CACHE_DIR", "/tmp/prism-qec-numba")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("RAYON_NUM_THREADS", "1")
os.environ.setdefault("QISKIT_PARALLEL", "FALSE")

import numpy as np
from numba import njit
import stim

from route import ARMS, BUDGET, REPO, assemble, compile_arm, make_topologies
from qec_circuits import experiment, to_qiskit

PROBABILITIES = [1e-4, 3e-4, 1e-3, 3e-3, 1e-2]
SHOTS = 200_000
SEEDS = list(range(0, 2000, 100))
DIRECTORY = Path(__file__).resolve().parent


def memory(basis):
    """Retain both types of temporal syndrome checks, including qldpc's omitted ones."""
    mem = to_qiskit(experiment("steane", 3, basis))
    previous = {}
    known = {tuple(sorted(d)) for d in mem.detectors}
    for ins in mem.qc.data:
        if ins.operation.name != "measure":
            continue
        q = mem.qc.find_bit(ins.qubits[0]).index
        k = mem.qc.find_bit(ins.clbits[0]).index
        if q in previous:
            pair = (previous[q], k)
            if pair not in known:
                mem.detectors.append(list(pair))
                known.add(pair)
        previous[q] = k
    return mem


def signatures(circ, sites):
    """Encode X/Z fault signatures with logical L0 in bit zero and detectors above it."""
    assert circ.num_observables == 1 and circ.num_detectors < 62
    result = np.zeros((len(sites), 2), dtype=np.int64)
    regions = circ.detecting_regions()
    for target, ticks in regions.items():
        bit = 0 if target.is_logical_observable_id() else 1 + target.val
        for i, (tick, q, _) in enumerate(sites):
            if tick not in ticks or q >= len(ticks[tick]):
                continue
            pauli = ticks[tick][q]
            if pauli in (2, 3):  # X anticommutes with Y and Z.
                result[i, 0] |= 1 << bit
            if pauli in (1, 2):  # Z anticommutes with X and Y.
                result[i, 1] |= 1 << bit
    return result


def complete_readout_checks(circ, expected_measurements=25):
    """Keep the consistency information from both physical rail measurements."""
    out = circ.copy()
    previous = {}
    extras = []
    k = 0
    for ins in circ:
        if ins.name == "R":
            for t in ins.targets_copy():
                previous.pop(t.value, None)
        elif ins.name == "M":
            for t in ins.targets_copy():
                if t.value in previous:
                    extras.append((previous[t.value], k))
                previous[t.value] = k
                k += 1
    assert len(extras) == circ.num_measurements - expected_measurements
    for a, b in extras:
        out.append("DETECTOR", [stim.target_rec(a - k), stim.target_rec(b - k)])
    out.detector_error_model()  # Every extra parity must be deterministic.
    # Check that detectors plus L0 span every noiseless measurement constraint.
    pivots = {}
    for ins in out:
        if ins.name not in ("DETECTOR", "OBSERVABLE_INCLUDE"):
            continue
        vector = 0
        for t in ins.targets_copy():
            vector ^= 1 << (k + t.value)
        while vector:
            bit = vector.bit_length()
            if bit not in pivots:
                pivots[bit] = vector
                break
            vector ^= pivots[bit]
    assert len(pivots) == out.num_detectors + out.num_observables
    assert len(pivots) == out.count_determined_measurements()
    return out


@njit(cache=True)
def insert(vector, pivots):
    """Return whether the column span now contains a syndrome-free logical flip."""
    for bit in range(len(pivots) - 1, 0, -1):
        if vector & (1 << bit):
            if pivots[bit]:
                vector ^= pivots[bit]
            else:
                pivots[bit] = vector
                return False
    return vector == 1


@njit(cache=True)
def ambiguous(columns, erased, n_detectors):
    """Test rank([H; L]) > rank(H) for the erased locations."""
    pivots = np.zeros(n_detectors + 1, dtype=np.int64)
    for i in erased:
        for col in columns[i]:
            if insert(col, pivots):
                return True
    return False


@njit(cache=True)
def sample(columns, n_detectors, p, shots, seed):
    """Sample independent erasures by exact geometric gaps and test recoverability."""
    np.random.seed(seed)
    failures = 0
    for _ in range(shots):
        pivots = np.zeros(n_detectors + 1, dtype=np.int64)
        i = np.random.geometric(p) - 1
        failed = False
        while i < len(columns) and not failed:
            for col in columns[i]:
                if insert(col, pivots):
                    failed = True
                    break
            i += np.random.geometric(p)
        failures += failed
    return failures


@njit(cache=True)
def small_patterns(columns, n_detectors):
    """Count all ambiguous single-site and two-site erasure patterns."""
    singles = 0
    for i in range(len(columns)):
        singles += ambiguous(columns, np.array([i]), n_detectors)
    pairs = 0
    for i in range(len(columns)):
        for j in range(i):
            pairs += ambiguous(columns, np.array([i, j]), n_detectors)
    return singles, pairs


def validate_signatures(circ, sites, columns):
    """Cross-check every fault column against Stim's detector error model."""
    positions = [i for i, ins in enumerate(circ) if ins.name == "TICK"]
    for (tick, q, _), row in zip(sites, columns):
        pos = positions[tick] + 1
        for name, expected in zip(("X_ERROR", "Z_ERROR"), row):
            fault = stim.Circuit()
            fault.append(name, [q], 0.125)
            dem = (circ[:pos] + fault + circ[pos:]).detector_error_model()
            observed = 0
            for ins in dem:
                if ins.type == "error":
                    for t in ins.targets_copy():
                        observed ^= 1 << (0 if t.is_logical_observable_id() else t.val + 1)
            assert observed == expected, (tick, q, name, observed, expected)


def with_heralds(circ, sites, p, pauli_z=None):
    """Insert actual erasure channels and preserve all original measurement references."""
    out = stim.Circuit()
    record_map, flags = [], []
    by_tick = {}
    for i, (tick, q, _) in enumerate(sites):
        by_tick.setdefault(tick, []).append((q, i))
    tick = 0
    count = 0
    for ins in circ:
        targets = [stim.target_rec(record_map[len(record_map) + t.value] - count)
                   if t.is_measurement_record_target else t for t in ins.targets_copy()]
        out.append(ins.name, targets, ins.gate_args_copy())
        if ins.name == "M":
            record_map.extend(range(count, count + len(targets)))
            count += len(targets)
        if ins.name == "TICK":
            for q, i in by_tick.get(tick, ()):
                out.append("HERALDED_ERASE", [q], p if np.isscalar(p) else p[i])
                flags.append(count)
                count += 1
                if pauli_z is not None and pauli_z[i]:
                    out.append("Z_ERROR", [q], pauli_z[i])
            tick += 1
    for k in flags:
        out.append("DETECTOR", [stim.target_rec(k - count)])
    assert len(flags) == len(sites)
    assert len(record_map) == circ.num_measurements
    return out


@njit(cache=True)
def decode_samples(columns, syndromes, flags, observables):
    """Solve for a compatible logical flip using only the syndrome and erasure flags."""
    n_detectors = syndromes.shape[1]
    result = np.zeros((len(flags), 2), dtype=np.bool_)
    for shot in range(len(flags)):
        pivots = np.zeros(n_detectors + 1, dtype=np.int64)
        for i in range(len(columns)):
            if flags[shot, i]:
                for col in columns[i]:
                    if insert(col, pivots):
                        result[shot, 0] = True
        syndrome = 0
        for j in range(n_detectors):
            syndrome |= int(syndromes[shot, j]) << (j + 1)
        for bit in range(n_detectors, 0, -1):
            if syndrome & (1 << bit):
                syndrome ^= pivots[bit]
        assert syndrome < 2  # The measured syndrome must have a compatible fault.
        result[shot, 1] = (syndrome & 1) != observables[shot, 0]
    return result


def decode_ldpc(columns, syndromes, flags):
    """Predict logical flips with ldpc's OSD-0 decoder, conditioned on erasure flags."""
    from ldpc import BpOsdDecoder

    columns = columns.ravel()
    n_detectors = syndromes.shape[1]
    checks = ((columns[None, :] >> np.arange(1, n_detectors + 1)[:, None]) & 1).astype(np.uint8)
    logical = (columns & 1).astype(np.uint8)
    predictions = np.zeros(len(syndromes), dtype=np.bool_)
    for shot, (syndrome, erased) in enumerate(zip(syndromes, flags)):
        syndrome = syndrome.astype(np.uint8)
        # Zero is a compatible correction for zero syndrome, including ambiguous shots.
        if not syndrome.any():
            continue
        active = np.flatnonzero(np.repeat(erased, 2))
        matrix = checks[:, active]
        # Given a herald, X and Z are independent fair bits (I/X/Y/Z equiprobable).
        decoder = BpOsdDecoder(matrix, error_rate=0.5, max_iter=1,
                              bp_method="product_sum", osd_method="OSD_0", osd_order=0)
        correction = decoder.decode(syndrome)
        assert np.array_equal(matrix @ correction % 2, syndrome)
        predictions[shot] = logical[active] @ correction % 2
    return predictions


def audit(output, use_ldpc=False):
    """Check actual erasure sampling and decoding on every seed-zero pilot circuit."""
    records = []
    for basis, topo, arm in itertools.product(("X", "Z"), ("grid", "hex_lattice"), ARMS):
        cell = f"{basis}_{topo}_{arm}_0"
        row = json.loads((output / f"{cell}.json").read_text())
        circ = stim.Circuit((output / f"{cell}.stim").read_text())
        columns = np.array(row["columns"], dtype=np.int64)
        shots, p = 100_000, 0.01
        # Sample the circuit, never the approximate heralded-channel DEM.
        noisy = with_heralds(circ, row["sites"], p)
        detectors, obs = noisy.compile_detector_sampler(seed=20261011).sample(
            shots, separate_observables=True)
        nd = row["n_detectors"]
        decoded = decode_samples(columns, detectors[:, :nd], detectors[:, nd:], obs)
        ambiguous_count = int(decoded[:, 0].sum())
        if use_ldpc:
            predictions = decode_ldpc(columns, detectors[:, :nd], detectors[:, nd:])
            failed = predictions != obs[:, 0]
        else:
            failed = decoded[:, 1]
        errors = int(failed.sum())
        assert not (failed & ~decoded[:, 0]).any(), cell
        assert abs(errors - ambiguous_count / 2) < 5 * np.sqrt(ambiguous_count / 4), cell
        prior = row["results"][-1]
        pooled = (ambiguous_count + prior["ambiguous"]) / (shots + prior["shots"])
        se = np.sqrt(pooled * (1 - pooled) * (1 / shots + 1 / prior["shots"]))
        assert abs(ambiguous_count / shots - prior["probability"]) < 5 * se, cell
        record = dict(cell=cell, p=p, shots=shots, ambiguous=ambiguous_count,
                      decoded_errors=errors, errors_on_recoverable_patterns=0,
                      rank_sampler_z=(ambiguous_count / shots - prior["probability"]) / se)
        if use_ldpc:
            from importlib.metadata import version

            record.update(decoder="ldpc.BpOsdDecoder/OSD_0", ldpc_version=version("ldpc"),
                          stim_version=stim.__version__,
                          row_sha256=hashlib.sha256((output / f"{cell}.json").read_bytes()).hexdigest(),
                          circuit_sha256=hashlib.sha256((output / f"{cell}.stim").read_bytes()).hexdigest(),
                          script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                          sampling_seed=20261011)
        records.append(record)
        print(json.dumps(record), flush=True)
    filename = "ldpc_decoder_audit.json" if use_ldpc else "decoder_audit.json"
    (output / filename).write_text(json.dumps(records, indent=2) + "\n")


def upgrade_readouts(output):
    """Recompute every saved route with all available rail-readout constraints."""
    prior = DIRECTORY / "data" / "ideal_erasure_v1"
    output.mkdir(parents=True, exist_ok=True)
    analysis_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    for basis, topo, arm, seed in itertools.product(
        ("X", "Z"), ("grid", "hex_lattice"), ARMS, SEEDS
    ):
        cell = f"{basis}_{topo}_{arm}_{seed}"
        path = prior / f"{cell}.json"
        row = json.loads(path.read_text())
        assert row["protocol"] == "ideal-erasure-v1"
        circ = complete_readout_checks(stim.Circuit((prior / f"{cell}.stim").read_text()))
        columns = signatures(circ, row["sites"])
        validate_signatures(circ, row["sites"], columns)
        measurements = circ.compile_sampler(seed=0).sample(256)
        d, obs = circ.compile_m2d_converter(skip_reference_sample=True).convert(
            measurements=measurements, separate_observables=True)
        assert not d.any() and not obs.any()
        singles, pairs = small_patterns(columns, circ.num_detectors)
        results = []
        for i, p in enumerate(PROBABILITIES):
            failures = sample(columns, circ.num_detectors, p, SHOTS, (row["rng_seed"] + i) % 2**32)
            results.append(dict(p=p, shots=SHOTS, ambiguous=int(failures), probability=failures / SHOTS))
        row.update(protocol="ideal-erasure-v2", columns=columns.tolist(),
                   n_detectors=circ.num_detectors, ambiguous_singles=int(singles),
                   ambiguous_pairs=int(pairs), results=results,
                   prior_row_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                   analysis_sha256=analysis_hash, readout_checks=circ.num_detectors - 18)
        row["validation"]["complete_measurement_constraints"] = circ.count_determined_measurements()
        (output / f"{cell}.json").write_text(json.dumps(row, indent=2) + "\n")
        (output / f"{cell}.stim").write_text(str(circ) + "\n")
        print(cell, "readout checks", row["readout_checks"], "pairs", pairs, flush=True)


def check():
    """Check the rank criterion by exhaustive faults and ideal Steane data erasures."""
    toy = stim.Circuit("R 0\nM 0\nTICK\nM 0\nOBSERVABLE_INCLUDE(0) rec[-1]")
    complete = complete_readout_checks(toy, expected_measurements=1)
    sites = [(0, 0, "swap")]
    assert ambiguous(signatures(toy, sites), np.array([0]), 0)
    assert not ambiguous(signatures(complete, sites), np.array([0]), 1)
    rng = np.random.default_rng(7)
    for n in range(1, 5):
        for _ in range(40):
            columns = rng.integers(0, 32, size=(n, 2), dtype=np.int64)
            outcomes = {}
            for fault in itertools.product((0, 1), repeat=2 * n):
                value = 0
                for col, active in zip(columns.flat, fault):
                    if active:
                        value ^= int(col)
                outcomes.setdefault(value >> 1, set()).add(value & 1)
            brute = any(len(v) == 2 for v in outcomes.values())
            assert ambiguous(columns, np.arange(n), 4) == brute

    # Hamming parity checks, with a weight-three Steane logical on columns 1,2,3.
    columns = np.array([[((q + 1) << 1) | int(q < 3), 0] for q in range(7)], dtype=np.int64)
    for size in (1, 2):
        assert not any(ambiguous(columns, np.array(e), 3)
                       for e in itertools.combinations(range(7), size))
    assert sum(ambiguous(columns, np.array(e), 3)
               for e in itertools.combinations(range(7), 3)) == 7
    assert ambiguous(columns, np.array([0, 1, 2]), 3)
    # Exhaustively sum all 128 data-erasure patterns to check the sampler.
    p = 0.2
    exact = 0.0
    for mask in range(128):
        erased = np.array([i for i in range(7) if mask >> i & 1], dtype=np.int64)
        if ambiguous(columns, erased, 3):
            exact += p ** len(erased) * (1 - p) ** (7 - len(erased))
    estimate = sample(columns, 3, p, SHOTS, 1) / SHOTS
    assert abs(exact - estimate) < 5 * np.sqrt(exact * (1 - exact) / SHOTS)
    print(json.dumps(dict(check="passed", rank_examples=160,
                          steane_triples=7, exact=exact, sampled=estimate)))


def run(basis, topo, arm, seed, output):
    """Compile one fixed pilot cell and save its checks, fault map and sampled outcomes."""
    started = time.monotonic()
    compiler_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    compiler_tree = subprocess.check_output(
        ["git", "rev-parse", "HEAD:src", "HEAD:crates"], cwd=REPO, text=True).splitlines()
    source_sha256 = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in DIRECTORY.glob("*.py")}
    mem = memory(basis)
    cmap = make_topologies(mem.qc.num_qubits)[topo]
    routed, metrics = compile_arm(mem.qc, cmap, arm, seed)
    sites = []
    circ, _ = assemble(mem, routed, noise=False, erasure_sites=sites)
    circ = complete_readout_checks(circ)
    circ.detector_error_model()  # Raises if any parity is nondeterministic.
    measurements = circ.compile_sampler(seed=0).sample(256)
    d, obs = circ.compile_m2d_converter(skip_reference_sample=True).convert(
        measurements=measurements, separate_observables=True)
    assert not d.any() and not obs.any()
    columns = signatures(circ, sites)
    validate_signatures(circ, sites, columns)
    singles, pairs = small_patterns(columns, circ.num_detectors)
    cell = f"{basis}_{topo}_{arm}_{seed}"
    rng_seed = int.from_bytes(hashlib.sha256(cell.encode()).digest()[:4], "little")
    results = []
    for i, p in enumerate(PROBABILITIES):
        failures = sample(columns, circ.num_detectors, p, SHOTS, (rng_seed + i) % 2**32)
        results.append(dict(p=p, shots=SHOTS, ambiguous=int(failures),
                            probability=failures / SHOTS))
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{cell}.stim").write_text(str(circ) + "\n")
    row = dict(protocol="ideal-erasure-v2", code="steane", rounds=3, basis=basis,
               topo=topo, arm=arm, seed=seed,
               objective="error" if arm != "logical" else None,
               budget=BUDGET if arm != "logical" else None,
               reschedule=False, compiler_commit=compiler_commit, compiler_tree=compiler_tree,
               sites=sites, columns=columns.tolist(), n_sites=len(sites),
               n_detectors=circ.num_detectors, ambiguous_singles=int(singles),
               readout_checks=circ.num_detectors - 18,
               ambiguous_pairs=int(pairs), swaps=metrics.swaps, depth=metrics.depth,
               active_duration=metrics.duration, physical_sites=cmap.size(),
               rng_seed=rng_seed, results=results,
               validation=dict(noiseless_shots=256, checked_fault_columns=2 * len(sites),
                               complete_measurement_constraints=circ.count_determined_measurements()),
               source_sha256=source_sha256,
               seconds=round(time.monotonic() - started, 2))
    (output / f"{cell}.json").write_text(json.dumps(row, indent=2) + "\n")
    print(json.dumps({k: v for k, v in row.items() if k not in ("sites", "columns")}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--audit-ldpc", action="store_true", help="decode actual Stim shots with ldpc OSD-0")
    parser.add_argument("--tasks", action="store_true", help="print missing cells for xargs -P 2 -n 8")
    parser.add_argument("--upgrade-readouts", action="store_true")
    parser.add_argument("--basis", choices=("X", "Z"))
    parser.add_argument("--topo", choices=("grid", "hex_lattice"))
    parser.add_argument("--arm", choices=ARMS)
    parser.add_argument("--seed", type=int, choices=SEEDS)
    parser.add_argument("--output", type=Path, default=DIRECTORY / "data" / "ideal_erasure_v2")
    args = parser.parse_args()
    if args.check:
        check()
    elif args.audit:
        audit(args.output)
    elif args.audit_ldpc:
        audit(args.output, use_ldpc=True)
    elif args.upgrade_readouts:
        upgrade_readouts(args.output)
    elif args.tasks:
        for basis, topo, arm, seed in itertools.product(
            ("X", "Z"), ("grid", "hex_lattice"), ARMS, SEEDS
        ):
            if not (args.output / f"{basis}_{topo}_{arm}_{seed}.json").exists():
                print(f"--basis {basis} --topo {topo} --arm {arm} --seed {seed}")
    else:
        if None in (args.basis, args.topo, args.arm, args.seed):
            parser.error("provide --basis, --topo, --arm and --seed, or --check")
        run(args.basis, args.topo, args.arm, args.seed, args.output)
