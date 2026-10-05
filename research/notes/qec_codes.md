# Prism on error-correcting codes

Notes from 2026-09-03. Question: does prism hold up on QEC syndrome-extraction
circuits, which are the realistic dual-rail workload, rather than only on the
mqt.bench NISQ set? Scripts in `research/scripts/qec/`, raw rows in
`research/data/qec/*.jsonl` (untracked).

## Target architecture (literature)

- Teoh et al., arXiv:2212.12077 (PNAS 2023), Fig. 6: unit cell = 2 cavities,
  1 transmon, 3 beamsplitter couplers (1 intra-qubit, 2 to neighbors). The
  cavity graph is a honeycomb; contracting each dual-rail pair gives a square
  lattice of qubits. ZZ/CZ needs one cavity from each qubit, so the rotated
  surface code sits on it with no routing, provided the compiler picks the
  right rail per gate. This is `hex_lattice` in `make_topologies`.
- Chang, Singh, Claes, Sahay, Teoh, Puri, arXiv:2408.00842: erasure check
  after every 2Q gate, built into a modified ZZ; half the cells need no
  transmon (3.5 transmons/cell). Threshold ~4.2% vs ~1% Pauli.
- Gu, Retzker, Kubica, arXiv:2312.14060: dual-rail ZZ parity measurement is
  native, so CSS honeycomb Floquet codes on 3-valent lattices are the other
  natural fit. Gu, Vaknin, Retzker, Kubica, arXiv:2408.00829: sparser erasure
  check schedules, one-way reset pulses.
- Kubica et al. PRX 13, 041022; Levine et al. (AWS) PRX 14, 011051; Huang et
  al. arXiv:2504.12099; Chadwick et al. "Erasure Minesweeper" arXiv:2505.00066:
  transmon dual-rail, 3 transmons per erasure qubit, degree-4 grid.
- Mehta et al. arXiv:2503.10935 / Nature 2026: SWS CZ ~500 ns, 0.5% erasure.
  QCI/D-Wave roadmap 17, 49, 181 dual-rail qubits (d = 3, 5, 9).
- qLDPC on local hardware, all hand-scheduled: Berthusen et al. arXiv:2404.17676,
  Zhao/Yan/Ni arXiv:2509.00850, directional codes arXiv:2507.19430, directional
  tile codes arXiv:2606.19482, HAL arXiv:2507.23011. They reject generic SWAP
  routing because a transmon SWAP is 3 CNOTs; on dual-rail a rail SWAP is one
  beamsplitter. Evan's toric-network BB routing paper is arXiv:2604.18714.
- Violaris et al. arXiv:2601.02183 (perspective) lists erasure-aware compilers
  as an open tooling gap.

## Circuits

All single-round unless noted, one fresh ancilla per check, X checks as
H-sandwiched CNOTs, Z checks as data-to-ancilla CNOTs. Builders in
`qec_quick.py` and `qec_rounds.py`.

| name | logical qubits | notes |
|---|---|---|
| surface_d3 / d5 | 17 / 49 | rotated, standard 4-step schedule |
| ls_merge_d3 | 41 | 3x7 merged patch = lattice-surgery merge round |
| honeycomb_2x2 | 35 | CSS honeycomb, 3 rounds, ancilla scheme |
| steane_cnot | 26 | two Steane encoders, transversal CNOT, one round each |
| bb_18_4_4 | 36 | BB code, l=m=3, A=1+x+y, B=1+y+x^2y (brute-force verified d=4); naive serial schedule, so depth is an upper bound |
| surface_d3_r3, bb_18_4_4_r3 | 17, 36 | 3 rounds, ancilla measure + reset in place |
| ls_split_merge | 41 | separate round, merged round, separate round; ancilla keyed by absolute plaquette |

Topologies from `run_experiment.make_topologies(n)`: grid, hex_lattice,
heavy_hex, chain, sized to 2(n+1) rails. Arms: quotient SABRE, greedy
(early commit), prism (retained set). Budget scale b = layout starts = swap
trials, refinement iterations = b/2.

## Results

Single round, b=40, swaps / duration in us (seeds identical unless a range):

| circuit | topo | quotient | greedy | prism |
|---|---|---|---|---|
| surface_d3 | hex | 9 to 28 / 4.6 to 5.6 | 6 / 4.1 | 10 / 2.9 |
| surface_d3 | grid | 9 to 12 / 3.2 | 1 / 3.2 | 2 to 4 / 2.8 to 3.9 |
| bb_18_4_4 | hex | 525 / 33 | 379 / 30 | 307 / 22 |
| bb_18_4_4 | grid | 356 / 24 | 293 / 22 | 247 / 20 |
| bb_18_4_4 | heavy_hex | 1070 / 46 | 493 / 28 | 433 / 21 |
| steane_cnot | hex | 261 / 26 | 177 / 19 | 149 / 16 |
| steane_cnot | grid | 132 / 16 | 135 / 18 | 111 / 14 |
| steane_cnot | heavy_hex | fail (24 slots < 26) | 258 / 19 | 223 / 17 |
| ls_merge_d3 | hex | 102 / 7 | 107 / 7 | 83 / 6 |
| ls_merge_d3 | grid | 74 / 6 | 63 / 7 | 37 / 5 |
| ls_merge_d3 | heavy_hex | 329 / 14 | 132 / 6 | 112 to 138 / 7 |

Single round, b=8: surface_d5 hex 189 / 232 / 217, grid 93 / 142 / 97
(quotient / greedy / prism); honeycomb_2x2 hex 50 to 57 / 71 to 83 / 58 to 72;
surface_d3 chain 87 / 82 to 85 / 77.

Three rounds with in-place reset, b=8:

| circuit | topo | quotient | greedy | prism |
|---|---|---|---|---|
| surface_d3_r3 | hex | 0 to 54 | 80 to 85 | 56 |
| surface_d3_r3 | grid | 0 to 22 | 29 | 12 to 20 |
| surface_d3_r3 | heavy_hex | 262 to 286 | 124 to 141 | 93 to 107 |
| bb_18_4_4_r3 | hex | 2495 to 2569 | 1376 | 1105 to 1119 |
| bb_18_4_4_r3 | grid | 1702 to 1707 | 1040 to 1072 | 806 to 850 |
| bb_18_4_4_r3 | heavy_hex | 4888 to 4955 | 1793 to 1900 | 1479 |
| ls_split_merge | hex | 274 to 308 | 292 | 187 |
| ls_split_merge | grid | 194 to 203 | 267 | 212 |
| ls_split_merge | heavy_hex | 888 to 923 | 464 | 445 |

