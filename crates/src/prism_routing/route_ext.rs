//! prism's multi-realization routing on top of Qiskit's Sabre router.
//!
//! This file is compiled as a child module of the vendored `sabre::route` (declared there with
//! `#[path]`), so it can use the private `State`, `Order` and `RoutedItem` types without making
//! them public upstream.
//!
//! A `MultiTwoQ` node has several candidate realizations, each a list of two-qubit pairs.  Its
//! routing cost is the minimum over realizations of the summed pair distances.  The node commits
//! as soon as any realization has every pair adjacent; ties go to the realization with the lowest
//! decayed physical load, then to the default realization.
//!
//! With no `MultiTwoQ` nodes in the input, every hook here is a no-op and the router is stock
//! Qiskit Sabre.

// Restore the lints that `crate::sabre` allows for the vendored files (see `lib.rs`), at the
// levels set in `Cargo.toml`.
#![warn(
    dead_code,
    clippy::cast_possible_truncation,
    clippy::cast_precision_loss,
    clippy::doc_markdown,
    clippy::items_after_statements,
    clippy::too_many_lines
)]
#![deny(clippy::unwrap_used, clippy::wildcard_imports)]

use std::cmp::Ordering;

use ndarray::ArrayView2;
use rustworkx_core::petgraph::prelude::*;
use smallvec::SmallVec;

use qiskit_circuit::nlayout::NLayout;
use qiskit_circuit::{PhysicalQubit, VirtualQubit};

use super::super::dag::{InteractionKind, SabreDAG, SabreNode};
use super::super::vec_map::VecMap;
use super::{
    Order, RoutedItem, RoutedItemKind, RoutingProblem, RoutingResult, RoutingTarget, State,
    satisfy_successor_edges, swap_map_trial,
};
use crate::prism_routing::VirtRealizations;
use crate::prism_routing::input::{EVENT_KIND_COMMIT, EVENT_KIND_SUB_GATE, EVENT_KIND_SWAP, Event};

/// Per-routing-step decay of the physical-load tie-break.
const PHYS_LOAD_DECAY: f64 = 0.9;

/// One sub-gate fire inside a sub-routed `MultiTwoQ` commit.
pub(super) struct SubGate {
    /// Index of the pair within the chosen realization.
    sub_idx: u32,
    /// Swaps applied immediately before this sub-gate.
    swaps_before: Box<[[PhysicalQubit; 2]]>,
}

impl RoutedItem {
    /// Swaps inserted for this item, including those inside a sub-routed schedule.
    pub(super) fn swap_count(&self) -> usize {
        let inner = match &self.kind {
            RoutedItemKind::SubRoutedMultiTwoQ { schedule, .. } => {
                schedule.iter().map(|g| g.swaps_before.len()).sum()
            }
            _ => 0,
        };
        self.initial_swaps().len() + inner
    }
}

/// The realizations of a node known to be `MultiTwoQ`.
///
/// # Panics
///
/// If `node` is not a `MultiTwoQ` node.  Only `MultiTwoQ` nodes enter [`MultiLayers`], so this is an
/// internal invariant.
fn realizations(sabre: &SabreDAG, node: NodeIndex) -> &VirtRealizations {
    match &sabre.dag[node].kind {
        InteractionKind::MultiTwoQ { realizations, .. } => realizations,
        _ => unreachable!("only MultiTwoQ nodes are tracked by MultiLayers"),
    }
}

/// Map a physical qubit through `swap`, if one is given.
fn through(p: PhysicalQubit, swap: Option<[PhysicalQubit; 2]>) -> PhysicalQubit {
    match swap {
        Some([a, b]) if p == a => b,
        Some([a, b]) if p == b => a,
        _ => p,
    }
}

