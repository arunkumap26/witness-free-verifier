# Phase C lens: distributions (the shape of every numeric quantity, per corpus)

- Script: `analysis/probes/phase_c_distributions.py`
  (`PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_c_distributions`, about 45 s, single process).
  Two full reruns produced identical JSON apart from `wall_seconds`.
- Data: `analysis/out/phase_c/distributions.json`. Every number below is in that JSON. Paths use this notation:
  - `P[...]` = `profiles["corpus|stratum|quantity"]`
  - `PH.x` = `posthoc.x`
  - `S.x` = `summary.x`
  - `ST` = `strata`
- Inputs: Phase B IR caches only, plus `swechat_population.parquet` (5,850 sessions), `aiv_cu_sessions.parquet` (78,114
  sessions) and `whowhen_labels.json`.
- Phase B sessions (`corpus_info`):

  | corpus | sessions |
  |---|---|
  | swechat | 2,000 (claude_code 1,679, opencode 214, codex 77, gemini 22, cursor 8) |
  | aiv_cu | 2,000 (10 strata) |
  | cc_local | 186 |
  | aiv_cc | 189 |
  | whowhen | 111 |

- cc_local is private. The JSON holds only numbers, built-in tool classes (others are folded into `other`) and harness enum
  labels.

**Rules.**
- Fixed before the first run: `prereg`. They cover step detection, the spike rule, the mode rule, Hill k, round-number divisors, the
  score, and min_n = 200 values and 5 sessions.
- `changes_after_test_run` records two changes made after a test run on whowhen and aiv_cc:
  - min_n for session-level quantities was lowered to 100, because aiv_cc has 189 and cc_local 186 sessions. This is a coverage
    change, not a change to any outcome.
  - A unit bug was fixed: pandas 3 parses timestamps to microseconds.
- Everything added after looking at the first full run is listed in `posthoc_rules` with its motivation:
  - blocks `ph1` to `ph10`
  - the `summary` tallies, including the definition of "featureless"
- Treat post-hoc numbers as hypotheses.

**Statistics.**
- Rates use a session-clustered bootstrap (`lib/stats.cluster_rate`), or Wilson when each session contributes exactly one value.
- Mode-count stability, p99/p50 and Hill CIs come from 400 session-bootstrap resamples (`prereg.B_SHAPE`).
- The ranking in section 2 is my judgment, informed by `ranking_by_prereg_score`. The raw score puts agent-chosen timeouts on
  top because they are spiky, round and quantized. I moved those down because they are expected.

---------------------------------------------------------------------------------------------------------------------

## Part A: Numbers

### 1. Coverage and how often each shape feature occurs (`summary`)

| Item | Count | Path |
|---|---|---|
| Quantity × stratum profiles | 922 | `S.profiles_total` |
| Fully profiled | 690 | `S.profiled` |
| Below min_n | 228 | `S.too_small` |
| Empty | 4 | `S.empty` |

Flags among the 690 profiled quantities:

| Flag | Count | Path |
|---|---|---|
| ≥ 1 spike | 278 | `S.with_spike` |
| ≥ 2 modes | 183 | `S.with_multimodal`; by mode count: 132 two, 41 three, 8 four, 2 five (`S.n_modes_distribution`) |
| Round-number flag | 31 | `S.with_round` |
| Negative values | 23 | `S.with_neg` |
| Hill CI upper bound < 2 | 62 of 486 tails measured | `S.with_hill_hi_lt2`, `S.with_tail_measured` |
| Hill CI upper bound < 1 | 7 | `S.with_hill_hi_lt1` |
| **Featureless** (one mode, no spike, no round flag, no negative) | **293** | `S.with_featureless` |

### 2. The 15 most surprising shapes, ranked, with mechanical causes

Cause status: **measured** (a check in this script shows it), **inferred** (the shape fits a known mechanism, but nothing here
proves it), or **unknown**.

