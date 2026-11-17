# PRISM, revision r3 (arXiv v1)

This branch reproduces every figure, table and printed number of the arXiv paper *PRISM: A Logical–Physical Boundary Compiler for Dual-Rail Qubits*. Start with [`REPRODUCE.md`](REPRODUCE.md).

The research code here is the package `marabbecca` on Qiskit 2.4.1, with every baseline and research arm. Raw result rows live under `artifacts/paper/` and `research/`. The maintained tool is the `prism-qc` package on the [`main`](https://github.com/Yale-QCS/prism) branch.

marabbecca is a Qiskit transpiler for encoded quantum circuits, where each logical qubit is carried by multiple physical wires and a single logical gate often has many equivalent physical realizations.

In the dual-rail encoding, each logical qubit is a pair of physical modes called rails: $|0_L\rangle = |01\rangle$ and $|1_L\rangle = |10\rangle$. A logical CRZ two-qubit gate needs only one rail from each pair to interact. The four (control-rail, target-rail) combinations all can implement a logical CRZ. All such candidates are equivalent on the codespace but touch different physical wires.

Standard Qiskit transpilation has to pick one candidate before layout and routing run. The best candidate is whichever has its 2Q sub-gates on adjacent qubits, but adjacency depends on the layout, and the best layout depends on which candidate routing is trying to satisfy. marabbecca breaks this loop by exposing the candidate set as a first-class IR node and deferring the commit until a downstream policy chooses one.

Four commit policies ship with the package. The most ambitious is `PrismRouting`, a SABRE variant whose front-layer score takes a *minimum* over each op's candidates, folding the realization choice into routing rather than fixing it beforehand.

___
### Getting Started

```bash
pip install -e .[dev]
```

```python
from qiskit.transpiler import CouplingMap
from marabbecca.staged_pms import build_pm
from marabbecca.encodings import DualRail

cmap = CouplingMap.from_grid(4, 4)  # 16 physical qubits → 8 dual-rail logical
pm = build_pm(cmap, enc=DualRail, strategy="prism")
pm.run(qc)
metrics = pm.property_set[
    "circuit_metrics"
]  # CircuitMetrics(swaps, depth, active_gates, size)
```

`strategy` is one of `"trivial"`, `"logical"` (Logical-SABRE), `"greedy"` (Greedy), or `"prism"` (PRISM). The returned `StagedPassManager` has three stages; only the lowering stage differs across strategies.

```bash
python research/benches/quick_bench.py   # 5 circuits, under a minute
python research/benches/full_bench.py    # every benchmark circuit
```

___
### `LoweredOp`

```python
class LoweredOp(Operation):
    realizations: tuple[QuantumCircuit, ...]
    default_index: int
```

- A `LoweredOp` IR node carries the candidate set for a logical operation.
- A `CommitPolicy` analysis pass writes the chosen realization per op to the property set.
- An `ApplyCommits` transformation substitutes each `LoweredOp` with its chosen realization.

```
QuantumCircuit on logical wires (any basis)
   │  logical    transpile into enc.LOGICAL_ISA
   ▼
QuantumCircuit over enc.LOGICAL_ISA
   │  lowering   LowerExpansion → CommitPolicy → ApplyCommits
   ▼
QuantumCircuit on physical wires
   │  physical   transpile into enc.PHYSICAL_ISA
   ▼
Routed circuit
```

___
### Commit policies

- **`trivial`** assigns each op its `default_index`, ignoring topology and layout.
- **`logical`** contracts the topology by collapsing each rail pair to a single node, then runs `SabreLayout` + `SabreSwap` on the resulting quotient graph. Each op commits to whichever realization places all its 2Q sub-gates on adjacent qubits under the produced layout, falling back to `default_index` if none does.
- **`greedy`** runs the same `PrismRouting` layout-and-routing search as `prism`, but fixes the nearest complete realization assignment at each routing call's entry layout. It is the paper's early-commitment arm.
- **`prism`** (Picking Realizations Inside Sabre Mapping) routes the multi-realization IR directly through `PrismRouting` instead of pre-committing realizations. When scoring the front layer to pick swaps, each multi-realization op contributes the minimum cost over its candidate realizations, so layout, routing, and realization choice are determined jointly:

  ```python
  def _op_cost(pairs_per_real, new_phys, dist) -> float:
      return min(
          sum(dist[new_phys(v1)][new_phys(v2)] for v1, v2 in real)
          for real in pairs_per_real
      )
  ```
