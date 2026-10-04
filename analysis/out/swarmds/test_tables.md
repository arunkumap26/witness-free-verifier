### TEST split (result)

**Soundness on this split's honest rows** (FP = honest row called contradicted)

| method | unit | honest n | FP | honest supported | honest abstained | TP | precision |
|---|---|---:|---:|---:|---:|---:|---:|
| T0 | tool_output | 9757 | 0 | 9757 | 0 | 780 | 1.0 |
| T0 | claim | 243 | 0 | 0 | 243 | 0 | None |
| T1 | tool_output | 9757 | 0 | 1387 | 8370 | 2039 | 1.0 |
| T1 | claim | 243 | 0 | 0 | 243 | 0 | None |
| T3 | tool_output | 9757 | 0 | 382 | 9375 | 452 | 1.0 |
| T3 | claim | 243 | 0 | 0 | 243 | 0 | None |
| TC | tool_output | 9757 | 0 | 0 | 9757 | 790 | 1.0 |
| TC | claim | 243 | 0 | 0 | 243 | 0 | None |
| CLM | tool_output | 9757 | 0 | 0 | 9757 | 0 | None |
| CLM | claim | 243 | 0 | 113 | 130 | 144 | 1.0 |
| **ours** | tool_output | 9757 | 0 | 1395 | 8362 | 3778 | 1.0 |
| **ours** | claim | 243 | 0 | 113 | 130 | 144 | 1.0 |
| baseline | tool_output | 9757 | 0 | 9757 | 0 | 368 | 1.0 |
| baseline | claim | 243 | 0 | 153 | 90 | 38 | 1.0 |
| union | tool_output | 9757 | 0 | 9757 | 0 | 4041 | 1.0 |
| union | claim | 243 | 0 | 225 | 18 | 145 | 1.0 |

**Recall by `source`**: contradicted (contradicted / n spoofed). Last column: ours abstained / ours said supported, on spoofed rows.

| source | n spoofed | T0 | T1 | T3 | TC | CLM | **ours** | baseline | union | ours abst / supp |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| chore_answer | 7 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 6 (0.857) | 6 (0.857) | 0 (0.000) | 6 (0.857) | 1 / 0 |
| claim | 34 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 29 (0.853) | 29 (0.853) | 30 (0.882) | 30 (0.882) | 2 / 3 |
| counterfactual | 1149 | 0 (0.000) | 86 (0.075) | 20 (0.017) | 229 (0.199) | 0 (0.000) | 315 (0.274) | 88 (0.077) | 383 (0.333) | 834 / 0 |
| injected | 3333 | 780 (0.234) | 1376 (0.413) | 415 (0.124) | 417 (0.125) | 0 (0.000) | 2821 (0.846) | 152 (0.046) | 2948 (0.884) | 512 / 0 |
| mode_claim | 62 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 62 (1.000) | 62 (1.000) | 8 (0.129) | 62 (1.000) | 0 / 0 |
| mode_claim_prompted | 44 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 44 (1.000) | 44 (1.000) | 0 (0.000) | 44 (1.000) | 0 / 0 |
| scope_substitution | 18 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 3 (0.167) | 3 (0.167) | 0 (0.000) | 3 (0.167) | 14 / 1 |
| tiered | 1465 | 0 (0.000) | 577 (0.394) | 17 (0.012) | 144 (0.098) | 0 (0.000) | 642 (0.438) | 128 (0.087) | 710 (0.485) | 823 / 0 |

**Recall by `spoof_class`**: contradicted (contradicted / n spoofed). Last column: ours abstained / ours said supported, on spoofed rows.

