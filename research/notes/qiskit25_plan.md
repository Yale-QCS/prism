# Qiskit 2.5 and MultiStagePassManager: refactor plan for prism

Written 2026-09-03. Installed: qiskit 2.4.2, pin `qiskit>=2.4.1,<2.5`.
Latest on PyPI: 2.5.2. Rust crate pins `qiskit-circuit` / `qiskit-transpiler`
git tag 2.3.1 (vendored SABRE), uses only `VirtualQubit` from them.

## What 2.5 actually adds

- `qiskit.passmanager.MultiStagePassManager(**stages)`: named stages run in
  order, each a `Task`, an iterable of tasks, or a `BasePassManager`. A stage
  may preserve its IR (`Task[IR, IR]`) or lower it (`Task[IR1, IR2]`). No
  implicit circuit/DAG conversion, no `pre_*`/`post_*` hooks, no automatic
  IR translation. A `BasePassManager` used as a stage contributes only its
  tasks (its frontend/backend conversions are skipped). Stages are
  replaceable by attribute assignment; `run(program, property_set=ps)` mutates
  a caller-supplied property set. Execution linearizes to a
  `FlowControllerLinear`. Custom-IR passes derive from `GenericPass[IR_IN,
  IR_OUT]` with `run(passmanager_ir)` and `self.property_set`.
- Qiskit's own new presets (`generate_preset_pbc_pass_manager`,
  `generate_preset_clifford_t_pass_manager`) still return `StagedPassManager`;
  `MultiStagePassManager` is the generic framework, not yet used by IBM's
  presets.
- SABRE: lookahead is now per circuit layer, `Heuristic.with_lookahead([0.5/n],
  Constant)` takes a list of layer weights. Stock `SabreLayout`/`SabreSwap`
  results change.
- `TwoQubitPeepholeOptimization` replaces `ConsolidateBlocks` +
  `UnitarySynthesis` at O2/O3 (fidelity-oriented, multithreaded).
- VF2 determinism fix, `ElidePermutations` virtual-permutation-layout fix,
  `BasisTranslator` nested control-flow fix.

## Empirical status

- Full prism test suite passes on 2.5.2 with no code change (159 tests,
  PYTHONPATH override).
- Same-seed metrics, grid, budget 8, seed 0 (2.4.2 -> 2.5.2, swaps):

  | circuit | quotient | greedy | prism |
  |---|---|---|---|
  | surface_d3 | 12 -> 9 | 18 -> 18 | 20 -> 20 |
  | bb_18_4_4 | 383 -> 434 | 314 -> 314 | 264 -> 264 |
  | qft n=8 | 22 -> 28 | 20 -> 20 | 16 -> 16 |
  | ae n=8 | 34 -> 30 | 23 -> 21 | 16 -> 19 |

  The quotient arm moves everywhere (stock SABRE heuristic changed). The
  practical arms are stable where the lowering route is kept and move where
  the O3 physical stage wins the compare-and-swap (ae). The HPCA raw artifacts
  are therefore 2.4-only replays.

## What is wonky in `staged_pms.py` today

1. The `build_pm` strategy ladder: six `if/elif` branches assembling pass
   lists.
2. Cross-stage state smuggled through `property_set`: `layout`,
   `realization_choices`, `lowering_routed_dag`, `lowering_routed_final_layout`,
   `online_n_swaps`, `search_trace`, `prism_objective`, `routing_handoff_kept`,
   `handoff_scores`, plus the `logical_output_permutation` in DAG metadata.
   `LoweredOp` nodes ride inside a `DAGCircuit` as custom `Operation`s.
3. Physical-stage surgery on the preset: strip `ElidePermutations` from
   init, strip `SetLayout`, empty `layout` and `routing` when the combined
   route is used, inject metrics snapshots through `pre_*`/`post_*` hooks.
4. `LowerExpansion` clears `layout`/`final_layout` to stop quotient-sized
   layouts leaking across the encoding boundary.

## Target design

