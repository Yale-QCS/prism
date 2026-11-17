"""Sanity checks for flag_memory.py. Usage: sanity.py timing | channels | published | off"""
import json
import sys

import numpy as np

import flag_memory as fm
from flag_memory import mm


def timing():
    """A loss at any one site raises exactly one flag, at the pair's first observation after it."""
    for protocol in ("readout", "checks", "checks3"):
        for basis in "XZ":
            for arm in mm.ARMS:
                mem, qc = fm.routed(protocol, basis, arm, 0, fm.HERE)
                base, sites, _ = fm.build(mem, qc, fm.device("table4", checks=protocol != "readout"), split=True)
                groups = fm.intervals(base, sites)
                tick_at = [i for i, ins in enumerate(base) if ins.name == "TICK"]
                missed = 0
                for s, site in enumerate(sites):
                    # Independent forward scan of the circuit: the pair's next joint check, else its next readout
                    # (the later rail if the two are read apart), and the readout after every check.
                    q, k, check, readout = site["qubit"], s, None, None
                    for at, ins in enumerate(base[tick_at[s]:], tick_at[s]):
                        if ins.name == "TICK":
                            if check is None and sites[k]["qubit"] == q and sites[k]["kind"] == "gate:joint_check":
                                check = at
                            k += 1
                        elif ins.name == "M" and q in [t.value for t in ins.targets_copy()]:
                            readout = at
                        elif ins.name == "R" and q in [t.value for t in ins.targets_copy()]:
                            break
                    assert readout is not None and readout > tick_at[s]
                    one = [float(i == s) for i in range(len(sites))]
                    for fn, expected in ((0.0, readout if check is None else check), (1.0, readout)):
                        flags = fm.sample_flags(base, sites, groups, one, 0.0, fn, 8, 1)[2]
                        raised = np.flatnonzero(flags.any(axis=0))
                        assert len(raised) == 1 and flags[:, raised].all(), (protocol, basis, arm, s, fn, raised)
                        g = groups[raised[0]]
                        assert (g["qubit"], g["at"]) == (q, expected) and g["check"] == (expected == check)
                    missed += check is not None
                print(f"timing ok: {protocol} {basis} {arm} seed 0, {len(sites)} sites, {len(groups)} flags, "
                      f"{missed} sites whose missed loss is flagged at the next readout", flush=True)


def channels():
    """False positives flag exactly the checks, and a missed flag moves to the pair's next observation."""
    for protocol in ("checks", "checks3"):
        for basis in "XZ":
            mem, qc = fm.routed(protocol, basis, "greedy", 0, fm.HERE)
            base, sites, _ = fm.build(mem, qc, fm.device("table4", checks=True), split=True)
            groups = fm.intervals(base, sites)
            none = [0.0] * len(sites)
            det, obs, flags = fm.sample_flags(base, sites, groups, none, 1.0, 0.0, 64, 1)
            assert (flags == np.array([g["check"] for g in groups])).all() and not det.any() and not obs.any()
            shots, rates = 8000, []
            for q in sorted({g["qubit"] for g in groups if g["check"]}):
                # The pair's groups from its first check to the readout that follows the last one.
                mine = [k for k, g in enumerate(groups) if g["qubit"] == q]
                mine = mine[next(n for n, k in enumerate(mine) if groups[k]["check"]):]
                mine = mine[:next(n for n, k in enumerate(mine) if not groups[k]["check"]) + 1]
                one = [float(i == groups[mine[0]]["sites"][0]) for i in range(len(sites))]
                flags = fm.sample_flags(base, sites, groups, one, 0.0, 0.5, shots, 2)[2]
                assert (flags.sum(axis=1) == 1).all() and (flags[:, mine].sum(axis=1) == 1).all()
                expected = [0.5 ** (n + 1) for n in range(len(mine) - 1)] + [0.5 ** (len(mine) - 1)]
                assert np.allclose(flags[:, mine].mean(axis=0), expected, atol=4 / np.sqrt(shots)), (protocol, basis, q)
                rates = expected
            print(f"channels ok: {protocol} {basis} greedy seed 0: fp=1 flags exactly the {sum(g['check'] for g in groups)} "
                  f"checks with no detector flip; fn=0.5 flag rates {rates} on each data pair, one flag per shot", flush=True)


def published():
    """The ideal protocol without the added term reproduces every published hexagonal-lattice row."""
    total = {}
    for basis in "XZ":
        for arm in mm.ARMS:
            for seed in range(0, 2000, 100):
                new = json.loads((fm.HERE / "rows_published" / f"ideal_{basis}_{arm}_{seed}.json").read_text())
                old = json.loads((mm.OUTPUT / f"{basis}_{fm.TOPO}_{arm}_{seed}.json").read_text())
                assert (new["errors"], new["shots"], new["flagged_shots"], new["rng_seed"]) == (
                    old["errors"], old["shots"], old["heralded_shots"], old["rng_seed"]), (basis, arm, seed)
                assert new["score"] == old["score"] and new["duration_us"] == old["duration_us"]
                total[basis, arm] = total.get((basis, arm), 0) + new["errors"]
    print("published rows reproduced exactly, errors per 1,000,000 shots:", total)


def off():
    """With all noise off every row has zero logical errors and zero flags."""
    rows = [json.loads(p.read_text()) for p in sorted((fm.HERE / "rows_off").glob("*.json"))]
    assert all(r["errors"] == 0 and r["flagged_shots"] == 0 for r in rows)
    count = {}
    for r in rows:
        count[r["protocol"]] = count.get(r["protocol"], 0) + 1
    print("noise off: zero logical errors and zero flags in", count)


if __name__ == "__main__":
    {"timing": timing, "channels": channels, "published": published, "off": off}[sys.argv[1]]()
