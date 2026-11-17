"""The passes between ``DAGCircuit`` and ``MultiRealization``."""

from __future__ import annotations

from qiskit.circuit import ClassicalRegister, Clbit, Measure, QuantumRegister
from qiskit.converters import circuit_to_dag
from qiskit.dagcircuit import DAGCircuit
from qiskit.passmanager import GenericPass
from qiskit.passmanager.compilation_status import PassManagerState, RunState
from qiskit.transpiler import Layout, TranspileLayout

from prism_qc import dualrail
from prism_qc.ir import RAILS, MultiRealization, MultiRealizationInstruction


class DAGToMultiRealization(GenericPass[DAGCircuit, MultiRealization]):
    """Lower each logical qubit to its rails and each operation to its candidates.

    A measurement writes rail 0 to its clbit ``c[i]`` and rail ``w`` to ``c_rail<w>[i]``.
    """

    def run(self, dag: DAGCircuit) -> MultiRealization:
        n = dag.num_qubits()
        cregs, clbits, partner = _rail_registers(dag)
        data = []
        prep = dualrail.initialize()
        for i in range(n):
            for ci in prep.data:
                rails = tuple(RAILS * i + prep.find_bit(q).index for q in ci.qubits)
                data.append(MultiRealizationInstruction(ci.operation, rails))
        for node in dag.topological_op_nodes():
            op = dualrail.lower(node.op, tuple(node.cargs))
            rails = tuple(
                RAILS * dag.find_bit(q).index + w
                for q in node.qargs
                for w in range(RAILS)
            )
            if isinstance(node.op, Measure):
                c = node.cargs[0]
                cl = (c, *(partner[c, w] for w in range(1, RAILS)))
            else:
                cl = tuple(node.cargs)
            data.append(MultiRealizationInstruction(op, rails, cl))

        perm = self.property_set["logical_output_permutation"] or range(n)
        ir = MultiRealization(
            qregs=[QuantumRegister(RAILS, f"q{i}") for i in range(n)],
            cregs=cregs,
            clbits=clbits,
            data=data,
            output_permutation=tuple(
                RAILS * perm[i] + w for i in range(n) for w in range(RAILS)
            ),
            metadata=dict(dag.metadata or {}),
        )
        ir.verify()
        return ir


def _rail_registers(
    dag: DAGCircuit,
) -> tuple[list[ClassicalRegister], list[Clbit], dict[tuple[Clbit, int], Clbit]]:
    """The registers and clbits with rail registers added, and each measured clbit's partner per rail.

    Rail ``w`` of a measurement into clbit ``c`` writes ``c``'s partner in
    ``<register>_rail<w>``, or in ``rail<w>`` for a clbit in no register.
    """
    measured = {node.cargs[0] for node in dag.op_nodes(Measure)}
    sources = [(r, list(r), f"{r.name}_") for r in dag.cregs.values()]
    loose = [c for c in dag.clbits if c in measured and not dag.find_bit(c).registers]
    if loose:
        sources.append((None, loose, ""))
    names = set(dag.cregs)
    cregs, clbits, partner = [], list(dag.clbits), {}
    for creg, bits, prefix in sources:
        if creg is not None:
            cregs.append(creg)
        if measured.isdisjoint(bits):
            continue
        for w in range(1, RAILS):
            name = f"{prefix}rail{w}"
            while name in names:
                name += "_"
            names.add(name)
            reg = ClassicalRegister(len(bits), name)
            cregs.append(reg)
            clbits += list(reg)
            for bit, p in zip(bits, reg, strict=True):
                partner.setdefault((bit, w), p)
    return cregs, clbits, partner


class MultiRealizationToDAG(GenericPass[MultiRealization, DAGCircuit]):
    """Emit every chosen candidate, and the layout if the program is placed.

    In the layout, virtual qubit ``RAILS * i + w`` is rail ``w`` of
    logical qubit ``i``, then the ancillas.
    """

    def run(self, ir: MultiRealization) -> DAGCircuit:
        ir.verify()
        dag = circuit_to_dag(ir.to_circuit())
        ps = self.property_set
        ps["num_input_qubits"] = len(ir.rails)
        # ElidePermutations' convention: qubit at the end -> its index at the start.
        ps["virtual_permutation_layout"] = Layout(
            dict(zip(ir.rails, ir.output_permutation, strict=True))
        )
        ancillas = QuantumRegister(ir.num_wires - len(ir.rails), "ancilla")
        virtuals = ir.rails + list(ancillas)
        ps["original_qubit_indices"] = {q: v for v, q in enumerate(virtuals)}
        if ir.placement is None:
            return dag
        initial, final = ir.placement.initial, ir.placement.final
        ps["layout"] = Layout.from_intlist(initial, *ir.qregs, ancillas)
        ps["final_layout"] = Layout(
            {dag.qubits[p]: f for p, f in zip(initial, final, strict=True)}
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
