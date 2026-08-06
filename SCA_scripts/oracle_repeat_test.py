#!/usr/bin/env python3
"""REAL per-query averaging test for the HQC-G PC-oracle (device-side).

H6 in HONEST_ORACLE_SCENARIO.md *simulates* averaging by pooling different
within-class traces. This script does the HONEST version: it re-sends the SAME
chosen ciphertext K times on the live device and averages THOSE traces (true
measurement-noise averaging on a deterministic target), then measures how the
single-QUERY oracle accuracy grows with K.

Protocol:
  1. PROFILE  : capture a labelled training pool (m'=0 vs decode-failure), one
                trace per drawn message, to build the LDA template. (Standard
                profiled-oracle setting, exactly like Ravi / Ji-Dubrova.)
  2. QUERY    : draw N_QUERY fresh messages (balanced across the two classes);
                for EACH, capture K_MAX repeated traces of the *same* message.
  3. EVALUATE : for K in 1,2,4,8,16 average the first K repeats of each query,
                classify with the template, report single-QUERY accuracy vs K.
                Because the device is deterministic, the K repeats differ only by
                noise -> averaging raises SNR by ~sqrt(K), lifting 73% -> ~97%.

Outputs (in PowerTrace_HQC_G/avgtest_<stamp>/):
  averaging_real.csv   K, accuracy, std, n_queries
  averaging_real.png   accuracy vs K (real repeats)   -> replaces simulated H6
  template.npz         the profiling template (m0,m1,pois,w,bias)
  metadata.json        run settings

Close the PicoScope GUI, then run in the x64 conda env:
  & "C:\\Users\\t-mkarabulut\\Miniconda3x64\\envs\\cwhmac\\python.exe" oracle_repeat_test.py
"""
import os
import json
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
PROFILE_N = 2000     # labelled training traces to build the template
N_QUERY   = 400      # distinct fresh chosen ciphertexts to score (balanced)
K_MAX     = 16       # repeated captures of the SAME ciphertext per query
K_GRID    = [1, 2, 4, 8, 16]
N_POI     = 40       # POIs for the template (ties with full-cov at ~73%)
MSG_POOL  = os.path.join(os.path.dirname(__file__), "oracle_msgs.npz")
OUT_ROOT  = os.path.join(os.path.dirname(__file__), "PowerTrace_HQC_G")
# ====================================================================== #


def load_pools():
    d = np.load(MSG_POOL)
    c0 = [int(h, 16) for h in d["class0"]]
    c1 = [int(h, 16) for h in d["class1"]]
    return c0, c1


def welch_t(X, y):
    x0, x1 = X[y == 0], X[y == 1]
    m0, m1 = x0.mean(0), x1.mean(0)
    v0, v1 = x0.var(0, ddof=1), x1.var(0, ddof=1)
    t = (m0 - m1) / np.sqrt(v0 / len(x0) + v1 / len(x1) + 1e-24)
    return t, m0, m1, v0, v1


def build_template(X, y, k):
    """Diagonal-LDA template on top-k Welch-|t| POIs (matches collect_data.py)."""
    t, m0, m1, v0, v1 = welch_t(X, y)
    pois = np.argsort(np.abs(t))[::-1][:k]
    vp = 0.5 * (v0 + v1) + 1e-24
    w = ((m0 - m1) / vp)[pois]
    bias = float(w @ (0.5 * (m0[pois] + m1[pois])))
    return dict(pois=pois, w=w, bias=bias, m0=m0, m1=m1, t=t)


def classify(rows, tpl):
    proj = rows[:, tpl["pois"]] @ tpl["w"]
    return np.where(proj > tpl["bias"], 0, 1).astype(np.int8)