**1. Codex `reasoning_output_tokens` lands on a lattice at 516 + 518k.** (`PH.ph5_reasoning_lattice`)
- Usage-bearing token_count rows:

  | value | rows | sessions | count at each of the ±4 neighbours |
  |---|---|---|---|
  | 516 | 111 | 27 | 1, 4, 5, 3 / 0, 1, 0, 0 |
  | 1034 | 16 | 10 | 2, 2, 1, 1 / 0, 0, 0, 0 |
  | 1552 | 2 | | |
  | 2070 | 5 | | |
  | 2588 | 4 | | |
  | 3106 | 1 | | |
  | 3624 | 0 | | |
  | 4142 | 1 | | |

- Share of rows on the lattice: 140/6910 = 0.020 [0.016, 0.028], in 68 sessions.
- By model: gpt-5.4 has 136 of 140 on-lattice rows (out of 5,809 rows), gpt-5.4-mini 3 of 101, gpt-5.3-codex 1 of 1,000.
- The profile, which also counts repeated token_count rows, gives 516 at count 138, share 0.0193, 85.8× its local density
  (`P["swechat|codex|extra.meta.reasoning_output_tokens"].spikes[0]`).
- Cause: **unknown**. The counter is written by the provider. The neighbours are empty above each lattice point, not on both
  sides, which looks like a counter that snaps or saturates.

**2. Exactly 41 turns in 46% of all AI Village computer-use sessions.** (`PH.ph4_turn_cap`)
- Overall: 35,684/78,114 = 0.457 [0.453, 0.460].
- By stratum the share runs from 0.226 (openai-chat) to 0.677 [0.663, 0.690] (anthropic-haiku).
- Agent-SDK stratum: 1/862. Its loop is different, and it shows no spike.
- 31,360 of the 41-turn sessions have exactly 1 synthetic bootstrap turn, and 31,473 sessions overall have exactly 40 model
  turns.
- Neighbouring values: 40 turns 1,514; 42 turns 4,300; more than 41 turns 7,024.
- Cause: **inferred**, a harness cap of 40 model turns plus 1 synthetic turn. The data contains no harness configuration.

**3. Gemini image prompt tokens sit on a per-image lattice.** (`PH.ph8_gemini_image_tokens`)
- gemini-flash `promptTokensDetails.IMAGE`: divisible by 1064 in 3219/3219 rows (90 sessions).
- gemini-pro: divisible by 258 or by 1064 in 10499/10569 = 0.993 [0.984, 1.0]. Divisible by 258: 0.604. Divisible by 1064:
  0.389.
- Spike mass: 0.993 (flash) and 0.989 (pro) of all values (`P["aiv_cu|gemini-*|extra.call.usage_detail.promptTokensDetails.IMAGE"].spike_mass`).
- Cached image tokens are **not** on the lattice: 11/3022 (flash) and 40/9318 (pro). Their parity is 0.495 and 0.490, which is
  what random numbers give.
- Cause: **measured** lattice, **inferred** mechanism: a fixed token cost per image, with two sizes on pro. The prompt-side
  count therefore reports how many images were in context.

**4. Edit and Write calls have a plateau at 5.0 to 5.2 s, in 73 Claude Code sessions.** (`PH.ph2_edit_5s_plateau`, `P["swechat|claude_code|latency_ms[edit]"]`)
- Edit latency has modes at 11.5 ms and about 4,870 ms (stability 0.78), with exact-value spikes at 5014 to 5021 ms.
- Share of calls in [4900, 5200) ms:

  | tool | share | n | sessions |
  |---|---|---|---|
  | Edit | 0.022 [0.011, 0.038] | 644/28,793 | 73 |
  | Write | 0.006 | 28/4,478 | |
  | Read | 0.0001 | 7/55,258 | |

- Inside the plateau:
  - The PostToolUse hook's progress event comes a median 5,020 ms after the call and 1 ms after the result's timestamp.
  - PreToolUse progress appears on 4 of 644 plateau calls, against 5,588 of 26,323 Edit calls under 1 s.
