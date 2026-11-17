# Artifact: marabbecca (revision r2 pipeline)

## Abstract

This artifact contains PRISM, a logical-physical boundary compiler for
dual-rail qubits, built as Qiskit transpiler stages with a Rust routing
kernel. It supports the paper's evaluation claims: the controlled core
comparison (SWAP and depth reductions vs the greedy baseline), the scaling
study to 32 logical qubits, and the hardware projection (postselection shot
overhead and conditional-infidelity reductions at 16 logical qubits). Each
paper figure regenerates from a notebook in `src/notebooks/`, which checks
the headline numbers inline against the values quoted in the paper.

## Artifact check-list (meta-information)

| Field | Value |
| ----- | ----- |
| Algorithm | Realization-aware SABRE routing (PRISM / DR-SABRE); greedy, logical-SABRE, and trivial baselines |
| Program | Python package `marabbecca` + Rust extension `marabbecca._accelerate` |
| Compilation | Rust stable (`rustup`) via setuptools-rust; Python 3.12 |
| Data set | MQT Bench circuits, frozen as qpy under `artifacts/paper/manifests/circuits/`; raw result rows under `artifacts/paper/raw/` |
| Run-time environment | Linux; container image (see below) or any host with Python 3.12 + Rust |
| Hardware | x86-64; no accelerator required |
| Metrics | Routing SWAPs, physical depth, circuit duration, keep probability, postselection shot overhead, conditional infidelity |
| Output | Figures rendered in the notebooks; headline numbers asserted inline |
| Experiments | core/logical (controlled, n=8), scale (n=8-32), device projection (n=16) |
| Disk space required | ~2 GB (source build); +40 MB raw rows from Zenodo |
| Workflow preparation time | ~30 minutes (Rust build dominates) |
| Experiment completion time | Minutes per figure notebook; days to regenerate raw rows from scratch |
| Publicly available | <!-- repo URL of the frozen artifact --> |
| Code licenses | MIT (vendored `crates/src/sabre/` is Apache-2.0, Qiskit) |
| Archived (DOI) | <!-- Zenodo version DOI of the evaluated release --> |

## Description

### How to access

- Source: this repository at the artifact tag
- Archived snapshot: Zenodo DOI above
- Raw result rows: `artifacts/paper/raw/*.jsonl` (~40 MB), tracked here.

### Hardware dependencies

None beyond x86-64 Linux.

### Software dependencies

Python 3.12 + `rustup`. The recorded runs used Python 3.12.3, Qiskit 2.4.1,
MQT Bench 2.2.2, rustc 1.89.0. The crate now needs Rust 1.97; a 1.89.0 and a
1.97.1 build give byte-identical outputs on 216 same-seed compile cells.
This repository is pinned to `qiskit<2.5`;
Qiskit 2.5 changes stock SABRE and O3 and does not reproduce the rows.

## Installation

`make init` (Python 3.12 + Rust toolchain).

## Experiment workflow

Everything a paper number depends on runs from `scripts/paper/` (see its
README). The chain is raw rows -> exports -> figures and the numbers written
in the prose; the manuscript never recomputes a headline number.

Regenerating raw rows is a batch job. The core and logical-baseline rows
come from the fairness runner and the `arms` configs:

```
.venv/bin/python scripts/paper/run_fairness.py --config configs/paper/core.toml --workers 12
.venv/bin/python scripts/paper/run_fairness.py --config configs/paper/logical.toml --workers 12
.venv/bin/python scripts/paper/run_fairness.py --config configs/paper/scale.toml --workers 12
```

(`--only circuit=dj` restricts a run; `--out name.jsonl` writes under
`artifacts/paper/raw/`.) Each run ends by checking that every row of the declared
grid (circuits x widths x topologies x seeds x arms) is present and succeeded;
re-running a config on a complete file runs nothing and repeats that check.

`make figures` regenerates every data figure in the paper into `paper/figures/`
from the tracked rows under `artifacts/paper/raw/` (`git diff` shows any change):

- `scripts/paper/export_core.py`, `export_scaling.py`, `export_device.py`: the
  core comparison (aggregate and per-workload figures), scaling, and hardware
  projection, each with 95% bootstrap intervals over seeds.
- `src/notebooks/paper/03_completions.ipynb`: the unitary-completion figure.
- `scripts/paper/emit_strategy_ladder.py`: the strategy-ladder circuits (Fig. 8);
  asserts the printed SWAP and depth counts.

## Evaluation and expected results

- `pytest tests` passes (~300 tests, under a minute).
- The completions notebook runs top-to-bottom; check cells assert the paper's numbers
  inline (exact given the recorded raw rows): SWAP reduction 26.0-31.3% and
  depth reduction 7.9-12.4% across topologies (core, n=8); postselection
  shot overhead reduction 28.8-34.2% and conditional infidelity reduction
  7.6-8.6% (hardware projection, n=16); the 7/6, 5/5, 4/3 strategy-ladder
  counts in the demo. A full rerun of the experiments (new circuit
  population) may shift the aggregates by well under a percent.

## Experiment customization

The TOML files under `configs/paper/` define the experiment grids (benchmarks,
topologies, seeds, arms, search budget). `build_pm(...)` exposes the
compiler strategies directly for new circuits and coupling maps.

## Notes

`crates/src/sabre/` is vendored from Qiskit 2.3.1 (Apache-2.0, per-file
headers retained); `crates/README.md` documents why the fork exists and how
its dependency pins are kept coherent.
