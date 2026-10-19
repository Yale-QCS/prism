"""``PrismRouting``: place a ``MultiRealization`` and choose every realization.

SABRE layout-and-routing over retained realization sets. The outer loop
follows Qiskit's O3 ``SabreLayout``: random and standard starting layouts
undergo alternating forward/backward refinement, then one multi-trial forward
route is kept per start. The best final route by ``SearchBudget.objective``
gives the placement and the choices. The kernel is
``crates/src/prism_routing/layout.rs``; it scores every start and returns only
the winning route.

Routing SWAPs go between operations, never inside one. An operation that is
not ``MultiRealizationOp.single_edge`` cannot be routed onto one device edge:
it is passed through, at its default candidate and off the device edges, and
the physical stage routes it.
"""

from __future__ import annotations

import math
import random
import warnings
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Literal, get_args

from qiskit.circuit import Clbit, Operation
from qiskit.circuit.library import SwapGate
from qiskit.passmanager import GenericPass
from qiskit.transpiler import CouplingMap, TranspilerError

from prism._accelerate import dense_layout, prism_layout_and_routing
from prism.ir import (
    MultiRealization,
    MultiRealizationInstruction,
    MultiRealizationOp,
    Placement,
    commuting_predecessors,
)
from prism.metrics import is_free

__all__ = ["Objective", "PrismRouting", "SearchBudget"]

Objective = Literal["swaps", "depth"]


