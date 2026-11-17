# gcm_h6: what it is, why PRISM's hex duration is worse, and whether a rule can toss it

Rows: `artifacts/paper/raw/breadth.jsonl` (47b2aa0, 2026-10-07), 20 seeds x 3 graphs x 2 arms. Scripts and raw outputs are in this directory (`structure.py`, `seeds.py`, `rails.py`, `recompile.py`, `compare_resched.py`, `headline.py`). The worktree was not written to.

## 1. What the circuit is

**Source.** QASMBench medium-scale `gcm`, commit 357b942, copied to `artifacts/paper/manifests/qasmbench/gcm_h6.qasm` and frozen to `artifacts/paper/manifests/circuits/gcm_h6_n13.qpy`. QASMBench's table lists it as "Generator coordinate method", algorithm class Quantum Chemistry, 13 qubits, 3148 gates, 762 CNOT, reference arXiv:2212.09205 (a GCM calculation for an H6 chain; the `_h6` suffix is the molecule). The file's only comment is `// Term: YYIIIIIIIIXX`, a 12-qubit Pauli string.

**Counts.**

| stage | ops | two-qubit | depth | active gates |
|---|---|---|---|---|
| raw QASM | rz 1522, sx 858, cx 762, x 6, measure 1 (3149) | 762 cx | 2447 | - |
| `transpile(basis=["cx","u"])` (the README's structural table) | u 2386, cx 762 | 762 | 2447 | - |
| after `DualRail.logical_pm()` (the logical stage every arm runs) | rz 1548, rx 836, crz 762, measure 1 (3147) | 762 crz | 2048 | 1599 (crz + rx + measure; rz is free) |
| lowered program body, Greedy, mean over 60 runs | crz 762, rswap 836, swap = routing SWAPs, measure 2 | 762 crz | 936-1005 physical | 1907 (1,599 + SWAPs) |

The two-qubit depth of the logical circuit is 762, equal to the CX count: **every two-qubit gate is on one serial chain.** The interaction graph has 22 edges; qubit 0 has all 12 others as partners and is in 642 of the 762 CX (the other 120 are between system qubits). One classical bit, and only q[0] is measured. So this is a Hadamard-test style circuit: an ancilla (q0) controls Pauli-string rotations on 12 system qubits, 86 `rz` centres sit between two identical CX, with 4 distinct rotation angles, and the CX come as 698 singletons and 32 pairs rather than long ladders. It is not a UCC ansatz of repeated layers; it is one long controlled-evolution with an ancilla hub.

**Why its active-gate count is so large.** It has 762 two-qubit gates where the next-largest suite circuit (sat) has 146; the dual-rail lowering keeps that ratio (one crz per CX, one rswap per rx). Mean Greedy active gates over 60 runs: gcm_h6 1,907; next qram 436, sat 394, qf21 343 (suite median 136). Because the CX are serial on the hub, 762 x 500 ns = 381 us is the critical path if nothing overlaps; the measured durations are 300-460 us, so gcm_h6 is also 4x the duration of the next circuit (sat, 86 us). The duration term dominates its route score (section 2).

**Does the pre-registered rule exclude it?** No. Checking each clause of `research/rebuttal/suite/README.md`: (1) family `gcm` is not in the 16 MQT workloads; (2) it needs routing (hub degree 12 > 6 adjacent pair sites on the grid, 4 on hex, 3 on heavy-hex); (3) no reset or classical control, one terminal measurement; (4) 762 two-qubit gates is 13x below the 10^4 threshold; (5) not a duplicate; (6) the only `gcm` instance. The README's own candidate table lists it with CX 762 and max partners up to 24, so its size was known when the rule was applied. Option (a) in section 3 is false as the rule is written.

## 2. The duration anomaly

### 2.1 What J is for this circuit

Route selection keeps, among 43 layout starts, the start with the lowest J = -log F_cond (`metrics.device_success`, scored in `prism_routing.score` with `objective="error"`):

J = 13 * duration_us * r + 762 * c1 + (rswap + swap) * c2, with r = 2.306e-4 per us per qubit, c1 = -log(1 - SWS_ERROR) = 5.034e-4, c2 = -log(1 - RSWAP_ERROR) = 9.900e-5.

The three terms for the selected routes (cell means over 20 seeds):

| graph | arm | J | exposure (duration) | SWS (762 crz, fixed) | beamsplitter (836 rswap + SWAPs) | SWAPs | duration us | depth |
|---|---|---|---|---|---|---|---|---|
| grid | greedy | 1.5316 | 1.0488 (68%) | 0.3836 | 0.0992 | 165.9 | 349.9 | 936 |
| grid | prism | 1.5314 | 1.0592 (69%) | 0.3836 | 0.0886 | 58.6 | 353.4 | 920 |
| hex | greedy | 1.5755 | 1.0763 (68%) | 0.3836 | 0.1156 | 331.8 | 359.1 | 1005 |
| hex | prism | 1.6375 | 1.1539 (70%) | 0.3836 | 0.1000 | 174.4 | 384.9 | 1065 |
| heavy-hex | greedy | 1.5536 | 1.0454 (67%) | 0.3836 | 0.1246 | 422.1 | 348.8 | 977 |
| heavy-hex | prism | 1.5220 | 1.0261 (67%) | 0.3836 | 0.1123 | 298.1 | 342.3 | 934 |

J reconstructs each row's final duration from the recorded start score to within 2e-16, so the score is computed on the circuit whose duration is reported. The SWS term is a constant. The beamsplitter term moves by 9.9e-5 per SWAP; the exposure term moves by 3.0e-3 per microsecond. **One SWAP is worth 0.033 us of critical path.** The SWAP range across a seed's 43 starts (about 150 SWAPs) is worth 0.015 in J; the duration range (about 100 us) is worth 0.30. So for gcm_h6, selection by J is selection by duration: in every one of the 120 runs the selected start is within 1 us of the start with the shortest duration. The duration weight is not small; it is the whole decision. The anomaly is not a property of J's weights in the sense of duration being under-weighted. The reverse: J ignores PRISM's SWAP advantage because, at 13 qubits, 100 SWAPs are worth 3 us.

### 2.2 Hex, seed by seed

Selected route per seed (J, SWAPs, duration us, depth) and the J gap from the selected start to the next-best start. A gap of 0.18 is 60 us. The last two columns are counterfactual selections from the same 43 starts: the start with the fewest SWAPs, and the start's population median.

| seed | Greedy J / SWAPs / dur / depth | PRISM J / SWAPs / dur / depth | Greedy gap | PRISM gap | fewest-SWAP start, G: SWAPs/dur | fewest-SWAP start, P: SWAPs/dur | median start dur G / P |
|---|---|---|---|---|---|---|---|
| 0 | 1.692 / 248 / 400.6 / 1140 | 1.584 / 179 / 367.0 / 995 | 0.008 | 0.080 | 206/404.6 | 147/406.4 | 458 / 426 |
| 100 | 1.773 / 236 / 428.0 / 1206 | 1.657 / 206 / 390.5 / 1071 | 0.003 | 0.018 | 233/464.4 | 140/406.6 | 464 / 429 |
| 200 | 1.413 / 328 / 305.0* / 812 | 1.669 / 225 / 393.6 / 1099 | 0.265 | 0.033 | 229/436.3 | 142/407.3 | 452 / 426 |
| 300 | 1.495 / 349 / 331.6* / 945 | 1.679 / 185 / 398.4 / 1105 | 0.187 | 0.008 | 213/398.6 | 145/410.0 | 463 / 430 |
| 400 | 1.470 / 319 / 324.2* / 908 | 1.612 / 168 / 376.5 / 1069 | 0.310 | 0.039 | 223/434.7 | 122/392.0 | 462 / 420 |
| 500 | 1.480 / 383 / 325.6* / 916 | 1.633 / 210 / 382.3 / 1050 | 0.227 | 0.000 | 230/421.5 | 108/408.5 | 454 / 431 |
| 600 | 1.479 / 336 / 326.6* / 923 | 1.552 / 183 / 356.2 / 988 | 0.196 | 0.039 | 253/394.6 | 142/424.2 | 460 / 424 |
| 700 | 1.427 / 320 / 310.0* / 837 | 1.680 / 172 / 399.2 / 1103 | 0.274 | 0.003 | 243/435.1 | 157/406.6 | 442 / 420 |
| 800 | 1.462 / 346 / 320.6* / 891 | 1.634 / 176 / 383.8 / 1046 | 0.230 | 0.007 | 206/425.9 | 161/415.6 | 446 / 422 |
| 900 | 1.466 / 402 / 320.2* / 889 | 1.669 / 126 / 397.1 / 1065 | 0.225 | 0.002 | 219/401.3 | 126/397.1 | 454 / 425 |
| 1000 | 1.633 / 397 / 376.0 / 1019 | 1.651 / 112 / 391.5 / 1066 | 0.095 | 0.000 | 239/427.5 | 112/391.5 | 463 / 424 |
| 1100 | 1.729 / 297 / 411.3 / 1168 | 1.634 / 157 / 384.5 / 1066 | 0.038 | 0.035 | 234/443.5 | 154/404.3 | 453 / 422 |
| 1200 | 1.451 / 320 / 317.8* / 880 | 1.663 / 176 / 393.5 / 1075 | 0.021 | 0.011 | 252/414.0 | 156/431.2 | 459 / 425 |
| 1300 | 1.689 / 330 / 397.1 / 1069 | 1.603 / 127 / 375.0 / 1062 | 0.069 | 0.055 | 228/444.7 | 127/375.0 | 453 / 427 |
| 1400 | 1.440 / 411 / 311.3* / 847 | 1.618 / 156 / 379.0 / 1056 | 0.280 | 0.015 | 228/429.5 | 156/379.0 | 456 / 427 |
| 1500 | 1.750 / 270 / 419.2 / 1200 | 1.681 / 207 / 398.4 / 1085 | 0.004 | 0.020 | 258/444.4 | 144/407.6 | 455 / 420 |
| 1600 | 1.472 / 392 / 322.6* / 904 | 1.658 / 184 / 391.4 / 1113 | 0.256 | 0.008 | 236/440.9 | 157/394.9 | 446 / 422 |
| 1700 | 1.703 / 280 / 403.4 / 1177 | 1.607 / 180 / 374.6 / 1076 | 0.022 | 0.024 | 234/446.9 | 148/396.5 | 455 / 425 |
| 1800 | 1.744 / 369 / 414.1 / 1215 | 1.649 / 165 / 389.2 / 1086 | 0.005 | 0.006 | 221/420.6 | 140/412.9 | 446 / 424 |
| 1900 | 1.744 / 302 / 416.1 / 1145 | 1.616 / 195 / 377.0 / 1025 | 0.005 | 0.073 | 229/442.8 | 149/408.5 | 457 / 425 |

`*` marks Greedy's outlier routes (duration below 340 us): 11 seeds (200-900, 1200, 1400, 1600). In those 11 seeds Greedy's selected start uses 319-411 SWAPs, more than its own median start in 9 of them (SWAP rank 18-43 of 43), and runs 305-332 us; its next-best start runs 395-430 us. In the other 9 seeds Greedy's selected route runs 376-428 us and PRISM's is shorter in 8 of them. PRISM's selected routes run 356-399 us in every seed; its largest best-to-second gap is 0.080.

Cell-level consequences (hex):

| selection rule applied to the same 43 starts per seed | PRISM duration vs Greedy | PRISM SWAPs vs Greedy |
|---|---|---|
| actual: lowest J (= shortest duration) | -7.2% [-13.7, -1.0] (PRISM longer) | 47.4% fewer |
| fewest SWAPs | +5.8% (PRISM shorter) | 38.6% fewer |
| population median start | +6.6% (PRISM shorter) | 36.7% fewer |

PRISM's starts are the better population: on hex its pooled 860 start durations are lower than Greedy's at the 5th, 25th, 50th, 75th and 95th percentiles (394, 413, 425, 436, 454 us against 414, 438, 455, 472, 496 us). But min-over-43 selection rewards the lower tail, and Greedy has one: 12 of its 860 hex starts are under 340 us, PRISM has 0 (under 360 us: 12 against 1). Greedy's selected J is lower than PRISM's in 12 of 20 hex seeds, so PRISM also loses the cell on the objective J itself, by -3.9% [-8.1, 0.3].

### 2.3 Where the outlier routes come from: not the rescheduler

I recompiled hex seeds 200 (Greedy outlier, gap 0.265) and 0 (no outlier), both arms, with `reschedule = false` and everything else as in `configs/paper/breadth.toml` (`recompile.py`, 3 workers; `compare_resched.md`):


| seed | arm | rescheduling | selected: dur µs / SWAPs / depth | min start dur | median start dur | #starts < 340 µs | gap J best→2nd | selected start index |
|---|---|---|---|---|---|---|---|---|
| 200 | greedy | on (rows) | 305.0 / 328 / 812 | 305.0 | 451.6 | 1 | 0.265 | 3 |
| 200 | greedy | off (recompile) | 333.0 / 328 / 954 | 333.0 | 473.3 | 1 | 0.249 | 3 |
| 200 | prism | on (rows) | 393.6 / 225 / 1099 | 393.6 | 426.1 | 0 | 0.033 | 31 |
| 200 | prism | off (recompile) | 426.6 / 142 / 1226 | 426.6 | 455.6 | 0 | 0.013 | 4 |
| 0 | greedy | on (rows) | 400.6 / 248 / 1140 | 400.6 | 458.3 | 0 | 0.008 | 22 |
| 0 | greedy | off (recompile) | 417.6 / 206 / 1220 | 417.6 | 481.6 | 0 | 0.027 | 36 |
| 0 | prism | on (rows) | 367.0 / 179 / 995 | 367.0 | 426.5 | 0 | 0.080 | 20 |
| 0 | prism | off (recompile) | 405.3 / 179 / 1157 | 405.3 | 448.3 | 0 | 0.037 | 20 |

- seed 200 greedy: start-by-start SWAP counts identical in 43/43 starts (the route is the same; only the emitted order differs); rescheduling shortens a start by 10.5–42.2 µs (mean 25.7); the start selected with rescheduling on has pre-rescheduling duration 333.0 µs (rank 1/43 before rescheduling).
- seed 200 prism: start-by-start SWAP counts identical in 43/43 starts (the route is the same; only the emitted order differs); rescheduling shortens a start by 10.9–53.8 µs (mean 27.1); the start selected with rescheduling on has pre-rescheduling duration 428.1 µs (rank 2/43 before rescheduling).
- seed 0 greedy: start-by-start SWAP counts identical in 43/43 starts (the route is the same; only the emitted order differs); rescheduling shortens a start by 6.0–43.8 µs (mean 24.1); the start selected with rescheduling on has pre-rescheduling duration 425.3 µs (rank 2/43 before rescheduling).
- seed 0 prism: start-by-start SWAP counts identical in 43/43 starts (the route is the same; only the emitted order differs); rescheduling shortens a start by 8.5–38.8 µs (mean 24.7); the start selected with rescheduling on has pre-rescheduling duration 405.3 µs (rank 1/43 before rescheduling).

Routing is unchanged: all 43 starts of all four runs have the same SWAP count with rescheduling off, so the rescheduler only reorders. It shortens every start by 6-54 us (mean 24-27 us) and does so equally for both arms. Greedy's outlier start (seed 200, start 3) is already the shortest start before rescheduling (333 us against 395+ for the others), with the same 328 SWAPs. The outlier is in the route, not in the reordering. (This agrees with the 2026-10-06 heavy-hex check in `gcm_h6.md`.) Rescheduling changes which start wins in two of the four runs, as expected when it shortens starts by different amounts, which is why the rows must keep rescheduling in the selection loop.

### 2.4 Where the outlier routes come from: the realization pattern on the hub

Greedy binds one realization per gate at route entry by distance under the entry layout (`_greedy_commit_ctx`), so for a given start each (hub, partner) pair always uses the same rail of the hub. PRISM re-chooses per gate against the current layout. From `realization_choices` (762 per run) and the logical crz list, the hub's rail sequence per run (`rails.md`):


| graph | arm | mean duration us | hub-rail switches per route | longest same-rail run | corr(duration, switches) over 20 seeds | corr(duration, SWAPs) |
|---|---|---|---|---|---|---|
| grid | greedy | 349.9 | 167 | 79 | +0.80 | -0.69 |
| grid | prism | 353.4 | 188 | 60 | +0.30 | +0.35 |
| hex | greedy | 359.1 | 147 | 90 | +0.68 | -0.59 |
| hex | prism | 384.9 | 207 | 57 | -0.20 | +0.03 |
| heavy-hex | greedy | 348.8 | 129 | 104 | +0.48 | -0.74 |
| heavy-hex | prism | 342.3 | 138 | 95 | +0.77 | -0.74 |

Pooled over the 120 runs, duration correlates with hub-rail switches at +0.60 and with SWAP count at -0.29. SWAP count does not predict duration on this circuit; the realization pattern does. On the grid and hex, PRISM switches the hub's rail 190-210 times per route against Greedy's 150-170, and its longest same-rail run is 57-60 gates against Greedy's 79-90. Diagonal gates (crz, rz) on a shared rail commute and the rescheduler overlaps them; a rail switch inserts a non-commuting boundary (the SWAP or rswap that makes the other rail adjacent). PRISM's per-gate choice buys SWAPs and pays critical path; Greedy's fixed per-pair choice occasionally (one start in 43, half the seeds) gives a layout where the fixed assignment runs the chain with few boundaries. Neither router aims at this: SABRE scores SWAP distance, the time-aware variants in `research/rebuttal/time_aware/README.md` were tested and vetoed, and the lexicographic one left gcm_h6's PRISM duration about 6% worse. So the answer to "J's weights, the rescheduler, or PRISM's realization choice" is the third, with the first as the amplifier: PRISM's distance-driven realizations make a longer critical path on the serial hub chain, and J (duration-dominated at 13 qubits) then picks the arm with the one lucky short start rather than the arm with the better population. I did not isolate which feature of the lucky layouts produces the short chain; that would need a per-start critical-path trace, not the rows.

### 2.5 Grid and heavy-hex

| graph | Greedy seeds with best-to-2nd gap >= 0.18 (hex has an 11th outlier, seed 1200, whose 2nd-best start is also short) | PRISM seeds with gap >= 0.18 | starts < 340 us, G / P (of 860) | duration: PRISM vs Greedy | fewest-SWAP selection would give | SWAPs: PRISM fewer by |
|---|---|---|---|---|---|---|
| grid | 5 | 0 | 9 / 1 | -1.0% [-6.2, 3.8] | +5.9% | 64.7% |
| hex | 10 | 0 | 12 / 0 | -7.2% [-13.7, -1.0] | +5.8% | 47.4% |
| heavy-hex | 6 | 10 | 27 / 17 | +1.8% [-4.8, 8.0] | +4.5% | 29.4% |

Same mechanism, different luck. On the grid Greedy has 5 outlier seeds (287-299 us) and PRISM none, but PRISM's non-outlier routes (339-363 us) are shorter than Greedy's (360-388 us), so the cell is a tie. On heavy-hex PRISM's own starts have the tail too (17 starts under 340 us, 10 outlier seeds), and the cell is a tie the other way. Hex is where PRISM has no tail at all (0 starts under 340 us, 1 under 360) while Greedy has 12.

## 3. Can a rule toss it?

Equal-weight reductions (mean of per-workload reductions, paired over 20 seeds), grid / hex / heavy-hex, in percent. `headline.py` reuses `export_suite.load`, `values` and `equal_weight_interval`, so "keep_25" reproduces `summary.json` exactly.

| option | removed | SWAPs | depth | duration |
|---|---|---|---|---|
| (c) keep all 25 | none | 30.4 / 23.2 / 17.0 | 7.8 / 8.5 / 8.0 | 6.9 / 7.3 / 6.9 |
| drop gcm_h6 only (any size rule with k in 3.3-13.9) | gcm_h6 | 29.0 / 22.2 / 16.5 | 8.1 / 9.1 / 8.1 | 7.2 / 7.9 / 7.1 |
| (b) active gates > 3x suite median | gcm_h6, qram | 29.1 / 22.1 / 16.3 | 8.0 / 9.1 / 8.0 | 7.1 / 7.9 / 7.0 |
| (b) active gates > 2x suite median | sat, gcm_h6, qf21, qram, knn | 29.5 / 22.6 / 15.9 | 7.7 / 8.9 / 7.6 | 7.0 / 7.7 / 6.9 |
| drop all QASMBench (back to 16 MQT) | sat, seca, gcm_h6, multiply, qf21, qec9xz, bv, qram, knn | 29.8 / 21.7 / 15.6 | 7.6 / 8.9 / 7.3 | 6.8 / 7.6 / 6.5 |

With 95% intervals, keep against drop gcm_h6:

| metric | graph | keep 25 | drop gcm_h6 |
|---|---|---|---|
| SWAPs | grid | 30.4 [24.5, 32.9] (sum 34.9) | 29.0 [22.8, 31.6] (sum 28.9) |
| SWAPs | hex | 23.2 [20.1, 25.2] (sum 29.5) | 22.2 [18.9, 24.3] (sum 24.7) |
| SWAPs | heavy-hex | 17.0 [15.9, 18.0] (sum 20.9) | 16.5 [15.3, 17.6] (sum 18.9) |
| depth | grid | 7.8 [7.0, 8.6] (sum 5.8) | 8.1 [7.3, 8.8] (sum 8.4) |
| depth | hex | 8.5 [7.6, 9.3] (sum 3.7) | 9.1 [8.4, 9.8] (sum 9.8) |
| depth | heavy-hex | 8.0 [7.3, 8.6] (sum 7.4) | 8.1 [7.6, 8.6] (sum 9.1) |
| duration | grid | 6.9 [6.2, 7.4] (sum 3.6) | 7.2 [6.6, 7.8] (sum 7.0) |
| duration | hex | 7.3 [6.7, 7.8] (sum 1.9) | 7.9 [7.4, 8.4] (sum 8.2) |
| duration | heavy-hex | 6.9 [6.2, 7.5] (sum 5.4) | 7.1 [6.5, 7.7] (sum 7.7) |

Size ranking (mean Greedy active gates over 60 runs, suite median 136): gcm_h6 1,907 (14.0x), qram 436 (3.2x), sat 394 (2.9x), qf21 343 (2.5x), knn 278 (2.0x), vqe_two_local 272, multiplier 272, rg_qft_multiplier 267, then the rest at or below 1.4x. By two-qubit gates: gcm_h6 762, sat 146, qram 116, qf21 103.

**(a) "It violates the pre-registered rule."** False (section 1). Saying so would be a misstatement a reviewer with the QASMBench table can check in one line: 762 CX.

**(b) A uniform size rule.** Any threshold between 3.3x and 13.9x the suite median removes exactly gcm_h6 and nothing else; 3x also removes qram, 2x removes five QASMBench circuits. The rule is clean in effect but not in origin: the suite README states "Nothing is dropped, re-seeded or re-run because of its result", the 10^4 threshold was chosen and applied before the compiles, and gcm_h6's size was in the candidate table. A size clause added now is a post-hoc exclusion of the one cell PRISM loses, and the cell it removes is also the cell with PRISM's largest SWAP reductions in the suite (65 / 47 / 29%). Removing it **lowers** the SWAP headline by 1.4 / 1.0 / 0.5 points and raises depth by 0.3 / 0.6 / 0.1 and duration by 0.3 / 0.6 / 0.2 points. The summed reductions move more (duration sum 3.6 / 1.9 / 5.4 -> 7.0 / 8.2 / 7.7) because gcm_h6 is 38-42% of the suite's summed depth, which is exactly why the headline is equal-weight.

**(c) Keep it and state it.** The cell counts become: duration 72 of 75 cells lower, 67 with interval above 0, 1 below 0 (gcm_h6/hex); the other two "higher" duration cells are gcm_h6/grid and dj/grid, both within noise. The largest per-run losses in all three metrics are gcm_h6 runs (SWAPs +70 at heavy-hex seed 1600, depth +287 and duration +89 us at hex seeds 200 and 700), all of them Greedy-outlier seeds.

## 4. Recommendation

Keep gcm_h6; it does not fall under any clause of the pre-registered rule, dropping it would cost 0.5-1.4 points of the SWAP headline to gain 0.2-0.6 points of duration, and a size clause written after seeing the one losing cell is the cherry-pick a reviewer would look for. Report the hex duration loss as what it is: on a Hadamard-test circuit whose 762 two-qubit gates form one serial chain on an ancilla, duration is 70% of the route score, SWAP count does not predict duration (correlation -0.29), and route selection keeps the shortest of 43 schedules, so Greedy wins the cell with one lucky fixed-realization start in 11 of 20 seeds while PRISM's starts, shorter at every percentile, have no such tail; PRISM still cuts SWAPs by 47% there and the rescheduler is not the cause (routes identical with it off). The one-sentence version for section 5.2: "On gcm_h6, whose two-qubit gates are serial on one ancilla, PRISM removes 29-65% of the SWAPs but its hexagonal-lattice schedules are 7.2% [1.0, 13.7] longer, because the route score is dominated by duration and Greedy's fixed realizations produce, in half the seeds, one start with a shorter critical path than any of PRISM's."
