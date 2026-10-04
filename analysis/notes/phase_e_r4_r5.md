# Phase E, A1 second pass: R4 dual-rendering recount and R5 usage-ledger reconciliation (item r4_r5)

- Script: `analysis/probes/phase_e_r4_r5.py`. Run it from the worktree root with
  `PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_r4_r5 --workers 8`. One run takes about a minute; the actual
  time is in `runtime_s`.
- Output: `analysis/out/phase_e/r4_r5.json`, raw numbers only. Every number in this note comes from that file, and the
  JSON path is given beside each one. A second run to scratch produced an identical file apart from `runtime_s`.
- Pre-registration: `prereg_e.json a1.proposal_rules` (R4_specific, R5_specific), `artifact_checks`, `stratification`
  and `survival_rule`. `check_frozen()` passed (`spec_module_sha256_lf == spec_module_sha256_lf_prereg`). No threshold was
  set or changed here.
- The N7 recall leg is not recomputed here. It is read from the N7 content item's shards
  (`analysis/out/phase_e/n7_content_shards/{swechat__claude_code,cc_local}_{B,E}.json`). The shard sha256 and the
  prereg sha match are recorded under `R4|R5.units.<unit>.n7_meta`.
- Labels: R4 and R5 on swechat are "E not blind", because Phase C read the whole swechat population. cc_local is B only,
  unreplicated, private, and reported as aggregates only.

## 1. Mechanical results (from the JSON)

`verdicts[]`, 22 cells (`n_verdict_cells`).

| Candidate / unit | B | E | B ∪ E | Survival (final label) |
|---|---|---|---|---|
| R4 swechat/claude_code | WEAK | WEAK | WEAK | **SURVIVES (E not blind), WEAK** |
| R4 cc_local | WEAK | — | — | **SURVIVES (B only, unreplicated), WEAK** |
| R5 swechat/claude_code | ALIVE | ALIVE | ALIVE | **SURVIVES (E not blind), ALIVE** |
| R5 swechat/codex | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN: no N7 R5 cells for this unit |
| R5 swechat/opencode | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN: no N7 R5 cells |
| R5 swechat/gemini | INSUFFICIENT_N | INSUFFICIENT_N | NOT_RUN | NOT_RUN (NOT_REPLICABLE_AT_N) |

No kill test fired. No artifact check lowered any label.

### R4 dual-rendering recount, swechat/claude_code (`R4.units.swechat/claude_code`)

**Raw join** (`raw_join_coverage`):
- B: 1,679 sessions; 1,554 carry raw `numLines`; 30,011 counters.
- E: 1,546 sessions; 1,444 carry raw `numLines`; 28,198 counters.
- Every counter joined to an IR result: 0 without one in B and in E.
- Raw parse: 0 bad JSON lines and 0 duplicate tool_use ids in either split.
- Decision units are all `Read` results: 58,209 (`decision_unit_tools`).

**Honest flag rate (session level), the null that matters most here** (`verdict_blocks`):

| Split | Flagged / deciding sessions | Rate [95% CI] | Unexplained units |
|---|---|---|---|
| B | 0/1,554 | [0, 0.0025] | 0 of 30,011 |
| E | 0/1,444 | [0, 0.0027] | 0 of 28,198 |
| B ∪ E | 0/2,998 | [0, 0.0013] | 0 |

**Whitelist coverage** (`whitelist_coverage_ir_BuE`):
- Visible numbered-line count differs from `numLines` in 287/58,209 = 0.0049 [0.0044, 0.0055] results, across 187
  sessions.
- The frozen whitelist excuses all 287:

  | Whitelist class | Mismatches |
  |---|---|
  | persisted-output | 203 |
  | shorter-than-offset | 75 |
  | identical/unchanged reference | 5 |
  | redaction | 3 |
  | negative line number | 1 |

- 2,011 of 58,209 units match a whitelist class whether or not their counts differ: redaction 1,506, persisted 204,
  identical 157, shorter-than-offset 143, negative line 1 (`all_units_matching_a_whitelist_class`).
