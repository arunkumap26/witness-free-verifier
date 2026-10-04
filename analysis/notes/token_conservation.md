# Phase C lens: token conservation between consecutive API calls (Phase B split)

Script: `analysis/probes/phase_c_token_conservation.py` (reads only `analysis/cache/{swechat,cc_local,aiv_cc,aiv_cu}_B.parquet`
and `swechat_population.parquet`; text never leaves the script, only lengths and substring counts).
Data: `analysis/out/phase_c/token_conservation.json`. Every number below is in that JSON. Paths are relative to its root,
and `S:` abbreviates `fmt.<unit>.`. Phase A5 (`out/phase_a/a5.json`) does not exist, so this lens ran on its own.
`aiv_accounting` already did this check on all aiv_cc runs. Here aiv_cc (B runs only) is a reference point, not the focus.

## Method in one paragraph
For each conversation thread (main thread or one subagent), I keep one usage per API call (USAGE DEDUPE) and set
context C = input + cache_read + cache_create (Anthropic-style usage: Claude Code formats, OpenCode, aiv_cu Anthropic)
or C = input (Codex, Gemini CLI and aiv_cu Gemini, whose input already includes cached tokens). For consecutive calls k,
k+1 the window holds everything logged between the first event of call k and the first event of call k+1 that call k
did not generate: results, user text, system text and meta markers. dC = C(k+1) - C(k) is regressed on the logged
content of the window and of call k. The primary model is M_hyb. It uses call k's logged output_tokens where they are
plausible from the call's own chars (F = 1 when generated chars <= 6 x out_k), and chars otherwise. Fits are Huber,
cross-fitted over 2 session folds, so every residual is out-of-fold. The pre-registered M_chars and M_out are reported
next to it. "Clean" pairs have no break flag (compaction, microcompact, image, human user turn, model switch,
api_error, unaligned generated event, cc_local family-member switch, unrecorded attachment, Codex result > 40k chars).
Tamper simulation: lengthen or shorten the largest logged result in a clean window by delta chars. The predicted dC
moves by (fitted tokens/char) x delta and the real dC does not, so the residual shifts. The threshold comes from the
other fold's honest residuals (FPR 1%). Three detectors: D_abs (|r| > q99), D_bin (q99 per window-size bin) and D_asym
(the 0.5% and 99.5% signed tails). Post-hoc changes, each with its reason, are in `post_hoc`. The main ones are M_hyb as
primary, Huber, the min-30-nonzero term rule, the Codex large-result flag, D_asym, and the model-aware and tool-aware
variants.

---------------------------------------------------------------------------------------------------------------------

## A. Numbers

### A1. Coverage (`S:pairs`, `S:clean_pairs`, `S:clean_sessions`)
| unit | pairs | clean pairs | clean sessions | notes |
|---|---|---|---|---|
| swechat:claude_code | 153106 | 141477 | 1638 | 3731 threads, 30771 pairs in subagent threads |
| cc_local:claude_code | 30179 | 28668 | 174 | 23171 pairs in subagent threads |
| aiv_cc:claude_code | 35306 | 32310 | 117 | |
| swechat:codex | 6841 | 6394 | 63 | |
| swechat:opencode | 5332 | 4973 | 212 | |
| swechat:gemini | 1896 | 1692 | 21 | small |
| aiv_cu:anthropic | 22673 | 22671 | 748 | |
| aiv_cu:gemini | 11945 | 11945 | 347 | |
Cursor (8 sessions) and the aiv_cu OpenAI/compat strata log no usage (`build_counters`). Who&When has none either.

### A2. Usage-field semantics (clean pairs)
- **Logged output_tokens are often streaming partials** (`S:out_le_10_share_clean`): out_k <= 10 in 0.29 of swechat
  CC pairs, 0.193 of cc_local pairs and 0.885 of aiv_cc pairs. It is never or almost never <= 10 in Codex, OpenCode or
  Gemini (0.0-0.001). The plausible-final share (F) is 0.637 / 0.733 / 0.115 for those three CC units and >= 0.96
  elsewhere, except Gemini (0.207 in aiv_cu, where reasoning chars are counted as generated; 0.752 in Gemini CLI)
  (`S:out_final_share_clean`).
- **cc_local logs thinking blocks with 0 chars** in 18915 of 28668 clean pairs (`S:desc_flag_counts_clean.d_thinking_redacted`).
  Its appended-chars/dC ratio is 1.808 against 2.594 in swechat CC (`S:ratio_all_appended_chars_per_dC`). A
  chars-only model therefore cannot work on cc_local, which is why the hybrid model was added.
