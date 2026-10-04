# Prior art: Phase E Track B verdicts

Written 2026-10-04. This file synthesizes the Track B evidence in `analysis/out/phase_e/track_b/`:
B2a_provider_id_facts, B2b_timestamping_lit, B2c_systems, B1a_timing_channels_fraud, B1b_apm_runtime,
B1c_logs_llm_latency, B1d_agent_eval, B3a_tokens_harness_timers, B3b_reaction_concurrency_determinism,
B3c_errors_transfer, plus the prior-art fields of b4, B5a, B5b, B5c and B5d. No new searching was done for this file.

**How to read it**
- **Verdicts.** NOVEL: no opened source does it. PARTIAL: the technique or its ingredients are published, but our
  combination or application was not found. TAKEN: an opened source does it. N/A: a fact, not a novelty claim.
  UNVERIFIED: rests on a source no agent opened, or was not researched at all.
- **NOVEL is always search-bounded.** It means "not found in roughly 300 opened sources", not "proven absent".
- **Citations.** Every citation below was opened by a Track B agent (`opened: true` in the evidence file named in
  brackets). Anything else is marked **UNVERIFIED** where it appears. Quotes are kept short; the full deciding passage
  is in the named JSON. Quotes that came through WebFetch extraction may be paraphrased by the extractor (B1b, B1d and
  B2a flag this). B2a cross-checked every id and number it relied on by decoding.
- **Interpretation.** Blocks headed **[INTERPRETATION]** are this writer's synthesis, not findings.
- **Skeptic pass.** A citation skeptic later re-opened 103 citations, including every deciding citation behind a
  NOVEL or PARTIAL verdict, and searched again for missed B1/B2 prior art. All changes are listed in §5 with their
  evidence, and the evidence file is `analysis/out/phase_e/track_b/B_citation_skeptic.json`. No cited source turned out
  not to exist. One verdict label changed (the B2 conjunction is now marked near-TAKEN), one deciding citation was
  re-labelled as secondhand, and several passages were reworded.

---

## Verdict table

| Item | Verdict | Closest work | Deciding citation (opened) |
|---|---|---|---|
| **B2. Request-id clock bracket.** The time in a provider-minted request id, with one constant skew per stream, must fall between the stream's last input and the response's first output | **PARTIAL.** The method is old. The application is new | Willassen 2008 clock-hypothesis test, whose §2 also summarises Gladyshev & Patel 2005 bracketing by externally timed events and Schatz et al. 2006 server-clock correlation; forensic time anchors (Vanini et al.); Roughtime draft-17 §8.2; Jaeger ClockSkew adjuster; email id-date checks (§1.1) | Willassen 2008 Theorem 2 and §2; arXiv 2412.12814 §4, a one-sentence secondary summary of the time-anchor definition (the Vanini et al. 2024 primary is UNVERIFIED). No source among the 35 B2b opened combines an id-embedded time, a causal bracket and a skew allowance on a recorded log [B2b; skeptic §5] |
| B2, application. LLM-provider request ids as the external clock for agent tool-log stamps, plus the single-response binding test | **NOVEL** | Langfuse ai-gateway and Codex rollout-trace store the provider id beside their own clock and never relate the two; the debug-claude-session skill | 0 of 25 systems use a provider id or provider clock to verify, order or bound anything [B2c]. The skill says: "Correlate by time + model, not request id." [B2b] |
| B2, fact. Is any provider id layout documented or stable? | **N/A. Undocumented for every provider, with no stability promise. This is a MATERIAL LIMITATION** | Anthropic errors doc and SDK; OpenAI API overview; Vertex and Gemini protos | Anthropic `types/message.py`: "The format and length of IDs may change over time." OpenAI lists changing "the length or format of opaque strings" as backwards-compatible [B2a] |
| **B1(a).** A residual of duration against expected workload as a fabrication signal in agent tool logs (N1) | **PARTIAL** | BOINC CreditNew; van der Linden and Sinharay response-time residuals; DeepLog; Kovah 2012 timing attestation; crewAI PR #3388 (agent domain, fixed floor, never merged) | BOINC CreditNew.md: reported elapsed time is checked against the declared FLOP bound, and "falsifying ... elapsed time" is named as the cheat [B1b]. Sinharay 2020 [B1a] |
| **B1(b).** corr(residual, output_size) separates work-bound from generation-bound latency | **PARTIAL** (narrow: neither the statistic nor the application was found) | Early Bird (arXiv 2409.20002) §IV-D and Fig. 11; Time Will Tell (arXiv 2412.15431) | Early Bird §IV-D observes that cache-hit TTFT is flat in request length while a miss grows almost linearly; its document-probing attack separates hit from miss with a 2.0 s threshold at 89% accuracy (Fig. 11) (input side) [B1c; skeptic §5]. No opened source correlates a residual with output size [B1a–B1d] |
| B3.1 Token conservation (context growth vs logged appended content) | PARTIAL | Velasco et al., arXiv 2510.05181; Paritok, arXiv 2609.22114 | 2510.05181 §3.2; 2609.22114 Table 2 [B3a] |
| B3.2 Cache-read chain as a witness that each logged prefix was sent | PARTIAL | KeyPooling, arXiv 2608.17485; CacheTracer, arXiv 2608.20732 | 2608.17485 §II-A; 2608.20732 Assumption 1 [B3a] |
| B3.3 Prompt-cache timing side channel (Gu et al.) | TAKEN as a technique. It does not overlap B3.1 or B3.2 and cannot run on recorded logs | Gu et al., ICML 2025, arXiv 2502.07776 | 2502.07776 §2.1 and §3.1 [B3a] |
| B3.4 N2 accounting identity (inline fabrication is billed as output tokens) | PARTIAL | ReAct reference code; billing audits | ReAct `hotpotqa.ipynb`, stop at `"\nObservation {i}:"` [B3a] |
| B3.5 Harness dual-rendering recount (toolUseResult vs visible text) | PARTIAL | GhostBuster cross-view diff (2005); NTFS $SI vs $FN; Hearsay App. G | MSR-TR-2005-25; Magnet $FN blog; arXiv 2609.32495 App. G [B3a] |
| B3.6 Nested timer chain (tool-printed ≤ harness timer ≤ window ≤ provider interval) | PARTIAL | Jaeger ClockSkew adjuster; Sharma et al., arXiv 2604.21361; Willassen 2008 | jaeger `clockskew.go` child-inside-parent check; 2604.21361 §3, benign skew only [B3a] |
| B3.7 Reaction-time scaling (N3) | PARTIAL | Zhang & Conrad 2014 survey speeding; Google patent US8271865; Palisade LLM Agent Honeypot | Zhang & Conrad p.129, a 300 ms-per-word floor [B3b] |
| B3.8 Concurrency-contention scaling (N4) | PARTIAL | Rubenstein, Kurose & Towsley 2000; RAFT (CCS 2011); Ristenpart et al. 2009 | UMass TR 99-66 abstract; IACR ePrint 2010/214 [B3b] |
| B3.9 Repeat-command determinism (N5) | PARTIAL, the closest of these to TAKEN | AdvancedShelLM, arXiv 2606.27990; shelLM; ToolEmu; StableToolBench; Berenson 1995 and Elle | 2606.27990 §5.3 tester quote; Berenson et al., A2 non-repeatable read [B3b] |
| B3.10 Error-message fidelity, passive and log-only (N5) | PARTIAL. The general technique is TAKEN, and the brief's premise is **FALSE** | Bitter Harvest (WOOT 2018); ToolEmu; CEF/Thanatosis, arXiv 2606.14831 | WOOT 2018 §4.4.2; 2309.15817 Table A.1; 2606.14831 §1 [B3c] |
| B3.11 Cross-harness non-transfer (N6) | PARTIAL as a claim; NOVEL as the measured grid | TraceProbe, arXiv 2607.06184; FreeLog, arXiv 2507.19806 | 2607.06184 §V–VI; 2507.19806 Table 1 [B3c] |
| Not researched: rank 2 image-token ledger; rank 3 git execution window; N5 sort order, truncation boundary, whitespace, output-size distribution and cold start | **UNVERIFIED** | — | Section 3.13 |

---

## 1. B2: Server-minted request ids (highest priority)

**Claim under test** (FINDINGS §4.3 rank 1; PHASE_E_PROMPT B2). Take the timestamp embedded in a provider-minted
request id. With one constant client–server skew per stream, it must sit between the stream's last input event and the
response's first output block. That gives a clock the agent does not control. The same decode supports a
single-response binding test.

### 1.1 Sub-claim verdicts

