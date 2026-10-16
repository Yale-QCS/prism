//! Route ranking: the metrics of a routed program, without building its circuit.
//!
//! [`Metrics`] equals `prism.metrics.CircuitMetrics.of(placed.to_circuit())` for the placed
//! program that Python replays from a route.  Python decides which gates are free and which wires
//! each gate touches: its qubits, its clbits, and the clbits its condition reads, as
//! `QuantumCircuit.depth` counts them.  A routing SWAP is a non-free `swap` on its two qubits.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use qiskit_circuit::nlayout::NLayout;
use qiskit_circuit::{PhysicalQubit, VirtualQubit};

use super::input::{Op, RoutedOp};

/// One gate of a realization: `(qubits, clbits, free, swap)`.
///
/// `qubits` are virtual qubits and `clbits` index the program's classical bits.  `free` is
/// `prism.metrics.is_free` of the gate, and `swap` says that the gate is a `swap`.
pub type Gate = (Vec<u32>, Vec<u32>, bool, bool);

/// The route-selection objective, `SearchBudget.objective` in Python.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Objective {
    /// Fewest SWAPs, then least depth, then fewest active gates.
    Swaps,
    /// Least depth, then fewest active gates, then smallest size.
    Depth,
}

impl TryFrom<&str> for Objective {
    type Error = PyErr;

    /// The objective named `"swaps"` or `"depth"`.
    fn try_from(name: &str) -> PyResult<Self> {
        match name {
            "swaps" => Ok(Self::Swaps),
            "depth" => Ok(Self::Depth),
            _ => Err(PyValueError::new_err(format!("unknown objective {name:?}"))),
        }
    }
}

/// The metrics of a routed program, as `prism.metrics.CircuitMetrics` defines them.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Metrics {
    /// `swap` gates, routing SWAPs included.
    pub swaps: usize,
    /// Critical-path length counted in non-free gates.
    pub depth: usize,
    /// Non-free gates.
    pub active_gates: usize,
    /// Gates.
    pub size: usize,
}

impl Metrics {
    /// The score of these metrics under `objective`; lower is better.
    pub fn score(&self, objective: Objective) -> [usize; 3] {
        match objective {
            Objective::Swaps => [self.swaps, self.depth, self.active_gates],
            Objective::Depth => [self.depth, self.active_gates, self.size],
        }
    }

    /// Count one gate on `wires`, whose depths are in `depths`.
    ///
    /// As in `QuantumCircuit.depth`, every wire of the gate moves to the deepest of them, plus one
    /// unless the gate is free: a free gate adds no layer but still orders its wires.
    fn add(
        &mut self,
        depths: &mut [usize],
        wires: impl Iterator<Item = usize> + Clone,
        free: bool,
        swap: bool,
    ) {
        let depth = wires.clone().map(|w| depths[w]).max().unwrap_or_default() + usize::from(!free);
        for w in wires {
            depths[w] = depth;
        }
        self.swaps += usize::from(swap);
        self.active_gates += usize::from(!free);
        self.size += 1;
    }
}

/// The route of the lowest score under `objective`, and the first of equal scores: `None` if
/// there are no routes.
pub fn best<R>(routes: impl IntoIterator<Item = (Metrics, R)>, objective: Objective) -> Option<R> {
    routes
        .into_iter()
        .min_by_key(|(metrics, _)| metrics.score(objective))
        .map(|(_, route)| route)
}

/// The gates of every realization of a routing problem, checked against it.
pub struct Program<'a> {
    ops: &'a [Op],
    num_clbits: usize,
}

impl<'a> Program<'a> {
    /// The gates of `ops` on `num_qubits` virtual qubits.
    ///
    /// # Errors
    ///
    /// If an op does not list the gates of each of its realizations, or a gate names a qubit out
    /// of range.
    pub fn new(ops: &'a [Op], num_qubits: u32) -> PyResult<Self> {
        let mut num_clbits = 0;
        for (k, (reals, _, _, gates)) in ops.iter().enumerate() {
            if gates.len() != reals.len() {
                return Err(PyValueError::new_err(format!(
                    "op {k}: gates for {} realizations, but {} realizations",
                    gates.len(),
                    reals.len()
                )));
            }
            for (qubits, clbits, ..) in gates.iter().flatten() {
                if let Some(q) = qubits.iter().find(|&&q| q >= num_qubits) {
                    return Err(PyValueError::new_err(format!(
                        "op {k}: gate on qubit {q} of {num_qubits}"
                    )));
                }
                num_clbits = clbits
                    .iter()
                    .map(|&c| c as usize + 1)
                    .fold(num_clbits, usize::max);
            }
        }
        Ok(Self { ops, num_clbits })
    }

