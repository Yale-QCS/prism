"""``build_pm``: prism's ``MultiStagePassManager``, and the passes that change IR.

Stages and their IRs::

    input                     QuantumCircuit -> DAGCircuit        CircuitToDAG
    logical                   DAGCircuit -> DAGCircuit            enc.logical_pm(): stock passes
    dag_to_multi_realization  DAGCircuit -> MultiRealization      DAGToMultiRealization
    routing                   MultiRealization -> MultiRealization PrismRouting
    multi_realization_to_dag  MultiRealization -> DAGCircuit      MultiRealizationToDAG
    physical                  DAGCircuit -> DAGCircuit            enc.physical_pm(): stock O3
    output                    DAGCircuit -> QuantumCircuit        DAGToCircuit
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qiskit.circuit import (
    ClassicalRegister,
    Clbit,
    ControlFlowOp,
    Measure,
    QuantumCircuit,
    QuantumRegister,
)
from qiskit.converters import circuit_to_dag, dag_to_circuit
from qiskit.dagcircuit import DAGCircuit
from qiskit.passmanager import GenericPass, MultiStagePassManager
from qiskit.passmanager.compilation_status import PassManagerState, RunState
from qiskit.transpiler import CouplingMap, Layout, TranspileLayout, TranspilerError

from prism.ir import MultiRealization, MultiRealizationInstruction
from prism.routing import PrismRouting, SearchBudget

if TYPE_CHECKING:
    from prism.encodings.base import QubitEncoding

__all__ = [
    "CircuitToDAG",
    "DAGToCircuit",
    "DAGToMultiRealization",
    "MultiRealizationToDAG",
    "SearchBudget",
    "build_pm",
]


class CircuitToDAG(GenericPass[QuantumCircuit, DAGCircuit]):
    """``QuantumCircuit -> DAGCircuit``, as ``qiskit.transpiler.PassManager`` enters."""

    def run(self, passmanager_ir: QuantumCircuit) -> DAGCircuit:
        """Convert, recording the input qubit indices unless the caller seeded them."""
        if self.property_set["original_qubit_indices"] is None:
            self.property_set["original_qubit_indices"] = {
                bit: i for i, bit in enumerate(passmanager_ir.qubits)
            }
        if self.property_set["num_input_qubits"] is None:
            self.property_set["num_input_qubits"] = passmanager_ir.num_qubits
        return circuit_to_dag(passmanager_ir, copy_operations=True)


class DAGToCircuit(GenericPass[DAGCircuit, QuantumCircuit]):
    """``DAGCircuit -> QuantumCircuit``, as ``qiskit.transpiler.PassManager`` exits."""

    def run(self, passmanager_ir: DAGCircuit) -> QuantumCircuit:
        """Convert, attaching the ``TranspileLayout`` and writing its canonical form back."""
        out = dag_to_circuit(passmanager_ir, copy_operations=False)
        layout = TranspileLayout.from_property_set(passmanager_ir, self.property_set)
        if layout is not None:
            out._layout = layout
            layout.write_into_property_set(self.property_set)
        # Private fields Qiskit's own PassManager backend sets the same way.
        out._clbit_write_latency = self.property_set["clbit_write_latency"]
        out._conditional_latency = self.property_set["conditional_latency"]
        if start_times := self.property_set["node_start_time"]:
            out._op_start_times = [
                start_times[node] for node in passmanager_ir.topological_op_nodes()
            ]
        return out


class DAGToMultiRealization(GenericPass[DAGCircuit, MultiRealization]):
    """``DAGCircuit -> MultiRealization``: each logical operation becomes its encoding rule.

    Every logical qubit gets ``WIRES_PER_LOGICAL`` rails and the encoding's
    preparation. A measurement writes the logical clbit from rail 0 and the
    other rails to a ``herald`` register. ``logical_output_permutation`` comes
    from the property set (set by ``ElideLogicalPermutations``).
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
        n_herald = sum(
            node.op.num_qubits * (wpl - 1)
            for node in dag.op_nodes()
            if isinstance(node.op, Measure)
        )
        herald: list[Clbit] = []
        if n_herald:
            name, k = "herald", 0
            while name in dag.cregs:
                k += 1
                name = f"herald{k}"
            cregs.append(ClassicalRegister(n_herald, name))
            herald = list(cregs[-1])
            clbits += herald

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
                cl = (node.cargs[0], *herald[: op.num_clbits - 1])
                herald = herald[op.num_clbits - 1 :]
            elif isinstance(node.op, ControlFlowOp):
                cl = tuple(node.cargs)
            else:
                cl = ()
            data.append(MultiRealizationInstruction(op, rails, cl))

        perm = self.property_set["logical_output_permutation"]
        ir = MultiRealization(
            enc=enc,
            qregs=[QuantumRegister(wpl, f"q{i}") for i in range(n)],
            cregs=cregs,
            clbits=clbits,
            data=data,
            logical_output_permutation=tuple(range(n) if perm is None else perm),
            metadata=dict(dag.metadata or {}),
        )
        ir.verify()
        return ir


