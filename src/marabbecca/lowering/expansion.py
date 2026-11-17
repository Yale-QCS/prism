"""Lowering-stage wire-level expansion.

``LowerExpansion`` is the entry pass of the lowering stage: it takes a logical
DAG (n logical qubits) and produces a physical-wire DAG (n * wpl qubits) of
``LoweredOp`` nodes plus inlined init gates. A ``CommitPolicy`` then picks
realizations and ``ApplyCommits`` substitutes them in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qiskit import QuantumCircuit, QuantumRegister
from qiskit.circuit import ClassicalRegister, Clbit, Measure
from qiskit.circuit.controlflow import ControlFlowOp
from qiskit.dagcircuit import DAGCircuit
from qiskit.transpiler import TransformationPass

from marabbecca.lowering.ir import LoweredOp

if TYPE_CHECKING:
    from marabbecca.encodings.base import QubitEncoding


class LowerExpansion(TransformationPass):
    """Expand a logical DAG to a wire-level DAG of ``LoweredOp`` nodes plus init gates."""

    def __init__(self, *, enc: type[QubitEncoding]) -> None:
        """Store the target encoding class."""
        super().__init__()
        self.enc = enc

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Expand the logical DAG; emit init gates and per-op ``LoweredOp`` nodes."""
        # Upstream SabreLayout/SabreSwap on the chip quotient (logical_pm) leaves
        # layout / final_layout sized to the quotient. Clear so they don't leak
        # into the physical stage; CommitPolicy may write rail-sized replacements.
        self.property_set["layout"] = None
        self.property_set["final_layout"] = None

        enc = self.enc
        wpl = enc.WIRES_PER_LOGICAL
        n_logical = len(dag.qubits)
        qubit_to_logical = {q: i for i, q in enumerate(dag.qubits)}

        # One physical qreg per logical qubit, wpl wires each.
        regs = [QuantumRegister(wpl, f"q{i}") for i in range(n_logical)]
        out_dag = DAGCircuit()
        out_dag.metadata = dict(dag.metadata or {})
        for reg in regs:
            out_dag.add_qreg(reg)

        # Allocate a fresh "meas" creg with wpl physical bits per logical clbit
        # (logical clbit k -> bits k*wpl .. k*wpl + wpl - 1), then carry over
        # any other cregs from the input (skipping a same-named "meas" already
        # added).
        has_measure = any(isinstance(node.op, Measure) for node in dag.op_nodes())
        n_phys_meas = len(dag.clbits) * wpl if has_measure else 0
        meas_cr: ClassicalRegister | None = None
        if n_phys_meas:
            meas_cr = ClassicalRegister(n_phys_meas, "meas")
            out_dag.add_creg(meas_cr)
        for cr in dag.cregs.values():
            if meas_cr is not None and cr.name == meas_cr.name:
                continue
            out_dag.add_creg(cr)

        # Codestate prep per logical qubit. Each prep gate is wrapped as a fixed
        # LoweredOp on its own wires, so the lowered DAG is homogeneous (every op
        # is a LoweredOp) and the commit policies route init like any other op.
        init_template = enc.initialize()
        # Idle logical wires (the quotient graph's unused nodes under Logical-SABRE's
        # layout) carry no program and get no preparation.
        idle = set(dag.idle_wires())
        for i in range(n_logical):
            if dag.qubits[i] in idle:
                continue
            for instr in init_template.data:
                local = [init_template.find_bit(q).index for q in instr.qubits]
                sub = QuantumCircuit(len(local))
                sub.append(instr.operation, range(len(local)))
                out_dag.apply_operation_back(
                    LoweredOp.fixed(sub, name=instr.operation.name),
                    [regs[i][lq] for lq in local],
                    [],
                )

        # Emit each LoweredOp on its physical wires. Measure ops write the
        # meas_cr bits of their own logical clbit, so routing may reorder
        # measurements; control-flow ops keep their original cargs; everything
        # else has none.
        for node in dag.topological_op_nodes():
            logical_qubits = tuple(qubit_to_logical[q] for q in node.qargs)
            lop = enc.lower(node.op, tuple(node.cargs))
            physical_wires = [regs[i][w] for i in logical_qubits for w in range(wpl)]

            if isinstance(node.op, Measure):
                k = dag.find_bit(node.cargs[0]).index
                phys_clbits: list[Clbit] = [
                    meas_cr[k * lop.num_clbits + j] for j in range(lop.num_clbits)
                ]
            elif isinstance(node.op, ControlFlowOp):
                phys_clbits = list(node.cargs)
            else:
                phys_clbits = []

            out_dag.apply_operation_back(lop, physical_wires, phys_clbits)

        return out_dag
