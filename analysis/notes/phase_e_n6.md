# Phase E N6: transfer grid, notes (INTERPRETATION)

Everything in this file is interpretation of `analysis/out/phase_e/n6_grid.json`, written by
`analysis/probes/phase_e_n6.py`. Every number below occurs in that JSON (checked with
`python -m analysis.probes.phase_e_n6 --check analysis/notes/phase_e_n6.md`). The grid itself is in
`analysis/TRANSFER_MATRIX.md`; the new and changed cells are appended to `analysis/DECISION_TABLE.md` under
"Phase E update". Figures: `analysis/out/phase_e/fig_transfer_matrix.png`, `fig_n7_recall.png` (data in `fig_data.json`).

**What this item is.** Assembly only. No IR cache, raw file or split was opened. Each of the 22 × 18 loaded cells comes
from a committed Phase B or Phase E output under the pre-registered fill rule. A cell that no item computed is
NOT_RUN or NOT_TESTABLE, never a copied or guessed label. 8 more columns (Track B corpora acquired but not loaded,
change_log D7) add 176 NOT_RUN cells and are left out of every count.

## Nulls first

- **Most of the grid is undecided.** Of 396 loaded cells, 172 are NOT_TESTABLE (a required field is missing), 110
  are INSUFFICIENT_N and 26 are NOT_RUN. Only 87 carry a verdict.
- **7 of 22 mechanisms have no cell at WEAK or better anywhere:** Probe 4a hex, R2 image ledger, N5a determinism, N5b
  sort order, N5c truncation boundary, N5d whitespace and N5f error fidelity.
- **5 loaded columns have no decided cell at all:** swechat/gemini, swechat/cursor, swechat/copilot,
  swechat/simple_text and pub_trace_commons.
- **The 26 NOT_RUN cells are not nulls.** 24 are Probe 1–4 cells on units that have an E split but no A1 candidate. No
  Phase E item re-ran the Phase B code on E for them, so their Phase B verdicts still stand for B only. A1 covered
  P1 on swechat/claude_code and swechat/opencode, P2 on swechat/claude_code (main thread), P3a on
  swechat/claude_code, and P4b on swechat/claude_code. The other 2 are R5 on swechat/codex and swechat/opencode, where n7_content
  computed no R5_LEDGER cells, so only the honest leg exists.
- **Nothing here is a detection of a real fabrication.** Recall comes from synthetic tampering. Probes 3a and 4b are
  honest-baseline rates.

## The transfer statement, read literally

- **Decided pairs: 218.** 90 transfer (both ≥ WEAK). 1 fails to transfer (ALIVE vs DEAD). 127 are neither: 66
  WEAK–DEAD and 61 DEAD–DEAD.
- **The single failing pair** is Probe 3a, the zero-error tail. It is ALIVE on swechat/claude_code (E: Z = 8/380 = 0.021
  W[0.011, 0.041]) and DEAD on cc_local (B only, Phase B run: Z 15/36 = 0.417 W[0.271, 0.578]). Both units are Claude
  Code logs, so the one strict failure to transfer happens inside one harness, not across two.
- **Transfer pairs are concentrated.** 45 of the 90 come from N2 token accounting alone. N2 is ≥ WEAK in 10 of the 12
  units that pass its field gate. The next largest contributors are Probe 1 with 10 and N5e with 10.
- **Why failure looks rare.** The statement can only fire on an ALIVE cell, and ALIVE is rare: 8 of 87 decided cells.
- **What the data supports instead** of "fabrication-detection signals do not transfer across harnesses":
  - ALIVE signals stay inside one or two units per mechanism. Only 2 mechanisms are ALIVE in two units: R1 in
    swechat/claude_code and tbench2, and N1 in swechat/claude_code and aiv_cc.
  - Most cross-corpus pairs are WEAK–DEAD or DEAD–DEAD rather than ALIVE–DEAD.
  - The secondary contribution should be phrased as "signals rarely reach ALIVE outside the unit they were found
    in", not as a measured failure to transfer.

## The 8 ALIVE cells

