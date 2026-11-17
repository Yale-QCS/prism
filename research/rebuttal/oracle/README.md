# Exact oracle: PRISM's and Greedy's gap to optimal, and retained sets under a second router (A-Q2, D-Q2)

## Pre-registration (2026-10-07, before running)

- **Router:** `scripts/paper/oracle.py`, unchanged. Dijkstra over (canonical layout, done set) with a joint initial layout, unit-cost SWAPs, and a zero-cost closure that executes every ready gate with an adjacent support. Its bound is admissible, so it is exact when it finishes.
- **Instances:** the script's built-in catalog of 21 CR_z-only circuits with 3–5 logical qubits on chains and 2×n grids, including two spare-pair instances. The catalog is fixed in code, and no instance is added or dropped after the run.
- **Time cap:** 600 s per solve (`config.toml`). An instance counts as certified only if both solves (four supports and one support) finish exactly within the cap. Uncertified instances are listed, but they are excluded from every gap statistic.
- **Compiler runs:** Greedy and PRISM through `build_pm` with local initialization, which has no co-location herald, so the counts match the oracle's gate-routing SWAPs. The objective is `swaps`, at seeds 0, 100 and 200, on the current build (`561bcfb`) with the time-aware flags off. Both the minimum over the seeds and the mean are reported.
- **Reported per certified instance:**
  - S4 = optimal SWAPs with all four supports;
  - S1 = optimal SWAPs with the single default support;
  - PRISM's and Greedy's SWAPs.
- **Summary statistics:**
  - A-Q2, myopia: PRISM's gap PRISM − S4, in SWAPs and as a fraction of S4 where S4 > 0, and the number of instances where PRISM is optimal. The same for Greedy.
  - D-Q2, retained sets under a non-SABRE router: S1 − S4 per instance and in total.
  - Caveat, stated with the result: S1 fixes the default realization. Greedy instead binds the nearest realization at route entry, so S1 bounds fixed binding in general, not Greedy's own optimum.
- **What this cannot show:** these are small instances only, at most 5 logical qubits, because the search is exponential. They say nothing about gaps at n = 8 or larger.

## Results (2026-10-07; `data/oracle.jsonl`, `data/run.log`; run on `561bcfb`, flags off)

All instances have 3–5 logical qubits on 6- to 10-node chains and 2×n grids, so none of these numbers is a claim about n = 8 or larger.

- **Certified:** 17 of 20 instances, all with 3–4 logical qubits. The three 5-qubit instances (k5_chain10, rand_dag_n5_s42_chain10, k5_grid25) are uncertified, because their single-support solve hit the 600 s cap. The log's "HARD FAILURE: certificate replay failed" lines are those three: a capped solve returns a bound with no certificate to replay. Their four-support solves are exact (S4 = 1, 0 and 0). PRISM and Greedy match those values, but they stay out of the statistics, as pre-registered.
- **A-Q2 (gap to optimal), 17 certified instances with 3–4 logical qubits:** PRISM's SWAPs equal the exact four-support optimum S4 on 17 of 17, and so do Greedy's. But S4 = 0 on all 17: every instance routes with zero SWAPs under a free joint initial layout. These instances are too small to separate the two compilers or to measure myopia. The result shows that neither compiler is far from optimal on trivially routable instances, and nothing more.
- **D-Q2 (retained sets under a non-SABRE router), the same 17 instances:** with only the default support fixed, the exact optimum S1 is positive on 8 of 17 instances, at 2–6 SWAPs and 23 SWAPs in total. With all four supports it is 0 on all of them. So under a second, exact router the same realization sets remove every SWAP that a fixed default realization needs.
- **Caveat on S1:** S1 fixes the default realization. Greedy instead binds the nearest realization under its entry layout, and it reaches 0 SWAPs on all 17 instances. So S1 bounds fixed default binding, not Greedy. The D-Q2 number shows that retained sets matter to an exact router. It does not show PRISM's edge over Greedy.

### Draft rebuttal paragraphs (each ≤ 120 words)

A-Q2 (myopia): "On 17 small instances (3–4 logical qubits, 6–8-node chains and grids) that an exact Dijkstra router certifies, PRISM and Greedy both match the optimal SWAP count. These instances are routable without SWAPs under a free initial layout, so they cannot measure myopia at the sizes we evaluate. The exact search does not finish in 600 s at five logical qubits, so the gap to optimal at n ≥ 8 stays open, which we now state as a limitation."

D-Q2 (a second router): "The same realization sets drive a non-SABRE router: our exact Dijkstra router over (layout, executed gates) treats each gate's realizations as alternative supports. On 17 certified instances (3–4 logical qubits), fixing every CR_z to one default realization raises the optimum from 0 to 2–6 SWAPs on 8 instances (23 in total), and retaining all four removes them. The availability relation is router-independent; SABRE is one host."

