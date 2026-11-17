"""Export the device-model hardware-relevance experiment."""

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

from marabbecca.utils.metrics import RSWAP_ERROR, device_success  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PAPER_ROOT = ROOT / "paper"
RAW = ROOT / "artifacts/paper/raw/scale.jsonl"
OUT = ROOT / "artifacts/paper/paper_export/device"
COPY_TO_PAPER = True
FIGURE_BASENAME = "eval_hardware_liu_v25"
EXPECTED_STARTS = 43
EXPECTED_ITERATIONS = 16
EXPECTED_OBJECTIVE = "error"
# Keep probability: Eq. 1 on the dual-rail device of Mehta et al. (arXiv:2503.10935), from the rows'
# pair exposure. Every live pair decays at the four-cavity mean rate while idle, and each gate erases
# each live pair it touches with its measured, role-dependent probability. Conditional fidelity stays
# marabbecca.utils.metrics.device_success. Values match research/rebuttal/wallclock/sim.MEHTA.
MODEL = "mehta"
T1_US = 4 / (1 / 231 + 1 / 411 + 1 / 652 + 1 / 342)
ERASURE = {"crz_control": 4.00e-3, "crz_target": 0.96e-3} | dict.fromkeys(
    ("rswap", "swap", "rx"), (8.56e-4 + 5.92e-4) / 2
)

# Postselection can run a workload only if Greedy keeps at least this share of shots (fixed in research/rebuttal/scale/HEADLINE.md).
VIABLE_KEEP = 0.01

WIDTHS = (8, 12, 16)
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
# Seeds are read from the rows.
SEEDS: tuple[int, ...] = ()

GRID_COLOR = "#4c78a8"
HEX_COLOR = "#d9902f"


def _read_rows() -> list[dict]:
    global SEEDS  # noqa: PLW0603

    all_rows = [
        json.loads(line) for line in RAW.read_text().splitlines() if line.strip()
    ]
    SEEDS = tuple(sorted({int(row["outer_seed"]) for row in all_rows}))
    rows = [
        row
        for row in all_rows
        if row.get("circuit_name") in BENCHMARKS
        and int(row.get("requested_n", -1)) in WIDTHS
        and row.get("topology_name") in TOPOLOGIES
        and int(row.get("outer_seed", -1)) in SEEDS
        and row.get("strategy") in ARMS
    ]
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
        raise RuntimeError("device experiment population drift")

    for row in rows:
        trace = row.get("search_trace") or {}
        if (
            not row.get("success")
            or row.get("schema_version") != 5
            or row.get("objective") != EXPECTED_OBJECTIVE
            or row.get("heuristic_config") != "qiskit_sabre"
            or row.get("tie_break") != "load"
            or row.get("duration_unmodeled_ops")
            or trace.get("n_starts") != EXPECTED_STARTS
            or trace.get("max_iterations") != EXPECTED_ITERATIONS
            or trace.get("final_swap_trials") != 40
            or trace.get("n_failed_starts") != 0
        ):
            raise RuntimeError(f"invalid result row: {row.get('run_id')}")

    return rows


def _model_row(row: dict, rswap_error: float) -> dict:
    width = int(row["actual_n_logical"])
    duration_us = float(row["duration_ns"]) / 1_000.0
    ops = row["program_body_op_counts"]
    n_semantic_rswap = sum(int(ops.get(name, 0)) for name in ("rswap", "rx", "sx"))
    n_routing_rswap = int(ops.get("swap", 0))
    _, conditional_fidelity = device_success(
        width, float(row["duration_ns"]), ops, rswap_error=rswap_error
    )
    keep_probability = math.exp(
        sum(n * math.log1p(-ERASURE[key]) for key, n in row["pair_touches"].items())
        - row["pair_idle_us"] / T1_US
    )
    return {
        "duration_us": duration_us,
        "routing_swaps": int(row["router_inserted_swaps"]),
        "n_sws": int(ops.get("crz", 0)),
        "n_semantic_rswap": n_semantic_rswap,
        "n_routing_rswap": n_routing_rswap,
        "n_rswap": n_semantic_rswap + n_routing_rswap,
        "n_rz": int(ops.get("rz", 0)),
        "cavity_exposure_us": width * duration_us,
        "coupler_exposure_us": 0.0,
        "lifetime_exposure_us": width * duration_us,
        "pair_idle_us": row["pair_idle_us"],
        "keep_probability": keep_probability,
        "postselection_shot_overhead": 1.0 / keep_probability,
        "conditional_fidelity_proxy": conditional_fidelity,
        "conditional_infidelity_proxy": 1.0 - conditional_fidelity,
        "overall_success_probability": keep_probability * conditional_fidelity,
    }


