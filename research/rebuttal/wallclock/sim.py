"""Exact density-matrix simulation of routed dual-rail and bare circuits (P1, H1).

Dual-rail: every rail is a cavity whose photon decays at ``t1``. Lost-photon
branches are discarded by the terminal occupation check, so the kept state is
the no-jump branch. All dual-rail ISA gates conserve photon number, so the kept
state lives on at most 2^n occupation bitmasks and is simulated exactly as a
density matrix over those masks, whatever the rail count. Its trace is P_keep.

Bare transmon: one qubit per logical qubit, no erasure check; loss and dephasing
stay in the state. Simulated as a full density matrix over the active qubits.

Times are in microseconds.
"""

from __future__ import annotations

import dataclasses
import itertools
import math
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
from scipy import sparse
from qiskit import QuantumCircuit
from qiskit.quantum_info import DensityMatrix, Kraus, Operator, Pauli, Statevector, partial_trace

from marabbecca.utils.metrics import (
    DEPHASING_RATE_PER_US,
    RSWAP_ERROR,
    T1_CAVITY_US,
    is_synthetic_preparation,
)


@dataclass(frozen=True)
class Device:
    """Timing and noise of one physical element type."""

    name: str
    t1: float
    # Pure-dephasing coherence decay rate of one element (1/us).
    dephasing: float
    durations: dict[str, float]
    # Residual Z probability after a gate, on (qarg 0, qarg 1).
    pauli_z: dict[str, tuple[float, ...]] = field(default_factory=dict)
    # Depolarizing probability over all of a gate's qubits.
    depolarizing: dict[str, float] = field(default_factory=dict)
    # Photon-loss probability a gate adds on qarg 0 beyond cavity decay (the
    # SWS coupler); flagged on dual-rail, an undetected decay on bare.
    loss: dict[str, float] = field(default_factory=dict)
    # Measured erasure probability of a gate on each live pair it touches, by role
    # (qarg 0's pair, qarg 1's pair). If set, loss is pair-wide: it replaces the
    # gate's own decay and coupler loss, idle loss acts on each pair outside its
    # gates, and rails only dephase.
    erasure: dict[str, tuple[float, ...]] = field(default_factory=dict)
    # If set, background dephasing acts on each pair's logical coherence (at 2 x
    # ``dephasing``) only outside the gates that touch the pair, the gates' own
    # dephasing being the measured residual Z; otherwise each rail dephases at
    # ``dephasing`` for all of its time, gates included (the additive model).
    idle_dephasing: bool = False


# Mehta et al. (arXiv:2503.10935) cavity device as first modelled, as in metrics.device_success
# (kept so the rows before MEHTA stay reproducible; run.py and resim.py add coupler loss).
# Each rail dephases at the mean of the two echo times (4.0, 4.8 ms) read as a
# Pauli phase-flip time, so a dual-rail qubit's coherence time is 1/(2 gamma) =
# 2.2 ms. That lies between the two Ramsey times (3.1, 1.5 ms): a reading with
# no dynamical decoupling (none is applied), as on the transmon. The SWS residual is split by role
# (Table III: control Z 3.9e-4, target Z 1.1e-4); the X parts (<3e-6) and the
# logical bit-flip rate (1/520 ms) are omitted.
LEGACY = Device(
    name="legacy",
    t1=T1_CAVITY_US,
    dephasing=DEPHASING_RATE_PER_US,
    durations={"crz": 0.5, "rswap": 0.2, "swap": 0.2, "x": 0.2, "rx": 0.2, "rz": 0.0},
    pauli_z={"crz": (3.9e-4, 1.1e-4), "rswap": (RSWAP_ERROR,), "swap": (RSWAP_ERROR,), "rx": (RSWAP_ERROR,)},
)

