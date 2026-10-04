# Phase C lens: within-session change points (regime shifts)

Script: `analysis/probes/phase_c_changepoints.py` (`PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_c_changepoints`, about 45–70 s,
single process; a second run reproduced the JSON exactly apart from `meta.runtime_s`).
Data: `analysis/out/phase_c/changepoints.json`. Every number below is in that JSON; paths are relative to its root, and
`S.` abbreviates `corpora.swechat.series.`. Inputs are the Phase B caches. The read-only raw scans are swechat Claude Code
transcripts and cc_local main files, used for the per-entry `version`, `sessionId` and `permissionMode`; no content was copied.
cc_local appears only as aggregates. The JSON holds no session ids, tool names or strings for that corpus.

Method (fixed in `meta.prereg` before any change point was computed):
- Eligibility: sessions with at least 40 main-thread calls, and series with at least 40 points.
- Detector: binary segmentation with a penalized likelihood and a minimum segment of 10 points.
  - Continuous series use log1p values, a Gaussian mean shift with sigma = sd(diff)/sqrt(2), and a penalty of 2 ln n.
  - `err` uses a Bernoulli model with a penalty of 2 ln n.
  - `tool` uses a multinomial model over the top 7 tools plus "other", with a penalty of C ln n.
- Series: latency, gap, result_len, err, tool and thinking are per call; ctx, usage_in and usage_out are per API response.
- Co-occurrence: an event co-occurs if its seq lies within 3 points either side of the change point, or in the tight window
  (point k-1, point k]. The chance expectation for each change point is the fraction of admissible positions
  [10, n-10] in the same series whose window holds such an event. Reported as obs/exp with a session-clustered bootstrap.
- Controls:
  - one i.i.d. permutation of every series;
  - one permutation of 10-point blocks, which keeps short-range dependence;
  - a synthetic AR(1) calibration.
- Harness event types and their definitions are in `meta.harness_definitions`. The primary set excludes `other_system`, which
  the broad set adds.

Bugs fixed and post-hoc additions are listed in `meta.revisions` (r1–r3 bugs, P1–P5 post hoc). The P keys are descriptive
only: they never change detection, co-occurrence or the no-harness counts. Treat them as hypotheses that need a holdout.

---

## Part 1: Measurements

### 1.1 Eligibility (`corpora.*.inventory`)
- **swechat:** 970/2000 B sessions are eligible: claude_code 897, codex 34, opencode 26, gemini 10, cursor 3. In 22 of them
  every call is a subagent call (session-level subagents). 897 raw transcripts were scanned and 0 were missing.
- **cc_local:** 15/186. Most cc_local calls are subagent/workflow calls, so few sessions reach 40 main-thread calls.
- **aiv_cc:** 54/189 runs.
- **aiv_cu:** 988/2000.
- **whowhen:** 0/111. Calls per session max out at 30 (`corpora.whowhen.inventory.calls_per_session`), and there are no
  timestamps. **No result for Who&When.**
- **aiv_cu session-length cap (structure nobody asked about):** of all 78,114 computer-use sessions, 42,837 have 40–43
  turns, and the single most common length is 41 (35,684 sessions). Only 1,385 exceed 43
  (`corpora.aiv_cu.inventory.all_sessions_turn_count`). An aiv_cu "session" is therefore a window of about 40 turns
  imposed by the harness. That boundary is itself the largest harness event in the corpus. Within a session, a
  minimum segment of 10 confines change points to positions 10–30 (pos_rel p5/p95 = 0.25/0.75, `corpora.aiv_cu.series.*.pos_rel`).
  The gap series is eligible in only 292/988 aiv_cu sessions, because a 40-call session has 39 gaps.
