# Phase E, N1: conditional duration model

**Data.** `analysis/out/phase_e/n1.json`, written by `analysis/probes/phase_e_n1.py`
(`PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_n1`, 538.2 s, `runtime_s`).

**Pre-registration.** `prereg_e.json n1_conditional_duration`, run as written apart from the choices listed in
`deviations` (section 7). `check_frozen()` passed (`check_frozen`). The JSON records the sha256 of `prereg_e.json`
and of `prereg_e_common.py`. The pairs, the no-human-wait filter, `n1_key()` and `n1_residuals()` come from the frozen
module. They are called through `prereg_e_calibration.unit_pairs`, the code path that produced the A-split detector
bounds. No threshold was changed.

**Conventions.**
- k/n = rate [95% session-clustered CI]. ρ = Spearman [95% session-bootstrap CI, 1,000 draws]. s = sessions (aiv_cc:
  runs).
- Splits: B, E (swechat only; the replication), and B ∪ E pooled (the artifact-check population).
- The primary scope is the shell family, and it decides the unit's N6 cell. auto_read is reported as the secondary
  scope.
- Sections 1 to 6 report data. **Section 8 is interpretation.** Every number below is in the JSON, rounded, and its
  path is given or is the obvious block (`units.<unit>.results.<split>.<scope>`).

**Labels.**
- swechat/claude_code and cc_local shell: *human-wait contaminated (permissionMode not in the IR)*.
- opencode and gemini shell: *permission timing unknown*.
- aiv_cc: *single-agent case study*, B only, unreplicated.
- cc_local: *private*, aggregates only, B only, unreplicated.

## 1. Coverage first: repeat-command rate RR (`units.<unit>.coverage_first`)

RR = qualified calls that sit in a repeat group / qualified calls. A repeat group is (session, tool_key, n1_key) with
at least 2 qualified instances. RR bounds what N1 can cover: a call outside a repeat group gets no residual and no
verdict.

| unit | split | shell RR | auto_read RR | context: shell repeat calls / all shell pairs (before qualification) |
|---|---|---|---|---|
| swechat/claude_code | B | 6,907/40,879 = 0.169 [0.156, 0.182], 1,373 s | 2,773/26,639 = 0.104 [0.092, 0.119] | 6,907/61,066 = 0.113 [0.103, 0.123] |
| swechat/claude_code | E | 6,536/37,326 = 0.175 [0.162, 0.189], 1,278 s | 2,479/22,952 = 0.108 [0.094, 0.124] | 6,536/56,923 = 0.115 [0.104, 0.126] |
| swechat/claude_code | B ∪ E | 13,443/78,205 = 0.172 [0.162, 0.182], 2,651 s | 5,252/49,591 = 0.106 [0.096, 0.116] | 13,443/117,989 = 0.114 [0.107, 0.122] |
| swechat/codex | B | 859/5,133 = 0.167 [0.079, 0.235], 56 s | no qualified auto_read | 859/6,399 = 0.134 [0.075, 0.207] |
| swechat/codex | E | 248/2,033 = 0.122 [0.070, 0.160], 38 s | — | 248/4,155 = 0.060 [0.026, 0.113] |
| swechat/opencode | B | 600/1,853 = 0.324 [0.145, 0.446], 207 s | 179/5,113 = 0.035 [0.012, 0.060] | 600/1,859 = 0.323 [0.145, 0.445] |
| swechat/opencode | E | 200/1,180 = 0.170 [0.039, 0.284], 176 s | 71/3,785 = 0.019 [0.004, 0.041] | 200/1,180 = 0.170 [0.039, 0.284] |
| swechat/gemini | B | 302/587 = 0.515 [0.276, 0.600], 16 s | 213/321 = 0.664 [0.424, 0.766] | 302/603 = 0.501 [0.261, 0.588] |
| swechat/gemini | E | 70/181 = 0.387 [0.257, 0.541], 11 s | 30/73 = 0.411 [0.239, 0.588] | 70/196 = 0.357 [0.228, 0.515] |
| cc_local | B | **958/22,292 = 0.043 [0.017, 0.054]**, 79 s | 344/1,817 = 0.189 [0.063, 0.335] | 958/26,873 = 0.036 [0.011, 0.045] |
| aiv_cc (single agent) | B | 1,964/6,330 = 0.310 [0.194, 0.438], 58 runs | 116/3,024 = 0.038 [0.011, 0.094] | 1,964/7,884 = 0.249 [0.163, 0.334] |

