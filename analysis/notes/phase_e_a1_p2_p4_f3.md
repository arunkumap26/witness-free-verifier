# Phase E A1: Probe 2 WEAK candidates, Probe 4 round numbers, follow-up F3 (item `a1_p2_p4_f3`)

- **Script:** `analysis/probes/phase_e_a1_p2_p4_f3.py`. Run it with
  `PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_a1_p2_p4_f3`. The run took 247.1 s.
- **Raw numbers:** `analysis/out/phase_e/a1_p2_p4_f3.json`. The F3 section of the same run is also written alone to
  `analysis/out/phase_e/f3_round.json`.
- **Pre-registration:**
  - `check_frozen()` passed. The spec sha matches `prereg_e.json`, and the Phase B module and calibration shas match.
  - Thresholds come from `prereg_e.json` and `prereg.json`. None was tuned.
  - Every rule reading is listed in the JSON's `deviations`, including the changes made between debug runs, each with its
    before and after.
- **Populations:**
  - **B ∪ E pooled** for the re-measurement and the artifact checks.
  - **E** for the replication label.
  - **B only** for cc_local and aiv_cc, labelled UNREPLICATED.
  - One swechat/claude_code E id has no IR rows: 1,545 sessions were loaded (`extraction.swechat/claude_code/E.sessions`).
- **Labels:** cc_local is private, so its section holds aggregates only. aiv_cc is a single-agent case study.

Everything below the "Interpretation" heading is interpretation. Everything above it is copied from the JSON.

---

## 1. Verdicts (mechanical, `verdicts.*` and `candidates.*.survival`)

