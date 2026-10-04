"""Phase A6: unused fields and parser surprises.

Cross-references the raw-field census (analysis/out/phase_a/a6_raw_census.json, made from raw data by
phase_a6_raw_census.py) with what the IR captures NOW (ir.COLUMNS plus every `extra` key in the Phase A caches),
compiles the parser surprises recorded in the build / review reports, and inventories the non-tool entry types the
loaders skip.

Run from the worktree root:
  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_a_a6

Reads (read-only): analysis/cache/<corpus>_A.parquet for the five corpora (Phase A split ONLY; *_B.parquet is never
opened), analysis/cache/swechat_population.parquet (session -> format), analysis/cache/whowhen_labels.json (key names
only), analysis/out/phase_a/a6_raw_census.json, analysis/out/build/*.json.
Writes RAW COUNTS ONLY to analysis/out/phase_a/a6.json. Interpretation: analysis/notes/phase_a_a6.md.
All rules and thresholds are in RULES and were fixed before the outputs were computed.
"""
import collections
import json
import re
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from analysis.lib import stats
from analysis.lib.ir import COLUMNS

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "analysis" / "cache"
BUILD = ROOT / "analysis" / "out" / "build"
CENSUS = ROOT / "analysis" / "out" / "phase_a" / "a6_raw_census.json"
OUT = ROOT / "analysis" / "out" / "phase_a" / "a6.json"
CORPORA = ["swechat", "cc_local", "aiv_cc", "aiv_cu", "whowhen"]
KINDS = ["user", "system", "assistant", "call", "result", "meta"]
CLASSES = ["TIMER", "CLOCK", "COUNTER", "HASH_ID", "STATUS", "TOKEN"]

EXTRA_DEPTH = 5          # dict levels walked inside `extra` (lists do not add depth)
LIST_CAP = 50            # elements walked per list inside `extra`
RARE_EXPECTED_MIN = 3.0  # see RULES["status"]["uncaptured"]
GENERIC_LEAVES = {"id", "type", "name", "index", "status", "code", "error", "value", "count", "key", "kind", "state"}
STRIP_PREFIXES = ["payload.", "data.", "toolUseResult.", "tool_use_result.", "state.metadata.", "state.", "attachment.",
                  "info.", "content.", "agent_messages.", "message."]

RULES = {
    "data": "Phase A caches only (analysis/cache/<corpus>_A.parquet). Raw-data facts come from the existing census "
            "(a6_raw_census.json) and the build/review reports; no raw file is opened by this script.",
    "ir_inventory": {
        "columns": "fill = non-null rows / rows, per corpus x kind (swechat also per format x kind); CI = "
                   "lib.stats.cluster_rate with the session as unit.",
        "extra": f"every key path inside the `extra` JSON (dict levels <= {EXTRA_DEPTH}, first {LIST_CAP} list "
                 "elements, list levels written '[]'); fill = rows whose extra contains the path / rows of the cell; "
                 "CI = cluster_rate by session. Cells: corpus x kind, and corpus x slice (slice = the IR rows that "
                 "correspond to one raw entry group, see slice_rules).",
    },
    "slice_rules": "Each IR row gets tags naming the raw entry group(s) it came from, derived from kind, tool_raw, "
                   "is_subagent/parent_call_id and the loader's own discriminators in extra (entry_type, type, subtype, "
                   "attachment_type, part_type, message_type, operation, journal_type). The mapping is written from "
                   "the loader docstrings/code (function row_tags) before any outcome was computed. A census group "
                   "maps to the rows carrying its tag. cc_local tags carry 'main:'/'subagent:' prefixes (census "
                   "convention); swechat Claude Code subagent rows nested in agent_progress carry 'nested:' tags plus "
                   "'progress/agent_progress'.",
    "census_scope": "census `flagged[]` entries whose source is ingested into the IR: swechat_transcripts/<format>, "
                    "cc_local/claude_code, ai_village/claude_code_messages (+ /content_as_cc), "
                    "ai_village/computer_use_turns, who_and_when. Fill rates are the census's own (raw data, census "
                    "sample and unit, CI as stored by the census).",
    "status": {
        "order": "first matching test wins: (1) explicit rule in CAPTURE_RULES; (2) census captured mark "
                 "(cc_jsonl / ir_column:*); (3) name match against the slice's extra paths; (4) declared skip; "
                 "(5) slice absent from A; (6) expected-count test.",
        "captured_column": "rule maps the raw path to an IR column and that column is non-null in >= 1 row of the "
                           "slice (verify_scope 'slice'); for rules marked '@joined' (the value is written on another "
                           "row, e.g. Codex exec_command_end exit_code -> the result row) also the corpus/format "
                           "(verify_scope 'format_joined'); when the slice has no row in A, the corpus/format "
                           "(verify_scope 'format_slice_absent').",
        "captured_extra_renamed": "rule maps the raw path to an extra path (renamed by the loader) present in the "
                                  "slice (or corpus/format, verify_scope as above).",
        "inside_args_or_text_json": "rule says the raw field sits inside a JSON string the IR keeps whole (`args` = "
                                    "call input, `text` = model-visible result); present in IR but not as a field.",
        "label_store": "Who&When ground-truth fields: kept out of the IR by design, in analysis/cache/whowhen_labels.json.",
        "omitted_by_loader": "loader docstring says the field is deliberately not emitted.",
        "not_captured_by_rule": "explicit rule target 'none': the field is known not to be copied (e.g. Codex "
                                "last_token_usage.total_tokens, whose leaf would otherwise name-match "
                                "extra.total_token_usage.total_tokens; nested Claude Code toolUseResult keys); the census "
                                "mark and name matching are skipped and the status comes from tests (4)-(6). Flag "
                                "`not_captured_by_rule` = true on the entry.",
        "rule_target_unverified": "rule names an IR target but the target is null/absent in the A cache for that "
                                  "corpus/format.",
        "captured_census_mark": "census marked it captured (cc_jsonl path list or IR-column semantic key).",
        "captured_extra_leaf": "leaf key (generic leaves: the full path after stripping one of STRIP_PREFIXES) "
                               "occurs among the slice's extra paths. Name-level match; can be a false positive.",
        "not_emitted": "the raw entry group is skipped by the loader (declared in DECLARED_SKIP from the loader "
                       "docstrings/code), so none of its fields reach the IR.",
        "slice_absent_in_A": "the loader emits the group but no row of it is in the A sample: cannot be checked here.",
        "uncaptured": f"slice has rows in A, no test matched and expected = census fill rate x slice rows in A >= "
                      f"{RARE_EXPECTED_MIN}. Reason for {RARE_EXPECTED_MIN}: P(0 occurrences | Poisson mean 3) = "
                      "0.050, so absence at that expectation is evidence (~5% level) that the IR drops the field "
                      "rather than that the A sample lacks it.",
        "inconclusive_rare": f"as uncaptured but expected < {RARE_EXPECTED_MIN}.",
    },
    "candidate_lists": {
        "not_in_ir": "statuses not_emitted, uncaptured, inconclusive_rare, slice_absent_in_A, "
                     "rule_target_unverified",
        "inside_args_or_text": "status inside_args_or_text_json",
        "tags": {
            "mcp_structured_content": "path contains 'mcpMeta.structuredContent' (MCP server-defined payload)",
            "model_authored_input": "path inside a call input (message.content[].input, arguments, args, toolArgs, "
                                    "agent_action, state.input, toolRequests[].arguments, invocation.arguments, "
                                    "content[].input)",
            "entry_session_id": "leaf sessionId / session_id on a Claude Code / Agent SDK entry",
            "label": "Who&When ground-truth field",
            "census_classifier_artifact": "paths the census lists as known false flags (its section 1.5): tabId, "
                                          "writtenAtMs, VSCode_Expert, success_time, repo_github_metadata.id, "
                                          "template_repository.id",
            "harness_measured": "none of the tags above",
        },
    },
    "aiv_cu_population_crosscheck": "for aiv_cu census paths under agent_messages, the full-population occurrence "
                                    "count from out/build/aiv_cu_pass1_stats.json agent_messages_key_paths (all "
                                    "2,510,487 turns) by API shape; rate = occurrences / turns of that shape "
                                    "(aiv_cu_build population.turns_by_shape), given only for paths without list "
                                    "levels (list paths count elements, not rows). Row unit, no session CI (the "
                                    "pass-1 stats carry no session ids).",
    "aiv_cu_pass1_extra_paths": "pass-1 key paths not in the census (the census saw only the first 20,000 rows) whose "
                                "leaf words hit the census word sets (census meta.rules.class_rules.word_sets) are "
                                "added with class_evidence 'name_only' (no value-type evidence available); container "
                                "paths (a dict/list whose children are listed) are skipped.",
    "aiv_cu_shape_slices": "aiv_cu rows are also tagged computer_use_turns/<API shape> (shape from stratum, "
                           "AIVCU_SHAPE_OF_STRATUM); a census aiv_cu path is checked against the slice of the shape its "
                           "prefix belongs to (AIVCU_SHAPE_OF_PATH), row-level fields against all rows.",
    "parser_surprises": "items are written by hand from reading the build/review reports (every report key whose "
                        "name or value records an unexpected raw-data shape, an ordering/id/flag inconsistency, or a "
                        "loader-review finding); each item's numbers are READ by this script from the cited "
                        "file + key path at run time (value 'MISSING' if the path does not resolve). Items that the "
                        "same fact supports in several reports are merged into one item with several evidence "
                        "entries; `same_fact` lists evidence names that must be equal and `consistent` records "
                        "whether they are.",
    "non_tool_inventory": "census non_tool_entry_inventory groups (raw data, full populations except the AI Village "
                          "head) with census kind != 'tool', plus build-report counters; disposition = skipped "
                          "(DECLARED_SKIP) or emitted; A rows = IR rows in A carrying the group's tag. Flag "
                          "'emitted_but_absent_in_A' when disposition is emitted, A rows = 0 and expected A rows = "
                          f"records x (A sessions / population sessions of that format) >= {RARE_EXPECTED_MIN}.",
}

# ------------------------------------------------------------------------------------------------- slice tagging

def row_tags(corpus, fmt, kind, d, tool_raw, is_sub, parent_call_id, stratum):
    """Raw entry-group tags for one IR row (census group naming). Written from the loader docstrings/code."""
    et = d.get("entry_type")
    if fmt == "claude_code":
        base = []
        if kind in ("assistant", "call") or et == "assistant_thinking_only":
            base.append("assistant")
        elif kind == "result":
            base += ["user/tool_result", f"toolUseResult/{tool_raw}" if tool_raw else "toolUseResult/unresolved"]
        elif et == "progress":
            base.append(f"progress/{d.get('type')}")
        elif et == "system":
            base.append(f"system/{d.get('subtype')}")
        elif et == "attachment":
            base.append(f"attachment/{d.get('attachment_type')}")
        elif et == "result":
            base.append(f"result/{d.get('subtype')}")
        elif et == "queue-operation":
            base.append(f"queue-operation/{d.get('operation')}")
        elif et == "workflow_journal":
            jt = d.get("journal_type")
            base.append("result/None" if jt == "result" else str(jt))
        elif et in ("frame-link", "file-history-delta"):
            base.append(et)
        elif kind in ("user", "system") and et is None:
            base.append("user/text")
        else:
            base.append(f"<unmapped:{kind}:{et}>")
        if corpus == "cc_local":
            return [("subagent:" if is_sub else "main:") + b for b in base]
        if corpus == "swechat" and is_sub and parent_call_id:
            tags = ["nested:" + b for b in base] + ["progress/agent_progress"]
            tags += [b for b in base if b.startswith("toolUseResult/")]
            return tags
        if corpus == "aiv_cc":
            return base + ["claude_code_messages"]
        return base
    if fmt == "codex":
        tags = []
        if kind == "call":
            tags.append("response_item/web_search_call" if d.get("server_tool") else
                        "response_item/custom_tool_call" if d.get("custom_tool") else "response_item/function_call")
        elif kind == "result":
            tags += ["response_item/function_call_output", "response_item/custom_tool_call_output"]
        elif kind in ("assistant", "user") or (kind == "system" and et is None):
            tags.append("response_item/message")
        elif et == "event_msg":
            tags.append(f"event_msg/{d.get('type')}")
        elif et == "response_item":
            tags.append(f"response_item/{d.get('type')}")
        elif et in ("session_meta", "turn_context", "compacted"):
            tags.append(et)
        if kind in ("assistant", "call") and d.get("thinking_chars"):
            tags.append("response_item/reasoning")
        return tags
    if fmt == "opencode":
        tags = []
        pt = d.get("part_type")
        if kind in ("call", "result"):
            tags.append(f"part/tool/{tool_raw}")
        if kind == "meta" and pt:
            tags.append(f"part/{pt}")
        if kind in ("assistant", "user", "system"):
            tags.append("part/text")
        if d.get("thinking_chars"):
            tags.append("part/reasoning")
        if kind in ("assistant", "call") or (kind == "meta" and (pt == "step-finish" or "message_error" in d)):
            tags.append("message_info/assistant")
        if kind in ("user", "system"):
            tags.append("message_info/user")
        return tags
    if fmt == "gemini":
        tags = []
        if kind in ("assistant", "call", "result"):
            tags.append("message/gemini")
        if kind in ("call", "result"):
            tags.append(f"toolCall/{tool_raw}")
        if kind == "user":
            tags.append("message/user")
        if kind == "meta":
            tags.append(f"message/{d.get('message_type')}")
        return tags
    if fmt == "copilot":
        if kind in ("assistant", "call"):
            return ["line/assistant.message"]
        if kind == "result":
            return ["line/tool.execution_complete"]
        if kind == "user":
            return ["line/user.message"]
        if et:
            return [f"line/{et}"]
        return []
    if fmt in ("cursor", "simple_text"):
        return ["line/assistant"] if kind in ("assistant", "call") else ["line/user"] if kind == "user" else []
    if corpus == "aiv_cu":
        return ["computer_use_turns", f"computer_use_turns/{AIVCU_SHAPE_OF_STRATUM.get(stratum, 'unknown')}"]
    if corpus == "whowhen":
        return [f"json/{stratum}", f"parquet/{stratum}"]
    return []


# aiv_cu stratum -> agent_messages API shape (load_aiv_cu docstring: stratum is a provider/model family; the OpenAI split
# is by API shape; compat-chat models use the chat shape; anthropic-claude-code rows use the Agent-SDK shape)
AIVCU_SHAPE_OF_STRATUM = {"anthropic-claude-code": "anthropic-sdk", "anthropic-opus": "anthropic",
                          "anthropic-sonnet": "anthropic", "anthropic-haiku": "anthropic", "anthropic-fable": "anthropic",
                          "gemini-pro": "gemini", "gemini-flash": "gemini", "openai-responses": "openai-responses",
                          "openai-chat": "openai-chat", "compat-chat": "openai-chat"}
# raw path prefix -> shape, for census aiv_cu paths (first match wins; no match = row-level field, all shapes)
AIVCU_SHAPE_OF_PATH = [(r"^agent_messages\[\]", "openai-responses"),
                       (r"^agent_messages\.(textMessage|thinkingMessage|_sdkFormat)", "anthropic-sdk"),
                       (r"^agent_messages\.(candidates|usageMetadata|responseId|modelVersion|sdkHttpResponse)", "gemini"),
                       (r"^agent_messages\.(tool_calls|reasoning_details|reasoning_content|reasoning|refusal|annotations)",
                        "openai-chat"),
                       (r"^agent_messages\.", "anthropic")]


