# HQC_SCA — Side-channel analysis of HQC's G function (SHAKE256) on CW310

Power/EM side-channel study of the **HQC** KEM (NIST PQC) on a ChipWhisperer
CW310 FPGA, mirroring the Ravi et al. (TCHES 2020) plaintext-checking-oracle
attack. The isolated **G function** `θ = SHAKE256(0x03 ‖ m′)` is the leakage
point that instantiates a plaintext-checking (PC) oracle, which is used to mount
a chosen-ciphertext key-recovery attack against HQC's secret `y`.

## Highlights / results
- **TVLA leakage** on the G/Keccak core: peak |t| ≈ 69 at 1.25 GS/s.
- **Single-trace PC oracle:** 100 % accuracy on held-out traces → the oracle is real.
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
| `SCA_scripts/DATA_COLLECTION_README.md` | capture-now / plot-later workflow |

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
