# Phase C lens: sequences (structural regularities in tool-call order)

- Script: `analysis/probes/phase_c_sequences.py`. Run: `PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_c_sequences`
  (single process; `meta.seconds_total` gives the runtime). Four reruns reproduced the pre-registered sections exactly.
- Data: `analysis/out/phase_c/sequences.json` (raw counts only). Paths below are relative to its root. `G` stands for `groups`.
- Input: the Phase B IR caches of all five corpora. Sessions in split / sessions with at least one call
  (`integrity.<corpus>.all`): swechat 2000/1951, cc_local 186/174, aiv_cc 189/123, aiv_cu 2000/1979, whowhen 111/97.
- Pre-registration lives in `meta.prereg`: windows, the similarity threshold, failure markers, regexes and the rule thresholds.
  Revisions with before/after/reason are in `meta.revisions`. I debugged the code on the A split, and two definitions changed
  there before any B outcome existed: the shell parser, and the retry signature. The A-split control showed `near` = 0.27,
  driven by shared JSON key names and path prefixes. One pre-registered quantity, R1 `session_strict`, was implemented after
  run 1 exactly as written.
- Everything under a key containing `posthoc` was added after I read the first B output (`meta.posthoc_additions`). Treat
  those as hypotheses that need a holdout.
- Rate format: `rate [95% CI] num/den`. CIs are session-clustered bootstraps (`stats.cluster_rate`). Differences use a joint
  session bootstrap. Groups with fewer than 30 sessions in a denominator get counts only (`insufficient_n`).
- Privacy (cc_local): tool names are folded and mcp tools collapse to `mcp`. Shell words outside a public allowlist become
  `other`. No paths, args, commands or ids are written.

---------------------------------------------------------------------------------------------------------------------

## Part 1: Measurements

### 1.0 Pairing and order integrity: parser surprises first (`integrity`)
- **Results written before their call.** swechat has 57 results that sit before their own tool_use in file order
  (`integrity.swechat.all.results_before_their_call_detail`, post hoc):
  - All 57 are Claude Code main-stream calls, in 27 sessions.
  - In 57/57 the result timestamp is still at or after the call timestamp: median +17 ms, max +292 ms.
  - The seq gap has median 1 and max 1406. By tool: edit 29, read 12, write 9.
  - So file order is not causal order. Any sequence check has to pair by call_id and timestamps, not by line order.
- **Calls without a result:**
  - claude_code: 285, 0.00146 [0.001, 0.002]. Top tools: shell 143, subagent 59.
  - codex: 74, of which 73 are websearch (server-side, never answered in the transcript).
  - cursor: 164/164, because the format has no results.
  - opencode: 4. cc_local, aiv_cu: 0. aiv_cc: 8.
  - whowhen: Algorithm-Generated (AG) 31 (unexecuted code blocks), Hand-Crafted (HC) 29, of which websurfer is 26.
  - (`integrity.<corpus>.by_group.<g>`)
- Failure classes for claude_code: ok 186226, fail 7449, reject 692, none 285. Markers: cc_exit_code 3225,
  cc_tool_use_error 2470, cc_interrupt_reject 662, cc_permission_denied 30.
- cc_local main: 296 rejects in 7512 calls, 292 of them permission denials.
- **cc_local concentration.** 6 sessions hold the 675 subagent streams, with 29,030 of the 36,542 calls
  (`G.cc_local.sub.ngrams`, `G.cc_local.all.ngrams`). Pooled cc_local rates mostly describe those 6 workflow-heavy sessions,
  so I report `main` separately.
- aiv_cc: of 189 runs in the split, only 123 have any call (see the header line).
- aiv_cu: stderr is present on many calls without a failure marker (git and curl progress). Failure markers come from
  `AIVCU_FAIL_RX` (`meta.aivcu_fail_rx`).