- **The coverage bound.** In the largest unit (swechat/claude_code, B ∪ E), 0.172 of qualified shell calls repeat a
  command within their session. That is 0.114 of all shell call/result pairs. On every other shell pair, N1 is silent by
  construction.
- **cc_local shell RR is 0.043**, below the pre-registered 0.10 coverage condition. The local sessions rarely repeat a
  shell command. The A-split feasibility count in PREREG_E §2 (N1) already said so.
- Fewer calls carry a residual than sit in a repeat group, because a residual needs a reference with the same error
  status (`coverage_first.<split>.residual_bearing_share_of_qualified`). claude_code B ∪ E shell: 11,865 residuals from
  78,205 qualified calls.

## 2. Verdicts (mechanical; `units.<unit>.cell_final`, `summary_raw`)

The N6 cell is the E verdict where E exists and is not INSUFFICIENT_N, otherwise the B verdict. Artifact checks can
only lower it. 28 verdict blocks were computed (`cells_computed`: unit × split × scope). No family-wise correction was
applied.

| unit | N6 cell (primary: shell) | B | E | B ∪ E pooled (not the cell) | deciding number (JSON path) |
|---|---|---|---|---|---|
| swechat/claude_code | **ALIVE** (human-wait contaminated) | ALIVE | ALIVE | ALIVE | E: ρ_hon CI [0.016, 0.046] inside ±0.15; ρ_pc CI lo 0.425 ≥ 0.30; RR 0.175 ≥ 0.10; flag rate 0.0103 ≤ 0.02, CI hi 0.0143 ≤ 0.05 (`results.E.shell.verdict.deciding_number`) |
| aiv_cc (single-agent case study) | **ALIVE** (B only, unreplicated) | ALIVE | — | — | ρ_hon CI [0.002, 0.074]; ρ_pc CI lo 0.707; RR 0.310; flag 0.0058, CI hi 0.0158 (`results.B.shell.verdict`) |
| swechat/codex | **INSUFFICIENT_N** (NOT_REPLICABLE_AT_N) | INSUFFICIENT_N (837 residuals, **18 s** < 20) | INSUFFICIENT_N (232, 14 s) | WEAK: honest flag rate 0.0262 > 0.02, CI hi 0.0548 > 0.05 | `results.B.shell.residuals.n_sessions` = 18 |
| swechat/gemini | **INSUFFICIENT_N** (NOT_REPLICABLE_AT_N) | INSUFFICIENT_N (279, 11 s) | INSUFFICIENT_N (62, 9 s) | WEAK: flag rate 0.0293, CI hi 0.0591 | `results.B.shell.residuals.n_sessions` = 11 |
| swechat/opencode | **INSUFFICIENT_N** (NOT_REPLICABLE_AT_N) | INSUFFICIENT_N (577, 13 s) | INSUFFICIENT_N (192, 11 s) | **DEAD**: ρ_pc CI lo 0.138 ≤ ρ_hon CI hi 0.158 | `results.BE.shell.verdict.deciding_number` |
| cc_local (private) | **INSUFFICIENT_N** (B only) | INSUFFICIENT_N (943 residuals, **7 s**) | — | — | `results.B.shell.residuals.n_sessions` = 7; RR 0.043 would also fail ALIVE |
| aiv_cu, whowhen, swechat/cursor | NOT_TESTABLE | call and result share one stamp / no stamps / no results | | | `not_testable` |
| swechat/copilot, simple_text | not run | no copilot session in B or E; simple_text has no pairs | | | `units_not_in_prereg_list` |

**Kill tests.** The pre-registered DEAD rule fired once: **swechat/opencode, B ∪ E pooled shell**. Its synthetic
positive control does not separate from the honest residuals: ρ_pc 0.324 [0.138, 0.498] against ρ_hon 0.087 [0.039,
0.158]. That pooled block is not the N6 cell, which is INSUFFICIENT_N on both B and E. No artifact check fired in any
unit. No block reached INCONCLUSIVE.

