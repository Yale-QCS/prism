---
name: project-reviewer-ablation-results
description: "External-review ablations (2026-07-31) — tie-break confound denied, front-layer-commit baseline decomposition, seed-level stats, excluded-workload check"
metadata: 
  node_type: memory
  type: project
  originSessionId: a7c9ba5f-fe15-4dc9-9fb8-45abbd2635b5
  modified: 2026-08-01T06:07:41.707Z
---

External review of `main_anon.pdf` (weak reject) raised four
empirically testable concerns; all were prototyped on the frozen core_v22
cells (16 workloads, grid+hex, n=8, seeds 0-19, 40+3 starts / 16 iters /
40-trial final). Raw: `artifacts/paper/raw/rr_*.jsonl`; scripts:
`research/ablations/`.

- **Tie-break confound (their W1): DENIED.** PRISM rerun with Greedy's exact
  tie-break (`tie_break="default"`): router-inserted swaps identical in
  640/640 paired runs (26.0/31.3% unchanged); the load tie-break carries only
  0.5-1.4pp of the 7.9/12.4% depth win. Note the v22 paper run set
  `tie_break="load"` and greedy binding structurally ignores it, so the paper
  prose (§4C "least recent use") describes a knob that does not produce the
  SWAP headline.
- **Front-layer-commit baseline (their W2): PARTIAL CONFIRM, good story.**
  New Rust mode `multi_front_commit` (default off; off-path certified
  row-identical on 40 cells + quick_bench + 38 routing tests): freeze each
  deferred gate to its closest realization at first front-layer entry,
  sticky-score and commit only that choice. Result: front-commit gets
  25.0%/20.7% (grid/hex) swap reduction vs Greedy; PRISM's retained sets add
  a consistent further 8.6%/6.7% over front-commit (paired 392 better / 66
  worse of 640); depth is a tie between them. So ~4/5 of the headline is
  fresh commitment timing, ~1/5 is live alternatives during SWAP search, and
  BOTH require the multi-realization boundary IR (front-commit is not
  expressible in an early-lowering pipeline). Depth argument for retained
  sets is weak standalone.
- **Seed-level stats (their W6): answered from existing raw.** Swaps: prism
  regresses in 5/640 paired runs (max +2), 0/20 pooled seeds, 0/32 cells.
  Depth: 110/640 paired regressions, 3/32 hex cells regress on mean (dj,
  modular_adder, qaoa hex).
- **Workload conditioning (their W4): conservative, but prose inexact.** Of
  the 10 excluded MQT workloads, 6 are all-zero for every arm; bv/graphstate/
  wstate have tiny trivial-only swaps with greedy=prism=0 (headline ratio of
  means invariant); randomcircuit is heavily routed (greedy 119/178,
  prism 67/107 grid/hex = ~40-44% prism win), so the full-26 pooled reduction
  would be LARGER (~34.5% grid / ~29.6% hex). But the §5.1 criterion sentence
  ("workloads where the default-realization compiler inserts SWAPs at n=8")
  does not literally reproduce the 16: wstate (trivial 7/9 swaps) and
  randomcircuit satisfy it yet are excluded. Exclusion provenance needs a
  real answer before the rebuttal.

CLEAN-FINGERPRINT REGENERATION (2026-08-01, commit 13bac1e, fingerprint
f11c126f41661ff2): rr2_* raws row-identical to rr_* incl. hashes,
dirty_tree=False. Exact literals now in the paper: ablated-vs-Greedy
25.0/20.7%, PRISM-vs-ablated 8.4/6.8% (earlier 8.6/6.7 came from rounded
means), tie-break depth 12.4/7.9 -> 11.0/7.4, slack 30.6/28.8,
randomcircuit 20-seed 40.8/38.9% (3-seed 43.7/39.9 superseded). §5
Ablations subsection + §5.1 rewrite + W5 setup facts (MQT 2.2.2,
algorithm-level, 5x4 grid/3x3 hex, Ryzen 5 5600X) are INKED.

Review 2 (2026-08-01, MIRAGE-novelty reviewer) checks, same rr_ pipeline:

