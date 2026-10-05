import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle
fig = plt.figure(figsize=(16, 13)); fig.patch.set_facecolor("white")
BEF, AFT, RAIL, SW, TXT = "#8b93a3", "#1b7f79", "#dde2ea", "#c98a2b", "#1c2128"
def node(ax, x, y, label, sub, color, w=1.7, h=0.8):
    ax.add_patch(FancyBboxPatch((x - w/2, y - h/2), w, h, boxstyle="round,pad=0.02,rounding_size=0.08", fc="white", ec=color, lw=2))
    ax.text(x, y + 0.13, label, ha="center", va="center", fontsize=10, color=TXT, weight="bold")
    ax.text(x, y - 0.2, sub, ha="center", va="center", fontsize=8, color="#5c6470")
def arrow(ax, x0, y0, x1, y1, color):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=12, color=color, lw=1.4, shrinkA=14, shrinkB=14))
# ---------- Panel 1: boundary DAG before / after ----------
ax = fig.add_subplot(3, 1, 1); ax.set_xlim(0, 16); ax.set_ylim(-0.6, 6.4); ax.axis("off")
ax.text(0.2, 6.1, "1. Boundary DAG for  H(A) ; CRZ(A,D) ; CRZ(A,B) ; CRZ(A,C) ; H(A)   (uncommitted CRZ footprint = all four rails of both operands)", fontsize=11, weight="bold", color=TXT)
ax.text(0.2, 5.45, "before: program order over the footprint", fontsize=10, color=BEF, weight="bold")
xs = [1.2, 3.4, 5.6, 7.8, 10.0]; labs = [("H(A)", "rails A0 A1"), ("CRZ(A,D)", "A0 A1 D0 D1"), ("CRZ(A,B)", "A0 A1 B0 B1"), ("CRZ(A,C)", "A0 A1 C0 C1"), ("H(A)", "A0 A1")]
for x, (l, s) in zip(xs, labs): node(ax, x, 4.6, l, s, BEF)
for a, b in zip(xs, xs[1:]): arrow(ax, a, 4.6, b, 4.6, BEF)
ax.text(11.6, 4.6, "front layer holds one CRZ on A at a time:\nthe router must serve D first even if B and C\nare already adjacent", fontsize=9, color="#5c6470", va="center")
ax.text(0.2, 3.5, "after: diagonal ops depend only on the last non-diagonal op per rail", fontsize=10, color=AFT, weight="bold")
node(ax, 1.2, 1.5, "H(A)", "A0 A1", AFT)
for y, (l, s) in zip([2.7, 1.5, 0.3], [("CRZ(A,D)", "A0 A1 D0 D1"), ("CRZ(A,B)", "A0 A1 B0 B1"), ("CRZ(A,C)", "A0 A1 C0 C1")]):
    node(ax, 5.6, y, l, s, AFT); arrow(ax, 1.2, 1.5, 5.6, y, AFT); arrow(ax, 5.6, y, 10.0, 1.5, AFT)
node(ax, 10.0, 1.5, "H(A)", "A0 A1", AFT)
ax.text(11.6, 1.5, "front layer holds all three: whichever partner is\nadjacent commits now; the SWAP score sums over all\n(prism kernel only; stock SABRE asserts here)", fontsize=9, color="#5c6470", va="center")
# ---------- Panel 2: rail timeline ----------
ax = fig.add_subplot(3, 1, 2); ax.set_xlim(0, 16); ax.set_ylim(-0.4, 6.6); ax.axis("off")
ax.text(0.2, 6.3, "2. The same program routed on rails. Layout: A0-A1 adjacent, B0 next to A1, C0 next to A0, D0 one site away (across spare S). Lanes are sites named by the rail that starts there; the SWAP moves D's rail into the empty spare site S.", fontsize=10.5, weight="bold", color=TXT)
def timeline(ax, x0, title, color, lanes, ops, T):
    y0 = 5.4
    ax.text(x0, y0 + 0.4, title, fontsize=10, color=color, weight="bold")
    for i, l in enumerate(lanes):
        y = y0 - i * 0.62; ax.add_patch(Rectangle((x0, y - 0.22), T * 1.0, 0.44, fc=RAIL, ec="none")); ax.text(x0 - 0.15, y, l, ha="right", va="center", fontsize=9, color=TXT)
    for t in range(T + 1): ax.text(x0 + t, y0 - len(lanes) * 0.62 + 0.12, str(t), ha="center", fontsize=8, color="#5c6470")
    for (t, ls, label, kind) in ops:
        ys = [y0 - lanes.index(l) * 0.62 for l in ls]; c = SW if kind == "swap" else color
        if len(ys) > 1: ax.plot([x0 + t + 0.5] * 2, [min(ys), max(ys)], color=c, lw=2.5, zorder=1)
        for yy in ys: ax.add_patch(Rectangle((x0 + t + 0.05, yy - 0.2), 0.9, 0.4, fc=c, ec="white", lw=1, zorder=2))
        ax.text(x0 + t + 0.5, ys[0], label, ha="center", va="center", fontsize=7.5, color="white", weight="bold", zorder=3)
