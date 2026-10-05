"""Quick QEC routing numbers: rotated surface code and CSS honeycomb on prism topologies."""

from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).absolute().parents[3] / "src"))
sys.path.insert(0, str(Path(__file__).absolute().parents[3] / "scripts"))

from qiskit import QuantumCircuit  # noqa: E402

import math  # noqa: E402

from qiskit.transpiler import CouplingMap  # noqa: E402


def make_topologies(n_logical: int) -> dict[str, CouplingMap]:
    """Paper sizing: 2*(n+1) rails; smallest chain/grid/heavy-hex/hex that holds them."""
    n_phys = 2 * (n_logical + 1)
    rows = math.ceil(math.sqrt(n_phys))
    hh = 3
    while CouplingMap.from_heavy_hex(hh).size() < n_phys:
        hh += 2
    side = math.ceil(math.sqrt(n_phys / 2))
    while CouplingMap.from_hexagonal_lattice(side, side).size() < n_phys:
        side += 1
    return {
        "chain": CouplingMap.from_line(n_phys),
        "grid": CouplingMap.from_grid(rows, math.ceil(n_phys / rows)),
        "heavy_hex": CouplingMap.from_heavy_hex(hh),
        "hex_lattice": CouplingMap.from_hexagonal_lattice(side, side),
    }

warnings.filterwarnings("ignore")


def rotated_surface_code(d: int, cols: int | None = None) -> QuantumCircuit:
    """One syndrome round of a rows x cols rotated surface patch, fresh ancillas, 4-step schedule."""
    r, c = d, cols or d
    data = {(i, j): i * c + j for i in range(r) for j in range(c)}
    plaq = []  # (kind, corner (i,j)) covering data (i..i+1, j..j+1)
    for i in range(-1, r):
        for j in range(-1, c):
            kind = "Z" if (i + j) % 2 == 0 else "X"
            interior = 0 <= i <= r - 2 and 0 <= j <= c - 2
            top_bot = (i in (-1, r - 1)) and 0 <= j <= c - 2 and kind == "X"
            left_right = (j in (-1, c - 1)) and 0 <= i <= r - 2 and kind == "Z"
            if interior or top_bot or left_right:
                plaq.append((kind, (i, j)))
    assert len(plaq) == r * c - 1, len(plaq)
    n_anc = len(plaq)
    qc = QuantumCircuit(r * c + n_anc, n_anc)
    anc = {p: r * c + k for k, p in enumerate(plaq)}
    for kind, p in plaq:
        if kind == "X":
            qc.h(anc[(kind, p)])
    # X checks: NW, NE, SW, SE; Z checks: NW, SW, NE, SE (avoids hook errors).
    order = {"X": [(0, 0), (0, 1), (1, 0), (1, 1)], "Z": [(0, 0), (1, 0), (0, 1), (1, 1)]}
    for step in range(4):
        for kind, (i, j) in plaq:
            di, dj = order[kind][step]
            q = data.get((i + di, j + dj))
            if q is None:
                continue
            a = anc[(kind, (i, j))]
            if kind == "X":
                qc.cx(a, q)
            else:
                qc.cx(q, a)
    for kind, p in plaq:
        if kind == "X":
            qc.h(anc[(kind, p)])
    for k, p in enumerate(plaq):
        qc.measure(anc[p], k)
    return qc


def css_honeycomb(m: int, n: int, rounds: int = 3) -> QuantumCircuit:
    """CSS honeycomb Floquet code (Gu-Retzker-Kubica), ancilla scheme, fresh ancilla per check."""
    import networkx as nx

    G = nx.hexagonal_lattice_graph(m, n)
    nodes = {v: k for k, v in enumerate(sorted(G.nodes()))}
    colors: dict[int, list] = {0: [], 1: [], 2: []}
    for u, v in G.edges():
        (i1, j1), (i2, j2) = u, v
        if i1 == i2:  # vertical edge: colour by lower j parity
            colors[min(j1, j2) % 2].append((nodes[u], nodes[v]))
        else:
            colors[2].append((nodes[u], nodes[v]))
    # Sanity: proper edge colouring.
    for c, es in colors.items():
        seen = set()
        for a, b in es:
            assert a not in seen and b not in seen, c
            seen.update((a, b))
    schedule = [("X", 0), ("Z", 1), ("X", 2), ("Z", 0), ("X", 1), ("Z", 2)][:rounds]
    n_data = len(nodes)
    n_anc = sum(len(colors[c]) for _, c in schedule)
    qc = QuantumCircuit(n_data + n_anc, n_anc)
    k = 0
    for pauli, c in schedule:
        for a, b in colors[c]:
            anc = n_data + k
            if pauli == "X":
                qc.h(a)
                qc.h(b)
            qc.cx(a, anc)
            qc.cx(b, anc)
            if pauli == "X":
                qc.h(a)
                qc.h(b)
            qc.measure(anc, k)
            k += 1
    return qc


