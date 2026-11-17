# theory_verification (2026-06-26)

Computational verification of the paper claims that the draft asserts but does not
exhibit (peer-review audit T1.4 "asserts theorems it doesn't exhibit", T1.8
"load-bearing math punted to a nonexistent artifact"). Run with the repo venv:
`.venv/bin/python verify_realizations.py` and `verify_graph_claims.py`.

## verify_realizations.py - the realization-equivalence foundation (§3.2, §4.1, §4.3)

Conjugates each candidate's physical unitary back through the dual-rail isometry
and compares. Results (theta=0.7):

- **All four CRZ rail-pairings are exactly equivalent** (identical up to one global
  phase, relative phases intact) **and each equals logical CRZ(theta)**:
  `diag(1,1,e^{-i theta/2},e^{+i theta/2})`. The sign-flip + open-control-RZ
  corrections in `dualrail.py:134-145` are faithful. This is the claim §4.3's
  relaxation-soundness rests on; it is now verified, not asserted. VERIFIED.
- Both SWAP partitions = logical SWAP; X -> X_L; RZ -> RZ_L. VERIFIED.
- **Init herald `CRZ(pi)` is NOT codespace-identity.** As a codespace operator it is
  `diag(1,-i)` = logical S-dagger. It acts as identity only on the prepared
  `|0_L>=|01|>` (the control-off state), so the init is functionally correct, but
  the description "codespace-identity" (`dualrail.py:41`, memory
  `project_init_crz_herald`) is imprecise. Correct statement: "diagonal,
  leakage-free, identity on the prepared codeword." PRECISION FIX.

## verify_graph_claims.py - the §3.3 connectivity-class claims

Brute force + neighborhood counting on grids. Results:

- **Degree saturation, EXACT**: on a triangle-free grid (Delta=4) the quotient
  degree of a logical node is `2*Delta-2 = 6` at co-location (sep 1), 7 at sep 2,
  and saturates to `2*Delta = 8` at sep 3, flat beyond. Matches the paper's "+2
  quotient edges, two SWAPs from co-location, nothing past separation 3" exactly.
  VERIFIED.
- **K_6 on a 2x6 grid EXISTS but requires delocalized rails.** All 10395 pairings
  searched: a zero-swap K_6 embedding exists (all 15 logical interactions
  nearest-neighbor), but NONE with co-located (grid-adjacent) rails - every qubit
  must be delocalized (rails >=2 apart). One witness:
  `[((0,0),(1,2)),((0,1),(0,3)),((1,0),(0,4)),((0,2),(1,4)),((1,1),(1,5)),((1,3),(0,5))]`.
  The paper's "all fifteen pairs adjacent" is ambiguous (reads as co-located, which
  is false). Honest + stronger statement: dual-rail reaches K_6 zero-swap precisely
  by spending delocalization on all six qubits. This witness is the figure the
  `\evm` note at `03:57` asked for. CLAIM HOLDS, PROSE NEEDS PRECISION.
- Bipartite grid has zero triangles -> bare-qubit zero-swap clique ceiling is K_2.
  VERIFIED.

## verify_generality.py - the "carries other codes" claim (abstract, §5.5, §6.3)

Same isometry conjugation, generalized to k wires/logical and entangled codewords.

- **RepCode [[3,1]]**: X (1 realization), Z (3, the stabilizer-mult orbit), CX (6,
  the S_3 permutation orbit) - all equal the intended logical gate. VERIFIED.
- **Iceberg [[4,1,2]]**: X (2), Z (4), CX (8, the partition-preserving S_4 subgroup)
  - all equal the intended logical gate. VERIFIED. This is exactly the §6.3
  BLOCK-TODO spot-check (Iceberg Z=4, CX=8 rows); it passes, the marker can clear.
