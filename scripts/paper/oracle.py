"""Exact routing oracle for small dual-rail CRZ-only circuits.

Problem: given a physical connectivity graph G, a dependency DAG of logical CRZ
gates with per-gate support sets (pairs of logical rail indices), and unit-cost
physical SWAPs, jointly find the initial layout, gate execution order consistent
with dependencies, realization (support choice) per gate, and SWAP sequence that
minimizes total inserted SWAPs. Final layout is free.

Search: Dijkstra over states (canonical_layout_tuple, done_bitmask).
Zero-cost closure: execute all ready gates with an adjacent valid support before
any SWAP expansion. This is applied after every SWAP and at initialization.
Unit-cost transitions: SWAP any physical edge.
Initial layout: joint -- all injections of n_rails logical rails into n_phys
physical nodes are seeded as starting states at cost 0.

Rail-exchange symmetry: for logical qubit q with rails (2q, 2q+1), swapping
the two rails gives an equivalent state if ALL gates involving q have support
sets symmetric under this swap. CRZ with all four supports is symmetric for
both control and target. CRZ with the single default support (ra=1, rb=0) is
NOT symmetric for either qubit. The canonical form sorts each eligible
qubit's rail pair: min(layout[2q], layout[2q+1]) at index 2q.

Admissible lower bound:
  h(state) = max over ready-but-not-adjacent gates g of max(0, d_min(g) - 1)
  where d_min(g) = min over (r1,r2) in g.supports of shortest_path(layout[r1], layout[r2]).
  Admissible: executing g requires its endpoints adjacent (distance 1); each SWAP
  reduces distance along any path by at most 1; so d_min - 1 SWAPs are needed for
  g alone. Taking the max (not sum) ensures the bound is valid with shared SWAPs.

Default realization: DualRail.crz uses default_index=2. The four candidates are
indexed as (ra, rb) in (0,1)x(0,1), so index 2 = (ra=1, rb=0). In logical rail
terms: rail 1 of the control qubit (2*ctrl+1) adjacent to rail 0 of the target
qubit (2*tgt+0). The single-realization oracle restricts to this one support.

Scope restriction: CRZ-only logical circuits, no logical X or SWAP gates.
This ensures the compiler's final swap instruction count equals routing overhead.
Initialization uses local_init=True (_DualRailLocalInit) to suppress the
co-location herald CRZ(pi), which would otherwise add init-routing SWAPs and
make the compiler count incomparable to the oracle's gate-routing count.
"""

from __future__ import annotations

import heapq
import itertools
import json
import math
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Adjust sys.path so we can import marabbecca without installing
# ---------------------------------------------------------------------------
_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from paper_common import run_id  # noqa: E402

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class Gate(NamedTuple):
    """A logical 2-qubit gate with its set of valid physical support pairs.

    ctrl, tgt: logical qubit indices.
    supports: frozenset of (logical_rail_1, logical_rail_2) pairs, where
    logical rail index r belongs to logical qubit r//2. The gate is executable
    when layout[r1] and layout[r2] are adjacent in the physical graph.
    label: human-readable gate name.
    """

    ctrl: int
    tgt: int
    supports: frozenset[tuple[int, int]]
    label: str = "crz"


@dataclass(frozen=True)
class Instance:
    """A routing oracle problem instance.

    n_logical: number of logical qubits; each encoded as 2 rails (indices 2q, 2q+1).
    n_phys: number of physical nodes (labels 0..n_phys-1).
    adj: per-node adjacency frozensets, length n_phys.
    gates: tuple of Gate objects in a valid topological order.
    predecessors: predecessors[i] is the frozenset of gate indices that must
                  complete before gate i (direct dependency DAG).
    label: human-readable instance name.
    """

    n_logical: int
    n_phys: int
    adj: tuple[frozenset[int], ...]
    gates: tuple[Gate, ...]
    predecessors: tuple[frozenset[int], ...]
    label: str = ""

    @property
    def n_rails(self) -> int:
        return 2 * self.n_logical

    @property
    def n_gates(self) -> int:
        return len(self.gates)

    @property
    def edges(self) -> list[tuple[int, int]]:
        seen = []
        for u, nbrs in enumerate(self.adj):
            for v in nbrs:
                if u < v:
                    seen.append((u, v))
        return sorted(seen)


@dataclass
class SolveResult:
    """Oracle solver result for one instance with one realization mode."""

    swap_count: int
    status: str  # "exact", "bound" (timeout), "infeasible"
    init_layout: tuple[int, ...]  # logical_rail -> physical_node at t=0
    actions: list  # ('execute', gate_idx, (p1, p2)) or ('swap', p1, p2)
    certified: bool  # True if replay confirmed the trace
    solve_time_s: float = 0.0


# ---------------------------------------------------------------------------
# All-pairs shortest paths (BFS)
# ---------------------------------------------------------------------------


def _apsp(n_phys: int, adj: tuple[frozenset[int], ...]) -> list[list[int]]:
    """All-pairs shortest paths on the physical graph via BFS from each node."""
    INF = 10**9
    dist = [[INF] * n_phys for _ in range(n_phys)]
    for src in range(n_phys):
        dist[src][src] = 0
        q: deque[int] = deque([src])
        while q:
            u = q.popleft()
            for v in adj[u]:
                if dist[src][v] == INF:
                    dist[src][v] = dist[src][u] + 1
                    q.append(v)
    return dist


# ---------------------------------------------------------------------------
# Symmetry: which logical qubits can have their rails exchanged
# ---------------------------------------------------------------------------


def _sym_mask(instance: Instance) -> list[bool]:
    """Compute which logical qubits admit rail-exchange canonicalization.

    Qubit q is symmetrizable if every gate involving q has a support set
    symmetric under swapping rails 2q and 2q+1. CRZ with all 4 supports is
    always symmetric. Single-realization CRZ is NOT symmetric.
    """
    can_sym = [True] * instance.n_logical
    for q in range(instance.n_logical):
        r0, r1 = 2 * q, 2 * q + 1
        for gate in instance.gates:
            # Check if gate involves qubit q
            involves = any(r in (r0, r1) for pair in gate.supports for r in pair)
            if not involves:
                continue
            # Check symmetry under swap of r0 <-> r1
            swapped = frozenset(
                (
                    r1 if a == r0 else (r0 if a == r1 else a),
                    r1 if b == r0 else (r0 if b == r1 else b),
                )
                for a, b in gate.supports
            )
            if swapped != gate.supports:
                can_sym[q] = False
                break
    return can_sym