# The same device calibrated to Mehta et al.'s measured erasure (MODEL.md section 2):
# idle loss at the rate-averaged cavity T1 of Table 2 (231, 411, 652, 342 us), and
# per-operation erasure from Table 3 on each live pair touched. CR_z: control
# 4.00e-3, target 0.96e-3. Beamsplitter (rswap, swap, rx): 7.2e-4, the mean of the
# control and target X-sqrt(X) values (8.56e-4, 5.92e-4). The values average over the
# experiment's states, so applying them whatever the state is an approximation.
# Dephasing, residuals and durations are unchanged.
_BEAMSPLITTER_ERASURE = (8.56e-4 + 5.92e-4) / 2
MEHTA = dataclasses.replace(
    LEGACY,
    name="mehta",
    t1=4 / (1 / 231 + 1 / 411 + 1 / 652 + 1 / 342),
    erasure={"crz": (4.00e-3, 0.96e-3)} | {g: (_BEAMSPLITTER_ERASURE,) * 2 for g in ("rswap", "swap", "rx")},
)

# The same device with background dephasing charged only while a pair idles
# (MODEL.md section 1). Mehta et al. identify the measured CZ Z errors as the
# gate's dephasing, so MEHTA charged in-gate dephasing twice. Rows after
# 2026-10-11 (`data/v3_*.jsonl`) use this device.
MEHTA_IDLE = dataclasses.replace(MEHTA, name="mehta_idle", idle_dephasing=True)

# A current fixed-frequency transmon device (IBM Heron class): T1 200 us,
# T2 130 us, CZ 68 ns at 3e-3, SX 32 ns at 2.5e-4. A SWAP is three CZs.
_T1_TRANSMON, _T2_TRANSMON, _CZ_ERROR = 200.0, 130.0, 3e-3
BARE_TRANSMON = Device(
    name="bare_transmon",
    t1=_T1_TRANSMON,
    dephasing=1.0 / _T2_TRANSMON - 1.0 / (2.0 * _T1_TRANSMON),
    durations={"cz": 0.068, "sx": 0.032, "x": 0.032, "rz": 0.0, "swap": 3 * 0.068 + 2 * 0.032},
    depolarizing={"cz": _CZ_ERROR, "sx": 2.5e-4, "x": 2.5e-4, "swap": 1 - (1 - _CZ_ERROR) ** 3},
)
BARE_TRANSMON_BASIS = ["cz", "sx", "x", "rz", "swap"]

# A stronger transmon point: T1 = T2 = 300 us, CZ at 1e-3 (SWAP = three CZs).
STRONG_TRANSMON = dataclasses.replace(
    BARE_TRANSMON,
    name="strong_transmon",
    t1=300.0,
    dephasing=1 / 300.0 - 1 / 600.0,
    depolarizing=BARE_TRANSMON.depolarizing | {"cz": 1e-3, "swap": 1 - (1 - 1e-3) ** 3},
)


