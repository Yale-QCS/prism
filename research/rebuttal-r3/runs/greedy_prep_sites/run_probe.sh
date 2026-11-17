#!/bin/bash
# Re-run a sample of published cells through prep_probe.py, 4 at a time, 2G each.
R=.; S=$R/research/rebuttal/suite/swaps; D=/home/evm9/prism/scratch/r3.1-compiler
OUT=${OUT:-$D/probe.jsonl}; : > $OUT; : > $D/tasks.txt
for c in qaoa qft hhl multiplier cdkm_ripple_carry_adder ae; do for t in grid hex_lattice heavy_hex; do for s in 0 100 200 300 400; do for a in greedy prism; do
  echo "$S/core_swaps.toml $c 8 $t $s $a" >> $D/tasks.txt; done; done; done; done
for cw in "multiply 13" "qram 20"; do for t in grid hex_lattice heavy_hex; do for s in 0 100 200 300 400; do for a in greedy prism; do
  echo "$S/breadth_swaps.toml $cw $t $s $a" >> $D/tasks.txt; done; done; done; done
TOTAL=$(wc -l < $D/tasks.txt)
export R D OUT TOTAL
xargs -P 4 -L 1 bash -c 'systemd-run --user --scope -q -p MemoryMax=2G -p MemorySwapMax=0 $R/.venv/bin/python $D/prep_probe.py "$@" 2>>$D/probe.err >> $OUT || echo "FAIL $*" >> $D/probe.err; echo "$(wc -l < $OUT)/$TOTAL"' _ < $D/tasks.txt
