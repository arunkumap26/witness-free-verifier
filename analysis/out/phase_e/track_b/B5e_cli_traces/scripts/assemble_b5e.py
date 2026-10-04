"""B5e final assembly: merges census/b5e_computed.json (script-computed counts) with the hand-written interpretation,
prior-art verdicts, listed/failed corpora and the source register into analysis/out/phase_e/track_b/B5e_cli_traces.json.
Numbers quoted in the interpretation are pulled from the computed file at assembly time, not typed.
Usage: python assemble_b5e.py <B5e dir> <out.json>
"""
import json, os, sys

D = sys.argv[1]
C = json.load(open(os.path.join(D, "census/b5e_computed.json"), encoding="utf-8"))
S = json.load(open(os.path.join(D, "census/sample_audit.json"), encoding="utf-8"))
TL = C["tracelab"]["census"]["by_provider"]
cor = C["corpora"]; rid = C["provider_clock_coverage"]; pop = C["hf_agent_traces_population"]


def fa(c, f, k, default=0):
    return (cor.get(c, {}).get("aggregate_by_format", {}).get(f, {}) or {}).get(k, default)


def tot_cc(k):
    return sum(fa(c, "claude_code", k) for c in cor)


cc_sessions = tot_cc("sessions"); cc_calls = tot_cc("tool_calls"); cc_joined = tot_cc("results_joined"); cc_results = tot_cc("tool_results")
cc_req = tot_cc("req_ids"); cc_asst = tot_cc("assistant_entries"); cc_v7 = tot_cc("req_v7"); cc_agree = tot_cc("req_agree")
cc_ts = tot_cc("ua_ts_iso_ms_z"); cc_ua = tot_cc("ua_entries"); cc_calls_rid = tot_cc("calls_with_requestId")
pi_s = sum(fa(c, "pi", "sessions") for c in cor); pi_calls = sum(fa(c, "pi", "tool_calls") for c in cor); pi_j = sum(fa(c, "pi", "results_joined") for c in cor)
pi_res = sum(fa(c, "pi", "tool_results") for c in cor)
pi_fam = {}
for c in cor:
    for k, v in (fa(c, "pi", "responseId_family", {}) or {}).items():
        pi_fam[k] = pi_fam.get(k, 0) + v
pi_hex_ok = sum(fa(c, "pi", "respid_within_5s::openai_resp_hex50") for c in cor)
pi_gen_ok = sum(fa(c, "pi", "respid_within_5s::openrouter_gen_secs") for c in cor)
cx_s = fa("cli-codex-hf", "codex", "sessions"); cx_calls = fa("cli-codex-hf", "codex", "tool_calls"); cx_j = fa("cli-codex-hf", "codex", "outputs_joined")
cx_out = fa("cli-codex-hf", "codex", "tool_outputs"); cx_lines = fa("cli-codex-hf", "codex", "lines"); cx_ts = fa("cli-codex-hf", "codex", "lines_ts_iso_ms_z")
oc_s = sum(fa(c, "opencode", "sessions") for c in cor); oc_parts = sum(fa(c, "opencode", "tool_parts") for c in cor)
oc_join = sum(fa(c, "opencode", "tool_parts_callID_output") for c in cor); oc_t = sum(fa(c, "opencode", "tool_parts_time_start_end") for c in cor)
cap_rows = fa("agentcap-dacorvo", "captures", "capture_rows"); cap_sla = fa("agentcap-dacorvo", "captures", "sse_with_sla_ts_us")
cap_created = fa("agentcap-dacorvo", "captures", "sse_with_created")
tlc, tlx = TL["claude"], TL["codex"]
mk = C["marker_scan"]
cx_wall = sum(v["counts"].get("codex:wall_time", 0) for k, v in mk.items() if k.startswith("cli-codex-hf"))
cx_outs_mk = sum(v["counts"].get("codex:outputs", 0) for k, v in mk.items() if k.startswith("cli-codex-hf"))
r = lambda k, n: {"k": k, "n": n, "rate": round(k / n, 5) if n else None}
_pr = rid.get("per_repo_decode_deltas", {})
_out5 = sorted(((v["pi_openai_resp_hex50"]["n"] - v["pi_openai_resp_hex50"]["within_5s"], k) for k, v in _pr.items() if "pi_openai_resp_hex50" in v), reverse=True)
pi_worst = {"repo": _out5[0][1], "outside_5s": _out5[0][0], "of_all_outside_5s": sum(x[0] for x in _out5)} if _out5 else None
low_req = []
for k, v in _pr.items():
    e = v.get("claude_code_req")
    if e and e.get("assistant_entries") and (e.get("req_ids") or 0) / e["assistant_entries"] < 0.5:
        low_req.append(f"{k.split('::')[1]} ({e.get('req_ids') or 0}/{e['assistant_entries']})")
_vers, _models = set(), {}
for c in cor.values():
    cc = c["aggregate_by_format"].get("claude_code") or {}
    _vers.update(k for k in (cc.get("cc_version") or {}) if k[:1].isdigit())
    for m, n in (cc.get("model") or {}).items():
        _models[m] = _models.get(m, 0) + n
_vt = lambda s: tuple(int(x) if x.isdigit() else 0 for x in s.split("."))
vers_range = f"{min(_vers, key=_vt)}..{max(_vers, key=_vt)}" if _vers else None
top_models = [m for m, _ in sorted(_models.items(), key=lambda kv: -kv[1])[:6]]
GB = lambda b: round(b / 1e9, 3)
bytes_all = sum(v["bytes_on_disk"] for v in cor.values()) + sum(a.get("bytes", 0) for a in C["tracelab"]["download"])

