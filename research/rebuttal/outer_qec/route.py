"""Route a qldpc memory experiment on dual-rail hardware and rebuild it in stim.

Usage: route.py CODE ROUNDS SEED [SEED ...]
Prints one JSON row per (topology, arm, seed). Each routed circuit is
converted back to a kept-shot logical stim circuit (MEHTA, postselected); building its
detector error model fails if any detector or observable is not
deterministic, i.e. if the routed circuit does not implement the experiment.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO / "src"), str(REPO / "scripts/paper")]

import stim  # noqa: E402
from qiskit.transpiler import CouplingMap  # noqa: E402

from paper_common import make_topologies  # noqa: E402
from marabbecca.encodings import DualRail  # noqa: E402
from marabbecca.lowering.commit import SearchBudget  # noqa: E402
from marabbecca.staged_pms import build_pm  # noqa: E402
from qec_circuits import experiment, to_qiskit  # noqa: E402
from to_stim import convert  # noqa: E402

ARMS = ["logical", "greedy", "prism"]
BUDGET = dict(heuristic_config="qiskit_sabre", tie_break="load",
              layout_starts=40, refinement_iterations=16, prism_swap_trials=40)


def compile_arm(qc, cmap, arm, seed):
    kw = {} if arm == "logical" else {
        "budget": SearchBudget(objective="error", **BUDGET), "objective": "error"}
    pm = build_pm(cmap, enc=DualRail, strategy=arm, seed=seed, **kw)
    return pm.run(qc), pm.property_set["circuit_metrics"]


def assemble(mem, routed, *, noise=True, erasure_sites=None) -> tuple[stim.Circuit, float]:
    """Remap the source experiment's measurements onto the converted routed circuit."""
    c, meas, p_keep, pair = convert(routed, mem.n_meas, mem.tags,
                                  noise=noise, erasure_sites=erasure_sites)
    ref = c.num_qubits  # noise-free reference qubits of a basis-None experiment
    qmap = {}
    for ins in list(mem.pre) + list(mem.post):
        for t in ins.targets_copy():
            if not (t.is_combiner or t.is_measurement_record_target) and t.value not in pair and t.value not in qmap:
                qmap[t.value] = ref + len(qmap)
    qmap.update(pair)

    def remap(block):
        out = stim.Circuit()
        for ins in block:
            targets = []
            for t in ins.targets_copy():
                if t.is_combiner or t.is_measurement_record_target:
                    targets.append(t)
                else:
                    q = qmap[t.value]
                    targets.append(stim.target_x(q) if t.is_x_target else stim.target_y(q) if t.is_y_target
                                   else stim.target_z(q) if t.is_z_target else q)
            out.append(ins.name, targets, ins.gate_args_copy())
        return out

    out = remap(mem.pre) + c + remap(mem.post)
    total = out.num_measurements
    idx = meas[: mem.n_meas] + list(range(c.num_measurements, total))  # body, then post (MPP)
    for recs in mem.detectors:
        out.append("DETECTOR", [stim.target_rec(idx[k] - total) for k in recs])
    for i, recs in sorted(mem.observables.items()):
        out.append("OBSERVABLE_INCLUDE", [stim.target_rec(idx[k] - total) for k in recs], i)
    return out, p_keep


def build(code, rounds, cmap, arm, seed):
    mem = to_qiskit(experiment(code, rounds))
    routed, metrics = compile_arm(mem.qc, cmap, arm, seed)
    circ, p_keep = assemble(mem, routed)
    circ.detector_error_model()
    return circ, metrics, p_keep


if __name__ == "__main__":
    code, rounds, seeds = sys.argv[1], int(sys.argv[2]), [int(s) for s in sys.argv[3:]]
    n = to_qiskit(experiment(code, rounds)).qc.num_qubits
    topos = make_topologies(n)
    topos["full"] = CouplingMap.from_full(2 * n)  # every pair adjacent: no routing
    for topo in ["full", "grid", "hex_lattice", "heavy_hex"]:
        for arm in ARMS:
            for seed in seeds:
                t0 = time.time()
                circ, m, p_keep = build(code, rounds, topos[topo], arm, seed)
                print(json.dumps(dict(code=code, rounds=rounds, n=n, topo=topo, arm=arm, seed=seed,
                                      swaps=m.swaps, depth=m.depth, duration=m.duration, p_keep=p_keep,
                                      secs=round(time.time() - t0, 2))), flush=True)
