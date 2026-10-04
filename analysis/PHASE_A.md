# Phase A: schema reconnaissance (the gate for Phase B)

All numbers come from `analysis/out/phase_a.json`, written by `analysis/probes/phase_a_merge.py` from a1–a6,
a6_raw_census, `phase_a/resolve.json` and the verifier records. Each number sits under `headline`, `gate_rules`,
`resolutions` (cited as R:id) or `sources.<file>`. Only split A was used. Notation: k/n = rate [95% CI]; s = sessions
(for aiv_cc, runs). CIs are session-clustered bootstraps unless marked W (Wilson). **Interpretation** marks text that
is not data.

**Verification.** An independent verifier re-derived every question. All decisive counts reproduced except two A6
headline fills (aiv_cc and aiv_cu), which counted keys rather than values. `resolutions` settles 39 verifier
discrepancies; my own checks are in `analysis/probes/phase_a_resolve.py`. Two resolutions change a gate label: A2
copilot (R:A2-2) and the A4 text-proxy labels (R:A4-1). A1 and A5 verdicts are unchanged.

## Gate decisions

| Gate (pre-registered rule) | Alive | Dead or untestable |
|---|---|---|
| Probe 1 latency (A1 kill rule) | swechat claude_code (126 s), cc_local (107 s), aiv_cc (77 runs, **one agent**). Small n: codex (15 s), opencode (25 s), gemini (10 s). copilot passes the rule but has only 2 s | **aiv_cu**: call and result share one stamp in 6,107/6,107 pairs. **whowhen**: no timestamps (0 of 353 pairs stamped). **swechat cursor**: no timestamps. **swechat simple_text**: no tool pairs |
| Join completeness (A2, hi ≤ 0.01) | swechat claude_code, codex, opencode, cc_local, aiv_cc; swechat gemini once 1 session is excluded | cursor absent (no results). copilot insufficient n (R:A2-2). aiv_cu untestable, because the loader builds every pair (R:A2-5). whowhen partial |
| Error definition (A4) | Native flag: Claude Code formats, codex, opencode, gemini, copilot. Text proxy usable: swechat CC, cc_local, aiv_cc (B), codex (C) | Text proxy partial: opencode (absent on shell). Text proxy absent: gemini, copilot. aiv_cu: no flag at all. cursor and simple_text: no results |
| Token conservation (A5) | TIGHT: aiv_cc (one agent). OpenCode result-only form meets the TIGHT thresholds (its ratio is post hoc). LOOSE: swechat CC, opencode, Gemini CLI | NOT_TIGHT: codex, cc_local, every aiv_cu stratum (haiku INSUFFICIENT). No usage data: copilot, cursor, simple_text, whowhen, aiv_cu OpenAI/compat |
| Truncation (A3) | Gating needed before any claim-vs-output test: CC, codex, gemini, opencode | No marked truncation in aiv_cu or whowhen (unmarked caps are not excluded) |

## A1. Timestamp granularity: the latency gate

Kill rule: a unit is dead if its stamps are whole-second or a call and its result share a stamp (majority rule,
`gate_rules.A1_latency_kill_rule`).
- **swechat claude_code: ALIVE.** Millisecond stamps. 13,589 pairs over 126 s. Identical stamps 37/13,589 = 0.27%
  [0.13, 0.48]; whole-second stamps 26/27,178 = 0.096% [0.062, 0.131]; 0 negative deltas. Delta p50 0.101 s
  [0.069, 0.142]; main thread 0.133 s; subagents 0.048 s (3,910 pairs, 52 s).
- **codex** 0/1,120 identical (15 s). **opencode** 14/3,735 = 0.37% [0.07, 0.72] (25 s). **gemini** 0/2,313 (10 s),
  with 6 negative deltas. **copilot** 0/265 (2 s). All ALIVE, each on few sessions.