@dataclass(frozen=True)
class SearchBudget:
    """Search effort and route-selection objective.

    Args:
        layout_starts: Random starting layouts (Qiskit's dense, identity and
            reverse layouts are always added).
        refinement_iterations: Forward/backward refinement rounds per start.
        swap_trials: Routing trials per start in the final forward pass.
        objective: How the final route is chosen among every trial of every
            start. ``"swaps"``: fewest SWAPs, then least depth, then fewest
            active gates. ``"depth"``: least depth (the critical path in
            non-free gates), then fewest SWAPs, then fewest active gates. A
            number ``w >= 0``: least ``swaps + w * depth``, then as ``"swaps"``.
            It only ranks finished routes; the routing heuristic does not see it.
    """

    layout_starts: int = 40
    refinement_iterations: int = 16
    swap_trials: int = 40
    objective: Objective | float = "swaps"

    def __post_init__(self) -> None:
        if isinstance(self.objective, bool) or not (
            self.objective in get_args(Objective)
            or isinstance(self.objective, (int, float))
            and 0 <= self.objective < math.inf
        ):
            raise ValueError(
                f"objective must be one of {list(get_args(Objective))} or a finite "
                f"depth weight >= 0, got {self.objective!r}"
            )
        for name in ("layout_starts", "refinement_iterations", "swap_trials"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be >= 1, got {getattr(self, name)}")


class PrismRouting(GenericPass[MultiRealization, MultiRealization]):
    """Place the program and choose a realization for every ``MultiRealizationOp``.

    Reads a ``MultiRealization`` with no placement; returns one with a
    placement, physical-qubit instructions, routing SWAPs, and a choice on
    every ``MultiRealizationOp``. An op that is not ``single_edge`` is passed
    through at ``default_index`` and left for the physical stage to route,
    with a ``UserWarning``. Publishes ``online_n_swaps`` (routing SWAPs) to the
    property set. The result shares its registers, clbits and metadata with the
    input.

    Args:
        coupling_map: Connected device graph; edges are undirected, as dual-rail
            interactions have no direction.
        seed: Seed of the layout search; ``None`` draws one.
        budget: Search effort and objective.

    Raises:
        ValueError: if ``coupling_map`` is disconnected.
    """

    def __init__(
        self,
        coupling_map: CouplingMap,
        *,
        seed: int | None = None,
        budget: SearchBudget | None = None,
    ) -> None:
        """Check the coupling map and keep the search configuration."""
        if not coupling_map.is_connected():
            raise ValueError(
                "coupling_map is disconnected; prism routes on one connected "
                "component. Pass the component to use, e.g. "
                "coupling_map.connected_components()[0]."
            )
        if not coupling_map.is_symmetric:
            coupling_map = deepcopy(coupling_map)
            coupling_map.make_symmetric()
        super().__init__()
        self.coupling_map = coupling_map
        self.seed = seed
        self.budget = budget or SearchBudget()

    def run(self, passmanager_ir: MultiRealization) -> MultiRealization:
        """Refine and score every start in the kernel, then replay the best final route.

        Raises:
            TranspilerError: if the program is already placed or needs more
                qubits than the device has.
        """
        ir = passmanager_ir
        if ir.placement is not None:
            raise TranspilerError("PrismRouting got a program that is already placed")
        n_phys, n_virt = self.coupling_map.size(), len(ir.rails)
        if n_virt > n_phys:
            raise TranspilerError(
                f"the circuit needs {n_virt} physical qubits ({len(ir.qregs)} logical "
                f"x {ir.enc.WIRES_PER_LOGICAL} wires) but the coupling map has "
                f"{n_phys}. Use a larger coupling map or fewer qubits."
            )
        if n_through := sum(
            isinstance(ins.operation, MultiRealizationOp)
            and not ins.operation.single_edge
            for ins in ir.data
        ):
            warnings.warn(
                f"PrismRouting passed {n_through} operation(s) through unrouted: no "
                "candidate has its 2-qubit gates on one rail pair. Each keeps its "
                "default candidate, and the physical stage routes it.",
                UserWarning,
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
            [
                (seed % (1 << 64), v2p)
                for seed, v2p in self._starting_layouts(base_seed, edge_list, n_virt)
            ],
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
        """``layout_starts`` seeded random layouts, then Qiskit's dense, identity and reverse layouts."""
        n_phys = self.coupling_map.size()
        starts = []
        for trial in range(self.budget.layout_starts):
            v2p = list(range(n_phys))
            random.Random(base_seed + trial).shuffle(v2p)
            starts.append((base_seed + trial, v2p))
        seed = base_seed + self.budget.layout_starts
        return starts + [
            (seed, dense_layout(edges, n_phys, n_virt)),
            (seed + 1, list(range(n_phys))),
            (seed + 2, list(reversed(range(n_phys)))),
        ]


def _routing_problem(ir: MultiRealization) -> list[tuple]:
    """The kernel's routing problem: per instruction, ``(pairs, default, predecessors, gates)``.

    ``pairs[r]`` lists the rail pairs of the two-qubit gates of realization
    ``r``, and ``gates[r]`` its gates as the kernel scores them (see
    ``crates/src/prism_routing/input.rs``). An op that is not ``single_edge``
    gets realizations with no pairs: the kernel commits its default at once,
    adding no SWAP for it.
    """
    clbit_index = {bit: i for i, bit in enumerate(ir.clbits)}

    def gate(op: Operation, qubits: list[int], clbits: list[Clbit]) -> tuple:
        """``(qubits, clbits, free, swap)``; clbits as ``QuantumCircuit.depth`` reads them."""
        return (
            qubits,
            sorted({clbit_index[c] for c in clbits}),
            is_free(op),
            op.name == "swap",
        )

    ops, wires, diagonal = [], [], []
    for ins in ir.data:
        op = ins.operation
        if isinstance(op, MultiRealizationOp):
            gates = [
                [
                    gate(
                        ci.operation,
                        [ins.qubits[real.find_bit(q).index] for q in ci.qubits],
                        [ins.clbits[real.find_bit(c).index] for c in ci.clbits],
                    )
                    for ci in real.data
                ]
                for real in op.candidates
            ]
            routed, default, diag = op.single_edge, op.default_index, op.diagonal
        else:
            gates = [[gate(op, list(ins.qubits), list(ins.clbits))]]
            routed, default, diag = True, 0, False
        pairs = [
            [g[0] for g in real if len(g[0]) == 2] if routed else [] for real in gates
        ]
        ops.append((pairs, default, gates))
        wires.append(
            {q for real in gates for g in real for q in g[0]} | set(ins.clbits)
        )
        diagonal.append(diag)
    preds = commuting_predecessors(wires, diagonal)
    return [
        (pairs, default, sorted(deps), gates)
        for (pairs, default, gates), deps in zip(ops, preds)
    ]


def _replay(
    routed: list[tuple[list[tuple[int, int]], int, int]],
    data: list[MultiRealizationInstruction],
    v2p: list[int],
    n_phys: int,
) -> list[MultiRealizationInstruction]:
    """Turn the kernel's routed order into placed instructions.

    Each ``(swaps, k, r)`` places the routing SWAPs ``swaps``, then
    instruction ``k`` whole, with choice ``r``.
    """
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
