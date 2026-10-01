// The outer layout search that `SabreLayout` runs upstream (`layout.rs`):
// for every starting layout, alternate forward and backward refinement routes
// for `max_iterations`, then one multi-trial forward route from the refined
// layout. Prism keeps starting-layout generation, circuit emission, and
// objective scoring in Python; this function owns every routing call.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use rayon_cond::CondIterator;

use qiskit_circuit::dag_circuit::DAGCircuit;
use qiskit_circuit::nlayout::NLayout;
use qiskit_circuit::{PhysicalQubit, getenv_use_multiple_threads};

use crate::prism_routing::input::sabre_dag_from_flat;
use crate::sabre::dag::SabreDAG;
use crate::sabre::heuristic::Heuristic;
use crate::sabre::route::{PyRoutingTarget, RoutingProblem, flatten_routing_result, swap_map};

/// One flattened prism precompute: `(virt_pairs, succ, pred_count, local_default)`.
type Flat = (Vec<Vec<Vec<[u32; 2]>>>, Vec<Vec<u32>>, Vec<u32>, Vec<u32>);

fn dag_from_flat(flat: &Flat) -> PyResult<SabreDAG> {
    let (virt_pairs, succ, pred_count, local_default) = flat;
    let n_ops = virt_pairs.len();
    if succ.len() != n_ops || pred_count.len() != n_ops || local_default.len() != n_ops {
        return Err(PyValueError::new_err(
            "virt_pairs, succ, pred_count, local_default must have the same outer length",
        ));
    }
    Ok(sabre_dag_from_flat(
        virt_pairs,
        succ,
        pred_count,
        local_default,
    ))
}

fn layout_of(v2p: &[u32]) -> NLayout {
    NLayout::from_virtual_to_physical(v2p.iter().map(|&p| PhysicalQubit::new(p)).collect())
        .expect("starting layouts are permutations of the physical qubits")
}

/// Refine every start and route it. Returns, per start and in start order,
/// `(events, final_v2p, n_swaps, refined_v2p)` for its final route, where
/// `refined_v2p` is the layout that final route began from.
///
/// Route seeds follow the schedule Python used: start seed `s`, forward
/// refinement `s*1000 + 2*it`, backward `s*1000 + 2*it + 1`, final
/// `s*1000 + 2*max_iterations`, all mod 2^64.
#[pyfunction]
#[pyo3(signature=(forward, reverse, target, heuristic, starts, max_iterations, swap_trials, run_in_parallel=None))]
#[allow(clippy::too_many_arguments)]
pub fn prism_layout_and_routing(
    forward: Flat,
    reverse: Flat,
    target: &PyRoutingTarget,
    heuristic: &Heuristic,
    starts: Vec<(u64, Vec<u32>)>,
    max_iterations: usize,
    swap_trials: usize,
    run_in_parallel: Option<bool>,
) -> PyResult<Vec<(Vec<(u8, u32, u32)>, Vec<u32>, u32, Vec<u32>)>> {
    let Some(target_inner) = target.0.as_ref() else {
        return Err(PyValueError::new_err(
            "prism_layout_and_routing requires an explicit coupling target",
        ));
    };
    let sabre_fwd = dag_from_flat(&forward)?;
    let sabre_rev = dag_from_flat(&reverse)?;
    let dummy_dag = DAGCircuit::new();
    let problem_fwd = RoutingProblem {
        target: target_inner,
        sabre: &sabre_fwd,
        dag: &dummy_dag,
        heuristic,
    };
    let problem_rev = problem_fwd.with_sabre(&sabre_rev);
    let parallel = starts.len() > 1 && run_in_parallel.unwrap_or_else(getenv_use_multiple_threads);

    let run_start = |(seed, initial_v2p): (u64, Vec<u32>)| {
        let n_phys = initial_v2p.len() as u32;
        let mut v2p = initial_v2p;
        for it in 0..max_iterations as u64 {
            let fwd = swap_map(
                problem_fwd,
                &layout_of(&v2p),
                Some(seed.wrapping_mul(1000).wrapping_add(2 * it)),
                1,
                Some(false),
            );
            v2p = flatten_routing_result(&fwd, n_phys).1;
            let back = swap_map(
                problem_rev,
                &layout_of(&v2p),
                Some(seed.wrapping_mul(1000).wrapping_add(2 * it + 1)),
                1,
                Some(false),
            );
            v2p = flatten_routing_result(&back, n_phys).1;
        }
        let final_route = swap_map(
            problem_fwd,
            &layout_of(&v2p),
            Some(
                seed.wrapping_mul(1000)
                    .wrapping_add(2 * max_iterations as u64),
            ),
            swap_trials.max(1),
            Some(false),
        );
        let (events, final_v2p, n_swaps) = flatten_routing_result(&final_route, n_phys);
        (events, final_v2p, n_swaps, v2p)
    };
    Ok(CondIterator::new(starts, parallel).map(run_start).collect())
}
