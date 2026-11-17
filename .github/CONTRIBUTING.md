# Contributing

This branch is the research artifact for the PRISM paper. The maintained tool
is the `prism` package on `main`.

## Setup

Development uses Python 3.12 and Rust 1.97 or newer.

```sh
git clone -b revision-r3 https://github.com/Yale-QCS/prism.git
cd prism
make init
```

With `uv` installed, `make init` installs the exact environment in `uv.lock`
(Qiskit 2.4.1). For an existing checkout, run `make submodules` to fetch the paper.

## Making changes

Run `make test` and `make lint` before committing. Tests rebuild the Rust
extension. Use `make format` for formatting and `make help` for other commands.

Commit hooks enforce [Conventional Commits](https://www.conventionalcommits.org/).

## Paper

`paper/` is a separate Git repository synced with Overleaf through its `main`
branch. Commit and push paper edits inside `paper/`, then commit the new
submodule reference here. To take in Overleaf edits, run
`git submodule update --remote paper`.

## Experiments

The evaluation pipeline is in `scripts/paper/`; see its README. Raw result rows
live untracked in `artifacts/paper/` (local copies and Zenodo).