A typed pipeline where the encoding boundary is an IR boundary:

```
input     QuantumCircuit -> DAGCircuit          (records original_qubit_indices, num_input_qubits)
logical   DAGCircuit -> DAGCircuit               enc.logical_pm() tasks
expand    DAGCircuit -> LoweredProgram           LowerExpansion, typed
commit    LoweredProgram -> LoweredProgram       one CommitPolicy (the strategy)
lower     LoweredProgram -> DAGCircuit           ApplyCommits + handoff resolution; sets layout/final_layout
physical  DAGCircuit -> DAGCircuit               preset StagedPassManager (hooks intact)
output    DAGCircuit -> QuantumCircuit           attaches TranspileLayout
```

`LoweredProgram` is a frozen dataclass (`dataclasses.replace` for updates):
`dag` (rail-level DAG of `LoweredOp`), `enc`, `wires` (logical -> rail tuple),
`meas_map`, `logical_output_permutation`, `choices`, `layout`, `routed_dag`,
`routed_final_layout`, `n_swaps`, `search_trace`, `objective`. Every
property-set key in item 2 above becomes a field. `CommitPolicy` becomes
`GenericPass[LoweredProgram, LoweredProgram]` whose `commit()` returns a
`CommitResult` merged by `replace`. `RecordCircuitMetrics` stays a DAG pass
and runs at the `lower` output and inside the physical preset hooks.

Strategy selection becomes stage assignment, not a ladder:

```python
pm = build_pm(cmap, enc)          # default commit stage = PrismRouting
pm.commit = GreedyCommit(cmap, enc=enc, seed=s)
```

The quotient arm's `SabreLayout`/`SabreSwap` on the quotient graph are
logical-DAG tasks; they move into a `prelayout` stage between `logical` and
`expand`, which is where they belong, and `RecordQuotientPartition` records
into `LoweredProgram` at expansion.

Physical stage: keep `generate_preset_pass_manager` as a nested
`StagedPassManager` so `pre_*`/`post_*` hooks and the O3 optimization loop
survive. Replace the surgery with stage plugins: an `init_method` plugin that
is the stock init without `ElidePermutations`, and `layout_method` /
`routing_method` set to a registered no-op plugin (`prism_combined`) when the
lowering route is kept. `ResolveRoutingHandoff` / `UseLoweringRoute` read the
`LoweredProgram` in the `lower` stage rather than the property set.

What the IR buys beyond tidiness:

- The VF2-on-quotient perfect-layout start (see `qec_codes.md`) is a
  `prelayout` task that writes a seed layout into `LoweredProgram`.
- Dynamic rail allocation at measure/reset boundaries (free-rail pool) is IR
  state, not a property-set convention.
- A second encoding or a second commit policy is a stage swap, testable in
  isolation with a synthetic `LoweredProgram`.
- `run(..., property_set=ps)` gives `run_experiment.py` the same
  instrumentation surface it has now.

## Phases and gates

Same-seed metrics on the core grid (`core_v22` config, 3 circuits, 2 seeds,
both practical arms) are the regression gate for every phase; a change in
any number reverts the phase.

0. **Pin bump, no refactor.** `qiskit>=2.5,<2.6`, run the suite, run the
   gate under 2.4.2 and 2.5.2, record the drift table above in ARTIFACT.md.
   Decide: re-freeze `artifacts/hpca/raw` under 2.5 (preferred if the paper
   is re-run anyway) or keep a `[replay]` extra pinning 2.4 for the artifact.
   Half a day.
1. **Introduce `LoweredProgram` behind the existing pipeline.** `LowerExpansion`
   builds it, `CommitPolicy.run` unpacks/repacks it, `ApplyCommits` and the
   handoff passes read fields. Keep `StagedPassManager`, keep the property-set
   keys as a mirror for one release so `run_experiment.py` is untouched.
   One day.
