#!/bin/bash
# Run from the repository root. One job at a time, 10 workers.
set -e
D=research/rebuttal/suite/seeds80
for f in core breadth_added breadth; do
  timeout 36000 .venv/bin/python scripts/paper/run_fairness.py --config $D/$f.toml --workers 10 --out ${f}_seeds80.jsonl
done
