# A-Q2 (myopia) and D-Q2: does commitment shape future routing?

prism-66 review (2026-10-08): adopted. Correction before use: §4 says "PRISM commits only at this point", but the release valve (state_methods.rs:91-144) can commit a non-executable realization and sub-route it. Every draft must scope the claim to executable realizations and name the release valve. Decision: the exact oracle (block 07) leaves the paper; A-Q2 is answered with this argument and the tie-break result.

Analysis on revision r2 as of 2026-10-08. No compiles. One check under a minute (§3.3). Paths are relative to `.`.

## Verdict

The hypothesis is **true for routing** (layout, SWAP sequence, SWAP count) in every configuration the paper uses. It is **false in three narrower senses**, and the rebuttal must not overclaim:

1. **Timing.** The pick decides which rails and couplers are busy. So it can delay, or serialize, a later gate on those rails. Depth and duration depend on the pick, and the router's pick rule (`load` or `default`) looks at past load, not at upcoming gates. That is myopic in time (§3.2).
2. **Time-aware variant.** With `wait_scale > 0`, the committed realization's rails set the ready times, and the SWAP score reads them. The commit then does change later SWAP choices. This variant is off in core/breadth/s53.
3. **Outer selection.** Under the `error` (or depth, duration) objective, the pick changes each start's score and therefore which start is kept. s53 shows this: all 64,500 start pairs have equal SWAP counts, but 309 of 1,500 runs report a different final SWAP count (139 / 93 / 77 per graph), because the kept start changed.

Also, one part of prism-66's framing is wrong: Greedy and PRISM do **not** share SWAP choices. They share SABRE's search and parameters, but PRISM's per-gate cost is the minimum over realizations and its executability test is "any realization adjacent". That difference is the whole SWAP gain. So the remaining myopia is "SABRE's greedy search applied to PRISM's cost function". It is not "SABRE's own and not PRISM's".

## 1. Does commitment change state that later routing reads?

### 1.1 Where commitment happens

- **Atomic commit at execution (PRISM, the normal path).** A `MultiTwoQ` node reaches `update_route` (`crates/src/sabre/route.rs:529`) when its predecessors are done, or after a SWAP makes a realization adjacent (`state_methods.rs:59-83`, where any adjacent realization is enough). `commit_or_defer_multi` (`crates/src/prism_routing/ext.rs:430-496`) commits only when some realization has **all** its pairs at distance 1 (`ext.rs:442-445`, `146-159`, `167-195`, `230-253`). Otherwise it defers the node into the front layer (`ext.rs:491-494`).
- **Commit at route entry (Greedy).** `_greedy_commit_ctx` (`src/marabbecca/lowering/commit_policies/prism_routing.py:637-683`) collapses every set to its nearest realization under the entry layout. It does this before each of the 33 route invocations of a start (`prism_routing.py:474-492`).
- **Commit at front-layer entry (front-commit ablation).** `ext.rs:446-470` freezes the nearest realization at first deferral. The score then uses that witness (`ext.rs:539-541`, `556-557`; extended set `ext.rs:746-749`).
- **Release-valve sub-route (PRISM too, rare).** After `attempt_limit` SWAPs without progress, `force_enable_or_subroute` (`crates/src/prism_routing/state_methods.rs:91-105`) can pick the nearest **non-executable** realization (`ext.rs:271-301`) and sub-route it with SWAPs specific to that realization (`state_methods.rs:111-144`). This is the only place PRISM commits before execution, and the only place a PRISM commit changes the layout.

### 1.2 State read by later routing, path by path (atomic commit)

