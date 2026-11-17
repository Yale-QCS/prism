"""E06: per-cell seed aggregation, hierarchical bootstrap, and LaTeX macro generation.

Usage:
  .venv/bin/python scripts/paper/summarize.py artifacts/paper/raw/pilot_qft4.jsonl \\
      --baseline greedy --treatment prism \\
      [--metric router_inserted_swaps] \\
      [--out-dir artifacts/paper/summaries]

Outputs:
  artifacts/paper/summaries/<experiment_id>_<treatment>_vs_<baseline>_<metric>.json
  artifacts/paper/latex/generated_results.tex  (section for this run, idempotent)

Naming rule for LaTeX macros
  experiment_id prefix: strip trailing _nNUM suffix, camelcase remaining parts.
    core_n8 -> Core  |  pilot_qft4 -> PilotQft4
  metric prefix: abbreviation map (see _METRIC_ABBREV); fallback = camelcase.
    router_inserted_swaps -> Swap  |  physical_depth -> Depth
  Combined: \\{ExpMetric}Reduction, ...{ExpMetric}CILow, ...CIHigh,
            ...Wins, ...Ties, ...Losses, ...Cells, ...PooledChange, ...MedianChange.
  Example: core_n8 + router_inserted_swaps -> \\CoreSwapReduction, \\CoreSwapWins, etc.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Macro naming
# ---------------------------------------------------------------------------

_METRIC_ABBREV: dict[str, str] = {
    "router_inserted_swaps": "Swap",
    "final_swap_instructions": "FinalSwap",
    "semantic_swap_instructions": "SemanticSwap",
    "physical_depth": "Depth",
    "active_gate_count": "Gates",
    "duration_ns": "Duration",
    "compile_time_s": "CompileTime",
}


def _macro_prefix(
    experiment_id: str, metric: str, treatment: str, baseline: str
) -> str:
    """Return CamelCase prefix for generated LaTeX macros.

    The canonical prism-vs-greedy pair keeps the short prefix; any other
    pairing embeds treatment (and non-greedy baseline) so blocks never collide.
    """
    exp = re.sub(r"_n\d+$", "", experiment_id)
    exp_part = "".join(p.title() for p in exp.split("_") if p)
    met_part = _METRIC_ABBREV.get(metric) or "".join(
        p.title() for p in metric.split("_") if p
    )
    pair_part = ""
    if (treatment, baseline) != ("prism", "greedy"):
        pair_part = treatment.title() + (
            "" if baseline == "greedy" else "Vs" + baseline.title()
        )
    return exp_part + pair_part + met_part


# ---------------------------------------------------------------------------
# Data loading and filtering
# ---------------------------------------------------------------------------


def _load_rows(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _cell_key(row: dict) -> tuple:
    return (row["circuit_name"], row["requested_n"], row["topology_name"])


def _group_complete_pairs(
    rows: list[dict], baseline: str, treatment: str, metric: str
) -> tuple[list[dict], list[dict]]:
    """Return (complete_cell_seeds, excluded_cells).

    A cell+seed is complete if both baseline and treatment have a successful row
    with a non-null metric value for that (cell_key, outer_seed).
    Returns:
      complete_cell_seeds: list of {cell_key, outer_seed, baseline_val, treatment_val,
                                    baseline_run_id, treatment_run_id}
      excluded_cells: list of {cell_key, outer_seed, reason}
    """
    # Index: (cell_key, outer_seed, strategy) -> row
    index: dict[tuple, dict] = {}
    for row in rows:
        if row.get("success") is not True:
            continue
        if row.get("strategy") not in (baseline, treatment):
            continue
        key = (_cell_key(row), row["outer_seed"], row["strategy"])
        index[key] = row

    # Collect all (cell_key, seed) pairs where at least one strategy present
    all_pairs: set[tuple] = {k[:2] for k in index}

    complete = []
    excluded = []
    for ck, seed in sorted(all_pairs):
        b_row = index.get((ck, seed, baseline))
        t_row = index.get((ck, seed, treatment))
        reason = None
        if b_row is None:
            reason = f"missing {baseline}"
        elif t_row is None:
            reason = f"missing {treatment}"
        elif b_row.get(metric) is None:
            reason = f"{baseline}.{metric} is null"
        elif t_row.get(metric) is None:
            reason = f"{treatment}.{metric} is null"
        if reason:
            excluded.append(
                {
                    "circuit_name": ck[0],
                    "requested_n": ck[1],
                    "topology_name": ck[2],
                    "outer_seed": seed,
                    "reason": reason,
                }
            )
        else:
            complete.append(
                {
                    "cell_key": ck,
                    "outer_seed": seed,
                    "baseline_val": float(b_row[metric]),
                    "treatment_val": float(t_row[metric]),
                    "baseline_run_id": b_row["run_id"],
                    "treatment_run_id": t_row["run_id"],
                }
            )
    return complete, excluded


def _build_cell_structure(complete_pairs: list[dict]) -> list[dict]:
    """Group pairs by cell_key; each cell has a list of seed records."""
    cells: dict[tuple, list] = {}
    for rec in complete_pairs:
        ck = rec["cell_key"]
        if ck not in cells:
            cells[ck] = []
        cells[ck].append(rec)
    result = []
    for ck, records in sorted(cells.items()):
        result.append(
            {
                "cell_key": ck,
                "circuit_name": ck[0],
                "requested_n": ck[1],
                "topology_name": ck[2],
                "seeds": sorted(records, key=lambda r: r["outer_seed"]),
            }
        )
    return result


# ---------------------------------------------------------------------------
# Point estimates
# ---------------------------------------------------------------------------


def _cell_means(cell: dict) -> tuple[float, float]:
    """Mean over seeds for baseline and treatment."""
    b = sum(s["baseline_val"] for s in cell["seeds"]) / len(cell["seeds"])
    t = sum(s["treatment_val"] for s in cell["seeds"]) / len(cell["seeds"])
    return b, t


def _compute_point_estimates(
    cells: list[dict],
    median_zero_treatment: bool = False,
) -> dict[str, Any]:
    """Compute pooled totals, win/tie/loss, median, geo-mean of ratio.

    ``median_zero_treatment=True`` (round-3 prespec policy) additionally
    reports a median per-cell relative change whose eligibility excludes only
    zero-baseline cells, so a valid zero-treatment cell contributes -100%;
    the geometric mean keeps its stricter b>0 and t>0 eligibility with the
    zero-treatment exclusions counted explicitly. The default reproduces the
    legacy summary output byte-for-byte.
    """
    b_totals = []
    t_totals = []
    per_cell_diff = []
    per_cell_ratio = []
    per_cell_rc = []
    ratio_excluded = []
    rc_excluded_zero_baseline = 0
    geo_excluded_zero_treatment = 0
    wins = ties = losses = 0

    for cell in cells:
        b, t = _cell_means(cell)
        b_totals.append(b)
        t_totals.append(t)
        diff = t - b
        per_cell_diff.append(diff)
        if b > 0:
            per_cell_rc.append((t - b) / b)
        else:
            rc_excluded_zero_baseline += 1
        if b > 0 and t > 0:
            per_cell_ratio.append(t / b)
        else:
            if b > 0 and t == 0:
                geo_excluded_zero_treatment += 1
            ratio_excluded.append(
                {
                    "circuit_name": cell["circuit_name"],
                    "requested_n": cell["requested_n"],
                    "topology_name": cell["topology_name"],
                    "baseline_mean": b,
                    "treatment_mean": t,
                }
            )
        if t < b:
            wins += 1
        elif t == b:
            ties += 1
        else:
            losses += 1

    sum_b = sum(b_totals)
    sum_t = sum(t_totals)
    pooled_relative_change = (sum_t - sum_b) / sum_b if sum_b > 0 else None

    n = len(per_cell_diff)
    median_diff = (
        float(sorted(per_cell_diff)[n // 2])
        if n % 2 == 1
        else (sorted(per_cell_diff)[n // 2 - 1] + sorted(per_cell_diff)[n // 2]) / 2
        if n > 0
        else None
    )

    n_ratio = len(per_cell_ratio)
    if n_ratio > 0:
        log_sum = sum(math.log(r) for r in per_cell_ratio)
        geo_mean_ratio = math.exp(log_sum / n_ratio)
        median_ratio = (
            float(sorted(per_cell_ratio)[n_ratio // 2])
            if n_ratio % 2 == 1
            else (
                sorted(per_cell_ratio)[n_ratio // 2 - 1]
                + sorted(per_cell_ratio)[n_ratio // 2]
            )
            / 2
        )
    else:
        geo_mean_ratio = None
        median_ratio = None

    out = {
        "n_cells": len(cells),
        "win_tie_loss": [wins, ties, losses],
        "pooled_baseline_total": sum_b,
        "pooled_treatment_total": sum_t,
        "pooled_relative_change": pooled_relative_change,
        "median_per_cell_difference": median_diff,
        "median_per_cell_ratio": median_ratio,
        "geo_mean_ratio": geo_mean_ratio,
        "n_cells_excluded_from_ratio": len(ratio_excluded),
        "cells_excluded_from_ratio": ratio_excluded,
    }
    if median_zero_treatment:
        n_rc = len(per_cell_rc)
        srt = sorted(per_cell_rc)
        median_rc = (
            (
                float(srt[n_rc // 2])
                if n_rc % 2 == 1
                else (srt[n_rc // 2 - 1] + srt[n_rc // 2]) / 2
            )
            if n_rc
            else None
        )
        out |= {
            "median_per_cell_relative_change": median_rc,
            "median_rc_eligible_cells": n_rc,
            "median_rc_excluded_zero_baseline": rc_excluded_zero_baseline,
            "geo_excluded_zero_treatment": geo_excluded_zero_treatment,
        }
    return out


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

BOOTSTRAP_SEED = 12345
N_BOOTSTRAP = 10000


def bootstrap_ci(
    cells: list[dict], n_draws: int = N_BOOTSTRAP, seed: int = BOOTSTRAP_SEED
) -> dict:
    """Hierarchical bootstrap: resample cells, then seeds within each cell.

    Statistic 1 (pooled): (sum_treatment - sum_baseline) / sum_baseline over resampled pairs.
    Statistic 2 (median): median per-cell relative change over resampled cells.
    """
    rng = np.random.default_rng(seed)
    n_cells = len(cells)
    # Pre-build arrays: cells[i]["seeds"] = list of (b, t) pairs
    seed_arrays = [
        np.array(
            [(s["baseline_val"], s["treatment_val"]) for s in c["seeds"]], dtype=float
        )
        for c in cells
    ]

    pooled_stats = np.full(n_draws, np.nan)
    median_stats = np.full(n_draws, np.nan)

    for i in range(n_draws):
        ci_draw = rng.integers(0, n_cells, size=n_cells)
        b_sum = t_sum = 0.0
        cell_rc = []
        for ci in ci_draw:
            arr = seed_arrays[ci]
            ns = len(arr)
            si_draw = rng.integers(0, ns, size=ns)
            resampled = arr[si_draw]
            b_mean = resampled[:, 0].mean()
            t_mean = resampled[:, 1].mean()
            b_sum += b_mean
            t_sum += t_mean
            if b_mean > 0:
                cell_rc.append((t_mean - b_mean) / b_mean)
        if b_sum > 0:
            pooled_stats[i] = (t_sum - b_sum) / b_sum
        if cell_rc:
            median_stats[i] = float(np.median(cell_rc))

    valid_p = pooled_stats[~np.isnan(pooled_stats)]
    valid_m = median_stats[~np.isnan(median_stats)]
    return {
        "bootstrap_seed": seed,
        "n_bootstrap": n_draws,
        "pooled_ci_low": float(np.percentile(valid_p, 2.5)) if len(valid_p) else None,
        "pooled_ci_high": float(np.percentile(valid_p, 97.5)) if len(valid_p) else None,
        "median_ci_low": float(np.percentile(valid_m, 2.5)) if len(valid_m) else None,
        "median_ci_high": float(np.percentile(valid_m, 97.5)) if len(valid_m) else None,
    }


# ---------------------------------------------------------------------------
# LaTeX output
# ---------------------------------------------------------------------------


def _pct(v: float | None) -> str:
    if v is None:
        return r"\textcolor{blue}{TODO}"
    return f"{v * 100:.1f}\\%"


def _num(v: float | None, decimals: int = 2) -> str:
    if v is None:
        return r"\textcolor{blue}{TODO}"
    return f"{v:.{decimals}f}"


def _latex_block(
    prefix: str,
    experiment_id: str,
    baseline: str,
    treatment: str,
    metric: str,
    estimates: dict,
    ci: dict,
) -> str:
    wins, ties, losses = estimates["win_tie_loss"]
    n_cells = estimates["n_cells"]
    pooled = estimates["pooled_relative_change"]
    if "median_per_cell_relative_change" in estimates:
        # v3 prespec median: eligibility excludes only zero-baseline cells,
        # so zero-treatment cells contribute -100% (the ratio-based legacy
        # median silently drops them).
        median_rc_val = estimates["median_per_cell_relative_change"]
    else:
        median_rc = estimates.get("median_per_cell_ratio")
        median_rc_val = median_rc - 1.0 if median_rc is not None else None

    lines = [
        f"% BEGIN {prefix} ({experiment_id} / {treatment} vs {baseline} / {metric})",
        "% Naming rule: strip _nNUM from experiment_id, camelcase; abbreviate metric (see summarize.py).",
        "% Regenerate: .venv/bin/python scripts/paper/summarize.py ... (idempotent).",
        rf"\newcommand{{\{prefix}Reduction}}{{{_pct(pooled)}}}",
        # Magnitude form for "cuts X by <n>%" sentences (sign dropped).
        rf"\newcommand{{\{prefix}ReductionAbs}}{{{_pct(abs(pooled) if pooled is not None else None)}}}",
        rf"\newcommand{{\{prefix}CILow}}{{{_pct(ci['pooled_ci_low'])}}}",
        rf"\newcommand{{\{prefix}CIHigh}}{{{_pct(ci['pooled_ci_high'])}}}",
        rf"\newcommand{{\{prefix}CIAbsRange}}{{{_pct(abs(ci['pooled_ci_high']) if ci['pooled_ci_high'] is not None else None)}--{_pct(abs(ci['pooled_ci_low']) if ci['pooled_ci_low'] is not None else None)}}}",
        rf"\newcommand{{\{prefix}MedianChange}}{{{_pct(median_rc_val)}}}",
        rf"\newcommand{{\{prefix}Wins}}{{{wins}}}",
        rf"\newcommand{{\{prefix}Ties}}{{{ties}}}",
        rf"\newcommand{{\{prefix}Losses}}{{{losses}}}",
        rf"\newcommand{{\{prefix}Cells}}{{{n_cells}}}",
        rf"\newcommand{{\{prefix}GeoMeanRatio}}{{{_num(estimates['geo_mean_ratio'], 3)}}}",
        rf"\newcommand{{\{prefix}RatioExcluded}}{{{estimates['n_cells_excluded_from_ratio']}}}",
        f"% END {prefix}",
    ]
    return "\n".join(lines)


def _write_latex(latex_dir: Path, block_text: str, prefix: str) -> None:
    """Write or replace the block for this prefix in generated_results.tex."""
    latex_dir.mkdir(parents=True, exist_ok=True)
    out_path = latex_dir / "generated_results.tex"
    begin_tag = f"% BEGIN {prefix}"
    end_tag = f"% END {prefix}"

    if out_path.exists():
        existing = out_path.read_text()
        if begin_tag in existing:
            # Replace the existing block
            start = existing.index(begin_tag)
            end = existing.index(end_tag, start) + len(end_tag)
            new_content = existing[:start] + block_text + existing[end:]
            out_path.write_text(new_content)
            return
        # Append with blank line separator
        out_path.write_text(existing.rstrip("\n") + "\n\n" + block_text + "\n")
    else:
        out_path.write_text(block_text + "\n")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_DEFAULT_LATEX_DIR = Path(__file__).resolve().parents[2] / "artifacts/paper/latex"


def summarize(
    path: Path,
    baseline: str,
    treatment: str,
    metric: str,
    out_dir: Path,
    oracle_path: Path | None = None,
    latex_dir: Path | None = None,
    bootstrap_seed: int | None = None,
    n_bootstrap: int | None = None,
    median_zero_treatment: bool = False,
    macro_prefix: str | None = None,
    topologies: tuple[str, ...] | None = None,
    file_tag: str | None = None,
) -> dict:
    """Run full summarize pipeline; return the summary dict.

    The four optional knobs exist for the round-3 (v3) path: prespec
    bootstrap seed/draws, the zero-treatment median policy, and a curated
    TeX-valid macro prefix (the derived prefix keeps underscores/digits from
    v3 arm names, which are invalid in TeX control words). Defaults leave
    every legacy output byte-identical.
    """
    # TODO: oracle merging not yet implemented; hook is here.
    if oracle_path is not None:
        raise NotImplementedError(
            "oracle merging (--oracle) is not yet implemented; "
            "leave this for the X01 packet"
        )

    rows = _load_rows(path)
    if topologies is not None:
        rows = [r for r in rows if r.get("topology_name") in topologies]
    n_total = len(rows)
    n_success = sum(1 for r in rows if r.get("success") is True)

    complete_pairs, excluded = _group_complete_pairs(rows, baseline, treatment, metric)
    cells = _build_cell_structure(complete_pairs)

    if not cells:
        raise SystemExit(
            f"no complete paired cells for {treatment} vs {baseline} on metric={metric}; "
            f"excluded: {excluded}"
        )

    estimates = _compute_point_estimates(
        cells, median_zero_treatment=median_zero_treatment
    )
    ci = bootstrap_ci(
        cells,
        n_draws=n_bootstrap if n_bootstrap is not None else N_BOOTSTRAP,
        seed=bootstrap_seed if bootstrap_seed is not None else BOOTSTRAP_SEED,
    )

    experiment_ids = sorted({r.get("experiment_id", "?") for r in rows})
    experiment_id = (
        experiment_ids[0] if len(experiment_ids) == 1 else "+".join(experiment_ids)
    )

    summary = {
        "experiment_id": experiment_id,
        "baseline": baseline,
        "treatment": treatment,
        "metric": metric,
        "filter": {
            "requires_success": True,
            "requires_both_strategies": True,
            **({"topologies": sorted(topologies)} if topologies is not None else {}),
            "n_total_rows": n_total,
            "n_success_rows": n_success,
            "n_complete_pairs": len(complete_pairs),
            "excluded_pairs": excluded,
            "aggregation": "per-cell mean over seeds, then across cells",
            "zero_handling": (
                "paired differences included for all cells; "
                "ratio summaries (geo_mean_ratio) exclude cells where baseline or treatment <= 0"
            ),
        },
        "n_cells": estimates["n_cells"],
        "cells": [
            {
                "circuit_name": c["circuit_name"],
                "requested_n": c["requested_n"],
                "topology_name": c["topology_name"],
                "n_seeds": len(c["seeds"]),
                "baseline_mean": sum(s["baseline_val"] for s in c["seeds"])
                / len(c["seeds"]),
                "treatment_mean": sum(s["treatment_val"] for s in c["seeds"])
                / len(c["seeds"]),
                "seed_records": c["seeds"],
            }
            for c in cells
        ],
        **estimates,
        **ci,
    }

    # Write summary JSON
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{experiment_id}_{treatment}_vs_{baseline}_{metric}"
    if file_tag is not None:
        stem += f"_{file_tag}"
    json_path = out_dir / f"{stem}.json"
    summary["summary_file"] = str(json_path)
    json_path.write_text(json.dumps(summary, indent=2))

    # Write LaTeX macros
    prefix = macro_prefix or _macro_prefix(experiment_id, metric, treatment, baseline)
    if latex_dir is None:
        latex_dir = _DEFAULT_LATEX_DIR
    block = _latex_block(
        prefix, experiment_id, baseline, treatment, metric, estimates, ci
    )
    _write_latex(latex_dir, block, prefix)
    print(f"summary JSON -> {json_path}")
    print(
        f"LaTeX macros -> {latex_dir / 'generated_results.tex'}  (prefix: \\{prefix}...)"
    )
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("raw_jsonl", type=Path)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--treatment", required=True)
    parser.add_argument("--metric", default="router_inserted_swaps")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "artifacts/paper/summaries",
    )
    parser.add_argument("--oracle", type=Path, default=None)
    args = parser.parse_args()

    if not args.raw_jsonl.exists():
        sys.exit(f"not found: {args.raw_jsonl}")

    summary = summarize(
        args.raw_jsonl,
        args.baseline,
        args.treatment,
        args.metric,
        args.out_dir,
        args.oracle,
    )
    wins, ties, losses = summary["win_tie_loss"]
    print(
        f"\n{summary['n_cells']} cells, {wins}W/{ties}T/{losses}L, "
        f"pooled={summary['pooled_relative_change']:.3f}, "
        f"CI=[{summary['pooled_ci_low']:.3f}, {summary['pooled_ci_high']:.3f}]"
    )


if __name__ == "__main__":
    main()
