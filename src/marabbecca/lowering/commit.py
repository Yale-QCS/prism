"""Commit-policy abstraction and consumers.

Mirrors Qiskit's ``Layout`` analysis+apply pattern:

    Qiskit:  TrivialLayout / SabreLayout (analysis: sets ``property_set["layout"]``)
             → ApplyLayout (transformation: permutes the DAG by the layout)

    marabbecca: Trivial / Direct / PrismRouting
                (returns a ``CommitResult``; base wires it into property_set)
             → ApplyCommits (transformation: substitutes each ``LoweredOp`` node)

A ``CommitPolicy`` picks one realization per decision op (in
``CommitResult.choices``); ``ApplyCommits`` substitutes them in. A policy
that also routes returns its routed DAG, which replaces the circuit, with
``layout`` and ``final_layout`` set as Qiskit's routing passes leave them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from qiskit.converters import circuit_to_dag
from qiskit.dagcircuit import DAGCircuit
from qiskit.transpiler import Layout, TransformationPass

from marabbecca.lowering.ir import LoweredOp

if TYPE_CHECKING:
    from marabbecca.encodings.base import QubitEncoding


# Effort anchors from the stock O3 preset: SabreLayout(max_iterations=4,
# layout_trials=20, swap_trials=20) and SabreSwap(trials=20). Pinning them
# makes every arm's search effort explicit and reproducible (stock classes
# otherwise default trial counts to ``default_num_processes()``, which is
# machine-dependent). The paper comparison runs early-commitment and
# retained-set inputs through one shared Qiskit-style layout-and-routing
# schedule and validates their configuration cell by cell.
SABRE_TRIALS = 20
SABRE_ITERATIONS = 4


@dataclass(frozen=True)
class SearchBudget:
    """Search effort for the ``greedy`` and ``prism`` strategies.

    Every knob is a fixed value here — nothing derives from CPU count. Both
    strategies use ``layout_starts`` random layouts plus Qiskit's dense,
    identity, and reverse layouts, run ``refinement_iterations`` alternating
    forward/backward calls, and use ``prism_swap_trials`` trials for each
    final route. Trial ``t`` uses seed ``base + t`` (the identity trial uses
    ``base + layout_starts``). The defaults are the stock O3 effort; the
    paper's evaluation passes 40/16/40 with ``load`` tie-breaking explicitly.
    ``logical`` takes only the three counts, for its quotient-graph SABRE.
    """

    layout_starts: int = SABRE_TRIALS
    refinement_iterations: int = SABRE_ITERATIONS
    prism_swap_trials: int = SABRE_TRIALS
    objective: str = "swaps"
    heuristic_config: str = "qiskit_sabre"
    tie_break: str = "default"

    def __post_init__(self) -> None:
        if self.objective not in {
            "swaps",
            "depth",
            "gates",
            "duration",
            "error",
            "custom",
        }:
            raise ValueError(f"unknown objective {self.objective!r}")
        if self.heuristic_config not in {"tuned", "qiskit_sabre"}:
            raise ValueError(f"unknown heuristic_config {self.heuristic_config!r}")
        if self.tie_break not in {"load", "default"}:
            raise ValueError(f"unknown tie_break {self.tie_break!r}")
        for field in ("layout_starts", "refinement_iterations", "prism_swap_trials"):
            if getattr(self, field) < 1:
                raise ValueError(f"{field} must be >= 1, got {getattr(self, field)}")


@dataclass(frozen=True)
class CommitResult:
    """A commit policy's result.

    - ``choices``: realization picks for ``ApplyCommits``, in decision-op
      topological order (fixed ops omitted).
    - ``layout``: if set, written to ``property_set["layout"]``; the physical
      stage's layout search is gated on ``layout is None``.
    - ``routed_dag``: if set, a routed DAG in physical coordinates that
      replaces the circuit; ``routed_final_layout`` is its output permutation
      and is written to ``property_set["final_layout"]``.
    - ``n_swaps``: SWAP instructions this policy inserted for routing, written
      to ``property_set["routing_swaps"]``.
    - ``search_trace``: JSON-serializable search instrumentation, written to
      ``property_set["search_trace"]`` if set.
    """

    choices: tuple[int, ...]
    layout: Layout | None = None
    routed_dag: DAGCircuit | None = None
    routed_final_layout: Layout | None = None
    n_swaps: int = 0
    search_trace: dict | None = None


class CommitPolicy(TransformationPass, ABC):
    """Pick realizations for ``LoweredOp`` nodes; optionally set the layout or return a routed DAG.

    Subclasses implement ``commit(dag) -> CommitResult``; this base class
    wires the result into ``property_set`` so the downstream pipeline doesn't
    need to know which subclass produced it.
    """

    def __init__(self, *, enc: type[QubitEncoding]) -> None:
        """Bind the encoding type the policy will operate on."""
        super().__init__()
        self.enc = enc

    @abstractmethod
    def commit(self, dag: DAGCircuit) -> CommitResult:
        """Pick realizations and (optionally) a layout and routed DAG."""

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Wire the ``CommitResult`` into ``property_set``; return the routed DAG if any."""
        result = self.commit(dag)
        self.property_set["realization_choices"] = result.choices
        self.property_set["routing_swaps"] = result.n_swaps
        if result.layout is not None:
            self.property_set["layout"] = result.layout
        if result.search_trace is not None:
            self.property_set["search_trace"] = result.search_trace
        if result.routed_dag is None:
            return dag
        self.property_set["final_layout"] = result.routed_final_layout
        return result.routed_dag


class ApplyCommits(TransformationPass):
    """Substitute each ``LoweredOp`` node with the realization indexed by ``realization_choices``.

    The choices tuple is in decision-op topological order; fixed ops always use
    index 0. Also publishes ``semantic_swaps``: the SWAP instructions in the
    lowered circuit that routing did not insert (logical-X rail exchanges).
    """

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Substitute each ``LoweredOp`` node with the indexed realization."""
        choices = self.property_set.get("realization_choices", ())
        choice_iter = iter(choices)
        for node in list(dag.topological_op_nodes()):
            if not isinstance(node.op, LoweredOp):
                continue
            lop: LoweredOp = node.op
            idx = next(choice_iter) if lop.is_decision else 0
            sub_dag = circuit_to_dag(lop.realizations[idx])
            dag.substitute_node_with_dag(node, sub_dag)
        self.property_set["semantic_swaps"] = (
            dag.count_ops(recurse=False).get("swap", 0)
            - self.property_set["routing_swaps"]
        )
        return dag