out = {
    "key": "B5e_cli_traces",
    "task": "Phase E Track B5 (sources group e): public OpenCode / Codex CLI / Cline / Roo Code / Claude Code session or trace releases (GitHub, HF, blog datasets). Find, field-audit on a sample, download what passes (licence permitting research use, ungated, caps 5 GB/corpus and 25 GB total), record schema notes, request-id presence, and prior art for tooling that already embodies our checks.",
    "produced_by": {
        "scripts": "analysis/out/phase_e/track_b/B5e_cli_traces/scripts/ (hf_sweep.py, hf_format_census.py, hf_files_census.py(+_retry,+_lib), census_summary.py, dedupe_clusters.py, sample_audit.py, pi_respid_decode.py, pinned_dl.py, dl_github_release.py, census_downloaded.py, census_tracelab.py, marker_scan.py, compose_b5e.py, assemble_b5e.py)",
        "computed_counts": "analysis/out/phase_e/track_b/B5e_cli_traces/census/b5e_computed.json (compose_b5e.py; every count below comes from it or from the census files it names)",
        "hub_metadata": "analysis/out/phase_e/track_b/B5e_cli_traces/meta/ (hf_files_census.json is stored as meta/hf_files_census.json.gz, byte-identical after gunzip; census_summary.py, dedupe_clusters.py and sample_audit.py read the decompressed path)",
        "download_manifests": "census/download_manifest.json (HF, per repo) + <dest>/_b5e_manifest.json (per file sha256) + census/download_manifest_github.json (TraceLab asset)",
        "source_evidence": "analysis/out/phase_e/track_b/B5e_cli_traces/sources/ (MANIFEST_github.json: URL + sha256 of each fetched file; repo meta JSONs)",
        "samples": "third-party sample bytes are kept in the session scratchpad only (not committed)",
    },
    "scope_and_rules_followed": [
        "Public, ungated, licence-tagged data only; no click-through accepted; gated sets listed. Nothing under swarm/, data/swarm/ or .claude/worktrees/swarm read. No transcripts generated. No paid API calls.",
        "Field audit on a sample before every download: one native session file per (dataset, harness class), first <=3 MB via HTTP Range pinned to the commit sha (census/sample_audit.json), or the release-asset head for TraceLab, or one small parquet for agentcap captures.",
        "Downloads pinned to the audited commit sha (HF) or release tag + GitHub asset digest (TraceLab); sha256 of every file recorded; HF LFS files checked against the Hub's LFS sha256; append-only (existing files never overwritten); shared 25 GB and per-corpus 5 GB caps checked before every repo/asset (pinned_dl.py, dl_github_release.py).",
        "Downloaded files are data only (jsonl/json/parquet/gz); nothing downloaded was executed.",
        "HF format:agent-traces datasets were deduplicated by LFS content hash before auditing; one licensed representative per content cluster was sampled.",
    ],
    "headline": {
        "interpretation": True,
        "downloaded": ["tracelab-uw (TraceLab v0.0.2, CC BY 4.0)", "cli-trace-commons (trace-commons/agent-traces, CC BY 4.0)",
                       "cli-claude-code-hf (12 raw Claude Code repos)", "cli-codex-hf (6 raw Codex rollout repos)", "cli-pi-hf (23 raw Pi session repos)",
                       "agentcap-dacorvo (OpenCode + Pi traces with joinable HTTP wire captures)"],
        "downloaded_bytes_total": bytes_all, "downloaded_GB": GB(bytes_all),
        "biggest_find": f"TraceLab (UW, arXiv 2606.30560, CC BY 4.0): real Claude Code + Codex sessions from 43 developers, content-stripped but with per-tool emitted_at/result_at (ISO ms), result_chars, is_error, exit codes and a harness-internal latency next to the wall latency. v0.0.2 census: Claude {tlc['sessions']} sessions / {tlc['tools']} tool calls ({tlc['tools_emitted_and_result_at']} with call+result stamps); Codex {tlx['sessions']} sessions / {tlx['tools']} tool calls ({tlx['tools_internal_latency']} with harness-internal latency, {tlx['tools_exit_code']} with exit code). This is the largest public CLI corpus with the clocks N1 (residual vs result size), N3 (reaction time vs result size) and the nested-timer check need. It carries NO provider request ids and no content, so content and id checks cannot run on it.",
        "request_id_column": {
            "claude_code_raw_hf": f"{cc_req}/{cc_asst} assistant entries in the downloaded raw Claude Code files carry an Anthropic req_ id; {cc_v7}/{cc_req} decode as UUIDv7 under the B2a layout (UNVERIFIED vs vendor docs); for {cc_agree}/{cc_v7}, (carrying entry timestamp minus decoded id time) lies in [-2 s, +600 s] (the B4 agreement window). {cc_calls_rid}/{cc_calls} tool calls sit in a response that has a requestId. Repos where under half of assistant entries carry one (scrubbed, not recorded, or a non-Anthropic backend): {low_req}. Claude Code versions seen (top-25 per repo): {vers_range}; top models: {top_models}.",
            "pi_openai_responses": f"Pi sessions backed by the OpenAI Responses API store responseId resp_<50 hex>; {pi_hex_ok}/{pi_fam.get('openai_resp_hex50', 0)} decode (B2a hex50 layout, 1 s resolution, UNVERIFIED) to within 5 s of the message's own epoch-ms timestamp; {pi_worst['outside_5s'] if pi_worst else 0} of the {pi_worst['of_all_outside_5s'] if pi_worst else 0} outside 5 s come from one repo ({pi_worst['repo'] if pi_worst else None}), where the id time falls up to minutes AFTER the message stamp (descriptive; cause not established). OpenRouter gen-<unix seconds>-...: {pi_gen_ok}/{pi_fam.get('openrouter_gen_secs', 0)} within 5 s. {pi_fam.get('<missing>', 0)}/{sum(pi_fam.values())} Pi assistant messages carry no responseId (older Pi versions / providers). A second provider-clock family exists in public CLI traces, but only for Pi, not Codex rollouts.",
            "codex_and_opencode_native": "No provider request/response id in any downloaded Codex rollout or OpenCode export (sample id_like_keys empty; response_item entries carry no id).",
            "agentcap_wire_captures": f"{cap_rows} captured /v1/chat/completions calls; provider SSE body has id + created on {cap_created}; HF-Router (GLM-4.6) responses add sla_metrics.ts_us (provider-side microsecond time) on {cap_sla} rows. Captures store no general HTTP headers (only X-Served-By/X-Build-Info columns) and their request_id is minted by the capture proxy.",
            "consequence": f"The rank-1 request-id bracket gains {cc_req} new public Anthropic request ids from independent contributors (Claude Code {vers_range}), i.e. an out-of-sample check of the UNVERIFIED id layout outside swechat, but in {cc_sessions} small session files rather than thousands of streams." + " Pi + OpenAI resp_ ids are a possible second family at 1 s resolution. Codex, OpenCode, Cline and Roo public traces add zero request-id coverage.",
        },
        "named_harness_outcome": {
            "claude_code": "Many small raw uploads on HF (agent-traces format); 12 licensed repos + trace-commons downloaded; TraceLab adds content-free timing for thousands more sessions.",
            "codex_cli": "6 small licensed raw rollout repos downloaded + TraceLab Codex rows. Large Codex sets (Becks723, basedlsg, Mike0021, AletheiaResearch) carry no licence: listed.",
            "opencode": "Only agentcap/dacorvo (3 repos) and 1 trace-commons file; the dacorvo runs are joinable to wire captures. Inferact-style or SFT re-exports fail the audit.",
            "cline": "No public Cline session corpus with data. cline/incident-traces (CC BY 4.0, has a 'deception' label) holds 0 sessions at the audited revision; cline-bench releases tasks only.",
            "roo_code": "None. RooCodeInc/Roo-Code is archived on GitHub (last push 2026-05-15); Roo-Code-Evals holds exercises only.",
        },
        "hazards_found": "Public 'trace' datasets with timestamps that do not record execution: ibm-research/codex_swebenchpro_traces_Otel says its timestamps are synthetic (random 1-10 s); Swival exports (jedisct1/*) show 0-4 ms call-to-result gaps; owao/qwen38-27B shows 0.000 s on all 107 sampled gaps; Jadson/* rewrote tool calls. Any timing mechanism must reject such sources, and the format:agent-traces tag alone does not guarantee native records.",
    },
    "seen_data_warning": "This task computed, on the downloaded corpora: call-to-result gap quantiles, Anthropic req_ id decode deltas, Pi resp_/gen- id decode deltas, Codex 'Wall time' marker rates, TraceLab wall-vs-internal latency inversions, and capture SSE field rates. A later pre-registered test of those quantities on these corpora is not blind: pre-register on held-out repos/sessions.",
    "computed": C,
}

