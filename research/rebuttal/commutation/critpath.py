import sys, warnings; warnings.filterwarnings("ignore"); sys.path.insert(0, "scripts/paper")
from collections import Counter, defaultdict
from qiskit import qpy
from paper_common import make_topologies
from marabbecca.encodings import DualRail
from marabbecca.lowering.commit import SearchBudget
from marabbecca.staged_pms import build_pm
from marabbecca.utils.metrics import is_free
b, topo = sys.argv[1], sys.argv[2]
cm = make_topologies(8)[topo]
budget = SearchBudget(objective="swaps", heuristic_config="qiskit_sabre", tie_break="load", layout_starts=40, refinement_iterations=16, prism_swap_trials=40)
qc = qpy.load(open(f"artifacts/paper/manifests/circuits/{b}_n8.qpy", "rb"))[0]
for strat in ("greedy", "prism"):
  for com in (False, True):
    out = build_pm(cm, DualRail, strategy=strat, seed=0, budget=budget, commute_diagonal=com).run(qc)
    lay = out.layout.initial_layout.get_physical_bits()
    lab = {p: (int(v._register.name[1:]), v._index) for p, v in lay.items() if v._register.name[1:].isdigit()}
    t = defaultdict(int); prev = {}; node = []
    for ins in out.data:
        qs = [out.find_bit(q).index for q in ins.qubits]; nm = ins.operation.name
        logical = tuple(sorted({lab[q][0] for q in qs if q in lab}))
        if nm == "swap": a, c = qs; lab[a], lab[c] = lab.get(c), lab.get(a)
        if is_free(ins.operation): continue
        s = max(t[q] for q in qs); p = max(qs, key=lambda q: t[q])
        k = len(node); node.append((nm, logical, prev.get(p)))
        for q in qs: t[q] = s + 1; prev[q] = k
    # walk back the critical path from the last op
    k = max(prev.values(), key=lambda i: i); path = []
    k = max(range(len(node)), key=lambda i: 0)
    # pick the op finishing last
    end = max(t, key=t.get); k = prev[end]
    while k is not None: path.append(node[k]); k = node[k][2]
    kinds = Counter(n for n, _, _ in path); touched = Counter(q for _, lg, _ in path for q in lg)
    print(f"{strat:6s} commute={com!s:5s} depth={max(t.values()):3d} critical path: {dict(kinds)}  logical qubits on it: {dict(touched.most_common(4))}")
