PYTHON_VERSION = python3.12
VENV           = .venv
RUST_BIN      ?= $(HOME)/.cargo/bin
export PATH   := $(RUST_BIN):$(PATH)

UV := $(shell command -v uv 2>/dev/null)
ifdef UV
  INSTALL = uv pip install --python $(VENV)/bin/python
else
  INSTALL = $(VENV)/bin/pip install
endif

.DEFAULT_GOAL := help
.PHONY: help init update-hooks reset-venv rebuild test format lint clean

help:  ## List targets
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*?##/ {printf "  %-24s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

$(VENV)/bin/python:
	$(PYTHON_VERSION) -m venv $(VENV)

init: $(VENV)/bin/python  ## Create the development environment and install git hooks
	$(INSTALL) -e .[dev] --quiet
	@if [ "$$(git rev-parse --git-dir)" = "$$(git rev-parse --git-common-dir)" ]; then \
		$(VENV)/bin/pre-commit install --hook-type pre-commit --hook-type commit-msg; \
	else echo "Linked worktree: git hooks are installed from the main checkout"; fi

update-hooks:  ## Bump hook revisions in .pre-commit-config.yaml
	@$(VENV)/bin/pre-commit autoupdate

reset-venv:  ## Delete the environment
	rm -rf $(VENV)

rebuild:  ## Rebuild the Rust extension
	$(INSTALL) -e . --quiet --no-deps

test: rebuild  ## Run Rust and Python tests
	cargo test --manifest-path crates/Cargo.toml --locked --all-targets
	$(VENV)/bin/pytest tests

format:  ## Format Rust and Python in place
	cargo fmt --manifest-path crates/Cargo.toml
	$(VENV)/bin/pre-commit run --all-files

lint:  ## Check formatting, clippy and ruff without changing anything
	cargo fmt --manifest-path crates/Cargo.toml --check
	cargo clippy --manifest-path crates/Cargo.toml --all-targets --all-features -- -D warnings
	$(VENV)/bin/ruff check src tests
	$(VENV)/bin/ruff format --check src tests

clean:  ## Remove build artifacts and caches
	rm -rf build dist src/*.egg-info .pytest_cache .ruff_cache crates/target \
	       src/prism/_accelerate*.so src/prism/_accelerate*.pyd
	find src tests -name __pycache__ -type d -prune -exec rm -rf {} +
