//! The flat routing input from Python, and the event stream returned to it.
//!
//! Python passes one routing problem as four parallel arrays indexed by op (see [Flat]).  The
//! result is a stream of `(kind, a, b)` events:
//!
//! - `(EVENT_KIND_COMMIT, op_idx, real_idx)`: emit the whole realization `real_idx` of op `op_idx`
//!   at the current layout.
//! - `(EVENT_KIND_SWAP, p1, p2)`: swap physical qubits `p1` and `p2`.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rustworkx_core::petgraph::prelude::*;

use qiskit_circuit::VirtualQubit;

use super::{VirtRealizations, single_edge};
use crate::sabre::{InteractionKind, SabreDAG, SabreNode};

/// One `(kind, a, b)` event.
pub type Event = (u8, u32, u32);

/// Event tag: commit a whole realization.
pub const EVENT_KIND_COMMIT: u8 = 0;
/// Event tag: apply a swap.
pub const EVENT_KIND_SWAP: u8 = 1;

/// One routing problem as Python flattens it: `(virt_pairs, succ, pred_count, local_default)`.
///
/// - `virt_pairs[k][r]`: the virtual-qubit pairs of realization `r` of op `k`.  Some realization
///   of each op has no pairs or all its pairs on one qubit pair, so the router can route it as one
///   edge.
/// - `succ[k]`: the ops that depend on op `k`, one entry per dependency edge.
/// - `pred_count[k]`: the number of dependency edges into op `k`.
/// - `local_default[k]`: the realization of op `k` preferred on a tie.
pub type Flat = (Vec<Vec<Vec<[u32; 2]>>>, Vec<Vec<u32>>, Vec<u32>, Vec<u32>);

fn invalid(msg: String) -> PyErr {
    PyValueError::new_err(msg)
}

/// Build a [`SabreDAG`] from a validated [`Flat`] problem on `num_qubits` virtual qubits.
///
/// An op with one realization of one pair becomes `TwoQ`, so the stock router handles it
/// unchanged; every other op becomes `MultiTwoQ`.  `SabreNode::indices[0]` holds the op index
/// `k`, which the event stream reports back to Python.
///
/// # Errors
///
/// If the arrays differ in length, an op has no realization or none on at most one qubit pair, a
/// default is out of range, a pair names an out-of-range or repeated qubit, a successor is out of
/// range, or `pred_count` disagrees with `succ`.
pub fn sabre_dag_from_flat(flat: &Flat, num_qubits: u32) -> PyResult<SabreDAG> {
    let (virt_pairs, succ, pred_count, local_default) = flat;
    let n_ops = virt_pairs.len();
    if succ.len() != n_ops || pred_count.len() != n_ops || local_default.len() != n_ops {
        return Err(invalid(
            "virt_pairs, succ, pred_count and local_default must have the same length".into(),
        ));
    }
    let mut dag: DiGraph<SabreNode, ()> = DiGraph::with_capacity(n_ops, n_ops);
    for (k, (reals, &default)) in virt_pairs.iter().zip(local_default).enumerate() {
        let kind =
            op_kind(reals, default, num_qubits).map_err(|e| invalid(format!("op {k}: {e}")))?;
        dag.add_node(SabreNode {
            indices: vec![NodeIndex::new(k)],
            kind,
        });
    }
    for (k, succs) in succ.iter().enumerate() {
        for &s in succs {
            if s as usize >= n_ops {
                return Err(invalid(format!("op {k}: successor {s} out of range")));
            }
            dag.add_edge(NodeIndex::new(k), NodeIndex::new(s as usize), ());
        }
    }
    for (node, &count) in dag.node_indices().zip(pred_count) {
        let edges = dag.edges_directed(node, Direction::Incoming).count();
        if edges != count as usize {
            return Err(invalid(format!(
                "op {}: pred_count is {count} but succ has {edges} edges into it",
                node.index()
            )));
        }
    }
    let first_layer = dag.externals(Direction::Incoming).collect();
    Ok(SabreDAG {
        initial: Vec::new(),
        dag,
        first_layer,
    })
}

/// The interaction kind of one op, or why its realizations are invalid.
fn op_kind(
    reals: &[Vec<[u32; 2]>],
    default: u32,
    num_qubits: u32,
) -> Result<InteractionKind, String> {
    if reals.is_empty() {
        return Err("no realizations".into());
    }
    if default as usize >= reals.len() {
        return Err(format!("default realization {default} out of range"));
    }
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
        return Err("every realization has pairs on several qubit pairs".into());
    }
    Ok(InteractionKind::MultiTwoQ {
        realizations,
        default_realization: default,
    })
}

#[cfg(test)]
mod tests {
    use super::{Flat, InteractionKind, sabre_dag_from_flat};

    fn flat(virt_pairs: Vec<Vec<Vec<[u32; 2]>>>, succ: Vec<Vec<u32>>, pred: Vec<u32>) -> Flat {
        let n = virt_pairs.len();
        (virt_pairs, succ, pred, vec![0; n])
    }

    #[test]
    fn single_pair_ops_are_stock_two_qubit_nodes() {
        let input = flat(
            vec![
                vec![vec![[0, 1]]],
                vec![vec![[1, 2]], vec![[0, 2]]],
                vec![vec![]],
            ],
            vec![vec![1], vec![], vec![]],
            vec![0, 1, 0],
        );
        let sabre = sabre_dag_from_flat(&input, 3).expect("valid input");
        let kinds: Vec<_> = sabre.dag.node_weights().map(|n| &n.kind).collect();
        assert!(matches!(kinds[0], InteractionKind::TwoQ(_)));
        assert!(matches!(kinds[1], InteractionKind::MultiTwoQ { .. }));
        assert!(matches!(kinds[2], InteractionKind::MultiTwoQ { .. }));
        let first: Vec<usize> = sabre.first_layer.iter().map(|n| n.index()).collect();
        assert_eq!(first, vec![0, 2]);
    }

    #[test]
    fn invalid_inputs_are_errors() {
        let ok = || flat(vec![vec![vec![[0, 1]]]], vec![vec![]], vec![0]);
        assert!(sabre_dag_from_flat(&ok(), 2).is_ok());
        assert!(sabre_dag_from_flat(&ok(), 1).is_err(), "qubit out of range");
        let mut bad = ok();
        bad.0[0] = vec![];
        assert!(sabre_dag_from_flat(&bad, 2).is_err(), "no realizations");
        let mut bad = ok();
        bad.0[0][0][0] = [1, 1];
        assert!(sabre_dag_from_flat(&bad, 2).is_err(), "repeated qubit");
        let mut bad = ok();
        bad.3[0] = 1;
        assert!(
            sabre_dag_from_flat(&bad, 2).is_err(),
            "default out of range"
        );
        let mut bad = ok();
        bad.1[0] = vec![1];
        assert!(
            sabre_dag_from_flat(&bad, 2).is_err(),
            "successor out of range"
        );
        let mut bad = ok();
        bad.2[0] = 1;
        assert!(sabre_dag_from_flat(&bad, 2).is_err(), "pred_count mismatch");
        let mut bad = ok();
        bad.0[0] = vec![vec![[0, 1], [1, 2]]];
        assert!(
            sabre_dag_from_flat(&bad, 3).is_err(),
            "no single-edge realization"
        );
        let mut bad = ok();
        bad.2.push(0);
        assert!(sabre_dag_from_flat(&bad, 2).is_err(), "length mismatch");
    }
}
