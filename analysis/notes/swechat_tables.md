# Phase C lens: SWE-chat session/checkpoint tallies as a second, harness-side bookkeeping

Data: `analysis/out/phase_c/swechat_tables.json`, written by `analysis/probes/phase_c_swechat_tables.py`
(`python -m analysis.probes.phase_c_swechat_tables`; the transcript scan runs on a 4-process pool; a from-scratch rerun reproduced the JSON exactly).
Inputs: `data/swe-chat-pinned/{sessions,checkpoints,session_logs,commits(numeric + files_changed),conversations(narrow)}.parquet`
and all 5,850 raw transcripts. JSON paths are given in brackets. Rates are k/n with a Wilson 95% CI (session or checkpoint
is the unit) unless marked `cluster_rate` (session-clustered bootstrap, or repo-clustered where stated).
Pre-registration (formulas, tolerances, thresholds, calibration sessions, revision log) is in `meta.prereg`. Everything
under `followup` was added after I had read the first report pass. It is post hoc and labelled as such in the JSON.

Part 1 has the measurements and Part 2 the interpretation.

---

## Part 1: Measurements

### 1.1 Which columns are independent bookkeeping (established by recount, not assumed)

Three layers sit in `sessions.parquet`:
- **Harness (Entire CLI `metadata.json`)**: the token tallies (`input/output/cache_creation/cache_read_tokens`,
  `api_call_count`), `files_touched`, `checkpoints_count`, `created_at`, attribution, and the transcript offsets
  (`checkpoint_transcript_start`, `transcript_lines_at_start`, `transcript_identifier_at_start`). These are the second
  bookkeeping.
- **Dataset builder (derived from the transcript)**: `tool_call_count`, `unique_tools_count`, `research_count`,
  `action_count`, `first_write_position`, `turn_count`, `prompt_count`, `duration_seconds`. They agree with
  `conversations.parquet` almost by identity [`part2_consistency.c_builder_and_auxiliary_vs_conversations`]:
  tool_call_count 5475/5476, unique_tools 5475/5476, research 5476/5476, action 5476/5476, turn_count 5772/5785,
  first_write_position (0-based position among tool_use rows) 4549/4561. `duration_seconds` equals the span of
  user+assistant record timestamps in the raw transcript in 4919/4920 = 0.9998 [0.9988, 1.0000]. It equals the span
  of all records in only 623/4930 [`followup.duration_alternatives`].
- **LLM annotation**: `user_persona`, `session_success`.

### 1.2 Harness token tally vs a recount from the stored raw transcript (the core check)
[`part2_consistency.b_harness_tally_vs_transcript_recount`]

Formula F0 (calibrated on one session, `meta.prereg.calibration_sessions`): distinct `message.id` over top-level
`type=="assistant"` records, last-occurrence usage, summed. A session is matched if all 5 fields
(api, input, cache_creation, cache_read, output) are exactly equal over the whole transcript (full), over its first
`api_call_count` messages (prefix), or over some contiguous run of `api_call_count` messages (window). Tolerance: 0.

Claude-Code-format transcripts with a harness tally, api_call_count > 0: n = 4836.

| class | k/n | rate [95% CI] |
|---|---|---|
| full | 2771/4836 | 0.573 [0.559, 0.587] |
| prefix | 1665/4836 | 0.344 [0.331, 0.358] |
| window | 358/4836 | 0.074 [0.067, 0.082] |
| none | 42/4836 | 0.0087 [0.0064, 0.0117] |

Matched by any class: 4794/4836 = 0.9913 [0.9883, 0.9936]. Repo-clustered (183 repos): 0.9913 [0.9874, 0.9942].
The variants fall short of F0. F3 (first-occurrence usage) matches only 492 full and leaves 4145 none, and its
4-field version (output excluded) leaves 66 none. F4 (drop `<synthetic>` messages) leaves 649 none. F1 (drop sidechain
records) leaves 44 none, with sidechain messages present in only 3 sessions. F2 (add the subagent messages embedded in
progress records) matches no session that F0 misses (`followup.F2_full_and_F0_not_full` = 0), although 1954 sessions
carry such messages.

