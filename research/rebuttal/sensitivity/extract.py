"""Per saved routed circuit (Greedy/PRISM, n = 8, 12, 16): the touch counts behind the closed form
-ln P_keep = I/T1 + N_crz [-ln(1-e_c) - ln(1-e_t)] + B [-ln(1-e_bs)]  (MODEL.md section 3),
and the summed live-pair idle time I re-timed for every beamsplitter duration t_bs the sweep needs
(routing `swap` and intra-pair `rswap`/`rx` share t_bs; CR_z stays 500 ns). The scheduler is the
ASAP rail-clock scheduler of validate._pair_schedule; at 200 ns it is checked against validate.loss_parts.
Writes data/parts_n{n}.jsonl. Pool of 3 workers.
Usage: .venv/bin/python research/rebuttal/sensitivity/extract.py [--data-dir WALLCLOCK_DATA --out OUT_DIR]"""
import argparse, dataclasses, json, math, sys
from multiprocessing import Pool
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
WC = REPO / "research/rebuttal/wallclock"
OUT = Path(__file__).resolve().parent / "data"
sys.path[:0] = [str(WC), str(REPO / "src")]
import sim  # noqa: E402
import validate  # noqa: E402
from qiskit import qpy  # noqa: E402

DEV = sim.MEHTA
BS_OPS = ("rswap", "swap", "rx", "x")  # every beamsplitter-class operation; "x" is timed, not charged
T1_US = DEV.t1  # 356.5 us, the rate average of Mehta's four cavities
E_BS = DEV.erasure["swap"][0]  # 7.24e-4 per live pair touched at 200 ns
C_BS = E_BS - 0.2 / T1_US  # coupler constant 1.63e-4: the part of the measured erasure that is not cavity decay during the pulse

# The sweep. T1 in us (log-spaced 100 us to 2 ms, with the measured value and Mehta's extreme cavities),
# t_bs in ns (50 to 500 ns, with the measured 200 ns and Mehta's fastest 136 ns).
T1_GRID = (100.0, 150.0, 231.0, T1_US, 500.0, 652.0, 1000.0, 1500.0, 2000.0)
TBS_GRID = (50.0, 70.0, 100.0, 136.0, 200.0, 300.0, 400.0, 500.0)
RHO_MEAS = 0.2 / T1_US  # 5.61e-4
# Collapse test: at each rho = t_bs/T1, every T1 of the grid whose t_bs = rho T1 lies within 50 to 500 ns.
RHO_SET = (5e-5, 1e-4, 2e-4, 4e-4, RHO_MEAS, 1e-3, 2e-3, 3e-3)
# Literature corners: (2 ms, 50 ns) best 3D cavities with Teoh's fastest beamsplitter; (231 us, 208 ns) Mehta's worst cavity and slowest beamsplitter.
ANCHORS = ((2000.0, 50.0), (231.0, 208.0))


def tbs_points():
    """Every (T1 us, t_bs ns) the sweep evaluates, and the sorted distinct t_bs values to schedule."""
    pts = {(t1, tb) for t1 in T1_GRID for tb in TBS_GRID} | set(ANCHORS)
    pts |= {(t1, round(rho * t1 * 1e3, 6)) for rho in RHO_SET for t1 in T1_GRID if 50 <= rho * t1 * 1e3 <= 500}
    return sorted(pts), sorted({tb for _, tb in pts})


def schedule(qc, device):
    """D, summed live-pair idle time I, live-pair count and touch counts (validate._pair_schedule logic)."""
    live, idle, pair = sim.live_pairs(qc)
    where = list(range(qc.num_qubits))
    clock = [0.0] * qc.num_qubits
    busy = {p: [] for p in pair.values()}
    counts = {"crz": 0, "bs_intra": 0, "swap2": 0, "swap1": 0}
    for i, ins in enumerate(qc.data):
        op = ins.operation
        if op.name == "barrier" or i in idle:
            continue
        rails = [qc.find_bit(q).index for q in ins.qubits]
        start = max(clock[r] for r in rails)
        duration = 0.0 if sim.is_synthetic_preparation(op) else device.durations[op.name]
        if duration and op.name in device.erasure:
            pairs = {pair[live[where[r]]] for r in rails if where[r] in live}
            for p in pairs:
                busy[p].append((start, start + duration))
            if op.name == "crz":
                counts["crz"] += 1
            elif op.name == "swap":
                if pairs:
                    counts[f"swap{len(pairs)}"] += 1
            else:
                counts["bs_intra"] += 1
        if op.name == "swap":
            a, b = rails
            where[a], where[b] = where[b], where[a]
        for r in rails:
            clock[r] = start + duration
    end = max(clock)
    return end, sum(end - validate.union_length(v) for v in busy.values()), len(busy), counts


def one(args):
    n, row, tbs_ns, data = args
    with (data / f"circuits_n{n}" / f"{row['circuit']}_{row['topology']}_{row['seed']}_{row['arm']}.qpy").open("rb") as f:
        qc = qpy.load(f)[0]
    D, I, n_live, c = schedule(qc, DEV)
    ref_n, ref_D, ref_I, ref_log = validate.loss_parts(qc, DEV)
    e_c, e_t = DEV.erasure["crz"]
    B = c["bs_intra"] + 2 * c["swap2"] + c["swap1"]
    log_er = c["crz"] * (math.log1p(-e_c) + math.log1p(-e_t)) + B * math.log1p(-E_BS)
    assert abs(ref_D - D) < 1e-9 and abs(ref_I - I) < 1e-9 and abs(ref_log - log_er) < 1e-12 and ref_n == n_live
    idle = []
    for tb in tbs_ns:
        dev = dataclasses.replace(DEV, durations={**DEV.durations, **{g: tb / 1e3 for g in BS_OPS}})
        _, I_tb, _, c_tb = schedule(qc, dev)
        assert c_tb == c
        idle.append(I_tb)
    return {"n": n, "circuit": row["circuit"], "topology": row["topology"], "seed": row["seed"], "arm": row["arm"],
            "n_live": n_live, "D": D, "I": I, **c, "B": B, "tbs_ns": tbs_ns, "I_tbs": idle,
            "loss_closed": I / T1_US - log_er, "loss_sim": -math.log(row["p_keep"])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=WC / "data", help="wallclock rows v2_n<n>.jsonl and circuits_n<n>/")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    _, tbs_ns = tbs_points()
    jobs = []
    for n in (8, 12, 16):
        for line in (a.data_dir / f"v2_n{n}.jsonl").open():
            r = json.loads(line)
            if r["arm"] in ("greedy", "prism") and r["device"] == "mehta":
                jobs.append((n, r, tbs_ns, a.data_dir.resolve()))
    total = len(jobs)
    print(f"{len(tbs_ns)} beamsplitter durations per circuit, {total} circuits", flush=True)
    results = {8: [], 12: [], 16: []}
    with Pool(3) as pool:
        for i, res in enumerate(pool.imap_unordered(one, jobs, chunksize=4), 1):
            results[res["n"]].append(res)
            if i % 20 == 0 or i == total:
                print(f"{i}/{total}", flush=True)
    a.out.mkdir(parents=True, exist_ok=True)
    for n, rows in results.items():
        rows.sort(key=lambda r: (r["circuit"], r["topology"], r["seed"], r["arm"]))
        with (a.out / f"parts_n{n}.jsonl").open("w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        worst = max(abs(r["loss_closed"] - r["loss_sim"]) / r["loss_sim"] for r in rows)
        print(f"n={n}: {len(rows)} rows, max rel gap closed form vs simulated -ln P_keep {worst:.1e}", flush=True)


if __name__ == "__main__":
    main()
