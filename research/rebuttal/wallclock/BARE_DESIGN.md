# Bare-transmon baseline (meta-review item 2, reviewer B): evaluation design

> Historical design. The active direct comparison is specified in [README.md](README.md).
> The fidelity-based crossover, detector mapping and timing assumptions below are not admitted paper claims.
> The reporting change was made after preliminary results were seen; see `../response_log.md`.

Design only, 2026-10-08. No runs were launched. Line numbers refer to the revision r2 working tree as of today. Literature numbers were read in the source PDFs or arXiv abstracts. The extracted texts are in this scratchpad (`pdfs/`, `pdfs2/`, `dl/`, `lit_transmon.md`, `lit_dualrail.md`).

## 0. Why P1 failed, and what this design changes

P1 failed on four counts (`wallclock/REDTEAM.md`; `README.md` ll. 206–211; `response_log.md` ll. 15–44):

1. **Error convention.** The transmon used depolarizing p = r. The channel in `sim._pauli_mixture` (`sim.py` ll. 361–364) has r = 3p/4 for two qubits and p/2 for one, so the transmon was flattered by 4/3.
2. **Lifetimes.** T1/T2 and the "strong" point were our own picks.
3. **Per-shot overhead.** It was one number (2 µs), and the verdict flips between 2 and 200 µs.
4. **Variance model.** 1/F² was asserted without support. Omissions cut both ways: no transmon readout error and no dynamical decoupling, but also no dual-rail SPAM erasure and native SWAP on the transmon.

The legacy transmon was also compiled on the dual-rail rail graph, with 2(n+1) nodes (`run.py` l. 85, `paper_common.make_topologies` ll. 20–42). That graph is twice the transmon's need, and nobody stated it.

This design removes each dependence instead of choosing a value:

- **Convention.** Fixed, using IBM's definition of its own error number.
- **Transmon quality.** It becomes the output, a break-even CZ error r*(n), instead of an input. Published devices are marked against r*(n).
- **Per-shot time.** It becomes a break-even ratio. The simulated shot ratio is reported separately from it.
- **Variance model.** It is justified by tightness theorems, applied identically to both arms, and bracketed by an implementable protocol (PEC).
- **Every omission.** Each is settled in the transmon's favour, or applied symmetrically.

**The finding that should shape the framing.** The fact below is computed from the existing rows: legacy transmon rows corrected only for readout, and MEHTA dual-rail rows with SPAM applied analytically. Against a transmon at the best-pair level (legacy "strong": CZ p = 1e-3, T1 = T2 = 300 µs), PRISM's shot ratio, defined as (1/(P_keep F²)) / (1/F_t²), gets worse from n = 8 to n = 12:

- with Mehta's measured SPAM erasure f = 6.6% and transmon readout error 1.63%: 1.44 → 2.09;
- with de Graaf's f = 0.5%: 0.87 → 0.98.

Against Heron-r2-median-class transmons it improves with width, 0.6 → 0.3 before SPAM. The reason is that both costs are exponential in circuit volume, so the crossover width is set by the per-gate exponents:

- a dual-rail erasure costs e^(λ) in shots (postselection, 1/P);
- a transmon Pauli error costs e^(2λ) (unbiased rescaling, 1/F²).

So dual rail overtakes a transmon at some finite width only if that transmon's error per unit circuit is worse than a threshold. Otherwise it never overtakes. **The honest, undeniable answer to B is that threshold, r*(n), as a function of width.** No single verdict serves. The crossover "logical-qubit count" B asks for exists against some transmons and not others, and we should say which.

## 1. Baseline

**Device.** One fixed-frequency transmon per logical qubit, no erasure check, no postselection (P_keep = 1; Evan, 2026-10-07). There is no bare-cavity arm.

**Gate set.** {CZ, SX, X, RZ (virtual)}, Heron's native set.
- Drop `swap` from the basis. In `run.py` l. 103 / `sim.BARE_TRANSMON_BASIS` l. 100 it is native today. It must be synthesized as 3 CZ + 1q gates, so that its error and duration come from the parts.
- Logical CR_z → 2 CZ + RZ, the transpiler's choice.