/// Summed pair distance of one realization, with `swap` optionally applied.
fn cost(
    real: &[[VirtualQubit; 2]],
    layout: &NLayout,
    swap: Option<[PhysicalQubit; 2]>,
    dist: &ArrayView2<f64>,
) -> f64 {
    real.iter()
        .map(|[a, b]| {
            dist[[
                through(layout[*a], swap).index(),
                through(layout[*b], swap).index(),
            ]]
        })
        .sum()
}

/// Minimum of [`cost`] over all realizations.
fn min_cost(
    reals: &VirtRealizations,
    layout: &NLayout,
    swap: Option<[PhysicalQubit; 2]>,
    dist: &ArrayView2<f64>,
) -> f64 {
    reals
        .iter()
        .map(|r| cost(r, layout, swap, dist))
        .fold(f64::INFINITY, f64::min)
}

/// Whether every pair of `real` is on a coupling edge under `layout`.
fn executable(real: &[[VirtualQubit; 2]], layout: &NLayout, target: &RoutingTarget) -> bool {
    real.iter()
        .all(|[a, b]| target.neighbors.contains_edge(layout[*a], layout[*b]))
}

/// Every virtual qubit named by any realization, with repeats.
fn qubits(reals: &VirtRealizations) -> impl Iterator<Item = VirtualQubit> + '_ {
    reals.iter().flat_map(|r| r.iter().flatten().copied())
}

/// Multi-realization nodes held in each Sabre layer, in parallel with the stock `Layers`.
///
/// `Layers` holds one gate per qubit per layer, which multi-realization nodes cannot satisfy, so
/// they are kept here instead.  Nodes are stored by index only: realizations are read from the
/// [`SabreDAG`] and mapped through the current layout when scored, so a swap needs no update here.
pub(super) struct MultiLayers {
    /// Nodes of each layer, in insertion order.
    layers: Box<[Vec<NodeIndex>]>,
    /// The layer holding each node, if any.
    location: VecMap<NodeIndex, Option<u16>>,
    /// Number of front-layer multi nodes touching each virtual qubit.
    front_active: VecMap<VirtualQubit, u32>,
    /// Decayed count of committed two-qubit gates on each physical qubit.
    phys_load: Vec<f64>,
}

impl MultiLayers {
    pub(super) fn new(num_layers: u16, num_qubits: u32, sabre: &SabreDAG) -> Self {
        Self {
            layers: vec![Vec::new(); num_layers.into()].into_boxed_slice(),
            location: vec![None; sabre.dag.node_count()].into(),
            front_active: vec![0; num_qubits as usize].into(),
            phys_load: vec![0.0; num_qubits as usize],
        }
    }

    /// Number of multi nodes in `layer`.
    pub(super) fn len(&self, layer: u16) -> usize {
        self.layers[usize::from(layer)].len()
    }

    /// Whether `layer` holds no multi nodes.
    pub(super) fn is_empty(&self, layer: u16) -> bool {
        self.layers[usize::from(layer)].is_empty()
    }

