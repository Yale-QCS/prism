// This code is part of Qiskit.
//
// (C) Copyright IBM 2022
//
// This code is licensed under the Apache License, Version 2.0. You may
// obtain a copy of this license in the LICENSE.txt file in the root directory
// of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
//
// Any modifications or derivative works of this code must retain this
// copyright notice, and modified files need to carry a notice indicating
// that they have been altered from the originals.

// Marabbecca: vendored from Qiskit 2.3.1; dropped `layout` submodule;
// multi-realization extensions live in `crate::prism_routing`.
#![allow(dead_code)]

pub(crate) mod dag;
pub mod heuristic;
pub(crate) mod layer;
pub(crate) mod route;

use pyo3::prelude::*;
use pyo3::wrap_pyfunction;

pub fn sabre(m: &Bound<PyModule>) -> PyResult<()> {
    m.add_wrapped(wrap_pyfunction!(route::sabre_routing))?;
    m.add_wrapped(wrap_pyfunction!(
        crate::prism_routing::routing::prism_routing
    ))?;
    m.add_wrapped(wrap_pyfunction!(
        crate::prism_routing::layout::prism_layout_and_routing
    ))?;
    m.add_class::<route::PyRoutingTarget>()?;
    m.add_class::<heuristic::SetScaling>()?;
    m.add_class::<heuristic::Heuristic>()?;
    m.add_class::<heuristic::BasicHeuristic>()?;
    m.add_class::<heuristic::LookaheadHeuristic>()?;
    m.add_class::<heuristic::DecayHeuristic>()?;
    Ok(())
}
