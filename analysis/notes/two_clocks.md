# Phase C lens `two_clocks`: pairs of clocks/timers on the same event, and the inequalities between them

- Script: `analysis/probes/phase_c_two_clocks.py`. Run it with `PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_c_two_clocks`. A full run takes about 40 s and needs no GPU.
- Data: `analysis/out/phase_c/two_clocks.json`. It holds raw counts only. Every number below is in that JSON, and the path after a number is relative to its root.
- Split: Phase B caches throughout (`swechat_B`, `cc_local_B`, `aiv_cc_B`, `aiv_cu_B`).
- Raw reads are restricted to B sessions: SWE-chat Claude Code and OpenCode transcripts, and cc_local root main files for `cost-state`.
- cc_local is private: only aggregates of it appear.

Conventions:
- **slack** is defined per pair so that the physical inequality holds iff slack >= 0 (ms).
- Violations are counted at three levels:
  - the pre-registered tolerance (`PREREG.tol_ms_event_clock` = 2 ms; 1 ms for the AI Village µs clocks);
  - at 0;
  - "gross" (beyond 1 s).
- Rates are session-clustered (`rate_violation_tol`). For 0 events the clustered CI is the degenerate [0, 0], so the pair-level Wilson upper bound is also given (`wilson_violation_tol.hi`).
- Pre-registered thresholds are in `prereg`. Everything added after a section's first run is listed in `post_hoc` and carries a `POSTHOC_` prefix where possible.
  - Run 0 had a unit bug (pandas 3 inferred µs/ms resolution). It was fixed before any number was read (`post_hoc.time_conversion_fix`).

---------------------------------------------------------------------------------------------------------------------

## Part A. Numbers

### A1. Inventory of clock pairs measured