def _make_canonicalizer(n_logical: int, can_sym: list[bool]):
    """Return a closure that maps layout tuples to their canonical form.

    For each symmetrizable qubit q, we sort the pair (layout[2q], layout[2q+1])
    so that the smaller physical node occupies index 2q. This is applied for
    all 2^(#symmetrizable) combinations and the lexicographically smallest
    result is chosen.
    """
    sym_qubits = [q for q in range(n_logical) if can_sym[q]]

    if not sym_qubits:
        return lambda layout: layout

    def canonicalize(layout: tuple[int, ...]) -> tuple[int, ...]:
        best = layout
        for mask in range(1 << len(sym_qubits)):
            lst = list(layout)
            for bit, q in enumerate(sym_qubits):
                if (mask >> bit) & 1:
                    lst[2 * q], lst[2 * q + 1] = lst[2 * q + 1], lst[2 * q]
            cand = tuple(lst)
            if cand < best:
                best = cand
        return best

    return canonicalize


# ---------------------------------------------------------------------------
# Zero-cost closure
# ---------------------------------------------------------------------------


def _zero_cost_closure(
    layout: tuple[int, ...],
    done: int,
    instance: Instance,
    adj: tuple[frozenset[int], ...],
) -> tuple[int, list]:
    """Execute all ready gates with an adjacent support; return (new_done, actions).

    Layout is unchanged (gate execution does not move rails). The returned actions
    list records ('execute', gate_idx, (phys1, phys2)) for each executed gate,
    in the order executed. The support chosen is the lex-smallest adjacent pair.
    """
    actions = []
    changed = True
    while changed:
        changed = False
        for g in range(instance.n_gates):
            if (done >> g) & 1:
                continue
            # Check all predecessors done
            if not all((done >> p) & 1 for p in instance.predecessors[g]):
                continue
            # Find the lex-smallest adjacent support
            gate = instance.gates[g]
            best_support = None
            for r1, r2 in sorted(gate.supports):
                p1, p2 = layout[r1], layout[r2]
                if p2 in adj[p1]:
                    if best_support is None or (p1, p2) < best_support:
                        best_support = (p1, p2)
            if best_support is not None:
                done |= 1 << g
                actions.append(("execute", g, best_support))
                changed = True
    return done, actions


# ---------------------------------------------------------------------------
# SWAP application
# ---------------------------------------------------------------------------


def _apply_swap(layout: tuple[int, ...], pa: int, pb: int) -> tuple[int, ...]:
    """Apply a physical SWAP on edge (pa, pb) to the layout.

    For tight layouts (all physical nodes occupied): exchange the two rails.
    For sparse layouts: if only one endpoint is occupied, the rail moves there.
    """
    lst = list(layout)
    inv: dict[int, int] = {v: k for k, v in enumerate(lst)}
    ra = inv.get(pa)
    rb = inv.get(pb)
    if ra is not None:
        lst[ra] = pb
    if rb is not None:
        lst[rb] = pa
    return tuple(lst)


# ---------------------------------------------------------------------------
# Admissible A* heuristic
# ---------------------------------------------------------------------------


def _heuristic(
    layout: tuple[int, ...],
    done: int,
    instance: Instance,
    dist: list[list[int]],
) -> int:
    """Admissible lower bound on remaining SWAPs needed.

    For each ready-but-not-adjacent gate g, at least max(0, d_min(g) - 1) SWAPs
    are needed to make g executable. The maximum over all such gates is a valid
    lower bound (admissible) because any single SWAP reduces distance by at most 1
    along any path, and we take the max (not sum), so shared SWAPs are not
    double-counted against the bound.
    """
    h = 0
    for g in range(instance.n_gates):
        if (done >> g) & 1:
            continue
        if not all((done >> p) & 1 for p in instance.predecessors[g]):
            continue
        gate = instance.gates[g]
        d_min = min(dist[layout[r1]][layout[r2]] for r1, r2 in gate.supports)
        h = max(h, d_min - 1)
    return h


# ---------------------------------------------------------------------------
# Main Dijkstra / A* solver
# ---------------------------------------------------------------------------


