# Transfer matrix: every mechanism × every corpus (Phase E, N6)

Built by `python -m analysis.probes.phase_e_n6` (`analysis/probes/phase_e_n6.py`) from Phase B outputs (committed) and Phase E outputs (not yet committed when this file was audited; their sha256 are under Sources), and nothing else (assembly: no cache, raw source or split was opened). This file is generated: re-running the script overwrites the audit edits logged in `analysis/out/phase_e/audit_log.json`. Every cell, its source path, its B / E / pre-check labels and its deciding number are in `analysis/out/phase_e/n6_grid.json` (`cells.<row>.<column>`). The script checks that every number in this file occurs in that JSON. Pre-registration: `analysis/PREREG_E.md` section 3, `prereg_e.json` `n6_transfer_grid`.

- **Cell vocabulary** (prereg): ALIVE, WEAK, DEAD, INSUFFICIENT_N (ins-n), INCONCLUSIVE, NOT_TESTABLE(<missing field>) (n/t), NOT_RUN(<reason>) (n/r). One added reading: `strata` = the N2 aiv_cu cell, which the prereg decides per model stratum (A/W/D = strata ALIVE/WEAK/DEAD).
- **Marks.** ᴮ = B only (unit has no E, or E was INSUFFICIENT_N); * = not blind (R3–R5 'E not blind'; Track B corpora 'NOT_BLIND': change_log D6 names R1/F1, Probe 1 and N3, and some builders also marked N1, N4 and N5g; such cells are replications on new data under frozen thresholds, not held-out confirmations); ↓ = the label after the pre-registered artifact checks / kill tests is lower than the rule's own E (or B) verdict.
- **Fill rule.** Field gate first; then the E verdict where the unit has E (B where E is INSUFFICIENT_N or absent). Probes 1–4: an A1 candidate's final label where one exists, the Phase B verdict for units without E ('B only (Phase B run)'), and NOT_RUN where the unit has E but no Phase E item re-ran it (the Phase B verdict is beside it in the JSON, never in it). R1 is composed here from f1_bracket.json and n7_timing.json (see deviations in the JSON).
- **Every positive in this grid is a synthetic tamper or an honest-baseline rate.** No corpus contains a known real fabricated tool result.
- **aiv_cc is a single-agent case study** (one agent, one SDK session) in every cell and count below. **cc_local is private**: aggregates and labels only.
- **Not every cell received the same checks (AUDIT NOTE).** A missing ↓ does not mean a cell passed every check. (a) Probe 1–4 cells on the Track B corpora carry the Phase B rule label only: no artifact check and no A1 kill test (F3, K1–K3) was run on them, while the swechat and cc_local cells of the same rows were lowered by those checks; Probe 4b tbench2 ALIVE is such a cell (`newcorp_measure_tbench2.json` `checks` has no P4 entry; its F3 block is context only). (b) AC5 was NOT_RUN on every Track B cell and on aiv_cc (no population table). (c) R1 tbench2 is one submission (one agent, one model; stratum WozCode__Claude-Opus-4.6). Its measurement group recorded AC4 as label only (`checks.R1.AC4_dominance`: one stratum by construction) and the after-checks label ALIVE; the prereg names that label-only reading for aiv_cc only. The orchestrator resolution in `analysis/out/phase_e/newcorp_resolutions.json` (change_log D2 + survival rule) applies the cc_local R1 reading (one cluster, empty leave-out, UNTESTABLE_WITHOUT_DOMINANT, cap WEAK): the cell is WEAK↓ with its numbers unchanged, and the pre-resolution label ALIVE is kept as `label_before_resolution` in `n6_grid.json` `cells.R1_bracket['tbench2']`.

## Grid

