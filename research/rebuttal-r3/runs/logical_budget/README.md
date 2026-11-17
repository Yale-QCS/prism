# Logical-SABRE at Greedy/PRISM's search budget (R1, 2026-11-12)

Logical-SABRE is kept as a quantitative reference with no algorithmic engineering effort. This run changes only its search
budget on the quotient graph, to the one Greedy and PRISM use (§V-A). The matching, `DirectCommit`, the physical
stage (`SabreSwap(trials=20)` of the O3 preset) and route selection are unchanged.

## What changed

| | submitted rows | these rows |
|---|---|---|
| quotient `SabreLayout` `layout_trials` | 20 random + dense, identity, reverse | **40** random + dense, identity, reverse |
| quotient `SabreLayout` `max_iterations` (forward-backward pairs) | 4 | **16** |
| quotient `SabreLayout` `swap_trials` (trials of each start's final route) | 20 | **40** |
| quotient `SabreSwap` `trials` | 20 | 40 (a no-op: `SabreLayout` already routes the circuit, and this pass added 0 SWAPs in all 1,480 probed runs) |

What each parameter does, read in Qiskit 2.4.1's source (`crates/transpiler/src/passes/sabre/layout.rs` at tag 2.4.1,
copy in `/home/evm9/prism/scratch/r3-logical-budget/q241/`). `sabre_layout_and_routing` makes `num_random_trials`
random starts (`layout.rs:81`). `add_heuristic_layouts` then appends dense, identity and reverse starts (`:444-458`).
The ring start for 127/133/156-site devices never applies on these quotient graphs. Each start runs `max_iterations`
forward and backward routing passes (`:391-395`) and a final `swap_map` with `num_swap_trials` trials (`:409-415`). The
start with the fewest SWAPs wins (`:168`). This has the same shape as `PrismRouting._starting_layouts`
(`prism_routing.py`: `layout_starts` random plus dense, identity and reverse, `max_iterations` forward-backward pairs,
`swap_trials` final trials per start). So 40/16/40 is the exact equivalent, with 43 starts in both. The starts' seeds
differ: Qiskit draws them from `Pcg64Mcg(seed)`, PRISM uses `seed + t`. They are a different RNG, not a different budget.

Code (uncommitted):
- `src/marabbecca/staged_pms.py`: `build_pm(strategy="logical")` reads `budget.layout_starts`,
  `refinement_iterations` and `prism_swap_trials` into the quotient `SabreLayout`/`SabreSwap`. `budget=None` gives
  `SearchBudget()`, i.e. 20/4/20, the submitted setting. It raises if the budget sets a non-default heuristic or
  tie-break, because Qiskit's `SabreLayout` has neither knob.
- `scripts/paper/run_fairness.py`: the logical arm takes `layout_starts`, `refinement_iterations` and
  `prism_swap_trials` from the config, with defaults 20/4/20. Rows record the values used in
  `quotient_sabre_layout_trials`, `quotient_sabre_refinement_iterations` and `quotient_sabre_swap_trials`.
- `src/marabbecca/lowering/commit.py`: one docstring line.
- `scripts/paper/export_suite.py`: `--logical FILE...` (the Logical-SABRE row files) and `--out DIR`. With no
  arguments it reads and writes what it did before. `summary.json` now also has `figure_means`, the Fig. 9 panel (d)/(h)
  bar heights.

The old setting still reproduces. Every existing logical config, unchanged, runs at 20/4/20. All 4,796 successful
submitted rows were re-run from their own configs with the changed code (`/home/evm9/prism/scratch/r3-logical-budget/old_*.jsonl`).
4,795 match the raw rows in routing SWAPs and depth. The one exception is qf21, hexagonal lattice, seed 100: the same
SWAP count and depth 171 against 172, the same mismatch `audit/baseline-check.md` §3 found before this change.
`export_suite.py` on the submitted rows reproduces `artifacts/paper/paper_export/suite/summary.json` exactly, apart from
the added `figure_means` key.

## Configs and rows

