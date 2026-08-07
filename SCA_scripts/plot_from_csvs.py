#!/usr/bin/env python3
"""Generate SCA figures from CSV files only — no raw .npz needed.

All CSV files are in the GitHub repo. Clone, install deps, run:

  git clone https://github.com/Mervespm/HQC_SCA
  cd HQC_SCA
  pip install numpy matplotlib
  python SCA_scripts/plot_from_csvs.py --all

Or for a single dataset:
  python SCA_scripts/plot_from_csvs.py k_block0_0_vs_sigma
  python SCA_scripts/plot_from_csvs.py honest_0_vs_failure
  python SCA_scripts/plot_from_csvs.py artificial_m0_vs_m1
"""
import os
import csv
import argparse
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "results_datasets")
FS_HZ = 156.25e6


def load_csv(folder, name):
    path = os.path.join(ROOT, folder, name)
    rows = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            rows.append({k: float(v) for k, v in row.items()})
    return rows


def load_summary(folder):
    path = os.path.join(ROOT, folder, "summary.csv")
    d = {}
    with open(path) as f:
        for row in csv.reader(f):
            if len(row) == 2:
                d[row[0]] = row[1]
    return d


def make_figure(name):
    print(f"[{name}]")
    summ   = load_summary(name)
    tvla   = load_csv(name, "tvla_curve.csv")
    means  = load_csv(name, "class_means.csv")
    scores = load_csv(name, "oracle_scores.csv")

    # arrays
    t_abs   = np.array([r["welch_t"]       for r in tvla])
    t_us    = np.arange(len(t_abs)) / FS_HZ * 1e6
    m0      = np.array([r["mean_class0"]   for r in means])
    m1      = np.array([r["mean_class1"]   for r in means])
    diff    = m0 - m1

    peak_idx = int(np.abs(t_abs).argmax())
    peak_t   = float(np.abs(t_abs).max())
    peak_us  = t_us[peak_idx]
    poi_idx  = np.argsort(np.abs(t_abs))[::-1][:20]

    # oracle scores
    proj  = np.array([r["projection"]  for r in scores])
    label = np.array([r["true_label"]  for r in scores])

    zoom_half = min(200, peak_idx, len(t_abs) - 1 - peak_idx)
    z0, z1    = peak_idx - zoom_half, peak_idx + zoom_half
    zs        = slice(z0, z1)

    test_acc = float(summ.get("test_acc", 0))
    n_traces = summ.get("n_traces", "?")
    BLUE, RED, GREEN = "#1f4e79", "#c0392b", "#27ae60"

    labels_map = {
        "k_block0_0_vs_sigma": "K oracle — success m=0 vs failure sigma",
        "honest_0_vs_failure":  "G oracle (honest) — m=0 vs decode-failure (DISMISSED for K)",
        "artificial_m0_vs_m1":  "G artificial — m=0 vs m=1 (NOT the attack pair)",
    }
    title = labels_map.get(name, name)

    fig, axes = plt.subplots(3, 1, figsize=(11, 11))
    fig.suptitle(
        f"{title}\nN={n_traces}  peak|t|={peak_t:.1f}  oracle={test_acc*100:.1f}%",
        fontsize=11, fontweight="bold"
    )

    # panel 1 — class means full window
    ax = axes[0]
    n0 = int((label == 0).sum()); n1 = int((label == 1).sum())
    ax.plot(t_us, m0, color=BLUE, lw=0.6, label=f"class 0 (n_test~{n0})")
    ax.plot(t_us, m1, color=RED,  lw=0.6, label=f"class 1 (n_test~{n1})")
    ax.axvspan(t_us[z0], t_us[z1], color="gold", alpha=0.35, label="zoom region")
    ax.set_title("class-mean power traces (full window)"); ax.set_ylabel("mean power (ADC)")
    ax.set_xlabel("time (us)"); ax.legend(fontsize=8, loc="upper right"); ax.grid(alpha=0.3)

    # panel 2 — zoom + diff
    ax2 = axes[1]; ax2r = ax2.twinx()
    zt = t_us[zs]
    ax2.plot(zt, m0[zs], color=BLUE, lw=1.0, label="class 0")
    ax2.plot(zt, m1[zs], color=RED,  lw=1.0, label="class 1")
    ax2r.plot(zt, diff[zs], color=GREEN, lw=0.9, ls="--", label="diff (m0-m1)")
    ax2.set_title(f"zoom on leakage point (peak |t| at {peak_us:.2f} us)")
    ax2.set_ylabel("mean power (ADC)"); ax2r.set_ylabel("diff (ADC)", color=GREEN)
    ax2r.tick_params(axis="y", labelcolor=GREEN); ax2.set_xlabel("time (us)")
    lines = ax2.get_lines() + ax2r.get_lines()
    ax2.legend(handles=lines, labels=[l.get_label() for l in lines], fontsize=8)
    ax2.grid(alpha=0.3)

    # panel 3 — TVLA
    ax3 = axes[2]
    ax3.plot(t_us, np.abs(t_abs), color="#2c3e50", lw=0.5)
    ax3.axhline(4.5, color="orange", ls="--", lw=1.2, label="threshold 4.5")
    ax3.scatter(t_us[poi_idx], np.abs(t_abs)[poi_idx],
                color=RED, s=30, zorder=5, label="top-20 POIs")
    ax3.set_title("|Welch t| -- TVLA"); ax3.set_ylabel("|Welch t|")
    ax3.set_xlabel("time (us)"); ax3.legend(fontsize=8); ax3.grid(alpha=0.3)

    fig.tight_layout(rect=[0, 0, 1, 0.94])
    outpath = os.path.join(ROOT, name, "fig_sca_3panel.png")
    fig.savefig(outpath, dpi=160); plt.close(fig)
    print(f"  saved: {outpath}")
    return outpath


def main():
    ap = argparse.ArgumentParser(
        description="Generate SCA 3-panel figures from CSV files (no raw npz needed).\n"
                    "All CSVs are in the GitHub repo."
    )
    ap.add_argument("dataset", nargs="?", default=None,
                    help="Dataset folder name under results_datasets/")
    ap.add_argument("--all", action="store_true", help="Generate for all datasets")
    args = ap.parse_args()

    datasets = [
        "k_block0_0_vs_sigma",
        "honest_0_vs_failure",
        "artificial_m0_vs_m1",
    ]

    if args.all:
        for name in datasets:
            if os.path.isdir(os.path.join(ROOT, name)):
                make_figure(name)
    elif args.dataset:
        make_figure(args.dataset)
    else:
        print("Usage:\n  python plot_from_csvs.py --all\n  python plot_from_csvs.py <dataset_name>")
        print("\nAvailable datasets:")
        for name in datasets:
            if os.path.isdir(os.path.join(ROOT, name)):
                print(f"  {name}")


if __name__ == "__main__":
    main()
