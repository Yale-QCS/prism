# Steane memory with a faithful erasure-flag model (W2)

Run 2026-11-12, uncommitted. The 2026-11-16 skip-gate re-run of rows (b) and (c) is in [its own section](#skip-gate-leakage-model-pavlovich-et-al-2026-11-16). Hexagonal lattice only, X and Z memories, the 20 paired routing seeds of Table II (0–1900), Greedy against PRISM. Decisions: the top entries of `../../response_log.md`. Audits: `../../audit/steane.md`, `../../audit/steane-check.md`.

## Results

P_L is pooled over 20 routes. The interval is the 95% percentile interval of the relative reduction from `scipy.stats.bootstrap` (paired over routing seeds, 20,000 resamples, generator seed 745), given as [low, high].

**X memory, hexagonal lattice**

| Protocol | Greedy P_L (%) | PRISM P_L (%) | Relative reduction (%) [95%] | Seeds PRISM lower/equal/higher | SWAPs G → P | Duration (µs) G → P | Route score G → P | Shots per route |
|---|---|---|---|---|---|---|---|---|
| published Table II | 0.0971 | 0.0749 | 22.9 [14.6, 31.3] | 17/1/2 | 70.15 → 47.75 | 13.37 → 10.69 | 0.7251 → 0.6336 | 50,000 |
| (a) ideal per-site flags | 0.0930 | 0.0691 | 25.7 [18.5, 32.3] | 18/0/2 | 70.15 → 47.75 | 13.37 → 10.69 | 0.7248 → 0.6333 | 200,000 |
| (b) flags at readout only | 0.3051 | 0.2289 | 25.0 [18.6, 31.4] | 20/0/0 | 70.15 → 47.75 | 13.37 → 10.69 | 0.7248 → 0.6333 | 200,000 |
| (c) compiled checks, rounds 1-2 | 0.5803 | 0.4512 | 22.3 [16.6, 27.1] | 17/0/3 | 84.55 → 48.90 | 20.78 → 17.27 | 1.0116 → 0.8664 | 200,000 |
| (c') compiled checks, all 3 rounds | 0.7959 | 0.5917 | 25.7 [20.8, 29.9] | 19/0/1 | 83.40 → 52.20 | 26.10 → 20.50 | 1.1181 → 0.9493 | 200,000 |

**Z memory, hexagonal lattice**

| Protocol | Greedy P_L (%) | PRISM P_L (%) | Relative reduction (%) [95%] | Seeds PRISM lower/equal/higher | SWAPs G → P | Duration (µs) G → P | Route score G → P | Shots per route |
|---|---|---|---|---|---|---|---|---|
| published Table II | 0.0965 | 0.0649 | 32.7 [24.6, 40.7] | 19/1/0 | 78.50 → 48.90 | 13.59 → 10.52 | 0.7336 → 0.6280 | 50,000 |
| (a) ideal per-site flags | 0.0929 | 0.0693 | 25.4 [17.1, 32.8] | 18/0/2 | 78.50 → 48.90 | 13.59 → 10.52 | 0.7333 → 0.6277 | 200,000 |
| (b) flags at readout only | 0.3024 | 0.2152 | 28.8 [23.8, 33.9] | 20/0/0 | 78.50 → 48.90 | 13.59 → 10.52 | 0.7333 → 0.6277 | 200,000 |
| (c) compiled checks, rounds 1-2 | 0.5680 | 0.4475 | 21.2 [13.8, 27.4] | 17/0/3 | 81.30 → 52.55 | 20.87 → 17.42 | 1.0080 → 0.8883 | 200,000 |
| (c') compiled checks, all 3 rounds | 0.6159 | 0.5008 | 18.7 [12.5, 24.5] | 18/0/2 | 74.85 → 48.30 | 23.59 → 20.24 | 1.0627 → 0.9429 | 200,000 |

Published SWAPs and durations (§VI-B): 70.15 → 47.75 and 78.50 → 48.90 SWAPs; 13.37 → 10.69 µs and 13.59 → 10.52 µs. Rows (a) and (b) use the published routes, so these are unchanged. Row (c) is re-routed with the checks in the circuit; its duration includes 2.94 µs per check.

What the rows show:

- **PRISM stays below Greedy in every row**, on 17 to 20 of 20 seeds. The reduction is 19–29%, against the published 22.9% and 32.7%. Every interval excludes zero.
- **Row (c), the Table II headline:** P_L 0.58% → 0.45% (X) and 0.57% → 0.45% (Z), reductions 22.3% [16.6, 27.1] and 21.2% [13.8, 27.4].
- **Delayed flags raise P_L 3.1–3.3×** over ideal flags (row b against row a).
- **Compiled checks with de Graaf's parameters are worse than no checks** over three rounds (row c against row b), by 1.9–2.1×. Each check costs 2.94 µs, 0.8% loss, 0.51% false flags and 0.12% depolarizing error.
- **The checks cost PRISM no routing.** PRISM's SWAPs go from 47.75 and 48.90 to 48.90 and 52.55; Greedy's go from 70.15 and 78.50 to 84.55 and 81.30. PRISM keeps 42% and 35% fewer SWAPs.
- Row (a) is close to the published row in absolute P_L (0.093% and 0.069% in both bases). The Z reduction is 25.4% where the published one is 32.7%; the intervals overlap.

The transmon rows are kept as published: 2.1724% and 2.0526% (0.1% CZ error), 5.6250% and 5.2801% (0.3%). The noise change is a dual-rail control-loss effect and does not apply to them. They still have instantaneous readout and reset, while row (c) charges dual rail 2.94 µs per check.

## Skip-gate leakage model (Pavlovich et al.), 2026-11-16

Run 2026-11-16, uncommitted. The model and decoder follow Pavlovich et al. (arXiv:2607.29443, §II.1–II.2, §IV). The author chose row (b), flags at readout only, as the Table II headline; row (c) is the compiled-check comparison. Rows are in `rows_skipgate/`, and the code is `skipgate.py`, `sanity_skipgate.py`, and the `items` hook in `flag_memory.build`. The routes, loss sites, rates and seeds are unchanged.

### Results

**X memory, hexagonal lattice**

| Protocol | Greedy P_L (%) | PRISM P_L (%) | Relative reduction (%) [95%] | Seeds PRISM lower/equal/higher | SWAPs G → P | Duration (µs) G → P | Shots per route |
|---|---|---|---|---|---|---|---|
| (a) flag at every loss, erasure model (`table4`; equal under skip-gate) | 0.0930 | 0.0691 | 25.7 [18.5, 32.3] | 18/0/2 | 70.15 → 47.75 | 13.37 → 10.69 | 200,000 |
| (b) flags at readout only, erasure model (`table4`) | 0.3051 | 0.2289 | 25.0 [18.6, 31.4] | 20/0/0 | 70.15 → 47.75 | 13.37 → 10.69 | 200,000 |
| (b) flags at readout only, skip-gate, earlier decoder | 0.9292 | 0.7061 | 24.0 [18.2, 29.3] | 19/0/1 | 70.15 → 47.75 | 13.37 → 10.69 | 100,000 |
| (b) flags at readout only, **skip-gate** | 0.7645 | 0.6648 | 13.0 [2.1, 22.5] | 14/0/6 | 70.15 → 47.75 | 13.37 → 10.69 | 100,000 |
| (c) compiled checks, rounds 1-2, erasure model (`table4`) | 0.5803 | 0.4512 | 22.3 [16.6, 27.1] | 17/0/3 | 84.55 → 48.90 | 20.78 → 17.27 | 200,000 |
| (c) compiled checks, rounds 1-2, skip-gate, earlier decoder | 1.2022 | 0.8599 | 28.5 [23.1, 33.0] | 19/0/1 | 84.55 → 48.90 | 20.78 → 17.27 | 100,000 |
| (c) compiled checks, rounds 1-2, **skip-gate** | 1.2070 | 0.8728 | 27.7 [21.6, 32.8] | 19/0/1 | 84.55 → 48.90 | 20.78 → 17.27 | 100,000 |

**Z memory, hexagonal lattice**

| Protocol | Greedy P_L (%) | PRISM P_L (%) | Relative reduction (%) [95%] | Seeds PRISM lower/equal/higher | SWAPs G → P | Duration (µs) G → P | Shots per route |
|---|---|---|---|---|---|---|---|
| (a) flag at every loss, erasure model (`table4`; equal under skip-gate) | 0.0929 | 0.0693 | 25.4 [17.1, 32.8] | 18/0/2 | 78.50 → 48.90 | 13.59 → 10.52 | 200,000 |
| (b) flags at readout only, erasure model (`table4`) | 0.3024 | 0.2152 | 28.8 [23.8, 33.9] | 20/0/0 | 78.50 → 48.90 | 13.59 → 10.52 | 200,000 |
| (b) flags at readout only, skip-gate, earlier decoder | 0.7925 | 0.5862 | 26.0 [20.4, 31.5] | 19/0/1 | 78.50 → 48.90 | 13.59 → 10.52 | 100,000 |
| (b) flags at readout only, **skip-gate** | 0.7165 | 0.5760 | 19.6 [12.3, 26.3] | 18/0/2 | 78.50 → 48.90 | 13.59 → 10.52 | 100,000 |
| (c) compiled checks, rounds 1-2, erasure model (`table4`) | 0.5680 | 0.4475 | 21.2 [13.8, 27.4] | 17/0/3 | 81.30 → 52.55 | 20.87 → 17.42 | 200,000 |
| (c) compiled checks, rounds 1-2, skip-gate, earlier decoder | 1.4417 | 1.1461 | 20.5 [13.6, 26.9] | 16/0/4 | 81.30 → 52.55 | 20.87 → 17.42 | 100,000 |
| (c) compiled checks, rounds 1-2, **skip-gate** | 1.2607 | 0.9756 | 22.6 [13.8, 30.5] | 17/0/3 | 81.30 → 52.55 | 20.87 → 17.42 | 100,000 |

The interval and seed counts are as in Results above (paired seed bootstrap, `scipy.stats.bootstrap`, 20,000 resamples, generator seed 745). "Skip-gate, earlier decoder" is the run in `rows_skipgate/superseded_sampled_env/`. It decoded with a basis drawn from 64 sampled patterns per location, and a false flag left the pair untouched. Both are fixed below.

- 100,000 shots per route; 2,000,000 per arm and basis. Stim seeds as in `table4`.
- Row (c') (21 checks) was dropped at the author's request.
- Row (a) is not re-run. With a flag at every loss, the pair is detected and reset at the loss site itself, before the next event; a `before:crz` loss is reset at its TICK, before the gate. Nothing is ever skipped. The leak's envelope at an immediate detection is the site's X and Z columns, so this is exactly the published `HERALDED_ERASE` model and decoder. Row (a) in `rows_table4/` is therefore already the skip-gate row (a).
- Superseded runs in `rows_skipgate/`:
  - `superseded_200k/`: 18 cells at 200,000 shots, before the shot count was cut.
  - `superseded_hand_gf2/`: decoder columns from hand-written elimination.
  - `superseded_sampled_env/`: columns from `ldpc.mod2.pivot_rows` on sampled patterns.
  - These two used the same spans, but which vectors became columns moved P_L by up to 8%. An independent review found that 26–49 of about 110 errors per cell flipped with the envelope seed (`scratch/skipgate-review/p8.py`). The current decoder has no basis choice.

What the rows show:

- **Row (b), the headline: PRISM's reduction is 13.0% [2.1, 22.5] (X) and 19.6% [12.3, 26.3] (Z).** PRISM is lower on 14 and 18 of 20 seeds. Both intervals exclude zero; X only barely.
  - Under the erasure model it was 25.0% and 28.8%, and under the earlier skip-gate decoder 24.0% and 26.0%.
- **Row (c), compiled checks: 27.7% [21.6, 32.8] (X) and 22.6% [13.8, 30.5] (Z),** on 19 and 17 seeds; it was 28.5% and 20.5% with the earlier decoder.
- **Row (b)'s reduction depends on the decoder.** Readout routes have no checks, so no false flags, and the decoder is the only change from the earlier skip-gate run. It is better on every arm, but more so for Greedy:
  - X: Greedy P_L falls from 0.929% to 0.765% (−18%), PRISM's from 0.706% to 0.665% (−6%);
  - Z: Greedy's falls from 0.793% to 0.717% (−10%), PRISM's from 0.586% to 0.576% (−2%).
  - Greedy's routes hold more loss sites, so more of their shots have two or more losses, where decoding matters (below). A better decoder may narrow row (b) further; the interval is decoder-conditional.
- **Absolute P_L rises 2.1–2.9× over the erasure model:**
  - row (b): Greedy 0.305% → 0.765% (X) and 0.302% → 0.717% (Z); PRISM 0.229% → 0.665% and 0.215% → 0.576%;
  - row (c): Greedy 0.580% → 1.207% and 0.568% → 1.261%.
- **Why P_L rises.** An empty pair drops out of every later stabilizer measurement until it is found. Measured on readout, Greedy X seed 0, losses only, 20,000 shots, final decoder (`scratch/skipgate/diag7.out`):
  - shots with one loss: 0 failures in 7,236;
  - shots with two losses: 2.47% of 2,515 fail; shots with three: 11.6% of 586.
  - With exact loss locations, 46 of 3,694 two-loss location pairs (sampled by rate) have a syndrome-free logical in the union of their two envelopes, a 0.62% floor. All 46 involve an ancilla; 0 of 913 data–data pairs do, as distance 3 requires (`scratch/skipgate/diag8.out`). None of the 506 single locations has one.
  - The decoder knows only the flagged interval, not the location, which accounts for the rest.
  - The earlier "3.5% floor" in this section used nested column sets that over-count the envelope; it is withdrawn.
- **Compiled checks are still worse than none:** for Greedy, by 1.58× (X) and 1.76× (Z) (1.9–2.1× under the erasure model). This agrees with Pavlovich et al.'s recommendation of end-of-line three-state readout over mid-circuit checks.
- **Unexplained shots: 0** of 16,000,000 (8,000,000 per row).

### Model

- **Skipping.** From its loss until its detection, a pair is empty. Every event that touches it is skipped as one unit (`build` items): a CR_z with either operand empty, an R_SWAP, and the pair's own Z residual and check depolarizing. The intact partner of a skipped CR_z is untouched, including the S corrections that the lowering puts on it. A routing SWAP is not a Stim operation: the empty pair is relabelled with its rails as before, and only that pair's SWAP noise is skipped.
- **Detection and reset.** A joint check finds an empty pair with probability 1 − 0.037, and a missed loss stays empty until the next check or readout. Every flag resets its pair completely mixed (a uniform random Pauli). That includes a false flag on an intact pair (probability 0.0051 per check), because the hardware cannot tell a false flag from a true one, and Pavlovich et al. return a qubit reported as leaked to the completely mixed state. A readout always finds an empty pair and resets it just before the pair's first rail measurement; the flag goes to that readout's group. Ancilla pairs are re-prepared by their scheduled reset.
- **Loss sites.** These are the same as `table4`, including half of each control erasure placed before the CR_z.
- **Target dephasing.** The `table4` target-dephasing term needs no separate channel; the skip produces it.
  - In `table4`, a control erased before the gate carried X or Y with probability 1/2, and the CR_z turned that into Z on the target.
  - Now a control lost before the gate switches the gate off, so the target misses its control-dependent phase. The control's value is lost, so relative to the reference circuit the target is dephased.
  - For one CZ with a maximally mixed control, skip and erase-then-apply give the same target channel, Z with probability 1/2. They differ for every later gate of the lost pair: erase-then-apply spreads the pair's Pauli to all later partners, and skip leaves them alone.
  - `table4` never had an added rate (`full` did). No term is added here.

### Simulation

`skipgate.sample` runs one Stim `TableauSimulator` per shot that has any loss, Z, depolarizing event or false flag. Between events it runs slices of the routed Stim circuit. While a pair is empty, it applies the `build` events one by one and skips those that touch the empty pair. Detection events come from Stim's `compile_m2d_converter`. A shot with none of these events has no detection event. Sampling each loss set's `removed` circuit with `compile_sampler` instead (the review's optional suggestion) was not timed.

Library check (`steane-check.md` §6, plus probes in `scratch/skipgate/` and `scratch/skipgate-review/`):
- **Stim 1.16** has no leakage state. Its frame simulators apply Pauli errors to a fixed circuit, and skipping a gate is not a Pauli error.
- **deltakit-stim 0.2.7** randomizes a leaked qubit's CZ partner (`p7.py`).
- **leakysim 0.5.0** (`TableauSimulator`-based) skips a two-qubit instruction with a leaked operand (`leaky_skip_probe.py`). It runs on Stim 1.16 with identical results despite its `stim==1.15` pin (`leaky_semantics_probe_stim116.out`), so §6's "not compatible with 1.16" is a pip pin, not a fault.
  - It skips per instruction, not per event.
  - When the CR_z control is leaked, the lowering's S gates still put Z on the intact target, but a status-conditioned `LeakyPauliChannel` after the event undoes that (`p6.py`).
  - When the target is leaked, the lowering's S on the intact control still runs. That is a non-Pauli error that no leakysim Pauli channel can undo: 1012/2000 control X-basis flips where the skipped event gives 0 (`p6.py`).
  - So the per-event loop is hand-written around Stim's `TableauSimulator`. leakysim, with that channel, serves as the outside reference for the control-leaked case (Validation).

### Decoder

- **Base.** `SkipDecoder` extends `IntervalDecoder`: the same ldpc BP+OSD (serial product-sum, 7 iterations, OSD-CS order 2), the same unflagged Z and check-depolarizing priors, and the same flag groups.
- **Envelope columns** (`skipgate.envelopes`). A flagged group no longer opens the X and Z columns of its sites. It opens the Pauli envelope of each place the pair could have leaked:
  - For each site of the group's chain (its own sites, and those of earlier groups whose checks it follows), `removed` deletes the pair's events from that site to the group's detection point and depolarizes the pair there.
  - Stim's `detector_error_model(allow_gauge_detectors=True)` of that circuit is taken under the routed circuit's detectors, with the observable added as one more detector. It lists the location's fault and gauge mechanisms. The routed circuit's converter applied to the circuit's `reference_sample()` gives its offset.
  - Every distinct vector is one decoder column, recorded with the locations whose envelope contains it. Nothing is sampled and no basis is chosen.
  - The span of each location's mechanisms equals the span of its sampled outcomes at all 1,261 locations of two circuits (`scratch/skipgate-review/p5.py`), and the skip cross-check below confirms coverage.
- **Prior.** A pair leaks at most once before its flag.
  - Location ℓ of the window gets the disjoint share e_ℓ ∏_{ℓ' before ℓ in the window} (1 − e_ℓ') f_n^{a_ℓ}. The window, a_ℓ, and the total with its f_p/(1 − f_n) term are as in Appendix C, Eq. (21), whose shares are the first-order form of this.
  - A mechanism gets (1/2) × (sum of the shares of the locations whose envelope contains it) / total.
  - At a check, the check site's own mechanisms (the reset) also carry the false-positive weight f_p/(1 − f_n), so every flag, true or false, opens the reset at prior 1/2.
- **Basis choice on identical samples** (50,000 shots, three cells, `scratch/skipgate/diag6.out`; errors listed for readout Greedy X 0, readout PRISM Z 300, checks Greedy X 0):

  | Columns | Errors |
  |---|---|
  | every DEM mechanism (current) | 473, 258, 413 |
  | pivot basis of the DEM vectors | 788, 285, 469 |
  | pivot basis of 64 sampled patterns, seed 0 | 648, 221, 480 |
  | pivot basis of 64 sampled patterns, seed 1 | 639, 222, 445 |

- **Decoder choice.** Pavlovich et al. decode with MWPM and branch-and-bound. MWPM needs a matching graph. A single data fault in the Steane memory flips up to three detectors of one type (each data qubit sits in up to three checks), so its detector graph is a hypergraph and BP+OSD stays.
- **Unexplained shots.** A shot whose syndrome needs a column with prior 0, or that OSD cannot match, is scored as a logical error.

- **Old decoder on the new samples** (50,000 skip-gate shots, the same samples for both decoders, `scratch/skipgate/diag7.out`). The Eq. (21) columns (each site's X and Z) also explain every shot: 0 unexplained. They decode 2–3× worse, though:
  - readout, Greedy X seed 0: P_L 2.24% with `IntervalDecoder` against 0.90% with `SkipDecoder`;
  - checks, Greedy X seed 0: 1.70% against 0.84%;
  - checks, PRISM Z seed 100: 3.34% against 1.12%.

### Validation (`skipgate_sanity.log`)

- **Build unchanged.** On readout and checks, Greedy X seed 0, `build` with the `items` hook gives a Stim circuit identical (as text) to the previous `build`.
- **Noise off.** On all 240 routes (readout, checks, checks3 × 2 bases × 2 arms × 20 seeds), `sample` gives no detection event, observable flip or flag. One certain Z at site 0, run through the tableau loop, gives exactly Stim's Z column.
- **Pauli-only equivalence.** On 6 circuits:
  - each of 20 fixed Z patterns gives, on every shot, exactly the XOR of Stim's fault columns (`detecting_regions`);
  - with Z residuals and check depolarizing at 20× their rates, the 44 detector and observable rates match Stim's `compile_detector_sampler` on the same channels at 40,000 shots (all within 5σ).
- **Skip cross-check.** On 4 circuits, 125 certain-loss locations:
  - the tableau loop matches Stim's sampler on the explicit circuit with the pair's events removed and the pair reset completely mixed at detection: same affine span of outcomes (which for these circuits fixes the law), per-bit rates within 0.08 over 2,000 shots, and for the 122 supports of at most 64 patterns, the same pattern set at frequencies within 5σ;
  - every tableau pattern lies in the span of that location's own DEM mechanisms;
  - 70 of the 125 differ in support from erase-and-keep-the-gates, the previous model.
- **Two losses.** On the same 4 circuits, 8 pairs each: two certain losses on pairs that share a later CR_z match Stim on the circuit with both pairs' events removed (same affine span, 2,000 shots).
- **Outside reference** (`outside`). Hand-written toy cells that use neither `build`, `removed` nor the routed circuits, 4,000 shots each:
  - **Control lost** before both of two lowered CR_z, or between them: the tableau loop and leakysim (with the status-conditioned channel and a completely mixed return channel) give the same patterns at equal rates. The partner flips at 0.000 and 0.497, against 0 and 1/2 by hand.
  - **Target lost:** the intact control's Y readout flips at 0.513 (1/2 by hand). leakysim, which keeps the lowering's S, flips it at 1.000 (1 by hand).
  - **False flag:** a false flag on one half of a Bell pair destroys the parity, at 0.497 (1/2 by hand); with no flag nothing fires.
  - **Missed loss:** a loss that the check misses is flagged only at the readout.
- **Flag timing.** On 6 circuits (3,102 sites), a certain loss raises exactly one flag: in its own group with f_n = 0 (the pair's next check or readout), and at the pair's next readout with f_n = 1.
- **Unexplained shots.** None in the 160 rows (16,000,000 shots).

Commands, from this directory:

```sh
python=/home/evm9/prism/dev/steane-venv/bin/python
for t in pauli skip two outside timing off; do $python sanity_skipgate.py $t; done > skipgate_sanity.log
./run.sh skipgate 100000 readout checks
$python report.py table4 skipgate
```

`outside` runs leakysim 0.5.0 from `/home/evm9/prism/scratch/skipgate/venv-l16` (Stim 1.16, `leakysim` installed with `--no-deps`).

Runtime: a mean of 110 s per readout cell and 104 s per checks cell at 100,000 shots, of which 5–17 s is building the envelopes. The 160 cells took 49 minutes (2,940 s) with six workers, part of the time sharing the CPU with the validation suite and diagnostics. Envelope columns per route: 207–264 (readout), 320–439 (checks).

## Noise model: `table4`

The decision named "the CR_z control-loss target error from Mehta (about 0.094% per gate)". In Mehta et al. (arXiv:2503.10935, Results, leakage propagation, Fig. 4 and Table 4) that number is 2.55(5)% divided by N = 27 gates: an upper bound on the target's XX and YY error per CZ, measured only in shots where the control was found in |00⟩. The author confirmed this reading and chose the `table4` model:

- A control lost before the gate switches the gate off; a control that starts in |01⟩ and is lost during the gate leaves Z(θ), θ ∈ [0, π], on the target (their Table 4). Their Fig. 4b models a loss during the gate as a loss before it or after it.
- `table4` adds no rate. Half of each control erasure (4.0e-3 / 2) is placed before the CR_z and half after it. The target is then dephased only in shots where the control is lost (1.0e-3 per gate), and the error comes with the control's flag.
- The conditional 0.094% bound itself is omitted (about 4e-6 per gate).

## Protocols

| Row | Routes | Flags the decoder gets |
|---|---|---|
| (a) ideal | published | one per noise site, at the loss |
| (b) readout | published | one per pair per readout: ancillas every round, data pairs once at the end |
| (c) checks | re-routed with 14 checks | as (b), plus one per data pair per joint check |
| (c') checks3 | re-routed with 21 checks | as (c), with a check in round 3 too |

- **Row (c) has 14 compiled checks, not 21.** Each data pair is checked after its last two-qubit gate of rounds 1 and 2; its two-rail final readout is the round-3 check. Row (c') compiles the third check as well.
- **Sampling is Stim's.** Every loss site is a `HERALDED_ERASE` (`erasure_pilot.with_heralds`, as published), and every joint check has a false-positive herald that leaves the qubit alone, `HERALDED_PAULI_CHANNEL_1(0.0051, 0, 0, 0)`. A false flag therefore costs the decoder information, not the qubit: no flag triggers a re-preparation in this model. (`steane-check.md` §6 says this instruction depolarizes at once; that is wrong for arguments (p, 0, 0, 0), which herald without a Pauli: `scratch/r3-review2/p1_fp_channel.py`.) In rows (b) and (c) the decoder does not see those heralds. About ten lines of numpy (`sample_flags`) OR them over each (pair, interval) group, drop a check's flag with probability 3.7%, and carry a dropped flag to the pair's next check or readout. Stim has no delayed-herald or false-negative channel (`steane-check.md` §6). Readouts are ideal, as published.
- **What this model idealizes.** Between its loss and its flag the pair is a depolarized qubit that still takes part in gates, not an empty pair. The empty pair's effect on its CR_z partners is a Z kick, and every such pattern lies in the span of the fault columns the decoder opens for the flagged interval. A pair can be lost again before its flag. The earlier hand-written sampler kept the pair empty and re-prepared it at the flag; the reviewer's probe found the two agree within sampling noise. *(2026-11-16: that sampler was a `FlipSimulator` Pauli-frame sampler (see Superseded below; its code is not in git). A frame simulator cannot remove a gate, so it still applied the lost pair's gates and propagated its Pauli: the same erasure picture, which is why it agreed. Under skip-gate leakage the span claim above does not hold: a skipped CR_z removes the pair from later checks. See the skip-gate section, where P_L is 2.1–2.9× higher.)*
- **Decoder.** `ldpc.BpOsdDecoder` with the published settings (serial product-sum BP, 7 iterations, OSD-CS order 2). For a flagged interval each site gets prior e_s / total / 2 on its X and Z columns. The total also holds the check's false-positive rate divided by (1 − 0.037), which opens no column: a false flag is no fault. Sites of earlier intervals of the same pair are included with weight 0.037 per check passed, back to the last check that raised a flag. Check sites carry an unflagged X prior for the depolarizing error. No shot was left without an explanation inside the model.
- **Readout groups.** Every readout closes a group, including one with no noise site before it. The two rails of a pair can be read at different times in the published schedule; sites up to the later rail belong to that one readout.
- **Route objective** for (c): the published formula (negative log probability of no erasure or Z event) over the device with the check's duration, loss and dephasing. The routes were selected with the superseded `full` term in the score; that term is a constant per CR_z.

## Parameters and sources

| Parameter | Value | Source |
|---|---|---|
| Gates, idling, T1, dephasing | unchanged `wallclock/sim.MEHTA_IDLE` | Mehta et al., as published |
| Control loss before the gate | half of 4.0e-3 | Mehta et al., Table 4 and Fig. 4b |
| Check duration | 2.94 µs | de Graaf et al. (arXiv:2406.14621): 1.820 µs pulse + 0.12 µs beamsplitter ramp + 1 µs readout. They state no total; their text mentions a 1 µs readout, and the sum is my assumption |
| Loss during a check | 0.82% | this device's T1 (356.5 µs) over 2.94 µs. De Graaf measure 2.41% on their device, equal to their idle loss for the same time; the check that is running flags it |
| Check false positives | 0.51% | de Graaf et al. |
| Check false negatives | 3.7% | de Graaf et al. |
| Check Pauli error | 0.12% depolarizing + 0.067% Z | de Graaf et al.: at most 0.12% transmon-induced, "closer to a depolarizing channel"; the Z part is this device's idle dephasing over 2.94 µs (they measure 0.20% idling on theirs) |

All check parameters are taken from a different device (a Yale cavity pair with a transmon ancilla), not from the Mehta device. Their flagged-erasure total of 2.92% is not used directly: its loss part is replaced by this device's loss over the same duration.

## Statistics and seeds

- 200,000 shots per route (published: 50,000); 4,000,000 per arm and basis.
- The bootstrap resamples routing seeds, both arms together. Shot noise is inside each per-seed rate.
- Stim seeds: both arms of one routing seed and basis share one seed, the first 8 bytes of SHA-256 of `r3_{basis}_{seed}`, in every protocol. The two arms' circuits differ, so this fixes the generator state, not the individual faults. Rows under `rows_published/` keep the published per-arm seed so that they reproduce.

## Sanity checks

- **Noise off:** 320 cells (4 protocols × 80), 10,000 shots each: zero logical errors and zero flags (`sanity.py off`).
- **Reproduction:** row (a) with the published noise reproduces all 80 published hexagonal-lattice rows exactly: error counts, flagged-shot counts, route score and duration. Totals per 1,000,000 shots are 971, 749, 965 and 649, the four dual-rail cells of Table II (`sanity.py published`).
- **Flag timing:** on 12 circuits (3 delayed protocols × 2 bases × 2 arms, seed 0; 5,928 sites) a certain loss at one site raises exactly one flag, in the group of that pair's first joint check or readout after the site, found by an independent scan of the circuit. With every check missing (fn = 1) the one flag is raised at the pair's next readout instead (1,626 sites that lie before a check) (`sanity.py timing`).
- **Check channels:** on 4 circuits (checks and checks3, both bases, Greedy, seed 0), fp = 1 with no loss flags exactly the 14 or 21 check groups and flips no detector or observable. One certain loss with fn = 0.5 gives flag rates 1/2, 1/4, 1/4 (two checks, then the readout) or 1/2, 1/4, 1/8, 1/8 (three checks) on every data pair, and exactly one flag per shot (`sanity.py channels`). Both logs are in `timing.log`.
- **Lowering unchanged for published circuits:** two published cells recompiled with the edited sources give the saved score and SWAP count.

## What changed

- `research/rebuttal/outer_qec/route.py`, `to_stim.py`: paths resolve from the file's location.
- `src/marabbecca/synthesis/preparation.py`: `ErasureCheckGate` (logical) and `JointCheckGate` (two rails, timed).
- `src/marabbecca/encodings/dualrail.py`: both names in the ISAs and the rule `erasure_check → joint_check` on the pair's rails.
- `src/marabbecca/staged_pms.py`: `erasure_check` in `NON_GATE_ISA_NAMES`.
- `src/marabbecca/utils/metrics.py`: `joint_check` duration, 2940 ns.
- Here: `flag_memory.py` (one cell), `run.sh` (sweep), `sanity.py`, `report.py`, `requirements.txt`.
- No hand-written simulator remains in the `table4` rows. (The skip-gate rows use a hand-written per-event loop on Stim's `TableauSimulator`; see that section for the library check.) `sample_flags` (`flag_memory.py` lines 172–206) is the numpy flag bookkeeping around Stim's sampler.

## Commands

From this directory, with `/home/evm9/prism/dev/steane-venv` (`requirements.txt`; Qiskit 2.4.1 comes from the repository `.venv`). `run.sh` puts its six workers in one `systemd-run` scope capped at 8 GB and skips finished rows.

```sh
python=/home/evm9/prism/dev/steane-venv/bin/python
($python sanity.py timing; $python sanity.py channels) > timing.log
./run.sh published 50000 ideal
./run.sh off 10000 ideal readout checks checks3
./run.sh table4 200000 ideal readout checks checks3
$python sanity.py published; $python sanity.py off
$python report.py table4 > report.md
```

Rows are `rows_{noise}/{protocol}_{basis}_{arm}_{seed}.json`; compiled routes are `routes_checks/` and `routes_checks3/` (QPY).

## Runtime

A cell takes about 5 s (a), 7 s (b), 12 s (c) and 13 s (c') at 200,000 shots, of which 3 s is compiling in (c). The 320 `table4` rows took 0.8 CPU-hours; the noise-off and `table4` sweeps together ran in 11.5 minutes with six workers.

## Superseded: `full` noise and the first sampler

`superseded/herald_erase_fp/` holds the (c) and (c') rows from the second pass, in which the false-positive herald was a `HERALDED_ERASE` that also depolarized the qubit (an extra 0.38% Pauli error per check). Row (c) was then 0.6202 → 0.4824% (X) and 0.6106 → 0.4810% (Z).

`superseded/` holds the first pass: `rows_full/`, its report and logs. It used a hand-written `FlipSimulator` sampler (since replaced by the Stim heralds above) and the `full` noise model, an independent, unflagged Z of 9.4e-4 on every CR_z target. That model misreads Mehta's 0.094% as unconditional; it is a worst case only. It nearly doubles the unflagged error budget and triples P_L under ideal flags. The current `flag_memory.py` still accepts `--noise full`, but these rows are from the old sampler and decoder weights.


**X memory, hexagonal lattice** (superseded)

| Protocol | Greedy P_L (%) | PRISM P_L (%) | Relative reduction (%) [95%] | Seeds PRISM lower/equal/higher | SWAPs G → P | Duration (µs) G → P | Route score G → P | Shots per route |
|---|---|---|---|---|---|---|---|---|
| (a) ideal per-site flags, noise `full` | 0.3134 | 0.2617 | 16.5 [11.4, 21.5] | 18/0/2 | 70.15 → 47.75 | 13.37 → 10.69 | 0.7928 → 0.7013 | 200,000 |
| (b) flags at readout only, noise `full` | 0.7336 | 0.5830 | 20.5 [16.3, 24.7] | 20/0/0 | 70.15 → 47.75 | 13.37 → 10.69 | 0.7928 → 0.7013 | 200,000 |
| (c) compiled checks, rounds 1-2, noise `full` | 0.8006 | 0.6438 | 19.6 [14.7, 23.8] | 18/0/2 | 84.55 → 48.90 | 20.78 → 17.27 | 1.0796 → 0.9344 | 200,000 |
| (c') compiled checks, all 3 rounds, noise `full` | 1.0416 | 0.8169 | 21.6 [17.6, 25.0] | 19/0/1 | 83.40 → 52.20 | 26.10 → 20.50 | 1.1861 → 1.0173 | 200,000 |

**Z memory, hexagonal lattice** (superseded)

| Protocol | Greedy P_L (%) | PRISM P_L (%) | Relative reduction (%) [95%] | Seeds PRISM lower/equal/higher | SWAPs G → P | Duration (µs) G → P | Route score G → P | Shots per route |
|---|---|---|---|---|---|---|---|---|
| (a) ideal per-site flags, noise `full` | 0.3020 | 0.2443 | 19.1 [13.7, 24.2] | 19/0/1 | 78.50 → 48.90 | 13.59 → 10.52 | 0.8013 → 0.6957 | 200,000 |
| (b) flags at readout only, noise `full` | 0.5656 | 0.4430 | 21.7 [17.8, 25.3] | 19/0/1 | 78.50 → 48.90 | 13.59 → 10.52 | 0.8013 → 0.6957 | 200,000 |
| (c) compiled checks, rounds 1-2, noise `full` | 1.0673 | 0.8947 | 16.2 [9.9, 21.6] | 18/0/2 | 81.30 → 52.55 | 20.87 → 17.42 | 1.0760 → 0.9563 | 200,000 |
| (c') compiled checks, all 3 rounds, noise `full` | 1.1966 | 1.0048 | 16.0 [11.3, 20.5] | 19/0/1 | 74.85 → 48.30 | 23.59 → 20.24 | 1.1307 → 1.0109 | 200,000 |
