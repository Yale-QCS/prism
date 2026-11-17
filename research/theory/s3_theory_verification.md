# §3 theory excursion: verification of the 5 unverified claims (2026-06-22)

Goal: research-fix (not cut) the §3.3 split-thickness / K_6 / 2-pire material and
the cost-equivalence + maximal-ISA claims. Sources: Eppstein et al., "On the
Planar Split Thickness of Graphs" (arXiv:1512.04839, LATIN'16 / Algorithmica
2018), read directly; brute-force witness script
`.claude/scripts/temp_diagnostics/k6_ladder.py`.

Notation: f(G) = planar split thickness = min k such that G is k-splittable into
a planar graph. A k-split replaces each vertex by <=k copies, each neighbor
joined to >=1 copy. A dual-rail logical qubit = a 2-region "empire" (2 rails), so
the dual-rail-embeddable interaction graphs are exactly those with f <= 2.

## Claim 1: "every max-degree-<=4 graph is 2-splittable into planar; tight at D=5"
VERDICT: TRUE, both halves. Attribution should be tightened.
- Eppstein §2.3: planar split thickness of a max-degree-D graph is <= ceil(D/2)
  (split every degree-d vertex into ceil(d/2) copies of degree <=2; degree-2
  graphs are planar). So D<=4 => f <= 2. The degree-4 claim is a COROLLARY of the
  ceil(D/2) bound (this answers the paper's own BLOCK TODO: yes, restate as a
  corollary). Page 2 also notes it follows from thickness (degree-4 graphs have
  thickness 2, which upper-bounds f).
- Tightness at D=5 is their Theorem 3: "For any nontrivial minor-closed property
  P, there exists a graph G of maximum degree five whose P split thickness is at
  least 3." Planarity is minor-closed, so some degree-5 graph has f >= 3 (not
  2-splittable). So ceil(5/2)=3 is achieved => "tight at D=5" is correct.
- FIX: cite the ceil(D/2) bound + Theorem 3 explicitly rather than a vague
  "Eppstein show degree-4 is 2-splittable." The current prose is accurate; only
  the attribution is loose.

## Claim 2: "K_6 on a 2x6 ladder, all 15 pairs adjacent, nothing to route"
VERDICT: TRUE, with an explicit witness; K_6 is exactly the ladder maximum.
- Witness (2x6 ladder sites (row,col), brute force over all pair-partitions,
  explicit recheck missing = NONE):
    q0: (0,0),(0,4)   q1: (0,1),(1,3)   q2: (0,2),(1,0)
    q3: (0,3),(1,5)   q4: (0,5),(1,1)   q5: (1,2),(1,4)
  All 15 logical pairs have some rail of i adjacent to some rail of j => the
  logical quotient is K_6, zero SWAPs needed. This closes the figure+witness
  BLOCK TODO (`03_deloc:157`).
- K_7 is NOT realizable on a 2x7 ladder (brute force). So K_6 is the maximum
  complete quotient on a 2-row grid strip; the paper's K_6 is the right claim,
  not an undersell, for ladder/grid hosts. (Cap is the degree: a 2xN ladder has
  max degree 3, so a logical node reaches <= 2*3 = 6 minus internal/shared
  losses; K_7 needs quotient degree 6 everywhere, unreachable.)
- Independent cross-check: Theorem 1 (Ringel-Jackson) gives f(K_n)=2 for
  5<=n<=12, so f(K_6)=2 (K_6 IS 2-splittable into a planar graph); the witness
  exhibits one such planar host (the ladder is planar).

## Claim 3: "Heawood 1890 drew the same object as a 2-pire map, twelve mutually
## adjacent empires of two regions each"
VERDICT: history REAL, but the paper MISIDENTIFIES its own object. This is a real
error to fix, and it hides an UPGRADE.
- Heawood 1890 (per Eppstein p.2-3): "every 12 mutually adjacent empires can be
  drawn as a 2-pire map where each empire has size exactly 2." That object is
  K_12 (twelve 2-region empires, all mutually adjacent), and f(K_12)=2 is the
  MAXIMUM complete 2-pire (f(K_13)=ceil(13/6)=3). Ringel-Jackson generalized:
  6k mutually adjacent k-empires => f(K_n) <= ceil(n/6).
