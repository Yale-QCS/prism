---
name: project_xonrail_cancelrailx
description: O3 physical resynthesis emits X-on-rail (rx frames around crz); CancelRailX pass fixes it; benign blast radius (fidelity-only)
metadata: 
  node_type: memory
  type: project
  originSessionId: 12e56f20-a335-4d1e-8209-9e2167a2f6d2
---

2026-06-18: `physical_pm`'s O3 stage (`PHYSICAL_RESYNTHESIS=True` → level 3)
emits **X-on-rail**: `ConsolidateBlocks`+`UnitarySynthesis` fuse 2Q blocks, but
the dual-rail ISA's only 2Q gates (`crz`/`rswap` parametric, `swap` degenerate)
aren't a fixed KAK basis, so Qiskit's generic synthesis straddles the `crz`
entangler with `rx(±π)` 1Q frames. Those are forbidden single-rail X (leakage +
mis-pricing).

**Blast radius (verified BENIGN):** on the real suite prism `rx=0` on 23/24
circuits; only `rg_qft_multiplier` triggered it. Counting metrics UNCHANGED — the
resynthesis swapped 6 `crz`→6 `rx`, 1:1 in `active_gates` (metrics live in
`utils/metrics.py`; `FREE_GATES={rz,u1,p,z}`, so `rx` counts but the swap nets
out). **No published swap/depth/gate number is wrong.** The only real exposure
was fidelity: `crz` (inter-rail SWS ~7e-3) → `rx` (intra-rail ~7e-4), a ~10×
under-price on affected circuits. The big resynth on/off baseline swing is O3's
*legitimate* VF2 re-routing ([[feedback_keep_better_routing]]), not this bug;
prism is unaffected by O3 entirely (101→101 swaps).

**Fix:** `CancelRailX` `TransformationPass` (`staged_pms.py`, `post_optimization`
hook) propagates each `rx(θ≡π mod 2π)` rightward as a Pauli-X frame
(`X·rz(θ)=rz(-θ)·X`; `X_t·crz=crz(-θ)`; `X_c·crz=crz(-θ)·rz(θ)_t`; rides `swap`)
until pairs annihilate; exact incl. global phase; prep `x`/measure/`rswap`
materialize-and-leave. Keeps O3's consolidation AND removes rx. `PHYSICAL_
RESYNTHESIS=False` also zeros rx but drops the baselines' VF2 chance → inflates
prism's apparent advantage, so it's the wrong fix. See [[project_init_crz_herald]].
