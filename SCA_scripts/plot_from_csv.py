#!/usr/bin/env python3
"""Plot HQC-G leakage results from the CSVs written by collect_data.py.

This needs ONLY numpy + matplotlib -- NO device, NO chipwhisperer, NO picosdk.
Run it anywhere (e.g. after you no longer have the CW310), pointing it at a
collect_* folder you committed to GitHub:

    python plot_from_csv.py PowerTrace_HQC_G/collect_2026-08-05_18-00-00

It writes PNGs next to the CSVs:
    tvla_first_order.png     first-order Welch t vs sample (with +/-4.5 lines)
    tvla_second_order.png    second-order t vs sample
    diff_of_means.png        mean0-mean1 (with POIs marked)
    example_traces.png       a few raw traces per class
    oracle_hist.png          single-trace oracle projection histogram + accuracy
"""
import os
import sys
import csv

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def load_csv(path):
    with open(path) as f:
        rows = list(csv.reader(f))
    header = rows[0]
    data = np.array([[float(x) for x in r] for r in rows[1:]], dtype=np.float64)
    return header, data


def col(header, data, name):
    return data[:, header.index(name)]


def plot_tvla(d, header, data):
    samp = col(header, data, "sample")
    for which, fname, title in [("t_first", "tvla_first_order.png", "First-Order TVLA"),
                                ("t_second", "tvla_second_order.png", "Second-Order TVLA")]:
        if which not in header:
            continue
        t = col(header, data, which)
        plt.figure(figsize=(12, 6))
        plt.plot(samp, t, color="#1b3b6f", linewidth=0.6)
        plt.axhline(4.5, color="#2e8b78", linestyle="--", linewidth=1.4)
        plt.axhline(-4.5, color="#2e8b78", linestyle="--", linewidth=1.4)
        pk = int(np.nanargmax(np.abs(t)))
        plt.plot(samp[pk], t[pk], "ro", ms=6)
        plt.annotate(f"peak |t|={abs(t[pk]):.1f}", (samp[pk], t[pk]),
                     textcoords="offset points", xytext=(8, 8))
        plt.xlabel("Sample No."); plt.ylabel("t-value"); plt.title(title)
        plt.xlim(samp[0], samp[-1]); plt.tight_layout()
        plt.savefig(os.path.join(d, fname), dpi=130); plt.close()


def plot_diff(d, header, data):
    samp = col(header, data, "sample")
    diff = col(header, data, "diff_of_means")
    plt.figure(figsize=(12, 6))
    plt.plot(samp, diff, color="#7a1b3b", linewidth=0.7)
    poi_path = os.path.join(d, "poi.csv")
    if os.path.exists(poi_path):
        _, p = load_csv(poi_path)
        idx = p[:, 0].astype(int)
        plt.plot(samp[idx], diff[idx], "o", color="#f4a300", ms=4, label="POIs")
        plt.legend()
    plt.xlabel("Sample No."); plt.ylabel("mean(m'=0) - mean(m'=1)")
    plt.title("Difference of Means")
    plt.xlim(samp[0], samp[-1]); plt.tight_layout()
    plt.savefig(os.path.join(d, "diff_of_means.png"), dpi=130); plt.close()


def plot_examples(d):
    path = os.path.join(d, "example_traces.csv")
    if not os.path.exists(path):
        return
    header, data = load_csv(path)
    samp = col(header, data, "sample")
    plt.figure(figsize=(12, 6))
    for i, name in enumerate(header):
        if name.startswith("m0_"):
            plt.plot(samp, data[:, i], color="#1b6f3b", alpha=0.5, linewidth=0.5)
        elif name.startswith("m1_"):
            plt.plot(samp, data[:, i], color="#6f1b1b", alpha=0.5, linewidth=0.5)
    plt.plot([], [], color="#1b6f3b", label="m'=0")
    plt.plot([], [], color="#6f1b1b", label="m'=1")
    plt.xlabel("Sample No."); plt.ylabel("power"); plt.legend()
    plt.title("Example power traces per class")
    plt.xlim(samp[0], samp[-1]); plt.tight_layout()
    plt.savefig(os.path.join(d, "example_traces.png"), dpi=130); plt.close()


def plot_oracle(d):
    path = os.path.join(d, "oracle_scores.csv")
    if not os.path.exists(path):
        return
    header, data = load_csv(path)
    proj = col(header, data, "proj")
    label = col(header, data, "label").astype(int)
    thr = 0.5 * (proj[label == 0].mean() + proj[label == 1].mean())
    pred = np.where(proj > thr, 0, 1)
    acc = (pred == label).mean()
    plt.figure(figsize=(10, 6))
    plt.hist(proj[label == 0], bins=60, alpha=0.6, color="#1b6f3b", label="m'=0")
    plt.hist(proj[label == 1], bins=60, alpha=0.6, color="#6f1b1b", label="m'=1")
    plt.axvline(thr, color="k", linestyle="--", label="decision")
    plt.xlabel("template projection"); plt.ylabel("count"); plt.legend()
    plt.title(f"Single-trace oracle projection  (accuracy = {acc*100:.1f}%)")
    plt.tight_layout()
    plt.savefig(os.path.join(d, "oracle_hist.png"), dpi=130); plt.close()
    print(f"  oracle single-trace accuracy = {acc*100:.2f}%")


def main():
    if len(sys.argv) < 2:
        print("usage: python plot_from_csv.py <collect_folder>")
        sys.exit(1)
    d = sys.argv[1]
    header, data = load_csv(os.path.join(d, "tvla_curve.csv"))
    plot_tvla(d, header, data)
    plot_diff(d, header, data)
    plot_examples(d)
    plot_oracle(d)
    print(f"PNGs written to {d}")


if __name__ == "__main__":
    main()
