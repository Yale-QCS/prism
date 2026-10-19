//! The routing problem from Python, and the routed order returned to it.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rustworkx_core::petgraph::prelude::*;

use qiskit_circuit::VirtualQubit;

use super::score::Gate;
use super::{VirtRealizations, single_edge};
use crate::sabre::{InteractionKind, SabreDAG, SabreNode};

/// One op of the routing problem, in program order: `(default, predecessors, gates)`.
///
/// - `default`: the realization preferred on a tie.
/// - `predecessors`: the earlier ops that this op must follow.
/// - `gates[r]`: every gate of realization `r`, in order (see [`Gate`]).  Its two-qubit gates are
///   the pairs the router must bring together.
pub type Op = (u32, Vec<u32>, Vec<Vec<Gate>>);

/// One routed op: `(swaps, op, realization)`, where `swaps` are the physical-qubit swaps applied
/// just before op `op` executes with realization `realization`.
pub type RoutedOp = (Vec<[u32; 2]>, usize, u32);

/// The forward and reverse [`SabreDAG`]s of `ops` on `num_qubits` virtual qubits.
///
/// Node `k` of the forward DAG is op `k`.  The reverse DAG runs the program backwards, for
/// backward refinement: op `k` is its node `n - 1 - k`, and every dependency is flipped.  An op
/// with one realization of one pair becomes `TwoQ`, so the stock router handles it unchanged;
/// every other op becomes `MultiTwoQ`.
///
/// # Errors
///
/// If an op has no realization, a pair names an out-of-range or repeated qubit, or a predecessor
/// is not an earlier op.
pub fn sabre_dags(ops: &[Op], num_qubits: u32) -> PyResult<[SabreDAG; 2]> {
    let mut kinds = Vec::with_capacity(ops.len());
    let mut edges = Vec::new();
    for (k, (default, preds, gates)) in ops.iter().enumerate() {
        let invalid = |e: String| PyValueError::new_err(format!("op {k}: {e}"));
        kinds.push(op_kind(gates, *default, num_qubits).map_err(invalid)?);
        for &p in preds {
            if p as usize >= k {
                return Err(invalid(format!("predecessor {p} is not an earlier op")));
            }
            edges.push([p as usize, k]);
        }
    }
    let last = ops.len().saturating_sub(1);
    let mut reversed: Vec<_> = edges.iter().map(|&[p, k]| [last - k, last - p]).collect();
    // Add each node's out-edges in increasing target order, as the forward DAG does: the router
    // visits successors in the order of their edges.
    reversed.sort_unstable();
    let forward = sabre_dag(kinds.iter().cloned(), edges);
    Ok([forward, sabre_dag(kinds.into_iter().rev(), reversed)])
}

/// A [`SabreDAG`] of nodes `kinds` and dependency `edges`, without original DAG indices.
fn sabre_dag(
    kinds: impl ExactSizeIterator<Item = InteractionKind>,
    edges: Vec<[usize; 2]>,
) -> SabreDAG {
    let mut dag = DiGraph::with_capacity(kinds.len(), edges.len());
    for kind in kinds {
        dag.add_node(SabreNode {
            indices: Vec::new(),
            kind,
        });
    }
    for [a, b] in edges {
        dag.add_edge(NodeIndex::new(a), NodeIndex::new(b), ());
    }
    let first_layer = dag.externals(Direction::Incoming).collect();
    SabreDAG {
        initial: Vec::new(),
        dag,
        first_layer,
    }
}

/// The interaction kind of one op of realizations `gates`, or why a gate is invalid.
///
/// An op with no realization on at most one qubit pair cannot be routed onto one coupling edge:
/// its realizations lose their pairs, so it commits `default` at once and adds no SWAP.
fn op_kind(gates: &[Vec<Gate>], default: u32, num_qubits: u32) -> Result<InteractionKind, String> {
    let pair = |&[a, b]: &[u32; 2]| {
        if a >= num_qubits || b >= num_qubits || a == b {
            Err(format!("invalid pair ({a}, {b}) on {num_qubits} qubits"))
        } else {
            Ok([VirtualQubit::new(a), VirtualQubit::new(b)])
        }
    };
    let pairs = |real: &[Gate]| -> Result<Box<[_]>, String> {
        real.iter()
            .filter_map(|(qubits, ..)| <&[u32; 2]>::try_from(qubits.as_slice()).ok())
            .map(pair)
            .collect()
    };
    if gates.is_empty() {
        return Err("no realization".into());
    }
    let mut realizations: VirtRealizations = gates
        .iter()
        .map(|real| pairs(real))
        .collect::<Result<_, _>>()?;
    if let [real] = &*realizations
        && let [only] = &**real
    {
        return Ok(InteractionKind::TwoQ(*only));
    }
    if !realizations
        .iter()
        .any(|real| real.is_empty() || single_edge(real).is_some())
    {
        realizations = realizations.iter().map(|_| Box::default()).collect();
    }
    Ok(InteractionKind::MultiTwoQ {
        realizations,
        default_realization: default,
    })
}
