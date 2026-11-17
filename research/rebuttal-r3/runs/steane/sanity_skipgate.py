"""Checks of skipgate.py against Stim. Usage: sanity_skipgate.py off | pauli | skip | two | outside | timing"""
import subprocess
import sys

from ldpc import mod2
import numpy as np
import stim

import flag_memory as fm
import skipgate as sg
from erasure_pilot import signatures

CELLS = [(p, b, a) for p in ("readout", "checks", "checks3") for b in "XZ" for a in fm.mm.ARMS]


def zeros(c):
    """Rates with every channel off."""
    return np.zeros(len(c.sites))


def packed(c, det, obs):
    """Detection events and observable as column integers (L0 in bit 0)."""
    return (det.astype(np.int64) @ (1 << np.arange(1, det.shape[1] + 1, dtype=np.int64))) | obs[:, 0].astype(np.int64)


def rank(vectors):
    """GF(2) rank of packed integers (ldpc.mod2)."""
    vectors = np.asarray(list(vectors), dtype=np.int64)
    return int(mod2.rank(((vectors[:, None] >> np.arange(63)) & 1).astype(np.uint8))) if vectors.any() else 0


def stim_patterns(c, circuit, shots, seed):
    """Stim's own sampler on an explicit circuit, as detection events of the routed circuit."""
    return sg.detector_bits(c, circuit.compile_sampler(seed=seed).sample(shots))


def off():
    """No noise: no detection event, observable flip or flag on every route; one certain Z checks the tableau path."""
    for protocol, basis, arm in CELLS:
        for seed in range(0, 2000, 100):
            c = sg.cell(protocol, basis, arm, seed)
            phase = zeros(c)
            phase[0] = 1.0
            z0 = signatures(c.base, [(s["tick"], s["qubit"], s["kind"]) for s in c.sites[:1]])[0, 1]
            det, obs, flags = sg.sample(c, zeros(c), phase, 0.0, 0.0, 0.0, 64, seed)
            assert (packed(c, det, obs) == z0).all() and not flags.any(), (protocol, basis, arm, seed)
            det, obs, flags = sg.sample(c, zeros(c), zeros(c), 0.0, 0.0, 0.0, 64, seed)
            assert not det.any() and not obs.any() and not flags.any()
        print(f"off ok: {protocol} {basis} {arm}, 20 seeds", flush=True)


def pauli():
    """Pauli-only noise: per shot identical to the XOR of Stim's fault columns, and in law equal to Stim's sampler."""
    for protocol, basis, arm in CELLS[::2]:
        c = sg.cell(protocol, basis, arm, 0)
        z = signatures(c.base, [(s["tick"], s["qubit"], s["kind"]) for s in c.sites])[:, 1]
        rng = np.random.default_rng(3)
        for _ in range(20):
            chosen = rng.random(len(c.sites)) < 0.05
            det, obs, _ = sg.sample(c, zeros(c), chosen.astype(float), 0.0, 0.0, 0.0, 8, 1)
            assert (packed(c, det, obs) == np.bitwise_xor.reduce(z[chosen])).all()
        phase = np.array([s["pauli_z"] for s in c.sites]) * 20
        det, obs, _ = sg.sample(c, zeros(c), phase, fm.CHECK_DEPOL * 20, 0.0, 0.0, 40_000, 2)
        noisy = fm.with_residuals(c.base, [dict(s, pauli_z=p) for s, p in zip(c.sites, phase)], fm.CHECK_DEPOL * 20)
        ref_det, ref_obs = noisy.compile_detector_sampler(seed=2).sample(40_000, separate_observables=True)
        ours, ref = np.hstack([det, obs]).mean(0), np.hstack([ref_det, ref_obs]).mean(0)
        tol = 5 * np.sqrt(np.maximum(ref, 1e-3) / 40_000)
        assert (abs(ours - ref) < tol).all(), np.max(abs(ours - ref) / tol)
        print(f"pauli ok: {protocol} {basis} {arm} seed 0: 20 fixed Z patterns equal the XOR of Stim's columns; "
              f"20x residual rates match compile_detector_sampler on {len(ours)} bits (max |diff| "
              f"{np.max(abs(ours - ref)):.4f})", flush=True)


