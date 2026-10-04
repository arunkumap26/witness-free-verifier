# A6 raw-field census: fields we have not used yet

Data: `analysis/out/phase_a/a6_raw_census.json`, written by `analysis/probes/phase_a6_raw_census.py`. The per-part
inputs are in `analysis/out/phase_a/a6_parts/*.json`. Every number below appears in that JSON, at the path given in
brackets. Rates come with the CI the JSON stores: `cluster_rate` with the file (swechat, cc_local), run (AI Village
`claude_code_messages`), session (conversations table) or repo (checkpoints, commits) as the unit, and Wilson where
rows are the unit. `meta.rules` holds all rules, word sets and thresholds, plus the changes made after the test runs
(`meta.rules.changes_after_test_run`).

Part 1 has the measurements and Part 2 the interpretation. The first part makes no claims about what anything means.

---

## Part 1: Measurements

### 1.1 Format detection (swechat transcripts, all 5,850 files, by content)
[`parts.transcripts.format_counts`, `format_by_agent_label`]
- claude_code 4,925, opencode 623, codex 213, gemini 59, cursor 23, simple_text 4, copilot 2, doc_parse_failed 1.
- The content format disagrees with the dataset's `agent` label in these cells: 4 files labelled "Claude Code" are
  Cursor format; 3 labelled "Gemini CLI" are Claude Code format; 24 labelled "Agent" and 49 labelled "unknown" are
  Claude Code format; 3 labelled "unknown" are Gemini format.
- Line stats for the claude_code population: 2,991,527 lines, 15 salvaged (concatenated JSON values on one line), 10
  undecodable [`non_tool_entry_inventory.swechat_transcripts.claude_code.line_stats`].
- Key-path sample: 300 files [`parts.transcripts.sample.alloc`], allocated claude_code 159, opencode 46, codex 35,
  gemini 31, cursor 23, simple_text 4, copilot 2.

### 1.2 Non-tool entry inventory (full populations; files_with = k of N files, Wilson CI)
[`non_tool_entry_inventory.<corpus>.<format>.groups`]

**swechat Claude Code (N = 4,925 files)**

| group | records | files_with | Wilson |
|---|---|---|---|
| progress/hook_progress | 567,878 | 4,159 | 0.844 [0.834, 0.854] |
| progress/bash_progress | 384,398 | 2,101 | 0.427 [0.413, 0.440] |
| progress/agent_progress | 359,844 | 1,981 | 0.402 [0.389, 0.416] |
| queue-operation/enqueue | 177,110 | 2,606 | 0.529 [0.515, 0.543] |
| queue-operation/dequeue | 170,773 | 1,832 | 0.372 [0.359, 0.386] |
| queue-operation/remove | 5,571 | 1,226 | 0.249 [0.237, 0.261] |
| queue-operation/popAll | 293 | 191 | 0.039 [0.034, 0.045] |
| file-history-snapshot | 60,218 | 3,987 | 0.810 [0.798, 0.820] |
| system/stop_hook_summary | 33,044 | 4,153 | 0.843 [0.833, 0.853] |
| system/turn_duration | 18,669 | 3,384 | 0.687 [0.674, 0.700] |
| attachment/hook_success | 8,877 | 225 | 0.046 [0.040, 0.052] |
| progress/mcp_progress | 6,624 | 348 | 0.071 [0.064, 0.078] |
| last-prompt | 2,296 | 696 | 0.141 [0.132, 0.151] |
| pr-link | 1,960 | 846 | 0.172 [0.161, 0.183] |
| permission-mode | 1,407 | 347 | 0.070 [0.064, 0.078] |
| system/api_error | 1,400 | 182 | 0.037 [0.032, 0.043] |
| system/compact_boundary | 1,024 | 570 | 0.116 [0.107, 0.125] |
| summary | 844 | 91 | 0.018 [0.015, 0.023] |
| custom-title | 745 | 223 | 0.045 [0.040, 0.051] |
| agent-name | 421 | 197 | 0.040 [0.035, 0.046] |
| system/microcompact_boundary | 351 | 49 | 0.010 [0.008, 0.013] |

