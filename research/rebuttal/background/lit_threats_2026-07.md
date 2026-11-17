---
name: reference-lit-threats-2026-07
description: "2026-07 literature sweep; Canopus/ReQISC/Iceberg-Patches are the must-cite near-neighbors, each differentiated by binding time + layout-dependent realization sets"
metadata: 
  node_type: memory
  type: reference
  originSessionId: aea4aa3e-75f1-466b-a6ba-ab2cfa83e02b
---

**Decision (2026-10-05):** Canopus and ReQISC are not cited. Evan judged both low quality. Iceberg Patches is cited (mazzetti).

2026-07-16 threat sweep (full detail:
`research/rebuttal/background/research_review_2026-07-16.md`). Three must-cites, none
fatal: Canopus (arXiv 2511.04608, ISCA'26) selects among SYNTHESIS pathways of
one fixed-wire gate inside SABRE via monodromy-polytope cost, the closest
analogue; ReQISC (2511.06746, ASPLOS'26) picks among native gate types per pair
(hardware knob, layout-independent); Iceberg Patches (2604.09956) + Iceberg v2
(2504.21172) select gadget structure at encoding time, pre-routing. PRISM's
differentiator against all three: the realization set is encoding-derived,
placement-dependent, and bound at routing time against the live layout. The
quotient/dual-rail formalization space had no competitor as of the sweep.
MICRO 2026 program not yet public; re-sweep in August. 2607.10274 (commuting
blocks) and 2603.29536 (distributed decompositions): confirmed no-threat.
Positioning ammo: EDA e-graph technology mapping (Smith arXiv 2404.00786, Kong
PLDI'26) as the classical analog; Mehta 2503.10935 pins the noise parameters
(0.53%/CZ, durations); ERADO paper 2606.31428 yield model matches our
Eq. accept-gates exactly. See [[project-prism-vs-greedy-mechanism]].
