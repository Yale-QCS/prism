"""Code-space faithfulness of prism routing, per encoding.

Both prism and the baselines start from vacuum |0..0>, so the layout-normalized
output statevector (via Operator.from_circuit, which undoes initial/final
layout) is the cleanest ordering-free, code-space-agnostic faithfulness probe:
realizations may differ on the complement subspace, but the output state from
vacuum lives in the code space, so a faithful prism must match greedy exactly.

Findings 2026-06-17 (after the normalize-plain-ops fix in prism_routing):
  DualRail  n=2,3,4 : |<prism|greedy>|^2 = 1.0 AND |<prism|logical>|^2 = 1.0
  RepCode   n=2,3   : 1.0
  Iceberg   n=2     : 1.0
  Iceberg   n=3     : 0.0625 on seeds 1,42 (1.0 on seed 7)  <-- BUG
The Iceberg failure localizes to its multi-gate GHZ init (H,CX,CX,CX sharing a
hub wire): a chain of FIXED co-location ops where interleaved swaps corrupt the
emitted state on some layouts. DualRail (1Q init + multi-realization CRZ) and a
forced dual-rail rejoin-H are faithful, so the bug is the chained-fixed-coloc
case, not co-location-with-swap in general.
"""

from __future__ import annotations

import numpy as np
from qiskit import QuantumCircuit
from qiskit.quantum_info import Operator
from qiskit.transpiler import CouplingMap

from marabbecca.encodings import DualRail, Iceberg412, RepCode


def _out_state(enc, qc, cm, strat, seed):
    from marabbecca.staged_pms import build_pm

    pm = build_pm(cm, enc=enc, strategy=strat, seed=seed)
    out = pm.run(qc)
    U = Operator.from_circuit(out).data
    psi0 = np.zeros(U.shape[0], dtype=complex)
    psi0[0] = 1.0  # physical vacuum |0..0>
    return U @ psi0


def fidelity(enc, qc, cm, seed, refs=("greedy",)):
    """|<prism|ref>|^2 from vacuum, for each baseline ref."""
    sp = _out_state(enc, qc, cm, "prism", seed)
    return {r: abs(np.vdot(sp, _out_state(enc, qc, cm, r, seed))) ** 2 for r in refs}


def main():
    cases = [
        ("DualRail", DualRail, 3, CouplingMap.from_line(6), True, ("greedy", "logical")),
        ("RepCode", RepCode, 3, CouplingMap.from_grid(3, 3), False, ("greedy",)),
        ("Iceberg", Iceberg412, 3, CouplingMap.from_grid(2, 6), False, ("greedy",)),
    ]
    for name, enc, n, cm, universal, refs in cases:
        for seed in (1, 7, 42):
            qc = QuantumCircuit(n)
            if universal:
                qc.h(0)
            for i in range(n - 1):
                qc.cx(i, i + 1)
            fid = fidelity(enc, qc, cm, seed, refs)
            flag = "" if all(abs(v - 1) < 1e-6 for v in fid.values()) else "  <-- UNFAITHFUL"
            cells = "  ".join(f"|<p|{r}>|^2={v:.4f}" for r, v in fid.items())
            print(f"{name:9s} n={n} seed={seed}: {cells}{flag}")


if __name__ == "__main__":
    main()