**swechat Codex (N = 213)**: turn_context 994 (213 files), event_msg/token_count 16,200 (189 files; 0.887
[0.838, 0.923]), task_started 979 (213), task_complete 821 (134; 0.629 [0.562, 0.691]), response_item/ghost_snapshot
317 (109; 0.512 [0.445, 0.578]), compacted 60 and event_msg/context_compacted 60 (17 files each; 0.080 [0.050, 0.124]),
turn_aborted 53 (22), thread_rolled_back 29 (9; 0.042 [0.022, 0.078]).

**swechat OpenCode (N = 623)**: part/step-start 14,908 and part/step-finish 14,888 (622 files; 0.998 [0.991, 1.0]),
part/patch 2,187 (117; 0.188 [0.159, 0.220]), part/subtask 199 (16), part/file 19 (11), part/compaction 14 (8).

**swechat Gemini (N = 59)**: message/info 119 (38; 0.644 [0.517, 0.754]), message/error 9 (8), message/warning 14 (3).

**cc_local main sessions (N = 332)**: attachment/total_tokens_reminder 13,078 (298; 0.898 [0.860, 0.926]), last-prompt
4,235 (332), atis-latch 3,710 (297), bridge-session 2,605 (59), queue-operation/enqueue 2,357 (332), system/stop_hook_summary
1,662 (293), ai-title 1,639 (46), mode 1,533 (39), frame-link 618 (13), file-history-snapshot 538 (268; 0.807
[0.761, 0.846]), file-history-delta 263 (17), artifact-autoreact-ledger 194 (10), cost-state 113 (111; 0.334
[0.286, 0.387]), artifact-comment-monitor 95 (11), system/compact_boundary 21 (15), system/api_error 17 (10).
**cc_local subagent files (N = 840)**: attachment/structured_output 477 (477; 0.568 [0.534, 0.601]), workflow-journal
lines `started` 762 (67), `result` 682 (62), `failed` 32 (5), `launched` 21 (21).
- No `progress/*` group and no `system/turn_duration` group appear in either cc_local stratum. In cc_local,
  subagent traffic is in separate files (840 subagent files beside 332 main files,
  `parts.cc_local.n_jsonl_files`), not nested in `agent_progress` as it is in swechat.

**SWE-chat conversations table** (2,692,480 rows) [`non_tool_entry_inventory.swechat_conversations_value_counts`]:
turn_type progress 1,322,498; queue_operation 354,144; file_snapshot 60,456; system_event 58,938; summary 836.
queue_op_subtype: user_prompt_delivered 169,517; user_prompt_enqueued 166,217; task_notification 5,258;
user_prompt_discarded 4,999.

### 1.3 Class-flagged fields
[`flagged_counts`, `flagged[]`]
2,647 class-flagged paths in total, 1,855 of them uncaptured (`captured` absent or `not_ir_source`). Uncaptured by
class: HASH_ID 783, COUNTER 358, STATUS 262, TOKEN 233, CLOCK 164, TIMER 62.

Below are the uncaptured fields (no `cc_jsonl` or `ir_column` mark) that I judge a consistency check could use. The
choice of which to list is interpretation; the numbers are from `flagged[]`. "ld" is the informational loader
string-literal mark.