- Cache chain exact (cr(k+1) == cr(k) + cc(k)) in clean pairs: swechat CC 0.978, cc_local 0.982, aiv_cc 0.999,
  aiv_cu Anthropic 0.487, OpenCode 0.087 (OpenCode is mostly OpenAI models, so this identity does not apply)
  (`S:cache_chain_exact_clean`).
- Within a clean window, dC < 0 is rare: swechat CC 0.001 (92 pairs in 47 sessions), Codex 0.003, aiv_cu
  0.002-0.003, OpenCode and cc_local 0 or 1 pair. Gemini CLI is the exception at 0.032: 54 pairs in 6 sessions, with
  21 and 19 in two of them, at a median C_k of 333123 tokens against 192674.5 for all its clean pairs
  (`S:dC_negative_clean`, `S:dC_negative_clean_concentration`).

### A3. Chars per token of result text (M_hyb, 1 / beta_result, session-bootstrap CI; `S:models.M_hyb.result_chars_per_token`)
swechat CC 3.204 (3.179-3.229); cc_local 2.879 (2.326-3.024); aiv_cc 3.185 (3.137-3.22); Codex 3.621 (3.555-3.674);
OpenCode 4.631 (4.484-4.771); Gemini CLI 2.621 (2.517-2.855); aiv_cu Anthropic 2.734 (2.64-2.879); aiv_cu Gemini 3.264
(2.984-3.554). M_hyb also has newline and non-ASCII terms, so beta_result is not the whole per-char rate.
A model-light estimate uses pairs where one result of >= 2000 chars dominates: chars / (dC - out_k) =
swechat CC 2.833 (2.803-2.862, per-pair p5/p50/p95 2.093/2.874/3.626, n 12612), aiv_cc 2.638, Codex 3.783, OpenCode
3.732 (`S:single_result_dominated`). By model (`S:flags.per_model.*.result_chars_per_token`), swechat CC: opus-4-6
3.196, sonnet-4-6 3.478, haiku-4-5 3.259, opus-4-5 2.82, sonnet-4-5 2.92, opus-4-7 2.36 (CI 2.31-2.494, 12 sessions).
Codex: gpt-5.4 3.667, gpt-5.3-codex 3.295. OpenCode gpt-5.3-codex 4.764.

### A4. Honest residuals (out-of-fold, tokens; `S:models.<M>.oof_residual.abs`)
| unit | M_hyb abs p50 | p90 | p99 (CI) | signed p1 / p99 | M_chars p99 | M_out p99 |
|---|---|---|---|---|---|---|
| swechat CC | 51.7 | 377.8 | 2347.4 (2250.8-2481.9) | -1026 / 1949 | 2801.0 | 3094.5 |
| cc_local | 162.5 | 1323.6 | 5348.8 (3707.0-5876.0) | -3467 / 4418 | 5871.3 | 6591.3 |
| aiv_cc | 36.9 | 164.0 | 623.7 (499.9-752.9) | -346 / 467 | 770.1 | 1127.3 |
| Codex | 36.6 | 355.0 | 1893.5 (1190.2-4410.4) | -950 / 1336 | 2772.0 | 1948.6 |
| OpenCode | 30.7 | 420.0 | 1800.7 (1483.2-2541.6) | -1073 / 1472 | 2519.5 | 1831.7 |
| Gemini CLI | 48.6 | 1292.5 | 14476.3 (9647.6-20301.0) | -11746 / 9334 | 12212.2 | 12197.4 |
| aiv_cu Anthropic | 398.1 | 873.5 | 4320.2 (3750.5-5120.6) | -1039 / 3766 | 4786.6 | 4614.6 |
| aiv_cu Gemini | 437.9 | 864.7 | 3490.7 (2785.1-4440.9) | -907 / 3068 | 3594.0 | 3587.3 |
- The median pair conserves to tens of tokens in the coding scaffolds and the tail sets the threshold. The tail is
  skewed positive (the model saw more than was logged) in every unit except Gemini CLI.
- Model-aware fits (one cross-fit per model) do not shrink the tail. swechat CC p99 goes from 2347.4 to 2352.1,
  aiv_cu Anthropic from 4320.2 to 4730.6, cc_local from 5348.8 to 6951.7 (`S:flags.model_aware_oof_residual`).
  That is a null.
- cc_local subagent-thread pairs have |r| p99 5644 against 2271 for main-thread pairs
  (`S:flags.descriptive_clean.d_subagent_thread`). Fold thresholds differ (3918.5 vs 5418.1), and the realized FPR
  misses nominal: D_abs 0.019 (0.008-0.024), D_bin 0.047, D_asym 0.048 (0.014-0.107)
  (`S:detection_M_hyb.realized_fpr`). All other units except Gemini CLI land at 0.009-0.016 (Gemini CLI: D_bin 0.021,
  D_asym 0.031).

