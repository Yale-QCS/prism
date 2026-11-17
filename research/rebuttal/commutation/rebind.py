"""Same SWAPs, re-pick each CR_z's rail pair among those adjacent at commit time, by earliest start."""
import sys, warnings; warnings.filterwarnings("ignore"); sys.path.insert(0, "scripts/paper")
from collections import defaultdict
from qiskit import qpy
from paper_common import make_topologies
from marabbecca.encodings import DualRail
from marabbecca.lowering.commit import SearchBudget
from marabbecca.staged_pms import build_pm
from marabbecca.utils.metrics import is_free
BENCH = ["dj","qaoa","draper_qft_adder","modular_adder","qft","qpeexact","qpeinexact","qftentangled","bmw_quark_copula","hhl","ae","cdkm_ripple_carry_adder","full_adder","vqe_two_local","rg_qft_multiplier","multiplier"]
topo = sys.argv[1]
cm = make_topologies(8)[topo]; adj = set(map(tuple, cm.get_edges()))
budget = SearchBudget(objective="swaps", heuristic_config="qiskit_sabre", tie_break="load", layout_starts=40, refinement_iterations=16, prism_swap_trials=40)
def timeline(out, rebind):
    lay = out.layout.initial_layout.get_physical_bits()
    lab = {p: (int(v._register.name[1:]), v._index) for p, v in lay.items() if v._register.name[1:].isdigit()}
    where = {l: p for p, l in lab.items()}
    t = defaultdict(int)
    for ins in out.data:
        qs = [out.find_bit(q).index for q in ins.qubits]; nm = ins.operation.name
        if nm == "swap" and len(qs) == 2:
            a, b = qs; la, lb = lab.get(a), lab.get(b); lab[a], lab[b] = lb, la
            if la: where[la] = b
            if lb: where[lb] = a
        if is_free(ins.operation): continue
        if nm == "crz" and rebind and len(qs) == 2 and lab.get(qs[0]) and lab.get(qs[1]) and lab[qs[0]][0] != lab[qs[1]][0]:
            qa, qb = lab[qs[0]][0], lab[qs[1]][0]
            pairs = [(where[(qa, ra)], where[(qb, rb)]) for ra in (0, 1) for rb in (0, 1)]
            pairs = [p for p in pairs if p in adj or p[::-1] in adj]
            qs = list(min(pairs, key=lambda p: max(t[p[0]], t[p[1]])))
        s = max(t[q] for q in qs)
        for q in qs: t[q] = s + 1
    return max(t.values())
tot = defaultdict(int)
for b in BENCH:
    qc = qpy.load(open(f"artifacts/paper/manifests/circuits/{b}_n8.qpy", "rb"))[0]
    row = []
    for com in (False, True):
        out = build_pm(cm, DualRail, strategy="prism", seed=0, budget=budget, commute_diagonal=com).run(qc)
        d0, d1 = timeline(out, False), timeline(out, True)
        tot[(com, 0)] += d0; tot[(com, 1)] += d1; row += [d0, d1]
    print(f"{b:24s} order {row[0]:4d}->{row[1]:4d}   commute {row[2]:4d}->{row[3]:4d}")
print("TOTAL order", tot[(False,0)], "->", tot[(False,1)], "  commute", tot[(True,0)], "->", tot[(True,1)])
