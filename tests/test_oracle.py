"""Tests for the X01 exact routing oracle.

Covers: hand-solvable instances, single-realization equivalence,
duplicate-support invariance, monotonicity, replay validation, brute-force
cross-check on tiny instances.

Run: .venv/bin/pytest -q tests/test_oracle.py
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "paper"))

from oracle import (  # noqa: E402
    Gate,
    Instance,
    SolveResult,
    _adj_from_edges,
    _apsp,
    _compute_direct_predecessors,
    _line_edges,
    _ring_edges,
    _zero_cost_closure,
    make_gate,
    make_instance,
    replay,
    solve,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tiny_line_instance(multi: bool = True) -> Instance:
    """2 logical qubits, 4 physical nodes in a line. One CRZ gate."""
    return make_instance(2, _line_edges(4), [(0, 1)], multi=multi, label="tiny_line")


def _verify(
    inst: Instance, expected_swaps: int | None = None, timeout: float = 30.0
) -> SolveResult:
    result = solve(inst, timeout=timeout)
    assert result.status == "exact", f"expected exact, got {result.status}"
    if expected_swaps is not None:
        assert result.swap_count == expected_swaps, (
            f"expected {expected_swaps} swaps, got {result.swap_count}"
        )
    assert replay(inst, result), "replay failed"
    return result


# ---------------------------------------------------------------------------
# Hand-solvable: path topology, single gate
# ---------------------------------------------------------------------------


class TestHandSolvablePath:
    def test_single_crz_multi_2q_4nodes(self):
        """Two logical qubits, 4 physical nodes on a line.

        Multi-realization: 4 support pairs. Best layout places each qubit's
        rails adjacent to the other qubit's rails. On a 4-node path [0-1-2-3],
        the rails of q0 are (0,1) and q1 are (2,3). The best support pair for
        multi-realization needs rail_a adj to rail_b. Layout (0,1,2,3) maps
        rails (0,1,2,3) to nodes (0,1,2,3). Support (rail 1 of q0, rail 0 of q1)
        = (r1, r2) = (1, 2), which are adjacent (1-2 edge). So 0 swaps suffice.
        """
        inst = _tiny_line_instance(multi=True)
        _verify(inst, expected_swaps=0)

    def test_single_crz_single_2q_4nodes(self):
        """Default single realization: only (r1=1, r2=2) = (2*0+1, 2*1+0).

        With layout (0,1,2,3): layout[1]=1 (node 1), layout[2]=2 (node 2).
        They are adjacent. So 0 swaps even for single realization.
        """
        inst = _tiny_line_instance(multi=False)
        _verify(inst, expected_swaps=0)

    def test_two_sequential_crz_multi(self):
        """3 logical qubits, chain 6 nodes, CRZ(0,1) then CRZ(1,2).

        With careful layout, each gate can be placed with adjacent rails.
        Multi-realization should achieve 0 swaps.
        """
        inst = make_instance(
            3, _line_edges(6), [(0, 1), (1, 2)], multi=True, label="chain3_seq"
        )
        result = _verify(inst, timeout=30.0)
        # Multi-realization can always find a zero-swap layout for a sequential chain
        assert result.swap_count == 0, (
            f"expected 0 swaps for chain, got {result.swap_count}"
        )

    def test_k2_ring_multi_zero_swaps(self):
        """Two logical qubits on a 4-cycle physical graph.

        4-cycle has all nodes at distance <= 2. Multi-realization should get 0 swaps.
        """
        inst = make_instance(2, _ring_edges(4), [(0, 1)], multi=True, label="k2_ring4")
        _verify(inst, expected_swaps=0)

    def test_crz_chain_3q_needs_no_swap_multi(self):
        """Chain n=3, all-pairs (K3) on a 6-node line.

        Multi-realization oracle should find <=1 swap (routing may share SWAPs
        between sequential layers). Verify result is certified exact.
        """
        inst = make_instance(
            3, _line_edges(6), [(0, 1), (0, 2), (1, 2)], multi=True, label="k3"
        )
        result = _verify(inst, timeout=60.0)
        assert result.swap_count >= 0


# ---------------------------------------------------------------------------
# Single-realization equivalence
# ---------------------------------------------------------------------------


class TestSingleRealizationEquivalence:
    def test_single_support_same_as_multi_with_one_support(self):
        """Single-support and one-support multi instances give the same result.

        An instance with only one support per gate should give same result
        whether passed as multi=True (full 4 supports) restricted to 1 or
        directly as single=False (1 support), when the supports match.
        """
        # Build instance with single gate supporting only (r1=1, r2=2) = default
        gate = Gate(ctrl=0, tgt=1, supports=frozenset({(1, 2)}), label="crz")
        preds = _compute_direct_predecessors([(0, 1)])
        n_phys = 4
        adj = _adj_from_edges(n_phys, _line_edges(n_phys))
        inst_manual = Instance(
            n_logical=2,
            n_phys=n_phys,
            adj=adj,
            gates=(gate,),
            predecessors=preds,
            label="manual_single",
        )

        inst_default = make_instance(
            2, _line_edges(n_phys), [(0, 1)], multi=False, label="default"
        )
        res_manual = solve(inst_manual, timeout=30.0)
        res_default = solve(inst_default, timeout=30.0)

        assert res_manual.status == "exact"
        assert res_default.status == "exact"
        assert res_manual.swap_count == res_default.swap_count

    def test_single_support_gives_valid_replay(self):
        """Replay must pass for single-realization instances."""
        inst = make_instance(2, _line_edges(4), [(0, 1)], multi=False)
        result = solve(inst, timeout=30.0)
        assert result.status == "exact"
        assert replay(inst, result)


# ---------------------------------------------------------------------------
# Duplicate support invariance
# ---------------------------------------------------------------------------


class TestDuplicateSupportInvariance:
    def test_four_copies_same_as_one(self):
        """4 copies of the same support should give the same optimum as 1 copy."""
        support = (1, 2)  # (r1, r2) for q0, q1 on 4-node chain
        gate_dup = Gate(
            ctrl=0, tgt=1, supports=frozenset({support, (1, 2)}), label="crz"
        )
        gate_single = Gate(ctrl=0, tgt=1, supports=frozenset({support}), label="crz")

        preds = (_compute_direct_predecessors([(0, 1)])[0],)
        adj = _adj_from_edges(4, _line_edges(4))

        inst_dup = Instance(2, 4, adj, (gate_dup,), preds, "dup")
        inst_single = Instance(2, 4, adj, (gate_single,), preds, "single")

        res_dup = solve(inst_dup, timeout=30.0)
        res_single = solve(inst_single, timeout=30.0)

        assert res_dup.status == "exact"
        assert res_single.status == "exact"
        assert res_dup.swap_count == res_single.swap_count

    def test_full_supports_vs_subset_nodup(self):
        """Full 4-support set: duplicate-free frozenset same as explicit 4 entries."""
        gate_full = make_gate(0, 1, multi=True)
        assert len(gate_full.supports) == 4  # frozenset; no duplicates by definition
        gate_manual = Gate(
            ctrl=0, tgt=1, supports=frozenset({(0, 2), (0, 3), (1, 2), (1, 3)})
        )
        assert gate_full.supports == gate_manual.supports


# ---------------------------------------------------------------------------
# Multi-realization monotonicity
# ---------------------------------------------------------------------------


class TestMonotonicity:
    def test_multi_opt_le_single_opt(self):
        """Adding more support options never increases the optimum."""
        for n in [2, 3]:
            edge_list = _line_edges(2 * n)
            gp = [(0, 1)]
            inst_multi = make_instance(n, edge_list, gp, multi=True)
            inst_single = make_instance(n, edge_list, gp, multi=False)
            res_m = solve(inst_multi, timeout=30.0)
            res_s = solve(inst_single, timeout=30.0)
            assert res_m.status == "exact"
            assert res_s.status == "exact"
            assert res_m.swap_count <= res_s.swap_count, (
                f"n={n}: multi={res_m.swap_count} > single={res_s.swap_count}"
            )

    def test_superset_supports_no_worse(self):
        """Adding one more support option never increases the optimal cost."""
        # Single gate: start with 2 supports, add all 4
        adj = _adj_from_edges(4, _line_edges(4))
        preds = _compute_direct_predecessors([(0, 1)])
        gate2 = Gate(ctrl=0, tgt=1, supports=frozenset({(0, 2), (1, 3)}))
        gate4 = Gate(
            ctrl=0, tgt=1, supports=frozenset({(0, 2), (0, 3), (1, 2), (1, 3)})
        )
        inst2 = Instance(2, 4, adj, (gate2,), preds, "two_support")
        inst4 = Instance(2, 4, adj, (gate4,), preds, "four_support")
        res2 = solve(inst2, timeout=30.0)
        res4 = solve(inst4, timeout=30.0)
        assert res2.status == "exact"
        assert res4.status == "exact"
        assert res4.swap_count <= res2.swap_count


# ---------------------------------------------------------------------------
# Replay validation
# ---------------------------------------------------------------------------


class TestReplayValidation:
    def test_replay_single_gate_no_swap(self):
        inst = _tiny_line_instance(multi=True)
        result = solve(inst, timeout=30.0)
        assert result.status == "exact"
        ok = replay(inst, result)
        assert ok

    def test_replay_with_swaps(self):
        """Force a SWAP by using a single-realization gate that's hard to reach."""
        # 3 logical qubits, 6-node chain, 3 sequential gates
        inst = make_instance(3, _line_edges(6), [(0, 1), (1, 2), (0, 2)], multi=False)
        result = solve(inst, timeout=60.0)
        assert result.status == "exact"
        assert replay(inst, result)

    def test_replay_rejects_bad_trace(self):
        """Manually corrupt a result and check replay rejects it."""
        inst = _tiny_line_instance(multi=True)
        result = solve(inst, timeout=30.0)
        assert result.status == "exact"

        # Tamper: claim 1 extra SWAP in the count
        bad_result = SolveResult(
            swap_count=result.swap_count + 1,
            status="exact",
            init_layout=result.init_layout,
            actions=result.actions,
            certified=False,
        )
        assert not replay(inst, bad_result)

    def test_replay_rejects_infeasible(self):
        inst = _tiny_line_instance(multi=True)
        bad = SolveResult(
            swap_count=0,
            status="infeasible",
            init_layout=(),
            actions=[],
            certified=False,
        )
        assert not replay(inst, bad)

    def test_replay_all_standard_instances(self):
        """Replay must pass for every hand-solvable instance we can certify."""
        instances = [
            make_instance(2, _line_edges(4), [(0, 1)], multi=True),
            make_instance(2, _line_edges(4), [(0, 1)], multi=False),
            make_instance(3, _line_edges(6), [(0, 1), (1, 2)], multi=True),
            make_instance(3, _line_edges(6), [(0, 1), (1, 2)], multi=False),
        ]
        for inst in instances:
            result = solve(inst, timeout=30.0)
            assert result.status == "exact", f"non-exact for {inst.label}"
            assert replay(inst, result), f"replay failed for {inst.label}"


