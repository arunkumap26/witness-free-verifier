# A1: timestamp granularity and semantics (the latency gate)

Data: `analysis/out/phase_a/a1.json`, written by `analysis/probes/phase_a_a1.py`
(`PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_a_a1`, about 25 s). Inputs are the Phase A caches only
(`analysis/cache/<corpus>_A.parquet`, plus `swechat_population.parquet` for the per-session format). No `_B` file was
opened. Every number below is in that JSON; the path is given in brackets. The rules, tool classes and thresholds are
in `rules`. They were fixed before any outcome was computed and were not changed afterwards. Some descriptive checks
were added after the first run (multi-call messages, distinct-stamp digit test, and others); they are listed with
reasons in `rules.additions_after_first_run`. Rates are
`lib.stats.cluster_rate` with the session as the unit. Quantile CIs come from a session-clustered bootstrap that makes
the same draws as `lib.stats.cluster_quantile` (`ci_impl_check.equal = true`). Where a quantile has no CI, the group has
only one session. cc_local appears only as aggregates: tool names outside the Claude Code built-ins are collapsed to
`mcp__*` / `other_tool`.

Part 1 holds the measurements and Part 2 the interpretation.

## Verdicts (kill rule, applied as written in the brief)

Rule [`rules.kill_rule`]: a corpus/format is KILLED if more than 0.5 of its paired stamps are whole-second, or more than
0.5 of its call/result pairs have identical stamps (or there are no stamps or pairs). Otherwise it is ALIVE.
[`verdicts`]

| corpus / format | verdict | deciding number | pairs (sessions) |
|---|---|---|---|
| swechat / claude_code | **ALIVE** | 0.096% of stamps whole-second [0.062, 0.131]; 0.272% of pairs identical [0.128, 0.484]; ms stamps | 13,589 (126) |
| swechat / codex | **ALIVE** | 0.089% whole-second [0, 0.224]; 0/1,120 identical | 1,120 (15) |
| swechat / opencode | **ALIVE** | 0.054% whole-second [0, 0.101]; 0.375% identical [0.073, 0.723] | 3,735 (25) |
| swechat / gemini | **ALIVE** | 0.151% whole-second [0.092, 0.251]; 0/2,313 identical | 2,313 (10) |
| swechat / copilot | **ALIVE** (n = 2 sessions) | 0/530 whole-second; 0/265 identical | 265 (2) |
| swechat / cursor | **KILLED** | no timestamps (ts_kind none); 206 calls, no results in the source | 0 |
| swechat / simple_text | **KILLED** | no tool calls; 20/20 stamps whole-second | 0 |
| cc_local | **ALIVE** | 0.058% whole-second [0.023, 0.116]; 0/5,164 identical | 5,164 (107) |
| aiv_cc | **ALIVE** (semantics caveat: row-insert time, ~50 ms floor) | 0/66,950 whole-second; 0/33,475 identical; µs stamps | 33,475 (77) |
| aiv_cu | **KILLED** | 6,107/6,107 pairs share one stamp (100% [100, 100]); also KILLED in every one of the 10 strata | 6,107 (199) |
| whowhen | **KILLED** | no timestamps: 0 of 353 pairs have a stamp | 0 |

No ALIVE format gets the `mixed_flag`: each whole-second or identical share is at or below 0.01.

---

## Part 1: Measurements

### 1.1 Pairing [`pairing`]
- swechat: 21,749 calls, 21,025 results, 21,022 pairs. 726 calls have no result. By format
  [`groups.swechat/format=<f>.format.calls_without_result`]: cursor 206 (the source has no results), gemini 486 (all
  unstamped, in 1 session), claude_code 31 (20 sessions), codex 2, copilot 1. 1 duplicate call id was dropped.
- cc_local 5,164 pairs (1 call without a result). aiv_cc 33,475 (4). aiv_cu 6,107 (0). whowhen 353 (20 calls without a
  result). Every pair in the timestamped corpora has both stamps. whowhen has none (`pairs_missing_ts` 353).
- is_subagent never differs between a call and its result (`is_subagent_call_ne_result` 0 everywhere).

