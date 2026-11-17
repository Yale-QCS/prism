"""Executable contract for the CRZ path described by the PRISM paper.

These tests deliberately separate the outer Python search from the Rust
single-pass router.  They lock the details needed to describe the evaluated
algorithm without relying on comments or paper pseudocode.
"""

import pytest
from qiskit import QuantumCircuit, QuantumRegister
from qiskit.circuit.library import CRZGate
from qiskit.dagcircuit import DAGCircuit
from qiskit.transpiler import CouplingMap

from marabbecca.encodings import DualRail
from marabbecca.lowering.commit import CommitResult, SearchBudget
from marabbecca.lowering.commit_policies import prism_routing as prism_module
from marabbecca.lowering.commit_policies.prism_routing import PrismRouting, score
from marabbecca.lowering.ir import LoweredOp
from marabbecca.staged_pms import build_pm


def test_default_search_budget_is_explicit():
    policy = PrismRouting(CouplingMap.from_line(4), enc=DualRail)

    assert policy.num_trials == 20
    assert policy.num_starts == 23
    assert policy.max_iterations == 4
    assert policy.swap_trials == 20
    assert policy.start_mode == "qiskit_o3"
    assert policy.binding_mode == "retained"
    assert policy.EXTENDED_SET_SIZE == 40
    assert policy.EXTENDED_SET_WEIGHT == 0.5
    assert policy.DECAY_INCREMENT == 0.01
    assert policy.DECAY_RESET_INTERVAL == 5
    assert policy.PHYS_LOAD_DECAY == 0.9


def test_swap_objective_uses_depth_before_gate_count(monkeypatch):
    """Equal-SWAP routes are selected by depth, then active gate count."""

    class DummyCircuit:
        @staticmethod
        def count_ops():
            return {"swap": 3}

        @staticmethod
        def size():
            return 11

    monkeypatch.setattr(prism_module, "physical_depth", lambda _qc: 7)
    monkeypatch.setattr(prism_module, "active_gate_count", lambda _qc: 9)

    assert score(DummyCircuit(), "swaps") == (3, 7, 9)


@pytest.mark.parametrize("strategy", ["greedy", "prism"])
def test_custom_objective_selects_the_emitted_route(strategy):
    """Both compiler arms select from the same final candidates using the callback."""
    qc = QuantumCircuit(4)
    for a, b in [(0, 3), (1, 2), (0, 2), (1, 3)]:
        qc.crz(0.3, a, b)
    candidates = []

    def cost(candidate):
        # Deliberately prefer more SWAPs to distinguish this from default selection.
        value = -float(candidate.count_ops().get("swap", 0))
        candidates.append(value)
        return value

    pm = build_pm(
        CouplingMap.from_line(8),
        enc=DualRail,
        strategy=strategy,
        seed=11,
        objective="custom",
        route_score=cost,
        budget=SearchBudget(
            objective="custom",
            layout_starts=2,
            refinement_iterations=1,
            prism_swap_trials=2,
        ),
    )
    result = pm.run(qc)
    values = candidates.copy()
    trace = pm.property_set["search_trace"]
    assert len(values) == len(trace["starts"]) == 5
    assert len(set(values)) > 1
    assert cost(result) == min(values)
    assert [entry["final_score"][0] for entry in trace["starts"]] == values


def test_custom_objective_requires_explicit_callback():
    cm = CouplingMap.from_line(4)
    for factory in (build_pm, PrismRouting):
        with pytest.raises(ValueError, match="requires route_score"):
            factory(cm, enc=DualRail, objective="custom")
        with pytest.raises(ValueError, match="other objectives"):
            factory(cm, enc=DualRail, route_score=lambda qc: qc.size())
    with pytest.raises(ValueError, match="no built-in score"):
        score(QuantumCircuit(1), "custom")


