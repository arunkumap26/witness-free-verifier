# Probe 3: environment pushback (Phase B)

- **Script:** `analysis/probes/probe_3.py`. Run it with `PYTHONIOENCODING=utf-8 python -m analysis.probes.probe_3`; it
  takes about 31 s.
- **Data:** `analysis/out/probe_3.json`, raw numbers only. Every number below is in that file. Rates are k/n followed by
  the session-clustered bootstrap 95% CI. Session shares use Wilson intervals. s = sessions.
- **Pre-registration:** the script ran under prereg.json sha256 `3189a326…`. It checked that
  `prereg_common.py` sha256 `bb50f690…` equals `provenance.spec_module_sha256` (match: true).
- **Data split:** B only. The aiv_cc overlap count also reads the `session_id` column of `aiv_cc_A.parquet`, because
  `global.aiv_cc_rule` requires it.
- **Phase C:** nothing from Phase C was read.

Sections 1 to 4 report measurements. Section 5 is **interpretation**, marked as such.

## 1. Verdicts (computed mechanically by `prereg.json probe3.verdict`)

The script computed 16 verdict cells (8 units × 2). Every verdict and its deciding number is under
`units.<unit>.verdict`.

| unit | zero-error tail (primary) | deciding number | reaction (secondary) | deciding number |
|---|---|---|---|---|
| swechat/claude_code | **ALIVE** | Z = 9/413 = 0.022 W[0.012, 0.041]; n_long 413 | **WEAK** | effect 0.106 [0.091, 0.121]; CI lo is below 0.10 |
| cc_local | **DEAD** | Z = 15/36 = 0.417 W[0.271, 0.578] | **WEAK** | effect 0.118 [0.038, 0.191] |
| aiv_cc (single-agent case study) | INSUFFICIENT_N | n_long 16 < 20 (Z = 1/16) | **DEAD** | effect −0.230 [−0.343, −0.077] |
| swechat/codex | INSUFFICIENT_N | n_long 11 (Z = 0/11, W hi 0.259) | **DEAD** | effect 0.038 [−0.041, 0.183] |
| swechat/opencode | INSUFFICIENT_N | n_long 7 (Z = 0/7, W hi 0.354) | **WEAK** | effect 0.101 [0.030, 0.206] |
| swechat/gemini (union; small n) | INSUFFICIENT_N | n_long 1 | **DEAD** | effect 0.015 [−0.021, 0.077] |
| aiv_cu (proxy, capped at WEAK) | **DEAD** | Z = 678/988 = 0.686 W[0.657, 0.714] | **WEAK** | effect 0.034 [0.009, 0.058] |
| whowhen/Algorithm-Generated | **WEAK** | Z = 7/27 = 0.259 W[0.132, 0.447] | **DEAD** | effect 0.099 [−0.083, 0.276] |
| swechat/cursor | DEAD (prereg) | 164 calls, 0 results | DEAD | |
| whowhen/Hand-Crafted | DEAD (prereg) | no failure signal; 386 paired calls | DEAD | |
| swechat/simple_text | DEAD (prereg listing) | 0 B sessions | DEAD | |
| swechat/copilot | NOT_TESTABLE | 0 B sessions | NOT_TESTABLE | |

Kill criteria that fired. Each is a DEAD verdict, and that line of work stopped for the unit:
- **Zero-error tail:** cc_local and aiv_cu.
- **Reaction:** aiv_cc, codex, gemini and whowhen AG.

No threshold was changed. The post-hoc numbers in section 3.3 do not revive any of these verdicts.

## 2. Honest baseline: how often environments push back

### 2.1 Per-call error rate (primary definition)

Source: `error_rate_per_call`, `sessions_with_any_primary_error`.

| unit | primary errors / paired calls | rate [CI] | sessions with ≥ 1 error |
|---|---|---|---|
| swechat/claude_code | 7,449 / 194,367 | 0.0383 [0.0360, 0.0408] | 1,137/1,649 = 0.690 W[0.667, 0.711] |
| swechat/codex | 544 / 9,727 | 0.0559 [0.0457, 0.0803] | 40/63 = 0.635 |
| swechat/opencode | 307 / 8,195 | 0.0375 [0.0258, 0.0483] | 77/213 = 0.362 |
| swechat/gemini (union, labelled) | 253 / 1,776 | 0.1425 [0.0841, 0.1783] | 13/21 = 0.619 |
| cc_local | 1,104 / 36,542 | 0.0302 [0.0210, 0.0358] | 30/174 = 0.172 W[0.124, 0.235] |
| aiv_cc | 779 / 38,738 | 0.0201 [0.0106, 0.0308] | 53/119 = 0.445 |
| aiv_cu (proxy) | 1,288 / 59,956 | 0.0215 [0.0194, 0.0236] | 557/1,979 = 0.281 |
| whowhen AG (code_exec) | 54 / 149 | 0.362 [0.280, 0.443] | 41/62 = 0.661 |

