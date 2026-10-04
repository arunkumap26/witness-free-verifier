# Phase E, N4 concurrency physics + N5 battery items c (truncation boundary) and g (cold start)

**Data.** `analysis/out/phase_e/n4_n5cg.json`, written by `analysis/probes/phase_e_n4_n5cg.py`
(`PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_n4_n5cg`, 313.7 s in run 6, `runtime_s`).

**Scope.** N4 (`prereg_e.json n4_concurrency`), N5c (`n5_battery.c_truncation_boundary`) and N5g
(`n5_battery.g_cold_start`). N5 items a, b, d, e, f are in `n5_battery.json` (separate agent). The three Track B
corpora (agentcap, pub_codex, tbench2) are NOT_RUN here (`track_b_corpora`). Their B/E caches were still being written
while this item ran, and their unit mapping is not wired into this script. They are left to the N6 grid run.

**Pre-registration.** The script ran with `check_frozen()` passing (`check_frozen`). The JSON carries the sha256 of
`prereg_e.json` and of `prereg_e_common.py`.
- The frozen helpers do every extraction:
  - N4: `inflight_counts`, the Phase B `p1_qualified` / `W_KEYS` / `G_TOOLS` / `g_latency`;
  - N5c: `truncation_info`, `truncated_result`;
  - N5g: `qualify_pairs`, `cold_start_values`;
  - artifact checks: `join_clean_mask`, `dominance`, `post_strat_weights`, `confinement`, `audit_sample`.
- No threshold was changed. Every verdict follows the mechanical rule of the prereg section. The choices the
  prereg leaves open are in `deviations` (16 entries, section 7 below). They were written into the script before the
  first full run, except two that were corrected after an independent re-derivation (C1, C2; section 9).
- **Run history.**
  - Run 1 was stopped by me during the aiv_cc N4 AC1 audit. phase_e_n1's aiv_cc raw reader tests every target id as a
    substring of every gz line, which was taking hours for the roughly 10^4 targets the audit needs. I added
    `raw_lookup()`, which pre-filters by `toolu_` id extraction and uses the same parser.
  - Run 2 was complete.
  - Run 3 added two things after I saw that cc_chars_mid was DEAD: a post-hoc raw audit of the inexact cc_chars_mid
    results (`...per_item.cc_chars_mid.post_hoc_not_a_verdict`), and the deviation entry that documents the existing
    non-level-recompute convention.
  - Run 4 added the counts in `all_pairs_counts` and corrected the wording of the Track B NOT_RUN reason.
  - I diffed every run against the previous one. Apart from the added fields, the Track B cache-existence flags and
    `runtime_s`, nothing changed, so every measured number is identical across runs 2 to 4.
  - **Runs 5 and 6 (corrections, section 9).** An independent re-deriver reproduced every number and found two
    blocking rule-application errors, both in swechat/codex N4 and cc_local N4. Run 5 applied corrections C1 and C2.
    Run 6 added the `corrections` block, which keeps each earlier value next to the new one. Diffed against run 4:
    no measured number (Δ, CI, n, sessions) changed. 51 labels, statuses and rule strings changed
    (`corrections.n_values_changed`), and two N6 cells moved: **swechat/codex N4 WEAK → DEAD** and **cc_local N4 WEAK →
    DEAD**.
- **Smoke tests.** Before run 1 I ran the code on small subsets (40 sessions per unit and split, and 250 swechat CC B
  sessions) to find bugs. No threshold or definition was changed after them.

**Conventions.**
- Rates are k/n [95% session-clustered CI]; session shares use Wilson; s = sessions (aiv_cc: runs).
- Splits: B; E (swechat and aiv_cu only; E is the replication); B ∪ E is the artifact-check population.
- **N6 cell** = the E verdict where E exists and is not INSUFFICIENT_N, else the B verdict. Artifact checks can only
  lower it.
- Δ is in decades (log10 seconds).
- Sections 1 to 7 report data. **Section 8 is interpretation.** Every number below is in the JSON, rounded.
- Paths:
  - `units.<unit>.results.{n4,n5g}.<split>` and `units.<unit>.results.n5c.<item>.<split>` for results;
  - `units.<unit>.cells.<row>` and `n6_cells.<unit>.<row>` for cells.
- 44 verdict blocks were computed (`cells_computed`). No family-wise correction was applied.

**Labels.**
- cc_local is *private*: aggregates only, clusters as indices, B only, unreplicated.
- aiv_cc is a *single-agent case study*, B only, unreplicated.
- N5g shell sessions in swechat CC and cc_local carry "human-wait contaminated". In opencode and gemini they carry
  "permission timing unknown".

---

## 1. N6 cells (`n6_cells`)