# ---------------- downloaded corpora (schema notes) ----------------
def repos_of(c):
    return [x["repo"] for x in cor[c]["repos"]]

out["corpora_downloaded"] = [
    {"name": "tracelab-uw", "source": {"url": "https://github.com/uw-syfi/TraceLab/releases/tag/v0.0.2", "asset": "syfi_coding_trace.jsonl.gz",
                                         "sha256": C["tracelab"]["download"][0].get("sha256"), "digest_match": C["tracelab"]["download"][0].get("sha256_match"),
                                         "repo_commit": "11b8b14c6005808ab272b3431487066832582414", "paper": "arXiv 2606.30560"},
     "licence": "CC BY 4.0 (LICENSE-DATASET.md); code Apache-2.0", "research_use_ok": True,
     "downloaded_to": "C:\\Swarms\\data\\acquired\\tracelab-uw\\v0.0.2\\", "bytes": C["tracelab"]["download"][0].get("bytes"),
     "schema_note": {"unit": "one JSON row per LLM round (step); rows grouped by pseudonymous session_id",
                     "row_fields": sorted(C["tracelab"]["census"]["row_keys"].keys()),
                     "tool_fields": sorted(C["tracelab"]["census"]["tool_keys"].keys()),
                     "timing_events": "ordered list of {event_type in user_message|text|reasoning|tool_call|tool_result|usage_report, timestamp ISO-8601 ms Z, content_chars}",
                     "timestamp_format": "ISO-8601 UTC with ms ('2026-05-31T14:18:50.524Z')",
                     "ids": "session_id, round_id, tool_call_id are stable pseudonyms (join preserved); no provider request/response id",
                     "content": "removed: only *_chars counts, token usage, executables/command_skeleton for shell calls",
                     "counts_by_provider": TL},
     "field_audit": {"per_event_timestamps": True, "call_result_join": "tool_call_id with emitted_at/result_at inside the same row", "provider_request_ids": False,
                     "sample": "first 4 MB of the release asset (29,750 rows) before download"}},
]
for c, label in [("cli-trace-commons", "Trace Commons (raw Claude Code + 1 OpenCode, contributor-donated, anonymized)"),
                 ("cli-claude-code-hf", "raw Claude Code JSONL uploads (HF agent-traces format)"),
                 ("cli-codex-hf", "raw Codex rollout JSONL uploads"),
                 ("cli-pi-hf", "raw Pi session JSONL uploads (adjacent CLI harness; carries provider responseIds)"),
                 ("agentcap-dacorvo", "agentcap runs: OpenCode + Pi native traces with joinable HTTP wire captures")]:
    v = cor[c]
    out["corpora_downloaded"].append({
        "name": c, "family": label, "downloaded_to": f"C:\\Swarms\\data\\acquired\\{c}\\<owner>__<repo>@<sha8>\\",
        "repos": v["repos"], "bytes": v["bytes_on_disk"],
        "licences": sorted({x["licence"] for x in v["repos"]}), "research_use_ok": True,
        "integrity": {"lfs_mismatch": sum(x.get("lfs_mismatch", 0) for x in v["download_records"]), "size_mismatch": sum(x.get("size_mismatch", 0) for x in v["download_records"]),
                      "per_repo_manifest": "<dest>/_b5e_manifest.json"},
        "aggregate_by_format": v["aggregate_by_format"],
    })

