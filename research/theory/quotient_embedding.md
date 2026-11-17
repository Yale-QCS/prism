# Quotient embedding: placement for encoded qubits is inverse vertex splitting

Written 2026-06-10, the response to "impress me": the quotient-graph theory,
which the paper sets up and abandons, is the inverse of a named graph-theory
parameter with published theorems, and that identification changes what
PLACEMENT means for rail-encoded qubits, upgrades the density law to a
graph-theoretic predictor, reinterprets prism's measured win mechanism, and
yields a hand-verifiable demo no bare-qubit or fused-pair compiler can match.
Cross-refs: `conceptual_spine.md`, `port_parallelism.md`,
`research/rebuttal/background/prior_work_comparison_plan.md`.

## 1. The identification

A k-split of a graph H replaces each vertex by at most k copies such that
every H-edge has at least one copy-pair adjacent. The PLANAR SPLIT THICKNESS
of H is the least k such that H k-splits into a planar graph (Eppstein,
Kindermann, Kobourov et al., [arXiv:1512.04839](https://arxiv.org/abs/1512.04839),
Algorithmica 2017).

Dual-rail placement IS 2-splitting, read in reverse. Placing the two rails of
each logical qubit on the hardware graph G and asking every interacting
logical pair to have an adjacent rail pair is exactly: embed H into the
quotient family {Q(G, Pi)} over all placements Pi, which is exactly: find a
2-split of H that is a subgraph of G. The quotient graph the paper defines and
drops is the forward direction of a parameter graph theorists already
characterized:

- Bare qubits / fused-pair (Quotient-SABRE) compilers need H to be a SUBGRAPH
  of G (split thickness 1 against G). For planar degree-4 grids that excludes
  every non-planar H and most dense H; routing pays the difference on every
  layer, forever.
- Rail-level dual-rail placement needs H to 2-SPLIT into G. The reachable
  class jumps discontinuously: **K_5 through K_12 are 2-splittable into planar
  graphs** (their Theorem; f(K_n) = ceil(n/6) in general, and recognizing
  2-splittability is NP-hard). Non-planar logical connectivity on planar
  hardware, from the encoding alone.

## 2. The hand-verifiable demo (no compiler needed)

K_4, four logical qubits all-to-all, on a PATH of 8 physical sites:

```
site:   1    2    3    4    5    6    7    8
rail:   A    B    C    A    D    B    C    D
```

Adjacent pairs realize: AB(1,2), BC(2,3), CA(3,4), AD(4,5), DB(5,6), BC(6,7
again), CD(7,8). All six logical pairs of K_4 are present. A fully connected
4-qubit diagonal circuit (4-qubit all-to-all QAOA cost layer, any 4-qubit
phase polynomial) runs with ZERO swaps on a line. Bare qubits on a line
support path-adjacency only; a fused-pair compiler sees a 4-node line. Both
pay swaps for 3 of the 6 pairs on every layer. Boundary, equally clean: K_5 on
a line is impossible by counting (a line of 10 sites has 9 adjacent pairs,
K_5 needs 10 distinct ones). The degree bound deg_Q <= 2d finally earns its
keep as the local form of this global statement.

Grid caveat (state it honestly): the K_12 result is for general planar
targets. On a degree-4 grid each rail has degree <= 4, so logical degree
<= 8, and K_n on a grid dies by degree/edge counting well before 12. The grid
numbers need their own small enumeration (cheap, see E1); the planar numbers
are the headline class statement.

## 3. What it does to the compiler stack (place / commit / route, all from theory)

1. **Placement = maximum partial quotient embedding.** Find Pi maximizing the
   (demand-weighted) fraction of H's edges realized as quotient adjacencies,
   INCLUDING self-loops for qubits with non-diagonal-gate demand (co-location
   is just the self-loop edge in the same objective, so the diagonal freedom
   and the rejoin demand are one weighted embedding problem, not two passes).
   NP-hard in general (Eppstein), so heuristic, like all placement. This
   directly attacks the KNOWN seed bottleneck (memory
   `project_sabredr_seed_bottleneck`: stock SabreLayout lands rail pairs
   badly, CRZ-only chains end up non-adjacent and iterations do not recover).
2. **Commit = port assignment** (`port_parallelism.md`): on the embedded
   subgraph, the diagonal layer schedules to depth = max port load,
   approximately ceil(Delta_H / 2), with zero swaps.
3. **Route = prism's min over realizations,** now only for the RESIDUAL
   (the edges the embedding could not realize). And the banked mechanism
   number gets a reinterpretation: prism's routing-aware picks cutting ~94%
   of swaps means prism has been DISCOVERING partial quotient embeddings
   online, greedily, the whole time. The static pass is the principled
   complement; prism is its online approximation and its fallback.

## 4. What it does to the law

The density law (win ~ decision-op density, corr +0.70) refines to a
graph-theoretic predictor computable BEFORE compilation: the embedded
fraction of the interaction graph under the best found Pi (or cheaper proxies
for it: arboricity-style bounds, degree profiles). Decision-op density is the
gate-count shadow of this graph parameter. Prediction: embedded fraction
correlates with the win better than raw density, and the circuits where prism
wins biggest (crz-dense qaoa) are exactly those whose H has high 2-split
embeddability relative to its subgraph embeddability gap.

## 5. The architecture sentence

Connectivity is normally bought with hardware (couplers, higher-degree
lattices, multi-chip links). Here it is bought with the encoding plus the
compiler: the same 2x redundancy that buys erasure conversion also buys
(a) doubled gate bandwidth (ports) and (b) a strictly larger class of
natively-embeddable interaction graphs (split thickness 2 vs subgraph), on
unchanged planar hardware. That is an architecture claim, stated in
graph-theoretic terms, with a hand-checkable witness (K_4 on a path) and a
published mathematical foundation.

## 6. Experiments (cheap first, each independently publishable as a figure)

- **E1 (hours): grid/line embedding enumeration.** Small exact search: which
  K_n / random 3-regular / QAOA instance graphs embed into quotients of
  lines, ladders, grids of given size. Produces the "reach table" (the grid
  analog of Eppstein's planar numbers) and the K_4-on-a-line figure. The
  existing `dev_quotients.ipynb` / `dev_simple_graph_enum.ipynb` suggest
  partial machinery exists.
- **E2 (a day): embedded-fraction predictor.** For the 26-circuit suite,
  compute interaction graphs, run a simple embedding heuristic (greedy edge
  insertion or annealing over Pi), correlate embedded fraction with the
  banked per-circuit win. Tests the law refinement on existing data.
- **E3 (days): QuotientEmbed layout pass.** Seed prism with the
  embedding-optimized initial layout instead of stock SabreLayout (the seed
  bottleneck fix). Measure swap/depth deltas on crz-dense circuits. This is
  the lever: a placement stage that the theory designs and the router
  exploits.
- **E4 (with port assignment): the zero-swap diagonal-layer demo.** K_4
  all-to-all QAOA cost layer on a line: zero swaps, depth = port load, vs
  bare/fused baselines paying swaps every layer. The single most
  reviewer-legible artifact of the whole conceptual stack.

## 6b. RESULTS (2026-06-10): theorems harvested + the constructive algorithm measured

**Exact theorem statements (read from the paper, pages 1-6):**
- Theorem 1 (with Ringel-Jackson): f(K_n) = 1 for n <= 4, **= 2 for
  5 <= n <= 12**, = ceil(n/6) otherwise. Lineage: Heawood 1890 proved 12
  mutually adjacent EMPIRES draw as a "2-pire map"; dual-rail placement is
  2-pire cartography, a 136-year-old construction recruited as a quantum
  placement theorem.
- **Section 2.3, the bound that matters most: planar split thickness <=
  ceil(Delta/2)** (every 2-regular graph is planar). So EVERY interaction
  graph with max degree <= 4 is 2-splittable: all 3-regular QAOA instances,
  all chain/ring Trotter layers, degree-4 lattice models. Tight at Delta = 5
  (their Theorem 4: max-degree-5 graphs exist with split thickness >= 3 for
  any nontrivial minor-closed target class).
- K_{m,n}: K_{5,16}, K_{6,10}, K_{7,8} are 2-splittable (as quadrangulations)
  and are the largest such for m = 5, 6, 7.
- NP-hard to recognize 2-splittability (planar 3-SAT reduction); arboricity
  of k-splittable graphs <= 3k+1; constant-factor approximation exists;
  k-splittability testable in LINEAR time for bounded treewidth.

**The ceil(Delta/2) proof is constructive for us (`euler_ladder.py`):**
Petersen-decompose a max-degree-4 H into two max-degree-2 subgraphs (disjoint
paths and cycles), lay each along one row of a 2 x n ladder in chain order.
Every H-edge is realized by a ladder adjacency except ONE closure edge per
cycle in the decomposition. O(n) construction, no search, scales arbitrarily.
Measured (20 seeds per cell):

| H | n | residual (unrealized) edges | non-planar instances |
|---|---|---|---|
| ring (Trotter/QAOA ring) | 8-32 | **0%** at every size | n/a |
| random 3-regular | 8 | 4.2% mean (max 16.7%) | 3/20 |
| random 3-regular | 16 | 2.1% | 16/20 |
| random 3-regular | 24 | 1.4% | 20/20 |
| random 3-regular | 32 | **0.2%** (max 2.1%) | 20/20 |
| random 4-regular | 8-24 | 17.8% -> 7.5% | nearly all |

Reading: at n = 32, a random NON-PLANAR cubic interaction graph has 99.8% of
its edges nearest-neighbor on a plain 2 x 32 ladder, the weakest 2D hardware
there is, via an O(n) deterministic layout. Bare qubits cannot fully embed a
non-planar H on ANY planar hardware at any size; the residual is what routing
pays every layer, forever. The residual SHRINKS with n for the 2-split
because the Eulerian decomposition produces few long chains (cycle count
grows much slower than edge count). With port assignment on top, the realized
edges schedule at depth = port load <= ~3 independent of n: a full ZZ layer
over a non-planar cubic graph at zero swaps and O(1) depth.

K_4 sanity: the constructive layout reproduces a zero-residual K_4-on-a-line
placement automatically (different witness than the hand one, equally valid).

**Exact reach table (`embed_search.py`, completed 2026-06-10, all on TIGHT
2n-site hardware unless noted):**

| instance | 2-split (dual-rail) | bare subgraph |
|---|---|---|
| K_4 on line(8) | YES (the hand construction, confirmed) | no |
| K_5 on line(10) | no (counting bound, confirmed exhaustively) | no |
| K_5 on ladder 2x5 | **YES, tight** | no |
| K_6 on ladder 2x6 | **YES, tight** | no |
| K_6 on grid 3x4 | YES | no |
| K_7 on grid 4x4 (2 spare) | no (exhaustive, 46 s) | no |
| K_8 on grid 4x4 | no | no |
| K_8 on grid 4x5 | timeout (unknown; greedy partial 0.79) | no |
| random 3-regular n=8 on 4x4 | **20/20 fully embed** (3/20 non-planar) | **0/20** |
| random 3-regular n=10 on 4x5 | 6/20 proven yes, 14 timeouts, 0 refuted | 0/20 |
| random 3-regular n=12 on 4x6 | 2/20 proven yes, 18 timeouts, 0 refuted | 0/20 |

Two sharpenings:

1. **Grids are bipartite, so the bare-native class excludes every triangle.**
   K_4 bare fails on every grid not because of size but because grids have no
   odd cycles; bare qubits on grid hardware can NEVER natively satisfy even a
   triangle of interactions, and triangles are everywhere in real circuits.
   Vertex identification breaks bipartiteness, which is exactly what the
   2-split adds. The dichotomy on tight grid hardware: bare native class =
   triangle-free subgraphs; dual-rail native class = up to K_6 all-to-all,
   including non-planar instances. (The K_6-on-a-tight-ladder witness is the
   striking one: six fully connected logical qubits on 2x6, zero spare sites.)
2. **K_7 is the exact all-to-all boundary on 4x4** (proven exhaustively), so
   the grid reach is: K_6 yes (even on a ladder), K_7 no. The planar-class
   K_12 number is the upper envelope; degree-4 grids stop at 6.

The n=10/12 timeouts are search-engineering, not feasibility (zero refutals,
and the constructive ladder layout already certifies 96-100% partial at those
sizes); a SAT-solver backend or symmetry breaking would close them. Immediate
implication for E3: the n=8 benchmark suite's qaoa instances live on grids
where EVERY 3-regular interaction graph fully embeds, so an embedding-aware
seed should drive qaoa's routing cost toward zero; that is a concrete,
falsifiable prediction for the existing suite.

**New algorithmic statement for the paper (replaces "heuristic embedding" for
the common case):** for Delta(H) <= 4, placement is SOLVED constructively up
to O(#cycles) residual edges by Euler-split ladder layout; prism routes the
residual. The NP-hardness (general case) and the linear-time treewidth FPT
(structured circuits have moderate treewidth) bracket the complexity story.
Wider grids (4 x n/2, boustrophedon rows) can close cycles and should drive
the 4-regular residual toward zero; untested, noted.

## 6c. REALITY CHECK (2026-06-10, `real_topologies.py`): heavy-hex + the actual suite

Answer to the "irl it's heavy-hex and algorithms never map exactly" objection.
Full embedding is the boundary probe; the operating claim is the WORKLOAD
SPLIT: the fraction of 2Q-op weight a placement absorbs natively, routing
paying only the residual. Measured on the real n=8 suite circuits (MQT fetch +
actual DualRail pre-lowering, weighted aggregate interaction graphs) and on
IBM-style heavy-hex d=3 (19 sites, 20 edges, bipartite, max degree 3).

**Heavy-hex reach:** K_4 and K_5 2-split embed on heavy-hex(3); K_6 does not;
K_3 BARE does not (bipartite, confirmed: a triangle of interactions can never
be native on any heavy-hex device at any size). **Random 3-regular n=8:
10/10 fully embed on heavy-hex** with only 3 spare sites. Heavy-hex being
sparser and parity-constrained makes the bare baseline worse and the 2-split
relief LARGER, not smaller: degree lifts 3 -> 6 and the parity obstruction
breaks.

**Real circuits, weighted embedded fraction (static greedy 2-split):**

| circuit | pair density | max deg | grid 4x4 | heavy-hex |
|---|---|---|---|---|
| ghz / graphstate / wstate | 25-29% | 2 | 100% | 100% |
| qaoa | 50% | 5 | **100%** | 93% |
| draper_qft_adder / modular_adder | 57% | 7 | 95-96% | 77-81% |
| qft / qpeexact / vqe_two_local (complete aggregates) | 100% | 7 | 79-81% | 57-62% |
| randomcircuit | 96% | 7 | 87% | 71% |

Reading: even for COMPLETE aggregate interaction graphs (qft), a single static
2-split placement makes ~80% of the 2Q-op weight nearest-neighbor on the
suite's grid; routing services the remaining ~20%. The structured workloads
(qaoa, state-prep) absorb 93-100%. On heavy-hex the absorbable share is
57-100%. qaoa at 100% on the grid corroborates the E3 falsifiable prediction
(near-zero routing with an embedding seed).

Honest caveats: the static fraction is a structural statistic, not a depth
claim. It counts simultaneous satisfiability in one layout; it ignores
congestion/serialization (port assignment handles that) and it understates
the dynamic compiler, which re-embeds as rails drift (prism's min = a
time-sequence of partial embeddings; the frozen-pick ablation already showed
that dynamic component carries ~94% of swap savings). The architecture is:
static embed as the SEED, prism as the dynamic re-embedder, SABRE for the
true residual.

## 6d. E3 ROUND 1 (2026-06-10, `e3_seed_test.py`): naive seed FALSIFIED, qft win, diagnosis

Terminology fix first (user): hex-lattice (plain honeycomb, degree <= 3, no
edge qubits) is not heavy-hex (the subdivided IBM variant). Both bipartite.
Plain hex 2x2 (16 sites, 19 edges, tight for n=8) measured alongside: K_5 yes
/ K_6 no, K_3 bare impossible, random cubic 10/10 full embeds, suite
fractions BETWEEN grid and heavy-hex (structured 93-100%, dense 64-88%).

**Round-1 result (edges-only embedding seed into PrismRouting via an
`_initial_v2p` override, no src/ edits, 3 seeds, 4x5 grid):**

| circuit | embfrac (edges only) | stock prism d/sw | seeded d/sw | verdict |
|---|---|---|---|---|
| qaoa | 100% | 15/6 14/10 14/6 | 16/10 16/12 16/13 | **WORSE: prediction falsified** |
| ghz | 100% | 16/0 16/0 16/0 | 17/2 17/1 16/0 | worse/equal (stock already 0 swaps) |
| qft | 84% | 24/24 23/21 26/22 | 22/17 24/16 26/20 | **swaps -7/-5/-2, the dense win** |
| modular_adder | 100% | 25/16 24/19 25/24 | 25/17 25/22 25/21 | mixed/neutral |

**Diagnosis (the failure is the theory talking):** the round-1 objective
violated this memo's own section-3 spec by omitting CO-LOCATION demand. qaoa's
mixer layers are rx on every qubit and ghz carries 15 rx; both are
non-diagonal, rails must rejoin. The edges-only seed scatters rails to satisfy
crz adjacency and then pays rejoin routing on every mixer layer. The
placement-dependent-ISA picture says demand = edge weight (diagonal coupling)
PLUS self-loop weight (non-diagonal 1Q); a seed optimizing half the demand
loses exactly where the other half dominates. Round 2 implements the designed
objective (per-qubit rx+x counts as self-loop weight, own-rail adjacency
scored). Also honest: stock prism already solves ghz/qaoa-class circuits to
near-optimal swaps at n=8, so the seed's headroom is concentrated in the
DENSE aggregates, which is where round 1 in fact delivered (qft swaps -5
mean). The static seed is a dense-circuit lever, not a uniform one.

## 6e. E3 ROUND 2 + VERDICT: the static seed is not a robust upgrade at n=8; the honest integration is seed-as-extra-trial

Round 2 (co-location-aware objective: per-qubit rx+x counts as self-loop
weight, own-rail adjacency scored):

| circuit | embfrac (full demand) | stock prism d/sw | seeded d/sw |
|---|---|---|---|
| qaoa | 94% | 15/6 14/10 14/6 | 16/8 16/8 15/10 |
| ghz | 100% | 16/0 x3 | 16/0 x3 (repaired) |
| qft | 70% | 24/24 23/21 26/22 | 24/22 23/23 24/23 (round-1 win gone) |
| modular_adder | 88% | 25/16 24/19 25/24 | 25/19 25/17 27/18 |

**Verdict, stated plainly:** a single static embedding seed does NOT robustly
beat stock prism at n=8 with full trials. The demand composition decides which
objective wins per circuit (qft is edge-dominated, the edges-only seed cut
swaps -5 mean; qaoa/ghz are co-location-heavy, the self-loop weighting
repaired them but traded away qft). Stock prism's 16 SabreLayout trials +
forward/backward refinement + the dynamic per-gate min already capture most
of what a static layout can offer at this scale; the ablation said as much
(the dynamic component carries the swap win).

**Three follow-ups, ranked:**
1. **Seed-as-extra-trial (never-hurts by construction).** Offer the embedding
   placement as ONE of prism's `num_trials` initial layouts and let the
   existing best-of-trials selection pick. Keeps round-1's qft win, cannot
   lose qaoa/ghz, mirrors the teleport `best_single` min-includes-no-op
   pattern. Trivial to implement (the subclass already exists); this is the
   honest production integration.
2. **Trial-budget / compile-time angle:** seed quality matters most at
   num_trials=1-4 (fast compiles). "Embedding-seeded prism at 4 trials
   matches stock at 16" would be a compile-time result. Untested.
3. **Scale retest at n=20+** where the SabreLayout seed bottleneck
   (memory `project_sabredr_seed_bottleneck`) actually bites; n=8 headroom is
   simply small.

The conceptual results (reach theorems, bipartite/triangle dichotomy,
workload-split fractions, the constructive ladder layout) are independent of
this lever and stand. The "stronger than prism" search continues on the OTHER
lever: port assignment (port_parallelism.md E1/E2), which targets DEPTH
through commit-time choice rather than placement, and is untested.

## 7. Prior-art and verification flags

- Planar split thickness: [arXiv:1512.04839](https://arxiv.org/abs/1512.04839)
  (theorem statements now verified against the PDF, section 6b above).
- No quantum-compilation use of split thickness / inverse vertex splitting
  found in this sweep; the existing quantum placement literature is subgraph
  isomorphism + heuristic layout. Needs a dedicated check near submission
  (search terms: vertex splitting qubit placement, quotient coupling map,
  multi-rail connectivity).
- The r-rail generalization (r-split thickness) covers future multi-rail
  codes; Eppstein's general-k results apply. One sentence of future work.

## 8. Honest limits

- Diagonal layers only; non-diagonal demand enters as self-loop weight in the
  embedding objective rather than disappearing.
- Both rails of a qubit are pinned by the embedding while it is in force;
  dynamic circuits with phase-varying interaction graphs need re-embedding or
  fall back to prism (the online version). The static-embed-plus-route-residual
  design degrades gracefully to current behavior.
- Erasure-check co-location (cadence) is compatible: checks need self-loops,
  which the weighted objective can include, or itinerant-ancilla parity
  checks (recorded thought, unbuilt) remove the demand entirely.
- The grid class is smaller than the planar class (degree 4); claim the grid
  numbers only after E1 produces them.
