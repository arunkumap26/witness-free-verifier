# Phase C lens: correlations (Spearman scan within corpora)

- Script: `analysis/probes/phase_c_correlations.py`. Run: `PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_c_correlations`
  (single process, about 2 minutes; deterministic, so a rerun reproduces the JSON).
- Data: `analysis/out/phase_c/correlations.json`. It holds raw numbers only: feature profiles, every eligible pair in every
  unit (`all_pairs`, column names in `all_pairs_columns`), the top lists, the replication verdicts, the pre-registered
  rules (`prereg`), the rules added after run 1 (`post_hoc`), and the post-hoc follow-ups `F1`-`F7`
  (`units.<unit>.post_hoc_followups`).
- Inputs: the IR caches only (`analysis/cache/*_{B,A}.parquet`, `swechat_population.parquet`, `aiv_cu_sessions.parquet`,
  `whowhen_labels.json`). cc_local appears here only as correlations, counts and quantiles.

Every number below is in the JSON, rounded here to 3 decimals. Rates are `rate [95% CI] num/den`, with session-clustered
bootstrap CIs (`lib/stats.py`) unless stated. Part A is measurement. Part B is interpretation.

---------------------------------------------------------------------------------------------------------------------

## Part A. Measurements

### A0. Design (fixed before any correlation was computed; `prereg`)

**Units.**
- Discovery: `<corpus>/B` for each of the five corpora.
- Replication:
  - `<corpus>/A`, the held-out Phase A split of the same corpus.
  - The other corpora.
  - The swechat B format strata `swechat/B:{claude_code,opencode,codex}`. These are subsets of `swechat/B`, so they are
    reported but never counted as replications (`post_hoc.independent_units`).
  - The 78,114-session aiv_cu population table, session level only, with six features (`units.aiv_cu/population`).

**Sizes** (`units.<u>.n_sessions / n_calls / n_events`):

| unit | sessions / calls / events |
|---|---|
| swechat/B | 2,000 / 214,592 / 933,268 |
| cc_local/B | 186 / 36,542 / 147,506 |
| aiv_cc/B | 189 / 38,746 / 131,676 |
| aiv_cu/B | 2,000 / 59,956 / 158,111 |
| whowhen/B | 111 / 595 / 2,638 |

- A splits (sessions / calls): swechat 200 / 21,749; cc_local 123 / 5,165; aiv_cc 125 / 33,479; aiv_cu 200 / 6,107;
  whowhen 73 / 373.
- swechat B formats: claude_code 1,679 / 194,652; opencode 214 / 8,199; codex 77 / 9,801.

**Features.** Definitions are in `feature_defs` and the raw-column lineage of each is in `feature_lineage`.
- Per call (28): tool-class indicators `t_*`; `lat_ms` (result ts minus call ts); `hdur_ms` (harness-reported duration);
  `prog_s` (CC progress timer); `res_len`, `stderr_len`, `arg_len`; `err` (native_error true or a CC/Who&When
  failure marker); `nerr` (native_error alone); `prev_err`; `same_tool_prev`; `pos_idx`, `pos_rel`; `gap_prev_ms`
  (since the previous event); `gap_input_ms` (since the latest earlier result/user/system event, i.e. model
  turnaround); the issuing response's `resp_out`, `resp_ctx`, `resp_think`, `resp_ncalls`; `sub`; `srv_ms` (Gemini
  server timing, aiv_cu only).
- Per session (24): counts, `err_rate`, `nerr_rate`, `n_tools`, `dur_s`, token sums, `n_compact`, `sub_share`,
  `think_sum`, `shell_share`, medians of `res_len` / `arg_len` / `lat_ms` / `gap_input_ms`, `calls_per_resp`, plus the
  Who&When labels `is_correct` and `mistake_step / history_len`.
- A feature is dropped from a unit if it is constant there or non-null in fewer than 200 calls / 30 sessions
  (`units.<u>.<level>.dropped`).

**Statistics.**
- rho is Spearman on pairwise-complete rows. CIs are session-clustered bootstraps (1,000 replicates) of the Pearson
  correlation of the pair's fixed mid-ranks.
- Three extra views:
  - `rho_within`: ranks minus the session mean, which removes between-session differences.
  - `rho_within_tool`: ranks minus the tool mean.
  - `rho_partial` (session level): partial on rank(n_events), i.e. size.
- Pairs that are definitional by construction were declared before computing: two tool indicators, pos_idx-pos_rel,
  err-nerr, err_rate-nerr_rate, n_calls-n_results. They stay in the raw lists with flag `D`. The `*_excl` lists omit them.
- Eligibility: at least 200 rows in at least 10 sessions (call level), or at least 30 sessions (session level).
- Replication rule: the CI in the other unit excludes 0, has the discovery sign, and |rho| >= 0.1, on the same statistic.

**Fixed-rank approximation check** (`units.<u>.exact_rerank_check_summary`; the top 10 call and top 10 session pairs per
unit, re-ranked inside every replicate, 200 replicates):

| unit | max absolute difference in a CI bound | median |
|---|---|---|
| swechat | 0.054 | 0.001 |
| cc_local | 0.116 | 0.004 |
| aiv_cc | 0.028 | 0.006 |
| aiv_cu | 0.010 | 0.002 |
| whowhen | 0.031 | 0.012 |

The worst case is cc_local `gap_prev_ms|gap_input_ms`: approximate [0.321, 0.705], exact [0.205, 0.699]. cc_local
lower bounds are therefore the least reliable.

**Changes after run 1** (`post_hoc`):
- A numerical guard: `rho_within` is null when the within-session variance is at most 1e-9 of the total.
- The independent-unit count no longer includes the swechat format strata.
- Follow-ups F1-F7, all labelled post hoc, each with what motivated it.

### A1. Annotation codes (interpretation; used in the tables)

Mechanical codes:
- **D**: definitional or declared.
- **Z**: size family. Both features scale with session length.
- **S**: shared input, shared endpoint or compositional. Examples: tool args and thinking are counted in output tokens;
  gap_prev and gap_input end at the same call ts; parts of a fixed total.
- **T**: tool composition. The pair involves a tool indicator, or it collapses within tool.
- **C**: between-session composition. The pair collapses within session.
- **H**: known harness or IR behavior, measured in F1-F7, documented in the loader docstrings, or measured in
  `aiv_accounting`.
- **P**: serving physics. Streaming, generation or prefill time tracks chars or tokens. `aiv_accounting` found the same
  for block gaps in aiv_cc.

Non-mechanical codes:
- **B**: a cause is stated but not tested.
- **U**: unexplained.

B and U together are "unexplained" in the sense of the task.

"indep. rep" is k/n: the pair replicates in k of the n independent units where it is computable. "A" is the verdict in
the same corpus's held-out A split.

### A2. Top 25 |rho| per corpus: per call (pooled) and per session (raw)

#### swechat/B call_pooled

| # | pair | rho [95% CI] | n / sessions | within-sess | within-tool | partial | A | indep. rep | code |
|---|---|---|---|---|---|---|---|---|---|
| 1 | err - nerr | +1.000 [+1.000, +1.000] | 80977 / 1833 | +1.000 | +1.000 | NA | rep | 5/5 | D |
| 2 | lat_ms - prog_s | +0.869 [+0.841, +0.894] | 7099 / 724 | +0.846 | +0.847 | NA | rep | 1/1 | H |
| 3 | lat_ms - hdur_ms | +0.844 [+0.697, +0.968] | 10764 / 1199 | +0.750 | +0.564 | NA | rep | 3/3 | H |
| 4 | t_subagent - hdur_ms | +0.754 [+0.665, +0.836] | 10764 / 1199 | +0.659 | NA | NA | rep | 1/1 | T |
| 5 | resp_out - sub | -0.580 [-0.607, -0.548] | 204524 / 1883 | -0.622 | -0.550 | NA | rep | 2/3 | H |
| 6 | t_edit - arg_len | +0.567 [+0.553, +0.581] | 214583 / 1951 | +0.579 | NA | NA | rep | 5/5 | T |
| 7 | hdur_ms - arg_len | +0.567 [+0.401, +0.726] | 10764 / 1199 | +0.508 | -0.108 | NA | rep | 1/3 | T |
| 8 | t_read - res_len | +0.550 [+0.517, +0.571] | 214065 / 1946 | +0.560 | NA | NA | rep | 2/7 | T |
| 9 | gap_input_ms - sub | -0.539 [-0.567, -0.508] | 214425 / 1946 | -0.470 | -0.493 | NA | rep | 3/3 | H+B |
| 10 | pos_idx - pos_rel | +0.532 [+0.498, +0.566] | 214576 / 1935 | +0.884 | +0.515 | NA | rep | 9/9 | D |
| 11 | t_mcp - prog_s | -0.520 [-0.591, -0.431] | 7127 / 728 | -0.356 | NA | NA | rep | 1/1 | T |
| 12 | t_shell - lat_ms | +0.515 [+0.495, +0.537] | 214063 / 1944 | +0.505 | NA | NA | rep | 5/5 | T |
| 13 | hdur_ms - gap_prev_ms | +0.507 [+0.388, +0.637] | 10764 / 1199 | +0.319 | +0.124 | NA | rep | 1/3 | U |
| 14 | arg_len - gap_prev_ms | +0.491 [+0.459, +0.514] | 214416 / 1946 | +0.489 | +0.260 | NA | rep | 5/7 | P |
| 15 | pos_idx - resp_ctx | +0.490 [+0.443, +0.537] | 204524 / 1883 | +0.481 | +0.476 | NA | rep | 3/7 | H |
| 16 | gap_input_ms - resp_ncalls | -0.484 [-0.502, -0.467] | 204624 / 1883 | -0.442 | -0.418 | NA | rep | 3/6 | U |
| 17 | hdur_ms - resp_out | +0.482 [+0.438, +0.524] | 5517 / 1180 | +0.466 | +0.188 | NA | rep | 1/3 | B |
| 18 | hdur_ms - prog_s | +0.479 [+0.337, +0.592] | 275 / 94 | +0.393 | +0.479 | NA | na | 0/0 | H |
| 19 | resp_ctx - sub | -0.461 [-0.491, -0.427] | 204524 / 1883 | -0.490 | -0.413 | NA | rep | 2/3 | H |
| 20 | gap_prev_ms - resp_ncalls | -0.441 [-0.459, -0.419] | 204624 / 1883 | -0.441 | -0.367 | NA | rep | 3/6 | S |
| 21 | t_shell - t_read | -0.439 [-0.453, -0.426] | 214592 / 1951 | -0.411 | NA | NA | rep | 7/7 | D |
| 22 | gap_input_ms - resp_out | +0.432 [+0.404, +0.459] | 204524 / 1883 | +0.430 | +0.356 | NA | rep | 5/7 | P |
| 23 | gap_prev_ms - gap_input_ms | +0.432 [+0.377, +0.481] | 214425 / 1946 | +0.462 | +0.307 | NA | rep | 6/7 | S |
| 24 | t_shell - prog_s | +0.431 [+0.334, +0.508] | 7127 / 728 | +0.250 | NA | NA | not_rep | 0/1 | T |
| 25 | gap_input_ms - resp_ctx | +0.426 [+0.404, +0.448] | 204524 / 1883 | +0.382 | +0.378 | NA | rep | 3/7 | P |


