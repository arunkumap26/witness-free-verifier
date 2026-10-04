# Phase C lens: identifiers as data (ids_and_clocks_in_ids)

Script: `analysis/probes/phase_c_ids_and_clocks_in_ids.py`. Data: `analysis/out/phase_c/ids_and_clocks_in_ids.json`.
Run: `PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_c_ids_and_clocks_in_ids` (about 2 minutes, single process).
Inputs are the IR caches only. The primary split is B: swechat 2,000 sessions, cc_local 186, aiv_cc 189, aiv_cu 2,000,
whowhen 111 (`inputs`). Split A is a holdout, used only to re-run the time-decoding agreement (`clocks_holdout_A`),
because I read the id layouts off split-B data while exploring.

Every number below is in the JSON. The path after each number is relative to its root. `[a, b]` is a session-clustered
bootstrap 95% CI. cc_local outputs are aggregates only, and the JSON holds no cc_local id value: I checked that 0 cc_local
id strings appear in it.

Pre-registration is in `prereg`: the bands, the 2 s / 3 s tolerances, the plausible-time window, the bracket rule, and
the family regexes. Every change made after a dev run is listed, with its reason, in `prereg.changes_after_dev_run`.
Those changes are:
- the "> 1 day off means a chance hit" rule for Anthropic ids;
- per-stream ordering;
- the UUID field counts;
- the `msg_datetime14` family;
- the Codex `ws_` layout;
- the T1 classes;
- the whole-hour split;
- the copy cross-tab;
- excluding the release's `REDACTED` placeholder ids from the copy checks.

---------------------------------------------------------------------------------------------------------------------

## Part A. Numbers

### A1. Decoded id layouts (P2e/P2f, `bits`, `epochs`, `census`)

**Anthropic ids are base58 strings that carry a 128-bit value after `<prefix>_01`.** In the decoded value, the RFC 9562
version field sits at bits 76-79 and the variant field at bits 62-63.

- **Request ids (`req_011C…`) are UUIDv7: a 48-bit unix-ms timestamp, then version 7, then variant 2.**
  - Every request id in every corpus has this shape: swechat 154,815/154,815 (`bits.swechat.anthropic_req.time_format`)
    and cc_local 31,085/31,085. A uniform 128-bit value would carry it 2,418.98 and 485.70 times respectively.
  - The 7 biased bits are exactly 62, 63 and 75-79.
- **Message ids changed format.**
  - Before the switch they are uniform 128-bit random values. In swechat (Jan-Apr 2026), 156,277 msg ids show 0 biased
    bits, and 2,360 carry the v4 shape where 2,441.8 would be expected by chance (`bits.swechat.anthropic_msg.random_format`).
    aiv_cc shows the same: 0 biased bits.
  - After the switch they are UUIDv7: cc_local 30,680/30,680, aiv_cu 8,232 of 8,240.
  - In aiv_cu the switch falls on 2026-07-06 (`epochs.aiv_cu.anthropic_msg_switch`). The first UUIDv7 event is at
    20:23:44 UTC and the last random-format event is at 20:37:04 UTC. 81 old-format events fall after the first new one, and 3
    new-format events fall before the last old one.
  - By month, aiv_cu has 0 UUIDv7 msg ids in 2025-04 through 2026-06. In 2026-07 it has 2,946 UUIDv7 against 870 other.
    In 2026-08 it has 3,314 against 0, and in 2026-09 1,972 against 0 (`epochs.aiv_cu.anthropic_msg`).
- **Tool-use ids (`toolu_`) are random 128-bit values in every month observed except the latest.** The latest values
  carry the UUIDv4 shape:
  - cc_local: 20,415 uuid4-shaped against 16,123 other (`epochs.cc_local.anthropic_toolu`), with the bias at bits
    62, 63 and 76-79.
  - aiv_cu: 59 uuid4-shaped in 2026-08 against 1,003 in 2026-09 (`epochs.aiv_cu.anthropic_toolu`).
  - In swechat the uuid4 shape stays at chance level: 2,947 observed against 3,022.25 expected.
