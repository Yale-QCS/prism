# Commutation-aware PRISM: measurements and options (2026-10-06)

This is a design study; no compiler code was changed. It bears on reviewer items R3 (objectives beyond SWAPs) and R4 (cost beyond distance) in `../reviews.md`, and partly on G3 (routers beyond SABRE).

Setup: `core`, seeds 0–2, the paper budget (40+3 starts, 16 iterations, 40 final trials), and both kernel arms. The existing switches are `commute_diagonal` (dependencies relaxed among {crz, rz}), `reschedule` (critical-path re-emission of the output) and `objective`. The configs are in `configs/`, the rows in `data/`, and `sweep_table.py` prints the tables.

## Audit (2026-10-06)

- Correctness: `tests/test_encoded_equivalence.py` compares routed rail statevectors with the encoded logical state for both Greedy and PRISM, with commutation off, on, and on with rescheduling (3 seeds). Rescheduling does not change routes: with it on, SWAP counts and realization choices match the paper rows in 192 of 192 runs.
- Completeness: every row file has 192 of 192 successful runs except `depth_time1com.jsonl` (189). Its sums cover different runs from the comparison rows, so ignore it.
- The patched variants (window, level, final_only, urgency, time) record the same config fields as plain commutation; only the file name identifies the variant.
- The "paper" row in the tables is not rescheduled; every other row is. Comparisons against it mix the rescheduling gain with the variant's own effect.
- The `objective` selects among starts on the routed circuit before the physical stage (O3 and rescheduling); the reported metrics are measured after it.
- Under program order Greedy's gates are fixed TwoQ nodes, so router-side prototypes acting on multi-realization nodes (time-aware cost) affect only PRISM there; those rows are not controlled.
- Seeds were not independent (found 2026-10-06 by the suite session). Random start s uses seed base+s and the standard layouts use base+40..42, so outer seeds 0, 1 and 2 share 41 of their 43 starts. Every comparison here is still a valid A/B between configurations, because all configurations use the same starts. But the "3 seeds" are close to one seed's worth of search, so no per-seed spread from this study is meaningful. The suite now spaces seeds 100 apart.
- `full_adder` is the same circuit as `cdkm_ripple_carry_adder` (every row identical), so the suite sums here count that workload twice. The suite now uses `vbe_ripple_carry_adder` instead.
- The configs under `configs/` record exactly what produced `data/` and are kept as they are. New runs derive from the current `configs/paper/core.toml` (spaced seeds, vbe_ripple_carry_adder, heavy_hex).
- Scope: 3 seeds and the 16-workload, two-topology suite. Anything that goes into the paper must be re-run on the current suite (more workloads, plus heavy_hex) at 20 seeds.

## Findings

1. **For this ISA, {crz, rz} is the complete commutation structure.** The lowered ops are crz (4 realizations), rz, rx (one rswap on its rail pair), x and joint_herald (preparation), and measure. The only other commuting pair would be rx with rx, and consecutive RX gates are already merged during logical optimization. A general checker or DAGDependency would find nothing extra.

2. **The headroom is large.** `headroom.py` gives the routing-free depth with all-to-all connectivity, summed over 16 workloads:

   | dependencies | fixed realization | free rail choice |
   |---|---|---|
   | program order | 750 | 750 |
   | commutation | 586 | 545 |

   Rail choice gains nothing under program order, because an unresolved CR_z blocks all four rails of both qubits. Commutation is what makes port parallelism possible. Examples: rg_qft_multiplier 116 → 47, multiplier 118 → 49.

3. **The router currently throws the headroom away.** With commutation, PRISM's routed depth gets worse, not better. On the grid: 2435 → 2662 depth (no rescheduling) and 2229 → 2590 (with rescheduling), while Greedy's improves.
   - `critpath.py` on bmw_quark_copula (grid): Greedy goes 70 → 43, PRISM goes 35 → 70.
   - PRISM's critical path becomes a zigzag of CR_z → RX → CR_z across qubits (35 CR_z, 27 RX, 6 SWAP).
   - Reading: SABRE executes every executable gate immediately. With relaxed dependencies some qubits race ahead while others lag, and PRISM races more because its realization sets make more gates executable.

4. **Not a commit-time choice problem.** `rebind.py` re-picks each CR_z among the rail pairs adjacent at commit time, minimizing start time, with the SWAPs fixed. Total depth: 888 → 892, i.e. no gain. Almost always only one pair is adjacent. The loss is in where the SWAPs bring partners, and in the execution order.

5. **Heuristic weights don't fix it.** `heuristic_config = "tuned"` (Size-scaled basic term, lookahead 40, decay 0.01) with commutation leaves PRISM's grid depth edge at 3.5–6.6% and makes absolute durations worse.

