# Phase E, N7 attack battery: content and accounting detectors (`n7_content`)

**Paragraphs marked INTERPRETATION are interpretation. The "Raw facts" list only points into the JSON.** The numbers
come from
`analysis/out/phase_e/n7_content.json` (script `analysis/probes/phase_e_n7_content.py`, shards in
`analysis/out/phase_e/n7_content_shards/`). Each number is quoted with the JSON path that holds it. `cells[...]` keys
read `unit|split|detector|attack|param`. Rates are k/n with 95% Wilson intervals over sessions, one tampered copy per
session. The pre-registration is `PREREG_E.md` section 4 and `prereg_e.json n7_attack_battery`. `check_frozen()`
passed before any data was read (`check_frozen`).

This is the content and accounting half of N7. The timing detectors (R1 bracket, P1 floor and generation, N1, N3, N5g,
R3 git, N4) are in the timing half (`phase_e_n7_timing.py`) and are not computed here
(`scope.detectors_other_half_not_computed_here`).

## Raw facts (pointers only)

- **Detectors (11).** P2_KFN, P3_ZERO, N2, N5a, N5b, N5c, N5d, N5f, R2_IMAGE, R4_DUAL, R5_LEDGER
  (`scope.detectors_this_half`, decision units in `scope.decision_units`).
- **Probe 4 (entropy and round numbers) is NOT_RUN.** The pre-registered N7 detector table and the applicability
  matrix have no Probe 4 detector (`scope.P4_round_entropy`, `deviations[1]`).
- **Cells.** 1,275 unit x split x detector x attack x parameter cells were computed (`verdict_cells_computed`):
  - DETECTS 12;
  - PARTIAL 35;
  - BLIND 939;
  - INSUFFICIENT_N 289 (`label_counts`).
- **NA_BLIND_BY_CONSTRUCTION.** 125 detector x attack pairs (`na_blind_by_construction`). These include every `time_*` and
  `id_*` attack for every detector in this half: no content or accounting detector reads stamps or request ids. They
  count as BLIND in the walk-through and are not cells.
- **Samples.** The cap is 500 tampered sessions per cell, drawn from one seeded order per unit x split. The honest FPR
  is measured on the same sessions untampered.
- **Units.**
  - swechat/claude_code: B 1,679 sessions, E 1,545.
  - swechat/opencode: B 214, E 193.
  - swechat/codex: B 77, E 65.
  - swechat/gemini: B 22, E 14.
  - swechat/cursor: B 8, E 7.
  - cc_local: B 186 (private, aggregates only).
  - aiv_cc: B 189 (single-agent case study).
  - aiv_cu: B 2,000, E 2,000.
  - whowhen: B 111.

  The counts are at `units.<unit>.<split>.sessions`. Copilot and simple_text have 0 sessions in B and E.

## 1. What reaches DETECTS

INTERPRETATION. Only the **accounting** detectors reach DETECTS, and only against **accounting** attacks. No content
detector (P2_KFN, P3_ZERO, N5a–N5f) reaches DETECTS against any attack in any unit. Every DETECTS cell:

| cell | recall | honest FPR (same sessions) | ADR |
|---|---|---|---|
| swechat/claude_code B, R5_LEDGER, delete_response | 379/500 = 0.758 [0.719, 0.793] | 5/500, hi 0.023 | 0.748 [0.708, 0.784] |
| swechat/claude_code E, R5_LEDGER, delete_response | 396/500 = 0.792 [0.754, 0.825] | 4/500, hi 0.020 | 0.784 [0.748, 0.820] |
| swechat/claude_code B, R5_LEDGER, inline_fabrication | 368/500 = 0.736 [0.696, 0.773] | 5/500, hi 0.023 | 0.726 [0.690, 0.766] |
| swechat/claude_code E, R5_LEDGER, inline_fabrication | 374/500 = 0.748 [0.708, 0.784] | 4/500, hi 0.020 | 0.740 [0.698, 0.778] |
| aiv_cu B, R2_IMAGE, image_relabel_gui | 305/323 = 0.944 [0.914, 0.964] | 26/323, hi 0.115 | 0.876 [0.839, 0.910] |
| aiv_cu E, R2_IMAGE, image_relabel_gui | 305/325 = 0.938 [0.907, 0.960] | 18/325, hi 0.086 | 0.889 [0.849, 0.923] |
| aiv_cu B, R2_IMAGE, image_insert_screenshot | 234/404 = 0.579 [0.531, 0.626] | 26/404, hi 0.093 | 0.515 [0.470, 0.562] |
| aiv_cu E, R2_IMAGE, image_insert_screenshot | 231/403 = 0.573 [0.524, 0.621] | 18/403, hi 0.069 | 0.529 [0.476, 0.576] |
| cc_local B, N2, inline_fabrication | 120/174 = 0.690 [0.617, 0.754] | 18/174, hi 0.158 | 0.586 [0.511, 0.661] |
| swechat/opencode B, N2, inline_fabrication | 164/213 = 0.770 [0.709, 0.821] | 72/213, hi 0.404 | 0.432 [0.366, 0.498] |
| swechat/opencode E, N2, inline_fabrication | 136/190 = 0.716 [0.648, 0.775] | 67/190, hi 0.423 | 0.363 [0.295, 0.432] |
| swechat/codex E, N2, inline_fabrication | 45/52 = 0.865 [0.747, 0.933] | 30/52, hi 0.701 | 0.288 [0.173, 0.404] |

Paths: `cells["<key>"].recall`, `.fpr`, `.k_honest_flagged`, `.adr`.

Reading notes (interpretation):

- **R5_LEDGER** (Entire usage tally against a recount of the raw transcript) replicates on E. It detects deleted
  responses and inline fabrication. It is PARTIAL on delete_pair:
  - B: 229/500 = 0.458 [0.415, 0.502];
  - E: 219/500 = 0.438 [0.395, 0.482].

  It is **BLIND to inserted call+result pairs**:
  - B insert_pair_consistent: 5/500, equal to its honest 5/500;
  - E insert_pair_consistent: 4/500, equal to its honest 4/500.

  This is as the Phase D test plan expected: an inserted pair carries no message id, so the tally cannot see it.
  R5 is labelled **"E not blind"** (`cells[...].labels`).
- **N2 DETECTS in high-FPR units.**
  - In opencode and codex, the DETECTS label sits on a high honest session flag rate: opencode B 72/213, codex E 30/52.
  - Codex B, the same attack, is BLIND: recall 56/63 = 0.889 [0.788, 0.945] against FPR 44/63 with hi 0.798
    (`cells["swechat/codex|B|N2|inline_fabrication|tau"]`).
  - In swechat/claude_code, N2 is only PARTIAL:
    - B 220/500 = 0.440 [0.397, 0.484] against FPR hi 0.203;
    - E 224/500 = 0.448 [0.405, 0.492] against FPR hi 0.201.
  - The per-response flag rule is diluted at session level. A session is flagged when any response is.
- **R2_IMAGE detects the two image attacks on B and on E.**
  - It is PARTIAL on delete_pair and on both insert_pair attacks (B and E).
  - It is BLIND to inline_fabrication, which touches output tokens, not prompt IMAGE tokens:
    - B 22/335, equal to its honest 22/335;
    - E 16/325, equal to its honest 16/325.

## 2. Honest session-level flag rates (whole detector population)

The paths are `units.<unit>.<split>.honest_population.<detector>.session_flag_rate_all` and `flagged_sessions` /
`population_sessions`. Abstaining sessions count as not flagged.

