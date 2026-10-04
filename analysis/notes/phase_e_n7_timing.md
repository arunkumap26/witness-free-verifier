# Phase E N7 attack battery: timing detectors (item `n7_timing`)

- **Data file:** `analysis/out/phase_e/n7_timing.json` (raw numbers only).
- **Script:** `analysis/probes/phase_e_n7_timing.py`. To run it: `PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_n7_timing --workers 4`. It took 2,561 s (`runtime_s`).
- **Pre-registration:**
  - `analysis/PREREG_E.md` section 4.
  - `prereg_e.json n7_attack_battery`.
  - `check_frozen()` passed. `spec_module_sha256_lf` equals `spec_module_sha256_lf_prereg`.
- **The other half of N7:** `phase_e_n7_content.py` covers the content detectors. It leaves R1, P1_FLOOR, P1_GEN, N1, N3, N5g, R3 and N4 to this item.

Cell paths are written `cells.<unit>|<split>|<detector>|<attack>|<param>`. A recall or FPR is quoted as k/n sessions. Everything under "Interpretation" is my reading of the numbers. It is not data.

---

## 1. What ran (measurement facts)

**Detectors**

| Detector | Decision unit and rule |
|---|---|
| R1_BRACKET | stream; L − U > 2,000 ms |
| P1_FLOOR | call; δ ≤ 0 or δ < the A-split floor |
| P1_GEN | qualified W pair; r ≥ 1 |
| N1 | call; residual outside the A bounds |
| N3 | session; ρ_s ≤ 0 over ≥ 20 gaps |
| N5g | session; c_s ≤ 0 |
| R3_GIT | generator-class commit claim; commit_date outside [call − 2 s, result + 2 s] |
| N4 | no per-session rule, so every cell is NA_BLIND_BY_CONSTRUCTION |

The thresholds used are copied into `thresholds_used`.

**Units × splits and their sessions** (`unit_split_checks.<unit|split>.sessions_in_split_unit`)

| Unit | B | E |
|---|---|---|
| swechat/claude_code | 1,679 | 1,545 |
| swechat/opencode | 214 | 193 |
| swechat/codex | 77 | 65 |
| swechat/gemini | 22 | 14 |
| cc_local | 186 | — |
| aiv_cc | 189 | — |

- cc_local is private: aggregates only.
- aiv_cc is a single-agent case study.

**Grid**
- Every attack × parameter of the pre-registered grid: 61 attack-params.
- Per cell, every session with ≥ 1 eligible target, capped at 500 by `rng_for('N7', unit, split)`.
- One tampered copy per session.
- The honest FPR is measured on the same sessions untampered.
- Labels come from `n7_cell_label()`.

**Size:** 4,331 cells (`n_cells`), of which 3,236 are verdict cells (`n_verdict_cells`).

**Not testable** (listed in `scope.not_testable`; these combinations have no cells):
- R1 everywhere except swechat/claude_code and cc_local, because the other units have no decodable request ids.
- R3 on cc_local and aiv_cc, because there is no external commit table.
- Every timing detector on aiv_cu, whowhen and swechat/cursor, because they have no distinct stamps or no results.

**Determinism check.** The full run was executed twice: first without N5g, then with the final script.
- All 3,721 non-N5g cells were identical between the two runs.
- The comparison ran in a scratch script. Only its result is reported here, and it is not in the JSON.

## 2. Honest FPR on the selected sessions

Source: `verdicts.per_unit_split_detector.<unit|split|det>.honest_union_of_selected_sessions`. The rate is session-level: a session counts if ≥ 1 of its units is flagged, and sessions that abstain count as not flagged.