## Exact embedding check (`embed_search.py`)

rustworkx VF2 of the logical interaction graph into the pair quotient of the
rail lattice, one direction-class pairing at a time (milliseconds).

- surface_d3, surface_d5, ls_merge_d3, honeycomb_2x2 all embed in hex_lattice.
  Pinned as the identity start, greedy and prism both return 0 swaps, and stay
  at 0 over 3 rounds with in-place reset. Cold starts miss it every seed
  (prism 10, greedy 6 on d3 hex at b=40): a layout-search miss, not chance.
- grid: the aligned-domino quotient of an s x s rail grid is s x s/2, so
  surface_d3 needs a 10x10 rail grid (default sizing gives 6x6); d5 does not
  embed even at 12x12. Hex has no aspect-ratio loss, which is why Teoh's
  lattice is hexagonal.
- heavy_hex: degree-3 nodes are pairwise non-adjacent, so a rail pair has
  external degree <= 3. No degree-4 code ever embeds; routing is mandatory.
- steane_cnot (deg 10) and bb_18_4_4 (deg 6) embed nowhere.

## Findings

1. Planar codes are a layout problem, not a routing one. Where the embedding
   exists prism keeps it; it does not find it. A VF2-on-quotient start
   (Qiskit O3 pattern: VF2Layout, then SABRE) would close every planar cell.
   VF2 itself is not a contribution.
2. Non-planar codes and non-native lattices are where prism wins: 12 to 25%
   fewer swaps than greedy, 10 to 40% shorter cycles, up to 2.3x fewer swaps
   than quotient SABRE, in single- and multi-round settings.
3. Pinned ancilla reuse amortizes: surface_d3 ~19 swaps/round over 3 rounds vs
   30 for one cold round; BB flat at ~370/round. The router leaves each
   ancilla where its check needs it next.
4. "Floating" ancillas emulated by renaming each reset to a fresh logical
   qubit are 2 to 4x worse everywhere. That measures rail inflation (every
   reuse becomes a statically bound pair), not the re-hosting freedom.
5. Practical-arm results are identical across seeds: the dense/identity
   starts dominate, the random start pool contributes nothing here.
6. Herald constraint on reset costs little (BB hex 1105 -> 1082 with local
   prep; surface 56 -> 23 to 41; lattice surgery noisy).

## Code changes

- `DualRail.reset` now lowers to the in-place `initialize` template (labeled X
  + joint_herald on the same rails). Test `test_reset_is_in_place_reprep`.
  Measurement was already per-rail (remote-capable); reset is the only
  locality constraint.

## Open followups

- Dynamic rail allocation in the Rust router: release both rails at
  measurement, allocate the nearest free adjacent pair at reset. This is the
  physical-layer freedom with no qubit-level analogue (dual-rail measurement
  is destructive and rail-local). Payoff expected only where the check
  pattern changes between rounds (lattice surgery, Floquet), not for repeated
  memory rounds.
- VF2-seeded start in `PrismRouting.start_mode`.
- Native ZZ-parity measurement op for Floquet codes (no ancilla qubit).
- Bravyi depth-7 BB schedule; size topologies by quotient slack, not rail count;
  quotient arm needs its own sizing rule (heavy_hex matching covers 48 of 60).
- Multi-round with erasure checks modeled as a 1Q op after every 2Q gate
  (Chang et al.) for duration numbers.

## Rerun

```bash
.venv/bin/python research/scripts/qec/qec_quick.py bb_18_4_4,steane_cnot hex_lattice,grid 0,1 40
.venv/bin/python research/scripts/qec/qec_rounds.py surface_d3_r3 hex_lattice 0 8 greedy,prism [local]
.venv/bin/python research/scripts/qec/embed_search.py surface_d3,surface_d5
```

## 2026-09-09: qubit reuse, and commutation-aware routing dependencies

**Qubit reuse (branch `qubit-reuse`, scripts `qec/qubit_reuse.py`, `qec/reuse_experiment.py`).**
qiskit-qubit-reuse 0.0.2 does not run on Qiskit 2 (reads removed `op.condition`, mutates a
DAG while iterating). Reimplemented the greedy causal-cone algorithm (DeCross et al.) in 60
lines. Prism on the reused circuit, each on the smallest lattice for its own width, budget 8:
rails halve (BB 81->42, surface d5 100->56); swaps halve on non-planar codes (BB grid 264->128,
Steane 133->89) and go flat or up on planar ones; physical depth and duration rise 2 to 6x
(serialized checks). A width-for-time trade, valuable when width-limited. mqt.bench circuits
show no reuse until barriers are removed and alg-level gates decomposed; qft/ae none even then.
Dual-rail-specific extension: a reset need not land on the measured rails (re-host at reset).

