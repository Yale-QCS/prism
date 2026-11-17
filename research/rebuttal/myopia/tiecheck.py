import sys, random, math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/"research/rebuttal/oracle")); sys.path.insert(0,str(ROOT/"scripts/paper"))
import fixed_layout as F, oracle as O
from qiskit.transpiler import CouplingMap
from marabbecca.lowering.commit_policies.prism_routing import PrismRouting
same=diff=0; commits_diff=0
for name,builder in O.INSTANCE_CATALOG[:12]:
    inst,gp,edges=builder(True); cmap=CouplingMap(edges+[(b,a) for a,b in edges])
    dag=F.lowered(gp,inst.n_logical)
    rng=random.Random(name)
    for k in range(4):
        layout=tuple(rng.sample(range(inst.n_phys),inst.n_rails))
        out={}
        for tb in ("load","default"):
            pol=PrismRouting(cmap,enc=F.LocalInit,seed=0,tie_break=tb)
            ctx=pol._precompute(dag)
            v2p=[0]*ctx.n_virt
            for q,virt in ctx.q_to_virt.items():
                reg=next(r for r in dag.qregs.values() if q in r)
                v2p[virt]=layout[2*int(reg.name[1:])+list(reg).index(q)]
            v2p+=[p for p in range(ctx.n_phys) if p not in set(v2p)]
            tr,_,_=pol._route(ctx,v2p,7,4)
            out[tb]=( [e for e in tr[0] if e[0]==1], tr[1], [e for e in tr[0] if e[0]==0])
        if out["load"][:2]==out["default"][:2]: same+=1
        else: diff+=1
        if out["load"][2]!=out["default"][2]: commits_diff+=1
print("swap-seq+final-layout identical:",same,"differ:",diff,"; runs where committed realizations differ:",commits_diff)
