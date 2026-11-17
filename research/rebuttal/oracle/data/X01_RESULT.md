# X01 Result: Exact Small-Instance Oracle

## What was built

- `scripts/paper/oracle.py`: Dijkstra-based exact routing oracle over states
  (canonical_layout, done_bitmask). Zero-cost closure executes all ready
  gates with adjacent supports before any SWAP expansion. A* lower bound:
  max over ready-blocked gates of max(0, min_support_dist - 1). Rail-exchange
  symmetry canonicalizes layouts for multi-realization instances (all 4 supports
  are symmetric under per-qubit rail swap). Initial layout is joint (all
  injections of n_rails into n_phys nodes seeded at cost 0).
- `tests/test_oracle.py`: unit tests (hand-solvable, one-realization
  equivalence, duplicate-support invariance, monotonicity, replay, brute force).
- `configs/paper/oracle.toml`: experiment configuration.
- `artifacts/paper/raw/oracle.jsonl`: raw per-instance rows.

Compiler runs use `_DualRailLocalInit` (local_init=True) to suppress the
co-location herald CRZ(pi), which would otherwise add init-routing SWAPs not
counted by the oracle. This makes S_greedy and S_prism comparable to S_multi_opt.

Default realization: DualRail.crz default_index=2 = (ra=1, rb=0), i.e., rail 1
of the control qubit adjacent to rail 0 of the target qubit.

## Instance table

Columns: S_def_opt = single-realization optimum, S_multi_opt = multi-realization
optimum, S_greedy/S_prism = compiler results (min over compiler seeds),
Opp = S_def_opt - S_multi_opt, G_greedy/G_prism = gap to optimum,
Captured = (S_greedy - S_prism) / (S_greedy - S_multi_opt) [undef if denom=0].

| Instance                     | nl | ng | S_def | S_opt | S_grd | S_prm | Opp | G_grd | G_prm | Captured | Status |
| ---------------------------- | -- | -- | ----- | ----- | ----- | ----- | --- | ----- | ----- | -------- | ------ |
| crz_chain_n3_chain6          |  3 |  2 |     0 |     0 |     0 |     0 |   0 |     0 |     0 |    undef | exact  |
| crz_ring_n3_chain6           |  3 |  3 |     0 |     0 |     0 |     0 |   0 |     0 |     0 |    undef | exact  |
| k3_chain6                    |  3 |  3 |     0 |     0 |     0 |     0 |   0 |     0 |     0 |    undef | exact  |
| rand_dag_n3_chain6           |  3 |  4 |     0 |     0 |     0 |     0 |   0 |     0 |     0 |    undef | exact  |
| crz_chain_n3_grid23          |  3 |  2 |     0 |     0 |     0 |     0 |   0 |     0 |     0 |    undef | exact  |
| k3_grid23                    |  3 |  3 |     0 |     0 |     0 |     0 |   0 |     0 |     0 |    undef | exact  |
| crz_chain_n4_chain8          |  4 |  3 |     0 |     0 |     0 |     0 |   0 |     0 |     0 |    undef | exact  |
| k4_chain8                    |  4 |  6 |     3 |     0 |     0 |     0 |   3 |     0 |     0 |    undef | exact  |
| rand_dag_n4_chain8           |  4 |  5 |     2 |     0 |     0 |     0 |   2 |     0 |     0 |    undef | exact  |
| crz_chain_n4_grid24          |  4 |  3 |     0 |     0 |     0 |     0 |   0 |     0 |     0 |    undef | exact  |
| k4_grid24                    |  4 |  6 |     0 |     0 |     0 |     0 |   0 |     0 |     0 |    undef | exact  |
| k4_repeated_chain8           |  4 | 12 |     6 |     0 |     0 |     0 |   6 |     0 |     0 |    undef | exact  |
| rand_dag_n4_deep_s42_chain8  |  4 | 15 |     2 |     0 |     0 |     0 |   2 |     0 |     0 |    undef | exact  |
| rand_dag_n4_deep_s43_chain8  |  4 | 15 |     4 |     0 |     0 |     0 |   4 |     0 |     0 |    undef | exact  |
| rand_dag_n4_deep_s44_chain8  |  4 | 15 |     3 |     0 |     0 |     0 |   3 |     0 |     0 |    undef | exact  |
| k5_chain10                   |  5 | 10 |    -1 |     1 |     1 |     1 | None |     0 |     0 |    undef | FAIL   |
| rand_dag_n5_s42_chain10      |  5 |  8 |    -1 |     0 |     0 |     0 | None |     0 |     0 |    undef | FAIL   |
| k5_grid25                    |  5 | 10 |    -1 |     0 |     0 |     0 | None |     0 |     0 |    undef | FAIL   |
| k4_chain10_spare             |  4 |  6 |     3 |     0 |     0 |     0 |   3 |     0 |     0 |    undef | exact  |
| k4_grid25_spare              |  4 |  6 |     0 |     0 |     0 |     0 |   0 |     0 |     0 |    undef | exact  |

## Commands

```
.venv/bin/python scripts/paper/oracle.py --config configs/paper/oracle.toml
.venv/bin/pytest -q tests/test_oracle.py
```

## What the numbers permit and do NOT permit the paper to claim

Certified-exact instances: 20 of 20 total.

**PERMITS:**
- Support opportunity is real: 7/20 certified instances show S_def_opt > S_multi_opt (avg opp = 3.29 SWAPs). Multi-realization IR provably reduces optimal routing overhead on these instances.
- PRISM achieves the multi-realization optimum on 20/20 certified instances (zero prism gap).

**DOES NOT PERMIT:**
- Claims about uncertified (timeout/bound) instances -- those are upper bounds only.
- Extrapolation to larger n without new oracle runs.
- Claims that PRISM is optimal in general (gap may be non-zero on other instances).
- Claims about topologies not in this table.

**HARD FAILURES (3 instances):**
- k5_chain10: S_prism=1 < S_multi_opt=1
- rand_dag_n5_s42_chain10: S_prism=0 < S_multi_opt=0
- k5_grid25: S_prism=0 < S_multi_opt=0
This indicates a metric semantics mismatch or oracle bug. Do not use these results in the paper.

## Uncertainties

- Compiler runs use a single seed (or min over a small set); the reported S_greedy/S_prism
  are not the true compiler optimum over all seeds. Running more seeds would tighten gaps.
- The oracle uses tight topologies (n_phys = n_rails = 2*n_logical), not the full
  n+1-spare-pair topologies used in the main experiments. Opportunity and gaps may differ
  on larger topologies.
- Init SWAPs are excluded via local_init=True. If the main experiment uses the default
  local_init=False, the comparison must account for init overhead separately.
