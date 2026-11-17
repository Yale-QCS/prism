"""baseline-check Q1 (p3_matchings.py) at the 40/16/40 quotient budget: same devices, workloads, seeds and match seeds."""
import os as _os
HERE = _os.path.dirname(_os.path.abspath(__file__)) + "/"
ROOT = _os.path.abspath(_os.path.join(HERE, "../../../..")) + "/"
import sys, json
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, HERE)
import lsabre_probe as L
import run_fairness
from p3_matchings import MQT, SEEDS

_orig = run_fairness._run_one
BUDGET = {"layout_starts": 40, "refinement_iterations": 16, "prism_swap_trials": 40}
run_fairness._run_one = lambda spec, *a, **k: _orig({**spec, **BUDGET}, *a, **k)
# the 12 matchings p3_matchings.py picked (p3_out_<topo>.txt): default (None) plus 11 alternatives
PICKS = {"grid": [None, 100, 0, 1, 2, 3, 4, 5, 6, 9, 10, 11],
         "heavy_hex": [None, 1, 0, 3, 4, 5, 7, 8, 10, 11, 25, 29]}
OUT = HERE + "p3_matchings_budget.jsonl"

if __name__ == "__main__":
    tasks = [(c, 8, topo, s, ms) for topo, picks in PICKS.items() for ms in picks for c in MQT for s in SEEDS]
    with open(OUT, "w") as f, ProcessPoolExecutor(4) as ex:
        for i, row in enumerate(ex.map(L._task, tasks, chunksize=4), 1):
            f.write(json.dumps(row) + "\n"); f.flush()
            print(f"{i}/{len(tasks)}", flush=True)