### 1.2 Stamp granularity [`groups.<g>.<sub>.all_event_stamps`, `.paired_stamps`]
- Every swechat format with stamps, and cc_local, writes exactly 3 fractional digits: claude_code 57,496/57,496 stamps,
  codex 4,865, opencode 8,427, gemini 7,328, copilot 2,250, cc_local 21,074. simple_text writes 0 digits (20 stamps).
- aiv_cc and aiv_cu stamps are microseconds with trailing zeros stripped. aiv_cc events: 6 digits 101,759, 5 digits
  10,187, 4 digits 1,080, 3 digits 111, 2 digits 7. aiv_cu events: 14,506 / 1,445 / 121 / 13 for 6/5/4/3 digits. That is
  roughly a factor of 10 per stripped digit.
- The last native digit is uniform, so the stamps really carry the precision they print. chi2 p on distinct stamps:
  swechat 0.20 (41,357 stamps), cc_local 0.45, aiv_cc 0.89 (66,950), aiv_cu 0.28 (6,107)
  [`last_digit_native_chi2_uniform_distinct_stamps`]. Counting aiv_cu's shared stamp twice (call and result) gives a
  spurious p = 0.009 [`last_digit_native_chi2_uniform`]. Use the distinct-stamp version.
- Delta resolution: the gcd of all nonzero |delta| is 1,000 µs in every ms-stamped format and 1 µs in aiv_cc
  [`gcd_abs_nonzero_delta_us`]. Whole-ms deltas in aiv_cc: 44/33,475 = 0.13% [0.09, 0.17], about chance (0.1%).

### 1.3 Call-to-result delta (seconds) [`groups.<g>.<sub>.delta_s`, `.delta_negative`]

| group | n | sess | min | p1 | p5 | p50 [CI] | p95 [CI] | max | neg |
|---|---|---|---|---|---|---|---|---|---|
| swechat / claude_code | 13,589 | 126 | 0 | 0.002 | 0.006 | 0.101 [0.069, 0.142] | 30.1 [20.4, 38.0] | 78,675.7 | 0 |
| swechat / codex | 1,120 | 15 | 0.001 | 0.008 | 0.024 | 0.197 [0.164, 0.357] | 7.40 [3.30, 9.93] | 299.98 | 0 |
| swechat / opencode | 3,735 | 25 | 0 | 0.001 | 0.002 | 0.022 [0.017, 0.024] | 12.7 [4.48, 100.8] | 600.13 | 0 |
| swechat / gemini | 2,313 | 10 | -0.022 | 0.058 | 0.072 | 0.335 [0.130, 0.391] | 30.8 [23.3, 48.0] | 4,814.8 | 6 |
| swechat / copilot | 265 | 2 | 0.141 | 0.144 | 0.156 | 0.582 [0.229, 1.03] | 18.7 [11.0, 26.4] | 524.5 | 0 |
| cc_local | 5,164 | 107 | 0.001 | 0.002 | 0.007 | 0.247 [0.102, 0.351] | 25.3 [6.80, 45.2] | 600.09 | 0 |
| aiv_cc | 33,475 | 77 | 0.046 | 0.065 | 0.105 | 0.448 [0.407, 0.529] | 8.22 [6.41, 20.7] | 361.5 | 0 |
| aiv_cu | 6,107 | 199 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

- Split by is_subagent: swechat claude_code main p50 0.133 s [0.091, 0.183] (n 9,679) vs subagent 0.048 s
  [0.033, 0.095] (n 3,910, 52 sessions). opencode main 0.023 vs subagent 0.006 s (n 333, 14 sessions). codex main 0.182
  vs subagent 0.692 s (n 179, 7 sessions). cc_local main 0.135 s (n 2,839) vs subagent 0.427 s [0.117, 4.53] (n 2,325
  from only 4 sessions). aiv_cc, aiv_cu and whowhen have no subagent events.
- Negative deltas: 6 in total, all in Gemini shell calls (min -0.022 s; 0.26% [0, 0.44] of Gemini pairs). There are none
  in any other format. The Gemini floor: p1 0.058 s overall; edit and write are never below 0.064 s; read p5 0.061 s
  [`groups.swechat/format=gemini.format.top_tools`].