def solve(
    instance: Instance,
    *,
    timeout: float = 300.0,
    use_symmetry: bool = True,
    init_layout: tuple[int, ...] | None = None,
) -> SolveResult:
    """Exact joint-layout routing oracle via Dijkstra with zero-cost closure.

    Returns a SolveResult with status 'exact' if all states are certified,
    'bound' if the timeout was reached before proving optimality, or 'infeasible'
    if no solution exists (disconnected graph case). ``init_layout`` (rail ->
    node) fixes the initial layout instead of seeding every injection.
    """
    t_start = time.monotonic()

    if instance.n_gates == 0:
        return SolveResult(
            swap_count=0,
            status="exact",
            init_layout=tuple(range(instance.n_rails)),
            actions=[],
            certified=True,
            solve_time_s=0.0,
        )

    adj = instance.adj
    dist = _apsp(instance.n_phys, adj)
    can_sym = _sym_mask(instance) if use_symmetry else [False] * instance.n_logical
    canonicalize = _make_canonicalizer(instance.n_logical, can_sym)

    done_all = (1 << instance.n_gates) - 1
    n_rails = instance.n_rails
    n_phys = instance.n_phys

    # State key: (canonical_layout, done_bitmask)
    # Heap entry: (f_score, counter, g_score, state_key)
    # came_from[state_key] = (prev_state_key_or_None, actions_since_prev, actual_layout_here)
    visited: dict[tuple, int] = {}  # state_key -> best g_score
    came_from: dict[tuple, tuple] = {}  # state_key -> (prev, actions, actual_layout)

    heap: list = []
    _ctr = itertools.count()

    def _push(
        g_score: int, state_key: tuple, prev_key, actions: list, actual_layout: tuple
    ):
        if state_key in visited and visited[state_key] <= g_score:
            return
        visited[state_key] = g_score
        came_from[state_key] = (prev_key, actions, actual_layout)
        h = _heuristic(actual_layout, state_key[1], instance, dist)
        heapq.heappush(heap, (g_score + h, next(_ctr), g_score, state_key))

    # Seed initial layouts: all injections of n_rails rails into n_phys nodes.
    # Equivalent to a virtual super-source with zero-cost edges to each starting state.
    seeds = (
        [init_layout]
        if init_layout is not None
        else itertools.permutations(range(n_phys), n_rails)
    )
    for perm in seeds:
        layout0 = tuple(perm)
        done0, init_actions = _zero_cost_closure(layout0, 0, instance, adj)
        canon0 = canonicalize(layout0)
        sk0 = (canon0, done0)
        _push(0, sk0, None, init_actions, layout0)

    # Physical edges: (pa, pb) with pa < pb, for SWAP generation
    phys_edges = instance.edges

    best_goal: tuple | None = None
    best_cost = 10**9

    while heap:
        if time.monotonic() - t_start > timeout:
            # Timeout: report bound if we have any solution, else infeasible
            if best_goal is not None:
                result = _reconstruct(best_goal, came_from, best_cost, t_start)
                result.status = "bound"
                result.certified = False
                return result
            return SolveResult(
                swap_count=-1,
                status="bound",
                init_layout=(),
                actions=[],
                certified=False,
                solve_time_s=time.monotonic() - t_start,
            )

        f, _, heap_g, sk = heapq.heappop(heap)

        # Lazy deletion: skip stale entries where we later found a better path.
        # visited[sk] always holds the best g found so far; if heap_g is larger,
        # this entry was superseded.
        actual_g = visited[sk]
        if heap_g > actual_g:
            continue

        canon_layout, done = sk
        actual_layout = came_from[sk][2]

        # Goal check
        if done == done_all:
            if actual_g < best_cost:
                best_cost = actual_g
                best_goal = sk
            # Dijkstra: first time we extract a goal state, it's optimal
            result = _reconstruct(sk, came_from, actual_g, t_start)
            result.certified = replay(instance, result, adj)
            return result

        # Expand: apply each physical SWAP (cost +1)
        inv_layout = {v: k for k, v in enumerate(actual_layout)}
        for pa, pb in phys_edges:
            # Only SWAP if at least one endpoint is occupied
            if pa not in inv_layout and pb not in inv_layout:
                continue

            new_layout = _apply_swap(actual_layout, pa, pb)
            new_done, exec_actions = _zero_cost_closure(new_layout, done, instance, adj)
            new_canon = canonicalize(new_layout)
            new_sk = (new_canon, new_done)
            new_g = actual_g + 1
            actions_step = [("swap", pa, pb)] + exec_actions
            _push(new_g, new_sk, sk, actions_step, new_layout)

    # Heap exhausted: if we never reached goal, infeasible
    if best_goal is not None:
        result = _reconstruct(best_goal, came_from, best_cost, t_start)
        result.certified = replay(instance, result, adj)
        return result
    return SolveResult(
        swap_count=-1,
        status="infeasible",
        init_layout=(),
        actions=[],
        certified=False,
        solve_time_s=time.monotonic() - t_start,
    )


def _reconstruct(
    goal_sk: tuple,
    came_from: dict,
    cost: int,
    t_start: float,
) -> SolveResult:
    """Trace back through came_from to build the full action sequence."""
    path = []
    sk = goal_sk
    while sk is not None:
        prev_sk, actions, actual_layout = came_from[sk]
        path.append((actual_layout, actions))
        sk = prev_sk
    path.reverse()

    # The initial layout is the actual layout of the first state in the chain
    init_layout = path[0][0]
    all_actions = []
    for _, acts in path:
        all_actions.extend(acts)

    return SolveResult(
        swap_count=cost,
        status="exact",
        init_layout=init_layout,
        actions=all_actions,
        certified=False,
        solve_time_s=time.monotonic() - t_start,
    )


# ---------------------------------------------------------------------------
# Replay / certificate validation
# ---------------------------------------------------------------------------


def replay(
    instance: Instance,
    result: SolveResult,
    adj: tuple[frozenset[int], ...] | None = None,
) -> bool:
    """Validate a SolveResult by replaying the action sequence.

    Returns True if:
    - Every 'swap' action is on a valid physical edge
    - Every 'execute' action's gate is ready (predecessors done) and has an
      adjacent support matching the recorded (p1, p2) = (layout[r1], layout[r2])
    - Total SWAP count matches result.swap_count
    - All gates are done at the end
    """
    if result.status == "infeasible":
        return False
    if adj is None:
        adj = instance.adj

    layout = list(result.init_layout)
    if len(layout) != instance.n_rails:
        return False

    done = 0
    swap_count = 0
    inv = {v: k for k, v in enumerate(layout)}

    for action in result.actions:
        if action[0] == "swap":
            _, pa, pb = action
            if pb not in adj[pa]:
                return False
            ra = inv.get(pa)
            rb = inv.get(pb)
            if ra is not None and rb is not None:
                layout[ra] = pb
                layout[rb] = pa
                inv[pb] = ra
                inv[pa] = rb
            elif ra is not None:
                layout[ra] = pb
                inv[pb] = ra
                inv.pop(pa, None)
            elif rb is not None:
                layout[rb] = pa
                inv[pa] = rb
                inv.pop(pb, None)
            swap_count += 1

        elif action[0] == "execute":
            _, g_idx, (p1, p2) = action
            if (done >> g_idx) & 1:
                return False  # double execution
            if not all((done >> p) & 1 for p in instance.predecessors[g_idx]):
                return False  # predecessor not done
            gate = instance.gates[g_idx]
            # Check that (p1, p2) is a valid support
            valid = False
            for r1, r2 in gate.supports:
                if layout[r1] == p1 and layout[r2] == p2:
                    if p2 in adj[p1]:
                        valid = True
                        break
            if not valid:
                return False
            done |= 1 << g_idx
        else:
            return False

    done_all = (1 << instance.n_gates) - 1
    if done != done_all:
        return False
    if swap_count != result.swap_count:
        return False
    return True


# ---------------------------------------------------------------------------
# Instance builders
# ---------------------------------------------------------------------------


