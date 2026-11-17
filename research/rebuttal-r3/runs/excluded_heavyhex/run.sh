#!/bin/bash
# Heavy-hex completion of excluded_swaps (revision 3). Run from the repository root; resumable (rows already in the .jsonl are skipped).
# 5 workers inside one 5 GB memory scope.
set -e
D=research/rebuttal-r3/runs/excluded_heavyhex
systemd-run --user --scope -q -p MemoryMax=5G -p MemorySwapMax=0 \
  .venv/bin/python scripts/paper/run_fairness.py --config $D/excluded_swaps_heavyhex.toml --workers 5 --out "$PWD/$D/excluded_swaps_heavyhex.jsonl" 2>> $D/run.err
