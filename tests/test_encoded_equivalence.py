"""The compiled rail circuit implements the logical circuit under the encoding."""

import numpy as np
import pytest
from qiskit import QuantumCircuit
from qiskit.circuit import ClassicalRegister
from qiskit.circuit.random import random_circuit
from qiskit.quantum_info import Statevector
from qiskit.transpiler import CouplingMap, PassManager

from prism import dualrail_pm
from prism.encodings import DualRail, QubitEncoding
from prism.ir import MultiRealization, MultiRealizationOp
from prism.pipeline import SearchBudget, build_pm, prism_stages

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
    stages = prism_stages(CouplingMap.from_grid(2, 4), DualRail, seed=0, budget=BUDGET)
    stages.logical = PassManager()
    with pytest.warns(UserWarning, match="passed 1 operation"):
        out = PassManager([stages.to_flow_controller()]).run(qc)
    assert _overlap(qc, out) == pytest.approx(1.0, abs=1e-6)


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


class OneWire(QubitEncoding):
    """Each logical qubit on one wire: any encoding with rules compiles."""

    WIRES_PER_LOGICAL = 1
    LOGICAL_ISA = frozenset({"rz", "sx", "x", "cz", "measure"})
    PHYSICAL_ISA = frozenset({"rz", "sx", "x", "cz"})

    @classmethod
    def initialize(cls):
        return QuantumCircuit(1)

    @classmethod
    def _as_is(cls, op):
        qc = QuantumCircuit(op.num_qubits)
        qc.append(op, qc.qubits)
        return MultiRealizationOp(op.name, (qc,), diagonal=op.name in ("rz", "cz"))

    rz = sx = x = cz = _as_is


@pytest.mark.parametrize(
    ("enc", "cmap", "mc"),
    [
        (OneWire, CouplingMap.from_line(5), False),
        (DualRail, CouplingMap.from_grid(3, 4), True),  # MCX adds an ancilla qubit
    ],
)
def test_measured_distribution_matches_logical(enc, cmap, mc):
    """Logical clbits keep the logical distribution, through a logical SWAP and an X."""
    qc = random_circuit(4, 3, max_operands=2, seed=7)
    qc.h(range(3))
    if mc:
        qc.mcx([0, 1, 2], 3)
    qc.cx(0, 3)
    qc.swap(1, 2)
    qc.x(2)
    qc.add_register(ClassicalRegister(4))
    qc.measure(range(4), range(4))
    out = build_pm(cmap, enc=enc, seed=3).run(qc)
    want = _clbit_probabilities(qc, qc.clbits)
    got = _clbit_probabilities(out, qc.clbits)  # logical clbits read rail 0
    assert got.keys() == want.keys()
    assert all(got[k] == pytest.approx(want[k], abs=1e-9) for k in want)