2. **Switch `build_pm` to `MultiStagePassManager`.** Explicit input/output
   tasks, `commit` stage per strategy, physical preset via plugins instead of
   surgery, delete the property-set mirror, update `run_experiment.py` to
   read `LoweredProgram` fields via the returned property set. One to two
   days including notebooks and docs.
3. **Rust follow-up (optional).** Re-vendor SABRE from the 2.5 tag so the
   prism kernel's heuristic matches stock 2.5 (`with_lookahead` layers). Only
   needed if the paper claims parity with stock 2.5 SABRE; the kernel is
   otherwise version-independent. Half a day plus a full re-run.

## Risks

- `MultiStagePassManager` execution is documented as subject to change
  (linearized flow controller). Stage names and attribute assignment are the
  stable surface; do not depend on nesting semantics.
- `GenericPass` subclasses on a custom IR lose `TransformationPass`
  bookkeeping (`requires`/`preserves`, DAG-specific `execute`). Fine for
  commit policies, which never used it.
- Baseline drift under 2.5 (quotient arm, O3 compare-and-swap) is real and
  must be documented, not hidden: every published number is tied to a
  qiskit version.
- `TwoQubitPeepholeOptimization` may change what `CancelRailX` sees after O3
  resynthesis; the same-seed gate covers it.

## Hindsight revisions (same day, after review)

Three decisions above were inherited from working around the missing framework.

1. **Prism is the preset's layout+routing stage, not a separate commit stage.**
   Register `PassManagerStagePlugin` entry points (`layout_method` /
   `routing_method` = `prism`, `greedy`, `quotient_sabre`). Deletes
   `ResolveRoutingHandoff`, `UseLoweringRoute`, the emptied stages, the
   `SetLayout` stripping, and the property-set handoff. The paper arms never
   used the O3 compare-and-swap; keep it as an opt-in experiment arm only.
2. **Boundary IR stays `LoweredOp` nodes in a `DAGCircuit`** (IBM's PBC preset
   uses the same pattern). Register `LoweredOp` in the boundary `Target` so
   init passes skip it. `LoweredProgram` carries only what a DAG cannot:
   wire binding, Pauli frame, free-rail pool. Rule: program semantics in the
   IR, instrumentation in the property set.
3. **Encoding = `Target` + equivalence library of realizations** (each entry
   a circuit with a wire footprint, later an output mapping and frame
   update). `LowerExpansion` becomes a translation pass. Replaces
   `LOGICAL_ISA` / `PHYSICAL_ISA` / `custom_name_mapping` / per-gate
   classmethods as the user-facing way to add a code.

