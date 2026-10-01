// Multi-realization SABRE routing entry point. Builds a `SabreDAG` directly
// from a prism precompute, dispatches to stock `swap_map`, and
// serializes the resulting routed order back to prism's flat event
// stream via `route::flatten_routing_result` (which lives inside the route
// module so it can read private fields of `RoutingResult`).

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use qiskit_circuit::PhysicalQubit;
use qiskit_circuit::dag_circuit::DAGCircuit;
use qiskit_circuit::nlayout::NLayout;

use crate::prism_routing::input::sabre_dag_from_flat;
use crate::sabre::heuristic::Heuristic;
use crate::sabre::route::{PyRoutingTarget, RoutingProblem, flatten_routing_result, swap_map};

/// Multi-realization SABRE routing pyfunction. Builds a `SabreDAG` with
/// `MultiTwoQ` variants from the flat prism precompute, runs
/// `swap_trials` independent attempts of stock `swap_map`, and serializes
/// the lowest-swap result.
///
/// Returns `(events, final_v2p, n_swaps)`.
#[pyfunction]
#[pyo3(signature=(virt_pairs, succ, pred_count, local_default, target, heuristic, initial_v2p, swap_trials=1, seed=0, run_in_parallel=None))]
pub fn prism_routing(
    virt_pairs: Vec<Vec<Vec<[u32; 2]>>>,
    succ: Vec<Vec<u32>>,
    pred_count: Vec<u32>,
    local_default: Vec<u32>,
    target: &PyRoutingTarget,
    heuristic: &Heuristic,
    initial_v2p: Vec<u32>,
    swap_trials: usize,
    seed: u64,
    run_in_parallel: Option<bool>,
) -> PyResult<(Vec<(u8, u32, u32)>, Vec<u32>, u32)> {
    let Some(target_inner) = target.0.as_ref() else {
        return Err(PyValueError::new_err(
            "prism_routing requires an explicit coupling target (all-to-all not supported)",
        ));
    };
    let n_ops = virt_pairs.len();
    if succ.len() != n_ops || pred_count.len() != n_ops || local_default.len() != n_ops {
        return Err(PyValueError::new_err(
            "virt_pairs, succ, pred_count, local_default must have the same outer length",
        ));
    }
    let n_phys = initial_v2p.len() as u32;
    let sabre_dag = sabre_dag_from_flat(&virt_pairs, &succ, &pred_count, &local_default);
    let initial_layout = NLayout::from_virtual_to_physical(
        initial_v2p.iter().map(|&p| PhysicalQubit::new(p)).collect(),
    )?;
    // Stock SABRE's `RoutingProblem.dag` is required for `ControlFlow` nodes
    // and for `RoutingResult::rebuild`. Marabbecca's IR never produces either,
    // so an empty `DAGCircuit` satisfies the type without affecting behavior.
    let dummy_dag = DAGCircuit::new();
    let problem = RoutingProblem {
        target: target_inner,
        sabre: &sabre_dag,
        dag: &dummy_dag,
        heuristic,
    };
    let result = swap_map(
        problem,
        &initial_layout,
        Some(seed),
        swap_trials.max(1),
        run_in_parallel,
    );
    Ok(flatten_routing_result(&result, n_phys))
}
