#!/usr/bin/env python3
"""K-oracle FEASIBILITY PROXY on the EXISTING G bitstream.

Idea (no new bitstream needed to test the leakage): the hardware Keccak is the
same core whether we call it G or K. The ONLY thing that changes the oracle is
WHAT gets absorbed:

  G-oracle (current):  absorb  0x03 || m'
     success -> m' = 0           (all-zero, HW=0)
     failure -> m' = garbage     (~19% of the time ALSO HW~=0  -> COLLIDES -> 74% cap)

  K-oracle (proposed): absorb  0x04 || m' || theta   where theta = G(m')
     success -> theta = G(0)     = a FIXED pseudo-random 320-bit value
     failure -> theta = G(gbg)   = a DIFFERENT pseudo-random value every query
     (m' being near-zero no longer matters: theta avalanches -> classes separate)

We EMULATE the K classes on the current 128-bit-m' G core by absorbing the low
128 bits of the REAL theta:

  class 0 (K-success proxy): m_reg = low128( G(0) )        -- CONSTANT every trace
  class 1 (K-failure proxy): m_reg = low128( G(random) )   -- differs every trace

This is faithful to what K absorbs (the theta content) and answers the only open
question honestly: does the SAME Keccak separate these classes better than the
near-zero-vs-zero G classes? If device accuracy here is >> 74%, the K target is
worth synthesising a real hqc_k_ctrl for.

Run (device connected, PicoScope GUI closed):
  python k_proxy_test.py --n 1200
"""
import os
import csv
import random
import argparse
import hashlib

import numpy as np

from cw310_program_test import program_cw310, run_one_g
from pico_scope import Scope
# reuse the exact capture + template + projection used for the honest datasets
from two_oracle_datasets import capture, template, project, process

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results_datasets")


def theta_low128(mprime_int):
    """low 128 bits of theta = SHAKE256(0x03 || m'), i.e. the real G output that
    the K hash would absorb, truncated to the 128-bit m_reg we can drive."""
    mp = mprime_int.to_bytes(16, "big")
    th = hashlib.shake_256(bytes([0x03]) + mp).digest(40)   # 320-bit theta
    return int.from_bytes(th[:16], "big")                    # low 128 bits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1200,
                    help="total traces (balanced over the 2 proxy classes)")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    rng = random.Random(args.seed)
    n_each = args.n // 2

    # ---- build the two K-proxy message sets ----
    theta_S = theta_low128(0)                       # success theta (CONSTANT)
    succ = [theta_S] * n_each
    fail = [theta_low128(rng.getrandbits(128)) for _ in range(n_each)]  # varied

    msgs = succ + fail
    labels = [0] * n_each + [1] * n_each
    order = list(zip(msgs, labels)); rng.shuffle(order)
    msgs, labels = zip(*order)

    target = program_cw310()
    scope = Scope()
    print(f"scope: {scope.n_samples} samples/trace")
    print(f"K-proxy: class0 = FIXED theta=G(0) low128 = 0x{theta_S:032x}")
    print(f"         class1 = G(random) low128, {n_each} distinct values\n")

    X, y = capture(target, scope, msgs, labels, "Kproxy")
    scope.close()

    summ = process("k_proxy_success_vs_fail",
                   "K-proxy: fixed theta=G(0) vs varied theta=G(random)",
                   X, np.asarray(y, np.int8),
                   [10, 20, 40, 80], OUT, rng)

    # append a one-line comparison row so it sits next to the G numbers
    row = dict(dataset="k_proxy_success_vs_fail", **{k: summ[k] for k in
               ("n_traces", "samples", "poi_k", "peak_abs_t",
                "train_acc", "test_acc", "tp", "tn", "fp", "fn")})
    print("\n================ RESULT ================")
    print(f"  K-proxy single-query oracle: test acc = {summ['test_acc']*100:.1f}% "
          f"(peak |t|={summ['peak_abs_t']})")
    print(f"  compare -> honest G oracle device = 74.4% (baseline) / 76.0% (fix#7)")
    if summ["test_acc"] > 0.80:
        print("  => K target CLEARS the G ceiling. Worth synthesising hqc_k_ctrl.")
    else:
        print("  => K proxy did NOT clear the ceiling on this model/capture; re-examine.")
    print("========================================")


if __name__ == "__main__":
    main()