    /// The multi nodes in `layer`.
    pub(super) fn nodes(&self, layer: u16) -> impl Iterator<Item = NodeIndex> + '_ {
        self.layers[usize::from(layer)].iter().copied()
    }

    /// Put `node` in lookahead `layer`, moving it out of any deeper layer that holds it, as
    /// `Layers::insert` does.  Front-layer insertion goes through [`Self::defer`].
    pub(super) fn insert(&mut self, layer: u16, node: NodeIndex) {
        debug_assert!(layer > 0);
        self.unlink(node);
        self.layers[usize::from(layer)].push(node);
        self.location[node] = Some(layer);
    }

    /// Put `node` in the front layer.
    fn defer(&mut self, node: NodeIndex, reals: &VirtRealizations) {
        debug_assert!(self.location[node].is_none());
        for q in qubits(reals) {
            self.front_active[q] += 1;
        }
        self.layers[0].push(node);
        self.location[node] = Some(0);
    }

    /// Remove `node` from whichever layer holds it, and return that layer.
    pub(super) fn remove(&mut self, node: NodeIndex, sabre: &SabreDAG) -> Option<u16> {
        let layer = self.unlink(node)?;
        if layer == 0 {
            for q in qubits(realizations(sabre, node)) {
                self.front_active[q] -= 1;
            }
        }
        Some(layer)
    }

    /// Take `node` out of the layer holding it, if any, and return that layer.
    fn unlink(&mut self, node: NodeIndex) -> Option<u16> {
        let layer = self.location[node].take()?;
        let nodes = &mut self.layers[usize::from(layer)];
        let pos = nodes
            .iter()
            .position(|n| *n == node)
            .expect("`location` and `layers` agree");
        // Order-preserving: the scoring sum and the routable-node order follow insertion order.
        nodes.remove(pos);
        Some(layer)
    }

    /// Commit `node` now if a realization is executable and return its index; otherwise defer
    /// `node` into the front layer and return `None`.
    pub(super) fn try_commit(
        &mut self,
        node: NodeIndex,
        problem: RoutingProblem,
        layout: &NLayout,
    ) -> Option<u32> {
        let InteractionKind::MultiTwoQ {
            realizations: reals,
            default_realization,
        } = &problem.sabre.dag[node].kind
        else {
            unreachable!("`try_route` only commits MultiTwoQ nodes here");
        };
        let is_default = |r: usize| u32::try_from(r).is_ok_and(|r| r == *default_realization);
        let load = |real: &[[VirtualQubit; 2]]| -> f64 {
            real.iter()
                .flatten()
                .map(|v| self.phys_load[layout[*v].index()])
                .sum()
        };
        // Lowest load wins; among equal loads the default realization, then the lowest index.
        let best = reals
            .iter()
            .enumerate()
            .filter(|(_, real)| executable(real, layout, problem.target))
            .map(|(r, real)| (r, load(real)))
            .min_by(|(ra, la), (rb, lb)| {
                la.total_cmp(lb)
                    .then_with(|| match (is_default(*ra), is_default(*rb)) {
                        (true, false) => Ordering::Less,
                        (false, true) => Ordering::Greater,
                        _ => Ordering::Equal,
                    })
            });
        let Some((r, _)) = best else {
            self.defer(node, reals);
            return None;
        };
        for v in reals[r].iter().flatten() {
            self.phys_load[layout[*v].index()] += 1.0;
        }
        Some(u32::try_from(r).expect("realization count fits in u32"))
    }

    /// Decay the physical-load tie-break by one routing step.
    pub(super) fn decay_load(&mut self) {
        for load in &mut self.phys_load {
            *load *= PHYS_LOAD_DECAY;
        }
    }

    /// Add `weight` times the score change of every multi node in `layer` to each candidate swap,
    /// and return `weight` times their summed current score.
    pub(super) fn add_scores(
        &self,
        layer: u16,
        weight: f64,
        swap_scores: &mut [([PhysicalQubit; 2], f64)],
        problem: RoutingProblem,
        layout: &NLayout,
    ) -> f64 {
        let dist = problem.target.distance.view();
        let mut absolute = 0.0;
        for &node in &self.layers[usize::from(layer)] {
            let reals = realizations(problem.sabre, node);
            let base = min_cost(reals, layout, None, &dist);
            absolute += base;
            for (swap, score) in swap_scores.iter_mut() {
                *score += weight * (min_cost(reals, layout, Some(*swap), &dist) - base);
            }
        }
        weight * absolute
    }
}