Unchanged: the vendored SABRE kernel (no upstream hook for per-gate
multi-realization cost; freeze it as prism's router derived from 2.3.1), and
the explicit `output` task that defines prism's own layout object, because the
encoding boundary breaks `TranspileLayout`'s virtual-to-physical bijection.

Revised stages:

```
input -> logical -> prelayout (quotient SABRE, VF2 seed) -> expand (boundary IR)
      -> physical preset, layout/routing = prism plugin -> output (prism layout)
```

Phase 2 becomes "plugins + Target/library encoding"; less code than the
commit-stage version.

## Pre-execution checks (run 2026-09-03, scratchpad `plan_checks.py`)

Same-seed cells: surface_d3, qft n=8, ae n=8 on grid, seeds 0 and 1, prism and
greedy, budget 8.

- **A. Prism as the preset's layout stage.** Stock O3 preset built from
  `_physical_target` plus `target.add_instruction(LoweredOp, name=...)`,
  `preset.layout = [PrismRouting, UseLoweringRoute]`, `preset.routing = []`,
  run on the boundary circuit (after `LowerExpansion`), stock init untouched.
  On **2.4.2: all 12 cells identical to `build_pm`** (swaps, depth, duration),
  and `out.layout` is attached. So the plugin design is metric-preserving.
- **B. `MultiStagePassManager` wrapper** (input task, logical, lowering,
  physical preset as nested `StagedPassManager`, output task) on **2.5.2: all
  12 cells identical**, `TranspileLayout.from_property_set` attaches. The
  shared property set and nested-preset hooks work as claimed.
- **C. `EquivalenceLibrary` as realization store.** A 4-wire parameterized
  placeholder with four entries; `get_entry` on a bound instance returns the
  four realizations in insertion order with the parameter bound.
- **`Target` can be subclassed and carry attributes** (`DualRailTarget.enc`),
  so a stage plugin can recover the encoding from `pass_manager_config.target`.

### Blocker found: Qiskit 2.5 `CommutativeCancellation` hangs on boundary ops

- Check A on **2.5.2 never returns**: `faulthandler` traceback places it inside
  `CommutativeCancellation.run` in the preset init stage. A 33-op qft n=4
  boundary circuit runs past 580 s; 2.4.2 finishes instantly. Every other O3
  init pass (`UnitarySynthesis`, `HLS`, `BasisTranslator`, `ElidePermutations`,
  `RemoveDiagonalGatesBeforeMeasure`, `RemoveIdentityEquivalent`,
  `InverseCancellation`, `ConsolidateBlocks`, `Split2QUnitaries`) is fine on
  the same circuit.
- Prism-free repro: `Gate("rx", 1, [0.4])` (an opaque `Gate` named like a
  standard rotation) between two `rz` hangs on 2.5.2, fine on 2.4.2;
  `Instruction("rx", ...)` does not hang. Cause is PR #16191 (2.5.0), which
  matches rotation gates **by name**; its regression test (issue 13988) only
  covers a 2-qubit custom `ryy`.
- **Renaming the boundary ops fixes it.** With `LoweredOp` nodes built as
  `<gate>_L` (names set at construction; mutating `_name` on ops already in a
  circuit does not reach the Rust-side node name, which is why the first
  attempt looked insufficient) and registered in the boundary `Target`,
  check A on **2.5.2 matches `build_pm` on all 12 cells** with stock init
  running before prism.
- Bisected boundary prefix: four `x`/`joint_herald` prep pairs then an opaque
  2-wire op named `rz`. **Minimal prism-free repro (2.5.2 hangs, 2.4.2
  instant):**

  ```python
  qc = QuantumCircuit(2)
  qc.append(Gate("x", 1, []), [1])
  qc.append(Gate("rz", 2, []), [0, 1])
  CommutativeCancellation()(qc)
  ```

  **Root cause (verified 2026-09-04): a GIL deadlock, not the #13988 bug.**
  #13991 (Treinish, 2.0) fixed #13988 by replacing name-keyed lookups in the
  commutation checker (`SUPPORTED_OP: HashSet<&str>`, `SUPPORTED_ROTATIONS:
  HashMap<&str, ..>`, `get_standard_gate_names`) with `StandardGate`-indexed
  tables; the cancellation pass classifies with `try_standard_gate()`. That
  fix is still in 2.5.2. What broke is PR #16014 (2.5.0, "Parallelize the
  CommutationAnalysis pass"): per-qubit analysis now runs on rayon workers,
  and the checker's fallback for non-standard gates builds a matrix through
  Python (`try_matrix_with_definition`), which needs the GIL while the
  calling thread holds it. Evidence: unrestricted `CommutationAnalysis` on
  any two opaque `Gate`s sharing a wire (`foo` then `bar`) hangs;
  `QISKIT_IN_PARALLEL=TRUE` (forces the serial path) returns in 1 ms;
  `RAYON_NUM_THREADS=1` still hangs; `Instruction` never hangs because
  `PyOpKind::Instruction` short-circuits before the matrix path.
  `CommutativeCancellation` only shows it for names in its cancellable set
  (`x`, `rx`, `rz`, `sx`, ...) because its checker is built with a
  gate-name filter that skips everything else before the Python fallback.
  So the `_L` rename protects prism from `CommutativeCancellation`
  specifically; any pass running an unrestricted `CommutationAnalysis`
  (`CommutativeInverseCancellation`, `CommutativeOptimization`, which
  issue #15452 proposes enabling by default) still deadlocks on `LoweredOp`
  pairs. Guard: never run commutation passes on the boundary IR, or set
  `QISKIT_IN_PARALLEL=TRUE` for that stage. Filed as Qiskit/qiskit#16937 (2026-09-04) against #16014,
  with the `foo`/`bar` `CommutationAnalysis` repro.
- `LoweredOp` has no `copy()`, so `QuantumCircuit.copy()` fails on a boundary
  circuit. Add it (cheap) regardless of the pipeline choice.

### Consequence for the design

Boundary op names get their own namespace (`<gate>_L`, or `lowered.<gate>`)
registered in the boundary `Target`, so no name-keyed stock pass can mistake a
boundary op for the gate it lowers. With that, stock O3 init is safe on the
boundary IR and metric-preserving on both 2.4.2 and 2.5.2. Whether init runs
before prism (Qiskit's intended order) or after commit (today's order) is
then a free choice; the same-seed gate showed no difference on the checked
cells.

## Workaround landed (2026-09-04, uncommitted in prism, staged)

- `LoweredOp` names are namespaced at construction: `name` -> `f"{name}_L"`,
  original kept as `logical_name`; `copy()` added. `pin.py` and
  `RecordQuotientRoutingSwaps` use `logical_name`.
- `staged_pms.py`: `serial_commutation()` context manager
  (`QISKIT_IN_PARALLEL=TRUE`, restored on exit), `SerialCommutativeCancellation`,
  and `guard_commutation_passes(pm)` which reclasses every
  `CommutativeCancellation` in a (Staged)PassManager tree; `build_pm` applies it
  (2 instances in the O3 preset). Rule comment: no commutation pass on logical
  or boundary stages.
- `pyproject`: `qiskit>=2.5,<2.6` (venv is 2.5.2).
- Gates: suite 162 passed; the 12 same-seed cells (surface_d3, qft8, ae8; grid;
  seeds 0,1; prism, greedy) are identical to the pre-edit 2.5.2 baselines.
- Deferred to phase 1: `LoweredOp` as an `Instruction` subclass (removes the
  deadlock path entirely via `PyOpKind::Instruction`).

## Phase 1 landed (2026-09-04, staged in prism, uncommitted)

Boundary IR is a type now. `src/prism/lowering/ir.py`:

- `LoweredProgram` (frozen dataclass): `dag` (rail-wire DAG of `LoweredOp`),
  `enc`, `wires` (logical qubit -> rail tuple), `ancilla_wires`,
  `logical_output_permutation`, and the commit decision `choices`, `layout`,
  `routed_dag`, `routed_final_layout`. `with_commit(CommitResult)` via
  `dataclasses.replace`; `committed_dag()` substitutes realizations on a copy
  and leaves `dag` intact. Instrumentation (swap counts, traces, objective)
  stays in the property set by rule.
- `apply_commits(dag, choices)` is the pure substitution; `ApplyCommits` (legacy
  DAG pass) delegates to it.

Typed stage tasks (`qiskit.passmanager.GenericPass`): `ExpandStage`
(`DAGCircuit -> LoweredProgram`, wraps the pure `expand()`; `LowerExpansion`
kept as the DAG-only pass for hand-built pipelines), `CommitStage(policy)`
(`LoweredProgram -> LoweredProgram`, runs any `CommitPolicy.commit` over
`prog.dag`, mirrors `realization_choices`/`online_*`/`search_trace` to the
property set), `LowerStage` (`LoweredProgram -> DAGCircuit`, publishes
`layout` and the routed handoff under the keys the physical preset reads),
`RecordQuotientRoutingSwaps` (now `LoweredProgram -> LoweredProgram`).

`build_pm` returns `PrismPassManager(MultiStagePassManager)` with stages
`input, logical, prelayout, expand, commit, lower, physical, output`;
`CircuitToDAG`/`DAGToCircuit` are the explicit boundary tasks; `.property_set`
and `run(qc)` keep the old call surface (`run_experiment._run_one` verified on
all three arms). The strategy ladder is now "pick a policy"; `pm.commit =
CommitStage(policy)` swaps it (routed-handoff contract must match `physical`).
`guard_commutation_passes` walks `MultiStagePassManager` too.

Gates: suite 165 passed; the 12 same-seed cells identical to the pre-refactor
2.5.2 baselines; ruff clean.

Still to do (phase 2): plugin-based physical stage instead of preset surgery,
`Target` + equivalence-library encodings, drop the property-set mirror once
`run_experiment` reads the program directly, `LoweredOp` as `Instruction`.

## Phase 2a landed (2026-09-04, staged in prism, uncommitted): physical stage without surgery

- Paper arms (`use_lowering_route=True`): preset generated with
  `routing_method="none"`; layout stage emptied by assignment; the routing
  stage is Qiskit's `CheckMap` validity check on the retained route.
  `UseLoweringRoute` (init-front insertion) is gone; `InstallLoweringRoute`
  is a typed `LoweredProgram -> DAGCircuit` task in `lower`.
- Baseline arms: stock preset (`SabreLayout` lays out and routes jointly),
  with exactly two stock tasks excluded and the reason for each documented:
  `ElidePermutations` (init; would make a committed rail exchange a free
  virtual permutation) and `SetLayout(None)` (layout; erases the published
  layout). Everything else is the hook API (`pre_layout`, `pre_routing`,
  `post_routing`, `post_optimization`).
- `RecordProgramMetrics` (`LoweredProgram -> LoweredProgram`) takes the
  lowering snapshot over `committed_dag()`; `LowerStage` substitutes in place.
- Two dead ends, both diagnosed by diffing stage task trees: `routing_method
  ="none"` for the baseline arms sets `SabreLayout(skip_routing=True)`, and
  the stock layout stage's leading `SetLayout(None)` wipes the published
  layout. Both changed the baseline arms' numbers until reverted.
- Evidence: `research/scripts/gates/full_gate.py check` (96 cells: 4 circuits
  x grid/hex x 2 seeds x 6 strategies; swaps, depth, active gates, duration,
  router swaps, handoff, op counts, width, layout, permutation) -> 0
  mismatches against the baseline recorded before the change; suite 165.

## Phase 2b landed (2026-09-04): one lowering path

- `CommitPolicy` is a plain ABC (`commit(dag) -> CommitResult`, `property_set`
  attribute shared by `CommitStage`); the `AnalysisPass` base and its `run`
  side-channel writer are gone. `ApplyCommits` and `LowerExpansion` deleted;
  `apply_commits()` / `expand()` are the functions, `LowerStage` /
  `ExpandStage` the tasks.
- `OverDag(pass)` lifts any DAG pass (`PinRealizations`, metrics) to
  `LoweredProgram -> LoweredProgram`; the fairness-test harness builds its
  pinned pipeline as `PrismPassManager(input, logical, expand, pin, commit,
  lower, physical, output)`.
- Gate: 96 cells identical again; suite 165; ruff clean. No notebook or
  script referenced the deleted classes.

## Phase 2c (2026-09-04): `staged_pms.py` split, prose cut, paper-set gate

- `staged_pms.py` (837 lines, 170 of docstring) is gone. `pipeline.py` (build_pm,
  PrismPassManager, boundary tasks, InstallLoweringRoute, RecordProgramMetrics),
  `logical.py` (basic_logical_pm, ElideLogicalPermutations), `physical.py`
  (physical_pm, ResolveRoutingHandoff, SeedVF2ErrorMap, CancelRailX,
  SafeOptimizeSwapBeforeMeasure, commutation guard), quotient-arm accounting
  in `utils/quotient.py`. One-line docstrings throughout. The duplicate
  default-key metrics snapshot in `lower` is gone.
- Paper-set gate `research/scripts/gates/paper_gate.py`: the 16 core mqt.bench
  circuits from the frozen qpy manifests, paper budget (40/16/40, qiskit_sabre,
  load tie-break), three paper arms, grid + hex, seed 0. Old pipeline
  (`staged_pms_old.py` snapshot, dispatch patched) vs new in one process:
  **0 of 96 differ**. Log kept as `paper_gate_2026-09-04.log`.
- New vs the frozen HPCA rows (qiskit 2.4.1): quotient arm differs in 31/32
  cells (stock SABRE changed in 2.5), practical arms in 9/32 each (O3
  optimization changes in 2.5; 6 cells with more swaps, 1 with fewer for
  greedy). This is the Qiskit-version drift, not the refactor; same-version
  old-vs-new is identical. The HPCA artifact remains a 2.4 replay.
- 96-cell full-strategy gate on the split modules: 0 mismatches. Suite 165.

## Split and bulldoze (2026-09-04, evening; staged in prism, uncommitted)

Decision: marabbecca is the frozen HPCA artifact (Qiskit 2.4.1, every arm,
validators, rows; verified head reproduces the frozen `dj` rows exactly via
`run_fairness.py`), prism is the tool on 2.5. Copied to marabbecca: adapted
`ARTIFACT.md`, the two figure notebooks under `artifacts/hpca/prism_notebooks/`,
README pointer, runner note in `scripts/hpca/README.md` (uncommitted there).

Deleted from prism: `artifacts/hpca`, `ARTIFACT.md`, `scripts/run_experiment.py`,
notebooks 02/03, the quotient/greedy/trivial/stock-plus policies, `pin.py`,
`utils/quotient.py`, `utils/benchmarks.py`, `ResolveRoutingHandoff`,
`handoff_mode`, pre/post-routing snapshots, `swap_provenance`, `LowerStage`,
the search-trace payload, greedy binding, sticky witness, legacy start mode,
the `tuned` heuristic, `tie_break` (load is hardwired), teleport
(`DualRailTeleport`, `bell_prep`, ancilla pool, `ancilla_wires`), and the
tests for all of it. `build_pm(cmap, enc, *, seed, budget)`; `SearchBudget`
is `layout_starts=40, refinement_iterations=16, swap_trials=40, objective`.

Sizes: `src/prism` 4,531 -> 2,872 lines; tests 4,289 -> ~1,000; `prism_routing.py`
889 -> 622; `physical.py` 328 -> 248; runner gone. Gates: 93 tests;
`research/scripts/gates/prism_gate.py` (16 paper circuits from marabbecca's qpy,
paper budget, grid+hex, seed 0, prism) 0 of 32 mismatches against the
pre-cut 2.5.2 numbers.

Open: PyPI name (`prism` is taken; `qiskit-prism` free), entry-point stage
plugins for ecosystem listing, outer search loop into Rust (prism_routing.py
would drop to ~200), `LoweredOp` as `Instruction`, README/docs rewrite for the
tool, CITATION/pyproject metadata.

## Outer loop in Rust (2026-09-04, late; staged)

`crates/src/prism_routing/layout.rs` (110 lines): `prism_layout_and_routing(
forward, reverse, target, heuristic, starts, max_iterations, swap_trials)`
takes both flattened contexts exactly as Python built them, runs the
forward/backward refinement and the final multi-trial route per start
(starts in parallel via `CondIterator`, inner routes serial), same seed
schedule mod 2^64, and returns one `(events, final_v2p, n_swaps,
refined_v2p)` per start. Python keeps `_starting_layouts`, emission,
`score`, and `_build_result`; `commit` is 30 lines; `_route_invocation` and
the per-call plumbing are gone. Start seeds are wrapped mod 2^64 before the
call (exact: the route schedule already reduced mod 2^64).

Gates: 93 tests; `prism_gate.py` 0 of 32 mismatches, and the 32-cell paper
set now runs in 8 s wall (was ~90 s). `prism_routing.py` 622 -> 590; the
remaining bulk is emission (`_emit_*`, ~130 lines) and precompute (~130),
which a follow-up could move into the crate too (emit the routed DAG in Rust
like `RoutingResult::rebuild`).
