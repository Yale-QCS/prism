"""Exact embedding search: does each code's logical interaction graph embed in a direction-class
pair-quotient of the rail topology (rustworkx VF2)? If yes, pin that embedding as the identity
layout and record what greedy/prism do from it."""

from __future__ import annotations

import math
import sys
from pathlib import Path
import time
import warnings

sys.path.insert(0, str(Path(__file__).absolute().parents[3] / "src"))
sys.path.insert(0, str(Path(__file__).absolute().parents[3] / "scripts"))
sys.path.insert(0, str(Path(__file__).absolute().parent))
warnings.filterwarnings("ignore")

import rustworkx as rx  # noqa: E402
from qiskit.transpiler import CouplingMap  # noqa: E402

from qec_quick import CIRCUITS, compile_one  # noqa: E402
from qec_quick import make_topologies  # noqa: E402

SPARE_PAIRS = 1


def interaction_graph(qc) -> rx.PyGraph:
    g = rx.PyGraph()
    g.add_nodes_from(range(qc.num_qubits))
    seen = set()
    for ins in qc.data:
        if ins.operation.num_qubits == 2:
            a, b = (qc.find_bit(q).index for q in ins.qubits)
            e = (min(a, b), max(a, b))
            if e not in seen:
                seen.add(e)
                g.add_edge(a, b, None)
    return g


def pairings(topo: str, n_logical: int, cmap: CouplingMap) -> dict[str, list[tuple[int, int]]]:
    """Direction-class perfect-ish matchings of the rail topology."""
    n_phys = 2 * (n_logical + SPARE_PAIRS)
    edges = {tuple(sorted(e)) for e in cmap.get_edges()}
    out: dict[str, list[tuple[int, int]]] = {}
    if topo == "grid":
        rows = math.ceil(math.sqrt(n_phys))
        cols = math.ceil(n_phys / rows)
        for name, cond in (("h_even", lambda r, c: c % 2 == 0), ("h_odd", lambda r, c: c % 2 == 1)):
            out[name] = [(r * cols + c, r * cols + c + 1) for r in range(rows) for c in range(cols - 1) if cond(r, c)]
        for name, cond in (("v_even", lambda r, c: r % 2 == 0), ("v_odd", lambda r, c: r % 2 == 1)):
            out[name] = [(r * cols + c, (r + 1) * cols + c) for r in range(rows - 1) for c in range(cols) if cond(r, c)]
    elif topo == "hex_lattice":
        side = math.ceil(math.sqrt(n_phys / 2))
        while CouplingMap.from_hexagonal_lattice(side, side).size() < n_phys:
            side += 1
        g = rx.generators.hexagonal_lattice_graph(side, side, with_positions=True)
        assert g.num_nodes() == cmap.size()
        classes: dict[tuple[int, int], list] = {}
        for u, v in g.edge_list():
            (x1, y1), (x2, y2) = g[u], g[v]
            key = (round((x2 - x1) * 10), round(abs(y2 - y1) * 10))
            classes.setdefault(key, []).append((min(u, v), max(u, v)))
        for k, key in enumerate(sorted(classes)):
            out[f"dir{k}"] = classes[key]
    else:
        return {}
    for name, m in list(out.items()):
        assert all(e in edges for e in m), name
        nodes = [x for e in m for x in e]
        assert len(nodes) == len(set(nodes)), name
    return out


def quotient(cmap: CouplingMap, pairs: list[tuple[int, int]]) -> rx.PyGraph:
    p2l = {}
    for i, (a, b) in enumerate(pairs):
        p2l[a] = i
        p2l[b] = i
    q = rx.PyGraph()
    q.add_nodes_from(range(len(pairs)))
    seen = set()
    for u, v in cmap.get_edges():
        lu, lv = p2l.get(u), p2l.get(v)
        if lu is None or lv is None or lu == lv:
            continue
        e = (min(lu, lv), max(lu, lv))
        if e not in seen:
            seen.add(e)
            q.add_edge(lu, lv, None)
    return q


def pinned_cmap(cmap: CouplingMap, pairs, mapping: dict[int, int], n_logical: int) -> CouplingMap:
    """Relabel so logical q's rails are 2q, 2q+1 at the embedded pair."""
    relabel = {}
    for qn, lq in mapping.items():
        a, b = pairs[qn]
        relabel[a] = 2 * lq
        relabel[b] = 2 * lq + 1
    nxt = 2 * n_logical
    for v in range(cmap.size()):
        if v not in relabel:
            relabel[v] = nxt
            nxt += 1
    return CouplingMap([(relabel[u], relabel[v]) for u, v in cmap.get_edges()])


def main() -> None:
    names = sys.argv[1].split(",") if len(sys.argv) > 1 else list(CIRCUITS)
    topos = ["hex_lattice", "grid", "heavy_hex"]
    for name in names:
        qc = CIRCUITS[name]()
        n = qc.num_qubits
        ig = interaction_graph(qc)
        max_deg = max(ig.degree(v) for v in ig.node_indices())
        for topo in topos:
            cmap = make_topologies(n)[topo]
            found = None
            if topo == "heavy_hex":
                # any pairing: quotient degree <= 3 (rail degree <= 3, one edge consumed by the pair)
                print(f"{name:14} {topo:11} interaction max_deg={max_deg}  quotient max_deg<=4 only if pair rails both deg-3; skipping VF2", flush=True)
                continue
            for pname, pairs in pairings(topo, n, cmap).items():
                q = quotient(cmap, pairs)
                qdeg = max(q.degree(v) for v in q.node_indices())
                t0 = time.time()
                m = rx.vf2_mapping(q, ig, subgraph=True, induced=False, call_limit=20_000_000)
                mapping = next(iter(m), None)
                dt = time.time() - t0
                print(f"{name:14} {topo:11} pairing={pname:7} |Q|={q.num_nodes():3} qdeg={qdeg} ig_deg={max_deg} embeds={'yes' if mapping else 'no ':3} ({dt:.1f}s)", flush=True)
                if mapping and not found:
                    found = (pname, pairs, dict(mapping))
            if found:
                pname, pairs, mapping = found
                pc = pinned_cmap(cmap, pairs, mapping, n)
                for arm in ("prism",):
                    r = compile_one(arm, qc, pc, 0, 8)
                    print(f"  pinned[{pname}] {arm:6} swaps={r['swaps']:3} depth={r['depth']:3} dur={r['duration_us']}us", flush=True)


if __name__ == "__main__":
    main()