**Two-port bound.** Each dual-rail qubit has two rails; diagonal gates use one. ASAP schedule
with per-rail resources vs one-port logical depth: 23% total over the 16 paper circuits plus
3 QEC rounds (multipliers ~40%, BB 59%, qft/ae 0%). Prism already harvests part of this
(several circuits' physical depth is below the one-port bound).

**Commutation-aware dependencies (branch `commuting-deps`, `PrismRouting.COMMUTE_DIAGONAL`).**
`_build_deps` now treats CRZ/RZ as mutually commuting: a diagonal op depends only on the last
non-diagonal op per wire. Paper set, paper budget, seed 0, grid+hex: swaps 641 -> 521
(-18.7%), depth flat, duration +1.8%; with the depth objective swaps -15.5%, depth +3.5%.
QEC rounds: BB 246->180 / 326->256, Steane 111->90 / 159->133. Semantics verified by
`test_encoded_equivalence.py` (routed rails vs the encoding isometry, flag on and off).
Depth does not improve because realization choice ignores rail occupancy; a rail-load-aware
score is the next step for the two-port gain. `prism_gate.py` runs with the flag off to keep
reproducing the paper arm.

### Does the relative paper claim move? (marabbecca branch `commuting-deps`, 2026-09-09)

Same relaxation patched into marabbecca's `_build_deps` (2.4.1). Greedy binding collapses
nodes to stock single-pair kind and stock `FrontLayer` asserts when two front-layer gates
share a qubit, so this A/B used prism's kernel with every node routed through the
realization front layer (that kernel does not reproduce the paper rows exactly, 31/32
cells move slightly; it is used for both arms and both flags). 16 paper circuits, paper
budget, seed 0, grid+hex, totals:

| | greedy swaps | prism swaps | prism vs greedy swaps | depth | duration |
|---|---|---|---|---|---|
| whole-qubit deps (paper) | 883 | 649 | -26.5% | -9.5% | -8.7% |
| commutation-aware deps | 728 | 532 | -26.9% | -4.2% | -2.7% |

Both arms gain ~18% in swaps; prism's relative swap advantage is unchanged; its relative
depth and duration advantages shrink by about half. Quotient SABRE (stock Qiskit) cannot
take the relaxation without modifying Qiskit's router, so a re-run would widen the gap to
that baseline. Not a bug: stock SABRE has the same wire-ordered DAG; commutation-aware
routing (Itoko et al. 2020) is the standard technique and the discussion chapter names the
limitation. Prism-specific complication: the encoding conflicts on all four rails, and
prism's front layer must hold two gates on one rail (it already can; stock cannot).
Prism's `input.rs` keeps the stock fast path (restoring it keeps the gate exact); the
all-MultiTwoQ variant is experiment-only.

### Two-port harvest attempts (2026-09-09, both negative; patch kept in `research/patches/`)

Achieved rail concurrency, measured from committed realizations (consecutive commuting CRZs on
one logical qubit landing on different rails): paper deps 44.9%, commutation-aware 37.3%,
i.e. coin-flip. Two attempts to raise it inside the router, both on top of commutation-aware
deps, paper set + 3 QEC rounds, seed 0, grid+hex:

1. Global rail-load term in the realization score (`dist + w * phys_load`): swaps +11% (w=0.25)
   to +41% (w=1.0), depth flat to +6.5%, concurrency unchanged (44.6%). Steers every gate off
   busy rails, not just siblings.
2. Sibling-aware penalty (kernel remembers each op's committed rails; a realization on the rail
   a commuting sibling used on the shared logical qubit pays `w`; used as primary key among
   executable realizations and added in SWAP scoring): w in {0.5, 1, 2}: swaps -0.5% to +8%,
   depth -0.6% to +2.6%, concurrency 42.8% at w=1.

Conclusion: which rail is adjacent is fixed by the layout, which clusters a qubit's partners on
one side; a local realization term cannot buy concurrency at the swap price. Harvesting the
23% two-port bound would need a layout objective (place each logical qubit's rails to face
different partner groups), i.e. a different placement problem, not a scoring tweak. The kernel
keeps only the commutation-aware dependencies (`COMMUTE_DIAGONAL`), which are worth 18.7%
swaps on the paper set; the sibling machinery was reverted (diff in
`research/patches/sibling_rail_penalty_2026-09-09.patch`).

### Where prism's headroom is (2026-09-10, paper set n=8, grid+hex, seed 0, commutation-aware deps)

Scripts and logs: `research/scripts/diag/`. Totals over the 32 compiles (641 swaps, depth 1737,
duration 581 us at the paper budget 40/16/40).

Search budget: 5x starts swaps -5.9%, 4x refinement iterations -2.3%, 5x swap trials -1.2%,
5x starts + 4x iterations -7.0% (compile time 8 s -> 46 s for the set). Per-start spread: the best
start is typically 20-40% below the median and often unique, yet pair-aware starts (each logical
qubit's rails on a coupling edge, random maximal matching) change nothing (+0.3% swaps): the
refinement loop erases start structure.

Swap attribution (each SWAP charged to the first later op that uses a rail it moved):
CRZ reach 63%, RX rejoin 30%, joint-herald co-location 7%. `local_init=True` (no herald
constraint) gives swaps -7.8%, depth -8.2%.

Realization choice at commit: of 1416 CRZ commits, 1285 (91%) had exactly one adjacent
realization, 120 had two, 11 had three or four. Consecutive commuting CRZs on one logical qubit:
46% landed on different rails, 53% were forced onto the same rail, 1% chose the same rail. So
prism's gain is in which realization the swap sequence makes available, not in choosing among
executable ones; that is why sibling-aware scoring could not move concurrency.

RX sensitivity (delete a random fraction of logical RX before routing, semantics ignored):
25% fewer RX -> swaps -1.7%, depth -6.5%; 50% -> swaps -8.5%, depth -19.7%, duration -16.8%;
all -> swaps -42%, depth -58%. Rejoins drive depth and duration more than swaps.

Post-selection objective: depth objective swaps +16.8% / depth -13.3% / duration -13.0%;
duration objective swaps +22.9% / duration -13.9%. The paper's device section already runs both
arms under the duration objective (`device_v17_liu_duration_n8_16.toml`).

Logical X count after the logical stage is 0-1 per circuit, so a free X-by-relabel realization
has nothing to save.

Conclusion: within the paper's machine model and the SABRE family, remaining routing gains are
single digits and fair to both arms (budget, herald-aware layout). Larger gains need either
fewer rejoins (RX-count synthesis; encoding-agnostic technique, dual-rail-specific payoff) or a
machine-model extension (pre-shared Bell pairs for teleported CZ, rail teleportation), which the
paper's discussion explicitly excludes, or an optimality-gap study (exact rails+realizations
solver on small instances) to see whether the SABRE family itself is the ceiling.

Budget A/B on the frozen arms (marabbecca, paper deps, seed 0, `diag/marab_budget_ab.py`):
    starts=40: greedy swaps 879 depth 1874 | prism swaps 635 depth 1736 | prism vs greedy swaps +27.8% depth +7.4%
    starts=200: greedy swaps 815 depth 1859 | prism swaps 603 depth 1622 | prism vs greedy swaps +26.0% depth +12.7%

### Measurement commutes with diagonal gates (2026-09-10, sizing only; `diag/measure_commute*.py`)

Rule: a qubit whose remaining gates are all diagonal and end in a Z measurement can be measured
at its last non-diagonal gate; every later CRZ on it becomes a classically controlled RZ on the
other operand, which is free in dual-rail. Encoding-agnostic (semiclassical QFT, Griffiths-Niu
1996), so every arm gets it; the payoff is dual-rail specific because CRZ is the 500 ns gate.

Paper set: 340 of 708 CRZs (48%) qualify. Routing the reduced circuits with prism: swaps 641 ->
288 (-55%), depth -45%, duration -45%. Split: 170 come from qubits that never see a non-diagonal
gate (the a/b input registers of the multipliers and the draper adder are computational-basis
constants, a benchmark artifact), 170 from genuine measurement tails (qft 28/28, qpe 21/28,
qftentangled 28/35, ae 21/35, hhl 12/48). Caveats: the duration model has no measurement or
feedforward latency, and the semiclassical chain serializes measure -> conditional RZ -> RX per
qubit, so depth/duration gains are overstated; swap gains are real but they remove the routing
problem itself on the QFT family (qft goes to 0 swaps for every arm), so this shrinks prism's
edge rather than widening it. A dynamic-circuit dual-rail study, not a prism improvement.

### Optimality gap pilot (2026-09-10, `diag/exact_rails.py`, OR-tools CP-SAT, transition model)

4-qubit instances: prism ties the best solution found on every instance; proven optimal on
three (qft grid 1, qftentangled grid 1, hhl hex 2), vqe grid feasible 5 vs prism 6 (unproven).
5- and 6-qubit runs in progress (180 to 240 s per instance, lower bounds rarely prove).

### EarlyMeasurement pass (2026-09-10, implemented, staged in prism, default on)

`synthesis/early_measure.py`, appended to `DualRail.logical_pm` under `DualRail.early_measure`
(the reproduction gate sets it False and stays 0/32). A qubit whose remaining gates are all
diagonal and end in a Z measurement is measured at its last non-diagonal gate; later `rz` on it
vanish; later `crz` become `if_test` RZs on the other operand (control measured: `rz(theta)` on
the target if 1; target measured to m: unconditional `rz(-theta/2)` plus `rz(theta)` if 1 on the
control). Not Qiskit's `RemoveDiagonalGatesBeforeMeasure` (that deletes a diagonal gate only when
every operand goes straight to measurement; it removes 0 of 708 CRZs here).