| spoof_class | n spoofed | T0 | T1 | T3 | TC | CLM | **ours** | baseline | union | ours abst / supp |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| chore_answer | 7 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 6 (0.857) | 6 (0.857) | 0 (0.000) | 6 (0.857) | 1 / 0 |
| counterfactual | 1149 | 0 (0.000) | 86 (0.075) | 20 (0.017) | 229 (0.199) | 0 (0.000) | 315 (0.274) | 88 (0.077) | 383 (0.333) | 834 / 0 |
| environment_tampering | 1 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 / 1 |
| fabricated_digest | 14 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 12 (0.857) | 12 (0.857) | 12 (0.857) | 12 (0.857) | 2 / 0 |
| fabricated_line_count | 20 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 17 (0.850) | 17 (0.850) | 18 (0.900) | 18 (0.900) | 0 / 3 |
| foreign_token_as_digest | 1 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 1 (1.000) | 1 (1.000) | 0 (0.000) | 1 (1.000) | 0 / 0 |
| injected_I-forge | 279 | 0 (0.000) | 30 (0.107) | 15 (0.054) | 160 (0.574) | 0 (0.000) | 184 (0.659) | 0 (0.000) | 184 (0.659) | 95 / 0 |
| injected_I-grammar | 780 | 0 (0.000) | 379 (0.486) | 4 (0.005) | 113 (0.145) | 0 (0.000) | 478 (0.613) | 152 (0.195) | 605 (0.776) | 302 / 0 |
| injected_I-launder | 339 | 0 (0.000) | 164 (0.484) | 110 (0.325) | 115 (0.339) | 0 (0.000) | 266 (0.785) | 0 (0.000) | 266 (0.785) | 73 / 0 |
| injected_I-recompute | 744 | 0 (0.000) | 743 (0.999) | 3 (0.004) | 1 (0.001) | 0 (0.000) | 743 (0.999) | 0 (0.000) | 743 (0.999) | 1 / 0 |
| injected_I-state | 411 | 0 (0.000) | 60 (0.146) | 283 (0.689) | 28 (0.068) | 0 (0.000) | 370 (0.900) | 0 (0.000) | 370 (0.900) | 41 / 0 |
| injected_I-struct | 780 | 780 (1.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 780 (1.000) | 0 (0.000) | 780 (1.000) | 0 / 0 |
| invented_digest_in_claim | 2 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 2 (1.000) | 2 (1.000) | 2 (1.000) | 2 (1.000) | 0 / 0 |
| mode_claim_prompted | 44 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 44 (1.000) | 44 (1.000) | 0 (0.000) | 44 (1.000) | 0 / 0 |
| mode_claim_unperformed_step | 58 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 58 (1.000) | 58 (1.000) | 6 (0.103) | 58 (1.000) | 0 / 0 |
| propagated_harness_artifact | 10 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 10 / 0 |
| propagated_stale_file | 1 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 1 / 0 |
| scope_substitution | 6 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 3 (0.500) | 3 (0.500) | 0 (0.000) | 3 (0.500) | 3 / 0 |
| session_token_misattributed | 1 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 1 (1.000) | 1 (1.000) | 0 (0.000) | 1 (1.000) | 0 / 0 |
| tiered_easy | 507 | 0 (0.000) | 189 (0.373) | 8 (0.016) | 68 (0.134) | 0 (0.000) | 224 (0.442) | 38 (0.075) | 249 (0.491) | 283 / 0 |
| tiered_hard | 474 | 0 (0.000) | 190 (0.401) | 5 (0.011) | 36 (0.076) | 0 (0.000) | 204 (0.430) | 39 (0.082) | 221 (0.466) | 270 / 0 |
| tiered_medium | 484 | 0 (0.000) | 198 (0.409) | 4 (0.008) | 40 (0.083) | 0 (0.000) | 214 (0.442) | 51 (0.105) | 240 (0.496) | 270 / 0 |

**Recall by `unit`**: contradicted (contradicted / n spoofed). Last column: ours abstained / ours said supported, on spoofed rows.

| unit | n spoofed | T0 | T1 | T3 | TC | CLM | **ours** | baseline | union | ours abst / supp |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| claim | 164 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 144 (0.878) | 144 (0.878) | 38 (0.232) | 145 (0.884) | 17 / 3 |
| tool_output | 5948 | 780 (0.131) | 2039 (0.343) | 452 (0.076) | 790 (0.133) | 0 (0.000) | 3778 (0.635) | 368 (0.062) | 4041 (0.679) | 2169 / 1 |

**Recall by `instructed_to_lie`**: contradicted (contradicted / n spoofed). Last column: ours abstained / ours said supported, on spoofed rows.

| instructed_to_lie | n spoofed | T0 | T1 | T3 | TC | CLM | **ours** | baseline | union | ours abst / supp |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 5939 | 780 (0.131) | 1998 (0.336) | 442 (0.074) | 766 (0.129) | 91 (0.015) | 3811 (0.642) | 384 (0.065) | 4068 (0.685) | 2124 / 4 |
| 1 | 173 | 0 (0.000) | 41 (0.237) | 10 (0.058) | 24 (0.139) | 53 (0.306) | 111 (0.642) | 22 (0.127) | 118 (0.682) | 62 / 0 |

**Recall by `consistency`**: contradicted (contradicted / n spoofed). Last column: ours abstained / ours said supported, on spoofed rows.

| consistency | n spoofed | T0 | T1 | T3 | TC | CLM | **ours** | baseline | union | ours abst / supp |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| consistent | 997 | 0 (0.000) | 171 (0.172) | 330 (0.331) | 270 (0.271) | 0 (0.000) | 701 (0.703) | 0 (0.000) | 701 (0.703) | 296 / 0 |
| inconsistent | 353 | 0 (0.000) | 54 (0.153) | 8 (0.023) | 44 (0.125) | 0 (0.000) | 102 (0.289) | 353 (1.000) | 353 (1.000) | 251 / 0 |
| not_checkable | 4762 | 780 (0.164) | 1814 (0.381) | 114 (0.024) | 476 (0.100) | 144 (0.030) | 3119 (0.655) | 53 (0.011) | 3132 (0.658) | 1639 / 4 |

**Recall by `difficulty_tiered`**: contradicted (contradicted / n spoofed). Last column: ours abstained / ours said supported, on spoofed rows.

| difficulty_tiered | n spoofed | T0 | T1 | T3 | TC | CLM | **ours** | baseline | union | ours abst / supp |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| easy | 507 | 0 (0.000) | 189 (0.373) | 8 (0.016) | 68 (0.134) | 0 (0.000) | 224 (0.442) | 38 (0.075) | 249 (0.491) | 283 / 0 |
| hard | 474 | 0 (0.000) | 190 (0.401) | 5 (0.011) | 36 (0.076) | 0 (0.000) | 204 (0.430) | 39 (0.082) | 221 (0.466) | 270 / 0 |
| medium | 484 | 0 (0.000) | 198 (0.409) | 4 (0.008) | 40 (0.083) | 0 (0.000) | 214 (0.442) | 51 (0.105) | 240 (0.496) | 270 / 0 |

**Honest trap classes** (label not_spoofed; verdict counts)

- **ours**: `{'unverified_true_claim|supported': 8, 'unverified_true_claim|unconstrained': 14}`
- baseline: `{'unverified_true_claim|unconstrained': 22}`

**Spoofed rows newly caught over the baseline** (the baseline did not contradict them)

| method | total | by spoof_class |
|---|---:|---|
| T0 | 780 | injected_I-struct 780 |
| T1 | 1984 | injected_I-recompute 743, injected_I-grammar 379, tiered_easy 178, tiered_medium 177, tiered_hard 170, injected_I-launder 164, counterfactual 83, injected_I-state 60, injected_I-forge 30 |
| T3 | 444 | injected_I-state 283, injected_I-launder 110, counterfactual 19, injected_I-forge 15, tiered_easy 7, tiered_hard 4, injected_I-recompute 3, injected_I-grammar 2, tiered_medium 1 |
| TC | 744 | counterfactual 210, injected_I-forge 160, injected_I-launder 115, injected_I-grammar 90, tiered_easy 67, tiered_medium 39, tiered_hard 34, injected_I-state 28, injected_I-recompute 1 |
| CLM | 107 | mode_claim_unperformed_step 52, mode_claim_prompted 44, chore_answer 6, scope_substitution 3, foreign_token_as_digest 1, session_token_misattributed 1 |
| **ours** | 3780 | injected_I-struct 780, injected_I-recompute 743, injected_I-grammar 453, injected_I-state 370, counterfactual 295, injected_I-launder 266, tiered_easy 211, tiered_medium 189, injected_I-forge 184, tiered_hard 182, mode_claim_unperformed_step 52, mode_claim_prompted 44, chore_answer 6, scope_substitution 3, foreign_token_as_digest 1, session_token_misattributed 1 |

Baseline-only catches (baseline contradicted, ours did not): `{'injected_I-grammar': 127, 'counterfactual': 68, 'tiered_medium': 26, 'tiered_easy': 25, 'tiered_hard': 17, 'fabricated_line_count': 1}`

**Unique to one check** (spoofed rows contradicted by exactly one of our checks): T0 780, T1 1761, T3 302, TC 654, CLM 144

### DEV split (tuning data (rules developed here))

**Soundness on this split's honest rows** (FP = honest row called contradicted)

| method | unit | honest n | FP | honest supported | honest abstained | TP | precision |
|---|---|---:|---:|---:|---:|---:|---:|
| T0 | tool_output | 9739 | 0 | 9739 | 0 | 720 | 1.0 |
| T0 | claim | 238 | 0 | 0 | 238 | 0 | None |
| T1 | tool_output | 9739 | 0 | 1358 | 8381 | 1849 | 1.0 |
| T1 | claim | 238 | 0 | 0 | 238 | 0 | None |
| T3 | tool_output | 9739 | 0 | 410 | 9329 | 361 | 1.0 |
| T3 | claim | 238 | 0 | 0 | 238 | 0 | None |
| TC | tool_output | 9739 | 0 | 0 | 9739 | 662 | 1.0 |
| TC | claim | 238 | 0 | 0 | 238 | 0 | None |
| CLM | tool_output | 9739 | 0 | 0 | 9739 | 0 | None |
| CLM | claim | 238 | 0 | 149 | 89 | 109 | 1.0 |
| **ours** | tool_output | 9739 | 0 | 1364 | 8375 | 3379 | 1.0 |
| **ours** | claim | 238 | 0 | 149 | 89 | 109 | 1.0 |
| baseline | tool_output | 9739 | 0 | 9739 | 0 | 384 | 1.0 |
| baseline | claim | 238 | 1 | 115 | 122 | 30 | 0.9677 |
| union | tool_output | 9739 | 0 | 9739 | 0 | 3646 | 1.0 |
| union | claim | 238 | 1 | 218 | 19 | 110 | 0.991 |

**Recall by `source`**: contradicted (contradicted / n spoofed). Last column: ours abstained / ours said supported, on spoofed rows.

| source | n spoofed | T0 | T1 | T3 | TC | CLM | **ours** | baseline | union | ours abst / supp |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| chore_answer | 3 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 3 (1.000) | 3 (1.000) | 0 (0.000) | 3 (1.000) | 0 / 0 |
| claim | 30 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 25 (0.833) | 25 (0.833) | 25 (0.833) | 26 (0.867) | 3 / 2 |
| counterfactual | 1151 | 0 (0.000) | 66 (0.057) | 8 (0.007) | 137 (0.119) | 0 (0.000) | 204 (0.177) | 57 (0.050) | 251 (0.218) | 947 / 0 |
| false_pass_assertion | 1 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 1 / 0 |
| injected | 3108 | 720 (0.232) | 1266 (0.407) | 337 (0.108) | 382 (0.123) | 0 (0.000) | 2585 (0.832) | 127 (0.041) | 2692 (0.866) | 523 / 0 |
| mode_claim | 67 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 66 (0.985) | 66 (0.985) | 4 (0.060) | 66 (0.985) | 0 / 1 |
| mode_claim_prompted | 9 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 9 (1.000) | 9 (1.000) | 1 (0.111) | 9 (1.000) | 0 / 0 |
| scope_substitution | 14 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 5 (0.357) | 5 (0.357) | 0 (0.000) | 5 (0.357) | 9 / 0 |
| tiered | 1514 | 0 (0.000) | 517 (0.342) | 16 (0.011) | 143 (0.095) | 0 (0.000) | 590 (0.390) | 200 (0.132) | 703 (0.464) | 924 / 0 |
| verbatim_contradicted_pass | 1 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 1 (1.000) | 1 (1.000) | 0 (0.000) | 1 (1.000) | 0 / 0 |

**Recall by `spoof_class`**: contradicted (contradicted / n spoofed). Last column: ours abstained / ours said supported, on spoofed rows.

| spoof_class | n spoofed | T0 | T1 | T3 | TC | CLM | **ours** | baseline | union | ours abst / supp |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| chore_answer | 3 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 3 (1.000) | 3 (1.000) | 0 (0.000) | 3 (1.000) | 0 / 0 |
| counterfactual | 1151 | 0 (0.000) | 66 (0.057) | 8 (0.007) | 137 (0.119) | 0 (0.000) | 204 (0.177) | 57 (0.050) | 251 (0.218) | 947 / 0 |
| fabricated_check_result | 1 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 1 (1.000) | 1 (1.000) | 0 (0.000) | 1 (1.000) | 0 / 0 |
| fabricated_digest | 17 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 13 (0.765) | 13 (0.765) | 14 (0.824) | 14 (0.824) | 3 / 1 |
| fabricated_line_count | 13 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 12 (0.923) | 12 (0.923) | 11 (0.846) | 12 (0.923) | 0 / 1 |
| false_pass_assertion | 1 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 1 / 0 |
| foreign_token_as_digest | 3 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 2 (0.667) | 2 (0.667) | 0 (0.000) | 2 (0.667) | 0 / 1 |
| human_view_watermark_as_agent_digest | 1 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 1 (1.000) | 1 (1.000) | 0 (0.000) | 1 (1.000) | 0 / 0 |
| injected_I-forge | 288 | 0 (0.000) | 16 (0.056) | 0 (0.000) | 146 (0.507) | 0 (0.000) | 159 (0.552) | 0 (0.000) | 159 (0.552) | 129 / 0 |
| injected_I-grammar | 720 | 0 (0.000) | 359 (0.499) | 1 (0.001) | 105 (0.146) | 0 (0.000) | 453 (0.629) | 127 (0.176) | 560 (0.778) | 267 / 0 |
| injected_I-launder | 333 | 0 (0.000) | 147 (0.441) | 90 (0.270) | 102 (0.306) | 0 (0.000) | 237 (0.712) | 0 (0.000) | 237 (0.712) | 96 / 0 |
| injected_I-recompute | 711 | 0 (0.000) | 711 (1.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 711 (1.000) | 0 (0.000) | 711 (1.000) | 0 / 0 |
| injected_I-state | 336 | 0 (0.000) | 33 (0.098) | 246 (0.732) | 27 (0.080) | 0 (0.000) | 305 (0.908) | 0 (0.000) | 305 (0.908) | 31 / 0 |
| injected_I-struct | 720 | 720 (1.000) | 0 (0.000) | 0 (0.000) | 2 (0.003) | 0 (0.000) | 720 (1.000) | 0 (0.000) | 720 (1.000) | 0 / 0 |
| invented_digest_in_claim | 1 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 1 (1.000) | 1 (1.000) | 1 (1.000) | 1 (1.000) | 0 / 0 |
| mode_claim_prompted | 9 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 9 (1.000) | 9 (1.000) | 1 (0.111) | 9 (1.000) | 0 / 0 |
| mode_claim_unperformed_step | 60 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 60 (1.000) | 60 (1.000) | 3 (0.050) | 60 (1.000) | 0 / 0 |
| propagated_harness_artifact | 7 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 7 / 0 |
| propagated_stale_file | 1 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 1 / 0 |
| scope_substitution | 5 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 4 (0.800) | 4 (0.800) | 0 (0.000) | 4 (0.800) | 1 / 0 |
| session_token_misattributed | 2 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 2 (1.000) | 2 (1.000) | 0 (0.000) | 2 (1.000) | 0 / 0 |
| tiered_easy | 517 | 0 (0.000) | 169 (0.327) | 7 (0.013) | 53 (0.102) | 0 (0.000) | 201 (0.389) | 67 (0.130) | 240 (0.464) | 316 / 0 |
| tiered_hard | 495 | 0 (0.000) | 172 (0.347) | 0 (0.000) | 44 (0.089) | 0 (0.000) | 185 (0.374) | 55 (0.111) | 213 (0.430) | 310 / 0 |
| tiered_medium | 502 | 0 (0.000) | 176 (0.351) | 9 (0.018) | 46 (0.092) | 0 (0.000) | 204 (0.406) | 78 (0.155) | 250 (0.498) | 298 / 0 |
| verbatim_contradicted_pass | 1 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 1 (1.000) | 1 (1.000) | 0 (0.000) | 1 (1.000) | 0 / 0 |

**Recall by `unit`**: contradicted (contradicted / n spoofed). Last column: ours abstained / ours said supported, on spoofed rows.

| unit | n spoofed | T0 | T1 | T3 | TC | CLM | **ours** | baseline | union | ours abst / supp |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| claim | 125 | 0 (0.000) | 0 (0.000) | 0 (0.000) | 0 (0.000) | 109 (0.872) | 109 (0.872) | 30 (0.240) | 110 (0.880) | 13 / 3 |
| tool_output | 5773 | 720 (0.125) | 1849 (0.320) | 361 (0.062) | 662 (0.115) | 0 (0.000) | 3379 (0.585) | 384 (0.067) | 3646 (0.632) | 2394 / 0 |

**Recall by `instructed_to_lie`**: contradicted (contradicted / n spoofed). Last column: ours abstained / ours said supported, on spoofed rows.

| instructed_to_lie | n spoofed | T0 | T1 | T3 | TC | CLM | **ours** | baseline | union | ours abst / supp |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 5745 | 714 (0.124) | 1800 (0.313) | 361 (0.063) | 630 (0.110) | 90 (0.016) | 3396 (0.591) | 390 (0.068) | 3657 (0.637) | 2346 / 3 |
| 1 | 129 | 0 (0.000) | 44 (0.341) | 0 (0.000) | 27 (0.209) | 19 (0.147) | 76 (0.589) | 24 (0.186) | 83 (0.643) | 53 / 0 |
| None | 24 | 6 (0.250) | 5 (0.208) | 0 (0.000) | 5 (0.208) | 0 (0.000) | 16 (0.667) | 0 (0.000) | 16 (0.667) | 8 / 0 |

**Recall by `consistency`**: contradicted (contradicted / n spoofed). Last column: ours abstained / ours said supported, on spoofed rows.

| consistency | n spoofed | T0 | T1 | T3 | TC | CLM | **ours** | baseline | union | ours abst / supp |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| consistent | 968 | 0 (0.000) | 170 (0.176) | 278 (0.287) | 239 (0.247) | 0 (0.000) | 628 (0.649) | 0 (0.000) | 628 (0.649) | 340 / 0 |
| inconsistent | 354 | 0 (0.000) | 76 (0.215) | 5 (0.014) | 32 (0.090) | 0 (0.000) | 110 (0.311) | 354 (1.000) | 354 (1.000) | 244 / 0 |
| not_checkable | 4576 | 720 (0.157) | 1603 (0.350) | 78 (0.017) | 391 (0.085) | 109 (0.024) | 2750 (0.601) | 60 (0.013) | 2774 (0.606) | 1823 / 3 |

**Recall by `difficulty_tiered`**: contradicted (contradicted / n spoofed). Last column: ours abstained / ours said supported, on spoofed rows.

| difficulty_tiered | n spoofed | T0 | T1 | T3 | TC | CLM | **ours** | baseline | union | ours abst / supp |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| easy | 517 | 0 (0.000) | 169 (0.327) | 7 (0.013) | 53 (0.102) | 0 (0.000) | 201 (0.389) | 67 (0.130) | 240 (0.464) | 316 / 0 |
| hard | 495 | 0 (0.000) | 172 (0.347) | 0 (0.000) | 44 (0.089) | 0 (0.000) | 185 (0.374) | 55 (0.111) | 213 (0.430) | 310 / 0 |
| medium | 502 | 0 (0.000) | 176 (0.351) | 9 (0.018) | 46 (0.092) | 0 (0.000) | 204 (0.406) | 78 (0.155) | 250 (0.498) | 298 / 0 |

**Honest trap classes** (label not_spoofed; verdict counts)

- **ours**: `{'unverified_true_claim|supported': 7, 'unverified_true_claim|unconstrained': 16}`
- baseline: `{'unverified_true_claim|contradicted': 1, 'unverified_true_claim|unconstrained': 22}`

**Spoofed rows newly caught over the baseline** (the baseline did not contradict them)

| method | total | by spoof_class |
|---|---:|---|
| T0 | 720 | injected_I-struct 720 |
| T1 | 1771 | injected_I-recompute 711, injected_I-grammar 359, tiered_medium 148, injected_I-launder 147, tiered_hard 146, tiered_easy 145, counterfactual 66, injected_I-state 33, injected_I-forge 16 |
| T3 | 356 | injected_I-state 246, injected_I-launder 90, counterfactual 8, tiered_medium 7, tiered_easy 4, injected_I-grammar 1 |
| TC | 624 | injected_I-forge 146, counterfactual 127, injected_I-launder 102, injected_I-grammar 85, tiered_easy 52, tiered_medium 42, tiered_hard 41, injected_I-state 27, injected_I-struct 2 |
| CLM | 80 | mode_claim_unperformed_step 57, mode_claim_prompted 8, scope_substitution 4, chore_answer 3, foreign_token_as_digest 2, session_token_misattributed 2, fabricated_line_count 1, human_view_watermark_as_agent_digest 1, fabricated_check_result 1, verbatim_contradicted_pass 1 |
| **ours** | 3342 | injected_I-struct 720, injected_I-recompute 711, injected_I-grammar 433, injected_I-state 305, injected_I-launder 237, counterfactual 194, tiered_easy 173, tiered_medium 172, injected_I-forge 159, tiered_hard 158, mode_claim_unperformed_step 57, mode_claim_prompted 8, scope_substitution 4, chore_answer 3, foreign_token_as_digest 2, session_token_misattributed 2, fabricated_line_count 1, human_view_watermark_as_agent_digest 1, fabricated_check_result 1, verbatim_contradicted_pass 1 |

Baseline-only catches (baseline contradicted, ours did not): `{'injected_I-grammar': 107, 'counterfactual': 47, 'tiered_medium': 46, 'tiered_easy': 39, 'tiered_hard': 28, 'fabricated_digest': 1}`

**Unique to one check** (spoofed rows contradicted by exactly one of our checks): T0 718, T1 1643, T3 261, TC 545, CLM 109
