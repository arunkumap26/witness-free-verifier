# Phase E new-corpus measurement: group agentcap_codex (agentcap, pub_codex)

- **Script:** `analysis/probes/phase_e_newcorp_agentcap_codex.py`. Run it with
  `PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_newcorp_agentcap_codex`. It takes about 2 minutes and is
  seeded: repeated runs gave identical labels.
- **Outputs:**
  - `analysis/out/phase_e/newcorp_measure_agentcap.json`: 45 cells, 9 of them with an ALIVE, WEAK or DEAD label.
  - `analysis/out/phase_e/newcorp_measure_pub_codex.json`: 22 cells, 1 with a label.
- **Build reports:** `analysis/out/phase_e/newcorp_build_{agentcap,pub_codex}_{B,E}.json`.
- **Caches:** `analysis/cache/{agentcap,pub_codex}_{B,E}.parquet`. H was never built, read or listed.

Numbers below come from those JSONs, with the path given. Sections marked **INTERPRETATION** are my reading. They are
not verdicts.

## What ran

**Caches.** The B and E caches were built with each loader's own `build_split()`. The loader code was not edited, so
its sha256 in the extension record still holds.

- **agentcap (D5 exclusions).** The D5 sessions were removed from the id list before parsing. B has 214 split ids, minus
  42 excluded, giving 172 sessions. E has 214 − 15 = 199 sessions. The script asserts that no excluded id is in either
  cache (`build.B` and `build.E`).
- **pub_codex.** B has 12 sessions and E has 12. There are no exclusions.
- **Secrets.** The loaders' redaction counts are in the build reports. A scan of both output JSONs found 0
  secret-pattern matches and 0 session ids.

**Units (D1 unit argument):**

| unit | sessions B / E | pairs B / E |
|---|---|---|
| agentcap/opencode → `swechat/opencode` | 85 / 95 | 996 / 1,119 |
| agentcap/pi → `agentcap/pi` | 87 / 104 | 1,568 / 1,735 |
| pub_codex → `swechat/codex` | 12 / 12 | 831 / 693 |

**Rows.** Every N6 row was run under its own rule on B, on E and on B ∪ E. Each cell shows the E label unless E is
INSUFFICIENT_N; in that case it shows the B label with the suffix "(B only)".

**NOT_BLIND (D6).** The suffix is on the P1, R1, N1, N3, N4 and N5g cells and on the two-clock cell. N1, N4 and N5g are
my extension of D6: they also read call→result latency.

**Artifact checks, run on B ∪ E for every N cell that reaches WEAK anywhere:**

- AC1 raw-source audit: 30 events.
- AC2 truncation.
- AC3 join.
- AC4 dominance. Per D2 the cluster is the stratum; the model and single-session clusters are checked too.
- AC5: NOT_RUN. There is no registered population table for new corpora.
- The four stratification axes.

Check effects are applied to the cell label.

## Cells

Labels are final (after checks). Each row gives B / E / B∪E and the deciding number.

### agentcap/opencode

| row | cell | B / E / B∪E | deciding number |
|---|---|---|---|
| P1 latency | NOT_TESTABLE (D1: G90/floors not calibrated on agentcap A, no pooled value) | — | analog run (post hoc, `swechat/opencode` Phase B thresholds): fp 0/588, AUC 1.000 [1.000, 1.000], G 48 pairs / 41 s on B∪E |
| P2 knowledge | DEAD | DEAD / DEAD / DEAD | S_path_any (S_deep n 6 < 100) E 108/267 = 0.40 [0.31, 0.51], 55 s; D = pooled 6 |
| P3a zero-error | NOT_TESTABLE (D1: L75) | — | the analog L75 = 185 would be INSUFFICIENT_N in any case (1 long session in B∪E) |
| P3b reaction | DEAD | DEAD / DEAD / DEAD | E effect R_fail − R_ok −0.008 [−0.058, 0.049]; 193 failed c_i from 60 s |
| P4a hex / P4b round | INSUFFICIENT_N | all INSUFFICIENT_N | T_orig hex 32 symbols (N_min 1,131); T_orig ints 9 distinct |
| R1–R5 | NOT_TESTABLE | — | 0 decodable ids (877 / 704 distinct `chatcmpl-`/other ids); no image usage; no external commit table; no raw counters; no external tally |
| N1 | INSUFFICIENT_N (NOT_BLIND) | all INSUFFICIENT_N | shell residuals 33 from 9 s (B∪E); RR 0.055; rho_hon −0.02 |
| N2 | **ALIVE** | ALIVE / ALIVE / ALIVE | E honest 0/417 (68 s; Wilson hi 0.009); recall at 0.8τ 0.974; τ 0.260 from A |
| N3 | INSUFFICIENT_N (NOT_BLIND) | INS / INS / WEAK | 16 / 14 sessions with ≥ 20 gaps; B∪E 30 s, rho 0.45 [0.33, 0.56] |
| N4 | INSUFFICIENT_N (NOT_BLIND) | — | W pairs at k ≥ 2: 9 in 3 s |
| N5a / b / d / f | INSUFFICIENT_N | — | determinism pairs 2; ls 73 / grep -n 61 / ls -l 68 outputs (B∪E); 0 error frames |
| N5c | NOT_TESTABLE (0 Claude Code markers) | — | — |
| N5e size | **WEAK** (cap) | INS / WEAK / WEAK | E: 1 family (grep, IQR 1.49) above comparator CI hi 1.21 |
| N5g cold start | INSUFFICIENT_N (NOT_BLIND) | INS / INS / WEAK | 27 / 26 eligible sessions (< 30) |

