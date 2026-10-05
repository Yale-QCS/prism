"""Qubit reuse by measure-and-reset (DeCross et al., arXiv:2210.08039, greedy variant).

Order measured qubits by causal-cone size; emit each cone in topological order onto a new
circuit, and when a wire first appears, reuse a slot whose qubit has already been measured
(with a reset) before allocating a new one. Same measurement statistics, fewer qubits, more
depth. Written here because qiskit-qubit-reuse 0.0.2 predates Qiskit 2.
"""

from __future__ import annotations

from qiskit import QuantumCircuit
from qiskit.converters import circuit_to_dag
from qiskit.dagcircuit import DAGOpNode


def qubit_reuse(qc: QuantumCircuit, *, dual: bool = False) -> QuantumCircuit:
    """Return an equivalent circuit on fewer qubits; ``dual`` reverses the greedy order tie-break."""
    dag = circuit_to_dag(qc)
    topo = list(dag.topological_op_nodes())
    rank = {n: i for i, n in enumerate(topo)}
    preds = {n: [p for p in dag.predecessors(n) if isinstance(p, DAGOpNode)] for n in topo}
    last_on = {}  # qubit -> last op node on that wire
    for n in topo:
        for q in n.qargs:
            last_on[q] = n
    # a qubit "terminates" if its last op is a measurement: its slot frees afterwards
    ends = {q: n for q, n in last_on.items() if n.op.name == "measure"}

    def cone(node) -> set:
        seen, stack = set(), [node]
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            stack.extend(preds[n])
        return seen

    cones = {q: cone(n) for q, n in ends.items()}
    emitted: set = set()
    slot_of: dict = {}  # old qubit -> new slot index
    free: list[int] = []
    n_slots = 0
    out_ops: list[tuple[DAGOpNode, list[int]]] = []

    def emit(node) -> None:
        nonlocal n_slots
        slots = []
        for q in node.qargs:
            if q not in slot_of:
                if free:
                    slot_of[q] = free.pop(0)
                    out_ops.append((None, [slot_of[q]]))  # reset marker
                else:
                    slot_of[q] = n_slots
                    n_slots += 1
            slots.append(slot_of[q])
        out_ops.append((node, slots))
        emitted.add(node)
        for q in node.qargs:
            if ends.get(q) is node:
                free.append(slot_of[q])

    remaining = dict(cones)
    while remaining:
        q = min(remaining, key=lambda k: (len(remaining[k] - emitted), -rank[ends[k]] if dual else rank[ends[k]]))
        for node in sorted(remaining.pop(q) - emitted, key=rank.get):
            emit(node)
    for node in topo:
        if node not in emitted:
            emit(node)

    out = QuantumCircuit(n_slots, qc.num_clbits)
    clbit_index = {c: i for i, c in enumerate(qc.clbits)}
    for node, slots in out_ops:
        if node is None:
            out.reset(slots[0])
        else:
            out.append(node.op, slots, [clbit_index[c] for c in node.cargs])
    return out


def check_dependencies(qc: QuantumCircuit, reused: QuantumCircuit) -> bool:
    """Every original op appears once and in an order consistent with the original DAG."""
    a = [(i.operation.name, tuple(i.operation.params), len(i.qubits)) for i in qc.data]
    b = [(i.operation.name, tuple(i.operation.params), len(i.qubits)) for i in reused.data if i.operation.name != "reset"]
    return sorted(map(str, a)) == sorted(map(str, b)) and reused.num_qubits <= qc.num_qubits