Three plumbing fixes were needed for feedforward to survive lowering and routing, all latent bugs
for any `if_else` circuit: (1) the lowered measurement of a logical qubit now writes wire 0 into
the logical clbit and the other wire into a `herald` creg (the old code sent both wires to a fresh
`meas` creg and dropped the input's, and an input creg also named `meas`, as mqt's `measure_all`
makes, collided with it so both wires wrote the same bit); (2) the routing dependency graph adds
classical bits as wires (`_build_deps(..., cl_used)`), otherwise an `if_else` could be routed
before the measurement it reads; (3) metrics treat control flow whose bodies are free as free.
Exact branch-enumerating distribution tests (`test_early_measure.py`) cover the logical rewrite
and the routed rail circuit.

Paper set, prism, seed 0, grid+hex, 32 compiles, pass off -> on:
swaps 641 -> 292 (-54%), depth 1737 -> 1233 (-29%), duration 581 -> 334 us (-42%),
CRZ 1407 -> 735 (-48%). Same caveats as the sizing: half the removed CRZs come from constant
input registers (multipliers, draper adder), the model has no measurement/feedforward latency,
and every arm gets the same rewrite, so it is a pipeline improvement, not a routing one.

### Hinted CP-SAT improvement search from prism's route (2026-09-10, `diag/exact_rails_hint.py`)

Transition model (OLSQ2-style blocks, any matching of SWAPs between blocks), every op free to move
within +-2 blocks of its prism block and to change realization, mappings free, seeded with prism's
own route; 120 s per instance, 8 workers. The first incumbent equals prism's count on most
instances (the block cut is imperfect on a few), so any lower value is a real gap; no lower
bound was ever proven (bound 0 everywhere), so these are upper bounds on prism's distance from
optimal, not the distance itself.

    dj                       grid        prism=  2 first=2.0 best=2.0 bound=0 status=FEASIBLE blocks=3 120s
    dj                       hex_lattice prism=  4 first=6.0 best=4.0 bound=1 status=FEASIBLE blocks=5 120s
    qaoa                     grid        prism=  4 first=4.0 best=4.0 bound=0 status=FEASIBLE blocks=5 120s
    qaoa                     hex_lattice prism= 14 first=14.0 best=13.0 bound=0 status=FEASIBLE blocks=15 120s
    draper_qft_adder         grid        prism=  6 first=10.0 best=4.0 bound=0 status=FEASIBLE blocks=7 120s
    draper_qft_adder         hex_lattice prism= 12 first=12.0 best=11.0 bound=0 status=FEASIBLE blocks=12 120s
    modular_adder            grid        prism=  3 first=4.0 best=3.0 bound=0 status=FEASIBLE blocks=4 120s
    modular_adder            hex_lattice prism= 12 first=12.0 best=12.0 bound=0 status=FEASIBLE blocks=12 120s
    qft                      grid        prism= 13 first=13.0 best=13.0 bound=0 status=FEASIBLE blocks=11 120s
    qft                      hex_lattice prism= 22 first=22.0 best=20.0 bound=0 status=FEASIBLE blocks=19 120s
    qpeexact                 grid        prism= 15 first=14.0 best=13.0 bound=0 status=FEASIBLE blocks=14 120s
    qpeexact                 hex_lattice prism= 22 first=21.0 best=21.0 bound=0 status=FEASIBLE blocks=21 120s
    qpeinexact               grid        prism= 15 first=14.0 best=13.0 bound=0 status=FEASIBLE blocks=14 120s
    qpeinexact               hex_lattice prism= 22 first=21.0 best=21.0 bound=0 status=FEASIBLE blocks=21 121s
    qftentangled             grid        prism= 16 first=30.0 best=16.0 bound=0 status=FEASIBLE blocks=16 120s
    qftentangled             hex_lattice prism= 24 first=24.0 best=21.0 bound=0 status=FEASIBLE blocks=23 121s
    bmw_quark_copula         grid        prism= 14 first=14.0 best=12.0 bound=0 status=FEASIBLE blocks=15 120s
    bmw_quark_copula         hex_lattice prism= 27 first=27.0 best=26.0 bound=0 status=FEASIBLE blocks=26 120s
    hhl                      grid        prism= 30 first=29.0 best=27.0 bound=0 status=FEASIBLE blocks=29 120s
    hhl                      hex_lattice prism= 42 first=41.0 best=41.0 bound=0 status=FEASIBLE blocks=41 120s
    ae                       grid        prism= 18 first=18.0 best=16.0 bound=0 status=FEASIBLE blocks=16 120s
    ae                       hex_lattice prism= 25 first=25.0 best=23.0 bound=0 status=FEASIBLE blocks=22 122s
    cdkm_ripple_carry_adder  grid        prism=0
    cdkm_ripple_carry_adder  hex_lattice prism=0
    full_adder               grid        prism=0
    full_adder               hex_lattice prism=0
    vqe_two_local            grid        prism= 59 first=59.0 best=59.0 bound=0 status=FEASIBLE blocks=54 120s
    vqe_two_local            hex_lattice prism= 85 first=85.0 best=85.0 bound=0 status=FEASIBLE blocks=72 121s
    rg_qft_multiplier        grid        prism= 23 first=23.0 best=20.0 bound=0 status=FEASIBLE blocks=24 120s
    rg_qft_multiplier        hex_lattice prism= 43 first=43.0 best=41.0 bound=0 status=FEASIBLE blocks=40 121s
    multiplier               grid        prism= 23 first=23.0 best=23.0 bound=0 status=FEASIBLE blocks=23 120s
    multiplier               hex_lattice prism= 46 first=46.0 best=44.0 bound=0 status=FEASIBLE blocks=45 122s
    TOTAL prism=641 best=608.0 improvement=5.1%

