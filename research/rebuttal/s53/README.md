# §5.3 ablations on the final settings: plan, pre-registered 2026-10-07 (prism-a7)

§5.3 l.66, l.68 and l.70 report the front-commit ablation, the tie-break ablation and the larger grids. Their rows (`raw/front_commit`, `tiebreak`, `slack`, `excluded`, 2026-10-06 14:33–14:46) predate the rail-X fix (9cb6c53, 18:16). They also cover only the grid and hex lattice, and only the 16 MQT workloads. §5.2 reports the final rows (47b2aa0): 25 workloads, three device graphs and 20 seeds. This plan re-runs only the ablation arms on those settings. The Greedy and PRISM rows of §5.2 are reused as they are, so a reader who compares Greedy across §5.2 and §5.3 sees the same rows.

The compiler is the one that produced 47b2aa0. The only later src change, d57bf82, adds two row fields (`pair_idle_us`, `pair_touches`) and does not change routing.

## 1. Runs

Each run uses the settings of `configs/paper/core.toml` and `configs/paper/breadth.toml`, except for the field named:

- objective `error`;
- rescheduling on;
- `qiskit_sabre`;
- 40 layout starts plus 3, 16 refinement iterations and 40 swap trials;
- seeds 0 to 1900 in steps of 100.

| run | arm | change from core | workloads | graphs | runs |
|---|---|---|---|---|---|
| front_commit | `prism_front_commit` | none | 25 (16 MQT at 8, nine QASMBench at native width) | grid, hex, heavy-hex | 1,500 |
| tiebreak | `prism` | `tie_break = "default"` | 25 | grid, hex, heavy-hex | 1,500 |
| slack | `greedy`, `prism` | topologies `grid_25`, `grid_36` | 16 MQT | the two larger grids | 1,280 |
| excluded | `greedy`, `prism` | the nine excluded MQT workloads | 9 | grid, hex, heavy-hex | 1,080 |

**One change in the front_commit run.** The 2026-10-06 front_commit run used `tie_break = "default"`, but PRISM uses `"load"`. The `prism_front_commit` arm passes the tie-break to the router (`prism_routing.py:436–452`). So "holding the choice open reduces the ablated count by a further Y" compared two arms that also differed in tie-break. This run uses `"load"`, so front_commit and PRISM differ only in when the realization is fixed.

**Device graphs.** front_commit, tiebreak and excluded run on all three graphs, as in §5.2. slack stays on the grid family, because its claim is about spare sites on a square grid at eight logical qubits. The nine QASMBench circuits need 22 to 50 rails and do not fit on 25 or 36 sites. The paper's 20-site grid uses the core rows.

**Configs.** There are six configs, in this directory:
- `front_commit_core.toml` and `front_commit_breadth.toml`;
- `tiebreak_core.toml` and `tiebreak_breadth.toml`;
- `slack.toml` and `excluded.toml`.

Each one is `core.toml` or `breadth.toml` with only the fields in the table changed. The rows go to `artifacts/paper/raw/s53_<run>.jsonl`. The 2026-10-06 files stay where they are, as the legacy rows in the evidence table of `../archive/rebuttal_letter_pre_minimal.md`.

## 2. Cost

The estimate takes the summed `compile_time_s` of the final rows, which ran at 8 to 12 workers.

| run | estimate (core-hours) | basis |
|---|---|---|
| front_commit | 3.5–4.5 | PRISM core 0.72 + breadth 2.92, times 1.0–1.25 (the 2026-10-06 front_commit/PRISM time ratio) |
| tiebreak | 3.6 | PRISM core and breadth |
| slack | 1.2 | the 2026-10-06 slack rows |
| excluded | 0.4 | the 2026-10-06 excluded rows times 1.5, for the third graph |
| total | 9–10 | |

At 8 workers this takes about 1.2–1.5 hours of wall time. gcm_h6 bounds it, at about 110 s per PRISM run and 120 runs per ablation arm. Every job runs under `timeout 7200`. I check with prism-09 before starting, and I use at most 8 workers with the machine total at or under 12 cores.

**Cheaper option.** Restricting front_commit and tiebreak to the 16 MQT workloads on three graphs costs about 3.3 core-hours, or about 30 minutes. §5.3 would then report on a different population from §5.2. I recommend the full suite.

## 3. Sentences to be restated, and the statistic for each

Every statistic follows §5.2 (suite/README.md §3):
- **Cell.** 1 − mean(arm)/mean(baseline) over 20 seeds.
- **Intervals.** 95% paired seed bootstrap (`paper_common.bootstrap_interval`, 2,000 resamples, rng 0), with seeds resampled jointly across workloads.
- **Per graph.** The equal-weight mean of per-workload reductions leads, and the summed reduction follows.
- **Run counts.** Over paired (workload, graph, seed) runs: 1,500 for the suite runs, 320 per grid for slack.

The numbers are reported whatever they show. No ablation is re-tuned after its result.

**l.66, sentence 3.** "Commitment under current layouts alone reduces Greedy's total routing SWAP count by 25.0% on the grid and 20.6% on the hexagonal lattice, and holding the choice open reduces the ablated count by a further 8.4% and 6.8%, with fewer SWAPs in 392 of the 640 paired runs and more in 66."