**swechat Claude Code sample (159 files)**
| group | path | class | n_rec / n_records | fill [CI] | files |
|---|---|---|---|---|---|
| toolUseResult/Read | file.numLines, file.startLine, file.totalLines | COUNTER | 2,514 / 2,561 | 0.982 [0.972, 0.989] | 149/149 |
| toolUseResult/Edit | structuredPatch[].oldLines / newLines | COUNTER | 1,958 / 2,029 | 0.965 [0.952, 0.976] | 135/135 |
| toolUseResult/Grep | numLines | COUNTER | 823 / 939 | 0.876 [0.839, 0.908] | 89/95 |
| file-history-snapshot | snapshot.trackedFileBackups.<key>.version / backupTime | COUNTER / CLOCK | 1,362 / 1,673 | 0.814 [0.756, 0.856] | 121/127 |
| system/stop_hook_summary | hookInfos[].durationMs | TIMER | 792 / 951 | 0.833 [0.694, 0.911] | 104/131 |
| system/stop_hook_summary | hookCount; hookErrors; stopReason | COUNTER; STATUS | 951 / 951 | 1.0 | 131/131 |
| system/turn_duration | messageCount | COUNTER | 198 / 572 | 0.346 [0.122, 0.565] | 18/113 |
| assistant | message.usage.server_tool_use.web_search_requests / web_fetch_requests | TOKEN | 8,857 / 19,457 | 0.455 [0.332, 0.567] | 143/159 |
| assistant | message.usage.cache_creation.ephemeral_5m / 1h_input_tokens | TOKEN | 19,424 / 19,457 | 0.998 [0.994, 1.0] | 159/159 |
| assistant | message.stop_reason | STATUS | 19,457 / 19,457 | 1.0 | 159/159 |
| toolUseResult/Agent | toolStats.{readCount, searchCount, bashCount, editFileCount, linesAdded, linesRemoved, otherToolCount} | COUNTER | 5 / 313 | 0.016 [0.000, 0.046] | 2/56 |
| pr-link | prNumber | COUNTER | 68 / 68 | 1.0 | 22/22 |

**swechat Codex sample (35 files)**
| group | path | class | n_rec / n_records | fill [CI] | files |
|---|---|---|---|---|---|
| event_msg/exec_command_end | payload.duration.secs / nanos | TIMER | 1,868 / 1,868 | 1.0 | 9/9 |
| event_msg/mcp_tool_call_end | payload.duration.secs / nanos | TIMER | 96 / 96 | 1.0 | 4/4 |
| response_item/custom_tool_call_output | payload.output{json}.metadata.duration_seconds | TIMER | 185 / 228 | 0.811 [0.450, 0.947] | 9/12 |
| event_msg/task_complete | payload.duration_ms; payload.completed_at | TIMER; CLOCK | 84 / 126 | 0.667 [0.000, 0.873] | 2/19 |
| event_msg/task_started | payload.started_at | CLOCK | 107 / 158 | 0.677 [0.129, 0.868] | 12/35 |
| event_msg/token_count | info.{total,last}_token_usage.total_tokens; cached_input_tokens; reasoning_output_tokens | TOKEN | 1,950 / 1,966 | 0.992 [0.980, 0.996] | 31/31 |
| event_msg/patch_apply_end | payload.success; payload.status | STATUS | 185 / 185 | 1.0 | 9/9 |
| turn_context | payload.current_date | CLOCK | 159 / 159 | 1.0 | 35/35 |

**swechat OpenCode sample (46 files)**: the IR keeps one clock per event (`time.start` / `time.created`), and the
second clock goes uncaptured: `state.time.end` on tool parts (read 659/659; grep 120/120; glob 88/88; bash 247/249,
0.992 [0.977, 1.0]), `info.time.completed` on assistant messages 635/637 (0.997 [0.992, 1.0]), and reasoning
`time.end` 603/604 (0.998 [0.995, 1.0]). Tool metadata counters: bash `state.metadata.exit` 247/249 (0.992); grep
`state.metadata.matches` 120/120; glob `state.metadata.count` 87/88 (0.989 [0.960, 1.0]); edit
`state.metadata.filediff.additions/deletions` 18/18. Token fields: step-finish `tokens.*` and `cost` 633/633; session
`info.summary.additions/deletions/files` 46/46 and `info.time.updated` 46/46.

