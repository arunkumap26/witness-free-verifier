# Phase C lens: aiv_narration (an agent's own session narration vs that session's tool log)

Script: `analysis/probes/phase_c_aiv_narration.py`. Data: `analysis/out/phase_c/aiv_narration.json`. Every number below
is in that JSON, and the path after each number is relative to its root. The script streams `events.jsonl.gz` once
(381,610 rows, `events_census.rows`) and reads `computer_use_sessions.jsonl.gz`, the aiv_cu IR caches A and B, and
`aiv_cu_sessions.parquet`.

Unit: the session. Sample: aiv_cu A and B together, 2,200 sessions. 2,192 of them have IR events
(`linkage.sampled_sessions_in_ir`). The other 8 are 1-turn sessions whose only turn is synthetic
(`linkage.sampled_not_in_ir`). CIs are session-clustered
bootstraps (`lib/stats.cluster_rate`) or Wilson intervals over sessions. Format below: `rate (CI), claims / sessions`.

Extraction and support rules were fixed in `prereg` before any support rate was computed. Rules added after the first
run are in `post_hoc_rules`, and their outputs are only under `post_hoc`. Comparing the parsed JSON against the
first run showed every pre-registered section unchanged after the post-hoc additions.

**Channels.** Each one is matched against the session's own log, meaning call args, shell commands and result
text/stderr:
- `stop_summary`: STOP_USING_COMPUTER.summary. This is the agent's own session summary, written before the
  2026-03-24 perma-computer-use change.
- `consolidate_goal`: CONSOLIDATE.nextSessionGoal, written after a session in the perma regime. It looks forward but
  often carries state.
- `session_goal`: written before the session. Used as a baseline.

**Controls.** The same extraction is run on narration that is not about the session, then checked against this
session's log:
- `c1_prev_same_agent`: the same agent's previous narration.
- `c2_other_agent`: the narration from a different agent nearest in time.

---------------------------------------------------------------------------------------------------------------------

## A. Numbers

### A1. Parser surprises and linkage (`events_census`, `linkage`)

- **STOP rows carry no `computerUseSessionId`.** The key is absent from all 25,939 STOP rows
  (`events_census.boundary_keys.STOP_USING_COMPUTER`). The brief assumed it was there.
  - Linkage used instead: agent order. Within each agent, a STOP inherits the session id of the START just before it.
  - Pairing counts: 25,934 STOPs follow a START, 5 follow another STOP, and 41 STARTs have no STOP
    (`linkage.stop_pairing`).
  - Validation: 25,782 of 25,785 linked STOPs are inserted after the session's last turn, and the agent matches in
    25,785 of 25,785 (`linkage.validation`).
- **CONSOLIDATE.computerUseSessionId names the session that just ended.** All 52,244 linked rows come after that
  session's last turn and 0 come before its first turn (`linkage.validation`).
- **START.sessionGoal equals `computer_use_sessions.session_goal`** in 727 of 727 sampled sessions
  (`linkage.start_sessionGoal_eq_session_goal`).
- **Post hoc: the narration chain.** The agent's previous CONSOLIDATE nextSessionGoal is exactly this session's
  session_goal in 1,470 cases and differs in 3 (`post_hoc.chain_equality`; counted over all 2,200 sampled sessions,
  including the 8 without IR events). In the perma regime, then, the "previous narration" control and the session goal are the
  same text. That is why the consolidate c1 and session_goal rows match.
- **`has_been_asked_to_stop` is False in all 2,200 sampled sessions** (`linkage.sampled_has_been_asked_to_stop`). A
  split by operator-forced stop is not possible.
- **Post hoc: placeholder summaries.** 5,975 of 25,939 STOP summaries are one of three platform texts
  (`post_hoc.placeholder_summaries.strings`):
  - "No summary made public ...": 3,578 rows, 2026-03-05 to 2026-03-27
  - "This week, computer use session summaries aren't being included in this event. This is so agents don't see each
    other summaries": 1,743 rows, 2026-01-12 to 2026-01-23
  - "No summary provided": 654 rows

  180 sampled sessions have a placeholder, and they yield 0 entity claims. The second placeholder implies that the
  STOP summary is broadcast to the other agents.

