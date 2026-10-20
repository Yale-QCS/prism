"""prism's stages and the passes between ``DAGCircuit`` and ``MultiRealization``."""

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
    """Lower each logical qubit to its rails and each operation to its candidates.

    A measurement writes rail 0 to its clbit ``c[i]`` and rail ``w`` to ``c_rail<w>[i]``.
    """

    def __init__(self, enc: type[QubitEncoding]) -> None:
        super().__init__()
        self.enc = enc

    def run(self, passmanager_ir: DAGCircuit) -> MultiRealization:
        dag, enc = passmanager_ir, self.enc
        wpl = enc.WIRES_PER_LOGICAL
        n = len(dag.qubits)
        logical = {q: i for i, q in enumerate(dag.qubits)}
        clbits = list(dag.clbits)
        # Rail w of a measurement into clbit c writes c's partner in "<register>_rail<w>".
        measured = {node.cargs[0] for node in dag.op_nodes(Measure)}
        sources = [(r, f"{r.name}_", list(r)) for r in dag.cregs.values()]
        loose = [
            c for c in dag.clbits if c in measured and not dag.find_bit(c).registers
        ]
        if loose:
            sources.append((None, "", loose))
        names = {r.name for r in dag.cregs.values()}
        cregs: list[ClassicalRegister] = []
        partner: dict[tuple[Clbit, int], Clbit] = {}
        for creg, prefix, bits in sources:
            if creg is not None:
                cregs.append(creg)
                if not measured & set(bits):
                    continue
            for w in range(1, wpl):
                name = f"{prefix}rail{w}"
                while name in names:
                    name += "_"
                names.add(name)
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
    """Emit every chosen candidate, and the layout if the program is placed.

    In the layout, virtual qubit ``WIRES_PER_LOGICAL * i + w`` is rail ``w`` of
    logical qubit ``i``, then the ancillas.
    """

    def run(self, passmanager_ir: MultiRealization) -> DAGCircuit:
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
        # Fold the elided permutation into final_layout, as stock layout passes do.
        TranspileLayout.from_property_set(dag, ps).write_into_property_set(ps)
        return dag

    def update_status(
        self, state: PassManagerState, run_state: RunState
    ) -> PassManagerState:
        """Forget completed passes, as ``TransformationPass`` does, so stock passes rerun."""
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
    """Prism's stages for ``enc`` on ``coupling_map``, a connected, undirected device graph.

    Replace a stage, then run ``PassManager([stages.to_flow_controller()])``.
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
    """``prism_stages`` in a ``PassManager``."""
    return PassManager(
        [prism_stages(coupling_map, enc, seed=seed, budget=budget).to_flow_controller()]
    )


def dualrail_pm(
    coupling_map: CouplingMap,
    *,
    seed: int = 42,
    budget: SearchBudget | None = None,
) -> PassManager:
    """A ``PassManager`` compiling to dual-rail qubits on ``coupling_map``."""
    return build_pm(coupling_map, DualRail, seed=seed, budget=budget)
