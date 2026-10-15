# `prism_accelerate`

Rust extension module backing prism's routing, exposed to Python as `prism._accelerate`.

## Layout

- [`src/sabre/`](src/sabre/): Qiskit's Sabre router, vendored from Qiskit 2.6.0rc1 with a small
  local patch. Its [README](src/sabre/README.md) lists the upstream files, the patch, and how to
  reproduce, update and remove the copy.
- [`src/prism_routing/`](src/prism_routing/): prism's code. `route_ext.rs` holds the
  multi-realization routing hooks and is compiled inside the vendored `route` module; `input.rs`
  converts Python's flat routing problem; `layout.rs` is the Python entry point, prism's layout
  search (the outer loop that upstream `SabreLayout` runs); `mod.rs` builds the routing target
  and its dense starting layout.

## Build

```
PYO3_PYTHON=$(which python3) cargo build --locked
```

setuptools-rust sets `PYO3_PYTHON` to the building interpreter and passes `--locked`.

## Dependency pinning

The `qiskit-circuit`, `qiskit-transpiler` and `qiskit-util` git dependencies must resolve their
own dependencies to the versions Qiskit builds with. A fresh resolution does not: it takes newer
releases (for example a second `hashbrown` through pyo3, or `ndarray`/`nalgebra` through numpy)
that duplicate types against qiskit-circuit's, and the build fails deep inside qiskit-circuit.

So `Cargo.lock` is seeded from Qiskit's own `Cargo.lock` at the same tag, and every build uses
`--locked`. `Cargo.toml` states the same version requirements as Qiskit's
`[workspace.dependencies]` for the crates prism uses directly. To move to a new Qiskit tag:

```sh
git -C /path/to/qiskit show <tag>:Cargo.lock > Cargo.lock
# update the three git tags (and any changed requirements) in Cargo.toml
cargo build            # without --locked once: drops Qiskit-only packages, adds prism's
cargo build --locked   # must now pass unchanged
```

After the first build, every package version in `Cargo.lock` must still equal Qiskit's; only
packages Qiskit does not use (today `inventory`, for pyo3's `multiple-pymethods`) may be added.
