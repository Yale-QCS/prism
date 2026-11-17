"""Routed dual-rail rail circuit -> logical stim circuit with MEHTA noise.

Each pair's two rail contents are followed through swaps, so a swap is a
relabeling and logical qubit p is the pair p's content. Every other rail op
acts on the one-photon-per-pair codespace as a logical Clifford, computed
numerically from its rail unitary. Convention |0_L> = |01>, |1_L> = |10>
(wire 0 holds the photon for 1_L), wires set by each joint_herald.

Postselected effective model, per pair, from wallclock/sim.MEHTA. Photon
loss (each op's erasure by role, and idle loss at 1/T1 in the gaps between
the pair's ops) is not put in the circuit: kept shots are those with no loss
anywhere, and their probability P_keep is returned. The kept state is
undistorted (MODEL.md section 1), so the stim circuit carries only the
kept-shot errors: each op's residual Z and dephasing 2*gamma on the logical
coherence over all time (Z_ERROR).
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from functools import lru_cache

import numpy as np
import stim
from qiskit.quantum_info import Operator
from marabbecca.utils.metrics import is_synthetic_preparation

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "wallclock"))
import sim  # noqa: E402

DEVICE = sim.MEHTA


@lru_cache(maxsize=None)
def _logical_circuit(op_key, n_pairs: int, wires: tuple) -> stim.Circuit:
    """Logical action of a rail op. ``wires[i]`` = (pair, wire) of qarg i, or None."""
    name, params = op_key
    op = _OPS[op_key]
    # Local rails: both wires of every involved pair, then empty qargs.
    rails = [(p, w) for p in range(n_pairs) for w in (0, 1)]
    qpos = [rails.index(x) if x is not None else None for x in wires]
    extra = [i for i, x in enumerate(qpos) if x is None]
    for k, i in enumerate(extra):
        qpos[i] = len(rails) + k
    nr = len(rails) + len(extra)
    full = Operator(np.eye(2**nr)).compose(op, qargs=qpos).data
    # Codespace basis state for logical bits b: wire0 = b, wire1 = 1 - b.
    idx = []
    for b in range(2**n_pairs):
        occ = 0
        for p in range(n_pairs):
            bit = b >> p & 1
            occ |= bit << (2 * p) | (1 - bit) << (2 * p + 1)
        idx.append(occ)
    u = full[np.ix_(idx, idx)]
    assert np.allclose(u.conj().T @ u, np.eye(len(idx)), atol=1e-9), (name, params, wires)
    return stim.Tableau.from_unitary_matrix(u, endian="little").to_circuit("elimination")


_OPS: dict = {}


def convert(qc, n_logical_clbits: int, tags: dict[int, int] | None = None,
            *, noise=True, erasure_sites=None):
    """Return the kept-shot stim circuit, each logical clbit's stim measurement index, P_keep,
    and the pair holding each tagged qubit.

    ``tags`` maps logical clbit -> qubit for tag measurements: they only
    identify the measured pair, take no time and add nothing to the stim circuit.
    """
    tags = tags or {}
    tagged = {}
    c = stim.Circuit()
    at: list = [None] * qc.num_qubits  # rail -> (pair, wire)
    clock = [0.0] * qc.num_qubits
    last = {}  # pair -> time its noise is accounted to
    n_pairs = 0
    phys_meas = {}  # physical clbit -> (stim meas index, invert)
    measured_at = {}  # pair -> stim meas index of its current measurement
    n_meas = 0
    log_keep = 0.0

    def erase(p, prob):
        nonlocal log_keep
        log_keep += math.log1p(-prob)

    def advance(p, t, busy_from):
        """Idle loss over [last, busy_from], dephasing over [last, t]."""
        if not noise:
            return
        t0 = last[p]
        erase(p, 1 - math.exp(-max(0.0, busy_from - t0) / DEVICE.t1))
        pz = (1 - math.exp(-2 * DEVICE.dephasing * (t - t0))) / 2
        if pz > 0:
            c.append("Z_ERROR", [p], pz)
        last[p] = t

    for ins in qc.data:
        op = ins.operation
        name = op.name
        rails = [qc.find_bit(q).index for q in ins.qubits]
        if name == "barrier":
            continue
        if name == "measure" and qc.find_bit(ins.clbits[0]).index // 2 in tags:
            tagged[tags[qc.find_bit(ins.clbits[0]).index // 2]] = at[rails[0]][0]
            continue
        synthetic = is_synthetic_preparation(op)
        dur = 0.0 if synthetic or name not in DEVICE.durations else DEVICE.durations[name]
        start = max(clock[r] for r in rails)
        for r in rails:
            clock[r] = start + dur
        if name == "joint_herald":
            a, b = rails
            pa, pb = at[a], at[b]
            if pa is not None and pb is not None and pa[0] == pb[0]:
                p = pa[0]  # in-place reset of a measured pair
                advance(p, start, start)
                c.append("R", [p])
            else:
                p = n_pairs
                n_pairs += 1
                last[p] = start
            at[a], at[b] = (p, 0), (p, 1)
            measured_at.pop(p, None)
            continue
        if synthetic:
            continue
        if name == "measure":
            (r,) = rails
            p, w = at[r]
            if p not in measured_at:
                advance(p, start, start)
                c.append("M", [p])
                measured_at[p] = n_meas
                n_meas += 1
            phys_meas[qc.find_bit(ins.clbits[0]).index] = (measured_at[p], w == 1)
            continue
        touched = list(dict.fromkeys(at[r][0] for r in rails if at[r] is not None))
        for p in touched:
            if name != "swap":  # a swap relabels rails; it does not end a measurement
                measured_at.pop(p, None)
            advance(p, start + dur, start)
        if name == "swap":
            a, b = rails
            at[a], at[b] = at[b], at[a]
        else:
            key = (name, tuple(round(float(x), 9) for x in op.params))
            _OPS.setdefault(key, Operator(op))
            local = {p: i for i, p in enumerate(touched)}
            wires = tuple(None if at[r] is None else (local[at[r][0]], at[r][1]) for r in rails)
            sub = _logical_circuit(key, len(touched), wires)
            for inst in sub:
                c.append(inst.name, [touched[t.value] for t in inst.targets_copy()])
        if erasure_sites is not None and len(rails) == 2:
            assert name in ("crz", "rswap", "swap"), name
            tick = c.num_ticks
            c.append("TICK")
            erasure_sites.extend((tick, p, name) for p in touched)
        # Op noise: erasure per touched pair by role, residual Z per named rail.
        if noise and dur:
            roles = DEVICE.erasure.get(name, ())
            seen = set()
            for r, e in zip(rails, roles):
                if at[r] is not None and at[r][0] not in seen:
                    seen.add(at[r][0])
                    erase(at[r][0], e)
            for r, pz in zip(rails, DEVICE.pauli_z.get(name, ())):
                if at[r] is not None and pz > 0:
                    c.append("Z_ERROR", [at[r][0]], pz)
    # Tagged pairs idle until the routed part ends (the noiseless readout follows it).
    end = max(clock)
    for p in tagged.values():
        advance(p, end, end)
    # Logical clbit k reads physical clbit 2k (wire 0 of the lowered measure).
    return c, [phys_meas[2 * k][0] for k in range(n_logical_clbits)], math.exp(log_keep), tagged