**Compiler.** Qiskit 2.4.1 `transpile(optimization_level=3)` (SabreLayout + SabreSwap, VF2), then the same `RescheduleCommutingDiagonals` the dual-rail arms get (`run.py` ll. 44–57, l. 38).
- **Effort parity.** PRISM keeps the best of 43 starts by −log F_cond. The transmon gets the best of K = 40 `seed_transpiler` values, selected by its own analytic error objective: ESP = Π(1 − r_g) · Π_q exp(−idle_q/T1)·exp(−idle_q/T_φ) over the scheduled circuit. Report best-of-1 against best-of-40 so the effect of effort is visible.
- Keep the existing min over {O3, our logical optimizer + O3} (`run.py` ll. 51–57).

**Ceiling arm, which removes routing and topology from the argument.** The same transmon compiled to all-to-all connectivity: zero SWAPs, the same idle model. No compiler on any connectivity beats this for a given gate synthesis. If dual rail with PRISM beats the transmon's all-to-all ceiling at some r, routing quality on the transmon side is irrelevant to the verdict at that r. (P1 objection (a) used a cruder version: gate errors only, from op counts.)

**Topologies.** grid and hex_lattice (the dual-rail topologies), plus heavy_hex for the transmon (IBM's native graph). Heavy-hex is a sensitivity row; the transmon gets whichever is better per workload.

**Qubit-count fairness.** B frames the dual-rail cost as "2× physical qubits". We charge it in the transmon's favour.
- **Chip.** The transmon gets the same chip size as dual rail: 2(n+1) nodes, from `make_topologies` with `SPARE_PAIRS = 1`, `paper_common.py` l. 17.
- **Parallel copies.** It may run k = ⌊2(n+1)/n⌋ = 2 copies of the circuit in parallel. Its wall-clock is divided by k.
- **Routing room.** Each copy also keeps the routing room of the whole chip. This is an upper bound that no real device meets: copies need disjoint qubits, and crosstalk is ignored. State it as such.
- **k = 1 row.** Report k = 1 as a row too: the same chip used only for routing room, which is the legacy setup.
- **Caveat to state in one sentence.** A cavity rail is not a transmon. Mehta's dual-rail qubit uses two cavities plus coupler and readout transmons. Counting rails as qubits therefore undercounts dual-rail hardware, and the comparison follows B's accounting.

**Widths.** n ∈ {4, 8, 12, 16}. The n = 4 manifests exist: 26 circuits in `artifacts/paper/manifests/circuits/*_n4.qpy`. n = 4 is needed because against Heron-median transmons the crossover may lie below 8. Without it we could only say "n* ≤ 8".

Beyond 16, an analytic extension to 20–32 is possible:
- dual rail from the closed form for P_keep (`MODEL.md` §3) and `scale.jsonl`'s `pair_idle_us` / `pair_touches` (`scripts/paper/export_device.py` ll. 139–140);
- the transmon from compile plus ESP, calibrated against simulation at 8–16.

Label it as a projection, or leave it out. It is not needed if r*(n) has converged by 16.

## 2. Parameters

### Transmon (convention: published r is the RB average gate error; simulator p_2q = 4r/3, p_1q = 2 r_1q)

IBM docs (`docs.quantum.ibm.com`, guides/qpu-information) define the 2Q error as "Average gate fidelity of the two-qubit operation from randomized benchmarking … includes the error of the layer of single-qubit Cliffords" and SX error as "Average gate fidelity of the √X (SX) gate from randomized benchmarking, measured simultaneously". Google's Willow spec sheet says errors are "measured with randomized benchmarking techniques and reported as 'average error'" (footnote 1).

| Point | CZ r, t_CZ | 1q r, t | T1 / T2 | Readout error / duration | Source |
|---|---|---|---|---|---|
| **Heron r2 median** (processor) | 2.848e-3, 68 ns | SX 2.88e-4, 32 ns* | 136.5 / 78.6 µs (T2 Hahn echo) | 1.63e-2 (median assignment) / 1560 ns | AbuGhanem, arXiv:2410.00916, Table IV (ibm_fez, 4 Jul 2024): "median CZ error of 2.848 × 10−3, and a median gate time of 68 ns"; "Readout assignment error … 0.016300"; "Readout length (ns) 1560" |
| **Willow mean** (processor, simultaneous) | 3.3e-3, 42 ns | 3.5e-4, 25 ns | 68 µs / T2,CPMG 89 µs | 7.7e-3 / not published | Willow spec sheet, 9 Dec 2024, QEC Chip 1: "0.33% ± 0.18% (CZ)", "0.035% ± 0.029%", "0.77% ± 0.21%"; arXiv:2408.13687: "mean operating T1 of 68 µs and T2,CPMG of 89 µs"; SI §I: "CZ gates are performed in 42 ns", "all XY rotations have 25 ns duration" |
| **Best transmon pair** | 1.0e-3 (99.90 ± 0.01% iRB), 48 ns | take r/10 | Q1 228.6 / T2E 358.9; Q2 205.3 / 129.8 µs | use Heron r3's 3.4e-3 | Li et al., PRX 14, 041050, arXiv:2402.18926v3: "CZ-gate length of 48 ns … CZ-gate fidelity of 99.90 ± 0.01%"; Table III |
| Heron r3 (context only, live values) | best 2Q 5.3–7.2e-4; layered (EPLG) 2.65–4.82e-3 | — | not on the table view | 3.4–5.7e-3 | IBM computers page, read 2026-10-08 (ibm_boston, ibm_pittsburgh, ibm_aachen). Live, not citable as published; snapshot `backend.properties()` if used |
| Fluxonium (context, not a transmon) | 99.922%, 50 ns | — | T1 450–1200 µs | — | Ding et al., PRX 13, 031035, arXiv:2304.06087 |

\*The SX duration of 32 ns is the legacy value in `sim.py` l. 97. The agent did not find it in Table IV, so it needs a check or a citation of IBM's gate-length property. Sung et al. (PRX 11, 021058) reports 99.76%, not ≥ 99.9%. Do not use it as a best case.

**Matching the dual-rail side, which is a two-qubit demonstration.** The dual-rail parameters come from Mehta et al.'s best pair. Comparing them only against a 156-qubit processor's medians would be unfair to the transmon, and a hostile reviewer would say so. The like-for-like comparison is best pair against best pair: Mehta against Li et al.'s DTC pair. The processor medians (Heron r2, Willow) are context. They answer "against what you can rent today".

**Transmon-favourable settings.**
- Dynamical decoupling is modelled as idles at the echo T2. As a variant, idles are T1-limited (T_φ → ∞).
- No leakage, crosstalk or ZZ.
- Reset and state-preparation error are zero.
- Readout error is applied as a symmetric X flip on each qubit before the overlap. This is equivalent for computational-basis readout.

### Dual rail (MEHTA, `sim.py` ll. 82–88, `MODEL.md` §2), plus SPAM and per-shot terms

The gate, erasure, lifetime and dephasing values are unchanged from `MODEL.md` §2. The following are added; P1 never applied them in its transmon comparison.

- **SPAM erasure.** f per qubit, applied as P_keep × (1 − f)^n.
  - Mehta et al., arXiv:2503.10935v2, Table III, "SPAM [1 round] Average erasure assignment 6.79 × 10−2 / 6.43 × 10−2". The text says: "overall SPAM erasure errors, defined to be assigned erasure outcomes when attempting to prepare in either |01⟩ or |10⟩, are measured to be 6.79% and 6.43%".
  - This is the **measured, pessimistic** value. The **optimistic** value is de Graaf et al., arXiv:2406.14621, Intro: "only 0.51±0.02% are false positives".
  - The two bracket the result. **This one parameter decides the n = 8 verdict against good transmons** (see §0), so it must be a sweep axis, not a fixed value.
- **Logical misassignment.** 2.0e-4 and 2.3e-4 (Table III, SPAM 1 round), applied as an X flip, the same as the transmon readout.
- **Detection efficiency η.** 0.996 (Table III leakage detection error 3.46e-3 and 3.90e-3), already handled after the fact in `detection.py` ll. 59–70.

**Per-shot time.** No dual-rail paper publishes a repetition rate (checked: Chou, Teoh, Koottandavida, de Graaf, Mehta). The components:

| Component | Value | Source |
|---|---|---|
| Logical measurement | "total duration of 4.8 µs for this sequence" | Chou et al., arXiv:2307.03169, p. 2 |
| Readout | t_M = 2.0 / 3.6 µs, processing 0.4 µs | Chou et al., Supp. Table I |
| Reset | Measurement-based: "we require a string of six successful outcomes … add a short delay of 10 µs before restarting" | Chou et al., Supp. Sec. IV.A |
| Preparation | "optimal control pulse … with a duration of 1 µs" | Chou et al., Supp. Sec. III.E |
| Erasure check | "a shorter square pulse with a duration Tp = 1.820 µs" | de Graaf et al., Fig. 3 section |
| Erasure check, alternative | "The entire circuit takes exactly 12µs to execute" | Koottandavida et al., arXiv:2311.04423 |

Our own estimate from these components is about 25–60 µs plus D. It must be labelled ours.

Transmon per-shot time:
- **Willow, which includes its circuits:** "Circuit repetitions per second 63,000", about 15.9 µs per shot (spec sheet, Chip 2).
- **Hardware floor:** "500 ns measurement and 160 ns reset" (arXiv:2207.06431, Fig. 1 caption).
- **IBM:** 3.8 kHz MCPS, about 263 µs per circuit. This is a live value. IBM defines MCPS as including "measurement, reset, and reinitialization".
- **Unverified.** IBM's default rep_delay of 250 µs could not be verified. Do not cite it.

These numbers span 16× on the transmon side alone. That is why §3 reports per-shot time as a break-even ratio, not as an input.

## 3. Metrics

Task: estimate ⟨O⟩ of the ideal output for a bounded observable (‖O‖ ≤ 1) to additive error ε, unbiased. All arms are compared at the same ε, so ε cancels.

**M0, kept-shot quality (assumption-free).**
- Kept-shot state fidelity F, from simulation with readout applied, for each arm.
- Also the bias guarantee 2√(1 − F) ≥ |⟨O⟩_noisy − ⟨O⟩| (Fuchs–van de Graaf; P1 ARGUMENT objection (b)), and the exact bias 1 − F of the certifying observable (the ideal-state projector).

M0 answers "what does a kept shot buy". It needs no variance model, but by itself it does not answer B.

**M1, raw shots to precision ε (the variance model).**
- N = C / (P ε²). Here P is the keep probability: P_keep · (1 − f)^n for dual rail and 1 for the transmon. C is the unbiased-mitigation cost of the kept-shot noise.
- **Headline C = 1/λ², with λ = (2ⁿF − 1)/(2ⁿ − 1), the global-depolarizing attenuation.** Use λ, not F. They differ at n = 4.
- Why this choice is defensible, and transmon-favourable:
  - Tsubouchi, Sagawa, Yoshioka, PRL 131, 210601 (2023), arXiv:2208.09385. Eq. 7 shows that for global depolarizing noise every unbiased estimator needs N ≳ (‖x‖²/ε²)(1−p)^(−2L), and the abstract says "the bound can be asymptotically saturated by merely rescaling the measurement results". So 1/λ² is the *optimal* unbiased cost for that noise.
  - Their Eq. 8 (local noise on 2-design circuits) gives an average-case lower bound exponential in nL. To first order it is the same e^(2·error) scaling. That reduction is our derivation and must be stated as ours.
  - Postselection costs 1/P, linearly, while unbiased post-processing costs the square. Cai et al., RMP 95, 045005 (2023), arXiv:2210.00921, Sec. II.D and the symmetry-verification discussion: "Tr[Πρ]⁻¹" against "Tr[Πρ]⁻²". This is the published, citable form of the erasure-conversion advantage, and the core of the subsection.
  - The **same** C is applied to dual rail's kept shots. Its residual Z noise is close to global for this purpose and small.
- **Bracket: C = γ², with γ computed for probabilistic error cancellation (PEC) from the noise model.** PEC is an implementable unbiased protocol. van den Berg et al., Nat. Phys. 19, 1116 (2023), arXiv:2201.09866: "sampling overhead γ = exp(Σ_k 2λ_k)", and the variance "scales with the square of the sampling overhead factor". For two-qubit depolarizing γ = f^(−15/8), so N grows about as F⁻⁴. This bracket favours dual rail, so it is reported as sensitivity only.
  - γ is analytic from the schedule (per-gate Pauli channels plus twirled T1/T2 idles). It needs no simulation and costs about 100 lines.
- **Unmitigated row (B's literal reading: equal kept shots, no correction).** Dual rail needs 1/P more raw shots, and in exchange its bias is bounded by 2√(1−F_d) instead of 2√(1−F_t). Report it in one sentence, because a reviewer will ask: under that accounting dual rail always costs more time, and buys accuracy.
- What not to say: that 1/F² is a lower bound for *all* mitigation. Biased or nonlinear methods are bounded only by the much weaker Takagi, Tajima, Gu, PRL 131, 210602 (2023) (Thm 3) and Takagi et al., npj QI 8, 114 (2022). Quek et al., Nat. Phys. 20, 1648 (2024) shows worst-case cost exponential in nD.

**M2, wall-clock (answers B directly).**
- T = N · t_shot / k, with t_shot = D + t_overhead and k parallel copies (transmon k = 2, dual rail k = 1).
- The ratio factors exactly:

  W = T_dr / T_tr = S · τ · k_tr, where S = N_dr / N_tr is the shot ratio and τ = t_shot,dr / t_shot,tr is the per-shot-time ratio.

- S comes from simulation and the sourced device parameters. τ is engineering. Report S with seed intervals, then:
  - **the break-even per-shot ratio τ* = 1/(k S)**: dual rail is faster in wall-clock iff its shot takes less than τ* times the transmon's;
  - **W at the sourced bracket of τ**, both arms at their component per-shot times, as a band.
- This is what removes the per-shot-overhead dependence that killed P1. The paper states τ*, and the reader places their own hardware.

**M3, the crossover.**
- **Width.** n*(arm, transmon point) is the smallest simulated width where the geometric-mean W < 1 and the 95% interval excludes 1. The point estimate interpolates ln W linearly between simulated widths. If W < 1 already at n = 4, report "≤ 4". If W never falls below 1, report "none up to 16" and the trend.
- **Break-even transmon.** r*(n, arm) is the transmon CZ error at which S·τ·k = 1, with 1q error r/10, T1/T2 at the best pair's values, and t_CZ = 68 ns via T1_eff = T1·68 ns/t_CZ (the approximation pre-registered at `1662bf6`). It is found by interpolating ln S in ln r between simulated r values.
- **Which metric answers B.** M2 at the sourced τ band answers "what is the total execution time", and M3's n* answers "at what logical-qubit count". **r*(n) is the robust form of M3 and should be the figure's headline.** For each width it says which transmons dual rail with PRISM beats. PRISM's contribution is r*_PRISM / r*_Greedy and n*_PRISM against n*_Greedy, with intervals: how far PRISM moves the break-even.

Aggregation is unchanged from `v2_report.py`: geometric mean over workloads of per-workload means over grid/hex and seeds, with a 1000-resample paired seed bootstrap. "Wins on m/16" is per workload. Each workload's cost is averaged as the mean of 1/(P λ²) over seeds and topologies, not 1/mean. Pre-register that choice.

## 4. Simulation method

**Exists and is usable.**
- `sim.simulate_bare` (`sim.py` ll. 437–479). It runs over active qubits only; there is an exact density matrix (`BareExact` ll. 367–386) and trajectories (`BareTrajectories` ll. 389–434).
- The `bare_transmon` arm in `run.py` (ll. 100–110) and `resim.py` (`_one`, which hard-codes `STRONG_TRANSMON`).
- Saved legacy bare circuits: 240 at n = 8 and 160 at n = 12 in `data/circuits_n{8,12}/*bare_transmon.qpy`. The active-qubit count is 7–12 at n = 8 and 10–15 at n = 12. The circuits were compiled on the rail graph with `swap` native, so recompile them; do not reuse them.
- Dual-rail rows at n = 8, 12 and 16 exist (`data/v2_n{8,12,16}.jsonl`) and need no new simulation, except n = 4. SPAM, η and τ apply analytically (`detection.py`).

**Must change.**
1. **Convention.** `sim.py` ll. 92–109: p_2q = 4r/3, p_1q = 2 r_1q. Express each device in published r and convert in one place.
2. **Swap.** Drop `swap` from `BARE_TRANSMON_BASIS` (l. 100) and the `swap` durations and errors (ll. 97–98).
3. **Readout flip.** Add a readout X flip at the end of `simulate_bare`, and the logical misassignment flip at the end of `simulate_dualrail`.
4. **Device points.** Replace `BARE_TRANSMON` and `STRONG_TRANSMON` with sourced devices: Heron r2 median, Willow mean, DTC pair, plus an r-grid at the pair's lifetimes. Gate durations come from each device.
5. **Compile.** `_bare_compile`: best-of-K by ESP, an all-to-all ceiling arm, heavy_hex. Bare arms run in a separate script from `run.py`'s dual-rail cell, because the dual-rail rows already exist.
6. **n = 4.** Add dual-rail rows at n = 4 (`run.py --device mehta --width 4 --transmon none`), exact.
7. **Analysis script.** S, λ, PEC γ, W, τ*, n*, r*, bootstrap. It replaces `costs.py`, which uses F in place of λ, has no SPAM and fixes the overhead at 2 µs (`costs.py` l. ~40).
8. **Validation.** The `validate.py`-style checks should cover the bare simulator too: trajectories against the exact density matrix at n = 8, and the readout flip against a direct calculation. This is a test of core logic, so it falls under the no-defensive-checks rule's exception for core logic.

**Method by width.**
- **Transmon, n = 4 and 8:** exact density matrix.
- **Transmon, n = 12:** trajectories, 256 per circuit.
- **Transmon, n = 16:** trajectories on up to about 20 active qubits. 32 × 2²⁰ complex amplitudes is 512 MB per batch, which fits in 15 GB. Batch at 32 and run 128 trajectories per circuit.
  - Per-row standard error at F about 0.1 is about 0.027. Pooled over about 64 rows per workload set it is a few percent in the geometric mean, and 1/λ² doubles the relative error. That precision is enough for the sign, because S at 16 is far from 1 for every transmon except the best pair.
  - Pre-register a timing probe on 3 circuits before committing. If the projected cost exceeds 40 CPU-h, n = 16 runs 2 seeds (0, 100), and r* at 16 comes from the separability model ln F = c + a·r + b/T1. That model was pre-registered at `1662bf6` and is fitted at n = 8 and 12 with held-out checks.
- **Seeds.** 0, 100, 200, 300, 400 for compile, the same as the dual-rail rows: at least 43 apart, and paired.
- **Trajectory seeds.** Shared across r points, so the r* curve is smooth.

## 5. Sensitivity and the pre-registered reading rule

**Headline cell (pre-registered).**
- Best transmon pair (Li et al.) against the best dual-rail pair (Mehta et al.).
- C = 1/λ², SPAM f = 6.6% (measured), k_tr = 2.
- The transmon gets best-of-40 compile and echo-T2 idles.
- τ is reported as τ*.

Every setting the reviewer could question is set at the transmon-favourable end, except f. f takes the measured value; its optimistic bound is a sensitivity row.

**One-at-a-time sensitivity rows (each reported as r*(n) and S at n = 8, 12, 16).**
- Transmon: r over {5e-4, 1e-3, 2e-3, 4e-3}; T1 at the pair's values, ×0.5 and ×2; T2 = echo, T1-limited (perfect DD), or Hahn median; readout 3.4e-3 (Heron r3) or 1.63e-2 (r2); topology grid, hex or heavy_hex; best-of-1 or best-of-40; all-to-all ceiling.
- Dual rail: f ∈ {0.5%, 6.6%, 2 rounds' 14–18%}; η ∈ {0.996, 0.963}; CR_z erasure ×0.5 and ×1 (the dual-rail lever that matters most); cavity T1 at the Chou/Koottandavida range.
- Accounting: C = 1/λ² or PEC γ²; k = 1 or 2.

Everything except the transmon r-grid and T1 rows is analytic on existing rows.

**Reading rule (fixed before any run).**

1. **Dual rail with PRISM beats the best transmon pair at some n ≤ 16** (W < 1 at τ*, interval excluding 1): report n*, and "dual rail with PRISM overtakes a best-in-class transmon at n* logical qubits; PRISM moves the crossover from n*_Greedy to n*_PRISM".
2. **It beats the processor medians (Heron r2, Willow) but not the best pair:**
   - report r*(n) and the published devices on either side;
   - report n* against each processor;
   - say plainly: "against today's best transmon pairs, postselected dual rail does not pay for its overhead at these widths; the case for dual rail there is outer codes (Kubica, Teoh, Chang)";
   - report PRISM's effect as r*_PRISM / r*_Greedy.

   This is the outcome §0's arithmetic predicts.
3. **It loses to every published transmon point:** report r* and S, and say: "postselected dual rail at Mehta et al.'s parameters is slower than current transmons for these workloads; PRISM reduces the gap by X". Point to the erasure parameter the cavity side must reach: the CR_z erasure at which r* crosses Heron r2's median.
4. **The verdict differs between f = 0.5% and 6.6%:** the paper names SPAM erasure as the deciding parameter and gives the f at break-even. No result is withheld, and no transmon point or overhead is changed after a result is seen.

The sentence for B is fixed as a template: "At n logical qubits, dual rail with PRISM estimates an observable to fixed precision in S× the transmon's shots; it is faster in wall-clock than any transmon with CZ error above r*(n), and than [device] whenever its shot takes less than τ*× the transmon's."

**Choices that could still decide the outcome, and how each is neutralized.**

| Choice | Neutralized by |
|---|---|
| Transmon quality | It is the output, r*(n) |
| Per-shot time | It is the output, τ*, plus a sourced band |
| Variance model | Tight for global depolarizing (Tsubouchi), the same on both arms, bracketed by PEC |
| Qubit count | k = 2 in the transmon's favour, k = 1 reported |
| Compiler effort | Best-of-40 and an all-to-all ceiling |
| Device-class mismatch | Best pair against best pair, with processor medians as context |
| SPAM erasure | Swept, because it decides the n = 8 verdict |
| Workload mix across widths | MQT generators change the circuit with n, so W(n) is per suite. Report the per-workload win counts and the per-workload r* spread |

## 6. Literature (each verified in the source; one sentence of evidence)

- **Kubica et al., PRX 13, 041022 (2023), arXiv:2208.05461.** Main text p. 2, with Fig. 1: "for erasure rate e = 0.01 the erasure protocol tolerates Pauli error rate p up to 0.0051 … 5.2× improvement over the standard protocol value." This is QEC, not postselection.
- **Teoh et al., PNAS 120, e2221736120 (2023), arXiv:2212.12077.** The earlier list gave 2208.05461 for this paper, but that is Kubica's ID. Erasures occur "with probability ∼ 1% per two-qubit gate", and Pauli errors from "second-order hardware errors … occurring with probability 0.01% per two-qubit gate" (Sec. III.A). Abstract: "orders of magnitude smaller".
- **Chou et al., Nat. Phys. 20, 1454 (2024), arXiv:2307.03169.** Abstract: "logical state preparation and measurement errors at the 0.01%-level and detect over 99% of cavity decay events as erasures … phase errors occur 6 times less frequently and bit flips occur at least 140 times less frequently". The 140× against 170× across versions is unverified; cite v3.
- **Levine et al., PRX 14, 011051 (2024), arXiv:2307.08737.** Dual-rail transmons: "erasure probability p_erasure = 2.19(2)×10⁻³ per gate while the residual errors are ∼40 times lower", "<0.1% dephasing error per check". This shows the erasure hierarchy is not cavity-specific.
- **Koottandavida et al., PRL 132, 180601 (2024), arXiv:2311.04423.** "erasure rate of 3.981 ± 0.003 (ms)⁻¹ and a residual dephasing error rate up to 0.17 (ms)⁻¹", a hierarchy of about 23×. The 12 µs erasure check is a per-shot overhead datum.
- **de Graaf et al., npj Quantum Inf. 11 (2025), arXiv:2406.14621.** Article number unverified. "only 0.51±0.02% are false positives … missed-erasure probability of only (9.0 ± 0.5)×10⁻⁴"; check pulse 1.820 µs. This is the optimistic SPAM bound.
- **Mehta et al., arXiv:2503.10935v2.** No journal version found. Abstract: CZ "∼500 ns … residual gate infidelity after error detection below 0.1% … erasure rates of ∼0.5% per gate". Table III: SPAM erasure assignment 6.79% and 6.43% per round. Fig. 2d text: "Because of the finite erasure probability (0.69%) per gate, the usable sequence depth is limited to only a few hundred gates." Cite that last sentence honestly: it is the source of the dual rail's own limit.
- **Griffiths, Friel, Vlastakis, arXiv:2606.31428 (2026).** Sec. 4.5 / Fig. 6, for QFT at n = 15 (1029 gates, p_e = 0.008, check error 0.005, s_a = 1000): "the single-rail model falls short … at F ≈ 0.023, but the postselected dual-rail model comfortably surpasses it at F ≈ 0.163".
  - **Caveats to state if cited.** The two arms share one T1 of 60 µs (a dual-rail transmon against its own single-rail version, not a cavity against Heron). They are compared at equal *accepted* shots. The "noise floor" 1/√s_a comes from a textbook shot-noise argument, not mitigation theory. The paper does not weigh wall-clock.
  - So it supports M0, kept-shot quality, and does not answer B. The current rebuttal M2 paragraph (`rebuttal.md` l. 28) leans on it more than it bears.
- **Cai et al., RMP 95, 045005 (2023), arXiv:2210.00921.** Postselection costs Tr[Πρ]⁻¹, and unbiased post-processing costs Tr[Πρ]⁻² (Sec. II.D, symmetry verification). PEC costs about e^(4λ) (Eq. 18). This is the citation for the mechanism.
- **Tsubouchi et al., PRL 131, 210601 (2023), arXiv:2208.09385.** Eq. 7: (1−p)^(−2L) is optimal for unbiased mitigation under global depolarizing noise, and rescaling saturates it. This justifies the headline C.
- **van den Berg et al., Nat. Phys. 19, 1116 (2023), arXiv:2201.09866.** γ = exp(2Σλ_k), with shots ∝ γ². This justifies the PEC bracket.
- **Bounds not to over-claim.** Takagi, Tajima, Gu, PRL 131, 210602 (2023), Theorem 3; Takagi et al., npj QI 8, 114 (2022); Quek et al., Nat. Phys. 20, 1648 (2024).
- **Other, optional.**
  - Wu et al., Nat. Commun. 13, 4657 (2022), arXiv:2201.03540: "98% of errors can be converted into erasures"; threshold 0.937% → 4.15%.
  - Scholl et al., Nature 622, 273 (2023): Bell fidelity ≥ 0.9971 after excising erasures, framed for NISQ use.
  - Sahay et al., PRX 13, 041013 (2023).
- **Transmon sources.** AbuGhanem arXiv:2410.00916 Table IV; Willow spec sheet and arXiv:2408.13687; Li et al., PRX 14, 041050; IBM qpu-information docs for the error convention; arXiv:2207.06431 Fig. 1 for readout plus reset of 660 ns.
- **No direct prior work.** No paper besides Griffiths compares dual-rail and bare qubits on NISQ circuits. That is the novelty claim for this subsection, and it should be worded carefully.

## 7. Cost

**Engineering.** About 1.5 agent-days:
- items 1–5 of §4: about 0.5 day;
- the analysis script with λ, PEC γ, τ*, n* and r* bootstrap: about 0.5 day;
- the figure and validation: about 0.5 day.

There are no `src/` edits; everything lives under `research/rebuttal/wallclock/`. Per the shared-worktree memory, ping the other sessions anyway, because the work shares the cores.

**Compute.** The legacy timings are in `1662bf6`'s pre-registration: about 1100 CPU-s per transmon point over 160 circuits at n = 8 exact, and about 1050 CPU-s per point at n = 12 with 64 trajectories.

| Job | Estimate |
|---|---|
| Transmon compile, best-of-40, 4 widths × 16 workloads × 3 topologies × 5 seeds, plus all-to-all | ≈ 4–8 CPU-h |
| n = 4: dual-rail and transmon, all points | < 0.5 CPU-h |
| n = 8: 3 device points + 4 r-grid points + 3 sensitivity rows, about 10 points × 0.3 | ≈ 3 CPU-h |
| n = 12: about 6 points × 1.2 CPU-h (256 trajectories) | ≈ 7 CPU-h |
| n = 16: 2–3 points | probe first; estimated 15–40 CPU-h |
| **Total** | **≈ 30–60 CPU-h** |

On the 2 free cores that is 1–1.5 days. On 10 cores after the current job, it is about 4–6 h.

Order the runs so that the n = 4, 8 and 12 results and the analytic rows come first, then n = 16 last.

**Paper footprint (0.5–0.75 page).**
- **Placement.** A new subsection after §5.4 (the Section 5 changes in `../rebuttal_minimal.patch`): "Net benefit over a bare transmon", about 0.4 page of text.
  - One paragraph each: baseline and fairness, then the metric with its one-line justification (Cai; Tsubouchi), then the result with the reading-rule sentence.
- **One single-column figure, two panels.**
  - (a) r*(n) against logical qubits for PRISM, Greedy and Logical-SABRE, with seed bands. Horizontal markers show Heron r2 median, Willow and the DTC pair. The shaded side is "dual rail faster", drawn at τ = 1 and labelled with τ*'s meaning.
  - (b) Kept-shot infidelity against time per kept shot at n = 16, one point per arm and device. This panel is assumption-free (M0).
- **What it replaces.** The P1 width figure (`data/legacy/figures/p1_width_paper.pdf`) and the earlier proposed bare-transmon panel.
- **Budget.** About 0.25 page for the figure and caption.

**Risk to flag to prism-66.** The expected outcome is reading-rule case 2. Evan wants "undeniable"; this design makes the result undeniable, not favourable. If Evan expects "dual rail wins", raise that before the runs, not after.