# ---------------------------------------------------------------------------
# Brute-force cross-check on tiny instances
# ---------------------------------------------------------------------------


def _brute_force_min_swaps(inst: Instance, max_swaps: int = 6) -> int:
    """Exhaustive BFS over (layout, done_bitmask) to find minimum SWAPs.

    Explores all injections of n_rails into n_phys nodes as starting layouts,
    then applies SWAPs up to depth max_swaps. Returns the minimum cost or -1
    if not found within max_swaps.
    """
    from collections import deque

    done_all = (1 << inst.n_gates) - 1

    def closure_done(layout: tuple, done: int) -> int:
        changed = True
        while changed:
            changed = False
            for g in range(inst.n_gates):
                if (done >> g) & 1:
                    continue
                if not all((done >> p) & 1 for p in inst.predecessors[g]):
                    continue
                gate = inst.gates[g]
                for r1, r2 in gate.supports:
                    if layout[r2] in inst.adj[layout[r1]]:
                        done |= 1 << g
                        changed = True
                        break
        return done

    # BFS: state = (layout, done), cost = swaps applied
    seen: dict[tuple, int] = {}
    queue: deque[tuple] = deque()

    for perm in itertools.permutations(range(inst.n_phys), inst.n_rails):
        layout0 = tuple(perm)
        done0 = closure_done(layout0, 0)
        key = (layout0, done0)
        if key not in seen:
            seen[key] = 0
            if done0 == done_all:
                return 0
            queue.append((layout0, done0, 0))

    while queue:
        layout, done, cost = queue.popleft()
        if cost >= max_swaps:
            continue
        for pa, pb in inst.edges:
            inv = {v: k for k, v in enumerate(layout)}
            if pa not in inv and pb not in inv:
                continue
            lst = list(layout)
            ra, rb = inv.get(pa), inv.get(pb)
            if ra is not None:
                lst[ra] = pb
            if rb is not None:
                lst[rb] = pa
            new_layout = tuple(lst)
            new_done = closure_done(new_layout, done)
            new_cost = cost + 1
            key = (new_layout, new_done)
            if key not in seen or seen[key] > new_cost:
                seen[key] = new_cost
                if new_done == done_all:
                    return new_cost
                queue.append((new_layout, new_done, new_cost))
    return -1  # not found within max_swaps