**Class breakdown** (`error_rate_per_call.per_class`):
- **swechat CC:**
  - cc_exit_code 3,225 (0.0166)
  - cc_tool_use_error 2,470 (0.0127)
  - unmarked native 1,754 (0.0090)
  - Reported apart: interrupt/reject 662 and permission-denied 30.
- **cc_local:**
  - cc_exit_code 730
  - unmarked 245
  - tool_use_error 129
  - Reported apart: permission-denied 334, in 111 sessions.
- **aiv_cc:**
  - unmarked 532
  - exit_code 202
  - tool_use_error 45
  - The village-bash proxy has 88 hits and is never pooled.
- **codex:** native 449, exit header 95.
- **gemini:** tool_failure 88 (0.0495 [0.0373, 0.0685]) and command_failure 165 (0.0929 [0.036, 0.1349]).

### 2.2 Per-session error rate distribution

Source: `per_session_error_rate`. The JSON also holds linear bins, log10 histograms, and p50/p75/p90 cluster CIs.

| unit | sessions | exactly 0 | p25 | p50 | p75 | p90 | max |
|---|---|---|---|---|---|---|---|
| swechat CC, all | 1,649 | 512 | 0 | 0.0241 | 0.0519 | 0.0882 | 0.5 |
| swechat CC, long (L75) | 413 | 9 | 0.018 | 0.0311 [0.0296, 0.0339] | 0.0508 | 0.0725 | 0.1535 |
| cc_local, all | 174 | 144 | 0 | 0 | 0 | 0.0386 | 0.1333 |
| cc_local, long (L75) | 36 | 15 | 0 | 0.0226 | 0.0381 | 0.0647 | 0.1333 |
| aiv_cc, ≥ 20 calls | 57 | 8 | 0.0034 | 0.0075 | 0.0282 | 0.0636 | 0.1421 |
| aiv_cu, long (L75) | 988 | 678 | 0 | 0 | 0.025 | 0.0714 | 0.35 |
| opencode, all | 213 | 136 | 0 | 0 | 0.0435 | 0.0701 | 0.3333 |
| codex, long | 11 | 0 | 0.0413 | 0.0821 | 0.121 | 0.1693 | 0.1733 |
| whowhen AG, long | 27 | 7 | 0.125 | 0.3333 | 0.4667 | 0.7 | 0.8 |

### 2.3 Zero-error long sessions (the tail)

Source: `zero_error_tail`. E0 is the share expected if errors were independent, at the unit's pooled per-call rate.

| unit | L75 | n_long | zero-error | Z [Wilson] | E0 | Z/E0 | at L90: zero/n_long |
|---|---|---|---|---|---|---|---|
| swechat CC | 134 | 413 | 9 | 0.022 [0.012, 0.041] | 0.00091 | 24.0 | 0/224, W hi 0.017 |
| cc_local | 20 | 36 | 15 | 0.417 [0.271, 0.578] | 0.304 | 1.37 | 0/14 |
| aiv_cc | 666 | 16 | 1 | 0.0625 [0.011, 0.283] | 7.8e-11 | 8.0e8 | 1/9 |
| codex | 120 | 11 | 0 | 0 [0, 0.259] | 6.5e-5 | 0 | 0/9 |
| opencode | 185 | 7 | 0 | 0 [0, 0.354] | 2.7e-5 | 0 | 0/4 |
| gemini | 405 | 1 | 0 | 0 [0, 0.793] | 6.5e-46 | 0 | 0/1 |
| aiv_cu | 40 | 988 | 678 | 0.686 [0.657, 0.714] | 0.414 | 1.66 | 178/292 = 0.610 |
| whowhen AG | 3 | 27 | 7 | 0.259 [0.132, 0.447] | 0.211 | 1.23 | 3/12 |

**swechat CC, the zero-error share by call count** (`zero_error_share_by_ncalls_log2_bin`; observed vs E0 per bin):

| calls | zero-error sessions | share | E0 |
|---|---|---|---|
| 32–63 | 112/356 | 0.315 | 0.173 |
| 64–127 | 50/346 | 0.145 | 0.0375 |
| 128–255 | 10/254 | 0.039 | 0.002 |
| 256–511 | 0/119 | | |
| 512–1023 | 0/55 | | |
| 1024+ | 0/7 and 0/2 | | |

