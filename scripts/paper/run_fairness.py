"""Runner for core and controlled comparison studies.

One raw JSONL row per compiled arm instance. Work unit = one cell
(circuit, width, topology, seed); cells parallelize across --workers
processes. Resume is by deterministic run_id. Ladder configs (cost study)
expand prism start counts into separate rows.

  .venv/bin/python scripts/paper/run_fairness.py --config configs/paper/core.toml [--workers 12] [--dry-run] [--quick]

``--quick`` runs the config's ``quick_seeds`` (default: its first three seeds)
and ``quick_widths`` (default: its widths) into ``artifacts/paper/quick/``, for
iterating in minutes; the paper uses the full rows in ``artifacts/paper/raw/``.

Each arm is a ``build_pm`` strategy: ``logical`` (Logical-SABRE),
``greedy`` (Greedy) and ``prism`` (PRISM); ``prism_front_commit`` is the
front-layer-commit ablation of ``prism``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paper_common import CODE_REPO, make_topologies, run_id  # noqa: E402

sys.path.insert(0, str(CODE_REPO / "src"))

SCHEMA_VERSION = 5

# arm -> build_pm keyword arguments.
ARMS: dict[str, dict] = {
    "logical": {"strategy": "logical"},
    "greedy": {"strategy": "greedy"},
    "prism": {"strategy": "prism"},
    "prism_front_commit": {"strategy": "prism", "front_commit": True},
}
BUDGET_FIELDS = (
    "heuristic_config",
    "tie_break",
    "layout_starts",
    "refinement_iterations",
    "prism_swap_trials",
)


def _arm_spec_for_config(cfg: dict, arm: str) -> dict:
    """Apply explicit experiment-wide router settings to one arm."""
    from marabbecca.lowering.commit import SearchBudget

    spec = dict(ARMS[arm])
    # Logical-SABRE's quotient SabreLayout takes only the three counts; unset, they are the submitted 20/4/20.
    fields = BUDGET_FIELDS[2:] if spec["strategy"] == "logical" else BUDGET_FIELDS
    for field in fields:
        spec[field] = cfg.get(field, getattr(SearchBudget, field))
    if spec["strategy"] != "logical":
        # Commutation-relaxed routing needs the PRISM kernel.
        commute = cfg.get("commute_diagonal", False)
        spec["commute_diagonal"] = "best" if commute == "best" else bool(commute)
        spec["wait_scale"] = float(cfg.get("wait_scale", 0.0))
        spec["wait_realizations"] = bool(cfg.get("wait_realizations", True))
        spec["wait_mode"] = cfg.get("wait_mode", "additive")
    if spec.get("front_commit"):
        # False scores lookahead gates on the minimum, as PRISM does; true reproduces the submitted ablation.
        spec["front_commit_witness"] = bool(cfg.get("front_commit_witness", True))
    # Rescheduling runs after routing, so every arm takes it.
    spec["reschedule"] = bool(cfg.get("reschedule", False))
    return spec


CONTROL_FLOW_NAMES = {
    "if_else",
    "while_loop",
    "for_loop",
    "switch_case",
}


def _assert_no_machine_dependence() -> None:
    if os.environ.get("QISKIT_SABRE_ALL_THREADS"):
        raise SystemExit(
            "QISKIT_SABRE_ALL_THREADS is set; refusing (machine-dependent trials)"
        )
    from qiskit import user_config

    if user_config.get_config().get("sabre_all_threads"):
        raise SystemExit("Qiskit user config sabre_all_threads is set; refusing")


def _summarize_trace(trace: dict) -> dict:
    """Search budget, failed starts, the winning dependency rule, and each start's final score."""
    out = {
        k: trace[k]
        for k in (
            "max_iterations",
            "final_swap_trials",
            "n_failed_starts",
            "commute_won",
        )
        if k in trace
    }
    out["n_starts"] = len(trace["starts"])
    out["final_scores"] = [s.get("final_score") for s in trace["starts"]]
    return out