L2 = ["A0", "A1", "B0", "C0", "S (spare)", "D0"]
timeline(ax, 0.9, "before (program order): depth 6", BEF, L2,
    [(0, ["A0", "A1"], "H(A)", "g"), (1, ["S (spare)", "D0"], "SWAP", "swap"), (2, ["A0", "S (spare)"], "CRZ A,D", "g"), (3, ["A1", "B0"], "CRZ A,B", "g"), (4, ["A0", "C0"], "CRZ A,C", "g"), (5, ["A0", "A1"], "H(A)", "g")], 6)
timeline(ax, 8.7, "after (dependency DAG): depth 5", AFT, L2,
    [(0, ["A0", "A1"], "H(A)", "g"), (1, ["A1", "B0"], "CRZ A,B", "g"), (1, ["S (spare)", "D0"], "SWAP", "swap"), (2, ["A0", "C0"], "CRZ A,C", "g"), (3, ["A0", "S (spare)"], "CRZ A,D", "g"), (4, ["A0", "A1"], "H(A)", "g")], 6)
ax.text(0.9, 0.5, "Before: the front layer holds only CRZ(A,D), so the SWAP that brings D's rail to A's neighborhood (D0 into site S) runs first and B, C wait behind it. After: CRZ(A,B) commits at t=1 while the SWAP runs; CRZ(A,C) and CRZ(A,D) still serialize on A0. Swaps equal here; on the paper set the freedom also removes SWAPs (-19%).", fontsize=9, color="#5c6470", wrap=True)
# ---------- Panel 3: rescheduler ----------
ax = fig.add_subplot(3, 1, 3); ax.set_xlim(0, 16); ax.set_ylim(-0.4, 6.6); ax.axis("off")
ax.text(0.2, 6.3, "3. Rescheduler on the routed rail circuit. CRZ(A,B) and CRZ(A,C) commute on A0; B's chain (RX, CRZ B,D, RX D) is the critical path.", fontsize=10.5, weight="bold", color=TXT)
L3 = ["A0", "B0", "B1", "C0", "D0", "D1"]
timeline(ax, 0.9, "emitted in commit order (C was adjacent first): depth 5", BEF, L3,
    [(0, ["A0", "C0"], "CRZ A,C", "g"), (1, ["A0", "B0"], "CRZ A,B", "g"), (2, ["B0", "B1"], "H(B)", "g"), (3, ["B0", "D0"], "CRZ B,D", "g"), (4, ["D0", "D1"], "H(D)", "g")], 5)
timeline(ax, 8.7, "critical-path order over the commuting DAG: depth 4", AFT, L3,
    [(0, ["A0", "B0"], "CRZ A,B", "g"), (1, ["A0", "C0"], "CRZ A,C", "g"), (1, ["B0", "B1"], "H(B)", "g"), (2, ["B0", "D0"], "CRZ B,D", "g"), (3, ["D0", "D1"], "H(D)", "g")], 5)
ax.text(0.9, 0.5, "Same gates, same SWAPs, same unitary; only the order of two commuting diagonal gates on A0 changes, and B's chain starts one step earlier. Measured: depth -7% on prism's routes alone, -3% net on top of the dependency DAG (paper set, 3 seeds).", fontsize=9, color="#5c6470", wrap=True)
plt.tight_layout(); out = "/tmp/claude-1000/-home-evm9-prism/1ae99356-0e84-472f-8923-fc3178a9233e/scratchpad/fig/before_after_explainer.png"; plt.savefig(out, dpi=110); print(out)
