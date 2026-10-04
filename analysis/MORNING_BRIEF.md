# Morning brief: Phase E (20-minute read; code freeze 15:00 America/Chicago today)

Written 2026-10-04, about 07:55 CDT (Track C3); audited about 08:10 CDT (number trace: `trace_brief.json`; changes: `audit_log.json` entry MB1). Every number is copied from a file under `analysis/out/phase_e/` or a committed `.md` that cites one. Each section names its sources. **[I]** marks interpretation; everything else is copied.

> **Read these caveats before any number.**
> 1. **Every positive is SYNTHETIC.** No corpus contains a known real fabricated tool result. Every recall or DETECTS figure comes from the pre-registered N7 injectors applied to real honest sessions. Every honest rate is a baseline, not a detection.
> 2. **Several E splits are NOT blind.** (a) R3, R4 and R5 on swechat are "E not blind": Phase C lenses read the whole swechat population (`prereg_e.json splits.E_freshness`). (b) Every new-corpus cell for R1, P1 and N3 is NOT_BLIND, because Track B computed id-decode deltas and gap quantiles over the full acquired corpora (`n6_grid.json track_b_decisions.D6_blindness`). (c) agentcap: 42 B, 15 E and 14 H sessions were parsed into an abandoned A cache (`newcorp_split_incident_agentcap.json`). The B and E ones are excluded (`newcorp_exclusions.json`). (d) aiv_cu: B2a's id scans touched 517 rows / 270 sessions of H (`PRIOR_ART.md` §4).
> 3. **aiv_cc is one agent.** Every aiv_cc cell is a single-agent case study, B only. **cc_local** is private (aggregates only), B only and unreplicated. cc_local, aiv_cc and whowhen have no E split.
> 4. **tbench2 R1 relabel (ALIVE → WEAK, `newcorp_resolutions.json`) is applied and committed** in `n6_grid.json`, `DECISION_TABLE.md`, `TRANSFER_MATRIX.md`, `phase_e_n6.py` and `SECOND_PASS.md` §6. Authoritative counts (`n6_grid.json` `transfer.primary.totals`): ALIVE 7, WEAK 41.

## 1. What ran, what finished, what failed

