# Circuit quality and postselection cost

The active bare-transmon comparison uses `bare_report.py` and `bare_figure.py`.
Read the manuscript in [../review_minimal.pdf](../review_minimal.pdf). Its sole edit source is
[../rebuttal_minimal.patch](../rebuttal_minimal.patch). Files here are experiment evidence.

Fidelity calibration was corrected on 2026-10-11. The dual-rail rows before that
date (`data/v2_*.jsonl`, device `mehta`) added background dephasing during gates
to measured gate dephasing that already includes it. The corrected rows
(`data/v3_*.jsonl`, device `mehta_idle`) charge background dephasing only while a
pair idles. Acceptance and duration are the same in both. See [MODEL.md](MODEL.md)
and the response-log entry of 2026-10-11.

## Reproduce the direct comparison

From the repository root:

```sh
.venv/bin/python research/rebuttal/wallclock/resim.py --width 8 --device mehta_idle --workers 4
.venv/bin/python research/rebuttal/wallclock/bare_report.py --simulate --workers 3
.venv/bin/python research/rebuttal/wallclock/bare_figure.py
```

The first command resumes missing exact simulations at nominal width eight.
Omit `--simulate` to rebuild the report from complete rows. It requires all 16
MQT workloads, both topologies, and five seeds. It fails on missing cells instead
of dropping workloads. VBE has seven program qubits at this nominal width; the
other workloads have eight.

- `data/bare_direct_n8.jsonl` holds exact density-matrix results at CZ average
  gate errors 0.1% and 0.3%. Each circuit is reconstructed from the winning
  transpiler seed in `data/bare_n8.jsonl`; gate counts, selection score and duration
  must match. There is no fitted fidelity correction.
- `data/v3_n8.jsonl` supplies the exact dual-rail Greedy and PRISM results
  (`data/v2_n8.jsonl` holds the superseded additive-dephasing rows, reachable with
  `bare_report.py --dualrail`). Both platforms use ideal preparation and terminal measurement. The fidelity is the
  output state's overlap with the ideal circuit state, conditional on acceptance.
  It is not the probability of a correct classical answer.
- `data/bare_report.json` and `bare_report.txt` are generated from those rows.
  `data/figures/bare_comparison.pdf` is a figure asset, not another paper draft.

Each plotted point is a workload's arithmetic mean over two topologies and five
seeds. The shot cost is mean(1/P), not 1/mean(P). The report also gives time per
retained sample as `A + B*h`, with `A = mean(D/P)` and `B = mean(1/P)`. Here `h` is
that platform's total preparation, check, readout and reset time per attempt.
It is unspecified, rather than inferred from partial timings of different
experiments. Illustrative common overheads in the text report are assumptions.
Equal retained-sample counts do not imply equal accuracy.

Both arms receive the same coupling graphs, with 20 grid sites and 30 hexagonal
sites. A site denotes one cavity rail or one bare transmon; this does not equate
control, coupler and readout hardware. Only one program is run at a time. Bare
compilation keeps the best of 80 candidates, two input transformations for each
of 40 transpiler seeds. The saved dual-rail circuits use the existing core settings.

The transmon reference is a parameter model, not a particular measured processor.
It uses T1 = 136.5 us, T2 = 89 us, single-qubit average error 2.88e-4, 25 ns
single-qubit pulses, 42 ns CZ gates, and virtual RZ. Gate relaxation is included in those average errors. `bare_report.transmon_device`
chooses the residual depolarizing strengths so the composed channels have the
specified total gate error. `bare_report.py --check` verifies that accounting.
[MODEL.md](MODEL.md) gives the derivation and parameter sources.
The direct comparison sets preparation/readout errors to zero on both sides.
[MODEL.md](MODEL.md) defines the dual-rail noise and its hardware extrapolations.

## Detector accounting

`detection.apply` remains an abstract sensitivity model. Its `f` is the probability
of flagging a *present* photon. Mehta et al.'s 6.43% and 6.79% values are total SPAM
erasure assignment, including preparation and measurement failures. They cannot
supply `f` while those failures are also charged separately. De Graaf et al.'s
0.51% false-positive rate belongs to a different mid-circuit protocol; its
conditional false-negative probability is 3.7%, not the approximately 0.09%
unconditional missed-erasure fraction.

The former combined scenarios are withdrawn as hardware predictions. The generic
sweeps remain reproducible, with their assumptions in `detection.py`; existing
`detection.txt` and `data/detection.json` are historical outputs. The direct
comparison uses ideal checks and does not claim to repair a measured detector
channel from insufficient calibration data. A full SPAM instrument and repetition
protocol remain necessary for an end-to-end hardware comparison.

The same report now includes a separate yield sensitivity. It multiplies circuit
acceptance by `(1-e)^n`, with the actual encoded-qubit count and one combined SPAM
factor per qubit. The two values of `e`, 6.43% and 6.79%, come from Mehta's two
characterized qubits; they are alternatives, not confidence bounds. This assumes
independence across qubits and from circuit loss, charges no additional
preparation/readout loss, and makes no claim about fidelity after SPAM errors.
At nominal width eight, the median attempt count becomes 2.50–2.58, with a range
of 1.84–4.27 over all workloads and both rates. The report retains the wider costs.
`bare_report.py --check` checks that the SPAM factor is charged once; the report
also checks that the same factor leaves per-workload PRISM/Greedy ratios unchanged.

## Other evidence

- `sim.py`, `run.py`, `resim.py`, `validate.py`: dual-rail simulation and checks.
- `sweep.py`, `v2_report.py`: circuit-noise sensitivity and within-dual-rail results
  through width sixteen. `v2_report.txt` documents its explicit acceptance cutoff;
  that cutoff is not used in the direct bare comparison.
- `bare.py`, `validate_bare.py`: the wider transmon sweep and validation jobs.
  Their raw rows are preserved. The active direct report does not need their
  fitted calibration or wait for the wider runs.
- `BARE_PREREG.md`, `BARE_DESIGN.md`: historical crossover design, superseded for
  reporting after preliminary results were seen. The decision and source audit
  are recorded in [../response_log.md](../response_log.md).
- `data/legacy/`: earlier device models. The legacy summary, cost and break-even
  scripts read those files. Their conclusions are not current paper claims.

No mitigation factor is inferred from state fidelity, no hypothetical parallel
copies are charged, and no workload is excluded for low acceptance.
