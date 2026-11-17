#!/bin/bash
# Fig. 11a front-commit ablation, isolated (revision 3). Run from the repository root; resumable (re-running skips rows already in the .jsonl).
# Each config runs at 5 workers inside one 5 GB memory scope.
set -e
D=research/rebuttal-r3/runs/front_commit_isolated
for f in front_commit_swaps_isolated front_commit_swaps_heavyhex_isolated; do
  systemd-run --user --scope -q -p MemoryMax=5G -p MemorySwapMax=0 \
    .venv/bin/python scripts/paper/run_fairness.py --config $D/$f.toml --workers 5 --out "$PWD/$D/$f.jsonl" 2>> $D/run.err
done
