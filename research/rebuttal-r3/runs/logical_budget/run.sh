#!/bin/bash
# Logical-SABRE at Greedy/PRISM's search budget (40/16/40). Run from the repository root; resumable (run_fairness skips
# run_ids already in the output). Rows go next to the configs. The qasmbench and seeds64 runs end with
# "N of M declared rows missing or failed": those are the knn heavy-hex cells, which no matching can place (as in the
# submitted rows), so a nonzero exit does not stop the script.
D=research/rebuttal-r3/runs/logical_budget
export RAYON_NUM_THREADS=1
for c in logical_budget logical_qasmbench_budget logical_added_budget logical_randomcircuit_budget logical_seeds64_budget; do
  timeout 14400 .venv/bin/python scripts/paper/run_fairness.py --config $D/$c.toml --workers 5 --out "$PWD/$D/$c.jsonl" \
    || echo "=== $c exited $?"
done
echo "=== all done $(date -u +%FT%TZ)"