def _compute_direct_predecessors(
    gate_pairs: list[tuple[int, int]],
) -> tuple[frozenset[int], ...]:
    """Direct dependency DAG: gate j's predecessors are the most recent gate
    on each qubit of j that precedes j in the list."""
    last_on_qubit: dict[int, int] = {}
    preds = []
    for j, (c, t) in enumerate(gate_pairs):
        direct_preds: set[int] = set()
        if c in last_on_qubit:
            direct_preds.add(last_on_qubit[c])
        if t in last_on_qubit:
            direct_preds.add(last_on_qubit[t])
        preds.append(frozenset(direct_preds))
        last_on_qubit[c] = j
        last_on_qubit[t] = j
    return tuple(preds)


def _adj_from_edges(n: int, edges: list[tuple[int, int]]) -> tuple[frozenset[int], ...]:
    """Build adjacency tuple from undirected edge list."""
    nbrs: list[set[int]] = [set() for _ in range(n)]
    for a, b in edges:
        nbrs[a].add(b)
        nbrs[b].add(a)
    return tuple(frozenset(s) for s in nbrs)


def make_gate(ctrl: int, tgt: int, multi: bool = True) -> Gate:
    """Make a CRZ gate between logical qubits ctrl and tgt.

    multi=True: all 4 rail-pair supports.
    multi=False: single default realization (ra=1, rb=0, i.e. (2*ctrl+1, 2*tgt+0)).
    DualRail.crz default_index=2 corresponds to (ra=1, rb=0) in the loop
    for ra in (0,1): for rb in (0,1): candidates[2*ra + rb] = circuit(ra,rb).
    So index 2 = (ra=1, rb=0): rail 1 of control adjacent to rail 0 of target.
    """
    if multi:
        supports = frozenset(
            (2 * ctrl + ra, 2 * tgt + rb) for ra in (0, 1) for rb in (0, 1)
        )
    else:
        # Default: ra=1 (rail 2*ctrl+1), rb=0 (rail 2*tgt+0)
        supports = frozenset({(2 * ctrl + 1, 2 * tgt + 0)})
    return Gate(ctrl=ctrl, tgt=tgt, supports=supports)


def make_instance(
    n_logical: int,
    edge_list: list[tuple[int, int]],
    gate_pairs: list[tuple[int, int]],
    multi: bool = True,
    label: str = "",
) -> Instance:
    """Build an Instance from a physical edge list and ordered CRZ gate list.

    gate_pairs: list of (ctrl, tgt) logical qubit pairs in sequential order.
    The dependency DAG is the direct-predecessor DAG derived from this ordering.
    """
    n_phys = max(max(a, b) for a, b in edge_list) + 1
    adj = _adj_from_edges(n_phys, edge_list)
    gates = tuple(make_gate(c, t, multi=multi) for c, t in gate_pairs)
    preds = _compute_direct_predecessors(gate_pairs)
    return Instance(
        n_logical=n_logical,
        n_phys=n_phys,
        adj=adj,
        gates=gates,
        predecessors=preds,
        label=label,
    )


def _line_edges(n: int) -> list[tuple[int, int]]:
    """Edges of a path graph on n nodes."""
    return [(i, i + 1) for i in range(n - 1)]


def _ring_edges(n: int) -> list[tuple[int, int]]:
    """Edges of a cycle graph on n nodes."""
    return [(i, (i + 1) % n) for i in range(n)]


def _grid_edges(rows: int, cols: int) -> list[tuple[int, int]]:
    """Edges of an r x c grid graph (row-major node labeling)."""
    edges = []
    for r in range(rows):
        for c in range(cols):
            n = r * cols + c
            if c + 1 < cols:
                edges.append((n, n + 1))
            if r + 1 < rows:
                edges.append((n, n + cols))
    return edges


# ---------------------------------------------------------------------------
# Compiler runner (for S_greedy and S_prism)
# ---------------------------------------------------------------------------


def _run_compiler(
    gate_pairs: list[tuple[int, int]],
    n_logical: int,
    edge_list: list[tuple[int, int]],
    strategy: str,
    seed: int = 0,
    theta: float = math.pi / 4,
) -> int:
    """Run the marabbecca compiler on a CRZ-only circuit and return swap count.

    Uses _DualRailLocalInit (local_init=True) to suppress the co-location herald
    CRZ(pi), which would otherwise add init-routing SWAPs not accounted for in
    the oracle. The oracle counts only gate-routing SWAPs; local_init=True makes
    the compiler count agree.
    """
    from qiskit import QuantumCircuit
    from qiskit.transpiler import CouplingMap

    from marabbecca.encodings import DualRail
    from marabbecca.staged_pms import build_pm

    class _DualRailLocalInit(DualRail):
        """DualRail with local (single-wire) init; no co-location herald."""

        local_init = True

    # Build logical circuit (topological order = gate_pairs order)
    qc = QuantumCircuit(n_logical)
    for ctrl, tgt in gate_pairs:
        qc.crz(theta, ctrl, tgt)

    # Build coupling map from edge list
    max(max(a, b) for a, b in edge_list)  # raises on an empty edge_list
    # CouplingMap needs explicit reverse edges for undirected
    cmap2 = CouplingMap([(a, b) for a, b in edge_list] + [(b, a) for a, b in edge_list])
    cmap2.make_symmetric()

    pm = build_pm(
        cmap2, enc=_DualRailLocalInit, strategy=strategy, seed=seed, objective="swaps"
    )
    pm.run(qc)
    return pm.property_set["circuit_metrics"].swaps


# ---------------------------------------------------------------------------
# Experiment instance catalog
# ---------------------------------------------------------------------------


def _crz_chain_n3(
    multi: bool,
) -> tuple[Instance, list[tuple[int, int]], list[tuple[int, int]]]:
    """CRZ chain on 3 logical qubits: crz(0,1) -> crz(1,2). 6-node chain topology."""
    gp = [(0, 1), (1, 2)]
    edges = _line_edges(6)
    return make_instance(3, edges, gp, multi=multi, label="crz_chain_n3"), gp, edges


def _crz_ring_n3(
    multi: bool,
) -> tuple[Instance, list[tuple[int, int]], list[tuple[int, int]]]:
    """CRZ triangle on 3 logical qubits: crz(0,1) -> crz(1,2) -> crz(0,2). 6-node chain."""
    gp = [(0, 1), (1, 2), (0, 2)]
    edges = _line_edges(6)
    return make_instance(3, edges, gp, multi=multi, label="crz_ring_n3"), gp, edges