**Secondary scope (auto_read).**
- swechat/claude_code auto_read is ALIVE on B, E and B ∪ E. E: ρ_hon 0.057 [0.034, 0.085], ρ_pc 0.559 [0.498, 0.621],
  RR 0.108, flag rate 0.0029 [0.0004, 0.0063].
- Every other auto_read block is INSUFFICIENT_N, or has no qualified calls (codex).

## 3. The numbers behind the verdicts (primary scope, shell)

| unit / split | residuals (s) | ρ_hon = Spearman(r, log10 bytes) | ρ_pc (tampered, n) | honest flag rate at A bounds | secondary ρ(r, Δlog bytes) |
|---|---|---|---|---|---|
| claude_code B | 6,056 (569) | 0.027 [0.012, 0.041] | 0.468 [0.425, 0.511] (1,970) | 76/6,056 = 0.0125 [0.0087, 0.0167] | 0.108 [0.065, 0.151] |
| claude_code E | 5,809 (498) | 0.031 [0.016, 0.046] | 0.474 [0.425, 0.527] (1,872) | 60/5,809 = 0.0103 [0.0069, 0.0143] | 0.073 [0.030, 0.114] |
| claude_code B ∪ E | 11,865 (1,067) | 0.029 [0.019, 0.039] | 0.471 [0.439, 0.505] (3,842) | 136/11,865 = 0.0115 [0.0090, 0.0143] | 0.091 [0.062, 0.121] |
| aiv_cc B | 1,901 (34) | 0.039 [0.002, 0.074] | 0.796 [0.707, 0.858] (308) | 11/1,901 = 0.0058 [0.0022, 0.0158] | 0.106 [−0.014, 0.175] |
| codex B ∪ E | 1,069 (32) | 0.034 [0.013, 0.078] | 0.841 [0.671, 0.912] (301) | 28/1,069 = 0.0262 [0.0089, 0.0548] | 0.117 [0.053, 0.230] |
| gemini B ∪ E | 341 (20) | 0.011 [−0.143, 0.101] | 0.566 [0.375, 0.706] (71) | 10/341 = 0.0293 [0.013, 0.0591] | 0.007 [−0.229, 0.136] |
| opencode B ∪ E | 769 (24) | 0.087 [0.039, 0.158] | 0.324 [0.138, 0.498] (93) | 10/769 = 0.013 [0.003, 0.0326] | 0.230 [0.140, 0.355] |
| cc_local B | 943 (7) | 0.019 [−0.027, 0.062] | 0.843 [0.821, 0.948] (311) | 2/943 = 0.0021 [0, 0.0041] | 0.179 [−0.002, 0.263] |

**Residual distributions** (`residuals.q*`, decades). The spread is narrow in the middle and wide in the tails:
- claude_code B ∪ E shell: median |r| 0.076; p5 / p95 −0.626 / 0.647; p0.5 / p99.5 −2.002 / 2.212.
- aiv_cc: median |r| 0.044; p5 / p95 −0.248 / 0.272.
- opencode B ∪ E: median |r| 0.035; p5 / p95 −0.145 / 0.185.

The median number of same-status references per residual is 2.0 in claude_code, 13.0 in aiv_cc and 9.0 in opencode
B ∪ E.

