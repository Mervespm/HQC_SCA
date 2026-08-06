#!/usr/bin/env python3
"""Offline experiments to push the single-query PC-oracle past the 71-73% floor.

Runs entirely on a saved raw pool (raw_pool.npz, correct 0vFAIL classes) -- no
device. Compares, with the SAME cross-validated protocol:

  base   : diagonal-LDA on top-K Welch-|t| POIs (what collect_data.py ships)
  fullcov: full (pooled) covariance LDA on top-K POIs  (lever 1)
  fullcov+std / +pca : preprocessing before the classifier   (lever 4)
  averaging: average K deterministic repeats before classifying (lever 2, SIM)

The averaging is *simulated* by pooling within-class traces (the device is
deterministic per query, so real repeats of one ciphertext average the same
way -- this gives the achievable d'-vs-K curve as an upper reference).

Usage:
  python oracle_boost.py --npz PowerTrace_HQC_G\\learncurve_2026-08-06_13-25-15
"""
import os
import sys
import argparse
import numpy as np


def load_pool(path):
    if os.path.isdir(path):
        for name in ("raw_pool.npz", "raw_traces.npz"):
            cand = os.path.join(path, name)
            if os.path.exists(cand):
                path = cand
                break
    d = np.load(path)
    key = "traces" if "traces" in d else d.files[0]
    lkey = "labels" if "labels" in d else d.files[1]
    return d[key].astype(np.float64), d[lkey].astype(np.int8)


def welch_t(X, y):
    x0, x1 = X[y == 0], X[y == 1]
    m0, m1 = x0.mean(0), x1.mean(0)
    v0, v1 = x0.var(0, ddof=1), x1.var(0, ddof=1)
    n0, n1 = len(x0), len(x1)
    return (m0 - m1) / np.sqrt(v0 / n0 + v1 / n1 + 1e-24), m0, m1, v0, v1


def diag_lda(Xtr, ytr, k):
    """Diagonal-covariance LDA on top-k POIs (the baseline oracle)."""
    t, m0, m1, v0, v1 = welch_t(Xtr, ytr)
    pois = np.argsort(np.abs(t))[::-1][:k]
    vp = 0.5 * (v0 + v1) + 1e-24
    w = ((m0 - m1) / vp)[pois]
    bias = float(w @ (0.5 * (m0[pois] + m1[pois])))
    return pois, w, bias


def full_lda(Xtr, ytr, k, shrink=0.1):
    """Full pooled-covariance LDA (Fisher) on top-k POIs with shrinkage.

    Diagonal LDA ignores that neighbouring samples are highly correlated; the
    Fisher discriminant w = Sigma^-1 (mu0-mu1) whitens that correlation and is
    the optimal linear oracle under Gaussian noise."""
    t, m0all, m1all, _, _ = welch_t(Xtr, ytr)
    pois = np.argsort(np.abs(t))[::-1][:k]
    X = Xtr[:, pois]
    x0, x1 = X[ytr == 0], X[ytr == 1]
    mu0, mu1 = x0.mean(0), x1.mean(0)
    S = (np.cov(x0, rowvar=False) * (len(x0) - 1)
         + np.cov(x1, rowvar=False) * (len(x1) - 1)) / (len(X) - 2)
    S = np.atleast_2d(S)
    # shrinkage toward the diagonal keeps S invertible when k is large
    S = (1 - shrink) * S + shrink * np.diag(np.diag(S) + 1e-12)
    w = np.linalg.solve(S, mu0 - mu1)
    bias = float(w @ (0.5 * (mu0 + mu1)))
    return pois, w, bias


def apply_lin(X, pois, w, bias):
    proj = X[:, pois] @ w
    return np.where(proj > bias, 0, 1).astype(np.int8), proj


