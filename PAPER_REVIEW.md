# Review report: HQC-128 POWER plaintext-checking-oracle attack on CW310

**Reviewer stance:** the work is promising and has a credible novelty axis (HQC-RMRS, FPGA hardware, Keccak-`G` leakage), but the paper is **not submission-ready** until the corrected honest-oracle story fully replaces the older artificial-oracle narrative. A TCHES/CHES reviewer will focus less on whether 74--76% can be amplified (it can) and more on whether the paper cleanly proves that this noisy oracle is the one available in a real chosen-ciphertext decapsulation attack, that the query errors are independent across the proposed repetitions, and that the partial support recovered by the oracle is completed into a full verified HQC secret key.

I also ran the CPU-only completion smoke test:

```text
python hqc_attack_sim.py --mode complete --missing 2 --seed 1
=> FULL KEY RECOVERED & VERIFIED; structural tail n-n1*n2 = 5; cost ~2^3.3 HW-checks
```

---

## 0. Evidence anchors that should drive the paper

| Claim | Evidence | Reviewer interpretation |
|---|---|---|
| Artificial `m'=0` vs `m'=1` is not attack-realistic. | `HONEST_ORACLE_SCENARIO.md:12-33`; `ORACLE_DATASETS.md:8-23`; artificial dataset: `results_datasets\artificial_m0_vs_m1\summary.csv:6,8-12` gives peak `|t|=25.382`, test accuracy `1.0`, no FP/FN. | Keep as a negative-control/anti-result only. Do **not** use it for attack cost. |
| Honest baseline oracle is about 74%. | `paper_results\paper_key_results.csv:2`; `paper_results\fix7_device.csv:2` gives baseline test `0.7440`; honest side-by-side dataset gives `0.724` in `results_datasets\honest_0_vs_failure\summary.csv:6,8-12`. | Headline should be **74--76% single-query**, not 98--100%. |
| Highest device-measured honest oracle is 76.0%. | `paper_results\paper_key_results.csv:4`; `paper_results\fix7_device.csv:3` gives `sys` test `0.7600`. | Correct headline: **76.0% device-measured**, with confidence intervals. |
| 78% is model-only. | `paper_results\paper_key_results.csv:8,10`; `paper_results\fix7_construction.csv:3,5` gives model `0.7583` vs `0.7750`. | Do not headline 78%; treat as offline construction sweep/sampling noise. |
| Same-ciphertext averaging is a dead end. | `HONEST_ORACLE_SCENARIO.md:56-68`, `160-178`; `plan.md:113,172`. | Remove all text suggesting per-query/same-ciphertext averaging improves accuracy. |
| Amplification is by independent ciphertexts and soft/hard combining. | `HONEST_ORACLE_SCENARIO.md:189-204`; `paper_results\soft_vs_hard.csv:6,8,15-16`; `paper_results\paper_key_results.csv:16-19`. | This is the valid path to full-key success. |
| Three different accuracies exist. | `plan.md:119-123`; `HONEST_ORACLE_SCENARIO.md:307-311`. | Paper must repeatedly distinguish single-query, per-bit-after-vote, and full-key success. |
| Linear-algebra tail completion works for missing 0..5. | `HONEST_ORACLE_SCENARIO.md:315-361`; `paper_results\linalg_completion.csv:2-7`; `paper_results\paper_key_results.csv:21-27`; code in `hqc_attack_sim.py:261-299`. | The completion step is credible, but the paper must state its assumptions and verification condition. |

---

## 1. Soundness of the oracle and accuracy claims

### 1.1 The corrected story is scientifically sound

The honest-oracle correction is the right one. The real chosen-ciphertext attack observes `m'=0` after decode success versus decode-failure garbage after crossing the RS correction boundary; it does not get to choose `m'=1` as the alternative class (`HONEST_ORACLE_SCENARIO.md:12-33`, `ORACLE_DATASETS.md:19-23`). This maps cleanly to Ravi-style plaintext-checking/decoding-failure oracles.

The physical ceiling explanation is also plausible: the failure class includes a confounder from the other secret bits, and a nontrivial fraction of failures produces very low-Hamming-weight `m'`, making those traces look like success (`HONEST_ORACLE_SCENARIO.md:32-55`). This is exactly the kind of non-Gaussian class-overlap limitation that a hardware power reviewer will accept **if** the histograms and confusion matrices are shown honestly.