def _per_workload(rows: list[dict], rswap_error: float = RSWAP_ERROR) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        groups[
            (
                row["circuit_name"],
                int(row["requested_n"]),
                row["topology_name"],
                row["strategy"],
            )
        ].append(row)

    output = []
    for key in sorted(groups):
        benchmark, width, topology, arm = key
        group = groups[key]
        if {int(row["outer_seed"]) for row in group} != set(SEEDS):
            raise RuntimeError(f"incomplete seed cell: {key}")
        modeled = [_model_row(row, rswap_error) for row in group]
        output.append(
            {
                "benchmark": benchmark,
                "width": width,
                "topology": topology,
                "strategy": arm,
                "model": MODEL,
                "n_seeds": len(group),
                **{
                    f"mean_{field}": float(np.mean([item[field] for item in modeled]))
                    for field in modeled[0]
                },
            }
        )
    return output


def _matching_lifetime(rows: list[dict], width: int, topology: str) -> float:
    """Relative T1 increase at which Greedy's shot overhead (geomean over workloads) matches PRISM's at T1_US."""

    def overhead(arm: str, t1: float) -> float:
        by_workload = defaultdict(list)
        for row in rows:
            if (
                int(row["requested_n"]) == width
                and row["topology_name"] == topology
                and row["strategy"] == arm
            ):
                log_erasure = sum(
                    n * math.log1p(-ERASURE[k]) for k, n in row["pair_touches"].items()
                )
                by_workload[row["circuit_name"]].append(
                    math.exp(row["pair_idle_us"] / t1 - log_erasure)
                )
        return math.exp(np.mean([math.log(np.mean(v)) for v in by_workload.values()]))

    target, low, high = overhead(PRISM, T1_US), T1_US, 1e7
    if overhead(GREEDY, high) > target:
        return (
            math.nan
        )  # the erasures alone cost Greedy more than PRISM's whole overhead
    for _ in range(100):
        mid = (low + high) / 2
        low, high = (mid, high) if overhead(GREEDY, mid) > target else (low, mid)
    return low / T1_US - 1.0


