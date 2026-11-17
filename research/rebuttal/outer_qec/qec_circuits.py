"""Memory experiments from qldpc, as Qiskit circuits for routing.

Circuits, check schedules, detectors and observables are qldpc's
(``get_memory_experiment``, default EdgeColoring schedule). CSS codes use a
fixed-basis experiment, all of it routed. A non-CSS code (basis None) has
a noiseless encoder, entangling the code with a noise-free reference
qubit, and a noiseless MPP readout around its noisy QEC rounds; only the
rounds are routed, and the encoder and readout are kept as stim (``pre``,
``post``). Each data qubit then gets a tag measurement at the start of the
routed circuit, so its pair can be identified after routing. (At the end,
a Z measurement would let the compiler drop diagonal gates before it.)

Measurement k of the qldpc circuit is clbit k of the Qiskit circuit (MPP
products continue the count but are not in it); detectors and rec
observables are kept as absolute measurement indices.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import stim
from qiskit import QuantumCircuit
from qldpc import circuits, codes
from sympy.abc import x, y

# [[8,3,2]] colour code on a cube, vertex v = 4a + 2b + c: X on all 8
# vertices, Z on the faces (four independent ones).
_FACES = [(0, 0), (1, 0), (2, 0), (0, 1)]
CODES = {
    "steane": codes.SteaneCode,
    "c832": lambda: codes.CSSCode(
        np.ones((1, 8), int),
        np.array([[(v >> k & 1) == s for v in range(8)] for k, s in _FACES], int),
    ),
    "five": codes.FiveQubitCode,
    "surface": lambda: codes.SurfaceCode(3),  # rotated, [[9,1,3]]
    # [[18,4,4]] bivariate bicycle code (Liu et al., arXiv:2604.18714).
    "bb18": lambda: codes.BBCode({x: 3, y: 3}, 1 + x + y, 1 + y + x**2 * y),
}


def experiment(code: str, rounds: int, basis: str = "X") -> stim.Circuit:
    c = CODES[code]()
    basis = basis if isinstance(c, codes.CSSCode) else None
    return circuits.get_memory_experiment(c, basis=basis, num_rounds=rounds).flattened()


@dataclass
class Memory:
    qc: QuantumCircuit  # the routed part
    n_meas: int  # measurements in qc, excluding tags
    detectors: list[list[int]] = field(default_factory=list)
    observables: dict[int, list[int]] = field(default_factory=dict)
    pre: stim.Circuit = field(default_factory=stim.Circuit)  # noiseless, before qc
    post: stim.Circuit = field(default_factory=stim.Circuit)  # noiseless, after qc
    tags: dict[int, int] = field(default_factory=dict)  # tag clbit -> data qubit


def to_qiskit(circ: stim.Circuit) -> Memory:
    ops = [ins for ins in circ if ins.name not in ("QUBIT_COORDS", "TICK", "SHIFT_COORDS")]
    first_reset = next(i for i, ins in enumerate(ops) if ins.name in ("R", "RX"))
    readout = next((i for i, ins in enumerate(ops) if ins.name == "MPP"), len(ops))
    pre, body = ops[:first_reset], ops[first_reset:readout]
    body_qubits = {t.value for ins in body for t in ins.targets_copy() if t.is_qubit_target}
    n = max(body_qubits) + 1
    data = sorted({t.value for ins in pre for t in ins.targets_copy() if t.is_qubit_target} & body_qubits)
    n_meas = sum(1 for ins in body if ins.name in ("M", "MX") for _ in ins.targets_copy())
    qc = QuantumCircuit(n, n_meas + len(data))
    mem = Memory(qc, n_meas)
    for ins in pre:
        mem.pre.append(ins)
    touched: set[int] = set(data)  # encoded data qubits are in use from the start
    for i, q in enumerate(data):
        qc.measure(q, n_meas + i)
        mem.tags[n_meas + i] = q
    k = 0

    def fresh_reset(q):
        if q in touched:
            qc.reset(q)
        touched.add(q)

    for ins in ops[first_reset:]:
        name = ins.name
        if name == "MPP" or (name == "OBSERVABLE_INCLUDE" and not all(t.is_measurement_record_target for t in ins.targets_copy())):
            mem.post.append(ins)
            k += len(ins.target_groups()) if name == "MPP" else 0
            continue
        if name in ("DETECTOR", "OBSERVABLE_INCLUDE"):
            recs = [k + t.value for t in ins.targets_copy()]
            if name == "DETECTOR":
                mem.detectors.append(recs)
            else:
                mem.observables.setdefault(int(ins.gate_args_copy()[0]), []).extend(recs)
            continue
        qs = [t.value for t in ins.targets_copy()]
        if name in ("CX", "CZ"):
            for a, b in zip(qs[::2], qs[1::2]):
                getattr(qc, name.lower())(a, b)
                touched |= {a, b}
            continue
        for q in qs:
            if name == "R":
                fresh_reset(q)
            elif name == "RX":
                fresh_reset(q)
                qc.h(q)
            elif name in ("M", "MX"):
                if name == "MX":
                    qc.h(q)
                qc.measure(q, k)
                k += 1
                touched.add(q)
            elif name in ("H", "S"):
                getattr(qc, name.lower())(q)
                touched.add(q)
            else:
                raise ValueError(name)
    return mem
