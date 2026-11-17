# Outer-code proof of concept

The active experiment is [mehta_memory.py](mehta_memory.py). It uses the same
`wallclock.sim.MEHTA_IDLE` device as the postselection and bare-transmon study.
The parameter definitions and their sources are in
[the shared model specification](../wallclock/MODEL.md). There is no separate
QEC hardware calibration or adjustable noise multiplier.

The experiment compiles three-round Steane memories in X and Z bases on grid
and hexagonal connectivity. qLDPC supplies the memory circuits, Stim samples
the routed circuits, and `ldpc.BpOsdDecoder` corrects each shot using its
syndrome and erasure locations. It uses the library's documented serial
product-sum BP with seven iterations and OSD-CS order two. The outcome is wrong decoded logical
measurements divided by shots. Shots with erasures are decoded, not discarded.

X and Z memory test phase and bit preservation. Their source circuits contain
the same 72 two-qubit interactions; X memory adds data-basis Hadamards at
preparation and readout. Each complete circuit is compiled separately. Basis
simplification changes native control/target assignments and gate ordering,
so these tests do not hold the physical route fixed. Differences between
their failure rates include both the noise asymmetry and the selected routes.

Both compilers use the same 40/16/40 search budget, seeds 0 through 1900 in
steps of 100, and no final rescheduling. Each of the 160 circuits receives
50,000 shots at the nominal device point. The route-selection score is minus
the log probability of no erasure or residual-Z channel event. It consumes
the same scheduled channels as the simulator, including gate/role dependence,
idle loss and idle dephasing. This is a physical-fault proxy, not a decoder
inside the router. Default SWAP selection elsewhere in the paper is unchanged.

The score uses the channels underlying Eqs. 17 and 18, not their product
literally. For an idle interval of length `t`, the simulated probability of no
Z event is `(1 + exp(-2*gamma*t))/2`; Eq. 18 uses `exp(-gamma*t)` as a lower
bound. Replacing the former by the latter changes the saved route scores by
less than 0.00045%. The channels and selected routes are unchanged. This check
does not establish that the two scores select identical routes from all
candidates. Table I rounds the displayed parameters only; the simulations
retain the original shared values.

Preparation, readout, erasure detection and immediate replacement remain
ideal, with no check or replacement time. Constituents accrue noise between
preparation/reset and readout. The shared device also extends the measured
intra-pair beamsplitter rates to routing SWAPs. These assumptions limit the
experiment to a hardware-informed proof of concept; it is not a prediction
for a complete physical QEC implementation.

## Physical-transmon control

`bare_memory.py` runs the same Steane memories with one physical transmon per
constituent. It imports `wallclock.bare_report.transmon_device` at the same
0.1% and 0.3% CZ-error points as the existing bare-qubit study. Stim uses the
Pauli twirl of that thermal channel, preserving its Pauli-transfer diagonal
and average gate fidelity but omitting the nonunital relaxation term. Gate
durations, coherence times and calibrated residual depolarization are unchanged.
The channel check compares the twirl with the full Kraus channel and checks
six small noisy circuits against density-matrix evolution.

Both implementations use the same available site graphs. Seven data and six
check constituents require thirteen transmons or twenty-six cavity rails;
spare sites remain available for routing. The transmon arm uses native Qiskit
O3 with its built-in Clifford synthesis and selects among eighty candidates at the nominal 0.3% CZ error, then
evaluates that route at both error points. Its decoder uses the same library
and settings, with no erasure flags. Each route receives 50,000 shots per point.

This compares one extraction circuit across constituent types. Its unflagged
Pauli faults can have identical syndromes and different logical effects.
The comparison therefore includes the usefulness of erasure information in
this circuit; it does not compare optimized fault-tolerant implementations
or establish a platform ranking. Ideal preparation/readout and ideal immediate
dual-rail erasure recovery remain explicit assumptions. The circuit-only
duration excludes preparation, measurement and recovery costs.

## Reproduce

Use Qiskit 2.4.1 and the repository's built extension, with `stim==1.16.0`,
`qldpc==0.4.1` and `ldpc==2.4.1`. Set `QEC_PYTHON` to that environment's Python
executable. The workspace interpreter is recorded in
[the response log](../response_log.md).

From the repository root:

```sh
export OPENBLAS_NUM_THREADS=1 RAYON_NUM_THREADS=1 QISKIT_PARALLEL=FALSE
export NUMBA_CACHE_DIR=/tmp/prism-qec-numba MPLCONFIGDIR=/tmp/prism-matplotlib
mkdir -p research/rebuttal/outer_qec/data/mehta_memory
"$QEC_PYTHON" research/rebuttal/outer_qec/mehta_memory.py --check > research/rebuttal/outer_qec/data/mehta_memory/validation.json
"$QEC_PYTHON" research/rebuttal/outer_qec/mehta_memory.py --tasks > /tmp/prism-mehta-qec-tasks
xargs -r -P 2 -n 8 "$QEC_PYTHON" research/rebuttal/outer_qec/mehta_memory.py < /tmp/prism-mehta-qec-tasks > research/rebuttal/outer_qec/data/mehta_memory/run.log 2>&1
"$QEC_PYTHON" research/rebuttal/outer_qec/mehta_report.py --audit
.venv/bin/python research/rebuttal/outer_qec/mehta_report.py
```