### A2. Coverage (`coverage`, `post_hoc.placeholder_summaries`)

- **Raw coverage.** STOP summary: 727/2,192, 0.332 (0.312-0.352). CONSOLIDATE: 1,465/2,192, 0.668 (0.648-0.688).
  Both: 0. Neither: 0/2,192 (upper bound 0.0017). Every sampled session therefore has exactly one narration channel,
  set by regime (`coverage.all`). By stratum the split is total: anthropic-claude-code and openai-chat are STOP only,
  while anthropic-fable and gemini-flash are CONSOLIDATE only (`coverage.by_stratum`).
- **Substantive coverage** (placeholders removed). STOP: 547/2,192, 0.250 (0.232-0.268). Any channel: 2,012/2,192,
  0.918 (0.906-0.929).
- **Lengths.** Sampled STOP summaries have a median of 2,352 chars (`summary_profile.summary_chars`). Sampled
  CONSOLIDATE nextSessionGoals have a median of 319 chars (`consolidate_profile.next_goal_chars_sampled`).

### A3. Where the narration comes from (`summary_profile`)

- **The summary text never appears in the STOP event's raw model output.** First 100 alphanumeric chars: 0/25,939
  over the whole STOP population (Wilson upper 0.00015). Output is present in 13,495/25,939 rows
  (`summary_profile.population_all_stop_rows`).
- **The summary is too long for the STOP call's tokens.** Summary chars exceed 8 x STOP outputTokens in
  19,728/24,615 rows, 0.801 (0.796-0.806). The median is 44.0 summary chars per STOP output token.
- **The summary is generated after the last turn.**
  - STOP insert minus the session's last turn: median 42.2 s (`summary_profile.latency_s_stop_minus_last_turn`).
  - Spearman(summary chars, that latency): 0.416 (0.342-0.485), n 727.
  - Spearman(summary chars, session turns): 0.064 (-0.012 to 0.143), which is null.

### A4. Claim support by type (`claims.<source>.entities.<type>.supported`)

"Supported" means:
- url, path, filename, command, quoted: the value is in the session's call side or result side.
- hex_id, number: the value is in the result side.

| type | stop_summary | stop c2 (other agent) | consolidate_goal | consolidate c2 | session_goal (pre-session) |
|---|---|---|---|---|---|
| url | 0.317 (0.256-0.388), 1235/315 | 0.094 (0.069-0.126) | 0.520 (0.447-0.595), 398/172 | 0.052 (0.029-0.075) | 0.508 (0.436-0.577) |
| path | 0.622 (0.548-0.693), 352/157 | 0.048 (0.017-0.081) | 0.701 (0.647-0.750), 883/288 | 0.027 (0.017-0.041) | 0.529 (0.426-0.626) |
| filename | 0.625 (0.545-0.702), 762/223 | 0.157 (0.111-0.212) | 0.690 (0.639-0.741), 1273/343 | 0.079 (0.055-0.107) | 0.600 (0.546-0.660) |
| command | 0.680 (0.610-0.746), 434/133 | 0.080 (0.051-0.116) | 0.355 (0.282-0.435), 490/112 | 0.038 (0.022-0.056) | 0.479 (0.403-0.557) |
| quoted text | 0.331 (0.302-0.363), 3596/507 | 0.047 (0.038-0.057) | 0.462 (0.410-0.509), 2842/423 | 0.038 (0.026-0.053) | 0.329 (0.292-0.369) |
| hex id | 0.590 (0.470-0.706), 256/93 | 0.112 (0.052-0.185) | 0.731 (0.647-0.812), 1383/302 | 0.076 (0.041-0.114) | 0.402 (0.350-0.456) |
| number | 0.351 (0.272-0.435), 1472/329 | 0.059 (0.034-0.094) | 0.490 (0.454-0.528), 3673/744 | 0.095 (0.076-0.115) | 0.378 (0.345-0.410) |