- Most common exact deltas [`delta_exact_values.top`]: claude_code 7, 8, 9, 6, 10 ms (222, 215, 213, 211, 200 pairs);
  opencode 3, 4, 2 ms; codex 0.158 to 0.184 s; aiv_cc has 33,001 distinct values in 33,475 pairs (no value occurs more
  than 3 times). The heavy right tails are real waits: the swechat claude_code maximum is 78,675.7 s, a subagent.

### 1.4 aiv_cc: event time vs insert time [`aiv_cc_insert_time`]
- **parent_uuid check not measurable**: parent_uuid is null on 113,144/113,144 aiv_cc rows. Causal proxy: 0 result rows
  are stamped before their call row and 0 share its stamp.
- **No batch inserts.** 0 of 113,019 consecutive-row gaps are under 1 ms (0 runs) and 0 are zero. The smallest gap
  between any two rows of a run is 0.018192 s [`consecutive_rows`]. Minimum gap by transition: result->call 0.0182 s,
  meta->system 0.0205, call->result **0.0461**, call->call 0.0462, assistant->call 0.0487
  [`consecutive_rows.by_kind_transition.*.gap_s`]. Event-time references: Claude Code entries share a millisecond in
  8.1% [5.6, 14.0] of cc_local gaps and 13.9% [8.7, 19.5] of swechat claude_code gaps [`consecutive_rows_reference`].
- **Floor.** Every tool's call->result delta starts at about 50 ms in aiv_cc, including the in-process TodoWrite. In the
  event-time Claude Code corpora the p1 for the same tools is 1 to 31 ms [`per_tool_low_quantiles`]:

  | tool | aiv_cc min / p1 | swechat claude_code p1 | cc_local p1 |
  |---|---|---|---|
  | todo | 0.0505 / 0.0516 | 0.001 | (n/a) |
  | read | 0.0495 / 0.0582 | 0.002 | 0.004 |
  | glob | 0.0510 / 0.0552 | 0.001 | 0.031 |
  | edit | 0.0528 / 0.0566 | 0.001 | 0.008 |
  | write | 0.0506 / 0.0555 | 0.005 | 0.005 |
  | shell | 0.0509 / 0.0662 | 0.022 | 0.005 |
- **Offset, not distortion.** delta minus the tool-reported duration: Glob durationMs p50 0.049 s [0.038, 0.073], p5
  0.019, 89/90 non-negative. WebFetch p50 0.025 s (14/15). WebSearch durationSeconds p50 0.027 s (42/43; 1 session)
  [`aiv_cc_insert_time.reported_duration_vs_delta`]. For comparison, the event-time cc_local Glob offset is p50 0.010 s
  [0.009, 0.010] with 427/427 non-negative [`cc_local_reported_duration_vs_delta`].
- Run level: insert-stamp span vs the SDK result row's duration_ms (82 runs with duration > 0): span minus duration p50
  -0.0037 s, p5 -0.244, p95 0.128; ratio p50 0.99999. 18 result rows report duration_ms = 0
  [`sdk_result_duration_vs_run_span`].
- `init` rows: permissionMode = bypassPermissions in 125/125 runs [`init_permissionMode_counts`].

### 1.5 aiv_cu: shared turn stamp [`aiv_cu_shared_turn`]
- Call and result share the stamp in 6,107/6,107 pairs (199 sessions). Every one of the 6,455 turn rows has one
  distinct stamp.
- Inter-turn gap (a separate and weaker quantity: model generation + harness + action + screenshot + insert):
  n 6,255 over 199 sessions, p50 14.06 s [13.26, 14.92], p5 5.74, p95 66.3, min 0.0129; 0 zero gaps. By stratum p50:
  gemini-flash 10.45 s, compat-chat 11.68, haiku 12.24, gemini-pro 12.37, sonnet 14.86, fable 14.98, openai-responses
  15.43, openai-chat 15.77, claude-code 17.57, opus 18.23 [`inter_turn_gap_by_stratum_s`].