| unit | N4 concurrency | N5c truncation | N5g cold start |
|---|---|---|---|
| swechat/claude_code | **WEAK**. Before checks it was ALIVE on B and E; it was downgraded by CONFINED. **Under the literal in-flight definition the separation comes from subagent nesting; see 2.2** | **DEAD**. The cell is the lowest sub-item (see 3): cc_chars_mid DEAD (E exactness 0.845); cc_glob_cap **ALIVE** (E 0.996); cc_lines_tail NOT_RUN | **DEAD** (E median c 0.000, share c ≤ 0 0.502, 978 s) |
| swechat/codex | **DEAD** after checks (corrected from WEAK, section 9). E was WEAK (Δ_W 0.100 [0.047, 0.130]; no G tool); B is DEAD (Δ_W CI covers 0). On B ∪ E, AC4 is DOMINATED and tool_key and length are CONFINED | NOT_TESTABLE (no harness truncation markers) | **DEAD**. E is DEAD; B was WEAK and is not replicated; AC4 DOMINATED and CONFINED |
| swechat/opencode | **WEAK** (B and E; G below min n) | INSUFFICIENT_N (1 marked result on B, 1 on E) | **DEAD**. E is DEAD; B was WEAK and is not replicated |
| swechat/gemini | INSUFFICIENT_N (0 W pairs at k ≥ 2) | NOT_TESTABLE (no markers) | INSUFFICIENT_N (13 s B, 9 s E) |
| swechat/cursor | NOT_TESTABLE (no call/result pairs) | NOT_TESTABLE (no tool results) | NOT_TESTABLE (no pairs) |
| swechat/copilot, simple_text | NOT_TESTABLE (no sessions in B or E) | same | same |
| cc_local (private, B only) | **DEAD** after checks (corrected from WEAK, section 9). Before checks it was WEAK (Δ_W 0.096 [0.001, 0.172]); AC2 fails to DEAD, AC4 is DOMINATED, and tool_key and length are CONFINED | INSUFFICIENT_N (7 marked, 3 s) | **WEAK** (median c 0.120 [0.069, 0.582]; AC2 recompute INSUFFICIENT_N) |
| aiv_cc (single agent, B only) | **WEAK** (Δ_W 0.271 [0.051, 0.431]; G below min n) | INSUFFICIENT_N (chars_mid 5, glob 6) | **WEAK** (median c 0.211 [0.124, 0.359]) |
| aiv_cu | NOT_TESTABLE (per-call intervals: 0 of 59,956 B / 60,396 E pairs have a positive delta) | NOT_TESTABLE (no markers) | NOT_TESTABLE (per-call stamps) |
| whowhen (B only) | NOT_TESTABLE (no stamps: 0 of 535 pairs stamped) | NOT_TESTABLE (no markers) | NOT_TESTABLE |

**No N4, N5c or N5g cell is ALIVE after checks.**
- The only ALIVE label left is one N5c sub-item, swechat CC cc_glob_cap. It sits inside a DEAD item cell (the
  lowest-sub-item rule, deviation "N5c item cell").
- N4 WEAK cells after checks: swechat CC, opencode and aiv_cc (single agent). The opencode and aiv_cc cells rest on W
  alone, because G (the generation-bound control) does not reach the minimum n in either of them.
- **N4 nulls after checks: swechat/codex and cc_local are DEAD.** They are as prominent as the WEAK cells. In both, a
  W-only Δ_W that excluded 0 on the full population no longer excludes it when one repo, user or session is left out,
  or in most strata.

## 2. N4 concurrency physics (`results.n4`)

### 2.1 The announced null, against the counts

PREREG_E §2 announced that concurrency would be rare (A: swechat CC 9 W pairs at k ≥ 2). That count used
`inflight_counts()` on the W subset only. The JSON definition counts every pair of the session in any thread. Both are
reported here (deviation "N4 in-flight population"):

| unit, split | W pairs (s) | W k ≥ 2, JSON definition (s) | W k ≥ 2 within the W set only | G pairs (s) | G k ≥ 2 (s) | all stamped pairs: k ≥ 2 / k ≥ 4 / n |
|---|---|---|---|---|---|---|
| swechat CC B | 26,639 (1,103) | 16,529 (797) | 361 | 4,053 (914) | 1,525 (434) | 63,805 / 14,990 / 194,366 |
| swechat CC E | 22,952 (1,003) | 14,546 (748) | 112 | 3,630 (829) | 1,238 (388) | 58,885 / 9,686 / 180,046 |
| codex B | 5,949 (57) | 3,116 (49) | 2,953 | 0 | 0 | 4,726 / 1,093 / 9,727 |
| codex E | 2,303 (38) | 1,005 (31) | 985 | 0 | 0 | 2,930 / 672 / 6,216 |
| opencode B | 5,113 (209) | 2,266 (179) | 2,238 | 128 (12) | 7 (2) | 3,180 / 1,060 / 8,194 |
| opencode E | 3,785 (187) | 1,916 (157) | 1,897 | 38 (7) | 1 (1) | 2,509 / 888 / 5,419 |
| gemini B / E | 321 (16) / 73 (11) | 0 / 0 | 0 / 0 | 24 (5) / 20 (4) | 4 (2) / 9 (2) | 100 / 13 / 1,776; 82 / 12 / 528 |
| cc_local B | 1,817 (115) | 673 (98) | 18 | 167 (12) | 60 (8) | 17,305 / 5,430 / 36,542 |
| aiv_cc B | 7,423 (65) | 220 (21) | 0 | 190 (27) | 46 (6) | 2,006 / 113 / 38,738 |

