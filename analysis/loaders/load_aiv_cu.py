"""Loader for corpus `aiv_cu`: AI Village computer_use_turns -> common event IR (analysis/lib/ir.py).

Inputs (read-only): data/ai-village/computer_use_turns.jsonl.gz (one row = one agent turn), computer_use_sessions.jsonl.gz
(session -> agent_id), agents.jsonl.gz (agent_id -> name, model_string).

Outputs
  analysis/cache/aiv_cu_turns.parquet      pass-1 light index, one row per turn (all turns), for Phase C reuse
  analysis/cache/aiv_cu_sessions.parquet   per-session table: turn count, first/last created_at, shape, model, bash turns, stratum
  analysis/cache/samples/aiv_cu.json       sample.draw output (A/B session lists)
  analysis/cache/aiv_cu_A.parquet, aiv_cu_B.parquet   IR events for the sampled sessions (ir.to_frame + ir.validate)
  analysis/out/build/aiv_cu_build.json     build report (counts only); aiv_cu_pass1_stats.json (key-path inventory)

Run: python -m analysis.loaders.load_aiv_cu                 end to end, idempotent
     python -m analysis.loaders.load_aiv_cu --reuse-pass1   reuse the pass-1 parquet if present (development only)

PASS 1 (all rows). The file is ordered by random UUID `id`, so each session's turns are scattered through it. The main
process decompresses 64 MB blocks (cut at a newline) and a spawn pool json-parses every line with the same message parser
used in pass 2 (`parse_message`), returning one light row per turn. Throughput is benchmarked single-process on the first
50,000 lines, and the whole pass is timed.

SESSION ATTRIBUTES (aiv_cu_sessions.parquet)
  agent/model: computer_use_sessions.agent_id -> agents.model_string. Row-level model fields exist only in the Anthropic,
  Agent-SDK and Gemini shapes; the OpenAI shapes store no model, so model_string is the session's model of record.
  shape: majority `agent_messages` shape over the session's non-synthetic turns (all turns if none), ties alphabetical.
  stratum (10 provider/model families, from model_string; the OpenAI split is by API shape, which is fixed per model):
    anthropic-opus | anthropic-sonnet | anthropic-haiku | anthropic-fable   claude-* by family word
    anthropic-claude-code   claude-code::* (Claude Agent SDK agent; turns stored in the `_sdkFormat` shape)
    openai-responses        OpenAI first-party models whose rows are Responses-API item lists (gpt-5*, gpt-6*)
    openai-chat             OpenAI first-party models whose rows are chat-completions messages (o1, o3, o4-mini, gpt-4o, gpt-4.1)
    compat-chat             third-party OpenAI-compatible chat messages (DeepSeek, Kimi, GLM, Grok, Muse, Tinker fine-tunes)
    gemini-pro | gemini-flash                                               gemini-* by family word
  Each model_string's API shape is its majority shape over all its non-synthetic rows. length (for terciles) = turn count.

PASS 2 (all rows again, single process). Every line starts with the fixed prefix {"id":"<36>","session_id":"<36>"
(pass 1 counts violations; a regex fallback handles any). Raw lines of the sampled sessions are kept and parsed per session.

SYNTHETIC TURNS. The harness writes bootstrap turns that the model never generated: a `mouse_move` to the screen centre in
provider format, recognisable by an all-zero message id (Anthropic msg_000.., usage all zero), an all-zero tool-call id
(chat: call_000..), an empty Responses item list, or a Gemini candidate holding only a bare functionCall with no role,
finishReason, responseId, modelVersion or usageMetadata. Such a turn becomes ONE `system` event (harness-injected content
the model then sees as its own history): text None, tool/call_id None, extra.synthetic = rule, extra.action = agent_action.
No call/result is emitted for it, so call counts are model-generated calls only.

ORDERING AND TIES. Rows are sorted per session by (created_at parsed to microseconds, index of the executed call inside its
provider message, row id). created_at is the DB row-insert time, written after the action executed (pass-2 report checks
it against the Gemini HTTP date header). Ties on created_at are counted; the row id (random UUID) is the last, arbitrary
tie-break. seq = 0..n-1 in that order; within a row the order is assistant text(s), call, result.

REPEATED MESSAGES. One provider response holding several tool calls is stored verbatim in every row that executed one of
them (Anthropic parallel tool_use before 2026-06-03, chat models emitting several calls, Agent-SDK messages spanning
several tool turns). Rows are grouped per session by message key: the provider message id (Anthropic msg id, Gemini
responseId, the Agent-SDK ACTING message id (below), first Responses item id) when present and not all-zero; otherwise,
for chat-shaped rows with tool calls and Gemini rows with >= 2 calls, an md5 of the canonical message JSON. Within a group,
each row's executed action is matched to a not-yet-consumed provider call (tiers: identical command / identical
action+coordinate+text, same action, tool name, single call). Assistant texts are emitted once per (group, text) (Agent-SDK:
once per (holding message id, text)); reasoning, usage and timing are attached once per group (first row); later rows get
extra.dup_message = true. Calls of a group never matched by any row are listed in extra.unexecuted_calls on the group's
first event (the harness drops them silently).

AGENT-SDK ROWS (`_sdkFormat`, stratum anthropic-claude-code). The row holds exactly two Agent-SDK stream messages:
textMessage (one `text` block) and thinkingMessage (one `thinking` block), each with its own API message id and usage
(streaming partials: stop_reason null, output_tokens partial), and no tool_use block. They are the LATEST text block and
the LATEST thinking block the harness had seen when the action ran, so they often come from two different API responses
(a response with thinking + tool_use but no text leaves a stale textMessage; pass-1 population counts in the build
report). The row is keyed on the ACTING message = the response that issued the action:
  same id                -> that message (usage from textMessage, the later streaming snapshot of the two);
  ids differ, history    -> the message whose id first appears LATER in the session (an id unseen in earlier rows counts
                            as first appearing in this row), in (created_at, row id) order (sdk_resolve);
  ids differ, both first appear in the same row -> the larger prompt (input + cache_read + cache_creation tokens);
                            equal -> thinkingMessage (sdk_local_pick). The prompt rule alone fails across context
                            edits/compaction (prompt shrinks), which is why history comes first.
api_msg_id, usage_*, model and the dup_message grouping of the call event come from the acting message. The other
message's id and usage go in the call's extra.sdk = {acting, rule, other: {block, id, new_in_row, usage,
usage_on_text_event}}. Assistant text events carry api_msg_id = their textMessage id and are deduplicated by that id. When
the textMessage is a separate, earlier response that is not the acting one, its usage is put on its own first text event
(extra.sdk_usage_of_non_acting_text_message) once per message id, so every API response visible in the data has its usage
on exactly one event; a non-acting thinkingMessage (no event of its own) keeps its usage in extra.sdk.other only.
reasoning_chars / reasoning_items count each SDK message's thinking once per message id (on the row where it first
appears). A row whose two ids were both seen in earlier rows (a second action of one response, or a response with
neither text nor thinking, which the data cannot tell apart) is a dup_message row of its acting message.
The pass-1 index applies the same rule: workers take the row-local choice, resolve_sdk_turns then applies session
history, and the build report checks that IR call events and the pass-1 index agree on api_msg_id and usage.

MAPPING PER NON-SYNTHETIC TURN (row) -> IR events; all events: ts = created_at (ISO, source fractional digits kept),
ts_kind = 'shared_turn', uuid = row id, model = row model when present else model_string, api_msg_id = message key id
(None for chat shapes, which store no id; Agent-SDK text events: their textMessage id), is_subagent = False.
  assistant  one event per model-visible text item: Anthropic/SDK `text` blocks; Gemini text parts without `thought`;
             Responses `message` items (output_text, refusal; extra.phase); chat `content` and `refusal`. Reasoning is never
             emitted as text: extra.reasoning_chars (Anthropic/SDK thinking, Gemini thought parts, Responses reasoning
             summary+content text, chat max(len(reasoning_content), len(reasoning), sum reasoning_details text)) and
             extra.reasoning_encrypted (redacted_thinking blocks / encrypted_content items / reasoning.encrypted details)
             go on the row's first event. A talk-only turn (agent_action null) with no visible text gets one assistant
             event with text '' and extra.empty_text = true so its usage/timing survive.
  call       one per executed action (agent_action not null). tool: 'shell' for bash ({command} or {restart}); 'gui' for
             click/key/type/scroll/mouse/screenshot/drag/wait/hold_key/cursor GUI actions; else ir.normalize_tool(action
             name) (e.g. get_pixel_coords_of_element, send_message_back_to_chat, pause, search_history). tool_raw: the
             matched provider tool name (bash, computer, use_computer, computer_call, ...), else the action name.
             args = agent_action JSON; command = agent_action.command for bash. call_id = matched provider call id when it is
             present, not all-zero and unique among the session's calls; else 'turn:' + row id (extra.provider_call_id
             keeps any provider id, extra.call_id_fallback the reason: no_provider_call | duplicate_in_session).
             extra: action, call_match, msg_tool_calls, meta (stop_reason / finish_reason / phase).
             An agent_action with no action name ({} when the model's tool input was cut off by max_tokens, or
             {coordinate, text}) takes its tool class from the matched provider call (bash -> shell, computer -> gui),
             'unknown' when no call matches; extra.action keeps 'empty' / 'other:<keys>'.
  result     one per call, same call_id/tool/tool_raw/ts: text = output, stderr = error; extra.output_null, error_null,
             system (when not null), screenshot_is_redacted, has_redaction_been_overruled, updated_at. native_error and
             exit_code stay None: the table has neither field and `error` is stderr, not a failure flag.
  system     a talk-only turn that has output/error/system gets one system event carrying them (pass 1 counts: none).
  usage      on the call event, or the last assistant event of a talk-only turn. Anthropic usage -> usage_*; Agent-SDK
             acting message's usage -> usage_* (streaming partials, kept raw; see AGENT-SDK ROWS; a talk-only SDK row
             whose last text event belongs to another message gets an extra empty-text event for the acting message;
             the population has no talk-only SDK rows); Gemini usageMetadata -> usage_in =
             promptTokenCount (INCLUDES cached tokens, unlike Anthropic input_tokens), usage_out = candidatesTokenCount,
             usage_cache_read = cachedContentTokenCount; thoughtsTokenCount, totalTokenCount and the per-modality
             prompt/cache breakdowns in extra.usage_detail. The OpenAI shapes carry no usage in this table.
  timing     extra.timing on the same event as usage: Gemini sdkHttpResponse.headers server-timing `dur` (ms) and the HTTP
             `date` header (ISO, 1 s resolution). The pass-1 key inventory found no latency/created field in other shapes.
"""
import argparse
import collections
import gzip
import hashlib
import json
import multiprocessing as mp
import os
import re
import time
from datetime import timezone
from email.utils import parsedate_to_datetime