impl State {
    /// Append the candidate swaps touching qubits of front-layer multi nodes, after the stock
    /// candidates and without duplicating them.  With no multi nodes the list is unchanged.
    pub(super) fn push_multi_candidates(&mut self, problem: RoutingProblem) {
        let front = self.layers.front();
        for &node in &self.multi.layers[0] {
            for v in qubits(realizations(problem.sabre, node)) {
                let phys = self.layout[v];
                for &neighbor in &problem.target.neighbors[phys] {
                    // Edges to stock-active qubits were pushed by the stock loop.
                    if front.is_active(neighbor) {
                        continue;
                    }
                    // Mirror the stock convention: edges between two active qubits are ordered.
                    let swap = if self.multi.front_active[self.layout[neighbor]] > 0 {
                        [phys.min(neighbor), phys.max(neighbor)]
                    } else {
                        [phys, neighbor]
                    };
                    if !self.swap_scores.iter().any(|(s, _)| *s == swap) {
                        self.swap_scores.push((swap, 0.0));
                    }
                }
            }
        }
    }

    /// Push the front-layer multi nodes on either qubit of `swap` that became executable.
    pub(super) fn push_multi_routable(
        &self,
        problem: RoutingProblem,
        swap: [PhysicalQubit; 2],
        out: &mut Vec<NodeIndex>,
    ) {
        for &node in &self.multi.layers[0] {
            let reals = realizations(problem.sabre, node);
            let touches = qubits(reals).any(|v| swap.contains(&self.layout[v]));
            if touches
                && reals
                    .iter()
                    .any(|r| executable(r, &self.layout, problem.target))
                && !out.contains(&node)
            {
                out.push(node);
            }
        }
    }

    /// Release valve.  If a multi node's closest realization is strictly closer than the closest
    /// stock gate, route that realization gate by gate and commit it; otherwise use the stock
    /// valve.  An empty return means the commit already happened.
    pub(super) fn force_enable_or_subroute<'a>(
        &mut self,
        problem: RoutingProblem<'a>,
        order: &mut Order<'a>,
        current_swaps: &mut Vec<[PhysicalQubit; 2]>,
    ) -> SmallVec<[NodeIndex; 2]> {
        let dist = problem.target.distance.view();
        let stock_best = self
            .layers
            .front()
            .iter_gates()
            .map(|(_, [a, b])| dist[[self.layout[a].index(), self.layout[b].index()]])
            .fold(f64::INFINITY, f64::min);
        let mut best: Option<(NodeIndex, usize, f64)> = None;
        for &node in &self.multi.layers[0] {
            for (r, real) in realizations(problem.sabre, node).iter().enumerate() {
                let d = cost(real, &self.layout, None, &dist);
                if best.is_none_or(|(_, _, b)| d < b) {
                    best = Some((node, r, d));
                }
            }
        }
        match best {
            Some((node, r, d)) if d < stock_best => {
                debug_assert!(current_swaps.is_empty());
                let schedule = self.sub_route(problem, node, r);
                self.commit_sub_routed(problem, order, node, r, schedule);
                SmallVec::new()
            }
            _ => self.force_enable_closest_node(problem, current_swaps),
        }
    }

    /// Route realization `r` of `node` as a chain of two-qubit gates with a nested Sabre trial,
    /// and apply its swaps to this state.
    fn sub_route(&mut self, problem: RoutingProblem, node: NodeIndex, r: usize) -> Box<[SubGate]> {
        let real = &realizations(problem.sabre, node)[r];
        let chain = chain_dag(real);
        let result = swap_map_trial(
            problem.with_sabre(&chain),
            &self.layout,
            self.seed.wrapping_add(1),
        );
        let mut schedule = Vec::with_capacity(result.order.order.len());
        for item in &result.order.order {
            for &swap in item.initial_swaps() {
                self.apply_swap(swap);
            }
            let sub_idx = chain.dag[item.node].indices[0].index();
            for v in real[sub_idx] {
                self.multi.phys_load[self.layout[v].index()] += 1.0;
            }
            schedule.push(SubGate {
                sub_idx: u32::try_from(sub_idx).expect("pair count fits in u32"),
                swaps_before: item.initial_swaps().into(),
            });
        }
        schedule.into_boxed_slice()
    }

    /// Record a sub-routed commit, then advance the layers as `update_route` does.
    fn commit_sub_routed<'a>(
        &mut self,
        problem: RoutingProblem<'a>,
        order: &mut Order<'a>,
        node: NodeIndex,
        r: usize,
        schedule: Box<[SubGate]>,
    ) {
        assert_eq!(self.multi.remove(node, problem.sabre), Some(0));
        order.order.push(RoutedItem {
            initial_swaps: None,
            node,
            kind: RoutedItemKind::SubRoutedMultiTwoQ {
                real_idx: u32::try_from(r).expect("realization count fits in u32"),
                schedule,
            },
        });
        let visit = &mut self.visit;
        satisfy_successor_edges(node, problem.sabre, &mut self.predecessors[0], |s| {
            visit.push_back(s);
        });
        self.update_route(problem, order, &[], None);
    }
}

