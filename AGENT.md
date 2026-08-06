# HQC_SCA — Agent Instructions

> Editable by the user. The agent reads this file at the start of HQC side-channel work.

## Goal
Side-channel attack on the **HQC** code-based KEM hardware (Yale / Sanjay Deshpande
implementation in `../HQC-CPA/pqc-hqc-hardware`). Mirror the proven HMAC-256 CW310
setup (`../HMAC_SCA`) and the MLDSA CW305 setup (`../HQC-CPA/MLDSA-SCA`).

## Attack target (decided)
- **Operation:** DECAPSULATION (uses the *fixed* long-term secret `y` → stationary secret,
  perfect for repeated chosen-ciphertext measurement).
- **Leak point:** the **G function**, i.e. `theta = G(m')` computed as **SHAKE256** over the
  decrypted message `m'`. On real HW there is ONE shared `keccak_top` (instantiated once in
  `hqc_kem_joint_design.v`), time-multiplexed; G vs K are told apart by the domain-separator
  word on `shake_din`:
    - **G (theta):** `THETA_D_DOMSEP` = hqc128 `0x80000088`, hqc192 `0x800000c8`, hqc256 `0x80000108`
    - **K (shared secret):** `HASH_LB_DOMSEP` = hqc128 `0x80000290`, hqc192 `0x80000058`, hqc256 `0x800000b0`
- **Why G:** leaking the Keccak absorb of `m'` recovers `m'` → instantiates a **plaintext-checking
  (PC) oracle** (Ravi et al., TCHES 2020, ported to HQC's code-based decoder). Chosen ciphertexts
  + PC oracle recover the secret support of `y`; then `x = s ⊕ h·y` (public relation) → full key.

## What we are building (this folder)
A standalone **G = SHAKE256(m')** FPGA target with the SAME host interface as HMAC:
- `hdl/hqc_g_ctrl.sv`   — AHB-Lite slave wrapping the real `keccak_top`; loads `m'`, runs G,
                          exposes `theta`, and drives `g_trig_o` HIGH across the permutation.
- `hdl/cw310_hqc_top.sv`— CW310 top: USB pins → `cw305_usb_reg_fe` → `ahb_interface` → `hqc_g_ctrl`;
                          `tio_trigger = g_trig`.
- Shared infra copied from HMAC_SCA: `ahb_interface.sv`, `fpga/common/*`, `cw310.xdc`.

## Parameter set
Default **hqc128** (K=128 bit m', WEIGHT=66, N=17669, theta=320 bit). Keep `parameter_set`
overridable for hqc192 / hqc256.

## Toolchain / conventions
- **ModelSim:** Intel FPGA 18.1 (`C:\intelFPGA\18.1\modelsim_ase`). Sim flow mirrors
  `../HMAC_SCA/hdl_tb/compile256_cw310.do` (`.vf` file list + `vsim -c -do`).
- **Python libs: YOU CAN USE ANACONDA to manage Python libraries** — we will edit the
  ChipWhisperer `cw310.py` / capture scripts later for the real device (ScopeWhisperer).
- HQC RTL source of truth: `../HQC-CPA/pqc-hqc-hardware/hardware`
  (common/shake256, decap, encap). Do not modify the HQC RTL; wrap it.
- Verify `theta` **bit-exactly** against the real `encap`/`decap` reference in sim before trusting HW.
- No device yet — first get the interface + full G working in simulation.

## Reference vectors
`../HQC-CPA/pqc-hqc-hardware/hardware/decap/tb/memory_files/{u,v,y}_128.in` — decap KAT inputs.

## Status
- [x] Folder scaffolded, shared CW infra copied, attack target decided (G/SHAKE256 in decap).
- [x] Keccak-only G isolation tb (`sim_g\keccak_g_tb.v`) runs in ModelSim, no hang.
- [x] theta bit-exact verified: RTL == Python SHAKE256(0x03 || m')[:40] for m'=0 and m'=1.
      G framing = 7 words: 0x40000140 (out hdr, 320-bit theta), 0x80000088 (in hdr, 136 bits),
      0x00000003 (G domain sep), then 4 words of m'. Squeeze = 10 words. Reset core between calls.
- [x] `hdl/hqc_g_ctrl.sv` — self-contained AHB-Lite slave wrapping keccak_top + G sequencer +
      g_trig_o (HIGH across absorb->permute->squeeze). No Caliptra deps.
- [x] `hdl/cw310_hqc_top.sv` — CW310 top (USB -> usb_reg_fe -> ahb_interface -> hqc_g_ctrl,
      tio_trigger = g_trig).
- [x] Pin-level bench `hdl_tb/cw310_hqc_top_tb.sv` + `compile_cw310.do`: drives the physical USB
      pins, runs G(m'=0) and G(m'=1), theta bit-exact PASS. Trigger window ~96 cycles per G op.
- [x] `syn/build_bitstream.tcl` — Vivado non-project build for CW310 (xc7k410tfbg676-2).
- [ ] Program bitstream + ChipWhisperer capture scripts (after device arrives).

## Register map (hqc_g_ctrl, AHB word address)
| Addr | Name   | Dir | Meaning                         |
|------|--------|-----|---------------------------------|
| 0x00 | CTRL   | W   | bit0 = START (self-clearing)    |
| 0x04 | STATUS | R   | bit0 = busy, bit1 = done         |
| 0x10 | M0     | W   | m'[127:96] (absorbed first)      |
| 0x14 | M1     | W   | m'[95:64]                        |
| 0x18 | M2     | W   | m'[63:32]                        |
| 0x1C | M3     | W   | m'[31:0]  (absorbed last)        |
| 0x20..0x44 | THETA0..9 | R | 320-bit theta output       |

Host sequence per G op: write M0..M3, write CTRL=1, poll STATUS bit1, read THETA0..9.
theta words read back are little-endian == Python `shake_256(bytes([3])+m').digest(40)`.

## Build / run commands (verified)
- Keccak-only isolation sim: `cd sim_g; vsim -c -do run_g.do`
- Full pin-level FPGA-path sim: `cd hdl_tb; vsim -c -do compile_cw310.do`  (expect "ALL TESTS PASSED")
- Bitstream: `cd syn; & "C:\Xilinx\Vivado\2023.1\bin\vivado.bat" -mode batch -source build_bitstream.tcl`
  Output: `syn/build/cw310_hqc_top.bit`.
