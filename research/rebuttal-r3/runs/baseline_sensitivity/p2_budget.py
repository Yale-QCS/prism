"""baseline-check §3 probe (lsabre_probe.run over the p2_suite cells, seeds 0..1900) at the 40/16/40 quotient budget."""
import os as _os
HERE = _os.path.dirname(_os.path.abspath(__file__)) + "/"
ROOT = _os.path.abspath(_os.path.join(HERE, "../../../..")) + "/"
import sys, json
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, HERE)
import lsabre_probe as L
import p2_suite
import run_fairness

_orig = run_fairness._run_one
BUDGET = {"layout_starts": 40, "refinement_iterations": 16, "prism_swap_trials": 40}
run_fairness._run_one = lambda spec, *a, **k: _orig({**spec, **BUDGET}, *a, **k)
OUT = HERE + "p2_suite_budget.jsonl"

if __name__ == "__main__":
    try:
        done = {(r["circuit"], r["width"], r["topology"], r["seed"]) for r in map(json.loads, open(OUT))}
    except FileNotFoundError:
        done = set()
    todo = [t for t in p2_suite.tasks if t not in done]
    with open(OUT, "a") as f, ProcessPoolExecutor(5) as ex:
        for i, row in enumerate(ex.map(L._task, todo, chunksize=4), 1):
            f.write(json.dumps(row) + "\n"); f.flush()
            print(f"{i}/{len(todo)}", flush=True)
