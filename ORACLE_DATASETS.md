# HQC-G single-trace oracle — two datasets, side by side

*Generated 2026-08-06 15:21 on the CW310 HQC-G core, identical scope settings for both.*

Two message-class pairs are profiled with the **same** template attack. The only
difference is **which two classes** the device is asked to separate.

| | **A — artificial** `m'=0` vs `m'=1` | **B — honest** `m'=0` vs decode-FAILURE |
|---|---|---|
| what it is | a clean hand-picked 1-bit contrast | the pair the **real key-recovery attack** queries |
| attacker can inject it? | **no** | **yes** (chosen ciphertext → decode succeeds/fails) |
| traces | 2000 | 2000 |
| samples/trace | 95250 | 95250 |
| peak \|t\| | **25.382** | **20.731** |
| single-trace oracle (test) | **100.0%** | **72.4%** |
| verdict | **over-states** the oracle — do NOT report | **honest** paper number |

**Why B is the correct one.** During a chosen-ciphertext attack on HQC the leaking
secret bit `y[j]` shows up *only* as a decode **success** (`m'=0`, 15 corrected
errors) vs **failure** (garbage `m'`, 16 errors). The oracle question is literally
"did the inner decode succeed or fail?" — the Ravi et al. (TCHES 2020)
plaintext-checking-oracle model. The artificial `m'=0/1` pair is a value the
attacker never gets to inject, so its ~100% accuracy is not
achievable in a real attack.

Dataset B above was captured with the **baseline** ciphertext pool (fillers
anywhere) and scores **72.4%**. The best device-measured honest oracle uses the
**fix #7 systematic-region construction** and reaches **76.0%** (`paper_results/fix7_device.csv`:
baseline 74.4% → fix #7 76.0%). **76.0% is the honest, device-confirmed ceiling
we report** — the 78% that appears in `fix7_construction.csv` is an *offline
Hamming-weight model* estimate only (and its `max_sys_fillers` vs `RS_T_sys`
gap is sampling noise, since both are the same `n_filler=15, region=sys`
construction), so we do not headline it. The honest 72–76% is amplified to ≥99%
full-key by majority-vote / soft-LLR combining over independent queries (see
`paper_results/soft_vs_hard.csv`).

---

## Dataset A — artificial `m'=0` vs `m'=1`  (folder `results_datasets/artificial_m0_vs_m1/`)

peak |t| = 25.382, single-trace test accuracy = **100.0%**
(train 100.0%, K=20 POIs).
Confusion (test): TP=255 TN=245 FP=0 FN=0.

![A TVLA](results_datasets/artificial_m0_vs_m1/fig_tvla.png)
![A means](results_datasets/artificial_m0_vs_m1/fig_means.png)
![A diff](results_datasets/artificial_m0_vs_m1/fig_diff.png)
![A oracle](results_datasets/artificial_m0_vs_m1/fig_oracle_hist.png)
![A confusion](results_datasets/artificial_m0_vs_m1/fig_confusion.png)

CSVs: `class_means.csv`, `diff_of_means.csv`, `tvla_curve.csv`,
`oracle_scores.csv`, `summary.csv` (+ `raw_traces.npz`).

---

## Dataset B — honest `m'=0` vs decode-FAILURE  (folder `results_datasets/honest_0_vs_failure/`)

peak |t| = 20.731, single-trace test accuracy = **72.4%**
(train 74.2%, K=10 POIs).
Confusion (test): TP=197 TN=165 FP=76 FN=62.
The overlap in the projection histogram is the physical HW≈0 confounder floor.

![B TVLA](results_datasets/honest_0_vs_failure/fig_tvla.png)
![B means](results_datasets/honest_0_vs_failure/fig_means.png)
![B diff](results_datasets/honest_0_vs_failure/fig_diff.png)
![B oracle](results_datasets/honest_0_vs_failure/fig_oracle_hist.png)
![B confusion](results_datasets/honest_0_vs_failure/fig_confusion.png)

CSVs: same set as A (+ `raw_traces.npz`).

---

## Reproduce
```
python gen_oracle_msgs.py --n 1000 --seed 1              # honest pool (once)
python two_oracle_datasets.py --n 1000                   # captures A and B
```