def _summarize(per_workload: list[dict]) -> list[dict]:
    lookup = {
        (
            row["benchmark"],
            int(row["width"]),
            row["topology"],
            row["strategy"],
        ): row
        for row in per_workload
    }
    metrics = (
        "duration_us",
        "postselection_shot_overhead",
        "conditional_infidelity_proxy",
    )
    output = []
    for width in WIDTHS:
        for topology in TOPOLOGIES:
            comparison = {
                "width": width,
                "topology": topology,
                "model": MODEL,
                "n_benchmarks": len(BENCHMARKS),
                "n_seeds": len(SEEDS),
            }
            for metric in metrics:
                greedy_values = []
                prism_values = []
                relative_reductions = []
                wins = 0
                ties = 0
                for benchmark in BENCHMARKS:
                    greedy = lookup[
                        (
                            benchmark,
                            width,
                            topology,
                            GREEDY,
                        )
                    ][f"mean_{metric}"]
                    prism = lookup[
                        (
                            benchmark,
                            width,
                            topology,
                            PRISM,
                        )
                    ][f"mean_{metric}"]
                    greedy_values.append(greedy)
                    prism_values.append(prism)
                    if greedy == 0:
                        raise RuntimeError(
                            f"zero {metric} denominator: "
                            f"{benchmark}, n={width}, {topology}"
                        )
                    relative_reductions.append(1.0 - prism / greedy)
                    wins += prism < greedy
                    ties += math.isclose(
                        prism,
                        greedy,
                        rel_tol=0.0,
                        abs_tol=1e-12,
                    )
                prefix = metric.removesuffix("_us").removesuffix("_proxy")
                comparison |= {
                    f"greedy_mean_{prefix}": float(np.mean(greedy_values)),
                    f"prism_mean_{prefix}": float(np.mean(prism_values)),
                    f"{prefix}_suite_total_reduction": (
                        1.0 - float(np.sum(prism_values)) / float(np.sum(greedy_values))
                    ),
                    f"{prefix}_equal_workload_reduction": float(
                        np.mean(relative_reductions)
                    ),
                    f"{prefix}_geomean_ratio_reduction": (
                        1.0
                        - math.exp(
                            float(np.mean(np.log(prism_values)))
                            - float(np.mean(np.log(greedy_values)))
                        )
                    ),
                    f"{prefix}_wins": wins,
                    f"{prefix}_ties": ties,
                }

            for metric in (
                "keep_probability",
                "conditional_fidelity_proxy",
                "overall_success_probability",
            ):
                prefix = metric.removesuffix("_proxy")
                for arm in ARMS:
                    values = [
                        lookup[
                            (
                                benchmark,
                                width,
                                topology,
                                arm,
                            )
                        ][f"mean_{metric}"]
                        for benchmark in BENCHMARKS
                    ]
                    comparison[f"{arm}_{prefix}_mean"] = float(np.mean(values))

            greedy_success = [
                lookup[
                    (
                        benchmark,
                        width,
                        topology,
                        GREEDY,
                    )
                ]["mean_overall_success_probability"]
                for benchmark in BENCHMARKS
            ]
            prism_success = [
                lookup[
                    (
                        benchmark,
                        width,
                        topology,
                        PRISM,
                    )
                ]["mean_overall_success_probability"]
                for benchmark in BENCHMARKS
            ]
            comparison |= {
                "overall_success_probability_suite_mean_improvement": (
                    float(np.sum(prism_success)) / float(np.sum(greedy_success)) - 1.0
                ),
                "overall_success_probability_equal_workload_improvement": (
                    float(
                        np.mean(
                            [
                                prism / greedy - 1.0
                                for greedy, prism in zip(
                                    greedy_success,
                                    prism_success,
                                    strict=True,
                                )
                            ]
                        )
                    )
                ),
                "overall_success_probability_geomean_ratio_improvement": (
                    math.exp(
                        float(np.mean(np.log(prism_success)))
                        - float(np.mean(np.log(greedy_success)))
                    )
                    - 1.0
                ),
                "overall_success_probability_wins": sum(
                    prism > greedy
                    for greedy, prism in zip(
                        greedy_success,
                        prism_success,
                        strict=True,
                    )
                ),
            }
            output.append(comparison)
    return output


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _render(summary: list[dict]) -> tuple[Path, Path, Path]:
    lookup = {(int(row["width"]), row["topology"]): row for row in summary}
    styles = {
        "grid": (GRID_COLOR, "o", "Square grid"),
        "hex_lattice": (HEX_COLOR, "s", "Hexagonal lattice"),
    }
    panels = (
        (
            "postselection_shot_overhead_geomean_ratio_reduction",
            "(a) Postselection shot overhead",
            "Reduction (%)",
        ),
        (
            "conditional_infidelity_geomean_ratio_reduction",
            "(b) Conditional infidelity",
            "Reduction (%)",
        ),
    )

    with plt.style.context("lusca"):
        plt.rcParams.update(
            {
                "font.size": 7.0,
                "axes.labelsize": 7.2,
                "xtick.labelsize": 6.7,
                "ytick.labelsize": 6.7,
                "legend.fontsize": 6.8,
                "pdf.fonttype": 42,
            }
        )
        figure, axes = plt.subplots(1, 2, figsize=(3.35, 1.62))
        for axis, (metric, title, ylabel) in zip(axes, panels, strict=True):
            all_values = []
            for topology in TOPOLOGIES:
                color, marker, label = styles[topology]
                central = np.asarray(
                    [100.0 * lookup[(width, topology)][metric] for width in WIDTHS]
                )
                axis.plot(
                    WIDTHS,
                    central,
                    color=color,
                    marker=marker,
                    markersize=3.2,
                    linewidth=1.3,
                    label=label,
                )
                axis.annotate(
                    f"{central[-1]:.1f}",
                    (WIDTHS[-1], central[-1]),
                    xytext=(-3, 3),
                    textcoords="offset points",
                    ha="right",
                    fontsize=5.8,
                    color=color,
                )
                all_values.extend(central)
            axis.set_title(title, loc="left", fontsize=7.1)
            axis.set_xticks(WIDTHS)
            axis.set_xlabel("Logical qubits")
            axis.set_ylabel(ylabel)
            axis.set_ylim(0, max(all_values) * 1.2)
            axis.grid(color="#e1e1e1", linewidth=0.45)
            axis.set_axisbelow(True)
        handles, labels = axes[0].get_legend_handles_labels()
        figure.legend(
            handles,
            labels,
            loc="upper center",
            ncol=2,
            frameon=False,
            bbox_to_anchor=(0.5, 1.02),
        )
        figure.tight_layout(rect=(0, 0, 1, 0.84), pad=0.3, w_pad=0.4)

    pdf = OUT / f"{FIGURE_BASENAME}.pdf"
    png = OUT / f"{FIGURE_BASENAME}.png"
    paper_pdf = PAPER_ROOT / f"figures/{FIGURE_BASENAME}.pdf"
    figure.savefig(pdf, bbox_inches="tight", pad_inches=0.02)
    figure.savefig(png, dpi=300, bbox_inches="tight", pad_inches=0.02)
    plt.close(figure)
    if COPY_TO_PAPER:
        shutil.copyfile(pdf, paper_pdf)
    return pdf, png, paper_pdf