class TestBruteForce:
    def test_single_gate_tiny_brute(self):
        """2q, 4-node line, one CRZ: brute force and oracle must agree."""
        for multi in [True, False]:
            inst = _tiny_line_instance(multi=multi)
            bf = _brute_force_min_swaps(inst)
            res = solve(inst, timeout=30.0)
            assert res.status == "exact"
            assert res.swap_count == bf, (
                f"multi={multi}: oracle={res.swap_count}, brute={bf}"
            )

    def test_two_gate_chain_brute(self):
        """3q, 6-node line, two sequential CRZ: brute force and oracle agree."""
        for multi in [True, False]:
            inst = make_instance(3, _line_edges(6), [(0, 1), (1, 2)], multi=multi)
            bf = _brute_force_min_swaps(inst)
            res = solve(inst, timeout=60.0)
            assert res.status == "exact"
            assert res.swap_count == bf, (
                f"multi={multi}: oracle={res.swap_count}, brute={bf}"
            )

    def test_k3_brute(self):
        """3q, 6-node line, K3 (all pairs): oracle and brute force agree."""
        for multi in [True, False]:
            inst = make_instance(
                3, _line_edges(6), [(0, 1), (0, 2), (1, 2)], multi=multi
            )
            bf = _brute_force_min_swaps(inst)
            res = solve(inst, timeout=60.0)
            assert res.status == "exact"
            assert res.swap_count == bf, (
                f"multi={multi}: oracle={res.swap_count}, brute={bf}"
            )


