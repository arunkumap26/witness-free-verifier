# Phase A, A2: join completeness (call <-> result)

Script `analysis/probes/phase_a_a2.py`; numbers in `analysis/out/phase_a/a2.json`. Data: split A caches only (swechat 200
sessions, cc_local 123, aiv_cc 125 runs, aiv_cu 200, whowhen 73). Join key = (session_id, call_id) within a session.
Rates are `stats.cluster_rate` (session bootstrap, 95%), written as num/den = rate [lo, hi], n = sessions with a nonzero
denominator. A zero count gives a degenerate bootstrap CI [0, 0]. For those cases the informative bound is the Wilson
interval on the share of sessions affected (`sessions_affected` in the JSON).

Verdict rule (`prereg.verdict_rule`): a slice is usable if all four rates have hi <= 0.01, absent if it has calls but no
results, and partial otherwise. A second verdict drops calls whose reason is structural (the source never records a
result for them). The 0.01 cut was set after I had already looked at the swechat-A unpaired counts during schema
exploration. It is a round number and I did not change it afterwards. This disclosure is in the JSON.

## Answer

**In the raw IR, the joins are nearly complete for every format that records results. The SWE-chat table is not.**
Orphan results: 3 in 21,025 swechat results, and 0 in each of the other corpora. No call key has more than one result in
any corpus. There is 1 duplicate call key, and the release caused it: two Gemini ids redacted to the literal `REDACTED`.
Every gap that matters is structural and confined to whole formats or sessions. Losses inside sessions are rare per call,
but common per session.

| slice (all) | orphan results | calls without result | same, excl. structural | dup keys | verdict / excl. structural |
|---|---|---|---|---|---|
| swechat, all formats | 3/21025 = 0.0001 [0.0000, 0.0003] | 727/21749 = 0.0334 [0.0015, 0.0858], n=182 | 32/21054 = 0.0015 [0.0008, 0.0023] | 1/21748 | partial / usable |
| swechat claude_code | 3/13592 = 0.0002 [0.0000, 0.0005] | 31/13620 = 0.0023 [0.0013, 0.0036], n=127 | 30/13619 = 0.0022 [0.0012, 0.0036] | 0 | usable / usable |
| swechat codex | 0/1120 | 2/1122 = 0.0018 [0.0000, 0.0045], n=15 | 1/1121 = 0.0009 [0.0000, 0.0035] | 0 | usable / usable |
| swechat opencode | 0/3735 | 0/3735, n=25 | 0/3735 | 0 | usable / usable |
| swechat gemini | 0/2313 | 487/2800 = 0.1739 [0.0000, 0.5509], n=11 | 0/2313 | 1/2799 | partial / usable |
| swechat copilot | 0/265 | 1/266 = 0.0038 [0.0000, 0.0082], n=2 | 1/266 | 0 | usable / usable |
| swechat cursor | no results | 206/206 = 1.0, n=2 | n/a | 0 | **absent** / absent |
| swechat simple_text | no calls | | | | no_tool_calls |
| cc_local | 0/5164 | 1/5165 = 0.0002 [0.0000, 0.0010], n=107 | 1/5165 | 0 | usable / usable |
| aiv_cc | 0/33475 | 4/33479 = 0.0001 [0.0000, 0.0003], n=78 | 3/33478 = 0.0001 [0.0000, 0.0002] | 0 | usable / usable |
| aiv_cu | 0/6107 | 0/6107, n=199 | 0/6107 | 0 | usable (by construction, see below) |
| whowhen | 0/353 | 20/373 = 0.0536 [0.0299, 0.0822], n=63 | 8/361 = 0.0222 [0.0074, 0.0348] | 0 | **partial** / partial |

Calls with more than one result: 0 in every row above (Wilson upper bound on sessions affected, for example swechat
0/182 [0.000, 0.021] and aiv_cu 0/199 [0.000, 0.019]).

### Split by is_subagent
- swechat, is_subagent=False: calls without result 725/17325 = 0.0418 [0.0017, 0.1079], n=161. Excluding structural:
  30/16630 = 0.0018 [0.0009, 0.0029]. Orphans 3/16603.
- swechat, is_subagent=True: calls without result 2/4424 = 0.0005 [0.0000, 0.0011], n=73. Orphans 0/4422.
  - By format: claude_code nested 2/3912 = 0.0005 [0.0000, 0.0013], n=52; codex sub-agent sessions 0/179, n=7;
    opencode child sessions 0/333, n=14.
  - Subagent calls pair at least as well as main-stream calls. No paired call/result differs in is_subagent
    (0 of 21,022 pairs).
