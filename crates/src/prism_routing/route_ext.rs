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
    /// Positions in `State::swap_scores` of the candidate swaps on each physical qubit, for the
    /// current routing step.
    swaps_on: Vec<Vec<usize>>,
    /// Scratch for [`Self::add_scores`]: the candidate swaps on one node's qubits.
    touched: Vec<usize>,
}

impl MultiLayers {
    pub(super) fn new(num_layers: u16, num_qubits: u32, sabre: &SabreDAG) -> Self {
        Self {
            layers: vec![Vec::new(); num_layers.into()].into_boxed_slice(),
            location: vec![None; sabre.dag.node_count()].into(),
            front_active: vec![0; num_qubits as usize].into(),
            phys_load: vec![0.0; num_qubits as usize],
            swaps_on: vec![Vec::new(); num_qubits as usize],
            touched: Vec::new(),
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
        &mut self,
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
            // A swap on none of the node's qubits leaves its cost unchanged, so only the swaps on
            // them change score, in the same order of additions as a full pass.
            self.touched.clear();
            self.touched
                .extend(qubits(reals).flat_map(|v| &self.swaps_on[layout[v].index()]));
            self.touched.sort_unstable();
            self.touched.dedup();
            for &i in &self.touched {
                let (swap, score) = &mut swap_scores[i];
                *score += weight * (min_cost(reals, layout, Some(*swap), &dist) - base);
            }
        }
        weight * absolute
    }
}

impl State {
    /// Append the candidate swaps touching qubits of front-layer multi nodes, after the stock
    /// candidates and without duplicating them, and index all candidates by qubit.  With no multi
    /// nodes the list is unchanged.
    pub(super) fn push_multi_candidates(&mut self, problem: RoutingProblem) {
        let front = self.layers.front();
        let multi = &mut self.multi;
        for swaps in &mut multi.swaps_on {
            swaps.clear();
        }
        for (i, (swap, _)) in self.swap_scores.iter().enumerate() {
            for p in swap {
                multi.swaps_on[p.index()].push(i);
            }
        }
        for &node in &multi.layers[0] {
            for v in qubits(realizations(problem.sabre, node)) {
                let phys = self.layout[v];
                for &neighbor in &problem.target.neighbors[phys] {
                    // Edges to stock-active qubits were pushed by the stock loop.
                    if front.is_active(neighbor) {
                        continue;
                    }
                    // Mirror the stock convention: edges between two active qubits are ordered.
                    let swap = if multi.front_active[self.layout[neighbor]] > 0 {
                        [phys.min(neighbor), phys.max(neighbor)]
                    } else {
                        [phys, neighbor]
                    };
                    let on_phys = &multi.swaps_on[phys.index()];
                    if !on_phys.iter().any(|&i| self.swap_scores[i].0 == swap) {
                        for p in swap {
                            multi.swaps_on[p.index()].push(self.swap_scores.len());
                        }
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