- Cause: **unknown**. The time is spent inside the tool, before PostToolUse. It occurs only for file mutations and only in some
  environments. A fixed wait, such as an editor or diagnostics timeout, is a guess. **UNVERIFIED.**

**5. Claude Code truncates shell output at about 10,040 chars on failure and 30,000 chars on success. OpenCode truncates near 51,550.** (`PH.ph1_caps`)
- swechat CC, results starting "Exit code" (n = 3,237):
  - 205 results in 122 sessions are within 1% of the maximum (10,050).
  - The pile is at 10,039 (100 results) and 10,040 (79).
  - Non-failure results peak at 29,766, with no pile.
- cc_local: success maximum is exactly 30,000 (3 results at the maximum, 12 within 1%, in 3 sessions). Failure p99 is 10,039.
- aiv_cc: failure maximum is 10,040 (5 results within 1%).
- OpenCode shell: 91/1,859 results in 85 sessions are within 1% of 51,551. The p99 is 51,541.
- Cause: **inferred**, harness truncation limits. The two Claude Code limits split cleanly by exit status.

**6. `updated_at` in AI Village is a copy of `created_at`, not a second clock.** (`PH.ph3_updated_at`)
- 59,834/59,956 result rows (1,979 sessions) differ by at most 0.01 ms. The median is 0.002 ms
  (`P["aiv_cu|anthropic-opus|derived.result.updated_at_minus_ts_ms"].describe`).
- 17 rows (17 sessions) differ by more than 1 s: 0.00028 [0.00015, 0.00043]. None is negative.
- None of those 17 is a redacted screenshot, against 367 redacted rows overall.
- Cause: **inferred**, both fields set at insert. The raw census had listed this field as an uncaptured second clock. It
  carries no independent timing for 99.8% of rows.

**7. Uncached input tokens collapse to one or two constants per harness.**

| Corpus / stratum | Value: share | Path |
|---|---|---|
| swechat CC | 1: 0.697 (110,225/158,061); 3: 0.135. Hill α 0.445 [0.396, 0.507] | `P["swechat\|claude_code\|usage_in"]` |
| cc_local | 2: 0.922 | `P["cc_local\|all\|usage_in"].small_values_top5` |
| aiv_cc | only 8 (0.858) and 10 (0.142), so the detected step is 2 | `P["aiv_cc\|all\|usage_in"]` |
| aiv_cu Agent-SDK | 8 (0.845) and 10 (0.155) | `P["aiv_cu\|anthropic-claude-code\|usage_in"]` |
| aiv_cu direct API, value 10 | opus 0.259, sonnet 0.249, haiku 0.436 | |
| aiv_cu direct API, value 2 | opus 0.186, sonnet 0.191; fable 2: 0.857 | |

- Cause: **inferred**. With prompt caching only the newest suffix is uncached, so the constant is that suffix's framing cost.
  This matches aiv_accounting ("uncached input median 8, p99 10").

**8. File order is not time order.**
- swechat CC:
  - 0.047 [0.044, 0.050] of consecutive gaps are negative: 40,243/855,208 (`P["swechat|claude_code|gap_ms"].negative`).
  - hook_progress → result gaps: 0.529 [0.504, 0.554] negative and 0.428 zero.
  - 57 results come before their own call in seq (`ST.swechat.claude_code.result_seq_before_call`).
- OpenCode result → call gaps: 0.300 [0.251, 0.367] negative.
- Cause, Claude Code: **measured**. The result carries the tool-completion stamp, and the PostToolUse hook progress is stamped
  1 ms later (`PH.ph2...median_ms_PostToolUse_minus_result_ts` = +1) but written earlier in the file.
- Cause, OpenCode: parallel tool parts (loader docstring).

**9. Claude Code's bash_progress events tick at 1 Hz with 0 to 4 ms of jitter.** (`P["swechat|claude_code|gap_ms[meta:bash_progress>meta:bash_progress]"]`)
- 0.877 [0.848, 0.902] of 115,088 gaps (668 sessions) sit on spike values 1000 to 1004 ms and above.
- By value: 1001 is 0.319, 1000 is 0.176, 1002 is 0.169, 1003 is 0.083. The p50 is 1001 ms and the p99 1219 ms.
- The same ticks produce:
  - a spike mass of 0.117 in the pooled gap_ms
  - its round-number flag: divisible by 100 in 0.060 [0.053, 0.068] of gaps, against 0.01 expected