### 1.1 Tool n-grams (`G.<corpus>.<group>.ngrams`)
| group | sessions | calls | self-loop share | H(next\|cur) bits [CI] | unigram H | identical consecutive call |
|---|---|---|---|---|---|---|
| swechat claude_code | 1651 | 194,652 | 0.566 [0.557, 0.575] | 1.969 [1.933, 1.993] | 2.807 | 0.0045 [0.0032, 0.0059] 853/190,806 |
| claude_code/main | 1651 | 137,654 | 0.538 [0.529, 0.548] | 2.043 [2.005, 2.067] | 2.868 | 0.005 [0.003, 0.006] |
| claude_code/sub | 648 | 56,998 | 0.635 [0.623, 0.648] | 1.583 [1.535, 1.620] | 2.350 | 0.004 [0.002, 0.006] |
| swechat codex | 63 | 9,801 | 0.703 [0.665, 0.786] | 1.244 [0.926, 1.416] | 1.850 | 0.065 [0.007, 0.099] |
| swechat opencode | 213 | 8,199 | 0.611 [0.571, 0.662] | 1.594 [1.411, 1.683] | 2.177 | 0.004 [0.002, 0.006] |
| cc_local main | 174 | 7,512 | 0.618 [0.585, 0.656] | 1.599 [1.429, 1.698] | 2.303 | 0.002 [0.000, 0.004] |
| aiv_cc | 123 | 38,746 | 0.499 [0.400, 0.589] | 1.632 [1.386, 1.802] | 2.460 | **0.248 [0.155, 0.332]** 9572/38,623 |
| aiv_cu | 1979 | 59,956 | 0.523 [0.509, 0.539] | 1.829 [1.769, 1.8735] | 2.833 | 0.069 [0.062, 0.076] |
| whowhen HC | 33 | 415 | 0.872 [0.811, 0.919] | 0.523 [0.351, 0.692] | 0.733 | 0.037 [0.022, 0.051] |

- Claude Code unigram shares: shell 0.314, read 0.284, edit 0.148, grep 0.097. Subagent streams are read-heavy: read 0.428.
  OpenCode subagents: read 0.616, edit 9 calls in 4176.
- The top bigrams in every coding scaffold are self-loops. Claude Code: shell→shell 42,278, read→read 29,661, edit→edit 15,340.
  The first cross-tool bigram is read→edit (8,810).
- Codex: shell 0.653 plus write_stdin polls 0.175. A same-tool run of 10 or more occurs in 0.825 [0.730, 0.905] of its streams;
  for Claude Code the figure is 0.299 [0.282, 0.318].
- First call of a main stream:
  - claude_code: read 0.320 [0.296, 0.341], shell 0.216, subagent 0.158 (n 1651).
  - cc_local main: shell 166/174, 0.954 [0.920, 0.983].
  - aiv_cc: `mcp__village__get_events` 100/123, 0.813 [0.740, 0.878].
  - aiv_cu: shell 0.441 [0.419, 0.462].
- aiv_cc is a polling loop. get_events makes up 0.471 of calls, and get_events→get_events accounts for 13,526 bigrams.
- whowhen AG has a single token (code_exec), so its n-grams are degenerate.

### 1.2 Shell commands (`G.<corpus>.<group>.shell`)
| group | shell calls | cd-prefixed | multi-segment |
|---|---|---|---|
| claude_code | 61,209 | 0.072 [0.057, 0.089] | 0.560 [0.544, 0.576] |
| codex | 6,400 | 0.0045 [0.000, 0.0085] 29/6400 | 0.353 [0.311, 0.433] |
| opencode | 1,862 | 0.0005 [0.000, 0.002] 1/1862 | 0.113 [0.062, 0.158] |
| cc_local all / main | 26,873 / 4,309 | 0.516 [0.297, 0.592] / 0.227 [0.099, 0.386] | 0.836 / 0.743 |
| aiv_cc | 7,885 | 0.459 [0.251, 0.628] | 0.747 [0.608, 0.859] |
| aiv_cu | 24,604 | 0.418 [0.393, 0.443] | 0.744 [0.724, 0.765] |

- Lead words differ by scaffold:
  - Claude Code: grep 4950, ls 4059, git add 3436, git diff 3064, find 2935, git log 2745.
  - Codex: sed 0.238 [0.119, 0.313] of commands, rg 774, nl 306.
  - aiv_cc: gh pr 2417, curl 1186.
  - aiv_cu: cat 3214, python 2360, echo 1857.
- Codex commands include PowerShell. get-content is a lead word 253 times in 7/59 sessions, and get-content → select-object
  occurs 71 times as a segment bigram.
