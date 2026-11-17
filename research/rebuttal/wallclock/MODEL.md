# Dual-rail device model and simulator

`sim.MEHTA_IDLE` is the device model for every current dual-rail row (`data/v3_*.jsonl`, from 2026-10-11). Its parameters are the measured values of the two-qubit dual-rail cavity device of Mehta et al. (Quantum Circuits, Inc.), arXiv:2503.10935, Tables 2 and 3, read 2026-10-07 from the arXiv HTML. "C" is the control dual-rail qubit and "T" the target. `sim.MEHTA` has the same parameters with the superseded additive dephasing channel of section 1a. It produced `data/v2_*.jsonl` and stays in `sim.py` so that those rows can be regenerated. Every statement here is checked against `sim.py` or the cited table. Evan asked for this file: "if this is going to go into the paper we need a really tight, precise description of the error models, the simulator, the results."

**Calibration correction, 2026-10-11.** Mehta's Fig. 3 and main text identify the
CZ target's measured Z error as dephasing during the gate, governed by its idle
coherence, so the measured control and target Z errors are full gate
contributions. `sim.MEHTA` also dephased both rails at the background rate during
every gate and so charged in-gate dephasing twice. One CR_z(π) between two encoded
|+> states with noiseless zero-duration preparation has infidelity 0.000728913
under `sim.MEHTA` and 0.000499957 under `sim.MEHTA_IDLE`, which equals
1 − (1 − 3.9e−4)(1 − 1.1e−4), the value of the quoted gate Z probabilities alone.
The correction changes only the dephasing channel. P_keep and duration are the
same on every saved circuit (relative difference at most 1.4e−15 at n = 8), so
the acceptance, SPAM yield and timing results do not move. At n = 8 the median
workload-mean kept-shot fidelity rises from 0.977639 to 0.982391 for Greedy and
from 0.978602 to 0.982900 for PRISM, and the median paired PRISM − Greedy
workload-mean fidelity difference falls from +0.000936 to +0.000600.

## 1. What the simulator computes

- **Input.** A routed rail circuit from the compiler. Its operations are:
  - `crz` (SWS CR_z between one rail of each of two pairs)
  - `rswap` (beamsplitter within a pair)
  - `swap` (beamsplitter between rails of two pairs, the routing SWAP)
  - `rz` (virtual, no time)
  - zero-time preparation placeholders (`x` labeled synthetic, `joint_herald`).

  Over the 480 saved n = 8 PRISM and Greedy circuits, these are the only operation types.
- **State.** Each rail is one cavity mode with at most one photon. Every operation conserves photon number, and the terminal erasure check discards every shot in which a pair has lost its photon. The kept state is therefore the no-jump branch, which lies in the span of the 2^n occupation states with one photon per pair. The simulator evolves this unnormalized density matrix exactly. Its trace is P_keep, and its fidelity to the noiseless output of the same circuit, divided by P_keep, is the kept-shot fidelity F. The kept state lies in the codespace, so F is the logical state fidelity.
- **Trajectories (n ≥ 12).** P_keep stays exact. The Z errors are sampled over 1000 trajectories per circuit.
- **Time.** Each rail keeps its own clock. An operation starts when all its rails are free. Pairs that take part in no gate other than SWAP are not simulated (`sim.live_pairs`).
- **Noise.** Loss acts on whole pairs, so it scales the kept state and leaves it undistorted.
  1. Each operation multiplies the state by (1 − e) for each live pair it touches, with e from §2 by role.
  2. Each live pair also loses its photon at 1/T1 for every moment outside the operations that touch it, from t = 0 to the end of the circuit.
  3. Each live pair's logical coherence decays by exp(−2γ idle_p) over its idle time idle_p of §3, the time outside the union of the timed operations that touch the pair. γ is the per-rail rate of §2, so 2γ is the logical phase-flip rate. The channel is a logical Z with probability (1 − exp(−2γ idle_p))/2. It commutes with CR_z, rz, X and SWAP, which are diagonal or relabelings in the occupation basis, and not with a beamsplitter on the pair, so the simulator applies the idle time accumulated since the previous beamsplitter on the pair just before each beamsplitter on it and the remainder at the end of the circuit. This is exact for the time-ordered channel.
  4. After each operation, each named rail takes its residual Z error of §2. In the codespace a Z on either rail of a pair is the pair's logical Z. These measured errors are the whole dephasing of the operation. No background dephasing is charged during an operation on any rail of a pair it touches.