How the three matched classes are explained:
- **prefix**: in 1664 of 1665 sessions `created_at` comes before the last transcript timestamp. The median is −28.8 s
  (`created_minus_tx_end_by_cls.prefix`). The stored transcript runs a median of 3 messages past the snapshot
  (`msgs_after_snapshot_prefix`, max 524).
- **window**: `checkpoint_transcript_start` is declared for 357 of the 358 window sessions. The tally equals the run
  starting at that declared offset in 353 of them (`claude_format.window_sessions`; crosstab in
  `F0_declared_start.ctx_start.matched_class_crosstab`). `transcript_identifier_at_start` was found in all 876
  transcripts that declare it. It locates the window start less well: 57/118 = 0.483 [0.395, 0.572].
- **full**: the median `created_at − last transcript timestamp` is +753.7 s, and 39 of 2771 are negative.

Other scaffolds (formula calibrated on one session each):
Codex X0 (cumulative `total_token_usage` at the k-th `token_count` event, with output = output + reasoning):
full 147, prefix 37, none 5 of 189. That is 184/189 = 0.974 [0.940, 0.989]; X1 (output without reasoning) matches 2/189.
OpenCode O0: full 604, prefix 8, window 1, none 9 of 622. O1 (output + reasoning) leaves 572 none.
Gemini CLI G0: full 26, prefix 19, window 2, none 8 of 55. G1 (output + thoughts) leaves 52 none.

### 1.3 Most of the unmatched cases are a dataset join artifact
[`part2_consistency.a_session_vs_raw_metadata_copy`, `followup.table_vs_raw_metadata_mismatch`,
`followup.classes_using_session_logs_metadata`, `followup.residual_unmatched`]

- In 39 of 5719 sessions the token columns of `sessions.parquet` differ from the `token_usage` in
  `session_logs.session_metadata_raw` (api_call_count agrees 5680/5719 = 0.9932 [0.9907, 0.9950]).
  All 39 belong to more than one checkpoint, and in all 39 the sessions-table output_tokens is larger than the raw value.
- Rescanning these 39 with the raw-metadata tally matches every one: prefix 22, full 14, window 3. The sessions-table
  values match none in 31 of them.
- After substituting the `session_logs` tally, the matched rates are: Claude Code format 4822/4836 = 0.9971
  [0.9951, 0.9983]; Codex 186/189 = 0.984 [0.954, 0.995]; OpenCode 613/621 = 0.987 [0.975, 0.994]; Gemini 47/55 = 0.855
  [0.738, 0.924]. All formats together: 5668/5701 = 0.9942 [0.9919, 0.9959]; unmatched 33/5701 = 0.0058 [0.0041, 0.0081].
- Residual 33 (claude 14, codex 3, opencode 8, gemini 8), spread over 18 repos (6 in hirakiuc/gh-orbit, all Gemini;
  5 in entireio/cli). 7 of the 14 Claude cases match a prefix on the 4 non-output fields (`claude_noout_class`), so only
  the output count differs. In 26 of the 33 the transcript has more messages than the tally, in 3 fewer, and in 4 the
  same number. No residual tally equals the whole-transcript recount of any other session
  (`followup.unmatched_with_other_session_full_tally` = 0). The per-session list is in `followup.unmatched_tally_sessions`.

### 1.4 Harness-side identities that hold or fail
[`part2_consistency.e_checkpoint_level`, `part2_consistency.f_attribution_and_timestamps`]
- Checkpoint tally = sum of its sessions' tallies, for checkpoints whose sessions are all canonical there (n = 2510):
  all 5 fields equal in 2504/2510 = 0.9976 [0.9948, 0.9989]. Single-session: 2114/2116. Multi-session: 390/394 for
  the sum, against 4/394 for the max. For checkpoints with a session that is canonical elsewhere (n = 9571), only
  1000/9571 = 0.104 [0.099, 0.111] are equal. In 8563 of them cp_output < sum (median ratio 0.580).
