"""Export the paper scaling figure from the scale experiment."""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
from collections import defaultdict
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import lusca  # noqa: E402,F401
import matplotlib.pyplot as plt  # noqa: E402
from paper_common import BOOTSTRAP_SAMPLES, bootstrap_interval  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PAPER_ROOT = ROOT / "paper"
# SWAP-selected re-run (objective = "swaps", as the submission; research/rebuttal/suite/swaps/scale_swaps.toml).
RAW = ROOT / "artifacts/paper/raw/scale_swaps.jsonl"
OUT = ROOT / "artifacts/paper/paper_export/scaling"
QUICK_RAW = ROOT / "artifacts/paper/quick/scale.jsonl"
QUICK_OUT = ROOT / "artifacts/paper/quick_export/scaling"
# paper/ is a reference checkout; the figure reaches the draft through rebuttal_minimal.patch.
COPY_TO_PAPER = False
FIGURE_BASENAME = "eval_scaling_combined_v25"

# Widths and seeds are read from the rows.
WIDTHS: tuple[int, ...] = ()
TOPOLOGIES = ("grid", "hex_lattice")
ARMS = ("greedy", "prism")
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
    "vbe_ripple_carry_adder",
    "vqe_two_local",
    "rg_qft_multiplier",
    "multiplier",
)
SEEDS: tuple[int, ...] = ()
# Widest compiled width of any workload not run to the widest width (none in the SWAP-selected re-run).
MAX_WIDTH: dict[str, int] = {}


def _benchmarks(width: int) -> tuple[str, ...]:
    return tuple(b for b in BENCHMARKS if width <= MAX_WIDTH.get(b, width))


GRID_COLOR = "#4c78a8"
HEX_COLOR = "#d9902f"
GREEDY_COLOR = "#d69b32"
PRISM_COLOR = "#39877f"


def _read_rows() -> list[dict]:
    global WIDTHS, SEEDS  # noqa: PLW0603

    rows = [json.loads(line) for line in RAW.read_text().splitlines() if line.strip()]
    WIDTHS = tuple(sorted({int(row["requested_n"]) for row in rows}))
    SEEDS = tuple(sorted({int(row["outer_seed"]) for row in rows}))
    expected = {
        (benchmark, width, topology, seed, arm)
        for width in WIDTHS
        for benchmark in _benchmarks(width)
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
        raise RuntimeError("scaling population drift")

    for row in rows:
        trace = row.get("search_trace") or {}
        duration = float(row["duration_ns"])
        if (
            not row.get("success")
            or row.get("schema_version") != 5
            or row.get("objective") != "swaps"
            or row.get("heuristic_config") != "qiskit_sabre"
            or row.get("tie_break") != "load"
            or row.get("duration_unmodeled_ops")
            or trace.get("n_starts") != 43
            or trace.get("max_iterations") != 16
            or trace.get("final_swap_trials") != 40
            or trace.get("n_failed_starts") != 0
            or not math.isclose(duration / 100.0, round(duration / 100.0))
        ):
            raise RuntimeError(f"invalid scaling row: {row.get('run_id')}")

    return rows


def _summaries(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    samples: dict[tuple, list[float]] = defaultdict(list)
    by_seed: dict[tuple, dict[int, float]] = defaultdict(dict)
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
            by_seed[(*prefix, metric)][int(row["outer_seed"])] = float(row[metric])

    scaling = []
    timing = []
    for width in WIDTHS:
        for topology in TOPOLOGIES:
            members = _benchmarks(width)
            metric_values: dict[str, dict[str, list[float]]] = {}
            for metric in (
                "router_inserted_swaps",
                "physical_depth",
                "duration_ns",
            ):
                values = {arm: [] for arm in ARMS}
                for benchmark in members:
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
                # Greedy and PRISM share each seed's layout starts, so seeds pair the arms.
                greedy_seeds, prism_seeds = (
                    np.asarray(
                        [
                            [
                                by_seed[(benchmark, width, topology, arm, metric)][seed]
                                for seed in SEEDS
                            ]
                            for benchmark in members
                        ]
                    )
                    for arm in ARMS
                )
                suite_low, suite_high = bootstrap_interval(greedy_seeds, prism_seeds)
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
                        "n_benchmarks": len(members),
                        "n_seeds": len(SEEDS),
                        "greedy_suite_total": float(np.sum(greedy)),
                        "prism_suite_total": float(np.sum(prism)),
                        "suite_total_reduction": (
                            1.0 - float(np.sum(prism)) / float(np.sum(greedy))
                        ),
                        "suite_ci_low": suite_low,
                        "suite_ci_high": suite_high,
                        "runs_worse": int(np.sum(prism_seeds > greedy_seeds)),
                        "runs": int(prism_seeds.size),
                        "equal_workload_reduction": float(np.mean(relative)),
                        "wins": wins,
                        "ties": ties,
                        "losses": len(members) - wins - ties,
                    }
                )

            times = {arm: [] for arm in ARMS}
            for benchmark in members:
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
                    "n_benchmarks": len(members),
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