## Follow-up: fixed initial layouts (pre-registered 2026-10-07, before any code; prism-66's design)

The first run was weak because a free joint initial layout lets every small instance route without SWAPs. Fixing the initial layout makes the question about routing from a given layout, which is the setting a layout search hands to the router.

- **Instances:** the 17 instances certified in the first run (3–4 logical qubits).
- **Layouts:** for each instance, k = 5 random injections of its rails into the graph's nodes, drawn with `random.Random(2026).sample` per instance. Every arm and every solve uses the same layouts.
- **Per (instance, layout λ0):**
  - S4(λ0): the exact optimum from λ0 with all four supports. `oracle.solve` seeds only λ0.
  - SG(λ0): the exact optimum from λ0 with each gate's support fixed to the realization Greedy binds at λ0. Greedy's rule is the nearest realization by rail distance at λ0, with ties to the default (index 2) and then the lowest index, as in `closest_realization`. This is Greedy's commitment with perfect routing.
  - PRISM(λ0) and Greedy(λ0): one route from λ0 through `PrismRouting._route` with no layout search and no refinement, with 40 SWAP trials (the paper's final-route trials) and seed 0. Local initialization, so no herald.
  - Cap: 600 s per solve. A pair counts only if both S4 and SG are exact.
- **Readings, all stated with the instance sizes:**
  - PRISM − S4: PRISM's myopia gap at a given layout (A-Q2).
  - SG − S4: the cost of early commitment alone, with routing made perfect (A, D-Q2).
  - Greedy − SG: Greedy's heuristic loss.
  - Reported as totals over pairs, the number of pairs with each gap > 0, and the fraction of pairs with S4 > 0.
- **Check before concluding:** if fewer than half of the certified pairs have S4 > 0, the layouts still route almost free. The run is then repeated once on sparser graphs at the same n (chains in place of grids), with the result reported either way.
- **Limits:** 3–4 logical qubits, small graphs. A heuristic route from one layout without refinement is not the paper's full search; it isolates the router.

### Results (2026-10-07; `fixed_layout.py` → `data/fixed_layout.jsonl`, `data/fixed_layout.log`)

The instances are 17 CR_z-only circuits with 3–4 logical qubits and 2–15 CR_z gates, on 6- to 10-node chains and 2×n grids, each from 5 fixed random initial layouts. None of these numbers is a claim about n = 8 or larger.

- **Certified:** 85 of 85 (instance, layout) pairs. Both exact solves finished within the cap for every pair.
- **Sparsity check passed:** 49 of 85 pairs (58%) have S4 > 0, above the pre-registered half, so no rerun on sparser graphs was needed.

| summed over 85 pairs | SWAPs |
|---|---|
| S4, exact optimum with four supports | 87 |
| PRISM, one route from the layout | 88 |
| SG, exact optimum with Greedy's binding fixed | 119 |
| Greedy, one route from the layout | 124 |

| reading | total | pairs > 0 | pairs < 0 |
|---|---|---|---|
| PRISM − S4: PRISM's myopia gap (A-Q2) | 1 | 1 | 0 |
| Greedy − S4 | 37 | 20 | 0 |
| SG − S4: cost of early commitment alone, with routing made perfect | 32 | 20 | 0 |
| Greedy − SG: Greedy's heuristic loss | 5 | 3 | 0 |

**Claim:**
- From a fixed layout on these small instances, PRISM routes optimally in 84 of 85 pairs. It is one SWAP above optimal in total.
- Greedy's 37 excess SWAPs come almost entirely from committing early. Fixing Greedy's binding and routing it perfectly still costs 32 SWAPs (86%) over the optimum. Greedy's heuristic routing adds only 5.
- So the gain is commitment timing, not heuristic luck. A perfect router cannot recover what early binding gives up.

**What this does not show:** gaps at n ≥ 8, where exact search is out of reach, or the effect of the layout search, which this design removes on purpose.

### Draft rebuttal paragraph (A-Q2 and D-Q2, ≤ 120 words)

"To separate commitment timing from routing quality, we fix the initial layout and compare against an exact Dijkstra router on 85 certified (instance, layout) pairs with 3–4 logical qubits and 2–15 CR_z gates. PRISM is optimal in 84 of 85 pairs (88 SWAPs against an optimum of 87). Greedy uses 124. Fixing Greedy's realization choices and routing them optimally still costs 119. So 32 of Greedy's 37 excess SWAPs come from committing early, and only 5 from its routing heuristic. A better router cannot recover what early binding gives up. The same realization sets drive this non-SABRE exact router, which also answers D-Q2. Exact search does not scale past five logical qubits, so we state the gap at n ≥ 8 as open."
