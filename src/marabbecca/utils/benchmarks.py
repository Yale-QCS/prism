"""Benchmark sweep harness: fetch mqt-bench circuits, run each strategy, return metrics rows."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from qiskit.transpiler import CouplingMap, PassManager
from tqdm.auto import tqdm

if TYPE_CHECKING:
    from qiskit import QuantumCircuit

PMFactory = Callable[[CouplingMap], PassManager]

# MQT-bench circuits keyed to their structural class for per-class breakdowns.
# Order is canonical: ascending prism depth on grid_2xn at n=8.
CIRCUIT_CLASS: dict[str, str] = {
    "graphstate": "misc",
    "bv": "oracle",
    "dj": "oracle",
    "ghz_dynamic": "trivial",
    "ghz": "trivial",
    "qnn": "trivial",
    "qaoa": "variational",
    "wstate": "trivial",
    "draper_qft_adder": "arithmetic",
    "vqe_real_amp": "trivial",
    "vqe_su2": "trivial",
    "modular_adder": "arithmetic",
    "qft": "qft_phase",
    "qpeexact": "qft_phase",
    "qpeinexact": "qft_phase",
    "qftentangled": "qft_phase",
    "bmw_quark_copula": "misc",
    "bmw_quark_cardinality": "trivial",
    "hhl": "qft_phase",
    "ae": "qft_phase",
    "cdkm_ripple_carry_adder": "arithmetic",
    "full_adder": "arithmetic",
    "vqe_two_local": "variational",
    "rg_qft_multiplier": "arithmetic",
    "multiplier": "arithmetic",
    "randomcircuit": "misc",
}


def _fetch_with_fallback(
    name: str, requested: int, min_size: int = 2
) -> tuple[QuantumCircuit, int] | tuple[None, Exception | None]:
    """Fetch a benchmark, probing downward on size-constraint failure.

    Returns ``(qc, actual_size)`` or ``(None, last_exception)`` if no size in
    ``[min_size, requested]`` loads.
    """
    from mqt.bench import get_benchmark_alg

    last_err: Exception | None = None
    for s in range(requested, min_size - 1, -1):
        try:
            return get_benchmark_alg(benchmark=name, circuit_size=s), s
        except Exception as e:  # noqa: BLE001
            last_err = e
    return None, last_err


def run_suite(
    topologies: dict[str, CouplingMap],
    strategies: dict[str, PMFactory],
    *,
    suite: Iterable[tuple[str, int]],
    verbose: bool = True,
    trials: dict[str, int] | None = None,
    base_seed: int = 42,
    objective: str = "swaps",
) -> list[dict]:
    """Run each strategy over each (circuit, topology); one long-format row per combination.

    Each strategy's PassManager must publish ``CircuitMetrics`` to
    ``property_set["circuit_metrics"]``. Circuits exceeding ``2 * cmap.size()`` rails
    are skipped. When a benchmark rejects the requested size (e.g. half_adder needs
    odd n), the runner falls back to the nearest smaller valid size and records both
    ``requested_size`` and ``size`` on each row.

    ``trials`` makes the cross-strategy effort budget explicit: strategy ``s``
    runs ``trials.get(s, 1)`` seeded restarts (``seed=base_seed+i``, factories
    must accept ``seed=``) and keeps the best FINAL circuit by the ``objective``
    key (swaps-lex by default, matching prism's internal post-selection; see
    ``prism_routing.score``). ``elapsed_s`` then accounts the total across restarts. With
    ``trials=None`` (default) each factory runs once as bound (legacy path).
    """
    if objective not in {"swaps", "depth", "gates", "duration"}:
        raise ValueError(
            f"unknown objective {objective!r}; expected swaps | depth | gates | duration"
        )
    rows: list[dict] = []
    bar = tqdm(list(suite), desc="Benchmarks", unit="circuit", leave=True)
    for name, requested_size in bar:
        qc, actual = _fetch_with_fallback(name, requested_size)
        if qc is None:
            if verbose:
                bar.write(f"  {name}({requested_size}): SKIP fetch ({actual})")
            continue
        size = actual
        if verbose and size != requested_size:
            bar.write(
                f"  {name}({requested_size}→{size}): adjusted size to satisfy benchmark constraint"
            )

        n_phys = 2 * qc.num_qubits
        for topo_name, cmap in topologies.items():
            if cmap.size() < n_phys:
                if verbose:
                    bar.write(
                        f"  {name}({size}) [{topo_name}]: SKIP "
                        f"(map has {cmap.size()} qubits, need {n_phys})"
                    )
                continue
            line_parts: list[str] = []
            for strat_name, factory in strategies.items():
                n_restarts = 1 if trials is None else max(1, trials.get(strat_name, 1))
                best: tuple | None = None  # (key, metrics, seed)
                t0 = time.time()
                try:
                    for i in range(n_restarts):
                        if trials is None:
                            pm = factory(cmap)
                        else:
                            pm = factory(cmap, seed=base_seed + i)
                        pm.run(qc)
                        m = pm.property_set["circuit_metrics"]
                        if objective == "swaps":
                            key = (m.swaps, m.active_gates, m.depth)
                        elif objective == "gates":
                            key = (m.active_gates, m.depth)
                        elif objective == "duration":
                            key = (m.duration, m.active_gates)
                        else:
                            key = (m.depth, m.active_gates)
                        if best is None or key < best[0]:
                            best = (key, m, base_seed + i)
                    elapsed = time.time() - t0
                except Exception as e:  # noqa: BLE001
                    if verbose:
                        bar.write(
                            f"  {name}({size}) [{topo_name}, {strat_name}]: "
                            f"SKIP compile ({e})"
                        )
                    continue
                m = best[1]
                row = {
                    "circuit": name,
                    "size": size,
                    "requested_size": requested_size,
                    "topology": topo_name,
                    "strategy": strat_name,
                    "n_logical": qc.num_qubits,
                    "n_physical": n_phys,
                    "swaps": m.swaps,
                    "depth": m.depth,
                    "active_gates": m.active_gates,
                    "n_evaluated": m.n_evaluated,
                    "elapsed_s": elapsed,
                    "trials": n_restarts,
                    "seed": best[2] if trials is not None else None,
                }
                rows.append(row)
                line_parts.append(
                    f"{strat_name} s={row['swaps']:>4} d={row['depth']:>4}"
                )
            if verbose and line_parts:
                bar.write(f"  {name}({size}) [{topo_name}]: " + "  ".join(line_parts))
    return rows
