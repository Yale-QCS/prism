# Which shot-overhead number the abstract can carry (prism-66, 2026-10-07)

Source: `artifacts/paper/raw/scale.jsonl`, 2120 rows (64f6245), five seeds (0 to 400). The run compiled `multiplier` through 16 logical qubits and `rg_qft_multiplier` through 24, so each width has 16 workloads from 8 to 16, 15 at 20 and 24, and 14 at 28 and 32. The rows were scored with the recalibrated Eq. 1 (`mehta`, 754818d). The tables below are `artifacts/paper/paper_export/device/by_width.csv` (484270a).

## The problem with 33.5–40.9%

The block 09/10 headline (Greedy needs 1.50× / 1.69× PRISM's shots at 16 logical qubits) is the geomean over workloads of the shot-overhead ratio. Two workloads carry it:

| n = 16 | expected photon losses per shot, Greedy / PRISM | Greedy's keep probability | Greedy / PRISM shots |
|---|---|---|---|
| multiplier, grid | 13.5 / 11.4 | about 1e-6 | 8.5× |
| rg_qft_multiplier, grid | 13.3 / 11.5 | about 1e-6 | 6.4× |
| other 14 workloads, grid | 0.3–4.8 | 0.8%–75% | 1.00–1.79× |

Without those two, the geomean is 1.20× (grid) and 1.33× (hex). The shot ratio is exp(ΔL), where ΔL is the absolute difference in expected losses, so it is largest exactly where postselection cannot run. At 32 logical qubits the same effect gives 6.9× and 10.5×, from workloads that keep about 1 shot in 10^13. A reviewer who reads the per-workload figure will see this. The "suite-mean keep probability 0.14–0.17" also hides it.

## What the rows support

The exponent itself: −ln P_keep is the expected number of photon losses per shot. PRISM's reduction of it is scale-free, holds on every workload from n = 12, and grows with width. Geomean over workloads, 95% paired seed intervals:

| n | grid | hex | workloads with fewer losses |
|---|---|---|---|
| 8 | 5.4% [4.3, 6.3] | 5.6% [5.3, 6.0] | 14/16, 16/16 |
| 12 | 7.8% [7.1, 8.7] | 9.0% [8.7, 9.2] | 16/16 |
| 16 | 8.9% [8.4, 9.6] | 11.6% [11.1, 12.1] | 16/16 |
| 20 | 11.2% [10.5, 11.8] | 13.1% [12.7, 13.5] | 15/15 |
| 24 | 12.8% [12.3, 13.3] | 15.2% [14.8, 15.5] | 15/15 |
| 28 | 12.9% [12.1, 13.4] | 15.4% [14.7, 16.2] | 14/14 |
| 32 | 14.8% [14.1, 15.7] | 16.6% [15.9, 17.2] | 14/14 |

Shots, on the workloads postselection can run (Greedy keeps at least 1% of shots; threshold fixed here before any further cut):

| n | grid: workloads, geomean, max | hex: workloads, geomean, max |
|---|---|---|
| 16 | 13, 1.16×, 1.43× | 13, 1.27×, 1.73× |
| 20 | 10, 1.36×, 1.60× | 10, 1.47×, 1.80× |
| 24 | 6, 1.67×, 2.48× | 3, 1.38×, 2.06× |

## Proposed sentence (needs Evan)

> On a device model calibrated to measured dual-rail hardware, PRISM's routes remove 8.9--11.6\% of the photon losses each shot incurs at 16 logical qubits, and 14.8--16.6\% at 32. Because a shot survives only if no photon is lost, this compounds: at 20 logical qubits, Greedy needs 1.36--1.47$\times$ PRISM's shots on the workloads postselection can still run.

## What changed with the final rows

- The n = 24 loss row now has 15 workloads, because `rg_qft_multiplier` finished at 24. It was 12.5% [11.9, 13.1] and 15.1% [14.7, 15.4] on 14 workloads.
- This note gave the n = 16 grid losses as 13.6 / 11.5 for `multiplier` and 13.4 / 11.5 for `rg_qft_multiplier`. The 2100-row file and the final rows both give 13.5 / 11.4 and 13.3 / 11.5, so the old values were errors in this note, not a change in the rows. The shot ratios (8.5× and 6.4×) and the geomeans without the two workloads (1.20× and 1.33×) were correct.
- The other rows of both tables and every number in the proposed sentence match `by_width.csv`.
