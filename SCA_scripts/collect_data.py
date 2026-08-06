#!/usr/bin/env python3
"""Collect HQC-G leakage data on the LIVE device and save plot-ready CSVs.

Run this WHILE YOU STILL HAVE THE DEVICE. It captures as many labelled traces
(m'=0 vs m'=1) as you let it, and writes small CSV files you can commit to
GitHub and plot later OFFLINE with plot_from_csv.py (no device / chipwhisperer
needed).

What it saves (all CSV, tiny, git-friendly):
  tvla_curve.csv       sample, mean0, mean1, diff_of_means, t_first, t_second
  oracle_scores.csv    proj, label        (held-out test set -> histogram/accuracy)
  poi.csv              poi_sample_index   (top leaking samples)
  example_traces.csv   sample, m0_ex0..., m1_ex0...   (a few raw traces per class)
  summary.csv          key, value         (peak |t|, N, accuracy, sample rate...)
  metadata.json        full run settings
Optionally also raw_traces.npz (float32) for full offline reproduction.

Ctrl+C at ANY time -> it flushes everything collected so far and exits cleanly.
It also auto-flushes every FLUSH_EVERY traces, so a disconnect never loses much.

Run in the x64 conda env (close the PicoScope GUI first):
  & C:\\Users\\t-mkarabulut\\Miniconda3x64\\envs\\cwhmac\\python.exe collect_data.py
"""
import os
import json
import random
import datetime

import numpy as np
from tqdm import tqdm

from cw310_program_test import program_cw310, run_one_g
from pico_scope import Scope
from tvlaCalc import TVLACalc

# =============================== SETTINGS =============================== #
N_TRACES    = 60000      # total traces to try to collect (Ctrl+C to stop early)
RAW_POOL    = 20000      # how many raw traces to keep in RAM for template/oracle
EXAMPLE_N   = 8          # example raw traces saved per class (for the trace plot)
TEST_FRAC   = 0.2        # fraction of the raw pool used as held-out oracle test
N_POI       = 40         # leaking samples used for the oracle projection
M0, M1      = 0, 1       # the two message classes
FLUSH_EVERY = 5000       # write CSVs to disk every this many traces (crash-safe)
SAVE_RAW_NPZ = True      # also dump the raw pool as float32 .npz (bigger file)
OUT_ROOT    = os.path.join(os.path.dirname(__file__), "PowerTrace_HQC_G")
# ====================================================================== #


def build_template(X, y, k):
    """LDA/matched-filter template on the top-k leaking samples (Welch |t|)."""
    x0, x1 = X[y == 0], X[y == 1]
    m0, m1 = x0.mean(0), x1.mean(0)
    v0, v1 = x0.var(0, ddof=1), x1.var(0, ddof=1)
    n0, n1 = len(x0), len(x1)
    t = (m0 - m1) / np.sqrt(v0 / n0 + v1 / n1 + 1e-24)
    pois = np.argsort(np.abs(t))[::-1][:k]
    vp = 0.5 * (v0 + v1) + 1e-24
    w = ((m0 - m1) / vp)[pois]
    midpoint = 0.5 * (m0[pois] + m1[pois])
    bias = float(w @ midpoint)
    return dict(pois=pois, w=w, bias=bias, t=t, m0=m0, m1=m1)