| State | Changed by the commit? | Evidence |
|---|---|---|
| Layout `NLayout` / Python `v2p` | No. Only `apply_swap` mutates it. | `route.rs:463-474`. Python updates `v2p` only on SWAP events (`prism_routing.py:547-551`). COMMIT emits the realization at the current `v2p` (`prism_routing.py:535-539`, `870-891`). |
| Rail-to-pair map, output permutation | No. Same as layout. The final layout is `trace[1]` (`prism_routing.py:314, 323, 748-751`). | as above |
| Dependency DAG, released successors | No. Dependencies use the **union** of rails over all realizations (`prism_routing.py:812-835`, `838-865`). The successors released are the same for every pick (`route.rs:593-600`). | |
| Front layer, extended set | No. Both are rebuilt from the layout and the done set (`route.rs:1048-1058`). | |
| SABRE decay | No. It is reset after any routed node (`route.rs:1060-1062`). | |
| RNG | No. Only `choose_best_swap` draws from it. The sub-route seed is `seed+1`, independent of picks (`state_methods.rs:127`). | |
| Pauli frame | None exists. Each realization carries its own diagonal correction (`encodings/dualrail.py:111-132`; `research/theory/realization_corrections.md`). | |
| `phys_load` | **Yes** (`ext.rs:485-488`). It is read only by `executable_choice_balanced` (`ext.rs:167-195`), which chooses among executable realizations, which again changes nothing above. It never enters SWAP scoring. | |
| `ready` (rail busy times) | **Yes**, when durations are passed (`route.rs:476-503` reads `realizations[r]`). Durations are passed only if `wait_scale > 0` (`prism_routing.py:490`). With durations passed, `choose_best_swap` reads `ready` (`route.rs:815-838`), and the pick rule becomes `executable_choice_ready` (`ext.rs:471-472`). | |

So, by induction over the routing loop (`route.rs:1008-1066`): with `wait_scale = 0`, the SWAP sequence and the final layout of a route are a function of (DAG, initial layout, seed). They do not depend on any pick among executable realizations, and the `tie_break` setting cannot change them. s53's 64,500/64,500 equal start pairs are therefore a code-level consequence, not luck. The check in §3.3 confirms it at the level of the SWAP sequence.

### 1.3 By operation

- **CR_z.** Four realizations, each one `crz` on one rail pair, plus an `rz` correction on the target rail when `ra = 1` (`dualrail.py:119-132`). It has one 2Q pair. The commit requires that pair to be adjacent. It moves no photon.
- **rx → rswap.** One fixed realization, `RSwapGate` on the qubit's own two rails (`dualrail.py:96-101`). There is no choice, so there is no commitment. Its 2Q pair still has to be routed adjacent.
- **x.** Fixed `swap(0,1)` (`dualrail.py:89-93`). This **does** move a photon between rails. The router treats it as a gate on wires, though, not as a relabeling, so the layout is unchanged. "A gate moves no photons" is false as a slogan. The precise invariant is "a commit never changes `v2p`".
- **Logical SWAP, aligned and crossed.** Both realizations exist (`dualrail.py:135-153`). The crossed one includes its intra-pair correction, and as a permutation of wire contents it equals the aligned one. Contents [A0,A1,B0,B1] go to [B0,B1,A0,A1] in both. They never reach PRISM's router, because `ElideLogicalPermutations` removes every input SWAP before lowering (`dualrail.py:73-76`, `staged_pms.py:142-171`). Only Logical-SABRE commits them (paper block 01). **Boundary of the claim:** if the compiler implemented Fig. 5(c), the crossed matching as a tracked frame or relabeling, the commit **would** change the rail-to-pair map, and the hypothesis would fail. The implementation does not do this.
- **Multi-interaction realizations** (iceberg CX, repcode CX, and the logical SWAP in principle). An atomic commit needs **all** pairs adjacent (`ext.rs:442-445`). It is emitted in place with no layout change. A non-atomic commit (sub-route with SWAPs between sub-gates) occurs only through the release valve (§1.1).
- **Joint herald, rz.** Fixed. There is no choice.

## 2. Where the choice is made, and what delayed commitment changes

PRISM makes **no routing-relevant choice at commit**. The choice that matters is made implicitly, one SWAP at a time, in the score. Relative to Greedy, delayed commitment changes exactly four things in the SWAP sequence:

1. **Front-layer cost.** Each gate costs `min_r Σ dist` (`ext.rs:44-53`, used in `ext.rs:536-548`, `550-563`), where Greedy uses the distance of `r*` fixed at entry.
2. **Lookahead cost.** The same minimum is applied in the 20-gate extended set (`ext.rs:743-771`).
3. **Executability.** A gate leaves the front layer when **any** realization is adjacent (`state_methods.rs:59-83`; `ext.rs:146-159`), not only when `r*` is. This is the direct SWAP saving.
4. **Release valve.** The valve can target a gate's nearest realization (`ext.rs:271-301`).

Front-commit changes 1 to 3 to "the witness frozen at front-layer entry".

**Where myopia can live.** It can live only in the SWAP search, which has three parts:

