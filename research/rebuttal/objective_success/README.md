# Route selection by overall success (pre-registered 2026-10-07, prism-66, before any run)

**Hypothesis.** Route selection minimizes −log F_cond, which leaves out photon loss ("more shots recover it", `prism_routing.score`). §5.4 shows loss dominates the routing cost on the measured device. So selecting the route among the 43 starts by overall success, −log(P_keep · F_cond), with P_keep from the recalibrated Eq. 1 (`metrics.pair_exposure`, T1 = 356.5 µs, the Mehta erasures), should lower both compilers' shot overhead.

**Change.** `run.py` replaces only the `"error"` branch of `prism_routing.score` with −log(P_keep · F_cond). The tiebreaks are unchanged. Both arms get it. Routing, the starts and the seeds are unchanged. Rows keep `objective = "error"` in their fields; every row in `data/` uses the patched objective.

**Probe.** `scale16.toml` at quick scope: n = 16, seed 0, grid and hex_lattice, greedy and prism, 16 workloads. The baseline is the same seed's rows in `artifacts/paper/raw/scale.jsonl`, which have identical starts.

**Reading, fixed now.**
- **Adopt** for the main results only if neither compiler's suite shot overhead (mehta Eq. 1, the export_device aggregation) gets worse, and neither compiler's SWAPs or duration rise by more than 5%. PRISM's margin over Greedy does not decide adoption.
- **Report** PRISM's margin over Greedy under both objectives either way.
- If it is adopted, the full scale run (5 seeds, all widths) and core re-run under it before any paper number uses it.

## Result (2026-10-07, 64 rows, `compare.py`)

Null. Selecting by −log(P_keep·F) picks essentially the same routes as −log F_cond. New/old ratios for every arm, metric and graph lie within 0.997–1.018: SWAPs, duration, 1/P_keep and P_keep·F. PRISM/Greedy 1/P_keep is 0.630 → 0.632 on the grid and 0.590 → 0.589 on hex. Both objectives are dominated by the schedule's duration, so they rank the 43 starts alike. Under the pre-registered rule it is not adopted, since nothing improves. The main results keep −log F_cond.
