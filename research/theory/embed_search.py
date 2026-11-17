"""Exact search: does interaction graph H embed into a 2-split quotient of hardware graph G?

A placement assigns 2 tokens (rails) per logical vertex to distinct sites of G.
H embeds iff every H-edge has some token-pair adjacent in G. Backtracking with
most-constrained-first ordering and neighbor-coverage pruning; per-instance
time limit. Bare-qubit comparison = same search with 1 token per vertex
(subgraph isomorphism into G).
"""

from __future__ import annotations

import itertools
import random
import time

import networkx as nx


def embeds(
    H: nx.Graph,
    G: nx.Graph,
    tokens_per_vertex: int = 2,
    time_limit: float = 60.0,
    selfloops: set | None = None,
):
    """Return a placement dict {h_vertex: tuple(sites)} or None. Raises TimeoutError.

    ``selfloops``: vertices whose own tokens must also be G-adjacent
    (co-location demand: non-diagonal 1Q gates / erasure checks).
    """
    sites = list(G.nodes())
    adj = {s: set(G.neighbors(s)) for s in sites}
    selfloops = selfloops or set()
    order = sorted(H.nodes(), key=lambda v: H.degree(v), reverse=True)
    placement: dict = {}
    used: set = set()
    deadline = time.monotonic() + time_limit

    def consistent(v, toks):
        if v in selfloops and len(toks) == 2 and toks[1] not in adj[toks[0]]:
            return False
        for u in H.neighbors(v):
            if u in placement:
                if not any(t in adj[s] for t in toks for s in placement[u]):
                    return False
        return True

    def candidates(v):
        placed_nbrs = [u for u in H.neighbors(v) if u in placement]
        free = [s for s in sites if s not in used]
        if placed_nbrs:
            # At least one token must sit adjacent to the first placed neighbor.
            u0 = placed_nbrs[0]
            near = {t for s in placement[u0] for t in adj[s] if t not in used}
            for t1 in near:
                for t2 in free:
                    if t2 == t1 or (tokens_per_vertex == 2 and t2 < t1 and t2 in near):
                        continue  # skip dup unordered pairs where both in near
                    yield (t1, t2) if tokens_per_vertex == 2 else (t1,)
                if tokens_per_vertex == 1:
                    yield (t1,)
                    return
        else:
            it = (
                itertools.combinations(free, 2)
                if tokens_per_vertex == 2
                else ((s,) for s in free)
            )
            yield from it

    def bt(i):
        if time.monotonic() > deadline:
            raise TimeoutError
        if i == len(order):
            return True
        v = order[i]
        seen = set()
        for toks in candidates(v):
            key = tuple(sorted(toks))
            if key in seen or len(set(toks)) != len(toks):
                continue
            seen.add(key)
            if not consistent(v, key):
                continue
            placement[v] = key
            used.update(key)
            if bt(i + 1):
                return True
            used.difference_update(key)
            placement.pop(v)
        return False

    try:
        return dict(placement) if bt(0) else None
    except TimeoutError:
        raise


def greedy_partial_fraction(H: nx.Graph, G: nx.Graph, restarts: int = 200, seed: int = 0):
    """Greedy partial embedding: best fraction of H-edges realized over random restarts."""
    rng = random.Random(seed)
    sites = list(G.nodes())
    adj = {s: set(G.neighbors(s)) for s in sites}
    best = 0.0
    m = H.number_of_edges()
    for _ in range(restarts):
        verts = list(H.nodes())
        rng.shuffle(verts)
        placement, used = {}, set()
        for v in verts:
            free = [s for s in sites if s not in used]
            scored = []
            for toks in itertools.combinations(free, 2):
                c = sum(
                    1
                    for u in H.neighbors(v)
                    if u in placement
                    and any(t in adj[s] for t in toks for s in placement[u])
                )
                scored.append((c, rng.random(), toks))
            _, _, toks = max(scored)
            placement[v] = toks
            used.update(toks)
        realized = sum(
            1
            for a, b in H.edges()
            if any(t in adj[s] for t in placement[a] for s in placement[b])
        )
        best = max(best, realized / m)
        if best == 1.0:
            break
    return best


def line(n):
    return nx.path_graph(n)


def grid(r, c):
    return nx.convert_node_labels_to_integers(nx.grid_2d_graph(r, c))


def report(name, H, G, tpv=2, tl=60.0):
    t0 = time.monotonic()
    try:
        res = embeds(H, G, tokens_per_vertex=tpv, time_limit=tl)
        dt = time.monotonic() - t0
        tag = "YES" if res else "no"
        print(f"  {name:42s} {tag:8s} ({dt:5.1f}s)")
        return res is not None
    except TimeoutError:
        print(f"  {name:42s} TIMEOUT  ({tl:5.1f}s)")
        return None


if __name__ == "__main__":
    print("== K_n complete graphs, 2-split (dual-rail), tight hardware (2n sites) ==")
    report("K_4 on line(8)  [the hand construction]", nx.complete_graph(4), line(8))
    report("K_5 on line(10) [counting says no]", nx.complete_graph(5), line(10))
    report("K_5 on ladder 2x5", nx.complete_graph(5), grid(2, 5))
    report("K_5 on grid 3x4 (2 spare)", nx.complete_graph(5), grid(3, 4))
    report("K_6 on ladder 2x6", nx.complete_graph(6), grid(2, 6))
    report("K_6 on grid 3x4", nx.complete_graph(6), grid(3, 4))
    report("K_6 on grid 4x4 (4 spare)", nx.complete_graph(6), grid(4, 4), tl=120)
    report("K_7 on grid 4x4 (2 spare)", nx.complete_graph(7), grid(4, 4), tl=120)
    report("K_8 on grid 4x4", nx.complete_graph(8), grid(4, 4), tl=300)
    report("K_8 on grid 4x5 (4 spare)", nx.complete_graph(8), grid(4, 5), tl=300)

    print("\n== bare-qubit comparison: subgraph embedding (1 token), same hardware ==")
    report("K_4 on line(8), bare", nx.complete_graph(4), line(8), tpv=1)
    report("K_4 on grid 3x4, bare", nx.complete_graph(4), grid(3, 4), tpv=1)
    report("K_5 on grid 4x5, bare", nx.complete_graph(5), grid(4, 5), tpv=1)

    print("\n== random 3-regular H (QAOA MaxCut), n qubits on 2n-site grid ==")
    for n, gshape in [(8, (4, 4)), (10, (4, 5)), (12, (4, 6))]:
        G = grid(*gshape)
        yes = no = tout = 0
        bare_yes = 0
        planar_ct = 0
        for s in range(20):
            H = nx.random_regular_graph(3, n, seed=s)
            planar_ct += nx.check_planarity(H)[0]
            try:
                r = embeds(H, G, time_limit=30.0)
                yes += r is not None
                no += r is None
            except TimeoutError:
                tout += 1
            try:
                rb = embeds(H, G, tokens_per_vertex=1, time_limit=30.0)
                bare_yes += rb is not None
            except TimeoutError:
                pass
        print(
            f"  n={n:2d} grid{gshape}: 2-split {yes}/20 embed ({no} no, {tout} t/o); "
            f"bare subgraph {bare_yes}/20; planar H {planar_ct}/20"
        )

    print("\n== greedy partial fraction (anytime), K_8 on 4x5 ==")
    f = greedy_partial_fraction(nx.complete_graph(8), grid(4, 5), restarts=100)
    print(f"  K_8 on grid 4x5 greedy partial: {f:.2f} of edges realized")
