//! Route ranking: the metrics of a routed program, without building its circuit.
//!
//! [`Metrics`] equals `prism.metrics.CircuitMetrics.of(placed.to_circuit())` for the placed
//! program that Python replays from a route.  Python decides which gates are free and which wires
//! each gate touches: its qubits, its clbits, and the clbits its condition reads, as
//! `QuantumCircuit.depth` counts them.  A routing SWAP is a non-free `swap` on its two qubits.

use std::cmp::Ordering;

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
///
/// It ranks finished routes only; the routing heuristic does not see it.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Objective {
    /// Fewest SWAPs, then least depth, then fewest active gates.
    Swaps,
    /// Least depth, then fewest SWAPs, then fewest active gates.
    Depth,
    /// Least `swaps + w * depth`, then as [`Objective::Swaps`].
    Weighted(f64),
}

/// `SearchBudget.objective` as Python passes it: a name or a depth weight.
#[derive(FromPyObject)]
pub enum ObjectiveArg {
    Name(String),
    DepthWeight(f64),
}

impl TryFrom<ObjectiveArg> for Objective {
    type Error = PyErr;

    /// `"swaps"`, `"depth"`, or a finite depth weight `>= 0`.
    fn try_from(arg: ObjectiveArg) -> PyResult<Self> {
        match arg {
            ObjectiveArg::Name(name) => match name.as_str() {
                "swaps" => Ok(Self::Swaps),
                "depth" => Ok(Self::Depth),
                _ => Err(PyValueError::new_err(format!("unknown objective {name:?}"))),
            },
            ObjectiveArg::DepthWeight(w) if w.is_finite() && w >= 0.0 => Ok(Self::Weighted(w)),
            ObjectiveArg::DepthWeight(w) => Err(PyValueError::new_err(format!(
                "a depth weight must be finite and >= 0, got {w}"
            ))),
        }
    }
}

impl Objective {
    /// The order of `a` and `b` under this objective; `Less` means `a` is better.
    #[allow(clippy::cast_precision_loss, reason = "gate counts are far below 2^52")]
    pub fn cmp(self, a: &Metrics, b: &Metrics) -> Ordering {
        let swaps_first = |m: &Metrics| (m.swaps, m.depth, m.active_gates);
        match self {
            Self::Swaps => swaps_first(a).cmp(&swaps_first(b)),
            Self::Depth => {
                let key = |m: &Metrics| (m.depth, m.swaps, m.active_gates);
                key(a).cmp(&key(b))
            }
            Self::Weighted(w) => {
                let cost = |m: &Metrics| m.swaps as f64 + w * m.depth as f64;
                cost(a)
                    .total_cmp(&cost(b))
                    .then_with(|| swaps_first(a).cmp(&swaps_first(b)))
            }
        }
    }

    /// The most routing SWAPs that a route may have and still rank at least level with `best`.
    /// Only [`Objective::Swaps`] bounds them: every routing SWAP is a `swap` gate.
    pub fn max_swaps(self, best: &Metrics) -> usize {
        match self {
            Self::Swaps => best.swaps,
            Self::Depth | Self::Weighted(_) => usize::MAX,
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

/// The best route under `objective`, and the first of equally good ones: `None` if there are no
/// routes.
pub fn best<R>(routes: impl IntoIterator<Item = (Metrics, R)>, objective: Objective) -> Option<R> {
    routes
        .into_iter()
        .min_by(|(a, _), (b, _)| objective.cmp(a, b))
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
    /// If a gate names a qubit out of range.
    pub fn new(ops: &'a [Op], num_qubits: u32) -> PyResult<Self> {
        let mut num_clbits = 0;
        for (k, (.., gates)) in ops.iter().enumerate() {
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