- **Chance hits.** A random-format id can decode to a plausible time by chance. Observed counts match the expectation:
  - swechat msg: 55 observed against 52.78 expected (`clocks.swechat.api_msg_id|anthropic_msg`);
  - aiv_cc msg: 12 against 11.93.
  - All of them are more than 1 day off the event (`n_time_format_abs_offset_gt_1day`).
- Positional entropy separates the layouts (`census.*.positional_entropy.entropy_bits_sum`):

  | id type | bits |
  |---|---|
  | random toolu / msg | 128.0 |
  | UUIDv4 entry uuids | 122.0 |
  | UUIDv7 request ids | 112.6 (swechat), 110.5 (cc_local) |
  | OpenAI `call_` | 142.8 |
  | Gemini 8-char base36 call ids | 41.3 |
  | Gemini `call_<digits>` | 19.5 |
  | Kimi-style `tool:N` | 6.2 |

Other layouts that carry time:
- **OpenAI Responses item ids** (`fc_`, `msg_`, …; aiv_cu): there are two hex layouts.
  - `hex48_time_first` appears only in 2025-08 and 2025-09.
  - `hex50_prefix16_00_time` appears from 2025-09 on (`epochs.aiv_cu.openai_item_hex`).
  - In the hex50 layout the first 16 hex digits are constant within a session: 472 sessions, each with exactly 1 prefix,
    and 0 prefixes shared across sessions (`bits.aiv_cu.openai_item_hex_segments`).
  - Codex `ws_` ids use the same layout with byte `01` (50/50, `clocks.swechat.call_id|openai_item_hex`).
- **Gemini responseId** (aiv_cu): bytes 0-3 hold little-endian unix seconds. Byte 3 takes 2 distinct values, byte 11
  takes 1, and bytes 9 and 10 take 12 each (`bits.aiv_cu.gemini_response_id_bytes`).
- **OpenCode** `ses_`/`msg_`/`prt_`: 12 hex digits encode (ms * 4096 + counter) mod 2^48, bitwise-negated for `ses_`.
  The counter low bits are 1 for 18,377 prt ids, 2 for 380, 3 for 4, and 4, 5 and 6 for 1 each
  (`counters.swechat.opencode_counter_low12`).
- **Client-side ids that carry time:**
  - Gemini CLI call ids `<tool>_<ms>_<k>`;
  - Codex session ids and Codex subagent thread ids, both UUIDv7: 77/77 and 25/25;
  - `chatcmpl-<ms>` (1 session);
  - `msg_<YYYYMMDDhhmmss>…` behind a proxy (466 ids, 5 sessions).

### A2. The embedded time compared with the event timestamp (P2, `clocks`, `clocks_holdout_A`)

`offset = event ts - embedded time`. A violation is offset < -2 s (< -3 s for second-resolution ids).

| family (corpus / stratum) | n ids (sessions) | min | median [CI] | violations (sessions) | holdout A: n, min, violations |
|---|---|---|---|---|---|
| Anthropic req, swechat CC | 154,765 (1,639) | -4,094 ms | 3,673 [3,558, 3,802] ms¹ | 10 (1) | 11,047, -1,001, 0 |
| Anthropic req, cc_local | 31,085 (186) | -7,749 | p50 4,737 [4,310, 5,415] | 125 (3) | 4,294, -16,359, 26 |
| Anthropic msg UUIDv7, cc_local | 30,680 (185) | -8,043 | 4,446.5 [4,055, 5,009] | 135 (3) | 4,294, -16,707, 28 |
| Anthropic msg UUIDv7, aiv_cu opus | 3,481 (106) | 1,297 | 11,607 [10,754, 12,679] | 0 | 334, 3,224, 0 |
| aiv_cu sonnet / haiku / fable | 2,660 / 1,043 / 1,048 | 1,186 / 1,344 / 3,518 | 8,835 / 8,177 / 12,398 | 0 / 0 / 0 | 136 / 145 / 434 ids, 0 violations |
| OpenAI items, aiv_cu | 14,038 (478) | 450 | 5,739 [5,514, 5,944] | 0 | 840, 477, 0 |
| Gemini responseId, aiv_cu pro / flash | 9,028 (255) / 3,264 (92) | 309 / 1,448 | 7,517 / 8,562 | 0 / 0 | 633 / 528 ids, 0 violations |
| OpenCode prt (client clock) | 8,174 (213) | -14 | 82 [18, 159] | 0 | 4,113, -24, 0 |
| OpenCode ses vs first event | 213 (213) | 2 | 5 [4, 5] | 0 | 25, 2, 0 |
| Gemini CLI call id | 1,677 (20) | 0 | 11 [3, 14] | 0 | 2,313, 0, 0 |
| Codex session UUIDv7 vs first event | 77 (77) | 872 | 4,109 [3,764, 4,546] | 0 | 19, 1,115, 0 |
| `msg_datetime14`, residual after whole hours | 466 (5) | 2,564 | p50 7,766 | 0 | — |

