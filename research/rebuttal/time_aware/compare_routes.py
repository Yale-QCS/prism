"""Compare routing SWAPs and realization choices run by run between two row files (default-flag reproduction check).

Usage: .venv/bin/python research/rebuttal/time_aware/compare_routes.py <before.jsonl> <after.jsonl>
"""

import json
import sys
from collections import Counter

before, after = ({r["run_id"]: r for r in map(json.loads, open(p))} for p in sys.argv[1:3])
c = Counter()
for rid, a in after.items():
    b = before.get(rid)
    if b is None:
        c["missing in before"] += 1
        continue
    same_swaps = a["router_inserted_swaps"] == b["router_inserted_swaps"]
    same_choices = a.get("realization_choices") == b.get("realization_choices")
    c[(a["strategy"], "swaps same" if same_swaps else "swaps differ", "choices same" if same_choices else "choices differ")] += 1
for k, v in sorted(c.items(), key=str):
    print(v, k)
