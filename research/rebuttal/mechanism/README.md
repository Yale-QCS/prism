# Why delayed commitment helps some workloads more than others

Question from prism-66, 2026-10-07: PRISM's routing-SWAP reduction against Greedy spans 3–8× across workloads (Fig. 9). Can circuit structure predict it? An answer would bear on reviewer A (driven by a few cases? myopia), C (generality) and D (when another router or encoding would benefit).

## Pre-registration (2026-10-07, before any feature is computed or compared with any outcome)

### Outcome

- **Y (primary):** for each cell (workload × device graph), Y = 1 − Σ_seeds PRISM routing SWAPs / Σ_seeds Greedy routing SWAPs.
  - Rows: `artifacts/paper/raw/core.jsonl`, n = 8, 20 seeds, error selection with rescheduling. There are 16 workloads × 3 graphs = 48 cells.
  - These rows predate `9cb6c53`. That fix changes only the physical stage, and routing SWAP counts come from the lowering stage. The quick rerun had identical SWAP edges.
- **Y32 (secondary):** the same reduction at n = 32 from the paper's old scale rows (`41fabb1:artifacts/paper/raw/scale.jsonl`). That is grid and hex, 5 seeds, swaps objective, 32 cells. Selection differs, so Y32 is a robustness check only.

### Roles (amendment 1, 2026-10-07, before any run)

- **Predictors** are computable from the logical circuit before routing: A and A′. Only a predictor says when delayed commitment will help another circuit or encoding (reviewers C and D), so the deep claim needs one.
- **Mediators** are measured on routes and show how the gain arises: B, C and D.
  - D is close to definitional. Greedy's excess distance when a gate becomes pending is roughly the SWAPs it pays extra, so a high ρ(D, Y) is expected and is not an insight on its own.
  - D measures how stale Greedy's binding is, which is the "commit under the current layout" effect in the front-commit ablation (24.4% / 20.7% of Greedy's SWAPs).
  - B measures choice at commit. With D, it bears on the "hold the choice open" effect, the further 8.8% / 7.7%, which no feature here isolates.
  - C measures the share of Greedy's SWAPs spent on rejoins. Realization choice cannot remove rejoin SWAPs, so C bounds the reachable gain from above.
- **Seed stability:** for B, C and D, each cell's spread over the 3 seeds (standard deviation, and minimum to maximum) is reported next to the value.

### Features

Each feature is fixed below and computed once.

- **A (H-a): CR_z gates per separated-rail interval.**
  - Run each workload through the dual-rail logical stage (`DualRail.logical_pm()`), which gives a circuit over {crz, rx, rz, x, swap, measure}.
  - For each logical qubit, split its gate sequence at every rx and every x on it. Both force its two rails to meet: rx becomes an rswap on the pair, and x a swap of the pair.
  - A = (number of CR_z incidences) / (number of intervals that contain at least one CR_z), pooled over qubits. One value per workload.