- Cause: **inferred**, a 1 s timer.

**10. Call-to-result latency has a tail index near 1, and timeouts explain only part of it.**
- Hill α:

  | Quantity | Hill α |
  |---|---|
  | swechat CC latency | 1.028 [0.975, 1.091] (top-k drawn from 821 sessions; the largest session holds 0.038) |
  | cc_local latency | 1.007 [0.757, 1.221] |
  | OpenCode latency | 0.580 [0.438, 2.626] |
  | swechat CC consecutive gaps | 0.765 [0.731, 0.800] |

- swechat CC p99/p50 = 2513 [2054, 3162].
- Timeouts (`PH.ph6_timeout_hits`), swechat CC:
  - Calls with a timeout argument that reached it: 535/14,166 = 0.038 [0.031, 0.045].
  - Of those, ended within 5 s after the timeout: 295, 0.021.
  - Calls without a timeout argument that ran ≥ 120 s: 0.015. In [120, 125) s: 0.0022.
  - Shell calls in the top 1% (≥ 245 s): 56 of 611 ended at a timeout. cc_local: 27 of 269.
- Cause: **measured** for the timeout part. The remainder is **unknown**: no human-approval or background field in the IR.

**11. Logged output-token counts are streaming snapshots, with a mode at 1.**
- swechat CC usage_out (`P["swechat|claude_code|usage_out"]`):
  - Equals 1 in 0.169 of responses.
  - Has 3 modes (1, 27 and 154 tokens), stable in 400/400 resamples.
  - Spikes at 25 (0.040, 723 sessions) and 19 (0.014).
- Share equal to 1: aiv_cc 0.618; aiv_cu Agent-SDK 0.680.
- Spikes at 8000 (13 values, 9 sessions, swechat CC) and 8192 (12 values, 2 sessions, aiv_cu opus) look like max-token caps.
  That is unverified, because the IR has no stop_reason.
- Cause: **inferred**, per-block rows written mid-stream. aiv_accounting reached the same conclusion.

**12. Polling loops return identical outputs thousands of times.**
- aiv_cc get_events: 1,568 results of exactly 3,764 chars (3 sessions) and 1,287 of 3,679 chars (3 sessions; the top session
  holds 0.998). Each is an empty-feed payload, prefix `{"events": [], "hasMore": false` (`PH.ph10...aiv_cc|all|result|3764`).
- Spike mass in get_events results: 0.558 [0.497, 0.602] of 18,239.
- Codex `yield_time_ms` is 1,000 in 0.894 of exec calls.
  - Of the 3,382 calls with yield 1,000 (27 sessions), latency lands in [yield, yield + 300 ms) for 0.329 [0.061, 0.390].
  - 2,233 return earlier. Median latency minus yield is −110 ms (`PH.ph9_codex_yield`).
  - Latency spikes at 1,158 to 1,161 ms come from at most 4 sessions (top-session share ≥ 0.95).
- Cause: **measured**, polling plus the unified-exec yield window.

**13. Harness templates make tool-output lengths spiky.** (`PH.ph10_template_attribution`)

| Corpus | Template or length | Count / share |
|---|---|---|
| swechat CC | TaskUpdate results at 22 chars ("Updated task #N status") | 0.738 (3,506/4,748) |
| swechat CC | Grep "No matches found" (16 chars) | 0.160 |
| swechat CC | Glob "No files found" (14 chars) | 0.217 |
| swechat CC | "(Bash completed with no output)" (31 chars) | 2,343 |
| swechat CC | TodoWrite result template (160 chars) | 1,309 |
| swechat CC | `<local-command-caveat>` system text (245 chars) | 1,769 |
| cc_local | `total_tokens_reminder` attachments, two lengths: 86 and 49 chars | 13,611 + 12,054 of 36,306 system events |
| aiv_cu | "Message successfully sent back to chat" | 2,615 |
| aiv_cu | "Paused for N seconds." (22 or 23 chars) | |
| whowhen Hand-Crafted | "Next speaker WebSurfer" | 331 of 934 assistant events |
| whowhen Algorithm-Generated | "There is no code from the last 1 message…" | 36/36 system events |

