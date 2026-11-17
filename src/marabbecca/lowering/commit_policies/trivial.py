"""Trivial commit: ``default_index`` for every decision op (or a uniform-random pick).

Analog of Qiskit's ``TrivialLayout`` — the lightest possible policy. No
coupling map, no awareness of physical positions. Default mode picks each
encoding's canonical ``default_index``; ``randomize=True`` picks a uniform-random
realization for each decision op (deterministic given ``seed``).
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from qiskit.dagcircuit import DAGCircuit

from marabbecca.lowering.commit import CommitPolicy, CommitResult
from marabbecca.lowering.ir import LoweredOp

if TYPE_CHECKING:
    from marabbecca.encodings.base import QubitEncoding


class TrivialCommit(CommitPolicy):
    """Set ``realization_choices`` to ``default_index`` per op, or a uniform-random pick if ``randomize=True``."""

    def __init__(
        self, *, enc: type[QubitEncoding], randomize: bool = False, seed: int = 42
    ) -> None:
        """Bind encoding; ``randomize=True`` picks uniformly across each decision's realizations."""
        super().__init__(enc=enc)
        self.randomize = randomize
        self.seed = seed

    def commit(self, dag: DAGCircuit) -> CommitResult:
        """Defaults or random picks; no layout/routing hints."""
        op_nodes = [
            n for n in dag.topological_op_nodes() if isinstance(n.op, LoweredOp)
        ]
        if self.randomize:
            rng = random.Random(self.seed)
            choices = tuple(
                rng.randrange(len(n.op.realizations))
                for n in op_nodes
                if n.op.is_decision
            )
        else:
            choices = tuple(n.op.default_index for n in op_nodes if n.op.is_decision)
        return CommitResult(choices=choices)
