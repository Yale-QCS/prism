// PRISM extension types, scoring helpers, and newtype wrappers around
// upstream `FrontLayer`/`ExtendedSet`. The wrappers (`RealizationFrontLayer`,
// `RealizationExtendedSet`) fold multi-realization state into the upstream
// types via `Deref`/`DerefMut`-based composition, so `layer.rs` carries no
// edits. Also hosts a second `#[pymethods] impl PyRoutingTarget` block that
// exposes `RoutingTarget.from_coupling_list` to Python.

use std::ops::{Deref, DerefMut};

use hashbrown::HashSet;
use indexmap::IndexMap;
use ndarray::prelude::*;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rustworkx_core::petgraph::prelude::*;

use qiskit_circuit::nlayout::NLayout;
use qiskit_circuit::{PhysicalQubit, VirtualQubit};
use qiskit_transpiler::neighbors::Neighbors;

use crate::sabre::dag::{InteractionKind, SabreDAG, SabreNode};
use crate::sabre::layer::{ExtendedSet, FrontLayer};
use crate::sabre::route::{PyRoutingTarget, RoutingTarget};

/// Multi-realization 2Q candidates in virtual-qubit coordinates.
/// Outer list: per realization. Inner list: 2Q sub-gates of that realization.
pub type VirtRealizations = Box<[Box<[[VirtualQubit; 2]]>]>;

/// Materialized realizations in physical-qubit coordinates
/// (`apply_swap` permutes these in place).
pub type Realizations = Box<[Box<[[PhysicalQubit; 2]]>]>;

/// One sub-gate fire inside a sub-routed `MultiTwoQ` commit.
pub struct SubGate {
    pub sub_idx: u32,
    pub swaps_before: Box<[[PhysicalQubit; 2]]>,
}

// ----- scoring helpers -----

/// `min_r sum_p dist[p]`: the multi-realization per-op cost is the closest
/// realization by summed pair distance. THE single change vs stock SABRE: a
/// `min` over candidate realizations folded into the front-layer score.
pub fn op_cost_min(realizations: &[Box<[[PhysicalQubit; 2]]>], dist: &ArrayView2<f64>) -> f64 {
    realizations
        .iter()
        .map(|real| {
            real.iter()
                .map(|p| dist[[p[0].index(), p[1].index()]])
                .sum::<f64>()
        })
        .fold(f64::INFINITY, f64::min)
}

/// `op_cost_min` evaluated under a virtual `swap` application (no mutation):
/// the swap permutes the distance lookup for the two swapped qubits.
pub fn op_cost_min_post_swap(
    realizations: &[Box<[[PhysicalQubit; 2]]>],
    swap: [PhysicalQubit; 2],
    dist: &ArrayView2<f64>,
) -> f64 {
    let [a, b] = swap;
    let permute = |p: PhysicalQubit| {
        if p == a {
            b
        } else if p == b {
            a
        } else {
            p
        }
    };
    realizations
        .iter()
        .map(|real| {
            real.iter()
                .map(|p| dist[[permute(p[0]).index(), permute(p[1]).index()]])
                .sum::<f64>()
        })
        .fold(f64::INFINITY, f64::min)
}

/// Sum-of-pair-distances for one selected realization.
pub fn realization_cost(realization: &[[PhysicalQubit; 2]], dist: &ArrayView2<f64>) -> f64 {
    realization
        .iter()
        .map(|p| dist[[p[0].index(), p[1].index()]])
        .sum()
}

/// `realization_cost` under a virtual SWAP application.
pub fn realization_cost_post_swap(
    realization: &[[PhysicalQubit; 2]],
    swap: [PhysicalQubit; 2],
    dist: &ArrayView2<f64>,
) -> f64 {
    let [a, b] = swap;
    let permute = |p: PhysicalQubit| {
        if p == a {
            b
        } else if p == b {
            a
        } else {
            p
        }
    };
    realization
        .iter()
        .map(|p| dist[[permute(p[0]).index(), permute(p[1]).index()]])
        .sum()
}

