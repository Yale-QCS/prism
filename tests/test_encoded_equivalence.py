"""The compiled rail circuit implements the logical circuit under the encoding."""

import numpy as np
import pytest
from qiskit import QuantumCircuit
from qiskit.circuit import ClassicalRegister
from qiskit.circuit.library import QFTGate
from qiskit.circuit.random import random_circuit
from qiskit.quantum_info import Statevector
from qiskit.transpiler import CouplingMap, PassManager

from prism import SearchBudget, dualrail_pm, prism_stages
from prism.ir import MultiRealization

BUDGET = SearchBudget(layout_starts=4, refinement_iterations=2, swap_trials=4)


def _logical(seed: int, n: int = 3) -> QuantumCircuit:
    """Random logical circuit with plenty of commuting diagonal gates on shared qubits."""
    rng = np.random.default_rng(seed)
    qc = random_circuit(n, 4, max_operands=2, seed=seed)
    for _ in range(6):
        a, b = rng.choice(n, 2, replace=False)
        qc.crz(float(rng.uniform(0.1, 3)), int(a), int(b))
        qc.rz(float(rng.uniform(0.1, 3)), int(a))
    return qc


def _trailing_swap(seed: int) -> QuantumCircuit:
    """Random circuit ending in an unmeasured SWAP (the logical stage must record it)."""
    qc = random_circuit(3, 4, max_operands=2, seed=seed)
    qc.swap(1, 2)
    return qc


def _trailing_x(seed: int) -> QuantumCircuit:
    """Random circuit ending in unmeasured X, a rail SWAP the physical stage must keep."""
    qc = random_circuit(3, 4, max_operands=2, seed=seed)
    qc.x(0)
    qc.crz(0.4, 1, 2)
    qc.x(2)
    return qc


def _conditional(seed: int) -> QuantumCircuit:
    """``if_else`` over all three qubits between entangling gates; ``_take`` picks a branch."""
    qc = random_circuit(3, 3, max_operands=2, seed=seed)
    qc.add_register(ClassicalRegister(1))
    with qc.if_test((qc.clbits[0], False)) as else_:
        qc.rx(0.3, 0)
        qc.x(1)
        qc.rz(0.7, 2)
    with else_:
        qc.x(0)
        qc.rx(1.1, 2)
    qc.crz(0.5, 0, 2)
    qc.crz(0.9, 1, 0)
    return qc


def _mid_swaps(seed: int) -> QuantumCircuit:
    """Logical SWAPs between entangling gates: the elided permutation must reach the layout."""
    qc = random_circuit(3, 3, max_operands=2, seed=seed)
    qc.swap(0, 1)
    qc.crz(0.7, 1, 2)
    qc.swap(1, 2)
    qc.rx(0.3, 0)
    return qc


def _take(qc: QuantumCircuit, branch: int) -> QuantumCircuit:
    """``qc`` with every ``if_else`` replaced by its block ``branch`` (Statevector has no control flow)."""
    out = qc.copy_empty_like()
    for ins in qc.data:
        if ins.operation.name == "if_else":
            out.compose(
                ins.operation.blocks[branch], ins.qubits, ins.clbits, inplace=True
            )
        else:
            out.append(ins)
    return out


def _overlap(qc: QuantumCircuit, out: QuantumCircuit) -> float:
    """Overlap of ``out`` with the dual-rail encoding of ``qc``'s state.

    Rail ``w`` of logical qubit ``i`` is virtual qubit ``2i + w`` on ``final_index_layout()``;
    |0_L> = |01> (rail 1 excited), |1_L> = |10>; spare qubits are |0>.
    """
    final = out.layout.final_index_layout()
    expected = np.zeros(2**out.num_qubits, dtype=complex)
    for idx, amp in enumerate(Statevector(qc).data):
        bits = ((idx >> i) & 1 for i in range(qc.num_qubits))
        rails = (2 * i + (0 if b else 1) for i, b in enumerate(bits))
        expected[sum(1 << final[v] for v in rails)] += amp
    return abs(np.vdot(expected, Statevector(out).data))


def verify_ir(*, dag, **_):
    """Callback: full ``verify`` after every pass that returns a ``MultiRealization``."""
    if isinstance(dag, MultiRealization):
        dag.verify()


@pytest.mark.parametrize(
    "make", [_logical, _trailing_swap, _trailing_x, _conditional, _mid_swaps]
)
@pytest.mark.parametrize("seed", [0, 1])
def test_routed_rails_match_encoded_logical_state(make, seed):
    qc = make(seed)
    pm = dualrail_pm(CouplingMap.from_grid(2, 4), seed=seed, budget=BUDGET)
    compiled = pm.run(qc, callback=verify_ir)
    branch = seed % 2  # the branch an if_else takes, in both circuits
    overlap = _overlap(_take(qc, branch), _take(compiled, branch))
    assert overlap == pytest.approx(1.0, abs=1e-6)


