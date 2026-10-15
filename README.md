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

The coupling map must be connected and symmetric, with at least two physical qubits per logical qubit.
The only supported control flow is `if_else`. Its blocks may contain only single-qubit gates; an `if_else` over several qubits is lowered as one `if_else` per qubit, so its blocks must not write classical bits.
Other inputs raise a `ValueError` (bad `build_pm` arguments) or a `TranspilerError` (an unsupported circuit).

Citation: TODO, once the paper is out.

> [!IMPORTANT]
> This software is provided as-is with no guarantee of support or maintenance.
> AI tools were used to assist in writing code in this repository.
> Bug reports and pull requests are welcome. For more information, see [the contribution guide](https://github.com/evmckinney9/prism/blob/main/.github/CONTRIBUTING.md).