### 1.2 The paper currently still has dangerous conflations

The corrected files are clear in places, but the repository still contains text that would be fatal if it appears in the submitted paper:

1. **Current main write-up still claims a perfect oracle.** `HQC_G_SCA_DESIGN_AND_ATTACK.md:189-217` states “DONE (100% @ 1.25 GS/s)”, “single-trace accuracy 100.00%”, and “perfect plaintext-checking oracle.” This is the artificial `m'=0` vs `m'=1` result and must be deleted or moved to a “negative control / not attack-injectable” subsection.
2. **Current figures/captions still describe the old oracle.** `HQC_G_SCA_DESIGN_AND_ATTACK.md:367-411` claims 98.4% single-trace accuracy, >=99% at 1200 profiling traces, and full-key >=99% at `R≈5..13`. These values must be replaced by the honest 74--76% single-query and `R≈31/51` soft/hard story.
3. **The README repeats the old headline.** `README.md:9-13` says the PC oracle is 98--100% and the simulation recovers with ~16 calls. If reviewers see this, they will suspect the correction is cosmetic. Update or remove it before submission.
4. **`HONEST_ORACLE_SCENARIO.md` has an internal contradiction.** It correctly says same-ciphertext averaging is flat (`HONEST_ORACLE_SCENARIO.md:56-68`, `160-178`) and that independent ciphertexts are the amplifier (`189-204`), but later still lists “single-query accuracy vs K (73→97.5%)” and cost rows for “averaged K=8/K=16” (`HONEST_ORACLE_SCENARIO.md:236-245`). Those rows resurrect the discarded artifact and must be removed or relabeled as obsolete.
5. **Avoid “~100% key recovery” wording without qualification.** Prefer “full-key success ≈99% at R=31 soft / R=51 hard under the independent-error model calibrated at p=0.74” and cite `soft_vs_hard.csv:6,8`. This prevents readers from confusing single-query oracle accuracy with full-key Monte Carlo success.

### 1.3 Recommended wording for the three accuracy numbers

Use this exact style throughout:

- **Single-query device oracle:** 74.4% baseline, 76.0% fix #7 (`paper_key_results.csv:2,4`; `fix7_device.csv:2-3`).
- **Per-bit after independent-query combining:** at p=0.74, soft `R=31` gives `0.999848` per-bit; hard `R=51` gives `0.999902` (`soft_vs_hard.csv:6,8`). At p=0.76, soft `R=31` gives `0.999951`, hard `R=41` gives `0.999845` (`soft_vs_hard.csv:15-16`).
- **Full-key success:** at p=0.74, soft `R=31` gives `0.990000`, hard `R=51` gives `1.000000` in the 4000-key Monte Carlo table (`soft_vs_hard.csv:6,8`); at p=0.76, soft `R=31` gives `0.996750`, hard `R=41` gives `0.999750` (`soft_vs_hard.csv:15-16`).

Also add binomial/Monte-Carlo confidence intervals. A 1.6-point difference between 74.4% and 76.0% on 1000 traces is directionally useful but not, by itself, a strong statistical separation; call 76.0% “highest measured” rather than “proven ceiling” unless repeated A/B captures support it.

---

## 2. Novelty and positioning versus prior work

### 2.1 What is genuinely new

The strongest defensible novelty claim is:

> First demonstrated **FPGA/hardware power** plaintext-checking-oracle attack path for **current HQC-RMRS-128** that targets the decapsulation **Keccak `G = SHAKE256(0x03 || m')`** computation, rather than a software decoder implementation.

This is meaningfully distinct from prior HQC SCA that targets software decoders on Cortex-M4, and from Ravi-style generic PC-oracle work on LWE/LWR KEMs. Keep the novelty narrow and precise: not “first HQC SCA”, not “first PC oracle”, not “simpler than all decoder attacks”, but “first hardware/FPGA HQC-RMRS Keccak-`G` leakage instantiation with full-key completion.”

### 2.2 Prior work that must be cited and contrasted

The citation set should include at least:

- Ravi, Sinha Roy, Chattopadhyay, Bhasin, **TCHES 2020**, generic side-channel attacks on CCA-secure PKE/KEMs. Use as the methodology origin.
- Schamberger et al., **CARDIS 2020 / ePrint 2020/910**, HQC software power attack on the BCH decoder. Contrast old HQC/BCH + software decoder vs current HQC-RMRS + hardware Keccak `G`.
- Schamberger et al., **PQCrypto 2022 / ePrint 2022/724**, RS/RMRS decoder attack and linear-algebra/ISD completion. Cite specifically for the completion method reused here.
- Goy et al., **PQCrypto 2022** EM attack on RM/FHT with <20k traces. If the draft keeps the current “Goy TCHES 2024 SASCA” wording (`HQC_G_SCA_DESIGN_AND_ATTACK.md:414-419`), resolve the venue/year/name discrepancy and cite the intended paper(s) accurately.
- Ueno et al., **“Curse of Re-Encryption”, TCHES 2022**, because it is especially relevant to `G`/SHAKE plaintext-checking leakage through re-encryption logic.
- Dong & Guo, **OT-PCA, TCHES 2025 / ePrint 2024/1715**, for robust low-accuracy/soft-oracle framing and query reduction.
- Guo et al., **SCA-LDPC, TCHES 2023 / ePrint 2023/294**, for belief-propagation decoding from noisy side-channel observations.
- Tanaka et al., **TCHES 2023**, multi-valued PC oracle, because it directly motivates improving beyond binary success/failure.
- Ngo et al., **TCHES 2021**, deep learning on masked Saber, as broader modern DL oracle context.
- Ji, Wang & Dubrova, **ASHES 2023**, if retained from `HONEST_ORACLE_SCENARIO.md:78-88`, because it supports 70--80% single-trace oracle amplification on a masked hardware target.

### 2.3 Framing to avoid

- Do not say the attack is categorically “simpler” than Goy/SASCA. Say it is a **different binary-oracle leakage path** requiring chosen ciphertexts and repetitions, whereas decoder attacks may be single-trace or lower-query but target different circuitry. `HONEST_ORACLE_SCENARIO.md:254-260` already recommends this correction.
- Do not imply decoder prior work is superseded. In fact, decoder attacks may avoid the `HW≈0` confounder; this should appear as a limitation and future-work opportunity.
- Do not overstate “hardware” if only the isolated `G` block is on FPGA. The paper must explicitly separate “device-measured leakage on isolated G” from “full decapsulation integration.”

---

## 3. Key-recovery completeness

### 3.1 Linear-algebra completion is credible but conditional

The completion method is correctly described in the corrected narrative: given a correct partial support `P`, search remaining support candidates and accept the set for which `x_hat = s XOR h*y_hat` has `HW(x_hat)=w` (`HONEST_ORACLE_SCENARIO.md:315-336`; `hqc_attack_sim.py:261-299`). The sweep `missing=0..5` verifies 30/30 keys in each case with costs up to `2^3.32` HW checks (`linalg_completion.csv:2-7`). This is strong evidence for the **tail-completion subroutine**.

The review-critical caveat is that this proves completion **assuming**:

1. the partial support `P` is correct (no false positives in the accepted support), and
2. the candidate pool contains all missing true support positions.

Those assumptions are stated in the code docstring (`hqc_attack_sim.py:261-264`) but must be explicit in the paper. The paper should then show how the measured oracle produces such a `P` with high probability.

### 3.2 What is missing for a full-key-break claim

Add an end-to-end table that connects the device-measured oracle to the completion step:

- For p=0.744 and p=0.760, simulate/rank all probeable coordinates for many random keys using the exact query construction, independent ciphertexts, boundary-word failures, and soft scores.
- Report distribution of: true support hits among top candidates; false positives; missing support count; candidate pool size needed for 99%/99.9% completion; final verified key success.
- Include the structural 5-coordinate tail separately from noise-induced misses. The current `linalg_completion.csv` covers the structural tail, but not large candidate pools caused by misranking under a 74--76% oracle.
- If false positives remain in `P`, explain whether completion searches substitutions or only additions. The current `linalg_complete` only completes a correct subset; it does not repair wrong positions already included in `P`.

The claim “partial 60/66 oracle result becomes a full verified key break” is acceptable **only** if the paper proves that the 60 known positions are true positives and the remaining 6 are in a bounded candidate list. Otherwise, phrase as “linear-algebra completion closes the structural tail once a correct partial support is obtained; weaker/noisier support recovery falls back to side-channel-informed ISD.”

### 3.3 Verification condition

