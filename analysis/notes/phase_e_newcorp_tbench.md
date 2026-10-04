# Phase E new corpora, group `tbench`: tbench2 and glm_tb21

Script: `analysis/probes/phase_e_newcorp_tbench.py` (`PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_newcorp_tbench`,
about 20 min; `NEWCORP_ONLY=<corpus>` runs one corpus).
Outputs: `analysis/out/phase_e/newcorp_measure_tbench2.json`, `analysis/out/phase_e/newcorp_measure_glm_tb21.json`.
Each output has `cells` (one per N6 row: label, B / E / B∪E labels, deciding number, n, sessions, CI and a JSON path into
`detail`), `detail` (raw numbers per split), `checks` (artifact checks on B∪E for cells at WEAK or better) and
`deviations`. Every number below is copied from those files. Sections 1 to 4 report numbers only. Interpretation is
confined to section 5 and is marked as such.

## 1. What ran

- **check_frozen() passed.** The spec module matches `prereg_e.json`. Each corpus's calibration file sha256 equals
  its change_log entry (`calibration.matches_change_log`).
- **D1, unit argument.** Every frozen function was called with `unit = 'tbench2'` or `unit = 'glm_tb21'`.
- **D2, dominance cluster.** The AC4 and confinement cluster is the stratum: submitting agent__model for tbench2
  (25 strata); glm_tb21 has a single stratum.
- **D5, exclusions.** `newcorp_exclusions.json` lists nothing for either corpus, and 0 sessions were removed.
- **D6, blindness.** The R1 bracket, placebo and tamper cells, and all latency-built cells (Probe 1, N1, N4, N5g) and
  N3, carry `NOT_BLIND (D6)`.
- **Caches.** Built with the corpora's own loaders using `--split B|E`. This was the first B/E run of those code
  paths, and no loader logic was changed.

  | corpus | split | sessions | rows | parse errors |
  |---|---|---|---|---|
  | tbench2 | B | 2,000 | 230,991 | 0 |
  | tbench2 | E | 2,000 | 231,800 | 0 |
  | glm_tb21 | B | 23 | 2,735 | 0 |
  | glm_tb21 | E | 23 | 3,455 | 0 |

  The sha256 of each cache is in `caches`. H was never built or read.
- **Credential redaction (counts only, loader redaction).** tbench2 `extra.credential_redactions` summed to 1,157 (B)
  and 1,355 (E); the markers sit in text, args and command. glm_tb21 had 0. No value was printed.
- **Field gate.** Re-checked on B and E (`field_gate`). On tbench2 B:
  - 56,550 pairs, of which 13,950 have distinct call/result stamps. Only 6 of 25 strata have them: the three Claude
    Code JSONL strata, the two Gemini CLI strata and hookele. The ATIF strata share one stamp per step.
  - Decodable request ids exist only in WozCode__Claude-Opus-4.6: 79 sessions per split.
  - Usage is GRANULAR.
  - There is no error definition for the unit.

  glm_tb21 has 0 pairs with distinct stamps on A, B and E, no request ids, and GRANULAR usage.

## 2. Cells (N6 label = E verdict where E is not INSUFFICIENT_N, else B "B only")

### tbench2 (2,000 B + 2,000 E sessions)

