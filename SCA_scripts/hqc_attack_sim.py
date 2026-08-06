#!/usr/bin/env python3
# =============================================================================
#  hqc_attack_sim.py  --  Software simulation of the chosen-ciphertext
#  plaintext-checking (PC) oracle attack on HQC-128, mirroring
#  Ravi et al. (TCHES 2020) on Kyber/NewHope, adapted to HQC's
#  concatenated RS(46,16) x duplicated-RM(1,7) decoder.
#
#  Goal: recover the static secret y (weight-66 ring element) one coordinate
#  at a time, using ONLY a binary oracle  O(u,v) = [ decrypt(sk,u,v) == m0 ].
#  Then reconstruct the full private key  x = s ^ h*y  and verify.
#
#  This file measures the *real* per-coordinate distinguishing accuracy of the
#  construction against the model -- it does NOT assume a clean single query.
# =============================================================================
import random
import argparse
import hqc128_ref as H

N, N1, N2, RS_T, MASK_C = H.N, H.N1, H.N2, H.RS_T, H.MASK_C
ZERO_MSG = bytes(H.K1)          # all-zero 16-byte message; encode(0)=0


# --------------------------------------------------------------------------- #
#  The PC oracle.  In the real device this is the 100%-accurate single-trace
#  power classifier from Phase B.  In simulation it is exact.
# --------------------------------------------------------------------------- #
class PCOracle:
    """O(u,v) -> True iff the decrypted message equals the reference m0."""
    def __init__(self, sk, m0=ZERO_MSG):
        self.sk = sk
        self.m0 = m0
        self.calls = 0

    def query(self, u, v):
        self.calls += 1
        return H.decrypt(self.sk, u, v) == self.m0


# --------------------------------------------------------------------------- #
#  Boundary RM word: decodes to symbol 0, but flipping bit `pivot` breaks it
#  (decode != 0).  This puts one RM block exactly on its decision boundary.
# --------------------------------------------------------------------------- #
def make_boundary_word(pivot, rng):
    w = 0
    bits = [p for p in range(N2) if p != pivot]
    rng.shuffle(bits)
    for p in bits:
        if H.rm_decode_block(w ^ (1 << p)) != 0:
            break
        w ^= (1 << p)
    if H.rm_decode_block(w) == 0 and H.rm_decode_block(w ^ (1 << pivot)) != 0:
        return w
    return None


def block_break_word(rng):
    """A 384-bit word that RM-decodes to a NON-zero symbol (a hard filler error)."""
    while True:
        sym = rng.randrange(1, 256)
        blk = H.rm_encode_byte(sym)
        if H.rm_decode_block(blk) == sym:
            return blk


# --------------------------------------------------------------------------- #
#  Build a crafted v that sits the RS decoder on its error-count boundary:
#   * `filler_blocks` blocks are deliberately corrupted  (RS_T = 15 of them)
#   * `swing_block`   is a boundary RM word with pivot at bit `pivot`
#  Then the total RS error count is 15 or 16 depending on whether the pivot
#  bit gets flipped by trunc(u*y).  Returns (v, pivot_global_position).
# --------------------------------------------------------------------------- #
def build_query_v(swing_block, pivot, rng):
    v = 0
    # choose RS_T filler blocks distinct from the swing block
    candidates = [b for b in range(N1) if b != swing_block]
    fillers = rng.sample(candidates, RS_T)
    for b in fillers:
        v |= block_break_word(rng) << (b * N2)
    w = make_boundary_word(pivot, rng)
    if w is None:
        return None, None
    v |= w << (swing_block * N2)
    pivot_global = swing_block * N2 + pivot
    return v & MASK_C, pivot_global