def _by_width() -> list[dict]:
    """Greedy against PRISM at every width in RAW, over the workloads complete at that width, with 95% paired seed intervals.

    Expected photon losses per shot are -ln P_keep. The shot ratio is Greedy's mean 1/P_keep over PRISM's. The viable set
    holds the workloads where Greedy keeps at least VIABLE_KEEP of its shots (research/rebuttal/scale/HEADLINE.md).
    """
    cells: dict = defaultdict(
        lambda: defaultdict(dict)
    )  # (width, topology) -> (workload, arm) -> seed -> losses
    for line in RAW.read_text().splitlines():
        row = json.loads(line)
        if (
            row.get("success")
            and row["circuit_name"] in BENCHMARKS
            and row["topology_name"] in TOPOLOGIES
        ):
            losses = row["pair_idle_us"] / T1_US - sum(
                n * math.log1p(-ERASURE[k]) for k, n in row["pair_touches"].items()
            )
            cells[(int(row["requested_n"]), row["topology_name"])][
                (row["circuit_name"], row["strategy"])
            ][int(row["outer_seed"])] = losses
    picks = np.random.default_rng(0).integers(0, len(SEEDS), (2000, len(SEEDS)))

    def geomean_ratio(a: np.ndarray, b: np.ndarray) -> tuple[float, float, float]:
        """Geomean over workloads of mean(b)/mean(a), with its paired seed interval."""
        point = math.exp(np.mean(np.log(b.mean(-1)) - np.log(a.mean(-1))))
        draws = np.exp(
            np.mean(np.log(b[:, picks].mean(-1)) - np.log(a[:, picks].mean(-1)), axis=0)
        )
        low, high = np.percentile(draws, [2.5, 97.5])
        return point, float(low), float(high)

    output = []
    for (width, topology), arms in sorted(cells.items()):
        workloads = [
            b
            for b in BENCHMARKS
            if all(set(arms.get((b, a), {})) == set(SEEDS) for a in ARMS)
        ]
        if not workloads:
            continue
        greedy, prism = (
            np.array([[arms[(b, a)][s] for s in SEEDS] for b in workloads])
            for a in ARMS
        )
        loss_ratio, loss_low, loss_high = geomean_ratio(greedy, prism)
        shots, shots_low, shots_high = geomean_ratio(np.exp(prism), np.exp(greedy))
        greedy_keep = 1 / np.exp(greedy).mean(-1)
        viable = greedy_keep >= VIABLE_KEEP
        entry = {
            "width": width,
            "topology": topology,
            "n_workloads": len(workloads),
            "loss_reduction": 1 - loss_ratio,
            "loss_reduction_ci_low": 1 - loss_high,
            "loss_reduction_ci_high": 1 - loss_low,
            "fewer_losses": int((prism.mean(-1) < greedy.mean(-1)).sum()),
            "greedy_over_prism_shots": shots,
            "shots_ci_low": shots_low,
            "shots_ci_high": shots_high,
            "greedy_keep_median": float(np.median(greedy_keep)),
            "greedy_keep_min": float(greedy_keep.min()),
            "greedy_keep_max": float(greedy_keep.max()),
            "n_viable": int(viable.sum()),
        }
        if viable.any():
            g, p = np.exp(greedy[viable]), np.exp(prism[viable])
            ratio, low, high = geomean_ratio(p, g)
            entry |= {
                "viable_shots": ratio,
                "viable_shots_ci_low": low,
                "viable_shots_ci_high": high,
                "viable_shots_max": float((g.mean(-1) / p.mean(-1)).max()),
            }
        output.append(entry)
    return output


