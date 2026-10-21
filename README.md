# PRISM

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![CI](https://github.com/evmckinney9/prism/actions/workflows/ci.yml/badge.svg)](https://github.com/evmckinney9/prism/actions/workflows/ci.yml)

PRISM is a Qiskit transpiler for dual-rail qubits, where each logical qubit is a pair of physical modes (rails).
A logical gate then has several physical realizations on different rails; PRISM keeps all of them through lowering and picks one per gate while routing.

```bash
pip install --pre prism-qc
```

## Quickstart

```python
import numpy as np
from qiskit import QuantumCircuit
from qiskit.transpiler import CouplingMap
from prism import ErasureCheck, dualrail_pm

qc = QuantumCircuit(3, 3)
qc.rx(np.pi / 2, [0, 1, 2])
qc.crz(np.pi / 2, 0, 1)
qc.append(ErasureCheck(), [1], [1])
qc.crz(np.pi / 2, 1, 2)
qc.rx(np.pi / 2, [1, 2])
qc.measure(range(3), range(3))

pm = dualrail_pm(CouplingMap.from_line(6), seed=7)
out = pm.run(qc)
print(pm.property_set["circuit_metrics"])
```

```text
CircuitMetrics(swaps=0, depth=6, active_gates=13, size=18)
```

![The input circuit](https://raw.githubusercontent.com/evmckinney9/prism/main/docs/quickstart_input.png)

![The compiled circuit](https://raw.githubusercontent.com/evmckinney9/prism/main/docs/quickstart_output.png)

Rails `q<i>_0` and `q<i>_1` carry logical qubit `i`.
`EarlyMeasurement` measures qubit 0 right after its first `crz`, which becomes an `rz` conditioned on its bit.
A measurement writes rail 0, the logical bit, to `c[i]` and rail 1 to `c_rail1[i]`; both 0 means the photon was lost.
`dualrail_pm(..., budget=SearchBudget(objective="depth"))` prefers depth over SWAPs.

## Gate set

| Logical | Physical, on the qubit's rails |
| --- | --- |
| `rz(θ)` | `rz(θ)` on rail 0 |
| `rx(θ)` | `rswap(θ)`, the exponential SWAP of the two rails |
| `x` | `swap` of the two rails |
| `crz(θ)` | `crz(±θ)` from either rail of the control to either rail of the target: four candidates |
| `swap` | none: the logical stage relabels the qubits |
| `measure` | `measure` on both rails |
| `reset`, and preparation | `Initialize("10")` on the two rails |
| `ErasureCheck` | `PauliProductMeasurement(Pauli("ZZ"))` on the two rails: 1 if the photon is there, without disturbing the logical state |
| `if_else` | `if_else` on the qubit's rails |

The physical `Target` allows the two-rail operations only on device edges, so no stock pass can leave the code space. No gate moves across an `ErasureCheck`.

Limits:

- The coupling map must be connected, with at least two physical qubits per logical qubit.
- `if_else` is the only control flow; its blocks hold single-qubit gates and no measurement.
- A multi-controlled X with three or more controls uses an idle qubit as a clean ancilla, or adds one (register `mcd_anc`).
- Barriers are dropped.

## Pipeline

`prism.prism_stages(coupling_map)` is a `MultiStagePassManager`. Its passes are in `prism.passes`:

| Stage | IR | Passes |
| --- | --- | --- |
| `logical` | `DAGCircuit` | stock passes and a dual-rail equivalence library to the logical gate set, then `EarlyMeasurement` |
| `dag_to_multi_realization` | `DAGCircuit -> MultiRealization` | each operation becomes a `MultiRealizationOp` with its candidates |
| `multi_realization` | `MultiRealization` | `ElideRailExchanges` and `PrismRouting` (layout, routing and a `choice` per op) |
| `multi_realization_to_dag` | `MultiRealization -> DAGCircuit` | each choice becomes gates, with the layout |
| `physical` | `DAGCircuit` | stock cleanups, stock layout and routing of unrouted operations, `CommutativeOptimization`, `RescheduleCommutingDiagonals` |

Any pass that sets every `choice` is a complete `multi_realization` stage. The physical stage then lays out and routes with stock Qiskit:

```python
import random

from qiskit.passmanager import GenericPass
from qiskit.transpiler import PassManager
from prism import prism_stages
from prism.ir import MultiRealization, MultiRealizationOp


class RandomChoice(GenericPass[MultiRealization, MultiRealization]):
    def run(self, passmanager_ir: MultiRealization) -> MultiRealization:
        for ins in passmanager_ir.data:
            if isinstance(op := ins.operation, MultiRealizationOp):
                op.choice = random.randrange(len(op.candidates))
        return passmanager_ir


stages = prism_stages(CouplingMap.from_line(6))
stages.multi_realization = [RandomChoice()]
out = PassManager([stages.to_flow_controller()]).run(qc)
```

## Development

```bash
make init  # .venv, editable install, git hooks
make test
```

Citation: TODO, once the paper is out.

> [!IMPORTANT]
> This software is provided as-is with no guarantee of support or maintenance.
> AI tools were used to assist in writing code in this repository.
> Bug reports and pull requests are welcome. For more information, see [the contribution guide](https://github.com/evmckinney9/prism/blob/main/.github/CONTRIBUTING.md).