def _k3(multi: bool) -> tuple[Instance, list[tuple[int, int]], list[tuple[int, int]]]:
    """All-pairs CRZ on 3 logical qubits (K3). 6-node chain."""
    gp = [(0, 1), (0, 2), (1, 2)]
    edges = _line_edges(6)
    return make_instance(3, edges, gp, multi=multi, label="k3"), gp, edges


def _crz_chain_n4(
    multi: bool,
) -> tuple[Instance, list[tuple[int, int]], list[tuple[int, int]]]:
    """CRZ chain on 4 logical qubits: crz(0,1)->crz(1,2)->crz(2,3). 8-node chain."""
    gp = [(0, 1), (1, 2), (2, 3)]
    edges = _line_edges(8)
    return make_instance(4, edges, gp, multi=multi, label="crz_chain_n4"), gp, edges


def _k4(multi: bool) -> tuple[Instance, list[tuple[int, int]], list[tuple[int, int]]]:
    """All-pairs CRZ on 4 logical qubits (K4). 8-node chain."""
    gp = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
    edges = _line_edges(8)
    return make_instance(4, edges, gp, multi=multi, label="k4"), gp, edges


def _rand_dag_n3(
    multi: bool,
) -> tuple[Instance, list[tuple[int, int]], list[tuple[int, int]]]:
    """Random CRZ DAG on 3 logical qubits, seed=42. 6-node chain."""
    import random

    rng = random.Random(42)
    pairs = [(i, j) for i in range(3) for j in range(i + 1, 3)]
    rng.shuffle(pairs)
    # Take 4 random gates (with some repetition allowed via the ordering)
    gp = [pairs[i % len(pairs)] for i in range(4)]
    # Deduplicate consecutive same-pair: keep ordering but avoid trivial no-ops
    edges = _line_edges(6)
    return make_instance(3, edges, gp, multi=multi, label="rand_dag_n3_s42"), gp, edges


def _rand_dag_n4(
    multi: bool,
) -> tuple[Instance, list[tuple[int, int]], list[tuple[int, int]]]:
    """Random CRZ DAG on 4 logical qubits, seed=42. 8-node chain."""
    import random

    rng = random.Random(42)
    pairs = [(i, j) for i in range(4) for j in range(i + 1, 4)]
    rng.shuffle(pairs)
    gp = pairs[:5]  # 5 random pairs (no repeats from a shuffle of 6 pairs)
    edges = _line_edges(8)
    return make_instance(4, edges, gp, multi=multi, label="rand_dag_n4_s42"), gp, edges


def _crz_chain_n3_grid(
    multi: bool,
) -> tuple[Instance, list[tuple[int, int]], list[tuple[int, int]]]:
    """CRZ chain on 3 logical qubits on a 2x3 grid (6 nodes)."""
    gp = [(0, 1), (1, 2)]
    edges = _grid_edges(2, 3)
    return (
        make_instance(3, edges, gp, multi=multi, label="crz_chain_n3_grid23"),
        gp,
        edges,
    )


def _k3_grid(
    multi: bool,
) -> tuple[Instance, list[tuple[int, int]], list[tuple[int, int]]]:
    """K3 on 2x3 grid (6 nodes)."""
    gp = [(0, 1), (0, 2), (1, 2)]
    edges = _grid_edges(2, 3)
    return make_instance(3, edges, gp, multi=multi, label="k3_grid23"), gp, edges


def _crz_chain_n4_grid(
    multi: bool,
) -> tuple[Instance, list[tuple[int, int]], list[tuple[int, int]]]:
    """CRZ chain on 4 logical qubits on a 2x4 grid (8 nodes)."""
    gp = [(0, 1), (1, 2), (2, 3)]
    edges = _grid_edges(2, 4)
    return (
        make_instance(4, edges, gp, multi=multi, label="crz_chain_n4_grid24"),
        gp,
        edges,
    )


def _k4_grid(
    multi: bool,
) -> tuple[Instance, list[tuple[int, int]], list[tuple[int, int]]]:
    """K4 on 2x4 grid (8 nodes)."""
    gp = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
    edges = _grid_edges(2, 4)
    return make_instance(4, edges, gp, multi=multi, label="k4_grid24"), gp, edges


def _k4_repeated_chain8(
    multi: bool,
) -> tuple[Instance, list[tuple[int, int]], list[tuple[int, int]]]:
    """K4 all-pairs on 8-node chain executed twice; round-2 depends on round-1 via direct-predecessor DAG."""
    k4_pairs = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
    gp = (
        k4_pairs + k4_pairs
    )  # 12 gates; _compute_direct_predecessors enforces round ordering
    edges = _line_edges(8)
    return (
        make_instance(4, edges, gp, multi=multi, label="k4_repeated_chain8"),
        gp,
        edges,
    )


def _rand_dag_n4_deep(seed: int, n_gates: int = 15):
    """Factory: deep random CRZ DAG on n=4, chain-8, with n_gates gates (repetitions allowed)."""

    def builder(
        multi: bool,
    ) -> tuple[Instance, list[tuple[int, int]], list[tuple[int, int]]]:
        import random

        rng = random.Random(seed)
        k4_pairs = [(i, j) for i in range(4) for j in range(i + 1, 4)]
        gp = [k4_pairs[rng.randrange(6)] for _ in range(n_gates)]
        edges = _line_edges(8)
        label = f"rand_dag_n4_deep_s{seed}_chain8"
        return make_instance(4, edges, gp, multi=multi, label=label), gp, edges

    return builder


def _k5_chain10(
    multi: bool,
) -> tuple[Instance, list[tuple[int, int]], list[tuple[int, int]]]:
    """K5 all-pairs CRZ on 10-node chain (tight: n_phys=10, n_rails=10).

    By the edge-counting argument: chain-10 has 9 edges; K5 needs 10 qubit-pair
    supports; each chain edge supports exactly 1 qubit pair (bijection of rails to
    nodes). Hence S_multi_opt >= 1 is a theorem for this instance.
    """
    gp = [(i, j) for i in range(5) for j in range(i + 1, 5)]  # 10 pairs
    edges = _line_edges(10)
    return make_instance(5, edges, gp, multi=multi, label="k5_chain10"), gp, edges


