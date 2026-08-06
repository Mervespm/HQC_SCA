# HQC_SCA — Side-channel analysis of HQC's G function (SHAKE256) on CW310

Power/EM side-channel study of the **HQC** KEM (NIST PQC) on a ChipWhisperer
CW310 FPGA, mirroring the Ravi et al. (TCHES 2020) plaintext-checking-oracle
attack. The isolated **G function** `θ = SHAKE256(0x03 ‖ m′)` is the leakage
point that instantiates a plaintext-checking (PC) oracle, which is used to mount
a chosen-ciphertext key-recovery attack against HQC's secret `y`.

## Highlights / results
- **TVLA leakage** on the G/Keccak core: peak |t| ≈ 28 on a 2500-trace pool (≈72 on a larger 19k campaign) at 1.25 GS/s.
- **Single-trace PC oracle:** 98–100 % accuracy on held-out traces → the oracle is real.
- **Software attack simulation** (`SCA_scripts/hqc_attack_sim.py`) against a
  verified HQC-128 reference model: recovers individual coefficients of the
  secret `y` (10/10 correct, ~16 oracle calls each); the same primitive sweeps
  to the full key `x = s ⊕ h·y`.

## Repo layout
| path | what |
|---|---|
| `HQC_G_SCA_DESIGN_AND_ATTACK.md` | full design + attack write-up (RTL, register map, 4-phase attack) |
| `hdl/` | working G-function target RTL (AHB slave + G sequencer + trigger) |
| `SCA_scripts/hqc128_ref.py` | verified HQC-128 reference model (self-tested) |
| `SCA_scripts/hqc_attack_sim.py` | software PC-oracle key-recovery simulation |
| `SCA_scripts/collect_data.py` | on-device capture → plot-ready CSVs (Ctrl-C safe) |
| `SCA_scripts/plot_from_csv.py` | offline plotting from CSVs (numpy + matplotlib only) |
| `SCA_scripts/oracle_test.py` | on-device single-trace oracle (template attack) |
| `SCA_scripts/tvla_hqc.py`, `tvlaCalc.py` | TVLA capture + incremental engine |
| `SCA_scripts/pico_scope.py`, `cw310_program_test.py` | PicoScope + CW310 host drivers |
| `SCA_scripts/PowerTrace_HQC_G/` | captured leakage data (CSVs + plots) |
| `figures/` | paper-ready figures (fig2–fig7); see the figure↔CSV table below |
| `SCA_scripts/DATA_COLLECTION_README.md` | capture-now / plot-later workflow |

## Paper figures & their data (device-free)

Every figure below is **already plotted and committed**, and its **source CSV is in the
repo** — so with no device you can re-plot or re-analyse any of them. Figures live in
`figures/`; the full captions + walkthrough are in
`HQC_G_SCA_DESIGN_AND_ATTACK.md` §4.5.

| Fig | PNG (`figures/`) | **CSV you need** (under `SCA_scripts/PowerTrace_HQC_G/`) | What it shows | Regenerate |
|---|---|---|---|---|
| 2 | `fig2_tvla.png` | `learncurve_2026-08-06_10-16-15/fig_tvla.csv` | TVLA \|t\| vs time (peak ≈ 28) | `plot_paper_figs.py learncurve_2026-08-06_10-16-15` |
| 3 | `fig3_oracle_hist.png` | `learncurve_2026-08-06_10-16-15/fig_oracle_hist.csv` | single-trace oracle histogram (98.4 %) | same as Fig 2 |
| 4 | `fig4_learning_curve.png` | `learncurve_2026-08-06_10-18-46/learning_curve.csv` | accuracy vs #training traces (90 %@240, 99 %@1200) | `learning_curve.py --npz learncurve_2026-08-06_10-16-15` |
| 5 | `fig5_poi_curve.png` | `learncurve_2026-08-06_10-18-46/poi_curve.csv` | accuracy vs #POIs (sweet spot ~10–40) | same as Fig 4 |
| 6 | `fig6_mean_traces.png` | `learncurve_2026-08-06_10-16-15/fig_mean_traces.csv` | class-mean traces + Welch-\|t\| ("why it works") | `plot_paper_figs.py learncurve_2026-08-06_10-16-15` |
| 7 | `fig7_success_vs_trials.png` | `success_2026-08-06_10-32-20/success_vs_trials.csv` | attack success vs repetitions R | `success_vs_trials.py` *(pure software, no data)* |

**Figs 2, 3 and 6 share one identical time axis** — they are all produced from the
single pool below by `plot_paper_figs.py` (x-axis in µs, peak at 8.31 µs), so they line
up cleanly in the paper.

**The one file that reproduces everything (kept locally, not pushed):** the real
2500-trace labelled device pool `learncurve_2026-08-06_10-16-15/raw_pool.npz`. It is
**git-ignored to keep the repo light** — the committed per-figure CSVs above are enough
to re-draw every plot. Keep the `.npz` on disk if you want to *re-analyse* raw traces
(e.g. a noise sweep `learning_curve.py --npz learncurve_2026-08-06_10-16-15 --noise 3`).

> Run commands from `SCA_scripts/` with the conda python, e.g.
> `& C:\Users\t-mkarabulut\Miniconda3x64\envs\cwhmac\python.exe plot_from_csv.py <folder>`.

## Data collection & plotting
See `SCA_scripts/DATA_COLLECTION_README.md`. In short — collect on the device:

```powershell
& C:\Users\t-mkarabulut\Miniconda3x64\envs\cwhmac\python.exe SCA_scripts\collect_data.py
```

then plot later on any machine (no device needed):

```powershell
python SCA_scripts\plot_from_csv.py SCA_scripts\PowerTrace_HQC_G\collect_<date>
```

## Notes
- FPGA build trees and bitstreams (`syn/`, `sim_*/`, `hdl_tb/`, `*.bit`) and bulky
  raw blobs (`*.npz`, `*.pkl`) are **git-ignored** to keep the repo light; the
  plot-ready CSVs are committed. See `.gitignore`.
- Python libs are managed with Anaconda (env `cwhmac`, has `chipwhisperer` + `picosdk`).

## References
- P. Ravi, S. Sinha Roy, A. Chattopadhyay, S. Bhasin. *Generic Side-channel
  attacks on CCA-secure lattice-based PKE and KEMs.* IACR TCHES 2020(3):307–335.
- HQC specification (NIST PQC).