### agentcap/pi

This unit has no registered analogue and no error definition.

| row | cell | B / E / B∪E | deciding number |
|---|---|---|---|
| P1, N4 | NOT_TESTABLE (no Phase B no-human-wait class list for `agentcap/pi`; D1) | — | — |
| P2 | DEAD | DEAD / DEAD / DEAD | S_path_any E 317/583 = 0.54 [0.47, 0.62]; S_deep 0, because there is no error definition and so no first-try success |
| P3a, P3b, N5f | NOT_TESTABLE (no error definition for unit) | — | Pi records a native isError, which the frozen code does not read for this unit |
| P4a / P4b | INSUFFICIENT_N | — | hex T_orig 15 symbols; ints T_orig 513 distinct but from 8 sessions (< 10) |
| N1 | INSUFFICIENT_N (NOT_BLIND) | — | shell residuals 119 from 32 s (B∪E) |
| N2 | **WEAK** (was ALIVE; AC4 cap) | ALIVE / ALIVE / ALIVE | E honest 2/722 = 0.003 (hi 0.009); recall 0.997. AC4: pi/local holds 0.95 of events; leaving it out → INSUFFICIENT_N → UNTESTABLE_WITHOUT_DOMINANT → cap WEAK |
| N3 | **WEAK** (NOT_BLIND) | WEAK / WEAK / WEAK | E rho 0.28 [0.19, 0.38], 31 s; share rho_s ≤ 0 = 5/31 |
| N5b, N5d | INSUFFICIENT_N | — | B∪E only: grep -n 0/149 (27 s); ls 2/108; ls -l 0/103 |
| N5e | DEAD | WEAK / DEAD / DEAD | E 1 of 4 families above comparator |
| N5g | **WEAK** (NOT_BLIND) | WEAK / WEAK / WEAK | E median c 0.243 [0.163, 0.426] decades; share c ≤ 0 = 11/49 |

### pub_codex (D1 `swechat/codex`)

| row | cell | deciding number |
|---|---|---|
| N2 | **WEAK** (E ALIVE, capped) | E 5/134 = 0.037 (hi 0.065, 10 s), recall 1.0; B 9/142 = 0.063 (WEAK). AC4: gpt-5.5 holds 0.95 of events and codex_vscode 0.67 → leave-out INSUFFICIENT_N → cap WEAK |
| P1, P3a | NOT_TESTABLE (D1) | under the analog thresholds both would be INSUFFICIENT_N anyway: 2 qualified W pairs, because approval_policy 'never' is rare; no G tool; n_long 4 |
| everything else | INSUFFICIENT_N or NOT_TESTABLE | only 24 sessions in B∪E. P3b has 9 sessions with a failure (< 10). P2 S_path_any 91 / 105 (< 200). N1 has 0 residuals. R1: Codex logs no request id |

**Artifact checks on the WEAK-or-better N cells** (`cells.<row>.<unit>.artifact_checks`):

- AC1 found 0 of 30 differing in every audited cell (agentcap and pub_codex).
- AC2 and AC3 never changed a label.
- AC4 is structural here. The D2 cluster (stratum) has 2 values per unit, and the local route holds 0.84 to 0.95 of
  events. Every leave-out of the dominant stratum falls below the minimum n, so every agentcap/pi and pub_codex N cell is
  capped at WEAK.
  - Exception: agentcap/opencode N2 stays ALIVE, because the hf-router stratum alone is still ALIVE.
- No cell is CONFINED. Most axes are UNTESTABLE (fewer than 2 reportable strata).

## EXPLORATORY: two-clock consistency (agentcap; not pre-registered; NOT_BLIND)

Path: `exploratory_two_clock` and `cells.X_two_clock_created`.

**Inequality.** Take each response whose capture was joined (by response id, tool-call id or position). Its serving
process stamps an integer-second `created` time c_k. The check is:

> ts(last result or user event of the stream before the response) ≤ server time of the first chunk ≤ ts(first harness
> event of the response),

where the server time lies in [c_k, c_k + 1 s).

The two hosts' clocks may differ by an unknown constant offset θ per stream, so each response gives a range for θ:
lo_k = prev_ms − c_k − 1 s ≤ θ ≤ hi_k = first_ms − c_k. A stream is inconsistent if max lo − min hi > 2,000 ms, the
frozen R1 tolerance. The streams are computed with `prereg_e_common.bracket_streams`. The absolute variant fixes θ = 0.

