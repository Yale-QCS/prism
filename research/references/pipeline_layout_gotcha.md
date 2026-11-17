---
name: project_pipeline_layout_gotcha
description: "TRAP: after the FULL pipeline, property_set['layout'] does NOT match lowering_routed_dag (VF2PostLayout rewrites it against the O3 dag). For a coherent (layout, routed-dag) pair use a truncated logical+lowering run. Plus: delocalization intervals are bimodal across circuits."
metadata:
  node_type: memory
  type: project
  originSessionId: board-drain-2026-06-26
---

A measurement trap that silently invalidates any analysis pairing a layout with a routed DAG.

**The gotcha.** After the full pipeline, `property_set["layout"]` does NOT correspond to `lowering_routed_dag`: VF2PostLayout rewrites the layout against the O3 dag (verified: none of 64 trial `v2p_initial` match). To get a coherent (layout, routed-dag) pair, run a TRUNCATED logical+lowering pipeline, not the full one. Known snag: `multiplier` crashes Qiskit's disjoint-components check on the truncated run (`find_bit` component None), unresolved.

**Bimodal delocalization (2026-06-10, grid n=8, 23 circuits).** Replay of `lowering_routed_dag` over the lowering layout (0 violations on rswap/measure pair-consistency). 9 circuits NEVER delocalize (maxWin=0: opportunistic checks give free full coverage, no forced rejoins); the freedom circuits delocalize for most or all of the circuit (modular_adder 35/35 layers, rg_qft_multiplier 120/120, hhl 68/69, qft 34/37). No middle mode. Idle-separated windows exist (hhl 13 idle layers, rg_qft 10, ae 8). `diagnostics/routing/delocalization_intervals.py`. Drained from board 2026-06-26.
