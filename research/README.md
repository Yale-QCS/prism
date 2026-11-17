# Research

Scripts, results and notes behind the paper and its revisions. Superseded work and dead ends (teleport, cadence, reshape, the June to July evaluation versions, the campaign boards) are not part of this branch.

Run the scripts from the repository root with `.venv/bin/python`.

## theory/

The §3 claims.

- `verify_realizations.py`: the four CR_z realizations, SWAP, X and RZ are exact logical gates. The init herald CRZ(π) is logical S†, not identity.
- `verify_gateset.py`: the delocalized one-qubit gate set is O(2) = {Rz} ∪ {Rz X} (Eq. delocal-group, Fig. weyl-sweep).
- `verify_graph_claims.py`: the availability-graph degree is at most 2Δ, and K_6 on the 2×6 ladder needs every qubit delocalized (Fig. availability-graph).
- `k6_ladder_witness.py` with `embed_search.py`: an explicit K_6 witness on the 2×6 ladder.
- Notes: `brod_galvao_can_closed_form.md` (Weyl coordinates of M(A,B)), `realization_corrections.md`, `rswap_swap_power_convention.md`, `init_crz_herald.md`, `xonrail_cancelrailx.md`, `prop1_and_unification.md` (availability graph = quotient), `quotient_embedding.md`, `separation_cadence_bound.md`, `s3_theory_verification.md`, `verification_2026-06-26.md`.

## ablations/

§5.1 workload exclusions and §5.3 ablations. `results.md` has the numbers and the open rebuttal items.

- `report.py` recomputes the §5.1, §5.3 and per-run §5.2 numbers from `artifacts/paper/raw/` (the ablation files against `core.jsonl`) and the §5.4 numbers left as arithmetic on the device export.
- The `.toml` files (`front_commit`, `tiebreak`, `slack`, `excluded`, `randomcircuit`) configure all five runs for `scripts/paper/run_fairness.py`, including the `prism_front_commit` arm and the `grid_25`/`grid_36` larger-grid topologies.
- `check_excluded_workloads.py` checks that the nine excluded workloads need no routing. `exclusion_rule.md` gives the rule.

## rebuttal/ and rebuttal-r3/

Experiments, each with a README that gives its pre-registration, rows and scripts:

- `suite/`: the primary 25-workload suite of §5.1–5.2 (16 MQT Bench algorithms, MQT's randomcircuit, eight QASMBench circuits). `suite/swaps/` holds the SWAP-selected re-run that supplies the current numbers.
- `scale/`: loss-exponent and shot-overhead analysis from 8 to 32 logical qubits. `HEADLINE.md` is a historical analysis, not current manuscript text.
- `s53/`: the §5.3 ablations re-run on the J-selected suite (25 workloads, three graphs). History. The submitted ablation numbers come from `suite/swaps/`.
- `hardware/`: Section V-D, the two device models, Eqs. 17–19, their check against simulation, and Fig. 12.
- `sensitivity/`: PRISM's loss margin over Greedy across cavity T1 and beamsplitter duration (B-2, D-5). `hardware/` reads its loss-part and dephasing rows for Fig. 12.
- `wallclock/`: the device models (`MODEL.md`), direct bare-transmon comparison (`bare_report.py`), and dual-rail simulation through width sixteen. Its README identifies the active analysis and withdrawn detector interpretations.
- `outer_qec/`: the corrected Steane memory experiment under ideal heralded erasures, including the decoder audit. Only `data/ideal_erasure_v2/` supplies current results; v1 is superseded audit evidence.
- `tradeoff/`: SWAPs against duration at 16 logical qubits under each route-selection objective (R3).
- `oracle/`: exact search from fixed layouts, PRISM and Greedy against optimal (A-Q2, D-Q2).
- `myopia/`: whether commitment shapes later routing (A-Q2, D-Q2), an argument with no new compiles.
- `mechanism/`: whether circuit structure predicts the per-workload gain (it does not).
- `time_aware/`: time-aware SWAP cost (R4).
- `objective_success/`: route selection by overall success, −log(P_keep · F_cond).
- `commutation/`: design study for commutation-aware PRISM.
- `port_parallelism/`: the ⌈Δ/2⌉ depth floor for commuting CR_z layers (a theorem, not claimed in the paper).
- `railx/`, `erado_probe/`: the rail-X option study and an ERADO cross-check of the acceptance proxy (needs `erado` and `qiskit_aer`, not in `.venv`).
- `q4_stabilizer_proto.py`: rep-code and surface-code d=3 prototype (stdout only).

`background/` holds the pre-submission notes (June and July 2026): the prior-work comparison and in-loop evidence (why Greedy stands in for placement-time binding), the harsh and research reviews, the citation check and the near-neighbor sweep. Their numbers predate the re-run.

## references/

Citation ledgers (`background_refs.md`, `classical_compilation_refs.md`, `iceberg_multireal_competitors.md`, `teleport_routing_priorart.md`), the Mehta dual-rail noise parameters, venue and evaluation conventions, quantikz figure notes, and `pipeline_layout_gotcha.md` (the routed layout is not `property_set["layout"]`).

## benches/

- `quick_bench.py`: five circuits at n = 8, Logical-SABRE, Greedy and PRISM.
- `full_bench.py`: the same over every benchmark circuit.
- `faithfulness.py`: statevector check of routed output for DualRail, RepCode and Iceberg.

## Read first

1. `ablations/results.md`
2. `theory/brod_galvao_can_closed_form.md`, then `theory/realization_corrections.md`
3. `theory/prop1_and_unification.md`
4. `references/dualrail_noise_mehta_sws.md` (its fidelity percentages are superseded by §5.4)
5. `rebuttal/review_minimal.pdf`, then `rebuttal/response_log.md`
6. `rebuttal/port_parallelism/floor_theorem.md`
