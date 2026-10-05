"""Multi-round syndrome extraction with ancilla reuse: pinned (measure+reset in place) vs
floating (each reset re-hosts the ancilla on a fresh logical qubit, i.e. free rail choice)."""

from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).absolute().parents[3] / "src"))
sys.path.insert(0, str(Path(__file__).absolute().parents[3] / "scripts"))
sys.path.insert(0, str(Path(__file__).absolute().parent))
warnings.filterwarnings("ignore")

from qiskit import QuantumCircuit  # noqa: E402

from qec_quick import compile_one  # noqa: E402
from qec_quick import make_topologies  # noqa: E402


def _surface_plaquettes(r: int, c: int):
    plaq = []
    for i in range(-1, r):
        for j in range(-1, c):
            kind = "Z" if (i + j) % 2 == 0 else "X"
            interior = 0 <= i <= r - 2 and 0 <= j <= c - 2
            top_bot = (i in (-1, r - 1)) and 0 <= j <= c - 2 and kind == "X"
            left_right = (j in (-1, c - 1)) and 0 <= i <= r - 2 and kind == "Z"
            if interior or top_bot or left_right:
                plaq.append((kind, (i, j)))
    assert len(plaq) == r * c - 1
    return plaq


def surface_rounds(d: int, rounds: int) -> QuantumCircuit:
    """``rounds`` rounds of rotated surface d x d, ancillas measured and reset in place."""
    data = {(i, j): i * d + j for i in range(d) for j in range(d)}
    plaq = _surface_plaquettes(d, d)
    anc = {p: d * d + k for k, p in enumerate(plaq)}
    qc = QuantumCircuit(d * d + len(plaq), rounds * len(plaq))
    order = {"X": [(0, 0), (0, 1), (1, 0), (1, 1)], "Z": [(0, 0), (1, 0), (0, 1), (1, 1)]}
    for rnd in range(rounds):
        for kind, p in plaq:
            if kind == "X":
                qc.h(anc[(kind, p)])
        for step in range(4):
            for kind, (i, j) in plaq:
                di, dj = order[kind][step]
                q = data.get((i + di, j + dj))
                if q is None:
                    continue
                a = anc[(kind, (i, j))]
                qc.cx(a, q) if kind == "X" else qc.cx(q, a)
        for kind, p in plaq:
            if kind == "X":
                qc.h(anc[(kind, p)])
        for k, p in enumerate(plaq):
            qc.measure(anc[p], rnd * len(plaq) + k)
            if rnd < rounds - 1:
                qc.reset(anc[p])
    return qc


def bb_rounds(rounds: int) -> QuantumCircuit:
    """``rounds`` rounds of the [[18,4,4]] BB code, one reused ancilla per check."""
    import numpy as np

    l = m = 3

    def shift(n, k):
        return np.roll(np.eye(n, dtype=int), k, axis=1)

    def mat(terms):
        M = np.zeros((l * m, l * m), dtype=int)
        for i, j in terms:
            M = (M + np.kron(shift(l, i), shift(m, j))) % 2
        return M

    A, B = mat([(0, 0), (0, 1), (1, 0)]), mat([(0, 0), (0, 1), (2, 1)])
    Hx, Hz = np.hstack([A, B]), np.hstack([B.T, A.T])
    checks = [("X", list(np.flatnonzero(row))) for row in Hx] + [("Z", list(np.flatnonzero(row))) for row in Hz]
    qc = QuantumCircuit(18 + len(checks), rounds * len(checks))
    for rnd in range(rounds):
        for k, (kind, supp) in enumerate(checks):
            a = 18 + k
            if kind == "X":
                qc.h(a)
            for q in supp:
                qc.cx(a, q) if kind == "X" else qc.cx(q, a)
            if kind == "X":
                qc.h(a)
            qc.measure(a, rnd * len(checks) + k)
            if rnd < rounds - 1:
                qc.reset(a)
    return qc


def floating(qc: QuantumCircuit) -> QuantumCircuit:
    """Drop every reset and rename the qubit's later uses to a fresh qubit (free re-hosting)."""
    cur = list(range(qc.num_qubits))
    nxt = qc.num_qubits
    ops = []
    for ins in qc.data:
        idx = [qc.find_bit(q).index for q in ins.qubits]
        if ins.operation.name == "reset":
            cur[idx[0]] = nxt
            nxt += 1
            continue
        ops.append((ins.operation, [cur[i] for i in idx], [qc.find_bit(c).index for c in ins.clbits]))
    out = QuantumCircuit(nxt, qc.num_clbits)
    for op, qs, cs in ops:
        out.append(op, qs, cs)
    return out


