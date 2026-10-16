//! prism's layout search: the outer loop that upstream `SabreLayout` runs in `layout.rs`.
//!
//! For every starting layout, alternate forward and backward refinement routes for
//! `max_iterations`, then route forward once more with `swap_trials` trials from the refined
//! layout, and keep the final route of the lowest score over every trial of every start.  Python
//! keeps starting-layout generation and circuit emission.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rand::distr::StandardUniform;
use rand::prelude::*;
use rand_pcg::Pcg64Mcg;
use rayon_cond::CondIterator;

use qiskit_circuit::dag_circuit::DAGCircuit;
use qiskit_circuit::nlayout::NLayout;
use qiskit_util::getenv_use_multiple_threads;

use super::input::{Op, RoutedOp, sabre_dags};
use super::score::{Objective, Program, best};
use super::{explicit_target, layout_from_v2p, v2p_of};
use crate::sabre::heuristic::Heuristic;
use crate::sabre::route::{PyRoutingTarget, RoutingProblem, routed_ops, swap_map, swap_map_trial};

/// One final route: `(routed, final_v2p, refined_v2p)`.
type StartResult = (Vec<RoutedOp>, Vec<u32>, Vec<u32>);

/// Refine every start and route it.  Returns the [`StartResult`] whose route scores lowest under
/// `objective` (`"swaps"` or `"depth"`, see [`Objective`]) over every final trial of every start,
/// the earliest trial and start on a tie, where `refined_v2p` is the layout the final route began
/// from.
///
/// Route seeds follow prism's schedule: for start seed `s`, forward refinement `it` uses
/// `s*1000 + 2*it`, backward `s*1000 + 2*it + 1`, and the final route `s*1000 + 2*max_iterations`,
/// all mod 2^64; the final route's trials take their seeds from it as upstream `swap_map` does.  Starts run in parallel unless Qiskit's settings ask for one thread
/// (`getenv_use_multiple_threads`); the result does not depend on it.
///
/// # Errors
///
/// If there are no starts, the target is all-to-all, a start is not a permutation of its qubits,
/// `ops` is invalid, or `objective` is unknown.
#[pyfunction]
pub fn prism_layout_and_routing(
    ops: Vec<Op>,
    target: &PyRoutingTarget,
    heuristic: &Heuristic,
    starts: Vec<(u64, Vec<u32>)>,
    max_iterations: u64,
    swap_trials: usize,
    objective: &str,
) -> PyResult<StartResult> {
    let objective = Objective::try_from(objective)?;
    let target = explicit_target(target)?;
    let num_qubits = u32::try_from(target.num_qubits())?;
    let starts = starts
        .into_iter()
        .map(|(seed, v2p)| Ok((seed, layout_from_v2p(&v2p, num_qubits)?)))
        .collect::<PyResult<Vec<(u64, NLayout)>>>()?;
    let [sabre_fwd, sabre_rev] = sabre_dags(&ops, num_qubits)?;
    let program = Program::new(&ops, num_qubits)?;
    // Upstream reads the `DAGCircuit` only to rebuild a routed circuit or route control flow;
    // prism does neither, so an empty one fills the slot.
    let dag = DAGCircuit::new();
    let forward = RoutingProblem {
        target,
        sabre: &sabre_fwd,
        dag: &dag,
        heuristic,
    };
    let reverse = forward.with_sabre(&sabre_rev);
    let parallel = starts.len() > 1 && getenv_use_multiple_threads();

    let run_start = |(seed, mut layout): (u64, NLayout)| {
        let base = seed.wrapping_mul(1000);
        for it in 0..max_iterations {
            let seed = base.wrapping_add(2 * it);
            layout = swap_map(forward, &layout, Some(seed), 1, Some(false)).final_layout;
            let seed = base.wrapping_add(2 * it + 1);
            layout = swap_map(reverse, &layout, Some(seed), 1, Some(false)).final_layout;
        }
        // The trial seeds of upstream `swap_map`, but the trial is chosen by `objective`, not by
        // SWAP count alone, so trials with equal SWAPs are ranked by depth.
        let seed = base.wrapping_add(2 * max_iterations);
        let (metrics, routed, final_v2p) = Pcg64Mcg::seed_from_u64(seed)
            .sample_iter(StandardUniform)
            .take(swap_trials.max(1))
            .map(|trial_seed| {
                let result = swap_map_trial(forward, &layout, trial_seed);
                let routed = routed_ops(&result);
                (
                    program.metrics(&routed, &layout),
                    routed,
                    v2p_of(&result.final_layout),
                )
            })
            .min_by_key(|(metrics, ..)| metrics.score(objective))
            .expect("at least one trial");
        (metrics, (routed, final_v2p, v2p_of(&layout)))
    };
    let routes: Vec<_> = CondIterator::new(starts, parallel).map(run_start).collect();
    best(routes, objective).ok_or_else(|| PyValueError::new_err("no starting layout"))
}