- **Observable harness events differ sharply by corpus:**
  - swechat: 16 event types (counting `other_system` and the post-hoc `synthetic_msg`), including 11,715 user turns, 3,478 subagent starts, 835 compaction markers, 174 /clear, 89 model
    switches, 68 version changes and 104 sessionId changes. The sessionId changes fall in only 4 sessions.
  - aiv_cc: compaction (2,008 marker rows) and 1 api_error.
  - **aiv_cu: only tool timeouts (234 in 103 sessions).** Its raw "model switches" were naming artifacts (model string vs
    provider model version) and are removed by r2: `model_switch_pairs_eligible_sessions` is empty.
- **swechat main-thread model switches are mostly to and from Haiku:**
  - opus-4-6 → haiku-4-5 (21), sonnet-4-6 → haiku-4-5 (21), haiku-4-5 → sonnet-4-6 (19), haiku-4-5 → opus-4-6 (12);
  - plus one switch to a model named `exact-dodo`.

  Source: `corpora.swechat.inventory.model_switch_pairs_eligible_sessions`. The data does not say why Haiku turns appear
  in the main thread.

### 1.2 Detector calibration (`synthetic_calibration_ar1`, `S.*.lag1_autocorr`)
- **AR(1) false-positive rate** (300 replicates each; n = 50 / 200 / 1000):

  | rho | n = 50 | n = 200 | n = 1000 |
  |---|---|---|---|
  | 0 | 0.050 | 0.027 | 0.013 |
  | 0.3 | 0.297 | 0.410 | 0.350 |
  | 0.5 | 0.657 | 0.843 | 0.890 |
  | 0.7 | 0.907 | 1.000 | 1.000 |

  **The detector is calibrated only for independent data.**
- **Median lag-1 autocorrelation in swechat:** latency 0.354, result_len 0.220, gap 0.127, usage_out 0.051, usage_in 0.042,
  thinking 0.007, ctx 0.985 (ctx is a growing level).
- **What the controls mean:**
  - The i.i.d. shuffle control measures the false-positive floor for exchangeable data.
  - The block-shuffle control keeps dependence within 10 points. It can also keep part of a real regime signal, because
    blocks from two regimes still differ in mean. So "observed minus block control" is a conservative lower bound on
    regime structure beyond short-range persistence.

### 1.3 How many sessions show a step change (k/n sessions, Wilson CI; `*.sessions_with_cp`, `*shuffle_control*`)

**swechat** (n = eligible series):

| series | observed | i.i.d. shuffle | block shuffle | change points (up/down) |
|---|---|---|---|---|
| latency | 703/966 = 0.728 [0.699, 0.755] | 0.043 | 0.569 | 1656 (998/658) |
| gap | 529/950 = 0.557 [0.525, 0.588] | 0.044 | 0.313 | 753 (600/153) |
| result_len | 585/966 = 0.606 [0.574, 0.636] | 0.037 | 0.430 | 1003 (363/640) |
| err | 121/966 = 0.125 [0.106, 0.148] (129 degenerate) | 0.022 | 0.071 | 155 (88/67) |
| tool | 709/970 = 0.731 [0.702, 0.758] | 0.001 | 0.356 | 1087 |
| thinking | 259/970 = 0.267 [0.240, 0.296] (355 constant) | 0.034 | 0.106 | 357 (138/219) |
| ctx | 779/852 = 0.914 [0.894, 0.931] | 0.052 | 0.865 | 5147 (4797/350) |
| usage_in | 341/852 = 0.400 [0.368, 0.434] | 0.053 | 0.249 | 994 (598/396) |
| usage_out | 222/852 = 0.261 [0.232, 0.291] | 0.040 | 0.174 | 312 (105/207) |

**aiv_cc** (54 runs; observed / block):
- gap 0.556 / 0.037
- tool 0.556 / 0.130
- thinking 0.352 / 0.056
- latency 0.463 / 0.278
- result_len 0.519 / 0.259
- usage_out 0.444 / 0.093
- err 0.185 / 0.074
- usage_in 0.074 / 0.000

