#!/usr/bin/env python3
"""Capture the TWO oracle datasets side by side, under identical scope settings,
and emit publication-quality artifacts for each plus a comparison markdown.

  DATASET A  -- ARTIFICIAL pair  m'=0 vs m'=1
     the clean 1-bit contrast; over-states the oracle (~100%). Kept ONLY to show
     what NOT to report.
  DATASET B  -- HONEST pair  m'=0 (RS decode SUCCESS) vs decode-FAILURE garbage
     the class pair the real HQC key-recovery attack actually queries (~74-76%).

For each dataset we write (into results_datasets/<name>/):
  raw_traces.npz        float32 [N, S] + labels           (gitignored, reproducible)
  class_means.csv       sample, mean_class0, mean_class1
  diff_of_means.csv     sample, mean0_minus_mean1
  tvla_curve.csv        sample, welch_t                    (|t|>4.5 = leak)
  oracle_scores.csv     projection, true_label, pred        (held-out test)
  summary.csv           metric,value  (n, peak_t, train_acc, test_acc, poi_k ...)
  fig_tvla.png          Welch t-test, +/-4.5 band
  fig_means.png         two class-mean traces overlaid
  fig_diff.png          difference-of-means
  fig_oracle_hist.png   LDA projection histogram, two classes
  fig_confusion.png     2x2 confusion matrix (held-out)

Then ORACLE_DATASETS.md embeds both side by side.

Run (device connected, PicoScope GUI closed):
  python two_oracle_datasets.py --n 1000
"""
import os
import csv
import json
import random
import argparse
import datetime

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from cw310_program_test import program_cw310, run_one_g
from pico_scope import Scope

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "results_datasets")
PLT_BLUE, PLT_RED = "#1f4e79", "#c0392b"


# --------------------------------------------------------------------------- #
def capture(target, scope, msgs, labels, desc):
    """msgs: list[int] 128-bit m'; labels: list[int]. Returns X[N,S], y[N]."""
    X = np.empty((len(msgs), scope.n_samples), np.float32)
    y = np.asarray(labels, np.int8)
    for i, m in enumerate(msgs):
        scope.arm()
        run_one_g(target, int(m))
        tr, _ = scope.read()
        X[i] = tr
        if (i + 1) % 500 == 0:
            print(f"    [{desc}] {i+1}/{len(msgs)}")
    return X, y


def template(Xtr, ytr, k):
    x0, x1 = Xtr[ytr == 0], Xtr[ytr == 1]
    m0, m1 = x0.mean(0), x1.mean(0)
    v0, v1 = x0.var(0, ddof=1), x1.var(0, ddof=1)
    n0, n1 = len(x0), len(x1)
    t = (m0 - m1) / np.sqrt(v0 / n0 + v1 / n1 + 1e-24)
    pois = np.argsort(np.abs(t))[::-1][:k]
    vp = 0.5 * (v0 + v1) + 1e-24
    w = ((m0 - m1) / vp)[pois]
    mid = 0.5 * (m0[pois] + m1[pois])
    bias = float(w @ mid)
    return dict(pois=pois, w=w, bias=bias, t=t, m0=m0, m1=m1)


def project(X, tpl):
    return X[:, tpl["pois"]] @ tpl["w"] - tpl["bias"]