| # | corpus | clock 1 | clock 2 | inequality | n | viol @tol | path |
|---|---|---|---|---|---|---|---|
| 1 | swechat CC | Glob `durationMs` | result.ts − call.ts | gap ≥ timer | 2109 | 1 | `cc_result_timers.swechat.pairs.Glob\|durationMs` |
| 2 | swechat CC | WebFetch `durationMs` | gap | gap ≥ timer | 341 | 0 | `...pairs.WebFetch\|durationMs` |
| 3 | swechat CC | WebSearch `durationSeconds` | gap | gap ≥ timer | 158 | 0 | `...pairs.WebSearch\|durationSeconds` |
| 4 | swechat CC | Task / Agent `totalDurationMs` | gap | gap ≥ timer | 1023 / 1886 | 0 / 0 | `...pairs.Task\|...`, `...Agent\|...` |
| 5 | cc_local | Glob / WebFetch / WebSearch / Bash `timedOutAfterMs` | gap | gap ≥ timer | 804 / 61 / 53 / 50 | 0 each | `cc_result_timers.cc_local.pairs` |
| 6 | aiv_cc | Glob / WebFetch / WebSearch | gap (row-insert clock) | gap ≥ timer | 43 / 14 / 4 | 0 / 0 / 1 | `cc_result_timers.aiv_cc.pairs` |
| 7 | swechat CC | bash_progress `elapsedTimeSeconds` | progress.ts − call.ts | lag ≥ 1000·elapsed (floor rule) | 112677 | 0 | `cc_bash_progress.floor_rule` |
| 8 | swechat CC | bash_progress `elapsedTimeSeconds` | own `timeoutMs` | 1000·elapsed ≤ timeout + 1 s | 88307 | 1 | `cc_bash_progress.elapsed_vs_timeoutMs` |
| 9 | swechat CC | mcp_progress `elapsedTimeMs` | completed.ts − started.ts | span ≥ elapsed | 1147 | 0 | `cc_mcp_progress.end_minus_start_ge_elapsed` |
| 10 | swechat CC | `turn_duration.durationMs` | turn_duration.ts − last human prompt.ts | span ≥ dur | 5858 | 56 | `cc_turn_duration.last_user_before` |
| 11 | swechat CC | Stop `hookInfos[].durationMs` | summary.ts − first Stop hook_progress.ts | span ≥ max(dur) | 6714 | 0 | `cc_raw.stop_hooks.span_ge_max_duration` |
| 12 | swechat CC | hook attachment `durationMs` (newer versions) | attachment.ts − call.ts | span ≥ dur | 455 Pre / 1231 Post | 0 / 0 | `cc_raw.hook_attachments.POSTHOC_*_vs_call` |
| 13 | swechat CC | api_error `retryInMs` | child.ts − api_error.ts | gap ≥ retryInMs | 530 | 5 | `cc_raw.api_error_retry.child_after_retry_wait` |
| 14 | cc_local | cost-state `totalAPIDuration` | `totalAPIDurationWithoutRetries` | ≥ | 70 | 0 | `cc_local_cost_state.api_ge_api_without_retries` |
| 15 | cc_local | cost-state startTime + totalDuration | the file's last event ts | ≥ | 70 | 3 | `cc_local_cost_state.end_vs_file_last_event` |
| 16 | Codex | `exec_command_end` duration | end.ts − call.ts | ≥ | 4890 | 0 | `codex.exec_command_end` |
| 17 | Codex | `mcp_tool_call_end` duration | end.ts − call.ts | ≥ | 425 | 0 | `codex.mcp_tool_call_end` |
| 18 | Codex | "Wall time: X seconds" header (model-visible) | output.ts − call.ts | ≥ | 5768 | 14 | `codex.wall_time_header.gap_ge_wall_time` |
| 19 | Codex | `yield_time_ms` (args) | output.ts − call.ts when output says "running" | ≥ | 1682 | 9 (0 with 30 s cap) | `codex.running_output_gap_ge_yield_time_ms`, `codex.POSTHOC_running_output_gap_ge_min_yield_30s` |
| 20 | Codex | apply_patch `metadata.duration_seconds` | gap | ≥ | 684 | 0 | `codex.apply_patch_metadata_duration` |
| 21 | Codex | `started_at` / `completed_at` (epoch s) / `duration_ms` | event ts | floor-consistent | 89 / 77 | 0 / 0 | `codex.task_*_ts_vs_*` |
| 22 | Codex | UUIDv7 turn_id / session id / new_thread_id | event ts | ts ≥ uuid ms | 360 / 77 / 56 | 0 / 0 / 0 | `codex.uuid7_*` |
| 23 | OpenCode | tool `state.time.start/end` | message `time.created/completed` | nested | 8197 / 8194 | 0 / 4 | `opencode.tool_start_ge_message_created`, `opencode.tool_end_le_message_completed` |
| 24 | OpenCode | id-embedded ms (`ses_`/`msg_`/`prt_`) | created / part time.start | ts ≥ id ms | 208 / 5471 / 4483 (reasoning) | 0 / 1 / 0 | `opencode.session_id_clock`, `opencode.message_id_clock`, `opencode.part_id_clock` |
| 25 | Gemini CLI | message.timestamp | toolCall.timestamp | ≥ | 1776 | 3 | `gemini_cli.call_result` |
| 26 | aiv_cu (Gemini) | Google `server-timing dur` | created_at − previous row created_at | gap ≥ dur | 12292 | 0 | `aiv_cu.gap_ge_server_dur` |
| 27 | aiv_cu (Gemini) | Google HTTP `Date` (1 s floor) | created_at | created ≥ date | 12292 | 0 | `aiv_cu.created_ge_http_date` |
| 28 | aiv_cu | `updated_at` | `created_at` | ≥ | 59956 | 0 | `aiv_cu.updated_ge_created` |

### A2. Pairs that hold with no or almost no violations (headline nulls of the violation search)