- Server timing exists only for Gemini: 1,161 gaps (gemini-pro 633, gemini-flash 528; 35 sessions). Server duration p50
  4.675 s. Gap minus server duration: p50 6.364 s [5.820, 6.933], p5 1.474, min 0.539, **0/1,161 negative**.
- created_at minus the HTTP Date header (1 s resolution): p50 4.489 s [3.916, 5.000], min 0.151, 0/1,161 negative.
- Result `updated_at` is within 1 ms of created_at in 6,104/6,107 rows (2 rows are 1 s or more later), so it adds no
  timing.

### 1.6 Claude Code formats: human waits and hooks [`claude_code_human_wait.<corpus>`]
Latency by tool class, all calls [`latency_by_class/all`]:

| corpus | class | n | p50 | p95 | share > 2 s | share > 10 s |
|---|---|---|---|---|---|---|
| swechat CC | auto_read | 5,971 | 0.041 | 0.938 | 1.54% [0.86, 2.37] | 0.28% [0.09, 0.56] |
| swechat CC | file_write | 2,235 | 0.042 | 28.8 | **13.2% [6.8, 21.7]** | 8.4% [4.2, 13.8] |
| swechat CC | shell | 4,150 | 0.481 | 42.8 | 34.0% [28.4, 40.9] | 14.0% [10.6, 18.0] |
| swechat CC | internal_noperm | 626 | 0.040 | 1.30 | 4.5% [1.0, 9.4] | 2.2% [0, 5.8] |
| swechat CC | human_interactive | 50 | 23.98 | 238 | 88.0% [76.5, 97.4] | 78.0% [62.8, 88.2] |
| cc_local | auto_read | 759 | 0.040 | 0.537 | 0.26% [0, 0.65] | 0/759 |
| cc_local | file_write | 358 | 0.013 | 0.078 | **0/358** (max 0.09 s) | 0 |
| cc_local | shell | 3,312 | 0.371 | 47.7 | 26.1% [13.3, 29.4] | 11.9% [5.4, 13.5] |
| aiv_cc | auto_read | 2,800 | 0.294 | 0.977 | 1.57% [0.17, 4.32] | 0.04% [0, 0.13] |
| aiv_cc | file_write | 598 | 0.112 | 24.5 | 31.9% [0, 53.6] | 20.6% [0, 41.0] |
| aiv_cc | shell | 7,451 | 0.782 | 31.4 | 20.1% [12.3, 30.8] | 8.3% [4.1, 13.2] |

- Markers on paired results:
  - swechat CC: cc_interrupt_reject on 59 results in 34/126 sessions (27.0% [20.0, 35.3]). Their latency is p50 23.4 s
    [16.9, 53.5] and p5 5.78. By class: shell 22, human_interactive 18, file_write 13. cc_permission_denied on 3
    results in 2 sessions (latency p50 0.022 s).
  - cc_local: cc_permission_denied on 173 results in 67/107 sessions (62.6% [53.2, 71.2]), latency p50 0.007 s, max
    0.037. cc_interrupt_reject on 9 results in 6 sessions.
  - aiv_cc: neither marker (0/77 sessions).
  - The probe's own `error_marker` agrees with the loader's `extra.marker` on every result that has one.
- Hooks (swechat CC, hook_progress linked by parent_call_id): 88 sessions have a tool hook. PreToolUse hooks are on 7.4%
  [3.3, 12.1] of auto_read calls, 15.9% [8.7, 24.7] of file_write and 6.4% [2.7, 11.8] of shell [`hooks_by_class`]. All 3,178 PreToolUse hook stamps fall
  inside the call->result window, p50 0.002 s after the call stamp (p95 0.021, max 487 s). PostToolUse stamps fall p50
  0.001 s after the result stamp; 75 of 7,773 fall before it. cc_local has no hook_progress events. 23
  hook_additional_context attachments link to 10 calls (all file_write), and there are 214 stop_hook_summary events.
  18/123 cc_local sessions carry an auto_mode attachment. permissionMode is not in the swechat or cc_local IR.
