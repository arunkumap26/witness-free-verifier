# Second pass on the surviving candidates (Phase E, A1)

This file answers the A1 brief (`analysis/PHASE_E_PROMPT.md`). For each surviving candidate it says what was re-measured,
what was used to try to kill it, whether it survived, the deciding number, and whether split E replicated split B. The
candidates are the Probe 1–4 survivors, the Phase D proposals R1–R5 and the three follow-ups F1–F3.

**What is data here and what is not.**
- Every number is copied from a Phase E output under `analysis/out/phase_e/`. Each output was written by its own
  script under the frozen pre-registration (`analysis/PREREG_E.md`, `analysis/prereg_e.json`,
  `analysis/probes/prereg_e_common.py`, commit 55fc556). The file and JSON path are given next to each number.
- Paragraphs headed **Interpretation** are interpretation. Everything else is copied.
- The survival table (section 1) is also written, label by label, to `analysis/out/phase_e/second_pass.json`. That
  file is written by `analysis/probes/phase_e_second_pass.py`, which only assembles: it opens no cache, raw source or
  split. The same script checks every number in this file against the Phase E outputs (`md_number_check`). Command,
  from the worktree root: `PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_second_pass --check
  analysis/SECOND_PASS.md`.
- The item notes under `analysis/notes/phase_e_*.md` hold the full detail. This file is the summary across items.

**Pre-registration.**
- `check_frozen()` passed for every item and for the assembly (`second_pass.json check_frozen`).
- The spec module sha256-LF is `31924af28f05…`, equal to the pre-registered value.
- No threshold was changed after a result was seen.
- `prereg_e.json` itself changed after some items ran. Only `change_log` grew, with the pre-registered new-corpus
  extensions; the frozen spec did not change. The items record the sha they ran under.

