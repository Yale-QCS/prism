# R3 trade-off figure at 16 logical qubits

`configs/w16_{swaps,depth,duration,error}.toml` are the core configs at width 16, five seeds each (0 to 400), with route selection by each objective. The rows in `data/` come from the compiler after the rail-X fix (`9cb6c53`). `../commutation/objectives_figure.py --w16` draws `../commutation/figures/objectives_w16.{png,pdf}`.

Run from the repo root: `.venv/bin/python scripts/paper/run_fairness.py --config research/rebuttal/tradeoff/configs/w16_error.toml --workers 9 --out ../../../research/rebuttal/tradeoff/data/w16_error.jsonl` (`--out` is relative to `artifacts/paper/raw/`).
