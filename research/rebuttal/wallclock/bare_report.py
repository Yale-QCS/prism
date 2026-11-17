"""Compare exact circuit fidelity, acceptance and duration at nominal width eight.

Run with --simulate --workers 3 once, then without --simulate to rebuild the report.
The dual-rail rows come from --dualrail (default `data/v3_n8.jsonl`, the MEHTA_IDLE
device; `data/v2_n8.jsonl` holds the superseded additive-dephasing rows).
Both platforms use ideal preparation and terminal measurement. Timing is A + B*h,
where h is the complete per-attempt overhead in microseconds, A = mean(D/P),
and B = mean(1/P). No fidelity-to-sampling-cost conversion is made.
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import argparse
import dataclasses
import hashlib
import json
import math
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from qiskit import qpy

import bare
import sim

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
WIDTH = 8
CZ_ERRORS = (0.001, 0.003)
TOPOLOGIES = ("grid", "hex_lattice")
SEEDS = (0, 100, 200, 300, 400)
ARMS = ("greedy", "prism")
EXACT = DATA / "bare_direct_n8.jsonl"
DUALRAIL = DATA / "v3_n8.jsonl"
NOISE_VERSION = "ideal-spam-rb-includes-gate-relaxation-v1"
# Provenance of the saved exact rows: bare.py, bare_n8.jsonl and sim.py as of 2026-10-08. The 2026-10-11
# sim.py change (MEHTA_IDLE) left simulate_bare and the bare state classes byte-identical.
EXACT_PROVENANCE = "640393a02406607b51a868191d813169f849cecec121a6fa2a9283dc7d4d540b"
SPAM_REJECTIONS = (0.0643, 0.0679)  # Mehta Table 3, one-round total SPAM erasure assignment.


def transmon_device(cz_error: float) -> sim.Device:
    """Match total gate error r after composing relaxation and residual depolarization."""
    t = dataclasses.replace(bare.CENTRAL, cz=cz_error, readout=0.0)
    residual = {}
    for gate, qubits, error in (("cz", 2, t.cz), ("sx", 1, t.sq), ("x", 1, t.sq)):
        duration = bare.DURATIONS[gate]
        thermal_fe = ((1 + math.exp(-duration/t.t1) + 2*math.exp(-duration/t.t2))/4)**qubits
        dimension = 2**qubits
        target_fe = 1 - (dimension+1)/dimension * error
        probability = (thermal_fe-target_fe)/(thermal_fe-1/dimension**2)
        assert 0 <= probability <= 1, "Gate error is below the chosen relaxation floor"
        residual[gate] = probability
    return dataclasses.replace(t.device(), depolarizing=residual)


def digest(path: Path) -> str:
    """SHA-256 of a source or result file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def key(row: dict) -> tuple:
    """Paired workload, topology and compiler seed."""
    return row["circuit"], row["topology"], row["seed"]


def selected_rows() -> list[dict]:
    """Require the complete paired suite; do not silently filter missing or costly rows."""
    rows = [json.loads(line) for line in (DATA / "bare_n8.jsonl").open()]
    rows = [r for r in rows if r["arm"] == "best40" and r["topology"] in TOPOLOGIES]
    expected = {(c, t, s) for c in bare.run.CFG["circuits"] for t in TOPOLOGIES for s in SEEDS}
    assert len(rows) == len(expected) and {key(r) for r in rows} == expected
    return rows


def simulate(row: dict, provenance: str) -> list[dict]:
    """Reconstruct a saved winner and simulate both CZ points with ideal SPAM."""
    from paper_common import make_topologies

    manifest = bare.REPO / f"artifacts/paper/manifests/circuits/{row['circuit']}_n8.qpy"
    with manifest.open("rb") as f:
        qc = qpy.load(f)[0].remove_final_measurements(inplace=False)
    circuit, logical = max(
        bare._transpile(qc, make_topologies(WIDTH)[row["topology"]], row["transpiler_seed"]),
        key=lambda pair: bare.log_esp(pair[0]),
    )
    assert math.isclose(bare.log_esp(circuit), row["log_esp"], abs_tol=1e-10)
    assert dict(circuit.count_ops()) == row["op_counts"]
    out = []
    for error in CZ_ERRORS:
        device = transmon_device(error)
        result = sim.simulate_bare(circuit, device, logical=logical)
        assert math.isclose(result["duration_us"], row["duration_us"], abs_tol=1e-10)
        assert result["fidelity_se"] == 0 and 0 <= result["fidelity"] <= 1 + 1e-10
        out.append({k: row[k] for k in ("circuit", "topology", "seed", "n_logical", "n_active", "transpiler_seed")} |
                   result | {"cz_error": error, "provenance": provenance, "manifest_sha256": digest(manifest)})
    return out