def skip():
    """A certain loss: the tableau loop equals Stim on the circuit with the pair's events removed, and lies in the
    envelope columns the decoder opens for it; without skipping (erase, keep the gates) the law differs."""
    shots = 2000
    for protocol, basis, arm in CELLS[::3]:
        c = sg.cell(protocol, basis, arm, 0)
        env = sg.envelopes(c)
        rng = np.random.default_rng(5)
        compared = differs = small = 0
        for k in rng.choice(len(c.groups), 12, replace=False):
            g = c.groups[k]
            for pos in rng.choice(len(env[k]["chain"]), min(3, len(env[k]["chain"])), replace=False):
                i, q = env[k]["chain"][pos], g["qubit"]
                if not g["check"] and any(c.groups[j]["check"] for j in g["earlier"]) and i not in g["sites"]:
                    fn = 1.0  # a loss before a check reaches this readout only if every check misses it
                elif i in g["sites"]:
                    fn = 0.0
                else:
                    continue
                one = zeros(c)
                one[i] = 1.0
                det, obs, flags = sg.sample(c, one, zeros(c), 0.0, 0.0, fn, shots, 7)
                assert flags[:, k].all() and flags.sum(1).max() == 1
                ours = packed(c, det, obs)
                check = g["sites"][-1] if g["check"] else None
                theirs = stim_patterns(c, sg.removed(c, [(i, q, check)]), shots, 11)
                # Stabilizer outcomes under uniform Pauli twirls are uniform over an affine space, so equal affine
                # spans mean equal laws; small supports are also compared pattern by pattern, the rest bit by bit.
                shift = ours[0]
                assert rank(ours ^ shift) == rank(theirs ^ shift) == rank(np.r_[ours ^ shift, theirs ^ shift])
                bits = lambda v: (v[:, None] >> np.arange(c.base.num_detectors + 1)) & 1
                assert (abs(bits(ours).mean(0) - bits(theirs).mean(0)) < 0.08).all()
                if len(set(theirs)) <= 64:
                    assert set(ours) == set(theirs), (protocol, basis, arm, k, i)
                    for v in set(ours):
                        a, b = (ours == v).mean(), (theirs == v).mean()
                        assert abs(a - b) < 5 * np.sqrt(a * (1 - a) / shots) + 5 / shots, (v, a, b)
                    small += 1
                opened = [v for v, positions in env[k]["columns"] if pos in positions]  # this location alone
                assert rank(opened + list(set(ours))) == rank(opened), ("outside the envelope", protocol, basis, arm, k, i)
                kept = stim.Circuit()
                for ins in c.base:
                    kept.append(ins)
                    if ins.name == "TICK" and kept.num_ticks - 1 == c.sites[i]["tick"]:
                        kept.append("DEPOLARIZE1", [q], 0.75)
                erased = stim_patterns(c, kept, shots, 13)
                differs += set(erased) != set(ours)
                compared += 1
        print(f"skip ok: {protocol} {basis} {arm} seed 0: {compared} certain losses match Stim on the circuit with "
              f"the pair's events removed (same affine span and bit rates; {small} small supports pattern by pattern; "
              f"{shots} shots each) and lie in the envelope; "
              f"{differs} of them differ from erase-and-keep-gates", flush=True)


def timing():
    """A certain loss raises one flag, at the pair's first check after it (fn=0) or at its next readout (fn=1)."""
    for protocol, basis, arm in CELLS[::2]:
        c = sg.cell(protocol, basis, arm, 0)
        for i, s in enumerate(c.sites):
            k = next(k for k, g in enumerate(c.groups) if i in g["sites"])
            later = [j for j, g in enumerate(c.groups) if g["qubit"] == s["qubit"] and j >= k]
            readout = next(j for j in later if not c.groups[j]["check"])
            one = zeros(c)
            one[i] = 1.0
            for fn, expected in ((0.0, k), (1.0, readout)):
                flags = sg.sample(c, one, zeros(c), 0.0, 0.0, fn, 4, 1)[2]
                assert (flags.sum(1) == 1).all() and flags[:, expected].all(), (protocol, basis, arm, i, fn)
        print(f"timing ok: {protocol} {basis} {arm} seed 0: {len(c.sites)} sites", flush=True)

def two():
    """Two certain losses on pairs that share a later CR_z: the tableau loop equals Stim with both pairs' events removed."""
    shots, rng = 2000, np.random.default_rng(9)
    for protocol, basis, arm in CELLS[::3]:
        c = sg.cell(protocol, basis, arm, 0)
        group = {i: k for k, g in enumerate(c.groups) for i in g["sites"]}
        position, shared = 0, []
        for item in c.items:
            position += item[0] == "site"
            if item[0] == "ops" and len(item[2]) == 2:
                shared.append((position, sorted(item[2])))
        done = 0
        for at, (a, b) in [shared[j] for j in rng.permutation(len(shared))]:
            sites = [max((i for i in range(at) if c.sites[i]["qubit"] == q), default=None) for q in (a, b)]
            if None in sites or done == 8:
                continue
            one = zeros(c)
            one[sites] = 1.0
            det, obs, _ = sg.sample(c, one, zeros(c), 0.0, 0.0, 0.0, shots, 7)
            ours = packed(c, det, obs)
            losses = [(i, c.sites[i]["qubit"], c.groups[group[i]]["sites"][-1] if c.groups[group[i]]["check"] else None)
                      for i in sites]
            theirs = stim_patterns(c, sg.removed(c, losses), shots, 11)
            shift = ours[0]
            assert rank(ours ^ shift) == rank(theirs ^ shift) == rank(np.r_[ours ^ shift, theirs ^ shift]), (protocol, sites)
            done += 1
        print(f"two ok: {protocol} {basis} {arm} seed 0: {done} pairs of certain losses before a shared CR_z match Stim "
              f"with both pairs' events removed (same affine span, {shots} shots)", flush=True)


