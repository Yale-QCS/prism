"""Executable contract for the routing pass.

These tests separate the outer Python search from the Rust router and lock
the details the search depends on.
"""

from types import SimpleNamespace

from qiskit import QuantumCircuit, QuantumRegister
from qiskit.circuit.library import CRZGate
from qiskit.passmanager import PropertySet
from qiskit.transpiler import CouplingMap

from prism import routing as prism_module
from prism.encodings import DualRail
from prism.ir import MultiRealization, MultiRealizationInstruction, MultiRealizationOp
from prism.routing import PrismRouting, SearchBudget, score


def _program(n_logical: int, data) -> MultiRealization:
    return MultiRealization(
        enc=DualRail,
        qregs=[QuantumRegister(2, f"q{i}") for i in range(n_logical)],
        cregs=[],
        clbits=[],
        data=list(data),
        logical_output_permutation=tuple(range(n_logical)),
    )


def test_default_search_budget_is_explicit():
    policy = PrismRouting(CouplingMap.from_line(4))

    assert policy.budget == SearchBudget(40, 16, 40, "swaps")
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
        CouplingMap.from_line(2),
        seed=5,
        budget=SearchBudget(layout_starts=2, refinement_iterations=3, swap_trials=20),
    )
    policy.property_set = PropertySet()
    ctx = SimpleNamespace(n_phys=2, candidates=[])
    calls = {}
    starts = [(5, [0, 1]), (6, [1, 0]), (7, [0, 1]), (8, [0, 1]), (9, [1, 0])]
    monkeypatch.setattr(policy, "_precompute", lambda _ir: ctx)
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
    monkeypatch.setattr(policy, "_replay", lambda _events, _ctx, _v2p: ([], {}))
    monkeypatch.setattr(MultiRealization, "to_circuit", lambda self: self)
    monkeypatch.setattr(
        prism_module, "score", lambda placed, _obj: (placed.placement.initial[0], 0, 0)
    )

    placed = policy.run(_program(0, []))

    assert calls["starts"] == starts
    assert calls["it"] == 3 and calls["trials"] == 20
    assert calls["fwd"] == ("flat", ctx) and calls["rev"] == ("flat", ctx)
    assert placed.placement.initial == (0, 1)  # the first start with the lowest score
    assert policy.property_set["online_n_swaps"] == 5


def test_dependency_graph_uses_union_of_candidate_wires():
    """An op with several candidates depends conservatively on every wire any candidate uses."""
    on_01 = QuantumCircuit(3)
    on_01.cx(0, 1)
    on_02 = QuantumCircuit(3)
    on_02.cx(0, 2)
    on_1 = QuantumCircuit(1)
    on_1.x(0)
    prog = _program(
        2,
        [
            MultiRealizationInstruction(
                MultiRealizationOp("choice", (on_01, on_02)), (0, 1, 2)
            ),
            MultiRealizationInstruction(MultiRealizationOp("x", (on_1,)), (1,)),
        ],
    )
    ctx = PrismRouting(CouplingMap.from_line(4))._precompute(prog)

    assert ctx.virt_pairs[0] == (((0, 1),), ((0, 2),))
    assert ctx.virts_used == [frozenset({0, 1, 2}), frozenset({1})]
    assert ctx.succ == [[1], []]
    assert ctx.pred_count == [0, 1]


def test_available_crz_commits_atomically_and_emits_complete_candidate():
    """An available CRZ produces one atomic commit, including its local RZ."""
    prog = _program(
        2, [MultiRealizationInstruction(DualRail.crz(CRZGate(0.3)), (0, 1, 2, 3))]
    )
    cmap = CouplingMap.from_line(4)
    policy = PrismRouting(cmap)
    ctx = policy._precompute(prog)
    flat = policy._flatten_ctx(ctx)
    target = prism_module.RoutingTarget.from_coupling_list(
        list(cmap.get_edges()), ctx.n_phys
    )
    [(events, final_v2p, n_swaps, _refined)] = prism_module.prism_layout_and_routing(
        flat, flat, target, policy._make_heuristic(4), [(0, [0, 1, 2, 3])], 0, 1
    )

    # Candidate 2 is the encoding default and uses the adjacent pair (1, 2).
    assert events == [(prism_module._COMMIT, 0, 2)]
    assert final_v2p == [0, 1, 2, 3]
    assert n_swaps == 0

    data, chosen = policy._replay(events, ctx, [0, 1, 2, 3])
    assert chosen == {0: 2} and data[0].operation.choice == 2
    assert _program(2, data).to_circuit().count_ops() == {"crz": 1, "rz": 1}
