# Phase A5: token accounting and token conservation

Script: `analysis/probes/phase_a_a5.py`. Data: `analysis/out/phase_a/a5.json`. Every number below is in that JSON; the
path after a number is relative to its root. Split A only (`analysis/cache/*_A.parquet`); no `*_B` file was opened.
Raw files were read for split-A sessions only, and only for fields the IR drops (`part1.raw_A_checks`). cc_local
results here are aggregates only.

---------------------------------------------------------------------------------------------------------------------

## HEADLINE: NO FIELD ACCOUNTS TOOL-RESULT TOKENS SEPARATELY FROM MODEL-GENERATED TOKENS

**No field in any corpus gives the token count of a tool result's text apart from the rest of the prompt.**
Every per-call usage record has one input bucket (Anthropic: uncached input + cache read + cache creation; OpenAI/Codex,
Gemini: one prompt count that includes cached tokens). Tool output, user text, system text and earlier model output all
land in it together. The only splits on the generated side are reasoning vs visible output.

The candidates, each checked:

| Candidate | What the data shows | Separates tool-result tokens? |
|---|---|---|
| Gemini CLI `tokens.tool` (swechat gemini, raw; the IR drops it) | present on 2505 of 3017 split-A gemini messages, **nonzero in 0**; `total == input + output + thoughts` holds 2505/2505 (`part1.raw_A_checks.swechat_gemini_tokens_A.counts`) | **No.** The field exists but is always 0 |
| Gemini API `toolUsePromptTokenCount` (aiv_cu gemini) | key absent on all 752 + 528 usage rows; `totalTokenCount == prompt + candidates + thoughts` 752/752 and 528/528 (`part1.semantics.identities.aiv_cu/gemini-*:usageMetadata`) | **No.** There is no hidden tool bucket |
| Gemini `promptTokensDetails` by modality (aiv_cu gemini) | TEXT/IMAGE split on 752/752 and 528/528 usage rows; sums equal promptTokenCount 752/752 and 528/528. IMAGE tokens rise between two calls in 417/420 (gemini-pro) and 191/191 (gemini-flash) gaps holding a GUI result, and in 0/309 and 0/320 gaps without one. Step sizes: gemini-pro p1-p50 258, p75-max 1064; gemini-flash min = max = 1064 (`part2.aiv_cu/gemini-*.gemini_modality`) | **Partly.** Screenshot tool results (images only) are counted exactly and apart from text. Text tool output is not. Gemini computer-use only: 23 + 17 split-A sessions |
| Claude Code `usage.iterations[]` (raw; IR drops it) | swechat split A: 5356 empty lists, 132 single-iteration lists, 0 longer; cc_local split A: 4 empty, 7463 single, 0 longer; every iteration has type `message` and equals its parent usage (132/132, 7463/7463) (`part1.raw_A_checks.*_usage_iterations_A`) | **No.** Never more than one iteration |
| Claude Code `toolUseResult.totalTokens` / `usage` (Task/Agent results) | 199 of 13592 swechat claude_code results (Task 48, Agent 151); 0 in cc_local and aiv_cc split A (`part1.separate_tool_result_accounting`) | **No.** These are the tokens the subagent used, not the size of the result text |
| Reasoning splits: Codex `reasoning_output_tokens`, OpenCode `reasoning_tokens`, Anthropic `output_tokens_details.thinking_tokens`, Gemini `thoughtsTokenCount` | Codex: reasoning <= output on 701/701 rows, >0 on 612; OpenCode: >0 on 2589/3414; aiv_cu Anthropic: <= usage_out on 1277/1277, >0 on 1056 (`part1.semantics.identities`) | **No.** These split the model's own output |
| Copilot `systemTokens` / `conversationTokens` / `toolDefinitionsTokens` | 3 meta rows in 1 split-A session (`part1.extra_token_fields.swechat/copilot`) | **No.** Tool *definitions*, written only at compaction or shutdown |
| Copilot `toolTelemetry.metrics.responseTokenLimit` | 82/265 tool.execution_complete lines in A6's sample (`part1.a6_uncaptured_token_paths`) | **No.** It is a limit, not a count |

So a check that wants "tokens of this tool result" has to infer them from the context delta (section 3). The one
exception is screenshot images in Gemini computer-use, where the provider's IMAGE count gives them exactly.

---------------------------------------------------------------------------------------------------------------------

## 1. Which per-turn token fields exist

