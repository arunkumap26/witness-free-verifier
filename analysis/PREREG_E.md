# Phase E pre-registration

This file fixes, before any Phase E measurement, how the A1 second pass, the new candidates N1–N5, the transfer grid N6
and the attack battery N7 are run, on which data, with which thresholds, and how results map to verdicts. The
machine-readable twin is `analysis/prereg_e.json`. Where this file and the JSON differ, the JSON wins and the
difference is a bug to log in `change_log`.

It builds on the Phase B pre-registration (`analysis/PREREG.md`, `analysis/prereg.json`,
`analysis/probes/prereg_common.py`, commit 3df8d28). Everything Phase B defined (pairing, the no-human-wait filter, error
classes, the Probe 1–4 statistics, verdict rules and A-split thresholds) is reused unchanged unless a section below says
otherwise. Nothing in the Phase B files was edited.

**Files.**
- `analysis/probes/prereg_e_common.py` holds the frozen definitions (`SPEC_E`, every regex in `RX_E` and
  `PARAM_CONTEXT`) and the code that implements them: guards, artifact checks, the bracket and its placebo, the
  floor-shift covariates, the parameter-exclusion rule, N1–N5 extraction and detectors, and the N7 attack injectors.
  Measurement scripts import it and must call `check_frozen()` first. It compares the LF-normalised sha256 of the module
  with `prereg_e.json provenance.spec_module_sha256_lf`. The comparison ignores line endings because `core.autocrlf` is
  true in this repo.
- `analysis/probes/prereg_e_calibration.py` (`PYTHONIOENCODING=utf-8 python -m analysis.probes.prereg_e_calibration`,
  1.5 to 3 minutes; the actual time is in `runtime_s`) reads split A. It writes raw counts to `analysis/out/phase_e/prereg_e_calibration.json`, then writes
  `prereg_e.json`. That file holds SPEC_E, the thresholds derived from A (`resolved`), the earlier-phase numbers this
  file quotes (`references`, copied by explicit JSON path) and the sha256 provenance of every input.

**What I read, and what I did not.**
- Read: the briefs, `PREREG.md`, `prereg.json`, the Phase B probe outputs, `FINDINGS.md`, `phase_d/ranking.json`, the
  Phase C lens scripts and the split A caches.
- Not opened: any `*_B.parquet`, `*_E.parquet` or `*_EH.json`, or anything held out (H).
- `prereg_e_calibration.json opened_files` lists every file the calibration opened. The script asserts that none of them
  is a B, E, EH or H file.
- The swechat `sessions.parquet` was read with a pyarrow filter on split-A ids, so no other row was loaded.

**What the calibration computed on A, and what it did not.**
- **Computed:** feasibility counts, harness constants, noise-scale parameters and detector thresholds. Each is listed
  where it is used.
- **Not computed on A:** any Phase E outcome. That excludes:
  - every correlation (N1 ρ, N3 ρ);
  - every detector flag or violation rate (N2, N5, R2, R3);
  - determinism drift;
  - round-number shares;
  - recall and tamper results;
  - any second-pass statistic.

Notation: `C:` = `prereg_e_calibration.json units.<unit>.<path>`, `R:` = `prereg_e.json resolved.<path>`, `REF:` =
`prereg_e.json references.<key>`, `S:` = a `prereg_e.json` section. Rates are k/n [95% CI]; s = sessions; W = Wilson.
**[S]** marks a number that came from a Phase C skeptic's uncommitted scratch script and survives only as text in a
committed file.

---

## 0. Splits and global rules (`S:splits`, `S:global`)

| Split | Role | Who reads it in Phase E |
|---|---|---|
| A | calibration | `prereg_e_calibration.py` only |
| B | Phase B split. Phase C lenses also read it, so B is not blind for any Phase C observation | measurement |
| E | fresh Phase E split: swechat 1,825, aiv_cu 2,000 sessions (REF:heldout_manifest_counts) | measurement; reported separately as the replication |
| H | held out for the Track C eval | **nobody**. `read_cache()` refuses it. `split_ids()` reads only key `"E"` of the EH file |

- **Re-measurement population.** Every second-pass statistic and every artifact check runs on B ∪ E pooled, which gives
  the larger n. The replication verdict uses E alone.
- **Units without E.** cc_local, aiv_cc and whowhen are re-measured on B only and labelled UNREPLICATED.
- **No new cc_local split.** No post-commit cc_local split is built. Recent local Claude Code sessions include sessions
  that operate the local Qwen swarm, which is out of scope.
- **Projected E sessions per unit.** These are counts, not measurements (R:e_projection = n_E × B_unit / B_corpus):

  | unit | projected E sessions |
  |---|---|
  | swechat/claude_code | 1,532.1 |
  | opencode | 195.3 |
  | codex | 70.3 |
  | gemini | 20.1 |
  | cursor | 7.3 |
  | copilot and simple_text | 0 each |
  | aiv_cu | 2,000 |

**E is not fresh everywhere (`S:splits.E_freshness`).**
- Two committed Phase C lenses read event data beyond B:
  - `phase_c_commit_witness.py` drew a seeded sample from the whole swechat population;
  - `phase_c_swechat_tables.py` read the whole population's tables and transcripts.
- Skeptic re-runs that the index describes as "full population" (raw_census A6-O1/O2, commit_witness O9/O11,
  swechat_tables T1/T3) also read E and H sessions.
- Consequences:
  - **R3 git, R4 dual and R5 ledger are labelled "E not blind"** and can at best reach SURVIVES (not blind).
  - **Their H numbers are not fully blind either.** Track C must say so.
  - H is still untouched by Phase E itself.
- Population *metadata* tables carry no event data. Several lenses read them.

**Global rules.**
- **CIs and minimum n.** CI methods, the minimum-n rules and the zero-numerator rule are those of `prereg.json
  global`:
  - cluster_rate for rates, cluster_quantile for quantiles, Wilson for session shares;
  - the session bootstrap (`boot_stat`) for Spearman, AUC and differences, with ≥ 900 of 1,000 valid draws;
  - a rate needs ≥ 30 events from ≥ 5 sessions; a p1 needs ≥ 500 from ≥ 5 sessions.

  Item-specific minima below only add to these.
- **Threshold sources.** §9 lists every threshold in this file by source: derived from split A, carried from Phase B/C/D, or
  a judgment call fixed now.
- **Seeds.**
  - Bootstrap: 20261003.
  - Tamper draws, donors and N7 subsamples: SEED_E = 20261005, through `rng_for(*parts)`.
  - Split of any new Track B corpus: 20261006.
- **Verdicts.**
  - Mechanism cells use ALIVE / WEAK / DEAD / INSUFFICIENT_N / INCONCLUSIVE / NOT_TESTABLE / NOT_RUN.
  - NOT_RUN is never read as a null.
  - No family-wise correction is applied, and every output reports how many cells it computed.
- **Outputs.**
  - One committed script and one raw-count JSON per item (`S:outputs`), each carrying prereg_e.json's sha256.
  - Interpretation goes to `SECOND_PASS.md` and `DECISION_TABLE.md`, never into a JSON.
- **Labels.** cc_local outputs are aggregates only. Every aiv_cc number carries "single-agent case study".
- **New corpora (`S:splits.new_corpora`).** Any corpus Track B downloads is split at load time.
  - A = min(200, 20% of N). The remainder R splits into B = min(2,000, R/3), E = min(2,000, R/3) and H = the rest,
    using lib/sample cells and seed 20261006.
  - Its unit thresholds come from its own A, through `calibrate_unit()`, and are written to
    `prereg_e_calibration_<corpus>.json` before its B or E is read.
  - That file's sha256 is appended to `change_log` as a pre-registered extension.

---

## 1. A1: second pass on surviving candidates

### 1.1 Artifact checks (`S:artifact_checks`; run on B ∪ E for every candidate, and for any N cell that reaches WEAK or better)

