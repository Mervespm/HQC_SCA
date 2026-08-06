"""Phase-B PC-oracle analysis from an aggregated TVLA campaign (no raw traces).

tvla_hqc.py stores class means + variances (Welford) in tCalc.pkl, not the raw
traces. That is enough to do the next attack step analytically:

  * recompute first/second-order TVLA at the full trace count,
  * pick the leaking samples (POIs),
  * model the single-trace plaintext-checking ORACLE as an LDA / matched-filter
    over the POIs and derive its accuracy from a Gaussian model, and
  * compute the majority-vote repeats R needed for a ~99.9% oracle.

The single-trace error of the optimal linear (matched-filter) classifier with
per-class means m0,m1 and pooled per-sample variance vp is
    err = Phi(-D/2),   D^2 = sum_over_POIs (m0-m1)^2 / vp        (Mahalanobis)
assuming independent samples. Real ADC samples are oversampled/correlated, so
the multi-POI D is an OPTIMISTIC upper bound; the single-best-POI D is a
CONSERVATIVE lower bound. We report BOTH so the true accuracy is bracketed.

Run (any Python with numpy/scipy; no hardware, no chipwhisperer needed):
  & "$env:USERPROFILE/Miniconda3x64/envs/cwhqc/python.exe" oracle_from_stats.py [tCalc.pkl]
"""
import os
import sys
import glob
import pickle
from math import comb, erf, sqrt

import numpy as np


def phi(z):
    """Standard-normal CDF via erf (avoids a scipy dependency)."""
    return 0.5 * (1.0 + erf(z / sqrt(2.0)))


def majority_R(p_err, target=1e-3, rmax=199):
    """Odd repeats R so a majority vote of per-query error p_err beats target."""
    if p_err <= 0:
        return 1
    R = 1
    while R <= rmax:
        err = sum(comb(R, k) * p_err**k * (1 - p_err)**(R - k)
                  for k in range(R // 2 + 1, R + 1))
        if err < target:
            return R
        R += 2
    return rmax


def main():
    # locate the pickle (arg, else newest campaign dir)
    if len(sys.argv) > 1:
        pkl = sys.argv[1]
    else:
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "PowerTrace_HQC_G")
        cands = glob.glob(os.path.join(base, "*", "tCalc.pkl"))
        if not cands:
            sys.exit("no tCalc.pkl found under PowerTrace_HQC_G/")
        pkl = max(cands, key=os.path.getmtime)
    outdir = os.path.dirname(pkl)
    print(f"Loading {pkl}\n")

    with open(pkl, "rb") as f:
        tc = pickle.load(f)

    m0 = tc.fixed_stats.mean()          # class m'=0 mean trace
    m1 = tc.random_stats.mean()         # class m'=1 mean trace
    v0 = tc.fixed_stats.variance()
    v1 = tc.random_stats.variance()
    n0 = tc.fixed_stats.n
    n1 = tc.random_stats.n
    N = tc.traceNum
    ns = len(m0)

    # first-order Welch t
    t = (m0 - m1) / np.sqrt(v0 / max(n0, 1) + v1 / max(n1, 1) + 1e-24)
    abst = np.abs(t)
    peak = int(np.nanargmax(abst))
    n_leak = int((abst > 4.5).sum())

    print(f"=== Phase A recap (from {N} traces: m'=0 n={n0}, m'=1 n={n1}) ===")
    print(f"first-order peak |t| = {abst[peak]:.1f} at sample {peak}")
    print(f"samples with |t|>4.5 : {n_leak} / {ns}")
    lo = max(0, peak - 3); hi = min(ns, peak + 4)
    print(f"leak region ~ samples [{int(np.argmax(abst>4.5))} .. "
          f"{ns - 1 - int(np.argmax(abst[::-1]>4.5))}]\n")

    # ---- Phase B: single-trace oracle model ----
    vp = 0.5 * (v0 + v1) + 1e-24        # pooled per-sample variance
    delta = m0 - m1                     # class-mean difference (matched filter)
    d2_all_samples = (delta**2 / vp)    # per-sample Mahalanobis^2 contribution

    # POIs = top-K leaking samples by |t|
    for K in (1, 5, 10, 20, 40):
        pois = np.argsort(abst)[::-1][:K]
        D = float(np.sqrt(d2_all_samples[pois].sum()))   # combined separation
        acc = phi(D / 2.0)                               # optimal single-trace acc
        p_err = 1.0 - acc
        R = majority_R(p_err)
        tag = ("conservative (single best POI)" if K == 1 else
               f"K={K} POIs")
        print(f"POIs={K:<3d} D={D:6.2f}  single-trace acc={acc*100:6.2f}%  "
              f"err={p_err*100:5.2f}%  ->  R={R:>3d} repeats for <0.1% oracle   [{tag}]")

    # bracket: best single POI (lower bound) vs 20-POI (typical template)
    poi1 = int(np.argmax(d2_all_samples))
    D1 = float(np.sqrt(d2_all_samples[poi1]))
    acc1 = phi(D1 / 2.0)
    pois20 = np.argsort(abst)[::-1][:20]
    D20 = float(np.sqrt(d2_all_samples[pois20].sum()))
    acc20 = phi(D20 / 2.0)

    print("\n=== Verdict ===")
    print(f"single-best-sample oracle (conservative)  : {acc1*100:.2f}%  "
          f"(R={majority_R(1-acc1)} repeats -> 99.9%)")
    print(f"20-POI matched-filter oracle (optimistic)  : {acc20*100:.2f}%  "
          f"(R={majority_R(1-acc20)} repeats -> 99.9%)")
    print("True single-trace accuracy lies between these (samples are")
    print("oversampled/correlated, so the 20-POI value is an upper bound).")
    if acc1 > 0.99 or acc20 > 0.999:
        print(">>> ORACLE IS STRONG: chosen-ciphertext key recovery of y is feasible.")
    elif acc20 > 0.9:
        print(">>> ORACLE IS USABLE with a few repeated queries (majority vote).")
    else:
        print(">>> weak: collect more traces / raise SNR (chan-A range, alignment).")

    # save the matched-filter template so Phase D can drive the real decap oracle
    np.savez(os.path.join(outdir, "oracle_template.npz"),
             m0=m0, m1=m1, vp=vp, t=t,
             pois20=pois20, w20=(delta / vp)[pois20],
             bias20=float(((delta / vp)[pois20]) @ (0.5 * (m0 + m1)[pois20])))
    with open(os.path.join(outdir, "oracle_from_stats.txt"), "w") as f:
        f.write(f"traces {N}  (m0 n={n0}, m1 n={n1})\n")
        f.write(f"first-order peak |t| {abst[peak]:.1f} at sample {peak}, "
                f"{n_leak} samples > 4.5\n")
        f.write(f"conservative single-POI oracle acc {acc1*100:.2f}%\n")
        f.write(f"20-POI matched-filter oracle acc   {acc20*100:.2f}%\n")
    print(f"\nSaved oracle_template.npz + oracle_from_stats.txt to {outdir}")


if __name__ == "__main__":
    main()