Each config is its submitted counterpart, with a new `experiment_id` and the three budget keys. Workloads, widths,
graphs, seeds, objective (`error`, which Logical-SABRE ignores) and `reschedule = true` are unchanged.

| config | copied from | rows |
|---|---|---|
| `logical_budget.toml` | `configs/paper/logical.toml` (16 MQT, n = 8, seeds 0–1900) | 960 |
| `logical_qasmbench_budget.toml` | `research/rebuttal/suite/logical_qasmbench.toml` (7 QASMBench, incl. gcm_h6, seeds 0–1900) | 420 (20 knn heavy-hex failures) |
| `logical_added_budget.toml` | `research/rebuttal/suite/logical_added.toml` without cc (qf21, bv) | 120 |
| `logical_seeds64_budget.toml` | `research/rebuttal/suite/seeds80/logical_seeds64.toml` (24 workloads, seeds 2000–6300) | 3168 (44 knn heavy-hex failures) |
| `logical_randomcircuit_budget.toml` | `research/rebuttal/suite/seeds80/logical_randomcircuit.toml` (seeds 0–6300) | 192 |

Total: 4,860 rows, the same (workload, graph, seed) cells as the 4,860 submitted Logical-SABRE rows that
`export_suite.py` reads. cc is left out because every arm fails on it (suite README, clause 3), and its submitted
rows are in `suite_unsupported.jsonl`, not in the logical files. As before, the only failures are the 64 knn heavy-hex
runs ("More virtual qubits (25) exist than physical"). Those make `run_fairness.py` exit 1 at the end of two configs,
which `run.sh` expects.

## Commands

From the repository root (resumable: `run_fairness.py` skips `run_id`s already in the output):

```
systemd-run --user --scope -q -p MemoryMax=5G -p MemorySwapMax=0 research/rebuttal-r3/runs/logical_budget/run.sh > research/rebuttal-r3/runs/logical_budget/run.log 2>&1
cd scripts/paper && ../../.venv/bin/python export_suite.py --out ../../research/rebuttal-r3/runs/logical_budget/export \
  --logical $PWD/../../research/rebuttal-r3/runs/logical_budget/{logical_budget,logical_qasmbench_budget,logical_added_budget,logical_seeds64_budget,logical_randomcircuit_budget}.jsonl
```

`export/` holds the exporter's full output on the new rows: `summary.json`, `per_cell.csv`, `distribution.csv` and
`suite_figure.pdf/png` (Fig. 9). The Greedy-vs-PRISM content is identical to the paper export. Only the `logical`
block, the `figure_means` Logical-SABRE values and Fig. 9's Logical-SABRE bars change.

## Runtime

The pilot was seed 0 of every config, 78 cells in 27 s at 5 workers. Its new-to-old compile-time ratio was 1.7, but
the old times there come from the submitted rows, which ran under other conditions. The full run took **10.8 min wall**
at 5 workers (17:44–17:55 UTC), with `RAYON_NUM_THREADS=1`.

Compile time against the old budget, both runs under the same conditions (5 workers, `RAYON_NUM_THREADS=1`, all
4,796 successful cells):

| | old 20/4/20 | new 40/16/40 | ratio |
|---|---|---|---|
| summed compile time (CPU-s) | 1,132 | 3,172 | 2.8× |
| grid / hex / heavy-hex | 297 / 366 / 468 | 879 / 989 / 1,304 | 2.96 / 2.70 / 2.79× |
| median per run | 0.088 s | 0.309 s | 3.5× |
| per workload | | | 1.09× (bv) to 4.05× (qftentangled), median 3.3× |
| wall, 5 workers | about 4 min | 10.8 min | |

## Results (old vs new)

§V-B sentence: summed routing SWAPs over the suite workloads (25 on grid and hex, 24 on heavy-hex, because knn is not
placeable), 64 seeds, with the 95% paired-seed interval from `summary.json` `logical.*.sum_ci`.

