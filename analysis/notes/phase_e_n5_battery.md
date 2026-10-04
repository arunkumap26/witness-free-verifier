# Phase E, N5 lightweight battery: items a, b, d, e, f

**Data.** `analysis/out/phase_e/n5_battery.json`, written by `analysis/probes/phase_e_n5_battery.py`
(`PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_n5_battery`, 225.6 s, `runtime_s`).

**Scope.** This file covers battery items a (determinism), b (sort order), d (whitespace), e (output-size distribution) and
f (error-message fidelity). Items c (truncation boundary) and g (cold start) are not part of this item
(`items_not_covered`).

**Pre-registration.** `prereg_e.json n5_battery`, run as written apart from the choices in `deviations` (section 8).
- `check_frozen()` passed (`check_frozen`). The JSON records the sha256 of `prereg_e.json` and of `prereg_e_common.py`.
- Extraction follows the calibration's code path (`prereg_e_calibration.cal_n5`). The frozen helpers do the work:
  `determinism_pairs`, `mask_volatile`, `ls_order_violation`, `gitlog_order_violation`, `grepn_order_violation`,
  `ws_violations`, `normalize_ws`, `error_fidelity_checks`, the `atk_digit` / `atk_reorder_lines` injectors, and the
  artifact-check helpers.
- No threshold was changed. Every verdict is the mechanical rule of `S:n5_battery.*.verdict`.
- **Run history.** The final JSON is from the fourth full run. Runs 2 to 4 fixed the order of the JSON path strings
  (`deciding_path`) and added summary fields (`n6_cells`, `BE_pooled_not_the_cell`). The measurement code, seeds and
  every number were unchanged across runs.
- **Post hoc diagnostics.** Before the first full run I ran the script on subsets of B/E (≤ 120 sessions per unit and
  split) and inspected drifting and violating outputs for parser defects. That inspection led me to add the descriptive
  blocks marked `post_hoc_not_a_verdict`. The item-cell rule for b/d (deviation 2) was written before any data was read.

**Conventions.**
- k/n = rate [95% session-clustered CI], then s = sessions (aiv_cc: runs).
- A zero numerator also carries the per-event Wilson upper bound. The ALIVE rule uses that bound (global rule).
- Splits: B; E (swechat and aiv_cu only; E is the replication); B ∪ E pooled, which is the artifact-check population.
- **The N6 cell** is the E verdict where E exists and is not INSUFFICIENT_N, else the B verdict ("B only"). Artifact
  checks can only lower it.
- Sections 1 to 7 report data. **Section 9 is interpretation.** Every number below is in the JSON, rounded. Paths:
  - `units.<unit>.results.<item>.<split>` for a, e, f;
  - `units.<unit>.results.<item>.per_checker.<checker>.<split>` for b and d;
  - `units.<unit>.cells.<row>` and `n6_cells.<unit>.<row>` for cells.
- 210 verdict blocks were computed (`cells_computed`). No family-wise correction was applied.

**Labels.** cc_local is *private*: aggregates only, with cluster and family names replaced by indices. B only,
unreplicated. aiv_cc is a *single-agent case study*, B only, unreplicated. whowhen is B only.

---

## 1. N6 cells (`n6_cells`)

