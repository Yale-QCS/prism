VENV := .venv
export PATH := $(HOME)/.cargo/bin:$(PATH)

.DEFAULT_GOAL := help
.PHONY: help init rebuild test format lint clean

help:  ## List targets
	@awk 'BEGIN {FS = ":.*##"} /^[a-z]+:.*##/ {printf "  %-10s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

$(VENV)/bin/python:
	python3.12 -m venv $(VENV)

init: $(VENV)/bin/python  ## Create .venv, install editable with dev extras, install git hooks
	$(VENV)/bin/pip install -e .[dev] --quiet
	@# A linked worktree shares the main checkout's hooks, which point at its venv.
	@if [ "$$(git rev-parse --git-dir)" = "$$(git rev-parse --git-common-dir)" ]; then $(VENV)/bin/pre-commit install; fi

rebuild:  ## Rebuild the Rust extension
	$(VENV)/bin/pip install -e . --quiet --no-deps

test: rebuild  ## Run Rust and Python tests
	cargo test --manifest-path crates/Cargo.toml --locked
	$(VENV)/bin/pytest

format:  ## Format Rust and Python in place
	cargo fmt --manifest-path crates/Cargo.toml
	$(VENV)/bin/pre-commit run --all-files

lint:  ## Check formatting, clippy and ruff
	cargo fmt --manifest-path crates/Cargo.toml --check
	cargo clippy --manifest-path crates/Cargo.toml --all-targets --all-features -- -D warnings
	$(VENV)/bin/ruff check
	$(VENV)/bin/ruff format --check

clean:  ## Remove build artifacts
	rm -rf build dist src/*.egg-info crates/target src/prism/_accelerate*
