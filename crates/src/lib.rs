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
    m.add_function(wrap_pyfunction!(prism_routing::dense_layout, m)?)?;
    m.add_function(wrap_pyfunction!(
        prism_routing::layout::prism_layout_and_routing,
        m
    )?)?;
    m.add_class::<prism_routing::input::RoutedOp>()?;
    Ok(())
}
