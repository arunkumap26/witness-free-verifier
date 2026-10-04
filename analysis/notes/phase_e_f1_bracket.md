# Phase E F1 + R1: the request-id bracket, its placebo, and the honest failures

**INTERPRETATION.** This file interprets `analysis/out/phase_e/f1_bracket.json`, written by
`analysis/probes/phase_e_f1_bracket.py` (pre-registration: `PREREG_E.md` §1.4 R1 and §1.5 F1; `check_frozen()` passed).
Every number below is in that JSON; section names in brackets point to it. Rates are k/n with a session-clustered 95%
CI unless marked W (Wilson, per stream). cc_local is private: aggregates only.

## Bottom line

1. **Step 0: REPRODUCED.** Committed code reproduces the skeptic's placebo numbers on the same 3,676 streams. The
   Phase C placebo numbers stand. Rank 1 keeps its criterion-(a) lead, and R1 carries no "(Step 0 NOT_REPRODUCED)"
   suffix.
2. **The honest failure rate replicates and stays at about 0.3%.** B is 10/3,676 and the fresh E split is 11/3,332.
3. **No shared benign cause, and the effective FP rate does not fall toward zero.** None of the nine pre-registered
   categories is shared on swechat. Two corrections were adopted on B (restamped_copy, user_input_binding); they remove
   3 of the 10 B failures and **0 of the 11 E failures**. FP_eff on E is 11/3,325 = 0.00331 [0.00145, 0.00551].
4. **What the failures actually are (post hoc, not a verdict).** They come from two mechanisms that no pre-registered
   category covers:
   - out-of-order result writes: 5 of 10 in B, 3 of 11 in E;
   - client clock running behind the server: 1 in B, 6 in E.

   Restamped resume copies account for 3 more in B.
5. **R1 is PENDING_N7** for both units. The ceiling is ALIVE for swechat/claude_code. For cc_local the ceiling is
   WEAK after the dominance check (B only, unreplicated).
   - Not "back-dating only": several other single-response or single-call types clear the honest bar at stream level.
     Adjacent id swap flags 0.954.
   - Blind types: forward-dating, early results, deletions, every shift of 2 s or less, and crude foreign-id splices.

## 1. Step 0 [`step0`]

| check | own count (3,676 streams) | skeptic text (3,673 streams) | rule | pass |
|---|---|---|---|---|
| honest inconsistent | 10 | 10 | 10 ± 3 | yes |
| 5 s back-date | 1,448 = 0.3939 | 1,441 = 0.3923 | within 0.03 (diff 0.0016) | yes |
| 30 s back-date | 3,588 = 0.9761 | 3,581 = 0.9750 | within 0.01 (diff 0.0011) | yes |
| 5 / 30 / 300 s later | 10 / 10 / 10 | 10 | honest ± 3 | yes |
| roll_ids (reference only) | 3,670 | 3,667 | — | — |

- **Stream counts.** The re-implementation counts 3,676 streams, the same as the committed lens. The skeptic text says
  3,673 and the brief 3,674. The gap is reported, not reconciled.
- **Placebo CIs.** These are the first session-clustered CIs for the placebo
  [`units["swechat/claude_code|B"].placebo`]: 5 s 0.3939 [0.3726, 0.4150], 30 s 0.9761 [0.9703, 0.9817], over 1,610
  sessions.

## 2. Honest bracket [`units.*.honest`]

| unit / split | streams | inconsistent | rate [CI] | sessions | consistent slack U−L p50 |
|---|---|---|---|---|---|
| swechat/claude_code B | 3,676 | 10 | 0.00272 [0.00112, 0.00466] | 1,610 | 2,268.5 ms |
| swechat/claude_code E | 3,332 | 11 | 0.00330 [0.00145, 0.00540] | 1,486 | 2,216 ms |
| swechat/claude_code B ∪ E | 7,008 | 21 | 0.00300 [0.00173, 0.00443] | 3,096 | — |
| cc_local B | 847 | 1 | 0.00118 [0, 0.00248]; W [0.00021, 0.00666] | 174 | 1,586.5 ms |

Tolerance sensitivity (streams over the tolerance):

| tolerance | B | E |
|---|---|---|
| 0 s | 18 | 17 |
| 2 s | 10 | 11 |
| 5 s | 7 | 7 |
| 60 s | 2 | 3 |

No threshold was changed.

## 3. The honest failures

