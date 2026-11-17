#!/bin/bash
# Greedy with greedy_prep_sites on (scratch overlay of the proposed patch), 4 at a time, 2G each.
R=.; D=/home/evm9/prism/scratch/r3.1-compiler
OUT=$D/probe_prepsites.jsonl; : > $OUT
TOTAL=$(wc -l < $D/tasks_greedy.txt)
export R D OUT TOTAL PROBE_TREE=$D/proposed/tree GREEDY_PREP_SITES=1
xargs -P 4 -L 1 bash -c 'systemd-run --user --scope -q -p MemoryMax=2G -p MemorySwapMax=0 $R/.venv/bin/python $D/prep_probe.py "$@" 2>>$D/probe3.err >> $OUT || echo "FAIL $*" >> $D/probe3.err; echo "$(wc -l < $OUT)/$TOTAL"' _ < $D/tasks_greedy.txt