def _check_round(qc: QuantumCircuit, checks: list[tuple[str, list[int]]], first_anc: int) -> None:
    """Append one syndrome round: fresh ancilla per (kind, support) check; X checks via H-sandwiched CNOTs."""
    for k, (kind, supp) in enumerate(checks):
        a = first_anc + k
        if kind == "X":
            qc.h(a)
        for q in supp:
            qc.cx(a, q) if kind == "X" else qc.cx(q, a)
        if kind == "X":
            qc.h(a)
        qc.measure(a, qc.num_clbits - len(checks) + k)


def bb_18_4_4() -> QuantumCircuit:
    """One syndrome round of the [[18,4,4]] bivariate bicycle code (l=m=3, A=1+x+y, B=1+y+x^2y)."""
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
    qc = QuantumCircuit(18 + len(checks), len(checks))
    _check_round(qc, checks, 18)
    return qc


def steane_cnot() -> QuantumCircuit:
    """Two Steane [[7,1,3]] encoders, transversal logical CNOT, one syndrome round per block."""
    H = [[0, 2, 4, 6], [1, 2, 5, 6], [3, 4, 5, 6]]
    checks = [(k, [b + q for q in row]) for b in (0, 7) for k in ("X", "Z") for row in H]
    qc = QuantumCircuit(14 + len(checks), len(checks))
    for b in (0, 7):
        for q in (4, 5, 6):
            qc.h(b + q)
        for ctl, tgt in [(0, 1), (0, 2), (6, 0), (6, 1), (6, 3), (5, 0), (5, 2), (5, 3), (4, 1), (4, 2), (4, 3)]:
            qc.cx(b + ctl, b + tgt)
    for q in range(7):
        qc.cx(q, 7 + q)
    _check_round(qc, checks, 14)
    return qc


CIRCUITS = {
    "bb_18_4_4": bb_18_4_4,
    "steane_cnot": steane_cnot,
    "ls_merge_d3": lambda: rotated_surface_code(3, 7),
    "surface_d3": lambda: rotated_surface_code(3),
    "honeycomb_2x2": lambda: css_honeycomb(2, 2),
    "surface_d5": lambda: rotated_surface_code(5),
}


def compile_one(arm: str, qc, cmap, seed: int, budget_scale: int):
    """Compile with prism (the tool has one policy now; ``arm`` is kept in the row for old logs)."""
    from prism.encodings import DualRail
    from prism.lowering.commit import SearchBudget
    from prism.pipeline import build_pm

    if arm != "prism":
        raise NotImplementedError(f"{arm}: baseline arms live in marabbecca now")
    budget = SearchBudget(
        objective="swaps",
        layout_starts=budget_scale,
        refinement_iterations=max(2, budget_scale // 2),
        swap_trials=budget_scale,
    )
    pm = build_pm(cmap, enc=DualRail, seed=seed, budget=budget)
    t0 = time.time()
    out = pm.run(qc)
    dt = time.time() - t0
    m = pm.property_set["circuit_metrics"]
    ops = out.count_ops()
    return {
        "swaps": m.swaps,
        "router_swaps": pm.property_set.get("online_n_swaps"),
        "rswap": int(ops.get("rswap", 0)),
        "crz": int(ops.get("crz", 0)),
        "depth": m.depth,
        "active": m.active_gates,
        "duration_us": round(m.duration / 1000, 2),
        "sec": round(dt, 1),
    }


def main() -> None:
    names = sys.argv[1].split(",") if len(sys.argv) > 1 else ["surface_d3", "honeycomb_2x2"]
    topos = sys.argv[2].split(",") if len(sys.argv) > 2 else ["hex_lattice", "grid", "heavy_hex", "chain"]
    seeds = [int(s) for s in sys.argv[3].split(",")] if len(sys.argv) > 3 else [0, 1]
    budget_scale = int(sys.argv[4]) if len(sys.argv) > 4 else 8
    arms = ["prism"]
    out_path = Path(__file__).absolute().parents[3] / Path("research/data/qec/quick.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    hdr = f"{'circuit':14} {'n':>3} {'topo':11} {'arm':8} {'seed':>4} {'swaps':>5} {'rtr':>4} {'rswap':>5} {'crz':>4} {'depth':>5} {'dur_us':>7} {'sec':>6}"
    print(hdr, flush=True)
    for name in names:
        qc = CIRCUITS[name]()
        n = qc.num_qubits
        for topo in topos:
            cmap = make_topologies(n)[topo]
            for arm in arms:
                for seed in seeds:
                    try:
                        r = compile_one(arm, qc, cmap, seed, budget_scale)
                    except Exception as e:  # noqa: BLE001
                        print(f"{name:14} {n:3} {topo:11} {arm:8} {seed:4} FAIL {type(e).__name__}: {e}"[:200], flush=True)
                        continue
                    row = {"circuit": name, "n_logical": n, "n_phys": cmap.size(), "topo": topo, "arm": arm, "seed": seed, "budget_scale": budget_scale, **r}
                    with out_path.open("a") as f:
                        f.write(json.dumps(row) + "\n")
                    print(
                        f"{name:14} {n:3} {topo:11} {arm:8} {seed:4} {r['swaps']:5} {str(r['router_swaps']):>4} {r['rswap']:5} {r['crz']:4} {r['depth']:5} {r['duration_us']:7} {r['sec']:6}",
                        flush=True,
                    )


if __name__ == "__main__":
    main()