class CodespaceState:
    """Kept dual-rail state, exact: density matrix and ideal vector over occupied-rail bitmasks."""

    def __init__(self, live: dict[int, int]) -> None:
        # Each live rail's content owns one mask bit; a swap moves contents, so it only relabels.
        self.bit = dict(live)
        self.masks = np.zeros(1, dtype=np.int64)
        self.rho = np.ones((1, 1), dtype=complex)
        self.ideal = np.ones(1, dtype=complex)

    def occupation(self, rail: int) -> np.ndarray:
        """Return each basis mask's occupation of ``rail`` (always 0 for a rail holding no live content)."""
        b = self.bit.get(rail)
        return np.zeros(len(self.masks), dtype=np.int64) if b is None else (self.masks >> b) & 1

    def flip(self, rail: int) -> None:
        """Apply X on ``rail`` (a relabeling of the masks)."""
        self.masks = self.masks ^ (1 << self.bit[rail])

    def swap(self, a: int, b: int) -> None:
        """Exchange the contents of two rails."""
        ba, bb = self.bit.pop(a, None), self.bit.pop(b, None)
        if ba is not None:
            self.bit[b] = ba
        if bb is not None:
            self.bit[a] = bb

    def phase(self, d: np.ndarray) -> None:
        """Apply a diagonal unitary given as one phase per mask."""
        self.rho *= np.outer(d, d.conj())
        self.ideal *= d

    def coherence(self, rail: int, factor: float) -> None:
        """Scale coherences between masks that differ on ``rail`` (a Z with probability (1 - factor) / 2)."""
        a = self.occupation(rail)
        self.rho *= np.where(a[:, None] != a[None, :], factor, 1.0)

    def damp(self, rail: int, survival: float) -> None:
        """Keep the branch in which a photon on ``rail`` survives with probability ``survival``."""
        f = np.where(self.occupation(rail) == 1, math.sqrt(survival), 1.0)
        self.rho *= np.outer(f, f)

    def relax(self, rail: int, t: float, device: Device) -> None:
        """Keep the no-loss branch of ``t`` of cavity decay and dephase ``rail`` (dephase only under pair-wide loss)."""
        if t > 0:
            if not device.erasure:
                self.damp(rail, math.exp(-t / device.t1))
            if not device.idle_dephasing:
                self.coherence(rail, math.exp(-device.dephasing * t))

    def scale(self, survival: float) -> None:
        """Keep the branch in which one pair keeps its photon, with probability ``survival`` whatever its state."""
        self.rho *= survival

    def _sparse(self, matrix: np.ndarray, rails: list[int]) -> sparse.csr_matrix:
        """Build a one- or two-rail unitary on the mask basis and update the masks to its image."""
        bits = [self.bit[r] for r in rails]
        local = sum(self.occupation(r) << i for i, r in enumerate(rails))
        cleared = self.masks & ~sum(1 << b for b in bits)
        cols, outs, amps = [], [], []
        for lout in range(2 ** len(rails)):
            amp = matrix[lout, local]
            hit = np.abs(amp) > 1e-14
            cols.append(np.flatnonzero(hit))
            outs.append(cleared[hit] | sum(((lout >> i) & 1) << b for i, b in enumerate(bits)))
            amps.append(amp[hit])
        masks, rows = np.unique(np.concatenate(outs), return_inverse=True)
        u = sparse.csr_matrix((np.concatenate(amps), (rows, np.concatenate(cols))), shape=(len(masks), len(self.masks)))
        self.masks = masks
        return u

    def unitary(self, matrix: np.ndarray, rails: list[int]) -> None:
        """Apply a one- or two-rail unitary (qiskit order: ``rails[0]`` is the low bit)."""
        u = self._sparse(matrix, rails)
        self.rho = (u @ (u @ self.rho).conj().T).conj().T
        self.ideal = u @ self.ideal

    def result(self) -> tuple[float, float, float]:
        """Return P_keep, the conditional state fidelity and its standard error (0 when exact)."""
        p_keep = float(np.trace(self.rho).real)
        return p_keep, float((self.ideal.conj() @ self.rho @ self.ideal).real) / p_keep, 0.0


class CodespaceTrajectories(CodespaceState):
    """Kept dual-rail state as a batch of trajectories; the no-loss branch stays exact, Z errors are sampled."""

    def __init__(self, live: dict[int, int], shots: int, rng: np.random.Generator) -> None:
        super().__init__(live)
        self.rng = rng
        self.psi = np.ones((shots, 1), dtype=complex)

    def phase(self, d: np.ndarray) -> None:
        self.psi *= d
        self.ideal *= d

    def coherence(self, rail: int, factor: float) -> None:
        hit = self.rng.random(len(self.psi)) < (1 - factor) / 2
        if hit.any():
            self.psi[hit] *= 1 - 2 * self.occupation(rail)

    def damp(self, rail: int, survival: float) -> None:
        self.psi *= np.where(self.occupation(rail) == 1, math.sqrt(survival), 1.0)

    def scale(self, survival: float) -> None:
        self.psi *= math.sqrt(survival)

    def unitary(self, matrix: np.ndarray, rails: list[int]) -> None:
        u = self._sparse(matrix, rails)
        self.psi = (u @ self.psi.T).T
        self.ideal = u @ self.ideal

    def result(self) -> tuple[float, float, float]:
        # Z errors are unitary, so every trajectory carries the same no-loss weight.
        p_keep = float(np.vdot(self.psi[0], self.psi[0]).real)
        overlaps = np.abs(self.psi @ self.ideal.conj()) ** 2 / p_keep
        return p_keep, float(overlaps.mean()), float(overlaps.std(ddof=1) / math.sqrt(len(overlaps)))


