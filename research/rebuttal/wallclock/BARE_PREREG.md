# Bare-transmon break-even: pre-registration (P1; B-W, B-1, B-Q, M2)

> Historical design. The active direct comparison is specified in [README.md](README.md).
> The fidelity-based crossover, detector mapping and timing assumptions below are not admitted paper claims.
> The reporting change was made after preliminary results were seen; see `../response_log.md`.

Written 2026-10-08, before any run that compares dual rail with a transmon. It implements `BARE_DESIGN.md` with the PI's framing (Evan, via prism-66): "we shouldnt need to state a specific transmon processor, just give a reasonable range and do sensitivity sweep/analysis." Section 9 lists every departure from the design.

Before this file was committed, only two kinds of run had been made: the transmon compile timing probe, and the check of the transmon fidelity model against the simulator (`validate_bare.py`, section 4). Neither produces a dual-rail-against-transmon number.

## 1. Question and headline

B asks at what logical-qubit count dual rail with PRISM overtakes a bare-qubit baseline in total execution time. The answer we report is a threshold on the transmon instead of a verdict against one device.

- **Headline.** The break-even transmon two-qubit (CZ) error r*(n), for each dual-rail compiler (PRISM, Greedy, Logical-SABRE), at n = 4, 8, 12 and 16 logical qubits. Dual rail with that compiler is faster in wall-clock than any transmon whose CZ error is above r*(n), with the transmon's other parameters at their central values.
- **Sensitivity.** How r*(n) moves when each other parameter goes to either end of its range (section 2). The envelope of these one-at-a-time values is the figure's band.
- **PRISM's effect.** r*_PRISM / r*_Greedy and r*_PRISM / r*_Logical-SABRE, with paired seed intervals. A ratio below 1 means that PRISM extends the set of transmons dual rail beats.
- No processor is named or marked. The figure shows the reported range of transmon CZ errors, 1.0e-3 to 3.3e-3, as an unlabelled band.

## 2. Parameters and ranges

The citations below stay in these notes. They do not go in the figure.

**Error convention.** A published transmon error is the randomized-benchmarking average gate error r. IBM defines its 2Q error as "Average gate fidelity of the two-qubit operation from randomized benchmarking", and Google's Willow spec sheet says errors are "reported as 'average error'". The simulator's depolarizing channel ρ → (1 − p)ρ + p I/d has r = p(d − 1)/d. So p_2q = 4r/3 and p_1q = 2 r_1q, converted in one place (`bare.Transmon`). IBM's 2Q number includes the layer of single-qubit Cliffords. We still add the compiled 1q gates' own error, which double-counts slightly against the transmon.

**Transmon** (`bare.VARIANTS`). Each parameter has a central value and two range ends.

| Parameter | Low end | Central | High end | Sources |
|---|---|---|---|---|
| CZ error r | swept, grid 1e-4 to 3e-2 (81 log points) | (output) | | reported range 1.0e-3 (Li et al., PRX 14, 041050, arXiv:2402.18926: "CZ-gate fidelity of 99.90 ± 0.01%") to 3.3e-3 (Willow spec sheet, chip 1: "0.33% ± 0.18% (CZ)"). Heron r2 median 2.848e-3 (AbuGhanem, arXiv:2410.00916, Table IV) lies inside |
| 1q error | 1.5e-4 | 2.88e-4 | 3.5e-4 | Li et al. App. G: 99.985% and 99.981%; AbuGhanem Table IV: SX 2.88e-4 (ibm_fez median); Willow spec sheet: 0.035% |
| T1 | 68 µs | 136.5 µs | 262.7 µs | Willow, arXiv:2408.13687: "mean operating T1 of 68 µs"; AbuGhanem Table IV: 136.52 µs (ibm_fez median); AbuGhanem: Eagle median "T1: 262.69 µs" |
| T2 | 78.6 µs | 89 µs | 2 T1 (no pure dephasing: ideal dynamical decoupling) | AbuGhanem Table IV: 78.58 µs (Hahn echo, ibm_fez median); Willow: "T2,CPMG of 89 µs"; 2 T1 is the physical bound |
| Readout error | 3.4e-3 | 7.7e-3 | 1.63e-2 | IBM computers page, ibm_boston (Heron r3), read 2026-10-08, a live value; Willow spec sheet: "0.77%"; AbuGhanem Table IV: 0.0163 |
| Per-shot overhead o (readout, reset, repetition) | 0.66 µs | 15.9 µs | (central is the slow end) | arXiv:2207.06431, Fig. 1: "500 ns measurement and 160 ns reset"; Willow spec sheet: 63,000 circuit repetitions per second |

