//! Rust kernels for prism: Qiskit's Sabre router, vendored, with prism's multi-realization hooks.
use pyo3::prelude::*;

// The vendored files import these through `crate::`, as inside `qiskit-transpiler`.
pub(crate) use qiskit_transpiler::{TranspilerError, neighbors, target};

mod prism_routing;
// Vendored upstream code keeps upstream's style; these are the lints from `Cargo.toml` it trips.
// `dead_code` covers the upstream items prism never calls (control-flow nodes, conversion from
// a `DAGCircuit`, rebuilding a routed `DAGCircuit`, and upstream's Python entry point); deleting
// them would grow `local.patch`.  `route_ext.rs`, prism code compiled inside `sabre::route`,
// restores every lint.
#[allow(
    dead_code,
    clippy::cast_possible_truncation,
    clippy::cast_precision_loss,
    clippy::doc_markdown,
    clippy::items_after_statements,
    clippy::too_many_lines,
    clippy::unwrap_used,
    clippy::wildcard_imports
)]
mod sabre;

#[pymodule]
fn _accelerate(m: &Bound<'_, PyModule>) -> PyResult<()> {
    sabre::register(m)
}