- bash_progress pre-exec offset (swechat CC; shell calls long enough to emit progress, 373 calls, 51 sessions;
  offset = (progress stamp - call stamp) - elapsedTimeSeconds): p50 0.074 s, p90 5.6, p95 35.7; > 2 s in 15.0%
  [7.2, 26.9]; > 10 s in 7.8% [4.1, 12.9]; none below -1 s [`bash_progress_pre_exec_offset_s`].

### 1.7 Multi-call messages [`claude_code_human_wait.<corpus>.multi_call_message_effect`]
Share of pairs whose call is not the last tool_use block of its API message: swechat CC 25.6% [22.6, 28.6], cc_local
21.9% [13.0, 39.0], aiv_cc 10.4% [6.9, 13.5].
- aiv_cc file_write: the last block has p50 0.089 s; a block that is not last has p50 **15.5 s** (165 calls, 4
  sessions). Measured from the last block's stamp, the not-last calls have p50 0.227 s, and only 5/165 of their results
  come before the last block's stamp.
- In the event-time CLI corpora, the result of a not-last call usually comes before the last block is even stamped:
  cc_local shell 369/423 (87.2%), file_write 54/54; swechat CC auto_read 1,800/2,231 (80.7%), shell 466/674 (69.1%).

### 1.8 Other format semantics [`format_semantics_checks`]
- Codex:
  - exec_command delta minus exec_command_end duration_s: p50 0.0775 s [0.0767, 0.1305], 184/184 non-negative.
  - Delta by tool_raw: shell_command p50 0.176 s, exec_command 0.711 s, apply_patch 0.063 s.
  - 12/1,120 results returned while the process was still running (`unified_exec_running`).
  - Fixed waits show up as delta floors: mcp__zls__diagnostics min 3.002 s; wait_agent 10.001 to 30.003 s.
- Copilot: tool.execution_start minus the call stamp is at most 0.003 s (p95 0.001; 265 pairs, 2 sessions). 159/266
  calls share their call stamp with another call (one message, several tools).
- Gemini: 16/2,313 calls share a call stamp.
- Claude Code (swechat): delta minus the tool-reported duration: Glob p50 0.007 s, p95 0.564, max 9.96 (n 168);
  WebFetch p50 1.68 s, p95 88.6 (n 37, 9 sessions); WebSearch p50 2.44 s (n 7). cc_local: WebFetch p50 0.004 s (n 20),
  WebSearch 0.003 s (n 15).
- OpenCode has no tool-reported duration to compare with. Per the loader, its call and result stamps are the tool
  part's time.start and time.end.

---

## Part 2: Interpretation

**The gate.** Latency analysis is ALIVE in 7 of 11 units. Six are clean: swechat claude_code, codex, opencode, gemini,
copilot, and cc_local. aiv_cc is ALIVE by the rule, with a semantic caveat. It is KILLED in four: aiv_cu (shared stamp,
100% of 6,107 pairs, in every stratum), whowhen and swechat cursor (no stamps), and swechat simple_text (no tool calls,
whole-second stamps). The four non-Claude-Code formats rest on few sessions: Gemini 10, Codex 15, OpenCode 25, Copilot 2.
Their verdicts concern stamp granularity. They give no evidence that per-format latency baselines would be stable.

**What the stamps mean, per corpus.**
- *Claude Code (swechat, cc_local).* These are real ms event stamps. Where the tool reports its own duration, the stamps
  bracket it with a few ms to tens of ms of overhead (cc_local Glob +10 ms, 427/427 non-negative). Delta is "block
  complete -> result written". Hooks and permission prompts both fall inside it: PreToolUse hooks are stamped in the
  window in 3,178/3,178 cases.
- *aiv_cc.* The stamps are DB insert times. They track event time, not batch time: no two rows ever land within 18 ms,
  and run spans match the SDK's own duration_ms to p50 -3.7 ms. But there is an additive floor of about 50 ms on every
  call->result delta, and it is the same for TodoWrite and Bash. That is the ingestion floor the brief asked about.
  Below about 0.1 s the delta measures the pipeline, not the tool. A separate trap: in this SDK version a call that is
  not the last tool_use block of its message waits for the rest of the message to be generated (file_write p50 15.5 s
  vs 0.089 s). Its delta is mostly generation time.