- Gate durations are fixed at the fastest sourced values, CZ 42 ns and 1q 25 ns (arXiv:2408.13687 SI), the transmon-favourable end.
- The transmon has no leakage, crosstalk, ZZ or state-preparation error, all in its favour.
- Readout is a symmetric X flip on each program qubit before the overlap.
- IBM's 3.8 kHz circuit rate (about 263 µs per shot) is left out. It is live, not archival, and it includes system latency that the dual-rail per-shot time below does not carry.

**Dual rail** (`sim.MEHTA`, `MODEL.md` §2, unchanged). The per-shot terms are applied after the fact with `detection.apply`.

| Parameter | Low end | Central | High end | Sources |
|---|---|---|---|---|
| SPAM erasure (false positive) f per pair | 0.51% | 6.6% | (central is the measured, high end) | de Graaf et al., arXiv:2406.14621: "only 0.51±0.02% are false positives"; Mehta et al., arXiv:2503.10935, Table III, SPAM [1 round] average erasure assignment 6.79e-2 and 6.43e-2 |
| Detection efficiency η | 0.963 | 0.996 | 0.9991 | de Graaf: "false negative error rate of pFN = 3.7(2)% per erasure check"; Mehta Table III, leakage detection error 3.5e-3 and 3.9e-3; de Graaf: "missed erasure fraction of (9.0 ± 0.5) × 10−4" |
| Check time t_check (terminal check and logical readout) | 1.82 µs | 4.8 µs | 12 µs | de Graaf: check pulse "Tp = 1.820 µs"; Chou et al., arXiv:2307.03169: logical measurement, "total duration of 4.8 µs for this sequence"; Koottandavida et al., arXiv:2311.04423: "The entire circuit takes exactly 12µs" |
| Logical misassignment m | fixed 2.15e-4 | | | Mehta Table III, 2e-4 and 2.3e-4 |
| Fixed per-shot time | 15.4 µs | | | preparation pulse of 1 µs (Chou Supp. III.E) plus a cavity reset of six successful measurements (Chou Supp. IV.A) of t_M 2.0 µs and 0.4 µs processing each (Chou Supp. Table I) |

- The photon is exposed for 1 µs + t_check per pair beyond the circuit, which is `detection.apply`'s τ. Loss during this exposure is at the cavity T1, and its dephasing counts as error.
- The dual-rail reset is held fixed. Only the transmon's per-shot overhead goes down to a hardware floor, which favours the transmon.

## 3. Arms, compile and fairness

- **Dual rail.** The existing MEHTA rows `data/v2_n{8,12,16}.jsonl`, plus new n = 4 rows from `run.py --device mehta --width 4 --transmon none` (exact). Compile seeds are 0, 100, 200, 300 and 400 on grid and hex_lattice, with 2(n+1) rails.
- **Transmon** (`bare.py`). It is recompiled; the legacy circuits are not reused.
  - Chip: the same 2(n+1)-node grid and hex_lattice (`make_topologies`). Basis {CZ, SX, X, RZ}, with no native SWAP.
  - Compiler: Qiskit 2.4.1 `transpile(optimization_level=3)`, then the same `RescheduleCommutingDiagonals` as the dual-rail arms.
  - Candidates: for each cell, stock O3 and the dual-rail logical optimizer followed by O3, at transpiler seeds s, s+1, …, s+39. The cell keeps the candidate with the highest ESP, ln ESP = Σ_gates ln(1 − r_g) − Σ_active qubits idle·(1/T1 + 1/T_φ), at the central parameters (`best40`). The best of the first pair is kept as `best1`. The transpiler seeds of different compile seeds stay at least 60 apart.
  - The all-to-all ceiling compiles each workload with no coupling map, so it has no SWAPs (`all_to_all`).