import numpy as np
import pandas as pd

from analysis.lib import ir, sample, stats

CORPUS = "aiv_cu"
DATA = os.path.join("C:\\", "Swarms", "data", "ai-village")
TURNS = os.path.join(DATA, "computer_use_turns.jsonl.gz")
SESSIONS = os.path.join(DATA, "computer_use_sessions.jsonl.gz")
AGENTS = os.path.join(DATA, "agents.jsonl.gz")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE = os.path.join(ROOT, "analysis", "cache")
OUT = os.path.join(ROOT, "analysis", "out", "build")
TURNS_PQ = os.path.join(CACHE, "aiv_cu_turns.parquet")
SESS_PQ = os.path.join(CACHE, "aiv_cu_sessions.parquet")
SAMPLE_JSON = os.path.join(CACHE, "samples", "aiv_cu.json")
SPLIT_PQ = os.path.join(CACHE, "aiv_cu_{}.parquet")
REPORT = os.path.join(OUT, "aiv_cu_build.json")
PASS1_STATS = os.path.join(OUT, "aiv_cu_pass1_stats.json")

BLOCK = 64 << 20
N_WORKERS = max(2, min(12, (os.cpu_count() or 4) - 4))

GUI_ACTIONS = {"left_click", "right_click", "middle_click", "double_click", "triple_click", "key", "type", "scroll",
               "mouse_move", "screenshot", "wait", "left_click_drag", "hold_key", "cursor_position", "left_mouse_down",
               "left_mouse_up", "zoom", "drag", "keypress", "click", "move"}
GUI_TOOL_NAMES = {"computer", "use_computer", "computer_call"}
SDK_KEYS = ("textMessage", "thinkingMessage")
ZERO_CALL_ID = re.compile(r"^(?:call_|toolu_)?0+$")
ZERO_MSG_ID = re.compile(r"^msg_0+$")
DUR_RX = re.compile(r"dur=([0-9.]+)")
SID_RX = re.compile(rb'"session_id":"([0-9a-f-]{36})"')


# ----------------------------------------------------------------------------------------------------------------------
# message parsing (shared by both passes)

def msg_shape(am):
    if am is None:
        return "null"
    if isinstance(am, list):
        return "openai-responses" if am else "empty-list"
    if isinstance(am, dict):
        if "candidates" in am:
            return "gemini"
        if am.get("_sdkFormat"):
            return "anthropic-sdk"
        if am.get("type") == "message" and "content" in am:
            return "anthropic"
        if "choices" in am:
            return "openai-chat-completion"
        if "role" in am:
            return "openai-chat"
        return "empty-dict" if not am else "dict-other"
    return "other:" + type(am).__name__


def _loads_maybe(s):
    if isinstance(s, str):
        try:
            return json.loads(s)
        except (json.JSONDecodeError, ValueError):
            return s
    return s


def _anthropic_blocks(msg, out):
    for b in msg.get("content") or []:
        if not isinstance(b, dict):
            continue
        bt = b.get("type")
        if bt == "text":
            out["texts"].append({"text": b.get("text") or "", "item_id": None})
        elif bt == "thinking":
            out["reasoning_chars"] += len(b.get("thinking") or "")
            out["reasoning_items"] += 1
        elif bt == "redacted_thinking":
            out["reasoning_encrypted"] += 1
        elif bt in ("tool_use", "server_tool_use"):
            out["calls"].append({"id": b.get("id"), "name": b.get("name"), "args": b.get("input"), "item_id": b.get("id")})
        else:
            out["other_items"]["block:" + str(bt)] += 1


def _anthropic_usage(u):
    if not isinstance(u, dict):
        return None
    det = {k: u.get(k) for k in ("service_tier", "inference_geo") if k in u}
    for k in ("output_tokens_details", "cache_creation"):
        if isinstance(u.get(k), dict):
            det[k] = u[k]
    return {"usage_in": u.get("input_tokens"), "usage_out": u.get("output_tokens"),
            "usage_cache_read": u.get("cache_read_input_tokens"), "usage_cache_create": u.get("cache_creation_input_tokens"),
            "detail": det or None}


def _prompt_tokens(u):
    """Total prompt size of one Anthropic response: input + cache_read + cache_creation tokens (None without usage)."""
    if not isinstance(u, dict):
        return None
    return sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))


def sdk_local_pick(tm, hm):
    """Row-local choice of the Agent-SDK message that issued the row's action, from the row alone.
    tm / hm: parsed textMessage / thinkingMessage (dict with id, prompt_tokens) or None. Returns (pick, rule), pick in
    {'textMessage', 'thinkingMessage', None}. Same id -> textMessage (one response; its text block is the later streaming
    snapshot of the two). Different ids -> the message with the larger prompt (input + cache_read + cache_creation; the
    conversation context only grows between calls unless context editing/compaction intervenes); equal -> thinkingMessage
    (in an extended-thinking response the thinking block comes first, so a row whose two blocks come from different
    responses most often has a stale text block). Session history refines this in sdk_resolve."""
    if tm is None and hm is None:
        return None, "no_message"
    tid, hid = (tm or {}).get("id"), (hm or {}).get("id")
    if not tid or not hid:
        if tid:
            return "textMessage", "single_message"
        if hid:
            return "thinkingMessage", "single_message"
        return ("textMessage" if tm is not None else "thinkingMessage"), "no_id"
    if tid == hid:
        return "textMessage", "same_id"
    tp, hp = tm.get("prompt_tokens"), hm.get("prompt_tokens")  # both present here (tid and hid set)
    if tp is not None and hp is not None and tp != hp:
        return ("thinkingMessage" if hp > tp else "textMessage"), "prompt_tokens"
    return "thinkingMessage", "tie_thinking"


def sdk_apply(pm, pick, rule):
    """Set api_msg_id / usage / model of an Agent-SDK parse from the chosen ('acting') message."""
    msgs = pm["sdk"]["msgs"]
    m = msgs.get(pick) if pick else None
    if m is None and msgs:  # only non-standard keys: first one in key order
        m = msgs[sorted(msgs)[0]]
    pm["sdk"]["pick"], pm["sdk"]["rule"] = pick, rule
    pm["api_msg_id"] = m["id"] if m else None
    pm["usage"] = m["usage"] if m else None
    pm["model"] = (m or {}).get("model") or next((x["model"] for x in msgs.values() if x.get("model")), None)


def sdk_resolve(rows):
    """Session-history choice of the acting message for the Agent-SDK rows of ONE session, in (created_at, row id) order.
    rows: [(text_id, thinking_id, local_pick, local_rule)]. Returns [(pick, rule)].
    When the two ids differ, the message whose id FIRST appears later in the session is the newer response (an id not
    seen in an earlier row counts as first appearing in this row), so it issued this row's action (rule 'history').
    When both first appear in the same row (both new, or both introduced together earlier) the row-local rule stands."""
    first, out = {}, []
    for i, (ti, hi, lp, lr) in enumerate(rows):
        if ti and hi and ti != hi:
            ft, fh = first.get(ti, i), first.get(hi, i)
            if ft != fh:
                out.append(("textMessage" if ft > fh else "thinkingMessage", "history"))
            else:
                out.append((lp, lr))
        else:
            out.append((lp, lr))
        for x in (ti, hi):
            if x:
                first.setdefault(x, i)
    return out


