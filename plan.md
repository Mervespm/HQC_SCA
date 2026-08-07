# HQC-G Side-Channel Experiment — Plan & Scope

## Objective
Demonstrate a power/EM side-channel distinguisher on HQC's **G function**
(`theta = SHAKE256(0x03 || m')`) running in isolation on the ChipWhisperer
CW310. The distinguisher (m'=0 vs m'=1, generalised to a TVLA / plaintext-
checking oracle) is the leakage primitive behind chosen-ciphertext key
recovery on HQC decapsulation (Ravi et al., TCHES 2020, ported to HQC).

## Why G / decapsulation
- Decap uses the **fixed** long-term secret `y` → stationary secret, ideal for
  repeated chosen-ciphertext measurement.
- `m' = Decode(v ⊕ u·y)` inside decap; G absorbs `m'` into Keccak. Leaking that
  absorb turns the Keccak into a **PC oracle** (binary: is m' the expected value?).
- Chosen `(u,v)` probes isolate coordinates of `y`'s support → recover `y`;
  then `x = s ⊕ h·y` (public relation) → full secret key.

## Design (this folder) — COMPLETE & SIM-VERIFIED
```
USB pins ─▶ cw305_usb_reg_fe ─▶ ahb_interface (AHB-Lite master)
                                     │
                                     ▼
                              hqc_g_ctrl  (AHB-Lite slave)
                                 ├─ register map (m', CTRL, STATUS, theta)
                                 ├─ G framing sequencer
                                 ├─ keccak_top  (reference SHAKE256)
                                 └─ g_trig_o ─▶ tio_trigger (scope)
```
- `hdl/hqc_g_ctrl.sv`   — DUT: AHB slave + sequencer + Keccak + trigger.
- `hdl/cw310_hqc_top.sv`— CW310 FPGA top.
- `hdl/shake256/*.v`    — reference Keccak SHAKE core (unmodified).
- `hdl/ahb_interface.sv`, `hdl/fpga/common/*`, `hdl/cw310.xdc` — CW infra.

### G framing (verified bit-exact vs Python `hashlib.shake_256`)
7 input words → 10 output words:
`0x40000140` (out hdr, 320-bit θ) · `0x80000088` (in hdr, 136 bits) ·
`0x00000003` (G domain sep) · m'[127:96] · m'[95:64] · m'[63:32] · m'[31:0].

### Trigger
`g_trig_o` HIGH across absorb→permute→squeeze (~96 crypto-clock cycles),
driven purely by hardware timing → identical, fixed-width capture window per
op, independent of host/USB latency. Rising edge = scope arm.

## Verification status
| Step | Command | Result |
|------|---------|--------|
| Keccak-only isolation | `sim_g/run_g.do` | θ differs for m'=0/1, DONE |
| θ bit-exact vs Python | `python` SHAKE256 ref | MATCH (m'=0 and m'=1) |
| Full pin-level FPGA path | `hdl_tb/compile_cw310.do` | **ALL TESTS PASSED** |
| Bitstream | `syn/build_bitstream.tcl` | see `syn/build/` |

## Bitstream
`cd syn; vivado -mode batch -source build_bitstream.tcl`
→ `syn/build/cw310_hqc_top.bit` for CW310 (Kintex-7 XC7K410T-FBG676, -2).
Override part: `... -tclargs <part>`.

## Capture / TVLA scripts (SCA_scripts/) — DONE, hardware-ready
- `cw310_program_test.py` — host driver. `program_cw310()`, `run_one_g(target, m')`
  (writes m', pulses START, waits DONE, reads θ), θ self-check vs hashlib.
  **Verified on real HW: 10/10 correct θ (m'=0 → ee812081…, m'=1 → e1ec1018…).**
- `pico_scope.py` — PS6000a wrapper (copied from HMAC rig). Only change:
  `TOTAL_CORE_CYCLES = 200` (HQC-G Keccak window ~96 cyc + margin/tail) vs HMAC's
  381*2. Chan A = power (AC ±100 mV ×1), chan B = trigger (AC ±1 V, 0.15 V rising,
  ×10). `Scope()` = 0 pre-trigger (trigger-aligned TVLA).
- `tvlaCalc.py` — generic Welford/Welch TVLA engine (copied verbatim from HMAC).
- `tvla_hqc.py` — **the m'=0 vs m'=1 leakage campaign** (Ravi et al. Kyber-style
  two-class distinguisher). Per trace flips a coin → m'=M0 (class0) or m'=M1
  (class1), arms scope, fires G, `tCalc.addTrace(trace, coin)`. Every TRACE_STEPS
  saves: first/second-order TVLA (|t|>4.5 = leak), the two class-mean traces
  overlaid, and their **difference-of-means** (the direct "0 vs 1" picture), plus
  a resumable pickle. Output: `SCA_scripts/PowerTrace_HQC_G/<timestamp>/`.
  Validated offline on synthetic two-class data: peak |t|=12 at the injected
  leak sample; class-mean/diff CSV+PNG render correctly.

### Run the campaign (device connected, PicoScope GUI CLOSED)```
& "$env:USERPROFILE/Miniconda3x64/envs/cwhqc/python.exe" tvla_hqc.py
```
Tune on the live rig: chan-A range (`A_RANGE_V`) so the signal fills ±range
without clipping; `TOTAL_CORE_CYCLES` if the trigger window differs from sim;
`M1` to target a different m' bit/coordinate. Watch |t| exceed ±4.5 at the
Keccak-absorb samples → that is the PC-oracle leakage result.

## Remaining work (needs the physical device)
1. **Run TVLA campaign** with `tvla_hqc.py` and confirm |t|>4.5 separation
   between m'=0 and m'=1 (tune scope range/window live).
2. **PC-oracle attack**: script chosen `(u,v)` decap inputs and use the Keccak
   leak as the binary oracle to recover `y`, then compute `x` and the full key.
   (This step targets the *full decap* on real HW; the G-only target here is the
   leakage/threshold characterisation vehicle.)

## Notes
- Default parameter set **hqc128** (m'=128 bit, θ=320 bit). For hqc192/hqc256 the
  in-header (`0x800000c8` / `0x80000108`) and m' word count change — extend the
  sequencer + register map accordingly.
- Anaconda is approved for Python lib management (per user).
- Do NOT modify the HQC reference RTL; only wrap it.

---

## Oracle & key-recovery campaign — STATUS (updated 2026-08-06)

### Honest re-profiling (the central correction)
The paper oracle must profile the **natural HQC class pair** the attack really
queries — `m′=0` (RS decode SUCCESS) vs decode-FAILURE garbage — NOT the
artificial `m′=0` vs `m′=1`. Faithful profiling gives the honest single-query
oracle **≈74 %** (was an inflated ~99 %). The ceiling is physical: ~17 % of
decode-failures have `m′` with Hamming weight ≈ 0, indistinguishable from a
success (the confounder `u·y` sprays the other 65 secret bits).

### What raises accuracy (measured, device-grounded)
| lever | effect | verdict |
|---|---|---|
| same-ciphertext averaging | FLAT (74.5→73.8 %, twice on device) | ❌ dead end (noise-free device) |
| better classifier / preprocessing | ties ~73 % | ❌ dead end |
| **fix #7 ciphertext design (systematic-region fillers)** | oracle 74→**76 %**, \|t\| 13.3→16.8 | ✅ device-confirmed |
| **majority vote over R independent ciphertexts** | per-bit → ≥99.9 %, full key ~99 % | ✅ the real amplifier |
| **soft-LLR combining vs hard vote** | ~40 % fewer queries (R 51→31 @p=0.74) | ✅ new contribution |

### The three accuracy numbers (never conflate)
1. single-**trace** oracle **≈74–76 %** (one query),
2. per-**bit** after voting **≥99.9 %**,
3. full-**key** **≈99 %** at R≈31 (soft) / R≈51 (hard) → ~2,700–4,700 queries,
   same order as Ravi et al. Kyber (~2,100–2,900).

### Artifacts (SCA_scripts/paper_results/)
`paper_key_results.csv` (+`.md`) — master table · `fix7_device.csv` — device A/B ·
`fix7_construction.csv` — offline construction sweep · `soft_vs_hard.csv`+`.png` —
amplification · `linalg_completion.csv` — linear-algebra tail recovery ·
`results_datasets/` — the two side-by-side oracle datasets + pro figures.

### Highest device-measured oracle = 76.0 % (do NOT report 78 %)
The **best value we actually measured on the CW310 is 76.0 %** (fix #7,
`fix7_device.csv`). The **78 % is only the offline Hamming-weight model** in
`fix7_construction.csv`; its `max_sys_fillers` vs `RS_T_sys` gap is sampling
noise (both are the same `n_filler=15, region=sys` construction), so it is NOT a
separate stronger lever and is not reported as the headline number.

### Closing the recovery gap — linear-algebra completion (Schamberger Sec. 3.3)
We do **not** need all 66 support positions from the oracle. Given the
confidently recovered part `P ⊂ supp(y)`, the missing `w−|P|` positions (the
`n−n1·n2 = 5` structural tail) are finished by the public relation
`s = x + h·y, HW(x)=w`: brute-force the tail until `HW(x̂)=w`. Verified in
`hqc_attack_sim.py --mode complete` and swept in `linalg_completion.py`:
**30/30 full keys recovered & verified for every missing∈{0..5}**, cost ≤ 2³·³
HW-checks. This turns our partial 60/66 oracle result into a **proven full,
verified key break** with zero extra oracle queries. Fallback for a weaker
oracle: side-channel-informed modified Prange ISD (Schamberger Sec. 3.4).

### Novelty vs Schamberger et al. (first HQC KEM power SCA)
They: **software** Cortex-M4, **BCH** decoder (old HQC), ~100 % software oracle.
Us: **FPGA hardware**, **HQC-RMRS** Keccak-`G` leak, physical single-trace
oracle 74–76 %. We reuse their linear-algebra completion + ISD to close our
hardware oracle's partial-support gap; the oracle-construction and
hardware-leakage results are the new contribution.
amplification. Honest figures in `HQC_SCA/honest_figs/`. Narrative:
`HONEST_ORACLE_SCENARIO.md`.

---

## K-oracle breakthrough — 2026-08-06

**Key insight:** In real HQC decapsulation the FO transform applies **implicit
rejection** — on decode FAILURE the shared-secret hash K receives `sigma`
(a fixed per-key random secret, HW ≈ 64), NOT random decode garbage. On decode
SUCCESS it receives `m = 0` (HW = 0). This `0` vs `sigma` pair is:
- confounder-free (sigma is always high-weight, never near-zero → no HW≈0 collision)
- attack-realistic (exactly what the real device computes)
- measurable on the EXISTING G bitstream (write `m_reg = 0` or `m_reg = sigma`)

**Device result** (`k_block0_test.py`, N=4000, 156.25 MS/s, 15.6 samp/clk):
- **single-trace oracle: 100.0%**, peak |t| = 273.8, FP=0 FN=0
- compared to G oracle: 74.4–76.0%

**Attack query model** (`paper_results/k_attack_model.csv`):
Both attacks must scan all N1×N2=17,664 probeable ring positions to find
the 66 secret support positions (we don't know which 66 in advance).

| oracle | p | R per position | total queries | vs Schamberger'22 |
|---|---|---|---|---|
| G baseline | 74.4% | 23 | 406,272 | 0.2× (5× worse) |
| G fix #7 | 76.0% | 20 | 353,280 | 0.2× (5× worse) |
| **K oracle** | **100%** | **1** | **17,664** | **4× fewer** |

**Minimum traces:** ~200 profiling + 17,664 attack = ~17,864 total.
K oracle is **23× fewer queries than our G oracle** and **4× fewer than
Schamberger et al. PQCrypto'22** (the best prior HQC attack, ~72,000 queries).

**Why G is expensive:** at p=74%, R=23 repetitions per position × 17,664
positions = 406K total. The low oracle accuracy multiplies the scan cost.
At K's p=100%, R=1 suffices: scan cost = position count only.

**No new bitstream needed:** sigma is the message-field content at Keccak block 0,
same hardware, just different m_reg value. The full K hash (mc = sigma ‖ u ‖ v) is
common-mode across both classes at blocks 1–32; all oracle leakage is in block 0.

### New scripts
`k_block0_test.py` — device capture; `hqc_k_ref.py` — reference model;
`paper_results/k_attack_model.csv` — oracle comparison table.

### Remaining / optional (large future work)
- Full-decap hardware target (decoder + re-encrypt + K in one FPGA design).
- OT-PCA / block-sparsity scan to reduce attack queries below 17,664.

### Settled dead ends (do not revisit)
- **max-Hamming-weight fillers** (`--high_hw`): strongest leak (\|t\|=24.5) but
  oracle 74.2 %, tied with baseline — raising failure HW also raises success HW,
  confounder overlap unchanged. fix #7 sys-region (76 %) is the ceiling.
- **Higher sample rate** (1250 MS/s / 95 250 samples): no gain over 156 MS/s.
- **Same-ciphertext averaging**, **classifier/preprocessing tweaks**: no gain.
- **Artificial m'=0 vs m'=1 pair** (`oracle_test.py`, `M0,M1=0,1`): hits ~100 %
  but is NOT the attack-realistic oracle — must not be used as the paper number.