- *aiv_cu.* There is no per-call latency at all. The inter-turn gap minus Gemini server time (p50 6.4 s, never negative)
  is a coarse "harness + action + screenshot" quantity, available for 2 Gemini strata only. created_at minus the HTTP
  Date header would be a per-action proxy, but the Date header is whole-second, so by the same kill rule it is dead as a
  latency.
- *Codex.* delta = exec time + about 78 ms (exec_command). Polling/yield semantics (unified exec, wait_agent timeouts)
  put fixed-value spikes into the distribution. tool_raw must be kept apart.
- *Gemini.* The call stamp is the message stamp. The p1 is 58 ms (edit/write never below 64 ms) and there are 6
  negative deltas, so the message stamp is not exactly "call emitted".
- *OpenCode.* time.start/time.end is the cleanest execution measure here: read p50 0.004 s, todo p50 0.001 s. Whether
  permission prompts fall inside it cannot be told from these data.

**Human waits (iii).** The evidence is strong in swechat Claude Code and absent in aiv_cc and cc_local.
- A local Edit/Write executes in milliseconds, yet in swechat 13.2% [6.8, 21.7] of file_write calls take more than 2 s.
- 27% of sessions contain a user rejection ("doesn't want to proceed") that came p50 23 s after the call: a human
  answering a permission prompt.
- 15% of long shell commands started more than 2 s after the call (bash_progress offset).
- swechat WebFetch runs p50 1.7 s past its own reported duration, consistent with per-domain permission prompts.
- cc_local looks auto-approved for edits: 0/358 file_write calls over 2 s, max 0.09 s. Its 173 permission denials are
  automatic (p50 7 ms), not human.
- aiv_cc runs bypassPermissions in 125/125 runs. Its slow file_writes are the multi-call artefact above, not humans.
- Auto-approved reads are clean everywhere: more than 2 s in 1.5% (swechat), 0.26% (cc_local) and 1.6% (aiv_cc).

**Proposed rule for Probe 1: calls with no human wait (proposed, NOT applied).** A call qualifies only if all of these
hold:
1. Its corpus/format is ALIVE above, and both stamps exist.
2. Its tool class is `auto_read` (read/glob/grep/ls) or `internal_noperm` (todo/task*/toolsearch). Alternatively it is
   in a corpus whose permission mode is known to be bypass, which is aiv_cc only. Then every tool class except
   human_interactive and subagent qualifies.
3. It is the last (or only) tool_use block of its API message (same session_id, api_msg_id).
4. Its result carries neither cc_permission_denied nor cc_interrupt_reject.
5. It has no linked PreToolUse/PostToolUse hook_progress event (swechat claude_code) and no linked hook attachment
   (cc_local).
6. aiv_cc: subtract nothing, but treat deltas below 0.1 s as floor-bound. Compare tools only above that.
7. Shell/edit/write/web tools in swechat claude_code and cc_local are excluded until permissionMode is carried into the
   IR (see follow-ups). Where bash_progress exists, the pre-exec offset can be used to measure the wait, not to keep the
   call.

What the rule removes and what remains has not been measured. That is Phase B's first count.

**Nulls, reported with the same weight as the hits.**
- aiv_cc parent_uuid check: not measurable (0 non-null parent_uuid of 113,144).
- aiv_cc batch inserts: none (0 of 113,019 gaps under 1 ms).
- aiv_cu: there is no per-call latency at all.
- whowhen: no time information of any kind.
- Swechat claude_code shows almost no negative or identical stamps (0 negative; 0.27% identical). Identical stamps are
  not a hidden problem in any ALIVE format.

**Could not measure here.** permissionMode for swechat and cc_local (it is in the raw entries but not in the IR). Whether
OpenCode's time.start falls before or after a permission prompt. The aiv_cc parent-ordering check. Hook durations in
cc_local, which writes no hook_progress. Per-format baselines with more than 25 sessions outside Claude Code.

**Follow-ups (not done here).**
- A loader change to carry Claude Code `permissionMode` (and mode switches) into `extra` for swechat and cc_local.
  It would let rule 7 be replaced by a measured permission regime.
- A Phase B count of how many calls the proposed rule keeps, per corpus and tool class.