| unit | N5a determinism | N5b sort | N5d whitespace | N5e size | N5f error fidelity |
|---|---|---|---|---|---|
| swechat/claude_code | **DEAD** (E drift 0.281) | **DEAD** (ls; grep_n WEAK, git_log INSUFFICIENT_N) | **DEAD** (pytest_banner; git_status_tab **ALIVE**, ls_long WEAK, wc WEAK) | **WEAK** (E 42/47 families) | INSUFFICIENT_N (28 frames, 3 s on B; 7 frames on E) |
| swechat/codex | INSUFFICIENT_N (7 pairs) | DEAD (grep_n E 0.051) | INSUFFICIENT_N | DEAD (E 2/9; checks also fail) | NOT_TESTABLE (no numbered Read results) |
| swechat/opencode | INSUFFICIENT_N (1 pair B, 4 E) | INSUFFICIENT_N | INSUFFICIENT_N | DEAD (E 1/3) | NOT_TESTABLE (no numbered Read results) |
| swechat/gemini | INSUFFICIENT_N (4 pairs) | INSUFFICIENT_N | INSUFFICIENT_N | INSUFFICIENT_N (0 qualifying families on B and E) | NOT_TESTABLE (no numbered Read results) |
| swechat/cursor | NOT_TESTABLE (no tool results) | NOT_TESTABLE | NOT_TESTABLE | NOT_TESTABLE | NOT_TESTABLE |
| swechat/copilot, simple_text | NOT_TESTABLE (no sessions in B or E) | same | same | same | same |
| cc_local (private, B only) | INSUFFICIENT_N (234 pairs, 6 s) | DEAD (ls 0.639) | DEAD (ls_long 0.289) | **DEAD** (WEAK before checks; CONFINED) | INSUFFICIENT_N (4 frames) |
| aiv_cc (single agent, B only) | INSUFFICIENT_N (2 pairs) | INSUFFICIENT_N | INSUFFICIENT_N | **WEAK** (4/6 families) | INSUFFICIENT_N (0 frames) |
| aiv_cu | INSUFFICIENT_N (5 pairs B, 3 E) | DEAD (ls E 0.280, grep_n E 0.123) | DEAD (pytest_banner 0.879; ls_long WEAK before checks, then DEAD by AC4) | **WEAK** (E 10/10 families) | NOT_TESTABLE (no numbered Read results) |
| whowhen (B only) | NOT_TESTABLE (no shell commands, no Read results) | NOT_TESTABLE | NOT_TESTABLE | NOT_TESTABLE | NOT_TESTABLE |

- **Item cells for b and d** take the lowest final label among the checkers that have an ALIVE/WEAK/DEAD cell
  (deviation 2). Every checker label is listed in `n6_cells.<unit>.<row>.per_checker_final`.
- **No N5 item cell is ALIVE.** The only ALIVE label is one checker, swechat/claude_code d git_status_tab, and it sits
  inside a DEAD item cell.
- **Outside swechat/claude_code, the only cells above DEAD are N5e WEAK** in aiv_cu (replicated on E) and in aiv_cc
  (single agent, B only). In swechat/claude_code, N5e is WEAK as well.

## 2. Item a: repeat-command determinism (`results.a`)

The statistic is drift: a determinism pair whose two results differ after `mask_volatile()`.

| unit | split | pairs | drift | byte-identical (unmasked) | verdict |
|---|---|---|---|---|---|
| swechat/claude_code | B | 2,146, 348 s | 640/2,146 = **0.298** [0.206, 0.402] | 1,506/2,146 = 0.702 | DEAD |
| swechat/claude_code | E | 1,745, 335 s | 491/1,745 = **0.281** [0.188, 0.389] | 1,254/1,745 = 0.719 | DEAD |
| swechat/claude_code | B ∪ E | 3,891, 683 s | 1,131/3,891 = 0.291 [0.220, 0.371] | 2,760/3,891 = 0.709 | DEAD |
| cc_local | B | 234, **6 s** | 3/234 = 0.013 [0.002, 0.059] | 231/234 | INSUFFICIENT_N (< 20 s) |
| swechat/codex | B / E | 7 (4 s) / 5 (4 s) | 6/7 / 5/5 | 0/7 / 0/5 | INSUFFICIENT_N |
| swechat/opencode | B / E | 1 / 4 | 0 / 0 | 1/1 / 4/4 | INSUFFICIENT_N |
| swechat/gemini | B / E | 4 / 0 | 3/4 / — | 1/4 | INSUFFICIENT_N |
| aiv_cc | B | 2 | 1/2 | 1/2 | INSUFFICIENT_N |
| aiv_cu | B / E | 5 / 3 | 1/5 / 0/3 | 4/5 / 3/3 | INSUFFICIENT_N |