6. **The existing knobs already give large absolute gains** (rescheduling on in every row except the paper's):

   | config | grid: PRISM duration µs (edge vs Greedy) | hex: PRISM duration µs (edge) | SWAP edge, grid / hex |
   |---|---|---|---|
   | paper (swaps, order, no reschedule) | 832 (13.5%) | 906 (1.9%) | 30.6 / 25.5% |
   | swaps, order, reschedule | 759 (16.7%) | 851 (5.9%) | 30.6 / 25.5% |
   | depth, order | 696 (9.7%) | 746 (9.8%) | 33.7 / 26.6% |
   | best of order/commute, by depth | 690 (6.9%) | 721 (9.6%) | 22.4 / 27.7% |

   Rescheduling is a free win for both arms. Depth or duration selection cuts PRISM's absolute duration by 16–20% from the paper, while the SWAP edge stays at 22–35%.

7. **Two hypotheses tested** (`patched_run.py`, which patches PrismRouting in-process and runs `run_fairness`; rows in `data/*_final_only`, `*_window*`):
   - H1, commutation only in the final route (refinement under program order): helps SWAPs, does not recover depth.
   - H2, bounded reordering, where a diagonal gate may overtake at most K earlier diagonal gates on each rail: K = 2 fixes most of the racing. Under SWAP selection, PRISM gets 657 vs 720 SWAPs at equal depth and duration on the grid, and 1107 vs 1192 SWAPs with 5% less depth on hex. Under depth selection no variant beats program order yet.

8. **Portfolios** (each run keeps the best dependency rule under the objective, for both arms) lower PRISM's absolute depth and duration further. With depth selection, the best of all six rules gives grid 1994 depth / 685 µs and hex 2137 / 716 µs, i.e. 18–21% less duration than the paper. But Greedy gains about as much, so PRISM's edge stays at 20–34% SWAPs and 7–11% depth and duration.

9. **What is PRISM-only.** By the routing-free bound, most of commutation's depth potential (750 → 586) is open to a fixed-realization router too. Only the last step (586 → 545, about 7%) needs realization choice, i.e. port parallelism. The SWAP edge (25–35% in every configuration) is PRISM's robust, unique win.

10. **Level window and urgency weighting** (`cmp.py` prints every variant):
    - Level window (`MODE=level<W>` in `patched_run.py`): a gate enters the front layer only once all gates more than W dependency levels below it are done. With W = 1 under SWAP selection, PRISM's hex result beats program order on every metric (1131 vs 1192 SWAPs, 2417 vs 2610 depth, 809 vs 851 µs); the grid is roughly even. Under depth selection it ties program order on hex and loses slightly on the grid.
    - Urgency weighting (a Rust prototype, now reverted): each pending multi-realization gate's SWAP-score term is weighted by α^(level − shallowest pending level), with α = 0.5 and 0.25. It improves on plain commutation (grid depth 2590 → 2384) but is worse than the restrictions and than program order.
    - Conclusion: restricting or reweighting commutation limits the damage but never makes commutation a depth gain under depth selection. With distance-only SWAP scoring, commutation's freedom is spent on fewer SWAPs, never on parallelism. The untested lever is time-aware scoring (per-rail ready times), which would prefer SWAPs and realizations on idle rails.

11. **Time-aware realization cost** (a Rust prototype, now reverted). It kept a per-physical-qubit ready time, updated on every SWAP and every two-qubit commit (one hook in the vendored `route.rs` for fixed gates), and scored each pending gate's realizations as distance + λ × (how late its rails are free − the earliest-free rail), λ ∈ {0.25, 0.5, 1}.
    - It moves PRISM along the SWAP/depth frontier, not past it. With λ = 0.5, program order and depth selection, PRISM reaches grid 1981 depth / 679 µs (the best so far) and hex 2240 / 734, but with many more SWAPs (1211 vs 861 on the grid).
    - Caveat: under program order Greedy's gates are fixed TwoQ nodes, so the time term does not apply to Greedy; the PRISM-vs-Greedy edges in those rows are not controlled.
    - Plateau: across program order with depth selection, portfolios, the level window and time-aware cost, PRISM's best absolute duration is about 680–720 µs, i.e. 13–21% below the paper's 832/906.

12. **Remaining lever: a post-routing joint reorder and re-bind.** Keep the program-order routes. Let commuting CR_z gates move in time and switch to another rail pair that is adjacent at that moment, minimizing the critical path. It adds no SWAPs and cannot increase depth. The current rescheduler already does the reordering half and already captures part of the commutation headroom: PRISM's routed depth (about 660 per seed) is below the routing-free program-order ideal (750). The routing-free commutation ideal is 545.

Next: confirm the top configurations at 20 seeds, then prototype port-aware SWAP selection in the Rust kernel to test the ~7% PRISM-only depth headroom.

## Options, strongest last

- A. **Rescheduling on for both arms.** No routing change.
- B. **Depth or duration selection.** It already exists; this is the objective sweep reviewer A asked for.
- C. **Commutation as a per-start alternative,** keeping the better route under the objective, for both arms.
- D. **Fix the racing so commutation helps PRISM's depth** (needs Rust):
  - weight front-layer gates by urgency (their dependency level, or slack against the critical path) instead of equally;
  - and/or choose SWAPs and realizations by rail ready time, so commuting CR_z gates spread across a qubit's two rails (the port-parallelism floor in `../port_parallelism/`).

  This is the only option that exploits what realization sets uniquely allow. The routing-free bound says it is worth up to 27% depth. Measure on bmw_quark_copula, rg_qft_multiplier and multiplier first.