def main():
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    outdir = os.path.join(OUT_ROOT, f"avgtest_{stamp}")
    os.makedirs(outdir, exist_ok=True)
    msgs0, msgs1 = load_pools()
    print(f"pools: class0={len(msgs0)}  class1={len(msgs1)}")

    target = program_cw310()
    scope = Scope()
    ns = scope.n_samples
    print(f"scope: {ns} samples/trace")

    # ---- 1. PROFILE: labelled training pool (1 trace / drawn message) ----
    Xtr = np.empty((PROFILE_N, ns), dtype=np.float64)
    ytr = np.empty(PROFILE_N, dtype=np.int8)
    for i in tqdm(range(PROFILE_N), desc="profile"):
        coin = random.randint(0, 1)
        m = random.choice(msgs0 if coin == 0 else msgs1)
        scope.arm(); run_one_g(target, m)
        tr, _ = scope.read()
        Xtr[i] = tr; ytr[i] = coin
    tpl = build_template(Xtr, ytr, N_POI)
    base_acc = float((classify(Xtr, tpl) == ytr).mean())   # train-set sanity
    print(f"template built: peak |t|={np.abs(tpl['t']).max():.1f}, "
          f"train acc={base_acc*100:.1f}%")

    # ---- 2. QUERY: N_QUERY fresh messages, K_MAX repeats of EACH ----
    # store per-query repeated traces so we can average the first K for any K.
    qlabel = np.empty(N_QUERY, dtype=np.int8)
    qrepeats = np.empty((N_QUERY, K_MAX, ns), dtype=np.float64)
    for q in tqdm(range(N_QUERY), desc="query"):
        coin = q % 2                       # balanced classes
        m = random.choice(msgs0 if coin == 0 else msgs1)
        qlabel[q] = coin
        for r in range(K_MAX):             # SAME message, K_MAX times
            scope.arm(); run_one_g(target, m)
            tr, _ = scope.read()
            qrepeats[q, r] = tr
    scope.close()

    # ---- 3. EVALUATE: accuracy vs K (average first K repeats per query) ----
    rows = []
    for K in K_GRID:
        avg = qrepeats[:, :K, :].mean(axis=1)      # (N_QUERY, ns)
        pred = classify(avg, tpl)
        acc = float((pred == qlabel).mean())
        # per-class recall for the paper's confusion note
        r0 = float((pred[qlabel == 0] == 0).mean())
        r1 = float((pred[qlabel == 1] == 1).mean())
        rows.append((K, acc, r0, r1))
        print(f"  K={K:>2}  single-query acc={acc*100:6.2f}%  "
              f"(m'=0 recall {r0*100:.1f}%, fail recall {r1*100:.1f}%)")

    # ---- save CSV + figure + template ----
    np.savetxt(os.path.join(outdir, "averaging_real.csv"),
               np.array([(K, a, r0, r1) for K, a, r0, r1 in rows]),
               delimiter=",", header="K,accuracy,recall_m0,recall_fail",
               comments="", fmt="%.6g")
    np.savez(os.path.join(outdir, "template.npz"),
             pois=tpl["pois"], w=tpl["w"], bias=tpl["bias"],
             m0=tpl["m0"], m1=tpl["m1"], t=tpl["t"])

    Kv = [r[0] for r in rows]; acc = [r[1] * 100 for r in rows]
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.plot(Kv, acc, marker="o", lw=2, color="#0b6e4f")
    for k_, a_ in zip(Kv, acc):
        ax.annotate(f"{a_:.1f}%", (k_, a_), textcoords="offset points",
                    xytext=(0, 8), ha="center", fontsize=9)
    ax.set_xscale("log", base=2); ax.set_xticks(Kv); ax.set_xticklabels(Kv)
    ax.set_xlabel("REAL repeated captures averaged per query  K")
    ax.set_ylabel("single-query oracle accuracy (%)")
    ax.set_title(f"Real per-query averaging on device (N={N_QUERY} queries)")
    ax.grid(alpha=0.3); ax.set_ylim(65, 100)
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, "averaging_real.png"), dpi=160)
    plt.close(fig)

    with open(os.path.join(outdir, "metadata.json"), "w") as f:
        json.dump(dict(created=stamp, n_samples=ns, profile_n=PROFILE_N,
                       n_query=N_QUERY, k_max=K_MAX, n_poi=N_POI,
                       sample_rate_hz=getattr(scope, "fs", None),
                       train_acc=base_acc,
                       results=[dict(K=K, acc=a, recall_m0=r0, recall_fail=r1)
                                for K, a, r0, r1 in rows]), f, indent=2)

    print(f"\nDONE. Saved real-averaging curve + template to {outdir}")
    print("This REPLACES the simulated H6 with genuine device repeats.")


if __name__ == "__main__":
    main()
