# Port parallelism: the leverage point where the theory buys depth

Written 2026-06-09 in response to the user's challenge: the don't-care /
placement-dependent-ISA theory is nice but disconnected from prism and the
depth metric; prism is a trivial min; find where the analysis actually buys
something. This memo derives a depth mechanism from the abelian structure of
the delocalized ISA, shows no existing abstraction can express it, checks it
against the implemented conventions, and specs the experiments. Cross-refs:
`conceptual_spine.md` (the formalism), `homerun_plan.md` (priorities).

## 1. The insight chain

1. The delocalized ISA is abelian. Everything delocalization permits (Rz, X up
   to frame, CRz) is diagonal up to tracked Pauli frame. The non-universality
   that reads as pure weakness is, algebraically, total commutativity.
2. Commutativity on bare qubits buys only REORDERING: two commuting gates that
   share a qubit still serialize, because they contend for the same physical
   resource. That contention is a hardware fact for bare qubits and an
   ABSTRACTION ARTIFACT for encoded ones.
3. Dual-rail's logical CRz touches ONE rail per logical qubit (weight-1
   coupling, the realization sets are exactly the choice of which rail). So
   two CRz gates sharing logical qubit A can occupy DISJOINT physical
   resources: CRz(A,B) on (a_0, b_j) and CRz(A,C) on (a_1, c_k). Diagonal,
   disjoint supports, simultaneously executable. **A logical qubit is a
   two-port device: each rail is an independent gate port.**
4. The simultaneity is unconditionally legal precisely BECAUSE the delocalized
   ISA is abelian. The weakness and the strength are the same algebraic fact.