- Links: checkpoint→session 24794/24794 and session→checkpoint 24775/24775 are symmetric. 1711 of 26505 `session_pks`
  do not resolve to a session row (`session_pks_resolution.n_unresolved`), and 61 `checkpoint_ids` are missing from the checkpoints table.
  `session_count` equals len(metadata.sessions) in 13335/13406.
- `commits` rows per checkpoint equal `commit_count` in 8201/13406 = 0.612 [0.604, 0.620]. Checkpoint additions
  equal the sum over commit rows in 13406/13406.
- **Checkpoint duplication across repos** [`followup.checkpoint_id_in_multiple_repos`]: 1825 of 11581 checkpoint_ids
  appear under two repo_ids, which covers 3650/13406 = 0.272 [0.265, 0.280] of checkpoint rows. There are 7 repo pairs, the largest being
  marcus-sa/brain + osabiohq/osabio (994 ids) and cyyeh/… + wanshicheng/duckdb-data-agent (472). Of the 1622 groups of
  checkpoints that share an identical non-zero 5-field tally, 1490 are a single checkpoint_id seen under two repos, and
  122 are distinct checkpoint_ids carrying identical session_pks. The largest group is 101 checkpoints, all with the
  same 2 sessions, 90 of them with commit_count 0 (`checkpoint_duplicate_largest_group`).
- Attribution: total_committed = agent_lines + human_added in 4345/5569 = 0.780 [0.769, 0.791], and with human_modified
  added in 4747/5569 = 0.852 [0.843, 0.862]. The agent_percentage identity holds in 5224/5392 = 0.969 [0.964, 0.973].
  No negative values. `created_at − attribution_calculated_at` is never negative (min 0.0008 s, median 0.217 s,
  20 > 60 s, max 21784.2 s).

### 1.5 Builder and auxiliary tallies that do not agree
- **conversations.parquet drops 0.187 of tool calls** [`followup.tool_call_count_vs_raw`]. tool_call_count equals all
  distinct raw `tool_use` ids in only 479/4847 = 0.099 [0.091, 0.108]. It equals the tool_use ids in the **last record
  of each message.id** in 4834/4847 = 0.9973 [0.9954, 0.9984] (first record: 8/4847). Dropped ids, pooled:
  76258/407920 = 0.187 [0.180, 0.193] (cluster_rate, 4847 sessions).
- **conversations per-turn tokens cannot rebuild session totals** [`...conv_per_turn_tokens_vs_session_tokens`]:
  the pooled conversation/session ratio is input 0.013 [0.007, 0.027], output 0.085 [0.079, 0.091], cache_creation
  0.115 [0.104, 0.128], and cache_read 0.104 [0.093, 0.115]. Assistant rows that carry tokens make up
  37966/359216 = 0.106 [0.100, 0.111] of API calls.
- `prompt_count` = non-continuation `user_prompt` rows in 3988/5785 = 0.689 [0.677, 0.701]. By scaffold that is
  Claude Code 0.637 and Codex 0.986.
  `session_metrics.turn_count` (raw harness, n = 1292) equals prompt_count in 525/1292 = 0.406 [0.380, 0.433].
  The prompt count in `context_md` (n = 4302) equals prompt_count in 2787/4302 = 0.648 [0.633, 0.662]. Its most
  common offset is −7 (380 sessions, 302 of them in dayhaysoos/nimbus, 21 repos).
- Files: Claude-format sessions with both non-empty (n = 4276) [`part2_consistency.d_files_touched_vs_write_tool_paths.api_pos`]:
  set equality between files_touched and Write/Edit/MultiEdit/NotebookEdit paths holds in 1628/4276 = 0.381 [0.366, 0.395].
  Pooled, edited paths that are in files_touched: 0.528 [0.507, 0.548]. Out-of-cwd paths are 0.049 [0.045, 0.053] of
  edited paths [`followup.files_touched_vs_in_cwd_write_paths`].
  Followup hypothesis, written down before computing [`followup.files_touched_vs_edits_and_commits`], n = 3201 sessions
  with commit files: files_touched ⊆ files changed in the canonical checkpoint's commits in 2812/3201 = 0.878 [0.867, 0.889].
  An edited path is in files_touched iff it was committed: cluster_rate 0.896 [0.881, 0.909] over 2821 sessions
  (2x2 counts: 7546 in-ft & committed, 7905 neither, 1031 in-ft & not committed, 767 committed & not in-ft).
  Only 0.312 [0.204, 0.500] of files_touched entries were tool-edited.