def _recursive_output_audit(
    qc,
    cmap,
) -> tuple[dict[str, int], dict[str, int], dict[str, int], list[dict], bool]:
    """Count nested operations and validate every concrete 2Q interaction."""
    from marabbecca.utils.metrics import is_synthetic_preparation

    counts: dict[str, int] = {}
    program_body_counts: dict[str, int] = {}
    synthetic_counts: dict[str, int] = {}
    violations: list[dict] = []
    edges = {tuple(sorted(edge)) for edge in cmap.get_edges()}
    has_control_flow = False

    def walk(circuit, physical_qubits: list[int]) -> None:
        nonlocal has_control_flow
        for instruction in circuit.data:
            name = instruction.operation.name
            counts[name] = counts.get(name, 0) + 1
            destination = (
                synthetic_counts
                if is_synthetic_preparation(instruction.operation)
                else program_body_counts
            )
            destination[name] = destination.get(name, 0) + 1
            mapped = [
                physical_qubits[circuit.find_bit(q).index] for q in instruction.qubits
            ]
            blocks = getattr(instruction.operation, "blocks", ())
            if blocks:
                has_control_flow = True
                for block in blocks:
                    if block is not None:
                        walk(block, mapped)
                continue
            if len(mapped) == 2 and name != "barrier":
                pair = tuple(sorted(mapped))
                if pair not in edges:
                    violations.append({"op": name, "pair": list(pair)})

    walk(qc, list(range(qc.num_qubits)))
    return (
        counts,
        program_body_counts,
        synthetic_counts,
        violations,
        has_control_flow,
    )


def _build_arm_pm(
    spec: dict,
    cmap,
    seed: int,
    objective: str,
    *,
    prism_starts=None,
):
    from marabbecca.encodings import DualRail
    from marabbecca.lowering.commit import SearchBudget
    from marabbecca.staged_pms import build_pm

    kwargs = dict(spec)
    budget = {field: kwargs.pop(field) for field in BUDGET_FIELDS if field in kwargs}
    if prism_starts is not None:
        budget["layout_starts"] = prism_starts
    kwargs["budget"] = SearchBudget(objective=objective, **budget)
    return build_pm(
        cmap,
        enc=DualRail,
        seed=seed,
        objective=objective,
        **kwargs,
    )


def _run_one(
    spec: dict,
    qc,
    cmap,
    seed: int,
    objective: str,
    *,
    prism_starts=None,
) -> dict:
    """Compile one arm instance; return the metric/instrumentation payload."""
    t0 = time.time()
    pm = _build_arm_pm(
        spec,
        cmap,
        seed,
        objective,
        prism_starts=prism_starts,
    )
    out_qc = pm.run(qc)
    ps = pm.property_set
    m = ps["circuit_metrics"]
    trace = ps.get("search_trace")
    choices = list(ps.get("realization_choices", ()))
    from marabbecca.encodings import DualRail
    from marabbecca.utils.metrics import FREE_GATES, GATE_DURATIONS

    top_level_op_counts = {
        name: int(count) for name, count in out_qc.count_ops().items()
    }
    (
        op_counts,
        program_body_op_counts,
        synthetic_preparation_counts,
        connectivity_violations,
        has_control_flow,
    ) = _recursive_output_audit(out_qc, cmap)
    duration_unmodeled = sorted(
        set(op_counts)
        - set(GATE_DURATIONS)
        - FREE_GATES
        - {
            "measure",
            "barrier",
            "reset",
            "delay",
            "if_else",
            "while_loop",
            "for_loop",
            "switch_case",
        }
    )
    if has_control_flow:
        # The current duration model schedules a static DAG only. It does not
        # assign latency to measurement-conditioned branches or classical
        # feed-forward, so a numeric duration would be misleading.
        duration_unmodeled.append("control_flow")
        duration_unmodeled = sorted(set(duration_unmodeled))
    allowed_ops = set(DualRail.PHYSICAL_ISA) | {
        "measure",
        "barrier",
        "reset",
        "delay",
        "if_else",
        "while_loop",
        "for_loop",
        "switch_case",
    }
    unexpected_ops = sorted(set(op_counts) - allowed_ops)
    logical_permutation = list(
        ps.get("logical_output_permutation", range(qc.num_qubits))
    )
    if out_qc.layout is None:
        physical_permutation = list(range(out_qc.num_qubits))
    else:
        physical_permutation = [int(p) for p in out_qc.layout.routing_permutation()]
    logical_permutation_valid = sorted(logical_permutation) == list(
        range(qc.num_qubits)
    )
    physical_permutation_valid = sorted(physical_permutation) == list(
        range(out_qc.num_qubits)
    )
    if unexpected_ops:
        raise RuntimeError(f"final circuit contains non-ISA ops: {unexpected_ops}")
    if connectivity_violations:
        raise RuntimeError(
            "final circuit violates physical connectivity: "
            f"{connectivity_violations[:5]}"
        )
    if not logical_permutation_valid or not physical_permutation_valid:
        raise RuntimeError("invalid logical or physical output permutation")

    payload = {
        "compile_time_s": round(time.time() - t0, 4),
        "final_swap_instructions": m.swaps,
        "active_gate_count": m.active_gates,
        "physical_depth": m.depth,
        "duration_ns": m.duration if not duration_unmodeled else None,
        "duration_unmodeled_ops": duration_unmodeled or None,
        "pair_idle_us": m.pair_idle_us if not duration_unmodeled else None,
        "pair_touches": m.pair_touches,
        "circuit_size": m.size,
        "final_op_counts": op_counts,
        "program_body_op_counts": program_body_op_counts,
        "synthetic_preparation_counts": synthetic_preparation_counts,
        "final_top_level_op_counts": top_level_op_counts,
        "control_flow_present": has_control_flow,
        "logical_output_permutation": logical_permutation,
        "logical_permutation_ops_elided": int(
            ps.get("logical_permutation_ops_elided", 0)
        ),
        "physical_routing_permutation": physical_permutation,
        "native_connectivity_valid": True,
        "native_isa_valid": True,
        "output_permutations_valid": True,
        "n_decisions_resolved": len(choices),
        "realization_choices": choices,
        "quotient_partition_pairs": (
            [list(pair) for pair in ps["quotient_partition_pairs"]]
            if ps.get("quotient_partition_pairs") is not None
            else None
        ),
        "quotient_graph_edges": (
            [list(edge) for edge in ps["quotient_graph_edges"]]
            if ps.get("quotient_graph_edges") is not None
            else None
        ),
        "quotient_graph_size": ps.get("quotient_graph_size"),
        "router_inserted_swaps": ps["routing_swaps"],
        "semantic_swap_instructions": ps["semantic_swaps"],
    }
    if trace is not None:
        payload["search_trace"] = _summarize_trace(trace)
        payload["lowering_wall_s"] = trace.get("wall_s")
    return payload


