"""Export the paper-facing core figures from the core and logical runs."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import defaultdict
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import lusca  # noqa: E402,F401
import matplotlib.pyplot as plt  # noqa: E402
from paper_common import bootstrap_interval  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/paper/paper_export/core"
PAPER_FIGURE = ROOT / "paper/figures/eval_core_by_benchmark_topologies_v23.pdf"
PAPER_AGGREGATE = ROOT / "paper/figures/eval_core_aggregate_row_v22.pdf"
RAW = ROOT / "artifacts/paper/raw"
QUICK_RAW = ROOT / "artifacts/paper/quick"
QUICK_OUT = ROOT / "artifacts/paper/quick_export/core"

TOPOLOGIES = ("grid", "hex_lattice", "heavy_hex")
ARMS = ("logical", "greedy", "prism")
LOGICAL, GREEDY, PRISM = ARMS
METRICS = ("router_inserted_swaps", "physical_depth")
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

TOPOLOGY_LABELS = {
    "grid": "Grid",
    "hex_lattice": "Hexagonal lattice",
    "heavy_hex": "Heavy-hex",
}
ARM_LABELS = {
    LOGICAL: "Logical-SABRE",
    GREEDY: "Greedy",
    PRISM: "PRISM",
}
ARM_COLORS = {
    LOGICAL: "#b8bdc2",
    GREEDY: "#d69b32",
    PRISM: "#39877f",
}
ARM_HATCHES = {
    LOGICAL: "///",
    GREEDY: "...",
    PRISM: "",
}
BENCHMARK_LABELS = {
    "dj": "dj",
    "qaoa": "qaoa",
    "draper_qft_adder": "draper",
    "modular_adder": "mod-add",
    "qft": "qft",
    "qpeexact": "qpe-ex",
    "qpeinexact": "qpe-in",
    "qftentangled": "qft-ent",
    "bmw_quark_copula": "copula",
    "hhl": "hhl",
    "ae": "ae",
    "cdkm_ripple_carry_adder": "cdkm",
    "vbe_ripple_carry_adder": "vbe",
    "vqe_two_local": "vqe-2local",
    "rg_qft_multiplier": "rg-mult",
    "multiplier": "mult",
}
REGRESSION = "#b55a55"


def _summaries(rows: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    seeds = sorted({int(row["outer_seed"]) for row in rows})
    values: dict[tuple, dict[int, float]] = defaultdict(dict)
    for row in rows:
        for metric in METRICS:
            values[
                (
                    row["circuit_name"],
                    row["topology_name"],
                    row["strategy"],
                    metric,
                )
            ][int(row["outer_seed"])] = float(row[metric])

    per_benchmark: list[dict] = []
    absolute: list[dict] = []
    comparisons: list[dict] = []
    for metric in METRICS:
        benchmark_means: dict[tuple, float] = {}
        for benchmark in BENCHMARKS:
            for topology in TOPOLOGIES:
                for arm in ARMS:
                    cell = values[(benchmark, topology, arm, metric)]
                    if len(cell) != len(seeds):
                        raise RuntimeError(
                            f"incomplete seed cell: {benchmark}, {topology}, "
                            f"{arm}, {metric}"
                        )
                    benchmark_means[(benchmark, topology, arm)] = float(
                        np.mean(list(cell.values()))
                    )

        for topology in TOPOLOGIES:
            for arm in ARMS:
                absolute.append(
                    {
                        "topology": topology,
                        "metric": metric,
                        "strategy": arm,
                        "mean": float(
                            np.mean(
                                [
                                    benchmark_means[(benchmark, topology, arm)]
                                    for benchmark in BENCHMARKS
                                ]
                            )
                        ),
                    }
                )

            greedy = np.asarray(
                [
                    benchmark_means[(benchmark, topology, GREEDY)]
                    for benchmark in BENCHMARKS
                ]
            )
            prism = np.asarray(
                [
                    benchmark_means[(benchmark, topology, PRISM)]
                    for benchmark in BENCHMARKS
                ]
            )
            defined = greedy > 0
            reductions = np.full_like(greedy, np.nan)
            reductions[defined] = 1.0 - prism[defined] / greedy[defined]
            zero_zero = (~defined) & (prism == 0)
            # Greedy and PRISM share each seed's layout starts, so seeds pair the arms.
            greedy_seeds = np.asarray(
                [
                    [
                        values[(benchmark, topology, GREEDY, metric)][seed]
                        for seed in seeds
                    ]
                    for benchmark in BENCHMARKS
                ]
            )
            prism_seeds = np.asarray(
                [
                    [
                        values[(benchmark, topology, PRISM, metric)][seed]
                        for seed in seeds
                    ]
                    for benchmark in BENCHMARKS
                ]
            )
            suite_low, suite_high = bootstrap_interval(greedy_seeds, prism_seeds)
            comparisons.append(
                {
                    "topology": topology,
                    "metric": metric,
                    "greedy_mean": float(np.mean(greedy)),
                    "prism_mean": float(np.mean(prism)),
                    "suite_total_reduction": float(
                        1.0 - np.sum(prism) / np.sum(greedy)
                    ),
                    "suite_ci_low": suite_low,
                    "suite_ci_high": suite_high,
                    "runs_worse": int(np.sum(prism_seeds > greedy_seeds)),
                    "runs": int(prism_seeds.size),
                    "equal_workload_reduction": float(np.mean(reductions[defined])),
                    "wins": int(np.sum(reductions[defined] > 1e-12)),
                    "ties": int(
                        np.sum(np.abs(reductions[defined]) <= 1e-12) + np.sum(zero_zero)
                    ),
                    "losses": int(np.sum(reductions[defined] < -1e-12)),
                    "undefined_nonzero": int(np.sum((~defined) & (prism != 0))),
                }
            )

            for index, benchmark in enumerate(BENCHMARKS):
                interval = (
                    bootstrap_interval(
                        greedy_seeds[index : index + 1], prism_seeds[index : index + 1]
                    )
                    if defined[index]
                    else (None, None)
                )
                per_benchmark.append(
                    {
                        "benchmark": benchmark,
                        "topology": topology,
                        "metric": metric,
                        "logical_sabre_mean": benchmark_means[
                            (benchmark, topology, LOGICAL)
                        ],
                        "greedy_mean": float(greedy[index]),
                        "prism_mean": float(prism[index]),
                        "relative_reduction": (
                            float(reductions[index]) if defined[index] else None
                        ),
                        "ci_low": interval[0],
                        "ci_high": interval[1],
                    }
                )
    return absolute, per_benchmark, comparisons


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _render_aggregate(
    absolute: list[dict],
    *,
    stem: str = "fig8_core_aggregate_seed20",
) -> tuple[Path, Path]:
    lookup = {
        (row["topology"], row["metric"], row["strategy"]): row["mean"]
        for row in absolute
    }
    with plt.style.context("lusca"):
        plt.rcParams.update(
            {
                "font.size": 7.8,
                "axes.labelsize": 8.2,
                "xtick.labelsize": 7.7,
                "ytick.labelsize": 7.4,
                "legend.fontsize": 7.8,
                "pdf.fonttype": 42,
            }
        )
        figure, axes = plt.subplots(1, 2, figsize=(7.15, 1.65))
        group_x = np.arange(len(TOPOLOGIES))
        width = 0.22
        specs = (
            ("router_inserted_swaps", "(a) Routing SWAPs"),
            ("physical_depth", "(b) Physical depth"),
        )
        for axis, (metric, title) in zip(axes, specs, strict=True):
            all_values = []
            for arm_index, arm in enumerate(ARMS):
                arm_values = [
                    lookup[(topology, metric, arm)] for topology in TOPOLOGIES
                ]
                all_values.extend(arm_values)
                bars = axis.bar(
                    group_x + (arm_index - 1) * width,
                    arm_values,
                    width=width,
                    color=ARM_COLORS[arm],
                    edgecolor="#303030",
                    linewidth=0.5,
                    label=ARM_LABELS[arm],
                    zorder=3,
                )
                for bar in bars:
                    bar.set_hatch(ARM_HATCHES[arm])
                axis.bar_label(bars, fmt="%.1f", padding=2, fontsize=7.0)
            axis.set_title(title, loc="left", fontsize=8.2)
            axis.set_xticks(
                group_x,
                [TOPOLOGY_LABELS[topology] for topology in TOPOLOGIES],
            )
            axis.set_ylim(0, max(all_values) * 1.19)
            axis.grid(axis="y", color="#dedede", linewidth=0.5, zorder=0)
            axis.set_axisbelow(True)
        handles, labels = axes[0].get_legend_handles_labels()
        figure.legend(
            handles,
            labels,
            loc="upper center",
            ncol=3,
            frameon=False,
            bbox_to_anchor=(0.5, 1.01),
        )
        figure.tight_layout(
            rect=(0, 0, 1, 0.82),
            pad=0.3,
            w_pad=0.8,
        )
    pdf = OUT / f"{stem}.pdf"
    png = OUT / f"{stem}.png"
    figure.savefig(
        pdf,
        bbox_inches="tight",
        pad_inches=0.02,
        metadata={"CreationDate": None, "ModDate": None},
    )
    figure.savefig(png, dpi=300, bbox_inches="tight", pad_inches=0.02)
    plt.close(figure)
    return pdf, png


def _validated_rows(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if any(not row.get("success") for row in rows):
        raise RuntimeError(f"failed rows in {path}")
    return rows


def _load() -> list[dict]:
    rows = _validated_rows(RAW / "core.jsonl") + _validated_rows(RAW / "logical.jsonl")
    expected = {
        (benchmark, topology, seed, arm)
        for benchmark in BENCHMARKS
        for topology in TOPOLOGIES
        for seed in {int(row["outer_seed"]) for row in rows}
        for arm in ARMS
    }
    observed = {
        (
            row["circuit_name"],
            row["topology_name"],
            int(row["outer_seed"]),
            row["strategy"],
        )
        for row in rows
    }
    if observed != expected or len(rows) != len(expected):
        raise RuntimeError("the combined core population is incomplete")
    return rows


def _render_per_benchmark_by_topology(
    per_benchmark: list[dict],
    workloads: list[str] | None = None,
    stem: str = "core_by_benchmark_topologies_seed20",
    out: Path | None = None,
    paper_figure: Path | None = None,
    sort_topology: str = "hex_lattice",
    floor: float | None = None,
) -> tuple[Path, Path, list[str]]:
    """Fig. 9: per-workload reductions sorted by one topology's SWAP reduction; ``workloads`` replaces the core set (and skips the paper copy); whiskers below ``floor`` (%) stop there with an arrowhead."""
    names = workloads or list(BENCHMARKS)
    out = out or OUT
    paper_figure = paper_figure if workloads else PAPER_FIGURE
    lookup = {
        (row["benchmark"], row["topology"], row["metric"]): row for row in per_benchmark
    }
    metric_titles = {
        "router_inserted_swaps": "routing SWAPs",
        "physical_depth": "physical depth",
    }
    panel_specs = [
        (
            topology,
            metric,
            f"({'abcdefgh'[2 * row + column]}) {TOPOLOGY_LABELS[topology]} — {metric_titles[metric]}",
        )
        for row, topology in enumerate(TOPOLOGIES)
        for column, metric in enumerate(METRICS)
    ]
    reductions: dict[tuple[str, str], np.ndarray] = {}
    intervals: dict[tuple[str, str], np.ndarray] = {}
    for topology, metric, _title in panel_specs:
        values = []
        ranges = []
        for benchmark in names:
            row = lookup[(benchmark, topology, metric)]
            ranges.append(
                [
                    np.nan if row[key] is None else 100.0 * row[key]
                    for key in ("ci_low", "ci_high")
                ]
            )
            greedy = float(row["greedy_mean"])
            prism = float(row["prism_mean"])
            if greedy == 0:
                if prism != 0:
                    raise RuntimeError(
                        f"undefined reduction: {benchmark}, {topology}, {metric}"
                    )
                values.append(0.0)
            else:
                values.append(100.0 * (1.0 - prism / greedy))
        reductions[(topology, metric)] = np.asarray(values)
        intervals[(topology, metric)] = np.asarray(ranges)
    # Every panel uses one order: increasing SWAP reduction on sort_topology.
    sort_swaps = dict(
        zip(
            names,
            reductions[(sort_topology, "router_inserted_swaps")],
            strict=True,
        )
    )
    order = sorted(names, key=lambda b: (sort_swaps[b], b))
    index = [names.index(benchmark) for benchmark in order]
    reductions = {key: values[index] for key, values in reductions.items()}
    intervals = {key: ranges[index] for key, ranges in intervals.items()}

    with plt.style.context("lusca"):
        plt.rcParams.update(
            {
                "font.size": 7.2,
                "axes.labelsize": 7.6,
                "xtick.labelsize": 6.2,
                "ytick.labelsize": 6.8,
                "pdf.fonttype": 42,
            }
        )
        figure, axes = plt.subplots(
            len(TOPOLOGIES),
            len(METRICS),
            figsize=(7.15, 1.59 * len(TOPOLOGIES)),
            sharex=True,
        )
        x = np.arange(len(order))
        for axis, (topology, metric, title) in zip(
            axes.flat,
            panel_specs,
            strict=True,
        ):
            values = reductions[(topology, metric)]
            colors = np.where(
                values >= 0,
                ARM_COLORS[PRISM],
                REGRESSION,
            )
            axis.bar(
                x,
                values,
                color=colors,
                edgecolor="#303030",
                linewidth=0.35,
                width=0.76,
                zorder=3,
            )
            # Error bars are 95% bootstrap intervals over seeds.
            low, high = intervals[(topology, metric)].T
            if floor is not None:
                clipped = low < floor
                low = np.maximum(low, floor)
                axis.plot(
                    x[clipped],
                    low[clipped],
                    "v",
                    ms=2.4,
                    color="#303030",
                    zorder=5,
                    clip_on=False,
                )
            axis.errorbar(
                x,
                values,
                yerr=(values - low, high - values),
                fmt="none",
                ecolor="#303030",
                elinewidth=0.6,
                capsize=1.6,
                capthick=0.6,
                zorder=4,
            )
            axis.axhline(0, color="#777777", linewidth=0.6, zorder=2)
            axis.set_title(title, loc="left", fontsize=7.8)
            axis.set_ylabel("PRISM reduction\nvs. Greedy (%)")
            axis.grid(axis="y", color="#e1e1e1", linewidth=0.45, zorder=0)
            axis.set_axisbelow(True)

        for column, metric in enumerate(METRICS):
            all_values = np.concatenate(
                [intervals[(topology, metric)] for topology in TOPOLOGIES]
            )
            upper = max(0.0, float(np.nanmax(all_values)))
            lower = min(0.0, float(np.nanmin(all_values)))
            if floor is not None:
                lower = max(lower, floor)
            upper_margin = max(2.0, 0.06 * (upper - lower))
            lower_margin = 0.0 if lower == 0.0 else upper_margin
            for row in range(len(TOPOLOGIES)):
                axes[row, column].set_ylim(
                    lower - lower_margin,
                    upper + upper_margin,
                )

        labels = [BENCHMARK_LABELS.get(benchmark, benchmark) for benchmark in order]
        for axis in axes[:-1].flat:
            axis.tick_params(axis="x", labelbottom=False)
        for axis in axes[-1]:
            axis.set_xticks(x, labels, rotation=52, ha="right")
        figure.tight_layout(pad=0.35, h_pad=0.7, w_pad=0.8)

    pdf = out / f"{stem}.pdf"
    png = out / f"{stem}.png"
    figure.savefig(
        pdf,
        bbox_inches="tight",
        pad_inches=0.02,
        metadata={"CreationDate": None, "ModDate": None},
    )
    figure.savefig(png, dpi=300, bbox_inches="tight", pad_inches=0.02)
    plt.close(figure)
    if paper_figure is not None:
        shutil.copyfile(pdf, paper_figure)
    return pdf, png, order


def main() -> None:
    global RAW, OUT, PAPER_FIGURE, PAPER_AGGREGATE  # noqa: PLW0603

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--quick", action="store_true", help="export the quick-profile rows"
    )
    if parser.parse_args().quick:
        RAW, OUT, PAPER_FIGURE, PAPER_AGGREGATE = QUICK_RAW, QUICK_OUT, None, None
    OUT.mkdir(parents=True, exist_ok=True)
    rows = _load()
    absolute, per_benchmark, comparisons = _summaries(rows)

    absolute_path = OUT / "absolute_metrics.csv"
    benchmark_path = OUT / "per_benchmark.csv"
    comparison_path = OUT / "controlled_comparison.csv"
    _write_csv(absolute_path, absolute)
    _write_csv(benchmark_path, per_benchmark)
    _write_csv(comparison_path, comparisons)
    aggregate_pdf, _ = _render_aggregate(absolute, stem="core_aggregate_seed20")
    if PAPER_AGGREGATE is not None:
        shutil.copyfile(aggregate_pdf, PAPER_AGGREGATE)
    _render_per_benchmark_by_topology(per_benchmark)
    print(json.dumps({"rows": len(rows), "output": str(OUT)}, indent=2))


if __name__ == "__main__":
    main()
