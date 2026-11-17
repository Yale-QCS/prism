# Separation, cadence, and the two dividends of delocalization

Written 2026-06-10 (user spitball: how far do depth-optimized circuits
delocalize; can a cadence bound be related to a travel-radius bound; how does
this connect to the quotient theory's disjoint-neighborhood optimal placement;
is the optimal delocal placement reachable within a cadence window).
Numerics: `diagnostics/routing/separation_profile.py` (built on the validated
replay in `delocalization_intervals.py`); prism, depth objective, seed 42.

## 1. The routing light cone (cadence => radius, rigorous)

In a routed circuit, each layer's gates act on disjoint wires, so a rail moves
at most one edge per layer and the rail separation d(t) of a logical qubit
changes by at most 2 per layer (graph-metric triangle inequality, both rails
moving). If the qubit is co-located (d = 1) at layers t1 and t2, then for
every t between, d(t) <= 1 + 2 min(t - t1, t2 - t), so over a window of W
strictly-non-adjacent layers, max separation obeys

    d_max <= W + 2   (and the excursion costs >= 2(d_max - 1) swaps
                      involving that qubit's rails: each unit of separation
                      change is at least one rail-involving swap)

A check-every-X-layers regime therefore confines every qubit to a
delocalization radius ~X, and any policy that rejoins at checks pays a
per-window swap floor of 2(d - 1) for whatever separation d it reached.
Congestion (swaps blocked by other traffic, the user's caveat) only tightens
this; the bound needs no congestion model. Units caveat: cadence is
physically time, layers proxy it; under the SWS durations
(`reference_dualrail_noise_mehta_sws`) crz layers are ~3x intra-rail layers,
a refinement that rescales but does not change the structure.

## 2. Degree saturation at separation 3 (the quotient-theory connection)

The user's "optimal placement = disjoint rail neighborhoods" is exactly
right, and it saturates almost immediately. Two vertices share a common
neighbor iff their distance is exactly 2 (on triangle-free topologies, which
grid and heavy-hex are). So:

- d = 1 (co-located): neighborhoods disjoint but one edge each is spent
  internally; interior grid pair reaches |N(a0) u N(a1)| = 2*Delta - 2 = 6
  distinct neighbor vertices, plus the self-loop.
- d = 2: the unique bad distance; geodesic midpoints are shared, the union
  shrinks, shared neighbors produce multi-edges to the same partition.
- d >= 3: fully disjoint neighborhoods, no internal edge; the union reaches
  2*Delta = 8 on interior grid, the maximum.

So the CONNECTIVITY dividend of delocalization is a constant: +2 quotient
edges over co-location (6 -> 8 on grid interior), fully harvested at
separation 3, which is reachable from co-location in ONE swap layer (both
rails step outward, d: 1 -> 3) and reversible in one. Even a tight cadence
(X >= ~4 layers) retains the entire degree dividend forever: step out, sit
at d = 3, step back, check. Multi-edges (shared partitions among the
neighbor set) add no logical degree but are not pure waste: they are
realization multiplicity / parallel interaction bandwidth
(`angle_splitting.md`); measured multi-edge share is 6-31% of quotient edges.

What a tight cadence CANNOT retain is the second dividend:

## 3. The embedding dividend (what long leashes actually buy)

Placement is inverse vertex splitting (`quotient_embedding.md`, Eppstein
split thickness): the two rails of a split vertex travel to sit NEAR their
distinct demand-graph neighbors. For demand graphs with global structure
(QFT's phase ladder, K_n), the split halves of a vertex sit far apart in any
embedding witness (the K_6-on-2x6-ladder construction spans the ladder), so
demand-optimal separation scales with the embedded layout's geometry, up to
the diameter. The light cone then says precisely what cadence costs: a
cadence X caps the reachable radius at ~X, so it excludes every embedding
whose split-pairs need distance > X. Cadence partitions the two dividends:

    degree dividend (+2 edges):       survives any cadence >= ~4 layers
    embedding dividend (positioning): degrades with the radius cap ~X

## 4. Measured: prism operates in the embedding regime

`separation_profile.py`, prism depth-objective, n in {8,16}, grid (full/near
occupancy) + heavy-hex (d=3: 19 vertices for 16 rails; d=5: 57 for 32,
sparse). dMax/dMean over delocalized qubit-layers; p>=3 = fraction of
delocalized qubit-layers at separation >= 3; cone = max over interior
windows of (d_max-1)/W (1.0 = light-cone-saturating excursion); degCo/degSep
= realized quotient degree co-located vs separated; multi = multi-edge share.

```
circuit            n topo       layers  diam  dMax  dMean  p>=3  cone  degCo  degSep  multi       topWin(W,dmax)
qft                8 grid           37     6     6   3.14  0.67  1.00   3.85    4.59   0.14  (6,6),(24,6),(32,4)
qaoa               8 grid           26     6     4   2.18  0.16  1.00   3.21    3.92   0.19   (10,4),(3,2),(7,2)
modular_adder      8 grid           35     6     6   3.46  0.69  0.33   4.34    4.17   0.18 (35,6),(35,5),(35,4)
vqe_two_local      8 grid          102     6     5   2.67  0.43  1.00   3.28    4.31   0.17 (18,5),(44,5),(21,5)
vqe_su2            8 grid           34     6     1   1.00  0.00  0.00   2.75    0.00   0.31
qft                8 heavyhex3      45     8     7   3.55  0.64  1.00   2.24    3.01   0.15 (28,7),(43,7),(14,6)
qaoa               8 heavyhex3      41     8     6   2.42  0.23  1.00   1.73    2.64   0.16  (18,6),(23,4),(4,3)
modular_adder      8 heavyhex3      46     8     8   5.35  0.83  1.00   2.82    3.02   0.06 (46,8),(46,7),(46,7)
vqe_two_local      8 heavyhex3     128     8     7   3.32  0.71  1.00   1.76    3.39   0.10 (55,7),(18,6),(23,6)
vqe_su2            8 heavyhex3      41     8     1   1.00  0.00  0.00   2.00    0.00   0.00
qft               16 grid          104    10     9   4.57  0.87  1.00   5.20    5.65   0.07 (70,9),(77,8),(98,7)
qaoa              16 grid           81    10     7   2.79  0.42  1.00   3.75    4.97   0.14 (40,7),(52,6),(31,6)
modular_adder     16 grid          293    10     5   2.41  0.33  1.00   3.81    4.37   0.17 (26,5),(71,4),(142,4)
vqe_two_local     16 grid          297    10     8   3.68  0.72  1.00   4.23    5.44   0.10 (63,8),(34,7),(117,7)
vqe_su2           16 grid           65    10     1   1.00  0.00  0.00   3.75    0.00   0.12
qft               16 heavyhex5     128    16    13   6.36  0.92  1.00   2.72    3.61   0.08 (120,13),(107,10),(95,10)
qaoa              16 heavyhex5      82    16     9   3.92  0.78  1.00   2.17    3.72   0.07 (35,9),(34,8),(32,8)
modular_adder     16 heavyhex5     320    16     7   2.91  0.54  1.00   2.17    3.22   0.09 (133,7),(186,7),(30,7)
vqe_two_local     16 heavyhex5     302    16    11   4.79  0.82  1.00   2.32    3.86   0.07 (99,11),(79,11),(71,11)
vqe_su2           16 heavyhex5      69    16     5   3.12  0.45  1.00   2.01    2.85   0.02  (31,5),(13,3),(6,3)
```

Readings:

1. SEPARATION SCALES WITH THE CHIP. qft dMax goes 6 -> 9 -> 13 as the
   diameter goes 6 -> 10 -> 16 (0.6-0.9x diameter across the freedom
   circuits). This is the embedding regime, not the d~3 degree regime: the
   answer to "how far do they travel" is "a constant fraction of the
   diameter, growing with n".
2. EXCURSIONS SATURATE THE LIGHT CONE. cone = 1.00 nearly everywhere there
   are interior windows: prism contains maximal-velocity excursions
   (separation W+1 inside a length-W window). The depth objective produces
   sprint-out/sprint-back trajectories, not lingering at small radius.
3. THE DEGREE DIVIDEND IS SMALL AND CONFIRMED SMALL. degSep - degCo is
   ~+0.7..+2.6 (theory caps the interior-grid gain at +2; boundary, sparse
   occupancy, and partition collisions account for the spread, and
   modular_adder n=8 grid even inverts it). The measured wins cannot be
   degree-driven; they are positioning-driven. Consistent with the 94% swap
   pick-share = online greedy embedding reading.
4. MOST DELOCALIZED TIME IS BEYOND SATURATION. p>=3 = 0.64-0.92 on the
   freedom circuits at n=16: rails spend most separated time past the point
   where connectivity stops improving, again implying the position itself
   (being near demand partners) is the payoff.
5. OCCUPANCY MATTERS. The vqe_su2 control never delocalizes on full-occupancy
   grids but reaches d=5 with 31-layer windows on the sparse heavy-hex-5
   (32 rails on 57 vertices): given room, the router separates even
   rx-dense circuits. Sparse fabrics shift every circuit toward the
   embedding regime.
6. CADENCE CONSEQUENCE, quantitative: under cadence X the radius cap ~X
   would forbid the current solutions for X < dMax: at n=16 that means
   X >= ~7-13 layers minimum to keep prism's routing at all, and the
   windows actually used are far longer (70-186 layers). Tight cadence does
   not nibble at these solutions; it removes them. (Matches the bimodality
   in `delocalization_intervals_results.md`.)

## 5. Literature hooks

- Movement model and 1-step-per-layer: token-swapping / routing-via-matchings
  (Childs, Schoute, Unsal, `childs_circuit_2019`, already in refs.bib); the
  light cone is the trivial direction of their lower bounds.
- SWAP networks (Kivlichan et al., PRL 120, 110501, 2018): the extreme
  embedding regime (all-to-all on a line in linear depth, rails permanently
  in motion); prism's saturated cones are a budgeted version of the same
  phenomenon. VERIFY exact cite at bib time.
- Split thickness (Eppstein et al., arXiv:1512.04839): the embedding class;
  `quotient_embedding.md` for our forward direction.
- Morphing between embeddings = token swapping: `fragment_and_cover.md` (the
  only-search-is-the-morph framing).

## 6. What is paperable (S6.1 upgrade + one S3.3 remark)

- S6.1 (cadence, extensions): the light-cone proposition (two sentences +
  the swap floor), the saturation-at-3 remark, the two-dividend partition,
  and the measured table's headline (separation scales with diameter, cones
  saturated, degree gain ~constant): cadence is not a knob ON these
  solutions; it selects a different solution class. End-of-line stays free.
- S3.3 (quotient geometry): one remark after the degree-expansion equation:
  the maximal logical degree is reached at separation 3 and the gain over
  co-location is exactly the internal edge (+2 on triangle-free interiors);
  the value of larger separations is positional, which is the embedding
  story (forward ref to compiler/eval).
- Honest caveats to carry: layers proxy time (SWS durations rescale), the
  bound ignores congestion (only tightens), heavy-hex occupancy is a
  confound (noted, even useful: item 5), replay exchanges labels at logical
  SWAPs (pair sets exact).

## 7. Follow-ups (none blocking)

- objective="gates" leash comparison: does reclaiming the 15% swap premium
  shorten excursions (shallower cones), i.e., is the Pareto knob also a
  radius knob? Two runs, cheap.
- n=24 scaling point for the dMax-vs-diameter line (background bash).
- E-G insertion pass can now PRICE bounded staleness without running: each
  forced rejoin at separation d costs >= 2(d-1) rail-involving swaps, and
  the measured d distributions give the price table per circuit.