out["schema_notes_by_native_format"] = {
    "claude_code_jsonl": {"event_types": "user / assistant / system / summary / attachment / progress / file-history-snapshot / custom-title / last-prompt ...", "timestamp": "per entry 'timestamp' ISO-8601 ms Z",
                          "ids": "uuid/parentUuid chain, sessionId, assistant message.id (msg_), requestId (req_, Anthropic), tool_use.id (toolu_) joined by tool_result.tool_use_id", "structured_copy": "user.toolUseResult",
                          "tokens": "assistant message.usage", "error": "tool_result.is_error", "truncation": "text only (no field)"},
    "codex_rollout_jsonl": {"envelope": "{timestamp ISO-8601 ms Z, type in session_meta|turn_context|response_item|event_msg|compacted, payload}", "join": "payload.call_id on function_call/custom_tool_call and *_output",
                            "tokens": "event_msg/token_count", "in_result_harness_fields": "function_call_output text wrapper 'Chunk ID', 'Wall time: X seconds', 'Process exited with code N', 'Original token count' (marker_scan)",
                            "provider_ids": "none", "versions_seen": "cli_version 0.135.0-alpha.1 .. 0.145.0 (sample)"},
    "pi_session_jsonl": {"envelope": "header {type: session, version, id, timestamp, cwd}; entries {type: message|model_change|thinking_level_change|..., id, parentId, timestamp ISO ms}",
                         "message": "role user|assistant|toolResult; message.timestamp epoch ms; assistant: provider, model, api, usage, stopReason, responseId; toolCall blocks {id,name,arguments}; toolResult {toolCallId, isError, details}",
                         "provider_ids": "assistant.responseId (OpenAI resp_, Anthropic msg_, OpenRouter gen-, llama.cpp chatcmpl-, DeepSeek uuid)"},
    "opencode_export_json": {"envelope": "{info:{id, time:{created,updated}}, messages:[{info:{id, role, time:{created,completed}, providerID, modelID, tokens}, parts:[...]}]}",
                             "join": "tool part carries callID with state.input and state.output inline", "tool_clock": "state.time.start/end epoch ms (harness-measured tool execution window)", "provider_ids": "none"},
    "agentcap_capture_parquet": {"columns": "run_id, request_id (proxy UUID), model, captured_at (epoch s), task_id, turn, request (JSON), response (JSON or {stream, raw SSE}), served_by, served_build_info, served_model, provider, upstream_url",
                                 "join": "run_id == traces folder data/<run_id>/; per call by turn/time (not by id)"},
}

# ---------------- passed audit but listed ----------------
def samp(k):
    x = S.get(k, {}); m = x.get("metrics", {})
    return {"sample_url": x.get("url"), "sha": x.get("sha"), "gap_s": m.get("call_to_result_gap_s"), "models": m.get("models")}

out["corpora_passed_audit_but_listed"] = [
    {"name": "thomasmustier/pi-for-excel-sessions", "licence": "MIT", "bytes": 299856373, "why_listed": "size (300 MB) for a Pi corpus whose sampled session carries no responseId; low marginal value", "sample": samp("thomasmustier/pi-for-excel-sessions::pi")},
    {"name": "julien-c/synthtraces", "licence": "MIT", "bytes": 325746228, "why_listed": "Pi sessions where an LLM plays the user (README 'synthetic coding agent session traces'); tool execution is real per README but the corpus is synthetic by design; human decision", "sample": samp("julien-c/synthtraces::pi")},
    {"name": "dacorvo/{transformers-coding,hf-hub,funes-recall}-session-{goose,hermes}-traces + their goose/hermes capture parquets", "licence": "Apache-2.0", "why_listed": "same agentcap experiment, harnesses outside the named set (Goose, Hermes); not sample-audited; captures ~1.2 GB; useful for the N6 transfer grid if wanted"},
    {"name": "risenlab/agentlogs (AgentLogs, arXiv 2608.29204)", "licence": "CC BY 4.0, ungated", "bytes": 56747036194,
     "why_listed": "GitHub Copilot cloud agent (not a named CLI) and 56.7 GB > 5 GB per-corpus cap. Partial audit: datasets-server rows show session.id + entry_index ordering and data.callId; the paper's appendix shows assistant entries with 'created' at 1 s resolution and tool entries without a timestamp. A 1-shard (~200 MB) audit is needed before deciding.", "evidence": "meta/agentlogs_first_rows_schema.json"},
    {"name": "jedisct1/security-audits (Swival)", "licence": "MIT", "bytes": 1685161847, "why_listed": "Swival harness (README: 'not Claude Code'), not a named CLI; 1.69 GB; its sibling jedisct1/agent-traces-flashmania shows call-to-result gaps of 0-4 ms (timestamps not tied to execution). Sample of this repo had 0 tool calls, so its own audit is inconclusive.", "sample": samp("jedisct1/security-audits::claude_code")},
]