def aivcu_shape_of_path(path):
    for rx, shape in AIVCU_SHAPE_OF_PATH:
        if re.search(rx, path):
            return shape
    return None


def corpus_format(corpus, fmt_by_session, sid):
    if corpus == "swechat":
        return fmt_by_session.get(sid, "unknown")
    return {"cc_local": "claude_code", "aiv_cc": "claude_code", "aiv_cu": "aiv_cu", "whowhen": "whowhen"}[corpus]


# Raw entry groups the loaders skip (no IR row), from the loader docstrings/code.
DECLARED_SKIP = {
    ("swechat", "claude_code"): r"^(file-history-snapshot|queue-operation/.*|last-prompt|pr-link|permission-mode|summary|"
                                r"custom-title|agent-name|ai-title)$",
    ("cc_local", "claude_code"): r"^(main|subagent):(agent-name|ai-title|artifact-.*|atis-latch|bridge-session|"
                                 r"cost-state|custom-title|file-history-snapshot|last-prompt|mode)$",
    ("swechat", "opencode"): r"^session$",
    ("swechat", "gemini"): r"^session$",
}
SKIP_SOURCE = {
    ("swechat", "claude_code"): "lib/cc_jsonl.py Parser.feed: types other than progress/assistant/user/system/"
                                "attachment(with timestamp)/result are skipped",
    ("cc_local", "claude_code"): "load_cc_local docstring: entry types without a timestamp are dropped and counted "
                                 "(build loader_counters dropped_untimestamped:*)",
    ("swechat", "opencode"): "document-level info object: no IR row (feeds session-level subagent linkage)",
    ("swechat", "gemini"): "document-level session object: no IR row",
}

# ------------------------------------------------------------------------------------------------- capture rules
# (corpus or '*', format or '*', group regex, path regex, target). target: column:<c> | extra:<path> | args | text |
# label_store | omitted | none. Paths of the census group ai_village/claude_code_messages are matched with their
# leading 'content.' removed. Written from the loader docstrings/code.
_SW = "swechat"
CAPTURE_RULES = [
    # Claude Code (lib/cc_jsonl.py, lib/cc_attach.py, load_cc_local, load_aiv_cc)
    ("*", "claude_code", r".*", r"^message\.content\[\]\.input(\.|$)", "args"),
    ("*", "claude_code", r"^(main:|subagent:)?attachment/", r"^attachment\.type$", "extra:attachment_type"),
    ("*", "claude_code", r"^(main:|subagent:)?attachment/", r"^attachment\.commandMode$", "extra:command_mode"),
    ("*", "claude_code", r"^(main:|subagent:)?attachment/", r"^renderedRole$", "extra:rendered_role"),
    ("*", "claude_code", r".*", r"^(sessionId|session_id)$", "none"),
    # cc_jsonl copies only top-level toolUseResult keys (plus `usage` -> extra.subagent_usage): nested keys are not captured
    ("*", "claude_code", r"(^|:)user/tool_result$", r"^(toolUseResult|tool_use_result)\.(?!usage\.)[^.\[]+(\[\])?\.", "none"),
    ("*", "claude_code", r"(^|:)toolUseResult/", r"^(?!usage\.)[^.\[]+(\[\])?\.", "none"),
    ("aiv_cc", "claude_code", r"^assistant$", r"^error$", "extra:sdk_error"),
    ("aiv_cc", "claude_code", r"^system/init$", r"^tools$", "extra:n_tools"),
    ("aiv_cc", "claude_code", r"^claude_code_messages$", r"^sdk_session_id$", "column:session_id"),
    ("aiv_cc", "claude_code", r"^claude_code_messages$", r"^created_at$", "column:ts"),
    ("aiv_cc", "claude_code", r"^claude_code_messages$", r"^(id|agent_id|message_uuid)$", "none"),
    # Codex (load_swechat parse_codex)
    (_SW, "codex", r".*", r"^timestamp$", "column:ts"),
    (_SW, "codex", r"^event_msg/(exec_command_end|mcp_tool_call_end)$", r"^payload\.duration\.(secs|nanos)$", "extra:duration_s"),
    (_SW, "codex", r"^event_msg/exec_command_end$", r"^payload\.exit_code$", "column:exit_code@joined"),
    (_SW, "codex", r"^event_msg/exec_command_end$", r"^payload\.stderr$", "column:stderr@joined"),
    (_SW, "codex", r"^event_msg/(.*_end|view_image_tool_call)$", r"^payload\.call_id$", "column:parent_call_id"),
    (_SW, "codex", r"^event_msg/mcp_tool_call_end$", r"^payload\.invocation\.server$", "extra:server"),
    (_SW, "codex", r"^event_msg/mcp_tool_call_end$", r"^payload\.invocation\.tool$", "extra:mcp_tool"),
    (_SW, "codex", r"^event_msg/mcp_tool_call_end$", r"^payload\.result\.(Ok\.isError|Err)", "column:native_error@joined"),
    (_SW, "codex", r"^event_msg/token_count$", r"^payload\.info\.last_token_usage\.input_tokens$", "column:usage_in"),
    (_SW, "codex", r"^event_msg/token_count$", r"^payload\.info\.last_token_usage\.output_tokens$", "column:usage_out"),
    (_SW, "codex", r"^event_msg/token_count$", r"^payload\.info\.last_token_usage\.cached_input_tokens$", "column:usage_cache_read"),
    (_SW, "codex", r"^event_msg/token_count$", r"^payload\.info\.last_token_usage\.reasoning_output_tokens$", "extra:reasoning_output_tokens"),
    (_SW, "codex", r"^event_msg/token_count$", r"^payload\.info\.last_token_usage\.total_tokens$", "none"),
    (_SW, "codex", r"^event_msg/token_count$", r"^payload\.info\.total_token_usage\.(\w+)$", r"extra:total_token_usage.\1"),
    (_SW, "codex", r"^response_item/(function_call|custom_tool_call|web_search_call|tool_search_call)$", r"^payload\.call_id$", "column:call_id"),
    (_SW, "codex", r"^response_item/(function_call|custom_tool_call)$", r"^payload\.(arguments|input)", "args"),
    (_SW, "codex", r"^response_item/(function_call|custom_tool_call)_output$", r"^payload\.call_id$", "column:call_id"),
    (_SW, "codex", r"^response_item/(function_call|custom_tool_call)_output$", r"^payload\.output", "text"),
    (_SW, "codex", r"^turn_context$", r"^payload\.sandbox_policy\.type$", "extra:sandbox"),
    (_SW, "codex", r"^response_item/ghost_snapshot$|^compacted$", r"ghost_commit\.", "none"),
    # OpenCode (load_swechat parse_opencode)
    (_SW, "opencode", r"^part/tool/", r"^callID$", "column:call_id"),
    (_SW, "opencode", r"^part/tool/", r"^state\.time\.(start|end)$", "column:ts"),
    (_SW, "opencode", r"^part/tool/", r"^state\.time\.compacted$", "extra:compacted_at"),
    (_SW, "opencode", r"^part/tool/", r"^state\.input(\.|$)", "args"),
    (_SW, "opencode", r"^part/tool/", r"^state\.(output|error)$", "text"),
    (_SW, "opencode", r"^part/tool/", r"^state\.metadata\.exit$", "column:exit_code"),
    (_SW, "opencode", r"^part/tool/", r"^state\.status$", "extra:status"),
    (_SW, "opencode", r"^part/", r"^id$", "column:uuid"),
    (_SW, "opencode", r"^part/", r"^sessionID$", "column:session_id"),
    (_SW, "opencode", r"^part/(tool/.*|text|step-finish|reasoning)$", r"^messageID$", "column:api_msg_id"),
    (_SW, "opencode", r"^part/text$", r"^time\.start$", "column:ts"),
    (_SW, "opencode", r"^part/(text|reasoning)$", r"^time\.(start|end)$", "none"),
    (_SW, "opencode", r"^part/step-finish$", r"^tokens\.input$", "column:usage_in"),
    (_SW, "opencode", r"^part/step-finish$", r"^tokens\.output$", "column:usage_out"),
    (_SW, "opencode", r"^part/step-finish$", r"^tokens\.cache\.read$", "column:usage_cache_read"),
    (_SW, "opencode", r"^part/step-finish$", r"^tokens\.cache\.write$", "column:usage_cache_create"),
    (_SW, "opencode", r"^part/step-finish$", r"^tokens\.reasoning$", "extra:reasoning_tokens"),
    (_SW, "opencode", r"^part/step-finish$", r"^tokens\.total$", "none"),
    (_SW, "opencode", r"^part/(step-start|step-finish)$", r"^snapshot$", "none"),
    (_SW, "opencode", r"^message_info/assistant$", r"^info\.id$", "column:api_msg_id"),
    (_SW, "opencode", r"^message_info/assistant$", r"^info\.modelID$", "column:model"),
    (_SW, "opencode", r"^message_info/(assistant|user)$", r"^info\.sessionID$", "column:session_id"),
    (_SW, "opencode", r"^message_info/(assistant|user)$", r"^info\.time\.created$", "column:ts"),
    (_SW, "opencode", r"^message_info/assistant$", r"^info\.tokens\.input$", "column:usage_in"),
    (_SW, "opencode", r"^message_info/assistant$", r"^info\.tokens\.output$", "column:usage_out"),
    (_SW, "opencode", r"^message_info/assistant$", r"^info\.tokens\.cache\.read$", "column:usage_cache_read"),
    (_SW, "opencode", r"^message_info/assistant$", r"^info\.tokens\.cache\.write$", "column:usage_cache_create"),
    (_SW, "opencode", r"^message_info/assistant$", r"^info\.tokens\.reasoning$", "extra:reasoning_tokens"),
    (_SW, "opencode", r"^message_info/assistant$", r"^info\.tokens\.total$", "none"),
    (_SW, "opencode", r"^message_info/assistant$", r"^info\.cost$", "extra:cost"),
    (_SW, "opencode", r"^message_info/assistant$", r"^info\.error", "extra:message_error"),
    (_SW, "opencode", r"^message_info/assistant$", r"^info\.(time\.completed|finish|providerID|parentID)$", "none"),
    (_SW, "opencode", r"^session$", r"^info\.id$", "column:session_id"),
    # Gemini (load_swechat parse_gemini)
    (_SW, "gemini", r"^message/gemini$", r"^id$", "column:api_msg_id"),
    (_SW, "gemini", r"^message/(user|info|warning|error)$", r"^id$", "column:uuid"),
    (_SW, "gemini", r"^message/", r"^timestamp$", "column:ts"),
    (_SW, "gemini", r"^message/gemini$", r"^tokens\.input$", "column:usage_in"),
    (_SW, "gemini", r"^message/gemini$", r"^tokens\.output$", "column:usage_out"),
    (_SW, "gemini", r"^message/gemini$", r"^tokens\.cached$", "column:usage_cache_read"),
    (_SW, "gemini", r"^message/gemini$", r"^tokens\.(thoughts|tool|total)$", "none"),
    (_SW, "gemini", r"^message/gemini$", r"^model$", "column:model"),
    (_SW, "gemini", r"^message/gemini$", r"^toolCalls\[\]\.id$", "column:call_id"),
    (_SW, "gemini", r"^message/gemini$", r"^toolCalls\[\]\.status$", "extra:status"),
    (_SW, "gemini", r"^message/gemini$", r"^toolCalls\[\]\.timestamp$", "column:ts"),
    (_SW, "gemini", r"^message/gemini$", r"^toolCalls\[\]\.args(\.|$)", "args"),
    (_SW, "gemini", r"^message/gemini$", r"^toolCalls\[\]\.result\[\]\.functionResponse\.response\.(output|error)", "text"),
    (_SW, "gemini", r"^toolCall/", r"^id$", "column:call_id"),
    (_SW, "gemini", r"^toolCall/", r"^status$", "extra:status"),
    (_SW, "gemini", r"^toolCall/", r"^timestamp$", "column:ts"),
    (_SW, "gemini", r"^toolCall/", r"^args(\.|$)", "args"),
    (_SW, "gemini", r"^toolCall/", r"^result\[\]\.functionResponse\.response\.(output|error)", "text"),
    (_SW, "gemini", r"^message/(info|warning|error)$", r"^type$", "extra:message_type"),
    (_SW, "gemini", r"^session$", r"^sessionId$", "column:session_id"),
    # Copilot (load_swechat parse_copilot)
    (_SW, "copilot", r".*", r"^id$", "column:uuid"),
    (_SW, "copilot", r".*", r"^parentId$", "column:parent_uuid"),
    (_SW, "copilot", r".*", r"^timestamp$", "column:ts"),
    (_SW, "copilot", r"^line/assistant\.message$", r"^data\.messageId$", "column:api_msg_id"),
    (_SW, "copilot", r"^line/assistant\.message$", r"^data\.outputTokens$", "column:usage_out"),
    (_SW, "copilot", r"^line/assistant\.message$", r"^data\.toolRequests\[\]\.toolCallId$", "column:call_id"),
    (_SW, "copilot", r"^line/assistant\.message$", r"^data\.toolRequests\[\]\.arguments(\.|$)", "args"),
    (_SW, "copilot", r"^line/tool\.execution_complete$", r"^data\.toolCallId$", "column:call_id"),
    (_SW, "copilot", r"^line/tool\.execution_complete$", r"^data\.success$", "column:native_error"),
    (_SW, "copilot", r"^line/tool\.execution_complete$", r"^data\.error\.code$", "extra:error_code"),
    (_SW, "copilot", r"^line/tool\.execution_complete$", r"^data\.error$", "text"),
    (_SW, "copilot", r"^line/tool\.execution_start$", r"^data\.toolCallId$", "column:parent_call_id"),
    # Cursor / simple_text
    (_SW, "cursor", r"^line/assistant$", r"^message\.content\[\]\.input(\.|$)", "args"),
    (_SW, "simple_text", r".*", r"^timestamp$", "column:ts"),
    # AI Village computer_use_turns (load_aiv_cu)
    ("aiv_cu", "*", r".*", r"^id$", "column:uuid"),
    ("aiv_cu", "*", r".*", r"^session_id$", "column:session_id"),
    ("aiv_cu", "*", r".*", r"^created_at$", "column:ts"),
    ("aiv_cu", "*", r".*", r"^error$", "column:stderr"),
    ("aiv_cu", "*", r".*", r"^output$", "text"),
    ("aiv_cu", "*", r".*", r"^agent_action(\.|$)", "args"),
    ("aiv_cu", "*", r".*", r"^agent_messages\.(id|responseId)$", "column:api_msg_id"),
    ("aiv_cu", "*", r".*", r"^agent_messages\.(modelVersion|model)$", "column:model"),
    ("aiv_cu", "*", r".*", r"^agent_messages\[\]\.id$", "extra:item_id"),
    ("aiv_cu", "*", r".*", r"^agent_messages\[\]\.call_id$", "column:call_id"),
    ("aiv_cu", "*", r".*", r"^agent_messages\.content\[\]\.id$", "column:call_id"),
    ("aiv_cu", "*", r".*", r"^agent_messages\.tool_calls\[\]\.id$", "column:call_id"),
    ("aiv_cu", "*", r".*", r"^agent_messages\.candidates\[\]\.content\.parts\[\]\.functionCall\.id$", "column:call_id"),
    ("aiv_cu", "*", r".*", r"^agent_messages\.textMessage\.message\.id$", "column:api_msg_id"),
    ("aiv_cu", "*", r".*", r"^agent_messages\.thinkingMessage\.message\.id$", "extra:sdk.other.id"),
    ("aiv_cu", "*", r".*", r"^agent_messages\.(textMessage|thinkingMessage)\.session_id$", "extra:meta.sdk_session_id"),
    ("aiv_cu", "*", r".*", r"^agent_messages\.(textMessage|thinkingMessage)\.uuid$", "none"),
    ("aiv_cu", "*", r".*", r"^agent_messages\.usageMetadata\.promptTokenCount$", "column:usage_in"),
    ("aiv_cu", "*", r".*", r"^agent_messages\.usageMetadata\.candidatesTokenCount$", "column:usage_out"),
    ("aiv_cu", "*", r".*", r"^agent_messages\.usageMetadata\.cachedContentTokenCount$", "column:usage_cache_read"),
    ("aiv_cu", "*", r".*", r"^agent_messages\.usageMetadata\.(thoughtsTokenCount|totalTokenCount|serviceTier)$", r"extra:usage_detail.\1"),
    ("aiv_cu", "*", r".*", r"^agent_messages\.usageMetadata\.(promptTokensDetails|cacheTokensDetails)\[\]\.", r"extra:usage_detail.\1"),
    ("aiv_cu", "*", r".*", r"^agent_messages\.candidates\[\]\.finishReason$", "extra:meta.finish_reason"),
    ("aiv_cu", "*", r".*", r"^agent_messages\.stop_reason$", "extra:meta.stop_reason"),
    ("aiv_cu", "*", r".*", r"^agent_messages(\.textMessage\.message|\.thinkingMessage\.message)?\.usage\.(input_tokens)$", "column:usage_in"),
    ("aiv_cu", "*", r".*", r"^agent_messages(\.textMessage\.message|\.thinkingMessage\.message)?\.usage\.(output_tokens)$", "column:usage_out"),
    ("aiv_cu", "*", r".*", r"^agent_messages(\.textMessage\.message|\.thinkingMessage\.message)?\.usage\.cache_read_input_tokens$", "column:usage_cache_read"),
    ("aiv_cu", "*", r".*", r"^agent_messages(\.textMessage\.message|\.thinkingMessage\.message)?\.usage\.cache_creation_input_tokens$", "column:usage_cache_create"),
    ("aiv_cu", "*", r".*", r"^agent_messages(\.textMessage\.message|\.thinkingMessage\.message)?\.usage\.(cache_creation\.\w+|output_tokens_details\.\w+|service_tier|inference_geo)$", r"extra:usage_detail.\2"),
    ("aiv_cu", "*", r".*", r"^agent_messages\.sdkHttpResponse\.headers\.server-timing$", "extra:timing.server_timing_dur_ms"),
    ("aiv_cu", "*", r".*", r"^agent_messages\.sdkHttpResponse\.headers\.date$", "extra:timing.http_date"),
    ("aiv_cu", "*", r".*", r"^agent_messages\.(candidates\[\]\.index|tool_calls\[\]\.index|reasoning_details\[\]\.(index|id))$", "none"),
    ("aiv_cu", "*", r".*", r"^agent_messages\[\]\.status$", "none"),
    # Who&When (load_whowhen)
    ("whowhen", "*", r".*", r"^(is_correct|is_corrected|question_ID|level|mistake_reason|mistake_agent|mistake_step|mistake_type)$", "label_store"),
    ("whowhen", "*", r".*", r"^system_prompt(\.|$)", "omitted"),
]
RULES["changes_after_first_run"] = {
    "first_run_by_status_census_entries_n2061": {
        "rule_none": 162, "captured_census_mark": 583, "uncaptured": 525, "inside_args_or_text_json": 87,
        "slice_absent_in_A": 54, "captured_extra_leaf": 66, "inconclusive_rare": 101, "not_emitted": 60,
        "captured_column": 330, "captured_extra_renamed": 78, "label_store": 14, "omitted_by_loader": 1},
    "changes": [
        {"what": "rule target 'none'", "before": "own status rule_none, no A-sample test",
         "after": "skips census mark and name matching; status from tests (4)-(6); flag not_captured_by_rule",
         "reason": "one status vocabulary; rule_none hid whether the type is in A at all"},
        {"what": "Claude Code nested toolUseResult.<obj>.<key> paths", "before": "name-matched top-level extra keys "
         "(e.g. toolUseResult.read.bytes -> extra.bytes)", "after": "rule 'none'",
         "reason": "false capture: lib/cc_jsonl.py copies only top-level toolUseResult keys (+ usage)"},
        {"what": "AI Village row-level census group (claude_code_messages)", "before": "one slice = all aiv_cc rows, "
         "so content.message.stop_reason matched the SDK result rows' stop_reason",
         "after": "content.message.* -> 'assistant' slice, content.tool_use_result.* -> 'user/tool_result' slice",
         "reason": "false capture"},
        {"what": "census group toolUseResult/unresolved", "before": "no slice (slice_absent_in_A)",
         "after": "the corpus's user/tool_result slice", "reason": "the census could not resolve the tool; the IR "
         "result rows are the same entries"},
        {"what": "verification of column:/extra: rule targets", "before": "fell back to the whole corpus/format "
         "whenever the slice lacked the target (OpenCode part/patch messageID passed although patch rows carry no "
         "api_msg_id)", "after": "corpus/format only for rules marked '@joined' or when the slice has no row in A",
         "reason": "over-generous verification"},
        {"what": "OpenCode part messageID -> api_msg_id", "before": "all part types",
         "after": "tool / text / step-finish / reasoning parts", "reason": "patch, step-start, subtask, file, "
         "compaction meta rows carry no api_msg_id (loader code)"},
        {"what": "aiv_cu slicing", "before": "one slice = all aiv_cu rows (SDK stop_reason matched Anthropic "
         "meta.stop_reason)", "after": "per API shape (AIVCU_SHAPE_OF_STRATUM / AIVCU_SHAPE_OF_PATH)",
         "reason": "false capture"},
        {"what": "aiv_cu pass-1 name-only additions", "before": "container paths included (e.g. usageMetadata); "
         "modelVersion unmapped", "after": "containers skipped; agent_messages.modelVersion/model -> column:model",
         "reason": "a container is not a field; load_aiv_cu sets model from the row model"}],
    "not_rule_changes": "added after the first run: ts_null_by_format, totals, extra surprise items/evidence, "
                        "cc_local subagent concentration counters. RARE_EXPECTED_MIN was not changed."}