IR usage columns, rows filled / rows of that kind (`part1.ir_usage_fill.<group>.<kind>.<col>.rows_notnull`):

| Group (split-A sessions) | Where usage sits | in | out | cache_read | cache_create | usage_in includes cache? (`part1.semantics.usage_in_includes_cache`) |
|---|---|---|---|---|---|---|
| swechat/claude_code (128) | assistant 4742/4745, call 13620/13620, meta (thinking-only entries) 3480/23834 | yes | yes (streaming snapshot) | yes | yes | no: in >= cache_read on 1 of 21207 rows |
| cc_local (123) | assistant 1624/1624, call 5165/5165, meta 3460/5054 | yes | yes (varies within a response) | yes | yes | no: 0 of 10146 |
| aiv_cc (125) | assistant 14139/14139, call 33479/33479, meta 30098/31619 | yes | yes (snapshot) | yes | yes | no: 0 of 77656 |
| aiv_cu anthropic-* (93) | call: opus 684/684, sonnet 683/683, haiku 552/552, fable 436/436, claude-code (SDK) 561/587 | yes | yes | yes | yes | no (in >= cr on 0-9 rows per stratum) |
| aiv_cu gemini-pro / flash (23 / 17) | call 752/752, 528/528 | yes | yes | 698, 485 | none | yes: 698/698, 485/485 |
| aiv_cu openai-responses / openai-chat / compat-chat (28 / 17 / 22) | none | - | - | - | - | - |
| swechat/codex (19) | meta (token_count) 701/2314 | yes | yes | yes | none | yes: 686/686 |
| swechat/opencode (25) | meta (step-finish) 3414/7742 | yes | yes | yes | yes | no: 42 of 3122 (OpenCode stores input net of cache) |
| swechat/gemini (15) | assistant 2419/2923, call 2307/2800 | yes | yes | yes | none | yes: 4604/4604 |
| swechat/copilot (2) | assistant 98/98, call 266/266 | none | yes | none | none | - |
| swechat/cursor (7), simple_text (4), whowhen (73) | none | - | - | - | - | - |

- Within one API response, in / cache_read / cache_create never vary across its rows (0 responses in every group).
  usage_out varies in 3809 of 6900 multi-row swechat/claude_code responses, 1678/3590 cc_local, 4104/30089 aiv_cc
  (`part1.semantics.usage_constancy_within_response`). Claude Code-format output counts are streaming snapshots.
  The aiv_cc per-response max has median 1 (`part2.aiv_cc.post_hoc_residual_diagnostics.usage_out_k_describe.p50`).
- Extra token fields (`part1.extra_token_fields`):
  - Codex: `total_token_usage.*` (cumulative) and `reasoning_output_tokens` on 722 token_count rows. Cumulative
    `total == input + output` holds 722/722.
  - OpenCode: `cost` and `reasoning_tokens` on 3414 step-finish rows (cost > 0 on 3233).
  - aiv_cu Anthropic: `usage_detail.cache_creation.ephemeral_5m/1h` and `output_tokens_details.thinking_tokens`.
  - aiv_cu Gemini: `usage_detail.{promptTokensDetails, cacheTokensDetails}.{TEXT,IMAGE}`, `thoughtsTokenCount` and
    `totalTokenCount`.
  - Claude Code: `compactMetadata.preTokens` (34 rows, swechat) and `compact_metadata.pre_tokens` (432 rows, aiv_cc).
  - aiv_cc result rows: 100 rows (one per run that has one). `num_turns`, `total_cost_usd`, `duration_ms` and
    `duration_api_ms` are present on 100/100. The IR carries no usage on them (0/100), and `result.usage` / `modelUsage`
    are not in the IR (`part1.semantics.identities.aiv_cc:result_rows`).