def save_all(outdir, tv, raw, labels, meta):
    """Write every CSV from whatever has been collected so far."""
    os.makedirs(outdir, exist_ok=True)
    ns = meta["n_samples"]
    samp = np.arange(ns)

    # --- TVLA curves (mean0/mean1/diff/t) ---
    t1 = tv.compute_first_order_tvla()
    t2 = tv.compute_second_order_tvla()
    m0, _, m1, _ = tv.get_mean_variance()
    diff = m0 - m1
    hdr = "sample,mean0,mean1,diff_of_means,t_first,t_second"
    np.savetxt(os.path.join(outdir, "tvla_curve.csv"),
               np.column_stack([samp, m0, m1, diff, t1, t2]),
               delimiter=",", header=hdr, comments="", fmt="%.8g")

    peak_t = float(np.nanmax(np.abs(t1))) if len(t1) else 0.0
    peak_i = int(np.nanargmax(np.abs(t1))) if len(t1) else -1

    acc = poi = None
    # --- oracle scores (needs a labelled raw pool with both classes) ---
    if raw is not None and len(raw) > 20 and len(set(labels[:len(raw)].tolist())) == 2:
        X = raw[:len(labels[:len(raw)])]
        yv = labels[:len(X)]
        ntest = max(2, int(len(X) * TEST_FRAC))
        Xtr, ytr = X[:-ntest], yv[:-ntest]
        Xte, yte = X[-ntest:], yv[-ntest:]
        if len(set(ytr.tolist())) == 2 and len(set(yte.tolist())) == 2:
            tpl = build_template(Xtr, ytr, min(N_POI, X.shape[1]))
            proj = Xte[:, tpl["pois"]] @ tpl["w"]
            pred = np.where(proj > tpl["bias"], 0, 1).astype(np.int8)
            acc = float((pred == yte).mean())
            poi = tpl["pois"]
            np.savetxt(os.path.join(outdir, "oracle_scores.csv"),
                       np.column_stack([proj, yte]),
                       delimiter=",", header="proj,label", comments="", fmt="%.8g")
            np.savetxt(os.path.join(outdir, "poi.csv"), np.sort(poi),
                       delimiter=",", header="poi_sample_index", comments="", fmt="%d")

    # --- example raw traces per class ---
    if raw is not None and len(raw) > 2:
        yv = labels[:len(raw)]
        ex0 = raw[np.where(yv == 0)[0][:EXAMPLE_N]]
        ex1 = raw[np.where(yv == 1)[0][:EXAMPLE_N]]
        cols = [samp]
        names = ["sample"]
        for i, r in enumerate(ex0):
            cols.append(r); names.append(f"m0_ex{i}")
        for i, r in enumerate(ex1):
            cols.append(r); names.append(f"m1_ex{i}")
        np.savetxt(os.path.join(outdir, "example_traces.csv"),
                   np.column_stack(cols), delimiter=",",
                   header=",".join(names), comments="", fmt="%.8g")

    # --- summary + metadata ---
    meta = dict(meta)
    meta.update(n_traces_collected=tv.traceNum,
                n_fixed=tv.fixed_stats.n, n_random=tv.random_stats.n,
                peak_abs_t=peak_t, peak_t_sample=peak_i,
                oracle_accuracy=acc, n_poi=None if poi is None else len(poi))
    with open(os.path.join(outdir, "metadata.json"), "w") as f:
        json.dump(meta, f, indent=2)
    with open(os.path.join(outdir, "summary.csv"), "w") as f:
        f.write("key,value\n")
        for k, v in meta.items():
            f.write(f"{k},{v}\n")

    if SAVE_RAW_NPZ and raw is not None and len(raw) > 2:
        np.savez_compressed(os.path.join(outdir, "raw_traces.npz"),
                            traces=raw.astype(np.float32),
                            labels=labels[:len(raw)].astype(np.int8))
    return peak_t, peak_i, acc


def main():
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    outdir = os.path.join(OUT_ROOT, f"collect_{stamp}")
    os.makedirs(outdir, exist_ok=True)
    print(f"Saving to {outdir}")

    target = program_cw310()
    scope = Scope()
    ns = scope.n_samples
    print(f"Scope ready: {ns} samples/trace. Collecting up to {N_TRACES} traces "
          f"(Ctrl+C to stop & save).")

    tv = TVLACalc(ns)
    raw = np.empty((RAW_POOL, ns), dtype=np.float32)
    labels = np.empty(RAW_POOL, dtype=np.int8)
    n_raw = 0
    meta = dict(created=stamp, n_samples=ns, target="HQC-G (SHAKE256)",
                sample_rate_hz=getattr(scope, "fs", None),
                settings=dict(N_TRACES=N_TRACES, RAW_POOL=RAW_POOL,
                              N_POI=N_POI, TEST_FRAC=TEST_FRAC, M0=M0, M1=M1))

    try:
        for i in tqdm(range(N_TRACES), desc="collect"):
            coin = random.randint(0, 1)
            scope.arm()
            run_one_g(target, M0 if coin == 0 else M1)
            trace, _ = scope.read()
            tv.addTrace(trace, coin)
            if n_raw < RAW_POOL:          # keep a raw pool for template/examples
                raw[n_raw] = trace
                labels[n_raw] = coin
                n_raw += 1
            if (i + 1) % FLUSH_EVERY == 0:
                save_all(outdir, tv, raw[:n_raw], labels, meta)
                tqdm.write(f"  flushed at {i+1} traces")
    except KeyboardInterrupt:
        print("\nCtrl+C -> flushing collected data ...")
    finally:
        pt, pi, acc = save_all(outdir, tv, raw[:n_raw], labels, meta)
        try:
            scope.close()
        except Exception:
            pass
        print(f"\nDONE. {tv.traceNum} traces. peak |t|={pt:.1f} @ sample {pi}"
              + (f", oracle acc={acc*100:.1f}%" if acc is not None else ""))
        print(f"CSVs saved in: {outdir}")
        print("Commit that folder to GitHub, then run plot_from_csv.py on it later.")


if __name__ == "__main__":
    main()
