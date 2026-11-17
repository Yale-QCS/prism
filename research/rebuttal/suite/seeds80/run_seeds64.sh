#!/bin/bash
# Run from the repository root, 7 workers. The 2026-10-11 completion of the 64-seed suite (README.md):
# Logical-SABRE at the 44 added seeds on the 24 workloads, Logical-SABRE on randomcircuit at all 64 seeds,
# and Greedy/PRISM at the 44 added seeds for qec9xz, qram and knn. Progress lines are rows/total.
D=research/rebuttal/suite/seeds80
run() {  # config total out
  echo "=== $1 -> artifacts/paper/raw/$3 ($2 rows) $(date -u +%FT%TZ)"
  .venv/bin/python scripts/paper/run_fairness.py --config $D/$1.toml --workers 7 --out $3 2>&1 | sed -u "s|^\[\([0-9]*\)\]|\1/$2|"
}
run logical_seeds64 3168 logical_seeds64.jsonl        # exits 1: the 44 knn/heavy-hex rows fail as not placeable
run logical_randomcircuit 192 logical_randomcircuit.jsonl
run breadth_rest_seeds64 792 breadth_rest_seeds64.jsonl
echo "=== done $(date -u +%FT%TZ)"
# Added 2026-10-11 after launch: Greedy/PRISM on randomcircuit at the 44 added seeds (run by run_seeds64_random.sh after this script).
