#!/usr/bin/env python3
"""Fix #7 DEVICE A/B: capture the same-size profiling set for the BASELINE pool
(fillers anywhere) and the SYS pool (fillers in the RS systematic region), under
IDENTICAL scope settings, on the real CW310 HQC-G core. Report peak |t| and
single-query oracle train/test accuracy for each -> did ciphertext design raise
the physical ceiling?

Outputs (paper_results/fix7_device.csv): pool,n,peak_t,train_acc,test_acc
"""
import os
import json
import random
import numpy as np

from cw310_program_test import program_cw310, run_one_g
from pico_scope import Scope
from collect_data import build_template

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper_results")
N_PER_CLASS = 1000     # per class per pool
N_POI = 40


def load_pool(path):
    d = np.load(path)
    c0 = [int(h, 16) for h in d["class0"]]
    c1 = [int(h, 16) for h in d["class1"]]
    return c0, c1


def capture_pool(target, scope, c0, c1, n_per, rng):
    msgs = [(m, 0) for m in rng.sample(c0, min(n_per, len(c0)))] + \
           [(m, 1) for m in rng.sample(c1, min(n_per, len(c1)))]
    rng.shuffle(msgs)
    X, y = [], []
    for i, (m, lab) in enumerate(msgs):
        scope.arm()
        run_one_g(target, m)
        tr, _ = scope.read()
        X.append(np.asarray(tr, np.float32))
        y.append(lab)
        if (i + 1) % 500 == 0:
            print(f"    {i+1}/{len(msgs)}")
    return np.asarray(X, np.float32), np.asarray(y, np.int8)


def eval_pool(X, y, k, rng):
    n = len(X)
    idx = np.arange(n); rng.shuffle(idx)
    cut = int(0.75 * n)
    tr, te = idx[:cut], idx[cut:]
    tpl = build_template(X[tr], y[tr], k)
    peak_t = float(np.abs(tpl["t"]).max())

    def acc(sel):
        proj = X[sel][:, tpl["pois"]] @ tpl["w"] - tpl["bias"]
        pred = (proj < 0).astype(int)
        return float((pred == y[sel]).mean())
    return peak_t, acc(tr), acc(te)


def main():
    os.makedirs(OUT, exist_ok=True)
    rng = random.Random(1)
    here = os.path.dirname(os.path.abspath(__file__))
    pools = [
        ("baseline", os.path.join(here, "oracle_msgs.npz")),
        ("sys",      os.path.join(here, "oracle_msgs_sys.npz")),
        ("sys_maxhw", os.path.join(here, "oracle_msgs_maxhw.npz")),
    ]
    target = program_cw310()
    scope = Scope()
    print(f"scope: {scope.n_samples} samples/trace\n")

    rows = []
    for name, path in pools:
        if not os.path.exists(path):
            print(f"  SKIP {name}: {path} missing"); continue
        c0, c1 = load_pool(path)
        print(f"[{name}] capturing {2*N_PER_CLASS} traces ...")
        X, y = capture_pool(target, scope, c0, c1, N_PER_CLASS, rng)
        peak_t, tr, te = eval_pool(X, y, N_POI, rng)
        print(f"[{name}] peak |t|={peak_t:.1f}  train acc={tr*100:.1f}%  "
              f"test acc={te*100:.1f}%\n")
        rows.append(dict(pool=name, n=len(X), peak_t=peak_t,
                         train_acc=tr, test_acc=te))
    scope.close()

    csv = os.path.join(OUT, "fix7_device.csv")
    with open(csv, "w") as f:
        f.write("pool,n_traces,peak_t,train_acc,test_acc\n")
        for r in rows:
            f.write(f"{r['pool']},{r['n']},{r['peak_t']:.3f},"
                    f"{r['train_acc']:.4f},{r['test_acc']:.4f}\n")
    print(f"saved {csv}")
    if len(rows) >= 2:
        base = rows[0]["test_acc"]
        for r in rows[1:]:
            print(f"\nFIX #7 DEVICE: {r['pool']} test acc {r['test_acc']*100:.1f}% "
                  f"vs baseline {base*100:.1f}% ({(r['test_acc']-base)*100:+.1f} pts, "
                  f"peak|t| {r['peak_t']:.1f})")


if __name__ == "__main__":
    main()
