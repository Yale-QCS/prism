# S2 background citation ledger (dual-rail/erasure + compiler-IR)

Written 2026-06-11 by the background-section track. Companion to
`classical_compilation_refs.md` (which covers S2's classical paragraph).
Fills the "CITATION AGENT: assemble the chain" slot in
`claims_and_blocks.md` blocks (a)/(b). All fields below were verified by
web agents against arXiv/journal pages on 2026-06-11; the week-4 bib pass
re-checks before submission. User supplied the seed list (16 entries,
2026-06-11); 9 were already in refs.bib or duplicates, 7 new, plus 11 found
by search.

## Block (a) theory chain: why erasure conversion is the right first move

| key | ref | role |
|---|---|---|
| grassl_erasure_1997 | Grassl/Beth/Pellizzari, PRA 56, 33 (1997) | erasure channel QEC is easier, foundational |
| bennett_erasure_1997 | Bennett/DiVincenzo/Smolin, PRL 78, 3217 (1997) | erasure channel capacity, foundational |
| wu_erasure_2022 | (existing) Wu/Kolkowitz/Puri/Thompson, Nat Commun 2022 | erasure conversion proposal; threshold 0.94%->4.15% |
| kubica_erasure_2022 | (existing) Kubica et al., PRX 13, 041022 (2023) | T1-limit argument for superconducting circuits |
| gu_faulttolerant_2025 | Gu/Retzker/Kubica, PRR 7, 013249 (2025) | FT architectures from erasure qubits |
| gu_optimizing_2025 | Gu/Vaknin/Retzker/Kubica, PRX Quantum 6, 040354 (2025) | erasure-check schedule optimization, dual-rail-specific |
| chang_imperfect_2025 | Chang/.../Teoh/Puri, PRX Quantum 6, 040355 (2025) | surface code under imperfect erasure checks, dual-rail-specific |
| sahay_biased_2023 | Sahay/Jin/Claes/Thompson/Puri, PRX 13, 041013 (2023) | biased-erasure noise model (optional) |

## Block (b) hardware chain: the platform attention is real

Origin and photonic line: chuang_simple_1995 (PRA 52, 3489; names dual-rail;
arXiv quant-ph/9505011, NOT 9503016 which is Barenco) -> knill_klm_2001
(existing).

Superconducting cavity dual-rail (Yale/QCI): teoh_dual-rail_2022 (existing;
PNAS proposal) -> koottandavida_erasure_2024 (PRL 132, 180601; double-post
cavity erasure check, Devoret) -> chou2024superconducting (existing; Nat
Phys 2024 erasure-detected logical measurement) -> degraaf_midcircuit_2025
(npj QI 11, 1; mid-circuit check, missed-erasure 9e-4) ->
mehta_bias-preserving_2025 (existing; SWS 2Q gate <0.1% infidelity, STILL
arXiv-only as of 2026-06).

Superconducting transmon dual-rail: levine_demonstrating_2024 (existing,
AWS) ; multi-qubit milestone huang_logical_2026 (SUSTech; PUBLISHED Nat Phys
22, 591 (2026), was arXiv:2504.12099; 4 dual-rail qubits, GHZ 93.5%) ;
wills_metrology_2025 (OQC multimode, arXiv-only, optional breadth).

Neutral atoms: scholl_erasure_2023 (Nature 622, 273; first Rydberg erasure
conversion) + ma_midcircuit_2023 (Nature 622, 279; mid-circuit conversion,
back-to-back issue mates) -> zhang_metastable_2025 (arXiv:2506.13724;
logical-level Yb).

Trapped ion: kang_trappedion_dualrail_2023 (existing).

Encoded-gate lineage (primitives block): reinhold_errorcorrected_2020 (Nat
Phys 16, 822; error-corrected gates on an encoded cavity qubit).

Optional/adjacent, not added: li_autonomous (Nat Commun 15, 1681 (2024),
autonomous correction, not erasure-framed), violaris 2601.02183 (OQC
perspective review), Dakis 2510.08416 (dynamical error reshaping), Bluvstein
2024 (not erasure-specific), Mai 2601.21616 / Liu 2604.08672 (too recent).

## Compiler-IR subsection findings

- QIR opaque-qubit claim: attribute to the QIR spec itself
  (qiralliance_spec, @misc, github.com/qir-alliance/qir-spec), not
  McCaskey/Q-MLIR. McCaskey stays cited for the MLIR dialect work.
- GAP-CLAIM THREAT: Watkins et al. Quantum 8, 1354 (2024), ALREADY CITED,
  explicitly builds a lattice-surgery IR as its central abstraction;
  Chipmunq (arXiv:2603.16389, 2026) has a logical-to-physical IR for
  chiplet FT. The sentence "no widely adopted toolchain treats
  logical-to-physical lowering as a first-class compiler problem with its
  own IR" must be sharpened to: those IRs are code-specific and bind a
  single realization; none carries a candidate realization set the router
  can exploit. Proposed wording awaiting user ratification.
- Strong negative (two independent agents): NO compiler/routing/transpiler
  paper targeting dual-rail or erasure-detected hardware exists 2022-2026.
  Closest: Herzog/Berent/Kubica/Wille lattice-surgery line (already in S8
  set).
- Field upgrades banked: SABRE ASPLOS 2019 pp. 1001-1014 DOI
  10.1145/3297858.3304023; MLIR CGO 2021 pp. 2-14; t|ket> QST 6(1) 014003
  (2020); Qiskit arXiv:2405.08810 unpublished as of 2026; Catalyst JOSS
  9(99):6720.
- Ding (Yale) 2023-2026: nothing dual-rail/erasure-relevant for S2. HetEC
  (ASPLOS 2025, arXiv:2411.03202, heterogeneous QEC architecture) is an S8
  candidate at most.

## Existing-draft bugs found (fixed in 02_background.tex 2026-06-11)

1. chou2024superconducting was cited under "photonic systems"; Chou is a
   superconducting cavity experiment. Platform sentence rewritten with the
   correct four-way grouping.
2. Levine (transmon-transmon) was grouped under "transmon-cavity".
3. QIR opaque-qubit claim mis-attributed (see above).

## Quote misattribution resolved (2026-06-11)

The "antagonistic optimizations" quote is NOT Bradlee 1991. Verbatim source:
Ambrosch/Ertl/Beer/Krall, "Dependence-conscious global register
allocation," LNCS 782, pp. 125-136 (1994), abstract: "Register allocation
and instruction scheduling are antagonistic optimizations: Whichever is
applied first, it will impede the other." Fixed in 02_background.tex (red
VERIFY marker removed; ambrosch_dependence_1994 added; Bradlee demoted to
the empirical-study citation) and in classical_compilation_refs.md.

