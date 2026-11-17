"""Fig. 12 (Section V-D), approved 2026-10-11: (a) attempts per retained shot vs cavity lifetime 0.2-1 ms, Greedy/PRISM per width;
(b) Eqs. 18-19 vs exact simulation at n = 8; (c) state fidelity vs width, dual rail vs transmon. Grid, hex and heavy-hex where complete."""
import json, math, sys
from collections import defaultdict
from pathlib import Path
import numpy as np
REPO = Path(__file__).resolve().parents[3]; WC = REPO / "research/rebuttal/wallclock"
HH = Path(__file__).resolve().parents[1] / "wallclock/data/swaps/heavy_hex"; OUT = Path(__file__).resolve().parent / "figures"; OUT.mkdir(exist_ok=True)
sys.path[:0] = [str(WC), str(REPO / "src"), str(OUT)]
import sim, validate, bare  # noqa: E402
from equations import z_counts, EPS  # noqa: E402
from qiskit import qpy  # noqa: E402
import lusca  # noqa: F401,E402
import matplotlib; matplotlib.use("Agg")  # noqa: E702
import matplotlib.pyplot as plt  # noqa: E402
DEV, W = sim.MEHTA_IDLE, (8, 12, 16)
G, P, T1C, T3C = "#d69b32", "#39877f", "#4a4a4a", "#9a9a9a"
T1M, EC, ET, EBS, TBS = 356.512171, 4.0e-3, 9.6e-4, 7.24e-4, 200.0
TOPOS = ("grid", "hex_lattice", "heavy_hex")
t = bare.CENTRAL; RATE = 1 / (4 * t.t1) + 1 / (2 * t.t2)
# (a) parts
parts = {n: [json.loads(l) for f in (REPO / f"research/rebuttal/sensitivity/data/swaps/parts_n{n}.jsonl", REPO / f"research/rebuttal/sensitivity/data/swaps/heavy_hex/parts_n{n}.jsonl") if f.exists() for l in open(f)] for n in W}
def att(r, t1):
    I = float(np.interp(TBS, r["tbs_ns"], r["I_tbs"]))
    return math.exp(I / t1 - r["crz"] * (math.log1p(-EC) + math.log1p(-ET)) - r["B"] * math.log1p(-EBS))
def geo(n, arm, t1):
    by = defaultdict(list)
    for r in parts[n]:
        if r["arm"] == arm: by[(r["topology"], r["circuit"])].append(att(r, t1))
    return math.exp(np.mean([math.log(np.mean(v)) for v in by.values()]))
# (b),(c) dual rail Eq. 18 per circuit
def dualrail():
    rows = []
    for n in W:
        for d in (WC / f"data/swaps/circuits_n{n}", HH / f"circuits_n{n}"):
            for p in sorted(d.glob("*.qpy")):
                topo = next(k for k in TOPOS if f"_{k}_" in p.stem)
                name, rest = p.stem.split(f"_{topo}_"); seed, arm = rest.split("_")
                if arm not in ("greedy", "prism"): continue
                with p.open("rb") as f: qc = qpy.load(f)[0]
                _, _, I, _ = validate.loss_parts(qc, DEV); z = z_counts(qc)
                rows.append(dict(n=n, c=name, t=topo, s=int(seed), a=arm, eq18=math.exp(-DEV.dephasing * I + sum(z[g] * math.log1p(-EPS[g]) for g in EPS))))
    return rows
def eq19(r, cz):
    c = r["op_counts"]; busy = sum(c.get(g, 0) * k * bare.DURATIONS[g] for g, k in (("cz", 2), ("sx", 1), ("x", 1)))
    return math.exp(-(r["n_active"] * r["duration_us"] - busy) * RATE) * (1 - 1.25 * cz) ** c.get("cz", 0) * (1 - 1.5 * t.sq) ** (c.get("sx", 0) + c.get("x", 0))
def transmon():
    rows = []
    for n in W:
        hh = HH / f"bare_n{n}.jsonl"
        complete = hh.exists() and sum(1 for _ in open(hh)) >= 160
        for f in [WC / f"data/bare_n{n}.jsonl"] + ([hh] if complete else []):
            for r in map(json.loads, open(f)):
                if r["arm"] == "best40" and r["topology"] in TOPOS:
                    rows += [dict(n=n, c=r["circuit"], t=r["topology"], s=r["seed"], cz=cz, eq19=eq19(r, cz)) for cz in (0.001, 0.003)]
    return rows
DR, TR = dualrail(), transmon()
def quart(rows, key):
    by = defaultdict(list)
    for r in rows: by[r["c"]].append(r[key])
    v = [np.mean(x) for x in by.values()]; return np.median(v), *np.percentile(v, [25, 75])
ex = {(r["circuit"], r["topology"], r["seed"], r["arm"]): r["fidelity"] for r in map(json.loads, open(WC / "data/swaps/v3_n8.jsonl"))}
ex.update({(r["circuit"], r["topology"], r["seed"], r["arm"]): r["fidelity"] for r in map(json.loads, open(HH / "v3_n8.jsonl"))})
scat_dr = np.array([(1 - ex[k], 1 - r["eq18"]) for r in DR if r["n"] == 8 and (k := (r["c"], r["t"], r["s"], r["a"])) in ex])
bt = {(r["circuit"], r["topology"], r["seed"], r["cz_error"]): r["fidelity"] for r in map(json.loads, open(WC / "data/bare_direct_n8.jsonl"))}
scat_tm = np.array([(1 - bt[k], 1 - r["eq19"]) for r in TR if r["n"] == 8 and (k := (r["c"], r["t"], r["s"], r["cz"])) in bt])
graphs = {n: sorted({r["topology"] for r in parts[n]}) for n in W}
graphs_c = {n: sorted({r["t"] for r in TR if r["n"] == n}) for n in W}
print("graphs in (a):", graphs, "\ntransmon graphs in (c):", graphs_c, "\nscatter dual rail", len(scat_dr), "transmon", len(scat_tm))

