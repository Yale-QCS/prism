"""Exact MEHTA_IDLE re-simulation of the heavy-hex circuits at n = 8 (resim.py runs grid and hex only).
run.py --device mehta simulates on sim.MEHTA, which charges dephasing during gates too. Acceptance is identical,
fidelity is not, so the proxy check uses these rows.
Usage: .venv/bin/python research/rebuttal/hardware/resim_heavyhex.py [workers]"""
import json, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
WC = Path(__file__).resolve().parents[1] / "wallclock"
sys.path.insert(0, str(WC))
import resim  # noqa: E402

def main():
    d = WC / "data/swaps/heavy_hex"; workers = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    keep = ("circuit", "n_logical", "topology", "seed", "arm", "op_counts")
    rows = [json.loads(l) for l in open(d / "v2_n8.jsonl")]
    tasks = [({k: r[k] for k in keep} | {"device": "mehta_idle"}, d / "circuits_n8" / f"{r['circuit']}_heavy_hex_{r['seed']}_{r['arm']}.qpy", None, None) for r in rows]
    with open(d / "v3_n8.jsonl", "w") as f, ProcessPoolExecutor(workers) as pool:
        for i, row in enumerate(pool.map(resim._one, tasks), 1):
            f.write(json.dumps(row) + "\n"); f.flush()
            print(f"{i}/{len(tasks)}", flush=True)

if __name__ == "__main__":
    main()
