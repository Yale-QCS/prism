---
name: project_realization_corrections
description: The four CRZ realizations are DISTINCT gates reconciled by diagonal corrections from the equivalence library; NO Pauli-frame tracking exists at commit; the paper must never claim frame tracking
metadata: 
  node_type: memory
  type: project
  originSessionId: e2a7ab98-a8fb-40c9-9006-b356f910443b
---

User correction 2026-06-11, verified against `dualrail.py`. The four rail
pairings of a logical CRZ are not the same gate up to a tracked frame; they
are distinct gates reconciled inside each candidate circuit. Mechanism
(dualrail.py `crz()`): `Z_L = Z_a = -Z_b`, so a target on the b-rail flips
the rotation sign (use angle −θ), and a control on the b-rail is an
ANTI-control at the logical level, absorbed via the codespace-safe identity
`open-control CRZ(α) ≡ CRZ(−α) · RZ(α)_target`. The X-sandwich alternative
would need X_L, which is avoided (it maps |00> to |11>, breaking the
absorbing erasure state), so every correction is diagonal and
delocalization-compatible, which is the nontrivial fact the compiler relies
on. Logical SWAP (dualrail.py `swap()`): the rail-aligned pairing is two
bare swaps; the crossed pairing realizes SWAP_L·(X_L⊗X_L) and is corrected
by INTRA-PAIR swaps, chosen because intra-pair SWAP preserves |00>/|11>
while X⊗X would scramble them. The equivalence library
(`build_equivalence_library`, synthesis/delocal_decomp.py) is the named
home of these identities. There is NO Pauli-frame tracking at commit
anywhere in the implementation (PauliFramePropagation is an unrelated
logical-stage reshape pass).

**Why:** earlier paper drafts claimed "equivalent up to a Pauli-frame
correction recorded at commit and never emitted," which misdescribes the
implementation and undersells a good story (corrections could have broken
delocalization and provably do not).

**How to apply:** the paper says each candidate carries its own diagonal
correction generated from the equivalence library; never write
frame-tracking language for realizations. The narrative beat belongs in S4
(compile a gate into any candidate, insert the fixing gates, observe they
are diagonal). See [[feedback_dualrail_rules_leakage_cost]].
