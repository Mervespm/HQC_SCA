"""CW310 program + clock test for the HQC-G (SHAKE256) side-channel target.

Standalone CW310-side check (no PicoScope involved). It:
  1. connects to the CW310 over USB (scope=None -- PicoScope does capture, not a CW scope),
  2. programs the HQC-G bitstream,
  3. prints FPGA done / programmed status,
  4. sets VCCINT=1.0V and starts PLL1 output at 10 MHz (same as the HMAC/MLDSA reference).

Uses the STOCK cw.targets.CW310 class, so it does not need a custom register
class registered yet -- this just proves the board, USB, FPGA config and clock
are alive, then fires G = SHAKE256(0x03 || m') operations whose trigger/power
show in the PicoScope GUI. Every op's theta is checked bit-exactly against the
Python hashlib.shake_256 reference, so a green run means the whole
USB -> ahb_interface -> hqc_g_ctrl -> keccak_top path is correct on hardware.

Run from the x64 conda env:
  & "$env:USERPROFILE/Miniconda3x64/envs/cwhqc/python.exe" cw310_program_test.py
"""
import hashlib
import time

import chipwhisperer as cw

BSFILE = r"C:\Projects\SCA\HQC_SCA\syn\build\cw310_hqc_top.bit"
TARGET_FREQ = 10e6

# ---- CW register-file (mailbox) indices - from ahb_interface.sv ----
REG_CRYPT_WR   = 6
REG_CRYPT_RD   = 7
REG_CRYPT_ADDR = 8
REG_CRYPT_CTRL = 9
WRITE_CMD = 1
READ_CMD  = 2

# ---- inner hqc_g_ctrl AHB register offsets (see hqc_g_ctrl.sv) ----
CTRL_ADDR   = 0x00    # bit0 START (self-clearing)
STATUS_ADDR = 0x04    # bit0 busy, bit1 done
M_ADDR      = 0x10    # M0..M3 : m'[127:96],[95:64],[63:32],[31:0]
THETA_ADDR  = 0x20    # THETA0..THETA9 (320-bit output)

# ---- CTRL / STATUS bits ----
CTRL_START   = 0x1
STATUS_BUSY  = 0x1
STATUS_DONE  = 0x2

# ---- HQC-G parameters (hqc128) ----
G_DOMAIN   = 0x03     # HQC G domain-separator byte
M_BYTES    = 16       # m' = 128 bit
THETA_WORDS = 10      # theta = 320 bit = 10 x 32-bit words

# ---- TVLA / oracle test messages (m' = 0 and m' = 1) ----
M_FIXED  = 0
M_VARYING = 1


# ------------------------------------------------------------------ #
# mailbox helpers (stock CW310 target, no custom class needed)        #
# ------------------------------------------------------------------ #
def _wr_word(target, addr, value):
    target.fpga_write(REG_CRYPT_ADDR, list(int.to_bytes(addr, 4, "little")))
    target.fpga_write(REG_CRYPT_WR,   list(int.to_bytes(value & 0xFFFFFFFF, 4, "little")))
    target.fpga_write(REG_CRYPT_CTRL, list(int.to_bytes(WRITE_CMD, 1, "little")))


def _rd_word(target, addr):
    target.fpga_write(REG_CRYPT_ADDR, list(int.to_bytes(addr, 4, "little")))
    target.fpga_write(REG_CRYPT_CTRL, list(int.to_bytes(READ_CMD, 1, "little")))
    return int.from_bytes(target.fpga_read(REG_CRYPT_RD, 4), "little")


def _wr_reg(target, addr, value, n_words):
    for j in range(n_words):
        word = (value >> (32 * (n_words - 1 - j))) & 0xFFFFFFFF  # MSW first
        _wr_word(target, addr + 4 * j, word)


def _wait(target, mask, timeout=5.0):
    t0 = time.time()
    while (_rd_word(target, STATUS_ADDR) & mask) == 0:
        if time.time() - t0 > timeout:
            return False
        time.sleep(0.001)
    return True


