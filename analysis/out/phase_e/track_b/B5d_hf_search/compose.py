"""Compose analysis/out/phase_e/track_b/B5d_hf_search.json from the saved audit outputs in this folder.
Every count below is computed from the files here; quoted passages are copied from the sources opened (see `sources`)."""
import json, os
from collections import Counter, defaultdict

H = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(H), "B5d_hf_search.json")
L = lambda f: json.load(open(os.path.join(H, f), encoding="utf-8"))

cls = {r["id"]: r for r in L("classified.json")}
meta = {m["id"]: m for m in L("meta_compact.json")}
req = {r["id"]: r for r in L("reqcensus.json")}
t1 = L("targeted1.json"); t2 = L("targeted2.json"); t3 = L("targeted3.json")
exg = L("exgentic_probe_stats.json")
dups = L("dup_groups.json")
qcounts = L("search_query_counts.json")
tag = L("agent_traces_tag_listing.json")

MB = lambda i: round(meta[i]["total_bytes"] / 1e6, 1)
SHA = lambda i: meta[i]["sha"]
URL = lambda i: f"https://huggingface.co/datasets/{i}"
DEST = lambda i: "C:/Swarms/data/acquired/hf__" + i.replace("/", "__")
CMD = lambda i, inc=None: f"hf download {i} --repo-type dataset --revision {SHA(i)} --local-dir {DEST(i)}" + (f" --include \"{inc}\"" if inc else "")

# ---------------- funnel ----------------
rows = list(cls.values())
funnel = {
    "search_queries": len(qcounts),
    "distinct_datasets_from_keyword_search": 3249,
    "datasets_tagged_format_agent_traces": tag["n"],
    "candidates_audited": len(rows),
    "candidates_from_tag": sum(1 for r in rows if r.get("agent_traces_tag")),
    "by_licence_class": dict(Counter(r["licence_class"] for r in rows)),
    "gated": sorted([r["id"] for r in rows if r["gated"] not in (False, None)]),
    "mechanical_field_audit_pass_all": sum(1 for r in rows if r.get("field_audit_pass")),
    "mechanical_field_audit_pass_licensed": sum(1 for r in rows if r.get("field_audit_pass") and r["licence_class"] != "none"),
    "mechanical_field_audit_pass_licensed_GB": round(sum(r["total_bytes"] for r in rows if r.get("field_audit_pass") and r["licence_class"] != "none") / 1e9, 3),
    "mechanical_field_audit_pass_unlicensed": sum(1 for r in rows if r.get("field_audit_pass") and r["licence_class"] == "none"),
    "formats_of_passing": dict(Counter(r.get("format") for r in rows if r.get("field_audit_pass"))),
    "note": "Mechanical pass rule (classify.py docstring): >=50% of sampled records carry a timestamp-valued field at depth<=2 AND >=80% of sampled call ids have a matching result id. One or two files per dataset, first 400 kB. Targeted re-audits (targeted1-3.json, exgentic_probe_stats.json) override the mechanical verdict where named below; parquet-only and single-JSON-array datasets are not parsed by the mechanical pass.",
}

# ---------------- request-id census ----------------
anth = [r for r in req.values() if r["decodable"]]
sig = defaultdict(list)
for r in anth:
    sig[(r["decodable"], tuple(r["delta_s_quantiles"] or []))].append(r["id"])
groups = list(sig.values())
rep = lambda g: req[g[0]]
lic_groups = [g for g in groups if any(cls[i]["licence_class"] in ("permissive", "research_only") for i in g)]
other_groups = [g for g in groups if all(cls[i]["licence_class"] == "other" for i in g)]
none_groups = [g for g in groups if all(cls[i]["licence_class"] == "none" for i in g)]
disagree = [{"id": r["id"], "licence_class": cls[r["id"]]["licence_class"], "distinct_ids": r["decodable"], "agree": r["agree"], "off_s_min_med_max": r["delta_s_quantiles"]}
            for r in anth if r["agree"] < r["decodable"]]
fam = Counter()
for r in req.values():
    for k, v in r["families"].items():
        fam[k] += v
reqid = {
    "rule": "Decoder and agreement band copied from B2a decode_examples.py::anth and B4 probe (analysis/probes/phase_e_b4_inventory.py L31, L236): off = first carrying event timestamp - top-48-bit ms of the base58 body; agrees iff -2 s <= off <= +600 s. Counted over DISTINCT request ids in each dataset's sampled file only (first 400 kB of one file), not over whole datasets.",
    "datasets_whose_sample_carries_request_ids": len(req),
    "by_licence_class": dict(Counter(cls[i]["licence_class"] for i in req)),
    "record_families": dict(fam),
    "datasets_with_anthropic_shaped_ids": len(anth),
    "anthropic_shaped_distinct_ids_all_datasets": sum(r["decodable"] for r in anth),
    "uuidv7_version_and_variant_bits_ok": sum(r["uuidv7"] for r in anth),
    "agree_all_datasets": sum(r["agree"] for r in anth),
    "dedup_note": "Datasets whose sampled file gives identical (distinct-id count, offset quantiles) are counted once (copies such as the 24-member claude-fable-5 group).",
    "dedup_groups": len(groups),
    "dedup_distinct_ids": sum(rep(g)["decodable"] for g in groups),
    "dedup_agree": sum(rep(g)["agree"] for g in groups),
    "licensed_groups": len(lic_groups),
    "licensed_distinct_ids": sum(rep(g)["decodable"] for g in lic_groups),
    "licensed_agree": sum(rep(g)["agree"] for g in lic_groups),
    "licence_other_groups": [g for g in other_groups],
    "licence_other_distinct_ids": sum(rep(g)["decodable"] for g in other_groups),
    "licence_other_agree": sum(rep(g)["agree"] for g in other_groups),
    "unlicensed_groups": len(none_groups),
    "unlicensed_distinct_ids": sum(rep(g)["decodable"] for g in none_groups),
    "unlicensed_agree": sum(rep(g)["agree"] for g in none_groups),
    "disagreements": disagree,
    "observations": [
        "Every disagreement sits in an unlicensed dataset; all licensed groups agree. In three MarxistLeninist repro-* sets the median offset is a few seconds negative (-2.4 to -6.3 s), and in a fourth (repro-ambient-dataloops) it is -20.3 s. A client clock running behind the provider would produce exactly this. In DedeProGames/claude-code-traces-pt-br the events are stamped 28 to 42 s BEFORE their request id was minted. Neither card explains it. Client clock skew is the simplest candidate and was not investigated. This is a false-positive source the request-id check must budget for: a per-session constant offset.",
        "Non-Anthropic request ids appear in Claude-Code-format files produced by other endpoints: `req_<hex>` (Xiaomi MiMo via Claude Code, choucsan/mimo-*), and `req_other` shapes in Infatoshi/kernelbench-* (gpt-5.5, kimi via Claude Code) and the clem/davidkling hf-coding-tools family (gpt-4.1 / sonnet-4.6 through some gateway, msg ids `msg_<hex>`). None decodes to a time with the Anthropic layout.",
    ],
    "consequence_for_B2_B4": "B4 found one public corpus with provider request ids (swechat claude_code). The HF Hub adds licensed Claude Code session sets whose ids decode and agree with the carrying event clock (counts above). Coverage still covers only one harness and one provider (Claude Code to Anthropic first-party). Codex, Pi, OpenCode and Cursor files on HF carry no provider request id.",
}

