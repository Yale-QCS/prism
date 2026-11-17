"""Report the complete, fixed nominal-device Steane comparison; never select a subset."""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path
import time

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

DIRECTORY = Path(__file__).resolve().parent / 'data' / 'mehta_memory'
REPO = Path(__file__).resolve().parents[3]
GROUPS = list(itertools.product(('X', 'Z'), ('grid', 'hex_lattice')))
SEEDS = list(range(0, 2000, 100))
ARMS = ('greedy', 'prism')


def audit_transmon():
    """Bound decoder weakness using the exact syndrome/logical distribution, as an audit only."""
    import bare_memory as bare
    import stim

    bare.audit()
    path = DIRECTORY/'transmon_decoder_validation.json'
    rows = json.loads(path.read_text())
    for row in rows:
        source = json.loads((DIRECTORY/f"{row['cell']}.json").read_text())
        case = next(r for r in source['results'] if r['cz_error'] == row['cz_error'])
        circ = stim.Circuit((DIRECTORY/case['stim']).read_text())
        _, columns, priors, _ = bare.decoder_for(circ)
        # Exact XOR convolution of Stim's independent DEM mechanisms. Bit zero
        # is the logical flip, so each adjacent pair has the same syndrome.
        index = np.arange(1 << (circ.num_detectors+1))
        joint = np.zeros(len(index))
        joint[0] = 1
        for value, probability in zip(columns[:, 1], priors):
            joint = (1-probability)*joint+probability*joint[index ^ value]
        assert abs(joint.sum()-1) < 1e-12 and joint.min() >= 0
        row['optimal_decoder_failure_probability'] = float(joint.reshape(-1, 2).min(axis=1).sum())
        row['observed_library_decoder_failure_probability'] = case['logical_error']
        # Compare all marginals with the independent product expression.
        for bit in range(circ.num_detectors+1):
            expected = (1-np.prod(1-2*priors[(columns[:, 1] >> bit) & 1 != 0]))/2
            actual = joint[(index >> bit) & 1 != 0].sum()
            assert abs(actual-expected) < 1e-12
        print(json.dumps(row), flush=True)
    path.write_text(json.dumps(rows, indent=2)+'\n')


def audit():
    """Check the decoder in the erasure-only limit and the mixed channel's marginals."""
    import stim
    from erasure_pilot import decode_samples, with_heralds
    from mehta_memory import Decoder

    destination = DIRECTORY/'decoder_validation.json'
    previous = json.loads(destination.read_text()) if destination.exists() else []
    results = [r for r in previous if r['row_sha256'] == hashlib.sha256(
        (DIRECTORY/f"{r['cell']}.json").read_bytes()).hexdigest()]
    completed = {r['cell'] for r in results}
    for basis, topo, arm in itertools.product(('X', 'Z'), ('grid', 'hex_lattice'), ARMS):
        cell = f'{basis}_{topo}_{arm}_0'
        if cell in completed or not (DIRECTORY/f'{cell}.json').exists():
            continue
        row = json.loads((DIRECTORY/f'{cell}.json').read_text())
        base = stim.Circuit((DIRECTORY/f'{cell}.ideal.stim').read_text())
        noisy = stim.Circuit((DIRECTORY/f'{cell}.stim').read_text())
        columns = np.array(row['columns'], dtype=np.int64)
        nd = row['n_detectors']
        pe = np.array([s['erasure'] for s in row['sites']])
        pz = np.array([s['pauli_z'] for s in row['sites']])
        det, obs = noisy.compile_detector_sampler(seed=745).sample(100_000, separate_observables=True)
        observed = np.concatenate((obs, det[:, :nd]), axis=1).mean(axis=0)
        bits = (columns[:, :, None] >> np.arange(nd+1)) & 1
        # Either X or Z anticommutes with a tested parity: a flagged replacement
        # randomizes that parity. Residual Z contributes its separate XOR channel.
        factors = np.where(bits.any(axis=1), 1-pe[:, None], 1.)
        factors *= np.where(bits[:, 1, :], 1-2*pz[:, None], 1.)
        expected = (1-factors.prod(axis=0))/2
        se = np.sqrt(expected*(1-expected)/len(det))
        assert np.all(observed[se == 0] == expected[se == 0])
        zmax = float(np.max(np.abs(observed[se > 0]-expected[se > 0])/se[se > 0]))
        assert zmax < 6, (cell, zmax)

        points = [(s['tick'], s['qubit'], s['kind']) for s in row['sites']]
        pure = with_heralds(base, points, pe)
        det, obs = pure.compile_detector_sampler(seed=746).sample(10_000, separate_observables=True)
        decoder = Decoder(columns, nd, np.zeros(len(points)))
        prediction = decoder.decode(det[:, :nd], det[:, nd:])
        reference = decode_samples(columns, det[:, :nd], det[:, nd:], obs)
        wrong = prediction != obs[:, 0]
        assert not np.any(wrong & ~reference[:, 0]), cell
        ambiguous = int(reference[:, 0].sum())
        assert abs(wrong.sum()-ambiguous/2) <= 6*np.sqrt(ambiguous/4)+1, cell

        # Diagnostic: the standard extraction schedule may leave unflagged
        # single residual faults ambiguous. Do not hide this behind an erasure-only claim.
        decoder = Decoder(columns, nd, pz)
        syndrome = ((columns[:, 1, None] >> np.arange(1, nd+1)) & 1).astype(bool)
        single_wrong = decoder.decode(syndrome, np.zeros((len(points), len(points)), dtype=bool)) != (columns[:, 1] & 1)
        result = dict(cell=cell, mixed_shots=100_000, max_marginal_z=zmax,
                      row_sha256=hashlib.sha256((DIRECTORY/f'{cell}.json').read_bytes()).hexdigest(),
                      erasure_only_shots=10_000, ambiguous=ambiguous,
                      erasure_only_errors=int(wrong.sum()), errors_on_recoverable_patterns=0,
                      single_residual_locations_failed=int(single_wrong.sum()),
                      single_residual_first_order_sum=float(pz[single_wrong].sum()))
        results.append(result)
        print(json.dumps(result), flush=True)
        destination.write_text(json.dumps(results, indent=2)+'\n')
    print(f'Validated {len(results)}/8 seed-zero circuits.', flush=True)