| detector | swechat/claude_code B | swechat/claude_code E | other units (B; E where it exists) |
|---|---|---|---|
| R4_DUAL | 0/1,679 (0 of 30,011 counters) | 0/1,545 (0 of 28,198 counters) | cc_local 0/186 (0 of 365 counters) |
| R5_LEDGER | 13/1,679 = 0.008 [0.005, 0.013] | 10/1,545 = 0.006 [0.004, 0.012] | NOT_RUN for other swechat formats |
| P3_ZERO | 9/1,679 (9 of 413 long sessions) | 8/1,545 (8 of 380 long) | aiv_cu B 678/2,000 (678 of 988 long); cc_local 15/186 |
| N2 | 265/1,679 = 0.158 | 237/1,545 = 0.153 | opencode B 72/214; codex B 44/77; cc_local 18/186; aiv_cu B 66/1,130 |
| P2_KFN | 285/1,679 = 0.170 | 275/1,545 = 0.178 | opencode B 13/214; cc_local 7/186; aiv_cc 0/189 |
| N5a | 119/1,679 = 0.071 | 119/1,545 = 0.077 | codex B 3/77 |
| N5b | 196/1,679 = 0.117 | 189/1,545 = 0.122 | codex B 21/77; cc_local 17/186; aiv_cu B 105/2,000 |
| N5c | 19/1,679 = 0.011 | 16/1,545 = 0.010 | 0 flagged elsewhere; deciding sessions: aiv_cc 6, cc_local 3, opencode B 1 and E 1, all other units 0 |
| N5d | 159/1,679 = 0.095 | 130/1,545 = 0.084 | aiv_cu B 319/2,000; cc_local 19/186 |
| N5f | 1/1,679 (3 deciding sessions) | 1/1,545 (3 deciding) | 0 deciding sessions in every other unit except cc_local (2, 0 flagged) |
| R2_IMAGE | not testable | not testable | aiv_cu B 26/404 = 0.064 [0.044, 0.093]; E 18/403 = 0.045 [0.028, 0.069] |

Interpretation:

- **R4_DUAL** has no honest flag in any unit. Its zero is **not** out of sample:
  - Phase C identified the five whitelist formats on the full swechat population, which includes B and E (hence the
    "E not blind" label);
  - the frozen regexes are a fresh definition of those same formats.
- **R2_IMAGE on B exceeds 0.05.** Its B honest session flag rate of 26/404 = 0.064 is above the 0.05 that the Phase D
  kill rule for R2 uses (§1.4). The E rate is 18/403 = 0.045. The R2 verdict belongs to the A1 R2 item, which reads
  these numbers. At window level the rate is 70/13,472 on B and 18/13,429 on E
  (`honest_population.R2_IMAGE.unit_flag_rate`).
- **P3_ZERO cross-check.** P3_ZERO on swechat/claude_code B reproduces Probe 3's Phase B count exactly: 9 zero-error
  sessions among 413 long sessions (PREREG_E.md section 1.2 quotes 9/413). On aiv_cu P3 is meaningless: 678 of 988
  long sessions have zero proxy errors (B).
- **N5a has a dataset-redaction false-positive source.** In swechat/claude_code B, 287 determinism pairs have an n1 key
  that contains the dataset's redaction marker (`<R>`). 277 of them are flagged, against 640 flagged pairs in total
  (`units.swechat/claude_code.B.honest_population.N5a.descriptive_pairs_with_redacted_key`, `flagged_units`). Distinct
  redacted paths collapse to one key, so different files are compared as if they were repeats. This is descriptive
  only: the pre-registered rule is unchanged and no number was corrected.

## 2b. Inputs to the Phase D proposal rule (`proposal_rule_inputs`)

`S:a1.proposal_rules` decides R2, R4 and R5 from two inputs:
- the session-level honest flag rate on B ∪ E;
- the N7 cells on E (on B for units without E).

B and E hold disjoint sessions, so the pooled rate is a Wilson share over their union. The script applies the rule
mechanically **for reference only**. The A1 proposal items own these verdicts.

| proposal x unit | honest B ∪ E | single-call types DETECTS (reference split) | mechanical label (reference) |
|---|---|---|---|
| R2_IMAGE, aiv_cu (Gemini strata) | 44/807 = 0.055 [0.041, 0.072] | image_insert_screenshot, image_relabel_gui (E) | DEAD: the R2 kill rule fires at > 0.05 |
| R4_DUAL, swechat/claude_code | 0/3,224, hi 0.0012 | none (E) | WEAK, E not blind |
| R4_DUAL, cc_local | 0/186, hi 0.020 | none (B) | WEAK, B only, private |
| R5_LEDGER, swechat/claude_code | 23/3,224 = 0.007 [0.005, 0.011] | delete_response, inline_fabrication (E) | ALIVE, E not blind |