    /// The metrics of `routed`, a route of this program that starts from `layout`.
    pub fn metrics(&self, routed: &[RoutedOp], layout: &NLayout) -> Metrics {
        let mut layout = layout.clone();
        let num_qubits = layout.num_qubits();
        // Physical qubits, then clbits.
        let mut depths = vec![0; num_qubits + self.num_clbits];
        let mut metrics = Metrics::default();
        for (swaps, k, r) in routed {
            for &[a, b] in swaps {
                let [a, b] = [a, b].map(PhysicalQubit::new);
                metrics.add(&mut depths, [a.index(), b.index()].into_iter(), false, true);
                layout.swap_physical(a, b);
            }
            let (.., gates) = &self.ops[*k];
            for (qubits, clbits, free, swap) in &gates[*r as usize] {
                let qubits = qubits.iter().map(|&v| layout[VirtualQubit::new(v)].index());
                let clbits = clbits.iter().map(|&c| num_qubits + c as usize);
                metrics.add(&mut depths, qubits.chain(clbits), *free, *swap);
            }
        }
        metrics.depth = depths.into_iter().max().unwrap_or_default();
        metrics
    }
}

#[cfg(test)]
mod tests {
    use qiskit_circuit::nlayout::NLayout;

    use super::{Gate, Metrics, Op, Program, RoutedOp};

    /// A one-realization op of `gates`, for scoring only: it has no pairs.
    fn op(gates: Vec<Gate>) -> Op {
        (vec![vec![]], 0, vec![], vec![gates])
    }

    fn gate(qubits: &[u32], clbits: &[u32], free: bool) -> Gate {
        (qubits.to_vec(), clbits.to_vec(), free, false)
    }

    /// The metrics of `routed` on three qubits from the trivial layout.
    fn metrics(ops: &[Op], routed: &[RoutedOp]) -> Metrics {
        let program = Program::new(ops, 3).expect("valid program");
        program.metrics(routed, &NLayout::generate_trivial_layout(3))
    }

    #[test]
    fn free_gates_add_no_layer_but_order_their_wires() {
        // A gate on 0, a free gate on 0 and 1, a gate on 1, a free gate on 2: the free gate carries
        // qubit 0's depth to qubit 1, and neither free gate adds a layer.
        let ops = [
            op(vec![gate(&[0], &[], false)]),
            op(vec![gate(&[0, 1], &[], true)]),
            op(vec![gate(&[1], &[], false)]),
            op(vec![gate(&[2], &[], true)]),
        ];
        let routed = [
            (vec![], 0, 0),
            (vec![], 1, 0),
            (vec![], 2, 0),
            (vec![], 3, 0),
        ];
        let m = metrics(&ops, &routed);
        assert_eq!((m.depth, m.active_gates, m.size), (2, 2, 4));
    }

    #[test]
    fn clbits_are_wires() {
        // measure(0) -> c0; a gate on qubit 1 that reads c0: depth 2, not 1.
        let ops = [
            op(vec![gate(&[0], &[0], false)]),
            op(vec![gate(&[1], &[0], false)]),
        ];
        let m = metrics(&ops, &[(vec![], 0, 0), (vec![], 1, 0)]);
        assert_eq!(m.depth, 2);
    }

    #[test]
    fn routing_swaps_move_virtual_qubits() {
        // swap(0, 1) moves virtual 0 to physical 1, five gates deepen it there, and swap(1, 2)
        // carries that depth to physical 2, where virtual 0 then is.
        let ops = [
            op(vec![gate(&[0], &[], false); 5]),
            op(vec![gate(&[0], &[], false)]),
        ];
        let routed = [(vec![[0, 1]], 0, 0), (vec![[1, 2]], 1, 0)];
        let m = metrics(&ops, &routed);
        let expected = Metrics {
            swaps: 2,
            depth: 8,
            active_gates: 8,
            size: 8,
        };
        assert_eq!(m, expected);
    }
}