RULES["capture_rules"] = [list(r) for r in CAPTURE_RULES]
RULES["declared_skip"] = {f"{k[0]}|{k[1]}": {"regex": v, "source": SKIP_SOURCE[k]} for k, v in DECLARED_SKIP.items()}
RULES["thresholds"] = {"rare_expected_min": RARE_EXPECTED_MIN, "extra_depth": EXTRA_DEPTH, "list_cap": LIST_CAP,
                       "generic_leaves": sorted(GENERIC_LEAVES), "strip_prefixes": STRIP_PREFIXES}

CENSUS_SOURCE_CORPUS = {
    "swechat_transcripts": "swechat", "cc_local/claude_code": "cc_local", "ai_village/claude_code_messages": "aiv_cc",
    "ai_village/claude_code_messages/content_as_cc": "aiv_cc", "ai_village/computer_use_turns": "aiv_cu",
    "who_and_when": "whowhen"}


def census_corpus_format(source):
    if source.startswith("swechat_transcripts/"):
        return "swechat", source.split("/", 1)[1]
    c = CENSUS_SOURCE_CORPUS.get(source)
    if c is None:
        return None, None
    return c, {"cc_local": "claude_code", "aiv_cc": "claude_code", "aiv_cu": "aiv_cu", "whowhen": "whowhen"}[c]

# ------------------------------------------------------------------------------------------------- helpers


def jpaths(o, prefix="", depth=0, out=None):
    """Key paths inside a parsed extra value (dict levels <= EXTRA_DEPTH, lists as '[]')."""
    if out is None:
        out = set()
    if isinstance(o, dict):
        if depth >= EXTRA_DEPTH:
            return out
        for k, v in o.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            out.add(p)
            jpaths(v, p, depth + 1, out)
    elif isinstance(o, list):
        for v in o[:LIST_CAP]:
            jpaths(v, prefix + "[]", depth, out)
    return out


def leaf(path):
    seg = re.split(r"\.(?![^<]*>)", path)[-1]
    return seg.replace("[]", "").replace("{json}", "")


def stripped(path):
    p = path.replace("{json}", "")
    for pre in STRIP_PREFIXES:
        if p.startswith(pre):
            return p[len(pre):]
    return p


def crate(num_by_sess, den_by_sess):
    r = stats.cluster_rate(num_by_sess, den_by_sess)
    return {"k": int(r["num"]), "n": int(r["den"]), "rate": r["rate"], "lo": r["lo"], "hi": r["hi"],
            "n_sessions": r["n_sessions"]}


def get_path(obj, keys):
    for k in keys:
        if isinstance(obj, dict) and k in obj:
            obj = obj[k]
        elif isinstance(obj, list) and isinstance(k, int) and -len(obj) <= k < len(obj):
            obj = obj[k]
        else:
            return "MISSING"
    return obj

# ------------------------------------------------------------------------------------------------- part 1: IR inventory


class Cell:
    """Accumulates rows and extra-path presence per session for one cell (corpus x kind, or corpus x tag)."""
    __slots__ = ("rows", "path_sess", "col_nonnull")

    def __init__(self):
        self.rows = collections.Counter()           # session -> rows
        self.path_sess = collections.defaultdict(collections.Counter)  # path -> session -> rows with path
        self.col_nonnull = collections.Counter()    # column -> non-null rows

    def add(self, sid, paths, colvals):
        self.rows[sid] += 1
        for p in paths:
            self.path_sess[p][sid] += 1
        for c in colvals:
            self.col_nonnull[c] += 1

    def n(self):
        return sum(self.rows.values())

    def paths_summary(self, with_ci=True):
        sids = list(self.rows)
        den = [self.rows[s] for s in sids]
        out = {}
        for p in sorted(self.path_sess):
            num = [self.path_sess[p].get(s, 0) for s in sids]
            if with_ci:
                out[p] = crate(num, den)
            else:
                out[p] = {"k": int(sum(num)), "n": int(sum(den)), "n_sessions_with": sum(1 for x in num if x)}
        return out


def load_corpus(corpus, fmt_by_session):
    path = CACHE / f"{corpus}_A.parquet"
    assert path.name.endswith("_A.parquet") and path.exists(), path
    meta = pq.read_table(path, columns=["session_id", "stratum", "kind", "tool_raw", "is_subagent", "parent_call_id",
                                        "extra"]).to_pydict()
    n = len(meta["session_id"])
    valid = {}
    for c in COLUMNS:
        valid[c] = pq.read_table(path, columns=[c]).column(c).is_valid().to_numpy(zero_copy_only=False)
    rows = []
    for i in range(n):
        e = meta["extra"][i]
        d = json.loads(e) if isinstance(e, str) else None
        rows.append((meta["session_id"][i], meta["stratum"][i], meta["kind"][i], meta["tool_raw"][i],
                     bool(meta["is_subagent"][i]) if meta["is_subagent"][i] is not None else False,
                     meta["parent_call_id"][i], d if isinstance(d, dict) else {}))
    return rows, valid


def ir_inventory(fmt_by_session):
    inv = {"columns_by_kind": {}, "columns_by_format_kind": {}, "extra_by_kind": {}, "extra_by_format_kind": {},
           "rows": {}, "sessions": {}}
    slices = {}       # corpus -> tag -> Cell
    fmt_cells = {}    # corpus -> format -> Cell (format-level, for rule verification)
    unmapped = collections.Counter()
    for corpus in CORPORA:
        rows, valid = load_corpus(corpus, fmt_by_session)
        col_names = list(COLUMNS)
        validm = np.stack([valid[c] for c in col_names], axis=1)
        kind_cells = collections.defaultdict(Cell)
        fk_cells = collections.defaultdict(Cell)
        tag_cells = collections.defaultdict(Cell)
        fcells = collections.defaultdict(Cell)
        col_sess = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))   # kind -> col -> sess
        ts_j = col_names.index("ts")
        sess_rows, sess_ts_null, sess_fmt = collections.Counter(), collections.Counter(), {}
        fcol_sess = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))  # (fmt,kind) -> col -> sess
        for i, (sid, stratum, kind, tool_raw, is_sub, pcid, d) in enumerate(rows):
            fmt = corpus_format(corpus, fmt_by_session, sid)
            sess_rows[sid] += 1
            sess_fmt[sid] = fmt
            if not validm[i, ts_j]:
                sess_ts_null[sid] += 1
            paths = jpaths(d)
            nn = [col_names[j] for j in np.flatnonzero(validm[i])]
            kind_cells[kind].add(sid, paths, ())
            for c in nn:
                col_sess[kind][c][sid] += 1
            if corpus == "swechat":
                fk_cells[(fmt, kind)].add(sid, paths, ())
                for c in nn:
                    fcol_sess[(fmt, kind)][c][sid] += 1
            fcells[fmt].add(sid, paths, nn)
            for t in row_tags(corpus, fmt, kind, d, tool_raw, is_sub, pcid, stratum):
                if t.startswith("<unmapped"):
                    unmapped[f"{corpus}|{fmt}|{t}"] += 1
                tag_cells[(fmt, t)].add(sid, paths, nn)
        tsq = collections.defaultdict(lambda: {"sessions": 0, "sessions_all_ts_null": 0, "sessions_some_ts_null": 0,
                                               "events": 0, "events_ts_null": 0, "all_null_session_ids": []})
        # (sessions whose every event has ts None; the format's expected ts_kind is in ir.py / the loader docstrings)
        for sid, nrow in sess_rows.items():
            q = tsq[sess_fmt[sid]]
            q["sessions"] += 1
            q["events"] += nrow
            q["events_ts_null"] += sess_ts_null[sid]
            if sess_ts_null[sid] == nrow:
                q["sessions_all_ts_null"] += 1
                if corpus == "swechat":          # public corpus: ids may be listed (cc_local is private: counts only)
                    q["all_null_session_ids"].append(sid)
            elif sess_ts_null[sid]:
                q["sessions_some_ts_null"] += 1
        inv.setdefault("ts_null_by_format", {})[corpus] = {k: dict(v) for k, v in sorted(tsq.items())}
        inv["rows"][corpus] = len(rows)
        inv["sessions"][corpus] = len({r[0] for r in rows})

        def colsummary(cell, csess):
            sids = list(cell.rows)
            den = [cell.rows[s] for s in sids]
            return {c: crate([csess[c].get(s, 0) for s in sids], den) for c in col_names}

        inv["columns_by_kind"][corpus] = {k: {"rows": kind_cells[k].n(), "sessions": len(kind_cells[k].rows),
                                              "fill": colsummary(kind_cells[k], col_sess[k])}
                                          for k in KINDS if k in kind_cells}
        inv["extra_by_kind"][corpus] = {k: {"rows": kind_cells[k].n(), "sessions": len(kind_cells[k].rows),
                                            "paths": kind_cells[k].paths_summary()}
                                        for k in KINDS if k in kind_cells}
        if corpus == "swechat":
            for (fmt, k), cell in sorted(fk_cells.items()):
                inv["columns_by_format_kind"].setdefault(fmt, {})[k] = {
                    "rows": cell.n(), "sessions": len(cell.rows), "fill": colsummary(cell, fcol_sess[(fmt, k)])}
                inv["extra_by_format_kind"].setdefault(fmt, {})[k] = {
                    "rows": cell.n(), "sessions": len(cell.rows), "paths": cell.paths_summary()}
        slices[corpus] = tag_cells
        fmt_cells[corpus] = fcells
        del rows, valid, validm
    inv["unmapped_rows_by_tag"] = dict(unmapped)
    return inv, slices, fmt_cells

