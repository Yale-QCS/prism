# Section V-D hardware evaluation

Everything behind Section V-D and Fig. 12 of `../review_minimal.pdf`: the two device models, Eqs. 17–19, the check of those equations against simulation, and the figure. Built 2026-10-11 (prism-85, with Evan). Decisions and numbers are logged in `../response_log.md`.

## Models and equations

- Dual rail: `sim.MEHTA_IDLE` (`../wallclock/MODEL.md`), measured parameters of Mehta et al.
- Transmon: `bare_report.transmon_device` (`../wallclock/MODEL.md`, "Direct bare-transmon model"). The paper prints rounded values; the simulated values are unchanged.
- Eq. 17: P_keep = exp(−I/T1) Π_g (1−e_g)^K_g. I is the summed pair idle time.
- Eq. 18: F_DR = e^{−γI} Π_g (1−ε_g)^N_g, with the same I. It is a lower bound on simulated retained-shot fidelity.
- Eq. 19: F_T = exp[−I_T(1/4T1 + 1/2T2)] Π_g (1 − (d_g+1) r_g / d_g)^N_g. It is a lower bound on simulated transmon fidelity.

## Data (all SWAP-selected, `core_swaps.toml` settings, 16 MQT workloads × 5 seeds)

- Dual-rail circuits and rows. Grid and hex: `../wallclock/data/swaps/{circuits_n*,v2_n*.jsonl,v3_n8.jsonl}` (prism-66). Heavy-hex: `../wallclock/data/swaps/heavy_hex/`, compiled with `../wallclock/run.py --topologies heavy_hex --arms greedy prism --device mehta --measured` (exact simulation at n = 8, 8 trajectories at 12 and 16 because only P_keep is used there).
- Loss parts per beamsplitter duration: `../sensitivity/data/swaps/parts_n*.jsonl` and `.../heavy_hex/parts_n*.jsonl` (`../sensitivity/extract.py`).
- Transmon compiles: `../wallclock/data/bare_n*.jsonl` (grid and hex) and `../wallclock/data/swaps/heavy_hex/bare_n*.jsonl` (`bare_heavyhex.py`, because `bare.py` runs grid and hex only). Exact transmon simulation at n = 8: `../wallclock/data/bare_direct_n8.jsonl`.
- Trajectory fidelity at n = 16, measured device: `../sensitivity/data/swaps/dephasing_n16.jsonl` (rows with tphi_ms ≈ 2.18).

## Scripts (run from the repository root with `.venv/bin/python`)

| Script | Output | Purpose |
| --- | --- | --- |
| `equations.py` | `out/rows.jsonl`, `out/results.json` | Eqs. 17–19 per saved circuit at n = 8, 12, 16 |
| `proxy_check.py` | `out/proxy_check.json` | Eq. 18 vs trajectories at n = 16, Eq. 19 vs exact transmon at n = 8 |
| `section_numbers.py` | `out/numbers.json` | every Section V-D number: shot-overhead saving (geometric mean and median), duration, exchanges, keep probability, beamsplitter sensitivity |
| `figure.py` | `figures/eval_hardware.{pdf,png}` | Fig. 12 |
| `bare_heavyhex.py` | `../wallclock/data/swaps/heavy_hex/bare_n<w>.jsonl` | heavy-hex transmon compiles |
| `wallclock_cost.py` | `out/wallclock.json` | time-to-precision ratios against the transmon (Section V-D, B-1/B-Q) |
| `medians.py` | `out/medians.json` | median-workload attempts and retained-shot fidelity at n = 16 for both compilers, under each hardware variation and detection efficiency (Section V-D sensitivity) |
| `residual2x.py` | printed | median retained-shot fidelity at n = 16 with every unflagged gate error doubled (0.818 → 0.760 PRISM, 0.807 → 0.747 Greedy) |

## Results (n = 16, three graphs unless stated)

- Eq. 17 equals the simulated acceptance on every circuit (to 1e−12).
- Eq. 18 overstates infidelity by a median factor of 1.58 at n = 8 (exact, every circuit below the simulation) and 1.75 at n = 16 (trajectories, every circuit within 2 SE). Eq. 19 overstates it by 1.24 and 1.20 (CZ 0.1%, 0.3%), below the simulation on all 320 circuits.
- Shot-overhead saving: geometric mean of per-(workload, graph) PRISM/Greedy ratios 44.3% (grid 41.8, hex 42.9, heavy-hex 48.1), median 25.4%. At n = 8 and 12: 3.8% and 19.3%.
- Sensitivity at n = 16 (geometric mean): beamsplitter 2× faster 37.1%, 2× slower 57.0%; beamsplitter erasure 2× lower 41.0%, 2× higher 50.5%; cavity lifetime 2× longer 29.4%. CR_z erasure and check/readout rejection cancel exactly.