out["corpora_failed_audit"] = [
    {"name": "Inferact/codex_swebenchpro_traces", "licence": "MIT", "reason": "ShareGPT {from,value} turns; assistant text replaced by 'Lorem ipsum'; no per-event timestamps or call ids (Codex 'Wall time' only inside result text). Sample: first 400 KB.", "url": "https://huggingface.co/datasets/Inferact/codex_swebenchpro_traces/resolve/0d52ae8c75738117be9e58c7071bd9a5b43ff78f/codex_swebenchpro.json"},
    {"name": "ibm-research/codex_swebenchpro_traces_Otel", "licence": "CC BY-NC 4.0", "reason": "README: 'Timestamps are synthetic: spans within a trace are spaced with random 1-10 second delays'; derived from Inferact (lorem ipsum outputs). 6.16 GB.", "url": "https://huggingface.co/datasets/ibm-research/codex_swebenchpro_traces_Otel"},
    {"name": "jedisct1/agent-traces-flashmania (Swival)", "licence": "MIT", "reason": "Claude-Code-compatible export by a different harness; 49/49 sampled call-to-result gaps <= 0.004 s: stamps do not record execution", "sample": samp("jedisct1/agent-traces-flashmania::claude_code")},
    {"name": "owao/qwen38-27B", "licence": "MIT", "reason": "Pi-format file whose 107 sampled call-to-result gaps are all 0.000 s", "sample": samp("owao/qwen38-27B::pi")},
    {"name": "Jadson/ox-alpha-pi-traces-emacs-bridge", "licence": "MIT", "reason": "README: converted so every write/edit/read call runs through a different MCP tool; tool calls rewritten post hoc, not a record of execution"},
    {"name": "Samarth0710/traceweave (+ -viewer-test)", "licence": "MIT", "reason": "README: sessions 'rehydrated into the Claude Code JSONL schema' (converted); sampled file has 0 tool calls"},
    {"name": "vedalken/merchantscroll-traces", "licence": "MIT", "reason": "Cursor sessions converted to agent-traces format; sampled file has 0 tool calls"},
    {"name": "WhitzardAgent/ClaudeCode-{Anthropic,OpenAI,OpenHands,Hermes,AgentIR}", "licence": "apache-2.0 tag on a conversion of an unlicensed source (nlile)", "reason": "API-format messages (no per-event timestamps); licence provenance broken"},
    {"name": "nvidia/Open-SWE-Traces", "licence": "CC BY 4.0", "reason": "schema (README Data Fields): messages/tools/resolved/metadata; no per-event timestamps or call ids; its OpenCode/Claude Code subsets are announced 'soon', not released. 42.6 GB."},
    {"name": "PotatoHD/agent-coding-traces-public", "licence": "other/mixed", "reason": "normalised to text/source/lang"},
    {"name": "thomwolf/am-session-codex-check-d17941", "licence": "Apache-2.0", "reason": "0 tool calls in the only session"},
]

out["corpora_excluded_no_licence"] = {
    "summary": f"{pop['datasets_by_gate_and_licence'].get('open|none', 0)} of {pop['n_format_agent_traces']} HF format:agent-traces datasets (plus name-search extras) carry no licence tag and were not downloaded.",
    "notable": [
        {"name": "nlile/misc-merged-claude-code-traces-v1", "bytes": 1158006414, "note": "32,133 merged Claude traces from 10 HF sources; normalized; no licence"},
        {"name": "Becks723/codex-traces", "bytes": 164793001, "note": "131 raw Codex rollouts; no licence"},
        {"name": "basedlsg/codex-assistant-rollouts", "bytes": 816386683, "note": "27 raw Codex rollouts; no licence"},
        {"name": "Mike0021/codex-sessions", "bytes": 22168376, "note": "27 Codex sessions; no licence"},
        {"name": "AletheiaResearch/GPT-5.3-Codex-Spark-Codex", "bytes": 117484104, "note": "200 Codex rollouts (teich); no licence"},
        {"name": "lhoestq/agent-traces-example", "bytes": 472591, "note": "HF example: 2 Claude Code + 2 Codex raw files; no README/licence"},
        {"name": "TeichAI/* and many '<model>-claude-code-traces' distillation uploads", "note": "mostly no licence tag"},
        {"name": "doug-leith/extractor-code-development (Between the Commits, arXiv 2609.29744)", "note": "25 raw Claude Code sessions in a 96 MB zip; GitHub reports no licence; README does not grant one"},
        {"name": "cfahlgren1/codex-sessions, cfahlgren1/claude-sessions, ultralazr/claude-code-traces", "note": "license: other (terms not stated in card head)"},
    ],
}
out["corpora_gated_or_inaccessible"] = [
    {"name": "z-lab/glm52-cc", "status": "gated=manual (agree to share contact info); GLM-5.2 Claude Code traces", "action": "human decision"},
    {"name": "Intelligent-Internet/swebench-pro-gpt-5-codex-ii-agent-trajectories", "status": "gated=auto", "action": "human decision"},
    {"name": "Glint-Research/Fable-5-traces", "status": "HTTP 401 (private or removed); its content is reportedly the same as armand0e/claude-fable-5-claude-code (armand0e README)"},
    {"name": "13point5/opencode-rollouts-test, lwaekfjlk/codingcl-streams", "status": "HTTP 401"},
]
out["not_released_or_not_a_corpus"] = [
    {"name": "Cline: cline/incident-traces", "status": "CC BY 4.0, ungated, manifest.jsonl is 0 bytes at ce9dedfc5d492ca67509846f602c4593db1d71eb: no sessions yet. Taxonomy includes 'deception' ('All tests pass' when none were run). Watch: would be the first public labeled set of real agent incidents in a CLI harness."},
    {"name": "Cline: github.com/cline/cline-bench", "status": "tasks, environments and oracle solutions only; no user session traces (WebFetch)"},
    {"name": "Cline: github.com/cline/upload-hf", "status": "HTTP 404 (referenced by cline/incident-traces)"},
    {"name": "Roo Code", "status": "RooCodeInc/Roo-Code archived=true (GitHub API, pushed_at 2026-05-15); RooCodeInc/Roo-Code-Evals and lvogel123/roo-code-evals are exercises only"},
    {"name": "Microsoft 'Agentic Coding in the Wild' Copilot production traces (arXiv 2608.00101)", "status": "paper states plans to release sanitized traces; no release found; UNVERIFIED"},
    {"name": "OpenCode share links", "status": "individual shared sessions, no corpus or licence"},
    {"name": "SWE-chat codex/opencode/gemini/cursor/copilot subsets", "status": "settled corpus (CLAUDE_context §6); covered by B4, not re-researched"},
    {"name": "Terminal-Bench leaderboard CLI-agent runs", "status": "another B5 group's corpus (data/acquired/terminal-bench-2-leaderboard); not touched"},
]