- **Coverage.** The A split had already projected this (A pairs: swechat CC 89 in 27 s; cc_local 15 in 1 s; others
  ≤ 4; `A_split_eligibility_context`).
  - Only swechat/claude_code reaches the 100 pairs / 20 sessions minimum.
  - In swechat/claude_code, 3,717 of the 3,891 B ∪ E pairs are repeated Reads of the same path / offset / limit, and
    174 are read-only shell commands (`drift_by_key`).
- **Positive control** (`atk_digit` on the second result; a pair without a digit abstains as not flagged). Recall:
  - B: 2,030/2,146 = 0.946 [0.917, 0.969];
  - E: 1,662/1,745 = 0.952 [0.934, 0.968];
  - on honest non-drifting E pairs: 1,225/1,254 = 0.977;
  - abstentions (no digit): 114 on B, 83 on E.
- **Post hoc, NOT a verdict** (`post_hoc_not_a_verdict`). Swechat/claude_code honest drift is concentrated in two groups
  of pairs (B ∪ E):
  - **The n1 key contains the dataset redaction marker:** 441 of 453 such pairs drift. SWE-chat replaces path segments
    with the bare token `REDACTED`. Distinct files then share one key, so the pair is not a repeat at all.
  - **Either result is a primary error** (for example a sibling-call error stub followed by real output): 674 of 733
    pairs drift.
  - **Pairs in neither group** drift at 46/2,739 = 0.017 [0.010, 0.025], 554 s. By split: B 21/1,480 = 0.014
    [0.006, 0.026]; E 25/1,259 = 0.020 [0.011, 0.032].
  - This subset was chosen after looking at the data. It does not change the DEAD cell.

## 3. Item b: sort-order violations (`results.b.per_checker`)

| unit | checker | B | E | cell |
|---|---|---|---|---|
| swechat/claude_code | ls | 364/1,672 = 0.218 [0.179, 0.255], 439 s | 277/1,422 = **0.195** [0.160, 0.230], 439 s | DEAD |
| swechat/claude_code | git_log | 0/11, 9 s | 0/19, 5 s | INSUFFICIENT_N (B ∪ E 0/30, 14 s) |
| swechat/claude_code | grep_n | 165/5,010 = 0.033 [0.022, 0.046], 621 s | 89/4,219 = **0.021** [0.013, 0.029], 592 s | **WEAK** (checks pass) |
| swechat/codex | grep_n | 40/647 = 0.062 [0.038, 0.116], 52 s | 27/532 = **0.051** [0.031, 0.067], 40 s | DEAD |
| swechat/codex | ls | 6/11 | 6/10 | INSUFFICIENT_N |
| cc_local | ls | 676/1,058 = **0.639** [0.572, 0.765], 22 s | — | DEAD |
| cc_local | grep_n | 391/2,543, **13 s** | — | INSUFFICIENT_N (< 20 s) |
| aiv_cc | ls / grep_n | 23/71 (12 s) / 1/57 (10 s) | — | INSUFFICIENT_N |
| aiv_cu | ls | 83/271 = 0.306, 157 s | 106/378 = **0.280** [0.222, 0.344], 203 s | DEAD |
| aiv_cu | grep_n | 81/535 = 0.151, 202 s | 64/521 = **0.123** [0.089, 0.159], 204 s | DEAD |
| aiv_cu | git_log | 3/22 | 1/12 | INSUFFICIENT_N (B ∪ E 4/34) |
| opencode, gemini | all | ≤ 9 outputs | ≤ 4 outputs | INSUFFICIENT_N |

