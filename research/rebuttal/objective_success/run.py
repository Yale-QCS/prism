"""run_fairness with route selection by overall success, -log(P_keep * F_cond), on the measured device model.

  .venv/bin/python research/rebuttal/objective_success/run.py --config research/rebuttal/objective_success/scale16.toml --quick --workers 4 --out ../../../research/rebuttal/objective_success/data/success_n16_s0.jsonl
"""
import math
import sys

sys.path.insert(0, "scripts/paper")
import run_fairness as rf
from marabbecca.lowering.commit_policies import prism_routing as pr
from marabbecca.utils.metrics import device_success, pair_exposure, physical_duration

T1 = 4 / (1 / 231 + 1 / 411 + 1 / 652 + 1 / 342)
ERASURE = {"crz_control": 4.00e-3, "crz_target": 0.96e-3, "rswap": 7.24e-4, "swap": 7.24e-4, "rx": 7.24e-4}
_orig = pr.score


def score(qc, objective="swaps", n_logical=0):
    if objective != "error":
        return _orig(qc, objective, n_logical)
    idle, touches = pair_exposure(qc)
    log_keep = -idle / T1 + sum(c * math.log1p(-ERASURE[k]) for k, c in touches.items())
    _, fidelity = device_success(n_logical, physical_duration(qc), qc.count_ops())
    return (-(log_keep + math.log(fidelity)), *_orig(qc, "error", n_logical)[1:])


pr.score = score
sys.argv = ["run_fairness.py", *sys.argv[1:]]
rf.main()