- cc_local: is_subagent=True 0/2325, n=4 sessions; is_subagent=False 1/2840 = 0.0004 [0.0000, 0.0013], n=107.
- aiv_cc, aiv_cu, whowhen: no subagent events, so the True slice has n = 0.

### Why calls lack results (first-match rules in `prereg.unpaired_call_reason_rules`)

**Structural** (the source has no result by construction):
- **cursor**: no tool results in the format. 206 calls in 2 sessions (sizes 62 and 144).
- **one gemini session**: `d8bda4a8-…`, 487 calls, 0 results. It is the bare `{"messages": [...]}` export variant: its
  toolCalls carry id/name/args/status but no result (I checked one raw file during exploration; that check has no counts).
  The 486 distinct unpaired keys equal the full-population gemini `calls_without_result` = 486. That fits the format's
  population share of 0.0926 coming from this one session, but I did not verify it.
- **Codex**: 1 server-side `web_search_call`.
- **whowhen AG**: 12 code blocks the harness never ran (`extra.unexecuted`), in 9 sessions.

**Losses** in swechat claude_code (31):

| reason | calls | sessions |
|---|---|---|
| stream_end | 13 | 11 |
| compaction_before_next_result (compact_boundary) | 7 | 6 |
| session_start_hook_before_next_result (restart/resume) | 6 | 3 |
| other | 4 | 1 |
| session_has_no_results (a 1-call session) | 1 | 1 |

Of these, 7 are Task/Agent calls, and 4 of those 7 have nested subagent events: the subagent ran, but the parent's
tool_result is missing.

**Other loss counts:**
- cc_local: 1 (stream_end).
- aiv_cc: 4. Three are stream_end; one is a 1-call run whose next row is an `error_during_execution` result.
- codex: 1 (stream_end).
- copilot: 1 (stream_end).
- whowhen HC: 8 `superseded_by_later_call` in 6 sessions (the orchestrator issued a new instruction before the agent
  answered).

Under the pre-declared rule, the 1-call sessions in swechat claude_code and aiv_cc count as `session_has_no_results`, and
therefore as structural. Counting them as losses instead changes no verdict: 31/13620 hi 0.0036 and 4/33479 hi 0.0003.

**Per-session prevalence** of at least one unpaired call (Wilson):
- swechat claude_code: 20/127 [0.104, 0.231]
- aiv_cc: 4/78 [0.020, 0.125]
- cc_local: 1/107 [0.002, 0.051]
- whowhen: 15/63 [0.150, 0.356]

**Orphan results** (swechat claude_code, 3):
- 2 sit before any call or assistant event in their session. Both carry the `cc_interrupt_reject` marker: a resumed
  session file opens by rejecting a call that lives in the previous file.
- 1 is `other`: a result whose call is not in the session or anywhere else in split A.

### Join-quality side counts
- **Ordering:** 0 paired results precede their call in seq, in every corpus.
- **Call ids are not unique across sessions**, so the join key must include session_id:

  | corpus | ids in more than one session | detail |
  |---|---|---|
  | swechat | 204 (27 sessions) | 198 are loader synthetic ids, which are per-format-seq, not global |
  | aiv_cu | 50 provider ids (4 sessions) | |
  | whowhen | 63 `step:N` ids | |
  | cc_local, aiv_cc | 0 | |

- **Id provenance:**
  - aiv_cu: 1,036 of 6,107 calls have the loader fallback `turn:<row>` id (no provider call id).
  - swechat opencode: 1,026 of 3,735 calls have synthetic ids (the release redacted callIDs).
  - swechat cursor: 206 synthetic ids.
  - swechat gemini: 2 literal `REDACTED` ids. The loader kept these. They form the one duplicate key, which is harmless
    only because their session has no results.
- **aiv_cu pairing is constructed, not observed.** The loader emits a result for every executed call from the same row,
  so 0 defects there say nothing about the source.
  - The row holds the result content: 3,393/6,107 = 0.5556 [0.5020, 0.6102] of aiv_cu results have null or empty text
    (174/199 sessions).
  - The model also issued provider calls that the harness never executed and that have no IR call event:
    4 / (6,107 + 4) = 0.0007 [0.0000, 0.0016], in 3 sessions (gemini-pro 3, anthropic-haiku 1). This matches the build
    report's split-A count of 4.
- **Result text null or empty elsewhere:**

  | slice | null/empty | rate |
  |---|---|---|
  | swechat (all) | 429/21025 | 0.0204 [0.0149, 0.0261] |
  | swechat claude_code | 317/13592 | 0.0233 |
  | swechat opencode | 111/3735 | 0.0297 |
  | cc_local | 54/5164 | 0.0105 [0.0068, 0.0184] |
  | aiv_cc | 218/33475 | 0.0065 [0.0021, 0.0116] |
  | codex | 0 | |
  | whowhen | 0 | |