- **cc_local: ALIVE.** 0/5,164 identical; whole-second 6/10,328 = 0.058% [0.023, 0.116]; p50 0.247 s [0.102, 0.351].
- **aiv_cc: ALIVE.** Microsecond row-insert stamps. 0/33,475 identical, 0/66,950 whole-second. Every call-to-result
  delta is at least 0.046 s, even though rows can land 0.018 s apart. The floor is measured; its cause is not (R:A1-6).
  All 125 runs ran with bypassPermissions.
- **aiv_cu: KILLED.** Call and result share one stamp in 6,107/6,107 pairs, in all 10 strata. What remains is the
  inter-turn gap: p50 14.06 s [13.26, 14.92], 6,255 gaps.
- **whowhen, cursor: KILLED** (no timestamps). **simple_text: KILLED**: no pairs, and 20/20 stamps are whole-second.
- **Human waits (corrected):**
  - swechat CC: Edit/Write calls over 2 s are 296/2,235 = 13.2% [6.8, 21.7].
  - Permission-prompt rejections occur in 19/126 s = 15.1% W[9.9, 22.4], p50 23.0 s (R:A1-1). The original 34/126
    counted ExitPlanMode, AskUserQuestion and one interrupt as well.
  - Shell pre-exec offset over 2 s: 50/367 = 13.6% [5.8, 25.9]. The 6 Task calls are excluded (R:A1-3).
  - cc_local: 0/358 Edit/Write calls exceed 2 s, but 9 human-paced rejections occur in 6/107 s, p50 4.9 s.
    Permission denials there are machine-fast: 173 of them, p50 0.007 s (R:A1-2).
  - The aiv_cc claim that non-last blocks absorb later generation time is a one-session Write effect: 160/160 such
    calls come from 1 run (R:A1-5).

## A2. Join completeness (pairs on (session_id, call_id))
- swechat claude_code: 31/13,620 = 0.0023 [0.0013, 0.0036] calls have no result, but 20/127 s W[0.104, 0.231] have
  at least one. codex 2/1,122; opencode 0/3,735 (Wilson hi 0.0010); copilot 1/266 (2 s; Wilson hi 0.021, R:A2-2);
  cursor 206/206 (the format records no results).
- swechat gemini: 487/2,800, all from one session with no results; 0/2,313 elsewhere. swechat overall without the
  695 structural calls: 32/21,054 = 0.0015 [0.0008, 0.0023] (R:A2-1).
- cc_local 1/5,165; aiv_cc 4/33,479; aiv_cu 0/6,107 by construction, and 3,393/6,107 = 0.556 [0.502, 0.610] of its
  results have no text. whowhen 20/373 = 0.054 [0.030, 0.082]; excluding never-executed AG code blocks,
  8/361 = 0.022 [0.007, 0.035].
- Raw IR versus `conversations.parquet`: the table orphans 76,618/408,086 = 0.1877 of distinct results (whole-table
  census), while the raw full pass has 16 results without a call out of 633,366. **Null hidden by zero counts:** one
  salvaged, truncated OpenCode document in split A has 185 IR calls against 417 table rows. All 162 missing table ids
  come from it, and the join metrics cannot see this loss (R:A2-4).

## A3. Truncation of tool-result text
- The SWE-chat 10,256-char cap is **absent from the raw transcripts**: 0/21,025, while the table has 1,552 such rows
  and 1,395 raw results run longer than 10,256 chars.
- Any loss-type marker: swechat CC 134/13,592 = 0.99% [0.76, 1.22] (55/126 s); codex 11/1,120 = 0.98% [0.31, 2.02];
  opencode 40/3,735 = 1.07% [0.68, 1.64]; Gemini CLI `<tool_output_masked>` 840/2,313 = 36.3% [25.2, 43.2] (7/10 s;
  R:A3-1); cc_local 23/5,164 = 0.45% [0.19, 0.95] in text, 209/5,164 = 4.05% [2.02, 10.03] with the Glob flag; aiv_cc
  40/33,475 = 0.12% [0.04, 0.28] (11/77). The cc_local and aiv_cc counts include an older CC spill format the
  catalogue missed (R:A3-5). aiv_cu 0/6,107 and whowhen 0/353 (Wilson session upper bounds 1.9% and 5.7%).
