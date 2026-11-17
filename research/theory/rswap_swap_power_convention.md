---
name: rswap-swap-power-convention
description: "RSwapGate is exactly SWAP^(theta/pi) since 2026-07-28; before that it was the XY/beamsplitter matrix, and the two differ only by a logical global phase"
metadata: 
  node_type: memory
  type: project
  originSessionId: 3c11191a-a68f-4b4b-9b82-32126006192f
  modified: 2026-07-28T18:13:30.951Z
---

`RSwapGate(theta)` (`src/marabbecca/synthesis/rswap.py`) is defined as exactly
`SwapGate().power(theta/pi)` (principal branch), with `_define` =
`rxx(t/2)*ryy(t/2)*rzz(t/2)` + `global_phase=t/4`. Until 2026-07-28 the matrix
was the beamsplitter XY exchange `exp(-i(t/4)(XX+YY))` (identity on
{|00>,|11>}, iSWAP-family, `rswap(pi)^2 = ZZ`). The two conventions differ by
the phase `e^{i t/2}` on the single-excitation sector only, a logical global
phase: physically equivalent on a dual-rail block (both leave |00> and |11>
untouched; principal SWAP powers act as identity on the symmetric sector).
Verified at the switch: full test suite 273 passed, quick_bench bit-identical
(same-seed). Their Weyl classes differ: SWAP^t at fold(t/2,t/2,t/2) vs XY at
(t/2,t/2,0) in gulps units; this is the c3 = sector-relative-phase freedom of
the admissible completion line ([[brod-galvao-can-closed-form]]). Under the
SWAP-power convention `rswap(theta) = M(I, X^{theta/pi})`, so the executed
realization coincides with the canonical A=I completion (the paper Fig. 3 red
points: SWAP for X, SWAP^{1/2} for sqrt(X)).