def _cell_rows(task: dict) -> list[dict]:
    """Run every (arm, variant) of one cell inside this worker process."""
    from qiskit import qpy

    cfg = task["cfg"]
    circuit, width = task["circuit"], task["width"]
    topology, seed = task["topology"], task["seed"]
    qpy_path = (
        CODE_REPO / "artifacts/paper/manifests/circuits" / f"{circuit}_n{width}.qpy"
    )
    with qpy_path.open("rb") as f:
        qc = qpy.load(f)[0]
    cmap = make_topologies(width)[topology]
    base = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": cfg["experiment_id"],
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "circuit_name": circuit,
        "requested_n": width,
        "topology_name": topology,
        "objective": cfg["objective"],
        "outer_seed": seed,
        "actual_n_logical": qc.num_qubits,
        "n_physical_rails": 2 * qc.num_qubits,
        "runner_workers": task["workers"],
    }
    if cmap.size() < 2 * qc.num_qubits:
        return [
            {
                **base,
                "run_id": rid,
                "strategy": arm,
                "success": False,
                "error_type": "capacity",
                "error_message": f"{cmap.size()} phys < {2 * qc.num_qubits} rails",
            }
            for arm, variant, rid in task["variants"]
        ]

    rows = []
    for arm, variant, rid in task["variants"]:
        row = {**base, "run_id": rid, "strategy": arm, **variant.get("row_extra", {})}
        spec = _arm_spec_for_config(cfg, arm)
        row["heuristic_config"] = spec.get("heuristic_config")
        row["tie_break"] = spec.get("tie_break")
        row["commute_diagonal"] = spec.get("commute_diagonal", False)
        row["reschedule"] = spec.get("reschedule", False)
        row["wait_scale"] = spec.get("wait_scale", 0.0)
        row["wait_realizations"] = spec.get("wait_realizations", True)
        row["wait_mode"] = spec.get("wait_mode", "additive")
        if "front_commit_witness" in spec:
            row["front_commit_witness"] = spec["front_commit_witness"]
        if spec["strategy"] == "logical":
            row["quotient_sabre_layout_trials"] = spec["layout_starts"]
            row["quotient_sabre_swap_trials"] = spec["prism_swap_trials"]
            row["quotient_sabre_refinement_iterations"] = spec["refinement_iterations"]
        try:
            kwargs = {}
            if "prism_starts" in variant:
                kwargs["prism_starts"] = variant["prism_starts"]
            row |= _run_one(spec, qc, cmap, seed, cfg["objective"], **kwargs)
            row |= {"success": True, "error_type": None, "error_message": None}
        except Exception as e:  # noqa: BLE001
            row |= {
                "success": False,
                "error_type": type(e).__name__,
                "error_message": (str(e)[:500] or type(e).__name__),
            }
            row.setdefault("compile_time_s", None)
            traceback.print_exc()
        rows.append(row)
    return rows