- **swechat/claude_code grep_n is WEAK, not ALIVE.** The E rate 0.021 exceeds the 0.01 ALIVE point.
- **Artifact checks on grep_n**, run on B ∪ E (254/9,229 = 0.028 [0.020, 0.036]):
  - AC2 (no truncated) WEAK; AC3 (join clean) WEAK; AC5 (post-stratified) 0.031 [0.024, 0.039] WEAK.
  - AC4: dominated (repo 0.256, user 0.458, model 0.762 of events). The label is stable over all 15 leave-outs.
  - AC1: 0 of 30 audited violating outputs differ from the raw transcripts; the 30-output denominator diagnostic also
    differs in 0 of 30.
  - Strata: tool_key (Grep tool 177/6,054 vs shell 77/3,175), model, repo and length are all OK (not CONFINED).
  - SHIFT: the B point 0.033 lies outside the E CI [0.013, 0.029]. This has no verdict effect.
- **Positive control** (`atk_reorder_lines`, adjacent line swap). Recall on E:
  - swechat CC grep_n 3,615/4,219 = 0.857 and ls 1,180/1,422 = 0.830;
  - codex grep_n 326/532 = 0.613;
  - aiv_cu grep_n 409/521 = 0.785;
  - git_log 0/30 on swechat CC B ∪ E. Swapping a `Date:` line with its neighbour does not reorder the dates, so this
    control cannot test git_log.
- **Post hoc, NOT a verdict: a defect in the frozen grep -n parser.**
  - The `grep_n_line` regex has a lazy path group that splits hyphenated file names at `-NN-`. For example, a file named
    `step-04-x.md` is read as path `step` and line 04.
  - Re-parsing with a ':'-only path (match lines only, `colon_only_match_lines`) gives these counts:

    | unit | frozen-checker violations | violations under the ':'-only parse | eligible outputs |
    |---|---|---|---|
    | swechat CC (B ∪ E) | 249 | 55 | 8,155 |
    | codex (B ∪ E) | 66 | 49 | 1,170 |
    | aiv_cu (B ∪ E) | 140 | 110 | 987 |

  - In swechat CC, one repo stratum (a repo whose files are named `step-NN-*.md`) violates at 0.460 (289 outputs, 54 s;
    `stratification.repo`).

## 4. Item d: whitespace / formatting fingerprints (`results.d.per_checker`)

| unit | check | B | E | cell |
|---|---|---|---|---|
| swechat/claude_code | git_status_tab | 0/1,110 (Wilson hi 0.0034), 635 s | **0/1,096** (Wilson hi 0.0035), 654 s | **ALIVE** (checks pass) |
| swechat/claude_code | ls_long_alignment | 66/1,338 = 0.049 [0.024, 0.077], 346 s | 31/1,035 = **0.030** [0.019, 0.044], 347 s | WEAK (checks pass) |
| swechat/claude_code | wc_alignment | 4/138 = 0.029, 78 s | 2/113 = **0.018** [0, 0.047], 72 s | WEAK (AC4 UNTESTABLE_WITHOUT_DOMINANT, cap only) |
| swechat/claude_code | pytest_banner | 634/1,063 = 0.596, 226 s | 383/831 = **0.461** [0.349, 0.573], 182 s | DEAD |
| aiv_cu | ls_long_alignment | 10/223 = 0.045, 131 s | 14/320 = 0.044 [0.023, 0.067], 162 s | WEAK, then **DEAD** (AC4 DOMINATED) |
| aiv_cu | git_status_tab | 0/95, 74 s | 0/98, 76 s | INSUFFICIENT_N (< 100 each; B ∪ E 0/193, 150 s, is not a cell) |
| aiv_cu | wc_alignment | 11/52 | 21/58 | INSUFFICIENT_N (B ∪ E 32/110 = 0.291, not a cell) |
| aiv_cu | pytest_banner | 1,236/1,403 = 0.881 | 1,076/1,224 = 0.879, 318 s | DEAD |
| cc_local | ls_long_alignment | 322/1,114 = **0.289** [0.129, 0.363], 69 s | — | DEAD |
| cc_local | wc / pytest / git status | 334 outputs in 5 s / 1,673 in 18 s / 2 | — | INSUFFICIENT_N (sessions) |
| aiv_cc | all | ls_long 55 (13 s), git_status 30, pytest 31 | — | INSUFFICIENT_N |
| codex, opencode, gemini | all | ≤ 82 outputs | — | INSUFFICIENT_N |

