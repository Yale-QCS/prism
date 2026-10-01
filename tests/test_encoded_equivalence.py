"""End-to-end semantics: the routed rail circuit implements the logical circuit under the encoding."""

import numpy as np
import pytest
from qiskit import QuantumCircuit
from qiskit.circuit.random import random_circuit
from qiskit.quantum_info import Statevector
from qiskit.transpiler import CouplingMap

from prism.encodings import DualRail
from prism.lowering.commit import SearchBudget
from prism.lowering.commit_policies.prism_routing import PrismRouting
from prism.pipeline import build_pm


def _logical(seed: int, n: int = 3) -> QuantumCircuit:
    """Random logical circuit with plenty of commuting diagonal gates on shared qubits."""
    rng = np.random.default_rng(seed)
    qc = random_circuit(n, 4, max_operands=2, seed=seed)
    for _ in range(6):
        a, b = rng.choice(n, 2, replace=False)
        qc.crz(float(rng.uniform(0.1, 3)), int(a), int(b))
        qc.rz(float(rng.uniform(0.1, 3)), int(a))
    return qc


def _encode(logical_state: np.ndarray, n: int) -> np.ndarray:
    """|b_1..b_n> -> rails (wire0, wire1) = |01> for 0, |10> for 1; wire order follows the lowering registers."""
    out = np.zeros(2 ** (2 * n), dtype=complex)
    for idx, amp in enumerate(logical_state):
        if abs(amp) < 1e-14:
            continue
        rails = 0
        for i in range(n):
            bit = (idx >> i) & 1  # qiskit little-endian: qubit i is bit i
            w0, w1 = 2 * i, 2 * i + 1
            rails |= ((bit) << w0) | ((1 - bit) << w1)
        out[rails] += amp
    return out


@pytest.mark.parametrize("commute", [False, True])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_routed_rails_match_encoded_logical_state(commute, seed):
    PrismRouting.COMMUTE_DIAGONAL = commute
    try:
        n = 3
        qc = _logical(seed, n)
        cmap = CouplingMap.from_grid(2, 4)  # 8 rails: 3 logical pairs + one spare
        pm = build_pm(
            cmap,
            enc=DualRail,
            seed=seed,
            budget=SearchBudget(
                layout_starts=4, refinement_iterations=2, swap_trials=4
            ),
        )
        out = pm.run(qc)
        ps = pm.property_set
        # virtual rail v starts at initial[v] and ends at final[initial[v]]
        initial = ps["layout"]
        final = ps["final_layout"]
        virt_qubits = list(initial.get_virtual_bits())
        end_pos = {}
        for v_qubit in virt_qubits:
            p0 = initial[v_qubit]
            end_pos[v_qubit] = final[out.qubits[p0]]
        # lowering registers q0..q{n-1}, wires (0, 1) -> virtual index 2i + w
        by_index = {}
        for v_qubit, pos in end_pos.items():
            reg = v_qubit._register
            by_index[2 * int(reg.name[1:]) + v_qubit._index] = pos
        sv_out = Statevector(out).data
        expected_rails = _encode(Statevector(qc).data, n)
        # place expected rail state at the final physical positions, spare rails |0>
        n_phys = out.num_qubits
        expected = np.zeros(2**n_phys, dtype=complex)
        for rail_idx, amp in enumerate(expected_rails):
            if abs(amp) < 1e-14:
                continue
            phys = 0
            for v in range(2 * n):
                if (rail_idx >> v) & 1:
                    phys |= 1 << by_index[v]
            expected[phys] += amp
        overlap = abs(np.vdot(expected, sv_out))
        assert overlap == pytest.approx(1.0, abs=1e-6), f"overlap {overlap}"
    finally:
        PrismRouting.COMMUTE_DIAGONAL = True
