# port_parallelism: is the 2-port depth floor realized? (2026-06-26)

Measures whether prism's rail-level router already exploits the two-port structure
of a dual-rail qubit (CRz on rail a0 and CRz on rail a1 in the same layer). The script
(`measure_port_util.py`, n=8 grid, 26 MQT circuits, 3 seeds) used the removed
`GreedyCommit` and `pick_ablation.py`; it is in git history.

Method: walk prism's routed (rail-level) circuit, ASAP-layer it, track physical->
virtual through SWAPs, map each CRz's two physical wires back to logical qubits
(virtual rail v -> qubit v//2). A qubit in >=2 CRz in one layer is using both ports.
Per qubit: crz_incidence (CRz it touches) vs crz_layers (distinct layers it is in a
CRz). fused critical-path floor = max_q incidence (= Delta); achieved = max_q layers.

## Result

Port parallelism is ALREADY PARTIALLY realized, without being asked:

- **17%** of CRz incidences double up on a qubit's two rails in one layer (mean over
  26 circuits) - the router schedules same-qubit CRz in parallel when both rail-pairs
  are adjacent.
- The critical path is shortened by it: fused floor 15.2 -> prism achieves 13.9,
  **+1.3 layers saved** on average, more on dense circuits (multiplier +3.3, dj +2.3,
  qaoa +2.0, randomcircuit +2.0).
- Doubling is highest on the SPARSE/low-degree circuits (bv 38%, dj 31%, ghz 27%) and
  lower on the dense ones (multiplier 6%, randomcircuit 3%), because on dense circuits
  routing pushes a qubit's CRz apart across layers, eating the parallelism.

But prism stays FAR from the ceil(Delta/2) port floor (qaoa: floor 6, achieved 10;
multiplier: floor 28, achieved 52.7). So most of the theoretical 2x is unrealized.
CAVEAT: the gap to the floor is muddied by routing overhead (SWAPs inflate
crz_layers independent of port use), so it is an UPPER bound on the headroom a
deliberate port-assignment pass could recover, not a clean port-only deficit.

## Paper impact

S8 port-parallelism goes from "theorem + conjecture" to "theorem + measured partial
realization + scoped headroom." The clean, defensible claims: (1) the floor is
ceil(Delta/2) (theorem, `theory_verification/verify_port_parallelism.py`); (2) the
rail-level router already realizes port concurrency on ~17% of CRz, +1.3 critical-
path layers (this measurement); (3) the remaining gap to the floor is headroom for a
deliberate port-assignment pass, net of routing, which is the open experiment.