- **swechat/claude_code git_status_tab is the only ALIVE checker in this item.** Its checks:
  - AC2 and AC3 ALIVE; AC5 0/2,206 ALIVE.
  - AC4: dominated by user 0.324 and model 0.799, but every leave-out stays ALIVE.
  - AC1: the numerator is empty. The diagnostic audit of 30 denominator outputs found 0 differing.
  - Strata: model, repo and length are OK. Two repo strata are WEAK only because their Wilson bound exceeds 0.03 at
    about 100 outputs.
  - The positive control (`normalize_ws`, tab → 4 spaces) is caught in 2,206/2,206 outputs, which holds by construction.
- **aiv_cu ls_long_alignment loses its WEAK under AC4.**
  - One agent (one model) holds 0.319 of the outputs.
  - Leaving that agent out gives 0.057, which is DEAD.
  - AC1 is NOT_RUN for aiv_cu (no committed raw reader).
- **Positive control on swechat CC E:** ls_long_alignment 970/1,035 = 0.937; wc_alignment 89/113 = 0.788.
  - pytest_banner: 0/448 on honest-clean outputs. `normalize_ws` only collapses runs of spaces and tabs, and banners
    contain none, so the control cannot touch them.
- **Post hoc, NOT a verdict.** The frozen `pytest_banner` regex `^=+ .+ =+$` also matches the `=== section ===` lines
  that agents echo. Among swechat CC B ∪ E outputs whose command mentions pytest, 4/631 violate; among the rest,
  1,013/1,263 violate (`command_mentions_pytest`).

## 5. Item e: output-size distribution (`results.e`; capped at WEAK)

The statistic is the IQR of log10(bytes + 1) per command family (≥ 100 results from ≥ 10 sessions), compared with the
IQR of model-generated text. "Above" means the family's IQR point exceeds the comparator's CI hi.

| unit | split | families above / qualifying | comparator IQR [CI] (texts, s) | verdict |
|---|---|---|---|---|
| swechat/claude_code | B | 43/50 = 0.86 | 0.604 [0.582, 0.630] (73,283, 1,670 s) | WEAK |
| swechat/claude_code | E | **42/47 = 0.894** | 0.605 [0.589, 0.628] (67,014, 1,537 s) | WEAK |
| swechat/claude_code | B ∪ E | 66/80 = 0.825 | 0.609 [0.590, 0.623] | WEAK |
| aiv_cu | B | 10/10 | 0.389 [0.374, 0.398] (36,509, 1,640 s) | WEAK |
| aiv_cu | E | **10/10** | 0.385 [0.371, 0.395] (36,267, 1,626 s) | WEAK |
| aiv_cc | B | 4/6 = 0.667 | 0.364 [0.344, 0.389] (16,352, 149 runs) | WEAK |
| cc_local | B | 10/12 = 0.833 | 0.416 [0.372, 0.685] (6,807, 186 s) | WEAK, then **DEAD** (CONFINED) |
| swechat/codex | B / E | 5/9 / **2/9 = 0.222** | E 0.372 [0.241, 0.831] | WEAK / DEAD |
| swechat/opencode | B / E | 1/4 / 1/3 | E 0.776 [0.416, 1.007] | DEAD / DEAD |
| swechat/gemini | B / E | 0 qualifying / 0 qualifying | — | INSUFFICIENT_N (B ∪ E 0/2 = DEAD, not a cell) |

- **Families at or below the comparator.**
  - swechat CC E: git log 0.452, git push 0.452, git status 0.463, wc 0.485, which 0.602.
  - aiv_cc: curl 0.159, cat 0.283.