### 1a. Superseded additive variant (`sim.MEHTA`, rows `data/v2_*.jsonl`)

Items 1, 2 and 4 are the same. In place of item 3, each rail dephases at γ for all of its time from t = 0 to D, idle or in a gate, so every live pair's logical coherence decays by exp(−2γD) whatever its schedule, and the measured gate Z errors are added on top. Compared with the corrected channel it multiplies each pair's coherence by a further exp(−2γ busy_p), with busy_p = D − idle_p. `Device.idle_dephasing` selects the channel, and `resim.py --device mehta` regenerates the v2 rows.

## 2. MEHTA parameters

| quantity | model | source in Mehta et al. |
|---|---|---|
| cavity T1 (idle loss) | 356.5 µs, the rate average of the four cavities | Table 2: C 231 and 411 µs, T 652 and 342 µs |
| erasure per CR_z | control pair 4.00e−3, target pair 0.96e−3 | Table 3: C 0.400(4)%, T 0.096(4)% |
| erasure per beamsplitter (`rswap`, `swap`, `rx`) | 7.24e−4 on each live pair touched, the C/T mean | Table 3, per X√X gate: C 8.56e−4, T 5.92e−4 |
| CR_z duration | 0.5 µs | "∼500 ns" |
| beamsplitter duration | 0.2 µs | C 208 ns, T 136 ns |
| CR_z residual | Z: control 3.9e−4, target 1.1e−4 | Table 3: C 0.039(1)%, T 0.0112(9)%. The X parts, 2.8e−6 and 0.5e−6, are omitted |
| beamsplitter residual | Z, 9.9e−5 | iRB C 9.0e−5, T 1.08e−4 (caption value, the table prints 1.08e−5) |
| dephasing | γ = 2.3e−4 per µs on each rail, a logical coherence time 1/(2γ) of 2.2 ms, charged over each pair's idle time only (§1) | echo C 4.0 ms, T 4.8 ms, read as Pauli phase-flip times. The result sits between the Ramsey times (C 3.1 ms, T 1.5 ms), the reading without dynamical decoupling |
| bit flip | omitted | C 520 ms, T 1100 ms |
| erasure check | ideal in the current circuit-only comparison | Mehta Table 3 gives total SPAM erasure assignment, not conditional false-positive rates; it does not specify a complete detector channel for these circuits |
| SWAP between pairs | the intra-pair beamsplitter's duration, erasure and residual | not characterized (two-qubit device), an assumption |

Three approximations are stated with the model.
- Mehta's erasure values average over the states of their experiment. The model applies them whatever the state.
- The model gives both rails of a pair the same T1. With C's 231 and 411 µs, the no-jump branch would distort the kept state by about (Δγ·t/2)²/4 ≈ 5e−5 per qubit at t = 15 µs.
- The X parts of the CR_z residual and the bit flips are below 3e−6 per gate and are omitted.

## 3. Closed form for P_keep (the paper's Eq. 1, `validate.py` check 3)

P_keep = exp(−Σ_p idle_p / T1) × Π_ops Π_{p touched by op} (1 − e_{op, role})

The factors are defined as follows.

