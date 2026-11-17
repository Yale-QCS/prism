# Time-aware SWAP cost (R4, reviewer A Q1: realization cost beyond distance)

Status: implemented in commits `561bcfb` (additive cost) and `7eb3f54` (lexicographic mode), default off. The implementation lives in the compiler. Historical patches were removed during the 2026-10-08 cleanup; do not apply them to current code. The attempted Logical-SABRE count-after-cleanup change was dropped because it can count semantic SWAPs as routing exchanges.

## Change

Use the current compiler with the configurations below; no patches are required.

- **Ready times:** the routing state keeps a ready time for each physical qubit, in SWAP durations. A committed node advances its qubits to max(ready) + its duration. A SWAP advances its two qubits by 1.
- **SWAP term:** every candidate SWAP also pays `w · λ · (start − now)`. Here `start` = max(ready) of its two qubits, `now` = min(ready) over the active front-layer qubits, and `w` is the basic term's weight, with the same scaling.
- **Realization term** (added 2026-10-07 at prism-66's request, before any run; `wait_realizations`, default on whenever the weight is on):
  - In the front-layer score, each pending gate costs h(g) = min_r [distance_r + λ · wait_r], where wait_r = max(ready of r's rails) − now, evaluated before and after each candidate SWAP. A fixed gate has one realization, so it adds its own λ · wait. The witness rule applies as before.
  - At commit, the executable realization whose rails are free soonest is taken, with ties to the default and then the lowest index. This replaces the tie-break rule only while the term is on.
  - The same weight λ drives both terms. There is no second weight.
- **Both arms:** Greedy and PRISM route through the same kernel call (`prism_routing` → `swap_map`), so both get both terms. Greedy commits its realization at route entry, before any ready time exists, so its commit-time term is zero by construction. That is the phase-ordering point of the paper.
- **Off by default:** `wait_scale = 0` (the default) passes no durations, and scoring is stock SABRE. The mini sub-route problem always runs without the term, because its node indices are not the outer ones.
- **Durations:** each op's duration is the critical path of its default realization (`metrics.physical_duration`), divided by the SWAP duration (200 ns).
- **Touched-node scoring (R6):** `RealizationFrontLayer::score` and `wait_score` sum deltas only over the multi nodes in `phys_to_nodes[a] ∪ phys_to_nodes[b]`, because a SWAP leaves every other node's distance and wait cost unchanged. That removes the O(|F|) loop per candidate SWAP. The extended set keeps its loop, which is capped at the lookahead size.
- **Config:** `wait_scale` in a config (default 0). The rows record it.

## Weight, from the device model (fixed before any run)

The route selector minimizes −log F_cond (`metrics.device_success`).

- A SWAP on the critical path costs its beamsplitter error, ε = −log(1 − RSWAP_ERROR) = 9.90e-5. It also costs the dephasing and bit flips of all n logical qubits over its duration: n · r · t_swap, where r = 2.306e-4 /µs per qubit and t_swap = 0.2 µs.
- Waiting one SWAP duration on the critical path costs only n · r · t_swap.
- The distance term counts about one SWAP per unit distance. So, in the distance term's units, the weight of one SWAP duration of wait is

  λ(n) = n·r·t_swap / (ε + n·r·t_swap)

| n logical | 8 | 13 | 16 | 25 | 32 |
|---|---|---|---|---|---|
| λ | 0.788 | 0.858 | 0.882 | 0.921 | 0.937 |

`wait_scale = 1` uses λ(n) exactly. We report `wait_scale` 0.5 and 2 only as sensitivity. We do not choose the weight by its effect on PRISM's margin.

Limits of the proxy: a rail's wait counts against the earliest-ready front qubit, not the true critical path. Ready times include only two-qubit ops and SWAPs, since single-qubit ops are not in the routing DAG.

## Reading of the matrix (pre-registered 2026-10-07, before any run)

Compare each arm against its own `off` row on core quick and on gcm_h6. Report duration, depth and SWAPs.

- If the SWAP-only row gives most of the duration gain for both arms, report it as a generic router improvement that both compilers get. Credit PRISM's realization term only with the extra gain on top of SWAP-only.
- If the realization term adds duration gain for PRISM beyond SWAP-only, report that extra as realization-specific (R4, reviewer A Q1). For Greedy, the commit-time part is zero by construction, because Greedy binds before any ready time exists.
- Report PRISM's edge over Greedy separately under each row. A larger absolute gain does not by itself mean a larger edge.
- If the derived weight (`wait_scale = 1`) makes either arm worse on −log F, the term does not go into the main results. The sensitivity runs (0.5, 2) do not replace the derived weight.

## Default-flag verification (2026-10-07)

- `pytest`: 196 passed.
- Quick core on the new build against the post-`9cb6c53` quick rows: 288 of 288 runs have identical routing SWAPs and realization choices, and the totals of depth and duration are identical (`compare_routes.py`).
- Quick logical: SWAPs, depth and duration are identical. The idle-prep cleanup removes 426 of 1,584 joint_herald and preparation x gates.
- Routing-stage time on quick core rose from 1,012 s to 1,550 s in total, with 10 workers in both runs. The touched-node scoring allocates and sorts per candidate SWAP, which costs more than the old loop at n=8. The quiet single-process before/after table against n is in `data/route_timing.jsonl` (labels `before_quiet` and `after`; the `before` rows ran under another session's 8-worker load and are not used).

  Routing-stage seconds, summed over qft, multiplier, qaoa and draper_qft_adder on the grid. Routes are identical before and after at every n.

  | n | Greedy before → after | PRISM before → after | PRISM / Greedy before → after |
  |---|---|---|---|
  | 8 | 8.9 → 9.0 | 9.0 → 8.6 | 1.02 → 0.96 |
  | 16 | 104.1 → 98.6 | 108.4 → 100.9 | 1.04 → 1.02 |
  | 24 | 625.7 → 562.3 | 577.9 → 526.7 | 0.92 → 0.94 |

  PRISM's routing stage is 4–9% faster, growing with n, and Greedy gains about as much, since it takes the same multi path. The 1,012 → 1,550 s quick-core difference was machine load. A per-qubit sorted-Vec structure was prepared but not built, because allocation was not the bottleneck.

## Follow-up: lexicographic wait (pre-registered 2026-10-07, before any code; the only follow-up)

The diagnosis from the smoke cell and the SWAP-only row: SABRE scores each candidate SWAP relative to the others and has no "wait" action. A wait term therefore rewards SWAPs that change no distance on idle rails over useful SWAPs on busy rails, and the router pays SWAP error to stay busy.

- **Design:** distance stays primary.
  - At each SWAP step, the candidates within `best_epsilon` of the minimum stock score (the set SABRE picks randomly from) are filtered to those that start soonest: minimum max(ready) over the two qubits. SABRE then picks randomly among the remaining ones as before.
  - At commit, the executable realization whose rails are free soonest is taken. This is already lexicographic, because every executable realization has distance 1.
  - The front-layer realization term (min_r [distance_r + λ·wait_r]) is not used, because it trades distance for wait.
- **Weight:** the ordering has no weight, so λ drops out, and this variant is weight-free. `wait_scale > 0` turns it on. One flag value, `wait_mode = "lexicographic"`, selects it, and both arms get it.
- **Rows:** quick core and gcm_h6 (breadth quick), for each arm against its own off row.
- **Reading and veto:** the same rules as above. If either arm's −log F gets worse, it does not go into the main results. PRISM's realization-specific credit is the gain on top of what Greedy gets.
- **If it also fails,** the answer to A-Q1 is the finding: the formulation accepts any per-realization cost, but a duration-aware cost needs a router that can price waiting against inserting a SWAP. That points to the exact formulation in G3. No third variant.

## Matrix results (2026-10-07, quick core = 16 workloads × 3 graphs × 3 seeds, and gcm_h6 × 3 graphs × 3 seeds; `matrix.py` → `data/matrix.json`, rows in `data/rows/`)

Each arm is compared with its own off row on matched runs. The −log F change decides the veto.

| variant | core −log F, Greedy / PRISM | core SWAPs, Greedy / PRISM | gcm_h6 −log F, Greedy / PRISM | verdict |
|---|---|---|---|---|
| SWAP term only (λ) | +16.9% / +10.3% | +275% / +273% | +36.4% / +13.3% | vetoed |
| SWAP + realization (λ) | +23.0% / +12.8% | +338% / +322% | +42.5% / +10.5% | vetoed |
| SWAP + realization (0.5λ) | +15.2% / +8.5% | +244% / +245% | +36.2% / +10.3% | vetoed |
| SWAP + realization (2λ) | +29.5% / +18.2% | +409% / +394% | +43.3% / +12.3% | vetoed |
| lexicographic (weight-free) | −0.3% / −0.1% | +3.8% / +2.5% | −1.7% / −1.7% | passes, negligible |

- **Additive terms:** every additive variant makes both arms worse, at every weight. Under every variant PRISM's edge over Greedy grows (core −log F edge 5.8% → 9.0–14.0%), but only because Greedy degrades more. By the pre-registered rule that is not credited.
- **Lexicographic:** it passes the veto, but the change is a fraction of a percent on core and 1.7% on gcm_h6, at 3 seeds, so it is probably within noise. Greedy gains slightly more than PRISM, so there is no realization-specific credit. PRISM's −log F edge goes from 5.8% to 5.6%. gcm_h6 is not fixed: PRISM's duration there stays about 6% worse than Greedy's.
- **Reading, as pre-registered:** no variant gives PRISM a gain on top of what Greedy gets. The answer to A-Q1 is the finding. The formulation accepts any per-realization cost, and a time-aware term is easy to add. But SABRE scores candidate SWAPs relative to each other and has no "wait" action, so an additive duration term rewards SWAPs that change no distance on idle rails, and a tie-break-only term has too few ties to matter. A duration-aware cost needs a router that can price waiting against inserting a SWAP, which points to the exact formulation in G3.
- **Code:** both variants stay behind `wait_scale` (default 0) and `wait_mode` (default `additive`). At defaults, quick core reproduces all 288 routes and realization choices after each build (`compare_routes.py`).

### Draft rebuttal paragraph (A-Q1, ≤ 120 words)

"The formulation accepts any per-realization cost, so we tested duration directly: each realization's rail wait, priced in the same −log F units as the route objective, with a weight from the device model rather than a tuned one. Added to SABRE's score, it made both compilers worse, because SABRE compares SWAPs only against each other and cannot wait, so it inserts useless SWAPs on idle rails. As a tie-break only, the change was negligible for both (≤ 1.7% in −log F). A duration-aware realization cost therefore needs a router that weighs waiting against moving, such as an exact formulation in which each gate's adjacency constraint becomes a disjunction over its realizations; the availability relation carries over unchanged."

## Plan

1. After prism-09's run ends: message it, apply, build, `pytest`.
2. Check with `wait_scale = 0` that core quick rows match the current quick rows exactly (SWAPs, depth, realization choices). The patch also restricts front-layer scoring to the nodes on the two swapped qubits (R6 complexity fix), which must not change any route. Log `lowering_wall_s` before and after, per width, on quick-scale.
3. Matrix {off, SWAP term only (`wait_realizations = false`), SWAP + realization terms} × {Greedy, PRISM}, at `wait_scale = 1`: gcm_h6 (breadth, 3 seeds) first, then core quick. The SWAP-only row separates the generic router change from the realization-specific one. Then `wait_scale` 0.5 and 2 as sensitivity.
4. Adopt only if Evan approves. It is a method change for the rebuttal.
