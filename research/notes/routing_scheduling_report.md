# Routing and scheduling changes on `commuting-deps` (report, 2026-09-11)

All staged in prism, uncommitted. Suite 105 passing. Reproduction gate
(`research/scripts/gates/prism_gate.py`) turns every new behavior off and stays 0 of 32 mismatches
against the paper's 2.5.2 numbers.

## 1. Relaxed dependencies (port-level commutation in the boundary DAG)

Where: `PrismRouting._build_deps(virts_used, diagonal, cl_used)` and `_precompute` in
`src/prism/lowering/commit_policies/prism_routing.py`; flag `PrismRouting.COMMUTE_DIAGONAL = True`,
set `DIAGONAL_OPS = {"crz", "rz"}`.

Before: every lowered op depended on the previous op touching any rail in its footprint. An
uncommitted CRZ's footprint is all four rails of both operands, so two commuting CRZs sharing a
logical qubit were serialized on four wires.

After: an op flagged diagonal (logical name in `DIAGONAL_OPS`) depends only on the last non-diagonal
op on each of its wires; a non-diagonal op (rx, x, herald, measure, if_else, swap) depends on every
diagonal op since, plus the last non-diagonal. Program order among commuting diagonals is dropped.
Applied to both the forward and the reversed (layout-refinement) DAGs.

Why correct: every realization of a logical diagonal gate is diagonal on every rail it can use
(rail CRZ plus rail RZ corrections), so the ops commute physically for any commitment; the
non-diagonal ops touch both rails and remain barriers. Verified by
`test_encoded_equivalence.py` (routed rail statevector vs encoding isometry, flag on and off, 3 seeds).

Why prism can host it: the realization front layer holds several nodes on shared rails; stock
SABRE's front layer holds one gate per qubit and asserts otherwise. Greedy takes it only on prism's
kernel, by duplicating its fixed realization for diagonal ops so the node stays on the multi
front layer (`diag/marab_commute_resched.py`); the Logical-SABRE arm cannot take it.

Numbers (paper set, 16 circuits, n=8, grid+hex, paper budget, 3 seeds, swaps objective):
prism 643 -> 521 swaps (-19%), greedy 885 -> 738 (-17%), prism's swap edge 27.3% -> 29.4%,
depth flat for prism, prism's depth edge 8.0% -> 4.1%. Mechanism of the flat depth: with relaxed
deps a qubit's pending CRZs commit in bursts on the rail adjacent to the partner cluster; share of
a qubit's CRZs on its busier rail 68% -> 72%, summed longest same-rail runs 742 -> 943.

Prior art: Itoko et al. (arXiv:1907.02686), commutation-aware SabreSwap (arXiv:2202.03459).

## 2. Rescheduler (`RescheduleCommutingDiagonals`)

Where: `src/prism/synthesis/reschedule.py`; wired in `physical.py` as the last pass before
`RecordCircuitMetrics` (post_optimization when resynthesizing, post_translation otherwise); flag
`QubitEncoding.reschedule = True` in `encodings/base.py`.

What: re-emits the routed physical circuit by critical-path list scheduling over the same
port-level dependency graph (physical rz/crz commute on shared wires; everything else is a
barrier; clbits are wires). Unit weight for non-free ops, zero for free ones (`metrics.is_free`).
Ops are emitted wave by wave in start-time order, so the linear order is a valid schedule of the
relaxed graph. Gate multiset unchanged, unitary unchanged (Operator test in
`test_reschedule.py`), depth never grows.

Why it exists: the router's commit order is not a schedule; it over-serializes commuting rail
gates. Swap-free depth of prism's routes is 1431 (paper deps) / 1479 (relaxed); after rescheduling
1184 / 1234.

Numbers (same setting, 3 seeds): alone, depth -7% and duration -8% for prism at unchanged swaps;
greedy depth 1883 -> 1804. With relaxed deps: prism swaps -19%, depth -3%, duration -2% vs the
paper pipeline; prism's depth/duration edge over greedy 4.7% / 2.5%.

## 3. Three latent bugs (any circuit with `if_else` or mid-circuit measurement was affected)

3a. Measurement clbit wiring (`lowering/expansion.py`). Before: both rails of a measured logical
qubit wrote a fresh creg named `meas` and the input's cregs were dropped when also named `meas`
(mqt's `measure_all`), so both rails wrote the same bit and feedforward conditions on the
logical clbit read nothing. After: wire 0 writes the logical clbit (`node.cargs[0]`), the other
wires write a `herald` register (name de-duplicated against the input), and all input cregs are
carried over. Depth of the reproduction was off by 1 to 3 layers under the first version of this
fix (same-bit writes created a clbit chain); the herald register restored 0 of 32.

3b. Classical dependencies in the routing DAG (`_build_deps`, `cl_used`). Before: dependencies
were built from rail wires only, so an `if_else` could be routed before the measurement that
writes its clbit; the routed circuit's measured distribution was wrong (found by the exact
branch simulator in `test_early_measure.py`). After: classical bits are extra wires; only
non-diagonal ops (measure, if_else) touch them, so measure -> if_else and if_else -> later measure
are ordered. No effect on circuits with final measurements only (gate exact).

3c. Free control flow in metrics (`utils/metrics.py::is_free`). Before: an `if_else` holding only
free gates counted as an active gate and a depth layer. After: control flow whose bodies are all
free is free. Used by `physical_depth`, `active_gate_count`, and the rescheduler's weights.

Verification for all three: `test_early_measure.py` compares exact output distributions of the
original circuit, the rewritten logical circuit, and the routed rail circuit with feedforward
(branch-enumerating simulator); the pipeline round-trips seeds and the gate stays exact.

## On hold / stripped

`EarlyMeasurement` (`synthesis/early_measure.py`, `DualRail.early_measure`) is implemented and
tested but default off. Stripped after negative results: sibling-aware realization penalty, static
port assignment, rail-balanced SWAP tie-break (site load), commutation window, kernel back to the
gate-exact build. Notes and scripts: `research/qec_codes.md`, `scripts/diag/`.
