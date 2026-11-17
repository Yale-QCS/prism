# ERADO feasibility probe (X09)

Cross-checks the analytic acceptance model against ERADO
(github.com/oqc-community/erado, v1.1.0), the Aer-based erasure-noise +
postselection simulator behind the "limits of erasure-based postselection"
paper the eval already cites.

Result (2026-07-16, qft n=8 grid seed 42, Gamma=1e-5/ns, 300 shots, seed 0):

| circuit | simulated acceptance | analytic exp(-G*sum_T) | qubit-time |
|---|---|---|---|
| greedy-compiled | 0.743 | 0.774 | 25650 ns |
| prism-compiled | 0.787 | 0.792 | 23270 ns |

Direction and magnitude agree with the analytic proxy within binomial error;
prism's shorter routes buy higher acceptance, as claimed. Verdict: FEASIBLE.

Integration facts:
- Circuits stay ISA-formed. Erasure sampling keys on gate names (crz 500 ns,
  swap/rswap/x 170 ns, rz free) via a 10-line `ErasureCircuitSampler` subclass;
  erado upstream supports only a uniform rate and would otherwise charge rz.
- `RSwapGate` now carries an exact `rxx(t/2)+ryy(t/2)` definition (tested,
  compiler-inert) so the Aer execution boundary can translate it; the
  `TranspilingBackend` shim confines translation to `backend.run`.
- erado's linux dep pins `qiskit-aer-gpu-cu11`; install in a separate venv with
  `pip install --no-deps erado` plus `qiskit==2.4.1 qiskit-aer pydantic numpy
  scipy`. The frozen paper venv is untouched.
- Cost: ~1 s/shot at 16 rails on CPU statevector (erado runs one circuit per
  shot). A full X09 subset (4 circuits x 2 strategies x 1000 shots) is a few
  CPU-hours or a GPU run. False-positive/false-negative rates are constructor
  knobs, giving the sampling-overhead vs accepted-fidelity separation directly.

Run: create the venv as above, then from this directory
`<erado-venv>/bin/python probe.py` (frozen probe circuits are the two .qpy
files; regenerate with the marabbecca pipeline if the compiler changes).