- **Meta events linked by parent_call_id (progress timers, end records)**, swechat main stream:
  - 18,204 of 20,008 resolve to a call in the same session.
  - Every tool-attached type resolves: bash_progress 6,033, hook PostToolUse 7,769, hook PreToolUse 3,182,
    codex exec_command_end 681, mcp_progress 36.
  - The 1,804 unresolved are Stop hooks (1,189) and SessionStart hooks (613), which are not tool-attached, plus 1
    web_search_end and 1 PostToolUse.
  - Subagent-slice meta links (codex 129, opencode 240) point to spawn calls in other sessions.
  - cc_local: 1,897 subagent meta links, all resolved.
- **Session-level subagent parents (codex, opencode)** mostly cannot be resolved inside split A:
  - codex: 5 parent ids, 0 found in split A; 4 of 9 subagent sessions have no parent id at all.
  - opencode: 9 parent ids, 3 found in another A session; 5 of 14 subagent sessions have no parent id.
  - claude_code nested: 163/163 resolve in-session. cc_local: 13/13 resolve in-session.
- **Consistency:** this script's split-A counts equal the build reports' split-A pairing counts for cc_local, aiv_cc and
  aiv_cu (`consistency_with_build_reports_split_A`).

## Raw transcripts vs the conversations table (cited, not recomputed)

**Table orphans** (`cited.swechat_table_recon_pinned`, `derived_from_cited`):
- `conversations.parquet` has 76,618 orphaned results among 408,086 distinct tool_result ids: 0.1877 of results, a census
  of the whole table.
- It holds 349,729 distinct tool_use ids, and only 331,468 calls with a result.
- It keeps subagent traffic only inside progress metadata rows: 172,814 hidden tool_use ids, of which 172,769 are paired.
  None of the 76,618 orphans matches a hidden tool_use (0).

**The orphans are table artifacts** (`cited.swechat_table_orphans_in_raw_check`):
- In a seeded check of 50 of the 4,386 table sessions with orphans, all 1,367 orphan ids checked were found as top-level
  assistant tool_use ids in the pinned raw transcripts (1,367/1,367; 0 inside progress).
- Phase C measured the mechanism: the table keeps only the last record per message.id and drops 0.1869 [0.1804, 0.1927]
  of tool_use ids (76,258/407,920, n=4,847 sessions).

**The raw full-population pass** (`cited.swechat_full_population_pass`, all 5,850 files):

| scope | calls | results | results without call | calls without result |
|---|---|---|---|---|
| all formats | 635,454 | 633,366 | 16 (share 0.0000253) | 2,104 (0.0033) |
| claude_code | | | 16 | 861/584,802 = 0.0015 |
| codex | | | | 131/21,902 = 0.0060 |
| gemini | | | | 486/5,246 = 0.0926 |
| opencode | | | | 6/22,619 = 0.0003 |
| cursor | | | | 619/619 |

Duplicate call ids: claude_code 16, gemini 1.

The raw IR also recovers 176,501 nested subagent calls as is_subagent call events. The table hides 172,814 of these
inside progress rows. The two counts come from different session sets and definitions, so they are not a matched
comparison.

**Cross-check on the 2,200-session A+B sample** (`cited.swechat_table_vs_raw_crosscheck`):
- 2,159 sessions are in the table and 41 are absent.
- In the present sessions the raw IR has 171,329 calls (excluding nested) against 133,018 table tool_use rows, so
  38,311 more.
- Raw has more calls in 1,671 sessions, the same in 485, and fewer in 3.
- 38,178 raw ids are not in the table. 162 table ids are not in raw, all opencode, tied to REDACTED-id handling.

By format:

| format | sessions | raw calls | table tool_use rows |
|---|---|---|---|
| claude_code | 1,801 present | 147,483 | 120,355 |
| codex | 96 | 10,923 | 0 |
| cursor | 15 | 370 | 0 |
| gemini | 7 of 37 in the table | | equal to raw where present (497) |
| opencode | 239 | 11,934 | 12,166 |

In opencode, 238 sessions are equal and 1 has fewer raw calls, a difference of 232.

**Net:** for joins, the table loses about one result in five to orphaning (0.1877). The raw transcripts lose 16 results in
633,366, and they add Codex and Cursor calls that the table lacks entirely.

## Nulls stated plainly
- No corpus shows a call key with more than one result.
- Apart from swechat's 3, no corpus shows an orphan result.
- aiv_cu's zero is uninformative: pairing there is built by the loader.
- swechat cursor has no results at all.
- The whowhen pairings are assigned by the loader (AG by step adjacency, HC by an open-call heuristic). Nothing in the
  data can check them.