/// Closest realization, breaking equal-cost ties toward `preferred` and then
/// the lowest candidate index.
pub fn closest_realization(
    realizations: &[Box<[[PhysicalQubit; 2]]>],
    dist: &ArrayView2<f64>,
    preferred: usize,
) -> usize {
    assert!(!realizations.is_empty());
    let preferred = preferred.min(realizations.len() - 1);
    let mut best = preferred;
    let mut best_cost = realization_cost(&realizations[preferred], dist);
    for (index, realization) in realizations.iter().enumerate() {
        let cost = realization_cost(realization, dist);
        if cost < best_cost || (cost == best_cost && best != preferred && index < best) {
            best = index;
            best_cost = cost;
        }
    }
    best
}

/// Neutral executable choice: the default realization when all its pairs are
/// adjacent, otherwise the lowest-index realization with all pairs adjacent.
/// `None` if none are adjacent. No load term; the stable-index preference
/// makes the controlled live arms independent of routing-history state.
pub fn executable_choice_default(
    realizations: &[Box<[[PhysicalQubit; 2]]>],
    dist: &ArrayView2<f64>,
    default_idx: usize,
) -> Option<usize> {
    let adjacent = |real: &Box<[[PhysicalQubit; 2]]>| {
        real.iter()
            .all(|p| dist[[p[0].index(), p[1].index()]] == 1.0)
    };
    if realizations.get(default_idx).is_some_and(&adjacent) {
        return Some(default_idx);
    }
    realizations.iter().position(adjacent)
}

/// Realization with all pairs adjacent and lowest summed `phys_load`,
/// breaking load ties toward `default_idx`. `None` if none are adjacent.
pub fn executable_choice_balanced(
    realizations: &[Box<[[PhysicalQubit; 2]]>],
    dist: &ArrayView2<f64>,
    phys_load: &[f64],
    default_idx: usize,
) -> Option<usize> {
    let mut best: Option<(usize, f64)> = None;
    for (r_idx, real) in realizations.iter().enumerate() {
        let adjacent = real
            .iter()
            .all(|p| dist[[p[0].index(), p[1].index()]] == 1.0);
        if !adjacent {
            continue;
        }
        let load: f64 = real
            .iter()
            .flat_map(|p| [p[0].index(), p[1].index()])
            .map(|i| phys_load[i])
            .sum();
        let take = match best {
            None => true,
            Some((_, b_cost)) => load < b_cost || (load == b_cost && r_idx == default_idx),
        };
        if take {
            best = Some((r_idx, load));
        }
    }
    best.map(|(idx, _)| idx)
}

/// Materialize virtual realizations into physical-qubit coordinates.
pub fn materialize_phys_reals(realizations: &VirtRealizations, layout: &NLayout) -> Realizations {
    realizations
        .iter()
        .map(|real| {
            real.iter()
                .map(|p| [p[0].to_phys(layout), p[1].to_phys(layout)])
                .collect::<Box<[_]>>()
        })
        .collect::<Box<[_]>>()
}

/// If a multi-rep realization is strictly closer (by sum-of-pair-distances)
/// than the closest stock single-pair node, return `(node, real_idx)` so
/// the caller sub-routes it. Otherwise `None`, and the caller falls through
/// to upstream's stock `force_enable_closest_node`.
pub fn pick_multi_force_target(
    front: &RealizationFrontLayer,
    dist: &ArrayView2<f64>,
) -> Option<(NodeIndex, usize)> {
    let stock_best = front
        .iter()
        .map(|(_, p)| dist[[p[0].index(), p[1].index()]])
        .fold(f64::INFINITY, f64::min);
    let mut multi_best: Option<(NodeIndex, usize, f64)> = None;
    for (&node, reals) in front.multi_iter() {
        let candidates: Box<dyn Iterator<Item = (usize, &Box<[[PhysicalQubit; 2]]>)> + '_> =
            match front.multi_witness(&node) {
                Some(witness) => Box::new(std::iter::once((witness, &reals[witness]))),
                None => Box::new(reals.iter().enumerate()),
            };
        for (r_idx, real) in candidates {
            let d: f64 = real
                .iter()
                .map(|p| dist[[p[0].index(), p[1].index()]])
                .sum();
            if multi_best.as_ref().is_none_or(|(_, _, b)| d < *b) {
                multi_best = Some((node, r_idx, d));
            }
        }
    }
    multi_best.and_then(|(n, ri, d)| (d < stock_best).then_some((n, ri)))
}

