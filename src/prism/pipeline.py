"""prism's stages, the passes that change IR, and ``build_pm``.

``prism_stages`` is a ``MultiStagePassManager`` from ``DAGCircuit`` to ``DAGCircuit``::

    logical                   DAGCircuit -> DAGCircuit             enc.logical_pm(): stock passes
    dag_to_multi_realization  DAGCircuit -> MultiRealization       DAGToMultiRealization
    multi_realization         MultiRealization -> MultiRealization [ElideRailExchanges, PrismRouting, RetimeDiagonals]
    multi_realization_to_dag  MultiRealization -> DAGCircuit       MultiRealizationToDAG
    physical                  DAGCircuit -> DAGCircuit             physical_pm: stock O3, then CommutativeOptimization,
                                                                   FoldCRZAngles, EarlyMeasurement, DropMeasuredSwaps,
                                                                   RescheduleCommutingDiagonals, RecordCircuitMetrics

``build_pm`` nests it in a ``qiskit.transpiler.PassManager``, which converts the
circuit to a DAG and back as for any transpiler pipeline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qiskit.circuit import (
    ClassicalRegister,
    Clbit,
    Measure,
    QuantumRegister,
)
from qiskit.converters import circuit_to_dag
from qiskit.dagcircuit import DAGCircuit
from qiskit.passmanager import GenericPass, MultiStagePassManager
from qiskit.passmanager.compilation_status import PassManagerState, RunState
from qiskit.transpiler import (
    CouplingMap,
    Layout,
    PassManager,
    TranspileLayout,
)

from prism.encodings import DualRail
from prism.ir import MultiRealization, MultiRealizationInstruction
from prism.passes import ElideRailExchanges, RetimeDiagonals
from prism.physical import physical_pm
from prism.routing import PrismRouting, SearchBudget

if TYPE_CHECKING:
    from prism.encodings.base import QubitEncoding

__all__ = [
    "DAGToMultiRealization",
    "MultiRealizationToDAG",
    "SearchBudget",
    "build_pm",
    "dualrail_pm",
    "prism_stages",
]


class DAGToMultiRealization(GenericPass[DAGCircuit, MultiRealization]):
    """``DAGCircuit -> MultiRealization``: each logical operation becomes its encoding rule.

    Every logical qubit gets ``WIRES_PER_LOGICAL`` rails and the encoding's
    preparation. A measurement writes rail 0 to its clbit ``c[i]`` and rail ``w``
    to ``c_rail<w>[i]``, a register added per measured register. ``output_permutation`` starts
    as the property set's ``logical_output_permutation`` (set by ``ElideLogicalPermutations``) on rails.
    """

    def __init__(self, enc: type[QubitEncoding]) -> None:
        """Bind the encoding whose rules expand each operation."""
        super().__init__()
        self.enc = enc

    def run(self, passmanager_ir: DAGCircuit) -> MultiRealization:
        """Expand the logical DAG; the result passes ``verify``."""
        dag, enc = passmanager_ir, self.enc
        wpl = enc.WIRES_PER_LOGICAL
        n = len(dag.qubits)
        logical = {q: i for i, q in enumerate(dag.qubits)}
        cregs = list(dag.cregs.values())
        clbits = list(dag.clbits)
        # Rail w of the measurement that writes clbit c goes to the partner of c
        # in "<register>_rail<w>", one register per measured register.
        measured = {node.cargs[0] for node in dag.op_nodes(Measure)}
        sources = [
            (f"{r.name}_", list(r)) for r in dag.cregs.values() if measured & set(r)
        ]
        loose = [
            c for c in dag.clbits if c in measured and not dag.find_bit(c).registers
        ]
        if loose:
            sources.append(("", loose))
        partner: dict[tuple[Clbit, int], Clbit] = {}
        for prefix, bits in sources:
            for w in range(1, wpl):
                name = f"{prefix}rail{w}"
                while any(r.name == name for r in cregs):
                    name += "_"
                reg = ClassicalRegister(len(bits), name)
                cregs.append(reg)
                clbits += list(reg)
                for bit, p in zip(bits, reg):
                    partner.setdefault((bit, w), p)

        data = []
        prep = enc.initialize()
        for i in range(n):
            for ci in prep.data:
                rails = tuple(wpl * i + prep.find_bit(q).index for q in ci.qubits)
                data.append(MultiRealizationInstruction(ci.operation, rails))
        for node in dag.topological_op_nodes():
            op = enc.lower(node.op, tuple(node.cargs))
            rails = tuple(wpl * logical[q] + w for q in node.qargs for w in range(wpl))
            if isinstance(node.op, Measure):
                c = node.cargs[0]
                cl = (c, *(partner[c, w] for w in range(1, wpl)))
            else:
                cl = tuple(node.cargs)
            data.append(MultiRealizationInstruction(op, rails, cl))

        perm = self.property_set["logical_output_permutation"] or range(n)
        ir = MultiRealization(
            enc=enc,
            qregs=[QuantumRegister(wpl, f"q{i}") for i in range(n)],
            cregs=cregs,
            clbits=clbits,
            data=data,
            output_permutation=tuple(
                wpl * perm[i] + w for i in range(n) for w in range(wpl)
            ),
            metadata=dict(dag.metadata or {}),
        )
        ir.verify()
        return ir


class MultiRealizationToDAG(GenericPass[MultiRealization, DAGCircuit]):
    """``MultiRealization -> DAGCircuit``: materialize every choice on the physical qubits.

    The only step that drops the candidate sets. Needs a choice on every
    ``MultiRealizationOp``. An unplaced program is emitted on its rails, with
    the elided ``output_permutation``, for the physical stage to lay out and
    route. A placed one gets a rail-level layout: the
    output's ``TranspileLayout`` has virtual qubit ``WIRES_PER_LOGICAL * i + w``
    for rail ``w`` of logical qubit ``i``, ancillas after them, and the elided
    ``output_permutation`` in its final layout.
    """

    def run(self, passmanager_ir: MultiRealization) -> DAGCircuit:
        """Verify, materialize, and publish the rail-level layout.

        Raises:
            TranspilerError: if the program has an undecided op or fails ``verify``.
        """
        ir = passmanager_ir
        ir.verify()
        dag = circuit_to_dag(ir.to_circuit())
        ps = self.property_set
        ps["original_qubit_indices"] = {q: v for v, q in enumerate(ir.rails)}
        ps["num_input_qubits"] = len(ir.rails)
        # ElidePermutations' convention: qubit at the end -> its index at the start.
        ps["virtual_permutation_layout"] = Layout(
            dict(zip(ir.rails, ir.output_permutation))
        )
        if ir.placement is None:
            return dag
        initial, final = ir.placement.initial, ir.placement.final
        # The virtual circuit is the rail circuit: rail w of logical qubit i is
        # virtual index wpl * i + w; free physical qubits become ancillas.
        ancillas = QuantumRegister(len(initial) - len(ir.rails), "ancilla")
        virtuals = ir.rails + list(ancillas)
        layout = Layout({q: initial[v] for v, q in enumerate(virtuals)})
        for reg in [*ir.qregs, ancillas]:
            layout.add_register(reg)
        ps["layout"] = layout
        ps["original_qubit_indices"] = {q: v for v, q in enumerate(virtuals)}
        ps["final_layout"] = Layout(
            {dag.qubits[initial[v]]: final[v] for v in range(len(initial))}
        )
        # Qiskit's canonical form (the elided permutation folded into final_layout) for the stock passes.
        TranspileLayout.from_property_set(dag, ps).write_into_property_set(ps)
        return dag

    def update_status(
        self, state: PassManagerState, run_state: RunState
    ) -> PassManagerState:
        """Forget completed passes, as ``TransformationPass`` does.

        The physical stage's stock passes must rerun on the new DAG even if the
        logical stage already ran them.
        """
        state = super().update_status(state, run_state)
        if run_state == RunState.SUCCESS:
            state.workflow_status.completed_passes.clear()
        return state


def prism_stages(
    coupling_map: CouplingMap,
    enc: type[QubitEncoding],
    *,
    seed: int = 42,
    budget: SearchBudget | None = None,
) -> MultiStagePassManager[DAGCircuit, DAGCircuit]:
    """Prism's stages, compiling an ``enc``-encoded DAG onto ``coupling_map``.

    Replace a stage before nesting, e.g. ``stages.multi_realization = [MyPass(), PrismRouting(...)]``,
    then run ``PassManager([stages.to_flow_controller()])`` (what ``build_pm`` returns).

    Args:
        coupling_map: Connected device graph; edges are undirected.
        enc: The qubit encoding class, e.g. ``DualRail``.
        seed: Seed of the layout search and the physical stage.
        budget: Search effort and objective; ``None`` uses ``SearchBudget()``.

    Raises:
        ValueError: if ``coupling_map`` is disconnected.
    """
    routing = PrismRouting(coupling_map, seed=seed, budget=budget)
    return MultiStagePassManager(
        logical=enc.logical_pm(),
        dag_to_multi_realization=DAGToMultiRealization(enc),
        multi_realization=[ElideRailExchanges(), routing, RetimeDiagonals()],
        multi_realization_to_dag=MultiRealizationToDAG(),
        physical=physical_pm(routing.coupling_map, enc, seed=seed),
    )


def build_pm(
    coupling_map: CouplingMap,
    enc: type[QubitEncoding],
    *,
    seed: int = 42,
    budget: SearchBudget | None = None,
) -> PassManager:
    """``PassManager`` compiling ``enc``-encoded circuits onto ``coupling_map``: ``prism_stages`` nested.

    Read the property set afterwards from ``pm.property_set`` (``circuit_metrics``,
    ``online_n_swaps``, ``logical_output_permutation``).
    A callback receives the IR as ``dag``: a ``DAGCircuit`` or a ``MultiRealization``.
    Arguments and errors are those of ``prism_stages``.
    """
    return PassManager(
        [prism_stages(coupling_map, enc, seed=seed, budget=budget).to_flow_controller()]
    )


def dualrail_pm(
    coupling_map: CouplingMap, *, seed: int = 42, budget: SearchBudget | None = None
) -> PassManager:
    """``build_pm`` for the dual-rail encoding."""
    return build_pm(coupling_map, DualRail, seed=seed, budget=budget)
