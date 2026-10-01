"""Early measurement preserves the measured distribution, through lowering and routing too."""

import numpy as np
import pytest
from qiskit import QuantumCircuit
from qiskit.circuit.library import QFTGate
from qiskit.circuit.random import random_circuit
from qiskit.converters import circuit_to_dag, dag_to_circuit
from qiskit.quantum_info import Statevector
from qiskit.transpiler import CouplingMap

from prism.encodings import DualRail
from prism.lowering.commit import SearchBudget
from prism.pipeline import build_pm
from prism.synthesis.early_measure import EarlyMeasurement

IDENTITY_LIKE = {"barrier", "joint_herald"}


def distribution(qc: QuantumCircuit, creg_name: str) -> dict[str, float]:
    """Exact output distribution over ``creg_name`` by enumerating measurement branches."""
    n = qc.num_qubits
    qidx = {q: i for i, q in enumerate(qc.qubits)}
    cidx = {c: i for i, c in enumerate(qc.clbits)}
    creg = next(r for r in qc.cregs if r.name == creg_name)

    def apply(instrs, branches):
        for instr in instrs:
            op, qs = instr.operation, [qidx[q] for q in instr.qubits]
            if op.name in IDENTITY_LIKE:
                continue
            if op.name == "measure":
                k, c = qs[0], cidx[instr.clbits[0]]
                new = []
                for psi, bits in branches:
                    idx = np.arange(2**n)
                    for m in (0, 1):
                        proj = psi * (((idx >> k) & 1) == m)
                        p = float(np.vdot(proj, proj).real)
                        if p > 1e-12:
                            new.append((proj, {**bits, c: m}))
                branches = new
            elif op.name == "if_else":
                cond_bit, value = op.condition
                body = op.blocks[0]
                inner_q = {
                    body.qubits[i]: instr.qubits[i] for i in range(len(instr.qubits))
                }
                inner_c = {
                    body.clbits[i]: instr.clbits[i] for i in range(len(instr.clbits))
                }
                mapped = [
                    type(bi)(
                        bi.operation,
                        [inner_q[q] for q in bi.qubits],
                        [inner_c[c] for c in bi.clbits],
                    )
                    for bi in body.data
                ]
                taken = [b for b in branches if b[1].get(cidx[cond_bit], 0) == value]
                rest = [b for b in branches if b[1].get(cidx[cond_bit], 0) != value]
                branches = apply(mapped, taken) + rest
            else:
                branches = [
                    (Statevector(psi).evolve(op, qargs=qs).data, bits)
                    for psi, bits in branches
                ]
        return branches

    psi0 = np.zeros(2**n, dtype=complex)
    psi0[0] = 1.0
    out: dict[str, float] = {}
    for psi, bits in apply(qc.data, [(psi0, {})]):
        key = "".join(str(bits.get(cidx[c], 0)) for c in reversed(creg))
        out[key] = out.get(key, 0.0) + float(np.vdot(psi, psi).real)
    return out


def _cases():
    qft = QuantumCircuit(3, 3, name="qft")
    qft.h(0)
    qft.crz(0.7, 0, 1)
    qft.append(QFTGate(3), range(3))
    qft.measure(range(3), range(3))
    rng = np.random.default_rng(3)
    rand = random_circuit(3, 4, max_operands=2, seed=3)
    rand = QuantumCircuit(3, 3).compose(rand)
    for _ in range(4):
        a, b = rng.choice(3, 2, replace=False)
        rand.crz(float(rng.uniform(0.2, 2.5)), int(a), int(b))
        rand.rz(float(rng.uniform(0.2, 2.5)), int(b))
    rand.measure(range(3), range(3))
    return [qft, rand]


def _close(a, b):
    keys = set(a) | set(b)
    return all(abs(a.get(k, 0.0) - b.get(k, 0.0)) < 1e-9 for k in keys)


@pytest.fixture(autouse=True)
def _early_measure_on():
    DualRail.early_measure = True
    yield
    DualRail.early_measure = False


@pytest.mark.parametrize("qc", _cases())
def test_logical_rewrite_preserves_distribution(qc):
    logical = DualRail.logical_pm().run(qc)  # includes EarlyMeasurement
    assert logical.count_ops().get("if_else", 0) > 0
    assert _close(distribution(qc, "c"), distribution(logical, "c"))


@pytest.mark.parametrize("qc", _cases())
def test_routed_rails_preserve_distribution(qc):
    pm = build_pm(
        CouplingMap.from_grid(2, 4),
        enc=DualRail,
        seed=1,
        budget=SearchBudget(layout_starts=3, refinement_iterations=2, swap_trials=3),
    )
    out = pm.run(qc)
    assert _close(distribution(qc, "c"), distribution(out, "c"))


def test_pass_is_idempotent_and_skips_when_nothing_qualifies():
    qc = QuantumCircuit(2, 2)
    qc.h(0)
    qc.crz(0.3, 0, 1)
    qc.h(1)  # non-diagonal after the crz on both operands
    qc.h(0)
    qc.measure(range(2), range(2))
    dag = circuit_to_dag(qc)
    once = EarlyMeasurement().run(dag)
    assert dag_to_circuit(once).count_ops().get("if_else", 0) == 0
    assert dag_to_circuit(EarlyMeasurement().run(once)) == dag_to_circuit(once)
