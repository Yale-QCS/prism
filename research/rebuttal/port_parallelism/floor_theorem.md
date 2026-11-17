---
name: project_port_parallelism_floor
description: "Port-parallelism depth floor ceil(Delta/2) is a THEOREM (Petersen 2-factorization), verified, not the conjecture the paper hedges; strongest unclaimed depth result"
metadata: 
  node_type: memory
  type: project
  originSessionId: 56bdf6a2-b4ee-42d2-85ae-865c5d9a72ed
---

2026-06-26 (verified, `research/rebuttal/port_parallelism/verify_port_parallelism.py`).

A dual-rail logical qubit is a **2-port device** (its two rails). A logical CRz(A,B)
uses one port of each endpoint. In an abelian (all-commuting) CRz layer with demand
graph of max degree `Delta`, a time step is a max-degree-<=2 edge subset, so the
depth floor is the minimum number of max-degree-<=2 subgraphs that edge-decompose
the demand graph.

- Fused-node IR: 1 gate per qubit per step => floor `Delta`.
- Port-aware: <=2 gates per qubit per step => floor `ceil(Delta/2)`. **An up-to-2x
  depth win on dense abelian layers (QAOA, Trotter, QFT).**

**This is a theorem, not a conjecture.** Lower bound `ceil(Delta/2)` is immediate
(2 ports). Achievability follows from Petersen 2-factorization (every 2k-regular
graph = k edge-disjoint 2-factors; odd-regular = perfect matching + (r-1)/2
2-factors). Verified by explicit construction on K_4..K_9, 3/4/5/6-regular, path,
ring: all achieve `ceil(Delta/2)` exactly with a valid decomposition.

**Paper impact.** §8:40 hedges this VERIFY/SOFTEN ("the value we conjecture a
port-aware assignment can reach") and the prior draft mis-cited split-thickness for
it; the correct basis is 2-factorization, and it can be stated as a result. The
genuinely OPEN part is what §8 already says: PHYSICAL achievability under routing,
since the two ports are physical rails that must reach their partners. **MEASURED 2026-06-26** (`scripts/research/port_parallelism/measure_port_util.py`,
n=8 grid, 3 seeds): the rail-level router ALREADY realizes port concurrency without
being asked. It doubles up **17%** of CRz on a qubit's two rails in one layer
(walk the routed circuit, ASAP-layer, track p2v through SWAPs, map CRz wires ->
logical via rail v//2), shortening the critical CRz path by a mean **+1.3 layers**
(multiplier +3.3, dj +2.3, qaoa/randomcircuit +2.0). Doubling is HIGHER on
sparse/low-degree circuits (bv 38%, dj 31%) and lower on dense ones (multiplier 6%,
randomcircuit 3%) because routing pushes a busy qubit's CRz across layers. Prism
stays FAR above the ceil(Delta/2) floor (qaoa floor 6 vs achieved 10), so headroom
remains, but the gap is muddied by routing overhead (an UPPER bound on a port-pass's
recoverable savings, not a clean deficit). Folded into §8:40 (now "theorem +
measured partial realization + scoped headroom"). See
[[project_prism_vs_greedy_mechanism]], [[project_four_strategy_ladder]].

**K7 witness VERIFIED + GENERIC (2026-07-16):** independent construction of a
planar, cubic, bridgeless 14-vertex graph whose rail-pair contraction is K7,
3-edge-colorable, so the complete 21-gate CRZ workload runs in 3 physical
layers (single-port machines need chi'(K7)=7, a 2.33x depth separation).
Explicit witness + layers in `research/rebuttal/background/research_review_2026-07-16.md`.
New fact: 41% of ALL random 3/3 rail assignments of K7 are planar (5000-sample
test), so these fabrics are abundant, not fine-tuned. Kept out of the paper
because the router does not exploit it; future-work material.
