#!/usr/bin/env python3
"""Generate the professional 3-panel SCA figure for any oracle dataset.

Panel 1: class-mean power traces (full window)
Panel 2: zoom on leakage point (peak |t|) with difference-of-means overlay
Panel 3: Welch |t| curve, threshold 4.5, top-20 POIs marked

Usage:
  python plot_sca_figure.py k_block0_0_vs_sigma         # K oracle
  python plot_sca_figure.py honest_0_vs_failure         # G honest oracle
  python plot_sca_figure.py artificial_m0_vs_m1         # G artificial (dismissed)
  python plot_sca_figure.py --all                       # all three side by side
"""
import os
import sys
import csv
import argparse
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

HERE   = os.path.dirname(os.path.abspath(__file__))
ROOT   = os.path.join(HERE, "results_datasets")
FS_HZ  = 156.25e6     # sample rate (update if changed)


def load_dataset(name):
    folder = os.path.join(ROOT, name)
    npz    = np.load(os.path.join(folder, "raw_traces.npz"))
    X, y   = npz["X"].astype(np.float64), npz["y"]
    summ   = {}
    with open(os.path.join(folder, "summary.csv")) as f:
        for row in csv.reader(f):
            if len(row) == 2:
                summ[row[0]] = row[1]
    return X, y, summ


def make_figure(name, title_suffix=""):
    X, y, summ = load_dataset(name)
    n0, n1 = (y == 0).sum(), (y == 1).sum()
    S = X.shape[1]
    t_us = np.arange(S) / FS_HZ * 1e6

    m0 = X[y == 0].mean(0)
    m1 = X[y == 1].mean(0)
    diff = m0 - m1

    # Welch t
    v0 = X[y == 0].var(0, ddof=1) / max(n0, 1)
    v1 = X[y == 1].var(0, ddof=1) / max(n1, 1)
    t  = diff / np.sqrt(v0 + v1 + 1e-30)
    peak_idx = int(np.abs(t).argmax())
    peak_t   = float(np.abs(t).max())
    peak_us  = t_us[peak_idx]

    # top-20 POIs
    poi_idx = np.argsort(np.abs(t))[::-1][:20]

    # zoom window: ±200 samples around peak
    zoom_half = min(200, peak_idx, S - 1 - peak_idx)
    z0, z1   = peak_idx - zoom_half, peak_idx + zoom_half

    test_acc = float(summ.get("test_acc", 0))
    peak_abs = float(summ.get("peak_abs_t", peak_t))
    n_total  = int(summ.get("n_traces", n0 + n1))

    BLUE, RED, GREEN = "#1f4e79", "#c0392b", "#27ae60"
    fig, axes = plt.subplots(3, 1, figsize=(11, 11))
    fig.suptitle(
        f"HQC-G Keccak SCA — {name.replace('_', ' ')}{title_suffix}\n"
        f"N={n_total}  peak|t|={peak_abs:.1f}  oracle={test_acc*100:.1f}%",
        fontsize=12, fontweight="bold"
    )

    # ── Panel 1: full trace ──────────────────────────────────────────────────
    ax = axes[0]
    ax.plot(t_us, m0, color=BLUE, lw=0.6, label=f"class 0 success (n={n0})")
    ax.plot(t_us, m1, color=RED,  lw=0.6, label=f"class 1 failure  (n={n1})")
    ax.axvspan(t_us[z0], t_us[z1], color="gold", alpha=0.35, label="zoom region")
    ax.set_title("class-mean power traces (full window)")
    ax.set_ylabel("mean power (ADC)")
    ax.set_xlabel("time (μs)")
    ax.legend(fontsize=8, loc="upper right")
    ax.grid(alpha=0.3)

    # ── Panel 2: zoom + diff ─────────────────────────────────────────────────
    ax2 = axes[1]
    ax2r = ax2.twinx()
    zs = slice(z0, z1)
    zt = t_us[zs]
    ax2.plot(zt, m0[zs], color=BLUE, lw=1.0, label="class 0")
    ax2.plot(zt, m1[zs], color=RED,  lw=1.0, label="class 1")
    ax2r.plot(zt, diff[zs], color=GREEN, lw=0.9, ls="--", label="diff (m0−m1)")
    ax2.set_title(f"zoom on leakage point (peak |t| at {peak_us:.2f} μs)")
    ax2.set_ylabel("mean power (ADC)")
    ax2r.set_ylabel("diff (ADC)", color=GREEN)
    ax2r.tick_params(axis="y", labelcolor=GREEN)
    ax2.set_xlabel("time (μs)")
    lines = ax2.get_lines() + ax2r.get_lines()
    ax2.legend(handles=lines, labels=[l.get_label() for l in lines],
               fontsize=8, loc="upper left")
    ax2.grid(alpha=0.3)

    # ── Panel 3: TVLA ────────────────────────────────────────────────────────
    ax3 = axes[2]
    ax3.plot(t_us, np.abs(t), color="#2c3e50", lw=0.5)
    ax3.axhline(4.5, color="orange", ls="--", lw=1.2, label="threshold 4.5")
    ax3.scatter(t_us[poi_idx], np.abs(t)[poi_idx],
                color=RED, s=30, zorder=5, label="top-20 POIs")
    ax3.set_title("|Welch t| — TVLA")
    ax3.set_ylabel("|Welch t|")
    ax3.set_xlabel("time (μs)")
    ax3.legend(fontsize=8)
    ax3.grid(alpha=0.3)

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    outpath = os.path.join(ROOT, name, "fig_sca_3panel.png")
    fig.savefig(outpath, dpi=160)
    plt.close(fig)
    print(f"  saved -> {outpath}")
    return outpath


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", nargs="?", default=None)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    datasets = {
        "k_block0_0_vs_sigma":   " (K oracle — implicit rejection)",
        "honest_0_vs_failure":   " (G oracle — honest, DISMISSED for K)",
        "artificial_m0_vs_m1":   " (G artificial — over-states oracle, NOT for paper)",
    }

    if args.all:
        for name, suffix in datasets.items():
            if os.path.isdir(os.path.join(ROOT, name)):
                print(f"[{name}]")
                make_figure(name, suffix)
    elif args.dataset:
        suffix = datasets.get(args.dataset, "")
        make_figure(args.dataset, suffix)
    else:
        print("Usage: python plot_sca_figure.py <dataset_name>  or  --all")
        print("Available:", list(datasets.keys()))


if __name__ == "__main__":
    main()
