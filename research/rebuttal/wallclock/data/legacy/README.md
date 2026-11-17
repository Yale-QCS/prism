# Legacy rows (superseded)

These rows come from the `sim.LEGACY` device: 500 µs cavity T1, loss as cavity decay plus an optional CR_z coupler term, with the transmon arms. The calibrated `sim.MEHTA` rows in `data/v2_*.jsonl` (`MODEL.md` §2) replace them. They are kept so that the superseded numbers in `ARGUMENT.md`, `../../../archive/rebuttal_letter_pre_minimal.md` and `response_log.md` stay reproducible.

| File | Run | Fed |
|---|---|---|
| `rows_n8.jsonl` | `run.py --width 8`, no coupler loss, representative transmon | `figure.py`, `summary.py`, `resim.py` input |
| `rows_n8_loss0.jsonl`, `rows_n12_loss0.jsonl` | `resim.py --loss 0` | exp(−nD/T1) check (`ARGUMENT.md`) |
| `rows_n8_loss0.002.jsonl`, `rows_n12_loss0.002.jsonl` | `resim.py --loss 2e-3` | P1 transmon sampling-cost figures (`costs.py`, `figure_width.py`, `figure_prism_greedy.py`, `breakeven_*.py`) |
| `rows_n12.jsonl` | `run.py --width 12`, representative transmon | `resim.py` input, P1 n = 12 |
| `rows_n12_strong_transmon.jsonl` | `resim.py`, best-case transmon | P1 n = 12 best-case point |
| `sweep_n8.jsonl` | `sweep.py` (LEGACY variants) | H1 sweep table (`sweep_table.py`), the n = 8 best-case transmon |
| `breakeven_n8.jsonl` | `breakeven.py`, 222 rows; the run was stopped | Break-even plane (`README.md`, "Break-even transmon"); never reported |
| `figures/p1_width.{pdf,png}`, `figures/p1_width_paper.{pdf,png}` | `figure_width.py --tag _loss0.002` | The historical P1 width figure cited by `ARGUMENT.md` |

The 15-row `rows_n16.jsonl`, compiled from the invalid 2026-10-06 circuits and not referenced anywhere, was deleted.

The LEGACY figure scripts (`figure.py`, `figure_width.py`, `figure_prism_greedy.py`, `breakeven_figure.py`) write to `figures/` here. `p1_fidelity_wallclock` and `p1_prism_greedy`, which nothing cited, were deleted.