def test_outer_search_matches_qiskit_refinement_then_final_route(
    monkeypatch,
):
    """Each start refines forward/backward, then scores one final route."""
    policy = PrismRouting(
        CouplingMap.from_line(2),
        enc=DualRail,
        seed=5,
        num_trials=2,
        max_iterations=3,
    )
    dag = DAGCircuit()
    fwd_ctx = object()
    rev_ctx = object()
    route_calls = []
    scored = []
    built = {}

    monkeypatch.setattr(
        prism_module.disjoint_utils,
        "require_layout_isolated_to_component",
        lambda *_: None,
    )
    monkeypatch.setattr(policy, "_precompute", lambda _dag: fwd_ctx)
    monkeypatch.setattr(policy, "_reversed_ctx", lambda _ctx: rev_ctx)
    starts = [
        ("random", 5, [0]),
        ("random", 6, [1]),
        ("dense", 7, [2]),
        ("identity", 8, [3]),
        ("reverse", 9, [4]),
    ]
    monkeypatch.setattr(policy, "_starting_layouts", lambda _ctx, _seed: starts)

    def fake_route(ctx, v2p, seed, swap_trials):
        route_calls.append((ctx, tuple(v2p), seed, swap_trials))
        return ([], [seed], 0), ctx, None

    monkeypatch.setattr(policy, "_route", fake_route)
    monkeypatch.setattr(
        policy, "_emit_circuit_from_trace", lambda trace, _ctx, _v2p: trace
    )

    def fake_score(trace, objective, *_):
        scored.append((trace[1][0], objective))
        return (trace[1][0], 0, 0)

    monkeypatch.setattr(prism_module, "score", fake_score)
    monkeypatch.setattr(
        policy,
        "_trace_to_payload",
        lambda _trace, _ctx: {"chosen_realizations": {}, "n_swaps": 0},
    )

    def fake_build(_dag, _ctx, out, _payload, initial_v2p):
        built.update(out=out, initial_v2p=initial_v2p)
        return CommitResult(choices=())

    monkeypatch.setattr(policy, "_build_result", fake_build)

    result = policy.commit(dag)

    assert len(route_calls) == 5 * (3 * 2 + 1)
    assert (
        sum(ctx is fwd_ctx and trials == 1 for ctx, _, _, trials in route_calls) == 15
    )
    assert (
        sum(ctx is rev_ctx and trials == 1 for ctx, _, _, trials in route_calls) == 15
    )
    assert (
        sum(ctx is fwd_ctx and trials == 20 for ctx, _, _, trials in route_calls) == 5
    )
    assert len(scored) == 5
    assert all(objective == "swaps" for _, objective in scored)

    # The first random start has the lowest final-route seed and score.
    assert built["out"][1] == [5006]
    assert built["initial_v2p"] == [5005]
    assert result.search_trace["n_failed_starts"] == 0


def test_dependency_graph_uses_union_of_candidate_wires():
    """A decision node depends conservatively on every wire any candidate uses."""
    qreg = QuantumRegister(3, "q")
    dag = DAGCircuit()
    dag.add_qreg(qreg)

    on_01 = QuantumCircuit(3)
    on_01.cx(0, 1)
    on_02 = QuantumCircuit(3)
    on_02.cx(0, 2)
    dag.apply_operation_back(
        LoweredOp.decision((on_01, on_02), name="choice"),
        list(qreg),
    )

    on_1 = QuantumCircuit(1)
    on_1.x(0)
    dag.apply_operation_back(LoweredOp.fixed(on_1, name="x"), [qreg[1]])

    policy = PrismRouting(CouplingMap.from_line(3), enc=DualRail)
    ctx = policy._precompute(dag)

    assert ctx.virt_pairs[0] == (((0, 1),), ((0, 2),))
    assert ctx.virts_used == [frozenset({0, 1, 2}), frozenset({1})]
    assert ctx.succ == [[1], []]
    assert ctx.pred_count == [0, 1]


def test_greedy_binding_selects_once_under_route_entry_layout():
    """Greedy collapses candidates without changing the boundary dependencies."""
    qreg = QuantumRegister(4, "q")
    dag = DAGCircuit()
    dag.add_qreg(qreg)
    dag.apply_operation_back(DualRail.crz(CRZGate(0.3)), list(qreg))

    policy = PrismRouting(
        CouplingMap.from_line(4),
        enc=DualRail,
        binding_mode="greedy",
    )
    ctx = policy._precompute(dag)

    fixed, choices = policy._greedy_commit_ctx(ctx, [0, 1, 2, 3])
    assert choices == [2]
    assert fixed.virt_pairs == [(((1, 2),),)]
    assert fixed.real_idx_map == [(2,)]
    assert fixed.succ == ctx.succ
    assert fixed.pred_count == ctx.pred_count

    moved, choices = policy._greedy_commit_ctx(ctx, [0, 3, 1, 2])
    assert choices == [0]
    assert moved.virt_pairs == [(((0, 2),),)]


def test_available_crz_commits_atomically_and_emits_complete_candidate():
    """An available CRZ produces one atomic commit, including its local RZ."""
    qreg = QuantumRegister(4, "q")
    dag = DAGCircuit()
    dag.add_qreg(qreg)
    dag.apply_operation_back(DualRail.crz(CRZGate(0.3)), list(qreg))

    policy = PrismRouting(
        CouplingMap.from_line(4),
        enc=DualRail,
        seed=0,
        num_trials=1,
        max_iterations=1,
    )
    ctx = policy._precompute(dag)
    trace, _, _ = policy._route(ctx, [0, 1, 2, 3], 0, 1)
    events, final_v2p, n_swaps = trace

    # Candidate 2 is the encoding default and uses the adjacent pair (1, 2).
    assert events == [(policy._EVENT_COMMIT, 0, 2)]
    assert final_v2p == [0, 1, 2, 3]
    assert n_swaps == 0

    emitted = policy._emit_circuit_from_trace(trace, ctx, [0, 1, 2, 3])
    assert emitted.count_ops() == {"crz": 1, "rz": 1}
