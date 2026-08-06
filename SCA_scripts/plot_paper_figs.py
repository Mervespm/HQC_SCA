#!/usr/bin/env python
"""
plot_paper_figs.py  --  regenerate ALL trace-domain paper figures from a SINGLE
labelled pool (raw_pool.npz), so they share one identical sample axis, one peak
location and one sample rate.  Device-free (numpy + matplotlib only).

Produces, in the pool folder:
    fig_tvla.png / .csv         (Welch |t| vs time, TVLA)
    fig_oracle_hist.png / .csv  (single-trace LDA oracle histogram + accuracy)
    fig_mean_traces.png / .csv  (class-mean overlay + zoom + |t|, "why it works")

All x-axes are in microseconds (rate-independent) and cover the SAME window,
so the figures are directly comparable in the paper.

Usage:
    python plot_paper_figs.py <folder|raw_pool.npz> [--fs 1.25e9] [--k 20] [--crop_us A B]
"""
import argparse, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

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
    t = (m0 - m1) / np.sqrt(v0 / len(x0) + v1 / len(x1) + 1e-24)
    return m0, m1, t


def lda_template(X, y, pois):
    x0, x1 = X[y == 0], X[y == 1]
    m0, m1 = x0.mean(0), x1.mean(0)
    v0, v1 = x0.var(0, ddof=1), x1.var(0, ddof=1)
    vp = 0.5 * (v0 + v1) + 1e-24
    w = ((m0 - m1) / vp)[pois]
    bias = float(w @ (0.5 * (m0[pois] + m1[pois])))
    return w, bias