- Cause: **measured**, from the template prefixes and enum labels.

**14. aiv_cc's stderr and Read channels hold mostly harness notices.**
- stderr: 0.470 [0.221, 0.694] of 4,919 values are one 93-char notice, "Shell cwd was reset to /home/<user>…", in 19 sessions.
  The other 0.530 are empty (`P["aiv_cc|all|stderr_chars"]`).
- Read results: 2,530/2,914 = 0.868 are the 7-char string `[image]`.
- Cause: **measured**. Images were stripped from the export, and the cwd-reset notice comes from the harness.

**15. Numbers the agent chooses are round and come from a small vocabulary.**
- swechat CC shell `timeout` (`P["swechat|claude_code|args.shell.timeout"]`):
  - 0.978 of 14,195 values sit on 16 spike values.
  - 120,000 ms is 0.272 (643 sessions), 30,000 is 0.197, 60,000 is 0.159, 300,000 is 0.105.
  - All 736 values ≥ 600 s are whole minutes.
- head/tail `-n`: values ≥ 100 are multiples of 10 in 875/878 = 0.997 [0.992, 1.0]. Common values: 20 (0.237), 5 (0.169),
  10 (0.132), 30 (0.122).
- sleep: all 709 values ≥ 10 s are whole seconds, and all 138 values ≥ 600 s are whole minutes.
- read.limit: values ≥ 100 are multiples of 10 in 0.986.
- Timeout arguments above 600,000 ms: 88 in swechat CC and 704 of 2,432 in cc_local (`PH.ph6`).
- Cause: model-chosen parameters, which is expected. 120,000 ms is Claude Code's default, written out explicitly.

**Also notable, outside the top 15:**
- Codex `model_context_window` takes only two values: 258,400 (0.775) and 950,000 (0.225), 77 sessions.
- The first-request prompt size repeats across sessions:
  - OpenCode usage_in 7,174 occurs once in each of 52 sessions, and 7,222 in 28.
  - OpenCode: a 4,657-char "You are a code reviewer…" prompt opens 106 of 214 sessions.
  - cc_local: a 2,074-char user text appears once in each of 150 of 186 sessions.
- The Glob result cap of 100 files:
  - cc_local numFiles = 100 in 337/861 = 0.391 of results (96 sessions)
  - swechat CC: 70 results
- The Gemini HTTP `date` header precedes the row's `created_at`:
  - in 3264/3264 rows (flash) and 9028/9028 (pro)
  - medians −4.4 s and −4.6 s; the closest are −78 ms and −112 ms
  - (`P["aiv_cu|gemini-*|derived.call.http_date_minus_ts_ms"]`)
- OpenCode cache_read is flagged as round, divisible by 100 in 0.040 [0.034, 0.045] against 0.01 expected.
  - That follows from its 128-token granularity: 0.953 of values are multiples of 128 (`step_shares["128"]`).
  - One multiple of 128 in 25 is divisible by 100.

### 3. Parser and IR surprises (data about the pipeline)
- `[Request interrupted by user]` and `[Request interrupted by user for tool use]` are harness strings, but the IR files them
  under kind `user` (`PH.ph7_interrupt_markers_as_user`).
  - swechat CC: 862/12,964 = 0.066 [0.059, 0.074] of user events, in 433 sessions.
  - cc_local: 42/623 = 0.067 [0.039, 0.086], in 12 sessions.
  - This inflates `user_text_chars` (spikes at 29 and 42), `session.n_user` and `calls_per_user_event`.
