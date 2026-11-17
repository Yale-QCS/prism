---
name: reference_dualrail_noise_mehta_sws
description: "Dual-rail SWS noise params (Mehta preprint, App C.1 + Table 3) grounding the fidelity/erasure model: erasure 7e-4 / Z-dephasing 1e-4 per 2q SWS gate, 1q ~10x smaller; the two-axis model (yield<-depth, fidelity<-ops)."
metadata: 
  node_type: memory
  type: reference
  originSessionId: caa6f6e4-aea1-4f21-b83b-4d377e5a1565
---

Noise grounding for the dual-rail fidelity model (`research/scripts/fidelity_lsr/`,
full extraction in `notes_sws.md`). Source: **Mehta et al. arXiv:2503.10935** (2025), SWS =
**Swap-Wait-Swap**. They do NOT implement Hadamard; the 1Q gate is **sqrtX** (differs from H
by S gates), a beamsplitter exchange between the two cavity modes of a logical dual-rail qubit.

**TWO gate tiers (the asymmetry — intra-rail beamsplitter vs inter-rail dispersive CZ):**
- **`crz` = inter-rail SWS CZ, ~500ns** (dispersive via transmon coupler): erasure
  **0.53%** (5.3e-3), residual Z **0.03–0.1%** (N=27: control 3.9e-4 / target 1.1e-4).
- **`rswap`/`x` = intra-rail beamsplitter, ~170ns** (136 target / 208 control; direct
  beamsplitter): erasure **~7e-4** (5.9e-4–8.6e-4), Z **~1e-4** (9e-5–1.1e-4).
- ⇒ the entangler is **~3x slower** + ~7–10x higher erasure than the intra-rail op.
- Routing `swap` = beamsplitter inter-cavity swaps (fast ~100–200ns tier), NOT 3×CZ.
- diagonal Z / RZ: software-tracked phase, **free** (zero error/time) — in `FREE_GATES`.
- Coherence: cavity T1 ~500µs, dual-rail T_ϕ,DR ~5ms (suppressed common-mode dephasing →
  small residual Z); coupler T1 ~70µs is the lossy element (dominates SWS erasure).
- Control:target asymmetry ~4:1 erasure, ~3.5:1 Z (SWS is directional); bit-flip <3ppm.
- (My earlier note had 7e-4/1e-4 as THE numbers; those are the 1Q BEAMSPLITTER tier, not the
  SWS CZ. The CZ is ~10x worse on erasure. Corrected.)

**The model is TWO SEPARATE axes (user, decisive):**
1. **Post-selection yield (LSR) ← DURATION (≈ depth, duration-weighted by tier).** Erasure
   is gate-active-dominated (SWS erasure 5.3e-3 ≫ idle T1 over 500ns ≈ 1e-3), concentrated on
   the crz/SWS layers. Use **duration-weighted depth** = Σ_layer max-gate-duration (crz 500ns,
   bs/swap 170ns, free Z 0). Per-rail survival = ∏ over its gates. The FIXED crz count × 500ns
   is a floor BOTH strategies share; **prism's yield edge is the depth/duration reduction**
   (fewer swap-layers + lower total depth = less wall-clock). X errors → erasures →
   post-selected away. (Earlier "pure depth, rails·depth" was right in spirit; refine to
   tier-weighted duration so the cheap fast swaps aren't overcounted vs the expensive SWS.)
2. **State fidelity ← DURATION dephasing (NOT gate-count residual-Z).** CORRECTED 2026-06-25 by
   sim (`research/scripts/fidelity_lsr/validate_dual_channel.py` + `state_fid.py`): the per-
   gate Z (1e-4 for a 500ns crz) is just T_gate/T_phi, so dephasing is DURATION-driven, total
   exposure ≈ n_log·T_crit/T_phi (T_phi,DR ~5ms), unifying idle+gate Z. prism's shorter T_crit cuts
   STATE infidelity ~50-60% at n=16-24-matched exposure (density-matrix sim). **The TVD trap:**
   Z-dephasing is DIAGONAL → INVISIBLE to a computational-basis bitstring distribution (output TVD
   barely moves over a 100x T_phi sweep). So the fidelity win is real for COHERENCE-SENSITIVE
   workloads (VQE/QPE/subroutines), benign for pure sampling. Never claim a conditional-fidelity /
   TVD win on sampling circuits. The old gate-count `F=(1-pz)^N` framing is superseded.

**Skip-gate / end-of-line check — CONFIRMED in App E (measured), the nuance recalled:** an
erased control is in vacuum so the SWS CZ **switches off → identity on the target** (skip-gate,
measured; small residual Pauli 0.18–0.19%). The recalled nuance: a loss *mid-gate* while the
control is |01⟩ leaves a **known, deterministic conditional dephasing** on the partner (X+Y
0.7% N=1, ~0.094%/gate amortized) ⇒ Pauli-frame / post-processing correctable, NOT random.
Before-gate loss = clean identity; mid-gate loss = trackable residual. This is exactly why
end-of-line erasure detection suffices and mid-circuit checks "don't buy much." Acceptance
factorizes over worldlines (exp(-εX) structurally exact); the conditional dephasing affects
fidelity (2nd order), deferred to a Stim/Aer conditional-error pass.

**Payoff:** ONE lever (qubit-time n_log·T_crit), TWO channels: T1,cav→yield (2-5x shots at scale,
trajectory-sim validated, analytic LSR conservative) and T_phi→STATE fidelity (~50-60% infidelity
cut at scale for coherence-sensitive workloads, DM-sim validated; invisible to sampling TVD). The
CRZ-erasure floor (5.3e-3 × fixed count) is untouchable by routing → physical win is intrinsically
duration-driven, not count-driven; first-order CRZ reduction needs reshape (separate). Frame per
workload, not blanket "fidelity." See [[project_prism_vs_greedy_mechanism]].
