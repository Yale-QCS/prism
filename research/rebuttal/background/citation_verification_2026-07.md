---
name: reference-citation-verification-2026-07
description: "External verification report (2026-07-31) fully dispositioned; citation base checked; key rulings on baselines, QCI, and version facts"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 38c1cd8c-5b4b-4f94-b0f7-11e950e871ec
  modified: 2026-08-01T03:05:41.821Z
---

An external verification report on the submission was triaged and closed 2026-07-31. Do not re-audit these:

- Every flagged citation resolved: MIRAGE + Marol cited and distinguished in §6 (report didn't know the user IS the MIRAGE author); Kuehnke/Sayginel/Benhemou bib entries were already correct; "Pavlovich & Puri" was never in the paper; arXiv:2509.18547 verified (Teoh lead, lossy microwave links, cited correctly in §6); Violaris confirmed in Materials for Quantum Technology (accepted 2026-07-29, volume/pages unassigned, re-check at camera-ready); Crooks note current version is v0.11.0 beta 2026-02-21 (report's "v4" was wrong), bib title fixed to "Gates, States, and Circuits: Quantum Gates".
- Chou bit-flip suppression: published Nature Physics says "at least 150 times", arXiv says 140. Paper cites the journal version so prose says 150. Rule: match the number to the version cited.
- §5.1 no-baseline paragraph (before the implementation paragraph): existing encoded-op routers each target one code+architecture, none accepts a realization set, hedged "to the best of our knowledge" up front; Qiskit gained multi-representation framework support only in v2.5 (July 2026), cited via qiskit_multistage_2026 (also cited in §2's framework list; intentionally dropped from §1).
- User rulings: MIRAGE/Marol cannot be baselines (structurally cannot consume the input; adapting them = reimplementing the contribution); no QCI/Aqumen mention (unpublished algorithm is not citable prior art); mehta residual params are correctly attributed to liu_toric_2026 as projections.

Related: [[lit-threats-2026-07]].
