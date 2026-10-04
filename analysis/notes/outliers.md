# Phase C lens: multi-axis outlier sessions

Script: `analysis/probes/phase_c_outliers.py`. Data: `analysis/out/phase_c/outliers.json` (raw counts only).
Run: `PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_c_outliers` (features stage ~75 s, report stage ~1 min;
two report runs gave byte-identical JSON). Input: the Phase B IR caches (`<corpus>_B.parquet`), plus
`aiv_cu_sessions.parquet`, `swechat_population.parquet`, `whowhen_labels.json` and the attribute columns repo_id,
cli_version and created_at from `data/swe-chat-pinned/sessions.parquet`. The unit is the session (aiv_cc: the run).

Every number below is in the JSON. Paths are relative to `corpora.<corpus>` unless they start with `summary`, `prereg`
or `posthoc`. Rates are `k/n = rate [Wilson 95%]`. One observation per session, so Wilson is the session-level interval.

## Rule (`prereg`, fixed before any z score was computed)
- Features: 30–39 per corpus (20 for whowhen), from a common set plus corpus-specific ones (`prereg.features`).
- Transform: log10(1+x) for counts, sizes, tokens and durations; log10(x) for ratios; raw for shares.
- Robust z: (x − median) / (1.4826·MAD). When MAD = 0 the scale falls back to 1.253314·meanAD. A feature that is
  constant in a corpus is dropped.
- Extreme means |z| > 3.5. An outlier is a session extreme on ≥ 3 axes.
- Picks: 10 for swechat and aiv_cu, 5 for the other corpora. They are ranked by number of extreme axes, then by the
  capped sum of |z|.
- Sensitivity checks, also fixed in advance: z within stratum (strata of ≥ 20 sessions), and a run without the
  meanAD-scaled features.
- Null: a 200-permutation column-permutation null for the ≥ 3 count.

Post-hoc changes are listed in `posthoc`:
- **P1**: the `native_err_frac` denominator was changed before any z score existed.
- **P2–P7**: added after the first report. P2 is the permutation-null tail, P3 and P4 are per-stratum breakdowns,
  P5 and P6 are follow-ups and session descriptors, and P7 is the timeout-bin gap counts.
- Everything labelled POSTHOC is hypothesis-grade.

---

## A. Numbers

### A0. Headline (`summary`)

| corpus | n | features | outliers (≥3 axes) | null ≥3 mean [2.5, 97.5] | within-stratum | no-meanAD |
|---|---|---|---|---|---|---|
| swechat | 2000 | 39 | 605 = 0.3025 [0.283, 0.323] | 551.4 [532, 576] | 440 (1992 covered) | 298 |
| cc_local | 186 | 37 | 72 = 0.387 [0.320, 0.459] | 98.4 [90, 106] | 61 (173 covered) | 72 |
| aiv_cc | 189 | 34 | 62 = 0.328 [0.265, 0.398] | 60.0 [53, 67] | 66 (189) | 25 |
| aiv_cu | 2000 | 30 | 606 = 0.303 [0.283, 0.324] | 647.3 [623, 670] | 587 (2000) | 452 |
| whowhen | 111 | 20 | 13 = 0.117 [0.070, 0.190] | 7.2 [4, 11] | 6 (111) | 0 |

- For comparison, the swechat_tables lens applied the same rule to 22 sessions-table features. It found
  101/4847 = 0.0208 [0.0172, 0.0253] (`context_swechat_tables_part4_claude_code`). On IR event features the same rule
  flags about 30% of sessions.
- **NULL: at ≥ 3 axes the outlier count is not above the independence null.** Observed vs null at ≥ 3
  (`POSTHOC_P2_permutation_null_tail[">=3"]`):
  - cc_local and aiv_cu are below the null: 72 vs 90–106, 606 vs 623–670. In 200/200 permutations the null count was
    ≥ the observed count.
  - aiv_cc is inside the null: 62 vs 53–67.
  - swechat is just above: 605 vs 532–576.
  - whowhen is at the edge: 13 vs 4–11, with 1/200 permutations ≥ 13.
