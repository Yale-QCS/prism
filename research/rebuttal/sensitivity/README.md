# sensitivity: PRISM's margin over Greedy across cavity lifetime and beamsplitter duration (B-2, D-5)

Reviewers B-2 and D-5 ask how PRISM's loss advantage depends on the device. This directory re-values the saved n = 8, 12, 16 routes of both compilers over a grid of two physical parameters, the cavity lifetime T1 and the beamsplitter duration t_bs, and reports PRISM's expected losses relative to Greedy's. `figures/sensitivity.pdf` is the one-column figure proposed for Section V-D. A first version of this directory swept multipliers on the fitted per-gate erasure numbers; it was replaced because multipliers are not device parameters.

## Model

The device is `sim.MEHTA` of `research/rebuttal/wallclock/sim.py` (Mehta et al., arXiv:2503.10935; `MODEL.md` section 2). The expected loss exponent of a routed circuit is the closed form of `MODEL.md` section 3,

    -ln P_keep = I / T1 + N_crz [-ln(1 - e_c) - ln(1 - e_t)] + B [-ln(1 - e_bs)],

where I is the summed live-pair idle time, N_crz the CR_z count and B the number of beamsplitter pair-touches (one per intra-pair rswap, two for a routing SWAP between live pairs, one for a SWAP into an empty rail). On every saved circuit it matches the simulated -ln P_keep of the `v2_*` rows to 1e-12 relative (`extract.py` asserts this at the measured point).

The sweep moves two physical parameters and nothing else.

