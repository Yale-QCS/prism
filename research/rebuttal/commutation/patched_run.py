"""run_fairness with PrismRouting patched for a hypothesis; MODE=final_only | window<K>."""
import os, sys
sys.path.insert(0, "scripts/paper")
import run_fairness as rf
from marabbecca.lowering.commit_policies.prism_routing import PrismRouting

MODE = os.environ["MODE"]
if MODE == "final_only":
    orig_pre, orig_route = PrismRouting._precompute, PrismRouting._route
    def _precompute(self, dag):
        self.commute_diagonal = False
        order = orig_pre(self, dag)
        self.commute_diagonal = True
        self._comm_ctx, self._order_ctx = orig_pre(self, dag), order
        return order
    def _route(self, ctx, v2p, seed, swap_trials):
        if swap_trials == self.swap_trials and ctx is self._order_ctx:
            ctx = self._comm_ctx
        return orig_route(self, ctx, v2p, seed, swap_trials)
    PrismRouting._precompute, PrismRouting._route = _precompute, _route
elif MODE.startswith("window"):
    K = int(MODE[6:])
    def _build_deps(virts_used, diagonal=()):
        n = len(virts_used); diagonal = diagonal or (False,) * n
        succ = [[] for _ in range(n)]; pred = [0] * n
        last_nd, since = {}, {}
        for k, vs in enumerate(virts_used):
            deps = set()
            for v in vs:
                if v in last_nd: deps.add(last_nd[v])
                older = since.get(v, [])
                deps.update(older if not diagonal[k] else older[:-K] if K else older)
            for j in sorted(deps): succ[j].append(k); pred[k] += 1
            for v in vs:
                if diagonal[k]: since.setdefault(v, []).append(k)
                else: last_nd[v] = k; since[v] = []
        return succ, pred
    PrismRouting._build_deps = staticmethod(_build_deps)
elif MODE.startswith("level"):
    W = int(MODE[5:])
    orig = PrismRouting._build_deps
    def _build_deps(virts_used, diagonal=()):
        succ, pred = orig(virts_used, diagonal)
        n = len(virts_used); level = [0] * n
        for k in range(n):  # ops arrive in topological order
            for j in succ[k]:
                level[j] = max(level[j], level[k] + 1)
        by_level = {}
        for k, l in enumerate(level): by_level.setdefault(l, []).append(k)
        existing = [set(s) for s in succ]
        for k in range(n):
            for l in range(0, level[k] - W):
                for j in by_level.get(l, ()):
                    if k not in existing[j]:
                        existing[j].add(k); succ[j].append(k); pred[k] += 1
        return succ, pred
    PrismRouting._build_deps = staticmethod(_build_deps)
else:
    raise SystemExit(MODE)
sys.argv = ["run_fairness.py", *sys.argv[1:]]
rf.main()