### 3a. Pre-registered categories [`units.*.benign`]

Controls are 5 consistent streams per inconsistent stream.

| category | B: inconsistent / controls | E: inconsistent / controls | cc_local: inconsistent / controls |
|---|---|---|---|
| restamped_copy | 3/10 / 1/50 (enrichment 0.28) | 0/11 / 0/55 | 0/1 / 0/5 |
| clock_step | 1/10 / 50/50 | 3/11 / 55/55 | 0/1 / 5/5 |
| user_input_binding | 1/10 / 0/50 | 0/11 / 0/55 | 1/1 / 0/5 |
| concurrent_streams, api_retry, compaction, long_gap, whole_second, vertex_or_bedrock | 0 | 0 | 0 |
| no category | 5 | 8 | 0 |

- **No shared benign cause on swechat.** The rule needs a share of at least 0.5 with enrichment of at least 0.3.
- **clock_step is uninformative as a category.** Every consistent stream is trivially piecewise-consistent, so the
  controls are 50/50 and 55/55.
- **cc_local meets the shared-cause rule on a single stream.** user_input_binding is 1/1 against 0/5 controls.
- **AC1 parser audit.** 10/10 B and 11/11 E inconsistent streams match the raw transcripts on binding stamps and request
  ids, with 0 differences [`r1["swechat/claude_code"].artifact_checks.AC1_parser`]. The failures are in the data, not
  in the parser.

### 3b. Corrections and adoption on B [`units.*.corrections_single`]

swechat/claude_code B; uncorrected: honest 10, 5 s power 0.3939, 30 s power 0.9761.

| correction | honest | 5 s | 30 s | adopted | why not |
|---|---|---|---|---|---|
| restamped_copy (dedupe) | 8 | 0.3934 | 0.9760 | **yes** | — |
| user_input_binding (drop) | 9 | 0.3936 | 0.9755 | **yes** | — |
| clock_step (one change point) | 9 | 0.3319 | 0.8909 | no | 30 s power below 0.90; 5 s power moves more than 0.05 |
| all others | 10 | — | — | no | the honest count does not fall |

- **On E** (not used for adoption), clock_step would lower the honest count from 11 to 8. Its 30 s power is 0.9073, but
  its 5 s power falls to 0.3496 against 0.4151.
- **Why clock-step absorption costs power.** A real client clock step and a back-dated response look the same to the
  bracket.
- **cc_local adopts nothing.** The user_input_binding drop leaves the stream flagged, and clock_step's 30 s power is
  0.8571.

### 3c. Effective false-positive rate [`f1_effective_fp`]

| | honest FP_eff | 5 s power | 30 s power |
|---|---|---|---|
| swechat/claude_code B (adopted set) | 7/3,671 = 0.00191 [0.00057, 0.00349] | 0.3931 | 0.9755 |
| swechat/claude_code **E** (frozen, applied unchanged) | **11/3,325 = 0.00331 [0.00145, 0.00551]** | 1,378/3,325 = 0.4144 [0.3916, 0.4386] | 3,260/3,325 = 0.9805 [0.9753, 0.9853] |
| cc_local B | 1/847 (nothing adopted) | 0.2562 | 0.9008 |

- **Still flagged under the adopted set.** B: 5 with no category, 1 restamped_copy, 1 clock_step. E: 8 with no
  category, 3 clock_step.
- **FP_eff does not fall on the fresh split.** The brief hoped a shared benign cause would bring FP toward zero. That
  did not happen on E.

### 3d. What the failures are: POST HOC, NOT A VERDICT [`units.*.posthoc_mechanisms`, `units.*.benign.inconsistent_streams`]

I inspected the binding events and then classified each failure with a mechanical rule. These descriptors were chosen
after seeing the data. They can explain the failures, but they cannot be adopted as corrections.

| mechanism | B | E | what it is |
|---|---|---|---|
| out_of_order_result | 5 | 3 | The L-binding input is a tool result whose own call is written later in the file, and that call belongs to the very response it binds. In all 8 the input is stamped after the response's first event: by 7–38 ms in 6 cases (4 B, 2 E), by 1,977 ms in one E case and by 7,185 ms in one B case. |
| client_behind_server | 1 | 6 | The U-binding response's first event is stamped 4,094 ms to 8,227,787 ms *before* its id time, so the client clock was behind for part of the stream. 2 of the E cases are two subagent streams of one session. |
| restamped_copy | 3 | 0 | Resume copies; 2 of the 3 carry gaps of 3,516,357 ms and 21,344,792 ms. |
| user_input_binding | 1 | 0 | |
| other | 0 | 2 | |

