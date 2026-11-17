// Boundary glue for the multi-realization SABRE routing pyfunction. Builds
// a `SabreDAG` from flat precompute arrays; the result stream is returned
// as a flat `Vec<(u8, u32, u32)>` of `(kind, a, b)` event tuples.

use rustworkx_core::petgraph::prelude::*;

use qiskit_circuit::VirtualQubit;

use crate::prism_routing::ext::VirtRealizations;
use crate::sabre::dag::{InteractionKind, SabreDAG, SabreNode};

/// Event tags for the flat `events: Vec<(u8, u32, u32)>` trace stream.
///
/// - `(COMMIT, op_idx, real_idx)`: atomic commit. Python emits the entire
///   realization circuit at the current layout. Used for ops whose chosen
///   realization is fully adjacent at commit time.
/// - `(SWAP, q1, q2)`: apply a swap; updates the python-side v2p.
/// - `(SUB_GATE, op_idx, packed)`: fire one sub-gate of an op's realization
///   at the current layout. `packed = (real_idx << 16) | sub_idx`. Used for
///   sub-routed commits where intra-realization swaps interleave with the
///   sub-gates. The `(op_idx, real_idx)` of the chosen realization is implied
///   by the high bits of `packed`; multiple `SUB_GATE` events for the same
///   `op_idx` all share that `real_idx`.
pub const EVENT_KIND_COMMIT: u8 = 0;
pub const EVENT_KIND_SWAP: u8 = 1;
pub const EVENT_KIND_SUB_GATE: u8 = 2;

/// Build a `SabreDAG` directly from a marabbecca precompute. Each op becomes
/// one `SabreNode`; degenerate single-realization-single-pair ops emit
/// `InteractionKind::TwoQ` (so stock fast paths apply), the rest emit
/// `InteractionKind::MultiTwoQ`. `SabreNode.indices[0]` is a pun on op-index
/// (`NodeIndex::new(k)`); the marabbecca emission path keys on it to look up
/// the original `LoweredOp`.
pub fn sabre_dag_from_flat(
    virt_pairs: &[Vec<Vec<[u32; 2]>>],
    succ: &[Vec<u32>],
    pred_count: &[u32],
    local_default: &[u32],
) -> SabreDAG {
    let n_ops = virt_pairs.len();
    let mut dag: DiGraph<SabreNode, ()> = DiGraph::with_capacity(n_ops, n_ops);
    let nodes: Vec<NodeIndex> = (0..n_ops)
        .map(|k| {
            let virt_pairs_k = &virt_pairs[k];
            let kind = if virt_pairs_k.len() == 1 && virt_pairs_k[0].len() == 1 {
                let p = virt_pairs_k[0][0];
                InteractionKind::TwoQ([VirtualQubit::new(p[0]), VirtualQubit::new(p[1])])
            } else {
                let realizations: VirtRealizations = virt_pairs_k
                    .iter()
                    .map(|real| {
                        real.iter()
                            .map(|p| [VirtualQubit::new(p[0]), VirtualQubit::new(p[1])])
                            .collect::<Box<[_]>>()
                    })
                    .collect::<Box<[_]>>();
                InteractionKind::MultiTwoQ {
                    realizations,
                    default_realization: local_default[k],
                }
            };
            dag.add_node(SabreNode {
                indices: vec![NodeIndex::new(k)],
                kind,
            })
        })
        .collect();
    for (k, succs) in succ.iter().enumerate() {
        for &s in succs {
            dag.add_edge(nodes[k], nodes[s as usize], ());
        }
    }
    let first_layer: Vec<NodeIndex> = (0..n_ops)
        .filter(|&k| pred_count[k] == 0)
        .map(|k| nodes[k])
        .collect();
    SabreDAG {
        initial: vec![],
        dag,
        first_layer,
    }
}
