//! Rust kernels for prism: Qiskit's Sabre router, vendored, with prism's multi-realization hooks.
use pyo3::prelude::*;

// The vendored files import these through `crate::`, as inside `qiskit-transpiler`.
pub(crate) use qiskit_transpiler::{TranspilerError, neighbors, target};

mod prism_routing;
// Upstream code: unused items and upstream style stay, since changing them would grow `local.patch`.
#[allow(
    dead_code,
    clippy::unwrap_used,
    clippy::wildcard_imports,
    clippy::items_after_statements
)]
mod sabre;

#[pymodule]
fn _accelerate(m: &Bound<'_, PyModule>) -> PyResult<()> {
    sabre::register(m)
}