/// A [`SabreDAG`] that is a chain of the pairs of one realization.  `indices[0]` of each node holds
/// the pair's index in `real`.
fn chain_dag(real: &[[VirtualQubit; 2]]) -> SabreDAG {
    let mut dag = DiGraph::with_capacity(real.len(), real.len().saturating_sub(1));
    let nodes: Vec<NodeIndex> = real
        .iter()
        .enumerate()
        .map(|(i, pair)| {
            dag.add_node(SabreNode {
                indices: vec![NodeIndex::new(i)],
                kind: InteractionKind::TwoQ(*pair),
            })
        })
        .collect();
    for w in nodes.windows(2) {
        dag.add_edge(w[0], w[1], ());
    }
    SabreDAG {
        initial: Vec::new(),
        dag,
        first_layer: nodes.first().copied().into_iter().collect(),
    }
}

/// Flatten a routing result into prism's `(kind, a, b)` event stream and its swap count.
///
/// See [`crate::prism_routing::input`] for the event encoding.
pub fn flatten_routing_result(result: &RoutingResult<'_>) -> (Vec<Event>, u32) {
    let mut events = Vec::with_capacity(result.order.order.len() * 2);
    let mut n_swaps: u32 = 0;
    let mut push_swaps = |events: &mut Vec<Event>, swaps: &[[PhysicalQubit; 2]]| {
        for [a, b] in swaps {
            events.push((EVENT_KIND_SWAP, a.0, b.0));
            n_swaps += 1;
        }
    };
    for item in &result.order.order {
        push_swaps(&mut events, item.initial_swaps());
        let op_idx = u32::try_from(result.problem.sabre.dag[item.node].indices[0].index())
            .expect("op count fits in u32");
        match &item.kind {
            RoutedItemKind::Simple => events.push((EVENT_KIND_COMMIT, op_idx, 0)),
            RoutedItemKind::MultiTwoQ(r) => events.push((EVENT_KIND_COMMIT, op_idx, *r)),
            RoutedItemKind::SubRoutedMultiTwoQ { real_idx, schedule } => {
                for g in schedule {
                    push_swaps(&mut events, &g.swaps_before);
                    let packed = (*real_idx << 16) | (g.sub_idx & 0xFFFF);
                    events.push((EVENT_KIND_SUB_GATE, op_idx, packed));
                }
            }
            RoutedItemKind::ControlFlow(_) => unreachable!("prism's input has no control flow"),
        }
    }
    push_swaps(&mut events, &result.order.final_swaps);
    (events, n_swaps)
}

#[cfg(test)]
mod tests {
    use ndarray::array;
    use qiskit_circuit::dag_circuit::DAGCircuit;

    use super::super::super::heuristic::{
        BasicHeuristic, Heuristic, LookaheadHeuristic, SetScaling,
    };
    use super::super::{PyRoutingTarget, State, satisfy_successor_edges, swap_map};
    use super::{
        DiGraph, InteractionKind, MultiLayers, NLayout, NodeIndex, PhysicalQubit, RoutingProblem,
        SabreDAG, SabreNode, VirtRealizations, VirtualQubit, chain_dag, min_cost,
    };