def contiguous_runs(idx):
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
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--fs", type=float, default=1.25e9, help="sample rate (Hz)")
    ap.add_argument("--k", type=int, default=20, help="#POIs for template/markers")
    ap.add_argument("--crop_us", type=float, nargs=2, default=None,
                    help="crop all x-axes to [A,B] microseconds")
    args = ap.parse_args()

    X, y, outdir = load_pool(args.path)
    n0, n1 = int((y == 0).sum()), int((y == 1).sum())
    ns = X.shape[1]
    t_us = np.arange(ns) / args.fs * 1e6                     # x-axis in microseconds

    m0, m1, t = welch_t(X, y)
    at = np.abs(t)
    pois = np.argsort(at)[::-1][:args.k]
    peak = int(at.argmax())

    if args.crop_us:
        lo = int(args.crop_us[0] * 1e-6 * args.fs)
        hi = int(args.crop_us[1] * 1e-6 * args.fs)
    else:
        lo, hi = 0, ns
    sl = slice(max(0, lo), min(ns, hi))

    # ---------- Fig 1: TVLA ----------
    fig, ax = plt.subplots(figsize=(9, 3.4))
    for a, b in contiguous_runs(pois):
        ax.axvspan(t_us[a], t_us[b], color="0.85", zorder=0)
    ax.plot(t_us[sl], at[sl], lw=0.8, color="#1f4e79")
    ax.axhline(TVLA_THRESH, ls="--", color="orange", lw=1, label=f"threshold {TVLA_THRESH}")
    ax.set_xlabel("time (\u00b5s)"); ax.set_ylabel("|Welch t|")
    ax.set_title(f"TVLA (m'=0 vs m'\u22600), n={n0}+{n1}, peak |t|={at.max():.1f}")
    ax.set_xlim(t_us[sl][0], t_us[sl][-1]); ax.legend(loc="upper right"); ax.grid(alpha=0.25)
    fig.tight_layout(); fig.savefig(os.path.join(outdir, "fig_tvla.png"), dpi=160)
    plt.close(fig)

    # ---------- Fig 2: single-trace oracle histogram ----------
    rng = np.random.default_rng(0)
    perm = rng.permutation(len(X)); ntr = len(X) // 2
    tr, te = perm[:ntr], perm[ntr:]
    pois_tr = np.argsort(np.abs(welch_t(X[tr], y[tr])[2]))[::-1][:args.k]
    w, bias = lda_template(X[tr], y[tr], pois_tr)
    proj = X[te][:, pois_tr] @ w
    pred = np.where(proj > bias, 0, 1)
    acc = float((pred == y[te]).mean())
    fig, ax = plt.subplots(figsize=(9, 3.4))
    ax.hist(proj[y[te] == 0], bins=60, alpha=0.7, color="#1f4e79", label="m'=0")
    ax.hist(proj[y[te] == 1], bins=60, alpha=0.7, color="#c0392b", label="m'\u22600")
    ax.axvline(bias, ls="--", color="k", lw=1, label="decision boundary")
    ax.set_xlabel("LDA projection"); ax.set_ylabel("count")
    ax.set_title(f"Single-trace oracle: held-out accuracy = {acc*100:.2f}%  (k={args.k} POIs)")
    ax.legend(loc="upper center"); ax.grid(alpha=0.25)
    fig.tight_layout(); fig.savefig(os.path.join(outdir, "fig_oracle_hist.png"), dpi=160)
    plt.close(fig)

    # ---------- Fig 3: mean traces (full + zoom + |t|) in microseconds ----------
    half = 120
    z0, z1 = max(0, peak - half), min(ns, peak + half)
    fig, (a0, az, a1) = plt.subplots(3, 1, figsize=(9, 8),
                                     gridspec_kw={"height_ratios": [2, 2, 1.2]})
    for a, b in contiguous_runs(pois):
        a0.axvspan(t_us[a], t_us[b], color="0.85", zorder=0)
        a1.axvspan(t_us[a], t_us[b], color="0.85", zorder=0)
    a0.axvspan(t_us[z0], t_us[z1], color="#ffe08a", alpha=0.5, zorder=0)
    a0.plot(t_us[sl], m0[sl], lw=0.7, color="#1f4e79", label=f"m'=0 (n={n0})")
    a0.plot(t_us[sl], m1[sl], lw=0.7, color="#c0392b", label=f"m'\u22600 (n={n1})", alpha=0.85)
    a0.set_ylabel("mean power (ADC)"); a0.set_title("class-mean power traces (full window)")
    a0.legend(loc="upper right"); a0.grid(alpha=0.25); a0.set_xlim(t_us[sl][0], t_us[sl][-1])

    zx = t_us[z0:z1]
    az.plot(zx, m0[z0:z1], lw=1.3, color="#1f4e79", label="m'=0")
    az.plot(zx, m1[z0:z1], lw=1.3, color="#c0392b", label="m'\u22600")
    ad = az.twinx()
    ad.plot(zx, (m0 - m1)[z0:z1], lw=1.0, color="#2e7d32", ls="--", label="difference")
    ad.set_ylabel("diff (ADC)", color="#2e7d32"); ad.tick_params(axis="y", labelcolor="#2e7d32")
    az.set_ylabel("mean power (ADC)")
    az.set_title(f"zoom on leakage point (peak |t| at {t_us[peak]:.2f} \u00b5s)")
    az.legend(loc="upper left"); az.grid(alpha=0.25); az.set_xlim(zx[0], zx[-1])

    a1.plot(t_us[sl], at[sl], lw=0.8, color="#3d3d3d")
    a1.axhline(TVLA_THRESH, ls="--", color="orange", lw=1, label=f"threshold {TVLA_THRESH}")
    a1.scatter(t_us[pois], at[pois], s=14, color="#c0392b", zorder=5, label=f"top-{args.k} POIs")
    a1.set_ylabel("|Welch t|"); a1.set_xlabel("time (\u00b5s)")
    a1.legend(loc="upper right"); a1.grid(alpha=0.25); a1.set_xlim(t_us[sl][0], t_us[sl][-1])
    fig.tight_layout(); fig.savefig(os.path.join(outdir, "fig_mean_traces.png"), dpi=160)
    plt.close(fig)

    # ---------- CSVs ----------
    np.savetxt(os.path.join(outdir, "fig_tvla.csv"),
               np.column_stack([t_us, at]), delimiter=",",
               header="time_us,abs_welch_t", comments="")
    np.savetxt(os.path.join(outdir, "fig_oracle_hist.csv"),
               np.column_stack([proj, y[te]]), delimiter=",",
               header="lda_projection,label", comments="")
    np.savetxt(os.path.join(outdir, "fig_mean_traces.csv"),
               np.column_stack([t_us, m0, m1, m0 - m1, t]), delimiter=",",
               header="time_us,mean_m0,mean_m1,diff,welch_t", comments="")

    print(f"pool: {len(X)} traces, {ns} samples @ {args.fs/1e9:.2f} GS/s"
          f"  ({ns/args.fs*1e6:.1f} \u00b5s window)")
    print(f"peak |t| = {at.max():.1f} at {t_us[peak]:.2f} \u00b5s (sample {peak})")
    print(f"single-trace oracle accuracy (k={args.k}) = {acc*100:.2f}%")
    print("saved fig_tvla / fig_oracle_hist / fig_mean_traces (.png + .csv) to", outdir)


if __name__ == "__main__":
    main()
