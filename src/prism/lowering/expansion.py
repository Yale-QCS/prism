"""Lowering-stage wire-level expansion.

``expand`` takes a logical DAG (n logical qubits) and produces a
``LoweredProgram``: a physical-wire DAG (n * wpl qubits) of ``LoweredOp`` nodes
plus inlined init gates, with the wire binding. ``ExpandStage`` is the typed
stage task.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qiskit import QuantumCircuit, QuantumRegister
from qiskit.circuit import ClassicalRegister, Clbit, Measure
from qiskit.circuit.controlflow import ControlFlowOp
from qiskit.dagcircuit import DAGCircuit
from qiskit.passmanager import GenericPass, PropertySet

from prism.lowering.ir import LoweredOp, LoweredProgram

if TYPE_CHECKING:
    from prism.encodings.base import QubitEncoding


def _clear_quotient_layouts(property_set: PropertySet) -> None:
    # Upstream SabreLayout/SabreSwap on the chip quotient (logical_pm) leaves
    # layout / final_layout sized to the quotient. Clear so they don't leak
    # into the physical stage; CommitPolicy may write rail-sized replacements.
    property_set["layout"] = None
    property_set["final_layout"] = None


class ExpandStage(GenericPass):
    """Typed stage task: logical ``DAGCircuit`` -> ``LoweredProgram``."""

    def __init__(self, *, enc: type[QubitEncoding]) -> None:
        """Bind the encoding type used for lowering."""
        super().__init__()
        self.enc = enc

    def run(self, passmanager_ir: DAGCircuit) -> LoweredProgram:
        """Expand the logical DAG into the boundary IR."""
        _clear_quotient_layouts(self.property_set)
        return expand(passmanager_ir, self.enc)


def expand(dag: DAGCircuit, enc: type[QubitEncoding]) -> LoweredProgram:
    """Expand a logical DAG to a ``LoweredProgram`` of ``LoweredOp`` nodes plus init gates."""
    wpl = enc.WIRES_PER_LOGICAL
    n_logical = len(dag.qubits)
    qubit_to_logical = {q: i for i, q in enumerate(dag.qubits)}

    # One physical qreg per logical qubit, wpl wires each.
    regs = [QuantumRegister(wpl, f"q{i}") for i in range(n_logical)]
    out_dag = DAGCircuit()
    out_dag.metadata = dict(dag.metadata or {})
    for reg in regs:
        out_dag.add_qreg(reg)

    lowered_ops = [
        (
            node,
            tuple(qubit_to_logical[q] for q in node.qargs),
            enc.lower(node.op, tuple(node.cargs)),
        )
        for node in dag.topological_op_nodes()
    ]

    # Wire 0 of a measured logical qubit reports into the logical clbit, so
    # feedforward on it keeps working after lowering; the other wires (the
    # herald bits) draw from a fresh creg whose name avoids the input's.
    for cr in dag.cregs.values():
        out_dag.add_creg(cr)
    n_herald = sum(
        node.op.num_qubits * (wpl - 1)
        for node in dag.op_nodes()
        if isinstance(node.op, Measure)
    )
    meas_cr: ClassicalRegister | None = None
    if n_herald:
        name, k = "herald", 0
        while name in dag.cregs:
            k += 1
            name = f"herald{k}"
        meas_cr = ClassicalRegister(n_herald, name)
        out_dag.add_creg(meas_cr)

    # Codestate prep per logical qubit. Each prep gate is wrapped as a fixed
    # LoweredOp on its own wires, so the lowered DAG is homogeneous (every op
    # is a LoweredOp) and the commit policies route init like any other op.
    init_template = enc.initialize()
    for i in range(n_logical):
        for instr in init_template.data:
            local = [init_template.find_bit(q).index for q in instr.qubits]
            sub = QuantumCircuit(len(local))
            sub.append(instr.operation, range(len(local)))
            out_dag.apply_operation_back(
                LoweredOp.fixed(sub, name=instr.operation.name),
                [regs[i][lq] for lq in local],
                [],
            )

    clbit_idx = 0
    for node, logical_qubits, lop in lowered_ops:
        physical_wires = [regs[i][w] for i in logical_qubits for w in range(wpl)]

        if isinstance(node.op, Measure):
            phys_clbits: list[Clbit] = [node.cargs[0]] + [
                meas_cr[clbit_idx + j] for j in range(lop.num_clbits - 1)
            ]
            clbit_idx += lop.num_clbits - 1
        elif isinstance(node.op, ControlFlowOp):
            phys_clbits = list(node.cargs)
        else:
            phys_clbits = []

        out_dag.apply_operation_back(lop, physical_wires, phys_clbits)

    perm = (dag.metadata or {}).get("logical_output_permutation")
    return LoweredProgram(
        dag=out_dag,
        enc=enc,
        wires=tuple(tuple(reg) for reg in regs),
        logical_output_permutation=(
            tuple(perm) if perm is not None else tuple(range(n_logical))
        ),
    )