def _rand_dag_n5_chain10(
    multi: bool,
) -> tuple[Instance, list[tuple[int, int]], list[tuple[int, int]]]:
    """Random 8-gate CRZ DAG on 5 logical qubits, seed=42, chain-10."""
    import random

    rng = random.Random(42)
    k5_pairs = [(i, j) for i in range(5) for j in range(i + 1, 5)]  # 10 pairs
    rng.shuffle(k5_pairs)
    gp = k5_pairs[:8]  # 8 of 10 K5 pairs
    edges = _line_edges(10)
    return (
        make_instance(5, edges, gp, multi=multi, label="rand_dag_n5_s42_chain10"),
        gp,
        edges,
    )


def _k5_grid25(
    multi: bool,
) -> tuple[Instance, list[tuple[int, int]], list[tuple[int, int]]]:
    """K5 all-pairs CRZ on 2x5 grid (10 nodes, 13 edges). Grid has more slack than chain."""
    gp = [(i, j) for i in range(5) for j in range(i + 1, 5)]  # 10 pairs
    edges = _grid_edges(2, 5)
    return make_instance(5, edges, gp, multi=multi, label="k5_grid25"), gp, edges


def _k4_chain10_spare(
    multi: bool,
) -> tuple[Instance, list[tuple[int, int]], list[tuple[int, int]]]:
    """K4 on 10-node chain with one spare pair (n_phys=10, n_rails=8 = 2*4).

    Matches the main experiment's n+1-spare-pair convention for n=4.
    Seeding enumerates P(10,8) = 1,814,400 injections.
    """
    gp = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
    edges = _line_edges(10)
    return make_instance(4, edges, gp, multi=multi, label="k4_chain10_spare"), gp, edges


def _k4_grid25_spare(
    multi: bool,
) -> tuple[Instance, list[tuple[int, int]], list[tuple[int, int]]]:
    """K4 on 2x5 grid with one spare pair (n_phys=10, n_rails=8 = 2*4).

    Matches the main experiment's spare-pair convention on the grid topology.
    """
    gp = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
    edges = _grid_edges(2, 5)
    return make_instance(4, edges, gp, multi=multi, label="k4_grid25_spare"), gp, edges


# Catalog: (name, builder_fn) pairs
INSTANCE_CATALOG = [
    # n=3 baselines on chain-6 and grid-2x3
    ("crz_chain_n3_chain6", _crz_chain_n3),
    ("crz_ring_n3_chain6", _crz_ring_n3),
    ("k3_chain6", _k3),
    ("rand_dag_n3_chain6", _rand_dag_n3),
    ("crz_chain_n3_grid23", _crz_chain_n3_grid),
    ("k3_grid23", _k3_grid),
    # n=4 tight on chain-8 and grid-2x4
    ("crz_chain_n4_chain8", _crz_chain_n4),
    ("k4_chain8", _k4),
    ("rand_dag_n4_chain8", _rand_dag_n4),
    ("crz_chain_n4_grid24", _crz_chain_n4_grid),
    ("k4_grid24", _k4_grid),
    # n=4 deeper on chain-8 (more gates; may expose compiler sub-optimality)
    ("k4_repeated_chain8", _k4_repeated_chain8),
    ("rand_dag_n4_deep_s42_chain8", _rand_dag_n4_deep(42)),
    ("rand_dag_n4_deep_s43_chain8", _rand_dag_n4_deep(43)),
    ("rand_dag_n4_deep_s44_chain8", _rand_dag_n4_deep(44)),
    # n=5 tight on chain-10 and grid-2x5 (K5 provably has S_multi_opt >= 1 on chain)
    ("k5_chain10", _k5_chain10),
    ("rand_dag_n5_s42_chain10", _rand_dag_n5_chain10),
    ("k5_grid25", _k5_grid25),
    # Spare-pair instances (n_phys = 2n+2) matching main-experiment topology convention
    ("k4_chain10_spare", _k4_chain10_spare),
    ("k4_grid25_spare", _k4_grid25_spare),
]


# ---------------------------------------------------------------------------
# Captured fraction helper
# ---------------------------------------------------------------------------


def _captured(s_greedy: int, s_prism: int, s_multi_opt: int) -> str:
    denom = s_greedy - s_multi_opt
    if denom == 0:
        return "undef"
    return f"{(s_greedy - s_prism) / denom:.3f}"