def live_pairs(qc: QuantumCircuit) -> tuple[dict[int, int], set[int], dict[int, int]]:
    """Find the prepared pairs that take part in a gate other than swap or the preparation itself.

    Returns a mask bit for each rail that starts holding live content, the
    instruction indices that prepare idle pairs, and the pair of each mask bit
    (the two contents a joint herald joins). Logical-SABRE prepares every
    quotient pair, including ones no program qubit ever occupies. Content is
    followed through swaps, so a pair counts as live wherever it moves.
    """
    where = {q: q for q in range(qc.num_qubits)}  # position -> original rail of the content there
    parent = list(range(qc.num_qubits))

    def root(r: int) -> int:
        while parent[r] != r:
            parent[r] = parent[parent[r]]
            r = parent[r]
        return r

    used, preps = set(), []
    for i, ins in enumerate(qc.data):
        op, rails = ins.operation, [qc.find_bit(q).index for q in ins.qubits]
        if op.name == "swap":
            a, b = rails
            where[a], where[b] = where[b], where[a]
        elif op.name == "joint_herald":
            parent[root(where[rails[0]])] = root(where[rails[1]])
            preps.append((i, where[rails[0]]))
        elif is_synthetic_preparation(op):
            preps.append((i, where[rails[0]]))
        elif op.name != "barrier":
            used.update(where[r] for r in rails)
    live_roots = {root(r) for r in used}
    live = sorted(r for r in range(qc.num_qubits) if root(r) in live_roots)
    pair = {i: sorted(live_roots).index(root(r)) for i, r in enumerate(live)}
    return {r: i for i, r in enumerate(live)}, {i for i, r in preps if root(r) not in live_roots}, pair


def apply_gate(state: CodespaceState, op, rails: list[int]) -> None:
    """Apply one rail-circuit instruction to a codespace state, without noise."""
    if op.name == "joint_herald":
        return
    if op.name == "x":
        state.flip(rails[0])
    elif op.name == "swap":
        state.swap(*rails)
    elif op.name == "rz":
        theta = float(op.params[0])
        state.phase(np.exp(0.5j * theta * (2 * state.occupation(rails[0]) - 1)))
    elif op.name == "crz":
        theta = float(op.params[0])
        target = np.exp(0.5j * theta * (2 * state.occupation(rails[1]) - 1))
        state.phase(np.where(state.occupation(rails[0]) == 1, target, 1.0))
    else:
        state.unitary(Operator(op).data, rails)


# Operations that commute with a pair's logical dephasing: diagonal ones, X (a relabeling) and content moves.
_Z_COMMUTING = {"joint_herald", "x", "swap", "rz", "crz"}


def idle_time(intervals: list[tuple[float, float]], start: float, end: float) -> float:
    """Length of [start, end] not covered by the union of ``intervals``."""
    covered, reach = 0.0, start
    for a, b in sorted(intervals):
        covered += max(0.0, min(b, end) - max(a, reach))
        reach = max(reach, b)
    return end - start - covered