with plt.style.context("lusca"):
    plt.rcParams.update({"font.size": 7.0, "axes.labelsize": 6.8, "xtick.labelsize": 6.2, "ytick.labelsize": 6.2, "legend.fontsize": 5.8, "pdf.fonttype": 42})
    fig = plt.figure(figsize=(3.35, 3.0)); gs = fig.add_gridspec(2, 2, height_ratios=(1.0, 1.0))
    ax_a, ax_b, ax_c = fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[0, 1]), fig.add_subplot(gs[1, :])
    t1 = np.geomspace(200, 1000, 30)
    for n, al in zip(W, (0.45, 0.7, 1.0)):
        ax_a.plot(t1, [geo(n, "greedy", x) for x in t1], color=G, lw=1.2, alpha=al, zorder=3)
        ax_a.plot(t1, [geo(n, "prism", x) for x in t1], color=P, lw=1.2, alpha=al, zorder=3)
        ax_a.text(980, geo(n, "greedy", 1000) * 1.12, f"$n$ = {n}", fontsize=5.4, va="bottom", ha="right")
    ax_a.axvline(T1M, color="#9a9a9a", lw=0.6, ls="--")
    ax_a.set_xscale("log"); ax_a.set_yscale("log"); ax_a.minorticks_off(); ax_a.set_xlim(200, 1000)
    ax_a.set_xticks((200, 300, 500, 1000), ("0.2", "0.3", "0.5", "1")); ax_a.set_yticks((1, 10, 100), ("1", "10", "100"))
    ax_a.set_xlabel("Cavity lifetime (ms)"); ax_a.set_ylabel("Shot overhead, $1/P_{\\mathrm{keep}}$"); ax_a.set_title("(a) Shot overhead", loc="left", fontsize=7.0)
    ax_a.legend(handles=[plt.Line2D([], [], color=G, label="Greedy"), plt.Line2D([], [], color=P, label="PRISM")], frameon=False, loc="upper right", bbox_to_anchor=(1.0, 0.86), handlelength=1.4)
    for pts, col, mk, lab in ((scat_dr, P, "o", "Dual rail, Eq. 18"), (scat_tm, T1C, "^", "Transmon, Eq. 19")):
        ax_b.plot(pts[:, 0], pts[:, 1], mk, ms=2.0, mfc="white", mec=col, mew=0.6, ls="", label=lab, zorder=3)
    lim = (3e-3, 1); ax_b.plot(lim, lim, color="#2b2b2b", lw=0.7, zorder=2)
    ax_b.set_xscale("log"); ax_b.set_yscale("log"); ax_b.minorticks_off(); ax_b.set_xlim(lim); ax_b.set_ylim(lim)
    ax_b.set_xticks((0.01, 0.1, 1), ("0.01", "0.1", "1")); ax_b.set_yticks((0.01, 0.1, 1), ("0.01", "0.1", "1"))
    ax_b.set_xlabel("Simulated infidelity"); ax_b.set_ylabel("Proxy infidelity"); ax_b.set_title("(b) Proxy vs. exact, $n$ = 8", loc="left", fontsize=7.0)
    ax_b.legend(frameon=False, loc="lower right", handletextpad=0.1, borderaxespad=0.2, fontsize=5.4)
    for key, col, mk, lab, ls, dx in (("greedy", G, "s", "Dual rail, Greedy", "-", -0.3), ("prism", P, "o", "Dual rail, PRISM", "-", -0.1),
                                      (0.001, T1C, "^", "Transmon, CZ 0.1%", "--", 0.1), (0.003, T3C, "v", "Transmon, CZ 0.3%", "--", 0.3)):
        q = [quart([r for r in DR if r["n"] == n and r["a"] == key], "eq18") if isinstance(key, str) else quart([r for r in TR if r["n"] == n and r["cz"] == key], "eq19") for n in W]
        ax_c.errorbar([n + dx for n in W], [x[0] for x in q], yerr=[[x[0] - x[1] for x in q], [x[2] - x[0] for x in q]], color=col, marker=mk, ms=3.0,
                      lw=1.3, ls=ls, capsize=1.5, elinewidth=0.8, mfc="white" if not isinstance(key, str) else col, label=lab, zorder=3)
    ax_c.set_xticks(W); ax_c.set_ylim(0, 1.02); ax_c.set_xlabel("Logical qubits"); ax_c.set_ylabel("Fidelity proxy"); ax_c.set_title("(c) Fidelity proxy", loc="left", fontsize=7.0)
    ax_c.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.32), ncol=2, handlelength=1.8, columnspacing=1.0, handletextpad=0.3)
    for ax in (ax_a, ax_b, ax_c): ax.grid(color="#e1e1e1", lw=0.45, zorder=0); ax.set_axisbelow(True)
    fig.tight_layout(pad=0.2, h_pad=0.6, w_pad=0.8)
    fig.savefig(OUT / "eval_hardware.pdf"); fig.savefig(OUT / "eval_hardware.png", dpi=300)