/// Build a mini `SabreDAG` from a multi-rep realization's virtual-qubit
/// sub-gates. Sub-gates become `InteractionKind::TwoQ` nodes chained in
/// order; `SabreNode.indices[0]` puns on the sub-gate index.
pub fn build_mini_sabredag(virt_real: &[[VirtualQubit; 2]]) -> SabreDAG {
    let n = virt_real.len();
    let mut dag: DiGraph<SabreNode, ()> = DiGraph::with_capacity(n, n);
    let nodes: Vec<NodeIndex> = (0..n)
        .map(|i| {
            dag.add_node(SabreNode {
                indices: vec![NodeIndex::new(i)],
                kind: InteractionKind::TwoQ(virt_real[i]),
            })
        })
        .collect();
    for i in 0..n.saturating_sub(1) {
        dag.add_edge(nodes[i], nodes[i + 1], ());
    }
    let first_layer = if n > 0 { vec![nodes[0]] } else { Vec::new() };
    SabreDAG {
        initial: Vec::new(),
        dag,
        first_layer,
    }
}

// ----- impl PyRoutingTarget (prism-only API) -----

#[pymethods]
impl PyRoutingTarget {
    /// Build a target from an undirected edge list. PRISM uses this
    /// because upstream's ``from_target`` requires a wrapped ``BaseTarget``
    /// that ``Target.from_configuration(...)`` doesn't satisfy from Python.
    #[staticmethod]
    pub fn from_coupling_list(edges: Vec<[u32; 2]>, num_qubits: u32) -> PyResult<Self> {
        let n = num_qubits as usize;
        let mut adj: Vec<Vec<PhysicalQubit>> = vec![Vec::new(); n];
        for [a, b] in edges {
            if (a as usize) >= n || (b as usize) >= n {
                return Err(PyValueError::new_err(format!(
                    "edge ({a}, {b}) out of range for num_qubits={num_qubits}"
                )));
            }
            adj[a as usize].push(PhysicalQubit::new(b));
            adj[b as usize].push(PhysicalQubit::new(a));
        }
        let mut neighbors: Vec<PhysicalQubit> = Vec::new();
        let mut partition: Vec<usize> = Vec::with_capacity(n + 1);
        partition.push(0);
        for mut local in adj {
            local.sort();
            local.dedup();
            neighbors.extend(local);
            partition.push(neighbors.len());
        }
        let neighbors = Neighbors::from_parts(neighbors, partition)
            .map_err(|e| PyValueError::new_err(e.to_string()))?;
        Ok(Self(Some(RoutingTarget::from_neighbors(neighbors))))
    }
}

// ----- RealizationFrontLayer: prism wrapper around `FrontLayer` -----
//
// Implements `Deref`/`DerefMut` to `FrontLayer` so all stock methods
// (`qubits()`, `iter()`, `insert()`, ...) auto-delegate. We override only
// the methods whose semantics change with multi state (`len`, `is_empty`,
// `is_active`, `score`, `total_score`, `apply_swap`, `remove`, `iter_nodes`,
// `iter_active`).

pub struct RealizationFrontLayer {
    inner: FrontLayer,
    multi: IndexMap<NodeIndex, Realizations, ::ahash::RandomState>,
    multi_witness: IndexMap<NodeIndex, usize, ::ahash::RandomState>,
    phys_to_nodes: Vec<HashSet<NodeIndex>>,
    sticky_witness: bool,
    /// Per-physical-qubit cumulative load accumulator for the MultiTwoQ
    /// adjacent-realization tiebreak.
    phys_load: Vec<f64>,
}

impl Deref for RealizationFrontLayer {
    type Target = FrontLayer;
    fn deref(&self) -> &FrontLayer {
        &self.inner
    }
}
impl DerefMut for RealizationFrontLayer {
    fn deref_mut(&mut self) -> &mut FrontLayer {
        &mut self.inner
    }
}

