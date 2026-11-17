# Iceberg multi-realization papers (MICRO 2026 co-submissions)

Two anonymized MICRO 2026 submissions the user flagged as "very similar, say
something about multi-realizations, specific to Iceberg codes." Read in full
2026-06-08 (PDFs in ~/Downloads, confidential drafts). Both confirm the user's
read: each exploits the fact that one logical gate / gadget on a high-rate QED
code has MANY physical realizations. Verdict: this is the closest competitive
framing to marabbecca's central claim, and it narrows (does not kill) our novelty.
Treat as the related-work anchor and the novelty stress-test.

## Paper 2901 — AQORN: A Qubit Resource Optimizer for Reducing Noise in QED Architectures

- Code: Iceberg `[[n, n-2, 2]]` (QED, distance 2), focus `[[4,2,2]]`, k>1 logical
  per patch. A "patch" = physical qubits encoding a set of logical qubits.
- **The multi-realization statement (their §2.3, near-verbatim):** "logical
  operators are synthesized as multi-qubit physical circuits rather than
  single-site gates. The realization of these logical operators varies depending
  not only on gate type but qubit location as well as how many encoded qubits they
  are acting on. For that reason, logical gate cost is strongly context
  dependent." Their Table 1 = physical cost (1q/2q counts, depth) of each
  realization: 1Q `Targeted` vs `Patch-wise`; CNOT/CZ/XCX `Intra-patch` /
  `Inter-patch aligned` / `Inter-patch misaligned` / `Transversal`. Fig 4-5: these
  realizations differ up to 4x in depth and have different fidelities.
- **Where they choose the realization:** at PLACEMENT (the "qubit packing problem":
  assign program qubits to patches so cheap realizations are exposed) + a
  translator that "rewrites each logical gate into its physical Iceberg
  implementation, selecting the cheapest encoding based on qubit placement." Three
  passes: Hadamard commutation (push H to end, cancel), gate merging (combine
  compatible gates into transversal/patch-wise), qubit packing (greedy
  noise-biased, who shares a patch) + grid alignment.
- **No connectivity-constrained routing.** They assume "intra-patch swap gates can
  be implemented at negligible cost ... holds for architectures with flexible
  connectivity such as neutral atom systems." Realization choice is placement-time
  and greedy, NOT a min folded into a routing score.
- Results: 71 QASMBench circuits, Stim noise sim. Depth -34%, 1q -31%, 2q -17%,
  LSR (logical selection rate) +86%, TVD 1.75x vs a naive pack-by-index baseline.
- **Note that bites our gate-set theory (their words):** "Hadamard commutation
  works for the Iceberg code because the Iceberg code has known efficient
  implementations for every basis-rotated logical gate. This pass would fail for
  other code families for which efficient implementations of a rotated logical
  gate are not available." Same boundary marabbecca's gate-set theory draws.

## Paper 1600 — Flexible Fault Tolerance: Weaving Error Detection Gadgets and Quantum Algorithms

- Code: Iceberg `[[k+2, k, 2]]`, focus QAOA(MaxCut), also QFT/IQP. Hardware:
  Quantinuum H2-1 trapped ion, all-to-all connectivity.
- **The multi-realization angle = gadget + gate flexibility.** Init/syndrome/meas
  gadgets can be internally reordered/resynthesized without breaking fault
  tolerance (GHZ init is permutation-symmetric; syndrome measures Sz,Sx which are
  permutation-invariant). Logical-gate flexibility: Rzz commute; Rxx mixer gates
  share the top qubit and reorder; a logical X rotation can use top rail `t` OR
  bottom rail `b`, halving depth. They call this "the set of executable gate
  options arising from the flexibility."
- **How they exploit it:** CO-COMPILATION of algorithm + QED gadgets via an A*
  TREE SEARCH over executable gate options (admissible depth-estimate heuristic,
  progress-tracked). Plus Z2 problem symmetry. The search enumerates realizations
  and picks the min-depth weave.
- **Routing is a footnote.** All-to-all hardware; §7 briefly extends to
  nearest-neighbor by reducing SWAP count in a syndrome gadget (Fig 12). No
  routing-integrated realization choice.
- Results: 2q depth -55% vs fixed-gadget baseline; beyond-break-even pushed from 20
  to 34 algorithmic qubits on H2-1; QAOA/QFT/IQP.
- **Public prior-art version (CITABLE):** Jin, He, Hao, Omanakuttan, Amaro, Tannu,
  Shaydulin, Pistoia, "Iceberg Beyond the Tip: Co-Compilation of a QED Code and a
  Quantum Algorithm," [arXiv:2504.21172](https://arxiv.org/abs/2504.21172) (2025;
  overlapping authors Jin/Shaydulin/Pistoia). The Iceberg-QAOA baseline they beat:
  Shaydulin & Pistoia, "QAOA with N·p>200," IEEE QCE 2023.

## What this means for marabbecca

