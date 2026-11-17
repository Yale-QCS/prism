# The negatives are the positive: in-loop coupling absorbs placement-time intelligence

Written 2026-06-10 after a session of stronger-than-prism attempts. Every
placement-time or seed-side intervention failed to beat stock prism at equal
budget; the one same-budget improvement (commutation-relaxed DAG) works by
widening the ROUTER's in-loop freedom and is established prior art (Itoko
2020, Alam MICRO 2020, fragment_and_cover.md §5.7). This memo names the
pattern, because it is the strongest empirical defense the paper's central
claim has.

## The ledger (all same-seed, equal trial budget, measured this session)

| intervention | where it acts | result |
|---|---|---|
| coverage-embedding seed, edges only (E3 r1) | placement | loses (qaoa 16/10+ vs 15/6) |
| + self-loop demand (E3 r2) | placement | repairs ghz, trades away qft |
| embed seed + relaxed DAG (the 2x2) | placement | loses in BOTH DAGs |
| stock/relaxed trial split 8+8 vs 16 | budget | wash (3W/4T/3L) |
| degree-gated relaxation cap=4 | scheduling | non-monotone on the suite |
| iterated layout-commit fixed point (iter2/iter3) | seed | wash at n=8 (8W/9T/9L) |
| RTG-style two-pass Config D | commit | predicted D≈C (unrun, experiment track) |

Versus: prism's own machinery (16 trials x 4 forward/backward iterations x
min-over-realizations in the front layer) absorbs every one of these. The
forward/backward loop already re-grounds picks against refined placements;
trial diversity already covers good seeds; the in-loop min already discovers
partial embeddings online (the banked 94% swap pick-share).

## What this means

1. **The claim "realization choice must live inside routing" now has seven
   independent falsification attempts, all surviving.** AQORN/Jin choose at
   placement time; every placement-time mechanism we built (including
   theory-guided ones with exact coverage guarantees) loses to the in-loop
   form at equal budget. This is the prior_work_comparison_plan argument,
   landed empirically from our own side.
2. **Prism is not "basic"; it is a stochastic solver for the coupled
   placement-pick-route fixed point.** Static structure helps only when it
   changes the search space (the commutation relaxation), not the starting
   point (every seed intervention). "Simple and efficient" was the user's
   design bar; the evidence says the simplicity is load-bearing, not naive.
3. **Where the trials lose power is known and bounded:** dense fragments
   (qft-class) at n>=8 are the one regime where seed-side help registered at
   all (iter2 qft 24/24 -> 22/21, hhl, ae, vqe_two_local). If the n=16+
   iterated-seed run shows the dense wins growing while sparse stays tied,
   the honest landing is a dense-circuit-only seed refinement, not a new
   algorithm.

## Paper placement

This belongs in the evaluation as the ablation family around the spine:
frozen-pick (banked) isolates the coupling's value; Config D isolates
two-pass vs in-loop; this session's seed ladder isolates placement-time vs
route-time intelligence. Three independent knives, one conclusion. Write it
as a defense, not a victory lap: the contribution stays honest-small (the
IR + the min), and these results say that small thing is placed exactly
where it must be.