| Mechanism | swechat/claude_code | swechat/codex | swechat/opencode | swechat/gemini | swechat/cursor | swechat/copilot | swechat/simple_text | cc_local (private) | aiv_cc (single-agent case study) | aiv_cu | whowhen | agentcap/opencode | agentcap/pi | glm_tb21 | pub_cc_hf | pub_codex | pub_trace_commons | tbench2 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Probe 1: latency physics | WEAK↓ | n/r | WEAK↓ | n/r | n/t | n/t | n/t | WEAKᴮ↓ | WEAKᴮ | n/t | n/t | n/t* | n/t* | n/t* | WEAK* | n/t* | ins-n* | n/t* |
| Probe 2: knowledge precedence (main thread) | WEAK | n/r | n/r | n/r | n/t | n/t | n/t | DEADᴮ | DEADᴮ↓ | n/r | ins-nᴮ | DEAD | DEAD | ins-n | DEAD | ins-n | ins-n | DEAD |
| Probe 3a: zero-error tail | ALIVE | n/r | n/r | n/r | n/t | n/t | n/t | DEADᴮ | ins-nᴮ | n/r | WEAKᴮ | n/t | n/t | n/t | ins-n | n/t | ins-n | n/t |
| Probe 3b: retry reaction to failure | n/r | n/r | n/r | n/r | n/t | n/t | n/t | WEAKᴮ | DEADᴮ | n/r | DEADᴮ | DEAD | n/t | n/t | DEAD | ins-n | ins-n | n/t |
| Probe 4a: hex digit uniformity | n/r | n/r | n/r | n/r | n/t | n/t | n/t | ins-nᴮ | ins-nᴮ | n/r | ins-nᴮ | ins-n | ins-n | ins-n | ins-n | ins-n | ins-n | ins-n |
| Probe 4b: round numbers | WEAK↓ | n/r | n/r | n/r | n/t | n/t | n/t | WEAKᴮ↓ | ins-nᴮ | n/r | ins-nᴮ | ins-n | ins-n | ins-n | ins-n | ins-n | ins-n | ALIVE |
| R1: request-id clock bracket | ALIVE | n/t | n/t | n/t | n/t | n/t | n/t | WEAKᴮ↓ | n/t | n/t | n/t | n/t* | n/t* | n/t* | WEAK*↓ | n/t* | ins-n* | WEAK*↓ |
| R2: image-token ledger | n/t | n/t | n/t | n/t | n/t | n/t | n/t | n/t | n/t | DEAD↓ | n/t | n/t | n/t | n/t | n/t | n/t | n/t | n/t |
| R3: git execution window | WEAK* | ins-nᴮ* | ins-nᴮ* | ins-nᴮ* | n/t | n/t | n/t | n/t | n/t | n/t | n/t | n/t | n/t | n/t | n/t | n/t | n/t | n/t |
| R4: harness dual-rendering recount | WEAK* | n/t | n/t | n/t | n/t | n/t | n/t | WEAKᴮ | n/t | n/t | n/t | n/t | n/t | n/t | ins-n | n/t | ins-n | WEAK |
| R5: usage-ledger reconciliation | ALIVE* | n/r* | n/r* | ins-nᴮ* | n/t | n/t | n/t | n/t | n/t | n/t | n/t | n/t | n/t | n/t | n/t | n/t | n/t | n/t |
| N1: conditional duration model | ALIVE | ins-nᴮ | ins-nᴮ | ins-nᴮ | n/t | n/t | n/t | ins-nᴮ | ALIVEᴮ | n/t | n/t | ins-n* | ins-n* | n/t* | ins-n | ins-n* | ins-n | WEAK* |
| N2: token accounting | WEAK | WEAK | WEAK | n/t | n/t | n/t | n/t | WEAKᴮ | n/t | strata 3A/3W/4D | n/t | ALIVE | WEAK↓ | WEAK | WEAK | WEAK↓ | ins-n | WEAK |
| N3: reaction time to a result | DEAD | WEAK | DEAD | ins-nᴮ | n/t | n/t | n/t | ins-nᴮ | DEADᴮ↓ | n/t | n/t | ins-n* | WEAK* | ins-n* | DEAD* | ins-n* | ins-n* | WEAK* |
| N4: concurrency physics | WEAK↓ | DEAD↓ | WEAK | ins-nᴮ | n/t | n/t | n/t | DEADᴮ↓ | WEAKᴮ | n/t | n/t | ins-n* | n/t* | n/t* | ins-n | ins-n* | ins-n | n/t* |
| N5a: repeat-command determinism | DEAD | ins-nᴮ | ins-nᴮ | ins-nᴮ | n/t | n/t | n/t | ins-nᴮ | ins-nᴮ | ins-nᴮ | n/t | ins-n | ins-n | ins-n | ins-n | ins-n | ins-n | DEAD |
| N5b: sort-order violations | DEAD | DEAD | ins-n | ins-n | n/t | n/t | n/t | DEADᴮ | ins-nᴮ | DEAD | n/t | ins-n | ins-n | ins-n | ins-n | ins-n | ins-n | DEAD |
| N5c: truncation boundary | DEAD | n/t | ins-n | n/t | n/t | n/t | n/t | ins-nᴮ | ins-nᴮ | n/t | n/t | n/t | n/t | ins-n | ins-n | n/t | ins-n | ins-n |
| N5d: whitespace fingerprints | DEAD | ins-n | ins-n | ins-n | n/t | n/t | n/t | DEADᴮ | ins-nᴮ | DEAD | n/t | ins-n | ins-n | ins-n | ins-n | ins-n | ins-n | DEAD |
| N5e: output-size distribution | WEAK | DEAD | DEAD | ins-nᴮ | n/t | n/t | n/t | DEADᴮ↓ | WEAKᴮ | WEAK | n/t | WEAK | DEAD | ins-n | WEAK | ins-n | ins-n | DEAD |
| N5f: error-message fidelity | ins-nᴮ | n/t | n/t | n/t | n/t | n/t | n/t | ins-nᴮ | ins-nᴮ | n/t | n/t | ins-n | n/t | n/t | ins-n | ins-n | ins-n | n/t |
| N5g: cold-start signature | DEAD | DEAD | DEAD | ins-nᴮ | n/t | n/t | n/t | WEAKᴮ | WEAKᴮ | n/t | n/t | ins-n* | WEAK* | n/t* | ins-n | ins-n* | ins-n | DEAD* |

