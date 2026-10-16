"""``PrismRouting``: place a ``MultiRealization`` and choose every realization.

SABRE layout-and-routing over retained realization sets. The outer loop
follows Qiskit's O3 ``SabreLayout``: random and standard starting layouts
undergo alternating forward/backward refinement, then one multi-trial forward
route is kept per start. The best final route by ``SearchBudget.objective``
gives the placement and the choices. The kernel is
``crates/src/prism_routing/layout.rs``.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Literal, get_args

from qiskit import QuantumCircuit
from qiskit.circuit.library import SwapGate
from qiskit.passmanager import GenericPass
from qiskit.transpiler import CouplingMap, TranspilerError

from prism._accelerate import (
    BasicHeuristic,
    DecayHeuristic,
    Heuristic,
    LookaheadHeuristic,
    RoutingTarget,
    SetScaling,
    prism_layout_and_routing,
)
from prism.ir import (
    MultiRealization,
    MultiRealizationInstruction,
    MultiRealizationOp,
    Placement,
    commuting_predecessors,
)
from prism.metrics import active_gate_count, physical_depth

__all__ = ["Objective", "PrismRouting", "SearchBudget"]

Objective = Literal["swaps", "depth"]

# Rust event kind (crates/src/prism_routing/input.rs); every other event is a commit.
_SWAP = 1


@dataclass(frozen=True)
class SearchBudget:
    """Search effort and route-selection objective.

    Args:
        layout_starts: Random starting layouts (Qiskit's dense, identity and
            reverse layouts are always added).
        refinement_iterations: Forward/backward refinement rounds per start.
        swap_trials: Routing trials per start in the final forward pass.
        objective: ``"swaps"`` (fewest inserted SWAPs, then depth, then gates) or
            ``"depth"`` (critical-path depth in non-free gates, then gates, then size).
    """

    layout_starts: int = 40
    refinement_iterations: int = 16
    swap_trials: int = 40
    objective: Objective = "swaps"

    def __post_init__(self) -> None:
        if self.objective not in get_args(Objective):
            raise ValueError(
                f"objective must be one of {list(get_args(Objective))}, got {self.objective!r}"
            )
        for name in ("layout_starts", "refinement_iterations", "swap_trials"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be >= 1, got {getattr(self, name)}")


def _score(qc: QuantumCircuit, objective: Objective) -> tuple[int, int, int]:
    """Post-selection score for ``qc`` under ``objective``; lower is better."""
    d, g, sz = physical_depth(qc), active_gate_count(qc), qc.size()
    if objective == "swaps":
        return (qc.count_ops().get("swap", 0), d, g)
    return (d, g, sz)


class PrismRouting(GenericPass[MultiRealization, MultiRealization]):
    """Place the program and choose a realization for every ``MultiRealizationOp``.

    Reads a ``MultiRealization`` with no placement; returns one with a
    placement, physical-qubit instructions, routing SWAPs, and a choice on
    every ``MultiRealizationOp``. Publishes, as routed, ``realization_choices``
    (the chosen index of each op with several candidates, in program order) and
    ``online_n_swaps`` (routing SWAPs) to the property set; a later pass that
    revises a choice does not update them.

    Args:
        coupling_map: Connected, symmetric device graph.
        seed: Seed of the layout search; ``None`` draws one.
        budget: Search effort and objective.

    Raises:
        ValueError: if ``coupling_map`` is disconnected or directed.
    """

    LOOKAHEAD_LAYERS = 8

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
            raise ValueError(
                "coupling_map is directed; prism needs every edge in both "
                "directions. Call coupling_map.make_symmetric() first."
            )
        super().__init__()
        self.coupling_map = coupling_map
        self.seed = seed
        self.budget = budget or SearchBudget()

    def run(self, passmanager_ir: MultiRealization) -> MultiRealization:
        """Refine every start in the kernel, then keep the best final route by objective.

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
        forward, reverse = _routing_problems(ir)
        base_seed = (
            self.seed
            if self.seed is not None
            else random.SystemRandom().getrandbits(64)
        )
        target = RoutingTarget.from_coupling_list(
            list(self.coupling_map.get_edges()), n_phys
        )
        results = prism_layout_and_routing(
            forward,
            reverse,
            target,
            self._make_heuristic(n_phys),
            [
                (int(seed) % (1 << 64), list(v2p))
                for seed, v2p in self._starting_layouts(base_seed, target, n_virt)
            ],
            self.budget.refinement_iterations,
            self.budget.swap_trials,
        )
        edges = frozenset(
            e for a, b in self.coupling_map.get_edges() for e in ((a, b), (b, a))
        )
        best = None  # (score, placed program, choices, n_swaps); first start wins ties
        for events, final_v2p, n_swaps, refined_v2p in results:
            data, chosen = _replay(events, ir.data, list(refined_v2p), n_phys)
            placed = replace(
                ir,
                data=data,
                placement=Placement(tuple(refined_v2p), tuple(final_v2p), edges),
            )
            s = _score(placed.to_circuit(), self.budget.objective)
            if best is None or s < best[0]:
                best = (s, placed, chosen, n_swaps)
        assert best is not None
        _, placed, chosen, n_swaps = best
        self.property_set["realization_choices"] = tuple(
            r
            for k, r in sorted(chosen.items())
            if isinstance(op := ir.data[k].operation, MultiRealizationOp)
            and len(op.candidates) > 1
        )
        self.property_set["online_n_swaps"] = int(n_swaps)
        return placed

    def _make_heuristic(self, n_phys: int) -> Heuristic:
        """Qiskit 2.6 ``SabreLayout``'s heuristic, with ``LOOKAHEAD_LAYERS`` lookahead layers.

        Stock looks one layer ahead at weight ``0.5 / n_phys``. That is too
        shallow for prism, whose commits route gates in cascades; eight layers at
        the stock weight beat Qiskit 2.3's 20-gate extended set on both SWAPs and
        depth.
        """
        return Heuristic(
            basic=BasicHeuristic(1.0, SetScaling.Constant),
            lookahead=LookaheadHeuristic(
                [0.5 / n_phys] * self.LOOKAHEAD_LAYERS, SetScaling.Constant
            ),
            decay=DecayHeuristic(0.001, 5),
            attempt_limit=10 * n_phys,
            best_epsilon=1e-10,
        )

    def _starting_layouts(
        self, base_seed: int, target: RoutingTarget, n_virt: int
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
            (seed, target.dense_layout(n_virt)),
            (seed + 1, list(range(n_phys))),
            (seed + 2, list(reversed(range(n_phys)))),
        ]


