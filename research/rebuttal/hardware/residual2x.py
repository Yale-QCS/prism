"""Section V-D: median retained-shot fidelity (Eq. 18) at n = 16 over three graphs, as measured and with every unflagged gate error doubled.
Usage: .venv/bin/python research/rebuttal/hardware/residual2x.py"""
import json, math, sys
from collections import defaultdict
from pathlib import Path
import numpy as np
REPO = Path(__file__).resolve().parents[3]; WC = REPO / "research/rebuttal/wallclock"
sys.path[:0] = [str(WC), str(REPO / "src"), str(REPO / "research/rebuttal/hardware")]
import sim, validate
from equations import z_counts, EPS
from qiskit import qpy
DEV = sim.MEHTA_IDLE; TOPOS = ("grid", "hex_lattice", "heavy_hex")
files = [p for d in (WC / "data/swaps/circuits_n16", WC / "data/swaps/heavy_hex/circuits_n16") for p in sorted(d.glob("*.qpy"))]
F = {1: defaultdict(lambda: defaultdict(list)), 2: defaultdict(lambda: defaultdict(list))}
for i, p in enumerate(files):
    topo = next(k for k in TOPOS if f"_{k}_" in p.stem); name, rest = p.stem.split(f"_{topo}_"); seed, arm = rest.split("_")
    if arm not in ("greedy", "prism"): continue
    with p.open("rb") as f: qc = qpy.load(f)[0]
    _, _, I, _ = validate.loss_parts(qc, DEV); z = z_counts(qc)
    for k in (1, 2): F[k][arm][name].append(math.exp(-DEV.dephasing * I + sum(z[g] * math.log1p(-k * EPS[g]) for g in EPS)))
    if (i + 1) % 80 == 0 or i + 1 == len(files): print(f"{i+1}/{len(files)}", flush=True)
for k in (1, 2):
    print(k, {a: round(float(np.median([np.mean(v) for v in F[k][a].values()])), 3) for a in ("greedy", "prism")})
