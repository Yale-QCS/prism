#!/bin/bash
# Run from the repository root after run_seeds64.sh: Greedy/PRISM on randomcircuit at the 44 added seeds, 4 workers.
D=research/rebuttal/suite/seeds80
while pgrep -f run_seeds64.sh >/dev/null; do sleep 30; done
echo "=== randomcircuit_seeds64 -> artifacts/paper/raw/randomcircuit_seeds64.jsonl (264 rows) $(date -u +%FT%TZ)"
.venv/bin/python scripts/paper/run_fairness.py --config $D/randomcircuit_seeds64.toml --workers 4 --out randomcircuit_seeds64.jsonl 2>&1 | sed -u "s|^\[\([0-9]*\)\]|\1/264|"
echo "=== done $(date -u +%FT%TZ)"