class MultiRealizationToDAG(GenericPass[MultiRealization, DAGCircuit]):
    """``MultiRealization -> DAGCircuit``: materialize every choice on the physical qubits.

    The only step that drops the candidate sets. Needs a placement and a
    choice on every ``MultiRealizationOp``. Writes a rail-level layout: the
    output's ``TranspileLayout`` has virtual qubit ``WIRES_PER_LOGICAL * i + w``
    for rail ``w`` of logical qubit ``i``, ancillas after them, and the elided
    logical permutation in its final layout.
    """

    def run(self, passmanager_ir: MultiRealization) -> DAGCircuit:
        """Verify, materialize, and publish the rail-level layout.

        Raises:
            TranspilerError: if the program is unplaced, has an undecided op, or
                fails ``verify``.
        """
        ir = passmanager_ir
        if ir.placement is None:
            raise TranspilerError(
                "MultiRealizationToDAG needs a placed program; run a routing pass (PrismRouting) first"
            )
        ir.verify()
        dag = circuit_to_dag(ir.to_circuit())
        initial, final = ir.placement
        # The virtual circuit is the rail circuit: rail w of logical qubit i is
        # virtual index wpl * i + w; free physical qubits become ancillas.
        ancillas = QuantumRegister(len(initial) - len(ir.qubits), "ancilla")
        virtuals = ir.qubits + list(ancillas)
        layout = Layout({q: initial[v] for v, q in enumerate(virtuals)})
        for reg in [*ir.qregs, ancillas]:
            layout.add_register(reg)
        wpl = ir.enc.WIRES_PER_LOGICAL
        ps = self.property_set
        ps["layout"] = layout
        ps["original_qubit_indices"] = {q: v for v, q in enumerate(virtuals)}
        ps["num_input_qubits"] = len(ir.qubits)
        # ElidePermutations' convention: qubit at the end -> its index at the start.
        ps["virtual_permutation_layout"] = Layout(
            {
                reg[w]: wpl * ir.logical_output_permutation[i] + w
                for i, reg in enumerate(ir.qregs)
                for w in range(wpl)
            }
        )
        ps["final_layout"] = Layout(
            {dag.qubits[initial[v]]: final[v] for v in range(len(initial))}
        )
        # Canonical form (the elided permutation folded into final_layout) for the stock passes.
        canonical = TranspileLayout.from_property_set(dag, ps)
        assert canonical is not None  # "layout" is set
        canonical.write_into_property_set(ps)
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


def build_pm(
    coupling_map: CouplingMap,
    enc: type[QubitEncoding],
    *,
    seed: int = 42,
    budget: SearchBudget | None = None,
) -> MultiStagePassManager[QuantumCircuit, QuantumCircuit]:
    """Pass manager compiling ``enc``-encoded circuits onto ``coupling_map``.

    Run it as ``pm.run(qc, property_set=ps)`` to read the property set
    afterwards (``circuit_metrics``, ``realization_choices``, ``online_n_swaps``,
    ``logical_output_permutation``). A callback receives ``passmanager_ir`` as a
    ``QuantumCircuit``, ``DAGCircuit`` or ``MultiRealization``.

    Args:
        coupling_map: Connected, symmetric device graph.
        enc: The qubit encoding class, e.g. ``DualRail``.
        seed: Seed of the layout search and the physical stage.
        budget: Search effort and objective; ``None`` uses ``SearchBudget()``.

    Raises:
        ValueError: if ``coupling_map`` is disconnected or directed.
    """
    return MultiStagePassManager(
        input=CircuitToDAG(),
        logical=enc.logical_pm(),
        dag_to_multi_realization=DAGToMultiRealization(enc),
        routing=PrismRouting(coupling_map, seed=seed, budget=budget),
        multi_realization_to_dag=MultiRealizationToDAG(),
        physical=enc.physical_pm(coupling_map, seed=seed),
        output=DAGToCircuit(),
    )
