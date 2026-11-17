# `prism_accelerate`

Rust extension module behind prism's routing, imported as `prism_qc._accelerate`.

- [`src/sabre/`](src/sabre/): Qiskit 2.6.0's Sabre router, vendored with a small patch
  ([README](src/sabre/README.md)).
- [`src/prism_routing/`](src/prism_routing/): prism's code. `layout.rs` is the Python entry point
  and layout search, `input.rs` builds the Sabre DAGs, `score.rs` ranks routes, `route_ext.rs`
  holds the multi-realization hooks compiled inside the vendored `route` module.

Build with `make rebuild`, or `PYO3_PYTHON=$(which python3) cargo build --locked`.

## Dependency pinning

The Qiskit git dependencies only build against the versions Qiskit itself locks. A fresh
resolution pulls newer, duplicated crates and fails inside `qiskit-circuit`. So `Cargo.lock`
starts as Qiskit's `Cargo.lock` at the same tag, and every build uses `--locked`. To move to a new
Qiskit tag:

```sh
git -C /path/to/qiskit show <tag>:Cargo.lock > Cargo.lock
# update the three git tags (and any changed requirements) in Cargo.toml
cargo build            # without --locked once: drops Qiskit-only packages, adds prism's
cargo build --locked   # must now pass unchanged
```

Afterwards every package version in `Cargo.lock` must still equal Qiskit's, with none added.
