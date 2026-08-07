#!/usr/bin/env python3
"""K block-0 oracle on the EXISTING hardware -- the REAL Hamming-distance part.

Insight (from the HQC reference kem.c): during decapsulation the shared-secret
hash is  K = SHAKE256( mc || 0x04 ),  mc = (message || u || v), where the message
field is:
      SUCCESS -> m      = 0            (Hamming weight 0)
      FAILURE -> sigma  = fixed per-key secret (Hamming weight ~= 64)
u and v are IDENTICAL between the success and failure hypotheses of a single
query, so they are common-mode: ALL oracle-distinguishing leakage lives in the
16-byte message field, absorbed in Keccak BLOCK 0. The current G core already
absorbs a 128-bit message field into block 0, so we can measure the real K
message-field oracle WITHOUT re-synthesising: just feed the true K values.

  class 0 (success): m' = 0                         (HW 0)
  class 1 (failure): m' = sigma  (one fixed random 128-bit value, HW ~= 64)

This is NOT the artificial m'=0/1 pair -- these are the actual values real K
processes on success vs failure. The near-zero-garbage confounder that caps the
G oracle at 74-76% cannot occur here: failure is always the fixed high-weight
sigma, never near-zero.

Run (device connected, PicoScope GUI closed):
  python k_block0_test.py --n 1200
"""
import os
import random
import argparse

import numpy as np

from cw310_program_test import program_cw310
from pico_scope import Scope
from two_oracle_datasets import capture, process

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results_datasets")


def hw128(x):
    return bin(x).count("1")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1200)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    rng = random.Random(args.seed)
    n_each = args.n // 2

    # sigma = fixed per-key implicit-rejection secret (keygen once, never changes).
    # In the real attack ALL failure traces from the same victim use the SAME sigma.
    # So the correct test is: class1 = one fixed sigma repeated n_each times.
    sigma = 0
    while hw128(sigma) < 56 or hw128(sigma) > 72:
        sigma = rng.getrandbits(128)

    msgs = [0] * n_each + [sigma] * n_each     # success = 0, failure = fixed sigma
    labels = [0] * n_each + [1] * n_each
    order = list(zip(msgs, labels)); rng.shuffle(order)
    msgs, labels = zip(*order)

    target = program_cw310()
    scope = Scope()
    print(f"scope: {scope.n_samples} samples/trace")
    print(f"K block-0: class0 = m'=0  (HW 0,  decode SUCCESS)")
    print(f"           class1 = sigma = 0x{sigma:032x}  (HW {hw128(sigma)}, fixed per key)\n")

    X, y = capture(target, scope, msgs, labels, "Kblk0")
    scope.close()

    summ = process("k_block0_0_vs_sigma",
                   "K block-0: success m=0 vs failure sigma (real K values, fixed sigma)",
                   X, np.asarray(y, np.int8), [10, 20, 40, 80], OUT, rng)

    print("\n================ RESULT ================")
    print(f"  K block-0 oracle: test acc = {summ['test_acc']*100:.1f}% "
          f"(peak |t|={summ['peak_abs_t']})")
    print(f"  confusion: TP={summ['tp']} TN={summ['tn']} FP={summ['fp']} FN={summ['fn']}")
    print(f"  compare -> honest G oracle = 74.4% / 76.0%")
    print(f"  sigma is FIXED (keygen once) -> correct real-attack model")
    print("========================================")


if __name__ == "__main__":
    main()
