# `marabbecca_accelerate`

Rust extension module backing marabbecca's PRISM routing. Exposed to Python
as `marabbecca._accelerate`.

## Provenance

Files under [`src/sabre/`](src/sabre/) are vendored from Qiskit 2.3.1
(`crates/transpiler/src/passes/sabre/`, Apache 2.0, Copyright IBM 2022-2025).
Vendored because they are `pub(crate)` or `mod`-private upstream and cannot be
imported as a library dependency. Public supporting types (`NLayout`, qubit
newtypes, `Neighbors`, `Target`, etc.) come from the `qiskit-circuit` and
`qiskit-transpiler` git deps unmodified.

The algorithmic extension (multi-realization scoring during routing) requires
adding a variant to the closed `InteractionKind` enum and extending the
concrete `FrontLayer::score` method. Neither is reachable from outside Qiskit's
crate; forking the four affected files is the minimum-surface way to host it.

## Build

```
PYO3_PYTHON=$(which python3) cargo build
```

Maturin sets `PYO3_PYTHON` automatically when building wheels.

## Dependency pinning

Qiskit 2.3.1 predates `hashbrown 0.16`, `nalgebra 0.34`, and `ndarray 0.17`.
Its workspace deps allow those newer ranges, so a fresh resolver in any
downstream context upgrades them and duplicates types against qiskit-circuit's
pinned versions. The errors surface as `FromPyObject` and pyarray-impl
mismatches deep inside qiskit-circuit.

Direct-dep pins only constrain our crate's slot. Transitive picks by numpy,
pyo3, and indexmap stay free to pick the latest in-range. `[patch.crates-io]`
is the only knob that replaces a registry entry globally and forces one
version in every slot. The patches in `Cargo.toml` pin hashbrown, nalgebra,
and ndarray; `indexmap` is capped below 2.12 because 2.12+ hard-requires
`hashbrown ^0.16`.

If hashbrown publishes 0.15.6 or nalgebra publishes 0.33.4, the tag-pinned
patches stay frozen at the older patch level. Bump tags when needed.
