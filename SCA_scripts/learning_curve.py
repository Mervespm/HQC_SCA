#!/usr/bin/env python3
"""Minimum-traces (learning curve) analysis for the HQC-G single-trace oracle.

The device oracle hits ~100% -- so the interesting question for the paper is:
HOW FEW training traces are actually needed to build a working oracle? This
script measures single-trace accuracy as a function of the number of TRAINING
traces (the template-building set), which is the standard SCA learning curve.

It ALSO sweeps the number of POIs, and can add synthetic noise, so you can show
where the oracle degrades (useful precisely because the real scope is "too
clean").

Two ways to run:
  * LIVE capture (needs CW310 + PicoScope, conda env):
        python learning_curve.py --capture 2500
    captures a labelled pool, saves it to raw_pool.npz, then analyses it.
  * OFFLINE from a saved pool (numpy only, no device):
        python learning_curve.py --npz <folder_or_raw_pool.npz>

Outputs (in the run folder):
  learning_curve.csv    n_train, acc_mean, acc_std, err_mean   (over repeats)
  learning_curve.png    accuracy vs #training traces (with 90/99% guide lines)
  poi_curve.csv/.png    accuracy vs #POIs at a fixed n_train
  summary.txt           the minimum n_train to reach 90 / 99 / 100%
"""
import os
import sys
import csv
import argparse
import datetime

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "PowerTrace_HQC_G")


# --------------------------------------------------------------------------- #
#  Template (identical maths to oracle_test.py: LDA on the top-k Welch-|t| POIs)
# --------------------------------------------------------------------------- #
def build_template(X, y, k):
    x0, x1 = X[y == 0], X[y == 1]
    m0, m1 = x0.mean(0), x1.mean(0)
    v0, v1 = x0.var(0, ddof=1), x1.var(0, ddof=1)
    n0, n1 = max(len(x0), 1), max(len(x1), 1)
    t = (m0 - m1) / np.sqrt(v0 / n0 + v1 / n1 + 1e-24)
    pois = np.argsort(np.abs(t))[::-1][:k]
    vp = 0.5 * (v0 + v1) + 1e-24
    w = ((m0 - m1) / vp)[pois]
    bias = float(w @ (0.5 * (m0[pois] + m1[pois])))
    return pois, w, bias


def accuracy(Xtr, ytr, Xte, yte, k):
    pois, w, bias = build_template(Xtr, ytr, k)
    proj = Xte[:, pois] @ w
    pred = np.where(proj > bias, 0, 1).astype(np.int8)
    return float((pred == yte).mean())