- **The Iceberg trouble is NOT in the gate-realization orbits.** The x/z/cx orbits
  are faithful, so the open n=3 issue (`05:170` "chained-init faithfulness issue")
  is not a gate-orbit problem. CAVEAT: this verification covered the per-gate orbits
  on single/two blocks, NOT the multi-block chained INIT at n=3, so it does not rule
  out an init-faithfulness bug there; whether the n=3 blocker is init-faithfulness or
  emission is still open (sibling). What IS settled: the IR/orbit construction
  carries to all three codes faithfully (the §6.3 orbit table is sound).

## verify_port_parallelism.py - the §8 depth-floor conjecture (VERIFY/SOFTEN)

A dual-rail qubit is a 2-port device, so an abelian CRz layer with demand graph of
max degree Delta has depth floor = min number of max-degree-<=2 subgraphs that
edge-decompose it. Lower bound ceil(Delta/2) (2 edges cleared per node per step).

- **The floor is achieved for every demand graph tested** (K_4..K_9, 3/4/5/6-regular,
  path, ring), confirmed by explicit edge-disjoint 2-factorization (Eulerian
  orientation -> k-regular bipartite -> k perfect matchings = constructive Petersen):
  `got == ceil(Delta/2)`, valid decomposition, max degree 2. So the floor is EXACTLY
  ceil(Delta/2), versus Delta for a fused-node IR: a guaranteed up-to-2x depth win on
  dense abelian layers (QAOA, Trotter, QFT).
- **This is a theorem, not a conjecture.** §8:40 hedges it VERIFY/SOFTEN ("the value
  we conjecture a port-aware assignment can reach"); it follows from Petersen
  2-factorization and is confirmed here. The paper can state the abstract floor as a
  result and scope the open question precisely to PHYSICAL achievability (the two
  ports are physical rails that must reach their partners under routing). The earlier
  draft's prior-cite of split-thickness for this formula was wrong (audit T2.6); the
  right basis is 2-factorization.

## verify_gateset.py - the gate-set theorem (§3.2, the placement-dependent-ISA headline)

Sweeps the completion A over U(2) and reads the Weyl coordinates of the matchgate
M(A,B) to ask: which logical 1Q gates B have a LOCAL (delocalizable) completion?

- Rz(theta) (diagonal), Rz(theta)X (anti-diagonal), X (pole flip): a local
  completion exists (Weyl distance 0). DELOCALIZABLE.
- H, sqrt(X), Ry(theta), Rx(theta): no completion is local (min Weyl ~0.35-0.79).
  PERFECT ENTANGLERS.
- => the delocalized 1Q ISA is exactly O(2) = {Rz} u {Rz X}, matching Eq.
  (delocal-group). "Every sqrt(X) completion is a perfect entangler" (§3.2):
  VERIFIED. X is the anti-diagonal pole flip, erasure-rejected in practice (it maps
  |00><->|11|>), leaving the phase rotations as the usable delocalized set.

This is the mathematical foundation of the placement-dependent-ISA framing; it was
asserted in the draft (audit T1.4 flagged the maximal-ISA claim as unproven). The 1Q
characterization is now verified. (Maximality over arbitrary multi-mode operations,
T1.4's stricter reading, is still not addressed here.)

## verify_lever_negative.py - the §8.1 reshape obstruction (Cartan measure-zero)

- The CRZ(theta) family lies exactly on the (a,0,0) Weyl line (a=theta/4, b=c=0 for
  all theta); 8/8 random SU(4) are off it. So the delocalized entangler is a
  measure-zero slice of SU(4), and generic 2Q blocks need a basis change to reach it.
- H.Rz.H = Rx confirmed: the basis change is a non-diagonal 1Q gate (co-location
  class) that local rewriting cannot slide to a boundary. This is why pre-lowering
  reshape is a near-no-op on 24/26 circuits (§8.1). VERIFIED. The gate-set theorem,
  the density law, and this reshape obstruction are one measure-zero-line fact in
  three places.

## NOT verified here (left for the bib/author)

Eppstein `ceil(Delta/2)` split-thickness bound and the Delta=5 tightness (`03:147`)
are literature claims (cite, not recompute).