**Conventions.**
- **Every positive in this file is synthetic.** Every recall, DETECTS, PARTIAL and positive-control number below is
  measured against the pre-registered N7 injectors (or an item's own positive-control injector) applied to real honest
  sessions. No corpus contains a known real fabricated tool result. Honest-baseline rates are not detections.
- k/n = rate [95% CI]. The CI is session-clustered unless marked W (Wilson). s = sessions (aiv_cc: runs).
- **B** is the Phase B split. Phase C also read it, so B is not blind for Phase C observations.
- **E** is the fresh Phase E split, and the replication.
- **B ∪ E** pooled is the re-measurement population and the population for every artifact check.
- cc_local, aiv_cc (single-agent case study) and whowhen have no E. They are re-measured on B only and labelled
  UNREPLICATED.
- cc_local is private: aggregates and labels only.
- aiv_cc is a **single-agent case study** wherever it appears.
- R3, R4 and R5 carry "(E not blind)": Phase C lenses read the whole swechat population, E included
  (`prereg_e.json splits.E_freshness`).

**Survival vocabulary** (`prereg_e.json survival_rule`, frozen `survival_status()`):

| Status | Rule |
|---|---|
| KILLED | E is DEAD, or an artifact check fails to DEAD, or a candidate kill test fires |
| DOWNGRADED | E is one level below Phase B, or a check, confinement or kill test lowers the label one level |
| SURVIVES | E ≥ Phase B, every check passes, and the candidate is neither CONFINED nor DOMINATED |
| NOT_RUN | no usable label exists, for example E and B ∪ E are INSUFFICIENT_N or the N7 leg is missing. This is not a null |

The artifact checks are AC1 parser, AC2 truncation, AC3 join, AC4 dominance and AC5 sampling. A check can only lower a
label ("no rescue"). A post-hoc subset or correction is reported as "post hoc, not a verdict".

---

## 1. Survival table (mechanical)

Source: `second_pass.json a1_rows`, `r1_rows`, `r2_r5_rows`. Each row there names the item path it was copied from.

| # | Candidate, unit | Phase B | E | B ∪ E | survival_status | Final | Deciding number |
|---|---|---|---|---|---|---|---|
| 1 | P1 latency, swechat/opencode | ALIVE | ALIVE | ALIVE | **DOWNGRADED** | WEAK | AC4: without the dominant repo, the generation-bound control G is 8 pairs from 6 s, below 30/5. UNTESTABLE_WITHOUT_DOMINANT, so capped at WEAK |
| 2 | P1 latency, cc_local (private) | ALIVE | — | ALIVE (B) | **DOWNGRADED (B only, unreplicated)** | WEAK | AC4: one project alias holds 1.0 of W and G; leaving it out leaves 0 pairs |
| 3 | P1 latency, swechat/claude_code | WEAK | ALIVE | WEAK | **DOWNGRADED** | WEAK (= Phase B) | K2: the B ∪ E floor is UNSTABLE, 35/279 series = 0.125 W[0.092, 0.169] |
| 4 | P3 zero-error tail, swechat/claude_code | ALIVE | ALIVE | ALIVE | **SURVIVES** | ALIVE | E: Z = 8/380 = 0.021 W[0.011, 0.041] |
| 5 | P2 knowledge precedence, CC main | WEAK | WEAK | WEAK | **SURVIVES** | WEAK | E: S_deep 608/4,466 = 0.136 [0.117, 0.156] |
| 6 | P2, CC subagent | WEAK | WEAK | WEAK | **SURVIVES** | WEAK | E: S_deep 612/7,920 = 0.077 [0.061, 0.097] |
| 7 | P2, opencode subagent | WEAK | ALIVE | WEAK | **DOWNGRADED** | WEAK | AC4: one repo holds 0.933 of S_deep events, so UNTESTABLE_WITHOUT_DOMINANT |
| 8 | P2, codex subagent | WEAK | WEAK | WEAK | **SURVIVES** | WEAK | E: S_path_any 62/523 = 0.119 [0.086, 0.153] |
| 9 | P2, aiv_cc main (single-agent case study) | WEAK | — | WEAK (B) | **KILLED (B only, unreplicated)** | DEAD | AC4 DOMINATED (4 of the top 5 run leave-outs cross 0.20) and CONFINED on tool |
| 10 | P4 round numbers, swechat/claude_code | ALIVE | ALIVE | ALIVE; F3 WEAK | **DOWNGRADED** | WEAK | F3: g = 0.118 is 0.464 of g_full on B ∪ E; ALIVE needs ≥ 0.5 |
| 11 | P4 round numbers, cc_local (private) | ALIVE | — | ALIVE; F3 WEAK | **DOWNGRADED (B only, unreplicated)** | WEAK | F3: 114/206 = 0.553 [0.131, 0.731]; the CI lo does not clear the ALIVE bar |
| 12 | P4 round numbers, swechat/* pooled | ALIVE | ALIVE | ALIVE; F3 WEAK | **KILLED** | DEAD | AC4: without claude-opus-4-6, g = 0.071 ≤ 0.075, which is COLLAPSE |
| 13 | R1 request-id bracket, swechat/claude_code | (exploratory) | ALIVE | ALIVE | **SURVIVES** | ALIVE | honest 21/7,008 streams = 0.00300 [0.00173, 0.00443]; on E, synthetic time_response_early 30 s recall 488/500 (CI lo 0.9585) against FPR 3/500 (CI hi 0.0175) |
| 14 | R1, cc_local (private) | (exploratory) | — | WEAK | **DOWNGRADED (B only, unreplicated)** | WEAK | AC4: one project holds 0.9988 of streams; leaving it out leaves 1 stream |
| 15 | R2 image-token ledger, aiv_cu Gemini | (untested) | ALIVE | DEAD | **KILLED** | DEAD | Phase D kill rule: B ∪ E honest session rate 44/807 = 0.0545 W[0.0409, 0.0724] > 0.05 |
| 16 | R3 git window, swechat/claude_code | (untested) | WEAK | WEAK | **SURVIVES (E not blind)** | WEAK | honest 2/976 = 0.0020 W[0.0006, 0.0074]; no N7 single-call DETECTS |
| 17–19 | R3, codex / opencode / gemini | (untested) | INSUFFICIENT_N | INSUFFICIENT_N | **NOT_RUN (NOT_REPLICABLE_AT_N) (E not blind)** | — | 7 / 8 / 9 decided sessions in B ∪ E (< 30) |
| 20 | R4 dual rendering, swechat/claude_code | (untested) | WEAK | WEAK | **SURVIVES (E not blind)** | WEAK | honest 0/2,998 sessions; best N7 (synthetic) cell on E rewrite_consistent_k=5, recall 205/500 = 0.41 (PARTIAL) |
| 21 | R4, cc_local (private) | (untested) | — | WEAK (B) | **SURVIVES (B only, unreplicated)** | WEAK | honest 0/110 sessions; N7 best PARTIAL |
| 22 | R5 usage ledger, swechat/claude_code | (untested) | ALIVE | ALIVE | **SURVIVES (E not blind)** | ALIVE | honest 23/3,165 = 0.0073 [0.0048, 0.0109]; on E, synthetic delete_response recall 396/500 = 0.792 [0.754, 0.825] |
| 23–24 | R5, codex / opencode | (untested) | NOT_RUN | NOT_RUN | **NOT_RUN (NOT_REPLICABLE_AT_N) (E not blind)**: the function's suffix for a missing E label; the cause is the missing N7 leg | — | N7 R5 cells exist only for claude_code; honest leg codex 4/126, opencode 4/405 |
| 25 | R5, gemini | (untested) | INSUFFICIENT_N | NOT_RUN | **NOT_RUN (NOT_REPLICABLE_AT_N) (E not blind)** | — | 13 decided sessions on E; honest 6/34 on B ∪ E |

**Counts** (`second_pass.json counts`), over 25 candidate × unit rows:

| | Count |
|---|---|
| SURVIVES | 9 |
| DOWNGRADED | 7 |
| KILLED | 3 |
| NOT_RUN | 6 |
| Final ALIVE | 3, all in swechat/claude_code: P3 zero-error tail (honest baseline only; no positive control), R1, and R5 (E not blind) |
| Final WEAK | 13 |
| Final DEAD | 3 |

- **No SHIFT.** In no candidate does the B point fall outside the E CI (AC5 `SHIFT` = false in every `a1_*`, `r2_r3`
  and `r4_r5` candidate that ran AC5).
- **The follow-ups move no verdict.** F1's adopted corrections are frozen into R1's FP_eff. F2 cannot raise or lower
  P1 (`f2_floor_shift.json verdict_effect`). F3 is the kill test that capped P4.
- **The R1 rows are the only labels assembled here.**
  - `f1_bracket.json` left R1 at PENDING_N7: no N7 output existed when it ran (`r1.*.verdict.label`).
  - `n6_grid.json` composed the R1 label from f1 and `n7_timing.json` (`n6_grid.json deviations[2]`).
  - `phase_e_second_pass.py` then called the frozen `survival_status()` on that label
    (`second_pass.json r1_rows[*].survival_inputs`, `.checks`). Both final labels equal the N6 cells
    (`agrees_with_n6_cell` = true).

---

## 2. Probe candidates (P1–P4)

### 2.1 P1 latency physics, swechat/opencode: DOWNGRADED → WEAK

Source: `a1_p1_p3.json candidates['P1/swechat/opencode']`, `verdicts['P1/swechat/opencode']`.

**Re-measured.**

| population | fp_share | AUC | G control |
|---|---|---|---|
| B (reproduces Phase B exactly; `reproduction_B_vs_phase_b.all_match` = true) | 7/4,419 | 0.99916 | 127 pairs from 12 s |
| E (replication) | 6/3,283 = 0.0018 [0, 0.0050], 186 s | 0.9986 [0.9958, 1.0000] | 37 pairs from 7 s |
| B ∪ E | 13/7,702 = 0.0017 [0.0004, 0.0033] | 0.9990 [0.9981, 0.9996] | 164 pairs from 19 s |

**Kill attempts** (B ∪ E):

| check | result |
|---|---|
| AC1 parser | 13/13 numerator events found raw, 0 differ |
| AC2 truncation | 1,704 truncated W pairs dropped: fp 11/5,998, AUC 0.9988. ALIVE |
| AC3 join | 0 pairs dropped |
| AC4 dominance | **fires (cap).** One repo holds 0.863 of W and 0.951 of G. One model, gpt-5.3-codex, holds 0.837 of W and 0.970 of G. Without the repo, W is 1,052 pairs from 68 s with fp 7/1,052, but G is 8 pairs from 6 s. Without the model, G is 5 pairs from 5 s. Result: UNTESTABLE_WITHOUT_DOMINANT |
| AC5 sampling | weighted fp 0.0016, AUC 0.9991. ALIVE; no SHIFT |
| K1 control composition | dropping the top G session (35 pairs, 0.213 of G) gives AUC 0.9992 [0.9982, 0.9998]. PASS |
| K2 floor stability | untested: 20 series in B ∪ E, 5 in E (< 30) |
| K3 stamp quality | 19 W pairs dropped. ALIVE |
| strata | No axis is CONFINED. repo#2 has fp 1/571 and repo#3 fp 6/324; both are WEAK only because they have no G |

**B vs E.** Replicated: ALIVE on both, no SHIFT. E's G (37 pairs from 7 s) is just above the 30/5 minimum.

**Plain statement.** The ALIVE verdict does not survive the dominance check. The generation-bound control exists only
inside one repo and one model, so separability cannot be tested anywhere else.

**Interpretation.** OpenCode read/grep/glob latencies sit far below generation time in every repo with enough data.
What fails to generalise is the comparison against generated output, not the work-bound side.

### 2.2 P1 latency physics, cc_local (private; B only): DOWNGRADED (B only, unreplicated) → WEAK

Source: `a1_p1_p3.json candidates['P1/cc_local']`.

- **Re-measured (B only).** fp 1/1,019 = 0.0010 [0, 0.0033] over 112 s. AUC 0.919 [0.881, 0.971]. G 153 pairs from
  12 s. This reproduces Phase B exactly.
- **Kill attempts.**

  | check | result |
  |---|---|
  | AC4 | **fires (cap).** One project alias holds 1.0 of W and of G, and leaving it out leaves 0 pairs. claude-opus-5 holds 0.932 of W; leaving it out leaves W 69 pairs from 5 s |
  | K1 (the bimodal G) | dropping the 47 workflow pairs *raises* AUC to 0.983 [0.968, 0.996], G 106 pairs from 11 s. Also dropping the top G session gives 0.982 [0.963, 0.999], G 84 from 10 s. PASS |
  | AC1 | 1/1 found raw, 0 differ |
  | AC2 | 197 W pairs dropped. ALIVE |
  | AC3, K3 | 0 dropped |
  | K2 | untested (5 series) |
  | AC5 | NOT_RUN: no population table |
  | strata | glob is WEAK (AUC 0.814). The model and repo axes are UNTESTABLE |
- **B vs E.** No E exists. **UNREPLICATED.**
- **Plain statement.** This is one developer's one project on essentially one model. It cannot support a claim beyond
  that cluster, and the cap records this.

### 2.3 P1 latency physics, swechat/claude_code: DOWNGRADED → WEAK (unchanged from Phase B)

Source: `a1_p1_p3.json candidates['P1/swechat/claude_code']`. Floor follow-up: F2, section 4.2.

**Re-measured.**

| population | fp_share | AUC | floor step share | label |
|---|---|---|---|---|
| B (reproduces Phase B) | 72/20,937 | 0.98702 | 21/156 = 0.135, UNSTABLE | WEAK |
| E | 63/18,256 = 0.0035 [0.0024, 0.0046], 926 s | 0.986 [0.973, 0.995]; G 3,320 from 823 s | 10/123 = 0.081 W[0.045, 0.143], STABLE | **ALIVE** |
| B ∪ E | 135/39,193 = 0.0034 [0.0027, 0.0042] | 0.9866 [0.9794, 0.9922] | 35/279 = 0.125 W[0.092, 0.169], UNSTABLE (30 up, 5 down) | WEAK |

**Kill attempts** (B ∪ E). Every check kept fp and AUC ALIVE:

| check | result |
|---|---|
| AC1 | 30/30 found raw, 0 differ |
| AC2 | 738 W and 4 G truncated pairs dropped |
| AC3 | 392 W and 50 G pairs dropped, including 1,461 call ids copied across sessions |
| K3 | 81 W and 14 G whole-second pairs dropped |
| AC5 | weighted fp 0.0034, AUC 0.9866 |
| AC4 | claude-opus-4-6 holds 0.713 of W and 0.815 of G; the null-user pseudo-cluster holds 0.392 of W. None of the 11 leave-outs moves fp or AUC off ALIVE. Without claude-opus-4-6: W 11,256, G 1,319, AUC 0.991 |
| K1 | the top G session holds 83 pairs (0.012 of G). PASS |
| strata | ALIVE in every reportable stratum: 3 tools, 5 of 6 models, 33 repos, 3 length terciles. Nothing is CONFINED |
| **K2 floor stability** | **fires.** UNSTABLE on B ∪ E, so E's ALIVE drops one level to WEAK |

**B vs E.** Separability replicates (no SHIFT on fp or AUC). The floor does not replicate the same way: B is UNSTABLE
(0.135) and E is STABLE (0.081).

**Plain statement.** The status reads DOWNGRADED because E (ALIVE) was lowered, but the final label equals Phase B's
WEAK. The second pass confirms WEAK; it neither raises nor loses it.

**Interpretation.** This is the most robust separability number in the A1 set. It holds on fresh data, under every
artifact check, without the dominant model or user, and in every stratum. What holds it at WEAK is the floor, and F2
(section 4.2) could not explain the floor. Per split, the floor result sits on either side of the 0.10 line (B 0.135,
E 0.081). The pre-registered population for K2 is B ∪ E, which is UNSTABLE, so K2 fires and the WEAK label stands; the
per-split values do not soften it.

### 2.4 P2 knowledge precedence: three SURVIVES, one DOWNGRADED, one KILLED (all WEAK or DEAD)

Source: `a1_p2_p4_f3.json candidates['P2/…']`, `verdicts['P2/…']`, `instrument_check`. S_deep is the
knowledge-from-nowhere share of deep first-try accesses; lower is better. ALIVE needs ≤ 0.05.

| cell | B (reproduces Phase B) | E (replication) | B ∪ E | status → final |
|---|---|---|---|---|
| CC main | 671/4,655 = 0.144 [0.125, 0.163], 586 s | 608/4,466 = 0.136 [0.117, 0.156], 511 s, WEAK | 1,279/9,121 = 0.140 [0.127, 0.153], 1,097 s | **SURVIVES → WEAK** |
| CC subagent | 525/6,850 = 0.077 [0.062, 0.091], 296 s | 612/7,920 = 0.077 [0.061, 0.097], 306 s, WEAK | 1,137/14,770 = 0.077 [0.067, 0.089], 602 s | **SURVIVES → WEAK** |
| opencode subagent | 16/219 = 0.073 [0.020, 0.150], 53 s | 10/232 = 0.043 [0.004, 0.095], 49 s, ALIVE | 26/451 = 0.058 [0.024, 0.101], 102 s | **DOWNGRADED → WEAK** |
| codex subagent (S_path_any) | 104/795 = 0.131 [0.099, 0.163], 36 s | 62/523 = 0.119 [0.086, 0.153], 23 s, WEAK | 166/1,318 = 0.126 [0.103, 0.149], 59 s | **SURVIVES → WEAK** |
| aiv_cc main (single-agent case study; S_path_any) | 710/3,689 = 0.192 [0.081, 0.351], 53 runs | — | B only | **KILLED (B only, unreplicated) → DEAD** |

**Kill attempts.**
- **Instrument check** (CC main S_symbol_ref ≤ 0.10): B ∪ E 2,541/89,985 = 0.028; E 1,299/43,149 = 0.030. It holds,
  so no cap applies.
- **K1, strict workspace-root rule.**
  - CC main, CC subagent and aiv_cc: 0 rows affected.
  - codex: 79 rows affected, no label change.
  - opencode: 4,242 rows lose their depth, leaving 0 decidable S_deep accesses. The verdict falls back to S_path_any
    461/4,863 = 0.095, capped at WEAK. K1 did not fire.
- **K2, sessions with complete records** (reported only).
  - CC main: 616/4,195 = 0.147.
  - CC subagent: 490/6,801 = 0.072.
  - aiv_cc: INSUFFICIENT_N, because every run resumes the SDK session.
- **AC1.** 0 of the audited events changed in every cell: 30 in four cells, and 26 in opencode, where every numerator
  event was audited.
- **AC2, AC3, AC5.** PASS in every cell; AC5 is NOT_RUN for aiv_cc.
- **AC4.**
  - CC main: PASS.
  - CC subagent: PASS. Dropping claude-opus-4-6 gives 68/1,598 = 0.043, a *higher* label, which is ignored (no
    rescue).
  - opencode: **UNTESTABLE_WITHOUT_DOMINANT.** One repo holds 0.933 of S_deep events.
  - codex: UNTESTABLE_WITHOUT_DOMINANT, no label change.
  - aiv_cc (single-agent case study): **DOMINATED.** Leaving out any one of 4 of the top 5 runs moves S_path_any to
    0.202–0.212.
- **Strata.**
  - aiv_cc (single-agent case study) is **CONFINED on tool**: Read 7/2,617 is WEAK, while mcp__village__bash 190/376 = 0.505 and shell
    120/267 = 0.449 are DEAD before the cap.
  - Every other cell: no confinement.

**B vs E.** All three swechat Claude Code and codex cells replicate at almost the same rate, with no SHIFT. opencode's
E ALIVE comes from the Phase B root-rule deviation and from one repo.

**Plain statements.**
- **P2 aiv_cc main is KILLED** (single-agent case study, B only, unreplicated). Its WEAK rests on single runs and on
  Read accesses only.
  - The kill depends on two logged rule readings (`a1_p2_p4_f3.json deviations`, "antecedents-incomplete cap in
    strata and AC4").
  - With both readings reversed, the cell would stay WEAK. With only the AC4 reading reversed, it is still KILLED by
    confinement.
- **No P2 cell is ALIVE on B ∪ E.**

**Interpretation.** The honest knowledge-from-nowhere base rate is stable: 0.077 to 0.140 of deep reads in Claude Code
(B ∪ E), nearly the same on both splits, and every raw audit is clean. That is a reliable measurement and an unusable per-reference flag. P2 does not move
from WEAK.

### 2.5 P3 zero-error tail, swechat/claude_code: SURVIVES → ALIVE

Source: `a1_p1_p3.json candidates['P3zero/swechat/claude_code']`, `verdicts['P3zero/swechat/claude_code']`.

**Re-measured.**

| population | Z = long sessions (≥ L75 = 134 calls) with zero primary errors |
|---|---|
| B (reproduces Phase B) | 9/413 = 0.022 W[0.012, 0.041] |
| E (replication) | 8/380 = 0.021 W[0.011, 0.041]; E0 0.00074; Z/E0 28.4. ALIVE |
| B ∪ E | 17/793 = 0.021 [0.013, 0.034] |

**Kill attempts** (B ∪ E):

| test | result |
|---|---|
| K1 (≥ 10 shell calls) | 17/780 = 0.022. PASS |
| **K2 (without cc_tool_use_error)** | 62/793 = **0.078 [0.061, 0.099]**, under the 0.10 downgrade line. PASS, and the closest call in its item (`a1_p1_p3`). On E alone: 28/380 = 0.074 [0.051, 0.104]. cc_tool_use_error is 4,905 of the 14,556 primary errors |
| K3 (per model and repo) | no stratum fires. claude-opus-4-6 holds 0.802 of long sessions, with Z 15/636 = 0.024. The largest repo holds 0.169, with Z 0/134 |
| K4 (L90 = 220, reported only) | B ∪ E 1/432; E 1/208; B 0/224 |
| AC1 | 17/17 zero-error sessions re-derived from raw, 0 differ |
| AC2 | 26/784 = 0.033. ALIVE |
| AC3 | 17/787. ALIVE |
| AC4 | the null-user cluster (0.363) and claude-opus-4-6 leave-outs stay ALIVE. Without the latter: 2/157 = 0.013, Wilson hi 0.045 |
| AC5 | 0.021 [0.011, 0.033]; no SHIFT |
| strata | model (4 strata) and repo (8) are not CONFINED. Length is UNTESTABLE by construction |

**B vs E.** Replicated: ALIVE on both, no SHIFT.

**Plain statement.** P3 has no positive control. SURVIVES means the honest baseline is stable: Z = 0.021 of long Claude
Code sessions are error-free. It does not show that a fabricated session would be error-free. Its K2 margin is small:
the CI hi is 0.099 on B ∪ E and 0.104 on E.

### 2.6 P4 round numbers (with F3): two DOWNGRADED, one KILLED

Source: `a1_p2_p4_f3.json candidates['P4round/…']` (the F3 block is also written alone to `f3_round.json`). F3's rule
and its result are in section 4.3.

| cell | Phase B (B) | E | F3 result | other checks | status → final |
|---|---|---|---|---|---|
| swechat/claude_code | 127/300 = 0.423 [0.334, 0.520] against M_all 2,365/20,419 = 0.116 [0.110, 0.122]. ALIVE | 91/248 = 0.367 [0.289, 0.454] against 2,001/17,722 = 0.113. ALIVE | WEAK on B ∪ E and on E → cap WEAK | AC1 0/30 changed. AC2, AC3 and AC5 PASS. AC4 UNTESTABLE_WITHOUT_DOMINANT: claude-opus-4-6 holds 0.736 of the values, and without it 88 values remain (< 100). Cap WEAK, no change | **DOWNGRADED → WEAK** |
| cc_local (private, B only) | 221/341 = 0.648 [0.435, 0.786] against 2,243/18,550 = 0.121. ALIVE | — | WEAK → cap WEAK | AC1 0 changed among 25 located (5 not located: resume-family files). AC4 UNTESTABLE (one project holds 1.0). AC5 NOT_RUN | **DOWNGRADED (B only, unreplicated) → WEAK** |
| swechat/* pooled | 141/322 against 2,777/23,570. ALIVE | ALIVE | WEAK → cap WEAK | **AC4 DOMINATED.** claude-opus-4-6 holds 0.664 of the values. Without it, F3 collapses: g = 0.071 ≤ 0.25 × 0.301 = 0.075 (107 values), a one-level downgrade | **KILLED → DEAD** |

**B vs E.** The full statistic replicates (ALIVE on E, no SHIFT). The parameter-free residual is weaker on E than on B
(section 4.3).

**Plain statements.**
- **The pooled swechat/\* round-number row is KILLED.** Without claude-opus-4-6 sessions its residual gap collapses.
- **P4 loses ALIVE in every unit.**
- cc_local is UNREPLICATED.

---

## 3. Phase D proposals (R1–R5)

The rule for every proposal (`prereg_e.json a1.proposal_rules`):
- **ALIVE:** the honest flag rate (session-level; stream-level for R1) is ≤ 0.05 with CI hi ≤ 0.10, **and** at least one
  single-call or single-response attack type DETECTS in N7 on E (on B for units without E).
- **WEAK:** the honest flag rate is ≤ 0.20 and at least one attack type is DETECTS or PARTIAL.
- **DEAD:** otherwise.

None of the proposals has a Phase B verdict, so `survival_status()` starts from the E label, or from the B label for a
unit without E (cc_local), as `r4_r5.json` did.

### 3.1 R1 request-id clock bracket: swechat/claude_code SURVIVES → ALIVE; cc_local DOWNGRADED (B only, unreplicated) → WEAK

Sources: `f1_bracket.json r1`, `units`, `step0`; `n7_timing.json cells`, `verdicts.per_unit_split_detector`;
`n6_grid.json cells.R1_bracket`; `second_pass.json r1_rows`. F1, the explanation of the honest failures, is in section
4.1.

**Re-measured (honest leg, stream level).**

| unit / split | streams | inconsistent | rate [CI] | sessions |
|---|---|---|---|---|
| swechat/claude_code B | 3,676 | 10 | 0.00272 [0.00112, 0.00466] | 1,610 |
| swechat/claude_code **E** | 3,332 | 11 | 0.00330 [0.00145, 0.00540] | 1,486 |
| swechat/claude_code B ∪ E | 7,008 | 21 | 0.00300 [0.00173, 0.00443] | 3,096 |
| cc_local B | 847 | 1 | 0.00118 [0, 0.00248]; W [0.00021, 0.00666] | 174 |

**Step 0 came first.** Committed code reproduced the uncommitted Phase C placebo on the same 3,676 streams.
- The honest count is 10.
- 5 s back-dating flags 1,448/3,676 = 0.3939 [0.3726, 0.4150], against the skeptic's 0.3923.
- 30 s back-dating flags 3,588/3,676 = 0.9761 [0.9703, 0.9817], against 0.9750.
- Later shifts flag 10 at each of 5, 30 and 300 s.
- `step0.result` = REPRODUCED, so no "(Step 0 NOT_REPRODUCED)" suffix applies.

**Kill attempts.**

| attempt | swechat/claude_code (B ∪ E) | cc_local (B) |
|---|---|---|
| Phase D kill rule: a tamper type whose CI lo ≤ the honest CI hi is a null for that type | bar 0.00443. 30 s back-dating clears: 6,857/7,008, CI lo 0.9746. Other single-response types clear too, e.g. id_swap_adjacent 6,685/7,008 = 0.9539 (CI lo 0.9481), so R1 is **not** "back-dating only" | bar 0.00248. 30 s back-dating 763/847, CI lo 0.874 |
| AC1 parser | 10/10 B and 11/11 E inconsistent streams match the raw transcripts, 0 differences | NOT_RUN: no cc_local raw file is opened |
| AC2 truncation | still 21 after dropping 4,199 truncated results | PASS |
| AC3 join | 21 → 11 on clean-joined inputs; label unchanged. PASS | PASS |
| AC4 dominance | model 0.809 and user 0.352 dominate, but every leave-out stays ALIVE-eligible. PASS | **fires (cap):** one project holds 0.9988 of the streams, and leaving it out leaves 1 stream |
| AC5 sampling | weighted 0.00298 [0.00171, 0.00443]. PASS | NOT_RUN |
| strata | 5 model, 42 repo and 3 length strata are reportable. No confinement | not confined |
| N7 leg (single-call DETECTS on E; B for cc_local) | 4 single-call types DETECT on E: time_response_early, time_result_late, id_swap_adjacent, id_splice_foreign | the same 4 types DETECT on B |

**Deciding N7 cells** (`n7_timing.json cells`, 500 synthetically tampered sessions per cell, honest FPR on the same
sessions untampered):

| cell | recall | honest FPR | label |
|---|---|---|---|
| CC E time_response_early 30 s | 488/500 (CI lo 0.9585) | 3/500 (CI hi 0.0175) | DETECTS |
| CC B time_response_early 30 s | 481/500 (CI lo 0.9414) | 6/500 (CI hi 0.0259) | DETECTS |
| CC E time_response_early 10 s / 5 s / 2 s | 429/500 / 163/500 / 3/500 | 3/500 | DETECTS / PARTIAL / BLIND |
| CC E id_swap_adjacent | 486/500 (CI lo 0.9536) | 3/500 | DETECTS |
| CC E id_splice_foreign, nearest / random | 395/500 / 17/500 | 3/500 | DETECTS / PARTIAL |
| CC E time_result_late 5 s | 272/500 (CI lo 0.5002) | 3/500 | DETECTS |
| cc_local B time_response_early 30 s | 169/186 | 1/186 | DETECTS |
| cc_local B id_swap_adjacent | 174/174 (CI lo 0.9784) | 1/174 (CI hi 0.0318) | DETECTS |

**B vs E.** Replicated. B's honest point 0.00272 lies inside E's CI [0.00145, 0.00540]. The same tamper types clear the
kill bar on B alone and on E alone (`r1["swechat/claude_code"].verdict_per_split`). The N7 label counts are identical:
DETECTS 21, PARTIAL 6 on both B and E (`n6_grid.json cells.R1_bracket['swechat/claude_code'].r1_composition`).

**What R1 does not see** (nulls against synthetic tampers, B ∪ E stream level, against the honest 21;
`f1_bracket.json r1.*.tamper_stream_level`):
- **Forward-dating** (time_response_late 5/30/300 s): 21 each. One-sided by construction.
- **Early results** (time_result_early, every D): 21. 5,390–6,967 of 7,007 draws were clamped.
- **Deletions:** delete_response 20, delete_pair 21.
- **Every shift ≤ 2 s.** The largest, time_tail_late 2 s, flags 32/7,007 with CI lo 0.0031, below the bar 0.00443.
- **Crude foreign-id splice.** 6,759 of 7,008 randomly spliced ids decode more than 1 day from their event, and
  `bracket_responses()` silently drops them (199 streams abstain). Only 253/7,008 are flagged.
- **Nearest-time splice within ±2 s:** 790/7,008 donors, undetectable by design.
- **cc_local only:** insert_pair_squeezed does not clear (56/784, CI lo 0.0). The random splice clears the clustered bar
  but not the Wilson bar of 0.00666.

**Back-dating power on the stream grid** (B ∪ E, `d_grid_summary`):

| D | 0.5 s | 1 s | 2 s | 5 s | 10 s | 30 s | 60 s | 300 s |
|---|---|---|---|---|---|---|---|---|
| flagged | 21 | 21 | 24 | 0.4051 | 0.8980 | 0.9790 | 0.9922 | 0.9997 |

The first three columns are stream counts; the rest are rates.

**Plain statement for cc_local.** R1 is DOWNGRADED to WEAK, B only and unreplicated. With one project holding 0.9988 of
the streams, the bracket cannot be tested outside that project.

**Interpretation.** R1 is the strongest proposal and the only one that survives as ALIVE on fresh, blind data. Its limits
are as definite as its strengths:
- against synthetic tampering, it detects back-dating of a response by ≥ 10 s and re-use or swapping of ids near
  their own time;
- it is blind by construction to forward-dating, deletion and sub-2-second edits;
- the request-id clock layout is inferred from data and is UNVERIFIED against provider documentation, and a forger who
  re-mints ids defeats it (`PREREG_E.md` §7).

### 3.2 R2 image-token ledger, aiv_cu Gemini strata: KILLED → DEAD

Source: `r2_r3.json R2`; N7 cells from `n7_content_shards/aiv_cu_{B,E}.json` (`R2.n7_cells`).

**Re-measured.**
- 807 sessions: 404 in B and 403 in E. 27,072 windows, every one decided.
- Window-level flag rate 88/27,072 = 0.0033 [0.0016, 0.0054].
- Non-GUI windows with any image-token change: 0 of 14,446.
- GUI windows with no increment: 53 of 12,626.

| population | flagged sessions | rate W[95%] | rule's honest half |
|---|---|---|---|
| B | 26/404 | 0.0644 [0.0443, 0.0926] | DEAD |
| E | 18/403 | 0.0447 [0.0284, 0.0695] | ALIVE |
| **B ∪ E** | **44/807** | **0.0545 [0.0409, 0.0724]** | **DEAD: the Phase D kill fires** |

**Kill attempts and checks.**
- AC1 drew 30 of the 88 violating windows from the raw `computer_use_turns` stream. All 30 matched, with 0 field
  differences: the misses are in the provider's own usage record.
- AC2: 0 windows dropped. AC3: still 44/807. AC5: 0.0545 [0.0390, 0.0700]. All three keep DEAD.
- AC4: agent (0.470) and model (0.367) dominate. No leave-out lowers the label.
- Strata: **CONFINED** on agent cluster and model generation. Only agent #1 and gemini-2.5 are signal-bearing.

**B vs E.** E alone would be ALIVE (`R2.kill_test.fires_E` = false), and B's point (0.0644) lies inside E's CI
(SHIFT = false). The prereg names B ∪ E as R2's verdict population, so E does not rescue it.

**Plain statement.** **R2 is KILLED.** The honest session-level false-positive rate on B ∪ E, 44/807 = 0.0545, is over
the pre-registered 0.05 budget, and the rule says stop the line. Its recall against synthetic tampering does not change
this: on E, image_relabel_gui recall is 305/325 = 0.938 and image_insert_screenshot 231/403 = 0.573, both DETECTS.

**Post hoc, not a verdict.** One agent (gemini-3-pro-preview, which carries +2,160-token images) drives part of the
excess. Leaving it out gives 35/749 flagged sessions, under the 0.05 budget
(`R2.artifact_checks.AC4_dominance.kinds['repo (agent_id)'].leave_outs`). That would *raise* the label, so it is
reported and not used.
gemini-3.1-pro and gemini-3.5-flash are each above 0.05 on their own.

### 3.3 R3 git execution window: swechat/claude_code SURVIVES (E not blind) → WEAK; three units NOT_RUN at n

Source: `r2_r3.json R3`. Its N7 cells were read from `n7_timing.json` at 03:58:08, while a re-run of that file was in
progress. The final `n7_timing.json` has the same label and recall k in all 488 R3_GIT cells r2_r3 used, across the four
units: 0 differ, 0 missing (`second_pass.json r3_n7_recheck`). R3's N7 half therefore stands.

**Re-measured (swechat/claude_code).**
- **Coverage.** 5,844 of 374,420 tool results (0.0156) carry a generator-class commit claim, above the 0.005 stop
  rule.
- **Resolution.** 2,513 of 5,872 generator claims resolve against the external commit table (0.428). The detector
  abstains on the rest.
- **Honest rate.**

  | population | out-of-window claims | sessions flagged |
  |---|---|---|
  | B ∪ E | 3 of 2,513 decided claims | 2/976 = 0.0020 W[0.0006, 0.0074] |
  | E | 0 of 1,244 claims | 0/489, W hi 0.0078 |

**Kill attempts.**
- AC1: all 3 flagged claims were found raw with identical stamps.
- AC3: the join-clean filter removes all three, leaving 0/974, still WEAK. The three are re-stamped resume or fork
  copies.
- AC2: 2/972. AC5: 0.0016 [0, 0.0040]. AC4: one model holds 0.818; every leave-out stays WEAK.
- No axis is CONFINED.
- The pre-registered class split held: re-reader commands (cat, tail, grep of saved output) resolve 5 claims, and all 5
  are out of window. Without the split they would have entered the honest rate.

**Why WEAK.** On E, no single-call attack DETECTS, with FPR 0/500 in every cell. The PARTIAL cells are insertions,
rewrites and tail shifts: insert_pair_consistent 83/500, for example. time_result_late is 0/500 at every D.

**B vs E.** WEAK on both, no SHIFT. E is a re-measurement, not a blind replication (E not blind).

**Plain statement for codex, opencode and gemini.** NOT_RUN (NOT_REPLICABLE_AT_N). They have 7, 8 and 9 decided sessions
in B ∪ E. Coverage is 0.0033 and 0.0022 for codex and opencode, below the 0.005 stop rule, and 0.0061 for gemini. These
are nulls of coverage, not of the window.

### 3.4 R4 dual-rendering recount: swechat/claude_code SURVIVES (E not blind) → WEAK; cc_local SURVIVES (B only, unreplicated) → WEAK

Source: `r4_r5.json R4`; N7 legs from `n7_content_shards/{swechat__claude_code,cc_local}_{B,E}.json`.

**Re-measured.**
- **Raw join.** B 30,011 counters; E 28,198 counters. Every counter joined to an IR result.
- **Honest rate.** 0 sessions are flagged on B (0/1,554), E (0/1,444) and B ∪ E (0/2,998, CI [0, 0.0013]).
- **Mismatches.** 287 of 58,209 Read results show a visible line count different from `numLines`. The whitelist
  frozen in the prereg excuses all 287.
- **cc_local (B).** 0/110 sessions; 2/365 mismatches, both whitelisted.

**Kill attempts.**
- AC1: 0 flagged units, so 30 decision units were audited as a supplement; 0 changes.
- AC2: 206 truncated units dropped. AC3: 360 non-clean units dropped. Label WEAK in both.
- AC4: model (0.775) and user dominate; every leave-out stays WEAK.
- AC5: weighted 0.0; no SHIFT.
- No confinement.
- cc_local AC4 is UNTESTABLE_WITHOUT_DOMINANT, a cap with no effect because the label is already WEAK.

**Why WEAK.** No single-call attack DETECTS. On E the best cell is rewrite_consistent_k=5, recall 205/500 = 0.41
[0.368, 0.454] (PARTIAL), with honest FPR 0/500 [0, 0.0076]. Seven attack types are BLIND at 0/500:
sub_single_flip_error, sub_single_digit, reorder_lines, delete_pair, delete_response, insert_pair_consistent and
insert_pair_squeezed. These include every edit that preserves the line count.

**B vs E.** WEAK on both (B best rewrite k=5 230/500 = 0.46), no SHIFT. cc_local is **UNREPLICATED**.

### 3.5 R5 usage-ledger reconciliation: swechat/claude_code SURVIVES (E not blind) → ALIVE; three units NOT_RUN

Source: `r4_r5.json R5`; N7 legs from the `n7_content_shards`.

**Re-measured (swechat/claude_code).**

| split | flagged / decided sessions | rate [CI] |
|---|---|---|
| B | 13/1,645 | 0.0079 [0.0046, 0.0135] |
| E | 10/1,520 | 0.0066 [0.0036, 0.0121] |
| B ∪ E | 23/3,165 | 0.0073 [0.0048, 0.0109] |

These equal the N7 shards' honest counts, which come from an independent implementation.

**N7 leg on E** (synthetic tampering; honest FPR 4/500 = 0.008):

| attack | recall | label |
|---|---|---|
| delete_response | 396/500 = 0.792 [0.754, 0.825] | DETECTS |
| inline_fabrication | 374/500 = 0.748 [0.708, 0.784] | DETECTS |
| delete_pair | 219/500 = 0.438 | PARTIAL |
| insert_pair_consistent | 4/500, equal to honest | **BLIND** |
| insert_pair_squeezed | 4/500, equal to honest | **BLIND** |

**Kill attempts.**
- AC1: all 23 flagged sessions were re-read by an independent parser; 0 changes.
- AC3 (session-level clean join): 8/3,111 = 0.0026 [0.0013, 0.0051]. ALIVE.
- AC4: user and model dominate; every leave-out stays ALIVE.
- AC5: 0.0072 [0.0047, 0.0101]; no SHIFT.
- AC2: not applicable.
- No confinement.

**B vs E.** ALIVE on B, E and B ∪ E. E is not blind.

**Plain statements.**
- **R5 has no verdict for codex or opencode (NOT_RUN):** N7 R5 cells were computed only for the Claude Code format.
  The honest leg was measured: codex 4/126 = 0.0317 [0.0124, 0.0788]; opencode 4/405 = 0.0099 [0.0038, 0.0251].
- **gemini is NOT_REPLICABLE_AT_N:** 13 decided sessions on E. Its honest rate is the highest of the four formats, at
  6/34 on B ∪ E.
- **R5 is blind to inserted call/result pairs and to tool-result content.** It constrains which API responses exist and
  what they were billed, nothing more.

---

## 4. The three follow-ups

### 4.1 F1: the 10 honest request-id failures. No shared benign cause; FP_eff does not fall toward zero

Source: `f1_bracket.json units.*.benign`, `units.*.corrections_single`, `f1_effective_fp`, `units.*.posthoc_*`.

**What the brief asked.** Explain the 10 honest failures in about 3,674 streams. A shared benign cause would drop the
effective FP rate toward zero.

**Stream counts.** The re-implementation counts 3,676 streams. The skeptic text gives 3,673 and the brief 3,674. They are
reported side by side, not reconciled (`step0.conditions`).

**Pre-registered categories.** Rule: a category is a shared benign cause if it is present in ≥ 0.5 of inconsistent
streams with enrichment ≥ 0.3 over 5 consistent controls per stream.

| category | B: inconsistent / controls | E: inconsistent / controls | cc_local |
|---|---|---|---|
| restamped_copy | 3/10 vs 1/50 (enrichment 0.28) | 0/11 vs 0/55 | 0/1 |
| clock_step | 1/10 vs 50/50 | 3/11 vs 55/55 | 0/1 vs 5/5 |
| user_input_binding | 1/10 vs 0/50 | 0/11 vs 0/55 | **1/1 vs 0/5** |
| the other six | 0 | 0 | 0 |
| no category | 5 | 8 | 0 |

- **swechat, B and E: no shared benign cause** (`second_pass.json followups.F1.categories_meeting_shared_cause_rule`).
- **cc_local meets the rule on a single stream** (user_input_binding). Its correction does not lower the honest count,
  so it is not adopted.
- clock_step is uninformative as a category: every consistent stream is trivially piecewise-consistent.

**Corrections adopted on B** (adoption rule: lowers the honest count, keeps 30 s power ≥ 0.90, keeps 5 s power within
0.05):

| correction | honest count | 5 s power | 30 s power | adopted? |
|---|---|---|---|---|
| restamped_copy | 10 → 8 | 0.3934 | 0.9760 | yes |
| user_input_binding | 10 → 9 | 0.3936 | 0.9755 | yes |
| clock_step | — | 0.3319 | 0.8909 | no: 30 s power below 0.90 |

**Effective FP rate** (the adopted set, frozen and applied unchanged to E):

| | FP_eff | 5 s power | 30 s power |
|---|---|---|---|
| swechat/claude_code B | 7/3,671 = 0.00191 [0.00057, 0.00349] | 0.3931 | 0.9755 |
| **swechat/claude_code E** | **11/3,325 = 0.00331 [0.00145, 0.00551]** | 1,378/3,325 = 0.4144 [0.3916, 0.4386] | 3,260/3,325 = 0.9805 [0.9753, 0.9853] |
| cc_local B (nothing adopted) | 1/847 | 0.2562 | 0.9008 |

**Plain statement.** **F1's hope did not hold on fresh data.** The adopted corrections remove 3 of the 10 B failures and
**0 of the 11 E failures**. FP_eff on E is about 0.003, not near zero.

**Post hoc, not a verdict** (`units.*.posthoc_mechanisms`, `units.*.posthoc_ordered_inputs`). Two mechanisms that no
pre-registered category covers account for most failures:

| mechanism | B | E |
|---|---|---|
| out-of-order result writes: a tool result written before its own call line | 5 | 3 |
| client clock behind the server | 1 | 6 |

- An "ordered inputs" recompute gives B 10 → 5 (0.00136) and E 11 → 8 (0.00240), with placebo power essentially
  unchanged.
- It was chosen after seeing the data, so it is not adopted.
- **Interpretation.** It is the obvious candidate to pre-register before H or a new corpus is read.

### 4.2 F2: the swechat latency-floor shifts. OPEN; cannot be dismissed as benign, and not compromise-specific either

Source: `f2_floor_shift.json` (second run). The first run's per-split outcomes were withdrawn for violating the global
minimum n; the earlier values are kept under `corrections`.

**What the brief asked.** 13.5% of swechat sessions shift their latency floor mid-session. A mid-session regime change
is also what compromise looks like from outside. Investigate before dismissing.

**What the 13.5% is.** It is 21 of 156 eligible *series* (0.135 W[0.090, 0.197]) in 18 of 114 sessions on B. The
replication:

| population | step series / eligible | share | label |
|---|---|---|---|
| B (reproduces Phase B, series for series) | 21/156 (18 up, 3 down) | 0.135 [0.090, 0.197] | UNSTABLE |
| **E** | 10/123 (10 up, 0 down) | **0.081 [0.045, 0.143]** | **STABLE** |
| B ∪ E (union of the two runs; the primary F2 population) | 31/279, in 28 sessions | 0.111 [0.079, 0.153] | UNSTABLE |
| B ∪ E pooled index (sensitivity) | 35/279 | 0.125 [0.092, 0.169] | UNSTABLE |

**Kill attempt** (the classification). 11 pre-registered covariates were measured at the step against 248 random control
splits in 196 sessions. A covariate is credited if its rate is ≥ 0.25 above the control rate and it appears in ≥ 3
step series.

| class (B ∪ E, 31 step series) | count | W[95%] |
|---|---|---|
| BENIGN (≥ 1 credited covariate) | 0/31 | [0, 0.110] |
| COMPROMISE_LIKE (frozen signature, no credited covariate) | 3/31 | [0.033, 0.249] |
| UNEXPLAINED | 28/31 | [0.751, 0.967] |

- **Outcome: OPEN** (`verdicts.F2_outcome_BuE`). DISMISSIBLE_AS_BENIGN needs BENIGN ≥ 0.8.
- **B alone (21 step series) and E alone (10) are INSUFFICIENT_N.** They get raw counts only, with no credit test and no
  outcome. The pooled-index sensitivity is also OPEN (0/35, 4/35, 31/35).
- **No covariate is credited.** The closest is an idle gap ≥ 300 s in the window: 18/31 = 0.581 at steps against
  85/248 = 0.343 at controls, diff +0.238 [+0.048, +0.427]. That is below the 0.25 bar, which was not moved.
- **Nulls.** Harness version 1/31 vs 2/248. Permission mode 2/31 vs 16/248. Hooks 0/31 vs 9/248. Parallelism 2/31 vs
  21/248 (`populations.BuE.covariates`). Compaction 1/31 vs 35/248 (`populations.BuE.harness_by_type_descriptive`,
  whose denominators are `step_series` and `control_series`).

**The compromise signature is non-specific** (post hoc, descriptive; no step is a known compromise, so this is a
base-rate comparison, not a detection):
- It fires at 3/31 = 0.097 of steps, all through the r leg on small-result series.
- It fires at 48/248 = 0.194 [0.149, 0.247] of control random splits, more often than at the steps.

**Post hoc, not a verdict.** Read as 5 *session* calls on each side instead of 5 series calls, the idle-gap enrichment
shrinks to 5/31 = 0.161 against 20/248 = 0.081 (+0.081).

**Plain statement.** The floor shifts **cannot be dismissed as benign** under the pre-registered rule: 0 of 31 are
explained. They are **not evidence of compromise** either: the signature fires more often at random points. On the fresh
split the shift rate is below the 0.10 line. **F2 moves no verdict** (`verdict_effect`), and P1 swechat/claude_code
stays WEAK.

**Interpretation.** The only association, with idle gaps, depends on the window reading. A resume-after-idle regime is
consistent with cold caches or a reopened session, and equally with a takeover after a pause. The log cannot separate
these. The Phase B "UNSTABLE" label sits at a seed-sensitive margin: 8 series near p = 0.01 flip between seed
indexings (`steps.pooled_vs_union_step_flag_differs`). This is reported, not used: the frozen label stands, and F2 moves
no verdict either way.

### 4.3 F3: round numbers without model-chosen parameters. Not DEAD (no collapse), but ALIVE is not kept

Source: `f3_round.json candidates`; `a1_p2_p4_f3.json candidates['P4round/…'].populations.*.F3`.

**What the brief asked.** Re-run excluding model-chosen timeout values. If the 42%-vs-12% gap collapses, mark DEAD.

**Rule, fixed in advance.**
- Exclude every distinct value with any parameter occurrence: a JSON number, a CLI option, a key=value with a
  parameter-like key, host:port, and so on.
- Gap g = p(remaining) − p(M_all), and g_full is the same gap before exclusion.
- **DEAD** if the Phase B rule gives DEAD on the remainder, or if g ≤ 0.25 × g_full.
- **ALIVE kept** only if the rule gives ALIVE and g ≥ 0.5 × g_full. Otherwise WEAK.

**swechat/claude_code:**

| population | T_orig last-0, all values | M_all last-0 | g_full | remaining after exclusion | g | g / g_full | F3 |
|---|---|---|---|---|---|---|---|
| B | 127/300 = 0.423 | 0.116 | 0.308 | 54/200 = 0.270 [0.160, 0.403] | 0.154 | 0.501 | WEAK |
| **E** | 91/248 = 0.367 | 0.113 | 0.254 | 31/156 = 0.199 [0.131, 0.288] | 0.086 | **0.338** | WEAK |
| B ∪ E | 169/459 = 0.368 [0.305, 0.437] | 3,930/34,788 = 0.113 [0.109, 0.118] | 0.255 | 71/307 = 0.231 [0.158, 0.316] | 0.118 | **0.464** | WEAK |

- **What was excluded.** 152 of 459 distinct values are parameters, and 98 of those end in 0. JSON-number arguments are
  the largest context (90), then key=value (50) and CLI options (31).
- **cc_local (B only).** 114/206 = 0.553 [0.131, 0.731] remain; g / g_full = 0.820. The rule gives WEAK because the CI lo
  0.131 does not clear the bar.
- **swechat/\* pooled.** g / g_full is 0.462 on B ∪ E and 0.263 on E. On E, g = 0.0692 sits just above the collapse
  threshold 0.0656 (`f3_round.json candidates['P4round/swechat/* (pooled)'].populations.E.F3.strict`). AC4 then kills
  the row (section 2.6).
- **The reading variants do not decide.** The first-occurrence reading gives ALIVE on B ∪ E (0.546) and WEAK on E. The
  deciding label is WEAK under every reading, because E is WEAK under every reading.

**Plain statement.** **The gap does not collapse, so P4 is not DEAD in swechat/claude_code or cc_local.** Excluding
parameters removes about half of the gap: 0.464 of it is left on B ∪ E and 0.338 on E. That is below the 0.5 needed
to keep ALIVE. **P4 is WEAK in both units, and the pooled row is KILLED.**

**Interpretation.** The skeptic was half right. Chosen parameters supply a large part of the round-number excess. The
residual sits mostly in Write-call content and in one model's sessions (post hoc, descriptive). That points to constants
in code the model writes, a fingerprint of which model wrote the content and what kind of content it is, rather than
to invented measurements.

---

## 5. Phase B cells that were not carried into A1

`PREREG_E.md` §1.2 lists the Phase B ALIVE or WEAK cells that were not A1 candidates:

| Probe | Cells |
|---|---|
| Probe 1 | swechat/codex, swechat/gemini, aiv_cc (single-agent case study) |
| Probe 3a | whowhen/Algorithm-Generated |
| Probe 3b | swechat/claude_code, swechat/opencode, cc_local, aiv_cu |
| Probe 4a | swechat/claude_code, aiv_cu, two pooled rows |
| Probe 4b | aiv_cu, public/* pooled |

They received no kill battery. The prereg said they would be re-run on E in N6 where the unit has E, but no Phase E item
re-ran Probe 1–4 code on E. Those N6 cells are therefore NOT_RUN, with the Phase B verdict stored beside them and never
in them (`n6_grid.json deviations[1]`: 24 cells NOT_RUN instead of an E verdict). **This is a coverage gap of the
second pass, not a null.** Units without E keep their Phase B verdict as "B only (Phase B run)":
- aiv_cc (single-agent case study) Probe 1: WEAK;
- whowhen Probe 3a: WEAK;
- cc_local Probe 3b: WEAK.

---

## 6. New candidates N1–N5 and the N7 battery: headline cells

The full grid, failing cells included, is in **`analysis/TRANSFER_MATRIX.md`** (`n6_grid.json`). The per-item detail is in
`analysis/notes/phase_e_n1.md`, `phase_e_n2_n3.md`, `phase_e_n4_n5cg.md`, `phase_e_n5_battery.md`, `phase_e_n7_timing.md`
and `phase_e_n7_content.md`. Only headline cells are shown here.

| Mechanism | Headline cell | Deciding number | Source |
|---|---|---|---|
| **N1** conditional duration (shell; human-wait contaminated) | swechat/claude_code **ALIVE**, replicated (B, E and B ∪ E ALIVE) | E: ρ_hon 0.031 [0.016, 0.046]; ρ_pc (synthetic positive control) 0.474, CI lo 0.425; RR 6,536/37,326 = 0.175; honest flag 60/5,809 = 0.0103, CI hi 0.0143 | `n1.json units['swechat/claude_code'].results.E.shell.verdict` |
| N1 | aiv_cc **ALIVE** (single-agent case study, B only) | ρ_hon 0.039 [0.002, 0.074]; ρ_pc (synthetic positive control) CI lo 0.707; flag 11/1,901 = 0.0058 | `n1.json units.aiv_cc.results.B.shell.verdict` |
| N1 nulls | codex, opencode, gemini and cc_local are INSUFFICIENT_N (18, 13, 11 and 7 sessions on B, below 20). Coverage (B ∪ E): 13,443/78,205 = 0.172 of qualified CC shell calls repeat. As a per-call alarm (B ∪ E) the detector flags only 219/3,842 = 0.057 of synthetically tampered CC shell instances | — | `n1.json` |
| **N2** token accounting (inline fabrication only) | ALIVE in 3 aiv_cu strata on E: gemini-pro 1/494, gemini-flash 0/430, anthropic-sonnet 21/781 = 0.0269 (synthetic-injection recall 0.932). swechat/claude_code is WEAK on synthetic recall: E 0.891 [0.882, 0.900] < 0.90. codex, opencode and cc_local are WEAK | as listed | `n2.json units.*.cell_final` |
| **N3** reaction time | **DEAD** in swechat/claude_code. Pooled ρ on E is −0.039 [−0.054, −0.024], and 565/1,170 = 0.483 of honest sessions have ρ_s ≤ 0, about the rate at which the permuted (synthetic) positive control is flagged (0.485). codex is WEAK (ρ 0.223 on E); its secondary turns negative after subtracting generation time | — | `n3.json units.*.cell_final` |
| **N4** concurrency | Nothing is ALIVE after checks. swechat/claude_code went from ALIVE to WEAK (CONFINED). Its separation has the wrong sign and is a subagent-nesting effect: 16,181 of 16,529 k ≥ 2 W pairs on B are inside a subagent. codex and cc_local are DEAD after checks | — | `n4_n5cg.json n6_cells` |
| **N5** battery | No item cell is ALIVE. a determinism DEAD (CC E drift 491/1,745 = 0.281). b sort DEAD (ls E 277/1,422 = 0.195). c truncation DEAD (cc_chars_mid E 0.845), while the glob-cap sub-item is ALIVE (0.996). d whitespace DEAD, with the git-status tab checker ALIVE at 0/1,096. e size WEAK in CC (42/47 families), aiv_cu and aiv_cc (single-agent case study, B only). f error fidelity INSUFFICIENT_N (28 frames). g cold start DEAD (CC E share 0.502) | — | `n5_battery.json n6_cells`, `n4_n5cg.json n6_cells` |

**N7 attack battery** (synthetic tampering of real honest sessions; every DETECTS below is against a synthetic attack).
- **Size.** Timing half: 3,236 verdict cells (`n7_timing.json n_verdict_cells`). Content half: 1,275 cells, of which
  DETECTS 12, PARTIAL 35, BLIND 939 and INSUFFICIENT_N 289 (`n7_content.json label_counts`).
- **Who detects.** Six detectors have any DETECTS cell: R1_BRACKET, P1_FLOOR, P1_GEN, R5_LEDGER, R2_IMAGE and N2
  (`second_pass.json n7_walkthrough_union.detectors_with_any_DETECTS_cell`). These are the clock and accounting
  detectors. No content detector (P2_KFN, P3_ZERO, N5a–f) reaches DETECTS against any attack in any unit, and neither
  do N1, N3, N5g or R3_GIT.
- **Combined walk-through.** Assembled here from both halves (`second_pass.json n7_walkthrough_union`): **10 of 21
  attack types have no DETECTS cell in any detector, unit or split.**
  - time_response_late;
  - sub_single_flip_error, sub_single_digit, sub_matched_bytes;
  - rewrite_consistent_k;
  - reorder_adjacent_pairs, reorder_lines;
  - delete_pair;
  - insert_pair_consistent, insert_pair_squeezed.

  The same 10 result when only replication-split cells are counted.

**Transfer.** 87 of the 396 loaded N6 cells are decided: ALIVE 8, WEAK 40, DEAD 39. 1 of 218 decided pairs fails to
transfer: Probe 3a, cc_local DEAD against swechat/claude_code ALIVE. The checks matter: before the artifact checks and
kill tests the same cells held 19 ALIVE (`n6_grid.json transfer`).
The 8 ALIVE cells are not equally checked; `analysis/TRANSFER_MATRIX.md` lists the caveats per cell (Probe 4b
tbench2 received no artifact check; R1 tbench2 is one submission with AC4 recorded as label only; AC5 was NOT_RUN on
every Track B corpus and on aiv_cc; R5 is E not blind; N1 aiv_cc is a single-agent case study on B only).

---

## 7. Plain statements: every KILLED, DEAD, UNREPLICATED and NOT_RUN

**KILLED / DEAD:**
- **P2 knowledge precedence, aiv_cc main** (single-agent case study): KILLED (B only, unreplicated) → DEAD. AC4
  DOMINATED, CONFINED on tool.
- **P4 round numbers, swechat/\* pooled:** KILLED → DEAD. It collapses without claude-opus-4-6.
- **R2 image-token ledger, aiv_cu Gemini:** KILLED → DEAD. The honest session rate 44/807 = 0.0545 exceeds 0.05.
- **New candidates (section 6), DEAD in swechat/claude_code, the largest unit:** N3 reaction time; N5a determinism;
  N5b sort order; N5c truncation; N5d whitespace; N5g cold start. N4 is DEAD after checks in swechat/codex and cc_local.
  Every other DEAD cell (39 in the loaded grid) is listed in `analysis/TRANSFER_MATRIX.md` (`n6_grid.json cells`).

**DOWNGRADED:**
- **P1 latency, swechat/opencode:** ALIVE → WEAK. The control cannot be tested outside one repo and one model.
- **P1 latency, cc_local:** ALIVE → WEAK. One project.
- **P2, opencode subagent:** E ALIVE → WEAK, the same as its Phase B label. One repo; S_deep does not exist under the
  strict root rule.
- **P4 round numbers, swechat/claude_code and cc_local:** ALIVE → WEAK. Parameters explain about half the gap.
- **R1, cc_local:** ALIVE (B) → WEAK. One project.
- **P1 latency, swechat/claude_code:** status DOWNGRADED (E ALIVE → WEAK), but the final label equals Phase B's WEAK.

**UNREPLICATED (B only):**
- P1 cc_local, P4 cc_local, R1 cc_local and R4 cc_local (all private);
- P2 aiv_cc main (single-agent case study).
- New candidates on units without E (section 6): N1 aiv_cc ALIVE (single-agent case study), and every cell marked ᴮ
  in `analysis/TRANSFER_MATRIX.md`.

None of these has an E split, so none of their labels is a replication.

**NOT_RUN (not nulls):**
- R3 codex, opencode and gemini, and R5 gemini: NOT_REPLICABLE_AT_N (E not blind).
- R5 codex and opencode: the N7 leg was not computed for their formats.
- 24 Probe 1–4 cells not re-run on E (section 5).

**Follow-up nulls:**
- **F1:** no shared benign cause; FP_eff on E 0.00331 is not near zero.
- **F2:** 0/31 floor steps explained as benign; B and E alone are INSUFFICIENT_N.
- **F3:** not a collapse, but ALIVE is lost.

---

## 8. Interpretation (not data)

**What survived the attempts to kill it.** All three ALIVE labels are in swechat/claude_code. It is the largest unit,
and the only Phase B public unit with decodable request ids (of the Track B corpora, pub_cc_hf, pub_trace_commons and
tbench2 also pass the R1 field gate; see the R1 row of `analysis/TRANSFER_MATRIX.md`, all NOT_BLIND):
1. **R1 request-id bracket: ALIVE.**
   - Honest stream FP 0.00300, and 0.00331 on fresh E after the frozen corrections.
   - Against synthetic tampering on E, it detects ≥ 10 s response back-dating, adjacent id swaps and nearest-time
     foreign ids.
   - It is blind to forward-dating, deletion and ≤ 2 s edits.
   - Its E split is blind, so this is a replication.
2. **R5 usage ledger: ALIVE (E not blind).**
   - Honest session FP 0.0073.
   - Against synthetic tampering, it detects deleted responses and inline fabrication.
   - It is blind to inserted pairs and to result content.
   - Phase C had read E, so E re-measures it and does not blind-replicate it.
3. **P3 zero-error tail: ALIVE**, replicated on a blind E, but as a baseline only. There is no positive control.

**What held at WEAK.**
- P1 separability in Claude Code: it holds under every artifact check, but the floor moves (K2), so it stays WEAK.
- P2: a stable but high honest rate.
- P4: half explained by parameters.
- R3: the window rarely gets a resolvable claim.
- R4: zero honest flags, but blind to count-preserving edits.

**What died.**
- R2: honest session rate 0.0545 on B ∪ E, over the pre-registered 0.05 budget.
- The pooled round-number row.
- P2 in the single-agent aiv_cc.

**The cross-corpus lesson.** Most second-pass losses outside swechat Claude Code came from concentration in one
cluster:
- one repo or project: P1 opencode, P1 cc_local, P2 opencode, R1 cc_local;
- one model: P4 pooled;
- a few runs of one agent: P2 aiv_cc.

The two exceptions are P4 cc_local, lowered by F3, and R2, killed by its honest rate. The units other than swechat Claude
Code are mostly too concentrated to test whether these mechanisms generalise. That is a null of testability: it shows
neither that these mechanisms fail elsewhere nor that they work elsewhere.

**The follow-ups.** None of them gives the clean answer the brief hoped for:
- no pre-registered category removes the request-id failures; a post hoc reading (not a verdict) attributes most of
  them to harness behaviour (out-of-order result writes, client clock behind the server);
- the floor shifts are unexplained but not compromise-shaped;
- the round numbers are partly parameters.

**What would change this:**
- pre-registering the "ordered inputs" bracket rule and a separate implausible-id flag before H is read;
- a second repo or model in the opencode and cc_local controls;
- a real (non-synthetic) fabricated result anywhere.

---

## 9. Deviations, limits and what was not measured

**Number check** (`second_pass.json md_number_check`). Every number token in this file matches a number in the Phase E
outputs at its printed precision; none needed the prereg files. Every k/n pair also sits together in one output, with one
exception: 35/248 (compaction at controls, section 4.2), whose denominator is the sibling field `control_series`. The
token check matches across all outputs, so it guards against transcription errors but does not prove the cited path.
For that, `md_number_check.subtree_checks` looks up each section's decimals only inside the subtree the section names as
its source; none is missing. That check describes the text before the Phase E audit. After the audit edits the check
was re-run by `analysis/probes/phase_e_trace.py` (`analysis/out/phase_e/trace.json`; edits logged in
`analysis/out/phase_e/audit_log.json`).

**Deviations of this write-up** (`second_pass.json deviations`):
1. **The R1 survival status is computed in the assembly.** The frozen `survival_status()` was called on the N6-composed
   labels, following the sibling items' conventions. Effect: none. The final labels equal the N6 cells.
2. **An assembly script and JSON were added** (`phase_e_second_pass.py` → `second_pass.json`). The prereg names
   `SECOND_PASS.md` for interpretation but no script. Effect: none.

Each item's own deviations are in its JSON `deviations` list and its notes file. Those that shape a verdict are named
above: P2 aiv_cc rule readings, the F2 minimum-n correction, N4 correction C1, and R1 composition in N6.

**Limits.**
- **Every positive is synthetic.** No corpus contains a known real fabricated tool result. Recall is recall against our
  own tampering model.
- **E is not blind for R3, R4 and R5.** H is not fully blind for them either (`prereg_e.json splits.E_freshness`).
- **cc_local, aiv_cc (single-agent case study) and whowhen have no E.** Their labels are unreplicated.
- **The request-id clock layout is inferred from data** and is unverified against provider documentation.

**Not measured.**
- Phase D's extra tamper plans for R3 (replay) and R4 (line edits, whitelisted rewrites). They are not in the prereg
  battery.
- R5 N7 for non-Claude Code formats.
- R2 sessions above 40 GUI windows: 1 session.
- cc_local: AC1 for R1 (no raw cc_local file is opened by that item) and AC5 for every candidate (no population
  table). aiv_cc (single-agent case study): AC5 (no population table).
- Track B corpora (agentcap, glm_tb21, pub_cc_hf, pub_codex, pub_trace_commons, tbench2): AC5 for every cell (no
  population table for new corpora), and no artifact check or A1 kill test for their Probe 1–4 cells (Phase B rule
  only). See `analysis/TRANSFER_MATRIX.md`.
- A blind replication of R4 and R5 on swechat.

---

## 10. Sources

| file | what it supplies |
|---|---|
| `analysis/out/phase_e/a1_p1_p3.json` | P1 (3 units), P3 |
| `analysis/out/phase_e/a1_p2_p4_f3.json` | P2 (5 cells), P4 (3 cells), F3 |
| `analysis/out/phase_e/f3_round.json` | F3 (same run) |
| `analysis/out/phase_e/f1_bracket.json` | F1, R1 honest leg, kill rule and checks |
| `analysis/out/phase_e/f2_floor_shift.json` | F2 |
| `analysis/out/phase_e/r2_r3.json` | R2, R3 |
| `analysis/out/phase_e/r4_r5.json` | R4, R5 |
| `analysis/out/phase_e/n7_timing.json`, `n7_content.json`, `n7_content_shards/` | N7 legs |
| `analysis/out/phase_e/n6_grid.json` | R1 composition, transfer counts, NOT_RUN cells |
| `analysis/out/phase_e/n1.json`, `n2.json`, `n3.json`, `n4_n5cg.json`, `n5_battery.json` | N1–N5 headline cells |
| `analysis/out/phase_e/second_pass.json` | the survival table as labels, the R1 status, the combined N7 walk-through, input sha256 and this file's number check |
