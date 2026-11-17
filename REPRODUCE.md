# Reproducing the paper

This guide maps every figure, table and printed result of the arXiv paper *PRISM: A Logical–Physical Boundary Compiler for Dual-Rail Qubits* to the command that produces it and the data that command reads. The saved result rows are in the repository, so most items regenerate in seconds. Regenerating the rows themselves means recompiling the workloads and takes hours.

## Setup

Requirements: Linux x86-64, Python 3.12, a Rust toolchain (`rustup`, Rust 1.97 or newer), and `uv` (optional; without it `pip` installs unpinned versions).

```
git clone --branch revision-r3 --single-branch https://github.com/Yale-QCS/prism.git prism-paper
cd prism-paper
make init          # creates .venv from uv.lock and builds the Rust extension
make test          # optional: Rust and Python tests, and the dual-rail simulator checks
```

The recorded rows were produced with Python 3.12.3, Qiskit 2.4.1 and MQT Bench 2.2.2. Qiskit 2.5 changes stock SABRE and does not reproduce the rows.

Run every command below from the repository root with `.venv/bin/python`. The paper source is not part of this branch; compare the regenerated figures and numbers with the arXiv PDF, against which every command here was checked.

The Steane-memory experiment (Table II) also needs the packages in `research/rebuttal-r3/runs/steane/requirements.txt` (Stim, `ldpc`, `qldpc`) in a second environment that can import this repository's `.venv` packages; pass its interpreter to `run.sh` as `QEC_PYTHON`. The summary script `report.py` runs in the main `.venv`.

Each script writes its outputs next to itself or under `artifacts/paper/paper_export/` unless it takes `--out`.

## Runtime classes

- **seconds**: reads saved rows or saved circuits; under 30 s on a desktop.
- **minutes**: recompiles a small experiment; under 15 min on 6 to 12 cores.
- **hours**: recompiles or resimulates a full experiment. CPU-hours below are the summed `compile_time_s` of the saved rows, so they exclude circuit loading and process start-up.

## Figures

