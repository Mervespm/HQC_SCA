"""Single-trace PC-oracle validator for the HQC-G leak (m'=0 vs m'=1).

The TVLA (tvla_hqc.py) proves the two classes are *separable* when you already
know the labels. A real chosen-ciphertext attack needs the opposite: given ONE
power trace of an UNKNOWN m', decide its class with no label. This script builds
that classifier (the plaintext-checking oracle) and measures its accuracy.

Method (classic template / reduced-template attack):
  1. Capture a labelled set on the live device (coin -> m'=0 or m'=1).
  2. Split into TRAIN and TEST.
  3. On TRAIN: compute class means mean0/mean1 and a per-sample Welch |t|; pick
     the top-K leaking samples (points of interest, POIs).
  4. Classifier: project each trace onto the difference-template
     w = (mean0 - mean1) restricted to the POIs; the midpoint threshold
     separates the two classes (equivalent to nearest-class-mean / a 1-D LDA on
     the POIs). Predict class for every held-out TEST trace.
  5. Report single-trace accuracy + confusion. >~99% => the oracle is real and
     the CCA key-recovery attack works end-to-end on this target.

Also saves the template so it can drive the real decap oracle later.

Close the PicoScope GUI, then run in the x64 conda env:
  & "$env:USERPROFILE/Miniconda3x64/envs/cwhqc/python.exe" oracle_test.py
"""
import os
import random
import datetime

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from tqdm import tqdm

from cw310_program_test import program_cw310, run_one_g
from pico_scope import Scope

# =============================== SETTINGS =============================== #
TRAIN_N   = 10000        # labelled traces used to build the template
TEST_N    = 1000         # held-out labelled traces used to score the oracle
N_POI_MAX = 4000         # upper bound; the best K is auto-picked by validation
VAL_FRAC  = 0.2          # fraction of TRAIN held out to choose K
M0, M1    = 0, 1         # the two message classes
# ====================================================================== #


def capture_set(target, scope, n, desc):
    """Capture n labelled traces: returns (traces[n, samples], labels[n])."""
    X = np.empty((n, scope.n_samples), dtype=np.float64)
    y = np.empty(n, dtype=np.int8)
    for i in tqdm(range(n), desc=desc):
        coin = random.randint(0, 1)
        scope.arm()
        run_one_g(target, M0 if coin == 0 else M1)
        trace, _ = scope.read()
        X[i] = trace
        y[i] = coin
    return X, y


def build_template(X, y, k):
    """LDA/matched-filter template on the top-k leaking samples (by Welch |t|).

    Weights are variance-normalised (w = Delta / pooled_var) -- the statistically
    optimal linear discriminant when per-sample noise varies, which beats a plain
    difference-of-means filter at picking signal out of noisy samples.
    """
    x0, x1 = X[y == 0], X[y == 1]
    m0, m1 = x0.mean(0), x1.mean(0)
    v0, v1 = x0.var(0, ddof=1), x1.var(0, ddof=1)
    n0, n1 = len(x0), len(x1)
    t = (m0 - m1) / np.sqrt(v0 / n0 + v1 / n1 + 1e-24)
    pois = np.argsort(np.abs(t))[::-1][:k]           # top-k leaking samples
    vp = 0.5 * (v0 + v1) + 1e-24                      # pooled per-sample variance
    w = ((m0 - m1) / vp)[pois]                        # LDA weights at POIs
    midpoint = 0.5 * (m0[pois] + m1[pois])           # decision boundary
    bias = float(w @ midpoint)                        # project midpoint -> threshold
    return dict(m0=m0, m1=m1, t=t, pois=pois, w=w, bias=bias, n0=n0, n1=n1)


def classify(X, tpl):
    """Single-trace prediction for each row of X. class0 if projection > bias."""
    proj = X[:, tpl["pois"]] @ tpl["w"]
    return np.where(proj > tpl["bias"], 0, 1).astype(np.int8)