- Segment bigrams:
  - Claude Code: grep→head 5081. git add→git commit 2616 (share 0.041 [0.034, 0.048], in 702/1415 sessions).
  - aiv_cu: git add→git commit 1751, and git commit→git push 1284 (356/1168 sessions).
- Parse limits: shell control words show up as segment words, for example OpenCode `[`→`break` and `fi`→`sleep`, 12 each.
  aiv_cu has 0.965 [0.959, 0.971] of shell calls parsed. I did not investigate the rest.

### 1.3 Retry shapes (`G.<corpus>.<group>.retry`; K = 3 calls after the failed result, near = similarity ≥ 0.8)
| group | fail anchors | retry after fail | retry after ok (control) | lift fail − ok [CI] | exact after fail / after ok |
|---|---|---|---|---|---|
| claude_code | 7449 | 0.348 [0.330, 0.366] | 0.142 [0.137, 0.148] | **0.203 [0.184, 0.222]** (1135 s) | 0.131 [0.118, 0.143] / 0.008 [0.006, 0.009] |
| claude_code/main | 5173 | 0.385 [0.366, 0.406] | 0.139 [0.134, 0.144] | 0.243 [0.224, 0.263] | 0.151 / 0.009 |
| claude_code/sub | 2276 | 0.263 [0.228, 0.298] | 0.150 [0.138, 0.162] | 0.106 [0.072, 0.140] | 0.085 / 0.005 |
| opencode | 307 | 0.466 [0.344, 0.550] | 0.127 [0.113, 0.140] | **0.348 [0.233, 0.424]** (77 s) | 0.290 [0.134, 0.406] / 0.008 |
| cc_local all | 1104 | 0.223 [0.195, 0.283] | 0.110 [0.101, 0.140] | 0.121 [0.097, 0.205] (30 s) | exact lift 0.034 [−0.005, 0.061] |
| aiv_cc | 779 | 0.388 [0.281, 0.463] | 0.442 [0.340, 0.526] | **−0.041 [−0.172, 0.075]** | 0.273 / **0.391 [0.282, 0.482]** |
| aiv_cu | 1054 | 0.230 [0.192, 0.270] | 0.303 [0.291, 0.314] | **0.021 [−0.019, 0.064]** (500 s) | exact lift −0.006 [−0.036, 0.031] |
| whowhen AG | 54 | 0.222 [0.120, 0.327] | 0.263 [0.148, 0.377] | 0.073 [−0.063, 0.212] (31 s) | 0/54 / 1/95 |

- Claude Code, what happens next:
  - The retry succeeds in 0.769 [0.738, 0.796] (1992/2590) and fails again in 0.226.
  - There are 6552 failure loops: length 1 = 6138, 2 = 333, 3 = 53, 4 = 18, 5 = 7, 6 or more = 3. Loops of 3 or more make up
    0.012 [0.009, 0.015].
  - Exact retry by tool:
    - edit 0.250 [0.211, 0.294] (221/885)
    - shell 0.151 [0.130, 0.172]
    - read 0.063 [0.048, 0.079]
    - subagent 0/77, even though subagent retry (near) is 0.571.
- **Post hoc, the read-gate path** (`G.swechat.claude_code.retry.posthoc_edit_read_gate`): 372 of the 885 failed edits are
  "not read" refusals.
  - They are retried in 0.551 [0.485, 0.619], against 0.435 [0.384, 0.491] for other edit failures.
  - Among those retries, a read of the same path sits between failure and retry in **197/205 = 0.961 [0.917, 0.995]**.
    For other edit failures it is 0.668 [0.599, 0.739].
- Below the 30-session minimum, counts only:
  - Gemini: exact retry 82/253 failure anchors (13 sessions); the retry fails again in 62/105.
  - Codex: 99/449 (18 sessions).
- aiv_cu harness specifics (`G.aiv_cu.all.aiv_cu_specific`):
  - After "coordinates unavailable", get_pixel_coords is called again in 0.477 [0.391, 0.555] (62/130).
  - After a bash timeout ("must be restarted"), the next call is a restart in 0.174 [0.108, 0.250] (61/351).
  - By stratum: openai-responses 0/137 (70 sessions); anthropic-opus 28/29 (13 sessions, counts only).