**Positive-control mechanics** (`positive_control`).
- One tampered instance per repeat group, δ' = result chars × 0.25 / G90(unit).
- claude_code B ∪ E: 4,098 tampered groups. 256 of them were dropped because the result had 0 chars (δ' = 0). Median
  T_gen is 1.138 s.

**Natural control** (Phase B G set, copied from `probe_1.json`; `natural_control_phase_B_G_set`):
- swechat/claude_code: 0.496 [0.421, 0.570], 3,812 pairs.
- aiv_cc: 0.751 [0.644, 0.940].
- cc_local: 0.695 [0.533, 0.805].
- opencode: −0.048 [−0.263, 0.311].
- gemini: INSUFFICIENT_N.
- codex: no G set.

## 4. Artifact checks (B ∪ E; `units.<unit>.artifact_checks`)

These ran for the two cells at WEAK or better (claude_code, aiv_cc). For information they also ran on the codex and
gemini pooled WEAK blocks, without AC1.

| check | swechat/claude_code (base ALIVE) | aiv_cc (base ALIVE, B) |
|---|---|---|
| AC1 parser, 30 detector-flagged events vs raw source | **PASS**: 0/30 differ (pool 136 flagged); 30/30 stamps equal | **PASS**: 0/11 differ (only 11 flagged exist, all audited) |
| AC1 diagnostic, 30 random residual-bearing events (not a verdict) | 0/30 differ | 0/30 differ |
| AC2 without truncated results | ALIVE (11,652 residuals; ρ_hon 0.026 [0.016, 0.037], ρ_pc 0.470 [0.435, 0.501]) | ALIVE (1,899) |
| AC3 join-clean pairs only | ALIVE (11,715; ρ_hon 0.028 [0.017, 0.039]) | ALIVE (1,901) |
| AC4 dominance | dominated (repo 0.256 of residuals; user 'nan' = missing user_id, 0.383; model 0.756), **label stable**: 15/15 leave-outs ALIVE (min ρ_pc CI lo 0.409, max ρ_hon 0.032, max flag rate 0.0142, min RR 0.155; leaving out the missing-user_id cluster keeps 7,317 residuals in 678 s) | agent and model are single clusters: labelled only. Top run holds 0.261 of residuals; 5/5 run leave-outs ALIVE |
| AC5 post-stratified | ALIVE (ρ_hon 0.031 [0.017, 0.045], ρ_pc 0.495 [0.458, 0.534], RR 0.170, flag 0.0128, CI hi 0.0176); SHIFT no (B point 0.027 inside E CI [0.016, 0.046]) | NOT_RUN (no population table) |
| strata: tool_key / model / repo / length tercile | UNTESTABLE (1 reportable) / OK (4 ALIVE) / OK (9 reportable, all WEAK or ALIVE) / OK (mid, long ALIVE; short WEAK): **not CONFINED** | OK (shell and mcp__village__bash both ALIVE) / UNTESTABLE / UNTESTABLE / UNTESTABLE |
| final | **ALIVE** | **ALIVE** (single-agent case study, B only) |

Pooled codex and gemini blocks, for information only (not cells):
- **codex:** AC2, AC3 and AC5 stay WEAK. AC4 is UNTESTABLE_WITHOUT_DOMINANT: leaving out zchee/zmux (0.501 of
  residuals) leaves 13 sessions, and leaving out the missing-user_id cluster leaves 14.
- **gemini:** one repo and user (hirakiuc/gh-orbit) holds 0.968 of residuals, and every leave-out falls below 20
  sessions. AC5 SHIFT holds: the B ρ_hon point 0.040 lies outside the E CI [−0.184, 0.029].

## 5. Nulls, stated plainly

- **Five of six testable units have no N1 verdict at the pre-registered minimum n** (≥ 200 residuals from ≥ 20
  sessions on B or E).
  - codex: 18 and 14 sessions.
  - gemini: 11 and 9.
  - opencode: 13 and 11.
  - cc_local: 7.

  N1 is a claude_code result, plus a single-agent case study.
- **cc_local shell coverage is 0.043.** This falls below the 0.10 coverage condition even before min n.
- **opencode shell, B ∪ E pooled: DEAD.** The synthetic positive control ρ_pc 0.324 does not clear the honest ρ_hon
  CI.
- **The per-call detector barely sees the synthetic positive control in claude_code shell.** This is a diagnostic, not
  a verdict input (`positive_control.detector_flag_on_tampered_diagnostic`). At the A bounds [−2.025, 1.998] it flags
  219/3,842 = 0.057 [0.048, 0.065] of tampered shell instances in B ∪ E. In claude_code auto_read the same diagnostic is
  1,633/2,078 = 0.786 [0.761, 0.808]. For aiv_cc shell it is 138/308 = 0.448 [0.365, 0.528], for cc_local shell 155/311
  = 0.498 [0.382, 0.541], for codex B ∪ E 52/301 = 0.173 [0.109, 0.286] and for gemini B ∪ E 1/71 = 0.014 [0, 0.064].
- **auto_read coverage is low** in opencode (B ∪ E 0.028) and aiv_cc (0.038).

## 6. What could not be measured

- **Units without stamps.** aiv_cu, whowhen and swechat/cursor are NOT_TESTABLE: their stamps are shared, absent, or
  they have no results.
- **Small units.** codex, gemini and opencode have too few E sessions for any replication (E sessions in cache: 65,
  14 and 193, of which 14, 9 and 11 have shell residuals).
- **Human wait.** It cannot be removed from claude_code and cc_local shell durations, because the IR has no
  permissionMode. The A bounds therefore include human-wait tails.
- **No ground truth.** The positive control is synthetic: a generation time computed from result length. Recall
  against real fabrication is unmeasured.

## 7. Deviations and implementation choices (`deviations` in the JSON; full text there)

1. **Output file names.** They follow the pre-registration (`phase_e_n1.py` → `n1.json`), not the orchestrator's
   `n1_duration` template.
2. **Positive-control draw.** The tampered instance is drawn among the instances that have a same-status reference.
   The rng key is `rng_for('N1pc', session_id, n1_key)`.
3. **Empty results.** A tampered instance whose result has 0 chars has δ' = 0. It is dropped from ρ_pc and counted.
4. **Rule gaps.** A ρ_hon point below −0.15, or a CI that cannot be reported, maps to INCONCLUSIVE. No block hit this.
5. **Scope.** The cell uses the primary scope (shell). auto_read is the secondary scope.
6. **Pooled blocks.** B ∪ E pooled verdicts are reported but are never the cell. AC2–AC5 and the strata were run on
   the codex and gemini pooled WEAK blocks for information only. AC1 was not run for them.
7. **AC1.** The sample is 30 detector-flagged events (fewer exist in aiv_cc: 11). AC1 FAIL would cost one level. A
   residual-instance audit is reported as a diagnostic.
8. **AC4.** Denominator events are residuals. Leave-outs recompute RR over every session outside the cluster. The
   aiv_cc single clusters are labelled only (PREREG_E §1.1). A missing swechat user_id forms one cluster.
9. **AC5.** Uses a weighted Spearman (weighted mid-ranks, weighted Pearson) with a session bootstrap.
10. **AC3.** Copied call_ids are taken over the corpus's B and E caches.
11. **Natural control.** Copied from Phase B, not recomputed on E.

## 8. Interpretation (not data)

- **What survived.** In swechat/claude_code, the one large unit, the honest within-session residual is nearly
  independent of output size: ρ_hon 0.029 on 11,865 residuals in 1,067 sessions.
  - The CI excludes 0 but sits far inside ±0.15.
  - It replicates on E: 0.031 against B's 0.027.
  - It survives every artifact check, and no stratum confines it.

  That is the property N1 needs. A substituted duration proportional to output length would be visible as a
  correlation (ρ_pc ≈ 0.47).
- **What ALIVE does and does not mean here.**
  - The pre-registered rule judges separation at the level of a *correlation over many calls*. It does not judge the
    per-call detector.
  - The per-call detector, with the A-split bounds, catches 0.057 of synthetic tampered shell calls in claude_code. The
    honest shell residual tails reach ±2 decades: repeated `pytest`, build or network commands
    vary that much, and human wait is in the durations. A generation-time substitution usually lands inside that band.
  - So N1-shell is ALIVE as a population-level signal and weak as a per-call alarm. auto_read, where repeats are tight,
    is the opposite case: the same diagnostic is 0.786.
  - N7 will give the formal per-attack recall. This note predicts nothing for it beyond these diagnostics.
- **Coverage is the binding limit.** Even where N1 works it can speak to 0.172 of qualified shell calls, and 0.114 of
  all shell pairs, in claude_code. That is because repeats of the same normalised command are the minority.
- **No transfer evidence yet.**
  - Every other harness is either too small to test, dominated by one repo (gemini 0.968, codex 0.501), or DEAD at
    pooled n (opencode, where the positive control itself is weak: shell durations there sit in a narrow band and
    T_gen does not track the residual).
  - aiv_cc agrees with claude_code, but it is one agent.
  - Whether N1 transfers across harnesses is therefore open, not shown.