def summarize(rows: list[dict]) -> dict:
    """Mean quality and the two coefficients of time per retained sample."""
    return {
        "fidelity": float(np.mean([r["fidelity"] for r in rows])),
        "p_keep": float(np.mean([r["p_keep"] for r in rows])),
        "duration_us": float(np.mean([r["duration_us"] for r in rows])),
        "time_intercept_us": float(np.mean([r["duration_us"] / r["p_keep"] for r in rows])),
        "time_slope": float(np.mean([1 / r["p_keep"] for r in rows])),
    }


def spam_attempts(rows: list[dict], rejection: float) -> float:
    """Charge combined preparation/readout rejection once per actual encoded qubit."""
    return float(np.mean([1 / (r["p_keep"] * (1-rejection)**r["n_logical"]) for r in rows]))


def check() -> None:
    """Check total gate error through composed channels and nonlinear shot aggregation."""
    from qiskit.quantum_info import Kraus, average_gate_fidelity

    for error in CZ_ERRORS:
        device = transmon_device(error)
        for gate, k, target in (("cz", 2, error), ("sx", 1, bare.CENTRAL.sq)):
            t = device.durations[gate]
            survive = math.exp(-t/device.t1)
            pz = (1-math.exp(-device.dephasing*t))/2
            amp = [np.diag([1, math.sqrt(survive)]), np.array([[0, math.sqrt(1-survive)], [0, 0]])]
            phase = [math.sqrt(1-pz)*np.eye(2), math.sqrt(pz)*np.diag([1, -1])]
            channel = Kraus([p@a for p in phase for a in amp])
            if k == 2:
                channel = channel.tensor(channel)
            ops, weights = sim._pauli_mixture(k, device.depolarizing[gate])
            channel = channel.compose(Kraus([math.sqrt(w)*op for w, op in zip(weights, ops)]))
            assert math.isclose(1-average_gate_fidelity(channel), target, abs_tol=1e-12)
    result = summarize([dict(fidelity=1, p_keep=p, duration_us=d) for p, d in ((0.5, 2), (0.25, 3))])
    assert result["time_intercept_us"] == 8 and result["time_slope"] == 3
    # Different widths and acceptance expose double charging and averaging before inversion.
    rows = [dict(p_keep=0.5, n_logical=1), dict(p_keep=0.25, n_logical=2)]
    assert spam_attempts(rows, 0) == 3
    assert spam_attempts(rows, 0.5) == 10  # Mean of 4 and 16 attempts.


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--check", action="store_true", help="check channel and aggregation accounting, then exit")
    parser.add_argument("--dualrail", type=Path, default=DUALRAIL, help="exact dual-rail rows at width eight")
    parser.add_argument("--data-dir", type=Path, default=DATA, help="v2_n<width>.jsonl rows and the report; the transmon rows stay in data/")
    args = parser.parse_args()
    check()
    if args.check:
        print("Composed gate error, shot aggregation and single-charge SPAM checks pass")
        return
    rows = selected_rows()
    sources = {name: digest(HERE / name) for name in ("bare.py", "sim.py", "data/bare_n8.jsonl")}
    provenance = hashlib.sha256((json.dumps(sources, sort_keys=True)+NOISE_VERSION).encode()).hexdigest()
    exact = [json.loads(line) for line in EXACT.open()] if EXACT.exists() else []
    assert all(r["provenance"] in (provenance, EXACT_PROVENANCE) for r in exact), "Exact rows use different inputs"
    existing = {(key(r), r["cz_error"]) for r in exact}
    assert len(existing) == len(exact), "Duplicate exact rows"
    missing = [r for r in rows if any((key(r), e) not in existing for e in CZ_ERRORS)]
    if missing and not args.simulate:
        raise SystemExit(f"{len(missing)} cells missing; run --simulate --workers 3")
    if missing:
        with EXACT.open("a") as output, ProcessPoolExecutor(args.workers) as pool:
            futures = [pool.submit(simulate, r, provenance) for r in missing]
            for future in as_completed(futures):
                part = future.result()
                for r in part:
                    if (key(r), r["cz_error"]) not in existing:
                        output.write(json.dumps(r) + "\n")
                        exact.append(r)
                output.flush()
                print(f"exact cells {len(exact) // len(CZ_ERRORS)}/{len(rows)}", flush=True)
    assert len(exact) == len(rows) * len(CZ_ERRORS)
    manifests = {r["circuit"]: digest(bare.REPO / f"artifacts/paper/manifests/circuits/{r['circuit']}_n8.qpy") for r in rows}
    assert all(r["manifest_sha256"] == manifests[r["circuit"]] for r in exact)
    dr = [json.loads(line) for line in args.dualrail.open()]
    dr = [r for r in dr if r["arm"] in ARMS and r["topology"] in TOPOLOGIES]
    assert all(r["fidelity_se"] == 0 for r in dr)
    (dualrail_device,) = {r["device"] for r in dr}
    for arm in ARMS:
        paired = [r for r in dr if r["arm"] == arm]
        assert len(paired) == len(rows) and {key(r) for r in paired} == {key(r) for r in rows}
    workloads = {}
    for c in bare.run.CFG["circuits"]:
        groups = {arm: [r for r in dr if r["arm"] == arm and r["circuit"] == c] for arm in ARMS}
        groups |= {f"bare_{e}": [r for r in exact if r["circuit"] == c and r["cz_error"] == e] for e in CZ_ERRORS}
        assert all(len(g) == len(TOPOLOGIES) * len(SEEDS) for g in groups.values())
        workloads[c] = {arm: summarize(g) for arm, g in groups.items()}
    sources |= {name: digest(HERE / name) for name in ("data/bare_direct_n8.jsonl", "bare_report.py")}
    sources[str(args.dualrail.resolve().relative_to(HERE))] = digest(args.dualrail)
    acceptance_by_width = {}
    spam_by_width = {}
    for width in (8, 12, 16):
        path = args.data_dir / f"v2_n{width}.jsonl"
        wide = [json.loads(line) for line in path.open()]
        wide = [r for r in wide if r['arm'] == 'prism' and r['topology'] in TOPOLOGIES]
        assert len(wide) == len(rows) and {key(r) for r in wide} == {key(r) for r in rows}
        costs = {c: summarize([r for r in wide if r['circuit'] == c])['time_slope'] for c in workloads}
        acceptance_by_width[width] = costs
        spam_by_width[width] = {
            e: {c: spam_attempts([r for r in wide if r['circuit'] == c], e) for c in workloads}
            for e in SPAM_REJECTIONS
        }
        sources[str(path.resolve().relative_to(HERE))] = digest(path)
    for c, w in workloads.items():
        groups = {a: [r for r in dr if r['arm'] == a and r['circuit'] == c] for a in ARMS}
        assert len({r['n_logical'] for g in groups.values() for r in g}) == 1
        for e in SPAM_REJECTIONS:
            ratio = spam_attempts(groups['prism'], e) / spam_attempts(groups['greedy'], e)
            assert math.isclose(ratio, w['prism']['time_slope']/w['greedy']['time_slope'])
    report = {
        "width": WIDTH, "topologies": TOPOLOGIES, "seeds": SEEDS,
        "assumptions": "Ideal preparation and terminal checks on both platforms; exact state fidelity before readout. Independent local noise, uniform device parameters. One program per device. No mitigation-cost conversion.",
        "timing": "For per-attempt overhead h (preparation, checking, readout, reset), time per retained sample in us = time_intercept_us + time_slope * h. Platforms may have different h; no measured h is asserted.",
        "resources": "Same coupling graphs (20 grid sites, 30 hexagonal sites); a site is one cavity rail or one bare transmon. Eight program qubits except VBE's seven. Additional cavity control and readout hardware is not equated.",
        "transmon": dataclasses.asdict(dataclasses.replace(bare.CENTRAL, readout=0.0)),
        "cz_errors": CZ_ERRORS, "sources_sha256": sources, "workloads": workloads,
        "dualrail_rows": str(args.dualrail.resolve().relative_to(HERE)), "dualrail_device": dualrail_device,
        "noise_version": NOISE_VERSION,
        "residual_depolarizing": {e: transmon_device(e).depolarizing for e in CZ_ERRORS},
        "prism_attempts_by_width": acceptance_by_width,
        "spam_yield": {
            "source": "https://arxiv.org/html/2503.10935v2",
            "assumptions": "Yield-only sensitivity: multiply circuit acceptance by (1-e)^n once, using each circuit's actual encoded-qubit count. A uniform total SPAM rejection e is independent across qubits and of circuit loss. The endpoints are two measured qubits, not confidence bounds. No separate preparation/readout loss is charged; no SPAM-adjusted fidelity is inferred.",
            "rejections": SPAM_REJECTIONS,
            "prism_attempts_by_width": spam_by_width,
        },
    }
    (args.data_dir / "bare_report.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = ["Direct bare-transmon comparison, nominal width eight", report["assumptions"], report["timing"],
             f"Dual-rail rows {report['dualrail_rows']}, device {dualrail_device} (MODEL.md section 1).",
             "Each workload averages both topologies and five seeds. All 16 workloads retained.",
             "workload | arm | fidelity | acceptance | time per retained sample (us), h in us"]
    for c, arms in workloads.items():
        for arm, r in arms.items():
            lines.append(f"{c:24s} {arm:12s} {r['fidelity']:.6f} {r['p_keep']:.6f} {r['time_intercept_us']:.3f} + {r['time_slope']:.3f} h")
    for arm in next(iter(workloads.values())):
        values = [w[arm] for w in workloads.values()]
        lines.append(f"{arm}: median workload-mean F {np.median([r['fidelity'] for r in values]):.6f}; "
                     f"mean inverse acceptance range {min(r['time_slope'] for r in values):.3f} to {max(r['time_slope'] for r in values):.3f}")
    for h in (0, 20, 100):
        ratios = [(w['prism']['time_intercept_us'] + h*w['prism']['time_slope']) /
                  (w['greedy']['time_intercept_us'] + h*w['greedy']['time_slope']) for w in workloads.values()]
        lines.append(f"PRISM/Greedy time geomean at common illustrative overhead h={h} us: {math.exp(np.log(ratios).mean()):.6f}")
    # For each workload, (A_dr+B_dr*h)/(A_bare+h) lies between A_dr/A_bare and B_dr.
    assert all(w['prism']['time_intercept_us'] > w['bare_0.001']['time_intercept_us'] and
               w['prism']['time_slope'] > 1 for w in workloads.values())
    lines.append("At every common per-attempt overhead h >= 0, PRISM costs more time per retained sample than bare on every workload mean.")
    for width, costs in acceptance_by_width.items():
        lines.append(f"PRISM width {width}, all workloads: attempts median {np.median(list(costs.values())):.3f}, "
                     f"range {min(costs.values()):.3f} to {max(costs.values()):.3f}; {sum(x > 100 for x in costs.values())} above 100")
    lines.append(report['spam_yield']['assumptions'])
    for width, scenarios in spam_by_width.items():
        for e, costs in scenarios.items():
            lines.append(f"PRISM width {width}, SPAM rejection {100*e:.2f}%: attempts median {np.median(list(costs.values())):.3f}, "
                         f"range {min(costs.values()):.3f} to {max(costs.values()):.3f}")
    (HERE / "bare_report.txt" if args.data_dir == DATA else args.data_dir / "bare_report.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[-7:]))


if __name__ == "__main__":
    main()