### 1.4 Always / never regularities (`G.<corpus>.<group>.regularities`, `.rules`)
**R1 read before edit** (same path, same stream):
- Claude Code strict: 0.960 [0.955, 0.966] 27,665/28,808 (1434 sessions).
  - session_strict 0.962 [0.956, 0.968]
  - strict or written 0.985 [0.982, 0.987]
  - broad (basename seen earlier) 0.996 [0.995, 0.997]
- "Not read" refusal: 0.213 [0.175, 0.257] (244/1143) without a prior same-path read, against 0.005 [0.003, 0.006]
  (128/27,665) with one. Edit failure: 0.241 vs 0.022.
- OpenCode strict: 0.815 [0.709, 0.908] (772/947, 36 sessions), with 0 refusals.
- Counts only:
  - Codex: strict 0/722; it has no read tool and reads via shell. Broad 704/722.
  - cc_local: strict 231/1457, session_strict 602/1457, written 1049/1457, broad 1456/1457. 0 refusals in the 1226 edits
    without a prior read (12 sessions).
  - aiv_cc: 325/345.

**Mined precedence rules** (pre-registered thresholds `meta.prereg.rules_mining`; conditional version post hoc). Rules that
hold when both tools are in the stream:
- Claude Code (`G.swechat.claude_code.rules.posthoc_conditional_rules`):
  - read always precedes edit 0.999 [0.998, 0.999] 28,768/28,802
  - read precedes write 0.980 [0.968, 0.989]
  - taskcreate precedes taskupdate 0.996 [0.989, 1.000]
  - toolsearch precedes taskcreate 0.983, taskupdate 0.985, todo 0.972 and webfetch 0.981
  - shell follows edit 0.977 [0.971, 0.982]
- OpenCode: read always precedes edit 947/947, 1.000.
- cc_local main: toolsearch always precedes mcp 0.989 [0.961, 0.997] (550/556, 41 sessions).
- aiv_cu: get_pixel_coords precedes left_click 0.981 [0.971, 0.988].
- aiv_cc: 55 conditional "always" rules. For example, start_computer_session precedes gui (unconditional 0.996), and
  get_pixel_coordinates is bracketed by gui and read 362/362.

**Mutually exclusive tool generations.** Of 4749 Claude Code taskupdate calls, 27 are in streams that also contain a todo
call. Of 1310 todo calls, 2 are in streams with taskupdate or taskcreate
(`rules.rules[].posthoc_x_calls_in_streams_with_y`).

**R2 explore before the first file access:**
- Claude Code: 0.366 [0.347, 0.386] of 3634 streams. Main 0.295 [0.271, 0.318], sub 0.421 [0.388, 0.457].
- Before the first deep call: 0.432 [0.407, 0.456].
- The very first call is a file call in 0.435 [0.410, 0.459].
- OpenCode 0.690 [0.629, 0.752], aiv_cc 0.234 [0.128, 0.362], cc_local main 0.284 [0.207, 0.371].

**R3 verification after mutation** (Claude Code, 2060 mutation streams):
- test after the first mutation 0.336 [0.305, 0.366]
- **test after the last mutation 0.216 [0.190, 0.244]**
- test or build/lint after the last mutation 0.363 [0.330, 0.395]
- the last test failed, given a test after the last mutation: 0.038 [0.017, 0.065] (17/446)
- test within 10 calls of a mutation: 0.196 [0.174, 0.220]
- test calls that fail: 0.120 [0.098, 0.141] (541/4527)
- Subagents: verify after the last mutation 0.430 [0.342, 0.515].
- OpenCode: test after the last mutation 0.132 [0.026, 0.237] (38 streams). Its test calls fail 0.493 [0.412, 0.627]
  (66/134).

**R4 git commit:**
- Claude Code (3487 commit calls, 953 sessions):
  - status or diff since the previous commit 0.514 [0.481, 0.545]
  - add or -a 0.959 [0.950, 0.967]
  - log/show within 5 calls after 0.172 [0.148, 0.195]
  - push later 0.618 [0.570, 0.669]; main 0.677 [0.630, 0.720], sub 0.041 [0.000, 0.119]
  - commit failed 0.077 [0.062, 0.093]