- CC error truncation keeps the head, so `Exit code N` survives 15/15 (swechat, 10 s) and 15/15 (aiv_cc, 2 s). The
  like-for-like baseline on untruncated failures is 233/285 = 0.82 [0.73, 0.88] (R:A3-2). Gemini masking cannot be
  tested, because Gemini writes `Exit Code:` only for nonzero exits: 0 of 816 shell results show `Exit Code: 0`
  (R:A3-3). Persisted-output spills show a 1,833-2,282-char preview: 65 results in 36/126 swechat CC s.
- Flags versus text: the CC Glob `truncated` flag is absent on 34 of 44 text-marked swechat truncations (R:A3-4).
  In cc_local the 186 flag-true Glob results carry no catalogue marker, but a text shape separates them 186/186 vs
  0/241 (R:A3-6).

## A4. Error-signal survival and proposed Probe 3 definitions
- **swechat CC:** native filled 4,464/13,592 = 0.328 [0.285, 0.370]; null means "not flagged". `error_marker` (A):
  P 488/488 (W lo 0.992), R 488/614 = 0.795 [0.720, 0.855] (90 s).
- **cc_local:** A P 331/331, R 331/349 = 0.948 [0.900, 0.977] (74 s). 157 of the 311 native-true shell results are
  permission denials. 9 non-shell Workflow results are False (R:A4-4).
- **aiv_cc:** A R 296/538 = 0.550 [0.342, 0.791]. B (A plus census regexes): P 534/637 = 0.838 [0.736, 0.897],
  R 534/538 = 0.993 [0.977, 0.999] (38 runs). 1,746 village-bash JSON turns carry no native flag. 33,473/33,475
  results come from one SDK session (R:A4-3).
- **codex:** native plus a nonzero exit header. The header alone: P 47/47, R 47/49 = 0.959 [0.823, 1.0]. C reaches
  49/49 only by adding a timeout string. Positives come from 6 s (R:A4-2).
- **opencode:** native filled 3,735/3,735. The text proxy reaches only 26/157 = 0.166 [0.096, 0.253] of shell
  failures.
- **gemini:** A P 0/280, R 0/143. Native status and the text exit code never coincide (by loader construction).
- **copilot:** 8 native positives in 2 s. **aiv_cu:** no flag; a stderr regex proxy fires on 118/6,107 = 0.019
  [0.013, 0.026], unvalidated. **whowhen:** exit code on 87/353 (36 nonzero); 36/36 agreement is tautological.

## A5. Token accounting and conservation
- **No field counts tool-result tokens separately** in any corpus. Gemini CLI `tokens.tool` is nonzero in 0/2,505.
  The only exception is Gemini computer-use screenshots: IMAGE tokens rise in 417/420 (pro) and 191/191 (flash) gaps
  that contain a GUI result, and in 0/309 gaps without one.
- Conservation (median |cross-fit residual| relative to a typical result; pre-registered rule; `gate_rules.A5_conservation_rule`):
  - **aiv_cc TIGHT.** Spearman 0.985 [0.977, 0.988]; 66.1 tokens (random-split p50 63.8) against a 1,447.7-token
    result, ratio 0.046 [0.038, 0.054]. All 27,491 fit pairs come from one SDK session (R:A5-3). Images cost about
    913.7 tokens each [904.2, 916.7].
  - **LOOSE:** swechat CC 0.742 [0.591, 0.9996] (borderline, R:A5-4); opencode 0.470; Gemini CLI 0.517, or 0.646 at
    the random-split median (R:A5-1).
  - OpenCode result-only form: Spearman 0.951 [0.934, 0.970]; 19.3 tokens = 0.102 [0.070, 0.135]; random-split p50
    15.5 tokens.
  - **NOT_TIGHT:** codex 2.311, cc_local 1.639, aiv_cu strata (Spearman 0.407 to 0.702; pooled 0.323). A post-hoc
    Codex form that subtracts all output tokens reaches ratio 0.334 [0.139, 0.658], which would be LOOSE (R:A5-2).