| Paper item | Command | Reads | Runtime |
| --- | --- | --- | --- |
| Figs. 1, 2, 4, 5, 6, 8 and Algorithm 1 (drawn in TikZ) | none; built with the paper | `paper/figures/{prism_overview,availability_motivation,quotient_example,crz_candidates,compiler_strategies,logical_swap_candidates,alg_drsabre}.tex` | n/a |
| Fig. 3 (`unitary_completions.pdf`; the left inset is `completion_hierarchy.tex`) | `.venv/bin/jupyter-execute src/notebooks/paper/03_completions.ipynb` → `build/figures/unitary_completions.pdf` | nothing; computes Weyl coordinates of sampled completions | seconds |
| Fig. 7 (`strategy_ladder.tex`) | `.venv/bin/python scripts/paper/emit_strategy_ladder.py --output <file>` (compiles the five-qubit example with the three compilers and stops if the SWAP and depth counts differ from the paper's) | nothing | under a minute (three small compilations) |
| Fig. 9 (`eval_suite_v25.pdf`) | `B=$PWD/research/rebuttal-r3/runs/logical_budget; .venv/bin/python scripts/paper/export_suite.py --logical $B/logical_budget.jsonl $B/logical_qasmbench_budget.jsonl $B/logical_added_budget.jsonl $B/logical_seeds64_budget.jsonl $B/logical_randomcircuit_budget.jsonl --out <dir>` → `<dir>/suite_figure.pdf`, `summary.json`, `per_cell.csv` | `artifacts/paper/raw/{core_swaps,breadth_swaps,breadth_added_swaps,randomcircuit_swaps}.jsonl` and the five Logical-SABRE files named in the command | seconds; rows: about 20 CPU-hours (Greedy and PRISM) plus about 1 CPU-hour (Logical-SABRE) |
| Fig. 10 (`eval_scaling_combined_v25.pdf`) | `.venv/bin/python scripts/paper/export_scaling.py` → `artifacts/paper/paper_export/scaling/` | `artifacts/paper/raw/scale_swaps.jsonl` | seconds; rows: about 67 CPU-hours |
| Fig. 11 (`eval_ablations.pdf`) | `D=research/rebuttal-r3/runs/front_commit_isolated; .venv/bin/python research/rebuttal/tradeoff/ablation_objectives_figure.py --ablation $D/front_commit_swaps_isolated.jsonl $D/front_commit_swaps_heavyhex_isolated.jsonl --out <stem>` | `artifacts/paper/raw/core_swaps.jsonl`, the two files in the command, `research/rebuttal/tradeoff/data/w16_{swaps,duration}.jsonl` | seconds; rows: 12 min (panel a), about 6 CPU-hours (panel b) |
| Fig. 12 (`eval_hardware.pdf`) | `.venv/bin/python research/rebuttal/hardware/figure.py` → `research/rebuttal/hardware/figures/eval_hardware.pdf` | saved routed circuits `research/rebuttal/wallclock/data/swaps/circuits_n{8,12,16}/*.qpy` and `.../swaps/heavy_hex/circuits_n{8,12,16}/*.qpy` (1,440 files, 92 MB, tracked); `research/rebuttal/sensitivity/data/swaps/parts_n*.jsonl` and `.../heavy_hex/parts_n*.jsonl`; `research/rebuttal/wallclock/data/bare_n*.jsonl`, `bare_direct_n8.jsonl`, `swaps/v3_n8.jsonl`, `swaps/heavy_hex/{bare_n*,v3_n8}.jsonl` | about 20 s; circuits and simulations: hours |

## Tables

| Paper item | Command | Reads | Runtime |
| --- | --- | --- | --- |
| Table I (device models) | none; parameters are constants in `research/rebuttal/wallclock/sim.py` (`MEHTA_IDLE`) and `bare.py` (`CENTRAL`), documented in `research/rebuttal/wallclock/MODEL.md` | | n/a |
| Table II, dual-rail rows, and the Section V-E text | `.venv/bin/python research/rebuttal-r3/runs/steane/report.py skipgate` | `research/rebuttal-r3/runs/steane/rows_skipgate/{readout,checks}_{X,Z}_{greedy,prism}_<seed>.json` (160 files) and `research/rebuttal/outer_qec/data/mehta_memory/{X,Z}_hex_lattice_{greedy,prism}_<seed>.json` | seconds; rows: `research/rebuttal-r3/runs/steane/run.sh skipgate 100000 readout checks`, under an hour on six cores |
| Table II, transmon rows | read lines "X hex_lattice" and "Z hex_lattice" of `research/rebuttal/outer_qec/data/mehta_memory/report.txt`; each value is the pooled `errors / shots` of the `results` entries in `{X,Z}_hex_lattice_transmon_<seed>.json` in that folder (20 routes, 50,000 shots per route and CZ error) | those files | rows: hours (`research/rebuttal/outer_qec/bare_memory.py`) |
| Tables III and IV (device graphs, workloads) | none; the graph rules are in the appendix text, the workload lists in `research/rebuttal/suite/swaps/{core_swaps,breadth_swaps,breadth_added_swaps,randomcircuit_swaps}.toml`, and the frozen circuits in `artifacts/paper/manifests/circuits/` | | n/a |
| Table V (Steane noise model) and the appendix result with a flag at every loss | model: `research/rebuttal-r3/runs/steane/skipgate.py` and `flag_memory.py`; result: `.venv/bin/python research/rebuttal-r3/runs/steane/report.py table4`, row "(a)" | `research/rebuttal-r3/runs/steane/rows_table4/ideal_*.json` | seconds |

## Numbers in the text

| Paper text | Command | Reads | Runtime |
| --- | --- | --- | --- |
| Abstract, introduction, conclusion | restate Section V values | | |
| Section V-A: nine excluded workloads need at most four routing SWAPs | `.venv/bin/python research/ablations/report.py` (line "excluded nine", grid and hexagonal lattice) and the table in `research/rebuttal-r3/runs/excluded_heavyhex/README.md` (heavy-hex) | `artifacts/paper/raw/excluded_swaps.jsonl`, `research/rebuttal-r3/runs/excluded_heavyhex/excluded_swaps_heavyhex.jsonl` | seconds |
| Section V-B, first paragraph (suite SWAP and depth reductions with intervals, 73 of 75 means, 202 of 4,800 runs, dj depth, Logical-SABRE comparisons) | the Fig. 9 command; values are in `<dir>/summary.json` (`aggregate`, `router_inserted_swaps`, `physical_depth`, `logical`) and `per_cell.csv` | as Fig. 9 | seconds |
| Section V-B, scaling and compile-time paragraphs | the Fig. 10 command; printed JSON and `scaling_summary.csv`, `timing_summary.csv` | `artifacts/paper/raw/scale_swaps.jsonl` | seconds |
| Section V-C, front-commit ablation (24.8/22.2/17.3%, 5.8/5.2/1.4%, qaoa) | the Fig. 11 command; printed per graph | as Fig. 11 | seconds |
| Section V-C, tie-break and larger grids (11.1/10.4 → 9.9/9.9%, 28.8% and 28.5%) | `.venv/bin/python research/ablations/report.py`, lines "tiebreak" and "slack" (the script stops with a `KeyError` after printing them, at a heavy-hex Logical-SABRE summary the paper does not use) | `artifacts/paper/raw/{core_swaps,tiebreak_swaps,slack_swaps}.jsonl` | seconds |
| Section V-C, route-selection objectives (6–10%, 9–13%, 27.6–34.4%, 12.5–16.4%) | `.venv/bin/python research/rebuttal/tradeoff/objectives_bars.py` (PRISM against Greedy per objective) and `cd research/rebuttal/commutation && ../../../.venv/bin/python objectives_figure.py --w16` (SWAPs and durations per objective; the 6–10% and 9–13% are ratios of the printed values) | `research/rebuttal/tradeoff/data/w16_{swaps,depth,duration,error}.jsonl` | seconds; rows: about 12 CPU-hours |
| Section V-C, last paragraph: Greedy selecting from preparation sites (11%, −2.7% to +1.2%, 1.3% to 2.4%) | `.venv/bin/python research/rebuttal-r3/runs/greedy_prep_sites/compare.py` and `aggregate.py` | `probe.jsonl`, `probe_prepsites.jsonl` in that folder (120 Greedy runs; `greedy_prep_sites.patch` is the unapplied compiler change they used) | seconds; rows: `run_prepsites.sh`, about 10 min |
| Section V-C, last paragraph: Logical-SABRE under other matchings (24% fewer to 9% more; 0.5% to 36% fewer; four disconnected) and its fallback shares (50%; 35%, 53%, 48%) | `.venv/bin/python research/rebuttal-r3/runs/baseline_sensitivity/p3_analyze.py` (the "new 40/16/40" block) and `p5_analyze_budget.py` | `p3_matchings_budget.jsonl`, `p2_suite_budget.jsonl` in that folder and the Fig. 9 Logical-SABRE rows | seconds; rows: `p3_matchings_budget.py`, `p2_budget.py` |
| Section V-D, durations, shot overhead (geometric means and medians), sensitivity geometric means | `.venv/bin/python research/rebuttal/hardware/section_numbers.py` | `research/rebuttal/sensitivity/data/swaps/parts_n*.jsonl`, `.../heavy_hex/parts_n*.jsonl` | seconds |
| Section V-D, median-workload attempts, keep probability, detection efficiency | `.venv/bin/python research/rebuttal/hardware/medians.py` | Fig. 12 circuits at 16 logical qubits, `parts_n16.jsonl` | about 15 s |
| Section V-D, doubled residual errors (0.76 and 0.75) | `.venv/bin/python research/rebuttal/hardware/residual2x.py` | Fig. 12 circuits at 16 logical qubits | about 15 s |
| Section V-D, sampling-time ratios against the transmon (2.5/1.2/0.34, 2.9/1.8/0.72) | `.venv/bin/python research/rebuttal/hardware/wallclock_cost.py` | `research/rebuttal/hardware/out/rows.jsonl` (rebuilt by `equations.py` from the Fig. 12 circuits) | seconds |
| Section V-D, proxy against simulation (factors 1.6, 1.8, 1.2) | `.venv/bin/python research/rebuttal/hardware/proxy_check.py` (1.8 at 16 qubits, 1.2 transmon) and `equations.py` (1.6 at eight qubits, grid and hexagonal lattice) | `research/rebuttal/hardware/out/rows.jsonl`, `research/rebuttal/sensitivity/data/swaps/dephasing_n16.jsonl`, `research/rebuttal/wallclock/data/{bare_n*,bare_direct_n8}.jsonl`, `swaps/v3_n8.jsonl` | seconds |
| Section V-D, proxy infidelity reductions (7.4/9.1/10.0%), Fig. 12c medians (0.70 → 0.14, 0.96 → 0.82), and the proxy factor 1.6 over all 480 eight-qubit circuits | `.venv/bin/python research/rebuttal/hardware/fig12_numbers.py` (runs `figure.py`, which also rewrites `research/rebuttal/hardware/figures/eval_hardware.pdf`) | Fig. 12 circuits | about 20 s |
| Section V-E | the Table II command; the SWAP, duration and seed-count columns give the remaining values | as Table II | seconds |
| Appendix (Steane noise), flag at every loss: 25.7% and 25.4% | `.venv/bin/python research/rebuttal-r3/runs/steane/report.py table4` | `rows_table4/ideal_*.json` | seconds |

## Regenerating the rows

All compile experiments run through `scripts/paper/run_fairness.py --config <file.toml> --workers N`. A run is resumable and ends by checking that every declared row is present. `--out` is relative to `artifacts/paper/raw/`.

| Rows | Config or script | Cost |
| --- | --- | --- |
| `core_swaps`, `breadth_swaps`, `breadth_added_swaps`, `randomcircuit_swaps`, `scale_swaps`, `tiebreak_swaps`, `slack_swaps`, `excluded_swaps` | `research/rebuttal/suite/swaps/<name>.toml` (`research/rebuttal/suite/swaps/run.sh` runs them all in one background job) | 6.5, 10.0, 1.6, 2.0, 66.9, 1.0, 2.8 and 0.6 CPU-hours |
| Logical-SABRE rows of Fig. 9 | `research/rebuttal-r3/runs/logical_budget/run.sh` | 11 min on five cores |
| Front-commit ablation | `research/rebuttal-r3/runs/front_commit_isolated/run.sh` | 12 min on five cores |
| Excluded workloads on heavy-hex | `research/rebuttal-r3/runs/excluded_heavyhex/run.sh` | under 1 min |
| Objective study at 16 qubits | `research/rebuttal/tradeoff/configs/w16_{swaps,depth,duration,error}.toml` | about 3 CPU-hours each |
| Hardware circuits, simulations and transmon compiles | `research/rebuttal/wallclock/run.py`, `resim.py`, `bare.py`; `research/rebuttal/hardware/{bare_heavyhex,resim_heavyhex}.py`; then `research/rebuttal/sensitivity/extract.py` and `dephasing.py` (see `research/rebuttal/hardware/README.md`) | hours |
| Steane memory | `research/rebuttal-r3/runs/steane/run.sh` (see its README) | under an hour |

Seeds are fixed. In a re-run of 4,796 saved Logical-SABRE rows with the pinned environment, all but one matched in routing SWAPs and depth (one depth differed by one layer); other library versions can shift the aggregates.

## Notes

- `make figures`, `ARTIFACT.md` and `scripts/paper/README.md` describe the pipeline of the previous version of the paper and do not regenerate Figs. 9, 11 or 12; use the commands above.
- The Fig. 7 command and the commands under "Regenerating the rows" were not re-run when this guide was checked; every other command above was, and its output matches the paper.
- The regenerated Fig. 3 differs from the paper's file only in the shade of the orange lines (Matplotlib version).
- Some notes and logs under `research/` record absolute paths from the machine the experiments ran on.