| row | cell | B | E | B∪E | deciding number (E unless noted) | n / sessions |
|---|---|---|---|---|---|---|
| R1_bracket (WozCode stratum) | **ALIVE**, NOT_BLIND | ALIVE | ALIVE | ALIVE | honest streams 0/82 (Wilson hi 0.0448); 30 s back-date 79/82 (cluster lo 0.918); N7 single-response DETECTS: time_response_early ≥ 10 s, id_swap_adjacent 75/79, id_splice_foreign random 79/79, time_result_late ≥ 5 s | 82 streams / 79 s |
| P4b_round | **ALIVE** | ALIVE | ALIVE | ALIVE | T_orig last-0 321/653 = 0.492 [0.412, 0.574] vs M_all 0.150 (CI hi 0.175) | 653 values / 204 s |
| N1 (shell) | **WEAK**, NOT_BLIND, pooled bounds | WEAK | WEAK | WEAK | fails only the flag-rate leg: 47/1,368 = 0.034 (CI hi 0.054); ρ_hon 0.036 [−0.001, 0.076]; ρ_pc 0.433 [0.335, 0.524]; RR 0.152 | 1,368 residuals / 204 s |
| N2 | **WEAK** | WEAK | WEAK | WEAK | honest flag 2,078/13,018 = 0.160 [0.133, 0.188]; recall at 0.8τ 0.897 | 13,018 responses / 1,352 s |
| N3 | **WEAK**, NOT_BLIND | WEAK | WEAK | WEAK | pooled ρ 0.261 [0.233, 0.289]; share ρ_s ≤ 0 = 278/1,037 = 0.268 | 50,068 gaps / 1,037 s |
| R4_dual (2 Claude Code strata) | **WEAK** | WEAK | WEAK | WEAK | honest sessions 0/117 (Wilson hi 0.032); no single-call type DETECTS; PARTIAL: sub_matched_bytes base 11/156, reorder_adjacent_pairs 27/156 | 428 units / 117 s |
| P2_knowledge | DEAD | DEAD | DEAD | DEAD | S_deep empty (no error definition, so first_try_success is never set); fallback S_path_any 8,429/14,019 = 0.601 [0.574, 0.628] | 14,019 / 1,146 s |
| N5a_determinism | DEAD | DEAD | DEAD | DEAD | drift 167/206 = 0.811 (B 0.679) | 206 pairs / 90 s |
| N5b_sort | DEAD | DEAD | DEAD | DEAD | ls violation 0.383 (1,420 outputs); grep_n 0.104 (452); git_log INSUFFICIENT_N (16) | |
| N5d_whitespace | DEAD | DEAD | DEAD | DEAD | pytest_banner 0.666 (548), wc 0.400 (105), ls -l 0.077 (1,561); git_status INSUFFICIENT_N (29) | |
| N5e_size | DEAD | DEAD | DEAD | DEAD | 14 of 38 families above the comparator's IQR CI hi (share 0.37 < 0.5) | 38 families |
| N5g_cold_start | DEAD, NOT_BLIND | WEAK | DEAD | WEAK | median c CI lo 0.0 (E) | 374 s |
| P4a_hex | INSUFFICIENT_N | INSUFF | INSUFF | ALIVE | T_orig symbols 768 (E) and 832 (B), below N_min 1,131 | |
| N5c_truncation | INSUFFICIENT_N | INSUFF | INSUFF | INSUFF | cc_chars_mid 14 (B) and 20 (E) marked results, below 50 | |
| P1_latency | NOT_TESTABLE | | | | Probe 1 qualification classes, floors, G90 and the G set are defined only for registered units; there is no pooled value (D1) | |
| N4 | NOT_TESTABLE | | | | Phase B W/G populations are defined only for registered units (D1) | |
| P3a, P3b, N5f | NOT_TESTABLE | | | | error signal: `error_classes` has no definition for the unit (D1) | |
| R2, R3, R5 | NOT_TESTABLE | | | | no IMAGE usage; no external commit table; no Entire tally (field gate) | |

### glm_tb21 (23 B + 23 E sessions, one stratum)

| row | cell | B | E | B∪E | deciding number | n / sessions |
|---|---|---|---|---|---|---|
| N2 | **WEAK** | WEAK | WEAK | WEAK | E: honest flag 21/224 = 0.094 (CI hi 0.248); recall at 0.8τ 0.973. B: 9/247 = 0.036 (hi 0.082), recall 0.858 | 224 / 17 s |
| N3 | INSUFFICIENT_N, NOT_BLIND | INSUFF (11 s) | INSUFF (10 s) | DEAD (21 s, pooled ρ CI lo −0.00001) | below 20 sessions with ≥ 20 gaps in each split | |
| P2, P4a, P4b, N5a–e | INSUFFICIENT_N | | | | P2 has 0 first mentions (Terminus keystrokes are not parsed as shell by the Phase B code); P4b T_orig 10 values | |
| P1, N1, N4, N5g | NOT_TESTABLE | | | | 0 pairs with distinct call/result stamps on A, B and E | |
| R1 | NOT_TESTABLE | | | | no request ids (self-hosted vLLM) | |
| P3a, P3b, N5f | NOT_TESTABLE | | | | error signal (D1) | |
| R2–R5 | NOT_TESTABLE | | | | field gate | |