# ------------------------------------------------------------------------------------------------- part 1b: census x IR


def match_rule(corpus, fmt, group, path):
    for rc, rf, rg, rp, target in CAPTURE_RULES:
        if rc not in ("*", corpus) or rf not in ("*", fmt):
            continue
        if not re.search(rg, group):
            continue
        m = re.search(rp, path)
        if m:
            return m.expand(target) if "\\" in target else target, [rc, rf, rg, rp, target]
    return None, None


def target_present(target, cell, fcell):
    """(present, scope) for column:/extra: targets. Verified on the slice when it has rows in A; on the corpus/format
    when the slice is absent from A, or when the rule marks the value as living on a joined row ('@joined')."""
    target, _, joined = target.partition("@")
    kind, _, name = target.partition(":")
    scopes = [("slice", cell)] if (cell is not None and cell.n()) else []
    if joined or not scopes:
        scopes.append(("format_joined" if joined else "format_slice_absent", fcell))
    for scope, c in scopes:
        if c is None:
            continue
        if kind == "column" and c.col_nonnull.get(name, 0) > 0:
            return True, scope
        if kind == "extra" and any(p == name or p.startswith(name + ".") or p.startswith(name + "[]")
                                   for p in c.path_sess):
            return True, scope
    return False, None


def classify_entry(corpus, fmt, group, path, census_captured, fill_rate, cell, fcell):
    target, rule = match_rule(corpus, fmt, group, path)
    res = {"rule": rule, "target": target}
    n_slice = cell.n() if cell is not None else 0
    res["slice_rows_A"] = n_slice
    res["slice_sessions_A"] = len(cell.rows) if cell is not None else 0
    if target is not None and target != "none":
        if target in ("args", "text"):
            res["status"] = "inside_args_or_text_json"
        elif target == "label_store":
            res["status"] = "label_store"
        elif target == "omitted":
            res["status"] = "omitted_by_loader"
        else:
            ok, scope = target_present(target, cell, fcell)
            res["status"] = ("captured_column" if target.startswith("column:") else "captured_extra_renamed") if ok \
                else "rule_target_unverified"
            res["verify_scope"] = scope
        return res
    if target == "none":   # explicit 'not captured': skip the census mark and name matching, keep the A-sample tests
        res["not_captured_by_rule"] = True
    elif census_captured and (census_captured == "cc_jsonl" or census_captured.startswith("ir_column:")):
        res["status"] = "captured_census_mark"
        return res
    if target != "none" and cell is not None and n_slice:
        lf = leaf(path)
        if lf in GENERIC_LEAVES:
            sp = stripped(path)
            hit = [p for p in cell.path_sess if p == sp or p.replace("[]", "") == sp.replace("[]", "")]
        else:
            hit = [p for p in cell.path_sess if leaf(p) == lf]
        if hit:
            res["status"] = "captured_extra_leaf"
            res["matched_extra_paths"] = sorted(hit)[:5]
            return res
    skip = DECLARED_SKIP.get((corpus, fmt))
    if skip and re.search(skip, group):
        res["status"] = "not_emitted"
        return res
    if not n_slice:
        res["status"] = "slice_absent_in_A"
        return res
    expected = (fill_rate or 0.0) * n_slice
    res["expected_in_A"] = round(expected, 3)
    res["status"] = "uncaptured" if expected >= RARE_EXPECTED_MIN else "inconclusive_rare"
    return res


TAG_RULES = [
    ("mcp_structured_content", re.compile(r"mcpMeta\.structuredContent")),
    ("model_authored_input", re.compile(r"(message\.content\[\]\.input|arguments|(^|\.)args(\.|$)|toolArgs|"
                                        r"agent_action|state\.input|invocation\.arguments|content\[\]\.input)")),
    ("census_classifier_artifact", re.compile(r"(tabId|writtenAtMs|VSCode_Expert|success_time|"
                                              r"repo_github_metadata\.id|template_repository\.id)")),
]


def noise_tags(corpus, fmt, path, status):
    tags = [name for name, rx in TAG_RULES if rx.search(path)]
    if fmt == "claude_code" and leaf(path) in ("sessionId", "session_id"):
        tags.append("entry_session_id")
    if status == "label_store":
        tags.append("label")
    return tags or ["harness_measured"]


def census_crossref(census, slices, fmt_cells):
    entries = []
    for f in census["flagged"]:
        corpus, fmt = census_corpus_format(f["source"])
        if corpus is None:
            continue
        group, path = f["group"], f["path"]
        slice_group = group
        if f["source"] == "ai_village/claude_code_messages" and path.startswith("content."):
            path = path[len("content."):]
            # row-level census group: route the content paths to the Claude Code entry slices they belong to
            if path.startswith("message."):
                group = slice_group = "assistant"
            elif path.startswith("tool_use_result."):
                group = slice_group = "user/tool_result"
        if group.endswith("toolUseResult/unresolved"):   # census could not resolve the tool: use all tool results
            slice_group = group[: -len("toolUseResult/unresolved")] + "user/tool_result"
        if corpus == "aiv_cu":
            shape = aivcu_shape_of_path(path)
            if shape:
                slice_group = f"computer_use_turns/{shape}"
        cell = slices[corpus].get((fmt, slice_group))
        fcell = fmt_cells[corpus].get(fmt)
        fill = f.get("fill") or {}
        res = classify_entry(corpus, fmt, group, path, f.get("captured"), fill.get("rate"), cell, fcell)
        entries.append({
            "corpus": corpus, "format": fmt, "source": f["source"], "group": f["group"], "path": f["path"],
            "slice_used": slice_group,
            "classes": f["classes"], "census_captured": f.get("captured"), "census_loader_mark": f.get("loader"),
            "raw_fill": {"n_rec": f["n_rec"], "n_records": f["n_records"], "unit": f["unit"], "rate": fill.get("rate"),
                         "lo": fill.get("lo"), "hi": fill.get("hi"), "ci": fill.get("ci"), "n_units": fill.get("n_units"),
                         "scope": fill.get("scope")},
            **res, "tags": noise_tags(corpus, fmt, f["path"], res["status"])})
    return entries


def aiv_cu_population(entries, pass1, aivcu_build, census, slices, fmt_cells):
    """Attach full-population occurrence counts to aiv_cu entries; add pass-1-only flagged-by-name paths."""
    kp = pass1["agent_messages_key_paths"]
    rows_by_shape = aivcu_build["population"]["turns_by_shape"]
    for e in entries:
        if e["corpus"] != "aiv_cu" or not e["path"].startswith("agent_messages"):
            continue
        rest = e["path"][len("agent_messages"):]
        if not rest.startswith("["):
            rest = rest if rest.startswith(".") else "." + rest
        pop = []
        for shape, paths in kp.items():
            if rest in paths:
                occ = paths[rest]
                nrows = rows_by_shape.get(shape)
                pop.append({"shape": shape, "occurrences": occ, "turns_of_shape": nrows,
                            "rate": (occ / nrows) if (nrows and "[]" not in rest) else None})
        e["population_pass1"] = pop
    words = census["meta"]["rules"]["class_rules"]["word_sets"]
    wsets = {cls: set(words[f"{cls}_W"]) for cls in ("TIMER", "CLOCK", "TOKEN", "COUNTER", "HASH", "STATUS")}
    seen = {e["path"] for e in entries if e["corpus"] == "aiv_cu"}
    extra_entries = []
    fcell = fmt_cells["aiv_cu"].get("aiv_cu")
    for shape, paths in kp.items():
        cell = slices["aiv_cu"].get(("aiv_cu", f"computer_use_turns/{shape}"))
        for kpath, occ in paths.items():
            full = "agent_messages" + kpath
            if full in seen:
                continue
            if any(o != kpath and (o.startswith(kpath + ".") or o.startswith(kpath + "[]")) for o in paths):
                continue   # container (dict/list) path: its children are evaluated instead
            lw = set(w.lower() for w in re.split(r"[^A-Za-z0-9]+|(?<=[a-z])(?=[A-Z])", leaf(kpath)) if w)
            pw = set(w.lower() for w in re.split(r"[^A-Za-z0-9]+|(?<=[a-z])(?=[A-Z])", kpath) if w)
            cls = [c for c, ws in (("TIMER", wsets["TIMER"]), ("CLOCK", wsets["CLOCK"]), ("COUNTER", wsets["COUNTER"]),
                                   ("HASH_ID", wsets["HASH"]), ("STATUS", wsets["STATUS"])) if lw & ws]
            if pw & wsets["TOKEN"]:
                cls.append("TOKEN")
            if not cls:
                continue
            nrows = rows_by_shape.get(shape)
            res = classify_entry("aiv_cu", "aiv_cu", f"computer_use_turns/{shape}", full, None,
                                 (occ / nrows) if (nrows and "[]" not in kpath) else None, cell, fcell)
            extra_entries.append({
                "corpus": "aiv_cu", "format": "aiv_cu", "source": "aiv_cu_pass1_stats.agent_messages_key_paths",
                "group": f"computer_use_turns/{shape}", "slice_used": f"computer_use_turns/{shape}", "path": full,
                "classes": cls, "class_evidence": "name_only",
                "census_captured": None, "census_loader_mark": None,
                "raw_fill": {"n_rec": occ, "n_records": nrows, "unit": "turn (occurrences; list paths count elements)",
                             "rate": (occ / nrows) if (nrows and "[]" not in kpath) else None, "lo": None, "hi": None,
                             "ci": None, "n_units": None, "scope": "full population, pass 1"},
                **res, "tags": noise_tags("aiv_cu", "aiv_cu", full, res["status"])})
    return extra_entries

# ------------------------------------------------------------------------------------------------- part 2: surprises

SB, SR, SR2 = "swechat_build.json", "swechat_review.json", "swechat_review2.json"
CB, R1, R2, FX, FP = ("cc_local_build.json", "review_cc_local_aiv_cc.json", "review2_cc_local_aiv_cc.json",
                      "cc_local_attachment_fix_check.json", "cc_local_fork_policy_owner_check.json")
VB = "aiv_cc_build.json"
UB, UR, UV, UP = "aiv_cu_build.json", "aiv_cu_review.json", "aiv_cu_review_reverify.json", "aiv_cu_pass1_stats.json"
WB, WR = "whowhen_build.json", "whowhen_review.json"
CEN = "../phase_a/a6_raw_census.json"
FPP = ["full_population_pass", "by_format"]
CXP = FPP + ["codex", "parse"]
OCP = FPP + ["opencode", "parse"]

