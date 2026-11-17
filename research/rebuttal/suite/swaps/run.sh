#!/bin/bash
# SWAP-selected re-run, 2026-10-11. Run from the repository root. Suite at 7 workers, scale at 5 in parallel, ablations after the suite.
set -e
D=research/rebuttal/suite/swaps
(timeout 36000 .venv/bin/python scripts/paper/run_fairness.py --config $D/scale_swaps.toml --workers 5 --out scale_swaps.jsonl >> $D/run_scale.log 2>&1) &
for f in core_swaps randomcircuit_swaps breadth_added_swaps breadth_swaps front_commit_swaps tiebreak_swaps slack_swaps excluded_swaps; do
  timeout 36000 .venv/bin/python scripts/paper/run_fairness.py --config $D/$f.toml --workers 7 --out $f.jsonl >> $D/run.log 2>&1
done
wait
echo "=== all done $(date -u +%FT%TZ)" >> $D/run.log