## 3. Artifact checks on B∪E (cells at WEAK or better; `checks.<row>`)

No check lowered any WEAK+ cell. AC1 was run on every one of those cells. N5g reached WEAK on B only, its cell is
DEAD, and it has no raw reader, so its AC1 is NOT_RUN.

- **AC1 (parser), an independent raw reader:**
  - R1: 30/30 decoded responses match the raw requestId and timestamp (uuid lookup).
  - N1: 30/30 flagged shell calls match (stamps within 1 ms, n1 key; cc_jsonl 19, gemini_cli 8, hookele 3).
  - N2: 30/30 flagged responses keep the flag on raw values (usage_out, rc and chars all equal; atif 29, hookele 1).
  - N3: 30/30 gaps of flagged sessions match raw stamps (atif 24, gemini 3, hookele 2, cc 1).
  - glm N2: 30/30.
  - R4: no flagged unit, so 0 audited.
- **AC2 (truncation) and AC3 (join):** PASS everywhere. Two exceptions:
  - glm N2 AC3 keeps 42 of 471 responses and is INSUFFICIENT_N. That has no effect, because it is not a level.
  - For tbench2 N2, AC3 keeps 12,998 of 26,139 responses and is still WEAK.
- **AC4 (stratum).**
  - N1 is not dominated: the top stratum is ClaudeCode__GLM-4.7 at 0.243 of residuals.
  - N2 and N3 are not dominated.
  - R4 is dominated (ClaudeCode__GLM-4.7 holds 0.556 of units), but both leave-outs keep the honest part ALIVE.
  - R1 is a single stratum, so it is labelled only; no session holds more than 0.10 of the streams.
  - glm N2 is a single stratum and labelled only; leaving out its top session (0.185 of responses) stays WEAK.
- **AC5:** NOT_RUN, because `population_cells()` has no new-corpus branch (frozen).
- **Confinement.** None of the WEAK+ cells is CONFINED:
  - N1: the model and stratum axes are OK, with 5 signal-bearing strata.
  - N2: OK, but the strata range from ALIVE (WozCode, JJAgent, Terminus2__DeepSeek) to DEAD (Meta-Harness,
    Terminus-KIRA ×2, Terminus2__GLM-5, Terminus2__GPT-5.3-Codex, vix).
  - N3: OK.
  - R1: OK on length terciles; all three terciles are ALIVE.
  - N5g (B WEAK only) is CONFINED on length tercile, which would lower it to DEAD; the cell is already DEAD from E.

## 4. Other reported numbers (context, no verdict effect)

- **F3 parameter exclusion on P4b (tbench2).** The prereg assigns F3 to A1 candidates only, so it is reported as
  context.
  - Strict exclusion removes 121 of 653 E values.
  - The residual last-0 share is 0.429 against M_all 0.150: g = 0.279 against g_full = 0.342, a ratio of 0.82.
  - The F3 rule on these data would give ALIVE (B and B∪E as well).
  - Counts equal `prereg_e_calibration.cal_round` on the same frames.
- **N1 positive control.** ρ_pc does not depend on G90: G90 = 1 and G90 = 100 differ by at most 2.5e-5 (rank ties
  under floating point).
- **Probe 4 hex on B∪E (not the cell).**
  - T_orig w_adj = 0.620 [0.373, 0.981] on 1,360 symbols from 65 sessions.
  - The M_git control has w_adj 0.024 (hi 0.059).
- **R1 tolerance sensitivity.** 0 honest streams exceed 0 ms of gap on either split. Consistent-stream slack U − L:
  p5 1,851 ms, p50 2,297 ms, p95 2,952 ms (E).
- **R1 N7 blind cells (E):**
  - time_response_early ≤ 2 s
  - time_result_early (all D)
  - time_response_late (5, 30, 300 s)
  - delete_response and delete_pair
  - id_splice_foreign with the nearest-time donor (1/79)

