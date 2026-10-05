# Rail-balanced SWAP tie-break (2026-09-11, negative, stripped)

Kernel flag `multi_swap_tie_break_load` on `Heuristic`; in `choose_best_swap`, among
equal-score SWAPs keep those minimizing `RealizationFrontLayer::post_swap_load(swap, dist)`
= sum over multi nodes of `phys_load` at the sites of the node's closest realization under
the virtual swap; then the usual seeded draw. Python knob `PrismRouting.SWAP_TIE_BREAK_LOAD`.

Prism, paper set, seed 0, commute on + rescheduler on: swaps objective +6.0% swaps, depth +0.5%,
same-rail runs 943 -> 983; depth objective +14.2% swaps, depth +0.7%. Site-indexed load pushes
work to fresh sites (costs swaps) and does not balance rails. Not kept.