Not loaded (change_log D7, time budget): openhands_eval, tracelab-uw, cli-pi-hf, miniswe, sweagent-combo2, osworld, webarena-infinity, openhands-feedback. All 22 cells of each of these 8 columns are NOT_RUN(not loaded) and are left out of every count below.

## Transfer statement, evaluated mechanically

Rule (prereg): a mechanism TRANSFERS between two testable units if both cells are ≥ WEAK; it FAILS TO TRANSFER if one is ALIVE and the other DEAD. Pairs are formed among the decided cells (ALIVE / WEAK / DEAD) of the 18 loaded columns. 'Testable' = passed the field gate (NOT_RUN cells that passed it count as testable but undecided).

| Mechanism | testable | decided | ALIVE | WEAK | DEAD | ins-n | n/r | n/t | decided pairs | TRANSFER pairs | FAIL pairs (ALIVE–DEAD) | WEAK–DEAD | DEAD–DEAD | statement |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Probe 1: latency physics | 8 | 5 | 0 | 5 | 0 | 1 | 2 | 10 | 10 | 10 | 0 | 0 | 0 | TRANSFERS in every decided pair |
| Probe 2: knowledge precedence (main thread) | 15 | 7 | 0 | 1 | 6 | 4 | 4 | 3 | 21 | 0 | 0 | 6 | 15 | no failing pair; not every pair transfers |
| Probe 3a: zero-error tail | 10 | 3 | 1 | 1 | 1 | 3 | 4 | 8 | 3 | 1 | 1 | 1 | 0 | FAILS TO TRANSFER in >= 1 pair |
| Probe 3b: retry reaction to failure | 12 | 5 | 0 | 1 | 4 | 2 | 5 | 6 | 10 | 0 | 0 | 4 | 6 | no failing pair; not every pair transfers |
| Probe 4a: hex digit uniformity | 15 | 0 | 0 | 0 | 0 | 10 | 5 | 3 | 0 | 0 | 0 | 0 | 0 | no decided pair |
| Probe 4b: round numbers | 15 | 3 | 1 | 2 | 0 | 8 | 4 | 3 | 3 | 3 | 0 | 0 | 0 | TRANSFERS in every decided pair |
| R1: request-id clock bracket | 5 | 4 | 1 | 3 | 0 | 1 | 0 | 13 | 6 | 6 | 0 | 0 | 0 | TRANSFERS in every decided pair |
| R2: image-token ledger | 1 | 1 | 0 | 0 | 1 | 0 | 0 | 17 | 0 | 0 | 0 | 0 | 0 | no decided pair |
| R3: git execution window | 4 | 1 | 0 | 1 | 0 | 3 | 0 | 14 | 0 | 0 | 0 | 0 | 0 | no decided pair |
| R4: harness dual-rendering recount | 5 | 3 | 0 | 3 | 0 | 2 | 0 | 13 | 3 | 3 | 0 | 0 | 0 | TRANSFERS in every decided pair |
| R5: usage-ledger reconciliation | 4 | 1 | 1 | 0 | 0 | 1 | 2 | 14 | 0 | 0 | 0 | 0 | 0 | no decided pair |
| N1: conditional duration model | 12 | 3 | 2 | 1 | 0 | 9 | 0 | 6 | 3 | 3 | 0 | 0 | 0 | TRANSFERS in every decided pair |
| N2: token accounting | 12 | 10 | 1 | 9 | 0 | 1 | 0 | 6 | 45 | 45 | 0 | 0 | 0 | TRANSFERS in every decided pair |
| N3: reaction time to a result | 13 | 7 | 0 | 3 | 4 | 6 | 0 | 5 | 21 | 3 | 0 | 12 | 6 | no failing pair; not every pair transfers |
| N4: concurrency physics | 10 | 5 | 0 | 3 | 2 | 5 | 0 | 8 | 10 | 3 | 0 | 6 | 1 | no failing pair; not every pair transfers |
| N5a: repeat-command determinism | 14 | 2 | 0 | 0 | 2 | 12 | 0 | 4 | 1 | 0 | 0 | 0 | 1 | no failing pair; not every pair transfers |
| N5b: sort-order violations | 14 | 5 | 0 | 0 | 5 | 9 | 0 | 4 | 10 | 0 | 0 | 0 | 10 | no failing pair; not every pair transfers |
| N5c: truncation boundary | 8 | 1 | 0 | 0 | 1 | 7 | 0 | 10 | 0 | 0 | 0 | 0 | 0 | no decided pair |
| N5d: whitespace fingerprints | 14 | 4 | 0 | 0 | 4 | 10 | 0 | 4 | 6 | 0 | 0 | 0 | 6 | no failing pair; not every pair transfers |
| N5e: output-size distribution | 14 | 10 | 0 | 5 | 5 | 4 | 0 | 4 | 45 | 10 | 0 | 25 | 10 | no failing pair; not every pair transfers |
| N5f: error-message fidelity | 7 | 0 | 0 | 0 | 0 | 7 | 0 | 11 | 0 | 0 | 0 | 0 | 0 | no decided pair |
| N5g: cold-start signature | 12 | 7 | 0 | 3 | 4 | 5 | 0 | 6 | 21 | 3 | 0 | 12 | 6 | no failing pair; not every pair transfers |

