# Prior art: teleport-vs-route as a routing decision

Answers teleport_gadget.md open question #5 (novelty/framing) and the user's
question: "does anyone fold a Bell/gate-teleport-vs-SWAP-route choice into the
routing algorithm?" Status: lit verified (arXiv abstracts + published venues read
2026-06-08); the novelty-delta claims are my assessment, not a proof of absence.

## Verdict

Yes, the decision exists in the literature, in three clusters. None of them is our
exact construction. The unclaimed combination is: **per-gate `min`-in-front-layer
choice of `{rejoin | teleport}` for a SINGLE-QUBIT gate on a DELOCALIZED dual-rail
logical qubit, on a flat single-device topology.** Each of those three qualifiers
rules out a different chunk of the prior art. The strongest reviewer-facing
contribution is the *primitive* (non-local 1Q gate on a delocalized encoded qubit
without rejoining its rails), not the routing integration, which has near-misses.

## The three clusters

### 1. Theory-CS: routing-time separation (whole-protocol, asymptotic)
- **Devulapalli, Schoute, Bapat, Childs, Gorshkov, "Quantum Routing with
  Teleportation," PRR 6, 033313 (2024), [arXiv:2204.04185](https://arxiv.org/abs/2204.04185).**
  Permutations under interaction constraints with pre-distributed entanglement +
  LOCC instead of SWAPs. Result: a graph where teleport gives an `O(log n)`
  worst-case routing-time speedup over SWAP; `O(sqrt(N) log N)` upper bound on the
  separation. **Choice is at protocol-design level, not per-gate.** Pure existence
  bound, no heuristic.
