"""Round-3 fairness invariants: controlled arms, budgets, binding, connectivity.

Covers budget parity, candidate expectations, route connectivity, seed
reproducibility, and no CPU-derived trials.
"""

import os
import re
from pathlib import Path

import numpy as np
import pytest
from qiskit import QuantumCircuit
from qiskit.circuit.library import QFTGate
from qiskit.converters import circuit_to_dag, dag_to_circuit
from qiskit.transpiler import CouplingMap, PassManager, StagedPassManager

from marabbecca.encodings import DualRail
from marabbecca.lowering.commit import ApplyCommits, SearchBudget
from marabbecca.lowering.commit_policies.prism_routing import PrismRouting
from marabbecca.lowering.expansion import LowerExpansion
from marabbecca.lowering.ir import LoweredOp
from marabbecca.staged_pms import build_pm

SRC = Path(__file__).resolve().parents[1] / "src" / "marabbecca"

CONTROL_BUDGET = SearchBudget(
    layout_starts=4,
    refinement_iterations=2,
    heuristic_config="qiskit_sabre",
    tie_break="default",
)


def _qft_qc(n=4):
    qc = QuantumCircuit(n)
    qc.append(QFTGate(n), range(n))
    return qc


def _lowered_dag(qc, enc=DualRail):
    return circuit_to_dag(
        PassManager([LowerExpansion(enc=enc)]).run(enc.logical_pm().run(qc))
    )


def _prism_pm(cm, seed, budget):
    lowering = [
        LowerExpansion(enc=DualRail),
        PrismRouting(
            cm,
            enc=DualRail,
            seed=seed,
            objective=budget.objective,
            num_trials=budget.layout_starts,
            max_iterations=budget.refinement_iterations,
            swap_trials=budget.prism_swap_trials,
            heuristic_config=budget.heuristic_config,
            tie_break=budget.tie_break,
            start_mode="legacy_identity",
        ),
        ApplyCommits(),
    ]
    return StagedPassManager(
        stages=["logical", "lowering", "physical"],
        logical=DualRail.logical_pm(),
        lowering=PassManager(lowering),
        physical=DualRail.physical_pm(cm, seed=seed, use_lowering_route=True),
    )


# ---------------------------------------------------------------------------
# SearchBudget: explicit, validated, exact accounting
# ---------------------------------------------------------------------------


def test_search_budget_standard_values_are_fixed_constants():
    b = SearchBudget()
    assert (b.layout_starts, b.refinement_iterations, b.prism_swap_trials) == (
        20,
        4,
        20,
    )
    assert (b.objective, b.heuristic_config, b.tie_break) == (
        "swaps",
        "qiskit_sabre",
        "default",
    )


def test_tuned_load_configuration_remains_available_by_request():
    b = SearchBudget(heuristic_config="tuned", tie_break="load")
    assert (b.heuristic_config, b.tie_break) == ("tuned", "load")


def test_paper_arms_share_qiskit_style_schedule_and_retain_its_route():
    qc = _qft_qc(4)
    cm = CouplingMap.from_grid(2, 4)
    budget = SearchBudget(
        layout_starts=2,
        refinement_iterations=1,
        prism_swap_trials=2,
    )
    traces = {}
    for strategy in ("greedy", "prism"):
        pm = build_pm(
            cm,
            enc=DualRail,
            strategy=strategy,
            seed=11,
            budget=budget,
        )
        pm.run(qc)
        traces[strategy] = pm.property_set["search_trace"]

    greedy = traces["greedy"]
    retained = traces["prism"]
    for field in (
        "heuristic_repr",
        "num_trials",
        "start_mode",
        "standard_layouts",
        "final_swap_trials",
        "refinement_swap_trials",
        "max_iterations",
        "route_calls",
    ):
        assert greedy[field] == retained[field], field
    greedy_pool = [(s["kind"], s["seed"], s["initial_v2p"]) for s in greedy["starts"]]
    retained_pool = [
        (s["kind"], s["seed"], s["initial_v2p"]) for s in retained["starts"]
    ]
    assert greedy_pool == retained_pool
    assert greedy["binding_mode"] == "greedy"
    assert retained["binding_mode"] == "retained"


def test_duration_model_uses_liu_beamsplitter_duration():
    from marabbecca.synthesis.rswap import RSwapGate
    from marabbecca.utils.metrics import physical_duration

    fractional = QuantumCircuit(2)
    fractional.append(RSwapGate(np.pi / 2), [0, 1])
    full = QuantumCircuit(2)
    full.swap(0, 1)
    assert physical_duration(fractional) == 200.0
    assert physical_duration(full) == 200.0


