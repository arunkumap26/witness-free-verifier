# Phase E, follow-up F2: swechat/claude_code latency-floor shifts

**Data.** `analysis/out/phase_e/f2_floor_shift.json`, written by `analysis/probes/phase_e_f2_floor_shift.py`
(`PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_f2_floor_shift`, 319.4 s, `runtime_s`).

**Revision.** This is the second run. An independent re-derivation found that the first run (`2026-10-04T08:30:10Z`)
gave rates, CIs, a covariate credit and an F2 outcome for B alone (21 step series) and E alone (10 step series). The
global minimum n forbids that: a rate needs ≥ 30 from ≥ 5 sessions (`prereg_e.json global.min_n` →
`prereg.json global.min_n`). Item-specific minima can only be stricter. The rule is now applied as written:
- B alone and E alone are **INSUFFICIENT_N**. Each shows raw k/n only: no rate, no CI, no credit test, no outcome.
- The headline "idle_gap credited on E alone" (7/10) is **withdrawn**.
- The primary B ∪ E population (31 step series from 28 sessions) and the pooled-index sensitivity (35 from 30) are
  above the minimum. Their numbers and their outcome OPEN are unchanged.

Every earlier value is kept beside the new one under `corrections` in the JSON (section 6 below). The raw data, the
step series, the controls and the covariate flags are identical to the first run.

**Pre-registration.** `prereg_e.json followups.F2_floor_shift`, `covariate_definitions` and `global.min_n`
(PREREG_E.md §1.6). The run follows them as written, except for the choices listed in `deviations` (section 7 below).
`check_frozen()` passed (`prereg.check_frozen`). The F2 thresholds and the min-n rule are asserted against the prereg
text when the script starts. The frozen module supplies `compromise_signature`, `js_distance`, `raw_cc_entries` and
`rng_for`. The step rule reuses the Phase B code path (`prereg_calibration.p1_qualified` and
`prereg_common.change_point`, with the seed `SEED + i`). No threshold was changed after any result was seen.

**Conventions.**
- k/n = share [Wilson 95%], given only where the denominator is ≥ 30 from ≥ 5 sessions.
- "k/n (insufficient n)" = raw count only, below that minimum.
- diff = step rate − control rate, with a 95% session-bootstrap CI (1,000 draws, every draw valid).
- s = sessions.
- Sections 1 to 7 report data. **Section 8 is interpretation.**
- Every number below is in the JSON. The path is given, or the block is obvious.

---

## 1. Which series shifted (`steps`)

| population | eligible series | step series | sessions with step / eligible | share | label |
|---|---|---|---|---|---|
| B (Phase B run) | 156 | 21 (18 up, 3 down) | 18 / 114 | 0.135 [0.090, 0.197] | UNSTABLE |
| **E (replication)** | 123 | **10 (10 up, 0 down)** | 10 / 98 | **0.081 [0.045, 0.143]** | **STABLE** |
| B ∪ E, union of the two runs (**primary F2 population**) | 279 | 31 (28 up, 3 down) | 28 / 212 | 0.111 [0.079, 0.153] | UNSTABLE |
| B ∪ E, pooled index (sensitivity) | 279 | 35 | — | 0.125 [0.092, 0.169] | UNSTABLE |

The step share is a rate over *eligible* series: 156, 123 and 279 series, all from more than 5 sessions. So the
replication label passes the minimum n. Only the F2 step-series populations of B and E fall below it.

- **Reproduction.**
  - B reproduces Phase B exactly: 21/156 series and 18/114 sessions, and every series has the same (k, step, p) as
    `probe_1.json` (`steps.B_reproduces_phase_b.series_level_match` = true).
  - The B, E and pooled counts equal those of `a1_p1_p3.json` (`steps.cross_check_a1_p1_p3`).
- **The replication does not confirm the instability.**
  - On E the step share is 10/123 = 0.081. The Phase B 0.10 rule labels that STABLE.
  - The E interval [0.045, 0.143] overlaps the B interval.
  - E has no down-steps.
- **Seed sensitivity.** The step count depends on how the permutation seeds are indexed. Eight series change their
  step flag between the per-split runs and the pooled run (`steps.pooled_vs_union_step_flag_differs`). In each of them
  the permutation p lies between 0.005 and 0.045, close to the 0.01 cut, and D is unchanged. The F2 outcome is the
  same under both readings (section 4).