def redecode(arm, basis_filter=None):
    """Reuse all saved routes and identical Stim samples after validating the decoder."""
    from qiskit import qpy
    from mehta_memory import Decoder, circuit, memory

    for basis, topo, seed in itertools.product(('X', 'Z'), ('grid', 'hex_lattice'), SEEDS):
        if basis_filter is not None and basis != basis_filter:
            continue
        started = time.monotonic()
        cell = f'{basis}_{topo}_{arm}_{seed}'
        path = DIRECTORY/f'{cell}.json'
        row = json.loads(path.read_text())
        if row['protocol'] == 'mehta-memory-v2':
            continue
        assert row['protocol'] == 'mehta-memory-v1'
        with (DIRECTORY/f'{cell}.qpy').open('rb') as f:
            qc = qpy.load(f)[0]
        base, noisy, points, sites, duration, score = circuit(memory(basis), qc)
        assert str(base).strip() == (DIRECTORY/f'{cell}.ideal.stim').read_text().strip()
        assert str(noisy).strip() == (DIRECTORY/f'{cell}.stim').read_text().strip()
        assert sites == row['sites'] and score == row['score'] and duration == row['duration_us']
        new_sources = {name: hashlib.sha256((REPO/name).read_bytes()).hexdigest()
                       for name in row['source_sha256']}
        for name, digest in new_sources.items():
            if not name.endswith('/mehta_memory.py'):
                assert digest == row['source_sha256'][name], name
        columns = np.array(row['columns'], dtype=np.int64)
        nd = row['n_detectors']
        pz = np.array([s['pauli_z'] for s in sites])
        decoder = Decoder(columns, nd, pz)
        assert decoder.decoder.schedule == 'serial' and decoder.decoder.osd_order == 2
        single_checks = decoder.check_single_residuals(pz)
        sampler = noisy.compile_detector_sampler(seed=row['rng_seed'])
        errors, heralded = 0, 0
        for start in range(0, row['shots'], 10_000):
            det, obs = sampler.sample(min(10_000, row['shots']-start), separate_observables=True)
            prediction = decoder.decode(det[:, :nd], det[:, nd:])
            errors += int(np.count_nonzero(prediction != obs[:, 0]))
            heralded += int(np.count_nonzero(det[:, nd:].any(axis=1)))
        assert heralded == row['heralded_shots']
        row['osd0_audit'] = {key: row[key] for key in
                             ('errors', 'logical_error', 'decoder', 'bp_iterations', 'source_sha256')}
        row['osd0_audit']['settings'] = dict(bp_method='product_sum', schedule='parallel',
                                           osd_method='OSD_0', osd_order=0, max_iter=30)
        row.update(protocol='mehta-memory-v2', errors=errors, logical_error=errors/row['shots'],
                   decoder='ldpc.BpOsdDecoder/OSD_CS/serial', bp_iterations=7, osd_order=2,
                   source_sha256=new_sources, circuit_revalidated=True,
                   single_residual_faults_checked=single_checks,
                   single_residual_faults_failed=0, redecode_seconds=time.monotonic()-started)
        path.write_text(json.dumps(row, indent=2)+'\n')
        print(json.dumps({k: row[k] for k in ('basis','topo','arm','seed','errors','logical_error','redecode_seconds')}), flush=True)


