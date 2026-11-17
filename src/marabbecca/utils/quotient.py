"""Induced quotient graph for logical-routing baselines (placeholder when ``pairs`` isn't supplied)."""

from __future__ import annotations

import warnings

from qiskit.transpiler import CouplingMap


class InducedQuotientWarning(UserWarning):
    """Signals that ``make_placement`` will induce a quotient. Supply ``pairs`` to silence."""


warnings.warn(
    "marabbecca.utils.quotient: logical-routing baselines induce logical "
    "connectivity via maximum matching unless ``pairs`` is supplied "
    "explicitly. Different matchings yield different quotient graphs.",
    InducedQuotientWarning,
    stacklevel=2,
)


def make_placement(
    coupling_map: CouplingMap,
) -> tuple[list[tuple[int, int]], CouplingMap]:
    """Maximum-matching placement: returns ``(pairs, logical_cmap)``."""
    import networkx as nx

    G = nx.Graph()
    G.add_edges_from(coupling_map.get_edges())
    matching = nx.max_weight_matching(G, maxcardinality=True)
    pairs = sorted(tuple(sorted(e)) for e in matching)

    p2l = {}
    for i, (a, b) in enumerate(pairs):
        p2l[a] = i
        p2l[b] = i

    log_edges = set()
    for u, v in G.edges():
        lu, lv = p2l.get(u), p2l.get(v)
        if lu is not None and lv is not None and lu != lv:
            log_edges.add((min(lu, lv), max(lu, lv)))

    return pairs, CouplingMap(list(log_edges))