- aiv_cu (1836 commits, 559 sessions):
  - status or diff 0.267 [0.235, 0.302]
  - add 0.990 [0.983, 0.995]
  - **push later 0.971 [0.956, 0.983]**
  - failed 0.032 [0.018, 0.048]
- aiv_cc: status or diff 64/279, push 275/279 (23 sessions).

**R5 re-read after edit within 5 calls:** Claude Code 0.213 [0.201, 0.225].

### 1.5 aiv_cu by model (`G.aiv_cu["model:<m>"]`)
24 models have at least 30 B sessions. 18 do not and are listed in `aiv_cu_models.models_insufficient_n`.

Values below are rounded to 2 decimals from the JSON:
- shell share of calls
- click preceded by get_pixel_coords
- identical consecutive call share
- self-loop share
- H(next|cur)
- fail-marker share
- status/diff before commit, where at least 30 sessions have commits

| model | s | shell | pix→click | identical | self-loop | H | fail | status/diff before commit |
|---|---|---|---|---|---|---|---|---|
| claude-3-7-sonnet | 54 | 0.08 | 0.00 | 0.08 | 0.48 | 1.74 | 0.01 | n/a |
| claude-haiku-4-5 | 118 | 0.17 | 0.00 | 0.20 [0.15, 0.25] | 0.48 | 1.77 | 0.01 | n/a |
| claude-opus-4-5 | 113 | 0.23 | 0.00 | 0.21 [0.16, 0.26] | 0.52 | 1.64 | 0.01 | n/a |
| claude-sonnet-4-5 | 99 | 0.20 | 0.00 | 0.16 | 0.43 | 2.04 | 0.00 | n/a |
| claude-opus-4-6 | 41 | 0.91 [0.86, 0.95] | n/a | 0.01 | 0.85 | 0.58 | 0.01 | n/a |
| claude-opus-4-7 / 4-8 | 40 / 43 | 0.70 / 0.75 | n/a | 0.07 / 0.02 | 0.76 / 0.67 | 0.98 / 1.13 | 0.02 / 0.01 | – / 0.01 [0.00, 0.03] |
| claude-sonnet-4-6 / 5 | 63 / 51 | 0.71 / 0.67 | n/a | 0.03 / 0.06 | 0.72 / 0.71 | 1.01 / 1.07 | 0.01 / 0.00 | n/a |
| deepseek-reasoner | 117 | 0.81 | n/a | 0.00 | 0.73 | 0.88 | 0.03 | 0.31 [0.21, 0.44] |
| deepseek-v4-pro | 35 | 0.92 | n/a | 0.01 | 0.88 | 0.50 | 0.03 | 0.04 [0.01, 0.09] |
| gemini-2.5-pro | 195 | 0.28 | **0.89 [0.86, 0.92]** | 0.09 | 0.39 | 1.55 | 0.01 | n/a |
| gemini-3.1-pro / 3.5-flash | 89 / 82 | 0.36 / 0.29 | 0.82 / 0.90 | 0.06 / 0.04 | 0.44 / 0.35 | 1.56 / 1.69 | 0.02 / 0.01 | n/a |
| gpt-5 / 5.1 | 86 / 137 | 0.11 / 0.39 | 0.08 / 0.02 | 0.02 / 0.07 | 0.38 / 0.61 | 2.14 / 1.58 | 0.04 / 0.02 | n/a |
| gpt-5.2 | 92 | 0.38 | 0.91 [0.79, 0.99] | 0.01 | 0.41 | 1.63 | 0.03 | 0.36 [0.23, 0.52] |
| gpt-5.4 | 83 | 0.49 | 0.00 | 0.04 | 0.50 | 1.76 | 0.02 | 0.59 [0.41, 0.77] |
| gpt-5.5 / kimi-k2.6 / glm-5.2 | 34 / 39 / 43 | 0.76 / 0.57 / 0.90 | n/a | 0.03 / 0.08 / 0.01 | 0.72 / 0.68 / 0.83 | 1.02 / 1.10 / 0.56 | 0.02 / 0.02 / 0.02 | n/a |
| o3 | 78 | 0.03 | 0.92 [0.90, 0.95] | 0.01 | 0.15 [0.13, 0.19] | 2.03 | 0.04 | n/a |
| claude-code::opus-4-5 / fable-5 | 35 / 36 | 0.26 / 0.45 | n/a | 0.10 / 0.06 | 0.40 / 0.47 | 1.81 / 1.85 | 0.01 / 0.00 | n/a |

