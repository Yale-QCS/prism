//! The routing problem from Python, and the routed order returned to it.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rustworkx_core::petgraph::prelude::*;

use qiskit_circuit::VirtualQubit;

use super::score::Gate;
use super::{VirtRealizations, single_edge};
use crate::sabre::{InteractionKind, SabreDAG, SabreNode};

/// One op of the routing problem, in program order: `(realizations, default, predecessors, gates)`.
///
/// - `realizations[r]`: the virtual-qubit pairs of realization `r`.  Some realization has no
///   pairs or all its pairs on one qubit pair, so the router can route it on one edge.
/// - `default`: the realization preferred on a tie.
/// - `predecessors`: the earlier ops that this op must follow.
/// - `gates[r]`: every gate of realization `r`, in order, to score routes (see
///   [`Program`](super::score::Program)).
pub type Op = (Vec<Vec<[u32; 2]>>, u32, Vec<u32>, Vec<Vec<Gate>>);

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
/// If an op has no realization or none on at most one qubit pair, a pair names an out-of-range or
/// repeated qubit, or a predecessor is not an earlier op.
pub fn sabre_dags(ops: &[Op], num_qubits: u32) -> PyResult<[SabreDAG; 2]> {
    let mut kinds = Vec::with_capacity(ops.len());
    let mut edges = Vec::new();
    for (k, (reals, default, preds, _)) in ops.iter().enumerate() {
        let invalid = |e: String| PyValueError::new_err(format!("op {k}: {e}"));
        kinds.push(op_kind(reals, *default, num_qubits).map_err(invalid)?);
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

/// The interaction kind of one op, or why its realizations are invalid.
fn op_kind(
    reals: &[Vec<[u32; 2]>],
    default: u32,
    num_qubits: u32,
) -> Result<InteractionKind, String> {
    let pair = |&[a, b]: &[u32; 2]| {
        if a >= num_qubits || b >= num_qubits || a == b {
            Err(format!("invalid pair ({a}, {b}) on {num_qubits} qubits"))
        } else {
            Ok([VirtualQubit::new(a), VirtualQubit::new(b)])
        }
    };
    if let [real] = reals
        && let [only] = real.as_slice()
    {
        return Ok(InteractionKind::TwoQ(pair(only)?));
    }
    let realizations: VirtRealizations = reals
        .iter()
        .map(|real| real.iter().map(pair).collect())
        .collect::<Result<_, _>>()?;
    if !realizations
        .iter()
        .any(|real| real.is_empty() || single_edge(real).is_some())
    {
        return Err("no realization on at most one qubit pair".into());
    }
    Ok(InteractionKind::MultiTwoQ {
        realizations,
        default_realization: default,
    })
}
