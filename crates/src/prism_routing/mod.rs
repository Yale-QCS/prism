//! prism's multi-realization extension of the vendored Qiskit Sabre router.
//!
//! - [`input`]: the flat routing problem from Python and the event stream back to it.
//! - [`layout`]: prism's layout search, the outer loop of upstream `SabreLayout`.
//!
//! The routing hooks themselves are in `route_ext.rs`, which is compiled as a child module of
//! `crate::sabre::route` (declared there) so that it can reach the router's private state.

pub mod input;
pub mod layout;

use ndarray::Array2;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use qiskit_circuit::nlayout::NLayout;
use qiskit_circuit::{PhysicalQubit, VirtualQubit};
use qiskit_transpiler::neighbors::Neighbors;
use qiskit_transpiler::passes::best_subset;

use crate::sabre::route::{PyRoutingTarget, RoutingTarget};

/// Candidate realizations of one node in virtual qubits: per realization, its two-qubit pairs.
pub type VirtRealizations = Box<[Box<[[VirtualQubit; 2]]>]>;

#[pymethods]
impl PyRoutingTarget {
    /// Build a target from an undirected edge list on `num_qubits` physical qubits.
    #[staticmethod]
    pub fn from_coupling_list(edges: Vec<[u32; 2]>, num_qubits: u32) -> PyResult<Self> {
        let n = num_qubits as usize;
        let mut adj: Vec<Vec<PhysicalQubit>> = vec![Vec::new(); n];
        for [a, b] in edges {
            if a >= num_qubits || b >= num_qubits {
                return Err(PyValueError::new_err(format!(
                    "edge ({a}, {b}) out of range for num_qubits={num_qubits}"
                )));
            }
            adj[a as usize].push(PhysicalQubit::new(b));
            adj[b as usize].push(PhysicalQubit::new(a));
        }
        let mut neighbors = Vec::new();
        let mut partition = Vec::with_capacity(n + 1);
        partition.push(0);
        for mut local in adj {
            local.sort_unstable();
            local.dedup();
            neighbors.extend(local);
            partition.push(neighbors.len());
        }
        let neighbors = Neighbors::from_parts(neighbors, partition)
            .map_err(|e| PyValueError::new_err(e.to_string()))?;
        Ok(Self(Some(RoutingTarget::from_neighbors(neighbors))))
    }

    /// The densely connected subgraph that Qiskit's `DenseLayout` picks for `num_virtual` qubits
    /// (`best_subset`, without error rates), in its breadth-first order, followed by the remaining
    /// physical qubits in index order: a virtual-to-physical list over every physical qubit.
    ///
    /// # Errors
    ///
    /// If the target is all-to-all, or `num_virtual` exceeds its number of qubits.
    pub fn dense_layout(&self, num_virtual: usize) -> PyResult<Vec<u32>> {
        let neighbors = &explicit_target(self)?.neighbors;
        let num_qubits = u32::try_from(neighbors.num_qubits())?;
        let physical = || (0..num_qubits).map(PhysicalQubit::new);
        if num_virtual > neighbors.num_qubits() {
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
}

/// The routing target behind a Python `RoutingTarget`, which prism requires to be explicit.
fn explicit_target(target: &PyRoutingTarget) -> PyResult<&RoutingTarget> {
    target.0.as_ref().ok_or_else(|| {
        PyValueError::new_err("prism routing needs a coupling target (all-to-all is not supported)")
    })
}

/// A layout from a virtual-to-physical list, which must be a permutation of `0..len`.
fn layout_from_v2p(v2p: &[u32]) -> PyResult<NLayout> {
    let mut seen = vec![false; v2p.len()];
    for &p in v2p {
        match seen.get_mut(p as usize) {
            Some(slot @ false) => *slot = true,
            _ => {
                return Err(PyValueError::new_err(format!(
                    "layout {v2p:?} is not a permutation of 0..{}",
                    v2p.len()
                )));
            }
        }
    }
    NLayout::from_virtual_to_physical(v2p.iter().copied().map(PhysicalQubit::new).collect())
}

/// The virtual-to-physical list of `layout`.
fn v2p_of(layout: &NLayout) -> Vec<u32> {
    layout.iter_virtual().map(|(_, p)| p.0).collect()
}