impl RealizationFrontLayer {
    pub fn new(num_qubits: u32, sticky_witness: bool) -> Self {
        Self {
            inner: FrontLayer::new(num_qubits),
            multi: IndexMap::with_hasher(::ahash::RandomState::default()),
            multi_witness: IndexMap::with_hasher(::ahash::RandomState::default()),
            phys_to_nodes: (0..num_qubits as usize).map(|_| HashSet::new()).collect(),
            sticky_witness,
            phys_load: vec![0.0; num_qubits as usize],
        }
    }

    /// Try to commit a `MultiTwoQ` node atomically (return realization index)
    /// or defer it into the front layer (return `None`). `tie_break_load`
    /// selects the load-balanced choice (`true`) or the neutral
    /// default-then-index choice (`false`); `phys_load` is accumulated on the
    /// committed realization's pairs in both modes (consulted only in the
    /// load mode).
    pub fn commit_or_defer_multi(
        &mut self,
        node_id: NodeIndex,
        realizations: &VirtRealizations,
        default_realization: u32,
        layout: &NLayout,
        dist: &ArrayView2<f64>,
        tie_break_load: bool,
    ) -> Option<u32> {
        let phys_reals = materialize_phys_reals(realizations, layout);
        let choice = if tie_break_load {
            executable_choice_balanced(
                &phys_reals,
                dist,
                &self.phys_load,
                default_realization as usize,
            )
        } else {
            executable_choice_default(&phys_reals, dist, default_realization as usize)
        };
        match choice {
            Some(r_idx) => {
                for pair in &phys_reals[r_idx][..] {
                    self.phys_load[pair[0].index()] += 1.0;
                    self.phys_load[pair[1].index()] += 1.0;
                }
                Some(r_idx as u32)
            }
            None => {
                self.insert_multi(node_id, phys_reals, default_realization as usize, dist);
                None
            }
        }
    }

    /// Bump `phys_load` by 1 on each endpoint of a sub-gate fire.
    pub fn bump_pair_load(&mut self, a: PhysicalQubit, b: PhysicalQubit) {
        self.phys_load[a.index()] += 1.0;
        self.phys_load[b.index()] += 1.0;
    }

    /// Decay `phys_load` by a multiplicative factor.
    pub fn decay_phys_load(&mut self, rate: f64) {
        self.phys_load.iter_mut().for_each(|x| *x *= rate);
    }

    // --- overrides that fold multi state into stock semantics ---

    pub fn len(&self) -> usize {
        self.inner.len() + self.multi.len()
    }

    pub fn is_empty(&self) -> bool {
        self.inner.is_empty() && self.multi.is_empty()
    }

    pub fn is_active(&self, qubit: PhysicalQubit) -> bool {
        self.inner.is_active(qubit) || !self.phys_to_nodes[qubit.index()].is_empty()
    }

    pub fn score(&self, swap: [PhysicalQubit; 2], dist: &ArrayView2<f64>) -> f64 {
        let mut total = self.inner.score(swap, dist);
        for (node, reals) in self.multi.iter() {
            if self.sticky_witness {
                let witness = self.multi_witness[node];
                total += realization_cost_post_swap(&reals[witness], swap, dist)
                    - realization_cost(&reals[witness], dist);
            } else {
                total += op_cost_min_post_swap(reals, swap, dist) - op_cost_min(reals, dist);
            }
        }
        total
    }

    pub fn total_score(&self, dist: &ArrayView2<f64>) -> f64 {
        self.inner.total_score(dist)
            + self
                .multi
                .iter()
                .map(|(node, reals)| {
                    if self.sticky_witness {
                        realization_cost(&reals[self.multi_witness[node]], dist)
                    } else {
                        op_cost_min(reals, dist)
                    }
                })
                .sum::<f64>()
    }

    pub fn apply_swap(&mut self, swap: [PhysicalQubit; 2]) {
        self.inner.apply_swap(swap);
        let [a, b] = swap;
        for realizations in self.multi.values_mut() {
            for real in realizations.iter_mut() {
                for pair in real.iter_mut() {
                    if pair[0] == a {
                        pair[0] = b;
                    } else if pair[0] == b {
                        pair[0] = a;
                    }
                    if pair[1] == a {
                        pair[1] = b;
                    } else if pair[1] == b {
                        pair[1] = a;
                    }
                }
            }
        }
        self.phys_to_nodes.swap(a.index(), b.index());
    }