¹ The median CI is computed on a fixed-seed whole-session subsample: 53,890 ids in 635 sessions
(`median_ci_on_session_subsample`). The full-data p50 is 3,778 ms.

- The swechat agreement rate (-2 s ≤ offset ≤ 10 min) is 0.99986 [0.99971, 0.99996], 154,743/154,765 (`agreement_rate`).
  12 offsets exceed 10 min (`far_count`).
- `msg_datetime14`: the whole-hour component is -8 for 466/466 ids (`whole_hour_component_counts`). This is consistent
  with a UTC+8 wall clock in these ids.
- cc_local's negative offsets are concentrated:
  - In the main stream, p1 is -4,851 ms. In the subagent streams, p1 is +1,088 ms (`by_is_subagent`).
  - Per-session floors (`floor.cc_local.anthropic_req`): 3 of 18 sessions with at least 20 ids have a floor below -2 s.
    The minimum floor is -7,749 ms.
  - Drift between the two halves of a session exceeds 2 s in 2 of 18 sessions.
- **swechat floors** (1,231 sessions; `floor.swechat.anthropic_req.claude_code`):
  - floor p50 1,681 ms, p5 845.5 ms;
  - 1 session with a floor below -2 s, and 8 below 0;
  - drift beyond ±2 s in 15/1,231 sessions, and never beyond ±10 s.
- **aiv_cu floors:** no session has a floor below 0, for any family.

### A3. Order and the skew bracket (P2b `order`, P2c `bracket`, `bracket_x_copies`)

- **Order.** I compared consecutive ids within a stream (session × agent). An id inversion means the embedded time goes
  backwards by more than the tolerance.

  | stream | pairs | id inversions | ts inversions |
  |---|---|---|---|
  | swechat request ids | 151,519 | 5 (4 of them also ts inversions) | 4 |
  | cc_local request ids | 30,207 | 3 | 0 |
  | aiv_cu (every family) | all pairs | 0 | 0 |
  | OpenCode prt | 7,961 | 2 | 4 |
  | Gemini CLI | 1,657 | 0 | 0 |

  The first dev run ordered request ids across concurrent subagents instead of within streams, and found thousands of
  inversions in cc_local. That run is not in the final JSON; the rule change is in the changes log.
- **Bracket** (`bracket`). For a server-minted id, the time it carries must fall after the last input event and before
  the first output block, up to one constant client-server skew per stream.

  | corpus | streams with ≥ 2 responses | inconsistent | notes |
  |---|---|---|---|
  | swechat | 3,676 | 10 | session-clustered rate 0.0027 [0.0011, 0.0047] |
  | cc_local | 847 | 1 | despite 125 upper-bound violations caused by skew |
  | aiv_cu Anthropic opus / sonnet / haiku / fable | 105 / 80 / 27 / 32 | 0 | |
  | aiv_cu Gemini pro / flash | 255 / 92 | 0 | |
  | aiv_cu OpenAI | 463 | 3 | |

  - In consistent swechat streams, the interval that pins down the skew (U - L) has p50 2,268.5 ms, p5 1,102.75 and
    p95 3,807.
  - Of the 10 swechat sessions with an inconsistent stream, 2 are among the 3 sessions that hold re-stamped copies (A5).
  - The 10 responses that violate the upper bound all sit in 1 session, which holds no copies (`bracket_x_copies`).
