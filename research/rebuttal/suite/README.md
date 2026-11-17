# One 25-workload suite (G5, R2, A-2, B-3): plan, pre-registered 2026-10-07

**Current rows:** the submitted revision uses the SWAP-selected re-run in [swaps/](swaps/README.md) (64 seeds). This plan and [seeds80/](seeds80/README.md) describe the earlier J-selected runs, kept as history.

The plan below was written for 23 workloads. §1 adds two circuits, and every count of 23, 69 or 1,380 means 25, 75 or 1,500.

Evan: "if the reviewer wanted more workloads, i think we need to add them to the paper and not just the rebuttal." The seven QASMBench circuits join the 16 MQT Bench workloads as one suite in §5.2. They stop being a separate breadth result. Everything below is fixed before any suite statistic is computed. Writing it, I looked only at Greedy's summed SWAPs and depth (for the weighting question in §4), never at a PRISM-versus-Greedy suite number.

## 1. Workloads

| source | workloads | width | rows |
|---|---|---|---|
| MQT Bench 2.2.2 | the 16 of `configs/paper/core.toml` | 8 | `artifacts/paper/raw/core.jsonl`, `logical.jsonl` |
| QASMBench (Li et al., ACM TQC 2023), commit 357b942 | sat 11, seca 11, multiply 13, gcm_h6 13, qec9xz 17, qram 20, knn 25 | native | `artifacts/paper/raw/breadth.jsonl` (+ new Logical-SABRE rows) |

The two configs already agree on the objective (error), rescheduling, heuristic, tie-break, 40 layout starts, 16 refinement iterations, 40 swap trials, the seeds 0..1900 step 100, and the three topologies. Only the circuits and widths differ, so the suite merges rows at export time. One config would add nothing.

### Selection rule (applied mechanically 2026-10-07, before any compile of the circuits it adds)

The 2026-10-06 rule was written from notes, and some of its exclusions were judgments by analogy (qf21 as "phase estimation", bv as a suite family, cc "like bv"). prism-66 ruled that every clause is applied mechanically, and a circuit that no clause excludes joins. The candidates are QASMBench's medium-scale set at commit 357b942 (25 circuits, 11–27 qubits). The clauses, each checked by script:

1. **Family in the 16-workload MQT suite**, by name or by the file's own header: qft_n18 (qft), hhl_n14 (hhl), multiplier_n15 (multiplier), bigadder_n18 (header: Cuccaro ripple-carry adder = cdkm_ripple_carry_adder). bv, qf21 and cc are **not** in the 16, so this clause doesn't exclude them. (MQT's bv was one of the nine zero-pressure exclusions at n = 8, which is a different rule.)
2. **Needs no routing.**
   - The interaction graph (two-qubit pairs after unrolling to CX) is a path, so it embeds with every pair adjacent: cat_state_n22, ghz_state_n23, ising_n26, wstate_n27.
   - dnn_n16 is a 16-cycle, which the structural test can't settle. Greedy alone (seed 0, breadth settings) inserts 0 routing SWAPs on all three graphs, so it is excluded. No PRISM run was made.
3. **Contains an operation the compiler cannot lower**: reset (`DualRail.reset` raises `NotImplementedError`): bwt_n21, square_root_n18; and classically conditioned gates whose lowering has several realizations (`encodings/base.py` `if_else` raises `ValueError`): cc_n12, found when every arm failed on it. Mid-circuit measurement by itself is supported, so it is not a clause: seca_n11 measures mid-circuit and compiles.
4. **More than 10^4 two-qubit gates:** factor247_n15 (273k), vqe_n24 (1.5M), bwt_n21.
5. **Duplicate within QASMBench:** swap_test_n25 has the same 12 multi-qubit gates on the same qubits as knn_n25. Only single-qubit angles differ, so the routing problem is identical.
6. **One instance per family** (added by prism-66 before any bv compile): when a family has several medium-scale instances, keep the widest. This drops bv_n14 and keeps bv_n19, the same choice as one width per MQT workload. No other family in the medium set has two instances.

What remains, with the reasons it needs routing (some logical qubit has more distinct partners than a rail pair can have adjacent sites: at most 6 on the grid, 4 on hex, 3 on heavy-hex):

| circuit | qubits | CX | max partners | status |
|---|---|---|---|---|
| sat_n11, seca_n11, multiply_n13, gcm_h6 (gcm_n13), qec9xz_n17, qram_n20, knn_n25 | 11–25 | 32–762 | 6–24 | in the 2026-10-06 seven |
| cc_n12 | 12 | 12 | 11 | **excluded by clause 3 at compile time**: every arm raised `ValueError` on every run (180 of 180), because its classically conditioned H and X lower to several realizations, and `encodings/base.py` `if_else` refuses that. The static check (measure/reset scan) did not catch this. No PRISM result for cc ever existed. The rows are in `artifacts/paper/raw/suite_unsupported.jsonl`. |
| bv_n14 | 14 | 13 | 13 | dropped by clause 6 |
| **bv_n19** | 19 | 18 | 18 | joins (the widest bv) |
| **qf21_n15** | 15 | 115 | 11 | joins |

The suite is **16 + 9 = 25 workloads, 75 cells, 1,500 paired runs**. Every count in §3 and §6 of this plan that says 23, 69 or 1,380 means 25, 75 and 1,500. Logical-SABRE can place both new circuits on heavy-hex (maximum matching 24 ≥ 19). Scripts: the structural table is from `qiskit.transpile(..., basis_gates=["cx","u"])` and `rustworkx`; the dnn check is a single-arm `run_fairness._run_one`.

### randomcircuit (keep 260746b consistent)

260746b states the exclusion criterion (a sampled random circuit, not an algorithm) and then what including it would do to the suite reductions. The suite sentence keeps both. The "including it would raise…" numbers must be recomputed over 23 workloads. **Gap:** `randomcircuit.jsonl` has grid and hex rows only, so this sentence can't cover heavy-hex unless the randomcircuit run gets heavy-hex. That run is 40 tiny n = 8 runs, about one minute. I won't run it without your go.

## 2. New compute: Logical-SABRE on the seven

- Config: `research/rebuttal/suite/logical_qasmbench.toml`, which is `logical.toml` with the seven circuits and `[circuit_widths]`. Rows are in `artifacts/paper/raw/logical_qasmbench.jsonl`.
- Size: 7 × 3 × 20 = 420 runs. **knn on heavy-hex cannot run.** A 57-site heavy-hex lattice has a maximum matching of 24 rail pairs, so Logical-SABRE can't hold 25 logical qubits (`make_topologies` plus `rustworkx.max_weight_matching`). Greedy and PRISM need 52 sites and fit. That leaves 400 feasible runs. The 20 infeasible ones go in the rows as failures with the reason, and the exporter reports the cell as "not placeable", not as missing.
- Wall time, estimated from the rows: Logical-SABRE's summed compile time on core is 0.56× Greedy's (1,944 s against 3,457 s). Greedy's breadth runs total 10,830 CPU-s, and gcm_h6 alone is 7,570 s at about 126 s per run. At 0.56× and 12 workers that gives **about 10–15 minutes wall**, bounded by the 60 gcm_h6 runs. The core ratio is uncertain at 11–25 qubits (per-run ratios range from 0.07 to 9.5), so first a one-seed probe (21 runs, a few minutes) checks for failures and the time per circuit. The full job starts only if the probe projects under 45 minutes. A hard `timeout 3600` caps the job.
- Before it starts, I ping prism-09 that a 12-worker job is going onto the machine.

### Build mismatch (objection, your call)

The core and logical rows (2026-10-06 18:18 UTC) predate the rail-X fix (`9cb6c53`) and the touched-node scoring and idle-wire change (`561bcfb`). The breadth rows (2026-10-07 07:39 UTC) and the new Logical-SABRE rows run on the current build. On quick core, routes and realization choices were identical across both builds, so SWAP counts carry over. Depth and duration can differ, because the rail-X fix changes single-rail gates. A 69-cell suite would then mix builds in its depth and duration columns.

The final core and logical re-run is pending anyway. It costs about (3,457 + 3,451 + 1,944) CPU-s / 12 ≈ **12–15 minutes wall**. I recommend running it in the same background job (core first, then logical with both circuit sets), so the suite comes from one build. If you say no, the export marks the 16 MQT cells' depth and duration as pre-`9cb6c53`, and the export is rebuilt after the final re-run. The export is a pure function of the rows either way.

## 3. One export: `scripts/paper/export_suite.py` → `artifacts/paper/paper_export/suite/`

The export reads core, breadth and both logical files. It checks that every (workload, topology, seed, arm) key is present once, and skips only the 20 infeasible Logical-SABRE rows. It reuses `paper_common.bootstrap_interval` (2,000 resamples, paired seeds, seed 0). The 23 workloads share the same 20 seeds, so one paired seed resample covers the whole suite.

The metrics are routing SWAPs (`router_inserted_swaps`), physical depth and duration (`duration_ns`). There are 69 cells: 23 workloads × 3 topologies.

1. **Cells.** For each cell, the reduction is 1 − mean(PRISM)/mean(Greedy), with a 95% interval. The export counts, per metric and topology and suite-wide, how many cells are lower, tied and higher, and how many have intervals above or below 0. `per_cell.csv` and `per_cell.tex`.
2. **Per-run losses.** For each metric, the number of the 1,380 paired runs in which PRISM is higher than Greedy, with the largest loss in absolute units and the cell it occurs in.
3. **Distribution (A-1, B-3).** For each workload, the min, median and max of the per-run reduction over its 60 paired runs. Runs where Greedy is 0 are counted as ties and left out of the ratio. For each topology, the min, median and max of the cell reductions across the 23 workloads. `distribution.csv`.
4. **Suite aggregates, per topology, with intervals.**
   - **Headline: equal weight**, the mean of per-workload reductions. On summed Greedy means over 23 workloads, gcm_h6 is 19–23% of the routing SWAPs and 38–42% of the depth, and the QASMBench seven are 65–67% of the depth. A summed reduction would mostly report one circuit. Equal weight counts each workload once.
   - Also reported: the summed reduction over all 23 workloads, and the summed reduction over the 16 MQT workloads. The MQT figure keeps continuity with §5.3's ablations and the §5.3 scaling text, which stay at 16 workloads (they are not re-run).
5. **Logical-SABRE range.** The reductions of PRISM and of Greedy relative to Logical-SABRE, per topology, both weightings, over 68 cells (knn heavy-hex not placeable, stated). The SWAP count is stated as a range, like the current 54.1–55.0% on the grid, because cleanup removes a different number of SWAPs per arm (`response_log.md`). Depth stays a single number.
6. **Macros.** `scripts/generate_eval_macros.py` reads `suite/summary.csv` for `\EvalCoreSwapReductionRange` and `\EvalCoreDepthReductionRange`. Before anything is written, the macro names are kept and their meaning changes from "16 workloads, grid–hex sum" to "23 workloads, three topologies, equal weight". prism-66 decides between that and new names.

## 4. Reporting gcm_h6 and sat on heavy-hex (fixed now, whatever the merged numbers show)

- **gcm_h6** stays in every aggregate with its own bars in Fig. 9, and has one sentence in §5.2. It is the circuit with the most gates (1,905 active, 4× the next). PRISM uses fewer SWAPs on every topology, but its schedules are longer on the hexagonal lattice by the measured amount and interval, because SABRE scores SWAP distance, not parallelism (`gcm_h6.md`). It is not a footnote, and it doesn't come with a remedy we didn't ship.
- **sat on heavy-hex** is counted as "lower but interval includes 0" in the cell count. The §5.2 sentence that gives the significant-cell count names it.
- Any further cell whose interval crosses 0 or turns negative after a re-run gets the same treatment: counted, named if it reverses, and kept in.
- Nothing is dropped, re-seeded or re-run because of its result.

## 5. Proposed paper changes (active source: `../rebuttal_minimal.patch`)

Each block replaces sentences in place and is no longer than what it replaces, except where noted.

- **§5.1 suite sentence** (`05_evaluation.tex:9`): 23 workloads, the two sources, the widths 8 and 11–25, the selection rule in one sentence (QASMBench medium-scale circuits from families outside the MQT suite that need routing, without mid-circuit resets or more than 10^4 two-qubit gates), the QASMBench citation (a new bib entry), and the randomcircuit sentence with recomputed numbers. Net +1 sentence. The device-graph sentence gains heavy-hex.
- **§5.2 result paragraphs** (`:35`, `:37`, `:39`): the cell counts (69 cells and 1,380 runs replace 32 cells and 640 runs), the suite reductions with intervals, the Logical-SABRE sentence, and the gcm_h6 and sat sentences from §4.
- **Fig. 9** (`eval_core_by_benchmark_topologies`, a full-width `figure*` of 3 topology rows × 2 metric columns, 7.15 × 4.8 in): **same width and layout**. The bars go from 16 to 23 per panel, so the spacing per bar shrinks from 0.21 in to 0.15 in, and labels at 6.2 pt rotated 52° still fit. A thin vertical separator and a bracket label mark the MQT and QASMBench groups, and the order within each group stays the hex-SWAP order. No second row is needed. A third metric column (duration) would need 7.15 × 4.8 in for 3 × 3 panels and smaller panels. **Recommendation:** keep SWAPs and depth, and give duration in the text and the per-cell table, as now. The caption: "23 workloads", widths, seeds.
- **Fig. 10 caption** (`:105`): "the 16 workload means" becomes 23, once the aggregate figure takes the suite.
- **Intro** (`01_intro.tex:42`): "Across 16 workloads with eight logical qubits and two target topologies" becomes 23 workloads with 8 to 25 logical qubits and three topologies, plus the macros.
- **Abstract** (`abstract.tex`): hard-coded 31.3% and 12.4% become the new headline values. They should become the macros, if the abstract's build allows it.

## 6. Numbers that change from 16 to 23 workloads

Paper (all in `paper/`):

| where | now | becomes |
|---|---|---|
| abstract | 31.3% SWAPs, 12.4% depth | suite headline |
| intro :42 | "16 workloads … two target topologies", `\EvalCoreSwapReductionRange`, `\EvalCoreDepthReductionRange` | 23 workloads, 3 topologies, macros recomputed |
| §5.1 :9 | "16 algorithm-level workloads", randomcircuit 40.8/38.9% and 31.3→33.6%, 26.0→29.2% | 23 workloads, rule, recomputed randomcircuit sentence (heavy-hex gap, §1) |
| §5.2 :35 | 32 means, 27 fewer and 5 ties, 5 of 640 runs, depth 16 grid and 11/2/3 hex | 69 cells and 1,380 runs; counts per metric |
| §5.2 :37 | 31.3/26.0%, 28.7/23.2%, 12.4/7.9%, 13.1/7.5% | suite aggregates (§3.4) |
| §5.2 :39 | Logical-SABRE: Greedy 46.1/40.4%, PRISM 63.0/55.9%, depth 20.8/25.2% | 68-cell range (§3.5) |
| Fig. 9 + caption | 16 workloads | 23 |
| Fig. 10 caption :105 | "16 workload means" | 23 |
| macros | `EvalCoreSwapReductionRange` 26.0–31.3%, `EvalCoreDepthReductionRange` 7.9–12.4% | recomputed |

These stay at 16 workloads and get a scope phrase where needed: the front-commit ablation (`:66`), device slack (`:70`), the scaling sweep (`:41`, `:43`), the device projections at n = 16 (`:94`), and the Discussion figure caption (`06_discussion.tex:42`). The scaling sweep is width-swept and QASMBench has fixed widths, so the sweep can't include the seven.

Rebuttal (`research/rebuttal/`):

| where | now | becomes |
|---|---|---|
| `archive/rebuttal_letter_pre_minimal.md` breadth paragraph (A-2) | separate 21-cell breadth result, 7.9–64.7%, 20/21 | rewritten for the 69-cell suite |
| `archive/rebuttal_letter_pre_minimal.md` randomcircuit sentence | 31.3→33.6%, 26.0→29.2% | recomputed |
| `archive/rebuttal_letter_pre_minimal.md` A-1 / B-3 (distribution, intervals) | 16-workload numbers where quoted | 23-workload distribution (§3.3) |
| `response_log.md` G5 and R2 | breadth result as separate | the suite result, same session |
| `reviews.md` G5, R2 status | breadth done / min-median-max pending | updated |
| `response_log.md` | Logical-SABRE count range, suite rows | evidence and change record |

## 7. Order

1. prism-66 reviews this plan, decides the open items (cc_n12, the randomcircuit heavy-hex run, the core re-run, the macro names) and gives a go.
2. One-seed Logical-SABRE probe, then the full job in the background (with the core and logical re-run if approved). I ping prism-09 before it starts.
3. `export_suite.py`; verify each number from the rows; stage block 08; log G5 and R2; update `reviews.md`. Commit with `git commit --no-verify -- <paths>` and push.
4. The route-selection objective figure in the manuscript.

## 8. 2026-10-11: gcm_h6 excluded by a size clause (Evan's decision, made after the results were seen)

This section was written after the 25-workload results were known, and it changes what §4 fixed ("Nothing is dropped, re-seeded or re-run because of its result"). It is stated here so the paper and the rebuttal can say the same thing: the exclusion is post hoc. The pre-registered rule (§1) does not exclude gcm_h6; `gcm_h6_audit.md` (§1 there) checks every clause. The audit that led here is in `gcm_h6_audit.md` and `../response_log.md`: on gcm_h6 PRISM's hexagonal-lattice schedules are 7.2% [1.0, 13.7] longer than Greedy's, the only significant duration loss in the suite, while PRISM removes 29–65% of its SWAPs. Evan decided on 2026-10-11 to cut gcm_h6 from the suite with a uniform size clause rather than report the cell. The clause:

> **Clause 7 (size, added 2026-10-11).** Circuits whose two-qubit gate count exceeds five times the suite median are excluded. The count is the one clause 4 already uses (gates after unrolling to CX; the frozen circuits in `artifacts/paper/manifests/circuits/`).

Checked against every workload (counts from the 2026-10-11 suite audit, `transpile(basis_gates=["cx","u"], optimization_level=0)` of the frozen circuits; suite median over the 25 workloads = 68):

| circuit | two-qubit gates | ratio to median | 5× = 340 |
|---|---|---|---|
| gcm_h6 | 762 | 11.2 | **excluded** |
| sat | 252 | 3.7 | stays |
| randomcircuit (outside the suite) | 222 | 3.3 | stays |
| qram | 136 | 2.0 | stays |
| multiplier | 132 | 1.9 | stays |
| rg_qft_multiplier | 120 | 1.8 | stays |
| the other 19 | 7–115 | ≤ 1.7 | stay |

Every threshold from 3.8× to 11.2× the median removes gcm_h6 and nothing else (3.3× is randomcircuit's ratio, so 3.4× to 11.2× if randomcircuit is counted); 5× is a round number inside that window, not a tuned one. The same holds if the count is taken after the dual-rail logical pass (CRZ gates: gcm_h6 762 against a median of 39, sat 146, randomcircuit 179; 5× = 195 again removes only gcm_h6). A compile-time budget reads less cleanly: gcm_h6 takes 118 s per compile against a 3 s median (40×), but 5× the median also removes sat (16 s) and qram (15 s), and the number is machine-dependent, so the gate count is the clause.

Effect, on the 20-seed rows (`gcm_h6_audit.md` §3): removing gcm_h6 lowers the equal-weight SWAP headline by 1.4 / 1.0 / 0.5 points (grid / hex / heavy-hex) and raises depth by 0.3 / 0.6 / 0.1 and duration by 0.3 / 0.6 / 0.2 points; the cell it removes is the one PRISM loses on duration and also the one with PRISM's largest SWAP reductions. Evan also decided on 2026-10-11 that **randomcircuit joins the suite** as a workload (MQT Bench's sampled circuit at n = 8, 222 two-qubit gates, 3.3× the median, so clause 7 keeps it; the §1 exclusion "a sampled random circuit, not an algorithm" is withdrawn, and the §5.1 "including it would raise" sentence goes). The suite is **16 MQT algorithms + randomcircuit + 8 QASMBench = 25 workloads, 75 cells**, and with the 64 seeds of `seeds80/README.md`, 4,800 paired runs. Logical-SABRE covers 74 cells (knn on heavy-hex is not placeable); its randomcircuit rows are new (`artifacts/paper/raw/logical_randomcircuit.jsonl`). `scripts/paper/export_suite.py` applies the exclusion (`EXCLUDED`) and reads randomcircuit with the other sources; the 16-MQT aggregate (`mqt16`) still leaves randomcircuit out so §5.3 keeps its reference set.