- **By tool.** Reads dominate: 25 of the 31 step series are `read`, from 207 eligible read series. The other step
  series are 4 `grep`, 1 `glob` and 1 `todo` (`steps.BuE_union_of_split_runs.by_tool`).

## 2. Covariates at the step and at random control splits (`populations.<pop>.covariates`)

- **Controls.** Each non-step eligible series gets one random split k in [20, n − 20]
  (`rng_for('F2', session, tool_key)`).
- **Window.** Covariates are evaluated at k* (step series) or at k (controls), in a window of 5 series calls on each
  side of the split.
- **Balance.** The windows are comparable in size. They hold a median of 44 session calls at the steps and 51 at the
  controls (`post_hoc.step_window_session_calls`, `control_window_session_calls`). The 5th and 95th percentiles at the
  steps are withheld (31 < 100).

**B ∪ E (primary): 31 step series in 28 sessions; 248 controls in 196 sessions.**

| covariate | step | control | diff [session bootstrap] | present in step series | credited |
|---|---|---|---|---|---|
| harness_events (any of 15) | 24/31 = 0.774 | 161/248 = 0.649 | +0.125 [−0.038, +0.282] | 24 | no |
| version_change | 1/31 = 0.032 | 2/248 = 0.008 | +0.024 [−0.017, +0.100] | 1 | no |
| cwd_or_branch_change | 8/31 = 0.258 | 44/248 = 0.177 | +0.081 [−0.085, +0.262] | 8 | no |
| permission_mode_change | 2/31 = 0.065 | 16/248 = 0.065 | +0.000 [−0.079, +0.102] | 2 | no |
| **idle_gap (≥ 300 s)** | **18/31 = 0.581** | **85/248 = 0.343** | **+0.238 [+0.048, +0.427]** | 18 | **no (below 0.25)** |
| hook_rate_change | 0/31 = 0.000 | 9/248 = 0.036 | −0.036 [−0.059, −0.016] | 0 | no |
| tool_mix_shift | 24/31 = 0.774 | 179/248 = 0.722 | +0.052 [−0.136, +0.210] | 24 | no |
| parallelism_change | 2/31 = 0.065 | 21/248 = 0.085 | −0.020 [−0.103, +0.094] | 2 | no |
| result_size_shift | 12/31 = 0.387 | 110/248 = 0.444 | −0.056 [−0.241, +0.139] | 12 | no |
| subagent_in_flight | 14/31 = 0.452 | 145/248 = 0.585 | −0.133 [−0.332, +0.067] | 14 | no |
| workspace_change | 12/31 = 0.387 | 112/248 = 0.452 | −0.065 [−0.263, +0.141] | 12 | no |

**No covariate is credited on B ∪ E** (`populations.BuE.credited_covariates` = []).

**B alone and E alone: insufficient n on the step side.** The control side is reportable. No difference, CI or credit
test is computed (`populations.<B|E>.min_n`, `.covariates.<cv>.credit_test`).

| population | step series (sessions) | idle_gap at steps | idle_gap at controls | credit test |
|---|---|---|---|---|
| B | 21 (18 s) | 11/21 (insufficient n) | 47/135 = 0.348 | not computed |
| E | 10 (10 s) | 7/10 (insufficient n) | 38/113 = 0.336 | not computed (first run: credited, now withdrawn) |
| pooled-index sensitivity | 35 (30 s) | 20/35 | 83/244 | computed: diff +0.231, not credited |

**Window-reading sensitivity for idle_gap** (post hoc, not a verdict; `post_hoc.idle_gap_window_reading_sensitivity`).
The same ≥ 300 s rule, with the window read as 5 session calls on each side of the split call instead of 5 series
calls:

| population | as run (5 series calls), step vs control | 5 session calls, step vs control |
|---|---|---|
| B ∪ E | 18/31 vs 85/248, diff +0.238 | 5/31 = 0.161 vs 20/248 = 0.081, diff +0.081 |
| B | 11/21 (insufficient n) vs 47/135 | 3/21 (insufficient n) vs 12/135 |
| E | 7/10 (insufficient n) vs 38/113 | 2/10 (insufficient n) vs 8/113 |
| pooled index | 20/35 vs 83/244, diff +0.231 | 7/35 = 0.200 vs 19/244 = 0.078, diff +0.122 |

