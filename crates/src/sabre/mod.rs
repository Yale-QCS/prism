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

use crate::prism_routing::{self, layout};

/// Add prism's routing functions to the extension module `m`.
pub fn register(m: &Bound<PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(prism_routing::dense_layout, m)?)?;
    m.add_function(wrap_pyfunction!(layout::prism_layout_and_routing, m)?)?;
    Ok(())
}