**swechat Gemini sample (31 files)**: message `tokens.{input,output,cached,thoughts,tool,total}` 2,509/2,511 (0.999
[0.997, 1.0]); `toolCalls[].status` 2,227/2,511 (0.887 [0.851, 0.910]); `toolCalls[].resultDisplay.diffStat.*` (model/user
added/removed lines and chars) 765/2,511 (0.305 [0.220, 0.360]); session `startTime` and `lastUpdated` 31/31.

**cc_local sample (300 files: 95 main, 205 subagent; key names and counts only)**
- main:cost-state: `totalCostUSD`, `totalAPIDuration`, `totalAPIDurationWithoutRetries`, `totalToolDuration`,
  `totalDuration`, `totalLinesAdded`, `totalLinesRemoved` and `startTime` are each present in 34/34 records across 33
  units.
- main:assistant: `message.usage.iterations[].*` 8,630/8,640 (0.999 [0.997, 1.0]);
  `message.usage.output_tokens_details.thinking_tokens` 7,780/8,640 (0.900 [0.711, 0.998]); `apiBlockIndex`
  6,284/8,640 (0.727 [0.497, 0.911]).
- main:toolUseResult/Read `file.numLines/startLine/totalLines` 194/210 (0.924 [0.847, 0.986]); Glob `totalMatches`
  375/375; Edit `structuredPatch[].oldLines/newLines` 225/226 (0.996 [0.986, 1.0]).
- sidecar `workflow.json` (65 files, full census): `durationMs`, `totalTokens`, `totalToolCalls`, `agentCount`,
  `startTime` 65/65; `meta.json` `spawnDepth` 758/773 (0.981 [0.968, 0.988]).

**AI Village (first 20,000 rows of each table)**
- Ordering check [`parts.aiv.tables.<t>.order_check`]: in claude_code_messages, computer_use_turns, events,
  agent_memories, chat_messages and computer_use_sessions, 19,999 of 19,999 adjacent id pairs are ascending.
  created_at ascends in 10,004 / 10,040 / 10,069 / 9,981 / 9,941 / 10,028 of 19,999 pairs, and the head spans
  2025-04-02 to 2026-09-19 (claude_code_messages: 2026-01-26 to 2026-03-30). The files are sorted by id and the
  head is not time-sorted, which fits the "random UUID order ⇒ time-uniform head" premise. Only the ordering was
  checked, not uniformity.
- computer_use_turns: `updated_at` 20,000/20,000 is a second row clock with no IR mark. Gemini
  `agent_messages.usageMetadata.*` 4,275/20,000 (0.214 [0.208, 0.219], Wilson over rows; the head has 17,418 distinct
  session_ids).
- claude_code_messages (unit = run; 180 runs in the head): `content.message.usage.cache_creation.ephemeral_*` and
  `content.message.stop_reason` 13,792/20,000 (0.690 [0.685, 0.695]). The result rows carry `modelUsage.<model>.*`
  (opus-4-5 costUSD 18/20). Full scan: 53 distinct sdk_session_id, the largest holding 244,709 of 244,820 rows; 314
  init rows [`parts.aiv.tables.claude_code_messages.sdk_session_full_scan`].
- events (not an IR source): `data.cost` and `data.inputTokens` / `data.outputTokens` 19,291/20,000 (0.965
  [0.962, 0.967]). The table also carries the raw model output with provider usage blocks.

**SWE-chat tables (full tables; not IR sources)**
- sessions: `api_call_count` 5,851/5,851; `tool_call_count` 5,476/5,851 (0.936 [0.929, 0.942]); `turn_count`
  5,798/5,851; `duration_seconds` 4,931/5,851 (0.843 [0.833, 0.852]).
- checkpoints: `cp_api_call_count` and the `cp_*_tokens` columns 13,406/13,406. In `checkpoint_metadata_raw`
  (500-row sample): `token_usage.{input,output,cache_*}_tokens, api_call_count` 484/500 (0.968 [0.931, 0.992], repo
  cluster).
