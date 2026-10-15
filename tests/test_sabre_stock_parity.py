"""prism's vendored SABRE router equals the installed Qiskit's on input without multi-realization ops.

Every op here has one realization of one pair, so prism builds only stock ``TwoQ`` nodes, and the
routed circuit and final layout must match ``qiskit._accelerate.sabre.sabre_routing`` exactly for
the same heuristic, layout, trials and seed.  The flat input mirrors ``SabreDAG::from_dag``: ops in
``topological_op_nodes`` order, successors ascending, and no consecutive gates on the same pair
(which ``from_dag`` would merge).

The heuristic has no lookahead: prism's router fixes a defect in the lookahead layers that the
installed Qiskit still has (``crates/src/sabre/README.md``), so with lookahead the two differ.
The Rust tests ``lookahead_*`` in ``route_ext.rs`` check the lookahead layers instead.
"""

from __future__ import annotations

import random

import pytest
from qiskit import QuantumCircuit
from qiskit._accelerate import sabre as stock
from qiskit._accelerate.nlayout import NLayout
from qiskit.converters import circuit_to_dag
from qiskit.transpiler import CouplingMap, Target

from prism import _accelerate as ours

MAPS = {
    "grid4x4": lambda: CouplingMap.from_grid(4, 4),
    "line12": lambda: CouplingMap.from_line(12),
    "hex19": lambda: CouplingMap.from_heavy_hex(3),
    "ring10": lambda: CouplingMap.from_ring(10),
}

# prism's layout search routes a start with seed ``s`` and no refinement using route seed
# ``1000 * s`` (``crates/src/prism_routing/layout.rs``).
SEED_STRIDE = 1000


def _heuristic(module, n: int):
    """Stock ``SabreLayout`` heuristic in 2.6, without lookahead."""
    return (
        module.Heuristic(attempt_limit=10 * n)
        .with_basic(1.0, module.SetScaling.Constant)
        .with_decay(0.001, 5)
    )


def _random_cx(n: int, m: int, rng: random.Random) -> QuantumCircuit:
    qc, last = QuantumCircuit(n), {}
    while len(qc.data) < m:
        a, b = rng.sample(range(n), 2)
        if last.get(a) == last.get(b) == frozenset((a, b)):
            continue
        qc.cx(a, b)
        last[a] = last[b] = frozenset((a, b))
    return qc


def _route_stock(dag, cmap, n, seed, trials):
    target = Target.from_configuration(["cx"], coupling_map=cmap)
    out, final = stock.sabre_routing(
        dag,
        stock.RoutingTarget.from_target(target),
        _heuristic(stock, n),
        NLayout.generate_trivial_layout(n),
        trials,
        SEED_STRIDE * seed,
    )
    return out, [final.virtual_to_physical(v) for v in range(n)]


def _route_ours(dag, cmap, n, seed, trials):
    nodes = list(dag.topological_op_nodes())
    index = {node: k for k, node in enumerate(nodes)}
    qubits = [[dag.find_bit(q).index for q in node.qargs] for node in nodes]
    succ = [sorted({index[s] for s in dag.op_successors(node)}) for node in nodes]
    pred = [0] * len(nodes)
    for ss in succ:
        for s in ss:
            pred[s] += 1
    flat = ([[[q]] for q in qubits], succ, pred, [0] * len(nodes))
    [(events, final_v2p, _, _)] = ours.prism_layout_and_routing(
        flat,
        flat,
        ours.RoutingTarget.from_coupling_list([list(e) for e in cmap.get_edges()], n),
        _heuristic(ours, n),
        [(seed, list(range(n)))],
        0,
        trials,
    )
    qc, v2p, p2v = QuantumCircuit(n), list(range(n)), list(range(n))
    for kind, a, b in events:
        if kind == 1:  # swap physical a, b
            qc.swap(b, a)
            va, vb = p2v[a], p2v[b]
            v2p[va], v2p[vb] = b, a
            p2v[a], p2v[b] = vb, va
        else:
            q0, q1 = qubits[a]
            qc.cx(v2p[q0], v2p[q1])
    return circuit_to_dag(qc), final_v2p


@pytest.mark.parametrize("trials", [1, 4])
@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("gates", [20, 80, 200])
@pytest.mark.parametrize("name", list(MAPS))
def test_matches_stock_sabre_routing(name, gates, seed, trials):
    cmap = MAPS[name]()
    n = cmap.size()
    dag = circuit_to_dag(_random_cx(n, gates, random.Random(1000 * seed + gates)))
    stock_dag, stock_v2p = _route_stock(dag, cmap, n, seed, trials)
    ours_dag, ours_v2p = _route_ours(dag, cmap, n, seed, trials)
    assert ours_dag == stock_dag
    assert ours_v2p == stock_v2p


def test_detects_a_different_seed():
    """The comparison is sensitive: a different seed changes the stock route."""
    cmap = MAPS["grid4x4"]()
    n = cmap.size()
    dag = circuit_to_dag(_random_cx(n, 200, random.Random(7)))
    assert _route_ours(dag, cmap, n, 1, 1) != _route_stock(dag, cmap, n, 2, 1)