- **Out-of-order writes.** The out-of-order streams in the transcripts are all Claude Code 2.1.x. My reading is that the
  harness wrote a fast tool's result line before the assistant tool_use line of the same response. It looks like a
  harness write-order artifact, not tampering.
- **Post hoc "ordered inputs" recompute** [`units.*.posthoc_ordered_inputs`]. A result whose own call appears later in
  the file is no longer used as an input.
  - B: 10 → 5, 0.00136 [0.00026, 0.00270]. E: 11 → 8, 0.00240 [0.00063, 0.00422].
  - Placebo power is essentially unchanged: B 5 s 0.3931 and 30 s 0.9761; E 0.4142 and 0.9811.
  - It drops 57 of 194,371 B results and 24 of 180,049 E results.
  - **This is not a pre-registered category, so FP_eff stays as in 3c.** It is the obvious candidate to pre-register
    before the next untouched data (H, or a new corpus).
- **The residue after ordering is mostly real client clock jumps** (6 of 11 on E). The bracket cannot tell those from
  back-dating without losing power.

## 4. R1 [`r1`]

### 4a. Honest leg

Both units are ALIVE-eligible:
- swechat/claude_code B ∪ E: 0.00300 [0.00173, 0.00443];
- cc_local B: 0.00118, CI hi 0.00248.

### 4b. Kill rule at stream level (Phase D rule; bar = honest session-clustered CI hi)

The bar is 0.00443 for swechat/claude_code B ∪ E and 0.00248 for cc_local.

- **30 s back-dating clears.** The F1 placebo flags 6,857/7,008 in swechat/claude_code B ∪ E, CI lo 0.9746. In cc_local
  it flags 763/847, CI lo 0.874. **R1 is not DEAD.**
- **Other single types also clear in swechat/claude_code B ∪ E**, so R1 is not "back-dating only". The same set clears on
  B alone and on E alone (`verdict_per_split`).

  | type | flagged / eligible | rate | CI lo |
  |---|---|---|---|
  | id_swap_adjacent | 6,685/7,008 | 0.9539 | 0.9481 |
  | id_splice_foreign, nearest decoded time | 5,382/7,008 | 0.768 | 0.7544 |
  | time_tail_late 5 s / 10 s | — | 0.6568 / 0.9412 | — |
  | time_result_late 5 s / 10 s (plateau about 0.62 above that) | — | 0.4774 / 0.6235 | — |
  | insert_pair_consistent | 2,498/7,007 | 0.3565 | — |
  | insert_pair_squeezed | 757/6,596 | 0.1148 | — |
  | id_splice_foreign, random | 253/7,008 | 0.0361 | 0.0317 |

- **Back-date grid** (time_response_early, N7 injector, B ∪ E).

  | D | 0.5 s | 1 s | 2 s | 5 s | 10 s | 30 s | 60 s | 300 s |
  |---|---|---|---|---|---|---|---|---|
  | flagged | 21 | 21 | 24 | 0.4051 | 0.8980 | 0.9790 | 0.9922 | 0.9997 |

  - On this grid, power first reaches 0.5 at 10 s and 0.9 at 30 s (`d_grid_summary`). The consistent-stream slack p50 is
    2,268.5 ms.
  - The injector and the F1 placebo agree at 5 s: 2,839 against 2,831 on the same streams.

### 4c. Nulls: types the bracket does not see (swechat/claude_code B ∪ E, against 21 honest)

| type | flagged | why |
|---|---|---|
| time_response_late, 5 / 30 / 300 s | 21 each | forward-dating is invisible by construction |
| time_result_early, every D | 21 | moving an input earlier only loosens the bracket; 5,390–6,967 of 7,007 draws were clamped at call + 1 ms |
| delete_response | 20 | deletion removes constraints (208 streams abstain) |
| delete_pair | 21 | deletion removes constraints (56 abstain) |
| any shift of 2 s or less | — | stays within the honest bar; the largest is time_tail_late 2 s at 32/7,007, CI lo 0.0031 |

