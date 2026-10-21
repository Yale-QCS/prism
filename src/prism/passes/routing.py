"""``PrismRouting``: Sabre layout and routing that picks each operation's realization.

The search is Qiskit's O3 ``SabreLayout`` loop, run in the Rust kernel
(``crates/src/prism_routing``). Routing SWAPs go between operations, never inside one.
"""

from __future__ import annotations

import math
import random
import warnings
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Literal, get_args

from qiskit.circuit import Clbit, Operation, Qubit
from qiskit.circuit.library import SwapGate
from qiskit.passmanager import GenericPass
from qiskit.transpiler import CouplingMap, TranspilerError

from prism._accelerate import dense_layout, prism_layout_and_routing
from prism.ir import (
    RAILS,
    MultiRealization,
    MultiRealizationInstruction,
    MultiRealizationOp,
    Placement,
    commuting_predecessors,
)
from prism.metrics import is_free

Objective = Literal["swaps", "depth"]


@dataclass(frozen=True)
class SearchBudget:
    """Search effort, and how the final route is chosen.

    Args:
        layout_starts: Random starting layouts, besides the dense, identity and
            reverse layouts.
        refinement_iterations: Forward and backward refinement rounds per start.
        swap_trials: Routing trials per start in the final forward pass.
        objective: ``"swaps"``: fewest SWAPs, then least depth. ``"depth"``: least
            depth, then fewest SWAPs. A number ``w >= 0``: least
            ``swaps + w * depth``. Ties go to fewer active gates.
    """

    layout_starts: int = 40
    refinement_iterations: int = 16
    swap_trials: int = 40
    objective: Objective | float = "swaps"

    def __post_init__(self) -> None:
        obj = self.objective
        named = isinstance(obj, str) and obj in get_args(Objective)
        weight = (
            isinstance(obj, (int, float))
            and not isinstance(obj, bool)
            and 0 <= obj < math.inf
        )
        if not (named or weight):
            raise ValueError(
                f"objective must be one of {list(get_args(Objective))} or a finite "
                f"depth weight >= 0, got {self.objective!r}"
            )
        for name in ("layout_starts", "refinement_iterations", "swap_trials"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be >= 1, got {getattr(self, name)}")


class PrismRouting(GenericPass[MultiRealization, MultiRealization]):
    """Place the program and choose a realization for every ``MultiRealizationOp``.

    An op that is not ``single_edge`` keeps ``default_index`` and is left, with a
    warning, for the physical stage to route. Sets ``property_set["online_n_swaps"]``.

    Args:
        coupling_map: A connected device graph; edges are undirected.
        seed: Seed of the layout search; ``None`` draws one.
        budget: Search effort and objective.
    """

    def __init__(
        self,
        coupling_map: CouplingMap,
        *,
        seed: int | None = None,
        budget: SearchBudget | None = None,
    ) -> None:
        if not coupling_map.is_connected():
            raise ValueError(
                "coupling_map is disconnected; pass one of its connected_components()"
            )
        if not coupling_map.is_symmetric:
            coupling_map = deepcopy(coupling_map)
            coupling_map.make_symmetric()
        super().__init__()
        self.coupling_map = coupling_map
        self.seed = seed
        self.budget = budget or SearchBudget()

    def run(self, ir: MultiRealization) -> MultiRealization:
        ir.verify()
        if ir.placement is not None:
            raise TranspilerError("PrismRouting got a program that is already placed")
        n_phys, n_virt = self.coupling_map.size(), len(ir.rails)
        if n_virt > n_phys:
            raise TranspilerError(
                f"the circuit needs {n_virt} physical qubits ({len(ir.qregs)} logical "
                f"x {RAILS} rails) but the coupling map has "
                f"{n_phys}. Use a larger coupling map or fewer qubits."
            )
        if n_through := sum(
            isinstance(ins.operation, MultiRealizationOp)
            and not ins.operation.single_edge
            for ins in ir.data
        ):
            warnings.warn(
                f"PrismRouting passed {n_through} operation(s) through to the physical "
                "stage: no candidate has its 2-qubit gates on one rail pair",
                UserWarning,
                stacklevel=2,
            )
        base_seed = (
            self.seed
            if self.seed is not None
            else random.SystemRandom().getrandbits(64)
        )
        edges = frozenset(self.coupling_map.get_edges())  # both orientations
        edge_list = list(edges)
        routed, final_v2p, refined_v2p = prism_layout_and_routing(
            _routing_problem(ir),
            edge_list,
            n_phys,
            self._starting_layouts(base_seed, edge_list, n_virt),
            self.budget.refinement_iterations,
            self.budget.swap_trials,
            self.budget.objective,
        )
        self.property_set["online_n_swaps"] = sum(len(swaps) for swaps, _, _ in routed)
        return replace(
            ir,
            data=_replay(routed, ir.data, list(refined_v2p), n_phys),
            placement=Placement(tuple(refined_v2p), tuple(final_v2p), edges),
        )

    def _starting_layouts(
        self, base_seed: int, edges: list[tuple[int, int]], n_virt: int
    ) -> list[tuple[int, list[int]]]:
        """``(seed, v2p)`` of the random, dense, identity and reverse starts."""
        n_phys = self.coupling_map.size()
        layouts = []
        for trial in range(self.budget.layout_starts):
            v2p = list(range(n_phys))
            random.Random(base_seed + trial).shuffle(v2p)
            layouts.append(v2p)
        layouts += [
            dense_layout(edges, n_phys, n_virt),
            list(range(n_phys)),
            list(reversed(range(n_phys))),
        ]
        return [((base_seed + i) % (1 << 64), v2p) for i, v2p in enumerate(layouts)]


def _routing_problem(ir: MultiRealization) -> list[tuple]:
    """Per instruction ``(default, predecessors, gates)``; ``gates[r]`` lists realization ``r``'s gates."""
    clbit_index = {bit: i for i, bit in enumerate(ir.clbits)}

    def gate(op: Operation, qubits: Iterable[Qubit], clbits: Iterable[Clbit]) -> tuple:
        return (
            list(qubits),
            sorted({clbit_index[c] for c in clbits}),
            is_free(op),
            op.name == "swap",
        )

    ops, wires = [], []
    for ins in ir.data:
        op = ins.operation
        if isinstance(op, MultiRealizationOp):
            gates = [
                [gate(*g) for g in ins.candidate_gates(r)]
                for r in range(len(op.candidates))
            ]
            ops.append((op.default_index, gates))
        else:
            gates = [[gate(op, ins.qubits, ins.clbits)]]
            ops.append((0, gates))
        wires.append(
            {q for real in gates for g in real for q in g[0]} | set(ins.clbits)
        )
    preds = commuting_predecessors(wires, [ins.diagonal for ins in ir.data])
    return [
        (default, sorted(deps), gates)
        for (default, gates), deps in zip(ops, preds, strict=True)
    ]


def _replay(
    routed: list[tuple[list[tuple[int, int]], int, int]],
    data: list[MultiRealizationInstruction],
    v2p: list[int],
    n_phys: int,
) -> list[MultiRealizationInstruction]:
    """Placed instructions from the kernel's route: per ``(swaps, k, r)``, the SWAPs, then instruction ``k`` with choice ``r``."""
    p2v = [0] * n_phys
    for v, p in enumerate(v2p):
        p2v[p] = v
    placed: list[MultiRealizationInstruction] = []
    for swaps, k, r in routed:
        for a, b in swaps:
            placed.append(MultiRealizationInstruction(SwapGate(), (a, b)))
            v_a, v_b = p2v[a], p2v[b]
            v2p[v_a], v2p[v_b] = v2p[v_b], v2p[v_a]
            p2v[a], p2v[b] = p2v[b], p2v[a]
        ins = data[k]
        op = ins.operation
        if isinstance(op, MultiRealizationOp):
            op = replace(op, choice=r)
        placed.append(
            MultiRealizationInstruction(
                op, tuple(v2p[v] for v in ins.qubits), ins.clbits
            )
        )
    return placed
