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

`heuristic.rs`, `layer.rs` and `vec_map.rs` are verbatim. `dag.rs` and `route.rs` have
[local.patch](local.patch) applied.
New items in the patch carry a `PRISM:` comment. The patch:

- `dag.rs`: adds the `InteractionKind::MultiTwoQ` variant (a node with alternative
  realizations, each a list of qubit pairs) and its arm in `SabreDAG::only_interactions`.
- `route.rs`: declares `route_ext` (prism's code in `../prism_routing/route_ext.rs`) as a child
  module, so that it can use the private `State` and `Order`; adds a `RoutedItemKind` variant;
  keeps `MultiTwoQ` nodes in a parallel `State.multi` at every point where `TwoQ` nodes enter or
  leave `Layers`; adds their candidate swaps and scores in `choose_best_swap`; lets the release
  valve `force_enable_closest_node` also bring a multi node's single-edge realization together;
  decays the load tie-break from the main loop; and gives `swap_map_trial` a bound on its swaps,
  past which it returns `None`, so that prism can stop a final trial that cannot win.
- `route.rs`: fixes the delta update of the lookahead layers (below).

### Local bug fix: lookahead layers

One hunk of the patch is a bug fix, not a hook, and is a deliberate deviation from upstream:
`State::update_route`'s delta update of the lookahead layers (`route.rs`, the `for num_layer`
loop). Upstream (2.5 to 2.6.0rc1) loses gates from lookahead layers 1 and deeper in two ways:

- **Dropped successor.** A gate is lost from layer k when its last predecessor to be satisfied
  was routed in the same update while another of its predecessors is still in layer k-1.
  Upstream tests `prev_predecessors[node]` (the routed predecessor) where it needs
  `prev_predecessors[satisfied]` (the successor).
- **Multi-layer jump.** A node that moves up more than one layer in one update satisfies its
  successors only in the next tracker, so they stay blocked in the deeper layers for the rest of
  the route.

The fix tests the successor and carries such a node to the next level while its edges in the
next tracker are still unsatisfied. Stock routing of random CX circuits barely notices the
defect, because few gates route at once; prism's commits route many gates in cascades, so with
the defect most routing steps score a wrong lookahead layer (+8% router SWAPs at one layer, and
deeper lookahead stops helping). `Synchronize` and `ControlFlow` nodes have the same
multi-layer jump; prism emits neither, so the hunk leaves them alone.

The Rust test `lookahead_layers_match_rebuild_while_routing` (layers rebuilt from scratch at
every step, 1, 2 and 4 layers) fails without it. Drop the hunk when upstream fixes the defect,
then rerun that test.

With no `MultiTwoQ` node in the input and no lookahead, the patched router is the stock router.
With lookahead the two differ by the bug fix above.

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

To verify: run `make test`, `make lint`, and the regression gate
(`tools/gate/gate.py check`); a gate difference must be reviewed and re-recorded.

## Removal

Remove this copy when Qiskit's router accepts a caller-defined interaction kind or a cost hook
on its layers, so that prism can supply multi-realization nodes without editing the router.