# ---------------- recommended corpora (pending human approval to download) ----------------
def tgt(rid, path_end):
    for t in t1 + t2 + t3:
        if t["id"] == rid and t["path"].endswith(path_end):
            return t
    return None

cc_reqid_lic = []
for g in lic_groups:
    licd = [i for i in g if cls[i]["licence_class"] in ("permissive", "research_only")]
    r0 = sorted(licd, key=lambda i: (cls[i]["licence_class"] != "permissive", i))[0]
    cc_reqid_lic.append({"repo": r0, "copies_in_group": len(g), "licence": cls[r0]["license"], "MB": MB(r0), "revision": SHA(r0),
                         "distinct_ids_in_sample": req[r0]["decodable"], "agree": req[r0]["agree"], "off_s_min_med_max": req[r0]["delta_s_quantiles"],
                         "models": list(req[r0]["models"]), "command": CMD(r0)})

EXCLUDE_CONVERTED = {"Samarth0710/traceweave": "rehydrated into Claude Code schema from other harnesses (README); timestamps not native",
                     "Jadson/ox-alpha-pi-traces-emacs-bridge": "converted from TeichAI/Ox-Alpha-Pi-Traces with tool calls re-run through a bridge (README)",
                     "julien-c/synthtraces": "synthetic sessions: two models drive Pi on generated tasks (README 'generate synthetic coding agent session traces'); harness timing is real, prompts are not"}
pi_mit = [i for i, r in cls.items() if r.get("field_audit_pass") and r["licence_class"] in ("permissive", "research_only") and r.get("format") in ("pi_or_sts_message", "pi_header") and i not in EXCLUDE_CONVERTED]
codex_lic = [i for i, r in cls.items() if r.get("field_audit_pass") and r["licence_class"] in ("permissive", "research_only") and r.get("format") == "codex"]
cc_noreq_lic = [i for i, r in cls.items() if r.get("field_audit_pass") and r["licence_class"] in ("permissive", "research_only") and r.get("format") == "claude_code"
                and not any(i in g for g in lic_groups) and i not in EXCLUDE_CONVERTED and not i.startswith("Infatoshi/")]