- Cavity lifetime T1, swept over 100 us to 2 ms, log-spaced, with the measured 356.5 us (the rate average of Mehta's four cavities) and Mehta's extreme cavities 231 and 652 us on the grid: T1 = 100, 150, 231, 356.5, 500, 652, 1000, 1500, 2000 us. Anchors: Mehta Table 2, 231 to 652 us per cavity; Chou et al. 2023, about 500 us; the best 3D cavities, in the ms range.
- Beamsplitter duration t_bs, swept over 50 to 500 ns with the measured 200 ns and Mehta's fastest 136 ns on the grid: t_bs = 50, 70, 100, 136, 200, 300, 400, 500 ns. Anchors: Teoh et al. propose 50 to 100 ns; Mehta measured 136 to 208 ns.
- Erasure per beamsplitter pair-touch e_bs(t_bs, T1) = t_bs / T1 + c_bs. The measured beamsplitter erasure 7.24e-4 at 200 ns is mostly cavity decay during the pulse (0.2 / 356.5 = 5.61e-4); the rest, c_bs = 7.24e-4 - 0.2 / 356.5 = 1.63e-4, is a coupler constant fixed by the measured point and held fixed. Idle loss I / T1 uses the same T1. The routing SWAP and the intra-pair rswap are the same physical operation and get the same t_bs and e_bs.
- CR_z is held at its measured values throughout: 500 ns, control-pair erasure 4.00e-3, target 0.96e-3. The control photon sits in the transmon coupler during the gate's wait, so this erasure is transmon-T1 limited, not cavity limited, and does not move with T1 or t_bs.
- Schedules are re-timed for each t_bs with the ASAP rail-clock scheduler of `validate._pair_schedule` (reimplemented in `extract.py` and checked equal to `validate.loss_parts` at 200 ns on every circuit), with CR_z fixed at 500 ns. Durations and idle times change with t_bs; the touch counts do not.
- Routes are fixed. Neither compiler re-routes under the changed device, so the sweep measures how the recorded routes are valued, not how either compiler would route if told the device had changed. The two parameters are perturbed jointly on the 9 x 8 grid.

Each cell is PRISM / Greedy of the expected loss exponent, computed as in `v2_report.ratio`: per workload the ratio of seed means, then the geometric mean over the 16 MQT workloads with equal weight, with a 95% interval from 1000 paired resamples of the 5 seeds (both arms resampled on the same seeds, and the same resamples in every cell). A ratio of 0.90 is a 10% reduction in expected losses.

## Does the margin collapse onto rho = t_bs / T1?

Not within the seed intervals. At each of eight values of rho (5e-5 to 3e-3) the ratio was evaluated at every grid T1 whose t_bs = rho T1 lies in 50 to 500 ns (2 to 6 points per rho). The point estimates at equal rho spread by at most 0.016 (rho = 4e-4, n = 8 grid; 0.015 at n = 16 grid, rho = 1e-4) while the interval half-widths are 0.001 to 0.008, and only 17 of the 48 (rho, n, topology) groups have every point inside every other point's interval. Against the 0.13 range of the ratio over the whole grid (0.83 to 0.98 at n = 16 hex) rho still explains most of the variation (`figures/collapse.png`, a diagnostic, not for the paper).

The residual is not the coupler constant: e_bs = rho + c_bs depends on rho alone. It is the fixed 500 ns CR_z. At fixed rho the exponent is rho I(t_bs) / t_bs + K_cz N_crz + B [-ln(1 - rho - c_bs)], and I(t_bs) / t_bs, the idle time in beamsplitter units, falls from about 12 000 at t_bs = 50 ns to 2 300 at 500 ns (n = 16, seed and workload means) because CR_z waits do not shrink with t_bs. Below the measured rho a longer T1 at fixed rho moves the ratio toward 1 (the idle term, where PRISM saves most, shrinks against the fixed CR_z term); above it the direction reverses (the beamsplitter erasure term, where PRISM's touch ratio is 0.75 to 0.77, gains weight). The figure is therefore a heatmap over (T1, t_bs) rather than one curve in rho.

## Data provenance

- Circuits: `research/rebuttal/wallclock/data/circuits_n{8,12,16}/{workload}_{topology}_{seed}_{arm}.qpy`, the Greedy and PRISM routes behind `research/rebuttal/wallclock/data/v2_n{8,12,16}.jsonl` (16 workloads, grid and hexagonal lattice, 5 seeds, 2 arms, 320 circuits per n). The `mehta` rows of those files give the simulated P_keep that the closed form is checked against.
- `data/parts_n{8,12,16}.jsonl`: per circuit, the touch counts (crz, bs_intra, swap2, swap1, B) and the summed idle time I at each of the 27 beamsplitter durations the sweep needs (`tbs_ns`, `I_tbs`), written by `extract.py` (3 workers, about 4 minutes).
- `data/sweep.json`: the model constants and grids (`model`), the measured-point `baseline`, the 9 x 8 `grid` cells, the equal-rho `collapse` cells and their `spread` summary, the literature-corner `anchors`, and a dense point-estimate `field` (49 T1 x 27 t_bs per n and topology) for the contours; each cell carries n, topology, t1_us, tbs_ns, rho, e_bs, ratio, lo, hi, n_worse. Written by `analyze.py`; `figure.py` reads only this file.

## Reproduce

    .venv/bin/python -W ignore research/rebuttal/sensitivity/extract.py   # writes data/parts_n*.jsonl
    .venv/bin/python -W ignore research/rebuttal/sensitivity/analyze.py   # writes data/sweep.json, prints the key numbers
    .venv/bin/python -W ignore research/rebuttal/sensitivity/figure.py    # writes figures/sensitivity.{pdf,png}, figures/collapse.png

## Key numbers (reduction in expected losses, PRISM versus Greedy, grid / hex)

| point | n = 8 | n = 12 | n = 16 |
|---|---|---|---|
| measured (356.5 us, 200 ns; reproduces the v2 report) | 4.6 / 5.4% | 7.4 / 8.4% | 9.6 / 11.0% |
| Mehta's slowest cavity and slowest beamsplitter (231 us, 208 ns) | 5.6 / 6.4% | 8.6 / 9.6% | 10.9 / 12.4% |
| ms-class cavity with Teoh's fastest beamsplitter (2 ms, 50 ns) | 1.6 / 1.7% | 2.5 / 2.9% | 3.5 / 3.9% |
| largest margin on the grid (100 us, 500 ns) | 8.3 / 9.7% | 12.4 / 14.2% | 14.8 / 16.8% |
| range over Mehta's own box (grid cells 231 to 652 us, 136 to 200 ns) | 3.1 to 5.5 / 3.5 to 6.3% | 5.1 to 8.5 / 5.8 to 9.5% | 6.9 to 10.8 / 7.9 to 12.2% |

- The margin grows with rho. At n = 16 hex it is 11.0% at the measured point, 12.4% at Mehta's worst corner, and shrinks to 3.9% [3.7%, 4.1%] at a 2 ms cavity driven with a 50 ns beamsplitter, where idle loss and beamsplitter erasure are both small against the fixed CR_z erasure (e_bs = 1.9e-4 against 4.96e-3 per CR_z).
- At the measured point 75% (grid) and 77% (hex) of the loss exponent PRISM saves at n = 16 is idle time; the rest is beamsplitter erasure on the routing SWAPs it avoids (PRISM touches 0.75 to 0.77 of Greedy's pairs, and idles 0.83 to 0.85 of Greedy's time).
- No grid cell has the equal-weight ratio above 1; the largest upper interval bound is 0.986 (n = 8 grid, 2 ms, 50 ns). Per workload, PRISM is behind at some cells on vbe_ripple_carry_adder (1.009), dj (1.007) and modular_adder (1.005) at n = 8 grid, dj (1.044 at 100 us, 500 ns) and qaoa (1.005) at n = 8 hex, dj (1.015) at n = 12 grid and dj (1.006 at 2 ms, 50 ns) at n = 16 hex; n = 12 hex and n = 16 grid have PRISM ahead on all 16 workloads at every cell.

## Figure

`figure.py` follows the paper's figure style (`lusca`, 3.35 in, 6.5 to 7.2 pt, `pdf.fonttype` 42). The heatmap is n = 16 on the hexagonal lattice over T1 (log) and t_bs (log) with one single-hue ramp (darker is a larger PRISM margin, the ramp runs light #f2f7f6 to dark #1d4f49 through the paper's PRISM teal), labelled contours every 0.02, the measured device as a star, and the literature ranges as brackets along the axes (Mehta's T1 and t_bs ranges, Teoh's proposed t_bs, ms-class cavities). `figures/collapse.png` is the diagnostic scatter of every grid cell against rho (grid #4c78a8 circles, hex #d9902f squares, marker size grows with n; the dataviz validator passes the pair on CVD and normal-vision separation and flags the blue's chroma and the orange's contrast, so identity is also carried by marker shape).

Proposed caption (57 words):

> Expected losses of \sysname{}'s routes relative to Greedy's at 16 logical qubits on the hexagonal lattice as the cavity lifetime and the beamsplitter duration move from their measured values (star). Beamsplitter erasure is cavity decay during the pulse plus a fixed coupler term, schedules are retimed, CR$_z$ is held at its measured values, routes are fixed. Lower is better.

Proposed Section V-D sentences (bracketed values become macros):

> The measured device fixes one point in a space of cavity lifetimes and beamsplitter durations, so we evaluate the saved routes again of both compilers across [100]~$\mu$s to [2]~ms and [50] to [500]~ns without rerouting (Fig.~\ref{fig:eval-sensitivity}). The loss reduction at 16 qubits grows from [11.0\%] at the measured point to [12.4\%] at the slowest cavity and beamsplitter Mehta et al. report and falls to [3.9\%] for a millisecond cavity driven with a 50~ns beamsplitter, where the fixed CR$_z$ erasure dominates, and \sysname{} never loses more than Greedy at any point of the grid.
