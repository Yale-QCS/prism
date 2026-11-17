"""Isolate the value of erasure flags on the fixed Steane routes; no hardware comparison."""

import hashlib
import itertools
import json
from pathlib import Path
import numpy as np
from numba import njit

from erasure_report import DATA, SEEDS, PROBABILITIES

@njit(cache=True)
def fwht(values):
    """Transform an XOR convolution in place with the Walsh-Hadamard transform."""
    width = 1
    while width < len(values):
        for start in range(0, len(values), 2 * width):
            for j in range(start, start + width):
                left, right = values[j], values[j + width]
                values[j], values[j + width] = left + right, left - right
        width *= 2
    return values


def spectrum(columns, n_detectors):
    """Count locations with a nontrivial character at each transform frequency."""
    # A hidden replacement is I with probability 1-3p/4 and X/Y/Z with p/4.
    # Its character is 1 when both fault columns have even parity, else 1-p.
    # XOR convolution multiplies these characters across independent locations.
    multiplicity = np.zeros(1 << (n_detectors + 1), dtype=np.float64)
    for x, z in columns:
        for signature in (0, x, z, x ^ z):
            multiplicity[signature] += 1
    weights = len(columns) - fwht(multiplicity) / 4
    assert np.all(weights == np.rint(weights))
    assert weights.min() == 0 and weights.max() <= len(columns)
    return weights


def distribution(weights, p):
    """Return joint P(syndrome, logical flip), including both logical cosets."""
    joint = fwht(np.power(1 - p, weights)) / len(weights)
    assert abs(joint.sum() - 1) < 1e-10
    assert abs(joint[joint < 0].sum()) < 1e-10
    return np.maximum(joint, 0).reshape(-1, 2)


def single_fault_coefficient(columns):
    """Return the linear-in-p optimal error when flags are hidden."""
    counts = {}
    for x, z in columns:
        for signature in (x, z, x ^ z):
            counts.setdefault(signature >> 1, [0, 0])[signature & 1] += 1
    # No fault dominates syndrome zero. Else choose the more frequent logical value.
    return (counts.get(0, [0, 0])[1] + sum(min(v) for s, v in counts.items() if s)) / 4


def check():
    """Compare the full joint distribution with exhaustive Pauli enumeration."""
    rng = np.random.default_rng(71)
    for n_detectors in range(4):
        for n_sites in range(1, 7):
            columns = rng.integers(0, 1 << (n_detectors + 1), size=(n_sites, 2))
            for p in (0, .003, .1, 1):
                direct = np.zeros(1 << (n_detectors + 1))
                for faults in itertools.product(range(4), repeat=n_sites):
                    signature, mass = 0, 1
                    for (x, z), fault in zip(columns, faults):
                        signature ^= (0, x, z, x ^ z)[fault]
                        mass *= 1 - 3 * p / 4 if fault == 0 else p / 4
                    direct[signature] += mass
                actual = distribution(spectrum(columns, n_detectors), p).ravel()
                assert np.allclose(actual, direct, atol=1e-12, rtol=1e-11)
            leading = distribution(spectrum(columns, n_detectors), 1e-7).min(axis=1).sum() / 1e-7
            assert abs(leading - single_fault_coefficient(columns)) < 1e-5
    print('96 exhaustive distribution checks and 24 single-fault limits passed', flush=True)


def audit(row, weights):
    """Hide every flag from the posterior decoder on actual noisy Stim samples."""
    import stim
    from erasure_pilot import with_heralds
    cell = f"{row['basis']}_{row['topo']}_{row['arm']}_0"
    circ = stim.Circuit((DATA / f"{cell}.stim").read_text())
    records = []
    for p in (0.003, 0.01):
        joint = distribution(weights, p)
        prediction = joint[:, 1] > joint[:, 0]
        expected = float(joint.min(axis=1).sum())
        noisy = with_heralds(circ, row['sites'], p)
        shots = 100_000
        detectors, obs = noisy.compile_detector_sampler(seed=20261012).sample(
            shots, separate_observables=True)
        # The suffix contains flags. They never enter this decoder's input.
        powers = np.left_shift(np.uint64(1), np.arange(row['n_detectors'], dtype=np.uint64))
        syndromes = detectors[:, :row['n_detectors']].astype(np.uint64) @ powers
        errors = int(np.count_nonzero(prediction[syndromes] != obs[:, 0]))
        z = (errors / shots - expected) / np.sqrt(expected * (1-expected) / shots)
        assert abs(z) < 5, (cell, p, z)
        records.append(dict(cell=cell, p=p, shots=shots, errors=errors, expected=expected, z=float(z)))
    return records