def lattice_surgery(d: int = 3) -> QuantumCircuit:
    """Separate round on two d x d patches, one merged (d x 2d+1) round, separate round again.

    Ancilla identity is keyed by absolute plaquette corner, so checks shared between the
    separate and merged codes reuse their ancilla (measure + reset); seam-only checks get
    their own. Seam data qubits exist from t=0 and are measured out at the end.
    """
    cols = 2 * d + 1
    data = {(i, j): i * cols + j for i in range(d) for j in range(cols)}
    sep = [(k, (i, j)) for k, (i, j) in _surface_plaquettes(d, d)] + [
        (k, (i, j + d + 1)) for k, (i, j) in _surface_plaquettes(d, d)
    ]
    merged = _surface_plaquettes(d, cols)
    keys = list(dict.fromkeys(sep + merged))
    anc = {p: len(data) + k for k, p in enumerate(keys)}
    stages = [sep, merged, sep]
    n_meas = sum(len(st) for st in stages) + d
    qc = QuantumCircuit(len(data) + len(keys), n_meas)
    order = {"X": [(0, 0), (0, 1), (1, 0), (1, 1)], "Z": [(0, 0), (1, 0), (0, 1), (1, 1)]}
    cbit = 0
    for s_idx, plaq in enumerate(stages):
        for kind, p in plaq:
            if kind == "X":
                qc.h(anc[(kind, p)])
        for step in range(4):
            for kind, (i, j) in plaq:
                di, dj = order[kind][step]
                q = data.get((i + di, j + dj))
                if q is None:
                    continue
                a = anc[(kind, (i, j))]
                qc.cx(a, q) if kind == "X" else qc.cx(q, a)
        for kind, p in plaq:
            if kind == "X":
                qc.h(anc[(kind, p)])
        later = set().union(*stages[s_idx + 1 :]) if s_idx + 1 < len(stages) else set()
        for p in plaq:
            qc.measure(anc[p], cbit)
            cbit += 1
            if p in later:
                qc.reset(anc[p])
    for i in range(d):  # measure out the seam column
        qc.measure(data[(i, d)], cbit)
        cbit += 1
    return qc


CIRCUITS = {
    "ls_split_merge": lambda: lattice_surgery(3),
    "surface_d3_r3": lambda: surface_rounds(3, 3),
    "bb_18_4_4_r3": lambda: bb_rounds(3),
}


def main() -> None:
    names = sys.argv[1].split(",") if len(sys.argv) > 1 else list(CIRCUITS)
    topos = sys.argv[2].split(",") if len(sys.argv) > 2 else ["hex_lattice", "grid", "heavy_hex"]
    seeds = [int(s) for s in sys.argv[3].split(",")] if len(sys.argv) > 3 else [0, 1]
    budget = int(sys.argv[4]) if len(sys.argv) > 4 else 8
    arms = sys.argv[5].split(",") if len(sys.argv) > 5 else ["prism"]
    local_init = len(sys.argv) > 6 and sys.argv[6] == "local"
    if local_init:
        from prism.encodings import DualRail

        DualRail.local_init = True
    out_path = Path(__file__).absolute().parents[3] / Path("research/data/qec/rounds.jsonl")
    print(f"local_init={local_init}")
    print(f"{'circuit':14} {'variant':8} {'n':>3} {'topo':11} {'arm':8} {'seed':>4} {'swaps':>5} {'depth':>5} {'dur_us':>7} {'sec':>6}", flush=True)
    for name in names:
        pinned = CIRCUITS[name]()
        variants = {"pinned": pinned, "floating": floating(pinned)}
        n_topo = variants["floating"].num_qubits  # same physical lattice for both variants
        for topo in topos:
            cmap = make_topologies(n_topo)[topo]
            for vname, qc in variants.items():
                for arm in arms:
                    for seed in seeds:
                        try:
                            r = compile_one(arm, qc, cmap, seed, budget)
                        except Exception as e:  # noqa: BLE001
                            print(f"{name:14} {vname:8} {qc.num_qubits:3} {topo:11} {arm:8} {seed:4} FAIL {type(e).__name__}: {str(e)[:120]}", flush=True)
                            continue
                        row = {"circuit": name, "variant": vname, "n_logical": qc.num_qubits, "n_phys": cmap.size(), "topo": topo, "arm": arm, "seed": seed, "budget_scale": budget, "local_init": local_init, **r}
                        with out_path.open("a") as f:
                            f.write(json.dumps(row) + "\n")
                        print(f"{name:14} {vname:8} {qc.num_qubits:3} {topo:11} {arm:8} {seed:4} {r['swaps']:5} {r['depth']:5} {r['duration_us']:7} {r['sec']:6}", flush=True)


if __name__ == "__main__":
    main()
