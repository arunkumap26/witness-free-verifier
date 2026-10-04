# Phase E new corpora, group pubcc: pub_cc_hf and pub_trace_commons

**INTERPRETATION.** This note interprets two output files:
- `analysis/out/phase_e/newcorp_measure_pub_cc_hf.json`
- `analysis/out/phase_e/newcorp_measure_pub_trace_commons.json`

Both were written by `analysis/probes/phase_e_newcorp_pubcc.py`, which ran `check_frozen()` first. The pre-registration
is `PREREG_E.md` and `prereg_e.json`, including the change_log extension records for both corpora and decisions D1 to
D7 (commit 669124a). Every number below is in those JSONs. Bracketed paths point into them. Rates are k/n. CIs are
session-clustered unless marked W (Wilson).

## What ran

- **B and E caches.** Built with the corpus loaders' `--split` path, with no change to the loaders. The D5 exclusion
  list names no session of these corpora, so 0 were excluded [`exclusions_D5`].

  | corpus | B sessions | E sessions |
  |---|---|---|
  | pub_cc_hf | 43 | 43 |
  | pub_trace_commons | 7 | 7 |

  Loader reports: `newcorp_build_<corpus>_{B,E}.json`. The re-scan for unredacted secrets found 0 matches. 72
  redactions were applied in pub_cc_hf and 0 in pub_trace_commons. Counts only.
- **D1.** Every unit-dispatching frozen function received the unit argument `cc_local`.
- **Thresholds.** They come from the corpus's own A calibration file, resolved with the Phase B rules
  [`thresholds_from_A`]:
  - pub_cc_hf: G90 76.5, L75 111, D_unit 4.
  - pub_trace_commons: G90 80.4, L75 251, D_unit 6 (pooled fallback).
  - Both: pooled N1 bounds.
- **D2.** The AC4 and strata cluster is the stratum: repo for pub_cc_hf, modal model for pub_trace_commons. The model
  and single-session axes are kept as well.
- **D6.** R1, P1 and N3 are labelled NOT_BLIND.
- **Cells.** 23 per corpus [`cells`].

## Bottom line

1. **R1 request-id bracket, pub_cc_hf: no honest failures.**
   - B: 0 of 45 streams inconsistent (37 sessions), W hi 0.079.
   - E: 0 of 37 streams (37 sessions), W hi 0.094.
   - B ∪ E: 0 of 82 streams (74 sessions), W hi 0.045.

   With 0 failures there is nothing for the benign categories to explain, and no correction was adopted. Because
   these cells are NOT_BLIND, this is a replication under frozen thresholds, not a held-out confirmation.
2. **R1 label for pub_cc_hf: WEAK (DOMINATED). The underlying split verdicts are ALIVE on B and on E.**
   - The kill rule passes. The 30 s back-date flags 76/82 streams, CI lo 0.867, against an honest bar of 0.045.
   - Several non-back-dating types also clear the bar, so R1 is not "back-dating only".
   - The N7 leg on E is DETECTS.
   - The one downgrade is the AC4 model leave-out: claude-fable-5 holds 0.63 of the streams. Leaving it out leaves
     30 streams with 0 failures. The zero-count Wilson hi is then 0.1135, above the 0.10 ALIVE bar.
   - **This is a small-n downgrade, not an observed failure.**
3. **pub_trace_commons is INSUFFICIENT_N almost everywhere.** It has 7 + 7 sessions. R1 has 0 of 14 honest streams
   inconsistent, against a minimum of 30 streams.
4. **Other pub_cc_hf cells.**

   | label | cells |
   |---|---|
   | WEAK | P1, N2, N5e |
   | DEAD | P2 (instrument suspect), P3b, N3 |
   | INSUFFICIENT_N | P3a, P4a, P4b, N1, N4, N5a, N5b, N5c, N5d, N5f, N5g, R4 |
   | NOT_TESTABLE | R2, R3, R5 (missing fields) |

## 1. R1 request-id bracket and F1 [`r1`]

### 1a. Honest streams

Streams have ≥ 2 decoded responses. The tolerance is the frozen 2,000 ms.

| corpus / split | streams | sessions | inconsistent | W hi | consistent slack U − L, p50 |
|---|---|---|---|---|---|
| pub_cc_hf B | 45 (37 main) | 37 | 0 | 0.079 | 2,283 ms |
| pub_cc_hf E | 37 (37 main) | 37 | 0 | 0.094 | 3,760 ms |
| pub_cc_hf B ∪ E | 82 | 74 | 0 | 0.045 | — |
| pub_trace_commons B | 7 | 7 | 0 | 0.354 | 1,880 ms |
| pub_trace_commons E | 7 | 7 | 0 | 0.354 | 1,926 ms |

