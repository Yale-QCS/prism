"""Reorder commuting diagonal physical gates by critical path.

Routing emits gates in commit order. Physical diagonal gates on shared
rails commute, so the emitted order is one of many; this pass
re-emits the circuit by critical-path list scheduling over the
commutation-relaxed dependency graph, which only shortens the circuit.
"""

from qiskit.dagcircuit import DAGCircuit
from qiskit.transpiler import TransformationPass

from prism.ir import DIAGONAL_GATES, commuting_predecessors
from prism.metrics import is_free


class RescheduleCommutingDiagonals(TransformationPass):
    """Critical-path list scheduling over a dependency graph where diagonal gates commute."""

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Re-emit ``dag`` in a depth-minimizing order that respects the relaxed dependencies."""
        nodes = list(dag.topological_op_nodes())
        n = len(nodes)
        preds = commuting_predecessors(
            [(*node.qargs, *node.cargs) for node in nodes],
            [node.op.name in DIAGONAL_GATES for node in nodes],
        )
        succs: list[list[int]] = [[] for _ in range(n)]
        for k, ps in enumerate(preds):
            for p in ps:
                succs[p].append(k)
        weight = [0 if is_free(node.op) else 1 for node in nodes]
        cp = [0] * n
        for k in range(n - 1, -1, -1):
            cp[k] = weight[k] + max((cp[s] for s in succs[k]), default=0)
        done: dict[int, int] = {}
        wire_free: dict = {}
        remaining = set(range(n))
        out = dag.copy_empty_like()
        while remaining:
            ready = [k for k in remaining if all(p in done for p in preds[k])]
            ready.sort(key=lambda k: (-cp[k], k))
            for k in ready:
                node = nodes[k]
                wires = list(node.qargs) + list(node.cargs)
                start = max(
                    [done[p] for p in preds[k]]
                    + [wire_free.get(w, 0) for w in wires]
                    + [0]
                )
                done[k] = start + weight[k]
                for w in wires:
                    wire_free[w] = done[k]
                remaining.discard(k)
            # emit this wave in start-time order so the linear order is a valid schedule
            for k in sorted(ready, key=lambda k: (done[k] - weight[k], k)):
                node = nodes[k]
                out.apply_operation_back(node.op, node.qargs, node.cargs)
        return out
