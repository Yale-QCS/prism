# Evaluation pipeline

The evaluation pipeline. Everything a paper number depends on runs from here, noninteractively.

Order: raw result rows -> exports -> figures and numbers in the prose.
The manuscript never recomputes a headline number.

`run_fairness.py` produces the three runs from `configs/paper/`: `core` (the
controlled comparison), `logical` (the Logical-SABRE arm) and `scale` (n = 8
to 32), each into `artifacts/paper/raw/<experiment_id>.jsonl`. Each run ends by
checking that every declared row is present and succeeded. The exporters turn
the raw rows into `artifacts/paper/paper_export/`: `export_core.py` (`core/`),
`export_scaling.py` (`scaling/`), and `export_device.py` (`device/`), which
uses the device model in `marabbecca.utils.metrics.device_success`:

```
.venv/bin/python scripts/paper/export_device.py
```

The arms are `logical`, `greedy`, `prism` and the `prism_front_commit`
ablation; rows record the arm as `strategy`.

`emit_strategy_ladder.py` writes the Fig. 7 circuit.
The remaining modules are libraries that the tests import.

Two `run_fairness.py` config keys postdate the submission and default to false,
which reproduces it. `commute_diagonal = true` lets commuting CRZ/RZ gates leave
program order in the routing dependency graph (arms on the PRISM kernel only).
`reschedule = true` re-emits each arm's final circuit by critical-path order over
the same relaxed dependencies. Rows record both values.


## Environment

Audited stack: Python 3.12.3, Qiskit 2.4.1, MQT Bench 2.2.2, rustc/cargo 1.97.1.
The submitted rows were built with rustc 1.89.0; the extension built with 1.89.0
and 1.97.1 gives byte-identical outputs on 216 same-seed compile cells.

Install (requires Rust 1.97 on PATH; the Rust extension builds via setuptools-rust during pip install):

```
pip install -e '.[test,eval]'
```

For eval-only environments (no dev tools):

```
pip install -e '.[eval]'
```

The uv.lock in the repo root pins the full transitive closure; to verify the lock is consistent with the installed environment run `uv lock --locked`.