- **Fairness.** The transmon gets the same chip as dual rail. It runs k = 2 copies in parallel, so its wall-clock is divided by 2 (headline), and each copy keeps the whole chip's routing room. That is an upper bound, because real copies need disjoint qubits. k = 1 is a sensitivity row. A cavity rail is not a transmon, so counting rails as qubits undercounts dual-rail hardware; we follow B's accounting.
- **Workloads.** The 16 core workloads at n = 8, 12 and 16. At n = 4 three are missing:
  - vbe_ripple_carry_adder has no n = 4 manifest;
  - draper_qft_adder and hhl fail in the dual-rail logical optimizer (`DualRail.logical_pm`, a TranspilerError on their custom gates). Fixing that is a src/ change, which this task does not make.

  Both arms use the same set at every width.

## 4. Transmon fidelity: a per-circuit model, checked against the simulator

A full trajectory simulation of every transmon point is not affordable at n = 16, at about 25 CPU-min per circuit and point. So F comes from one ideal-statevector pass per compiled circuit (`bare.fingerprint`), and all transmon parameters become a closed-form sweep (`bare.log_fidelity`).

- At each noise location, the model records the exact fidelity of the local channel applied to the ideal state there:
  - each CZ: depolarizing p_2q;
  - each SX and X: depolarizing p_1q;
  - each per-qubit interval between gates, including the gate's own duration: amplitude damping at T1 and pure dephasing at T_φ, with 1/T_φ = 1/T2 − 1/(2T1);
  - each program qubit's readout flip.
- F is the product of these local fidelities. It is exact to first order in the error rates.
- The fidelity is that of the program qubits' reduced state. A location on a qubit whose content ends as an ancilla, after that qubit's last CZ, cannot reach the program qubits, so it is skipped. The dual-rail simulator likewise tracks live pairs only.
- **What the check found before any comparison** (`validate_bare.py`, workloads on the grid at seed 0, best of one pair, against `sim.simulate_bare` extended with program-qubit fidelity and readout).
  - The model under-estimates the transmon's F. It leaves out error pairs that cancel or compose on the same support, for example Z errors on either side of diagonal gates.
  - The relative error of ln F grows with |ln F|:
    - n = 8, exact: median 1.6% at r = 3e-3 and 3.3% at 1e-2, at most 12.6% (multiplier);
    - n = 12 qft, trajectories: about 13%.
  - Each noise source shows it alone, at 2–4% of ln F for |ln F| ≈ 0.4–1: CZ, 1q, T1 and T_φ (dephasing is the largest).
  - An under-estimated transmon F lowers r*, in dual rail's favour.
- **Calibration (the headline uses it).** ln F = ln F_model + c_n (ln F_model)². c_n is fitted per width by least squares on ln F_sim − ln F_model, weighted by 1/SE² with a relative SE floor of 1e-3 (`validate_bare.calibration`).
  - Calibration rows: every workload on the grid at seed 0.
    - n = 4 and 8: exact density matrix, five points (central at r = 1e-3, 3e-3 and 1e-2, the all-best corner, T1 68 µs with readout 1.63e-2).
    - n = 12: 1024 trajectories at central r = 1e-3, central r = 3e-3 and the all-best corner.
    - n = 16: 256 trajectories at central r = 1e-3 and the all-best corner.
  - Fitted before this commit: c_4 = 0.104, c_8 = 0.0301. The n = 8 calibrated residual is 0.5% of ln F at the median and 4% at most. c_12 and c_16 come from runs started at this commit and are recorded in section 4a without change.
  - **Rule.** The calibrated model is used at every width. The uncalibrated model is reported as a row (dual-rail-favourable). If c_16 has a standard error above half its value, c_16 = c_12 is used instead, and that is stated.

### 4a. Calibration constants

- c_4 = 0.104 (SE 0.003), c_8 = 0.0301 (SE 0.0001), both exact.
- c_12, c_16: pending, filled in from `data/validate_bare_n{12,16}.jsonl`.

## 5. Metrics

Task: estimate ⟨O⟩ of the ideal output state, with ‖O‖ ≤ 1, to a fixed additive precision, unbiased. Both arms are compared at the same precision, so it cancels.

- **Raw shots.** N = C / P.
  - P is the dual-rail keep probability from `detection.apply`, which includes f and η. P = 1 for the transmon.
  - C is the unbiased-mitigation cost of the kept-shot noise. Headline: C = 1/λ², with λ = (2ⁿF − 1)/(2ⁿ − 1), on both arms. This is the global-depolarizing attenuation, and rescaling attains it (Tsubouchi, Sagawa, Yoshioka, PRL 131, 210601, Eq. 7).
  - F is the kept-shot fidelity of the n program qubits, including readout (transmon) and logical misassignment (dual rail, F·(1 − m)ⁿ, a lower bound that is pessimistic for dual rail).
  - If λ ≤ 0, N is infinite.
