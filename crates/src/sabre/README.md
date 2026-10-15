# Vendored Qiskit Sabre

Qiskit's Sabre router, copied from Qiskit tag `2.6.0rc1`, revision
[`0a86474a`](https://github.com/Qiskit/qiskit/tree/0a86474ae6bbf43ce44e1ef2b87164044913df7a)
(Apache 2.0, Copyright IBM). The router is private to `qiskit-transpiler`, and prism adds a node
kind to its closed `InteractionKind` enum and hooks to its private routing state, so it cannot be
used as a library dependency. Public types (`NLayout`, qubit newtypes, `Neighbors`, `Target`) come
from the `qiskit-circuit`, `qiskit-transpiler` and `qiskit-util` git dependencies unmodified.

| File | Qiskit source |
|---|---|
| `dag.rs` | `crates/transpiler/src/passes/sabre/dag.rs` |
| `heuristic.rs` | `crates/transpiler/src/passes/sabre/heuristic.rs` |
| `layer.rs` | `crates/transpiler/src/passes/sabre/layer.rs` |
| `route.rs` | `crates/transpiler/src/passes/sabre/route.rs` |
| `vec_map.rs` | `crates/transpiler/src/passes/sabre/vec_map.rs` |

`layer.rs` and `vec_map.rs` are verbatim. The other files have [local.patch](local.patch) applied.
New items in the patch carry a `PRISM:` comment. The patch:

- `dag.rs`: adds the `InteractionKind::MultiTwoQ` variant (a node with alternative
  realizations, each a list of qubit pairs) and its arm in `SabreDAG::only_interactions`.
- `heuristic.rs`, `route.rs`: sets the `module` of the six Python classes to `prism._accelerate`,
  where prism exports them, so that pickling resolves to prism's classes and not Qiskit's.
- `route.rs`: declares `route_ext` (prism's code in `../prism_routing/route_ext.rs`) as a child
  module, so that it can use the private `State` and `Order`; adds two `RoutedItemKind` variants;
  counts sub-routed swaps in `Order::swap_count`; keeps `MultiTwoQ` nodes in a parallel
  `State.multi` at every point where `TwoQ` nodes enter or leave `Layers`; adds their candidate
  swaps and scores in `choose_best_swap`; and calls the multi-realization release valve and load
  decay from the main loop.

With no `MultiTwoQ` node in the input, the patched router is the stock router. The stock-parity
test checks this against the installed Qiskit wheel.

`mod.rs` is local: it replaces upstream `mod.rs`, which registers upstream's Python functions,
and omits upstream `layout.rs`, which imports the private `passes::disjoint_layout`. prism's
layout loop is `../prism_routing/layout.rs`. `lib.rs` maps the upstream `crate::` imports onto
`qiskit_transpiler` and allows, for this module only, the lints from `Cargo.toml` that upstream
code trips. Vendored files keep upstream formatting; the patched lines are `rustfmt`-formatted.

## Reproduce

From this directory, with a Qiskit Git repository that contains the revision:

```sh
qiskit=/path/to/qiskit
rev=0a86474ae6bbf43ce44e1ef2b87164044913df7a
out=$(mktemp -d)
mkdir -p "$out/src/sabre"
for f in dag heuristic layer route vec_map; do
    git -C "$qiskit" show "$rev:crates/transpiler/src/passes/sabre/$f.rs" > "$out/src/sabre/$f.rs"
done
git -C "$out" apply "$PWD/local.patch"
diff -r --exclude=mod.rs --exclude=README.md --exclude=local.patch . "$out/src/sabre"
```

## Update

Copy the five files at the new revision, apply `local.patch`, and resolve any conflicts. Keep
the patch limited to the changes listed above; new logic goes in `route_ext.rs`. Regenerate the
patch with `git diff --no-index` from the upstream files to this directory, with paths
`a/src/sabre/<file>` and `b/src/sabre/<file>`. Update the git tags in `Cargo.toml` and reseed
`Cargo.lock` from Qiskit's `Cargo.lock` at the same tag (see `crates/README.md`).

To verify: run the stock-parity test (`tests/test_sabre_stock_parity.py`) against a Qiskit wheel
of the same revision, `make test`, `make lint`, and the regression gate
(`tools/gate/gate.py check`); a gate difference must be reviewed and re-recorded.

## Removal

Remove this copy when Qiskit's router accepts a caller-defined interaction kind or a cost hook
on its layers, so that prism can supply multi-realization nodes without editing the router.