- **Artifact checks.**
  - **swechat/claude_code.** AC2, AC3 and AC5 are WEAK. AC4: dominated (user 0.405, model 0.789), and every leave-out
    stays WEAK. Strata are OK: model, 4 of 5 reportable WEAK (claude-haiku DEAD); repo, 35 reportable, WEAK and DEAD;
    length, all three WEAK. **Final WEAK.**
  - **aiv_cu.** Not dominated; AC2, AC3 and AC5 WEAK; strata OK (29 model and 30 agent strata, all WEAK). **Final WEAK.**
  - **aiv_cc.** Always dominated (one agent, label only). The 5 session leave-outs stay WEAK. Length strata OK.
    **Final WEAK.**
  - **cc_local.** One project holds every family result and the top session holds 0.483 of them, so AC4 is
    UNTESTABLE_WITHOUT_DOMINANT. The length tercile is CONFINED (long WEAK, mid DEAD). **Final DEAD.**
  - **codex.** The E cell is DEAD. On B ∪ E (7/14 = 0.5, WEAK): AC4 DOMINATED (e.g. leaving out one repo gives 0.462,
    DEAD); model and length are CONFINED. **Final DEAD.**
- AC1 is NOT_RUN for item e: a population statistic has no numerator events.

## 6. Item f: error-message fidelity (`results.f`)

| unit | split | checkable frames | unfaithful | coverage = frames / error results | verdict |
|---|---|---|---|---|---|
| swechat/claude_code | B | 28, **3 s** | 1 | 28/7,449 = 0.0038 | INSUFFICIENT_N |
| swechat/claude_code | E | 7, 3 s | 1 | 7/7,107 = 0.0010 | INSUFFICIENT_N |
| swechat/claude_code | B ∪ E | 35, 6 s | 2 (0.057 [0, 0.286]) | 35/14,556 = 0.0024 | INSUFFICIENT_N |
| cc_local | B | 4, 2 s | 0 | 4/1,104 = 0.0036 | INSUFFICIENT_N |
| aiv_cc | B | 0 | — | 0/779 | INSUFFICIENT_N |
| codex, opencode, gemini, aiv_cu, whowhen | B / E | — | — | — | NOT_TESTABLE (no numbered Read results) |

- **This is the null announced in PREREG_E §5, confirmed.** At most 0.0038 of error results (swechat CC B) carry a
  Python or rustc frame pointing at a line the session had shown, so N5f has nothing to work on.
- The positive control (line + 7) flags 35/35 swechat CC frames and 4/4 cc_local frames.

## 7. Nulls and INSUFFICIENT_N, stated plainly

- **N5a determinism is DEAD in swechat/claude_code,** the only unit with enough pairs. The honest drift is 0.281 on E
  (0.298 on B), above the 0.20 DEAD line.
- **N5a is INSUFFICIENT_N everywhere else.** The highest pair count is cc_local's 234, in 6 sessions; the other units
  have ≤ 12 pairs each.
- **N5b sort is DEAD as an item in every testable unit:** swechat CC, codex, cc_local and aiv_cu.
  - **ls is DEAD wherever it is testable:** honest violation 0.195 to 0.639.
  - **git_log is INSUFFICIENT_N in every unit.** The largest pool is aiv_cu B ∪ E at 34 outputs.
- **N5d whitespace is DEAD as an item in swechat CC, cc_local and aiv_cu,** and INSUFFICIENT_N in the rest.
  - pytest_banner is DEAD wherever it is testable (0.461 to 0.881).
  - ls_long_alignment is DEAD in cc_local (0.289) and in aiv_cu after AC4.
- **N5e size is DEAD in opencode, codex and cc_local** (the last two after checks), INSUFFICIENT_N in gemini, and capped
  at WEAK by rule where it holds.
- **N5f error fidelity is INSUFFICIENT_N or NOT_TESTABLE in every unit.**
- **No N5 item reaches ALIVE in any unit.**

## 8. Deviations (`deviations`, 13 entries)

