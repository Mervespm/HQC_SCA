"""Two-class (m'=0 vs m'=1) leakage campaign for the HQC G-function on CW310.

This is the HQC analogue of the Ravi et al. Kyber/mLKEM Keccak distinguisher
(https://github.com/PRASANNA-RAVI/Generic-SCA-CCA-Lattice-Schemes): we feed the
G-function's SHAKE256 two fixed inputs -- m'=0 and m'=1 -- and show that their
power signatures during the Keccak absorb/permute are statistically separable.
That separability is exactly the plaintext-checking (PC) oracle that drives
chosen-ciphertext key recovery on HQC decapsulation.

Methodology (same rig/maths as the HMAC tvla_hmac.py):
  * Welch's t-test, first- AND second-order, via online RunningStats (tvlaCalc).
  * Per trace: flip a coin -> class 0 (m'=M0) or class 1 (m'=M1).
  * |t| > 4.5 => the two classes are distinguishable (leakage).
  * Also saves the two class-mean traces and their difference-of-means, which is
    the most direct "0 vs 1" picture.
  * Results (CSV + PNG) + a resumable TVLACalc pickle are written every
    TRACE_STEPS traces.

Traces are aligned by the hardware trigger (chan B rising edge = G start), so
every trace is a fixed-length window from the same point -- no per-trace slicing.

Close the PicoScope GUI first, then run in the x64 conda env:
  & "$env:USERPROFILE/Miniconda3x64/envs/cwhqc/python.exe" tvla_hqc.py
"""
import os
import gc
import pickle
import random
import datetime

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from tqdm import tqdm

from cw310_program_test import program_cw310, run_one_g
from pico_scope import Scope
from tvlaCalc import TVLACalc

# =============================== SETTINGS =============================== #
TRACE_NUM   = 1000000     # total traces to capture
TRACE_STEPS = 1000       # save CSV/PNG + checkpoint every this many traces
START_OVER  = 1          # 1 = fresh run; 0 = resume newest dir from pickle

# The two fixed messages under test (Ravi-style m'=0 vs m'=1). Change M1 to any
# 128-bit value to test a different bit/coordinate of m'.
M0 = 0                    # class-0 message (fixed)
M1 = 1                    # class-1 message (fixed)
# ====================================================================== #


def _save_class_means(tCalc, directory, label):
    """Save the two class-mean traces overlaid + their difference-of-means.

    This is the most direct 'm'=0 vs m'=1' visual: where the two means diverge
    is where the Keccak leaks the message. The TVLA t-plot (from tCalc) is the
    variance-normalised version of the same information.
    """
    mean0 = tCalc.fixed_stats.mean()
    mean1 = tCalc.random_stats.mean()
    n0, n1 = tCalc.fixed_stats.n, tCalc.random_stats.n
    if n0 == 0 or n1 == 0:
        return
    diff = mean0 - mean1

    # overlaid class means
    plt.figure(figsize=(12, 6))
    plt.plot(mean0, color="#1b3b6f", linewidth=0.6, label=f"mean m'={M0}  (n={n0})")
    plt.plot(mean1, color="#c1121f", linewidth=0.6, label=f"mean m'={M1}  (n={n1})")
    plt.xlim(0, len(mean0))
    plt.xlabel("Sample No."); plt.ylabel("mean power (raw ADC)")
    plt.title("HQC-G Keccak: class-mean power, m'=0 vs m'=1")
    plt.legend(loc="upper right")
    plt.savefig(os.path.join(directory, f"class_means_{label}.png"))
    plt.close()

    # difference of means
    plt.figure(figsize=(12, 6))
    plt.plot(diff, color="#2e8b78", linewidth=0.6)
    plt.axhline(0, color="k", linewidth=0.5)
    plt.xlim(0, len(diff))
    plt.xlabel("Sample No."); plt.ylabel("mean(m'=0) - mean(m'=1)")
    plt.title("HQC-G Keccak: difference of means (m'=0 - m'=1)")
    plt.savefig(os.path.join(directory, f"diff_of_means_{label}.png"))
    plt.close()

    np.savetxt(os.path.join(directory, "class_mean_m0.csv"), mean0, delimiter=",")
    np.savetxt(os.path.join(directory, "class_mean_m1.csv"), mean1, delimiter=",")
    np.savetxt(os.path.join(directory, "diff_of_means.csv"), diff, delimiter=",")


def main():
    target = program_cw310()
    print("CW310 ready.\n")
    scope = Scope()   # 0 pre-trigger: trigger-aligned window (settings in pico_scope.py)

    # ---- output dir + TVLA state (fresh or resumed) ----
    out_base = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "PowerTrace_HQC_G")
    if START_OVER:
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        mydir = os.path.join(out_base, stamp)
        os.makedirs(mydir)
        tCalc = TVLACalc(scope.n_samples)
        captured = 0
        print(f"Fresh run -> {mydir}\n")
    else:
        dirs = [os.path.join(out_base, d) for d in os.listdir(out_base)
                if os.path.isdir(os.path.join(out_base, d))]
        mydir = max(dirs, key=os.path.getmtime)
        with open(os.path.join(mydir, "tCalc.pkl"), "rb") as f:
            tCalc = pickle.load(f)
        captured = tCalc.traceNum
        print(f"Resuming {mydir} from trace {captured}\n")

    try:
        for traceNum in tqdm(range(captured, TRACE_NUM), desc="Capturing traces"):
            coin = random.randint(0, 1)          # 0 = class m'=M0, 1 = class m'=M1
            mprime = M0 if coin == 0 else M1
            scope.arm()
            run_one_g(target, mprime)            # loads m', pulses START -> fires trigger
            try:
                trace, _trig = scope.read()
            except Exception as e:
                print(f"\nFailed capture at {traceNum}: {e}")
                continue

            # save a few example power traces for a sanity check
            if traceNum < 10:
                plt.clf()
                plt.plot(trace, color="r", linewidth=0.1)
                plt.xlim(0, len(trace))
                plt.xlabel("Sample No."); plt.ylabel("power-value")
                plt.title(f"HQC-G power trace {traceNum} (m'={mprime})")
                plt.savefig(os.path.join(mydir, f"power{traceNum}.png"))

            tCalc.addTrace(trace, coin)
            del trace
            gc.collect()

            if (traceNum + 1) % TRACE_STEPS == 0:
                tCalc.save_tvla_results(mydir, str(traceNum + 1))
                _save_class_means(tCalc, mydir, str(traceNum + 1))
                with open(os.path.join(mydir, "tCalc.pkl"), "wb") as f:
                    pickle.dump(tCalc, f)
    finally:
        tCalc.save_tvla_results(mydir, "final")
        _save_class_means(tCalc, mydir, "final")
        with open(os.path.join(mydir, "tCalc.pkl"), "wb") as f:
            pickle.dump(tCalc, f)
        scope.close()
        # report peak leakage
        t1 = tCalc.compute_first_order_tvla()
        if tCalc.fixed_stats.n and tCalc.random_stats.n:
            k = int(np.nanargmax(np.abs(t1)))
            print(f"\nDone. {tCalc.traceNum} traces "
                  f"(m'={M0}: {tCalc.fixed_stats.n}, m'={M1}: {tCalc.random_stats.n}).")
            print(f"Peak |t| = {abs(t1[k]):.1f} at sample {k} "
                  f"({'LEAK' if abs(t1[k]) > 4.5 else 'no leak yet'}).")
        print(f"Results in {mydir}")


if __name__ == "__main__":
    main()
