# Contributing

## Setup

Development uses Python 3.12 and Rust 1.97 or newer.

```sh
git clone https://github.com/evmckinney9/prism.git
cd prism
make init
```

`.devcontainer/` provides the same toolchain in a container.

## Making changes

Run `make test` and `make lint` before submitting changes. Tests rebuild the
Rust extension. Use `make format` for formatting and `make help` for other commands.

Test behavior through the public API, allowing different valid realizations
and routes.

Commit hooks enforce [Conventional Commits](https://www.conventionalcommits.org/).

The HPCA paper artifact, with its baselines and evaluation pipeline, is on the
`hpca-r1` and `hpca-r2` branches, not here.

## Documentation

Edit the [user guide](../docs/index.rst) and preview it with `make docs-serve`.
Run `make docs` to check it.

## Releases

Push a stable `vX.Y.Z` tag matching the version in `pyproject.toml`.
The [release workflow](../.github/workflows/release.yml) builds and tests distributions.
Review the draft GitHub release and its distributions before publishing;
publication triggers the [PyPI upload](../.github/workflows/publish.yml).