| unit / split | R1 | P1_FLOOR | P1_GEN | N1 | N3 | N5g | R3 |
|---|---|---|---|---|---|---|---|
| swechat/claude_code B (693 s) | 6 (0.009) | 142 (0.205) | 20 (0.029) | 17 (0.025) | 272 (0.392) | 244 (0.352) | 0 (0.000) |
| swechat/claude_code E (687 s) | 5 (0.007) | 154 (0.224) | 24 (0.035) | 15 (0.022) | 261 (0.380) | 231 (0.336) | 0 (0.000) |
| cc_local B (186 s) | 1 (0.005) | 0 (0.000) | 1 (0.005) | 2 (0.011) | 4 (0.022) | 13 (0.070) | NOT_TESTABLE |
| aiv_cc B (119 s, single-agent) | NOT_TESTABLE | 44 (0.370) | 25 (0.210) | 9 (0.076) | 23 (0.193) | 12 (0.101) | NOT_TESTABLE |
| swechat/opencode B (213 s) | NOT_TESTABLE | 7 (0.033) | 3 (0.014) | 5 (0.023) | 27 (0.127) | 78 (0.366) | 0 |
| swechat/opencode E (190 s) | NOT_TESTABLE | 12 (0.063) | 2 (0.011) | 5 (0.026) | 20 (0.105) | 78 (0.411) | 0 |
| swechat/codex B (63 s) | NOT_TESTABLE | 3 (0.048) | 22 (0.349) | 5 (0.079) | 3 (0.048) | 20 (0.317) | 0 |
| swechat/codex E (52 s) | NOT_TESTABLE | 3 (0.058) | 15 (0.288) | 2 (0.038) | 5 (0.096) | 13 (0.250) | 0 |

- swechat/gemini B (21 sessions) and E (12 sessions) are below the 30-session minimum, so every gemini cell is INSUFFICIENT_N.
- R3's zero rests on few decided units. It decided 577 generator claims in B and 572 in E (`decided_units`), in 206 B and 226 E sessions.

## 3. Results by detector

### R1_BRACKET (swechat/claude_code B and E; cc_local B)

**DETECTS** in both splits, with E reproducing B.

| Attack | Range | swechat/claude_code E | swechat/claude_code B | cc_local B |
|---|---|---|---|---|
| `time_response_early` | D ≥ 10 s | at 30 s: 488/500 vs honest 3/500 | at 30 s: 481/500 vs 6/500 | at 30 s: 169/186 vs 1/186 |
| `time_result_late` | D ≥ 5 s | at 5 s: 272/500 vs 3/500 (recall CI lo 0.5002) | | |
| `time_tail_late` and `time_tail_early` | D ≥ 5 s, both splits | | | |
| `id_swap_adjacent` | — | 486/500 | 492/500 | 174/174 |
| `id_splice_foreign`, variant `nearest` | — | 395/500 | 389/500 | 166/186 |

- Localization is near-complete. For example, E `time_response_early|30` has 488/488 flagged sessions with the flag on the tampered stream.
- The single-call types with a DETECTS cell are `time_response_early`, `time_result_late`, `id_swap_adjacent` and `id_splice_foreign`. They are listed under `single_call_types_detecting` in both splits.

**PARTIAL** (E):

| Attack | E recall |
|---|---|
| `time_response_early` at 5 s | 163/500 |
| `insert_pair_consistent` | 187/500 |
| `insert_pair_squeezed` | 91/500 |
| `rewrite_consistent_k` k = 2 | 151/500 |
| `rewrite_consistent_k` k = 5 | 241/500 |
| `id_splice_foreign` random | 17/500 |

**BLIND:**
- `time_response_early` at D ≤ 2 s. At 2 s in E the recall is 3/500, equal to the honest 3/500.
- Every `time_response_late` D. At 300 s in E it is 3/500.
- `time_result_early` at every D.
- `delete_pair` and `delete_response`.

**Stream-level Phase D check.** `cells.*.r1_stream_level.phase_d_rule_tampered_lo_gt_honest_hi` is True for every DETECTS and PARTIAL cell above. It is False for the BLIND ones.
- This rule is an input to the A1 R1 verdict.
- That verdict belongs to the A1 item. It also depends on F1's adopted corrections, which are not applied here: the N7 R1 detector is the uncorrected rule.

### P1_FLOOR

**Honest session FPR is high in the CC-format units:** 0.205 in swechat/claude_code B and 0.224 in E. The detector is per call and its floor sits at about p1, so long sessions almost always contain one call below it.

