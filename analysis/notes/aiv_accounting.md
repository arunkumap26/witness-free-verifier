# Phase C lens: internal accounting identities in the AI Village Claude Agent SDK stream

Script: `analysis/probes/phase_c_aiv_accounting.py` (reads raw `data/ai-village/claude_code_messages.jsonl.gz` and
`claude_code_sessions.jsonl.gz`; does not use `analysis/cache`). Data: `analysis/out/phase_c/aiv_accounting.json`.
Every number below is in that JSON; the path after each number is relative to its root.

Unit: the RUN (one SDK invocation: an `sdk_session_id` split at each `system/init` row, the loader's rule). 314 runs in
53 sdk sessions (`runs`, `sdk_sessions`). All 314 runs are used (Phase A and B samples together; nothing here sets a
Phase B threshold). CIs are run-clustered bootstraps or Wilson intervals over runs. Runs are resumes of one long
conversation by one agent, so runs are not fully independent even though they are the resampling unit.

Rules added after the first run of the script (all in `post_hoc_rules`, each reported next to the un-ruled version):
failed-resume result rows (error_during_execution, num_turns 0, duration 0) are not attributed to the run they fall in;
responses with zero context usage are kept out of context pairs; an extra per-tool-call term in the linear fit; an
exact-match test for responses missing from result.usage.

---------------------------------------------------------------------------------------------------------------------

## A. Numbers

### A1. Durations (m1_durations; 211 runs with exactly one attributable result and >=1 API response)

| Inequality (tolerance 0) | holds | path |
|---|---|---|
| duration_ms >= created_at(result) - created_at(init) | 131/211 (Wilson 0.554-0.684) | `m1_durations.by_rule.attributable` |
| duration_ms >= union of call->result created_at intervals | 211/211 (0.982-1.0) | same |
| duration_api_ms <= duration_ms | 84/211 (0.334-0.465) | same |
| duration_ms - duration_api_ms >= tool interval union | 26/211 (0.085-0.174) | same |
| duration_api_ms >= created_at-based API-time estimate | 189/211 (0.847-0.93) | same |

- Under the raw rule (no attribution fix) the first inequality holds 129/212 and the tool-union one 209/212; the
  difference comes from runs whose only result row was a failed-resume result appended after them
  (`m1_durations.by_rule.raw`, `post_hoc_rules.attributable_result`).
- duration_ms vs created_at span: ratio median 1.00003 (CI 1.00001-1.00009), p25 0.99927, p75 1.00103
  (`m1_durations.ratios.duration_over_span`); |duration_ms - span| median 30.1 ms (CI 26.1-38.9), p90 230.6 ms,
  p99 2211.4 ms (`m1_durations.slack_ms.abs_duration_minus_span`). Pearson r 0.99999 (`m1_durations.correlations`).
- The single large outlier: run `.../r031`, duration_ms 277325 vs span 509959.7 ms (`m1_durations.largest_abs_duration_minus_span`).
  The same run is the only num_turns mismatch (A2).
- created_at partition of wall time: span - tool union - created_at API estimate has median 69.3 ms, p5 53.5 ms
  (`m1_durations.slack_ms.span_minus_tool_union_minus_createdat_api_estimate`); p75 43508.8 ms because parallel tool
  intervals overlap response intervals.
- duration_api_ms <= duration_ms splits on whether modelUsage lists models that never appear in the stream:
  39/39 in runs with the main model only, 45/172 in runs that also list haiku/sonnet
  (`m1_durations.split_by_nonmain_models`). In main-model-only runs, duration_api_ms over the created_at estimate:
  pooled 1.129 (CI 1.097-1.158).
- Spearman(duration_api_ms, created_at API estimate) 0.968 (CI 0.948-0.982), n 211 (`m1_durations.correlations`).

### A2. Counts, usage, cost (m2_counts_usage; 211 runs)

- **num_turns == (user rows with null subtype) + 1: 210/211** (Wilson 0.974-0.999); the exception is `.../r031`
  (`m2_counts_usage.num_turns.eq_n_user_rows_plus_1`). num_turns == number of API responses: 143/211
  (`...eq_n_api_responses`). So num_turns counts user-side messages (each tool-result row, plus compaction summaries),
  not API responses.
- Per-response usage: input, cache_read and cache_creation never vary across the rows of one response; output_tokens
  varies in 8340 of 65529 multi-row responses (`m2_counts_usage.per_response_usage_constancy`).
- result.usage vs sum over logged responses: input equal in 196/211 (0.886-0.956), cache_read 197/211, cache_creation
  196/211; result is never above the stream sum (result_gt_sum 0); output equal in only 25/211, totals 9231390 (result)
  vs 1603611 (sum of last-row snapshots) (`m2_counts_usage.result_usage_vs_per_response_sum`).
- Responses logged but missing from result.usage (`m2_counts_usage.responses_in_stream_not_in_result_usage`):
  12 runs with result.usage below the stream sum (non-zero), plus 3 runs (`r085`, `r121`, `r140`) where result.usage is
  all zero and the main model is absent from modelUsage although 1-2 main-model responses are logged
  (`m2_counts_usage.modelUsage_main_minus_result_usage.runs_main_model_missing_from_modelUsage_but_main_responses_in_stream`).
  In 6 of the 12 runs exactly one logged response matches the deficit in all three fields; all 6 matched responses carry
  a non-null stop_reason. Base rate of a non-null stop_reason among non-synthetic responses: 131/65550
  (Wilson 0.0017-0.0024). In the 3 all-zero runs, 3/3 have every response with a non-null stop_reason.
  Excluding non-null-stop responses makes result.usage equal the stream sum in 198/211 runs vs 196/211 without the
  exclusion, so the stop_reason pattern is not a complete rule.
- Run-level output identity: result output_tokens vs logged assistant chars including thinking: Spearman 0.9972
  (CI 0.9941-0.9983), pooled 2.379 chars/output token (CI 2.277-2.485), per-run p5-p95 2.132-3.531, n 190 runs.
  Without thinking chars: pooled 1.472 (`m2_counts_usage.result_output_tokens_vs_logged_assistant_chars`).
- modelUsage[main] vs result.usage (`m2_counts_usage.modelUsage_main_minus_result_usage`): runs without compaction
  125/125 equal in all four fields. Runs with compaction (65 runs, 595 compactions): cache_read difference 0 in 65/65;
  input difference == k x compactions in 64/65 with k = 2 (v2.0.77) and 3 (v2.1.38); hidden output tokens vs logged
  compaction-summary chars Spearman 0.9975 (CI 0.9912-0.9993), pooled 3.734 chars/token (CI 3.687-3.79), per-run range
  3.431-4.305; hidden cache_creation / sum(pre_tokens) pooled 0.860 (CI 0.843-0.872); no field ever negative.
- Non-main models (haiku, sonnet) are listed in 172/211 runs (Wilson 0.757-0.862) but no response of theirs appears in
  the stream (assistant rows by model: 168245 opus, 21 `<synthetic>`); their pooled cost share is 0.00496
  (CI 0.0038-0.0064) (`m2_counts_usage.modelUsage_composition`).
- total_cost_usd == sum of modelUsage costUSD within 1e-6 USD: 265/265 result rows (`m2_counts_usage.cost_total_vs_modelUsage_sum`).
- Implied prices fitted from the data alone (no outside prices), USD per million tokens
  (`m2_counts_usage.implied_price_fit`): opus input 5.00, output 25.00, cache read 0.50, cache creation 6.25; haiku
  1.00 / 5.00 / 0.10 / 1.25; sonnet 3.00 / 15.00 / 0.30 / 3.75. Reproduction within tolerance: 190/190, 172/172,
  141/141 (largest abs residual 1.2e-12 USD). 1-hour cache creation tokens: 0 in every result row.

### A3. created_at semantics (m3_created_at)

- No identical created_at between adjacent rows of a run (0 of 244506), none globally (0 groups); no adjacent gap under
  10 ms; minimum gaps 17.5-46.2 ms depending on transition (`m3_created_at.gaps_ms_by_transition`).
- Medians by transition: block-to-block within one response 534.0 ms (CI 505.9-577.1), response row -> tool result
  407.1 ms, tool result -> next response 3336.3 ms, last response row -> result row 63.7 ms, status -> compact_boundary
  34.5 ms (`m3_created_at.gaps_ms_by_transition.*.median` / `describe`).
- Within one response, the gap before a block tracks that block's size: Pearson 0.930 (CI 0.919-0.948), Spearman 0.788
  (CI 0.753-0.819), n 99701 in 241 runs; median 162.1 chars/s (CI 155.5-168.0)
  (`m3_created_at.within_message_gap_vs_next_block_chars`).
- Tool-reported durations vs created_at call->result gap (`m3_created_at.tool_reported_duration_vs_gap`): gap >= reported
  duration for WebFetch 28/29 (median slack 33.3 ms), Glob 132/133 (44.0 ms), WebSearch 45/47 (27.6 ms, only 2 runs);
  minimum slack -37.2 ms. Spearman(gap, reported) 0.992 WebFetch, 0.9995 WebSearch, 0.096 Glob (Glob durations are tiny).
- Ordering (`m3_created_at.ordering`): tool result created before its call 0; next response's first row before all
  results of the previous response 0 of 65309; block-type order inversions within a response 0; 3002 tool results are
  created before the calling response's last row (tools start while the response is still streaming); 2813 multi-row
  responses are interleaved with other rows.
- Linkage (`m3_created_at.linkage_fields`): parent_tool_use_id non-null 0, parentUuid key present 0, message_uuid column
  non-null 0; content.uuid present and distinct on 244819 rows. There is no uuid chain to test against.
- sessions table: every one of 303 sessions rows is immediately preceded (global created_at order) by a system/init row,
  302 of the same sdk session; lag median 27.9 ms (CI 27.1-29.5), max 1180.3 ms (`m3_created_at.sessions_table`).
  11 sdk sessions have init rows but no sessions row.

### A4. Context growth / token conservation (m4_context)

- 65571 API responses, 21 with zero context usage; 65310 consecutive pairs in 190 runs: clean 59804, image 4570,
  compact 933, zero_usage 3 (`m4_context.pair_categories`).
- Negative context deltas (`m4_context.negative_delta.by_category`): compact 933/933, image 27/4570, clean 3/59804,
  zero_usage 3/3. The 30 negative clean+image pairs all reset cache_read to 20401-21400 tokens (median delta -9249)
  (`...negative_nonzero_noncompact_with_cache_read_reset`). No zero deltas.
- **Cache chain: cache_read(k+1) == cache_read(k) + cache_creation(k) in 59747/59804 clean pairs**, run-clustered
  rate 0.99905 (CI 0.99858-0.99943); image pairs 4367/4570 (breaks have median -2104 tokens); compact pairs 0/933
  (`m4_context.cache_chain`). Uncached input of the next response: median 8 tokens, p99 10.
- Clean-pair delta vs chars appended (`m4_context.clean`): with thinking chars Pearson 0.982 (CI 0.971-0.990),
  Spearman 0.986 (CI 0.981-0.989), pooled 2.610 chars/token (CI 2.586-2.638), per-pair median 2.535 (CI 2.508-2.57),
  p5-p95 2.078-2.87. Without thinking chars: Spearman 0.982, median 2.433, p5 1.56.
- Linear fit (pre-registered 3 terms) tokens per char: user 0.3437, assistant visible 0.3070, thinking 0.2739,
  intercept 237.3; R2 0.9663; |residual| median 49.6 tokens (CI 42.1-56.5), p90 201.0, p99 685.7. Half-split hold-out
  (fit on one half of runs, evaluate on the other): R2 0.9718, |residual| median 51.7, p90 221.6, p99 667.7
  (`m4_context.clean.linear_fits.prereg_3term`). Post-hoc 5-term fit: per tool call 138.6 tokens, intercept 95.0,
  |residual| median 45.4, p99 664.2 (`...posthoc_extended`). |residual| / delta: median 0.023, p90 0.236, p99 0.887.
- Per tool (single call answered by a single result, `m4_context.clean.per_tool_single_call_pairs`): chars/token median
  ranges from 2.289 (Grep) to 3.112 (Write); get_events (29192 pairs) |residual| p50 27.1 / p99 585.8; built-in tools
  Bash, Read, Grep, Glob, Edit, TodoWrite have mean residuals between -92.7 and -193.8 tokens (built-in Write: -15.1),
  village MCP tools between -40.3 and +35.7.
- Images (stripped from the export as `[IMAGE_REMOVED]`): residual tokens per image median 898.8 (CI 896.7-899.6),
  p25 887.6, p75 901.4, p95 1007.1; 259 of 4543 fall in 316-562 tokens (`m4_context.image_pairs_positive_delta`).
- Compaction (`m4_context.compaction`): pre_tokens equals the last response's context 0/933 and is never below it;
  pre_tokens - last context vs chars appended after it: Spearman 0.819 (CI 0.725-0.898), median 3.775 chars/token
  (n 863). Post-compaction context median 26465.5 tokens; Spearman with summary chars -0.135 (CI -0.274 to 0.030).
- Across runs (resume), first response of run r+1 vs last of run r (234 pairs without compaction): negative delta
  88/234, cache chain holds 1/234, cache_read zero 34/234 (`m4_context.cross_run_resume`).

---------------------------------------------------------------------------------------------------------------------

## B. Interpretation (not data)

**For Phase A, created_at behaves like event time with tens of milliseconds of lag.** The SDK's own wall clock
(duration_ms) matches the created_at span to a median 30 ms; tool-reported durations sit inside created_at gaps with
median slack of 27.6-44.0 ms; and the gaps between blocks of one response grow with block size at ~160 chars/s, which only happens
if rows are written as blocks finish streaming, not in a batch. There are no ties and no sub-10 ms gaps; the minimum adjacent gap
is 17.5-46.2 ms depending on transition, which looks like an insert-latency floor. Two caveats for Phase A: tool results can be created before the calling response's last row
(streaming tool execution), and the row `id` is random, so it carries no order.

**The result row is a strong internal ledger, and most of it reconciles exactly.**
- num_turns is a row-count checksum: tool-result/summary rows + 1, exact in 210/211 runs. Removing or inserting a
  tool-result row would break it.
- Cost is an exact linear function of modelUsage tokens with per-model coefficients recoverable from the data, so
  cost and tokens cannot be edited independently.
- modelUsage[main] = result.usage + one hidden call per compaction (fixed 2 or 3 input tokens, zero cache read). That
  call's output tokens track the logged summary text (Spearman 0.9975). The stream does not record the call, but the
  ledger lets the logged summary be checked against the server's token count for it.
- result.usage equals the sum of logged per-response usage in about 93% of runs and is never larger. The exceptions go
  the other way: the log holds responses the ledger does not count (15 of 211 runs). A fabricated assistant turn
  inserted into a log would show this same signature. In this corpus the benign cause looks like an SDK path that emits
  final-usage, non-null-stop_reason responses (6/6 exact single matches have one, against a base rate of about 0.2%),
  but that is an association, not a mechanism. **This is the main false-positive source for a "log vs ledger" check.**
- duration_api_ms <= duration_ms is not a physical law in this data: it fails mainly because hidden
  haiku/sonnet calls (never in the stream) add API time. In runs with the main model only, it holds 39/39.

**Token conservation works at the level of individual turns.** Server-side context counts follow the logged appended
content tightly (Spearman 0.986), and the cache chain shows the context grows almost purely by appending (99.9% exact).
So each turn's logged tool result plus assistant output is constrained to the server-observed increment, within an
absolute residual of 49.6 tokens at the median and 685.7 at p99 (hold-out 51.7 / 667.7) under a crude chars-based model. That is a usable witness-free
check: a tool result whose logged length differs from what the model saw by more than a few hundred tokens would stand
out. Length-preserving substitutions would not. Measured false-positive sources:
- images stripped from the log (about 900 tokens each; the budget is recoverable, but the content is not)
- unlogged context edits: 30 drops back to the system-prompt prefix without a compact_boundary
- per-tool framing offsets (six built-in tools have mean residuals of -92.7 to -193.8 tokens)
- compaction
- resumes, where the chain holds in only 1/234 cases, so the check does not carry across runs

A real tokenizer was not used (no new dependencies), so the residual floor here is an upper bound.

**Nulls.**
- Post-compaction context size does not track summary length (Spearman -0.135, CI spans 0). Post-compaction context
  exceeds summary chars / 2.5 by a median 22975.1 tokens of content not in the stream
  (`m4_context.compaction.post_ctx_minus_summary_chars_over_2_5_describe`).
- Glob's own durationMs does not predict the created_at gap (Spearman 0.096).
- Per-row output_tokens in the stream is a streaming snapshot, not the final count. Only the run-level total is
  usable.
- There is no uuid or parent chain in this stream to check ordering against.

**Novelty (UNVERIFIED).** Using the provider's own cache accounting (the cache-chain identity) together with context
deltas as a content-length witness for agent tool logs may not have been described for fabrication detection. I have
not checked the literature. Cost-ledger reconciliation and timing checks are standard auditing ideas.
