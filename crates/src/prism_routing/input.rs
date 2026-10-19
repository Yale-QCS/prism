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
/// every other op becomes `MultiTwoQ`.  The stock layers hold one `TwoQ` node per qubit, so the
/// `TwoQ` ops on each qubit must be ordered: an op that commutes with the latest `TwoQ` op on one
/// of its qubits becomes `MultiTwoQ` too.
///
/// # Errors
///
/// If an op has no realization, a pair names an out-of-range or repeated qubit, or a predecessor
/// is not an earlier op.
pub fn sabre_dags(ops: &[Op], num_qubits: u32) -> PyResult<[SabreDAG; 2]> {
    let mut kinds = Vec::with_capacity(ops.len());
    let mut edges = Vec::new();
    // The latest `TwoQ` op on each virtual qubit.
    let mut last_two_q: Vec<Option<usize>> = vec![None; num_qubits as usize];
    for (k, (default, preds, gates)) in ops.iter().enumerate() {
        let invalid = |e: String| PyValueError::new_err(format!("op {k}: {e}"));
        for &p in preds {
            if p as usize >= k {
                return Err(invalid(format!("predecessor {p} is not an earlier op")));
            }
            edges.push([p as usize, k]);
        }
        let realizations = realizations(gates, num_qubits).map_err(invalid)?;
        let ordered = |pair: &[VirtualQubit; 2]| {
            pair.iter()
                .all(|q| last_two_q[q.index()].is_none_or(|j| precedes(ops, j, k)))
        };
        if let [real] = &*realizations
            && let [pair] = &**real
            && ordered(pair)
        {
            for q in pair {
                last_two_q[q.index()] = Some(k);
            }
            kinds.push(InteractionKind::TwoQ(*pair));
        } else {
            kinds.push(InteractionKind::MultiTwoQ {
                realizations,
                default_realization: *default,
            });
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

/// Whether op `j` precedes the later op `k` through the predecessors of `ops`.
fn precedes(ops: &[Op], j: usize, k: usize) -> bool {
    let mut seen = vec![false; k - j];
    let mut stack = vec![k];
    while let Some(n) = stack.pop() {
        for &p in &ops[n].1 {
            let p = p as usize;
            if p == j {
                return true;
            }
            if p > j && !std::mem::replace(&mut seen[p - j], true) {
                stack.push(p);
            }
        }
    }
    false
}

/// The pairs of each realization `gates[r]` of one op, or why a gate is invalid.
///
/// An op with no realization on at most one qubit pair cannot be routed onto one coupling edge:
/// its realizations lose their pairs, so it commits its default at once and adds no SWAP.
fn realizations(gates: &[Vec<Gate>], num_qubits: u32) -> Result<VirtRealizations, String> {
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
    let realizations: VirtRealizations = gates
        .iter()
        .map(|real| pairs(real))
        .collect::<Result<_, _>>()?;
    if realizations
        .iter()
        .any(|real| real.is_empty() || single_edge(real).is_some())
    {
        Ok(realizations)
    } else {
        Ok(realizations.iter().map(|_| Box::default()).collect())
    }
}
