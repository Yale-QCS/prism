//! prism's multi-realization extension of the vendored Sabre router.
//!
//! The routing hooks are in `route_ext.rs`, compiled inside `crate::sabre::route` so that they
//! can reach the router's private state.

pub mod input;
pub mod layout;
pub mod score;

use ndarray::Array2;
use pyo3::prelude::*;
use qiskit_circuit::{PhysicalQubit, VirtualQubit};
use qiskit_transpiler::neighbors::Neighbors;
use qiskit_transpiler::passes::best_subset;

use crate::sabre::route::RoutingTarget;

/// The two-qubit pairs of each candidate realization of one node.
pub type VirtRealizations = Box<[Box<[[VirtualQubit; 2]]>]>;

/// The qubit pair that every pair of `real` is on, in either order, if there is one.
pub fn single_edge(real: &[[VirtualQubit; 2]]) -> Option<[VirtualQubit; 2]> {
    let (&[a, b], rest) = real.split_first()?;
    rest.iter()
        .all(|&pair| pair == [a, b] || pair == [b, a])
        .then_some([a, b])
}

/// The routing target of an undirected edge list on `num_qubits` physical qubits.
pub fn routing_target(edges: &[[u32; 2]], num_qubits: u32) -> RoutingTarget {
    let mut adj = vec![Vec::new(); num_qubits as usize];
    for &[a, b] in edges {
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
    RoutingTarget::from_neighbors(Neighbors::from_parts_unchecked(neighbors, partition))
}

/// The subgraph that Qiskit's `DenseLayout` picks for `num_virtual` qubits (`best_subset`
/// without error rates), then the other physical qubits in index order.
#[pyfunction]
pub fn dense_layout(edges: Vec<[u32; 2]>, num_qubits: u32, num_virtual: usize) -> Vec<u32> {
    let n = num_qubits as usize;
    // `best_subset` would place one qubit for an empty circuit.
    let dense = if num_virtual == 0 {
        Vec::new()
    } else {
        let mut adjacency = Array2::zeros((n, n));
        for [a, b] in edges {
            adjacency[[a as usize, b as usize]] = 1.0;
            adjacency[[b as usize, a as usize]] = 1.0;
        }
        let no_errors = Array2::zeros((1, 1));
        let [_, _, dense] = best_subset(
            num_virtual,
            adjacency.view(),
            0,
            0,
            false,
            true,
            no_errors.view(),
        );
        dense
    };
    let rest = (0..n).filter(|p| !dense.contains(p));
    dense
        .iter()
        .copied()
        .chain(rest)
        .map(|p| p as u32)
        .collect()
}