| reduction relative to Logical-SABRE | grid old → new | hex old → new | heavy-hex old → new |
|---|---|---|---|
| Greedy, routing SWAPs (sum) | 38.1 → **34.0** [33.5, 34.5] | 31.6 → **26.8** [26.1, 27.4] | 53.8 → **52.9** [52.7, 53.2] |
| PRISM, routing SWAPs (sum) | 57.2 → **54.3** [54.0, 54.7] | 49.4 → **45.8** [45.3, 46.3] | 63.1 → **62.5** [62.3, 62.6] |
| PRISM, physical depth (sum) | 19.2 → **16.6** [16.0, 17.1] | 21.6 → **19.7** [19.1, 20.2] | 34.6 → **34.4** [34.1, 34.8] |
| Greedy, physical depth (sum) | 11.3 → 8.5 | 12.8 → 10.7 | 27.3 → 27.1 |
| Greedy, routing SWAPs (equal weight) | 43.2 → 38.0 | 35.9 → 29.7 | 53.5 → 52.8 |
| PRISM, routing SWAPs (equal weight) | 57.7 → 53.8 | 50.3 → 45.4 | 61.6 → 61.1 |
| Greedy / PRISM, final-circuit SWAPs (sum, the other end of the range) | 36.6 / 56.1 → 32.0 / 53.0 | 30.7 / 48.8 → 25.8 / 45.2 | 53.1 / 62.6 → 52.3 / 61.9 |
| Greedy / PRISM, duration (sum) | 9.2 / 15.9 → 6.8 / 13.7 | 8.3 / 16.0 → 6.5 / 14.3 | 19.4 / 26.2 → 19.4 / 26.2 |

Fig. 9 panels (d) and (h), Logical-SABRE bars (mean over the workloads all three compilers place). Greedy and PRISM
are unchanged:

| Logical-SABRE | grid old → new | hex old → new | heavy-hex old → new |
|---|---|---|---|
| mean routing SWAPs | 49.67 → 46.54 | 71.85 → 67.13 | 153.24 → 150.61 |
| mean physical depth | 82.72 → 80.15 | 94.22 → 91.94 | 122.39 → 122.10 |
| (Greedy / PRISM SWAPs, for scale) | 30.73 / 21.25 | 49.17 / 36.37 | 70.87 / 56.53 |

Logical-SABRE's own summed routing SWAPs fall by 6.3% on the grid, 6.6% on hex and 1.7% on heavy-hex. Per run, 2,028
of 4,736 paired runs improve, 2,086 tie and **622 get worse**. The larger search minimizes SWAPs on the quotient graph,
and the physical SWAPs the second stage adds afterwards are not scored, so more search does not always help.

## Share of extra physical SWAPs from unavailable logical SWAPs

Method of `audit/baseline-check.md` §3: its probe (`/home/evm9/prism/scratch/r3-audit/baseline-check/lsabre_probe.py`)
was reused unchanged, with the budget injected into `run_fairness._run_one`
(`/home/evm9/prism/scratch/r3-logical-budget/p2_budget.py`), on the same 1,500 cells (25 workloads, seeds 0–1900).
The aggregation is `p5_analyze.py` pointed at the new files (`p5_analyze_budget.py`, output `p5_out_budget.txt`, same folder).
All 1,480 successful probe runs reproduce these rows' SWAPs, depth and pairs.

| graph | L-SABRE SWAPs (sum of means) | from lowered logical SWAPs | added by physical router | added share, old → new | added per unavailable logical SWAP, old → new | logical SWAPs with neither variant, old → new |
|---|---|---|---|---|---|---|
| grid | 1158.3 | 755.5 | 402.8 | 35.1 → **34.8%** | 2.13 → 2.12 | 50.9 → 50.4% |
| hex | 1693.6 | 790.8 | 902.8 | 53.2 → **53.3%** | 2.28 → 2.28 | 100 → 100% |
| heavy-hex | 3600.2 | 1860.5 | 1739.7 | 48.4 → **48.3%** | 1.88 → 1.87 | 100 → 100% |

The budget removes some logical SWAPs (grid 8,048 → 7,555; hex 8,505 → 7,908; heavy-hex 18,955 → 18,605). The share
of physical SWAPs that the second stage adds for unexecutable logical SWAPs stays where it was. That overhead comes from
the matching and the commit policy, not from the search budget.
