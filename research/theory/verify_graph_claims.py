"""Verify the S3.3 graph-theory claims the paper asserts but does not exhibit
(audit T1.4): the K_6 witness on a 2x6 grid, the quotient degree bound deg_Q<=2*Delta
and its saturation at separation 3, and the bipartite bare-qubit K_2 ceiling.
"""
import itertools
import networkx as nx


def grid(rows, cols):
    G = nx.Graph()
    for r in range(rows):
        for c in range(cols):
            if c + 1 < cols:
                G.add_edge((r, c), (r, c + 1))
            if r + 1 < rows:
                G.add_edge((r, c), (r + 1, c))
    return G


def perfect_matchings(verts):
    """All partitions of an even-length vertex list into unordered pairs."""
    if not verts:
        yield []
        return
    a = verts[0]
    for i in range(1, len(verts)):
        b = verts[i]
        rest = verts[1:i] + verts[i + 1:]
        for sub in perfect_matchings(rest):
            yield [(a, b)] + sub


def quotient_complete(G, pairing):
    """Is the quotient (contract each pair to a node) the complete graph K_{|pairs|}?"""
    v2l = {}
    for i, (a, b) in enumerate(pairing):
        v2l[a] = i
        v2l[b] = i
    n = len(pairing)
    ladj = set()
    for u, v in G.edges():
        lu, lv = v2l[u], v2l[v]
        if lu != lv:
            ladj.add((min(lu, lv), max(lu, lv)))
    return len(ladj) == n * (n - 1) // 2, ladj


print("=" * 70)
print("CLAIM: a 2x6 grid embeds K_6 (6 logical qubits, all 15 pairs adjacent)")
print("=" * 70)
G = grid(2, 6)
verts = list(G.nodes())
print(f"  2x6 grid: {len(verts)} vertices, {G.number_of_edges()} edges")
found = None
found_adjacent = None
count = 0
for m in perfect_matchings(verts):
    count += 1
    ok, _ = quotient_complete(G, m)
    if ok:
        if found is None:
            found = m
        # does this witness use only grid-adjacent rail pairs (co-locatable)?
        if all(G.has_edge(a, b) for a, b in m):
            found_adjacent = m
            break
print(f"  searched {count} pairings")
print(f"  K_6 witness exists at all      : {found is not None}")
print(f"  K_6 witness with ADJACENT rails: {found_adjacent is not None}")
if found_adjacent:
    print(f"  adjacent-rail witness pairing  : {found_adjacent}")
elif found:
    print(f"  (only non-adjacent-rail) witness: {found}")

print("=" * 70)
print("CLAIM: deg_Q <= 2*Delta, saturating to 2*Delta at rail separation >=3")
print("=" * 70)
for name, GG, Delta in [("5x5 grid", grid(5, 5), 4)]:
    # interior pair: pick two interior vertices at varying distance, pair the rest arbitrarily by matching
    # measure deg_Q of one chosen logical node as a function of its rails' separation
    interior = [(r, c) for (r, c) in GG.nodes() if 0 < r < 4 and 0 < c < 4]
    base = interior[len(interior) // 2]
    dist = dict(nx.single_source_shortest_path_length(GG, base))
    for sep in (1, 2, 3, 4):
        # find a partner vertex at exactly `sep` from base, both interior
        partner = next((v for v in interior if dist.get(v) == sep and v != base), None)
        if partner is None:
            continue
        # quotient degree of the {base,partner} logical node = distinct logical
        # neighbors; pair every other vertex with itself is impossible, so just
        # count distinct OTHER vertices adjacent to base or partner, minus the
        # internal edge, treating all other vertices as their own singletons.
        nbrs = (set(GG.neighbors(base)) | set(GG.neighbors(partner))) - {base, partner}
        print(f"  {name}: rails sep={sep}  ->  distinct external neighbors = {len(nbrs)}  (2*Delta={2*Delta})")

print("=" * 70)
print("CLAIM: bipartite device => bare-qubit zero-swap clique ceiling is K_2 (no triangle)")
print("=" * 70)
for name, GG in [("5x5 grid", grid(5, 5)), ("2x6 grid", grid(2, 6))]:
    print(f"  {name}: bipartite={nx.is_bipartite(GG)}  triangles={sum(nx.triangles(GG).values())//3}")
