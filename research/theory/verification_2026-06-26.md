# Morning report: overnight on the paper (2026-06-26)

Two deliverables: (1) I **verified the load-bearing theory the paper asserts but
never shows** (the audit's T1.4/T1.8 "asserts theorems it doesn't exhibit / punts
proofs to a nonexistent artifact"), turning assertions into evidence and changing
two decisions; (2) a **mean-reviewer harsh report + safe prose/rigor polish** across
every section. Build clean throughout (`latexmk`, exit 0, 22pp). Numbers + the line
regression remain the sibling's lane; I changed no number values.

- Verification code + full findings: `research/theory/`
  (`README.md` + 4 runnable scripts, repo venv: `.venv/bin/python`).
- Harsh per-section review + reviewer verdict: `research/rebuttal/background/harsh_review_2026-06-26.md`.
- Clean read (no scaffolding): `delocal_dualrail/build/main_acm_CLEAN_noscaffolding.pdf`.

## 1. What the verification found (the substance)

**The foundation is solid (was punted to "the artifact").** By conjugating every
realization back through the encoding isometry:
- All four CRZ rail-pairings are exactly equivalent and each equals logical CRZ(θ);
  both SWAP partitions = SWAP; X, RZ faithful. The §4.3 relaxation-soundness claim
  ("candidates exactly equivalent by construction") is now verified, not asserted.
- RepCode (X/Z×3/CX×6) and Iceberg (X×2/Z×4/CX×8) realizations are ALL faithful.
  The §6.3 Iceberg orbit rows a reviewer would spot-check: verified. Generality of
  the IR/orbit construction holds for all three codes.
- The gate-set theorem (§3.2, the placement-dependent-ISA headline): verified by
  Weyl-coordinate sweep. The delocalizable 1Q gates are exactly O(2) = {Rz, Rz·X, X};
  H, √X, Ry, Rx have no local completion (perfect entanglers). "Every √X completion
  is a perfect entangler" holds. This is the math foundation of the whole framing.

**Two findings that change what the paper should say:**
- **§3.3 is an asset, not a liability.** I'd first flagged the split-thickness /
  K₆ / degree-bound material as decorative + unverified and said cut it. I ran it
  instead: the degree saturation is EXACT (2Δ-2 at co-location → 2Δ at separation 3,
  flat beyond, on a 7×7 grid: 6,7,8,8), the bipartite K₂ ceiling holds, and a
  zero-swap K₆ embedding on a 2×6 grid EXISTS (brute force over all 10395 pairings).
  Keep it and *exhibit* it. One precision fix already applied: the K₆ requires all
  six qubits delocalized (no co-located-rail K₆ exists), so I corrected "all fifteen
  pairs adjacent" → "all fifteen interactions nearest-neighbor, every qubit
  delocalized" (`03:151`), which is both honest and stronger (the clique is bought
  by spending delocalization). The witness pairing is the figure your `03:57` note
  asked for.
- **Port parallelism is a theorem the paper is calling a conjecture, and it's the
  strongest depth result in the document.** A dual-rail qubit is a 2-port device, so
  an abelian CRz layer of max-demand-degree Δ has depth floor exactly ⌈Δ/2⌉ (vs Δ for
  a fused-node IR, an up-to-2× win). I confirmed achievability by explicit
  2-factorization on K₄..K₉, 3/4/5/6-regular, path, ring (all hit ⌈Δ/2⌉). §8:40
  hedges this VERIFY/SOFTEN; it follows from Petersen 2-factorization and is
  verified. State it as a result; the genuinely open part is physical achievability
  under routing, which §8 already identifies.

**One real (minor) defect, code side:** the init herald `CRZ(π)` is logical S† =
`diag(1,-i)` on the codespace, NOT "codespace-identity" as `dualrail.py:41` and
memory `project_init_crz_herald` claim. Harmless (it only ever acts on the prepared
|0_L⟩, the control-off state, where it is identity) but the label is wrong. Fix the
docstring + memory; not in the paper, so no paper edit.

**Re-scope for the sibling (with a caveat I corrected):** Iceberg's x/z/cx orbits
are provably faithful, so the n=3 blocker is NOT in the gate realizations. But my
check covered the per-gate orbits, NOT the multi-block chained INIT at n=3, so I
cannot claim "not faithfulness" outright, it could be an init-faithfulness bug I
didn't test, or emission. What's settled: the orbit table is sound and the IR
carries to all three codes; the n=3 hunt should start at the chained init, not the
gate orbits.

## 2. Prose/rigor polish applied (safe, non-destructive, builds clean)

Notation `G(A,B)`→`M(A,B)` (your flagged collision); title→pinned; typo; 3 `\evm`
flags resolved in place. Rigor framing in abstract + §1 (own the baseline, drop
unsupported 94%/25-of-25/"two codes", "predicts"→"tracks", scope fidelity to yield +
coherence-sensitive state fidelity); magnitude values left for the sibling.
Readability splits of the worst over-compressed sentences in §1,§2,§3.2,§4,§6,§7;
conclusion broken into two beats. Full inline list in the harsh review.

## 3. Needs you (author decisions; not enacted)

- Promote the quotient reduction (`03:161`) to a named Proposition ahead of the
  connectivity-class material (`conceptual_spine.md` §3); §3.3 verification above
  makes this safe to lean on.
- §6 demote cadence (largest subsection, not a contribution; prime page recovery).
- Defend trial-parity in one sentence + report seed spread (3-seed mean, no variance
  under per-circuit win claims).
- The reviewer verdict (harsh_review.md top) lists the 5 reject-counts and what flips
  each to accept.

## 4. Sibling (numbers + regression)

Line regression shown as a result (`05:100`) → delete once fixed, not soften.
Cross-section number disagreements are a two-snapshot mismatch → regenerate from one
run. Reconcile "predicts/+0.70/density law" across abstract/§1/§5.4/§8.1 together;
the pick-share correlation recomputes to ≈0, the defensible version is realization
slack (density × spread), see harsh_review T1.3 / `conceptual_spine.md` §5.