recommended = [
    {"name": "Exgentic multi-benchmark OTel agent traces", "repo": "Exgentic/agent-llm-traces", "url": URL("Exgentic/agent-llm-traces"), "revision": SHA("Exgentic/agent-llm-traces"),
     "licence": "cdla-permissive-2.0 (card front-matter `license: cdla-permissive-2.0`; permits use, modification and sharing incl. research; no NC clause)", "MB": MB("Exgentic/agent-llm-traces"),
     "sessions": "1,781 traces (README); 5 harnesses (claude_code, openai_solo, tool_calling, tool_calling_with_shortlisting, smolagents_code); 6 benchmarks; 5 models",
     "field_audit": {"verdict": "PASS", "evidence_file": "B5d_hf_search/exgentic_probe_stats.json",
                     "ms_timestamps": "YES per LLM call: span start_time/end_time ISO-8601 with microseconds (e.g. " + exg["per_row"][0]["first_start"] + "). Tool executions are not spans; a tool's wall interval is the gap between span k end and span k+1 start.",
                     "call_result_join": "YES: OTel GenAI message parts tool_call.id <-> tool_call_response.id; sampled rows joined " + ", ".join(f"{e['joined']}/{e['tool_call_ids']}" for e in exg["per_row"]) + " (the last call of each session has no response)",
                     "provider_request_ids": "gen_ai.response.id per span (sampled Azure DeepSeek-V3.2 rows: 32-hex, e.g. " + str(exg["per_row"][0]["response_id_example"]) + "; no known time layout). claude_code-harness rows not sampled, so their id shape is UNVERIFIED.",
                     "caveats": f"only 6 rows of shard 3 (harness tool_calling, appworld) were sampled; one sampled session has {max(e['n_negative_gaps'] for e in exg['per_row'])} negative inter-span gaps (overlapping LLM calls), so ordering by start time is not safe without checking. The open-agent-leaderboard/traces repo (unlicensed) appears to hold the same benchmarks as raw jsonl."},
     "schema_note": "row = session {harness, benchmark, models[], max_tokens, total_tokens, session_id, collected_at, spans[]}; span {span_id, trace_id, name 'chat <model>', kind, type 'llm_call', start_time, end_time, attributes{gen_ai.operation.name, gen_ai.request.model, gen_ai.response.model, gen_ai.usage.input_tokens, gen_ai.usage.output_tokens, gen_ai.response.id, gen_ai.response.finish_reasons[], gen_ai.input.messages (JSON string), gen_ai.output.messages (JSON string), gen_ai.tool.definitions}, resource_attributes{telemetry.sdk.*, service.*}, status{code, message}, harness, benchmark, session_id}. 39 parquet shards.",
     "command": CMD("Exgentic/agent-llm-traces"), "priority": "A"},
    {"name": "AgentBRANE SWE-bench Lite v14 harness-native traces", "repo": "melissapan/swe-bench-lite-agent-traces-v14", "url": URL("melissapan/swe-bench-lite-agent-traces-v14"), "revision": SHA("melissapan/swe-bench-lite-agent-traces-v14"),
     "licence": "cc-by-4.0 (README: 'The original compilation and metadata are CC BY 4.0 and are intended to support open research.')", "MB": MB("melissapan/swe-bench-lite-agent-traces-v14"),
     "sessions": "1,890 published traces (README), 1,908 trace.jsonl files on disk; harnesses claude-code, codex, pi; 7 model slugs (fable, haiku, kimi, luna, opus, sol, sonnet); 3 replicates",
     "field_audit": {"verdict": "PASS for the Claude Code third only",
                     "ms_timestamps": "Claude Code (SDK stream-json): timestamp ISO ms on 95% of records (" + str(tgt('melissapan/swe-bench-lite-agent-traces-v14', '0017659d895cdf7925b5a59bb5ef2713/trace.jsonl')['audit']['events_with_ts_depth_le2']) + "/" + str(tgt('melissapan/swe-bench-lite-agent-traces-v14', '0017659d895cdf7925b5a59bb5ef2713/trace.jsonl')['audit']['n_records']) + "). Codex (`codex exec --json` events: type/item/thread_id): NO timestamps. Pi (json-mode stream): timestamps on 17% of records (message objects only; tool_execution_* events unstamped).",
                     "call_result_join": "Claude Code tool_use.id <-> tool_result.tool_use_id 11/11 in sample; Pi toolCallId 6/6; Codex items carry ids and exit_code but no timestamps",
                     "provider_request_ids": "NONE: Claude Code went through a gateway and the traces carry no requestId; gateway receipts.jsonl exclude provider request ids and carry no timestamps (route, outcome, byte counts, sha256 digests only)",
                     "caveats": "Gateway receipts are a third record per call (byte counts + digests of request/response bodies) that could be cross-checked against the trace, but they carry no clock and no id join to trace events."},
     "schema_note": "data/traces.jsonl rows {observation_id, cell_id, harness, model_slug, task_id, replicate, attempt_id, resolved, turns, input/output/cache tokens, trace_path, trace_sha256, trace_bytes, trace_events, trace_format (claude-code-native-jsonl | codex-native-jsonl | pi-native-jsonl), gateway_receipts_path, gateway_receipt_count, ...}; per attempt dir: trace.jsonl, gateway/receipts.jsonl, model.patch, result.json, report.json, test_output.txt.zst, bundle-manifest.json.",
     "command": CMD("melissapan/swe-bench-lite-agent-traces-v14"), "priority": "A"},
    {"name": "MCPHunt agent traces (MCP data-propagation benchmark)", "repo": "lihaonan0716/mcphunt-agent-traces", "url": URL("lihaonan0716/mcphunt-agent-traces"), "revision": SHA("lihaonan0716/mcphunt-agent-traces"),
     "licence": "cc-by-4.0 (card front-matter)", "MB": MB("lihaonan0716/mcphunt-agent-traces"),
     "sessions": "3,615 main + 2,706 mitigation + 387 live-guard + 78 browser-replication traces (README); 5 models",
     "field_audit": {"verdict": "PASS (structural parse of the first trace of mitigation/deepseek_m0_rv1.json)",
                     "ms_timestamps": "YES per tool call: events[].timestamp epoch seconds with microseconds (e.g. 1777219294.977868) plus events[].latency_ms",
                     "call_result_join": "YES: assistant tool_calls[].id <-> tool message tool_call_id 8/8 in the parsed trace; events[] has one record per call in order (8 events for 8 calls)",
                     "provider_request_ids": "NONE seen",
                     "caveats": "One trace parsed structurally; the other 31 files were not. Tool results are MCP servers in a controlled workspace; env_snapshot gives the workspace state (files, db tables, git commits), which is a world-state reference for consistency checks."},
     "schema_note": "file = {schema_version, pipeline_git_commit, task_taxonomy_version, labeling_rules_version, traces[]}; trace keys: trace_id, task_id, task_prompt, task_category, risk_mechanism, sink_policy, env_type, mitigation(_level), model, wire_api, num_turns, num_events, turn_log[{turn, finish_reason, n_tool_calls, prompt_tokens, completion_tokens, has_text}], tool_errors, task_completed, truncated, api_errors, duration_s, events[{turn, server, tool, args, result_preview, result_full, result_chars, result_truncated, success, error, canary_in_result, canary_visible_to_llm, canary_in_args, latency_ms, timestamp}], messages[OpenAI chat], labeling{...}, completion_checks{...}, env_snapshot{...}, measurement{prompt/completion/total tokens, api_retries, ...}, collection_timestamp.",
     "command": CMD("lihaonan0716/mcphunt-agent-traces"), "priority": "A"},
    {"name": "Trace Commons (raw multi-harness donated sessions)", "repo": "trace-commons/agent-traces", "url": URL("trace-commons/agent-traces"), "revision": SHA("trace-commons/agent-traces"),
     "licence": "cc-by-4.0 (README: 'The Trace Commons compilation ... is released under CC-BY-4.0'; contents keep their own licences, contributor-certified)", "MB": MB("trace-commons/agent-traces"),
     "sessions": "28 Claude Code jsonl (57.1 MB), 1 OpenCode json, 1 Cursor jsonl; codex/ and pi/ hold only .gitkeep at this revision",
     "field_audit": {"verdict": "PASS (Claude Code files); OpenCode PASS on timestamps (epoch-ms time.start/end per part), join not machine-checked; Cursor FAIL (no timestamps)",
                     "ms_timestamps": "Claude Code timestamp ISO ms on 87.5% of records in sample",
                     "call_result_join": "tool_use/tool_result 69/70 in sample",
                     "provider_request_ids": "YES Anthropic `req_011C...` (" + str(tgt('trace-commons/agent-traces', '07b57159-218e-4330-a64e-0ec4b4355056.jsonl')['audit']['n_request_id_values']) + " distinct in the sampled 600 kB)",
                     "caveats": "Small. The parquet table under data/ is a re-shaped view; use sessions/ (README: 'The raw sessions/ files remain the source of truth')."},
     "schema_note": "sessions/claude_code/*.jsonl = native Claude Code (type, sessionId, uuid, parentUuid, timestamp, message{content[tool_use|tool_result|text|thinking], usage, model, id}, requestId, toolUseResult); sessions/opencode/*.json = opencode export {info{id, time{created, updated}, tokens}, messages[{info{role, time{created, completed}}, parts[{type, callID?, state{time{start, end}}}]]}.",
     "command": CMD("trace-commons/agent-traces", "sessions/*"), "priority": "A"},
    {"name": "Claude Code sessions with Anthropic request ids, licensed, deduplicated", "repo": "(family, one representative per duplicate group)", "url": "see members",
     "licence": "per member (mit, apache-2.0, cc-by-4.0, cc0-1.0, agpl-3.0)", "MB": round(sum(m["MB"] for m in cc_reqid_lic), 1),
     "members": cc_reqid_lic,
     "field_audit": {"verdict": "PASS (each member passed the mechanical audit; ids decoded with the B2a decoder)",
                     "ms_timestamps": "ISO ms per entry", "call_result_join": "tool_use.id <-> tool_result.tool_use_id",
                     "provider_request_ids": f"YES: {sum(m['distinct_ids_in_sample'] for m in cc_reqid_lic)} distinct ids in samples, {sum(m['agree'] for m in cc_reqid_lic)} agree with the B4 band",
                     "caveats": "Many are distillation captures (teich) or hackathon build logs. The claude-fable-5 group has 24 copies on the Hub, 3 of them licensed. Sessions resumed from earlier sessions repeat earlier lines, so dedupe on uuid."},
     "schema_note": "native Claude Code jsonl (see Trace Commons)", "command": "one `hf download` per member (members[].command)", "priority": "A"},
    {"name": "KernelBench agent traces (Infatoshi)", "repo": "Infatoshi/kernelbench-hard-traces (+ kernelbench-mega-traces)", "url": URL("Infatoshi/kernelbench-hard-traces"), "revision": SHA("Infatoshi/kernelbench-hard-traces"),
     "licence": "mit (both)", "MB": round(MB("Infatoshi/kernelbench-hard-traces") + MB("Infatoshi/kernelbench-mega-traces"), 1),
     "sessions": f"{cls['Infatoshi/kernelbench-hard-traces']['n_jsonl']} + {cls['Infatoshi/kernelbench-mega-traces']['n_jsonl']} jsonl, one per (harness, model, problem)",
     "field_audit": {"verdict": "PASS", "ms_timestamps": "ISO ms on ~99% of records", "call_result_join": "100% in 4 sampled files (69-154 calls each)",
                     "provider_request_ids": "present but NOT Anthropic-shaped in the sampled codex/kimi files (`req_other` family); Anthropic-shaped in the claude-fable-5 file (targeted3)",
                     "caveats": "Several harnesses (claude, codex, kimi-claude) appear rendered into Claude Code jsonl schema, so non-Claude files are a conversion and their timestamps may not be native. UNVERIFIED which."},
     "schema_note": "Claude Code jsonl schema", "command": CMD("Infatoshi/kernelbench-hard-traces") + " ; " + CMD("Infatoshi/kernelbench-mega-traces"), "priority": "B"},
    {"name": "Swival security-audit traces (Claude-Code-compatible export from a different harness)", "repo": "jedisct1/security-audits", "url": URL("jedisct1/security-audits"), "revision": SHA("jedisct1/security-audits"),
     "licence": "mit", "MB": MB("jedisct1/security-audits"), "sessions": f"{cls['jedisct1/security-audits']['n_jsonl']} jsonl",
     "field_audit": {"verdict": "PASS on 1 of 4 sampled files (the others are tool-free stubs)", "ms_timestamps": "ISO 6dp", "call_result_join": "15/15 in the dlang file", "provider_request_ids": "NONE",
                     "caveats": "README: 'generated with Swival (**not** Claude Code ...)' and 'Swival's Claude Code compatible trace export'. A different harness that writes the same schema is a natural cross-harness transfer test. Many files are short and have no tool calls."},
     "schema_note": "Claude Code jsonl schema written by Swival", "command": CMD("jedisct1/security-audits"), "priority": "B"},
    {"name": "Pi coding-agent sessions (real, pi-share-hf exports), MIT/Apache/BSD/CC-BY", "repo": "(family)", "url": "see members",
     "licence": "per member", "MB": round(sum(MB(i) for i in pi_mit), 1),
     "members": [{"repo": i, "licence": cls[i]["license"], "MB": MB(i), "n_jsonl": cls[i]["n_jsonl"], "revision": SHA(i), "command": CMD(i)} for i in sorted(pi_mit, key=lambda i: -MB(i))],
     "field_audit": {"verdict": "PASS (mechanical, each member)", "ms_timestamps": "entry timestamp ISO ms + message.timestamp epoch ms", "call_result_join": "content[type=toolCall].id <-> toolResult message toolCallId",
                     "provider_request_ids": "NONE (pi format has none)", "caveats": "pi-share-hf exports pass deterministic redaction + LLM review. MaxDevv/real-pi-coding-agent-traces-sessions compiles many of these plus pi-mono (licence 'other', no text), so download the members, not the compilation."},
     "schema_note": "pi session format: header {type:'session', version, id, timestamp, cwd}; entries {type, id, parentId, timestamp, message{role, content[text|thinking|toolCall{id,name,arguments}], usage, timestamp(ms), model, provider}} ; tool results role 'toolResult' with toolCallId, toolName, isError", "command": "members[].command", "priority": "B"},
    {"name": "Codex CLI rollouts (native ~/.codex/sessions), licensed", "repo": "(family)", "url": "see members", "licence": "per member", "MB": round(sum(MB(i) for i in codex_lic), 1),
     "members": [{"repo": i, "licence": cls[i]["license"], "MB": MB(i), "n_jsonl": cls[i]["n_jsonl"], "revision": SHA(i), "command": CMD(i)} for i in sorted(codex_lic, key=lambda i: -MB(i))],
     "field_audit": {"verdict": "PASS (mechanical, each member)", "ms_timestamps": "line timestamp ISO ms", "call_result_join": "response_item function_call.call_id <-> function_call_output.call_id",
                     "provider_request_ids": "NONE (codex rollouts carry none; B4 found a turn_context trace_id of unknown provenance in swechat codex)", "caveats": "Mostly hackathon build logs; small."},
     "schema_note": "codex rollout jsonl {timestamp, type: session_meta|turn_context|response_item|event_msg, payload}", "command": "members[].command", "priority": "B"},
    {"name": "Other licensed Claude Code sessions without Anthropic-shaped request ids", "repo": "(family)", "url": "see members", "licence": "per member", "MB": round(sum(MB(i) for i in cc_noreq_lic), 1),
     "members": [{"repo": i, "licence": cls[i]["license"], "MB": MB(i), "revision": SHA(i), "command": CMD(i)} for i in sorted(cc_noreq_lic, key=lambda i: -MB(i))],
     "field_audit": {"verdict": "PASS (mechanical)", "ms_timestamps": "ISO ms/us", "call_result_join": "tool_use/tool_result", "provider_request_ids": "NONE in sample", "caveats": "includes 'other'-licensed only if licence_class allowed; see members"},
     "schema_note": "Claude Code jsonl", "command": "members[].command", "priority": "C"},
]
for r in recommended:
    if r["repo"] == "(family)" or r["repo"].startswith("(family"):
        pass