## Reading queue (user dump 2026-06-11; read one by one, user places each)

23 links from the user, cataloged 2026-06-11; synopses from abstracts only,
none deep-read yet. "in bib" = key exists in refs.bib. Placement is the
user's call per item; fill the field during the read-through.

1. arXiv:2504.21172v2, Jin et al., "Iceberg Beyond the Tip: Co-Compilation
   of a Quantum Error Detection Code and a Quantum Algorithm". IN BIB
   (jin_iceberg_2025), S8 prose drafted. The placement-time
   realization-choice competitor. Placement: S8 (drafted); user may want S2.
2. arXiv:2207.11674, Wu et al., "AutoComm" (MICRO 2022). IN BIB
   (wu_autocomm_2022), S8 prose drafted. Burst communication scheduling for
   distributed programs. Placement: S8 (drafted).
3. arXiv:2605.16595, Paz/Grossman, "qstack: Compositional End-to-End
   Compilation for Fault-Tolerant Quantum Programs" (May 2026, arXiv-only).
   Pass-chain framework encoding logical circuits into small codes.
   Placement: TBD (gap-paragraph neighbor or S8).
4. arXiv:2510.13541, Haug et al., "Lattice surgery with Bell measurements"
   (arXiv-only). Module-crossing surgery via Bell measurements at ~40%
   entanglement saving. Placement: TBD.
5. PRL 134, 090602 (2025) = arXiv:2407.16336, Shaw et al., "Lowering
   Connectivity Requirements For Bivariate Bicycle Codes Using Morphing
   Circuits". Degree-6 -> degree-5 syndrome circuits, biplanar layout.
   Placement: TBD (connectivity-bought-with-compilation theme).
6. arXiv:2505.16891v2, Zhu et al., "Quantum Compiler Design for Qubit
   Mapping and Routing: A Cross-Architectural Survey" (arXiv-only).
   Mapping/scheduling survey across SC/ion/atom. Placement: TBD (S2 routing
   paragraph umbrella cite candidate).
7. arXiv:2602.24062, Bandini et al., "Optimized Compilation for Distributed
   Quantum Computing" (arXiv-only). Greedy EPR-sharing gate grouping +
   commutative reordering. Placement: TBD (S8 distributed cluster).
8. arXiv:2603.29536, de Ronde et al., "Logical-to-Physical Compilation for
   Reducing Depth in Distributed Quantum Systems" (arXiv-only). CNOT-chain
   grouping over shared entanglement. Placement: TBD (S8 distributed
   cluster).