def cv_accuracy(X, y, builder, k, folds=5, rng=None, prep=None):
    """Stratified-ish k-fold CV accuracy for a linear oracle builder."""
    rng = rng or np.random.default_rng(0)
    n = len(X)
    idx = rng.permutation(n)
    accs = []
    for f in range(folds):
        te = idx[f::folds]
        tr = np.setdiff1d(idx, te, assume_unique=False)
        Xtr, ytr, Xte, yte = X[tr], y[tr], X[te], y[te]
        if min((ytr == 0).sum(), (ytr == 1).sum()) < 2:
            continue
        if prep is not None:
            Xtr, Xte = prep(Xtr, Xte)
        pois, w, bias = builder(Xtr, ytr, k)
        pred, _ = apply_lin(Xte, pois, w, bias)
        accs.append((pred == yte).mean())
    return float(np.mean(accs)), float(np.std(accs))


def prep_standardize(Xtr, Xte):
    mu = Xtr.mean(0)
    sd = Xtr.std(0) + 1e-12
    return (Xtr - mu) / sd, (Xte - mu) / sd


def avg_curve(X, y, k, Ks, folds=5, rng=None):
    """Simulated per-query averaging: within the TEST class, average K traces
    together (deterministic device -> real repeats average the same way) and
    measure the resulting single-*query* accuracy vs K."""
    rng = rng or np.random.default_rng(1)
    n = len(X)
    idx = rng.permutation(n)
    out = []
    for K in Ks:
        accs = []
        for f in range(folds):
            te = idx[f::folds]
            tr = np.setdiff1d(idx, te)
            pois, w, bias = full_lda(X[tr], y[tr], k)
            # build averaged test queries per class
            for cls in (0, 1):
                pool = te[y[te] == cls]
                rng.shuffle(pool)
                groups = [pool[i:i + K] for i in range(0, len(pool) - K + 1, K)]
                if not groups:
                    continue
                Xa = np.stack([X[g].mean(0) for g in groups])
                pred, _ = apply_lin(Xa, pois, w, bias)
                accs.append((pred == cls).mean())
        out.append((K, float(np.mean(accs)), float(np.std(accs))))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--npz", required=True, help="folder or raw_pool.npz")
    ap.add_argument("--kgrid", type=str, default="5,10,20,40,80,160")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    X, y = load_pool(args.npz)
    print(f"Pool: {len(X)} traces, {X.shape[1]} samples, "
          f"class0={(y==0).sum()} class1={(y==1).sum()}\n")
    rng = np.random.default_rng(args.seed)
    kgrid = [int(s) for s in args.kgrid.split(",")]

    print("=== Lever 1: classifier (5-fold CV single-trace accuracy) ===")
    print(f"{'K':>5} | {'diag-LDA':>16} | {'full-cov LDA':>16} | "
          f"{'full-cov +std':>16}")
    best = (0, "", 0.0)
    for k in kgrid:
        a1, s1 = cv_accuracy(X, y, diag_lda, k, args.folds, rng)
        a2, s2 = cv_accuracy(X, y, full_lda, k, args.folds, rng)
        a3, s3 = cv_accuracy(X, y, full_lda, k, args.folds, rng,
                             prep=prep_standardize)
        print(f"{k:>5} | {a1*100:6.2f} +/-{s1*100:4.2f}  | "
              f"{a2*100:6.2f} +/-{s2*100:4.2f}  | {a3*100:6.2f} +/-{s3*100:4.2f}")
        for tag, a in (("diag", a1), ("fullcov", a2), ("fullcov+std", a3)):
            if a > best[2]:
                best = (k, tag, a)
    print(f"\nBEST single-trace: {best[1]} @ K={best[0]} -> {best[2]*100:.2f}% "
          f"(baseline diag@40 ~ 73%)\n")

    kbest = best[0]
    print(f"=== Lever 2: per-query averaging (full-cov LDA, K_poi={kbest}) ===")
    print("  avg over device repeats -> single-QUERY accuracy")
    for K, a, s in avg_curve(X, y, kbest, [1, 2, 4, 8, 16], args.folds, rng):
        print(f"   avg {K:>2} traces/query -> {a*100:6.2f}% +/-{s*100:4.2f}")
    print()


if __name__ == "__main__":
    main()