#### swechat/B session

| # | pair | rho [95% CI] | n / sessions | within-sess | within-tool | partial | A | indep. rep | code |
|---|---|---|---|---|---|---|---|---|---|
| 1 | n_calls - n_results | +0.998 [+0.995, +1.000] | 2000 / 2000 | NA | NA | +0.973 | rep | 9/9 | D |
| 2 | n_resp - ctx_sum | +0.976 [+0.973, +0.978] | 1980 / 1980 | NA | NA | +0.761 | rep | 7/7 | Z |
| 3 | n_calls - n_resp | +0.971 [+0.968, +0.974] | 1980 / 1980 | NA | NA | +0.694 | rep | 7/7 | Z |
| 4 | n_results - n_resp | +0.971 [+0.968, +0.974] | 1980 / 1980 | NA | NA | +0.694 | rep | 7/7 | Z |
| 5 | n_calls - ctx_sum | +0.958 [+0.954, +0.962] | 1980 / 1980 | NA | NA | +0.589 | rep | 7/7 | Z |
| 6 | n_results - ctx_sum | +0.958 [+0.954, +0.962] | 1980 / 1980 | NA | NA | +0.590 | rep | 7/7 | Z |
| 7 | n_events - n_resp | +0.952 [+0.947, +0.957] | 1980 / 1980 | NA | NA | NA | rep | 7/7 | Z |
| 8 | n_events - n_results | +0.952 [+0.946, +0.957] | 2000 / 2000 | NA | NA | NA | rep | 9/9 | Z |
| 9 | n_events - n_calls | +0.952 [+0.946, +0.957] | 2000 / 2000 | NA | NA | NA | rep | 10/10 | Z |
| 10 | n_events - ctx_sum | +0.945 [+0.939, +0.950] | 1980 / 1980 | NA | NA | NA | rep | 7/7 | Z |
| 11 | n_asst - n_resp | +0.910 [+0.901, +0.920] | 1980 / 1980 | NA | NA | +0.475 | rep | 7/7 | Z |
| 12 | ctx_max - ctx_sum | +0.892 [+0.879, +0.903] | 1980 / 1980 | NA | NA | +0.696 | rep | 7/7 | Z |
| 13 | n_asst - ctx_sum | +0.889 [+0.873, +0.903] | 1980 / 1980 | NA | NA | +0.344 | rep | 7/7 | Z |
| 14 | n_events - n_asst | +0.884 [+0.874, +0.895] | 2000 / 2000 | NA | NA | NA | rep | 9/9 | Z |
| 15 | err_rate - nerr_rate | +0.872 [+0.858, +0.884] | 1833 / 1833 | NA | NA | +0.863 | rep | 7/7 | D |
| 16 | n_calls - n_asst | +0.865 [+0.853, +0.877] | 2000 / 2000 | NA | NA | +0.164 | rep | 9/9 | Z |
| 17 | n_results - n_asst | +0.863 [+0.850, +0.875] | 2000 / 2000 | NA | NA | +0.144 | rep | 9/9 | Z |
| 18 | n_results - ctx_max | +0.822 [+0.804, +0.840] | 1980 / 1980 | NA | NA | +0.338 | rep | 7/7 | Z |
| 19 | n_calls - ctx_max | +0.822 [+0.804, +0.840] | 1980 / 1980 | NA | NA | +0.338 | rep | 7/7 | Z |
| 20 | dur_s - n_resp | +0.821 [+0.803, +0.839] | 1980 / 1980 | NA | NA | +0.326 | rep | 7/7 | Z |
| 21 | n_asst - dur_s | +0.815 [+0.797, +0.831] | 1991 / 1991 | NA | NA | +0.375 | rep | 7/7 | Z |
| 22 | dur_s - ctx_sum | +0.804 [+0.784, +0.823] | 1980 / 1980 | NA | NA | +0.246 | rep | 7/7 | Z |
| 23 | n_events - dur_s | +0.803 [+0.783, +0.821] | 1991 / 1991 | NA | NA | NA | rep | 8/8 | Z |
| 24 | n_events - ctx_max | +0.798 [+0.779, +0.818] | 1980 / 1980 | NA | NA | NA | rep | 7/7 | Z |
| 25 | n_calls - n_tools | +0.795 [+0.776, +0.812] | 2000 / 2000 | NA | NA | +0.331 | rep | 8/9 | Z |


#### cc_local/B call_pooled

| # | pair | rho [95% CI] | n / sessions | within-sess | within-tool | partial | A | indep. rep | code |
|---|---|---|---|---|---|---|---|---|---|
| 1 | err - nerr | +1.000 [+1.000, +1.000] | 27222 / 174 | +1.000 | +1.000 | NA | rep | 5/5 | D |
| 2 | lat_ms - hdur_ms | +0.946 [+0.929, +0.958] | 918 / 110 | +0.902 | +0.923 | NA | rep | 3/3 | H |
| 3 | gap_prev_ms - gap_input_ms | +0.643 [+0.321, +0.705] | 36542 / 174 | +0.673 | +0.662 | NA | rep | 6/7 | S |
| 4 | pos_idx - pos_rel | +0.633 [+0.468, +0.777] | 36507 / 139 | +0.903 | +0.663 | NA | rep | 9/9 | D |
| 5 | t_search - hdur_ms | -0.541 [-0.641, -0.366] | 918 / 110 | NA | NA | NA | rep | 2/3 | T |
| 6 | t_web - hdur_ms | +0.541 [+0.366, +0.641] | 918 / 110 | NA | NA | NA | rep | 2/3 | T |
| 7 | arg_len - gap_prev_ms | +0.500 [+0.467, +0.735] | 36542 / 174 | +0.459 | +0.363 | NA | rep | 5/7 | P |
| 8 | pos_idx - resp_out | -0.489 [-0.594, +0.080] | 36542 / 174 | -0.408 | -0.501 | NA | not_rep | 2/7 | H |
| 9 | t_shell - t_edit | -0.488 [-0.605, -0.240] | 36542 / 174 | -0.536 | NA | NA | rep | 3/5 | D |
| 10 | t_shell - same_tool_prev | +0.485 [+0.282, +0.548] | 36368 / 139 | +0.473 | NA | NA | rep | 6/9 | T |
| 11 | t_search - resp_think | +0.477 [+0.343, +0.744] | 36542 / 174 | +0.193 | NA | NA | rep | 1/5 | T |
| 12 | t_shell - t_read | -0.443 [-0.622, -0.263] | 36542 / 174 | -0.456 | NA | NA | rep | 7/7 | D |
| 13 | gap_prev_ms - resp_ctx | +0.434 [+0.326, +0.593] | 36542 / 174 | +0.379 | +0.349 | NA | rep | 4/7 | P |
| 14 | t_shell - lat_ms | +0.427 [+0.171, +0.541] | 36542 / 174 | +0.441 | NA | NA | rep | 5/5 | T |
| 15 | pos_idx - sub | +0.425 [+0.313, +0.646] | 36542 / 174 | +0.143 | +0.394 | NA | rep | 1/3 | B |
| 16 | resp_ctx - resp_ncalls | -0.422 [-0.527, -0.335] | 36542 / 174 | -0.400 | -0.342 | NA | rep | 3/6 | B |
| 17 | hdur_ms - pos_rel | -0.392 [-0.479, -0.296] | 918 / 110 | -0.426 | -0.321 | NA | rep | 1/3 | U |
| 18 | hdur_ms - resp_think | -0.389 [-0.504, -0.229] | 918 / 110 | -0.165 | -0.128 | NA | rep | 1/3 | U |
| 19 | t_shell - nerr | -0.388 [-0.458, -0.318] | 27222 / 174 | -0.374 | NA | NA | rep | 4/5 | H |
| 20 | gap_input_ms - resp_ctx | +0.378 [+0.247, +0.503] | 36542 / 174 | +0.383 | +0.344 | NA | not_rep | 3/7 | P |
| 21 | t_edit - lat_ms | -0.374 [-0.479, -0.196] | 36542 / 174 | -0.416 | NA | NA | rep | 3/5 | T |
| 22 | gap_input_ms - sub | -0.370 [-0.587, -0.286] | 36542 / 174 | -0.309 | -0.355 | NA | rep | 3/3 | B |
| 23 | arg_len - resp_ncalls | -0.368 [-0.517, -0.290] | 36542 / 174 | -0.312 | -0.219 | NA | rep | 3/6 | B |
| 24 | t_edit - arg_len | +0.353 [+0.268, +0.400] | 36542 / 174 | +0.347 | NA | NA | rep | 5/5 | T |
| 25 | t_mcp - nerr | +0.352 [+0.261, +0.417] | 27222 / 174 | +0.332 | NA | NA | rep | 3/5 | H |