def parse_message(am):
    """Normalise one `agent_messages` value. Returns dict(shape, model, api_msg_id, texts[{text,item_id,refusal?}],
    reasoning_chars, reasoning_items, reasoning_encrypted, calls[{id,name,args,item_id}], usage|None, timing|None,
    meta{}, bare (gemini: candidate without role/finishReason), other_items Counter); Agent-SDK rows also get
    sdk{msgs{textMessage, thinkingMessage: id, model, usage, prompt_tokens, reasoning_*}, pick, rule} and texts carry
    msg_id (the id of the SDK message that holds them)."""
    out = {"shape": msg_shape(am), "model": None, "api_msg_id": None, "texts": [], "reasoning_chars": 0,
           "reasoning_items": 0, "reasoning_encrypted": 0, "calls": [], "usage": None, "timing": None, "meta": {},
           "bare": False, "other_items": collections.Counter(), "sdk": None}
    sh = out["shape"]
    if sh == "anthropic":
        out["model"], out["api_msg_id"] = am.get("model"), am.get("id")
        _anthropic_blocks(am, out)
        out["usage"] = _anthropic_usage(am.get("usage"))
        out["meta"] = {"stop_reason": am.get("stop_reason")}
    elif sh == "anthropic-sdk":
        msgs = {}
        for k in sorted(am):
            v = am[k]
            if k == "_sdkFormat":
                continue
            if not isinstance(v, dict):
                out["other_items"]["sdk_key:" + k] += 1
                continue
            if k not in SDK_KEYS:
                out["other_items"]["sdk_key:" + k] += 1
            msg = v.get("message") if isinstance(v.get("message"), dict) else {}
            sub = {"texts": [], "calls": [], "reasoning_chars": 0, "reasoning_items": 0, "reasoning_encrypted": 0,
                   "other_items": out["other_items"]}
            _anthropic_blocks(msg, sub)
            mid = msg.get("id")
            for x in sub["texts"] + sub["calls"]:
                x["msg_id"] = mid
            out["texts"] += sub["texts"]
            out["calls"] += sub["calls"]
            for f in ("reasoning_chars", "reasoning_items", "reasoning_encrypted"):
                out[f] += sub[f]
            if v.get("session_id"):
                out["meta"]["sdk_session_id"] = v.get("session_id")
            msgs[k] = {"key": k, "id": mid, "model": msg.get("model"), "usage": _anthropic_usage(msg.get("usage")),
                       "prompt_tokens": _prompt_tokens(msg.get("usage")), "reasoning_chars": sub["reasoning_chars"],
                       "reasoning_items": sub["reasoning_items"], "reasoning_encrypted": sub["reasoning_encrypted"]}
        pick, rule = sdk_local_pick(msgs.get("textMessage"), msgs.get("thinkingMessage"))
        out["sdk"] = {"msgs": msgs, "pick": pick, "rule": rule, "local_pick": pick, "local_rule": rule}
        sdk_apply(out, pick, rule)
    elif sh == "gemini":
        out["model"], out["api_msg_id"] = am.get("modelVersion"), am.get("responseId")
        fins, bare = [], True
        for c in am.get("candidates") or []:
            if not isinstance(c, dict):
                continue
            fins.append(c.get("finishReason"))
            content = c.get("content") or {}
            if c.get("finishReason") is not None or content.get("role") is not None:
                bare = False
            for p in content.get("parts") or []:
                if not isinstance(p, dict):
                    continue
                if isinstance(p.get("functionCall"), dict):
                    fc = p["functionCall"]
                    out["calls"].append({"id": fc.get("id"), "name": fc.get("name"), "args": fc.get("args"), "item_id": None})
                elif "text" in p:
                    if p.get("thought"):
                        out["reasoning_chars"] += len(p.get("text") or "")
                        out["reasoning_items"] += 1
                    else:
                        out["texts"].append({"text": p.get("text") or "", "item_id": None})
                elif p.get("thought"):
                    out["reasoning_items"] += 1
                else:
                    out["other_items"]["part:" + ",".join(sorted(k for k in p if k != "thoughtSignature"))] += 1
        out["bare"] = bare and len(fins) > 0
        out["meta"] = {"finish_reason": fins[0] if len(fins) == 1 else (fins or None)}
        um = am.get("usageMetadata")
        if isinstance(um, dict):
            det = {k: um.get(k) for k in ("thoughtsTokenCount", "totalTokenCount", "toolUsePromptTokenCount", "serviceTier")
                   if k in um}
            for k in ("promptTokensDetails", "cacheTokensDetails", "candidatesTokensDetails", "toolUsePromptTokensDetails"):
                if isinstance(um.get(k), list):
                    det[k] = {str(x.get("modality")): x.get("tokenCount") for x in um[k] if isinstance(x, dict)}
            det["usage_in_includes_cache"] = True
            out["usage"] = {"usage_in": um.get("promptTokenCount"), "usage_out": um.get("candidatesTokenCount"),
                            "usage_cache_read": um.get("cachedContentTokenCount"), "usage_cache_create": None, "detail": det}
        resp = am.get("sdkHttpResponse")
        hdr = (resp.get("headers") or {}) if isinstance(resp, dict) else {}
        if hdr:
            t = {}
            st = hdr.get("server-timing")
            if st is not None:
                m = DUR_RX.search(str(st))
                t["server_timing_dur_ms"] = float(m.group(1)) if m else None
                if not m:
                    t["server_timing_raw"] = str(st)
            if hdr.get("date"):
                try:
                    t["http_date"] = parsedate_to_datetime(hdr["date"]).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                except (TypeError, ValueError):
                    t["http_date"] = None
                    t["http_date_raw"] = hdr["date"]
            out["timing"] = t or None
    elif sh == "openai-responses":
        for it in am:
            if not isinstance(it, dict):
                out["other_items"]["nondict"] += 1
                continue
            t = it.get("type")
            if t == "reasoning":
                out["reasoning_items"] += 1
                for s in (it.get("summary") or []) + (it.get("content") or []):
                    if isinstance(s, dict):
                        out["reasoning_chars"] += len(s.get("text") or "")
                if it.get("encrypted_content"):
                    out["reasoning_encrypted"] += 1
            elif t == "message":
                if out["api_msg_id"] is None:
                    out["api_msg_id"] = it.get("id")
                if it.get("phase") is not None:
                    out["meta"]["phase"] = it.get("phase")
                for c in it.get("content") or []:
                    if not isinstance(c, dict):
                        continue
                    if c.get("type") in ("output_text", "text"):
                        out["texts"].append({"text": c.get("text") or "", "item_id": it.get("id")})
                    elif c.get("type") == "refusal":
                        out["texts"].append({"text": c.get("refusal") or "", "item_id": it.get("id"), "refusal": True})
                    else:
                        out["other_items"]["msgcontent:" + str(c.get("type"))] += 1
            elif t == "function_call":
                out["calls"].append({"id": it.get("call_id"), "name": it.get("name"), "args": _loads_maybe(it.get("arguments")),
                                     "item_id": it.get("id")})
            elif t == "computer_call":
                out["calls"].append({"id": it.get("call_id"), "name": "computer_call", "args": it.get("actions", it.get("action")),
                                     "item_id": it.get("id")})
            else:
                out["other_items"]["item:" + str(t)] += 1
        if out["api_msg_id"] is None and out["calls"]:
            out["api_msg_id"] = out["calls"][0]["item_id"]
    elif sh in ("openai-chat", "openai-chat-completion"):
        msg = am
        if sh == "openai-chat-completion":
            ch = am.get("choices") or [{}]
            msg = (ch[0] or {}).get("message") or {}
            out["model"], out["api_msg_id"] = am.get("model"), am.get("id")
        c = msg.get("content")
        if isinstance(c, str) and c != "":
            out["texts"].append({"text": c, "item_id": None})
        elif isinstance(c, list):
            for x in c:
                if isinstance(x, dict) and "text" in x:
                    out["texts"].append({"text": x.get("text") or "", "item_id": None})
        if isinstance(msg.get("refusal"), str) and msg["refusal"]:
            out["texts"].append({"text": msg["refusal"], "item_id": None, "refusal": True})
        rc = [len(msg.get(k)) for k in ("reasoning_content", "reasoning") if isinstance(msg.get(k), str)]
        rd = 0
        for x in msg.get("reasoning_details") or []:
            if isinstance(x, dict):
                v = x.get("text") or x.get("summary") or ""
                rd += len(v) if isinstance(v, str) else 0
                if x.get("type") == "reasoning.encrypted":
                    out["reasoning_encrypted"] += 1
        out["reasoning_chars"] = max(rc + [rd])
        out["reasoning_items"] = int(out["reasoning_chars"] > 0)
        for tc in msg.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") or {}
            out["calls"].append({"id": tc.get("id"), "name": fn.get("name"), "args": _loads_maybe(fn.get("arguments")),
                                 "item_id": None})
        for k in msg:
            if k not in ("role", "content", "refusal", "reasoning", "reasoning_content", "reasoning_details", "tool_calls",
                         "annotations"):
                out["other_items"]["chat_key:" + k] += 1
    elif sh == "dict-other":
        out["other_items"]["dict_keys:" + ",".join(sorted(am))[:80]] += 1
    return out


def synthetic_rule(pm, aname):
    """Name of the rule that marks a harness-written bootstrap turn, else None (see module docstring)."""
    sh = pm["shape"]
    if sh == "empty-list":
        return "empty_responses_list"
    if sh == "anthropic" and ZERO_MSG_ID.match(str(pm["api_msg_id"] or "")):
        return "zero_msg_id"
    if sh in ("openai-chat", "anthropic") and any(ZERO_CALL_ID.match(str(c.get("id") or "")) for c in pm["calls"]):
        return "zero_call_id"
    if (sh == "gemini" and pm["usage"] is None and pm["api_msg_id"] is None and pm["model"] is None and pm["bare"]
            and not pm["texts"] and pm["reasoning_items"] == 0 and len(pm["calls"]) == 1):
        return "gemini_bare_call"
    return None


# ----------------------------------------------------------------------------------------------------------------------
# actions

def action_name(a):
    if a is None:
        return "none"
    if not isinstance(a, dict):
        return "other:" + type(a).__name__
    if "command" in a:
        return "bash"
    if "action" in a:
        return str(a.get("action"))
    if a.get("restart") is not None and set(a) <= {"restart"}:
        return "restart"
    if not a:
        return "empty"
    return "other:" + ",".join(sorted(a))


def action_tool(name):
    if name in ("bash", "restart"):
        return "shell"
    if name in GUI_ACTIONS:
        return "gui"
    return ir.normalize_tool(name)


def _args_dict(c):
    a = c.get("args")
    return a if isinstance(a, dict) else {}


def match_call(action, aname, calls, consumed=()):
    """(index, how) of the provider call that the executed action corresponds to. Candidates are ranked by
    (already consumed by an earlier row of the same message, tier, position)."""
    if not calls or not isinstance(action, dict):
        return None, "none"
    key = aname.replace("send_message_back_to_chat", "send_message_to_chat").lower()
    cands = []
    for i, c in enumerate(calls):
        ad, n = _args_dict(c), str(c.get("name") or "").lower()
        tier = None
        if aname == "bash" and "command" in ad and ad.get("command") == action.get("command"):
            tier = (1, "command")
        elif "action" in action and ad.get("action") == action.get("action"):
            exact = all(ad.get(k) == action.get(k) for k in ("coordinate", "text"))
            tier = (1, "action_exact") if exact else (2, "action")
        elif n and (n == key or (len(n) > 3 and (n in key or key in n))):
            tier = (3, "name")
        elif aname in ("bash", "restart") and n in ("bash", "shell"):
            tier = (3, "name")
        elif aname in GUI_ACTIONS and n in GUI_TOOL_NAMES:
            tier = (3, "name")
        if tier:
            cands.append((i in consumed, tier[0], i, tier[1]))
    if cands:
        best = min(cands)
        return best[2], best[3]
    if len(calls) == 1:
        return 0, "single"
    return None, "none"


# ----------------------------------------------------------------------------------------------------------------------
# pass 1

P1_COLS = ["id", "session_id", "created_at", "updated_at", "shape", "row_model", "api_msg_id", "synthetic", "action",
           "n_calls", "match_how", "provider_call_id", "has_output", "has_error", "has_system", "output_chars", "error_chars",
           "n_texts", "text_chars", "reasoning_chars", "reasoning_encrypted", "has_usage", "usage_in", "usage_out",
           "server_timing_dur_ms", "http_date", "screenshot_is_redacted", "line_bytes", "prefix_ok",
           # Agent-SDK rows only (else null): both message ids, the acting-message choice (row-local in the workers,
           # session-history-resolved by resolve_sdk_turns), which message has the larger prompt / cache_read, and the
           # usage of the message NOT chosen (api_msg_id / usage_in / usage_out hold the chosen one).
           "sdk_text_msg_id", "sdk_thinking_msg_id", "sdk_pick", "sdk_rule", "sdk_prompt_cmp", "sdk_cache_read_cmp",
           "sdk_other_usage_in", "sdk_other_usage_out"]


def _cmp(tv, hv):
    if tv is None or hv is None:
        return None
    return "thinking" if hv > tv else ("text" if tv > hv else "equal")


def _sdk_p1(pm):
    s = pm.get("sdk")
    if not s:
        return [None] * 8
    tm, hm = s["msgs"].get("textMessage") or {}, s["msgs"].get("thinkingMessage") or {}
    other = hm if s["pick"] == "textMessage" else tm
    ou = other.get("usage") or {}
    cr = lambda m: (m.get("usage") or {}).get("usage_cache_read")
    return [tm.get("id"), hm.get("id"), s["pick"], s["rule"], _cmp(tm.get("prompt_tokens"), hm.get("prompt_tokens")),
            _cmp(cr(tm), cr(hm)), ou.get("usage_in"), ou.get("usage_out")]