**Who are the zero-error long sessions?** (`zero_error_long_profile`)
- **swechat CC:**
  - The 9 sessions have 136–204 calls (p50 162), against p50 243.5 for long sessions with errors.
  - All 9 contain shell calls.
  - Their shell share of calls is 0.207, against 0.323 for long sessions with errors. Their file_write share is
    0.222, against 0.165.
  - Counting permission/interrupt flags as well, 5/413 long sessions have no native error flag at all.
- **cc_local:**
  - The 15 sessions have 20–30 calls, against p50 98 for long sessions with errors.
  - glob is 0.508 of their calls and shell 0.129. Shell is 0.758 in long sessions with errors.
  - Counting permission denials, 0/36 long sessions are free of native flags.
- **aiv_cc:** the one zero-error long run has 1,771 calls, 0.976 of them `mcp__village__get_events` polls and 0 shell
  calls.
- **aiv_cu:**
  - 352 of the 678 zero-error long sessions contain no shell call. The proxy reads stderr and fires only on shell.
  - Among long sessions with at least one shell call, Z = 326/630 = 0.517 W[0.478, 0.556]. This is descriptive and
    not a verdict.
  - Z by stratum, at the pooled L75 (`aiv_cu_per_stratum`):

    | stratum | zero-error / long | Z |
    |---|---|---|
    | compat-chat | 56/138 | 0.406 |
    | openai-responses | 116/186 | 0.624 |
    | gemini-pro | 142/198 | 0.717 |
    | anthropic-opus | 101/139 | 0.727 |
    | anthropic-sonnet | 127/150 | 0.847 |
    | openai-chat | 18/18 | 1.0 |

### 2.4 Early versus late in a session

Source: `early_late`. Sessions with at least 20 calls, split at floor(n/2). This section is descriptive, with no verdict.

| unit | sessions | early rate | late rate | late − early [CI] | label | errors early only / late only |
|---|---|---|---|---|---|---|
| swechat CC | 1,308 | 0.0395 | 0.0371 | −0.0024 [−0.0056, 0.0009] | stable | 227 / 251 |
| codex | 50 | 0.0555 | 0.0565 | 0.0010 [−0.0146, 0.0165] | stable | 6 / 7 |
| opencode | 135 | 0.0304 | 0.0477 | 0.0173 [0.0044, 0.0325] | **rises** | 1 / 43 |
| gemini (union) | 13 | 0.108 | 0.181 | 0.073 [−0.024, 0.136] | stable | 0 / 1 |
| cc_local | 36 | 0.0300 | 0.0319 | 0.0019 [−0.0038, 0.0121] | stable | 3 / 5 |
| aiv_cc | 57 | 0.0197 | 0.0205 | 0.0008 [−0.0077, 0.0105] | stable | 10 / 11 |
| aiv_cu | 1,500 | 0.0237 | 0.0167 | −0.0070 [−0.0096, −0.0040] | **falls** | 203 / 125 |
| whowhen AG | 0 eligible | | | | | |

The by-decile rates are in `by_position_decile`. For swechat CC they run from 0.0417 (first decile) to 0.0337 (last);
for aiv_cu, from 0.0367 to 0.0148.

## 3. Reaction to failure (retry)

### 3.1 Pre-registered rates

Source: `retry`. A retry is a call to the same tool_key as the previous call in the thread, with identical args or a
token Jaccard of at least 0.5.

| unit | R_fail | R_ok | effect [CI] | exact: R_fail / R_ok |
|---|---|---|---|---|
| swechat CC | 1,435/7,414 = 0.194 [0.180, 0.209] | 15,942/182,652 = 0.087 [0.083, 0.092] | 0.106 [0.091, 0.121] | 0.0101 / 0.0026 |
| cc_local | 251/1,095 = 0.229 [0.201, 0.307] | 3,820/34,267 = 0.111 [0.078, 0.197] | 0.118 [0.038, 0.191] | 0.0237 / 0.0005 |
| opencode | 54/287 = 0.188 | 672/7,697 = 0.087 | 0.101 [0.030, 0.206] | 0 / 0.0003 |
| aiv_cu | 190/1,263 = 0.150 | 6,632/56,714 = 0.117 | 0.034 [0.009, 0.058] | 0.0063 / 0.070 |
| codex | 119/544 = 0.219 | 1,649/9,122 = 0.181 | 0.038 [−0.041, 0.183] | 0.0018 / 0.068 |
| gemini (union) | 11/252 = 0.044 | 43/1,503 = 0.029 | 0.015 [−0.021, 0.077] | 0 / 0 |
| aiv_cc | 81/773 = 0.105 | 12,681/37,848 = 0.335 | −0.230 [−0.343, −0.077] | 0.0078 / 0.253 |
| whowhen AG | 21/41 = 0.512 | 26/63 = 0.413 | 0.099 [−0.083, 0.276] | 0 / 0.016 |

