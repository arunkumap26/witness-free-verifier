# Corpus inventory (Phase E Track B: B4, B5, B6, B7)

2026-10-04. This file consolidates the Track B corpus work: the audit of what we held (B4), the acquisitions (B5a-e), the
assessment of generating a request-id corpus (B6) and the cost of a release artifact (B7). It adds no new analysis of
mechanisms. Section 5 is written so a loader can be built from it.

**Provenance rule.** Every number below is in a file under `analysis/out/phase_e/`. Each section names its files. Short
names used throughout:

| Tag | File (all under `analysis/out/phase_e/track_b/` unless stated) |
|---|---|
| [b4] | `b4.json` (probe `analysis/probes/phase_e_b4_inventory.py`, raw output `analysis/out/phase_e/b4_inventory.json`) |
| [B5a] | `B5a_sweagent_openhands.json` (+ `B5a_sweagent_openhands/census/*.json`) |
| [B5b] | `B5b_aider_tbench_metr.json` (+ `B5b_aider_tbench_metr/{id_clock_checks,tb2_stats_v2,glm_stats_v2}.json`) |
| [B5c] | `B5c_web_os_agents.json` (+ `B5c_web_os_agents/b5c_field_audit.json`) |
| [B5d] | `B5d_hf_search.json` |
| [B5e] | `B5e_cli_traces.json` (+ `B5e_cli_traces/census/census_downloaded.json`) |
| [B6] | `B6.json` |
| [B7] | `B7.json` |
| [CI] | `corpus_inventory.json`, written by `corpus_inventory/compose_inventory.py` (this task). It holds the disk census, the distinct request-id census, the agentcap join check, the corpus registry and every derived total used here. |
| [SK] | `corpus_skeptic.json` (+ `corpus_skeptic/{field_audit,full_counts,request_id_scan,combo2_synthetic,openhands_shapes,context_probe}.json` and the scripts beside them): the corpus skeptic's independent re-check. See "Skeptic changes" at the end. |

Paragraphs marked **Interpretation** are reasoning, not measurement.

---

## 0. Bottom line

1. **Provider request ids are present in 5 of the 21 corpora we hold, and 4 of those 5 are public.** All 5 are Claude Code
   talking to Anthropic: one harness, one provider. Before B5 the count was 2 of 7, with 1 public [b4]. The new public
   corpora add 19,281 distinct request ids, which is 0.063 of swechat's 305,727 (non-H) [CI `request_id_totals`]. They add
   operators, Claude Code versions and dates. They add no harness and no provider. The id layout (UUIDv7, ms) is still
   inferred from data, not documented by the vendor [b4].
2. **No second harness or provider carries request ids.** The nearest substitutes are provider *response* ids with an
   embedded time at 1 s resolution: OpenAI `resp_` (TB2 hookele, Pi sessions), Meta Muse Spark (OSWorld), Gemini
   `responseId` (aiv_cu). See 1.2.
3. **B5 downloaded 14 corpora, 14.958 GB on disk; 10.042 GB of the 25 GB cap is left** [CI `disk`]. All 14 passed the field
   audit before download. The skeptic re-ran it on samples: all 14 pass, two of them weakly (OSWorld, WebArena-Infinity:
   one stamp or window per step, positional join) [SK]. All declare MIT, Apache-2.0, CC BY 4.0, CC0, BSD-3-Clause or
   (one repo) AGPL-3.0 on their cards.
   One corpus is over the 5 GB per-corpus cap on disk, and only because of a `.git` folder (section 2.4).
4. **Most useful new holdings:** the Terminal-Bench 2 leaderboard subset (21 ATIF harnesses plus 3 native log formats on
   the same 89 tasks: the cleanest cross-harness control for N6); TraceLab (743,819 tool calls, of which 304,290 Claude
   Code and 438,760 Codex carry both a call and a result stamp; content removed: timing at scale for N1/N3); OpenHands
   eval outputs (a second harness with id join, exit codes and 19 model strings); combo2 (4,525 tool results the harness itself flags as substituted: the only natural labelled
   positives we hold, and they are not zero-latency).
5. **B6:** generating a corpus for request-id *coverage* is no longer needed, because public raw Claude Code JSONL keeps
   `requestId`. Only the B6 micro-pilot (P0, 3-4.5 engineering hours) still buys something new: a documented server
   clock beside each id. It is blocked on human decisions H1 to H3 (extra usage is enabled on the account) [B6].
6. **B7:** before the 3:00 pm freeze, do T0 only: the coverage table for the writeup, 1-2 h [B7]. B7's licence matrix
   predates the acquisitions. Adding them to a release needs new loaders: 11 new formats, 22-44 h by extrapolating B7's
   2-4 h per loader [CI `loaders`]. It also needs a per-corpus licence and secrets pass.

---

## 1. Inventory of the corpora we hold

### 1.1 Request-id column first

Definition [b4 `REQUEST_ID_COLUMN_FIRST/definition`]: a provider request id is an id the LLM provider mints per HTTP
request and the harness stores in the log (Anthropic `request-id` header, value `req_...`). Response, message and item
ids are not counted here even when they embed time; they are in 1.2.

**Plain statement: 5 of the 21 corpora we hold carry provider request ids (swechat, cc_local,
terminal-bench-2-leaderboard, cli-trace-commons, cli-claude-code-hf). 4 are public; cc_local is private. All 5 are
Claude Code to Anthropic. Within terminal-bench-2-leaderboard only 1 of the 25 submissions whose logs we hold carries
them (the repo has 75; the other 50 are in our subset as result.json/exception.txt only), and within
cli-claude-code-hf 10 of 12 repos do.** [CI `registry`]

| Corpus | Public | **PROVIDER REQUEST IDS** | Coverage (unit stated) | Distinct ids | Agree with carrying event in [-2 s, +600 s] | Source |
|---|---|---|---|---|---|---|
| swechat, Claude Code format | yes (ODC-BY) | **YES**: Anthropic `req_`, incl. 494 `req_vrtx_` | calls 380,855/388,605 = 0.980, session-clustered CI [0.973, 0.987] | 305,727 (non-H) | 305,584 | [b4] |
| swechat, all six formats | yes | Claude Code only | calls 380,855/429,071 = 0.888 [0.862, 0.909]; Codex, OpenCode, Gemini CLI, Cursor, Copilot contribute 0 | | | [b4] |
| cc_local | **no** (private) | **YES**: Anthropic `req_` | calls 41,707/41,707 | 35,379 | 35,227 | [b4] |
| terminal-bench-2-leaderboard | yes (Apache-2.0 card) | **YES, 1 of 25 submissions with logs (75 in repo)**: WozCode__Claude-Opus-4.6 (Claude Code) | 444/444 sessions; 12,327 entries | 7,272 | 12,279/12,327 entries (0.9961) | [B5b] `id_clock_checks.json`, [CI] |
| cli-trace-commons | yes (CC BY 4.0) | **YES** | 7,496/7,499 assistant entries | 4,349 | 7,496 entries | [B5e] census, [CI] |
| cli-claude-code-hf (12 repos) | yes (per repo) | **YES, 10 of 12 repos** | 21,577/24,425 assistant entries; none in INONONO (0/146) or victor (0/268); AlinCiocan 271/2,506 | 7,660 (2,576 shared by two repos, counted once) | 21,567 entries | [B5e], [CI] |
| aiv_cc | gated, custom terms | NO | calls 0/72,225 | | | [b4] |
| aiv_cu | gated, custom terms | NO: 0 request-id keys in 2,446,268 non-H rows | | | | [b4] |
| whowhen | yes (MIT) | NO | calls 0/968 | | | [b4] |
| collusion-wiki, urlquery | licence UNVERIFIED | n/a: no LLM calls (external witnesses) | | | | [b4] |
| tracelab-uw | yes (CC BY 4.0) | NO: ids pseudonymized | | | | [B5e] |
| cli-codex-hf | yes | NO: no request or response id in rollouts | | | | [B5e] |
| cli-pi-hf | yes | NO: response ids only (1.2) | | | | [B5e] |
| agentcap-dacorvo | yes (Apache-2.0) | NO: capture `request_id` is minted by the capture proxy; models are local or HF-Router | | | | [B5e] |
| openhands-evaluation-outputs | yes (MIT) | NO: v2.x carries response id + `created` | | | | [B5a] |
| openhands-feedback | yes (MIT) | NO | | | | [B5a] |
| miniswe-v2-qwen3-30b-swebv-tarsur385 | yes (MIT) | NO: ids minted by the operator's vLLM | | | | [B5a] |
| sweagent-combo2-rl-rollouts | yes (MIT) | NO | | | | [B5a] |
| glm52-nf3-tb21-traces | yes (MIT) | NO: self-hosted vLLM | | | | [B5b] |
| osworld_verified_trajs | yes (MIT) | NO: Claude runs went through Bedrock (`msg_bdrk_`), 0 `req_` | | | | [B5c] |
| webarena_infinity_trajs | yes (MIT) | NO | | | | [B5c] |

Notes on the column:
- TB2 "1 of 25" was checked as follows. B5b scanned the 3 submissions with native Claude Code JSONL: WozCode has ids;
  ClaudeCode__GLM-4.7 and cchuter have 0. This task scanned all 9,670 ATIF `trajectory.json` files for request-id-like
  keys or `req_` values and found 5 matches in `mteb-leaderboard` trials [CI `atif_request_id_scan`]. That regex
  misses ids inside escaped JSON. The skeptic's strict scan of every TB2 file (Anthropic layout) finds 6 ids outside
  WozCode, in 6 files of Meta-Harness (3), Terminus-KIRA (2) and JJAgent (1). All 6 sit inside observation content or
  step message text (API error bodies), none in a harness field, so the conclusion stands [SK]. 25 submissions hold
  structured logs (21 ATIF; native-only ClaudeCode__GLM-4.7, cchuter, Gemini-CLI Flash, hookele). The other 50 (not 53)
  were downloaded as `result.json` + `exception.txt` only, so they are unchecked [SK `field_audit.json`].