# (id, corpus, category, what, [ (name, file, path) ...], same_fact groups, status)
# status: open (present in the current IR) | resolved_in_loader (a review finding the current build fixes) |
#         handled_by_loader (the loader encodes it: synthetic id / deferred attach / flag)
SURPRISES = [
    # ---------------- swechat
    ("sw_label_vs_content_format", "swechat", "format_detection",
     "sessions whose scaffold label disagrees with the transcript's content format",
     [("label_ClaudeCode_fmt_cursor", SB, ["label_x_format", "Claude Code", "cursor"]),
      ("label_GeminiCLI_fmt_claude_code", SB, ["label_x_format", "Gemini CLI", "claude_code"]),
      ("label_unknown_fmt_claude_code", SB, ["label_x_format", "unknown", "claude_code"]),
      ("label_unknown_fmt_gemini", SB, ["label_x_format", "unknown", "gemini"]),
      ("label_Agent_fmt_claude_code", SB, ["label_x_format", "Agent", "claude_code"]),
      ("label_RogerRoger_fmt_claude_code", SB, ["label_x_format", "Roger Roger Agent", "claude_code"])], [], "handled_by_loader"),
    ("sw_session_without_transcript", "swechat", "missing_data", "sessions.parquet rows without a transcript file",
     [("sessions_without_transcript", SB, ["population", "sessions_without_transcript"]),
      ("sessions_without_file_rv2", SR2, ["rv2_sample_nums", "sessions_without_file"])], [], "open"),
    ("sw_cc_concatenated_json_lines", "swechat", "malformed_lines",
     "Claude Code lines holding two JSON values (no newline); salvaged with raw_decode",
     [("lines_salvaged", SB, FPP + ["claude_code", "parse", "lines_salvaged"]),
      ("objects_from_salvaged_lines", SB, FPP + ["claude_code", "parse", "objects_from_salvaged_lines"]),
      ("census_salvaged_lines", CEN, ["non_tool_entry_inventory", "swechat_transcripts", "claude_code", "line_stats", "salvaged_lines"])],
     [["lines_salvaged", "census_salvaged_lines"]], "handled_by_loader"),
    ("sw_cc_undecodable_lines", "swechat", "malformed_lines", "Claude Code lines that fail to decode even after salvage",
     [("bad_lines", SB, FPP + ["claude_code", "parse", "bad_lines"]),
      ("files_with_bad_lines", SB, FPP + ["claude_code", "parse", "files_with_bad_lines"]),
      ("review_lines", SR, ["population_claude_code_undecodable_lines", "lines"]),
      ("review_lines_containing_tool_use", SR, ["population_claude_code_undecodable_lines", "lines_containing_tool_use"]),
      ("review_lines_containing_tool_result", SR, ["population_claude_code_undecodable_lines", "lines_containing_tool_result"]),
      ("census_bad_lines", CEN, ["non_tool_entry_inventory", "swechat_transcripts", "claude_code", "line_stats", "bad_lines"])],
     [["bad_lines", "review_lines", "census_bad_lines"]], "open"),
    ("sw_cc_fixture_entry_types", "swechat", "format_detection",
     "Claude Code files with test-fixture entries of type tool_use/tool_result (no CC harness writes them)",
     [("cc_fixture_entries", SB, FPP + ["claude_code", "parse", "cc_fixture_entries"]),
      ("files", SB, ["format_notes", "claude_code_files_with_tool_use_or_tool_result_entry_types"])], [], "handled_by_loader"),
    ("sw_cc_zero_event_file", "swechat", "missing_data", "Claude Code transcript files yielding zero IR events",
     [("files_with_zero_events", SB, FPP + ["claude_code", "parse", "files_with_zero_events"]),
      ("format_notes", SB, ["format_notes", "claude_code_files_with_zero_events"])],
     [["files_with_zero_events", "format_notes"]], "open"),
    ("sw_cc_call_result_pairing", "swechat", "id_linkage", "Claude Code pairing anomalies (full population)",
     [("duplicate_call_ids", SB, FPP + ["claude_code", "duplicate_call_ids"]),
      ("results_without_call", SB, FPP + ["claude_code", "results_without_call"]),
      ("calls_without_result", SB, FPP + ["claude_code", "calls_without_result"]),
      ("review_calls_without_result", SR, ["full_population_independent_recount", "claude_code", "calls_without_result"]),
      ("review_results_without_call", SR, ["full_population_independent_recount", "claude_code", "results_without_call"])],
     [["calls_without_result", "review_calls_without_result"], ["results_without_call", "review_results_without_call"]], "open"),
    ("sw_cc_subagent_only_in_progress", "swechat", "structure",
     "Claude Code subagent calls that exist only nested inside progress/agent_progress entries",
     [("calls_nested_subagent", SB, FPP + ["claude_code", "calls_nested_subagent"]),
      ("calls_total", SB, FPP + ["claude_code", "calls"]),
      ("review_nested_calls", SR, ["full_population_independent_recount", "claude_code", "nested_calls"])],
     [["calls_nested_subagent", "review_nested_calls"]], "handled_by_loader"),
    ("sw_ts_backward_steps", "swechat", "ordering_time",
     "events whose ts is earlier than the previous event's in file order (parallel results / call+result interleave)",
     [("claude_code", SB, FPP + ["claude_code", "ts_backward_steps"]),
      ("opencode", SB, FPP + ["opencode", "ts_backward_steps"]),
      ("gemini", SB, FPP + ["gemini", "ts_backward_steps"]),
      ("codex", SB, FPP + ["codex", "ts_backward_steps"])], [], "open"),
    ("sw_gemini_result_before_call", "swechat", "ordering_time", "Gemini tool results stamped before/at their call",
     [("result_ts_before_call_ts", SR, ["population_gemini_result_vs_call_ts", "result_ts_before_call_ts"]),
      ("result_ts_equal_call_ts", SR, ["population_gemini_result_vs_call_ts", "result_ts_equal_call_ts"]),
      ("results_with_both_ts", SR, ["population_gemini_result_vs_call_ts", "results_with_both_ts"])], [], "open"),
    ("sw_gemini_calls_without_result", "swechat", "missing_data",
     "Gemini toolCalls with no `result` key (one session holds all of them)",
     [("calls_without_result", SB, FPP + ["gemini", "calls_without_result"]),
      ("calls_without_result_key", SR2, ["rv2_gem_nores", "counts", "calls_without_result_key"]),
      ("sessions", SR2, ["rv2_gem_nores", "counts", "sessions"]),
      ("per_session", SR2, ["rv2_gem_nores", "per_session"])], [], "open"),
    ("sw_gemini_redacted_duplicate_ids", "swechat", "redaction",
     "Gemini call ids redacted to REDACTED, producing a duplicate call id",
     [("duplicate_call_ids", SB, FPP + ["gemini", "duplicate_call_ids"]),
      ("dup_rows", SR2, ["rv2_gem_red", "dup_rows"]),
      ("id_contains_REDACTED", SR2, ["rv2_gem_red", "id_contains_REDACTED"])],
     [["duplicate_call_ids", "dup_rows"]], "open"),
    ("sw_gemini_text_exit_vs_flag", "swechat", "flag_inconsistency",
     "Gemini shell results whose text says 'Exit Code: N' (N != 0) while native_error is not true (no structured "
     "exit field; A+B sample)",
     [("shell_results", SB, ["per_format_AB", "gemini", "summary", "shell_results"]),
      ("text_exit_nonzero", SB, ["per_format_AB", "gemini", "summary", "gemini_shell_results_text_exit_nonzero"]),
      ("text_exit_nonzero_native_true", SB, ["per_format_AB", "gemini", "summary", "gemini_shell_results_text_exit_nonzero_native_true"]),
      ("shell_results_native_true", SB, ["per_format_AB", "gemini", "summary", "shell_results_native_true"])], [], "open"),
    ("sw_cursor_no_results_no_ts", "swechat", "missing_data", "Cursor transcripts: tool calls but no results, no timestamps",
     [("calls", SB, FPP + ["cursor", "calls"]), ("results", SB, FPP + ["cursor", "results"]),
      ("events_with_ts", SB, FPP + ["cursor", "events_with_ts"]), ("events", SB, FPP + ["cursor", "events"])], [], "open"),
    ("sw_opencode_document_salvage", "swechat", "malformed_document",
     "OpenCode document that fails json.load; messages salvaged one by one until the first undecodable one",
     [("document_parse_not_ok", SB, ["full_population_pass", "document_parse_not_ok"]),
      ("salvaged_messages", SB, OCP + ["salvaged_messages"]), ("salvage_stopped", SB, OCP + ["salvage_stopped"])],
     [], "handled_by_loader"),
    ("sw_opencode_redacted_ids", "swechat", "redaction",
     "OpenCode message ids / call ids redacted to REDACTED by the release (synthetic ids substituted)",
     [("redacted_message_ids", SB, OCP + ["redacted_message_ids"]),
      ("files_with_message_id_REDACTED", SB, ["format_notes", "opencode_files_with_message_id_REDACTED"]),
      ("format_notes_message_ids_REDACTED", SB, ["format_notes", "opencode_message_ids_REDACTED"]),
      ("call_ids_redacted_or_missing", SB, OCP + ["opencode_call_ids_redacted_or_missing"]),
      ("step_finish_synthetic_api_msg_id", SB, OCP + ["opencode_step_finish_synthetic_api_msg_id"]),
      ("conversations_table_REDACTED_ids", SB, ["crosscheck_conversations", "by_format", "opencode", "table_REDACTED_ids_skipped"])],
     [["redacted_message_ids", "format_notes_message_ids_REDACTED"]], "handled_by_loader"),
    ("sw_opencode_completed_nonzero_exit", "swechat", "flag_inconsistency",
     "OpenCode tool parts with status 'completed' but metadata.exit != 0",
     [("population", SB, OCP + ["opencode_results_completed_with_nonzero_exit"]),
      ("pre_fix_sessions_with_exit_nonzero_native_false", SR, ["AB_error_flag_vs_exit", "opencode_all_results", "sessions_with_exit_nonzero_native_false"]),
      ("post_fix_exit_nonzero_native_false", SB, ["review_fix_checks", "error_flag_vs_exit", "opencode_all_results", "exit_nonzero_native_false"])],
     [], "resolved_in_loader"),
    ("sw_opencode_untimed_parts", "swechat", "missing_data",
     "OpenCode parts with no time field (step-start/finish, patch, subtask, file, compaction): IR ts None",
     [("step_start", SR2, ["rv2_kinds", "opencode_untimed_parts_first300", "step-start|has_time=False"]),
      ("step_finish", SR2, ["rv2_kinds", "opencode_untimed_parts_first300", "step-finish|has_time=False"]),
      ("patch", SR2, ["rv2_kinds", "opencode_untimed_parts_first300", "patch|has_time=False"]),
      ("subtask", SR2, ["rv2_kinds", "opencode_untimed_parts_first300", "subtask|has_time=False"])], [], "open"),
    ("sw_opencode_text_ts_from_message", "swechat", "ordering_time",
     "OpenCode text parts without time.start: ts taken from the message's time.created (A+B)",
     [("rows", SR, ["AB_opencode_text_ts_from_message_created", "rows"])], [], "handled_by_loader"),
    ("sw_opencode_compaction_summary_as_assistant", "swechat", "structure",
     "OpenCode compaction summary messages whose text part is emitted as assistant text",
     [("summary_messages", SR, ["population_opencode_compaction_summaries", "summary_messages"]),
      ("emitted_as_assistant", SR, ["population_opencode_compaction_summaries", "summary_text_parts_emitted_as_assistant"])],
     [], "open"),
    ("sw_codex_end_events_without_call", "swechat", "id_linkage",
     "Codex *_end events whose call_id has no function_call in the file (nested execs, server tools)",
     [("exec_command_end", SB, CXP + ["codex_exec_command_end_without_call"]),
      ("mcp_tool_call_end", SB, CXP + ["codex_mcp_tool_call_end_without_call"]),
      ("web_search_end", SB, CXP + ["codex_web_search_end_without_call"]),
      ("patch_apply_end", SB, CXP + ["codex_patch_apply_end_without_call"]),
      ("collab_agent_spawn_end", SB, CXP + ["codex_collab_agent_spawn_end_without_call"]),
      ("collab_waiting_end", SB, CXP + ["codex_collab_waiting_end_without_call"]),
      ("collab_close_end", SB, CXP + ["codex_collab_close_end_without_call"]),
      ("collab_agent_interaction_end", SB, CXP + ["codex_collab_agent_interaction_end_without_call"])], [], "handled_by_loader"),
    ("sw_codex_exec_end_written_before_output", "swechat", "ordering_time",
     "Codex exec_command_end written to the file before the output it ends",
     [("noheader", SB, CXP + ["codex_exec_order_noheader_end_written_before_output"]),
      ("exited", SB, CXP + ["codex_exec_order_exited_end_written_before_output"]),
      ("running", SB, CXP + ["codex_exec_order_running_end_written_before_output"]),
      ("review_end_before_output", SR, ["population_codex_exec_end_ordering", "end_before_output"]),
      ("review_joined", SR, ["population_codex_exec_end_ordering", "joined"])], [], "handled_by_loader"),
    ("sw_codex_exit_never_shown", "swechat", "missing_data",
     "Codex process exits the model never saw (no later poll showed 'Process exited')",
     [("never_shown", SB, CXP + ["codex_exec_exit_never_shown_to_model"]),
      ("never_shown_nonzero", SB, CXP + ["codex_exec_exit_never_shown_to_model_nonzero"]),
      ("rv2_never_shown", SR2, ["rv2_codex_pop", "exec", "exits_never_shown"]),
      ("rv2_never_shown_nonzero", SR2, ["rv2_codex_pop", "exec", "exits_never_shown_nonzero"])],
     [["never_shown", "rv2_never_shown"], ["never_shown_nonzero", "rv2_never_shown_nonzero"]], "handled_by_loader"),
    ("sw_codex_unified_exec_deferred_exit", "swechat", "structure",
     "Codex unified exec: exit deferred from a 'running' output to a later write_stdin poll",
     [("deferred", SB, CXP + ["codex_exec_output_running_exit_deferred"]),
      ("attached_to_write_stdin", SB, CXP + ["codex_exec_exit_attached_to_write_stdin_output"]),
      ("write_stdin_exited_without_exec_end", SB, CXP + ["codex_write_stdin_output_exited_without_exec_end"]),
      ("rv2_ws_exited_no_exec_end", SR2, ["rv2_codex_pop", "exec", "ws_exited_process_has_no_exec_end"]),
      ("pre_fix_running_with_exit_code_set_AB", SR, ["AB_codex_running_output_exit_attribution", "of_which_exit_code_set"]),
      ("post_fix_running_with_exit_code_set_AB", SB, ["review_fix_checks", "codex_running_output_exit_attribution", "of_which_exit_code_set"])],
     [["write_stdin_exited_without_exec_end", "rv2_ws_exited_no_exec_end"]], "resolved_in_loader"),
    ("sw_codex_sessions_without_exec_end", "swechat", "missing_data",
     "Codex sessions (A+B) whose files contain no exec_command_end at all: exit only in the output header text, "
     "exit_code column null",
     [("sessions_all_noend", SR2, ["rv2_codex_join", "by_session_class", "sessions_all_noend"]),
      ("exited_outputs_in_those", SR2, ["rv2_codex_join", "by_session_class", "exited_all_noend"]),
      ("header_exited_exit_code_null", SR2, ["rv2_codex_noend", "header_exited_exit_code_null"]),
      ("header_exited_exit_code_null_header_nonzero", SR2, ["rv2_codex_noend", "header_exited_exit_code_null_header_nonzero"]),
      ("codex_sessions_AB", SR2, ["rv2_codex_noend", "codex_sessions_AB"]),
      ("shell_results_AB", SB, ["per_format_AB", "codex", "summary", "shell_results"]),
      ("shell_results_exit_code_nonnull_AB", SB, ["per_format_AB", "codex", "summary", "shell_results_exit_code_nonnull"])],
     [], "open"),
    ("sw_codex_token_count_repeats", "swechat", "duplication",
     "Codex token_count rows repeating the previous cumulative total (no new API call)",
     [("repeat_of_previous_total", SB, CXP + ["codex_token_count_repeat_of_previous_total"]),
      ("repeat_total_but_last_differs", SB, CXP + ["codex_token_count_repeat_total_but_last_differs"]),
      ("of_which_last_in_out_zero", SB, CXP + ["codex_token_count_repeat_total_but_last_differs_last_in_out_zero"]),
      ("rv2_repeat", SR2, ["rv2_codex_pop", "token_count", "repeat"]),
      ("rv2_rows", SR2, ["rv2_codex_pop", "token_count", "rows"])],
     [["repeat_of_previous_total", "rv2_repeat"]], "handled_by_loader"),
    ("sw_codex_no_response_ids", "swechat", "id_linkage",
     "Codex logs no API response id: every usage row's api_msg_id is synthetic (A+B)",
     [("usage_rows", SB, ["per_format_AB", "codex", "summary", "usage_rows"]),
      ("usage_rows_api_msg_id_synthetic", SB, ["per_format_AB", "codex", "summary", "usage_rows_api_msg_id_synthetic"]),
      ("pre_fix_api_msg_id_null", SR, ["AB_usage_rows", "codex", "api_msg_id_null"]),
      ("post_fix_api_msg_id_null", SB, ["review_fix_checks", "usage_rows", "codex", "api_msg_id_null"])],
     [["usage_rows", "usage_rows_api_msg_id_synthetic"]], "handled_by_loader"),
    ("sw_codex_human_prompt_unmatched", "swechat", "structure",
     "Codex event_msg.user_message texts with no matching response_item user message",
     [("no_response_item", SR, ["population_codex_human_prompts", "no_response_item"]),
      ("event_user_messages", SR, ["population_codex_human_prompts", "event_user_messages"]),
      ("rv2_unmatched", SR2, ["rv2_kinds", "codex_user_classification", "event_user_messages_unmatched_in_response_items"]),
      ("rv2_sessions_with_unmatched", SR2, ["rv2_kinds", "codex_user_classification", "sessions_with_unmatched"])],
     [["no_response_item", "rv2_unmatched"]], "open"),
    ("sw_usage_copied_per_block", "swechat", "duplication",
     "usage copied onto every block-event of one API response (A+B; dedupe on (session, api_msg_id) required)",
     [("cc_usage_in_sum_all_rows", SB, ["review_fix_checks", "usage_rows", "claude_code", "usage_in_sum"]),
      ("cc_usage_in_sum_dedup_session_and_id", SB, ["review_fix_checks", "usage_rows", "claude_code", "usage_in_sum_dedup_session_and_id"]),
      ("cc_usage_in_sum_dedup_id_global", SB, ["review_fix_checks", "usage_rows", "claude_code", "usage_in_sum_dedup_id_global"]),
      ("gemini_usage_in_sum_all_rows", SB, ["review_fix_checks", "usage_rows", "gemini", "usage_in_sum"]),
      ("gemini_usage_in_sum_dedup", SB, ["review_fix_checks", "usage_rows", "gemini", "usage_in_sum_dedup_session_and_id"])],
     [], "handled_by_loader"),
    ("sw_call_ids_in_several_sessions", "swechat", "duplication",
     "call ids present in more than one session (resumed / forked transcripts copy history; A+B)",
     [("in_more_than_one_session", SR, ["AB_call_ids_in_multiple_sessions", "in_more_than_one_session"]),
      ("sessions_involved", SR, ["AB_call_ids_in_multiple_sessions", "sessions_involved"]),
      ("shared_across_A_and_B", SR, ["AB_call_ids_in_multiple_sessions", "shared_across_A_and_B"])], [], "open"),
    ("sw_conversations_table_drops_calls", "swechat", "derived_table",
     "conversations.parquet vs raw transcripts (2,200 sampled sessions): tool calls missing from the table",
     [("raw_ids_not_in_table", SB, ["crosscheck_conversations", "totals", "raw_ids_not_in_table"]),
      ("cc_raw_ids_not_in_table", SB, ["crosscheck_conversations", "by_format", "claude_code", "raw_ids_not_in_table"]),
      ("codex_table_tool_use_rows", SB, ["crosscheck_conversations", "by_format", "codex", "table_tool_use_rows"]),
      ("codex_raw_calls", SB, ["crosscheck_conversations", "by_format", "codex", "raw_calls"]),
      ("opencode_table_ids_not_in_raw", SB, ["crosscheck_conversations", "by_format", "opencode", "table_ids_not_in_raw"]),
      ("cc_table_duplicate_id_rows", SB, ["crosscheck_conversations", "by_format", "claude_code", "table_duplicate_id_rows"]),
      ("sessions_absent_from_table", SB, ["crosscheck_conversations", "sessions_absent_from_table"]),
      ("sampled_sessions", SB, ["crosscheck_conversations", "sampled_sessions"]),
      ("review_cc_raw_minus_table", SR, ["crosscheck_claude_code_independent", "raw_minus_table"]),
      ("build_cc_raw_minus_table", SB, ["crosscheck_conversations", "by_format", "claude_code", "raw_minus_table_where_raw_more"])],
     [["review_cc_raw_minus_table", "build_cc_raw_minus_table"]], "open"),
    ("sw_redaction_markers", "swechat", "redaction", "redaction-marker substrings in raw transcript files, by format",
     [(f, SB, ["redaction_markers_raw_files", f, "total_substring"]) for f in
      ("claude_code", "opencode", "codex", "gemini", "copilot", "cursor")], [], "open"),
    ("sw_copilot_output_tokens_only", "swechat", "missing_data", "Copilot usage rows carry output tokens only (A+B)",
     [("rows_usage_any", SR2, ["rv2_nums", "usage", "copilot", "rows_usage_any"]),
      ("rows_usage_in", SR2, ["rv2_nums", "usage", "copilot", "rows_usage_in"])], [], "open"),
    # ---------------- cc_local
    ("cl_resume_chain_families", "cc_local", "duplication",
     "main files that start with a copy of another main file's history (resume chains), merged into families",
     [("uuids_in_multiple_main_files", CB, ["fork_families", "uuids_in_multiple_main_files"]),
      ("families_with_multiple_files", CB, ["fork_families", "families_with_multiple_files"]),
      ("files_in_multi_file_families", CB, ["fork_families", "files_in_multi_file_families"]),
      ("file_sets_before_merge", CB, ["fork_families", "file_sets_before_merge"]),
      ("sessions_after_merge", CB, ["fork_families", "sessions_after_merge"]),
      ("copy_events_dropped_uuid", CB, ["fork_families", "copy_events_dropped_uuid"]),
      ("copy_events_dropped_hash", CB, ["fork_families", "copy_events_dropped_hash"]),
      ("largest_family", CB, ["fork_families", "family_size_histogram", "13"])], [], "handled_by_loader"),
    ("cl_rejected_owner_policy", "cc_local", "id_linkage",
     "under the rejected 'owner' fork policy, subagent events whose parent call sat in another session",
     [("subagent_events_parent_call_in_other_session", FP, ["subagent_events_parent_call_in_other_session"]),
      ("subagent_events_with_parent_call_id", FP, ["subagent_events_with_parent_call_id"]),
      ("sessions_affected", FP, ["sessions_affected"])], [], "resolved_in_loader"),
    ("cl_write_order_inversions", "cc_local", "ordering_time",
     "raw lines written out of timestamp order (queue-operation before previous stop_hook_summary; resume copies)",
     [("ts_inversions_adjacent_main", CB, ["loader_counters", "ts_inversions_adjacent_main"]),
      ("ts_inversions_adjacent_wf_agent", CB, ["loader_counters", "ts_inversions_adjacent_wf_agent"]),
      ("ts_inversions_adjacent_subagent", CB, ["loader_counters", "ts_inversions_adjacent_subagent"]),
      ("files_with_ts_inversion_main", CB, ["loader_counters", "files_with_ts_inversion_main"]),
      ("files_main", CB, ["loader_counters", "files_main"]),
      ("lines_over_1h_below_running_max_main", CB, ["loader_counters", "ts_lines_over_1h_below_running_max_main"]),
      ("lines_main", CB, ["loader_counters", "lines_main"])], [], "handled_by_loader"),
    ("cl_subagent_after_parent_result", "cc_local", "ordering_time",
     "subagent events stamped after their parent call's result (background Workflow / Agent runs)",
     [("ts_after_parent_result", CB, ["full_corpus_ir", "subagent", "timing_vs_parent", "ts_after_parent_result"]),
      ("with_ts", CB, ["full_corpus_ir", "subagent", "timing_vs_parent", "with_ts"]),
      ("ts_before_parent_call", CB, ["full_corpus_ir", "subagent", "timing_vs_parent", "ts_before_parent_call"]),
      ("workflow_after", CB, ["full_corpus_ir", "subagent", "timing_vs_parent", "by_parent_tool", "Workflow", "ts_after_parent_result"]),
      ("workflow_with_ts", CB, ["full_corpus_ir", "subagent", "timing_vs_parent", "by_parent_tool", "Workflow", "events_with_ts"]),
      ("agent_after", CB, ["full_corpus_ir", "subagent", "timing_vs_parent", "by_parent_tool", "Agent", "ts_after_parent_result"]),
      ("agent_with_ts", CB, ["full_corpus_ir", "subagent", "timing_vs_parent", "by_parent_tool", "Agent", "events_with_ts"])],
     [], "open"),
    ("cl_attachment_visibility_inferred", "cc_local", "visibility",
     "attachment events whose model visibility is inferred from type (no `rendered` record in that CC version)",
     [("type_rendered_in_newer_versions", R2, ["previous_blocking_issue_attachments", "ir_attachment_totals", "visibility", "type_rendered_in_newer_versions"]),
      ("old_only_type_assumed_visible", R2, ["previous_blocking_issue_attachments", "ir_attachment_totals", "visibility", "old_only_type_assumed_visible"]),
      ("rendered", R2, ["previous_blocking_issue_attachments", "ir_attachment_totals", "visibility", "rendered"]),
      ("events", R2, ["previous_blocking_issue_attachments", "ir_attachment_totals", "events"]),
      ("visible_text_null", R2, ["previous_blocking_issue_attachments", "ir_attachment_totals", "visible_text_null"])],
     [], "handled_by_loader"),
    ("cl_attachments_were_meta", "cc_local", "visibility",
     "pre-fix caches had model-visible attachments as kind meta with no text (A split transitions)",
     [("A_meta_to_system", FX, ["splits", "A", "kind_transitions", "meta->system"]),
      ("A_meta_to_user", FX, ["splits", "A", "kind_transitions", "meta->user"]),
      ("A_text_changed_rows", FX, ["splits", "A", "text_changed_rows"])], [], "resolved_in_loader"),
    ("cl_wire_tool_inputs_differ", "cc_local", "flag_inconsistency",
     "tool_use input differs from the harness wireToolInputs copy (bash 'cd ... &&' prefix stripped, edits)",
     [("equal", R1, ["cc_local_wireToolInputs_vs_tool_use_input", "equal"]),
      ("differs", R1, ["cc_local_wireToolInputs_vs_tool_use_input", "differs"]),
      ("bash_prefix_stripped", R1, ["cc_local_wireToolInputs_vs_tool_use_input", "bash_prefix_stripped_cd_and=True"]),
      ("edit_diff", R1, ["cc_local_wireToolInputs_vs_tool_use_input", "edit_diff"]),
      ("other_tool_diff", R1, ["cc_local_wireToolInputs_vs_tool_use_input", "other_tool_diff"])], [], "open"),
    ("cc_usage_out_streaming_partials", "cc_local+aiv_cc", "duplication",
     "API message ids whose events carry different usage_out (streaming partials); input/cache never differ",
     [("cc_local_multi_event_ids", R1, ["usage_within_api_msg_id", "cc_local", "api_msg_ids_with_more_than_one_event"]),
      ("cc_local_differing_out", R1, ["usage_within_api_msg_id", "cc_local", "differing_usage_out"]),
      ("cc_local_differing_in_or_cache", R1, ["usage_within_api_msg_id", "cc_local", "differing_usage_in_or_cache"]),
      ("cc_local_differing_out_rv2", R2, ["cc_local_corpus_numbers_reproduced", "usage_within_api_msg_id", "differing_out"]),
      ("aiv_cc_multi_event_ids", R1, ["usage_within_api_msg_id", "aiv_cc", "api_msg_ids_with_more_than_one_event"]),
      ("aiv_cc_differing_out", R1, ["usage_within_api_msg_id", "aiv_cc", "differing_usage_out"]),
      ("aiv_cc_differing_out_rv2", R2, ["aiv_cc_corpus_numbers_reproduced", "usage_within_api_msg_id", "differing_out"])],
     [["cc_local_differing_out", "cc_local_differing_out_rv2"], ["aiv_cc_differing_out", "aiv_cc_differing_out_rv2"]], "open"),
    ("cc_thinking_only_api_messages", "cc_local+aiv_cc", "missing_data",
     "API responses made only of thinking blocks: absent from the IR at review 2, now emitted as meta "
     "(entry_type assistant_thinking_only)",
     [("cc_local_missing_at_review2", R2, ["thinking_only_api_messages_absent_from_ir", "cc_local", "raw_msg_ids_missing_from_ir"]),
      ("aiv_cc_missing_at_review2", R2, ["thinking_only_api_messages_absent_from_ir", "aiv_cc", "raw_msg_ids_missing_from_ir"]),
      ("cc_local_thinking_only_meta_now", CB, ["full_corpus_ir", "meta_entry_types", "assistant_thinking_only:None"]),
      ("aiv_cc_thinking_only_rows", R2, ["thinking_only_api_messages_absent_from_ir", "aiv_cc_assistant_rows_with_only_thinking_blocks"]),
      ("aiv_cc_thinking_only_meta_now", VB, ["full_corpus_ir", "meta_entry_types", "assistant_thinking_only:None"])],
     [["aiv_cc_thinking_only_rows", "aiv_cc_thinking_only_meta_now"]], "resolved_in_loader"),
    ("cl_review_numbers_predate_cache", "cc_local", "provenance",
     "review-2 row counts predate the current caches (thinking-only meta rows added after the review)",
     [("review2_A_rows", R2, ["cc_local_corpus_numbers_reproduced", "ir_rows", "A"]),
      ("current_A_rows", CB, ["splits", "A", "rows"]),
      ("review2_full_rows", R2, ["cc_local_corpus_numbers_reproduced", "ir_rows", "full"]),
      ("current_full_rows", CB, ["full_corpus_ir", "rows"])], [], "open"),
    ("cl_native_error_and_exit_fill", "cc_local", "missing_data",
     "results without an is_error key (native_error null) and no structured exit code field",
     [("results", CB, ["full_corpus_ir", "native_error", "results"]),
      ("native_error_filled", CB, ["full_corpus_ir", "native_error", "filled"]),
      ("exit_code_filled", CB, ["full_corpus_ir", "exit_code_filled"])], [], "open"),
    ("cl_ts_ties", "cc_local", "ordering_time", "events sharing one millisecond timestamp",
     [("tie_groups", CB, ["full_corpus_ir", "ts_ties", "tie_groups"]),
      ("events_in_tie_groups", CB, ["full_corpus_ir", "ts_ties", "events_in_tie_groups"]),
      ("largest_tie_group", CB, ["full_corpus_ir", "ts_ties", "largest_tie_group"]),
      ("paired_identical_ts", CB, ["full_corpus_ir", "pairing", "paired_identical_ts"])], [], "open"),
    ("cl_double_delivery", "cc_local", "duplication",
     "visible attachment payloads also found in a Parser-derived user/system text of the same session",
     [("found", R2, ["previous_blocking_issue_attachments", "double_delivery_reproduced", "found"]),
      ("tested", R2, ["previous_blocking_issue_attachments", "double_delivery_reproduced", "tested"])], [], "open"),
    ("cc_sample_redraw_order_dependence", "cc_local+aiv_cc", "provenance",
     "independent sample redraw equals the saved A/B only in the loader's population order, not file order",
     [("cc_local_redraw_A_equal_file_order", R2, ["samples", "independent_population_redraw_in_file_order", "cc_local", "redraw_A_equal"]),
      ("cc_local_redraw_A_equal_loader_order", R2, ["samples", "independent_population_redraw_in_loader_order", "cc_local", "redraw_A_equal"]),
      ("aiv_cc_redraw_A_equal_file_order", R2, ["samples", "independent_population_redraw_in_file_order", "aiv_cc", "redraw_A_equal"]),
      ("aiv_cc_A_sessions_changed_by_row_order", R1, ["sample_checks", "aiv_cc", "A_sessions_changed_when_only_input_row_order_changes"])],
     [], "open"),
    # ---------------- aiv_cc
    ("av_sdk_session_not_a_unit", "aiv_cc", "unit_definition",
     "one sdk_session_id holds almost all rows (the agent resumed one SDK session); session unit = run between inits",
     [("distinct_sdk_session_id", VB, ["sdk_sessions", "distinct_sdk_session_id"]),
      ("largest_sdk_session_rows", VB, ["sdk_sessions", "largest_sdk_session_rows"]),
      ("largest_share", VB, ["sdk_sessions", "largest_sdk_session_share"]),
      ("init_rows", VB, ["sdk_sessions", "init_rows"]),
      ("claude_code_sessions_table_rows", VB, ["sdk_sessions", "claude_code_sessions_table_rows"]),
      ("claude_code_sessions_table_distinct_sdk_session_id", VB, ["sdk_sessions", "claude_code_sessions_table_distinct_sdk_session_id"]),
      ("census_full_scan_distinct", CEN, ["parts", "aiv", "tables", "claude_code_messages", "sdk_session_full_scan", "distinct_sdk_session_id"])],
     [], "handled_by_loader"),
    ("av_content_session_id_differs", "aiv_cc", "id_linkage", "rows whose content.session_id differs from the row's sdk_session_id",
     [("rows_content_session_id_differs", VB, ["sdk_sessions", "rows_content_session_id_differs"]),
      ("distinct_content_session_id", VB, ["sdk_sessions", "distinct_content_session_id"])], [], "open"),
    ("av_message_uuid_null", "aiv_cc", "missing_data", "message_uuid column null on every row",
     [("message_uuid_null_rows", VB, ["sdk_sessions", "message_uuid_null_rows"]),
      ("rows", VB, ["recon_reproduction", "raw_scan", "rows"])], [["message_uuid_null_rows", "rows"]], "open"),
    ("av_sdk_errors", "aiv_cc", "flag_inconsistency", "assistant rows carrying an SDK `error` field",
     [("assistant_rows_with_sdk_error", VB, ["loader_counters", "assistant_rows_with_sdk_error"]),
      ("authentication_failed", VB, ["loader_counters", "sdk_error_value:authentication_failed"]),
      ("unknown", VB, ["loader_counters", "sdk_error_value:unknown"])], [], "open"),
    ("av_native_error_fill", "aiv_cc", "missing_data", "tool results without an is_error key (native_error null)",
     [("results", VB, ["full_corpus_ir", "native_error", "results"]),
      ("filled", VB, ["full_corpus_ir", "native_error", "filled"]),
      ("true", VB, ["full_corpus_ir", "native_error", "true"])], [], "open"),
    ("av_runs_without_result_row", "aiv_cc", "missing_data", "runs by number of SDK result rows (0 = run never closed)",
     [("runs_0_results", VB, ["population", "results_rows_per_session", "0"]),
      ("runs_1_result", VB, ["population", "results_rows_per_session", "1"]),
      ("runs_2_results", VB, ["population", "results_rows_per_session", "2"]),
      ("runs_4_results", VB, ["population", "results_rows_per_session", "4"])], [], "open"),
    ("av_created_at_trimmed_fraction", "aiv_cc", "ordering_time",
     "created_at fractional digits (trailing zeros stripped by the source)",
     [(f"digits_{k}", VB, ["full_corpus_ir", "ts_fractional_digits", str(k)]) for k in range(1, 7)], [], "open"),
    ("av_calls_without_result", "aiv_cc", "id_linkage", "tool_use blocks with no tool_result",
     [("calls_without_result", VB, ["full_corpus_ir", "pairing", "calls_without_result"]),
      ("recon_expected", VB, ["recon_reproduction", "expected", "calls_without_result"])],
     [["calls_without_result", "recon_expected"]], "open"),
    # ---------------- aiv_cu
    ("au_synthetic_bootstrap_turns", "aiv_cu", "synthetic_content",
     "harness-written bootstrap turns (mouse_move to screen centre) the model never generated",
     [("zero_msg_id", UB, ["population", "synthetic_turns_by_rule", "zero_msg_id"]),
      ("empty_responses_list", UB, ["population", "synthetic_turns_by_rule", "empty_responses_list"]),
      ("gemini_bare_call", UB, ["population", "synthetic_turns_by_rule", "gemini_bare_call"]),
      ("zero_call_id", UB, ["population", "synthetic_turns_by_rule", "zero_call_id"]),
      ("synthetic_mouse_move", UB, ["population", "synthetic_turns_by_action", "mouse_move"]),
      ("sessions_with_synthetic_turn", UB, ["population", "sessions_with_synthetic_turn"]),
      ("sessions_only_synthetic", UB, ["population", "sessions_only_synthetic"]),
      ("review_first_in_session", UR, ["synthetic_position_in_session", "first"]),
      ("review_mid_session", UR, ["synthetic_position_in_session", "mid"])],
     [["sessions_with_synthetic_turn", "review_first_in_session"]], "handled_by_loader"),
    ("au_nonsynthetic_centre_moves", "aiv_cu", "synthetic_content",
     "model-generated mouse_move to (512,384) (same target as the bootstrap turn), none first in session",
     [("rows", UR, ["non_synthetic_mouse_move_to_512_384", "rows"]),
      ("first_in_session", UR, ["non_synthetic_mouse_move_to_512_384", "first_in_session"])], [], "open"),
    ("au_zero_provider_call_ids", "aiv_cu", "id_linkage", "rows whose provider call id is all zeros",
     [("rows", UB, ["population", "zero_provider_call_ids", "rows"]),
      ("anthropic", UB, ["population", "zero_provider_call_ids", "by_shape", "anthropic"]),
      ("openai_chat", UB, ["population", "zero_provider_call_ids", "by_shape", "openai-chat"])], [], "handled_by_loader"),
    ("au_action_unmatched_to_provider_call", "aiv_cu", "id_linkage",
     "executed actions matched to no tool call in the stored provider message (call_id falls back to 'turn:<row id>')",
     [("none", UB, ["population", "row_level_match_how", "none"]),
      ("action_exact", UB, ["population", "row_level_match_how", "action_exact"]),
      ("command", UB, ["population", "row_level_match_how", "command"]),
      ("name", UB, ["population", "row_level_match_how", "name"]),
      ("action", UB, ["population", "row_level_match_how", "action"]),
      ("single", UB, ["population", "row_level_match_how", "single"]),
      ("no_action_talk_only", UB, ["population", "row_level_match_how", "no_action"])], [], "handled_by_loader"),
    ("au_unexecuted_calls", "aiv_cu", "missing_data",
     "talk-only rows whose stored message holds tool calls the harness never executed",
     [("talk_only_rows_with_tool_calls_in_message", UB, ["population", "talk_only_rows_with_tool_calls_in_message"])],
     [], "handled_by_loader"),
    ("au_repeated_messages", "aiv_cu", "duplication",
     "rows sharing one provider message id within a session (message stored in every row it executed)",
     [("anthropic_sdk", UB, ["population", "rows_sharing_message_id_within_session_by_shape", "anthropic-sdk"]),
      ("anthropic", UB, ["population", "rows_sharing_message_id_within_session_by_shape", "anthropic"])], [], "handled_by_loader"),
    ("au_server_timing_by_month", "aiv_cu", "missing_data",
     "Gemini server-timing header absent before 2025-12 (non-synthetic Gemini rows)",
     [(m, UB, ["population", "gemini_server_timing_fill_by_month_non_synthetic", m, "k"]) for m in
      ("2025-04", "2025-11", "2025-12", "2026-01")] +
     [(m + "_n", UB, ["population", "gemini_server_timing_fill_by_month_non_synthetic", m, "n"]) for m in
      ("2025-04", "2025-11", "2025-12", "2026-01")] +
     [("gemini_rows_with_timing", UB, ["population", "fields_by_shape_non_synthetic", "gemini", "server_timing", "k"]),
      ("gemini_rows", UB, ["population", "fields_by_shape_non_synthetic", "gemini", "server_timing", "n"])], [], "open"),
    ("au_no_latency_outside_gemini", "aiv_cu", "missing_data",
     "no latency / server-timing field in any non-Gemini shape; OpenAI shapes carry no usage and no row model",
     [("anthropic_server_timing", UB, ["population", "fields_by_shape_non_synthetic", "anthropic", "server_timing", "k"]),
      ("openai_chat_usage", UB, ["population", "fields_by_shape_non_synthetic", "openai-chat", "usage", "k"]),
      ("openai_chat_rows", UB, ["population", "fields_by_shape_non_synthetic", "openai-chat", "usage", "n"]),
      ("openai_responses_usage", UB, ["population", "fields_by_shape_non_synthetic", "openai-responses", "usage", "k"]),
      ("openai_responses_rows", UB, ["population", "fields_by_shape_non_synthetic", "openai-responses", "usage", "n"]),
      ("rows_without_row_model", UB, ["population", "turns_by_row_model", "<none>"])], [], "open"),
    ("au_updated_after_created", "aiv_cu", "ordering_time", "rows with updated_at - created_at > 1 s",
     [("over_1s", UB, ["population", "updated_minus_created_over_1s", "k"]),
      ("rows", UB, ["population", "updated_minus_created_over_1s", "n"]),
      ("over_1s_redacted", UB, ["population", "updated_minus_created_over_1s_by_redaction_flag", "True"]),
      ("max_seconds", UB, ["population", "updated_minus_created_seconds_all_rows", "max"]),
      ("review_over_1s", UR, ["updated_minus_created_over_1s", "upd_gt1"])], [["over_1s", "review_over_1s"]], "open"),
    ("au_created_at_trimmed_fraction", "aiv_cu", "ordering_time", "created_at fractional digits (trailing zeros stripped)",
     [(f"digits_{k}", UB, ["population", "created_at_fractional_digits", str(k)]) for k in range(0, 7)], [], "open"),
    ("au_sdk_text_vs_thinking_ids", "aiv_cu", "id_linkage",
     "Agent-SDK rows whose textMessage and thinkingMessage come from different API responses (stale text)",
     [("rows", UB, ["population_anthropic_sdk", "rows"]),
      ("rows_text_id_ne_thinking_id", UB, ["population_anthropic_sdk", "rows_text_id_ne_thinking_id"]),
      ("gt_no_match_in_session", UV, ["sdk_ground_truth_vs_claude_code_messages", "no_match_in_session"]),
      ("review_rows_text_id_ne_thinking_id", UR, ["sdk_text_vs_thinking_message", "population", "rows_text_id_ne_thinking_id"])],
     [["rows_text_id_ne_thinking_id", "review_rows_text_id_ne_thinking_id"]], "handled_by_loader"),
    ("au_sessions_without_turns", "aiv_cu", "missing_data", "computer_use_sessions rows with no turns",
     [("sessions_table_rows_without_turns", UB, ["population", "sessions_table_rows_without_turns"]),
      ("sessions_table_rows", UB, ["population", "sessions_table_rows"])], [], "open"),
    ("au_empty_message_shapes", "aiv_cu", "malformed_document", "turns whose agent_messages is an empty list / empty dict",
     [("empty_list", UB, ["population", "turns_by_shape", "empty-list"]),
      ("empty_dict", UB, ["population", "turns_by_shape", "empty-dict"])], [], "handled_by_loader"),
    ("au_empty_or_partial_action", "aiv_cu", "malformed_document",
     "agent_action with no action name ({} after max_tokens cut-off, or {coordinate,text})",
     [("empty", UB, ["population", "actions", "empty"]),
      ("other_coordinate_text", UB, ["population", "actions", "other:coordinate,text"])], [], "handled_by_loader"),
    ("au_screenshot_redacted", "aiv_cu", "redaction", "turns with screenshot_is_redacted = true",
     [("true", UB, ["population", "screenshot_is_redacted", "True"])], [], "open"),
    ("au_no_failure_flag", "aiv_cu", "missing_data",
     "no failure flag or exit code in the table (`error` is stderr); A recount",
     [("A_native_error_nonnull", UR, ["full_split_recount_from_raw", "A", "native_error_nonnull"]),
      ("A_exit_code_nonnull", UR, ["full_split_recount_from_raw", "A", "exit_code_nonnull"]),
      ("shell_error_nonempty", UB, ["population", "fill_by_action_class_non_synthetic", "shell", "error_non_empty", "k"]),
      ("shell_rows", UB, ["population", "fill_by_action_class_non_synthetic", "shell", "rows"])], [], "open"),
    # ---------------- whowhen
    ("ww_label_agent_vs_speaker", "whowhen", "label_inconsistency",
     "ground-truth mistake_agent differs from the speaker at mistake_step",
     [("ag_mismatch", WB, ["per_split", "Algorithm-Generated", "agent_vs_speaker", "mismatch"]),
      ("hc_mismatch", WB, ["per_split", "Hand-Crafted", "agent_vs_speaker", "mismatch"]),
      ("hc_case_insensitive_match", WB, ["per_split", "Hand-Crafted", "agent_vs_speaker", "case_insensitive_match"]),
      ("review_labels_mismatch", WR, ["recount", "labels_vs", "mismatch"])], [], "open"),
    ("ww_question_absent_from_history", "whowhen", "structure",
     "Algorithm-Generated tasks whose top-level question appears nowhere in the history (loader assumes it is "
     "repeated in history[0])",
     [("ag_question_absent_from_whole_history", WR, ["omitted_fields", "ag_question_absent_from_whole_history"]),
      ("ag_question_prefix_in_history0", WR, ["omitted_fields", "ag_question_prefix_in_history0"]),
      ("ag_n", WR, ["omitted_fields", "ag_n"])], [], "open"),
    ("ww_log_leakage", "whowhen", "contamination",
     "Hand-Crafted messages containing run-script stderr/stdout (warnings, tracebacks, FINAL ANSWER lines)",
     [("hc_msgs_with_leak", WR, ["recount", "raw", "Hand-Crafted", "hc_msgs_with_leak"]),
      ("thought_with_warning", WR, ["claims", "counts", "thought_with_warning"]),
      ("hc_messages", WB, ["per_split", "Hand-Crafted", "messages"])], [], "handled_by_loader"),
    ("ww_unpaired_calls", "whowhen", "missing_data", "calls the harness never answered",
     [("ag_unexecuted_next_speaker_not_terminal", WB, ["per_split", "Algorithm-Generated", "observations", "ag_call_unexecuted:next_speaker_not_terminal"]),
      ("ag_unexecuted_history_end", WB, ["per_split", "Algorithm-Generated", "observations", "ag_call_unexecuted:history_end"]),
      ("ag_unpaired_calls", WB, ["per_split", "Algorithm-Generated", "unpaired_calls"]),
      ("hc_unanswered_superseded", WB, ["per_split", "Hand-Crafted", "observations", "hc_call_unanswered:superseded"]),
      ("hc_unanswered_history_end", WB, ["per_split", "Hand-Crafted", "observations", "hc_call_unanswered:history_end"]),
      ("hc_unpaired_calls", WB, ["per_split", "Hand-Crafted", "unpaired_calls"])], [], "handled_by_loader"),
    ("ww_exitcode_text_outside_terminal", "whowhen", "flag_inconsistency",
     "'exitcode' text inside expert (non-terminal) messages; fenced blocks the AG2 extractor cannot parse",
     [("expert_text_contains_exitcode", WB, ["per_split", "Algorithm-Generated", "observations", "ag_expert_text_contains_exitcode"]),
      ("task_prompt_contains_exitcode", WB, ["per_split", "Algorithm-Generated", "observations", "ag_task_prompt_contains_exitcode"]),
      ("backticks_without_extractable_block", WB, ["per_split", "Algorithm-Generated", "observations", "ag_backticks_without_extractable_block"])],
     [], "open"),
    ("ww_hc_no_exit_flag", "whowhen", "missing_data",
     "Hand-Crafted results without a harness exit code (WebSurfer/FileSurfer/Assistant)",
     [("native_error_null_results", WR, ["recount", "Hand-Crafted", "native_error_null_results"]),
      ("results", WB, ["per_split", "Hand-Crafted", "results"])], [], "open"),
    ("ww_step0_task_prompt_calls", "whowhen", "structure",
     "AG step-0 task prompts carrying code blocks (emitted as calls)",
     [("ag_step0_calls", WR, ["hc_thought_kinds_and_unpaired", "ag_step0_calls"]),
      ("ag_step0_calls_executed", WR, ["hc_thought_kinds_and_unpaired", "ag_step0_calls_executed"]),
      ("build_task_prompt_with_call", WB, ["per_split", "Algorithm-Generated", "observations", "ag_task_prompt_with_call"])],
     [["ag_step0_calls", "build_task_prompt_with_call"]], "handled_by_loader"),
    ("ww_terminal_no_code", "whowhen", "structure", "Computer_terminal replies 'There is no code ... to execute'",
     [("ag_terminal_no_code", WB, ["per_split", "Algorithm-Generated", "observations", "ag_terminal_no_code"]),
      ("review_terminal_nonexit", WR, ["edge", "ag_terminal_nonexit"])], [["ag_terminal_no_code", "review_terminal_nonexit"]], "open"),
    ("ww_mistake_step_landing", "whowhen", "label_inconsistency",
     "IR kind at the labelled mistake_step (narration = assistant text with no call)",
     [("ag_call", WB, ["per_split", "Algorithm-Generated", "mistake_step_landing", "call"]),
      ("ag_narration", WB, ["per_split", "Algorithm-Generated", "mistake_step_landing", "narration"]),
      ("ag_result", WB, ["per_split", "Algorithm-Generated", "mistake_step_landing", "result"]),
      ("hc_result", WB, ["per_split", "Hand-Crafted", "mistake_step_landing", "result"]),
      ("hc_narration", WB, ["per_split", "Hand-Crafted", "mistake_step_landing", "narration"]),
      ("hc_call", WB, ["per_split", "Hand-Crafted", "mistake_step_landing", "call"])], [], "open"),
]