- **PEC bracket** (sensitivity only). C = γ² with γ = exp(2ε), where ε is the total Pauli error probability of the circuit (van den Berg et al., Nat. Phys. 19, 1116).
  - Transmon: CZ (15/16)p_2q, 1q (3/4)p_1q, T1 and T_φ over the duration on every active qubit, readout.
  - Dual rail: CR_z and beamsplitter residual Z, dephasing over the duration plus exposure on every rail, misassignment.
- **Wall-clock.** T = N · t_shot / k.
  - Dual rail: t_shot = D + 15.4 µs + t_check, k = 1.
  - Transmon: t_shot = D + o, k = 2.
- **W(r).** The geometric mean over workloads of [mean T_dualrail / mean T_transmon(r)], with each mean over the two topologies and five seeds (the mean of costs, not of their inverses). The all-to-all transmon has one value per workload.
- **r*.** The r where W(r) = 1. It is found by linear interpolation of ln W in ln r on the 81-point grid. W falls with r. If W < 1 already at 1e-4, r* is reported as "< 1e-4"; if W > 1 at 3e-2, as "> 3e-2".
- **Workload set.** The viable set: workloads where Greedy keeps at least 1% of its shots with ideal checks (1 / seed mean of 1/P_keep ≥ 0.01, the `README.md` rule) on both grid and hex. It is fixed per width and independent of every parameter here. An all-workload row is reported too.
- **Intervals.** 1000 resamples of the five compile seeds (seed 0 of the generator), with the same indices for dual rail and transmon and for both topologies. Each interval is a 95% percentile interval. The PRISM ratios and the width trend r*(16)/r*(8) use the same resamples.
- **Also reported, with no reading attached.**
  - Per-workload r* (median and range).
  - The shot ratio S and the break-even per-shot ratio τ* = 1/(kS) at r = 1.0e-3 and 3.3e-3.
  - Panel (b)'s numbers.

## 6. Sensitivity rows (each gives r*(n) for every compiler and width)

- **One at a time, forming the band.** Transmon 1q error low and high; T1 low and high; T2 low and 2T1; readout low and high; per-shot overhead 0.66 µs. Dual rail f 0.51%; η 0.963 and 0.9991; t_check 1.82 and 12 µs.
- **Reported separately, outside the band.**
  - k = 1;
  - PEC γ²;
  - transmon best of 1 (compiler effort);
  - transmon all-to-all ceiling;
  - all workloads;
  - transmon model uncalibrated (c_n = 0);
  - transmon-favourable corner: every transmon parameter at its best, o 0.66 µs, η 0.963, t_check 12 µs, f 6.6%;
  - dual-rail-favourable corner: every transmon parameter at its worst, f 0.51%, η 0.9991, t_check 1.82 µs.

## 7. Reading rule (fixed now)

Let R = [1.0e-3, 3.3e-3] be the reported transmon CZ range, and let the band be the envelope of section 6's one-at-a-time rows.

1. **r*_PRISM(n) is below 1.0e-3 at some n.** Say that, from that n, dual rail with PRISM is faster in wall-clock than every transmon in the reported range at central parameters. Then check whether the band's upper edge is also below 1.0e-3. Only if it is, say "for every parameter in its range".
2. **r*_PRISM(n) is inside R.** Say: "faster than transmons whose CZ error exceeds r*(n), slower than better ones", with the band.
3. **r*_PRISM(n) is above 3.3e-3 at every n (dual rail loses everywhere).** Say: "postselected dual rail at Mehta et al.'s measured parameters is slower in wall-clock than every transmon in the reported range up to n = 16".
   - Give the trend r*(16)/r*(8) and PRISM's ratios.
   - Name the dual-rail parameter whose range end moves r* most, and say whether that end brings r* into R.
   - Nothing is re-tuned.
4. **Mixed cases.** If case 1, 2 or 3 differs between n, report each width's case. A width trend ("dual rail gains with width") is claimed only if the r*(16)/r*(8) interval excludes 1.
5. **SPAM.** If the f = 0.51% row puts any width in a different case from the headline, name SPAM erasure as the deciding parameter and give both values.
6. **PRISM.** "PRISM raises (or lowers) the break-even CZ error by X% against Greedy" is stated only where the paired interval excludes 1. Otherwise say the compilers are indistinguishable at that width.
7. **No re-tuning.** No range, central value, metric or workload set changes after the first comparison number. Any later change is a deviation, logged in section 10 with its reason, and the pre-registered value is still reported.