- **Crude foreign-id splice is a blind spot.** 6,759 of 7,008 randomly spliced ids decode more than 1 day away from the
  response. `bracket_responses()` drops such ids as implausible, so the tampered response is **silently removed, not
  flagged** (199 streams abstain).
  - The pre-registered 1-day sanity filter therefore converts an obvious splice into a non-event.
  - A detector built on this needs a separate "implausible id" flag.
- **Nearest-time splice.** 790 of 7,008 donors sit within ±2 s of the target id, which is undetectable by design.
- **cc_local.** Random splice flags 8/847, CI lo 0.0046. That clears the clustered bar (0.00248) but not the per-stream
  Wilson bar of 0.00666 (`clears_wilson_bar_sensitivity`). It is the only cell where the choice of bar matters.
  insert_pair_squeezed does not clear in cc_local (56/784, CI lo 0.0).

### 4d. Artifact checks and strata (pooled) [`r1.*.artifact_checks`, `r1.*.strata`]

**swechat/claude_code**

| check | result |
|---|---|
| AC1 | PASS (0/10 B, 0/11 E) |
| AC2 | PASS: still 21 after dropping 4,199 truncated results |
| AC3 | PASS, label unchanged: 21 → 11 when only clean-joined results are inputs (3,019 results dropped). The clean-join rule also drops results written before their call, so this is consistent with 3d; which of the 10 streams it removes was not itemised. |
| AC4 | model dominated (0.809) and user dominated (0.352); every leave-out stays ALIVE-eligible, so pass |
| AC5 | weighted 0.00298 [0.00171, 0.00443], PASS |

Strata: 5 model, 42 repo and 3 length-tercile strata are reportable. No confinement: every reportable stratum is ALIVE
or WEAK, and the WEAK ones are small-n repos.

**cc_local**

| check | result |
|---|---|
| AC1 | NOT_RUN: no raw cc_local file is opened |
| AC2, AC3 | PASS |
| AC5 | NOT_RUN: no population table |
| AC4 | one project holds 0.9988 of the streams and one session holds 0.355; leaving the project out leaves 1 stream, below the minimum n → **capped at WEAK** |

### 4e. Verdict

| unit | label | ceiling before N7 | ceiling after checks |
|---|---|---|---|
| swechat/claude_code (B ∪ E; B and E alone the same) | **PENDING_N7** | ALIVE | ALIVE |
| cc_local (B only, unreplicated) | **PENDING_N7** | ALIVE | WEAK |

- **Why pending.** ALIVE needs at least one single-call or single-response attack type to DETECT on E in the N7
  session-level cells. No `n7_attacks*.json` existed at run time (`n7_outputs_present` is empty).
- **What the stream-level cells suggest.** They make that leg very likely to pass, with id swap at 0.954 per stream.
  They are not N7 cells, though, and are not counted as such.

## 5. Limits

- Every positive is synthetic.
- The request-id clock layout is inferred from data and is UNVERIFIED against provider documentation. A forger who
  re-mints ids defeats the bracket.
- The bracket is one-sided. It does not see forward-dating, early results, deletions, shifts within the roughly 2 s
  slack, or ids more than 1 day off.
- FP_eff on fresh data is about 0.003, not near zero.

## 6. Deviations (also in the JSON `implementation_notes`)

1. **restamped_copy "another session of the corpus".** This was read as the readable corpus: swechat B ∪ E and
   cc_local B. A is calibration-only and H is never read. Copies whose twin is in A or H are missed, which can only
   under-count that benign category.
2. **R1 output location.** R1 lives in `f1_bracket.json` (item f1_bracket), not in a separate `a1_R1.json`.
3. **R1 kill-rule tamper cells are stream-level, using the N7 injectors.**
   - One tamper per stream; target seed `rng_for(attack, param, session, stream)`.
   - The prereg's N7 seeds are per session. The N7 DETECTS leg is left to N7.
4. **Missing stamps in the injectors.** Missing stamps are `pd.NA` in the cache. They were passed to the injectors as
   `None`, so the frozen `atk_insert_pair` takes its own skip path instead of raising. A development run raised on
   cc_local squeezed inserts before this. The injector code is unchanged, and the final run has 0 injector errors
   (`errors` in every cell).
5. **cc_local AC1 NOT_RUN.**
6. **AC4 session axis.** An explicit single-session axis was added to AC4.
7. **Post hoc sections.** `posthoc_mechanisms` and `posthoc_ordered_inputs` were added after inspecting the
   failures. They are labelled post hoc and have no verdict effect.