### A5. What breaks conservation
**Break flags** (non-clean pairs scored with the clean fit; exceed = share of |r| > clean q99; `S:flags.break.*`):
- Compaction resets the context. swechat CC: n 340, median residual -120568, exceed 1.0. aiv_cc: n 504, median -138278,
  exceed 1.0. Codex: n 31, median -183776.
- Images (the log keeps only an `[image]` marker). Single-image pairs: aiv_cc median 1036.0 tokens per image
  (1033.4-1036.8, p5-p95 1020-1144, n 2492), cc_local 822.1 (486.7-1422.8, n 450), swechat CC 531.8 (323.8-1168.7,
  p5-p95 104-1617, n 425) (`S:flags.single_image_residual_tokens`).
- Human user turns. swechat CC: n 10235, median -2.6, exceed 0.075, dC < 0 in 0.048. By model, dC < 0 at a user turn is
  0.26 for sonnet-4-5 (n 366) against 0.015 for opus-4-6 (n 7214), 0.007 for sonnet-4-6 and 0.021 for opus-4-5. The
  reasoning models drop more: Codex gpt-5.4 0.351 (n 231), gpt-5.3-codex 0.568 (n 74), OpenCode gpt-5.3-codex 0.468
  (n 233) (`S:flags.user_turn_only_by_model`).
- swechat CC, smaller groups: model switch n 111, exceed 0.405; unaligned generated events n 437, exceed 0.481;
  microcompact n 44, exceed 0.364; api_error n 119, exceed 0.126; unrecorded attachment text n 530, exceed 0.06.
- Codex results over 40k chars: n 101, exceed 0.594. **Codex saturation** (`codex_saturation.bins_result_chars`): for
  single-result pairs, dC - out_k rises with result size up to [30k,40k) chars (median 9338, n 16). Above that it caps:
  [60k,100k) median 12949 (n 5); [100k,300k) median 11611 with p5-p75 11602-11628 (n 14, 14 sessions; median result
  120249 chars). The model saw a fixed-size truncation and the log kept the whole output.

**Inside clean pairs** (residual with the flag vs without, out-of-fold; `S:flags.descriptive_clean.*`), swechat CC:
- Cache-read drop (cache miss): median -15.3 (-31.9, 30.3) vs -20.5, so C is unchanged by a miss in the typical case.
  The tail is not: exceed 0.163 vs 0.009, |r| p99 127632. Cache-chain break: exceed 0.059.
- Text redaction (`REDACTED` in the window): median +63.4 (45.2-76.6) vs -22.4, exceed 0.035 vs 0.009, n 7407. The
  logged text is shorter than what the model saw.
- Persisted output (the model saw a preview, which is what was logged): median +104.3 (86.1-125.0), exceed 0.035 vs
  0.01, n 961.
- Thinking: logged thinking exceed 0.018 (n 18680); thinking-only blocks logged with 0 chars exceed 0.023 (n 6294);
  pairs without either 0.009.
- Subagent (Task) results: median -77.9, exceed 0.011 (n 2426), no different from base. Subagent-thread pairs: exceed
  0.012 vs 0.009.

**Tools that carry content the log does not show** (single-tool windows; `S:flags.per_tool_single_tool_windows`):
- ToolSearch, swechat CC: 1117 of 1124 windows log 0 result chars, yet dC median is 1147. Residual median +890.1
  (736.7-991.5), exceed 0.198 (0.171-0.228). cc_local: 143 of 143 windows log 0 chars, median +2707.0.
- ExitPlanMode, swechat CC: logged result median 2833 chars, residual median -1334.7 (-1534.7, -1059.2), exceed 0.185.
  The log carries more than the model saw. The mechanism is not established.
- Skill: logged result median 33 chars, residual median -74.2 but |r| p99 10968, exceed 0.029. TaskOutput: exceed 0.06.
- aiv_cu `pause`, Anthropic: logged result median 23 chars, dC p99 28144 and p1 -5460, exceed 0.188 (0.122-0.26),
  n 436. Gemini pause: dC p99 4620, exceed 0.025.
- The well-behaved tools in swechat CC: edit |r| p99 686, grep 944, shell 1522, read 2979 (read alone is 591 of the 1415
  exceedances, against 32728 of 141477 pairs; `S:flags.exceedance_profile`). Exceedances split 1061 positive, 354
  negative.
