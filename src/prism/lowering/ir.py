"""The boundary IR: ``LoweredOp`` nodes in a rail-wire DAG, wrapped by ``LoweredProgram``.

``LoweredOp`` is an ``Operation`` carrying candidate physical realizations. It
lives in a ``DAGCircuit`` over physical wires; its ``num_qubits`` is the union
of wires any realization could touch (for dependency tracking). Commit picks a
realization and substitutes it via ``substitute_node_with_dag``.

``LoweredProgram`` is what crosses the logical-physical boundary as a typed
stage IR: the DAG plus the state a DAG cannot carry (wire binding, the elided
logical permutation, and the commit decision with its optional routed handoff).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from qiskit.circuit import Operation, QuantumCircuit, Qubit
from qiskit.converters import circuit_to_dag, dag_to_circuit
from qiskit.dagcircuit import DAGCircuit
from qiskit.transpiler import Layout

if TYPE_CHECKING:
    from prism.encodings.base import QubitEncoding
    from prism.lowering.commit import CommitResult


class LoweredOp(Operation):
    """A logical op paired with its candidate physical realizations."""

    def __init__(
        self,
        realizations: Sequence[QuantumCircuit],
        *,
        default_index: int = 0,
        name: str = "lowered",
    ) -> None:
        """Validate the realization set and record its shared widths."""
        reals = tuple(realizations)
        if not reals:
            raise ValueError("LoweredOp must have at least one realization")
        widths = {qc.num_qubits for qc in reals}
        if len(widths) != 1:
            raise ValueError(
                f"All realizations must have identical num_qubits; got {sorted(widths)}"
            )
        clwidths = {qc.num_clbits for qc in reals}
        if len(clwidths) != 1:
            raise ValueError(
                f"All realizations must have identical num_clbits; got {sorted(clwidths)}"
            )
        if not 0 <= default_index < len(reals):
            raise ValueError(
                f"default_index {default_index} out of range for {len(reals)} realizations"
            )
        self.realizations = reals
        self.default_index = default_index
        # The op name is namespaced (``crz`` -> ``crz_L``) so no stock pass that
        # keys on standard gate names (``CommutativeCancellation`` and friends)
        # mistakes a boundary op for the gate it lowers. ``logical_name`` keeps
        # the original for dispatch and accounting.
        self.logical_name = name
        self._name = f"{name}_L"
        self._num_qubits = reals[0].num_qubits
        self._num_clbits = reals[0].num_clbits

    def copy(self, name: str | None = None) -> LoweredOp:
        """Shallow copy (realizations are immutable circuits); ``name`` is the logical name."""
        return LoweredOp(
            self.realizations,
            default_index=self.default_index,
            name=self.logical_name if name is None else name,
        )

    @classmethod
    def fixed(cls, qc: QuantumCircuit, *, name: str = "lowered") -> LoweredOp:
        """Single-realization ``LoweredOp``."""
        return cls((qc,), name=name)

    @classmethod
    def decision(
        cls,
        candidates: Sequence[QuantumCircuit],
        *,
        default_index: int = 0,
        name: str = "lowered",
    ) -> LoweredOp:
        """Multi-realization ``LoweredOp`` with the encoding's canonical pick."""
        cands = tuple(candidates)
        if len(cands) < 2:
            raise ValueError(
                f"decision() expects 2+ candidates; got {len(cands)} — use fixed() instead"
            )
        return cls(cands, default_index=default_index, name=name)

    @property
    def name(self) -> str:
        """Operation name."""
        return self._name

    @property
    def num_qubits(self) -> int:
        """Number of wires every realization spans."""
        return self._num_qubits

    @property
    def num_clbits(self) -> int:
        """Number of clbits every realization touches."""
        return self._num_clbits

    @property
    def is_fixed(self) -> bool:
        """True when there is exactly one realization."""
        return len(self.realizations) == 1

    @property
    def is_decision(self) -> bool:
        """True when there are multiple realizations to pick from."""
        return len(self.realizations) > 1


def apply_commits(dag: DAGCircuit, choices: Sequence[int]) -> DAGCircuit:
    """Substitute, in place, each ``LoweredOp`` with its chosen realization.

    ``choices`` is in decision-op topological order; fixed ops use index 0.
    """
    choice_iter = iter(choices)
    for node in list(dag.topological_op_nodes()):
        if not isinstance(node.op, LoweredOp):
            continue
        lop: LoweredOp = node.op
        idx = next(choice_iter) if lop.is_decision else 0
        dag.substitute_node_with_dag(node, circuit_to_dag(lop.realizations[idx]))
    return dag


@dataclass(frozen=True)
class LoweredProgram:
    """Boundary IR: a rail-wire DAG of ``LoweredOp`` nodes plus what the DAG cannot hold.

    ``wires[i]`` are logical qubit ``i``'s rails. ``logical_output_permutation`` is the elided input
    permutation. The commit stage fills ``choices`` and, for routing-aware
    policies, ``layout`` and the chip-coordinate ``routed_dag`` with its
    ``routed_final_layout`` (one correctness unit: both or neither).
    Instrumentation (swap counts, search traces) stays in the property set.
    """

    dag: DAGCircuit
    enc: type[QubitEncoding]
    wires: tuple[tuple[Qubit, ...], ...]
    logical_output_permutation: tuple[int, ...] = ()
    choices: tuple[int, ...] | None = None
    layout: Layout | None = None
    routed_dag: DAGCircuit | None = None
    routed_final_layout: Layout | None = None

    @property
    def n_logical(self) -> int:
        """Number of logical qubits."""
        return len(self.wires)

    @property
    def is_committed(self) -> bool:
        """True once a commit policy has chosen realizations."""
        return self.choices is not None

    def with_commit(self, result: CommitResult) -> LoweredProgram:
        """Return the program with a policy's decision attached."""
        if result.routed_dag is not None and result.routed_final_layout is None:
            raise ValueError("CommitResult.routed_dag requires routed_final_layout")
        return replace(
            self,
            choices=tuple(result.choices),
            layout=result.layout,
            routed_dag=result.routed_dag,
            routed_final_layout=result.routed_final_layout,
        )

    def committed_dag(self) -> DAGCircuit:
        """The rail-wire DAG with every realization substituted (``dag`` is left intact)."""
        if self.choices is None:
            raise ValueError("LoweredProgram is not committed")
        copy = circuit_to_dag(
            dag_to_circuit(self.dag, copy_operations=False), copy_operations=False
        )
        return apply_commits(copy, self.choices)