def compile_surprises():
    cache = {}

    def load(fname):
        if fname not in cache:
            p = BUILD / fname if not fname.startswith("..") else (BUILD / fname).resolve()
            cache[fname] = json.loads(p.read_text(encoding="utf-8"))
        return cache[fname]

    out = []
    for sid, corpus, cat, what, ev, same, status in SURPRISES:
        evid = []
        vals = {}
        for name, fname, keys in ev:
            v = get_path(load(fname), keys)
            if isinstance(v, list):
                v = {"list_len": len(v)}
            vals[name] = v
            evid.append({"name": name, "file": f"analysis/out/build/{fname}" if not fname.startswith("..")
                         else "analysis/out/phase_a/a6_raw_census.json", "path": keys, "value": v})
        consistent = [{"names": g, "equal": len({json.dumps(vals[n], sort_keys=True) for n in g}) == 1} for g in same]
        reports = sorted({e["file"] for e in evid})
        out.append({"id": sid, "corpus": corpus, "category": cat, "what": what, "status": status,
                    "count": evid[0]["value"] if evid else None, "count_name": evid[0]["name"] if evid else None,
                    "evidence": evid, "same_fact": consistent, "n_reports": len(reports), "reports": reports,
                    "missing_paths": [e["name"] for e in evid if e["value"] == "MISSING"]})
    return out