#### cc_local/B session

| # | pair | rho [95% CI] | n / sessions | within-sess | within-tool | partial | A | indep. rep | code |
|---|---|---|---|---|---|---|---|---|---|
| 1 | n_calls - n_results | +1.000 [+1.000, +1.000] | 186 / 186 | NA | NA | +1.000 | rep | 9/9 | D |
| 2 | n_events - n_calls | +0.988 [+0.983, +0.993] | 186 / 186 | NA | NA | NA | rep | 10/10 | Z |
| 3 | n_events - n_results | +0.988 [+0.983, +0.993] | 186 / 186 | NA | NA | NA | rep | 9/9 | Z |
| 4 | n_resp - ctx_sum | +0.988 [+0.985, +0.992] | 186 / 186 | NA | NA | +0.670 | rep | 7/7 | Z |
| 5 | n_events - ctx_sum | +0.983 [+0.977, +0.988] | 186 / 186 | NA | NA | NA | rep | 7/7 | Z |
| 6 | n_events - n_resp | +0.982 [+0.975, +0.988] | 186 / 186 | NA | NA | NA | rep | 7/7 | Z |
| 7 | n_calls - n_resp | +0.975 [+0.962, +0.985] | 186 / 186 | NA | NA | +0.169 | rep | 7/7 | Z |
| 8 | n_results - n_resp | +0.975 [+0.962, +0.985] | 186 / 186 | NA | NA | +0.169 | rep | 7/7 | Z |
| 9 | dur_s - tok_out | +0.973 [+0.954, +0.985] | 186 / 186 | NA | NA | +0.860 | rep | 7/7 | Z |
| 10 | n_calls - ctx_sum | +0.973 [+0.962, +0.981] | 186 / 186 | NA | NA | +0.051 | rep | 7/7 | Z |
| 11 | n_results - ctx_sum | +0.973 [+0.962, +0.981] | 186 / 186 | NA | NA | +0.051 | rep | 7/7 | Z |
| 12 | tok_out - ctx_sum | +0.917 [+0.878, +0.949] | 186 / 186 | NA | NA | +0.238 | rep | 6/7 | Z |
| 13 | n_events - tok_out | +0.915 [+0.873, +0.950] | 186 / 186 | NA | NA | NA | rep | 7/7 | Z |
| 14 | n_resp - tok_out | +0.914 [+0.873, +0.947] | 186 / 186 | NA | NA | +0.201 | rep | 7/7 | Z |
| 15 | n_calls - tok_out | +0.908 [+0.860, +0.946] | 186 / 186 | NA | NA | +0.053 | rep | 7/7 | Z |
| 16 | n_results - tok_out | +0.908 [+0.860, +0.946] | 186 / 186 | NA | NA | +0.053 | rep | 7/7 | Z |
| 17 | ctx_max - ctx_sum | +0.907 [+0.878, +0.932] | 186 / 186 | NA | NA | +0.320 | rep | 7/7 | Z |
| 18 | dur_s - ctx_sum | +0.897 [+0.852, +0.933] | 186 / 186 | NA | NA | +0.254 | rep | 7/7 | Z |
| 19 | nerr_rate - shell_share | -0.897 [-0.921, -0.869] | 174 / 174 | NA | NA | -0.850 | rep | 5/6 | H |
| 20 | n_events - ctx_max | +0.896 [+0.864, +0.925] | 186 / 186 | NA | NA | NA | rep | 7/7 | Z |
| 21 | dur_s - n_resp | +0.893 [+0.849, +0.929] | 186 / 186 | NA | NA | +0.206 | rep | 7/7 | Z |
| 22 | n_events - dur_s | +0.892 [+0.846, +0.931] | 186 / 186 | NA | NA | NA | rep | 8/8 | Z |
| 23 | err_rate - nerr_rate | +0.887 [+0.849, +0.916] | 174 / 174 | NA | NA | +0.866 | rep | 7/7 | D |
| 24 | n_calls - ctx_max | +0.882 [+0.847, +0.912] | 186 / 186 | NA | NA | -0.057 | rep | 7/7 | Z |
| 25 | n_results - ctx_max | +0.882 [+0.847, +0.912] | 186 / 186 | NA | NA | -0.057 | rep | 7/7 | Z |


#### aiv_cc/B call_pooled

| # | pair | rho [95% CI] | n / sessions | within-sess | within-tool | partial | A | indep. rep | code |
|---|---|---|---|---|---|---|---|---|---|
| 1 | err - nerr | +1.000 [+1.000, +1.000] | 5698 / 66 | +1.000 | +1.000 | NA | rep | 5/5 | D |
| 2 | t_shell - nerr | -0.780 [-0.853, -0.626] | 5698 / 66 | -0.687 | NA | NA | rep | 4/5 | H |
| 3 | arg_len - gap_prev_ms | +0.768 [+0.702, +0.820] | 38746 / 123 | +0.777 | +0.649 | NA | rep | 5/7 | P |
| 4 | pos_idx - pos_rel | +0.683 [+0.618, +0.744] | 38701 / 78 | +0.923 | +0.714 | NA | rep | 9/9 | D |
| 5 | t_gui - nerr | +0.678 [+0.384, +0.783] | 5698 / 66 | +0.561 | NA | NA | rep | 1/1 | H |
| 6 | t_shell - t_mcp | -0.603 [-0.717, -0.467] | 38746 / 123 | -0.718 | NA | NA | rep | 3/5 | D |
| 7 | gap_input_ms - resp_think | +0.603 [+0.552, +0.649] | 38620 / 78 | +0.610 | +0.551 | NA | rep | 5/7 | P |
| 8 | gap_prev_ms - gap_input_ms | +0.547 [+0.507, +0.583] | 38620 / 78 | +0.524 | +0.441 | NA | rep | 6/7 | S |
| 9 | t_mcp - arg_len | -0.539 [-0.600, -0.452] | 38746 / 123 | -0.427 | NA | NA | rep | 3/5 | T |
| 10 | lat_ms - stderr_len | -0.504 [-0.561, -0.399] | 4919 / 47 | -0.257 | -0.504 | NA | rep | 1/4 | U |
| 11 | arg_len - gap_input_ms | +0.460 [+0.396, +0.511] | 38620 / 78 | +0.383 | +0.311 | NA | rep | 5/7 | P |
| 12 | t_shell - arg_len | +0.455 [+0.376, +0.515] | 38746 / 123 | +0.476 | NA | NA | rep | 6/9 | T |
| 13 | t_gui - lat_ms | +0.404 [+0.254, +0.513] | 38738 / 119 | +0.350 | NA | NA | rep | 1/1 | T |
| 14 | t_gui - t_mcp | -0.402 [-0.473, -0.323] | 38746 / 123 | -0.266 | NA | NA | rep | 1/1 | D |
| 15 | t_read - res_len | -0.398 [-0.518, -0.280] | 38738 / 119 | -0.500 | NA | NA | rep | 2/7 | T |
| 16 | lat_ms - nerr | -0.366 [-0.533, -0.213] | 5698 / 66 | -0.319 | -0.095 | NA | rep | 3/5 | B |
| 17 | t_mcp - res_len | +0.355 [+0.261, +0.461] | 38738 / 119 | +0.446 | NA | NA | rep | 1/5 | T |
| 18 | t_read - t_mcp | -0.340 [-0.392, -0.283] | 38746 / 123 | -0.193 | NA | NA | rep | 1/5 | D |
| 19 | arg_len - same_tool_prev | -0.339 [-0.433, -0.203] | 38623 / 78 | -0.225 | +0.011 | NA | rep | 1/9 | T |
| 20 | lat_ms - res_len | +0.319 [+0.178, +0.470] | 38738 / 119 | +0.366 | +0.281 | NA | rep | 2/5 | U |
| 21 | t_shell - gap_prev_ms | +0.312 [+0.249, +0.372] | 38746 / 123 | +0.308 | NA | NA | rep | 2/7 | T |
| 22 | t_read - lat_ms | -0.305 [-0.407, -0.215] | 38738 / 119 | -0.494 | NA | NA | rep | 5/5 | T |
| 23 | stderr_len - resp_out | -0.293 [-0.452, -0.087] | 4919 / 47 | +0.032 | -0.293 | NA | rep | 1/5 | H |
| 24 | t_mcp - nerr | +0.288 [+0.224, +0.395] | 5698 / 66 | +0.247 | NA | NA | rep | 3/5 | H |
| 25 | t_mcp - gap_prev_ms | -0.276 [-0.364, -0.176] | 38746 / 123 | -0.232 | NA | NA | rep | 1/5 | T |