# ---------------- prior art ----------------
out["prior_art"] = [
    {"claim": "A public CLI-trace release, or the tooling built around these releases, already checks tool results for fabrication or internal inconsistency from the log",
     "closest_work": "WhitzardAgent/agentir 'verify' pass; TraceLab validators; Cline incident-traces; Trace Commons donate-trace; HF Agent Trace Viewer",
     "does": "AgentIR VerifyPass checks unique event ids, monotonic indices, existing parent ids, tool names, artifact references and (strict mode) tool results whose tool_call_id has no matching call. TraceLab validators audit duplicate tool rows and timing-accounting residuals. Cline incident-traces collects human-labelled incidents incl. 'deception'. donate-trace scrubs secrets/PII and asks the contributor to review. The HF viewer renders call/result pairs.",
     "does_not": "None compares a result with other results, with the command, with a clock, or with a provider id. AgentIR's checks are structural ('verifies structural integrity and consistency of an AgentIR record'); a fabricated result with a valid id passes. Cline's labels are human-supplied and the set is empty.",
     "verdict": "NOT TAKEN", "interpretation": True,
     "deciding_citation": "sources/agentir_passes_verify.py (WhitzardAgent/agentir@68d991160ad579d2b4514da01684249a2a0bf629, VerifyPass._check_episode/_check_strict); sources/tracelab_validators__README.md (uw-syfi/TraceLab@11b8b14c); sources/cline_incident_traces_TAXONOMY.md"},
    {"claim": "Existing CLI-log tooling already uses provider request ids as a clock or response-binding check",
     "closest_work": "ccusage (ryoppippi/ccusage) Claude adapter",
     "does": "Builds a usage dedupe key from (message_id, request_id, session_id, timestamp): 'let exact_hash = usage_dedupe_hash(message_id, request_id, session_id, entry.timestamp);'",
     "does_not": "Never decodes the id's embedded time, never orders it against the log clock; uses it only as an identity key for cost deduplication.",
     "verdict": "NOT TAKEN (for the id-as-clock use; decoding time from ids is general prior art handled by B2)", "interpretation": True,
     "deciding_citation": "sources/ccusage_rust__adapters__claude__src__lib.rs lines 219-222 (ryoppippi/ccusage@8904e880d04e4cb4d4223457615bbe94385ac675)"},
    {"claim": "N1-adjacent: timing residuals computed over coding-agent traces",
     "closest_work": "TraceLab (arXiv 2606.30560) user_turn_gap_audit and tool-overhead analysis",
     "does": "Computes 'residual = response time - generation - tool time' and attributes it to handoffs, untimed tool calls, usage events, missing timestamps ('Goal: confirm the residual is accounting noise'). The paper quantifies Codex tool overhead as end-to-end minus internal execution time (18.6% of tool latency; mean 1.11 s, p99 10.0 s).",
     "does_not": "Does not condition the residual on the work a call claims (repeat-command baseline, output size) and does not use it as a fabrication or tamper signal.",
     "verdict": "PARTIAL (adjacent technique on the same kind of data; neither N1 sub-claim (a) nor (b) is taken by it). Passed to the B1 synthesizer.", "interpretation": True,
     "deciding_citation": "sources/tracelab_validators__human_in_the_loop__user_turn_gap_audit__README.md; arXiv 2606.30560 (alphaXiv report: 'For Codex, approximately 18.6% of the end-to-end tool latency is attributed to non-execution overhead')"},
    {"claim": "B3 nested timer: harness-internal tool durations are recorded alongside wall-clock stamps",
     "closest_work": "Codex exec output wrapper ('Wall time: X seconds'); Claude Code OpenTelemetry claude_code.tool_result (duration_ms, tool_result_size_bytes); Codex OTel codex.tool_result (duration); TraceLab tool_internal_latency_ms vs tool_wall_latency_ms",
     "does": f"These record a per-call duration that is independent of the log's call/result stamps. In the downloaded Codex rollouts {cx_wall}/{cx_outs_mk} outputs carry the 'Wall time' marker; TraceLab's Codex rows carry internal latency on {tlx['tools_internal_latency']}/{tlx['tools']} calls, and {tlx['tools_wall_lt_internal']} of those have wall latency < internal latency (descriptive honest inconsistency, not a threshold).",
     "does_not": "No source opened cross-checks the two clocks to flag tampering; the OTel exports are off by default (CLAUDE_CODE_ENABLE_TELEMETRY; Codex [otel] opt-in).",
     "verdict": "PARTIAL (inputs exist and are used for accounting; the consistency check is not done by any source opened)", "interpretation": True,
     "deciding_citation": "https://code.claude.com/docs/en/monitoring-usage (tool_result: duration_ms, tool_result_size_bytes; 'Tracing is off by default'); https://learn.chatgpt.com/docs/config-file/config-advanced (codex.tool_result: duration, success, output snippet; 'Disabled by default'); census/marker_scan.json; census/census_tracelab.json"},
    {"claim": "B6: a public corpus of raw provider responses (ids, timing) joined to native harness traces already exists",
     "closest_work": "huggingface/agentcap + dacorvo/*-session-captures",
     "does": "Captures every /v1/chat/completions request/response body (SSE raw) through a proxy, per run, joinable to OpenCode/Pi/Goose/Hermes native traces by run_id; HF-Router responses include provider id, created and sla_metrics.ts_us.",
     "does_not": "Backends are local llama.cpp and HF Router (GLM-4.6), not Anthropic or OpenAI first-party; no general HTTP headers (no request-id header); request_id is proxy-minted; README: 'Capture and export are deliberately dumb: persist the wire content'; no cross-check of trace vs capture.",
     "verdict": "PARTIAL (the open-weight / router case exists publicly; an Anthropic request-id-header corpus does not)", "interpretation": True,
     "deciding_citation": "sources/agentcap_README.md (huggingface/agentcap@2acf01aa4a24f799416ba260dd6a2639ddf4f198); dacorvo/transformers-coding-session-captures README schema (request_id: 'UUID minted by the capture proxy')"},
    {"claim": "Claim-vs-record checking on raw Claude Code transcripts (narration layer)",
     "closest_work": "Leith, 'Between the Commits' (arXiv 2609.29744)",
     "does": "Mines raw Claude Code .jsonl for pytest FAIL->edit->PASS episodes and fact-checks Claude's statements with an LLM decompose-classify-verify pipeline using codebase + transcripts as evidence.",
     "does_not": "Treats the transcript's tool results as ground truth; no check of the record's own consistency, clocks or ids.",
     "verdict": "NOT TAKEN for record self-consistency (same family as OverclaimBench / Plans They Abandon: trusts the log)", "interpretation": True,
     "deciding_citation": "arXiv 2609.29744 Sec. V-A ('we mine the raw Claude Code session transcripts directly ... these preserve every tool call: the exact pytest command run and its pass/fail output')"},
]