- Every compaction-marked pair dropped: 33/33 in swechat CC, 429/429 in aiv_cc. Unmarked drops are the
  false-positive class: 67/10,744 swechat CC, 150/3,384 opencode, 87/2,487 Gemini CLI.

## A6. Fields the IR does not carry, and parser surprises
- The census has 2,083 entries: 642 uncaptured, 924 not in the IR. 435 harness-measured candidates have key fill
  ≥ 0.3. 302 entries the census called uncaptured are already in the IR.
- Of the 435 candidates, census value counts show 7 majority-null (stop_reason/stop_sequence; aiv_cc stop_reason is
  non-null in 14/13,792). Another 7 aiv_cu entries have no value counts (R:A6-1).
- The strongest missing redundancy is CC `toolUseResult` counters:
  - Read numLines 2,514/2,561 = 0.982, top-level results only. 1,794 of the 4,043 A Read rows are subagent rows
    (R:A6-2).
  - Edit structuredPatch 1,958/2,029 = 0.965.
  - Stop-hook durations 792/951 = 0.833.
- The 80 parser surprises split into 47 open, 28 handled by the loader and 5 resolved.

## Surprises (data)
- The table's 10 KB cap does not exist in the raw data. The cap that does exist is Claude Code's own middle elision of
  failing shell output (15 results, p50 10,040 chars; A3).
- Gemini CLI masks 36.3% of its tool results. The transcript cannot show what the model saw (A3).
- One OpenCode document truncated during salvage loses 232 calls from the IR, and no join metric notices (R:A2-4).
- aiv_cc is effectively a single agent: 33,473/33,475 results and all conservation pairs come from one SDK session.
- The marker for a human rejection takes p50 23.0 s in swechat. The permission-denied marker takes p50 0.007 s in
  cc_local (R:A1-1, R:A1-2).

## Consequences for Phase B (Interpretation)
1. **Probe 1 (latency):** run on swechat CC, cc_local and aiv_cc; report codex, opencode and gemini as small-n; drop
   aiv_cu, whowhen, cursor and simple_text. Filter human waits before using shell, edit, write or web latencies in the
   CLI corpora (auto-read and internal tools, no rejection marker, no linked hook). Treat aiv_cc deltas under about
   0.1 s as floor-bound, and its CIs as one agent's.
2. **Probe 3 (errors):** use `native_error` where it is filled (for CC formats, null means not flagged). Keep the
   marker classes apart: in cc_local, permission denials are not command failures. Keep Gemini's two classes apart.
   Label aiv_cu results as proxy-based or drop them.
3. **Token conservation** can carry a mechanism in aiv_cc, which is one agent, and in OpenCode's result-only form. The
   Codex full-output form must be pre-registered before it is used. Exclude compaction pairs, and set thresholds from
   the split-A residual distributions.
4. **Claim-vs-output checks:** gate on truncation per scaffold (markers, flags, Glob shape); exclude Gemini masked
   results; treat spilled previews as a candidate fabrication surface (claims about unseen spilled content cannot be
   checked).
5. **Data hygiene:** use the raw IR, never `conversations.parquet`; join on (session_id, call_id); require an A6
   candidate to be non-null before using it. The counters Phase B wants (Read numLines, Edit patch counts, hook
   durations) need a loader change, decided by day.
6. **Split hygiene.** Several Phase C lenses read `*_B.parquet` (their headers say so: token_conservation, two_clocks,
   changepoints, distributions, outliers, sequences, ids_and_clocks_in_ids; aiv_narration and correlations read both
   splits). Set Phase B thresholds from this file only. Do not count Phase C findings on B as held-out confirmation.
