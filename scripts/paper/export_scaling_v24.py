"""Export the paper scaling figure from the validated v24 experiment."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import lusca  # noqa: E402,F401
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PAPER_ROOT = ROOT / "paper"
RAW = ROOT / "artifacts/paper/raw/scale_v24_ordered_depth_tie_n8_32.jsonl"
VALIDATION = RAW.with_name(RAW.stem + "_fairness_validation.json")
OUT = ROOT / "artifacts/paper/paper_export/scale_v24_ordered_depth_tie"
FIGURE_BASENAME = "eval_scaling_combined_v24"

WIDTHS = (8, 12, 16, 20, 24, 28, 32)
TOPOLOGIES = ("grid", "hex_lattice")
ARMS = ("greedy_early_commit", "prism_retained_set")
GREEDY, PRISM = ARMS
BENCHMARKS = (
    "dj",
    "qaoa",
    "draper_qft_adder",
    "modular_adder",
    "qft",
    "qpeexact",
    "qpeinexact",
    "qftentangled",
    "bmw_quark_copula",
    "hhl",
    "ae",
    "cdkm_ripple_carry_adder",
    "full_adder",
    "vqe_two_local",
    "rg_qft_multiplier",
    "multiplier",
)
SEEDS = (42, 7, 123, 1001, 2002)

GRID_COLOR = "#4c78a8"
HEX_COLOR = "#d9902f"
GREEDY_COLOR = "#d69b32"
PRISM_COLOR = "#39877f"


def _read_rows() -> tuple[list[dict], dict]:
    report = json.loads(VALIDATION.read_text())
    if (
        not report.get("valid")
        or report.get("errors")
        or report.get("n_missing_vs_grid")
        or report.get("n_rows") != 2240
        or report.get("n_success") != 2240
    ):
        raise RuntimeError("v24 scaling fairness validation failed")

    rows = [json.loads(line) for line in RAW.read_text().splitlines() if line.strip()]
    expected = {
        (benchmark, width, topology, seed, arm)
        for benchmark in BENCHMARKS
        for width in WIDTHS
        for topology in TOPOLOGIES
        for seed in SEEDS
        for arm in ARMS
    }
    observed = {
        (
            row["circuit_name"],
            int(row["requested_n"]),
            row["topology_name"],
            int(row["outer_seed"]),
            row["strategy"],
        )
        for row in rows
    }
    if len(rows) != len(expected) or observed != expected:
        raise RuntimeError("v24 scaling population drift")

    for row in rows:
        trace = row.get("search_trace") or {}
        duration = float(row["duration_ns"])
        if (
            not row.get("success")
            or row.get("schema_version") != 5
            or row.get("objective") != "swaps"
            or row.get("heuristic_config") != "qiskit_sabre"
            or row.get("tie_break") != "load"
            or row.get("configured_handoff_mode") != "best"
            or row.get("routing_handoff_kept") != "lowering"
            or row.get("duration_unmodeled_ops")
            or row.get("runner_workers") != 12
            or trace.get("n_starts") != 43
            or trace.get("max_iterations") != 16
            or trace.get("final_swap_trials") != 40
            or trace.get("n_failed_starts") != 0
            or not math.isclose(duration / 100.0, round(duration / 100.0))
        ):
            raise RuntimeError(f"invalid scaling row: {row.get('run_id')}")

    metadata = {
        "input": str(RAW.relative_to(ROOT)),
        "validations": [str(VALIDATION.relative_to(ROOT))],
        "rows": len(rows),
        "widths": list(WIDTHS),
        "benchmarks": list(BENCHMARKS),
        "topologies": list(TOPOLOGIES),
        "seeds": list(SEEDS),
        "arms": list(ARMS),
        "source_fingerprints": sorted({row["source_fingerprint"] for row in rows}),
        "config_fingerprints": sorted({row["config_fingerprint"] for row in rows}),
        "code_git_shas": sorted({row["code_git_sha"] for row in rows}),
    }
    return rows, metadata


def _summaries(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    samples: dict[tuple, list[float]] = defaultdict(list)
    for row in rows:
        prefix = (
            row["circuit_name"],
            int(row["requested_n"]),
            row["topology_name"],
            row["strategy"],
        )
        for metric in (
            "router_inserted_swaps",
            "physical_depth",
            "duration_ns",
            "compile_time_s",
        ):
            samples[(*prefix, metric)].append(float(row[metric]))

    scaling = []
    timing = []
    for width in WIDTHS:
        for topology in TOPOLOGIES:
            metric_values: dict[str, dict[str, list[float]]] = {}
            for metric in (
                "router_inserted_swaps",
                "physical_depth",
                "duration_ns",
            ):
                values = {arm: [] for arm in ARMS}
                for benchmark in BENCHMARKS:
                    for arm in ARMS:
                        group = samples[(benchmark, width, topology, arm, metric)]
                        if len(group) != len(SEEDS):
                            raise RuntimeError(
                                f"incomplete metric cell: {benchmark}, "
                                f"{width}, {topology}, {arm}, {metric}"
                            )
                        values[arm].append(float(np.mean(group)))
                metric_values[metric] = values
                greedy = values[GREEDY]
                prism = values[PRISM]
                relative = [
                    1.0 - retained / fixed
                    for fixed, retained in zip(greedy, prism, strict=True)
                    if fixed != 0
                ]
                wins = sum(
                    retained < fixed
                    for fixed, retained in zip(greedy, prism, strict=True)
                )
                ties = sum(
                    math.isclose(
                        retained,
                        fixed,
                        rel_tol=0.0,
                        abs_tol=1e-12,
                    )
                    for fixed, retained in zip(greedy, prism, strict=True)
                )
                scaling.append(
                    {
                        "width": width,
                        "topology": topology,
                        "metric": metric,
                        "n_benchmarks": len(BENCHMARKS),
                        "n_seeds": len(SEEDS),
                        "greedy_suite_total": float(np.sum(greedy)),
                        "prism_suite_total": float(np.sum(prism)),
                        "suite_total_reduction": (
                            1.0 - float(np.sum(prism)) / float(np.sum(greedy))
                        ),
                        "equal_workload_reduction": float(np.mean(relative)),
                        "wins": wins,
                        "ties": ties,
                        "losses": len(BENCHMARKS) - wins - ties,
                    }
                )

            times = {arm: [] for arm in ARMS}
            for benchmark in BENCHMARKS:
                for arm in ARMS:
                    group = samples[
                        (
                            benchmark,
                            width,
                            topology,
                            arm,
                            "compile_time_s",
                        )
                    ]
                    if len(group) != len(SEEDS):
                        raise RuntimeError(
                            f"incomplete timing cell: {benchmark}, "
                            f"{width}, {topology}, {arm}"
                        )
                    times[arm].append(float(np.mean(group)))
            greedy_time = float(np.mean(times[GREEDY]))
            prism_time = float(np.mean(times[PRISM]))
            timing.append(
                {
                    "width": width,
                    "topology": topology,
                    "n_benchmarks": len(BENCHMARKS),
                    "n_seeds": len(SEEDS),
                    "greedy_mean_s": greedy_time,
                    "prism_mean_s": prism_time,
                    "prism_over_greedy": prism_time / greedy_time,
                }
            )
    return scaling, timing


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _render(
    scaling: list[dict],
    timing: list[dict],
) -> tuple[Path, Path, Path]:
    scaling_lookup = {
        (int(row["width"]), row["topology"], row["metric"]): 100.0
        * float(row["suite_total_reduction"])
        for row in scaling
    }
    timing_lookup = {
        (int(row["width"]), row["topology"], arm): float(
            row["greedy_mean_s"] if arm == GREEDY else row["prism_mean_s"]
        )
        for row in timing
        for arm in ARMS
    }

    with plt.style.context("lusca"):
        plt.rcParams.update(
            {
                "font.size": 7.0,
                "axes.labelsize": 7.2,
                "xtick.labelsize": 6.5,
                "ytick.labelsize": 6.5,
                "legend.fontsize": 6.2,
                "pdf.fonttype": 42,
            }
        )
        figure = plt.figure(figsize=(3.35, 2.55))
        grid_spec = figure.add_gridspec(
            2,
            2,
            height_ratios=(1.0, 1.05),
        )
        axes = (
            figure.add_subplot(grid_spec[0, 0]),
            figure.add_subplot(grid_spec[0, 1]),
            figure.add_subplot(grid_spec[1, :]),
        )

        topology_styles = {
            "grid": (GRID_COLOR, "o", "Grid"),
            "hex_lattice": (HEX_COLOR, "s", "Hexagonal lattice"),
        }
        reduction_panels = (
            ("router_inserted_swaps", "(a) Routing SWAPs"),
            ("duration_ns", "(b) Critical-path duration"),
        )
        for axis, (metric, title) in zip(
            axes[:2],
            reduction_panels,
            strict=True,
        ):
            for topology in TOPOLOGIES:
                color, marker, label = topology_styles[topology]
                axis.plot(
                    WIDTHS,
                    [scaling_lookup[(width, topology, metric)] for width in WIDTHS],
                    color=color,
                    marker=marker,
                    markersize=3.2,
                    linewidth=1.35,
                    label=label,
                    zorder=3,
                )
            axis.set_title(title, loc="left", fontsize=7.3)
            axis.set_xticks((8, 16, 24, 32))
            axis.set_ylim(0, 36)
            axis.grid(color="#e1e1e1", linewidth=0.45, zorder=0)
            axis.set_axisbelow(True)
        axes[0].set_ylabel("Reduction (%)")
        axes[0].legend(
            frameon=False,
            loc="lower right",
            handlelength=1.4,
            handletextpad=0.3,
        )

        timing_styles = {
            ("grid", GREEDY): (
                GREEDY_COLOR,
                "o",
                "-",
                "Greedy, grid",
            ),
            ("grid", PRISM): (
                PRISM_COLOR,
                "^",
                "-",
                "PRISM, grid",
            ),
            ("hex_lattice", GREEDY): (
                GREEDY_COLOR,
                "s",
                "--",
                "Greedy, hex",
            ),
            ("hex_lattice", PRISM): (
                PRISM_COLOR,
                "v",
                "--",
                "PRISM, hex",
            ),
        }
        axis = axes[2]
        for topology in TOPOLOGIES:
            for arm in ARMS:
                color, marker, linestyle, label = timing_styles[(topology, arm)]
                axis.plot(
                    WIDTHS,
                    [timing_lookup[(width, topology, arm)] for width in WIDTHS],
                    color=color,
                    marker=marker,
                    linestyle=linestyle,
                    markersize=3.2,
                    linewidth=1.35,
                    label=label,
                    zorder=3,
                )
        axis.set_title("(c) Compilation time", loc="left", fontsize=7.3)
        axis.set_xlabel("Logical qubits")
        axis.set_ylabel("Time (s)")
        axis.set_xticks(WIDTHS)
        axis.set_ylim(bottom=0)
        axis.grid(color="#e1e1e1", linewidth=0.45, zorder=0)
        axis.set_axisbelow(True)
        axis.legend(frameon=False, ncol=2, loc="upper left")

        figure.tight_layout(pad=0.35, w_pad=0.5, h_pad=0.45)

    pdf = OUT / f"{FIGURE_BASENAME}.pdf"
    png = OUT / f"{FIGURE_BASENAME}.png"
    paper_pdf = PAPER_ROOT / "figures" / f"{FIGURE_BASENAME}.pdf"
    figure.savefig(
        pdf,
        bbox_inches="tight",
        pad_inches=0.02,
        metadata={"CreationDate": None, "ModDate": None},
    )
    figure.savefig(png, dpi=300, bbox_inches="tight", pad_inches=0.02)
    plt.close(figure)
    shutil.copyfile(pdf, paper_pdf)
    return pdf, png, paper_pdf


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows, metadata = _read_rows()
    scaling, timing = _summaries(rows)
    scaling_path = OUT / "scaling_summary.csv"
    timing_path = OUT / "timing_summary.csv"
    _write_csv(scaling_path, scaling)
    _write_csv(timing_path, timing)
    figures = _render(scaling, timing)

    provenance = {
        **metadata,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "duration_model": {
            "sws_ns": 500.0,
            "beamsplitter_ns": 200.0,
            "software_tracked_z_ns": 0.0,
            "synthetic_preparation_ns": 0.0,
        },
        "aggregation": (
            "Average five seeds within each workload. Scaling reductions use "
            "the ratio of the sums of the 16 workload means; the CSV also "
            "reports the unweighted mean of workload-relative reductions. "
            "Timing points average the 16 workload means."
        ),
        "timing_scope": (
            "Descriptive per-compilation wall time recorded during the same "
            "12-worker experiment. Each compiler invocation is single-threaded."
        ),
        "outputs": [
            str(scaling_path.relative_to(ROOT)),
            str(timing_path.relative_to(ROOT)),
            str(figures[0].relative_to(ROOT)),
            str(figures[1].relative_to(ROOT)),
            str(figures[2].relative_to(ROOT)),
        ],
        "regenerate": (".venv/bin/python scripts/paper/export_scaling_v24.py"),
        "export_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    (OUT / "PROVENANCE.json").write_text(json.dumps(provenance, indent=2) + "\n")

    n32 = [row for row in scaling if int(row["width"]) == 32]
    ratios = [float(row["prism_over_greedy"]) for row in timing]
    print(
        json.dumps(
            {
                "rows": len(rows),
                "n32": n32,
                "timing_ratio_mean": float(np.mean(ratios)),
                "timing_ratio_range": [
                    float(np.min(ratios)),
                    float(np.max(ratios)),
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