- **Bapat, Childs, Gorshkov, Schoute, "Advantages and Limitations of Quantum
  Routing," PRX Quantum 4, 010313 (2023), [arXiv:2206.01766](https://arxiv.org/abs/2206.01766);**
  and **"Quantum Routing with Fast Reversals," Quantum 5, 533 (2021),
  [arXiv:2103.03264](https://arxiv.org/abs/2103.03264)** (SWAP-only). Spectral
  bounds on when quantum ops can beat SWAP routing. Theory, no router.

Use for: motivation ("teleport *can* asymptotically beat SWAP"), not as a baseline.

### 2. Distributed QC: TeleData vs TeleGate across module boundaries
The choice is real and per-block here, but always across a hard module boundary
where the *only* inter-module op is entanglement consumption.
- **Eisert, Jacobs, Papadopoulos, Plenio, "Optimal local implementation of
  nonlocal quantum gates," PRA 62, 052317 (2000),
  [arXiv:quant-ph/0005101](https://arxiv.org/abs/quant-ph/0005101).** The
  foundational TeleGate cost floor: 1 Bell pair + 2 cbits = one non-local CNOT.
  Cite as the cost-unit ancestor of our teleport realization.
- **Wu, Zhang, Li, Shabani, Xie, Ding, "AutoComm," MICRO 2022,
  [arXiv:2207.11674](https://arxiv.org/abs/2207.11674).** THE most relevant DQC
  paper for us, and a MICRO precedent. Key insight = "burst communication": n
  consecutive gates from one data qubit into a remote node collapse to ONE TeleGate
  (1 EPR) instead of n, because the comm qubit (not the data qubit) is measured.
  Explicitly compares TeleGate (1 EPR for the burst) vs TeleData (2 EPR: move out +
  back). Per-block decision in a pattern-extraction pass. 75.6% EPR / 71.4% latency
  reduction. **CollComm** ([arXiv:2208.06724](https://arxiv.org/abs/2208.06724))
  adds EPR buffering (prep entanglement off the critical path).
- Partition-phase choosers: **Andrés-Martínez & Heunen** hypergraph partition,
  TeleGate-only, PRA 100, 032308 (2019),
  [arXiv:1811.10972](https://arxiv.org/abs/1811.10972); **Cuomo et al.** ILP min
  EPR, ACM TQC 2023, [arXiv:2112.14139](https://arxiv.org/abs/2112.14139);
  **Ferrari et al.** TeleGate+TeleData mix, IEEE TQE 2021/2023
  ([arXiv:2012.09680](https://arxiv.org/abs/2012.09680),
  [arXiv:2305.02969](https://arxiv.org/abs/2305.02969)); **Davis et al.** METIS,
  both strategies, no single winner, QCE 2023,
  [arXiv:2310.03942](https://arxiv.org/abs/2310.03942); **Baker et al.**
  time-sliced partitioning (TeleData), CF 2020,
  [arXiv:2005.12259](https://arxiv.org/abs/2005.12259); **Sundaram, Gupta,
  Ramakrishnan**, DISC 2021, TeleData-only, per-gate w/ lookahead.

Use for: the cost model and the "no single strategy dominates, it's
circuit-dependent" framing (Davis). The gap: their teleport is a discrete
boundary-crossing that burns a scarce pre-shared Bell pair; ours is one realization
among rail-pair choices on a flat graph.

### 3. SABRE + teleport on one device (the actual near-misses)
- **Russo et al., "TeleSABRE," IEEE QCE 2025,
  [arXiv:2505.08928](https://arxiv.org/abs/2505.08928).** Closest in mechanism:
  augments the SABRE front-layer candidate set with intra-core SWAP, TeleData, and
  TeleGate, all scored by one energy function, min wins per iteration. BUT
  multi-core: a teleport candidate only exists when the gate spans two cores;
  intra-core gates never see one. 28% inter-core op reduction.
- **Sanjiang Li, "dSABRE," 2026,
  [arXiv:2605.21960](https://arxiv.org/abs/2605.21960).** Five-term teleport score
  in a SABRE loop, but two-phase (intra-core SWAP first, inter-core teleport only
  when the front is exhausted), not a flat per-gate min. Multi-core. 41-44% EPR vs
  TeleSABRE.
- **Babu et al., "Gate teleportation-assisted routing (RTG)," 2025,
  [arXiv:2502.04138](https://arxiv.org/abs/2502.04138).** The one single-device
  result: ancilla qubits form teleport edges; greedy heuristic reroutes some gates
  via teleport. BUT it is a POST-PASS after SABRE fixes the layout, not a
  front-layer min. 10-25% depth reduction (DJ, QAOA on IBM Eagle heavy-hex). This
  is our nearest single-device baseline/competitor; cite it and state the
  difference (in-loop min vs separate pass; ordinary qubits vs delocalized rails).
- **Hillmich, Zulehner, Wille, "Exploiting Quantum Teleportation in Quantum Circuit
  Mapping," ASP-DAC 2021, [arXiv:2011.07314](https://arxiv.org/abs/2011.07314).**
  Earliest single-device "teleport as a mapping alternative," also a separate
  strategy not a per-gate min.
- Physical-movement analogs that DO use a per-gate `min{move, SWAP}` but where the
  primitive is atom/ion transport, not Bell teleport: **S-SYNC** (trapped-ion
  shuttle vs swap co-opt, ISCA 2025, [arXiv:2505.01316](https://arxiv.org/abs/2505.01316));
  neutral-atom hub-shuttling and hybrid compilers (Schmid et al.
  [arXiv:2311.14164](https://arxiv.org/abs/2311.14164)). These show the
  per-gate-min pattern is accepted; we instantiate it with a different primitive.

## The novelty delta for marabbecca

Three independent qualifiers, each killing part of the prior art:
1. **Flat single-device topology** (not multi-core): kills TeleSABRE/dSABRE as
   exact matches; their teleport is structurally forced at boundaries.
2. **In-loop per-gate `min` over realizations** (not a separate pass): kills RTG /
   Hillmich as exact matches.
3. **Single-qubit gate on a DELOCALIZED encoded qubit** (`rejoin` vs `teleport`),
   not a two-qubit non-local CNOT or a data-qubit teleport: kills the ENTIRE DQC
   and SABRE-teleport literature as exact matches. Gate teleportation
   (Gottesman-Chuang [arXiv:quant-ph/9908010](https://arxiv.org/abs/quant-ph/9908010),
   Zhou-Leung-Chuang [arXiv:quant-ph/0002039](https://arxiv.org/abs/quant-ph/0002039))
   always operates on a LOCALIZED qubit; nobody applies a 1Q gate to a qubit whose
   own halves are spatially separated, without co-locating them. The dual-rail
   building blocks are all demonstrated hardware (2Q gate Mehta et al.
   [arXiv:2503.10935](https://arxiv.org/abs/2503.10935); CNOT Huang et al.
   [arXiv:2504.12099](https://arxiv.org/abs/2504.12099); erasure detection Levine
   [arXiv:2307.08737](https://arxiv.org/abs/2307.08737), de Graaf
   [arXiv:2406.14621](https://arxiv.org/abs/2406.14621)), so the gadget is buildable.

Honest framing: qualifier (3) is the real novelty; (1)+(2) are "first to put it
in the front-layer min on a flat device," a routing-engineering delta with close
neighbors. Lead the paper with the primitive, support with the integration.

## The triangle-inequality blocker is explained by this literature

The experiment track found `op_cost_min` can never prefer teleport (triangle
inequality: routing a Bell pair + overhead always costs >= routing the qubits).
The DQC literature says exactly why and when teleport nonetheless wins, and none of
those mechanisms exist in the current flat-metric cost:
- **Amortized/pre-shared Bell pairs.** AutoComm/CollComm prep entanglement OFF the
  critical path (EPR buffering). Teleport beats SWAP only when the Bell-pair cost is
  paid elsewhere/earlier, not charged to the gate at route time.
- **Burst/collective reuse.** AutoComm's core result: one Bell pair serves n gates
  (1 EPR vs n). Per-single-gate the triangle inequality holds; the win is amortized
  over a burst of gates sharing the same delocalized qubit. Our 1Q-gate teleport may
  be exactly such a burst if a delocalized qubit takes several non-diagonal gates in
  its delocalization window.
- **Access to connectivity SWAP can't reach** (a teleport bus / long-range link off
  the SWAP metric), the §7 bi-layer idea.

Implication for the experiment track: a flat-metric `op_cost_min` is the wrong cost
model for teleport, and that is consistent with prior art, not a bug in the gadget.
The cost/IR abstraction needs at least one of {amortized Bell-prep accounting,
multi-gate burst credit, off-metric teleport channel}. Match `[[project_teleport_triangle_blocker]]`.

## Reviewer / citation frame (hand to paper track)
- Position against **RTG (2502.04138)** and **TeleSABRE (2505.08928)** as the
  nearest routing-integration neighbors; against **AutoComm (MICRO 2022)** as the
  MICRO-precedent cost-model ancestor; against **Devulapalli (2204.04185)** for the
  "teleport can beat SWAP" theory motivation.
- The defensible claim: "first to fold non-local-gate teleportation into the routing
  heuristic as a per-gate realization on a flat single-device topology, and first to
  do so for a single-qubit gate on a delocalized dual-rail qubit." Verify the second
  clause against a fresh arXiv sweep near submission (preprints move fast: dSABRE is
  already 2026).
- Do NOT claim we invented gate teleportation or non-local gates; cite Eisert,
  Gottesman-Chuang, Zhou-Leung-Chuang as the primitive's lineage.

## Unverified / to recheck before submission
- Absence claims are "not found in this sweep," not proofs. Re-sweep arXiv quant-ph
  for dual-rail/distributed-dual-rail compiler preprints near submission.
- A few quantitative figures (Cuomo, Ferrari, Bandini) were abstract-only; pull
  full text if cited with numbers.