- In aiv_cu (`shared_turn`), call → result latency is 0 in all 59,956 pairs. This is by construction (`ST.aiv_cu.*.shared_turn_latency`).
- In swechat Gemini, the assistant → call gap is 0 in 1482/1482 cases, because the call's timestamp is the message's timestamp.
- 57 swechat CC call/result pairs have the result before the call in seq (item 8 above).
- Two estimator artifacts:
  - Hill α on capped or discrete quantities comes out absurdly large, for example 6,349.5 for aiv_cc stderr length and 209,208
    for Codex model_context_window. It marks a hard maximum, not a light tail.
  - The binned bootstrap CI for p99/p50 can exclude the point value on discrete data, for example head_tail_n 10.165 against
    [10.366, 10.366].

### 4. Nulls (reported with the same weight as the hits)
- **No timestamp quantization anywhere.**
  - The ms field equals 000 at the expected 1/1000 rate in every stratum: swechat CC 0.00096 [0.00087, 0.00104] of 856,886
    (`ST.swechat.claude_code.ts_quant.ms_eq_000`); aiv_cc 0.00104.
  - Multiples of 10 ms appear at about 0.1 everywhere (swechat CC 0.1002).
  - No source writes second-truncated stamps.
- **293 of 690 profiled quantities are featureless.** That includes 93 of 192 session-level shapes and 92 of 148 extra-field
  shapes (`S.featureless_by_family`, `S.profiled_by_family`).
- **Thinking and reasoning lengths are unremarkable.** 38 profiles: 32 featureless, 3 with spikes, 3 multimodal
  (`S.thinking_reasoning`).
- **Round-number excess is rare and always mechanical.** 31 flags in total (`S.with_round`). All are one of:
  - an agent-chosen parameter (timeouts, sleep, head/tail, read limit/offset, pause, get_events limit)
  - a harness counter (Glob numFiles, progress timeoutMs, totalLines)
  - the 1 Hz timer
  - the 128-token cache granularity
  - one Agent-SDK cache_create flag: 0.039 against 0.01
  - None appears in text lengths or latencies.
- **Session-level shapes:**
  - The only session-length spike is aiv_cu's 41 turns.
  - swechat CC tool-mix entropy is unimodal (1 mode, stability 1.0, 1,651 sessions).
  - aiv_cu turn gaps are unimodal in 9 of 10 strata, with p50 11.5 to 17 s.
- **whowhen supports almost nothing here.**
  - It has no timestamps.
  - Its session-level quantities, including mistake_step, fall below min_n (78 and 33 sessions).
  - Only text lengths are profiled.
- **Cursor has no timestamps and no results.** Its 8 sessions are below min_n for almost everything.

---------------------------------------------------------------------------------------------------------------------

## Part B: Interpretation (not data)

1. **The sharpest shapes are written by the server or the harness, not by the model.**
   - Server-written:
     - the Gemini per-image token lattice
     - Codex's 128-token cache grid
     - the Codex reasoning lattice
   - Harness-written:
     - the 1 Hz progress tick
     - template-length results
     - uncached-input constants
     - output caps
     - the 41-turn cap
   - Each is a regularity that a log writer, human or LLM, would have to reproduce by accident.
   - Two kinds of check follow from this:
     - **Plausibility checks on reported numbers.** On Gemini, prompt-side image tokens are on the lattice in ≥ 0.99 of rows,
       so an off-lattice value is suspect. The Codex reasoning lattice is weaker: only 0.020 of rows sit on it, so it works as
       a model fingerprint, not a per-row validity rule.
     - **Harness-conformance checks.** Examples: progress cadence, exact template strings, the right uncached-input constant
       for the claimed harness, no shell output longer than its cap. These test whether a log came from the claimed
       harness. They do not test whether a tool result is true.
