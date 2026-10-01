use pyo3::prelude::*;

mod prism_routing;
mod sabre;

#[pymodule]
fn _accelerate(m: &Bound<'_, PyModule>) -> PyResult<()> {
    sabre::sabre(m)?;
    Ok(())
}
