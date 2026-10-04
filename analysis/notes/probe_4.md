# Probe 4 (Phase B): entropy and incidental detail

Every number below is in `analysis/out/probe_4.json`, written by `analysis/probes/probe_4.py`. An identical copy is at
`analysis/out/phase_b/probe_4.json`, the path the prereg output contract names. The script ran on split B only. It
opened split A for one thing: a count-only check that its extraction reproduces the calibration (§0). Notation:
rate [95% CI] (k/n); s = sessions (aiv_cc: runs). CIs are session-clustered bootstraps (`lib/stats.py`), 1,000 draws,
seed 20261003. Sections marked **Interpretation** are not data.

## 0. Provenance and instrument checks

- **Prereg check.** sha256 of `prereg_common.py` is `bb50f690…6947`, equal to `prereg.json`
  `provenance.spec_module_sha256` (`provenance.spec_sha_ok`). The script also checks the calibration script, because
  it imports that script's `digit_test_ci`, the CI routine that produced `resolved.probe4.control_A`
  (`provenance.calibration_sha_ok`).
- **Thresholds**, all read from `prereg.json` (`thresholds_used`):
  - N_min = 1,131 symbols;
  - instrument ceiling = 0.15;
  - ALIVE w_adj = 0.15;
  - round-number margin = 0.05;
  - round-number minimum = 100 distinct values from 10 sessions.
- **Extraction check on A.** Run on split A, the extraction reproduces every class count in `prereg_calibration.json`
  exactly, in every unit: distinct tokens, symbols, sessions, integer values and git-call counts
  (`implementation_check_A.mismatches` = []). No digit test or round share of any class was computed on A.
- **Machine control.** M_git is uniform wherever it is large. In swechat/claude_code it has 139,967 symbols over
  978 s, w_adj 0.002, CI hi 0.016. Its CI hi is 0.034 in aiv_cu, 0.067 in codex and opencode, and 0.102 in aiv_cc.
  M_all is not always uniform:
  - swechat/gemini M_all: w_adj 0.166 [0.101, 0.458] (2,160 symbols, 12 s);
  - whowhen M_all: 0.118 [0.096, 0.177] (4,235 symbols, 38 s).

  Both would fail the instrument check. Neither verdict reaches that step, because T_orig is below N_min first.

## 1. Verdicts (computed mechanically; `verdict_table`, `units.<u>.verdicts`, `pooled.<cell>.verdicts`)

There are 26 verdict cells (`n_verdict_cells`). **No kill criterion fired.** No reachable control failed the
instrument check.

**Hex, primary.** ALIVE needs T_orig w_adj ≥ 0.15 and its CI lo above the control's CI hi. WEAK needs only the point
above the control's CI hi.

