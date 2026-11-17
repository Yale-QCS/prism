#!/bin/bash
# 2026-10-11 night: the first scale_swaps runner has a 10 h timeout (23:20) that lands before multiplier is done.
# Wait for its in-flight rg_qft_multiplier n=28 hex tasks (row 2080), then restart it without a timeout at 11 workers
# (the full-suite queue was cancelled and the dephasing sweep is done). run_fairness resumes by run_id.
D=research/rebuttal/suite/swaps
while [ $(wc -l < artifacts/paper/raw/scale_swaps.jsonl) -lt 2080 ] && pgrep -f "scale_swaps.toml --workers 5" >/dev/null; do sleep 30; done
pkill -f "scale_swaps.toml --workers 5"; sleep 5
echo "=== scale resume at 11 workers $(date +%T), $(wc -l < artifacts/paper/raw/scale_swaps.jsonl) rows" >> $D/run_scale.log
.venv/bin/python scripts/paper/run_fairness.py --config $D/scale_swaps.toml --workers 11 --out scale_swaps.jsonl >> $D/run_scale.log 2>&1
echo "=== scale done $(date +%T)" >> $D/run_scale.log
