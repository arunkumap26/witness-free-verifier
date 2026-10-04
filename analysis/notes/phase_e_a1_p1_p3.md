# Phase E A1 second pass: Probe 1 and Probe 3 candidates (item a1_p1_p3)

**This file is interpretation.** The raw numbers are in `analysis/out/phase_e/a1_p1_p3.json`, written by
`analysis/probes/phase_e_a1_p1_p3.py` (runtime 693.2 s). Every number below appears in that JSON. JSON paths are
relative to its root. The run was made under the frozen pre-registration: `check_frozen()` passed, and the
prereg_e.json sha256 is `4c77ac53…` (`prereg`). Rates are k/n [95% CI]. "s" means sessions. W[] is a Wilson interval
over sessions or series.

## Verdicts (`verdicts`)

| Candidate | Phase B | E verdict | B ∪ E verdict | Status (survival_status) | Final | What decided it |
|---|---|---|---|---|---|---|
| P1 swechat/opencode | ALIVE | ALIVE | ALIVE | **DOWNGRADED** | WEAK | AC4: the G control cannot be tested without its dominant repo or model (cap WEAK) |
| P1 cc_local (private, B only) | ALIVE | — | ALIVE (B) | **DOWNGRADED (B only, unreplicated)** | WEAK | AC4: every W and G pair is in one project alias; one model holds 0.932 of W (cap WEAK) |
| P1 swechat/claude_code | WEAK (floor UNSTABLE) | ALIVE | WEAK | **DOWNGRADED** | WEAK | K2: the B ∪ E floor is UNSTABLE, 35/279 series = 0.125 W[0.092, 0.169] |
| P3 zero-error tail, swechat/claude_code | ALIVE | ALIVE | ALIVE | **SURVIVES** | ALIVE | E: Z = 8/380 = 0.021 W[0.011, 0.041]; every check and kill test passed |

No candidate was KILLED. Three of the four lost a level. In each of the three, the separability statistic itself held:
fp_share and AUC stayed ALIVE in every population and every computable check. The level was lost to a structural
check: control concentration in two units, floor stability in one.

The claude_code status reads "DOWNGRADED", but its final label equals the Phase B label (WEAK). E alone gave ALIVE,
because its floor was STABLE (10/123 = 0.081). K2 then lowered that ALIVE back to WEAK on the B ∪ E floor. The second
pass therefore **confirms Phase B's WEAK**; it neither upgrades nor loses it.

## Reproduction first

On split B, every unit reproduces the committed Phase B numbers exactly (`candidates.*.reproduction_B_vs_phase_b.all_match`
= true for all four):
- opencode: fp 7/4,419, AUC 0.99916;
- cc_local: fp 1/1,019, AUC 0.91864;
- claude_code: fp 72/20,937, AUC 0.98702, floor steps 21/156, transfer FLOOR_SHIFT on read and taskupdate;
- P3: Z 9/413, 194,367 paired calls.

The Phase E numbers below therefore come from the same code path, not from a re-implementation that drifted.

## P1 swechat/opencode: replicates, but the control lives in one repo

- **Replication (E).** fp 6/3,283 = 0.0018 [0, 0.0050] over 186 s. AUC 0.9986 [0.9958, 1.0000]. G is only 37 pairs
  from 7 s, just above the 30/5 minimum (`populations.E.separability`).
- **B ∪ E.** fp 13/7,702 = 0.0017 [0.0004, 0.0033]. AUC 0.9990 [0.9981, 0.9996]. G 164 pairs from 19 s.
- **AC4, the deciding check.** It was mandatory for this unit.
  - One repo holds 0.863 of eligible W pairs and 0.951 of eligible G pairs. One model, gpt-5.3-codex, holds 0.837 of W
    and 0.970 of G.
  - Without that repo: W 1,052 from 68 s, with fp still 7/1,052, but G is **8 pairs from 6 s**. Without that model:
    G is 5 pairs from 5 s.
  - So the generation-bound control cannot be formed outside the dominant repo and model: UNTESTABLE_WITHOUT_DOMINANT,
    capped at WEAK.
  - Every computable leave-out stayed ALIVE: repos 2–5, five users including the null-user cluster, and five
    G-heavy sessions (`artifact_checks.AC4_dominance.leave_outs`).
- **Strata.** The work-bound side does generalise across repos: repo#2 fp 1/571 and repo#3 fp 6/324 are ALIVE on fp.
  Those strata are WEAK overall only because they have no G (AUC INSUFFICIENT_N). No axis is CONFINED.
