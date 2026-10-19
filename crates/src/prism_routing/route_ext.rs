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
//! When the router is stuck, the stock release valve also considers the realizations of the
//! front-layer multi nodes that sit on one qubit pair: it swaps the closest pair of all together
//! along a shortest path, and the node then commits as usual.  Swaps go between nodes, never inside
//! one.
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

use ndarray::ArrayView2;
use rustworkx_core::petgraph::prelude::*;

use qiskit_circuit::nlayout::NLayout;
use qiskit_circuit::{PhysicalQubit, VirtualQubit};

use super::super::dag::{InteractionKind, SabreDAG};
use super::super::vec_map::VecMap;
use super::{RoutedItemKind, RoutingProblem, RoutingResult, RoutingTarget, State};
use crate::prism_routing::input::RoutedOp;
use crate::prism_routing::{VirtRealizations, single_edge};

/// Per-routing-step decay of the physical-load tie-break.
const PHYS_LOAD_DECAY: f64 = 0.9;

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

    /// Whether `layer` holds no multi nodes.
    pub(super) fn is_empty(&self, layer: u16) -> bool {
        self.layers[usize::from(layer)].is_empty()
    }

    /// The multi nodes in `layer`.
    pub(super) fn nodes(&self, layer: u16) -> impl Iterator<Item = NodeIndex> + '_ {
        self.layers[usize::from(layer)].iter().copied()
    }

    /// The pair of each single-edge realization of each front-layer multi node, for the release
    /// valve.  Every front-layer multi node has one: `input` requires a realization with no pairs,
    /// which commits at once, or with every pair on one qubit pair.  A node whose pair is adjacent
    /// has already committed.
    pub(super) fn front_pairs<'s>(
        &'s self,
        sabre: &'s SabreDAG,
    ) -> impl Iterator<Item = (NodeIndex, [VirtualQubit; 2])> + 's {
        self.layers[0].iter().flat_map(move |&node| {
            realizations(sabre, node)
                .iter()
                .filter_map(|real| single_edge(real))
                .map(move |pair| (node, pair))
        })
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
        let default = *default_realization as usize;
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
                    .then((*ra != default).cmp(&(*rb != default)))
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

    /// The front-layer multi nodes on either qubit of `swap` that became executable.
    pub(super) fn multi_routable(
        &self,
        problem: RoutingProblem,
        swap: [PhysicalQubit; 2],
    ) -> impl Iterator<Item = NodeIndex> {
        self.multi.layers[0].iter().copied().filter(move |&node| {
            let reals = realizations(problem.sabre, node);
            qubits(reals).any(|v| swap.contains(&self.layout[v]))
                && reals
                    .iter()
                    .any(|r| executable(r, &self.layout, problem.target))
        })
    }
}

/// The routed order of `result`: per node, the swaps before it, its node index and its
/// realization.
///
/// prism's input has no control flow, so the order ends with no swaps (`Order::final_swaps`).
pub fn routed_ops(result: &RoutingResult<'_>) -> Vec<RoutedOp> {
    debug_assert!(result.order.final_swaps.is_empty());
    let realization = |kind: &RoutedItemKind| match kind {
        RoutedItemKind::Simple => 0,
        RoutedItemKind::MultiTwoQ(r) => *r,
        RoutedItemKind::ControlFlow(_) => unreachable!("prism's input has no control flow"),
    };
    result
        .order
        .order
        .iter()
        .map(|item| {
            let swaps = item
                .initial_swaps()
                .iter()
                .map(|s| s.map(|p| p.0))
                .collect();
            (swaps, item.node.index(), realization(&item.kind))
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use ndarray::array;
    use qiskit_circuit::dag_circuit::DAGCircuit;

    use super::super::super::dag::SabreNode;
    use super::super::super::heuristic::{
        BasicHeuristic, Heuristic, LookaheadHeuristic, SetScaling,
    };
    use super::super::{RoutingTarget, State, satisfy_successor_edges};
    use super::{
        DiGraph, InteractionKind, NLayout, NodeIndex, PhysicalQubit, RoutingProblem, SabreDAG,
        VirtRealizations, VirtualQubit, min_cost,
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

    fn line(n: u32) -> RoutingTarget {
        let edges: Vec<_> = (1..n).map(|i| [i - 1, i]).collect();
        crate::prism_routing::routing_target(&edges, n).expect("valid line")
    }

    #[test]
    fn min_cost_is_exact() {
        let dist = array![[0.0, 1.0, 5.0], [1.0, 0.0, 1.0], [5.0, 1.0, 0.0]];
        let layout = NLayout::generate_trivial_layout(3);
        // Each realization sums to 6; the sum of per-pair minima would be 2.
        let r = reals(&[&[[0, 1], [0, 2]], &[[0, 2], [1, 2]]]);
        assert!((min_cost(&r, &layout, None, &dist.view()) - 6.0).abs() < 1e-12);
        // A trial swap is scored without being applied to the layout.
        let dist = array![[0.0, 1.0, 2.0], [1.0, 0.0, 1.0], [2.0, 1.0, 0.0]];
        let r = reals(&[&[[0, 2]]]);
        let swap = Some([PhysicalQubit::new(1), PhysicalQubit::new(2)]);
        assert!((min_cost(&r, &layout, swap, &dist.view()) - 1.0).abs() < 1e-12);
        assert!((min_cost(&r, &layout, None, &dist.view()) - 2.0).abs() < 1e-12);
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
            target: &target,
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
                target: &target,
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
                let nodes = state.force_enable_closest_node(problem, &mut swaps);
                state.update_route(problem, &mut order, &nodes, Some(swaps));
            }
            assert_eq!(order.order.len(), sabre.dag.node_count());
        }
    }
}
