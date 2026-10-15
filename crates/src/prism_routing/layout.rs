//! prism's layout search: the outer loop that upstream `SabreLayout` runs in `layout.rs`.
//!
//! For every starting layout, alternate forward and backward refinement routes for
//! `max_iterations`, then route forward once more with `swap_trials` trials from the refined
//! layout.  Python keeps starting-layout generation, circuit emission and objective scoring.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rayon_cond::CondIterator;

use qiskit_circuit::dag_circuit::DAGCircuit;
use qiskit_circuit::nlayout::NLayout;
use qiskit_util::getenv_use_multiple_threads;

use super::input::{Event, Flat, sabre_dag_from_flat};
use super::{explicit_target, layout_from_v2p, v2p_of};
use crate::sabre::heuristic::Heuristic;
use crate::sabre::route::{PyRoutingTarget, RoutingProblem, flatten_routing_result, swap_map};

/// One final route: `(events, final_v2p, n_swaps, refined_v2p)`.
type StartResult = (Vec<Event>, Vec<u32>, u32, Vec<u32>);

/// Refine every start and route it.  Returns one [`StartResult`] per start, in start order, where
/// `refined_v2p` is the layout the final route began from.
///
/// Route seeds follow prism's schedule: for start seed `s`, forward refinement `it` uses
/// `s*1000 + 2*it`, backward `s*1000 + 2*it + 1`, and the final route `s*1000 + 2*max_iterations`,
/// all mod 2^64.
///
/// # Errors
///
/// If the target is all-to-all, a start is not a permutation, or a problem is invalid.
#[pyfunction]
#[pyo3(signature=(forward, reverse, target, heuristic, starts, max_iterations, swap_trials, run_in_parallel=None))]
#[allow(clippy::too_many_arguments, clippy::needless_pass_by_value)]
pub fn prism_layout_and_routing(
    forward: Flat,
    reverse: Flat,
    target: &PyRoutingTarget,
    heuristic: &Heuristic,
    starts: Vec<(u64, Vec<u32>)>,
    max_iterations: u64,
    swap_trials: usize,
    run_in_parallel: Option<bool>,
) -> PyResult<Vec<StartResult>> {
    let target = explicit_target(target)?;
    let starts = starts
        .iter()
        .map(|(seed, v2p)| Ok((*seed, layout_from_v2p(v2p)?)))
        .collect::<PyResult<Vec<(u64, NLayout)>>>()?;
    let Some(num_qubits) = starts.first().map(|(_, layout)| layout.num_qubits()) else {
        return Ok(Vec::new());
    };
    if starts
        .iter()
        .any(|(_, layout)| layout.num_qubits() != num_qubits)
    {
        return Err(PyValueError::new_err("starting layouts differ in length"));
    }
    let num_qubits = u32::try_from(num_qubits)?;
    let sabre_fwd = sabre_dag_from_flat(&forward, num_qubits)?;
    let sabre_rev = sabre_dag_from_flat(&reverse, num_qubits)?;
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
    let parallel = starts.len() > 1 && run_in_parallel.unwrap_or_else(getenv_use_multiple_threads);

    let run_start = |(seed, mut layout): (u64, NLayout)| {
        let base = seed.wrapping_mul(1000);
        for it in 0..max_iterations {
            let seed = base.wrapping_add(2 * it);
            layout = swap_map(forward, &layout, Some(seed), 1, Some(false)).final_layout;
            let seed = base.wrapping_add(2 * it + 1);
            layout = swap_map(reverse, &layout, Some(seed), 1, Some(false)).final_layout;
        }
        let seed = base.wrapping_add(2 * max_iterations);
        let result = swap_map(
            forward,
            &layout,
            Some(seed),
            swap_trials.max(1),
            Some(false),
        );
        let (events, n_swaps) = flatten_routing_result(&result);
        (
            events,
            v2p_of(&result.final_layout),
            n_swaps,
            v2p_of(&layout),
        )
    };
    Ok(CondIterator::new(starts, parallel).map(run_start).collect())
}
