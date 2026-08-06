| metric | value | unit | note |
|---|---|---|---|
| single_query_oracle_acc_baseline | 0.7400 | fraction | device CW310 HQC-G, m'=0 vs decode-failure, fillers anywhere |
| peak_tvla_t_baseline | 13.300 | abs_t | Welch |t|, baseline ciphertext |
| single_query_oracle_acc_fix7 | 0.7600 | fraction | device CW310 HQC-G, fix #7 systematic-region fillers |
| peak_tvla_t_fix7 | 16.776 | abs_t | Welch |t|, fix #7 ciphertext (stronger leak) |
| boundary_word_success_rate | 0.6000 | fraction | make_boundary_word() probeable-pivot rate (40% unprobeable) |
| model_oracle_acc_baseline_RS_T_any | 0.7250 | fraction | HW-model acc; d'=0.9249, class0 HW 8.580, class1 HW 18.760 |
| model_oracle_acc_RS_T_sys | 0.7900 | fraction | HW-model acc; d'=1.4033, class0 HW 14.830, class1 HW 51.990 |
| model_oracle_acc_RS_T_parity | 0.7150 | fraction | HW-model acc; d'=0.7948, class0 HW 1.700, class1 HW 3.400 |
| model_oracle_acc_max_sys_fillers | 0.7600 | fraction | HW-model acc; d'=1.2223, class0 HW 15.270, class1 HW 48.980 |
| class0_success_HW_mean_baseline | 8.1 | bits | success m' Hamming weight (128-bit) |
| class1_failure_HW_mean_baseline | 19.73 | bits | decode-failure m' Hamming weight (128-bit) |
| class0_success_HW_mean_fix7_sys | 20.55 | bits | success m' Hamming weight (128-bit) |
| class1_failure_HW_mean_fix7_sys | 54.45 | bits | decode-failure m' Hamming weight (128-bit) |
| R_for_99pct_key_hard_p0.74 | 51 | queries/bit | min R for >=99% full-key at oracle p=0.74, d'=1.28669 |
| R_for_99pct_key_soft_p0.74 | 31 | queries/bit | min R for >=99% full-key at oracle p=0.74, d'=1.28669 |
| R_for_99pct_key_hard_p0.76 | 41 | queries/bit | min R for >=99% full-key at oracle p=0.76, d'=1.41261 |
| R_for_99pct_key_soft_p0.76 | 31 | queries/bit | min R for >=99% full-key at oracle p=0.76, d'=1.41261 |
| per_bit_acc_after_voting_max | 1.0 | fraction | per-secret-bit accuracy after soft combining (approaches 1.0) |