#### aiv_cc/B session

| # | pair | rho [95% CI] | n / sessions | within-sess | within-tool | partial | A | indep. rep | code |
|---|---|---|---|---|---|---|---|---|---|
| 1 | n_results - n_resp | +0.995 [+0.988, +1.000] | 156 / 156 | NA | NA | +0.773 | rep | 7/7 | Z |
| 2 | n_events - n_resp | +0.989 [+0.985, +0.992] | 156 / 156 | NA | NA | NA | rep | 7/7 | Z |
| 3 | n_calls - n_results | +0.989 [+0.976, +0.997] | 189 / 189 | NA | NA | +0.828 | rep | 9/9 | D |
| 4 | n_calls - n_resp | +0.986 [+0.975, +0.995] | 156 / 156 | NA | NA | +0.690 | rep | 7/7 | Z |
| 5 | n_events - think_sum | +0.985 [+0.979, +0.991] | 154 / 154 | NA | NA | NA | rep | 7/7 | Z |
| 6 | n_calls - n_tools | +0.982 [+0.973, +0.990] | 189 / 189 | NA | NA | +0.813 | rep | 8/9 | Z |
| 7 | n_resp - ctx_sum | +0.980 [+0.974, +0.986] | 156 / 156 | NA | NA | +0.629 | rep | 7/7 | Z |
| 8 | n_events - n_asst | +0.977 [+0.967, +0.984] | 189 / 189 | NA | NA | NA | rep | 9/9 | Z |
| 9 | n_resp - think_sum | +0.976 [+0.967, +0.984] | 154 / 154 | NA | NA | +0.044 | rep | 7/7 | Z |
| 10 | n_results - ctx_sum | +0.974 [+0.964, +0.982] | 156 / 156 | NA | NA | +0.481 | rep | 7/7 | Z |
| 11 | n_events - n_results | +0.973 [+0.966, +0.979] | 189 / 189 | NA | NA | NA | rep | 9/9 | Z |
| 12 | n_results - n_tools | +0.971 [+0.956, +0.984] | 189 / 189 | NA | NA | +0.666 | rep | 8/9 | Z |
| 13 | dur_s - think_sum | +0.970 [+0.954, +0.983] | 154 / 154 | NA | NA | +0.220 | rep | 7/7 | Z |
| 14 | n_results - think_sum | +0.970 [+0.957, +0.980] | 154 / 154 | NA | NA | -0.145 | rep | 7/7 | Z |
| 15 | n_events - ctx_sum | +0.967 [+0.954, +0.977] | 156 / 156 | NA | NA | NA | rep | 7/7 | Z |
| 16 | n_calls - ctx_sum | +0.967 [+0.955, +0.977] | 156 / 156 | NA | NA | +0.441 | rep | 7/7 | Z |
| 17 | ctx_sum - think_sum | +0.966 [+0.949, +0.979] | 154 / 154 | NA | NA | +0.260 | rep | 7/7 | Z |
| 18 | dur_s - n_resp | +0.965 [+0.939, +0.983] | 156 / 156 | NA | NA | +0.095 | rep | 7/7 | Z |
| 19 | n_events - n_calls | +0.964 [+0.953, +0.974] | 189 / 189 | NA | NA | NA | rep | 10/10 | Z |
| 20 | n_calls - think_sum | +0.958 [+0.941, +0.972] | 154 / 154 | NA | NA | -0.038 | rep | 7/7 | Z |
| 21 | n_asst - think_sum | +0.957 [+0.942, +0.969] | 154 / 154 | NA | NA | +0.063 | rep | 7/7 | Z |
| 22 | n_tools - n_resp | +0.955 [+0.936, +0.972] | 156 / 156 | NA | NA | +0.483 | rep | 6/7 | Z |
| 23 | n_asst - n_resp | +0.954 [+0.943, +0.964] | 156 / 156 | NA | NA | -0.042 | rep | 7/7 | Z |
| 24 | n_events - n_tools | +0.947 [+0.932, +0.959] | 189 / 189 | NA | NA | NA | rep | 8/9 | Z |
| 25 | dur_s - ctx_sum | +0.941 [+0.909, +0.965] | 156 / 156 | NA | NA | +0.011 | rep | 7/7 | Z |


#### aiv_cu/B call_pooled

| # | pair | rho [95% CI] | n / sessions | within-sess | within-tool | partial | A | indep. rep | code |
|---|---|---|---|---|---|---|---|---|---|
| 1 | pos_idx - pos_rel | +0.901 [+0.895, +0.908] | 59921 / 1944 | +0.971 | +0.903 | NA | rep | 9/9 | D |
| 2 | t_shell - t_gui | -0.757 [-0.770, -0.744] | 59956 / 1979 | -0.468 | NA | NA | rep | 3/3 | D |
| 3 | t_gui - arg_len | -0.706 [-0.723, -0.689] | 59956 / 1979 | -0.552 | NA | NA | rep | 1/3 | T |
| 4 | pos_idx - resp_ctx | +0.661 [+0.644, +0.678] | 36835 / 1161 | +0.903 | +0.673 | NA | rep | 3/7 | H |
| 5 | t_shell - arg_len | +0.655 [+0.639, +0.670] | 59956 / 1979 | +0.405 | NA | NA | rep | 6/9 | T |
| 6 | t_shell - res_len | +0.641 [+0.621, +0.661] | 28963 / 1746 | +0.455 | NA | NA | rep | 1/9 | T |
| 7 | pos_rel - resp_ctx | +0.608 [+0.590, +0.626] | 36822 / 1148 | +0.881 | +0.615 | NA | rep | 3/7 | H |
| 8 | resp_think - srv_ms | +0.517 [+0.468, +0.557] | 12236 / 347 | +0.626 | +0.518 | NA | rep | 1/1 | P |
| 9 | gap_input_ms - srv_ms | +0.497 [+0.457, +0.533] | 12236 / 347 | +0.475 | +0.525 | NA | rep | 1/1 | P |
| 10 | res_len - same_tool_prev | +0.457 [+0.436, +0.477] | 27849 / 1698 | +0.256 | +0.025 | NA | rep | 3/9 | T |
| 11 | arg_len - resp_out | +0.362 [+0.325, +0.401] | 36835 / 1161 | +0.530 | +0.310 | NA | rep | 5/7 | S |
| 12 | gap_input_ms - resp_out | +0.297 [+0.261, +0.333] | 36800 / 1158 | +0.365 | +0.401 | NA | rep | 5/7 | P |
| 13 | t_shell - resp_out | +0.294 [+0.256, +0.335] | 36835 / 1161 | +0.223 | NA | NA | rep | 1/7 | T |
| 14 | gap_prev_ms - resp_out | -0.272 [-0.316, -0.226] | 36835 / 1161 | -0.183 | -0.291 | NA | rep | 1/7 | H |
| 15 | res_len - resp_out | +0.270 [+0.222, +0.319] | 15236 / 989 | -0.068 | -0.126 | NA | rep | 1/7 | C |
| 16 | gap_prev_ms - resp_ctx | +0.261 [+0.229, +0.290] | 36835 / 1161 | +0.042 | +0.250 | NA | rep | 4/7 | H |
| 17 | t_shell - same_tool_prev | +0.250 [+0.230, +0.271] | 57977 / 1944 | +0.248 | NA | NA | rep | 6/9 | T |
| 18 | stderr_len - arg_len | +0.241 [+0.187, +0.296] | 3768 / 974 | +0.187 | +0.195 | NA | not_rep | 0/6 | U |
| 19 | same_tool_prev - resp_out | +0.239 [+0.209, +0.270] | 35674 / 1148 | -0.031 | +0.184 | NA | not_rep | 1/7 | C |
| 20 | resp_out - srv_ms | +0.226 [+0.171, +0.281] | 12236 / 347 | +0.305 | +0.282 | NA | not_rep | 0/1 | P |
| 21 | gap_input_ms - resp_think | +0.221 [+0.197, +0.247] | 59631 / 1973 | +0.294 | +0.221 | NA | rep | 5/7 | P |
| 22 | res_len - arg_len | +0.220 [+0.187, +0.254] | 28963 / 1746 | -0.041 | -0.102 | NA | rep | 1/9 | C |
| 23 | t_shell - gap_input_ms | -0.212 [-0.237, -0.183] | 59631 / 1973 | -0.034 | NA | NA | rep | 1/7 | T |
| 24 | t_gui - gap_input_ms | +0.202 [+0.176, +0.225] | 59631 / 1973 | +0.052 | NA | NA | rep | 3/3 | T |
| 25 | pos_idx - srv_ms | +0.192 [+0.151, +0.233] | 12236 / 347 | +0.243 | +0.193 | NA | rep | 1/1 | P |


