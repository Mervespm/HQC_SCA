#!/usr/bin/env python
"""
plot_mean_traces.py  --  "why the oracle works" figure.

Loads a labelled raw-trace pool (raw_pool.npz with keys `traces`,`labels`)
and produces a clean 2-panel publication figure:

  (top)    mean power trace for m'=0  vs  m'!=0, overlaid, with the
           top-k Welch-|t| POIs shaded -- shows the two classes are
           physically distinguishable, and *where*.
  (bottom) Welch |t| across samples, with the 4.5 TVLA threshold and
           the selected POIs marked -- shows leakage is strong & localised.

The POI selection is IDENTICAL to the single-trace oracle
(learning_curve.py / oracle_test.py): top-k by |Welch t|.

Usage:
    python plot_mean_traces.py <folder-with-raw_pool.npz | path\\to.npz> [k]

Device-independent: numpy + matplotlib only.
"""
import os, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

K_DEFAULT = 20
TVLA_THRESH = 4.5


def load_pool(path):
    if os.path.isdir(path):
        path = os.path.join(path, "raw_pool.npz")
    d = np.load(path)
    return d["traces"].astype(np.float64), d["labels"].astype(np.int8), os.path.dirname(path)


def welch_t(X, y):
    x0, x1 = X[y == 0], X[y == 1]
    m0, m1 = x0.mean(0), x1.mean(0)
    v0, v1 = x0.var(0, ddof=1), x1.var(0, ddof=1)
    n0, n1 = len(x0), len(x1)
    t = (m0 - m1) / np.sqrt(v0 / n0 + v1 / n1 + 1e-24)
    return m0, m1, t


def contiguous_runs(idx):
    """Group a sorted index array into (start,end) contiguous spans for shading."""
    if len(idx) == 0:
        return []
    idx = np.sort(idx)
    runs, s = [], idx[0]
    for a, b in zip(idx[:-1], idx[1:]):
        if b != a + 1:
            runs.append((s, a)); s = b
    runs.append((s, idx[-1]))
    return runs


def main():
    if len(sys.argv) < 2:
        print("usage: python plot_mean_traces.py <folder|raw_pool.npz> [k]")
        sys.exit(1)
    path = sys.argv[1]
    k = int(sys.argv[2]) if len(sys.argv) > 2 else K_DEFAULT

    X, y, outdir = load_pool(path)
    n0, n1 = int((y == 0).sum()), int((y == 1).sum())
    m0, m1, t = welch_t(X, y)
    at = np.abs(t)
    pois = np.argsort(at)[::-1][:k]
    ns = X.shape[1]
    xs = np.arange(ns)
    peak = int(at.argmax())
    half = 120
    z0, z1 = max(0, peak - half), min(ns, peak + half)

    fig, (ax0, axz, ax1) = plt.subplots(3, 1, figsize=(9, 8),
                                        gridspec_kw={"height_ratios": [2, 2, 1.2]})

    # shade POI spans on the full-trace and |t| panels
    for a, b in contiguous_runs(pois):
        ax0.axvspan(a - 1, b + 1, color="0.85", zorder=0)
        ax1.axvspan(a - 1, b + 1, color="0.85", zorder=0)
    # mark the zoom window on the full panel
    ax0.axvspan(z0, z1, color="#ffe08a", alpha=0.5, zorder=0)

    ax0.plot(xs, m0, lw=0.7, color="#1f4e79", label=f"m'=0  (n={n0})")
    ax0.plot(xs, m1, lw=0.7, color="#c0392b", label=f"m'\u22600  (n={n1})", alpha=0.85)
    ax0.set_ylabel("mean power (ADC)")
    ax0.set_title("HQC-G single-trace oracle: class-mean power traces (full window)")
    ax0.legend(loc="upper right", framealpha=0.9)
    ax0.grid(alpha=0.25)
    ax0.set_xlim(0, ns - 1)

    # zoom panel: the two class means visibly diverge at the leakage point
    zx = np.arange(z0, z1)
    axz.plot(zx, m0[z0:z1], lw=1.3, color="#1f4e79", label="m'=0")
    axz.plot(zx, m1[z0:z1], lw=1.3, color="#c0392b", label="m'\u22600")
    axd = axz.twinx()
    axd.plot(zx, (m0 - m1)[z0:z1], lw=1.0, color="#2e7d32", ls="--",
             label="difference (m0\u2212m1)")
    axd.set_ylabel("diff (ADC)", color="#2e7d32")
    axd.tick_params(axis="y", labelcolor="#2e7d32")
    for p in pois:
        if z0 <= p < z1:
            axz.axvline(p, color="0.6", lw=0.6, zorder=0)
    axz.set_ylabel("mean power (ADC)")
    axz.set_title(f"zoom on leakage point (samples {z0}\u2013{z1}, peak |t| at {peak})")
    axz.legend(loc="upper left", framealpha=0.9)
    axz.grid(alpha=0.25)
    axz.set_xlim(z0, z1 - 1)

    ax1.plot(xs, at, lw=0.8, color="#3d3d3d")
    ax1.axhline(TVLA_THRESH, ls="--", color="orange", lw=1,
                label=f"TVLA threshold ({TVLA_THRESH})")
    ax1.scatter(pois, at[pois], s=14, color="#c0392b", zorder=5,
                label=f"top-{k} POIs")
    ax1.set_ylabel("|Welch t|")
    ax1.set_xlabel("sample")
    ax1.legend(loc="upper right", framealpha=0.9)
    ax1.grid(alpha=0.25)
    ax1.set_xlim(0, ns - 1)

    fig.tight_layout()
    out_png = os.path.join(outdir, "mean_traces.png")
    fig.savefig(out_png, dpi=160)

    # also dump the difference-of-means + |t| for external plotting
    out_csv = os.path.join(outdir, "mean_traces.csv")
    np.savetxt(out_csv,
               np.column_stack([xs, m0, m1, m0 - m1, t]),
               delimiter=",", header="sample,mean_m0,mean_m1,diff,welch_t",
               comments="")

    print(f"pool: {len(X)} traces, {ns} samples  (class0={n0}, class1={n1})")
    print(f"peak |t| = {at.max():.1f} at sample {int(at.argmax())}")
    print(f"top-{k} POIs span samples {pois.min()}..{pois.max()}")
    print("saved:", out_png)
    print("saved:", out_csv)


if __name__ == "__main__":
    main()
