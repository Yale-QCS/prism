# Ready-to-insert: Proposition 1 (the reduction) + the 2-factorization unification

Two pieces of intellectual content the paper is missing, both now safe to assert
(the surrounding claims are verified in `scripts/research/theory_verification/` and
`scripts/research/quotient_embedding/`). Drafted for ratification, not inserted: a
Proposition + proof is subtle enough that you should check the statement before it
goes in the paper proper. `conceptual_spine.md` §3 calls Proposition 1 "the paper's
central structural statement"; it is currently a mid-paragraph aside at `03:161`.

---

## Proposition 1 (realization-annotated routing reduces dynamic-quotient routing)

**Setup.** Let `G=(V,E)` be the fixed physical graph and `Pi_0` a partition of `V`
into rail pairs, one per logical qubit. Routing inserts a sequence of physical
SWAPs; let `pi_t` be the rail-to-vertex placement after `t` SWAPs and `Pi_t` the
induced partition. A logical two-qubit gate `g` carries a realization set
`R(g) = {(a_i, b_j)}` of rail pairings. Define its **annotated cost on `G`**

  `c_G(g,t) = min over (a_i,b_j) in R(g) of d_G(pi_t(a_i), pi_t(b_j))`,

and let `c_Q(g,t)` be the distance in the quotient `Q(G,Pi_t)` between the two
logical nodes of `g`.

**Claim.**
1. `g` is executable at time `t` (some realization's rails adjacent on `G`) iff its
   logical endpoints are adjacent in `Q(G,Pi_t)`.
2. `c_G(g,t) = 0` iff `c_Q(g,t)=0`, and the per-gate SWAP cost the router charges to
   make `g` executable equals `c_G(g,t)-1` under either view, evolving identically
   because a SWAP on `G` is a SWAP on the rails and updates `Pi_t` the same way.

Hence routing the realization-annotated circuit on the fixed `G` reproduces the
executability and the per-gate routing cost of routing on the moving quotient
`Q(G,Pi_t)`. Deferred realization is the change of coordinates under which
dynamic-graph routing becomes fixed-graph routing.

**Caveat (state it, it is the honest part).** The contracted quotient's
shortest-path metric is NOT `c_G`: contracting a rail pair permits a free hop
between a qubit's two rails, so a quotient shortest path can be shorter than any
rail-to-rail path on `G`. The router scores each gate by `c_G` (realization-min
between its own endpoints), not along quotient paths. The coincidence is of
executability and per-gate cost, not of the full graph metric. (This is exactly
what `03:161` already says in prose; the Proposition just names it.)

**Proof.** (1) A parallel edge between logical nodes `A,B` in `Q(G,Pi_t)` exists iff
some rail of `A` is `G`-adjacent to some rail of `B` (definition of the quotient),
iff some `(a_i,b_j) in R(g)` has `pi_t(a_i) ~ pi_t(b_j)`, iff `g` is executable. (2)
`c_G(g,t)=0` iff some realization is adjacent iff (by 1) the endpoints are
quotient-adjacent iff `c_Q(g,t)=0`. To make a chosen realization `(a_i,b_j)`
executable the router SWAPs one rail toward the other along a shortest `G`-path,
`d_G(pi_t(a_i),pi_t(b_j))-1` SWAPs; it takes the realization-min, `c_G(g,t)-1`. Each
such SWAP is a transposition of two physical sites, which is simultaneously a move
on `G` (updating `pi_t`) and the corresponding edge flip of `Q(G,Pi_t)` (updating
`Pi_t`); the two descriptions evolve in lockstep. With executability and per-gate
cost coinciding at every step, the annotated process on `G` reproduces the quotient
process gate-for-gate. QED

**Why it earns promotion.** It is the formal content behind "the two views are two
views of one object": the limit cases are corollaries (collapse `R(g)` to one
element -> SABRE on the rail graph; freeze `Pi` -> SABRE on one fixed quotient), and
it is why the host router's distance tables survive unchanged (Section 4). Place it
at the head of S3.3, ahead of the connectivity-class material, and make the limit
cases a one-line corollary.

---

## Observation: one 2-factorization, two dividends (unifies §3.3 and §8)

The same combinatorial object delivers BOTH advantages of the two-port structure,
and the paper presents them as unrelated. Petersen 2-factorization of an abelian
demand graph `D` (max degree `Delta`):

- **Placement dividend (§3.3).** Decompose a max-degree-4 `D` into two max-degree-2
  subgraphs and lay each along one row of a `2 x n` ladder: every interaction is
  nearest-neighbor, zero routing (`euler_ladder.py`; `K_6` on `2x6` is the tight
  case, `k6_ladder_witness.py` verifies 15/15 with all rails delocalized).
- **Scheduling dividend (§8).** Decompose `D` into `ceil(Delta/2)` max-degree-2
  subgraphs: each subgraph is one time step using <=2 ports per qubit, so the depth
  floor is `ceil(Delta/2)` vs `Delta` fused (`verify_port_parallelism.py`, an
  up-to-2x win).

These are the SAME decomposition. A 2-factor (max-degree-2 subgraph) is at once a
ladder row you can place without routing and a port-parallel layer you can execute
in one step. So the connectivity gain and the parallelism gain of delocalization are
one structure seen twice, which is the §3.3<->§8 through-line the paper is missing.
The right basis for the `ceil(Delta/2)` floor is this 2-factorization (Petersen), not
the split-thickness theorem the prior draft mis-cited (audit T2.6).

**Suggested use.** A sentence in §8's port-parallelism paragraph tying the floor to
the §3.3 ladder construction ("the 2-factorization that lays `D` on a ladder without
routing is the same one that schedules it in `ceil(Delta/2)` port-parallel layers"),
and the `ceil(Delta/2)` claim restated as a result, not a conjecture (memory
`[[project_port_parallelism_floor]]`).
