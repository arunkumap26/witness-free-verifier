# Signal Feasibility Probe: findings

## Read this first

**Headline (measurement).** Four fabrication-detection mechanisms were pre-registered (commit 3df8d28, thresholds
from split A only), run on split B, and given mechanical verdicts. An independent re-derivation reproduced 49 of 50 unit
checks; the one miss was a wording claim, not a number (`phase_b_verification.json`).
- **Latency physics** is ALIVE in two units, swechat/opencode and cc_local, and only for read-type tools. The largest
  unit, swechat Claude Code (W from 1,042 s), is WEAK: its floor is UNSTABLE, 21/156 series. The two ALIVE units could
  not test floor stability at all (0/15 and 0/5 series, below min-n; PV probe 1 audit, item 8d), and each ALIVE unit's
  generation-bound control G comes from 12 sessions.
- **Environment pushback** (a long session with zero tool errors) is ALIVE in one unit, swechat Claude Code. Its
  zero-error tail is DEAD in cc_local and aiv_cu. The reaction-to-failure test is never ALIVE: WEAK in 4 units, DEAD
  in 4.
- **Knowledge precedence** is never ALIVE. The best cell is WEAK, at S_deep 671/4,655 = 0.144 [0.125, 0.163]. It is
  DEAD in 3 cells.
- **Hex entropy** is never ALIVE. It is WEAK in 2 of the 8 testable units and INSUFFICIENT_N in the other 6; cursor has
  no control (PV probe 4 audit, rule 7).
- Probe 4's secondary round-number test is ALIVE in swechat CC and cc_local. What it measures is not settled. In the
  distinct-value class the verdict counts, JSON-number parameters are 49 of the 127 last-0 values (51 of 300 values),
  and the string-embedded subset alone is still 78/249 = 0.313 [0.213, 0.427], above the ALIVE bar M_all hi + 0.05 =
  0.172 (PV probe 4 audit, rule 6b). The JSON does not support "mostly chosen parameters".
- **No corpus contains a known fabricated tool result.** Every verdict below describes the honest baseline. None is a
  detection rate.
- **Phase C:** 239 observations, of which a skeptic reproduced 200. They led to five proposed log-integrity witnesses,
  ranked provisionally in §4. None has a committed single-response tamper measurement of its own witness. Rank 1's
  back-date placebo comes from uncommitted code and is withheld here. Rank 5's content leg borrows token
  conservation's single-result insertion curve (TC2). Ranks 2–4 have no tamper measurement of any kind.

**Data (split B unless noted; sessions from `PREREG.md` §0).**

| Corpus | B sessions | Notes |
|---|---|---|
| SWE-chat, pinned `SALT-NLP/SWE-chat@f66cca95` raw transcripts | claude_code 1,679; opencode 214; codex 77; gemini 22; cursor 8; copilot 0; simple_text 0 | Source is `transcripts/<session_id>.jsonl`, not `conversations.parquet` (§2, A2/A3). The `cfahlgren1` mirror is excluded because it carries unredacted secrets (`README.md` rule 8; `out/recon/swechat_diffdetail.txt`). |
| cc_local (private Claude Code logs) | 186 | Aggregates only. |
| aiv_cc (AI Village Claude Agent SDK stream) | 189 runs | Effectively one agent in one SDK session. |
| aiv_cu (AI Village computer_use_turns) | 2,000 | 10 model strata. |
| Who&When | 111 (AG 78, HC 33) | |
| collusion-wiki (14,591 revisions) and urlquery (38,160 reports) | | External witnesses only (`out/recon/small.txt`, `out/recon/urlquery.txt`). |

**Caveats that apply to everything below.**
1. **Phase B is not a blind held-out test.** The Phase C discovery lenses read split B before Phase B ran. Phase B
   thresholds came only from Phase A (`PREREG.md`: "No `*_B.parquet` was opened"). Phase C numbers are in-sample on B or
   on the full population, and they confirm nothing in Phase B.
2. **aiv_cc is a single agent.** 33,473 of 33,475 A results come from one SDK session (PA R:A4-3). 156 of 189 B runs
   share an SDK session with an A run (P1 `aiv_cc_split_overlap`). Every aiv_cc number is a one-agent case study.
3. **cc_local is private.** Only aggregates appear. It is also dominated by a few sessions: in B, 6 sessions hold
   33,415 of 36,542 calls (IX sequences/S15), and 92 of 186 sessions are one glob-heavy template (IX outliers/O4).
4. **SWE-chat source.** The data is the pinned f66cca95 raw transcripts. `conversations.parquet` orphans 76,618/408,086
   = 0.1877 of distinct results and, in the full-table recon (not a split-A measurement), caps 1,552 results at 10,256
   chars. The raw transcripts have neither problem (§2).
5. **Who&When** has no timestamps (0 of 353 A pairs stamped). `is_correct` is False in every session of both splits
   (IX correlations/O14), so every task in it is a failure.
6. **collusion-wiki and urlquery** contain no agent-side tool calls. They can only witness from outside.
7. **Provenance of skeptic numbers.** Wherever a skeptic disagreed with a lens, this report uses the skeptic's corrected
   number, as the brief requires. Those numbers came from the skeptics' uncommitted scratch scripts. They survive only as
   text in the committed `out/phase_c/_index.json` and `_verification_*.json`, and they are marked **[S]**. Rule 1 is
   fully met for them only after those scripts are committed and re-run.
8. **Phase D files.** `out/phase_d/ranking.json`, its inputs `out/phase_d/inputs/ranker_{1,2,3}.json` and its script
   `analysis/probes/phase_d_ranking.py` were written but not yet committed at this revision. Three consequences:
   - Numbers marked **[D]** are Wilson intervals that script computed, treating items as independent. Each is pure
     arithmetic on the k/n printed next to it (`analysis/lib/stats.wilson` reproduces every one), but rule 1 is met only
     once the script and its output are committed.
   - The rank order in §4.3 is interpretation written in that file. This report quotes **no ranker-level vote counts**
     (how many rankers placed what where), because their only source is the uncommitted inputs.
   - **Rule-4 deviation:** `ranking.json` sits under `analysis/out/` but also stores interpretation (`why_this_rank`,
     `build_first`, `disagreements[].resolution`, `relation_to_phase_b`). Its `field_kinds` labels those fields
     INTERPRETATION, but brief rule 4 says interpretation is never written into data files. That file is not edited
     here (it is an existing output); the fields should move to `analysis/notes/` before it is committed.
9. **Novelty of every proposed mechanism is UNVERIFIED.** Prior art is checked separately. Nothing here claims a
   mechanism is new.

**Conventions.**
- k/n = rate [95% CI]. CIs are session-clustered bootstraps (`lib/stats.py`) unless marked W, which means Wilson.
- s = sessions. For aiv_cc, s means runs.
- **Rule 5 and its exceptions.** Rates are given with a CI or as a bare k/n. Numbers that carry no CI fall into these
  classes only, and each is labelled where it appears:
  - quantiles copied from a file that stores no interval for them, marked "descriptive" (a shortfall against rule 5,
    not an exemption from it);
  - null expectations, which are model outputs rather than sampled rates (E0 under independence, the uniform-digit
    expectation, the 1/60 seconds-00 expectation);
  - simulation outputs (TC2 grid crossings, TC16 simulated power, the change-point detector's simulated false-positive
    rates), marked as such;
  - test-design parameters and thresholds copied from `prereg.json`.
  Point rates, correlations and fit statistics that had no CI and no k/n in any committed file were removed in this
  revision rather than quoted.
- **Counted, not copied.** A few tallies are counts of entries in committed lists, and no file stores them as numbers:
  49 of 50 (true entries of PV `probes[*].rederive.checks[*].reproduced`); 39 (entries of `phase_a.json`
  `resolutions`); 14 lenses and 141 overclaim notes (distinct `lens` values and entries of `skeptic_overclaims` in
  `out/phase_c/_index.json`); the 65 candidate mechanisms and their split by lens (entries of `_index.json`
  `candidate_mechanisms`); the 5 proposals per proposal lens (entries of `proposals_{power,robustness,coverage}.json`
  `proposals`); each probe's deviation count (entries of its `deviations` list); and the open parser surprises per
  corpus (entries of `out/phase_a/a6.json` `part2_parser_surprises` with status `open`).
- **Arithmetic shown.** Where a number is a sum or difference of committed numbers, the inputs are printed next to it
  (for example 21 − 1 = 20 steps, or the nine rows that make up 0/6,853).
- **Interpretation** is marked as such. Everything else is copied from a file.

**Source tags.**

| Tag | File |
|---|---|
| PA:`<key>` | `analysis/out/phase_a.json` `headline.<key>` |
| R:`<id>` | `phase_a.json` `resolutions` (restated in `PHASE_A.md`) |
| PR | `analysis/PREREG.md`, `analysis/prereg.json` |
| P1–P4:`<path>` | `analysis/out/probe_{1..4}.json`, restated with paths in `analysis/notes/probe_{1..4}.md` |
| PV | `analysis/out/phase_b_verification.json` |
| IX:`<lens>/<id>` | `analysis/out/phase_c/_index.json`. The numbers are that observation's `skeptic_numbers` **[S]** unless "(lens)" is written. |
| LC:`<file>`:`<key>` | Committed lens output `analysis/out/phase_c/<file>.json` |
| PG | `analysis/out/phase_c/_proposals_grounded.json` |
| RK:`<key>` | `analysis/out/phase_d/ranking.json` (uncommitted at this revision, caveat 8) |
| A5 | `analysis/out/phase_a/a5.json` |
| verify_a`<n>` | `analysis/out/phase_a/verification/verify_a<n>.json` `measurer_summary.could_not_measure[i]` |

---

## 1. Verdict table

### 1.1 One row per mechanism

The first six rows are the pre-registered probes. Their verdict is the best unit verdict. Thresholds, units and minimum
n come from `prereg.json`. The verdicts were computed mechanically and re-derived independently (PV). The rows after
them are mechanisms that have no pre-registered Phase B verdict: token conservation (a Phase A gate label only) and the
five Phase C proposals (untested).

| Mechanism | Overall verdict (unit) | Deciding number | n (events; sessions) | Unit verdicts |
|---|---|---|---|---|
| **Probe 1. Latency physics** (fp_share and AUC, with a floor-stability downgrade) | **ALIVE**: swechat/opencode and cc_local, auto-approved read-type tools only. Floor stability untestable in both (series below min-n) | opencode: fp 7/4,419 = 0.0016 [0, 0.0033], AUC 0.999 [0.998, 1.000]. cc_local: fp 1/1,019 = 0.0010 [0, 0.0033], AUC 0.919 [0.881, 0.971] | opencode: W 4,419 pairs from 208 s, G 127 from 12 s. cc_local: W 1,019 from 112 s, G 153 from 12 s | 11 cells: ALIVE 2, WEAK 4, DEAD 0, NOT_TESTABLE 5 (P1 `verdict_cells`). The largest unit, swechat CC, is WEAK (floor UNSTABLE) |
| **Probe 2. Knowledge precedence** (S_deep; falls back to S_path_any, capped at WEAK) | **WEAK**: swechat/claude_code main thread. No cell is ALIVE | S_deep 671/4,655 = 0.144 [0.125, 0.163] | 4,655 deep first-try reads; 586 s | 22 cells: ALIVE 0, WEAK 5, DEAD 3, INCONCLUSIVE 1, INSUFFICIENT_N 9, NOT_TESTABLE 4 (P2 `n_verdict_cells`) |
| **Probe 3a. Environment pushback: zero-error tail** (primary) | **ALIVE**: swechat/claude_code | Z = 9/413 = 0.022 W[0.012, 0.041] of long sessions (≥ 134 calls) have no primary error | 194,367 paired calls in 1,649 s; 413 long sessions | 8 computed cells: ALIVE 1, WEAK 1, DEAD 2, INSUFFICIENT_N 4. Plus 3 DEAD by prereg and 1 NOT_TESTABLE |
| **Probe 3b. Reaction to failure** (secondary) | **WEAK**: swechat/claude_code, cc_local, opencode, aiv_cu | CC effect R_fail − R_ok = 0.106 [0.091, 0.121]. ALIVE needs CI lo ≥ 0.10 | CC: 7,414 failed and 182,652 ok predecessors | 8 computed cells: WEAK 4, DEAD 4. Plus 3 DEAD by prereg and 1 NOT_TESTABLE |
| **Probe 4a. Entropy: hex digit test** (primary) | **WEAK**: swechat/claude_code and aiv_cu. Never ALIVE | CC T_orig w_adj 0.110 [0.041, 0.232] against control CI hi 0.016. ALIVE needs ≥ 0.15 | CC 1,868 symbols / 161 tokens / 71 s. aiv_cu 10,997 / 1,142 / 192 s | 8 testable units (`prereg.json` `probe4.units.testable`): WEAK 2, INSUFFICIENT_N 6. cursor: control missing (INSUFFICIENT_N). Pooled: WEAK 2. NOT_TESTABLE 2 |
| **Probe 4b. Round numbers** (secondary) | **ALIVE**: swechat/claude_code and cc_local. Partly confounded with chosen parameters, extent unmeasured (§3.4) | CC T_orig last digit 0: 127/300 = 0.423 [0.334, 0.520] against machine 2,365/20,419 = 0.116 [0.110, 0.122]. String-embedded subset alone 78/249 = 0.313 [0.213, 0.427] (post hoc) | 300 distinct values from 130 s, against 20,419 from 1,141 s | 8 testable units: ALIVE 2, WEAK 1, INSUFFICIENT_N 5. cursor: control missing (INSUFFICIENT_N). Pooled: ALIVE 1, WEAK 1. NOT_TESTABLE 2 |
| Token conservation (Phase A gate `gate_rules.A5_conservation_rule`; no Phase B probe) | **TIGHT only in aiv_cc (one agent)**. LOOSE cannot carry a mechanism (§2.8) | aiv_cc ratio 0.046 [0.038, 0.054], Spearman 0.985 [0.977, 0.988]. Single-result tamper curve (TC2, Phase C): +3,000 inserted chars detected at power 0.0099 [0.0088, 0.0113] in swechat CC at realized FPR 0.0101 [0.0092, 0.0112] | aiv_cc 27,491 fit pairs, 73 runs, one SDK session (split A; PA:A5.aiv_cc.ratio, IX TC2) | TIGHT 1 (aiv_cc). LOOSE 3: swechat CC 0.742 [0.591, 0.9996] (borderline), opencode 0.470 [0.342, 0.602], gemini 0.517 [0.403, 0.600]. NOT_TIGHT: codex 2.311 [0.914, 4.409], cc_local 1.639 [1.372, 2.941], every aiv_cu stratum. INSUFFICIENT: aiv_cu haiku. No usage data: copilot, cursor, simple_text, whowhen, aiv_cu OpenAI/compat (PA:A5.*; §2.6) |
| Phase C rank 1. Request-id clock bracket | **UNTESTED, no verdict** | Honest inconsistent streams 10/3,674 = 0.00272 [0.00112, 0.00466] | 3,674 swechat CC streams | §4.3 rank 1 (IX ids/O5). Tamper response withheld (uncommitted) |
| Phase C rank 2. Image-token ledger | **UNTESTED, no verdict** | Non-GUI windows with an increment 0/6,853 (the sum of nine committed rows, shown in §4.3 rank 2), W [0, 0.00056] [D] | 11,668 aiv_cu Gemini pairs | §4.3 rank 2 (IX TC9; LC:token_conservation). No tamper measurement |
| Phase C rank 3. Git execution window | **UNTESTED, no verdict** | Out-of-window commit claims 19/3,936, W [0.00309, 0.00753] [D] | 3,936 claims | §4.3 rank 3 (IX commit_witness/O11). No tamper measurement |
| Phase C rank 4. Dual-rendering recount | **UNTESTED, no verdict** | Read numLines agreement 87,827/88,229 = 0.9954, W [0.9950, 0.9959] | 88,229 results, 4,603 files | §4.3 rank 4 (IX raw_census/A6-O1). No tamper measurement |
| Phase C rank 5. Usage-ledger reconciliation | **UNTESTED, no verdict** | Unmatched tallies after the join fix 33/5,701 = 0.0058 [0.0041, 0.0081] | 5,701 s | §4.3 rank 5 (IX swechat_tables/T3). Content leg borrows TC2 |

**Kill criteria that fired in Phase B.**
- Probe 2: DEAD in opencode main, codex main and cc_local main.
- Probe 3 zero-error tail: DEAD in cc_local and aiv_cu.
- Probe 3 reaction: DEAD in aiv_cc, codex, gemini and whowhen AG.
- Probe 1: no kill fired in any testable unit. The A1 kill rule re-fired on B for the already-dead aiv_cu, whowhen and
  cursor.
- Probe 4: no kill fired.

**What happened after the kills.** No verdict and no threshold was changed after any B number existed (P1–P4
`thresholds_used`; PV audits, rule 4). But work did not fully stop. The Phase B scripts kept producing post-hoc
description on killed cells (PV probe 2 and probe 3 audits, rule 5), which contradicts README rule 6:
- Probe 2: S_path_any without creation targets on the three DEAD cells;
- Probe 3: the aiv_cc, codex and gemini tool-stratified reaction effects and the aiv_cc R_ok without village-bash rows;
  an alternate cc_local error definition that also counts permission and interrupt flags (0/36); the aiv_cu
  shell-restricted Z and per-stratum Z.

Those numbers appear only in the blocks marked **"Post-hoc description of killed cells: not evidence"** in §3.2 and
§3.3. They do not reopen any line.

### 1.2 Probe 1 per unit (P1 `verdicts`, `units.<u>.separability`, `.floor_step_change`)

| Unit | Verdict | fp_share (W eligible, r ≥ 1) | AUC (G vs W) | Floor step label | W pairs (s) / G pairs (s) |
|---|---|---|---|---|---|
| swechat/claude_code | **WEAK** (ALIVE, then downgraded because the floor is UNSTABLE) | 72/20,937 = 0.0034 [0.0025, 0.0044] | 0.987 [0.980, 0.993] | **UNSTABLE**: 21/156 = 0.135 W[0.090, 0.197] | 20,937 (1,042) / 3,812 (903) |
| swechat/opencode | **ALIVE** | 7/4,419 = 0.0016 [0, 0.0033] | 0.999 [0.998, 1.000] | **INSUFFICIENT_N**: 0/15 series from 10 s, W hi 0.20. The JSON prints STABLE | 4,419 (208) / 127 (12) |
| cc_local | **ALIVE** | 1/1,019 = 0.0010 [0, 0.0033] | 0.919 [0.881, 0.971] | **INSUFFICIENT_N**: 0/5 series from 4 s, W hi 0.43. The JSON prints STABLE | 1,019 (112) / 153 (12) |
| aiv_cc (one agent) | **WEAK** | 241/3,217 = 0.075 [0.040, 0.119] | 0.865 [0.762, 0.922] | STABLE: 8/134 = 0.060 W[0.031, 0.113] | 3,217 (43) / 178 (25) |
| swechat/codex (small n) | **WEAK** | 270/4,329 = 0.062 [0.026, 0.118] | INSUFFICIENT_N (no G tool) | STABLE: 0/33 | 4,329 (57) / 0 |
| swechat/gemini (small n) | **WEAK** (fp ALIVE, no positive control) | 0/295; per-event W hi 0.0129 | INSUFFICIENT_N (G 13 pairs from 5 s) | **INSUFFICIENT_N**: 0/4 series from 4 s. The JSON prints STABLE | 295 (16) / 13 (5) |
| aiv_cu | NOT_TESTABLE | 59,956/59,956 pairs share one stamp, in 1,979 s | | | |
| whowhen | NOT_TESTABLE | 0 of 535 pairs carry stamps; 111 s | | | |
| swechat/cursor | NOT_TESTABLE | 0 pairs; 8 s | | | |
| swechat/copilot, swechat/simple_text | NOT_TESTABLE | 0 B sessions | | | |

**Floor-label relabelling.** `probe_1.json` labels the opencode, cc_local and gemini floors STABLE. Their series counts
are below `global.min_n.rate_reportable` (≥ 30 from ≥ 5 sessions), which prescribes INSUFFICIENT_N, and the probe did not
log this as a deviation (PV probe 1 audit, item 8d). The table relabels them. No verdict changes either way: only
UNSTABLE triggers a downgrade. What changes is the reading. The two ALIVE verdicts carry no evidence of floor
stability; they carry an absence of evidence.

**A1 kill rule re-checked on B** (P1 `units.<u>.a1_recheck_B`; all six testable units ALIVE). Whole-second stamps:
swechat CC 389/388,732; opencode 11/16,388; codex 20/19,454; gemini 8/3,552; cc_local 86/73,084; aiv_cc 0/77,476.
Identical call/result stamps: swechat CC 897/194,366; opencode 37/8,194; codex 1/9,727; gemini 9/1,776; cc_local
1/36,542; aiv_cc 0/38,738.

### 1.3 Probe 2 per cell (P2 `verdicts`; `notes/probe_2.md` §1)

The instrument check passed: swechat CC main S_symbol_ref is 1,242/46,836 = 0.027 [0.022, 0.031] over 1,274 s, against
a ceiling of 0.10.

| Unit / stratum | Verdict | Deciding statistic | k/n, s |
|---|---|---|---|
| swechat/claude_code main | **WEAK** | S_deep 0.144 [0.125, 0.163] | 671/4,655, 586 s |
| swechat/claude_code subagent | **WEAK** | S_deep 0.077 [0.062, 0.091] | 525/6,850, 296 s |
| swechat/opencode subagent | **WEAK** | S_deep 0.073 [0.020, 0.150]. Depends on a logged deviation; under the strict root rule S_deep has n = 0 and the S_path_any fallback gives 244/2,498 = 0.098 [0.084, 0.112], 176 s, also WEAK (PV probe 2 re-derivation) | 16/219, 53 s |
| swechat/codex subagent | **WEAK** | S_path_any 0.131 [0.099, 0.163] (fallback; 0 deep accesses) | 104/795, 36 s |
| aiv_cc main (one agent) | **WEAK** | S_path_any 0.192 [0.081, 0.351] (fallback; S_deep 0/1,235 from only 13 s) | 710/3,689, 53 s |
| swechat/opencode main | **DEAD** | S_path_any 0.309 [0.229, 0.394] (fallback; S_deep from 11 s) | 237/767, 36 s |
| swechat/codex main | **DEAD** | S_path_any 0.311 [0.213, 0.429] (fallback; small n) | 343/1,103, 24 s |
| cc_local main | **DEAD** | S_path_any 0.592 [0.445, 0.653] (fallback; S_deep from 17 s) | 1,669/2,820, 173 s |
| aiv_cu main | **INCONCLUSIVE** (DEAD becomes INCONCLUSIVE because antecedents are incomplete). Label: "proxy-based first-try success" | S_path_any 0.807 [0.788, 0.824] | 9,597/11,889, 1,130 s |
| swechat/gemini main | INSUFFICIENT_N | S_deep 127 from 13 s; S_path_any 302 from 19 s | |
| swechat/cursor main | INSUFFICIENT_N | No results; 38 paths from 3 s | |
| whowhen main | INSUFFICIENT_N | 0 access calls; 27 paths from 15 s | |
| cc_local subagent | INSUFFICIENT_N | S_deep 12 from 2 s; S_path_any 14,975 from 6 s | |
| aiv_cc, aiv_cu, gemini, cursor, whowhen subagent | INSUFFICIENT_N | No subagent threads with calls | |
| copilot (both strata) | NOT_TESTABLE | 0 B sessions | |
| simple_text (both strata) | NOT_TESTABLE | No tool calls (P2 `verdicts.swechat/simple_text`) | |

### 1.4 Probe 3 per unit (P3 `units.<u>.verdict`, `.zero_error_tail`, `.retry`)

| Unit | Zero-error tail | Z, n_long | Reaction | Effect [CI]; R_fail and R_ok |
|---|---|---|---|---|
| swechat/claude_code | **ALIVE** | 9/413 = 0.022 W[0.012, 0.041] | **WEAK** | 0.106 [0.091, 0.121]; 1,435/7,414 and 15,942/182,652 |
| cc_local | **DEAD** | 15/36 = 0.417 W[0.271, 0.578] | **WEAK** | 0.118 [0.038, 0.191]; 251/1,095 and 3,820/34,267 |
| aiv_cu (proxy, capped at WEAK) | **DEAD** | 678/988 = 0.686 W[0.657, 0.714] | **WEAK** | 0.034 [0.009, 0.058]; 190/1,263 and 6,632/56,714 |
| whowhen Algorithm-Generated | **WEAK**, with no excess over independence: Z/E0 = 1.23 at L75 = 3 calls (PV probe 3 re-derivation) | 7/27 = 0.259 W[0.132, 0.447] | **DEAD** | 0.099 [−0.083, 0.276]; 21/41 and 26/63 |
| aiv_cc (one agent) | INSUFFICIENT_N | 1/16 (needs ≥ 20) | **DEAD** | −0.230 [−0.343, −0.077]; 81/773 and 12,681/37,848 |
| swechat/codex | INSUFFICIENT_N | 0/11 | **DEAD** | 0.038 [−0.041, 0.183]; 119/544 and 1,649/9,122 |
| swechat/opencode | INSUFFICIENT_N | 0/7 | **WEAK** | 0.101 [0.030, 0.206]; 54/287 and 672/7,697 |
| swechat/gemini (union of two classes) | INSUFFICIENT_N | 0/1 | **DEAD** | 0.015 [−0.021, 0.077]; 11/252 and 43/1,503 |
| cursor, whowhen Hand-Crafted, simple_text | DEAD (prereg) | No results, no failure signal, or no calls | DEAD (prereg) | |
| swechat/copilot | NOT_TESTABLE | 0 B sessions | NOT_TESTABLE | |

### 1.5 Probe 4 per unit (P4 `verdict_table`, `units.<u>.verdicts`, `pooled.<cell>.verdicts`)