def _routing_problems(ir: MultiRealization) -> tuple[tuple, tuple]:
    """The kernel's forward and reverse problems.

    A problem is ``(virt_pairs, succ, pred_count, local_default)``, one entry
    per instruction (see ``crates/src/prism_routing/input.rs``). The reverse
    problem is the program reversed, for backward refinement.
    """
    virt_pairs, wires, diagonal, local_default = [], [], [], []
    for ins in ir.data:
        op = ins.operation
        if isinstance(op, MultiRealizationOp):
            cands = op.candidates
            diagonal.append(op.diagonal)
            local_default.append(op.default_index)
        else:
            qc = QuantumCircuit(len(ins.qubits), len(ins.clbits))
            qc.append(op, qc.qubits, qc.clbits)
            cands = (qc,)
            diagonal.append(False)
            local_default.append(0)
        pairs, used = [], set(ins.clbits)
        for real in cands:
            gates = [
                [ins.qubits[real.find_bit(q).index] for q in ci.qubits]
                for ci in real.data
            ]
            used.update(v for g in gates for v in g)
            pairs.append([[g[0], g[1]] for g in gates if len(g) == 2])
        virt_pairs.append(pairs)
        wires.append(used)

    def problem(order: list[int]) -> tuple:
        preds = commuting_predecessors(
            [wires[k] for k in order], [diagonal[k] for k in order]
        )
        succ: list[list[int]] = [[] for _ in preds]
        for k, deps in enumerate(preds):
            for j in sorted(deps):
                succ[j].append(k)
        return (
            [virt_pairs[k] for k in order],
            succ,
            [len(deps) for deps in preds],
            [local_default[k] for k in order],
        )

    order = list(range(len(ir.data)))
    return problem(order), problem(order[::-1])


def _replay(
    events: list[tuple[int, int, int]],
    data: list[MultiRealizationInstruction],
    v2p: list[int],
    n_phys: int,
) -> tuple[list[MultiRealizationInstruction], dict[int, int]]:
    """Turn a kernel trace into placed instructions and the chosen candidate per instruction.

    ``COMMIT(k, r)`` places instruction ``k`` whole, with choice ``r``.
    ``SWAP(p, q)`` is a routing SWAP between two instructions.
    """
    p2v = [0] * n_phys
    for v, p in enumerate(v2p):
        p2v[p] = v
    placed: list[MultiRealizationInstruction] = []
    chosen: dict[int, int] = {}
    for kind, a, b in events:
        if kind == _SWAP:
            placed.append(MultiRealizationInstruction(SwapGate(), (a, b)))
            v_a, v_b = p2v[a], p2v[b]
            v2p[v_a], v2p[v_b] = v2p[v_b], v2p[v_a]
            p2v[a], p2v[b] = p2v[b], p2v[a]
            continue
        ins = data[a]
        op = ins.operation
        qubits = tuple(v2p[v] for v in ins.qubits)
        chosen[a] = b
        if isinstance(op, MultiRealizationOp):
            op = replace(op, choice=b)
        placed.append(MultiRealizationInstruction(op, qubits, ins.clbits))
    return placed, chosen
