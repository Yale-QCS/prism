# PRISM

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![CI](https://github.com/evmckinney9/prism/actions/workflows/ci.yml/badge.svg)](https://github.com/evmckinney9/prism/actions/workflows/ci.yml)

PRISM is a Qiskit transpiler for dual-rail qubits.
In the dual-rail encoding a logical qubit is carried by a pair of physical modes, so one logical gate has several physical realizations that touch different wires.
PRISM keeps every realization of each gate through lowering and picks one at routing time, against the live layout.

```bash
pip install git+https://github.com/evmckinney9/prism
```

Building from source needs a Rust toolchain.

```python
from qiskit import QuantumCircuit
from qiskit.transpiler import CouplingMap
from qiskit.passmanager import PropertySet
from prism.encodings import DualRail
from prism.pipeline import build_pm

qc = QuantumCircuit(4)
qc.h(0)
for i in range(3):
    qc.cx(i, i + 1)

pm = build_pm(CouplingMap.from_grid(2, 4), enc=DualRail, seed=42)
ps = PropertySet()
routed = pm.run(qc, property_set=ps)
print(ps["circuit_metrics"])
```

`ps` holds `circuit_metrics`, `realization_choices`, `online_n_swaps` and `logical_output_permutation`.
`routed.layout` is a rail-level `TranspileLayout`: virtual qubit `2*i + w` is rail `w` of logical qubit `i`, so `routed.layout.final_index_layout()[2*i + w]` is where that rail ends, the elided logical permutation included.

The coupling map must be connected and symmetric, with at least two physical qubits per logical qubit.
The only supported control flow is `if_else`. Its blocks may contain only single-qubit gates and no measurement; an `if_else` over several qubits is lowered as one `if_else` per qubit, so its blocks must not write classical bits.
Other inputs raise a `ValueError` (bad `build_pm` arguments) or a `TranspilerError` (an unsupported circuit).

## Pipeline

`build_pm` returns a Qiskit `MultiStagePassManager`. Every prism pass is a `GenericPass[IN, OUT]`.

| Stage | IR | Passes |
| --- | --- | --- |
| `input` | `QuantumCircuit -> DAGCircuit` | `CircuitToDAG` |
| `logical` | `DAGCircuit` | stock passes to the encoding's logical gate set; logical SWAPs are elided |
| `dag_to_multi_realization` | `DAGCircuit -> MultiRealization` | `DAGToMultiRealization`: each gate becomes its encoding rule |
| `routing` | `MultiRealization` | `PrismRouting`: placement and every realization choice |
| `multi_realization_to_dag` | `MultiRealization -> DAGCircuit` | `MultiRealizationToDAG`: materializes the choices, writes the layout |
| `physical` | `DAGCircuit` | the stock O3 preset (no layout or routing) and prism's rail passes |
| `output` | `DAGCircuit -> QuantumCircuit` | `DAGToCircuit` |

Replace a stage by assigning it, for example `pm.routing = [MyPass(), PrismRouting(cmap)]`.
A callback gets `passmanager_ir` as a `QuantumCircuit`, `DAGCircuit` or `MultiRealization`.

## The `MultiRealization` IR

`prism.ir.MultiRealization` is an ordered list of `MultiRealizationInstruction(operation, qubits, clbits)`, like `QuantumCircuit.data`.
An operation is a regular Qiskit operation or a `MultiRealizationOp`: one logical gate with its `candidates` (circuits on the gate's rails), the encoding's `default_index`, a `diagonal` flag, and a `choice`.
Constraint passes may shrink `candidates`; decision passes set `choice`, and a later pass may revise it.
`placement` (initial and final virtual-to-physical maps) is `None` until routing.
Before placement, instruction qubits are rail indices; after it, they are physical qubits, a routing SWAP is a regular `swap`, and a sub-routed gate is its chosen candidate's gates with SWAPs between them.
`MultiRealizationToDAG` is the only step that drops candidates: it needs a placement and a choice on every `MultiRealizationOp`.
`ir.verify()` checks the invariants; it runs after the entrance and before the exit.

A `MultiRealization` pass is a `GenericPass[MultiRealization, MultiRealization]`.
This one keeps only the encoding's default candidate of every `crz`:

```python
from dataclasses import replace
from qiskit.passmanager import GenericPass
from prism.ir import MultiRealization, MultiRealizationOp
from prism.routing import PrismRouting


class PinDefaultCRZ(GenericPass[MultiRealization, MultiRealization]):
    def run(self, passmanager_ir: MultiRealization) -> MultiRealization:
        for k, ins in enumerate(passmanager_ir.data):
            op = ins.operation
            if isinstance(op, MultiRealizationOp) and op.name == "crz":
                pinned = replace(
                    op, candidates=(op.candidates[op.default_index],), default_index=0
                )
                passmanager_ir.data[k] = ins._replace(operation=pinned)
        return passmanager_ir


cmap = CouplingMap.from_grid(2, 4)
pm = build_pm(cmap, enc=DualRail)
pm.routing = [PinDefaultCRZ(), PrismRouting(cmap)]
```

Citation: TODO, once the paper is out.

> [!IMPORTANT]
> This software is provided as-is with no guarantee of support or maintenance.
> AI tools were used to assist in writing code in this repository.
> Bug reports and pull requests are welcome. For more information, see [the contribution guide](https://github.com/evmckinney9/prism/blob/main/.github/CONTRIBUTING.md).
