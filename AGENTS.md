# Project instructions

prism is a Qiskit 2.5 transpiler for encoded (dual-rail) circuits. It carries each gate's realization set across the lowering boundary and binds one realization at routing time. This branch is the tool release and contains only the PRISM method. The HPCA paper artifact, with its baselines, ablations, evaluation pipeline and the `paper/` submodule, is on the `hpca-r1` (as submitted) and `hpca-r2` (rebuttal) branches.

Research notes, side-experiment scripts and their data are in `research/`, which lint skips. `research/notes/qiskit25_plan.md` holds the Qiskit 2.5 refactor plan, and `research/notes/qec_codes.md` holds the error-correcting-code experiments.
