# 80 seeds for the 25-workload suite (pre-registered 2026-10-08, prism-66, before any run)

Evan, 2026-10-08: some Fig. 9 error bars are too wide. The suite has 20 seeds per cell. This run adds 60 more (2000 to 7900, 100 apart, so no two seeds share layout starts) for both Greedy and PRISM, on the same build as the suite rows (47b2aa0; d57bf82 adds row fields only).

- Configs: `core.toml` (16 MQT workloads), `breadth.toml` (7 QASMBench), `breadth_added.toml` (qf21, bv). 4,500 cells, 9,000 runs.
- Rows: `artifacts/paper/raw/{core,breadth,breadth_added}_seeds80.jsonl`.
- Every suite statistic (Fig. 9, block 08, CLAIMS §1) is recomputed on all 80 seeds with the same estimators. The 20-seed numbers are not kept as an alternative.
- Expected effect: interval widths shrink by about half (√4). Cells whose Greedy mean is one or two SWAPs (vbe and cdkm on the grid) stay wide in percent, because one SWAP is a large fraction of the mean. The figure states this rather than hiding it.
- The §5.3 ablations stay on 20 seeds, paired with seeds 0 to 1900 of these rows.

**Paused 2026-10-08 12:20 by Evan's call** (deeper seeds wait until closer to the deadline). Partial rows on disk, untracked: core_seeds80 5,760 (complete), breadth_added_seeds80 720 (complete), breadth_seeds80 990 of 2,520. Resume by re-running run.sh; the runner skips existing run_ids only if it supports resume, otherwise delete the partial breadth file first.

## 2026-10-11: cut to 64 seeds (Evan's decision)

The run resumed on 2026-10-11 and was stopped at 15:19 UTC during gcm_h6/grid (`run.log`). Evan set the suite at **64 seeds per cell**: the 20 original seeds (0 to 1900) plus the first 44 added seeds (2000 to 6300, 100 apart). Nothing is renamed: the files keep their `_seeds80` names, and `scripts/paper/export_suite.py` uses only rows with `outer_seed <= 6300` (`MAX_SEED`). Rows at 6400 to 7900 stay in the files unused.

State of the rows at the stop, and what the 64-seed suite still needed:

| rows | content | through 6300 |
|---|---|---|
| `core_seeds80.jsonl` | 16 MQT workloads, Greedy and PRISM, seeds 2000–7900 | complete |
| `breadth_added_seeds80.jsonl` | qf21, bv, seeds 2000–7900 | complete |
| `breadth_seeds80.jsonl` | sat, seca, multiply at seeds 2000–7900; gcm_h6/grid at 2000–3300 only; **qec9xz, qram and knn were never reached** | gcm_h6 incomplete and excluded anyway (`../README.md` §8); the three others run below |
| `breadth_rest_seeds64.jsonl` | qec9xz, qram, knn, Greedy and PRISM, seeds 2000–6300 (`breadth_rest_seeds64.toml`) | run 2026-10-11 |
| `logical_seeds64.jsonl` | Logical-SABRE at seeds 2000–6300 on the 24 workloads (`logical_seeds64.toml`); knn/heavy-hex fails as not placeable, as before | run 2026-10-11 |
| `logical_randomcircuit.jsonl` | Logical-SABRE on randomcircuit at all 64 seeds (`logical_randomcircuit.toml`); randomcircuit had no Logical-SABRE rows before | run 2026-10-11 |
| `randomcircuit_seeds64.jsonl` | Greedy and PRISM on randomcircuit at seeds 2000–6300 (`randomcircuit_seeds64.toml`); randomcircuit is the 25th workload (`../README.md` §8) | run 2026-10-11 |

Scripts: `run_seeds64.sh` and `run_seeds64_random.sh` (7 workers; logs `run_seeds64.log`, `run_seeds64_random.log`). Same build as the paused run. Every suite statistic is recomputed on the 64 seeds with the same estimators; the 20-seed numbers are kept only for comparison in the rebuttal log. The expected interval shrink is about √(64/20) ≈ 1.8×.