- **Request/message pairing** (`req_msg_pairing`):
  - cc_local: 31,085 requests map 1:1 to message ids. Message time minus request time has min 44 ms, median 194 ms
    [115, 239] and max 7,093 ms, with 0 negative.
  - swechat: 14 of 155,326 requests carry more than 1 message id. No message id carries more than 1 request.

### A4. Counters inside ids (P2g, `counters.aiv_cu`)

- **Kimi-style `tool:N` / `tool_N`:** N equals the call's 1-based ordinal in the session for 1,511/1,511 calls in 42
  sessions. Every one of the 1,469 consecutive steps is +1.
- **`call-<uuid>-N`:** 578/578 calls in 16 sessions, and 562/562 steps of +1.
- **Gemini `call_<digits>`:** not a counter. There are 0 steps of +1 in 2,441 pairs, and the per-session Spearman median
  is 0.039.

### A5. Reuse, collisions and copies (P3, `reuse`, `within_session`, `copies`)

- **Within sessions:**
  - 0 call ids carry more than one call event, in every corpus.
  - Orphan results: swechat CC 4/194,371, rate 2.1e-05 [4.9e-06, 4.3e-05].
  - Calls without a result: swechat CC 285, codex 74, aiv_cc 8, and Cursor 164/164 (the format has no results).
- **Across sessions, swechat CC:** 2,060 entry uuids, 625 toolu ids, 562 msg ids and 561 request ids appear in exactly
  2 sessions. The random-id birthday expectation is effectively 0 (1.5e-24 for request ids,
  `reuse.swechat.request_id`).
- **Copies** (`copies.swechat`). The 2,060 shared uuids fall into 5 session pairs.
  - Content (args and text) is identical in 2,060/2,060 (`text.swechat.copy_consistency_of_cross_session_ids`).
  - Timestamps are equal in only 1,583; 477 differ.
  - 2 pairs carry differing timestamps: 297 of 345 shared uuids, and 180 of 212. They have 298 and 181 distinct
    differences (zero included), so the re-stamp is not a constant shift. Nonzero |diff| has min 139,490 ms, p50
    12,859,554 ms and max 21,350,483 ms.
- **The request-id clock settles which copy holds the original timestamp.**
  - Of 561 shared request ids, all copies agree with the clock in 383. In 178, exactly one copy agrees.
  - In 178/178 of those, the copy that disagrees is the later one.
  - The disagreeing copies are offset by at least 619,473 ms; the agreeing copies by 2,347 to 21,734 ms.
- **aiv_cu:**
  - Synthetic bootstrap turns carry zeroed provider ids: `toolu_000…` in 726 sessions and `call_000…` in 158
    (`reuse.aiv_cu.x_provider_call_id`).
  - Kimi counters repeat across sessions by construction: 185 values appear in more than 1 session, up to 17 sessions.
  - Gemini 8-character ids: 0 cross-session repeats.
  - Gemini `call_<digits>`: 1 repeat against 0.61 expected.
  - gemini-pro calls with no provider id (`turn:` fallback): 7,502 (`census.aiv_cu.call_id.gemini-pro.loader_synthetic`).

### A6. Ids inside text (P4, `text.<corpus>.counts`)

- **T1 spill notices** (swechat, 730). The tool id in the file path:

  | file-path id | count by tool |
  |---|---|
  | equals the result's own call id | Read 145, Grep 54, Bash 3, WebFetch 1 |
  | `REDACTED` by the release | Read 151, Grep 60, WebFetch 3, Bash 2, serena search 1 |
  | a 'b' + 8-character base36 output id, never issued as a background id in the session | Bash 281, Grep 7 |
  | other | Bash 22 |
  | **points to a different tool call** | **0** (no `other_call_in_session` class) |

  The directory uuid equals the session id in 719/730. aiv_cc: 10/10 equal the own call id and the session's uuid part.