INTERPRETATION:

- **R2.** R2 detects both image attacks, yet its Phase D kill rule fires on the pooled honest rate: 44/807 = 0.055 is
  above 0.05. E alone is 18/403 = 0.045. The kill is recorded, not overridden.
- **R4.** R4 never flags an honest session. It is still only WEAK, because no attack type reaches DETECTS: the best
  is PARTIAL at recall below 0.5.
- **R5.** R5 meets the ALIVE rule, but it carries "E not blind": Phase C lenses read E sessions for this mechanism.

## 3. Walk-through: attacks with no DETECTS cell in this half (`walkthrough.<attack|param>`)

INTERPRETATION. **The headline null.** These attack x parameter combinations have no DETECTS cell for any content or
accounting detector in any unit:
- sub_single_flip_error;
- sub_single_digit;
- sub_matched_bytes (any, samecmd);
- rewrite_consistent_k (2, 5);
- reorder_adjacent_pairs;
- reorder_lines;
- delete_pair;
- insert_pair_consistent;
- insert_pair_squeezed.

Every one of them **walks through this half of the battery untouched** at the DETECTS level. The best each manages is
PARTIAL:

- **R4_DUAL on substitution, rewrite and pair reorder (swechat/claude_code).** Recall reaches at most 230/500 = 0.460
  [0.417, 0.504] (B, rewrite_consistent_k 5). R4 cannot see count-preserving edits:
  - sub_single_digit: 0/500 on B;
  - reorder_lines: 0/500 on B.
- **P3_ZERO on sub_single_flip_error**, against a zero honest rate:
  - swechat/claude_code B 12/500 = 0.024 and E 8/500 = 0.016;
  - aiv_cu B 41/249 and E 37/240.
- **N5a and P2_KFN on inserted pairs in opencode.** The counts are small, for example opencode E P2_KFN
  insert_pair_squeezed 24/156 = 0.154 against FPR hi 0.073.
- **N5d on aiv_cu rewrite_consistent_k 5** is PARTIAL against a high honest rate:
  - B 228/500, FPR 172/500;
  - E 221/500, FPR 169/500.

The N5 sort, truncation, whitespace and error-fidelity checks (N5b, N5c, N5d, N5f) never exceed PARTIAL on any
substitution attack. In swechat/claude_code their recall equals or nearly equals their honest FPR. The attacks pick a
random result, so they rarely hit the few outputs those checkers can decide. For example, N5b reorder_lines in
swechat/claude_code B: 65/500 against FPR 56/500.

The attacks that do reach DETECTS somewhere in this half:
- delete_response (R5);
- inline_fabrication (R5, N2);
- image_relabel_gui (R2);
- image_insert_screenshot (R2).

The full walk-through needs the timing half merged with this one.

## 4. A caveat on the substitution attacks: many matched-bytes donors are exact copies

`diagnostics_noop_substitution.by_unit.<unit>.<split>.<attack|param>` is descriptive and not a verdict input. It replays
the cells' seeded draws and counts tampered copies whose replaced texts are all identical to the originals. The
pre-registered donor is the nearest-bytes **real** result, and that donor is often byte-identical:

- **sub_matched_bytes samecmd** is a no-op in:
  - swechat/claude_code B 214/500 = 0.428 and E 230/500 = 0.46;
  - opencode B 140/184 and E 119/170;
  - cc_local B 99/144.
- **sub_matched_bytes any** is a no-op in:
  - swechat/claude_code B 57/500 and E 50/500;
  - opencode B 100/211;
  - cc_local B 82/174.
- **sub_single_flip_error** is never a no-op: 0/500 in swechat/claude_code B and E.

INTERPRETATION. Recall in these cells is diluted by tampered copies that changed nothing. They are still the
pre-registered attack: an attacker who substitutes a real same-size result often substitutes an identical one. Do not
read the samecmd BLIND cells as evidence about substitutions that do change the content. No cell was recomputed
without the no-ops: that would be a post-hoc subset.

## 5. Deviations (`deviations`, 12 entries; summary)