def _row_features(line):
    d = json.loads(line)
    pm = parse_message(d.get("agent_messages"))
    a = d.get("agent_action")
    an = action_name(a)
    syn = synthetic_rule(pm, an)
    idx, how = (None, "no_action") if a is None else match_call(a, an, pm["calls"])
    pcid = pm["calls"][idx]["id"] if idx is not None else None
    u, t = pm["usage"] or {}, pm["timing"] or {}
    out, err = d.get("output"), d.get("error")
    row = [d.get("id"), d.get("session_id"), d.get("created_at"), d.get("updated_at"), pm["shape"], pm["model"],
           pm["api_msg_id"], syn, an, len(pm["calls"]), how, pcid, out is not None, err is not None,
           d.get("system") is not None, len(out) if isinstance(out, str) else -1, len(err) if isinstance(err, str) else -1,
           len(pm["texts"]), sum(len(x["text"]) for x in pm["texts"]), pm["reasoning_chars"], pm["reasoning_encrypted"],
           pm["usage"] is not None, u.get("usage_in"), u.get("usage_out"), t.get("server_timing_dur_ms"), t.get("http_date"),
           d.get("screenshot_is_redacted"), len(line), line[:7] == b'{"id":"' and line[43:59] == b'","session_id":"'
           ] + _sdk_p1(pm)
    return row, pm["other_items"], d


def resolve_sdk_turns(turns):
    """Apply sdk_resolve to the Agent-SDK rows of the pass-1 index (in place): per session in (created_at, row id)
    order, the same order pass 2 uses. Where history overrides the row-local choice, api_msg_id / usage_in /
    usage_out are swapped with the other message's. Returns the number of overridden rows."""
    m = turns["sdk_pick"].notna()
    if not m.any():
        return 0
    x = turns.loc[m, ["session_id", "created_at", "id", "sdk_text_msg_id", "sdk_thinking_msg_id", "sdk_pick", "sdk_rule"]].copy()
    x["_ts"] = pd.to_datetime(x["created_at"], format="ISO8601")
    x = x.sort_values(["session_id", "_ts", "id"])
    picks, rules = [], []
    for _, g in x.groupby("session_id", sort=False):
        res = sdk_resolve(list(zip(g["sdk_text_msg_id"], g["sdk_thinking_msg_id"], g["sdk_pick"], g["sdk_rule"])))
        picks += [p for p, _r in res]
        rules += [r for _p, r in res]
    x["_pick"], x["_rule"] = picks, rules
    flip = x.index[x["_pick"] != x["sdk_pick"]]
    for i in flip:
        r = turns.loc[i]
        new_id = r["sdk_text_msg_id"] if x.at[i, "_pick"] == "textMessage" else r["sdk_thinking_msg_id"]
        ui, uo = r["usage_in"], r["usage_out"]
        turns.loc[i, ["api_msg_id", "usage_in", "usage_out", "sdk_other_usage_in", "sdk_other_usage_out"]] = [
            new_id, r["sdk_other_usage_in"], r["sdk_other_usage_out"], ui, uo]
    turns.loc[x.index, "sdk_pick"] = x["_pick"]
    turns.loc[x.index, "sdk_rule"] = x["_rule"]
    return int(len(flip))


def _key_paths(o, p, acc, depth=0):
    if depth > 5:
        return
    if isinstance(o, dict):
        for k, v in o.items():
            q = p + "." + k
            acc[q] += 1
            if not (isinstance(v, str) or k in ("args", "input", "arguments")):
                _key_paths(v, q, acc, depth + 1)
    elif isinstance(o, list):
        for v in o:
            _key_paths(v, p + "[]", acc, depth + 1)


def p1_worker(block):
    rows, other, keypaths, bad = [], collections.Counter(), collections.defaultdict(collections.Counter), 0
    top_keys = collections.Counter()
    for line in block.split(b"\n"):
        if not line.strip():
            continue
        try:
            r, oi, d = _row_features(line)
        except (json.JSONDecodeError, ValueError):
            bad += 1
            continue
        rows.append(r)
        top_keys[",".join(sorted(d))] += 1
        for k, v in oi.items():
            other[(r[4], k)] += v
        _key_paths(d.get("agent_messages"), "", keypaths[r[4]])
    return pd.DataFrame(rows, columns=P1_COLS), other, {k: dict(v) for k, v in keypaths.items()}, bad, top_keys


def iter_blocks(path, block=BLOCK):
    with gzip.open(path, "rb") as f:
        tail = b""
        while True:
            buf = f.read(block)
            if not buf:
                if tail.strip():
                    yield tail
                return
            buf = tail + buf
            cut = buf.rfind(b"\n")
            if cut < 0:
                tail = buf
                continue
            yield buf[:cut + 1]
            tail = buf[cut + 1:]


def benchmark_first(n=50_000):
    """Single-process throughput of decompress + json.loads + feature extraction on the first n lines."""
    t0 = time.perf_counter()
    nb, lines = 0, []
    with gzip.open(TURNS, "rb") as f:
        for line in f:
            lines.append(line)
            nb += len(line)
            if len(lines) >= n:
                break
    t1 = time.perf_counter()
    for line in lines:
        _row_features(line.rstrip(b"\n"))
    t2 = time.perf_counter()
    return {"lines": len(lines), "decompressed_bytes": nb, "read_s": round(t1 - t0, 3), "parse_s": round(t2 - t1, 3),
            "lines_per_s": round(len(lines) / (t2 - t0), 1), "mb_per_s": round(nb / 1e6 / (t2 - t0), 2),
            "projected_single_process_s_all_rows": round((t2 - t0) * 2510487 / len(lines), 1)}


def pass1():
    bench = benchmark_first()
    print("benchmark first 50k:", bench, flush=True)
    t0 = time.perf_counter()
    frames, other, keypaths, bad, top_keys = [], collections.Counter(), collections.defaultdict(collections.Counter), 0, collections.Counter()
    nbytes = 0
    with mp.get_context("spawn").Pool(N_WORKERS) as pool:
        pending, blocks, done = collections.deque(), iter_blocks(TURNS), False
        while True:
            while not done and len(pending) < 2 * N_WORKERS:
                try:
                    b = next(blocks)
                except StopIteration:
                    done = True
                    break
                nbytes += len(b)
                pending.append(pool.apply_async(p1_worker, (b,)))
            if not pending:
                break
            df, oi, kp, bd, tk = pending.popleft().get()
            frames.append(df)
            other.update(oi)
            for sh, c in kp.items():
                keypaths[sh].update(c)
            bad += bd
            top_keys.update(tk)
            if len(frames) % 25 == 0:
                print(f"  pass1 blocks={len(frames)} t={time.perf_counter() - t0:.0f}s", flush=True)
    turns = pd.concat(frames, ignore_index=True)
    wall = time.perf_counter() - t0
    st = {"benchmark_first_50k": bench,
          "pass1": {"mode": f"main process gunzips {BLOCK >> 20} MB blocks; spawn pool of {N_WORKERS} parses",
                    "wall_s": round(wall, 1), "rows": int(len(turns)), "decompressed_bytes": nbytes,
                    "rows_per_s": round(len(turns) / wall, 1), "mb_per_s": round(nbytes / 1e6 / wall, 2), "bad_json_lines": bad},
          "row_top_level_keys": dict(top_keys),
          "unhandled_message_items": {f"{a}|{b}": v for (a, b), v in sorted(other.items())},
          "agent_messages_key_paths": {sh: dict(sorted(c.items())) for sh, c in keypaths.items()}}
    return turns, st