- **Looser matches** (STOP):
  - URL host found in the log: 0.557 (0.462-0.655).
  - Path, exact or by basename: 0.730 (0.667-0.790).
  - Command, by its first two tokens: 0.742 (0.677-0.806).
  - Hex ids next to commit/sha/push words: 0.533 (0.408-0.662), 197/88 (`claims.stop_summary.entities.*`).
- **STOP status breakdown, all claim types** (`claims.stop_summary.totals.entity_status_counts_all_types`):
  - none: 3,918
  - log_call: 1,728
  - log_result: 1,709
  - assistant_only (said in the session's own assistant text, no tool trace): 695
  - goal_only: 57
- **Matched-narration excess** (`own_vs_control.stop_summary`). Own minus c2, paired over sessions:
  - url: +0.190 (+0.112 to +0.266)
  - path: +0.513 (+0.409 to +0.619)
  - filename: +0.402 (+0.295 to +0.501)
  - command: +0.496 (+0.394 to +0.596)
  - quoted: +0.286 (+0.256 to +0.319)
  - hex: +0.339 (+0.141 to +0.513)
  - number: +0.272 (+0.185 to +0.349)

  Own minus c1 (the same agent's previous summary) is positive for every type, from +0.134 (url) to +0.385
  (command). The c1 rates themselves are high, e.g. filename 0.421 (0.354-0.494)
  (`claims.stop_c1_prev_same_agent`).
- **CONSOLIDATE minus its c1 (equal to session_goal)** (`own_vs_control.consolidate_goal`):
  - hex: +0.334 (+0.260 to +0.409)
  - path: +0.173 (+0.048 to +0.324)
  - number: +0.099 (+0.063 to +0.133)
  - url: +0.003 (-0.086 to +0.086), which is null
  - command: -0.092 (-0.147 to -0.035), so nextSessionGoal commands are supported less than the commands the agent
    planned for this session

### A5. Contradiction (pre-registered): almost empty

- **Assertive action claims.** stop_summary has 227: supported 89, unconstrained 70, contradicted_absent 68,
  contradicted_failed 0. consolidate_goal has 297: supported 206, contradicted_absent 74, unconstrained 16,
  contradicted_failed 1 (`claims.<src>.totals`).
  - Push in STOP: the evidence calls' outcomes are success 48, fail 1, unknown 20
    (`claims.stop_summary.actions.push.evidence_outcomes_assertive`).
  - No claim of push, commit, merge, PR or tests in either channel has a log showing that action failed.
- **Entity claims found in results only on error lines:** 2 in stop_summary and 2 in consolidate_goal
  (`claims.<src>.entities.{url,path,filename}.error_only_claims`).
- **The contradicted_absent share is not a fabrication rate.** It is no lower for other agents' narration. STOP push
  contradicted_absent is 0.290 (0.177-0.403) for the session's own narration and 0.450 (0.317-0.583) for c2.
  - A post-hoc context tag finds 23 of the 62 assertive STOP push rows inside code spans and 3 that name another model
    (`post_hoc.action_claim_context.stop_summary.push`). A row can carry more than one tag.
  - A 7-claim spot check (`post_hoc_rules.action_claim_context.why_added`) found other agents' pushes, earlier
    sessions, and planned command blocks.
- **The pre-registered own-vs-control difference for actions is exactly 0, with CI [0,0], by construction**
  (`own_vs_control.*.actions_supported`). An action claim's status depends only on the action type and the log.

### A6. Do action claims predict the log? (post hoc: `post_hoc.action_claim_conditioned_evidence`)

This covers sessions with at least 1 shell call. It compares P(the log has an evidence call) when the narration
asserts the action with P(the same) when the narration does not mention the action at all.

| channel / action | evidence when asserted | evidence when not mentioned | difference |
|---|---|---|---|
| STOP push | 31/49, 0.633 (0.493-0.753) | 39/255, 0.153 (0.114-0.202) | +0.480 (+0.330 to +0.614) |
| STOP commit | 21/29, 0.724 (0.543-0.853) | 45/271, 0.166 (0.126-0.215) | +0.558 (+0.381 to +0.719) |
| STOP pr_open | 10/13, 0.769 (0.497-0.918) | 21/293, 0.072 (0.047-0.107) | +0.698 (+0.450 to +0.922) |
| STOP merge | 5/27, 0.185 (0.082-0.367) | 13/276, 0.047 (0.028-0.079) | +0.138 (+0.001 to +0.297) |
| STOP deploy | 13/27, 0.481 (0.307-0.660) | 66/278, 0.237 (0.191-0.291) | +0.244 (+0.056 to +0.437) |
| CONS push | 97/118, 0.822 (0.743-0.881) | 434/1022, 0.425 (0.395-0.455) | +0.397 (+0.321 to +0.471) |
| CONS commit | 53/73, 0.726 (0.614-0.815) | 433/1065, 0.407 (0.377-0.436) | +0.319 (+0.213 to +0.416) |
| CONS merge | 13/26, 0.500 (0.321-0.679) | 32/1121, 0.029 (0.020-0.040) | +0.471 (+0.277 to +0.666) |

**Recall.** This takes sessions whose log shows a successful action and asks how often the narration asserts it:
- STOP push: 27/64, 0.422 (0.309-0.544)
- STOP commit: 19/62, 0.306 (0.206-0.430)
- CONS push: 82/456, 0.180 (0.147-0.218)
- CONS commit: 43/422, 0.102 (0.077-0.134)

### A7. Carry-over (post hoc: `post_hoc.carryover_split`)

A claim is "carried" if the same type and value is also in the agent's previous narration (c1).
- **STOP:** 0.262 (0.236-0.293) of claims are carried, 2,128 of 8,107 in 533 sessions.
  - Carried claims supported: 0.412 (0.354-0.473). Novel claims supported: 0.395 (0.359-0.430).
  - Paired novel minus carried: -0.003 (-0.065 to 0.054), n 415, which is null.
- **CONSOLIDATE:** 0.384 (0.349-0.418) of claims are carried.
  - Carried claims supported: 0.466 (0.428-0.501). Novel claims supported: 0.600 (0.568-0.630).
  - Paired difference: +0.112 (+0.063 to +0.159). For hex ids: novel 0.877 (0.811-0.932) vs carried 0.406
    (0.293-0.543).
- **Novel STOP string claims** (url, path, filename, command, quoted) supported, by how much of the session was GUI
  actions:
  - no GUI calls: 0.691 (0.640-0.737)
  - GUI share at most half: 0.445 (0.328-0.580)
  - GUI share over half: 0.278 (0.245-0.311)

### A8. Model family and GUI share (`by_stratum`, `by_gui_bin`, `by_model_string_min20`)

The measure here is pooled string-entity support (url, path, filename, command, quoted).
- **STOP, by GUI share:** gui_0 0.666 (0.582-0.743, 86 sessions) vs gui_gt_half 0.288 (0.258-0.320, 377 sessions).
  The matching c2 baselines are 0.144 (0.110-0.181) and 0.048 (0.036-0.061).
- **STOP, by stratum:**
  - compat-chat 0.609 (0.504-0.719, 26 sessions)
  - openai-responses 0.580 (0.507-0.646, 73 sessions)
  - openai-chat 0.413 (0.360-0.465)
  - anthropic-opus 0.328 (0.264-0.401), anthropic-haiku 0.323 (0.217-0.427), anthropic-sonnet 0.312 (0.256-0.373)
  - gemini-pro 0.250 (0.199-0.322, 94 sessions)
- **CONSOLIDATE, by stratum:**
  - openai-responses 0.771 (0.706-0.821, 122 sessions)
  - compat-chat 0.648 (0.573-0.725)
  - anthropic-opus 0.558 (0.505-0.609)
  - anthropic-sonnet 0.505 (0.443-0.552)
  - anthropic-fable 0.446 (0.365-0.520)
  - anthropic-haiku 0.350 (0.205-0.612)
- **Extremes by model** (at least 20 sessions):
  - gemini-3-pro-preview STOP URL support: 0.032 (0.010-0.094), 251 URLs in 14 sessions. A spot check found a memory
    dump of dozens of site URLs after a short GUI session.
  - gpt-5.2 STOP pooled support: 0.690 (0.610-0.748).
  - gpt-5.4 CONSOLIDATE pooled support: 0.865 (0.796-0.912).
  - gpt-5 CONSOLIDATE pooled support: 0.159 (0.047-0.286), 44 claims.

  Strata differ in GUI share, so these are not like-for-like model comparisons.

---------------------------------------------------------------------------------------------------------------------

## B. Interpretation (not data)

**The narration is grounded in the session's log well above chance, but only where the log can see.** For every claim
type, the session's own narration is supported more often than another agent's narration from the same moment, checked
against the same log. The STOP excess runs from +0.190 (url) to +0.513 (path).
- The other-agent baseline is low: path 0.048, quoted text 0.047. That baseline is a usable null distribution, so the
  matched-control design works.
- The excess falls sharply in GUI-heavy sessions. Screens are not logged, so whatever the agent read off the page
  ($ totals, follower counts, page titles) is unconstrained.
- For a witness-free checker, the tool log constrains mainly the shell and text-tool part of the narration: paths,
  commands, hashes and printed numbers. It does not constrain the visual part.

**What a narration-vs-log check would flag, and why most of it would be false positives.** Measured sources of benign
mismatch:
1. Memory carry-over. In this corpus, narration is a rolling memory document, not a session report: a quarter of
   STOP claims and over a third of CONSOLIDATE claims repeat the previous narration. In STOP, carried and novel claims
   are equally supported, so "is it new?" does not separate session-specific claims.
2. Multi-agent attribution. The summary is broadcast to other agents, and it reports their pushes and merges.
3. Planned command blocks written as code.
4. GUI-only observation.
5. Placeholders, 180 of the sampled STOP summaries.
6. Forward-looking text. nextSessionGoal commands are less supported than the plan they replace.

"Claimed push, no push in the log" occurs at 0.29 for the session's own narration, which does not differ from the
other-agent rate. A raw absence rule has no specificity here.

**Contradiction is the main null.** The log showed a claimed action failing 0 times in 227 assertive STOP claims and
once in 297 assertive CONSOLIDATE claims (`claims.<src>.totals`). Entity claims seen only on error lines: 2 in each
channel. Two readings are possible:
- the narration does not misreport failures that the text log records, or
- the failure-text rules are too crude to see them.

The data cannot separate these two. Either way, contradiction-by-failure has no base rate here to calibrate a
detector on.

**Action claims carry information in the forward direction, but recall is low.** Asserting push or commit raises the
chance that the log contains one: STOP push +0.480, commit +0.558; CONSOLIDATE push +0.397, commit +0.319. However, most sessions with a
successful push never mention it (STOP recall 0.42, CONS 0.18). Narration is selective, not exhaustive. So a missing
claim says nothing, and only asserted claims can be checked.

**The narration is produced by an unlogged generation step.** The summary text never appears in the STOP call's
output, its length exceeds 8x that call's output tokens in a 0.801 share of rows, and its length tracks the delay after the last
turn. The generating call (prompt, model, tokens) is not in the dataset. One sampled openai-chat summary starts with
"Certainly! Here's a detailed summary of the above computer use session", which suggests a harness summarization
prompt. In the perma regime, the narration (nextSessionGoal) is also, verbatim, the next session's goal: 1,470 sessions
match exactly and 3 differ. Narration feeds directly into the next session's instructions.

**Nulls, stated plainly.**
- Contradiction by failure: 0 in STOP, 1 in CONSOLIDATE.
- Error-only entity claims: 2 per channel.
- Summary length vs session length: Spearman 0.064, CI spans 0.
- Novel vs carried support in STOP: -0.003, CI spans 0.
- CONSOLIDATE URL support minus session-goal URL support: +0.003, CI spans 0.
- Operator-forced stop split: impossible, since every value is False.
- Action own-vs-control: degenerate by construction.

**Novelty (UNVERIFIED).** Using a matched other-agent narration as the null when checking an agent's self-report
against its tool log might not be described for agent-log verification. The same applies to the finding that
narration-vs-log agreement in multi-agent settings is dominated by memory carry-over and third-party attribution. I
have not checked the literature, so do not assert novelty.