def _variants_for(cfg: dict, arm: str) -> list[tuple[str, dict]]:
    """Expand an arm into (variant-dict, run-id extras) per config ladders."""
    variants: list[dict] = []
    if arm == "prism" and "prism_starts" in cfg:
        for k in cfg["prism_starts"]:
            variants.append(
                {
                    "prism_starts": k,
                    "row_extra": {"ladder_starts": k},
                    "id_extra": {"starts": k},
                }
            )
    else:
        variants.append({"row_extra": {}, "id_extra": {}})
    return variants


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", default=None)
    parser.add_argument("--only", nargs="*", default=[])
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    _assert_no_machine_dependence()
    if args.workers < 1:
        raise SystemExit("--workers must be at least 1")

    cfg = tomllib.loads(args.config.read_text())
    for arm in cfg["arms"]:
        if arm not in ARMS:
            raise SystemExit(f"unknown arm {arm!r}; known: {sorted(ARMS)}")
    only = dict(kv.split("=", 1) for kv in args.only)
    if args.quick:
        cfg["seeds"] = cfg.get("quick_seeds", cfg["seeds"][:3])
        cfg["widths"] = cfg.get("quick_widths", cfg["widths"])

    out_path = (
        CODE_REPO
        / "artifacts/paper"
        / ("quick" if args.quick else "raw")
        / (args.out or f"{cfg['experiment_id']}.jsonl")
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = out_path.read_text().splitlines() if out_path.exists() else []
    done = {json.loads(line)["run_id"] for line in lines if line.strip()}
    tasks = []
    expected: set[str] = set()
    n_rows_total = 0
    keymap = {
        "circuit": "circuit",
        "width": "width",
        "topology": "topology",
        "seed": "seed",
    }
    for circuit in cfg["circuits"]:
        # Fixed-width circuits (QASMBench) name their own widths.
        for width in cfg.get("circuit_widths", {}).get(circuit, cfg["widths"]):
            for topology in cfg["topologies"]:
                for seed in cfg["seeds"]:
                    cell = {
                        "circuit": circuit,
                        "width": width,
                        "topology": topology,
                        "seed": seed,
                    }
                    if not all(str(cell[keymap[k]]) == v for k, v in only.items()):
                        continue
                    variants = []
                    for arm in cfg["arms"]:
                        for var in _variants_for(cfg, arm):
                            rid = run_id(
                                cfg["experiment_id"],
                                circuit_name=circuit,
                                requested_n=width,
                                topology_name=topology,
                                arm=arm,
                                objective=cfg["objective"],
                                outer_seed=seed,
                                **var["id_extra"],
                            )
                            variants.append((arm, var, rid))
                    n_rows_total += len(variants)
                    expected.update(rid for _, _, rid in variants)
                    if all(rid in done for _, _, rid in variants):
                        continue
                    tasks.append(
                        {
                            "cfg": cfg,
                            **cell,
                            "variants": variants,
                            "workers": args.workers,
                        }
                    )

    if args.dry_run:
        print(
            f"{n_rows_total} rows total, {len(done)} present, {len(tasks)} cells to run"
        )
        for t in tasks[:10]:
            print(
                "  ",
                t["circuit"],
                t["width"],
                t["topology"],
                t["seed"],
                [a for a, _, _ in t["variants"]],
            )
        if len(tasks) > 10:
            print(f"  ... and {len(tasks) - 10} more cells")
        return

    t_start = time.time()
    n_written = 0

    n_cells = 0

    def _write(rows):
        nonlocal n_written, n_cells
        n_cells += 1
        with out_path.open("a") as f:
            for row in rows:
                if row["run_id"] in done:
                    continue
                f.write(json.dumps(row, sort_keys=True) + "\n")
                done.add(row["run_id"])
                n_written += 1
        f_done = sum(1 for r in rows if not r.get("success"))
        print(
            f"{n_cells}/{len(tasks)} [{n_written}] {rows[0]['circuit_name']}(n{rows[0]['requested_n']}) "
            f"{rows[0]['topology_name']} seed={rows[0]['outer_seed']}: "
            f"{len(rows)} rows ({f_done} failed) "
            f"[{time.time() - t_start:.0f}s]",
            flush=True,
        )

    if args.workers <= 1:
        for task in tasks:
            _write(_cell_rows(task))
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            for rows in ex.map(_cell_rows, tasks, chunksize=1):
                _write(rows)
    print(f"done: {n_written} new rows -> {out_path}")
    lines = out_path.read_text().splitlines() if expected else []
    rows = [json.loads(line) for line in lines if line.strip()]
    bad = expected - {row["run_id"] for row in rows if row.get("success")}
    if bad:
        raise SystemExit(
            f"{len(bad)} of {len(expected)} declared rows missing or failed"
        )


if __name__ == "__main__":
    main()