def _compile_ratios(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """PRISM/Greedy compile time per workload, and its geomean with a 95% paired seed interval over the workloads compiled at every width."""
    times: dict[tuple, dict[int, float]] = defaultdict(dict)
    for row in rows:
        key = (
            row["topology_name"],
            row["circuit_name"],
            int(row["requested_n"]),
            row["strategy"],
        )
        times[key][int(row["outer_seed"])] = float(row["compile_time_s"])
    common = _benchmarks(WIDTHS[-1])
    picks = np.random.default_rng(0).integers(
        0, len(SEEDS), (BOOTSTRAP_SAMPLES, len(SEEDS))
    )
    per_workload, geomean = [], []
    for topology in TOPOLOGIES:
        for width in WIDTHS:
            greedy, prism = (
                np.array(
                    [
                        [times[(topology, b, width, arm)][s] for s in SEEDS]
                        for b in common
                    ]
                )
                for arm in ARMS
            )
            per_workload += [
                {
                    "width": width,
                    "topology": topology,
                    "benchmark": b,
                    "prism_over_greedy": p.mean() / g.mean(),
                }
                for b, g, p in zip(
                    _benchmarks(width),
                    *(
                        np.array(
                            [
                                [times[(topology, b, width, arm)][s] for s in SEEDS]
                                for b in _benchmarks(width)
                            ]
                        )
                        for arm in ARMS
                    ),
                    strict=True,
                )
            ]
            draws = np.exp(
                np.mean(
                    np.log(prism[:, picks].mean(-1))
                    - np.log(greedy[:, picks].mean(-1)),
                    axis=0,
                )
            )
            low, high = np.percentile(draws, [2.5, 97.5])
            geomean.append(
                {
                    "width": width,
                    "topology": topology,
                    "n_benchmarks": len(common),
                    "geomean_prism_over_greedy": math.exp(
                        np.mean(np.log(prism.mean(-1)) - np.log(greedy.mean(-1)))
                    ),
                    "ci_low": float(low),
                    "ci_high": float(high),
                }
            )
    return per_workload, geomean


def _render(
    scaling: list[dict],
    timing: list[dict],
) -> tuple[Path, Path, Path]:
    scaling_lookup = {
        (int(row["width"]), row["topology"], row["metric"]): 100.0
        * float(row["suite_total_reduction"])
        for row in scaling
    }
    band_lookup = {
        (int(row["width"]), row["topology"], row["metric"]): (
            100.0 * float(row["suite_ci_low"]),
            100.0 * float(row["suite_ci_high"]),
        )
        for row in scaling
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
                # The band is the 95% bootstrap interval over seeds.
                low, high = zip(
                    *(band_lookup[(width, topology, metric)] for width in WIDTHS),
                    strict=True,
                )
                axis.fill_between(
                    WIDTHS, low, high, color=color, alpha=0.2, linewidth=0, zorder=2
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

        timing_lookup = {
            (int(row["width"]), row["topology"], arm): float(
                row["greedy_mean_s"] if arm == GREEDY else row["prism_mean_s"]
            )
            for row in timing
            for arm in ARMS
        }
        timing_styles = {
            ("grid", GREEDY): (GREEDY_COLOR, "o", "-", "Greedy, grid"),
            ("grid", PRISM): (PRISM_COLOR, "^", "-", "PRISM, grid"),
            ("hex_lattice", GREEDY): (GREEDY_COLOR, "s", "--", "Greedy, hex"),
            ("hex_lattice", PRISM): (PRISM_COLOR, "v", "--", "PRISM, hex"),
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
    if COPY_TO_PAPER:
        shutil.copyfile(pdf, paper_pdf)
    return pdf, png, paper_pdf


def main() -> None:
    global RAW, OUT, COPY_TO_PAPER  # noqa: PLW0603

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--quick", action="store_true", help="export the quick-profile rows"
    )
    if parser.parse_args().quick:
        RAW, OUT, COPY_TO_PAPER = QUICK_RAW, QUICK_OUT, False
    OUT.mkdir(parents=True, exist_ok=True)
    rows = _read_rows()
    scaling, timing = _summaries(rows)
    scaling_path = OUT / "scaling_summary.csv"
    timing_path = OUT / "timing_summary.csv"
    _write_csv(scaling_path, scaling)
    _write_csv(timing_path, timing)
    per_workload, geomean = _compile_ratios(rows)
    _write_csv(OUT / "compile_ratio_by_workload.csv", per_workload)
    _write_csv(OUT / "compile_ratio.csv", geomean)
    _render(scaling, timing)

    widest = [row for row in scaling if int(row["width"]) == WIDTHS[-1]]
    ratios = [float(row["prism_over_greedy"]) for row in timing]
    print(
        json.dumps(
            {
                "rows": len(rows),
                "widest": widest,
                "timing_ratio_mean": float(np.mean(ratios)),
                "compile_ratio_geomean": [
                    (
                        r["width"],
                        r["topology"],
                        round(r["geomean_prism_over_greedy"], 3),
                        round(r["ci_low"], 3),
                        round(r["ci_high"], 3),
                    )
                    for r in geomean
                ],
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
