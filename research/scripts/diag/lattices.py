"""Coupling maps for the port-choice study: grid (bipartite), hex (bipartite), triangular (grid plus one
diagonal per cell, non-bipartite: a site can neighbor both rails of an adjacent pair), king (grid plus
both diagonals)."""
from qiskit.transpiler import CouplingMap
def triangular(rows, cols):
    edges = []
    idx = lambda r, c: r * cols + c
    for r in range(rows):
        for c in range(cols):
            if c + 1 < cols: edges.append([idx(r, c), idx(r, c + 1)])
            if r + 1 < rows: edges.append([idx(r, c), idx(r + 1, c)])
            if r + 1 < rows and c + 1 < cols: edges.append([idx(r, c), idx(r + 1, c + 1)])
    return CouplingMap(edges + [[b, a] for a, b in edges])
def king(rows, cols):
    edges = []
    idx = lambda r, c: r * cols + c
    for r in range(rows):
        for c in range(cols):
            if c + 1 < cols: edges.append([idx(r, c), idx(r, c + 1)])
            if r + 1 < rows: edges.append([idx(r, c), idx(r + 1, c)])
            if r + 1 < rows and c + 1 < cols: edges.append([idx(r, c), idx(r + 1, c + 1)])
            if r + 1 < rows and c >= 1: edges.append([idx(r, c), idx(r + 1, c - 1)])
    return CouplingMap(edges + [[b, a] for a, b in edges])
def lattices(n_logical):
    n_phys = 2 * (n_logical + 1)
    import math
    rows = math.ceil(math.sqrt(n_phys)); cols = math.ceil(n_phys / rows)
    side = math.ceil(math.sqrt(n_phys / 2))
    while CouplingMap.from_hexagonal_lattice(side, side).size() < n_phys: side += 1
    return {"hex": CouplingMap.from_hexagonal_lattice(side, side), "grid": CouplingMap.from_grid(rows, cols),
            "triangular": triangular(rows, cols), "king": king(rows, cols)}