| | B | E | B ∪ E |
|---|---|---|---|
| inconsistent streams | 0/149 (Wilson hi 0.025) | 0/146 (hi 0.026) | 0/295 (hi 0.013) |
| absolute (θ = 0) violations | 0/2,430 responses | 0/2,178 | 0/4,608 (per-event hi 0.0008) |
| tolerance 0 | 0 | 0 | 0 |
| 5 s back-date of one response (placebo power) | 56/149 = 0.38 | 53/146 = 0.36 | 0.37 |
| 30 s back-date | 137/149 = 0.92 | 136/146 = 0.93 | 0.93 |

More detail:

- **Slack.** U − L on consistent streams has p50 1.78 s and p95 14.6 s. With θ = 0, lo never exceeds −134 ms and hi is
  never below +14 ms.
- **By harness.** OpenCode: 0/120 streams. Pi: 0/175.
- **Pi tight variant.** This uses the request start (message.timestamp) as the lower bound and requires created_last ≤
  response end. Result: 0/3,042 responses and 0/175 streams, with p50 slack 0.60 s.
- **By route.** hf-router, a remote clock: 0/31 streams, 456 responses. Local: 0/264.

**INTERPRETATION:**

- **The bracket idea transfers.** A clock stamped outside the harness bounds every one of 4,608 responses, at 1 s
  resolution. A single 30 s back-date of one response is caught in about 93% of streams; a 5 s back-date in about 37%.
  That is close to the swechat Claude Code R1 placebo the prereg quotes (≈0.39 at 5 s, ≈0.975 at 30 s).
- **Two limits.**
  - The witness is operator-side. `created` comes from a local llama.cpp-style server or the HF Router, not from a
    first-party provider, and for local runs it is probably the same host clock as the harness. Only the 31 hf-router
    streams compare against a remote clock.
  - It is not blind (D6). Track B B5e and the A build report summarised these clocks.
- **The A build report's "host clock offset" guess does not hold on B/E.** That report read the q0.01 of −16.7 s
  ("trace end minus created_last") as a host clock offset. On B/E, hi_k is never below +14 ms. The negative values on A
  most likely come from OpenCode rows whose stamp is a part start, not the response end.

## Nulls (as prominent as the hits)

1. **P1, the strongest Phase B candidate, has no cell on either corpus.** D1 has no pooled G90 or floor. On
   agentcap/opencode, the post-hoc analog run looks like Phase B (fp 0/588, AUC 1.0 on B∪E). B and E alone have G below
   30 pairs (19 and 29). This is the main open decision; see below.
2. **R1 cannot run on these corpora.** Neither carries a decodable provider request id. agentcap's ids are
   operator-minted `chatcmpl-` ids with no embedded clock, and Codex logs none. The two-clock cell is the substitute, and
   it is exploratory.
3. **P2 is DEAD on both agentcap units:** 0.40 and 0.54 of first-mention paths are unsourced. S_path_any includes
   creation targets, which have no antecedent by construction (a known Phase B issue), so DEAD here partly measures
   that.
4. **P3b is DEAD on agentcap/opencode.** Agents retry after a failure no more often than after a success: R_fail 0.113
   against R_ok 0.105 on B∪E, 442 failed calls from 122 sessions.
5. **pub_codex is too small to decide almost anything.** It has 12 + 12 sessions, and the swechat/codex qualification
   (approval_policy 'never') leaves 2 qualified pairs in B∪E.
6. **16 agentcap cells are INSUFFICIENT_N (opencode 10, pi 6), and so are 13 pub_codex cells.** On agentcap this is a
   lack of coverage, not an absent signal: P4 has too few model-originated tokens, N1 too few repeats, N4 too little
   concurrency, and N5a/b/d/f too few eligible outputs. Label counts: agentcap opencode 1 ALIVE, 1 WEAK, 2 DEAD,
   8 NOT_TESTABLE; pi 3 WEAK, 2 DEAD, 11 NOT_TESTABLE; pub_codex 1 WEAK, 8 NOT_TESTABLE.

## Decisions for the orchestrator

- **D1 reading.** I applied D1 literally: no pooled value means NOT_TESTABLE. That removes P1 and P3a from every new
  corpus, and blocks the N1 positive control. The alternative reading would use the analogue unit's Phase B thresholds,
  which is how the frozen code looks them up by unit name. For agentcap/opencode that reading gives P1 analog ALIVE on
  B∪E and WEAK on B and on E, the G-arm minimum n deciding. It is stored as `analog_unit_run` so it can be adopted
  without re-running.
- **Pi registration.** Pi needs its own error definition (native isError) and a no-human-wait class list. Without them,
  P1, P3, N4 and N5f stay NOT_TESTABLE.
- **AC4 dominance under D2.** With the stratum as cluster, the 2-value route split caps almost every agentcap and
  pub_codex N cell at WEAK by construction. A cluster with more values (run, suite or model) would be a change_log
  decision.