- **Other checks.**
  - K1: dropping the top G session (35 pairs, 0.213 of G) gives AUC 0.9992 [0.9982, 0.9998].
  - K2: floor untested (20 series in B ∪ E, 5 in E; < 30).
  - AC1: 13/13 numerator events found raw, 0 differ (11 by callID, 2 by ordinal for redacted ids).
  - AC2: 1,704 truncated W pairs dropped, fp 11/5,998, AUC 0.9988 → ALIVE.
  - AC3: 0 pairs dropped. K3: 19 W pairs dropped, ALIVE.
  - AC5 weighted: fp 0.0016, AUC 0.9991, ALIVE.
  - No SHIFT between B and E.

**Reading.** OpenCode read/grep/glob latencies sit far from generation time in every repo with enough data. The claim
"AUC against generated output" rests on subagent and websearch calls from essentially one repo and one model. Treat it
as WEAK until a second repo supplies a control.

## P1 cc_local: one project, one model (private; aggregates only; B only)

- **B.** fp 1/1,019 = 0.0010 [0, 0.0033]. AUC 0.919 [0.881, 0.971]. G 153 pairs from 12 s.
- **AC4.**
  - The proj01 alias holds 1.0 of both W and G. Leaving it out leaves 0 pairs.
  - claude-opus-5 holds 0.932 of W. Leaving it out leaves W 69 pairs from 5 s.
  - Result: UNTESTABLE_WITHOUT_DOMINANT, capped at WEAK.
  - One session holds 0.261 of W. Its leave-out and the other session leave-outs stay ALIVE.
- **K1 (the bimodal G).** Removing the workflow pairs (47) **raises** AUC from 0.919 to 0.983 [0.968, 0.996], with G
  106 pairs from 11 s. Also dropping the top G session (22 pairs) gives 0.982 [0.963, 0.999], G 84 from 10 s → PASS.
  The low mode of the bimodal G histogram is the workflow pairs (47, median r 0.0069) plus the 6 subagent pairs
  (median r 0.0064). webfetch (median r 1.39) and websearch (0.85) form the upper mode
  (`populations.B.separability.G_eligible_by_tool`).
- **Strata.**
  - The glob stratum is WEAK: AUC 0.814 [0.700, …]. The read stratum is ALIVE.
  - The model and repo axes are UNTESTABLE: only one reportable stratum each.
- **Other checks.**
  - K2: untested (5 series).
  - AC1: 1/1 found, 0 differ. The search covered the session's root file-set in the frozen snapshot.
  - AC2: 197 W dropped, ALIVE. AC3: 0 dropped. K3: 0 dropped.
  - AC5: NOT_RUN (no population table).

**Reading.** It is internally consistent, but it is one developer's one project on essentially one model. That cannot
support a transfer claim, and the cap reflects that.

## P1 swechat/claude_code: the separability holds everywhere; the floor still moves

- **E.** fp 63/18,256 = 0.0035 [0.0024, 0.0046] over 926 s. AUC 0.986 [0.973, 0.995], with G 3,320 from 823 s. The floor
  is STABLE: 10/123 series = 0.081 W[0.045, 0.143]. E verdict: ALIVE.
- **B ∪ E.** fp 135/39,193 = 0.0034 [0.0027, 0.0042]. AUC 0.9866 [0.9794, 0.9922]. The floor is **UNSTABLE**: 35/279
  series = 0.125 W[0.092, 0.169], with 30 steps up and 5 down. That gives WEAK, and K2 applies the same downgrade to E's
  ALIVE.
- **Seed caveat (descriptive).** The pooled change-point run indexes its permutation seeds over the pooled series order
  (the Phase B rule applied to B ∪ E). Its per-series p-values are therefore not the per-split ones. Per split the
  counts are B 21/156 = 0.135 and E 10/123 = 0.081 (`populations.B/E.floor_step_change`). B alone is above the 0.10
  line and E alone is below it. The 13.5% floor-shift question belongs to F2, a separate item; this item can neither raise nor
  explain it.
- **Every artifact check passed** with fp and AUC ALIVE:
  - AC2: 738 W and 4 G truncated pairs dropped.
  - AC3: 392 W and 50 G pairs dropped, including 1,461 call ids copied across sessions.
  - K3: 81 W and 14 G whole-second pairs dropped.
  - AC5: weighted fp 0.0034, AUC 0.9866.
  - AC1: 30/30 found raw, 0 differ.
- **AC4.** The unit is dominated by model (claude-opus-4-6: 0.713 of W, 0.815 of G) and by the null-user pseudo-cluster
  (0.392 of W). None of the 11 leave-outs moves fp or AUC off ALIVE. For example, without claude-opus-4-6 W is 11,256,
  G 1,319 and AUC 0.991. Without the null-user sessions AUC is 0.991 [0.987, 0.994].