### 1.6 Distribution shape (per scaffold) [`part1_distributions`]
- Sarle bimodality coefficient on log1p, lower CI > 0.555. Every flagged column is zero-inflated or sits on a boundary
  mass: human_added/modified/removed (zeros 2248/3211/4307 of 4623 in Claude Code), agent_percentage (1793 at 100,
  1059 at 0), cache_creation for OpenCode (616/623 zero) and Gemini (56/59 zero), and token columns of "other"
  (82–84/104 zero). session_success also flags, with its mass on 82 (1106), 88 (859) and 72 (851).
  Token and tool columns for Claude Code are not flagged (b 0.32–0.50).
- Spikes (pre-declared rule): none in any Claude Code token, tool or duration column. All spikes are in attribution
  columns (e.g. OpenCode total_committed 2864 ×122, agent_lines 2858 ×89; Codex total_committed 1890 ×47) or in Codex
  turn_count = prompt_count = 12 (×51). Each attribution spike value comes from 1 canonical checkpoint, with distinct
  `attribution_calculated_at` per session [`followup.spike_membership`]. The Codex 12-turn group covers 18 checkpoints,
  4 repos, 2 users and 51 distinct output_tokens values [`followup.codex_turn_count_12`].
- Checkpoint tally spikes, e.g. cp_output_tokens 32283 ×101, are the 101-checkpoint group in 1.4.
- Round numbers (values ≥ 100, against a 1/k baseline). Claude Code div100 lower bounds sit slightly above 0.01
  (e.g. input_tokens 27/1839 = 0.0147 [0.0101, 0.0213]). Codex cache_read div10 is 39/181 = 0.216 [0.162, 0.281], and
  OpenCode cache_read div10 is 110/619 = 0.178 [0.150, 0.210]. Cache granularity, checked post hoc
  [`followup.cache_read_tokens_granularity`]: Codex cache_read is divisible by 128 in 181/181 = 1.000 [0.979, 1.000],
  OpenCode in 569/619 = 0.919 [0.895, 0.938], Claude Code in 49/4785 = 0.0102 [0.0078, 0.0135], and Gemini in 0/57.
- created_at second-of-minute: χ² p = 0.357 (df 59, n 5848). duration ms last digit: χ² p = 0.684 (n 4931).
- Exact duplicates: one pair of distinct sessions with an identical non-zero 5-field tally (both 1-message sessions in
  entireio/cli, both F0 full). The `content_hash` is the empty string in 69 sessions, and no other hash repeats.
- Harness tally absent [`followup.api_zero`]: 145 sessions have api_call_count = 0. Only 13 of them have a `token_usage`
  key, 88 have transcript messages, and the cli_version is mostly "dev" (58) or "" (48).

### 1.7 Correlations (Claude Code, complete cases n = 4150 of 4847) [`part3_correlations.claude_code`]
- Spearman: 86 of 325 pairs have |ρ| ≥ 0.5, 62 of them across declared groups. The strongest cross-group pairs are
  api_call_count–tool_call_count 0.938 [0.930, 0.945] and cache_read–tool_call_count 0.937 [0.930, 0.944]. After those
  comes n_records with everything (0.72–0.88).
- Partial Spearman given rank(n_records): 16 of 300 pairs have |ρ| ≥ 0.5, only 6 of them cross-group, and all 6 are
  tokens×tools (api–tool_call_count 0.777 [0.753, 0.799]). The next cross-group pairs are files_touched_count–agent_lines
  0.450 [0.422, 0.478], turn_count–duration 0.436 [0.411, 0.462], action_count–n_sub_msgs −0.372 [−0.400, −0.343],
  and n_checkpoint_ids–agent_lines −0.253 [−0.283, −0.226]. session_success and agent_percentage appear in no top-30
  cross-group pair, in either variant.