**Per harness type** (descriptive counts; the credited unit is "any harness event", `harness_by_type_descriptive`).
B ∪ E, step / control:

| type | step | control |
|---|---|---|
| user_turn | 18 | 119 |
| subagent_start | 18 | 109 |
| task_notification | 9 | 13 |
| slash_command | 6 | 27 |
| interrupt | 4 | 21 |
| setting_change | 2 | 16 |
| compaction | 1 | 35 |
| version_change | 1 | 2 |
| resume, model_switch, context_clear, tool_timeout, rollback | 0 | 0 |

## 3. Compromise signature (`populations.<pop>.signature_step`, `signature_control_descriptive`)

| population | met at the step | leg ρ | leg r | met at control random splits (descriptive, post hoc) |
|---|---|---|---|---|
| B ∪ E | 3/31 = 0.097 [0.033, 0.249] | 0 | 3 | **48/248 = 0.194 [0.149, 0.247]** (leg ρ 8, leg r 40) |
| B | 3/21 (insufficient n) | 0 | 3 | 25/135 |
| E | 0/10 (insufficient n) | 0 | 0 | 23/113 |

On B ∪ E the signature is met **less** often at the floor steps than at random split points of series that have no
step.

## 4. Classes and outcome (`populations.<pop>.classes`, `.outcome`; `verdicts`)

| population | BENIGN | COMPROMISE_LIKE | UNEXPLAINED | outcome |
|---|---|---|---|---|
| **B ∪ E (primary)** | **0/31** [0, 0.110] | **3/31** [0.033, 0.249] | **28/31** [0.751, 0.967] | **OPEN** |
| B (21 step series, 18 s) | — | — | — | **INSUFFICIENT_N** (first run: OPEN) |
| E (10 step series, 10 s) | — | — | — | **INSUFFICIENT_N** (first run: OPEN, BENIGN 7/10) |
| pooled-index sensitivity | 0/35 | 4/35 | 31/35 | OPEN |

- **Outcome.** DISMISSIBLE_AS_BENIGN needs BENIGN ≥ 0.8 of step series and COMPROMISE_LIKE = 0. That fails on B ∪ E
  and on the pooled-index sensitivity, so the outcome there is **OPEN**. B alone and E alone get no outcome.
- **Split breakdown of the primary classes** (raw counts, `populations.<B|E>.classes_of_primary_BuE_raw`):
  - B: BENIGN 0/21, COMPROMISE_LIKE 3/21 (listing 0, 13, 18), UNEXPLAINED 18/21.
  - E: BENIGN 0/10, COMPROMISE_LIKE 0/10, UNEXPLAINED 10/10.
  - These are the B ∪ E classes, under which no covariate is credited. They are not own-split verdicts.
- **Verdicts.** F2 moves no verdict (`verdict_effect`). P1 swechat/claude_code keeps the label A1 gave it.
- **Cells.** 4 F2 outcomes: 2 decided (B ∪ E, pooled sensitivity), 2 INSUFFICIENT_N. 22 credit tests were computed and
  22 withheld (`verdict_cells_computed`).

## 5. The COMPROMISE_LIKE series, for human review (`step_series_listing`, listing indices 0, 13, 18)

All three are B series and all are up-steps. Each meets the signature only through leg r (post-step median r ≥ 0.1).
Each has small results, and each as-run window holds an idle gap ≥ 300 s and a user turn. Under the 5-session-call
reading only #13 keeps its idle gap (max gap 888 s; #0 7.7 s, #18 9.9 s). The listing is per series and is not a rate,
so the minimum n does not apply to it.