The sentence template for B: "At n logical qubits, dual rail with PRISM is faster in wall-clock than any transmon whose CZ error exceeds r*(n) (band [lo, hi] over the other transmon and dual-rail parameters' published ranges)."

## 8. Figure (single column, two panels, `bare_figure.py` → `data/figures/bare_breakeven.pdf`)

- **(a) r*(n) against logical qubits n = 4, 8, 12, 16**, log y.
  - One line per compiler (PRISM, Greedy, Logical-SABRE), with 95% seed intervals as error bars and the one-at-a-time sensitivity band shaded.
  - An unlabelled grey horizontal band for the reported transmon CZ range, with no device names.
  - The region above a curve is annotated "dual rail faster".
- **(b) n = 16, kept-shot infidelity 1 − F against time per kept shot**, both log.
  - Time per kept shot: t_shot/P for dual rail, t_shot/k for the transmon. Each is the geometric mean over viable workloads of topology and seed means.
  - One point per dual-rail compiler.
  - The transmon is a line over the reported CZ range, with end markers at 1.0e-3 and 3.3e-3 and no device names.
  - This panel does not depend on the variance model.
- Caption facts: the headline setting, k = 2, and the variance model C = 1/λ².

## 9. Departures from BARE_DESIGN.md (decided before any comparison)

- **No device markers or named processors.** These are the PI's instructions. Every transmon parameter has a range, and the headline uses the central values.
- **The design's "best pair against best pair" headline** (Li et al.'s pair at fixed T1/T2) is replaced by central values with ranges. The transmon-favourable corner row covers the best-pair case.
- **1q error** has its own range instead of r/10. The CZ time scaling of T1 is dropped, because gate times are fixed at the fastest sourced values.
- **Transmon F comes from the per-circuit model, calibrated to the simulator** (section 4), not from simulating every point, because simulation is too slow at n ≥ 12. The separability fallback of `1662bf6` is not needed.
- **Per-shot time** has explicit components and ranges instead of the τ* output alone. τ* is still printed.
- **Heavy-hex is dropped.** make_topologies sizes it above 2(n+1), which breaks the same-chip rule, and the all-to-all ceiling bounds every topology from above.
- **n = 4 has 13 workloads** (section 3).
- **Viable set:** the 1% rule must hold on both topologies.

## 10. Deviations after the first comparison number

1. **n = 16 calibration subset** (2026-10-08 12:55, before c_12 or c_16 was known).
   - **Why.** The pre-registered n = 16 calibration (all 16 workloads, 256 trajectories, two points) projected to more than 30 CPU-h. The large workloads take 2 to 3 hours per point: qaoa, bmw_quark_copula, cdkm, and multiplier at 5086 gates.
   - **Rule, fixed before any n = 16 calibration row.** Calibrate on the workloads whose projected cost is at most 60 CPU-min per point at 256 trajectories and whose model F at central r = 1e-3 is at least 0.05, so that 256 trajectories resolve F. Use the central r = 1e-3 point only. Nine workloads: dj, draper_qft_adder, modular_adder, qft, qpeexact, qpeinexact, qftentangled, ae and vbe_ripple_carry_adder.
   - The c_16 fallback rule of section 4 is unchanged.
2. **Disclosure.** To debug `bare_report.py`, it was run in memory on n = 4 and 8 only, with c_4 and c_8 as committed, before the n = 12 and n = 16 rows existed. Nothing in the procedure has been changed since.

3. **Reporting and source interpretation audit (2026-10-08, after preliminary crossover numbers were shared).** The user requested a less contrived comparison. The response now prioritizes conditional output-state fidelity and acceptance on the full workload set, with resources and circuit duration explicit. The fidelity-to-mitigation-cost conversion and detector-parameter mappings in the original design are not cleared for paper admission. See the dated P1/H1/H2 audit in `../response_log.md` for the primary sources, the conditional-versus-unconditional detection distinction, the direct eight-qubit diagnostic, and the draft response. This is a reporting change after results were seen; the original parameter tables, runs, and crossover calculation above are retained as history. No range or calibration is retuned by this entry.