- session_logs `session_metadata_raw` (500 rows): `token_usage.*` 488/500 (0.976 [0.959, 0.986]);
  `session_metrics.turn_count` 107/500 (0.214 [0.180, 0.252]); `transcript_lines_at_start` 52/500 (0.104
  [0.080, 0.134]); `prompt_attributions[].*` 9/500.
- commits `agent_changes` (500 rows): `[].structured_patch[].oldLines/newLines` 316/500 (0.632 [0.552, 0.707]).
  `file_attribution.__aggregate__.*` 500/500.
- conversations `timestamp` 2,577,946/2,692,480 (0.957 [0.951, 0.964], session cluster).

**Who&When**: no CLOCK-class field in either subset. Its only STATUS-flagged fields are labels (`is_correct`,
`mistake_reason`, `level`).

### 1.4 Pre-specified redundancy identities
[`parts.identities`; formulas in `meta.rules.identities`, exact equality, run once]

| check | match / n | rate, Wilson | cluster (files) | mismatching files |
|---|---|---|---|---|
| I4 CC Read numLines == numbered lines in model-visible text (swechat) | 2,510 / 2,514 | 0.998 [0.996, 0.999] | 0.998 [0.997, 1.0] (149) | 4 |
| I4 same, cc_local | 191 / 194 | 0.985 [0.956, 0.995] | 0.985 [0.962, 1.0] (59) | 3 |
| I5 CC Agent/Task totalToolUseCount == distinct nested tool_use ids (swechat) | 190 / 190 | 1.0 [0.980, 1.0] | 1.0 (71) | 0 |
| I1a Codex last_token_usage total == input + output | 1,935 / 1,950 | 0.992 [0.987, 0.995] | 0.992 [0.987, 1.0] (31) | 2 |
| I1b Codex cumulative chain total(n) = total(n-1) + last(n) | 1,862 / 1,919 | 0.970 [0.962, 0.977] | 0.970 [0.941, 0.994] (26) | 5 |
| I2 Gemini total == in + out + thoughts + tool (F1) | 2,509 / 2,509 | 1.0 [0.998, 1.0] | 1.0 (31) | 0 |
| I2 Gemini total == in + out (F3) | 1,366 / 2,509 | 0.544 [0.525, 0.564] | 0.544 [0.442, 0.647] (31) | 30 |
| I3 OpenCode step-finish total == in + out + reasoning + cache.read + cache.write (F1) | 148 / 633 | 0.234 [0.203, 0.268] | 0.234 [0.106, 0.381] (46) | 41 |
| I3 OpenCode F2 (in + out + reasoning) | 12 / 633 | 0.019 [0.011, 0.033] | 0.019 [0.005, 0.035] (46) | 46 |
| I4b CC Read numLines == splitlines(file.content) (swechat) | 1,172 / 2,514 | 0.466 [0.447, 0.486] | 0.466 [0.396, 0.530] (149) | 143 |

- I5 could not be checked in 94 Agent/Task results (20 files) because no nested traffic exists for the call.
- I4 mismatch diffs (text minus numLines): swechat n = 4, min −2,312, median −1,595, max −1. cc_local n = 3, all −1.
- I4b mismatch diffs: n = 1,342, all −1 (min = max = −1). cc_local: n = 102, all −1.
- I1a mismatch diffs run from 19,480 to 601,429 (n = 15). I1b diffs run from −601,429 to −19,480 (n = 57).
- I3 F1 mismatch diffs (total minus sum): n = 485, min −8,947, median −71, max −8. The message_info rows give the same
  counts as step-finish (148/633).

### 1.5 Classifier artifacts (known false flags)
- `repositories.repo_github_metadata.id` and `template_repository.id` are flagged CLOCK because GitHub ids fall in
  the epoch-seconds range. `tool_input_json/mcp__claude-in-*.tabId` is flagged CLOCK for the same reason.
