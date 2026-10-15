"""Type stub for the Rust extension ``prism._accelerate`` (``crates/src``). Kept in sync by hand."""

from typing import Any, ClassVar, final

Pairs = list[list[list[int]]]
Flat = tuple[list[Pairs], list[list[int]], list[int], list[int]]
Event = tuple[int, int, int]

@final
class SetScaling:
    Constant: ClassVar[SetScaling]
    Size: ClassVar[SetScaling]

@final
class BasicHeuristic:
    def __new__(cls, weight: float, scale: SetScaling) -> BasicHeuristic: ...

@final
class LookaheadHeuristic:
    def __new__(
        cls, weight: float, size: int, scale: SetScaling
    ) -> LookaheadHeuristic: ...

@final
class DecayHeuristic:
    def __new__(cls, increment: float, reset: int) -> DecayHeuristic: ...

@final
class Heuristic:
    def __new__(
        cls,
        basic: BasicHeuristic | None = None,
        lookahead: LookaheadHeuristic | None = None,
        decay: DecayHeuristic | None = None,
        attempt_limit: int | None = 1000,
        best_epsilon: float = 1e-10,
    ) -> Heuristic: ...

@final
class RoutingTarget:
    def __new__(cls) -> RoutingTarget: ...
    @staticmethod
    def from_coupling_list(
        edges: list[tuple[int, int]], num_qubits: int
    ) -> RoutingTarget: ...

def prism_layout_and_routing(
    forward: Flat,
    reverse: Flat,
    target: RoutingTarget,
    heuristic: Heuristic,
    starts: list[tuple[int, list[int]]],
    max_iterations: int,
    swap_trials: int,
    run_in_parallel: bool | None = None,
) -> list[tuple[list[Event], list[int], int, list[int]]]: ...
def sabre_routing(
    dag: Any,
    target: RoutingTarget,
    heuristic: Heuristic,
    initial_layout: Any,
    num_trials: int,
    seed: int | None = None,
    run_in_parallel: bool | None = None,
) -> tuple[Any, Any]: ...