    fn v(i: u32) -> VirtualQubit {
        VirtualQubit::new(i)
    }

    fn reals(pairs: &[&[[u32; 2]]]) -> VirtRealizations {
        pairs
            .iter()
            .map(|real| real.iter().map(|&[a, b]| [v(a), v(b)]).collect())
            .collect()
    }

    fn line(n: u32) -> PyRoutingTarget {
        let edges = (1..n).map(|i| [i - 1, i]).collect();
        PyRoutingTarget::from_coupling_list(edges, n).expect("valid line")
    }

    fn heuristic() -> Heuristic {
        Heuristic::new(
            Some(BasicHeuristic::new(1.0, SetScaling::Constant)),
            None,
            None,
            Some(100),
            1e-10,
        )
    }

    fn single_node_dag(kind: InteractionKind) -> SabreDAG {
        let mut dag = DiGraph::new();
        let node = dag.add_node(SabreNode {
            indices: vec![NodeIndex::new(0)],
            kind,
        });
        SabreDAG {
            initial: Vec::new(),
            dag,
            first_layer: vec![node],
        }
    }

    fn route(sabre: &SabreDAG, target: &PyRoutingTarget) -> (usize, Vec<u32>) {
        let dag = DAGCircuit::new();
        let heuristic = heuristic();
        let problem = RoutingProblem {
            target: target.0.as_ref().expect("explicit target"),
            sabre,
            dag: &dag,
            heuristic: &heuristic,
        };
        let n = u32::try_from(target.0.as_ref().map_or(0, |t| t.neighbors.num_qubits()))
            .expect("small target");
        let result = swap_map(
            problem,
            &NLayout::generate_trivial_layout(n),
            Some(7),
            1,
            None,
        );
        let (events, n_swaps) = super::flatten_routing_result(&result);
        let commits = events.iter().filter(|e| e.0 != 1).map(|e| e.2).collect();
        assert_eq!(n_swaps as usize, result.swap_count());
        (result.swap_count(), commits)
    }

    #[test]
    fn min_cost_is_min_of_sums() {
        let dist = array![[0.0, 1.0, 5.0], [1.0, 0.0, 1.0], [5.0, 1.0, 0.0]];
        let layout = NLayout::generate_trivial_layout(3);
        // Each realization sums to 6; the sum of per-pair minima would be 2.
        let r = reals(&[&[[0, 1], [0, 2]], &[[0, 2], [1, 2]]]);
        assert!((min_cost(&r, &layout, None, &dist.view()) - 6.0).abs() < 1e-12);
    }

    #[test]
    fn min_cost_after_swap_leaves_layout_unchanged() {
        let dist = array![[0.0, 1.0, 2.0], [1.0, 0.0, 1.0], [2.0, 1.0, 0.0]];
        let layout = NLayout::generate_trivial_layout(3);
        let r = reals(&[&[[0, 2]]]);
        let swap = Some([PhysicalQubit::new(1), PhysicalQubit::new(2)]);
        assert!((min_cost(&r, &layout, swap, &dist.view()) - 1.0).abs() < 1e-12);
        assert!((min_cost(&r, &layout, None, &dist.view()) - 2.0).abs() < 1e-12);
    }

    #[test]
    fn commit_prefers_lowest_load_then_default_then_lowest_index() {
        let target = line(3);
        // Realizations 1 and 2 are executable on the line 0-1-2; realization 0 is not.
        let r = reals(&[&[[0, 2]], &[[0, 1]], &[[1, 2]]]);
        let commit = |default, load: [f64; 3]| {
            let sabre = single_node_dag(InteractionKind::MultiTwoQ {
                realizations: r.clone(),
                default_realization: default,
            });
            let dag = DAGCircuit::new();
            let heuristic = heuristic();
            let problem = RoutingProblem {
                target: target.0.as_ref().expect("explicit target"),
                sabre: &sabre,
                dag: &dag,
                heuristic: &heuristic,
            };
            let mut multi = MultiLayers::new(1, 3, &sabre);
            multi.phys_load = load.to_vec();
            let layout = NLayout::generate_trivial_layout(3);
            multi.try_commit(NodeIndex::new(0), problem, &layout)
        };
        assert_eq!(commit(0, [0.0; 3]), Some(1));
        assert_eq!(commit(2, [0.0; 3]), Some(2));
        assert_eq!(commit(1, [0.0, 0.0, 0.5]), Some(1));
        assert_eq!(commit(1, [1.0, 0.0, 0.0]), Some(2));
    }