- The paper exhibits K_6 (six 2-rail qubits) and then says Heawood drew "the same
  object ... twelve mutually adjacent empires." K_6 != K_12. The "same object"
  identification is wrong (6 empires vs 12).
- UPGRADE (the honest + stronger statement): dual-rail qubits are 2-region
  empires, so the dual-rail-embeddable complete interaction graphs are exactly
  those with f<=2, which for K_n reaches n=12 (Heawood/Ringel-Jackson). The 2x6
  ladder realizes the smaller K_6 concretely; K_12 is the planar-theoretic
  maximum. BUT K_12 as a 2-pire is a maximal planar triangulation (Lemma 1: any
  2-split of K_12 has 24 vertices, 66 edges, all faces triangles), whereas real
  devices (grid, heavy-hex) are bipartite, triangle-free, max-degree <=4, so they
  are FAR from triangulations and do NOT host K_12. On device-relevant hosts the
  reachable complete quotient is small (K_6 on a 2x6 grid strip). So the device
  story is K_6; K_12 is the abstract planar ceiling. This nuance is worth stating
  and is more honest than "the same object."
- TWO FIX OPTIONS: (a) correct + strengthen as above (K_6 device-concrete, K_12
  planar-max, bipartite hardware caps you below K_12); (b) conservative: drop "the
  same object ... twelve" and cite the empire-map literature via Eppstein for the
  2-region-empire framing only. (a) is the better paper.

## Claim 4: cost-equivalence lemma (quotient distance = min over rail pairings)
VERDICT: TRUE for what the router uses (per-gate executability + min-over-pairings
score); FALSE as a global shortest-path identity. Scope the prose.
- EXACT part: logical u,v adjacent in the quotient Q(G,Pi) <=> some pairing has
  adjacent rails <=> min_{i,j} d_G(u_i, v_j) = 1. The binding rule (a CRz fires
  when some candidate is executable) and the front-layer score (cost = min over
  pairings of summed endpoint distance on the fixed graph G) are both exact on G.
- FALSE part: the contracted quotient's shortest-path metric is NOT equal to
  min-over-pairings in general, because contracting a pair to one node creates a
  free hop between that qubit's two rails. Counterexample: path
  x0 - a0 - a1 - y0 with A={a0,a1}. d_Q(X,Y)=2 (X-A-Y, free a0->a1), but the
  physical cost min_{i,j} d_G(X_i,Y_j) = d_G(x0,y0) = 3. The quotient under-counts
  by routing a gate "through" another logical node's contraction, which is not a
  physical move.
- The router never does this: it scores each gate by min-over-pairings of d_G
  between its OWN endpoints, never through other logical nodes, so the implemented
  cost is faithful. FIX: scope the claim to per-gate executability + the
  min-over-pairings score (exact on G), and drop/qualify "any distance measured on
  the moving quotient equals a minimum over candidate pairings" (the quotient
  shortest-path metric is not equal and is not what the router uses). This is the
  careful argument the BLOCK TODO (`03_deloc:173`) asked for.

## Claim 5: maximal-ISA, O(2) u {CRz}, over arbitrary multi-mode operations
VERDICT: SOUND as derived for 1Q + 2Q (the cases used); the "maximal over
arbitrary multi-mode operations" framing is not proven. Small scope fix, plus a
clean argument that nearly closes it.
- Derived solidly: (i) single delocalized qubit, 1Q logical gates = O(2) (R_z and
  R_z X), from the parity-preserving block form needing A,B simultaneously
  diagonal or anti-diagonal; (ii) two delocalized qubits through one meeting pair
  => the meeting-pair gate is diagonal (preserves both occupations) => CRz.
