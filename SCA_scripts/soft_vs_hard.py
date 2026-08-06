#!/usr/bin/env python3
"""Soft (LLR) combining vs hard majority voting for the HQC PC-oracle.

Both amplify an imperfect single-query oracle to ~100% by repeating INDEPENDENT
chosen-ciphertext queries. Hard voting throws away the classifier's confidence
(each query -> a 0/1 bit); soft combining keeps the LDA projection distance and
sums per-query log-likelihood ratios (LLRs). At the same physical separation,
soft combining reaches a target key-recovery probability with FEWER queries.

We model the device leakage as the measured Gaussian two-class problem:
  class0 (m'=0)   ~ N(+d/2, 1)
  class1 (failure)~ N(-d/2, 1)
where the separation d = d' (Mahalanobis) is fixed by the MEASURED single-query
accuracy p via  p = Phi(d/2)  =>  d = 2*Phi^{-1}(p). At p=0.74, d'~1.29.

For each secret bit we draw R independent query projections from the TRUE class
and decide by (a) hard majority of thresholded bits, or (b) sign of the summed
LLR. Full key = all W=66 bits correct. Monte-Carlo over many keys.

Outputs (SCA_scripts/paper_results/):
  soft_vs_hard.csv   p,d_prime,R,hard_bit,soft_bit,hard_key,soft_key
  soft_vs_hard.png   full-key success vs R, hard vs soft, for each p
"""
import os
import argparse
import numpy as np
from math import erf, sqrt

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper_results")


def phi(x):
    return 0.5 * (1 + erf(x / sqrt(2)))


def phi_inv(p):
    # Acklam-free: use numpy's inverse via bisection (p in (0,1))
    lo, hi = -10.0, 10.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if phi(mid) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def simulate(p, R, W=66, n_keys=4000, seed=0):
    """Monte-Carlo full-key success for hard vote and soft LLR at oracle acc p."""
    rng = np.random.default_rng(seed)
    d = 2.0 * phi_inv(p)                      # class separation (d')
    # per-key: W bits, each with R independent queries
    # draw true class per bit uniformly; leakage ~ N(+-d/2, 1)
    hard_key_ok = 0
    soft_key_ok = 0
    hard_bit_ok = 0
    soft_bit_ok = 0
    tot_bits = 0
    for _ in range(n_keys):
        truth = rng.integers(0, 2, W)                 # 0 -> +d/2, 1 -> -d/2
        mean = np.where(truth == 0, +d / 2, -d / 2)   # (W,)
        # samples: (W, R)
        x = rng.normal(loc=mean[:, None], scale=1.0, size=(W, R))
        # hard: threshold at 0 -> predict class0 if x>0 ; majority vote
        hard_votes = (x <= 0).sum(axis=1)             # votes for class1
        hard_pred = (hard_votes > R / 2).astype(int)
        # soft: LLR for N(+d/2) vs N(-d/2) is linear in x -> sum(x); sign decides
        soft_sum = x.sum(axis=1)
        soft_pred = (soft_sum <= 0).astype(int)       # <=0 -> class1
        hb = (hard_pred == truth).sum()
        sb = (soft_pred == truth).sum()
        hard_bit_ok += hb; soft_bit_ok += sb; tot_bits += W
        hard_key_ok += (hb == W)
        soft_key_ok += (sb == W)
    return dict(p=p, d_prime=d, R=R,
                hard_bit=hard_bit_ok / tot_bits, soft_bit=soft_bit_ok / tot_bits,
                hard_key=hard_key_ok / n_keys, soft_key=soft_key_ok / n_keys)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ps", type=float, nargs="+", default=[0.74, 0.78])
    ap.add_argument("--Rs", type=int, nargs="+",
                    default=[1, 5, 11, 21, 31, 41, 51, 71, 101])
    ap.add_argument("--nkeys", type=int, default=4000)
    ap.add_argument("--W", type=int, default=66)
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    rows = []
    for p in args.ps:
        for R in args.Rs:
            r = simulate(p, R, W=args.W, n_keys=args.nkeys, seed=int(p * 1000) + R)
            rows.append(r)
            print(f"p={p} d'={r['d_prime']:.2f} R={R:>3} | "
                  f"hard bit {r['hard_bit']*100:6.3f}% key {r['hard_key']*100:6.2f}% | "
                  f"soft bit {r['soft_bit']*100:6.3f}% key {r['soft_key']*100:6.2f}%")

    # CSV
    csv = os.path.join(OUT, "soft_vs_hard.csv")
    with open(csv, "w") as f:
        f.write("p,d_prime,R,hard_bit,soft_bit,hard_key,soft_key\n")
        for r in rows:
            f.write(f"{r['p']},{r['d_prime']:.5f},{r['R']},{r['hard_bit']:.6f},"
                    f"{r['soft_bit']:.6f},{r['hard_key']:.6f},{r['soft_key']:.6f}\n")

    # figure
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 4.6))
    colors = {0.74: "#c0392b", 0.78: "#1f4e79", 0.85: "#0b6e4f"}
    for p in args.ps:
        rs = [r for r in rows if r["p"] == p]
        R = [r["R"] for r in rs]
        c = colors.get(p, "#555")
        ax.plot(R, [r["hard_key"] * 100 for r in rs], "--o", color=c,
                label=f"hard vote, p={p}", lw=1.6, ms=4)
        ax.plot(R, [r["soft_key"] * 100 for r in rs], "-s", color=c,
                label=f"soft LLR, p={p}", lw=2.0, ms=4)
    ax.axhline(99, ls=":", color="grey", lw=1)
    ax.set_xlabel("repeated INDEPENDENT queries per secret bit  R")
    ax.set_ylabel("full-key recovery success (%)")
    ax.set_title(f"Soft LLR vs hard majority voting (W={args.W}, HQC-128)")
    ax.grid(alpha=0.3); ax.legend(fontsize=8, loc="lower right")
    ax.set_ylim(0, 101)
    fig.tight_layout()
    png = os.path.join(OUT, "soft_vs_hard.png")
    fig.savefig(png, dpi=160); plt.close(fig)
    print(f"\nsaved {csv}\nsaved {png}")


if __name__ == "__main__":
    main()
