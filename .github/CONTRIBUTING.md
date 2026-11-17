# Contributing

Development uses Python 3.12 and the Rust version in
[rust-toolchain.toml](../rust-toolchain.toml), which rustup installs automatically.

```sh
git clone https://github.com/Yale-QCS/prism.git
cd prism
make init   # .venv, editable install, git hooks
make test   # rebuilds the Rust extension, runs Rust and Python tests
make lint
```

Commits follow [Conventional Commits](https://www.conventionalcommits.org/), subject line only.

## Releases

Bump `version` in `pyproject.toml` and push a matching `vX.Y.Z` (or `vX.Y.ZrcN`) tag.
The [release workflow](workflows/release.yml) builds the wheels and sdist into a draft GitHub
release. Publishing the release uploads it to PyPI ([publish.yml](workflows/publish.yml)).