### 3.2 Calls that retry an immediately preceding failed call

Source: `retry_after_fail_share_of_successor_pairs`.

| unit | count | share |
|---|---|---|
| swechat CC | 1,435/190,637 | 0.0075 [0.0069, 0.0083] |
| cc_local | 251/35,693 | 0.0070 |
| opencode | 54/7,984 | 0.0068 |
| codex | 119/9,666 | 0.0123 |
| gemini | 11/1,755 | 0.0063 |
| aiv_cc | 81/38,621 | 0.0021 |
| aiv_cu | 190/57,977 | 0.0033 |
| whowhen AG | 21/104 | 0.202 |

### 3.3 Polling inflates R_ok

The source is `retry.per_tool_key_counts`.
- **aiv_cc:** `mcp__village__get_events` has 18,150 successful calls with a successor, and 11,716 of them are "retries".
  Exact repeats make up 9,561 of the unit's 12,681 R_ok retries.
- **codex:** `write_stdin` contributes 925 of the 1,649 R_ok retries.

A **POST HOC** tool-stratified effect is computed in `post_hoc_tool_stratified_effect`. It was not pre-registered and
feeds no verdict. It compares R_fail with R_ok within the same c_i tool_key:

| unit | tool-stratified effect |
|---|---|
| aiv_cc | 0.048 [0.021, 0.091] |
| swechat CC | 0.092 [0.078, 0.106] |
| cc_local | 0.130 [0.079, 0.199] |
| aiv_cu | 0.081 [0.056, 0.105] |
| codex | −0.015 [−0.155, 0.165] |
| opencode | −0.071 [−0.151, 0.047] |

The rows reported apart are in `rows_apart`:
- swechat CC interrupt/reject: R = 69/542 = 0.127 [0.098, 0.163].
- cc_local permission-denied: R = 6/325 = 0.018 [0, 0.037].

## 4. Population notes

- **B session counts** match `population_B` for every unit (`B_sessions_in_cache_all_rows`). Not every session has a
  paired call. Sessions with paired calls:

  | unit | with paired calls | B sessions |
  |---|---|---|
  | swechat CC | 1,649 | 1,679 |
  | codex | 63 | 77 |
  | cc_local | 174 | 186 |
  | aiv_cc | 119 | 189 runs |
  | aiv_cu | 1,979 | 2,000 |
  | whowhen AG | 62 | 78 |
- **aiv_cc split overlap** (`aiv_cc_split_overlap`): 156 of 189 B runs share an sdk_session_id with an A run. B has 35
  distinct sdk_session_id values and A has 20. aiv_cc B is not held out in content.
- **Long sessions came in below the pre-registered projection** (`thresholds_used.feasibility_projection_probe3_copied_from_prereg`):

  | unit | observed n_long | projected |
  |---|---|---|
  | opencode | 7 | 59.9 |
  | aiv_cc | 16 | 30.2 |
  | codex | 11 | 16.2 |
  | gemini | 1 | 4.4 |
  | whowhen AG | 27 | 24.4 |
  | cc_local | 36 | 42.3 |
  | swechat CC | 413 | 419.8 |
  | aiv_cu | 988 | 990.0 |

  B OpenCode sessions are short: calls per session p50 22, p75 30, against the A-derived L75 of 185.

## 5. Interpretation (not data)

1. **Zero-error tail.** The mechanism works in one unit, swechat Claude Code.
   - Honest Claude Code sessions almost always meet friction once they are long. 69% of all sessions see at least one
     primary error. Of the 413 sessions with at least 134 calls, only 9 (2.2%, CI up to 4.1%) are error-free. Of the
     224 sessions with at least 220 calls, none is.
   - So "a long CC session with zero tool errors" is a usable anomaly flag. Its honest false-positive base rate is
     about 2% at L75 and under 1.7% (upper bound) at L90.
   - Errors clump: Z is 24× the independence expectation, and the per-bin excess grows with session length. Even so,
     the tail empties by about 256 calls.
   - The honest zero-error sessions are near the L75 cut (136–204 calls), lighter on shell and heavier on edits. This
     looks like edit-heavy sessions that never ran a failing command.
   - Caveat: the flag is weak against a fabricator who knows about it. Faking an `Exit code 1` is easy, so this is a
     screen for naive fabrication, not a proof.