- aiv_cu Anthropic: per-model residual medians run from -580.3 (opus-4-6) to +265.6 (opus-4-5). Logged-thinking pairs
  sit at +169.1 vs -141.9 (`S:flags.per_model`, `...d_thinking_logged`). Pairs that break the cache chain sit at
  |r| p99 6370 vs 1509.
- Gemini CLI: the dC < 0 tail of A2 (6 sessions, large contexts) dominates its p99.

### A6. Feasibility: smallest single-result length change detectable at FPR 1% (`S:detection_M_hyb`)
Grid values in chars. "Longer" means the logged result is longer than what the model saw (inserted content).
"Shorter" means deleted content; it needs a result at least that long, so n falls. 0.5 / 0.9 = detection power.
| unit | T_abs (fold0/fold1) | D_abs longer 0.5 / 0.9 | D_abs shorter | D_asym longer | D_asym shorter |
|---|---|---|---|---|---|
| swechat CC | 2469.3 / 2244.8 | 7943 / 8913 | 7943 / 11220 | 5623 / 6310 | 10000 / 14125 |
| cc_local | 3918.5 / 5418.1 | 7943 / 12589 | 11220 / 17783 | 3548 / 7079 (FPR 0.048) | 12589 / 19953 |
| aiv_cc | 590.1 / 666.4 | 1778 / 2239 | 1778 / 2239 | 1585 / 1995 | 1778 / 2512 |
| Codex | 2060.9 / 1705.7 | 8913 / 10000 | 8913 / 12589 | 7943 / 8913 | 10000 / 12589 |
| OpenCode | 1619.3 / 1908.1 | 7943 / 8913 | 7079 / 10000 | 6310 / 7079 | 10000 / 14125 |
| Gemini CLI | 14483.1 / 11971.4 | 35481 / 50119 | not reached | 39811 / 56234 | not reached |
| aiv_cu Anthropic | 4580.2 / 4145.0 | 15849 / 22387 | 11220 / 17783 | 4467 / 7079 | 15849 / not reached |
| aiv_cu Gemini | 3490.0 / 3481.9 | 11220 / 15849 | 8913 / 22387 | 3548 / 7079 | 14125 / 25119 |
- Power at +3000 chars (D_abs): swechat CC 0.011 (0.01-0.012), Codex 0.01, OpenCode 0.021, aiv_cc 0.989 (0.984-0.994)
  (`...power.abs.longer.at.3000`). At +10000 chars: swechat CC 0.972, Codex 0.964, OpenCode 0.977.
- D_bin, aiv_cc: 891 / 1585 chars longer, 891 / 1259 shorter.
- **Tool-aware thresholds** (`S:detection_M_hyb_by_tool`, D_asym longer, 0.5 / 0.9): swechat CC edit 1122 / 1585, shell
  1259 / 1995, grep 1122 / 1778, read 7943 / 10000, toolsearch 3162 / 11220; aiv_cc gui 282 / 501, get_events
  1413 / 1778, shell 1778 / 2239; Codex shell 4467 / 5623; aiv_cu Gemini get_pixel_coords 1259 / 2818.
- Relative changes by result size (`S:detection_M_hyb.by_result_size`). In swechat CC, deleting a whole result
  (new length 0) is caught for results of 10k-100k chars at D_abs power 0.986. For 1k-10k chars the power is 0.118,
  and under 1k chars it is 0.003-0.01, no better than the FPR. Adding three times a result's own length in the 1k-10k
  bin: D_asym 0.707. In aiv_cc, deleting a 1k-10k result: 0.985.
- Model-aware detection gives no improvement. swechat CC D_abs is still 7943 / 8913, and aiv_cu Anthropic worsens to
  15849 / 44668 (`S:detection_M_hyb_model_aware`).

### A7. aiv_cu Gemini: TEXT vs IMAGE prompt tokens (`aiv_cu_gemini_text_image`)
- TEXT + IMAGE == promptTokenCount in 11945 of 11945 pairs.
- The IMAGE channel is exactly quantized. Every dIMAGE value is 0 or one per-model unit: 11668 of the 11668 pairs whose
  model has a unit. The units are 258 for gemini-2.5-pro and 1064 for gemini-3-pro, 3.1-pro and 3.5-flash. dIMAGE is
  never negative, and up to 40 images stay in context (no screenshot window). dIMAGE > 0 in 5059 of 5092 gui-action
  windows and in 0 of every other window type (shell 0/4134, get_pixel_coords 0/2033, pause 0/202, ...).
