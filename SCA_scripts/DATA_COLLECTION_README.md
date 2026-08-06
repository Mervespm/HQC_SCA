# HQC-G leakage data — capture now, plot later

Workflow for collecting side-channel data **while you have the CW310**, saving
small CSVs to GitHub, and plotting them **later on any machine** (no device).

## 1. Collect on the device (needs CW310 + PicoScope, conda env)

Close the PicoScope GUI, then:

```powershell
& C:\Users\t-mkarabulut\Miniconda3x64\envs\cwhmac\python.exe collect_data.py
```

- Captures labelled `m'=0` / `m'=1` power traces of the HQC-G (SHAKE256) core.
- Runs until `N_TRACES` (default 60000) or you press **Ctrl+C** — either way it
  flushes everything collected so far (also auto-flushes every 5000 traces).
- Writes a timestamped folder `PowerTrace_HQC_G/collect_<date>/` containing:

| file | contents | use |
|---|---|---|
| `tvla_curve.csv` | sample, mean0, mean1, diff_of_means, t_first, t_second | TVLA + diff-of-means plots |
| `oracle_scores.csv` | proj, label (held-out test set) | single-trace oracle histogram + accuracy |
| `poi.csv` | top leaking sample indices | mark POIs on plots |
| `example_traces.csv` | a few raw traces per class | example-trace plot |
| `summary.csv` / `metadata.json` | peak \|t\|, N, accuracy, sample rate, settings | run provenance |
| `raw_traces.npz` | up to `RAW_POOL` raw traces (float32) | full offline re-analysis (bigger) |

Tune the settings block at the top of `collect_data.py`
(`N_TRACES`, `RAW_POOL`, `N_POI`, `SAVE_RAW_NPZ`, ...).

## 2. Commit to GitHub

```powershell
git add PowerTrace_HQC_G/collect_<date>/
git commit -m "HQC-G leakage capture <date>"
git push
```

The CSVs are tiny and git-friendly. `raw_traces.npz` can be large — drop it or
use Git LFS if you only need the plots (the CSVs already contain everything the
plots need).

## 3. Plot later — anywhere, no device

Only needs `numpy` + `matplotlib`:

```powershell
python plot_from_csv.py                          # newest collect_* folder, automatically
python plot_from_csv.py PowerTrace_HQC_G/collect_<date>   # a specific folder
python plot_from_csv.py --all                    # every collect_* folder
```

Produces, next to the CSVs:
`tvla_first_order.png`, `tvla_second_order.png`, `diff_of_means.png`,
`example_traces.png`, `oracle_hist.png`.