- **Pairs.** A pair is the two rail contents that one `joint_herald` joins. Contents are followed through `swap`s, so a pair keeps its identity wherever its photon moves.
  - A pair is live if it takes part in any operation other than `swap` or its own preparation (`sim.live_pairs`). The compiler no longer prepares idle pairs (561bcfb), so in new circuits every heralded pair is live.
- **Schedule.** Each rail has a clock. An operation starts at the maximum clock of its rails and lasts its duration: CR_z 0.5 µs, beamsplitters 0.2 µs, and 0 for `rz`, `joint_herald` and synthetic preparations. D is the maximum final clock.
- **Idle time.** idle_p = D − |∪ [start, start + τ] over the operations with τ > 0 that touch p|. Each pair is exposed from t = 0 to D.
- **Pairs touched**, with e by role:
  - `crz`: the pair holding the control rail's content (e = 4.00e−3) and the pair holding the target rail's content (e = 0.96e−3).
  - `rswap` or `rx`: the one pair whose two rails it acts on (e = 7.24e−4).
  - `swap`: each distinct live pair whose content is on either of its rails (e = 7.24e−4 each). That is two pairs for a swap between pairs, one for a swap within a pair or a swap with a rail that holds no live content, and none for a swap between two empty rails.
  - `rz`, `joint_herald` and synthetic preparations: none.
- **Counted form.** In counts, P_keep = exp(−I / T1) · (1 − 4.00e−3)^{N_crz} · (1 − 0.96e−3)^{N_crz} · (1 − 7.24e−4)^{B}.
  - I = Σ_p idle_p.
  - N_crz is the number of CR_z gates.
  - B is the number of beamsplitter pair-touches: one per `rswap`, plus one or two per `swap` as defined above.
- **Reference.** `validate.loss_parts(qc, device)` returns (n, D, I, Σ ln(1 − e)) from the schedule alone, and `validate.closed_form` assembles them. On every MEHTA row the largest relative gap to the simulated P_keep is 3.2e−14 at n = 8, 9.2e−14 at n = 12 and 1.4e−12 at n = 16, where −ln P_keep reaches about 21, so the general bound is 2e−12. MEHTA_IDLE has the same loss channel and gives the same P_keep (`sim.idle_time` computes idle_p for both the loss and the dephasing). `validate.pair_losses` splits −ln P_keep into one term per pair, which `detection.py` uses.
- **Proxy.** `scripts/paper/export_device.py` computes the paper's Eq. 1 from the scale rows with the same parameters (model `mehta`, 754818d).

## 4. Validation (`validate.py`, output in `validate_output.txt`, under 2 minutes)

1. The noiseless codespace state matches `Statevector` of the routed rail circuit to 6e−15 (3 saved n = 8 circuits, one per arm).
2. With every noise rate ×25, P_keep and F match a full rail-level density matrix with loss as explicit Kraus jumps to 1e−15 (3 random 3-qubit circuits on 8 rails, LEGACY, MEHTA and MEHTA_IDLE). For MEHTA_IDLE the reference dephases both rails of a pair at γ over the pair's idle time, where `sim.py` dephases one mask bit at 2γ.
3. P_keep matches the closed form of §3 to 3e−14 relative (20 saved circuits, three devices). MEHTA and MEHTA_IDLE give the same P_keep.
4. 1000 trajectories match the exact density matrix at n = 8: F within 1.1 standard errors for MEHTA and 0.9 for MEHTA_IDLE, and P_keep to 1e−14 (4 saved circuits).

`make validate-sim` runs it, and `make test` includes it. The 26 saved circuits it reads are tracked in `data/circuits_n8/`.

## 5. LEGACY, the model before MEHTA