def main():
    check()
    source = DATA / 'summary.json'
    prior = json.loads(source.read_text())
    picks = np.random.default_rng(0).integers(0, len(SEEDS), size=(20_000, len(SEEDS)))
    records, audits = [], []
    for basis, topo, arm, seed in itertools.product(
        ('X', 'Z'), ('grid', 'hex_lattice'), ('greedy', 'prism'), SEEDS
    ):
        name = f'{basis}_{topo}_{arm}_{seed}.json'
        path = DATA / name
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == prior['row_sha256'][name], name
        row = json.loads(path.read_text())
        weights = spectrum(row['columns'], row['n_detectors'])
        if seed == 0:
            audits.extend(audit(row, weights))
        rates = [float(distribution(weights, p).min(axis=1).sum()) for p in PROBABILITIES]
        flagged = [r['probability'] / 2 for r in row['results']]
        assert all(h >= f for h, f in zip(rates, flagged))
        records.append(dict(source=name, sha256=digest, basis=basis, topo=topo,
                            arm=arm, seed=seed, hidden=rates, flags=flagged,
                            hidden_single_fault_coefficient=single_fault_coefficient(row['columns'])))
        if seed == SEEDS[-1]:
            print('Completed', basis, topo, arm, flush=True)
    results = []
    for basis, topo, i in itertools.product(('X', 'Z'), ('grid', 'hex_lattice'), range(len(PROBABILITIES))):
        entry = dict(basis=basis, topo=topo, p=PROBABILITIES[i], arms={})
        arrays = {}
        for arm in ('greedy', 'prism'):
            rr = [r for r in records if (r['basis'], r['topo'], r['arm']) == (basis, topo, arm)]
            assert [r['seed'] for r in rr] == SEEDS
            arrays[arm] = {mode: np.array([r[mode][i] for r in rr]) for mode in ('hidden', 'flags')}
            cells = {}
            for mode, values in arrays[arm].items():
                low, high = np.quantile(values[picks].mean(axis=1), [.025, .975])
                cells[mode] = dict(mean=float(values.mean()), seed_95=[float(low), float(high)])
            observed = round(sum(r['flags'][i] for r in rr) * 400_000)
            cells['ambiguous_count'] = observed
            if observed >= 100:
                ratios = arrays[arm]['hidden'][picks].sum(axis=1) / arrays[arm]['flags'][picks].sum(axis=1)
                cells['flag_gain_factor'] = cells['hidden']['mean'] / cells['flags']['mean']
                cells['flag_gain_factor_95'] = np.quantile(ratios, [.025, .975]).tolist()
            entry['arms'][arm] = cells
        results.append(entry)
    result = dict(description=__doc__, summary_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  channel='Same independent uniform replacement; only the decoder flag input changes',
                  seeds=SEEDS, probabilities=PROBABILITIES, records=records,
                  audits=audits, exhaustive_checks=96, single_fault_limit_checks=24,
                  limitation='All routes have single-fault ambiguity when flags are hidden; the extraction schedule is not a Pauli-fault-tolerant baseline',
                  results=results)
    (DATA / 'flag_control.json').write_text(json.dumps(result, indent=2) + '\n')
    plot(result)
    for r in results:
        if r['p'] not in (.003, .01):
            continue
        print(r['basis'], r['topo'], 'p=', r['p'])
        for arm, d in r['arms'].items():
            print(arm, 'hidden %', 100*d['hidden']['mean'], 'flags %', 100*d['flags']['mean'],
                  'flag gain', d.get('flag_gain_factor'), flush=True)
    print('Validated', len(records), 'routes;', sum(r['shots'] for r in audits),
          'direct circuit samples; max audit |z|', max(abs(r['z']) for r in audits), flush=True)


def plot(result):
    """Show every fixed sweep point, marking low-count flag estimates separately."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    fig, axes = plt.subplots(2, 2, figsize=(8.2, 7.0), sharex=True, sharey=True)
    colors = {'greedy': '#c16e14', 'prism': '#1768a3'}
    for ax, (basis, topo) in zip(axes.flat, itertools.product(('X', 'Z'), ('grid', 'hex_lattice'))):
        rows = [r for r in result['results'] if (r['basis'], r['topo']) == (basis, topo)]
        for arm in ('greedy', 'prism'):
            for mode, style in [('hidden', '--'), ('flags', '-')]:
                y = np.array([100*r['arms'][arm][mode]['mean'] for r in rows])
                lo = np.array([100*r['arms'][arm][mode]['seed_95'][0] for r in rows])
                hi = np.array([100*r['arms'][arm][mode]['seed_95'][1] for r in rows])
                ax.plot(PROBABILITIES, np.where(y > 0, y, np.nan), style, color=colors[arm], lw=1.7)
                ax.fill_between(PROBABILITIES, np.where(lo > 0, lo, np.nan), hi, color=colors[arm], alpha=.11)
                for j, p in enumerate(PROBABILITIES):
                    low_count = mode == 'flags' and rows[j]['arms'][arm]['ambiguous_count'] < 100
                    if y[j] > 0:
                        ax.plot(p, y[j], 'o', ms=4, color=colors[arm], mfc='white' if low_count else colors[arm])
                    else:
                        # One-sided 95% bound on zero ambiguous events, divided by two.
                        upper = 100 * (-np.expm1(np.log(.05)/4_000_000)) / 2
                        ax.plot(p, upper, 'v', ms=5, color=colors[arm], mfc='white')
        ax.set_title(f"{basis} memory / {'grid' if topo == 'grid' else 'hexagonal'}", fontsize=11)
        ax.set_xscale('log'); ax.set_yscale('log')
        ax.grid(alpha=.18, which='major')
        ax.tick_params(labelsize=9)
    for ax in axes[:, 0]:
        ax.set_ylabel('Logical error probability (%)', fontsize=10)
    for ax in axes[1]:
        ax.set_xlabel('Erasure probability per location, p', fontsize=10)
    handles = [Line2D([], [], color=colors[a], lw=2, label=a.title() if a=='greedy' else 'PRISM') for a in colors]
    handles += [Line2D([], [], color='#444', ls=s, label=l) for s,l in [('--','Flags withheld'),('-','Flags supplied')]]
    fig.legend(handles=handles, loc='upper center', ncol=4, frameon=False, fontsize=10)
    fig.text(.5, .02, 'Same Steane circuits and noise; optimal decoding in each condition. Ideal checks and replacement.\nThe extraction schedule is not single-fault tolerant without flags. This is not a transmon comparison.\nBands: 95% seed intervals. Open circles: fewer than 100 ambiguous events. Triangle: 95% upper bound.',
             ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .115, 1, .93))
    fig.savefig(DATA / 'flag_control.png', dpi=180)
    plt.close(fig)


if __name__ == '__main__':
    main()
