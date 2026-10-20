//! prism's layout search: the outer loop that upstream `SabreLayout` runs.

use pyo3::prelude::*;
use rand::distr::StandardUniform;
use rand::prelude::*;
use rand_pcg::Pcg64Mcg;
use rayon_cond::CondIterator;

use qiskit_circuit::PhysicalQubit;
use qiskit_circuit::dag_circuit::DAGCircuit;
use qiskit_circuit::nlayout::NLayout;
use qiskit_util::getenv_use_multiple_threads;

use super::input::{Op, RoutedOp, sabre_dags};
use super::routing_target;
use super::score::{Metrics, Objective, metrics, num_clbits};
use crate::sabre::heuristic::{
    BasicHeuristic, DecayHeuristic, Heuristic, LookaheadHeuristic, SetScaling,
};
use crate::sabre::route::route_ext::routed_ops;
use crate::sabre::route::{RoutingProblem, swap_map, swap_map_trial};

/// prism's commits route gates in cascades, and eight lookahead layers at the stock weight beat
/// Qiskit 2.3's 20-gate extended set on both SWAPs and depth.  The scaling is `Constant` because
/// `SetScaling::Size` would count only the stock gates of a layer, not its multi nodes.
const LOOKAHEAD_LAYERS: usize = 8;

/// Qiskit 2.6 `SabreLayout`'s heuristic, with [`LOOKAHEAD_LAYERS`] lookahead layers.
fn heuristic(num_qubits: u32) -> Heuristic {
    let n = f64::from(num_qubits);
    Heuristic::new(
        Some(BasicHeuristic::new(1.0, SetScaling::Constant)),
        LookaheadHeuristic::new(vec![0.5 / n; LOOKAHEAD_LAYERS], SetScaling::Constant),
        Some(DecayHeuristic::new(0.001, 5)),
        Some(10 * num_qubits as usize),
        1e-10,
    )
}

fn v2p_of(layout: &NLayout) -> Vec<u32> {
    layout.iter_virtual().map(|(_, p)| p.0).collect()
}

/// Refine each start by `max_iterations` forward and backward routes, route it forward with
/// `swap_trials` trials, and return `(route, final layout, refined layout)` of the trial that
/// ranks best under `objective`, the earliest on a tie.
///
/// For start seed `s`, forward refinement `it` uses seed `s*1000 + 2*it`, backward
/// `s*1000 + 2*it + 1`, and the final route `s*1000 + 2*max_iterations` (mod 2^64), from which
/// its trial seeds follow as in upstream `swap_map`.  Starts run in parallel unless
/// `getenv_use_multiple_threads` says otherwise; the result is the same.
#[pyfunction]
pub fn prism_layout_and_routing(
    ops: Vec<Op>,
    edges: Vec<[u32; 2]>,
    num_qubits: u32,
    starts: Vec<(u64, Vec<u32>)>,
    max_iterations: u64,
    swap_trials: usize,
    objective: Objective,
) -> (Vec<RoutedOp>, Vec<u32>, Vec<u32>) {
    let target = &routing_target(&edges, num_qubits);
    let heuristic = &heuristic(num_qubits);
    let [sabre_fwd, sabre_rev] = sabre_dags(&ops, num_qubits);
    let num_clbits = num_clbits(&ops);
    // Upstream reads the `DAGCircuit` only to rebuild a routed circuit or route control flow.
    let dag = DAGCircuit::new();
    let forward = RoutingProblem {
        target,
        sabre: &sabre_fwd,
        dag: &dag,
        heuristic,
    };
    let reverse = forward.with_sabre(&sabre_rev);
    let parallel = starts.len() > 1 && getenv_use_multiple_threads();

    let run_start = |(seed, v2p): (u64, Vec<u32>)| {
        let mut layout =
            NLayout::from_virtual_to_physical(v2p.into_iter().map(PhysicalQubit::new).collect())
                .expect("a layout fits in u32");
        let base = seed.wrapping_mul(1000);
        for it in 0..max_iterations {
            let seed = base.wrapping_add(2 * it);
            layout = swap_map(forward, &layout, Some(seed), 1, Some(false)).final_layout;
            let seed = base.wrapping_add(2 * it + 1);
            layout = swap_map(reverse, &layout, Some(seed), 1, Some(false)).final_layout;
        }
        // Upstream picks the trial with the fewest SWAPs; prism picks by `objective`, and stops a
        // trial once it cannot win.
        let seed = base.wrapping_add(2 * max_iterations);
        let mut best: Option<(Metrics, _, _)> = None;
        let mut max_swaps = usize::MAX;
        let trial_seeds = Pcg64Mcg::seed_from_u64(seed).sample_iter(StandardUniform);
        for trial_seed in trial_seeds.take(swap_trials) {
            let Some(result) = swap_map_trial(forward, &layout, trial_seed, max_swaps) else {
                continue;
            };
            let routed = routed_ops(&result);
            let metrics = metrics(&ops, num_clbits, &routed, &layout);
            if let Some((m, ..)) = &best
                && objective.cmp(&metrics, m).is_ge()
            {
                continue;
            }
            max_swaps = objective.max_swaps(&metrics);
            best = Some((metrics, routed, v2p_of(&result.final_layout)));
        }
        let (metrics, routed, final_v2p) = best.expect("swap_trials >= 1");
        (metrics, (routed, final_v2p, v2p_of(&layout)))
    };
    CondIterator::new(starts, parallel)
        .map(run_start)
        .collect::<Vec<_>>()
        .into_iter()
        .min_by(|(a, _), (b, _)| objective.cmp(a, b))
        .expect("at least one start")
        .1
}