def main():
    """Check all inputs, then write one report, summary and absolute-error figure."""
    rows, paths = {}, []
    for basis, topo, arm, seed in itertools.product(('X', 'Z'), ('grid', 'hex_lattice'), ARMS, SEEDS):
        path = DIRECTORY / f'{basis}_{topo}_{arm}_{seed}.json'
        row = json.loads(path.read_text())
        assert (row['basis'], row['topo'], row['arm'], row['seed']) == (basis, topo, arm, seed)
        assert row['protocol'] == 'mehta-memory-v2' and row['shots'] == 50_000
        assert row['objective'] == 'mehta_no_fault' and not row['reschedule']
        assert row['checked_fault_columns'] == 2*len(row['sites'])
        assert row['noiseless_shots'] == 256 and row['bp_iterations'] == 7
        assert row['decoder'] == 'ldpc.BpOsdDecoder/OSD_CS/serial' and row['osd_order'] == 2
        assert row['single_residual_faults_failed'] == 0
        assert row['score'] == row['winning_score'][0]
        assert row['logical_error'] == row['errors']/row['shots']
        expected_flags = 1-np.prod([1-s['erasure'] for s in row['sites']])
        flag_se = np.sqrt(expected_flags*(1-expected_flags)/row['shots'])
        assert abs(row['heralded_shots']/row['shots']-expected_flags) < 6*flag_se
        rows[basis, topo, arm, seed] = row
        paths.append(path)
    first = next(iter(rows.values()))
    for row in rows.values():
        for key in ('device', 'budget', 'versions', 'source_sha256', 'code', 'rounds'):
            assert row[key] == first[key], key
    for name, digest in first['source_sha256'].items():
        assert hashlib.sha256((REPO/name).read_bytes()).hexdigest() == digest, name
    validation = json.loads((DIRECTORY/'validation.json').read_text())
    assert validation['device'] == first['device']
    assert validation['max_exact_difference'] < validation['tolerance']
    audit_rows = json.loads((DIRECTORY/'decoder_validation.json').read_text())
    assert len(audit_rows) == 8 and all(r['errors_on_recoverable_patterns'] == 0 for r in audit_rows)
    for r in audit_rows:
        assert hashlib.sha256((DIRECTORY/f"{r['cell']}.json").read_bytes()).hexdigest() == r['row_sha256']

    rng = np.random.default_rng(745)
    indices = rng.integers(len(SEEDS), size=(20_000, len(SEEDS)))
    results = []
    lines = [
        'Nominal MEHTA_IDLE: three-round Steane memory, direct Stim + ldpc serial BP/OSD-CS(2).',
        '160 circuits, 20 seeds per arm and family, 50,000 shots per circuit.',
        'No postselection. Logical error = wrong decoded logical outcomes / shots.',
        'Both arms use the same physical-fault route score and 40/16/40 budget.',
        'Ideal preparation, readout and immediate erasure recovery; no check/reset cost.',
        'Intervals resample paired routing seeds (20,000 bootstrap replicates).',
        'They do not quantify uncertainty in the hardware or recovery assumptions.',
        '',
        'Family      Greedy errors/shots (P_L %)     PRISM errors/shots (P_L %)      Reduction, percentage points [95% seed CI]   Relative % [95% seed CI]',
    ]
    for basis, topo in GROUPS:
        entry = dict(basis=basis, topo=topo)
        rates = {}
        for arm in ARMS:
            cells = [rows[basis, topo, arm, seed] for seed in SEEDS]
            rates[arm] = np.array([r['logical_error'] for r in cells])
            draws = rates[arm][indices].mean(axis=1)
            entry[arm] = dict(
                errors=sum(r['errors'] for r in cells), shots=sum(r['shots'] for r in cells),
                logical_error=float(rates[arm].mean()),
                interval=np.quantile(draws, [0.025, 0.975]).tolist(),
                mean_swaps=float(np.mean([r['metrics']['swaps'] for r in cells])),
                mean_duration_us=float(np.mean([r['duration_us'] for r in cells])),
                mean_score=float(np.mean([r['score'] for r in cells])),
                fraction_with_erasure=sum(r['heralded_shots'] for r in cells)/sum(r['shots'] for r in cells),
            )
        g, p = rates['greedy'], rates['prism']
        gd, pd = g[indices].mean(axis=1), p[indices].mean(axis=1)
        entry['absolute_reduction'] = float(g.mean()-p.mean())
        entry['absolute_reduction_interval'] = np.quantile(gd-pd, [0.025, 0.975]).tolist()
        entry['relative_reduction'] = float(1-p.mean()/g.mean())
        entry['relative_reduction_interval'] = np.quantile(1-pd/gd, [0.025, 0.975]).tolist()
        entry['seeds_lower_equal_higher'] = [int(np.count_nonzero(test)) for test in (p<g, p==g, p>g)]
        results.append(entry)
        def cell(arm):
            r = entry[arm]
            return f"{r['errors']}/{r['shots']} ({100*r['logical_error']:.4f}%)"
        def estimate(key):
            lo, hi = entry[key+'_interval']
            return f"{100*entry[key]:.4f} [{100*lo:.4f}, {100*hi:.4f}]"
        lines.append(f'{basis} {topo:11} {cell("greedy"):29} {cell("prism"):29} {estimate("absolute_reduction"):40} {estimate("relative_reduction")}')
    lines.extend(['', 'Routing and decoder diagnostics:'])
    for r in results:
        g, p = r['greedy'], r['prism']
        lines.append(f"{r['basis']} {r['topo']}: SWAPs {g['mean_swaps']:.2f} -> {p['mean_swaps']:.2f}; duration {g['mean_duration_us']:.2f} -> {p['mean_duration_us']:.2f} us; physical-fault score {g['mean_score']:.4f} -> {p['mean_score']:.4f}; seeds with lower/equal/higher PRISM logical error {r['seeds_lower_equal_higher']}")
    lines.extend(['', 'All rates are the shared nominal device values; there is no fitted noise multiplier.',
                  'The old uniform-p sweep is historical evidence, not a Mehta calibration or sensitivity axis.',
                  'The route score is a physical-fault proxy; decoded logical error is measured separately.'])
    checks = sum(r['single_residual_faults_checked'] for r in rows.values())
    lines.append(f'All {checks} supported single residual faults are distinguishable and correctly decoded across the 160 routes. The separate eight-circuit mixed-channel and erasure-limit audits pass.')
    transmon_paths = [DIRECTORY/f'{basis}_{topo}_transmon_{seed}.json'
                      for basis, topo in GROUPS for seed in SEEDS]
    transmon_rows = []
    transmon_audit = []
    if any(p.exists() for p in transmon_paths):
        assert all(p.exists() for p in transmon_paths), 'Physical-transmon control incomplete'
        transmon_rows = [json.loads(p.read_text()) for p in transmon_paths]
        for row in transmon_rows:
            assert row['protocol'] == 'physical-transmon-memory-v2'
            assert row['unitary_synthesis_method'] == 'clifford'
            assert (row['code'], row['rounds'], row['constituents']) == ('steane', 3, 13)
            assert row['candidates'] == 80 and not row['reschedule']
            assert row['sabre'] == dict(layout_trials=1, max_iterations=16, swap_trials=40)
            assert row['selection_cz_error'] == .003
            assert row['decoder'] == 'ldpc.BpOsdDecoder/OSD_CS/serial'
            assert row['bp_iterations'] == 7 and row['osd_order'] == 2
            assert row['source_sha256'] == transmon_rows[0]['source_sha256']
            assert {r['cz_error'] for r in row['results']} == {.001, .003}
            assert all(r['shots'] == 50_000 and r['logical_error'] == r['errors']/r['shots'] for r in row['results'])
        for name, digest in transmon_rows[0]['source_sha256'].items():
            assert hashlib.sha256((REPO/name).read_bytes()).hexdigest() == digest, name
        channel_check = json.loads((DIRECTORY/'transmon_validation.json').read_text())
        assert channel_check['max_ptm_difference'] < 1e-12
        assert channel_check['max_density_matrix_marginal_z'] < 6
        transmon_audit = json.loads((DIRECTORY/'transmon_decoder_validation.json').read_text())
        assert len(transmon_audit) == 8
        for r in transmon_audit:
            assert hashlib.sha256((DIRECTORY/f"{r['cell']}.json").read_bytes()).hexdigest() == r['row_sha256']
            assert r['max_marginal_z'] < 6
            assert 'optimal_decoder_failure_probability' in r
        lines.extend(['', 'Physical-transmon control: same Steane code, rounds, site graphs and twenty seeds.',
                      'One transmon per constituent: 13 transmons versus 26 cavity rails, with unused graph sites available for routing.',
                      'Shared bare_report.transmon_device, CZ error 0.1% and 0.3%. Thermal noise uses its Pauli twirl.',
                      'Ideal preparation/readout on both platforms; dual rail additionally assumes immediate ideal erasure recovery.',
                      'Native Qiskit O3 with Clifford synthesis, eighty candidates, selection at 0.3% CZ error; no final rescheduling.',
                      'This same-code extraction circuit is not a matched-resource or optimized fault-tolerant platform comparison.',
                      'The unflagged extraction has ambiguous single-fault effects. Its result includes that circuit limitation.',
                      'Family       CZ error   Errors/shots       Logical error % [95% seed CI]   Duration us   Native CZs'])
        for entry in results:
            group = sorted([r for r in transmon_rows if r['basis'] == entry['basis'] and r['topo'] == entry['topo']], key=lambda r:r['seed'])
            assert [r['seed'] for r in group] == SEEDS
            for error in (.001, .003):
                cases = [next(r for r in row['results'] if r['cz_error'] == error) for row in group]
                rates = np.array([r['logical_error'] for r in cases])
                bounds = np.quantile(rates[indices].mean(axis=1), [.025, .975])
                entry[f'transmon_{error}'] = dict(
                    errors=sum(r['errors'] for r in cases), shots=sum(r['shots'] for r in cases),
                    logical_error=float(rates.mean()), interval=bounds.tolist(),
                    mean_duration_us=float(np.mean([r['duration_us'] for r in group])),
                    mean_native_cz=float(np.mean([r['op_counts'].get('cz', 0) for r in group])),
                    mean_routing_swaps_before_native_optimization=float(np.mean([r['route']['routing_swaps_before_native_optimization'] for r in group])))
                r = entry[f'transmon_{error}']
                lines.append(f"{entry['basis']} {entry['topo']:11} {100*error:.1f}%   {r['errors']}/{r['shots']}   {100*r['logical_error']:.4f} [{100*bounds[0]:.4f}, {100*bounds[1]:.4f}]   {r['mean_duration_us']:.3f}   {r['mean_native_cz']:.2f}")
        lines.extend(['', 'Seed-zero decoder audit (exact optimum for the stipulated Pauli circuit, not primary performance data):',
                      'The ldpc estimates use finite shots and can fall below an exact bound within sampling noise.'])
        for r in transmon_audit:
            lines.append(f"{r['cell']} CZ {100*r['cz_error']:.1f}%: optimal failure {100*r['optimal_decoder_failure_probability']:.4f}%, sampled ldpc {100*r['observed_library_decoder_failure_probability']:.4f}%; unambiguous single DEM mechanisms missed {r['unambiguous_single_mechanisms_failed']}")
        paths.extend(transmon_paths)
    report = '\n'.join(lines)+'\n'
    (DIRECTORY/'report.txt').write_text(report)
    summary = dict(protocol=first['protocol'], device=first['device'], budget=first['budget'],
                   versions=first['versions'], source_sha256=first['source_sha256'],
                   bootstrap_seed=745, bootstrap_replicates=20_000, groups=results,
                   total_shots=sum(r['shots'] for r in rows.values()),
                   total_comparison_shots=sum(r['shots'] for r in rows.values())+
                       sum(case['shots'] for row in transmon_rows for case in row['results']),
                   checked_fault_columns=sum(r['checked_fault_columns'] for r in rows.values()),
                   single_residual_faults_checked=checks,
                   decoder_validation=audit_rows,
                   transmon_control=dict(rows=len(transmon_rows),
                       total_shots=sum(case['shots'] for row in transmon_rows for case in row['results']),
                       decoder_validation=transmon_audit,
                       source_sha256=transmon_rows[0]['source_sha256'] if transmon_rows else {}),
                   input_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    (DIRECTORY/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')

    if transmon_rows:
        fig, (platform_ax, ax) = plt.subplots(1, 2, figsize=(13.2, 4.7), layout='constrained')
        platform_arms = [('transmon_0.003', 'Transmon · CZ 0.3%', '#b75d25'),
                         ('transmon_0.001', 'Transmon · CZ 0.1%', '#dfab66'),
                         ('greedy', 'Dual rail · Greedy', '#777777'),
                         ('prism', 'Dual rail · PRISM', '#1768ac')]
        for i, (arm, label, color) in enumerate(platform_arms):
            means = np.array([r[arm]['logical_error'] for r in results])*100
            bounds = np.array([r[arm]['interval'] for r in results]).T*100
            locs = np.arange(4)+(i-1.5)*.21
            platform_ax.bar(locs, means, width=.19, color=color, label=label,
                            yerr=np.array([means-bounds[0], bounds[1]-means]), capsize=2)
        platform_ax.set_xticks(np.arange(4), ['X · grid', 'X · hex', 'Z · grid', 'Z · hex'])
        platform_ax.set_ylabel('Wrong decoded logical outcomes (%)')
        platform_ax.set_ylim(bottom=0, top=platform_ax.get_ylim()[1]*1.25)
        platform_ax.set_title('Same Steane memory with different constituents')
        platform_ax.legend(frameon=False, fontsize=8, ncols=2, loc='upper left')
        platform_ax.spines[['right', 'top']].set_visible(False)
    else:
        fig, ax = plt.subplots(figsize=(8.0, 4.5), layout='constrained')
    x = np.arange(4)
    for arm, offset, color in [('greedy', -.17, '#777777'), ('prism', .17, '#1768ac')]:
        means = np.array([r[arm]['logical_error'] for r in results])*100
        bounds = np.array([r[arm]['interval'] for r in results]).T*100
        ax.bar(x+offset, means, width=.3, color=color, label='PRISM' if arm == 'prism' else 'Greedy',
               yerr=np.array([means-bounds[0], bounds[1]-means]), capsize=3)
        for loc, mean, high in zip(x+offset, means, bounds[1]):
            ax.annotate(f'{mean:.4f}%', (loc, high), xytext=(0, 5), textcoords='offset points',
                        ha='center', fontsize=9)
    ax.set_xticks(x, ['X · grid', 'X · hex', 'Z · grid', 'Z · hex'])
    ax.set_ylabel('Wrong decoded logical outcomes (%)')
    ax.set_ylim(bottom=0, top=ax.get_ylim()[1]*1.2)
    ax.set_title('Dual-rail compiler comparison' if transmon_rows else 'Three-round Steane memory at the shared Mehta device point')
    ax.legend(frameon=False, ncols=2)
    ax.spines[['right', 'top']].set_visible(False)
    footer = ('Three-round memory · 20 routing seeds · 50,000 shots per route and noise point · 95% seed intervals\n'
              'Ideal preparation/readout and dual-rail erasure recovery · transmon thermal Pauli approximation · same-code proof of concept') if transmon_rows else (
              'Ideal erasure recovery · 20 routing seeds · 50,000 shots per route\n95% intervals across seeds · modified objective shared by both compilers')
    fig.supxlabel(footer, fontsize=9)
    fig.savefig(DIRECTORY/'comparison.png', dpi=180)
    plt.close(fig)
    print(report, end='')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', action='store_true')
    parser.add_argument('--audit-transmon', action='store_true')
    parser.add_argument('--redecode', choices=ARMS)
    parser.add_argument('--basis', choices=('X', 'Z'))
    args = parser.parse_args()
    if args.redecode:
        redecode(args.redecode, args.basis)
    elif args.audit_transmon:
        audit_transmon()
    elif args.audit:
        audit()
    else:
        main()