Do not stop at `HW(x_hat)=w` in prose. State that the recovered `(x,y)` is verified against the public relation and/or by re-running HQC public-key consistency/decapsulation checks. The code checks ground truth in simulation (`hqc_attack_sim.py:211-231`, `303-335`), but in an attack paper the attacker does not know ground truth. Use the public key relation and KEM validation as the attacker-visible verification.

---

## 4. Strongest likely TCHES reviewer objections and how to preempt them

1. **“You attacked an isolated G block, not full HQC decapsulation.”**  
   Preempt with a block diagram of full decapsulation showing where `m'` enters `G`, exact cycle/trigger equivalence, and why the same Keccak core/leakage appears in full RTL. Ideally add a full-decap or post-place simulation trace; if not, state the limitation plainly.

2. **“Why not attack the decoder instead?”**  
   Answer: prior HQC attacks do, but they are software decoder attacks; this work isolates a new hardware Keccak/FO-transform leakage path. Also admit decoder targeting may remove the HW≈0 confounder and list it as a high-value extension.

3. **“Is 76% enough?”**  
   Yes under independent repetitions: cite `soft_vs_hard.csv:15-16` (p=0.76, soft R=31 gives 99.675% full-key; hard R=41 gives 99.975%). Include confidence intervals and analytic binomial curves matching Monte Carlo.

4. **“Are errors actually independent across independent ciphertexts?”**  
   This is the most important technical risk. Same-ciphertext averaging is flat, which supports the physical-overlap story, but independent-query voting assumes the confounder is re-randomized enough. Add empirical error-correlation measurements across independently generated `(u,v)` for the same key/coordinate and across coordinates.

5. **“Single key or many keys?”**  
   G leakage itself is key-independent, but the honest failure-message distribution is key/query dependent. Add multi-key offline distributions and, if feasible, at least several measured message pools/captures across independent generated keys or query sets.

6. **“Fix #7 only improves 1.6 percentage points; is that real?”**  
   Report Wilson/binomial CIs and repeat A/B measurements. Until then, call it “highest measured” and “directionally consistent with the HW model,” not a statistically proven improvement.

7. **“The 78% model value is cherry-picked.”**  
   Defuse by explicitly labeling it offline-only and noting `RS_T_sys` and `max_sys_fillers` are the same construction up to sampling noise (`fix7_construction.csv:3,5`; `paper_key_results.csv:8,10`).

8. **“Does the FO transform still compute G on invalid ciphertexts?”**  
   Include the decapsulation pseudocode/implementation line showing `theta = G(m')` is computed before the validity decision/key selection. This is central to PC-oracle validity.

9. **“Template profiling leaks labels unavailable to the attacker.”**  
   State the profiling model: open-device profiling or same-device calibration with chosen messages for isolated G; separate profiling traces from attack traces; no train/test overlap. Provide exact split and POI selection method.

10. **“Countermeasures?”**  
   Discuss masked/hiding Keccak, shuffling, dual-rail/precharge, blinding/re-randomizing `m'`, decoder failure handling that avoids low-HW success/failure distinction, and rate limiting/rejection of repeated malformed decaps. Do not claim resistance is bypassed unless tested.

---

## 5. Concrete improvement recommendations, ranked