# ---------------- listed for a human / partial / failed ----------------
listed = [
    {"name": "AgentLogs (GitHub Copilot cloud agent)", "repo": "risenlab/agentlogs", "url": URL("risenlab/agentlogs"), "revision": SHA("risenlab/agentlogs"), "licence": "cc-by-4.0 (DATA_LICENSE)", "MB": MB("risenlab/agentlogs"),
     "why_listed": "56.7 GB is over the 5 GB per-corpus cap. A subset fits: agent_session_logs is 276 shards of ~200 MB, so 10 to 20 shards (2 to 4 GB) plus agent_sessions (225 MB).",
     "field_audit": "schema-level PASS (docs/schema/agent_session_log_entry.md via WebFetch: data.created datetime, data.timestamp, data.callId / toolCallId / tool_call_id, choices[].message.tool_calls[].id, usage.*, modelCallDurationMs, error.*, truncateResult{...}); the first row group (197 MB) was too large to sample rows. 64,255,174 log entries, 549,239 sessions, 307,416 tasks (README). A second real-world harness at scale.",
     "subset_command": CMD("risenlab/agentlogs", "agent_sessions/*") + " ; " + CMD("risenlab/agentlogs", "agent_session_logs/part_0000[0-9]_of_00276.parquet"),
     "provider_request_ids": "UNVERIFIED: data.id and data.object fields exist (chat-completion objects with content_filter_results suggest Azure OpenAI `chatcmpl` ids, which have no known time layout); 'created' (server epoch seconds in chat.completion objects) would be a provider-side clock if present. Not sampled."},
    {"name": "AgentTrajectorySentinel", "repo": "sunnydubey1111/agent-trajectory-sentinel", "url": URL("sunnydubey1111/agent-trajectory-sentinel"), "revision": SHA("sunnydubey1111/agent-trajectory-sentinel"), "licence": "other: card says Apache-2.0 for project code/format, model outputs under the model licences (Qwen Apache-2.0, Llama 3.1 Community, Gemini API terms); paper appendix: MIT repo",
     "MB": MB("sunnydubey1111/agent-trajectory-sentinel"),
     "why_listed": "Strict audit FAIL: no absolute per-event timestamps (steps carry latency_s, output_tokens, error; tool_events carry result, result_chars, result_truncated, is_error, latency_s) and tool_events[].id is empty, so call/result pairing is structural (same step record). High value anyway: 3,581 episodes with deterministic tool-layer fault injection (context_corruption, i.e. corrupted tool results) at a verified onset step tau, plus organic 'hallucinated' labels. Those are labeled positives of the kind our corpora lack. Human decision: accept a no-timestamp labeled set for result-level checks?",
     "field_audit": "targeted1.json: traces/autogen/autogen-context_corruption-000.jsonl, 4 records, keys text/token_logprobs/action/latency_s/output_tokens/error/task/tool_events/schema",
     "command": CMD("sunnydubey1111/agent-trajectory-sentinel")},
    {"name": "Real Pi sessions compilation", "repo": "MaxDevv/real-pi-coding-agent-traces-sessions", "url": URL("MaxDevv/real-pi-coding-agent-traces-sessions"), "revision": SHA("MaxDevv/real-pi-coding-agent-traces-sessions"), "licence": "other (README: 'This is a compilation; each session remains under the license of its source dataset')",
     "MB": MB("MaxDevv/real-pi-coding-agent-traces-sessions"), "why_listed": "Passes the field audit, but 626 of 1,291 sessions come from badlogicgames/pi-mono (licence 'other', no licence text on the card) and 38 from aaaaliou/pi-synthetic (synthetic, despite the card's 'hand-filtered to exclude synthetic'). Download the MIT members directly (pi family above). pi-mono itself needs a human to ask its author for terms."},
    {"name": "Unlicensed passing datasets (do not download; ask authors)", "count": funnel["mechanical_field_audit_pass_unlicensed"],
     "largest": [{"repo": i, "MB": MB(i), "format": cls[i].get("format"), "request_ids_in_sample": cls[i].get("request_id_values")} for i in sorted([i for i, r in cls.items() if r.get("field_audit_pass") and r["licence_class"] == "none"], key=lambda i: -MB(i))[:25]],
     "why_listed": "No licence in card metadata, so do not download (task rule)."},
    {"name": "Unlicensed large corpora that did not pass or were not parseable", "items": [
        {"repo": "nlile/misc-merged-claude-code-traces-v1", "MB": MB("nlile/misc-merged-claude-code-traces-v1"), "note": "32,133 rows with `timestamp` and `request_id` columns plus raw `claude_log` (datasets-server /info). No licence. WhitzardAgent/ClaudeCode-* (apache-2.0) are format conversions of it, which drop timestamps and request ids. A licence relabel on a derivative does not license the source."},
        {"repo": "agent-evals/hal_traces", "MB": MB("agent-evals/hal_traces"), "note": "HAL harness zips, 113 GB, no licence, over cap"},
        {"repo": "Wejh/ninja-agent-traces", "MB": MB("Wejh/ninja-agent-traces"), "note": "no licence, over cap"},
        {"repo": "VonEquinox/efficient-agent-experiment-logs", "MB": MB("VonEquinox/efficient-agent-experiment-logs"), "note": "npy/pt experiment artifacts, not transcripts"},
        {"repo": "open-agent-leaderboard/traces", "MB": MB("open-agent-leaderboard/traces"), "note": "same benchmarks as Exgentic as raw jsonl; no licence"},
        {"repo": "badlogicgames/pi-mono", "MB": 224.8, "note": "licence 'other' with no licence text (WebFetch of card); 626 real pi sessions by the pi author"},
        {"repo": "TeichAI/DeepSeek-v4-Pro-Agent", "MB": MB("TeichAI/DeepSeek-v4-Pro-Agent"), "note": "the HF docs' own example dataset; teich distillation captures; no licence"}]},
    {"name": "Gated (needs a human to accept terms)", "items": [{"repo": i, "gated": cls[i]["gated"], "licence": cls[i]["license"], "MB": MB(i)} for i in funnel["gated"]]},
]

