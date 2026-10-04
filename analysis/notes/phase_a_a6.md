# Phase A6: unused fields and parser surprises

Data: `analysis/out/phase_a/a6.json`, written by `analysis/probes/phase_a_a6.py` from the Phase A caches only
(`analysis/cache/<corpus>_A.parquet`; no `_B` cache was opened), the raw-field census
(`analysis/out/phase_a/a6_raw_census.json`, see `analysis/notes/raw_census.md`) and the build/review reports in
`analysis/out/build/`. Every number below is in a6.json; the JSON key is given in brackets. Part 1 holds the
measurements and Part 2 the interpretation. All rules, regexes and the one threshold were fixed in `meta.rules` before
the outputs were read. Eight rule corrections followed the first run: seven removed false or over-generous "captured"
matches and one unified the statuses. They are logged with before/after/reason in
`meta.rules.changes_after_first_run` and summarised at the end of section 1.6. The threshold was not changed.

**How fill rates are reported.** "Raw fill" is the census's own number: records of the entry group carrying the field,
taken from the census sample (swechat 300 files, cc_local 300 files, AI Village head 20,000 rows) or the full
population where noted. Its CI is the one the census stored: a cluster bootstrap over files or runs, or Wilson over
records. "A" counts are IR rows in the Phase A caches: swechat 90,069 rows / 200 sessions, cc_local 21,222 / 123,
aiv_cc 113,144 / 125, aiv_cu 16,085 / 200, whowhen 1,733 / 73 [`part1_ir_inventory.rows`, `.sessions`]. IR fills
carry session-clustered bootstrap CIs.

---

## Part 1: Measurements

### 1.1 Census against the IR as built now
[`part1_census_crossref.summary`, `.summary_with_pass1_extra`, `part1_candidates.totals`]

There are 2,061 census-flagged paths from sources that feed the IR. Adding the aiv_cu pass-1 full-population paths that
the census head did not see brings the total to 2,083. Each path got one status. The order of tests and their
definitions are in `meta.rules.status`.

