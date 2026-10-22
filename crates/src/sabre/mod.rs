//! Qiskit's Sabre router, vendored from `crates/transpiler/src/passes/sabre/` at Qiskit
//! 2.6.0 with `local.patch` applied.  See `README.md`.
//!
//! This file is local: it replaces upstream `mod.rs` and omits upstream `layout.rs` and the
//! Python API.

mod dag;
pub mod heuristic;
mod layer;
pub mod route;
mod vec_map;

pub use dag::{InteractionKind, SabreDAG, SabreNode};