failed = [
    {"repo": "ibm-research/codex_swebenchpro_traces_Otel", "licence": "cc-by-nc-4.0", "MB": MB("ibm-research/codex_swebenchpro_traces_Otel"), "reason": "timestamps synthetic. README: 'Timestamps are synthetic: spans within a trace are spaced with random 1-10 second delays (no real wall-clock timing data was available in the source).' Assistant outputs are lorem ipsum."},
    {"repo": "ibm-research/lmcache-agentic-traces_Otel", "licence": "cc-by-nc-4.0", "MB": MB("ibm-research/lmcache-agentic-traces_Otel"), "reason": "OTel re-rendering of sammshen/lmcache-agentic-traces; same conversion pipeline as the codex OTel set, so synthetic timing assumed (README not read in full: UNVERIFIED)"},
    {"repo": "Inferact/codex_swebenchpro_traces", "licence": "mit", "MB": MB("Inferact/codex_swebenchpro_traces"), "reason": "one 218 MB JSON of ShareGPT-style {conversations:[{from, value}]}; no timestamp or id keys in the first 300 kB; assistant turns redacted to lorem ipsum (per the IBM derivative's README). README timing tables are summary statistics, not per-event fields."},
    {"repo": "sammshen/lmcache-agentic-traces", "licence": "cc-by-4.0", "MB": MB("sammshen/lmcache-agentic-traces"), "reason": "per-iteration `pre_gap` (s between last token of response N-1 and request N) and cumulative OpenAI messages; no absolute per-event timestamps, no per-tool duration. PARTIAL: pre_gap is a real client-side tool+think interval per LLM call (README)."},
    {"repo": "netpreme/coding_agent_traces", "licence": "mit", "MB": MB("netpreme/coding_agent_traces"), "reason": "per-turn ISL/OSL token counts (+ raw text for gpt-oss configs); no timestamps; 7.4 GB"},
    {"repo": "Jakumetsu/mcpmark-trajectory-log", "licence": "mit", "MB": MB("Jakumetsu/mcpmark-trajectory-log"), "reason": "task-level time.start/end only (meta.json); messages.json has call_id joins but no per-event timestamps; execution.log is plain text"},
    {"repo": "WhitzardAgent/ClaudeCode-* (Anthropic, OpenAI, Hermes, OpenHands, AgentIR)", "licence": "apache-2.0", "MB": MB("WhitzardAgent/ClaudeCode-Anthropic"), "reason": "format conversions of nlile/misc-merged-claude-code-traces-v1 into SFT message formats; timestamps and request ids dropped"},
    {"repo": "thoughtworks/agentic-coding-trajectories", "licence": "other (derivative-multi-source)", "MB": MB("thoughtworks/agentic-coding-trajectories"), "reason": "normalized/tokenized SWE-agent, OpenHands, Klear trajectories; no timestamps"},
    {"repo": "beomi/agent-traces", "licence": "other (mixed-upstream-licenses)", "MB": MB("beomi/agent-traces"), "reason": "62,812 deduplicated conversations normalized to OpenAI SFT format from 493 HF agent-trace repos; joins kept, timestamps dropped"},
    {"repo": "PotatoHD/github-pr-agent-trajectories", "licence": "other", "MB": MB("PotatoHD/github-pr-agent-trajectories"), "reason": "plan/subagent diffs, no events"},
    {"repo": "clem/davidkling/cfahlgren1 hf-coding-tools-traces family", "licence": "cc-by-4.0", "MB": MB("cfahlgren1/hf-coding-tools-traces"), "reason": "Claude Code schema with timestamps and request ids but zero tool calls in 6 sampled files (question-answer runs)"},
    {"repo": "melissapan/swe-bench-lite-agent-traces-v14 (codex part)", "licence": "cc-by-4.0", "MB": None, "reason": "codex exec --json event stream has no timestamps"},
    {"repo": "cline/incident-traces", "licence": "cc-by-4.0", "MB": MB("cline/incident-traces"), "reason": "only manifest.jsonl + docs at this revision; no sessions uploaded yet (ATIF + Cline messages promised). Re-check later."},
    {"repo": "harry1332/hpca2027-agentic-validated-traces-20260711", "licence": "mit", "MB": MB("harry1332/hpca2027-agentic-validated-traces-20260711"), "reason": "out of scope: DynamoRIO CPU instruction traces of agent workloads, not tool logs"},
    {"repo": "marco-bazzani/concealed-fabrication-agentic", "licence": "other", "MB": None, "reason": "62 synthetic Qwen3-8B episodes where the agent fabricates a value in its deliverable after a failed lookup; tool results are genuine; no timestamps or ids (card via WebFetch). Narration-layer fabrication, not our threat model."},
    {"repo": "Lightcap/agent-runtime-telemetry-small", "licence": "cc-by-4.0", "MB": MB("Lightcap/agent-runtime-telemetry-small"), "reason": "technically PASS (event_time_utc us, request_id joins tool_requests/tool_results, duration_ms) but payloads replaced by sha256 + byte counts and it is a single developer's MCP runtime with no model transcript. Low value; listed, not recommended."},
]