    pub fn remove(&mut self, index: &NodeIndex) {
        if let Some(reals) = self.multi.swap_remove(index) {
            self.multi_witness.swap_remove(index);
            for real in reals.iter() {
                for p in real.iter() {
                    self.phys_to_nodes[p[0].index()].remove(index);
                    self.phys_to_nodes[p[1].index()].remove(index);
                }
            }
        } else {
            self.inner.remove(index);
        }
    }

    pub fn iter_nodes(&self) -> impl Iterator<Item = &NodeIndex> {
        self.inner.iter_nodes().chain(self.multi.keys())
    }

    pub fn iter_active(&self) -> impl Iterator<Item = PhysicalQubit> + '_ {
        self.inner
            .iter_active()
            .copied()
            .chain((0..self.phys_to_nodes.len()).filter_map(|i| {
                (!self.phys_to_nodes[i].is_empty()).then_some(PhysicalQubit::new(i as u32))
            }))
    }

    // --- multi-only API ---

    /// Add a multi-realization node (physical-qubit coords).
    pub fn insert_multi(
        &mut self,
        index: NodeIndex,
        realizations: Realizations,
        default_realization: usize,
        dist: &ArrayView2<f64>,
    ) {
        for real in realizations.iter() {
            for p in real.iter() {
                self.phys_to_nodes[p[0].index()].insert(index);
                self.phys_to_nodes[p[1].index()].insert(index);
            }
        }
        let witness = closest_realization(&realizations, dist, default_realization);
        self.multi.insert(index, realizations);
        self.multi_witness.insert(index, witness);
    }

    /// Multi-realization entries (node index, &realizations).
    pub fn multi_iter(&self) -> impl Iterator<Item = (&NodeIndex, &Realizations)> {
        self.multi.iter()
    }

    /// Borrow the realizations for a multi-realization node.
    pub fn multi_get(&self, node: &NodeIndex) -> Option<&Realizations> {
        self.multi.get(node)
    }

    /// Sticky realization witness for `node`, when witness scoring is active.
    pub fn multi_witness(&self, node: &NodeIndex) -> Option<usize> {
        self.sticky_witness
            .then(|| self.multi_witness.get(node).copied())
            .flatten()
    }

    /// Multi nodes with any pair touching `qubit`.
    pub fn multi_nodes_on(&self, qubit: PhysicalQubit) -> &HashSet<NodeIndex> {
        &self.phys_to_nodes[qubit.index()]
    }
}

// ----- RealizationExtendedSet: prism wrapper around `ExtendedSet` -----

pub struct RealizationExtendedSet {
    inner: ExtendedSet,
    multi: Vec<Realizations>,
    multi_witness: Vec<usize>,
    sticky_witness: bool,
}

impl Deref for RealizationExtendedSet {
    type Target = ExtendedSet;
    fn deref(&self) -> &ExtendedSet {
        &self.inner
    }
}
impl DerefMut for RealizationExtendedSet {
    fn deref_mut(&mut self) -> &mut ExtendedSet {
        &mut self.inner
    }
}

impl RealizationExtendedSet {
    pub fn new(num_qubits: u32, sticky_witness: bool) -> Self {
        Self {
            inner: ExtendedSet::new(num_qubits),
            multi: Vec::new(),
            multi_witness: Vec::new(),
            sticky_witness,
        }
    }

    pub fn len(&self) -> usize {
        self.inner.len() + self.multi.len()
    }

    pub fn is_empty(&self) -> bool {
        self.inner.is_empty() && self.multi.is_empty()
    }

    pub fn score(&self, swap: [PhysicalQubit; 2], dist: &ArrayView2<f64>) -> f64 {
        let mut total = self.inner.score(swap, dist);
        for (index, reals) in self.multi.iter().enumerate() {
            if self.sticky_witness {
                let witness = self.multi_witness[index];
                total += realization_cost_post_swap(&reals[witness], swap, dist)
                    - realization_cost(&reals[witness], dist);
            } else {
                total += op_cost_min_post_swap(reals, swap, dist) - op_cost_min(reals, dist);
            }
        }
        total
    }

