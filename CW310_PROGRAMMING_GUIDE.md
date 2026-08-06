# How the CW310 HQC-G target was built & programmed

A step-by-step record of how the HQC-G (SHAKE256) side-channel target gets from
source RTL to a running, verified FPGA on the **ChipWhisperer CW310 "Bergen"**
board — so you can reproduce it later. There is a short **CW305** portability
note at the end (§7), since that's the board in the lab.

> TL;DR: `vivado -mode batch -source syn/build_bitstream.tcl` builds
> `syn/build/cw310_hqc_top.bit`, then
> `python SCA_scripts/cw310_program_test.py` flashes it, sets the clock, and
> fires G ops that are checked bit-exactly against `hashlib.shake_256`.

---

## 0. Hardware / board

| item | value |
|---|---|
| Board | ChipWhisperer **CW310** ("Bergen") |
| FPGA | Xilinx **Kintex-7 XC7K410T-FBG676**, speed grade **-2** |
| Host link | USB (ChipWhisperer NAEUSB register file / "mailbox") |
| Capture | **PicoScope 6000a** — chan A = power, chan B = trigger (NOT a CW scope) |
| Target clock | 10 MHz from the CW310 on-board PLL, output 2 |

The CW310 is used **target-only**: the ChipWhisperer library talks to the FPGA's
register file over USB, while a separate PicoScope does the power capture. That's
why `cw.target(scope=None, ...)` is called with `scope=None`.

---

## 1. Source files that go into the bitstream

Driven by `syn/build_bitstream.tcl`:

**Keccak / SHAKE256 core** (`hdl/shake256/`, Verilog-2001, order matters — package
and `clog2` first because they are ``` `include ```-d):
`keccak_pkg.v`, `clog2.v`, `rc.v`, `keccak_math.v`, `transform.v`,
`stateram_inference.v`, `state_ram.v`, `data_path.v`, `control_path.v`,
`keccak_top.v`.

**ChipWhisperer infrastructure** (`hdl/fpga/common/`):
`cw305_usb_reg_fe.v` (USB register front-end — the host "mailbox"),
`clocks.v` (clock/PLL glue).

**SCA target + top** (`hdl/`, SystemVerilog):
`ahb_interface.sv` (USB regs ⇄ AHB-lite bridge),
`hqc_g_ctrl.sv` (the G sequencer / AHB slave that drives Keccak + the trigger),
`cw310_hqc_top.sv` (top level, pin wiring).

**Constraints:** `hdl/cw310.xdc`.

---

## 2. Build the bitstream (Vivado)

Non-project (in-memory) flow, so no `.xpr` is needed.

```powershell
cd C:\Projects\SCA\HQC_SCA\syn
vivado -mode batch -source build_bitstream.tcl
# optional: override the part ->  -tclargs xc7k410tfbg676-2
```

What the TCL does, in order:
1. `create_project -in_memory -part xc7k410tfbg676-2`
2. adds `hdl/shake256` as an **include path** (for `clog2.v` / `keccak_pkg.v`),
3. `read_verilog` all Keccak + CW infra files, `read_verilog -sv` the three
   target `.sv` files, `read_xdc hdl/cw310.xdc`,
4. `synth_design -top cw310_hqc_top -flatten_hierarchy rebuilt`,
5. `opt_design → place_design → phys_opt_design → route_design`,
6. writes reports + `write_bitstream`.

**Outputs** land in `syn/build/`:
- `cw310_hqc_top.bit`  ← the file we program
- `cw310_hqc_top_timing.rpt`, `cw310_hqc_top_utilization.rpt`

> These build artifacts are **git-ignored** (see `.gitignore`) — rebuild them
> from the TCL rather than committing the `.bit`.

---

## 3. Program the FPGA + set the clock (Python)

Everything below is in `SCA_scripts/cw310_program_test.py`. Run it in the x64
Anaconda env that has `chipwhisperer`:

```powershell
& C:\Users\t-mkarabulut\Miniconda3x64\envs\cwhmac\python.exe `
    C:\Projects\SCA\HQC_SCA\SCA_scripts\cw310_program_test.py
```

`program_cw310()` does exactly this:

```python
import chipwhisperer as cw
BSFILE = r"C:\Projects\SCA\HQC_SCA\syn\build\cw310_hqc_top.bit"

target = cw.target(None, cw.targets.CW310, bsfile=BSFILE, slurp=False)
target.bytecount_size = 8            # our ahb_interface uses pBYTECNT_SIZE=8 (stock is 7)

print(target.fpga.isFPGAProgrammed())  # -> True

target.vccint_set(1.0)               # core voltage 1.0 V
target.pll.pll_enable_set(True)
target.pll.pll_outenable_set(False, 0)
target.pll.pll_outenable_set(False, 1)
target.pll.pll_outenable_set(True, 2)  # drive the target clock on PLL output 2
target.pll.pll_outfreq_set(10e6, 2)    # 10 MHz
target.pll.pll_outfreq_set(10e6, 1)
```

Key gotchas (learned the hard way):
- **`scope=None`** — the CW310 is target-only; the PicoScope captures power.
- **`target.bytecount_size = 8`** — our `ahb_interface.sv` sets
  `pBYTECNT_SIZE = 8`; the stock CW310 class defaults to 7 and reads/writes
  will be misaligned if you forget this.
- **Re-attach without reflashing:** `program_cw310(program=False)` calls
  `cw.target(..., bsfile=None)` — much faster for repeated runs once the board
  is already loaded (only re-applies the clock).
- Firmware "1.2.0 is outdated" USB warning is **harmless**.

---

## 4. Host ⇄ FPGA register protocol (the "mailbox")

The stock CW310 register file exposes byte arrays at fixed indices; our
`ahb_interface.sv` turns them into 32-bit AHB word transactions. Indices
(from `ahb_interface.sv`):

| CW reg | index | meaning |
|---|---|---|
| `REG_CRYPT_WR`   | 6 | write-data word |
| `REG_CRYPT_RD`   | 7 | read-data word |
| `REG_CRYPT_ADDR` | 8 | AHB address |
| `REG_CRYPT_CTRL` | 9 | command: 1=write, 2=read |

A word write = set ADDR (8), set WR (6), pulse CTRL (9)=1. A word read = set
ADDR (8), pulse CTRL (9)=2, read RD (7). See `_wr_word` / `_rd_word`.

**Inner `hqc_g_ctrl.sv` AHB register map:**

| name | offset | meaning |
|---|---|---|
| `CTRL`   | 0x00 | bit0 = START (self-clearing) |
| `STATUS` | 0x04 | bit0 = busy, bit1 = done |
| `M0..M3` | 0x10–0x1C | m′[127:96],[95:64],[63:32],[31:0] (MSW first) |
| `THETA0..9` | 0x20–0x44 | θ output, 320 bits = 10 × 32-bit words |

---

## 5. Run one G operation

`run_one_g(target, mprime_int)`:
1. write `m′` to `M0..M3` (MSW first — matches Keccak absorb order),
2. write `CTRL = START (0x1)`,
3. poll `STATUS` until `done` (bit1) — this also drops the hardware trigger,
4. read back `THETA0..9`.

The design computes **θ = SHAKE256(0x03 ‖ m′)**, squeezing 320 bits.
`m′` is 128-bit, absorbed most-significant-byte first
(`0x03 || m'.to_bytes(16, "big")`).

---

## 6. Verify correctness (bit-exact self-check)

`g_loop()` alternates `m′=0` / `m′=1` (the TVLA pair) and checks every hardware
θ against the Python golden model:

```python
import hashlib
msg = bytes([0x03]) + mprime.to_bytes(16, "big")
digest = hashlib.shake_256(msg).digest(40)          # 320 bits
```

A green run ("10/10 G operations returned the correct SHAKE256 theta") proves the
**whole path** `USB → ahb_interface → hqc_g_ctrl → keccak_top` is correct on
hardware. On the PicoScope you should see the trigger on chan B and the Keccak
power signature on chan A. This is the exact state captured in the transcript
(10/10, alternating m′=0/1).

---

## 7. Porting to the CW305 (the lab board)

The lab has a **CW305 (Artix-7 XC7A100T)**. The good news: the host protocol is
**identical** — the register front-end we use is literally `cw305_usb_reg_fe.v`,
and the ChipWhisperer library talks to both boards the same way. To move this
target to the CW305:

1. **Rebuild the bitstream for the CW305 part.** Change the part in
   `build_bitstream.tcl` (or pass `-tclargs`): CW305 is
   `xc7a100tftg256-2` (confirm your exact device/package). The
   `XC7K410T` in this repo is CW310-specific.
2. **New constraints.** `hdl/cw310.xdc` pins are for the CW310; create a
   `cw305.xdc` with the CW305 pinout (clock, USB FE, trigger, LEDs). The CW305
   also exposes its own PLL — reuse ChipWhisperer's CW305 clock example.
3. **Host code.** Swap `cw.targets.CW310` → `cw.targets.CW305` in
   `program_cw310()`. On the CW305, `bsfile=...` programs over USB the same way;
   `vccint_set` / `pll.*` and `bytecount_size = 8` still apply.
4. **Everything else is unchanged** — the AHB bridge, `hqc_g_ctrl`, the Keccak
   core, the register map, `run_one_g`, and the SHAKE256 self-check are
   board-agnostic RTL/host logic.
5. **Capacity check:** the Keccak core + wrapper fits the K7-410T easily; on the
   smaller A100T re-read `*_utilization.rpt` after synth to confirm it fits.

---

## 8. Quick reference — full flow

```powershell
# 1. build the bitstream (Vivado)
cd C:\Projects\SCA\HQC_SCA\syn
vivado -mode batch -source build_bitstream.tcl        # -> syn/build/cw310_hqc_top.bit

# 2. program + clock + verify (x64 conda env with chipwhisperer)
& C:\Users\t-mkarabulut\Miniconda3x64\envs\cwhmac\python.exe `
    C:\Projects\SCA\HQC_SCA\SCA_scripts\cw310_program_test.py
# expect: "FPGA programmed : True", "10/10 ... correct SHAKE256 theta"

# 3. capture / attack scripts then reuse program_cw310() from this module:
#    tvla_hqc.py, oracle_test.py, collect_data.py
```

**Files referenced here:** `syn/build_bitstream.tcl`,
`SCA_scripts/cw310_program_test.py`, `hdl/ahb_interface.sv`,
`hdl/hqc_g_ctrl.sv`, `hdl/cw310_hqc_top.sv`, `hdl/cw310.xdc`,
`hdl/shake256/*`, `hdl/fpga/common/*`.