9. arXiv:0804.4050, Jozsa/Miyake, "Matchgates and classical simulation of
   quantum circuits", Proc. R. Soc. A 464, 3089 (2008). Clifford-algebra
   matchgate simulability; NN matchgates classical, NNN universal.
   Placement: TBD (S3 matchgate/G(A,B) foundation next to
   brod2011extending).
10. arXiv:1106.1863, Brod/Galvao, PRA 84, 022310 (2011). IN BIB
    (brod2011extending), cited in S2 primitives + S3. Parity-preserving
    extension of matchgates to universality. Placement: done (verify S3 use
    during read-through).
11. arXiv:2601.20927, Koh et al., "Entangling logical qubits without
    physical operations" (arXiv-only, Jan 2026). "Phantom codes": logical
    entangling gates by compile-time qubit relabeling, zero physical ops.
    Closest-in-spirit neighbor to realization-choice-as-IR. Placement: TBD.
12. arXiv:2601.02183, Violaris et al., "Developments in superconducting
    erasure qubits for hardware-efficient quantum error correction"
    (arXiv-only perspective, OQC). Review of the dual-rail erasure line.
    Placement: TBD (S2 umbrella cite candidate).
13. arXiv:2508.20858, Zhou et al., "Louvre: Relaxing Hardware Requirements
    of Quantum LDPC Codes by Routing with Expanded Quantum Instruction Set"
    (arXiv-only). BB-code routing, degree 6 -> ~4-4.5 via expanded ISA.
    Placement: TBD (connectivity-bought-with-compilation theme).
14. arXiv:2511.18770, Li et al., "HOPPS: Hardware-Aware Optimal Phase
    Polynomial Synthesis with Blockwise Optimization" (arXiv-only).
    SAT-optimal {CNOT, Rz} block resynthesis. Placement: TBD (S8 synthesis
    or pre-lowering future work).
15. arXiv:2511.01260, Shirai et al., "High-fidelity all-microwave CZ gate
    with partial erasure-error detection via a transmon coupler"
    (arXiv-only). Coupler measurement converts some gate failures to
    heralded erasures. Placement: TBD (S2 erasure-hardware breadth).
16. PRR 7, 023120 (2025) = arXiv:2408.03064, Baumer/Woerner,
    "Measurement-Based Long-Range Entangling Gates in Constant Depth".
    Fan-out/long-range CNOT to constant depth via feedforward on a line.
    Placement: TBD (teleport-extension S6/S8 neighbor).
17. PRX Quantum 5, 030339 (2024) = arXiv:2308.13065, Baumer et al.,
    "Efficient Long-Range Entanglement using Dynamic Circuits". CNOT
    teleportation across 101 qubits with mid-circuit measurement +
    feedforward. Placement: TBD (teleport-extension S6/S8 neighbor).
18. NJP 23, 043015 (2021) = arXiv:2012.09061, van de Wetering,
    "Constructing quantum circuits with global gates". Clifford+phase
    circuits via global entangling interactions, count tied to non-Clifford
    phases. Placement: TBD.
19. arXiv:2510.16788, Nemirovsky et al., "Phase gadget compilation of
    quantum circuits using multiqubit gates" (arXiv-only). Phase-gadget
    compilation onto native multiqubit ion gates. Placement: TBD (S8
    commutation/synthesis cluster).
20. arXiv:2509.18547, Teoh et al., "Robust quantum communication through
    lossy microwave links" (arXiv-only, Yale). Heralded Bell pairs at 92%
    over a 2%-efficiency link; module-to-module teleportation at 90%.
    Placement: TBD (grounds teleport-realization Bell-resource story).
21. arXiv:2507.23011, Mathews et al., "Placing and routing quantum LDPC
    codes in multilayer superconducting hardware" (arXiv-only). HAL
    heuristic, ~150 explicit qLDPC layouts. Placement: TBD
    (placement/routing-for-codes neighbor).
22. arXiv:2408.00829 = gu_optimizing_2025, PRX Quantum 6, 040354. IN BIB,
    cited in S2 (check-schedule clause). Placement: done.
23. PRR 7, 013249 = gu_faulttolerant_2025. IN BIB, cited in S2 (same
    clause). Placement: done.

## Open

- Gap-paragraph rewrite RATIFIED + LANDED 2026-06-11 (code-specific,
  single-realization, no candidate set). Dual-rail subsection finalized same
  day (Kang demonstrated->proposed precision fix; scheduling-freedom
  colon-pivot restructured).
- Mehta/Zhang/Wills publication status + the two new-style APS DOIs
  (10.1103/985g-58gd, 10.1103/d1v7-nctj): re-check at week-4 bib pass.
- Reinhold/Li/Sahay banked in refs.bib but uncited in S2 (no honest slot;
  see chat note). Candidate homes: S8 or the noise appendix.