**Totals over the grid** (22 mechanisms × 18 loaded columns = 396 cells): testable 224, decided 87 (ALIVE 7, WEAK 41, DEAD 39), INSUFFICIENT_N 110, INCONCLUSIVE 0, NOT_RUN 26, NOT_TESTABLE 172, per-stratum 1. Decided pairs 218: TRANSFER 90, FAIL TO TRANSFER 1, WEAK–DEAD 66, DEAD–DEAD 61.

- Mechanisms with at least one decided pair: 16 of 22.
- Mechanisms that FAIL TO TRANSFER in at least one pair: 1.
- Mechanisms whose every decided pair TRANSFERS: 6.
- Mechanisms ALIVE in two or more units: 1; ≥ WEAK in two or more units: 11; no cell ≥ WEAK anywhere: 7.

### Failing pairs (one ALIVE, one DEAD)

- Probe 3a: zero-error tail: cc_local (DEAD) vs swechat/claude_code (ALIVE)

### Transferring pairs (both ≥ WEAK)

- Probe 1: latency physics: aiv_cc – cc_local; aiv_cc – pub_cc_hf; aiv_cc – swechat/claude_code; aiv_cc – swechat/opencode; cc_local – pub_cc_hf; cc_local – swechat/claude_code; cc_local – swechat/opencode; pub_cc_hf – swechat/claude_code; pub_cc_hf – swechat/opencode; swechat/claude_code – swechat/opencode
- Probe 3a: zero-error tail: swechat/claude_code – whowhen
- Probe 4b: round numbers: cc_local – swechat/claude_code; cc_local – tbench2; swechat/claude_code – tbench2
- R1: request-id clock bracket: cc_local – pub_cc_hf; cc_local – swechat/claude_code; cc_local – tbench2; pub_cc_hf – swechat/claude_code; pub_cc_hf – tbench2; swechat/claude_code – tbench2
- R4: harness dual-rendering recount: cc_local – swechat/claude_code; cc_local – tbench2; swechat/claude_code – tbench2
- N1: conditional duration model: aiv_cc – swechat/claude_code; aiv_cc – tbench2; swechat/claude_code – tbench2
- N2: token accounting: agentcap/opencode – agentcap/pi; agentcap/opencode – cc_local; agentcap/opencode – glm_tb21; agentcap/opencode – pub_cc_hf; agentcap/opencode – pub_codex; agentcap/opencode – swechat/claude_code; agentcap/opencode – swechat/codex; agentcap/opencode – swechat/opencode; agentcap/opencode – tbench2; agentcap/pi – cc_local; agentcap/pi – glm_tb21; agentcap/pi – pub_cc_hf; agentcap/pi – pub_codex; agentcap/pi – swechat/claude_code; agentcap/pi – swechat/codex; agentcap/pi – swechat/opencode; agentcap/pi – tbench2; cc_local – glm_tb21; cc_local – pub_cc_hf; cc_local – pub_codex; cc_local – swechat/claude_code; cc_local – swechat/codex; cc_local – swechat/opencode; cc_local – tbench2; glm_tb21 – pub_cc_hf; glm_tb21 – pub_codex; glm_tb21 – swechat/claude_code; glm_tb21 – swechat/codex; glm_tb21 – swechat/opencode; glm_tb21 – tbench2; pub_cc_hf – pub_codex; pub_cc_hf – swechat/claude_code; pub_cc_hf – swechat/codex; pub_cc_hf – swechat/opencode; pub_cc_hf – tbench2; pub_codex – swechat/claude_code; pub_codex – swechat/codex; pub_codex – swechat/opencode; pub_codex – tbench2; swechat/claude_code – swechat/codex; swechat/claude_code – swechat/opencode; swechat/claude_code – tbench2; swechat/codex – swechat/opencode; swechat/codex – tbench2; swechat/opencode – tbench2
- N3: reaction time to a result: agentcap/pi – swechat/codex; agentcap/pi – tbench2; swechat/codex – tbench2
- N4: concurrency physics: aiv_cc – swechat/claude_code; aiv_cc – swechat/opencode; swechat/claude_code – swechat/opencode
- N5e: output-size distribution: agentcap/opencode – aiv_cc; agentcap/opencode – aiv_cu; agentcap/opencode – pub_cc_hf; agentcap/opencode – swechat/claude_code; aiv_cc – aiv_cu; aiv_cc – pub_cc_hf; aiv_cc – swechat/claude_code; aiv_cu – pub_cc_hf; aiv_cu – swechat/claude_code; pub_cc_hf – swechat/claude_code
- N5g: cold-start signature: agentcap/pi – aiv_cc; agentcap/pi – cc_local; aiv_cc – cc_local

