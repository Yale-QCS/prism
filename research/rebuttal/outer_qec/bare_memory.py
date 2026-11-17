"""Physical-transmon control for the fixed Mehta Steane-memory experiment."""
from __future__ import annotations

import argparse
import dataclasses
from functools import lru_cache
import hashlib
import itertools
import json
import math
from pathlib import Path
import time

import mehta_memory as mm
import bare_report
import numpy as np
from qiskit import qpy
from qiskit.quantum_info import Operator
from qiskit.transpiler import PassManager
from qiskit.transpiler.passes import SabreLayout
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
import stim

ERRORS = bare_report.CZ_ERRORS
NOMINAL = bare_report.bare.CENTRAL.cz
STARTS = 40
OUTPUT = mm.OUTPUT


def thermal_probabilities(duration, device):
    """Independent Pauli channels whose product is the thermal channel's Pauli twirl."""
    xy = -math.expm1(-duration/(2*device.t1))/2
    z = -math.expm1(-device.dephasing*duration)/2
    return xy, xy, z


def scheduled(qc, device):
    """Return native gates and preceding idle times, with ideal reset/readout."""
    clocks = np.zeros(qc.num_qubits)
    events = []
    for ins in qc.data:
        op = ins.operation
        if op.name == 'barrier':
            continue
        assert op.name in {'reset', 'measure', 'cz', 'sx', 'x', 'rz'}, op.name
        qs = tuple(qc.find_bit(q).index for q in ins.qubits)
        start = max(clocks[list(qs)])
        idle = tuple(start-clocks[q] for q in qs)
        duration = device.durations.get(op.name, 0.0)
        clocks[list(qs)] = start+duration
        cbit = qc.find_bit(ins.clbits[0]).index if ins.clbits else None
        events.append((op, qs, cbit, idle, duration))
    return events, float(max(clocks))


def score(qc, device):
    """Negative log probability of no Pauli event in the simulated channels."""
    events, _ = scheduled(qc, device)
    cost = 0.0
    for op, qs, _, idle, duration in events:
        if op.name != 'reset':
            for dt in idle:
                cost -= sum(math.log1p(-p) for p in thermal_probabilities(dt, device))
        for _ in qs:
            cost -= sum(math.log1p(-p) for p in thermal_probabilities(duration, device))
        dep = device.depolarizing.get(op.name, 0.0)
        cost -= math.log1p(-dep*(1-1/4**len(qs)))
    return cost


@lru_cache(maxsize=None)
def clifford(name, params):
    """Convert a native ideal Clifford, checking its complete unitary."""
    from qiskit.circuit.library import CZGate, RZGate, SXGate, XGate
    op = {'cz': CZGate, 'sx': SXGate, 'x': XGate, 'rz': RZGate}[name](*params)
    return stim.Tableau.from_unitary_matrix(Operator(op).data, endian='little').to_circuit()


def circuit(mem, qc, device, *, noise=True):
    """Preserve classical measurement identities while adding native gate and idle noise."""
    out = stim.Circuit()
    measurements = {}
    events, duration = scheduled(qc, device)

    def thermal(q, dt):
        if noise:
            for axis, p in zip('XYZ', thermal_probabilities(dt, device)):
                if p:
                    out.append(f'{axis}_ERROR', [q], p)

    for op, qs, cbit, idle, dt in events:
        if op.name != 'reset':
            for q, gap in zip(qs, idle):
                thermal(q, gap)
        if op.name == 'reset':
            out.append('R', qs)
        elif op.name == 'measure':
            assert cbit not in measurements
            measurements[cbit] = out.num_measurements
            out.append('M', qs)
        else:
            body = clifford(op.name, tuple(float(p) for p in op.params))
            for ins in body:
                out.append(ins.name, [qs[t.value] for t in ins.targets_copy()])
            for q in qs:
                thermal(q, dt)
            p = device.depolarizing.get(op.name, 0.0)
            if noise and p:
                out.append(f'DEPOLARIZE{len(qs)}', qs, p*(1-1/4**len(qs)))
    assert set(measurements) == set(range(mem.n_meas))
    n = out.num_measurements
    for records in mem.detectors:
        out.append('DETECTOR', [stim.target_rec(measurements[k]-n) for k in records])
    for i, records in mem.observables.items():
        out.append('OBSERVABLE_INCLUDE', [stim.target_rec(measurements[k]-n) for k in records], i)
    out.detector_error_model()  # No approximate_disjoint_errors conversion.
    return out, duration


