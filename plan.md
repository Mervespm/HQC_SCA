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