- Dropped by the IR but present raw: Gemini CLI `tokens.thoughts` (nonzero on 1422/2505) and `tokens.total`, plus the
  always-zero `tokens.tool` (`part1.raw_A_checks.swechat_gemini_tokens_A`). Also Claude `usage.iterations[]` (above) and
  `cache_creation.ephemeral_*` in Claude Code transcripts. The SWE-chat tables hold per-turn and session token columns
  that are not an IR source (A6 copies in `part1.a6_uncaptured_token_paths`, from A6's own sample, not split A).
  A6's `captured` mark is not always right: for example, it lists Codex `cached_input_tokens` as uncaptured, but the IR
  carries it as usage_cache_read.

---------------------------------------------------------------------------------------------------------------------

## 2. Token conservation: setup

All rules are in `PREREG` and were fixed before any delta, correlation or residual was computed. Rules added after the
first run are in `POST_HOC`. In short:

- **Responses and threads.** Thread = (session, is_subagent, agent_id). There is one response per (session,
  api_msg_id). For Codex, the response is the assistant/call rows before each token_count.
- **Context and delta.** ctx = in + cache_read + cache_create (Anthropic, OpenCode) or in (Codex, Gemini). The delta is
  between consecutive responses in seq order.
- **Appended chars.** x = assistant text + (call args + tool name) of response k, plus the text of result/user/system
  rows between the two send points. aiv_cu also counts its separate stderr field.
- **Pair categories.** compaction (marker in the gap) > image ('[image]' marker; for aiv_cu, a GUI result in the gap) >
  non_image.
- **Fit set.** Fit set = non_image pairs with delta > 0. Theil-Sen fit; 2-fold cross-fit by session hash. The
  "typical result" is the median chars of one result event in the fit set times the fitted tokens/char.
- **Verdict rule (pre-registered).**
  - TIGHT if Spearman CI low >= 0.90 and cross-fit median |residual| <= 0.25 x typical result tokens.
  - LOOSE if Spearman >= 0.70 and the ratio is <= 1.0.
  - Otherwise NOT_TIGHT.
  - INSUFFICIENT if the fit set has < 10 sessions or < 200 pairs.

## 3. Token conservation: results

### 3a. Non-image growth pairs (`part2.<group>.non_image_growth`, `.typical_result`)

| Group | fit pairs (sessions) | Pearson | Spearman [CI] | chars/token median | cross-fit median abs residual, tokens [CI] | p90 | typical result, tokens | residual / typical result [CI] | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| **aiv_cc** | 27491 (73) | 0.989 | **0.985** [0.977, 0.988] | 2.431 | **66.1** [53.1, 82.9] | 195.5 | 1447.7 | **0.046** [0.038, 0.054] | **TIGHT** |
| swechat/claude_code | 10669 (125) | 0.974 | 0.915 [0.897, 0.931] | 2.225 | 125.1 [120.2, 130.3] | 607.8 | 168.7 | 0.742 [0.591, 1.0] | LOOSE |
| swechat/opencode | 3234 (25) | 0.982 | 0.911 [0.892, 0.930] | 3.175 | 89.2 [79.6, 103.0] | 481.9 | 189.9 | 0.470 [0.342, 0.602] | LOOSE |
| swechat/gemini (Gemini CLI) | 2400 (11) | 0.680 | 0.820 [0.778, 0.865] | 3.291 | 117.8 [91.8, 137.0] | 928.0 | 227.7 | 0.517 [0.403, 0.600] | LOOSE |
| swechat/codex | 655 (15) | 0.743 | 0.918 [0.889, 0.944] | 3.027 | 315.3 [294.1, 334.9] | 822.6 | 136.5 | 2.311 [0.914, 4.409] | NOT_TIGHT |
| cc_local | 4069 (106) | 0.878 | 0.831 [0.804, 0.899] | 1.446 | 586.3 [539.6, 740.4] | 2088.3 | 357.8 | 1.639 [1.372, 2.941] | NOT_TIGHT |
| aiv_cu/anthropic-opus | 268 (13) | 0.769 | 0.684 [0.487, 0.780] | 1.441 | 458.1 [345.5, 581.0] | 1289.2 | 61.9 | 7.398 | NOT_TIGHT |
| aiv_cu/anthropic-sonnet | 215 (12) | 0.473 | 0.702 [0.449, 0.858] | 1.594 | 221.4 [187.2, 266.8] | 925.0 | 57.7 | 3.840 | NOT_TIGHT |
| aiv_cu/anthropic-haiku | 188 (12) | 0.918 | 0.665 [0.356, 0.858] | 1.858 | 302.7 [263.0, 324.0] | 623.8 | 33.2 | 9.123 | INSUFFICIENT (188 < 200) |
| aiv_cu/anthropic-fable | 257 (14) | 0.442 | 0.407 [0.181, 0.646] | 1.189 | 410.8 [369.2, 462.2] | 1627.5 | 73.8 | 5.564 | NOT_TIGHT |
| aiv_cu/anthropic-claude-code (SDK) | 270 (16) | 0.156 | 0.420 [0.296, 0.744] | 0.178 | 1173.1 [208.1, 1609.8] | 5765.7 | 24.1 | 48.729 | NOT_TIGHT |
| aiv_cu/anthropic_all | 1198 (67) | 0.361 | 0.323 [0.146, 0.551] | 1.179 | 709.3 [606.6, 791.5] | 2747.5 | 35.1 | 20.209 | NOT_TIGHT |
| aiv_cu/gemini-pro | 309 (19) | 0.992 | 0.521 [0.380, 0.660] | 1.044 | 185.7 [151.5, 228.4] | 605.5 | 3.4 | 54.573 | NOT_TIGHT |
| aiv_cu/gemini-flash | 318 (17) | 0.763 | 0.517 [0.395, 0.644] | 0.656 | 352.2 [271.6, 401.5] | 860.9 | 10.6 | 33.153 | NOT_TIGHT |

- Pair totals: aiv_cc 30001, swechat/claude_code 10800, cc_local 4095, opencode 3389, gemini 2487, codex 684, aiv_cu
  strata 422-662 (anthropic_all 2912) (`part2.<group>.pairs`).
- Theil-Sen tokens/char (`part2.<group>.non_image_growth.theil_sen`):
  - Claude Code formats: 0.342 (swechat), 0.514 (cc_local), 0.366 (aiv_cc).
  - Others: OpenCode 0.263, Codex 0.267, Gemini CLI 0.305.
- Theil-Sen intercepts, in tokens per pair, i.e. growth no logged char explains:
  - Claude Code formats: 197.7 (swechat), 851.5 (cc_local), 217.4 (aiv_cc).
  - Others: OpenCode 123.0, Codex 289.8, Gemini CLI 111.1.
  - aiv_cu: 312.0 to 2269.1.
- Residual relative to the delta itself: median |residual| / delta is 0.037 for aiv_cc, 0.214 swechat/claude_code,
  0.202 OpenCode, 0.326 cc_local, 0.36 Gemini CLI (`part2.<group>.non_image_growth.abs_resid_over_delta`).
- The aiv_cu "typical result" is tiny: the median result text is 9-174 chars, because GUI results carry no text. The
  ratio column is not meaningful there. The absolute residuals (185.7 to 1173.1 tokens) are what decide those rows.

### 3b. Negative and zero deltas (`part2.<group>.delta_sign_all_pairs`, `.delta_sign_by_category`, `.negative_deltas`)

| Group | delta < 0, share of all pairs [CI] (count) | with compaction marker | unmarked negatives in non_image | delta == 0 |
|---|---|---|---|---|
| aiv_cc | 0.015 [0.014, 0.016] (449) | 429/449 (all 429 compaction pairs negative) | 2 of 27493 (+18 of 2079 image pairs) | 0 |
| swechat/claude_code | 0.009 [0.006, 0.015] (100) | 33/100 (all 33 compaction pairs negative) | 67 of 10744 | 8 |
| cc_local | 0.0 [0.0, 0.001] (1) | 0/1 | 1 of 4070 | 0 |
| swechat/opencode | 0.045 [0.030, 0.058] (154) | 4/154 | 150 of 3384 | 0 |
| swechat/gemini | 0.035 [0.024, 0.049] (87) | 0/87 (no marker exists in this format) | 87 of 2487 | 0 |
| swechat/codex | 0.041 [0.017, 0.063] (28) | 2/28 | 23 of 678 | 0 |
| aiv_cu/anthropic_all | 0.008 [0.004, 0.013] (24) | 0/24 | 12 of 1210 (the SDK stratum alone has 17 negatives in 604 pairs, 6 of them non_image) | 0 |
| aiv_cu/gemini-pro / flash | 0 (0) / 0.004 (2) | 0 | 0 / 2 | 0 |

Compaction markers predict a context drop every time they occur (33/33, 429/429). Context drops without a marker are
the false-positive source: 67 in swechat/claude_code, 150 in OpenCode (4.4% of non_image pairs), 87 in Gemini CLI.
Their causes are not recorded in the IR.

### 3c. Image split (`part2.<group>.image`)

| Group | image pairs (sessions) | residual under the non-image fit, per image, median tokens [CI] | IQR |
|---|---|---|---|
| aiv_cc | 2079 (26) | **913.7** [904.2, 916.7] | 905.2-918.7 |
| swechat/claude_code | 23 (8) | 1316.2 [1072.9, 1473.5] | 1064.0-1466.5 |
| cc_local | 25 (5) | -173.0 [-401.8, 150.2] | -401.7-65.9 |
| aiv_cu/anthropic-opus / sonnet / haiku / fable / SDK (per GUI result) | 394 / 446 / 374 / 160 / 328 | 809.3 / 810.0 / 779.2 / 634.3 / 1017.3 | |
| aiv_cu/gemini-pro / flash (per GUI result) | 420 / 191 | 332.3 / 710.6 | |

In aiv_cc an appended image costs a near-constant ~914 tokens, so the image budget can be recovered even though the
image is not in the export. For aiv_cu Gemini the IMAGE modality gives the exact step (HEADLINE table). The cc_local image result has 5 sessions and a CI that spans 0, so it is not usable.

### 3d. Variants (pre-registered)

- **With thinking chars added to x** (`part2.<group>.non_image_growth_with_thinking`): cross-fit median |residual| falls
  from 125.1 to 90.1 tokens (swechat/claude_code; Spearman 0.934) and from 66.1 to 59.2 (aiv_cc; 0.988). cc_local barely
  moves (586.3 -> 574.9). Thinking chars are only 2.2% of cc_local fit-set chars and >0 in 15.1% of its pairs
  (`thinking_chars_share_of_fit_set_x`, `post_hoc_residual_diagnostics.share_pairs_with_thinking_chars_gt0`).
- **Result-only** (y = delta - visible output tokens of response k, x = appended input chars only;
  `part2.<group>.result_only_variant`):

  | Group | Spearman [CI] | cross-fit median abs residual, tokens [CI] | residual / typical result [CI] | Under the verdict rule's thresholds |
  |---|---|---|---|---|
  | **swechat/opencode** | **0.951** [0.934, 0.970] | **19.3** [14.9, 22.5] | **0.102** [0.070, 0.135] | **meets TIGHT** |
  | swechat/gemini | 0.898 [0.857, 0.931] | 47.0 [40.7, 57.3] | 0.174 [0.151, 0.213] | LOOSE (Spearman CI low 0.857 < 0.90) |
  | swechat/codex | 0.842 [0.799, 0.888] | 373.1 [298.9, 425.8] | 2.783 [1.035, 5.363] | NOT_TIGHT |
  | aiv_cu/gemini-pro / flash | 0.436 / 0.407 | 176.0 / 342.0 | 52.3 / 33.0 | NOT_TIGHT |

  Subtracting the provider's exact output count, instead of converting output chars, cuts the OpenCode residual from
  89.2 to 19.3 tokens. The residual is then about a tenth of one typical tool result.
- **Gemini modality** (aiv_cu; `part2.aiv_cu/gemini-*.gemini_modality`): TEXT-modality growth vs appended chars has
  Spearman 0.521 / 0.517 in gaps without a GUI result, and -0.01 / 0.171 (CIs span 0) in gaps with one. Separating images
  exactly does not make the text side conserve. aiv_cu context grows by text the export does not hold.

### 3e. Post-hoc diagnostics (`POST_HOC.residual_diagnostics`; `part2.<group>.post_hoc_residual_diagnostics`)

Spearman of the cross-fit residual with response k's usage_out:

| Group | Spearman [CI] |
|---|---|
| cc_local | 0.538 [0.18, 0.614] |
| swechat/codex | 0.548 [0.491, 0.618] |
| swechat/opencode | 0.372 [0.301, 0.418] |
| swechat/claude_code | -0.052 [-0.125, 0.011] |
| aiv_cc | 0.029 (usage_out is a snapshot there: median 1) |

The cc_local and Codex residuals rise with the response's own output count. Their per-response output median is
939 and 305 tokens. The cc_local logs carry little thinking text (above).

---------------------------------------------------------------------------------------------------------------------

## 4. Verdict: is conservation worth a Phase C probe?

**Yes, for aiv_cc, which meets the pre-registered TIGHT criterion.**
- Spearman is 0.985 [0.977, 0.988].
- The cross-fit residual is 66.1 tokens at the median (p90 195.5) against a typical tool result of 1447.7 tokens, a
  ratio of 0.046 [0.038, 0.054].
- In practice, a tool result whose logged length differs from what the model saw by more than about a quarter of a
  typical result sits outside the p90 of honest pairs.
- A length-preserving substitution would not show.

**Conditionally, for OpenCode, Gemini CLI and SWE-chat Claude Code (all LOOSE).**
- Their median residuals are 89.2, 117.8 and 125.1 tokens, against typical results of 189.9, 227.7 and 168.7 tokens.
  An inflated or deflated result has to be roughly the size of a typical result to stand out.
- OpenCode's result-only variant meets the TIGHT thresholds (19.3 tokens, 0.102 of a result). The precondition is that
  the format logs exact per-response output counts.

**No, as measured, for cc_local, Codex and every aiv_cu stratum (NOT_TIGHT; haiku INSUFFICIENT).**
- cc_local and Codex residuals are 1.6x and 2.3x a typical result, and they track the response's own output tokens.
  This fits model output (thinking / encrypted reasoning) that stays in context but not in the log. That is an
  interpretation; the data shows only the correlation.
- aiv_cu context grows by hundreds of tokens per step that no logged text or image explains. Intercepts run from 312.0
  to 2269.1 tokens per pair, and the median chars per token is as low as 0.178 (SDK), 0.656 (gemini-flash), 1.044
  (gemini-pro) and 1.189 (fable).

## 5. Nulls (stated as prominently as the hits)

- **No separate tool-result token field exists** (headline table).
- Gemini CLI `tokens.tool` is 0 in 2505/2505 records.
- Claude `usage.iterations[]` never has more than one entry: swechat split A has 132 single-entry lists and cc_local split
  A has 7463, with 0 lists longer than 1 in either.
- Copilot has no input or context usage per call. Cursor, simple_text, Who&When and the aiv_cu OpenAI / compat strata
  have no usage at all (`part2_not_feasible`). Conservation cannot be tested in those split-A sessions: copilot 2,
  cursor 7, simple_text 4, Who&When 73, openai-responses 28, openai-chat 17, compat-chat 22.
- aiv_cu Anthropic and Gemini strata: Spearman 0.323-0.702 on the fit set. Conservation fails there whatever the result
  size.
- The cc_local image residual is not distinguishable from 0 (CI -401.8 to 150.2; 5 sessions).
- Thinking chars barely help cc_local (residual 586.3 -> 574.9 tokens).

## 6. Caveats

- Chars are not tokens. No tokenizer was used (no new dependencies), so every residual is an upper bound on what a real
  tokenizer would give.
- The aiv_cu image flag is a proxy: a GUI result in the gap. It is validated for Gemini only (IMAGE tokens rise in
  417/420 and 191/191 GUI gaps, and in 0/309 and 0/320 others). For the Anthropic strata it is an assumption.
- The aiv_cu stderr field is counted as model-visible; that is an assumption (PREREG.appended_chars).
- **Post-hoc rule `usage_row_without_api_msg_id`** (POST_HOC; affects aiv_cu/gemini-pro only, 119 of 752 usage rows).
  The rule makes each id-less usage row its own response.
  - Rule off: 615 pairs, fit set 278 pairs (15 sessions), Spearman 0.500, residual 207.1 tokens
    (`part2.aiv_cu/gemini-pro.post_hoc_rule_off`).
  - Rule on: 729 pairs, fit set 309 (19), Spearman 0.521, residual 185.7.
  - The verdict is unchanged.
- Orphan model-output rows (output with no usage-bearing response) are counted as appended content in their gap. There
  are 997 in Gemini CLI (2505 of 3017 Gemini messages carry tokens) and 87 in OpenCode. Their chars are 0.1% and 2.0% of
  the fit-set x (`orphan_chars_share_of_fit_set_x`).
- aiv_cc sessions are resumed runs of one agent, so they are not independent in content. Only 73 of its 125 split-A
  sessions have >= 2 responses in a thread (`part2.aiv_cc.pair_sessions`).

## 7. What this means for Phase B

- Token conservation can carry a mechanism only where the fit is tight:
  - aiv_cc on its own terms.
  - OpenCode / Gemini CLI / Claude Code SWE-chat with the result-only form, where exact output counts exist, or with
    thinking chars added.
- Phase B thresholds should come from the split-A cross-fit residual distribution (`cross_fit.resid` median / p90 /
  p99), per format.
- Compaction-marked pairs must be excluded, and unmarked negative deltas (67 / 150 / 87 per format) handled as a known
  false-positive class.
- Images need their own term: about 914 tokens per image in aiv_cc, exact counts from Gemini modality details.
- cc_local and Codex need the response's own output tokens in the model before conservation can be judged. Neither
  that form nor a Codex variant that subtracts the full usage_out (reasoning included) was pre-registered here.
