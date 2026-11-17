# Front-commit ablation, isolated (Fig. 11a, §V-C)

The submitted ablation (`research/rebuttal/suite/swaps/front_commit_swaps*.toml`) differed from PRISM in three ways:
1. it commits each gate when the gate enters the front layer (`multi_front_commit`), which is the intended ablation;
2. it scores lookahead-set gates on one witness realization instead of the minimum over R(g) (`multi_sticky_witness`), because `front_commit=True` set both kernel flags;
3. it used `tie_break = "default"`, while PRISM (`core_swaps`) uses `"load"`.

The audit is in `research/rebuttal-r3/audit/router.md` (R7.2) and `router-check.md` (section 6). These rows remove (2) and (3), so commit time is the only difference from PRISM.

## Code change

- `PrismRouting(front_commit_witness=True)` and `build_pm(front_commit_witness=True)`: when this is `False`, `front_commit` sets `multi_front_commit` alone, and `multi_sticky_witness` stays off. The default `True` keeps the submitted behaviour. The search trace records `multi_sticky_witness`.
- `scripts/paper/run_fairness.py`: the config key `front_commit_witness` (default true) applies to arms with `front_commit`, and rows record it. Progress lines now start with `i/total` cells.
- `research/rebuttal/tradeoff/ablation_objectives_figure.py`: `--metric` (default `router_inserted_swaps`, so the output is unchanged) lets the same logic report `physical_depth`.
- No Rust change. In the front layer, the two settings score the same way: under front-commit every front-layer gate that is not executable is frozen, and frozen gates are scored on their frozen realization either way (`crates/src/prism_routing/ext.rs:539`, `:667-673`). Only lookahead-set scoring changes (`ext.rs:746`).

Reproduction check: with `front_commit_witness` left at its default, the old config gives the same SWAPs and depth as the old rows on 4 cells (vqe_two_local and qft, seed 0, grid and hex).

## Configs and rows

| Config | Rows | Changes from the old config |
| --- | --- | --- |
| `front_commit_swaps_isolated.toml` | 640 (grid, hex) | `front_commit_witness = false`, `tie_break = "load"`, `experiment_id` |
| `front_commit_swaps_heavyhex_isolated.toml` | 320 (heavy-hex) | the same |

All 960 rows succeeded. The workloads, seeds (0..1900, step 100), width 8, budget 40/16/40, `qiskit_sabre`, `objective = "swaps"` and `reschedule = true` are copied unchanged.

## Commands

```
research/rebuttal-r3/runs/front_commit_isolated/run.sh        # resumable: rows already in the .jsonl are skipped
F=research/rebuttal/tradeoff/ablation_objectives_figure.py
D=research/rebuttal-r3/runs/front_commit_isolated
.venv/bin/python $F --ablation $D/front_commit_swaps_isolated.jsonl $D/front_commit_swaps_heavyhex_isolated.jsonl --out $D/ablation_objectives
.venv/bin/python $F --ablation $D/front_commit_swaps_isolated.jsonl $D/front_commit_swaps_heavyhex_isolated.jsonl --metric physical_depth --out <scratch>
.venv/bin/python $F [--metric physical_depth] --out <scratch>     # old rows, for comparison
```

Run each Python command inside `systemd-run --user --scope -p MemoryMax=5G -p MemorySwapMax=0`, as `run.sh` does.

Runtime: 12.4 min wall time at 5 workers for all 960 cells (2026-11-12). The pilot (9 of the heaviest cells) took 6 s.

## Results

Percentages are total reductions against Greedy over the same 320 runs per graph (16 workloads × 20 seeds). PRISM and Greedy rows come from `artifacts/paper/raw/core_swaps.jsonl`. "Further" is PRISM against the front-commit ablation.

| Graph | SWAPs: front-commit vs Greedy, old → new | SWAPs: further gain from keeping the choice open, old → new | Depth: front-commit vs Greedy, old → new | Depth: further gain, old → new |
| --- | --- | --- | --- | --- |
| Grid | 23.3 → 24.8% | 7.6 → 5.8% | 7.8 → 10.5% | 3.5 → 0.6% |
| Hex | 20.6 → 22.2% | 7.1 → 5.2% | 8.3 → 9.1% | 2.3 → 1.4% |
| Heavy-hex | 16.2 → 17.3% | 2.7 → 1.4% | 8.2 → 7.8% | 1.1 → 1.5% |

PRISM against Greedy: SWAPs 29.1/26.2/18.5%, depth 11.1/10.4/9.2%.

Effect of the lookahead-witness flag alone (old minus new front-commit, in points of Greedy's total):
- SWAPs: 1.5/1.6/1.1 points (grid/hex/heavy-hex). The tie-break cannot change SWAP counts (`router-check.md` §6), so this difference comes from the witness flag alone. It accounts for about a quarter of the old "further" gain on grid and hex, and half of it on heavy-hex.
- Depth: 2.7/0.8/−0.4 points. This difference mixes the witness flag with the tie-break change from `default` to `load`, which affects depth, so it cannot be attributed to the witness flag alone.

Workloads where the front-commit ablation has a higher mean SWAP count than Greedy: hex `qaoa` (old: grid `vbe_ripple_carry_adder`, hex `qaoa`).

Figure: `ablation_objectives.pdf` (and `.png`) is panel (a) on the new rows. Panel (b) is unchanged. It has not been copied into `paper/`.