def decoder_for(noisy):
    """Retain both syndrome and logical effect when passing Stim's DEM to ldpc."""
    dem = noisy.detector_error_model().flattened()
    values, probabilities = [], []
    for ins in dem:
        if ins.type != 'error':
            continue
        value = 0
        for target in ins.targets_copy():
            if target.is_relative_detector_id():
                value ^= 1 << (target.val+1)
            else:
                assert target.is_logical_observable_id() and target.val == 0
                value ^= 1
        if value:
            values.append(value)
            probabilities.append(ins.args_copy()[0])
    columns = np.column_stack((np.zeros(len(values), dtype=np.int64), values))
    decoder = mm.Decoder(columns, noisy.num_detectors, probabilities)
    # Unlike dual rail's residual-Z subset, a physical transmon has all Pauli faults.
    # Record ambiguities instead of claiming an unflagged extractor is fault tolerant.
    possible = set(values) | {0}
    ambiguous = sum((v ^ 1) in possible for v in values)
    return decoder, columns, np.array(probabilities), ambiguous


def compile_memory(mem, cmap, seed, device):
    """Choose among native Qiskit routes with fixed, recorded search effort."""
    sources = (mem.qc, mm.DualRail.logical_pm().run(mem.qc))
    winner, winning_key, info = None, None, None
    for variant, source in enumerate(sources):
        for start in range(STARTS):
            trial_seed = seed+start
            pm = generate_preset_pass_manager(
                optimization_level=3, basis_gates=bare_report.bare.BASIS,
                coupling_map=cmap, seed_transpiler=trial_seed,
                layout_method='sabre', routing_method='sabre', unitary_synthesis_method='clifford')
            pm.layout = PassManager([SabreLayout(cmap, seed=trial_seed, max_iterations=16,
                                                swap_trials=40, layout_trials=1)])
            route_swaps = []
            def record(**kw):
                if kw['pass_'].name() == 'SabreLayout':
                    route_swaps.append(int(kw['dag'].count_ops().get('swap', 0)))
            routed = pm.run(source, callback=record)
            cost = score(routed, device)
            key = (cost, routed.count_ops().get('cz', 0), routed.size())
            if winning_key is None or key < winning_key:
                winner, winning_key = routed, key
                info = dict(variant=('original', 'logical_preprocessing')[variant],
                            transpiler_seed=trial_seed, score=cost,
                            routing_swaps_before_native_optimization=route_swaps[0])
    return winner, info