# --------------------------------------------------------------------------- #
def learning_curve(X, y, test_n, grid, k, repeats, rng):
    """Accuracy vs #training traces, averaged over `repeats` random splits."""
    n = len(X)
    test_n = min(test_n, n // 3)
    rows = []
    for ntr in grid:
        if ntr + test_n > n:
            break
        accs = []
        for _ in range(repeats):
            perm = rng.permutation(n)
            te = perm[:test_n]
            tr = perm[test_n:test_n + ntr]
            ytr = y[tr]
            if min((ytr == 0).sum(), (ytr == 1).sum()) < 2:   # need >=2 per class
                continue
            accs.append(accuracy(X[tr], ytr, X[te], y[te], min(k, X.shape[1])))
        if accs:
            rows.append((ntr, float(np.mean(accs)), float(np.std(accs))))
    return rows


def poi_curve(X, y, test_n, ntr, k_grid, repeats, rng):
    n = len(X); test_n = min(test_n, n // 3)
    rows = []
    for k in k_grid:
        if k > X.shape[1]:
            break
        accs = []
        for _ in range(repeats):
            perm = rng.permutation(n)
            te = perm[:test_n]; tr = perm[test_n:test_n + ntr]
            if min((y[tr] == 0).sum(), (y[tr] == 1).sum()) < 2:
                continue
            accs.append(accuracy(X[tr], y[tr], X[te], y[te], k))
        if accs:
            rows.append((k, float(np.mean(accs)), float(np.std(accs))))
    return rows


def min_traces_for(rows, thresh):
    """Smallest n_train whose mean accuracy >= thresh (rows sorted by n_train)."""
    for ntr, a, _ in rows:
        if a >= thresh:
            return ntr
    return None


# --------------------------------------------------------------------------- #
def load_pool(path):
    """Load a labelled raw pool from an .npz (or a folder containing one)."""
    if os.path.isdir(path):
        path = os.path.join(path, "raw_pool.npz")
        if not os.path.exists(path):
            path = path.replace("raw_pool.npz", "raw_traces.npz")
    d = np.load(path)
    key = "traces" if "traces" in d else d.files[0]
    lkey = "labels" if "labels" in d else d.files[1]
    return d[key].astype(np.float64), d[lkey].astype(np.int8)


def capture_pool(n):
    """Capture n labelled traces live on the CW310 (imports device libs here so
    the offline --npz path needs no chipwhisperer/picosdk)."""
    import random
    from tqdm import tqdm
    from cw310_program_test import program_cw310, run_one_g
    from pico_scope import Scope
    target = program_cw310()
    scope = Scope()
    ns = scope.n_samples
    print(f"Capturing {n} labelled traces ({ns} samples each) ...")
    X = np.empty((n, ns), dtype=np.float32)
    y = np.empty(n, dtype=np.int8)
    for i in tqdm(range(n), desc="pool"):
        coin = random.randint(0, 1)
        scope.arm(); run_one_g(target, coin)
        tr, _ = scope.read()
        X[i] = tr; y[i] = coin
    scope.close()
    return X.astype(np.float64), y


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", type=int, default=0,
                    help="capture this many traces live on the device, then analyse")
    ap.add_argument("--npz", type=str, default=None,
                    help="analyse an existing raw pool (folder or .npz), no device")
    ap.add_argument("--test-n", type=int, default=600)
    ap.add_argument("--poi", type=int, default=40, help="POIs for the learning curve")
    ap.add_argument("--repeats", type=int, default=15, help="random splits per point")
    ap.add_argument("--noise", type=float, default=0.0,
                    help="add Gaussian noise (xN of trace std) to stress the oracle")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    outdir = os.path.join(OUT_ROOT, f"learncurve_{stamp}")
    os.makedirs(outdir, exist_ok=True)
    rng = np.random.default_rng(args.seed)

    if args.capture > 0:
        X, y = capture_pool(args.capture)
        np.savez_compressed(os.path.join(outdir, "raw_pool.npz"),
                            traces=X.astype(np.float32), labels=y)
        print(f"  saved raw_pool.npz ({len(X)} traces)")
    elif args.npz:
        X, y = load_pool(args.npz)
    else:
        print("give --capture N (live) or --npz <folder|file> (offline)")
        sys.exit(1)

    if args.noise > 0:
        X = X + rng.normal(0, args.noise * X.std(), X.shape)
        print(f"  added {args.noise}x-std Gaussian noise")

    print(f"Pool: {len(X)} traces, {X.shape[1]} samples, "
          f"class0={int((y==0).sum())} class1={int((y==1).sum())}")

    grid = [5, 10, 15, 20, 30, 40, 60, 80, 120, 160, 240, 320,
            480, 640, 800, 1000, 1200, 1600, 2000]
    lc = learning_curve(X, y, args.test_n, grid, args.poi, args.repeats, rng)

    with open(os.path.join(outdir, "learning_curve.csv"), "w", newline="") as f:
        wtr = csv.writer(f); wtr.writerow(["n_train", "acc_mean", "acc_std"])
        wtr.writerows([[n, f"{a:.4f}", f"{s:.4f}"] for n, a, s in lc])

    ns_ = [r[0] for r in lc]; am = [r[1] for r in lc]; asd = [r[2] for r in lc]
    plt.figure(figsize=(9, 5.5))
    plt.errorbar(ns_, am, yerr=asd, marker="o", color="#1b3b6f", capsize=3)
    for thr, col in [(0.90, "#f4a300"), (0.99, "#2e8b78")]:
        plt.axhline(thr, color=col, linestyle="--", linewidth=1.2,
                    label=f"{int(thr*100)}%")
    plt.xscale("log")
    plt.xlabel("number of training traces"); plt.ylabel("single-trace oracle accuracy")
    plt.title("HQC-G oracle: minimum training traces"); plt.ylim(0.45, 1.02)
    plt.grid(alpha=0.3); plt.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(outdir, "learning_curve.png"), dpi=130); plt.close()

    # POI sweep at a modest fixed train size
    ntr_fixed = min(400, len(X) - args.test_n)
    k_grid = [1, 2, 5, 10, 20, 40, 80, 160, 320, 640, 1280]
    pc = poi_curve(X, y, args.test_n, ntr_fixed, k_grid, args.repeats, rng)
    with open(os.path.join(outdir, "poi_curve.csv"), "w", newline="") as f:
        wtr = csv.writer(f); wtr.writerow(["n_poi", "acc_mean", "acc_std"])
        wtr.writerows([[k, f"{a:.4f}", f"{s:.4f}"] for k, a, s in pc])
    if pc:
        ks = [r[0] for r in pc]; pm = [r[1] for r in pc]; psd = [r[2] for r in pc]
        plt.figure(figsize=(9, 5.5))
        plt.errorbar(ks, pm, yerr=psd, marker="s", color="#7a1b3b", capsize=3)
        plt.xscale("log")
        plt.xlabel(f"number of POIs (n_train={ntr_fixed})")
        plt.ylabel("single-trace oracle accuracy")
        plt.title("HQC-G oracle: accuracy vs #POIs"); plt.ylim(0.45, 1.02)
        plt.grid(alpha=0.3); plt.tight_layout()
        plt.savefig(os.path.join(outdir, "poi_curve.png"), dpi=130); plt.close()

    # summary: minimum traces to reach each threshold
    lines = ["=== minimum training traces (single-trace oracle) ==="]
    for thr in (0.90, 0.99, 0.999, 1.0):
        m = min_traces_for(lc, thr)
        lines.append(f"  >= {thr*100:6.1f}% : "
                     + (f"{m} traces" if m else "not reached in this pool"))
    txt = "\n".join(lines)
    print(txt)
    with open(os.path.join(outdir, "summary.txt"), "w") as f:
        f.write(txt + "\n")
    print(f"\nSaved learning curve + POI curve to {outdir}")


if __name__ == "__main__":
    main()