**aiv_cu: NULL beyond short-range dependence.** Observed and block-control rates are close in every series:
- latency 0.534 vs 0.433
- gap 0.418 vs 0.370
- result_len 0.259 vs 0.218
- tool 0.181 vs 0.141
- thinking 0.319 vs 0.261
- usage_out 0.300 vs 0.231

err is degenerate in all 988 sessions, because aiv_cu has no error flag or marker.

**cc_local** (n = 15, wide CIs): latency 8/15, gap 10/15, result_len 7/15, tool 7/15, usage_out 9/14. thinking is
constant in 8/15 sessions.

ctx shifts in every corpus are dominated by the context growing: up-shifts are 4797 of 5147 in swechat and 1658 of 2150
in aiv_cc. Only down-shifts are informative (1.6).

**Size** (swechat, |delta| in sigma units, median; exp(|delta of log1p|) median and p95):

| series | sigma units | factor median | factor p95 |
|---|---|---|---|
| latency | 1.51 | 16.4 | 262.8 |
| gap | 1.13 | 5.08 | 30.8 |
| result_len | 1.32 | 8.51 | 48.4 |
| thinking | 1.17 | 8.36 | 132.9 |
| usage_out | 1.01 | 2.82 | 12.9 |

Source: `S.*.delta_sigma_abs`, `factor_exp_abs_delta`. Positions: result_len and thinking change points sit early
(pos_rel median 0.32), gap at 0.33, latency at 0.52.

### 1.4 What co-occurs at the change point (swechat, ±3-point window; obs/exp [CI]; `S.<series>.cooccur`, `by_direction`)
- **ctx down-shifts (n = 350):**
  - compaction: 238 vs 12.5 expected, o/e **19.1 [17.1, 21.0]**
  - slash commands other than /clear: o/e 3.47 [2.64, 4.48]
  - /clear: zero co-occurrence *and* zero expectation. All 174 /clear markers sit at the very start of their session
    (pos_rel median 0.005, p95 0.017; `corpora.swechat.inventory.posthoc_event_pos_rel_in_session.context_clear`, P5).
    A swechat transcript begins after the /clear, so this event type cannot explain any within-session shift.
  - subagent start: o/e 2.26
  - only 31 have no harness event (o/e 0.138 [0.088, 0.200])
- **ctx up-shifts:** compaction o/e 0.184. Growth never coincides with compaction.
- **aiv_cc ctx down-shifts (492):** 484 have compaction in the window (o/e 13.7 [13.0, 14.3]), and 8 have none
  (`corpora.aiv_cc.series.ctx.by_direction.down`).
- **usage_in (uncached input):**
  - model_switch o/e 4.81 [3.16, 8.22], tight 12.6 [7.7, 21.8]; for up-shifts, model_switch o/e 6.93
  - compaction tight o/e 11.3 [4.5, 16.6]
  - task_notification tight o/e 6.34 [4.24, 9.08]
- **thinking:**
  - model_switch tight o/e 14.7 [6.9, 31.1]
  - compaction tight o/e 7.71 [3.05, 12.6]
  - setting_change (permission-mode / /model) tight o/e 7.56 [2.93, 13.1]
  - for up-shifts, model_switch o/e 9.45 and idle ≥ 300 s o/e 5.59
  - in aiv_cc, compaction o/e 5.46 [3.75, 7.55] overall and 7.63 for up-shifts
- **latency:**
  - subagent_start o/e 1.97 [1.78, 2.17]; for down-shifts 2.86
  - user_turn o/e 1.17
  - latency down-shifts are enriched for idle ≥ 300 s (o/e 3.35 [2.63, 4.21])
  - **latency up-shifts are not enriched for any harness event: none-in-window o/e 1.034 [0.997, 1.072]**
- **gap:**
  - subagent_start o/e 2.04
  - user_turn o/e 1.40
  - setting_change tight o/e 5.72 [2.27, 9.98]
  - idle o/e 2.53 [1.95, 3.16]
