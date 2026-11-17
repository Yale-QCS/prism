"""E06 tests: summarize on synthetic fixtures.

Fixture setup: 2 cells x 2 seeds x 2 strategies (greedy, prism).
  Cell A = (circ_a, 4, grid)
    seed 0: greedy=6, prism=4  -> diff=-2, ratio=4/6
    seed 1: greedy=8, prism=4  -> diff=-4, ratio=4/8
    cell means: greedy=7, prism=4  -> diff=-3, ratio=4/7
  Cell B = (circ_b, 4, grid)
    seed 0: greedy=4, prism=2  -> diff=-2, ratio=0.5
    seed 1: greedy=4, prism=4  -> diff=0, ratio=1.0
    cell means: greedy=4, prism=3  -> diff=-1, ratio=3/4

Pooled relative change (on cell means):
  sum_treatment = 4 + 3 = 7
  sum_baseline  = 7 + 4 = 11
  pooled = (7 - 11) / 11 = -4/11 ≈ -0.36364

Win/tie/loss: A -> win (4<7), B -> win (3<4) -> 2W / 0T / 0L

Median per-cell diff (sorted: [-3,-1]): -2.0
Median per-cell ratio (sorted: [4/7, 3/4]): (4/7 + 3/4)/2 = (16+21)/56 = 37/56 ≈ 0.66071
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path setup so we can import the scripts without install
# ---------------------------------------------------------------------------

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts/paper"
sys.path.insert(0, str(SCRIPTS_DIR))

from summarize import (  # noqa: E402
    BOOTSTRAP_SEED,
    N_BOOTSTRAP,
    _build_cell_structure,
    _compute_point_estimates,
    _group_complete_pairs,
    _macro_prefix,
    bootstrap_ci,
    summarize,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_ENV = {
    "schema_version": 1,
    "experiment_id": "test_exp",
    "started_at_utc": "2026-01-01T00:00:00+00:00",
    "python_version": "3.12.3",
    "qiskit_version": "2.4.1",
    "numpy_version": "2.4.6",
    "mqt_bench_version": "2.2.2",
    "rustc_version": "1.89.0",
    "host_os": "Linux",
    "host_cpu": "x86_64",
    "objective": "swaps",
}


def _make_run_id(
    experiment_id: str,
    circuit_name: str,
    requested_n: int,
    topology_name: str,
    strategy: str,
    outer_seed: int,
) -> str:
    payload = json.dumps(
        {
            "experiment_id": experiment_id,
            "circuit_name": circuit_name,
            "objective": "swaps",
            "outer_seed": outer_seed,
            "requested_n": requested_n,
            "strategy": strategy,
            "topology_name": topology_name,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _row(
    circuit_name,
    requested_n,
    topology_name,
    strategy,
    outer_seed,
    router_inserted_swaps,
    success=True,
    error_type=None,
    experiment_id="test_exp",
) -> dict:
    rid = _make_run_id(
        experiment_id, circuit_name, requested_n, topology_name, strategy, outer_seed
    )
    base = {
        **_ENV,
        "experiment_id": experiment_id,
        "run_id": rid,
        "circuit_name": circuit_name,
        "requested_n": requested_n,
        "topology_name": topology_name,
        "strategy": strategy,
        "outer_seed": outer_seed,
        "success": success,
        "error_type": error_type,
        "error_message": None,
    }
    if success:
        base.update(
            {
                "actual_n_logical": requested_n,
                "n_physical_rails": requested_n * 2,
                "circuit_size": 20,
                "final_swap_instructions": router_inserted_swaps,
                "active_gate_count": 30,
                "physical_depth": 10,
                "compile_time_s": 0.5,
                "router_inserted_swaps": router_inserted_swaps,
                "semantic_swap_instructions": router_inserted_swaps,
                "duration_ns": 1000.0,
            }
        )
    return base


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def _two_cell_rows(experiment_id="test_exp") -> list[dict]:
    return [
        _row("circ_a", 4, "grid", "greedy", 0, 6, experiment_id=experiment_id),
        _row("circ_a", 4, "grid", "prism", 0, 4, experiment_id=experiment_id),
        _row("circ_a", 4, "grid", "greedy", 1, 8, experiment_id=experiment_id),
        _row("circ_a", 4, "grid", "prism", 1, 4, experiment_id=experiment_id),
        _row("circ_b", 4, "grid", "greedy", 0, 4, experiment_id=experiment_id),
        _row("circ_b", 4, "grid", "prism", 0, 2, experiment_id=experiment_id),
        _row("circ_b", 4, "grid", "greedy", 1, 4, experiment_id=experiment_id),
        _row("circ_b", 4, "grid", "prism", 1, 4, experiment_id=experiment_id),
    ]


# ---------------------------------------------------------------------------
# Summarize: point-estimate tests
# ---------------------------------------------------------------------------


class TestPointEstimates:
    def _get_cells(self):
        rows = _two_cell_rows()
        pairs, excluded = _group_complete_pairs(
            rows, "greedy", "prism", "router_inserted_swaps"
        )
        assert excluded == []
        return _build_cell_structure(pairs)

    def test_n_cells(self):
        cells = self._get_cells()
        assert len(cells) == 2

    def test_win_tie_loss(self):
        cells = self._get_cells()
        est = _compute_point_estimates(cells)
        wins, ties, losses = est["win_tie_loss"]
        assert wins == 2
        assert ties == 0
        assert losses == 0

    def test_pooled_relative_change(self):
        cells = self._get_cells()
        est = _compute_point_estimates(cells)
        # sum_treatment=7, sum_baseline=11, pooled=-4/11
        expected = -4 / 11
        assert abs(est["pooled_relative_change"] - expected) < 1e-10

    def test_median_per_cell_diff(self):
        cells = self._get_cells()
        est = _compute_point_estimates(cells)
        # sorted diffs: [-3, -1], median = -2.0
        assert abs(est["median_per_cell_difference"] - (-2.0)) < 1e-10

    def test_median_per_cell_ratio(self):
        cells = self._get_cells()
        est = _compute_point_estimates(cells)
        # ratios: [4/7, 3/4] = [0.5714..., 0.75], median = (4/7 + 3/4)/2 = 37/56
        expected = (4 / 7 + 3 / 4) / 2
        assert abs(est["median_per_cell_ratio"] - expected) < 1e-10

    def test_geo_mean_ratio(self):
        cells = self._get_cells()
        est = _compute_point_estimates(cells)
        expected = math.sqrt((4 / 7) * (3 / 4))
        assert abs(est["geo_mean_ratio"] - expected) < 1e-10

    def test_pooled_totals(self):
        cells = self._get_cells()
        est = _compute_point_estimates(cells)
        assert abs(est["pooled_baseline_total"] - 11.0) < 1e-10
        assert abs(est["pooled_treatment_total"] - 7.0) < 1e-10


# ---------------------------------------------------------------------------
# Summarize: zero handling
# ---------------------------------------------------------------------------


class TestZeroHandling:
    def _rows_with_zero_cell(self):
        rows = _two_cell_rows()
        # Add a cell with baseline=0, treatment=0
        rows += [
            _row("circ_z", 4, "grid", "greedy", 0, 0),
            _row("circ_z", 4, "grid", "prism", 0, 0),
        ]
        return rows

    def test_zero_cell_excluded_from_ratio(self):
        rows = self._rows_with_zero_cell()
        pairs, _ = _group_complete_pairs(
            rows, "greedy", "prism", "router_inserted_swaps"
        )
        cells = _build_cell_structure(pairs)
        est = _compute_point_estimates(cells)
        assert est["n_cells_excluded_from_ratio"] == 1
        assert est["n_cells"] == 3

    def test_zero_cell_included_in_difference(self):
        rows = self._rows_with_zero_cell()
        pairs, _ = _group_complete_pairs(
            rows, "greedy", "prism", "router_inserted_swaps"
        )
        cells = _build_cell_structure(pairs)
        est = _compute_point_estimates(cells)
        # zero cell diff = 0; median of [-3, -1, 0] = -1.0
        assert abs(est["median_per_cell_difference"] - (-1.0)) < 1e-10

    def test_zero_cell_disclosed_in_excluded_list(self):
        rows = self._rows_with_zero_cell()
        pairs, _ = _group_complete_pairs(
            rows, "greedy", "prism", "router_inserted_swaps"
        )
        cells = _build_cell_structure(pairs)
        est = _compute_point_estimates(cells)
        excluded = est["cells_excluded_from_ratio"]
        assert any(e["circuit_name"] == "circ_z" for e in excluded)


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


class TestBootstrap:
    def _cells(self):
        rows = _two_cell_rows()
        pairs, _ = _group_complete_pairs(
            rows, "greedy", "prism", "router_inserted_swaps"
        )
        return _build_cell_structure(pairs)

    def test_determinism(self):
        cells = self._cells()
        ci1 = bootstrap_ci(cells, n_draws=N_BOOTSTRAP, seed=BOOTSTRAP_SEED)
        ci2 = bootstrap_ci(cells, n_draws=N_BOOTSTRAP, seed=BOOTSTRAP_SEED)
        assert ci1 == ci2

    def test_different_seed_different_result(self):
        cells = self._cells()
        ci1 = bootstrap_ci(cells, n_draws=500, seed=1)
        ci2 = bootstrap_ci(cells, n_draws=500, seed=2)
        # Very unlikely to be identical with different seeds
        assert ci1 != ci2

    def test_ci_contains_point_estimate(self):
        cells = self._cells()
        est = _compute_point_estimates(cells)
        ci = bootstrap_ci(cells, n_draws=N_BOOTSTRAP, seed=BOOTSTRAP_SEED)
        pooled = est["pooled_relative_change"]
        assert ci["pooled_ci_low"] <= pooled <= ci["pooled_ci_high"]

    def test_ci_keys_present(self):
        cells = self._cells()
        ci = bootstrap_ci(cells, n_draws=100, seed=42)
        for key in (
            "bootstrap_seed",
            "n_bootstrap",
            "pooled_ci_low",
            "pooled_ci_high",
            "median_ci_low",
            "median_ci_high",
        ):
            assert key in ci


# ---------------------------------------------------------------------------
# Mutation / completeness detection
# ---------------------------------------------------------------------------


class TestMutationDetection:
    def test_deleted_row_excluded_from_summarize(self, tmp_path):
        rows = _two_cell_rows()
        rows = [
            r
            for r in rows
            if not (
                r["circuit_name"] == "circ_a"
                and r["outer_seed"] == 0
                and r["strategy"] == "prism"
            )
        ]
        pairs, excluded = _group_complete_pairs(
            rows, "greedy", "prism", "router_inserted_swaps"
        )
        # circ_a/seed=0 should be in excluded
        assert any(
            e["circuit_name"] == "circ_a" and e["outer_seed"] == 0 for e in excluded
        )
        # circ_a/seed=1 and circ_b pairs should still be complete
        complete_keys = {(p["cell_key"], p["outer_seed"]) for p in pairs}
        assert (("circ_a", 4, "grid"), 1) in complete_keys
        assert (("circ_b", 4, "grid"), 0) in complete_keys


# ---------------------------------------------------------------------------
# Full summarize pipeline (integration)
# ---------------------------------------------------------------------------


class TestSummarizePipeline:
    def _run(self, tmp_path, rows=None):
        if rows is None:
            rows = _two_cell_rows()
        p = tmp_path / "test_exp.jsonl"
        _write_jsonl(p, rows)
        out_dir = tmp_path / "summaries"
        latex_dir = tmp_path / "latex"
        return summarize(
            p, "greedy", "prism", "router_inserted_swaps", out_dir, latex_dir=latex_dir
        )

    def test_output_json_exists(self, tmp_path):
        self._run(tmp_path)
        expected = (
            tmp_path
            / "summaries"
            / "test_exp_prism_vs_greedy_router_inserted_swaps.json"
        )
        assert expected.exists()

    def test_output_json_schema(self, tmp_path):
        s = self._run(tmp_path)
        for key in (
            "experiment_id",
            "baseline",
            "treatment",
            "metric",
            "n_cells",
            "win_tie_loss",
            "pooled_relative_change",
            "pooled_ci_low",
            "pooled_ci_high",
            "filter",
        ):
            assert key in s, f"missing key: {key}"

    def test_filter_denominator_recorded(self, tmp_path):
        s = self._run(tmp_path)
        filt = s["filter"]
        assert filt["n_total_rows"] == 8
        assert filt["n_complete_pairs"] == 4  # 2 cells x 2 seeds

    def test_latex_macros_written(self, tmp_path):
        s = self._run(tmp_path)
        latex_path = tmp_path / "latex" / "generated_results.tex"
        assert latex_path.exists()
        content = latex_path.read_text()
        assert r"\TestExpSwapWins" in content
        wins, ties, losses = s["win_tie_loss"]
        assert wins == 2

    def test_idempotent_rerun(self, tmp_path):
        p = tmp_path / "test_exp.jsonl"
        _write_jsonl(p, _two_cell_rows())
        out_dir = tmp_path / "summaries"
        latex_dir = tmp_path / "latex"
        s1 = summarize(
            p, "greedy", "prism", "router_inserted_swaps", out_dir, latex_dir=latex_dir
        )
        s2 = summarize(
            p, "greedy", "prism", "router_inserted_swaps", out_dir, latex_dir=latex_dir
        )
        assert s1["pooled_relative_change"] == s2["pooled_relative_change"]
        assert s1["win_tie_loss"] == s2["win_tie_loss"]
        # Idempotency: only one BEGIN block in the tex file
        content = (latex_dir / "generated_results.tex").read_text()
        assert content.count("% BEGIN TestExpSwap") == 1


# ---------------------------------------------------------------------------
# Macro naming
# ---------------------------------------------------------------------------


class TestMacroNaming:
    def test_core_n8_swap(self):
        assert (
            _macro_prefix("core_n8", "router_inserted_swaps", "prism", "greedy")
            == "CoreSwap"
        )

    def test_pilot_qft4_depth(self):
        assert (
            _macro_prefix("pilot_qft4", "physical_depth", "prism", "greedy")
            == "PilotQft4Depth"
        )

    def test_fallback_camelcase(self):
        result = _macro_prefix("my_exp", "some_custom_metric", "prism", "greedy")
        assert result == "MyExpSomeCustomMetric"

    def test_noncanonical_pair_gets_distinct_prefix(self):
        assert (
            _macro_prefix("core_n8", "router_inserted_swaps", "logical", "greedy")
            == "CoreLogicalSwap"
        )
        assert (
            _macro_prefix("core_n8", "router_inserted_swaps", "prism", "trivial")
            == "CorePrismVsTrivialSwap"
        )


class TestV3MedianPolicy:
    """Round-3 prespec median: zero-treatment cells contribute -100%."""

    @staticmethod
    def _cells(pairs):
        return [
            {
                "circuit_name": f"c{i}",
                "requested_n": 8,
                "topology_name": "grid",
                "seeds": [
                    {
                        "outer_seed": 42,
                        "baseline_val": b,
                        "treatment_val": t,
                        "baseline_run_id": "rb",
                        "treatment_run_id": "rt",
                    }
                ],
            }
            for i, (b, t) in enumerate(pairs)
        ]

    def test_zero_treatment_contributes_minus_100(self):
        cells = self._cells([(10, 0), (10, 5), (10, 8)])
        est = _compute_point_estimates(cells, median_zero_treatment=True)
        # rc values: -1.0, -0.5, -0.2 -> median -0.5
        assert est["median_per_cell_relative_change"] == -0.5
        assert est["median_rc_eligible_cells"] == 3
        assert est["median_rc_excluded_zero_baseline"] == 0
        assert est["geo_excluded_zero_treatment"] == 1
        # Legacy ratio-based median silently drops the zero-treatment cell.
        assert est["median_per_cell_ratio"] == pytest.approx(0.65)

    def test_zero_baseline_excluded_from_median(self):
        cells = self._cells([(0, 3), (10, 0)])
        est = _compute_point_estimates(cells, median_zero_treatment=True)
        assert est["median_per_cell_relative_change"] == -1.0
        assert est["median_rc_excluded_zero_baseline"] == 1

    def test_legacy_output_unchanged_without_flag(self):
        cells = self._cells([(10, 0), (10, 5)])
        est = _compute_point_estimates(cells)
        assert "median_per_cell_relative_change" not in est

    def test_v3_macro_uses_prespec_median(self):
        from summarize import _latex_block

        cells = self._cells([(10, 0), (10, 5), (10, 8)])
        est = _compute_point_estimates(cells, median_zero_treatment=True)
        ci = {
            "pooled_ci_low": -0.6,
            "pooled_ci_high": -0.4,
            "bootstrap_seed": 0,
            "n_bootstrap": 10,
        }
        block = _latex_block(
            "FairTestSwap",
            "mechanism_v3_n8",
            "b",
            "t",
            "router_inserted_swaps",
            est,
            ci,
        )
        line = next(l for l in block.splitlines() if "MedianChange" in l)
        assert "-50.0" in line, line  # prespec median, not ratio-based -35%