| cell | verdict | T_orig symbols / tokens / s | T_orig w_adj [CI] | control (symbols, s) | control w_adj, CI hi |
|---|---|---|---|---|---|
| swechat/claude_code | **WEAK** | 1,868 / 161 / 71 | 0.110 [0.041, 0.232] | M_git (139,967, 978) | 0.002, 0.016 |
| swechat/codex | **INSUFFICIENT_N** | 64 / 1 / 1 | not computed | M_git (7,289, 43) | 0.000, 0.067 |
| swechat/opencode | **INSUFFICIENT_N** | 47 / 2 / 2 | not computed | M_git (8,804, 148) | 0.012, 0.067 |
| swechat/gemini (small n) | **INSUFFICIENT_N** | 0 / 0 / 0 | n/a | M_all (2,160, 12) | 0.166, 0.458 |
| swechat/cursor (small n; control missing) | **INSUFFICIENT_N** | 0 / 0 / 0 | n/a | none (0 results) | n/a |
| cc_local | **INSUFFICIENT_N** | 175 / 22 / 10 | not computed | M_all (36,906, 20) | 0.024, 0.132 |
| aiv_cc (single-agent case study) | **INSUFFICIENT_N** | 137 / 18 / 6 | not computed | M_git (6,004, 23) | 0.024, 0.102 |
| aiv_cu | **WEAK** | 10,997 / 1,142 / 192 | 0.093 [0.043, 0.216] | M_git (45,281, 630) | 0.017, 0.034 |
| whowhen | **INSUFFICIENT_N** | 32 / 1 / 1 | not computed | M_all (4,235, 38) | 0.118, 0.177 |
| swechat/* (pooled) | **WEAK** | 1,972 / 163 / 73 | 0.105 [0.052, 0.220] | M_git (156,783, 1,179) | 0.004, 0.015 |
| public/* (pooled) | **WEAK** | 13,131 / 1,323 / 272 | 0.083 [0.046, 0.169] | M_git (207,246, 1,828) | 0.004, 0.013 |
| swechat/copilot, swechat/simple_text | **NOT_TESTABLE** | 0 B sessions | | | |

**Round numbers, secondary.** The verdict compares the T_orig last-digit-0 share with M_all. ALIVE needs the T_orig CI
lo above the M_all CI hi + 0.05.

| cell | verdict | T_orig last-0 (k/n, s) | M_all last-0 (k/n, s) |
|---|---|---|---|
| swechat/claude_code | **ALIVE** | 0.423 [0.334, 0.520] (127/300, 130) | 0.116 [0.110, 0.122] (2,365/20,419, 1,141) |
| swechat/codex | **INSUFFICIENT_N** (31 values < 100) | 0.935 [0.879, 1.000] (29/31, 13) | 0.123 [0.111, 0.159] (352/2,872, 54) |
| swechat/opencode | **INSUFFICIENT_N** | 16/23 (11 s) | 0.318 [0.195, 0.456] (91/286, 45) |
| swechat/gemini | **INSUFFICIENT_N** | 1/1 | 0.154 [0.105, 0.180] (101/657, 17) |
| swechat/cursor | **INSUFFICIENT_N** | 4/8 (3 s) | no results |
| cc_local | **ALIVE** | 0.648 [0.435, 0.786] (221/341, 14) | 0.121 [0.110, 0.130] (2,243/18,550, 28) |
| aiv_cc | **INSUFFICIENT_N** (42 values) | 0.619 [0.444, 0.826] (26/42, 14) | 0.109 [0.099, 0.120] (284/2,597, 67) |
| aiv_cu | **WEAK** (CI lo 0.133 is not > 0.152 + 0.05) | 0.191 [0.133, 0.293] (740/3,866, 294) | 0.128 [0.113, 0.152] (3,000/23,506, 801) |
| whowhen | **INSUFFICIENT_N** | 4/9 (6 s) | 0.105 [0.061, 0.164] (20/190, 41) |
| swechat/* (pooled) | **ALIVE** | 0.438 [0.353, 0.531] (141/322, 145) | 0.118 [0.112, 0.124] (2,777/23,570, 1,239) |
| public/* (pooled) | **WEAK** | 0.203 [0.146, 0.298] (844/4,148, 430) | 0.120 [0.112, 0.129] (5,581/46,594, 2,108) |

**Caps.**
- The redaction rerun (§4) gave the same label as the main run in every swechat and pooled cell where a cap could
  apply, so no verdict was capped.
- Every aiv_cc verdict carries the label "single-agent case study". In B, 189 runs come from 35 distinct SDK sessions,
  and 156 of the 189 runs share an SDK session with an A run (`aiv_cc_rule`). Only 155 of the 189 runs contain any
  model-visible event (`units.aiv_cc.sessions`, `sessions_B_observed.aiv_cc`).

## 2. Surface: does the mechanism have anything to work on? (`units.<u>.census`)

The table shows the share of tool results that carry at least one valid hex token (length 7/8/32/40/64, UUIDs masked,
REDACTED runs dropped), a `large_int`, or an ISO/epoch timestamp.

| unit | results (s) | any of the three | hex | large int | timestamp | calls with model-originated hex |
|---|---|---|---|---|---|---|
| swechat/claude_code | 194,371 (1,649) | 0.150 [0.143, 0.158] | 0.072 [0.068, 0.076] | 0.085 [0.080, 0.090] | 0.034 [0.029, 0.038] | 170/194,652 = 0.00087 [0.00062, 0.00116] |
| swechat/codex | 9,727 (63) | 0.392 [0.274, 0.447] | 0.128 [0.111, 0.155] | 0.274 [0.137, 0.350] | 0.132 [0.092, 0.174] | 2/9,801 |
| swechat/opencode | 8,195 (213) | 0.246 [0.200, 0.301] | 0.138 [0.103, 0.185] | 0.126 [0.105, 0.152] | 0.087 [0.070, 0.106] | 28/8,199 |
| swechat/gemini | 1,776 (21) | 0.314 [0.244, 0.361] | 0.054 [0.042, 0.080] | 0.307 [0.239, 0.353] | 0.012 [0.007, 0.022] | 0/1,776 |
| swechat/cursor | 0 (no results in the source) | n/a | n/a | n/a | n/a | 0/164 |
| cc_local | 36,542 (174) | 0.224 [0.177, 0.263] | 0.020 [0.018, 0.027] | 0.181 [0.133, 0.209] | 0.062 [0.033, 0.089] | 19/36,542 |
| aiv_cc | 38,738 (119) | 0.825 [0.769, 0.871] | 0.082 [0.060, 0.109] | 0.184 [0.132, 0.262] | 0.801 [0.740, 0.855] | 12/38,746 |
| aiv_cu | 59,956 (1,979) | 0.160 [0.150, 0.170] | 0.089 [0.083, 0.096] | 0.100 [0.093, 0.108] | 0.033 [0.029, 0.037] | 560/59,956 = 0.0093 [0.0078, 0.0112] |
| whowhen | 535 (95) | 0.482 [0.394, 0.561] | 0.247 [0.177, 0.323] | 0.411 [0.325, 0.496] | 0.073 [0.045, 0.101] | 1/595 |

- **Where the fields come from.** By tool (`census.results_by_tool`), hex sits almost entirely in shell output:
  - swechat CC: shell 0.179 [0.169, 0.190] of 61,036 results, read 0.025 [0.021, 0.028], edit 0.007, grep 0.003,
    glob 0.005;
  - aiv_cu: shell 0.212 [0.199, 0.225], and the 26,983 GUI results carry none;
  - aiv_cc: the near-universal timestamp comes from `mcp__village__get_events` (0.999 of 18,239 results).
- **Hex per result is small.** Among swechat CC results that carry hex, the count per result is p50 2, p95 13
  (13,955 results; `census.hex_tokens_per_result.given_any`). Other units: aiv_cu p50 3, p95 13; opencode p50 2,
  p95 22; cc_local p50 2, p95 15; aiv_cc p50 2, p95 8.

**Interpretation.**
- In the largest unit, only 0.150 of tool results carry any of these fields, and 0.072 carry hex. A result that has
  hex usually has two tokens (p50 2, p95 13).
- The digit test needs 1,131 symbols to detect w = 0.15. That is far more hex than one fabricated result would
  carry.
- So the hex digit test can only describe a pooled class, or a long session at best. It cannot flag a single result.
- Models also originate hex rarely: a share of 0.00087 of swechat CC calls carry it, and 0.0093 of aiv_cu calls. That rarity is
  itself the main finding for the hex mechanism.

## 3. Hex: machine control versus model-typed (`units.<u>.hex.main`)

- **Where the test runs at all.** T_orig crosses N_min only in swechat/claude_code (1,868 symbols), aiv_cu (10,997)
  and the two pooled cells.
  - The prereg projected otherwise (`prereg_reference.feasibility_projection_p4`). For claude_code it projected 931.3
    symbols; B gave 1,868.
  - For opencode it projected 1,369.6; B gave 47.
  - For aiv_cu it projected 26,800; B gave 10,997.
- **Size of the deviation.** In each of these cells the T_orig deviation from uniform is detectable above the machine
  control. Each CI lo exceeds the control's CI hi: claude_code 0.041 vs 0.016, aiv_cu 0.043 vs 0.034, swechat/*
  0.052 vs 0.015, public/* 0.046 vs 0.013. The point estimates, 0.083 to 0.110, are below the pre-registered effect
  size of 0.15. Hence WEAK, not ALIVE.
- **Shape of the deviation** (`observed_symbol_counts` vs `expected_symbol_counts`).
  - swechat CC T_orig: low digits are over-represented ('0' 131, '1' 137, '2' 141 against 115.5 expected each) and
    '5' is short (87 against 115.5).
  - aiv_cu T_orig: '0' is over-represented, 908 against 679.0.
  - The descriptive top tokens (public units only, `examples_descriptive.T_orig_top`) contain sequential
    placeholders in swechat CC (`abc1234` ×12, `abcd1234` ×5, `aaa1111` ×5). They sit next to many tokens that look
    like real hashes.
- **Assistant text, descriptive only** (no verdict uses it).
  - aiv_cu A_orig: w_adj 0.390 [0.203, 0.627] (1,315 symbols, 84 s).
  - public/* A_orig: 0.218 [0.133, 0.370] (2,571 symbols).
  - swechat CC A_orig: 0.099 [0.085, 0.244] (1,133 symbols, 55 s).
- **Copied classes.** T_copy (swechat CC 0.063 [0.048, 0.093]) and A_copy (0.000 [0.000, 0.049]) sit near the
  machine control, as they should if they are copies.

**Interpretation.**
- "Model-originated" here means "not visible earlier in the session's record". The class mixes invented placeholders
  with real values the model got from outside the record:
  - earlier sessions or runs (aiv_cc and aiv_cu have no memory or prompt in the IR);
  - recall: aiv_cu T_orig contains `e3b0c442`, the 8-character prefix of sha256("");
  - hashes of lengths the token filter drops, such as a 7-character prefix of a 9–12-character hash shown in a
    result, which then cannot count as a copy.

  The real values are uniform and dilute the signal. The measured w_adj is therefore a lower bound on how
  non-uniform invented hex is.
- Even so, the effect is modest and needs pooled classes to see. As a per-result detector, the hex mechanism is not
  supported by these data.

## 4. Redaction handling (swechat; `units.<u>.counts`, `verdicts.*.redaction_rerun`)

- **Pre-mask.** Hex tokens inside a REDACTED run are dropped: 647 in swechat CC (628 of them from results), 2 in
  opencode, 4 in aiv_cu. Events containing REDACTED in swechat CC: 5,793 results, 3,442 calls, 830 system, 263 user,
  174 assistant. That is 0.030 [0.024, 0.036] of CC results.
- **Rerun on events with no REDACTED at all** (prereg `redaction_sensitivity`). It gives the same label as the main run
  in every cell where a cap could apply:
  - swechat CC hex: WEAK, T_orig 0.134 (1,752 symbols) against control hi 0.016;
  - swechat CC round numbers: ALIVE;
  - swechat/* hex: WEAK, 0.126;
  - public/* hex: WEAK, 0.107;
  - public/* round numbers: WEAK.
- **Stricter variant.** This one also removes REDACTED events from the sourcing antecedents. It gives the same labels:
  swechat CC hex 0.115 on 2,433 symbols, ALIVE for round numbers.
- **Interpretation.** Dropping redacted events moves T_orig w_adj up a little (0.110 → 0.134). That direction fits
  the prereg's worry that redaction removed high-entropy strings. It does not change any label.

## 5. Round numbers (secondary verdict) and what drives them

The prereg verdict is ALIVE in swechat/claude_code, cc_local and swechat/*, and WEAK in aiv_cu and public/* (§1).
The digit-ending details sit under `units.<u>.ints.main.<class>.round`.
- **swechat CC T_orig:** last-00 0.307 [0.220, 0.395] and last-000 0.233 [0.162, 0.301]. M_all: 0.022 [0.018, 0.026]
  and 0.009 [0.006, 0.012]. Under uniform last digits these would be 0.01 and 0.001.
- **Machine output is rounder than uniform.** M_all last-0 is 0.116 in CC, 0.121 in cc_local, 0.128 in aiv_cu and
  0.318 in opencode (cluster-heavy), against 0.1 under uniform.

**Post-hoc descriptive** (added after the verdicts existed; `units.<u>.post_hoc_descriptive`,
`examples_descriptive_ints`; it changed no number above, and run-to-run diffs show only added keys).
- **What the values are.** The most frequent swechat CC T_orig integers are tool timeouts: `120000` ×3,769
  occurrences, `30000` ×2,325, `60000` ×2,127, `300000` ×1,500, `600000` ×846. Codex shows `12000` ×2,332; opencode
  `120000` ×176.
- **By origin.** In swechat CC, T_orig values that come from JSON-number args (parameters) end in 0 at
  0.961 [0.900, 1.000] (49/51, 27 s). Values embedded in arg strings (shell commands, code) end in 0 at
  0.313 [0.213, 0.427] (78/249, 112 s). The cc_local figures are 0.795 (66/83) and 0.601 [0.241, 0.748] (155/258,
  14 s).
- **aiv_cu.** T_orig integers are nearly all in arg strings (3,865 of 3,866) and come almost entirely from shell calls
  (3,817 distinct values). The top values are 8-digit numbers repeated across sessions (`18874380` ×213,
  `84282297` ×172). These look like identifiers carried in from outside the record, not choices.
- **Assistant text** (descriptive): swechat CC A_orig last-0 0.551 [0.381, 0.705] (38/69, 45 s), below the verdict
  minimum of 100 values; aiv_cu A_orig 0.277 [0.219, 0.335] (128/462, 87 s).

**Interpretation.**
- The ALIVE round-number verdicts are real, but they mostly measure that models choose round parameters: timeouts,
  limits, sleeps. That is a property of choices, not of invented measurements.
- Model-typed integers inside strings are still rounder than machine output in CC (0.313 vs 0.116). This is closer
  to the mechanism, but it is post hoc and mixes code constants with any typed "observations".
- Whether a fabricated byte count, PID or duration would be round is not directly tested here. The A_orig class, the
  closest proxy for model-stated quantities, points the same way (0.551 in CC), at n below the verdict minimum.

## 6. Timestamps (pre-registered, no verdict; `units.<u>.timestamps`)

ISO timestamps with seconds equal to `00` (uniform expectation 1/60 ≈ 0.017):

| unit | M_all (results) | T_copy (args, sourced) | T_orig (args, unsourced) |
|---|---|---|---|
| swechat/claude_code | 0.030 [0.023, 0.039] (47,359 values, 612 s) | 0.427 [0.291, 0.571] (199) | 0.842 [0.767, 0.911] (260 values, 90 s) |
| swechat/codex | 0.051 [0.029, 0.139] (2,938) | 0.585 [0.333, 0.808] (41) | 0.605 [0.364, 0.870] (43, 8 s) |
| aiv_cu | 0.048 [0.029, 0.079] (7,331) | 0.118 [0.044, 0.204] (119) | 0.680 [0.388, 0.894] (394, 58 s) |
| cc_local | 0.387 [0.030, 0.664] (3,735, 90 s) | 29/143 (insufficient n: 3 s) | 0.486 [0.000, 0.649] (72, 5 s) |
| aiv_cc | 0.014 [0.010, 0.019] (6,352) | 0/12 | 4/9 |

**Interpretation.**
- Model-typed timestamps sit on the minute far more often than machine stamps do (CC 0.842 vs 0.030). Of all the
  fields tested, this one separates machine from model most cleanly in the large units.
- The machine baseline is not uniform everywhere. cc_local M_all is 0.387, with a CI from 0.030 to 0.664 that shows
  a few sessions dominate; T_copy in CC is 0.427. So the baseline has to be per source, not 1/60.
- This feeds no verdict.

## 7. Exploratory, NOT pre-registered (requested by the task; `units.<u>.exploratory_not_preregistered`)

- **Durations with an all-zero fraction** (e.g. `2.0s`; expectation = mean of 10^-d). Machine output is rounder than
  uniform: CC M_all 0.067 [0.057, 0.078] against 0.027 expected (12,256 values).
  - Model-typed durations show **no excess**: CC T_orig 0.031 [0.000, 0.086] (65 values, 0.078 expected) and A_orig
    0.038 [0.000, 0.072] (158 values, 0.062 expected).
  - cc_local: M_all 0.082 against 0.045 expected; T_orig 0.084 against 0.070.
  - **This is a null for the "durations ending .0" artifact.**
- **ls-style mtimes at minute :00** (1/60 ≈ 0.017 expected). Machine output sits at about the expected rate: CC M_all
  0.014 [0.011, 0.018] (4,581 values); aiv_cu 0.014 (8,317). Model-typed mtimes are too rare to measure: 4 values in
  CC T_orig.
- **"N bytes" ending in 00** (0.01 expected). Machine output: CC 0.037 [0.020, 0.055] (465 values); aiv_cu 0.032
  (603). Model-typed: CC T_orig 6/14, A_orig 4/21. Insufficient n.

## 8. Nulls (same prominence as hits)

1. **Hex is INSUFFICIENT_N in 7 of 9 testable units:**
   - codex 64 symbols, opencode 47, gemini 0, cursor 0, cc_local 175, aiv_cc 137, whowhen 32 (N_min 1,131);
   - models type almost no unsourced hex: 0.00087 of calls in swechat CC, and at most 0.0034 (28/8,199, opencode) in
     any swechat format.
2. **Hex never reaches ALIVE.** Where testable, the model-originated w_adj (0.083–0.110) is below the pre-registered
   effect size of 0.15.
3. **Hex cannot work per result.** A hex-bearing result has a median of 2 tokens, against the 1,131-symbol test
   minimum.
4. **Most tool results carry no hex, large integer or timestamp at all.** The share that carries any is 0.150 in
   swechat CC, 0.160 in aiv_cu, 0.224 in cc_local and 0.246 in opencode. aiv_cc is the exception (0.825 carry one,
   mostly harness event timestamps).
5. **Round numbers are INSUFFICIENT_N** in codex, opencode, gemini, cursor, aiv_cc and whowhen.
6. **Model-typed durations are not rounder than uniform** (exploratory).
7. **Machine-hex instrument** issues, latent behind INSUFFICIENT_N: gemini M_all (CI hi 0.458) and whowhen M_all
   (CI hi 0.177) would fail the 0.15 ceiling.

## 9. Interpretation: what this means for fabrication detection

- **Hex entropy (primary): mostly a null.**
  - The surface is thin: few results carry hex, and fewer calls carry model-originated hex.
  - Where it can be measured, model-originated hex is measurably but only modestly less uniform than machine hex,
    and only in pooled classes.
  - A digit-uniformity check would not flag a single fabricated `git log`. It could at most separate a corpus or a
    long session of invented hashes from real ones.
  - Placeholder-shaped tokens (`abc1234`, `aaa1111`) do occur. A literal pattern check would catch some, but that was
    not pre-registered and was not measured as a detector.
- **Round numbers and timestamps: stronger, but confounded.**
  - Model-typed integers and timestamps are much rounder than machine values (CC: last-0 0.423 vs 0.116; ISO :00
    0.842 vs 0.030).
  - Most of the integer effect is parameter choice (timeouts). The honest baseline for the field a fabricated result
    would carry (byte counts, PIDs, durations, mtimes) is machine output. That output is itself rounder than uniform
    (M_all last-0 0.109–0.318 against 0.1), and the rate varies by source.
  - A usable detector would need per-field machine baselines and enough values per result. The census suggests most
    results have neither.
- **Units.** aiv_cc is a single-agent case study and is INSUFFICIENT_N here anyway. cc_local results are aggregates
  only.

## 10. Deviations and implementation choices (also in the run summary)

1. **Output path.** The prereg contract says `analysis/out/phase_b/<probe>.json`; the task says
   `analysis/out/probe_4.json`. Both are written, byte-identical.
2. **JSON-number integers in args.** The calibration code took `large_int.fullmatch` and did not apply the SPEC's
   epoch exclusion. Phase B uses `pc.large_ints`, which follows the SPEC.
   - Affected: 100 epoch-shaped JSON numbers in swechat CC, 0 elsewhere (`counts.json_number_epoch_excluded`). The
     count was 0 in every unit on A.
3. **Reading of the redaction rerun.** "Events whose text has no REDACTED" is taken as: the strings scanned for that
   event contain no REDACTED. For results that is text and stderr; for calls the raw args; for assistant, user and
   system events, the text.
   - Sourcing still uses the full record. A stricter variant that also drops REDACTED events from the antecedents is
     reported; it gives the same labels.
4. **Redaction cap.** It is applied literally (any differing label gives WEAK). It covers both verdicts and the
   pooled swechat/* and public/* cells, since both contain swechat. It changed nothing.
5. **Classes below N_min.** They get raw symbol counts only, with no chi2 or w_adj (`global.min_n.below_min`). The
   probe4 "statistics" line lists chi2/w_adj per class; the below-min rule was given precedence.
6. **Exploratory patterns (§7) and the post-hoc breakdown (§5).** Both are additions, labelled in the JSON. Neither
   feeds a verdict.
7. **cc_local privacy.** Quantiles of integer values (min/max) are removed for cc_local. Examples are written for
   public units only, and hex examples only for lengths 7/8.

## 11. Limitations

- **"Unsourced" is an upper bound on "invented".** The sourcing record is incomplete: aiv_cc earlier runs, aiv_cu
  memory and system prompt, CC system prompt and compaction. Also, prefix-sourcing only sees earlier tokens of
  lengths 7/8/32/40/64, so a short hash cut from a 9–12-character one counts as T_orig.
- **The tests describe classes pooled over many sessions.** The session bootstrap handles clustering. It does not
  make a pooled-class effect a per-result signal.
- **Probe 4 has no fabricated positive control.** This probe measures how far the honest baseline separates
  model-typed from machine values. It does not measure detection of actual fabrications.