To add the physical-transmon control to that same report and figure:

```sh
"$QEC_PYTHON" research/rebuttal/outer_qec/bare_memory.py --check > research/rebuttal/outer_qec/data/mehta_memory/transmon_validation.json
"$QEC_PYTHON" research/rebuttal/outer_qec/bare_memory.py --tasks > /tmp/prism-transmon-memory-tasks
xargs -r -P 8 -n 6 "$QEC_PYTHON" research/rebuttal/outer_qec/bare_memory.py --prepare-only < /tmp/prism-transmon-memory-tasks > research/rebuttal/outer_qec/data/mehta_memory/transmon_prepare.log 2>&1
xargs -r -P 8 -n 6 "$QEC_PYTHON" research/rebuttal/outer_qec/bare_memory.py < /tmp/prism-transmon-memory-tasks > research/rebuttal/outer_qec/data/mehta_memory/transmon_run.log 2>&1
"$QEC_PYTHON" research/rebuttal/outer_qec/mehta_report.py --audit-transmon
.venv/bin/python research/rebuttal/outer_qec/mehta_report.py
```

Once any transmon rows exist, the report requires all eighty routes, both
noise points and the independent channel/decoder audits. It refuses to
publish a partial comparison. All controls stay in `data/mehta_memory/`.
The transmon audit also computes the exact optimal failure probability from
Stim's joint syndrome/logical distribution on the eight seed-zero circuits.
That check measures the scope for a better decoder; sampled ldpc outcomes
remain the primary result.

The incomplete generic-synthesis control is archived in
`data/mehta_memory/transmon_generic_synthesis_audit.tar.gz`. One of its routes
contained a non-Clifford native gate and was correctly rejected by Stim.
The active control recompiles every route with Qiskit's Clifford synthesis;
no route is removed or gate angle rounded to fit the simulator.

`--tasks` lists missing cells. Existing results are not overwritten. The report
requires every prescribed cell and checks their parameters, source hashes and
validation records. It writes one `report.txt`, `summary.json` and
`comparison.png` in `data/mehta_memory/`. Paired bootstrap intervals resample
routing seeds; they do not describe uncertainty in the hardware assumptions.

Each cell saves its physical QPY circuit, noiseless and noisy Stim circuits,
full device definition, noise locations, fault signatures, versions, source
hashes and actual error counts. Every cell checks its noiseless measurements
and independently verifies each X/Z fault signature with Stim. The decoder
receives only the syndrome and erasure flags. Residual-Z probabilities enter
its prior; the recorded logical outcome is used only to score its answer.
Every route must pass an exhaustive check that all supported single residual
faults are distinguishable and correctly decoded. Decoder settings follow
[the ldpc quantum-decoding example](https://software.roffe.eu/ldpc/quantum_decoder.html).
The `--check` command compares acceptance, conditional fidelity and duration
against the existing exact device simulator on small circuits with overlapping
operations and routing SWAPs. The reporter's `--audit` mode checks the mixed
channel's detector and observable probabilities against their analytic values,
then checks the library decoder against recoverability in the erasure-only
limit. These validation shots are separate from the performance estimates.

## Historical experiments

`erasure_pilot.py`, `erasure_report.py` and `data/ideal_erasure_v2/` retain the
old uniform-erasure study for reproduction. It used one probability per
active operation, ideal idles and no residual errors, while route selection
used a postselection-only proxy. Its numbers must not be called Mehta results.
A Mehta operating point cannot be placed on that one-dimensional uniform-p
curve. Any future sensitivity study must vary the shared model explicitly.

The first Mehta decoding pass used parallel BP with OSD-0 and failed some
recoverable single residual faults. The corrected report uses serial BP and
OSD-CS for every route, with unchanged hardware and Stim sampling seeds.
Each updated row retains the old counts under `osd0_audit`. The one-time
`mehta_report.py --redecode ARM` migration also verifies that the saved QPY
regenerates the same noise circuit. New `mehta_memory.py` runs use the corrected
decoder directly. These are decoder audit records, not alternative hardware results.

The old `--audit-ldpc` mode checks the uniform-erasure decoder on 1.2 million
actual noisy Stim samples. `flag_control.py` measures the effect of withholding
erasure locations under that same old channel. Its large effect partly
reflects an extraction circuit that relies on flags for single-fault recovery;
it is not a transmon comparison. `data/ideal_erasure_v1/` also omitted useful
readout constraints and is superseded audit evidence.

`qec_circuits.py`, `route.py` and `to_stim.py` provide reused circuit/routing
helpers. Their original command-line postselection experiments are historical.
Decisions, results and reviewer responses belong in `../response_log.md`.
Manuscript changes remain in the sole `../rebuttal_minimal.patch`, rendered as
`../review_minimal.pdf`; replacement experimental results await author review.