- **Tool timers inside the call→result window (Claude Code).**
  - swechat:
    - Glob: 1/2109 violations. Clustered rate 0.00047 [0, 0.0015]. Slack median 5 ms [4, 5] (`...Glob|durationMs`).
    - WebFetch 0/341, WebSearch 0/158, Task 0/1023 and Agent 0/1886.
      - Wilson upper bounds: 0.0111, 0.0237, 0.0037 and 0.0020.
  - cc_local: 0 violations in every pair.
    - Glob slack: min 3 ms, median 10 ms [9, 10], p99 24 ms. The Glob timer is never below 23 ms there (`timer_ms_describe.min`).
  - aiv_cc: 1/4 WebSearch, slack −8.39 ms; all else 0.
    - This agrees with the full-corpus aiv_accounting numbers copied into `aiv_cc_reused_from_aiv_accounting`: WebSearch 45/47, Glob 132/133, WebFetch 28/29.
- **bash_progress (swechat CC, direct Bash parents).**
  - Elapsed timer: 0/112677 violations under the floor rule. Wilson upper bound 3.4e-5. Slack min 3 ms, median 211 ms [165, 280] (`cc_bash_progress.floor_rule`).
  - Progress whose parent id is a Task/Agent call (8879 events, 278 parents; a subagent's Bash under the parent id): 0 violations (`cc_bash_progress.parent_is_task_or_agent`).
  - The result follows the last tick in 5676/5676 calls. Slack min 1 ms (`result_after_last_tick`).
- **Ticks are a 1 Hz chain phase-locked to the call.**
  - Δelapsed = 1 in 106390 consecutive tick pairs (`tick_delta_elapsed_counts`). Δt − 1000 ms has p5 −1 ms and p95 9 ms (`tick_dt_minus_1000_ms_describe_when_d_e_1`).
  - The per-call residual (lag − 1000·elapsed) has a range with median 6 ms and p95 334 ms over 5702 calls (`per_call_residual_range_ms_describe`).
  - The first tick is at elapsed 3 (3211 calls) or 2 (2449 calls) (`first_tick_elapsed_counts`).
- **Timeout records agree.**
  - The Bash call's `timeout` argument equals the progress `timeoutMs` in 2874/2874 calls (`args_timeout_eq_progress_timeoutMs`).
  - `timeoutMs` is constant within a call in 2963/2992 (`timeoutMs_constant_within_call`).
- **mcp_progress `elapsedTimeMs` equals completed.ts − started.ts.**
  - The difference is exactly 0 in 1014/1147. Slack max 2 ms, p99 1 ms (`cc_mcp_progress.end_minus_start_minus_elapsed_exact_0`, `end_minus_start_ge_elapsed`).
- **Stop hooks.**
  - summary.ts − first Stop hook_progress.ts ≥ max(hookInfos.durationMs): 0/6714 violations, Wilson upper bound 5.7e-4.
  - Slack median 1 ms [1, 1], p95 5 ms, p99 15 ms. Slack is 0 or 1 ms in 5285/6714 and |slack| ≤ 2 ms in 6183/6714.
  - Counts agree: hookCount == len(hookInfos) 10997/10997, and the number of Stop hook_progress events == hookCount 8719/8719 (`cc_raw.stop_hooks`).
  - The serial-execution probe (span ≥ **sum** of durations) fails 2482/2512 multi-hook summaries. Rate 0.988 [0.981, 0.993] (`multi_hook_span_ge_sum`).
- **Subagents (swechat).**
  - totalDurationMs vs result.ts − first nested event.ts: |residual| ≤ 2 ms in 1900/2188, ≤ 100 ms in 2184/2188, ≤ 1000 ms in 2188/2188 (`cc_subagent_containment.swechat.POSTHOC_total_vs_result_minus_first_nested`).
  - Nested events fall inside [call.ts, result.ts] for 2235/2235 starts and 2216/2216 ends.
- **Hook ordering vs tool calls (swechat raw).**
  - PreToolUse hook_progress.ts ≥ call.ts: 0/24418 violations, slack median 2 ms [2, 2].
  - PostToolUse: 0/65744 violations (`cc_raw.tool_hook_progress_vs_call_result`).
  - Newer-version hook attachments: PreToolUse attachment.ts − call.ts ≥ durationMs 0/455, slack median 2 ms [1, 3]; PostToolUse 0/1231 (`cc_raw.hook_attachments.POSTHOC_*_vs_call`).
- **Retry timer.**
  - `retryInMs` lies in the band 500·2^(attempt−1)·[1, 1.25], capped at 32000·[1, 1.25], for 533/533 api_error entries in 72 sessions (`cc_raw.api_error_retry.POSTHOC_retryInMs_in_band_...`; band read off `retryInMs_by_attempt`, i.e. descriptive).
  - Same-loop next attempt waits at least retryInMs in 391/392. The one exception is −9.67 ms (`POSTHOC_child_is_same_loop_next_attempt`).
- **Codex.**
  - exec end: 0/4890 at 2 ms. The 35 violations at 0 are all sub-ms (min −0.31 ms) (`codex.exec_command_end`).
  - mcp end: 0/425 at 2 ms (`codex.mcp_tool_call_end`).
  - Exec duration vs `timeout_ms`: 0/1610 (`exec_command_end.duration_le_timeout_ms`).
  - apply_patch: 0/684 (`apply_patch_metadata_duration`).
  - UUIDv7: turn id vs task_started.ts 0/360, slack median 4 ms [3, 19]. Session id vs session_meta.payload.timestamp 0/77, slack 2–133 ms. new_thread_id vs spawn end 0/56 (`codex.uuid7_*`).
  - started_at / completed_at: floor-consistent with their events, 89/89 and 77/77.
  - duration_ms agrees with (completed_at − started_at) within 1 s in 77/77 (`codex.turn_duration_ms_vs_epoch_seconds`).
  - The "Wall time" header is 49.7–139.2 ms below `exec_command_end` duration in 2357/2357 exec outputs with their own end (median −101.9 ms) (`codex.wall_time_header.exec_own_end_wall_minus_duration_ms`).
- **OpenCode.**
  - Tool end ≥ start 0/8194. Tool start ≥ message created 0/8197.
  - Reasoning parts nest inside their message: 0 violations in 5184/5178/5175 checks.
  - Session id clock: |created − id ms| ≤ 2 ms in 208/208, max 1 ms.
  - Message id clock: |created − id ms| ≤ 2 ms in 5190/5471, 1 violation (−5 ms).
  - Reasoning part id ms vs part time.start: p99 1 ms, 0/4483 violations.
  - Tool part id ms ≤ tool start: 0/7095 (`opencode.*`).
- **aiv_cu (Gemini).**
  - The row gap contains Google's server-timing duration: 0/12292 violations (Wilson upper bound 3.1e-4). Slack min 564 ms, p5 1227 ms [1114, 1348], median 6079 ms [5838, 6356] (`aiv_cu.gap_ge_server_dur`, `gap_minus_dur_quantiles_ci`).
  - created_at ≥ HTTP Date: 0/12292, min slack 78 ms (`created_ge_http_date`).
  - The HTTP Date ceiling bound holds too: 0/12292, min slack 454 ms (`http_date_ceiling_minus_prev_ge_dur`).
  - updated_at ≥ created_at: 0/59956. The difference is 1–8 µs for nearly all rows and > 1 s for 17/59956 (`aiv_cu.updated_minus_created_*`).

### A3. The violations, characterized

1. **Sleep / suspended timers (1 call).**
   - One Bash progress event reports elapsed 901 s against its own timeoutMs 300000, an overrun of 601000 ms (`cc_bash_progress.elapsed_vs_timeoutMs.violator_examples`).
   - The same call has a single tick gap of 899626 ms (`max_tick_gap_ms`). It is the only call over its timeout, and its tick gap covers the overrun (`calls_over_timeout`: 1 of 2992, `over_with_tick_gap_ge_overrun` 1).
   - Over all 378 tick gaps above 1.5 s (96 calls, 37 sessions), elapsed advances with the wall-clock gap in 377 (`tick_gaps_over_1500ms`).
   - The same session id also produces two of the five api_error retry violations (`cc_raw.api_error_retry.child_after_retry_wait.violator_examples`; errors are ConnectionRefused-type, no status).
2. **Transient backward clock reading (1 session).**
   - A Glob result has `durationMs` −2301 and result.ts − call.ts −2292 ms. The slack is therefore positive, so the inequality holds (`...Glob|durationMs.negative_timer_examples`).
   - The same session holds the only other negative call→result gap in swechat main threads, −52 ms (`cc_identical_timestamps.swechat.gap_negative_examples`).
   - Raw inspection: the entry after the bad result is back on the original timeline. This is not a persistent step.
3. **Identically stamped blocks (Claude Code 1.0.x mainly).**
   - The single Glob violation (timer 7 ms, gap 0) sits in a block of entries that all carry one timestamp.
   - Over swechat main threads:
     - 924 runs of tied timestamps; 16 runs of ≥ 5 events, 10 of ≥ 20, max 68 (`cc_identical_timestamps.swechat`).
     - call→result gap exactly 0 in 498/137380 pairs (177 sessions). Clustered rate 0.0036 [0.0022, 0.0055].
     - By session major.minor: 1.0 → 169/2327, 2.1 → 329/133590, 2.0 → 0/1463 (`gap_0_rate_by_major_minor`).
   - cc_local and aiv_cc have no gap-0 pairs (0/7512, 0/38738) and no tie run ≥ 5.
4. **Harness caps, not physics.**
   - Codex: 9/1682 "running" outputs arrive before the requested yield. All requested 120000 or 1200000 ms (`violator_yield_values`). With an effective yield of min(yield, 30000) ms: 0/1682, min slack 1 ms (`POSTHOC_running_output_gap_ge_min_yield_30s`).
   - cc_local: `timedOutAfterMs` ≠ the `timeout` argument in 9/15. Every mismatch is an argument above 600000 mapped to 600000 (`cc_bash_timeouts.cc_local.timedOutAfterMs.eq_arg_timeout.pairs_arg_to_timedOut`). All 50 timed-out results carry a backgroundTaskId.
   - Gap − timedOutAfterMs: min 102 ms, median 151 ms [137, 745].
5. **Logging lag of a start event (Codex).**
   - end.ts − task_started.ts ≥ duration_ms fails 16/77 at tol. Rate 0.208 [0.121, 0.441]; 10 gross (`codex.turn_duration_ms_vs_event_span`).
   - task_started.ts lies > 1 s after its own `started_at` second in 18/89, in 18 sessions (`task_started_ts_vs_started_at.within_1s`).
   - Post hoc: all 18 are the session's **first** turn: 18 of 22 first turns, 0 of 67 later turns.
     - Event lag on first turns: median 4220 ms, max 12034 ms. On later turns: median 519 ms, max 976 ms, i.e. inside the epoch-second floor (`POSTHOC_late_by_first_turn`).
   - Measured from `started_at` instead, 0/77 fail. The residual is 2–975 ms, which is the epoch-second floor (`POSTHOC_end_ts_minus_started_at_vs_duration_ms`).
   - Spearman(event lag, span residual) −0.265 [−0.664, −0.051], 12 sessions.
6. **Background / async launches (cc_local).**
   - The parent result precedes the last subagent event in 63/63 parents (56 Workflow, 7 Agent).
   - In 50 of these 63 the result precedes the first subagent event. Parent call→result gap median 22 ms, max 147 ms (`cc_subagent_containment.cc_local.result_before_last_nested`).
   - cc_local Agent/Workflow results carry no `totalDurationMs` (0 of 63).
7. **Children that are not the retry.**
   - The 5 api_error violators have children of 3 kinds: 3 are '[Request interrupted by user]' user entries, 1 is another concurrent loop's api_error, and 1 is the same loop's next attempt at −9.67 ms (`violators_child_kind`, `violator_examples`).
8. **Client- vs server-stamped ids (OpenCode).**
   - User text-part ids predate their message's `created` in 267/518 (33 sessions). Rate 0.515 [0.364, 0.612]; median −6.5 ms; min −13538 ms; 3 gross. File parts: 5/6.
   - Assistant-side parts never do (0/561 text, 0/4483 reasoning, 0/7095 tool) (`opencode.part_id_clock`).
9. **Fields whose meaning is not what the name suggests.**
   - OpenCode `session.time.updated` is below the last message's completion in 208/214, median −24830 ms (`opencode.session_updated_ge_last_message`). It is ≥ the last message's creation in 211/214.
   - Claude Code `turn_duration.durationMs`:
     - |span − dur| ≤ 1 s in only 0.226 [0.193, 0.257] of turns with the last prompt as start, and 0.179 [0.152, 0.206] with the first prompt of the turn.
     - The residual is mostly positive: 1316 in (2 ms, 1 s], 2995 in (1 s, 60 s], 1482 > 60 s, 56 negative (`cc_turn_duration.last_user_before.resid_bins`).
     - Post hoc: median residual is 1243 ms [922, 2826] for turns with no tool call (n 293) vs 5700 ms [4481, 7405] for turns with calls (n 5565).
     - Spearman with the summed call→result gaps of the turn: 0.483 [0.440, 0.537] (`POSTHOC_resid_by_calls_in_turn`).
   - cc_local cost-state:
     - startTime + totalDuration − the last event of the file is within 1 s of 900000 ms in 66/70 records. Rate 0.943 [0.863, 1.0], 68 files (`cc_local_cost_state.POSTHOC_end_minus_last_event_within_1s_of_900000ms`).
     - startTime precedes the file's first event by 712–1566 ms in 70/70.
     - 3/70 records end before the file's last event (gross).
10. **Millisecond-scale ordering slips (benign-looking, small n).**
    - Codex write_stdin "Wall time" exceeds the gap in 14/1540, ≤ 36.1 ms, in 2 sessions (`violator_sessions_tol`); exec_command outputs 0/4228 (`codex.wall_time_header.gap_ge_wall_time.by_tool`).
    - OpenCode `task` tool end exceeds message completion by 3 ms (4/116 task parts).
    - Gemini CLI cancelled tool calls stamped before their message (3/15 cancelled, ≤ 12 ms; 0/1688 success).
    - aiv_cc WebSearch −8.39 ms (row-insert clock).
11. **Unexplained (1 case).**
    - An OpenCode bash call ran 205775 ms against `timeout` 120000, exit 0 (`opencode.tool_duration_le_input_timeout.violator_examples`). OpenCode has no tick stream, so a suspend cannot be checked.

### A4. Quantization (timer resolution as written)

- Integer-ms timers with uniform last digits: Claude Code Glob/WebFetch/Task/Agent `durationMs`, turn `durationMs`, hook `durationMs`, mcp `elapsedTimeMs`, and Gemini server-timing `dur`. Chi-square p ≥ 0.14 for all except the following:
  - cc_local Glob `durationMs`: p 4.1e-5, n 804. It has a 23 ms floor and a narrow distribution.
  - swechat hook attachments: p 0.024, n 2219.
  - aiv_cc WebFetch: p 0.042, n 14.
- `timedOutAfterMs`: 50/50 divisible by 1000.
- `elapsedTimeSeconds`: integer, 121556/121556.
- WebSearch `durationSeconds`: float, mostly 14–16 decimals (`timer_quantization.decimals_as_written`).
- Codex `duration_s` and `Wall time`: mostly 9 and 4 decimals (`codex.exec_command_end.duration_s_decimals`, `codex.wall_time_header.decimals_as_written`).
- apply_patch `duration_seconds`: 0.1 s steps.
- `retryInMs`: float, 9–14 decimals.
- Codex started_at/completed_at: whole seconds. HTTP Date: whole seconds.
- Timestamp resolution (`ts_resolution`):
  - SWE-chat (all formats) and cc_local: 3 fractional digits in every row.
  - AI Village: µs with trailing zeros stripped (aiv_cc 118501/131676 rows with 6 digits, aiv_cu 142188/158111).

---------------------------------------------------------------------------------------------------------------------

## Part B. Interpretation (not data)

1. **Most harness timers in these logs are not independent clocks. They are a second encoding of the same wall-clock reading as the entry timestamps.**
   - The evidence is the identities, not the inequalities:
     - mcp `elapsedTimeMs` is literally completed.ts − started.ts (exact in 1014/1147).
     - The Stop-hook summary is stamped at first-hook-start + longest hook (0–1 ms in 5285/6714).
     - Agent/Task `totalDurationMs` is result.ts − first nested event.ts (≤ 2 ms in 1900/2188).
     - OpenCode ids carry the creation ms (session ids 208/208 within 1 ms).
     - The single negative Glob timer moved *together* with its timestamps under a transient backward clock reading, leaving the slack positive.
   - Consequence for witness-free verification: these pairs cannot reveal clock drift. They are cross-field checksums.
     - An honest harness reproduces them to within a few ms. An editor who changes one timestamp or one duration without recomputing the partner breaks them by the size of the edit.
     - The honest violation floor is measured and near zero. The 0.0–1 ms identities have essentially no slack for an edit to hide in.
2. **Truly independent clocks exist in two places, and both agree with physics everywhere.**
   - The first is the AI Village Gemini rows, where Google's server stamps (server-timing `dur`, HTTP `Date`) sit beside the AI Village DB's `created_at`.
     - In 12292/12292 rows the server time fits inside the DB row gap with at least 564 ms of client overhead, and no row is inserted before Google's Date.
     - This is a third-party clock that the logging party does not control.
   - The second is UUIDv7 / OpenCode-id time. It is generated by the same machine, but in a different code path from the event stamps.
3. **The violations are mechanical and fall into recognizable families.** None looks like fabrication. Each is a false-positive source a detector must model:
   - (a) machine suspend: wall-clock elapsed jumps, monotonic timeouts and tick intervals pause;
   - (b) transient bad clock reads;
   - (c) bulk re-stamped history in old Claude Code (1.0.x gap-0 pairs 169/2327 vs 2.1.x 329/133590). This destroys timing evidence rather than contradicting it;
   - (d) harness caps and clamps (30 s yield, 600000 ms timeout);
   - (e) start events logged late (Codex task_started, first turn of a session only: 18/22 first turns vs 0/67 later turns);
   - (f) async/background launches;
   - (g) concurrent loops and user interrupts sharing a parent chain;
   - (h) client-minted ids;
   - (i) fields whose names overstate their meaning (`session.time.updated`, `turn_duration`).
   - Every one was found by looking at the violators. The tolerance did not have to be widened for any of them.
4. **The pre-execution offset is measurable per Bash call.**
   - The first progress tick is exactly elapsed-seconds after the true execution start. So lag − 1000·elapsed on the first tick estimates the delay between the model's tool_use stamp and execution start.
   - That delay is p25 22 ms, median 73 ms and p95 28148 ms over 5702 calls (`first_tick_residual_ms_describe`). The pattern is bimodal-looking: automatic vs waited-for (likely permission prompts; not verified).
   - The same effect probably inflates the `turn_duration` residual (larger in turns with tool calls, Spearman 0.483 with in-turn gaps). That suggests the turn timer excludes some waiting time, but this is not established.
5. **Harness constants are fingerprints.** All are recovered from the data:
   - the 1 Hz tick starting at elapsed 2 or 3;
   - the retry backoff band (533/533);
   - the ~102 ms gap between Codex's Wall-time header and its exec_command_end duration (2357/2357 within 49.7–139.2 ms);
   - the 30 s yield cap and the 600000 ms Bash timeout clamp;
   - the cc_local 900 s exit-after-last-event constant (66/70).
   - A log not produced by the harness would have to reproduce all of them. Nothing here tests whether a forger would.
6. **Nulls, with the same weight.**
   - No progress stream exists in cc_local or aiv_cc, so the tick-chain and pre-execution checks do not transfer to the private current-version corpus or to the Agent SDK stream.
   - cc_local Agent results carry no `totalDurationMs`.
   - Hook attachments (newer versions) and hook_progress (older) never co-occur (0 joins). The Stop-hook identity needs hook_progress, and cc_local has neither start marker.
   - `turn_duration` is not a prompt→end timer (|res| ≤ 1 s in about a fifth of turns).
   - OpenCode `session.time.updated` is not a last-activity clock.
   - Gemini CLI has one pair only, and it is barely constraining.
   - Who&When and Cursor have no timestamps.

## Candidate mechanisms (each grounded in a measurement above; novelty UNVERIFIED for all)

1. **Cross-field timer identities as checksums.**
   - Recompute each redundant timer from the stamps it duplicates and require equality within a few ms: mcp elapsed, Stop-hook max duration, Agent totalDurationMs, OpenCode id ms, Codex wall time vs exec duration (~102 ms offset).
   - Honest floor: 0 violations at 2 ms in most pairs. False-positive sources: clock glitches move both fields together, so they are absorbed; bulk re-stamping (1.0.x) breaks the gap side.
2. **Third-party clock bracketing.**
   - A model API's own timing headers (server-timing, HTTP Date) must fit inside the logger's row gap: 0/12292 violations, min slack 454–564 ms.
   - A turn inserted or moved by the logger would need a consistent server timestamp it cannot mint. Applicable only where a provider returns such headers (Gemini here; none in other aiv_cu shapes).
3. **1 Hz progress-tick chain.**
   - Ticks are phase-locked to the call (per-call residual range median 6 ms) and advance with wall time across gaps (377/378).
   - Inserting, deleting or shifting a Bash result or its ticks breaks the chain. The first-tick phase also gives a per-call execution-start estimate.
   - False-positive sources: suspend (1 case), subagent ticks reported under the parent id (8879 events).
4. **Harness-constant fingerprints**: retry band, yield cap, timeout clamp, 900 s idle exit, tick start. These amount to cheap plausibility rules on any claimed log. Coverage is per harness version and not yet measured across versions.
5. **Timestamp-degeneracy screen** (a prerequisite rather than a detector): tie runs and gap-0 pairs mark logs whose timing evidence is gone (1.0.x 169/2327 pairs). Timing-based checks must abstain there instead of flagging.

## Could not measure

- Copilot (2 sessions, none in B). Cursor and Who&When have no timestamps.
- aiv_cc beyond the tool timers: no progress or hook data. The result-row `duration_ms` / `duration_api_ms` are covered by aiv_accounting and were copied, not recomputed (`aiv_cc_reused_from_aiv_accounting`).
- cc_local Stop-hook durations (stop_hook_summary records exist in the raw corpus; counts are in the A6 raw census, not here) have no start marker. cc_local hook attachments exist only as `hook_additional_context`.
- cc_local cost-state in family member files (only root files of B sessions were read: 68/186 had one). Whether the 900 s constant depends on version or launch mode, because the corpus is private and aggregates only were kept.
- The cause of the OpenCode 205775 ms bash overrun.
- Whether the 3 cc_local cost-state records ending before the file's last event are mid-file writes of a resumed session.
- Not attempted:
  - file-history-snapshot `backupTime` vs Edit timestamps;
  - `turn_duration.messageCount`;
  - Codex `rate_limits.resets_at`;
  - Gemini CLI `thoughts[].timestamp`;
  - queue-operation stamps vs prompts.
- Whether a forger would actually break any identity: no synthetic injection was run.