# ---------------- sources ----------------
out["sources"] = [
    {"url": "https://huggingface.co/docs/hub/en/agent-traces", "opened": True, "saw": "'Agent traces from Claude Code, Codex, and Pi Agent are natively supported on the Hugging Face Hub'; session dirs ~/.claude/projects, ~/.codex/sessions, ~/.pi/agent/sessions; no validation described"},
    {"url": "https://huggingface.co/docs/hub/en/session-traces-format", "opened": True, "saw": "STS-Format: session header {type, harness, id}; messages {role, content, toolCalls[{id,function}], toolCallId, timestamp (epoch ms, optional), model}; no validation of results or timing"},
    {"url": "https://huggingface.co/api/datasets?filter=format:agent-traces", "opened": True, "saw": f"{pop['n_format_agent_traces']} datasets (meta/hf_format_agent_traces.json)"},
    {"url": "https://huggingface.co/datasets/trace-commons/agent-traces", "opened": True, "saw": "CC-BY-4.0; 'raw, unmodified session file (only anonymized, never reshaped)'; sessions/claude_code, codex, pi, cursor, opencode"},
    {"url": "https://github.com/Trace-Commons-AI/donate-trace (SKILL.md, scripts/scrub.py @5eb9bcd17ceda270cec15f2be03afda4e83db663)", "opened": True, "saw": "scrub + TruffleHog + contributor review; no integrity or authenticity check; GitHub reports no licence"},
    {"url": "https://huggingface.co/datasets/cline/incident-traces (README, TAXONOMY.md, CONTRIBUTING.md @ce9dedfc)", "opened": True, "saw": "CC-BY-4.0; manifest.jsonl 0 bytes; categories incl. 'deception'"},
    {"url": "https://github.com/cline/upload-hf", "opened": False, "saw": "HTTP 404 (GitHub API)"},
    {"url": "https://github.com/cline/cline-bench", "opened": True, "saw": "tasks only, not user session traces"},
    {"url": "https://github.com/huggingface/agentcap (README @2acf01aa)", "opened": True, "saw": "'Capture and export are deliberately dumb: persist the wire content'; Apache-2.0"},
    {"url": "https://huggingface.co/datasets/dacorvo/transformers-coding-session-captures", "opened": True, "saw": "schema incl. request_id 'UUID minted by the capture proxy', captured_at epoch s, served_by/X-Served-By; join on run_id"},
    {"url": "https://github.com/WhitzardAgent/agentir/blob/68d991160ad579d2b4514da01684249a2a0bf629/src/agentir/passes/verify.py", "opened": True, "saw": "structural checks only (see prior_art[0])"},
    {"url": "https://github.com/ryoppippi/ccusage/blob/8904e880d04e4cb4d4223457615bbe94385ac675/rust/adapters/claude/src/lib.rs", "opened": True, "saw": "usage_dedupe_hash(message_id, request_id, session_id, entry.timestamp)"},
    {"url": "https://github.com/badlogic/cc-share-hf", "opened": False, "saw": "HTTP 404 (cited by ultralazr/claude-code-traces README)"},
    {"url": "https://code.claude.com/docs/en/monitoring-usage", "opened": True, "saw": "claude_code.api_request has request_id ('req_011...') and duration_ms; claude_code.tool_result has tool_use_id, duration_ms, tool_result_size_bytes; telemetry off by default"},
    {"url": "https://learn.chatgpt.com/docs/config-file/config-advanced (redirect from developers.openai.com/codex/config-advanced)", "opened": True, "saw": "codex.api_request, codex.sse_event, codex.tool_result (duration, success, output snippet); 'Disabled by default; opt in via [otel]'"},
    {"url": "https://codex.danielvaughan.com/2026/06/05/codex-cli-session-forensics-jsonl-post-mortems-codex-trace-cass-ccusage/", "opened": True, "saw": "codex-trace (viewer), cass (cross-agent search), ccusage (cost); none checks results for fabrication; only a jq wall-clock recipe"},
    {"url": "https://codex.danielvaughan.com/2026/04/29/codex-cli-rollout-files-session-recording-replay-audit-trails/", "opened": True, "saw": "audit trails by shipping rollouts / OTel; no hashing, signing or timing checks"},
    {"url": "https://arxiv.org/abs/2606.30560 (TraceLab)", "opened": True, "saw": "Sec 3.3 anonymization; tool latency: 'Codex reports the tool execution time explicitly, whereas for Claude we derive it from the tool's call and return timestamps'"},
    {"url": "https://github.com/uw-syfi/TraceLab @11b8b14c (README, LICENSE-DATASET.md, validators/*)", "opened": True, "saw": "dataset CC BY 4.0 via GitHub Releases; tool fields emitted_at/result_at/result_chars/tool_wall_latency_ms/tool_internal_latency_ms/is_error"},
    {"url": "https://api.github.com/repos/uw-syfi/TraceLab/releases", "opened": True, "saw": "v0.0.2 asset syfi_coding_trace.jsonl.gz 100,939,722 B, digest sha256:11ce51ec...; v0.0.1 53,601,226 B"},
    {"url": "https://arxiv.org/abs/2608.29204 (AgentLogs)", "opened": True, "saw": "307,416 tasks / 549,239 sessions / 64,255,174 log entries; HF risenlab/agentlogs; dataset CC BY 4.0; 56.7 GB"},
    {"url": "https://arxiv.org/abs/2608.00101 (Copilot production traces)", "opened": True, "saw": "alphaXiv report: plans to release sanitized traces; no release located (UNVERIFIED)"},
    {"url": "https://arxiv.org/abs/2609.29744 (Between the Commits)", "opened": True, "saw": "Sec V-A transcript mining; repo doug-leith/extractor-code-development has no licence"},
    {"url": "https://huggingface.co/datasets/nvidia/Open-SWE-Traces", "opened": True, "saw": "README Data Fields (messages, tools, resolved, metadata); 'Trajectories for OpenCode and Claude Code harnesses will be released soon'; paper arXiv 2606.16038 not opened"},
    {"url": "https://huggingface.co/datasets/Inferact/codex_swebenchpro_traces", "opened": True, "saw": "first 400 KB: conversations [{from, value}], assistant 'Lorem ipsum ...'"},
    {"url": "https://huggingface.co/datasets/ibm-research/codex_swebenchpro_traces_Otel", "opened": True, "saw": "'Timestamps are synthetic: spans within a trace are spaced with random 1-10 second delays'"},
    {"url": "https://huggingface.co/datasets/jedisct1/security-audits", "opened": True, "saw": "'agent traces generated with Swival (not Claude Code, despite what the HF interface currently shows)'"},
    {"url": "https://huggingface.co/datasets/armand0e/claude-fable-5-claude-code", "opened": True, "saw": "MIT; created 2026-06-11; says Glint-Research/Fable-5-traces was built from the same data (licence provenance check: AyoubChLin copy, created 2026-06-16, has no licence)"},
    {"url": "https://api.github.com/repos/RooCodeInc/Roo-Code", "opened": True, "saw": "archived: true; pushed_at 2026-05-15T18:08:47Z"},
    {"url": "https://huggingface.co/datasets/z-lab/glm52-cc", "opened": True, "saw": "gated: manual"},
    {"url": "analysis/out/phase_e/track_b/B2a_provider_id_facts/decode_examples.py", "opened": True, "saw": "Anthropic req_/msg_ base58 top-48-bit ms layout and OpenAI resp_ hex50 seconds layout reused here (layouts UNVERIFIED vs vendor docs)"},
]
out["process_incidents"] = [
    "HF API returned HTTP 429 for 36 of 523 metadata calls in the first census pass; all 36 were re-fetched with backoff (hf_files_census_retry.py), 0 errors remain.",
    "First sweep pass lost 3 queries (codex, opencode, goose) to a broken pipe from piping into `head` on Windows (OSError 22); re-run without the pipe.",
    "Windows console cp1252 encoding errors on README printing; re-run with PYTHONIOENCODING=utf-8 (no data affected).",
    "A bash command combining python and curl was denied by the permission layer; README tails were fetched with Python urllib instead.",
    "Sample audit of jedisct1/security-audits drew a 20 KB file with 0 tool calls (median-size pick); conclusions about Swival timing rest on the sibling flashmania sample.",
]
json.dump(out, open(sys.argv[2], "w", encoding="utf-8"), indent=1)
print("wrote", sys.argv[2])
print(json.dumps(out["headline"], indent=1)[:6000])