- **HIT (structure, POSTHOC P2): the upper tail is far above the null in every large corpus.** Extremes concentrate
  in the same sessions. Sessions with ≥ k extreme axes, observed vs null mean [2.5, 97.5]:

| corpus | ≥ 5 axes | ≥ 7 axes | other tail point | max axes, observed vs null |
|---|---|---|---|---|
| swechat | 182 vs 60.1 [48, 73] | 12 vs 2.6 [0, 6] | – | 10 vs null max 9 |
| cc_local | 54 vs 22.1 [16, 28] | – | ≥ 8: 16 vs 0.5 [0, 2] | 21 vs null max 11 |
| aiv_cu | 278 vs 77.5 [65, 92] | – | ≥ 8: 46 vs 0.5 [0, 2] | 11 vs null max 10 |
| aiv_cc | 17 vs 7.5 [4, 12] | – | – | 6; null mean 6.2, 171/200 permutations ≥ 6 |
| whowhen | – | – | ≥ 4: 4 vs 1.2 [0, 3], 5/200 permutations ≥ 4 | – |

### A1. swechat (n 2000)
**Pooled outliers are mostly format and one repo** (`profiles.format`, `profiles.repo_id`, `POSTHOC_P5_followups`)
- Outlier rate by format: claude_code 335/1679 = 0.20 [0.18, 0.22], opencode 184/214 = 0.86 [0.81, 0.90],
  codex 65/77 = 0.84 [0.75, 0.91], gemini 13/22 = 0.59 [0.39, 0.77], cursor 8/8.
- dayhaysoos/nimbus: 188/202 = 0.93 [0.89, 0.96] are outliers.
  - Its B sessions are 175 opencode and 27 codex, so 175 of the 214 B opencode sessions come from this one repo.
  - Within-format z drops it to 16/202 = 0.08 [0.05, 0.12] (`POSTHOC_P4_within_stratum_profiles.repo_id`).
- The 6 most common axis combinations (27, 24, 17, 14, 12 and 12 sessions) are opencode-only
  (`POSTHOC_P3_top_combos_by_stratum`). They are combinations of subagent_share+, ts_null_frac+, redacted_frac+,
  trunc_frac+ and cache_read_share−.
- Which formats produce which extremes (`POSTHOC_P3_extremes_by_stratum`):
  - ts_null_frac: opencode 211, cursor 8
  - subagent_share: opencode 176, codex 43
  - trunc_frac: opencode 121
  - ts_backward_frac: opencode 61, and no other format
  - redacted_frac: claude_code 303, opencode 115, codex 30
  - call_result_gap_median_s: claude_code 311

**Length**
- Short sessions are over-represented: T1 374/672 = 0.56 [0.52, 0.59], T2 91/663 = 0.14, T3 140/665 = 0.21
  (`profiles.length_tercile`).
- Every session with no calls is an outlier: 49/49 (`profiles.flag_no_calls`).

**Within-format (claude_code, n 1679)** (`POSTHOC_P5_followups.claude_code_format_outliers`, `POSTHOC_P4_within_stratum_profiles`)
- 363 outliers within the format vs 335 pooled; 294 are outliers under both rules.
- Within-stratum outlier rate by flag, across all covered sessions:

| flag | yes | no |
|---|---|---|
| compaction | 89/203 = 0.44 [0.37, 0.51] | 351/1789 = 0.20 |
| subagent | 131/869 = 0.15 [0.13, 0.18] | 309/1123 = 0.28 |
| any backward ts step | 315/1671 = 0.19 | 125/321 = 0.39 [0.34, 0.44] |

- By length tercile: T1 212/664 = 0.32, T2 79/663 = 0.12.
- By cli_version: 0.4.2 is 58/158 = 0.37 [0.30, 0.44]; 0.4.9 is 32/285 = 0.11 [0.08, 0.15].

**Error, truncation, redaction and end-of-session flags** (`profiles.*`)
- native error present: 296/1297 = 0.23 are outliers; absent: 309/703 = 0.44.
- truncation present 249/795 = 0.31, absent 356/1205 = 0.30 (no difference).
- redaction present 383/1115 = 0.34, absent 222/885 = 0.25.
- Sessions ending on an unanswered call: 33/108 = 0.31 [0.23, 0.40] (POSTHOC P6). Not enriched.
- Of the 20 sessions in B whose harness tally swechat_tables could not match, 7 are outliers
  (`swechat_tables_unmatched_tally`).

