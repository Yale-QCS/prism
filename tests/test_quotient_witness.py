"""Machine checks for the paper's Section 3 propositions (quotient connectivity)."""

from itertools import combinations

from qiskit.transpiler import CouplingMap

# Explicit K_6 witness on the 2x6 ladder (paper Fig. quotient-graph / Prop.
# "strict graph-class separation"): six two-site blocks, all 12 sites used,
# found by .claude/scripts/research/quotient_embedding/k6_ladder_witness.py
# and re-verified independently here. Site s = 6*row + col.
K6_PLACEMENT = {
    0: (0, 4),
    1: (1, 9),
    2: (7, 10),
    3: (3, 11),
    4: (5, 8),
    5: (2, 6),
}


def test_k6_on_2x6_ladder():
    """All 15 logical pairs of the six two-site blocks meet on a ladder edge."""
    cm = CouplingMap.from_grid(2, 6)
    edges = {frozenset(e) for e in cm.get_edges()}
    sites = [s for pair in K6_PLACEMENT.values() for s in pair]
    assert len(sites) == len(set(sites)) == 12
    for a, b in combinations(K6_PLACEMENT, 2):
        assert any(
            frozenset((ra, rb)) in edges
            for ra in K6_PLACEMENT[a]
            for rb in K6_PLACEMENT[b]
        ), f"pair ({a},{b}) has no adjacent rail pair"


def test_bare_qubits_on_ladder_have_no_triangle():
    """The bipartite ladder itself contains no K_3, so the K_6 quotient is a strict gain."""
    cm = CouplingMap.from_grid(2, 6)
    edges = {frozenset(e) for e in cm.get_edges()}
    nodes = range(cm.size())
    for tri in combinations(nodes, 3):
        assert not all(frozenset(p) in edges for p in combinations(tri, 2)), (
            f"triangle {tri} in supposedly bipartite ladder"
        )


def test_quotient_degree_bound():
    """deg_Q(q) <= sum of member degrees <= k*Delta on the witness layout."""
    cm = CouplingMap.from_grid(2, 6)
    edges = {frozenset(e) for e in cm.get_edges()}
    deg = {v: 0 for v in range(cm.size())}
    for e in edges:
        for v in e:
            deg[v] += 1
    delta = max(deg.values())
    site_owner = {s: q for q, pair in K6_PLACEMENT.items() for s in pair}
    for q, pair in K6_PLACEMENT.items():
        neighbors = {
            site_owner[w]
            for v in pair
            for e in edges
            if v in e
            for w in e
            if w != v and site_owner[w] != q
        }
        assert len(neighbors) <= sum(deg[v] for v in pair) <= 2 * delta