- Evidence status: no file under `analysis/out/phase_e/track_b/` is committed yet, so the B5 rows of this column rest on
  uncommitted files. The skeptic re-derived the three YES rows from the data, entry for entry (WozCode 12,327 / 7,272 /
  12,279; cli-trace-commons 7,496 / 4,349 / 7,496; cli-claude-code-hf 21,577 / 7,660 / 21,567). A full-content scan
  found no Anthropic-layout id in any harness field of the other 11 acquired corpora. The B4 rows agree with committed
  files: cc_local and aiv_cc request-id fill in `out/build/*_build.json`; swechat split-B ids in
  `out/phase_c/ids_and_clocks_in_ids.json` [SK].
- The agreement window and the UUIDv7 decode are B4's (inferred layout). Entry counts and distinct counts are different
  units: Claude Code writes one `requestId` on every content block of a response. B5e's headline figure "29,073 new
  public request ids" counts assistant entries. The distinct count for its two corpora is 12,009 [CI `request_id_totals`].
- No request id is shared across the three new public corpora, and no session id is either [CI
  `request_id_scan_new_public_cc/corpus_pairs_overlap`]. Overlap with swechat was not checked, because that would mean
  opening swechat's H split.
- Coverage gaps inside swechat Claude Code [b4]: Bedrock-backed calls carry none (0 of 3,575); 1,766 first-party calls
  lack one; the documented parquet tables drop the field, so it survives only in `transcripts/*.jsonl`.
- SWE-chat v2 (Hub main since 2026-10-02, 17,968 sessions, ODC-BY) has not been audited. B4 estimates about 2.5x more
  public Claude Code sessions if its raw transcripts keep `requestId`. That is UNVERIFIED [b4].

### 1.2 Other provider-minted ids with an embedded time (not request ids)

| Corpus | Id | Resolution | Measured agreement | Source |
|---|---|---|---|---|
| aiv_cu | Gemini `responseId`; OpenAI Responses item ids; Anthropic `msg_` (only after the 2026-07-06 format switch) | 1 s; 1 s; ms | Gemini 462,022/462,024; OpenAI 572,082 decodable, all agree; Anthropic 294,075 of 856,394 decodable. aiv_cu stamps a turn once, so there is no input-to-output window to bracket | [b4] |
| terminal-bench-2-leaderboard (hookele) | OpenAI `resp_` (hex50 layout) | 1 s | 12,804/12,804 inside [harness llm_call ts - 1 s, stream_summary ts + 1 s] | [B5b] `id_clock_checks.json` |
| cli-pi-hf | OpenAI `resp_` hex50; OpenRouter `gen-<unix s>` | 1 s | `resp_`: 4,877/5,452 within 5 s of the message stamp, and 574 of the 575 outliers come from one repo (woxQAQ/pi-web); `gen-`: 42/42 | [B5e] |
| osworld_verified_trajs (Muse Spark, 1 of 20 downloaded submissions) | Meta `resp_`/`rs_` (8 hex digits of Unix seconds) | 1 s | 8,228/8,231 steps within 1 s of `action_timestamp`, never after it; layout undocumented | [B5c] |
| openhands-evaluation-outputs (4 DeepSeek/Fireworks runs) | UUID + provider `created` | 1 s | Two Fireworks runs have 26 and 83 actions whose `created` is after the action stamp (min -0.159 s) | [B5a] |
| agentcap-dacorvo (HF-Router captures) | `sla_metrics.ts_us` in the SSE body | us | present on 2,006 capture rows; not tested | [B5e] |

### 1.3 Field inventory, all 21 corpora

Sessions and tool calls use each source's own unit (stated). "join" means the call-to-result join. B4 rows are non-H
measurements unless marked population.