**Picks** (`picks`; 9 Claude Code, 1 Codex; T1 6, T2 1, T3 3; 7–10 extreme axes; `picks_summary`)
1. `1a5567dc…` (ChetanReddyC/Shila-Murti, 6 events, 10 axes)
   - One Agent call whose result arrives 16,829.7 s later as `cc_interrupt_reject`.
   - call_result_gap z 135.1; native_err_frac and marker_err_frac 1.0; assistant chars 0.
2. `29dcda5f…`: same repo, same pattern, 27.8 s gap, `cc_interrupt_reject`, 9 axes.
3. `94aabe90…` (serg-alexv/rhea-project): 12,159 events, 16 compactions, 16 background tasks, 433 user events,
   3 models, 2 api_errors.
4. `fcd811f5…`: 14 events, 3 shell calls with median args of 5,710 chars, redacted_frac 0.071.
5. `261278d3…` (rhea-project again): 9,197 events, 9 compactions, max identical call ×68.
6. `c751510e…` (obsessiondb/rudel): out_tokens_total 96 against 118 events (chars_per_out_token 210.6),
   redacted_frac 0.093, 3 models.
7. `019d8eb9…` (Codex sub-agent rollout): subagent_share 1.0, cache_read_share 0.435, median args 2,685 chars.
8. `70dd74bc…` (marcus-sa/brain): 14 events (11 of them hook-progress meta), the transcript **ends on a Bash call
   with no result**, out tokens 9.
9. `83d51b62…` (entireio/cli): system_share 0.4.
10. `fe94d82a…`: 2,860 events, 8 background tasks, 146 user events.

### A2. cc_local (n 186; aggregates only)
**Half the B sample is one session template** (`POSTHOC_P5_followups.top_tool_glob_cluster`)
- 92/186 sessions have glob as their most-used tool. All 92 share these properties:
  - same stratum (proj01) and same model (claude-opus-5)
  - exactly 1 user event
  - at least one native error (outside the cluster: 28/94)
- Their sizes are narrow: n_events 41–117 (median 69), n_calls 6–30 (median 15), 3–8 distinct tools (median 3),
  span 35.6–168.7 s (median 90.7 s).
- **0/92 of them are outliers. All 72 outliers are among the other 94 sessions.**

**Model** (`profiles.model_top`)
- Outlier rate: claude-opus-5-5 37/37, claude-opus-4-7 13/13, claude-opus-5 19/133.
- Sessions with zero thinking characters: claude-opus-4-7 13/13, claude-opus-5 13/133, claude-opus-5-5 0/37
  (`thinking_chars_zero_by_model_top`).

**Strata and flags**
- proj02: 13/13 are outliers.
- By length: T1 50/63 = 0.79 [0.68, 0.88], T2 3/61 = 0.05, T3 19/62 = 0.31.
- Every session with any of these properties is an outlier:
  - subagents: 6/6
  - multi-member resume family: 6/6
  - workflow journal: 5/5
  - last event an assistant event: 24/24

**Axes driving the outliers** (`per_feature`)
- Extreme-high counts: call_result_gap_median_s 65, shell_share 56, args_chars_median 52, attachment_share 32.
- Most common combination: args_chars_median+, attachment_share+, call_result_gap_median_s+, shell_share+ and
  system_share+, in 12 sessions.

**Picks** (aliases only; all T3, all proj01, 15–21 extreme axes)
- These are the largest sessions:
  - 1,442–64,101 events
  - subagent share 0.488–0.846
  - 30–613 workflow-journal lines
  - up to 12 resume-family members
  - up to 12,886,603 output tokens
- Picks 1, 2 and 4 have their largest call→result gap at 600.96, 600.78 and 600.76 s.