`sim.LEGACY` is the device of the submission's §5.4 and of `metrics.device_success`, kept so that the rows in `data/legacy/` stay reproducible. It has the same durations, residuals and dephasing as MEHTA, but loss is rail decay at a cavity T1 of 500 µs (the "∼500 µs" of Mehta's text) and nothing else, so P_keep = exp(−nD/T1). `run.py --loss` and `resim.py --loss` added an SWS coupler term of 2e−3 per CR_z on the control rail, from luferlang `new_sws`. Against Table 3, LEGACY had about 2× too little erasure per CR_z on the control and per beamsplitter, and 40% too little idle loss, so its absolute P_keep was optimistic. In LEGACY a routing SWAP cost loss only through time, while in MEHTA each SWAP PRISM saves also saves a direct erasure. The current paper changes are in `../rebuttal_minimal.patch`, Section 5.

## Direct bare-transmon model (P1, 2026-10-08)

`bare_report.transmon_device` defines the active comparison at nominal width eight.
The uniform reference uses T1 = 136.5 us and one-qubit average error 2.88e-4 from
[AbuGhanem, Table IV](https://arxiv.org/pdf/2410.00916), and T2 = 89 us, CZ duration
42 ns and one-qubit duration 25 ns from [Google Quantum AI, section II and
Supplement I](https://arxiv.org/html/2408.13687v1). These are a composite parameter
model, not the characterization of one device. CZ average error is tested at 0.1%
and 0.3%; neither point is asserted to bound all transmons. RZ is virtual.
Preparation and terminal measurement are ideal on both platforms.

Gate relaxation is included in the specified gate error, not added to it. For a
k-qubit gate of duration t, independent amplitude damping and pure dephasing have
entanglement fidelity

`f_th = [(1 + exp(-t/T1) + 2 exp(-t/T2))/4]^k`.

The target average gate error r gives `f_target = 1 - (d+1)r/d`, with d = 2^k.
After composing thermal noise with a depolarizing channel of strength p,
`f_total = (1-p) f_th + p/d^2`. Thus the residual strength is
`p = (f_th - f_target)/(f_th - 1/d^2)`. A target below the relaxation floor is
rejected. `bare_report.py --check` constructs the full Kraus channels and verifies
the resulting average gate fidelities, independently of this scalar derivation.

For CZ errors 0.001 and 0.003, the residual depolarizing strengths are
0.0006665531 and 0.0033350002. For both SX and X they are 0.0003277973. Idle
relaxation uses the same T1 and T2. This replaces the historical bare sweep's
addition of full RB-equivalent depolarization *and* relaxation during the gate.
That historical sweep and its fitted calibration do not supply the new fidelity
results. The direct report evolves the density matrix without a fitted correction.

The dual-rail arm uses the channel of section 1 (`sim.MEHTA_IDLE`, rows
`data/v3_n8.jsonl`, selected by `bare_report.py --dualrail`), including its
extrapolation of the beamsplitter residual to routing exchanges. The rows in
`data/v2_n8.jsonl` from the additive variant of section 1a are superseded.
Exact simulation is exact for these stipulated noise channels; it does not
validate either hardware extrapolation. Accepted circuit-state fidelity excludes
measurement assignment errors. Device repetition overhead remains a separate
parameter in `(D+h)/P_keep`.

## Separate SPAM yield sensitivity

[Mehta, Table 3 and Appendix A.2](https://arxiv.org/html/2503.10935v2) report
one-round total SPAM erasure assignment of 6.43% and 6.79% for two dual-rail
qubits. These rates combine preparation and measurement rejection. The report
uses each rate as a uniform `e` in `P_total = P_circuit (1-e)^n`, with n taken
from each circuit, including VBE's smaller actual width. This assumes rejection
is independent across qubits and of circuit loss. It does not add a second loss
factor for preparation/readout duration or treat e as a conditional false alarm.
Workload shot cost is `mean(1/P_total)` across topology and seed, followed by
medians and ranges across all workloads. The two rates are sensitivity choices,
not an uncertainty interval for the device. Neither missed erasures nor logical
SPAM errors are inferred from this factor, so circuit fidelity is not relabeled
as fidelity after SPAM. A complete detector and repetition protocol remains open.
