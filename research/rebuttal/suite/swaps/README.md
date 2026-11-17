# SWAP-selected re-run (2026-10-11)

Evan's decision on 2026-10-11: route selection goes back to SWAP count (`objective = "swaps"`), as in the submission. This directory re-runs the suite, the §5.3 ablations and the scaling study under that objective. Its rows supply the numbers of the submitted revision. The J-selected rows (`core.jsonl`, `breadth.jsonl`, `randomcircuit.jsonl` and the `_seeds80`/`_seeds64` files) are supporting history.

Settings: 64 seeds (0 to 6300, 100 apart), grid, hex lattice and heavy-hex, gcm_h6 excluded by the size clause, randomcircuit included. The search budget and tie-break are the same as in the J runs.

## Runs

From the repository root, `research/rebuttal/suite/swaps/run.sh` runs each config through `scripts/paper/run_fairness.py` into `artifacts/paper/raw/<name>.jsonl`.

| config | rows | used by |
|---|---|---|
| `core_swaps`, `breadth_swaps`, `breadth_added_swaps`, `randomcircuit_swaps` | 6144, 2304, 768, 384 | `scripts/paper/export_suite.py` (Fig. 9, §V-A/B) |
| `front_commit_swaps`, `front_commit_swaps_heavyhex` | 640, 320 | `research/rebuttal/tradeoff/ablation_objectives_figure.py` (Fig. 11a) |
| `tiebreak_swaps`, `slack_swaps`, `excluded_swaps` | 640, 1280, 720 | `research/ablations/report.py` (§V-C, §V-A) |
| `scale_swaps` | 2240 | `scripts/paper/export_scaling.py` (Fig. 10) |

`scale_resume.sh` restarted the scale job without its 10 h timeout. `run.log`, `run_scale.log` and `run_front_commit_heavyhex.log` are the run logs.

`full/` holds the full-suite front-commit, duration- and depth-selected configs queued for Fig. 11. That queue was cancelled before it started. It produced no rows, and Fig. 11b uses the n = 16 objective rows in `research/rebuttal/tradeoff/data/`.