- **The announced null holds only for the within-set count.** Under the JSON definition, concurrency is common in every
  unit except gemini.
- **G (the control population) reaches the minimum n (≥ 100 pairs at k ≥ 2 from ≥ 10 s) only in swechat CC.**
  Everywhere else the rule is a W-only test. It gives WEAK if the Δ_W CI excludes 0 ("Δ_W CI excludes 0 with G below
  min n"), and DEAD if the Δ_W CI covers 0 (correction C1; the first version gave INSUFFICIENT_N there).

### 2.2 Statistic and verdict

Δ = median log10 δ at k ≥ 2 minus median at k = 1, within tool_key, pair-count-weighted, with a session bootstrap. G
latency comes from Phase B's `g_latency`: CC tool-reported durations for 3,402 of 4,053 G pairs on B and 2,861 of 3,630
on E. Outside the CC formats it is the stamp delta (`G.latency_source`).

| unit | split | Δ_W [CI] (keys) | Δ_G [CI] (keys) | verdict |
|---|---|---|---|---|
| swechat CC | B | −0.108 [−0.304, 0.027] (glob, grep, read) | 0.219 [0.152, 0.294] (subagent, webfetch, websearch) | ALIVE (disjoint, \|diff\| 0.326) |
| swechat CC | E | −0.095 [−0.218, −0.013] | 0.194 [0.102, 0.314] | ALIVE (diff −0.289) |
| swechat CC | B ∪ E | −0.079 [−0.206, −0.013] | 0.214 [0.154, 0.280] | ALIVE |
| codex | B | 0.159 [−0.091, 0.376] (exec_command, shell_command; 3,116 at k ≥ 2 in 49 s) | — (no G tool) | **DEAD** (W-only test, Δ_W CI covers 0; was INSUFFICIENT_N, C1) |
| codex | E | 0.100 [0.047, 0.130] (1,005 in 31 s) | — | WEAK |
| codex | B ∪ E | 0.122 [0.001, 0.290] (4,121 in 80 s) | — | WEAK (checks population) |
| opencode | B | 0.204 [0.116, 0.273] (glob, grep, read) | undefined (G k ≥ 2 = 7) | WEAK |
| opencode | E | 0.212 [0.117, 0.275] | undefined (G k ≥ 2 = 1) | WEAK |
| gemini | B / E | undefined (W k ≥ 2 = 0) | undefined | INSUFFICIENT_N |
| cc_local | B | 0.096 [0.001, 0.172] (glob, read) | undefined (G k ≥ 2 = 60 in 8 s) | WEAK |
| aiv_cc | B | 0.271 [0.051, 0.431] (shell, write) | −0.015 [−0.639, 0.060] (G below min n: 46 in 6 runs) | WEAK |

**swechat CC, what the literal k measures (`W.k_ge_2_composition`, `W.by_key`).**
- On B, 16,181 of the 16,529 W pairs at k ≥ 2 sit in a subagent thread. For 16,039 of them, the in-flight "other call"
  includes the parent subagent pair. Only 7,312 W pairs have k ≥ 2 once ancestor and descendant pairs are not counted.
  E: 14,110 / 13,904 / 5,147 of 14,546.
- The negative Δ_W comes from `read`:
  - B: median 0.032 s at k = 1, 0.018 s at k ≥ 2 (−0.250 decades);
  - E: 0.029 s against 0.016 s (−0.258).
- `grep` goes the other way (B +0.206, E +0.310), and `glob` is near zero (+0.013 / +0.040).
- G's positive Δ comes from `subagent` pairs:
  - B: median 51.0 s at k = 1, 89.5 s at k ≥ 2 (+0.244);
  - E: 48.2 s against 77.3 s (+0.205).

**POST HOC, NOT A VERDICT** (`post_hoc_not_a_verdict`). The same rule was re-run on two variants. The prereg verdict
above stands.

| variant | split | Δ_W [CI] | Δ_G [CI] | label under the same rule |
|---|---|---|---|---|
| k not counting ancestor/descendant pairs | B | −0.029 [−0.191, 0.104] (k ≥ 2: 7,312 in 610 s) | 0.141 [0.084, 0.210] | DEAD (overlap) |
| same | E | −0.048 [−0.134, 0.060] (5,147 in 557 s) | 0.100 [0.023, 0.191] | DEAD |
| main-thread W only | B | **+0.473** [0.281, 0.585] (348 in 191 s) | as above | DEAD |
| main-thread W only | E | +0.267 [0.033, 0.578] (436 in 174 s) | as above | DEAD |

In codex, opencode, cc_local and aiv_cc, no ancestor pair is in flight (`ancestor_pair_in_flight` = 0). In those units
the variant equals the verdict population, and its label is the same as the verdict (codex B: DEAD after C1, was
INSUFFICIENT_N).

**Peak concurrency (the #67730 class): share of pairs at k ≥ 4 (`share_k_ge_4`).**
- W:
  - swechat CC B 4,525/26,639 = 0.170 [0.128, 0.217]; E 0.100 [0.080, 0.123];
  - codex B 0.140 [0.078, 0.241]; E 0.069 [0.025, 0.123];
  - opencode B 0.191 [0.151, 0.234]; E 0.217 [0.181, 0.259];
  - cc_local 0.043 [0.007, 0.097];
  - aiv_cc 13/7,423 = 0.002 [0.000, 0.006].
- G: swechat CC B 355/4,053 = 0.088 [0.069, 0.110]; E 0.078 [0.059, 0.099].

N4 has no per-session rule, so every N7 cell is NA_BLIND_BY_CONSTRUCTION (S:n4_concurrency.n7). No detector exists to
attack.

## 3. N5c truncation boundary (`results.n5c`)

Constants come from `resolved.n5.truncation_constants_pooled`:
- cc_chars_mid: raw prefix and suffix of 5,002 / 5,002 UTF-16 units;
- cc_glob_cap: 100 listed lines;
- cc_lines_tail: n_A 4 < 5, so the constant is INSUFFICIENT_N and the item is NOT_RUN.

| unit | item | split | marked (s) | exact | exactness [CI lo] | verdict |
|---|---|---|---|---|---|---|
| swechat CC | cc_chars_mid | B | 244 (136) | 210 | **0.861** [0.759] | DEAD |
| swechat CC | cc_chars_mid | E | 194 (130) | 164 | **0.845** [0.742] | DEAD |
| swechat CC | cc_glob_cap | B | 331 (178) | 329 | **0.994** [0.984] | ALIVE |
| swechat CC | cc_glob_cap | E | 284 (178) | 283 | **0.996** [0.989] | ALIVE |
| swechat CC | cc_lines_tail | B / E | 7 (3) / 11 (4) | — | — | NOT_RUN (no constant) |
| cc_local | cc_chars_mid | B | 7 (3) | 7 | 1.000 [0.646, Wilson] | INSUFFICIENT_N |
| aiv_cc | cc_chars_mid / glob / lines_tail | B | 5 (3) / 6 (5) / 3 (1) | 5 / 6 / — | 1.000 [0.566] / 1.000 [0.610] / — | INSUFFICIENT_N / INSUFFICIENT_N / NOT_RUN |
| opencode | cc_glob_cap | B / E | 1 / 1 | 1 / 1 | — | INSUFFICIENT_N |
| codex, gemini, aiv_cu, whowhen | — | — | 0 | — | — | NOT_TESTABLE (no harness truncation markers) |

**swechat CC cc_chars_mid: what the inexact results look like.** These are descriptive counts, not a rescue.
- `inexact_detail`, E (30 inexact in 15 s):
  - prefix exact but suffix not: 5;
  - suffix exact but prefix not: 10;
  - both below the constant: 15;
  - either above the constant: 0.
- On B (34 in 17 s) the same counts are 13 / 10 / 9 / 3.
- `by_key`:
  - shell: B 209 of 241 exact; E 163 of 193;
  - taskoutput: B 0 of 2.
- POST HOC raw audit of all 64 inexact results on B ∪ E (`per_item.cc_chars_mid.post_hoc_not_a_verdict`):
  - 64/64 were found in the raw transcripts, and the IR text equals the raw text in 64/64;
  - the raw text is inexact in 64/64;
  - 0 contain a carriage return in the kept text;
  - 2 carry more than one marker.
  - The commonest raw prefix deficits are 0 (18 results), 1,400 (7) and 80 (6).
  - The exact control sample was 30/30 found, 30/30 IR = raw and 30/30 exact.
- **So the inexactness is in the transcripts themselves, not introduced by the parser.**

**cc_glob_cap.** The 3 inexact results on B ∪ E are 101 / 4 / 101 listed lines (`lines_top`). One of the B ones is a
shell result that contains the Glob marker text.

**cc_lines_tail** (descriptive only).
- grep: prefix_raw 20,006 in 3 of 3 B and 3 of 4 E.
- shell: B 29,528 / 28,516 / 29,638 (one each); E 30,006 (4), 27,484 (1), 6,066 (1).
- aiv_cc shell: 30,003 (3).

**Positive control** (`positive_control`): a long real result re-truncated at uniform random lengths.
- Recall is 1.000 everywhere it ran:
  - swechat CC chars_mid: B 11,305 results / 1,292 s; E 10,645 / 1,205 s;
  - glob: B 2,812; E 2,557;
  - cc_local chars_mid 2,991; aiv_cc chars_mid 1,402.
- This only confirms the checker fires on arbitrary cut lengths. A fabricator who copies the constants passes by
  construction.

## 4. N5g cold start (`results.n5g`)

c_s = log10 δ(first qualified call of the session's top tool) − median log10 δ(its later calls). A session is flagged if
c_s ≤ 0.

| unit | split | sessions | median c [CI] | share c_s ≤ 0 [Wilson] | verdict | PC recall (first δ := a later δ) |
|---|---|---|---|---|---|---|
| swechat CC | B | 1,060 | −0.020 [−0.057, 0.000] | 571/1,060 = 0.539 [0.509, 0.568] | DEAD | 554/1,060 = 0.523 |
| swechat CC | E | 978 | 0.000 [−0.021, 0.033] | 491/978 = 0.502 [0.471, 0.533] | DEAD | 508/978 = 0.519 |
| codex | B | 56 | 0.014 [0.004, 0.035] | 20/56 = 0.357 | WEAK | 31/56 = 0.554 |
| codex | E | 36 | 0.019 [−0.00001, 0.032] | 13/36 = 0.361 | DEAD | 20/36 = 0.556 |
| opencode | B | 189 | 0.088 [0.038, 0.117] | 78/189 = 0.413 | WEAK | 114/189 = 0.603 |
| opencode | E | 159 | 0.040 [0.000, 0.145] | 78/159 = 0.491 | DEAD | 95/159 = 0.597 |
| gemini | B / E | 13 / 9 | 0.773 / 0.439 | 5/13 / 2/9 | INSUFFICIENT_N | — |
| cc_local | B | 48 | 0.120 [0.069, 0.582] | 13/48 = 0.271 [0.166, 0.410] | WEAK | 32/48 = 0.667 |
| aiv_cc | B | 53 | 0.211 [0.124, 0.359] | 12/53 = 0.226 [0.135, 0.355] | WEAK | 22/53 = 0.415 |

- **No unit comes near ALIVE.** ALIVE needs share ≤ 0.05; the lowest share is aiv_cc's 0.226.
- In swechat CC, the honest flag rate (0.502 to 0.539) and the positive-control recall (0.519 to 0.523) are the same
  number: the detector does not separate the two.
- swechat CC by class of the top tool (`by_top_tool_class`):
  - B shell 779 s, median −0.038; auto_read 281 s, −0.008;
  - E shell 764 s, −0.017; auto_read 214 s, +0.037.
- In opencode the first and later calls take about 6 ms and 5 ms (median first δ 0.006 s, later 0.005 s); 164 of 189
  first calls on B are in a subagent thread.

## 5. Artifact checks (cells at WEAK or better on B or E; population B ∪ E)

| cell | AC1 parser | AC2 trunc | AC3 join | AC4 dominance | AC5 post-strat | strata | effect |
|---|---|---|---|---|---|---|---|
| swechat CC N4 (base ALIVE) | PASS 0/30 differ (pool 31,075) | ALIVE | ALIVE | user, model dominated; 10 leave-outs all ALIVE | ALIVE | **tool_key CONFINED** (read ALIVE; glob, grep DEAD); **length CONFINED** (long ALIVE; mid, short DEAD); model OK; repo OK | ALIVE → **WEAK** |
| swechat CC N5c cc_glob_cap (ALIVE) | PASS 0/3 (all inexact) | NOT_RUN (by definition) | ALIVE 0.995 | user, model dominated; leave-outs all ALIVE | ALIVE 0.996 [0.990] | model OK; length OK; tool_key, repo UNTESTABLE | stays ALIVE (item cell DEAD by rule) |
| codex N4 (WEAK; B ∪ E Δ_W 0.122 [0.001, 0.290]) | NOT_RUN (no raw reader) | WEAK | WEAK | **DOMINATED** (corrected from UNTESTABLE_WITHOUT_DOMINANT): 10 of 16 leave-outs drop to DEAD with W still at min n, e.g. zchee/zmux 0.052 [−0.091, 0.084] (2,410 in 49 s), user zchee 0.066 [−0.051, 0.083] (2,965 in 62 s), dayhaysoos/nimbus 0.089 [−0.062, 0.394] (2,820 in 47 s), and zchee/agent [−0.011, 0.277], which removes a single k ≥ 2 pair (4,120 in 79 s). 1 leave-out (model gpt-5.4: 763 in 9 s) is below min n | WEAK | **tool_key CONFINED** (shell_command WEAK 0.215 [0.039, 0.517]; exec_command DEAD 0.053 [−0.116, 0.068], 2,036 in 41 s); **length CONFINED** (short WEAK 0.055 [0.037, 0.090], 200 in 20 s; long DEAD [−0.029, 0.453], 3,192 in 21 s; mid DEAD [−0.067, 0.089], 729 in 39 s); repo OK; model UNTESTABLE | WEAK → **DEAD** (was: stays WEAK) |
| opencode N4 (WEAK) | NOT_RUN | WEAK | WEAK | repo 0.858, dominated; 15 leave-outs all WEAK | WEAK | all axes OK | stays WEAK |
| cc_local N4 (WEAK) | NOT_RUN | **DEAD** (Δ_W 0.095 [−0.015, 0.183], 588 in 89 s, W still at min n; was recorded as INSUFFICIENT_N) | WEAK | **DOMINATED** (corrected from UNTESTABLE_WITHOUT_DOMINANT): 2 of 10 leave-outs drop to DEAD (largest session: 0.112 [−0.021, 0.153], 543 in 97 s; third largest: 0.104 [−0.017, 0.139], 583 in 97 s); 2 are below min n (without the dominant project cluster, 0 W pairs at k ≥ 2 remain; without one model cluster, 27 in 2 s) | NOT_RUN (no population table) | **tool_key CONFINED** (glob WEAK 0.092 [0.061, 0.113]; read DEAD 0.097 [−0.046, 0.211], 455 in 51 s); **length CONFINED** (mid WEAK 0.111 [0.079, 0.147]; long DEAD 0.095 [−0.058, 0.186], 507 in 33 s) | WEAK → **DEAD** (was: stays WEAK by convention, with "stricter reading INSUFFICIENT_N" stated wrongly) |
| aiv_cc N4 (WEAK) | PASS 0/30 (pool 220) | WEAK | WEAK | session share 0.104; 5 leave-outs WEAK | NOT_RUN | UNTESTABLE | stays WEAK |
| codex N5g (cell DEAD from E; B WEAK) | NOT_RUN | WEAK | WEAK | **DOMINATED** (leaving out dayhaysoos/nimbus → DEAD) | WEAK | **tool_key CONFINED**, **repo CONFINED** | DEAD |
| opencode N5g (cell DEAD from E; B WEAK) | NOT_RUN | DEAD | WEAK | dominated, stable | WEAK | UNTESTABLE / OK | DEAD |
| cc_local N5g (WEAK) | NOT_RUN | **INSUFFICIENT_N** (20 s left) | WEAK | UNTESTABLE_WITHOUT_DOMINANT | NOT_RUN | UNTESTABLE | stays WEAK by convention; **stricter reading: INSUFFICIENT_N** |
| aiv_cc N5g (WEAK) | PASS 0/12 | WEAK | WEAK | not dominated | NOT_RUN | UNTESTABLE | stays WEAK |

**Non-level recomputes.** An AC recompute that lands on INSUFFICIENT_N is stored with `fail: true` but does not change
the cell (deviation "artifact-check recompute with a non-level label"; same convention as n5_battery.json). After C1, an
N4 recompute lands on INSUFFICIENT_N only when its W population is below min n. **One cell now depends on the
convention: cc_local N5g** (AC2 leaves 20 sessions, below the 30-session minimum). Under the stricter reading it is
INSUFFICIENT_N. The first version also listed cc_local N4 here. That was wrong: its AC2 recompute keeps W at min n, so
under C1 it is a DEAD recompute and lowers the cell.

**Other effects of C1 and C2 (no cell change).**
- swechat CC N4: 6 strata go from INSUFFICIENT_N to DEAD. They are 1 model stratum and 5 repo strata where W reaches min n
  but G does not. The model and repo axes stay OK.
- opencode N4: the tool_key stratum grep goes from INSUFFICIENT_N to DEAD (0.000 [−0.058, 0.051], 319 in 93 s). The
  axis stays OK, because glob and read are both WEAK.
- codex N5g: the AC4 status now also names the 2 leave-outs that fall below min n (user "nan", meaning no user id:
  26 s; model gpt-5.4: 17 s). The cell was already DEAD.

## 6. What could not be measured, and why

- **N4 W-vs-G separation outside swechat CC.**
  - G has no tool in codex.
  - G is too small elsewhere: opencode 128 / 38 pairs; cc_local 60 at k ≥ 2 in 8 s; aiv_cc 46 in 6 runs; gemini 24 / 20.
  - So every WEAK there means only that "Δ_W excludes 0", and every DEAD there (codex, cc_local) means only that it does
    not, robustly. Neither is the pre-registered discrimination between work-bound and generation-bound latency.
- **N4 in aiv_cu and whowhen.** aiv_cu has 0 pairs with a positive delta on B and on E; whowhen has no stamps.
- **AC1 outside the Claude Code formats.** No committed raw reader exists for codex, opencode or gemini, and cc_local is
  private. So the parser audit is NOT_RUN for codex N4, opencode N4, cc_local N4 / N5g, and codex / opencode N5g.
- **AC5 for cc_local and aiv_cc.** There is no population table.
- **N5c cc_lines_tail.** The A constant rests on n_A 4, and B ∪ E has only 18 marked results in swechat CC. In cc_local
  N5c is essentially absent: 7 cc_chars_mid markers and 0 glob markers on B.
- **N5c on any non-Claude-Code harness.** The markers are Claude Code strings. codex, gemini, aiv_cu and whowhen have
  none, and opencode has 1 per split.
- **N5g in gemini** (13 / 9 sessions). It is also INSUFFICIENT_N on every stratum smaller than 30 sessions.
- **The three Track B corpora** (`track_b_corpora`). NOT_RUN, for the reason given under Scope.
- **cc_local N4 and N5g replication.** There is no E split for cc_local, by the scope rule.

## 7. Deviations (`deviations`, 16 entries)

1. Output file names: `n4_n5cg.json`, not `n4.json`.
2. N4 in-flight population: the verdict uses k over all pairs (JSON definition); the within-set k is also reported.
3. N4 nesting: the verdict uses the literal "any thread" k. A variant excluding ancestor and descendant pairs is
   reported post hoc. This was decided before any N4 number existed.
4. N4 Δ combination: weight = the key's pair count; the key set is fixed on the point estimate; boot_stat.
5. N4 min n and missing branches. Min n is counted over the population. **Corrected (C1):** "G below min n and Δ_W CI
   covers 0", with W at min n, is DEAD, the null outcome of the W-only test. It was INSUFFICIENT_N.
6. **AC4 "leave-out falls below min n" (C2, new entry).** This is decided on the leave-out's own counts, not on its
   label. Every other leave-out is compared on levels.
7. N4 G latency: the Phase B `g_latency` exactly.
8. N5c exactness CI: 1 − the inexact-rate CI hi; with a zero numerator, 1 − the per-event Wilson hi.
9. N5c item cell: the lowest runnable sub-item.
10. N5c positive control: "long" means ≥ 10,004 UTF-16 units; two-sided cut layout; Glob keeps n of N lines.
11. N5c AC2 is NOT_RUN: every marked result is truncated by definition.
12. N5g statistic: one c_s per session; cluster_quantile median; Wilson share.
13. N5g positive control: rng_for('N5gpc', session, tool); the later-call set is unchanged.
14. Field gate: which units are NOT_TESTABLE, and why.
15. Artifact-check recompute with a non-level label: no change (convention). The stricter reading is stated in section 5.
   After C1 it affects only cc_local N5g.
16. Artifact-check details (AC1 numerators and the aiv_cc raw pre-filter, AC4 denominators, AC5 weights, strata axes).

---

## 8. Interpretation (not data)

**N4.**
- The pre-registered rule gives swechat CC an ALIVE separation on both B and E. But the separation has the wrong sign
  for the hypothesis: concurrent work-bound calls are *faster* (Δ_W < 0), not inflated.
- It is almost entirely a thread-membership effect. 16,181 of the 16,529 k ≥ 2 W pairs on B are calls inside a
  subagent, and 16,039 of those count their parent subagent pair as "in flight".
- Counting only non-nested overlap, Δ_W and Δ_G overlap (DEAD) on B and E. Taking main-thread W pairs only flips Δ_W
  positive (+0.47 / +0.27), and they still overlap with G.
- The pre-registered checks caught part of this: the label is CONFINED to `read` and to long sessions, which are the
  subagent-heavy strata, and drops to WEAK.
- I would read the swechat CC N4 cell as **no evidence for a concurrency signature that separates real from generated
  latency**.
- What survives outside swechat CC is narrower. It holds in opencode (Δ_W 0.204 on B, 0.212 on E) and in aiv_cc
  (single agent, 0.271): when other calls are in flight, work-bound calls are slower. That is the contention half of
  the hypothesis. It does **not** survive in codex or cc_local, which are DEAD after correction:
  - codex is positive on E (0.100) but not on B (CI covers 0). On B ∪ E the CI lower bound is 0.001. It crosses 0
    when one repo, one user or one of the 3 largest sessions is left out. It even crosses 0 when the repo zchee/agent
    is left out, which holds 0.0001 of the W pairs and 1 pair at k ≥ 2. Only shell_command and short sessions carry
    the effect.
  - cc_local's W-only Δ_W stops excluding 0 when truncated results are dropped (AC2) or the largest session is left
    out. Only glob and mid-length sessions carry it.
  - So "contention inflates work-bound latency" is not a general property across these harnesses. It held in 2 of the
    4 units where only W could be tested, and one of those 2 is a single agent.
- Two caveats on the surviving cells:
  - the generation-bound half was never measured outside swechat CC;
  - a harness that stamps all results of a parallel batch when the batch completes would produce the same inflation
    with no contention at all. This is untested, and is a candidate explanation for opencode, where reads take
    milliseconds.
- N4 has no per-session decision rule, so it cannot flag a session as built.

**N5c.**
- The idea behind it (real truncation lands on exact harness constants) holds for **Glob**: 3 of 615 capped results
  on B ∪ E are not exactly 100 lines, and this survived every check.
- It **fails for the mid-text character elision**: the inexact share of honest Claude Code elisions is 34/244 = 0.139
  on B and 30/194 = 0.155 on E (`inexact_rate`). The raw transcripts show the same lengths, so this is a property of the harness or its transcript, not of
  our parser. The varied deficits suggest more than one truncation path or version.
- A detector built on cc_chars_mid would flag that share of honest truncated outputs.
- The Glob cap is a narrow, cheap consistency check:
  - it covers only Claude Code Glob results that hit the cap (615 results in 356 sessions on B ∪ E, against
    194,366 + 180,046 swechat CC pairs);
  - its positive control is trivial: any non-100 cut is caught, and a fabricator who knows the constant passes.
- I would treat it as a COULD-tier format check, not a mechanism.

**N5g.**
- Cold start is DEAD where n is large. In swechat CC, about half of all sessions have a first call no slower than its
  later calls, and the detector flags honest sessions and the "no cold start" positive control at the same rate (about
  0.5).
- The two WEAK cells cannot be told apart from what is expected of honest data plus confounds:
  - cc_local (private, 48 s) and aiv_cc (single agent, 53 runs) have a median first-call excess of 0.120 and
    0.211 decades;
  - both are unreplicated;
  - cc_local's WEAK depends on the non-level-recompute convention;
  - first shell calls in Claude Code formats can include permission or human wait.
- codex and opencode were WEAK on B and did not replicate on E.

**Bottom line for the design.**
- None of N4, N5c or N5g earns a MUST or SHOULD slot.
- The Glob 100-line cap is the one exact harness constant that held (0.996 on E), at very small coverage.
- The N4 swechat CC "ALIVE before checks" is the most instructive null in this item. A literal concurrency count in
  nested-agent harnesses measures nesting, and the pre-registered rule is sign-agnostic, so it rewarded a separation in
  the opposite direction from the hypothesis.

---

## 9. Corrections (`corrections`; data, with the earlier values kept)

An independent re-deriver reproduced every number in this item and raised two blocking issues. Both were rule
applications, not measurement errors. No Δ, CI, n or session count changed (runs 4 → 6 diff).

**C1: the N4 branch "G below min n and Δ_W CI covers 0" (W at min n). It is now DEAD; it was INSUFFICIENT_N.**
- Why the earlier reading was wrong:
  - The prereg's WEAK rule ("Δ_W CI excludes 0 with G below min n"; PREREG_E: "Δ_W ≠ 0 without a G control") defines a
    W-only test.
  - PREREG_E §5 calls codex testable although it has no G control.
  - INSUFFICIENT_N means below min n, and W was not below it. Calling the outcome INSUFFICIENT_N turned a null into
    missing data.
  - The W-only analogue of "CIs overlap" is a Δ_W CI that covers the comparator 0.
  - The first version's own deviation already named DEAD as the alternative reading.
- C1 is applied everywhere the rule runs: base verdicts, AC2 / AC3 / AC5 recomputes, AC4 leave-outs, strata and post-hoc
  variants.

**C2: when an AC4 leave-out "falls below min n".** This is now decided on the leave-out's counts. It was decided by the
label INSUFFICIENT_N. In codex N4 every leave-out that went to INSUFFICIENT_N had kept W at min n (1,529 to 4,120 pairs
at k ≥ 2 in 25 to 79 sessions), and G was 0 in the base cell too. So UNTESTABLE_WITHOUT_DOMINANT was the wrong status;
the right one is DOMINATED.

| path (abridged) | before (run 4) | after (run 6) |
|---|---|---|
| `n6_cells.swechat/codex.N4.label` | WEAK | **DEAD** |
| `units.swechat/codex.cells.N4.B` (B verdict) | INSUFFICIENT_N | DEAD |
| `units.swechat/codex.cells.N4...AC4_dominance.status` | UNTESTABLE_WITHOUT_DOMINANT | DOMINATED (+ UNTESTABLE_WITHOUT_DOMINANT leave-outs) |
| `units.swechat/codex.cells.N4...tool_key.confinement` / `length_tercile.confinement` | UNTESTABLE / UNTESTABLE | CONFINED / CONFINED |
| `n6_cells.cc_local.N4.label` | WEAK | **DEAD** |
| `units.cc_local.cells.N4...AC2_no_truncated.label` | INSUFFICIENT_N | DEAD |
| `units.cc_local.cells.N4...AC4_dominance.status` | UNTESTABLE_WITHOUT_DOMINANT | DOMINATED (+ UNTESTABLE_WITHOUT_DOMINANT leave-outs) |
| `units.cc_local.cells.N4...tool_key.confinement` / `length_tercile.confinement` | UNTESTABLE / UNTESTABLE | CONFINED / CONFINED |
| 3 codex and 2 cc_local N4 strata (they produce the CONFINED rows above), 10 codex and 2 cc_local leave-out labels, 6 swechat CC and 1 opencode N4 strata, 2 codex post-hoc labels | INSUFFICIENT_N | DEAD (no other cell changes) |
| `units.swechat/codex.cells.N5g_cold_start...AC4_dominance.status` | DOMINATED | DOMINATED (+ UNTESTABLE_WITHOUT_DOMINANT leave-outs) (status text only; the cell stays DEAD) |

The full list of 51 changed values, each with its JSON path, before, after and rule, is in `corrections.values`.

**What the corrections do not change.**
- Every other N6 cell keeps its label: swechat CC N4 WEAK, opencode N4 WEAK, aiv_cc N4 WEAK, and all N5c and N5g cells.
- **cc_local N5g WEAK still rests on the non-level-recompute convention**, because its AC2 recompute leaves 20 sessions,
  below the minimum of 30. The stricter reading is INSUFFICIENT_N, as section 5 says.