def run(basis, topo, seed, output=OUTPUT, shots=mm.SHOTS, prepare_only=False):
    started = time.monotonic()
    cell = f'{basis}_{topo}_transmon_{seed}'
    path = output/f'{cell}.json'
    if path.exists():
        raise FileExistsError(path)
    output.mkdir(parents=True, exist_ok=True)
    mem = mm.memory(basis)
    cmap = mm.make_topologies(mem.qc.num_qubits)[topo]
    source_digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    prepared_path = output/f'{cell}.route.json'
    if prepared_path.exists():
        prepared = json.loads(prepared_path.read_text())
        assert prepared['source_sha256'] == source_digest
        assert prepared['qpy_sha256'] == hashlib.sha256((output/f'{cell}.qpy').read_bytes()).hexdigest()
        with (output/f'{cell}.qpy').open('rb') as f:
            qc = qpy.load(f)[0]
        route = prepared['route']
    else:
        qc, route = compile_memory(mem, cmap, seed, bare_report.transmon_device(NOMINAL))
    ideal, duration = circuit(mem, qc, bare_report.transmon_device(NOMINAL), noise=False)
    assert ideal.num_measurements == mem.n_meas
    assert ideal.num_detectors+ideal.num_observables == ideal.count_determined_measurements()
    det, obs = ideal.compile_detector_sampler(seed=0).sample(256, separate_observables=True)
    assert not det.any() and not obs.any()
    if not prepared_path.exists():
        saved = qc.copy()
        saved._layout = None
        with (output/f'{cell}.qpy').open('wb') as f:
            qpy.dump(saved, f)
        (output/f'{cell}.ideal.stim').write_text(str(ideal)+'\n')
        prepared_path.write_text(json.dumps(dict(route=route, source_sha256=source_digest,
            qpy_sha256=hashlib.sha256((output/f'{cell}.qpy').read_bytes()).hexdigest()), indent=2)+'\n')
    if prepare_only:
        print(json.dumps(dict(prepared=cell, seconds=time.monotonic()-started)), flush=True)
        return
    results = []
    for error in ERRORS:
        device = bare_report.transmon_device(error)
        noisy, _ = circuit(mem, qc, device)
        decoder, columns, priors, ambiguous = decoder_for(noisy)
        rng = int.from_bytes(hashlib.sha256(f'{cell}_{error}'.encode()).digest()[:8], 'little')
        sampler = noisy.compile_detector_sampler(seed=rng)
        errors = 0
        for start in range(0, shots, 10_000):
            det, obs = sampler.sample(min(10_000, shots-start), separate_observables=True)
            prediction = decoder.decode(det, np.zeros((len(det), len(columns)), dtype=bool))
            errors += int(np.count_nonzero(prediction != obs[:, 0]))
        filename = f'{cell}_{error}.stim'
        (output/filename).write_text(str(noisy)+'\n')
        results.append(dict(cz_error=error, device=dataclasses.asdict(device), shots=shots,
                            errors=errors, logical_error=errors/shots, rng_seed=rng,
                            dem_mechanisms=len(priors), ambiguous_dem_mechanisms=ambiguous,
                            stim=filename))
    sources = [Path(__file__), Path(mm.__file__), Path(bare_report.__file__),
               Path(bare_report.bare.__file__), Path(bare_report.sim.__file__),
               Path(__file__).parent/'qec_circuits.py', Path(__file__).parent/'erasure_pilot.py']
    row = dict(protocol='physical-transmon-memory-v2', basis=basis, topo=topo, seed=seed,
               code='steane', rounds=3, constituents=mem.qc.num_qubits, sites=cmap.size(),
               duration_us=duration, op_counts=dict(qc.count_ops()), route=route,
               candidates=2*STARTS, sabre=dict(layout_trials=1, max_iterations=16, swap_trials=40),
               unitary_synthesis_method='clifford',
               reschedule=False, selection_cz_error=NOMINAL, results=results,
               noise='Pauli twirl of shared thermal channel, shared residual depolarization',
               decoder='ldpc.BpOsdDecoder/OSD_CS/serial', bp_iterations=7, osd_order=2,
               source_sha256={str(p.relative_to(mm.REPO)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sources}, seconds=time.monotonic()-started)
    path.write_text(json.dumps(row, indent=2)+'\n')
    print(json.dumps({k: row[k] for k in ('basis', 'topo', 'seed', 'duration_us', 'results', 'seconds')}), flush=True)


def check():
    """Compare the Stim-compatible thermal channel with the full Kraus Pauli transfer matrix."""
    from qiskit import QuantumCircuit, transpile
    from qiskit.quantum_info import DensityMatrix, Kraus, PTM, average_gate_fidelity
    worst = 0.0
    for error in ERRORS:
        device = bare_report.transmon_device(error)
        for dt in (0, 0.025, 0.042, 0.3, 1.0):
            survive = math.exp(-dt/device.t1)
            pz = -math.expm1(-device.dephasing*dt)/2
            amp = [np.diag([1, math.sqrt(survive)]), np.array([[0, math.sqrt(1-survive)], [0, 0]])]
            phase = [math.sqrt(1-pz)*np.eye(2), math.sqrt(pz)*np.diag([1, -1])]
            full = Kraus([p@a for p in phase for a in amp])
            twirl = Kraus([np.eye(2)])
            for axis, p in zip('XYZ', thermal_probabilities(dt, device)):
                pauli = Operator.from_label(axis).data
                twirl = twirl.compose(Kraus([math.sqrt(1-p)*np.eye(2), math.sqrt(p)*pauli]))
            delta = float(np.max(np.abs(PTM(twirl).data-np.diag(np.diag(PTM(full).data)))))
            worst = max(worst, delta)
            assert delta < 1e-12
            assert abs(average_gate_fidelity(twirl)-average_gate_fidelity(full)) < 1e-12
        for name, k, target in (('cz', 2, error), ('sx', 1, bare_report.bare.CENTRAL.sq)):
            dt = device.durations[name]
            fe = ((1+math.exp(-dt/device.t1)+2*math.exp(-dt*(device.dephasing+1/(2*device.t1))))/4)**k
            dep = device.depolarizing[name]
            actual = (2**k)/(2**k+1)*(1-((1-dep)*fe+dep/4**k))
            assert abs(actual-target) < 1e-12
    max_z = 0.0
    for seed in range(6):
        rng = np.random.default_rng(seed)
        body = QuantumCircuit(3)
        for _ in range(8):
            a, b = rng.choice(3, 2, replace=False)
            body.sx(a)
            body.cz(a, b)
        qc = transpile(body.compose(body.inverse()), basis_gates=bare_report.bare.BASIS,
                       optimization_level=0, seed_transpiler=seed)
        qc.measure_all()
        mem = mm.memory('X')
        mem.n_meas, mem.detectors, mem.observables = 3, [[0], [1]], {0: [2]}
        device = bare_report.transmon_device(ERRORS[seed % 2])
        noisy, _ = circuit(mem, qc, device)
        rho = DensityMatrix.from_label('000')

        def apply_thermal(state, q, dt):
            e1 = math.exp(-dt/device.t1)
            e2 = math.exp(-dt*(device.dephasing+1/(2*device.t1)))
            weights = ((1+e1+2*e2)/4, (1-e1)/4, (1-e1)/4, (1+e1-2*e2)/4)
            channel = Kraus([math.sqrt(max(0, p))*Operator.from_label(axis).data
                             for axis, p in zip('IXYZ', weights)])
            return state.evolve(channel, qargs=[q])

        for op, qs, _, idle, dt in scheduled(qc, device)[0]:
            for q, gap in zip(qs, idle):
                rho = apply_thermal(rho, q, gap)
            if op.name == 'measure':
                continue
            rho = rho.evolve(op, qargs=list(qs))
            for q in qs:
                rho = apply_thermal(rho, q, dt)
            dep = device.depolarizing.get(op.name, 0)
            if dep:
                ops, weights = bare_report.sim._pauli_mixture(len(qs), dep)
                rho = rho.evolve(Kraus([math.sqrt(p)*op for op, p in zip(ops, weights)]),
                                 qargs=list(qs))
        expected = np.array([rho.probabilities([q])[1] for q in range(3)])
        det, obs = noisy.compile_detector_sampler(seed=seed+745).sample(100_000, separate_observables=True)
        observed = np.column_stack((det, obs)).mean(axis=0)
        se = np.sqrt(expected*(1-expected)/len(det))
        z = float(np.max(np.abs(observed-expected)/se))
        assert z < 6, (seed, observed, expected)
        max_z = max(max_z, z)
    print(json.dumps(dict(check='shared-channel-Pauli-twirl', max_ptm_difference=worst,
                          cz_errors=ERRORS, calibrated_gate_errors=True,
                          density_matrix_circuits=6, validation_shots=600_000,
                          max_density_matrix_marginal_z=max_z)))


def audit():
    """Check sampled channel marginals and single-fault ambiguity on each seed-zero control."""
    checks = []
    for basis, topo in itertools.product('XZ', ('grid', 'hex_lattice')):
        path = OUTPUT/f'{basis}_{topo}_transmon_0.json'
        row = json.loads(path.read_text())
        for result in row['results']:
            noisy = stim.Circuit((OUTPUT/result['stim']).read_text())
            decoder, columns, priors, ambiguous = decoder_for(noisy)
            values = columns[:, 1]
            bits = (values[:, None] >> np.arange(noisy.num_detectors+1)) & 1
            expected = (1-np.prod(np.where(bits, 1-2*priors[:, None], 1), axis=0))/2
            det, obs = noisy.compile_detector_sampler(seed=746).sample(100_000, separate_observables=True)
            observed = np.column_stack((obs, det)).mean(axis=0)
            se = np.sqrt(expected*(1-expected)/len(det))
            assert np.all(observed[se == 0] == expected[se == 0])
            z = float(np.max(np.abs(observed[se > 0]-expected[se > 0])/se[se > 0]))
            assert z < 6
            syndrome = ((values[:, None] >> np.arange(1, noisy.num_detectors+1)) & 1).astype(bool)
            predictions = decoder.decode(syndrome, np.zeros((len(values), len(values)), dtype=bool))
            wrong = predictions != (values & 1)
            possible = set(values) | {0}
            unambiguous = np.array([(v ^ 1) not in possible for v in values])
            checks.append(dict(cell=path.stem, cz_error=result['cz_error'],
                               row_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                               validation_shots=100_000, max_marginal_z=z,
                               dem_mechanisms=len(values), ambiguous_dem_mechanisms=ambiguous,
                               single_mechanisms_failed=int(wrong.sum()),
                               unambiguous_single_mechanisms_failed=int((wrong & unambiguous).sum()),
                               single_mechanism_failure_sum=float(priors[wrong].sum())))
    (OUTPUT/'transmon_decoder_validation.json').write_text(json.dumps(checks, indent=2)+'\n')
    print(json.dumps(checks), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--tasks', action='store_true')
    parser.add_argument('--audit', action='store_true')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--basis', choices=('X', 'Z'))
    parser.add_argument('--topo', choices=('grid', 'hex_lattice'))
    parser.add_argument('--seed', type=int, choices=mm.SEEDS)
    parser.add_argument('--shots', type=int, default=mm.SHOTS)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.check:
        check()
    elif args.audit:
        audit()
    elif args.tasks:
        for basis, topo, seed in itertools.product('XZ', ('grid', 'hex_lattice'), mm.SEEDS):
            if not (args.output/f'{basis}_{topo}_transmon_{seed}.json').exists():
                print(f'--basis {basis} --topo {topo} --seed {seed}')
    else:
        if None in (args.basis, args.topo, args.seed):
            parser.error('provide --basis, --topo and --seed')
        run(args.basis, args.topo, args.seed, args.output, args.shots, args.prepare_only)