LEAKY = "/home/evm9/prism/scratch/skipgate/venv-l16/bin/python"  # leakysim 0.5.0 on Stim 1.16
LEAKY_RUN = """
import sys, leaky, stim, numpy as np
S = leaky.LeakageStatus
loss = leaky.LeakyPauliChannel(1)
loss.add_transition(S(status=[0]), S(status=[1]), "I", 1.0)
loss.add_transition(S(status=[1]), S(status=[1]), "I", 1.0)
fix = leaky.LeakyPauliChannel(2)  # after a lowered CR_z whose control is leaked: undo the Z its S gates leave
for st, p in (([0, 0], "II"), ([1, 0], "IZ"), ([0, 1], "II"), ([1, 1], "II")):
    fix.add_transition(S(status=st), S(status=st), p, 1.0)
back = leaky.LeakyPauliChannel(1)  # detection: return completely mixed
for p in "IXYZ":
    back.add_transition(S(status=[1]), S(status=[0]), p, 0.25)
back.add_transition(S(status=[0]), S(status=[0]), "I", 1.0)
c = stim.Circuit(sys.stdin.read())
sys.stdout.buffer.write(leaky.Simulator(c.num_qubits, [loss, fix, back], seed=5).sample(c, int(sys.argv[1])).astype(np.uint8).tobytes())
"""


def toy(spec, detectors, kinds=None):
    """A hand-written cell: spec lists ("R"|"M", q), ("ops", text, pairs) and ("site", q); no build or removed."""
    base, items, sites = stim.Circuit(), [], []
    for item in spec:
        if item[0] == "site":
            sites.append(dict(tick=base.num_ticks, qubit=item[1], kind=(kinds or {}).get(len(sites), "idle"),
                              erasure=0.0, pauli_z=0.0))
            items.append(("site", len(sites) - 1))
            base.append("TICK")
        elif item[0] == "ops":
            items.append(("ops", stim.Circuit(item[1]), frozenset(item[2])))
            base += stim.Circuit(item[1])
        else:
            items.append(item)
            base.append(item[0], [item[1]])
    for i, recs in enumerate(detectors):
        base.append("DETECTOR" if i else "OBSERVABLE_INCLUDE", [stim.target_rec(r) for r in recs], *([] if i else [0]))
    base.detector_error_model()  # every detector and the observable are deterministic without noise
    return sg.Cell(base, items, sites, fm.intervals(base, sites), 0.0)


def leaky_patterns(c, spec, lost, shots, fix=True):
    """leakysim on the same spec: loss channel at the lost site, the conditioned fix after each CR_z that the lost
    pair controls, the return channel before the lost pair's first readout."""
    text, q, k, armed = [], c.sites[lost]["qubit"], 0, False
    for item in spec:
        if item[0] == "site":
            text.append("I[leaky<0>] %d" % q if k == lost else "TICK")
            armed |= k == lost
            k += 1
        elif item[0] == "ops":
            text.append(item[1])
            if fix and armed and q in item[2] and len(item[2]) == 2:
                text.append("I[leaky<1>] %d %d" % (q, (set(item[2]) - {q}).pop()))
        else:
            if item[0] == "M" and item[1] == q and armed:
                text.append("I[leaky<2>] %d" % q)
                armed = False
            text.append("%s %d" % item)
    run = subprocess.run([LEAKY, "-I", "-c", LEAKY_RUN, str(shots)], input="\n".join(text).encode(),
                         capture_output=True, check=True)
    m = np.frombuffer(run.stdout, dtype=np.uint8).reshape(shots, c.base.num_measurements).astype(bool)
    return sg.detector_bits(c, m)