### A3. aiv_cc (n 189 runs)
- Outliers are enriched for these traits:
  - long runs: T3 41/63 = 0.65 [0.53, 0.76]
  - compaction: 42/60 = 0.70 [0.57, 0.80]
  - "REDACTED" in text: 25/31 = 0.81 [0.64, 0.91]
  - native error: 39/53 = 0.74 [0.60, 0.84]
  - truncation: 10/11
- **The SDK clock identity shows up as an outlier axis.** sdk_duration_over_span has median 1.00001 and p25–p75
  0.985–1.0008 (`per_feature.sdk_duration_over_span.raw_describe_all`). It has 12 high and 17 low extremes.
- The ratio is 0 in 32 runs. log10 makes those NaN, so they are never extreme on this axis.
- Result rows per run (`POSTHOC_P5_followups.result_rows_counts`): 1 in 159 runs, 0 in 28, 2 in 1, 4 in 1. 20 of
  the 28 runs with no result row are outliers.
- Failed-resume result rows (num_turns 0 and duration 0) appear in 34 runs:
  - pooled outliers: 3/34 = 0.09 [0.03, 0.23]
  - within-month outliers: 27/34 = 0.79 [0.63, 0.90]
  - (`profiles` and `POSTHOC_P4_within_stratum_profiles` `.flag_failed_resume_rows`)

**Picks** (6 axes each)
- r197: 5 events, 1 call with a native error, no result row, cache_read_share 0.697.
- r259: 4 result rows (1 success, then 3 failed resumes), span 260,057.6 s, duration/span 0.028 (z −3305).
- r198: duration/span 0.183, 2,547 calls, the same call ×559, 31 compactions.
- r189: 2,450 calls, the same call ×486, 28 compactions.
- r202: 2,292 calls, the same call ×326, 30 compactions, no result row.
- In r198, r189 and r202 consec_dup_call_frac is 0.55–0.58.

### A4. aiv_cu (n 2000)
**A harness turn cap anchors the robust centre** (`POSTHOC_P5_followups`)
- In the 78,114-session population, 35,684 sessions have exactly 41 turns. Next are 42 turns (4,300) and
  40 turns (1,514). The counts for 35–39 turns are 837–902 each.
- In B, 901 sessions have 41 turns and 107 of them are outliers. 499 of the other 1,099 are outliers
  (`B_outliers_by_n_turns_eq_41`).
- n_calls is extreme-low in 664 sessions (`per_feature.n_calls`).
- By length: T1 486/672 = 0.72 [0.69, 0.76], T3 52/667 = 0.08.

**Bootstrap-only sessions**
- Population count: 221 sessions consist of the synthetic bootstrap turn plus one talk-only turn.
  - gpt-5.1-2025-11-13: 187/5979 = 0.031 [0.027, 0.036]
  - next highest: claude-sonnet-4-5 at 14/3979 = 0.0035
  - (`population_bootstrap_plus_one_talk_turn`)
- 7 of the 10 picks are such 2-event gpt-5.1 sessions, and 9 of the 10 picks have ≤ 10 events (`picks_summary`).

**Strata and model** (`profiles`)
- openai-chat stratum: 55/85 = 0.65 [0.54, 0.74].
- anthropic-sdk shape: 31/35 = 0.89 [0.74, 0.95].
- gpt-5.1: 102/148 = 0.69 [0.61, 0.76].
- Within-stratum z changes the picture. gpt-5.1 drops to 49/148 = 0.33 and anthropic-sonnet rises to
  125/272 = 0.46 [0.40, 0.52] (`sensitivity_within_stratum.per_stratum`, `POSTHOC_P4_within_stratum_profiles`).

**Model labels** (`n_models_ge2_model_sets`)
- 43 sessions carry two model strings. In 41, the agent's label (gemini-2.5-pro) differs from the row-level model
  version: preview-06-05 in 38, preview-05-06 in 2, preview-03-25 in 1. The other 2 differ only by the
  `claude-code::` prefix.

**Gemini-only axes** (`POSTHOC_P3_extremes_by_stratum`)
- call_id_fallback_frac extremes: gemini-pro 224, anthropic-claude-code 35.
- unexecuted_calls extremes: gemini-pro 39.
- Pick 6 (gemini-3-pro-preview) has 20 unexecuted provider calls against 19 executed ones, a 72,675.9 s span and a
  server-timing median of 25,946 ms.