- **Strata.** Separability is ALIVE in every reportable stratum except claude-opus-4-7, which is WEAK only for lack of G:
  - 3 tools: glob fp 62/1,606, AUC 0.948;
  - 5 of 6 models;
  - 33 repos;
  - 3 length terciles.

  Nothing is CONFINED.
- **K1.** The top G session holds 83 pairs (0.012 of G): no concentration.

**Reading.** In Claude Code public sessions, the work-bound-versus-generation-bound separation of read/grep/glob latency
is the most robust number in this item:
- it replicates on fresh E;
- it survives truncation, joins, stamps and reweighting;
- it holds without the dominant model or user and in every stratum.

What keeps it at WEAK is that the latency floor itself steps within sessions in more than 10% of eligible series.

## P3 zero-error tail, swechat/claude_code: survives

- **Replication (E).** Z = 8/380 = 0.021 W[0.011, 0.041] at L75 = 134; E0 = 0.00074, Z/E0 = 28.4. Verdict: ALIVE.
- **B ∪ E.** Z = 17/793 = 0.021 [0.013, 0.034]. No SHIFT between B and E.
- **Kill tests (B ∪ E).**
  - **K1 (sessions with ≥ 10 shell calls):** 17/780 = 0.022. PASS.
  - **K2, without cc_tool_use_error.** This is the closest call in the item. 62/793 = **0.078 [0.061, 0.099]**, below
    the 0.10 downgrade line, so PASS. On E alone it is 28/380 = 0.074 [0.051, 0.104].
    - Harness validation errors carry a real share of the friction: cc_tool_use_error is 4,905 of the 14,556 primary
      errors in B ∪ E (`populations.BuE.class_counts`).
  - **K3 (strata).** No stratum fires.
    - claude-opus-4-6 holds 0.802 of long sessions, with Z 15/636 = 0.024.
    - The largest repo holds 0.169, with Z 0/134.
  - **K4 (L90 = 220), reported only.** B∪E 1/432; E 1/208; B 0/224.
- **Artifact checks.**
  - AC1: all 17 zero-error long sessions were re-derived from the raw transcripts. Their paired-call counts are
    identical and none has a primary error, so 0 differ.
  - AC2: dropping 4,199 truncated pairs raises Z to 26/784 = 0.033, still ALIVE.
  - AC3: 17/787, ALIVE.
  - AC4: the leave-outs of the null-user cluster (0.363 of long sessions) and of claude-opus-4-6 stay ALIVE. Without
    the latter, 2/157 = 0.013, Wilson hi 0.045.
  - AC5 weighted: 0.021 [0.011, 0.033].
- **Strata.** Model has 4 reportable strata and repo has 8; neither is CONFINED. Length is UNTESTABLE by construction:
  every long session lies above the A upper tercile. Tool is NOT_APPLICABLE for a session-level statistic.

**Reading.** Honest long Claude Code sessions are rarely error-free (Z = 0.021), and that holds on fresh data, in every
stratum, and under every pre-registered attack on it. This is a baseline result only: **no positive control exists**.
Nothing here shows that a fabricated session would be error-free. Without harness-validation errors, Z rises to 0.078,
inside the ALIVE band but close to its edge.

## Nulls and limits, stated as prominently as the hits

- **Two of the three P1 ALIVE cells fail to generalise past one cluster.** opencode's control and all of cc_local come
  from one repo or project and one model. This is a null for transfer, not for the mechanism.
- **The claude_code floor remains UNSTABLE at twice the n.** The separability verdict cannot rise above WEAK until F2
  explains or discounts the steps. F2 may not raise the verdict (no rescue).
- **K2 floor tests were untestable** in opencode and cc_local (fewer than 30 eligible series). Floor stability there is
  unknown, not established.
- **P3 has no positive control**, and its K2 margin to 0.10 is small. The upper CI bound is 0.099 on B ∪ E and 0.104 on
  E.
- **AC3 limitation.** Copies shared with A or H sessions cannot be detected, because H may not be read.
- The deviations, each with its effect on the verdict, are in `deviations`. Two of them shape verdicts:
  - K2 is the Phase B floor rule and is never applied twice. It made no difference here: E's floor was STABLE, so E's
    verdict had not already been floor-downgraded, and K2 lowered ALIVE to WEAK once. A literal double application
    would differ only for an E verdict that the floor rule had already lowered.
  - Null repo_id / user_id are grouped into one "unknown" pseudo-cluster. This is not one person.