| # | tool | n, k* | factor | Q10 pre → post (s) | post median r | median result bytes, 5 pre / 5 post | covariates present | notes |
|---|---|---|---|---|---|---|---|---|
| 0 | grep | 48, 20 | 2.5 | 0.065 → 0.164 | 0.125 | 320 / 317 | harness (subagent_start, task_notification, user_turn), cwd/branch, idle gap (max 104,550 s), tool mix, subagent in flight | same session as step #1 (`read`, up 29.6×), step stamps 81 s apart |
| 13 | todo | 251, 222 | 2.1 | 0.041 → 0.087 | 0.264 | 160 / 160 | harness (user_turn), cwd/branch, idle gap (max 8,832 s), tool mix | — |
| 18 | grep | 94, 64 | 2.0 | 0.098 → 0.196 | 0.991 | 1,280 / 49 | harness (subagent_start, task_notification, user_turn), cwd/branch, idle gap (max 2,336 s), tool mix, result size | same session as step #19 (`read`, up 5.4×), step stamps 56,814 s apart |

The pooled-index sensitivity adds a fourth series: an E `grep` series that is a step only under pooled indexing
(`sensitivity_pooled_index.compromise_like_series`).

## 6. Corrections (`corrections`; earlier values kept, first run `2026-10-04T08:30:10Z`)

| path | before | after | reason |
|---|---|---|---|
| `populations.E.outcome` | OPEN (BENIGN 7, COMPROMISE_LIKE 0, UNEXPLAINED 3 of 10) | INSUFFICIENT_N | 10 step series < 30 |
| `populations.E.credited_covariates` | [idle_gap]: 7/10 vs 38/113, diff +0.364 [+0.032, +0.641] | [] (credit test not computed) | step-side rate below min n |
| `populations.E.classes` | BENIGN 7/10, COMPROMISE_LIKE 0/10, UNEXPLAINED 3/10 | not computed; primary split breakdown 0 / 0 / 10 of 10 | needs the E credit test |
| `populations.B.outcome` | OPEN (0, 3, 18 of 21) | INSUFFICIENT_N | 21 step series < 30 |
| `populations.B.credited_covariates` | [] (closest: idle_gap +0.176 [−0.063, +0.392]) | [] (credit test not computed) | same value, now "not tested" |
| `populations.B.classes` | 0/21, 3/21, 18/21 | not computed; primary split breakdown 0 / 3 / 18 of 21 | needs the B credit test |
| `populations.{B,E}.covariates.*` step side, diff, CI, credited | Wilson shares, diffs, bootstrap CIs | raw k/n, label insufficient n | below min n |
| `populations.{B,E}.signature_step.met_wilson` | B 3/21 W[0.050, 0.346]; E 0/10 W[0, 0.278] | raw k/n | below min n |
| `step_series_listing[*].class_own_split` | E listing 21, 23, 24, 27–30 BENIGN | INSUFFICIENT_N for every B and E series | own-split credit test withheld |
| `post_hoc.read_only_matched_BuE` step side | Wilson shares on 25 read step series | raw k/n | 25 < 30 |
| `post_hoc` quantile blocks | every quantile | p5/p95 withheld below 100, p1/p99 below 500 | quantile_reportable |

`class_BuE`, the primary class of every listed series, is unchanged.

## 7. Deviations (`deviations`)

1. **Population.** The step set is the union of the Phase B run on B and the replication run on E. Each run indexes
   its permutation seeds within its own split. The pooled-index reading is reported in full as a sensitivity.
2. **Window and segments.**
   - The window is the seq range [anchor(k* − 5), anchor(k* + 4)], where the anchors are the series' call seqs (the
     Phase C `window_bounds` convention).
   - Each "segment" is one half of that window.
   - Hook share and parallelism are computed over all session calls in each half. The series calls themselves are
     never hooked and are always last in their message, by the filter.
   - Result size uses the series' own 5 points on each side.
   - Tool mix compares the 20 session calls before the step call with the step call and the 19 after it.
   - A raw-field covariate fires when the value in effect changes at an entry stamped inside the window's time span.
   - The same code runs at the control splits.
3. **Subagent in flight.** Paired subagent or workflow calls only.
4. **Empty results.** Median result bytes are floored at 1 before the log ratio is taken.
5. **Minimum n (the fix).** The global min-n rule is applied to every population rate and quantile. B and E get raw
   k/n and INSUFFICIENT_N. In their place the raw split breakdown of the primary classes is reported. Per-series inputs
   of the pre-registered covariates and signature (5-point medians, the human-review listing) are single-series
   quantities, not population rates, and are not gated.