### A5. whowhen (n 111; no timestamps)
- Outlier rate by split: Hand-Crafted 8/33 = 0.24 [0.13, 0.41], Algorithm-Generated 5/78 = 0.06 [0.03, 0.14].
  Within-split z leaves 6 (overlap 5).
- is_correct is False for all 111 sessions, so no label contrast is possible.
- Position of the labelled mistake (`mistake_rel_position`, `POSTHOC_P5_followups`):
  - Median relative position of mistake_step: 0.111 in outliers (n 13) vs 0.274 in the rest (n 98).
  - In the "early" tercile: AG 5/5 outliers vs 47/73 of the rest; HC 7/8 outliers vs 11/25 of the rest.
  - **Small n, no CI given, hypothesis only.**
- Outlier axes:
  - replans+ and n_events+ (15 extreme each)
  - max_identical_call− (14)
  - terminal_no_code+ (9)
  - unexecuted_call_frac+ (7)
- Picks: three long Magentic runs (67–124 events, 2–4 replans) and two AG runs with 75–100% unexecuted code calls.

### A6. Timeout spikes in call→result gaps (POSTHOC P7, `POSTHOC_P7_timeout_gap_bins`)
Paired call→result gaps per 2-second bin (gaps / sessions):

| corpus | [118,120) | [120,122) | [122,124) | [598,600) | [600,602) | [602,604) |
|---|---|---|---|---|---|---|
| swechat | 56 / 47 | **235 / 99** | 74 / 51 | 0 / 0 | **173 / 23** | 8 / 4 |
| cc_local | 3 / 2 | **117 / 7** | 3 / 2 | 2 / 1 | **75 / 5** | 1 / 1 |
| aiv_cc | 1 / 1 | **11 / 7** | 1 / 1 | 0 / 0 | 3 / 1 | 0 / 0 |
| aiv_cu | 0 | 0 | 0 | 0 | 0 | 0 (shared_turn stamps) |

- Tools in the spike bins (`normalized_tool_by_bin`):
  - swechat [120,122): shell 188, taskoutput 23, subagent 16.
  - swechat [600,602): taskoutput 136, shell 37.
  - cc_local [120,122): shell 117.
  - cc_local [600,602): shell 67, taskoutput 7.
- The spike gaps are concentrated in few sessions and mostly in outliers: swechat [600,602) has 144 of its 173 gaps
  in outliers. I give counts only. These are not rates.

---

## B. Interpretation (not data)

**1. The multi-axis rule does not isolate rare sessions in agent-log IR. Read it as "how far from the dominant
template", not as "anomalous".**
- At |z| > 3.5 on ≥ 3 axes, about 30% of swechat, aiv_cu and aiv_cc sessions, and 39% of cc_local, are outliers.
- At ≥ 3 axes the count is at or below what independent axes would produce.
- Three mechanical causes:
  - **Robust centres sit on a template.** In cc_local the template is a single scheduled-looking session type
    (92/186, none of them outliers). In aiv_cu it is the 41-turn harness cap (35,684/78,114 sessions). In swechat it
    is the Claude Code majority format (1,679/2,000). Whatever is not the template is extreme on many axes at once.
  - **Shares computed on tiny denominators.** Shares that are exactly 0 or 1 in sessions of a few events reach
    very large z. Examples: z 137.4 for unpaired_call_frac 1.0 in swechat pick 8 (14 events), and z 132.6 for
    system_share 0.5 in aiv_cu picks 2–4 (2 events). So the top picks are mostly near-empty sessions: aiv_cu 9/10 have
    ≤ 10 events, and swechat picks 1, 2, 4, 8 and 9 have 6–20 events.
  - **Format mixing.** Pooled swechat outliers are 86% of opencode and 93% of one repo. Both effects mostly vanish
    under within-format z (nimbus 0.93 → 0.08).