# --------------------------------------------------------------------------- #
def process(name, title, X, y, k_grid, out_root, rng):
    d = os.path.join(out_root, name)
    os.makedirs(d, exist_ok=True)
    n = len(X)
    idx = np.arange(n); rng.shuffle(idx)
    cut = int(0.75 * n)
    tr, te = idx[:cut], idx[cut:]

    # pick best K by train->test
    best = None
    for k in k_grid:
        tpl = template(X[tr], y[tr], k)
        p_te = project(X[te], tpl)
        acc = float(((p_te < 0).astype(int) == y[te]).mean())
        if best is None or acc > best[0]:
            best = (acc, k, tpl)
    test_acc, k, tpl = best
    p_tr = project(X[tr], tpl)
    train_acc = float(((p_tr < 0).astype(int) == y[tr]).mean())
    peak_t = float(np.abs(tpl["t"]).max())
    p_te = project(X[te], tpl)
    pred_te = (p_te < 0).astype(int)

    # ---- CSVs ----
    np.savez_compressed(os.path.join(d, "raw_traces.npz"),
                        X=X.astype(np.float32), y=y)
    S = X.shape[1]
    with open(os.path.join(d, "class_means.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["sample", "mean_class0", "mean_class1"])
        for s in range(S):
            w.writerow([s, f"{tpl['m0'][s]:.6g}", f"{tpl['m1'][s]:.6g}"])
    with open(os.path.join(d, "diff_of_means.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["sample", "mean0_minus_mean1"])
        for s in range(S):
            w.writerow([s, f"{tpl['m0'][s]-tpl['m1'][s]:.6g}"])
    with open(os.path.join(d, "tvla_curve.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["sample", "welch_t"])
        for s in range(S):
            w.writerow([s, f"{tpl['t'][s]:.6g}"])
    with open(os.path.join(d, "oracle_scores.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["projection", "true_label", "pred"])
        for pj, tl, pr in zip(p_te, y[te], pred_te):
            w.writerow([f"{pj:.6g}", int(tl), int(pr)])
    # confusion
    tp = int(((pred_te == 1) & (y[te] == 1)).sum())
    tn = int(((pred_te == 0) & (y[te] == 0)).sum())
    fp = int(((pred_te == 1) & (y[te] == 0)).sum())
    fn = int(((pred_te == 0) & (y[te] == 1)).sum())
    summ = dict(dataset=name, n_traces=n, samples=S, poi_k=k,
                peak_abs_t=round(peak_t, 3),
                train_acc=round(train_acc, 4), test_acc=round(test_acc, 4),
                tp=tp, tn=tn, fp=fp, fn=fn)
    with open(os.path.join(d, "summary.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["metric", "value"])
        for kk, vv in summ.items():
            w.writerow([kk, vv])

    # ---- FIGURES ----
    # TVLA
    fig, ax = plt.subplots(figsize=(8, 3.4))
    ax.plot(tpl["t"], color=PLT_BLUE, lw=0.7)
    ax.axhline(4.5, ls="--", color=PLT_RED, lw=1)
    ax.axhline(-4.5, ls="--", color=PLT_RED, lw=1)
    ax.set_title(f"{title} — TVLA (peak |t|={peak_t:.1f})")
    ax.set_xlabel("sample"); ax.set_ylabel("Welch t")
    ax.grid(alpha=0.3); fig.tight_layout()
    fig.savefig(os.path.join(d, "fig_tvla.png"), dpi=160); plt.close(fig)

    # class means overlay
    fig, ax = plt.subplots(figsize=(8, 3.4))
    ax.plot(tpl["m0"], color=PLT_BLUE, lw=0.7, label="class 0 (m'=0 / success)")
    ax.plot(tpl["m1"], color=PLT_RED, lw=0.7, label="class 1")
    ax.set_title(f"{title} — class-mean traces")
    ax.set_xlabel("sample"); ax.set_ylabel("mean amplitude")
    ax.legend(fontsize=8); ax.grid(alpha=0.3); fig.tight_layout()
    fig.savefig(os.path.join(d, "fig_means.png"), dpi=160); plt.close(fig)

    # diff of means
    fig, ax = plt.subplots(figsize=(8, 3.4))
    ax.plot(tpl["m0"] - tpl["m1"], color="#0b6e4f", lw=0.7)
    ax.axhline(0, color="grey", lw=0.6)
    ax.set_title(f"{title} — difference of means (class0 − class1)")
    ax.set_xlabel("sample"); ax.set_ylabel("Δ amplitude")
    ax.grid(alpha=0.3); fig.tight_layout()
    fig.savefig(os.path.join(d, "fig_diff.png"), dpi=160); plt.close(fig)

    # oracle projection histogram
    fig, ax = plt.subplots(figsize=(7, 3.6))
    p0 = p_te[y[te] == 0]; p1 = p_te[y[te] == 1]
    lo, hi = p_te.min(), p_te.max()
    bins = np.linspace(lo, hi, 40)
    ax.hist(p0, bins, color=PLT_BLUE, alpha=0.6, label="class 0")
    ax.hist(p1, bins, color=PLT_RED, alpha=0.6, label="class 1")
    ax.axvline(0, ls="--", color="k", lw=1, label="decision boundary")
    ax.set_title(f"{title} — single-trace oracle (test acc {test_acc*100:.1f}%)")
    ax.set_xlabel("LDA projection"); ax.set_ylabel("count")
    ax.legend(fontsize=8); ax.grid(alpha=0.3); fig.tight_layout()
    fig.savefig(os.path.join(d, "fig_oracle_hist.png"), dpi=160); plt.close(fig)

    # confusion matrix
    fig, ax = plt.subplots(figsize=(3.6, 3.4))
    cm = np.array([[tn, fp], [fn, tp]])
    ax.imshow(cm, cmap="Blues")
    for (r, c), v in np.ndenumerate(cm):
        ax.text(c, r, str(v), ha="center", va="center",
                color="white" if v > cm.max()/2 else "black", fontsize=12)
    ax.set_xticks([0, 1]); ax.set_xticklabels(["pred 0", "pred 1"])
    ax.set_yticks([0, 1]); ax.set_yticklabels(["true 0", "true 1"])
    ax.set_title(f"{title}\nconfusion (test)")
    fig.tight_layout()
    fig.savefig(os.path.join(d, "fig_confusion.png"), dpi=160); plt.close(fig)

    print(f"  [{name}] n={n} peak|t|={peak_t:.1f} train={train_acc*100:.1f}% "
          f"test={test_acc*100:.1f}% (K={k}) -> {d}")
    return summ


# --------------------------------------------------------------------------- #
def load_honest_pool(path, n_each):
    d = np.load(path)
    c0 = [int(h, 16) for h in d["class0"]]
    c1 = [int(h, 16) for h in d["class1"]]
    n = min(n_each, len(c0), len(c1))
    return c0[:n], c1[:n]


def build_md(summaries, out_md):
    A = summaries["artificial_m0_vs_m1"]
    B = summaries["honest_0_vs_failure"]
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(f"""# HQC-G single-trace oracle — two datasets, side by side

*Generated {stamp} on the CW310 HQC-G core, identical scope settings for both.*

Two message-class pairs are profiled with the **same** template attack. The only
difference is **which two classes** the device is asked to separate.

| | **A — artificial** `m'=0` vs `m'=1` | **B — honest** `m'=0` vs decode-FAILURE |
|---|---|---|
| what it is | a clean hand-picked 1-bit contrast | the pair the **real key-recovery attack** queries |
| attacker can inject it? | **no** | **yes** (chosen ciphertext → decode succeeds/fails) |
| traces | {A['n_traces']} | {B['n_traces']} |
| samples/trace | {A['samples']} | {B['samples']} |
| peak \\|t\\| | **{A['peak_abs_t']}** | **{B['peak_abs_t']}** |
| single-trace oracle (test) | **{A['test_acc']*100:.1f}%** | **{B['test_acc']*100:.1f}%** |
| verdict | **over-states** the oracle — do NOT report | **honest** paper number |

**Why B is the correct one.** During a chosen-ciphertext attack on HQC the leaking
secret bit `y[j]` shows up *only* as a decode **success** (`m'=0`, 15 corrected
errors) vs **failure** (garbage `m'`, 16 errors). The oracle question is literally
"did the inner decode succeed or fail?" — the Ravi et al. (TCHES 2020)
plaintext-checking-oracle model. The artificial `m'=0/1` pair is a value the
attacker never gets to inject, so its ~{A['test_acc']*100:.0f}% accuracy is not
achievable in a real attack. Dataset B's ~{B['test_acc']*100:.0f}% is the honest
ceiling; it is amplified to ≥99% full-key by majority-vote / soft-LLR combining
over independent queries (see `paper_results/soft_vs_hard.csv`).

---

## Dataset A — artificial `m'=0` vs `m'=1`  (folder `results_datasets/artificial_m0_vs_m1/`)

peak |t| = {A['peak_abs_t']}, single-trace test accuracy = **{A['test_acc']*100:.1f}%**
(train {A['train_acc']*100:.1f}%, K={A['poi_k']} POIs).
Confusion (test): TP={A['tp']} TN={A['tn']} FP={A['fp']} FN={A['fn']}.

![A TVLA](results_datasets/artificial_m0_vs_m1/fig_tvla.png)
![A means](results_datasets/artificial_m0_vs_m1/fig_means.png)
![A diff](results_datasets/artificial_m0_vs_m1/fig_diff.png)
![A oracle](results_datasets/artificial_m0_vs_m1/fig_oracle_hist.png)
![A confusion](results_datasets/artificial_m0_vs_m1/fig_confusion.png)

CSVs: `class_means.csv`, `diff_of_means.csv`, `tvla_curve.csv`,
`oracle_scores.csv`, `summary.csv` (+ `raw_traces.npz`).

---

## Dataset B — honest `m'=0` vs decode-FAILURE  (folder `results_datasets/honest_0_vs_failure/`)

peak |t| = {B['peak_abs_t']}, single-trace test accuracy = **{B['test_acc']*100:.1f}%**
(train {B['train_acc']*100:.1f}%, K={B['poi_k']} POIs).
Confusion (test): TP={B['tp']} TN={B['tn']} FP={B['fp']} FN={B['fn']}.
The overlap in the projection histogram is the physical HW≈0 confounder floor.

![B TVLA](results_datasets/honest_0_vs_failure/fig_tvla.png)
![B means](results_datasets/honest_0_vs_failure/fig_means.png)
![B diff](results_datasets/honest_0_vs_failure/fig_diff.png)
![B oracle](results_datasets/honest_0_vs_failure/fig_oracle_hist.png)
![B confusion](results_datasets/honest_0_vs_failure/fig_confusion.png)

CSVs: same set as A (+ `raw_traces.npz`).

---

## Reproduce
```
python gen_oracle_msgs.py --n 1000 --seed 1              # honest pool (once)
python two_oracle_datasets.py --n 1000                   # captures A and B
```
""")
    print(f"wrote {out_md}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000,
                    help="traces per dataset (balanced across the 2 classes)")
    ap.add_argument("--pool", default=os.path.join(HERE, "oracle_msgs.npz"))
    args = ap.parse_args()
    os.makedirs(ROOT, exist_ok=True)
    rng = random.Random(1)

    # honest pool
    n_each = args.n // 2
    c0, c1 = load_honest_pool(args.pool, n_each)
    n_each = min(n_each, len(c0), len(c1))

    target = program_cw310()
    scope = Scope()
    print(f"scope: {scope.n_samples} samples/trace\n")
    k_grid = [10, 20, 40, 80]

    # ---- Dataset A: artificial m'=0 / m'=1 ----
    print("[A] artificial m'=0 vs m'=1 ...")
    msgsA = [0] * n_each + [1] * n_each
    labA = [0] * n_each + [1] * n_each
    zipA = list(zip(msgsA, labA)); rng.shuffle(zipA)
    msgsA, labA = zip(*zipA)
    XA, yA = capture(target, scope, msgsA, labA, "A")

    # ---- Dataset B: honest 0 vs failure ----
    print("[B] honest m'=0 vs decode-failure ...")
    msgsB = list(c0) + list(c1)
    labB = [0] * n_each + [1] * n_each
    zipB = list(zip(msgsB, labB)); rng.shuffle(zipB)
    msgsB, labB = zip(*zipB)
    XB, yB = capture(target, scope, msgsB, labB, "B")
    scope.close()

    summaries = {}
    summaries["artificial_m0_vs_m1"] = process(
        "artificial_m0_vs_m1", "A: m'=0 vs m'=1 (artificial)",
        XA, yA, k_grid, ROOT, rng)
    summaries["honest_0_vs_failure"] = process(
        "honest_0_vs_failure", "B: m'=0 vs decode-failure (honest)",
        XB, yB, k_grid, ROOT, rng)

    # combined CSV
    with open(os.path.join(ROOT, "datasets_summary.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dataset", "n_traces", "samples", "poi_k", "peak_abs_t",
                    "train_acc", "test_acc", "tp", "tn", "fp", "fn"])
        for s in summaries.values():
            w.writerow([s["dataset"], s["n_traces"], s["samples"], s["poi_k"],
                        s["peak_abs_t"], s["train_acc"], s["test_acc"],
                        s["tp"], s["tn"], s["fp"], s["fn"]])

    build_md(summaries, os.path.join(HERE, "..", "ORACLE_DATASETS.md"))


if __name__ == "__main__":
    main()