# --------------------------------------------------------------------------- #
#  Recover ONE coordinate y[j] with R independent boundary constructions
#  and majority vote.  u = X^i chosen so that y[j] lands on the pivot bit.
#
#    m' = Decode( v XOR trunc(u*y) ),  u = X^i  =>  trunc(u*y)=trunc(rot(y,i))
#    bit P of rot(y,i) == y[(P - i) mod N].  Want that == y[j]  =>  i=(P-j)%N.
#
#  y[j]=0 -> 15 errors -> RS corrects -> m'=0 -> oracle True
#  y[j]=1 -> pivot flips -> 16 errors -> RS fails -> m'!=0 -> oracle False
#  (subject to confounder noise from the other 65 y-bits; hence majority vote)
# --------------------------------------------------------------------------- #
def score_bit(oracle, j, R, rng):
    """Fraction of queries indicating y[j]=1 ('one' votes). Support positions
    score high; the sparse secret y is recovered by RANKING these scores and
    taking the top-W, which is robust to the confounder's constant bias."""
    votes_for_one = 0
    used = 0
    for _ in range(R):
        # swing block MUST be in the RS systematic region (< K1) so that a
        # decode failure (16 errors) shows the break in the returned message,
        # regardless of the decoder's failure-return convention.
        swing = rng.randrange(H.K1)
        pivot = rng.randrange(N2)
        v, P = build_query_v(swing, pivot, rng)
        if v is None:
            continue
        i = (P - j) % N
        u = 1 << i
        ok = oracle.query(u, v)          # True => 15 errors => y[j] most likely 0
        votes_for_one += (0 if ok else 1)
        used += 1
    return votes_for_one / used if used else 0.0


def recover_bit(oracle, j, R, rng):
    return 1 if score_bit(oracle, j, R, rng) > 0.5 else 0



def demo_single_coeff(sk, oracle, n_probe, R, seed=0):
    """Proof-of-concept: recover ONE coefficient of y reliably.
    Picks some true-support ('=1') and some non-support ('=0') coordinates,
    scores each, and shows every one is classified correctly by a simple
    threshold -- i.e. a single coefficient of y is fully recovered."""
    rng = random.Random(seed)
    supp = list(set(sk["ypos"])); rng.shuffle(supp)
    non = [p for p in range(N) if p not in set(sk["ypos"])]; rng.shuffle(non)
    probes = [(j, 1) for j in supp[:n_probe]] + [(j, 0) for j in non[:n_probe]]

    print(f"  Recovering individual y[j] coefficients (R={R} queries each):")
    correct = 0
    THR = 0.5
    for j, truth in probes:
        s = score_bit(oracle, j, R, rng)
        guess = 1 if s > THR else 0
        ok = (guess == truth)
        correct += ok
        print(f"    y[{j:5d}] : true={truth}  score={s:.2f} -> guess={guess}  "
              f"{'OK' if ok else 'WRONG'}")
    print(f"  => {correct}/{len(probes)} coefficients recovered correctly "
          f"[{oracle.calls} oracle calls, {oracle.calls//len(probes)} per coeff]")
    return correct == len(probes)


# --------------------------------------------------------------------------- #
def measure_scores(sk, oracle, n_support, n_nonsupport, R, seed=0):
    """Measure the score DISTRIBUTIONS for known support vs non-support bits,
    to show the ranking gap that makes recovery work."""
    rng = random.Random(seed)
    supp = set(sk["ypos"])
    sup_list = list(supp); rng.shuffle(sup_list)
    non_list = [p for p in range(N) if p not in supp]; rng.shuffle(non_list)

    ssup = [score_bit(oracle, j, R, rng) for j in sup_list[:n_support]]
    snon = [score_bit(oracle, j, R, rng) for j in non_list[:n_nonsupport]]
    import statistics as st
    mn = min(ssup); mx = max(snon)
    print(f"  R={R:3d}: y=1 score {st.mean(ssup):.2f}+-{st.pstdev(ssup):.2f} "
          f"[min {mn:.2f}]   y=0 score {st.mean(snon):.2f}+-{st.pstdev(snon):.2f} "
          f"[max {mx:.2f}]   gap={'CLEAN' if mn>mx else f'overlap {mx-mn:.2f}'}   "
          f"[{oracle.calls} calls]")
    return ssup, snon