- `artifact-comment-monitor artifacts.<key>.writtenAtMs` is flagged TIMER (the word "ms"), but its values are
  epoch-ms. TIMER takes precedence over CLOCK by rule.
- Who&When `system_prompt.VSCode_Expert` is flagged STATUS (the word "code"), and `mistake_reason` / `level` are
  flagged STATUS by name.
- `success_time` is flagged CLOCK and STATUS.
- The loader marks (`loader_leaf` / `loader_pair`) are string-literal matches only. Generic names match trivially.

---

## Part 2: Interpretation (not data)

1. **The harness writes a second, structured copy of most tool results, and the IR keeps only part of it.** For
   Claude Code, `toolUseResult` carries counters (Read numLines / startLine / totalLines, Grep numLines, Glob
   totalMatches, Edit structuredPatch line counts) that cc_jsonl does not extract. The one pre-specified check run on
   them (I4) holds 2,510/2,514 in swechat and 191/194 in cc_local. So a record pair (structured counter, model-visible
   text) exists and agrees in the honest baseline. If a tool result's text were rewritten, the counter is the cheapest
   place where it would stop agreeing. This is redundancy inside one harness record. It shows the record is
   internally consistent; it does not by itself show that a fabrication would break it.
2. **Second clocks.** OpenCode (`state.time.end`, `info.time.completed`), Codex (`exec_command_end.duration`,
   `task_complete.duration_ms`, `turn_aborted.duration_ms`), Claude Code (`stop_hook_summary.hookInfos[].durationMs`)
   and AI Village computer_use_turns (`updated_at`) each carry a second time field per event, and the IR drops it.
   These are timers or clocks written by the harness that a duration-vs-gap check could use. I did not measure their
   agreement.
3. **Session-level tallies are recountable.** Examples: cc_local `cost-state` (113 records in 111 of 332 main files),
   Codex `task_complete`, OpenCode session `summary`, cc_local `workflow.json` totals, swechat `sessions` /
   `checkpoints` / Entire.io `token_usage.api_call_count`. Each is a tally the transcript should reproduce. Caveat:
   Entire.io and the SWE-chat derived columns are probably computed from the same transcript, so agreement there
   would be tautological. Only disagreement is informative, and it would point to a post-hoc edit or a parsing
   difference, not necessarily a fabrication.
4. **file-history-snapshot is an unused harness-side mutation log.** It holds 60,218 records in 3,987 of 4,925 swechat
   CC files, and its trackedFileBackups version / backupTime fields fill 0.814 [0.756, 0.856] of snapshot records.
   An Edit or Write that reports success should be followed by a backup-version bump for that path. This was not
   measured here.
5. **The token identities split by scaffold.** Gemini's total is an exact sum (2,509/2,509). Codex last-usage is
   almost exact (1,935/1,950), and its cumulative chain breaks in 5 of 26 files with negative jumps whose magnitudes
   mirror the I1a mismatches. This looks like a counter reset (compaction or rollback), but that is unverified. For
   OpenCode, neither pre-specified formula holds (F1 148/633). By design, I did not search for the formula that
   would fit.
6. **Nulls.** cc_local has no `progress/*` nesting and no `system/turn_duration`. Checks that rely on swechat-era
   nesting (I5) or on turn_duration therefore do not transfer to current local logs as-is. Who&When has no clock
   field. Agent `toolStats` is too sparse to use (5/313). Copilot (2 files) and simple_text (4 files) are too small
   for rates.
7. **I4b and the AIV unit are artifacts, not findings.** I4b fails on 1,342/2,514 with a constant −1, which is a
   line-counting convention (trailing newline) in my check. The AI Village claude_code_messages `sdk_session_id` is
   not a usable resampling unit (one id holds 244,709/244,820 rows). The census uses the derived run (180 runs in the
   head), as the aiv_cc loader does.