def test_synthetic_preparation_is_free_in_program_body_metrics():
    from marabbecca.utils.metrics import (
        active_gate_count,
        physical_depth,
        physical_duration,
    )

    preparation = DualRail.initialize()
    assert preparation.size() == 2
    assert preparation.count_ops().get("joint_herald") == 1
    assert active_gate_count(preparation) == 0
    assert physical_depth(preparation) == 0
    assert physical_duration(preparation) == 0.0


def test_search_budget_is_frozen_and_validated():
    b = SearchBudget()
    with pytest.raises(Exception):
        b.layout_starts = 5
    with pytest.raises(ValueError):
        SearchBudget(objective="best")
    with pytest.raises(ValueError):
        SearchBudget(heuristic_config="fastest")
    with pytest.raises(ValueError):
        SearchBudget(tie_break="random")
    with pytest.raises(ValueError):
        SearchBudget(layout_starts=0)


def test_budget_objective_conflict_raises():
    cm = CouplingMap.from_line(8)
    with pytest.raises(ValueError):
        build_pm(
            cm,
            enc=DualRail,
            strategy="prism",
            objective="swaps",
            budget=SearchBudget(objective="depth"),
        )


def test_implicit_budget_propagates_objective_to_both_practical_arms():
    qc = _qft_qc(3)
    cm = CouplingMap.from_grid(2, 3)
    for strategy in ("greedy", "prism"):
        pm = build_pm(
            cm,
            enc=DualRail,
            strategy=strategy,
            seed=2,
            objective="duration",
        )
        pm.run(qc)
        assert pm.property_set["search_trace"]["objective"] == "duration", strategy


def test_no_cpu_derived_trials_in_sources_or_env():
    assert not os.environ.get("QISKIT_SABRE_ALL_THREADS"), (
        "QISKIT_SABRE_ALL_THREADS must be unset: preset trial counts would "
        "become machine-dependent"
    )
    from qiskit import user_config

    assert not user_config.get_config().get("sabre_all_threads"), (
        "Qiskit user config sabre_all_threads must be false/unset"
    )
    for rel in (
        "lowering/commit.py",
        "lowering/commit_policies/prism_routing.py",
        "staged_pms.py",
    ):
        code_lines = [
            line
            for line in (SRC / rel).read_text().splitlines()
            if not line.lstrip().startswith("#")
        ]
        assert not re.search(
            r"cpu_count|default_num_processes|CPU_COUNT", "\n".join(code_lines)
        ), rel


def test_physical_stage_o3_swap_trials_pinned_to_20():
    from qiskit.transpiler.passes import SabreSwap

    pm = DualRail.physical_pm(CouplingMap.from_line(8), seed=0)

    found = []

    def _walk(task):
        if isinstance(task, SabreSwap):
            found.append(task)
        for attr in ("tasks", "passes"):
            for sub in getattr(task, attr, ()) or ():
                _walk(sub)

    for stage in pm.to_flow_controller().tasks:
        _walk(stage)
    assert found, "no SabreSwap in the physical preset"
    assert all(s.trials == 20 for s in found)


def test_prism_fixed_seed_reproduces_full_trace():
    qc = _qft_qc(4)
    cm = CouplingMap.from_grid(2, 4)

    def _strip_times(obj):
        if isinstance(obj, dict):
            return {
                k: _strip_times(v)
                for k, v in obj.items()
                if k not in ("trial_s", "wall_s")
            }
        if isinstance(obj, list):
            return [_strip_times(v) for v in obj]
        return obj

    traces = []
    for _ in range(2):
        pm = _prism_pm(cm, 9, CONTROL_BUDGET)
        pm.run(qc)
        traces.append(_strip_times(pm.property_set["search_trace"]))
    assert traces[0] == traces[1]


def test_live_arm_sees_expected_candidate_sets():
    dag = _lowered_dag(_qft_qc(4))
    decision_sizes = [
        len(n.op.realizations)
        for n in dag.topological_op_nodes()
        if isinstance(n.op, LoweredOp) and n.op.is_decision
    ]
    assert decision_sizes, "qft lowering produced no decision ops"
    assert 4 in decision_sizes, "expected 4-candidate CRZ decisions"
    assert all(s >= 2 for s in decision_sizes)


def test_prism_native_route_satisfies_connectivity():
    qc = _qft_qc(4)
    cm = CouplingMap.from_grid(2, 4)
    dag = _lowered_dag(qc)
    result = PrismRouting(cm, enc=DualRail, seed=5).commit(
        circuit_to_dag(dag_to_circuit(dag))
    )
    edges = {tuple(sorted(e)) for e in cm.get_edges()}
    routed = dag_to_circuit(result.routed_dag)
    for inst in routed.data:
        if len(inst.qubits) == 2:
            pair = tuple(sorted(routed.find_bit(q).index for q in inst.qubits))
            assert pair in edges