def main() -> None:
    global RAW, OUT, FIGURE_BASENAME, COPY_TO_PAPER  # noqa: PLW0603

    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=RAW)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--figure-basename", default=FIGURE_BASENAME)
    parser.add_argument(
        "--quick", action="store_true", help="export the quick-profile rows"
    )
    args = parser.parse_args()
    if args.quick:
        args.raw = ROOT / "artifacts/paper/quick/scale.jsonl"
        args.out = ROOT / "artifacts/paper/quick_export/device"
        COPY_TO_PAPER = False
    RAW = args.raw if args.raw.is_absolute() else ROOT / args.raw
    OUT = args.out if args.out.is_absolute() else ROOT / args.out
    FIGURE_BASENAME = args.figure_basename
    OUT.mkdir(parents=True, exist_ok=True)
    rows = _read_rows()
    per_workload = _per_workload(rows)
    summary = _summarize(per_workload)
    for row in summary:
        row["greedy_matching_lifetime_increase"] = _matching_lifetime(
            rows, int(row["width"]), row["topology"]
        )
    per_workload_path = OUT / "per_workload.csv"
    summary_path = OUT / "summary.csv"
    _write_csv(per_workload_path, per_workload)
    _write_csv(summary_path, summary)
    _render(summary)
    _write_csv(OUT / "by_width.csv", _by_width())

    central_n16 = [row for row in summary if int(row["width"]) == 16]
    print(
        json.dumps(
            {
                "rows": len(rows),
                "per_workload_rows": len(per_workload),
                "summary_rows": len(summary),
                "n16": [
                    {
                        "topology": row["topology"],
                        "duration_reduction": row["duration_suite_total_reduction"],
                        "postselection_overhead_geomean_reduction": row[
                            "postselection_shot_overhead_geomean_ratio_reduction"
                        ],
                        "conditional_infidelity_reduction": row[
                            "conditional_infidelity_suite_total_reduction"
                        ],
                        "overall_success_probability_improvement": row[
                            "overall_success_probability_suite_mean_improvement"
                        ],
                    }
                    for row in central_n16
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