    pub fn total_score(&self, dist: &ArrayView2<f64>) -> f64 {
        self.inner.total_score(dist)
            + self
                .multi
                .iter()
                .enumerate()
                .map(|(index, reals)| {
                    if self.sticky_witness {
                        realization_cost(&reals[self.multi_witness[index]], dist)
                    } else {
                        op_cost_min(reals, dist)
                    }
                })
                .sum::<f64>()
    }

    pub fn clear(&mut self) {
        self.inner.clear();
        self.multi.clear();
        self.multi_witness.clear();
    }

    pub fn apply_swap(&mut self, swap: [PhysicalQubit; 2]) {
        self.inner.apply_swap(swap);
        let [a, b] = swap;
        for reals in self.multi.iter_mut() {
            for real in reals.iter_mut() {
                for pair in real.iter_mut() {
                    if pair[0] == a {
                        pair[0] = b;
                    } else if pair[0] == b {
                        pair[0] = a;
                    }
                    if pair[1] == a {
                        pair[1] = b;
                    } else if pair[1] == b {
                        pair[1] = a;
                    }
                }
            }
        }
    }

    /// Add a multi-realization entry (already in physical-qubit coords).
    pub fn push_multi(
        &mut self,
        realizations: Realizations,
        default_realization: usize,
        dist: &ArrayView2<f64>,
    ) {
        self.multi_witness.push(closest_realization(
            &realizations,
            dist,
            default_realization,
        ));
        self.multi.push(realizations);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ndarray::array;

    fn pq(i: u32) -> PhysicalQubit {
        PhysicalQubit::new(i)
    }

    #[test]
    fn op_cost_min_is_min_of_sums_not_sum_of_per_edge_minima() {
        let dist = array![[0.0, 1.0, 5.0], [1.0, 0.0, 1.0], [5.0, 1.0, 0.0]];
        let reals: Vec<Box<[[PhysicalQubit; 2]]>> = vec![
            vec![[pq(0), pq(1)], [pq(0), pq(2)]].into_boxed_slice(), // 1 + 5 = 6
            vec![[pq(0), pq(2)], [pq(1), pq(2)]].into_boxed_slice(), // 5 + 1 = 6
        ];
        // sum of per-edge minima would give 1 + 1 = 2; min-of-sums gives 6.
        assert_eq!(op_cost_min(&reals, &dist.view()), 6.0);
    }

    #[test]
    fn op_cost_min_post_swap_permutes_without_mutation() {
        let dist = array![[0.0, 1.0, 2.0], [1.0, 0.0, 1.0], [2.0, 1.0, 0.0]];
        let reals: Vec<Box<[[PhysicalQubit; 2]]>> = vec![vec![[pq(0), pq(2)]].into_boxed_slice()];
        assert_eq!(op_cost_min(&reals, &dist.view()), 2.0);
        // swapping 1<->2 relabels the pair to (0,1), distance 1
        assert_eq!(
            op_cost_min_post_swap(&reals, [pq(1), pq(2)], &dist.view()),
            1.0
        );
        assert_eq!(op_cost_min(&reals, &dist.view()), 2.0);
    }

    #[test]
    fn sticky_witness_distinguishes_swaps_that_switch_realizations() {
        let dist = array![
            [0.0, 1.0, 2.0, 3.0],
            [1.0, 0.0, 1.0, 2.0],
            [2.0, 1.0, 0.0, 1.0],
            [3.0, 2.0, 1.0, 0.0],
        ];
        let reals: Vec<Box<[[PhysicalQubit; 2]]>> = vec![
            vec![[pq(0), pq(2)]].into_boxed_slice(),
            vec![[pq(1), pq(3)]].into_boxed_slice(),
        ];
        let witness = closest_realization(&reals, &dist.view(), 0);
        assert_eq!(witness, 0);

        // The lower-envelope score treats both swaps as an improvement by
        // changing which realization supplies the minimum.
        for swap in [[pq(0), pq(1)], [pq(2), pq(3)]] {
            assert_eq!(
                op_cost_min_post_swap(&reals, swap, &dist.view())
                    - op_cost_min(&reals, &dist.view()),
                -1.0,
            );
        }

        // A fixed witness instead distinguishes progress toward realization 0
        // from movement away from it.
        assert_eq!(
            realization_cost_post_swap(&reals[witness], [pq(0), pq(1)], &dist.view())
                - realization_cost(&reals[witness], &dist.view()),
            -1.0,
        );
        assert_eq!(
            realization_cost_post_swap(&reals[witness], [pq(2), pq(3)], &dist.view())
                - realization_cost(&reals[witness], &dist.view()),
            1.0,
        );
    }

    #[test]
    fn executable_choice_default_prefers_default_then_lowest_index() {
        let dist = array![[0.0, 1.0, 1.0], [1.0, 0.0, 2.0], [1.0, 2.0, 0.0]];
        let reals: Vec<Box<[[PhysicalQubit; 2]]>> = vec![
            vec![[pq(1), pq(2)]].into_boxed_slice(), // dist 2: not executable
            vec![[pq(0), pq(1)]].into_boxed_slice(), // executable
            vec![[pq(0), pq(2)]].into_boxed_slice(), // executable
        ];
        // default executable: default wins regardless of index position.
        assert_eq!(executable_choice_default(&reals, &dist.view(), 2), Some(2));
        // default not executable: lowest executable index wins.
        assert_eq!(executable_choice_default(&reals, &dist.view(), 0), Some(1));
        // nothing adjacent: None.
        let far = array![[0.0, 3.0, 3.0], [3.0, 0.0, 3.0], [3.0, 3.0, 0.0]];
        assert_eq!(executable_choice_default(&reals, &far.view(), 0), None);
    }

    #[test]
    fn executable_choice_default_ignores_load_state() {
        let dist = array![[0.0, 1.0, 1.0], [1.0, 0.0, 2.0], [1.0, 2.0, 0.0]];
        let reals: Vec<Box<[[PhysicalQubit; 2]]>> = vec![
            vec![[pq(0), pq(1)]].into_boxed_slice(),
            vec![[pq(0), pq(2)]].into_boxed_slice(),
        ];
        // Load-balanced choice moves off the default under load; the neutral
        // choice must not.
        let load = [0.0, 5.0, 0.0];
        assert_eq!(
            executable_choice_balanced(&reals, &dist.view(), &load, 0),
            Some(1)
        );
        assert_eq!(executable_choice_default(&reals, &dist.view(), 0), Some(0));
    }

    #[test]
    fn executable_choice_requires_all_pairs_adjacent_and_breaks_load_ties_to_default() {
        let dist = array![[0.0, 1.0, 1.0], [1.0, 0.0, 2.0], [1.0, 2.0, 0.0]];
        let reals: Vec<Box<[[PhysicalQubit; 2]]>> = vec![
            vec![[pq(1), pq(2)]].into_boxed_slice(), // dist 2: not executable
            vec![[pq(0), pq(1)]].into_boxed_slice(), // executable, load 0.7
            vec![[pq(0), pq(2)]].into_boxed_slice(), // executable, load 0.7
        ];
        let load = [0.5, 0.2, 0.2];
        // load tie: default wins when it is executable ...
        assert_eq!(
            executable_choice_balanced(&reals, &dist.view(), &load, 2),
            Some(2)
        );
        // ... and the first executable stands when the default is not.
        assert_eq!(
            executable_choice_balanced(&reals, &dist.view(), &load, 0),
            Some(1)
        );
        // lower load beats the default.
        let load = [0.5, 0.9, 0.0];
        assert_eq!(
            executable_choice_balanced(&reals, &dist.view(), &load, 1),
            Some(2)
        );
        // nothing adjacent: None.
        let far = array![[0.0, 3.0, 3.0], [3.0, 0.0, 3.0], [3.0, 3.0, 0.0]];
        assert_eq!(
            executable_choice_balanced(&reals, &far.view(), &load, 0),
            None
        );
    }
}