- Not proven: maximality over (a) using two meeting pairs at once, or (b) joint
  >=3-mode operations. But a clean argument nearly closes it: any logical action
  outside O(2) u {CRz} needs either a non-diagonal single-mode action (=>
  co-location, by (i)) or a non-diagonal meeting-pair gate (=> breaks
  occupation/parity, by (ii)), so it cannot act on minimally-adjacent (one rail
  each) delocalized qubits. Using two meeting pairs is MORE adjacency (trending to
  co-location), not less, so it is outside the "delocalized" (minimal-adjacency)
  regime by definition. Multi-qubit logical gates compose from 1Q+2Q, and the set
  is abelian up to the pole flip, so composition adds no co-location-free
  universality (consistent with Eastin-Knill).
- FIX: state the result for the 1- and 2-qubit fragment (proven), add the
  one-paragraph "anything richer needs more adjacency => co-location" argument,
  and drop the unqualified "maximal over arbitrary multi-mode physical
  operations." This resolves the PRECISION CHECK (`03_deloc:86`).

## Experimental backing (2026-06-25) -- turn the theory into figures

The audience prefers measured figures to prose + citations. The §3 claims are
embedding claims, so they convert directly to mini-experiments. Two distinct,
both valid; do NOT conflate them.

### Capability (exact, combinatorial -- `temp_diagnostics/embed_capability.py`)
Largest K_m routable with ZERO swaps: bare = clique number of the host (bipartite
=> 2); dual-rail = largest K_m realizable as a disjoint-rail-pair 2-split.
  ladder(12) 2 vs 6 ; grid(16) 2 vs 6 ; grid(20) 2 vs 6 ;
  heavyhex(19) 2 vs 5 ; hex(30) 2 vs 5.
Headline: bare caps at K_2 on every (bipartite) device; delocalization lifts the
free-routing clique to K_5-K_6. Exact. This is the rigorous core of the
"2-splittable class is strictly larger" claim.

### Realized (heuristic router -- `temp_diagnostics/embed_tax_proto.py`)
One CZ per edge, bare = stock Qiskit SabreLayout+SabreSwap (n sites), dual-rail =
build_pm prism (2n sites), min SWAPs over seeds {42,7,123}.
- GRID cycles C3..C7: bare = 1,0,1,0,1 (a SWAP per ODD cycle, zero per even =
  the bipartite signature); dual-rail = 0,0,0,0,0 (flat). Clean, on-thesis.
- GRID cliques K3..K7: bare 1,2,3,6,7 ; dual-rail 0,1,3,6,9. The router does NOT
  reach the zero-routing optimum for dense cliques (K6 ties at 6, though K6 is
  zero-embeddable by the capability search) -- SABRE is heuristic. So clique
  evidence must come from the capability search, NOT the router.
- HEAVY-HEX is muddy (K3 bare 1, DR 2): so sparse (deg<=3, deg-2 links) that
  rails need routing to meet, shrinking the realized advantage. Honest caveat.

### Proposed §3 figure (replaces the empire-map prose with data)
Two panels: (a) free-routing clique capacity, bare vs dual-rail bars per topology
(exact, the 2 vs 5-6 table); (b) the odd-cycle tax, bare vs dual-rail SWAPs over
C3..C9 on grid (sawtooth vs flat zero). Caption ties both to bipartiteness.
Keep minimal prose: the 2-split framing + Eppstein cite + the figure. The
Eppstein/cost-equivalence/maximal-ISA edits (1,4,5) stay prose (not experiments).

## Net effect on §3
4 of 5 claims are TRUE and citable as-is with tightened attribution (1,2,4,5);
the witness (2) and the device-vs-planar-ceiling nuance (3) are upgrades. The one
real error is the Heawood "same object" conflation (3). None of the excursion
needs cutting; it needs: the explicit K_6 witness, the ceil(D/2)+Thm3 citation,
the K_12 planar-ceiling vs K_6 device-reality framing, the scoped cost-equivalence
statement, and the scoped maximal-ISA statement.