#### aiv_cu/B session

| # | pair | rho [95% CI] | n / sessions | within-sess | within-tool | partial | A | indep. rep | code |
|---|---|---|---|---|---|---|---|---|---|
| 1 | n_calls - n_results | +1.000 [+1.000, +1.000] | 2000 / 2000 | NA | NA | +1.000 | rep | 9/9 | D |
| 2 | n_calls - n_resp | +0.968 [+0.952, +0.981] | 1162 / 1162 | NA | NA | +0.911 | rep | 7/7 | Z |
| 3 | n_results - n_resp | +0.968 [+0.952, +0.981] | 1162 / 1162 | NA | NA | +0.911 | rep | 7/7 | Z |
| 4 | ctx_max - ctx_sum | +0.914 [+0.895, +0.931] | 1162 / 1162 | NA | NA | +0.920 | rep | 7/7 | Z |
| 5 | n_events - n_calls | +0.819 [+0.805, +0.831] | 2000 / 2000 | NA | NA | NA | rep | 9/9 | Z |
| 6 | n_events - n_results | +0.819 [+0.805, +0.831] | 2000 / 2000 | NA | NA | NA | rep | 9/9 | Z |
| 7 | n_events - n_resp | +0.794 [+0.769, +0.816] | 1162 / 1162 | NA | NA | NA | rep | 7/7 | Z |
| 8 | n_events - n_asst | +0.739 [+0.720, +0.757] | 2000 / 2000 | NA | NA | NA | rep | 9/9 | Z |
| 9 | shell_share - arg_len_med | +0.713 [+0.692, +0.734] | 1979 / 1979 | NA | NA | +0.709 | rep | 7/9 | T |
| 10 | n_calls - ctx_sum | +0.670 [+0.635, +0.703] | 1162 / 1162 | NA | NA | +0.552 | rep | 7/7 | Z |
| 11 | n_results - ctx_sum | +0.670 [+0.635, +0.703] | 1162 / 1162 | NA | NA | +0.552 | rep | 7/7 | Z |
| 12 | shell_share - res_len_med | +0.664 [+0.634, +0.693] | 1746 / 1746 | NA | NA | +0.662 | rep | 3/9 | T |
| 13 | n_resp - ctx_sum | +0.661 [+0.625, +0.695] | 1162 / 1162 | NA | NA | +0.527 | rep | 7/7 | Z |
| 14 | dur_s - ctx_sum | +0.627 [+0.586, +0.667] | 1162 / 1162 | NA | NA | +0.503 | rep | 7/7 | Z |
| 15 | dur_s - ctx_max | +0.588 [+0.546, +0.632] | 1162 / 1162 | NA | NA | +0.531 | rep | 7/7 | Z |
| 16 | n_calls - dur_s | +0.575 [+0.543, +0.607] | 2000 / 2000 | NA | NA | +0.290 | rep | 7/7 | Z |
| 17 | n_results - dur_s | +0.575 [+0.543, +0.607] | 2000 / 2000 | NA | NA | +0.290 | rep | 7/7 | Z |
| 18 | dur_s - gap_input_med | +0.559 [+0.523, +0.595] | 1973 / 1973 | NA | NA | +0.617 | rep | 5/7 | S |
| 19 | dur_s - tok_out | +0.549 [+0.506, +0.592] | 1162 / 1162 | NA | NA | +0.418 | rep | 7/7 | Z |
| 20 | dur_s - n_resp | +0.544 [+0.499, +0.589] | 1162 / 1162 | NA | NA | +0.244 | rep | 7/7 | Z |
| 21 | n_events - dur_s | +0.530 [+0.497, +0.564] | 2000 / 2000 | NA | NA | NA | rep | 7/7 | Z |
| 22 | res_len_med - arg_len_med | +0.489 [+0.455, +0.523] | 1746 / 1746 | NA | NA | +0.486 | rep | 1/9 | T |
| 23 | n_calls - ctx_max | +0.480 [+0.429, +0.529] | 1162 / 1162 | NA | NA | +0.428 | rep | 7/7 | Z |
| 24 | n_results - ctx_max | +0.480 [+0.429, +0.529] | 1162 / 1162 | NA | NA | +0.428 | rep | 7/7 | Z |
| 25 | ctx_sum - think_sum | +0.478 [+0.435, +0.523] | 1162 / 1162 | NA | NA | +0.384 | rep | 7/7 | Z |


#### whowhen/B call_pooled

| # | pair | rho [95% CI] | n / sessions | within-sess | within-tool | partial | A | indep. rep | code |
|---|---|---|---|---|---|---|---|---|---|
| 1 | t_shell - t_web | -0.857 [-0.919, -0.786] | 595 / 97 | -0.313 | NA | NA | rep | 3/7 | D |
| 2 | t_subagent - same_tool_prev | -0.603 [-0.717, -0.489] | 498 / 83 | -0.604 | NA | NA | rep | 1/4 | T |
| 3 | pos_idx - pos_rel | +0.595 [+0.554, +0.645] | 581 / 83 | +0.867 | +0.711 | NA | rep | 9/9 | D |
| 4 | t_shell - prev_err | +0.545 [+0.467, +0.622] | 462 / 80 | +0.000 | NA | NA | rep | 1/7 | H |
| 5 | t_shell - pos_idx | -0.536 [-0.611, -0.443] | 595 / 97 | +0.108 | NA | NA | rep | 1/9 | T |
| 6 | t_shell - err | +0.515 [+0.447, +0.582] | 535 / 95 | +0.000 | NA | NA | rep | 2/7 | H |
| 7 | t_web - res_len | +0.495 [+0.374, +0.612] | 535 / 95 | +0.337 | NA | NA | rep | 1/7 | T |
| 8 | t_shell - arg_len | +0.458 [+0.333, +0.571] | 595 / 97 | -0.029 | NA | NA | rep | 6/9 | T |
| 9 | t_web - prev_err | -0.455 [-0.543, -0.371] | 462 / 80 | +0.000 | NA | NA | rep | 1/7 | H |
| 10 | t_web - err | -0.437 [-0.506, -0.369] | 535 / 95 | +0.000 | NA | NA | rep | 1/7 | H |
| 11 | t_web - pos_idx | +0.428 [+0.297, +0.537] | 595 / 97 | -0.199 | NA | NA | rep | 1/7 | T |
| 12 | t_shell - res_len | -0.424 [-0.542, -0.283] | 535 / 95 | -0.182 | NA | NA | rep | 5/9 | T |
| 13 | t_web - arg_len | -0.405 [-0.532, -0.264] | 595 / 97 | -0.006 | NA | NA | rep | 2/7 | T |
| 14 | err - pos_idx | -0.350 [-0.400, -0.296] | 535 / 95 | -0.079 | -0.058 | NA | rep | 2/7 | C |
| 15 | prev_err - pos_idx | -0.346 [-0.403, -0.283] | 462 / 80 | -0.052 | -0.048 | NA | rep | 2/7 | C |
| 16 | res_len - arg_len | -0.331 [-0.442, -0.203] | 535 / 95 | +0.016 | -0.174 | NA | rep | 6/9 | C |
| 17 | arg_len - prev_err | +0.275 [+0.157, +0.385] | 462 / 80 | +0.044 | +0.015 | NA | rep | 1/7 | C |
| 18 | arg_len - err | +0.255 [+0.145, +0.358] | 535 / 95 | -0.023 | -0.033 | NA | rep | 1/7 | C |
| 19 | t_read - t_web | -0.251 [-0.348, -0.132] | 595 / 97 | -0.531 | NA | NA | rep | 1/7 | D |
| 20 | t_web - same_tool_prev | +0.249 [+0.148, +0.337] | 498 / 83 | +0.619 | NA | NA | rep | 1/7 | T |
| 21 | err - prev_err | +0.247 [+0.072, +0.398] | 420 / 78 | -0.457 | -0.042 | NA | rep | 6/7 | S |
| 22 | arg_len - pos_idx | -0.243 [-0.388, -0.100] | 595 / 97 | +0.084 | +0.049 | NA | not_rep | 2/9 | C |
| 23 | t_web - t_subagent | -0.227 [-0.310, -0.149] | 595 / 97 | -0.668 | NA | NA | rep | 1/4 | D |
| 24 | t_read - same_tool_prev | -0.216 [-0.409, -0.093] | 498 / 83 | -0.148 | NA | NA | rep | 5/7 | T |
| 25 | t_read - res_len | -0.162 [-0.269, +0.006] | 535 / 95 | -0.213 | NA | NA | rep | 3/7 | T |


#### whowhen/B session

