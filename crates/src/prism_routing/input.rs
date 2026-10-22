//! The routing problem from Python as Sabre DAGs.

use pyo3::prelude::*;
use rustworkx_core::petgraph::prelude::*;

use qiskit_circuit::VirtualQubit;

use super::score::Gate;
use super::{VirtRealizations, single_edge};
use crate::sabre::{InteractionKind, SabreDAG, SabreNode};

/// One op in program order.
#[derive(FromPyObject)]
pub struct Op {
    /// The realization that routing falls back to.
    pub default: u32,
    /// The earlier ops that it must follow.
    pub predecessors: Vec<u32>,
    /// The gates of each realization.
    pub gates: Vec<Vec<Gate>>,
}

/// One op of a route.
#[pyclass(frozen, get_all)]
pub struct RoutedOp {
    /// The SWAPs, on physical qubits, applied just before the op.
    pub swaps: Vec<[u32; 2]>,
    /// The op's index in the input.
    pub op: usize,
    /// The realization it commits.
    pub realization: u32,
}

/// The forward and reverse [`SabreDAG`]s of `ops` on `num_qubits` virtual qubits.
///
/// Op `k` is node `k` forward and node `n - 1 - k` reversed.  An op with one realization of one
/// pair becomes `TwoQ`, unless it is unordered with the latest `TwoQ` op on one of its qubits:
/// the stock layers hold one `TwoQ` node per qubit.  Every other op becomes `MultiTwoQ`.
pub fn sabre_dags(ops: &[Op], num_qubits: u32) -> [SabreDAG; 2] {
    let mut kinds = Vec::with_capacity(ops.len());
    let mut edges = Vec::new();
    let mut last_two_q: Vec<Option<usize>> = vec![None; num_qubits as usize];
    for (k, op) in ops.iter().enumerate() {
        edges.extend(op.predecessors.iter().map(|&p| [p as usize, k]));
        let realizations = realizations(&op.gates);
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
                default_realization: op.default,
            });
        }
    }
    let last = ops.len().saturating_sub(1);
    let mut reversed: Vec<_> = edges.iter().map(|&[p, k]| [last - k, last - p]).collect();
    // The router visits successors in edge order, which forward is increasing target order.
    reversed.sort_unstable();
    let forward = sabre_dag(kinds.iter().cloned(), edges);
    [forward, sabre_dag(kinds.into_iter().rev(), reversed)]
}

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

/// Whether op `j` precedes the later op `k`.
fn precedes(ops: &[Op], j: usize, k: usize) -> bool {
    let mut seen = vec![false; k - j];
    let mut stack = vec![k];
    while let Some(n) = stack.pop() {
        for &p in &ops[n].predecessors {
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

/// The two-qubit pairs of each realization of one op.
///
/// If no realization fits on one coupling edge, every realization loses its pairs: the op commits
/// its default at once and adds no SWAP.
fn realizations(gates: &[Vec<Gate>]) -> VirtRealizations {
    let realizations: VirtRealizations = gates
        .iter()
        .map(|real| {
            real.iter()
                .filter_map(|gate| <[u32; 2]>::try_from(gate.qubits.as_slice()).ok())
                .map(|pair| pair.map(VirtualQubit::new))
                .collect()
        })
        .collect();
    if realizations
        .iter()
        .any(|real| real.is_empty() || single_edge(real).is_some())
    {
        realizations
    } else {
        realizations.iter().map(|_| Box::default()).collect()
    }
}
