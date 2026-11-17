# Scaling v24 ordered-depth-tie experiment

This experiment extends the adopted n=8 paper configuration through 32
logical qubits. It contains the same 16 routing workloads at every width and
does not overwrite or relabel an earlier artifact.

## Controlled comparison

Greedy and PRISM use the same boundary router, canonical candidate ordering,
stock SABRE heuristic, load tie-break, initial-layout pool, seeds, objective,
refinement schedule, and final-route trials. Greedy selects one realization
when an operation enters the router. PRISM retains the complete realization
set.

Each compilation uses 40 random layouts and the dense, identity, and reverse
layouts. Each start uses 16 forward and backward refinements and 40
final-route trials. The route-selection objective minimizes routing SWAPs,
then physical depth, then active gate count.

## Population

The experiment contains 16 workloads at 8, 12, 16, 20, 24, 28, and 32
logical qubits. It uses square-grid and hexagonal-lattice topologies and five
compiler seeds. The complete experiment contains 2,240 rows.

## Program-body duration

The duration model assigns 500 ns to SWS and 200 ns to every beamsplitter
operation. Diagonal Z operations and synthetic preparation placeholders take
zero time. The reported duration is the weighted critical path of the final
routed program body.