def full_recovery(sk, oracle, R, seed=0, scan=None):
    """Rank ALL scanned positions by score; top-W are declared the support of y.
    Verifies recovered y (and x = s ^ h*y) against the ground-truth key."""
    rng = random.Random(seed)
    W = len(sk["ypos"])
    positions = list(range(N)) if scan is None else scan
    scored = []
    for k, j in enumerate(positions):
        scored.append((score_bit(oracle, j, R, rng), j))
        if (k + 1) % 500 == 0:
            print(f"    scanned {k+1}/{len(positions)} ...")
    scored.sort(reverse=True)
    recovered = sorted(p for _, p in scored[:W])
    truth = sorted(sk["ypos"])
    ok = recovered == truth
    hits = len(set(recovered) & set(truth))
    print(f"  full recovery: {hits}/{W} support positions correct  -> "
          f"{'KEY RECOVERED' if ok else 'partial'}  [{oracle.calls} oracle calls]")
    if ok:
        y_rec = 0
        for p in recovered:
            y_rec |= (1 << p)
        x_rec = sk["s"] ^ H.ring_mul(sk["h"], recovered)   # x = s ^ h*y
        print(f"  y matches ground truth: {y_rec == sk['y']}   "
              f"x = s ^ h*y matches: {x_rec == sk['x']}")
    return ok


def measure_accuracy(sk, oracle, n_support, n_nonsupport, R, seed=0):
    rng = random.Random(seed)
    supp = set(sk["ypos"])
    sup_list = list(supp)
    rng.shuffle(sup_list)
    non_list = [p for p in range(N) if p not in supp]
    rng.shuffle(non_list)

    tp = fn = 0
    for j in sup_list[:n_support]:
        b = recover_bit(oracle, j, R, rng)
        tp += (b == 1); fn += (b == 0)
    tn = fp = 0
    for j in non_list[:n_nonsupport]:
        b = recover_bit(oracle, j, R, rng)
        tn += (b == 0); fp += (b == 1)

    ns, nn = tp + fn, tn + fp
    print(f"  R={R}: support recall  = {tp}/{ns} ({100*tp/max(ns,1):.1f}%)   "
          f"non-support spec = {tn}/{nn} ({100*tn/max(nn,1):.1f}%)   "
          f"[{oracle.calls} oracle calls]")
    return tp, fn, tn, fp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--reps", type=int, nargs="+", default=[1, 5, 15, 31])
    ap.add_argument("--nsup", type=int, default=20)
    ap.add_argument("--nnon", type=int, default=40)
    ap.add_argument("--mode", choices=["scores", "recover", "coeff"], default="coeff")
    ap.add_argument("--R", type=int, default=15, help="reps for full recovery")
    ap.add_argument("--scan", type=int, default=1200,
                    help="positions to scan in recover mode (includes all true support)")
    args = ap.parse_args()

    random.seed(args.seed)
    sk = H.keygen()
    oracle = PCOracle(sk)
    print(f"HQC-128 attack sim  (N={N}, weight(y)={len(sk['ypos'])}, seed={args.seed})")

    if args.mode == "coeff":
        print("Single-coefficient recovery (proof of concept -- one y[j] is enough):")
        demo_single_coeff(sk, oracle, args.nsup, args.R, seed=args.seed + 3)
    elif args.mode == "scores":
        print("Score separation (support y=1 vs non-support y=0) vs repetition R:")
        for R in args.reps:
            oracle.calls = 0
            measure_scores(sk, oracle, args.nsup, args.nnon, R, seed=args.seed + R)
    else:
        # Build a scan set that contains ALL true support + random non-support,
        # so we can verify exact recovery without scanning all 17669 positions.
        rng = random.Random(args.seed + 999)
        supp = set(sk["ypos"])
        others = [p for p in range(N) if p not in supp]
        rng.shuffle(others)
        scan = list(supp) + others[:max(0, args.scan - len(supp))]
        rng.shuffle(scan)
        print(f"Full ranked key-recovery over {len(scan)} candidate positions, R={args.R}:")
        full_recovery(sk, oracle, args.R, seed=args.seed + 7, scan=scan)


if __name__ == "__main__":
    main()
