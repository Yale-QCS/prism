"""Print the Section V-D statistics that are computed inside figure.py (Fig. 12) but not printed by it: Fig. 12c medians, proxy-infidelity reductions at 16 logical qubits, and the proxy-to-simulation factors at eight logical qubits."""
import runpy, sys, math
from collections import defaultdict
import numpy as np
import os; FIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "figure.py"); sys.path.insert(0, os.path.dirname(FIG)); g = runpy.run_path(FIG)
DR, TR, quart, W = g["DR"], g["TR"], g["quart"], g["W"]
for n in W:
    print(n, "DR prism med %.3f greedy %.3f | TM cz0.1 %.3f cz0.3 %.3f" % (
        quart([r for r in DR if r["n"] == n and r["a"] == "prism"], "eq18")[0], quart([r for r in DR if r["n"] == n and r["a"] == "greedy"], "eq18")[0],
        quart([r for r in TR if r["n"] == n and r["cz"] == 0.001], "eq19")[0], quart([r for r in TR if r["n"] == n and r["cz"] == 0.003], "eq19")[0]))
for t in ("grid", "hex_lattice", "heavy_hex"):
    by = defaultdict(lambda: defaultdict(list))
    for r in DR:
        if r["n"] == 16 and r["t"] == t: by[r["c"]][r["a"]].append(1 - r["eq18"])
    ratio = [np.mean(v["prism"]) / np.mean(v["greedy"]) for v in by.values()]
    print(t, "proxy infidelity geomean reduction %.2f%%, workloads up %d of %d" % (100 * (1 - math.exp(np.mean(np.log(ratio)))), sum(x > 1 for x in ratio), len(ratio)))
for name, pts in (("dual rail n8", g["scat_dr"]), ("transmon n8", g["scat_tm"])):
    print(name, len(pts), "median proxy/sim infidelity %.3f, proxy>=sim on %d" % (np.median(pts[:, 1] / pts[:, 0]), int((pts[:, 1] >= pts[:, 0]).sum())))
print("geo attempts n16 at T1M: greedy %.2f prism %.2f" % (g["geo"](16, "greedy", g["T1M"]), g["geo"](16, "prism", g["T1M"])))