| # | pair | rho [95% CI] | n / sessions | within-sess | within-tool | partial | A | indep. rep | code |
|---|---|---|---|---|---|---|---|---|---|
| 1 | err_rate - nerr_rate | +1.000 [+1.000, +1.000] | 65 / 65 | NA | NA | +1.000 | rep | 7/7 | D |
| 2 | n_user - shell_share | -0.993 [-1.000, -0.985] | 97 / 97 | NA | NA | -0.979 | rep | 1/5 | H |
| 3 | n_calls - n_results | +0.958 [+0.931, +0.980] | 111 / 111 | NA | NA | +0.649 | rep | 9/9 | D |
| 4 | n_events - n_calls | +0.950 [+0.930, +0.967] | 111 / 111 | NA | NA | NA | rep | 10/10 | Z |
| 5 | n_events - n_results | +0.931 [+0.900, +0.955] | 111 / 111 | NA | NA | NA | rep | 9/9 | Z |
| 6 | n_events - shell_share | -0.813 [-0.857, -0.762] | 97 / 97 | NA | NA | NA | rep | 4/10 | H |
| 7 | n_asst - shell_share | -0.802 [-0.855, -0.746] | 97 / 97 | NA | NA | -0.488 | rep | 3/9 | H |
| 8 | n_events - n_user | +0.793 [+0.736, +0.844] | 111 / 111 | NA | NA | NA | rep | 5/5 | Z |
| 9 | n_user - n_asst | +0.780 [+0.714, +0.840] | 111 / 111 | NA | NA | +0.488 | rep | 5/5 | Z |
| 10 | n_calls - n_tools | +0.726 [+0.634, +0.803] | 111 / 111 | NA | NA | +0.249 | rep | 8/9 | Z |
| 11 | n_events - n_asst | +0.725 [+0.628, +0.809] | 111 / 111 | NA | NA | NA | rep | 9/9 | Z |
| 12 | n_calls - n_user | +0.721 [+0.641, +0.792] | 111 / 111 | NA | NA | -0.169 | rep | 5/5 | Z |
| 13 | n_results - n_user | +0.721 [+0.637, +0.797] | 111 / 111 | NA | NA | -0.079 | rep | 5/5 | Z |
| 14 | n_calls - shell_share | -0.720 [-0.794, -0.635] | 97 / 97 | NA | NA | +0.261 | rep | 3/10 | H |
| 15 | n_results - shell_share | -0.719 [-0.801, -0.620] | 97 / 97 | NA | NA | +0.116 | rep | 3/9 | H |
| 16 | n_events - n_tools | +0.707 [+0.615, +0.785] | 111 / 111 | NA | NA | NA | rep | 8/9 | Z |
| 17 | n_results - n_tools | +0.706 [+0.603, +0.789] | 111 / 111 | NA | NA | +0.188 | rep | 8/9 | Z |
| 18 | n_tools - shell_share | -0.624 [-0.758, -0.482] | 97 / 97 | NA | NA | -0.315 | rep | 4/9 | H |
| 19 | n_user - n_tools | +0.623 [+0.517, +0.713] | 111 / 111 | NA | NA | +0.145 | rep | 5/5 | Z |
| 20 | n_user - err_rate | -0.605 [-0.717, -0.514] | 95 / 95 | NA | NA | -0.512 | rep | 2/5 | H |
| 21 | err_rate - shell_share | +0.600 [+0.510, +0.711] | 95 / 95 | NA | NA | +0.498 | rep | 4/7 | H |
| 22 | n_user - arg_len_med | -0.577 [-0.701, -0.447] | 97 / 97 | NA | NA | -0.390 | rep | 1/5 | H |
| 23 | shell_share - arg_len_med | +0.567 [+0.437, +0.691] | 97 / 97 | NA | NA | +0.370 | rep | 7/9 | H |
| 24 | n_calls - n_asst | +0.559 [+0.421, +0.684] | 111 / 111 | NA | NA | -0.598 | rep | 9/9 | Z |
| 25 | n_asst - arg_len_med | -0.537 [-0.675, -0.399] | 97 / 97 | NA | NA | -0.323 | rep | 1/9 | H |

What the ten lists contain:
- **Call level:**
  - **swechat:** mostly mechanical. The non-mechanical entries are two U and one B, plus one H+B.
    - U: hdur_ms-gap_prev_ms, gap_input_ms-resp_ncalls.
    - B: hdur_ms-resp_out.
    - H+B: gap_input_ms-sub.
  - **cc_local:**
    - U: hdur_ms-pos_rel, hdur_ms-resp_think.
    - B: pos_idx-sub, resp_ctx-resp_ncalls, gap_input_ms-sub, arg_len-resp_ncalls.
  - **aiv_cc:**
    - U: lat_ms-stderr_len, lat_ms-res_len.
    - B: lat_ms-nerr.
  - **aiv_cu:** one U, stderr_len-arg_len.
  - **whowhen:** no B or U entry.
- **Session level:** every raw top-25 list contains only D, Z, H or T/S rows. No corpus has a non-mechanical pair among
  its 25 strongest session correlations. Session size and its components dominate.

### A3. Residual views and cross-corpus replication of the non-mechanical pairs

Source: `replication.<u>.{call_within_excl, call_within_tool_excl, session_partial_excl}`, plus the B/U rows of A2.
Only pairs whose discovery CI excludes 0 with |rho| >= 0.1 are listed. "stat" is the statistic of the list named.