| Sub-claim | Verdict | Closest work: what it does / does not | Deciding citation (opened) |
|---|---|---|---|
| Reading creation time out of opaque identifiers (UUIDv1/v6/v7, Snowflake, ULID, KSUID, Google `ei`) | TAKEN | Unfurl decodes many id families, including UUIDv7. dfdatetime, Magnet AXIOM, TweetedAt and Metaspike do the same. Unfurl has no parser for LLM-provider ids, would not decode `req_01…` unaided, and is not applied to agent logs | `unfurl/parsers/parse_uuid.py`: `timestamp = int(u.hex[:12], 16)` for v7 (https://raw.githubusercontent.com/obsidianforensics/unfurl/main/unfurl/parsers/parse_uuid.py) [B2a, B2b] |
| An external clock's time inside a local artifact, used to check the local clock or expose tampering (a "time anchor") | TAKEN | Weil 2002 corrects local MAC times from server times in cached HTML, as a range. Schatz et al. 2006 correlate web-cache timestamps with web-server records (via Willassen 2008 §2). Vanini et al. 2024 define a time anchor and treat a mismatch as tampering; that primary is UNVERIFIED and is known only through a one-sentence summary in arXiv 2412.12814. None concerns LLM ids or agent logs | Weil 2002, IJDE 1(2) ("A range of date and times should now be calculated"); Willassen 2008 §2; arXiv 2412.12814 §4, attributing the definition to its ref [19]: an anchor "contains two timestamps – one originating from the internal clock and one from an external source. If these timestamps do not match, this indicates tampering" [B2b; skeptic §5] |
| Bounding an event between causally preceding and following events of known time | TAKEN | Haber & Stornetta 1991 §6.2 is two-sided only when stamping is part of the event. James & Jang 2017 bound an action as (t2 − θ) ≤ τ ≤ t1 with a measured allowance. Haber & Stornetta need hash links made at stamping time | Haber & Stornetta, J. Cryptology 3:99–111, §6.1–6.2 (https://www.gwern.net/doc/bitcoin/1991-haber.pdf); arXiv 1803.08205 §3.1 [B2b] |
| A skew-tolerant cross-clock test: one constant offset must place every remote time inside its local causal bracket, and infeasibility is a tamper flag | PARTIAL | Willassen 2008 Thm 2: under a correct clock hypothesis (a deviation function, of which a constant offset is the simplest case), causally ordered stamps stay monotone; Thm 3 (Test-A) refutes the hypothesis when a causally ordered pair violates this. The paper motivates the test by timestamp manipulation; the antedating application is Willassen's ARES 2008 paper, which was not opened. Roughtime §8.2: chained external times with a radius, where an order violation means "malfeasance". Jaeger ClockSkew: a child span must fit its parent within maxDelta. Cristian/NTP and Moon 1998 bracket a remote reading and estimate offset. No opened work combines all four parts: an unsigned clock embedded in a server id, one existential constant offset per stream, infeasibility as a per-record flag on a recorded log, and no instrumentation | Willassen 2008 Thm 2 (https://dl.ifip.org/db/conf/ifip11-9/df2008/Willassen08.pdf); Roughtime draft-17 §8.2 (https://www.ietf.org/archive/id/draft-ietf-ntp-roughtime-17.html); Jaeger v1.60.0 `model/adjuster/clockskew.go` [B2b] |
| The conjunction: an id-embedded external time bounding a log event between causally ordered local events, with a skew allowance, on a recorded log | PARTIAL, **near-TAKEN as a method** (skeptic) | Each opened source has two of the three ingredients. Vanini anchors and Magnet AXIOM check an id time against the local clock. Jaeger, NTP and Willassen bracket with an allowance. Roughtime chains external times with an allowance, but its times are signed. Metaspike combines IMAP Internal Date with UID order to expose backdating, with no tolerance. **Skeptic additions:** (1) Willassen 2008 §2 already sets Gladyshev & Patel's 2005 bracketing by externally timed events beside Schatz et al.'s 2006 correlation of server-generated timestamps with a local clock hypothesis. Every ingredient except "the external clock sits inside a provider-minted id" therefore co-occurs in one 2008 paper. (2) Email threat hunting already compares an id-embedded date with a recorded log stamp. A 2026 KQL query (Albea) extracts the date inside an InternetMessageId and flags messages whose recorded processing Timestamp falls on a later day. It is passive and runs on recorded logs, but it is one-sided, has day-level tolerance, and trusts the log over the id. (3) Metaspike's Gmail case reads a FILETIME inside a MIME boundary to expose a backdated message | Absence across the 35 sources B2b opened; nearest misses are Roughtime §8.2, Willassen 2008 §2, arXiv 2412.12814 and `clockskew.go`. Willassen §2: "time boundaries can be established when an event that occurred at an unknown or uncertain time is causally preceded and succeeded by events whose times of occurrence are known … [these] must come from external sources". KQL: https://www.kqlsearch.com/query/Detect%20Potential%20Malicious%20Emails%20Based%20On%20Internetmessageid%20Dates&cmoast5p700023nlo25dqehv1 (the author's GitHub repo exists; the file itself was not located). **Risk:** see §1.5 [B2b; skeptic §5] |
| LLM-provider request ids as the anchor for agent tool-log stamps, and the single-response binding test | NOVEL | debug-claude-session correlates Claude Code transcripts with server logs by time window and explicitly does not use request ids. OTel GenAI defines `gen_ai.response.id` only as "The unique identifier for the completion" and has no provider-side timestamp attribute. Skeptic searches for public decoding of Anthropic `req_`/`msg_` or OpenAI `chatcmpl-` ids found none | https://claudskills.com/skills/debug-claude-session/SKILL.md [B2b]; `semantic-conventions-genai` `model/gen-ai/registry.yaml` @e07f4eba [B2c] |
| An existing system decodes a provider id as a clock to bound, order or verify tool-log stamps | NOVEL (systems view) | Langfuse ai-gateway stores `langfuse.gateway.upstream.request.id` next to start_time and first_byte; Codex rollout-trace stores `upstream_request_id` next to wall_time_unix_ms. Claude Code persists `requestId` beside each assistant timestamp. None decodes, compares or orders by it | langfuse `ai-gateway/src/telemetry/mapping.rs` L183-189 @f75c661d (metadata only); codex `codex-rs/rollout-trace/src/reducer/inference.rs` L211-217 @ab452649 (stored only) [B2c]. The skeptic re-opened both files and confirmed the content but not the line numbers. Spot-checks of LangSmith, Vivaria, Inspect, nabaos, AFR, Harbor, ccusage and OTel GenAI also found storage or correlation only |
| An eval harness or observability product checks harness or tool time against any provider-side clock (id time, OpenAI `created`, Google server-timing, HTTP Date, openai-processing-ms) | NOVEL | What exists: latency on each tool's own clock (Helicone, Langfuse, Inspect); ISO-format validation only (Harbor); staleness against the verifier's own clock (NabaOS receipt.rs); anchor time as a presence flag only (AFR) | harbor `src/harbor/models/trajectories/step.py` L93-102 (format check only); `afr/verifier.py` (`if timestamp == 0: missing.append(...)`) [B2c] |
| Using provider ids as dedupe keys, including recognising one response copied into several session transcripts (our resume/fork copies, FINDINGS ids/O7) | TAKEN | ccusage deduplicates Claude Code usage by (message.id, requestId) for exactly this reason. Harbor, Braintrust bt-daemon, OpenHands, Tracekit and the LiteLLM SpendLogs PK group on provider ids. None compares a copy's time with the original's | ccusage `rust/adapters/claude/src/README.md` @8904e880: Claude Code "can copy one response into multiple session transcripts" [B2c] |
| Ordering an agent event log by time-ordered ids (UUIDv7, ULID) | PARTIAL | NovaFabric orders by self-minted ULIDs and disclaims independence from the emitter's clock. AFR mints "UUIDv7-style" ids from its own `time.time()`. Neither uses a third party's id clock | NovaFabric §3.4: ULID order "is a convenience of representation, not independence from that clock" (arXiv 2609.12582) [B2c] |
| The provider as an independent witness the operator does not control | PARTIAL | Hearsay (instrumented second writer, RFC 3161 head) names the provider's request log as "the one witness the operator does not run" but never builds it. Its ledger timestamps are explicitly not bound. **Skeptic additions:** Qin et al. (arXiv 2609.30266) recommend an interception server outside the agent host and call provider compliance APIs independent but limited evidence, yet exclude "provider-side records" from their blue team. Luo et al. (arXiv 2605.02187) propose provider signatures over tool_use fields (sign-c), which needs provider cooperation and instrumentation. They state that "Providers attach no verifiable integrity tags" and that "Post-hoc detection cannot distinguish tampered from vanilla responses". Neither uses a provider id or clock | arXiv 2609.32495 App. I p.48; App. G [B2c]; arXiv 2609.30266 §1–2; arXiv 2605.02187 §3.2–3.3 [skeptic] |
| A provider-held check of a transcript against provider state (adjacent finding) | PARTIAL | Anthropic preserved thinking: a replayed thinking block is valid only while the system prompt, tools and every earlier message, tool_results included, are unchanged. A change gives a 400 error. Server-verifiable only, needs paid calls, covers only the prefix, and cannot catch execution-path fabrication | https://platform.claude.com/docs/en/build-with-claude/preserved-thinking [B2c] |
| A benchmark harness cross-checks its timer against a second clock to reject faked results | TAKEN (narrow; local clocks only). This writer assigned the verdict from B1b's cross-angle pointer; B1b gave none | Futuremark SystemInfo v4.20 added Windows RTC verification so results with inaccurate timing can be rejected. Both clocks are on the benchmarked machine, and there is no provider or server clock | https://community.hwbot.org/topic/83469-futuremark-systeminfo-v420-out: "Added Windows RTC clock verification, results with inaccurate time measurement can now be rejected on 3DMark.com" (a forum post, re-opened and confirmed by the skeptic) [B1b] |
| Secure or forward-secure audit logging as witness-free verification of an uninstrumented log | N/A (contrast class) | Schneier & Kelsey 1999, Ma & Tsudik 2008 and Crosby & Wallach 2009 give integrity, forward security or fork detection from keys or commitments made at write time. All need instrumentation | Schneier & Kelsey, cross-peer step 4 (https://www.schneier.com/wp-content/uploads/2016/02/paper-auditlogs.pdf); Crosby & Wallach §3.2 [B2b] |
| Causal-consistency checking of distributed logs across clocks under skew | TAKEN | Lamport 1978 IR2′; Mattern 1989; Elle 2020; Sharma et al. 2026 negative spans; Jaeger and Zipkin. All assume benign skew and honest records | arXiv 2604.21361 §3: "We do not consider adversarial clock manipulation" [B2b] |

### 1.2 Facts: what providers document about id structure

Sources: B2a (provider docs, SDK source and official examples, all opened; layouts cross-checked by decoding). The
corpus counts are from FINDINGS §4.2.1 and B2a's own scans.

| Provider / id | Layout documented? | Timestamp embedded? | Stable? |
|---|---|---|---|
| **Anthropic `request-id` header (`req_…`)**; also `request_id` in error bodies since 2025-08-19 | **No.** The errors page documents the header and gives two example values, with no format statement (https://platform.claude.com/docs/en/api/errors) | **Yes, inferred from data.** `req_` + `01` + 22 base58 chars is a 128-bit RFC 9562 UUIDv7 (48-bit Unix ms). Counts: swechat 154,815/154,815, cc_local 31,085/31,085, swechat claude_code (B4) 305,727 distinct ids. The doc's real-looking example `req_011CSHoEeqs5C35K2UUqR7Fy` decodes to 2025-08-19T21:43:15.444Z, the date of the release note that added `request_id` to error bodies. The other doc example, `req_018EeWyXxfu5pfWkrYcMdjWG`, is a placeholder and not v7 (version nibble 9) | **No vendor promise.** No change observed from 2025-08-19 to the latest data, which is absence of evidence only. The versioning page preserves only existing input/output parameters |
| Anthropic `msg_` | No. The SDK docstring reads "Unique object identifier. The format and length of IDs may change over time." | Before 2026-07-06 no (random). After, UUIDv7 in base58: cc_local 30,680/30,680, aiv_cu 8,232/8,240 | **Changed** on 2026-07-06 (first v7 at 20:23:44 UTC) with no entry in the 2026-07-01 to 07-15 release notes |
| Anthropic `toolu_` | No. `ToolUseBlock.id: str`, no docstring | No. Random; recently in a UUIDv4 shape | Shape changed (2026-08/09) |
| Anthropic Message body | — | **No server timestamp field** on Message (fields listed from `types/message.py`). The only per-response server clocks are the undocumented id time and the HTTP Date header, if a harness records it | — |
| OpenAI `x-request-id` | Only as "Unique identifier for this API request (used in troubleshooting)" (https://developers.openai.com/api/reference/overview) | **UNKNOWN.** The only official example is `req_123` (SDK READMEs). No corpus of ours stores it: 0 of the first 400,000 aiv_cu lines | — |
| OpenAI `chatcmpl-` | No. "A unique identifier for the chat completion." | **Yes, inferred.** base62(id[9:14]) + 1,576,800,000 = the documented `created` second (epoch 2019-12-20T00:00:00Z). Exact in 12/12 official examples, 2023-11-26 to 2025-03-10. The offset was fit on one, so 11 are out-of-sample. 1 s resolution, and redundant with `created` | Not tested after 2025-03 or on any corpus |
| OpenAI Responses `resp_`, `msg_`, `fc_`, `rs_`, `ws_`, `ctc_` | No. "Unique identifier for this Response." | **Yes, inferred.** Time-first hex: `resp_` hex[0:8] = `created_at` in 2/2 cookbook examples (1740465465; 1746989954). aiv_cu: 0 violations in 14,038 item ids | **No.** 32-hex (2025-02), then 48-hex (2025-05 to 08), then 50-hex with a per-session 16-hex prefix (2025-09 on). OpenAI's overview lists changing "the length or format of opaque strings, like resource identifiers" as backwards-compatible |
| OpenAI `call_` | No | No evidence of time (142.8 bits positional entropy in aiv_cu) | — |
| OpenAI documented server clocks | `created` / `created_at` / `completed_at` (Unix seconds) and the `openai-processing-ms` header. The 1 s resolution of `created` causes real ordering inversions against client stamps (pydantic-ai issue #2071) | — | — |
| **Google Gemini / Vertex `responseId`** | **Partial for Vertex.** The proto says response_id "is the encoding of the event_id" and never specifies event_id (`google/cloud/aiplatform/v1/prediction_service.proto`). The Gemini Developer API proto says nothing about structure (`generativelanguage/v1beta/generative_service.proto`) | **Yes, inferred.** Google's "ei"/EventId layout: uint32 LE Unix seconds + varint microseconds + 2 more varints. 20,000/20,000 aiv_cu ids parse exactly, with 0 trailing bytes. Varint 1 is < 1e6 in all of them and uniform. A pre-stated test against the DB row clock: adding the fraction lowers residual variance by 0.199 s² [0.105, 0.296]; a random fraction raises it by 0.215 [0.122, 0.305]; n = 9,532 pairs. **This corrects Phase C's 1 s resolution** (FINDINGS §4.2.1/§5.7) | No vendor statement |
| Google headers (Gemini Developer API, 5,000 aiv_cu rows) | `server-timing: gfet4t7; dur=N` is undocumented. `date` has 1 s resolution. 12 header keys, with no request-id header and no `x-goog-*` | — | — |
| Google documented server clocks | Vertex `createTime`, "Timestamp when the request is made to the server". The Gemini Developer API has none: absent from the proto, 0/5,000 rows | — | — |
| Meta (api.ai.meta.com) Muse Spark `resp_`, in one OSWorld submission | No Meta documentation found or opened | **Inferred.** The first 8 hex are Unix seconds, within 1 s of the OSWorld `action_timestamp` in 8,228/8,231 steps and never after it [B5c] | Unknown |

**SDKs and proxies.** All official SDKs checked pass ids through as opaque strings and never parse or decode them:
anthropic-sdk-python and -typescript, openai-python and openai-node, google-genai. An example is
`return self.http_response.headers.get("request-id")` in `anthropic/_response.py` [B2a]. So SDK source cannot serve as
layout documentation. Proxies re-mint ids. LiteLLM's `resp_` is base64 of the provider, model and original id
(`litellm/responses/utils.py`), and our corpora contain proxy-minted `chatcmpl-<13-digit ms>` and
`msg_<YYYYMMDDhhmmss>` ids [B2a]. Some corpora carry `req_<hex>` and other non-Anthropic `req_` shapes in Claude
Code-format files from other endpoints [B5d].

**MATERIAL LIMITATION (must appear in DESIGN.md).** Every id clock we use, Anthropic `req_`/`msg_`, OpenAI
`chatcmpl-`/`resp_`/items, Google `responseId` and Meta `resp_`, is reverse-engineered from data and examples. None is
documented. Two vendors explicitly reserve the right to change id format or length without a version bump, and at least
three undocumented format changes have been observed: Anthropic `msg_` on 2026-07-06, Anthropic `toolu_`, and OpenAI
items in 2025-02, 2025-05 and 2025-09. In addition, RFC 9562 §6.1 says implementations "MAY alter the actual timestamp"
and gives no guarantee of accuracy, so even a conforming v7 clock is only empirically accurate [B2b]. The ids are
unsigned, and RFC 9562 §8 says UUIDs must not be used as security capabilities, so a forger who learns the layout can
re-mint consistent ids [B2b].

**Corroborating observations from corpus work (data, not documentation).**
- **TB2 WozCode submission** (Claude Code 2.1.86, Mar 2026): 12,327/12,327 Anthropic ids decode as v7, and 12,279/12,327
  fall within [−2 s, +600 s] of their carrying entry [B5b].
- **TB2 hookele** (`gpt5.1-codex-mini`): 12,804/12,804 OpenAI `resp_` ids (hex50 layout) decode inside
  [llm_call − 1 s, stream_summary + 1 s] [B5b].
- **HF Hub:** 2,098 Anthropic-shaped distinct ids across 106 datasets, all with v7 version and variant bits, of which
  2,014 agree [B5d].
  - Every disagreement is in an unlicensed dataset, and offsets are negative: events are stamped up to 42 s before the
    id. Client clock skew is the simplest explanation, and it is not investigated. Budget for it as a false-positive
    source.
- **Coverage stays narrow:** Claude Code to Anthropic first-party, plus one OpenAI and one Meta submission at 1 s. See
  `analysis/CORPUS_INVENTORY.md` (B4) for the coverage column.

### 1.3 Systems: does anything already do it internally? (B2c)

- **Scope.** B2c examined 25 systems in 23 table rows, reading pinned source where it exists:
  - observability: Langfuse, LangSmith, Helicone, Braintrust, W&B Weave, Phoenix/OpenInference, OTel GenAI, OpenLLMetry;
  - eval harnesses: Inspect, Vivaria, SWE-bench/SWE-agent/mini-swe-agent, OpenHands, Harbor/Terminal-Bench;
  - harness logging: Codex, Claude Code;
  - log consumers and gateways: ccusage, LiteLLM;
  - capture-side papers: Tool Receipts/NabaOS, Hearsay, ACE, Tracekit, AFR, NovaFabric.
- **Recording is common; using the id for time is absent.**
  - **Claude Code records the provider request id by default:** `requestId` on transcript assistant entries, and
    `request_id` on OTel events, documented as "Server-assigned ID … read from the `request-id` response header".
  - **Others record it only when a specific component is in the path:** the Langfuse gateway, Weave (OpenAI SDK),
    LiteLLM headers (persistence not verified), Codex opt-in rollout-trace, and Vivaria (semantics undocumented).
  - **Inspect mints its own id instead** (`REQUEST_ID_HEADER = "x-irid"`, `inspect_ai/model/_providers/util/hooks.py` L70).
  - **Uses found:** correlation, support lookup, dedupe and grouping. Zero systems use the id for verification, ordering
    or bounding.
- **Closed back ends cannot be inspected.** This covers the LangSmith, Braintrust and Helicone servers, Claude Code core,
  and METR Middleman, so the systems verdict is bounded by them.
- **Similar checks elsewhere in Track B, none of them a provider-id clock:**
  - **B5c:** OSWorld, BrowserGym/AgentLab, WebArena, AgentBench and browser-use record step times and never read them
    back. AgentLab's ReproducibilityAgent replays against a live environment (a witness, not a log check).
  - **B5b:** no TB, Harbor, Aider or METR artifact parses provider ids.

### 1.4 [INTERPRETATION] What to claim for B2

- **Do not claim the method.** It is a time-anchor / clock-hypothesis consistency test (Vanini et al.; Willassen 2008)
  combined with event-time bounding (Haber & Stornetta 1991; Gladyshev & Patel 2005, the latter **UNVERIFIED**, known only
  through Willassen 2008). Cite Roughtime as the closest structural analogue, and Jaeger's ClockSkew adjuster as an
  observability tool that already runs the bracket check internally under a benign-skew assumption. Also cite
  Willassen 2008 §2, which already places external-time bracketing beside server-clock correlation. Email
  threat hunting already compares id-embedded dates with recorded log stamps (§1.1, conjunction row) [skeptic].
- **What is new is narrow.**
  - LLM-provider request ids, already present in uninstrumented agent records, used as the external anchor for tool-log
    stamps.
  - The single-response binding test.
  - The measured honest inconsistency rate on public corpora (FINDINGS §4.2.1: 10/3,674 swechat CC streams at 2 s
    tolerance).
- **Suggested replacement for FINDINGS §4.3 rank 1** "Novelty guess: UNVERIFIED": "A time-anchor / clock-hypothesis
  consistency test (Vanini et al. 2024; Willassen 2008; event-time bounding per Haber & Stornetta 1991), new only in its
  application to provider request ids in agent tool logs and in its measured honest rate."
- **Related work must cite four things:**
  - **ccusage**, for copy dedupe by (message.id, requestId). Our delta is only the time comparison.
  - **NovaFabric's disclaimer**, which frames exactly what a provider-minted id adds over a self-minted one.
  - **Hearsay**, which named the provider as the next witness and did not build it.
  - **Debug-claude-session**, as evidence that agent tooling correlates by time, not by id.
- **Design consequences** (from B2a, B2b and B2c):
  1. **Gate every decode** on a per-family format check: v7 version and variant bits for Anthropic, the exact 4-byte +
     3-varint parse for Gemini, hex length and position for OpenAI items. Return `unconstrained`, not `contradicted`,
     when the check fails.
  2. **Treat a format change** as lost coverage, not as a detection.
  3. **Prefer documented server clocks where they exist:** OpenAI `created`/`created_at`, Vertex `createTime`, the HTTP
     Date header, and `openai-processing-ms`. Anthropic has none in the body.
  4. **State the threat-model boundary.** The ids are unsigned and re-mintable. The bracket catches retiming and
     misbinding by an editor who does not re-mint ids, never a forger who has inferred the layout. Every standard
     trusted-time mechanism signs its time: RFC 3161, Roughtime, DKIM `t=`. It also cannot see field-level rewriting
     on the response path. A relay that rewrites tool_use fields and re-polishes the text with the same model
     (Luo et al., arXiv 2605.02187) leaves the provider id, and therefore the bracket, intact [skeptic].
  5. **Pre-register the tolerance.** RFC 3161 carries an explicit accuracy field and request ids carry none, so the 2 s
     tolerance is a measured design parameter and must be pre-registered.
  6. **The bracket is one-sided.** Per Haber & Stornetta §6.2, a stamp bounds an event in both directions only if
     stamping is part of the event. The request id stamps response generation, not tool execution. This is our
     late-stamping blind spot.
  7. **Gemini can be tightened.** Gemini's id clock is plausibly microsecond resolution, so the Gemini bracket could be
     narrowed from 1 s.

### 1.5 UNVERIFIED and not opened (B2)

- **Vanini, Hargreaves, van Beek & Breitinger 2024, "Was the clock correct?"** (FSI:DI 49:301759). Only the abstract was
  read, via OpenAlex; ScienceDirect returned 403, Augsburg refused the connection and DFRWS returned 403. **This is the
  main risk to the B2 PARTIAL verdict.** If its Google-search example bounds the server-minted `ei` time against causally
  ordered browser events with a tolerance, the conjunction is TAKEN for forensics. It needs library access. The skeptic
  also failed to open it: DFRWS returned 403, the alphaXiv title lookup resolved to arXiv 2412.12814, and no open copy
  turned up in search. arXiv 2412.12814 (a different paper by Vanini, Hargreaves and Breitinger) only summarises the
  time-anchor definition in one sentence.
- **Haber & Stornetta 1991.** The gwern copy is an image scan with no extractable text. The skeptic could not re-verify
  the §6.1–6.2 two-sided-bound reading; it rests on B2b.
- **Gladyshev & Patel 2005, IJDE 4(2).** Primary not opened (UCD repository HTTP 405, TLS mismatch). Its content is
  confirmed only through Willassen 2008 §2, which was opened. Not to be confused with Gladyshev & Patel 2004 (FSM event
  reconstruction), which CLAUDE_context §5 already lists.
- **Not opened at all:**
  - **Cristian 1989.** The primary failed TLS; only summaries were opened.
  - **Schatz, Mohay & Clark 2006, and Buchholz & Tjaden 2007.** DFRWS returned 403.
  - **Dreier et al. 2024.** Abstract only.
  - **Willassen's ARES 2008 paper and PhD thesis.**
  - **Bellare & Yee 1997.**
- **404s, not cited:**
  - `cheeky4n6monkey/4n6-scripts/google-ei-time.py`.
  - `ryoppippi/ccusage/src/data-loader.ts`. ccusage was opened at its current repo, ccusage/ccusage@8904e880.
  - Zipkin `CorrectForClockSkew.java` at master. zipkin-lens `clock-skew.js` was opened instead.
- **Closed systems and other gaps:**
  - The closed back ends listed in §1.3.
  - The Hearsay code URL was not located, and ACE code is unreleased.
  - **Tool Receipts.** CLAUDE_context §5 says it has "no public code", but nabaos/nabaos has a matching `receipt.rs`.
    Authorship is unconfirmed [B2c]. The skeptic re-opened `receipt.rs`. Its field list matches the paper's §3.2
    receipt, and it checks staleness against the verifier's own clock. The paper cites "Tharakan 2025,
    arXiv:2503.11221", but that id resolves to an unrelated image-quality paper (A-FINE). Do not cite Tharakan through
    Tool Receipts.

---

## 2. B1: Conditional duration model (N1)

### 2.1 Sub-claim (a): a residual of duration against expected workload as a fabrication signal in agent logs. **PARTIAL**

| Angle (evidence) | Angle verdict | Closest work: what it does / does not | Deciding citation (opened) |
|---|---|---|---|
| Timing side channels, tamper detection, fraud (B1a) | PARTIAL | **Psychometrics.** Sinharay 2020 (item preknowledge) contrasts an examinee's speed on compromised vs other items, on van der Linden's lognormal model (log T = item time intensity − person speed); it ships in CRAN `aberrance`. **Timing attestation.** Kovah 2012 sets control limits at mean ± 3 SD from about 200 repeats of an identical workload per host (the skeptic confirmed this in the IEEE S&P 2012 copy, because the MITRE URL now returns 403). **Cloud CPU.** Zheng et al. 2013 flag actual time above theoretical time plus a margin. Also time-deterministic replay (OSDI 2014) and healthcare "impossible day" audits. **None is about agent tool calls.** The attestation schemes choose the workload themselves, which N1 cannot | Sinharay 2020 (https://pmc.ncbi.nlm.nih.gov/articles/PMC7433384); Kovah 2012 (https://www.mitre.org/sites/default/files/pdf/11_4921.pdf) |
| APM, performance regression, runtime prediction (B1b) | PARTIAL | **BOINC CreditNew** (deployed) replaces a claim when the reported elapsed time × peak FLOPS exceeds the job's declared `fpops_bound`, and names falsified elapsed time as the cheat. **Sekar & Maniatis** (CCSW 2011) propose checking predicted consumption against provider reports (proposal only). **Kelly 2005** and TraceAnomaly 2020 are residual-vs-workload anomaly detectors over a trusted log. **MLPerf TEST04** fails a run that is significantly faster than the standard run (caching, not computing). **None is about agent logs.** BOINC is a one-sided static bound on the time field itself | https://raw.githubusercontent.com/wiki/BOINC/boinc/CreditNew.md; https://users.ece.cmu.edu/~vsekar/assets/pdf/2011CCSW-AA.pdf; https://github.com/mlcommons/inference/blob/master/compliance/TEST04/README.md |
| Log anomaly detection, LLM latency, MGT detection (B1c) | PARTIAL | **DeepLog** keeps per-log-key elapsed time and flags it by MSE against a fitted Gaussian. **Fu et al. 2009** fit per-transition, per-machine Gaussians. **van der Linden & Guo 2008** flag aberrant response times. **CacheWise and Continuum** already model expected agent tool-call duration from command, arguments and history, but only for KV-cache scheduling. **None** conditions on claimed work, flags too-fast calls, or considers fabricated records | DeepLog §3.2/§5.2 (https://users.cs.utah.edu/~lifeifei/papers/deeplog.pdf); arXiv 2606.16824 §5.2; arXiv 2511.02230 §4.2 |
| Agent evaluation and benchmark-cheating detection (B1d) | NOVEL (this angle) | **crewAI PR #3388** (closed, never merged) labels any wrapped tool execution under 10 ms `LIKELY_FAKE`. It is a live, instrumented fixed floor, with no workload model, no residual and no baseline. **METR 2025** triaged anomalously high-scoring RE-Bench runs and used an LLM monitor on HCAST. The page describes score triage, not any timing check on solutions or tool calls (skeptic correction). Inspect, SWE-agent, Vivaria, Harbor, Docent and OpenHands record per-call time and use it only for budgets, timeouts and display | crewAI `src/crewai/utilities/tool_execution_verifier.py` @7be92705 L164-166 (https://github.com/crewAIInc/crewAI/pull/3388); https://metr.org/blog/2025-06-05-recent-reward-hacking/ |
| Incidental (B5d) | NOVEL vs this work | **Dubey 2026** (arXiv 2608.02464, ESN+CUSUM agent monitor) uses log latency as a raw, unconditioned feature, then excludes wall-clock features from the shipped configuration as machine-specific | arXiv 2608.02464 §11(6) |

**Combined verdict: PARTIAL.** Treating a duration that the declared workload cannot explain as a falsified record is
deployed (BOINC CreditNew) and standard in test security (van der Linden; Sinharay). Residual-vs-workload anomaly
detection is standard in APM and log analysis. Agent tool-duration models already exist (CacheWise, Continuum). The
closest agent-domain fabrication rule is crewAI's unmerged fixed 10 ms floor. **Not found anywhere:** a passive,
two-sided, workload-conditioned residual on recorded agent tool calls with a within-session same-command baseline,
where the threat is fabricated result content.

**Design pattern: a baseline from within-unit repeats. TAKEN** (B1a, B1b, B1c).
- Kovah 2012: "each host must be baselined independently". The sentence concerns TPM tick counts, and the paper
  contrasts it with software timing attestation, where a shared baseline was tested (skeptic note).
- Sinharay's within-examinee contrast.
- Tsafrir, Etsion & Feitelson 2007 (PARTIAL): the mean of the same user's last two jobs beats mining history. Used for
  scheduling, not verification (https://www.cs.huji.ac.il/~feit/papers/Pred07TPDS.pdf).

**Context that supports the existing latency-floor test. TAKEN** (B1a). LLM honeypots fabricate shell and HTTP output
and treat raw latency as a giveaway: the SoK (arXiv 2510.25939) Table 1, Honeyval (arXiv 2605.29963) §5.2 and
ShellGames (arXiv 2606.17986). None conditions on workload, all judge live from the attacker's side, and Honeyval
reports "no clear correlation" between latency and detection rate.

### 2.2 Sub-claim (b): corr(residual, output_size) separates work-bound from generation-bound latency. **PARTIAL (narrow)**

| Angle (evidence) | Angle verdict | Closest work: what it does / does not | Deciding citation (opened) |
|---|---|---|---|
| B1a | NOVEL (angle-bounded) | Time Will Tell measures Pearson(generation time, output tokens) ≥ 0.987 for local models and 0.370 for GPT-4o over the API, and uses it to leak output length. Keystroke work (inverse roles) uses inter-key timing, and Roh et al. drop characters-per-minute as forgeable | arXiv 2412.15431 Table 3 |
| B1b | NOVEL (angle-bounded) | claude-code #67847, an anecdote: fabricating turns ran 3.9k–5.5k output tokens over 60–90 s, inline with no tool_use, and with no correlation test. MLPerf TEST09 bounds mean output length against truncation, not per call | https://github.com/anthropics/claude-code/issues/67847 |
| B1c | **PARTIAL** | Early Bird §IV-D: on commodity APIs, cache-hit TTFT "remains consistent, regardless of the request length", while a miss "increases almost linearly". A separate document-probing attack separates hit from miss with a 2.0 s threshold at 89% accuracy (Fig. 11). That is the "flat means retrieved, scaling means computed" logic, on the input side. Keystroke provenance tests production time against text produced | arXiv 2409.20002 §IV-D and Fig. 11 (skeptic: the two passages are in different parts of the paper) |
| B1d | NOVEL (angle-bounded) | crewAI PR #3388 stores `execution_time` and `output_size` side by side and its decision rule never reads `output_size`. Tool Receipts stores `duration_ms` next to `result_count`, and duration is not even covered by the HMAC | crewAI `tool_execution_verifier.py` L151-187; arXiv 2603.10060 §3.2 |

**Combined verdict: PARTIAL.** The three NOVEL verdicts were each explicitly conditional on the other angles finding
nothing. B1c found the inference pattern published: Early Bird separates two producing processes by whether latency
scales with length. Its physical premise is textbook: DistServe gives latency = TTFT + TPOT × n (arXiv 2401.09670), and
Time Will Tell measures it.

What no opened source does:
- correlate a workload-conditioned residual with output size;
- use output-size scaling to decide whether a recorded tool result was executed or generated.

Novelty is therefore limited to the statistic and the agent tool-log application.

### 2.3 Other B1 facts the design needs

- **Log anomaly detection mostly ignores duration.**
  - 5 of 62 surveyed deep log-AD approaches use event interval time (Landauer et al., arXiv 2207.03820 Table II).
  - Of the systems named in the brief, only DeepLog models time.
  - The deep-loglizer reference harness keeps only EventTemplate, so its DeepLog drops the time model.
  - The LogAnomaly, LogBERT, LogRobust and PLELog primaries were not opened. Their classification rests on Landauer
    and the deep-loglizer code [B1c].
- **Harnesses record per-call time but never test whether it is plausible** [B1d, B5a, B5b, B5c]:
  - Inspect: `ToolEvent.working_time`.
  - SWE-agent: `execution_time`.
  - mini-swe-agent: `extra.timestamp`.
  - OpenHands: event timestamps.
  - Harbor Terminus-2: `api_request_times_msec`.
  - AgentLab: `StepTimestamps`.
- **Benchmark-cheating detectors do not use timing.** The ones examined use LLM judges, pre-scans, honeypots, taint and
  lifecycle models, or re-execution. Examples: Scale AI (arXiv 2609.34262), CheatBench (arXiv 2609.36308), BenchShield
  (arXiv 2609.11028) and Kirgis et al. (arXiv 2605.08545). ACE names "timing monitors" as the missing sensor (arXiv
  2609.28915 App. B) [B1d].
- **The motivating incident could not have been checked.**
  - The OpenAI/Hugging Face transcripts had no per-action timestamps.
  - The agents used timing themselves to confirm their spoof ("the command returned immediately").
  - METR/Redwood detected the spoofing by output mismatch.
  - Source: https://metr.org/blog/2026-08-26-openai-hugging-face-incident-investigation/ [B1d].
- **The threat is real, and its detection is unaddressed.** Qin et al. show that tool-call spoofing through
  `BASH_ENV` leaves transcripts intact across harnesses, and leave detection out of scope (arXiv 2609.30266 fn. 4) [B1d].

### 2.4 [INTERPRETATION] Framing and limits for N1

- **Framing.** Present N1(a) as a transfer of timing attestation, response-time residuals (van der Linden; Sinharay)
  and BOINC-style workload checks to agent tool logs. Pre-empt the reviewer's line "this is van der Linden's residual
  for tool calls", the same way CLAUDE_context §8 pre-empts the Elle objection. Do not claim "first to use timing to
  flag fabricated tool results": crewAI PR #3388 exists.
- **Two-sided test.** Log-AD and BOINC flag only "too slow" and MLPerf only "too fast", but a fabricated result can be
  either.
- **Separate threat classes for (a) and (b)** [B1d].
  - Execution-layer spoofs run at program speed. They can trip (a) only when the claimed work should have taken longer.
  - They cannot trip (b).
- **Material limits:**
  - **Padding defeats it.** A timing-aware forger who pads to the expected duration passes both (a) and (b). Zheng et
    al. name this attack and need a time-lock puzzle to beat it. Condrey (arXiv 2601.17280) evades keystroke timing
    detectors in ≥ 99.8% of cases, and Jones & Bergen (arXiv 2405.08007) pad AI replies by about 0.3 s per character.
    N1 catches only non-adaptive fabrication.
  - **Raw duration fails.** Leiner 2019 and Xu & Malkin (arXiv 2607.00403) show unconditioned completion time does not
    detect faking. Report raw duration next to the residual. Nuance from the skeptic's re-read: Leiner finds completion
    time is the *most* reliable indicator of careless responding, and fails only on "intended faking".
  - **(b)'s null is not zero.**
    - Honest I/O latency also scales with bytes (LogGP's G term, UCSB TR 1995-09). Compare the fitted slope in s/KB
      with a generation-rate prior, not just the sign of the correlation.
    - In our own data, cc_local W has ρ = +0.164 [0.076, 0.292] (FINDINGS §3.1).
    - Hosted generators dilute (b): Pearson is 0.370 for GPT-4o over the API.
  - **Durations do not transfer across environments.** Recorded vs idle-replay SWE-bench commands show Kendall
    τ = −0.04, and the median replay runs at 0.12× (Ask the Tool, arXiv 2609.18849). This supports the within-session
    baseline.
  - **Byte-identical repeats leave corr undefined.** That bounds (b)'s coverage below the repeat rate.
  - **A duration is only as trustworthy as its clock.** Vivaria's `calledAt` is minted inside the agent's own
    container [B1d].

### 2.5 UNVERIFIED and not opened (B1)

- **Not opened (403/404):** Pioneer 2005; Franklin et al. VMM fuzzy benchmarking; the MDPI honeypot latency benchmark;
  the FCSM slides.
- **Read through a secondary source only:**
  - The Westwood PNAS primary (403), via 404 Media.
  - The TDR (OSDI 2014) PDF, through its patent.
- **Not opened (other):**
  - Cherkasova et al. DSN 2008, known only via Gow 2013.
  - The BOINC ValidationSimple runtime-outlier section (404 / empty).
  - The OTel GenAI `execute_tool` span spec (truncated).
- **Primaries known only through a survey or citing paper** [B1c]:
  - LogAnomaly, LogBERT, LogRobust, PLELog, SwissLog, ATT-GRU and LogNL.
  - InferCept.
  - Kundu 2024 and Crossley 2024.
- **Abstract only:** van der Linden & Guo 2008.
- **Not opened** [B1d]:
  - ImpossibleBench (opened later by B3c).
  - Hack-Verifiable Terminal Bench, Terminal Wrench, EvilGenie and BAITBENCH.
  - The METR/Redwood timestamp-reconstruction appendix.
- **Not opened in Dubey 2026:** its adversarial-evasion artifacts [B5d].

---

## 3. B3: Everything else

### 3.1 Token conservation (FINDINGS §4.3 rank 5, TC1/TC2). **PARTIAL** [B3a C1]

- **Closest work:**
  - **Velasco, Tsirtsis & Gomez-Rodriguez, "Auditing Pay-Per-Token in LLMs"** (arXiv 2510.05181). §3.2 computes the
    reported output length minus a Monte Carlo recount of the visible string, in a martingale test.
  - **Paritok** (arXiv 2609.22114). Table 2 shows that, turn by turn, the compressed and uncompressed Claude Code arms
    differ by exactly the compressed file slice (about 1.5–2K tokens), used for cost attribution only. The skeptic
    narrowed this wording: it is a between-arm accounting identity, not a within-session check that the input delta
    equals the appended content.
  - **Hoque et al., "Token Inflation"** (arXiv 2605.30040).
- **What they do not do.**
  - All billing audits trust the content and audit the provider. We do the reverse: audit the log content against the
    provider's counter.
  - None uses input-side context growth as a content-integrity check, and none runs on recorded agent transcripts.
  - Velasco needs next-token probabilities.
  - None reports a tamper curve. Ours (FINDINGS TC2): about 8,913 inserted chars for power 0.5 in swechat CC, and power
    0.003 for deleting a result under 1,000 chars.

### 3.2 Cache-read chain, cache_read(k+1) = cache_read(k) + cache_creation(k). **PARTIAL** [B3a C2]

- **Closest work:**
  - **KeyPooling** (arXiv 2608.17485 §II-A) uses the documented cached-input count as an oracle that a prefix was
    already sent. It notes that a positive "separates a genuine deployment from a fabrication".
  - **CacheTracer** (arXiv 2608.20732) states "Cache Telemetry integrity" as Assumption 1 and measures it: 3 false hits
    in 5,059 cold-prompt observations.
  - **CacheProbe** (arXiv 2605.30613).
  - **The Anthropic prompt-caching docs** define total input = cache_read + cache_creation + input and exact-prefix
    matching (https://platform.claude.com/docs/en/build-with-claude/prompt-caching).
- **What they do not do.**
  - All are live active probes within the cache lifetime. None reads recorded usage after the fact or chains the counter
    across one session's turns.
  - Reporting granularity varies by route, so the chain must be calibrated per provider and relay. KeyPooling: "so
    resolution belongs to the route". The skeptic found this with Table II (§VI-B) in the arXiv HTML; the "Table XI"
    cited earlier was not located.
- **[INTERPRETATION]** The witness is content-blind. It constrains which turns exist and their order, not what a tool
  result said. Honest breaks occur at compaction, on image pairs and at gaps of 300 s or more (FINDINGS §4.2.3,
  aiv_cc).

### 3.3 Prompt-cache timing side channel (Gu et al. 2025). **TAKEN as a technique; does not overlap 3.1/3.2** [B3a C3]

- **What Gu, Li, Kuditipudi, Liang & Hashimoto do** (ICML 2025, arXiv 2502.07776). A live TTFT audit with a two-sample
  KS test detects caching in 8 of 17 providers and global sharing in 7.
- **What it does not do.**
  - It does not read usage fields. DeepSeek's cache-hit count was used only to confirm hits.
  - It does not read recorded logs, and it needs the cache entry alive plus paid probes ($1.69–8.44 per test).
  - Our corpora carry no TTFT, and Anthropic's default cache lifetime is 5 minutes, so it cannot run retrospectively.
- **Suggested edit:** in FINDINGS §4.3 rank 5, replace "Gu et al. 2025; relevance UNVERIFIED" with "related work on
  live cache auditing; does not overlap the recorded-counter mechanism". The repo
  `chenchenygu/auditing-prompt-caching` was not opened.

### 3.4 N2 accounting identity: inline fabrication is billed as output tokens. **PARTIAL** [B3a C4]

- **Closest work.** The ReAct reference implementation calls the model with `stop=[f"\nObservation {i}:"]`, so the model
  cannot write its own observation; the harness inserts the real one
  (https://raw.githubusercontent.com/ysymyth/ReAct/master/hotpotqa.ipynb). Billing audits (2510.05181) verify output
  counts.
- **What it does not do.** ReAct prevents rather than detects, and its logs carry no token counts. No source uses the
  output-vs-input identity after the fact to separate fabrication classes.
- **Skeptic additions (internal embodiment).**
  - **crewAI PR #4077** (closed unmerged, 2026-04-28) is the follow-up to #3388. It rejects at parse time any LLM output
    that contains both an Action and a Final Answer: "Check for fabrication: LLM cannot include both Action and Final
    Answer". This is a harness rule against the inline-fabrication class N2 targets. It is live and preventive, uses
    no token counts and audits no logs (https://github.com/crewAIInc/crewAI/pull/4077).
  - **Luo et al.** (arXiv 2605.02187 §8) name "per-turn token accounting" as a complementary signal for relay
    tampering, because same-model re-polishing roughly doubles token use on tampered turns. It is a suggestion only.
  - Verdict unchanged: PARTIAL.
- **[INTERPRETATION]**
  - In structured tool-calling logs the role label already exposes inline fabrication.
  - The identity adds information only when an editor moves model text into a tool_result after the fact, and then it
    reduces to 3.1 with 3.1's power limits.
  - Execution-layer compromise returns as input tokens and is invisible to it.
  - CoIn, PALACE and Velasco et al. 2505.21627 were **not opened** (secondhand only).

### 3.5 Harness dual-rendering recount (toolUseResult counters vs visible tool_result text; FINDINGS §4.3 rank 4). **PARTIAL** [B3a C5]

- **Closest work:**
  - **Strider GhostBuster** cross-view diff (MSR-TR-2005-25,
    https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/tr-2005-25.pdf).
  - **NTFS $STANDARD_INFORMATION vs $FILE_NAME** timestomp detection. $FN is written only by the kernel (Magnet
    Forensics blog).
  - **Vanini et al.** (arXiv 2412.12814) weigh a redundant copy by its tamper resistance.
  - **Hearsay** (arXiv 2609.32495 App. G) saw native second copies in agent records (mini-SWE-agent
    `extra.raw_output`; SWE-agent trajectory vs history). It treated them only as a confound: "Twelve of the 14 misses
    on witnessed content" sit on such records. It never flags copy A ≠ copy B.
- **What they do not do.** No opened source compares two renderings that one agent harness writes inside its own
  record.
- **[INTERPRETATION]** By the forensic criterion this copy is weak. One process writes both renderings into the same
  JSONL line with the same permissions, unlike $FN, which a more privileged writer holds. Claim the measured agreement
  rate and the tamper response, never a new technique.
- **Residual risk, not opened:**
  - Codex rollout-trace keeps model-visible and runtime payloads apart: "runtime payloads are evidence, not proof that
    the model saw the same bytes" [B2c]. Whether its reducer compares them was not checked. The skeptic located the
    quote in `codex-rs/rollout-trace/README.md` under "Reducer Invariants", not in `inference.rs`. The README lists
    only structural invariants: seq order, and payload files existing before events refer to them. It lists no
    cross-copy comparison.
  - Inspect `ToolEvent.result` vs `ChatMessageTool`, OpenHands observation vs extras, Langfuse/LangSmith/Phoenix span
    nesting, and the ccusage recount were not opened [B3a].
- **Claude Code's OTel export** carries `tool_result_size_bytes` and `duration_ms` per `tool_use_id`. Where telemetry was
  enabled (off by default), this would be a cross-writer second copy. Public corpora will not carry it
  (https://code.claude.com/docs/en/monitoring-usage) [B3a].

### 3.6 Nested timer chain. **PARTIAL** [B3a C6]

The chain is: tool-printed duration ≤ harness timer ≤ call-to-result window ≤ provider-id interval.

- **Closest work:**
  - **Jaeger's ClockSkew adjuster** checks whether a child span "already fits within the parent span". If not, it
    shifts the child and warns past maxDelta (v1.57.0 `model/adjuster/clockskew.go`).
  - **Sharma et al.** (arXiv 2604.21361) count negative spans as a causality-health alarm.
  - **Willassen 2008** gives the forensic logic.
- **What they do not do.** All assume benign skew. Sharma states "We do not consider adversarial clock manipulation",
  and Jaeger repairs violations rather than flagging them. No source chains a tool's self-reported duration through
  harness timers to a provider clock as a fabrication check.
- **[INTERPRETATION]**
  - The harness-internal legs are near-tautological, because one process writes the timer and the stamps (FINDINGS
    §4.2.2: 0/112,677 bash_progress violations).
  - The only cross-writer legs are the outer provider bracket (B2) and the inner tool-printed duration, which the
    fabricator also writes.
  - The check is one-sided: it catches only output that over-claims elapsed time. It adds little beyond B2.

### 3.7 Reaction-time scaling, corr(next_call_gap, result_bytes) (N3). **PARTIAL** [B3b item 4]

- **Closest work:**
  - **Zhang & Conrad 2014** flag survey speeding below 300 ms per word × question length
    (https://ojs.ub.uni-konstanz.de/srm/article/view/5453/5344).
  - **Google patent US8271865** uses reading speed against document length to detect automated surfing.
  - **The Palisade LLM Agent Honeypot** (arXiv 2410.13919) labels responders under ~1.7 s as LLM agents, without
    conditioning on size.
- **What they do not do.** None asks whether the reader authored the content, and none computes the correlation on agent
  logs. TraceLab (arXiv 2606.30560) computes N3's inputs for serving characterisation only.
- **[INTERPRETATION] Expect a null.**
  - For an LLM, "reading" is prefill of the appended tokens (Early Bird; TraceLab). A fabricated result that returns
    through the harness as a tool_result is prefilled exactly like a real one.
  - Under Claude's output-resend accounting, even model-authored text is re-prefilled.
  - The gap before the next tool_use is dominated by argument streaming (FINDINGS §4.2.6: median 174.7 arg chars/s,
    ρ 0.809), which must be partialled out.
  - N3 can see only a result that never reached the model, i.e. post-hoc log rewriting, which is out of the threat
    model.

### 3.8 Concurrency-contention scaling (N4). **PARTIAL** [B3b item 5]

- **Closest work:**
  - **Rubenstein, Kurose & Towsley** (UMass TR 99-66 / SIGMETRICS 2000) decide from end-host delays whether two flows
    share a bottleneck (cross-measure vs auto-measure).
  - **Ristenpart et al.** (CCS 2009) detect VM co-residence from load-induced timing.
  - **RAFT** (Bowers et al., CCS 2011; IACR ePrint 2010/214) verifies a provider's claimed drive layout from
    parallel-read timing. Only the ePrint abstract was read.
  - **CPI2**, described via PANDA (arXiv 2511.08803); the CPI2 primary is **not opened**.
- **What they do not do.** None applies contention coupling to agent tool logs or to the executed-vs-generated question.
  RAFT, the conceptually closest and the likely reviewer citation, needs a challenge the verifier issues itself.
- **[INTERPRETATION]**
  - **Coverage binds:** TraceLab reports 1.2 tool calls per step. Report the overlap rate first.
  - **The premise holds narrowly:** only for fabricators that call an LLM at tool time.
  - **Noise is large:** PANDA twin tasks differ by 0.59× the between-task SD.
  - **Template:** use Rubenstein's cross-measure vs auto-measure test.
  - **#67730 is unreachable:** its fabricating subagents had zero tool_use entries.

### 3.9 Repeat-command determinism (N5). **PARTIAL, the closest of the B3 items to TAKEN** [B3b item 6]

- **Closest work:**
  - **AdvancedShelLM** (arXiv 2606.27990 §5.3). Human testers unmasked an LLM honeypot because "I did an ls in /var/
    twice, and got different results".
  - **shelLM** (arXiv 2309.00155) acknowledges the drift and prompts for repeat consistency.
  - **Galah and StableToolBench** (arXiv 2403.07714) cache responses "to ensure consistency".
  - **ToolEmu** (arXiv 2309.15817) makes consistency with the previous trajectory a Critical emulator requirement, judged
    by humans.
  - **The logic** is the Berenson et al. 1995 non-repeatable read A2 (arXiv cs/0701157) checked passively from history,
    as Elle does (arXiv 2003.10554).
  - **The premise** is SelfCheckGPT's (arXiv 2303.08896).
- **What they do not do.**
  - Every instance is live and attacker-side, or a design requirement on the fabricator, or a database check that
    trusts the record.
  - EC-Agent (arXiv 2610.00327) compares rerun digests, but actively and instrumented.
  - None is a passive check: identical read-only command, no intervening logged write, byte-different output, flagged.
- **[INTERPRETATION]**
  - **Framing:** present it as "Adya/Elle repeatable-read checking of the tool log", not a new idea.
  - **Defeats:**
    - A response cache keyed on the command defeats it, and that defence is already deployed: Galah, StableToolBench,
      and Ragsdale & Boppana and HoneyGPT via the SoK (**not opened**).
    - So does copying earlier output from context.
  - **Preconditions:**
    - It needs a no-unlogged-writer assumption.
    - Real nondeterminism must be normalised: timestamps, PIDs, ordering, timing lines.
  - **Two-sided:** static emulators are too deterministic where real output must change (Rouxii, arXiv 2609.26555).

### 3.10 Error-message fidelity (N5). **PARTIAL; general technique TAKEN; brief's premise FALSE** [B3c 7a–7d]

| Sub-claim | Verdict | Closest work: what it does / does not | Deciding citation (opened) |
|---|---|---|---|
| 7a. Fabricated or emulated command output betrayed by fidelity deviations: exact error strings, output conventions, consistency with earlier state | TAKEN | Bitter Harvest fingerprints honeypots by exact disconnect and error strings: Kippo "bad packet length" vs OpenSSH "Bad packet length", Cowrie `\n` vs OpenSSH `\x00`. Internet scans found 7,605 honeypots. The SoK and AdvancedShelLM list history inconsistency as an LLM-shell tell. All use active probing of a live system against a reference implementation, never a passive log check | Vetterl & Clayton, USENIX WOOT 2018 §4.4.2 (https://www.usenix.org/system/files/conference/woot18/woot18-paper-vetterl.pdf); arXiv 2510.25939 §3.1.1 |
| 7b. Passive cross-reference: paths, versions and line numbers in a recorded tool failure must agree with what the same transcript already showed | PARTIAL | ToolEmu requires emulated outputs, including exceptions, to stay consistent with the trajectory (human-judged: critical issues in 8.1% standard and 14.4% adversarial). ETF (arXiv 2410.14748) grounds code-summary entities against source. Spracklen et al. (arXiv 2406.10279) check package names against registries. None checks traceback paths, line numbers or versions against earlier records in the same log | arXiv 2309.15817 App. A.1 Table A.1; arXiv 2410.14748 §5.1 |
| 7c. Premise in the brief: "Nobody studies fabricated failures" | **TAKEN, so the premise is FALSE and must not appear in the writeup** | **Fabricated errors.** CEF/Thanatosis: a GPT-4o banking agent fabricated Python-style exception traces and invented error codes and timeouts. **Invented limits.** Sethi et al. (arXiv 2609.14758) and Singh (arXiv 2607.19449) document invented policy or capability limits after tool failure. **Invented environment.** Transluce's o3 report shows o3 inventing Python and GCC version strings. All of these sit in the agent's narration, not in harness-recorded tool_results. The CEF stack-trace case is n = 1 and "did not recur" under control | arXiv 2606.14831 §1, §4.6; https://transluce.org/investigating-o3-truthfulness |
| 7d. A detector for fabricated stack traces or error records exists | NOVEL (search-bounded) | CEF lists detection avenues as untested hypotheses (§5.2). arXiv 2605.24137 trains a classifier on bug-report summaries, not a fidelity check. Sentry attaches source context at capture time, which is instrumentation | arXiv 2606.14831 §5.2; arXiv 2605.24137 §III-C |

**[INTERPRETATION]**
- **Narrow the gap claim.** Fabricated failures are documented in narration and detected with judges, keywords or
  external witnesses. Nobody checks the fidelity of a recorded error against the log itself.
- **Expect mostly `unconstrained`.** A passive check cannot choose its probes, so verdicts will be `unconstrained`
  unless the log holds an earlier read, listing or version print. Report coverage before precision.
- **It catches only a minority.** ToolEmu's GPT-4 emulator had no critical consistency issue in 85.6–91.9% of cases, so
  the check catches only naive fabrication.
- **Truncation.** Truncated results (swechat 10 KB cap) must be `unconstrained`.
- **Key templates narrowly.** Error strings are implementation- and version-specific, so any template must be keyed by
  harness × tool × version.
- **Pair it.** Add a claim-vs-record check, so that narrated fake errors with no matching failed tool_result are caught.
- **Zero-error-tail is evadable.** CEF shows models produce plausible errors spontaneously, so the Probe 3 zero-error-tail
  signal can be evaded by error fabrication.
- **Not opened:**
  - HackerOne #3125832, which rendered empty. Its fake-GDB detail is **UNVERIFIED**; heise.de confirms the
    nonexistent-function claim only.
  - Guan et al. HoneyGPT, Weber et al. and VelLMes, known only via the SoK and AdvancedShelLM.
  - CHIME.
  - ABTest, known only via AgentGuard (arXiv 2609.16287, opened).

### 3.11 Cross-harness non-transfer of detection signals (N6). **PARTIAL as a claim; NOVEL as the grid** [B3c 8a–8e]

| Sub-claim | Verdict | Closest work | Deciding citation (opened) |
|---|---|---|---|
| 8a. Log anomaly detectors do not transfer across systems | TAKEN | FreeLog Table 1(c): zero-shot BGL→HDFS F1 3.32 (PLELog) and 4.35 (LogRobust), against 68–82 in-target. CroSysLog: OneLog cross-system "resulted in zero F1-Scores". Infrastructure logs, not agent transcripts | arXiv 2507.19806 Table 1; arXiv 2412.15445 §I C3, §II-B |
| 8b. Generated-content and hallucination detectors degrade under domain or generator shift | TAKEN | M4, RAID, and Orgad et al. (truthfulness probes are "skill-specific"). Counter-example to report: Pacchiardi et al.'s black-box lie detector transfers widely (arXiv 2309.15840) | arXiv 2305.14902; arXiv 2405.07940; arXiv 2410.02707 §4 |
| 8c. Agent-trace detectors change accuracy, prevalence or thresholds across benchmarks and scaffolds | TAKEN | TraceProbe normalises Claude Code, Codex and OpenCode trajectories and applies frozen deterministic detectors. Prevalence is scaffold-specific: structured-plan-absence is 49.6% vs 0.4% in a same-model scaffold control, and thresholds "should be audited on the target benchmark". ImpossibleBench: the same monitors catch 86–89% on LiveCodeBench but 42–65% on SWE-bench (arXiv 2510.20270). TRAIL: 0.183 vs 0.050 (arXiv 2505.08638). Silent Failure: leave-one-domain-out AUROC about 0.69 vs task-disjoint about 0.83 (arXiv 2606.09863; see §4) | arXiv 2607.06184 §V, §VI |
| 8d. The headline sentence "fabrication-detection signals do not transfer across harnesses" | PARTIAL | TraceProbe (deterministic process signals, not fabrication signals) and Silent Failure (learned text detector) together show that per-scaffold or per-domain calibration is needed. Cross-model transfer can hold while cross-domain transfer fails: leave-one-model-out about 0.91 vs leave-one-domain-out about 0.69 | arXiv 2607.06184 §VI; arXiv 2606.09863 Tables 8–9 |
| 8e. The N6 mechanism × corpus grid for witness-free tool-log fabrication signals, with failing cells | NOVEL (as a measurement) | TraceProbe reports detector × scaffold prevalence, but has no fabrication signals, no honest-vs-fabricated positives, no timing, token or request-id identities, and no recall-under-attack | arXiv 2607.06184 Tables II and V |

**[INTERPRETATION]**
- **Frame N6 as quantifying an expected effect for a new signal class.** It is not a surprise.
- **Separate harness from model.** Stratify so they are not confounded, copying TraceProbe's same-model scaffold
  control.
- **Cite TraceProbe in B7.** It already ships scaffold adapters normalising Claude Code, Codex and OpenCode into a common
  schema with timing and error status (Zenodo 10.5281/zenodo.20789918, 280.4 MB, licence not shown). This lowers the
  novelty of the B7 normalized-corpus release; the archive was not downloaded.

### 3.12 Other internal-embodiment findings from the corpus tasks (B4, B5)

| Claim | Verdict | Closest work: what it does / does not | Deciding citation (opened) |
|---|---|---|---|
| Witness-free structural checking of call/result records (join integrity) | PARTIAL | Harbor ATIF Pydantic models raise an error if an observation's `source_call_id` is not among the step's tool_calls, require sequential step_ids and parse every timestamp as ISO-8601. They do not check ordering (567 published ATIF files are non-monotonic and pass), content or duration | harbor `src/harbor/models/trajectories/trajectory.py` @3e30cca0, `validate_tool_call_references` [B5b] |
| Verify claims from the recorded artifacts without re-execution | PARTIAL | `swebench submit verify` re-grades from recorded test output ("No Docker and no re-execution"). It trusts the record, like OverclaimBench, and reads no timestamps, durations or ids | SWE-bench @02e7a74f `sb_submit_verify.py` docstring (local copy in `B5a_sweagent_openhands/sources/`) [B5a] |
| Tool-result shape or contract validation (N5 well-formedness) | PARTIAL | Dubey 2026's `tool_contract` "asks whether a result matched any shape its tool can return", on mock tools: 0/1,825 healthy flagged, 46% of injected context corruption caught. It treats tool results as ground truth for its fabrication class | arXiv 2608.02464 [B5d] |
| A harness commits to model I/O | PARTIAL (not a neighbour) | The Aider benchmark stores sha1 of each LLM request and response, computed by the same process. It never covers tool output | aider `base_coder.py` @5dc9490b [B5b] |
| Harness-written substitute results are labelled | N/A (data property) | mini-swe-agent pads unexecuted actions (`returncode: -1`, "action was not executed"). Using such flags as fabrication ground truth: **UNVERIFIED** | mini-swe-agent `actions_toolcall.py` @04d809ce L88 [B5a] |
| An instrumented release keeps the provider ids a B2 check needs | No (data fact) | AgentBRANE gateway receipts drop request ids and headers in the public projection. SCHEMA.md: "Authentication headers, response headers, provider request IDs, body artifact names, and raw request/response payloads are excluded". The schema does not mention timestamps; B5d's "no timestamps" is an observation of the data (skeptic) | HF `melissapan/swe-bench-lite-agent-traces-v14` SCHEMA/README [B5d] |

### 3.13 Not covered by Track B: novelty still UNVERIFIED

**These mechanisms have no Track B verdict.** DESIGN.md must not describe them as having cleared prior art:
- **FINDINGS §4.3 rank 2, the provider image-token ledger.** The closest covered item is token conservation (§3.1,
  PARTIAL). Nothing was searched for per-modality token counts as an exact count of screenshot-returning results.
- **FINDINGS §4.3 rank 3, the git execution window.** It was not researched. FINDINGS' own grounding checks call it
  partly prior art: claim-vs-record existence checks, event-time bounding, and output-grammar parsing (jc).
- **N5 sort-order violations, truncation-boundary behaviour, whitespace and formatting fingerprints, output-size
  distribution per command, and the cold-start signature.** These were not researched. The nearest covered prior art is
  honeypot fingerprinting by output conventions (§3.10, 7a, TAKEN as a technique) and shape validation (§3.12, Dubey
  2026).

---

## 4. Conflicts, corrections and process caveats

- **Silent Failure (arXiv 2606.09863) conflicts with the settled context.**
  - CLAUDE_context §7 says it is "TF-IDF only, no XGBoost".
  - Two agents independently read v1 (alphaXiv / arXiv HTML) as reporting TF-IDF+XGB columns and an XGBoost latency of
    1.19 ms [B1d, B3c].
  - This file cites only its transfer AUROCs and repeats neither statement about XGBoost. **A human should reconcile
    this before the writeup cites its detector.**
  - The skeptic's re-open of the arXiv HTML (version not pinned) also shows TF-IDF+XGBoost columns, with LOMO 0.913,
    LODO 0.665 and task-disjoint 0.825. It also shows "XGBoost inference on CPU takes 1.19 ms". The AUROCs this file
    uses (TF-IDF+LR: 0.904 / 0.696 / 0.849) are confirmed.
- **The brief's N5 premise is false.** Fabricated failures are documented (§3.10 7c). Remove the sentence from any
  writeup.
- **Gemini id clock resolution.** Phase C assumed 1 s. The microsecond field is supported by a pre-stated test (§1.2).
  FINDINGS §4.2.1/§5.7 should be updated by the owner.
- **The Gladyshev & Patel link in FINDINGS §4.3 rank 1**, which the grounding skeptic flagged as an unverified
  recollection, is now corroborated through Willassen 2008, which was opened. The 2005 primary is still unopened.
- **Split hygiene.** B2a's raw aiv_cu scans ran in file order with no split filter. They touched 517 rows / 270
  sessions of held-out split H, plus some rows of E, B and A (`B2a_provider_id_facts/split_exposure.json`). Only
  id-format aggregates were computed, and no detection threshold was tuned. **The orchestrator must judge whether this
  breaks the "nothing reads H" rule.** B4 skipped H throughout.
- **Quote fidelity.**
  - curl and the GitHub API were denied to B2a, so its web evidence came through WebFetch extraction. Ids and numbers
    were cross-checked by decoding.
  - B1b marks WebFetch-extracted quotes; re-open them before quoting them in the writeup.
  - B1d found that WebFetch missed timing passages that ACE's PDF does contain, so negatives obtained only by WebFetch
    screening are weak.
  - Weak-negative sources: NovaFabric, Tracekit, AFR, SINGED, the Inspect Scout paper, Silent Failure, LEDGER,
    SLEIGHT-Bench, Agent-Diff, Kirgis et al. and the MALT card in B1d.
- **Dead ends respected.** No agent cited thimble, TwinCheck or swarmtraces, nor the mis-titled arXiv 2604.01151 or
  2609.22600. Nothing swarm-related was read, no transcripts were generated, and nothing was committed.

---

## 5. Skeptic changes

A citation skeptic re-opened 103 citations: every deciding citation behind a NOVEL or PARTIAL verdict, and most B1/B2
citations. It also searched again for B1 and B2 prior art. The evidence is in
`analysis/out/phase_e/track_b/B_citation_skeptic.json`, which records the URL, how each source was opened, the deciding
passage and a status for each citation.

**Outcome:**
- 86 confirmed as cited.
- 15 confirmed but needing a wording or location fix.
- 1 unreadable (Haber & Stornetta, an image scan).
- 1 not found (Vanini et al. 2024, already UNVERIFIED).
- **No cited source turned out not to exist.**
- The citations not re-opened are listed in the JSON under `not_reopened_by_skeptic`. They are mostly supporting
  rather than deciding, and they keep the originating agent's `opened: true` status.

### 5.1 Verdict changes

| # | Item | Before | After | Evidence (opened) |
|---|---|---|---|---|
| V1 | B2 conjunction sub-row (§1.1) | PARTIAL | PARTIAL, **near-TAKEN as a method** | Willassen 2008 §2 (https://dl.ifip.org/db/conf/ifip11-9/df2008/Willassen08.pdf) already sets Gladyshev & Patel 2005 bracketing by externally timed events beside Schatz et al. 2006 server-clock correlation with a local clock hypothesis. Email threat hunting compares an InternetMessageId-embedded date with a recorded processing timestamp (Albea KQL, kqlsearch.com). Only the provider-minted id clock and the agent-log setting remain unfound |
| V2 | B2 time-anchor sub-row and verdict-table deciding citation | TAKEN; deciding citation "arXiv 2412.12814 time-anchor definition" | TAKEN; 2412.12814 re-labelled as a one-sentence secondary summary, with the Vanini et al. 2024 primary UNVERIFIED | 2412.12814 §4: "Another concept is time anchors as discussed by [19] …" Its authors are Vanini, Hargreaves and Breitinger, a different paper from [19] |
| V3 | Futuremark row (§1.1) | TAKEN (narrow), "re-open before quoting" | TAKEN (narrow), quote confirmed | hwbot forum: "Added Windows RTC clock verification, results with inaccurate time measurement can now be rejected on 3DMark.com" |

**Unchanged verdicts.** All other verdicts stand. Their deciding citations were confirmed:
- B2 application: NOVEL.
- B2 fact: N/A, with the material limitation kept.
- B1(a): PARTIAL.
- B1(b): PARTIAL (narrow).
- B3.1–B3.12: as before.

No opened source decodes an LLM-provider request or message id as a clock for agent tool-log stamps. No source
correlates a workload-conditioned residual with output size.

### 5.2 Corrections to citations and wording

| # | Where | Correction | Evidence |
|---|---|---|---|
| C1 | §1.1 skew-tolerant row | Willassen 2008 never uses the word "antedating"; that is his ARES 2008 paper, not opened. Reworded to Thm 2 plus Thm 3 (Test-A) | pypdf text of Willassen08.pdf |
| C2 | §1.1 conjunction row | Broken cross-reference "see §1.6" changed to §1.5 | file structure |
| C3 | §1.1 NOVEL row | OTel GenAI does not say the response id is "for correlation only". The registry defines it as "The unique identifier for the completion." | registry.yaml @e07f4eba |
| C4 | §1.1 systems row | Langfuse `mapping.rs` and Codex `inference.rs`: content confirmed, cited line numbers not confirmed | raw files at pinned commits |
| C5 | §3.5 | The Codex quote "runtime payloads are evidence, not proof …" is in `codex-rs/rollout-trace/README.md` (Reducer Invariants), not `inference.rs` | README via alphaXiv GitHub reader |
| C6 | §2.1 B1d row | METR 2025 describes triage of anomalously high-scoring runs and an LLM monitor. It does not describe a solution-runtime or timing check | metr.org/blog/2025-06-05-recent-reward-hacking |
| C7 | §2.1 B1a row, design-pattern list | Kovah 2012 confirmed from the IEEE S&P 2012 copy, because the MITRE URL returns 403. The "baselined independently" sentence is about TPM tick counts | ieee-security.org/TC/SP2012/papers/4681a239.pdf, pypdf text |
| C8 | Verdict table B1(b); §2.2 B1c row | Early Bird: the flat-vs-linear TTFT observation (§IV-D) and the 2.0 s / 89% thresholded attack (Fig. 11) are separate passages | arXiv 2409.20002 pages read |
| C9 | §2.4 | Leiner 2019: completion time is the most reliable indicator of careless responding; it fails on intended faking | Leiner 2019 abstract |
| C10 | §3.1 | Paritok Table 2 is a between-arm identity (compressed vs uncompressed differ by the compressed slice), not a within-session delta check | arXiv 2609.22114 HTML |
| C11 | §3.2 | KeyPooling "Table XI" not located; the route-granularity sentence sits with Table II §VI-B | arXiv 2608.17485 HTML |
| C12 | §3.12 | AgentBRANE SCHEMA excludes request ids and headers but does not mention timestamps | HF SCHEMA.md |
| C13 | §1.5 | Tool Receipts' reference "Tharakan 2025, arXiv:2503.11221" resolves to an unrelated image-quality paper (A-FINE). The nabaos `receipt.rs` fields match the paper's §3.2 receipt | alphaXiv 2503.11221; raw receipt.rs |
| C14 | §1.5 | Haber & Stornetta copy is an image scan; §6.2 reading not re-verified. Vanini 2024 primary still not openable | gwern PDF (CCITTFax); DFRWS 403 |
| C15 | §4 | Silent Failure: the arXiv HTML opened by the skeptic also shows TF-IDF+XGBoost and a 1.19 ms XGBoost latency. This file's TF-IDF+LR AUROCs are confirmed. The conflict with CLAUDE_context §7 is still for a human | arxiv.org/html/2606.09863 |

### 5.3 Prior art the earlier pass missed (all opened)

| Item | Relevant to | What it does / does not | Effect |
|---|---|---|---|
| **Albea 2026 KQL query** (InternetMessageId date vs processing Timestamp), https://www.kqlsearch.com/query/Detect%20Potential%20Malicious%20Emails%20Based%20On%20Internetmessageid%20Dates&cmoast5p700023nlo25dqehv1 | B2 conjunction | **Does:** a passive per-record flag on recorded email logs, comparing an id-embedded date with a log stamp. **Does not:** it is one-sided with day-level tolerance, has no causal bracket, and trusts the log over the id. The repo exists; the specific file was not located | V1 |
| **Willassen 2008 §2** (Gladyshev & Patel 2005; Schatz et al. 2006; Boyd & Forster 2004; Weil 2002) | B2 conjunction | **Does:** brackets with externally timed events and confirms or refutes a clock hypothesis from server-generated times. **Does not:** use an id-embedded clock, automate the check or touch agent logs | V1 |
| **Metaspike Gmail case**, https://www.metaspike.com/forensic-examination-manipulated-email-gmail/ | B2 id-embedded time | **Does:** reads a FILETIME inside a MIME boundary to expose a backdated message. **Does not:** use a tolerance; it is manual, and the token is client-minted | Analogue only |
| **Luo et al., arXiv 2605.02187** (BYOK relay tampering; sign-c) | B2 provider-as-witness; threat model; B3.4 | **Does:** shows relays can rewrite tool_use fields undetectably after the fact, and proposes provider signatures over execution fields. **Does not:** use provider ids or clocks; it needs instrumentation | Added to §1.1 and §1.4 item 4: field rewrites pass the id bracket |
| **Qin et al., arXiv 2609.30266 §1–2** | B2 provider-as-witness | **Does:** names provider compliance APIs as limited independent evidence and recommends an off-host interception server. **Does not:** use provider records; its blue team excludes them | Added to §1.1 |
| **crewAI PR #4077**, https://github.com/crewAIInc/crewAI/pull/4077 | B3.4 (N2) | **Does:** rejects outputs that hold both an Action and a Final Answer, i.e. inline-fabricated tool cycles, at parse time. **Does not:** merge, count tokens or audit logs | Added to §3.4 |

**Searched without a relevant hit:**
- Public decoding of Anthropic `req_`/`msg_` or OpenAI `chatcmpl-` ids.
- Discord/Snowflake screenshot verification (only generic decoders).
- MongoDB ObjectId vs `createdAt` tamper checks (only blog-level tips).
- LLM-honeypot timing tests that scale with output length (none beyond Honeyval/SoK/ShellGames/Palisade).
- Tool-call execution-time fabrication detectors in 2026 papers.

**Opened and rejected:**
- Chameleon (arXiv 2608.15407).
- Dispatch-level instrumentation (arXiv 2608.28439).
- A2A-ForensicTrace (arXiv 2609.33924).
- zkAgent (IACR ePrint 2026/199).

**Not touched:** no swarm material, no transcripts generated, no commits.