- The real structure is in the tail. Sessions with ≥ 5–8 extreme axes are far above the null: swechat ≥ 5 has
  182 vs 60.1, and aiv_cu ≥ 8 has 46 vs 0.5. That means the features co-move: the same sessions are extreme on many
  axes together. Part of this is built in by construction,
  for example n_calls−, synthetic_share+ and system_share+ in a 2-turn session. So a usable cut would be ≥ 5–8 axes,
  within stratum. **That cut was not pre-registered, and I did not apply it.**

**2. What the extreme-tail sessions share, corpus by corpus.**
- swechat:
  - Within the CC format they are compaction-heavy and long-running (background tasks, many user turns, several
    models), or short.
  - A recurring short pattern is one tool call answered after a long human wait by a rejection marker (picks 1–2).
  - Truncation and unanswered-call endings are not enriched.
- cc_local: they are orchestration sessions (subagents, workflow journals, resume families, millions of output
  tokens), and every session that has those features is an outlier.
- aiv_cc: they are long compaction runs that poll the same call hundreds of times, plus loader-unit artifacts.
  Failed-resume result rows are attached to the previous run, which stretches its span over days. This is the
  accounting lens's finding, rediscovered here as an outlier axis.
- aiv_cu: they are sessions that ended before the turn cap, bootstrap-only sessions, mostly gpt-5.1, and Gemini
  sessions with many silently unexecuted calls.
- whowhen: they are long Magentic runs with replans, and AG runs whose code was never executed.

**3. Surprises worth keeping (parser and harness facts, not fabrication):**
- The **harness turn cap at 41** in aiv_cu: session length is set by the harness for 35,684 of 78,114 sessions.
- **gpt-5.1 bootstrap-only sessions** occur at a rate of 0.031. The next five models in that list are all
  ≤ 0.0097.
- **Gemini model-of-record vs served preview versions** (41 B sessions).
- **cc_local is half one template** (92/186).
- **claude-opus-4-7 sessions in cc_local carry zero thinking characters** (13/13). This could be redacted thinking;
  I did not inspect content.
- **Timeout spikes.** Call→result gaps pile up at [120, 122) s (shell) and [600, 602) s (TaskOutput, shell). This is
  consistent with fixed harness timeouts. The values come from the data; whether they are the documented Claude Code
  defaults I did not check against an external source. A log that reports a shell call running past such a
  ceiling without a timeout marker would contradict the harness. The spike is a timing fingerprint a fabricated log
  would have to reproduce.

**4. Nulls, with equal weight.**
- ≥ 3-axis outliers are not above the independence null in 4 of 5 corpora. swechat is just above it.
- Truncation is not enriched in swechat outliers (0.31 vs 0.30).
- Ending on an unanswered call is not enriched (0.31 vs 0.30).
- A native error in the session goes with fewer outliers, not more, in swechat (0.23 vs 0.44) and cc_local
  (0.17 vs 0.79). In cc_local this is because the template sessions all contain errors.
- Without meanAD features, whowhen has 0 outliers. All its axes except 6 are zero-inflated.
- No outlier axis maps to a ground-truth failure label. whowhen has no successful sessions to contrast, and the
  mistake-position skew rests on 13 sessions.

**5. Novelty (UNVERIFIED).**
- Robust multi-feature outlier scoring is standard anomaly detection. Nothing here is new as a method.
- Two specific uses may be less common for fabrication detection: harness timeout ceilings as a timing witness
  (gap spikes at fixed caps), and provider-listed-but-unexecuted calls as a consistency witness. I did not search the
  literature.

## Could not measure
- Within-stratum z for swechat cursor (8 sessions) and cc_local proj02 (13): both strata are under the
  pre-registered minimum of 20.
- A label contrast for whowhen: every B session is a failure.
- Whether any outlier is a fabrication: no corpus has fabrication ground truth.
- Rates with CIs for the timeout spikes: gaps are clustered in few sessions, and only counts were computed.
- Content-level causes in cc_local (zero-thinking sessions, the template's error): the corpus is private.
- Overlap between these outliers and the swechat_tables outliers: that JSON stores no per-session ids.
- aiv_cc out_tokens_total per run is built from streaming snapshots (see aiv_accounting). Token features there are
  only internally comparable.