| Check | Procedure | Fail rule |
|---|---|---|
| AC1 parser | `audit_sample()` draws 30 numerator (or flagged) events with SEED_E. Each is looked up in the raw source, and the fields the statistic uses are compared: stamps, join, text length, error flag, request id | FAIL if ≥ 2 of 30 differ in a way that changes their contribution. 1 = PARSER_NOTE |
| AC2 truncation | recompute without results matching `truncated_result()` (the A3 marker catalogue plus `extra.truncated`) | FAIL if the label changes. The candidate takes the lower label |
| AC3 join | recompute on `join_clean_mask()` pairs: unique (session, call_id) on both sides, result after call, both stamps parse, call_id not present in another session | FAIL if the label changes. Lower label |
| AC4 dominance | clusters: repo (swechat `repo_id`; aiv_cu `agent_id`; cc_local project alias), user, model, single session. **Dominated if one repo, user or model holds > 0.25 of the denominator events or contributing sessions, or one session holds > 0.10 of the events.** If dominated: leave the dominant cluster out, then drop each of the 5 largest clusters one at a time | one-level downgrade (DOMINATED) if any leave-out drops the label. If a leave-out falls below min n: capped at WEAK (UNTESTABLE_WITHOUT_DOMINANT) |
| AC5 sampling | post-stratified recompute (`post_strat_weights`). Each session is weighted by its population cell size over the analysed sessions in that cell. Cells are recomputed from population metadata, which reproduces `samples/<corpus>.json population_by_cell` exactly: swechat 23 cells over 5,850 sessions, aiv_cu 30 cells over 78,114 (`prereg_e_calibration.json ac5_population_cells_check`). NOT_RUN for corpora without a population table | FAIL if the weighted label differs. Also reported: SHIFT if the B point lies outside the E CI (no verdict effect) |

**The dominance threshold 0.25 is a judgment call.** Above that share one cluster alone can move a clustered rate across
a verdict boundary. The A split shows that dominance is the norm, so AC4 will run for almost every candidate
(R:dominance_context_A). The top cluster's share of A paired calls is:

| unit | repo | user | model |
|---|---|---|---|
| swechat/claude_code | 0.339 | 0.415 | 0.705 |
| swechat/opencode | 0.920 | 0.765 | 0.791 |
| swechat/codex | 0.378 | 0.573 | 0.823 |
| cc_local | 0.896 | — | 0.933 |
| aiv_cu (agent) | 0.096 | — | 0.169 |

aiv_cu is the only unit not dominated at A. aiv_cc is one agent, so it is always dominated, and that is only labelled.

**Stratification (`S:stratification`).** Four axes:
- tool_key;
- modal model;
- repo (the AC4 cluster);
- session-length tercile, with cut points at the unit's A terciles of paired calls (R:length_terciles_A; e.g.
  swechat/claude_code 33.0 / 102.7, cc_local 5.7 / 17.0, aiv_cu 29.0 / 40.0).

A stratum is reportable if it meets the candidate's own minimum n. On an axis with at least two reportable strata, a
signal that reaches WEAK or better in exactly one of them is **CONFINED**. That costs one level (ALIVE → WEAK,
WEAK → DEAD).

**Survival rule (`survival_status()`).**

| Status | Rule |
|---|---|
| KILLED | the E verdict is DEAD, or an artifact check fails to DEAD, or a candidate kill test fires |
| DOWNGRADED | E is one level below the Phase B verdict, or a check or confinement lowers it one level |
| SURVIVES | E ≥ Phase B, every check passes, not CONFINED or DOMINATED |

Suffixes: "(B only, unreplicated)" for units without E; "(NOT_REPLICABLE_AT_N)" when E is INSUFFICIENT_N; "(E not
blind)" for R3–R5.

**No rescue.** A check can only lower a label. Post-hoc subsets, corrections and alternative definitions are reported
as "post hoc, not a verdict".

### 1.2 Candidates and their Phase B numbers (REF:P1_verdict, P2_verdict, P3_zero_error_B, P4_round_B)