2. **Several shapes are false-positive traps for any timing or length detector:**
   - **Order.** 4.7% of honest consecutive Claude Code gaps are negative, and 30% of OpenCode result → call gaps are negative.
   - **Tails.** α ≈ 1 means tail-based latency anomalies cannot be calibrated. Mean and variance do not exist, and timeouts
     explain only 56 of the 611 shell calls in the top 1%.
   - **Environment plateaus.** 2.2% of honest Edit calls in 73 sessions take a fixed 5 s.
   - **Censoring.** 46% of aiv_cu sessions end at the turn cap, not at task completion.
   - **Snapshots.** Logged output_tokens equal 1 in 17 to 68% of responses, so per-response output size is unusable.
3. **One second-clock idea is dead, one survives.**
   - `updated_at` carries no information.
   - The Gemini HTTP Date precedes the row insert in 100% of 12,292 rows, with a minimum margin of 78 ms. That is a strict
     inequality a fabricated row could violate. Its resolution is 1 s, so it constrains only gross time edits.
4. **Agents speak in round numbers, harnesses do not.** Flagged agent-chosen arguments are 0.87 to 1.0 round (sleep,
   head/tail, timeouts, read.limit, pause); read.offset is lower (0.44 to 0.66). Harness clocks and counters show no
   round-number excess except where an agent's choice is echoed (progress timeoutMs, totalLines), a cap is hit (Glob
   numFiles = 100) or a timer is involved.
   A clock reading that is suspiciously round is evidence of a narrated, not measured, value. This echoes ext_witness's
   finding on round epochs; here it is the agent's arguments, not narrated clocks, that are round.
5. **Several fixed values identify a scaffold version or an automation.** Examples: the identical first-request prompt sizes
   (OpenCode 7,174 tokens in 52 sessions), the 4,657-char reviewer prompt, cc_local's 2,074-char prompt, and Codex's two
   context-window constants. A log claiming to come from scaffold X at version V can be checked against these. Some of these
   constants also reveal dataset composition: automated review runs make up 106 of 214 OpenCode sessions.

## Candidate mechanisms (novelty UNVERIFIED for all)
1. **Provider usage-lattice plausibility check.**
   - Rule: prompt-side image tokens must be a sum of per-image costs (Gemini: 1064 or 258); cache reads must be multiples of
     the provider block (Codex: 128).
   - Grounded in `PH.ph8` and `P["swechat|codex|usage_cache_read"].step = 128`.
   - Honest on-lattice rate: 10,499/10,569 on pro, 3,219/3,219 on flash.
2. **Harness-conformance fingerprint.**
   - What to check:
     - bash_progress cadence: 0.877 within 1000 to 1004 ms
     - exact template strings and lengths
     - the uncached-input constant per harness: 1, 2, or 8/10
     - output never above the harness cap: 30,000 / about 10,050 / 51,551
   - Grounded in items 5, 7, 9 and 13.
   - False-positive sources:
     - scheduling jitter: only 0.877 of ticks are on cadence
     - template and cap changes across versions
     - the 10,050 maximum against the 10,039/10,040 pile
3. **Strict server-clock ordering (Gemini HTTP Date < row insert).** 12,292/12,292 hold. False-positive source: clock skew.
   It has 1 s resolution.
4. **Reasoning-token lattice as a model fingerprint.** A gpt-5.4 log should show about 2% of token_count rows on 516 + 518k.
   This is a corpus- or session-level test, not a per-row one. Grounded in `PH.ph5`. The mechanism is unknown.

## Could not measure
- Why the Edit/Write 5 s plateau exists. The IR has no environment, IDE or hook-configuration fields; hooks are excluded,
  since PreToolUse appears on only 4 of 644 plateau calls.
- Why Codex reasoning tokens snap to 516 + 518k. Only token_count events exist.
- Whether 41 turns is a configured cap. The data has no harness configuration.
- What fills the latency tail beyond timeouts: human permission waits and backgrounded commands are not in the IR.
- Whether the 8,000 and 8,192 output spikes are max-token stops. stop_reason is not in the IR.
- whowhen shapes (no timestamps; sessions below min_n), Cursor (no timestamps or results), and content-level attribution
  for cc_local (private; enum labels only).
- Sub-second ordering against the Gemini HTTP date (the header has 1 s resolution).
