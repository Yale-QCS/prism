---
name: project_init_crz_herald
description: "DualRail entangling init is X+CRZ(π) erasure-check herald, not X+CX; CZ/CX KAK-synthesize into spurious rx"
metadata: 
  node_type: memory
  type: project
  originSessionId: 12e56f20-a335-4d1e-8209-9e2167a2f6d2
---

2026-06-18: `DualRail.initialize()` default is `X(1) + CRZ(π,0,1)`, the native
diagonal stand-in for a heralded prep's joint erasure check (QND occupation
measurement on the rail pair, which forces the two rails co-located at t=0).

**Why not CX (the old placeholder):** `CX(0,1)` is codespace-faithful only on
the prepared `|01⟩` (`CX|10⟩=|11⟩` leaves the codespace), and since neither `cx`
nor `cz` is in the physical ISA `{x,rx,rz,crz,swap,rswap}`, Qiskit KAK-synthesizes
them into `rx` (2 rx + extra rz per logical qubit). That was the source of the
"mystery RX pile" on every b-rail in rendered circuits. Only native `crz` avoids
it. `CRZ(π)` is diagonal (no population transfer) and emits zero rx.

**CORRECTION 2026-06-26 (verified, `scripts/research/theory_verification/`):**
`CRZ(π)` is NOT "identity on the whole codespace" as previously stated here. By
isometry conjugation it is logical `S† = diag(1, -i)` on `{|01⟩,|10⟩}`. It acts as
identity ONLY on the prepared `|0_L⟩=|01⟩` (the control-off state), so the init is
functionally correct (it only ever sees `|0_L⟩` at t=0) and the benchmark numbers
are unaffected, but the "codespace-identity" label (and the same phrase in
`dualrail.py:48`) is imprecise. Correct statement: diagonal, leakage-free, identity
on the prepared codeword, logical S† on the codespace generally.

**Impact:** removes a small per-qubit init overhead charged equally to every
strategy. A/B same-seed (quick_bench, grid4x4): prism **swaps identical** per
circuit (co-location demand intact), prism Σdepth drops a few (removed H-layer),
greedy unchanged, advantage preserved/slightly sharper; DualRail faithful 1.0.
So all v2 suite numbers shift slightly (swaps unaffected, depth ratios ~same);
the headline swap ladder is preserved exactly. **Regenerate v2 numbers on the
fixed init before promotion.** `local_init=True` (single-wire prep, no herald) is
the no-co-location ablation. See [[project_prism_vs_greedy_mechanism]],
[[reference_dualrail_noise_mehta_sws]].