## 5. INTERPRETATION (not a verdict; the reader may disagree)

1. **The request-id bracket transfers.**
   - On a second harness with Anthropic ids (WozCode on Terminal-Bench 2.0), 0 of 168 honest streams are
     inconsistent on B∪E.
   - The 30 s back-date is caught in 161/168 streams. Id swaps and foreign-id splices are caught.
   - It is blind to the same attack classes as on swechat: small shifts under the ~2.3 s slack, late moves, deletions,
     and a splice whose donor id is nearest in time.
   - Caveats:
     - It is one submission: one agent, one model, 79 sessions per split.
     - The cell is NOT_BLIND (D6). Track B decoded ids over the full corpus.
     - The clock layout is still inferred, not documented.
   - This is a replication on new data under frozen thresholds, not a held-out confirmation.
2. **The R4 dual-rendering recount has no false positives on two non-Anthropic-model Claude Code harnesses**
   (GLM-4.7 and a local MiniMax build): 0 of 898 Read units. It only reaches WEAK because, with attack-defined
   targets, most substitutions hit non-Read results, which R4 cannot see. This is a coverage limit, not a
   false-positive problem.
3. **The three statistical WEAKs are heterogeneous.**
   - N1 is WEAK or better in every reportable latency stratum (cchuter is ALIVE; WozCode is below the minimum n).
     It misses ALIVE only on the flag rate at the pooled bounds (0.034 against 0.02). The pooled bounds came from other harnesses, so this is a threshold-transfer cost rather than a property of
     tbench2.
   - N2's honest flag rate ranges from ALIVE to DEAD across submissions. It is a corpus average of very different
     accounting conventions; for example, litellm proxies and Terminus "completion_tokens" may include hidden
     reasoning.
   - N3 is positive (ρ about 0.25), but ATIF stamps are step-write times taken after the commands ran. The "gap"
     therefore mixes the next LLM call with execution time, so the gap is not reading time. The prereg's
     prefill caveat applies, plus this one.
4. **The N5 battery is DEAD here as on swechat/claude_code.** Determinism drift 0.81, ls order 0.38 and pytest banner
   0.67 are honest violations. Terminal-screen results, multi-directory listings and writes hidden in Terminus
   keystrokes are plausible sources. The frozen intervening-write check only inspects shell-family keys, so a write
   inside a `bash_command` keystroke does not break a determinism pair. These are nulls of the checkers, not
   evidence about fabrication.
5. **Round numbers (P4b ALIVE) survive the F3 parameter exclusion on this corpus.** Model-typed integers in arguments
   stay rounder than machine output after removing CLI options, sleep/timeout arguments and key=value parameters.
   Many of these integers sit in code the model writes inside commands, such as heredoc scripts and python -c.
   Whether that counts as "a fabricated tool result would carry the signature" is open: the signal lives in call
   args, not in results.
6. **glm_tb21 is too small for nearly everything** (23 + 23 sessions, one stratum). It also has no distinct stamps:
   the Terminus host stamps the call and the result together. N2 WEAK on 17 to 19 sessions is the only measurable
   cell. Its AC3 is not informative because Terminus call ids ("call_k_j"-style) repeat across sessions, and the
   frozen join check treats them as copied.
7. **Generalisable finding for the new-corpus protocol.** D1's own-name unit argument switches off every mechanism
   that depends on a per-unit Phase B definition: error classes, Probe 1 qualification, G90/G set, and W/G for N4.
   The native error signal exists in tbench2 (15,279 of 66,124 B results carry `native_error`; 1,462 True) but is
   unused by construction. This is a NOT_TESTABLE of definitions, not of data.

## 6. What would change these labels

- **R1.** Any honest inconsistent stream in a further Anthropic-id corpus, or a documented id layout that differs
  from the inferred one.
- **N1.** Unit-specific bounds from a larger A, which the prereg forbids now.
- **N2.** A per-stratum τ; this would be a new pre-registration.
- **P4b.** The F3 collapse rule firing on another split. A reading that counts only result-side numbers would also
  change it, because T_orig here comes from call args.
- **glm_tb21.** All of its cells change only with more sessions.
