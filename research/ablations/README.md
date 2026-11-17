# Reviewer ablations (external review, 2026-07-31)

Prototypes answering the empirically testable weaknesses in the external
External review of `delocal_dualrail/main_anon.pdf` (weak reject; central
concern: the 26.0-31.3% SWAP win might come from PRISM's load/usage tie-break
or from Greedy's stale per-pass commitment rather than from retained-set
routing). All runs reuse the `configs/paper/core.toml` cells: 16 workloads, grid +
hex_lattice, n=8, seeds 0-19, 40+3 starts, 16 refinement iterations, 40-trial
final route, qiskit_sabre heuristic.

Findings (raw under `artifacts/paper/raw/<experiment_id>.jsonl`; `report.py` recomputes every number):

- **W1 tie-break confound: denied.** `tiebreak.toml` reruns
  the PRISM arm with Greedy's exact tie-break (`tie_break="default"`).
  Router-inserted SWAPs are identical to PRISM(load) in 640/640 paired runs;
  the load tie-break carries 0pp of the SWAP reduction and 0.5-1.4pp of the
  12.4/7.9% depth reduction.
- **W2 front-layer-commit baseline: run.** `front_commit.toml` runs the
  `prism_front_commit` arm (`build_pm(..., front_commit=True)`), which freezes each deferred gate to its
  closest realization at first front-layer entry and routes toward only that
  choice and keeps its own route, like Greedy and PRISM.
- **W6 seed-level uncertainty: answered from existing raw.** Per-run paired
  stats over core: PRISM SWAP regressions in 5/640 runs (max +2), 0/20
  pooled seeds and 0/32 workload-topology cells regress; depth regresses in
  110/640 runs and 3/32 hex cells (dj, modular_adder, qaoa).

`prism_front_commit` is a `scripts/paper/run_fairness.py` arm, so cells,
budgets, seeds, and row schema match the production runner.

Review-2 additions (2026-08-01): `slack.toml`
runs the core arms on 5x5 and 6x6 grids (56% and 125% spare sites); the swap
reduction holds at 30.6% and 28.8% versus 31.3% on the paper grid, with
identical 13/3/0 win-tie-loss. `check_excluded_workloads.py` +
`excluded.toml` route the nine excluded workloads over all
20 seeds (PRISM 0 SWAPs in every run, Greedy at most 1), backing the §5.1
exclusion sentence; `randomcircuit.toml` gives the separately
reported randomcircuit numbers (40.8/38.9%). The seed-noise test shows the
three hex depth regressions are systematic (qaoa +2 in 20/20 seeds), and the
per-gate erasure recomputation shows a per-SWS term cancels in the arm ratio
while any per-routing-gate term raises the projected advantage. The arity
ladder was already answered by `diversity_n8.jsonl` (binary choice -28/-30%,
duplicate arity null, full set -43.4%). Detail in memory
`project_reviewer_ablation_results`.

Pre-deadline red-team pair (2026-08-01): Mehta Table III prints the target iRB as 1.08e-5 against its own Fig. 5 caption's 1.08(1)e-4, and liu_toric_2026 transcribed the typo. Since 2026-10-06 the device model uses the corrected eps_RSWAP = 9.9e-5 (see research/rebuttal/response_log.md, F1).
