//! prism's multi-realization extension of the vendored Qiskit Sabre router.
//!
//! - [`input`]: the routing problem from Python and the routed order back to it.
//! - [`layout`]: prism's layout search, the outer loop of upstream `SabreLayout`.
//! - [`score`]: the metrics that rank the routes of the layout search.
//!
//! The routing hooks themselves are in `route_ext.rs`, which is compiled as a child module of
//! `crate::sabre::route` (declared there) so that it can reach the router's private state.

pub mod input;
pub mod layout;
pub mod score;

use ndarray::Array2;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use qiskit_circuit::nlayout::NLayout;
use qiskit_circuit::{PhysicalQubit, VirtualQubit};
use qiskit_transpiler::neighbors::Neighbors;
use qiskit_transpiler::passes::best_subset;

use crate::sabre::route::RoutingTarget;

/// Candidate realizations of one node in virtual qubits: per realization, its two-qubit pairs.
pub type VirtRealizations = Box<[Box<[[VirtualQubit; 2]]>]>;

/// The qubit pair that every pair of `real` is on, in either order: one coupling edge executes
/// `real`.  `None` if `real` has no pairs or pairs on several qubit pairs.
pub fn single_edge(real: &[[VirtualQubit; 2]]) -> Option<[VirtualQubit; 2]> {
    let (&[a, b], rest) = real.split_first()?;
    rest.iter()
        .all(|&pair| pair == [a, b] || pair == [b, a])
        .then_some([a, b])
}

/// The routing target of an undirected edge list on `num_qubits` physical qubits.
///
/// # Errors
///
/// If an edge names a qubit out of range.
pub fn routing_target(edges: &[[u32; 2]], num_qubits: u32) -> PyResult<RoutingTarget> {
    let mut adj: Vec<Vec<PhysicalQubit>> = vec![Vec::new(); num_qubits as usize];
    for &[a, b] in edges {
        if a >= num_qubits || b >= num_qubits {
            return Err(PyValueError::new_err(format!(
                "edge ({a}, {b}) out of range for num_qubits={num_qubits}"
            )));
        }
        adj[a as usize].push(PhysicalQubit::new(b));
        adj[b as usize].push(PhysicalQubit::new(a));
    }
    let mut neighbors = Vec::new();
    let mut partition = vec![0];
    for mut local in adj {
        local.sort_unstable();
        local.dedup();
        neighbors.extend(local);
        partition.push(neighbors.len());
    }
    let neighbors = Neighbors::from_parts(neighbors, partition)
        .map_err(|e| PyValueError::new_err(e.to_string()))?;
    Ok(RoutingTarget::from_neighbors(neighbors))
}

/// The densely connected subgraph that Qiskit's `DenseLayout` picks for `num_virtual` qubits
/// (`best_subset`, without error rates), in its breadth-first order, followed by the remaining
/// physical qubits in index order: a virtual-to-physical list over every physical qubit.
///
/// # Errors
///
/// If an edge is out of range, or `num_virtual` exceeds `num_qubits`.
#[pyfunction]
pub fn dense_layout(
    edges: Vec<[u32; 2]>,
    num_qubits: u32,
    num_virtual: usize,
) -> PyResult<Vec<u32>> {
    let neighbors = routing_target(&edges, num_qubits)?.neighbors;
    let physical = || (0..num_qubits).map(PhysicalQubit::new);
    if num_virtual > num_qubits as usize {
        return Err(PyValueError::new_err(format!(
            "{num_virtual} virtual qubits do not fit on {num_qubits} physical qubits"
        )));
    }
    // `best_subset` would place one qubit for an empty circuit.
    let dense = if num_virtual == 0 {
        Vec::new()
    } else {
        let mut adjacency = Array2::zeros((num_qubits as usize, num_qubits as usize));
        for p in physical() {
            for q in &neighbors[p] {
                adjacency[[p.index(), q.index()]] = 1.0;
            }
        }
        // No error rates: `use_error` is false, so the error matrix and counts are unused.
        let [_rows, _cols, dense] = best_subset(
            num_virtual,
            adjacency.view(),
            0,
            0,
            false,
            true,
            Array2::zeros((1, 1)).view(),
        );
        dense
    };
    let dense: Vec<PhysicalQubit> = dense
        .into_iter()
        .map(|p| u32::try_from(p).map(PhysicalQubit::new))
        .collect::<Result<_, _>>()?;
    let rest = physical().filter(|p| !dense.contains(p));
    Ok(dense.iter().copied().chain(rest).map(|p| p.0).collect())
}

/// A layout from a virtual-to-physical list, which must be a permutation of `0..num_qubits`.
fn layout_from_v2p(v2p: &[u32], num_qubits: u32) -> PyResult<NLayout> {
    let mut seen = vec![false; num_qubits as usize];
    let distinct = v2p.iter().all(|&p| match seen.get_mut(p as usize) {
        Some(slot @ false) => {
            *slot = true;
            true
        }
        _ => false,
    });
    if !distinct || v2p.len() != seen.len() {
        return Err(PyValueError::new_err(format!(
            "layout {v2p:?} is not a permutation of 0..{num_qubits}"
        )));
    }
    NLayout::from_virtual_to_physical(v2p.iter().copied().map(PhysicalQubit::new).collect())
}

/// The virtual-to-physical list of `layout`.
fn v2p_of(layout: &NLayout) -> Vec<u32> {
    layout.iter_virtual().map(|(_, p)| p.0).collect()
}