No deviation changes a threshold.

## 8. Interpretation (not data; every number is from the JSON above)

- **Plain answer, B ∪ E, n = 31 step series in 28 sessions.**
  - None of the shifts is explained by a pre-registered benign covariate at the pre-registered bar (BENIGN 0/31).
  - 3/31 are compromise-shaped by the frozen signature.
  - 28/31 are unexplained.
  - The F2 outcome is OPEN. The shifts cannot be dismissed as benign under the rule.
- **B alone and E alone cannot answer the question.** With 21 and 10 step series they are below the pre-registered
  minimum of 30, so neither has a credit test or an outcome. The earlier "idle_gap credited on E alone" was a reading
  of 7 of 10 series. It is withdrawn, not reversed: E gives no evidence either way.
- **The signature does not single out compromise.**
  - All three COMPROMISE_LIKE series pass through leg r on small-result series: grep and todo with post-step median
    results of 49 to 317 bytes.
  - On such series, T_gen = chars × 0.25 / G90 (G90 = 65.26 tokens/s, `thresholds_used.G90_tokens_per_s`) is small,
    so ordinary sub-second latencies already give r ≥ 0.1.
  - The same signature fires at random splits of non-step series 48/248 = 0.194 of the time. That is more often than at
    the steps (0.097).
  - On this evidence the three series are not distinguishable from the honest background. A human reviewer should
    read them as "small-output tools stepping up across an idle gap", not as a detection.
- **The only association is with idle gaps, and it is borderline and depends on the window reading.**
  - An idle gap ≥ 300 s sits in the window at 18/31 steps, against 85/248 random splits: +0.238 [+0.048, +0.427].
  - That is the one covariate whose CI excludes 0 on B ∪ E. It still falls below the pre-registered 0.25 credit bar,
    and the bar was not moved.
  - **The enrichment depends on how "W = 5 calls" is read** (post hoc, not a verdict;
    `post_hoc.idle_gap_window_reading_sensitivity`). Read as 5 *session* calls on each side, the window covers 10
    session calls instead of a median of 44 at the steps. The idle gap then falls to 5/31 = 0.161 at the steps
    against 20/248 = 0.081 at the controls (diff +0.081) on B ∪ E, and to 7/35 against 19/244 (+0.122) on the
    pooled index. Under that reading two of the three COMPROMISE_LIKE windows (#0, #18) hold no idle gap
    (`step_series_listing[*].idle_gap_session_call_window_post_hoc`). The association lives in long windows that
    span a pause, not at the step call itself.
  - All three COMPROMISE_LIKE series contain an idle gap.
  - A resume-after-idle regime is consistent with a benign cause: cold caches, a different machine load, or a session
    reopened later. It is equally what a mid-session takeover after a pause would look like from the log. The data
    here cannot separate the two.
- **Nulls, stated as prominently.**
  - **Harness changes** do not distinguish step points from random points: version 1/31 vs 2/248, permission mode
    2/31 vs 16/248, hooks 0/31 vs 9/248.
  - **Agent behaviour** does not distinguish them either: parallelism 2/31 vs 21/248, tool mix 24/31 vs 179/248.
  - **Workspace, result size and subagents** do not distinguish them, and all three are slightly *less* common at
    steps.
  - **Compaction** is in the window at 1/31 steps, against 35/248 controls.
- **The instability itself is fragile.**
  - On the fresh split E the step share is 0.081, which the Phase B rule labels STABLE.
  - Eight series near p = 0.01 flip between the two seed indexings.
  - 5 of the 31 steps go between floors that are both below 10 ms (`post_hoc.steps_with_both_Q10_below_10ms`). The
    minimum factor-2 step there is only a few milliseconds.
  - The Phase B UNSTABLE label is therefore a property of B at a seed-sensitive margin as much as of the corpus.
- **What would change this.** More step series would help most. B ∪ E gives 31, just above the minimum, and the
  idle-gap enrichment rests on 18 positives. A covariate the prereg did not include could also explain the shifts, for
  example machine identity or a gap measured across the whole segment rather than in the window. Any such test is post
  hoc and could not raise or lower a verdict here.
