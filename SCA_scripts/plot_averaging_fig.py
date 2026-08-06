#!/usr/bin/env python3
"""Generate the per-query AVERAGING figure (single-query oracle accuracy vs K)
from a labelled 0vFAIL raw pool. Device-free. Embeds into the scenario doc."""
import argparse, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def load_pool(path):
    if os.path.isdir(path):
        path = os.path.join(path, "raw_pool.npz")
    d = np.load(path)
    return d["traces"].astype(np.float64), d["labels"].astype(np.int8)


def welch_t(X, y):
    x0, x1 = X[y == 0], X[y == 1]
    m0, m1 = x0.mean(0), x1.mean(0)
    v0, v1 = x0.var(0, ddof=1), x1.var(0, ddof=1)
    t = (m0 - m1) / np.sqrt(v0 / len(x0) + v1 / len(x1) + 1e-24)
    return t, m0, m1, v0, v1


def full_lda(Xtr, ytr, k, shrink=0.1):
    t, m0, m1, _, _ = welch_t(Xtr, ytr)
    pois = np.argsort(np.abs(t))[::-1][:k]
    X = Xtr[:, pois]
    x0, x1 = X[ytr == 0], X[ytr == 1]
    mu0, mu1 = x0.mean(0), x1.mean(0)
    S = (np.cov(x0, rowvar=False) * (len(x0) - 1)
         + np.cov(x1, rowvar=False) * (len(x1) - 1)) / (len(X) - 2)
    S = np.atleast_2d(S)
    S = (1 - shrink) * S + shrink * np.diag(np.diag(S) + 1e-12)
    w = np.linalg.solve(S, mu0 - mu1)
    bias = float(w @ (0.5 * (mu0 + mu1)))
    return pois, w, bias


def avg_curve(X, y, k, Ks, folds=5, seed=1):
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(X))
    out = []
    for K in Ks:
        accs = []
        for f in range(folds):
            te = idx[f::folds]
            tr = np.setdiff1d(idx, te)
            pois, w, bias = full_lda(X[tr], y[tr], k)
            for cls in (0, 1):
                pool = te[y[te] == cls].copy()
                rng.shuffle(pool)
                groups = [pool[i:i + K] for i in range(0, len(pool) - K + 1, K)]
                if not groups:
                    continue
                Xa = np.stack([X[g].mean(0) for g in groups])
                pred = np.where(Xa[:, pois] @ w > bias, 0, 1)
                accs.append((pred == cls).mean())
        out.append((K, float(np.mean(accs)), float(np.std(accs))))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--k", type=int, default=40)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    X, y = load_pool(args.path)
    Ks = [1, 2, 4, 8, 16]
    rows = avg_curve(X, y, args.k, Ks)
    Kv = [r[0] for r in rows]; acc = [r[1] * 100 for r in rows]; sd = [r[2] * 100 for r in rows]

    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.errorbar(Kv, acc, yerr=sd, marker="o", lw=2, color="#1f4e79", capsize=4)
    for k_, a_ in zip(Kv, acc):
        ax.annotate(f"{a_:.1f}%", (k_, a_), textcoords="offset points",
                    xytext=(0, 8), ha="center", fontsize=9)
    ax.axhline(97.5, ls=":", color="green", lw=1)
    ax.axhline(73, ls=":", color="grey", lw=1)
    ax.set_xscale("log", base=2); ax.set_xticks(Kv); ax.set_xticklabels(Kv)
    ax.set_xlabel("traces averaged per identical query  K")
    ax.set_ylabel("single-QUERY oracle accuracy (%)")
    ax.set_title("Per-query averaging amplifies the 73% single-trace oracle")
    ax.grid(alpha=0.3); ax.set_ylim(65, 100)
    out = args.out or os.path.join(
        args.path if os.path.isdir(args.path) else os.path.dirname(args.path),
        "fig_averaging.png")
    fig.tight_layout(); fig.savefig(out, dpi=160); plt.close(fig)
    print("saved", out)
    for K, a, s in rows:
        print(f"  K={K:>2}  acc={a*100:.2f}% +/-{s*100:.2f}")


if __name__ == "__main__":
    main()