Read: prism sits within a few percent of what a 2-minute exact local search can find at 8
qubits; the gains are 1 to 3 swaps on QFT-family circuits and zero on the dense ones (vqe, hhl
hex, multiplier grid). A hybrid exact-window router is not the thing.

### Device-model axes on the frozen arms (2026-09-10, marabbecca, paper deps, seed 0, paper budget)

Spare rails (16 rails on grids of 16, 18, 20, 24 sites; `diag/marab_spares.py`):

    grid 4x4: greedy swaps 335 depth 857 dur 293 | prism swaps 244 depth 862 dur 295 | prism vs greedy swaps +27.2% depth -0.6% duration -0.6%
    grid 3x6: greedy swaps 367 depth 900 dur 304 | prism swaps 260 depth 806 dur 281 | prism vs greedy swaps +29.2% depth +10.4% duration +7.6%
    grid 5x4: greedy swaps 354 depth 948 dur 322 | prism swaps 241 depth 818 dur 280 | prism vs greedy swaps +31.9% depth +13.7% duration +13.0%
    grid 6x4: greedy swaps 340 depth 915 dur 312 | prism swaps 248 depth 809 dur 281 | prism vs greedy swaps +27.1% depth +11.6% duration +9.8%

Prism's swap edge is 27-32% at every size, including zero spares; the depth/duration edge needs
slack (vanishes at 4x4, 10-14% with 2+ spares). No widening on this axis. Note marabbecca's
research notes already banked the teleport gadget (de-risked June 2026, heralded 1/2 success cap)
and the cadence/rejoin bound (`separation_cadence_bound.md`), so neither is a fresh direction.

Periodic erasure checks (a joint herald on every qubit after every D layers of the input circuit;
`diag/marab_erasure.py`):

    period=0 grid       : greedy swaps 354 depth 948 dur 322 | prism swaps 241 depth 818 dur 280 | prism vs greedy swaps +31.9% depth +13.7% duration +13.0%
    period=0 hex_lattice: greedy swaps 531 depth 926 dur 302 | prism swaps 400 depth 918 dur 300 | prism vs greedy swaps +24.7% depth +0.9% duration +0.7%
    period=8 grid       : greedy swaps 440 depth 1009 dur 332 | prism swaps 334 depth 920 dur 309 | prism vs greedy swaps +24.1% depth +8.8% duration +6.8%
    period=8 hex_lattice: greedy swaps 699 depth 1154 dur 371 | prism swaps 527 depth 991 dur 318 | prism vs greedy swaps +24.6% depth +14.1% duration +14.4%
    period=4 grid       : greedy swaps 464 depth 1052 dur 342 | prism swaps 363 depth 1006 dur 329 | prism vs greedy swaps +21.8% depth +4.4% duration +3.6%
    period=4 hex_lattice: greedy swaps 748 depth 1191 dur 374 | prism swaps 564 depth 1049 dur 336 | prism vs greedy swaps +24.6% depth +11.9% duration +10.1%

Checks cost both arms 25-40% more swaps; prism's swap edge stays 22-25%; its depth/duration edge
on the hex lattice grows from ~1% to 12-14% because greedy pays more for each forced rejoin.
Not a substantial widening either.

Closing the search (2026-09-10): every fair axis tried (budget, starts, exact windows, spares,
erasure cadence, scoring) leaves prism's unique commitment-timing edge at 22-32% swaps. The
substantial improvements found are pipeline-level and shared by every arm: commutation-aware
dependencies (-18.7% swaps) and the EarlyMeasurement pass (-54% swaps, -42% duration).

EarlyMeasurement on both frozen arms (`diag/marab_em_arms.py`; the rewrite applied to marabbecca's
logical circuit and fed back through the pipeline; input creg renamed because marabbecca's expansion
drops a creg named `meas`; feedforward wiring not semantically checked there, routing effect faithful):

    EM=False grid       : greedy swaps 354 depth 948 dur 322 | prism swaps 241 depth 818 dur 280 | prism vs greedy swaps +31.9% depth +13.7% duration +13.0%
    EM=False hex_lattice: greedy swaps 531 depth 926 dur 302 | prism swaps 400 depth 918 dur 300 | prism vs greedy swaps +24.7% depth +0.9% duration +0.7%
    EM=True  grid       : greedy swaps 138 depth 622 dur 167 | prism swaps 111 depth 583 dur 168 | prism vs greedy swaps +19.6% depth +6.3% duration -0.3%
    EM=True  hex_lattice: greedy swaps 225 depth 639 dur 179 | prism swaps 185 depth 584 dur 161 | prism vs greedy swaps +17.8% depth +8.6% duration +9.9%
    with EM, prism fewer/tie/more swaps than greedy per circuit: {'grid': [4, 12, 0], 'hex_lattice': [7, 8, 1]}

Greedy gains as much as prism from the rewrite. Prism's swap edge narrows from 25-32% to 18-20%,
with 12 of 16 grid cases and 8 of 16 hex cases tied (the QFT family becomes trivial for both).
So the pass is a fair tool improvement that shrinks, not widens, the commitment-timing gap.