2. **cc_local is DEAD on the pre-registered cut.**
   - L75 is only 20 calls there, because most cc_local sessions are short. Its "long" sessions are 20–30-call,
     glob/read-heavy sessions that commonly finish without a failure.
   - At L90 (46 calls), 0/14 are error-free, but that is below the minimum n of 20.
   - Friction in cc_local also shows up as permission denials (334 results in 111 sessions). The prereg keeps these
     out of the primary error class. Counting them, 0/36 long sessions are flag-free.
   - The DEAD verdict reflects the threshold the prereg fixed. It is not evidence that long cc_local sessions are
     friction-free.
3. **aiv_cu is DEAD, and the proxy probably explains much of it.**
   - The proxy can only fire on shell stderr, and 352 of the 678 zero-error long sessions never ran a shell call.
     Sessions are also capped near 40 turns.
   - Even restricted to long sessions with a shell call, Z is 0.517. The stratum spread (0.406 to 1.0) says the
     proxy's sensitivity varies by model family.
   - With no validated error signal, nothing here says computer-use environments are frictionless.
4. **whowhen AG is WEAK, on sessions of 3+ code executions.** Per-call failure is high (0.362), but at 3 to 5 calls per
   session the tail does not empty.
5. **Units with too few long sessions are INSUFFICIENT_N.** codex (0/11), opencode (0/7), gemini (0/1) and aiv_cc (1/16)
   all point the same way as swechat CC: almost no error-free long sessions. They are not interpretable at the
   pre-registered n.
   - The OpenCode shortfall (7 long sessions against a projected 59.9) is a split-composition surprise. B OpenCode
     sessions are much shorter than A's, so the A-derived L75 of 185 leaves almost nothing in B.
6. **Reaction (retry) is at best WEAK everywhere.**
   - Agents do retry more after a failure than after a success. R_fail against R_ok is 0.194 vs 0.087 in swechat CC,
     0.229 vs 0.111 in cc_local, and 0.188 vs 0.087 in opencode. But the margin's CI lower bound stays below 0.10 in
     every unit.
   - Retries of a failed call are under 1.3% of all calls in every CLI unit (whowhen AG: 20%).
   - The aiv_cc DEAD (a negative effect) and the codex DEAD come largely from polling tools: `get_events` and
     `write_stdin` look like "retries" under a same-tool, same-args definition. The post-hoc tool-stratified aiv_cc
     effect is positive (0.048) but still small.
   - As a detector, "no retry after a failure" is not separable from honest behaviour. In swechat CC, R_fail is
     0.194, so most honest failures are not followed by a retry.
7. **Within-session drift.** The error rate does not drift in most units (stable in CC, codex, cc_local and aiv_cc).
   - It rises in OpenCode: errors late but none early in 43 of 135 sessions.
   - It falls in aiv_cu: the first decile is 0.0367 and the last 0.0148.
   - "Errors early, then none" is common in honest CC sessions (227/1,308). It is not an anomaly.

## 6. Deviations from the pre-registration

These are also in the JSON under `deviations`.
1. **Output path.** The output is `analysis/out/probe_3.json`, as the task specification says, not
   `analysis/out/phase_b/probe_3.json`. The content contract is kept. No verdict effect.
2. **Gemini.** Per-call rates are reported per class. The union per-call rate appears once, labelled, and serves only
   as p in E0 and in the union early/late row. No verdict effect.
3. **simple_text.** It is recorded as DEAD, as `prereg.json probe3.units.dead` lists it. PREREG.md section 0 calls it
   NOT_TESTABLE (0 B sessions). The label differs; no number depends on it.
4. **Retry successors.** The successor c_{i+1} ranges over all calls of the thread, paired or not, which is the
   literal SPEC text. The A feasibility count used paired calls only. The number of successors without a result is
   reported, for example 264 of 190,637 in swechat CC. No expected verdict effect.

## 7. Limits

- **aiv_cc** is one agent, and its B split is not content-held-out (156/189 runs).
- **aiv_cu** errors are an unvalidated proxy.
- **Gemini** uses the union of two classes that were never validated together.
- **The CC "unmarked" class** (native error with no text marker; 1,754 results in swechat CC) is counted as primary, as
  the prereg defines it. Its content was not inspected here.
- **Post-hoc numbers** (the tool-stratified effect, long sessions with a shell call, the zero-share-by-length bins, and
  the zero-error profiles) are descriptive only.
