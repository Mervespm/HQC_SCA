"""Shared PicoScope 6000a setup for the HQC-G (SHAKE256) SCA rig.

Single source of truth for the scope hardware settings AND the block-capture
logic used by tvla_hqc.py (and any simple-capture script). Adapted from the
HMAC-256 rig -- the ONLY functional change is the capture-window length, which
is derived from the HQC G-function's Keccak compute length instead of HMAC's.

  from pico_scope import Scope, A_RANGE_V, A_PROBE, B_RANGE_V, B_PROBE

  scope = Scope()                  # 0 pre-trigger (TVLA-style, trigger-aligned)
  scope = Scope(pre_trig_frac=0.2) # capture some baseline before the B edge
  scope.arm(); ...; power, trig = scope.read(); scope.close()

Close the PicoScope GUI first -- only one program can own the scope.

--- G capture window ---------------------------------------------------------
The hqc_g_ctrl trigger (g_trig_o) is HIGH across absorb -> Keccak permutation ->
squeeze. In the pin-level sim that window was ~96 crypto-clock cycles (one
Keccak-f[1600] permutation dominates). We capture TOTAL_CORE_CYCLES cycles with
a margin so the whole leaking window plus a little tail always fits.
"""
import ctypes
import atexit
from time import sleep

import numpy as np

from picosdk.ps6000a import ps6000a as ps
from picosdk.PicoDeviceEnums import picoEnum as enums
from picosdk.functions import assert_pico_ok, mV2adc


# =============================== SETTINGS =============================== #
RESOLUTION    = "10BIT"      # "8BIT" / "10BIT" / "12BIT"
# Pick SAMPLING_HZ for the samples/clock you want:
#   samples_per_clock = fs / TARGET_FREQ_HZ
# 6000E timebase law: tb 0..4 -> fs = 5e9 / 2**tb ;  tb>=5 -> fs = 156.25e6 / (tb-4)
#
#   want samp/clk | need fs    | set SAMPLING_HZ =  | timebase
#   --------------+------------+--------------------+---------
#      ~31        | 312.5 MS/s | 312.5e6 (current)  |   4
#      ~62        | 625 MS/s   | 625e6              |   3
#      ~125       | 1.25 GS/s  | 156e6*10           |   2
#      ~250       | 2.5 GS/s   | 2.5e9              |   1
TARGET_FREQ_HZ    = 10e6   # FPGA core clock
TOTAL_CORE_CYCLES = 381*2  # HMAC-256 compute length (5 SHA-256 blocks ~ 381 clks)
SAMPLING_HZ       = 156e6*10  # desired sampling rate 
MARGIN            = 1       # capture extra so the whole busy window fits

# channel A = power
A_COUPLING    = "AC"        
A_RANGE_V     = 0.1          
A_PROBE       = 1           
# channel B = trigger
B_COUPLING    = "AC"         
B_RANGE_V     = 1            
B_THRESH_V    = 0.15         
B_TIMEOUT_US  = 0            
B_PROBE       = 10           
    # chan B probe attenuation (x10 probe, matches GUI)

CAPTURE_TIMEOUT_S = 5.0      # give up if the trigger never fires
# ====================================================================== #

VRANGE = {0.01: 0, 0.02: 1, 0.05: 2, 0.1: 3, 0.2: 4, 0.5: 5,
          1.0: 6, 2.0: 7, 5.0: 8, 10.0: 9, 20.0: 10}
COUPLING = {"AC": enums.PICO_COUPLING["PICO_AC"],
            "DC": enums.PICO_COUPLING["PICO_DC"],
            "DC50": enums.PICO_COUPLING["PICO_DC_50OHM"]}
RESMAP = {"8BIT": "PICO_DR_8BIT", "10BIT": "PICO_DR_10BIT", "12BIT": "PICO_DR_12BIT"}


class ScopeReadError(RuntimeError):
    """A PicoSDK GetValues/RunBlock returned a non-OK status. Carries the raw
    numeric status so unknown codes (missing from picosdk's lookup table, which
    would otherwise KeyError) still produce a clean, catchable error."""
    def __init__(self, status):
        self.status = status
        try:
            from picosdk.constants import PICO_STATUS_LOOKUP
            name = PICO_STATUS_LOOKUP.get(status, f"UNKNOWN(0x{status:04X}={status})")
        except Exception:
            name = f"0x{status:04X}={status}"
        super().__init__(f"PicoSDK status {name}")