def select_k(Xtr, ytr):
    """Auto-pick the POI count K by holding out VAL_FRAC of TRAIN as validation.

    Sweeps K over a log grid up to N_POI_MAX and returns the K that maximises
    single-trace accuracy on the held-out split -- so N_POI adapts automatically
    to the sample rate / leak width instead of being hand-tuned.
    """
    nval = max(1, int(len(Xtr) * VAL_FRAC))
    Xf, yf = Xtr[:-nval], ytr[:-nval]     # fit split
    Xv, yv = Xtr[-nval:], ytr[-nval:]     # validation split
    grid = [k for k in (10, 20, 50, 100, 200, 400, 800, 1600, 3200, N_POI_MAX)
            if k <= min(N_POI_MAX, Xf.shape[1])]
    best_k, best_acc = grid[0], -1.0
    print("  selecting POI count by validation:")
    for k in sorted(set(grid)):
        tpl = build_template(Xf, yf, k)
        acc = float((classify(Xv, tpl) == yv).mean())
        flag = ""
        if acc > best_acc:
            best_acc, best_k, flag = acc, k, "  <-- best"
        print(f"    K={k:<5d} val acc = {acc*100:5.2f}%{flag}")
    print(f"  chosen K = {best_k} (val acc {best_acc*100:.2f}%)\n")
    return best_k


def main():
    target = program_cw310()
    print("CW310 ready.\n")
    scope = Scope()

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "PowerTrace_HQC_G",
                       "oracle_" + datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))
    os.makedirs(out)

    Xtr, ytr = capture_set(target, scope, TRAIN_N, "train")
    Xte, yte = capture_set(target, scope, TEST_N, "test ")
    scope.close()

    k = select_k(Xtr, ytr)                # auto-pick POI count on a val split
    tpl = build_template(Xtr, ytr, k)     # final template on ALL train traces
    pred = classify(Xte, tpl)
    acc = float((pred == yte).mean())

    # confusion matrix
    tp0 = int(((pred == 0) & (yte == 0)).sum()); fn0 = int(((pred == 1) & (yte == 0)).sum())
    tp1 = int(((pred == 1) & (yte == 1)).sum()); fn1 = int(((pred == 0) & (yte == 1)).sum())

    peak = int(np.nanargmax(np.abs(tpl["t"])))
    print(f"\n=== Single-trace PC-oracle result ({TEST_N} held-out traces) ===")
    print(f"train peak |t| = {abs(tpl['t'][peak]):.1f} at sample {peak}, "
          f"POIs = {sorted(tpl['pois'].tolist())}")
    print(f"accuracy   = {acc*100:.2f} %")
    print(f"m'=0 recall = {tp0}/{tp0+fn0}   m'=1 recall = {tp1}/{tp1+fn1}")
    verdict = ("ORACLE WORKS -> CCA key-recovery is feasible" if acc > 0.99
               else "usable but noisy; add traces / POIs or improve alignment"
               if acc > 0.9 else "too weak; check scope range / trigger alignment")
    print(f"verdict    = {verdict}")
    # A PC oracle can repeat each chosen-ciphertext query R times and majority-
    # vote; per-query error p shrinks fast. Report the R needed for ~99.9%.
    if 0.5 < acc < 1.0:
        p = 1.0 - acc
        R = 1
        from math import comb
        while R < 99:
            err = sum(comb(R, k) * p**k * (1 - p)**(R - k)
                      for k in range(R // 2 + 1, R + 1))
            if err < 1e-3:
                break
            R += 2
        print(f"           majority-vote over R={R} repeated queries -> ~99.9% oracle\n")
    else:
        print()

    # save template + a POI plot
    np.savez(os.path.join(out, "template.npz"),
             m0=tpl["m0"], m1=tpl["m1"], t=tpl["t"], pois=tpl["pois"],
             w=tpl["w"], bias=tpl["bias"])
    plt.figure(figsize=(12, 6))
    plt.plot(np.abs(tpl["t"]), color="#1b3b6f", linewidth=0.6, label="|t| per sample")
    plt.scatter(tpl["pois"], np.abs(tpl["t"])[tpl["pois"]], color="#c1121f",
                s=18, zorder=3, label=f"top-{len(tpl['pois'])} POIs")
    plt.axhline(4.5, color="#2e8b78", linestyle="--", linewidth=1.4)
    plt.xlim(0, len(tpl["t"])); plt.xlabel("Sample No."); plt.ylabel("|t|")
    plt.title(f"HQC-G oracle POIs  (single-trace acc = {acc*100:.2f} %)")
    plt.legend(loc="upper right")
    plt.savefig(os.path.join(out, "oracle_pois.png"))
    plt.close()

    with open(os.path.join(out, "result.txt"), "w") as f:
        f.write(f"accuracy {acc*100:.2f} %\npeak |t| {abs(tpl['t'][peak]):.1f} "
                f"at sample {peak}\nPOIs {sorted(tpl['pois'].tolist())}\n{verdict}\n")
    print(f"Saved template + POI plot to {out}")


if __name__ == "__main__":
    main()
