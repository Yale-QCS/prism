# Prior-work comparison plan (the "we beat our own greedy" defense)

The biggest single reviewer risk for the PRIMARY result (prism vs greedy,
[[project_prism_vs_greedy_mechanism]]) is "you only beat a baseline you wrote."
This memo is the concrete plan for what we compare against, why each comparison
is or is not portable, and the one runnable head-to-head a reviewer most wants.

Sources verified 2026-06-09: RTG [arXiv:2502.04138](https://arxiv.org/abs/2502.04138)
(HTML + abstract), Jin "Iceberg Beyond the Tip" [arXiv:2504.21172](https://arxiv.org/abs/2504.21172),
AQORN / Flexible-FT (anon MICRO 2026, see `iceberg_multireal_competitors.md`),
TeleSABRE [arXiv:2505.08928](https://arxiv.org/abs/2505.08928), dSABRE
[arXiv:2605.21960](https://arxiv.org/abs/2605.21960). Cross-refs:
`teleport_routing_priorart.md`, `iceberg_multireal_competitors.md`.

## TL;DR

1. **`greedy` is a faithful, even generous, proxy for the AQORN/Jin
   placement-time realization-choice paradigm, adapted to a constrained
   coupling map.** This is defensible from the code, not rhetoric
   (`GreedyCommit._greedy_pick` = per-op argmin total 2Q chip-distance under an
   iteratively SabreLayout-refined placement). Defend it explicitly; it is the
   load-bearing baseline.
2. **No published method is a clean drop-in head-to-head on our PRIMARY axis**
   (in-loop realization choice on a constrained map with encoded qubits). Each
   competitor is incomparable for a specific structural reason, listed below.
3. **The portable head-to-head that answers the reviewer is an RTG-STYLE
   two-pass selector reimplemented inside OUR IR** (route -> measure per-op
   distance pressure -> reselect realizations -> reroute), run as a third
   ablation config against the in-loop `min`. This is runnable on our exact
   benchmark, needs no spare qubits and no RTG source, and directly tests
   "two-pass (RTG/AQORN paradigm) vs in-loop coupling (ours)."

## 1. Defending `greedy` = the AQORN/Jin paradigm on a constrained map

What `GreedyCommit` actually does (`commit_policies/greedy.py`):

- `_initial_layout`: trivial (or random) placement, greedy picks under it.
- `_route_and_recommit` (the refinement loop, up to `max_iterations=4`): emit the
  flat committed circuit, run `SabreLayout(skip_routing=True)` to refine the
  placement (Qiskit's iterative forward/backward SabreSwap layout pass), then
  **re-pick each logical op's realization by `_greedy_pick`**.
- `_greedy_pick`: for each op, `argmin` over realizations of the **total 2Q chip
  distance** of that realization's two-qubit gates under the current layout
  (`coupling_map.distance(pa, pb)` summed over the realization's CX pairs).

That is exactly the AQORN/Jin move, term for term:

| AQORN / Jin (their words) | `GreedyCommit` |
|---|---|
| "logical gate cost is strongly context dependent" on realization + placement | cost = total 2Q chip-distance of the realization under the placement |
| "selecting the cheapest encoding based on qubit placement" | `argmin` chip-distance per op, given the layout |
| greedy noise-biased qubit packing (who shares a patch) | `SabreLayout`-refined placement feeding the next pick round |
| **choice is at PLACEMENT, before/without routing** | **picks are fixed by the commit policy; the router sees a committed circuit** |

The one substitution is the cost metric: AQORN/Jin assume negligible-cost
movement (all-to-all trapped ion / flexible neutral-atom), so their "cheapest
realization" is by gate count / patch alignment; we assume a **constrained
coupling map**, so the natural cost is chip-distance. Same paradigm
(choose-cheapest-realization-given-placement), instantiated on the regime those
papers explicitly do not handle. This is not weakening their method; it is the
faithful port of it to the setting our contribution targets.

**Why greedy is generous, not a strawman:** it gets a SabreLayout-refined
placement AND a full per-op argmin AND iterates the two to convergence. That is
the strongest a placement-time-choice method can do on a constrained map. The
prism win over it is therefore not "we used a smarter router than a dumb
baseline"; it is the value of **co-optimizing the choice with SWAP routing
instead of fixing it before routing**, which the frozen-pick ablation isolates
(`pick_ablation.py`: pick-share 56% depth / 94% swaps at n=8, 70% depth at n=20;
the pinned-greedy-picks-into-prism's-router config B is the apples-to-apples
control that proves the coupling is the win, not the SABRE router alone).

**Paper sentence to land it:** "Our `greedy` baseline instantiates the
placement-time realization-choice paradigm of AQORN [cite] and Jin et al.
[2504.21172] on a connectivity-constrained map: it selects each logical gate's
cheapest physical realization under an iteratively refined SABRE placement. The
prism contribution is to defer that choice into the routing `min`; the frozen-pick
ablation shows the deferral, not the router, carries the majority of the win."

## 2. Incomparability map (which competitors, and exactly why each can't be a drop-in)

| competitor | published setting | why NOT a drop-in head-to-head | what it IS to us |
|---|---|---|---|
| **AQORN** (anon MICRO 2026) | Iceberg, all-to-all / negligible-move (neutral atom), realization at placement | no connectivity-constrained routing at all; their realization choice gets nothing from routing because there is none | the paradigm our `greedy` proxies; cite as concurrent evidence the lens is right + as the thing prism extends INTO routing |
| **Jin "Iceberg Beyond the Tip"** [2504.21172] | Iceberg, all-to-all trapped ion (H2), A*-tree-search over gate options | all-to-all, no routing; co-compilation search, not a router | public prior-art anchor for the realization-choice lens; must be cited; same "no routing" incomparability |
| **TeleSABRE** [2505.08928] | MULTI-CORE, in-loop SABRE min over {swap, TeleData, TeleGate} | teleport candidate exists ONLY at core boundaries; intra-core gates never see one; structurally a different problem (inter-core comm minimization) | nearest in-loop-min mechanism; distinguish by "flat single device, every gate sees the choice" |
| **dSABRE** [2605.21960] | MULTI-CORE, two-phase (intra-core swap, then inter-core teleport) | multi-core + two-phase, not a flat per-gate min | same multi-core incomparability; note it is 2026 (re-sweep near submission) |
| **RTG** [2502.04138] | single device, BARE 1:1 qubits, teleport CNOTs through SPARE physical qubits, POST-PASS after SABRE | (a) bare qubits, no encoding / realization choice; (b) needs unused physical qubits for 1D teleport chains; (c) post-pass not in-loop; (d) it is a connectivity-EXTENSION method, not a realization-CHOICE method | the SECONDARY teleport arc's nearest single-device neighbor; NOT a baseline for the primary spine |

The clean one-liner for the related-work section: **AQORN/Jin are incomparable
because they have no routing (all-to-all); TeleSABRE/dSABRE because they are
multi-core (the teleport choice is boundary-forced); RTG because it is a
spare-qubit connectivity-extension on bare qubits, not encoded-realization
choice. The constrained-map, encoded, in-loop-realization-`min` cell is empty,
and `greedy` is the faithful in-cell baseline (the placement-time paradigm
ported into it).**

## 3. RTG portability verdict (the head-to-head a reviewer most wants)

**Question from the handoff:** is RTG's setup portable to our dual-rail /
constrained-map benchmark (runnable or reimplementable), or only describable?

**Verdict: only describable as published; NOT a clean drop-in; but a runnable
RTG-STYLE strawman is the right substitute.** Reasons, from the verified HTML:

1. **No public code.** No GitHub link in the paper. A faithful rerun is a full
   reimplementation, not a `pip install`.
2. **It is not a realization-choice method.** RTG keeps the algorithm's gates
   fixed and ADDS virtual connectivity by teleporting CNOTs through chains of
   *unused* physical qubits. There is no encoded logical gate and no candidate
   realization set. So it does not address the PRIMARY contribution at all;
   running it would compare apples (connectivity extension) to oranges
   (realization choice).
3. **It needs spare qubits our benchmark does not have.** RTG's premise is "20
   logical on 50 physical leaves 30 auxiliary qubits for teleport chains." Our
   benchmark fits the coupling map TO the encoded circuit (dual-rail = 2 wires
   per logical, grid sized to ~`n` logical), so spare physical qubits are scarce
   to absent. RTG starves in exactly our regime; this is itself a finding to
   state (the constrained-packed encoded setting is where RTG's premise fails).
4. **It is a post-pass.** Structurally identical to AQORN's separate translator
   and to a two-pass selector, which is the thing the prism in-loop `min` is
   defined against (`teleport_routing_priorart.md`: a two-pass selector
   "COLLAPSES the routing-integration differentiation").
5. **Bare qubits + heavy-hex Eagle + line-SABRE baseline.** Different device,
   different metric framing, mid-circuit-measure-heavy; not our encoded
   constrained-grid setup.

### The portable substitute (runnable, recommended)

Reimplement an **RTG-style two-pass realization selector inside our own IR** and
run it as a third config in `pick_ablation.py`:

- **Config A** = greedy (placement-time choice, the AQORN/Jin proxy). [exists]
- **Config B** = frozen (greedy picks pinned into prism's router). [exists]
- **Config C** = prism (in-loop `min`). [exists]
- **NEW Config D = two-pass / RTG-style:** route once with default picks; measure
  per-op routing pressure (post-route distance / swap count touching each op);
  reselect each op's realization to minimize that measured pressure; reroute.
  Iterate once or twice. This is the RTG/AQORN "route -> identify -> reselect ->
  reroute" structure expressed on OUR realization sets and OUR constrained map.

What D buys the paper: it is the **in-paradigm published-method comparison** a
reviewer demands, made portable by reusing our machinery (no RTG source, no spare
qubits). The hypothesis (and what `teleport_routing_priorart.md` predicts): D
recovers much of prism's win on the DISTANCE-dominated circuits (where a single
reselect after seeing the route is enough) but underperforms the in-loop `min` on
the COUPLED circuits (qaoa-like crz-dense, where the per-op choices interact and
one reselect pass cannot converge). If D ~= C everywhere, that is an honest
negative we must report (the in-loop integration would be inessential). If D < C
on the coupled circuits, that is the positive: **the in-loop coupling beats the
two-pass paradigm RTG/AQORN use, on the constrained map, measured on the same
benchmark.** Either way it closes the "did you compare to prior work's structure"
gap with a runnable number.

Effort estimate: D reuses `PinRealizations` (already built for config B) + the
existing routing entry point + a post-route pressure read. A focused day, not a
reimplementation of RTG. Hand to the experiment agent as a P2 task; it is lower
priority than the Iceberg generality demo but it is the single most direct answer
to the headline reviewer objection.

## 4. The trivial / logical baselines (the "obvious approach" floor)

`trivial` and `logical` are standard-transpile-the-encoded-circuit baselines (no
realization choice / default pick). Label them in the paper as "prior art = the
obvious approach: lower to a fixed realization and route with stock SABRE," and
surface their numbers. They are not a contribution of ours to defend; they are
the floor that shows realization choice matters at all. `greedy` is the
*sophisticated* prior-art proxy that the contribution must beat; trivial/logical
are the naive floor.

## 5. What to tell the paper track

- Open related work with the realization-choice lens AS PRIOR/CONCURRENT work
  (AQORN, Jin 2504.21172), not as our novelty. Stake the narrow claim:
  realization choice folded into the **connectivity-constrained routing `min`**,
  which all of them lack (all-to-all or multi-core or bare-qubit-spare-chain).
- State the incomparability map (section 2) explicitly; do not let a reviewer
  infer we dodged a comparison. Each "incomparable" has a one-sentence structural
  reason.
- Defend `greedy` as the faithful, generous in-cell baseline (section 1), and
  lean on the frozen-pick ablation to convert "beat your own baseline" into
  "isolated the mechanism (routing-realization coupling) that the prior paradigm
  structurally cannot capture."
- If bandwidth exists, run Config D (the RTG-style two-pass) for the one runnable
  published-paradigm head-to-head. Report it honestly whichever way it falls.

## Unverified / to recheck before submission

- RTG "no public code" is from the paper HTML having no repo link; recheck the
  authors' pages near submission in case a release appears.
- AQORN / Flexible-FT are anonymized MICRO 2026 co-submissions (confidential);
  cite Jin 2504.21172 as the public anchor. Concurrent submissions usually are
  not held against each other for novelty, but their framing will be in
  reviewers' heads, so the positioning above must hold regardless.
- Re-sweep arXiv for dSABRE / new single-device teleport-routing preprints near
  submission (the space moved in 2026).