    #[test]
    fn single_realization_routes_like_two_qubit_gate() {
        let target = line(5);
        let stock = single_node_dag(InteractionKind::TwoQ([v(0), v(4)]));
        let multi = single_node_dag(InteractionKind::MultiTwoQ {
            realizations: reals(&[&[[0, 4]]]),
            default_realization: 0,
        });
        let (stock_swaps, _) = route(&stock, &target);
        let (multi_swaps, commits) = route(&multi, &target);
        assert_eq!(stock_swaps, 3);
        assert_eq!(multi_swaps, stock_swaps);
        assert!(commits.iter().all(|&packed| packed >> 16 == 0));
    }

    #[test]
    fn executable_realization_commits_without_swaps() {
        let target = line(5);
        let sabre = single_node_dag(InteractionKind::MultiTwoQ {
            realizations: reals(&[&[[0, 4]], &[[2, 3], [3, 4]]]),
            default_realization: 0,
        });
        assert_eq!(route(&sabre, &target), (0, vec![1]));
    }

    fn lookahead(num_layers: usize) -> Heuristic {
        let weights = vec![0.1; num_layers];
        let lookahead = LookaheadHeuristic::new(weights, SetScaling::Constant);
        Heuristic::new(
            Some(BasicHeuristic::new(1.0, SetScaling::Constant)),
            Some(lookahead.expect("few layers")),
            None,
            Some(100),
            1e-10,
        )
    }

    /// A DAG of `ops`, each depending on the latest earlier op on each of its qubits.
    fn dag_of(ops: Vec<InteractionKind>) -> SabreDAG {
        let mut dag = DiGraph::new();
        let mut last = std::collections::HashMap::new();
        let mut first_layer = Vec::new();
        for (k, kind) in ops.into_iter().enumerate() {
            let wires: Vec<VirtualQubit> = match &kind {
                InteractionKind::TwoQ(pair) => pair.to_vec(),
                InteractionKind::MultiTwoQ { realizations, .. } => {
                    super::qubits(realizations).collect()
                }
                _ => unreachable!("tests build two-qubit nodes only"),
            };
            let node = dag.add_node(SabreNode {
                indices: vec![NodeIndex::new(k)],
                kind,
            });
            let mut preds: Vec<NodeIndex> =
                wires.iter().filter_map(|q| last.get(q)).copied().collect();
            preds.sort();
            preds.dedup();
            if preds.is_empty() {
                first_layer.push(node);
            }
            for pred in preds {
                dag.add_edge(pred, node, ());
            }
            for q in wires {
                last.insert(q, node);
            }
        }
        SabreDAG {
            initial: Vec::new(),
            dag,
            first_layer,
        }
    }

    /// Every lookahead layer's nodes (stock and multi), sorted.
    fn held_layers(state: &State) -> Vec<Vec<NodeIndex>> {
        (1..state.layers.num_layers().get())
            .map(|k| {
                let stock = state.layers.layers()[usize::from(k)].iter_gates();
                let mut nodes: Vec<_> = stock.map(|(n, _)| n).chain(state.multi.nodes(k)).collect();
                nodes.sort();
                nodes
            })
            .collect()
    }

