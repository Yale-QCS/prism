"""Direct commit: first all-adjacent realization per op, else ``default_index``.

Used by ``logical_pm`` after ``SabreLayout`` + ``SabreSwap`` on the chip
quotient. Quotient adjacency guarantees ≥1 inter-pair edge per 2Q op — enough
for single-2Q realizations (some CRZ candidate is fully adjacent) but not for
multi-2Q (SWAP needs 2 inter-pair edges). For SWAPs the rail-aligned default
(2 emitted) empirically beats the crossover (4 emitted) even when crossover
has more chip-adjacent matches; the only strict improvement is eliding the
SWAP into the layout via a permutation tracker.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from qiskit.dagcircuit import DAGCircuit
from qiskit.transpiler import CouplingMap, Layout

from marabbecca.lowering.commit import CommitPolicy, CommitResult
from marabbecca.lowering.ir import LoweredOp

if TYPE_CHECKING:
    from marabbecca.encodings.base import QubitEncoding


class DirectCommit(CommitPolicy):
    """Pick the first all-adjacent realization per op; ``default_index`` otherwise."""

    def __init__(
        self,
        coupling_map: CouplingMap,
        pairs: Sequence[tuple[int, ...]],
        *,
        enc: type[QubitEncoding],
    ) -> None:
        """Bind chip and per-logical wire assignment ``pairs`` (typically from quotient routing)."""
        if coupling_map is None or pairs is None:
            raise ValueError("DirectCommit requires coupling_map and pairs")
        super().__init__(enc=enc)
        self.coupling_map = coupling_map
        self.pairs = tuple(tuple(p) for p in pairs)

    def commit(self, dag: DAGCircuit) -> CommitResult:
        """Pick first all-adjacent realization (else default) and publish layout from ``pairs``.

        Logical permutations are elided before quotient routing, so every
        ``swap`` op here is a quotient-routing SWAP; ``n_swaps`` counts the
        physical SWAPs its selected realization lowers to.
        """
        flat = {q: i for i, q in enumerate(dag.qubits)}
        wpl = self.enc.WIRES_PER_LOGICAL
        choices: list[int] = []
        n_swaps = 0
        for node in dag.topological_op_nodes():
            if not isinstance(node.op, LoweredOp):
                continue
            lop: LoweredOp = node.op
            idx = lop.default_index if lop.is_decision else 0
            if lop.is_decision:
                qargs = node.qargs
                for cidx, realization in enumerate(lop.realizations):
                    qb = realization.qubits
                    all_adjacent = True
                    for ci in realization.data:
                        if len(ci.qubits) != 2:
                            continue
                        a = qb.index(ci.qubits[0])
                        b = qb.index(ci.qubits[1])
                        u = flat[qargs[a]]
                        v = flat[qargs[b]]
                        cu = self.pairs[u // wpl][u % wpl]
                        cv = self.pairs[v // wpl][v % wpl]
                        if self.coupling_map.distance(cu, cv) != 1:
                            all_adjacent = False
                            break
                    if all_adjacent:
                        idx = cidx
                        break
                choices.append(idx)
            if lop.name == "swap":
                n_swaps += lop.realizations[idx].count_ops().get("swap", 0)

        layout_dict = {
            dag.qubits[wpl * i + w]: pair[w]
            for i, pair in enumerate(self.pairs)
            for w in range(wpl)
        }
        return CommitResult(
            choices=tuple(choices), layout=Layout(layout_dict), n_swaps=n_swaps
        )