Erasure cadence, 3 seeds (0,1,2), both objectives (`diag/marab_erasure_3s*.log`):

    obj=swaps seeds=[0, 1, 2] period=0 grid       : greedy swaps 349 depth 940 dur 321 | prism swaps 243 depth 812 dur 277 | prism vs greedy swaps +30.3% depth +13.7% duration +13.5%
    obj=swaps seeds=[0, 1, 2] period=0 hex_lattice: greedy swaps 537 depth 943 dur 308 | prism swaps 400 depth 921 dur 302 | prism vs greedy swaps +25.4% depth +2.3% duration +1.9%
    obj=swaps seeds=[0, 1, 2] period=8 grid       : greedy swaps 441 depth 1011 dur 333 | prism swaps 334 depth 925 dur 311 | prism vs greedy swaps +24.3% depth +8.5% duration +6.7%
    obj=swaps seeds=[0, 1, 2] period=8 hex_lattice: greedy swaps 698 depth 1142 dur 367 | prism swaps 527 depth 994 dur 318 | prism vs greedy swaps +24.5% depth +13.0% duration +13.4%
    obj=swaps seeds=[0, 1, 2] period=4 grid       : greedy swaps 464 depth 1053 dur 342 | prism swaps 362 depth 992 dur 326 | prism vs greedy swaps +22.0% depth +5.8% duration +4.7%
    obj=swaps seeds=[0, 1, 2] period=4 hex_lattice: greedy swaps 749 depth 1187 dur 373 | prism swaps 563 depth 1053 dur 337 | prism vs greedy swaps +24.8% depth +11.3% duration +9.6%
    obj=duration seeds=[0, 1, 2] period=0 grid       : greedy swaps 458 depth 794 dur 263 | prism swaps 298 depth 732 dur 243 | prism vs greedy swaps +34.8% depth +7.8% duration +7.5%
    obj=duration seeds=[0, 1, 2] period=0 hex_lattice: greedy swaps 663 depth 872 dur 276 | prism swaps 489 depth 787 dur 255 | prism vs greedy swaps +26.2% depth +9.7% duration +7.5%
    obj=duration seeds=[0, 1, 2] period=8 grid       : greedy swaps 551 depth 932 dur 297 | prism swaps 385 depth 835 dur 275 | prism vs greedy swaps +30.1% depth +10.5% duration +7.3%
    obj=duration seeds=[0, 1, 2] period=8 hex_lattice: greedy swaps 840 depth 1024 dur 316 | prism swaps 607 depth 927 dur 295 | prism vs greedy swaps +27.7% depth +9.4% duration +6.6%
    obj=duration seeds=[0, 1, 2] period=4 grid       : greedy swaps 582 depth 976 dur 312 | prism swaps 415 depth 897 dur 291 | prism vs greedy swaps +28.6% depth +8.1% duration +6.6%
    obj=duration seeds=[0, 1, 2] period=4 hex_lattice: greedy swaps 914 depth 1096 dur 337 | prism swaps 670 depth 984 dur 309 | prism vs greedy swaps +26.7% depth +10.2% duration +8.3%