def outside():
    """Hand-built cases against an outside reference: leakysim (control lost) or a hand calculation."""
    shots = 4000
    cz = lambda a, b: f"S {a}\nH {b}\nCX {a} {b}\nH {b}\nS {b} {b}"  # the lowering of one CR_z, control a
    # A: pair 0 (control, |+>) is lost before or between two CR_z on pair 1 (|+>), read in X.
    spec = [("R", 0), ("R", 1), ("ops", "H 0", {0}), ("ops", "H 1", {1}), ("site", 0), ("ops", cz(0, 1), {0, 1}),
            ("site", 0), ("ops", cz(0, 1), {0, 1}), ("ops", "H 1", {1}), ("M", 1), ("M", 1), ("ops", "H 0", {0}),
            ("M", 0), ("M", 0)]
    c = toy(spec, [[-1], [-4], [-4, -3], [-2, -1]])
    for lost in (0, 1):
        one = np.zeros(2)
        one[lost] = 1.0
        det, obs, flags = sg.sample(c, one, np.zeros(2), 0.0, 0.0, 0.0, shots, 3)
        ours, theirs = packed(c, det, obs), leaky_patterns(c, spec, lost, shots)
        assert set(ours) == set(theirs) and (flags.sum(1) == 1).all(), (lost, set(ours), set(theirs))
        for v in set(ours):
            a, b = (ours == v).mean(), (theirs == v).mean()
            assert abs(a - b) < 5 * np.sqrt(a * (1 - a) / shots) + 5 / shots, (lost, v, a, b)
        print(f"outside ok: control lost {'before both CR_z' if lost == 0 else 'between the CR_z'}: tableau loop and "
              f"leakysim (conditioned fix channel) give the same {len(set(ours))} patterns at equal rates; partner "
              f"flip rate {np.mean(det[:, 0]):.3f} (hand: {0.0 if lost == 0 else 0.5})", flush=True)
    # B: target pair 0 (|1>) is lost before a CR_z controlled by pair 2 (|+>), and pair 2 is read in Y.
    # Reference: |+> -Z-> |-> -S-> |-i>, read 1. Skipped: |+>, a Y readout gives 0 or 1 at random (hand: 1/2).
    spec = [("R", 0), ("R", 2), ("ops", "X 0", {0}), ("ops", "H 2", {2}), ("site", 0),
            ("ops", "S 2\nH 0\nCX 2 0\nH 0", {0, 2}), ("ops", "S_DAG 2\nH 2", {2}), ("M", 2), ("M", 2), ("M", 0), ("M", 0)]
    c = toy(spec, [[-4], [-4]])
    det, obs, flags = sg.sample(c, np.array([1.0]), np.zeros(1), 0.0, 0.0, 0.0, shots, 3)
    rate = det[:, 0].mean()
    assert abs(rate - 0.5) < 5 * 0.5 / np.sqrt(shots), rate
    gap = leaky_patterns(c, spec, 0, shots, fix=False)
    print(f"outside ok: target lost: intact control's Y readout flips at {rate:.3f} (hand: 1/2); leakysim, which keeps "
          f"the lowering's S on the control, flips it at {np.mean(gap >> 1 & 1):.3f} (hand: 1)", flush=True)
    # C: a Bell pair (0, 1); a joint check on pair 0. A false flag resets pair 0, so the ZZ parity is lost (hand: 1/2);
    # a loss the check misses (fn = 1) is flagged at the readout instead.
    spec = [("R", 0), ("R", 1), ("ops", "H 0", {0}), ("ops", "CX 0 1", {0, 1}), ("site", 0), ("M", 0), ("M", 0),
            ("M", 1), ("M", 1)]
    c = toy(spec, [[-4, -2], [-4, -2]], kinds={0: "gate:joint_check"})
    det, obs, flags = sg.sample(c, np.zeros(1), np.zeros(1), 0.0, 1.0, 0.0, shots, 3)
    reset = det[:, 0].mean()
    assert flags[:, 0].all() and abs(reset - 0.5) < 5 * 0.5 / np.sqrt(shots)
    no = sg.sample(c, np.zeros(1), np.zeros(1), 0.0, 0.0, 0.0, shots, 3)
    assert not no[0].any() and not no[2].any()
    det, obs, flags = sg.sample(c, np.array([1.0]), np.zeros(1), 0.0, 0.0, 1.0, shots, 3)
    assert not flags[:, 0].any() and flags[:, 1].all() and abs(det[:, 0].mean() - 0.5) < 5 * 0.5 / np.sqrt(shots)
    print(f"outside ok: a false flag resets the pair (Bell parity flips at {reset:.3f}, hand 1/2); without one nothing "
          f"fires; a loss the check misses is flagged at the readout only (parity flips at {det[:, 0].mean():.3f}, hand 1/2)",
          flush=True)


if __name__ == "__main__":
    {"off": off, "pauli": pauli, "skip": skip, "two": two, "outside": outside, "timing": timing}[sys.argv[1]]()
