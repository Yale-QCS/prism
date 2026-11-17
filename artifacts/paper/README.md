# Paper artifacts

Outputs of `scripts/paper/` that the paper uses.

- `raw/`: JSON Lines, one row per compiler run, each file named after its config's `experiment_id`. Each row records its route-selection `objective`.
  - `*_swaps.jsonl` (`objective = "swaps"`): the re-run of 2026-10-11 in `research/rebuttal/suite/swaps/`. These supply the submitted revision's suite, ablation and scaling numbers. `logical*.jsonl` supplies the Logical-SABRE reference.
  - Every other PRISM and Greedy file was selected by J (`objective = "error"`) and is supporting history: the 2026-10-06 runs of `configs/paper/` and `research/ablations/` (`core`, `scale`, `front_commit`, `tiebreak`, `slack`, `excluded`, `randomcircuit`), the earlier suite (`breadth`, `*_seeds80`, `*_seeds64`, `research/rebuttal/suite/`) and its §5.3 re-run (`s53_*`, `research/rebuttal/s53/`).
  - `objective_{swaps,depth,duration}`, `reschedule_off` and `commute_best`: the objective and rescheduling study (`research/rebuttal/commutation/`).
  - `suite_unsupported.jsonl`: the cc runs that every arm rejected (`research/rebuttal/suite/README.md`).
- `paper_export/`: `core/`, `scaling/`, `device/`, `suite/`, `s53/`, `breadth/` and `suite34/`, the exports that the figures and the macro generator read.
- `manifests/circuits/`: the frozen benchmark circuits (QPY) that the runners load.
- `quick/` and `quick_export/` (untracked): output of `make quick`.

Earlier versions, audits and summaries are in the `revision-r1` branch under `archive/`.
