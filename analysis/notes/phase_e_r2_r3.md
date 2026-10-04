# Phase E A1 second pass: Phase D proposals R2 and R3 (item r2_r3)

**This file is interpretation.** The raw numbers are in `analysis/out/phase_e/r2_r3.json`, written by
`analysis/probes/phase_e_r2_r3.py` (runtime 53.7 s, script sha256-LF `c8f358fe7e47…`). Every number below appears in that
JSON; paths are relative to its root. The run was made under the frozen pre-registration: `check_frozen()` passed,
prereg_e.json sha256 `4c77ac53eda3…`, spec module sha256-LF `31924af28f05…` (equal to the prereg value). Rates are
k/n [95% CI]. "s" means sessions. W[] is a Wilson interval over sessions (the prereg's CI method for session shares).

Rules applied: `a1.proposal_rules` (ALIVE / WEAK / DEAD from the session-level honest flag rate plus the N7 cells of the
proposal's detector), the R2 Phase D kill rule (session rate > 0.05 → DEAD, stop the line), the R3 coverage stop rule
(< 0.005 of tool results → cap WEAK), artifact checks AC1–AC5 on B ∪ E, the stratification axes, and `survival_status()`.
Neither proposal has a Phase B verdict, so `survival_status()` starts from the E label.

## Verdicts (`verdicts`)

| Candidate | B | E (replication) | B ∪ E | Status | Final | Deciding number |
|---|---|---|---|---|---|---|
| R2 image-token ledger, aiv_cu Gemini strata | DEAD | ALIVE | **DEAD** | **KILLED** | DEAD | B ∪ E session honest flag rate 44/807 = 0.0545 W[0.0409, 0.0724] > 0.05 (`R2.verdict_blocks.BuE`, `R2.kill_test`) |
| R3 git window, swechat/claude_code (E not blind) | WEAK | WEAK | WEAK | **SURVIVES (E not blind)** | WEAK | honest 2/976 = 0.0020 W[0.0006, 0.0074]; no N7 single-call DETECTS, 15 PARTIAL cells on E (`R3.units.swechat/claude_code`) |
| R3 swechat/codex | INSUFFICIENT_N | INSUFFICIENT_N | INSUFFICIENT_N | NOT_RUN (NOT_REPLICABLE_AT_N) | — | 7 decided sessions in B ∪ E (< 30); coverage 0.0033 < 0.005 |
| R3 swechat/opencode | INSUFFICIENT_N | INSUFFICIENT_N | INSUFFICIENT_N | NOT_RUN (NOT_REPLICABLE_AT_N) | — | 8 decided sessions; coverage 0.0022 < 0.005 |
| R3 swechat/gemini | INSUFFICIENT_N | INSUFFICIENT_N | INSUFFICIENT_N | NOT_RUN (NOT_REPLICABLE_AT_N) | — | 9 decided sessions; coverage 0.0061 |

20 verdict cells were computed (`n_verdict_cells`). The "NOT_RUN" status for the three small R3 units is what the
frozen `survival_status()` returns when no level exists. It means "too few sessions to judge", not "not attempted": the
statistic was computed and is in the JSON.

Plain reading:
- **R2 is killed.** Its detector works against tampering, but its honest false-positive rate per session is just over the
  pre-registered 0.05 budget. The rule says stop the line, so this item stops here.
- **R3 survives at WEAK in one unit.** On swechat/claude_code the honest flag rate is near zero. But the detector
  catches no single-call attack well, and its E split is not blind. In every other harness there are too few commit
  claims to judge.

---

## R2: the Gemini image-token ledger (KILLED)

**What was measured.**
- 807 sessions of the gemini-pro and gemini-flash strata: 404 in B, 403 in E.
- 27,072 windows, every one decided. No model fell outside a lattice unit (`R2.context_BuE`).
- The unit rule is the pre-registered A rule. gemini-3-pro-preview and gemini-3.8-flash had no GUI windows on A, so
  they take the gemini-3 family unit 1,064 (`R2.unit_rule`).
- All 807 sessions decide at least one window. The session-rate denominator choice (deviation 2) therefore makes no
  difference here.

**The window-level ledger is as clean as Phase D said, on the non-GUI side.**
- Windows with no GUI call: 0 of 14,446 show any change in prompt IMAGE tokens, Wilson hi 0.00027
  (`R2.context_BuE.nongui_windows_with_change`).
- Every window holds at most one GUI call (`R2.context_BuE.k_units_by_n_gui`).
- 12,538 GUI windows increase by exactly one lattice unit.
- The failures are on the GUI side.
  - **53 of 12,626 GUI windows have no increment**, 0.0042 [0.0032, 0.0055]: 35 in B, 18 in E.
  - **35 GUI windows in B are off-lattice.** Every one is +2,160 tokens, from gemini-3-pro-preview
    (`R2.context.B.off_lattice_d_image_values`).
- Clustered over sessions, the window-level flag rate is 88/27,072 = 0.0033 [0.0016, 0.0054]
  (`R2.verdict_blocks.BuE.unit_rate_clustered`).

**Why a 0.3% window rate becomes a 5% session rate.**
- A session is flagged if any of its windows is. The median Gemini session has 17 GUI windows (p95 35;
  `R2.context_BuE.gui_windows_per_session`).
- Flags are mostly isolated. The median flagged session has one violating window; the max is 22, in one 2,160-unit
  session (`R2.context_BuE.violations_per_flagged_session`).
- So per-window misses compound across a session. Phase D listed this compounding as unmeasured; this item measures it.

| population | flagged sessions / decided | rate [W 95%] | honest half of the rule |
|---|---|---|---|
| B | 26/404 | 0.0644 [0.0443, 0.0926] | DEAD (> 0.05) |
| E | 18/403 | 0.0447 [0.0284, 0.0695] | ALIVE (≤ 0.05, hi ≤ 0.10) |
| **B ∪ E** | **44/807** | **0.0545 [0.0409, 0.0724]** | **DEAD: the kill fires** |

**Status: KILLED.**
- The Phase D kill rule is evaluated on B ∪ E, the population the prereg names for R2. It fires
  (`R2.kill_test.fires_BuE` = true).
- On E alone it would not fire (`fires_E` = false). E alone gives ALIVE (`R2.verdict_blocks.E.label`).
- B ∪ E is the verdict population, so the E result does not rescue the candidate.
- The candidate is also CONFINED on two axes: the agent cluster and the model generation. Only agent #1 and gemini-2.5
  are signal-bearing (`R2.confined_axes`).
- B's point (0.0644) lies inside E's CI (`R2.artifact_checks.AC5_sampling.shift.SHIFT` = false). So the B/E difference
  is within sampling noise, not a split artifact.

**The kill was attacked as an artifact. It held.**
- **AC1 parser.** 30 of the 88 violating windows were drawn and looked up in the raw `computer_use_turns.jsonl.gz`
  (2,510,487 lines streamed).
  - All 30 were found.
  - In all 30, the raw `usageMetadata.promptTokensDetails` IMAGE difference and the raw GUI class equal the IR values.
  - In all 30, no raw action row is missing from the window (`R2.artifact_checks.AC1_parser`, field_differs 0,
    contribution_changed 0).
  - The misses are in the provider's own usage record, not in our parser.
- **AC2 truncation.** 0 windows dropped. **AC3 join.** 18 windows dropped, still 44/807. **AC5 post-stratified.** 0.0545
  [0.0390, 0.0700]. All three keep DEAD.
- **AC4 dominance.** The candidate is dominated by agent (top share 0.470) and by model (0.367). No leave-out lowers
  the label.

**What drives it (post hoc, not a verdict).**

| session modal model | flagged / sessions | rate |
|---|---|---|
| gemini-3-pro-preview | 9/58 | 0.155 |
| gemini-3.1-pro-preview | 11/187 | 0.0588 |
| gemini-3.5-flash | 9/160 | 0.0563 |
| gemini-2.5-pro | 13/296 | 0.0439 |
| gemini-2.5-pro-preview-06-05 | 2/75 | 0.0267 |

(`R2.stratification["model (session modal)"]`.)

- By generation: gemini-3 29/428 = 0.0678 against gemini-2.5 15/379 = 0.0396 (`…["model generation (R2 stratum)"]`).
- **The gemini-3-pro-preview agent (#4) carries the 2,160-token images.** That image size is a model resolution
  setting, not tampering, and the A-derived family unit of 1,064 cannot represent it.
  - Leaving that agent out gives 35/749 = 0.0467, under the budget (`R2.artifact_checks.AC4_dominance.kinds["repo
    (agent_id)"].leave_outs`).
  - That leave-out raises the label, and a check may only lower it. So it is reported, not used.
  - Even without that agent, gemini-3.1-pro and gemini-3.5-flash are each above 0.05 on their own, from plain
    no-increment misses.
- An honest reading: **the ledger is near-exact per window, but not exact enough to give a per-session flag inside a 5%
  budget on sessions of ~17 screenshots.** A per-window or per-k-windows decision unit might fit the budget. That would
  be a new definition, so it is not run here.

**The detector side works, and that does not change the verdict.** N7 cells (from
`analysis/out/phase_e/n7_content_shards/aiv_cu_{B,E}.json`, `R2.n7_cells`) on E:

| attack | recall | FPR | label |
|---|---|---|---|
| image_relabel_gui | 305/325 = 0.938 | 0.055 | DETECTS |
| image_insert_screenshot | 231/403 = 0.573 | 0.0447 | DETECTS |
| insert_pair_squeezed | 116/403 | — | PARTIAL |
| insert_pair_consistent | 101/403 | — | PARTIAL |
| delete_pair | 70/403 | — | PARTIAL |
| inline_fabrication | equals its FPR | — | BLIND |

- inline_fabrication is BLIND by design: R2 reads prompt IMAGE tokens, not output usage.
- The N7 FPR equals this item's honest rate exactly, 26/404 on B and 18/403 on E. Two independent scripts ran the same
  detector on the same sessions and agree.

**Nulls and untested regimes.**
- The > 40 GUI-window regime that Phase D asked for is still untested. One E session exceeds 40; no B session does
  (`R2.context.*.sessions_gt40_gui_windows`).
- gemini-3.8-flash shows 1 GUI window in 682 windows (`R2.context_BuE.by_model`). It was tested, but it carries almost no
  GUI evidence.

---

## R3: the git execution window (SURVIVES at WEAK on swechat/claude_code; E not blind)

**Coverage first: the stop rule does not fire for claude_code.**
- 5,844 of 374,420 tool results (0.0156) carry at least one generator-class commit claim (`coverage.BuE.share_generator`).
  E alone gives 0.0162.
- Results whose claim also resolves and decides are 2,512 (0.0067). That is also above 0.005, so the two readings of
  "claims cover" agree.
- The cap does fire for codex (0.0033) and opencode (0.0022). It does not fire for gemini (0.0061).

**Resolution.**
- 2,513 of 5,872 generator claims resolve against the external commit table: 0.428 [0.415, 0.441]. By level: 2,363
  linked, 143 same-repo, 7 other-repo.
- The other 3,359 abstain (`context_BuE.by_class.generator`).
- Phase D quoted 0.358 non-resolution, on a different denominator. Here 0.572 of all generator claims do not resolve.
  **So the detector abstains on most commit claims.**

**The honest flag rate is close to zero.**
- B ∪ E: 3 of 2,513 decided claims are out of window. At session level that is 2/976 = 0.0020 [0.0006, 0.0074].
- E: 0 of 1,244 claims and 0/489 sessions, W hi 0.0078 (`verdict_blocks.E`).
- Timing of the in-window claims:
  - commit_date minus call stamp: median −0.087 s, p1 −0.897 s;
  - commit_date minus result stamp: always negative, max −0.096 s (`…generator.offset_commit_minus_*`).
- **The three flagged claims are re-stamped copies.**
  - All three are in B and are `[WIP]` commits. They resolve only at the same-repo level and have a zero call→result
    delta.
  - Each call id also appears in another session, and the commit predates the call by 11,235 s, 2,713 s and 158 s
    (`flagged_claims`).
  - AC1 found all three in the raw transcripts with identical stamps (3/3, 0 differ). The re-stamping is in the log,
    not in our parser.
  - AC3's join-clean filter removes all three: 0/974, still WEAK. So the known benign cause, resume/fork copies,
    explains the whole honest flag set.
- AC2 dropped 12 truncated claims: 2/972. AC5 post-stratified: 0.0016 [0, 0.0040]. No SHIFT between B and E.
- AC4: one model holds 0.818 of the decided sessions. Every leave-out stays WEAK; without that model, 2/178.
- Strata: no axis is CONFINED. Model has 3 reportable strata, repo 8 and length 3. The tool axis is UNTESTABLE, since
  every claim comes from shell.
- The denominator context audit (30 in-window claims checked against raw transcripts, no verdict effect) also matched
  30/30.

**Why WEAK and not ALIVE: the N7 half.**
- On E (`n7_cells.E`, FPR 0/500 in every cell), no single-call attack reaches DETECTS.
- PARTIAL cells:

  | attack | recall on E |
  |---|---|
  | insert_pair_consistent | 83/500 = 0.166 |
  | reorder_adjacent_pairs | 13/500 |
  | rewrite_consistent_k, k = 2 | 45/500 |
  | rewrite_consistent_k, k = 5 | 65/500 |
  | time_tail_* (shift every later event) | 27/500 to 161/500 |

- BLIND cells:
  - time_result_late is 0/500 at every D. Moving a result later only widens the window.
  - time_result_early: at most 4/500.
  - sub_matched_bytes, sub_single_digit and reorder_lines: at most 1/500.
- **Interpretation.** The window binds a commit to the call that printed it. A single forged or replayed result
  usually has no resolvable generator claim, so the detector abstains. In 0.0156 of results a claim exists; it fires
  only when the forgery moves that call relative to its commit.
- **What would change WEAK to ALIVE:** a single-call attack type that targets commit-bearing results. The N7 grid does
  not contain one, and Phase D's replay tamper is not in the prereg battery.

**Class separation was needed.**
- Re-reader commands (cat, tail, grep of saved output) printed 19 commit lines. 5 of them resolve, and **all 5 are out
  of window** (5/5, W[0.566, 1.0]; `context_BuE.by_class.rereader`).
- The "other" class gives 2/12.
- Had the pre-registered class split not excluded them, the honest rate would have included them. This replicates
  Phase C's after-the-fact classification, now under a rule fixed in advance.

**Small units (nulls of coverage, not of the window).**

| unit | sessions | claims | sessions flagged | coverage | cap |
|---|---|---|---|---|---|
| codex | 7 | 19 | 0 | 0.0033 | yes |
| opencode | 8 | 13 | 0 | 0.0022 | yes |
| gemini | 9 | 11 | 0 | 0.0061 | no |

- Every unit is INSUFFICIENT_N (< 30 decided sessions) on B, E and B ∪ E.
- Their N7 halves are DEAD or INSUFFICIENT_N in every cell. At these sizes R3 tells us nothing about transfer.

**Freshness.** R3 is in `E_SEEN_candidates`, so every R3 status carries "(E not blind)". Phase C's commit-witness lens
and its skeptic read the whole swechat population. E is therefore a re-measurement, not a blind replication. Track C must
say the same of H.

---

## Survival mechanics as applied

- **R2:** E label ALIVE. Checks, in order:
  - AC2, AC3 and AC5 pass at the B ∪ E label;
  - confinement gives a one-level downgrade;
  - the Phase D kill fires.

  Result: `KILLED`, final DEAD (`R2.survival`).
- **R3 claude_code:** E label WEAK. AC1–AC5 pass, AC4 passes, nothing is confined. Result: `SURVIVES (E not blind)`,
  final WEAK.

## Deviations (`deviations`; none changes a verdict)

1. **File name.** `r2_r3.json` / `phase_e_r2_r3.py`, the item key the orchestrator assigned, instead of `a1_<candidate>`.
2. **Session-rate denominator.** Flagged sessions over sessions with at least one decided unit. This is conservative.
   For R2 every session decides, so it makes no difference.
3. **R2 'models/' prefix.** `models/gemini-2.5-pro-preview-05-06` gets the gemini-2.5 family unit instead of abstaining.
   That decides 171 windows in 5 sessions, with 0 flagged. Had they abstained, B ∪ E would be 44/802 = 0.0549: still
   over 0.05, so still killed (`R2.deviation_models_prefix_effect`).
4. **R2 AC1 field set.** Defined as raw IMAGE counts, raw GUI class, and missing action rows.
5. **R3 AC1 for codex/gemini.** A substring lookup only, but their numerators were empty.
6. **Check mechanics** as in `phase_e_a1_p1_p3`.
7. **AC4 weights** = decided sessions.
8. **R2 tool stratum** = the first call of the window.
9. **N7 split.** E cells are used for the E and B ∪ E verdicts, B cells for B.

## Caveats and what was not measured

- **The N7 inputs are other items' files, read as they stood.**
  - `n7_timing.json`: sha256-LF `f5f90363…`, mtime 03:58:08.
  - The two aiv_cu content shards are recorded in `R2.n7_meta`.
  - A re-run of `phase_e_n7_timing` was in progress when this item ran. If it rewrites `n7_timing.json`, R3's N7 half
    should be re-read. Its honest half would not change.
- **Not run here, because the prereg does not define them.** Phase D's replay tamper for R3 (a real commit line copied
  into a later call or another session) and the printed-duration leg. These would be new tests.
- **R2 regimes not covered:** above 40 GUI windows (n = 1 session), and the aiv_cc stripped-image case study.
- **Every positive in N7 is synthetic.** Recall is recall against our own tampering model.
