# gcm_h6: PRISM's schedules are longer on the hexagonal lattice (final rows, 2026-10-07)

## Finding

gcm_h6 has the most gates in the suite. PRISM uses fewer routing SWAPs than Greedy on all three device graphs, but on the hexagonal lattice its schedules are longer, by 7.2% [1.0, 13.7]. This is the only cell in the 75-cell suite whose duration interval lies below zero. On the grid and heavy-hex, the duration reductions are −1.0% [−6.2, 3.8] and 1.8% [−4.8, 8.0], within noise. A negative reduction means PRISM is longer.

Per-run values over 20 seeds, Greedy and PRISM:

| graph | mean SWAPs | duration range (µs) | seeds where one start scores ≥ 0.18 below the next |
|---|---|---|---|
| grid | 166 / 59 | 287–388 / 339–363 | 5 / 0 |
| hex | 332 / 174 | 305–428 / 356–399 | 10 / 0 |
| heavy-hex | 422 / 298 | 307–420 / 301–412 | 6 / 10 |

## Mechanism

Each run routes from 43 layout starts and keeps the start with the lowest −log F_cond. That score is computed before O3. Over the kept routes, it has a correlation of 0.997 with the final duration. `search_trace.final_scores` records the score and the active gate count of every start. The lowering fixes the CR_z and RSWAP counts, so the active gate count changes only with the SWAP count.

1. On the hexagonal lattice, PRISM's starts are better than Greedy's as a population. PRISM's median start scores lower in 20 of 20 seeds, its 10th percentile in 19, and its second-best start in 17.
2. In 10 of Greedy's 20 seeds, a single start scores 0.19 to 0.31 below Greedy's next-best start. These starts have different indices in each seed, so they are random starts and not one standard layout. Selection keeps the outlier start, and in those 10 seeds Greedy's schedule takes 305 to 332 µs. PRISM's schedule takes 356 to 399 µs in every seed, and its largest gap between the best and next-best start in any seed is 0.08.
3. In all 10 seeds, Greedy's outlier start uses more SWAPs than its next-best start, by 20 to 183 active gates, but its schedule is shorter. SABRE scores candidate SWAPs by distance, so neither compiler seeks such a route. Greedy's fixed realizations produce one by chance in half of the seeds.
4. Greedy's kept route has the lower −log F_cond in 12 of the 20 seeds. So on this cell, PRISM also loses on the objective that route selection minimizes.
5. The same outlier starts explain the other two graphs. On heavy-hex, PRISM has an outlier start in 10 seeds and Greedy in 6, and the duration difference is a tie. On the grid, Greedy has an outlier in 5 seeds and PRISM in none, and Greedy's best schedules (287 to 299 µs) are shorter than any of PRISM's. PRISM's narrow range on the grid keeps its mean within noise.

## Earlier version

The 2026-10-06 version of this note measured heavy-hex on the 3-seed quick rows. There, PRISM lost duration on heavy-hex, and a recompile of heavy-hex seed 100 with rescheduling off reproduced Greedy's outlier route, which showed that rescheduling did not cause it. That recompile was not repeated on the final rows. On the final rows, heavy-hex is a tie and the loss is on the hexagonal lattice.

Rows: `artifacts/paper/raw/breadth.jsonl` (47b2aa0), cells from `artifacts/paper/paper_export/suite/per_cell.csv`.
