---
name: brod-galvao-can-closed-form
description: "Closed-form Weyl/CAN coordinates for parity-preserving M(A,B) from Brod-Galvao PRA 84 022310; drives the analytic Fig 3 (completion plane, admissible line)"
metadata: 
  node_type: memory
  type: project
  originSessionId: 3c11191a-a68f-4b4b-9b82-32126006192f
  modified: 2026-07-28T18:13:40.058Z
---

Brod & Galvao (PRA 84, 022310 (2011), Eqs. 10-11 / Lemma III.1): for
$M(A,B)$ with $B$ on span{|01>,|10>}, $A$ on span{|00>,|11>}, the CAN
coordinates are ${(\theta+\phi)/2, (\phi-\theta)/2, \beta}$ with
$\cos\theta=|A_{11}|$, $\cos\phi=|B_{11}|$, $e^{2i\beta}=\det A$ (global phase
fixed so $\det A=\det B^{-1}$); matchgate iff $\beta=0$. gulps `weyl` units =
Zhang/pi (SWAP=(0.5,0.5,0.5)); convert Brod x2/pi then fold by the Weyl group
(coordinate shifts mod 1, permutations, pairwise sign flips; chamber
k1>=k2>=k3, k1+k2<=1). Verified to 4e-16 against `GateInvariants`.
Consequences used in paper Fig 3 (now fully analytic, script
`.claude/scripts/temp_diagnostics/regen_unitary_completions.py`): completion
set of a logical 1q gate = folded plane $c_1+c_2=2\phi$ (2-parameter surface,
NOT positive volume; touches a separable corner iff $\phi\in\{0,\pi/2\}$,
which re-derives $\mathcal{G}_{deloc}\cong O(2)$); loss-admissible diagonal-A
subset = line $c_1=c_2=\phi$ with only the sector-relative phase $c_3$ free
(for X: the SWAP-to-iSWAP-class edge; the fold explains the bent sqrt(X)
curve). X folded plane = 3 chamber triangles, sqrt(X) = 5. See
[[rswap-swap-power-convention]] for which point the ISA executes.