- Raw-side text gives the identical table (`whitelist_coverage_raw_BuE`).
- Phase C reference, copied into `phase_c_references.dual_population`: 87,827/88,229 agree over the whole population.

**N7 leg on E** (`n7_meta.E.cells_detail`; 500 tampered sessions per cell; honest FPR 0/500 [0, 0.0076] in every cell):
- No single-call attack type DETECTS.
- PARTIAL:

  | Attack | Detected / tampered | Recall [95% CI] |
  |---|---|---|
  | rewrite_consistent_k=5 | 205/500 | 0.41 [0.368, 0.454] |
  | rewrite_consistent_k=2 | 154/500 | 0.308 |
  | reorder_adjacent_pairs | 147/500 | 0.294 |
  | sub_matched_bytes any | 76/500 | 0.152 |
  | sub_matched_bytes samecmd | 26/500 | 0.052 |

- **BLIND (0/500 each): sub_single_flip_error, sub_single_digit, reorder_lines, delete_pair, delete_response,
  insert_pair_consistent, insert_pair_squeezed.**
- B cells give the same labels (e.g. rewrite k=5 230/500 = 0.46 [0.417, 0.504]).
- The verdict is therefore WEAK in every split: the honest leg is ALIVE but the N7 leg is WEAK.

**Artifact checks on B ∪ E** (`artifact_checks`):
- **AC1:** 0 flagged units, so 0 were audited.
  - Supplementary audit of 30 decision units (a deviation): 0 contribution changes, PASS.
  - Full IR-vs-raw parity over all 58,209 units: 0 flag, line-count, length or whitelist differences.
- **AC2:** 206 truncated units dropped; label WEAK, unchanged.
- **AC3:** 360 non-clean units dropped (1,843 copied call ids considered); label WEAK, unchanged.
- **AC4:** model and user are both dominated; every leave-out stays WEAK; result PASS.
  - Model: the top share is 0.775.
  - User: the top cluster is the unknown user, at 0.339.
  - Repo: 0.181, not dominated.
- **AC5:** weighted rate 0.0; label WEAK; no SHIFT.

**Strata** (`stratification`):

| Axis | Result |
|---|---|
| tool | UNTESTABLE (one stratum, read) |
| model | OK, 5 reportable strata |
| repo | OK, 22 reportable strata |
| length | OK, 3 reportable strata |

### R4 cc_local, B only (`R4.units.cc_local`; aggregates only)

- **Raw join:** 186 B sessions, 110 with `numLines`, 365 counters, all joined.
- **Honest:** 0/110 sessions [0, 0.0337], 0/365 units.
- **Mismatches:** 2/365, both empty-file warnings, which the whitelist excuses.
- **N7 B:**
  - PARTIAL: reorder_adjacent_pairs 30/139 = 0.216, rewrite k=5 13/120 = 0.108.
  - sub_single_flip_error is INSUFFICIENT_N (29 tampered).
  - The other 9 cells are BLIND.
- **Label:** WEAK.
- **AC4:** one project alias holds all 110 deciding sessions, so the leave-out is INSUFFICIENT_N. The result is
  UNTESTABLE_WITHOUT_DOMINANT, which caps the label at WEAK. That has no effect, because the label is already WEAK.
- **AC5:** NOT_RUN (no population table).

### R5 usage ledger, swechat/claude_code (`R5.units.swechat/claude_code`)

**Gate** (`R5.gate_counts`):
- B: 1,645 decided; 31 sessions without a session_logs token_usage; 3 with api_call_count 0.
- E: 1,520 decided; 23 without token_usage; 3 with api_call_count 0.

**Honest flag rate** (tally from sessions.parquet, as pre-registered):

| Split | Flagged / decided sessions | Rate [95% CI] |
|---|---|---|
| B | 13/1,645 | 0.0079 [0.0046, 0.0135] |
| E | 10/1,520 | 0.0066 [0.0036, 0.0121] |
| B ∪ E | 23/3,165 | 0.0073 [0.0048, 0.0109] |