| Item | Status | Key output (source) |
|---|---|---|
| A0 decision table | done | `DECISION_TABLE.md` (A0, plus the appended Phase E update) |
| A1 second pass, 25 candidate × unit rows | done | SURVIVES 9, DOWNGRADED 7, KILLED 3, NOT_RUN 6 (`second_pass.json counts`) |
| F1, F2, F3 follow-ups | done (F2's first run gave B-alone and E-alone outcomes below the global minimum n; the correction relabels both INSUFFICIENT_N, and the B∪E outcome is unchanged) | `f1_bracket.json`, `f2_floor_shift.json`, `f3_round.json` |
| N1–N5, N7 battery | done. N7 has 3,236 timing verdict cells and 1,275 content cells | `n1`–`n5_battery.json`, `n7_timing.json`, `n7_content.json` |
| Independent verification of the 12 Track A items | every re-derived cell reproduced (in `n7_timing`, the R3_GIT, N1 and codex/gemini cells were not re-derived); 2 items needed fixes (`f2_floor_shift`, `n4_n5cg`) | `track_a_workflow_result.json items[].verify`, `.fixed` |
| N6 transfer grid + traceability audit | done | `n6_grid.json`, `trace.json`, `audit_log.json` |
| Track B: B1–B3 prior art, B4 audit, B5 acquisition, B6, B7 | done. The citation skeptic re-opened 103 citations | `PRIOR_ART.md`, `CORPUS_INVENTORY.md`, `track_b/*.json` |
| New-corpus build + measurement | **6 loaded** (tbench2, agentcap, pub_cc_hf, pub_trace_commons, pub_codex, glm_tb21). **8 not loaded** (time budget): openhands_eval, tracelab-uw, cli-pi-hf, miniswe, sweagent-combo2, osworld, webarena-infinity, openhands-feedback | `newcorp_build_workflow_result.json`, `newcorp_measure_*.json` |
| C1 `DESIGN.md` | done; critic-reviewed; committed 2baebcf | `DESIGN.md` |
| C2 scaffold | **still running at audit time (about 08:05 CDT).** `scaffold_check.json` does not exist. `verifier/`, `tests/`, `eval/attacks.py`, `eval/metrics.py`, `eval/run_eval.py` and `analysis/out/phase_e/{figures,demo}/` are on disk, uncommitted and unchecked | — |

**Failed or not done (coverage gaps, not nulls):**
- 176 N6 cells (22 rows × 8 corpora) are empty because their corpora were not loaded. They are separate from the 26 loaded cells labelled NOT_RUN.
- 24 Probe 1–4 cells were never re-run on E.
- The R5 N7 leg was not computed for codex or opencode.
- R3, R4 and R5 have no blind replication.
- DESIGN open item 0 (commit the Track A JSONs) **is done**: every cited item JSON is in ed2c1d4.

## 2. Decision table (N6 grid, after the tbench2 fix)

Source: `n6_grid.json cells`, `transfer.primary.totals` (caveat 4); `DECISION_TABLE.md` Phase E update. **A** = ALIVE, W = WEAK, D = DEAD, n = INSUFFICIENT_N, – = NOT_TESTABLE (a required field is absent), nr = NOT_RUN, S = per stratum. swechat cursor, copilot and simple_text are NOT_TESTABLE on every row and are left out.

| Mechanism | sw/CC | sw/codex | sw/oc | sw/gem | cc_local | aiv_cc | aiv_cu | whowhen | tbench2 | pub_cc_hf | pub_tc | pub_codex | glm_tb21 | acap/oc | acap/pi |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R1 request-id bracket | **A** | – | – | – | W | – | – | – | W | W | n | – | – | – | – |
| N2 token accounting | W | W | W | – | W | – | S | – | W | W | n | W | W | **A** | W |
| R5 usage ledger | **A** | nr | nr | n | – | – | – | – | – | – | – | – | – | – | – |
| R4 dual-render recount | W | – | – | – | W | – | – | – | W | n | n | – | – | – | – |
| P1 latency floor | W | nr | W | nr | W | W | – | – | – | W | n | – | – | – | – |
| N1 conditional duration | **A** | n | n | n | n | **A** | – | – | W | n | n | n | – | n | n |
| P3a zero-error tail | **A** | nr | nr | nr | D | n | nr | W | – | n | n | – | – | – | – |
| P4b round numbers | W | nr | nr | nr | W | n | nr | n | **A** | n | n | n | n | n | n |
| P2 knowledge precedence | W | nr | nr | nr | D | D | nr | n | D | D | n | n | n | D | D |
| P3b retry reaction | nr | nr | nr | nr | W | D | nr | D | – | D | n | n | – | D | – |
| P4a hex uniformity | nr | nr | nr | nr | n | n | nr | n | n | n | n | n | n | n | n |
| R3 git window | W | n | n | n | – | – | – | – | – | – | – | – | – | – | – |
| R2 image ledger | – | – | – | – | – | – | D | – | – | – | – | – | – | – | – |
| N3 reaction time | D | W | D | n | n | D | – | – | W | D | n | n | n | n | W |
| N4 concurrency | W | D | W | n | D | W | – | – | – | n | n | n | – | n | – |

N5a–g: no N5 item is ALIVE anywhere. Determinism, sort order, truncation, whitespace and cold start are all DEAD in sw/CC; size (N5e) is WEAK and error fidelity (N5f) INSUFFICIENT_N there. N2 aiv_cu is a per-stratum cell, PER_STRATUM(ALIVE 3, WEAK 3, DEAD 4), and is not counted among the ALIVE cells. The deciding numbers for the 7 ALIVE cells:

| ALIVE cell | Deciding number | n | Caveat |
|---|---|---|---|
| R1, sw/CC | honest 21/7,008 streams = 0.00300 [0.00173, 0.00443]; on E, a synthetic 30 s back-date is caught in 488/500 against 3/500 honest | 7,008 streams, 3,096 s (B∪E) | E blind: a replication |
| R5, sw/CC | honest E 10/1,520 sessions = 0.0066 [0.0036, 0.0121]; synthetic delete_response 396/500 against 4/500 | 1,520 sessions (E) | **E not blind** |
| N1, sw/CC | E ρ_hon 0.031 [0.016, 0.046] against synthetic ρ_pc 0.474 [0.425, 0.527]; honest flag 0.0103 | 5,809 residuals, 498 s | shell latency includes human wait |
| N1, aiv_cc | B ρ_hon 0.039 [0.002, 0.074]; ρ_pc 0.796 | 1,901 residuals, 34 s | **one agent**, B only |
| P3a, sw/CC | E Z = 8/380 = 0.021 W[0.011, 0.041] | 380 long sessions (E) | baseline only, no positive control |
| P4b, tbench2 | last-0 share 321/653 = 0.4916 against 4,083/27,304 = 0.1495 | 653 values, 204 s | Phase B rule only, no artifact check; the F3 parameter exclusion was run as context only (still ALIVE) |
| N2, agentcap/opencode | honest 0/417 responses, CI hi 0.009128; synthetic recall 0.9736 | 417 responses, 68 s | one corpus |

**Totals.** 396 loaded cells: ALIVE 7, WEAK 41, DEAD 39, INSUFFICIENT_N 110, NOT_TESTABLE 172, NOT_RUN 26, per-stratum 1. Before the artifact checks and kill tests the same cells held **19 ALIVE**. Of 218 decided pairs, 90 transfer (the rule needs only both cells ≥ WEAK; 45 of the 90 are N2), **1 fails** (P3a: cc_local DEAD against sw/CC ALIVE) and 127 are neither. **Only 1 mechanism is ALIVE in two or more units (N1), and its second unit is the one-agent aiv_cc.** 4 of the 7 ALIVE cells are in sw/CC.
**[I]** The grid does not support "signals fail to transfer". It supports "ALIVE stays within one or two units, and most cells are undecidable".

## 3. What survived the kill attempts, what died

Source: `SECOND_PASS.md` §1, §4, §7; `second_pass.json`; `f1_bracket.json`, `f2_floor_shift.json`, `f3_round.json`.

| Outcome | Candidates (deciding number) |
|---|---|
| **Survived ALIVE** (3, all in sw/CC) | R1 bracket (replicated on blind E); R5 ledger (E not blind); P3a zero-error tail (baseline only) |
| Held at WEAK | P1 latency in all 3 units; P2 knowledge precedence; P4 round numbers (after F3); R3 git window (2/976); R4 dual render (0/2,998 honest sessions) |
| **Killed / DEAD** | R2: honest 44/807 = 0.0545 > 0.05. P4 swechat pooled: collapses without claude-opus-4-6, g 0.071 ≤ 0.075. P2 aiv_cc main (one agent): dominated. N3, N5a, N5b, N5c, N5d and N5g are DEAD in sw/CC |
| Downgraded for concentration | P1 opencode (one repo), P1 cc_local (one project), P2 opencode subagent (one repo holds 0.933), R1 cc_local (one project holds 0.9988 of streams) |

- **F1 (request-id failures).** The placebo **reproduced**: same 3,676 streams, honest count 10, 30 s back-dating 3,588/3,676 = 0.9761 against the skeptic's 0.9750. **No shared benign cause:** no category met the pre-registered rule. **FP_eff does not fall toward zero:** the adopted corrections remove 3 of 10 failures on B and **0 of 11 on E**, leaving E at 11/3,325 = 0.00331 [0.00145, 0.00551]. Post hoc, not a verdict: out-of-order result writes (B 5, E 3) and client clock behind server (B 1, E 6).
- **F2 (floor shifts): OPEN, unexplained.** B reproduces 21/156 = 0.135. On E it is 10/123 = 0.081 (STABLE); on B∪E 31/279. BENIGN 0/31 W[0, 0.110], UNEXPLAINED 28/31. The compromise signature fires at 3/31 steps but at 48/248 = 0.194 of random control splits, so it is non-specific. No verdict moves.
- **F3 (round numbers):** removing parameters leaves **less than half** the gap (g/g_full 0.464 on B∪E, 0.338 on E; keeping ALIVE needs ≥ 0.5). Not DEAD, but WEAK in sw/CC and cc_local. **The pooled row is KILLED.**
- **N7 walk-through:** **10 of 21 attack types have no DETECTS cell** in any detector, unit or split: time_response_late; sub_single_flip_error, sub_single_digit, sub_matched_bytes; rewrite_consistent_k; reorder_adjacent_pairs, reorder_lines; delete_pair; insert_pair_consistent, insert_pair_squeezed. No content detector (P2_KFN, P3_ZERO, N5a–f) reaches DETECTS against any attack; the content half's 12 DETECTS cells are R5_LEDGER, N2 and R2_IMAGE (`second_pass.json n7_walkthrough_union`; `n7_content.json label_counts`).

## 4. Prior-art verdicts (`PRIOR_ART.md` verdict table; NOVEL means "not found among roughly 300 opened sources")

| Item | Verdict | Deciding work |
|---|---|---|
| **B2 request-id bracket: method** | **PARTIAL, near-TAKEN** | Willassen 2008 Thm 2 and §2; Roughtime §8.2; Jaeger ClockSkew; email id-date checks. Do not claim the method |
| **B2: application** (provider ids as the clock for agent tool logs; single-response binding) | **NOVEL** | 0 of 25 systems use a provider id or clock to verify anything (B2c) |
| **B2 fact: is the id layout documented?** | **No, for every provider; no stability promise. MATERIAL LIMITATION** | Anthropic SDK: "format and length of IDs may change". `req_` is UUIDv7 (ms) only by inference from data. `msg_` changed format on 2026-07-06 with no release note |
| **B1(a) duration residual vs workload** | **PARTIAL** | BOINC CreditNew; van der Linden / Sinharay; DeepLog; crewAI PR #3388 (a fixed 10 ms floor, never merged) |
| **B1(b) corr(residual, output size)** | **PARTIAL (narrow)** | Early Bird §IV-D (input side); Time Will Tell. Neither the statistic nor the agent application was found |
| B3.1 token conservation; B3.2 cache-read chain; B3.4 N2 identity; B3.5 dual render; B3.6 nested timer; B3.7 N3; B3.8 N4 | PARTIAL | see table rows |
| B3.3 prompt-cache timing side channel | TAKEN (technique; no overlap with ours) | Gu et al. 2025 |
| B3.9 repeat determinism | PARTIAL, closest to TAKEN | AdvancedShelLM; ToolEmu; Elle |
| B3.10 error-message fidelity | PARTIAL; technique TAKEN; **the brief's premise is FALSE** | WOOT 2018; ToolEmu |
| B3.11 cross-harness non-transfer | PARTIAL as a claim; NOVEL as the grid | TraceProbe; FreeLog |
| R2, R3, N5 sort / truncation / whitespace / size / cold start | **UNVERIFIED** (not researched) | P2, P3 and P4 have no verdict at all (`DESIGN.md` §7.0) |

## 5. Corpus inventory: provider request-id coverage first

Source: `CORPUS_INVENTORY.md` §0–2 (`track_b/b4.json`, `corpus_inventory.json`, `corpus_skeptic.json`); new-corpus sizes from `newcorp_build_workflow_result.json`.

| Corpus (N6 name) | Public | **PROVIDER REQUEST IDS** | **Distinct ids** | In N6 grid |
|---|---|---|---|---|
| swechat / claude_code | yes, ODC-BY | **YES**: 380,855/388,605 calls = 0.980 | **305,727** (non-H) | yes |
| swechat: codex, opencode, gemini, cursor, copilot | yes | **NO** (0) | — | yes |
| cc_local | **private** | **YES**: 41,707/41,707 calls | **35,379** | yes (B only) |
| terminal-bench-2-leaderboard (tbench2; N 11,329) | Apache-2.0 | **YES, 1 of 25 submissions with logs** (WozCode, 444 sessions) | **7,272** | yes |
| cli-claude-code-hf (pub_cc_hf; N 163) | per repo | **YES, 10 of 12 repos**: 21,577/24,425 entries | **7,660** | yes |
| cli-trace-commons (pub_trace_commons; N 27) | CC BY 4.0 | **YES**: 7,496/7,499 entries | **4,349** | yes (R1 n) |
| aiv_cc, aiv_cu (gated), whowhen | gated / MIT | NO | — | yes |
| agentcap (804), glm_tb21 (86), cli-codex-hf (pub_codex, 46) | Apache-2.0 / MIT | NO (proxy- or vLLM-minted, or none) | — | yes |
| The other 8 acquired corpora | MIT, Apache-2.0, BSD-3, CC BY 4.0 | NO | — | **not loaded** |

- **5 of the 21 corpora we hold carry request ids. 4 are public. All 5 are Claude Code talking to Anthropic: one harness, one provider.** The new public ids add 19,281 distinct ids, 0.063 of swechat's. They add no harness and no provider.
- **Downloaded:** 14 corpora, 14.958 GB, leaving 10.042 GB of the 25 GB cap. **All 14 passed the field audit.** The skeptic passes OSWorld and WebArena-Infinity only weakly. One corpus exceeds the 5 GB per-corpus cap, and only because of its `.git` folder. 6 were loaded and measured; 8 were not.

## 6. The design in ten lines (`DESIGN.md` Summary, §7.0–7.3; N1 per-call rate from `n1.json`)

1. `verifier/` gives every tool call `supported`, `contradicted` or `unconstrained`, with evidence, from the log alone: no narration, no LLM, no witness.
2. Threat model: execution-path compromise is in scope. Naive record editing is measured, but separately. Full harness compromise is out of scope by definition.
3. **MUST `id_bracket` (R1).**
4. **MUST `inline_output_accounting` (N2).** It is the only shipped check whose in-scope power is not an edit artifact (DA13). That power covers inline fabrication only and is PARTIAL in sw/CC.
5. SHOULD `ledger_tally` (R5) and `dual_render_recount` (R4). COULD `latency_floor` (P1, cc_local only).
6. Cut: N1 (a population statistic; per call it flags 219/3,842 = 0.057 of synthetic tampered shell calls), P3 (no prior-art verdict), N3, N4, N5, P2, P4, R2 and R3.
7. **[I] The shipped verifier mostly detects naive record editing.** A coherent forgery passes, and every positive is synthetic.
8. Only 5 of 21 corpora carry request ids, so `id_bracket` runs on those 5. The id layout is undocumented, so a decode failure is lost coverage, never a detection (DA20).
9. Parity gate (DA15): a check is enabled only if it reproduces the Track A numbers on E exactly. The climb loop runs on E; H is read once, after the freeze.
10. Timeline: scaffold from 08:00, **G0 (human) at 09:30**, checks 09:30–13:15, enable run 13:30, freeze 15:00, H run afterwards.

| Build first | Number that justifies it | Source |
|---|---|---|
| `id_bracket` | honest E 11/3,325 = 0.00331; synthetic 30 s back-date 488/500 against 3/500 honest | `f1_bracket.json f1_effective_fp`; `n7_timing.json cells` |
| `inline_output_accounting` | the only in-scope power that is not an edit artifact: synthetic inline_fabrication 224/500 against 83/500 honest (PARTIAL). Per-response honest rate 779/46,138 = 0.0169, **but 237/1,492 = 0.159 of honest sessions are flagged** | `n7_content.json cells`; `n2.json` |
| `ledger_tally` | synthetic delete_response 396/500 against 4/500; honest 10/1,520 (E not blind; session-level). Its inline_fabrication hit, 374/500 against 4/500, is an edit artifact under DA13 (the battery leaves the session tally unrepaired) | `n7_content.json`; `r4_r5.json` |

## 7. Decisions needing a human (question → recommended default)

| # | Question | Recommended default | Source |
|---|---|---|---|
| 1 | Generate a request-id corpus (B6)? | **No for coverage**: public Claude Code JSONL already keeps `requestId`. The P0 micro-pilot (3–4.5 h) only after the freeze, and only once extra usage is off or capped at $0 (H1: `hasExtraUsageEnabled = true` is **blocking**) and the ToS/proxy question (H3) is accepted | `CORPUS_INVENTORY.md` §3 |
| 2 | Publish the normalized dataset (B7)? | **T0 only before the freeze** (coverage table, 1–2 h). T1 (7.5–12 h) vs T2 (14–21.5 h) later. The acquired corpora would add 22–44 h of loaders plus a per-corpus licence and secrets pass | `CORPUS_INVENTORY.md` §4 |
| 3 | Notify the owners of credentials found in public upstream data? Counts: TB2, **446 files** with `sk-ant-` OAuth token values; cli-pi-hf, **1 `sk-ant-api03-` value** (twice, in one file); sammshen, **1 apparent bearer token** (not downloaded) | **[I] Yes, privately.** Never print the values; scrub them from anything derived | `CORPUS_INVENTORY.md` §2.4, §6 item 8 |
| 4 | Merge `div/analysis` (`verifier/`, `eval/run_eval.py` and siblings, `analysis/lib` + loaders) to `main`? CLAUDE.md rule 3 allows `eval/` changes only by day, together, on `main` | Merge by day, after the scaffold check passes and before any overnight loop; else use the DA1 vendored fallback | `DESIGN.md` open items 1–2, 6–7 |
| 5 | Sign off the `SCOPE.md` deviations? §4 still says "Use the mirror", lists ai-village and who-and-when as "Not used", and splits by repo 80/20 | Sign the DESIGN deviations table; update `SCOPE.md` §1 and §4 | `DESIGN.md` deviations |
| 6 | Approve gated, unlicensed or oversized downloads: Exgentic + AgentBRANE + MCPHunt (3,664.7 MB); METR MALT (1.66 GB); osworld2.0 (248.5 GB, choose a subset); CooperBench coop (12.05 GB); AgentLogs (56.7 GB); licence requests; SWE-chat v2 audit | **Defer until after the freeze.** No build item depends on them | `CORPUS_INVENTORY.md` §2.3, §6 |
| 7 | Delete the duplicate `.part` file (0.154 GB) and TB2 `hf_repo/.git` (1.070 GB)? `data/` is append-only (CLAUDE.md rule 5) | Delete both, only on an explicit human yes; sha manifests cover the content | `CORPUS_INVENTORY.md` §2.4 |
| 8 | The superseded SWE-chat mirror (`data/swe-chat-mirror-cfahlgren1`, unredacted secrets) is still on disk | Keep it unread (README rule 8); a human decides whether to remove it | `analysis/README.md` |
| 9 | agentcap: 14 exposed H sessions | Drop them by the hash match at the H build | `newcorp_split_incident_agentcap.json`; `DESIGN.md` §7.5 |
| 10 | aiv_cu: H rows touched by B2a's id scans (517 rows / 270 sessions) | Accept and document; no shipped check reads aiv_cu ids | `PRIOR_ART.md` §4; `DESIGN.md` open item 16 |
| 11 | Swarm-labeled data | It must arrive through the labeled-corpus schema (`eval/labeled.py` `LabeledCall`). Report it separately, never pooled with presumed-honest FPR; the headline moves only on a human yes. Whether to use it at all is a human decision | `DESIGN.md` §3.4, §5.8 |
| 12 | Enable `inline_output_accounting` on Claude Code formats at 0.159 honest-session cost? | Yes, under DA16, with the cost printed. Saying no means the write-up must state "no in-scope power in sw/CC" | `DESIGN.md` open item 11 |
| 13 | G0: approve the check list, DA13–DA21 and the `time_tail_early` class | Approve as written | `DESIGN.md` open items 10, 12–15 |
| 14 | (done) tbench2 relabel committed; `SECOND_PASS.md` §6 counts patched to 7/41 | — | caveat 4 |
| 15 | Silent Failure "XGBoost" conflicts with `CLAUDE_context` §7 | Cite only the confirmed TF-IDF+LR AUROCs until it is reconciled | `PRIOR_ART.md` §4 |
| 16 | Other DESIGN open items with no default: add `request_id`, `api_msg_id`, `native_error`, `exit_code` to the `SCOPE.md` §3 `turn` contract (else `id_bracket` and `ledger_tally` read `missing:` on turn input); confirm the `fpr_cap` / `CLEAN_CAP` rule; confirm the SWE-chat HF gate terms allow publishing a tampered session | **[I]** Settle all three at G0. The gate-terms question blocks publishing the demo page | `DESIGN.md` open items 3, 4, 8 |