- **(a) SABRE's search.** It takes one SWAP at a time with a bounded lookahead and has no optimality bound. This is common to every SABRE-based router.
- **(b) Two blind spots of the minimum-over-realizations cost.** First, each gate's nearest realization is taken independently, so two gates' nearest realizations can conflict. Stock SABRE has the analogous per-gate independence. Second, the minimum is flat across SWAPs that move toward *different* realizations (unit test `ext.rs:853-890`: both SWAPs score −1). (b) belongs to PRISM's cost, not to SABRE.
- **(c) The release valve's early commit.**

s53 shows that (b) is real run by run. PRISM against front-commit gives summed SWAP reductions of 8.3% [5.4, 11.0] on the grid, 8.7% [7.0, 10.3] on the hexagonal lattice and 1.5% [−0.6, 3.5] on heavy-hex. But PRISM uses **more** SWAPs than front-commit in 160, 145 and 198 of 500 runs (`artifacts/paper/paper_export/s53/summary.json`, `l66`). Holding the set open wins on average. It does not dominate.

The one fixed-layout oracle pair where PRISM is not optimal (`rand_dag_n4_deep_s43_chain8`, layout 1: S4 = 2, PRISM = 3, SG = 3, Greedy = 3) must be search myopia (a)/(b). It cannot be commitment myopia.

## 3. Is the precise claim true?

### 3.1 Claim, stated so that it is provable