**swechat/claude_code, `time_result_early`:**
- E: DETECTS at D = 5 s and 30 s only, at 257/500 and 256/500 against honest 121/500. The recall point sits just above 0.5: at 5 s it is 0.514.
- E at every other D, and B at every D: PARTIAL. For example, B at 5 s is 242/500 against 109/500.

**cc_local B:** DETECTS `time_result_early` at D ≥ 1 s. At 60 s it is 100/173 against 0/173.

**swechat/opencode:**
- DETECTS `time_tail_early` at every D. For example, E at 0.5 s is 144/190 against 12/190.
- `time_result_early` is only PARTIAL. For example, E at 1 s is 46/190.

**aiv_cc B (single-agent):** DETECTS `time_result_early` and `time_tail_early`, but against a very high honest rate. In the 67 sessions of `time_result_early|30`, the recall is 67/67 and the honest rate is 38/67.

### P1_GEN

**DETECTS** only on the late-latency attacks (`time_result_late` and `time_tail_late`, large D), in three units:

| Unit / split | Cell | Recall | Honest |
|---|---|---|---|
| swechat/opencode E | 300 s | 137/190 | 2/190 |
| swechat/codex E | 300 s | 33/52 | 15/52 |
| swechat/codex B | — | DETECTS | honest session FPR 0.349 |

In swechat/claude_code the best cell is PARTIAL: E at 300 s, 60/500 against 18/500.

### N1

- No DETECTS cell anywhere.
- The best cells are PARTIAL on `time_result_early` at D ≥ 10 s in swechat/claude_code. For example, B at 60 s is 43/500 against 14/500.
- Every substitution and reorder attack is BLIND. For example, E `sub_matched_bytes|samecmd` is 12/500 against the honest 12/500.

### N3

- No DETECTS or PARTIAL cell in any unit.
- The honest session rate is 0.392 in swechat/claude_code B (272/693), and 530 of those sessions decide. So 272 of the 530 deciding honest sessions already have ρ_s ≤ 0.

### N5g

- No DETECTS or PARTIAL cell in any unit.
- The honest session rate is 0.352 in swechat/claude_code B (244/693, with 455 deciding), 0.366 in opencode B and 0.411 in opencode E.

### R3_GIT (swechat; labelled "E not blind")

- No DETECTS cell.
- PARTIAL in swechat/claude_code on the multi-event timing rewrites: `time_tail_late`/`time_tail_early`, `insert_pair_consistent` and `rewrite_consistent_k`. For example, E `time_tail_late|30` is 158/500 against 0/500.
- On those cells, localization is about 0: 0/158 in that example. The flagged claims are later commit claims that the consistent shift moved out of their window, not the tampered pair.
- The only single-call type that is PARTIAL is `reorder_adjacent_pairs`, with localization 13/13 (E: 13/500).
- Every other unit is BLIND or INSUFFICIENT_N, with 3 to 6 deciding sessions.

### N4

Every cell is NA_BLIND_BY_CONSTRUCTION: there is no per-session rule.

## 4. Walk-through table

Source: `verdicts.walk_through_timing_only`. It lists the attacks with no DETECTS cell in any timing detector × unit × split × parameter.

| Attack | Single-call type? | Status under the timing detectors |
|---|---|---|
| time_response_late | no | walks through (BLIND / INSUFFICIENT_N) |
| sub_single_flip_error | yes | walks through |
| sub_single_digit | yes | walks through |
| sub_matched_bytes (base, samecmd) | yes | walks through |
| rewrite_consistent_k (2, 5) | no | walks through (best PARTIAL) |
| reorder_adjacent_pairs | yes | walks through (best PARTIAL) |
| reorder_lines | yes | walks through |
| delete_pair | yes | walks through |
| delete_response | yes | walks through |
| insert_pair_consistent | yes | walks through (best PARTIAL) |
| insert_pair_squeezed | yes | walks through (best PARTIAL) |
| inline_fabrication | yes | all cells NA: no timing detector reads usage |
| image_relabel_gui | yes | all cells NA |
| image_insert_screenshot | yes | NA or NOT_RUN: attack defined on aiv_cu, where every timing detector is NOT_TESTABLE |

These attacks have at least one DETECTS cell:
- time_result_early;
- time_result_late;
- time_tail_late;
- time_tail_early;
- time_response_early;
- id_swap_adjacent;
- id_splice_foreign.