- Modelling TEXT tokens alone cuts the bulk of the residual but not the tail. TEXT |r| p50 137.4 / p90 615.4 / p99
  3422.4, against all-prompt 437.9 / 864.7 / 3490.7. D_abs longer: 11220 / 12589 chars (TEXT) vs 11220 / 15849 (all).

---------------------------------------------------------------------------------------------------------------------

## B. Interpretation (not data)

**Conservation holds per call, and it is tight at the median.** In every scaffold with usage, the server's
context increment tracks the logged appended content. Median out-of-fold error is 30.7-51.7 tokens in the swechat
scaffolds, 162.5 in cc_local and 36.9 in aiv_cc. The cache chain is exact in 0.978 / 0.982 / 0.999 of Claude Code
pairs (swechat / cc_local / aiv_cc), so context grows by pure appending almost all the time. Result text runs 2.36-3.478
chars/token across swechat Claude Code models and 3.295-4.764 across OpenAI models, all from the data alone, with no
tokenizer. The aiv_cu per-model estimates are wide (point values 1.808-4.479, `fmt.aiv_cu:anthropic.flags.per_model`).

**The feasibility answer is "only large edits, unless the verifier is tool-aware".** With one threshold per scaffold
at FPR 1%, inserting or deleting roughly 5.6k-14k chars (grid values 5623-14125) in one result is the 50-90%
detection point for swechat Claude Code, Codex and OpenCode. A 3k-char insertion is invisible: power 0.01-0.021 against
an FPR of 0.01. The aiv_cc stream is much tighter, with grid values 1585-2512 chars. The thresholds are set by tails, and the tails come from identifiable sources:
- ToolSearch-style results whose logged text is empty while the model received tool schemas
- ExitPlanMode
- Skill and TaskOutput
- Read windows
- unlogged context edits around cache misses
- partial output_tokens in Claude Code logs

Thresholds set per tool in the window drop the detectable change for edit, grep and shell windows to about
1.1k-2.0k chars, and for aiv_cc screenshot actions to 282-501 chars. Equal-length or equal-token substitutions remain
undetectable by construction.

**Natural experiment.** SWE-chat's own secret redaction is a real, honest-data edit of logged text that shortens it.
Redacted windows show the predicted positive residual shift (median +63.4 against -22.4) and exceed the threshold at
0.035 against 0.009. The method responds to real edits in the expected direction.

**Scaffold-specific blind spots** (also false-positive sources):
- Codex truncates large tool outputs (dC - out_k caps at a median of 11611 tokens for results of 100k-300k chars).
  The log keeps the full output, so edits in the hidden part of a result above about 60k chars cannot be detected, and a
  naive check flags such results (exceedance 0.594 for results over 40k chars).
- Compaction and microcompaction reset the context.
- Human turns strip earlier thinking (sonnet-4-5) and reasoning (GPT-5 models): dC < 0 in 0.26 to 0.568 of those
  pairs, against 0.015 for opus-4-6.
- Gemini CLI drops context inside turns at very large sizes, with no marker in the log.
- aiv_cu `pause` turns take in content the log does not show (dC p99 28144 tokens against a 23-char logged result).
- Image tokens are only estimable: 1036.0 per image in aiv_cc, and a wide p5-p95 range of 104-1617 in swechat CC,
  where images vary in size.

**The cleanest witness is the Gemini modality split.** IMAGE prompt tokens move in exact per-model units, only on
screenshot-returning actions. That is an integer ledger of screenshots seen. It would expose an inserted, removed or
duplicated screenshot turn with no tokenizer error. The gui windows without an image increment (5059 of 5092 have
one) are the false-positive floor still to explain.

**Nulls (as prominent as the hits).**
- Model-aware fits do not shrink the honest tail in any unit (swechat CC p99 2347 -> 2352; aiv_cu Anthropic and
  cc_local get worse).
- cc_local cannot hold its nominal FPR. With 174 sessions dominated by subagent threads, realized FPR is 0.019-0.048,
  so its thresholds are not transferable between folds.
- Gemini CLI (21 sessions) has an honest p99 of 14476 tokens. Conservation there detects only edits of 35k+ chars.
- For results under 1k chars, no detector beats the FPR for deleting or doubling the result, in any unit.
- Splitting out IMAGE tokens does not shrink the TEXT tail (p99 3422 vs 3491).
- A real tokenizer was not used (no new dependencies). Every residual floor here is an upper bound.

**Novelty (UNVERIFIED).** I have not checked the literature. The following may not be described as fabrication checks
for agent tool logs:
- context-delta conservation with cross-fitted thresholds and tool-aware calibration
- the Gemini IMAGE-token screenshot ledger
- using benign redaction as a natural tamper calibration