| Candidate | Phase B | E label | Kill test result | Status | Final | Deciding number (n) |
|---|---|---|---|---|---|---|
| P4round swechat/claude_code | ALIVE | ALIVE | F3 WEAK (B ∪ E and E) → cap WEAK | **DOWNGRADED** | WEAK | B ∪ E residual after exclusion: 71/307 = 0.231 [0.158, 0.316] vs M_all 0.113, g = 0.464 × g_full (307 values, 158 s) |
| P4round cc_local (private) | ALIVE | — | F3 WEAK → cap WEAK | **DOWNGRADED** (B only, unreplicated) | WEAK | 114/206 = 0.553 [0.131, 0.731], g = 0.820 × g_full (206 values, 12 s) |
| P4round swechat/* (pooled) | ALIVE | ALIVE | F3 WEAK → cap WEAK; then AC4 DOMINATED | **KILLED** | DEAD | without claude-opus-4-6, g = 0.071 ≤ 0.25 × 0.301 = 0.075: COLLAPSE (107 values) |
| P2 swechat/claude_code main | WEAK | WEAK | K1: 0 rows affected | **SURVIVES** | WEAK | E: S_deep 608/4,466 = 0.136 [0.117, 0.156], 511 s |
| P2 swechat/claude_code subagent | WEAK | WEAK | K1: 0 rows affected | **SURVIVES** | WEAK | E: S_deep 612/7,920 = 0.077 [0.061, 0.097], 306 s |
| P2 swechat/opencode subagent | WEAK | ALIVE | K1 did not fire (fallback to S_path_any, WEAK) | **DOWNGRADED** (AC4 UNTESTABLE_WITHOUT_DOMINANT) | WEAK | E: S_deep 10/232 = 0.043 [0.004, 0.095], 49 s |
| P2 swechat/codex subagent | WEAK | WEAK | K1: 79 rows affected, no label change | **SURVIVES** | WEAK | E: S_path_any 62/523 = 0.119 [0.086, 0.153], 23 s |
| P2 aiv_cc main (single-agent case study) | WEAK | — | K1: 0 rows affected | **KILLED** (B only, unreplicated) | DEAD (INCONCLUSIVE under the antecedents-incomplete cap) | B: S_path_any 710/3,689 = 0.192 [0.081, 0.351], 53 runs; AC4 DOMINATED and CONFINED on tool |

**Cells computed:** 8 survival statuses (`verdict_cells_computed`). No family-wise correction is applied.

**Reproduction of Phase B on B.** Each B number below matches the committed Phase B output exactly. Every candidate
shows `reproduction_B_vs_phase_b.all_match = true`.

- **Probe 4:**
  - T_orig last-0: 127/300 for swechat/claude_code, 221/341 for cc_local, 141/322 for the pooled row.
  - M_all last-0: 2,365/20,419, 2,243/18,550 and 2,777/23,570 respectively.
  - The CIs of the two single units match too.
- **Probe 2:** 671/4,655, 525/6,850, 16/219, 104/795 and 710/3,689.

---

## 2. F3: are the round numbers just model-chosen parameters?

**Not DEAD by the pre-registered collapse rule, but downgraded from ALIVE to WEAK in every unit.**

The collapse rule fires when g ≤ 0.25 × g_full. Here g is the last-0 share of the remaining values minus the M_all
share, and g_full is the same gap before exclusion. In swechat/claude_code, excluding parameter values shrinks the
round-number gap to 0.464 of its size on B ∪ E and to 0.338 on E. Neither reaches the 0.25 collapse threshold. Neither
reaches the 0.5 needed to keep ALIVE either.

**What the exclusion removed in swechat/claude_code (B ∪ E).** Source:
`candidates['P4round/swechat/claude_code'].populations.BuE.F3.strict`.

- **152 of 459 distinct model-originated values** are parameters under the strict rule.
- **98 of those 152 end in 0** (`excluded_last0`).
- **By parameter context** (value × context pairs): JSON-number arguments 90, `key=value` with a parameter-like key 50,
  CLI option arguments 31, `host:port` 20, call arguments of `range` / `sleep` and similar 7, SQL LIMIT/OFFSET 5,
  numeric positionals of `head` / `tail` / `sleep` and similar 2.
- **By the origin of the value's first occurrence:** JSON number 80, argument string 72.

**The gap before and after exclusion:**

| Population | T_orig last-0 (all) | M_all last-0 | g_full | Remaining after strict exclusion | g | g / g_full | Collapse threshold | F3 |
|---|---|---|---|---|---|---|---|---|
| B | 127/300 = 0.423 | 2,365/20,419 = 0.116 | 0.308 | 54/200 = 0.270 [0.160, 0.403] | 0.154 | 0.501 | 0.077 | WEAK (rule WEAK) |
| E | 91/248 = 0.367 [0.289, 0.454] | 2,001/17,722 = 0.113 | 0.254 | 31/156 = 0.199 [0.131, 0.288] | 0.086 | 0.338 | 0.0635 | WEAK |
| B ∪ E | 169/459 = 0.368 [0.305, 0.437] | 3,930/34,788 = 0.113 [0.109, 0.118] | 0.255 | 71/307 = 0.231 [0.158, 0.316] | 0.118 | 0.464 | 0.064 | WEAK |

The brief's "42% vs 12%" is the B row: 0.423 vs 0.116.

- **cc_local (private, B only):**
  - All values: 221/341 = 0.648 [0.435, 0.786] vs 2,243/18,550 = 0.121.
  - Strict exclusion removes 135 values, 107 of them ending in 0. That leaves 114/206 = 0.553 [0.131, 0.731] from 12
    sessions.
  - g / g_full = 0.820, so the gap barely shrinks.
  - The rule gives WEAK, not ALIVE: the CI lower bound, 0.131, does not clear M_all's CI upper bound plus 0.05.
  - F3 is WEAK.
- **swechat/\* pooled:**
  - B ∪ E: g / g_full = 0.462 → WEAK.
  - E: g = 0.069 against a collapse threshold of 0.0656 (g / g_full = 0.263) → WEAK. This misses collapse by 0.004.
  - B alone: F3 ALIVE (0.512). The kill-test rule uses the lowest testable label of B ∪ E and E, which is WEAK.
- **The other exclusion readings do not decide** (`kill_tests.F3_parameter_exclusion.variants_reported_not_deciding`).
  - The calibration-code reading excludes a value only when an *unsourced* occurrence of it is a parameter. On
    swechat/claude_code B ∪ E it gives ALIVE (0.503), and on E it gives WEAK.
  - The first-occurrence rule also gives ALIVE on B ∪ E (0.546) and WEAK on E.
  - The strict JSON-text reading is primary (see `deviations`). The deciding label is WEAK under all three, because E is
    WEAK under all three.

---

## 3. Probe 4 candidates: the remaining kill attempts (B ∪ E)

| Check | swechat/claude_code | cc_local (private) | swechat/* pooled |
|---|---|---|---|
| AC1 parser (raw audit of 30 T_orig values ending in 0) | PASS: 0/30 changed, 30 located. Every value was in the raw call input; none was in a raw antecedent | PASS: 0 changed among 25 located. 5 calls sit in other resume-family members' main files and were not located | PASS: 0/30 changed (24 claude_code, 6 codex) |
| AC2 truncation | PASS (719 T occurrences dropped; full ALIVE, F3 WEAK) | PASS | PASS |
| AC3 join | PASS (2,120 T occurrences dropped) | PASS | PASS |
| AC4 dominance | UNTESTABLE_WITHOUT_DOMINANT. claude-opus-4-6 holds 0.736 of T_orig values; without it, 88 values remain after exclusion (< 100), so F3 is untestable. Cap WEAK, no label change | UNTESTABLE_WITHOUT_DOMINANT. One project holds all T_orig values (share 1.0); one session holds 0.434 | **DOMINATED.** claude-opus-4-6 holds 0.664 of T_orig values; without it, F3 COLLAPSES (g 0.071 ≤ 0.075, 107 values). One-level downgrade → DEAD |
| AC5 sampling | PASS (weighted: full ALIVE, F3 WEAK; g 0.118 vs g_full 0.255) | NOT_RUN (no population table) | PASS |
| Strata | Tool OK (shell and write both signal-bearing); model OK on the full statistic, F3 UNTESTABLE; repo UNTESTABLE (no repo reaches 100 values); length OK on the full statistic | Every axis UNTESTABLE (one reportable stratum) | Tool OK, model OK / UNTESTABLE, length OK |

---

## 4. Probe 2 candidates (S_deep = knowledge-from-nowhere share of deep first-try accesses; lower is better)

**Instrument check** (swechat/claude_code main S_symbol_ref ≤ 0.10): B ∪ E 2,541/89,985 = 0.028 (CI hi 0.032), E
1,299/43,149 = 0.030. It holds on both, so no cap applies.

| | CC main | CC subagent | opencode subagent | codex subagent | aiv_cc main |
|---|---|---|---|---|---|
| E (replication) | 608/4,466 = 0.136 [0.117, 0.156] WEAK | 612/7,920 = 0.077 [0.061, 0.097] WEAK | 10/232 = 0.043 [0.004, 0.095] **ALIVE** | S_path_any 62/523 = 0.119 [0.086, 0.153] WEAK | — |
| B ∪ E | 1,279/9,121 = 0.140 [0.127, 0.153], 1,097 s | 1,137/14,770 = 0.077 [0.067, 0.089], 602 s | 26/451 = 0.058 [0.024, 0.101], 102 s | S_path_any 166/1,318 = 0.126 [0.103, 0.149], 59 s | B: S_path_any 710/3,689 = 0.192 [0.081, 0.351], 53 runs |
| K1 strict root rule | 0 rows affected | 0 rows affected | 4,242 rows lose their depth. **S_deep has 0 decidable accesses** under the strict rule; the verdict falls back to S_path_any 461/4,863 = 0.095 (WEAK, capped), so K1 does not fire | 79 rows; S_path_any unchanged | 0 rows |
| K2 complete records (reported only) | 616/4,195 = 0.147 on unflagged sessions (430 of 1,097 decision sessions flagged) | 490/6,801 = 0.072 (253 of 602 flagged) | unchanged (0 decision sessions flagged) | unchanged | **INSUFFICIENT_N**: all 53 decision runs flagged (every run after r000 resumes the SDK session) |
| AC1 raw audit | PASS 0/30 changed (5 with antecedent text-length differences, no decision change) | PASS 0/30 | PASS 0/26 (every numerator event audited) | PASS 0/30 | PASS 0/30 |
| AC2 / AC3 / AC5 | PASS / PASS / PASS (weighted 0.140) | PASS / PASS / PASS | PASS / PASS / PASS | PASS / PASS / PASS | PASS / PASS / NOT_RUN |
| AC4 | PASS: user and model kinds dominated, no leave-out drops the label | PASS: dropping claude-opus-4-6 gives 68/1,598 = 0.043, a higher label, ignored (no rescue) | UNTESTABLE_WITHOUT_DOMINANT: repo#1 holds 0.933 of S_deep events; without it S_deep is below min n | UNTESTABLE_WITHOUT_DOMINANT (no label change) | **DOMINATED**: leaving out any one of 4 of the top 5 runs moves S_path_any to 0.202–0.212 (DEAD before the cap). Also UNTESTABLE (one model) |
| Strata | all axes OK (repo: 9 of 10 reportable repos signal-bearing) | tool UNTESTABLE, others OK | only length testable, OK | only length testable, OK | **CONFINED on tool**: Read 7/2,617 is WEAK; mcp__village__bash 190/376 = 0.505 and shell 120/267 = 0.449 are DEAD before the cap |

**AC1 context, outside the decision rule.**

- In 8 of 30 audited CC main-thread events, the path key appears in raw received text earlier in the transcript but
  in another thread. Main-thread events in a subagent's internal results are one example.
- In 20 of 30 CC subagent events, the key appears earlier in another thread, such as the parent's record.
- The prereg's thread rule does not count these as sources.

---

## 5. Nulls and what died

Each of these is stated as plainly as a hit.

- **P4 round numbers lose ALIVE everywhere.** Model-chosen parameters account for about half the gap.
  - swechat/claude_code: g / g_full is 0.464 on B ∪ E and 0.338 on E.
  - cc_local: 0.820.
  - pooled: 0.462 and 0.263.
- **The pooled swechat/* round-number row is KILLED.** Its residual gap depends on one model. Without
  claude-opus-4-6 sessions it collapses: g 0.071 ≤ 0.075.
- **P2 aiv_cc main is KILLED.**
  - Its WEAK rests on single runs: 4 of the top 5 leave-outs cross 0.20.
  - It is confined to Read accesses. Shell-type paths are DEAD before the cap.
  - Under the unit's antecedents-incomplete cap it reads INCONCLUSIVE.
  - The kill depends on two rule readings, both logged in `deviations` ("antecedents-incomplete cap in strata and AC4").
    - The strata reading counts DEAD-before-cap strata as reportable.
    - The AC4 reading compares an INCONCLUSIVE leave-out by its label before the cap.
  - If both readings were reversed, the cell would stay WEAK. With only the AC4 reading reversed, it is still KILLED
    by confinement (`AC4_dominance.result_if_INCONCLUSIVE_leave_outs_not_counted` = UNTESTABLE_WITHOUT_DOMINANT).
- **P2 swechat/opencode subagent: no S_deep under the strict rule.**
  - Under the pre-registered workspace-root rule, S_deep does not exist for this stratum (0 decidable accesses). Its E
    ALIVE comes from the Phase B root-rule deviation.
  - It also comes from one repo, which holds 0.933 of S_deep events.
  - The cell survives only as the S_path_any fallback, capped at WEAK.
- **No P2 cell reaches ALIVE on B ∪ E.** Honest knowledge-from-nowhere rates are 0.140 (CC main) and 0.077
  (CC subagent). Both are above the 0.05 ALIVE bound.

---

## Interpretation (not data)

**F3: the skeptic was half right.** In the swechat Claude Code population, model-chosen parameters supply a large part
of the "round numbers" signal. They are mostly JSON-number arguments and `key=value` / CLI option values, and about two
thirds of the removed values end in 0. The excess left after removing them is still about 0.12 above the machine
baseline. That is not a collapse, but it no longer supports ALIVE.

**Where the residual sits.** Two observations, both post hoc and descriptive. They are not tested and decide nothing.

- The residual lives mostly in a few strata: Write-call arguments (F3 ALIVE in that tool stratum) and claude-opus-4-6
  sessions. That looks like constants inside code the model writes, not invented measurements.
- If that reading holds, round numbers in model-originated integers say more about which model wrote the content, and
  what kind of content, than about fabrication.

The pooled kill and the near-collapse on E (0.263 vs 0.25) both point the same way: what remains is model-specific.

**P2's three swechat cells are stable but not usable as a per-reference flag.**

- They replicate on fresh E at almost the same rates:
  - CC main: 0.144 on B, 0.136 on E.
  - CC subagent: 0.077 on both.
  - Codex subagent: 0.131 on B, 0.119 on E.
- No parser, truncation, join, sampling or dominance artifact explains them. Every raw audit found 0 of 30
  contributions changed.
- They stay WEAK because the honest base rate itself is 8–14% of deep reads. The mechanism holds up as a measurement.
  As a detector it has too many false positives at the reference level.

**The opencode E ALIVE is not evidence.** It depends on the logged root-rule deviation and on one repo.

**Possible follow-ups.** These are out of scope here and were not done.

- Test whether the residual round-number excess is specific to Write or Edit content, and whether it disappears when
  numeric literals inside code are excluded. This would be a new pre-registered rule, not a rescue.
- Extend the cc_local raw reader to resume-family member files. This is 5 of 30 audited events.

## What could not be measured

- **cc_local P4 AC1:** 5 of 30 audited calls sit in other resume-family members' main files. Their names are not in
  the IR, and they were not searched.
- **P4 AC1 raw readers:** none exists for Gemini or Cursor raw formats. None was sampled (`format_not_implemented` = 0).
- **P2 AC1:** the enumeration source (a basename in an earlier enumeration result) is not re-derived from raw.
- **AC5 NOT_RUN** for cc_local and aiv_cc: there is no population table.
- **aiv_cc K2:** not testable, because every run is a resume.
- **Strata UNTESTABLE** wherever an axis has fewer than 2 reportable strata. Each is listed per candidate in
  `stratification.confinement`.
- **Pooled reproduction:** B k/n match Phase B, but CIs can differ because of session order in the bootstrap (see
  `deviations`).
