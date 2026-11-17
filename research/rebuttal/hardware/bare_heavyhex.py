"""Heavy-hex transmon compiles: bare._cell for topology heavy_hex (bare.py runs grid and hex only). Same model and K.
Usage: .venv/bin/python research/rebuttal/hardware/bare_heavyhex.py <width> research/rebuttal/wallclock/data/swaps/heavy_hex/bare_n<width>.jsonl <workers>"""
import json, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "wallclock"))
import bare, run  # noqa: E402

def main():
    width, out, workers = int(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
    circuits = [c for c in run.CFG["circuits"] if (bare.REPO / f"artifacts/paper/manifests/circuits/{c}_n{width}.qpy").exists()]
    tasks = [(c, width, "heavy_hex", s, bare.K) for c in circuits for s in (0, 100, 200, 300, 400)]
    total = len(tasks)
    with out.open("w") as f, ProcessPoolExecutor(workers) as pool:
        for i, rows in enumerate(pool.map(bare._cell, tasks), 1):
            for row in rows:
                f.write(json.dumps(row) + "\n")
            f.flush()
            print(f"{i}/{total} {rows[0]['circuit']} heavy_hex {rows[0]['seed']}", flush=True)

if __name__ == "__main__":
    main()