| Unit | Hex verdict | T_orig symbols / tokens / s; w_adj [CI] against the control's CI hi | Round-number verdict | T_orig last-0 against M_all last-0 |
|---|---|---|---|---|
| swechat/claude_code | **WEAK** | 1,868 / 161 / 71; 0.110 [0.041, 0.232] against 0.016 (M_git, 139,967 symbols, 978 s) | **ALIVE** | 127/300 = 0.423 [0.334, 0.520] (130 s) against 2,365/20,419 = 0.116 [0.110, 0.122] (1,141 s) |
| cc_local | INSUFFICIENT_N | 175 / 22 / 10 | **ALIVE** | 221/341 = 0.648 [0.435, 0.786] (14 s) against 2,243/18,550 = 0.121 [0.110, 0.130] (28 s) |
| aiv_cu | **WEAK** | 10,997 / 1,142 / 192; 0.093 [0.043, 0.216] against 0.034 (M_git, 45,281, 630 s) | **WEAK** (CI lo 0.133 is not above 0.152 + 0.05) | 740/3,866 = 0.191 [0.133, 0.293] (294 s) against 3,000/23,506 = 0.128 [0.113, 0.152] (801 s) |
| swechat/codex | INSUFFICIENT_N | 64 / 1 / 1 | INSUFFICIENT_N | 29/31 values, 13 s (needs ≥ 100) |
| swechat/opencode | INSUFFICIENT_N | 47 / 2 / 2 | INSUFFICIENT_N | 16/23, 11 s |
| swechat/gemini (small n) | INSUFFICIENT_N | 0 | INSUFFICIENT_N | 1/1 |
| swechat/cursor | INSUFFICIENT_N (no control) | 0 | INSUFFICIENT_N | 4/8, 3 s |
| aiv_cc (one agent) | INSUFFICIENT_N | 137 / 18 / 6 | INSUFFICIENT_N | 26/42, 14 s |
| whowhen | INSUFFICIENT_N | 32 / 1 / 1 | INSUFFICIENT_N | 4/9, 6 s |
| swechat/* (pooled) | WEAK | 1,972 / 163 / 73; 0.105 [0.052, 0.220] against 0.015 | ALIVE | 141/322 = 0.438 [0.353, 0.531] |
| public/* (pooled; contains aiv_cc) | WEAK | 13,131 / 1,323 / 272; 0.083 [0.046, 0.169] against 0.013 | WEAK | 844/4,148 = 0.203 [0.146, 0.298] |
| copilot, simple_text | NOT_TESTABLE | 0 B sessions | NOT_TESTABLE | |

N_min for the digit test is 1,131 symbols (PR `resolved.probe4.N_min`). The swechat redaction re-run gave the same label in
every cell, so no cap applied (P4 `verdicts.*.redaction_rerun`). Counting per `prereg.json` `probe4.units`, 8 units are
testable and cursor's control is missing, so hex is INSUFFICIENT_N in 6 of 8 testable units, not "7 of 9" (PV probe 4
audit, rule 7).

**Re-derivation differences (PV probe 4 re-derivation).** cc_local's round-number denominator is 340 in the re-derivation
against the probe's 341: the probe reads `-NNNNN` JSON numbers as NNNNN. The rate moves from 0.648 to 0.650, same label.
The two pooled cells' CIs differ slightly because the probe keys pooled sessions as `unit|sid`, which changes the seeded
bootstrap order: swechat/* hex [0.0519, 0.2205] in the probe against [0.0560, 0.2270] re-derived; public/* hex
[0.0458, 0.1693] against [0.0449, 0.1713]; public/* round [0.146, 0.298] against [0.1486, 0.2911]. No label can change.

### 1.6 Exploratory external-witness checks: NOT pre-registered, no verdict assigned

These rows are honest-baseline separations found by Phase C lenses that read split B. They are not verdicts, and nothing
in them was fixed in advance. The proposed mechanisms built on Phase C checks are in §4.3, not here.

| Check (not pre-registered / exploratory) | Corpus | Honest number | n | Status |
|---|---|---|---|---|
| A linked commit's patch contains the agent's Edit '+' lines (full match), against a cross-repo decoy | swechat CC, Entire-linked | 33,591/40,540 = 0.829 [0.812, 0.844] against decoy 55/40,540 = 0.0014 [0.0009, 0.0020]. Stronger nulls: same repo, other file, 278/39,496 = 0.007 [0.006, 0.009]; same path in earlier commits, 490/25,750 = 0.019 [0.016, 0.023]. **Honest no-match rate** (the false-positive base for this check): 5,534/40,540 = 0.137 [0.123, 0.153], repo-clustered [0.104, 0.168] | 40,540 calls, 2,689 s | IX commit_witness/O3, reproduced **[S]** |
| Write content is fully present in the committed file, against a decoy | same | 5,409/6,413 = 0.843 [0.825, 0.861] against 7/6,413 = 0.0011 [0.0003, 0.0022]. Only full matches discriminate: decoy partial matches 2,087/6,413 = 0.325 [0.302, 0.350] | 6,413 calls, 1,216 s | IX commit_witness/O6, reproduced **[S]** |
| Epochs agents print in prose, against collusion-wiki's own save time: mostly not later, with exceptions | collusion-wiki | All prose epochs: 7/582 = 0.012 [0.006, 0.025] more than 1 s after the save. Post-hoc fraction-form subset: 0/459, Wilson hi 0.0083. Non-fraction subset: 7/123 | 582 epochs, 285 pages | IX ext_witness/O10, reproduced **[S]** |
| Session narration is supported by the session's own log far more than another agent's same-time narration | aiv_cu STOP and CONS summaries | STOP paths, own log minus another agent's: paired diff +0.517 [+0.414, +0.618], 64 s. Against the stricter same-agent control c1, STOP path stays positive (CI above 0; the skeptic stores no interval, so the point value is not quoted), but **CONS url −0.002 [−0.090, +0.085]: null** | 64 s (paths) | IX aiv_narration/N4, reproduced **[S]** |
| Narration that claims an action the log shows failed | aiv_cu | 0/139 assertive STOP claims contradicted. **No power**: only 12 session-actions had all-failed evidence; 0/12 were claimed, Wilson hi 0.243 | 12 opportunities | IX aiv_narration/N6, reproduced (null) **[S]** |

---

## 2. Phase A results and what they killed

Phase A used split A only. Numbers come from `analysis/out/phase_a.json` (`headline`, `gate_rules`, `resolutions`),
restated in `analysis/PHASE_A.md`; per-corpus answers are also in `analysis/out/phase_a/_workflow_result.json`
`measured[]`. An independent verifier re-derived every question. All decisive counts reproduced except two A6 headline
fills (aiv_cc, aiv_cu), which had counted keys instead of values. 39 discrepancies were settled in `resolutions`; two of
them changed a gate label (R:A2-2 copilot; R:A4-1 text-proxy labels).

### 2.1 What Phase A killed (stated plainly)

| What died | Why (number) | Source |
|---|---|---|
| **Per-action latency in aiv_cu**, all 10 strata | Call and result share one row-insert stamp in 6,107/6,107 A pairs (199 s). Re-killed on B: 59,956/59,956 (1,979 s). Only the inter-turn gap is left: p50 14.06 s [13.26, 14.92] over 6,255 gaps | PA:A1.verdict.aiv_cu; PA:A1.aiv_cu_inter_turn_gap_s; P1 `not_testable` |
| **Any timing in Who&When** | 0 of 353 A pairs carry a stamp; 0 of 535 B pairs | PA:A1.verdict.whowhen |
| **Any timing in SWE-chat cursor**, and every claim-vs-output test there | No timestamps; 0 results for 206 calls | PA:A1.verdict.swechat_cursor; PA:A2.calls_without_result.swechat_cursor |
| **SWE-chat simple_text** | No tool pairs; 20/20 stamps are whole-second | PA:A1.verdict.swechat_simple_text |
| **`conversations.parquet` as a data source** | It orphans 76,618/408,086 = 0.1877 of distinct results; the raw pass has 16/633,366. In the full-table recon it caps 1,552 results at 10,256 chars, a cap absent from the raw transcripts (0/21,025), which hold 1,395 longer results. The 1,552 is a recon number over the whole table, carried for reference, not a split-A measurement (verify_a3 [5]) | PA:A2.table_orphan_share; PA:A3.table_cap_rows_recon (a3 `context_from_recon`, 1,552); PA:A3.swechat_cap_exact (0/21,025); PA:A3.raw_results_over_10256_chars |
| **Token conservation as a mechanism everywhere except aiv_cc** | NOT_TIGHT under the pre-registered rule: codex ratio 2.311 [0.914, 4.409] (15 s), cc_local 1.639 [1.372, 2.941] (106 s), aiv_cu Anthropic strata pooled Spearman 0.323 [0.146, 0.551] (67 s), every aiv_cu stratum NOT_TIGHT and haiku INSUFFICIENT. No usage data at all: copilot, cursor, simple_text, whowhen, aiv_cu OpenAI/compat. The LOOSE units (swechat CC 0.742 [0.591, 0.9996], borderline; opencode; gemini) pass the gate but cannot carry the mechanism (§2.8) | PA:A5.*; gate_rules.A5_conservation_rule |
| **A text-proxy error definition in gemini and copilot** | Absent: gemini A proxy P 0/280, R 0/143 | PA:A4.A.swechat_gemini |
| **A validated error flag in aiv_cu** | No flag exists. A stderr proxy fires on 118/6,107 = 0.019 [0.013, 0.026] and is unvalidated | PA:A4.aiv_cu_stderr_proxy |
| **copilot as a unit** | 2 A sessions; per-call Wilson hi 0.021 > 0.01 (R:A2-2); 0 B sessions | R:A2-2 |
| **The A3 marker catalogue as a truncation detector for cc_local Glob** (not text-only detection) | The 186 flag-true Glob results carry no catalogue marker. A post-hoc text shape ("101 lines, last line starts with `(`") separates them, 186/186 against 0/241, so text can detect them; the catalogue cannot | R:A3-6 |

### 2.2 A1. Timestamp granularity (the latency gate)

The kill rule (`gate_rules.A1_latency_kill_rule`): KILLED if no pair has both stamps, if more than 0.5 of stamps are
whole-second, or if more than 0.5 of pairs share one stamp.

| Corpus | Verdict | Deciding number | n |
|---|---|---|---|
| swechat/claude_code | ALIVE | Identical stamps 37/13,589 = 0.27% [0.13, 0.48]; whole-second 26/27,178 = 0.096% [0.062, 0.131]; delta p50 0.101 s [0.069, 0.142] | 126 s |
| swechat/codex | ALIVE (small n) | 0/1,120 identical | 15 s |
| swechat/opencode | ALIVE (small n) | 14/3,735 = 0.37% [0.07, 0.72] identical | 25 s |
| swechat/gemini | ALIVE (small n) | 0/2,313 identical; 6 negative deltas, because the call stamp is the message stamp | 10 s |
| swechat/copilot | ALIVE by rule only | 0/265 | 2 s |
| cc_local | ALIVE | 0/5,164 identical; whole-second 6/10,328 = 0.058% [0.023, 0.116]; p50 0.247 s [0.102, 0.351] | 107 s |
| aiv_cc | ALIVE (one agent) | 0/33,475 identical; 0/66,950 whole-second; every delta ≥ 0.046 s (a floor whose cause was not measured, R:A1-6) | 77 runs |
| aiv_cu | **KILLED** | 6,107/6,107 shared stamps | 199 s |
| whowhen | **KILLED** | 0/353 stamped | |
| swechat/cursor | **KILLED** | 0 stamped pairs | |
| swechat/simple_text | **KILLED** | 0 pairs | |

Human waits (corrected): permission-prompt rejections occur in 19/126 swechat CC s = 15.1% W[9.9, 22.4], p50 23.0 s
(R:A1-1). swechat CC Edit/Write calls over 2 s: 296/2,235 = 13.2% [6.8, 21.7]. Shell pre-exec offset over 2 s:
50/367 = 13.6% [5.8, 25.9] (R:A1-3). cc_local permission denials are machine-fast: 173 of them, p50 0.007 s
(R:A1-2). **Consequence:** shell, edit, write and web latencies in the Claude Code formats were excluded from Probe 1.

Two further resolutions that did not change a gate:
- **R:A1-5, aiv_cc non-last blocks.** The claim that this SDK "does not stream" holds only for one session's Write:
  160 non-last Write calls, all in 1 session, p50 15.65 s against 0.091 s for last-block Writes, 0/160 results before
  the last block's stamp. For other tools, non-last results often arrive before the last block (grep 41/41, read 45/68,
  get_events 502/993). The "last or only block" filter is kept as a precaution, not as an SDK property.
- **R:A1-7, OpenCode last-digit uniformity.** OpenCode alone fails it: chi2 p 0.039 on 8,298 distinct stamps (digit 5:
  919 against a mean of 829.8). The kill rule does not use digit uniformity, so the verdict is unchanged.

### 2.3 A2. Join completeness on (session_id, call_id)

| Corpus | Answer | Deciding number |
|---|---|---|
| swechat/claude_code | usable | 31/13,620 = 0.0023 [0.0013, 0.0036] calls without a result; but 20/127 s W[0.104, 0.231] have at least one |
| swechat/codex | usable | 2/1,122 |
| swechat/opencode | usable | 0/3,735 (Wilson hi 0.0010) |
| swechat/gemini | partial; usable once 1 session is excluded | 487/2,800, all from one session with no results; 0/2,313 elsewhere |
| swechat/copilot | insufficient n (R:A2-2) | 1/266 in 2 s |
| swechat/cursor | absent | 206/206 (the format records no results) |
| cc_local | usable | 1/5,165 |
| aiv_cc | usable | 4/33,479 |
| aiv_cu | untestable: the loader builds every pair (R:A2-5) | 0/6,107 by construction; 3,393/6,107 = 0.556 [0.502, 0.610] of results have no text |
| whowhen | partial | 20/373 = 0.054 [0.030, 0.082]; excluding never-executed AG code, 8/361 = 0.022 [0.007, 0.035] |

**A null hidden by zero counts:** one salvaged, truncated OpenCode document in split A has 185 IR calls against 417
table rows. All 162 missing table ids come from it, and the join metrics cannot see this loss (R:A2-4).

**Zero-count "usable" verdicts rest on a degenerate bootstrap (R:A2-3).** For a zero count, the session-clustered
bootstrap returns [0, 0], so the rule's upper bound does not bound the rate. Re-applied with per-call Wilson upper
bounds, only copilot changes (R:A2-2): opencode 0/3,735 (Wilson hi 0.0010), aiv_cu 0/6,107 (0.0006), cc_local 1/5,165
(0.0011), aiv_cc 4/33,479 (0.0003), codex 2/1,122 (0.0065) and swechat CC 31/13,620 (0.0032) stay usable. The share of
sessions affected has session-level Wilson bounds up to 0.133 (for 0/25), which the rule does not use.

### 2.4 A3. Truncation of tool-result text

| Corpus | Any loss-type marker | Notes |
|---|---|---|
| swechat/claude_code | 134/13,592 = 0.99% [0.76, 1.22] (55/126 s) | Persisted-output spills show a 1,833–2,282-char preview: 65 results in 36/126 s. Error truncation keeps `Exit code N` in 15/15 (10 s); untruncated baseline 233/285 = 0.82 [0.73, 0.88] (R:A3-2) |
| swechat/codex | 11/1,120 = 0.98% [0.31, 2.02] | |
| swechat/opencode | 40/3,735 = 1.07% [0.68, 1.64] | |
| swechat/gemini (Gemini CLI) | `<tool_output_masked>` 840/2,313 = 36.3% [25.2, 43.2] (7/10 s; R:A3-1) | Gemini writes `Exit Code:` only for nonzero exits (0 of 816 show `Exit Code: 0`), so masking's effect on errors cannot be tested (R:A3-3) |
| cc_local | 23/5,164 = 0.45% [0.19, 0.95] in text; 209/5,164 = 4.05% [2.02, 10.03] with the Glob flag | Glob flag absent on 34 of 44 text-marked swechat truncations (R:A3-4) |
| aiv_cc | 40/33,475 = 0.12% [0.04, 0.28] (11/77) | Includes an older spill format the catalogue missed (R:A3-5) |
| aiv_cu | 0/6,107 (Wilson session hi 1.9%) | Unmarked caps are not excluded |
| whowhen | 0/353 (Wilson session hi 5.7%) | Same |

### 2.5 A4. Error-signal survival (definitions used by Probes 2 and 3)

| Corpus | Answer | Deciding number |
|---|---|---|
| swechat/claude_code | Native flag usable; null means "not flagged" | Native filled 4,464/13,592 = 0.328 [0.285, 0.370]; text proxy A: P 488/488 (W lo 0.992), R 488/614 = 0.795 [0.720, 0.855], 90 s |
| cc_local | usable | A: P 331/331, R 331/349 = 0.948 [0.900, 0.977], 74 s; 157 of 311 native-true shell results are permission denials |
| aiv_cc | usable (proxy B) | A: R 296/538 = 0.550 [0.342, 0.791]. B: P 534/637 = 0.838 [0.736, 0.897], R 534/538 = 0.993 [0.977, 0.999], 38 runs. 1,746 village-bash JSON turns carry no native flag |
| swechat/codex | usable, small n | Exit header alone: P 47/47, R 47/49 = 0.959 [0.823, 1.0]; positives from 6 s (R:A4-2) |
| swechat/opencode | native only | Native filled 3,735/3,735; text proxy reaches 26/157 = 0.166 [0.096, 0.253] of shell failures |
| swechat/gemini | partial | A: P 0/280, R 0/143; native status and the text exit code never coincide |
| swechat/copilot | partial | 8 native positives in 2 s |
| aiv_cu | **absent** | stderr proxy 118/6,107 = 0.019 [0.013, 0.026], unvalidated |
| whowhen | partial | Exit code on 87/353 (36 nonzero); 36/36 agreement is tautological |

### 2.6 A5. Token accounting and conservation

**No field counts tool-result tokens separately in any corpus.** Gemini CLI `tokens.tool` is nonzero in 0/2,505
(PA:A5.gemini_cli_tokens_tool). The one exception is Gemini computer-use screenshots: IMAGE tokens rise in 417/420 (pro)
and 191/191 (flash) gaps containing a GUI result, and in 0/309 (pro) and 0/320 (flash) gaps without one (A5
`part2.aiv_cu/gemini-*.gemini_modality.gap_has_gui_result` and `.gap_has_no_gui_result`).

| Corpus | Rule label (`gate_rules.A5_conservation_rule`) | Deciding number |
|---|---|---|
| aiv_cc | **TIGHT** (one agent: all 27,491 fit pairs come from one SDK session, R:A5-3) | Spearman 0.985 [0.977, 0.988]; median \|residual\| 66.1 tokens against a 1,447.7-token typical result, ratio 0.046 [0.038, 0.054]. Images cost 913.7 tokens [904.2, 916.7] each |
| swechat/claude_code | LOOSE (borderline, R:A5-4) | Ratio 0.742 [0.591, 0.9996]; Spearman 0.915 [0.897, 0.931] |
| swechat/opencode | LOOSE; the result-only form meets the TIGHT thresholds (post hoc) | Ratio 0.470 [0.342, 0.602]; result-only Spearman 0.951 [0.934, 0.970], 19.3 tokens = 0.102 [0.070, 0.135] |
| swechat/gemini (Gemini CLI) | LOOSE, also at the random-split median (R:A5-1) | Ratio 0.517 [0.403, 0.600]; Spearman 0.820 [0.778, 0.865] |
| swechat/codex | **NOT_TIGHT** | Ratio 2.311 [0.914, 4.409], 15 s; the CI reaches the LOOSE range. Post-hoc description of a killed cell, not evidence: a form subtracting all output tokens gives 0.334 [0.139, 0.658] (R:A5-2) |
| cc_local | **NOT_TIGHT** | Ratio 1.639 [1.372, 2.941], 106 s |
| aiv_cu strata | **NOT_TIGHT** (haiku INSUFFICIENT: 188 fit pairs, 12 s) | Anthropic strata pooled: Spearman 0.323 [0.146, 0.551], ratio 20.2 [11.9, 40.1], 67 s. gemini-pro: Spearman 0.521 [0.380, 0.660], 19 s. gemini-flash: 0.517 [0.395, 0.644], 17 s |
| copilot, cursor, simple_text, whowhen, aiv_cu OpenAI/compat | no usage data | |

Every compaction-marked pair is dropped: 33/33 in swechat CC, 429/429 in aiv_cc. Unmarked drops are the false-positive
class: 67/10,744 swechat CC, 150/3,384 opencode, 87/2,487 Gemini CLI.

### 2.7 A6. Fields the IR does not carry, and parser surprises

- **Census.** 2,083 entries: 642 uncaptured, 924 not in the IR. 435 harness-measured candidates have key fill ≥ 0.3,
  of which 7 are majority-null by value (R:A6-1).
- **Strongest missing redundancy** (Claude Code `toolUseResult`): Read numLines 2,514/2,561 = 0.982 (top-level only,
  R:A6-2); Edit structuredPatch 1,958/2,029 = 0.965; Stop-hook durations 792/951 = 0.833. No loader reads them, as far
  as a string-literal match on `analysis/loaders/*.py` can tell (verify_a6_raw_census [3]; the caches were not read), so
  using them needs a loader change, decided by day.
- **Parser surprises:** 80 in total. 47 are open, 28 handled by the loader and 5 resolved (PA:A6.parser_surprises; list
  in `out/phase_a/a6.json` `part2_parser_surprises`). No build or review report has a parser-surprise field, so this
  list is a hand-selected compilation; its values are read from the reports, but the selection is judgement
  (verify_a6 [6]). The open ones are itemized in §5.8.

### 2.8 Consequences carried into Phase B (Interpretation, from `PHASE_A.md`)

- Probe 1 ran on swechat CC, cc_local and aiv_cc, with codex, opencode and gemini as small-n units, and with human-wait
  filters.
- Probe 3 used the native flag where it is filled and kept the marker classes apart.
- Token conservation can carry a mechanism only in aiv_cc (one agent) and in OpenCode's result-only form.
- Claim-vs-output checks must be gated on truncation.
- Use the raw IR, never `conversations.parquet`.
- Phase C findings on B do not count as held-out confirmation.

---

## 3. Per-probe findings, with distributions

**Common facts for all four probes.**
- **Pre-registration integrity.** Every probe checked that the sha256 of `prereg_common.py` equals `prereg.json
  provenance.spec_module_sha256` before it ran. The audit confirmed the prereg files are unchanged since 3df8d28 (PV
  audits, rule 1).
- **Re-derivation.** An independent re-derivation from the prereg text reproduced every verdict and deciding number in
  all four probes: 49 of 50 unit checks. The only miss was a summary sentence about Probe 1's W-set Spearman (PV
  `probes[0].rederive`).
- **Audits.** All four compliance audits found minor issues only, with no blocking violation and no fix round.
- **Distributions not reproduced below** are in the probe JSONs at these paths: Probe 1 per-tool floors and histograms
  (`units.<u>.qualified_by_tool.<tool>.log_histogram_s`); Probe 2 depth histograms (`units.<u>.strata.<s>.deep_first_try.depth_hist`)
  and per-tool sourcing (`classes.<class>.sourced_by`); Probe 3 per-tool error classes (`units.<u>.per_tool_key`),
  all-session and ≥ 20-call per-session error rates (`per_session_error_rate.all_sessions`, `.sessions_ge_20_calls`) and
  position deciles (`early_late.<class>.by_position_decile`); Probe 4 large-integer counts per result
  (`census.large_ints_per_result`) and per-tool hex in calls (`census.calls_by_tool`).

### 3.1 Probe 1: latency physics

**Measurement.** Auto-approved read-type tools return their results orders of magnitude faster than a model could
generate the same text (median log10 r −2.44 to −3.53 in the three CLI units below). Two exceptions run the other way:
harness floors near 50 ms in aiv_cc and Gemini, and shell commands, which reach r ≥ 1 in aiv_cc 241/2,785 and codex
shell_command 183/1,227 eligible W pairs. Whether those shell pairs are honest cannot be checked: no corpus has ground
truth.

**Honest floor: qualified auto_read latency, in seconds** (P1 `units.<u>.qualified_by_class_dist.auto_read`). p1, p5,
p10, p50 and p95 carry session-clustered CIs. p99 is descriptive, with no CI.

| Unit | n (s) | p1 | p5 | p10 | p50 | p95 | p99 |
|---|---|---|---|---|---|---|---|
| swechat/claude_code | 26,639 (1,103) | 0.002 [0.002, 0.002] | 0.004 [0.003, 0.004] | 0.006 [0.006, 0.007] | 0.035 [0.03, 0.045] | 0.686 [0.63, 0.737] | 1.937 |
| swechat/opencode | 5,113 (209) | 0.001 [0.001, 0.001] | 0.002 [0.002, 0.002] | 0.002 [0.002, 0.002] | 0.006 [0.006, 0.007] | 0.026 [0.024, 0.028] | 0.05388 |
| cc_local | 1,817 (115) | 0.004 [0.003, 0.005] | 0.005 [0.004, 0.007] | 0.006 [0.005, 0.009] | 0.014 [0.008, 0.038] | 0.3062 [0.186, 0.5751] | 1.21 |
| aiv_cc (one agent) | 3,024 (47) | 0.05647 [0.0532, 0.0604] | 0.06573 [0.06081, 0.07409] | 0.07449 [0.06624, 0.08731] | 0.1345 [0.115, 0.1884] | 0.7185 [0.3572, 1.253] | 1.863 |
| aiv_cc shell (one agent) | 3,913 (47) | 0.06492 [0.06252, 0.07255] | 0.08378 [0.07413, 0.1012] | 0.1131 [0.091, 0.2302] | 0.6141 [0.4139, 0.9228] | 4.829 [2.648, 30.33] | 90.94 |
| swechat/gemini | 321 (16) | INSUFFICIENT_N | 0.054 [0.01385, 0.05955] | 0.058 [0.0539, 0.077] | 0.095 [0.069, 0.113] | 0.189 [0.1183, 0.2004] | INSUFFICIENT_N |

**Histogram of qualified auto_read latency** (P1 `...auto_read.log_histogram_s`). Counts are per quarter-decade bin,
starting at the stated lower edge; each bin is ×1.778 wide.
- swechat CC, from 0.001 s: 189, 974, 1,102, 2,663, 3,892, 3,858, 2,407, 2,334, 1,698, 3,192, 2,270, 1,444, 336, 105,
  51, 45, 21, 26, 8, 8, 8, 4, 2, 2. Zero or negative: 229.
- opencode, from 0.001 s: 112, 1,211, 927, 1,087, 974, 662, 91, 12, 3, 16, 1, 4, 0, 0, 4, 0, 0, 2, 2, 0, 3, 1, 0, 1.
  Zero or negative: 24.
- cc_local, from 0.001778 s: 12, 120, 615, 227, 107, 403, 24, 154, 66, 49, 3, 31, 2, 1, 0, 0, 3.
- aiv_cc, from 0.03162 s: 28, 763, 1,112, 506, 402, 143, 35, 20, 12, 2, 1. The auto_read minimum is 0.0497 s; the
  lowest minimum of any aiv_cc tool is 0.0476 s, for computer_use (`notes/probe_1.md` §8).
- gemini, from 0.001778 s: 2, 2, 1, 3, 0, 18, 147, 122, 25, 1. Zero or negative: 4.

**Other qualified classes** (P1 `qualified_by_class_dist`; p5 / p50 / p95 with CIs):
- internal_noperm: swechat CC 0.001 [0.001, 0.001] / 0.006 [0.005, 0.011] / 0.146 [0.07499, 0.5535] (5,340; 568 s);
  cc_local 0.003 [0.003, 0.005] / 0.006 [0.005, 0.006] / 0.012 [0.0091, 0.0498] (162; 41 s); codex 0.00445 [0.004,
  0.008] / 0.0235 [0.019, 0.0285] / 0.2155 [0.1541, 2.093] (170; 33 s); aiv_cc 0.05573 [0.0546, 0.05861] / 0.0758
  [0.07142, 0.09243] / 0.6144 [0.2942, 1.641] (184; 22 runs).
- other: codex 0.0957 [0.038, 0.158] / 0.758 [0.4519, 0.826] / 6.915 [2.099, 10.97] (6,348; 60 s); aiv_cc 0.1731
  [0.1585, 0.2006] / 0.417 [0.3832, 0.5075] / 7.152 [5.76, 13.29] (27,707; 115 runs).
- **The harness floor differs by tool within one scaffold.** codex exec_command p1 is 0.267 [0.254, 0.316] s (3,502
  pairs, 34 s) against shell_command p1 0.0503 [0.0404, 0.149] s (1,631 pairs, 22 s) (P1
  `units.swechat/codex.qualified_by_tool`). A floor learned on one tool does not transfer to the other.

**Separability: r = latency / T_gen on eligible W pairs** (P1 `separability.W_log10_r`, `W_r_quantiles`,
`W_r_log_histogram`). r ≥ 1 is a false positive. The log10 r quantiles carry CIs; the r quantiles are descriptive.

| Unit | log10 r p5 | log10 r p50 | log10 r p95 | r p99 (descriptive) | r max |
|---|---|---|---|---|---|
| swechat CC (20,937; 1,042 s) | −3.72 [−3.77, −3.68] | −2.44 [−2.52, −2.36] | −0.88 [−0.96, −0.80] | 0.449 | 96.6 |
| opencode (4,419; 208 s) | −4.57 [−4.65, −4.50] | −3.53 [−3.61, −3.45] | −2.13 [−2.20, −2.10] | 0.0157 | 77.2 |
| cc_local (1,019; 112 s) | −3.97 [−4.04, −3.60] | −2.76 [−2.94, −2.54] | −1.46 [−1.59, −1.23] | 0.137 | 2.45 |
| aiv_cc (3,217; 43 runs) | −2.43 [−2.59, −2.28] | −0.81 [−0.94, −0.63] | 0.096 [−0.068, 0.331] | 17.4 | 61.7 |
| codex (4,329; 57 s) | −2.24 [−2.43, −2.07] | −1.20 [−1.31, −1.11] | 0.113 [−0.155, 0.389] | 3.85 | 25.0 |
| gemini (295; 16 s) | −2.37 [−2.53, −1.97] | −1.38 [−1.87, −1.29] | −1.08 [−1.33, −0.96] | 0.123 | 0.249 |

W r histograms are quarter-decade counts.
- swechat CC, from r = 1e-5: 6, 25, 89, 251, 582, 1,068, 1,585, 1,985, 2,147, 2,231, 2,311, 2,160, 1,759, 1,391, 1,142,
  851, 596, 384, 223, 79, 35, 15, 10, 3, 4, 1, 2, 2. The bins from r = 1 up are the last eight.
- aiv_cc, from r = 0.0003162: 2, 18, 41, 66, 109, 155, 130, 143, 211, 315, 563, 479, 392, 352, 138, 23, 12, 10, 32, 7,
  12, 7.
- **opencode (ALIVE)**, from r = 5.623e-06: 11, 100, 179, 331, 476, 601, 567, 550, 518, 354, 259, 161, 176, 101, 20, 3,
  1, 2, 0, 1, 1, 1, 2, 0, 0, 1, 1, 1, 1. The last eight bins (r from 1 up to 100) hold the 7 false positives.
- **cc_local (ALIVE)**, from r = 5.623e-05: 46, 85, 77, 56, 94, 159, 188, 59, 50, 78, 64, 34, 17, 4, 5, 2, 0, 0, 1. The
  last bin (r from 1.778 to 3.162) holds the 1 false positive.
- codex, from r = 3.162e-05: 1, 0, 2, 5, 3, 9, 19, 51, 118, 236, 355, 550, 689, 624, 504, 366, 318, 209, 97, 116, 38,
  12, 5, 2. The bins from r = 1 up are the last six.
- gemini, from r = 0.001778: 7, 18, 19, 34, 33, 116, 61, 6, 1 (maximum r 0.249).

**G (generation-bound control): distribution of log10 r** (P1 `separability.G_log10_r`, `G_r_log_histogram`).

| Unit | G pairs (s) | log10 r p5 | log10 r p50 | log10 r p95 |
|---|---|---|---|---|
| swechat CC | 3,812 (903) | −0.753 [−0.995, −0.493] | 0.354 [0.318, 0.393] | 1.67 [1.6, 1.75] |
| opencode | 127 (12) | −1.23 [−1.56, 1.01] | 1.30 [1.12, 1.41] | 1.63 [1.45, 1.66] |
| cc_local | 153 (12) | −2.31 [−2.36, −2.00] | −0.099 [−1.96, −0.018] | 0.243 [0.211, 0.300] |
| aiv_cc (one agent) | 178 (25 runs) | −0.342 [−0.410, −0.329] | −0.142 [−0.253, −0.106] | 0.277 [0.0453, 0.317] |
| gemini | 13 (5) | INSUFFICIENT_N | INSUFFICIENT_N | INSUFFICIENT_N |

G r histograms, quarter-decade counts:
- swechat CC, from r = 0.0003162: 5, 8, 9, 2, 11, 9, 11, 11, 18, 48, 59, 80, 113, 381, 764, 849, 445, 231, 218, 198,
  197, 81, 28, 21, 7, 5, 1, 1, 0, 0, 1.
- opencode, from r = 0.01778: 2, 5, 1, 1, 2, 0, 0, 0, 2, 1, 5, 29, 60, 18, 1.
- **cc_local, from r = 0.001778: 1, 13, 29, 8, 3, 2, 0, 1, 0, 1, 46, 43, 6. This control is bimodal.** The first four
  bins (r below 0.0178) hold 1 + 13 + 29 + 8 = 51 of its 153 pairs. Its p50 CI spans [−1.96, −0.018], and the
  re-derivation notes that the 53 workflow and subagent pairs are not generation-bound in practice (PV probe 1
  re-derivation, cc_local). The cc_local ALIVE AUC of 0.919 [0.881, 0.971] rests on this control.
- aiv_cc, from r = 0.01778: 1, 0, 0, 0, 0, 47, 87, 32, 10, 1.
- gemini, from r = 0.5623: 3, 4, 1, 1, 3, 1.

Medians of G r by tool, for n ≥ 30 only; descriptive, no CI (P1 `separability.G_eligible_by_tool`):
- CC subagent 2.62 (2,863/3,319 have r ≥ 1), CC webfetch 0.976 (151/335), CC websearch 0.676 (33/158).
- opencode subagent 22.1 (116/116).
- cc_local webfetch 1.39 (43/47), websearch 0.855 (6/53), workflow 0.0069 (0/47).
- aiv_cc search_history 0.720 (42/160).

**Where honest W pairs reach r ≥ 1** (P1 `W_eligible_r_ge_1_by_tool`):
- swechat CC: glob 27/873, grep 25/3,799, read 20/16,265.
- aiv_cc: shell 241/2,785, and 0 for read (325), grep (87) and glob (17).
- codex: shell_command 183/1,227 and exec_command 87/2,927.
- opencode: read 6/3,658 and glob 1/119.

**Result size against latency** (Spearman ρ, `notes/probe_1.md` §4).
- In G, ρ is positive: swechat CC 0.496 [0.421, 0.570], cc_local 0.695 [0.533, 0.805], aiv_cc 0.751 [0.644, 0.940].
- In W it is mostly not positive: swechat CC −0.013 [−0.051, 0.023]. **Audit correction:** cc_local W is +0.164
  [0.076, 0.292], with a CI that excludes 0. The notes' line "flat or negative in W" overgeneralizes (PV probe 1 audit,
  item 7b).

**Floor stability** (P1 `floor_step_change`).
- swechat CC is UNSTABLE: 21 steps in 156 eligible series = 0.135 W[0.090, 0.197], in 18 sessions. 18 steps go up and
  3 go down. The median step factor is 3.39 and the largest 35.4 (descriptive). Read 16/110, grep 3/38.
- Without the one step at the p boundary, the count is 21 − 1 = 20 steps in 156 series, 20/156
  (`sensitivity_steps_at_p_boundary`), still UNSTABLE.
- aiv_cc: 8/134 = 0.060 W[0.031, 0.113]. All 8 steps are in runs of one SDK session.
- opencode 0/15 (10 s), cc_local 0/5 (4 s) and gemini 0/4 (4 s) are below the rate minimum, so their label is
  INSUFFICIENT_N, not STABLE (§1.2). codex 0/33.
- **Floor transfer** A p5 → B: swechat CC read has FLOOR_SHIFT, with 2,153/17,543 = 0.123 [0.105, 0.144] of B pairs
  below the A p5. The taskupdate FLOOR_SHIFT is a quantization artifact: the A p5 equals the 1 ms stamp resolution.
  Every other tested tool transfers.

**Deviations from the prereg.** 6 were logged (P1 `deviations`); none changes a verdict:
1. output path;
2. zero deltas excluded, as on A;
3. change-point seed index over eligible series;
4. transfer also requires 5 sessions;
5. no vacuous FLAT kill;
6. nested-G exclusion in CC formats only.

The audit's minor findings (PV probe 1 audit):
- the seed deviation's effect analysis was one-sided (item 4a);
- G per-tool medians are quoted below n = 30 in the notes (item 8a); this report quotes only n ≥ 30;
- the OpenCode ALIVE is also limited to auto_read, which the notes did not say (item 7a);
- the floor-step label is assigned without the global rate min-n, an unlogged deviation: the STABLE labels for opencode
  (0/15), cc_local (0/5) and gemini (0/4) should read INSUFFICIENT_N (items 4c and 8d). This report relabels them.
  None would trigger a downgrade either way.

**Nulls, with the same prominence.**
- **The largest unit is not ALIVE.** swechat CC, with W pairs from 1,042 sessions, is WEAK because its floor is UNSTABLE
  (21/156).
- **The two ALIVE units have no floor-stability evidence.** Their series counts (0/15, 0/5) are below min-n.
- **The two ALIVE units' positive controls are small.** G is 127 pairs from 12 s (opencode, 116 of them subagent) and
  153 pairs from 12 s (cc_local, bimodal; see above).
- **Codex has no generation-bound control.** G = 0, so its AUC is untestable.
- **Gemini's control is too small.** G has 13 pairs from 5 s.
- **aiv_cu, whowhen and cursor have no per-action latency at all.**
- **Shell, edit and write latencies were never tested** in the Claude Code formats. Human waits cannot be separated
  without `permissionMode`, which the IR does not carry.
- **Web tools without a duration were dropped from G**: 1,163 swechat CC and 1,082 cc_local webfetch/websearch pairs
  have no tool-reported duration (P1 `separability.G_usable.excluded.no_tool_reported_duration`).
- **Results too short to test.** Only results long enough for T_gen ≥ 1 s are testable: 20,937 of 26,639 W pairs in
  swechat CC and 3,217 of 7,423 in aiv_cc. The thresholds are 189 to 377 chars by unit.

**Interpretation.**
- r ≪ 1 is consistent with the result not having been generated inline by the model's decoder at the G90 rate. A
  fabricator generating faster than G90, or using a smaller model, could also land at r < 1 (§5.1). r ≥ 1 is
  uninformative.
- The check is blind to a replaced execution layer, which emits results at program speed, and to padded latency.
- Floors must be calibrated per harness × tool.
- The swechat CC floor moves mid-session in 21 of 156 eligible series. A per-session learned floor would misfire.
- The two ALIVE units carry composition risk:
  - 175 of 214 B opencode sessions come from one repo (IX outliers/O3 **[S]**).
  - cc_local is dominated by a few sessions (caveat 3).

### 3.2 Probe 2: knowledge precedence

**Measurement: the honest unsourced baseline per reference class.** Main thread, first mentions
(`notes/probe_2.md` §3).

| Class | swechat CC | codex (small n) | opencode | gemini | cc_local | aiv_cc (one agent) | aiv_cu |
|---|---|---|---|---|---|---|---|
| path (S_path_any) | 0.289 [0.276, 0.300] | 0.311 [0.213, 0.429] | 0.309 [0.229, 0.394] | 0.523 [0.410, 0.635] | 0.592 [0.445, 0.653] | 0.192 [0.081, 0.351] | 0.807 [0.788, 0.824] |
| Edit old_string symbols | **0.027 [0.022, 0.031]** | 0.050 [0.011, 0.069] | 0.100 [0.043, 0.164] | 0.397 [0.201, 0.520] | 0.421 [0.320, 0.569] (12 s) | 0.028 [0.004, 0.073] | none |
| symbols in shell | 0.296 [0.263, 0.332] | 0.353 [0.278, 0.483] | 0.227 [0.144, 0.418] | 0.214 [0.143, 0.338] | 0.751 [0.675, 0.867] | 0.701 [0.467, 0.843] | 0.786 [0.761, 0.809] |
| env var and config key | 0.125 [0.103, 0.148] | 0.356 [0.208, 0.498] | 0.156 [0.050, 0.320] | 0.077 [0.000, 0.241] | 0.680 [0.530, 0.850] | 0.534 [0.217, 0.778] | 0.832 [0.796, 0.868] |

**Per-session unsourced path share, swechat CC main** (897 sessions with ≥ 10 first-mention paths;
`per_session_unsourced_share`). p10 0.069 [0.063, 0.077], median 0.243 [0.231, 0.261], p90 0.522 [0.492, 0.538].

**Per-session histograms for every cell** (P2 `units.<u>.strata.<s>.classes.path.per_session_unsourced_share.hist`;
sessions with ≥ 10 first-mention paths; counts by tenths of the unsourced share, from [0, 0.1) to [0.9, 1.0]). Cells
with fewer than 30 such sessions are raw counts only.

| Cell (verdict) | Sessions | 0–.1 | .1–.2 | .2–.3 | .3–.4 | .4–.5 | .5–.6 | .6–.7 | .7–.8 | .8–.9 | .9–1 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| swechat CC main (WEAK) | 897 | 160 | 190 | 207 | 120 | 112 | 65 | 18 | 15 | 5 | 5 |
| swechat CC subagent (WEAK) | 541 | 171 | 195 | 109 | 31 | 18 | 11 | 3 | 0 | 2 | 1 |
| opencode subagent (WEAK) | 127 | 77 | 32 | 14 | 2 | 2 | 0 | 0 | 0 | 0 | 0 |
| codex subagent (WEAK; raw counts) | 29 | 9 | 14 | 4 | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| aiv_cc main (WEAK, one agent) | 40 | 21 | 3 | 4 | 3 | 1 | 4 | 1 | 1 | 1 | 1 |
| opencode main (DEAD; raw counts) | 17 | 4 | 1 | 6 | 3 | 1 | 2 | 0 | 0 | 0 | 0 |
| codex main (DEAD; raw counts) | 21 | 3 | 7 | 6 | 3 | 0 | 0 | 2 | 0 | 0 | 0 |
| cc_local main (DEAD; raw counts) | 21 | 1 | 1 | 1 | 0 | 0 | 2 | 3 | 8 | 4 | 1 |
| aiv_cu main (INCONCLUSIVE) | 424 | 1 | 4 | 6 | 12 | 21 | 37 | 39 | 50 | 74 | 180 |
| gemini main (INSUFFICIENT_N; raw) | 11 | 0 | 0 | 3 | 0 | 1 | 2 | 3 | 1 | 1 | 0 |

The aiv_cc main histogram is concentrated near 0, with the rest spread over the whole range: 21 of its 40 runs sit in
[0, 0.1). That is one agent's runs, not 40 independent sessions.

**By depth, swechat CC main** (`unsourced_by_depth`). Depth 1 0.368 [0.327, 0.410]; depth 2 0.126 [0.104, 0.151];
depth 3 0.167 [0.147, 0.190]; depth 6 0.147 [0.119, 0.178]; depth 7 0.103 [0.073, 0.138]; depth 9 0.156 [0.120, 0.196];
depth 10 0.175 [0.095, 0.257]. **Past depth 1 the rate is flat.**

**By position in the thread** (`by_call_ordinal`). First call 0.352 [0.313, 0.392]; calls 5–19 0.252 [0.235, 0.267];
calls 100–499 0.320 [0.294, 0.347]; calls 500+ 0.403 [0.328, 0.453] (23 s).

**Where sources come from, swechat CC main paths** (`classes.path.sourced_by`). Result 0.594 [0.579, 0.608], user 0.103
[0.093, 0.113], system 0.067 [0.058, 0.076], enumeration 0.104 [0.096, 0.113]. Only 0.174 [0.166, 0.182] are sourced by
the immediately preceding result. The matching result lags by a median of 3 result events; p90 29 [26, 33].

**S_deep detail, swechat CC main.**
- First-try success 0.961 [0.958, 0.966].
- Sessions with at least one knowledge-from-nowhere deep read: 231/586 = 0.394 W[0.355, 0.434].
- By tool: read 0.147 [0.127, 0.166] (4,549); edit 0.019 [0.000, 0.051] (106).
- Post-hoc trace of the 671 such reads (`post_hoc_unsourced_deep_trace`):
  - 0.523 [0.455, 0.589] had the basename visible earlier;
  - 0.113 [0.080, 0.151] appeared in the agent's own earlier arguments;
  - 0.410 [0.347, 0.474] leave neither trace.

**Deviations.** 9 were logged (P2 `deviations`). None changes a verdict.
- **Drive-letter case.** Matching is case-insensitive. This matters materially only in cc_local: S_path_any 1,669/2,820
  = 0.592 [0.445, 0.653] against 0.694 [0.618, 0.737] literal (PV probe 2 re-derivation), both DEAD. S_deep, which is
  below the session minimum there, is 31/90 against 51/90 literal (raw counts only).
- **Access population.** Under the calibration population, swechat CC main S_deep is 0.157 [0.137, 0.178]. Same labels.

The audit corrected these things (PV probe 2 audit):
- **Work continued on killed cells (rule 5).** After the first B output, S_path_any without creation targets was added
  for the three DEAD cells, which contradicts "work stopped there" and README rule 6. The numbers are quarantined below.
- **Asymmetric treatment of below-minimum cells (rule 7).** The notes interpreted the one favourable below-minimum
  S_deep cell (aiv_cc 0/1,235) and left the unfavourable ones as bare counts. This report lists all five the same way
  under "Nulls".
- The three "sensitivity variants" were defined by the analyst. They are not pre-registered (rule 6b).
- The notes' claim that subagents are cleaner "because their nested prompt names the files" is contradicted for OpenCode.
  There, deep accesses are sourced by parent_prompt in 6/219 against result in 203/219. The claim holds only for CC
  subagents, where parent_prompt sources 1,803/6,850 = 0.263 [0.218, 0.309] (296 s; P2
  `units.swechat/claude_code.strata.sub.deep_first_try.deep_sourced_by`) (rule 6b).
- Two deviations lack a before/after (rule 4): the Codex subagent envelope source (the strict-prereg value is 0.138
  [0.105, 0.173] against the probe's 0.131, PV re-derivation; WEAK either way) and the OpenCode child-session root
  (strict fallback S_path_any 0.098 [0.084, 0.112], WEAK either way).
- 43 rates in the JSON sit below the global min-n floor. No verdict reads them (rule 8).

**Post-hoc description of killed cells: not evidence** (PV probe 2 audit, rule 5; it does not reopen any line).
S_path_any without creation targets, computed after the kill: codex main 0.300 [0.199, 0.425], opencode main 0.219
[0.168, 0.274], cc_local main 0.514 [0.383, 0.586]. All three stay above the 0.20 DEAD line.

**Nulls, with the same prominence.**
- **No cell is ALIVE**, including the instrument-validated swechat CC.
- **Three cells are DEAD**: opencode main, codex main and cc_local main.
- **S_deep below the 20-session minimum, all five cells as raw counts, no rates and no verdict**: codex main 27/156
  (11 s), opencode main 18/201 (11 s), gemini 55/127 (13 s), cc_local main 31/90 (17 s), aiv_cc main 0/1,235 (13 runs,
  one agent).
- **No subagent signal outside three scaffolds.** cc_local has 675 subagent threads, but they sit in 6 sessions.

**Interpretation.**
- "Any world-specific path with no visible antecedent" is buried. An honest agent leaves 0.19 to 0.81 of first-mention
  paths unsourced.
- "Deep first-try read of a never-shown path" is not buried, but it misses the 0.05 budget at 0.144.
- Edit `old_string` symbols are the quiet channel in CC formats (0.027 [0.022, 0.031]). Claude Code's read-before-edit
  gate is partial (IX sequences/S1 **[S]**): with no prior same-path read, only 244/1,143 = 0.2135 [0.1750, 0.2573] of
  edits are refused, and 187 edits with no visible read or write succeed.
- A usable detector would have to compare rates, not alarm per reference, and it would need a matcher that credits path
  composition.

### 3.3 Probe 3: environment pushback

**Per-call error rate, primary definition** (P3 `error_rate_per_call`, `sessions_with_any_primary_error`).

| Unit | Errors / paired calls | Rate [CI] | Sessions with ≥ 1 error |
|---|---|---|---|
| swechat/claude_code | 7,449 / 194,367 | 0.0383 [0.0360, 0.0408] | 1,137/1,649 = 0.690 W[0.667, 0.711] |
| swechat/codex | 544 / 9,727 | 0.0559 [0.0457, 0.0803] | 40/63 |
| swechat/opencode | 307 / 8,195 | 0.0375 [0.0258, 0.0483] | 77/213 |
| swechat/gemini (union, labelled) | 253 / 1,776 | 0.1425 [0.0841, 0.1783] | 13/21 |
| cc_local | 1,104 / 36,542 | 0.0302 [0.0210, 0.0358] | 30/174 = 0.172 W[0.124, 0.235] |
| aiv_cc (one agent) | 779 / 38,738 | 0.0201 [0.0106, 0.0308] | 53/119 |
| aiv_cu (proxy) | 1,288 / 59,956 | 0.0215 [0.0194, 0.0236] | 557/1,979 |
| whowhen AG | 54 / 149 | 0.362 [0.280, 0.443] | 41/62 |

**Primary error classes, swechat CC** (P3 `units.swechat/claude_code.error_rate_per_call.class_counts`). Counted as
primary: cc_exit_code 3,225, cc_tool_use_error 2,470 and unmarked 1,754, which sum to the 7,449 errors above. Kept
apart: cc_interrupt_reject 662 and cc_permission_denied 30. ok: 186,226.

**Per-session error rate in long sessions (≥ L75)** (P3 `per_session_error_rate.long_sessions_L75.linear_bins_positive`).
The first column counts sessions at exactly 0. The other bins are (lo, hi].

| Unit | n | = 0 | (0, .005] | (.005, .01] | (.01, .02] | (.02, .05] | (.05, .1] | (.1, .2] | (.2, .5] | (.5, 1] |
|---|---|---|---|---|---|---|---|---|---|---|
| swechat CC | 413 | 9 | 5 | 33 | 71 | 188 | 92 | 15 | 0 | 0 |
| cc_local | 36 | 15 | 0 | 0 | 1 | 16 | 2 | 2 | 0 | 0 |
| aiv_cu | 988 | 678 | 0 | 0 | 2 | 202 | 63 | 32 | 11 | 0 |
| whowhen AG | 27 | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 13 | 7 |
| aiv_cc | 16 | 1 | 3 | 3 | 4 | 3 | 2 | 0 | 0 | 0 |
| codex | 11 | 0 | 0 | 0 | 0 | 5 | 2 | 4 | 0 | 0 |
| opencode | 7 | 0 | 0 | 0 | 0 | 3 | 4 | 0 | 0 | 0 |

Long-session per-session quantiles for swechat CC: p25 0.018, p50 0.0311 [0.0296, 0.0339], p75 0.0508, p90 0.0725
(`notes/probe_3.md` §2.2). Only p50 carries a CI.

**swechat CC zero-error share by session length** (`zero_error_share_by_ncalls_log2_bin`; observed against the
independence expectation E0).

| Calls | Zero-error sessions | E0 |
|---|---|---|
| 32–63 | 112/356 | 0.173 |
| 64–127 | 50/346 | 0.0375 |
| 128–255 | 10/254 | 0.002 |
| 256–511 | 0/119 | |
| 512–1,023 | 0/55 | |
| 1,024+ | 0/7 and 0/2 | |

At L75: Z/E0 = 24.0. At L90 (≥ 220 calls): 0/224, W hi 0.017.

**Zero-error tail at L75 and L90 in every unit** (P3 `units.<u>.zero_error_tail.L75`, `.L90`). E0 is the share
independent errors would give (a null expectation, no CI). Z/E0 near 1 means no excess over independence. Cells below
n_long = 20 are INSUFFICIENT_N and are shown as raw counts; their Wilson intervals are in the JSON but are not quoted
(PV probe 3 audit, rule 8).

| Unit | L75 calls | Z at L75 | E0 | Z/E0 | L90 calls | Z at L90 |
|---|---|---|---|---|---|---|
| swechat CC (ALIVE) | 134 | 9/413 = 0.022 W[0.012, 0.041] | 0.000908 | 24.0 | 220 | 0/224, W hi 0.017 |
| cc_local (DEAD) | 20 | 15/36 = 0.417 W[0.271, 0.578] | 0.304 | 1.37 | 46 | 0/14 (raw) |
| aiv_cu (DEAD, proxy) | 40 | 678/988 = 0.686 W[0.657, 0.714] | 0.414 | 1.66 | 41 | 178/292 = 0.610 W[0.553, 0.664] |
| whowhen AG (WEAK) | 3 | 7/27 = 0.259 W[0.132, 0.447] | 0.211 | 1.23 | 4 | 3/12 (raw) |
| aiv_cc (one agent) | 666 | 1/16 (raw) | | | 1,559 | 1/9 (raw) |
| codex | 120 | 0/11 (raw) | | | 184 | 0/9 (raw) |
| opencode | 185 | 0/7 (raw) | | | 425 | 0/4 (raw) |
| gemini (union) | 405 | 0/1 (raw) | | | 548 | 0/1 (raw) |

Only swechat CC shows a zero-error tail far below independence. The whowhen AG WEAK sits at what independent errors
predict for 3-call "long" sessions; it is a WEAK by the rule's numbers, with no friction signal (PV probe 3
re-derivation).

**Reaction (retry).**
- Polling inflates R_ok:
  - aiv_cc `mcp__village__get_events` has 11,716 "retries" among 18,150 successful calls;
  - in codex, `write_stdin` supplies 925 of 1,649 R_ok retries.
- **POST HOC, no verdict, live cells only:** the tool-stratified effect (`post_hoc_tool_stratified_effect`) is swechat CC
  0.092 [0.078, 0.106], cc_local 0.130 [0.079, 0.199], aiv_cu 0.081 [0.056, 0.105] and opencode −0.071 [−0.151, 0.047].
  The values on the DEAD reaction cells are in the quarantined block below.
- Retries of an immediately preceding failed call are under 1.3% of all successor pairs in every CLI unit: swechat CC
  1,435/190,637 = 0.0075 [0.0069, 0.0083].

**Early against late in a session** (descriptive, no verdict; `early_late`; sessions with ≥ 20 calls).
- swechat CC: late − early = −0.0024 [−0.0056, 0.0009], 1,308 s. 227 sessions have errors early only and 251 late only.
- opencode rises: +0.0173 [0.0044, 0.0325], 135 s.
- aiv_cu falls: −0.0070 [−0.0096, −0.0040], 1,500 s.
- No change detected: codex +0.0010 [−0.0146, 0.0165] (50 s); gemini union +0.073 [−0.024, 0.136] (13 s); cc_local
  +0.0019 [−0.0038, 0.0121] (36 s); aiv_cc +0.0008 [−0.0077, 0.0105] (57 runs, one agent).
- whowhen AG: 0 sessions reach 20 calls.

**Deviations.** 4 were logged: output path; Gemini per-class rates; simple_text labelled DEAD per the JSON; the retry
successor set includes unpaired calls.

The audit's findings (PV probe 3 audit):
- **A false effect claim (rule 4a).** The last deviation's stated effect, "a fraction of a percent", is false for
  whowhen AG: 20 of 104 successors there are unpaired. No sensitivity run was done, and the AG reaction cell (DEAD, CI
  lo −0.083) could move.
- **Unlogged departures (rule 4c):** Wilson CIs and quantiles below the minimum n; the cc_local raw-tool-key comparison;
  the aiv_cc_A session-id read; and permission or interrupt results left out of R_ok (571 of 190,637 pairs in swechat
  CC).
- **Work continued on killed cells (rule 5).** See the quarantined block below.
- **An unsupported cause (rule 6b).** No JSON number supports "the codex DEAD comes largely from polling tools". The only
  codex post-hoc number is its tool-stratified effect, −0.015 [−0.155, 0.165].
- **Softened nulls (rule 7).** The notes' "0/36 long sessions are flag-free" for cc_local uses an alternate,
  non-pre-registered definition that also counts interrupt-reject markers. "The proxy probably explains much of it" for
  aiv_cu was asserted, not measured. The notes also interpreted INSUFFICIENT_N cells ("all point the same way as
  swechat CC"), which the prereg vocabulary forbids.
- **Below-minimum outputs (rule 8):** Wilson CIs on INSUFFICIENT_N cells, quantiles below the quantile minimum, and the
  aiv_cu openai-chat stratum Z on 18 long sessions without a label.

This report states the cc_local and aiv_cu zero-error tails, and the four DEAD reaction cells, as DEAD without
qualification. It does not interpret the INSUFFICIENT_N cells.

**Post-hoc description of killed cells: not evidence** (PV probe 3 audit, rule 5; none of it reopens a line).
- Tool-stratified reaction effect on the DEAD reaction cells: aiv_cc +0.048 [0.021, 0.091] (one agent; run-clustered CI
  overstates independence), codex −0.015 [−0.155, 0.165], gemini +0.022 [−0.017, 0.086].
- aiv_cc reaction with village-bash rows removed from R_ok: −0.230 [−0.343, −0.077], unchanged.
- cc_local, an alternate definition that also counts permission and interrupt flags: 0/36 long sessions are free of
  them (W hi 0.096). This is not the pre-registered error definition.
- cc_local, composition of the 15 zero-error long sessions: 20 to 30 calls each, glob 169 of their 333 calls.
- aiv_cu, long sessions with at least one shell call: 326/630 = 0.517 W[0.478, 0.556]; 352 of the 678 zero-error long
  sessions have no shell call.
- aiv_cu zero-error tail per model stratum, at the unit's L75 of 40 calls
  (`zero_error_tail.aiv_cu_per_stratum`): compat-chat 56/138 = 0.406 W[0.327, 0.489]; openai-responses 116/186 = 0.624
  W[0.552, 0.690]; gemini-flash 42/64 = 0.656 W[0.534, 0.761]; gemini-pro 142/198 = 0.717 W[0.651, 0.775];
  anthropic-opus 101/139 = 0.727 W[0.647, 0.794]; anthropic-haiku 58/72 = 0.806 W[0.700, 0.880]; anthropic-fable
  14/17 (raw); anthropic-sonnet 127/150 = 0.847 W[0.780, 0.896]; anthropic-claude-code 4/6 (raw); openai-chat 18/18
  (raw, 18 long sessions). Every stratum with n_long ≥ 20 is above the 0.30 DEAD line.

**Nulls, with the same prominence.**
- **cc_local zero-error tail: DEAD.** Z = 15/36 = 0.417.
- **aiv_cu zero-error tail: DEAD.** Z = 678/988 = 0.686.
- **Reaction is never ALIVE.** It is WEAK in 4 units and DEAD in 4 (aiv_cc, codex, gemini, whowhen AG).
- **Four units are INSUFFICIENT_N** for the zero-error tail: aiv_cc, codex, opencode and gemini.
- **The one other WEAK tail (whowhen AG) carries no excess over independence** (Z/E0 = 1.23).
- **OpenCode came in far below projection.** It had 7 long sessions against a projected 59.9. B OpenCode sessions are
  short: p50 22 calls against an A-derived L75 of 185.

**Interpretation.**
- In swechat Claude Code, a long session with zero tool errors is rare in honest logs (9/413; none of 224 at ≥ 220
  calls).
- Faking an `Exit code 1` is cheap. This screens naive fabrication; it proves nothing against an informed forger.

### 3.4 Probe 4: entropy and incidental detail

**Surface: share of tool results carrying any hex token, large integer or ISO/epoch timestamp** (P4
`units.<u>.census`).

| Unit | Results (s) | Any of the three | Hex | Large int | Timestamp | Calls with model-originated hex |
|---|---|---|---|---|---|---|
| swechat/claude_code | 194,371 (1,649) | 0.150 [0.143, 0.158] | 0.072 [0.068, 0.076] | 0.085 [0.080, 0.090] | 0.034 [0.029, 0.038] | 170/194,652 = 0.00087 [0.00062, 0.00116] |
| swechat/codex | 9,727 (63) | 0.392 [0.274, 0.447] | 0.128 [0.111, 0.155] | 0.274 [0.137, 0.350] | 0.132 [0.092, 0.174] | 2/9,801 |
| swechat/opencode | 8,195 (213) | 0.246 [0.200, 0.301] | 0.138 [0.103, 0.185] | 0.126 [0.105, 0.152] | 0.087 [0.070, 0.106] | 28/8,199 |
| swechat/gemini | 1,776 (21) | 0.314 [0.244, 0.361] | 0.054 [0.042, 0.080] | 0.307 [0.239, 0.353] | 0.012 [0.007, 0.022] | 0/1,776 |
| cc_local | 36,542 (174) | 0.224 [0.177, 0.263] | 0.020 [0.018, 0.027] | 0.181 [0.133, 0.209] | 0.062 [0.033, 0.089] | 19/36,542 |
| aiv_cc (one agent) | 38,738 (119) | 0.825 [0.769, 0.871] | 0.082 [0.060, 0.109] | 0.184 [0.132, 0.262] | 0.801 [0.740, 0.855] | 12/38,746 |
| aiv_cu | 59,956 (1,979) | 0.160 [0.150, 0.170] | 0.089 [0.083, 0.096] | 0.100 [0.093, 0.108] | 0.033 [0.029, 0.037] | 560/59,956 = 0.0093 [0.0078, 0.0112] |
| whowhen | 535 (95) | 0.482 [0.394, 0.561] | 0.247 [0.177, 0.323] | 0.411 [0.325, 0.496] | 0.073 [0.045, 0.101] | 1/595 |

Among swechat CC results that carry hex, the count per result is p50 2, p95 13 (13,955 results; descriptive). The digit
test needs 1,131 symbols. Other units' per-result counts are in P4 `units.<u>.census.hex_tokens_per_result`.

**Hex-bearing results by tool** (P4 `units.<u>.census.results_by_tool.<tool>.hex`; the largest tools per unit). Hex is
most common in shell, subagent and web output and is almost absent from edits, writes and GUI results.
- swechat CC: shell 10,904/61,036 = 0.179 [0.169, 0.190]; read 1,363/55,246 = 0.025 [0.021, 0.028]; edit 205/28,764 =
  0.007 [0.000, 0.018]; grep 52/18,883 = 0.003 [0.002, 0.004]; glob 32/5,925 = 0.005 [0.003, 0.008]; taskupdate
  0/4,748; write 6/4,470 = 0.001 [0.000, 0.003]; subagent 802/3,624 = 0.221 [0.187, 0.261].
- aiv_cu: gui 0/26,983; shell 5,242/24,698 = 0.212 [0.199, 0.225]; get_pixel_coords_of_element 0/4,044;
  send_message_back_to_chat 0/2,615; pause 0/1,224; search_history 83/292 = 0.284 [0.212, 0.365].
- cc_local: shell 582/26,873 = 0.022 [0.020, 0.033]; read 57/2,414 = 0.024 [0.002, 0.073]; edit 0/1,457; write 0/1,426.
- opencode: read 435/3,759 = 0.116 [0.079, 0.162]; shell 500/1,859 = 0.269 [0.212, 0.343]; edit 0/947; grep 148/872 =
  0.170 [0.091, 0.273].
- codex: exec_command 436/4,565 = 0.096 [0.069, 0.179]; shell_command 333/1,834 = 0.182 [0.120, 0.225]; write_stdin
  449/1,715 = 0.262 [0.128, 0.322]; apply_patch 0/722.
- aiv_cc (one agent): get_events 1,321/18,239 = 0.072 [0.052, 0.105]; shell 981/5,131 = 0.191 [0.138, 0.249];
  computer_use 0/3,955; read 12/2,914 = 0.004 [0.001, 0.009].
- whowhen: websurfer 125/337 = 0.371 [0.277, 0.483]; code_exec 7/149 = 0.047 [0.013, 0.092].

**Feasibility projection against observation** (P4 `prereg_reference.feasibility_projection_p4`, A-split projection;
`units.<u>.hex.main.T_orig.symbols`, B). T_orig hex symbols, projected → observed: swechat CC 931.3 → 1,868; opencode
1,369.6 → 47; aiv_cu 26,800.0 → 10,997; cc_local 119.5 → 175; aiv_cc 328.1 → 137; codex, gemini, cursor and whowhen
0.0 → 64, 0, 0 and 32. The opencode projection rested on 160 A symbols from 6 tokens in 4 sessions (PV probe 4
re-derivation); its B shortfall is real.

**Hex uniformity by class** (P4 `units.<u>.hex.main.<class>.digit_test`; w_adj [CI]; symbols / tokens / sessions). Only
T_orig feeds the verdict. The other classes are descriptive.

| Class | swechat CC | aiv_cu |
|---|---|---|
| M_git (control) | 0.002 [0.000, 0.016]; 139,967 / 15,389 / 978 | 0.017 [0.012, 0.034]; 45,281 / 5,239 / 630 |
| M_all | 0.010 [0.008, 0.017]; 302,051 / 22,923 / 1,228 | 0.022 [0.007, 0.053]; 223,522 / 12,171 / 837 |
| T_copy (copied into a call from earlier text) | 0.063 [0.048, 0.093]; 13,564 / 1,272 / 382 | 0.057 [0.040, 0.096]; 22,211 / 1,348 / 354 |
| T_orig (verdict class) | 0.110 [0.041, 0.232]; 1,868 / 161 / 71 | 0.093 [0.043, 0.216]; 10,997 / 1,142 / 192 |
| A_copy (assistant text, copied) | 0.000 [0.000, 0.049]; 11,731 / 1,543 / 557 | 0.104 [0.058, 0.212]; 6,335 / 568 / 201 |
| A_orig (assistant text, model-originated) | 0.099 [0.085, 0.244]; 1,133 / 97 / 55 | 0.390 [0.203, 0.627]; 1,315 / 155 / 84 |

T_copy (call-argument tokens equal to, or a prefix of, a token seen earlier in the session's result, user or system
text) is also less uniform than the M_git control in both units: its CI lower bound clears the control's upper bound
(0.048 against 0.016 in CC; 0.040 against 0.034 in aiv_cu). The probe notes' reading that the copied classes "sit near
the machine control" holds for CC A_copy only. **Interpretation:** part of the T_orig excess may come from which hex
tokens get typed into calls at all, not from invention.

**Hex digit counts, observed against expected** (P4 `units.<u>.hex.main.<class>.observed_symbol_counts` /
`expected_symbol_counts`). Expected is uniform hex conditioned on at least one digit and one letter.
- **swechat CC T_orig** (1,868 symbols). Digits 0–9: 131, 137, 141, 130, 127, **87**, 111, 102, 94, 94, against 115.547
  each. Letters a–f: 136, 112, 118, 131, 113, 104, against 118.754 each.
- **swechat CC M_git** (139,967 symbols). 0–9: 8,760, 8,622, 8,645, 8,754, 8,437, 8,575, 8,618, 8,613, 8,662, 8,674,
  against 8,622.973. a–f: 8,984, 8,909, 8,788, 8,850, 9,076, 9,000, against 8,956.212.
- **aiv_cu T_orig** (10,997 symbols). 0–9: **908**, 696, 644, 622, 724, 714, 629, 660, 668, 646, against 678.971.
  a–f: 683, 682, 698, 662, 621, 740, against 701.215.
- **aiv_cu M_git** (45,281 symbols). 0–9: 2,834, 2,848, 2,788, 2,833, 2,787, 2,891, 2,801, 2,842, 2,724, 2,742, against
  2,783.392. a–f: 2,815, 2,782, 2,846, 2,970, 2,980, 2,798, against 2,907.846.
- Descriptive top tokens in swechat CC T_orig include placeholders: `abc1234` ×12, `abcd1234` ×5, `aaa1111` ×5.

**Round numbers, swechat CC** (`units.<u>.ints.main.<class>.round`). The verdict statistic counts **distinct values**:
each integer counts once, however often it occurs.
- T_orig last-00 0.307 [0.220, 0.395] and last-000 0.233 [0.162, 0.301].
- M_all last-00 0.022 [0.018, 0.026] and last-000 0.009 [0.006, 0.012].
- **POST HOC, distinct values** (`post_hoc_descriptive.ints_T_by_origin`): of the 300 T_orig values, 51 are JSON-number
  parameters, and 49/51 of them end in 0 (0.961 [0.900, 1.000], 27 s). The other 249 are embedded in argument strings,
  and 78/249 = 0.313 [0.213, 0.427] (112 s) end in 0. So JSON-number parameters are 49 of the 127 last-0 values. The
  string-embedded subset alone clears the ALIVE bar, M_all hi + 0.05 = 0.172 (PV probe 4 audit, rule 6b). The
  independent re-derivation's own split (values that appear inside argument strings) gives 94/265 = 0.355 [0.255,
  0.457].
- **Occurrence-weighted, not the verdict unit:** the most frequent T_orig integers by occurrence are timeouts,
  `120000` ×3,769, `30000` ×2,325, `60000` ×2,127 (`examples_descriptive_ints`). In the verdict statistic each of these
  counts once out of 300.

**Last digit 0 by class in every unit** (`units.<u>.ints.main.<class>.round.last_0`; distinct values). Machine output
(M_all) sits near the uniform 0.1 in most units but not all.

| Unit | M_all | T_copy | T_orig |
|---|---|---|---|
| swechat CC | 2,365/20,419 = 0.116 [0.110, 0.122] | 204/1,479 = 0.138 [0.118, 0.160] | 127/300 = 0.423 [0.334, 0.520] |
| cc_local | 2,243/18,550 = 0.121 [0.110, 0.130] | 171/1,124 = 0.152 [0.125, 0.282] | 221/341 = 0.648 [0.435, 0.786] |
| aiv_cu | 3,000/23,506 = 0.128 [0.113, 0.152] | 259/1,772 = 0.146 [0.120, 0.195] | 740/3,866 = 0.191 [0.133, 0.293] |
| aiv_cc (one agent) | 284/2,597 = 0.109 [0.099, 0.120] | 7/77 = 0.091 [0.035, 0.155] | 26/42 (raw) |
| codex | 352/2,872 = 0.123 [0.111, 0.159] | 93/851 = 0.109 [0.094, 0.294] | 29/31 (raw) |
| opencode | 91/286 = 0.318 [0.195, 0.456] | 10/39 = 0.256 [0.099, 0.750] | 16/23 (raw) |
| gemini | 101/657 = 0.154 [0.105, 0.180] | 2/7 (raw) | 1/1 (raw) |
| whowhen | 20/190 = 0.105 [0.061, 0.164] | 0/2 (raw) | 4/9 (raw) |

Assistant text, descriptive only: swechat CC A_orig last-0 38/69 (raw, below the 100-value minimum); aiv_cu A_orig
128/462 = 0.277 [0.219, 0.335] (87 s).

**Timestamps with seconds = 00** (pre-registered, no verdict; uniform expectation 1/60;
`units.<u>.timestamps.iso.<class>.seconds_00`).

| Unit | M_all | T_copy | T_orig |
|---|---|---|---|
| swechat CC | 1,411/47,359 = 0.030 [0.023, 0.039] (612 s) | 85/199 = 0.427 [0.291, 0.571] (76 s) | 219/260 = 0.842 [0.767, 0.911] (90 s) |
| codex | 149/2,938 = 0.051 [0.029, 0.139] (36 s) | 24/41 = 0.585 [0.333, 0.808] (9 s) | 26/43 = 0.605 [0.364, 0.870] (8 s) |
| aiv_cu | 354/7,331 = 0.048 [0.029, 0.079] (470 s) | 14/119 = 0.118 [0.044, 0.204] (47 s) | 268/394 = 0.680 [0.388, 0.894] (58 s) |
| cc_local | 1,446/3,735 = 0.387 [0.030, 0.664] (90 s) | 29/143 (raw, 3 s) | 35/72 = 0.486 [0.000, 0.649] (5 s) |
| opencode | 62/313 = 0.198 [0.126, 0.328] (26 s) | 7/12 (raw) | 2/10 (raw) |
| aiv_cc (one agent) | 92/6,352 = 0.014 [0.010, 0.019] (77 runs) | 0/12 (raw) | 4/9 (raw) |

Copied timestamps (T_copy) are already far rounder than machine output in swechat CC and codex, so 1/60 is the wrong
baseline for model-typed values; a per-source baseline is needed.

**Exploratory, NOT pre-registered** (`exploratory_not_preregistered`).
- **Model-typed durations are not rounder than uniform.** swechat CC T_orig with an all-zero fraction: 0.031 [0.000,
  0.086], 65 values, against 0.078 expected. Machine output: 0.067 [0.057, 0.078] against 0.027.
- **ls mtimes and "N bytes" values** are too rare to test in the model-typed classes.

**Deviations.** 9 were logged (PV `probes[3].res.deviations`). None changes a verdict. They include:
- the epoch exclusion for JSON-number args;
- the reading of the redaction re-run;
- raw counts only below N_min;
- the post-hoc integer-origin breakdown, added after the verdicts existed. Run-to-run diffs show only added keys.

The audit corrections (PV probe 4 audit):
- **"Mostly chosen parameters" is not supported (rule 6b).** The run summary and the notes attributed the ALIVE
  round-number verdicts mostly to round parameters the model chooses, citing `120000` ×3,769. Those are occurrence
  counts; the verdict counts distinct values. In the distinct-value class, JSON-number parameters are 51/300 values and
  49/127 of the last-0 values, and the string-embedded subset alone is 78/249 = 0.313 [0.213, 0.427], above 0.172. An
  earlier draft of this report repeated the unsupported reading in its headline; it is withdrawn.
- **Machine output is not rounder everywhere (rule 6a).** whowhen M_all last-0 is 0.105 [0.061, 0.164], and that CI
  contains 0.1.
- **The INSUFFICIENT_N count (rule 7).** Under `prereg.json` it is 6 of 8 testable units, plus cursor with its control
  missing, not "7 of 9".
- **Unlogged departures (rule 4).** (a) The script returns INSUFFICIENT_N when the control CI is unreportable, a branch
  the prereg does not have (it never fired). (b) Quantiles use `stats.describe`, not the prereg's
  `stats.cluster_quantile`, with no min-n gate: 353 quantile entries sit below the quantile minimum (rule 8). (c) Split A
  was opened for a count-only implementation check; the notes disclose it, but the deviation list does not. None can
  change a verdict.

**Latent instrument failures** sit behind INSUFFICIENT_N:
- gemini M_all w_adj 0.166 [0.101, 0.458];
- whowhen M_all 0.118 [0.096, 0.177].

Both would fail the 0.15 ceiling.

**Nulls, with the same prominence.**
- **Hex never reaches ALIVE.** It is INSUFFICIENT_N in 6 of 8 testable units.
- **Models rarely type unsourced hex**: 170/194,652 = 0.00087 [0.00062, 0.00116] of swechat CC calls.
- **A single fabricated result cannot be tested.** A hex-bearing result has a median of 2 tokens against a 1,131-symbol
  minimum.
- **Most results carry none of the fields at all**: only 0.150 [0.143, 0.158] of swechat CC results carry any.
- **Round numbers are INSUFFICIENT_N in 5 of 8 testable units, and in cursor.**

**Interpretation.**
- Model-originated hex is measurably but only modestly less uniform than machine hex, and only when pooled over many
  results; no single result can be tested.
- "Unsourced" is not "invented". The direction of the resulting bias in w_adj is unknown. Recalled real hashes dilute
  it toward the control: aiv_cu T_orig contains `e3b0c442`, a prefix of sha256(""). Typed placeholders inflate it:
  `abc1234` ×12, `abcd1234` ×5 and `aaa1111` ×5 in swechat CC T_orig are less uniform than a fabricated SHA would be.
  And copied hex (T_copy) is itself less uniform than the control. So w_adj is neither a lower nor an upper bound for
  invented hex.
- What the ALIVE round-number verdicts measure is open. The distinct-value data do not show that chosen parameters
  explain most of the effect; nor do they show invented measurements, because the fields a fabricated result would carry
  (byte counts, PIDs, durations) were not testable at the needed n.

---

## 4. Phase C: discoveries and five proposed mechanisms

### 4.1 What Phase C is, and how to read it

- **Lenses.** 14 discovery lenses produced 239 observations. A skeptic re-checked each one, and the results are indexed
  in `out/phase_c/_index.json` (`by_kind_and_status`):

  | Kind | Total | Reproduced | Unchecked | Not reproduced |
  |---|---|---|---|---|
  | hit | 88 | 76 | 7 | 5 |
  | surprise | 59 | 52 | 4 | 3 |
  | null | 51 | 39 | 8 | 4 |
  | artifact | 41 | 33 | 6 | 2 |
  | **All** | **239** | **200** | **25** | **14** |

  The skeptics also logged 141 overclaim notes (`skeptic_overclaims`).
- **Candidates and proposals.** `_index.json` `candidate_mechanisms` lists 65 lens-level candidate mechanisms (raw_census
  8, ids_and_clocks_in_ids 7, two_clocks 6, five each from commit_witness, aiv_accounting and sequences, four each from
  ext_witness, distributions, correlations, aiv_narration and token_conservation, three each from swechat_tables,
  changepoints and outliers). They were not carried forward as such. The three proposal lenses (power, robustness,
  coverage) each wrote 5 proposals grounded in observation ids (`grounded_in`), not in candidate ids, and no committed
  file records which candidates a proposal drew on or why the other candidates were dropped. The 15 proposals were then
  merged into the 5 of §4.3.
- **Which split the lenses read.** They read split B, the full population, or both. Their numbers are in-sample and
  **confirm nothing in Phase B**.
- **Numbers.** Wherever a skeptic disagreed, the number below is the skeptic's **[S]**.
- **Not-reproduced observations are never used as support.** All 14 are listed in §4.2.8.
- **Status codes:** R = reproduced; U = unchecked (reported, not relied on); NR = not reproduced.

### 4.2 Main discoveries, grouped by theme

#### 4.2.1 Time inside identifiers: server-minted ids as a provider clock

| Finding | Numbers [S] | n | Status |
|---|---|---|---|
| Anthropic request ids decode as RFC 9562 UUIDv7 (base58 after `req_01`) | swechat 154,815/154,815 are v7 with variant 2, against 2,418.98 expected by chance. The n silently includes 50 Vertex ids the loader stored as message ids. cc_local 31,085/31,085. **The layout was inferred from data and is UNVERIFIED against vendor documentation** | 154,815 ids | IX ids_and_clocks_in_ids/O1, R |
| Request-id time agrees with the client event stamp | Counting every copy: 155,067/155,267 = 0.99871 [0.99676, 0.99992] in 1,638 s. Median offset 3,781 ms [3,684, 3,871]. Holdout A: 11,047 ids, 0 violations. The lens's 0.99986 [0.99971, 0.99996] depended on an arbitrary dedupe | 155,267 (session, request) pairs | ids/O2, R |
| **Skew bracket:** one constant client–server skew per stream places every request-id time between the stream's last input event and its first output block | 10/3,674 swechat CC streams are inconsistent: 0.00272 [0.00112, 0.00466]. Tolerance 0 s gives 18; 5 s gives 7. In consistent streams, the bracket width U−L is p5 1,102 ms, p50 2,268 ms, p95 3,807 ms (descriptive). cc_local 1/847, W [0.000208, 0.00666] **[D]**. aiv_cu Anthropic 0 of 105/80/27/32 streams; Gemini 0 of 255/92; OpenAI 3/463. Committed-script copy: 10/3,676, same CI, 1,610 s (LC:ids_and_clocks_in_ids:`bracket.swechat.anthropic_req.claude_code`). Of the 10 inconsistent sessions, 2 hold re-stamped resume/fork copies and 8 are unexplained (`bracket_x_copies.swechat`) | 3,674 streams | ids/O5, R. **Power is unmeasured in any committed file.** The only evidence that back-dating is caught is the skeptic's placebo, run by uncommitted code and withheld here (§4.3 rank 1). That late-stamping is invisible up to the next input event follows from the construction (reasoning) |
| Client clocks can trail the server by seconds; a constant per-session skew absorbs this | cc_local: 125 offset violations in 3 sessions, min −7,749 ms; drift > 2 s in 2 of 18 sessions. swechat: drift > 2 s in 15 sessions, > 10 s in 0. "Constant within a session" rests on 1–2 sessions | 18 cc_local s with ≥ 20 ids | ids/O6, R |
| Resumed or forked sessions re-stamp copied history; the request-id clock keeps the original time | 2,060 shared entries in 5 session pairs. 2 pairs are re-stamped onto only 1–2 distinct timestamps. Of 561 shared request ids, 178 have exactly one disagreeing copy, and it is the later copy in 178/178. That follows from the offsets (at least 619,473 ms), so it is not independent evidence | 2 re-stamped pairs | ids/O7, R |
| Anthropic message ids switched from random to UUIDv7 on 2026-07-06 (first v7 at 20:23:44 UTC) | aiv_cu: 0 v7 through 2026-06, then 3,314/0 and 1,972/0 in 2026-08 and 2026-09. cc_local: all 360 non-v7 ids fall before the switch and all 30,680 v7 ids after, 0 exceptions | aiv_cu and cc_local message ids | ids/O4, R |
| aiv_cu: every server-minted id family precedes the row insert | 0 violations in every family. **Weak by construction:** the row insert lags the id by a median 5.7–12 s, and OpenAI and Gemini ids have 1 s resolution | 1,043 to 14,038 ids per family | ids/O3, R |
| Client-minted ids agree with the same client's event clock | OpenCode part ids: 8,174, min −14 ms, p50 82 ms [18, 160], 0 violations. Same clock, so not independent | 8,174 ids, 213 s | ids/O10, R |
| **Null:** many ids carry no time | Pre-switch Anthropic message ids and toolu ids are uniform; aiv_cc stores 0 request ids | 155,197 random-format ids | ids/O13, R |
| **Null:** UUIDs printed inside tool output are not fresh | Of 561 v7 mentions, 440 are more than 10 min older than the printing event; 166 distinct values | 561 mentions, 43 s | ids/O14, R |
| A third-party clock on aiv_cu Gemini rows: Google `server-timing` always fits inside the DB row gap | gap ≥ server duration fails 0/12,292, Wilson hi 3.12e-4. Min slack 563.8 ms; p50 6,079 ms [5,838, 6,356]. Covers 347 of 2,000 B sessions | 12,292 rows | two_clocks/O7, R |
| Gemini HTTP Date precedes the row insert, but at 1 s resolution | Order is unambiguous in only 2,831/3,246 flash and 7,276/8,990 pro call rows | 3,246 flash and 8,990 pro call rows | distributions/D19, R (a consistency check, not a discovery) |
| OpenCode and Codex ids embed creation time | OpenCode session ids 208/208 within 2 ms; assistant messages 4,892/4,894; **user messages only 298/577**. Codex turn ids 0/360 violations | 5,471 messages; 360 turns | two_clocks/O4, O5, R |

#### 4.2.2 Harness timers: consistent, but one clock written twice

| Finding | Numbers [S] | n | Status |
|---|---|---|---|
| `bash_progress` elapsed is floored wall-clock elapsed since start | Floor rule 0/112,677, Wilson hi 3.41e-5. Slack min 3 ms, p50 211 ms [165, 280] | 687 s | two_clocks/O9, R |
| Stop-hook summary time equals the max hook `durationMs` (hooks run in parallel) | 0/6,714 violations at 2 ms (Wilson hi 5.7e-4). Slack is 0–1 ms in 5,285/6,714. Serial-sum check fails 2,482/2,512 = 0.988 [0.981, 0.993]. Version 2.1 only | 903 s | two_clocks/O1, R ("to the millisecond" overclaims) |
| Subagent `totalDurationMs` = parent result − first nested event | \|resid\| ≤ 2 ms in 1,900/2,188; ≤ 1 s in 2,188/2,188 | 2,188 | two_clocks/O3, R |
| Codex model-visible `Wall time` header never exceeds the call→output gap (exec_command) | 0/4,408. shell_command headers (0.1 s display) exceed the gap in 646/1,817, by ≤ 49 ms (rounding) | 4,408; 1,817 | two_clocks/O6, R |
| Tool-reported timers lie inside the call→result window | swechat Glob 1/2,090 = 0.00048 [0, 0.0017]; WebFetch 0/341; Task 0/1,023; Agent 0/1,886 | 742 s (Glob) | two_clocks/O8, R (near-null) |
| Exactly-zero call→result gaps | 498/137,380 = 0.0036 [0.0022, 0.0055] in 177 s. 169 lie in re-stamped blocks (2 old sessions); **329 (v2.1) have no established cause** | 137,380 pairs | two_clocks/O12, R (artifact) |
| cc_local async launches | 63/63 Workflow/Agent parent results arrive before their last nested event | 6 s | two_clocks/O15, R |

**Interpretation.** One process writes both the timer and the stamps. "Inside the window" is therefore near-tautological
(PG `lenses[0].ground.checks[2]`). These identities show internal consistency only; they do not witness against an
editor.

#### 4.2.3 Token and usage accounting

| Finding | Numbers [S] | n | Status |
|---|---|---|---|
| Per-call context growth matches logged appended content (out-of-fold \|residual\|, tokens) | p50 / p90 / p99 (descriptive; only the CC p99 has a CI): swechat CC 54.7 / 398.4 / 2,486.5 (p99 CI 2,355.2–2,662.8; 142,468 pairs, 1,641 s); aiv_cc (one agent) 36.0 / 164.5 / 627.1; codex 38.6 / 381.6 / 2,680.5; opencode 29.7 / 428.4 / 1,807.3; cc_local 152.2 / 1,321.4 / 4,950.8; aiv_cu Anthropic 381.1 / 896.8 / 4,499.1; aiv_cu Gemini 416.0 / 870.9 / 3,539.0; Gemini CLI 54.6 / 1,063.6 / 12,194.0. The aiv_cu values mix GUI windows (median residual +206.5) with shell windows (−602.8; descriptive) | 142,468 CC pairs | token_conservation/TC1, R |
| **Measured tamper curve (token conservation):** only multi-thousand-char edits to one result are detectable at FPR 1% | Inserted chars at power 0.5 / 0.9 (D_abs; simulation grid points, no CI): swechat CC 8,913 / 10,000; codex 7,943 / 12,589; opencode 8,913 / 10,000; aiv_cc 2,239 / 2,512; cc_local 8,913 / 12,589; aiv_cu Anthropic 14,125 / 17,783; Gemini CLI 31,623 / 35,481. Power at +3,000 chars: CC 0.0099 [0.0088, 0.0113]; aiv_cc 0.982 [0.974, 0.988] (one agent: all 117 'sessions' are runs of one SDK session, so this CI overstates generality, skeptic). Realized FPR CC 0.0101 [0.0092, 0.0112] | swechat CC clean pairs (as in TC1) | TC2, R |
| **Null:** small results cannot be checked | Simulated power to detect deleting a whole result, swechat CC (simulation estimates, no CI in source): [100, 1,000) chars 0.003 (n 61,269); [1,000, 10,000) 0.085 (n 40,056); [10,000, 100,000) 0.973 (n 8,788) | 61,269 | TC16, R |
| **aiv_cu Gemini image ledger:** per-window change in prompt IMAGE tokens is 0 or exactly one per-model unit | 11,668/11,668 pairs. Unit 258 for gemini-2.5-pro (4,925 pairs); 1,064 for 3-pro (682), 3.1-pro (3,166) and 3.5-flash (2,895). Never negative. GUI windows 5,059/5,092 positive; non-GUI windows shell 0/4,134, get_pixel_coords 0/2,033, pause 0/202. gemini-3.8-flash (277 pairs) never shows an image | 11,668 pairs | TC9, R; untested above 40 images |
| Prompt IMAGE counts sit on a per-model lattice | 10,569/10,569 pro rows on {258, 1,064, 2,160}; 3,219/3,219 flash rows on 1,064; 0/309 sessions mix lattices. Cached IMAGE counts are off-lattice (11/3,022 and 40/9,318) | 10,569 pro and 3,219 flash rows | distributions/D3, R (skeptic adds the 2,160 lattice) |
| ToolSearch results log 0 chars, yet the model receives tokens | 1,119/1,126 single-ToolSearch windows log 0 chars; residual p50 +897.4 [742.2, 997.6] | 422 s | TC4, R |
| Codex shows the model a truncated output while the log keeps all of it | dC − out saturates at p50 11,611 tokens for 100k–300k-char results (n 14; the skeptic finds most are near-identical outputs of one command) | 14 windows | TC5, R |
| Per-image token cost is recoverable only where images are uniform | aiv_cc 1,035.0 [1,029.2, 1,038.6] (n 2,491); swechat CC 535.0 [327.0, 1,168.8], p5–p95 121–1,618 (n 429) | | TC17, R |
| Human turns strip earlier thinking, model-dependently | dC < 0 at user turns: sonnet-4-5 0.264 [0.070, 0.466] (349, 30 s) against opus-4-6 0.016 [0.011, 0.022] | | TC11, R |
| aiv_cc cache-chain identity, cache_read(k+1) = cache_read(k) + cache_creation(k) (one agent) | 59,747/59,804, run-clustered 0.99905 [0.99858, 0.99943], 190 runs of one agent (the run-clustered CI overstates independence). Breaks: 49/59,772 at gaps < 300 s, 8/32 at ≥ 300 s; compaction 0/933; image pairs 4,367/4,570 | 59,804 | aiv_accounting/O9, R |
| aiv_cc token conservation (one agent) | Pre-registered 3-term fit: \|res\| p50 49.6 [42.2, 56.5]; p99 690.2, and 735 and 651 across two random half-splits (descriptive). Spearman 0.986 [0.981, 0.989]. Per stripped image: 890.1 [887.9, 890.9] | 59,804 clean pairs | aiv_accounting/O10, O11, R |
| aiv_cc: unlogged context resets | 30 non-compaction pairs where context shrinks and cache_read resets to the system prefix; 27/30 are image pairs; 0/30 carry a context_management object | 12 runs | aiv_accounting/O12, R |
| aiv_cc: hidden compaction calls and dropped responses | modelUsage = result.usage + 1 hidden call per compaction (input diff = k × compactions, 64/65). 15/211 runs have result.usage below the stream sum, all explained by responses with non-null stop_reason (subset-sum match 12/12) | 211 runs | aiv_accounting/O6, O7, R |
| Entire CLI usage tally equals a tolerance-0 recount of the stored transcript | 4,794/4,836 = 0.9913 [0.9883, 0.9936]; repo-clustered [0.9874, 0.9942] over 183 repos. Prefix snapshots precede the last transcript stamp in 1,664/1,664. **It is a recount of the transcript's own fields**; its only independent content is the commit-time snapshot | 4,836 s | swechat_tables/T1, R |
| After the dataset join fix, unmatched tallies | 33/5,701 = 0.0058 [0.0041, 0.0081]. By CLI version: 0.4.x 11/3,691 = 0.0030 [0.0017, 0.0053]; 0.5.x 15/1,048 = 0.0143 [0.0087, 0.0235]. The fix resolves 31 of 64 raw mismatches | 5,701 s | T3, T4, R |
| Codex cached input is always a multiple of 128 | 16,106/16,106 calls (found post hoc) | 16,106 | T11, R |
| Gemini CLI token total = input + output + thoughts | 5,141/5,141 (`tool` is always 0) | 58 files | raw_census/A6-O9, R (arithmetic a forger satisfies trivially) |

#### 4.2.4 Harness dual renderings and structural gates

| Finding | Numbers [S] | n | Status |
|---|---|---|---|
| Claude Code `toolUseResult.file.numLines` equals the numbered lines of the visible Read result | 87,827/88,229 = 0.9954, W [0.9950, 0.9959], cluster [0.9947, 0.9960], 4,603 files. All 402 mismatches are named formats: 282 persisted-output previews, 105 "shorter than offset" warnings, 7 identical-to references, 7 redactions, 1 negative line number. cc_local main 570/578. **Same writer for both renderings** | 88,229 | raw_census/A6-O1, R |
| Subagent `totalToolUseCount` = distinct nested tool_use ids | 6,623/6,623, W [0.9994, 1.0]. 2,150/8,773 = 0.245 [0.236, 0.254] of Agent/Task results have no nested traffic and cannot be checked | 1,934 files | A6-O2, R |
| Structured counters the IR does not extract | Fill: Read 88,229/90,763 = 0.972, cluster [0.969, 0.975]; Edit structuredPatch 70,553/73,460; Grep numLines 29,535/34,208. Glob totalMatches 0/6,422 in swechat | | A6-O4, R |
| `file-history-snapshot` covers mutated paths | 24,031/24,286 = 0.990 [0.986, 0.993]; 699 files have mutations but no snapshot | 3,737 files | A6-O5, R |
| Claude Code read-before-edit gate | With no prior same-path read, refusal is 244/1,143 = 0.2135 [0.1750, 0.2573]; with one, 128/27,665. 187 edits with no visible read or write still succeed | 1,430 s | sequences/S1, R |
| Ids quoted in model-visible text resolve to the same object | agentId 2,159 match, 0 mismatch (joined on parent_call_id) | | ids/O11, R |
| **Null:** current Claude Code lacks progress and turn_duration records | 0 of 332 cc_local main files; swechat has `progress/agent_progress` in 1,981/4,925 files | | A6-O10, R |

#### 4.2.5 External witnesses (git, wiki, urlquery, narration)

| Finding | Numbers [S] | n | Status |
|---|---|---|---|
| Commit coverage of sessions | 4,085/5,850 = 0.698 [0.686, 0.710] link ≥ 1 ok commit (W; differences by scaffold vanish under repo clustering) | 5,850 s | commit_witness/O1, R |
| Git can constrain part of the CC mutation stream | 47,047/60,170 = 0.782 [0.765, 0.799] of mutation calls in linked sessions can be tested against a commit; linked sessions hold 60,170/88,732 = 0.678 [0.646, 0.707] of all CC mutation calls | 3,057 s | O2, R |
| Edit '+' lines and Write content are corroborated far above decoys | See §1.6: 0.829 against 0.0014; 0.843 against 0.0011 | 40,540; 6,413 | O3, O6, R |
| A commit SHA printed in a Bash result resolves, and its commit_date falls in the call's window | 3,917/3,936 = 0.995 [0.992, 0.998] in 1,491 s; median offset −0.103 s [−0.137, −0.062]. Committed lens sample: 1,351/1,360 = 0.9934 [0.9860, 0.9985], 510 s (LC:commit_witness:`q4.commit_claims.matched_checks`) | 3,936 claims | O9, R |
| Out-of-window commit claims | 19/3,936, W [0.00309, 0.00753] **[D]**. Classified after the fact: 15 re-reads of saved output, 1 explicit GIT_COMMITTER_DATE, 3 unexplained | 14 s | O11, R |
| **Null:** a missing SHA cannot fire alone | 2,198/6,141 = 0.358 [0.321, 0.394] of honest commit claims do not resolve; 853/2,198 of those carry none of the three explaining flags, and the flags are co-occurrences, not verified causes | 1,839 s | O10, R |
| **Null:** `agent_changes` is a copy, not a witness | 84,335/95,892 = 0.879 [0.863, 0.895] match the transcript's own calls exactly | 4,534 checkpoints | O7, R |
| Residual "contradicted-looking" Edits | Contradicted-looking: 5,534 calls in 884 s. After the pre-registered flags (later-commit union, committed content, Bash keyword or basename, REDACTED): 704 in 215 s. Also excluding same-path edits by another session of the checkpoint: 536 in 156 s. Also applying the lens's **post-hoc** edge-substring rule: 148 in 74 s. Without the permissive Bash-basename flag: 1,024 in 276 s. No ground truth exists | 5,534 calls | O5, R |
| Epochs agents print in prose mostly do not postdate the external save, with exceptions | All prose epochs: 7/582 = 0.012 [0.006, 0.025] more than 1 s after the save; median −1 s [−1, −1]. Post-hoc fraction-form subset: 0/459, Wilson hi 0.0083; the non-fraction subset holds all 7, 7/123 | 582 epochs, 285 pages | ext_witness/O10, R |
| Real-clock time-of-day claims sit just before the save that carries them | Median −77 s [−98, −60] (n 738, 242 pages; skeptic's own classifier) | | O8, R |
| urlquery and wiki co-activity is source-specific at day level, not hour-level precedence | Permutation excess 0.332 [0.298, 0.365] (lens; the skeptic reproduces the point). **That CI is page-clustered, which the skeptic says understates uncertainty**: events on different pages share one campaign burst, and source-day clustering (36 clusters) widens the before-window rate to 0.555 [0.094, 0.894]. Against a ±2 h/4 h local null, 0.102 [0.042, 0.181] with source-day clusters; against the preceding hours, 0.030 [0.020, 0.044] | 3,044 events | O3, R (corrected) |
| **Nulls:** directionality, coverage and burst alignment | Forward before-minus-after at 1 h: 0.019 [0.010, 0.027]. DataUSA mentions preceded by a report: 48/1,259 = 0.038 [0.028, 0.049]. Burst alignment local excess: 0.036 [−0.007, 0.077] | | O4, O5, O6, R |
| Round "now" epochs after the save (post hoc, contaminated) | Round 26/54 against non-round 5/331 after the first save; 18/26 come from one label. Needs a holdout | 33 labels | O11, R |
| Narration grounding depends on GUI share | gui_0 0.657 [0.580, 0.728] (86 s) against gui_gt_half 0.286 [0.253, 0.318] (376 s). GUI results carry almost no text, only coordinate strings (the skeptic's row share has no k/n or CI and is not quoted) | | aiv_narration/N5, R |
| Narrated action claims predict the log, but recall is low and the effect is topic-confounded | STOP push asserted against not mentioned: 28/46 against 42/258, +0.446 [+0.297, +0.592]. CONS push 84/103 against 445/1,035, +0.386 [+0.298, +0.466]. Recall: STOP push 24/64, CONS push 70/456. **Holding git use fixed** (sessions that run some other git command): STOP push +0.340 [+0.176, +0.500]; CONS push falls to 76/85 against 386/556, +0.200 [+0.122, +0.271]; **CONS commit +0.126 [−0.006, +0.251], a CI that spans 0** | | N8, R |

#### 4.2.6 Behavioural regularities and distribution features

| Finding | Numbers [S] | n | Status |
|---|---|---|---|
| Block streaming clock: the gap before a tool_use block tracks its argument length | Median 174.7 arg chars/s [171.2, 178.0] (n 77,161, CC). ρ on B: CC 0.809 [0.793, 0.824], cc_local 0.916 [0.834, 0.950], aiv_cc 0.815 [0.766, 0.854] (one agent). The skeptic also finds it on the swechat CC and cc_local A splits (point values, no CI; not quoted). aiv_cc's A split is the same agent's conversation, so it is not a replication. The rate depends on the model (Haiku 397, Opus 168 chars/s; descriptive medians) | 77,161 | correlations/O6, R |
| Errors cluster within sessions, mostly as harness cascades | Within-session lag-1 ρ, swechat: 0.183 [0.158, 0.206], against a permutation null of −0.009. After removing sibling cancellations and interrupts, and keeping only cross-response pairs: 0.041 [0.031, 0.051] | | O9, R |
| A slow model turn predicts a slow tool execution, within tool | Within-tool ρ 0.197 [0.171, 0.223] (swechat, lens; reproduced). aiv_cc 0.194 [0.147, 0.248] (one agent); cc_local 0.183 [0.129, 0.216]. A residual remains in single-call last-block responses in all three CC-family corpora. Near zero in OpenCode and Codex (point values, no CI; not quoted). Unexplained | | O10, R |
| Change points beyond a block-shuffle control in swechat | Sessions with ≥ 1 latency CP: 703/966 against 550/966 under the block-shuffle control; paired excess +0.158 [0.126, 0.190]. This measures non-stationarity, not discrete regimes | 966 s | changepoints/O2, R |
| Latency up-shifts with no harness event mark entry into shell-heavy phases | Shell rises most at 603/745 latency up-shifts (the random-split comparison share has no k/n or CI and is not quoted). Cross-series coincidence latency→tool: 334 observed against 150.3 expected, o/e 2.22 [2.04, 2.41]. Partly mechanical, since latency is per-call tool duration | 745 CPs | O6, R |
| Edit/Write 5.0–5.2 s latency plateau | Edit 644/28,793 = 0.022 [0.011, 0.038] in 73 s; one session holds 176/644. Cause unknown | 73 s | distributions/D4, R |
| Harness output caps | Claude Code failed shell output is cut near 10,040 chars (205/3,237 within 1%; a 5,000-char head and tail); OpenCode at 51,510–51,551 | | D5, R |
| Latency tail and timeouts | Hill α 1.028 [0.975, 1.091] at k = 2% (swechat CC; the CI covers sampling only and α moves with the choice of k, so only α < 2, infinite variance, is robust). Of the top 1% of shell calls, 435/611 run at least 5 s past their own timeout; 535/14,170 = 0.038 [0.031, 0.045] of shell calls reach their timeout argument | 611 | D10, R |
| Numbers the model chooses are round | CC shell timeouts ≥ 600 s: 736/736 are whole minutes. head/tail -n values ≥ 100: 875/878 are multiples of 10. sleep values ≥ 10 s: 709/709 whole seconds, but 71/1,635 of all sleeps are fractional. A top-16 vocabulary covers most of the 14,199 timeout values (share without k/n; not quoted) | 14,199 | D15, R |
| Call→result gaps pile up at ceilings | [120, 122) s: 235 gaps in 99 s; [600, 602) s: 173 in 23 s, with one session holding 105/173. These are partly model-requested timeouts | | outliers/O9, R |
| Retry signature after failures | CC lift 0.202 [0.183, 0.221]; without read-gate anchors, 0.187 [0.168, 0.205]. aiv_cc's lift excluding get_events is 0.240 [0.123, 0.327] (post hoc; one agent, 49 runs; the CI overstates independence) | 1,135 s | sequences/S3, S4, R |
| Verification after the last mutation is the exception | Test after last mutation 450/2,060 = 0.218 [0.193, 0.246] | 2,060 streams | S8, R |
| aiv_cu turn budget | 35,684/78,114 = 0.457 [0.453, 0.460] of sessions have exactly 41 turns. This is a soft cap: 7,024/78,114 sessions exceed 41 turns, up to 326 | 78,114 | D2, changepoints/O4, R |
| Codex reasoning tokens pile onto a lattice at 516 + 518k | 140/6,910 = 0.020 [0.016, 0.028]; cause unknown | 68 s | D1, R |

#### 4.2.7 Important nulls

- **Whether the pre-registered outlier rule beats chance depends on how correlated features are counted.** The rule
  (|z| > 3.5 on ≥ 3 axes) flags 605/2,000 = 0.3025 [0.283, 0.323] of swechat sessions (lens).
  - Per-feature column-permutation null (200 permutations): swechat 605 against 550.1 [529, 571] (above); cc_local 72
    against 98.5 [90, 107] (below); aiv_cc 62 against 60.0 [54, 68] (inside); aiv_cu 606 against 648.0 [623, 671]
    (below); whowhen 13 against 7.2 [4, 11] (above). So 2 of 5 corpora are above; the lens's "4 of 5 not above" was
    wrong.
  - The skeptic's merged-feature null (features with |rank ρ| ≥ 0.7 merged into blocks, ≥ 3 blocks): swechat 577
    against [498, 547], aiv_cu 468 against [364, 405] and cc_local 25 against [1, 7] are all above; whowhen 0 against
    [0, 4].
  - The ≥ 5-axis tail is above the null under the lens's convention (IX outliers/O1, O2, R).
- **No non-mechanical session-level correlation** among the 25 strongest in any corpus (IX correlations/O12, R).
- **Who&When label correlations fail on split A**: −0.380 [−0.532, −0.198] on B against −0.107 [−0.386, 0.185] on A (IX correlations/O14,
  R).
- **aiv_cu change points.** The lens called this a null. The skeptic corrected it: a small but real excess over the
  block control in 5 of 7 series, e.g. latency +0.101 [0.055, 0.155]. The contrast with swechat is mostly a series-length
  effect (IX changepoints/O3, R).
- **Token conservation tails do not shrink** with model-aware fits or with an image split (IX TC14, TC10, R).
- **No timestamp quantization**: ms field 000 in 0.00096 [0.00087, 0.00104] of swechat CC stamps (IX distributions/D16,
  R).
- **aiv_cu `updated_at` is not a second clock**: 59,834/59,956 rows within 0.01 ms (IX D6, R).
- **Who&When has no clock field at all** (IX raw_census/A6-O11, R).
- **`has_been_asked_to_stop` is constant**: False in 2,200/2,200 sampled sessions (IX aiv_narration/N11, R).
- **Narration contradicted by logged failures**: 0/12 opportunities claimed (Wilson hi 0.243). This null has no power
  (IX N6, R).

#### 4.2.8 Artifacts that look like findings (do not build on these)

| Looks like | Is actually | Source |
|---|---|---|
| Orphaned results and a 10 KB cap in SWE-chat | `conversations.parquet` keeps only the last record per message.id: dropped 76,349/407,920 = 0.187 [0.181, 0.193]; builder tool_call_count equals last-record ids in 4,834/4,847. The cap is absent from raw transcripts | swechat_tables/T5, R; §2 A2/A3 |
| Results before their call; negative gaps | File order is not time order: 40,243/855,208 = 0.047 [0.044, 0.050] of CC consecutive gaps are negative; 57 results precede their call in the file with consistent stamps | distributions/D8, sequences/S10, R |
| Native-error rate differences | `is_error` is written for every built-in Bash result but for non-shell results only when true, so error rates track shell share | correlations/O1, R |
| Output-token signals | Logged per-row output_tokens are streaming snapshots: the per-response maximum usage_out is exactly 1 in 26,780/158,061 swechat CC responses and 21,932/35,463 aiv_cc responses (LC:distributions:`profiles.<unit>|usage_out.small_values_top5`) | D11, TC6, correlations/O2, R |
| Subagent turnaround and fan-out effects | gap_input contamination across interleaved streams, plus sibling-result interleaving | correlations/O3, O11, R |
| aiv_cu per-call latency | One `created_at` per turn, so lat = 0 for 59,956/59,956 | correlations/O4, R |
| Outlier clusters | Format plus one repo (nimbus is 175/214 of B opencode sessions); the cc_local template (92/186 sessions, 0 outliers); the 41-turn mode; a loader-made n_models; failed-resume rows; compaction as an automatic extreme axis | outliers/O3, O4, O5, O7, O8, O16, R |
| Change points everywhere | The binary-segmentation detector is over-sensitive under AR(1): at ρ 0.3 the simulated false-positive rate is 0.343–0.407 (300 simulated series per cell; simulation estimates, no CI). A pandas µs-resolution bug was fixed | changepoints/O1, O15, R |
| cc_local "empty thinking" | 19,026 of 29,011 clean pairs have a zero-char thinking-only block, but they come from only 21 of the 137 sessions with thinking blocks, and a top 5 of those sessions hold nearly all of them (share without k/n; not quoted). It is a few-session phenomenon, not a corpus property | TC7, R |
| A REDACTED uuid or duplicated checkpoints | One `REDACTED` uuid in 197 OpenCode sessions; checkpoint rows duplicated across forked repos, 3,650/13,406 | ids/O16, swechat_tables/T9, R |
| Codex counter chain "jumps down" | Duplicate token_count events and compaction; the total decreases in 0/615 breaks | raw_census/A6-O7, R |

**Not reproduced: 14 observations, never used as support.**
- ext_witness/O12: URL epochs postdating saves.
- commit_witness/O4: mechanical causes of contradicted Edits.
- distributions/D9: bash_progress jitter of 0–4 ms. The 1 Hz tick holds; the jitter claim was wrong.
- distributions/D12: "identical" polling outputs. They are not identical.
- distributions/D17: featureless-profile tallies.
- changepoints/O7: "0 unexplained context drops". The skeptic found 12.
- sequences/S16: restart compliance by API shape. A tokenization artifact.
- aiv_narration/N3: summary never produced by the STOP call. Headline count wrong.
- aiv_narration/N7: claimed-but-absent as common for unrelated narration. Overclaimed null.
- two_clocks/O13: the Codex yield-cap count.
- token_conservation/TC3: tool-aware thresholds at FPR 1%. Realized FPR is up to 0.0364.
- token_conservation/TC8: redaction as a natural tamper experiment.
- ids_and_clocks_in_ids/O12: references to never-issued ids. A regex artifact.
- ids_and_clocks_in_ids/O15: "0 duplicated call ids in every corpus". Guaranteed by construction in aiv_cu.

**Unchecked: 25 observations, reported in `_index.json` and not relied on here.**
- ext_witness O13, O14.
- raw_census A6-O13, A6-O18.
- swechat_tables T15, T16, T17, T18.
- commit_witness O14, O15.
- aiv_accounting O14–O19.
- distributions D20.
- correlations O17, O18.
- two_clocks O19–O22.
- ids_and_clocks_in_ids O18, O19.

### 4.3 The five proposed mechanisms, ranked (provisional)

**Where they come from.** Three proposal lenses (power, robustness, coverage) produced 15 proposals (5 each). All 15
passed a grounding check that verified every citation and number against `_index.json` and listed overclaims (PG).
Independent rankers merged them into five and ranked them on four criteria, in order (RK `criteria_order`):
- (a) measured separability or tamper power on honest data;
- (b) a witnessed quantity the agent cannot see, or that is costly to recompute;
- (c) measured coverage;
- (d) cost to build next.

**Provenance of the ranking.** The rank order is interpretation, and it lives only in the uncommitted Phase D files
(caveat 8). This report therefore quotes no ranker-level vote counts. The order of ranks 2 and 3 was contested among
the rankers and was resolved on criterion (a) (RK `disagreements` D1). Two parts were dropped (RK `ranker_inputs`):
- the D7 usage_in mode and D1 reasoning "lattices", which are not lattices per the grounding check (PG);
- the cache "stopwatch", which long-gap breaks contradict (8/32, IX aiv_accounting/O9).

**Why "provisional".** Rank 1 leads on criterion (a) only through a tamper response that comes from uncommitted code
and is withheld here. **On committed evidence alone, rank 2 leads on (a)**: it has the cleanest honest separation and
the only split-A replication by a committed script. If the withheld placebo is not reproduced by a committed script,
rank 2 moves to first (Step 0 below).

**All five are untested as detectors.** None has a committed single-response tamper measurement of its own witness.
Rank 1's back-date placebo is uncommitted and withheld. Rank 5's content leg borrows TC2, token conservation's
single-result insertion curve, which belongs to a different mechanism. Ranks 2–4 have no tamper measurement of any
kind. Every honest rate below is in-sample on B or on the population. Every novelty line is an **UNVERIFIED guess**;
prior art is checked separately, and nothing here claims a mechanism is new.

#### Rank 1. Provider-minted request-id clock bracket

**What it is.** A per-stream skew bracket and a single-response binding test on decoded Anthropic request ids. The
inter-request ceiling and the aiv_cu Gemini HTTP-header window are kept as unmeasured extensions.

**Merged from:** power#1, robustness#1, coverage#1, coverage#4.

**Observation.**
- **Honest rate**: 10/3,674 swechat Claude Code streams are inconsistent, session-clustered 0.00272 [0.00112, 0.00466]
  at 2 s tolerance (IX ids/O5 [S]). Tolerance 0 s gives 18 and 5 s gives 7.
- **Width.** In consistent streams the bracket width U−L is p5 1,102 / p50 2,268 / p95 3,807 ms (descriptive).
- **Committed-script copy:** 10/3,676, same CI, 1,610 s (LC:ids_and_clocks_in_ids:
  `bracket.swechat.anthropic_req.claude_code`). Of the 10 inconsistent sessions, 2 hold re-stamped resume/fork copies
  and 8 are unexplained.
- **cc_local**: 1/847, W [0.000208, 0.00666] [D].
- **Clock decode and agreement.** 154,815/154,815 swechat ids decode as v7, against 2,418.98 expected by chance; the
  layout is UNVERIFIED against documentation. Clock agreement counting every copy is 0.99871 [0.99676, 0.99992] in
  1,638 s. Holdout A: 11,047 ids, 0 violations.
- **Coverage gaps.** aiv_cc stores 0 request ids. The aiv_cu brackets show 0 inconsistent Anthropic and Gemini streams
  and 3/463 OpenAI, but they are weak by construction. Gemini server-timing fits inside the row gap in 0/12,292 rows.
- **Tamper response: withheld.** A skeptic placebo (back-dating or late-stamping one response's first event) was run on
  3,673 swechat streams by uncommitted scratch scripts (o5.py, o5b.py, o5c.py). Its counts survive only as text in the
  committed `_index.json` (ids/O5 `skeptic_numbers`) and in RK `computed.decisive_numbers.placebo_*`. The committed lens
  script writes no placebo. Under rule 1, and under this ranking's own Step 0, **this report does not quote those
  counts.** An all-response id roll was run by the same uncommitted code. It misbinds every response at once and is not a
  single-response test.

**Test measurement (plan, not measured).**
1. **Pre-register before running.** Tolerance 2 s. Honest rates fixed at 10/3,674 (swechat CC) and 1/847 (cc_local).
   Session-clustered CIs. One row per tamper type, never pooled.
2. **Step 0.** Commit the placebo as an `analysis/probes` script and re-run it on the same streams. Only then may the
   back-date counts be cited.
3. **Step 1: single-response tampers**, on swechat CC B, holdout A and cc_local. None has been measured yet:
   - splice one response with a request id from another session, or from later in the same session;
   - swap two adjacent responses' ids;
   - delete one response;
   - insert one fabricated call+result round;
   - delay one tool_result by D in {1, 2, 5, 30, 300} s with every id untouched, plus the consistent variant that shifts
     that result and all later client events.
4. **Step 2: back-date grid** from 1 to 30 s. Report D at power 0.5 and 0.9, next to the U−L p50 of 2,268 ms.
5. **Kill rule, fixed now.** A tamper type whose flagged-stream rate has a session-clustered lower bound at or below the
   honest upper bound is a null for that type. The honest upper bound is 0.00466 for swechat CC and 0.00666 (Wilson)
   for cc_local. If no single-response type clears it, the line becomes "back-dating only" and stops.
6. **Extensions, only after Step 1:**
   - an inter-request ceiling S = t_req(k+1) − t_req(k) against client duration claims, reporting the honest slack per
     timer type first;
   - an aiv_cu Gemini window w = created_at − HTTP Date, with positive controls (pause, explicit sleep).
7. **Split hygiene.** The cleanest test set is cc_local sessions recorded after the Phase C commits.

**False-positive sources (measured).**
- **Honest inconsistency.** 10/3,674 inconsistent streams (18 at 0 s, 7 at 5 s), of which 8 sessions are unexplained.
  cc_local 1/847.
- **Re-stamped copies.** Resume/fork copies collapse history onto 1–2 timestamps (2 session pairs, 178 request ids) and
  must be deduped (ids/O7).
- **Client clock steps.** A constant skew does not absorb them: drift > 2 s in 15 swechat sessions and in 2 of 18
  cc_local sessions (ids/O6).
- **Unexplained zero gaps.** 329 v2.1 same-millisecond call/result pairs have no established cause (two_clocks/O12).
- **Coarse clocks.** OpenAI and Gemini ids and the HTTP Date have 1 s resolution: OpenAI shows 3/463 inconsistent
  streams, and the HTTP Date orders unambiguously in only 2,831/3,246 flash and 7,276/8,990 pro rows (D19).
- **Ceiling leg.** Async launches return before their work ends: cc_local 63/63 (two_clocks/O15).

Unmeasured: provider-side skew between consecutive ids, retries, concurrent subagent streams.

Blind spots by construction, not false positives:
- late-stamping;
- compression of a call→result gap inside one round (reasoning, not measured);
- in-band fabrication, which the harness stamps consistently;
- content substitution;
- any editor who re-mints ids. The ids are unsigned, and a forger can infer the layout from data just as this lens did.

**Novelty guess: UNVERIFIED, do not claim novel.**
- Reading time out of UUIDv1/v7, ULID or Snowflake ids is known forensics.
- Bounding an event between causally ordered stamped events matches the Gladyshev & Patel event-time-bounding line. That
  link is the grounding skeptic's own unverified recollection (PG `lenses[0].ground.checks[0]`).
- If anything is new, it is narrow: using LLM-provider request ids as the external bound on agent tool-log stamps and as
  a response-binding test.

**Why this rank. Interpretation.**
- **(a)** Its own witness has a measured honest rate from committed code. Its tamper response comes from uncommitted
  code and is withheld, so on committed evidence alone it does not lead on (a). **The rank is conditional**: if the
  committed Step-0 re-run does not reproduce the 5 s back-date point, rank 1 loses its (a) lead and rank 2 moves to
  first (RK `final_ranking[0]`, D6). The grounding check also notes that "only measured tamper curve" is false: TC2 has
  one, for token conservation (PG `lenses[0].ground.checks[0]`).
- **(b)** When the provider mints the id is inferred, not observed: the request-id time precedes the client event stamp
  by a median 3,781 ms [3,684, 3,871], and the id layout itself is UNVERIFIED. That the model never sees the id is
  reasoning, not observation. The id is unsigned and re-mintable, so it binds only post-hoc retiming and misbinding,
  one-sidedly and per turn.
- **(c)** It covers Anthropic-backed Claude Code only: 155,267 (session, request) pairs in 1,638 swechat sessions, plus
  847 cc_local streams. The share of tool calls covered is unmeasured.
- **(d)** It is the cheapest next step. The lens code is committed; the placebo code exists but is not committed.

#### Rank 2. Provider image-token ledger

**What it is.** A per-window screenshot count from Gemini prompt IMAGE units, with the aiv_cc stripped-image residual as
a one-agent case study.

**Merged from:** power#4 (image part), coverage#5, robustness#5 (image part).

**Observation.**
- **Split B** (IX TC9 [S]). The per-window change in prompt IMAGE tokens is 0 or exactly one per-model unit in
  11,668/11,668 pairs (258 for 2.5-pro; 1,064 for the 3.x models).
- **GUI windows**: positive in 5,059/5,092. Misses 33/5,092, W [0.00462, 0.00909] [D].
- **Non-GUI windows** (committed lens table, LC:token_conservation:
  `aiv_cu_gemini_text_image.dIMAGE_positive_by_top_tool`): shell 0/4,134, get_pixel_coords 0/2,033, pause 0/202,
  send_message_back_to_chat 0/324, and the five small rows search_history 0/79, None 0/54, view_clipboard 0/23,
  move_to_room 0/2 and request_google_sign_in 0/2. In total 4,134 + 2,033 + 202 + 324 + 79 + 54 + 23 + 2 + 2 = 0/6,853,
  W [0, 0.00056] [D]. The committed file stores no per-session counts, so these intervals treat windows as independent.
- **Lattice**: {258, 1,064, 2,160} in 10,569/10,569 pro rows; 0/309 sessions mix lattices (D3).
- **Split A**, from committed Phase A output written before any Phase C lens read B (A5
  `part2.aiv_cu/gemini-*.gemini_modality`). The stored session-clustered intervals are degenerate at 0 and 1, so the
  Wilson bounds are added here as arithmetic on the k/n shown [D]:
  - gaps holding a GUI result: pro 417/420 = 0.9929 [0.9840, 1.0] (18 s; stored interval); flash 191/191 (12 s; stored
    [1.0, 1.0]; Wilson [0.9803, 1.0000] [D]);
  - gaps without one: pro 0/309 (19 s; stored [0, 0]; Wilson [0, 0.0123] [D]) and flash 0/320 (17 s; stored [0, 0];
    Wilson [0, 0.0119] [D]).
- **aiv_cc, one agent** (aiv_accounting/O11): residual per stripped image 890.1 [887.9, 890.9], n 4,543 pairs in 64 runs.
  227 of them fall in the 316–562 bin, below the honest per-turn |residual| p99 of 690.2. Single-image power is
  therefore below 1, and unmeasured.

**Test measurement (plan).**
1. Fix the rule on split A, where it is already measured: dIMAGE = (screenshot-returning actions in the window) ×
   unit(model generation).
2. Tamper honest B windows four ways:
   - delete one GUI result;
   - relabel a GUI action as shell;
   - insert a fabricated screenshot-returning call and result, with usage untouched;
   - splice in a window from another session.
3. Report detection per tamper type with session-clustered CIs. Report a session-level honest flag rate, which no file
   states yet.
4. Run the regime above 40 images. 442 population Gemini sessions exceed 40 GUI turns; no B session does.
5. aiv_cc: add or remove one `[IMAGE_REMOVED]` marker, and report power at FPR 1%.
6. **Kill rule, fixed now:** a session-level honest flag rate above 0.05 stops the line.

**False-positive sources (measured).**
- **Unexplained misses.** 33/5,092 GUI windows show no increment. They are not cap effects: images before median 4,
  max 31.
- **Model-dependent unit.** The unit varies with model generation, and 2,160 appears in 70 rows from 3 sessions.
- **No images at all.** gemini-3.8-flash (277 pairs) never shows an image.
- **Cached counts are unusable.** Cached IMAGE counts are off-lattice.
- **Untested regime.** Above 40 images is untested.
- **aiv_cc resets.** aiv_cc has 30 unlogged context resets, 27 of them on image pairs.
- **Variable image size.** User-pasted images vary: the swechat CC single-image residual has p5–p95 121–1,618.
- **Compounding.** Per-window misses compound at the session level; this is unmeasured.

**Novelty guess: UNVERIFIED, do not claim novel.**
- Token-count plausibility checks are generic billing practice.
- The coverage grounding check calls the ledger an extension of our own Phase A conservation plan.
- Using a provider's per-modality token breakdown as an exact count of screenshot-returning results may be undescribed.
  That is a guess.

**Why this rank. Interpretation.** Its order against rank 3 was contested among the rankers and resolved on criterion
(a) (RK `disagreements` D1; no vote counts are quoted, caveat 8).
- **(a)** It has the cleanest honest separation of the five, and the only one replicated on held-out data by a committed
  script that predates Phase C. On committed evidence alone it leads all five on (a). No tamper simulation exists, so
  its detection power is arithmetic, not measured.
- **(b)** It counts images and never speaks to their content. A live forger who returns a real or fake screenshot gets a
  real increment.
- **(c)** Its coverage is the narrowest: aiv_cu Gemini, with Gemini rows in 347 of 2,000 B sessions. But that is exactly
  where Probe 1 is NOT_TESTABLE, Probe 2 is INCONCLUSIVE and the Probe 3 tail is DEAD.
- **(d)** It is cheap: TC9 already computes it.

#### Rank 3. Git execution window

**What it is.** A commit SHA printed in a tool result must resolve, and its commit_date must fall inside the printing
call's call→result window. Fresh generator-printed readings and printed durations are unmeasured extensions; the
harness-timer legs are demoted to internal consistency checks.

**Merged from:** power#3, robustness#3.

**Observation** (IX commit_witness/O9, O10, O11, O1 [S]).
- **In window**: 3,917/3,936 = 0.995 [0.992, 0.998] in 1,491 s; median offset −0.103 s [−0.137, −0.062]. Committed lens
  copy: 1,351/1,360 = 0.9934 [0.9860, 0.9985], 510 s.
- **Out of window**: 19/3,936, W [0.00309, 0.00753] [D]. Classified after the fact: 15 re-reads, 1 explicit committer
  date, 3 unexplained.
- **Non-resolution**: 2,198/6,141 = 0.358 [0.321, 0.394], so a missing SHA cannot fire on its own.
- **Coverage**: 4,085/5,850 = 0.698 [0.686, 0.710] of swechat sessions link an ok commit.
- **No held-out replication exists.**
- **Fresh readings** (collusion-wiki only): post-hoc fraction-form subset 0/459, but all prose epochs 7/582 = 0.012
  [0.006, 0.025] after the save (ext_witness/O10).
- **Timer legs** (same-clock redundancy): bash_progress 0/112,677; Codex Wall time 0/4,408 on exec_command, against
  646/1,817 rounding exceedances on shell_command.
- **Never extracted**: the printed-duration leg.

**Test measurement (plan).**
1. **Split hygiene first.** Fix the generator vs re-reader command classes on one half of the commit-linked sessions and
   test on the other. The 15/19 classification was made on the full population.
2. Measure the share of all tool results that carry a resolvable SHA or a fresh reading. **Stop rule:** if that share is
   too small to matter, report it and stop.
3. Measure the honest out-of-window rate per command class, with session-clustered CIs.
4. Tamper:
   - replay a real commit-bearing output into a later call, and into another session of the same repo;
   - fabricate a SHA, and compare with the honest 0.358 non-resolution rate;
   - shift a commit call's stamps across a delta grid.
5. Printed-duration leg, only after step 2: pre-register regexes on split A, then run a lying-backend simulation and a
   padded backend.

**False-positive sources (measured).**
- **Re-reads of saved output**: 15 of the 19 out-of-window claims.
- **Explicit committer date**: 1.
- **Unexplained**: 3.
- **Auto-backgrounded commands**: 111 of 188 swechat 120 s shell results (outliers/O9).
- **Zero-width windows**: 329 unexplained gap-0 pairs (two_clocks/O12).
- **Display rounding**: Codex shell_command (two_clocks/O6).
- **Stale identifiers**: stored ids echoed by tools are not fresh, 440 of 561 v7 mentions (ids/O14).
- **Non-resolving SHAs** (0.358 of honest claims) must abstain, not fire.

**Novelty guess: UNVERIFIED, do not claim novel.**
- The grounding checks call it partly prior art: a claim-vs-record existence check overlapping our own git shadow-state
  plan, event-time bounding, and output-grammar parsing (jc).
- The possibly new part is bounding non-recomputable outputs by the log's own call window.

**Why this rank. Interpretation.**
- **(a)** In-window 0.995, but the exceptions were classified after seeing them, there is no held-out replication, and no
  tamper response has been measured.
- **(b)** It is the strongest witness of the five, by reasoning: commit_date is hashed into a SHA held in an external
  repo. It is also the only leg that tests result content against an external record.
- **(c)** It is narrow: Entire-linked swechat CC only.
- **(d)** Moderate.
- **Condition.** If criterion (b) were placed first, this would move to rank 2.

#### Rank 4. Harness dual-rendering recount

**What it is.** Claude Code `toolUseResult` structured counters (Read numLines, subagent totalToolUseCount, Edit and Grep
counters) checked against the model-visible result text.

**Merged from:** power#2, coverage#3.

**Observation** (IX raw_census/A6-O1, O2, O4, O10 [S]).
- **Read numLines**: 87,827/88,229 = 0.9954, W [0.9950, 0.9959], cluster [0.9947, 0.9960] over 4,603 files. All 402
  mismatches are named formats.
- **cc_local main**: 570/578 = 0.986 [0.973, 0.993]. All 8 mismatches are empty-file warnings.
- **Subagent count**: totalToolUseCount 6,623/6,623, W [0.9994, 1.0]. 2,150/8,773 = 0.245 [0.236, 0.254] of Agent/Task
  results cannot be checked.
- **Committed-script sample**: 2,510/2,514 (`out/phase_a/a6_raw_census.json`).
- **Version drift**: current Claude Code has no progress entries (0 of 332 cc_local main files).

**Test measurement (plan).**
1. Freeze the whitelist now. Measure the honest unexplained rate only on data the whitelist was not derived from. The
   existing 0 is in-sample.
2. Tamper clean Read results:
   - add or delete 1, 2 or 5 lines;
   - splice a same-path Read from another session;
   - count-preserving substitution (expected invisible);
   - rewrite a result into a whitelisted format, to measure the whitelist as an evasion route.
3. Do the same for totalToolUseCount.
4. Measure agreement, not fill, for Grep numLines and for Edit structuredPatch.
5. This needs a loader change, decided by day.

**False-positive sources (measured).**
- **The 402 swechat format mismatches and 8 cc_local warnings.** A detector without the whitelist fires on all of them.
- **The whitelist as an exemption.** It exempts any result an editor rewrites into those formats.
- **Version drift.** Glob totalMatches is 0/6,422 in swechat against 1,231/1,234 in cc_local.
- **Abstentions, not passes.** 2,150 Agent/Task results cannot be checked and must count as abstentions.

**Novelty guess: UNVERIFIED; probably not novel as a technique.** Consistency between redundant fields is a generic
integrity idea. The two grounding checks disagree on overlap.

**Why this rank. Interpretation.**
- **(a)** It has the largest-n exact agreement of any proposal, but "0 unexplained" is in-sample, and no tamper response
  has been measured.
- **(b)** It is the weakest witness: one harness writes both renderings. It catches naive post-hoc text edits and export
  faults only.
- **(c)** Claude Code formats only.

#### Rank 5. Usage-ledger reconciliation

**What it is.** The commit-time Entire usage tally frozen in git, plus parameter-free provider usage identities: the
cache-append chain, with Codex's 128-token cache granularity as a post-hoc note.

**Merged from:** power#5, robustness#2, coverage#2, robustness#4, and the 128-token rule from power#4/robustness#5.

**Observation** (IX swechat_tables/T1, T3, T4, T11; token_conservation/TC1, TC2, TC16; aiv_accounting/O9 [S]).
- **Tally**: equals a tolerance-0 recount in 4,794/4,836 = 0.9913 [0.9883, 0.9936]; repo-clustered [0.9874, 0.9942].
- **Unmatched after the join fix**: 33/5,701 = 0.0058 [0.0041, 0.0081]. By CLI version: 0.4.x 0.0030 [0.0017, 0.0053];
  0.5.x 0.0143 [0.0087, 0.0235].
- **Cache-append chain**, exact in clean pairs (committed lens,
  LC:token_conservation:`fmt.<unit>.cache_chain_exact_clean`): swechat CC 138,320/141,477 = 0.978 [0.975, 0.980] (1,638 s); cc_local
  28,160/28,668 = 0.982 [0.980, 0.990] (174 s, few-session dominated); aiv_cc 32,279/32,310 = 0.99904 [0.99847,
  0.99946] (one agent). The skeptic's independent pipeline reproduces these (IX TC1; point values only, not quoted).
  On the full aiv_cc stream: 59,747/59,804, run-clustered 0.99905 [0.99858, 0.99943] (aiv_accounting/O9; one agent, so
  the run-clustered CI overstates independence).
- **Codex cache granularity**: a multiple of 128 in 16,106/16,106 calls (post hoc).
- **Content binding** comes only through token conservation: inserted-text power 0.5 / 0.9 at 8,913 / 10,000 chars in
  swechat CC, at realized FPR 0.0101 [0.0092, 0.0112] (TC2; simulation grid points). Deleting a [100, 1,000)-char
  result has simulated power 0.003 over 61,269 deletions (TC16). This leg belongs to token conservation, not to the
  tally.

**Test measurement (plan).** On the 5,701 swechat sessions with a tally:
- delete one assistant message.id inside the snapshot;
- insert a copied message.id;
- append after the snapshot (expected invisible);
- insert a tool_use into an existing message.id (expected invisible);
- edit result content (invisible to the tally).

Report detection per tamper against the honest 33/5,701. Characterize honest per-session cache-chain breaks before any
session-level use.

**False-positive sources (measured).**
- **Honest mismatches**: 33/5,701, 6 of them in one repo, higher in CLI 0.5.x.
- **Dataset join artifact**: it must be fixed first.
- **Duplicated checkpoints**: 3,650/13,406 checkpoint rows.
- **aiv_cc chain breaks**: at compaction, on image pairs, and at long gaps (8/32).
- **Unlogged resets**: 30 in aiv_cc.
- **SDK-version-dependent omissions**: of non-null stop_reason responses (15 of 211 runs).
- **Hidden-content tools**: ToolSearch, residual +897.4 [742.2, 997.6].

**Novelty guess: UNVERIFIED, and mostly listed prior art** per the grounding checks:
- hash-chain sealing;
- capture-side tooling;
- standard audit reconciliation;
- prompt-cache auditing (Gu et al. 2025; relevance UNVERIFIED).

**Why this rank. Interpretation.**
- It constrains which turns exist, not what the results said.
- An editor can redo the tally. The git anchor is rewritable until pushed, and push time is not in the data.
- It carries the heaviest prior-art overlap.

### 4.4 Which to build first, and why (Interpretation)

**Build rank 1 first, conditionally, scoped as a post-hoc retiming and response-binding check, not as a fabrication
detector** (RK `build_first`). The condition is Step 0: on committed evidence alone, rank 2 leads on criterion (a).

**Order of work.**
1. **Step 0.** Commit the skeptic's placebo as an `analysis/probes` script and re-run it. If the re-run does not
   reproduce the 5 s back-date point, build rank 2 first instead.
2. **The single-response tamper suite** of §4.3, rank 1, on swechat CC B, holdout A and cc_local, with session-clustered
   CIs and one row per tamper type.
3. **The kill rule fixed in §4.3**, applied against the honest upper bound: 0.00466 for swechat CC, 0.00666 for
   cc_local.

**Why rank 1.**
- It can fail cleanly against a stated rule on the next run: it has a committed honest rate, committed lens code and a
  kill rule fixed now. Rank 2 also has a kill rule fixed now (§4.3, rank 2, step 6), so this is not unique to rank 1.
- Its tamper harness exists (uncommitted). If Step 0 reproduces the back-date point, rank 1 is the only proposal with
  a measured tamper response of its own witness; if not, rank 2 goes first.
- It runs on the corpora where Probe 1 is ALIVE (cc_local) or WEAK (swechat CC). Those timing verdicts depend on the
  stamps the bracket checks.

**Limits stated up front.**
- It is blind to in-band fabrication and to late-stamping.
- By reasoning, it is also blind to compression of a call→result gap inside one round. That is how an editor would hide
  an inline-generated result from Probe 1.
- It binds only editors who do not re-mint ids.

**Second, in parallel if capacity allows:** rank 2's tamper suite on aiv_cu Gemini. It is cheap, and its separation
already replicates on split A. If the priority is binding result content to an external record, rank 3 goes first,
gated on its coverage-share stop rule.

**Relation to Phase B (Interpretation; RK `relation_to_phase_b`).**
- **Different threats.** Probes 1–4 test behavioural signs that the producer fabricated a result. The five proposals are
  mostly log-integrity witnesses against post-hoc edits. Only rank 3's git leg tests a result's content against an
  external record.
- **No cross-validation.** No proposal revives a DEAD probe cell, and no probe verdict is confirmed by Phase C, because
  both read split B.
- **Rates are not comparable.** The proposals' low honest rates belong to structural identities a schema-aware editor
  can satisfy. The probes' rates belong to behavioural signals a fabricator must work to avoid. An honest rate is not a
  detection rate.

---

## 5. What we could not measure, and why

This section collects every `could_not_measure` list, every NOT_TESTABLE, INSUFFICIENT_N or killed line, and every open
loader problem. The sources are:
- `out/phase_a/verification/verify_a{1..6}*.json` (`measurer_summary.could_not_measure`), cited as verify_a`<n>` [i];
- PV `probes[*].res.could_not_measure`;
- `out/phase_c/_verification_{early,ir}.json` (`lenses[*].obs.could_not_measure`), cited as `<lens>` [i];
- `out/phase_a/a6.json` (`part2_parser_surprises`).

An earlier draft of this section omitted about forty of these items. This revision adds every item the completeness
audit listed, each with its source index. The only `could_not_measure` entries deliberately left out are the lenses'
notes that they spawned no subagents (ext_witness [7], aiv_accounting [9]), which are process notes, not measurement
gaps.

### 5.1 No ground truth for fabrication: the gap behind every number

- **No corpus labels a fabricated tool call or result.** Who&When labels mistakes only. So no probe and no Phase C check
  has a measured detection rate, miss rate, or false-positive rate against real fabrication. Every number in this report
  is an honest-baseline property.
- **Probe 1** cannot measure its miss rate. A fabricator generating faster than G90, or with a smaller model, could land
  at r < 1 (PV probe 1).
- **Probes 2 and 4** have no positive control. The deviation a fabricator would produce is unknown (PV probes 2 and 4).
- **Probe 3** cannot tell whether the zero-error flag survives an adversary who fabricates plausible errors (PV probe 3).
- **Synthetic injection.** Only two kinds were run:
  - token conservation (TC2, TC16), from a committed lens with a skeptic re-run;
  - the rank-1 placebo, from uncommitted code and withheld here.

  The usage tally (`swechat_tables`), every harness-timer identity (`two_clocks`: "whether a forger would actually break
  any identity is untested"), the image ledger, the commit window and the dual rendering have never been tampered with.
- **Undetectable by construction:**
  - substitutions that preserve token count, or length within the honest residual (token_conservation);
  - count-preserving content substitution (rank 4);
  - late-stamping and in-band fabrication (rank 1).

### 5.2 Timing that cannot be measured

| What | Why | Source |
|---|---|---|
| Per-action latency in aiv_cu | One stamp per turn for call and result: 59,956/59,956 in B | PA:A1.verdict.aiv_cu; P1 |
| Any timing in Who&When, SWE-chat cursor, simple_text | No timestamps, or no pairs | PA:A1 |
| Shell, edit, write and web latencies in the Claude Code formats | `permissionMode` is in the raw entries but not in the IR, so human waits cannot be separated from work; the loader change was not made | verify_a1; PR §7; P1 |
| Whether OpenCode time.start/end include permission-prompt waits | Not in the data | verify_a1 |
| cc_local hook durations | No hook_progress events and no hook start marker | verify_a1; two_clocks lens |
| Server timing for any aiv_cu model other than Gemini | Only Gemini rows carry it, and none before 2025-12 (a6 open surprise). It covers 347 of 2,000 B sessions | verify_a1; two_clocks/O7 |
| Codex AUC; Gemini AUC | Codex has no generation-bound tool (G = 0); Gemini G is 13 pairs from 5 s | P1 |
| Cause of the swechat CC floor steps, the Edit 5 s plateau, and the latency tail beyond timeouts | No hook-config, IDE, environment or permission-wait fields in the IR | PV probe 1; distributions lens |
| Sub-second order against the Gemini HTTP Date | The header has 1 s resolution | distributions lens |
| aiv_cc event order against a parent chain | parent_uuid is null on all 113,144 IR rows; no progress or hook data | verify_a1; aiv_accounting lens |
| Codex per-call usage | token_count rows are not linked to calls in the IR | correlations lens |
| Stable latency baselines outside Claude Code | 10–25 A sessions per format; copilot 2 | verify_a1 |
| Web-tool G pairs without a duration | 1,163 swechat CC and 1,082 cc_local webfetch/websearch pairs carry no tool-reported duration and were excluded from G | P1 `separability.G_usable.excluded`; `notes/probe_1.md` §7 |
| aiv_cc run durations as an independent check | Result-row duration_ms and duration_api_ms were copied from the aiv_accounting lens, not recomputed | two_clocks [1] |
| cc_local cost-state timing | Only B root files were read: 68/186 had cost-state. Whether the 900 s constant depends on version or launch mode is uncharacterized (private corpus) | two_clocks [3] |
| Cause of the one OpenCode bash overrun | 205,775 ms against a 120,000 ms timeout, exit 0; OpenCode has no tick stream to test for a suspend | two_clocks [4] |
| 3 cc_local cost-state records that end before the file's last event | Whether they are mid-file writes of resumed sessions is untested | two_clocks [5] |

### 5.3 Context the record does not hold, so "unsourced" is an upper bound everywhere

- **Claude Code**: CLAUDE.md, the system prompt, the cwd, prior or resumed sessions, compaction content, the content of
  spilled outputs (only the preview is logged), and the expanded ToolSearch schemas. The IR keeps text blocks only
  (PR §7; verify_a3; TC4).
- **Spilled outputs in every format**: the content of CC `tool-results/*.txt` and of the OpenCode, Gemini and Copilot
  tool-output files is not in the IR, so how much a preview hides is unknown beyond the size its marker states
  (verify_a3 [1]).
- **Gemini CLI masking**: 840/2,313 A results are masked. Whether the model saw the unmasked output first cannot be told
  (verify_a3).
- **aiv_cu**:
  - Screenshots are not exported; GUI results carry almost no text, only coordinate strings (N5).
  - There is no prompt, memory or user text in the IR.
  - The summarization call behind STOP summaries has no logged prompt, model or tokens.
  - `agent_memories.jsonl.gz` (2.4 GB) was not read (aiv_narration lens).
- **aiv_cc**: earlier runs are other IR sessions. Images (`[IMAGE_REMOVED]`) and thinking signatures (`[BLOB_REMOVED]`)
  are stripped, so image content and thinking authenticity cannot be checked (aiv_accounting lens).
- **Codex**: which part of a truncated output the model saw is unknown, so edits inside the truncated region are a
  blind spot (token_conservation lens).
- **Probe 4**: "unsourced" hex is an upper bound on "invented". Prefix-sourcing sees only earlier tokens of length
  7/8/32/40/64 (PV probe 4).

### 5.4 Error signals that cannot be validated

| What | Why | Source |
|---|---|---|
| aiv_cu error precision and recall | No reference flag. The stderr proxy is unvalidated, which caps aiv_cu at WEAK | verify_a4; PV probe 3 |
| whowhen Hand-Crafted errors | No failure signal (DEAD by prereg) | PV probe 3 |
| whowhen AG text-vs-flag agreement | Both come from one header (36/36 by construction) | verify_a4 |
| Gemini error classes together | Never validated jointly; only their union serves as a session indicator | PR; PV probe 3 |
| Content of the swechat CC "unmarked" native-error class | 1,754 results, not inspected | PV probe 3 |
| copilot text agreement | 8 native positives in 2 s | verify_a4 |
| aiv_cc village-bash JSON error proxy precision | Native never fires on those turns | verify_a4 |
| Codex: 163 shell results with neither native nor exit | Unified-exec deferral or missing exec_command_end; unresolved | verify_a4 |
| Whether OpenCode's model saw anything beyond `state.output` for shell results (exit metadata, say) | The IR text carries none, and prompt assembly is not in the data | verify_a4 [4] |
| Whether the aiv_cu separate stderr (`error`) field is shown to the model | Assumed yes; not verifiable from the export | verify_a5 [4] |
| Cursor retry and verification; Who&When HC retry | Cursor has no results; HC has no failure flags | sequences [5] |
| Failure-marker retention under spill, Codex truncation, OpenCode spill and Gemini masking | n = 0 truncated results with native_error true in those types | verify_a3 |
| Narration failure-regex precision (push, commit, PR, merge, tests, deploy) | No labels, so 0 contradictions cannot be told from regex blindness | aiv_narration lens |

### 5.5 Every INSUFFICIENT_N and below-minimum cell

**Probe 1**
- codex AUC: no G tool.
- gemini AUC: G 13 from 5 s.
- gemini auto_read p1 and p99.
- Floor stability for opencode (0/15 series, 10 s), cc_local (0/5, 4 s) and gemini (0/4, 4 s): series counts below
  min-n, Wilson hi 0.20 and 0.43 for the two ALIVE units. Relabelled INSUFFICIENT_N here; the JSON prints STABLE (PV
  probe 1 audit, items 4c and 8d). The two ALIVE verdicts therefore carry no floor-stability evidence.

**Probe 2**
- S_deep below 20 sessions, raw counts only: codex main 27/156 (11 s), opencode main 18/201 (11 s), gemini 55/127
  (13 s), cc_local main 31/90 (17 s) and aiv_cc main 0/1,235 (13 runs).
- aiv_cu: no structured file-access tools, so S_deep is undefined and there are no Edit old_string symbols; its
  first-try success is only a stderr proxy (PV `probes[1].res.could_not_measure[1]`).
- gemini main, cursor main and whowhen main.
- cc_local subagent: 2 and 6 sessions.
- Five subagent strata with no threads.
- 1,573 of 1,952 cc_local subagent accesses have unknown depth (PV probe 2).

**Probe 3**
- Zero-error tail: aiv_cc (16 long sessions), codex (11), opencode (7) and gemini (1).
- whowhen AG early/late: 0 sessions with ≥ 20 calls (max 5).

**Probe 4**
- Hex: codex (64 symbols), opencode (47), gemini (0), cursor (0), cc_local (175), aiv_cc (137) and whowhen (32), against
  N_min 1,131.
- Round numbers: codex, opencode, gemini, cursor, aiv_cc and whowhen.
- Model-typed ls mtimes and byte counts: fewer than 30 values everywhere.

**Phase C**
- Within-stratum z for swechat cursor (8 s) and cc_local proj02 (13 s).
- cc_local at useful power: only 15/186 B sessions reach 40 main-thread calls (changepoints lens).
- Codex, Gemini, cursor and cc_local subagent rates: fewer than 30 sessions.
- copilot (2 files) and simple_text (4).
- The re-stamped copy phenomenon: 5 shared-session pairs, 2 re-stamped.
- Bedrock and Vertex id rollout dates.
- Who&When: 0/111 eligible for change points (max 30 calls).

### 5.6 Token accounting limits

- **No tokenizer.** No new dependencies were allowed, so every residual floor and minimum detectable delta is an upper
  bound from a chars, newline and non-ASCII model (verify_a5; token_conservation lens).
- **No tool-result token field.** No field counts tool-result tokens separately in any corpus (PA:A5).
- **Streaming partials.** Claude Code per-response output_tokens are streaming partials, so result-only conservation was
  not run for CC formats. aiv_cc output can only be checked at run level (verify_a5; aiv_accounting lens).
- **No usage at all** in Who&When, cursor, and the aiv_cu OpenAI and compat strata (token_conservation lens).
- **Inferred only:** whether thinking or encrypted reasoning stays in context; within-turn retention cannot be separated
  from partial output counts.
- **aiv_cu Anthropic per-image cost**: screenshots carry no marker in the IR.
- **Mechanisms never checked against raw data:** the ExitPlanMode residual, the aiv_cu pause injections and the Gemini
  CLI context drops.
- **Not modelled or analysed:** subagent-boundary conservation and session or resume continuity.
- **Not compared:** A/B consistency. A5 output was not available to the lens when it ran.
- **aiv_cc limits:** the identity and timing of the hidden Haiku/Sonnet calls (modelUsage has no per-call timing); the
  causes of 15/211 runs with responses missing from the ledger (an association with stop_reason, not a mechanism);
  whether compaction `pre_tokens` contains a client-side estimate.
- **Gemini CLI:** only 2,505 of 3,017 split-A messages carry tokens; the rest blur their pairs (verify_a5).
- **Unmarked negative deltas** (OpenCode pruning, Claude Code context edits): their causes are unknown, because the IR
  records no marker for them (verify_a5 [5]).
- **aiv_cu residual against a typical result**: not meaningful, because GUI results carry almost no text (median 9 to
  174 chars) (verify_a5 [7]).
- **OpenCode's token-total formula**: by design only 2 pre-specified formulas were tried (verify_a6_raw_census [10]).
- **Prices**: only per-token coefficients implied by the data's own costUSD; no outside price list (aiv_accounting [0]).
- **The Codex 516 + 518k reasoning-token lattice**: cause unknown; only token_count events exist, no provider
  documentation (distributions [1]).
- **The 8000/8192 output-token spikes**: whether they are max-token stops is unknown, because stop_reason is not in the
  IR (distributions [4]).
- **aiv_cu Claude-Agent-SDK context drops**: whether they are compactions is unknown (the table has no marker), and no
  agent-id join to aiv_cc was done (changepoints [3]).
- **aiv_cc token-based features** are only internally comparable, because per-row output_tokens are streaming
  snapshots (outliers [6]).

### 5.7 Ids and provider clocks

- **Vendor documentation is missing for every decoded layout:** Anthropic UUIDv7-in-base58, OpenAI item hex time,
  Gemini responseId LE seconds, and OpenCode 48-bit time + counter. All are inferred from B and checked on holdout A
  only: UNVERIFIED.
- **Ids cannot be verified against the vendor server.** No corpus has API access.
- **Unknown meanings:** Gemini responseId bytes 4–16, the UUIDv7 rand_a bias (bit 75 is almost always 0 in swechat but
  not in cc_local; IX ids/O1 gives only point shares, not quoted), and the OpenAI per-session 16-hex prefix.
- **Uninspected cases:** the cause of 8 of the 10 inconsistent swechat bracket streams and of the 3 inconsistent aiv_cu
  OpenAI streams.
- **Census only:** PID consistency across results (330 swechat results match the PID pattern).
- **cc_local task notifications that reference ids never issued in-session** (637): the newer harness issuance texts
  were not inventoried. The related observation ids/O12 was not reproduced (a regex artifact), so this is an open
  question, not a finding (ids_and_clocks_in_ids [5]).
- **cc_local per-month id-format epochs**: private corpus, aggregates only (ids_and_clocks_in_ids [8]).
- **Who&When ids**: only loader-synthetic step ids and no timestamps, so there is nothing to measure
  (ids_and_clocks_in_ids [9]).
- **Never run** (§4.3):
  - the rank-1 inter-request ceiling;
  - the aiv_cu Gemini window w = created_at − HTTP Date;
  - the coverage stretch-guard power.
- **Provenance:** the rank-1 placebo was produced by uncommitted code and is withheld here.

### 5.8 Loader and IR open problems

**47 open parser surprises** (`out/phase_a/a6.json` `part2_parser_surprises`, status `open`).
- **swechat (18):**
  - sessions.parquet rows without a transcript file;
  - undecodable Claude Code lines;
  - files yielding zero IR events;
  - pairing anomalies;
  - ts earlier than the previous event in file order;
  - Gemini results stamped at or before their call;
  - Gemini toolCalls with no result (one session);
  - Gemini call ids redacted into duplicates;
  - Gemini `Exit Code: N` with native_error not true;
  - cursor with no results and no stamps;
  - OpenCode parts with no time field;
  - OpenCode compaction summaries emitted as assistant text;
  - Codex files with no exec_command_end;
  - Codex user_message texts with no matching response item;
  - call ids in more than one session (resume/fork copies);
  - tool calls missing from conversations.parquet;
  - redaction-marker substrings;
  - copilot usage rows with output tokens only.
- **cc_local (6), plus 2 shared with aiv_cc:**
  - subagent events stamped after the parent result (background runs);
  - tool_use input differing from the harness wireToolInputs copy;
  - review-2 row counts predating the caches;
  - results with no is_error key;
  - events sharing one millisecond;
  - attachment payloads duplicated in derived text;
  - shared: API message ids with differing usage_out (streaming partials);
  - shared: sample redraw matching only in loader order.
- **aiv_cc (7):**
  - content.session_id differing from sdk_session_id;
  - message_uuid null on every row;
  - assistant rows with an SDK `error` field;
  - results with no is_error key;
  - runs never closed (0 result rows);
  - created_at trailing zeros stripped;
  - tool_use blocks with no tool_result.
- **aiv_cu (8):**
  - model-generated mouse_move to (512, 384);
  - Gemini server-timing absent before 2025-12;
  - no latency or server-timing field in any non-Gemini shape, and no usage in OpenAI shapes;
  - rows with updated_at − created_at > 1 s;
  - created_at trailing zeros stripped;
  - sessions with no turns;
  - `screenshot_is_redacted = true` turns;
  - no failure flag or exit code at all.
- **whowhen (6):**
  - ground-truth mistake_agent differs from the speaker at mistake_step;
  - AG question absent from the history;
  - `exitcode` text inside non-terminal messages;
  - HC results without an exit code;
  - "There is no code to execute" replies;
  - the IR kind at the labelled mistake step.

**Fields that need a loader change**, decided by day:
- `permissionMode`;
- CC `toolUseResult` Read numLines/startLine/totalLines, Edit structuredPatch, Grep numLines and Glob totalMatches;
- CC stop-hook `hookInfos[].durationMs`;
- OpenCode `info.time.completed`;
- `file-history-snapshot`;
- cc_local cost-state and workflow totals.

No loader reads any of these, as far as a string-literal match on `analysis/loaders/*.py` can tell (A6-O3/O4 skeptic:
"none references numLines, structuredPatch or totalMatches"). The loader mark is only that string match, made while other
agents were editing the loaders; the caches were not read (verify_a6_raw_census [3]).

**How this list was built.** No build or review report has a `parser_surprises` or `open_problems` field. The 80-entry
list (47 open) is a hand-selected compilation: its values are read from the reports, but the selection is judgement
(verify_a6 [6]). Items outside the selection may exist.

**Other IR artifacts** (§4.2.8):
- interrupt markers filed as `user` (D18);
- results written before their call carry tool=None (S10);
- the aiv_cu loader rewrites duplicate provider call ids, 2 of them in split B (`out/build/aiv_cu_build.json`
  `splits.B.call_id_source.duplicate_in_session`);
- n_models is a loader artifact (outliers/O7);
- failed-resume rows fall into the previous aiv_cc run (outliers/O8);
- a salvaged, truncated OpenCode document silently loses 232 calls (R:A2-4);
- 1 OpenCode transcript is invalid JSON, and 1 Claude Code session has no transcript file (swechat_tables [1];
  `out/build/swechat_build.json`).
- `conversations.parquet` has no message-id column, so distinct assistant message ids had to come from the raw
  transcripts (swechat_tables [0]).

**Census gaps** (verify_a6; raw_census lens):
- 75 slice_absent_in_A and 121 inconclusive_rare entries;
- key paths deeper than the depth limits;
- cc_local subtrees hidden for privacy;
- `village-transcript.json` (362 MB) not censused;
- AI Village side tables censused on their first 20,000 rows only;
- `conversations.content`: only 340 of 500 sampled rows parsed;
- swechat transcript key-path fill rates come from a 300-file stratified sample; only the entry-type inventory covers the
  full population (verify_a6_raw_census [5]);
- 583 census-marked cc_jsonl paths were trusted from the census's code-derived path list, not re-verified as non-null in
  the A caches (verify_a6 [2]);
- aiv_cu population fill from pass-1 stats has no session-clustered CI (the pass-1 index has no session ids), and
  list-level paths count elements, not rows (verify_a6 [3]);
- AI Village computer_use_turns census CIs are Wilson over rows, not session-clustered, although the head spans 17,418
  sessions (verify_a6_raw_census [9]);
- the value equivalence of rule-mapped fields that live on another row (OpenCode message-level info.tokens against
  step-finish usage; Gemini functionResponse.id against call id) was not checked, only presence (verify_a6 [5]);
- the agreement of uncaptured second clocks with event stamps, and file-history-snapshot against Edit/Write: listed,
  never measured.

### 5.9 Corpus constraints

- **aiv_cc is one agent.** B is not held out in content (156/189 runs share an SDK session with A).
- **cc_local is private and few-session dominated.** Its subagent-thread pairs come from 6 sessions, and a top 5 of
  sessions hold most of its clean token-conservation pairs (IX TC15; share without k/n, not quoted). Content-level
  causes were never inspected: zero-thinking sessions, template errors, and the meaning of the `model` and
  `auto_mode` attachments (outliers [4]; changepoints [2]).
- **Why Haiku turns appear in swechat Claude Code main threads** is unknown (changepoints [2]).
- **Who&When has no outcome contrast.** There are no timestamps, every task failed, `is_correct` is constant, and its
  label correlations fail on A.
- **collusion-wiki and urlquery cannot link a claim to a fetch.** There are no agent tool calls. The urlquery catalogue
  has no URLs, bodies, values or submitter, so only source-level co-timing is possible. No transcripts exist for those
  campaigns. The wiki rclog clock is null on all 14,591 revisions. Time-of-day claims carry no date. Whether the task
  clock runs at wall-clock rate is unknown.
- **The wiki's save clocks are not independent.** time, write_date and request_time are identical by construction;
  only success_time and archived_at vary independently (ext_witness [3]).
- **SWE-chat session start times**: `sessions.created_at` is not the session start, so population-level time order from
  metadata is invalid; only the transcript-based sample order is (commit_witness [6]).
- **Whether 41 turns is a configured AI Village cap**: no harness config is in the data (distributions [2]).
- **AI Village `has_been_asked_to_stop`** is constant, so forced and voluntary stops cannot be compared.

### 5.10 Phase C items that were explicitly not attempted

| Lens | Not attempted |
|---|---|
| two_clocks | file-history-snapshot backupTime against Edit timestamps; turn_duration.messageCount; Codex rate_limits.resets_at; Gemini CLI thoughts[].timestamp; queue-operation stamps against prompts; whether the turn_duration residual is permission-wait time (only a correlation) |
| correlations | Exact re-ranked CIs beyond the top 10 pairs per unit (cc_local lower bounds can differ by up to 0.116); mechanisms for the unexplained replicating pairs (no host-load or permission-prompt timing); a model or harness version stratifier beyond the haiku/sonnet/opus substring (correlations [4]) |
| changepoints | A detector calibrated under the observed autocorrelation; per-event identity tests for the couplings; scaffold version changes inside runs or sessions |
| sequences | Linking assistant-text claims to sequences ("tests pass" against the last test result); a robust shell parser (the naive parser fails on part of the aiv_cu shell calls, cause not investigated); why cc_local read-before-edit is low with zero refusals; disentangling model, agent, task and period in aiv_cu; whether the openai-responses tool schema offers a bash restart action, which decides whether 0/137 timeout→restart is behaviour or schema (sequences [2]) |
| aiv_narration | Subject and tense attribution of claims; GUI-observed claims; the negation-rule miss rate; per-model comparisons controlled for GUI share |
| outliers | Session-clustered CIs for the timeout-bin spikes; overlap with the swechat_tables outlier set; the proposed k ≥ 5–8 tail cut (not pre-registered, not applied) |
| swechat_tables | Causes of the 33 residual unmatched tallies; prompt-count definitions; the attribution-metric version; 1,739 files_touched entries neither edited nor committed; recount formulas for copilot and cursor |
| commit_witness | Transcript-side checks for OpenCode, Codex, Gemini, Copilot and Cursor; NotebookEdit; the 5,205 commit_not_found rows; formatters and human keystrokes; concurrent edits outside the checkpoint; subagent transcripts outside the main JSONL |
| ext_witness | Claim-level linkage between witnesses; validation of the post-hoc heuristics (tense, roundness, task-to-UTC pairing) on a holdout |

### 5.11 Limits of this report's own process

- **Not blind.** Phase C read split B before Phase B ran, so Phase B is not a blind test (caveat 1).
- **Uncommitted skeptic code.** Skeptic numbers [S] come from uncommitted scripts. The rank-1 placebo is withheld for
  that reason.
- **Uncommitted Phase D files.** `ranking.json`, its inputs and `phase_d_ranking.py` were uncommitted at this revision.
  The [D] intervals depend on them, and no ranker-level vote count is quoted for that reason (caveat 8).
- **Rule-4 deviation in `ranking.json`.** It stores interpretation fields (`why_this_rank`, `build_first`,
  `disagreements[].resolution`, `relation_to_phase_b`) inside `analysis/out/`. They are labelled INTERPRETATION in its
  `field_kinds`, but they belong in `analysis/notes/` (caveat 8).
- **Post-hoc work on killed cells.** Phase B scripts kept describing killed cells after their kill (PV probe 2 and 3
  audits, rule 5). Those numbers are quarantined in §3.2 and §3.3.
- **Prior art for §4.3 was not checked.**
- **What the traceability audit can and cannot show.** `analysis/probes/phase_d_trace.py` matches every number here
  against every number indexed from the committed outputs. A match at low precision is weak evidence by itself. Its
  "colocated" class means the number shares a source record with other numbers from the same row or paragraph, not
  that the meaning was verified. Small integers can co-locate by chance inside long skeptic strings, and numbers stored
  only as percentages can miss co-location. The tuning steps of that script are logged in its output
  (`out/phase_d/trace.json` `parameter_log`).
- **Degenerate intervals.** Session-clustered bootstrap CIs are degenerate ([0, 0] or [1, 1]) at rates of exactly 0 or
  1. Where that matters, this report adds a per-event Wilson bound and says so (verify_a2 [5]; verify_a4 [6]).
- **Below-minimum values in the JSONs.** No verdict reads any of them:
  - Probe 2: 43 rates or CIs below the global min-n;
  - Probe 3: Wilson CIs on INSUFFICIENT_N cells;
  - Probe 4: 353 quantile entries below the quantile minimum;
  - Probe 1: G per-tool medians below n = 30 (PV audits, rule 8).

### 5.12 Joins, pairing and truncation that could not be checked

- **Whether all 486 population Gemini calls without a result come from the one split-A session.** The counts match, but
  confirming it would mean opening B caches or raw files (verify_a2 [0]).
- **Who&When pairing.** Whether the HC open-call heuristic and the AG adjacency pairing are correct cannot be checked: no
  ground truth exists for the pairings themselves (verify_a2 [2]).
- **The one swechat CC orphan classed "other" and the 4 "other" unpaired CC calls**: cause unknown, because the
  classification used IR fields only, with no text inspection (verify_a2 [3]).
- **No split-A table-against-raw comparison.** The cited cross-check covers the combined A+B sample and the recon covers
  the whole table (verify_a2 [4]).
- **aiv_cu join completeness at the source**: the loader emits a result for every executed call from the same row, so
  an orphan cannot appear in the IR (verify_a2 [1]; §2.3).
- **The cc_local Glob truncation note's wording**: private text, not read; only its shape was counted (verify_a3 [2]).
- **An aiv_cu output cap**: only one observation at the maximum (135,168 chars, gemini-pro), and B was not searched for
  more (verify_a3 [4]).
- **The SWE-chat 1,552-result cap** is a full-table recon number from `conversations.parquet`, not a split-A
  measurement; §2.1 and caveat 4 now say so (verify_a3 [5]).

---

## 6. Confidence log

**How to read a bet.** "X:1 label" means I would bet X to 1 that the verdict label replicates on a fresh sample drawn the
same way: same scaffolds, a similar version mix, honest logs. "X:1 CI" means the point estimate of that fresh sample
would land inside the CI stated here. The bets are judgement, not data. Every headline number and every number that
decides a verdict, a kill or a rank has a row; this revision added the rows the completeness audit found missing.

**Composition risks that recur in the bets.**
- **aiv_cc** is one agent.
- **cc_local** is dominated by a few sessions and by one 92-session template.
- **swechat opencode** in B is 175/214 one repo (IX outliers/O3).
- **Phase C read split B.**

### 6.1 Phase B verdict-deciding numbers

| # | Number (source) | Bet | What would change my mind |
|---|---|---|---|
| 1 | P1 swechat CC fp_share 72/20,937 = 0.0034 [0.0025, 0.0044], 1,042 s | 9:1 that fp stays ≤ 0.05; 3:1 CI | A sample from newer Claude Code versions, or hook-heavy setups, where read latency absorbs hook time; a faster G90 |
| 2 | P1 swechat CC floor step 21/156 = 0.135 W[0.090, 0.197], deciding the downgrade to WEAK | 3:2 that a fresh sample is also > 0.10 | The 0.10 line sits inside the CI, and one step sits at p = 0.01. A re-run at ≤ 0.10, or an identified cause (an unlogged hook, say) that can be filtered |
| 3 | P1 swechat CC AUC 0.987 [0.980, 0.993] | 9:1 that it stays ≥ 0.85 | G durations no longer taken from harness-reported durationMs |
| 4 | P1 opencode fp 7/4,419 = 0.0016 [0, 0.0033]; AUC 0.999 [0.998, 1.000] (ALIVE) | 2:1 label | 175/214 B sessions come from one repo; floor stability is untested (0/15 series, below min-n, W hi 0.20); G is 127 pairs from 12 s, 116 of them subagent. A multi-repo OpenCode sample with fp > 0.05 or floor steps would flip it |
| 5 | P1 cc_local fp 1/1,019 = 0.0010 [0, 0.0033]; AUC 0.919 [0.881, 0.971] (ALIVE) | 3:1 that fp stays ALIVE; 3:2 that the AUC lower bound stays ≥ 0.75 | G is 153 pairs from 12 s and bimodal (51 of 153 pairs below r = 0.0178); floor stability is untested (0/5 series, W hi 0.43). New cc_local sessions outside the template |
| 6 | P1 aiv_cc fp 241/3,217 = 0.075 [0.040, 0.119] (WEAK, one agent) | 4:1 label for this agent; no bet beyond it | A different agent, or runs without long shell commands |
| 7 | P1 aiv_cc AUC 0.865 [0.762, 0.922] (auc ALIVE; the unit is WEAK on fp; one agent) | 3:1 that the AUC lower bound stays ≥ 0.75 for this agent; no bet beyond it | The lower bound sits 0.012 above the 0.75 cut (PV probe 1 re-derivation). A different agent |
| 8 | P1 codex fp 270/4,329 = 0.062 [0.026, 0.118] (WEAK) | 1:1 label | The CI spans both the 0.05 and 0.10 lines; more than 57 sessions would decide it |
| 9 | P1 gemini fp 0/295, per-event W hi 0.0129 (WEAK for lack of a control) | 2:1 that fp stays ≤ 0.05 | 16 sessions only; ≥ 30 G pairs could make it ALIVE |
| 10 | P2 instrument check, CC S_symbol_ref 1,242/46,836 = 0.027 [0.022, 0.031] | 9:1 that it stays ≤ 0.10 in gated Claude Code | A harness without the read-before-edit gate. cc_local already shows 0.421 on 12 s |
| 11 | P2 CC main S_deep 671/4,655 = 0.144 [0.125, 0.163] (WEAK) | 9:1 that it stays in (0.05, 0.20]; 4:1 CI | A matcher that credits path composition would lower it, but that is a different statistic (0.523 [0.455, 0.589] of the residual had the basename visible) |
| 12 | P2 CC subagent S_deep 525/6,850 = 0.077 [0.062, 0.091] (WEAK) | 3:1 label | A fresh sample under 0.05 |
| 13 | P2 opencode subagent S_deep 16/219 = 0.073 [0.020, 0.150] (WEAK) | 3:2 label | It depends on a logged root deviation (under the strict rule the S_path_any fallback gives 0.098 [0.084, 0.112], same label) and on one repo |
| 14 | P2 codex subagent S_path_any 104/795 = 0.131 [0.099, 0.163] (WEAK by the S_path_any fallback; 36 s) | 3:1 label | The envelope deviation: the strict-prereg value is 0.138 [0.105, 0.173], same label (PV probe 2 re-derivation). A sample with enough deep accesses for S_deep to decide |
| 15 | P2 opencode main S_path_any 237/767 = 0.309 [0.229, 0.394] (DEAD) | 3:1 that it stays > 0.20 | A fresh opencode main sample at ≤ 0.20 under the pre-registered definition. 36 sessions, from a corpus dominated by one repo |
| 16 | P2 codex main S_path_any 343/1,103 = 0.311 [0.213, 0.429] (DEAD) | 2:1 label | 24 sessions; small n |
| 17 | P2 cc_local main S_path_any 1,669/2,820 = 0.592 [0.445, 0.653] (DEAD) | 4:1 label | Literal matching gives 0.694 [0.618, 0.737] (PV probe 2 re-derivation), also DEAD. A sample outside the 92-session template |
| 18 | P2 aiv_cc S_path_any 710/3,689 = 0.192 [0.081, 0.351] (WEAK, one agent) | 1:1 label | The CI spans the 0.20 line; the re-derivation flagged it as fragile (PV) |
| 19 | P2 aiv_cu S_path_any 9,597/11,889 = 0.807 [0.788, 0.824] (INCONCLUSIVE) | 19:1 CI | An IR that carries the aiv_cu prompt and memory |
| 20 | P3 CC zero-error tail Z 9/413 = 0.022 W[0.012, 0.041] (ALIVE) | 9:1 that Z stays ≤ 0.10; 4:1 CI | A shell-light, edit-heavy population. The honest zero-error long sessions are lighter on shell: shell is 305/1,472 of their calls against 43,427/134,633 in the other 404 long sessions |
| 21 | P3 CC at L90 0/224, W hi 0.017 | 4:1 that a fresh sample shows ≤ 1 per 100 | The same as #20 |
| 22 | P3 cc_local Z 15/36 = 0.417 W[0.271, 0.578] (DEAD) | 2:1 label | A fresh cc_local sample with Z ≤ 0.30 at the pre-registered L75 of 20 calls |
| 23 | P3 aiv_cu Z 678/988 = 0.686 W[0.657, 0.714] (DEAD) | 9:1 label | A validated aiv_cu error flag that replaces the stderr proxy |
| 24 | P3 whowhen AG Z 7/27 = 0.259 W[0.132, 0.447] (WEAK) | 1:1 label | The CI spans the 0.30 line. Even as WEAK it carries no excess over independence: Z/E0 = 1.23 at L75 = 3 calls (PV probe 3 re-derivation) |
| 25 | P3 CC reaction 0.106 [0.091, 0.121] (WEAK) | 3:1 that the CI lower bound stays < 0.10 | Read-gate refusals inflate it; the post-hoc tool-stratified effect is 0.092 [0.078, 0.106] |
| 26 | P3 cc_local reaction 0.118 [0.038, 0.191] (WEAK) | 2:1 label | Few-session dominance |
| 27 | P3 opencode reaction 0.101 [0.030, 0.206] (WEAK) | 3:2 label | The post-hoc tool-stratified effect is −0.071 [−0.151, 0.047] (post hoc, no verdict), which suggests composition |
| 28 | P3 aiv_cu reaction 0.034 [0.009, 0.058] (WEAK, proxy) | 2:1 label | A validated error flag |
| 29 | P3 aiv_cc reaction −0.230 [−0.343, −0.077] (DEAD, one agent) | 4:1 sign under the prereg definition, for this agent | A fresh run of this agent with effect CI lo > 0 under the prereg definition. Untested interpretation, which does not reopen the line: get_events supplies 11,716 of 18,150 R_ok retries |
| 30 | P3 codex 0.038 [−0.041, 0.183], gemini 0.015 [−0.021, 0.077], whowhen AG 0.099 [−0.083, 0.276] (all DEAD) | 3:1 each for codex and gemini; 3:2 for whowhen AG | whowhen AG has 20/104 unpaired successors and no sensitivity run (PV audit) |
| 31 | P4 CC hex T_orig w_adj 0.110 [0.041, 0.232] against control hi 0.016 (WEAK) | 3:1 label | Under the prereg, ALIVE needs w_adj ≥ 0.15 with the control's CI hi below the T_orig value; a fresh sample meeting that would change the label. The bias of "unsourced" has unknown direction (§3.4) |
| 32 | P4 aiv_cu hex 0.093 [0.043, 0.216] against 0.034 (WEAK) | 3:1 label | The same rule; the same unknown bias direction |
| 33 | P4 CC round T_orig 127/300 = 0.423 [0.334, 0.520] against M_all 0.116 [0.110, 0.122] (ALIVE) | 9:1 label. No bet on what it measures | Per-field machine baselines for byte counts and durations. In the distinct-value class, JSON-number parameters are 49 of the 127 last-0 values, and the string-embedded subset alone is 78/249 = 0.313 [0.213, 0.427] (post hoc; PV probe 4 audit, rule 6b) |
| 34 | P4 cc_local round 221/341 = 0.648 [0.435, 0.786] (ALIVE) | 2:1 label | 14 sessions |
| 35 | P4 aiv_cu round 740/3,866 = 0.191 [0.133, 0.293] (WEAK) | 2:1 label | Repeated 8-digit identifiers from outside the record dominate |
| 36 | P4 swechat/* pooled: hex w_adj 0.105 [0.052, 0.220] against 0.015 (WEAK); round 141/322 = 0.438 [0.353, 0.531] (ALIVE) | 3:1 hex label; 9:1 round label | Both are dominated by swechat CC (130 of 145 round sessions, PV probe 4 re-derivation). The hex CI moves with pooled session order: [0.0560, 0.2270] re-derived |
| 37 | P4 public/* pooled (contains aiv_cc): hex w_adj 0.083 [0.046, 0.169] against 0.013 (WEAK); round 844/4,148 = 0.203 [0.146, 0.298] (WEAK) | 3:1 each | aiv_cu dominates both; the CIs move with pooled session order (PV probe 4 re-derivation) |
| 38 | P4 CC model-typed ISO times on :00, 0.842 [0.767, 0.911] against 0.030 [0.023, 0.039] (no verdict) | 9:1 direction | Per-source baselines: cc_local machine output is already 0.387 [0.030, 0.664] |
| 39 | PV: 49 of 50 unit checks reproduced | 19:1 that the verdict tables are the mechanical output of the prereg on B | A second independent re-derivation that disagrees |

### 6.2 Phase A numbers that killed or gated lines

| # | Number (source) | Bet | What would change my mind |
|---|---|---|---|
| 40 | aiv_cu shared call/result stamp 6,107/6,107 (A) and 59,956/59,956 (B) | 99:1 | A different export of computer_use_turns with per-action stamps |
| 41 | conversations.parquet orphans 76,618/408,086 = 0.1877 of distinct results, against raw 16/633,366 | 99:1 | None expected; this is a builder dedup, confirmed independently (IX swechat_tables/T5) |
| 42 | aiv_cc conservation TIGHT, ratio 0.046 [0.038, 0.054] | 9:1 for this agent; no bet beyond it | Another agent |
| 43 | Gemini CLI masking 840/2,313 = 36.3% [25.2, 43.2] (7/10 s) | 3:1 CI | 10 sessions only |
| 44 | Conservation NOT_TIGHT: codex ratio 2.311 [0.914, 4.409] (15 s), cc_local 1.639 [1.372, 2.941] (106 s), aiv_cu Anthropic strata pooled Spearman 0.323 [0.146, 0.551] (67 s) | 4:1 that cc_local and aiv_cu stay NOT_TIGHT; 3:2 for codex | codex's CI reaches below 1.0, the LOOSE range, on 15 sessions. A real tokenizer would shrink every residual, since all are upper bounds |
| 45 | swechat CC conservation LOOSE, ratio 0.742 [0.591, 0.9996] | 1:1 that a fresh sample is LOOSE rather than NOT_TIGHT | The upper bound sits at the 1.0 line (R:A5-4) |
| 46 | Gemini CLI text-proxy error definition absent: A proxy P 0/280, R 0/143 | 9:1 that a text proxy stays unusable in Gemini CLI | A Gemini CLI version that writes `Exit Code:` for zero exits, or whose native status coincides with the text exit code |
| 47 | aiv_cu stderr proxy fires on 118/6,107 = 0.019 [0.013, 0.026] (unvalidated) | 3:1 CI; no bet that it measures errors | A reference failure flag in an aiv_cu export, against which its precision and recall could be measured |
| 48 | copilot as a unit: 1/266 calls without a result, per-call Wilson hi 0.021 > 0.01, 2 sessions (R:A2-2) | 19:1 that 2 sessions cannot support a unit | A copilot sample with ≥ 10 sessions |
| 49 | Human waits that excluded shell, edit and write from Probe 1: permission rejections in 19/126 swechat CC s = 15.1% W[9.9, 22.4]; Edit/Write over 2 s 296/2,235 = 13.2% [6.8, 21.7]; shell pre-exec offset over 2 s 50/367 = 13.6% [5.8, 25.9] | 4:1 that each stays above 5%, so the exclusion stays necessary | `permissionMode` in the IR, which would let human waits be filtered instead of excluding whole tool classes |
| 50 | swechat CC text proxy A, which defines Probe 3's primary error class: P 488/488 (W lo 0.992), R 488/614 = 0.795 [0.720, 0.855], 90 s | 9:1 that P stays ≥ 0.99; 3:1 CI for R | A Claude Code version that changes the error text; the 1,754-result "unmarked" native-error class, never inspected |

### 6.3 Phase C headlines and rank-deciding numbers (§4)

| # | Number (source) | Bet | What would change my mind |
|---|---|---|---|
| 51 | Bracket: honest inconsistent streams 10/3,674 = 0.00272 [0.00112, 0.00466] [S]; committed copy 10/3,676 | 4:1 that a fresh swechat CC sample is ≤ 0.00466 at 2 s; 3:1 that post-Phase-C cc_local is ≤ 0.00666 | More resume/fork re-stamping; a Claude Code change to when assistant entries are stamped; the 8 unexplained sessions turning out systematic |
| 52 | Request ids decode as UUIDv7, 154,815/154,815 [S] (layout UNVERIFIED) | 19:1 for ids of this period; 2:1 that the layout stays stable for a year | Vendor documentation, or a format change. Message ids already changed on 2026-07-06 (IX ids/O4) |
| 53 | Request-id clock agreement 155,067/155,267 = 0.99871 [0.99676, 0.99992] [S] | 9:1 CI | Larger re-stamped populations |
| 54 | Rank-1 tamper response (placebo) | **No bet. Withheld until Step 0 re-runs it from a committed script** | The re-run itself |
| 55 | Gemini IMAGE lattice 11,668/11,668 [S] | 19:1 for these model generations | A new generation with a different unit, or image pruning above 40 images |
| 56 | Non-GUI windows with an IMAGE increment 0/6,853 (sum of nine committed rows, §4.3 rank 2), W hi 0.00056 [D]; split A 0/309 and 0/320 | 9:1 that a fresh honest sample shows ≤ 1 per 1,000 | Session clustering. No per-session counts exist, so the interval treats windows as independent |
| 57 | Rank 2, split-A GUI side: gaps holding a GUI result show an increment in pro 417/420 = 0.9929 [0.9840, 1.0] (18 s) and flash 191/191, Wilson [0.9803, 1.0000] [D] (12 s) | 9:1 that ≥ 0.98 of GUI gaps show an increment in a fresh sample of these model generations | A generation with a different unit (2,160 already appears in 70 rows from 3 sessions); image pruning above 40 images |
| 58 | GUI windows without an increment 33/5,092, W [0.00462, 0.00909] [D] | 3:1 CI | The same clustering caveat; there is no session-level rate |
| 59 | Commit date inside the printing call's window 3,917/3,936 = 0.995 [0.992, 0.998] [S] | 9:1 that it stays ≥ 0.99 on another swechat CC sample; 1:1 that the 15/1/3 classification holds on a held-out half | Background-task-heavy sessions, where re-reads multiply |
| 60 | Rank 3 coverage: 4,085/5,850 = 0.698 [0.686, 0.710] (W) of swechat sessions link ≥ 1 ok commit [S] | 4:1 CI on another swechat snapshot | A change in scaffold mix; the differences by scaffold vanish under repo clustering |
| 61 | Honest commit claims that do not resolve 2,198/6,141 = 0.358 [0.321, 0.394] [S] | 4:1 CI | Repos with more history rewriting |
| 62 | Commit '+' lines full match 0.829 [0.812, 0.844] against decoy 0.0014 [0.0009, 0.0020] [S] | 9:1 that the gap persists | The same-repo null is 0.007 and the prior-commit null 0.019, still far below. The honest no-match rate, 5,534/40,540 = 0.137 [0.123, 0.153], is the base any alarm would fire on |
| 63 | Write content fully present in the committed file 5,409/6,413 = 0.843 [0.825, 0.861] against decoy 7/6,413 = 0.0011 [0.0003, 0.0022] [S] | 9:1 that the full-match gap persists | Only full matches discriminate: decoy partial matches are 2,087/6,413 = 0.325 [0.302, 0.350]. A repo mix heavy in generated or boilerplate files |
| 64 | Read numLines agreement 87,827/88,229 = 0.9954 [0.9950, 0.9959] [S] | 19:1 for swechat-era Claude Code; 2:1 that "0 unexplained after the whitelist" holds out of sample | A new Claude Code display format. cc_local main 570/578, all empty-file warnings, is mildly supportive |
| 65 | Subagent totalToolUseCount 6,623/6,623 [S] | 9:1 within that era | Current Claude Code no longer writes the nested traffic (0 of 332 cc_local main files have progress) |
| 66 | Entire tally recount 4,794/4,836 = 0.9913 [0.9883, 0.9936]; unmatched after the fix 33/5,701 = 0.0058 [0.0041, 0.0081] [S] | 4:1 CI | CLI 0.5.x already runs at 0.0143 [0.0087, 0.0235] |
| 67 | Rank 5, aiv_cc cache chain 59,747/59,804, run-clustered 0.99905 [0.99858, 0.99943] [S] (one agent) | 9:1 for this agent; no bet beyond it | Another agent. Long-gap breaks (8/32 at ≥ 300 s) already show the chain is not a stopwatch |
| 68 | Rank 5, Codex cached input a multiple of 128 in 16,106/16,106 calls [S] (post hoc) | 9:1 for this Codex era | A provider change to cache block size. It was found post hoc, so no pre-registered test of it exists |
| 69 | TC2: inserted chars at power 0.5 / 0.9, 8,913 / 10,000, swechat CC at realized FPR 0.0101 [0.0092, 0.0112] [S] | 4:1 within one grid step on a re-run | Model choices move the crossings by one grid step (skeptic) |
| 70 | TC16: deleting a result of 100–999 chars, simulated power 0.003 over 61,269 deletions [S] | 19:1 | It is arithmetic: a result under 1,000 chars shifts the residual by at most 310 tokens, against thresholds of 2,389–2,592 (skeptic) |
| 71 | Gemini server-timing inside the row gap, 0/12,292 violations, W hi 3.12e-4 [S] | 9:1 | A harness change that inserts rows before the action |
| 72 | bash_progress floor rule 0/112,677 [S] | 19:1 | It is the same clock, so a failure would be a bug. That is why it is not evidence against an editor |
| 73 | Narration supported by its own log, STOP path +0.517 [+0.414, +0.618] against another agent; STOP path against the same agent's earlier narration positive (CI above 0; interval not stored, point value not quoted), but CONS url −0.002 [−0.090, +0.085] against it, a null [S] | 3:1 that the STOP sign persists; no bet on CONS | Part of it is agent-specific vocabulary (skeptic); the stricter same-agent control already removes the CONS url effect |
| 74 | Error clustering after cascade controls, CC 0.041 [0.031, 0.051] [S] | 3:1 CI | Other unmodelled cascades |
| 75 | The pre-registered outlier rule against chance: per-feature permutation null swechat 605 vs 550.1 [529, 571], cc_local 72 vs 98.5 [90, 107], aiv_cu 606 vs 648.0 [623, 671]; merged-feature null swechat 577 vs [498, 547], aiv_cu 468 vs [364, 405], cc_local 25 vs [1, 7] [S] | 2:1 that "beats chance or not" stays convention-dependent on a fresh sample | A feature set without redundant features, where the two nulls agree |
| 76 | collusion-wiki prose epochs after the save: all 7/582 = 0.012 [0.006, 0.025]; post-hoc fraction-form subset 0/459, W hi 0.0083 [S] | 3:1 that the all-prose rate stays ≤ 0.025 | The fraction split is post hoc, on one wiki, and the epochs were selected by scripts that print and save at once |