Notes on the table:
- "n/a" in pix→click means fewer than 30 sessions with a click. In the commit column it means fewer than 30 sessions with a
  commit.
- Period confound (post hoc, `aiv_cu_models.posthoc_session_month_range_per_model`):
  - opus-4-5 spans 2025-12 to 2026-09 (median 2026-05).
  - opus-4-6 spans 2026-02 to 2026-08 (median 2026-04).
  - sonnet-4-5 median 2026-03; sonnet-4-6 median 2026-06.
  - o3 spans 2025-04 to 2025-11.

### 1.6 whowhen (`whowhen`, `G.whowhen.*`)
- Algorithm-Generated: code-exec failure rate per call 0.300 [0.232, 0.369] (54/180).
- Exact retry after a failed exec: **0/54**. Agents always change the code. Near retry is 0.222 [0.120, 0.327].
- The labelled mistake_step falls on a failed exec call or result step in 21/41 = 0.512 [0.365, 0.657] of sessions that have
  a failure. The uniform-step null expects 11.429 such hits.
- Mistake step relative to the first failure: before 7, at 19, after 15.
- Hand-Crafted has no failure signal: 0 'fail' among 415 calls. Its retry and co-location measures are therefore empty.

### Nulls (same weight as hits)
1. **No retry lift in the AI Village corpora or Who&When AG.**
   - aiv_cu −0.006 (exact) and 0.021 (exact or near), both CIs spanning 0, over 500 sessions.
   - aiv_cc −0.041 [−0.172, 0.075].
   - whowhen AG 0.073 [−0.063, 0.212].
   - The baselines are high: aiv_cc repeats an identical call after a success 0.391 of the time, and aiv_cu repeats 0.303.
2. **No ordering prohibition survives conditioning.** Of the unconditional "never" rules, the second tool is absent from
   more than half of the X-call streams in 30/30 for Claude Code, 95/96 for Claude Code subagents, 56/56 for aiv_cu, 32/32
   for OpenCode and 23/25 for cc_local (`rules.posthoc_n_never_rules`, `posthoc_n_never_rules_y_absent_in_majority`). The
   conditional version yields 0 "never" rules in every group (`rules.posthoc_n_conditional_never_rules`). Every "never" rule is a rarity
   artifact, except the todo/task disjointness, which is about co-occurrence rather than order.
3. Identical consecutive calls are rare in coding scaffolds: Claude Code 0.0045, OpenCode 0.004.
4. Test runs after the last mutation are not a regularity: 0.216 for Claude Code, 0.132 for OpenCode.
5. git status/diff before commit is not an "always": 0.514 for Claude Code, 0.267 for aiv_cu. Only git add is (0.959 / 0.990).
6. Codex, Gemini, Cursor, cc_local subagents and most cc_local edit and commit measures fall below 30 sessions.

---------------------------------------------------------------------------------------------------------------------

## Part 2: Interpretation (mine, not data)

1. **The strongest regularities are harness-enforced, and they form a checkable grammar.**
   - Claude Code refuses an Edit on an unread path, and the logs show it:
     - 0.999 of edits have an earlier Read in the same stream.
     - When the same-path read is missing, 0.213 of edits are refused with a "not read" text, against 0.005 when it is present.
     - A refusal is followed, almost always, by Read(path) then the same edit (197/205).
   - The same holds for TaskCreate before TaskUpdate (0.996) and ToolSearch before deferred tools (0.97–0.99).
   - These rules come from the harness, not the model, so a log produced without the harness has to reproduce them by hand.
   - The rules are scaffold- and version-specific:
     - Codex has no read tool.
     - OpenCode enforces read-before-edit without refusals (947/947).
     - Current Claude Code in cc_local shows strict same-path reads in only 231/1457 edits with 0 refusals. That suggests
       the gate's semantics changed (12 sessions only, counts).
