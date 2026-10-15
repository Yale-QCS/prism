"""End-to-end semantics: the routed rail circuit implements the logical circuit under the encoding."""

import numpy as np
import pytest
from qiskit import QuantumCircuit
from qiskit.circuit import ClassicalRegister
from qiskit.circuit.random import random_circuit
from qiskit.quantum_info import Statevector
from qiskit.transpiler import CouplingMap

from prism.encodings import DualRail
from prism.ir import MultiRealization
from prism.pipeline import SearchBudget, build_pm


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


def _mid_swaps(seed: int) -> QuantumCircuit:
    """Logical SWAPs between entangling gates: the elided permutation must reach the layout."""
    qc = random_circuit(3, 3, max_operands=2, seed=seed)
    qc.swap(0, 1)
    qc.crz(0.7, 1, 2)
    qc.swap(1, 2)
    qc.rx(0.3, 0)
    return qc


def _encode(logical_state: np.ndarray, n: int) -> np.ndarray:
    """|b_1..b_n> -> rails: virtual qubit ``2i + w`` is rail ``w`` of logical ``i``; |0_L> = |01>, |1_L> = |10>."""
    out = np.zeros(2 ** (2 * n), dtype=complex)
    for idx, amp in enumerate(logical_state):
        if abs(amp) < 1e-14:
            continue
        rails = 0
        for i in range(n):
            bit = (idx >> i) & 1  # qiskit little-endian: qubit i is bit i
            rails |= (bit << 2 * i) | ((1 - bit) << (2 * i + 1))
        out[rails] += amp
    return out


def verify_ir(*, passmanager_ir, **_):
    """Callback: full ``verify`` after every pass that returns a ``MultiRealization``."""
    if isinstance(passmanager_ir, MultiRealization):
        passmanager_ir.verify()


@pytest.mark.parametrize(
    "make", [_logical, _trailing_swap, _trailing_x, _conditional, _mid_swaps]
)
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_routed_rails_match_encoded_logical_state(make, seed):
    """The output state is the encoded logical state, rail ``v`` on ``final_index_layout()[v]``."""
    n = 3
    qc = make(seed)
    cmap = CouplingMap.from_grid(2, 4)  # 8 rails: 3 logical pairs + one spare
    pm = build_pm(
        cmap,
        enc=DualRail,
        seed=seed,
        budget=SearchBudget(layout_starts=4, refinement_iterations=2, swap_trials=4),
    )
    branch = seed % 2  # the branch an if_else takes, in both circuits
    compiled = pm.run(qc, callback=verify_ir)
    final = compiled.layout.final_index_layout()
    out = _take(compiled, branch)
    expected_rails = _encode(Statevector(_take(qc, branch)).data, n)
    # place expected rail state at the final physical positions, spare rails |0>
    expected = np.zeros(2**out.num_qubits, dtype=complex)
    for rail_idx, amp in enumerate(expected_rails):
        if abs(amp) < 1e-14:
            continue
        phys = sum(1 << final[v] for v in range(2 * n) if (rail_idx >> v) & 1)
        expected[phys] += amp
    overlap = abs(np.vdot(expected, Statevector(out).data))
    assert overlap == pytest.approx(1.0, abs=1e-6), f"overlap {overlap}"


def _clbit_probabilities(qc: QuantumCircuit, clbits) -> dict[int, float]:
    """Exact distribution of ``clbits`` (bit k of the key = ``clbits[k]``) for final measurements."""
    meas = {
        qc.find_bit(ins.clbits[0]).index: qc.find_bit(ins.qubits[0]).index
        for ins in qc.data
        if ins.operation.name == "measure"
    }
    targets = [meas[qc.find_bit(c).index] for c in clbits]
    probs = Statevector(qc.remove_final_measurements(inplace=False)).probabilities()
    out: dict[int, float] = {}
    for idx, p in enumerate(probs):
        if p > 1e-12:
            key = sum(((idx >> q) & 1) << k for k, q in enumerate(targets))
            out[key] = out.get(key, 0.0) + p
    return out


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_measured_output_matches_logical_distribution(seed):
    """Final measurements keep the logical distribution, logical SWAPs included."""
    qc = random_circuit(3, 4, max_operands=2, seed=seed)
    qc.x(0)
    qc.swap(1, 2)
    qc.crz(0.6, 0, 2)
    qc.x(2)
    qc.add_register(ClassicalRegister(3))
    qc.measure(range(3), range(3))
    pm = build_pm(
        CouplingMap.from_grid(2, 4),
        enc=DualRail,
        seed=seed,
        budget=SearchBudget(layout_starts=4, refinement_iterations=2, swap_trials=4),
    )
    out = pm.run(qc)
    want = _clbit_probabilities(qc, qc.clbits)
    got = _clbit_probabilities(out, qc.clbits)  # logical clbits read rail 0
    assert got.keys() == want.keys()
    assert all(got[k] == pytest.approx(want[k], abs=1e-9) for k in want)
