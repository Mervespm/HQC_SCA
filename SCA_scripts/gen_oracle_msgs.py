#!/usr/bin/env python3
"""Generate the TWO message pools the REAL key-recovery oracle actually queries,
so the device profiles the correct class pair (m'=0 vs decode-FAILURE garbage)
instead of the artificial m'=0 vs m'=1.

Why this matters
----------------
The old capture used M0=0, M1=1 -> a clean 1-bit contrast that OVER-states the
oracle. During the actual attack the two classes are:

  * y[j]=0  -> 15 RS errors -> RS SUCCESS  -> m' = 0            (class 0)
  * y[j]=1  -> 16 RS errors -> RS FAILURE  -> m' = garbage      (class 1)

The garbage m' carries real confounder noise (the other 65 secret bits sprayed
by u*y), so the classes OVERLAP -- exactly the difficulty the repetition +
majority vote defeats. Profiling THIS pair gives the honest single-query oracle.

m' is fully DETERMINISTIC software (hqc128_ref); only the G-power is hardware.
So we precompute the m' pools here, offline, WITHOUT a device, and the collector
just replays them on the FPGA.

Output (loaded by collect_data.py):
  oracle_msgs.npz  -> class0 (uint) m'=success pool, class1 (uint) m'=failure pool
  oracle_msgs_meta.json -> HW distributions + provenance

Run in any python (no device / chipwhisperer needed):
  python gen_oracle_msgs.py --n 4000 --seed 1
"""
import os
import json
import random
import argparse

import numpy as np

import hqc128_ref as H
import hqc_attack_sim as S


def msg_to_int(mbytes):
    """16-byte message (MSB-first, matches run_one_g absorb order) -> 128-bit int."""
    return int.from_bytes(mbytes, "big")


def hw_int(x):
    return bin(x).count("1")


def sample_class_msgs(sk, positions, n, rng, filler_region="any", high_hw=False):
    """Replay the real attack query on each coordinate and return the m' the G
    core would receive (as a 128-bit int), plus its Hamming weight."""
    out = []
    pos = list(positions)
    rng.shuffle(pos)
    idx = 0
    while len(out) < n:
        j = pos[idx % len(pos)]
        idx += 1
        swing = rng.randrange(H.K1)          # swing block in RS systematic region
        pivot = rng.randrange(H.N2)
        v, P = S.build_query_v(swing, pivot, rng, filler_region=filler_region,
                               high_hw=high_hw)
        if v is None:                        # make_boundary_word failed -> skip
            continue
        i = (P - j) % H.N
        u = 1 << i
        mprime = H.decrypt(sk, u, v)         # ACTUAL recovered message bytes
        out.append(msg_to_int(mprime))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4000,
                    help="messages per class")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__),
                                                  "oracle_msgs.npz"))
    ap.add_argument("--filler_region", choices=["any", "sys", "parity"],
                    default="any",
                    help="fix #7: 'sys' confines RS fillers to the systematic "
                         "region so failure garbage has high HW (better oracle)")
    ap.add_argument("--high_hw", action="store_true",
                    help="fix #7+: force filler symbols to popcount>=7 to "
                         "maximise/stabilise the failure-class Hamming weight")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    random.seed(args.seed)
    sk = H.keygen()
    supp = list(set(sk["ypos"]))                       # y=1 -> failure class
    non = [p for p in range(H.N) if p not in set(sk["ypos"])]  # y=0 -> success class

    print(f"HQC-128  weight(y)={len(supp)}  generating {args.n} msgs/class "
          f"(filler_region={args.filler_region}, high_hw={args.high_hw}) ...")
    class0 = sample_class_msgs(sk, non, args.n, rng, args.filler_region, args.high_hw)
    class1 = sample_class_msgs(sk, supp, args.n, rng, args.filler_region, args.high_hw)

    hw0 = np.array([hw_int(x) for x in class0])
    hw1 = np.array([hw_int(x) for x in class1])

    # store as hex strings (128-bit ints don't fit a numpy dtype)
    c0 = np.array([f"{x:032x}" for x in class0])
    c1 = np.array([f"{x:032x}" for x in class1])
    np.savez_compressed(args.out, class0=c0, class1=c1)

    meta = dict(
        n_per_class=args.n, seed=args.seed,
        class0="m'=0 success (y=0 query outputs)",
        class1="decode-failure garbage (y=1 query outputs)",
        class0_hw_mean=float(hw0.mean()), class0_hw_max=int(hw0.max()),
        class0_frac_zero=float((hw0 == 0).mean()),
        class1_hw_mean=float(hw1.mean()), class1_hw_sd=float(hw1.std()),
        class1_hw_min=int(hw1.min()), class1_hw_max=int(hw1.max()),
    )
    with open(os.path.splitext(args.out)[0] + "_meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    print(f"  class0 (success): HW mean={hw0.mean():.2f}  "
          f"frac(HW=0)={100*(hw0==0).mean():.1f}%  max={hw0.max()}")
    print(f"  class1 (failure): HW mean={hw1.mean():.2f} +-{hw1.std():.2f}  "
          f"min={hw1.min()} max={hw1.max()}")
    overlap = (hw1 == 0).mean()
    print(f"  class1 that still look like success (HW=0): {100*overlap:.1f}%  "
          f"<- single-query oracle error floor")
    print(f"Saved {args.out}")


if __name__ == "__main__":
    main()