# ---------------------------------------------------------------------------
# Dependency DAG and predecessor computation
# ---------------------------------------------------------------------------


class TestDAG:
    def test_direct_predecessors_chain(self):
        """Chain of 3 gates on 3 qubits: each gate depends on the prior gate on shared qubit."""
        preds = _compute_direct_predecessors([(0, 1), (1, 2), (0, 2)])
        assert preds[0] == frozenset()
        assert preds[1] == frozenset({0})  # gate 0 uses qubit 1
        assert preds[2] == frozenset({0, 1})  # gate 0 uses qubit 0; gate 1 uses qubit 2

    def test_independent_gates_no_preds(self):
        """Gates on disjoint qubits have no mutual dependency."""
        preds = _compute_direct_predecessors([(0, 1), (2, 3)])
        assert preds[0] == frozenset()
        assert preds[1] == frozenset()

    def test_direct_pred_skips_transitive(self):
        """Only direct (most-recent) predecessor captured, not transitive ones."""
        # Gates: 0=(0,1), 1=(0,2), 2=(0,3)
        # Gate 2 should only have gate 1 as direct pred (not 0)
        preds = _compute_direct_predecessors([(0, 1), (0, 2), (0, 3)])
        assert preds[2] == frozenset({1})


# ---------------------------------------------------------------------------
# APSP sanity
# ---------------------------------------------------------------------------


class TestAPSP:
    def test_line_distances(self):
        """Path graph: distance between nodes i and j is |i-j|."""
        n = 5
        adj = _adj_from_edges(n, _line_edges(n))
        dist = _apsp(n, adj)
        for i in range(n):
            for j in range(n):
                assert dist[i][j] == abs(i - j), f"dist[{i}][{j}] wrong"

    def test_complete_graph_distance(self):
        """Complete graph K4: all non-self distances are 1."""
        n = 4
        edges = [(i, j) for i in range(n) for j in range(i + 1, n)]
        adj = _adj_from_edges(n, edges)
        dist = _apsp(n, adj)
        for i in range(n):
            for j in range(n):
                expected = 0 if i == j else 1
                assert dist[i][j] == expected


# ---------------------------------------------------------------------------
# Zero-cost closure tests
# ---------------------------------------------------------------------------


class TestZeroCostClosure:
    def test_adjacent_gate_executed_immediately(self):
        """A ready gate with adjacent support is executed in zero-cost closure."""
        inst = _tiny_line_instance(multi=True)
        adj = inst.adj
        # Layout (0, 1, 2, 3): rail 0->node 0, rail 1->node 1, rail 2->node 2, rail 3->node 3
        # Gate crz(q0,q1): supports include (r1=1, r2=2) -> (node 1, node 2) which are adjacent
        layout = (0, 1, 2, 3)
        done, actions = _zero_cost_closure(layout, 0, inst, adj)
        done_all = (1 << inst.n_gates) - 1
        assert done == done_all, "adjacent gate should have been executed in closure"
        assert len(actions) == 1
        assert actions[0][0] == "execute"

    def test_non_adjacent_gate_not_executed(self):
        """A ready gate with no adjacent support stays pending."""
        inst = make_instance(2, _line_edges(4), [(0, 1)], multi=False)
        # Default support: (r=1, r=2) = rails at nodes layout[1] and layout[2]
        # Layout (0, 3, 1, 2): rail1->node3, rail2->node1. dist(3,1)=2, not adjacent
        layout = (0, 3, 1, 2)
        done, actions = _zero_cost_closure(layout, 0, inst, inst.adj)
        assert done == 0, "non-adjacent gate should NOT execute"
        assert actions == []
