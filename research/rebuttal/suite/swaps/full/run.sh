#!/bin/bash
# Full-suite §5.3 runs, 2026-10-11 night: front-commit ablation, then duration- and depth-selected routes.
# Starts after scale_swaps and the heavy-hex front-commit job finish. Run from the repository root.
D=research/rebuttal/suite/swaps/full
while pgrep -f "scale_swaps.toml|front_commit_swaps_heavyhex.toml" >/dev/null; do sleep 60; done
for f in core_front_commit breadth_front_commit breadth_added_front_commit randomcircuit_front_commit \
         core_duration breadth_duration breadth_added_duration randomcircuit_duration \
         core_depth breadth_depth breadth_added_depth randomcircuit_depth; do
  echo "=== $f start $(date +%T)"
  .venv/bin/python scripts/paper/run_fairness.py --config $D/$f.toml --workers 6 --out $f.jsonl
done
echo "=== all done $(date +%T)"
