#!/bin/bash
# Resumable sweep over 2 bases x 2 arms x 20 seeds. Usage: run.sh NOISE SHOTS PROTOCOL [PROTOCOL ...]
# NOISE skipgate runs skipgate.py (rows_skipgate/). Runs six workers inside one memory-capped scope and prints i/total after each cell.
set -u
here=$(cd "$(dirname "$0")" && pwd)
python=${QEC_PYTHON:-/home/evm9/prism/dev/steane-venv/bin/python}
export OPENBLAS_NUM_THREADS=1 RAYON_NUM_THREADS=1 QISKIT_PARALLEL=FALSE PYTHONWARNINGS=ignore
noise=$1; shots=$2; shift 2
script=flag_memory.py; extra="--noise $noise"
[ "$noise" = skipgate ] && script=skipgate.py && extra=
rows=$here/rows_$noise; mkdir -p "$rows"
tasks=(); total=0
for protocol in "$@"; do for basis in X Z; do for arm in greedy prism; do for seed in $(seq 0 100 1900); do
  total=$((total + 1))
  [ -e "$rows/${protocol}_${basis}_${arm}_${seed}.json" ] || tasks+=("$protocol $basis $arm $seed")
done; done; done; done
echo "$((total - ${#tasks[@]}))/$total"
[ ${#tasks[@]} -eq 0 ] && exit 0
protocols="$*"
export python here noise shots total script extra protocols
printf '%s\n' "${tasks[@]}" | systemd-run --user --scope -q -p MemoryMax=8G -p MemorySwapMax=0 \
  xargs -P 6 -L 1 sh -c '"$python" "$here/$script" "$@" $extra --shots "$shots" || echo "FAILED $*"; n=0; for p in $protocols; do n=$((n + $(ls "$here/rows_$noise/${p}"_*.json 2>/dev/null | wc -l))); done; echo "$n/$total"' _ 2>&1