# ---------------------------------------------------------------------------
# Main experiment runner
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse

    import tomllib

    parser = argparse.ArgumentParser(description="X01 exact oracle runner")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--timeout", type=float, default=None, help="Per-instance timeout (s)"
    )
    parser.add_argument("--only", nargs="*", default=[], help="instance=NAME to filter")
    args = parser.parse_args()

    cfg = tomllib.loads(Path(args.config).read_text())
    timeout = args.timeout if args.timeout is not None else cfg.get("timeout_s", 300.0)
    only_set = set(args.only)

    out_path = _REPO / cfg.get("output_jsonl", "artifacts/paper/raw/oracle.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Load completed run IDs for resume
    done_rids: set[str] = set()
    rows: list[dict] = []
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                rows.append(row)
                done_rids.add(row["run_id"])

    seeds: list[int] = cfg.get("compiler_seeds", [0])

    new_rows = []
    for inst_name, builder_fn in INSTANCE_CATALOG:
        if only_set and not any(f in inst_name for f in only_set):
            continue

        rid = run_id("X01", instance=inst_name)
        if rid in done_rids:
            print(f"[skip] {inst_name}")
            continue

        print(f"[run ] {inst_name} ...", flush=True)
        t0 = time.monotonic()

        # Build instances
        inst_multi, gp, edge_list = builder_fn(True)
        inst_single, _, _ = builder_fn(False)

        # Solve multi-realization optimum
        res_multi = solve(inst_multi, timeout=timeout)
        print(
            f"       S_multi_opt={res_multi.swap_count} ({res_multi.status})",
            flush=True,
        )

        # Solve single (default) realization optimum
        res_single = solve(inst_single, timeout=timeout)
        print(
            f"       S_default_opt={res_single.swap_count} ({res_single.status})",
            flush=True,
        )

        # Independent certificate replay (round 2): re-execute the action
        # sequence against the instance and check legality + count.
        replay_ok_multi = replay(inst_multi, res_multi)
        replay_ok_single = replay(inst_single, res_single)
        if not (replay_ok_multi and replay_ok_single):
            print("       HARD FAILURE: certificate replay failed!", flush=True)

        # Run compiler (best over seeds)
        s_greedy = 10**9
        s_prism = 10**9
        for seed in seeds:
            try:
                sg = _run_compiler(
                    gp, inst_multi.n_logical, edge_list, "greedy", seed=seed
                )
                s_greedy = min(s_greedy, sg)
            except Exception as e:
                print(f"       greedy seed={seed} FAIL: {e}", flush=True)
            try:
                sp = _run_compiler(
                    gp, inst_multi.n_logical, edge_list, "prism", seed=seed
                )
                s_prism = min(s_prism, sp)
            except Exception as e:
                print(f"       prism seed={seed} FAIL: {e}", flush=True)
        if s_greedy == 10**9:
            s_greedy = -1
        if s_prism == 10**9:
            s_prism = -1
        print(f"       S_greedy={s_greedy} S_prism={s_prism}", flush=True)

        # Invariant checks
        hard_failure = False
        if res_multi.status == "exact" and res_single.status == "exact":
            if res_multi.swap_count > res_single.swap_count:
                print("       HARD FAILURE: S_multi_opt > S_default_opt!", flush=True)
                hard_failure = True
        if res_multi.status == "exact" and s_prism >= 0:
            if s_prism < res_multi.swap_count:
                print(
                    f"       HARD FAILURE: S_prism={s_prism} < S_multi_opt={res_multi.swap_count}!"
                    " Metric semantics or oracle correctness broken.",
                    flush=True,
                )
                hard_failure = True
        if res_multi.status == "exact" and s_greedy >= 0:
            if s_greedy < res_multi.swap_count:
                print(
                    f"       HARD FAILURE: S_greedy={s_greedy} < S_multi_opt={res_multi.swap_count}!"
                    " Metric semantics or oracle correctness broken.",
                    flush=True,
                )
                hard_failure = True

        row = {
            "run_id": rid,
            "experiment_id": "X01",
            "instance_name": inst_name,
            "n_logical": inst_multi.n_logical,
            "n_phys": inst_multi.n_phys,
            "n_gates": inst_multi.n_gates,
            "edge_list": edge_list,
            "gate_pairs": gp,
            "S_default_opt": res_single.swap_count,
            "S_multi_opt": res_multi.swap_count,
            "S_greedy": s_greedy,
            "S_prism": s_prism,
            "status_single": res_single.status,
            "status_multi": res_multi.status,
            "certified_single": res_single.certified,
            "certified_multi": res_multi.certified,
            "solve_time_single_s": round(res_single.solve_time_s, 3),
            "solve_time_multi_s": round(res_multi.solve_time_s, 3),
            "support_opportunity": (
                res_single.swap_count - res_multi.swap_count
                if res_single.status == "exact" and res_multi.status == "exact"
                else None
            ),
            "greedy_gap": (
                s_greedy - res_multi.swap_count
                if res_multi.status == "exact" and s_greedy >= 0
                else None
            ),
            "prism_gap": (
                s_prism - res_multi.swap_count
                if res_multi.status == "exact" and s_prism >= 0
                else None
            ),
            "captured": (
                _captured(s_greedy, s_prism, res_multi.swap_count)
                if res_multi.status == "exact" and s_greedy >= 0 and s_prism >= 0
                else "n/a"
            ),
            "hard_failure": hard_failure or not (replay_ok_multi and replay_ok_single),
            "replay_ok_multi": replay_ok_multi,
            "replay_ok_single": replay_ok_single,
            "certificate_multi": {
                "init_layout": list(res_multi.init_layout or ()),
                "actions": [list(a) for a in res_multi.actions or ()],
            },
            "certificate_single": {
                "init_layout": list(res_single.init_layout or ()),
                "actions": [list(a) for a in res_single.actions or ()],
            },
            "compiler_seeds": seeds,
            "total_time_s": round(time.monotonic() - t0, 2),
        }
        rows.append(row)
        new_rows.append(row)
        with out_path.open("a") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")

        status_str = "HARD FAILURE" if hard_failure else "ok"
        print(
            f"       opp={row['support_opportunity']} g_gap={row['greedy_gap']}"
            f" p_gap={row['prism_gap']} captured={row['captured']} [{status_str}]",
            flush=True,
        )

    # Print compact table
    _print_table(rows)

    # Write RESULT file
    results_dir = _REPO / "artifacts/paper/results"
    results_dir.mkdir(parents=True, exist_ok=True)
    # Versioned result note: the 07-16 packet file X01_RESULT.md is historical
    # and immutable; post-P-1 reruns write alongside it.
    suffix = "_postp1" if "postp1" in str(out_path.name) else ""
    _write_result(results_dir / f"X01_RESULT{suffix}.md", rows)
    print(f"\nResults written to {out_path} and artifacts/paper/results/X01_RESULT.md")


def _print_table(rows: list[dict]) -> None:
    header = f"{'Instance':<28} {'n_l':>3} {'n_g':>3} {'S_def':>5} {'S_opt':>5} {'S_grd':>5} {'S_prm':>5} {'Opp':>4} {'G_grd':>5} {'G_prm':>5} {'Capt':>6} {'St':>5}"
    print("\n" + header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['instance_name']:<28} {r['n_logical']:>3} {r['n_gates']:>3}"
            f" {r['S_default_opt']:>5} {r['S_multi_opt']:>5}"
            f" {r['S_greedy']:>5} {r['S_prism']:>5}"
            f" {str(r['support_opportunity']):>4} {str(r['greedy_gap']):>5}"
            f" {str(r['prism_gap']):>5} {str(r['captured']):>6}"
            f" {'FAIL' if r.get('hard_failure') else r['status_multi'][:5]:>5}"
        )