# ------------------------------------------------------------------------------------------------- part 3: non-tool inventory


def non_tool_inventory(census, slices, inv):
    nt = census["non_tool_entry_inventory"]
    sw_build = json.loads((BUILD / SB).read_text(encoding="utf-8"))
    cl_build = json.loads((BUILD / CB).read_text(encoding="utf-8"))
    av_build = json.loads((BUILD / VB).read_text(encoding="utf-8"))
    cu_pass1 = json.loads((BUILD / UP).read_text(encoding="utf-8"))
    ww_rev = json.loads((BUILD / WR).read_text(encoding="utf-8"))
    a_by_fmt = sw_build["sample"]["A_by_format"]
    out = {"groups": [], "build_counters": {}, "tables_not_ingested": {}}

    def add(corpus, fmt, group, rec, files_with, nfiles, census_kind, a_frac, scope):
        skip = DECLARED_SKIP.get((corpus, fmt))
        disp = "skipped" if (skip and re.search(skip, group)) else "emitted"
        cell = slices[corpus].get((fmt, group))
        a_rows = cell.n() if cell else 0
        a_sess = len(cell.rows) if cell else 0
        expected = rec * a_frac if a_frac is not None else None
        flag = None
        if disp == "emitted" and a_rows == 0 and expected is not None and expected >= RARE_EXPECTED_MIN:
            flag = "emitted_but_absent_in_A"
        if disp == "skipped" and a_rows > 0:
            flag = "skipped_by_rule_but_present_in_A"
        out["groups"].append({"corpus": corpus, "format": fmt, "group": group, "census_kind": census_kind,
                              "raw_records": rec, "files_with": files_with, "n_files": nfiles, "raw_scope": scope,
                              "disposition": disp, "A_rows": a_rows, "A_sessions": a_sess,
                              "expected_A_rows": None if expected is None else round(expected, 2), "flag": flag})

    for fmt, v in nt["swechat_transcripts"].items():
        nfiles = v.get("n_files") or 0
        a_frac = (a_by_fmt.get(fmt, 0) / nfiles) if nfiles else None
        for g, gv in v.get("groups", {}).items():
            if gv.get("kind") == "tool":
                continue
            add("swechat", fmt, g, gv["records"], gv.get("files_with"), nfiles, gv.get("kind"), a_frac,
                "census: all files of the format")
    n_pop = cl_build["population"]["sessions"]
    a_frac = inv["sessions"]["cc_local"] / n_pop
    for role in ("main", "subagent"):
        v = nt["cc_local"][role]
        for g, gv in v["groups"].items():
            if gv.get("kind") == "tool":
                continue
            add("cc_local", "claude_code", f"{role}:{g}", gv["records"], gv.get("files_with"), v.get("n_files"),
                gv.get("kind"), a_frac, "census: all JSONL files, resume-chain copies included")
    av_pop = av_build["population"]["sessions"]
    for g, gv in nt["ai_village_claude_code_messages_head"].items():
        if gv.get("kind") == "tool":
            continue
        add("aiv_cc", "claude_code", g, gv["records"], None, None, gv.get("kind"), None,
            "census: first 20,000 rows of claude_code_messages (head, not population)")
    out["build_counters"]["cc_local_dropped_untimestamped"] = {
        k.split(":", 1)[1]: v for k, v in cl_build["loader_counters"].items() if k.startswith("dropped_untimestamped:")}
    out["build_counters"]["cc_local_loader_emitted"] = {
        k.split(":", 1)[1]: v for k, v in cl_build["loader_counters"].items() if k.startswith("loader_emitted:")}
    out["build_counters"]["aiv_cc_events_from"] = {
        k.split(":", 1)[1]: v for k, v in av_build["loader_counters"].items() if k.startswith("events_from:")}
    out["build_counters"]["aiv_cc_population_sessions"] = av_pop
    out["build_counters"]["cc_local_non_jsonl_files_not_loaded"] = cl_build["non_jsonl_files"]
    # concentration context for the flags: subagent files live in few sessions
    sub_sessions_A = set()
    for (fmt, tag), cell in slices["cc_local"].items():
        if tag.startswith("subagent:"):
            sub_sessions_A.update(cell.rows)
    out["build_counters"]["cc_local_population_sessions"] = n_pop
    out["build_counters"]["cc_local_sessions_with_subagent_files_population"] =         cl_build["population"]["sessions_with_subagent_files"]
    out["build_counters"]["cc_local_sessions_with_subagent_rows_A"] = len(sub_sessions_A)
    out["build_counters"]["cc_local_sessions_A"] = inv["sessions"]["cc_local"]
    out["build_counters"]["aiv_cu_row_top_level_keys"] = cu_pass1["row_top_level_keys"]
    out["aiv_cu_row_keys_disposition"] = {
        "agent_action": "args (call)", "agent_messages": "assistant/call events, usage, extra (reasoning, meta, timing)",
        "created_at": "ts", "error": "stderr (result)", "has_redaction_been_overruled": "extra (result)",
        "id": "uuid", "output": "text (result)", "screenshot_is_redacted": "extra (result)", "session_id": "session_id",
        "system": "extra.system (result, when not null)", "updated_at": "extra.updated_at (result)"}
    out["build_counters"]["whowhen_omitted_fields"] = ww_rev["omitted_fields"]
    for t, v in census["parts"]["aiv"]["tables"].items():
        if not v.get("ir_source"):
            out["tables_not_ingested"][f"ai_village/{t}"] = {"rows_read": v.get("rows_read"),
                                                             "head_cap": census["parts"]["aiv"]["head_rows"]}
    for t in census["parts"]["aiv"].get("not_censused", []):
        out["tables_not_ingested"][f"ai_village/{t}"] = {"rows_read": None, "note": "not censused"}
    for t, v in census["parts"]["tables"]["tables"].items():
        out["tables_not_ingested"][f"swechat/{t}.parquet"] = {"rows": v.get("rows")}
    out["tables_not_ingested"]["swechat/conversations.parquet_turn_type_counts"] = \
        census["non_tool_entry_inventory"]["swechat_conversations_value_counts"]["columns"]["turn_type"]
    # skipped-type summary
    summ = collections.defaultdict(list)
    for g in out["groups"]:
        if g["disposition"] == "skipped":
            summ[f"{g['corpus']}|{g['format']}"].append({"group": g["group"], "raw_records": g["raw_records"],
                                                          "files_with": g["files_with"], "n_files": g["n_files"]})
    out["skipped_summary"] = {k: sorted(v, key=lambda x: -x["raw_records"]) for k, v in summ.items()}
    out["skipped_totals"] = {k: {"types": len(v), "raw_records": sum(x["raw_records"] for x in v)} for k, v in summ.items()}
    out["flags"] = [g for g in out["groups"] if g["flag"]]
    out["flag_counts"] = dict(collections.Counter(g["flag"] for g in out["flags"]))
    return out