| status (2,083 entries) | n |
|---|---|
| captured_census_mark (cc_jsonl path list / IR semantic key) | 583 |
| captured_column (loader maps it to an IR column; verified non-null in A) | 323 |
| captured_extra_renamed (loader renames it into `extra`; verified in A) | 88 |
| captured_extra_leaf (same key name in the slice's `extra` in A) | 63 |
| inside_args_or_text_json (present only inside the raw `args` / `text` JSON string) | 87 |
| label_store (Who&When ground truth, kept out of IR by design) | 14 |
| omitted_by_loader | 1 |
| **uncaptured** (slice in A, field absent, expected count in A >= 3) | **642** |
| inconclusive_rare (field absent, expected < 3) | 121 |
| not_emitted (whole entry type skipped by the loader) | 80 |
| slice_absent_in_A (type emitted but not in the A sample) | 75 |
| rule_target_unverified | 6 |

- **The census under-counted what the IR captures for non-Claude-Code formats.** 302 entries the census marked
  uncaptured are in the IR now [`summary.census_uncaptured_now_captured_total`; list in
  `part1_candidates.census_marked_uncaptured_but_captured_now`]. By corpus [`summary.census_uncaptured_now_captured`]:
  swechat 165 via columns, 47 via renamed extra keys and 59 via same-name extra keys; aiv_cu 9 + 17 + 1; aiv_cc 1 + 2;
  cc_local 1. Examples: Gemini `tokens.input/output/cached` go to the usage columns; OpenCode `state.time.end` is the
  result row's `ts`, not a dropped second clock; Codex `exec_command_end` `payload.duration.*` becomes `extra.duration_s`
  and its `status` becomes `extra.status` / `exec_status`; Codex `task_complete.duration_ms` / `completed_at` and
  `task_started.started_at` are copied as is; aiv_cu `updated_at`, `stop_reason` and the Gemini `finishReason` /
  `thoughtsTokenCount` / server-timing are in `extra`.
- **The reverse also happened:** 48 entries the census marked captured are not usable fields
  [`summary.census_captured_now_not_total`, `summary.census_captured_now_not`]. 39 of them (swechat 20, cc_local 11, aiv_cc 8) sit only inside the `args` JSON
  string. 6 are Gemini timestamps that are null in A (section 1.5). 3 are rule-excluded: the OpenCode reasoning
  `time.start`, which the loader folds into `thinking_chars`, and the two aiv_cu SDK message `uuid`s, which differ from
  the IR `uuid` (= row id).

Not-in-IR candidates: 924 entries [`totals.not_in_ir`]. 722 of them carry no noise tag [`not_in_ir_harness_measured`],
and of those 435 have raw fill >= 0.3 [`not_in_ir_harness_measured_raw_fill_ge_0.3`]. Tags on the rest
[`not_in_ir_by_tag`]: per-entry `sessionId` 134, MCP structured content 47, model-authored call input 20, census
classifier artifact 1. Counts by corpus x class x tag are in `part1_candidates.not_in_ir_summary`. The full list, with
raw fill, CI, unit, status and A-slice rows, is in `part1_candidates.not_in_ir`.

### 1.2 Timer / clock / counter / hash-id / status / token fields in raw data and NOT in the IR
Selected from `part1_candidates.not_in_ir`: harness-written fields, highest fill per class. Rate [CI] is the raw fill
with the census unit. "A" = IR rows of that entry type in the A sample.

**TIMER**
| corpus | entry / path | raw fill | status (A rows) |
|---|---|---|---|
| swechat CC | `system/stop_hook_summary` `hookInfos[].durationMs` | 792/951, 0.833 [0.694, 0.911], 131 files | uncaptured (863) |
| swechat CC | `attachment/hook_success` `attachment.durationMs` (+ `attachment.exitCode`) | 18/18, 4 files | uncaptured (4) |
| swechat CC / cc_local | `system/api_error` `retryInMs` | 2/2 (2 files) / 5/5 (3 files) | uncaptured (24 / 4) |
| cc_local | `cost-state` `totalAPIDuration`, `totalAPIDurationWithoutRetries`, `totalToolDuration`, `totalDuration` | 34/34 each, 33 files | not_emitted |
| cc_local | `toolUseResult/Monitor` `timeoutMs` | 23/23, 4 files | uncaptured (7) |
| swechat Codex | `event_msg/turn_aborted` `payload.duration_ms` | 11/12, 0.917 [0.9, 1.0], 3 files | slice_absent_in_A |
| swechat Copilot | `tool.execution_complete` `toolTelemetry.metrics.commandTimeout` | 95/265, 0.358 [0.188, 0.562], 2 files | uncaptured (265) |
| swechat Codex | `custom_tool_call_output` `output{json}.metadata.duration_seconds` | 185/228, 0.811 [0.450, 0.947], 12 files | inside `text` only |

**CLOCK**
| corpus | entry / path | raw fill | status (A rows) |
|---|---|---|---|
| swechat CC | `file-history-snapshot` `snapshot.timestamp` / `trackedFileBackups.<key>.backupTime` | 1673/1673 / 1362/1673, 0.814 [0.756, 0.856], 127 files | not_emitted |
| cc_local | same | 214/214 / 126/214, 0.589 [0.048, 0.785], 78 files | not_emitted |
| cc_local | `file-history-delta` `backup.backupTime` (+ `backup.version`, `snapshotMessageId`) | 92/92, 5 files | uncaptured (65: rows emitted, fields dropped) |
| swechat OpenCode | `part/reasoning` `time.start` / `time.end` | 604/604 / 603/604, 0.998 [0.995, 1.0], 45 files | uncaptured (2,016) |
| swechat OpenCode | `message_info/assistant` `info.time.completed` | 635/637, 0.997 [0.992, 1.0], 46 files | uncaptured (7,637) |
| swechat OpenCode | `part/text` `time.end` | 98/159, 0.616 [0.519, 0.690] | uncaptured (948) |
| swechat Codex | `turn_context` `payload.current_date`; `token_count` `rate_limits.*.resets_at` | 159/159 (35 files); 907/1966, 0.461 [0.18, 0.89] | uncaptured (47; 728) |
| swechat Gemini / OpenCode | session `startTime`, `lastUpdated` / `info.time.updated` | 31/31 / 46/46 | not_emitted |
| cc_local | `attachment/queued_command` `attachment.timestamp`; `attachment/date` `attachment.date` | 151/151 (11 files); 82/82 (76 files) | uncaptured (42; 100) |

**COUNTER**
| corpus | entry / path | raw fill | status (A rows) |
|---|---|---|---|
| swechat CC | `toolUseResult/Read` `file.numLines/startLine/totalLines` | 2514/2561, 0.982 [0.972, 0.989], 149 files | uncaptured (4,043) |
| cc_local | same | 194/210, 0.924 [0.847, 0.986], 61 files | uncaptured (175) |
| swechat CC | `toolUseResult/Edit` `structuredPatch[].oldLines/newLines` | 1958/2029, 0.965 [0.952, 0.976], 135 files | uncaptured (1,924) |
| cc_local | same | 225/226, 0.996 [0.986, 1.0], 11 files | uncaptured (156) |
| swechat CC | `toolUseResult/Grep` `numLines` | 823/939, 0.876 [0.839, 0.908], 95 files | uncaptured (1,515) |
| cc_local | `toolUseResult/Glob` `totalMatches` | 375/375, 46 files | uncaptured (427) |
| swechat CC / cc_local | `system/stop_hook_summary` `hookCount` | 951/951 (131 files) / 596/596 (84 files) | uncaptured (863 / 214) |
| swechat CC | `system/turn_duration` `messageCount` | 198/572, 0.346 [0.122, 0.565], 113 files | uncaptured (473) |
| swechat Gemini | `toolCall/replace` / `write_file` `resultDisplay.diffStat.*` (8 line/char counters) | 562/656, 0.857 [0.810, 0.898] / 208/210, 0.990 [0.967, 1.0] | uncaptured (1,423 / 754) |
| swechat OpenCode | `part/tool/edit` `metadata.filediff.additions/deletions`; session `info.summary.additions/deletions/files` | 18/18 (3 files); 46/46 | uncaptured (82); not_emitted |
| swechat CC | `file-history-snapshot` `trackedFileBackups.<key>.version`; `pr-link` `prNumber` | 1362/1673; 68/68 | not_emitted |
| cc_local | `assistant` `apiBlockIndex` | 6284/8640, 0.727 [0.497, 0.911], 95 files | uncaptured (5,753) |

**TOKEN**
| corpus | entry / path | raw fill | status (A rows) |
|---|---|---|---|
| swechat CC | `assistant` `usage.cache_creation.ephemeral_5m/1h_input_tokens` | 19424/19457, 0.998 [0.994, 1.0], 159 files | uncaptured (17,933) |
| cc_local / aiv_cc | same | 8640/8640 (95 files) / 13792/13792 (147 runs) | uncaptured (5,753 / 77,716) |
| swechat CC | `assistant` `usage.server_tool_use.web_search/web_fetch_requests` | 8857/19457, 0.455 [0.332, 0.567] | uncaptured |
| cc_local | `assistant` `usage.iterations[].*`; `usage.output_tokens_details.thinking_tokens` | 8630/8640, 0.999 [0.997, 1.0]; 7780/8640, 0.900 [0.711, 0.998] | uncaptured (5,753) |
| swechat Gemini | `message/gemini` `tokens.thoughts`, `tokens.tool`, `tokens.total` | 2509/2511, 0.999 [0.997, 1.0], 31 files | uncaptured (8,036) |
| swechat OpenCode | `step-finish` `tokens.total`; message `info.tokens.total` | 633/633; 633/637, 0.994 [0.986, 1.0] | uncaptured (3,414; 7,637) |
| swechat Codex | `token_count` `last_token_usage.total_tokens` | 1950/1966, 0.992 [0.980, 0.996], 31 files | uncaptured (728) |
| cc_local | `cost-state` `totalCostUSD`; `modelUsage.claude-opus-5.*` | 34/34; 16/34, 0.471 [0.303, 0.636] | not_emitted |
| aiv_cc | `result/success` `usage.*`, `modelUsage.<model>.costUSD/inputTokens/...` | 20/20; opus 18/20, 0.9 [0.75, 1.0] | uncaptured (82) |

**STATUS**
| corpus | entry / path | raw fill | status (A rows) |
|---|---|---|---|
| swechat CC / cc_local / aiv_cc | `assistant` `message.stop_reason`, `stop_sequence` | 19457/19457 / 8640/8640 / 13792/13792 | uncaptured (17,933 / 5,753 / 77,716) |
| aiv_cu (pass 1, population) | Anthropic `stop_sequence`; Agent-SDK `textMessage/thinkingMessage.message.stop_reason` | 907506/907506; 11679/11679 | uncaptured (6,660; 1,637) |
| swechat CC / cc_local | `system/stop_hook_summary` `hookErrors`, `stopReason` | 951/951 / 596/596 | uncaptured |
| swechat CC | `toolUseResult/Agent` `status`; `TaskOutput` `retrieval_status`, `task.exitCode` | 296/313, 0.946 [0.911, 0.982]; 37/45, 0.822 [0.419, 1.0]; 35/45, 0.778 [0.419, 1.0] | uncaptured (233; 66) |
| cc_local | `toolUseResult/Workflow` `status` | 39/39, 8 files | uncaptured (10) |
| swechat Codex | `patch_apply_end` `payload.status`; `turn_aborted` `payload.reason` | 185/185 (9 files); 12/12 | uncaptured (96); slice_absent |
| swechat OpenCode | `message_info/assistant` `info.finish` | 633/637, 0.994 [0.986, 1.0] | uncaptured (7,637) |
| aiv_cu | Responses `agent_messages[].status` | 4776/20000, 0.239 [0.233, 0.245] (head, Wilson) | uncaptured (1,833) |

**HASH_ID**
| corpus | entry / path | raw fill | status (A rows) |
|---|---|---|---|
| swechat CC / cc_local | tool_result `sourceToolAssistantUUID` | 11370/11431, 0.995 [0.983, 1.0] / 4005/4005 | uncaptured (9,682 / 2,839) |
| swechat CC / cc_local | `promptId` on user text | 659/1813, 0.363 [0.201, 0.511] / 736/736 | uncaptured (1,507 / 312) |
| swechat CC | `progress/bash_progress` `toolUseID`; `stop_hook_summary` `toolUseID`; `compact_boundary` `logicalParentUuid` | 5925/5925; 951/951; 18/18 | uncaptured |
| swechat Codex | `exec_command_end` `payload.turn_id`; `turn_context` `turn_id`, `trace_id`; `session_meta` `git.commit_hash` | 1868/1868; 159/159; 98/159; 31/35, 0.886 [0.771, 0.971] | uncaptured |
| swechat Gemini | `toolCalls[].result[].functionResponse.id` | 2227/2511, 0.887 [0.851, 0.910] | uncaptured (8,036) |
| swechat OpenCode | `part/patch` `hash`; `step-finish` `snapshot` | 40/40; 633/633 | uncaptured |
| aiv_cc | row `id`; `content.session_id` | 20000/20000 each (head) | uncaptured |

Per-entry `sessionId` (CC, 134 entries) is tagged `entry_session_id`. It differs from the IR `session_id`, which is
the file, family or run.

### 1.3 What the IR does carry (A caches)
[`part1_ir_inventory.extra_by_kind`, `.extra_by_format_kind`, `.columns_by_kind`, `.columns_by_format_kind`;
fill = rows with the key / rows of the cell, session-clustered CI]

- Claude Code timers in swechat A: on meta rows, progress `elapsedTimeSeconds` is 6,033/23,834, 0.253 [0.141, 0.366],
  and `turn_duration` `durationMs` is 473/23,834, 0.020 [0.015, 0.026]. On result rows, `durationMs` is 205/13,592,
  0.015 [0.011, 0.020], and `totalDurationMs` (Task) is 199/13,592, 0.015 [0.011, 0.018]. All over 126-127 sessions.
  In cc_local A, result `durationMs` is 0.087 [0.042, 0.210] of 5,164 rows. cc_local has no progress or turn_duration
  meta rows.
- Codex (19 sessions): result `duration_s` is 764/1,120, 0.682 [0.474, 0.781]; meta `duration_s` is 766/2,314; meta
  `duration_ms` / `completed_at` are 16/2,314.
- OpenCode (25 sessions): result `compacted_at` is 1,935/3,735, 0.518 [0.334, 0.639]; result `exit` is 1,140/3,735,
  0.305 [0.213, 0.390].
- aiv_cu: call `timing.server_timing_dur_ms` is 1,161/6,107, 0.190 [0.132, 0.255], Gemini only; result `updated_at`
  is 6,107/6,107. aiv_cc meta `duration_ms` / `duration_api_ms` / `total_cost_usd` / `num_turns` are 100/31,619 (the
  SDK result rows).
- `native_error` fill on results [`columns_by_format_kind`, `columns_by_kind`]: swechat CC 0.328 [0.285, 0.370]
  (13,592 rows, 126 sessions); cc_local 0.650 [0.394, 0.790] (5,164 rows, 107 sessions); aiv_cc 0.178
  [0.108, 0.247] (33,475 rows, 77 sessions); aiv_cu 0 of 6,107 (no flag in the source); Codex 0.768 [0.524, 0.888];
  OpenCode, Gemini and Copilot 1.0. `exit_code`: Codex 0.606 [0.377, 0.726], OpenCode 0.304
  [0.213, 0.387], every Claude Code corpus 0.
- `extra.marker` (`ir.error_marker`) is written only by the Claude Code parser and Who&When. On swechat results it is
  present on 0.646 [0.529, 0.759] [`extra_by_kind.swechat.result.paths.marker`].

### 1.4 Parser surprises (80 items, deduplicated)
[`part2_parser_surprises`, `part2_summary`]

The items draw on 14 of the 15 build/review files [`part2_summary.n_build_report_files_read`,
`n_build_report_files_present`] plus the census. The 15th file, `aiv_cu_pass1_stats.json`, feeds Part 1 instead.

80 items: swechat 33, cc_local 11, cc_local+aiv_cc 3, aiv_cc 8, aiv_cu 16, whowhen 9. By status: open 47,
handled_by_loader 28, resolved_in_loader 5. Every cited key path resolved (`items_with_missing_paths` = []). All 25
cross-report same-fact checks agree (`same_fact_unequal` = []). No report file has a `parser_surprises` or
`open_problems` field. The items were compiled from counters, notes and review checks, and each value is read from
its file at run time. Selected open items, numbers as stored:

| id | what (counts) |
|---|---|
| `sw_gemini_text_exit_vs_flag` | Gemini shell results whose text says `Exit Code: N`, N != 0: 445 of 1,419 shell results (A+B), of which native_error true 0; shell results with native_error true: 26 |
| `sw_codex_sessions_without_exec_end` | 61 of 96 Codex A+B sessions write no `exec_command_end` at all; 1,346 exited outputs have exit_code null (85 with nonzero header exit); shell results with exit_code: 5,501 of 8,956 |
| `sw_conversations_table_drops_calls` | conversations.parquet lacks 38,178 raw call ids (CC 27,156; Codex table has 0 of 10,923 calls); 41 of 2,200 sampled sessions absent from the table |
| `sw_ts_backward_steps` | ts earlier than the previous event's, in file order: CC 124,103; OpenCode 6,662; Gemini 134; Codex 0 |
| `sw_gemini_result_before_call` | 14 Gemini results stamped before their call, 15 at the same stamp (4,759 with both) |
| `sw_gemini_calls_without_result` | 487 toolCalls without a `result` key, all in 1 session (d8bda4a8, evidence `per_session`). The same session has no `ts` on any event [`part1_ir_inventory.ts_null_by_format.swechat.gemini.all_null_session_ids`] |
| `sw_codex_human_prompt_unmatched` | 86 of 1,085 Codex `user_message` texts match no response_item (4 sessions) |
| `sw_call_ids_in_several_sessions` | 862 call ids in more than one session (15 sessions), 231 shared across A and B |
| `sw_cc_call_result_pairing` | CC duplicate call ids 16, results without call 16, calls without result 861 |
| `cl_subagent_after_parent_result` | cc_local subagent events stamped after the parent call's result: 113,950 of 114,045 (Workflow 111,625 / 111,664; Agent 2,325 / 2,381); before the parent call: 0 |
| `cl_wire_tool_inputs_differ` | cc_local `tool_use.input` differs from `wireToolInputs` in 4,473 cases (equal 14,250); 4,072 are a stripped `cd ... &&` bash prefix, 378 edits |
| `cc_usage_out_streaming_partials` | api_msg_ids whose events carry different `usage_out`: cc_local 4,886 of 11,220; aiv_cc 4,773 of 32,474; input/cache never differ (0) |
| `cl_native_error_and_exit_fill` | cc_local results 41,706, native_error filled 30,581, exit_code filled 0 |
| `cl_review_numbers_predate_cache` | review-2 counted 17,762 A rows; the current A cache has 21,222 (the thinking-only meta rows were added after the review) |
| `av_content_session_id_differs` | 53 aiv_cc rows whose `content.session_id` differs from `sdk_session_id` (54 distinct content ids) |
| `av_sdk_errors` | 21 assistant rows with an SDK `error`: authentication_failed 17, unknown 4 |
| `av_runs_without_result_row` | runs with 0 SDK result rows 53, with 1 259, with 2 1, with 4 1 |
| `au_no_latency_outside_gemini` | server-timing in 0 Anthropic rows; OpenAI chat 0 of 422,384 and Responses 0 of 586,287 rows carry usage; 1,046,801 turns have no row-level model |
| `au_server_timing_by_month` | Gemini server-timing: 0 of 1,199 rows in 2025-04, 0 of 12,801 in 2025-11, 9,031 of 23,370 in 2025-12, 20,161 of 20,161 in 2026-01 |
| `au_updated_after_created` | updated_at - created_at > 1 s on 733 of 2,510,487 rows (135 redacted); max 427,020.7729 s |
| `au_nonsynthetic_centre_moves` | 613 model-generated mouse_move to (512,384), the bootstrap target; 0 first in session |
| `au_no_failure_flag` | A recount: native_error and exit_code non-null 0; population shell rows with non-empty `error` (stderr) 138,031 of 981,509 |
| `ww_question_absent_from_history` | 10 of 126 Algorithm-Generated tasks: the question is nowhere in the history (loader assumes history[0] repeats it; 116 do) |
| `ww_label_agent_vs_speaker` | mistake_agent != speaker at mistake_step: AG 3, HC 3 (+2 case-insensitive) |
| `ww_hc_no_exit_flag` | Hand-Crafted results without a harness exit code: 644 of 652 |
| `ww_mistake_step_landing` | labelled step lands on a call AG 70 / HC 6, narration AG 54 / HC 13, result AG 2 / HC 39 |

Resolved in the current build (`resolved_in_loader`):
- OpenCode completed-with-nonzero-exit native flag: 79 sessions before the fix, 0 after.
- Codex 'running' outputs given exit codes: 807 before, 0 after.
- cc_local attachments that were meta: 3,814 A rows moved to system.
- Thinking-only API messages: 25 cc_local and 21 aiv_cc were missing at review 2; now 25,653 / 65,550 meta rows.
- The rejected 'owner' fork policy: 13,962 subagent events had their parent call in another session.

Handled by the loader (encoded as synthetic ids, deferred attachment, flags): 28 items. Examples are Codex `*_end`
events without a call (exec 1,791) and exit codes never shown to the model (95, of which 45 nonzero); OpenCode
redacted ids (2,196 message ids, 6,366 call ids); aiv_cu synthetic bootstrap turns (66,294 in 66,172 sessions);
resume-chain families in cc_local (332 file sets merged to 309 sessions; 22,463 + 724 copy events dropped).

### 1.5 Timestamps missing where the format has them [`part1_ir_inventory.ts_null_by_format`]
- swechat Gemini: 1 of 15 A sessions has no `ts` on any event. That is 1,028 of 8,356 events. The 6
  `rule_target_unverified` entries are Gemini tools seen only in that session.
- swechat CC: 1 of 128 sessions has no `ts` (6 events).
- OpenCode: all 25 sessions have some untimed events (7,733 of 16,160: step / patch / subtask parts).
- Cursor (7 sessions) and Who&When (73) have none by design.
- cc_local: 148 of 21,222 events are untimed (the workflow journal), in 2 sessions.

### 1.6 Non-tool entry types the loaders skip [`part3_non_tool_inventory`]
Record counts are raw, from the census (full populations).

| corpus / format | skipped types (records, files with / files) |
|---|---|
| swechat Claude Code (12 types, 421,664 records [`skipped_totals`]) | queue-operation/enqueue 177,110 (2,606/4,925), /dequeue 170,773 (1,832), /remove 5,571, /popAll 293; file-history-snapshot 60,218 (3,987); last-prompt 2,296; pr-link 1,960 (846); permission-mode 1,407; summary 844; custom-title 745; agent-name 421; ai-title 26 |
| cc_local (11 untimestamped types, 18,559 records, copies included) | last-prompt 4,235; atis-latch 3,710; custom-title 3,236; bridge-session 2,605; ai-title 1,639; mode 1,533; agent-name 661; file-history-snapshot 538 (268/332); artifact-autoreact-ledger 194; cost-state 113 (111/332); artifact-comment-monitor 95. Build counters match: `build_counters.cc_local_dropped_untimestamped` |
| swechat OpenCode / Gemini | the document-level `session` object (623 / 59 files): no IR row |
| cc_local inputs not read | tool-results spill files 406, workflow run summaries 65, subagent .meta.json 773 (read only for the parent link) [`build_counters.cc_local_non_jsonl_files_not_loaded`] |
| Who&When | `question` (repeated in history[0] for 116/126 AG and 58/58 HC; absent from the history for 10 AG) and `system_prompt` (356 entries) [`build_counters.whowhen_omitted_fields`] |
| Whole tables not ingested | AI Village events, chat_messages, agent_memories, computer_use_sessions (>= 20,000 rows each), claude_code_sessions 303, summaries 939, agents 46, ...; swechat sessions / session_logs 5,851, checkpoints 13,406, commits 14,459, conversations 2,692,480 [`tables_not_ingested`] |

Codex, Copilot, aiv_cc, aiv_cu: no entry type is skipped (every type becomes at least a meta row). Their losses are
at field level (1.2).

Flags [`part3_non_tool_inventory.flags`, `flag_counts`]: 31 types are emitted by rule but absent from A, with expected A rows >= 3
under the uniform-session assumption. Examples: swechat CC `attachment/async_hook_response` (4,695 records in 75
files), `system/informational`, `system/microcompact_boundary`; cc_local subagent attachments
(`auto_mode` 546 records, `structured_output` 477, ...). These records are concentrated in few files. cc_local subagent
files are in 10 of 309 sessions, and A holds 4 of those 10
[`build_counters.cc_local_sessions_with_subagent_files_population`, `..._rows_A`]. So the flags show that the
assumption fails for clustered types. They are not evidence of a loader drop.

Rule changes after the first run [`meta.rules.changes_after_first_run`]. On the first run the 2,061 census entries
split as uncaptured 525, inconclusive 101, slice-absent 54, not_emitted 60, rule_none 162, captured_column 330 and
captured_extra_leaf 66. The changes:
- `none` rules now fall through to the A-sample tests instead of having their own status.
- Nested Claude Code `toolUseResult.<obj>.<key>` paths no longer name-match top-level keys (e.g. `read.bytes` matched
  `bytes`).
- The AI Village row-level `content.message.*` / `content.tool_use_result.*` paths are checked against the CC entry
  slices. Before, the SDK result rows' `stop_reason` matched them.
- `toolUseResult/unresolved` uses the generic tool_result slice.
- Corpus-level verification of a rule target is allowed only for joined values or absent slices.
- OpenCode `messageID` maps to `api_msg_id` only for parts that carry it.
- aiv_cu is checked per API shape. Before, SDK `stop_reason` matched Anthropic `meta.stop_reason`.
- aiv_cu pass-1 container paths are skipped, and `modelVersion` maps to `model`.

Every change except the first removed a false or over-generous "captured" match.

---

## Part 2: Interpretation (not data)

1. **The IR keeps the harness's flags and one clock per event but drops most of the redundant structure.** The fields
   that let one record be checked against another sit almost entirely outside the IR:
   - structured counters beside model-visible text (Read line counts, Edit patch line counts, Grep / Glob counts,
     Gemini diffStat, OpenCode filediff);
   - second clocks (OpenCode reasoning and message completion times, file-history backup times, hook durations);
   - per-turn and per-session tallies (stop_hook hookCount, turn_duration messageCount, cc_local cost-state,
     OpenCode session summary);
   - linkage ids (`sourceToolAssistantUUID`, `promptId`, Codex `turn_id`).

   For a consistency-based fabrication check these are the most useful fields. All have raw fill >= 0.8 in at least
   one corpus (1.2). None needs new data, only loader changes. Changing a loader is outside A6.
2. **The census over-stated the gap for non-CC formats** (302 entries are in fact captured). Four of the second-clock
   leads in its Part 2 are already in the IR:
   - OpenCode `state.time.end` is the result `ts`;
   - the Codex `exec_command_end` duration is `extra.duration_s`;
   - Codex `task_complete.duration_ms` is copied into `extra`;
   - aiv_cu `updated_at` is in result `extra`.

   Codex `turn_aborted.duration_ms` cannot be checked, because the type is not in the A sample. The second clocks that
   are really missing are OpenCode `info.time.completed` and reasoning `time.start/end`, Claude Code
   `hookInfos[].durationMs` and hook-attachment `durationMs`, and the file-history backup times.
3. **Flags that disagree with the text are a recurring parser fact, not noise.** Examples: Gemini shell results
   saying `Exit Code: N` with native_error never true; OpenCode `completed` with a nonzero exit (now handled); Codex
   sessions with no `exec_command_end` at all, so the exit lives only in the output header; Claude Code results
   without an `is_error` key (native_error filled on 0.328 in swechat A). Any Phase B probe that uses `native_error`
   or `exit_code` as ground truth must stratify by format and treat null as "unknown", not "success".
4. **Timing caveats for Phase B latency work.**
   - Claude Code (swechat 124,103) and OpenCode (6,662) write events out of time order.
   - cc_local writes 2,206 adjacent inversions in main files; the loader re-sorts them.
   - cc_local subagent events almost always come after their parent's result (113,950 / 114,045), because Workflow
     and Agent runs are backgrounded. A parent-child latency check would see that ordering as a violation.
   - aiv_cu has a latency field only for Gemini, and only from 2025-12 on.
   - aiv_cc and aiv_cu `created_at` have trailing zeros stripped (variable fractional digits).
5. **The derived tables are not a substitute for raw transcripts.** conversations.parquet misses 38,178 call ids in
   the 2,200 sampled sessions, including every Codex call.
6. **Nulls.**
   - Who&When has no timer, clock, token or hash field. Its status fields are labels.
   - aiv_cu has no failure flag. Its `error` field is stderr.
   - Cursor has no results and no timestamps.
   - Copilot (2 files) and simple_text (4) are too small for rates.
   - cc_local has no progress or turn_duration entries.
   - The slice-absent and inconclusive entries (75 + 121) cannot be judged from the A sample.
