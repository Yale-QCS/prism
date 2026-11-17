# Dual-rail SWS noise model: extracted parameters

Source: **Mehta et al., arXiv:2503.10935** (2025), "Bias-preserving and error-detectable
entangling operations in a superconducting dual-rail system." SWS = **Swap-Wait-Swap**
(the inter-rail CZ). Numbers below are verbatim from the paper (main text, Table 2/3,
App C.1/E). Quantum Circuits Inc. is the company; this is the Yale/QCI lineage (Teoh 2023,
Chou 2023 precede it).

## THE gate-tier table (the asymmetry that drives the model)

Two physically distinct two-mode operations, and they are NOT the same cost:

| our gate | physical op | mechanism | duration | erasure/gate | residual Z/gate |
|----------|-------------|-----------|----------|-------------|-----------------|
| `crz` (inter-rail entangler) | **SWS CZ** | dispersive: swap excitation cavity→transmon coupler, wait χ·t, swap back | **~500 ns** | **0.53(2)%** (5.3e-3) | 0.03–0.1% (3e-4–1e-3); N=27 Z control 3.9e-4 / target 1.1e-4 |
| `rswap`/`x` (intra-rail) | **beamsplitter** | direct beamsplitter between the two cavity modes of one logical qubit | **136–208 ns** (~170 ns avg; "~100 ns" fast swaps) | **5.9e-4 – 8.6e-4** (~7e-4) | **9e-5 – 1.1e-4** (~1e-4) |

**The headline timing number you asked for:** inter-rail SWS/CZ ~500 ns vs intra-rail
beamsplitter ~170 ns ⇒ **the entangler is ~3x slower** than the single-qubit / rail
operation. The intra-rail op is fast because it is a direct beamsplitter between two linear
cavity modes; the inter-rail CZ is slow because it routes the excitation through the
dispersive coupler (g_ac/2π = 4.23 MHz; entangling χ_bc/2π = −1.51 MHz; t_wait ≈ 2.08 µs
for ϕ_e = π — note the wait dominates, so the "~500 ns" is the swap-in/swap-out envelope and
the full CZ including wait is longer; the paper quotes ~500 ns as the operational figure).

Single-qubit gate is sqrtX (X_{π/2}), NOT Hadamard (differs by S gates), realized as the
beamsplitter exchange. Control gate 208 ns, target gate 136 ns (g_bs/2π = 1.78 / 2.55 MHz).

**Control:target error asymmetry** (the SWS is directional): erasure 0.400(4)% control vs
0.096(4)% target (~4:1); Z 0.039(1)% control vs 0.0112(9)% target (~3.5:1). Bit-flip
(un-converted X) is < 3 ppm — i.e. T1 is almost fully converted to erasure, as designed.

## Coherence times (Table 2/3)

- Cavity T1 (single-photon decay): 231–652 µs (simple-estimate value **T1,cav ~ 500 µs**).
- Cavity T2R: 433–1001 µs; **dual-rail dephasing T_ϕ,DR ~ 5 ms** (the DR encoding suppresses
  common-mode dephasing → this is why residual Z is small).
- Coupler (transmon) T1 ~ 70 µs (text assumption 50 µs); T_ϕ echo ~1001 µs (text ~500 µs).
  The coupler is the lossy element; the SWS erasure budget is dominated by the transient
  excitation in the coupler during the swap.

## Erasure propagation / skip-gate (App E) — the nuance you couldn't recall

This is exactly the clean-propagation model, measured:
- **Control erased (|00⟩) before/during the CZ ⇒ the gate switches OFF: identity on the
  target.** (skip-gate confirmed — the entangler doesn't fire on a vacuum rail.) Small
  residual Pauli 0.19(2)% / 0.18(2)% for |00⟩ / |10⟩.
- **Loss occurs MID-gate while control in |01⟩ ⇒ conditional dephasing (a CZ-type error) on
  the target**, X+Y error 0.7(1)% (N=1), ~0.094% per-gate amortized. THE NUANCE: a loss
  *during* the entangler leaves a *known, deterministic* dephasing on the partner (not
  nothing, not random) ⇒ Pauli-frame / post-processing correctable. Before-gate loss = clean
  identity; mid-gate loss = trackable residual. This is why **end-of-line erasure detection
  suffices** and mid-circuit checks "don't buy much": the propagation is deterministic given
  the final occupation pattern.

## What this means for OUR model (corrects the earlier lump)

1. `crz` (SWS, 500 ns) and `rswap`/`x` (beamsplitter, ~170 ns) are **different tiers** —
   `dr_sim.py` counts them separately (crz=SWS erasure, rswap/swap/x=beamsplitter erasure).
   Routing `swap` (swap two logical qubits between cavity sites) decomposes to **beamsplitter**
   swaps (the fast inter-cavity ~100–200 ns op), NOT 3×CZ ⇒ swaps are cheap in *error* but still
   cost *time*.
2. **Yield axis (erasure, ← duration):** use **duration-weighted depth** = Σ_layer
   max-gate-duration, with 500 ns for crz-layers, ~170 ns for bs/swap-layers, 0 for free Z.
   Per-rail survival = exp(−t_rail / T1_eff) where erasure is ~T1-limited but coupler-dominated
   during SWS (so per-SWS erasure 5.3e-3 ≫ the ~T1 idle rate over 500 ns ≈ 500ns/500µs = 1e-3).
   ⇒ erasure is **gate-active-dominated**, concentrated on the SWS layers. prism's win = fewer
   swap-layers + lower total depth ⇒ less wall-clock ⇒ higher yield.
3. **Fidelity axis (residual Z, ← ops):** crz Z ~1e-4 (FIXED count across strategies),
   bs/swap Z ~1e-4 each (prism has fewer). So prism's conditional-fidelity gain comes from the
   swap reduction on the ~1e-4 tier; the fixed crz Z is the floor both share.
4. Honest split: the SWS erasure (5.3e-3) ≫ beamsplitter erasure (7e-4), so **yield is
   dominated by the crz count × its 500 ns** — which is FIXED across strategies. prism's yield
   edge is the *depth/duration* reduction (fewer idle + swap layers), not fewer crz. Quantify
   both the fixed-crz floor and the prism depth-driven delta.

## Still to pull (others, lower priority)

- Teoh 2023 (PNAS, dual-rail encoding w/ cavities) + Chou 2023 (2307.03169): foundational
  T1/erasure-conversion ratio, idle erasure rate per µs (for the idle-loss term).
- QCI "breakthrough 2-qubit gates" page: the ~100 ns inter-cavity swap figure.