- **A′ (H-a′, amendment 2): distinct CR_z partners per separated-rail interval.** Use the intervals defined for A. A′ = (sum over intervals of the number of distinct partner qubits among the interval's CR_z gates) / (number of intervals that contain at least one CR_z). One value per workload. The reasoning: four realizations help when a qubit's two rails can face different partners.
- **B (H-b): availability actually reached.**
  - On PRISM's routed lowering-stage circuits (seeds 0, 100, 200; physical stage removed), track every rail's physical position from the initial layout through each SWAP.
  - At each CR_z's execution, count how many of its four realizations (rail pairs (u_i, v_j)) are adjacent.
  - B = fraction of CR_z executions with at least 2 adjacent realizations. B_G is the same quantity on Greedy's routes, reported but not tested.
- **D (H-d): routing guidance, the realization-distance gap on Greedy's route.**
  - On Greedy's routed lowering-stage circuits (same seeds), track rail positions as for B.
  - A CR_z on logical qubits u, v becomes pending right after the last earlier op on any of u's or v's rails. At that position, compute the coupling-graph distance of each of its four realizations (rail pairs (u_i, v_j)).
  - gap = distance of the realization Greedy bound − minimum distance over the four. D = mean gap over all CR_z in the cell.
  - D_P is the same gap measured on PRISM's routes, against the realization PRISM finally committed. It is reported but not tested.
- **C (H-c): Greedy's R_X-rejoin SWAP share.**
  - On Greedy's routed lowering-stage circuits (same seeds), attribute each routing SWAP to the first later two-qubit op on either of its physical qubits.
  - CR_z means "reach". An rswap, or a swap lowered from a logical x, means "rejoin". A joint_herald means "herald".
  - C = rejoin SWAPs / all attributed SWAPs.

### Tests and what falsifies each hypothesis

- **Statistic:** Spearman ρ between each feature and Y over the 48 cells.
  - The 95% interval comes from 2000 bootstrap resamples of the 16 workloads, keeping each workload's three cells together, because cells of one workload are not independent.
  - Per-graph ρ (16 cells each) is reported for every hypothesis.
- **H-a predicts ρ(A, Y) > 0.** Falsified if the 95% interval includes 0 or ρ ≤ 0. Supported only if ρ ≥ 0.5 and the interval excludes 0.
- **H-a′ predicts ρ(A′, Y) > 0.** Falsified and supported under the same rules as H-a.
- **H-b predicts ρ(B, Y) > 0.** Falsified and supported under the same rules. B is measured on PRISM's own routes, so a positive ρ is consistent with H-b but does not show cause.
- **H-d predicts (i) ρ(D, Y) > 0, and (ii) that commits rarely have a choice.**
  - (i) is falsified and supported under the same rules as H-a.
  - (ii) is pooled B ≤ 0.2 (at least 80% of PRISM's CR_z commits have exactly one adjacent realization) with |ρ(B, Y)| < 0.3. It is falsified if pooled B > 0.2 or ρ(B, Y) ≥ 0.3 with its interval excluding 0.
  - H-b and H-d(ii) make opposite predictions about B, so at most one of them can be supported.
  - This re-measures the 2026-09-10 diagnostic (91%, 1285 of 1416 commits with one adjacent realization; `main:research/notes/qec_codes.md`) on current code, which uses program-order dependencies, not commutation-aware ones.
- **H-c predicts ρ(C, Y) < 0.** Falsified if the interval includes 0 or ρ ≥ 0. Supported only if ρ ≤ −0.5 and the interval excludes 0.
- **Size control:** for each feature, report the partial Spearman correlation controlling for log(Σ Greedy SWAPs). A hypothesis that loses its sign under this control is reported as "confounded by size".
- **Low counts:** cells with Σ Greedy SWAPs < 40 (2 per run) give noisy Y. The main test keeps them. A sensitivity run without them is reported.
- **Multiple tests:** five hypotheses are tested. A result that does not also survive a Bonferroni-corrected interval (99%) is called weak.
- **Outliers:** cells with a standardized residual above 2 in the rank regression of Y on the best-supported feature. Each is explained from its circuit, or listed as unexplained.
- **Y32:** each feature's ρ with Y32 is reported with the same intervals and is not used to decide support.

### Phase 2: causal test with constructed circuits (conditional, pre-registered now)

This runs only if A or A′ is supported in phase 1. If neither is, it does not run.

- **Circuits:** random circuits of 60 CR_z gates on 8 logical qubits, with random angles. Each qubit gets an R_X after every k of its CR_z incidences, k ∈ {1, 2, 4, 8, ∞}. For A′, the CR_z partners within each interval are drawn from a pool of p qubits, p ∈ {1, 2, 4, 7}, with k = 8.
- **Runs:** Greedy and PRISM on the square grid, core settings, 5 seeds per setting, and 5 random circuits per setting.
- **Prediction for A:** Y rises with k. It is supported if Y(k = ∞) − Y(k = 1) ≥ 10 points, with a 95% bootstrap interval (over circuits and seeds) excluding 0, and Spearman ρ(k, Y) > 0 over the settings. Otherwise it is falsified.
- **Prediction for A′:** the same rule, with p in place of k: Y(p = 7) − Y(p = 1) ≥ 10 points.

### What this cannot show

All three are correlations over 16 workloads. A supported hypothesis is a predictive regularity, not a causal proof. Phase 2 is the causal test, and it runs only under its condition.

## Measurement notes

- Features B, C and D treat every SWAP between the two rails of one logical qubit as semantic (a logical X). The router can also insert such a SWAP. The paper's routing count, duration and error model all include it. Rows minus replay show these are rare: 3 of 432 router SWAPs for Greedy and 0 of 395 for PRISM in the first 29 cell-seeds. The rule is left as is.

## Results (2026-10-07, all 48 cells; `analyze.py` → `data/report.json`, `figures/features.png`)

**Claim: no pre-registered feature predicts which workloads gain most. All five hypotheses are falsified. The one prediction that holds is H-d(ii): commits rarely have a choice.**

| feature | role | ρ with Y | 95% interval | verdict | partial ρ given size | ρ without low-count cells | ρ with Y32 |
|---|---|---|---|---|---|---|---|
| A, CR_z per separated-rail interval | predictor | +0.08 | [−0.35, +0.47] | falsified | −0.02 | +0.17 | +0.15 |
| A′, distinct partners per interval | predictor | −0.14 | [−0.51, +0.29] | falsified | −0.22 | −0.03 | +0.03 |
| B, PRISM commits with ≥ 2 adjacent realizations | mediator | +0.08 | [−0.30, +0.48] | falsified | +0.10 | +0.01 | +0.32 |
| D, Greedy's bound-vs-nearest gap when pending | mediator | +0.17 | [−0.20, +0.51] | falsified | +0.06 | +0.29 | +0.36 |
| C, Greedy's rejoin SWAP share | mediator | −0.24 | [−0.52, +0.00] | falsified | −0.27 | −0.25 | −0.42 |

Per-graph ρ has no consistent sign for any feature. For example, A′ is −0.44 on grid and −0.10 on heavy-hex, and C is +0.30 on grid and −0.52 on heavy-hex.

**H-d(ii) holds.**
- Pooled over all PRISM CR_z commits, B = 11.2%: 88.8% of commits have exactly one adjacent realization. The 2026-09-10 diagnostic found 91%, under commutation-aware dependencies.
- The choice rate does not track the gain (ρ = 0.08).
- So PRISM's advantage does not come from choosing well among executable realizations at commit. It comes from how routing proceeds while the set is held open. H-d(i), the D test, could not show which part of routing, because D is ~0. See the next point.

**D is almost always zero on Greedy's route.** D = 0 in 63% of cell-seeds, and its mean is 0.03. When a gate becomes pending, Greedy's bound realization is almost always already the nearest. This is endogenous, as prism-66 noted: Greedy's lookahead has been steering the layout toward its bound realizations, so the measurement cannot separate "Greedy's binding is not stale" from "Greedy's routing made it come true". The front-commit ablation, not this feature, is the clean measure of the commit-timing effect.

**Part of the spread is noise.**
- Across cells, Y has standard deviation 0.143. Seed noise, from a seed bootstrap of each cell's Y, accounts for 26% of that variance.
- The extremes are low-count cells. cdkm on grid shows 81.2%, with interval [10, 100], at 1.6 Greedy SWAPs per run. dj on grid shows 0.0% at 2.0.
- The robust high-gain cells are the multipliers: rg_qft_multiplier 42.3% on hex [39.5, 45.1] and 46.2% on grid [42.6, 49.5], and multiplier 49.4% on grid [45.5, 53.3], each with 57–86 Greedy SWAPs per run.
- The robust low-gain cells are dj, vbe_ripple_carry_adder and modular_adder on hex, all below 9% with intervals that include 0.
- Outliers (|z| > 2 on C): cdkm on grid (small count) and dj on grid (an exact tie at 2 SWAPs per run).

**Seed stability.** Median per-cell seed SD is 0.027 for B, 0.048 for C and 0.035 for D. The features are stable enough that their nulls are not a noise artifact.

**Phase 2 does not run.** Its condition was a supported predictor, and none was supported.

### Exploratory, not pre-registered (hypotheses for a future test only)

- B_G, the share of Greedy's CR_z executions with ≥ 2 adjacent realizations, has ρ = +0.40 with Y. It was reported but not tested.
- At n = 32 (Y32), the mediators correlate more strongly: C −0.42, D +0.36, B +0.32. One reading is that the effect becomes structural only at larger widths, where routes are longer. A pre-registered test at n ≥ 16 would be needed.

### What this does not explain

Why the multipliers gain about 45% and the adders under 10%. All five candidate structural features fail on these 16 workloads. An honest answer for now: the per-workload gain is not predicted by any simple structural statistic we tested, and part of the apparent spread is small-count noise.

### Draft rebuttal paragraph (reviewer A, "driven by a few cases?")

The gain is not driven by a few cases or by commit-time choice. In a pre-registered analysis of all 48 workload–graph cells, 89% of PRISM's CR_z commits had exactly one executable realization, and the rate of choice did not track the reduction (ρ = 0.08). So the benefit comes from holding the set open during routing, not from picking among executable options. No structural statistic we pre-registered predicted the per-workload reduction (|ρ| ≤ 0.24, all intervals include 0). A quarter of the apparent spread is seed noise in cells with few SWAPs. The reductions are largest and tightest on the multipliers (42–49%) and smallest on dj and the adders.