**Replicate in at least one other corpus (not only in the corpus's own A split):**

| pair (discovery unit, statistic) | rho [CI] | A | indep. rep | code / note |
|---|---|---|---|---|
| nerr - prev_err (swechat, within-tool) | +0.224 [+0.200, +0.250] | rep | 5/5 (aiv_cc B+A, cc_local B+A, swechat A) | B: error clustering (F5) |
| err - prev_err (swechat, within-tool) | +0.202 [+0.178, +0.229] | rep | 4/7 | B: error clustering (F5) |
| lat_ms - gap_input_ms (swechat, within-tool) | +0.197 [+0.171, +0.223] | rep | 5/5 (aiv_cc B+A, cc_local B+A, swechat A) | **U** |
| lat_ms - gap_input_ms (aiv_cc, within-tool) | +0.194 [+0.142, +0.253] | rep | 5/5 | **U** (same pair) |
| lat_med - gap_input_med (swechat, partial) | +0.356 [+0.318, +0.395] | rep | 3/5 (aiv_cc B+A, swechat A) | U: session mirror of the row above |
| res_len - err (aiv_cc, within-tool) | -0.268 [-0.375, -0.154] | rep | 3/7 (aiv_cc A, cc_local B, swechat B) | B: failures return shorter output |
| lat_ms - err (aiv_cc, within-tool) | -0.315 [-0.448, -0.166] | rep | 3/5 (aiv_cc A, cc_local B+A) | B: failures return faster |
| lat_ms - nerr (aiv_cc, pooled) | -0.366 [-0.533, -0.213] | rep | 3/5 | B: as above (within-tool -0.095) |
| gap_input_ms - sub (cc_local, pooled) | -0.370 [-0.587, -0.286] | rep | 3/3 (cc_local A, swechat B+A) | B: subagent turns faster (F6, F7) |
| resp_ctx - resp_ncalls (cc_local, pooled) | -0.422 [-0.527, -0.335] | rep | 3/6 (cc_local A, swechat B+A) | B: fan-out happens in small contexts |
| arg_len - resp_ncalls (cc_local, pooled) | -0.368 [-0.517, -0.290] | rep | 3/6; opposite in aiv_cc B+A, aiv_cu B | B: parallel calls carry short args |
| gap_input_ms - resp_ncalls (swechat, pooled) | -0.484 [-0.502, -0.467] | rep | 3/6 (cc_local B+A, swechat A) | **U** (see B5) |
| hdur_ms - res_len (cc_local, within-session) | +0.347 [+0.289, +0.415] | rep | 2/3 (cc_local A, swechat B) | B: more output, longer run |
| same_tool_prev - resp_ncalls (swechat, within-tool) | +0.241 [+0.232, +0.251] | rep | 2/7; opposite in aiv_cc B+A | B: parallel calls are mostly one tool |
| arg_len_med - calls_per_resp (cc_local, partial) | -0.711 [-0.787, -0.622] | rep | 3/6 (cc_local A, swechat B+A); opposite in aiv_cu B | B: fan-out sessions |
| n_user - calls_per_resp (cc_local, partial) | -0.539 [-0.625, -0.437] | rep | 3/3 | B: interactive sessions fan out less |
| n_user - lat_med (cc_local, partial) | +0.546 [+0.408, +0.660] | rep | 2/3 | B: interactive vs autonomous sessions |
| n_user - shell_share (cc_local, partial) | +0.657 [+0.534, +0.772] | rep | 2/5; opposite in whowhen B+A | B: same |
| think_sum - shell_share (cc_local, partial) | -0.569 [-0.701, -0.421] | rep | 2/7 | B: same |
| n_calls - res_len_med (aiv_cc, partial) | -0.503 [-0.599, -0.371] | rep | 3/9; opposite in swechat B+A | B: call-heavy sessions, shorter results |
| res_len - pos_idx (aiv_cc, within-tool) | -0.165 [-0.241, -0.093] | rep | 4/9 (whowhen B+A, aiv_cc A, aiv_cu A) | U: results shorten later in a session |
| res_len - same_tool_prev (whowhen, within-session) | +0.182 [+0.066, +0.283] | rep | 4/9 | U (within-tool +0.011, so it is tool runs) |
| arg_len - resp_ctx (aiv_cu, within-tool) | +0.151 [+0.123, +0.179] | not_rep | 2/7 (cc_local B, swechat B) | U |
| err - pos_rel (whowhen, within-session) | -0.172 [-0.281, -0.059] | rep | 2/7 (whowhen A, cc_local A) | U |

**Replicate only in the corpus's own A split, or have the opposite sign elsewhere:**

| pair (discovery unit, statistic) | rho [CI] | A | indep. rep | note |
|---|---|---|---|---|
| lat_ms - stderr_len (aiv_cc, pooled = within-tool) | -0.504 [-0.561, -0.399] | rep | 1/4; opposite in swechat B and A | U, corpus-specific |
| lat_ms - res_len (aiv_cc, pooled) | +0.319 [+0.178, +0.470] | rep | 2/5; opposite in swechat A | U, sign differs by harness (within-tool swechat/B +0.084 in `all_pairs`) |
| hdur_ms - pos_idx, hdur_ms - resp_ctx, hdur_ms - arg_len (cc_local, within-session) | -0.442, -0.431, -0.320 | rep | 1/3 each; opposite in swechat B and A | U, cc_local-specific |
| hdur_ms - pos_rel, hdur_ms - resp_think (cc_local, pooled) | -0.392, -0.389 | rep | 1/3 | U |
| hdur_ms - pos_idx (swechat, within-tool) | +0.307 [+0.154, +0.387] | not_rep | 0/3; opposite in cc_local B and A | U, non-replicating |
| resp_out - resp_ctx (swechat, within-tool) | +0.229 [+0.194, +0.262] | rep | 1/7; opposite in aiv_cc B, aiv_cu B and A | U |
| res_len - resp_think, res_len - gap_input_ms, resp_ctx - resp_think (aiv_cc, within-tool) | +0.241, +0.229, -0.223 | rep | 1/7 each | U, aiv_cc only |
| lat_ms - arg_len (cc_local, within-tool) | +0.421 [+0.284, +0.446] | rep | 1/5 | U |
| res_len - arg_len (cc_local, within-tool) | -0.302 [-0.324, -0.192] | not_rep | 2/9; opposite in aiv_cc B, swechat A | U, sign varies |
| stderr_len - arg_len (aiv_cu, pooled) | +0.241 [+0.187, +0.296] | not_rep | 0/6 | U |
| n_compact - sub_share (cc_local, partial) | +0.695 [+0.395, +1.000] | na | 0/2; opposite in swechat B | rests on 8 compaction records (`units.cc_local/B.compaction_records`) |
| n_calls - whowhen_mistake_rel, n_results - whowhen_mistake_rel (whowhen, partial) | -0.380 [-0.530, -0.218], -0.343 [-0.506, -0.161] | not_rep | 0/1 | the only label correlations; absent in whowhen/A |

### A4. Post-hoc follow-ups (`units.<u>.post_hoc_followups`)

**F1. native_error coverage by tool**

Share of results with a non-null native_error:

| unit | shell results | non-shell results |
|---|---|---|
| swechat/B:claude_code | 0.9995 [0.9989, 1.0] (61,037/61,066) | 0.030 [0.028, 0.033] (4,058/133,301); all 4,058 true, 0 false |
| cc_local | 1.0 (26,873/26,873) | 0.036 [0.024, 0.045] (349/9,669); 286 true, 63 false |
| aiv_cc | 0.659 [0.522, 0.779] (5,197/7,884) | 0.016 [0.006, 0.029] (501/30,854); all 501 true |
| swechat/B:opencode | 1.0 | 1.0 |
| swechat/B:codex | 0.594 [0.445, 0.702] | 0.675 [0.499, 0.799] |
| aiv_cu | 0 | 0 |

**F2. Placeholder usage**

Share of calls whose issuing response has usage_out <= 10:

| unit | share |
|---|---|
| swechat CC, subagent calls | 0.782 [0.762, 0.802] (44,545/56,998) |
| swechat CC, main calls | 0.174 [0.154, 0.194] |
| aiv_cc | 0.865 [0.750, 0.949] (33,508/38,746) |
| cc_local, subagent calls | 0.242 [0.021, 0.419] |
| cc_local, main calls | 0.0 (0/7,512) |
| aiv_cu | 0.024 [0.014, 0.035] |
| OpenCode | 0.0 |

The cc_local subagent figure covers 29,030 calls that sit in only 6 sessions, out of 36,542 calls in all.

**F3. Calls with gap_prev_ms == 0**

| unit | share |
|---|---|
| aiv_cu | 0.572 [0.549, 0.592] (34,203/59,835) |
| swechat | 0.012 |
| cc_local | 0.002 |
| aiv_cc | 0.0 |

**F4. Block streaming clock**

These are calls whose previous event (seq-1) belongs to the same API response. Share of all calls that qualify:
swechat CC 0.399, cc_local 0.309, aiv_cc 0.961.

| unit | n / sessions | rho [CI] | within-tool rho [CI] | median arg chars per second of gap [CI] |
|---|---|---|---|---|
| swechat CC | 77,161 / 1,648 | 0.815 [0.801, 0.828] | 0.579 [0.555, 0.602] | 174.7 [171.0, 178.3] |
| cc_local | 11,239 / 141 | 0.919 [0.878, 0.948] | 0.863 [0.707, 0.899] | 197.2 [174.6, 287.1] |
| aiv_cc | 37,231 / 123 | 0.815 [0.757, 0.855] | 0.709 [0.600, 0.783] | 101.7 [85.1, 128.5] |

Where the previous event belongs to a different response, the same rho is 0.462 (swechat CC), 0.357 (cc_local) and
0.409 (aiv_cc). For aiv_cu, where a turn row is the unit, it is -0.058 [-0.090, -0.024], within-tool 0.219.

**F5. Lag-1 error autocorrelation**

Observed within-session rho on calls with a non-null err, against 20 within-session permutations:

| unit | observed within-session rho [CI] | permutation null: mean (min to max) |
|---|---|---|
| swechat | 0.184 [0.160, 0.209] | -0.008 (-0.012 to -0.004) |
| swechat CC | 0.197 | -0.009 |
| cc_local | 0.129 [0.091, 0.297] | -0.014 |
| aiv_cc | 0.052 [0.004, 0.126] | -0.003 (-0.018 to 0.011) |
| codex | 0.056 [0.032, 0.076] | -0.007 |
| opencode | 0.044 [-0.001, 0.131] | -0.017 |
| whowhen | -0.483 [-0.633, -0.314] | -0.376 (-0.516 to -0.024) |

Pooled, swechat is 0.206 against a pooled null of 0.020.

**F6. Model family of subagent and main calls**
- swechat CC: subagent calls are Haiku 0.410 [0.366, 0.461] (23,381/56,998); main calls 0.005 [0.003, 0.010].
- cc_local: no Haiku in either group. The 29,030 subagent calls are opus 25,239, sonnet 1,011, other 2,780.
- OpenCode in swechat/B: 4,176 subagent calls in 176 sessions, against 4,023 main calls in 37 sessions.

**F7. gap_input within the call's own stream** (stream = is_subagent + parent_call_id)
- Negative gap_input among swechat CC subagent calls: 0.213 (12,128/56,998) across streams, 0.0008 (43/56,998) within
  the own stream. Main calls: 0.0005.
- OpenCode has negative gaps even within one stream: subagent 0.426, main 0.123. This is the documented parallel-call
  ordering, where the next call's start precedes the previous result's end.
- cc_local, aiv_cc, aiv_cu and Codex have no negative gaps.
- Stream-aware gap_input vs sub: swechat CC -0.385 [-0.411, -0.358] (raw -0.539); cc_local -0.394 [-0.606, -0.324].
- Stream-aware gap_input vs lat_ms, within-tool: swechat CC 0.234 [0.213, 0.253]; cc_local 0.214 [0.128, 0.251];
  aiv_cc 0.194 [0.142, 0.253]; opencode -0.027 [-0.089, 0.021]; codex -0.024 [-0.108, 0.174].

### A5. Other structure the scan surfaced

**aiv_cu population** (`units.aiv_cu/population`, 78,114 sessions)
- n_turns: p50 41, p95 42, max 326.
- shell_share vs n_synthetic: -0.442 [-0.449, -0.436]; partial on size -0.440.
- n_calls vs talk_share: -0.364 [-0.369, -0.359].

**Context growth with position (`pos_idx|resp_ctx`) is not universal** (`all_pairs`):

| unit | rho |
|---|---|
| aiv_cu | 0.661 |
| opencode | 0.878 |
| swechat | 0.490 |
| aiv_cc | 0.035 [0.012, 0.054] |
| cc_local | 0.151 [-0.134, 0.494] |

aiv_cc has 508 compact_boundary records in B (`units.aiv_cc/B.compaction_records`).

**Turnaround vs output volume differs by corpus.** gap_input_ms vs resp_out, within-tool:

| unit | rho [CI] |
|---|---|
| swechat | 0.356 [0.324, 0.389] |
| cc_local | 0.209 [0.163, 0.339] |
| aiv_cu | 0.401 [0.368, 0.434] |
| aiv_cc | 0.006 [-0.038, 0.059] |

In aiv_cc, resp_think carries the signal instead: gap_input_ms vs resp_think, within-tool 0.551 [0.498, 0.604].

**Two clocks per tool** (`lat_ms|hdur_ms`): swechat/B:claude_code 0.985 [0.979, 0.990], cc_local 0.946
[0.929, 0.958], swechat/B:codex 0.444 [0.229, 0.795].

**Features that are constant or missing** (`units.<u>.<level>.dropped`):
- aiv_cu: `err` is constant (the IR has no failure signal there) and `lat_ms` is undefined (shared_turn).
- cc_local: `stderr_len` is constant.
- Codex: `resp_*` are absent (token_count rows are not linked to calls).
- whowhen: `whowhen_is_correct` is constant in B, so no label-outcome correlation can be computed.

### A6. Nulls (same prominence as the hits)

- No session-level pair outside the mechanical families reaches any corpus's raw top 25.
- No whowhen call-level pair outside the mechanical codes survives. The negative within-session error autocorrelation
  (-0.483) lies inside its permutation null (F5). The two label correlations do not hold in whowhen/A.
- These do not replicate in any other corpus: aiv_cc lat_ms-stderr_len and lat_ms-res_len, every cc_local hdur_ms
  residual, and aiv_cu stderr_len-arg_len (A3, second table).
- Context growth with position is absent in aiv_cc and inside noise in cc_local (A5).
- gap_input_ms is flat against resp_out in aiv_cc (A5), because usage_out there is a placeholder (F2).

---------------------------------------------------------------------------------------------------------------------

## Part B. Interpretation (mine, not data)

**B1. Almost everything strong is mechanical.**
- In every corpus, the session-level top 25 is the size family: longer sessions have more of everything. Partialling out
  size leaves compositional pairs (parts of a fixed total turn negative) and tool-mix pairs.
- At the call level, the strongest pairs are tool composition, two clocks of one duration, and context growth.
- None of this is evidence about honesty. It is the baseline any multivariate "anomaly" screen would have to beat. A
  detector built on raw feature correlations would mostly be rediscovering session length and tool mix.

**B2. Harness facts that other lenses must respect** (all measured here):
1. *native_error is tool-conditional in Claude Code logs* (F1).
   - `is_error` is written for essentially every Bash result, and for other tools only when true.
   - So "null" means "unknown or success", and any error rate built on native_error measures shell share.
   - This alone produces nerr_rate-shell_share -0.897 in cc_local.
   - OpenCode records it for every result; aiv_cu never does.
2. *usage_out is a placeholder in two places* (F2):
   - aiv_cc rows (0.865 at or below 10 tokens).
   - The nested `agent_progress` copies of subagent messages in swechat (0.782, against 0.174 for main calls).
   - Per-response output tokens there are unusable. resp_out-sub -0.580 is an artifact of this.
3. *gap_input is contaminated by stream interleaving* (F7).
   - In swechat, 0.213 of subagent calls see a later-stamped input from another stream.
   - In OpenCode, parallel-call ordering gives negative gaps even within one stream.
   - Any timing check over swechat must order within streams. Recomputed that way, subagent turns are still faster
     (-0.385, and -0.394 in cc_local, which is time-sorted and has no negatives).
   - So the effect is real but was inflated.
4. *aiv_cu's shared turn stamp* makes gap_prev 0 for 0.572 of calls (F3). Only turn-level gaps exist there.
5. *cc_local's call level is six sessions.* 29,030 of 36,542 calls are workflow subagent calls in 6 sessions, which is
   why cc_local CIs are wide and some cc_local-only pairs (the hdur_ms residuals) do not travel.
6. *aiv_cu sessions are capped near 41-42 turns* (population p50 41, p95 42). Harness-bootstrap synthetic turns go with
   GUI sessions (shell_share-n_synthetic -0.442). Both are harness structure, not agent behavior.

**B3. The physics-based couplings are the strongest witness-free regularities, and they replicate.**
- *Block streaming clock* (F4). When a tool_use block's predecessor is a block of the same API response, the timestamp
  gap tracks the block's argument length.
  - rho 0.815 / 0.919 / 0.815 in swechat CC / cc_local / aiv_cc.
  - Within tool 0.579 / 0.863 / 0.709.
  - Rates 175 / 197 / 102 chars per second.
  - This holds in three independent Claude-Code-family corpora and their A splits.
  - It is the call-level analogue of the block-gap result in `aiv_accounting`.
- *Generation and prefill time.*
  - gap_input tracks output tokens (swechat 0.356 within tool), thinking chars (aiv_cc 0.551) and context size.
  - Gemini's server timing tracks reasoning chars (0.517).
- *Two clocks per tool.* The timestamp latency matches the harness's own duration (0.985 swechat CC, 0.946 cc_local).
  Codex is the exception (0.444), where unified-exec deferral separates them.

These are "mechanical" in the task's sense. They are also exactly the constraints a fabricated or edited log would have
to satisfy jointly, which makes them more useful than the unexplained pairs.

**B4. Non-mechanical pairs that replicate across corpora.**
- *Error clustering.*
  - Within-tool lag-1 error correlation is 0.202 to 0.224 in swechat and replicates in aiv_cc and cc_local (B and A).
  - Within-session values sit far above a within-session permutation null (0.184 vs -0.008 in swechat; 0.129 vs
    -0.014 in cc_local).
  - The effect is weaker in OpenCode/Codex (0.044 / 0.056) and absent in Who&When.
  - Plausible cause, untested: retry loops after a failure.
- *Turnaround couples to tool latency.*
  - A slow model turn predicts a slow tool call within the same tool. Within-tool: 0.197 swechat, 0.194 aiv_cc, 0.183
    cc_local in `all_pairs`; 0.214 to 0.234 stream-aware (F7).
  - Replicates 5/5 from both discovery units, plus the session-level mirror lat_med-gap_input_med.
  - It is absent in OpenCode and Codex.
  - I have no mechanism. Candidates I did not test: shared host or network slowness, permission-prompt waits, or
    time-of-day load. **This is the main unexplained replicating pair.**
- *Failures are short and fast.* Within tool, res_len-err is -0.268 (aiv_cc), -0.101 (swechat) and -0.126 (cc_local),
  and lat_ms-err is -0.315 (aiv_cc). Plausible and unsurprising.
- *Fan-out structure (CC family only).*
  - Responses that issue several calls have smaller context, shorter args and much shorter turnaround (-0.484 swechat,
    -0.270 cc_local).
  - Thinking is not lower in fan-out responses: resp_think-resp_ncalls is +0.045 swechat and +0.321 cc_local in
    `all_pairs`. So "less thinking" does not explain the faster turnaround. I code it U.
  - aiv_cc and aiv_cu show none of this.
- *Session type.* In cc_local, given size, human-prompt-heavy sessions are shell-heavy, slower per tool, fan out less
  and think less. Each replicates in at most cc_local/A plus swechat. This is a plausible interactive-vs-autonomous
  split, not tested.

**B5. Non-mechanical pairs that do not travel.**
- aiv_cc's lat_ms-stderr_len (-0.504) and lat_ms-res_len (+0.319) flip sign in swechat. cc_local's within-session
  hdur_ms residuals flip sign in swechat. aiv_cu's stderr_len-arg_len holds nowhere else.
- I read these as harness- or tool-mix-specific, not as general regularities. Any check built on them would be
  corpus-specific.
- The Who&When label correlation (mistake position earlier in call-heavy sessions, given size) fails its own held-out
  split, so it is a null.

## Candidate mechanisms (each grounded in a measurement above; novelty UNVERIFIED for all)

1. **Block streaming clock as a content-length witness.** For a tool_use block that follows another block of the same
   response, the timestamp gap divided by the args length should match the session's own streaming rate (median 175 /
   197 / 102 chars/s per harness, F4). A rewritten command or argument of different length breaks the rate.
   - False-positive sources:
     - The rate differs by model and harness (102 vs 175).
     - Only 0.31-0.40 of CC calls have a same-response predecessor (0.96 in aiv_cc).
     - The within-tool rho is lower (0.58 in swechat).
     - aiv_cu, OpenCode and Codex lack the block structure.
     - Stalls and retries inflate gaps.
   - UNVERIFIED novelty; `aiv_accounting` reported the block-level version for aiv_cc.
