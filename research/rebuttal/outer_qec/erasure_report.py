"""Summarize every cell of the fixed ideal-erasure pilot, including uncertain points."""

import itertools
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np

DATA = Path(__file__).resolve().parent / "data" / "ideal_erasure_v2"
SEEDS = list(range(0, 2000, 100))
PROBABILITIES = [1e-4, 3e-4, 1e-3, 3e-3, 1e-2]


def summarize():
    """Report paired routing-seed variation separately from finite-shot uncertainty."""
    rows = {}
    hashes, trees = {}, {}
    for basis, topo, arm, seed in itertools.product(
        ("X", "Z"), ("grid", "hex_lattice"), ("logical", "greedy", "prism"), SEEDS
    ):
        path = DATA / f"{basis}_{topo}_{arm}_{seed}.json"
        r = json.loads(path.read_text())
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        assert (r["basis"], r["topo"], r["arm"], r["seed"]) == (basis, topo, arm, seed)
        assert r["protocol"] == "ideal-erasure-v2" and r["rounds"] == 3
        assert r["n_detectors"] == 18 + r["readout_checks"]
        assert r["validation"]["complete_measurement_constraints"] == r["n_detectors"] + 1
        assert [s["p"] for s in r["results"]] == PROBABILITIES
        assert all(s["shots"] == 200_000 for s in r["results"])
        assert r["validation"]["checked_fault_columns"] == 2 * r["n_sites"]
        assert len(r["sites"]) == len(r["columns"]) == r["n_sites"]
        assert r["objective"] == (None if arm == "logical" else "error")
        assert not r["reschedule"]
        if arm != "logical":
            assert r["budget"] == dict(heuristic_config="qiskit_sabre", tie_break="load",
                                       layout_starts=40, refinement_iterations=16, prism_swap_trials=40)
        commit = r["compiler_commit"]
        if commit not in trees:
            trees[commit] = subprocess.check_output(
                ["git", "rev-parse", f"{commit}:src", f"{commit}:crates"],
                cwd=DATA, text=True).splitlines()
        assert trees[commit] == next(iter(trees.values()))
        if "compiler_tree" in r:
            assert r["compiler_tree"] == trees[commit]
        rows[basis, topo, arm, seed] = r
    picks = np.random.default_rng(0).integers(0, len(SEEDS), size=(20_000, len(SEEDS)))
    summary = []
    for basis, topo in itertools.product(("X", "Z"), ("grid", "hex_lattice")):
        arms = {a: [rows[basis, topo, a, s] for s in SEEDS]
                for a in ("logical", "greedy", "prism")}
        cost = {a: {key: float(np.mean([r[key] for r in rr]))
                    for key in ("swaps", "active_duration", "n_sites", "ambiguous_singles", "ambiguous_pairs")}
                for a, rr in arms.items()}
        pair_g = np.array([r["ambiguous_pairs"] for r in arms["greedy"]])
        pair_pr = np.array([r["ambiguous_pairs"] for r in arms["prism"]])
        pair_interval = np.quantile(
            1 - pair_pr[picks].sum(axis=1) / pair_g[picks].sum(axis=1), [0.025, 0.975]).tolist()
        print(f"\n{basis} memory / {topo}: mean over all {len(SEEDS)} seeds")
        for a, values in cost.items():
            print(a, json.dumps(values))
        for i, p in enumerate(PROBABILITIES):
            counts = {a: np.array([r["results"][i]["ambiguous"] for r in rr])
                      for a, rr in arms.items()}
            g, pr = counts["greedy"], counts["prism"]
            total_g, total_pr = int(g.sum()), int(pr.sum())
            reduction = 1 - total_pr / total_g if min(total_g, total_pr) >= 100 else None
            # Low-count points stay visible, but cannot support a precise ratio.
            seed_interval = mc_interval = None
            if min(total_g, total_pr) >= 100:
                ratios = pr[picks].sum(axis=1) / g[picks].sum(axis=1)
                seed_interval = np.quantile(1 - ratios, [0.025, 0.975]).tolist()
                var_g = (g * (1 - g / 200_000)).sum()
                var_pr = (pr * (1 - pr / 200_000)).sum()
                se_log = np.sqrt(var_g / total_g**2 + var_pr / total_pr**2)
                ratio = total_pr / total_g
                mc_interval = [float(1 - ratio * np.exp(1.96 * se_log)),
                               float(1 - ratio * np.exp(-1.96 * se_log))]
            entry = dict(basis=basis, topo=topo, p=p,
                         probability={a: float(c.sum() / (200_000 * len(SEEDS))) for a, c in counts.items()},
                         logical_error_probability={a: float(c.sum() / (400_000 * len(SEEDS)))
                                                    for a, c in counts.items()},
                         counts={a: c.tolist() for a, c in counts.items()},
                         prism_reduction=reduction,
                         seed_bootstrap_95=seed_interval,
                         fixed_routes_mc_95=mc_interval,
                         exact_pair_reduction=1 - cost["prism"]["ambiguous_pairs"] / cost["greedy"]["ambiguous_pairs"],
                         exact_pair_seed_bootstrap_95=pair_interval,
                         mean_cost=cost)
            summary.append(entry)
            rates = " / ".join(f"{entry['logical_error_probability'][a]:.7f}"
                               for a in ("logical", "greedy", "prism"))
            if reduction is None:
                comparison = "ratio unresolved (low event counts)"
            else:
                lo, hi = seed_interval
                comparison = f"reduction {100 * reduction:.1f}% [{100 * lo:.1f}, {100 * hi:.1f}]"
            print(f"p={p:g}: P_L Logical-SABRE / Greedy / PRISM = {rates}; {comparison}")
        pair_reduction = 1 - pair_pr.sum() / pair_g.sum()
        print(f"Unrecoverable two-location pattern reduction: {100 * pair_reduction:.1f}% "
              f"[{100 * pair_interval[0]:.1f}, {100 * pair_interval[1]:.1f}]")
    output = dict(cells=len(rows), samples=sum(s["shots"] for r in rows.values() for s in r["results"]),
                  checked_fault_columns=sum(r["validation"]["checked_fault_columns"] for r in rows.values()),
                  seeds=SEEDS, shots_per_cell=200_000, probabilities=PROBABILITIES,
                  logical_error_definition="Optimal guessing error = P_ambiguous / 2 for one logical bit under uniform heralded replacement",
                  compiler_trees=trees, row_sha256=hashes,
                  analysis_sha256=sorted({r.get("analysis_sha256", r["source_sha256"]["erasure_pilot.py"])
                                          for r in rows.values()}),
                  source_hashes={k: sorted({r["source_sha256"][k] for r in rows.values()})
                                 for k in ("qec_circuits.py", "route.py", "to_stim.py", "erasure_pilot.py")},
                  results=summary)
    (DATA / "summary.json").write_text(json.dumps(output, indent=2) + "\n")
    print(f"\n{output['cells']} cells; {output['samples']:,} erasure samples; "
          f"{output['checked_fault_columns']:,} independent fault-column checks.")
    print("Bracketed intervals bootstrap the observed per-seed estimates in pairs. "
          "Conditional Monte Carlo intervals for the fixed routes are in summary.json. "
          "Neither covers model uncertainty. Low-count ratios are withheld.")
    print("P_L is half the ambiguity probability under this uniform erasure model. "
          "The explicit decoder audit checks that identity; it is not a conversion from acceptance.")


if __name__ == "__main__":
    summarize()
