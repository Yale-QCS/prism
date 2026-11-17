---
name: Benchmark methodology — zero-baseline drops & SABRE seeding
description: User's stance on two recurring benchmarking judgment calls in marabbecca: dropping baseline-zero pairs from percent-change aggregates, and outer SABRE seeding.
type: feedback
originSessionId: 3d8c1bda-1188-4f3d-925f-d7a5fd2ea963
---
When summarizing benchmark results vs a baseline routing strategy:

**Triviality is a property of the (circuit, topology) pair, defined once on swaps, and applied to ALL metrics.** A pair is trivial iff `baseline.swaps == 0`. Trivial pairs are excluded from every aggregate (swaps geomean, depth geomean, win/tie/loss, Wilcoxon, percent change, performance profile), not just from the swap-specific aggregate.

**Why:** if the baseline needed 0 SWAPs, no routing actually happened on that pair. Depth on a 0-SWAP-routed circuit is just the input depth + a free layout — every strategy gets the same number, and "median depth change" averages those zeros into the headline. Filtering only swaps but not depth is the bug: it makes the depth aggregate look like it's measuring routing quality when it's actually measuring "did the problem need routing at all."

**How to apply:** filter `(c, t)` pairs upfront where `baseline.swaps == 0` and pass the filtered list into every reporting function. Report a single trivial count in the coverage block, not one per metric. Don't silently filter — say "N trivial pairs (baseline swaps = 0) excluded from all reporting."

---

**Outer-seed multi-trial runs are not needed for SABRE-based comparisons.** Qiskit's SABRE passes have an internal `trials` parameter that runs multiple inner trials and picks the best — so a single outer seed per (circuit, topology, strategy) cell is acceptable and we don't need to wrap `run_suite` in a multi-seed loop.

**Why:** the variance from SABRE's randomization is already absorbed inside the pass.

**How to apply:** don't push for multi-seed harness changes when proposing benchmark improvements. Focus on the summary statistics, not on running more trials.

---

**Zero-swap circuits are *labeled* "trivial," not deleted.** Circuits like `wstate`, `vqe_su2`, `bmw_quark_cardinality` that route 0 swaps under every strategy on the dominant test topology belong in `CIRCUIT_CLASS` with class label `"trivial"`. The label is the mechanism downstream analyses use to filter or break out these circuits — by class, not by name. Deleting them from `CIRCUIT_CLASS` breaks lookups (old data, per-class summaries, etc.).

**The two concerns are separate:**
1. `CIRCUIT_CLASS` (dict in `utils/benchmarks.py`) = name → structural class lookup. Includes every circuit we know about, including trivial ones. Don't delete entries.
2. The "active sweep list" — whatever set of (circuit, size) tuples is passed to `run_suite` in the notebook — *can* drop trivial ones. That's a separate decision and is usually expressed as `[name for name in CIRCUIT_CLASS if CIRCUIT_CLASS[name] != "trivial"]` or similar.

**Triviality is defined on swaps, not depth.** Depth deltas between strategies on a 0-swap circuit reflect only realization-commit choice (which candidate a free layout lands on), not routing skill — so triviality only matters for routing-comparison plots. State the reason as "0 swaps under every strategy," never as "0 depth" or "trivial depth."

**Why:** the user has corrected me on this multiple times. First I included 0-swap circuits in routing comparisons (wrong); then I tried to fix by deleting them from `CIRCUIT_CLASS` entirely (also wrong — the class label is the filter). The right move is: keep them in the classification dict labeled "trivial," and let the notebook's active sweep decide whether to include them.
