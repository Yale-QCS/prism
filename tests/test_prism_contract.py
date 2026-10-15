"""Executable contract for the CRZ routing path.

These tests separate the outer Python search from the Rust router and lock
the details the search depends on.
"""

from types import SimpleNamespace

from qiskit import QuantumCircuit, QuantumRegister
from qiskit.circuit.library import CRZGate
from qiskit.dagcircuit import DAGCircuit
from qiskit.transpiler import CouplingMap

from prism.encodings import DualRail
from prism.lowering.commit import CommitResult
from prism.lowering.commit_policies import prism_routing as prism_module
from prism.lowering.commit_policies.prism_routing import PrismRouting, score
from prism.lowering.ir import LoweredOp


def test_default_search_budget_is_explicit():
    policy = PrismRouting(CouplingMap.from_line(4), enc=DualRail)

    assert policy.num_trials == 20
    assert policy.num_starts == 23
    assert policy.max_iterations == 4
    assert policy.swap_trials == 20
    assert policy.PHYS_LOAD_DECAY == 0.9
    assert repr(policy._make_heuristic(4)) == repr(policy._make_heuristic(4))


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


def test_outer_search_hands_every_start_to_the_kernel(monkeypatch):
    """Starts and seeds go to ``prism_layout_and_routing``; the best final route wins by objective."""
    policy = PrismRouting(
        CouplingMap.from_line(2), enc=DualRail, seed=5, num_trials=2, max_iterations=3
    )
    ctx = SimpleNamespace(n_phys=2)
    calls = {}
    starts = [
        ("random", 5, [0, 1]),
        ("random", 6, [1, 0]),
        ("dense", 7, [0, 1]),
        ("identity", 8, [0, 1]),
        ("reverse", 9, [1, 0]),
    ]
    monkeypatch.setattr(
        prism_module.disjoint_utils,
        "require_layout_isolated_to_component",
        lambda *_: None,
    )
    monkeypatch.setattr(policy, "_precompute", lambda _dag: ctx)
    monkeypatch.setattr(policy, "_reversed_ctx", lambda c: c)
    monkeypatch.setattr(policy, "_flatten_ctx", lambda c: ("flat", c))
    monkeypatch.setattr(policy, "_starting_layouts", lambda _ctx, _seed: starts)

    def fake_kernel(
        fwd, rev, _target, _heuristic, kernel_starts, max_iterations, swap_trials
    ):
        calls.update(
            fwd=fwd,
            rev=rev,
            starts=kernel_starts,
            it=max_iterations,
            trials=swap_trials,
        )
        # final n_swaps = seed so the lowest seed (first random start) must win
        return [([], v2p, seed, v2p) for seed, v2p in kernel_starts]

    monkeypatch.setattr(prism_module, "prism_layout_and_routing", fake_kernel)
    monkeypatch.setattr(
        policy, "_emit_circuit_from_trace", lambda trace, _ctx, _v2p: trace
    )
    monkeypatch.setattr(prism_module, "score", lambda trace, _obj: (trace[2], 0, 0))
    monkeypatch.setattr(policy, "_trace_to_payload", lambda _t, _c: {"n_swaps": 0})
    built = {}

    def fake_build(_dag, _ctx, out, _payload, refined):
        built.update(out=out, refined=refined)
        return CommitResult(choices=())

    monkeypatch.setattr(policy, "_build_result", fake_build)
    policy.commit(DAGCircuit())

    assert calls["starts"] == [
        (5, [0, 1]),
        (6, [1, 0]),
        (7, [0, 1]),
        (8, [0, 1]),
        (9, [1, 0]),
    ]
    assert calls["it"] == 3 and calls["trials"] == 20
    assert calls["fwd"] == ("flat", ctx) and calls["rev"] == ("flat", ctx)
    assert built["out"][2] == 5 and built["refined"] == [0, 1]


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
    router = policy._make_router(ctx)
    trace = router(policy._flatten_ctx(ctx), [0, 1, 2, 3], 0, 1)
    events, final_v2p, n_swaps = trace

    # Candidate 2 is the encoding default and uses the adjacent pair (1, 2).
    assert events == [(policy._EVENT_COMMIT, 0, 2)]
    assert final_v2p == [0, 1, 2, 3]
    assert n_swaps == 0

    emitted = policy._emit_circuit_from_trace(trace, ctx, [0, 1, 2, 3])
    assert emitted.count_ops() == {"crz": 1, "rz": 1}