1. **Output naming.** This half writes `n7_content.json` and shards, not `n7_attacks.json`. No effect.
2. **Probe 4 is NOT_RUN.** There is no pre-registered N7 detector for it.
3. **rewrite_consistent_k error fields.** Replaced results take the donor's error flag (the attack fields declare
   `error`; the frozen injector replaces the text only). This affects the P2/P3/N5f rewrite cells.
4. **Donor usage stripped on inserts.** Inserted donor calls lose `extra.usage_detail`. The frozen injector copies it,
   which would make R2 detect the donor session's cumulative IMAGE count instead of the missing screenshot. This affects
   R2 on the insert attacks.
5. **Thread fields of inserted pairs.** Inserted pairs take the anchor's thread fields (is_subagent, agent_id,
   parent_call_id).
6. **Per-detector session populations.** Each detector draws from its own population in the same seeded order:
   - R2: aiv_cu Gemini strata;
   - N2 on aiv_cu: GRANULAR strata;
   - P3 on whowhen: the Algorithm-Generated stratum.
7. **FPR denominator.** It includes abstaining sessions, the same as recall.
8. **ADR confidence interval.** It comes from the vectorised session bootstrap (`stats.cluster_rate`, same seed and
   draw count).
9. **R5_LEDGER.** It is implemented for the Claude format only: the committed Phase C F0 recount and `_match()`,
   with the tally gated on session_logs token_usage and api_call_count 0 abstaining. A tamper reaches the recount
   through record uuids. Other swechat formats are NOT_RUN.
10. **R4_DUAL.** The visible line count uses the IR text with the A6-O1 regex. Inserted pairs carry no counter and
    abstain.
11. **P2_KFN decision units.** They span all threads (main and subagent).
12. **P2_KFN localization on cc_local** is not computed, because of the privacy guard in Probe 2's debug hook.

Implementation choices are listed under `implementation`. Missing stamps are passed to the frozen injectors as None,
not pd.NA (pandas 3 string dtype).

## 6. What could not be measured, and why

- **Probe 4**: no pre-registered N7 detector (NOT_RUN).
- **R5_LEDGER for swechat/codex, opencode, gemini and cursor**: NOT_RUN. The X0/O0/G0 recounts were not implemented in
  this item.
- **R5 for cc_local, aiv_cc, aiv_cu and whowhen**: NOT_TESTABLE (no external usage tally).
- **delete_response outside the Claude Code formats**: no request ids, so 0 eligible sessions and INSUFFICIENT_N
  (`units.<unit>.<split>.attack_eligibility["delete_response|-"]`).
- **rewrite_consistent_k on whowhen**: no stamps, so 0 eligible. The frozen injector needs call and result stamps.
- **sub_single_flip_error on whowhen** leaves the result an error: whowhen's error class is the exit code, which the
  frozen injector does not touch. The few whowhen flip cells therefore test no flip.
- **N5c cc_lines_tail**: NOT_RUN (n_A 4 < 5). N5c runs only on cc_chars_mid and cc_glob_cap.
- **N5f** has almost no decision units: 3 deciding sessions in swechat/claude_code B and 3 in E. Every N5f cell has
  0 flagged tampered sessions (BLIND or INSUFFICIENT_N). This is a coverage null, not a fidelity null, as the
  pre-registration announced.
- **swechat/gemini and swechat/cursor**: fewer than 30 sessions per split. Every cell there is INSUFFICIENT_N.
- **Localization**:
  - null for delete attacks, because the tampered unit no longer exists;
  - null for P2_KFN on cc_local;
  - trivially 1 for session-level detectors (P3_ZERO, R5_LEDGER).

## 7. Reproducibility

- **One script revision.** All 15 cell shards and 15 no-op diagnostic shards were produced by one run of the final
  script: `all_shards_same_script` is true, and every shard's `script_sha256_lf` equals the merged file's.
- **The first run reproduces.** A superseded first run of the same cell code (kept outside the repo) was compared cell
  by cell (`reproduction_check`). In every one of the 15 unit x split shards, `cells_identical` equals
  `cells_compared`, and `honest_population_identical` is true.
