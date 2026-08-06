#!/usr/bin/env python3
"""Fix #7: quantify + improve the chosen-ciphertext construction for the HQC PC-oracle.

Two honest questions the reviewer asked:
  (a) how often does make_boundary_word() fail (return None)?  -> unprobeable coords
  (b) how often does the decode-FAILURE m' collide with the success class (HW~=0)?
      -> that collision rate IS the physical floor that caps the oracle at ~74%.

Then we TRY to raise the ceiling: several construction variants that push the
failure garbage AWAY from HW~=0 (place the swing + fillers in the systematic
RS region so a failed decode returns high-Hamming-weight message symbols).
For each variant we report:
  - boundary-word success rate
  - class0 (success) vs class1 (failure) Hamming-weight of m' (128-bit)
  - modelled single-query oracle accuracy from the HW separation (Gaussian d').

Outputs (SCA_scripts/paper_results/):
  fix7_construction.csv   variant, bw_ok, hw0_mean, hw1_mean, hw1_zerofrac, d_prime, model_acc
"""
import os
import random
import argparse
from math import erf, sqrt

import numpy as np
import hqc128_ref as H
from hqc_attack_sim import make_boundary_word, block_break_word

N, N1, N2, RS_T, K1, MASK_C = H.N, H.N1, H.N2, H.RS_T, H.K1, H.MASK_C
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper_results")


def phi(x):
    return 0.5 * (1 + erf(x / sqrt(2)))


def hw128(mbytes):
    """Hamming weight of the 16-byte (128-bit) message m'."""
    return sum(bin(b).count("1") for b in mbytes)


def build_variant(swing, pivot, rng, n_filler, filler_region, high_hw=False):
    """Craft v. filler_region: 'sys' -> fillers in [0,K1), 'parity' -> [K1,N1),
    'any' -> anywhere. swing block is boundary word at `pivot`."""
    v = 0
    if filler_region == "sys":
        pool = [b for b in range(K1) if b != swing]
    elif filler_region == "parity":
        pool = [b for b in range(K1, N1) if b != swing]
    else:
        pool = [b for b in range(N1) if b != swing]
    if n_filler > len(pool):
        n_filler = len(pool)
    fillers = rng.sample(pool, n_filler)
    for b in fillers:
        v |= block_break_word(rng, high_hw=high_hw) << (b * N2)
    w = make_boundary_word(pivot, rng)
    if w is None:
        return None, None
    v |= w << (swing * N2)
    return v & MASK_C, swing * N2 + pivot


def simulate_class(sk, variant, n, rng):
    """Return (hw0_list success, hw1_list failure) for a construction variant.
    We emulate the two oracle classes: draw y[j]=0 (success, 15 errs) vs y[j]=1
    (failure, 16 errs) by decrypting the crafted ciphertext for support vs
    non-support pivots -- but here we directly measure the FAILURE garbage HW by
    forcing the pivot bit flip (adds the 16th error)."""
    n_filler, region = variant["n_filler"], variant["region"]
    high_hw = variant.get("high_hw", False)
    hw_success, hw_fail = [], []
    bw_fail = 0
    tries = 0
    while len(hw_fail) < n and tries < n * 20:
        tries += 1
        swing = rng.randrange(K1)          # systematic swing so failure shows in m'
        pivot = rng.randrange(N2)
        v, P = build_variant(swing, pivot, rng, n_filler, region, high_hw)
        if v is None:
            bw_fail += 1
            continue
        u = 1 << rng.randrange(N)
        # success case: v as-is -> 15 errors -> should decode to m'=0
        m_succ = H.decrypt(sk, u, v)
        hw_success.append(hw128(m_succ))
        # failure case: flip the pivot bit in v -> 16 errors -> decode FAILS
        v_fail = v ^ (1 << P)
        m_fail = H.decrypt(sk, u, v_fail)
        hw_fail.append(hw128(m_fail))
    return hw_success, hw_fail, bw_fail, tries


def measure_bw_rate(n, rng):
    """make_boundary_word failure rate over n random pivots."""
    ok = 0
    for _ in range(n):
        p = rng.randrange(N2)
        if make_boundary_word(p, rng) is not None:
            ok += 1
    return ok / n


def model_acc(hw0, hw1):
    """Optimal-threshold single-query accuracy from the two HW distributions
    (balanced classes)."""
    a0 = np.array(hw0, float); a1 = np.array(hw1, float)
    lo = min(a0.min(), a1.min()); hi = max(a0.max(), a1.max())
    best = 0.0
    for th in np.linspace(lo, hi, 200):
        # class0 has HW~0 (low), class1 failure has higher HW
        acc = 0.5 * ((a0 <= th).mean() + (a1 > th).mean())
        best = max(best, acc)
    # d' from means/pooled std
    d = abs(a0.mean() - a1.mean()) / (0.5 * (a0.std() + a1.std()) + 1e-9)
    return best, d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--n", type=int, default=120, help="samples per class per variant")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    rng = random.Random(args.seed)
    sk = H.keygen()

    bw = measure_bw_rate(300, rng)
    print(f"make_boundary_word success rate = {bw*100:.1f}%  "
          f"(failure -> unprobeable pivot)\n")

    variants = [
        dict(name="baseline_RS_T_any", n_filler=RS_T, region="any"),
        dict(name="RS_T_sys",          n_filler=RS_T, region="sys"),
        dict(name="RS_T_parity",       n_filler=RS_T, region="parity"),
        dict(name="max_sys_fillers",   n_filler=K1 - 1, region="sys"),
        dict(name="sys_maxhw",         n_filler=RS_T, region="sys", high_hw=True),
    ]

    rows = []
    for v in variants:
        hw0, hw1, bwf, tries = simulate_class(sk, v, args.n, rng)
        if not hw1:
            print(f"{v['name']:20s}: no valid constructions"); continue
        a0 = np.array(hw0, float); a1 = np.array(hw1, float)
        zerofrac = float((a1 <= a0.mean() + 1e-9).mean())   # failures that look like success
        collide = float((a1 <= max(2, a0.max())).mean())     # failures within success HW band
        acc, d = model_acc(hw0, hw1)
        rows.append(dict(variant=v["name"], bw_ok=bw,
                         hw0_mean=a0.mean(), hw1_mean=a1.mean(),
                         hw1_zerofrac=collide, d_prime=d, model_acc=acc))
        print(f"{v['name']:20s}: class0 HW {a0.mean():5.1f}  class1 HW {a1.mean():5.1f}  "
              f"collide(fail~success) {collide*100:5.1f}%  d'={d:4.2f}  "
              f"model acc {acc*100:5.1f}%")

    csv = os.path.join(OUT, "fix7_construction.csv")
    with open(csv, "w") as f:
        f.write("variant,bw_success_rate,hw0_mean,hw1_mean,collision_frac,d_prime,model_acc\n")
        for r in rows:
            f.write(f"{r['variant']},{r['bw_ok']:.4f},{r['hw0_mean']:.3f},"
                    f"{r['hw1_mean']:.3f},{r['hw1_zerofrac']:.4f},{r['d_prime']:.4f},"
                    f"{r['model_acc']:.4f}\n")
    print(f"\nsaved {csv}")
    if rows:
        best = max(rows, key=lambda r: r["model_acc"])
        print(f"BEST construction: {best['variant']} -> model acc {best['model_acc']*100:.1f}% "
              f"(baseline ~ {rows[0]['model_acc']*100:.1f}%)")


if __name__ == "__main__":
    main()
