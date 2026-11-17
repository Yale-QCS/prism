PYTHON_VERSION = python3.12
VENV           = .venv
RUST_BIN      ?= $(HOME)/.cargo/bin
export PATH   := $(RUST_BIN):$(PATH)

# The artifact environment is pinned by uv.lock; pip installs float.
UV := $(shell command -v uv 2>/dev/null)
ifdef UV
  INSTALL = uv pip install --python $(VENV)/bin/python
else
  INSTALL = $(VENV)/bin/pip install
endif

.DEFAULT_GOAL := help
.PHONY: help init submodules update-hooks reset-venv rebuild test validate-sim figures quick quick-scale format lint clean

help:  ## List targets
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*?##/ {printf "  %-24s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

$(VENV)/bin/python:
	$(PYTHON_VERSION) -m venv $(VENV)

submodules:  ## Fetch the paper commit pinned by this checkout
	git submodule update --init --recursive

init: $(VENV)/bin/python  ## Create the development environment (locked by uv.lock under uv) and install git hooks
ifdef UV
	uv sync --frozen --all-extras
else
	@$(VENV)/bin/pip install --upgrade pip --quiet
	$(INSTALL) -e .[dev] --quiet
endif
	@$(VENV)/bin/pre-commit install --hook-type pre-commit --hook-type commit-msg

update-hooks:  ## Bump hook revisions in .pre-commit-config.yaml
	@$(VENV)/bin/pre-commit autoupdate

reset-venv:  ## Delete the environment
	rm -rf $(VENV)

rebuild:  ## Rebuild the Rust extension
	$(INSTALL) -e . --quiet --no-deps

test: rebuild validate-sim  ## Run Rust and Python tests and the dual-rail simulator checks
	cargo test --manifest-path crates/Cargo.toml --locked --all-targets
	$(VENV)/bin/pytest tests

validate-sim: rebuild  ## Check the dual-rail simulator against Statevector, a full rail density matrix and Eq. 1 (about 20 s)
	$(VENV)/bin/python research/rebuttal/wallclock/validate.py

figures: rebuild  ## Regenerate the paper's data figures in paper/figures
	$(VENV)/bin/jupyter-execute src/notebooks/paper/03_completions.ipynb
	$(VENV)/bin/python scripts/paper/emit_strategy_ladder.py
	for e in core scaling device; do $(VENV)/bin/python scripts/paper/export_$$e.py || exit 1; done

quick: rebuild  ## Quick profile (about 9 min): core, logical and breadth into artifacts/paper/quick, core and breadth exports into quick_export
	for c in core logical breadth; do $(VENV)/bin/python scripts/paper/run_fairness.py --config configs/paper/$$c.toml --quick --workers 12 || exit 1; done
	for e in core breadth; do $(VENV)/bin/python scripts/paper/export_$$e.py --quick || exit 1; done

quick-scale: rebuild  ## Quick scale profile (about 9 min): scale at one seed, widths 8-16, with the scaling and device exports
	$(VENV)/bin/python scripts/paper/run_fairness.py --config configs/paper/scale.toml --quick --workers 12
	for e in scaling device; do $(VENV)/bin/python scripts/paper/export_$$e.py --quick || exit 1; done

format:  ## Format Rust and Python in place
	cargo fmt --manifest-path crates/Cargo.toml
	$(VENV)/bin/pre-commit run --all-files

lint:  ## Check formatting, clippy, and ruff without changing anything
	cargo fmt --manifest-path crates/Cargo.toml --check
	cargo clippy --manifest-path crates/Cargo.toml --all-targets --all-features -- -D warnings
	$(VENV)/bin/ruff check src
	$(VENV)/bin/ruff check tests
	$(VENV)/bin/ruff check scripts
	$(VENV)/bin/ruff format --check src tests scripts

clean:  ## Remove build artifacts and caches
	rm -rf build dist src/*.egg-info .pytest_cache .ruff_cache crates/target \
	       src/marabbecca/_accelerate*.so src/marabbecca/_accelerate*.pyd
	find src tests -name __pycache__ -type d -prune -exec rm -rf {} +