### 1.8 Multi-axis outliers (robust z, |z| > 3.5 on ≥ 3 of 22 features, `n_features_used`) [`part4_outliers`, `followup.outliers_claude_code_api_pos`]
- Claude Code primary (n = 4847): 101 outliers = 0.0208 [0.0172, 0.0253]. All 34 sessions with api_call_count = 0 are
  outliers (34 of 101), and the top combination is cache_creation−, cache_read−, output− (37). Several groups are
  over-represented. entireio/cli has 32/101 outliers against 771/4847 of the population. Other over-represented groups:
  cli_version "" (18 vs 154), created 2026-01 (16 vs 80), and user_persona "Other" (23 vs 358).
- Sensitivity without api = 0 (n = 4813): 69 outliers = 0.0143 [0.0113, 0.0181] across 35 repos. Outlier rate among
  tally-unmatched sessions: 10/42 = 0.238 [0.135, 0.385]. Among matched sessions: 59/4771 = 0.0124 [0.0096, 0.0159].
  8 of those 10 unmatched outliers are join-artifact sessions (1.3), and the outlier rate among all join-artifact
  sessions is 9/36 = 0.250 [0.138, 0.411]. Median session_success is 72 for outliers and 82 for the population. Median
  n_records is 792 against 257.
- All scaffolds, z within agent group (n = 5688): 321 = 0.0564 [0.0507, 0.0627]. OpenCode is 187 of the 321 against
  623/5688 of the population. Within it, dayhaysoos/nimbus has 73 against 553.

### Nulls (same prominence)
- No exact-repeat or round-number structure in Claude Code token, tool or duration columns beyond div100 shares
  whose lower CI bounds sit just above 0.01 (1.6).
- No subagent-inclusive formula (F2) explains any session that F0 leaves unmatched.
- No unmatched tally equals another session's recount, so there is no evidence of swapped bookkeeping.
- Timestamp sub-second and second-of-minute digits are consistent with uniform (p 0.684, 0.357).
- No non-mechanical cross-group correlation of |ρ| ≥ 0.5 remains after partialling out size.

---

## Part 2: Interpretation

**The harness token/API tally is an exact, independent second bookkeeping, and it reproduces from the transcript.**
For 5668/5701 = 0.9942 of sessions across 4 scaffolds, five integers written by the Entire CLI equal a deterministic
recount of the stored transcript, with no tolerance. That only holds once three mechanical effects are modelled: the
snapshot is a prefix (metadata is written at commit time while the session keeps going), the window starts at the
declared `checkpoint_transcript_start`, and the `session_logs` metadata is used rather than the deduplicated sessions
row. The remaining 33 (0.0058) are concentrated in a few repos and dev/old CLI builds. Half of the Claude ones differ only
in output_tokens at the snapshot boundary, which fits streaming-partial usage. I found no non-mechanical explanation
for the remaining 6 Claude Code, 3 Codex, 8 OpenCode and 8 Gemini cases. They are candidates for manual inspection,
not evidence of fabrication.

**Implication for witness-free verification.** The usage blocks in the transcript are themselves the evidence. Each
assistant message carries an API-issued `message.id` and usage. Someone who edits a tool *result* inside the transcript
does not change any usage number, so this tally cannot detect result fabrication. It can detect inserted, deleted or
duplicated assistant turns, and re-counted usage. A fabricated assistant message with a fresh id and plausible usage
would move the transcript recount away from a harness tally written at commit time, as long as that tally is stored
outside the transcript (it is, in `metadata.json` on a separate git branch). The detector would sit at 0.0058
unexplained mismatch on honest data (the false-positive floor, CI [0.0041, 0.0081]). The cache-read divisibility result
(Codex 181/181 multiples of 128) is a second, free plausibility check on any reported usage number, provided the
provider's granularity is known.