**Convention check (against `dualrail.py` and Ch.5):** with |0_L> = |01>,
a_0 = A_L, so physical crz(a_0, b_0) phases logical |1_A 1_B> = logical CRz
exactly, with identity on the idle rails (the canonical don't-care fill).
The b-rail variants absorb their sign/anti-control via the codespace-safe
identity already implemented in `crz`'s lowering. crz(a_0,b_0) tensor
crz(a_1,c_0) is a product of diagonals on disjoint mode pairs. Depth 1. No new
correctness machinery; the existing realization equivalences cover it.

## 2. Who can and cannot express this (the false-serialization argument)

- **Bare qubits:** CRz(A,B) and CRz(A,C) physically contend for qubit A.
  Serialization is real. Commutativity-aware routers (the QAOA literature)
  reorder; they cannot parallelize same-qubit gates. Depth floor for a
  diagonal layer = max logical degree Delta.
- **Fused-node IRs (Quotient-SABRE, every standard pipeline):** the logical
  qubit is one DAG resource; gates sharing it serialize BY CONSTRUCTION. The
  abstraction imposes a serialization the encoding does not require.
- **The rail-level multi-realization IR:** the only representation in the
  stack where the concurrency is even expressible. Depth floor for a diagonal
  layer drops from Delta to ceil(Delta/2).

The cleanest possible demonstration that the IR abstraction buys depth, on a
line placement with NO routing at all: chain ZZ layer (Ising Trotter / QAOA
ring cut open). Place rails interleaved or co-located on a line, either works:
a_0 a_1 b_0 b_1 c_0 c_1. CRz(A,B) commits to (a_1, b_0), CRz(B,C) to
(b_1, c_0): adjacent, disjoint, one layer. The fused-node compiler on the SAME
line: depth 2 (B is shared). Same gates, same hardware, the entire difference
is whether the IR can see rails. Bare qubits on the same line: also depth 2.
**The encoding's 2x qubit overhead converts into 2x gate bandwidth on diagonal
circuits.** For MICRO: an error-detecting encoding that ACCELERATES the
diagonal portion of circuits, with the IR as the enabling artifact.

## 3. Honest attribution (who gets the dividend)

The port dividend accrues to ANY rail-level realization-aware compiler:
greedy's argmin can also land port-disjoint picks when the placement offers
them. So this widens IR-vs-standard-pipeline (the paper's thesis claim), not
prism-vs-greedy per se. Two places where the win is NOT automatic and an
algorithm earns it:

- **Under dynamic layouts** (the realistic case), keeping ports disjoint while
  rails move is a routing-coupled choice; per-gate greedy has no reason to
  preserve disjointness and the prism front layer cannot even SEE the
  opportunity, because `LoweredOp` spans all four wires and the DAG serializes
  same-qubit decision ops before routing begins. Today any port parallelism in
  our output is ACCIDENTAL (it emerges after commit, when the depth metric
  sees disjoint wires).
- **Joint choice within a diagonal layer.** The greedy-insufficiency bound
  established that joint realization choice is hard in general (ordering
  couples the decisions). The abelian case is the exception THE THEORY
  IDENTIFIES: within a maximal commuting diagonal layer there is no ordering,
  so joint port assignment is a polynomial combinatorial problem, not a
  search. Model: split each logical vertex into two port-vertices, assign
  each CRz edge endpoint to a port, minimize max port load (and routing cost).
  This is degree-constrained edge coloring / b-matching territory; Vizing-type
  bounds give layer depth ceil(Delta/2)+O(1). **A new commit policy sits
  between prism and the oracle: per-gate greedy < prism (routing-coupled
  greedy) < diagonal-layer joint port assignment (tractable joint, abelian
  case) < oracle.** This answers "prism is trivial" with a principled
  algorithm derived from the structure, in exactly the regime (diagonal-dense)
  where the density law says our win lives.

## 4. Generalization and the design criterion

Port count for a gate type = WIRES_PER_LOGICAL / per-qubit support weight of
its realization. Dual-rail crz: 2/1 = 2 ports (the special feature: a diagonal
ENTANGLER of weight 1 per qubit). RepCode/Iceberg cx are transversal
(full-weight): 1 port, no concurrency dividend; their low-weight realizations
are 1Q Paulis where concurrency is routing-irrelevant. So the dividend is
dual-rail-specific among our codes, and it yields an encoding DESIGN
criterion worth stating: codes whose logical entanglers have low-weight
diagonal realizations buy gate bandwidth proportional to wires/weight. That is
a forward-looking architecture statement, not an overclaim, and it sharpens
why dual-rail is the right instance for the paper.

## 5. Predicted magnitudes (state before measuring, then measure)

- Chain/ring ZZ layer (Ising Trotter, QAOA ring): serialization floor 2 -> 1
  per layer, zero added swaps under the line placements above.
- QAOA cost layer, 3-regular: floor 3 -> 2.
- IQP / dense diagonal layers: floor Delta -> ceil(Delta/2), the maximal case.
- ghz and Clifford-heavy circuits: no effect (interleaved non-diagonal gates
  pin ordering), consistent with the existing regime split. The density law
  gains a second mechanism on the same axis: diagonal-dense circuits win twice
  (shorter routes from picks, halved serialization from ports). The two
  contributions are separable in analysis (E1 below), which upgrades the
  law's scatter into a two-mechanism decomposition.

## 6. Experiments (in order, each gates the next)

- **E1 (hours, post-processing only): measure ACCIDENTAL port parallelism.**
  In existing prism and greedy committed circuits, count same-logical-qubit
  diagonal gate pairs scheduled in the same layer on disjoint rails, vs the
  serialized count. Establishes the baseline ("the IR already buys this
  silently") and decomposes existing depth wins into pick-distance vs
  port-concurrency shares.
- **E2 (days): intentional port assignment for diagonal layers.** A commit
  policy (or a pre-commit pass over maximal commuting CRz runs) that solves
  the port-assignment matching per layer, then hands picks to the router
  (reuse `PinRealizations`). Compare against prism on diagonal-dense
  benchmarks (Ising chain/ring Trotter, QAOA cost layers, IQP). Predicted:
  approach the ceil(Delta/2) floor where prism's accidental rate falls short.
  Implementation note: do NOT relax the LoweredOp DAG inside Rust routing
  first; the pre-commit port-assignment + pin path needs no router surgery.
- **E3 (the demo figure): the line-placement chain.** Fused-IR depth 2 vs
  rail-IR depth 1 on the same line, no routing; the single cleanest figure of
  "the abstraction is the win." Then scale: Trotter depth vs n for
  fused/bare/greedy/prism/port-assigned.

## 7. Secondary leverage points (recorded, lower priority)

- **Min-pinch synthesis (the answer to the failed H-removal).** The theory
  says eliminating local Hadamards is impossible (the diagonal line is
  measure-zero in the Weyl chamber); the right objective is MINIMIZE and
  CONCENTRATE. Canonicalize every 1Q interstitial as Rz·Ry(theta)·Rz: the Rz
  parts commute through the diagonal structure and travel free; the lone
  Ry(theta) is the only co-location pinch. Per-2Q-block, the number of
  unavoidable pinches stratifies by Cartan coordinates (CPhase family: outer
  locals only; generic SU(4): the XX/YY factors each cost a basis-change
  pinch). Gives a computable per-circuit rejoin lower bound = the intrinsic
  demand the compiler can be measured against. This is the existing
  delocalization-aware-decomposition future-work slot, now with its cost
  function; h_reduction is its first pattern.
- **State-dependent don't-cares (a third class).** U and U·S are
  interchangeable when S stabilizes the current state (the truest quantum SDC:
  the distinguishing input never occurs). Gate-level non-universality does not
  preclude state-level shortcuts: a latitude-preserving state transition is
  implementable in O(2) even when the program wrote H. Exploiting it needs
  prefix structure knowledge (cheap only for Clifford prefixes / structured
  algorithms); record as future work, do not build.

## 8. Prior-art flags (verify before the paper claims firsts)

- Commutativity-aware routing/scheduling for QAOA (Alam et al. line;
  tket/Cowtan phase-gadget synthesis; Pauli-network synthesis, Rustiq;
  swap networks). All bare-qubit: commutativity is used to reorder and to
  synthesize, never to co-schedule same-qubit gates, which is physically
  impossible there. Our delta is encoding-enabled same-qubit concurrency.
  Needs a verification sweep before claiming novelty (likely clean: the
  premise requires rail-level encoded qubits with weight-1 couplings).
- Dual-rail hardware lit (Teoh, Mehta, Levine): gates operate on co-located
  rail pairs; no delocalized-rail concurrency. The two-port reading of a
  dual-rail qubit appears unclaimed; verify near submission.

## 9. Risks

- **Hardware simultaneity:** two crz's on disjoint mode pairs must be
  physically concurrent (no shared coupler/control constraints). True at the
  abstraction level the paper already uses (depth in layers); flag the
  hardware caveat once.
- **The accidental rate may already be high** (E1 may show prism gets most of
  the dividend for free on lines/rings). Then E2's marginal win is small and
  the story is "the IR silently delivers it, here is the decomposition,"
  which is still a strong thesis-serving result. Either E1 outcome feeds the
  paper.
- **Frame bookkeeping under concurrency:** two simultaneous frame-corrected
  realizations on the same qubit compose their corrections; the existing
  commit machinery applies them per-gate. Diagonal frames commute, so order
  is immaterial; one test in E2 should still assert logical equivalence
  end-to-end (statevector on small n).
