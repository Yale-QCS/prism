# PRISM

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![CI](https://github.com/evmckinney9/prism/actions/workflows/ci.yml/badge.svg)](https://github.com/evmckinney9/prism/actions/workflows/ci.yml)

PRISM is a Qiskit transpiler for dual-rail qubits.
In the dual-rail encoding a logical qubit is carried by a pair of physical modes (rails), so one logical gate has several physical realizations that touch different rails.
PRISM keeps every realization of each gate through lowering and picks one at routing time, against the live layout.

```bash
pip install git+https://github.com/evmckinney9/prism
```

Building from source needs a Rust toolchain.

## Quickstart

```python
from qiskit import QuantumCircuit
from qiskit.transpiler import CouplingMap
from prism.encodings import DualRail, ErasureCheck
from prism.pipeline import SearchBudget, build_pm

qc = QuantumCircuit(3, 4)
qc.h(0)
qc.cx(0, 1)
qc.append(ErasureCheck(), [1], [3])  # clbit 3 reads 1 unless the photon was lost
qc.cx(1, 2)
qc.measure(range(3), range(3))

pm = build_pm(
    CouplingMap.from_line(6), DualRail, seed=7, budget=SearchBudget(objective="depth")
)
out = pm.run(qc)

print(pm.property_set["circuit_metrics"])
print(qc.draw(cregbundle=False))
print(out.draw(idle_wires=False, fold=-1, cregbundle=False))
```

The input:

```text
     ┌───┐                       ┌─┐  
q_0: ┤ H ├──■────────────────────┤M├───────────
     └───┘┌─┴─┐┌────────────────┐└╥┘     ┌─┐  
q_1: ─────┤ X ├┤0               ├─╫───■──┤M├───
          └───┘│                │ ║ ┌─┴─┐└╥┘┌─┐
q_2: ──────────┤                ├─╫─┤ X ├─╫─┤M├
               │                │ ║ └───┘ ║ └╥┘
c_0: ══════════╡                ╞═╩═══════╬══╬═
               │  Erasure_check │         ║  ║
c_1: ══════════╡                ╞═════════╩══╬═
               │                │            ║
c_2: ══════════╡                ╞════════════╩═
               │                │  
c_3: ══════════╡0               ╞══════════════
               └────────────────┘  
```

The output, on rails `q<i>_0` and `q<i>_1` of logical qubit `i` (`CircuitMetrics(swaps=0, depth=7, active_gates=14, size=22)`):

- each logical qubit starts with `Initialize` on its two rails;
- `h` and `cx` become `rz`, `rswap` and one `crz`, and each `crz` uses the pair of rails the router chose for it;
- the erasure check is a ZZ measurement on the qubit's two rails;
- each measurement reads both rails, the second into `herald`.

```text
          ┌──────────────────┐┌──────────┐┌──────────────┐                                                        ┌─────────────┐┌─┐  
q2_0 -> 0 ┤0                 ├┤ Rz(-π/2) ├┤0             ├────────────────────────────────────────────────────────┤0            ├┤M├───
          │  Initialize(1,0) │└──────────┘│  Rswap(-π/2) │                                               ┌───────┐│  Rswap(π/2) │└╥┘┌─┐
q2_1 -> 1 ┤1                 ├────────────┤1             ├───────────────────────────────────────────────┤ Rz(π) ├┤1            ├─╫─┤M├
          ├──────────────────┤┌──────────┐├──────────────┤         ┌─────────────┐┌─────────┐┌──────────┐└───┬───┘└─────┬─┬─────┘ ║ └╥┘
q1_0 -> 2 ┤0                 ├┤ Rz(-π/2) ├┤0             ├─────────┤0            ├┤ Rz(π/2) ├┤0         ├────■──────────┤M├───────╫──╫─
          │  Initialize(1,0) │└──────────┘│  Rswap(-π/2) │┌───────┐│  Rswap(π/2) │└─────────┘│          │   ┌─┐         └╥┘       ║  ║
q1_1 -> 3 ┤1                 ├────────────┤1             ├┤ Rz(π) ├┤1            ├───────────┤1         ├───┤M├──────────╫────────╫──╫─
          ├──────────────────┤┌──────────┐├──────────────┤└───┬───┘└─┬──────────┬┘    ┌─┐    │          │   └╥┘          ║        ║  ║
q0_0 -> 4 ┤0                 ├┤ Rz(-π/2) ├┤0             ├────■──────┤ Rz(-π/2) ├─────┤M├────┤          ├────╫───────────╫────────╫──╫─
          │  Initialize(1,0) │└──────────┘│  Rswap(-π/2) │   ┌─┐     └──────────┘     └╥┘    │          │    ║           ║        ║  ║
q0_1 -> 5 ┤1                 ├────────────┤1             ├───┤M├───────────────────────╫─────┤          ├────╫───────────╫────────╫──╫─
          └──────────────────┘            └──────────────┘   └╥┘                       ║     │  PPM(ZZ) │    ║           ║        ║  ║
     c_0: ════════════════════════════════════════════════════╬════════════════════════╩═════╡          ╞════╬═══════════╬════════╬══╬═
                                                              ║                              │          │    ║           ║        ║  ║
     c_1: ════════════════════════════════════════════════════╬══════════════════════════════╡          ╞════╬═══════════╩════════╬══╬═
                                                              ║                              │          │    ║                    ║  ║
     c_2: ════════════════════════════════════════════════════╬══════════════════════════════╡          ╞════╬════════════════════╩══╬═
                                                              ║                              │          │    ║                       ║
     c_3: ════════════════════════════════════════════════════╬══════════════════════════════╡0         ╞════╬═══════════════════════╬═
                                                              ║                              └──────────┘    ║                       ║
herald_0: ════════════════════════════════════════════════════╩══════════════════════════════════════════════╬═══════════════════════╬═
                                                                                                             ║                       ║
herald_1: ═══════════════════════════════════════════════════════════════════════════════════════════════════╩═══════════════════════╬═
                                                                                                                                     ║
herald_2: ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╩═

```

`build_pm` returns a Qiskit `PassManager`. After a run, `pm.property_set` holds `circuit_metrics`, `online_n_swaps` (routing SWAPs) and `logical_output_permutation`.
`out.layout` is a rail-level `TranspileLayout`: virtual qubit `2*i + w` is rail `w` of logical qubit `i`.
`SearchBudget` sets the layout search effort and the objective, `"swaps"` (default) or `"depth"`.
A measurement writes the logical bit from rail 0 and the other rail to a `herald` register.

## Gate sets

The logical stage translates the input to the logical gate set; each logical operation then lowers to one or more realizations on its rails.

| Logical | Physical realization on the rails |
| --- | --- |
| `rz(θ)` | `rz(θ)` on rail 0 |
| `rx(θ)` | `rswap(θ)`, the exponential SWAP between the qubit's two rails |
| `x` | `swap` between the qubit's two rails |
| `crz(θ)` | four candidates, one per rail pairing: `crz(±θ)` between a control rail and a target rail, with an `rz` on the target for an open control |
| `swap` | elided in the logical stage (a relabelling of logical qubits) |
| `measure` | `measure` on both rails |
| `reset`, and preparation at the start | `Initialize("10")` on the rail pair |
| `ErasureCheck` | `PauliProductMeasurement(Pauli("ZZ"))` on the rail pair: rail parity, which detects a lost photon without disturbing the logical state |
| `if_else` | an `if_else` on one qubit's rails with its blocks lowered |

The physical `Target` has `rz` on each rail and `crz`, `swap`, `rswap`, `initialize` and the ZZ measurement on each device edge, so preparation and erasure checks are physically local, and no stock pass can produce an operation that leaves the code space.

Input limits:

- The coupling map must be connected and symmetric, with at least two physical qubits per logical qubit.
- The only supported control flow is `if_else`. Its blocks may hold only single-qubit operations and no measurement. An `if_else` over several qubits is lowered as one `if_else` per qubit, so its blocks must not write classical bits.
- Barriers are removed in the logical stage, as Qiskit's optimization passes would cross them anyway.
- A multi-controlled X with three or more controls, or a multi-controlled phase of π with four or more, adds one clean ancilla logical qubit (register `mcd_anc`).
- Other inputs raise a `ValueError` (bad arguments) or a `TranspilerError` (an unsupported circuit).

## Pipeline

`prism_stages` returns a Qiskit `MultiStagePassManager[DAGCircuit, DAGCircuit]`; `build_pm` nests it in a `PassManager`, which converts the circuit to a DAG and back.
Every prism pass is a `GenericPass[IN, OUT]`.

| Stage | IR | Passes |
| --- | --- | --- |
| `logical` | `DAGCircuit` | stock passes to the logical gate set, the dual-rail equivalence library, SWAP elision |
| `dag_to_multi_realization` | `DAGCircuit -> MultiRealization` | `DAGToMultiRealization`: each operation becomes its realizations |
| `routing` | `MultiRealization` | `PrismRouting`: placement and a choice for every operation |
| `multi_realization_to_dag` | `MultiRealization -> DAGCircuit` | `MultiRealizationToDAG`: binds the choices, writes the layout |
| `physical` | `DAGCircuit` | the stock O3 preset over the dual-rail `Target` (layout kept; stock SABRE routes only operations `PrismRouting` passed through), stock `CommutativeOptimization`, diagonal rescheduling |

A callback gets the IR as `dag`: a `DAGCircuit` or a `MultiRealization`.

## The `MultiRealization` IR

`prism.ir.MultiRealization` is an ordered list of `MultiRealizationInstruction(operation, qubits, clbits)`, like `QuantumCircuit.data`.
An operation is a regular Qiskit operation or a `MultiRealizationOp`: one logical operation with its `candidates` (circuits on its rails), the encoding's `default_index`, a `diagonal` flag, and a `choice`.
Constraint passes may shrink `candidates`; decision passes set `choice`, and a later pass may revise it.
`MultiRealizationToDAG` is the only step that turns candidates into regular operations; it needs a placement and a choice on every `MultiRealizationOp`.
`placement` (initial and final virtual-to-physical maps and the device edges) is `None` until routing.
Before placement, instruction qubits are rail indices; after it, they are physical qubits and a routing SWAP is a regular `swap`.
`ir.verify()` checks the invariants; it runs after the entrance and before the exit.

A `MultiRealization` pass is a `GenericPass[MultiRealization, MultiRealization]`.
To add one, replace a stage of `prism_stages` and nest the stages yourself.
This pass keeps only the encoding's default candidate of every `crz`:

```python
from dataclasses import replace
from qiskit.passmanager import GenericPass
from qiskit.transpiler import PassManager
from prism.ir import MultiRealization, MultiRealizationOp
from prism.pipeline import prism_stages
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
stages = prism_stages(cmap, DualRail)
stages.routing = [PinDefaultCRZ(), PrismRouting(cmap)]
pm = PassManager([stages.to_flow_controller()])
out = pm.run(qc)
```

## Development

```bash
make init  # .venv, the package in editable mode, git hooks
make test  # Rust and Python tests, including the examples in this README
```

Citation: TODO, once the paper is out.

> [!IMPORTANT]
> This software is provided as-is with no guarantee of support or maintenance.
> AI tools were used to assist in writing code in this repository.
> Bug reports and pull requests are welcome. For more information, see [the contribution guide](https://github.com/evmckinney9/prism/blob/main/.github/CONTRIBUTING.md).