The hex duration widening (2% -> 13%) survives three seeds under the swaps objective, but under the
duration objective (the paper's device arm) prism's duration edge is flat at 7-8% with or without
checks. So it is an artifact of minimizing swaps on a sparse lattice, not a new prism advantage.

### Smith, Pokharel, Maurya, Takita (IBM), arXiv:2609.08925 (2026-09-08), read 2026-09-10

"Resilience Beyond the Light Cone: Error-Detected Primitives for Practical Dynamic Circuits."
Transmons, not dual-rail. DISTRIBUTE (fan a control into a GHZ "distributed control" via fusion
measurements + feedforward) and COLLAPSE^(n) (measure it back through repetition-code checks;
explicit vs implicit checks) turn readout and gate errors into postselection with no extra
ancillas; single-feedforward-round variants when the controlled U is Clifford/Hermitian; O(k)-depth
error-detected Hadamard test; 100-qubit Bell pair F=0.59, W states to 20 qubits. Their noisy
simulations use a measurement+feedforward latency of ~24 two-qubit gate times (ibm_boston) and map
where dynamic beats unitary (Fig. 2).

Relevance: (1) it supplies the latency model EarlyMeasurement lacks. All 308 feedforward RZs the
pass emits on the paper set are live (each precedes a later RX on its target; the fully deferrable
cases are already deleted outright), and the QFT family needs 6-7 sequential feedforward rounds
(`diag/ff_live.py`, `diag/ff_rounds.py`). At ~24 gate times per round that is on the order of the
whole unitary depth, so the pass's duration gain is not real without a hybrid unitary/dynamic
decision like their Fig. 2, which is a routing-adjacent decision prism could make per gate.
(2) Distributed control is the principled form of the "clean ancilla per wire" idea for fan-out
CRZ structure (QFT/QPE controls): the control never moves; ancilla rails plus measurement replace
routing. Beyond the paper's machine model; a followup with ancilla rails and a latency model.

Hybrid classical-realization ceiling (`diag/hybrid_ceiling.py`, prism routes, early measurement
off, seed 0, 32 compiles, 635 swaps): swaps charged to CRZs eligible for the classical path are
227 (36%), reachable only by converting every eligible CRZ (up to 4 sequential feedforward rounds,
i.e. the full EarlyMeasurement rewrite). Converting only CRZs that cost >= 2 swaps saves 56 (9%)
with <= 2 rounds; >= 3 swaps saves 12 (2%). So a per-gate commit-time decision between rail pairs
and feedforward cannot buy more than single digits at any latency where rounds are not free; the
direction is closed.

Rail exposure under EarlyMeasurement (`diag/exposure.py`, prism, seed 0, 32 compiles): integrated
time-until-measurement summed over logical qubits 3553 -> 1815 qubit-us (-49%), critical path
581 -> 334 us (-42%). Exposure is the quantity dual-rail postselection actually pays for (loss
per rail per unit time), and it falls even where the critical path does not, because measured
qubits stop accumulating loss. Latency caveat still applies to the critical path, not to exposure.

### Why commutation-aware deps did not cut depth, and the rescheduler (2026-09-11)

Under the depth objective the relaxation makes depth worse (+3.5%) while cutting swaps 15.5%
(`diag/commute_by_objective.py`); a sliding commutation window of 2-4 does not help
(`diag/commute_window.py`). Mechanism (`diag/rail_load.py`): with relaxed deps a qubit's pending
CRZs are committed in bursts on whichever rail is adjacent to the partner cluster, so the share of
a qubit's CRZs on its busier rail rises 68% -> 72% and the summed longest same-rail runs rise
742 -> 943 (+27%). On bipartite lattices (grid, honeycomb) a partner rail adjacent to A0 is never
adjacent to A1, so no commit-time choice can split a burst; only partner placement can.

Swap-free depth of the routed circuits is 1431 (off) vs 1479 (on), and after commutation-aware
critical-path rescheduling 1184 vs 1234 (`diag/depth_diag.py`): the router's emitted order costs
depth for both settings, and the rail-burst effect is the residual 4%.

`synthesis/reschedule.py` (`RescheduleCommutingDiagonals`, physical stage, `enc.reschedule`,
gate sets False and stays 0/32): re-emits the routed circuit by critical-path list scheduling over
the commutation-relaxed DAG; unitary-preserving (Operator test), never deeper. Prism, paper set:

    objective=swaps  commute=False reschedule=False: swaps 641 (+0.0%) depth 1737 (+0.0%) dur 581 (+0.0%)
    objective=swaps  commute=False reschedule=True : swaps 641 (+0.0%) depth 1607 (-7.5%) dur 534 (-8.1%)
    objective=swaps  commute=True  reschedule=False: swaps 521 (-18.7%) depth 1737 (+0.0%) dur 592 (+1.8%)
    objective=swaps  commute=True  reschedule=True : swaps 521 (-18.7%) depth 1677 (-3.5%) dur 569 (-2.1%)
    objective=depth  commute=False reschedule=False: swaps 749 (+0.0%) depth 1506 (+0.0%) dur 506 (+0.0%)
    objective=depth  commute=False reschedule=True : swaps 749 (+0.0%) depth 1436 (-4.6%) dur 481 (-4.8%)
    objective=depth  commute=True  reschedule=False: swaps 633 (-15.5%) depth 1558 (+3.5%) dur 529 (+4.6%)
    objective=depth  commute=True  reschedule=True : swaps 633 (-15.5%) depth 1501 (-0.3%) dur 508 (+0.5%)

So the package is: relaxed deps (-18.7% swaps) + rescheduler (depth -3.5%, duration -2.1% net
vs the paper pipeline; the rescheduler alone gives -7.5% depth at unchanged swaps). Every arm can
take the rescheduler. The remaining lever for depth is rail-balanced partner placement during
the swap search (tie-break level, not score level, given the earlier sibling-penalty negative).

Static port assignment (`diag/port_assign.py`, 2026-09-11): forcing each qubit to alternate the rail it
offers across its commuting CRZ run (realizations restricted; single realizations duplicated so the node
stays on the multi front layer, since the stock fast path asserts on shared front-layer qubits): swaps
+80-150%, depth +8-12% under both objectives. Forced two-port concurrency is far more expensive than
the serialization it removes. Dead.

Early measurement placed on hold (2026-09-11): `DualRail.early_measure` default False; pass and tests
kept (tests enable it via fixture).

### Relaxed deps + rescheduler on both frozen arms, 3 seeds (2026-09-11)

Greedy takes relaxed deps by duplicating its fixed realization for diagonal ops (two identical
realizations keep the node on the multi-realization front layer; the stock fast path asserts when
two front-layer gates share a qubit). Rescheduler = prism's pass applied to marabbecca's output.
`diag/marab_commute_resched.py`, seeds 0,1,2, swaps objective, grid+hex summed:

    obj=swaps seeds=[0, 1, 2] commute=False resched=False: greedy swaps 885 depth 1883 dur 628 | prism swaps 643 depth 1733 dur 579 | prism vs greedy swaps +27.3% depth +8.0% duration +7.8%
    obj=swaps seeds=[0, 1, 2] commute=False resched=True : greedy swaps 885 depth 1804 dur 605 | prism swaps 643 depth 1613 dur 537 | prism vs greedy swaps +27.3% depth +10.6% duration +11.3%
    obj=swaps seeds=[0, 1, 2] commute=True  resched=False: greedy swaps 738 depth 1808 dur 600 | prism swaps 521 depth 1734 dur 590 | prism vs greedy swaps +29.4% depth +4.1% duration +1.7%
    obj=swaps seeds=[0, 1, 2] commute=True  resched=True : greedy swaps 738 depth 1755 dur 583 | prism swaps 521 depth 1673 dur 568 | prism vs greedy swaps +29.4% depth +4.7% duration +2.5%

Prism-only replication on seeds 1 and 2 (`diag/commute_x_resched_seeds.log`) matches seed 0:
relaxed deps -19% swaps at flat depth; rescheduler -7% depth alone, net -3% with relaxed deps.

Rail-balanced SWAP tie-break (site-indexed `phys_load` among equal-score SWAPs): swaps +6% / +14%,
depth flat, same-rail runs up; stripped (`research/patches/swap_tiebreak_load_2026-09-11.md`).
Commutation window knob also stripped (no effect). Kernel back to the gate-exact build; the only
kernel-facing change kept is classical-bit dependencies in `_build_deps`.

State of the routing/scheduling package: relaxed diagonal deps (prism -19% swaps, greedy -17%,
prism's swap edge 27% -> 29%), rescheduler (both arms -4 to -7% depth), early measurement on hold.
Depth/duration edge over greedy shrinks to 4.7% / 2.5% because greedy benefits more from the
depth handback. Every concurrency lever tried (sibling penalty, port assignment, swap tie-break)
is negative; the bipartite-lattice argument says commit-time rail choice cannot exist, and swap-
search steering costs more swaps than the depth it buys.

### Lattice study: where realization choice exists (2026-09-11, `diag/lattices.py`, `diag/lattice_*.py`)

Bipartite lattices (grid, hex, heavy-hex) never have a site adjacent to both rails of an adjacent
pair, so a CRZ commit has >= 2 executable realizations only when both pairs happen to align.
Non-bipartite lattices (triangular = grid + one diagonal, king = grid + both diagonals) do.
Prism, paper set, seed 0, 18 sites:

    commits with >=2 executable realizations: hex 6.6%, grid 11.9%, triangular 37.7%, king 40.7%
    (relaxed deps: 2.1 / 10.3 / 35.0 / 41.2%); sibling-on-different-rail: 45/41/42/48% (paper deps),
    31/31/35/47% (relaxed)
    swaps (paper deps): hex 400, grid 241, triangular 150, king 72

Relaxed deps x rescheduler behave the same on every lattice (-16 to -18% swaps; depth +8-11% without
the rescheduler, +1 to +6% with it under the swaps objective, neutral under the depth objective).
The paper's load tie-break among executable realizations (vs neutral) is worth 0.8% depth on hex,
2.4% grid, 3.6% triangular, 1.9% king (paper deps): the "choice" effect exists only with triangles
and is small even there.

Both frozen arms across lattices (seed 0, `diag/marab_lattices.py`):

    seeds=[0] commute=False hex       : greedy swaps 531 depth 926 dur 302 | prism swaps 400 depth 918 dur 300 | prism vs greedy swaps +24.7% depth +0.9% duration +0.7%
    seeds=[0] commute=False grid      : greedy swaps 354 depth 948 dur 322 | prism swaps 241 depth 818 dur 280 | prism vs greedy swaps +31.9% depth +13.7% duration +13.0%
    seeds=[0] commute=False triangular: greedy swaps 205 depth 880 dur 306 | prism swaps 150 depth 807 dur 288 | prism vs greedy swaps +26.8% depth +8.3% duration +5.9%
    seeds=[0] commute=False king      : greedy swaps 106 depth 780 dur 284 | prism swaps 72 depth 665 dur 237 | prism vs greedy swaps +32.1% depth +14.7% duration +16.5%
    seeds=[0] commute=True  hex       : greedy swaps 461 depth 932 dur 304 | prism swaps 323 depth 847 dur 286 | prism vs greedy swaps +29.9% depth +9.1% duration +6.1%
    seeds=[0] commute=True  grid      : greedy swaps 273 depth 878 dur 298 | prism swaps 198 depth 888 dur 304 | prism vs greedy swaps +27.5% depth -1.1% duration -2.0%
    seeds=[0] commute=True  triangular: greedy swaps 166 depth 888 dur 313 | prism swaps 125 depth 875 dur 306 | prism vs greedy swaps +24.7% depth +1.5% duration +2.0%
    seeds=[0] commute=True  king      : greedy swaps 86 depth 848 dur 303 | prism swaps 60 depth 740 dur 267 | prism vs greedy swaps +30.2% depth +12.7% duration +11.8%

Prism's swap edge is 25-32% on every lattice; triangles do not widen it. So delayed commitment's
value is availability timing under the swap search, not selection among available realizations.

Late binding (`diag/late_binding.py`, 2026-09-11): keep prism's SWAP sequence, let each CRZ move within
its window (between the barriers on its logical qubits) and take any realization adjacent under the
layout at the chosen position; lookahead list scheduling. Depth vs fixed realizations: grid +0.8%,
hex -2.2%, triangular -1.8%, king +0.7%; 21-25 of 708 CRZs move, 32-146 re-choose. Windows are
short (the beam splitters pin them) and the fixed SWAP sequence leaves no room. Post-route
re-commitment is not a lever either.

### Early measurement as a routing-time realization (2026-09-24, `diag/latency_sweep.py`, `diag/early_measure_mre.py`)

Literature check of the 2026-09-10 notes. Correct as stated: Griffiths-Niu 1996 (PRL 76, 3228) is the
control-measured rewrite; Qiskit's `RemoveDiagonalGatesBeforeMeasure` (Rust source) only deletes, 1q
diagonals before any measure, 2q/3q only when every successor is a measure (open issue #16976 notes it also
stops after one layer); Teoh et al. PNAS 2023 sec. C: Z rotations "in software by changing the phase of the
pump(s)"; Mehta et al. Nature 2026: SWS CZ ~500 ns. Missing citation: Rovara, Burgholzer, Wille,
arXiv:2511.22712 (Nov 2025) state the general rule set as a dynamic-circuit pass (diagonal commutes, X
negates the outcome, measured control -> classically controlled gate, measured target of a controlled
phase -> "exchange controls", our rz(-theta/2) + conditional rz(theta) case). They always convert every
eligible gate, optimize qubit count, and use no latency or cost model.

Latency numbers the notes lacked: ETH fan-out arXiv:2409.06989: 400 ns readout + 800 ns feedforward
= 1.2 us. Smith et al. arXiv:2609.08925 (ibm_boston): 1 us measure + 650 ns feedforward = 24.1 two-qubit
gate times at 70 ns. The same 1.65 us is 3.3 CRZ times at 500 ns, so the "24 gate times" objection from
2026-09-10 does not transfer: the classical stack is the same, the dual-rail gate is 7x slower. Chou et al.
Nat. Phys. 2024: cavity logical measurement sequence 4.8 us, decay ~0.2%/us.

Sweep (prism, seed 0, grid+hex, 32 compiles, measure M = 1 us, feedforward F varied; `if_else` waits for
its measurement + F; exposure = qubit-us until each logical measurement; survival = exp(-0.002 * exposure)):

    F(us) | crit. path never / always / per-circuit best (us, sum 32) | mean survival never / always / best
      0.0 |    649    477    461 (-28.9% vs never,  -3.3% vs always) | 0.808 0.872 0.874
      0.5 |    649    528    496 (-23.5% vs never,  -6.1% vs always) | 0.808 0.862 0.867
      1.0 |    649    580    511 (-21.2% vs never, -11.9% vs always) | 0.808 0.853 0.861
      2.0 |    649    686    529 (-18.5% vs never, -23.0% vs always) | 0.808 0.835 0.856
      5.0 |    649   1016    582 (-10.2% vs never, -42.7% vs always) | 0.808 0.782 0.849
     12.0 |    649   1786    646 ( -0.4% vs never, -63.8% vs always) | 0.808 0.680 0.835

Per circuit (grid, critical path, always vs never): qft/qpe/qftentangled/draper/ae flip from -10..-26% at
F=0 to +1..+9% at F=0.5 us and +19..+36% at 1 us; hhl, modular_adder, the multipliers stay negative to
F=2..5 us; dj, cdkm, full_adder, bmw are worse at every F (the measurement itself, 1 us = 2 CRZ times, is
on the path). So "always convert" (EarlyMeasurement as staged, and Rovara et al.) is the wrong policy at
any real latency, "never" leaves ~20% critical path and 5 points of survival on the table, and the
per-circuit best-of-two, a lower bound on a per-gate choice, beats both at every F, by 6% at ETH latency
and 12% at IBM latency. Under survival the gap is wider: at Chou-cavity latency (F ~ 5 us) always drops
below never (0.78 < 0.81) while best holds 0.85.

Proposal for the paper: make the classical path a realization. A tail CRZ gets a fifth candidate
{measure the control's rails now, feedforward rz on the target rail} beside its four rail pairs, and
PrismRouting binds it per gate at commit time from rail distance at that moment, rounds already chained,
and (M, F, gamma). That is the paper's thesis applied to a non-unitary realization; greedy/early binding
cannot make the choice because the swap cost of the coherent option is unknown before routing. IR cost:
`LoweredOp` requires equal `num_clbits` across realizations and the measurement node moves, so the
realization set needs a clbit and the tail's later measure must be elided when this candidate wins.
Figure: x = M+F with device markers (ETH 1.2, IBM 1.65, cavity 5.5 us), y = critical path and survival,
lines never / always / prism per-gate; prism's line should be the lower envelope. Dual-rail is the regime
where this matters because the stack latency is ~3 gate times, not 24. `hybrid_ceiling.py` (swaps only)
closed this direction on 2026-09-10; the swap objective was the wrong lens, latency and exposure are the
lens.