- **Hex depth regressions are systematic, not noise** (their W4): qaoa +2
  layers in 20/20 seeds, dj sign-p 0.002, modular_adder 0.004. Correct answer
  is the paper's existing objective-ordering explanation, never "noise".
  Dispersion overall tiny (paired swap-delta sd median 0.85, max 2.9).
- **Per-gate erasure term** (their W5): the reviewer's inference conflates
  gate types. The 0.5%/gate erasure is measured for SWS (coupler
  occupation), whose count = logical CRz count and is arm-invariant (73/96
  cells exact; term cancels, ~0.1pp). The gates PRISM removes are
  beamsplitter rswaps, which stay in cavity modes and never occupy the
  coupler, so their loss is duration-proportional and already modeled; no
  hardware-grounded per-gate term differentiates the arms. Sensitivity
  bound only: a hypothetical per-rswap term at 0.25/0.5%/gate would RAISE
  the n=16 overhead reduction to 40.6/45.2% or 50.3/56.2%.
- **Device slack does not dissolve the win** (their W3):
  grid 20/25/36 sites (25/56/125% spare) gives 31.3/30.6/28.8% swap
  reduction, W/T/L 13/3/0 at every slack level; hex was already 88% spare
  (30 sites) at 26.0%. Greedy's absolute swaps do not drop with slack
  (`rr_slack_seed20_n8.jsonl`).
- **Arity vs diversity already measured** (their W2): diversity_n8 ladder,
  260 common cells: R1 37.9 swaps; binary choice (MIRAGE arity) 26.6-27.1
  (-28/-30%); R4-duplicate null (+0.3%); full four-support set 21.4
  (-43.4%, a further ~20% below best binary). Benefit tracks unique
  supports, not arity. Legacy budget; rerun at v22 config before inking.
- Ref [29] "Pavlovich & Puri" was never in the paper; all citation flags
  dispositioned 2026-07-31 [[reference-citation-verification-2026-07]];
  MIRAGE/Marol-as-baseline has a standing user ruling (cannot consume the
  input). Eq. 11 rz corrections are software-tracked (FREE_GATES); needs one
  prose sentence.

Review pair 2 (2026-08-01, pre-deadline red team; borderline-3 + weak-reject-4):

- **eps_RSWAP=5.04e-5 inherits a verified typo, SHIPPED ANYWAY (user
  ruling).** Mehta 2503.10935 Table III prints target individual iRB 1.08e-5
  where its Fig. 5 caption says 1.08(1)e-4; the RB decay curves (~0.90 at
  1000 Cliffords), the ">99.98% fidelity" text, and the 5-of-6 exact
  table-caption entry matches all prove the caption right. liu_toric_2026
  Table 4 (user co-authored; erratum candidate) transcribed the typo; our
  central average should be 9.9e-5. Recomputed on scale_v24 raw
  (temp_diagnostics/recompute_rswap_error.py): conditional-infidelity
  reduction 7.6-8.6% -> 7.8-8.8% (rises; the removed exchanges carry the
  error), shot overhead unchanged 28.8/34.2%. Decision: keep 5.04e-5 in the
  submission (faithful to cited Liu source), disclose + correct in rebuttal
  if raised. Decoherence-subtracted eps (~5.3e-5) brackets the answer
  between the two computed runs.
- **QEC-regime data point exists (quick harness).** Rotated surface-code d=3
  (17 logical, 34 rails, 6x6 grid, 2 rounds, X-checks via CX + Z-checks via
  phase kickback): greedy 51 / prism 22 total swaps over 3 seeds = 56.9%
  reduction, above the algorithm-suite headline; depth -12.7% with one seed
  regressing. 1D rep-code d=3 is routing-trivial for both arms (like the
  excluded workloads). DualRail.reset unimplemented (ancillas unreset
  between rounds; routing content unaffected). Script:
  temp_diagnostics/q4_stabilizer_proto.py; harden via run_fairness
  monkeypatch before quoting.
- **Separated-rail qualifier INKED pre-deadline:** SS6.1 first sentence now
  "While its rails are separated and its excitation remains within the rail
  pair, ..." (closes the ancilla-mediated-transfer loophole reviewer 2
  named; consistent with the paragraph's measurement/state-transfer closer).

Related: [[project-fairness-v3-results]], [[project-greedy-stockplus-arm]].