This is the timing half only. The combined N7 walk-through needs the content half as well.

---

## 5. Interpretation (not data)

1. **Only one timing detector is a strong N7 performer: R1.** It is strong only for back-dating ≥ 10 s and for id tampering, and only where decodable request ids exist: swechat/claude_code and cc_local.
   - Its honest session rate stays at or below 0.009 in both swechat splits, and E reproduces B cell for cell at the label level.
   - It is one-sided by construction: late-shifted responses are invisible.
   - A forger who back-dates by ≤ 2 s, or less than the consistent-stream slack, also passes.
   - It never sees results moved earlier, deletions, or content.
   - A random foreign id is mostly invisible. Ids decoded more than a day from their event are dropped by `bracket_responses`, so the session abstains; only the `nearest` variant is caught.
2. **The latency-floor detector is real but expensive.** P1_FLOOR does respond to results moved earlier, but at a session-level honest rate of 0.20–0.22 in swechat/claude_code. That makes it usable only in the low-FPR units.
   - In cc_local the honest rate was 0/186.
   - In opencode it was 0.033 in B and 0.063 in E.
   - In aiv_cc it was 0.370, so a DETECTS label there means little.
3. **The opencode floor result depends on the injector's clamp.** In opencode, P1_FLOOR catches `time_tail_early` (unclamped, so δ < 0) but only partly catches `time_result_early`. The injector clamps early results at call + 1 ms, and the opencode read floor is exactly 0.001 s (`thresholds_used.floors_s`), so a clamped read never falls strictly below its floor.
4. **N3 and N5g null.** They never separate from honest on any attack. I read this as a null of the honest baseline, not of the attacks. Their honest session flag rates are:
   - N3 (reaction time): 0.392 / 0.380 in swechat/claude_code B / E.
   - N5g (cold start): 0.352 / 0.336 in swechat/claude_code and 0.366 / 0.411 in opencode.
5. **N1 is weak.** It reaches only PARTIAL. Its highest recall in swechat/claude_code is 43/500 (0.086) in B and 0.074 in E. Its residual needs a repeated command in the same session, and the tampered call is rarely one.
6. **R3's catches are collateral.** R3 has a zero honest rate on its decided claims, but what it catches comes from rewrites shifting later git commits, not from the tampered call. Its coverage is small: 206 of 693 sessions decide in B and 226 of 687 in E.
7. **Content substitution is invisible to every timing detector.** These are single-call substitutions with matched bytes, flipped errors, digit edits and line swaps. This is expected for the content-blind detectors. It is a null for P1_GEN, N1 and N3, which are applicable by the field matrix and still BLIND.

## 6. Caveats

- **Target rules are interpretation choices fixed before any result** (`target_rules` in the JSON).
  - `time_result_early` uses `qualify_pairs`'s shell + auto_read scope. P1_FLOOR/P1_GEN only see Phase B auto_read/internal_noperm pairs in CC-format units, so shell targets bound their recall.
  - Insertions use main-thread results and main-thread donors.
- **aiv_cc stamps have µs precision**, but `_shift_ts` (a frozen injector) writes ms. Every shifted aiv_cc event loses its sub-ms part.
  - The `k_new_flag_not_on_target` counts bound the collateral flags this could cause: for aiv_cc P1_FLOOR `time_tail_early` they are ≤ 3 per cell.
- **Per-call detectors grow with session length.** For P1_FLOOR, P1_GEN, N1 and R3, the honest session FPR rises with session length. The prereg accepts this cost.
- **R3 is E not blind** (prereg §0).
- **cc_local outputs are aggregates only.** No session ids, text or commands appear in the JSON.

## 7. Deviations

Logged in this item's StructuredOutput:
- The output file name (`n7_timing` instead of `n7_attacks`).
- The qualification scope for `time_result_early`.
- The unspecified target and donor eligibility rules.
- No cells for NOT_TESTABLE detector × unit combinations.
- The R3 SHA resolution order.
- The P1_FLOOR decision units.
- N5g included by assignment of the content half.

No threshold was changed. No kill test is defined for N7 cells.