# ------------------------------------------------------------------------------------------------- main


def summarize_crossref(entries):
    s = {"n_entries": len(entries), "by_status": collections.Counter(), "by_corpus_status": collections.Counter(),
         "census_uncaptured_now_captured": collections.Counter(), "census_captured_now_not": collections.Counter()}
    cap_states = {"captured_column", "captured_extra_renamed", "captured_extra_leaf", "captured_census_mark"}
    for e in entries:
        s["by_status"][e["status"]] += 1
        s["by_corpus_status"][f"{e['corpus']}|{e['status']}"] += 1
        census_cap = e["census_captured"] and (e["census_captured"] == "cc_jsonl" or e["census_captured"].startswith("ir_column:"))
        if not census_cap and e["status"] in cap_states:
            s["census_uncaptured_now_captured"][f"{e['corpus']}|{e['status']}"] += 1
        if census_cap and e["status"] not in cap_states:
            s["census_captured_now_not"][f"{e['corpus']}|{e['status']}"] += 1
    out = {k: (dict(v) if isinstance(v, collections.Counter) else v) for k, v in s.items()}
    out["census_uncaptured_now_captured_total"] = sum(s["census_uncaptured_now_captured"].values())
    out["census_captured_now_not_total"] = sum(s["census_captured_now_not"].values())
    return out


NOT_IN_IR = {"not_emitted", "uncaptured", "inconclusive_rare", "slice_absent_in_A", "rule_target_unverified"}


def candidate_summary(cands):
    out = collections.Counter()
    for e in cands:
        hm = "harness_measured" if e["tags"] == ["harness_measured"] else "tagged"
        for c in e["classes"]:
            out[f"{e['corpus']}|{c}|{hm}"] += 1
    return dict(sorted(out.items()))


def slim(e):
    keep = ("corpus", "format", "source", "group", "slice_used", "path", "classes", "class_evidence", "raw_fill",
            "status", "not_captured_by_rule", "target", "verify_scope", "slice_rows_A", "slice_sessions_A",
            "expected_in_A", "tags", "census_captured", "population_pass1", "matched_extra_paths")
    return {k: e[k] for k in keep if k in e}


def main():
    census = json.loads(CENSUS.read_text(encoding="utf-8"))
    pop = pq.read_table(CACHE / "swechat_population.parquet", columns=["session_id", "format"]).to_pydict()
    fmt_by_session = dict(zip(pop["session_id"], pop["format"]))
    labels = json.loads((CACHE / "whowhen_labels.json").read_text(encoding="utf-8"))
    label_keys = sorted({k for v in labels.values() for k in v})

    inv, slices, fmt_cells = ir_inventory(fmt_by_session)
    entries = census_crossref(census, slices, fmt_cells)
    pass1 = json.loads((BUILD / UP).read_text(encoding="utf-8"))
    aivcu_build = json.loads((BUILD / UB).read_text(encoding="utf-8"))
    extra_entries = aiv_cu_population(entries, pass1, aivcu_build, census, slices, fmt_cells)

    slice_out = {}
    for corpus, cells in slices.items():
        slice_out[corpus] = {f"{fmt}|{tag}": {"rows": c.n(), "sessions": len(c.rows),
                                              "extra_paths": c.paths_summary(with_ci=False),
                                              "columns_nonnull": dict(sorted(c.col_nonnull.items()))}
                             for (fmt, tag), c in sorted(cells.items())}
    all_entries = entries + extra_entries
    not_in_ir = [slim(e) for e in all_entries if e["status"] in NOT_IN_IR]
    in_json = [slim(e) for e in all_entries if e["status"] == "inside_args_or_text_json"]
    corrections = [slim(e) for e in entries if e["status"] in ("captured_column", "captured_extra_renamed",
                                                               "captured_extra_leaf")
                   and not (e["census_captured"] and (e["census_captured"] == "cc_jsonl" or
                                                      e["census_captured"].startswith("ir_column:")))]
    out = {
        "meta": {"script": "analysis/probes/phase_a_a6.py", "question": "A6 unused fields and parser surprises",
                 "seed": stats.SEED, "n_boot": stats.N_BOOT, "rules": RULES, "ir_columns": list(COLUMNS),
                 "inputs": {"A_caches": [f"analysis/cache/{c}_A.parquet" for c in CORPORA],
                            "census": "analysis/out/phase_a/a6_raw_census.json",
                            "build_reports": sorted(p.name for p in BUILD.glob("*.json"))},
                 "whowhen_label_keys": label_keys},
        "part1_ir_inventory": inv,
        "part1_ir_slices": slice_out,
        "part1_census_crossref": {"summary": summarize_crossref(entries),
                                  "summary_with_pass1_extra": summarize_crossref(all_entries),
                                  "entries": [slim(e) for e in entries],
                                  "aiv_cu_pass1_name_only_entries": [slim(e) for e in extra_entries]},
        "part1_candidates": {"totals": {
                                 "not_in_ir": len(not_in_ir), "inside_args_or_text": len(in_json),
                                 "census_marked_uncaptured_but_captured_now": len(corrections),
                                 "not_in_ir_harness_measured": sum(1 for e in not_in_ir if e["tags"] == ["harness_measured"]),
                                 "not_in_ir_harness_measured_raw_fill_ge_0.3": sum(
                                     1 for e in not_in_ir if e["tags"] == ["harness_measured"]
                                     and (e["raw_fill"]["rate"] or 0) >= 0.3),
                                 "not_in_ir_by_status": dict(collections.Counter(e["status"] for e in not_in_ir)),
                                 "not_in_ir_by_tag": dict(collections.Counter(t for e in not_in_ir for t in e["tags"]))},
                             "not_in_ir_summary": candidate_summary([e for e in all_entries if e["status"] in NOT_IN_IR]),
                             "inside_args_or_text_summary": candidate_summary(
                                 [e for e in all_entries if e["status"] == "inside_args_or_text_json"]),
                             "not_in_ir": not_in_ir, "inside_args_or_text": in_json,
                             "census_marked_uncaptured_but_captured_now": corrections},
        "part2_parser_surprises": compile_surprises(),
        "part3_non_tool_inventory": non_tool_inventory(census, slices, inv),
    }
    out["part2_summary"] = {
        "n_items": len(out["part2_parser_surprises"]),
        "by_corpus": dict(collections.Counter(s["corpus"] for s in out["part2_parser_surprises"])),
        "by_category": dict(collections.Counter(s["category"] for s in out["part2_parser_surprises"])),
        "by_status": dict(collections.Counter(s["status"] for s in out["part2_parser_surprises"])),
        "items_with_missing_paths": [s["id"] for s in out["part2_parser_surprises"] if s["missing_paths"]],
        "n_build_report_files_read": len(sorted({r for s in out["part2_parser_surprises"] for r in s["reports"]
                                                 if r.startswith("analysis/out/build/")})),
        "n_build_report_files_present": len(list(BUILD.glob("*.json"))),
        "same_fact_checks": sum(len(s["same_fact"]) for s in out["part2_parser_surprises"]),
        "same_fact_unequal": [(s["id"], c["names"]) for s in out["part2_parser_surprises"] for c in s["same_fact"]
                              if not c["equal"]]}
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")
    print("crossref:", json.dumps(out["part1_census_crossref"]["summary"]["by_status"]))
    print("surprises:", json.dumps(out["part2_summary"]))
    print("unmapped:", json.dumps(inv["unmapped_rows_by_tag"]))


if __name__ == "__main__":
    main()