- **err:** interrupt o/e 3.89 [2.30, 6.19]. Most other types are not significant.
- **result_len and tool:** the weakest harness association. result_len none-in-window o/e 0.945 [0.909, 0.980] and tool
  0.950 [0.914, 0.985]. result_len down-shifts give o/e 1.036 [0.995, 1.074].
- **resume and version_change:** too rare for informative CIs. Resume appears in 4 eligible swechat sessions and version
  change in 34. Example: latency version_change 3 obs vs 2.6 expected.

### 1.5 Shifts with NO co-occurring harness event (`*.no_harness_window`, `no_harness_cps`, `sessions_all_cps_no_harness`)

**swechat**, share of change points with no primary harness event within ±3 points (cluster rate) and obs/exp against
random placement:

| series | share with no event | obs/exp |
|---|---|---|
| latency | 1050/1656 = 0.634 [0.609, 0.660] | 0.887 [0.857, 0.919] |
| gap | 452/753 = 0.600 | 0.823 |
| result_len | 702/1003 = 0.700 | 0.945 |
| err | 95/155 = 0.613 | 0.862 |
| tool | 757/1087 = 0.696 | 0.950 |
| thinking | 189/357 = 0.529 | 0.732 |
| ctx | 2944/5147 = 0.572 | 0.876 |
| usage_in | 508/994 = 0.511 | 0.744 |
| usage_out | 169/312 = 0.542 | 0.819 |

The tight window gives 0.759–0.879. The broad set (adding `other_system`) lowers the shares by at most 0.052
(usage_out 0.542 → 0.490).

The no-harness population, characterized post hoc (P1, `S.*.posthoc_tool_mix_at_cp`):
- **latency up-shifts with no harness event (744):** the tool whose share rises most is shell in 598. The median tool-mix
  TV distance between the adjacent segments is 0.591. Latency down-shifts (306) go to edit (138) and read (76).
- **result_len down-shifts with no harness event (496):** edit 232, shell 153, taskupdate 56; TV median 0.667.
  result_len up-shifts go to read (88) and shell (78).
- **thinking down-shifts with no harness event (134):** edit 65, shell 44.
- **Idle gaps:** no-harness change points almost never carry a ≥ 300 s idle gap (latency 11 of 1050). Harness-event change
  points carry 65 of 606. When the user steps away, a user turn is logged.
- **Cross-series coincidence** (±3 calls, `corpora.swechat.cross_series`):
  - latency→tool 0.202 vs chance, o/e 2.22 [2.05, 2.40]
  - tool→latency o/e 2.28
  - gap→thinking o/e 2.83
  - result_len→tool o/e 1.98
  - err pairs are about 1 or lower (e.g. err→tool o/e 0.684 [0.323, 1.090])
- **aiv_cc couples more tightly:**
  - gap↔thinking o/e 21.3 [14.9, 34.5] (gap→thinking 22 of 69 gap change points)
  - result_len↔tool o/e 11.9
  - tool→err o/e 17.1 [8.2, 24.7]
- **aiv_cu:** result_len↔tool o/e 2.53 [2.29, 2.80]; latency↔gap o/e 0.93, a null.

**aiv_cu and aiv_cc no-harness shares are near 1 by construction:**
- aiv_cu: latency 0.981, gap 1.000, thinking 0.975. Only tool timeouts are logged.
- aiv_cc: latency 0.835. Only compaction is logged.

There is no user-turn channel in either AI Village stream. "No harness event" there means "no event the stream records".

### 1.6 The ctx down-shift residue (P2–P4, `corpora.*.posthoc_ctx_down_no_harness`)
**swechat: 31 down-shifts in 30 sessions.**
- Only 2 contain a one-step drop below 0.5× within the window, and both sit on runs of `<synthetic>` zero-usage responses
  (`n_synthetic_msg_in_window` 2).
