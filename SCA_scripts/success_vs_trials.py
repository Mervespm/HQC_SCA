#!/usr/bin/env python
"""
success_vs_trials.py  --  attack-feasibility figure, in the classic
"success probability vs number of trials" style (log2 x-axis, analytic
dashed curve + shaded band + red 'Simulated' Monte-Carlo markers).

Model
-----
The single-trace oracle reads one secret bit y[j] correctly with
probability p (this p is exactly the single-trace accuracy measured in
learning_curve.py -- e.g. 0.90 @240 traces, 0.99 @1200 traces).

To harden a bit we repeat the (chosen-ciphertext) query R times and take a
MAJORITY vote.  Probability the vote is correct:

    P_bit(R, p) = sum_{k > R/2} C(R,k) p^k (1-p)^(R-k)   (+ 1/2 * tie term)

Recovering the full sparse secret y needs all W coefficients right:

    P_key(R, p) = P_bit(R, p) ** W

Left panel  : per-coefficient success vs R, for several oracle accuracies.
Right panel : full-key (W coefficients) success vs R, same accuracies.

Both panels overlay Monte-Carlo 'Simulated' points (red squares) and a
shaded +-std band, matching the reference aesthetic.

Device-independent: numpy + matplotlib only.

Usage:
    python success_vs_trials.py [--W 66] [--out <folder>] [--sims 4000]
"""
import argparse, os, sys, math
from datetime import datetime
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from math import comb

# oracle single-trace accuracies to draw (tie them to the learning curve)
ACCURACIES = [0.99, 0.95, 0.90, 0.85]
W_DEFAULT = 66                       # HQC-128 Hamming weight of y


def p_bit_majority(R, p):
    """Prob. a majority vote of R Bernoulli(p) trials is correct (tie=1/2).
    Computed in log-space to avoid overflow of comb(R,k) at large R."""
    lp, lq = math.log(p), math.log1p(-p)
    tot = 0.0
    for k in range(R + 1):
        logc = (math.lgamma(R + 1) - math.lgamma(k + 1)
                - math.lgamma(R - k + 1) + k * lp + (R - k) * lq)
        term = math.exp(logc)
        if 2 * k > R:
            tot += term
        elif 2 * k == R:
            tot += 0.5 * term
    return tot


def mc_bit(R, p, sims, rng):
    """Monte-Carlo estimate of majority-vote success + std over `sims` runs."""
    draws = (rng.random((sims, R)) < p).sum(1)          # #correct votes
    succ = (2 * draws > R) | ((2 * draws == R) & (rng.random(sims) < 0.5))
    m = succ.mean()
    return m, math.sqrt(max(m * (1 - m), 1e-12) / sims)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--W", type=int, default=W_DEFAULT)
    ap.add_argument("--sims", type=int, default=4000)
    ap.add_argument("--rmax_pow", type=int, default=13, help="max R = 2**this")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    rng = np.random.default_rng(0)
    R_curve = np.unique(np.round(np.logspace(0, args.rmax_pow,
                                             120, base=2)).astype(int))
    R_curve = R_curve[R_curve >= 1]
    # sparser grid for the Monte-Carlo markers
    R_marks = np.unique(np.round(np.logspace(0, args.rmax_pow,
                                             13, base=2)).astype(int))

    colors = ["#0b3d91", "#1f6fd6", "#5aa0e6", "#a9c9f0"]

    fig, (axL, axR) = plt.subplots(1, 2, figsize=(12, 4.3), sharey=True)

    for p, c in zip(ACCURACIES, colors):
        # ---- analytic curves ----
        yb = np.array([p_bit_majority(int(R), p) for R in R_curve])
        yk = yb ** args.W
        axL.plot(R_curve, yb, "--", color=c, lw=1.6,
                 label=f"oracle acc = {p:.2f}")
        axR.plot(R_curve, yk, "--", color=c, lw=1.6,
                 label=f"oracle acc = {p:.2f}")

        # ---- Monte-Carlo 'Simulated' points + shaded band ----
        mb = np.array([mc_bit(int(R), p, args.sims, rng) for R in R_marks])
        mean_b, std_b = mb[:, 0], mb[:, 1]
        axL.fill_between(R_marks, mean_b - std_b, mean_b + std_b,
                         color=c, alpha=0.18, lw=0)
        mean_k = mean_b ** args.W
        # propagate band to key: d(x^W) = W x^(W-1) dx
        std_k = args.W * np.power(np.clip(mean_b, 1e-9, 1), args.W - 1) * std_b
        axR.fill_between(R_marks, np.clip(mean_k - std_k, 0, 1),
                         np.clip(mean_k + std_k, 0, 1),
                         color=c, alpha=0.18, lw=0)

    # red 'Simulated' markers (only label once, like the reference)
    for p in [ACCURACIES[1]]:                         # representative curve
        mb = np.array([mc_bit(int(R), p, args.sims, rng)[0] for R in R_marks])
        axL.plot(R_marks, mb, "s", mfc="none", mec="#d62728",
                 mew=1.3, ms=7, label="Simulated")
        axR.plot(R_marks, mb ** args.W, "s", mfc="none", mec="#d62728",
                 mew=1.3, ms=7, label="Simulated")

    for ax, title in [(axL, "per coefficient of y"),
                      (axR, f"full key (all W={args.W} coefficients)")]:
        ax.set_xscale("log", base=2)
        ax.set_xlim(1, 2 ** args.rmax_pow)
        ax.set_ylim(-0.02, 1.02)
        ax.set_xlabel("number of oracle repetitions per coefficient  (R)")
        ax.set_title(title)
        ax.grid(alpha=0.3, which="both")
        ax.legend(loc="lower right", framealpha=0.92, fontsize=9)
    axL.set_ylabel("attack success probability")

    fig.suptitle("HQC-G plaintext-checking oracle: success vs. repetitions",
                 y=1.02, fontsize=12)
    fig.tight_layout()

    out = args.out or os.path.join(
        "PowerTrace_HQC_G",
        "success_" + datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))
    os.makedirs(out, exist_ok=True)
    png = os.path.join(out, "success_vs_trials.png")
    fig.savefig(png, dpi=160, bbox_inches="tight")

    # dump the analytic curves to CSV
    hdr = ["R"] + [f"pbit_acc{p}" for p in ACCURACIES] + \
                  [f"pkey_acc{p}" for p in ACCURACIES]
    cols = [R_curve]
    for p in ACCURACIES:
        cols.append(np.array([p_bit_majority(int(R), p) for R in R_curve]))
    for p in ACCURACIES:
        cols.append(np.array([p_bit_majority(int(R), p) for R in R_curve]) ** args.W)
    np.savetxt(os.path.join(out, "success_vs_trials.csv"),
               np.column_stack(cols), delimiter=",",
               header=",".join(hdr), comments="")

    # print the practical takeaway: min R for 99% full-key success
    print("Saved:", png)
    for p in ACCURACIES:
        yk = np.array([p_bit_majority(int(R), p) for R in R_curve]) ** args.W
        idx = np.argmax(yk >= 0.99)
        r99 = int(R_curve[idx]) if yk[idx] >= 0.99 else None
        print(f"  oracle acc {p:.2f}: full-key >=99% at R = "
              f"{r99 if r99 else '>2**'+str(args.rmax_pow)} "
              f"(=> ~{r99*args.W if r99 else float('nan')} traces total)")


if __name__ == "__main__":
    main()