- front_commit against Greedy: equal-weight and summed SWAP reductions per graph, with intervals.
- PRISM against front_commit: the same, plus the runs with fewer and more SWAPs out of 1,500.
- As a consistency check, (1 − a)(1 − b) must reproduce §5.2's summed PRISM reduction on each graph. It is not reported.

**l.66, sentence 4.** "The ablation also regresses against Greedy on one workload mean and in 16 runs, and the retained sets remove the mean regression and 11 of the 16 while adding none."

- Cells where front_commit's mean exceeds Greedy's, with the number whose interval lies below zero.
- Runs where front_commit uses more SWAPs than Greedy. Of those, the runs where PRISM uses no more than Greedy (removed).
- Runs where PRISM uses more SWAPs than Greedy and front_commit does not (added).
- The same three counts for cells.

**l.68, sentences 2–3.** "Rerunning \sysname{} with Greedy's tie-breaking rule reproduces every per-run SWAP count and moves the depth reductions from 12.4% and 7.9% to 11.0% and 7.4%. For routing SWAPs, the two compilers therefore differ only in commitment timing."

- Per start: of the 1,500 × 43 start pairs in `search_trace.final_scores`, the number with equal active gate counts. The lowering fixes the CR_z and RSWAP counts, so equal active gate counts mean equal SWAP counts.
- Per run: the runs whose kept start differs, and the runs whose final SWAP count differs.
- Depth and duration reductions against Greedy under `load` and `default`, equal-weight per graph with intervals.
- Reading rule, fixed now. If every start pair has equal SWAP counts, sentence 3 stays, restated per start as a claim about layout starts, not selected runs. If any start pair differs, sentence 3 is cut and the count replaces it.

**l.70, sentence 2.** "Greedy instead inserts nearly the same number of routing SWAPs on square grids of 20, 25, and 36 sites, and \sysname{}'s reduction holds at 30.6% and 28.8% on the larger grids, with fewer routing SWAPs on 13 workloads and ties on three at each size."

- Greedy's summed SWAPs on 20, 25 and 36 sites, with the change from 20.
- PRISM's equal-weight and summed reductions on 25 and 36 sites, with intervals.
- Per size, the number of cells lower, tied and higher, and the number with intervals above zero.
- The 20-site values come from the core rows, so the three sizes use one build.

**§5.1, the exclusion sentence (block 08 l.14).** "We exclude nine MQT Bench workloads that pose no routing problem at this width."

- The maximum routing SWAPs per arm and graph over the 1,080 runs.
- The sentence stands if both arms are at most 1 in every run, as on the 2026-10-06 rows (PRISM 0, Greedy at most 1). Otherwise the sentence gives the counts.

## 4. Output

- An exporter, `research/rebuttal/s53/export.py`, writes `artifacts/paper/paper_export/s53/summary.json` and `per_cell.csv`.
- The manuscript treatment is in `../rebuttal_minimal.patch`, Section 5; no separate block patch is maintained.
- A `response_log.md` entry covers W1/Q1, W2/Q2 and review-2 W3/Q2.
- Use these rows when updating the response letter's evidence table.

## 5. Option (b): include the nine excluded workloads, a 34-workload suite (pre-registered 2026-10-08, before any equal-weight number is computed)

The §5.1 exclusion rule does not hold (`../response_log.md`, the 2026-10-08 §5.3 entry). prism-66 asked for a costed alternative that includes the nine MQT workloads, for Evan's decision 6. Nothing in blocks 08 or 09 changes unless Evan picks it.

**Rows.**
- Greedy and PRISM: `raw/s53_excluded.jsonl`, which already exists (core settings, 20 seeds, three graphs).
- Logical-SABRE: new rows, `excluded_logical.toml`, which is `configs/paper/logical.toml` with the nine circuits, written to `raw/s53_excluded_logical.jsonl`. The §5.2 Logical-SABRE sentence then covers the same 34 workloads.
- MQT `bv` at eight logical qubits and QASMBench `bv` at 19 share a circuit name. The variant export renames the MQT one `bv_n8`.

**How a cell whose Greedy mean is 0 enters.** These rules are fixed now.
- **Cell tallies.** The cell counts as lower, tied or higher on means, like every other cell. A cell where both means are 0 is tied.
- **Ratios.** The ratio 1 − mean(PRISM)/mean(Greedy) is undefined for such a cell. It is left out of the equal-weight mean and of the min, median and max of cell reductions for that reason only, and the number left out is stated per graph and metric. Within a bootstrap resample, a cell whose resampled Greedy sum is 0 is left out of that resample, as `export_suite.equal_weight_interval` already does.
- **Intervals.** Such a cell has no interval, so it is not counted as having an interval above 0.
- **Summed reductions.** These include every cell.
- **Reporting.** Every equal-weight reduction is reported with its interval as computed, including any interval that contains 0. No cell is dropped for having few SWAPs.

**Export.** `export_suite34.py` runs `scripts/paper/export_suite.py` unchanged over the 34-workload rows and writes `artifacts/paper/paper_export/suite34/`. The 25-workload outputs stay in place. The error objective (−log F_cond from `metrics.device_success`, equal weight, cells lower) is computed the same way for 25 and 34 workloads.

**Table for prism-66.** For 25 against 34 workloads, per graph:
- equal-weight and summed SWAP, depth and duration reductions, with intervals;
- the error objective;
- cell counts (lower, tied, higher, interval above 0);
- Logical-SABRE equal-weight ranges.
