"""Export the 25-workload suite (research/rebuttal/suite/README.md): 16 MQT Bench algorithms and randomcircuit at n = 8 plus
8 QASMBench circuits at native widths, 64 seeds per cell (0..1900 and 2000..6300, 100 apart).

Every suite-level statistic comes from here: per-cell reductions with 95% paired seed-bootstrap intervals, cell counts,
per-run losses, per-workload and per-topology distributions, equal-weight and summed aggregates, and the Logical-SABRE range.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import lusca  # noqa: F401
import matplotlib.pyplot as plt
from export_core import (
    ARM_COLORS,
    ARM_HATCHES,
    ARM_LABELS,
    BENCHMARK_LABELS,
    REGRESSION,
    TOPOLOGY_LABELS,
    _write_csv,
)
from paper_common import BOOTSTRAP_SAMPLES, bootstrap_interval

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "artifacts/paper/raw"
OUT = ROOT / "artifacts/paper/paper_export/suite"
TOPOLOGIES = ("grid", "hex_lattice", "heavy_hex")
METRICS = ("router_inserted_swaps", "physical_depth", "duration_ns")
# SWAP-selected rows (objective = "swaps", as the submission; research/rebuttal/suite/swaps/), 64 seeds 0..6300.
# The J-selected rows (core*.jsonl, breadth*.jsonl, randomcircuit*.jsonl) stay on disk as supporting evidence.
SOURCES = {
    "core_swaps.jsonl": "mqt",
    "breadth_swaps.jsonl": "qasmbench",
    "breadth_added_swaps.jsonl": "qasmbench",
    "randomcircuit_swaps.jsonl": "mqt",
}
# Logical-SABRE ignores the route-selection objective, so its J-run rows apply.
LOGICAL = (
    "logical.jsonl",
    "logical_qasmbench.jsonl",
    "logical_seeds64.jsonl",
    "logical_randomcircuit.jsonl",
)
MAX_SEED = 6300
# Excluded 2026-10-11 by the size clause in research/rebuttal/suite/README.md (762 two-qubit gates, 11x the suite median).
EXCLUDED = {"gcm_h6"}
# Logical-SABRE needs one matched rail pair per logical qubit; the 57-site heavy-hex lattice matches only 24.
NOT_PLACEABLE = {("knn", "heavy_hex")}


def equal_weight_interval(greedy: np.ndarray, prism: np.ndarray) -> tuple[float, float]:
    """95% interval of the mean per-workload reduction over (workload, seed) arrays, resampling seeds in pairs."""
    picks = np.random.default_rng(0).integers(
        0, greedy.shape[-1], (BOOTSTRAP_SAMPLES, greedy.shape[-1])
    )
    g, p = greedy[:, picks].sum(-1), prism[:, picks].sum(-1)
    with np.errstate(divide="ignore", invalid="ignore"):
        samples = np.nanmean(np.where(g > 0, 1.0 - p / g, np.nan), axis=0)
    low, high = np.nanpercentile(samples, [2.5, 97.5])
    return float(low), float(high)


def load(logical: tuple = LOGICAL) -> tuple[dict, dict, dict, list]:
    runs: dict = defaultdict(dict)  # (workload, topology) -> {(seed, arm): row}
    source, width, seeds = {}, {}, set()
    for name, src in SOURCES.items():
        for row in map(json.loads, (RAW / name).open()):
            if row["outer_seed"] > MAX_SEED or row["circuit_name"] in EXCLUDED:
                continue
            if not row["success"]:
                raise RuntimeError(f"failed row: {name} {row['run_id']}")
            key = (row["circuit_name"], row["topology_name"])
            runs[key][(row["outer_seed"], row["strategy"])] = row
            source[row["circuit_name"]], width[row["circuit_name"]] = (
                src,
                row["actual_n_logical"],
            )
            seeds.add(row["outer_seed"])
    for name in logical:
        for row in map(json.loads, (RAW / name).open()):
            if row["outer_seed"] > MAX_SEED or row["circuit_name"] in EXCLUDED:
                continue
            key = (row["circuit_name"], row["topology_name"])
            if not row["success"]:
                if key not in NOT_PLACEABLE:
                    raise RuntimeError(f"failed row: {name} {row['run_id']}")
                continue
            runs[key][(row["outer_seed"], "logical")] = row
    seeds = sorted(seeds)
    for (workload, topology), cell in runs.items():
        arms = ("greedy", "prism") + (
            () if (workload, topology) in NOT_PLACEABLE else ("logical",)
        )
        missing = [(s, a) for s in seeds for a in arms if (s, a) not in cell]
        if missing:
            raise RuntimeError(f"{workload} {topology}: missing {missing[:4]}")
    return runs, source, width, seeds


def values(cell: dict, seeds: list, arm: str, metric: str) -> np.ndarray | None:
    if metric == "logical_final_swaps":
        return np.array(
            [
                cell[(s, arm)]["final_swap_instructions"]
                - cell[(s, arm)]["semantic_swap_instructions"]
                for s in seeds
            ],
            float,
        )
    v = [cell[(s, arm)][metric] for s in seeds]
    return None if any(x is None for x in v) else np.array(v, float)


# Per-metric y range and ticks of the reduction panels; intervals below the range end in a marker.
Y_RANGE = {
    "router_inserted_swaps": ((-2.0, 100.0), (0, 25, 50, 75, 100)),
    "physical_depth": ((0.0, 25.0), (0, 10, 20)),
}
# A SWAP reduction is not drawn where Greedy averages fewer routing SWAPs than this (vbe and cdkm on the grid).
MIN_GREEDY_SWAPS = 1.0


def render_figure(
    cells: list, means: dict, out: Path, stem: str = "suite_figure"
) -> None:
    """Fig. 9: per-workload reductions (columns are topologies, rows are metrics) and, in a fourth column, each compiler's suite mean."""
    metrics = {
        "router_inserted_swaps": "routing SWAPs",
        "physical_depth": "physical depth",
    }
    short = {"router_inserted_swaps": "SWAPs", "physical_depth": "depth"}
    lookup = {(c["workload"], c["topology"]): c for c in cells}
    order = sorted(
        {c["workload"] for c in cells},
        key=lambda w: (lookup[(w, "grid")]["reduction_router_inserted_swaps"], w),
    )
    x = np.arange(len(order))
    with plt.style.context("lusca"):
        plt.rcParams.update(
            {
                "font.size": 6.6,
                "axes.labelsize": 6.8,
                "xtick.labelsize": 5.2,
                "ytick.labelsize": 6.0,
                "legend.fontsize": 6.0,
                "pdf.fonttype": 42,
            }
        )
        fig, axes = plt.subplots(
            2,
            4,
            figsize=(7.15, 3.0),
            gridspec_kw={
                "width_ratios": [1, 1, 1, 0.62],
                "wspace": 0.2,
                "hspace": 0.32,
            },
        )
        for row, (m, label) in enumerate(metrics.items()):
            for col, t in enumerate(TOPOLOGIES):
                ax = axes[row, col]
                (floor, top), ticks = Y_RANGE[m]
                red = np.array([100 * lookup[(w, t)][f"reduction_{m}"] for w in order])
                low = np.array([100 * lookup[(w, t)][f"low_{m}"] for w in order])
                high = np.array([100 * lookup[(w, t)][f"high_{m}"] for w in order])
                if m == "router_inserted_swaps":
                    few = np.array(
                        [
                            lookup[(w, t)]["greedy_router_inserted_swaps"]
                            < MIN_GREEDY_SWAPS
                            for w in order
                        ]
                    )
                    red[few], low[few], high[few] = np.nan, np.nan, np.nan
                clipped = (low < floor) & ~(red < floor)
                low = np.maximum(low, floor)
                ax.bar(
                    x,
                    red,
                    width=0.76,
                    color=np.where(red >= 0, ARM_COLORS["prism"], REGRESSION),
                    edgecolor="#303030",
                    linewidth=0.3,
                    zorder=3,
                )
                mid, top_end = (
                    np.maximum(red, floor),
                    np.maximum(high, floor),
                )  # a bar below the range keeps the part of its interval in range
                ax.errorbar(
                    x,
                    mid,
                    yerr=(mid - low, top_end - mid),
                    fmt="none",
                    ecolor="#303030",
                    elinewidth=0.5,
                    capsize=1.0,
                    capthick=0.5,
                    zorder=4,
                )
                ax.plot(
                    x[clipped],
                    low[clipped],
                    "v",
                    ms=2.2,
                    color="#303030",
                    zorder=5,
                    clip_on=False,
                )
                for k in np.flatnonzero(red < floor):
                    ax.plot(
                        x[k],
                        floor,
                        "v",
                        ms=3.6,
                        markerfacecolor=REGRESSION,
                        markeredgecolor=REGRESSION,
                        markeredgewidth=0.3,
                        zorder=10,
                        clip_on=False,
                    )
                    ax.annotate(
                        f"\u2212{-red[k]:.1f}",
                        (x[k], floor),
                        xytext=(0, 6.0),
                        textcoords="offset points",
                        ha="center",
                        va="bottom",
                        fontsize=5.0,
                        fontweight="bold",
                        color=REGRESSION,
                        zorder=6,
                    )
                ax.axhline(0, color="#777777", linewidth=0.5, zorder=2)
                ax.set_ylim(floor, top)
                ax.set_yticks(ticks)
                ax.set_xlim(-0.6, len(order) - 0.4)
                ax.set_title(
                    f"({'abcdefgh'[4 * row + col]}) {TOPOLOGY_LABELS[t]}, {label}",
                    loc="left",
                    fontsize=6.6,
                )
                ax.grid(axis="y", color="#e1e1e1", linewidth=0.45, zorder=0)
                ax.set_axisbelow(True)
                ax.set_xticks(
                    x,
                    [BENCHMARK_LABELS.get(w, w) for w in order] if row else [],
                    rotation=90,
                    fontsize=4.6,
                )
                ax.tick_params(axis="x", length=0)
                if col == 0:
                    ax.set_ylabel("PRISM reduction\nvs. Greedy (%)")
            ax = axes[row, 3]
            group = np.arange(len(TOPOLOGIES))
            for k, arm in enumerate(("logical", "greedy", "prism")):
                ax.bar(
                    group + (k - 1) * 0.26,
                    [means[(t, m, arm)] for t in TOPOLOGIES],
                    width=0.26,
                    color=ARM_COLORS[arm],
                    hatch=ARM_HATCHES[arm],
                    edgecolor="#303030",
                    linewidth=0.4,
                    label=ARM_LABELS[arm],
                    zorder=3,
                )
            ax.set_title(
                f"({'abcdefgh'[4 * row + 3]}) Mean {short[m]}", loc="left", fontsize=6.6
            )
            ax.set_xticks(
                group, ["Grid", "Hex", "Heavy-hex"] if row else [], rotation=0
            )
            ax.tick_params(axis="x", length=0)
            ax.grid(axis="y", color="#e1e1e1", linewidth=0.45, zorder=0)
            ax.set_axisbelow(True)
        handles, labels = axes[0, 3].get_legend_handles_labels()
        fig.legend(
            handles,
            labels,
            frameon=False,
            loc="lower right",
            bbox_to_anchor=(0.995, 0.0),
            fontsize=6.0,
            handlelength=1.4,
        )
        fig.subplots_adjust(left=0.08, right=0.99, top=0.94, bottom=0.2)
        fig.savefig(
            out / f"{stem}.pdf", metadata={"CreationDate": None, "ModDate": None}
        )
        fig.savefig(out / f"{stem}.png", dpi=300)
        plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--logical",
        nargs="+",
        default=LOGICAL,
        help="Logical-SABRE row files, relative to artifacts/paper/raw/ or absolute",
    )
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    out_dir = args.out
    runs, source, width, seeds = load(tuple(args.logical))
    workloads = sorted(width, key=lambda w: (source[w] != "mqt", width[w], w))
    out_dir.mkdir(parents=True, exist_ok=True)

    cells = []
    for w in workloads:
        for t in TOPOLOGIES:
            cell, entry = (
                runs[(w, t)],
                {
                    "workload": w,
                    "source": source[w],
                    "n_logical": width[w],
                    "topology": t,
                },
            )
            for m in METRICS:
                g, p = values(cell, seeds, "greedy", m), values(cell, seeds, "prism", m)
                if (
                    g is None
                ):  # duration is not modeled for classically controlled circuits
                    entry.update(
                        {
                            f"{k}_{m}": None
                            for k in ("greedy", "prism", "reduction", "low", "high")
                        }
                    )
                    continue
                low, high = bootstrap_interval(g[None], p[None])
                entry.update(
                    {
                        f"greedy_{m}": g.mean(),
                        f"prism_{m}": p.mean(),
                        f"low_{m}": low,
                        f"high_{m}": high,
                        f"reduction_{m}": 1.0 - p.sum() / g.sum() if g.sum() else 0.0,
                    }
                )
            cells.append(entry)
    _write_csv(out_dir / "per_cell.csv", cells)

    summary: dict = {
        "workloads": len(workloads),
        "cells": len(cells),
        "seeds": len(seeds),
        "paired_runs": len(cells) * len(seeds),
        "no_duration": sorted(
            {c["workload"] for c in cells if c["reduction_duration_ns"] is None}
        ),
        "not_placeable_logical": sorted(map(list, NOT_PLACEABLE)),
    }

    # Cell counts, per-run losses and distributions.
    for m in METRICS:
        block = {}
        for t in (*TOPOLOGIES, "all"):
            sel = [
                c
                for c in cells
                if (t == "all" or c["topology"] == t)
                and c[f"reduction_{m}"] is not None
            ]
            r = np.array([c[f"reduction_{m}"] for c in sel])
            gm, pm = (
                np.array([c[f"{a}_{m}"] for c in sel]) for a in ("greedy", "prism")
            )
            block[t] = {
                "cells": len(sel),
                "lower": int((pm < gm).sum()),
                "tied": int((pm == gm).sum()),
                "higher": int((pm > gm).sum()),
                "interval_above_0": int(sum(c[f"low_{m}"] > 0 for c in sel)),
                "interval_below_0": int(sum(c[f"high_{m}"] < 0 for c in sel)),
                "not_significant": [
                    f"{c['workload']}/{c['topology']}"
                    for c in sel
                    if not (c[f"low_{m}"] > 0)
                ],
                "cell_reduction_min_median_max": [
                    float(r.min()),
                    float(np.median(r)),
                    float(r.max()),
                ],
            }
        losses = [
            (cell[(s, "prism")][m] - cell[(s, "greedy")][m], w, t, s)
            for (w, t), cell in runs.items()
            for s in seeds
            if cell[(s, "greedy")][m] is not None
        ]
        worse = [x for x in losses if x[0] > 0]
        block["runs"] = {
            "paired": len(losses),
            "prism_higher": len(worse),
            "prism_lower": sum(x[0] < 0 for x in losses),
            "largest_loss": max(worse) if worse else None,
        }
        summary[m] = block

    distribution = []
    for w in workloads:
        entry = {"workload": w, "source": source[w]}
        for m in METRICS:
            per_run = [
                (cell[(s, "prism")][m], cell[(s, "greedy")][m])
                for t in TOPOLOGIES
                for cell in [runs[(w, t)]]
                for s in seeds
            ]
            if any(g is None for _, g in per_run):
                continue
            r = np.array([1 - p / g for p, g in per_run if g > 0])
            entry.update(
                {
                    f"min_{m}": r.min() if len(r) else None,
                    f"median_{m}": np.median(r) if len(r) else None,
                    f"max_{m}": r.max() if len(r) else None,
                    f"greedy_zero_runs_{m}": sum(g == 0 for _, g in per_run),
                }
            )
        distribution.append(entry)
    _write_csv(out_dir / "distribution.csv", distribution)

    # Suite aggregates per topology: equal weight (headline), sum over all workloads, sum over the 16 MQT workloads.
    def aggregate(arm_a: str, arm_b: str, metric: str, t: str, members: list) -> dict:
        members = [
            w for w in members if arm_a != "logical" or (w, t) not in NOT_PLACEABLE
        ]
        pairs = [
            (
                values(runs[(w, t)], seeds, arm_a, metric),
                values(runs[(w, t)], seeds, arm_b, metric),
            )
            for w in members
        ]
        pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
        A, B = np.array([a for a, _ in pairs]), np.array([b for _, b in pairs])
        sa, sb = A.mean(1), B.mean(1)
        eq = float(np.mean([1 - b / a for a, b in zip(sa, sb) if a > 0]))
        return {
            "workloads": len(pairs),
            "equal_weight": eq,
            "equal_weight_ci": equal_weight_interval(A, B),
            "sum": float(1 - sb.sum() / sa.sum()),
            "sum_ci": bootstrap_interval(A, B),
        }

    # The 16 MQT algorithms (without randomcircuit) keep continuity with the ablations and scaling of section 5.3.
    mqt = [w for w in workloads if source[w] == "mqt" and w != "randomcircuit"]
    summary["aggregate"] = {
        m: {
            t: {
                "suite": aggregate("greedy", "prism", m, t, workloads),
                "mqt16": aggregate("greedy", "prism", m, t, mqt),
            }
            for t in TOPOLOGIES
        }
        for m in METRICS
    }
    summary["logical"] = {}
    for m in ("router_inserted_swaps", "physical_depth", "duration_ns"):
        summary["logical"][m] = {
            t: {
                f"{arm}_vs_logical": aggregate("logical", arm, m, t, workloads)
                for arm in ("greedy", "prism")
            }
            for t in TOPOLOGIES
        }
    # The final-circuit count for Logical-SABRE (after the swap-before-measure cleanup) bounds the other end of the SWAP range.
    summary["logical"]["final_circuit_swaps"] = {}
    for t in TOPOLOGIES:
        out = {}
        for arm in ("greedy", "prism"):
            members = [w for w in workloads if (w, t) not in NOT_PLACEABLE]
            A = np.array(
                [
                    values(runs[(w, t)], seeds, "logical", "logical_final_swaps")
                    for w in members
                ]
            )
            B = np.array(
                [
                    values(runs[(w, t)], seeds, arm, "router_inserted_swaps")
                    for w in members
                ]
            )
            sa, sb = A.mean(1), B.mean(1)
            out[f"{arm}_vs_logical"] = {
                "equal_weight": float(
                    np.mean([1 - b / a for a, b in zip(sa, sb) if a > 0])
                ),
                "sum": float(1 - sb.sum() / sa.sum()),
            }
        summary["logical"]["final_circuit_swaps"][t] = out

    # Fig. 9: per-workload reductions and suite means. Logical-SABRE does not place knn on heavy-hex, so every compiler's
    # heavy-hex mean covers the workloads all three compiled.
    means = {}
    for t in TOPOLOGIES:
        common = [
            w
            for w in workloads
            if all(
                (seeds[0], a) in runs[(w, t)] for a in ("logical", "greedy", "prism")
            )
        ]
        for m in METRICS[:2]:
            for a in ("logical", "greedy", "prism"):
                means[(t, m, a)] = float(
                    np.mean([values(runs[(w, t)], seeds, a, m).mean() for w in common])
                )
    render_figure(cells, means, out_dir)
    summary["figure_means"] = {f"{t}/{m}/{a}": v for (t, m, a), v in means.items()}

    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=1, default=float) + "\n"
    )
    print(
        json.dumps(
            {
                k: summary[k]
                for k in ("workloads", "cells", "seeds", "paired_runs", "no_duration")
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