These equal the N7 shards' honest_population counts (13/1,645 B and 10/1,520 E), which come from an independent
implementation.

**N7 leg on E** (honest FPR 4/500 = 0.008 [0.0031, 0.0204]):

| Attack | Detected / tampered | Recall [95% CI] | Label |
|---|---|---|---|
| delete_response | 396/500 | 0.792 [0.754, 0.825] | DETECTS |
| inline_fabrication | 374/500 | 0.748 [0.708, 0.784] | DETECTS |
| delete_pair | 219/500 | 0.438 | PARTIAL |
| insert_pair_consistent | 4/500 (same as honest) | — | **BLIND** |
| insert_pair_squeezed | 4/500 (same as honest) | — | **BLIND** |

The B cells give the same labels. The verdict is ALIVE in B, E and B ∪ E.

**Artifact checks:**
- **AC1:** all 23 flagged sessions were re-read by an independent parser and matcher; 0 contribution changes; PASS.
- **AC2:** not applicable.
- **AC3** (session-level clean join; a deviation): 54 sessions dropped; 8/3,111 = 0.0026 [0.0013, 0.0051]; ALIVE.
- **AC4:** user and model are dominated; every leave-out stays ALIVE; PASS.
  - User: the top cluster is the unknown user, at 0.334.
  - Model: 0.784.
  - Repo: 0.165, not dominated.
- **AC5:** weighted rate 0.0072 [0.0047, 0.0101]; ALIVE; no SHIFT.

**Strata:**
- model, repo and length are all OK, with no confinement.
- Flags sit mostly in the long tercile: long 19/999, mid 3/1,097, short 1/1,069.
- claude-opus-4-6 holds 20/2,481.

**Descriptive** (`descriptive.BuE`, `join_fix_variant`):
- In 18 sessions the sessions.parquet tally differs from session_logs. 14 of those 18 are flagged. Re-run with the
  session_logs tally, the flagged sessions classify as prefix 10, full 4 and none 9.
- Join-fix variant: 9/3,165 = 0.0028 [0.0015, 0.0054]. This is reported, not a verdict.
- Output-only mismatches: 6 of the 23 flagged sessions.
- By CLI minor version: 0.5 has 8/583 = 0.0137; 0.4 has 11/2,026 = 0.0054.
- Phase C reference (`phase_c_references.ledger_unmatched`): 33/5,701.

### R5 on the other swechat formats (honest leg only; the N7 leg is NOT_RUN)

| Unit | Flagged / decided (B ∪ E) | Rate [95% CI] | E alone | Join-fix variant |
|---|---|---|---|---|
| codex | 4/126 | 0.0317 [0.0124, 0.0788] | 3/58 = 0.0517 [0.0177, 0.1414] | 3/126 |
| opencode | 4/405 | 0.0099 [0.0038, 0.0251] | — | 3/405 |
| gemini | 6/34 | 0.1765 [0.0835, 0.3351] | 2/13, INSUFFICIENT_N | 6/34 |

Pooled over the four formats (descriptive): 37/3,730 = 0.0099 [0.0072, 0.0136]. With the join-fix tally:
21/3,730 = 0.0056 [0.0037, 0.0086].

## 2. Nulls (as prominent as the hits)

- **R4 cannot reach ALIVE.** Out of 12 applicable N7 attack types, no single-call type DETECTS on E.
  - 7 are BLIND at 0/500. These include every count-preserving edit: single digit, error flip and line reorder.
  - Deleting or inserting a whole call/result pair is also BLIND, because the deleted or inserted pair carries no
    counter.
  - The best cell, rewrite_consistent_k=5, has recall 0.41 on E.
- **R5 is blind to inserted pairs.** On insert_pair_consistent and insert_pair_squeezed, recall equals the honest rate
  (4/500).