def simulate_dualrail(qc: QuantumCircuit, device: Device = MEHTA, shots: int | None = None, seed: int | list[int] = 0) -> dict:
    """Return P_keep, conditional state fidelity and duration of a routed rail circuit.

    ``shots=None`` is exact; otherwise the fidelity is a mean over ``shots`` trajectories,
    run in batches that keep the trajectory array near 128 MB.
    """
    live, idle, pair = live_pairs(qc)
    batch = max(1, (1 << 23) >> (len(live) // 2))
    if shots is not None and shots > batch:
        parts = [simulate_dualrail(qc, device, min(batch, shots - k), [seed, k]) for k in range(0, shots, batch)]
        sizes = [min(batch, shots - k) for k in range(0, shots, batch)]
        fidelity = sum(m * r["fidelity"] for m, r in zip(sizes, parts)) / shots
        se = math.sqrt(sum((m * r["fidelity_se"]) ** 2 for m, r in zip(sizes, parts))) / shots
        return parts[0] | {"fidelity": fidelity, "fidelity_se": se}
    state = CodespaceState(live) if shots is None else CodespaceTrajectories(live, shots, np.random.default_rng(seed))
    clock: dict[int, float] = defaultdict(float)
    # Under pair-wide loss, each live pair loses its photon at 1/t1 outside the gates that touch it.
    busy = {p: [] for p in pair.values()}  # pair -> (start, end) of the gates that touch it
    # Under idle dephasing, each pair's logical coherence decays at 2 gamma over the same idle time. The
    # decay commutes with every operation but a beamsplitter on the pair, so it is applied to the pair
    # just before each of those and at the end, for the idle time since the last such point.
    dephased = {p: 0.0 for p in pair.values()}  # pair -> time up to which its idle dephasing is applied
    for i, instruction in enumerate(qc.data):
        op = instruction.operation
        if op.name == "barrier" or i in idle:
            continue
        rails = [qc.find_bit(q).index for q in instruction.qubits]
        start = max(clock[r] for r in rails)
        for r in rails:
            state.relax(r, start - clock[r], device)
        if device.idle_dephasing and op.name not in _Z_COMMUTING:
            for p, r in {pair[state.bit[r]]: r for r in rails if r in state.bit}.items():
                state.coherence(r, math.exp(-2 * device.dephasing * idle_time(busy[p], dephased[p], start)))
                dephased[p] = start
        synthetic = is_synthetic_preparation(op)
        apply_gate(state, op, rails)
        duration = 0.0 if synthetic else device.durations[op.name]
        for r in rails:
            state.relax(r, duration, device)
        if not synthetic:
            for r, p in zip(rails, device.pauli_z.get(op.name, ())):
                state.coherence(r, 1 - 2 * p)
            if op.name in device.loss and not device.erasure:
                state.damp(rails[0], 1 - device.loss[op.name])
            if op.name in device.erasure:
                touched = {}  # pair -> erasure of its first role
                for r, e in zip(rails, device.erasure[op.name]):
                    if r in state.bit:
                        touched.setdefault(pair[state.bit[r]], e)
                for p, e in touched.items():
                    state.scale(1 - e)
                    busy[p].append((start, start + duration))
        for r in rails:
            clock[r] = start + duration
    end = max(clock.values())
    for r in list(clock):
        state.relax(r, end - clock[r], device)
    if device.erasure:
        for intervals in busy.values():
            state.scale(math.exp(-idle_time(intervals, 0.0, end) / device.t1))
    if device.idle_dephasing:
        for p, r in {pair[b]: r for r, b in state.bit.items()}.items():
            state.coherence(r, math.exp(-2 * device.dephasing * idle_time(busy[p], dephased[p], end)))
    p_keep, fidelity, fidelity_se = state.result()
    return {"p_keep": p_keep, "fidelity": fidelity, "fidelity_se": fidelity_se, "duration_us": end, "device": device.name}


def schedule_duration(qc: QuantumCircuit, device: Device) -> float:
    """Return the as-soon-as-possible critical-path duration of ``qc`` on ``device``."""
    finish: dict[int, float] = defaultdict(float)
    for ins in qc.data:
        if ins.operation.name == "barrier":
            continue
        qubits = [qc.find_bit(q).index for q in ins.qubits]
        end = max(finish[q] for q in qubits) + device.durations[ins.operation.name]
        for q in qubits:
            finish[q] = end
    return max(finish.values(), default=0.0)


_Z = np.diag([1.0, -1.0]).astype(complex)


def _pauli_mixture(k: int, p: float) -> tuple[list[np.ndarray], list[float]]:
    """``k``-qubit depolarizing channel with probability ``p`` as Paulis and weights."""
    labels = ["".join(s) for s in itertools.product("IXYZ", repeat=k)]
    return [Pauli(label).to_matrix() for label in labels], [1 - p + p / 4**k] + [p / 4**k] * (len(labels) - 1)


class BareExact:
    """Bare-device state as a density matrix."""

    def __init__(self, n: int) -> None:
        self.rho = DensityMatrix.from_label("0" * n)

    def unitary(self, matrix: np.ndarray, qubits: list[int]) -> None:
        self.rho = self.rho.evolve(Operator(matrix), qubits)

    def kraus(self, ops: list[np.ndarray], qubits: list[int]) -> None:
        self.rho = self.rho.evolve(Kraus(ops), qubits)

    def damp(self, q: int, gamma: float) -> None:
        self.kraus([np.diag([1, math.sqrt(1 - gamma)]).astype(complex), np.array([[0, math.sqrt(gamma)], [0, 0]], dtype=complex)], [q])

    def mixture(self, unitaries: list[np.ndarray], weights: list[float], qubits: list[int]) -> None:
        self.kraus([math.sqrt(w) * u for u, w in zip(unitaries, weights)], qubits)

    def fidelity(self, ideal: np.ndarray) -> tuple[float, float]:
        return float((ideal.conj() @ self.rho.data @ ideal).real), 0.0


class BareTrajectories:
    """Bare-device state as a batch of normalized trajectories with sampled Kraus branches."""

    def __init__(self, n: int, shots: int, rng: np.random.Generator) -> None:
        self.n, self.rng = n, rng
        self.psi = np.zeros((shots, 2**n), dtype=complex)
        self.psi[:, 0] = 1
        self.bits = [(np.arange(2**n) >> q) & 1 for q in range(n)]

    def _apply(self, matrix: np.ndarray, qubits: list[int], psi: np.ndarray) -> np.ndarray:
        """Apply a ``len(qubits)``-qubit matrix (qiskit order) to every row of ``psi``."""
        k, shots = len(qubits), len(psi)
        axes = [1 + self.n - 1 - q for q in reversed(qubits)]
        t = np.moveaxis(psi.reshape(shots, *[2] * self.n), axes, range(self.n + 1 - k, self.n + 1))
        shape = t.shape
        t = (t.reshape(-1, 2**k) @ matrix.T).reshape(shape)
        return np.moveaxis(t, range(self.n + 1 - k, self.n + 1), axes).reshape(shots, -1)

    def unitary(self, matrix: np.ndarray, qubits: list[int]) -> None:
        d = np.diag(matrix)
        if np.allclose(matrix, np.diag(d)):
            self.psi *= d[sum(self.bits[q] << i for i, q in enumerate(qubits))]
        else:
            self.psi = self._apply(matrix, qubits, self.psi)

    def damp(self, q: int, gamma: float) -> None:
        """Sample amplitude damping on ``q``: a decay moves |1> to |0>, otherwise the |1> part shrinks."""
        src = np.flatnonzero(self.bits[q])
        jump = self.rng.random(len(self.psi)) < gamma * (np.abs(self.psi[:, src]) ** 2).sum(axis=1)
        decayed = np.zeros_like(self.psi[jump])
        decayed[:, src ^ (1 << q)] = self.psi[jump][:, src]
        self.psi[:, src] *= math.sqrt(1 - gamma)
        self.psi[jump] = decayed
        self.psi /= np.linalg.norm(self.psi, axis=1, keepdims=True)

    def mixture(self, unitaries: list[np.ndarray], weights: list[float], qubits: list[int]) -> None:
        pick = self.rng.choice(len(unitaries), size=len(self.psi), p=np.array(weights) / sum(weights))
        for j in np.unique(pick):
            if j:
                rows = pick == j
                self.psi[rows] = self._apply(unitaries[j], qubits, self.psi[rows])

    def fidelity(self, ideal: np.ndarray) -> tuple[float, float]:
        """Return the mean trajectory fidelity and its standard error."""
        values = np.abs(self.psi @ ideal.conj()) ** 2
        return float(values.mean()), float(values.std(ddof=1) / math.sqrt(len(values)))


def simulate_bare(qc: QuantumCircuit, device: Device, shots: int | None = None, seed: int = 0,
                  logical: list[int] | None = None, readout: float = 0.0) -> dict:
    """Return the state fidelity and duration of a routed bare circuit over its active qubits.

    ``shots=None`` is exact; otherwise the fidelity is a mean over ``shots`` trajectories.
    ``logical`` (the physical qubits holding the program's qubits at the end) makes the fidelity that of
    their reduced state, after an X flip with probability ``readout`` on each of them.
    """
    active = sorted({qc.find_bit(q).index for ins in qc.data if ins.operation.name != "barrier" for q in ins.qubits})
    index = {p: i for i, p in enumerate(active)}
    small = QuantumCircuit(len(active))
    for ins in qc.data:
        if ins.operation.name != "barrier":
            small.append(ins.operation, [index[qc.find_bit(q).index] for q in ins.qubits])
    state = BareExact(len(active)) if shots is None else BareTrajectories(len(active), shots, np.random.default_rng(seed))

    def relax(q: int, t: float) -> None:
        if t > 0:
            state.damp(q, 1 - math.exp(-t / device.t1))
            p = (1 - math.exp(-device.dephasing * t)) / 2
            state.mixture([np.eye(2, dtype=complex), _Z], [1 - p, p], [q])

    clock = [0.0] * len(active)
    for ins in small.data:
        op = ins.operation
        qubits = [small.find_bit(q).index for q in ins.qubits]
        start = max(clock[q] for q in qubits)
        for q in qubits:
            relax(q, start - clock[q])
        state.unitary(Operator(op).data, qubits)
        duration = device.durations[op.name]
        for q in qubits:
            relax(q, duration)
        if op.name in device.depolarizing:
            state.mixture(*_pauli_mixture(len(qubits), device.depolarizing[op.name]), qubits)
        for q, p in zip(qubits, device.pauli_z.get(op.name, ())):
            state.mixture([np.eye(2, dtype=complex), _Z], [1 - p, p], [q])
        if op.name in device.loss:
            state.damp(qubits[0], device.loss[op.name])
        for q in qubits:
            clock[q] = start + duration
    end = max(clock)
    for q in range(len(active)):
        relax(q, end - clock[q])
    if logical is None:
        fidelity, se = state.fidelity(Statevector(small).data)
        return {"p_keep": 1.0, "fidelity": fidelity, "fidelity_se": se, "duration_us": end}
    keep = [index[p] for p in logical]
    rest = [q for q in range(len(active)) if q not in keep]
    # Axes ordered (ancilla qubits, program qubits), each little-endian, so a row of the ideal is the program state.
    axes = [len(active) - 1 - q for q in reversed(rest)] + [len(active) - 1 - q for q in reversed(keep)]
    ideal = np.transpose(Statevector(small).data.reshape([2] * len(active)), axes).reshape(2 ** len(rest), -1)
    program = ideal[0] / np.linalg.norm(ideal[0])
    flip = [np.sqrt(1 - readout) * np.eye(2), np.sqrt(readout) * np.array([[0, 1], [1, 0]])]
    if shots is None:
        rho = partial_trace(state.rho, rest) if rest else state.rho
        order = sorted(keep)
        for j in range(len(keep)):
            rho = rho.evolve(Kraus(flip), [j])
        # partial_trace keeps qubits in increasing index order; reorder the program state to match.
        vec = np.transpose(program.reshape([2] * len(keep)), [len(keep) - 1 - keep.index(q) for q in reversed(order)]).reshape(-1)
        return {"p_keep": 1.0, "fidelity": float((vec.conj() @ rho.data @ vec).real), "fidelity_se": 0.0, "duration_us": end}
    psi = state.psi
    for q in keep:
        hit = state.rng.random(len(psi)) < readout
        psi[hit] = psi[hit][:, np.arange(psi.shape[1]) ^ (1 << q)]
    t = np.transpose(psi.reshape(len(psi), *[2] * len(active)), [0, *(1 + a for a in axes)]).reshape(len(psi), 2 ** len(rest), -1)
    values = (np.abs(t @ program.conj()) ** 2).sum(axis=1)
    return {"p_keep": 1.0, "fidelity": float(values.mean()), "fidelity_se": float(values.std(ddof=1) / math.sqrt(len(values))), "duration_us": end}