| Corpus | Source, licence | Sessions | Tool calls | ms timestamps | Call/result join | Token counts | Truncation markers | Error markers | Field audit | Source |
|---|---|---|---|---|---|---|---|---|---|---|
| swechat/claude_code | HF SALT-NLP/SWE-chat @f66cca95 (v1), ODC-BY | 3,353 (pop. 4,925) | 388,605 (pop. 584,802) | 1,730,813/1,730,824 events | 388,002/388,605 by tool_call_id | 388,604/388,605 calls | 3,474/388,012 | is_error non-null 130,495/388,012, true 16,494; no exit code | pass | [b4] |
| swechat/codex | same | 161 | 17,153 | 74,868/74,868 | 17,063/17,153; 25 synthetic ids | per turn (token_count events) | 131/17,063 | native 11,063/17,063; exit_code 8,954 | pass | [b4] |
| swechat/opencode | same | 432 | 17,354 | 37,660/64,371 = 0.585 | 17,349/17,354; 4,903 synthetic ids | per step-finish | 308/17,349 | native 17,349/17,349; exit_code 4,163 | pass | [b4] |
| swechat/gemini | same | 51 | 5,104 | 14,441/15,469 | 4,617/5,104 | 4,601/5,104 | 1,300/4,617 | native 4,617/4,617 | pass | [b4] |
| swechat/cursor | same | 22 | 589 | 0/1,575 | none (no results recorded) | none | n/a | n/a | **fail** | [b4] |
| swechat/copilot | same | 2 | 266 | 2,250/2,250 | 265/266 | output only | 4/265 | native 265/265 | pass (n=2) | [b4] |
| cc_local | `~/.claude/projects` snapshot, private | 309 | 41,707 | 167,231/168,728 | 41,706/41,707 | 41,707/41,707 | 493/41,706 | native 30,581/41,706 | pass | [b4] |
| aiv_cc | HF aidigestorg/ai-village @838b4150, custom research terms, gated | 314 runs | 72,225 | row-insert us stamps | 72,213/72,225 | 72,225/72,225 | 62/72,213 | native 11,655/72,213 | pass | [b4] |
| aiv_cu | same | 76,114 (pop. 78,114) | 2,353,075 (calls counted per turn) | one stamp per turn, shared by call and result | by construction | per provider family | none marked | stderr channel only | pass | [b4] |
| whowhen | HF Kevin355/Who_and_When @59b9fcba, MIT (GitHub) | 184 | 968 (call ids loader-synthesised) | 0/4,371 | 888/968 | none | 0/888 | exit code 244/888 | **fail** | [b4] |
| collusion-wiki | local export, licence UNVERIFIED | n/a | 0 | wiki request-log times | n/a | n/a | n/a | n/a | n/a (witness) | [b4] |
| urlquery-agent-activity | local zip, licence UNVERIFIED | n/a | 0 | second precision | n/a | n/a | n/a | n/a | n/a (witness) | [b4] |
| terminal-bench-2-leaderboard | HF harborframework/terminal-bench-2-leaderboard @572b2614, Apache-2.0 (card) | 32,803 trials; 9,670 ATIF, 1,379 Claude Code JSONL, 884 Gemini-CLI, 443 hookele | ATIF 472,285; Claude Code 47,939; Gemini 21,009; hookele 12,230 | 399,962/399,962 ATIF steps (us or ms); hookele 1 s | ATIF 173,384 by id + 144,019 step-paired (Terminus); CC 47,852/47,939; Gemini 21,009 | ATIF metrics on 253,556 steps; 146,857 `api_request_times_msec` in 4,876 trials | Terminus 10,000-byte marker | CC is_error; Gemini "Exit Code: N"; exception_info on 5,398 trials | pass | [B5b] |
| glm52-nf3-tb21-traces | HF 0xSero/glm-5.2-nf3-hybrid-terminal-bench-2.1-traces @6020a41c, MIT (card) | 85 trials | 5,252 | 3,323/3,323 steps (us) | 2,106/3,237 by id, rest step-paired | yes; 3,199 api request times | Terminus marker | exception_info on 2 trials | pass | [B5b] |
| openhands-evaluation-outputs | HF OpenHands/openhands-evaluation-outputs @aa897780, MIT | 5,695 instances (19 runs) | 145,702 actions | 312,115/318,298 events (us) | 145,631/145,966 by cause (0.9977) | per action in v2.x (84,730) | 3,057 in v2.x; v1.9 unmeasured | exit_code 42,866; error obs 457 | pass | [B5a] |
| openhands-feedback | HF OpenHands/openhands-feedback @facf4560, MIT | 275 real-user sessions | 5,968 actions | 5,898/5,968 actions, 5,974/5,974 obs (us) | strict pairing 5,552/5,974 | none | 25 | exit_code 2,614; error obs 115 | pass | [B5a] |
| miniswe-v2-qwen3-30b-swebv-tarsur385 | HF tarsur385/... @58389eb5, MIT | 499 | 13,887 | 13,884/13,884 assistant, 13,664/13,664 tool (float s) | 13,664/13,664 by tool_call_id | 13,884 responses | not audited | returncode 13,664 (3,547 nonzero) | pass | [B5a] |
| sweagent-combo2-rl-rollouts (shard 00 of 6) | HF sweagent/combo2-rl-rollouts @eaff5487, MIT | 4,571 | 446,012 actions | 901,376/901,376 messages (float s) | 441,588/441,588 | token-id arrays only | not audited | returncode in content, 441,588 | pass | [B5a] |
| osworld_verified_trajs (20 of 99 submissions, text only) | HF xlangai/ubuntu_osworld_verified_trajs @5473c39e, MIT | 7,241 task runs | 145,817 steps | one stamp per step, before the action: us 49,907, s 95,890, missing 20 | positional (one row = action + its screenshot); call ids for Claude and Muse Spark | Claude/Muse/klick/Agent-S2 only | not measured | info.fail; tracebacks in logs; no exit codes | pass | [B5c] |
| webarena_infinity_trajs (Gemini/browser-use subset) | HF webarena-x/webarena-infinity-trajectories @73cf7f57, MIT | 844 | 11,760 actions (9,241 steps) | step start/end on 9,241/9,241 steps | positional; counts match in 9,078/9,241 steps | none | not measured | result.error 86/11,594 | pass | [B5c] |
| tracelab-uw | GitHub uw-syfi/TraceLab v0.0.2, CC BY 4.0 | 8,058 (Claude Code 5,319; Codex 2,739) | 743,819 (305,005 + 438,814) | ISO ms on every timing event and on tool `emitted_at`/`result_at` | tool_call_id (pseudonymized) with both stamps on 304,290 + 438,760 | per round | none (content removed) | is_error on every tool; Codex exit code 247,509 | pass | [B5e], [CI `derived_sums`] |
| cli-trace-commons | HF trace-commons/agent-traces @112ebd4d, CC BY 4.0 | 28 Claude Code + 1 OpenCode + 1 Cursor files | 4,264 CC + 3 OpenCode | 12,174/12,174 user+assistant entries | 4,262/4,262 | 7,499 assistant entries | text only | is_error true 269 | pass | [B5e] |
| cli-claude-code-hf | 12 HF repos (5.1) | 379 JSONL files; 210 distinct sessionIds | 12,997 | 39,686/39,686 | 12,994/12,994 results | 24,425 assistant entries | text only | is_error true 612 | pass | [B5e], [CI] |
| cli-codex-hf | 6 HF repos | 46 | 3,381 | 17,617/17,617 lines | 3,381/3,381 by call_id | 2,330 token_count events | "Original token count" wrapper | exit code in the output text wrapper | pass | [B5e] |
| cli-pi-hf | 23 HF repos | 530 session files, 522 distinct session ids (8 duplicate files hold 248 calls) | 23,974 | 55,175/55,175 entries; 50,107 messages with epoch ms | 23,928/23,928 by toolCallId | assistant usage | not measured | isError true 1,364 | pass | [B5e] |
| agentcap-dacorvo | 9 HF repos (dacorvo/*), Apache-2.0 | 804 (OpenCode 411 + Pi 393) | 11,499 (4,694 OpenCode tool parts + 6,805 Pi calls); 18,885 wire captures | OpenCode tool `time.start/end` on 4,685/4,694; Pi 16,073 messages epoch ms | OpenCode 3,934/4,694 parts with callID+output; Pi 6,804/6,805 | assistant tokens | not measured | OpenCode error field 751; Pi isError 991 | pass | [B5e], [CI `derived_sums`] |

---

## 2. Acquisition results (B5)

Rules applied by every B5 task [PHASE_E_PLAN.md]: public, research-permitting licences only; no gated sets (listed
instead); 5 GB per corpus and 25 GB total; destination `data/` (append-only); downloaded code never executed; field
audit on a sample before download. A corpus without per-event timestamps or a call/result join was not downloaded.

### 2.1 Downloaded (14 corpora)

On-disk bytes are from [CI `disk/per_dir`], measured 2026-10-04 after all downloads. Integrity column: what the
downloading task verified.

| Dir under `C:\Swarms\data\acquired\` | Source @ revision | Licence | On disk | Integrity | Why taken | Task |
|---|---|---|---|---|---|---|
| `openhands-evaluation-outputs/` | OpenHands/openhands-evaluation-outputs @aa8977805b4c | MIT | 4.762 GB (includes a 0.154 GB duplicate `.part` file) | 91/91 files match Hub LFS sha256 | Second harness with id join, exit codes, 19 model strings | B5a |
| `openhands-feedback/` | OpenHands/openhands-feedback @facf45600d62 | MIT | 0.114 GB | Hub LFS sha256 match | Only real-user (non-benchmark) OpenHands sessions | B5a |
| `miniswe-v2-qwen3-30b-swebv-tarsur385/` | tarsur385/qwen3-30b-a3b-instruct-2507-swebench-verified-mini-swe-agent @58389eb5426d | MIT | 0.224 GB | Hub LFS sha256 match | mini-swe-agent v2 format, same as the unlicensed SWE-bench bash-only leaderboard trajectories | B5a |
| `sweagent-combo2-rl-rollouts/` | sweagent/combo2-rl-rollouts @eaff5487b898, shard 00 of 6 + group_info | MIT | 0.446 GB | Hub LFS sha256 match | Harness-flagged substituted results (`extra.synthetic`, 4,525) | B5a |
| `terminal-bench-2-leaderboard/` | harborframework/terminal-bench-2-leaderboard @572b2614be2c, field-audited subset (52,543 of 513,085 files) | Apache-2.0 (card) | 5.884 GB, of which `hf_repo/.git` is 1.070 GB | sha256 of exact LF bytes; 1,766/1,766 match raw HTTPS | 75 submissions, about 24 log formats on the same 89 tasks; WozCode request ids; hookele `resp_` clock; Terminus timers | B5b |
| `glm52-nf3-tb21-traces/` | 0xSero/glm-5.2-nf3-hybrid-terminal-bench-2.1-traces @6020a41cb40c | MIT (card) | 0.104 GB | sha256 manifest | Self-hosted inference latency regime (no provider network) | B5b |
| `osworld_verified_trajs/` | xlangai/ubuntu_osworld_verified_trajs @5473c39e42a5, 20 of 99 submissions, text members only | MIT | 1.705 GB | CRC32 per member; sha256 per file in each `manifest.jsonl` | GUI agents; Claude toolu ids; Muse Spark id clock; klick ms log | B5c |
| `webarena_infinity_trajs/` | webarena-x/webarena-infinity-trajectories @73cf7f57a6ff, Gemini/browser-use subset | MIT | 0.104 GB | 1,690 files match Hub git blob ids | Browser agent with per-step start/end times | B5c |
| `tracelab-uw/` | GitHub uw-syfi/TraceLab release v0.0.2 asset `syfi_coding_trace.jsonl.gz` (repo commit 11b8b14c) | CC BY 4.0 (data), Apache-2.0 (code) | 0.101 GB | sha256 matches GitHub digest | Largest public CLI timing corpus (Claude Code + Codex), wall vs internal latency | B5e |
| `cli-trace-commons/` | trace-commons/agent-traces @112ebd4d03ce | CC BY 4.0 | 0.127 GB | per-file sha256 (`_b5e_manifest.json`) | Raw donated Claude Code sessions with request ids | B5e |
| `cli-claude-code-hf/` | 12 HF repos, each pinned (folder `<owner>__<repo>@<sha8>`) | MIT, Apache-2.0, CC BY 4.0, CC0, AGPL-3.0 (per repo) | 0.244 GB | per-file sha256; LFS match | Independent Claude Code uploads with request ids (Claude Code 2.1.131 to 2.1.252) | B5e |
| `cli-codex-hf/` | 6 HF repos, pinned | CC BY 4.0, MIT | 0.073 GB | per-file sha256 | Native Codex rollouts | B5e |
| `cli-pi-hf/` | 23 HF repos, pinned | MIT, Apache-2.0, BSD-3-Clause, CC BY 4.0 | 0.211 GB | per-file sha256 | Pi harness; carries provider response ids | B5e |
| `agentcap-dacorvo/` | 9 HF repos `dacorvo/*` (OpenCode + Pi traces + wire captures), pinned | Apache-2.0 | 0.858 GB | per-file sha256 | Native traces joinable to HTTP captures | B5e |

Total on disk 14.958 GB; headroom to the 25 GB cap 10.042 GB [CI `disk`]. Full repo lists with commit shas are in
[B5e `corpora_downloaded`]; per-file hashes sit next to the data.

### 2.2 Checked and not downloaded

**Passed the audit, not downloaded (licence, cap, approval or redundancy):**

| Candidate | Licence | Size | Why not | Task |
|---|---|---|---|---|
| Exgentic/agent-llm-traces (OTel spans, 5 harnesses, 1,781 sessions) | CDLA-Permissive-2.0 | 983.6 MB | B5d did not download without user approval in chat; priority A | B5d |
| melissapan/swe-bench-lite-agent-traces-v14 (AgentBRANE; Claude Code / Codex / Pi) | CC BY 4.0 | 2,087.6 MB | same; only the Claude Code third has timestamps; gateway stripped requestId | B5d |
| lihaonan0716/mcphunt-agent-traces (per-call epoch-us time, latency_ms, result_chars, truncation flag) | CC BY 4.0 | 593.5 MB | same; priority A | B5d |
| METR MALT (metr-evals/malt-transcripts-public) | MIT | 1.66 GB default config | gated (contact-info agreement); the account already has access; card schema passes, rows not inspected | B5b |
| CooperBench qwen9b mini-swe-agent coop / solo | MIT | 12.05 GB / 0.78 GB | coop over cap (two agents per task with messaging: swarm-relevant); solo redundant with tarsur385 | B5a |
| sweagent/combo2 shards 01-05, iter2-rl-rollouts | MIT | combo2 repo 2.93 GB, of which 0.445 GB was downloaded | kept unseen as confirmation data | B5a |
| OSWorld-Verified other 79 submissions, text only | MIT | about 4.2 GB | not needed yet; `bulk_text.py` fetches them | B5c |
| risenlab/agentlogs (GitHub Copilot cloud agent, 64M entries) | CC BY 4.0 | 56.7 GB | over cap; schema-level pass only; B5d has a shard-subset command | B5d, B5e |
| SWE-bench leaderboard trajectories (S3 + submitter repos; mini-swe-agent v2 subset passes) | none | e.g. 0.30 GB per entry | no licence | B5a |
| OpenHands Index full_archive tarballs (per-response latency and token ledgers) | none | e.g. 423,683,435 B and 515,328,661 B per archive | no licence; high value | B5a |
| OpenHandsCommunity/eval-output-webarena | none | 31.8 GB | no licence; every file over cap | B5a, B5c |
| thomasmustier/pi-for-excel-sessions | MIT | 300 MB | sampled session has no responseId; low marginal value | B5e |
| julien-c/synthtraces | MIT | 326 MB | an LLM plays the user (synthetic by design) | B5e |
| dacorvo Goose/Hermes traces + captures | Apache-2.0 | about 1.2 GB captures | harnesses outside the named set; not sample-audited | B5e |
| KernelBench (Infatoshi hard + mega) | MIT | 728.8 MB | B5d priority B. Non-Claude runs are rendered in Claude Code schema, so their timestamps may not be native | B5d |
| jedisct1/security-audits (Swival) | MIT | 1,685.2 MB | B5d priority B, but B5e found a sibling Swival export with call-to-result gaps of 0-4 ms (stamps do not record execution). Do not use for timing without a per-file gap check | B5d, B5e |
| 192 unlicensed HF datasets that pass the mechanical audit (separately, 89 unlicensed datasets carry request ids in their sampled file), e.g. nlile/misc-merged-claude-code-traces-v1 (1.16 GB, request_id + timestamp columns), Becks723/codex-traces, basedlsg/codex-assistant-rollouts | none | see [B5d], [B5e] | no licence | B5d, B5e |
| mlfoundations-cua-dev/osworld-trajectories | none | 23.3 GB | no licence | B5c |
| TB 2.1 official leaderboard jobs (Harbor Hub) | not stated | 22 jobs | needs the harbor CLI (third-party code) and has no licence | B5b |
| Simple-Codex `codex.txt` inside TB2 | Apache-2.0 | 32.7 MB | free text, but carries OpenAI `resp_` ids and per-exec wall time; cheap optional follow-up | B5b |

**Failed the field audit (no per-event timestamps, no join, synthetic or rewritten timing, or no tool calls):**
Aider benchmark logs (no public run logs, no tool calls); METR report transcripts and `runs.jsonl` (excerpts and per-run
rows); yoonholee/terminalbench-trajectories and mercor ApexAgents TB2.1 (timestamps stripped); nebius SWE-agent and
SWE-rebench OpenHands trajectories; SWE-Gym OpenHands sets; SWE-smith trajectories; Kwai-Klear mini_swe_agent_plus;
nvidia SWE-Zero / SWE-Hero / Open-SWE-Traces; livesweagent mini-swe-agent 1.14 (only provider `created`); OpenHands
CodeScout; sailplane; WhitzardAgent conversions (also broken licence provenance); Inferact and
ibm-research codex_swebenchpro traces (ibm-research's README says its timestamps are synthetic: random 1-10 s);
jedisct1/agent-traces-flashmania (49/49 gaps at most 0.004 s); owao/qwen38-27B (107/107 gaps at 0.000 s);
Jadson, Samarth0710, vedalken (converted or rewritten); PotatoHD; AgentBench (no release; one stamp per sample);
VisualWebArena GPT-4V+SoM (render HTML); McGill-NLP/agent-reward-bench (no per-step time; custom terms);
AgentTrajectorySentinel (no absolute timestamps, but has labelled injected corruption: see 6); LMCache agentic traces
(relative gaps only). Sources: [B5a] `corpora_failed_audit`, [B5b] `corpora`, [B5c] `listed_not_downloaded`, [B5d]
`corpora_failed_or_out_of_scope`, [B5e] `corpora_failed_audit`.

**Not released or not a corpus:** Cline (`cline/incident-traces` holds 0 sessions at the audited revision; its taxonomy
includes "deception"; worth re-checking); Roo Code (repo archived, exercises only); Microsoft Copilot production traces
(announced, not found); OpenCode share links (single sessions, no licence) [B5e].

**Search funnel.** B5d ran 40 HF queries (3,249 datasets) and audited 561 candidates, 505 of them with the Hub's
`format:agent-traces` tag. 276 passed the mechanical audit, but only 84 of those carry a licence (3.722 GB). Licence, not
schema, is the binding constraint [B5d `funnel`]. B5e independently censused the same 505-dataset tag population: 374 have no
licence tag [B5e `computed`].

### 2.3 For a human: gated, oversized, licence requests

| Item | What a human must do | Size | Value |
|---|---|---|---|
| METR MALT default config | approve the download (gate already accepted on the account) | 1.66 GB | only public set with manual misbehaviour labels; labels behaviours, not fabricated results |
| Exgentic, AgentBRANE v14, MCPHunt | approve the pinned `hf download` commands in [B5d] | 3,664.7 MB together [CI `derived_sums`] | multi-harness OTel spans; per-call latency + result size |
| xlangai/osworld2.0-trajectory | accept click-through terms; pick a subset | 248.5 GB | file list shows `call_*.json` and `api_usage.json`: possibly raw per-call API records |
| z-lab/glm52-cc; Intelligent-Internet/swebench-pro-gpt-5-codex-ii-agent-trajectories; Aeonthic/Agentic-SFT; Datoric/computer-use-agent-traces-250k; genlabs/OpenTraces; pablo85318/ml-intern-sessions; seekbot/seek-sessions | accept gate terms (none audited) | not measured | unknown |
| CooperBench coop | choose a sub-5 GB subset | 12.05 GB | two-agent coordination logs |
| AgentLogs | choose a shard subset: B5d suggests 10-20 of the 276 ~200 MB log shards (2-4 GB) plus agent_sessions (225 MB); B5e suggests a 1-shard audit first | 56.7 GB | second real-world harness at scale |
| SWE-bench S3 trajectories; OpenHands Index archives; OpenHands WebArena outputs; nlile merged Claude Code traces; unlicensed Codex sets; Between the Commits (doug-leith) | ask the owners for a licence | see [B5a], [B5e] | OpenHands Index has a per-response latency ledger; nlile declares a request_id column |
| SWE-chat v2 (Hub main, 17,968 sessions) | approve a download of the current raw transcripts for a requestId audit | not measured | possibly about 2.5x more public request ids (UNVERIFIED) |
| TB 2.1 Harbor Hub jobs | decide whether to install the harbor CLI | 22 jobs | live successor to the TB2 repo |

### 2.4 Hygiene items found on disk (data/ is append-only, so a human must act)

- `openhands-evaluation-outputs/outputs/SWE-bench_Lite-test/CodeActAgent/claude-3-5-sonnet-20241022_maxiter_100_N_v2.1-no-hint/output.jsonl.part`
  is a byte-identical duplicate of the `output.jsonl` beside it (153,841,006 B) left by a download race [B5a], [CI
  `disk/per_dir/openhands-evaluation-outputs/part_files`]. Safe to delete; loaders must glob `output.jsonl` exactly.
- `terminal-bench-2-leaderboard/hf_repo/.git` holds 1,070,068,963 B, including an orphaned 0.476 GB gc temp pack. That
  is the only reason the corpus is over the 5 GB cap on disk (4.814 GB without it) [CI `disk`], [B5b]. Removing it is safe
  because `_acquisition/FILES_SHA256.v2_lf_exact.jsonl` covers the content. Its remote URL was deliberately set to
  `https://invalid.invalid/lazy-fetch-blocked`; never run git fetch or `git lfs ls-files` there.
- **Credentials in upstream public data:** 446 `result.json`/`config.json` files under
  `submissions/terminal-bench/2.0/pilot-real__claude-opus-4-6` carry `CLAUDE_CODE_OAUTH_TOKEN` values with an `sk-ant-`
  prefix [B5b]. They are in our subset. Never print them; scrub agent env/kwargs from anything derived. Whether to tell
  the maintainers is a human decision. Separately, B6 saw what looks like an unredacted OpenRouter bearer token in the
  public first rows of `sammshen/swebench-sonnet-traces` (not downloaded) [B6 H9].
- **Credential-like value in cli-pi-hf (found by the skeptic, missing from earlier lists):** one session file in
  `cli-pi-hf/thomasmustier__pine-of-glass-sessions@b9a6b263/` (`2026-06-04T14-15-37-417Z_019e92fd-...jsonl`) contains an
  `sk-ant-api03-` value (79 characters, one distinct value, twice) in an `x-api-key` header of a curl command. It was not
  printed. Same handling as the TB2 tokens: never print, scrub from anything derived; whether to tell the uploader is a
  human decision [SK `context_probe.json`]. No other acquired corpus has an `sk-ant-` value. The two cli-claude-code-hf
  files that mention `CLAUDE_CODE_OAUTH_TOKEN` name the variable only.
- Several acquired dirs contain `.cache/huggingface/` download metadata; loaders should skip it. The 4 `.incomplete`
  files under `webarena_infinity_trajs/.cache/` are 0-byte markers; the files they refer to are present.

### 2.5 Seen-data warnings (keep tests blind)

- OpenHands eval: B5a computed `action.timestamp - model_response.created` per run. combo2 shard 00: B5a split latency
  by the synthetic flag. Pre-register any test of these on held-out instances or on combo2 shards 01-05 [B5a].
- CLI corpora: B5e computed call-to-result gap quantiles, request-id decode deltas, Pi `resp_` deltas, Codex
  "Wall time" marker rates and TraceLab wall-vs-internal inversions. Pre-register on held-out repos or sessions [B5e].
- B4 measured on swechat A, B and E only. H was never opened, and this task did not open it either [b4], [CI].

---

## 3. B6: assess generating a request-id corpus

Status: assessment only. Nothing was run, installed or generated [B6].

**What B6 found.**
- Claude Code JSONL already carries request ids (swechat 0.980 of calls, cc_local 41,707/41,707). What none of our
  corpora carries is the HTTP layer: response headers (`Date`, rate-limit headers) and a wire clock from a process other
  than the agent [B6 `bottom_line`].
- A corpus can be generated at zero marginal cash cost on the Max 20x plan, using documented features only:
  - `claude -p` and `claude setup-token`;
  - OTel `OTEL_LOG_RAW_API_BODIES=file:<dir>` for raw bodies keyed by request id;
  - optionally, a local TLS-inspecting proxy for headers and wire timestamps.
- **The blocker:** extra usage is enabled on the account (`hasExtraUsageEnabled = true`). Overflow would bill at API
  rates, so "no paid spend" cannot be guaranteed until a human disables it or sets a $0 cap [B6 H1].
- The method is TAKEN as a dataset practice. `sammshen/*` (14 HF datasets, MIT) captured HTTP pairs through a reverse
  proxy on public benchmarks, with HTTP `date` and proxy timestamps. They routed through OpenRouter, so they hold no
  first-party request-id header [B6 `prior_art_items`].
- Rejected options:
  - local models: the operator's server mints the ids, so there is no provider clock;
  - OpenCode Zen: the gateway mints the ids;
  - Codex on the ChatGPT login: standard rollouts hold no request id (0/792 local files), and OpenAI's docs point
    automation at paid API keys [B6 `options`].

**Options and verdicts** [B6 `options`]:

| Option | Verdict |
|---|---|
| A: Claude Code headless + JSONL + OTel raw bodies | viable base layer; lacks HTTP Date and an outside clock |
| B: A + local TLS proxy (mitmproxy, streaming mode) | viable if H3 is accepted; the only route to the documented Date clock |
| C: Codex CLI on the ChatGPT login | not recommended (ToS; API key = paid) |
| D: Gemini CLI free tier + proxy | optional second-provider arm; about 10 sessions/day |
| E: OpenCode Zen free models | reject (gateway-minted ids) |
| F: local models | reject (operator-minted ids) |
| G: download instead | check first (now done, see below) |

**Cost** [B6 `hours_estimate`]:

| Tier | Engineering hours | Wall clock | Scope |
|---|---|---|---|
| P0 micro-pilot | 3-4.5 | 0.25-1 h | tens of requests; checks the req_ layout against HTTP Date and a proxy clock |
| P1 quota pilot | 4-6 | 1-3 h | 5-10 public tasks; measures quota use per task |
| P2 corpus | 9-12 | 1-3 days | 100-200 Claude Code tasks |
| P0+P1+P2 | about 17-22 | plus 1-3 days | |
| Optional arms | Codex 2-3, Gemini 2 | | |

Only P0 fits before the 3:00 pm freeze, and only with slack in Track C.

**Human decisions** [B6 `needs_human_decision`]:

| Id | Blocking | Decision | Default if unanswered |
|---|---|---|---|
| H1 | yes | Disable extra usage or set a $0 cap before any run | no run of any size |
| H2 | yes | Tier: nothing / P0 / P1 / P2 (B6 recommends P0) | nothing |
| H3 | yes | Accept the ToS position for scripted runs on a Max subscription through a local proxy (the proxy sees the OAuth bearer; client-verification risk UNVERIFIED) | no proxy, no batch |
| H4 | no | Time window: after the freeze, with no overnight loop running | |
| H5 | no | Allow mitmproxy (MIT) and optionally Harbor/Docker images in a separate tool venv | |
| H6 | no | Publish or keep private; if published, strip Authorization, org ids, rate-limit headers, system prompts, paths | |
| H7 | no | Pin the Claude Code version (`--bare` will become the `-p` default and does not read OAuth) | |
| H8 | no | Confirm the ChatGPT plan before any Codex arm | |
| H9 | no | Tell the sammshen dataset owner about the exposed bearer token | |
| H10 | no | Later: a tampering arm in our own sandbox for real-provider labelled positives (out of this session's scope) | |

**What changed after B6 was written.** B6 made P1/P2 wait on B5e's audit of public raw Claude Code JSONL. That audit is
in: public uploads keep `requestId` (cli-trace-commons 7,496/7,499 assistant entries; cli-claude-code-hf 21,577/24,425)
[B5e], and TB2 WozCode adds 444 sessions [B5b].

**Interpretation.** Generating a corpus for request-id coverage is therefore unnecessary. What only generation can still
add:
- a documented server clock (HTTP Date) beside first-party ids (P0);
- a wire clock outside the agent process;
- possibly a non-Anthropic first-party request id (OpenAI `x-request-id`), whose layout is unknown.

None of these is a build dependency. H1 to H3 stay blocking.

---

## 4. B7: release-artifact cost

Status: assessment only [B7].

**Licence matrix for the B4 corpora** [B7 `licence_matrix`]:

| Corpus | Release as | Verdict |
|---|---|---|
| swechat | ODC-BY 1.0 shard. ODC-BY s.4.2(a) keeps a public derivative database under ODC-BY, so not CC BY 4.0; attribution-only, benchmarking allowed | redistributable with conditions |
| aiv_cc, aiv_cu | loader code + aggregates only, unless AI Digest gives written permission | not redistributable |
| whowhen | loader only, or a gated shard with GAIA question/answer text removed | MIT, but GAIA-encumbered |
| cc_local | never; even its aggregate row needs a human yes | never |
| collusion-wiki, urlquery | excluded (no licence, no tool calls) | not redistributable |

**Tiers and hours** (engineering judgement, not measured) [B7 `hours_estimate`]:

| Tier | Hours | Contents |
|---|---|---|
| T0 | 1-2 | coverage table + IR column reference in the writeup; no data |
| T1 | 7.5-12 | MIT code + SCHEMA.md + coverage table; users fetch each upstream themselves |
| T2 | 14-21.5 | T1 + scrubbed ODC-BY swechat shard on a gated HF repo |
| T3 | +4-6 | AI Village shards, only with written permission |

T2's line items:

| Item | Hours |
|---|---|
| Schema docs | 2-3.5 |
| Loader cleanup and full-population export | 4-6 |
| Coverage table | 1-1.5 |
| Dataset card | 2-3 |
| Privacy/secret scrub | 4-6 |
| Upload | 1-1.5 |

Estimated swechat IR shard: 623,829,773 B [B7 `release_size_estimate`].

**Main cost drivers:**
- The loaders only build sample caches today.
- Personal-looking emails appear in 0.3181 of non-H swechat sessions (1,280 sessions). Masking must preserve byte
  length, because result size feeds N1/N3/N5 [B7 `swechat_redaction_situation`].

**B7's recommendation:** T0 only before the freeze. T1 vs T2 is a morning decision.

**Prior art** (as recorded by B7):
- Schema: TAKEN by Harbor ATIF, Inspect Scout and HF STS.
- Pooled dataset: PARTIAL; ADP pools trajectories but without the verification fields.
- Verification-field coverage table: NOVEL as far as searched, and the search was narrow.

**Update for the B5 acquisitions.** B7's matrix and hours cover only the B4 corpora. B7 explicitly left out "loaders for
B5 acquisitions ... ~2-4 h each" [B7 `hours_estimate/not_counted`].
- Reuse: 4 of the acquired native formats are already parsed by existing code (Claude Code JSONL via `lib/cc_jsonl.py`;
  Codex rollouts, OpenCode exports and Gemini-CLI chats via `load_swechat.py`). Their compatibility with these newer
  versions is untested.
- New loaders: 11 formats.
- Cost: 11 x 2-4 h = **22-44 h**. This extrapolates B7's judgement; it is not a measurement [CI `loaders`].

**Interpretation.** The acquired corpora declare MIT, Apache-2.0, CC BY 4.0, CC0, BSD-3-Clause or AGPL-3.0 licences. A
data release is therefore no longer limited to SWE-chat in principle, but none of them has had B7's per-corpus pass. Known
hazards:
- upstream OAuth tokens in TB2 (2.4);
- real-user prompts and repos in openhands-feedback (aggregates only, per B5a);
- usernames in Pi folder names (e.g. `cli-pi-hf/Becks723__pi-traces@70163ead/--Users-becks723--`);
- one AGPL-3.0 repo (cfahlgren1/Fable-5-traces) that shares 29 sessions with an MIT repo (5.0, 5.11);
- Trace Commons contents keep their contributors' own licences [B5d].

Before the freeze this changes nothing: T0 is still the only tier that fits.

---

## 5. Loader notes (one per downloaded corpus)

### 5.0 Conventions that apply to all of them

- **Bytes are evidence.** Never let git or the OS rewrite line endings. Global `core.autocrlf=true` silently converted
  48,185 TB2 files and 788 GLM files at checkout; B5b restored the exact bytes [B5b]. Result sizes feed N1, N3 and N5.
- **Read pinned data in place, read-only.** Never execute code shipped with data (`analyze_outputs.py` and
  `pages/*.py` in openhands-evaluation-outputs; `bulk_text.py` and similar are ours, under `analysis/out/phase_e/`).
  Skip `.cache/huggingface/`, `_b5*_manifest.json`, `_acquisition/`, `SOURCE.json`, `manifest.jsonl`.
- **What the timestamp means differs by corpus.** The IR (`analysis/lib/ir.py`) has `ts_kind` in {event, row_insert,
  shared_turn, none}. The acquired corpora need more values. Recommendation (not implemented):

  | Proposed `ts_kind` | Meaning | Corpora |
  |---|---|---|
  | `pre_action` | stamped before the action runs | OSWorld |
  | `step_window` | one start/end pair per step | browser-use |
  | `post_batch` | tool stamp taken after all calls of a step | mini-swe-agent (combo2 is mini-swe-agent-derived; its stamp semantics are unverified) |
  | `host_after_exec` | Terminus step stamp, minted on the host after the commands | ATIF Terminus family |
  | `call_and_result` | separate call and result stamps in one row | TraceLab |

  The `corpus` enum also needs the new names.
- **Dedupe before counting.**
  - Copies are common on the Hub (one claude-fable-5 capture sits in 24 repos [B5d]).
  - In our holdings, armand0e/claude-fable-5-claude-code (MIT) and cfahlgren1/Fable-5-traces (AGPL-3.0) share 29
    session ids and 2,576 request ids [CI `repo_pairs_with_any_overlap`].
  - Dedupe on (sessionId, uuid) for Claude Code and on session id elsewhere.
- **Ids that are not provider-minted:** treat `chatcmpl-<uuid>` from litellm, ids from the operator's vLLM, and capture
  proxy ids as harness- or operator-side, not provider-side.

### 5.1 terminal-bench-2-leaderboard [B5b]

**Root and layout.** Use `terminal-bench-2-leaderboard/hf_repo/` only. 1,766 byte-identical early copies sit under
`terminal-bench-2-leaderboard/submissions/`; ignore them. The layout is
`hf_repo/submissions/terminal-bench/2.0/<agent>__<model>/<job>/<task>__<trial>/`, holding:
- trial `result.json`;
- `exception.txt` (optional);
- `agent/trajectory.json` (ATIF), or native logs:
  - Claude Code: `agent/sessions/projects/-app/<uuid>.jsonl`;
  - Gemini-CLI: `agent/gemini-cli.trajectory.json`;
  - hookele: `agent/.hookele/traj.jsonl`;
- `agent/recording.cast` (3 submissions only).

**Trial `result.json`.**
- Phase windows: `started_at`/`finished_at` plus environment_setup / agent_setup / agent_execution / verifier windows
  (ISO us Z).
- `agent_result.n_input_tokens`, `n_output_tokens` and `cost_usd`.
- Terminus family: `agent_result.metadata.api_request_times_msec[]`, one wall time per LLM request (4,876 trials,
  146,857 values).
- `exception_info` (5,398 trials).
- `config.agent.kwargs/env`. This field may hold credentials (2.4), so drop it on load.

**ATIF `trajectory.json`** (schema v1.2 / v1.5 / v1.6).
- `steps[]` fields: step_id, timestamp, source, model_name, message, `tool_calls[{tool_call_id, function_name,
  arguments}]`, `observation.results[{source_call_id, content}]`, `metrics{prompt_tokens, completion_tokens,
  cached_tokens, cost_usd}`, extra.
- Join by `source_call_id`.
- The Terminus family puts all keystroke calls of a step against one terminal observation in the same step. Emit them
  as step-paired with no per-call join.
- Terminus mints the step timestamp on the host after the step's commands run (`host_after_exec`).
- Terminus waits a model-chosen `duration` per keystroke batch, so "execution time" is partly agent-controlled.
- 567 files have non-monotonic step timestamps (JJAgent 462, WozCode 105). Treat this as interleaving, not signal.

**Native Claude Code JSONL.** Same format as cc_local and swechat: reuse `lib/cc_jsonl.py`.
- `requestId` appears only in WozCode__Claude-Opus-4.6. ClaudeCode__GLM-4.7 and cchuter (local MiniMax) have 0.
- Large outputs were spilled to `tool-results/*.txt`, which were not downloaded, so the full text of those results is
  missing from our copy.

**Gemini-CLI.**
- `messages[{id, timestamp (ms Z), type, content, tokens, model, toolCalls[{id, name, args, result[{functionResponse{id,
  response{output}}}], status, timestamp}]}]`.
- Exit codes appear only as "Exit Code: N" text. This is close to swechat's gemini format (`parse_gemini`), but untested.

**hookele `traj.jsonl`.**
- Fields: `type` (start | llm_call | stream_summary | raw_response | tool_execution | ...), `ts` (ISO, 1 s), iteration,
  `response_id` (OpenAI `resp_`), usage, call_id, name, args, output.

**asciinema casts** (optional second clock). v2 header `{timestamp (unix s), ...}`, then `[rel_seconds, 'i'|'o',
data]`. Whether the recorder runs inside the sandbox is UNVERIFIED, so its trust level is open.

### 5.2 glm52-nf3-tb21-traces [B5b]

- Same Harbor layout as TB2: `hf_repo/traces/<task>__<id>/{result.json, config.json, agent/{trajectory.json (ATIF
  v1.7), recording.cast, terminus_2.pane}, verifier/*}`, plus `hf_repo/results_summary.json`.
- 2,106 of 3,237 observations join by `source_call_id`; the rest are step-paired.
- Self-hosted vLLM, so there are no provider ids.
- The README says the endpoint and API key were redacted.

### 5.3 openhands-evaluation-outputs [B5a]

**Files.** `outputs/SWE-bench_Lite-test/CodeActAgent/<run>/output.jsonl`, 19 runs, one JSON line per instance. Glob
exactly `output.jsonl`, not `*.part`.

**Line.** `instance_id, instruction, metadata{agent_class, llm_config (api_key masked), max_iterations}, history,
metrics{accumulated_cost, costs[]}, test_result.git_patch, report, error`.

**`history`** has two shapes. Detect the shape per line (is `history[0]` a list?), not from the run name: one run
named v1.9 is flat [SK `openhands_shapes.json`; B5a `census_oh_eval.json` per_run.history_format agrees].
- Flat event list, 9 runs: `{id, timestamp, source, message, action|observation, args|content+extras, cause,
  tool_call_metadata{function_name, tool_call_id, model_response{id, created, model, usage, choices},
  total_calls_in_response}}`. Eight of them (the v2.x runs and v0.15.0) carry `tool_call_metadata`. The ninth,
  `claude-3-5-sonnet-20241022_maxiter_30_N_v1.9-no-hint`, is flat and joins by `cause`, but has no `tool_call_metadata`.
- `[action, observation]` pairs with no `tool_call_metadata`: the other 10 v1.9 runs.

**Join.** `observation.cause == action.id` in the 9 flat runs; positional within the pair in the 10 pair runs. The
145,631/145,966 total in 1.3 mixes both.

**Timestamps.** Naive ISO-8601 with microseconds; UTC by inference. 312,115 of 318,298 events have a parseable
timestamp; the events without one are v1.9 null events.

**Fields.**
- `exit_code` sits only in the extras of `CmdRunObservation`.
- Truncation markers were measured in v2.x only.
- `model_response.id` is litellm `chatcmpl-<uuid>` for Anthropic runs, with `created` set locally (also `chatcmpl-`
  for the Gemini run via litellm_proxy, whose `created` setter is UNVERIFIED [B5a]). DeepSeek and Fireworks runs carry
  a bare UUID with a provider `created`.
- `outputs/webarena/` holds only a pointer README (to OpenHands/eval-output-webarena); it is not data.

### 5.4 openhands-feedback [B5a]

- One parquet file, `data/train-00000-of-00001.parquet`.
- Columns: version, feedback (positive/negative), permissions, `timestamp[us]`, and `trajectory[]` of {action, content,
  extras (JSON string), id, message, observation, source, timestamp[us]}.
- There is no `cause` column. Pair an observation to the action with id = its id - 1 when the echoed command matches
  (5,552/5,974 pair; 5,144/5,170 echoes match).
- These are real users' prompts and repos: report aggregates only.
- 53 LLM configs, including local ollama models.

### 5.5 miniswe-v2-qwen3-30b-swebv-tarsur385 [B5a]

**Files.** `trajectories/<instance_id>.traj.json` (499) plus `preds.json(l)` and `grading_report.json`.

**Traj.** `{info{model_stats, config, mini_version, exit_status, submission}, messages[], trajectory_format,
instance_id}`.

**Messages.**
- assistant: `{content, tool_calls[{id, function{name, arguments}}], extra{actions, response{id, created, usage},
  cost, timestamp}}`
- tool: `{content, tool_call_id, extra{raw_output, returncode, timestamp, exception_info}}`
- Join by `tool_call_id`.

**Timestamp semantics.**
- `extra.timestamp` is `time.time()`. The assistant stamp is taken after the response returns. The tool stamp is taken
  after the whole action batch runs (`post_batch`), so parallel calls share near-identical stamps.
- `response.created` comes from the local vLLM (a separate-process clock, not a provider clock).

**Unmatched calls.** The 223 calls without a result are the final submit of the 223 runs that ended Submitted.

### 5.6 sweagent-combo2-rl-rollouts [B5a]

- Files: `trajectories_00.tar.gz` (4,571 trajectories) and `group_info.tar.gz`.
- Stream the tar members and never extract: all 6 shards total about 34.8 GiB uncompressed.
- Member `<instance_id>_<sample_index>.json`: `instance_id, instance, messages[{role, content, timestamp (float s),
  tool_call_id?, extra{actions|returncode|synthetic}}], model_patch, n_steps, exit_status, prompt_token_ids,
  response_token_ids, loss_mask, env_creation_time`.
- Join: `tool_call_id` = harness-minted `call_<step>_<k>`.
- `extra.synthetic` marks results the harness wrote itself:
  - `combo_ground`: 4,361
  - `combo_empty_guard`: 164
  - `user:combo_valve`: 101 (user-role messages)
  - The first two counts are tool-role messages. The skeptic's full pass of shard 00 finds that each of those 4,525
    tool messages comes with a user-role message carrying the same flag (another 4,361 + 164). So 9,151 messages carry
    `extra.synthetic`, and a raw-text count gives twice the tool figure. Select `role == "tool"` when using these as
    labelled positives [SK `combo2_synthetic.json`].
- Synthetic results still arrive at least 0.0462 s after the call, so they are not zero-latency. The descriptive
  latency split is in [B5a].
- Token-id arrays dominate the bytes.

### 5.7 osworld_verified_trajs [B5c]

**Layout.** `<submission>/tasks/<domain>/<task_uuid>[__runN]/{traj.jsonl, runtime.log, result.txt, other json/log
files}`, plus `_meta/`, `manifest.jsonl` (sha256 + CRC32) and `SOURCE.json`. The top-level `_bulk_summary_*.json` is
download bookkeeping.

**`traj.jsonl`** has one row per executed action:
- `step_num`
- `action_timestamp`, as `%Y%m%d@%H%M%S` or `%Y%m%d@%H%M%S%f`. It is taken before `env.step` (`pre_action`) on the
  runner's local clock with no zone.
- `action`: a pyautogui string or a dict. Claude: `{name, input, id: toolu_..., ...}`. Muse Spark: `{call_id,
  function_name, function_output, ...}`.
- `response`, `reward` (always 0 during the episode), `done`, `info`.
- `screenshot_file`: the observation. The PNGs were not downloaded.

**Join and clock.** Join is positional; there are no result-arrival times. Step gaps are dominated by fixed sleeps:
`sleep_after_execution` in each run's `args.json` (3.0 s in klick, 0.0 s in Muse Spark, 10.0 s in a non-downloaded run)
and a 60 s pre-episode sleep in the stock runner. Subtract a per-run constant.

**`runtime.log` varies by agent:**
- Claude: `repr(BetaMessage)` with `msg_bdrk_` ids and usage.
- Muse Spark: function_call_output items.
- klick: DEBUG log with ms timestamps (348,970 lines, 13,006 per-LLM-call usage lines) plus `llm_call_log.jsonl`.

### 5.8 webarena_infinity_trajs [B5c]

**Files.** `data/gemini/<env>/<task>/{history.json, result.json}`, plus `data/manifest.json`. 134 of the 978 Gemini
manifest entries have no `history.json` at this revision.

**`history.json`.** `{history: [ {model_output{evaluation_previous_goal, memory, next_goal, action:[{<name>:{params}}]},
result:[{is_done, extracted_content, error?, ...}], state{url, title, tabs, interacted_element, screenshot_path},
metadata{step_start_time, step_end_time (epoch float), step_number, step_interval}} ]}`.

**Join and time.** `action[i]` maps to `result[i]` by position. A step that stops early has fewer results. There is one
start/end pair per step (`step_window`), covering LLM time plus execution, and no per-action stamps.

**Selection.** Successful trajectories only: there are no negatives here.

### 5.9 tracelab-uw [B5e]

**File.** One `v0.0.2/syfi_coding_trace.jsonl.gz`; stream it.

**Unit.** One row per LLM round, grouped by pseudonymous `session_id`. `provider` is claude or codex.

**Row fields.** Token columns (prefix/append/output; Claude cache split; Codex reasoning), `current_*_chars`, model,
`timing_events[{event_type, timestamp (ISO ms Z), content_chars}]`, `tools[]`.

**Tool fields.** `tool_call_id` (pseudonym), tool_name, `emitted_at`, `result_at`, `tool_wall_latency_ms`,
`tool_internal_latency_ms` (Codex 343,549; Claude 1,974), `result_chars`, `input_chars`, `is_error`,
`command_exit_code` (Codex 247,509), `command_skeleton`, executables.

**Limits.**
- No content and no provider ids, so content and id checks cannot run.
- Emit separate call and result events from `emitted_at` and `result_at` (`call_and_result`).
- B5e counted 5,381 Codex tools with wall < internal latency (seen data).

### 5.10 cli-trace-commons [B5e]

**Files.** `trace-commons__agent-traces@112ebd4d/sessions/**` holds 28 raw Claude Code session files, 1 OpenCode
export and 1 Cursor file. `data/train-00000-of-00001.parquet` is not just an index: its 30 rows carry a `trace` column
with full copies of the same sessions, so the same 7,503 request-id occurrences appear in both places. Read
`sessions/` or the parquet, never both [SK].

**Claude Code.** Reuse `lib/cc_jsonl.py`.
- Entry fields: `timestamp` (ISO ms Z), uuid/parentUuid, sessionId, `message.id`, `requestId`, `tool_use.id` ->
  `tool_result.tool_use_id`, `toolUseResult` structured copy, `message.usage`, `is_error`.
- 521 PowerShell tool calls appear.

**OpenCode file.** Reuse `parse_opencode`.

**Licence.** Contents keep their contributors' own licences.

### 5.11 cli-claude-code-hf [B5e]

**Layout.** 12 folders `<owner>__<repo>@<sha8>/` of raw Claude Code JSONL, some with subagent files. 379 JSONL files
hold 210 distinct session ids [CI `per_corpus`, SK]. victor's 53 files are a Claude Code-like export with no sessionId
and no requestId. Reuse `lib/cc_jsonl.py`.

**Request ids.**
- Absent in INONONO and victor; partial in AlinCiocan.
- Model strings include non-Claude names (`qwen-fable5`, `Mini-Fable-5`, `<synthetic>`), so check the model before
  trusting a `requestId` family. On the entries that actually carry a `requestId`, the model is a Claude name, except
  `<synthetic>` (146 entries, harness-written messages) and none (8 `system` entries) [SK]. Treat `<synthetic>` entries
  as harness records, not provider responses.
- 2 assistant entries in cfahlgren1 carry a `req_` value of 28 characters that does not fit the Anthropic layout.

**Parse issues.** 2 unparseable lines in crispwisp [CI].

**Duplicates.** armand0e and cfahlgren1 (AGPL) overlap (5.0).

### 5.12 cli-codex-hf [B5e]

- 6 folders of `rollout-<date>-<uuid>.jsonl`.
- Envelope `{timestamp (ISO ms Z), type: session_meta|turn_context|response_item|event_msg|compacted, payload}`.
- Join `payload.call_id` on `function_call`/`custom_tool_call` and their `*_output`.
- Tokens come from `event_msg/token_count`.
- Wall time and exit code appear only inside the output text wrapper ("Wall time: X seconds", "Process exited with
  code N").
- CLI versions 0.135.0-alpha.1 to 0.140.0-alpha.2 in the downloaded files, from codex_vscode, Codex Desktop and
  codex-tui.
- `load_swechat.parse_codex` handles this envelope; untested on these versions.

### 5.13 cli-pi-hf [B5e]

**Layout.** 23 folders. Session JSONL v3 sits under `sessions/` or under path-named folders. Some folder names embed
local usernames.

**Format.**
- Header `{type: session, version, id, timestamp, cwd}`.
- Entries `{type: message|model_change|thinking_level_change|compaction|..., id, parentId, timestamp (ISO ms)}`.
- `message.timestamp` is epoch ms.
- Assistant messages carry `provider, model, api, usage, stopReason, responseId` and toolCall blocks `{id, name,
  arguments}`.
- `toolResult{toolCallId, isError, details}`. Join by `toolCallId`.

**Response ids.** 11,741 assistant messages lack `responseId`. Families: `resp_` (OpenAI), `msg_` (Anthropic), `gen-`
(OpenRouter), `chatcmpl` (llama.cpp and others), UUID (DeepSeek).

**Parse issues.** One file in lucacorbucci fails JSON decoding. It is the 0-byte
`.agents/skills/hf-cli/.hf-skill-manifest.json`, not a session; the repo's session JSONL parses (184/184 lines) [SK].

**Non-session JSONL and duplicates** [SK `full_counts.json`].
- 544 JSONL files: 530 sessions plus 14 pi-share-hf redaction manifests (427 rows of `{file, redacted_hash,
  redaction_key, source_hash}`, no timestamp). Load only files whose first line is `{type: session}`.
- The 530 session files hold 522 distinct session ids. In julien-c__pi-sessions, 7 sessions also appear under
  `huggingface.js/` (6 byte-identical, 1 differing). One session id appears in both thomasmustier pi-extensions and
  pi-mono. The 8 extra files hold 248 tool calls. Dedupe on session id, keeping the longer file.
- In 4 repos (OmarRabhI, championswimmer, moikapy, woxQAQ) the sessions sit under `_upload_staging/`, beside a generated
  card that says `license: other`. The root card, which the Hub shows, says MIT or Apache-2.0.

### 5.14 agentcap-dacorvo [B5e], [CI `agentcap_join`]

**Traces.**
- `dacorvo__*-opencode-traces@*/data/<run_id>/...`: OpenCode export JSON `{info, messages[{info{id, role,
  time{created, completed}, providerID, modelID, tokens}, parts[...]}]}`.
  - Tool parts carry `callID` and `state{input, output, status, time{start, end} (epoch ms)}`. That is a
    harness-measured execution window.
  - 3,934 of 4,694 tool parts carry both callID and output.
- `dacorvo__*-pi-traces@*/data/<run_id>/...`: Pi JSONL as in 5.13.
- Models are local GGUF / GLM via a local server and HF-Router.

**Captures.** `dacorvo__*-captures@*/data/*.parquet` with columns `run_id, request_id (proxy UUID), model, captured_at
(epoch s), task_id, turn, request (JSON), response (JSON or raw SSE), served_by, served_build_info, served_model,
provider, upstream_url`.

**Join to traces.**
- All 31 capture run_ids name a trace folder; 18,885/18,885 capture rows match at folder level [CI].
- B5e's census reported 0 here because its counter looked only inside each capture repo (census_downloaded.py
  L270-275); that 0 is not evidence of a missing join.
- Per-call alignment (by turn and time) is untested.
- Two OpenCode trace files fail JSON decoding.

---

## 6. Decisions needing a human (consolidated)

Data and acquisition:
1. Approve the B5d priority-A downloads: Exgentic, AgentBRANE v14, MCPHunt (3,664.7 MB). There is 10.042 GB of
   headroom [CI].
2. Approve METR MALT (1.66 GB; gate already accepted).
3. Gated click-throughs: osworld2.0-trajectory (very large: pick a subset), z-lab/glm52-cc, and the others in 2.3.
4. Over-cap subsets: CooperBench coop, AgentLogs.
5. Licence requests: SWE-bench S3 trajectories, OpenHands Index archives, OpenHands WebArena outputs, nlile merged
   Claude Code traces.
6. SWE-chat v2 raw transcripts for a requestId audit (B4's open item).
7. Delete the duplicate `.part` (0.154 GB) and TB2 `hf_repo/.git` (1.070 GB).
8. Whether to notify the TB2 maintainers (OAuth tokens in 446 files), the sammshen owner (bearer token) and the
   thomasmustier/pine-of-glass-sessions uploader (an `sk-ant-api03-` value in one session file, found by the skeptic).
9. Whether AgentTrajectorySentinel (70.1 MB, licence "other": Apache-2.0 format, model outputs under Qwen/Llama/Gemini
   terms) is wanted as labelled tool-layer corruption despite having no absolute timestamps [B5d].

B6 (generation): H1 (extra usage off or $0 cap), H2 (tier; recommended P0 only), H3 (ToS/proxy). H4-H10 as in section 3.

B7 (release):
- tier (T0 now; T1 vs T2 later);
- accept ODC-BY 1.0 for the swechat shard;
- email policy;
- gate the HF repo or not;
- include split H or not;
- ask AI Digest for permission;
- whether the cc_local aggregate row may be public;
- approve a SWE-chat v2 sessions download to sync upstream removals;
- **new:** whether any acquired corpus enters the release (needs B7's per-corpus pass first).

---

## 7. Prior art touching this inventory (verdicts recorded by the sibling tasks)

This task did not re-open these sources. Each verdict, with its deciding citation, is in the named file.

| Claim | Closest work | Verdict | File |
|---|---|---|---|
| A benchmark harness or trace release already checks recorded tool results or timing from the log | SWE-bench `submit verify`; SWE-agent, mini-swe-agent, OpenHands; Harbor ATIF; OSWorld, AgentLab/BrowserGym, WebArena, AgentBench, browser-use, AgentRewardBench; agentir verify pass, TraceLab validators, Cline incident-traces | NOT TAKEN for timing, provider-id clocks and result content. The exception is Harbor ATIF's referential check (each `source_call_id` must be a tool call in the same step): B5b rates structural join checking PARTIAL/TAKEN as schema validation | [B5a], [B5b], [B5c], [B5e] |
| Provider request ids used as a clock in CLI-log tooling | ccusage Claude adapter | NOT TAKEN | [B5e] |
| Timing residuals over coding-agent traces (N1-adjacent) | TraceLab user_turn_gap_audit and its tool-overhead analysis | PARTIAL (adjacent; neither N1 sub-claim taken) | [B5e] |
| Nested timer: internal vs wall tool duration recorded together | Codex "Wall time" wrapper; Claude Code / Codex OTel; TraceLab | PARTIAL (inputs exist; no consistency check found) | [B5e] |
| Public corpus of raw provider responses joined to native harness traces | agentcap + dacorvo captures; sammshen/* | PARTIAL (open-weight and router case exists; no Anthropic request-id-header corpus) | [B5e], [B6] |
| Generating such a corpus by proxy capture on public benchmarks | sammshen/* | TAKEN (method) | [B6] |
| Capture tooling for raw Claude Code traffic | claude-trace; Claude Code OTel raw bodies | TAKEN | [B6] |
| Validating the undocumented id layout against HTTP Date and a proxy clock | none found | NOVEL (small; a validation step) | [B6] |
| Common normalized schema across harnesses | Harbor ATIF; Inspect Scout; HF STS-Format; SWE-chat table | TAKEN | [B7] |
| Pooled multi-source trajectory dataset | Agent Data Protocol (arXiv 2510.24702); Exgentic | PARTIAL | [B7] |
| Per-corpus verification-field coverage table (this document's 1.3) | ADP Table 2 (rounds, action mix, thought coverage) | NOVEL as far as searched (narrow search) | [B7] |

Dead ends in `CLAUDE_context_swarms.md` s7 were not cited or pursued.

---

## Files

- This document: `analysis/CORPUS_INVENTORY.md`.
- Derived numbers and registry: `analysis/out/phase_e/track_b/corpus_inventory.json`. Its composer is
  `analysis/out/phase_e/track_b/corpus_inventory/compose_inventory.py`. It reads the Track B JSONs (sha256 of each
  recorded under `inputs`) and, read-only, `C:\Swarms\data\acquired`.
- Catalog rows for the acquired corpora: `C:\Swarms\data\README.md`, section "acquired/" (appended 2026-10-04).
- Skeptic re-check: `analysis/out/phase_e/track_b/corpus_skeptic.json` (composer
  `corpus_skeptic/compose_skeptic.py`), with the raw outputs and scripts in `analysis/out/phase_e/track_b/corpus_skeptic/`.

---

## Skeptic changes

2026-10-04, corpus skeptic. Scope: the 14 corpora marked downloaded in 2.1. For each one the skeptic checked that the
files are on disk, that a licence is recorded and permits research use, and that the size is within the caps. It then
re-ran the field audit (timestamps and call/result join) with its own parsers and scanned every file for provider
request ids. Everything is in [SK] = `analysis/out/phase_e/track_b/corpus_skeptic.json` and `corpus_skeptic/*.json`.

**How the checks were made.** None of the scripts in `corpus_skeptic/` imports the B5 scripts,
`compose_inventory.py` or `analysis/lib`, so a parser bug shared with B5 could not make both audits agree. Sampling
was seeded (20261004). The counts are structural only, with no latency or gap statistics, so they use up no held-out
budget. Credential-like values were counted, never printed. Neither swechat H nor anything swarm-related was opened.

### Verification table

| Corpus | On disk | Licence (permits research use) | Size vs 5 GB cap | Field audit re-run (sample) | Request-id row |
|---|---|---|---|---|---|
| openhands-evaluation-outputs | yes, 19 runs | MIT, card + Hub API @aa897780 (yes) | 4.762 GB (incl. 0.154 GB `.part` duplicate, sha256-identical) | pass: events with ts 6,534/6,654; flat-run observations resolving by cause 2,002/2,012 (114 instances) | NO confirmed (0 ids in 4.61 GB) |
| openhands-feedback | yes | MIT (yes) | 0.114 GB | pass: tool actions with ts 820/828; tool observations paired to the id-1 action 780/823 (40 sessions) | NO confirmed |
| miniswe-v2-qwen3-30b-swebv-tarsur385 | yes, 499 | MIT, Hub API @58389eb5 (yes) | 0.224 GB | pass: all stamps present; joined 993/1,016 calls, the 23 unjoined = 23 Submitted runs (40 trajectories) | NO confirmed |
| sweagent-combo2-rl-rollouts | yes, 4,571 | MIT, Hub API @eaff5487 (yes) | 0.446 GB | pass: stamps 3,757 + 3,717 all float s; joined 3,717/3,757, 40 unjoined = final submits (40 trajectories) | NO confirmed (5.6 GB decompressed) |
| terminal-bench-2-leaderboard | yes | Apache-2.0, card at @572b2614 opened (yes) | 5.884 GB: **over cap**, 4.814 GB without `.git` | pass: ATIF steps with sub-second ts 1,670/1,670; results by id 703/1,296, step-paired 578; CC calls joined 367/368; Gemini 126/126; hookele 140/140 (1 s stamps) | YES confirmed: WozCode 12,327 entries / 7,272 distinct / 12,279 agree; 25 (not 22) submissions with logs |
| glm52-nf3-tb21-traces | yes | MIT, Hub API @6020a41c (yes) | 0.104 GB | pass: steps with ts 772/772; results by id 494/752 (20 files) | NO confirmed |
| osworld_verified_trajs | yes, 20 submissions | MIT, Hub API @5473c39e (yes) | 1.705 GB | **weak pass**: one pre-action stamp per row 1,762/1,762, sub-second 523/1,762; positional join only (80 files) | NO confirmed |
| webarena_infinity_trajs | yes, 844 | MIT, Hub API @73cf7f57 (yes) | 0.104 GB | **weak pass**: step start/end 441/441; action and result counts match in 430/441 steps (40 files) | NO confirmed |
| tracelab-uw | yes | CC BY 4.0 data, LICENSE-DATASET.md @11b8b14c opened (yes; asks users not to re-identify) | 0.101 GB | pass, full pass: 8,058 sessions; 743,819 tools; both stamps 304,290 + 438,760 | NO confirmed |
| cli-trace-commons | yes | CC BY 4.0 compilation, Hub API @112ebd4d (yes; contents keep their own licences) | 0.127 GB | pass, all files: entries with ms ts 12,174/12,174; joined 4,262/4,264 | YES confirmed: 7,496/7,499; 4,349 distinct; 7,496 agree |
| cli-claude-code-hf | yes, 12 repos | MIT x5, Apache-2.0 x3, CC BY 4.0 x2, CC0 x1, AGPL-3.0 x1 (Hub API @0ba6f538) (yes) | 0.244 GB | pass, full pass: 39,686/39,686 ts; joined 12,994/12,997 | YES confirmed: 21,577/24,425; 7,660 distinct; 21,567 agree |
| cli-codex-hf | yes, 6 repos | CC BY 4.0 x3, MIT x3 (yes) | 0.073 GB | pass, all files: 17,617/17,617 ts; joined 3,381/3,381 | NO confirmed |
| cli-pi-hf | yes, 23 repos | MIT x17, Apache-2.0 x4, CC BY 4.0, BSD-3-Clause (Hub API @046e1aff) (yes) | 0.211 GB | pass, full pass: joined 23,927/23,974 (doc 23,928); epoch-ms 50,107/50,107 | NO confirmed: 31 Anthropic-layout ids occur, all inside text or error bodies |
| agentcap-dacorvo | yes, 9 repos | Apache-2.0 x9 (yes) | 0.858 GB | pass, full pass: OpenCode parts with callID and output 3,934/4,694, start/end 4,685; Pi joined 6,804/6,805; capture rows matching a trace folder 18,885/18,885 | NO confirmed: 18,885/18,885 capture ids are 32-hex proxy ids; `captured_at` is whole seconds |

Totals: 14/14 directories present; 14,957,562,193 B = 14.958 GB (13.93 GiB) against the 25 GB cap. Every licence
permits research use. Only TB2 exceeds the per-corpus cap, and only through its 1,070,068,963 B `.git`. 12 corpora
pass the field audit and 2 pass weakly. The three YES rows reproduce entry for entry. The full scan finds no
Anthropic-layout id in any harness field of the 11 NO corpora.

### Corrections made in place above

1. **TB2 denominator** (0, 1.1). It was "1 of 75 submissions" with "53 submissions without ATIF or native structured
   logs". It is now 25 submissions with structured logs (21 ATIF; native-only ClaudeCode__GLM-4.7, cchuter, Gemini-CLI
   Flash, hookele) and 50 without. The request-id carrier is 1 of 25.
2. **TB2 ATIF request-id scan** (1.1). CI's regex needs an unescaped closing quote, so it misses ids inside escaped
   JSON. The strict scan finds 6 Anthropic-layout ids in Meta-Harness, Terminus-KIRA and JJAgent files, all in
   observation content or message text. The conclusion is unchanged: no ATIF harness field carries request ids.
3. **Evidence status of the request-id column** (1.1). Nothing under `analysis/out/phase_e/track_b/` is committed. The
   B4 rows agree with committed build and Phase C files. The B5 rows were re-derived from the data.
4. **cli-claude-code-hf file count** (1.3, 5.11). 377 -> 379 JSONL files, matching CI's own `per_corpus`. Also: which
   models carry requestId, the `<synthetic>` caveat and 2 non-layout values.
5. **cli-pi-hf** (1.3, 5.13). 530 session files hold 522 distinct sessions; the 8 duplicate files hold 248 calls. 14
   non-session manifest files exist. The "fails JSON decoding" file is an empty skill manifest, not a session. The
   `_upload_staging` cards say "other".
6. **OpenHands eval run shapes** (5.3). "v2.x 8 flat / v1.9 11 pairs" -> 9 flat / 10 pairs.
   `claude-3-5-sonnet-20241022_maxiter_30_N_v1.9-no-hint` is flat with no `tool_call_metadata`, so detect the shape per
   line. B5a's own `census_oh_eval.json` already showed 9/10; the prose was wrong. `outputs/webarena/` is a pointer
   README.
7. **cli-trace-commons `data/`** (5.10). It is a full copy of the sessions (`trace` column), not an index.
8. **combo2 synthetic flags** (5.6). The 4,525 tool-role flags are confirmed. Each comes with a user-role message
   carrying the same flag, so 9,151 messages are flagged in all.
9. **Hygiene** (2.4, 6). Added the `sk-ant-api03-` value in one cli-pi-hf session file, not printed, and the benign
   `.incomplete` markers.
10. **Bottom line 3** (0). Added the re-run result: 14/14 pass, 2 weakly.

### Checked and confirmed, no change

- Byte counts per directory and in total; the TB2 `.git` orphan pack (476,164,092 B with its idx and rev).
- The 1,766 TB2 early copies (byte-identical to `hf_repo/`, 7.5 MB) and the OpenHands `.part` duplicate.
- 446 TB2 files with an `sk-ant-` value, all in pilot-real__claude-opus-4-6.
- OSWorld Claude runs: 0 `req_` ids (Bedrock).
- The agentcap capture-to-trace join: 31/31 run ids.
- TraceLab population counts.
- cli-codex-hf counts.
- Licence values on every on-disk card. Eleven were spot-checked against the Hub API or the upstream file at the pinned
  revision. The TB2 Hub API response was too large to fetch; its README at the pinned revision was read instead.

### Caveats the skeptic adds, not corrections

- TB2 ATIF "metrics on 253,556 steps" means a metrics object is present. In the sample, 1,007 of the 1,038 steps that
  have metrics show non-zero tokens.
- One hookele trajectory names model `gpt-5.1-codex-max` under a submission folder called `gpt5.1-codex-mini`. This
  was seen once and not counted.
- The 145,631/145,966 OpenHands join mixes the `cause` join (flat runs) with positional pairing (pair runs).
- OSWorld and WebArena-Infinity carry no result-arrival time. N1 and N3 cannot use them without a per-run model of
  fixed sleeps or step windows.
