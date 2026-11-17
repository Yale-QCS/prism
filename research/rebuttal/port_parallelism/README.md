# port_parallelism: the two-port depth floor of a dual-rail qubit (2026-06)

`floor_theorem.md` proves that an all-commuting CRz layer whose demand graph has maximum degree Δ needs exactly ⌈Δ/2⌉ steps when each rail is a port, and `verify_port_parallelism.py` checks it by construction. `measure_README.md` records whether the router used the two ports (its script used a removed API), and `notes.md` is the 2026-06-09 motivation.