- **T2 `agentId:` in Task/Agent results** (swechat, 3,099):

  | outcome | count |
  |---|---|
  | matches the nested agent id | 2,159 |
  | no nested events | 940 |
  | **mismatch** | **0** |

  cc_local: 7/7 match.
- **T3 background task ids** (swechat):
  - 824 issued.
  - References in call args:
    - TaskOutput: 560 issued before, 16 never issued;
    - TaskStop: 25 issued before;
    - BashOutput: 21; KillShell: 4.
  - Notification `<task-id>` (system): 994 issued before, 93 never issued.
  - Notification `<tool-use-id>` against the issuing call: 411 equal, 0 different, 451 redacted.
  - Output-file name against the task id: 664 equal, 0 different.
  - cc_local: 384 equal and 0 different, but 637 notification ids were never issued in the session against 397 issued
    before.
- **T3b todo task ids:** 4,677 references to a task created earlier, 76 to a task never created, and 11 ids re-issued.
- **T4 Codex unified-exec session ids:** 1,615 writes to a live session, 12 after the process exited, and 88 to an id
  never issued. 826 "running" headers repeat the same id (0 differ).
- **T5 commit claims:**
  - swechat: 3,035 claims; no 7-character sha carries 2 subjects. `git log` agrees with the claim's subject in 2,943
    cases after the claim (6 disagree) and 103 before it (4 disagree).
  - aiv_cu: 164 + 102 agree, 0 disagree. aiv_cc: 67 agree, 0 disagree. cc_local: 50 + 1 agree, 6 disagree.
- **T6 request ids printed in API-error JSON** (swechat): of 36 inside assistant text, 27 sit 0-1 s before the event,
  5 at 1-10 s, 3 at 10-60 s and 1 at -2-0 s. Of 9 inside results, 7 sit at 0-1 s. All 13 inside system text sit more
  than 60 s away.
- **T7 UUIDs inside result text:** 564 v7 UUIDs in swechat. 440 are more than 10 min older than the event and 28 are
  more than 60 s newer (`uuid_in_text_time_offsets.v7`). Session ids from other sessions appear in result text 851 times
  (v4) and 128 times (v7).

---------------------------------------------------------------------------------------------------------------------

## Part B. Interpretation (not data)

1. **The logs already contain a third clock that the client does not set.**
   - Anthropic request ids (all corpora), newer Anthropic message ids, OpenAI Responses item ids and Gemini responseIds
     each carry a server timestamp.
   - Against them, client event timestamps:
     - always come later in aiv_cu (min 309 ms, 0 violations in every family);
     - come later in all but 10 of 154,765 swechat request ids;
     - are bracketed by a single per-stream skew in 3,666 of 3,676 swechat streams.
   - The holdout split reproduces every family (0 violations outside cc_local).
   - **Main false-positive source: client clock skew.** cc_local sessions sit as far as -7,749 ms (-16,359 ms in split A)
     behind the server, which breaks a naive "offset ≥ 0" rule in 3 sessions. The bracket test absorbs it: 1/847 streams
     inconsistent. That is why the bracket is the usable form.
   - Server and client clocks differ, so a forger who re-times events must keep every event inside the brackets set by
     ids they cannot re-mint without knowing the layout.
   - **It is not cryptographic.** These ids are unsigned base58/hex strings. Anyone who knows the layout (now including
     this note) can mint consistent ones. The value is that ordinary edits made without that knowledge break it.
2. **The id clock already caught re-written timestamps in honest data.**
   - 2 swechat session pairs share content with re-stamped timestamps (477 entries): probably a resume or fork that wrote
     fresh times.
   - The request-id clock picks the original copy in 178/178 cases, and the re-stamped copy is always the later one.
   - This is the closest thing in the data to a positive control for timestamp tampering. n is small: 5 session pairs,
     2 of them re-stamped, split B only.
