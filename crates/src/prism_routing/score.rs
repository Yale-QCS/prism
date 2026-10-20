//! The metrics that rank routes, computed without building the routed circuit.
//!
//! [`metrics`] equals `prism.metrics.CircuitMetrics.of` of the circuit that Python replays from
//! the route.  A routing SWAP is a non-free `swap` on its two qubits.

use std::cmp::Ordering;

use pyo3::prelude::*;

use qiskit_circuit::nlayout::NLayout;
use qiskit_circuit::{PhysicalQubit, VirtualQubit};

use super::input::{Op, RoutedOp};

/// One gate: `(virtual qubits, clbits, free, is a swap)`.  `clbits` include those its condition
/// reads, as `QuantumCircuit.depth` counts them.
pub type Gate = (Vec<u32>, Vec<u32>, bool, bool);

/// `SearchBudget.objective`, validated in Python.
#[derive(Clone, Copy)]
pub enum Objective {
    /// Fewest SWAPs, then least depth, then fewest active gates.
    Swaps,
    /// Least depth, then fewest SWAPs, then fewest active gates.
    Depth,
    /// Least `swaps + w * depth`, then as [`Objective::Swaps`].
    Weighted(f64),
}

impl FromPyObject<'_, '_> for Objective {
    type Error = PyErr;

    fn extract(obj: Borrowed<'_, '_, PyAny>) -> PyResult<Self> {
        if let Ok(w) = obj.extract() {
            return Ok(Self::Weighted(w));
        }
        Ok(match &*obj.extract::<String>()? {
            "swaps" => Self::Swaps,
            "depth" => Self::Depth,
            name => unreachable!("unknown objective {name:?}"),
        })
    }
}

impl Objective {
    /// `Less` means `a` is better.
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

    /// The most routing SWAPs a route may have and still rank level with `best`.
    pub fn max_swaps(self, best: &Metrics) -> usize {
        match self {
            Self::Swaps => best.swaps,
            Self::Depth | Self::Weighted(_) => usize::MAX,
        }
    }
}

/// `prism.metrics.CircuitMetrics` of a routed program.
#[derive(Default)]
pub struct Metrics {
    /// `swap` gates, routing SWAPs included.
    pub swaps: usize,
    /// Critical-path length in non-free gates.
    pub depth: usize,
    /// Non-free gates.
    pub active_gates: usize,
    /// Gates.
    pub size: usize,
}

impl Metrics {
    /// Count one gate on `wires`.  As in `QuantumCircuit.depth`, a free gate adds no layer but
    /// still orders its wires.
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

/// The number of classical bits that the gates of `ops` use.
pub fn num_clbits(ops: &[Op]) -> usize {
    ops.iter()
        .flat_map(|(.., gates)| gates.iter().flatten())
        .flat_map(|(_, clbits, ..)| clbits)
        .map(|&c| c as usize + 1)
        .fold(0, usize::max)
}

/// The metrics of `routed`, a route of `ops` that starts from `layout`.
pub fn metrics(ops: &[Op], num_clbits: usize, routed: &[RoutedOp], layout: &NLayout) -> Metrics {
    let mut layout = layout.clone();
    let num_qubits = layout.num_qubits();
    // Physical qubits, then clbits.
    let mut depths = vec![0; num_qubits + num_clbits];
    let mut metrics = Metrics::default();
    for (swaps, k, r) in routed {
        for &[a, b] in swaps {
            let [a, b] = [a, b].map(PhysicalQubit::new);
            metrics.add(&mut depths, [a.index(), b.index()].into_iter(), false, true);
            layout.swap_physical(a, b);
        }
        let (.., gates) = &ops[*k];
        for (qubits, clbits, free, swap) in &gates[*r as usize] {
            let qubits = qubits.iter().map(|&v| layout[VirtualQubit::new(v)].index());
            let clbits = clbits.iter().map(|&c| num_qubits + c as usize);
            metrics.add(&mut depths, qubits.chain(clbits), *free, *swap);
        }
    }
    metrics.depth = depths.into_iter().max().unwrap_or_default();
    metrics
}
