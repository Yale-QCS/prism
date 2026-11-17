VENV := .venv
export PATH := $(HOME)/.cargo/bin:$(PATH)

UV := $(shell command -v uv 2>/dev/null)
ifdef UV
  INSTALL = uv pip install --python $(VENV)/bin/python
else
  INSTALL = $(VENV)/bin/pip install
endif

.DEFAULT_GOAL := help
.PHONY: help init rebuild test format lint clean

help:  ## List targets
	@awk 'BEGIN {FS = ":.*##"} /^[a-z]+:.*##/ {printf "  %-10s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

$(VENV)/bin/python:
	python3.12 -m venv $(VENV)

init: $(VENV)/bin/python  ## Create .venv, install editable with dev extras, install git hooks
	$(INSTALL) -e .[dev] --quiet
	@if [ "$$(git rev-parse --git-dir)" = "$$(git rev-parse --git-common-dir)" ]; then \
		$(VENV)/bin/pre-commit install; \
	else echo "Linked worktree: git hooks are installed from the main checkout"; fi

rebuild:  ## Rebuild the Rust extension
	$(INSTALL) -e . --quiet --no-deps

test: rebuild  ## Run Rust and Python tests
	cargo test --manifest-path crates/Cargo.toml --locked
	$(VENV)/bin/pytest

format:  ## Format Rust and Python in place
	cargo fmt --manifest-path crates/Cargo.toml
	$(VENV)/bin/pre-commit run --all-files

lint:  ## Check formatting, clippy, rustdoc and ruff without changing anything
	cargo fmt --manifest-path crates/Cargo.toml --check
	cargo clippy --manifest-path crates/Cargo.toml --all-targets --all-features -- -D warnings
	RUSTDOCFLAGS="-D warnings" cargo doc --manifest-path crates/Cargo.toml --no-deps
	$(VENV)/bin/ruff check
	$(VENV)/bin/ruff format --check

clean:  ## Remove build artifacts and caches
	rm -rf build dist src/*.egg-info .pytest_cache .ruff_cache crates/target src/prism_qc/_accelerate*
	find src tests -name __pycache__ -type d -prune -exec rm -rf {} +