| # | Topic | What was done | Effect on verdicts |
|---|---|---|---|
| 1 | File names | `phase_e_n5_battery.py` / `n5_battery.json` instead of `phase_e_n5.py` / `n5.json`, because the battery was split across agents | none |
| 2 | **Item cell for b and d** | No rule combines checkers, so the cell is the lowest checker label | lowers swechat CC N5b (grep_n WEAK) and N5d (git_status_tab ALIVE) to DEAD |
| 3 | Zero numerators | The ALIVE rule uses the per-event Wilson hi | as written |
| 4 | log10(bytes + 1) | Used on both sides of item e | none expected |
| 5 | Comparator CI and minimum n | e uses a comparator CI and a minimum of 30 texts / 5 s | none: no cell was INCONCLUSIVE |
| 6 | Comparator content | Model-generated text = IR assistant events plus subagent results | none |
| 7 | Positive-control seeds and abstention | Abstention counts as not flagged | — |
| 8 | f positive control | Implemented in the script (no frozen injector) | — |
| 9 | f pre-filter | Error results without a frame are skipped | none |
| 10 | Field-gate reading (NOT_TESTABLE) | — | — |
| 11 | AC3 copied ids | From the B and E caches | — |
| 12 | AC1 scope | Numerator = the flagged events; raw readers exist for the Claude Code formats only | AC1 NOT_RUN for aiv_cu ls_long_alignment, which is DEAD by AC4 anyway |
| 13 | AC4 / strata / AC5 details | Denominator = decision units per session; e's tool_key axis UNTESTABLE (one tool class); AC5 uses weighted rates (weighted quantiles for e) | listed per cell |

## 9. Interpretation (NOT data; every number above is in the JSON)

- **The battery mostly measures honest noise, and the noise is too high.**
  - Under the pre-registered definitions, three of the five items have no surviving cell. Determinism, sort order and
    whitespace are DEAD as items, and error fidelity has no coverage.
  - The honest false-positive sources are concrete and visible in the data, not hypothetical:
    - dataset redaction collapses distinct paths into one "repeated" key;
    - harness error stubs sit next to real output;
    - `ls` output follows locales that none of the four accepted orders match, and multi-directory listings concatenate;
    - the grep -n regex mis-splits hyphenated file names;
    - the "pytest banner" check matches echo separators.
  - These are reasons the checkers failed. They are not license to re-label them: any repair needs a fresh
    pre-registration and data not used here.
- **What did hold up is narrow.**
  - **git status tab-indentation** (swechat CC): 0 honest violations in 2,206 outputs across B ∪ E, robust to every
    artifact check. The tab is preserved and normalisation is caught. That only shows a forger who normalises whitespace
    is caught; a forger who copies the tab passes.
  - **grep -n line-order** (swechat CC): WEAK at 0.021 on E, and most of its residual honest violations come from the
    parser defect.
  - **ls -l and wc column alignment** (swechat CC): WEAK.
  - All four are single-unit results. The same checkers are DEAD or INSUFFICIENT_N in the other harnesses. This is a
    small instance of the N6 "signals do not transfer" pattern.
- **N5e WEAK is weaker than its label suggests.**
  - It says real command-output sizes spread more widely than the sizes of the model's own prose: 42 of 47 swechat CC
    families on E, 10 of 10 aiv_cu families.
  - The comparator is assistant text, not fabricated tool output. Nothing here shows that a model fabricating a `grep`
    result would produce sizes narrower than real `grep` results.
  - It makes no per-call decision, which is why the pre-registration caps it.
- **Post hoc only, for a future pre-registration.** In swechat CC, determinism drift excluding redaction-marked keys and
  error-result pairs was 0.017 [0.010, 0.025] (B ∪ E), and the digit-edit control was caught at about 0.95. That
  suggests a repaired determinism rule could be usable in Claude Code transcripts. The subset was chosen after seeing
  the data, so it is a hypothesis, not a finding.
- **Coverage is the binding constraint everywhere outside swechat CC.** Even there, determinism pairs exist in only 348
  of 1,679 B sessions and checkable traceback frames in 3. A per-session detector built from this battery would abstain
  on most sessions.