- **0** are sharp, off the edge and free of `<synthetic>` messages (`n_sharp_and_not_edge_and_no_synthetic`).
- The other 29 show no sharp step in the window (min step median +0.0012 log); 6 of the 31 sit exactly at k = 10 or
  k = n − 10.
- `<synthetic>` messages co-occur with ctx change points at o/e 7.49 [6.53, 8.69] (P3).

**aiv_cc: 8 down-shifts in 8 runs.** None is sharp, and 7 sit at the minimum-segment edge. These are compaction drops
the detector placed at the segment-length limit, outside the window. The aiv_cc `posthoc_n_cp_at_min_segment_edge` for
ctx is 27 of 2150.

**aiv_cu: 8 down-shifts in 6 sessions, all in the `anthropic-claude-code` stratum** (the Claude-Agent-SDK agent). 4 of
them are sharp, off the edge and unexplained (window minimum step −1.615 to −1.878 log). The computer_use_turns table has
no compaction marker. Whether this is the same agent whose compactions aiv_cc logs was not checked (no agent-id join was
done).

**cc_local: 1 down-shift.** It is not sharp.

Edge pinning in general (P4): swechat latency 149 of 1656 and ctx 490 of 5147; aiv_cu thinking 95 of 359 and
result_len 81 of 294.

### Nulls (same prominence)
- **aiv_cu:** no regime structure beyond short-range dependence in sessions of about 40 turns (1.3), and no harness events
  except tool timeouts. Tool timeouts do not enrich latency, tool or ctx change points: o/e 1.08, 0.80 and 0.95, all CIs
  spanning 1.
- **Who&When:** no eligible session.
- **Latency up-shifts** (the largest single class of swechat shifts, 998) have no harness enrichment: none o/e 1.034
  [0.997, 1.072].
- **result_len and tool change points** have only a slight harness enrichment: none o/e 0.945 and 0.950.
- **err** change points do not coincide with other series (err→gap/result_len/tool o/e 0.68–0.78, CIs include 1).
- **Rare events:** resume (sessionId change), version change and rollback are too rare in eligible B sessions to test.
- **Thinking:** the series is constant (degenerate) in 355/970 swechat sessions and 8/15 cc_local sessions.
- **Idle gaps:** a ≥ 300 s idle gap at a no-harness change point is rare in every corpus.

---

## Part 2: Interpretation (not data)

**Step changes are everywhere, and most of them are the agent's own phase changes, not the harness.** Sessions with at
least one change point clearly exceed the i.i.d. control in every series and corpus. The honest yardstick, though, is the
block-shuffle control, since latency and result_len carry median lag-1 autocorrelation of 0.22–0.35, where the AR(1)
calibration gives 15–41% false positives (rho 0.2–0.3). Against that yardstick the excess is still clear in swechat and aiv_cc, and absent in aiv_cu.
About 51–70% of swechat shifts have no harness event within ±3 calls (depending on the series), and the enrichment
for harness events is modest (none-in-window o/e 0.73–0.95). What does line up with them is the tool mix: latency up-shifts are the agent entering a
shell-heavy phase (tests and builds), and result_len and thinking down-shifts are it entering an edit-heavy phase. That
reading matches the early position of result_len and thinking shifts (median 0.32): exploration with long reads first,
then edits. These shifts are behavioural and leave no harness trace. A detector cannot tell them from tampering, so
**"unexplained regime shift" is not a usable fabrication signal on its own**. On honest data, 565 of 966 swechat
sessions already contain at least one latency shift with no harness event (`S.latency.no_harness_cps.sessions`).

**The exception is context size, which is close to fully explained.** In swechat and aiv_cc, every context down-shift
with a sharp drop in its window is accounted for by a logged compaction or /clear, or by a harness-written `<synthetic>`
message (0 residual in swechat after P3/P4, 0 in aiv_cc). The leftover "unexplained" down-shifts are detector artifacts:
boundaries pinned to the 10-point segment limit, away from the real drop. In aiv_cu, the Claude-Agent-SDK stratum shows
4 sharp drops with no marker, and that table logs no compactions. That is an example of how a missing harness channel
looks to this check: a false positive, not fabrication.