| Rank | Recommendation | Expected benefit | Effort | Needed for acceptance? |
|---|---|---:|---:|---|
| 1 | **Purge all artificial-oracle/perfect-oracle claims** from the paper, README, captions, and cost tables; replace with 74--76% / R=31--51 / full-key ≈99%. | Prevents fatal soundness rejection. | Low | **Yes** |
| 2 | **Add statistical confidence intervals and repeat A/B device captures** for baseline vs fix #7. | Makes 76.0% defensible and avoids overclaiming small deltas. | Low--Medium | **Yes** |
| 3 | **Validate independent-query error independence** on device or with measured message pools: per-coordinate error correlation, per-key variation, and calibration stability. | Supports the whole amplification argument. | Medium | **Yes** |
| 4 | **Add an end-to-end recovery table** from p=0.744/0.760 oracle -> ranked support -> linalg completion -> public-key verified secret. | Converts “components work” into “full break works.” | Medium | **Yes** |
| 5 | **Clarify isolated-G vs full-decap threat model** with implementation evidence that full decap computes the same `G(m')` under attacker-chosen ciphertexts. | Preempts hardware-realism objection. | Medium | **Yes**, unless the title/claims are narrowed. |
| 6 | **Fix novelty/literature section**: Schamberger CARDIS’20 and PQCrypto’22, Goy PQCrypto’22, Ravi TCHES’20, Ueno TCHES’22, Guo SCA-LDPC, Dong&Guo OT-PCA, Tanaka MV-PC, Ngo DL, Ji-Dubrova if used. | Positions contribution accurately. | Low | **Yes** |
| 7 | **Use soft LLR as the primary attack**, not a side note. Show score calibration, not just hard labels. | ~40% query reduction at p=0.74 (`R=31` vs `51`). | Medium | Strongly recommended |
| 8 | **Retarget RS/RM decoder leakage** to kill the HW≈0 `G` confounder. | Potentially much higher single-query accuracy and lower query count; aligns with prior HQC decoder attacks. | High | Nice-to-have; not required if G novelty is clear. |
| 9 | **Explore SCA-LDPC/BP completion using soft reliabilities** rather than top-W only. | More robust to weaker oracles/misranked support; ties to Guo TCHES’23. | Medium--High | Nice-to-have, useful for rebuttal. |
| 10 | **Try MV-PC / neural oracle / OT-PCA templates** on the existing traces. | Could extract multi-valued or more robust information from the same Keccak leakage; literature-aligned. | Medium | Nice-to-have. |
| 11 | **Consider targeting `K`/key-derivation path** in addition to `G`. | May produce a cleaner PC signal or independent confirmation. | Medium--High | Nice-to-have. |
| 12 | **Countermeasure experiments or at least analysis.** | Improves CHES/TCHES completeness. | Medium | Nice-to-have unless claims mention protected hardware. |

---

## 6. Prioritized submission punch-list

### Must fix before submission

1. Replace `HQC_G_SCA_DESIGN_AND_ATTACK.md:189-217` and `367-411` with the honest-oracle results.
2. Update `README.md:9-13` and the figure-source table so it no longer advertises 98--100% as the attack oracle.
3. Remove the obsolete averaging rows in `HONEST_ORACLE_SCENARIO.md:236-245`; keep only independent-ciphertext majority/soft combining.
4. Add a table titled “Do not conflate these accuracies” with the three numbers and citations to `paper_key_results.csv:2,4,16-19,21-27`.
5. Add confidence intervals for `fix7_device.csv:2-4` and repeat/cite at least one more device A/B run if possible.
6. Add an end-to-end measured-oracle recovery experiment/table, or narrow the claim to “component-verified full recovery under the calibrated independent-error model.”
7. State the assumptions of `linalg_complete`: correct partial support and candidate pool contains missing support. Add how false positives are handled.
8. Add the missing prior-work citations and remove “simpler” superiority language.
9. Add a threat-model paragraph: chosen-ciphertext access, profiling access, isolated G vs full decap, query budget, and no countermeasures.
10. Add a short artifact-reproducibility table: exact CSVs, scripts, seeds, Python env, and which values are device-measured vs model-only.

### Should fix for a stronger paper

1. Add multi-key/message-pool variability plots for honest oracle accuracy and failure-message HW distribution.
2. Add empirical independence/correlation plots for independent ciphertext repetitions.
3. Show Wilson CIs/confusion matrices for artificial and honest datasets side by side.
4. Include soft-score histograms and calibration curves, not only hard accuracies.
5. Include an ISD fallback complexity table for larger missing/candidate pools, tied to Schamberger Sec. 3.4.

### Nice-to-have extensions

1. Decoder leakage comparison (RS/RM/FHT) as a “why G is harder but novel” appendix.
2. OT-PCA or MV-PC reanalysis of existing traces.
3. Preliminary masked/hiding Keccak countermeasure discussion or experiment.
4. Full-decap FPGA integration measurement if schedule allows.

---

## Bottom-line recommendation

**Major revision before submission.** The corrected 74--76% honest oracle plus independent-query soft combining and linear-algebra completion can support a credible full-key attack paper, and the hardware/Keccak-G HQC-RMRS angle is publishable if positioned carefully. The main risk is not the low single-query accuracy; it is accidental reuse of obsolete 98--100% artificial-oracle text and an insufficient bridge from noisy per-query leakage to verified full-key recovery. Fix those, add statistics/independence evidence, and the work becomes much more defensible for TCHES/CHES.
