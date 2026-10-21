"""prism's transpiler passes, by stage."""

from prism.passes.logical import (
    EarlyMeasurement,
    ElideLogicalPermutations,
    MCPrepare,
    MinRXCliffords,
    SplitIfElse,
)
from prism.passes.lowering import DAGToMultiRealization, MultiRealizationToDAG
from prism.passes.multi_realization import ElideRailExchanges
from prism.passes.physical import (
    FenceErasureChecks,
    RecordCircuitMetrics,
    RescheduleCommutingDiagonals,
)
from prism.passes.routing import PrismRouting, SearchBudget

__all__ = [
    "DAGToMultiRealization",
    "EarlyMeasurement",
    "ElideLogicalPermutations",
    "ElideRailExchanges",
    "FenceErasureChecks",
    "MCPrepare",
    "MinRXCliffords",
    "MultiRealizationToDAG",
    "PrismRouting",
    "RecordCircuitMetrics",
    "RescheduleCommutingDiagonals",
    "SearchBudget",
    "SplitIfElse",
]