- **R5 is blind to tool-result content.** No content-edit attack is applicable to the ledger (prereg applicability
  matrix).
- **R5 has no verdict for codex, opencode or gemini (NOT_RUN).** These cells are not nulls.
- **gemini cannot replicate on E** (13 decided sessions). Its honest rate is the highest of the four formats: 6/34 on
  B ∪ E.
- **cc_local R4 is untestable for dominance.** One project alias holds every deciding session.

## 3. INTERPRETATION (not data)

- **R4 is a near-perfect honest-side instrument with weak attack coverage.**
  - Across 58,209 Read results, the frozen whitelist written before Phase E data explains every one of the 287
    harness mismatches. This holds on E, which Phase C read but never used to build the whitelist; the whitelist
    regexes were frozen in the prereg.
  - Fabrication detection is limited to edits that change a Read result's line count. The same harness writes both
    renderings, so a count-preserving edit is invisible by construction, and N7 confirms it at 0/500.
  - A caution about the whitelist: 2,011 of 58,209 results already match a whitelist regex. Most of them are
    dataset redactions (1,506). Any count mismatch on those results is excused, so the whitelist is a ready evasion
    route for an editor who adds a whitelist marker.
- **R5 survives as ALIVE on Claude Code**, and it is the stronger of the two.
  - The honest rate is about 0.7% at session level.
  - Two single-response attacks are detected on E at roughly 0.75 to 0.79 recall: deleting a response and inline
    fabrication.
  - Most honest flags trace to the dataset's sessions-table / session_logs join artifact (14 of 23), which Phase C
    already identified.
  - The rest cluster in long sessions (19 of the 23 flags are in the long tercile). Snapshot timing in long,
    multi-checkpoint sessions could explain this, but that explanation was not tested here. Neither is the
    concentration evidence of tampering.
  - R5 only constrains which API responses exist and what they were billed. It says nothing about what a tool
    result contained.
  - Its anchor is a recount that an editor with the transcript can redo.
- **"E not blind"** means a SURVIVES here is weaker evidence than a blind replication: Phase C observed both
  mechanisms on the whole population, including E.

## 4. Deviations (full list in `r4_r5.json deviations`)

1. Output file names: R4 and R5 share one script and one JSON under the orchestrator's item key `r4_r5`.
2. The N7 legs are read from the N7 content shards, not recomputed. A missing shard would give NOT_RUN.
3. The session-level honest rate uses deciding sessions as its denominator. This is conservative.
4. R4 AC1: the numerator is empty, so 30 decision units are audited as a supplement under the same fail rule.
5. R5 AC2 is not applicable: R5 reads no result text.
6. R5 AC3 is a session-level join check: the tally agrees across the two tables, there is one sessions row, and the
   transcript carries its own sessionId.
7. The R5 verdict uses the sessions.parquet tally as written in the prereg. The session_logs (join-fix) tally is
   descriptive only.
8. R5 for codex, opencode and gemini is NOT_RUN, because N7 cells exist only for claude_code.
9. Survival base: units with E start from the E label. cc_local starts from its B label with `has_e=False`.
10. AC1 FAIL, AC4 weights and confinement aggregation follow the sibling A1 items.
11. cc_local raw files: the snapshot directory is listed with discover(), and only the main and subagent files of B
    ids are opened.

None of these changed a verdict.

## 5. Could not measure

- **R5 N7 recall for codex, opencode and gemini.** The N7 content item implemented only the F0 (Claude Code) tamper
  propagation.
- **Phase D's extra R4 tamper plan** (add or delete 1, 2 or 5 lines; splice a same-path Read; rewrite into a
  whitelisted format) and the A6-O2 subagent `totalToolUseCount` leg. Neither is pre-registered in `R4_specific`, so
  neither was run.
- **Grep `numLines` and Edit `structuredPatch` agreement.** Not pre-registered.
- **A blind replication of R4 or R5.** It is impossible on swechat E, which Phase C had already read. The H numbers are
  not fully blind either (prereg `splits.E_freshness`).