# ------------------------------------------------------------------ #
# HQC-G reference + hardware run                                      #
# ------------------------------------------------------------------ #
def theta_ref_words(mprime_int):
    """Golden theta as 10 little-endian 32-bit words == hardware readback.

    theta = SHAKE256(0x03 || m'), squeeze 320 bits. m' is 128-bit, absorbed
    most-significant-byte first (m'[127:96] word first), so m'.to_bytes(16,'big').
    """
    msg = bytes([G_DOMAIN]) + int.to_bytes(mprime_int, M_BYTES, "big")
    d = hashlib.shake_256(msg).digest(4 * THETA_WORDS)
    return [int.from_bytes(d[4 * i:4 * i + 4], "little") for i in range(THETA_WORDS)]


def run_one_g(target, mprime_int):
    """Run one G op on the FPGA; returns theta as a list of 10 32-bit words."""
    # load m' (M0=m'[127:96] first, MSW-first matches the absorb order)
    _wr_reg(target, M_ADDR, mprime_int, 4)
    # kick one G op
    _wr_word(target, CTRL_ADDR, CTRL_START)
    # wait for completion (also drops the trigger)
    _wait(target, STATUS_DONE)
    # read theta back
    return [_rd_word(target, THETA_ADDR + 4 * i) for i in range(THETA_WORDS)]


def g_loop(target, iterations=0, delay=0.2):
    """Fire G ops so the trigger/power shows in the PicoScope GUI.

    Alternates m'=0 (fixed) and m'=1 (varying) -- the TVLA pair -- and checks
    each theta against the SHAKE256 reference. iterations=0 runs forever
    (Ctrl+C to stop) -- good for watching the scope.
    """
    print("  looping G ops -- watch PicoScope chan B (trigger) / chan A (power).")
    print("  alternating m'=0 / m'=1 (TVLA pair); press Ctrl+C to stop.")
    i = 0
    passed = 0
    try:
        while iterations == 0 or i < iterations:
            mprime = M_FIXED if (i % 2 == 0) else M_VARYING
            theta = run_one_g(target, mprime)
            expected = theta_ref_words(mprime)
            i += 1
            ok = (theta == expected)
            if ok:
                passed += 1
            th_hex = "".join(f"{w:08x}" for w in theta)
            status = "OK " if ok else "FAIL"
            print(f"    G #{i:03d} m'={mprime}: {status}  theta=0x{th_hex}")
            if not ok:
                exp_hex = "".join(f"{w:08x}" for w in expected)
                print(f"      expected 0x{exp_hex}")
            time.sleep(delay)
    except KeyboardInterrupt:
        pass
    print(f"\n  {passed}/{i} G operations returned the correct SHAKE256 theta.")
    return passed == i and i > 0


def program_cw310(verbose=True, program=True):
    """Connect to the CW310 and set the clock. Returns target.

    program=True  : (re)flash the HQC-G bitstream, then set clock. Use this the
                    first time, or after a power cycle / new bitstream.
    program=False : just re-attach to the already-programmed FPGA (bsfile=None,
                    no reflash) and re-apply the clock. Much faster -- use this
                    for repeated runs once the board is already loaded.
    """
    scope = None  # PicoScope handles capture; CW310 is target-only.
    if verbose:
        if program:
            print("Connecting to CW310 and programming HQC-G bitstream ...")
            print(f"  bsfile = {BSFILE}")
        else:
            print("Re-attaching to already-programmed CW310 (no reflash) ...")
    target = cw.target(scope, cw.targets.CW310,
                       bsfile=BSFILE if program else None, slurp=False)
    target.bytecount_size = 8  # our ahb_interface uses pBYTECNT_SIZE=8 (stock default is 7)

    if verbose:
        print(f"  FPGA programmed : {target.fpga.isFPGAProgrammed()}")

    target.vccint_set(1.0)
    target.pll.pll_enable_set(True)
    target.pll.pll_outenable_set(False, 0)
    target.pll.pll_outenable_set(False, 1)
    target.pll.pll_outenable_set(True, 2)
    target.pll.pll_outfreq_set(TARGET_FREQ, 2)
    target.pll.pll_outfreq_set(TARGET_FREQ, 1)
    if verbose:
        print(f"  target clock    : {TARGET_FREQ/1e6:.1f} MHz on PLL output 2")
    return target


def main():
    target = program_cw310()
    print("CW310 program + clock test PASSED.")
    print()
    print("Running G operations on the FPGA ...")
    g_loop(target, iterations=10, delay=1.0)
    return target


if __name__ == "__main__":
    main()
