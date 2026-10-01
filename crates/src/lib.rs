//! Rust kernels for prism: the realization-aware router and its SABRE fork.

use pyo3::prelude::*;

mod prism_routing;
mod sabre;

#[pymodule]
fn _accelerate(m: &Bound<'_, PyModule>) -> PyResult<()> {
    sabre::sabre(m)?;
    Ok(())
}