> Let the routing state be (layout L, done set D, plus SABRE's decay, RNG and front and lookahead sets, all functions of L, D and the step history). If gate g is ready and some realization of g is adjacent under L, then committing any adjacent realization moves the state to (L, D ∪ {g}) with the same auxiliary state. Every continuation, and so every later SWAP and every later gate's executability, is the same for every adjacent pick. Moreover, executing g now is weakly dominant over delaying it under SWAP count. Any SWAP sequence feasible from (L, D) is feasible from (L, D ∪ {g}), because dependencies only constrain.

This is true for any router whose cost is SWAP count, not just SABRE. The oracle's state space (layout, done set) with a "lex-smallest support" closure (`scripts/paper/oracle.py:223-257`) already assumes it: the support used is not part of the state.

### 3.2 Where it is false: timing (minimal example)

Take a 2×4 grid with top row `c1 – c0 – a0 – b0` and bottom row `· – · – a1 – b1`. Program: `CRz(A,B); CRz(A,C)`. Both gates are diagonal.

- For gate 1, the realizations (a0,b0) and (a1,b1) are both executable.
- For gate 2, only (a0,c0) is executable.

If gate 1 picks (a0,b0), both gates share rail a0, so the 2Q depth is 2. If it picks (a1,b1), the two gates are on disjoint rails, so the 2Q depth is 1. The SWAP count is 0 either way. Neither tie rule looks ahead to gate 2. `default` takes index 2 = (a1,b0), which is not executable here. It then falls to the lowest executable index, (a0,b0), and gets depth 2. `load` with zero past load ties and makes the same pick. It moves only on past load, never on gate 2. So the pick can "block" a later gate in **time**, never in **space**.

This is the mechanism behind s53's l.68 depth numbers. Depth reduction against Greedy is 7.8% with `load` and 7.4% with `default` on the grid. Duration reduction is 6.9% with `load` and 5.7% with `default`.

### 3.3 Check run here

`tiecheck.py` in this scratchpad routes 12 oracle-catalog instances × 4 random layouts from a fixed layout with `tie_break` `load` against `default` (4 SWAP trials, seed 7). The SWAP event sequence and final layout are identical in **48/48** routes. The committed realizations differ in **19** of them.

## 4. Draft A-Q2 (168 words)

> Committing a realization cannot block a later gate. A CR_z realization is a gate on two rails that are already adjacent, and it moves no rail. After the commit, the layout, the executed gates, SABRE's front and lookahead sets and its decay state are the same whichever executable realization was chosen, so the rest of the route is the same. PRISM commits only at this point. Rerunning PRISM with Greedy's rule for choosing among executable realizations changes the picks but reproduces the routing SWAP count of all 64,500 layout starts. Myopia can therefore enter only through the SWAP search: SABRE's one-SWAP greedy step with a 20-gate lookahead, scoring each gate by its nearest realization. Like SABRE, this search has no optimality bound, and it does not win every run: committing each gate on front-layer entry costs 8.3% and 8.7% more SWAPs in total on the grid and hexagonal lattice, yet uses fewer in 29–40% of runs. The pick affects only timing, since it decides which rails are busy.

## 4b. Paper version (§5.3 or §4, three sentences)

> Committing a realization cannot make a later gate harder to route: each realization acts on rails that are already adjacent, so the layout and the router's state after the commit are the same for every executable choice. All of \sysname{}'s routing decisions are therefore SWAP choices, made by SABRE's search scored with each gate's nearest realization, and any myopia enters there rather than at commitment. Consistently, changing the rule that picks among executable realizations leaves the routing SWAP count of every layout start unchanged and changes only depth and duration.

## 5. The oracle

### 5.1 What it adds beyond the argument

The argument settles commitment. It does not measure myopia in the SWAP search (§2 a/b). The oracle is the only measurement of that search against optimal: PRISM totals 88 against an optimum of 87 over 85 fixed-layout pairs. That evidence is weak:

- the instances have 3–4 logical qubits and ≤ 15 CR_z gates;
- "PRISM, one route" is the **best of 40** SABRE trials (`fixed_layout.py:26, 53`), which masks greedy errors;
- at this size even Greedy's heuristic is near-optimal for its binding (Greedy − SG = 5 SWAPs over 85 pairs). So the instances barely exercise the search whose myopia A asks about.

The SG decomposition (32 of 37) speaks to Greedy's commitment cost, which front-commit and Greedy already measure at full scale. For D-Q2, "an exact router with more options never does worse" (S4 ≤ S1) is true by construction. It shows the sets help an optimal router, not that PRISM's mechanism transfers.

### 5.2 Imprecisions

1. **"Dijkstra".** The search is A* with an admissible, and consistent, bound (`oracle.py:23-28`; priority `g + h` at `oracle.py:369-370`). The text calls it Dijkstra in README.md, in rebuttal.md l.22 and in paper block 07.
2. **"One route from the layout".** It is the best of 40 trials (README table, Results; rebuttal.md l.40 "PRISM uses 88").
3. **"21 CR_z-only circuits".** The README pre-registration says 21, but `INSTANCE_CATALOG` has **20**, and the results say "17 of 20".
4. **rebuttal.md l.22, "four retained realizations route all 17 with none".** This omits that the first run uses a **free joint initial layout**, under which S4 = 0 on all 17 (the README says these instances are "too small… to measure myopia"). S1 fixes the **default**, not Greedy's binding. The README states both caveats. rebuttal.md drops them.
5. **rebuttal.md l.40.** "32 of Greedy's 37 extra SWAPs … are the cost of committing early, not of SABRE's heuristic" holds only with layout search removed. The paper's Greedy rebinds at each of 33 route invocations after refinement. This should be stated.
6. **rebuttal.md l.40, front-commit numbers.** 24.4% / 20.7%, 8.8% / 7.7%, 377 / 161 of 640, 124 and 63 runs are the **legacy** 16-workload rows. They are superseded by s53 (`summary.json` `l66`): PRISM against front-commit summed 8.3% / 8.7% / 1.5%, 267/160, 312/145, 264/198 of 500 per graph; front-commit worse than Greedy in 71 / 99 / 67 runs.
7. **rebuttal.md l.40, "88.8% of commits have exactly one adjacent realization … so the gain comes from routing".** The conclusion is right, but the statistic is not needed. The pick is routing-irrelevant whatever the share is (§1.2), so the 88.8% figure and ρ = 0.08 can go.
8. **s53 l.68, "reproduces every per-run SWAP count".** This is false per run: 309 of 1,500 runs differ through start selection. It is true per start. The s53 reading rule already says to restate it per start. Make sure the final text says "every layout start", not "every run".
9. **Model mismatch.** The oracle uses local init (no herald), CR_z only and unit SWAPs. The README states this. The paper block does not.

### 5.3 Recommendation

**Cut the oracle from the paper** (drop block 07). Answer A-Q2 with the argument in §4b plus the tie-break invariance, both already in §5.3. Its one unique number (PRISM within one SWAP of optimal on 85 tiny best-of-40 cases) does not bear on n = 8 and does not stress the search. Its "Dijkstra" description is wrong, and the free-layout run invites "trivially routable" objections.

In the rebuttal, keep at most one hedged sentence, for example: "on 85 exhaustively solved instances with 3–4 logical qubits, PRISM's route from a fixed layout is within one SWAP of optimal in total". Or drop it. For D-Q2, use the interface argument instead. A host router needs only two functions, gate cost = min over realizations and executable = any realization adjacent. The commit is a free, routing-irrelevant pick (§3.1), so it can be delegated to the scheduler.