def test_op_the_router_passes_through_warns_and_stays_correct():
    """Without the logical stage a SWAP spans two rail pairs; the physical stage routes it."""
    qc = QuantumCircuit(3)
    qc.rx(0.3, 0)
    qc.rx(1.1, 1)
    qc.crz(0.5, 0, 1)
    qc.swap(0, 2)
    qc.crz(0.9, 2, 1)
    qc.rx(0.7, 0)
    stages = prism_stages(CouplingMap.from_grid(2, 4), seed=0, budget=BUDGET)
    stages.logical = PassManager()
    with pytest.warns(UserWarning, match="passed 1 operation"):
        out = PassManager([stages.to_flow_controller()]).run(qc)
    assert _overlap(qc, out) == pytest.approx(1.0, abs=1e-6)


def _clbit_probabilities(qc: QuantumCircuit, clbits) -> dict[int, float]:
    """Exact distribution of ``clbits`` (bit k of the key = ``clbits[k]``), enumerating measurement branches."""
    qc = qc.decompose(["pauli_product_measurement", "initialize"])
    rail = np.arange(2**qc.num_qubits)

    def run(data, branches, wire):
        """Apply ``data`` to each ``(bits, probability, state)``; ``wire`` maps block bits outward."""
        for ins in data:
            op, qargs = ins.operation, [qc.find_bit(wire[q]).index for q in ins.qubits]
            if op.name == "measure":
                bit, split = wire[ins.clbits[0]], []
                for bits, p, sv in branches:
                    for m, pm in enumerate(sv.probabilities(qargs)):
                        if pm > 1e-12:
                            kept = (rail >> qargs[0] & 1) == m
                            post = Statevector(sv.data * kept / np.sqrt(pm))
                            split.append(({**bits, bit: m}, p * pm, post))
                branches = split
            elif op.name == "if_else":
                cond, value = op.condition
                taken = []
                for branch in branches:
                    blocks = op.blocks[branch[0].get(wire[cond], 0) != value :]
                    if not blocks:
                        taken.append(branch)
                        continue
                    inner = dict(zip(blocks[0].qubits, ins.qubits, strict=True))
                    inner |= dict(zip(blocks[0].clbits, ins.clbits, strict=True))
                    inner = {k: wire[v] for k, v in inner.items()}
                    taken += run(blocks[0].data, [branch], inner)
                branches = taken
            else:
                branches = [(bits, p, sv.evolve(op, qargs)) for bits, p, sv in branches]
        return branches

    start = [({}, 1.0, Statevector.from_int(0, 2**qc.num_qubits))]
    identity = {b: b for b in (*qc.qubits, *qc.clbits)}
    out: dict[int, float] = {}
    for bits, p, _ in run(qc.data, start, identity):
        key = sum(bits.get(c, 0) << k for k, c in enumerate(clbits))
        out[key] = out.get(key, 0.0) + p
    return out


def _random_measured(mc: bool) -> QuantumCircuit:
    """Random circuit, an optional MCX, a logical SWAP and an X, then measured."""
    qc = random_circuit(4, 3, max_operands=2, seed=7)
    qc.h(range(3))
    if mc:
        qc.mcx([0, 1, 2], 3)
    qc.cx(0, 3)
    qc.swap(1, 2)
    qc.x(2)
    qc.add_register(ClassicalRegister(4))
    qc.measure(range(4), range(4))
    return qc


def _semiclassical() -> QuantumCircuit:
    """QFT, CRZs whose control or target is measured next, and a mid-circuit measurement."""
    qc = QuantumCircuit(4, 4)
    qc.rx(0.9, range(4))
    qc.append(QFTGate(4), range(4))
    qc.crz(0.6, 2, 3)
    qc.rx(0.5, 2)
    qc.measure(0, 0)
    with qc.if_test((qc.clbits[0], True)):
        qc.x(1)
    qc.crz(1.3, 1, 3)
    qc.measure(range(4), range(4))
    return qc


@pytest.mark.parametrize(
    ("cmap", "qc"),
    [
        # MCX adds an ancilla qubit
        (CouplingMap.from_grid(3, 4), _random_measured(mc=True)),
        (CouplingMap.from_grid(2, 5), _semiclassical()),
    ],
)
def test_measured_distribution_matches_logical(cmap, qc):
    """Logical clbits keep the logical distribution, also where measurement became classical control."""
    out = dualrail_pm(cmap, seed=3).run(qc)
    want = _clbit_probabilities(qc, qc.clbits)
    got = _clbit_probabilities(out, qc.clbits)  # logical clbits read rail 0
    assert got.keys() == want.keys()
    assert all(got[k] == pytest.approx(want[k], abs=1e-9) for k in want)