- **Tolerance sensitivity.** In pub_cc_hf B, 2 streams have a gap > 0 ms (the largest is 368 ms) and none exceeds
  1 s. E has none above 0 ms [`r1.splits.*.honest.tolerance_sensitivity_streams_over`].
- **A context.** The A split had 0 of 62 streams inconsistent (`prereg_e_calibration_pub_cc_hf.json bracket`).
- **Comparison with swechat/claude_code** (Track A, `f1_bracket.json`). It had 10/3,676 on B and 11/3,332 on E, about
  0.3%. Zero of 82 here is consistent with a rate of that size: expected failures ≈ 0.25. It is no evidence of a lower
  rate.
- **`<synthetic>` sensitivity.** Entries with model `<synthetic>` carry request ids: 15 in B and 7 in E. Dropping them
  leaves 0 inconsistent [`synthetic_sensitivity`].
- **Copied ids.** No request id appears in more than one session of B ∪ E [`copied_ids`].

### 1b. Benign categories, corrections and FP_eff [`benign`, `corrections_single`, `f1_effective_fp`]

- **No inconsistent stream exists in either corpus.** The category table is empty, so no shared benign cause can be
  tested. That is a null of coverage, not a finding about causes.
- **No correction was adopted.** None of the nine single corrections lowers an honest count that is already 0.
- **FP_eff on E is 0/37 streams.** Under no corrections the placebo power on E is 4/37 at 5 s and 34/37 at 30 s.
- **Posthoc descriptors** (Track A's post hoc rule, unchanged): nothing to classify.
- **Ordered-inputs recompute:** 0 results dropped.

### 1c. Placebo [`placebo`]

| corpus / split | 5 s back | 30 s back | 5 / 30 / 300 s later | roll_ids |
|---|---|---|---|---|
| pub_cc_hf B | 7/45 | 42/45 | 0 / 0 / 0 | 45/45 |
| pub_cc_hf E | 4/37 | 34/37 | 0 / 0 / 0 | 37/37 |
| pub_cc_hf B ∪ E | 11/82 = 0.134 [0.041, 0.233] | 76/82 = 0.927 [0.867, 0.973] | 0 / 0 / 0 | 82/82 |
| pub_trace_commons B ∪ E | 6/14 | 13/14 | 0 / 0 / 0 | 14/14 |

- **5 s power is lower than on swechat** (0.39 there). This is consistent with the wider consistent-stream slack here:
  p50 2.3 s on B and 3.8 s on E, against 2.27 s on swechat.
- **Step 0 does not apply.** It is defined on swechat/claude_code B, where Track A found it REPRODUCED.

### 1d. Kill rule and N7 leg

**Stream level** (B ∪ E; honest bar 0.045) [`pooled_BuE.tamper_stream_level`]:
- 30 s back-dating clears.
- 5 s back-dating does not: 10/82, CI lo 0.041.
- These clear: id_swap_adjacent 82/82, id_splice nearest 75/82, id_splice random 41/82, time_result_late from 5 s,
  time_tail_late / time_tail_early from 5 s, and insert_pair consistent 33/82 and squeezed 28/81.
- Blind: forward-dating, early results, delete_response, delete_pair, and every shift of 2 s or less.
- Back-date grid (time_response_early): power reaches 0.5 at 10 s and 0.9 at 30 s, as on swechat.

**Session-level N7 for R1_BRACKET** [`splits.*.n7_r1_session_level`]:
- Both B and E have 37 to 43 tampered sessions per cell, and FPR is 0 on the same sessions.
- **E leg: DETECTS.** These single-call types DETECT: time_response_early (from 10 s), time_result_late (from 10 s),
  id_swap_adjacent (37/37) and id_splice_foreign nearest (35/38).
- PARTIAL: insert_pair_* and random splice.
- pub_trace_commons: every N7 cell is INSUFFICIENT_N (7 sessions).

### 1e. Artifact checks and strata (B ∪ E) [`pooled_BuE.artifact_checks`, `pooled_BuE.strata`]

| check | result |
|---|---|
| AC2 truncation | PASS |
| AC3 join | PASS |
| AC5 | NOT_RUN: no population table for new corpora |
| AC1 parser | NOT_RUN: no numerator events to audit |
| AC1 extension (not pre-registered, no verdict effect) | 30 B and 30 E denominator streams match the raw JSONL on binding stamps and request ids, 0 differences; pub_trace_commons 7 + 7, 0 differences |
| AC4, stratum (repo) | dominated (top 0.30); every leave-out stays ALIVE |
| AC4, single session | dominated (0.110 > 0.10); every leave-out stays ALIVE |
| AC4, model | dominated (claude-fable-5 0.63). Leaving it out gives 0/30 streams, W hi 0.1135, which is WEAK. **One-level downgrade.** |
| Strata | Only one reportable stratum per axis (model: claude-fable-5; length: mid), so confinement is UNTESTABLE |

**Reading.** The DOMINATED downgrade comes from the ALIVE bar on a zero count at n = 30, not from any failure in the
other models. It would lift with about 7 more consistent non-fable streams; this is arithmetic, not a measurement. The
cell stays WEAK, per the rule.

## 2. Other mechanisms, pub_cc_hf [`cells`, `p1` … `r4`]

The cell shows E, or B with "B only" where E is INSUFFICIENT_N; B ∪ E is stored beside it.

| mechanism | B | E | B ∪ E | deciding numbers on E |
|---|---|---|---|---|
| P1 latency (NOT_BLIND) | WEAK | WEAK | WEAK | fp 0/144 (W hi 0.026); AUC 1.000 [1.000, 1.000] over 67 G pairs; downgraded by FLOOR_SHIFT on read |
| P2 knowledge, main | DEAD | DEAD | DEAD | S_deep below min n (35 from 8 s); fallback S_path_any 443/746 = 0.594, CI hi 0.700; matching instrument suspect |
| P2, subagent | INSUFFICIENT_N | INSUFFICIENT_N | INSUFFICIENT_N | — |
| P3a zero-error tail | INSUFFICIENT_N | INSUFFICIENT_N | INSUFFICIENT_N | n_long 4 at L75 = 111 (needs 20); 0 zero-error long sessions |
| P3b reaction | DEAD | DEAD | DEAD | effect 0.118, CI [−0.034, 0.248]; 66 failed calls with successor from 21 s |
| P4a hex | INSUFFICIENT_N | INSUFFICIENT_N | INSUFFICIENT_N | T_orig 16 symbols (B: 104), N_min 1,131 |
| P4b round numbers | INSUFFICIENT_N | INSUFFICIENT_N | ALIVE | E: 39 distinct T_orig values, needs 100 |
| N1 conditional duration | INSUFFICIENT_N | INSUFFICIENT_N | INSUFFICIENT_N | shell RR 13/417; 11 residuals from 5 s (needs 200 from 20) |
| N2 token accounting | WEAK | WEAK | WEAK | honest flag 45/361 = 0.125 [0.083, 0.166]; recall at 0.8τ 0.992; τ_A 0.668 |
| N3 reaction time (NOT_BLIND) | DEAD | DEAD | DEAD | pooled ρ 0.059 [−0.034, 0.165]; 21 sessions with ≥ 20 gaps; ρ_s ≤ 0 in 9/21 |
| N4 concurrency | INSUFFICIENT_N | INSUFFICIENT_N | INSUFFICIENT_N | 0 W pairs at k ≥ 2 |
| N5a determinism | INSUFFICIENT_N | INSUFFICIENT_N | INSUFFICIENT_N | 1 pair |
| N5b sort | INSUFFICIENT_N | INSUFFICIENT_N | INSUFFICIENT_N | largest checker: grep -n, 49 outputs from 15 s (B: 59 from 9 s); min 100 from 20 s |
| N5c truncation | INSUFFICIENT_N | INSUFFICIENT_N | INSUFFICIENT_N | 1 elision on E, 0 on B |
| N5d whitespace | INSUFFICIENT_N | INSUFFICIENT_N | INSUFFICIENT_N | largest checker on E: pytest banner 20 from 11 s; on B: 97 from 6 s |
| N5e size distribution | DEAD | WEAK | WEAK | 2/2 qualifying families (cd, grep) have IQR above the comparator CI hi 0.931; B has 0/1 |
| N5f error fidelity | INSUFFICIENT_N | INSUFFICIENT_N | INSUFFICIENT_N | 0 checkable frames (66 error results) |
| N5g cold start | INSUFFICIENT_N | INSUFFICIENT_N | DEAD | 21 eligible sessions on E (needs 30) |
| R4 dual-rendering | INSUFFICIENT_N | INSUFFICIENT_N | (honest leg ALIVE) | 24 decided sessions on E; 0 unexplained mismatches |
| R2 image, R3 git, R5 ledger | NOT_TESTABLE | — | — | field gate on A, re-checked on B [`field_gate_B`] |

### Notes on the pub_cc_hf cells

- **P1.** The fp_share and AUC legs are both ALIVE on B, E and B ∪ E.
  - The WEAK label comes from the pre-registered downgrade. The read tool's A floor is p5 = 0.001 s, which equals the
    1 ms stamp resolution, so no B or E pair can fall below it, and the floor is labelled FLOOR_SHIFT ("B floor
    higher").
  - On B, 1 of 2 eligible floor-step series also steps (UNSTABLE).
  - The Phase B descriptive sensitivity that excludes A floors at stamp resolution shows no shift
    [`p1.*.floor_transfer.sensitivity_excluding_A_p5_at_stamp_resolution`]. The verdict uses the pre-registered set.
- **P2.** The instrument check is re-run on this corpus's own main-thread S_symbol_ref and fails: 0.226 (B) and
  0.282 (E), against T_INSTRUMENT 0.10.
  - The label therefore carries "matching instrument suspect".
  - The Phase B post hoc descriptor (no verdict effect) shows the path signal is dominated by creation targets: 97/99
    are unsourced on E. It also shows 63% unsourced free paths.
  - This looks like an incomplete antecedent record (for example, attachments the model saw but the IR keeps as meta),
    not honest agents guessing paths. That is my reading, not a tested claim.
  - pub_cc_hf is not on the prereg's antecedents_incomplete list, so the DEAD is not converted to INCONCLUSIVE.
- **N2.** WEAK because the honest flag rate (0.125 on E, 0.198 on B) is above 0.05. The synthetic inline-fabrication
  recall is about 0.99.
  - The checks on B ∪ E all pass: AC2, AC3, the AC4 leave-outs (stratum, model, session) and strata (model: OK).
  - The prereg names hidden output absorbed by τ as an expected honest false-positive source. It is measured here, not
    corrected.
- **N5e.** Capped at WEAK by design. B is DEAD with one qualifying family. The B ∪ E checks pass.
- **R4.**
  - B ∪ E has 513 decided Read results in 51 sessions with 0 unexplained mismatches. The 13 raw-vs-visible
    mismatches are all whitelisted: 8 shorter-than-offset and 5 redaction. The 5 redaction cases include the loaders'
    own `<REDACTED:...>` markers.
  - B and E alone have fewer than 30 decided sessions, so the cell is INSUFFICIENT_N.
  - The R4 N7 leg was not run here, so even the B ∪ E honest leg cannot become a verdict.
  - The `cc_local` empty-file whitelist class (D1) excuses 0 additional units.

## 3. pub_trace_commons (7 + 7 sessions)

Every cell is INSUFFICIENT_N on B and on E except R2, R3 and R5, which are NOT_TESTABLE. B ∪ E context (no cell
effect):

| item | B ∪ E context |
|---|---|
| R1 | honest 0/14; 30 s back-date 13/14 |
| P1 | WEAK: fp 0/373; AUC not computable, G 23 < 30 |
| N2 | WEAK: honest flag 0.082 over 428 responses from 14 sessions; recall 0.97 |
| P3b | DEAD: effect 0.047 [−0.019, 0.106] |

The corpus can carry descriptive context only.

## 4. Nulls, stated plainly

- **R1 benign-cause analysis.** No honest inconsistent stream exists in either corpus, so there is nothing to explain.
  The "shared benign cause" question cannot be answered on these corpora.
- **INSUFFICIENT_N cells.**
  - pub_cc_hf: 12 of 23.
  - pub_trace_commons: 20 of 23.
- **Announced nulls that held.**
  - N4: 0 qualified W pairs at k ≥ 2.
  - N5f: 0 checkable frames.
  - N5c tail cut: NOT_RUN by the prereg.
  - git log sort: 0 outputs.

## Deviations and implementation choices (fixed before the B/E run; listed in the script docstring)

- **Where a cell is INSUFFICIENT_N on both B and E, its JSON `deciding_number` holds the B values.** The fill rule
  falls back to B. The E values quoted above are under `p4.E`, `n5.E`, and so on.

- **Probes 1–4 implementation.** Probes 1–4 run the committed Phase B code with unit `cc_local`. For the duration of
  each call, that module's `cc_local` threshold entries are swapped for this corpus's A values. No file is edited.
- **P4.** probe_4 runs with private=True, so no token values are written.
- **R1 code.**
  - Ported (copied) from Track A's uncommitted `phase_e_f1_bracket.py`, so this output does not depend on that file.
  - The R1 N7 leg is computed here at session level for the R1 detector.
  - The pooled B ∪ E artifact-check effects are applied to the shown split label.
- **Not run.**
  - AC1 for non-R1 cells.
  - The R4 N7 leg.
  - The N4 Δ statistic (min n not met anyway).
  - F3 parameter exclusion for P4b (an A1-candidate rule; P4b is INSUFFICIENT_N per split).
- **Track A conventions.**
  - N5e follows Track A's convention (session-bootstrap comparator CI; comparator ≥ 30 texts from 5 s).
  - The N3 cell uses no usage-adjusted secondary.