| Candidate | Phase B | Deciding number (B) | E? | Kill tests |
|---|---|---|---|---|
| P1 swechat/opencode | ALIVE | fp 7/4,419 = 0.0016 [0, 0.0033]; AUC 0.999 [0.998, 1.000]; G 127 pairs from 12 s | yes | K1–K3. AC4 mandatory: 175 of the 214 B opencode sessions come from one repo (REF:opencode_one_repo **[S]**, REF:population_B) |
| P1 cc_local | ALIVE | fp 1/1,019 = 0.0010 [0, 0.0033]; AUC 0.919 [0.881, 0.971]; G 153 pairs from 12 s | no | K1–K3. The G histogram is bimodal: the first four bins hold 1 + 13 + 29 + 8 = 51 of 153 (REF:cc_local_G_bimodal) |
| P1 swechat/claude_code | WEAK (floor UNSTABLE) | fp 72/20,937 = 0.0034 [0.0025, 0.0044]; AUC 0.987 [0.980, 0.993]; steps 21/156 series = 0.135 W[0.090, 0.197] | yes | K1–K3 + F2 (cannot raise the verdict) |
| P3 zero-error tail, swechat/claude_code | ALIVE | Z = 9/413 = 0.022 W[0.012, 0.041] at L75 = 134; E0 0.000908; Z/E0 24.0 | yes | K1–K4 |
| P4 round numbers, swechat/claude_code | ALIVE | T_orig last-0 127/300 = 0.423 [0.334, 0.520] against M_all 2,365/20,419 = 0.116 [0.110, 0.122] | yes | F3 |
| P4 round numbers, cc_local | ALIVE | 221/341 = 0.648 [0.435, 0.786] against 2,243/18,550 = 0.121 [0.110, 0.130] | no | F3 |
| P4 round numbers, swechat/* pooled (added by the audit) | ALIVE (pooled Phase B row, `decision_table.json`) | the pooled row; swechat/claude_code supplies 1,679 of the 2,000 swechat B sessions (REF:population_B), so it is not independent evidence | yes | F3, labelled "pooled" |
| P2 swechat/claude_code main | WEAK | S_deep 671/4,655 = 0.144 [0.125, 0.163], 586 s | yes | P2 K1–K2 |
| P2 swechat/claude_code subagent | WEAK | S_deep 525/6,850 = 0.077 [0.062, 0.091], 296 s | yes | P2 K1–K2 |
| P2 swechat/opencode subagent | WEAK | S_deep 16/219 = 0.073 [0.020, 0.150], 53 s (rests on a logged root-rule deviation) | yes | P2 K1–K2 |
| P2 swechat/codex subagent | WEAK | S_path_any 104/795 = 0.131 [0.099, 0.163], 36 s | yes (small) | P2 K1–K2 |
| P2 aiv_cc main | WEAK | S_path_any 710/3,689 = 0.192 [0.081, 0.351], 53 runs | no | P2 K1–K2 |
| R1–R5 (Phase D proposals) | untested | §1.4 | R1, R2 yes; R3–R5 E not blind | §1.4–1.5 |

Every Phase B ALIVE or WEAK cell in `analysis/out/phase_e/decision_table.json` is either a candidate above or listed
here (`S:a1.not_carried_into_A1`). The listed cells keep their Phase B verdict, get no A1 kill battery, and are re-run on
E in the N6 grid where the unit has E. Pooled rows have no N6 column and keep their Phase B verdict only.
- Probe 1: swechat/codex, swechat/gemini, aiv_cc (WEAK).
- Probe 3a zero-error tail: whowhen/Algorithm-Generated (WEAK).
- Probe 3b reaction: swechat/claude_code, swechat/opencode, cc_local, aiv_cu (WEAK).
- Probe 4a hex: swechat/claude_code, aiv_cu, swechat/* pooled, public/* pooled (WEAK).
- Probe 4b round numbers: aiv_cu, public/* pooled (WEAK).

### 1.3 Candidate-specific kill tests

**Probe 1** (all three units). The statistics are fp_share and AUC exactly as `prereg.json probe1.separability`, with
G90 from `prereg.json resolved.probe1.generation_rate`.
- **K1 control composition.**
  - Recompute AUC with G restricted to subagent, webfetch and websearch: workflow and search_history are excluded.
  - Then drop the session holding the most G pairs.
  - AUC DEAD → KILLED. G below 30 pairs from 5 s → capped at WEAK ("control too concentrated").
- **K2 floor stability.**
  - Run the Phase B change-point rule on B ∪ E and on E.
  - UNSTABLE → one-level downgrade.
  - Fewer than 30 series or fewer than 5 s → "floor untested" (no downgrade, flagged).
- **K3 stamp quality.** Exclude whole-second stamps. A label change takes the lower label.

**Probe 3 zero-error tail.** The statistic and verdict rule are `prereg.json probe3`, with L75 = 134 from A.
- K1: Z over long sessions with ≥ 10 shell calls. Z > 0.10 → DOWNGRADED; Z > 0.30 → KILLED.
- K2: Z with cc_tool_use_error removed from the error class. Z > 0.10 → DOWNGRADED ("friction is
  harness-validation-driven").
- K3: Z per model and per repo, with ≥ 20 long sessions per stratum. A reportable stratum holding ≥ 0.20 of long
  sessions with Z > 0.30 → DOWNGRADED.
- K4: Z at L90 is reported, with no verdict effect. Phase B had 0 zero-error sessions among 224 long sessions at L90 =
  220 (`analysis/out/probe_3.json units.swechat/claude_code.zero_error_tail.L90`).

**Probe 2 WEAK cells.** The statistic is S_deep (fallback S_path_any, capped at WEAK) exactly as `prereg.json probe2`,
with D_unit from Phase B's A split. The instrument check is re-run.
- K1: recompute with the strict pre-registered workspace-root rule. DEAD → KILLED ("rule-sensitive").
- K2: S_deep on sessions with no compaction, resume or /clear event. Reported only.

### 1.4 The five Phase D proposals (`S:a1.proposal_rules`)

The verdict comes from two numbers: the honest flag rate on B ∪ E (E separately), and the N7 recall cells of the
proposal's detector.

| Verdict | Rule |
|---|---|
| ALIVE | session-level (stream-level for R1) honest flag rate ≤ 0.05 with CI hi ≤ 0.10, **and** ≥ 1 single-call or single-response attack type DETECTS in N7 on E (B for units without E) |
| WEAK | honest flag rate ≤ 0.20, and ≥ 1 attack type is DETECTS or PARTIAL |
| DEAD | otherwise |

Judgment calls, as in Phase B: 0.05 is the false-positive budget at which a flag stays usable over many decisions.

- **R1 request-id bracket** (swechat/claude_code B ∪ E; cc_local B only). F1 below (§1.5) is part of it.
  - Phase D's kill rule is adopted. A tamper type whose flagged-stream CI lo is ≤ the honest CI hi is a null for that
    type.
  - If no single-response type other than back-dating clears that bar, R1 is WEAK ("back-dating only").
  - If 30 s back-dating fails too, R1 is DEAD.
  - **If F1 Step 0 is NOT_REPRODUCED** (§1.5), R1 is still measured with the Phase E code on B and E. No Phase C bracket
    or placebo number is then cited as evidence for it, and its verdict carries the suffix "(Step 0 NOT_REPRODUCED)".
- **R2 image-token ledger** (aiv_cu Gemini strata, B ∪ E). Phase D's kill rule is adopted: a session-level honest flag
  rate above 0.05 → DEAD.
  - **Window.** `image_windows()` + `image_window_violation()`: a window is consecutive usage-bearing calls. Its
    increment must be positive iff a GUI result falls in the window, and must sit on the unit lattice.
  - **Units (R:image_units_A.rule).** A model string uses its own A mode if it has ≥ 20 positive A windows: gemini-2.5-pro
    258 (192 windows), 2.5-pro-preview-06-05 258 (54), 3.1-pro-preview 1,064 (168), 3.5-flash 1,064 (191). Otherwise
    it uses its generation family's A mode: 258 for gemini-2.5, 1,064 for gemini-3. That covers 2.5-pro-preview-03-25,
    3-pro-preview and 3.8-flash; the latter two had 0 GUI windows on A.
  - **No image accounting.** A model with ≥ 10 GUI windows on A and no positive increment would be NOT_TESTABLE. None
    qualifies on A.
  - **Strata.** Model generation, and sessions with ≤ 40 versus > 40 GUI windows.
  - **B context, not a threshold.** GUI windows without an increment 33/5,092; non-GUI windows with one 0 of 6,853
    (REF:image_B).
- **R3 git execution window** (swechat, all formats with shell; E not blind).
  - **Scope.** Only claims printed by generator commands count (`git_cmd_class`): git commit / merge / cherry-pick /
    revert / rebase / am / pull.
  - **Separate classes.** Explicit-date commands (GIT_COMMITTER_DATE, --date) and re-readers (cat, tail, head, grep,
    ...) are classed apart. This fixes now the classification Phase C made after the fact (15 of its 19 out-of-window
    claims were re-reads; REF:git_nonresolution).
  - **Window.** [call ts − 2 s, result ts + 2 s] (`git_window_ok`).
  - **Abstention.** Non-resolving SHAs abstain, because 2,198/6,141 honest claims do not resolve.
  - **Coverage stop rule.** If claims cover < 0.005 of tool results, the verdict is capped at WEAK.
  - **A counts.** Generator claims: swechat/claude_code 194 claims in 58 s, opencode 34, codex 6, gemini 4. Re-reader
    claims: 4 (C:r3_git).
- **R4 dual-rendering recount** (E not blind). Needs raw `toolUseResult.file.numLines`, which the IR does not carry.
  - It is read from the swechat transcripts for B ∪ E Claude Code sessions and joined on tool_use_id.
  - **cc_local raw source, pinned now.** cc_local raw fields are read only from the frozen snapshot
    `data/claude-code-local` (the cc_local loader's ROOT), for split B session ids, in-process, aggregates only. They are
    never read from `~/.claude/projects` or any other live session store. Live stores hold sessions that operate the
    local Qwen swarm, which is out of scope.
  - **The whitelist is frozen now (`dual_whitelisted()`).** It covers persisted-output previews, "shorter than the
    provided offset" warnings, identical-to and unchanged references, redaction, negative line numbers, and (cc_local
    only) the empty-file warning.
  - Phase C classified its 402 mismatches into five formats with uncommitted code (REF:dual_population). The regexes
    here are a fresh frozen definition. The whitelist-coverage table is an output.
  - **Whitelist changes.** A class added after seeing B or E is logged and cannot raise the verdict.
  - **Blocked.** If the raw join is not implemented: NOT_RUN.
- **R5 usage-ledger** (E not blind). The Entire 5-integer tally is compared with a tolerance-0 recount of deduplicated
  per-response usage.
  - Phase C context: 33/5,701 unmatched after the join fix (REF:ledger_unmatched).
  - If not implemented: NOT_RUN.

### 1.5 Follow-up F1: the 10 honest bracket failures (`S:followups.F1_bracket_failures`)

**Step 0 comes before any bracket claim.** A committed script, `phase_e_f1_bracket.py`, re-implements the bracket and
its placebo using:
- `bracket_responses()`;
- `bracket_streams()`;
- `placebo_shift()`;
- `roll_ids()`.

It runs on the same streams: swechat/claude_code split B, streams with ≥ 2 decoded responses. The committed Phase C
lens counted 3,676 such streams with 10 inconsistent: cluster rate 0.00272 [0.00112, 0.00466] over 1,610 sessions
(REF:bracket_B_committed_lens).

- **Bracket.** For each response k:
  - lo_k = ts(last result or user event of the stream before the response's first event) − id_ms;
  - hi_k = ts(response's first event) − id_ms.

  Then L = max lo and U = min hi. A stream is inconsistent if L − U > 2,000 ms. Ids are decoded by `decode_req_ms`
  (48-bit ms layout inferred from data, UNVERIFIED against documentation), and ids more than 1 day from their event are
  dropped. A stream is (session, agent_id if subagent, else main).
- **Placebo.** One response per stream is chosen uniformly (`rng_for('F1', D, session, stream)`). Its first event moves
  D earlier for D ∈ {5, 30} s, and D later for D ∈ {5, 30, 300} s. `roll_ids` gives every response its successor's id;
  it is a reference only.
- **REPRODUCED** if all of these hold on the same stream set:
  - (a) the honest inconsistent count is 10 ± 3;
  - (b) the 5 s back-date flag share is within 0.03 of 1,441/3,673 **[S]**, and the 30 s share within 0.01 of
    3,581/3,673 **[S]** (REF:placebo_skeptic_text);
  - (c) every later shift flags within the honest count ± 3.

  Otherwise NOT_REPRODUCED. The Phase C placebo numbers are then withdrawn, and rank 1 loses its criterion-(a) lead (the
  Phase D condition). What then happens to R1 is fixed in §1.4.
- **Stream count.** Three stream counts circulate: the committed lens's 3,676 (REF:bracket_B_committed_lens), the skeptic
  text's 3,673 for the placebo shares and the 3,674 quoted in the brief (REF:placebo_skeptic_text). The re-implementation
  reports its own count next to them. A different count is reported as such and is not reconciled post hoc. The shares
  in (b) use the re-implementation's own count.
- **A context (R:bracket_A; sets no threshold).**
  - swechat/claude_code: 0 of 280 streams inconsistent. Per-event Wilson hi 0.0135 over 280 streams; per-session hi
    0.0303 over 123 sessions. Consistent-stream slack U − L p5 1,119.8 / p50 2,301.0 / p95 3,893.8 ms.
  - cc_local: 0 of 187 streams (per-event Wilson hi 0.0201); slack p50 1,882.0 ms.
  - The committed Phase C lens measured a B-split p50 of 2,268.5 ms (REF:bracket_B_committed_lens). The 2 s tolerance
    is Phase D's, not tuned here.
- **Benign categories.** Each is computed per inconsistent stream by `bracket_benign_categories()`.

  | category | what it detects |
  |---|---|
  | restamped_copy | a resume/fork copy |
  | clock_step | one split makes both halves consistent (`piecewise_consistent`) |
  | concurrent_streams | — |
  | api_retry | — |
  | compaction | — |
  | user_input_binding | a queued prompt stamped at enqueue |
  | long_gap | a gap above 600 s |
  | whole_second | — |
  | vertex_or_bedrock | — |

  Phase C context: 2 of the 10 B inconsistent sessions hold re-stamped copies (REF:bracket_x_copies_swechat).
- **Control.** 5 consistent streams per inconsistent stream (same unit and split), drawn with
  `rng_for('F1ctl', unit, split)`. Enrichment = the share among the inconsistent streams minus the share among the
  controls.
- **Shared benign cause.** A category present in ≥ 0.5 of inconsistent streams, with enrichment ≥ 0.3, that the log
  itself can detect.
- **Corrections and adoption.** One correction is fixed per category:

  | category | correction |
  |---|---|
  | restamped_copy | dedupe ids (smallest session_id) |
  | clock_step | allow one skew change point |
  | concurrent_streams | abstain |
  | api_retry, compaction, user_input_binding, long_gap | drop that response |
  | whole_second, vertex_or_bedrock | 3 s tolerance |

  A correction is ADOPTED only if, on B, it lowers the honest count, keeps 30 s back-date power ≥ 0.90, and keeps 5 s
  power within 0.05 of the uncorrected detector. It is then frozen and applied unchanged on E.
- **Effective FP.** FP_eff = streams still inconsistent under the adopted corrections, divided by streams (cluster_rate),
  on E and on B. It is reported with the corrected detector's 5 s and 30 s placebo power on E.

### 1.6 Follow-up F2: the swechat latency-floor shifts (`S:followups.F2_floor_shift`)

**What the 13.5% is.** It is a share of series, not sessions: 21 of 156 eligible series (qualified read-type pairs,
n ≥ 40 per session × tool_key), W[0.090, 0.197], in 18 of 114 eligible sessions. 18 steps go up and 3 go down
(REF:floor_steps_B).

- **Replication.** The Phase B step rule on E alone, with the Phase B 0.10 label rule.
- **Covariates in a window of 5 calls either side of k*:**
  - harness events: the 15 Phase C types, copied into `S:covariate_definitions`;
  - Claude Code `version` change, read raw with `raw_cc_entries()` from public swechat transcripts;
  - cwd or gitBranch change;
  - permissionMode change;
  - an idle gap ≥ 300 s;
  - a change of ≥ 0.5 in the share of hooked calls;
  - tool-mix Jensen–Shannon distance ≥ 0.3 (20 calls each side; `js_distance`);
  - a change of ≥ 0.3 in the share of not-last-in-message calls;
  - a result-size shift of ≥ ×2;
  - a subagent in flight at the step;
  - a workspace-root change.
- **Control.** For each non-step eligible series, one random split point (`rng_for('F2', session, tool_key)`). A
  covariate is **credited** if its rate at k* exceeds its control rate by ≥ 0.25 and it appears in ≥ 3 step series.
- **Compromise signature (`compromise_signature()`).** Either leg is enough:
  - post-step Spearman(result bytes, latency) ≥ 0.5 with ≥ 20 post-step pairs while the pre-step value is ≤ 0.2;
  - post-step median r = latency / T_gen ≥ 0.1, with T_gen from the unit's G90.

  The pattern is what a switch to generation-bound results would look like.
- **Classes and outcome.**

  | class | rule |
  |---|---|
  | BENIGN | ≥ 1 credited covariate in the window |
  | COMPROMISE_LIKE | signature met, no credited covariate |
  | UNEXPLAINED | neither |

  - DISMISSIBLE_AS_BENIGN if BENIGN ≥ 0.8 of step series and COMPROMISE_LIKE = 0; otherwise OPEN.
  - COMPROMISE_LIKE series are listed individually for human review.
  - No verdict moves either way.

### 1.7 Follow-up F3: round numbers without model-chosen parameters (`S:followups.F3_round_numbers`)

**Exclusion set, fixed now (`classify_args_ints()`).**
- Every JSON-number argument.
- Every integer inside an argument string whose preceding context (≤ 48 chars, same line) matches `PARAM_CONTEXT`:
  - a CLI option argument;
  - the numeric positional of sleep / timeout / head / tail / seq / wait / ulimit / nice / kill / watch / xargs -n /
    parallel -j;
  - key=value or key: value with a parameter-like key (timeout, limit, max, count, lines, port, size, retries, batch,
    seed, offset, ...);
  - arguments of range / sleep / setTimeout / islice and similar;
  - host:port;
  - brace ranges;
  - SQL LIMIT / OFFSET.

Primary value rule: a distinct T_orig value is excluded if **any** of its occurrences is a parameter (strict). The
first-occurrence version is reported alongside.

**Statistic.** The last-0 share of the remaining distinct T_orig values against M_all, on B ∪ E and on E. The gaps g =
p(T_orig_noparam) − p(M_all) and g_full = p(T_orig) − p(M_all) are computed on the same data. In Phase B (B split) the
gap was 0.423 − 0.116 for swechat/claude_code and 0.648 − 0.121 for cc_local (REF:P4_round_B).

**Collapse, defined now (= DEAD).** Either:
- the Phase B round-number rule gives DEAD on the remaining values (DEAD unless the remaining share's point exceeds
  M_all CI hi); or
- g ≤ 0.25 × g_full.

ALIVE is kept only if the rule gives ALIVE **and** g ≥ 0.5 × g_full; otherwise WEAK. Fewer than 100 distinct values from
10 s after exclusion → INSUFFICIENT_N, with the candidate capped at WEAK ("parameter-confounded, residual untestable").

**A counts (R:f3_counts_A).** The distinct T_orig values match Phase B's A calibration exactly in every unit; they are
counts only, with no shares.

| unit | distinct T_orig values | excluded (strict) | remain |
|---|---|---|---|
| swechat/claude_code | 47 | 23 | 24 |
| cc_local | 91 | 40 | 51 |

The Phase B post-hoc split is context only (REF:P4_round_B): in swechat/claude_code, JSON-number values were 49/51 last-0
and string-embedded values 78/249.

---

## 2. New candidates N1–N5

Units with per-call stamps: swechat/claude_code, codex, opencode, gemini, cc_local, aiv_cc. aiv_cu and whowhen are
NOT_TESTABLE for N1, N3, N4 and N5g. aiv_cu stamps are shared or row-insert stamps; whowhen has no stamps.

### N1: conditional duration model (`S:n1_conditional_duration`)

- **Scope.** The shell family is primary; Codex write_stdin is excluded. auto_read is secondary.
- **Pairs.** `qualify_pairs()` applies Phase B rules 1 and 3–6, with rule 2 replaced by the scope. It requires a
  positive delta and excludes backgrounded calls. Labels:
  - swechat/claude_code and cc_local shell: "human-wait contaminated (permissionMode not in the IR)";
  - opencode and gemini shell: "permission timing unknown".
- **Key and residual.** `n1_key()` normalises the command (strips `cd X &&` chains and a trailing 2>&1, collapses
  whitespace, adds Codex workdir). `n1_residuals()` computes r_i = log10 δ_i − the median log10 δ of the group's other
  instances with the same error status.
- **Coverage first.** RR = qualified calls in a repeat group / qualified calls. It is reported before any other N1
  number.

  A feasibility counts (C:n1.repeat_coverage_counts_A), shell calls in repeat groups / qualified shell calls:

  | unit | shell | auto_read |
  |---|---|---|
  | swechat/claude_code | 509/2,812 | 195/2,046 |
  | opencode | 520/1,140 | 197/1,554 |
  | gemini | 515/800 | 240/360 |
  | codex | 137/807 | 0 qualified auto_read calls on A |
  | cc_local | 39/2,710 | 20/439 |
  | aiv_cc | 2,180/5,876 | 126/2,668 |

- **Statistic.** ρ_hon = Spearman(r_i, log10(bytes + 1)) with a session-bootstrap CI.
- **Positive control** (synthetic, existing data). One instance per group gets δ' = result chars × 0.25 / G90, using
  Phase B's A-split G90. ρ_pc = Spearman(r_i', log10(bytes + 1)) over the **tampered instances only**, one per repeat
  group, each against its group's untouched instances, with a session-bootstrap CI. The untouched instances' recomputed
  residuals are left out: in a 2-instance group they are the tampered residual negated, which would pull ρ_pc towards 0
  by construction. The natural control is the Phase B G set's Spearman.
- **Detector and threshold.** A call is flagged if r_i is outside the unit's A-split [0.5th, 99.5th] percentile bounds
  (R:n1).

  | unit | bounds | A basis |
  |---|---|---|
  | swechat/claude_code | [−2.025, 1.998] | 646 residuals, 62 s |
  | gemini | [−1.717, 1.854] | 729 residuals, 8 s |
  | opencode | [−0.708, 0.645] | 710 residuals, 10 s |
  | aiv_cc | [−0.762, 1.091] | 2,228 residuals, 27 runs |
  | codex (pooled bounds) | [−1.255, 1.568] | own A: 133 residuals, 5 s |
  | cc_local (pooled bounds) | [−1.255, 1.568] | own A: 57 residuals, 3 s |

  The pooled bounds come from 4,503 residuals in 115 sessions. They apply because codex and cc_local fall below 500
  residuals from 5 sessions.
- **Min n.** ≥ 200 residuals from ≥ 20 sessions.
- **Verdict.**

  | Verdict | Rule |
  |---|---|
  | ALIVE | ρ_hon CI within [−0.15, 0.15], ρ_pc CI lo ≥ 0.30, RR ≥ 0.10, and the call-level honest flag rate ≤ 0.02 with CI hi ≤ 0.05 |
  | WEAK | ρ_hon point within ±0.15 and ρ_pc CI lo > ρ_hon CI hi, but an ALIVE condition fails; the failing one is named |
  | DEAD | ρ_hon point > 0.15, or ρ_pc CI lo ≤ ρ_hon CI hi |

  These thresholds are judgment calls.

### N2: token accounting (`S:n2_token_accounting`)

**Granularity check first.**
- G1 = share of API responses with ≥ 1 call that carry both usage_in and usage_out.
- G2 = median per-response usage_out ≥ 20 (not a streaming partial).
- G3 = responses identifiable.
- GRANULAR iff G1 ≥ 0.9 and G2 and G3.

**Not GRANULAR ⇒ DEAD.** A values (R:n2):

| unit | GRANULAR? | A values |
|---|---|---|
| swechat/claude_code | yes | G1 1.0, median 104, τ 0.409 from 4,215 responses |
| codex | yes | G1 1.0, median 305, τ 0.492 from 546 |
| opencode | yes | G1 0.972, median 149, τ 0.368 from 1,780 |
| cc_local | yes | G1 1.0, median 926, τ 0.772 from 3,509 |
| gemini | **no** | G1 0.823 |
| copilot | **no** | G1 0.0 |
| aiv_cc | **no** | median usage_out 1.0: streaming partials |
| cursor, simple_text, whowhen | **no** | no responses with usage |
| aiv_cu pooled | **no** | G1 0.849 |

aiv_cu is therefore checked per stratum (a drafting note).

| aiv_cu stratum | GRANULAR? | τ |
|---|---|---|
| anthropic-fable | yes | 0.709 |
| anthropic-haiku | yes | 0.865 |
| anthropic-opus | yes | 0.778 |
| anthropic-sonnet | yes | 0.673 |
| gemini-flash | yes | 0.298 |
| gemini-pro | yes | 0.271 |
| anthropic-claude-code | **no** | median 1.0 |
| openai-responses | **no** | G1 0.0 |

- **Statistic.** U_k = usage_out_k − τ × (assistant text + call args + thinking chars) of response k. τ is the A-split
  median of usage_out / chars over responses with usage_out ≥ 50 and chars ≥ 200.
- **Detector.** Flag the response if its last call's result has ≥ 800 chars and U_k ≥ 0.5 τ × chars(result).
- **Positive control.** Synthetic inline fabrication: usage_out += τ' × chars(result), with τ' ∈ {τ, 0.8τ}.
- **Min n.** ≥ 100 eligible responses from ≥ 10 s.
- **Verdict.** ALIVE if the honest flag rate is ≤ 0.05 (CI hi ≤ 0.10) and recall ≥ 0.90 at 0.8τ. WEAK if ≤ 0.20 and
  recall ≥ 0.50. DEAD otherwise.
- **Stated limit.** N2 is an identity for **inline** fabrication only: text the model's decoder produces is billed as
  output. An execution-layer fake returns through the harness and is billed as input on the next call, like a real
  result. So N2 is blind to it by construction. N2 separates the two threat classes; it does not detect the second. A
  large τ (cc_local 0.772) signals hidden output, such as unlogged thinking. That is an expected honest false-positive
  source, measured, not corrected.

### N3: reaction time (`S:n3_reaction_time`)

- **Gaps (`n3_gaps()`).** Per thread: from the last result of a batch to the next model event, with no user or system
  event in between. Batch bytes are summed. Gaps ≤ 0 or > 600 s are excluded.
- **Per session.** ρ_s = Spearman(gap, bytes) for sessions with ≥ 20 gaps.
- **Pooled ρ.** Session-bootstrap CI. A secondary version subtracts the next response's usage_out / G50.
- **Detector.** Session flagged if ρ_s ≤ 0 (judgment).
- **Positive control.** Within-session permutation of gaps.
- **Min n.** ≥ 20 sessions with ≥ 20 gaps. A sessions with ≥ 20 gaps (C:latency_counts.n3):

  | unit | sessions |
  |---|---|
  | swechat/claude_code | 96 |
  | aiv_cc | 40 |
  | opencode | 12 |
  | codex | 8 |
  | gemini | 8 |
  | cc_local | 7 |

- **Verdict.** ALIVE if pooled ρ CI lo ≥ 0.30 and share(ρ_s ≤ 0) ≤ 0.10 (W hi ≤ 0.20). WEAK if CI lo > 0. DEAD
  otherwise.
- **Stated limit.** The gap includes prefill, which also scales with result size.

### N4: concurrency physics (`S:n4_concurrency`)

- **In-flight count (`inflight_counts()`).** k = 1 + the other calls of the session in flight at the pair's midpoint.
- **Statistic.** Δ = median log10 δ at k ≥ 2 minus at k = 1, within tool_key, with a count-weighted mean. Δ is computed
  for Phase B's W set and for its G set (tool-reported durations).
- **Min n.** ≥ 100 pairs at k ≥ 2 from ≥ 10 s in each set.
- **Verdict.** ALIVE if the Δ_W and Δ_G CIs are disjoint and differ by ≥ 0.10 decades. WEAK if disjoint but smaller,
  or if Δ_W ≠ 0 without a G control. DEAD if the CIs overlap.
- **Also reported.** The share of pairs at k ≥ 4 (the #67730 class).
- **Announced null (C:latency_counts.n4).** Phase B's last-call-of-message rule makes concurrency rare in qualified CC
  pairs.

  | unit | W pairs at k ≥ 2 | G pairs at k ≥ 2 |
  |---|---|---|
  | swechat/claude_code | 9, in 4 s | 79, in 21 s |
  | cc_local | 0 | 16, in 4 s |
  | aiv_cc | 0 | 32, in 2 runs |
  | opencode | 411, in 20 s | 6, in 2 s |
  | codex | 492, in 13 s | no G tool |

  N4 has no per-session rule, so every N7 cell is NA_BLIND_BY_CONSTRUCTION.

### N5: lightweight battery (`S:n5_battery`)

| Item | Definition | Min n | ALIVE / WEAK / DEAD | Positive control | A eligibility (C:n5) |
|---|---|---|---|---|---|
| a determinism | `determinism_pairs()`: same n1_key twice; read-only command (`readonly_command()`: every pipeline program read-only, git read-only subcommands, no sed -i, no find -delete/-exec/-execdir/-ok/-okdir/-fprint/-fprintf/-fls, no sort -o/--output, no redirection, no time-dependent program) or the same Read; no intervening write, non-read-only shell, subagent or user event; neither truncated nor a reference stub. Drift = differ after `mask_volatile()` | 100 pairs / 20 s | ≤ 0.05 (CI hi ≤ 0.10) / ≤ 0.20 / else | last digit edited | swechat CC 89 pairs in 27 s; cc_local 15 in 1 s; others ≤ 4 |
| b sort order | `ls_order_violation` (ls -1/-l/piped, no t/S/r/U/f/c/u/v/X/R; violation if unsorted under byte, casefold, alnum-casefold and natural order); `gitlog_order_violation` (Date lines not non-increasing; --reverse, --topo-order and --graph excluded; Date: is the author date, so rebased or cherry-picked history can violate honestly: a stated false-positive source); `grepn_order_violation` (line numbers not strictly increasing within a file block) | 100 outputs / 20 s per checker | ≤ 0.01 (CI hi ≤ 0.03) / ≤ 0.05 / else | adjacent line swap | swechat CC: ls 96 in 39 s, grep -n 388 in 55 s, git log 0 |
| c truncation boundary | Claude Code elision: prefix and suffix must equal the A constants, **5,002 / 5,002 UTF-16 units, measured raw** (all text before / after the marker, separator newlines included; n_A 30; the newline-stripped lengths are a diagnostic only, §6 note 6). Glob cap: **100** listed lines (n_A 52). Tail cut: n_A 4 < 5, so the item is NOT_RUN (R:n5.truncation_constants_pooled) | 50 / 10 s | exact ≥ 0.99 (CI lo ≥ 0.95) / ≥ 0.90 / else | re-truncate a real result at a random length | as listed |
| d whitespace | ls -l size column right-aligned; git status long-format lines start with a tab; wc counts right-aligned; pytest banners of equal length (`ws_violations`) | 100 / 20 s per check | ≤ 0.01 (CI hi ≤ 0.03) / ≤ 0.05 / else | `normalize_ws` | swechat CC: git status 75 in 47 s, ls -l 85 in 29, pytest 36 in 11; cc_local: ls -l 178 in 52, pytest 452 in 14 |
| e size distribution | IQR of log10 bytes per command family (≥ 100 results from ≥ 10 s) against the IQR of model-generated text (assistant text, subagent results) | — | capped at WEAK: ≥ 0.5 of families above the comparator's CI hi; else DEAD | — | families meeting the minimum on A: swechat CC 12, aiv_cc 6, cc_local 5 |
| f error fidelity | `error_fidelity_checks`: a Python or rustc frame in an error result whose (path, line) was shown earlier by a numbered Read, with no edit between. Infidelity = the quoted source line differs from the shown line | 100 frames / 20 s | ≤ 0.02 (CI hi ≤ 0.05) / ≤ 0.10 / else | line number + 7 | **0 checkable frames in swechat CC A (of 550 error results), 1 in cc_local**. Announced as a likely INSUFFICIENT_N |
| g cold start | c_s = log10 δ(first qualified call of the session's top tool) − median log10 δ(its later calls), ≥ 5 later calls; flag if c_s ≤ 0 | 30 s | median c CI lo ≥ log10 1.5 and share(c_s ≤ 0) ≤ 0.05 / median c CI lo > 0 / else | first call given a later call's delta | eligible sessions: swechat CC 85, aiv_cc 38, cc_local 31, opencode 25 |

N5 thresholds are judgment calls fixed now. None was derived from an A rate: no A rate was computed.

---

## 3. N6: transfer grid (`S:n6_transfer_grid`)

- **Rows.** The 22 mechanism rows of `S:n6_transfer_grid.rows`: Probes 1–4 (with 3a/3b and 4a/4b split), R1–R5, N1–N4
  and N5a–g.
- **Columns.** The 11 Phase B units, plus one per Track B corpus.
- **Cells.** ALIVE, WEAK, DEAD, INSUFFICIENT_N, INCONCLUSIVE, NOT_TESTABLE(<missing field>), NOT_RUN(<reason>).

**Fill rule.**
1. **Field gate.** A cell is NOT_TESTABLE iff a required field (`S:n6_transfer_grid.required_fields`) is absent. It is
   checked on A (R:n6_field_gate_A) and re-checked on B.
2. **Run.** Otherwise the mechanism's own verdict rule runs on B and on E. The cell shows the E verdict where E exists
   and is not INSUFFICIENT_N; otherwise the B verdict with "B only". Both are stored.
   - For Probes 1–4 on units without E, the Phase B verdict is the B run and fills the cell as "B only (Phase B run)".
   - Where E exists, Probes 1–4 are re-run on E. A cell not re-run is NOT_RUN, with the Phase B verdict shown beside it,
     never copied into it.
3. **Labels.** aiv_cc cells carry "single-agent"; cc_local cells carry "private".

**Field gate on A (R:n6_field_gate_A).** These presence facts decide most NOT_TESTABLE cells in advance:

| field | present in | absent in |
|---|---|---|
| decodable request ids | swechat/claude_code (11,047), cc_local (4,294) | every other unit (0) |
| distinct call/result stamps | every unit with pairs | aiv_cu (0 of 6,107 pairs), whowhen (0 of 353 pairs stamped), cursor (no pairs) |
| prompt IMAGE usage | aiv_cu only (1,274 rows) | — |
| GRANULAR usage | see N2 | — |
| external commit table | swechat formats | — |

**Transfer statement.** A mechanism TRANSFERS between two testable units if both cells are WEAK or better. It FAILS TO
TRANSFER if one is ALIVE and the other DEAD. Per mechanism, the grid reports testable / ALIVE / WEAK / DEAD counts and
the number of failing pairs.

---

## 4. N7: attack battery (`S:n7_attack_battery`)

- **Sessions.** Per unit and split (B and E; B only for cc_local and aiv_cc): every session with ≥ 1 eligible target,
  capped at 500 by `rng_for('N7', unit, split)`. Each session is tampered once per cell, from its untampered copy.
- **Honest FPR.** Measured on the **same sessions untampered**.
- **Donors.** Only **other real results** of the same unit and split (`pick_donor()`). Matched bytes means within 5% at
  the nearest length; the byte difference is recorded.
- **Seeds.** Target `rng_for(attack, param, session)`; donor `rng_for('donor', attack, param, session)`.

| Attack | Parameters | Injector |
|---|---|---|
| time_result_early / _late | D ∈ {0.5, 1, 2, 5, 10, 30, 60, 300} s, one result stamp. Early is clamped at call + 1 ms, and clamped draws are labelled | `atk_time` |
| time_tail_late / _early | same D grid; the result and every later event move (consistent rewrite) | `atk_time` |
| time_response_early | same D grid; a response's first event (the R1 placebo) | `atk_time` |
| time_response_late | D ∈ {5, 30, 300} (one-sidedness check) | `atk_time` |
| id_swap_adjacent | two adjacent responses' request ids swapped | `atk_id_swap` |
| id_splice_foreign | one id from another session; variants random and nearest decoded time | `atk_id_splice` |
| sub_single_flip_error | one error result replaced by a real successful same-tool result (±5% bytes) | `atk_substitute` |
| sub_single_digit | last digit of the last integer of one result changed | `atk_digit` |
| sub_matched_bytes | one result replaced by a real same-tool result (±5% bytes); variant samecmd (same n1_key) | `atk_substitute` |
| rewrite_consistent_k | k ∈ {2, 5} consecutive results replaced, each pair re-timed to its donor's latency, later events shifted | `atk_rewrite_consistent` |
| reorder_adjacent_pairs | two adjacent pairs exchange contents; stamps, ids and seq stay | `atk_reorder_pairs` |
| reorder_lines | two adjacent lines swapped in one result with ≥ 3 lines | `atk_reorder_lines` |
| delete_pair / delete_response | one pair (with nested events) / one request id's events removed | `atk_delete_pair`, `atk_delete_response` |
| insert_pair_consistent / _squeezed | a real donor pair inserted. Consistent: later events shifted by the donor's gap + latency. Squeezed: placed at 25% / 75% of the gap, skipped below 2 ms | `atk_insert_pair` |
| inline_fabrication | usage_out += τ × chars(result) | `atk_inline_fabrication` |
| image_relabel_gui / image_insert_screenshot | aiv_cu: a GUI call relabelled as shell / a donor GUI pair inserted, usage untouched | `atk_image_relabel`, `atk_insert_pair` |

**Detectors and their thresholds.**

| Detector | Decision unit and threshold | Source |
|---|---|---|
| R1_BRACKET | stream: L − U > 2,000 ms | Phase D fixed; A slack context §1.5 |
| P1_FLOOR | call: δ ≤ 0, or δ < the A floor | R:n7.floor_thresholds: Phase B A p1, or p5 / 2 where p1 is not reportable. E.g. swechat CC read 0.003 s and grep 0.00981 s (p1); cc_local read 0.0025 s (p5/2); opencode read 0.001 s (p1); aiv_cc read 0.0588 s and shell 0.0636 s (p1); codex shell_command 0.045 s (p1) |
| P1_GEN | call: r ≥ 1 | the Phase B FP definition, G90 from Phase B A |
| N1 | call: residual outside the bounds | the A bounds in §2 |
| N2 | response: the U_k rule | τ from A |
| N3 | session: ρ_s ≤ 0 | judgment |
| N5a–d, N5f | pair / output / frame: violation | rule-based; truncation constants from A |
| N5g | session: c_s ≤ 0 | judgment |
| P2_KFN | call: knowledge_from_nowhere | Phase B definition, D_unit from Phase B A |
| P3_ZERO | session: long (≥ L75) and zero errors | L75 from Phase B A (swechat CC 134) |
| R2_IMAGE | window rule | A units, §1.4 |
| R3_GIT | generator claim out of window | 2 s |
| R4_DUAL, R5_LEDGER | raw fields | NOT_RUN if not loaded |
| N4 | none | — |

**Applicability (`applicable()`, from `ATTACK_FIELDS` × `DETECTOR_FIELDS`).** A cell whose attack modifies nothing its
detector reads is NA_BLIND_BY_CONSTRUCTION. It counts as BLIND in the walk-through table, with the reason. x = run,
· = NA.

| attack | R1 | P1F | P1G | N1 | N2 | N3 | N5a | N5b | N5c | N5d | N5f | N5g | P2 | P3 | R2 | R3 | R4 | R5 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| time_* (all six) | x | x | x | x | · | x | · | · | · | · | · | x | · | · | · | x | · | · |
| id_swap_adjacent, id_splice_foreign | x | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · | · |
| sub_single_flip_error, sub_matched_bytes | · | · | x | x | x | x | x | x | x | x | x | · | x | x | · | x | x | · |
| sub_single_digit, reorder_lines | · | · | x | x | x | x | x | x | x | x | x | · | x | · | · | x | x | · |
| rewrite_consistent_k | x | x | x | x | x | x | x | x | x | x | x | x | x | x | · | x | x | · |
| reorder_adjacent_pairs | · | x | x | x | x | x | x | x | x | x | x | · | x | x | · | x | x | · |
| delete_*, insert_* | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x | x |
| inline_fabrication | · | · | · | · | x | · | · | · | · | · | · | · | · | · | x | · | · | x |
| image_relabel_gui | · | · | · | · | · | · | · | · | · | · | · | · | · | · | x | · | · | · |
| image_insert_screenshot | x | · | · | · | · | x | x | · | · | · | x | x | x | x | x | · | · | x |

**Statistics and cell label (`n7_cell_label()`).** Per unit × split × detector × attack × parameter, never pooled
across attack types:
- FPR on the untampered sessions;
- recall on the tampered sessions, with abstention counted as not flagged;
- ADR = P(flagged tampered and not flagged honest);
- localization: whether the flagged unit is the tampered one.

Recall and FPR get Wilson intervals over sessions; ADR gets the session bootstrap.

**Session flag (`S:n7_attack_battery.session_flag`).** A session counts as flagged by a detector iff at least one of
its decision units (the call, response, stream, pair, output, frame, window, claim or session of the detector table
above) is flagged. A session in which the detector decides no unit abstains. The same aggregation is used on the
untampered copy (FPR) and the tampered copy (recall). For per-call detectors this makes the session FPR grow with session
length. That cost is accepted and shows up as a higher FPR, not as a corrected one.

| Label | Rule |
|---|---|
| DETECTS | recall ≥ 0.5 and recall CI lo > FPR CI hi |
| PARTIAL | recall CI lo > FPR CI hi |
| BLIND | otherwise |
| INSUFFICIENT_N | < 30 tampered sessions |

The walk-through table lists every attack type with no DETECTS cell. No detector threshold changes after any recall is
seen.

**Injector checks.** Every injector was exercised on hand-made synthetic frames, together with the bracket, sort-order,
whitespace, error-fidelity, image, git and determinism helpers. The remaining helpers (`n3_gaps`, `inflight_counts`,
`response_table`, `cold_start_values`, `image_windows`) ran on split A inside the calibration. Every synthetic check
passed (`prereg_e_calibration.json self_tests.all_passed`). For example:
- a 30 s response back-date is caught by the bracket, and a 30 s late shift is not;
- an adjacent id swap is caught;
- a shifted traceback line is flagged as infidelity;
- whitespace normalisation breaks ls -l alignment.

These are code checks on no data.

---

## 5. Nulls announced in advance (feasibility, from A counts; not measurements)

- **N2 is DEAD by granularity** in gemini, copilot, cursor, simple_text, aiv_cc, whowhen, and the aiv_cu
  anthropic-claude-code and openai-responses strata.
- **N4 will most likely be INSUFFICIENT_N** in every Claude Code-format unit: 9 qualified W pairs at k ≥ 2 in
  swechat CC A, and 0 in cc_local and aiv_cc. It is testable at most in opencode and codex, and codex has no G control.
- **N5f error fidelity will most likely be INSUFFICIENT_N everywhere**: 0 checkable frames in swechat CC A, 1 in
  cc_local. A null of coverage, not of fidelity.
- **N5c tail-cut is NOT_RUN** (4 A instances). **N5b git log** had 0 eligible outputs in swechat CC A, so it is likely
  INSUFFICIENT_N. Where it is testable, it has a known honest false-positive source. `Date:` shows the author date,
  while git orders by commit date and parentage, so rebased, cherry-picked or amended history can violate the order
  honestly.
- **N1 codex and cc_local run on pooled bounds.** cc_local shell repeats are rare: 39 of 2,710 qualified shell calls on A.
- **F3: 24 of 47 swechat CC A T_orig values survive the strict exclusion.** If B ∪ E follows A, the residual class may
  be near the 100-value minimum. Below it, P4 round numbers are capped at WEAK, not rescued.
- **R1 runs on two units only** (decodable request ids). R2 runs on aiv_cu Gemini only.
- **E is not blind for R3, R4 and R5**, and H is not fully blind for them either (§0).

## 6. Drafting notes (`prereg_e.json drafting_notes`)

These rules were revised during drafting. Each revision was made before any B or E number existed.
1. **AC5 weights.** Computed from population metadata instead of the E allocation, which sits next to the H
   allocation.
2. **R2 units.** A per-model unit became a model unit when it has ≥ 20 positive A windows, otherwise a family unit,
   after the A window counts.
3. **N2 for aiv_cu.** Checked per stratum, after the pooled A G1 of 0.849.
4. **P1 K1 wording.** "Tool-reported durations only" became "exclude workflow and search_history". The first wording
   would have removed opencode's subagent control by construction.
5. **N1 pooled-bounds fallback.** Written before the calibration ran.

**Pre-registration audit (2026-10-04).** The following changes came from the audit, before the orchestrator's commit and
before any B or E number. The calibration was then re-run with the official command, which regenerated both
`prereg_e_calibration.json` and `prereg_e.json`.

6. **N5c raw lengths.** `truncation_info()` used to strip every newline next to the marker. That also removed newlines
   belonging to the cut text, so honest elisions came out 1–2 UTF-16 units short of the harness constant. The detector
   would have measured a parser artifact. Prefix and suffix are now measured raw, separators included. The stripped
   lengths stay in the calibration output as a diagnostic: compare `c_truncation_A.cc_chars_mid` `prefix_u16_mode`
   with `prefix_u16_stripped_mode`.
7. **N5a read-only rule.** `find` with -delete, -exec, -execdir, -ok, -okdir, -fprint, -fprintf or -fls, and `sort`
   with -o or --output, are no longer read-only. They write, and as intervening commands they would hide a real write
   between a determinism pair.
8. **N1 ρ_pc** is computed over the tampered instances only (§2).
9. **N7 session flag.** The aggregation is now stated (§4).
10. **F1/R1.** The consequence of Step 0 NOT_REPRODUCED is stated, the three stream counts are reported side by side,
    and the F1 control draw has a seed (§1.4, §1.5).
11. **R4.** The cc_local raw source is pinned to the `data/claude-code-local` snapshot (§1.4).
12. **A1 coverage.** P4 round numbers, swechat/* pooled (Phase B ALIVE), became an F3 candidate. Every other Phase B
    ALIVE or WEAK cell not in A1 is now listed (§1.2).
13. **N5b git log.** The author-date false-positive source is stated (§2, §5).
14. **Threshold provenance.** §9 was added.

## 7. Known limitations (decided now)

- **No ground truth.** Every positive in N7 is synthetic; recall is recall against our own tampering model.
- **The request-id clock layout is inferred from data.** It is UNVERIFIED against provider documentation, and a forger
  can infer it too.
- **Shell latency in swechat CC and cc_local is human-wait contaminated** for N1, because permissionMode is not in the
  IR.
- **The N2 τ absorbs hidden output.** High-τ units (cc_local) are expected to show honest false positives.
- **R4 and R5 need raw-side joins.** They are NOT_RUN if those are not built; that is not a null.
- **aiv_cc is one agent. cc_local is private and dominated by one project.** Neither has E.

## 8. Change log

Empty at commit. Any later change goes to `prereg_e.json change_log` with before, after and the reason.

## 9. Threshold provenance (added by the pre-registration audit)

Every threshold in this file has one of three sources:
- **From A**: derived on split A by `prereg_e_calibration.py`, found under `prereg_e.json resolved`, or Phase B's A-split
  values under `prereg.json resolved`.
- **Carried**: fixed earlier, by a committed pre-registration (`prereg.json`), a committed lens or a Phase D test plan
  (`ranking.json`), and reused unchanged.
- **Judgment**: a value fixed now with no data behind it.

No threshold was derived from a B or E number. The Judgment column covers numbers this file does not otherwise mark as
judgment calls.

| Item | From A | Carried | Judgment, fixed now |
|---|---|---|---|
| Global | — | CI methods; minimum n (rate: 30 events from 5 s; p1: 500 from 5 s); verdict vocabulary (`prereg.json global`) | — |
| AC1–AC5, strata | length-tercile cuts (R:length_terciles_A) | — | AC1 fails at 2 of 30; AC4 cluster share 0.25, session share 0.10, 5 largest clusters; confinement costs one level |
| P1 kill tests | floors, G90 (`prereg.json resolved.probe1`) | Probe 1 rule; G min 30 pairs from 5 s; change-point rule (p ≤ 0.01, D* ≥ log10 2, UNSTABLE above 0.10; ≥ 30 series from 5 s) | which G tools K1 keeps; K3's whole-second exclusion |
| P3 kill tests | L75 = 134 (`prereg.json resolved.probe3`) | Probe 3 rule | K1 ≥ 10 shell calls, Z > 0.10 / > 0.30; K2 Z > 0.10; K3 ≥ 20 long sessions per stratum, stratum ≥ 0.20 of long sessions, Z > 0.30 |
| P2 kill tests | D_unit (`prereg.json resolved.probe2`) | Probe 2 statistic and rule | — |
| R1–R5 verdict | — | Phase D kill rules for R1 and R2 | honest flag rate 0.05 (CI hi 0.10) / 0.20 |
| F1 / R1 | slack context only (R:bracket_A, no threshold) | 2,000 ms tolerance (Phase D); 3,000 ms tolerance for whole-second stamps and the 1-day id-offset drop (committed lens `phase_c_ids_and_clocks_in_ids.py`) | Step 0: 10 ± 3, share tolerances 0.03 and 0.01, later shifts ± 3; long_gap 600 s; 5 controls per inconsistent stream; shared cause ≥ 0.5 with enrichment ≥ 0.3; adoption needs 30 s power ≥ 0.90 and 5 s power within 0.05 |
| R2 | lattice unit per model (R:image_units_A) | session honest flag > 0.05 → DEAD (Phase D) | model unit needs ≥ 20 positive A windows; NOT_TESTABLE at ≥ 10 GUI windows without an increment; stratum split at 40 GUI windows |
| R3 | — | ±2 s window (Phase D `ranking.json` git test plan) | coverage stop at 0.005 of tool results |
| F2 | G90 for T_gen (`prereg.json resolved.probe1`) | Phase B step rule; minimum segment 20 (Phase B m), reused for the control split [20, n − 20] | window 5 calls; idle gap 300 s; hook share 0.5; JS distance 0.3 over 20 calls; parallelism 0.3; result size ×2; credited ≥ 0.25 and ≥ 3 series; signature ρ ≥ 0.5 post and ≤ 0.2 pre with ≥ 20 post pairs, or median r ≥ 0.1; DISMISSIBLE at BENIGN ≥ 0.8 |
| F3 | — | Phase B round-number rule and its min n (100 distinct values from 10 s) | 48-char context window; collapse at g ≤ 0.25 g_full; ALIVE kept only at g ≥ 0.5 g_full |
| N1 | residual bounds (R:n1); G90 for the control | unit bounds need 500 residuals from 5 s (Phase B p1 rule) | already marked as judgment in §2; min n 200 residuals from 20 s |
| N2 | τ per unit or stratum (R:n2) | — | G1 ≥ 0.9; G2 median ≥ 20; τ eligibility usage_out ≥ 50 and chars ≥ 200; result ≥ 800 chars; U ≥ 0.5 τ × chars; τ' ∈ {τ, 0.8 τ}; flag rate 0.05 (CI hi 0.10) / 0.20; recall 0.90 / 0.50; min n 100 responses from 10 s |
| N3 | — | — | ρ_s ≤ 0 (marked in §2); gaps above 600 s dropped; ≥ 20 gaps per session; ≥ 20 sessions; pooled ρ CI lo 0.30; share 0.10 (W hi 0.20) |
| N4 | — | — | ≥ 30 pairs per arm per tool_key; min n 100 pairs at k ≥ 2 from 10 s; 0.10 decades; k ≥ 4 reported |
| N5 | truncation constants (R:n5.truncation_constants_pooled) | — | everything else in the N5 table (marked in §2); an item with < 5 A instances is NOT_RUN |
| N7 | floors, G90, L75, D_unit, τ, N1 bounds, image units (from A, as above) | R1 2,000 ms; R3 ±2 s | DETECTS at recall ≥ 0.5 with recall CI lo > FPR CI hi; ≥ 30 tampered sessions; cap 500 sessions; donors within 5% bytes; time grid 0.5–300 s; k ∈ {2, 5}; squeeze at 25% / 75%, skipped below 2 ms |
