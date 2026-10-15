//! Qiskit's Sabre router, vendored from `crates/transpiler/src/passes/sabre/` at Qiskit
//! 2.6.0rc1 with `local.patch` applied.  See `README.md`.
//!
//! This file is local: it replaces upstream `mod.rs`, omits upstream `layout.rs`, and registers
//! prism's Python API instead of upstream's.

mod dag;
pub mod heuristic;
mod layer;
pub mod route;
mod vec_map;

pub use dag::{InteractionKind, SabreDAG, SabreNode};

use pyo3::prelude::*;

use crate::prism_routing::layout;

/// Add the Sabre classes and prism's routing function to the extension module `m`.
pub fn register(m: &Bound<PyModule>) -> PyResult<()> {
    m.add_class::<route::PyRoutingTarget>()?;
    m.add_class::<heuristic::SetScaling>()?;
    m.add_class::<heuristic::Heuristic>()?;
    m.add_class::<heuristic::BasicHeuristic>()?;
    m.add_class::<heuristic::LookaheadHeuristic>()?;
    m.add_class::<heuristic::DecayHeuristic>()?;
    m.add_function(wrap_pyfunction!(layout::prism_layout_and_routing, m)?)?;
    Ok(())
}