**Couplings that look physical, and could therefore serve as internal witnesses:**
1. **Model switch → uncached-input jump** (usage_in tight o/e 12.6). This fits per-model prompt caches: a model switch
   should force a cache miss.
2. **Thinking volume ↔ inter-call time** (aiv_cc o/e 21.3, swechat 2.8). Generating thinking takes wall time.
3. **Compaction ↔ thinking / gap / result_len** shifts in aiv_cc (o/e 5.5 / 5.3 / 3.4). Behaviour resets after a summary.
4. **Interrupt ↔ err** shifts (o/e 3.9).

These are measured co-occurrences, not identities. Turning (1) or (2) into a per-event test would need a direct
measurement, not change points.

**Data surprises worth carrying to Phase D:**
- the aiv_cu session cap at about 41 turns;
- Haiku turns interleaved in the Claude Code main thread (74 of the 89 normalized switches involve haiku-4-5);
- /clear markers only at session starts (a swechat transcript begins after the /clear);
- `<synthetic>` zero-usage responses that look like context collapses (560 in 179 eligible swechat sessions);
- the pandas 3 microsecond parse that silently turned "ms" into seconds (r3; other probes using `astype("int64")` on parsed
  timestamps should check this).

## Candidate mechanisms (novelty UNVERIFIED)
1. **Context-drop accounting.** Every sharp drop in server-reported context size must sit within a few events of a logged
   compaction, /clear or harness-synthetic message. On honest data the sharp unexplained residue was 0 of 350 swechat and 0
   of 492 aiv_cc down-shifts (after the post-hoc P3/P4 rules), and 4 of 8 in aiv_cu, where compaction is not logged. It
   overlaps with the aiv_accounting cache-chain/context-delta check, and is blind to substitutions that preserve length.
2. **Model-switch cache-miss signature.** A claimed model switch should coincide with a jump in uncached input. Measured
   here only as change-point co-occurrence (usage_in × model_switch, tight o/e 12.6 [7.7, 21.8]). Per-switch rates are not
   measured.
3. **Thinking-time coupling.** Shifts in thinking volume co-occur with shifts in inter-call gap (aiv_cc o/e 21.3, swechat
   2.8). A log that claims heavy reasoning at short gaps, or the reverse, would break a coupling seen on honest data. The
   per-event relation is not measured.

## Could not measure
- Who&When (no timestamps; no session reaches 40 calls).
- Claude Code version inside aiv_cc runs (one version per run by construction) and Codex/OpenCode/Gemini versions within a
  session (one `session_meta` per Codex session in B; the other two have no version field in the IR).
- Why Haiku turns appear in Claude Code main threads; what the cc_local `model` and `auto_mode` attachments mean (private
  content not read).
- Whether ctx drops are compactions in aiv_cu (no marker in that table).
- A detector calibrated under the observed autocorrelation. Only the block-shuffle bound and the AR(1) table are given.
- Per-event identity tests for the couplings in Part 2 (outside this lens).

## Revision log (details in `meta.revisions`)
- **r1 (bug):** missing markers were NaN and counted as errors, so every err series was degenerate. Fixed before any err
  change point existed.
- **r2:** model-switch name normalization. The raw aiv_cu "switches" were model-string vs provider-version naming
  differences. The run-1 inventory had been seen.
- **r3 (bug):** timestamps were parsed in seconds, not ms (pandas 3 microsecond resolution). This changed the latency, gap
  and idle results; all run-2 results had been seen.
- **P1–P5:** post hoc, added after reading runs 4–6: tool-mix and step descriptors, the ctx-drop list, the
  `<synthetic>` descriptor, the edge-pinning counts, and the harness-event position inventory.