## Sensitivity readings (same rule, different inputs; none is the grid)

- **The 11 Phase B units only (Track B columns left out).** decided 57 (ALIVE 5, WEAK 26, DEAD 26); decided pairs 75: TRANSFER 24, FAIL 1; mechanisms with a failing pair 1.
- **Labels before artifact checks / kill tests (the rule's own E-or-B verdict).** decided 87 (ALIVE 19, WEAK 35, DEAD 33); decided pairs 218: TRANSFER 106, FAIL 1; mechanisms with a failing pair 1.
- **N2 aiv_cu read as its best stratum (ALIVE).** decided 88 (ALIVE 8, WEAK 41, DEAD 39); decided pairs 228: TRANSFER 100, FAIL 1; mechanisms with a failing pair 1.
- **N2 aiv_cu read as its worst stratum (DEAD).** decided 88 (ALIVE 7, WEAK 41, DEAD 40); decided pairs 228: TRANSFER 90, FAIL 2; mechanisms with a failing pair 2.
- **Probe 2 subagent stratum in place of the main thread.** decided 85 (ALIVE 7, WEAK 43, DEAD 35); decided pairs 207: TRANSFER 93, FAIL 1; mechanisms with a failing pair 1.

## Per-column counts

| Column | ALIVE | WEAK | DEAD | ins-n | INCONC | n/r | n/t | strata |
|---|---|---|---|---|---|---|---|---|
| swechat/claude_code | 4 | 8 | 6 | 1 | 0 | 2 | 1 | 0 |
| swechat/codex | 0 | 2 | 4 | 4 | 0 | 7 | 5 | 0 |
| swechat/opencode | 0 | 3 | 3 | 6 | 0 | 6 | 4 | 0 |
| swechat/gemini | 0 | 0 | 0 | 10 | 0 | 6 | 6 | 0 |
| swechat/cursor | 0 | 0 | 0 | 0 | 0 | 0 | 22 | 0 |
| swechat/copilot | 0 | 0 | 0 | 0 | 0 | 0 | 22 | 0 |
| swechat/simple_text | 0 | 0 | 0 | 0 | 0 | 0 | 22 | 0 |
| cc_local (private) | 0 | 7 | 6 | 6 | 0 | 0 | 3 | 0 |
| aiv_cc (single-agent case study) | 1 | 4 | 3 | 8 | 0 | 0 | 6 | 0 |
| aiv_cu | 0 | 1 | 3 | 1 | 0 | 5 | 11 | 1 |
| whowhen | 0 | 1 | 1 | 3 | 0 | 0 | 17 | 0 |
| agentcap/opencode | 1 | 1 | 2 | 10 | 0 | 0 | 8 | 0 |
| agentcap/pi | 0 | 3 | 2 | 6 | 0 | 0 | 11 | 0 |
| glm_tb21 | 0 | 1 | 0 | 9 | 0 | 0 | 12 | 0 |
| pub_cc_hf | 0 | 4 | 3 | 12 | 0 | 0 | 3 | 0 |
| pub_codex | 0 | 1 | 0 | 13 | 0 | 0 | 8 | 0 |
| pub_trace_commons | 0 | 0 | 0 | 19 | 0 | 0 | 3 | 0 |
| tbench2 | 1 | 5 | 6 | 2 | 0 | 0 | 8 | 0 |

## Where nothing is decided, plainly

- Loaded columns with no decided cell at all: swechat/gemini, swechat/cursor, swechat/copilot, swechat/simple_text, pub_trace_commons.
- Columns with decided cells but none ≥ WEAK: none.
- Mechanisms with no cell ≥ WEAK in any loaded column: Probe 4a: hex digit uniformity; R2: image-token ledger; N5a: repeat-command determinism; N5b: sort-order violations; N5c: truncation boundary; N5d: whitespace fingerprints; N5f: error-message fidelity.
- 26 loaded cells are NOT_RUN: the field gate passed but no Phase E item produced a verdict (mostly Probes 1–4 on units with E that no A1 candidate covered). They are not nulls.

## INTERPRETATION (not data)

A failure to transfer needs an ALIVE cell opposite a DEAD one, and ALIVE cells are rare (7 of 87 decided cells), so only 1 of 218 decided pairs fails to transfer (Probe 3a: zero-error tail: cc_local DEAD vs swechat/claude_code ALIVE). 90 pairs transfer (both >= WEAK), 45 of them from N2: token accounting alone; the other 127 are WEAK–DEAD (66) or DEAD–DEAD (61), which the pre-registered statement counts as neither. 1 of 22 mechanisms fails to transfer in at least one pair, 1 is ALIVE in two or more units, and 7 have no cell at WEAK or better anywhere. The artifact checks and kill tests matter: before them the same cells hold 19 ALIVE, after them 7. Most of the grid cannot be decided at all: 172 NOT_TESTABLE, 26 NOT_RUN and 110 INSUFFICIENT_N of 396 loaded cells. Read strictly, the grid does not show widespread failure to transfer; it shows that strong signals are confined to one or two units per mechanism and that most mechanism × corpus cells are undecidable or at most WEAK. ALIVE cells (7): Probe 3a: zero-error tail in swechat/claude_code (honest baseline only; no positive control); Probe 4b: round numbers in tbench2 (honest-baseline rate; Phase B rule only, no artifact check or kill test); R1: request-id clock bracket in swechat/claude_code; R5: usage-ledger reconciliation in swechat/claude_code (E not blind); N1: conditional duration model in swechat/claude_code; N1: conditional duration model in aiv_cc (single-agent case study, B only, unreplicated; AC5 not run); N2: token accounting in agentcap/opencode (AC5 not run). The one mechanism ALIVE in two or more units (N1) reaches that count only through a caveated cell (N1 aiv_cc). R1 tbench2, ALIVE before the orchestrator resolution, is WEAK after it (AC4 cap; see the audit note above), so R1 is ALIVE in swechat/claude_code only.

## Sources

- `analysis/out/phase_e/a1_p1_p3.json` sha256 `05b63d8451e96a65…`
- `analysis/out/phase_e/a1_p2_p4_f3.json` sha256 `9ebd5e5e89e49920…`
- `analysis/out/phase_e/decision_table.json` sha256 `e3747254f75a509a…`
- `analysis/out/phase_e/f1_bracket.json` sha256 `e0bbbd598d369505…`
- `analysis/out/phase_e/f2_floor_shift.json` sha256 `ce313640eaac73de…`
- `analysis/out/phase_e/f3_round.json` sha256 `d1cb643788996f67…`
- `analysis/out/phase_e/n1.json` sha256 `398b4723e90440a8…`
- `analysis/out/phase_e/n2.json` sha256 `e924a2978e873be0…`
- `analysis/out/phase_e/n3.json` sha256 `64865fdeb491ff48…`
- `analysis/out/phase_e/n4_n5cg.json` sha256 `995bca333eddef93…`
- `analysis/out/phase_e/n5_battery.json` sha256 `fe2d9a7b156c9d59…`
- `analysis/out/phase_e/n7_content.json` sha256 `5c677a8138f24097…`
- `analysis/out/phase_e/n7_timing.json` sha256 `e7899b2ec5e1b130…`
- `analysis/out/phase_e/newcorp_measure_agentcap.json` sha256 `40816aef748decb0…`
- `analysis/out/phase_e/newcorp_measure_glm_tb21.json` sha256 `bad548187187d371…`
- `analysis/out/phase_e/newcorp_measure_pub_cc_hf.json` sha256 `3679fade25339216…`
- `analysis/out/phase_e/newcorp_measure_pub_codex.json` sha256 `0ef8ff1980d0f49e…`
- `analysis/out/phase_e/newcorp_measure_pub_trace_commons.json` sha256 `6115363ff575cc87…`
- `analysis/out/phase_e/newcorp_measure_tbench2.json` sha256 `b2c6237101df0d1f…`
- `analysis/out/phase_e/newcorp_resolutions.json` sha256 `5008f509dec292e2…`
- `analysis/out/phase_e/r2_r3.json` sha256 `5b5c3305bd3d9338…`
- `analysis/out/phase_e/r4_r5.json` sha256 `d3e02c6902407fdf…`
- `analysis/out/probe_1.json` sha256 `76efcb0d897dd743…`
- `analysis/out/probe_2.json` sha256 `1bfcced9ba02190a…`
- `analysis/out/probe_3.json` sha256 `29a1e1f644fa5a4d…`
- `analysis/out/probe_4.json` sha256 `8f04b0918ed30a3d…`
- `analysis/prereg.json` sha256 `3189a3260e9ed220…`
- `analysis/prereg_e.json` sha256 `568d423f0e061f9a…`
- `analysis/probes/prereg_e_common.py (sha256_lf)` sha256 `31924af28f05d096…`
