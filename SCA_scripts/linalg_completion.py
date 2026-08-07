#!/usr/bin/env python3
# =============================================================================
#  linalg_completion.py -- paper evidence for the linear-algebra tail-recovery
#  step (Schamberger et al., TCHES 2020, Sec. 3.3-3.4) applied to our HQC-RMRS
#  hardware attack. Shows that a PARTIAL oracle support (t < w) is completed to
#  a FULL, verified key break without any extra oracle queries.
#
#  For each (seed, missing) we:
#    - draw a fresh HQC-128 key,
#    - keep w-missing true support positions (emulating the confidently probed
#      part), drop `missing` of them into an un-probeable candidate pool,
#    - finish by the HW(x)==w linear-algebra test,
#    - verify y and x = s ^ h*y against ground truth.
#
#  Output: paper_results/linalg_completion.csv
# =============================================================================
import os
import csv
import random
from math import comb, log2
import hqc128_ref as H
from hqc_attack_sim import linalg_complete, x_from_support

N, N1, N2 = H.N, H.N1, H.N2
N_TAIL = N - N1 * N2          # structural un-probeable tail (=5 for RMRS-128)
OUT = os.path.join("paper_results", "linalg_completion.csv")


def run(seeds=range(30), missings=(0, 1, 2, 3, 4, 5), decoys=6):
    os.makedirs("paper_results", exist_ok=True)
    rows = []
    for missing in missings:
        succ = 0
        trials_used = []
        for seed in seeds:
            random.seed(seed)
            sk = H.keygen()
            W = len(sk["ypos"])
            truth = sorted(sk["ypos"])
            rng = random.Random(seed + 777)
            rng.shuffle(truth)
            P = sorted(truth[missing:])
            true_missing = truth[:missing]
            non = [p for p in range(N) if p not in set(sk["ypos"])]
            pool = list(true_missing) + rng.sample(non, decoys)
            rng.shuffle(pool)
            full = linalg_complete(sk, P, pool, w=W, verbose=False)
            ok = False
            if full is not None:
                y_rec = 0
                for p in full:
                    y_rec |= (1 << p)
                x_rec = x_from_support(sk["s"], sk["h"], full)
                ok = (full == sorted(sk["ypos"])) and (y_rec == sk["y"]) \
                    and (x_rec == sk["x"])
            succ += ok
        n = len(list(seeds))
        # exhaustive completion cost over the STRUCTURAL tail (worst case)
        space = comb(max(N_TAIL, missing), missing) if missing > 0 else 1
        cost = log2(space) if space > 1 else 0.0
        rows.append(dict(missing=missing, trials=n, full_key_verified=succ,
                         success_rate=round(100 * succ / n, 1),
                         tail_size=N_TAIL,
                         completion_log2_hwchecks=round(cost, 2)))
        print(f"missing={missing}: {succ}/{n} full keys verified "
              f"({100*succ/n:.1f}%)  tail={N_TAIL}  cost=2^{cost:.1f}")
    with open(OUT, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        wr.writeheader()
        wr.writerows(rows)
    print(f"\nsaved {os.path.abspath(OUT)}")


if __name__ == "__main__":
    run()
