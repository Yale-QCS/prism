# Excluded workloads on heavy-hex (§V-A)

`artifacts/paper/raw/excluded_swaps.jsonl` (config `research/rebuttal/suite/swaps/excluded_swaps.toml`) covers grid and hexagonal lattice only. These rows add heavy-hex for the same nine workloads.

`excluded_swaps_heavyhex.toml` is a copy of `excluded_swaps.toml` with two changes: `experiment_id = "excluded_swaps_heavyhex"` and `topologies = ["heavy_hex"]`. Width 8, seeds 0..1900 (step 100, 20 seeds), budget 40/16/40, `qiskit_sabre`, `tie_break = "load"`, `objective = "swaps"`, `reschedule = true` and the Greedy and PRISM arms are unchanged.

## Command

```
research/rebuttal-r3/runs/excluded_heavyhex/run.sh    # from the repository root; resumable
```

It runs `scripts/paper/run_fairness.py` at 5 workers inside a 5 GB `systemd-run` scope. Run 2026-11-13: 360 rows (9 workloads × 20 seeds × 2 arms), all succeeded, 38 s wall time.

## Result

Routing SWAPs per run (`router_inserted_swaps`), 20 runs per entry:

| Workload | Greedy max | Greedy mean | PRISM max | PRISM mean |
| --- | --- | --- | --- | --- |
| bv | 2 | 0.65 | 1 | 0.50 |
| ghz | 3 | 1.25 | 3 | 1.40 |
| graphstate | 4 | 3.05 | 3 | 3.00 |
| bmw_quark_cardinality, ghz_dynamic, qnn, vqe_real_amp, vqe_su2, wstate | 0 | 0.00 | 0 | 0.00 |

Maximum over both arms: heavy-hex 4 (Greedy, graphstate), PRISM alone 3. For comparison, the existing rows give grid 0 and hexagonal 2 (Greedy and PRISM each reach 2: Greedy on graphstate, PRISM on ghz).