    /// The lookahead layers rebuilt from the front layer, as `State::begin` builds them.
    fn rebuilt_layers(state: &State, sabre: &SabreDAG) -> Vec<Vec<NodeIndex>> {
        let mut predecessors = state.predecessors[0].clone();
        let front = state.layers.front().iter_gates().map(|(n, _)| n);
        let mut previous: Vec<NodeIndex> = front.chain(state.multi.nodes(0)).collect();
        let mut layers = Vec::new();
        for _ in 1..state.layers.num_layers().get() {
            let mut layer = Vec::new();
            for &node in &previous {
                satisfy_successor_edges(node, sabre, &mut predecessors, |s| layer.push(s));
            }
            layer.sort();
            previous = layer.clone();
            layers.push(layer);
        }
        layers
    }

    #[test]
    fn lookahead_keeps_successor_of_routed_gate() {
        // On the line 0-..-5: `u` and `f` wait in the front layer, `s` follows `f`, and `t`
        // follows both `s` and `u`.  Once `f` is routable, `s` routes at once, so `t` waits only
        // on `u` and belongs in the first lookahead layer.
        let pair = |a, b| InteractionKind::TwoQ([v(a), v(b)]);
        let sabre = dag_of(vec![pair(0, 5), pair(1, 3), pair(3, 4), pair(4, 5)]);
        let target = line(6);
        let dag = DAGCircuit::new();
        let heuristic = lookahead(1);
        let problem = RoutingProblem {
            target: target.0.as_ref().expect("explicit target"),
            sabre: &sabre,
            dag: &dag,
            heuristic: &heuristic,
        };
        let (mut state, mut order) = State::begin(problem, NLayout::generate_trivial_layout(6), 0);
        assert_eq!(held_layers(&state), vec![vec![NodeIndex::new(2)]]);
        state.apply_swap([PhysicalQubit::new(1), PhysicalQubit::new(2)]);
        state.update_route(problem, &mut order, &[NodeIndex::new(1)], None);
        assert_eq!(held_layers(&state), vec![vec![NodeIndex::new(3)]]);
    }

    #[test]
    fn lookahead_layers_match_rebuild_while_routing() {
        let n = 7;
        let ops = (0..60u32)
            .map(|k| {
                let a = (k * 3) % n;
                let b = (a + 1 + (k * 5) % (n - 1)) % n;
                let c = (b + 1 + k % (n - 2)) % n;
                if k % 3 == 0 && c != a {
                    InteractionKind::MultiTwoQ {
                        realizations: reals(&[&[[a, b]], &[[a, c], [c, b]]]),
                        default_realization: 0,
                    }
                } else {
                    InteractionKind::TwoQ([v(a), v(b)])
                }
            })
            .collect();
        let sabre = dag_of(ops);
        let target = line(n);
        let dag = DAGCircuit::new();
        for num_layers in [1, 2, 4] {
            let heuristic = lookahead(num_layers);
            let problem = RoutingProblem {
                target: target.0.as_ref().expect("explicit target"),
                sabre: &sabre,
                dag: &dag,
                heuristic: &heuristic,
            };
            let (mut state, mut order) =
                State::begin(problem, NLayout::generate_trivial_layout(n), 0);
            // Route with the release valve alone: deterministic, and every step routes a node.
            while !(state.layers.front().is_empty() && state.multi.is_empty(0)) {
                assert_eq!(held_layers(&state), rebuilt_layers(&state, &sabre));
                let mut swaps = Vec::new();
                let nodes = state.force_enable_or_subroute(problem, &mut order, &mut swaps);
                if !nodes.is_empty() {
                    state.update_route(problem, &mut order, &nodes, Some(swaps));
                }
            }
            assert_eq!(order.order.len(), sabre.dag.node_count());
        }
    }

    #[test]
    fn chain_dag_orders_pairs() {
        let chain = chain_dag(&[[v(0), v(1)], [v(1), v(2)], [v(2), v(3)]]);
        assert_eq!(chain.first_layer, vec![NodeIndex::new(0)]);
        assert_eq!(chain.dag.edge_count(), 2);
    }
}