prior_art = [
    {"item": "Dubey 2026, 'Real-Time Detection and Repair of LLM Agent Failures' (arXiv 2608.02464) and its corpus sunnydubey1111/agent-trajectory-sentinel",
     "relevant_to": ["B1 (N1a duration residual)", "B3 (fabricated tool-result / result-level checks)"],
     "what_it_does": "One-class ESN+CUSUM monitor over per-step telemetry (hash embedding, token surprisal, action metadata incl. log latency) trained on healthy runs; deterministic checks: total_consistency (recompute the stated total from tool results received), required_coverage, and tool_contract ('asks whether a result matched any shape its tool can return'); injected tool-layer faults (context_corruption, malformed_json, wrong_document).",
     "what_it_does_not": "Treats tool results as ground truth for its fabrication class ('every figure asserted must trace to a tool result received'). Latency is a raw feature, not conditioned on workload, and 'wall-clock latency features are machine-specific and are excluded from the shipped configuration' (s.11(6)). No result-to-result consistency, no provider-side clock, no output-size discriminator.",
     "verdict_for_our_claims": {"N1a workload-conditioned duration residual": "NOVEL vs this work (latency used only as an unconditioned monitor feature, then dropped)",
                                "N1b corr(residual, output_size)": "NOVEL vs this work",
                                "tool-result shape / contract validation (N5 well-formedness items)": "PARTIAL: tool_contract validates result shape against the tool's possible returns on mock tools (0 of 1,825 healthy flagged; 46% of injected context corruption)",
                                "fabricated-tool-result detection from logs": "PARTIAL at most: their injected context corruption is tool-result corruption, detected by content-grounding telemetry plus tool_contract. Their 'fabrication' class is narration."},
     "opened": True, "how": "alphaXiv get_paper_content fullText", "url": "https://arxiv.org/abs/2608.02464",
     "deciding_passages": ["'wall-clock latency features are machine-specific and are excluded from the shipped configuration.'", "'tool_contract asks whether a result matched any shape its tool can return'", "'every figure asserted must trace to a tool result received (s.9)'"],
     "flag": "Not cited in B1d_agent_eval.json. Give it to the B1/B3 synthesizers. The 'Adversarial limit' artifacts (adversarial_evasion.csv, tamper_check.csv) are listed in its provenance table but were NOT opened: UNVERIFIED."},
    {"item": "AgentBRANE gateway receipts (melissapan/swe-bench-lite-agent-traces-v14)", "relevant_to": ["B2", "B6"],
     "what_it_does": "Records a gateway-side receipt per provider call next to the harness trace (route, outcome, decoded byte counts and sha256 of request and response bodies).",
     "what_it_does_not": "The public projection drops provider request ids and headers and carries no timestamps, so it cannot act as a clock.",
     "verdict_for_our_claims": {"provider-minted request-id clock (B2)": "not taken by this release; it is evidence that even an instrumented release strips the field B2 needs"},
     "opened": True, "url": "https://huggingface.co/datasets/melissapan/swe-bench-lite-agent-traces-v14/blob/main/SCHEMA.md", "deciding_passages": ["README: 'Gateway authentication/request/response headers and raw request/response bodies are not released; projected receipts retain route, outcome, byte-count, and digest evidence.'"]},
    {"item": "OpenTelemetry GenAI conventions as carried in Exgentic/agent-llm-traces", "relevant_to": ["B2"],
     "what_it_does": "Each LLM-call span carries gen_ai.response.id, a provider-minted response id, plus start/end time.",
     "what_it_does_not": "The sampled ids (Azure DeepSeek) are 32-hex with no time layout. Nothing cross-checks the id against the span clock.",
     "verdict_for_our_claims": {"B2 request-id clock": "not taken here; the convention preserves provider ids, which widens potential coverage where the provider embeds time"},
     "opened": True, "url": "https://huggingface.co/datasets/Exgentic/agent-llm-traces", "deciding_passages": ["schema field list from datasets-server /info: 'spans[].attributes.gen_ai.response.id:string'"]},
]