def _write_result(path: Path, rows: list[dict]) -> None:
    lines = [
        "# X01 Result: Exact Small-Instance Oracle",
        "",
        "## What was built",
        "",
        "- `scripts/paper/oracle.py`: Dijkstra-based exact routing oracle over states",
        "  (canonical_layout, done_bitmask). Zero-cost closure executes all ready",
        "  gates with adjacent supports before any SWAP expansion. A* lower bound:",
        "  max over ready-blocked gates of max(0, min_support_dist - 1). Rail-exchange",
        "  symmetry canonicalizes layouts for multi-realization instances (all 4 supports",
        "  are symmetric under per-qubit rail swap). Initial layout is joint (all",
        "  injections of n_rails into n_phys nodes seeded at cost 0).",
        "- `tests/test_oracle.py`: unit tests (hand-solvable, one-realization",
        "  equivalence, duplicate-support invariance, monotonicity, replay, brute force).",
        "- `configs/paper/oracle.toml`: experiment configuration.",
        "- `artifacts/paper/raw/oracle.jsonl`: raw per-instance rows.",
        "",
        "Compiler runs use `_DualRailLocalInit` (local_init=True) to suppress the",
        "co-location herald CRZ(pi), which would otherwise add init-routing SWAPs not",
        "counted by the oracle. This makes S_greedy and S_prism comparable to S_multi_opt.",
        "",
        "Default realization: DualRail.crz default_index=2 = (ra=1, rb=0), i.e., rail 1",
        "of the control qubit adjacent to rail 0 of the target qubit.",
        "",
        "## Instance table",
        "",
        "Columns: S_def_opt = single-realization optimum, S_multi_opt = multi-realization",
        "optimum, S_greedy/S_prism = compiler results (min over compiler seeds),",
        "Opp = S_def_opt - S_multi_opt, G_greedy/G_prism = gap to optimum,",
        "Captured = (S_greedy - S_prism) / (S_greedy - S_multi_opt) [undef if denom=0].",
        "",
    ]

    # Table header
    hdr = f"| {'Instance':<28} | nl | ng | S_def | S_opt | S_grd | S_prm | Opp | G_grd | G_prm | Captured | Status |"
    sep = f"| {'-' * 28} | -- | -- | ----- | ----- | ----- | ----- | --- | ----- | ----- | -------- | ------ |"
    lines.append(hdr)
    lines.append(sep)
    for r in rows:
        fail = "FAIL" if r.get("hard_failure") else ""
        status = fail if fail else r["status_multi"][:5]
        lines.append(
            f"| {r['instance_name']:<28} | {r['n_logical']:>2} | {r['n_gates']:>2}"
            f" | {r['S_default_opt']:>5} | {r['S_multi_opt']:>5}"
            f" | {r['S_greedy']:>5} | {r['S_prism']:>5}"
            f" | {str(r['support_opportunity']):>3}"
            f" | {str(r['greedy_gap']):>5} | {str(r['prism_gap']):>5}"
            f" | {str(r['captured']):>8} | {status:<6} |"
        )

    lines += [
        "",
        "## Commands",
        "",
        "```",
        ".venv/bin/python scripts/paper/oracle.py --config configs/paper/oracle.toml",
        ".venv/bin/pytest -q tests/test_oracle.py",
        "```",
        "",
        "## What the numbers permit and do NOT permit the paper to claim",
        "",
    ]

    # Generate claim analysis from actual data
    certified_rows = [
        r for r in rows if r["status_multi"] == "exact" and r["certified_multi"]
    ]
    opp_nonzero = [
        r
        for r in certified_rows
        if r.get("support_opportunity") and r["support_opportunity"] > 0
    ]
    prism_gap_zero = [r for r in certified_rows if r.get("prism_gap") == 0]
    prism_better_greedy = [r for r in certified_rows if r["S_prism"] < r["S_greedy"]]
    hard_fails = [r for r in rows if r.get("hard_failure")]

    lines += [
        f"Certified-exact instances: {len(certified_rows)} of {len(rows)} total.",
        "",
        "**PERMITS:**",
    ]
    if opp_nonzero:
        avg_opp = sum(r["support_opportunity"] for r in opp_nonzero) / len(opp_nonzero)
        lines.append(
            f"- Support opportunity is real: {len(opp_nonzero)}/{len(certified_rows)} certified instances"
            f" show S_def_opt > S_multi_opt (avg opp = {avg_opp:.2f} SWAPs). Multi-realization IR"
            " provably reduces optimal routing overhead on these instances."
        )
    if prism_gap_zero:
        lines.append(
            f"- PRISM achieves the multi-realization optimum on {len(prism_gap_zero)}"
            f"/{len(certified_rows)} certified instances (zero prism gap)."
        )
    if prism_better_greedy:
        avg_cap = []
        for r in prism_better_greedy:
            denom = r["S_greedy"] - r["S_multi_opt"]
            if denom > 0:
                avg_cap.append((r["S_greedy"] - r["S_prism"]) / denom)
        cap_str = (
            f" (avg captured fraction = {sum(avg_cap) / len(avg_cap):.3f})"
            if avg_cap
            else ""
        )
        lines.append(
            f"- PRISM beats greedy on {len(prism_better_greedy)}/{len(certified_rows)} instances{cap_str}."
        )

    lines += [
        "",
        "**DOES NOT PERMIT:**",
        "- Claims about uncertified (timeout/bound) instances -- those are upper bounds only.",
        "- Extrapolation to larger n without new oracle runs.",
        "- Claims that PRISM is optimal in general (gap may be non-zero on other instances).",
        "- Claims about topologies not in this table.",
    ]
    if hard_fails:
        lines += [
            "",
            f"**HARD FAILURES ({len(hard_fails)} instances):**",
        ]
        for r in hard_fails:
            lines.append(
                f"- {r['instance_name']}: S_prism={r['S_prism']} < S_multi_opt={r['S_multi_opt']}"
            )
        lines.append(
            "This indicates a metric semantics mismatch or oracle bug. Do not use these results in the paper."
        )
    else:
        lines.append("")
        lines.append(
            "No hard failures detected. S_multi_opt <= S_default_opt and S_multi_opt <= S_prism hold on all certified instances."
        )

    lines += [
        "",
        "## Uncertainties",
        "",
        "- Compiler runs use a single seed (or min over a small set); the reported S_greedy/S_prism",
        "  are not the true compiler optimum over all seeds. Running more seeds would tighten gaps.",
        "- The oracle uses tight topologies (n_phys = n_rails = 2*n_logical), not the full",
        "  n+1-spare-pair topologies used in the main experiments. Opportunity and gaps may differ",
        "  on larger topologies.",
        "- Init SWAPs are excluded via local_init=True. If the main experiment uses the default",
        "  local_init=False, the comparison must account for init overhead separately.",
    ]

    path.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