2. **Tool vocabularies fingerprint the harness version and the agent configuration.**
   - TodoWrite and TaskCreate/TaskUpdate almost never share a stream (27/4749 and 2/1310).
   - In aiv_cu, clicking via get_pixel_coords is around 0 for every Claude model and 0.82–0.92 for Gemini, gpt-5.2 and o3.
     That looks like which tools each agent was given rather than model preference. I did not verify the tool lists.
   - A log whose vocabulary or grammar does not match its claimed harness or model would stand out. The confounds are
     model = agent = period: AI Village gives each model its own persona, memory and tasks, and periods only partly overlap
     (opus-4-5 vs opus-4-6 overlap but differ 0.23 vs 0.91 in shell share).
3. **Failure markers leave a local sequence signature in coding agents and none in polling or computer-use agents.**
   - In Claude Code and OpenCode, an exact re-issue of the same call is rare after a success (0.008) and common after a failure
     (0.131 / 0.290).
   - So an exact repeat that follows an "ok" result is a cheap anomaly flag. It could be a result whose real outcome differed,
     or a flaky tool.
   - It only works with corpus-specific baselines. aiv_cc and aiv_cu repeat identical calls routinely (polling, scrolling),
     and there the lift is zero.
4. **What agents do NOT do is as informative as the rules.**
   - Only 0.216 of Claude Code mutation streams run a test after the last mutation (0.363 including build/lint).
   - So any end-of-session "tests pass" claim is unbacked by a test call after the final change in most mutation streams.
     This is a base rate for a claims-vs-actions check. The claims themselves were not measured here.
   - When a final test does run, it almost never fails (0.038). A claim of success after a failing last test would be rare
     in honest logs.
5. **File order is not event order** (57 results before their call, timestamps consistent). Some formats also never record
   results: Cursor, Codex web search. Sequence checks need call_id pairing and timestamp order, plus a whitelist of tools
   with no result.
6. **Who&When.** Failed code executions co-locate with annotated mistakes more often than uniform placement predicts
   (21 observed vs 11.429 expected). That is a sequence-position prior for blame, not a detector: only 21 of the 41
   annotated mistakes in sessions with a failure sit on a failure step.

## Candidate mechanisms (novelty UNVERIFIED for all)
1. **Harness-gate grammar check.** Verify the harness-enforced orderings: Read→Edit (with refusal→Read→retry),
   TaskCreate→TaskUpdate, ToolSearch→deferred tool.
   - Measured honest conformance: 28,768/28,802 edits have an earlier read when both tools are in the stream.
   - False positives: same-path strictness (1143/28,808 edits without a same-path read, which context from resumed or compacted
     history may explain), and version drift (cc_local).
2. **Version and configuration fingerprint from tool vocabulary.** Mutually exclusive tool generations; per-agent tool usage
   (get_pixel_coords).
   - False positives: mixed-version streams (27/4749) and resumed sessions across upgrades.
3. **Outcome-conditioned repetition test.** Compare exact-repeat rates after ok vs fail results with the corpus baseline
   (0.008 vs 0.131 in Claude Code).
   - False positives: polling and GUI corpora (aiv_cc exact-after-ok 0.391), flaky tools.
4. **Unverified-completion base rate.** Mutation streams with no test or build after the last mutation (the complement of
   verify-after-last-mutation = 0.363 for Claude Code) give the prior for a claims-vs-log check.
   - False positives: tasks that need no tests; verification done by hooks outside the log.

## Could not measure
- Fabrication ground truth. None of these corpora labels fabricated calls. Who&When labels mistakes, not fabrications.
- aiv_cu failures beyond the stderr regex. There is no native failure flag, so 'reject' does not exist there.
- Whether the openai-responses tool schema offers a bash restart action. That determines whether 0/137 timeout→restart
  reflects behaviour or schema.
- Why cc_local's strict read-before-edit is low without refusals. 12 sessions, and Claude Code version was not joined.
- Model vs agent vs task confounds in aiv_cu. Each model is roughly one agent with its own memory and goals.
- Cursor retry and verification (no results); Who&When HC retry (no failure flags); Codex and Gemini rates (under 30 sessions).
- The shell parser is naive: no subshells, control words become segment words, and aiv_cu parses only 0.965 of shell calls.
- Claims in assistant text were not linked to sequences; that belongs to a separate lens.
