"""Commit policies and the typed stage tasks that run them over the boundary IR."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from dataclasses import replace as _dc_replace
from typing import TYPE_CHECKING

from qiskit.dagcircuit import DAGCircuit
from qiskit.passmanager import GenericPass, PropertySet
from qiskit.transpiler import Layout
from qiskit.transpiler.basepasses import BasePass

from prism.lowering.ir import LoweredProgram

if TYPE_CHECKING:
    from prism.encodings.base import QubitEncoding


# Stock O3 preset trial counts, pinned so search effort never depends on CPU count.
SABRE_TRIALS = 20
SABRE_ITERATIONS = 4


@dataclass(frozen=True)
class SearchBudget:
    """Search effort and route-selection objective; the defaults are the paper configuration."""

    layout_starts: int = 40
    refinement_iterations: int = 16
    swap_trials: int = 40
    objective: str = "swaps"

    def __post_init__(self) -> None:
        if self.objective not in {"swaps", "depth", "gates", "duration"}:
            raise ValueError(f"unknown objective {self.objective!r}")
        for field in ("layout_starts", "refinement_iterations", "swap_trials"):
            if getattr(self, field) < 1:
                raise ValueError(f"{field} must be >= 1, got {getattr(self, field)}")


@dataclass(frozen=True)
class CommitResult:
    """``PrismRouting``'s decision: realization ``choices`` plus the layout and routed DAG it retained."""

    choices: tuple[int, ...]
    layout: Layout | None = None
    routed_dag: DAGCircuit | None = None
    routed_final_layout: Layout | None = None
    n_swaps: int | None = None


class CommitPolicy(ABC):
    """Pick realizations for ``LoweredOp`` nodes and hand off the layout and routed DAG."""

    def __init__(self, *, enc: type[QubitEncoding]) -> None:
        """Bind the encoding type the policy will operate on."""
        self.enc = enc
        self.property_set = PropertySet()

    @abstractmethod
    def commit(self, dag: DAGCircuit) -> CommitResult:
        """Pick realizations and (optionally) hand off layout / routed DAG."""


# ---------------------------------------------------------------------------
# Typed stage tasks over ``LoweredProgram``
# ---------------------------------------------------------------------------
def _publish_instrumentation(property_set: PropertySet, result: CommitResult) -> None:
    """Mirror a commit decision's accounting into the property set."""
    property_set["realization_choices"] = tuple(result.choices)
    if result.n_swaps is not None:
        property_set["online_n_swaps"] = result.n_swaps


class OverDag(GenericPass):
    """``LoweredProgram -> LoweredProgram``: run one DAG pass over the program's DAG."""

    def __init__(self, dag_pass: BasePass) -> None:
        """Wrap a transpiler pass (transformation or analysis)."""
        super().__init__()
        self.dag_pass = dag_pass

    def run(self, passmanager_ir: LoweredProgram) -> LoweredProgram:
        """Apply the pass; an analysis pass leaves the DAG as is."""
        self.dag_pass.property_set = self.property_set
        out = self.dag_pass.run(passmanager_ir.dag)
        return passmanager_ir if out is None else _dc_replace(passmanager_ir, dag=out)


class CommitStage(GenericPass):
    """``LoweredProgram -> LoweredProgram``: run one ``CommitPolicy`` and attach its decision."""

    def __init__(self, policy: CommitPolicy) -> None:
        """Wrap the policy whose ``commit`` decides the realizations."""
        super().__init__()
        self.policy = policy

    def run(self, passmanager_ir: LoweredProgram) -> LoweredProgram:
        """Decide realizations over the program's DAG."""
        self.policy.property_set = self.property_set
        result = self.policy.commit(passmanager_ir.dag)
        _publish_instrumentation(self.property_set, result)
        return passmanager_ir.with_commit(result)