sources = [
    {"url": "https://huggingface.co/api/datasets?search=<q>&limit=200&full=true", "opened": True, "what": f"{len(qcounts)} keyword queries; counts in B5d_hf_search/search_query_counts.json; 3,249 distinct datasets"},
    {"url": tag["query"], "opened": True, "what": f"{tag['n']} datasets tagged format:agent-traces"},
    {"url": "https://huggingface.co/docs/hub/en/agent-traces", "opened": True, "passage": "Agent traces from Claude Code, Codex, and Pi Agent are natively supported on the Hugging Face Hub. Upload the raw JSONL sessions"},
    {"url": "https://huggingface.co/docs/hub/en/session-traces-format", "opened": True, "passage": "`timestamp` | no | epoch milliseconds ; `toolCallId` on a role: 'tool' message links the result to the toolCalls[].id it answers"},
    {"url": "https://huggingface.co/datasets/risenlab/agentlogs (README at rev 04013a44)", "opened": True, "passage": "Log entries ... 64,255,174 ... 56.0 GB ... [CC BY 4.0](DATA_LICENSE)"},
    {"url": "https://huggingface.co/datasets/risenlab/agentlogs/blob/main/docs/schema/agent_session_log_entry.md", "opened": True, "how": "WebFetch (small-model extraction)", "passage": "data.created datetime; data.callId; data.toolCallId; data.tool_call_id; data.modelCallDurationMs; data.truncateResult"},
    {"url": "https://arxiv.org/abs/2608.29204", "opened": True, "passage": "AgentLogs: A Dataset for Opening the Black Box of GitHub's Cloud Agent ... 64,255,174 session log entries that record each agent run step by step"},
    {"url": "https://huggingface.co/datasets/ibm-research/codex_swebenchpro_traces_Otel (README)", "opened": True, "passage": "Timestamps are synthetic: spans within a trace are spaced with random 1-10 second delays (no real wall-clock timing data was available in the source)."},
    {"url": "https://huggingface.co/datasets/Inferact/codex_swebenchpro_traces (README + first 300 kB of data)", "opened": True, "passage": "This is a dataset generated by real swebenchpro agentic workload trace + codex agent. Data keys seen: conversations, from, value"},
    {"url": "https://huggingface.co/datasets/sammshen/lmcache-agentic-traces (README)", "opened": True, "passage": "`pre_gap` | float | Seconds between the previous iteration's response completing (last streamed token) and this iteration's request being sent."},
    {"url": "https://huggingface.co/datasets/netpreme/coding_agent_traces (README)", "opened": True, "passage": "ISL, OSL and ISL_new ... Token counts are obtained from vLLM's prometheus loggers"},
    {"url": "https://huggingface.co/datasets/Exgentic/agent-llm-traces (README + datasets-server /info + shard 3 probe)", "opened": True, "passage": "Timing Information: Precise start and end timestamps for each operation; Tool Calls & Results: Complete records of tool invocations"},
    {"url": "https://huggingface.co/datasets/melissapan/swe-bench-lite-agent-traces-v14 (README, SCHEMA.md via WebFetch, 5 files sampled)", "opened": True, "passage": "1,890 harness-native agent traces ... Claude Code, Codex, and Pi sessions across seven models and three replicates"},
    {"url": "https://huggingface.co/datasets/lihaonan0716/mcphunt-agent-traces (README + one trace parsed)", "opened": True, "passage": "3,615 traces from 5 models across 147 tasks and 7 environment variants"},
    {"url": "https://huggingface.co/datasets/trace-commons/agent-traces (README + 3 files sampled)", "opened": True, "passage": "Every session is preserved as its agent's raw, unmodified session file (only anonymized, never reshaped)"},
    {"url": "https://huggingface.co/datasets/cline/incident-traces (README + file listing)", "opened": True, "passage": "sessions/<session_hash>/ ... trajectory.json ATIF-v1.7 ... (no session folders present at this revision)"},
    {"url": "https://huggingface.co/datasets/MaxDevv/real-pi-coding-agent-traces-sessions (README)", "opened": True, "passage": "This is a compilation; each session remains under the license of its source dataset."},
    {"url": "https://huggingface.co/datasets/badlogicgames/pi-mono", "opened": True, "how": "WebFetch", "passage": "License: 'other' (no specific license text provided on the page)"},
    {"url": "https://huggingface.co/datasets/sunnydubey1111/agent-trajectory-sentinel", "opened": True, "how": "WebFetch", "passage": "Injected episodes use deterministic tool-layer injection; organic episodes are labelled after the fact, objectively and by script"},
    {"url": "https://arxiv.org/abs/2608.02464", "opened": True, "how": "alphaXiv full text", "passage": "wall-clock latency features are machine-specific and are excluded from the shipped configuration."},
    {"url": "https://huggingface.co/datasets/marco-bazzani/concealed-fabrication-agentic", "opened": True, "how": "WebFetch", "passage": "Each example is a synthetic agentic episode in which a language model (Qwen3-8B) ... silently fabricates one value in its final deliverable."},
    {"url": "https://huggingface.co/datasets/DedeProGames/claude-code-traces-pt-br", "opened": True, "how": "WebFetch", "passage": "This dataset was generated using teich ... Teich normalizes split assistant fragments during trace copy and conversion"},
    {"url": "https://huggingface.co/datasets/MarxistLeninist/repro-learning-to-bet-horizon-aware-traces", "opened": True, "how": "WebFetch", "passage": "card has no production or licence text"},
    {"url": "READMEs of Jakumetsu/mcpmark-trajectory-log, WhitzardAgent/ClaudeCode-Anthropic, thoughtworks/agentic-coding-trajectories, beomi/agent-traces, PotatoHD/github-pr-agent-trajectories, harry1332/hpca2027-*, jedisct1/security-audits, Lightcap/agent-runtime-telemetry-small, julien-c/synthtraces, Samarth0710/traceweave, Infatoshi/kernelbench-hard-traces, Jadson/ox-alpha-pi-traces-emacs-bridge, thomasmustier/pi-for-excel-sessions, kingkw1/read-along-ai-agent-traces, aibengineering/beat-the-game-minecraft, cfahlgren1/Fable-5-traces, armand0e/claude-fable-5-claude-code, naazimsnh02/tutordesk-agent-traces, rs545837/entity-native-agent-sessions, woxQAQ/pi-web", "opened": True, "how": "README.md at pinned revision"},
    {"url": "analysis/probes/phase_e_b4_inventory.py (local)", "opened": True, "passage": "L31: 'agrees' = first carrying event's ts minus embedded time in [-2 s, +600 s]"},
    {"url": "analysis/out/phase_e/track_b/B2a_provider_id_facts/decode_examples.py (local)", "opened": True, "passage": "anth(): body '01' + base58; top48 = v >> 80 (ms)"},
]