class Scope:
    """PS6000a block-capture wrapper: arm() then read() one trace.

    Chan B rising edge triggers; the window length comes from the core-cycle
    formula. read() returns (power_A, trig_B) as np.float64 raw-ADC arrays.

    pre_trig_frac : fraction of the window captured BEFORE the trigger edge
                    (0.0 = trigger-aligned start, used by TVLA;
                     0.2 = keep some baseline, useful for a sanity plot).
    """

    def __init__(self, pre_trig_frac=0.0, verbose=True):
        self.handle = ctypes.c_int16()
        self.res = enums.PICO_DEVICE_RESOLUTION[RESMAP[RESOLUTION]]
        assert_pico_ok(ps.ps6000aOpenUnit(ctypes.byref(self.handle), None, self.res))

        maxADC = ctypes.c_int16()
        ps.ps6000aGetAdcLimits(self.handle, self.res, ctypes.byref(ctypes.c_int16()),
                               ctypes.byref(maxADC))
        self.maxadc = maxADC.value
        bw = enums.PICO_BANDWIDTH_LIMITER["PICO_BW_FULL"]
        self.chA = enums.PICO_CHANNEL["PICO_CHANNEL_A"]
        self.chB = enums.PICO_CHANNEL["PICO_CHANNEL_B"]
        self.raw = enums.PICO_RATIO_MODE["PICO_RATIO_MODE_RAW"]
        self.i16 = enums.PICO_DATA_TYPE["PICO_INT16_T"]

        # turn all channels off, then enable A (power) and B (trigger)
        for c in range(4):
            assert_pico_ok(ps.ps6000aSetChannelOff(self.handle, c))
        assert_pico_ok(ps.ps6000aSetChannelOn(self.handle, self.chA, COUPLING[A_COUPLING],
                                              VRANGE[A_RANGE_V], 0.0, bw))
        assert_pico_ok(ps.ps6000aSetChannelOn(self.handle, self.chB, COUPLING[B_COUPLING],
                                              VRANGE[B_RANGE_V], 0.0, bw))

        # rising-edge trigger on channel B
        thr = mV2adc(B_THRESH_V * 1000.0, VRANGE[B_RANGE_V], maxADC)
        rising = enums.PICO_THRESHOLD_DIRECTION["PICO_RISING"]
        assert_pico_ok(ps.ps6000aSetSimpleTrigger(self.handle, 1, self.chB, thr,
                                                  rising, 0, B_TIMEOUT_US))

        # find a valid timebase and read the ACTUAL sample interval from the device
        # (at 10-bit the 6000E may reject the requested rate and pick a slower one).
        # PS6000a timebase->interval is PIECEWISE:
        #   tb 0..4  -> interval = 2^tb / 5e9  s   (5, 2.5, 1.25 GS/s, 625, 312.5 MS/s)
        #   tb >=5   -> interval = (tb-4) / 156.25e6 s
        # The old single-formula guess landed in the slow range (~52 MS/s). Invert
        # the correct branch so a GS/s request actually maps to the fast range.
        _T = 1.0 / SAMPLING_HZ                       # desired sample interval (s)
        if _T <= 3.2e-9:                             # fast range (>=312.5 MS/s)
            self.timebase = int(min(max(round(np.log2(max(_T * 5e9, 1.0))), 0), 4))
        else:                                        # slow range
            self.timebase = max(5, int(round(_T * 156.25e6 + 4)))
        tint_ns = ctypes.c_double(0)
        maxsmp = ctypes.c_uint64(0)
        while ps.ps6000aGetTimebase(self.handle, self.timebase, 100000,
                                    ctypes.byref(tint_ns), ctypes.byref(maxsmp), 0) != 0:
            self.timebase += 1
            if self.timebase > 30:
                raise RuntimeError("no valid timebase for this resolution")
        self.fs = 1e9 / tint_ns.value

        # samples = core_cycles * (fs/f_core) * margin
        samp_per_clk = self.fs / TARGET_FREQ_HZ
        self.n_samples = int(round(TOTAL_CORE_CYCLES * samp_per_clk * MARGIN))
        self.n_pre = int(self.n_samples * pre_trig_frac)   # samples before trigger
        self.n_post = self.n_samples - self.n_pre
        window_us = self.n_samples / self.fs * 1e6
        if verbose:
            print(f"Scope: {self.fs/1e6:.1f} MS/s (timebase {self.timebase}), "
                  f"{samp_per_clk:.1f} samp/clk")
            print(f"       {TOTAL_CORE_CYCLES} cycles x {MARGIN} = {self.n_samples} "
                  f"samples = {window_us:.1f} us window "
                  f"(pre-trig {self.n_pre})\n")

        # data buffers for A and B -- set ONCE. BOTH min/max buffers are instance
        # attrs (never GC'd) and we pass clear|add so the buffer is actually
        # ADDED (clear alone -> PICO_BUFFERS_NOT_SET at GetValues).
        self.bufA = (ctypes.c_int16 * self.n_samples)()
        self.bufAm = (ctypes.c_int16 * self.n_samples)()
        self.bufB = (ctypes.c_int16 * self.n_samples)()
        self.bufBm = (ctypes.c_int16 * self.n_samples)()
        clear = enums.PICO_ACTION["PICO_CLEAR_ALL"]
        add = enums.PICO_ACTION["PICO_ADD"]
        assert_pico_ok(ps.ps6000aSetDataBuffers(self.handle, self.chA,
                       ctypes.byref(self.bufA), ctypes.byref(self.bufAm),
                       self.n_samples, self.i16, 0, self.raw, clear | add))
        assert_pico_ok(ps.ps6000aSetDataBuffers(self.handle, self.chB,
                       ctypes.byref(self.bufB), ctypes.byref(self.bufBm),
                       self.n_samples, self.i16, 0, self.raw, add))

        # Always release the USB handle on interpreter exit -- even if a script
        # crashes mid-capture. Without this a crash leaves the 6000-series in a
        # hung "Unknown" USB state that needs a physical power-cycle to clear.
        self._closed = False
        atexit.register(self.close)

    def arm(self):
        """Start a block capture (returns immediately; trigger fires it)."""
        ti = ctypes.c_double(0)
        assert_pico_ok(ps.ps6000aRunBlock(self.handle, self.n_pre, self.n_post,
                                          self.timebase, ctypes.byref(ti),
                                          0, None, None))

    def _get_values(self):
        """One GetValues call; raise a clean error instead of a KeyError on an
        unknown PicoSDK status (the stock assert_pico_ok KeyErrors on codes that
        aren't in its lookup table, e.g. 20496, which then crashes the capture)."""
        n = ctypes.c_uint64(self.n_samples)
        ov = ctypes.c_int16(0)
        status = ps.ps6000aGetValues(self.handle, 0, ctypes.byref(n), 1,
                                     self.raw, 0, ctypes.byref(ov))
        if status != 0:
            raise ScopeReadError(status)

    def read(self, retries=3):
        """Wait for the trigger, then return (power_A, trig_B) raw-ADC arrays.

        Transient device errors (a stray PicoSDK status, a missed trigger) are
        retried up to `retries` times by re-arming, instead of crashing and
        losing the whole capture. Only a persistent failure raises.
        """
        for attempt in range(retries + 1):
            try:
                ready = ctypes.c_int16(0)
                waited = 0.0
                ps.ps6000aIsReady(self.handle, ctypes.byref(ready))
                while ready.value == 0:
                    sleep(0.001); waited += 0.001
                    if waited > CAPTURE_TIMEOUT_S:
                        ps.ps6000aStop(self.handle)
                        raise TimeoutError("trigger never fired -- adjust B settings")
                    ps.ps6000aIsReady(self.handle, ctypes.byref(ready))
                self._get_values()
                power = np.array(self.bufA, dtype=np.float64)
                trig = np.array(self.bufB, dtype=np.float64)
                return power, trig
            except (ScopeReadError, TimeoutError) as e:
                if attempt >= retries:
                    raise
                # transient: stop, re-arm, and try again
                try:
                    ps.ps6000aStop(self.handle)
                except Exception:
                    pass
                sleep(0.05)
                self.arm()

    def close(self):
        """Stop and disconnect the PicoScope. Idempotent and exception-safe so
        it is always safe to call from a finally block or atexit."""
        if getattr(self, "_closed", False):
            return
        self._closed = True
        try:
            ps.ps6000aStop(self.handle)
        except Exception:
            pass
        try:
            ps.ps6000aCloseUnit(self.handle)
        except Exception:
            pass