def run_pass1(reuse=False):
    if reuse and os.path.exists(TURNS_PQ) and os.path.exists(PASS1_STATS):
        with open(PASS1_STATS, encoding="utf-8") as f:
            st = json.load(f)
        turns = pd.read_parquet(TURNS_PQ)
        if list(turns.columns) == P1_COLS:
            print(f"reusing pass-1 index ({len(turns)} rows)", flush=True)
            return turns, st
    turns, st = pass1()
    t0 = time.perf_counter()
    st["sdk_history_resolution"] = {"rows_overriding_row_local_pick": resolve_sdk_turns(turns),
                                    "wall_s": round(time.perf_counter() - t0, 2)}
    os.makedirs(CACHE, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    turns.to_parquet(TURNS_PQ, index=False)
    with open(PASS1_STATS, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1, default=str)
    print("pass1:", st["pass1"], flush=True)
    return turns, st


# ----------------------------------------------------------------------------------------------------------------------
# population / strata

def load_agents_sessions():
    agents, sess = {}, {}
    with gzip.open(AGENTS, "rt", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            agents[d["id"]] = {"agent_name": d.get("name"), "model_string": d.get("model_string")}
    with gzip.open(SESSIONS, "rt", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            sess[d["id"]] = {"agent_id": d.get("agent_id"), "session_created_at": d.get("created_at")}
    return agents, sess


def stratum_of(model_string, model_shape):
    m = (model_string or "").lower()
    if not m:
        return "unknown"
    if m.startswith("claude-code::"):
        return "anthropic-claude-code"
    if m.startswith("claude"):
        for fam in ("opus", "sonnet", "haiku", "fable"):
            if fam in m:
                return "anthropic-" + fam
        return "unknown"
    if "gemini" in m:
        return "gemini-flash" if "flash" in m else "gemini-pro"
    first_party = bool(re.match(r"^(gpt-|o\d)", m))
    if model_shape == "openai-responses":
        return "openai-responses" if first_party else "compat-responses"
    if model_shape in ("openai-chat", "openai-chat-completion"):
        return "openai-chat" if first_party else "compat-chat"
    return "unknown"


def build_sessions(turns):
    agents, sess = load_agents_sessions()
    t = turns
    t["_ts"] = pd.to_datetime(t["created_at"], format="ISO8601")
    t["_model"] = t["session_id"].map(lambda x: (agents.get((sess.get(x) or {}).get("agent_id")) or {}).get("model_string"))
    real = t[t["synthetic"].isna()]
    ms = real.groupby(["_model", "shape"]).size().rename("n").reset_index().sort_values(["_model", "n"], ascending=[True, False])
    model_shape = ms.drop_duplicates("_model").set_index("_model")["shape"].to_dict()
    t["_bash"] = (t["action"] == "bash").astype(int)
    t["_gui"] = t["action"].isin(list(GUI_ACTIONS)).astype(int)
    t["_talk"] = (t["action"] == "none").astype(int)
    t["_syn"] = t["synthetic"].notna().astype(int)
    g = t.groupby("session_id", sort=True)
    s = pd.DataFrame({"n_turns": g.size(), "first_created_at": g["_ts"].min(), "last_created_at": g["_ts"].max(),
                      "n_bash_turns": g["_bash"].sum(), "n_gui_turns": g["_gui"].sum(), "n_talk_only_turns": g["_talk"].sum(),
                      "n_synthetic_turns": g["_syn"].sum()})
    counts = t.pivot_table(index="session_id", columns="shape", values="id", aggfunc="size", fill_value=0)
    real_counts = t[t["_syn"] == 0].pivot_table(index="session_id", columns="shape", values="id", aggfunc="size", fill_value=0)
    for c in counts.columns:
        s["n_shape_" + c] = counts[c].astype(int)
    major_all = counts[sorted(counts.columns)].idxmax(axis=1)
    major_real = real_counts[sorted(real_counts.columns)].idxmax(axis=1)
    s["shape"] = major_real.reindex(s.index).fillna(major_all.reindex(s.index))
    rm = real.dropna(subset=["row_model"]).groupby(["session_id", "row_model"]).size().rename("n").reset_index()
    rm = rm.sort_values(["session_id", "n", "row_model"], ascending=[True, False, True])
    s["row_model"] = rm.drop_duplicates("session_id").set_index("session_id")["row_model"]
    s = s.reset_index()
    s["in_sessions_table"] = s["session_id"].map(lambda x: x in sess)
    s["agent_id"] = s["session_id"].map(lambda x: (sess.get(x) or {}).get("agent_id"))
    s["agent_name"] = s["agent_id"].map(lambda x: (agents.get(x) or {}).get("agent_name"))
    s["model_string"] = s["agent_id"].map(lambda x: (agents.get(x) or {}).get("model_string"))
    s["model_shape"] = s["model_string"].map(model_shape)
    s["stratum"] = [stratum_of(m, sh) for m, sh in zip(s["model_string"], s["model_shape"])]
    for c in ("first_created_at", "last_created_at"):
        s[c] = s[c].dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    t.drop(columns=["_ts", "_model", "_bash", "_gui", "_talk", "_syn"], inplace=True)
    extra = {"sessions_table_rows": len(sess), "sessions_table_rows_without_turns": int(len(set(sess) - set(s["session_id"]))),
             "turn_sessions_missing_from_sessions_table": int((~s["in_sessions_table"]).sum()),
             "model_shape": {str(k): v for k, v in sorted(model_shape.items(), key=lambda kv: str(kv[0]))}}
    return s, extra


# ----------------------------------------------------------------------------------------------------------------------
# pass 2 + IR

def pass2_extract(session_ids):
    want = {s.encode() for s in session_ids}
    lines = collections.defaultdict(list)
    t0, n, nb, fallback = time.perf_counter(), 0, 0, 0
    with gzip.open(TURNS, "rb") as f:
        for line in f:
            n += 1
            nb += len(line)
            sid = line[59:95]
            if line[43:59] != b'","session_id":"':
                m = SID_RX.search(line[:400])
                sid = m.group(1) if m else b""
                fallback += 1
            if sid in want:
                lines[sid.decode()].append(line)
    wall = time.perf_counter() - t0
    st = {"mode": "single process line scan, fixed-offset session_id", "wall_s": round(wall, 1), "rows_scanned": n,
          "decompressed_bytes": nb, "rows_per_s": round(n / wall, 1), "mb_per_s": round(nb / 1e6 / wall, 2),
          "prefix_fallbacks": fallback, "rows_kept": int(sum(len(v) for v in lines.values())), "sessions_found": len(lines)}
    return lines, st


def _msg_fingerprint(am):
    return "md5:" + hashlib.md5(json.dumps(am, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def build_session(sid, stratum, model_string, raw_lines, counters):
    """Raw JSONL lines of one session -> list of IR event dicts (seq assigned)."""
    recs = []
    for line in raw_lines:
        d = json.loads(line)
        am = d.get("agent_messages")
        pm = parse_message(am)
        a = d.get("agent_action")
        an = action_name(a)
        r = {"d": d, "pm": pm, "a": a, "an": an, "syn": synthetic_rule(pm, an), "ts": pd.Timestamp(d["created_at"]),
             "gkey": None, "idx": None, "how": None}
        recs.append(r)
    recs.sort(key=lambda r: (r["ts"], r["d"]["id"]))
    # Agent-SDK rows: choose the acting message from session history (sdk_resolve), same order as pass 1
    sdk_recs = [r for r in recs if r["pm"].get("sdk") and r["pm"]["sdk"]["pick"] and not r["syn"]]
    if sdk_recs:
        rows = []
        for r in sdk_recs:
            s = r["pm"]["sdk"]
            rows.append(((s["msgs"].get("textMessage") or {}).get("id"), (s["msgs"].get("thinkingMessage") or {}).get("id"),
                         s["local_pick"], s["local_rule"]))
        for r, (pick, rule) in zip(sdk_recs, sdk_resolve(rows)):
            if pick != r["pm"]["sdk"]["local_pick"]:
                counters["sdk_history_overrides_row_local_pick"] += 1
            sdk_apply(r["pm"], pick, rule)
    for r in recs:
        if not r["syn"]:
            pm = r["pm"]
            mid = pm["api_msg_id"]
            if mid and not ZERO_MSG_ID.match(str(mid)):
                r["gkey"] = "id:" + str(mid)
            elif (pm["shape"] == "openai-chat" and pm["calls"]) or (pm["shape"] == "gemini" and len(pm["calls"]) >= 2):
                r["gkey"] = _msg_fingerprint(r["d"].get("agent_messages"))
    consumed = collections.defaultdict(set)
    for r in recs:
        if r["syn"] or r["a"] is None:
            continue
        r["idx"], r["how"] = match_call(r["a"], r["an"], r["pm"]["calls"], consumed[r["gkey"]] if r["gkey"] else ())
        if r["gkey"] and r["idx"] is not None:
            consumed[r["gkey"]].add(r["idx"])
    recs.sort(key=lambda r: (r["ts"], r["idx"] if (r["gkey"] and r["idx"] is not None) else -1, r["d"]["id"]))

    # ties on created_at
    tss = [r["ts"] for r in recs]
    tie_rows, tie_groups, tie_same_msg = 0, 0, 0
    i = 0
    while i < len(recs):
        j = i
        while j + 1 < len(recs) and tss[j + 1] == tss[i]:
            j += 1
        if j > i:
            tie_groups += 1
            tie_rows += j - i + 1
            if len({recs[k]["gkey"] for k in range(i, j + 1)}) == 1 and recs[i]["gkey"]:
                tie_same_msg += 1
        i = j + 1
    counters["tie_groups"] += tie_groups
    counters["tie_rows"] += tie_rows
    counters["tie_groups_within_one_message"] += tie_same_msg

    # provider call ids: usable only when present, not all-zero, unique among the session's executed calls
    pids = collections.Counter()
    for r in recs:
        if r["idx"] is not None:
            p = r["pm"]["calls"][r["idx"]].get("id")
            if p:
                pids[p] += 1

    # unexecuted calls per message group (or per ungrouped row)
    unexec = {}
    for r in recs:
        if r["syn"]:
            continue
        k = r["gkey"] or ("row:" + r["d"]["id"])
        if k in unexec:
            continue
        used = consumed[r["gkey"]] if r["gkey"] else ({r["idx"]} if r["idx"] is not None else set())
        unexec[k] = [{"name": c.get("name"), "id": c.get("id")} for i2, c in enumerate(r["pm"]["calls"]) if i2 not in used]

    events, seen_group, seen_text = [], set(), collections.defaultdict(set)
    sdk_seen, sdk_seen_text_ids, sdk_reasoned = set(), set(), set()  # Agent-SDK message ids seen in earlier rows

    def emit(r, kind, **kw):
        d, pm = r["d"], r["pm"]
        ev = {"corpus": CORPUS, "session_id": sid, "stratum": stratum, "seq": len(events), "kind": kind,
              "ts": ir.iso(d.get("created_at")), "ts_kind": "shared_turn", "tool": None, "tool_raw": None, "call_id": None,
              "args": None, "command": None, "text": None, "stderr": None, "native_error": None, "exit_code": None,
              "usage_in": None, "usage_out": None, "usage_cache_read": None, "usage_cache_create": None,
              "api_msg_id": (r["gkey"][3:] if (r["gkey"] or "").startswith("id:") else None), "request_id": None,
              "model": pm["model"] or model_string, "is_subagent": False, "parent_call_id": None, "agent_id": None,
              "uuid": d.get("id"), "parent_uuid": None, "extra": None}
        ev.update(kw)
        events.append(ev)
        return ev

    for r in recs:
        d, pm, a, an = r["d"], r["pm"], r["a"], r["an"]
        counters["rows"] += 1
        counters["rows_shape:" + pm["shape"]] += 1
        if r["syn"]:
            counters["synthetic_rows:" + r["syn"]] += 1
            ex = {"synthetic": r["syn"], "action": a, "shape": pm["shape"]}
            if pm["calls"]:
                ex["provider_call_id"] = pm["calls"][0].get("id")
            if pm["usage"]:
                ex["synthetic_usage"] = {k: v for k, v in pm["usage"].items() if k != "detail"}
            for k in ("output", "error", "system"):
                if d.get(k) is not None:
                    ex[k] = d.get(k)
            emit(r, "system", extra=ir.j(ex))
            continue
        counters["non_synthetic_rows_shape:" + pm["shape"]] += 1
        first = r["gkey"] is None or r["gkey"] not in seen_group
        if r["gkey"]:
            seen_group.add(r["gkey"])
        if not first:
            counters["dup_message_rows"] += 1
            counters["dup_message_rows_by_shape:" + pm["shape"]] += 1
        sdk = pm.get("sdk") if (pm.get("sdk") or {}).get("pick") else None
        sdk_other = None
        head = {}  # message-level extras that go on the row's first event
        if sdk:
            # reasoning belongs to the message that holds it: count it once per SDK message id, whichever row is acting
            rc = {"reasoning_chars": 0, "reasoning_items": 0, "reasoning_encrypted": 0}
            for m in sdk["msgs"].values():
                rk = (m["key"], m.get("id"))  # per (block, message id): textMessage and thinkingMessage may share an id
                if m.get("id") and rk not in sdk_reasoned:
                    sdk_reasoned.add(rk)
                    for f in rc:
                        rc[f] += m[f]
                    counters["sdk_messages_with_reasoning_attached"] += int(m["reasoning_items"] > 0)
            head.update({f: v for f, v in rc.items() if v})
            tid = (sdk["msgs"].get("textMessage") or {}).get("id")
            hid = (sdk["msgs"].get("thinkingMessage") or {}).get("id")
            counters["sdk_rows"] += 1
            counters["sdk_rule:" + str(sdk["rule"])] += 1
            if tid and hid and tid != hid:
                counters["sdk_rows_ids_differ"] += 1
                counters["sdk_rows_ids_differ_acting:" + sdk["pick"]] += 1
            counters["sdk_rows_new_text_msg"] += int(bool(tid) and tid not in sdk_seen)
            counters["sdk_rows_new_thinking_msg"] += int(bool(hid) and hid not in sdk_seen)
            if tid in sdk_seen_text_ids:  # the pre-fix grouping key (textMessage id) repeats an earlier row's
                counters["sdk_rows_repeating_earlier_text_id"] += 1
                counters["sdk_rows_repeating_earlier_text_id_with_new_thinking_id"] += int(bool(hid) and hid not in sdk_seen)
            okey = "thinkingMessage" if sdk["pick"] == "textMessage" else "textMessage"
            om = sdk["msgs"].get(okey)
            if om and om.get("id") and om["id"] != pm["api_msg_id"]:
                sdk_other = {"block": okey, "id": om["id"], "new_in_row": om["id"] not in sdk_seen,
                             "usage": {k: v for k, v in (om.get("usage") or {}).items() if k != "detail"} or None}
            sdk_seen.update(x for x in (tid, hid) if x)
            if tid:
                sdk_seen_text_ids.add(tid)
        elif first:
            if pm["reasoning_chars"]:
                head["reasoning_chars"] = pm["reasoning_chars"]
            if pm["reasoning_items"]:
                head["reasoning_items"] = pm["reasoning_items"]
            if pm["reasoning_encrypted"]:
                head["reasoning_encrypted"] = pm["reasoning_encrypted"]
        if first:
            ue = unexec.get(r["gkey"] or ("row:" + d["id"]))
            if ue:
                head["unexecuted_calls"] = ue
                counters["unexecuted_calls"] += len(ue)
                counters["unexecuted_calls_by_shape:" + pm["shape"]] += len(ue)
                counters["unexecuted_calls_talk_only_turn" if a is None else "unexecuted_calls_on_action_turn"] += len(ue)
        usage_kw, tail = {}, {}
        if first and pm["usage"]:
            u = pm["usage"]
            usage_kw = {k: u.get(k) for k in ("usage_in", "usage_out", "usage_cache_read", "usage_cache_create")}
            if u.get("detail"):
                tail["usage_detail"] = u["detail"]
        if first and pm["timing"]:
            tail["timing"] = pm["timing"]
        if pm["meta"]:
            tail["meta"] = pm["meta"]
        if not first:
            tail["dup_message"] = True
        if sdk:
            tail["sdk"] = {"acting": sdk["pick"], "rule": sdk["rule"]}
            if sdk_other:
                tail["sdk"]["other"] = sdk_other
        if usage_kw:
            counters["rows_with_usage_by_shape:" + pm["shape"]] += 1
        texts = []
        for x in pm["texts"]:
            tkey = ("id:" + str(x["msg_id"])) if x.get("msg_id") else r["gkey"]  # SDK: dedupe per holding message
            if tkey and x["text"] in seen_text[tkey]:
                continue
            if tkey:
                seen_text[tkey].add(x["text"])
            texts.append(x)
        asst = []
        for x in texts:
            ex, kw = {}, {}
            if x.get("refusal"):
                ex["refusal"] = True
            if x.get("item_id"):
                ex["item_id"] = x["item_id"]
            if x.get("msg_id"):
                kw["api_msg_id"] = x["msg_id"]
                # an SDK text message that is not the acting one is a separate, earlier API response: its usage goes
                # on its own (first) text event, once per message id
                if (sdk_other and x["msg_id"] == sdk_other["id"] and ("id:" + x["msg_id"]) not in seen_group
                        and sdk_other["usage"]):
                    seen_group.add("id:" + x["msg_id"])
                    kw.update({k: sdk_other["usage"].get(k) for k in ("usage_in", "usage_out", "usage_cache_read",
                                                                       "usage_cache_create")})
                    ex["sdk_usage_of_non_acting_text_message"] = True
                    sdk_other["usage_on_text_event"] = True
                    counters["sdk_non_acting_text_usage_on_text_event"] += 1
            asst.append(emit(r, "assistant", text=x["text"], extra=ex, **kw))
        if sdk_other and sdk_other["new_in_row"] and not sdk_other.get("usage_on_text_event"):
            counters["sdk_new_non_acting_message_usage_in_extra_only"] += 1
        if a is None:
            counters["talk_only_rows"] += 1
            if not asst or (sdk and asst[-1]["api_msg_id"] != pm["api_msg_id"]):
                asst.append(emit(r, "assistant", text="", extra={"empty_text": True}))
                counters["empty_text_assistant_events"] += 1
            asst[0]["extra"].update(head)
            asst[-1].update(usage_kw)
            asst[-1]["extra"].update(tail)
            if any(d.get(k) is not None for k in ("output", "error", "system")):
                emit(r, "system", text=d.get("output"), stderr=d.get("error"),
                     extra=ir.j({"talk_only_turn_output": True, "system": d.get("system")}))
                counters["talk_only_rows_with_output"] += 1
        else:
            idx, how = r["idx"], r["how"]
            counters["call_match:" + str(how)] += 1
            c = pm["calls"][idx] if idx is not None else {}
            pid = c.get("id")
            ex = {"action": an, "call_match": how, "msg_tool_calls": len(pm["calls"])}
            if pid and not ZERO_CALL_ID.match(str(pid)) and pids[pid] == 1:
                call_id = str(pid)
                counters["call_id_provider"] += 1
            else:
                call_id = "turn:" + d["id"]
                ex["call_id_fallback"] = "no_provider_call" if not pid else ("zero_id" if ZERO_CALL_ID.match(str(pid)) else "duplicate_in_session")
                counters["call_id_fallback:" + ex["call_id_fallback"]] += 1
                if pid:
                    ex["provider_call_id"] = pid
            if c.get("item_id") and c.get("item_id") != pid:
                ex["item_id"] = c["item_id"]
            if not asst:
                ex.update(head)
            else:
                asst[0]["extra"].update(head)
            ex.update(tail)
            tool = action_tool(an)
            if an == "empty" or an.startswith("other:"):  # e.g. tool input cut off by max_tokens -> agent_action {}
                nm = c.get("name")
                tool = "gui" if nm in GUI_TOOL_NAMES else (ir.normalize_tool(nm) if nm else "unknown")
                counters["calls_without_action_name:" + str(tool)] += 1
            tool_raw = c.get("name") or an
            emit(r, "call", tool=tool, tool_raw=tool_raw, call_id=call_id, args=ir.j(a),
                 command=a.get("command") if an == "bash" else None, extra=ir.j(ex), **usage_kw)
            rex = {"output_null": d.get("output") is None, "error_null": d.get("error") is None,
                   "screenshot_is_redacted": d.get("screenshot_is_redacted"),
                   "has_redaction_been_overruled": d.get("has_redaction_been_overruled"), "updated_at": d.get("updated_at")}
            if d.get("system") is not None:
                rex["system"] = d.get("system")
            emit(r, "result", tool=tool, tool_raw=tool_raw, call_id=call_id, text=d.get("output"), stderr=d.get("error"),
                 extra=ir.j(rex))
        for ev in asst:
            ev["extra"] = ir.j(ev["extra"] or None)
    return events


def sdk_raw_check(df, lines, ids):
    """Check the IR's Agent-SDK events against the raw lines with plain json access (not parse_message):
    reasoning per session = sum of thinking text over distinct thinkingMessage ids; call api_msg_id vs the two raw ids;
    call usage = raw usage of the message named by api_msg_id (same id -> textMessage); every raw message id has usage on
    at most one event."""
    c = collections.Counter()
    ex = pd.Series([json.loads(e) if isinstance(e, str) else {} for e in df["extra"]], index=df.index)
    for sid in ids:
        raw = [json.loads(x) for x in lines.get(sid, []) if b'"_sdkFormat"' in x]
        raw = [d for d in raw if isinstance(d.get("agent_messages"), dict) and d["agent_messages"].get("_sdkFormat")]
        if not raw:
            continue
        msgs, seen_h, reason = {}, set(), 0
        for d in sorted(raw, key=lambda d: (pd.Timestamp(d["created_at"]), d["id"])):
            am = d["agent_messages"]
            tm = (am.get("textMessage") or {}).get("message") or {}
            th = (am.get("thinkingMessage") or {}).get("message") or {}
            if th.get("id") and th["id"] not in seen_h:
                seen_h.add(th["id"])
                reason += sum(len(b.get("thinking") or "") for b in th.get("content") or [] if isinstance(b, dict))
            msgs[d["id"]] = (tm, th)
        m = (df["session_id"] == sid).to_numpy()
        s, se = df[m], ex[m]
        c["sessions"] += 1
        c["rows"] += len(raw)
        c["sessions_reasoning_chars_equal"] += int(sum(e.get("reasoning_chars", 0) for e in se) == reason)
        c["reasoning_chars_raw"] += reason
        c["reasoning_chars_ir"] += sum(e.get("reasoning_chars", 0) for e in se)
        for uuid, api, ui, uo, ucr, ucc in s.loc[s.kind == "call", ["uuid", "api_msg_id", "usage_in", "usage_out",
                                                                     "usage_cache_read", "usage_cache_create"]].itertuples(index=False):
            if uuid not in msgs:
                continue
            tm, th = msgs[uuid]
            if tm.get("id") != th.get("id"):
                c["calls_ids_differ"] += 1
                c["calls_ids_differ_api_eq_thinking_id"] += int(api == th.get("id"))
                c["calls_ids_differ_api_eq_text_id"] += int(api == tm.get("id"))
            if pd.notna(ui):
                u = (th if (api == th.get("id") and th.get("id") != tm.get("id")) else tm).get("usage") or {}
                c["calls_with_usage"] += 1
                c["calls_usage_equal_raw_message"] += int((ui, uo, ucr, ucc) == (
                    u.get("input_tokens"), u.get("output_tokens"), u.get("cache_read_input_tokens"),
                    u.get("cache_creation_input_tokens")))
        raw_ids = {x.get("id") for pair in msgs.values() for x in pair if x.get("id")}
        ub = s[s["usage_in"].notna()]
        c["raw_distinct_message_ids"] += len(raw_ids)
        c["raw_ids_with_usage_on_an_event"] += len(raw_ids & set(ub["api_msg_id"].dropna()))
        c["usage_events_api_msg_id_not_in_raw"] += len(set(ub["api_msg_id"].dropna()) - raw_ids)
        c["usage_events_repeating_an_api_msg_id"] += int(ub["api_msg_id"].dropna().duplicated().sum())
    return dict(c)


def build_split(name, ids, lines, sess_by_id, counters):
    evs = []
    for sid in ids:
        s = sess_by_id[sid]
        evs += build_session(sid, s["stratum"], s["model_string"], lines.get(sid, []), counters)
    df = ir.to_frame(evs)
    v = ir.validate(df)
    df.to_parquet(SPLIT_PQ.format(name), index=False)
    return df, v


# ----------------------------------------------------------------------------------------------------------------------
# report helpers

def _vc(s):
    return {str(k): int(v) for k, v in s.value_counts(dropna=False).items()}


def _frac(k, n):
    return {"k": int(k), "n": int(n), "frac": (round(k / n, 6) if n else None)}


def population_sdk(turns, p1):
    """Agent-SDK (textMessage + thinkingMessage) rows in the whole table: how often the two blocks come from different
    API responses and which one the loader keys the row on (pass-1 index after resolve_sdk_turns)."""
    x = turns[turns["sdk_pick"].notna()].copy()
    x["_ts"] = pd.to_datetime(x["created_at"], format="ISO8601")
    x = x.sort_values(["session_id", "_ts", "id"])
    diff = x["sdk_text_msg_id"].notna() & x["sdk_thinking_msg_id"].notna() & (x["sdk_text_msg_id"] != x["sdk_thinking_msg_id"])
    rep_text = rep_text_new_think = rep_acting = 0
    for _, g in x.groupby("session_id", sort=False):
        seen, seen_text, seen_act = set(), set(), set()
        for ti, hi, ai in zip(g["sdk_text_msg_id"], g["sdk_thinking_msg_id"], g["api_msg_id"]):
            if ti in seen_text:
                rep_text += 1
                rep_text_new_think += int(hi not in seen)
            rep_acting += int(ai in seen_act)
            seen.update((ti, hi))
            seen_text.add(ti)
            seen_act.add(ai)
    d = x[diff]
    return {"rows": int(len(x)), "sessions": int(x["session_id"].nunique()),
            "talk_only_rows": int((x["action"] == "none").sum()), "rows_with_usage": int(x["has_usage"].sum()),
            "rows_text_id_ne_thinking_id": int(diff.sum()),
            "ids_differ_prompt_tokens_larger": _vc(d["sdk_prompt_cmp"]),
            "ids_differ_cache_read_larger": _vc(d["sdk_cache_read_cmp"]),
            "ids_differ_acting_message": _vc(d["sdk_pick"]),
            "rule": _vc(x["sdk_rule"]),
            "history_overrides_of_row_local_pick": p1.get("sdk_history_resolution", {}).get("rows_overriding_row_local_pick"),
            "pre_fix_key_rows_repeating_earlier_text_id": rep_text,
            "pre_fix_key_of_which_new_thinking_id": rep_text_new_think,
            "rows_repeating_earlier_acting_id": rep_acting}


def population_report(turns, sessions, sess_extra):
    t = turns
    real = t[t["synthetic"].isna()]
    shapes = sorted(t["shape"].unique())
    by_shape = {}
    for sh in shapes:
        x = real[real["shape"] == sh]
        by_shape[sh] = {"rows_non_synthetic": int(len(x)),
                        "usage": _frac(x["has_usage"].sum(), len(x)),
                        "server_timing": _frac(x["server_timing_dur_ms"].notna().sum(), len(x)),
                        "http_date": _frac(x["http_date"].notna().sum(), len(x)),
                        "row_model": _frac(x["row_model"].notna().sum(), len(x)),
                        "api_msg_id": _frac(x["api_msg_id"].notna().sum(), len(x)),
                        "provider_call_id_on_action_rows": _frac(x.loc[x.action != "none", "provider_call_id"].notna().sum(),
                                                                 int((x.action != "none").sum()))}
    act = t["action"]
    cls = np.where(act == "none", "talk_only", np.where(act.isin(["bash", "restart"]), "shell",
                   np.where(act.isin(list(GUI_ACTIONS)), "gui", "other")))
    fill = {}
    for c in ["talk_only", "shell", "gui", "other"]:
        m = (cls == c) & t["synthetic"].isna().to_numpy()
        x = t[m]
        fill[c] = {"rows": int(m.sum()), "output_non_null": _frac(x["has_output"].sum(), len(x)),
                   "output_non_empty": _frac((x["output_chars"] > 0).sum(), len(x)),
                   "error_non_null": _frac(x["has_error"].sum(), len(x)),
                   "error_non_empty": _frac((x["error_chars"] > 0).sum(), len(x)),
                   "system_non_null": _frac(x["has_system"].sum(), len(x))}
    deg = t[t["provider_call_id"].fillna("").str.match(ZERO_CALL_ID.pattern)]
    upd = (pd.to_datetime(t["updated_at"], format="ISO8601") - pd.to_datetime(t["created_at"], format="ISO8601")).dt.total_seconds()
    return {
        "turn_rows": int(len(t)), "sessions_with_turns": int(t["session_id"].nunique()), **sess_extra,
        "row_id_duplicates": int(t["id"].duplicated().sum()), "line_prefix_ok": _frac(t["prefix_ok"].sum(), len(t)),
        "turns_by_shape": _vc(t["shape"]), "turns_by_row_model": _vc(t["row_model"].fillna("<none>")),
        "turns_by_model_string": {str(k): int(v) for k, v in sessions.groupby("model_string")["n_turns"].sum().items()},
        "turns_by_month": {k: int(v) for k, v in t["created_at"].str.slice(0, 7).value_counts().sort_index().items()},
        "sessions_by_stratum": _vc(sessions["stratum"]),
        "turns_by_stratum": {k: int(v) for k, v in sessions.groupby("stratum")["n_turns"].sum().items()},
        "sessions_by_shape": _vc(sessions["shape"]),
        "session_n_turns": stats.describe(sessions["n_turns"]),
        "actions": _vc(t["action"]),
        "synthetic_turns_by_rule": _vc(t["synthetic"].dropna()),
        "synthetic_turns_by_action": _vc(t.loc[t["synthetic"].notna(), "action"]),
        "sessions_with_synthetic_turn": int((sessions["n_synthetic_turns"] > 0).sum()),
        "sessions_only_synthetic": int((sessions["n_synthetic_turns"] == sessions["n_turns"]).sum()),
        "fill_by_action_class_non_synthetic": fill,
        "fields_by_shape_non_synthetic": by_shape,
        "zero_provider_call_ids": {"rows": int(len(deg)), "by_shape": _vc(deg["shape"])},
        "talk_only_rows_with_tool_calls_in_message": int(((t.action == "none") & (t.n_calls > 0)).sum()),
        "rows_sharing_message_id_within_session_by_shape": _vc(real.dropna(subset=["api_msg_id"]).loc[
            lambda x: x.duplicated(["session_id", "api_msg_id"], keep=False), "shape"]),
        "gemini_server_timing_fill_by_month_non_synthetic": {
            m: _frac(x["server_timing_dur_ms"].notna().sum(), len(x))
            for m, x in real[real["shape"] == "gemini"].groupby(real["created_at"].str.slice(0, 7))},
        "row_level_match_how": _vc(t["match_how"]),
        "rows_with_reasoning_text": _frac((real["reasoning_chars"] > 0).sum(), len(real)),
        "rows_with_encrypted_reasoning": _frac((real["reasoning_encrypted"] > 0).sum(), len(real)),
        "screenshot_is_redacted": _vc(t["screenshot_is_redacted"]),
        "updated_minus_created_seconds_all_rows": stats.describe(upd),
        "updated_minus_created_over_1s": _frac((upd > 1).sum(), len(upd)),
        "updated_minus_created_over_1s_by_redaction_flag": {str(k): int(v) for k, v in
                                                            t.loc[(upd > 1).to_numpy(), "screenshot_is_redacted"].value_counts(dropna=False).items()},
        "created_at_fractional_digits": _vc(t["created_at"].str.extract(r"\.(\d+)$")[0].str.len().fillna(0).astype(int)),
    }


def split_report(df, v, counters, sess_by_id, ids):
    calls = df[df.kind == "call"]
    res = df[df.kind == "result"]
    asst = df[df.kind == "assistant"]
    ex = [json.loads(x) if isinstance(x, str) else {} for x in df["extra"]]
    df = df.assign(_ex=ex)
    shape_of = {sid: sess_by_id[sid]["shape"] for sid in ids}
    # one usage-bearing event per turn row at most -> fill per non-synthetic turn row (uuid)
    rows = df[df.kind.isin(["call", "assistant"])].groupby("uuid").agg(
        session_id=("session_id", "first"), has_usage=("usage_in", lambda s: s.notna().any()),
        has_dur=("_ex", lambda s: any("timing" in e and e["timing"].get("server_timing_dur_ms") is not None for e in s)),
        has_date=("_ex", lambda s: any("timing" in e and e["timing"].get("http_date") for e in s)),
        dup=("_ex", lambda s: any(e.get("dup_message") for e in s)))
    rows["shape"] = rows["session_id"].map(shape_of)
    first_rows = rows[~rows["dup"]]
    usage_by_shape, timing_by_shape = {}, {}
    for sh, x in first_rows.groupby("shape"):
        usage_by_shape[sh] = _frac(x["has_usage"].sum(), len(x))
        timing_by_shape[sh] = {"server_timing_dur": _frac(x["has_dur"].sum(), len(x)), "http_date": _frac(x["has_date"].sum(), len(x))}
    # call/result integrity
    per_sess_dup = calls.groupby("session_id")["call_id"].apply(lambda s: int(s.duplicated().sum())).sum()
    joined = calls[["session_id", "call_id"]].merge(res[["session_id", "call_id"]], how="outer", indicator=True)
    # timing semantics check: created_at - HTTP date (Gemini) and updated_at - created_at
    lag, upd = [], []
    for ts, e, k in zip(df["ts"], df["_ex"], df["kind"]):
        t = e.get("timing") if isinstance(e, dict) else None
        if t and t.get("http_date"):
            lag.append((ir.parse_ts(ts) - ir.parse_ts(t["http_date"])).total_seconds())
        if k == "result" and e.get("updated_at"):
            upd.append((ir.parse_ts(ir.iso(e["updated_at"])) - ir.parse_ts(ts)).total_seconds())
    durs = [e["timing"]["server_timing_dur_ms"] for e in df["_ex"] if "timing" in e and e["timing"].get("server_timing_dur_ms") is not None]
    # usage is attached at most once per provider message id: count usage-bearing events that share (session, api_msg_id)
    ub = df[df["usage_in"].notna() & df["api_msg_id"].notna()]
    rows_usage = {k.split(":", 1)[1]: int(x) for k, x in counters.items() if k.startswith("rows_with_usage_by_shape:")}
    rows_real = {k.split(":", 1)[1]: int(x) for k, x in counters.items() if k.startswith("non_synthetic_rows_shape:")}
    sdk_calls = df[(df.kind == "call") & df["_ex"].map(lambda e: "sdk" in e)]
    sdk_texts = df[(df.kind == "assistant") & df["_ex"].map(lambda e: bool(e.get("sdk_usage_of_non_acting_text_message")))]
    sdk = {
        "rows": int(counters["sdk_rows"]),
        "rule": {k.split(":", 1)[1]: int(x) for k, x in counters.items() if k.startswith("sdk_rule:")},
        "rows_text_id_ne_thinking_id": int(counters["sdk_rows_ids_differ"]),
        "rows_text_id_ne_thinking_id_by_acting_message": {k.split(":", 1)[1]: int(x) for k, x in counters.items()
                                                          if k.startswith("sdk_rows_ids_differ_acting:")},
        "history_overrides_of_row_local_pick": int(counters["sdk_history_overrides_row_local_pick"]),
        "rows_with_new_text_msg_id": int(counters["sdk_rows_new_text_msg"]),
        "rows_with_new_thinking_msg_id": int(counters["sdk_rows_new_thinking_msg"]),
        "pre_fix_key_rows_repeating_earlier_text_id": int(counters["sdk_rows_repeating_earlier_text_id"]),
        "pre_fix_key_of_which_new_thinking_id": int(counters["sdk_rows_repeating_earlier_text_id_with_new_thinking_id"]),
        "dup_message_rows_acting_id_repeated": int(counters["dup_message_rows_by_shape:anthropic-sdk"]),
        "call_events": int(len(sdk_calls)),
        "call_events_with_usage": _frac(sdk_calls["usage_in"].notna().sum(), len(sdk_calls)),
        "call_events_distinct_api_msg_id": int(sdk_calls["api_msg_id"].nunique()),
        "non_acting_text_message_usage_on_text_event": int(len(sdk_texts)),
        "new_non_acting_message_usage_in_extra_only": int(counters["sdk_new_non_acting_message_usage_in_extra_only"]),
        "messages_with_reasoning_attached": int(counters["sdk_messages_with_reasoning_attached"]),
    }
    rep = {
        "validate": {k: int(x) for k, x in v.items()},
        "sessions": int(df.session_id.nunique()), "sessions_requested": len(ids),
        "events_by_kind": _vc(df["kind"]),
        "events_by_stratum": _vc(df["stratum"]),
        "sessions_by_stratum": _vc(df.drop_duplicates("session_id")["stratum"]),
        "turn_rows": int(counters["rows"]),
        "rows_by_shape": {k.split(":", 1)[1]: int(x) for k, x in counters.items() if k.startswith("rows_shape:")},
        "synthetic_rows_by_rule": {k.split(":", 1)[1]: int(x) for k, x in counters.items() if k.startswith("synthetic_rows:")},
        "talk_only_rows": int(counters["talk_only_rows"]),
        "empty_text_assistant_events": int(counters["empty_text_assistant_events"]),
        "talk_only_rows_with_output": int(counters["talk_only_rows_with_output"]),
        "calls_by_tool": _vc(calls["tool"]),
        "calls_by_tool_raw": _vc(calls["tool_raw"]),
        "shell_share_of_calls": _frac((calls["tool"] == "shell").sum(), len(calls)),
        "shell_calls_with_command": _frac(calls.loc[calls.tool == "shell", "command"].notna().sum(), int((calls.tool == "shell").sum())),
        "results": {"n": int(len(res)), "output_non_null": _frac(res["text"].notna().sum(), len(res)),
                    "output_non_empty": _frac((res["text"].fillna("").str.len() > 0).sum(), len(res)),
                    "stderr_non_null": _frac(res["stderr"].notna().sum(), len(res)),
                    "stderr_non_empty": _frac((res["stderr"].fillna("").str.len() > 0).sum(), len(res))},
        "results_shell": {"n": int((res.tool == "shell").sum()),
                          "output_non_empty": _frac((res.loc[res.tool == "shell", "text"].fillna("").str.len() > 0).sum(), int((res.tool == "shell").sum())),
                          "stderr_non_empty": _frac((res.loc[res.tool == "shell", "stderr"].fillna("").str.len() > 0).sum(), int((res.tool == "shell").sum()))},
        "usage_fill_by_shape_first_row_of_message": usage_by_shape,
        "usage_fill_by_row_shape_all_non_synthetic_rows": {sh: _frac(rows_usage.get(sh, 0), n) for sh, n in sorted(rows_real.items())},
        "usage_events_sharing_session_api_msg_id": int(ub.duplicated(["session_id", "api_msg_id"]).sum()),
        "usage_events_with_null_api_msg_id": int((df["usage_in"].notna() & df["api_msg_id"].isna()).sum()),
        "anthropic_sdk": sdk,
        "timing_fill_by_shape_first_row_of_message": timing_by_shape,
        "call_id_source": {k.split(":", 1)[-1] if ":" in k else k: int(x) for k, x in counters.items()
                           if k == "call_id_provider" or k.startswith("call_id_fallback:")},
        "call_match": {k.split(":", 1)[1]: int(x) for k, x in counters.items() if k.startswith("call_match:")},
        "dup_message_rows": int(counters["dup_message_rows"]),
        "dup_message_rows_by_shape": {k.split(":", 1)[1]: int(x) for k, x in counters.items() if k.startswith("dup_message_rows_by_shape:")},
        "unexecuted_calls": int(counters["unexecuted_calls"]),
        "unexecuted_calls_by_shape": {k.split(":", 1)[1]: int(x) for k, x in counters.items() if k.startswith("unexecuted_calls_by_shape:")},
        "unexecuted_calls_on_talk_only_turns": int(counters["unexecuted_calls_talk_only_turn"]),
        "unexecuted_calls_on_action_turns": int(counters["unexecuted_calls_on_action_turn"]),
        "calls_whose_action_has_no_name_by_tool": {k.split(":", 1)[1]: int(x) for k, x in counters.items() if k.startswith("calls_without_action_name:")},
        "call_stop_reason_when_action_empty": _vc(pd.Series([e.get("meta", {}).get("stop_reason") or e.get("meta", {}).get("finish_reason")
                                                             for e, k in zip(df["_ex"], df["kind"]) if k == "call" and e.get("action") == "empty"], dtype=object).astype(str)),
        "created_at_ties": {"tie_groups": int(counters["tie_groups"]), "rows_in_ties": int(counters["tie_rows"]),
                            "tie_groups_within_one_message": int(counters["tie_groups_within_one_message"]),
                            "tie_break": "(created_at, executed-call index within the shared message, row id)"},
        "call_ids_duplicated_within_session": int(per_sess_dup),
        "calls_without_result": int((joined["_merge"] == "left_only").sum()),
        "results_without_call": int((joined["_merge"] == "right_only").sum()),
        "ts_null": int(df["ts"].isna().sum()),
        "assistant_text_chars": stats.describe(asst["text"].fillna("").str.len()),
        "assistant_text_containing_thinking_tag": _frac(asst["text"].fillna("").str.contains("<thinking>", regex=False).sum(), len(asst)),
        "usage_in_on_events": _frac(df["usage_in"].notna().sum(), len(df)),
        "created_minus_http_date_seconds": stats.describe(lag),
        "server_timing_dur_ms": stats.describe(durs),
        "result_updated_minus_created_seconds": stats.describe(upd),
    }
    return rep


# ----------------------------------------------------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--reuse-pass1", action="store_true", help="reuse analysis/cache/aiv_cu_turns.parquet if present")
    args = ap.parse_args(argv)
    os.makedirs(os.path.dirname(SAMPLE_JSON), exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    turns, p1 = run_pass1(reuse=args.reuse_pass1)
    sessions, sess_extra = build_sessions(turns)
    sessions.to_parquet(SESS_PQ, index=False)
    print("strata:", sessions.stratum.value_counts().to_dict(), flush=True)

    pop = sessions[["session_id", "stratum"]].assign(length=sessions["n_turns"].astype(int))
    smp = sample.draw(pop, CORPUS)
    sample.save(smp, SAMPLE_JSON)
    print(f"sample: A={len(smp['A'])} B={len(smp['B'])}", flush=True)

    lines, p2 = pass2_extract(smp["A"] + smp["B"])
    print("pass2:", p2, flush=True)
    sess_by_id = sessions.set_index("session_id")[["stratum", "model_string", "shape"]].to_dict("index")
    splits = {}
    p1_key = turns.set_index("id")[["shape", "api_msg_id", "usage_in", "usage_out"]]
    for name in ("A", "B"):
        counters = collections.Counter()
        df, v = build_split(name, smp[name], lines, sess_by_id, counters)
        splits[name] = split_report(df, v, counters, sess_by_id, smp[name])
        # pass 1 (row-parallel + resolve_sdk_turns) and pass 2 (per session) must key every executed turn the same way
        c = df[df.kind == "call"][["uuid", "api_msg_id", "usage_in", "usage_out"]].astype(object)
        c = c.join(p1_key.astype(object), on="uuid", rsuffix="_p1")
        same_id = (c["api_msg_id"].isna() & c["api_msg_id_p1"].isna()) | (c["api_msg_id"] == c["api_msg_id_p1"])
        has_u = c["usage_in"].notna()
        same_u = (c.loc[has_u, "usage_in"].astype(float) == c.loc[has_u, "usage_in_p1"].astype(float)) & \
                 (c.loc[has_u, "usage_out"].astype(float) == c.loc[has_u, "usage_out_p1"].astype(float))
        splits[name]["call_events_vs_pass1_index"] = {
            "api_msg_id_equal": _frac(same_id.sum(), len(c)),
            "api_msg_id_differs_by_shape": _vc(c.loc[~same_id.to_numpy(), "shape"]),
            "usage_in_out_equal_where_call_has_usage": _frac(same_u.sum(), int(has_u.sum()))}
        splits[name]["anthropic_sdk_raw_check"] = sdk_raw_check(df, lines, smp[name])
        print(name, v, splits[name]["call_events_vs_pass1_index"], splits[name]["anthropic_sdk_raw_check"], flush=True)

    report = {
        "corpus": CORPUS, "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "loader": "analysis/loaders/load_aiv_cu.py",
        "inputs": {p: os.path.getsize(p) for p in (TURNS, SESSIONS, AGENTS)},
        "throughput": {"benchmark_first_50k_single_process": p1["benchmark_first_50k"], "pass1": p1["pass1"], "pass2": p2},
        "population": population_report(turns, sessions, sess_extra),
        "population_anthropic_sdk": population_sdk(turns, p1),
        "sample": {"seed": smp["seed"], "rule": smp["rule"], "population_sessions": smp["population_sessions"],
                   "A_n": len(smp["A"]), "B_n": len(smp["B"]), "alloc_A": smp["alloc_A"], "alloc_B": smp["alloc_B"]},
        "splits": splits,
        "pass1_unhandled_message_items": p1["unhandled_message_items"],
        "pass1_row_top_level_keys": p1["row_top_level_keys"],
    }
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, default=str)
    print("wrote", REPORT, flush=True)


if __name__ == "__main__":
    main()
