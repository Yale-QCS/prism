# railx: the rail-X fix check (9cb6c53)

`option_a.py` compiles each `core` cell with and without the physical stage's `ConsolidateBlocks`, which put rail X and other gates outside the one-photon-per-pair space into routes. `data/option_a.jsonl` has 276 rows compiled after 9cb6c53 removed it, and none of them has rx, an unlabeled x, or a gate that leaves that space.