2. **Turnaround vs generated volume.** gap_input must be at least what the logged output, thinking and context imply
   (F4 rates; A5 within-tool rho 0.356 / 0.551; srv_ms vs reasoning 0.517).
   - False positives: placeholder usage (F2), cross-stream ordering (F7), Haiku subagents (F6), and permission or human
     waits that only lengthen gaps.
   - Usable as a one-sided bound, not as an equality. UNVERIFIED.
3. **Error-burst statistic.** Honest CC-family logs show within-session lag-1 error autocorrelation of 0.05-0.20 above
   a permutation null of about 0 (F5). A log whose errors are injected independently, or scrubbed, would sit at the
   null. It is a session-level test that needs many calls, and the effect is small in OpenCode/Codex. UNVERIFIED.
4. **Turnaround-latency coupling** (within-tool 0.18-0.23 in three CC-family corpora, F7). A log assembled from
   independently drawn latencies would lack it. The mechanism is unknown, so the false-positive structure is unknown.
   The weakest of the four. UNVERIFIED.

## Could not measure

- Tool latency in aiv_cu (shared_turn stamp) and anything timed in Who&When (no timestamps).
- Per-call usage for Codex: token_count rows are not linked to calls in the IR.
- True per-response output tokens in aiv_cc and in swechat's nested subagent copies (placeholders, F2).
- Who&When outcome labels: `is_correct` is constant in the B sample.
- Model or harness version as a stratifier beyond the F6 family substring, and non-monotone relations. Spearman only.
- Whether any pair would separate fabricated from honest logs. There is no fabricated ground truth in these corpora.
  Everything above is the honest baseline only.