3. **Id formats form a dated sequence, so they support anachronism checks.**
   - Anthropic message ids went from random to UUIDv7 between 20:23:44 and 20:37:04 UTC on 2026-07-06 (in this corpus).
   - Tool ids moved to the UUIDv4 shape by 2026-09.
   - OpenAI item ids changed layout in 2025-09.
   - A log dated before a switch that carries post-switch ids, or one that carries old ids well after the switch,
     contradicts itself.
   - False-positive sources:
     - the overlap window (81 old ids after the first new one);
     - proxy and cloud variants (Bedrock `msg_bdrk_`, Vertex `_vrtx_`), whose rollout dates I did not measure.
4. **Counters inside ids work as sequence clocks.** Kimi-style ids equal the call ordinal in 1,511/1,511 calls. Deleting,
   inserting or reordering a tool call in such a log breaks an arithmetic identity. Coverage is narrow: 2 compat-chat
   id styles.
5. **Ids quoted in text are internally consistent wherever both ends are visible.**
   - Measured mismatches are 0 for: spill path to own call (0 pointing elsewhere), agentId to nested agent,
     notification tool-use-id to issuing call, and output file to task id.
   - The disagreements that do occur are references to things this session never issued:
     - Codex 88;
     - TaskOutput 16;
     - notifications 93 in swechat and 637 in cc_local.
   - Those are most likely issuance in a parent or earlier session, or an issuance text I did not pattern-match (cc_local
     is a newer harness version). As alarms they need lineage before use.
6. **Server-side ordering is tight.** In cc_local, message ids are minted 44 ms or more after their request id (never
   before). That is a second internal server identity a fabricated pair would have to satisfy.

### Nulls (as prominent as the hits)

- **These carry no time:** pre-switch Anthropic message ids and all tool-use ids (random or UUIDv4); Claude Code entry
  uuids, aiv_cu row ids and Gemini CLI message ids (all UUIDv4); OpenAI `call_` ids; and Claude Code agent ids.
  - aiv_cc therefore has **no decodable clock at all**: no request ids are stored, and its 12 time-plausible msg ids
    match the 11.93 expected by chance.
  - swechat message ids give nothing; only its request ids do.
- **UUIDs inside tool output are not tied to the event.** 440/564 v7 UUIDs are more than 10 min older than the event.
- **Gemini `call_<digits>` is neither a counter nor time-bearing.** Whatever it encodes, I did not decode it.
- **Who&When has only loader-synthetic ids** and no clock. There is nothing for this lens there.
- **Duplicate call ids within a session:** 0 in every corpus. Weak ids did not collide inside sessions in this data.

## Could not measure

- Whether these vendor id layouts are documented, stable, or the same on other platforms. All of them are inferred from
  the data and are UNVERIFIED. Bedrock/Vertex ids appear only in small numbers.
- The meaning of Gemini responseId bytes 4-16, of the UUIDv7 `rand_a` bias (bit 75 is almost always 0), and of the
  OpenAI per-session 16-hex prefix (perhaps a conversation id).
- Server-side verification: checking an id against the vendor would need API access, which no corpus provides.
- The copy and re-stamp result beyond split B. The full swechat population was not loaded.
- PID consistency (census only: 330 swechat results match the PID pattern), and cc_local per-month format epochs
  (private: aggregates only).
- Why 637 cc_local task notifications reference ids never issued in-session. The issuance text of newer harness versions
  was not inventoried.

## Candidate mechanisms (novelty guesses are UNVERIFIED)

1. **Server-id skew bracket.** Decode server-minted ids (req/msg UUIDv7-in-base58, OpenAI item hex time, Gemini
   responseId LE seconds). Require one constant skew per stream to bracket every response between its last input and
   its first block.
2. **Copy arbitration by id clock.** When the same event appears in two logs, the copy whose timestamp agrees with the
   embedded server time is the original.
3. **Id-format epoch check.** Check the id layout (random, v4 or v7; hex48 or hex50) against the claimed date.
4. **Ordinal counters in tool-call ids.** Check that `tool:N` equals the call ordinal.
5. **Cross-reference closure.** agentId, task ids, tool-use-ids in notifications, spill-path ids, Codex session ids and
   commit sha to subject must resolve to an earlier issuance of the same object.