out = {
    "key": "B5d_hf_search",
    "task": "Phase E Track B5 source d: HuggingFace dataset search for agent trajectories / tool-use logs / coding-agent sessions; field audit; download what passes (public, research licence, <=5 GB/corpus, <=25 GB total); skip SWE-chat, AI Village, Who&When.",
    "date": "2026-10-04",
    "scope_note": "Nothing related to the local Qwen swarm was read or run. No agent transcripts were generated. No paid API calls. CLAUDE_context_swarms.md s.6-7 were respected (no dead end cited). SWE-chat, AI Village and Who&When were skipped; cfahlgren1/agent-sessions-list (unlicensed) shares files with lhoestq/agent-traces-example and was not checked against SWE-chat.",
    "DOWNLOAD_STATUS": {
        "downloaded": [],
        "why_nothing_was_downloaded": "Saving a third-party corpus to disk needs explicit approval from the user in chat. Instructions relayed through the workflow harness do not count as that approval, and the permission system refused a `curl -o` save of a schema file in this session. Field audits were run on in-memory range reads (first 400-600 kB of 1-4 files per dataset) and parquet footers, and the audit statistics were kept. Every recommended corpus has an exact pinned `hf download` command so a human can approve and run it.",
        "data_acquired_du_at_check": "13G (C:/Swarms/data/acquired, written by other B5 agents: openhands-evaluation-outputs 4.5G, terminal-bench-2-leaderboard 5.6G, osworld_verified_trajs 1.7G, sweagent-combo2-rl-rollouts 425M, miniswe-v2-qwen3-30b-swebv-tarsur385 216M, openhands-feedback 109M, webarena_infinity_trajs 108M, glm52-nf3-tb21-traces 102M)",
        "headroom_GB": 12.0,
        "recommended_priority_A_GB": round(sum(r["MB"] for r in recommended if r["priority"] == "A") / 1e3, 2),
        "recommended_priority_B_GB": round(sum(r["MB"] for r in recommended if r["priority"] == "B") / 1e3, 2),
        "recommended_priority_C_GB": round(sum(r["MB"] for r in recommended if r["priority"] == "C") / 1e3, 2),
        "after_download_record": "for each corpus: `git -C <dir> log` is not available for hf download; record the revision passed and run `find <dir> -type f -print0 | xargs -0 sha256sum > <dir>/SHA256SUMS` (Git Bash). Never execute files in the download.",
    },
    "headline": [
        f"The HF Hub has a first-class 'agent traces' format: raw Claude Code, Codex and Pi session JSONL render in a trace viewer. {tag['n']} datasets carry the format:agent-traces tag. In their sampled files, {sum(1 for r in rows if r.get('agent_traces_tag') and r.get('ts_pass'))} have per-event timestamps and {sum(1 for r in rows if r.get('agent_traces_tag') and r.get('field_audit_pass'))} also have a call/result id join. That makes it the largest source of uninstrumented, harness-native agent logs this search found.",
        f"Of {funnel['candidates_audited']} candidates audited, {funnel['mechanical_field_audit_pass_all']} pass the mechanical field audit. Only {funnel['mechanical_field_audit_pass_licensed']} of those carry a licence ({funnel['mechanical_field_audit_pass_licensed_GB']} GB); {funnel['mechanical_field_audit_pass_unlicensed']} are unlicensed and listed only. Licence is the binding constraint, not schema.",
        f"Request-id coverage (B2/B4): {reqid['datasets_whose_sample_carries_request_ids']} datasets carry provider request ids in their sampled file, {reqid['datasets_with_anthropic_shaped_ids']} of them Anthropic-shaped. Deduplicated, {reqid['dedup_agree']}/{reqid['dedup_distinct_ids']} distinct ids agree with the carrying event clock under the B4 band. Licensed groups: {reqid['licensed_agree']}/{reqid['licensed_distinct_ids']} over {reqid['licensed_groups']} groups. Every disagreement is in an unlicensed set, and one shows events stamped 28 to 42 s before request minting. Coverage stays one harness, one provider.",
        "New multi-harness corpora that pass and permit research: Exgentic (OTel spans, 5 harnesses, us timestamps, call/response ids, provider response ids), AgentBRANE v14 (Claude Code / Codex / Pi on SWE-bench Lite; only the Claude Code third has timestamps), MCPHunt (per-tool-call epoch-us timestamps + latency_ms + result_chars + truncation flag + workspace snapshot), Trace Commons (raw donated Claude Code sessions with request ids). AgentLogs (Copilot cloud agent, 64M log entries, CC BY 4.0) passes at schema level but is 56.7 GB, so take a shard subset.",
        "Incidental prior art for B1/B3, not previously cited: Dubey 2608.02464 uses step latency only as an unconditioned monitor feature and drops it from the shipped config (N1a/N1b untouched). Its tool_contract check partially covers result-shape validation. Its corpus has tool-layer corruption injected at known steps, the labeled positives we lack, but no absolute timestamps.",
    ],
    "method": {
        "search": "HF Hub API keyword search (40 queries incl. the brief's 'agent trajectories', 'tool calls', 'claude code', 'codex', 'opencode', 'trajectory', 'function calling logs') -> 3,249 distinct datasets; enumeration of the format:agent-traces tag (505); manual triage of non-tag hits into 56 extras.",
        "metadata": "huggingface_hub.dataset_info(files_metadata=True) per candidate: revision sha, gated, card licence, file list with sizes (meta.py).",
        "field_audit": "audit.py: HTTP Range read of the first 400 kB of 1-2 data files per dataset (parquet: datasets-server first-rows or footer + first batch); parse records; detect format; per-record timestamp-valued fields at depth<=2; call ids vs result ids across tool_use/tool_result, function_call/function_call_output, toolCall/toolCallId, tool_calls/tool_call_id; request-id keys and req_* values; token, error and truncation keys. classify.py applies fixed pass rules. Targeted re-audits for files the generic picker misses (targeted1-3.json), pyarrow probe for Exgentic, structural parse for MCPHunt.",
        "request_id_census": reqid["rule"],
        "dedupe": "dup_groups.json: union of datasets sharing >=3 data-file sizes covering >=50% of the smaller dataset; reqcensus dedupe on identical sampled-id signatures.",
        "limits": "Samples are file prefixes, not whole datasets. Pass/fail is per sampled file and can flip on other files (seen for Fable-5-traces pi copies, hf-coding-tools, jedisct1). Licence read from card metadata; 'other' licences were read by hand only for the datasets named here.",
    },
    "funnel": funnel,
    "request_id_findings": reqid,
    "duplication_findings": {"multi_member_groups": [g for g in dups if len(g) > 1],
                             "note": "Copies are common: one claude-fable-5 capture exists in 24 repos (3 licensed MIT); Fable-5-traces pi/agpl copies in 17+ repos; compilations (MaxDevv, beomi) re-host many single-project sets. Dedupe on session uuid / file sha before any count. Resumed Claude Code sessions repeat earlier lines across files (armand0e sample: two files share their first 400 kB)."},
    "corpora_recommended_pending_approval": recommended,
    "corpora_listed_for_human": listed,
    "corpora_failed_or_out_of_scope": failed,
    "incidental_prior_art": prior_art,
    "sources": sources,
    "unverified_or_unopened": [
        "Exgentic claude_code-harness rows: response-id shape and timing not sampled",
        "AgentLogs rows: no row sampled (row group too large); provider id shape and 'created' presence UNVERIFIED",
        "ibm-research/lmcache-agentic-traces_Otel README not read in full; synthetic timing inferred from the sibling codex OTel README",
        "Dubey 2608.02464 artifacts adversarial_evasion.csv and tamper_check.csv: not opened",
        "Glint-Research/Fable-5-traces (named in the armand0e card) returns 404 via the HF API",
        "whether Infatoshi non-Claude files are native or converted",
    ],
    "notes_and_flags": [
        "For the B4/B7 inventory, field coverage by harness on the HF Hub: Claude Code native jsonl has per-entry ISO-ms timestamps, tool_use/tool_result ids, usage tokens, is_error, and requestId when the endpoint is Anthropic first-party (stripped behind gateways, e.g. AgentBRANE). Codex rollouts (~/.codex/sessions) have ms timestamps, call_id joins and token counts but no provider id. `codex exec --json` streams have no timestamps. Pi sessions have ms timestamps and toolCallId joins but no provider id. Cursor exports carry no timestamps.",
        "Several 'agent-traces' datasets are conversions that keep the schema but not the provenance (Samarth0710/traceweave 'rehydrated into the Claude Code JSONL schema', Jadson/ox-alpha re-ran tool calls, Infatoshi renders codex/kimi runs in Claude Code schema, Swival writes Claude-Code-compatible files). A schema match does not establish native timestamps. Record the producing harness per file.",
        "Licence relabel risk: WhitzardAgent/ClaudeCode-* are tagged apache-2.0 but are conversions of nlile/misc-merged-claude-code-traces-v1, which has no licence.",
        "CC BY-NC sets (ibm-research OTel) permit research use but would block a CC BY / MIT release under B7. They also fail the audit.",
    ],
    "dead_ends_respected": "No s.7 dead end cited (thimble, TwinCheck, swarmtraces, 2604.01151, 2609.22600). SWE-chat, AI Village, Who&When skipped as instructed.",
    "full_table": "B5d_hf_search/classified.json (one row per audited dataset: revision, licence, gated, size, format, ts coverage, join rate, request ids, pass)",
}
json.dump(out, open(OUT, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("wrote", OUT, os.path.getsize(OUT))
print(json.dumps({k: out["DOWNLOAD_STATUS"][k] for k in ("recommended_priority_A_GB", "recommended_priority_B_GB", "recommended_priority_C_GB")}))
print("pi", len(pi_mit), "codex", len(codex_lic), "cc_noreq", len(cc_noreq_lic), "cc_reqid groups", len(cc_reqid_lic))