The user's instinct is right and it matters. Both papers, plus the public Jin 2025
co-compilation paper, establish IN OUR EXACT SUBFIELD (high-rate-code compilation,
likely the same MICRO PC) that "one logical gate has many physical realizations
with context-dependent cost, and a compiler should choose among them." Marabbecca
CANNOT claim that observation as novel. The honest framing the board uses
("multi-realization carried as first-class IR + min in score") needs to narrow to
what these do NOT do.

**Framing (user, 2026-06-08): the contribution is generalizing the ROUTING
ALGORITHM, not a hardware optimization.** Teleport here is a dynamic circuit
(entangle ancilla, mid-circuit measure, classical feedforward, Pauli-frame
correction) built from local ops on a MONOLITHIC coupling map. It is NOT a
long-range coupler / static graph edge (that hardware "can and will probably exist
later" but is out of scope). So the "why not add teleport edges to the coupling
graph and let stock SABRE pick them" objection is a category error: there is no
edge; its cost is layout- and ancilla-dependent and it has side effects (consumes a
Bell pair, adds measurement, forks the delocalization state). A coupling-graph edge
is a scalar distance and structurally cannot express that. The multi-realization IR
is the abstraction that lets the algorithm admit such realizations AT ALL; that
generality is hardware-agnostic (same router with or without future long-range
couplers).

**The one honest contingency:** the front-layer min must actually flip to teleport
for some gates or the generalization is inert. It flips NOT on lower immediate
op-cost (that is the triangle-inequality dead end the experiment track hit) but on
the DOWNSTREAM value of preserving delocalization (rails stay apart, future routing
stays cheap). So the routing cost needs a global/lookahead term crediting that
state effect, not a per-op distance. Restates `[[project_teleport_triangle_blocker]]`
correctly: the fix is a stateful/global cost, not a hardware shortcut. The proving
experiment: show the min flips with layout and total cost beats always-SWAP,
always-teleport, AND placement-time-fixed (AQORN-style); if it never flips, drop the
IR to a fixed policy.

**What none of them do (marabbecca's defensible novelty, in priority order):**
1. **Realization choice folded into the CONNECTIVITY-CONSTRAINED ROUTING pass**
   (min-over-realizations inside the SABRE front-layer score, on a real coupling
   map). AQORN assumes negligible-cost movement (flexible/neutral-atom, no
   routing); 1600 is all-to-all trapped ion (no routing). Both decide realization
   at placement/scheduling, BEFORE/WITHOUT routing. Marabbecca's one-line change is
   precisely in the router. This is the cleanest differentiator and it is real.
2. **The dual-rail-specific realizations:** delocalized rail-pair routing (rails
   apart for depth) and the teleport-vs-rejoin gadget for a non-diagonal 1Q gate.
   Neither paper has an erasure code, delocalization, or a non-local 1Q-gate
   gadget. This is `[[project_teleport_routing_priorart]]` territory.
3. **Encoding-agnostic IR mechanism.** That two independent Iceberg papers exploit
   per-gate realization choice HELPS us argue it is a general compiler principle;
   marabbecca's contribution is the IR node + routing integration that makes it
   reusable across encodings (dual-rail being the instance), not a one-code hack.

**Threat to manage (tell the paper track):** do NOT open with "logical gates have
multiple realizations and we pick the best" as the headline novelty; AQORN frames
exactly that. Open with the routing integration (the `min` in the front-layer
score on a constrained topology) and the dual-rail teleport realization. Cite
AQORN/1600/Jin-2025 as concurrent/prior evidence that realization-choice is the
right lens, then stake the narrow, true claim. (Concurrent MICRO submissions
usually aren't held against each other for novelty, but Jin 2504.21172 IS public
prior art and must be cited; AQORN's "context-dependent realization" framing will
be in reviewers' heads regardless.)

**Reviewer-bar calibration (both papers, consistent with our board):** the
expected metrics in this subfield are circuit depth + 1q/2q gate counts +
post-selection / logical selection rate (LSR) + TVD (total variation distance vs
ideal) under a noise sim (Stim for AQORN; H2-1 emulator state-vector for 1600), and
for the strong version, hardware or emulator fidelity. Our board's "fidelity number
+ gadget + regime characterization" matches. Add LSR/post-selection rate and TVD
to the planned eval; that is what this community reports.

**Convergent technique = validation of S2.** AQORN's "Hadamard commutation"
(commute H to circuit end, cancel) is the same move as marabbecca's `h_reduction`
pre-lowering reshape, and AQORN's caveat (only works when the code has efficient
rotated-gate implementations) is marabbecca's gate-set boundary. S2 is a recognized
effective technique, not a speculative one. Cite AQORN as independent support.

## Sources
- Paper 2901 AQORN (anon MICRO 2026 submission, confidential PDF, not citable until public)
- Paper 1600 Flexible Fault Tolerance (anon MICRO 2026 submission, confidential PDF)
- Jin et al., "Iceberg Beyond the Tip," [arXiv:2504.21172](https://arxiv.org/abs/2504.21172) (public prior-art anchor for 1600)
- Shaydulin & Pistoia, "QAOA with N·p>200," IEEE QCE 2023 (Iceberg-QAOA baseline)