| Mechanism | Unit | Note |
|---|---|---|
| Probe 3a, zero-error tail | swechat/claude_code | A1 SURVIVES |
| Probe 4b, round numbers | tbench2 | Track B; its parameter-exclusion context is ALIVE |
| R1, request-id bracket | swechat/claude_code | Composed here from f1 + n7_timing; see below |
| R1, request-id bracket | tbench2 | NOT_BLIND (D6); one population stratum |
| R5, usage ledger | swechat/claude_code | E not blind |
| N1, conditional duration | swechat/claude_code | Shell scope; human-wait contaminated |
| N1, conditional duration | aiv_cc | Single-agent case study, B only |
| N2, token accounting | agentcap/opencode | Track B |

Two of the eight (tbench2 R1 and P4b) sit on a Track B corpus that is not blind for R1 (change_log D6).

## The checks did real work

- **Labels before the pre-registered artifact checks and kill tests hold 19 ALIVE cells; after them, 8.**
- **Cells lowered from ALIVE:**
  - P1: swechat/claude_code (K2 floor UNSTABLE), swechat/opencode and cc_local (AC4: dominant cluster, untestable
    without it).
  - P4b: swechat/claude_code and cc_local (F3: parameter exclusion keeps only WEAK).
  - R1: cc_local (AC4 cap) and pub_cc_hf (AC4 DOMINATED).
  - R2: aiv_cu (E ALIVE, but the Phase D kill rule fires on B u E at 44/807 = 0.0545, plus CONFINED).
  - N2: agentcap/pi and pub_codex.
  - N4: swechat/claude_code (CONFINED).
- **On the pre-check labels** the failing-pair count is still 1, and transfer pairs rise from 90 to 106.

## Sensitivity readings (same rule, different inputs)

- **The 11 Phase B units only:** 57 decided, 75 pairs, 24 transfer, 1 failing. The Track B corpora add most of the
  transfer pairs, through N2.
- **N2 aiv_cu.** The prereg decides N2 per model stratum here: 3 strata ALIVE, 3 WEAK and 4 DEAD.
  - Read as its worst stratum, it adds a second failing pair: N2 agentcap/opencode ALIVE vs aiv_cu DEAD.
  - Read as its best stratum, it adds transfer pairs (100 instead of 90).
  - Neither reading is the grid.
- **Probe 2 subagent stratum in place of the main thread:** 85 decided, 93 transfer, 1 failing.

## R1 was completed here (deviation)

f1_bracket.json left R1 at PENDING_N7, because the N7 output did not exist when it ran. The pre-registered proposal
rule needs both legs, so this script combined them:

- **swechat/claude_code: ALIVE.**
  - Honest leg, B u E pooled: 21/7008 streams = 0.00300 [0.00173, 0.00443].
  - The E bar hi is 0.00540.
  - N7 on E has 4 single-call types that DETECT. The best is time_response_early at 300 s: recall 491/500, CI lo
    0.9661, against FPR 3/500, CI hi 0.0175.
- **cc_local: WEAK (B only).**
  - Honest leg: 1/847 = 0.00118.
  - The N7 leg on B would allow ALIVE: id_swap_adjacent recall 174/174.
  - f1's AC4 cap (one project dominates) holds it at WEAK.

No new number was computed for either cell.

## Field gate versus item labels

- **The N6 fill rule puts the field gate first.** Where the A-split gate finds a required field absent, the grid shows
  NOT_TESTABLE even if the item itself wrote DEAD. The item's label is stored beside it.
- **N2 on swechat/gemini.** The unit is not GRANULAR on A (G1 below 0.9), although its B and E splits are GRANULAR. The
  N2 item marked it DEAD for lack of an A tau. Here it is NOT_TESTABLE. It is a candidate for a pre-registered A
  re-calibration, not a null.
- **tbench2 R4 runs the other way.** Its own A gate says no structured counters, by the unit-name rule. Its builder
  found the raw numLines field present in two Claude Code strata and ran R4, which came out WEAK. The grid keeps the
  builder's cell and carries the note in its suffix.

## What would change this (INTERPRETATION)

- **Re-running Probes 1–4 on E** for the 24 NOT_RUN cells, with the frozen Phase B code, would replace NOT_RUN with
  replication verdicts. PREREG_E 1.2 intended the N6 grid to do this; this assembly did not (logged deviation).
- **Loading the 8 acquired corpora** (176 cells) is the only way to widen the cross-harness evidence beyond 18 columns.
- **Harness versus sample size.** The grid cannot separate "the harness differs" from "the unit is small": 110 cells
  are INSUFFICIENT_N, and a cell that is ins-n in one unit and ALIVE in another is not evidence either way.