**What is not a second bookkeeping.** The builder columns (tool counts, durations, turn counts) are functions of the
same transcript, so their agreement says nothing about fabrication. `files_touched` is git-side: it tracks committed
files (0.896 iff-agreement on edited paths) rather than tool calls. That makes it a weak, real cross-check between
"the agent says it edited X" and "X changed in the commit". The commit-witness lens covers that ground better.

**Artifacts other lenses must know about** (all mechanical, all measured above):
1. `conversations.parquet` keeps only the last record per message.id and drops 0.187 of tool_use blocks, mostly
   parallel calls. That produces the orphaned tool_results seen in recon. Any "result without a call" signal built on
   the parquet is contaminated. Use the raw transcripts.
2. Per-turn tokens in `conversations.parquet` cover 0.106 of API calls.
3. Sessions-table token columns come from a different checkpoint snapshot than the stored transcript in 39 sessions.
4. 3650/13406 = 0.272 of checkpoint rows are the same checkpoint_id duplicated under a forked or renamed repo. Repo-level
   clustering and checkpoint counts double-count these.
5. `api_call_count = 0` means "no tally recorded" (132 of the 145 have no token_usage key), not zero calls.
6. The agent label disagrees with the transcript format in a few sessions (`inventory.tx_format_by_agent_label`).

**Correlations and outliers.** Every strong correlation is mechanical: size, the identity of one API call per tool
call, attribution arithmetic, or checkpoint splitting reducing per-session agent_lines. Every multi-axis outlier group
I could characterise is also mechanical: missing tallies, early or dev harness builds, single-repo automation. One
finding is useful. Sessions whose row mixes two snapshots (join artifact) are over-represented among multi-axis
outliers (outlier rate 0.250 [0.138, 0.411] vs 0.0124 [0.0096, 0.0159] for matched sessions), because ratio features like output per API call and tools per API call combine columns
from two different snapshots. A ratio-based outlier screen therefore does catch internally inconsistent bookkeeping,
but at a recall of 9/36 = 0.250 here, and only when the inconsistency is large.

## Candidate mechanisms (novelty UNVERIFIED)
1. **Out-of-band usage ledger reconciliation**: recompute (distinct message ids, summed usage) from the transcript and
   compare exactly with a tally the harness wrote elsewhere at commit time, allowing prefix and declared-offset windows.
   Honest unexplained mismatch is 33/5701. Blind to edits of tool results.
2. **Provider-granularity plausibility**: reported cached-token counts must be multiples of the provider's cache block
   (128 for the Codex/OpenAI path here). Free and stateless. The false-positive rate is 0/181 on Codex.
3. **Cross-snapshot inconsistency via ratio outliers**: a row whose columns come from different snapshots stands out
   on derived ratios (0.250 vs 0.0124 outlier rate).

## Could not measure
- `conversations.parquet` has no message-id column, so "distinct assistant message ids in conversations" was replaced
  by the raw transcripts.
- Copilot (2), Cursor (23) and 2 unparsed files have no recount formula. 1 OpenCode transcript is invalid JSON and 1
  Claude Code session has no transcript.
- Why the 33 residual sessions mismatch. That needs per-session manual reading, which is out of scope for this lens.
- Whether the harness tally would catch a deliberately inserted message. No synthetic injection was run.

## Revision log
- First tx pass: the 64 KiB head sniff misread 6 files whose first record is longer, and 30 newer Claude Code files
  starting with permission-mode/attachment records were not recognised. Both were fixed, and the Gemini JSON parser
  (G0/G1) was added, before any reported outcome (`meta.prereg.format_detection`).
- First conv pass divided microsecond timestamps by 1e9. This was fixed before the duration comparisons were read.
- The `followup` block was added after reading the first report pass (post hoc). That covers the duration
  alternatives, the last-record hypothesis, the join-artifact rescan, the commit-file hypothesis, cache granularity,
  multi-repo checkpoint ids and the outlier sensitivity without api = 0.
