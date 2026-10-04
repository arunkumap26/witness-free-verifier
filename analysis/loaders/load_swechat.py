"""SWE-chat loader: pinned snapshot SALT-NLP/SWE-chat@f66cca95 raw transcripts -> common event IR (analysis/lib/ir.py).

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.loaders.load_swechat
     E split only (Phase E): PYTHONIOENCODING=utf-8 python -m analysis.loaders.load_swechat --split E [--rederive A --scratch DIR]
     -> analysis/cache/swechat_E.parquet + analysis/out/phase_e/swechat_E_build.json; touches nothing below (build_split_e).
main() rebuilds everything end to end and is idempotent (same inputs -> same sample, caches and report):
  analysis/cache/samples/swechat.json        stratified disjoint A/B session lists (lib/sample.py)
  analysis/cache/swechat_population.parquet  one row per session with a transcript: session_id, agent label, stratum, format, length
  analysis/cache/swechat_A.parquet, swechat_B.parquet   IR caches (one row group per chunk of whole sessions)
  analysis/out/build/swechat_build.json      counts: label x format crosstab, per-format A+B stats, full-population pass,
                                             redaction markers, cross-check vs conversations.parquet

SOURCE OF EVENTS
  transcripts/<session_id>.jsonl (5,850 files), NOT conversations.parquet: that table drops tool calls that are present in
  the raw files and keeps subagent traffic only inside progress rows (see analysis/out/recon/swechat_*.txt).
  sessions.parquet supplies the session list and the scaffold label (`agent`). Raw data is opened read-only.

FORMAT DETECTION (by content, never by label; first 4 KB of each file, see sniff())
  opencode     one JSON document {"info": ..., "messages": [...]}
  gemini       one JSON document {"sessionId", "projectHash", "startTime", "messages": [...]} (or bare {"messages": [...]})
  codex        JSONL {timestamp, type: session_meta|turn_context|response_item|event_msg|compacted, payload}
  copilot      JSONL {type: "session.start"|"user.message"|"assistant.message"|"tool.execution_*"|..., data, id, parentId, timestamp}
  cursor       JSONL {role, message: {content: [...]}} with no top-level type and no timestamps
  simple_text  JSONL {type: user|assistant, timestamp, message: <string>} (toy scaffolds "Roger Roger"/"Vogon")
  claude_code  JSONL Claude Code entries (parentUuid / sessionId / type in the CC entry-type set)
  empty / unknown  counted, not parsed
  A first line longer than 4 KB is classified by regex on its prefix.

POPULATION AND STRATA
  Population = every sessions.parquet session_id that has a transcript file (the one without a file is recorded).
  stratum = agent label, case-folded aliases merged ('opencode'->'OpenCode', 'claude-code'->'Claude Code'); labels with
  fewer than 5 sessions -> 'other'. length = non-empty line count (JSONL formats) or number of messages (opencode, gemini;
  for a document that fails to parse, the number of messages salvaged, see below).

COMMON CONVENTIONS (all formats)
  lines     JSONL formats: empty lines skipped; a line that fails json.loads is retried as a run of concatenated JSON
            values (raw_decode; two entries written without a newline) with control characters allowed inside strings;
            a line that still fails is counted in bad_lines and skipped (never repaired by guessing).
  seq       file order (line order; for single-document formats: message order, then part / toolCall order inside a message).
            Ties in ts are never re-sorted: seq is the source order. Consequently ts is not monotone in seq where the
            source interleaves (CC parallel tool results; OpenCode/Gemini emit each call immediately followed by its
            result, so with parallel calls the next call's start precedes the previous result's end). The report
            counts these backward steps per format (ts_backward_steps).
  ts        harness timestamp of the event converted to ISO-8601 UTC keeping the source's fractional digits (ir.iso;
            non-UTC offsets such as +01:00 are converted to UTC here because ir.iso leaves them as written).
            ts_kind='event' when present, 'none' when the source has no stamp for that event (never invented).
  thinking  reasoning / thinking blocks are not emitted; their character count goes to extra.thinking_chars of the next
            assistant or call event (same rule as lib/cc_jsonl.py). Encrypted reasoning contributes 0 characters.
  text      kept verbatim, including the release's redaction markers ([REDACTED:SECRET], <TRUFFLEHOG_REDACTED_...>, bare
            REDACTED). Strings that contain lone UTF-16 surrogates (unencodable in UTF-8/Parquet) have those code points
            replaced with U+FFFD; the count is in the report.
  tool      ir.normalize_tool(tool_raw), plus one local fold: Codex 'shell_command' -> 'shell' (normalize_tool lacks it).
  command   shell command string for shell calls (Codex exec_command.cmd / shell_command.command / shell.command list -> the
            script after '-lc'/'-c', else the joined argv; OpenCode/Gemini/Copilot/CC input.command).
  synthetic call ids  where the source has a call without a usable id (Cursor tool_use; Codex web_search_call with no
            matching web_search_end; OpenCode tool parts whose callID the release redacted to "REDACTED"), call_id =
            "synthetic:<format>:<seq of the call>" and extra.synthetic_call_id = true (OpenCode: extra.source_call_id
            keeps the raw value). The OpenCode result reuses its call's synthetic id, so pairing is preserved.
  Session-level subagents  An OpenCode child session (info.parentID set) and a Codex sub-agent rollout (session_meta.source
            has a 'subagent' key) are subagent sessions in their own right: every event gets is_subagent=True,
            agent_id = the session's own id (Codex: agent_nickname if present), parent_call_id = the parent's spawning call id
            when it can be found in another transcript (OpenCode task tool metadata.sessionId; Codex collab_agent_spawn_end
            new_thread_id), else None. In-file nesting (Claude Code agent_progress) is the other kind of subagent event.
  native_error / exit_code  native_error is True when the harness recorded a failure: an error flag/status (CC is_error,
            OpenCode status=error, Gemini status error/cancelled, Copilot success=false, Codex patch/MCP failure) OR a
            harness-recorded nonzero exit code (Codex exec_command_end.exit_code, OpenCode state.metadata.exit). exit_code is
            filled only from such a structured field, never parsed from text. Both are attached to the result at which the
            model could see the outcome (see Codex unified exec below). Gemini has no structured exit field: a shell result
            whose text says "Exit Code: 1" can carry native_error=False (counted in the report, not repaired).
  usage rows and api_msg_id  ir.py's convention is "dedupe usage on api_msg_id". Every event that carries usage has a
            non-null api_msg_id. Where the source has no id, or the release redacted it, the id is synthetic:
            "synthetic:<format>:<session_id>:<m|u|l|e><n>" (globally unique; shared by the rows of one API response:
            OpenCode message index m<n>, Gemini m<n>, Copilot object index l<n>, Codex token_count u<seq>, post-pass
            safety net e<seq>) with extra.synthetic_api_msg_id = true on the usage-bearing row. A Codex token_count that
            repeats the previous cumulative total (no new API call) shares the previous row's api_msg_id and has its usage
            columns nulled (extra.repeat_of_previous_total, raw values in extra.last_token_usage_repeated), so both naive
            sums and dedupe-on-id sums are right. Consumers should still filter to usage-bearing rows before deduping
            (OpenCode assistant/call rows share the message id but carry no usage).

PER-FORMAT MAPPING
  claude_code  analysis.lib.cc_jsonl.Parser, one per session, fed every parseable line in file order (see that module:
               text->assistant, tool_use/server_tool_use->call, tool_result->result, agent_progress unwrapped with
               is_subagent=True and parent_call_id=parentToolUseID, bash/mcp/hook progress->meta, system->meta,
               duplicate uuids emitted once, attachment/file-history/queue-operation/... entries skipped).
               Local pre-normalization: test-fixture entries of type 'tool_use'/'tool_result' (no CC harness writes these)
               are fed as 'assistant'/'user' so their blocks are not silently dropped. Undecodable lines are counted.
  codex        Two passes over the file. Pass 1 indexes exec_command_end / patch_apply_end / mcp_tool_call_end by call_id,
               the human-typed event_msg.user_message texts, web_search_end records and session_meta.
               response_item.message: role assistant -> assistant; role developer -> system; role user -> user when one of
                 its input_text items equals (stripped) an event_msg.user_message text, else system (AGENTS.md,
                 environment_context, skill bodies, turn_aborted notices, sub-agent prompts...). input_image -> "[image]".
               response_item.reasoning -> thinking_chars (summary + content text; encrypted_content not counted).
               function_call -> call (args = parsed `arguments` JSON re-serialized; unparseable kept raw with
                 extra.args_unparsed). custom_tool_call -> call with args = {"input": <raw input>}.
               function_call_output / custom_tool_call_output -> result (text = output string; a content-item list is
                 joined with "[image]" for images). Joins by call_id:
                   exec_command_end -> exit_code column, native_error = (exit_code != 0), stderr = its stderr field,
                     extra.duration_s, extra.exec_status (completed/failed/declined), extra.exec_source -- on the result at
                     which the model saw the process end:
                     * Unified exec (exec_command with yield_time_ms; write_stdin polls). Its output starts with a harness
                       header; the line before "Output:" reads "Process exited with code N" or "Process running with
                       session ID N" (unified_exec_state() reads only that header, never the command output). If the
                       exec_command's own output says "running", the model has not seen the exit yet, whatever the file
                       order of exec_command_end (the end can be written before a buffered parallel output): that result
                       gets exit_code/native_error/stderr = None and extra.unified_exec_running, extra.exec_end_deferred,
                       extra.unified_exec_session_id. The end is then attached to the first later write_stdin result whose
                       arguments.session_id equals N and whose header says "Process exited" (extra.exec_end_call_id = the
                       exec_command call id). write_stdin results that still say "running" get None. If the model never
                       sees the exit, the end is attached to no result (counted: codex_exec_exit_never_shown_to_model); the
                       exec_command_end meta event below still carries it. Header exit code vs end exit_code disagreements
                       are counted (codex_exec_header_exit_ne_end_exit).
                     * Everything else (legacy shell / shell_command, outputs whose header says "exited", and failures such
                       as "exec_command failed ... SandboxDenied" or "aborted by user") gets the end on its own result.
                   patch_apply_end -> native_error = not success; mcp_tool_call_end -> native_error = ('Err' in result or
                     Ok.isError is true), extra.duration_s. Otherwise native_error/exit_code are None.
                 custom_tool_call_output's JSON-encoded metadata.exit_code is inside the model-visible text, so it is
                 copied to extra.output_metadata_exit_code only (not the exit_code column).
               response_item.web_search_call -> call (server-side tool, no result in the transcript; extra.server_tool),
                 call_id taken from the adjacent event_msg.web_search_end with the same action when present.
               response_item.tool_search_call / tool_search_output -> call / result.
               response_item.ghost_snapshot and other response_item types -> meta.
               event_msg.token_count -> meta with usage_in = last_token_usage.input_tokens, usage_out = output_tokens,
                 usage_cache_read = cached_input_tokens (total_token_usage, reasoning tokens in extra), api_msg_id =
                 synthetic "synthetic:codex:<session>:u<seq>" (Codex logs no response id). A token_count whose
                 total_token_usage equals the previous one with info is a repeat (no new API call): same api_msg_id as the
                 previous row, usage columns None, extra.repeat_of_previous_total. A token_count without info (rate limits
                 only) has no usage and no api_msg_id. No usage is attached to call/assistant events (Codex logs none per
                 response item).
               event_msg.exec_command_end / patch_apply_end / mcp_tool_call_end / collab_*_end / view_image_tool_call /
                 web_search_end -> meta at their own position with parent_call_id = their call_id (exec_command_end
                 also keeps exit_code, duration_s, status, source, process_id in extra; same convention as
                 cc_jsonl's progress meta events) and extra.has_call (False for exec_command_end emitted by nested
                 executions inside the `exec` code-mode tool, which have no function_call of their own).
               event_msg.agent_message / user_message / agent_reasoning -> meta without text (UI echoes of
                 response_items; extra.chars); all other event_msg types -> meta. turn_context -> meta and sets the
                 model column of subsequent events; session_meta -> meta. compacted -> system (text = payload.message)
                 when the message is non-empty, else meta.
  opencode     json.load of the document; on failure the info object and the messages are salvaged one by one with
               JSONDecoder.raw_decode until the first undecodable message (extra counts in report).
               user text part -> user (synthetic=true -> system); assistant text part -> assistant.
               ts = part.time.start, else the message's time.created (then extra.ts_src = "message_created").
               reasoning part -> thinking_chars. tool part -> call (ts = state.time.start, args = state.input) and, when
               state.status is completed or error, a result right after it (ts = state.time.end, text = state.output or
               state.error, exit_code = state.metadata.exit when it is an int, native_error = (status == 'error') or
               (exit_code is not None and exit_code != 0) -- bash parts end "completed" with a nonzero exit, flagged
               extra.native_error_from_exit; small scalar metadata in extra). Pending/running tool parts give a call only.
               step-finish -> meta carrying that step's usage (tokens.input/output/cache.read/cache.write; reasoning
               tokens and cost in extra); usage is NOT copied to assistant/call events (one usage row per API step).
               step-start / patch / subtask / file / compaction parts -> meta (no ts: these parts carry no time).
               assistant message info.error -> one meta event after the message's parts. model = message modelID.
               api_msg_id = message id (each assistant message holds at most one step-finish, i.e. one API step);
               when the release redacted it to "REDACTED" or it is missing: "synthetic:opencode:<session>:m<message index>",
               shared by that message's assistant/call/step-finish/error rows.
  gemini       messages in order. user -> user (content string or list of {text}); gemini -> assistant (content, if
               non-empty), then per toolCall a call (ts = message timestamp) and, when the call has a `result`, a result
               (ts = toolCall.timestamp, text = functionResponse.response.output / .error, native_error = status in
               {error, cancelled}, raw status in extra). thoughts -> thinking_chars. tokens -> usage columns on every
               assistant/call event of the message (api_msg_id = message id, dedupe on it; synthetic per message when
               the message has tokens but no id). info/warning/error -> meta (text kept). No structured exit code.
  cursor       no timestamps (ts_kind none). user text -> user; assistant text -> assistant; tool_use -> call with a
               synthetic call id. The source has no tool results.
  copilot      user.message -> user (text = transformedContent, the text the model saw; extra.human_chars).
               assistant.message -> assistant (non-empty content) + one call per toolRequest (call ts = message ts,
               usage_out = outputTokens, api_msg_id = messageId (synthetic when missing and tokens present),
               reasoningText -> thinking_chars).
               tool.execution_complete -> result (ts = its timestamp, text = result.content or error.message,
               native_error = not success). system.notification and session.compaction_complete (summaryContent) ->
               system. tool.execution_start -> meta (parent_call_id); all other types -> meta. uuid/parent_uuid = id/parentId.
  simple_text  user / assistant with the string message.
"""
import collections
import json
import os
import re
import time
from datetime import timezone
from multiprocessing import Pool

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from analysis.lib import cc_jsonl, ir, sample

CORPUS = "swechat"
LOADER_VERSION = "2"
SNAPSHOT = "SALT-NLP/SWE-chat@f66cca95"
DATA = os.path.join(os.environ.get("SWARMS_DATA", "C:/Swarms/data"), "swe-chat-pinned")
TRANS = os.path.join(DATA, "transcripts")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # analysis/
CACHE = os.path.join(HERE, "cache")
OUT = os.path.join(HERE, "out", "build")
N_PROC = int(os.environ.get("SWECHAT_PROCS", "8"))
FULL_PASS_BUDGET_S = 20 * 60

FORMATS = ["claude_code", "codex", "opencode", "gemini", "cursor", "copilot", "simple_text", "empty", "unknown"]
LABEL_ALIASES = {"opencode": "OpenCode", "claude-code": "Claude Code", "claude code": "Claude Code"}
LOCAL_TOOL_FOLD = {"shell_command": "shell"}
SCHEMA = pa.schema([(c, {"str": pa.string(), "int64": pa.int64(), "Int64": pa.int64(), "boolean": pa.bool_()}[t])
                    for c, t in ir.COLUMNS.items()])

# ---------------------------------------------------------------------------------------------------------------- utils

_OFFSET = re.compile(r"([+-])(\d\d):?(\d\d)$")


def to_iso(ts):
    """ir.iso plus conversion of non-UTC offsets to UTC, keeping the source's fractional digits."""
    if ts is None or ts == "" or isinstance(ts, bool):
        return None
    if isinstance(ts, (int, float)):
        return ir.iso(ts)
    s = str(ts).strip()
    m = _OFFSET.search(s)
    if m and m.group(0) not in ("+00:00", "-00:00", "+0000", "-0000") and "T" in s.replace(" ", "T"):
        dt = ir.parse_ts(s)
        if dt is not None and dt.tzinfo is not None:
            fd = ir.frac_digits(s)
            u = dt.astimezone(timezone.utc)
            out = u.strftime("%Y-%m-%dT%H:%M:%S")
            if fd:
                frac = re.search(r"\.(\d+)", s).group(1)
                out += "." + (u.strftime("%f") + frac[6:])[:fd]
            return out + "Z"
    return ir.iso(s)


def tool_norm(name):
    if name is None:
        return None
    return LOCAL_TOOL_FOLD.get(str(name).strip().lower()) or ir.normalize_tool(name)


def shell_command(tool, args):
    """Shell command string from a call's parsed args (None for non-shell tools)."""
    if tool != "shell" or not isinstance(args, dict):
        return None
    c = args.get("command", args.get("cmd"))
    if isinstance(c, list):
        c = [str(x) for x in c]
        if len(c) >= 3 and c[-2] in ("-lc", "-c", "/c"):
            return c[-1]
        return " ".join(c)
    return c if isinstance(c, str) else None


def small_scalars(d, limit=200, skip=()):
    """Scalar fields of a dict suitable for extra (bool/int/float, strings up to `limit` chars)."""
    out = {}
    if not isinstance(d, dict):
        return out
    for k, v in d.items():
        if k in skip:
            continue
        if isinstance(v, (bool, int, float)) or v is None:
            out[k] = v
        elif isinstance(v, str) and len(v) <= limit:
            out[k] = v
    return out


def dur_s(d):
    """Codex {secs, nanos} -> float seconds."""
    if isinstance(d, dict) and ("secs" in d or "nanos" in d):
        return float(d.get("secs") or 0) + float(d.get("nanos") or 0) / 1e9
    return None


class Session:
    """Event sink for the non-CC formats; mirrors cc_jsonl.Parser._emit's defaults."""

    def __init__(self, session_id, stratum):
        self.session_id, self.stratum, self.events = session_id, stratum, []
        self.pending_thinking = 0
        self.defaults = {}  # session-level overrides (is_subagent, agent_id, parent_call_id)

    def emit(self, kind, ts=None, **kw):
        t = to_iso(ts)
        ev = {"corpus": CORPUS, "session_id": self.session_id, "stratum": self.stratum, "seq": len(self.events),
              "kind": kind, "ts": t, "ts_kind": "event" if t else "none", "tool": None, "tool_raw": None, "call_id": None,
              "args": None, "command": None, "text": None, "stderr": None, "native_error": None, "exit_code": None,
              "usage_in": None, "usage_out": None, "usage_cache_read": None, "usage_cache_create": None,
              "api_msg_id": None, "request_id": None, "model": None, "is_subagent": False, "parent_call_id": None,
              "agent_id": None, "uuid": None, "parent_uuid": None, "extra": None}
        ev.update(self.defaults)
        extra = kw.pop("extra", None)
        if kind in ("assistant", "call") and self.pending_thinking:
            extra = dict(extra or {})
            extra["thinking_chars"] = self.pending_thinking
            self.pending_thinking = 0
        ev.update(kw)
        ev["extra"] = ir.j(extra) if extra else None
        self.events.append(ev)
        return ev


# -------------------------------------------------------------------------------------------------------------- sniffing

_CC_TYPES = r"(queue-operation|file-history-snapshot|summary|progress|system|user|assistant|attachment|last-prompt|" \
            r"permission-mode|custom-title|agent-name|ai-title|pr-link|tool_use|tool_result)"


def sniff_text(head):
    st = head.lstrip("\ufeff \t\r\n")
    if not st:
        return "empty"
    if re.match(r'\{\s*"info"\s*:', st):
        return "opencode"
    if re.match(r'\{\s*"(sessionId|projectHash)"\s*:', st) or re.match(r'\{\s*"messages"\s*:\s*\[', st):
        return "gemini"
    first = st.split("\n", 1)[0]
    o = None
    try:
        o = json.loads(first)
    except ValueError:
        pass
    if isinstance(o, dict):
        t = o.get("type")
        if "payload" in o and t in ("session_meta", "turn_context", "response_item", "event_msg", "compacted"):
            return "codex"
        if isinstance(t, str) and "." in t and "data" in o:
            return "copilot"
        if "role" in o and "message" in o and "type" not in o:
            return "cursor"
        if t in ("user", "assistant") and isinstance(o.get("message"), str):
            return "simple_text"
        if "parentUuid" in o or "sessionId" in o or (isinstance(t, str) and re.fullmatch(_CC_TYPES, t)):
            return "claude_code"
        return "unknown"
    # first line longer than the sniff window: classify on its prefix
    if re.match(r'\{"timestamp":\s*"[^"]*",\s*"type":\s*"(session_meta|turn_context|response_item|event_msg|compacted)"', first):
        return "codex"
    if re.match(r'\{"type":\s*"[a-z_]+\.[a-z_.]+",\s*"data"', first):
        return "copilot"
    if re.match(r'\{"role":', first):
        return "cursor"
    if re.match(r'\{"(parentUuid|sessionId)"|\{"type":\s*"' + _CC_TYPES + '"', first):
        return "claude_code"
    return "unknown"


def read_head(path, n=4096):
    with open(path, "rb") as f:
        return f.read(n).decode("utf-8", errors="replace")


# ------------------------------------------------------------------------------------------------------------- readers

def read_text(path):
    b = open(path, "rb").read()
    try:
        return b.decode("utf-8"), False
    except UnicodeDecodeError:
        return b.decode("utf-8", errors="replace"), True


def iter_json_lines(text, stat):
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        stat["lines"] += 1
        try:
            yield json.loads(line)
            continue
        except ValueError:
            pass
        objs = _salvage_line(line)
        if objs is None:
            stat["bad_lines"] += 1
            continue
        stat["lines_salvaged"] += 1
        stat["objects_from_salvaged_lines"] += len(objs)
        yield from objs


def _salvage_line(line):
    """A line that is not one JSON value: two or more objects written without a newline between them ('Extra data'),
    or raw control characters inside strings. Returns the decoded objects, or None if the line is still undecodable."""
    dec = json.JSONDecoder(strict=False)
    objs, pos, n = [], 0, len(line)
    try:
        while pos < n:
            obj, pos = dec.raw_decode(line, pos)
            objs.append(obj)
            while pos < n and line[pos] in " \t\r":
                pos += 1
    except ValueError:
        return None
    return objs or None


def load_document(text, stat):
    """Whole-document JSON with salvage: returns (top_without_messages, messages_list)."""
    try:
        d = json.loads(text)
        stat["doc"] = "ok"
        if not isinstance(d, dict):
            stat["doc"] = "not_object"
            return {}, []
        msgs = d.get("messages") if isinstance(d.get("messages"), list) else []
        return {k: v for k, v in d.items() if k != "messages"}, msgs
    except ValueError:
        pass
    dec = json.JSONDecoder()
    top, msgs = {}, []
    m = re.search(r'"info"\s*:\s*', text)
    if m and m.start() < 200:
        try:
            top["info"], _ = dec.raw_decode(text, m.end())
        except ValueError:
            pass
    for key in ("sessionId", "projectHash", "startTime", "lastUpdated", "kind"):
        mm = re.search(r'"%s"\s*:\s*"([^"]*)"' % key, text[:2000])
        if mm:
            top[key] = mm.group(1)
    m = re.search(r'"messages"\s*:\s*\[', text)
    if m:
        pos = m.end()
        n = len(text)
        while pos < n:
            while pos < n and text[pos] in " \t\r\n,":
                pos += 1
            if pos >= n or text[pos] == "]":
                break
            try:
                obj, pos = dec.raw_decode(text, pos)
            except ValueError:
                stat["salvage_stopped"] = True
                break
            msgs.append(obj)
    stat["doc"] = "salvaged" if msgs else "failed"
    stat["salvaged_messages"] = len(msgs)
    return top, msgs


# ------------------------------------------------------------------------------------------------------- format parsers

def parse_claude_code(sid, stratum, text, stat, ctx):
    p = cc_jsonl.Parser(CORPUS, sid, stratum)
    for e in iter_json_lines(text, stat):
        if isinstance(e, dict) and e.get("type") in ("tool_use", "tool_result"):
            stat["cc_fixture_entries"] += 1
            e = dict(e)
            e["type"] = "assistant" if e["type"] == "tool_use" else "user"
        if not isinstance(e, dict):
            stat["non_object_lines"] += 1
            continue
        p.feed(e)
    return p.events


_CODEX_ECHO = {"agent_message": "message", "user_message": "message", "agent_reasoning": "text"}
_CODEX_END_TYPES = {"exec_command_end", "patch_apply_end", "mcp_tool_call_end", "collab_agent_spawn_end",
                    "collab_waiting_end", "collab_close_end", "collab_agent_interaction_end", "view_image_tool_call",
                    "web_search_end"}


_UX_RUNNING = re.compile(r"^Process running with session ID (\d+)[ \t\r]*$", re.M)
_UX_EXITED = re.compile(r"^Process exited with code (-?\d+)[ \t\r]*$", re.M)


def unified_exec_state(txt):
    """Codex unified-exec output header (the harness-written lines before 'Output:'): ('running', session_id),
    ('exited', code) or (None, None). Only the header is searched, so command output quoting these phrases never counts."""
    if not isinstance(txt, str):
        return None, None
    i = txt.find("\nOutput:")
    head = txt[:i] if i >= 0 else txt[:600]
    m = _UX_RUNNING.search(head)
    if m:
        return "running", m.group(1)
    m = _UX_EXITED.search(head)
    if m:
        return "exited", int(m.group(1))
    return None, None


def _exec_end_fields(x):
    """exec_command_end payload -> (exit_code, native_error, stderr, extra fields)."""
    exit_code = x.get("exit_code")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        exit_code = None
    native = (exit_code != 0) if exit_code is not None else None
    stderr = x.get("stderr") if isinstance(x.get("stderr"), str) else None
    return exit_code, native, stderr, {"duration_s": dur_s(x.get("duration")), "exec_status": x.get("status"),
                                       "exec_source": x.get("source")}


def _codex_items_text(content):
    out = []
    for c in content if isinstance(content, list) else []:
        if not isinstance(c, dict):
            continue
        if c.get("type") in ("input_text", "output_text", "text"):
            out.append(c.get("text") or "")
        elif c.get("type") in ("input_image", "image"):
            out.append("[image]")
    return "\n".join(out)


def parse_codex(sid, stratum, text, stat, ctx):
    recs = [r for r in iter_json_lines(text, stat)]
    recs = [r for r in recs if isinstance(r, dict)]
    S = Session(sid, stratum)
    ends, human, wsend, calls_seen = {}, set(), [], set()
    end_pos, ri_before = {}, []  # exec_command_end record index by call_id; response_items before each record
    n_ri = 0
    meta = None
    for i, r in enumerate(recs):
        p = r.get("payload") if isinstance(r.get("payload"), dict) else {}
        pt = p.get("type")
        ri_before.append(n_ri)
        n_ri += int(r.get("type") == "response_item")
        if r.get("type") == "event_msg" and pt == "exec_command_end" and p.get("call_id"):
            end_pos.setdefault(p["call_id"], i)
        if r.get("type") == "session_meta" and meta is None:
            meta = p
        if r.get("type") == "event_msg":
            if pt in ("exec_command_end", "patch_apply_end", "mcp_tool_call_end") and p.get("call_id"):
                ends.setdefault(p["call_id"], {})[pt] = p
            elif pt == "user_message" and isinstance(p.get("message"), str):
                human.add(p["message"].strip())
            elif pt == "web_search_end":
                wsend.append((i, p))
        if r.get("type") == "response_item" and pt in ("function_call", "custom_tool_call", "tool_search_call"):
            calls_seen.add(p.get("call_id"))
    if meta:
        src = meta.get("source")
        if isinstance(src, dict) and "subagent" in src:
            stat["session_subagent"] = True
            own = meta.get("id")
            S.defaults = {"is_subagent": True, "agent_id": meta.get("agent_nickname") or own,
                          "parent_call_id": ctx.get("codex_spawn", {}).get(own)}
    stat["codex_event_user_message_texts"] += len(human)
    model = None
    call_tool, call_args = {}, {}
    used_ws = set()
    pending_exit = {}  # unified-exec session id -> (exec_command call_id, exec_command_end payload), exit not yet shown
    prev_total, prev_usage_id, prev_last = None, None, None
    for i, r in enumerate(recs):
        rt = r.get("type")
        ts = r.get("timestamp")
        p = r.get("payload") if isinstance(r.get("payload"), dict) else {}
        pt = p.get("type")
        if rt == "session_meta":
            ex = small_scalars(p, skip=("base_instructions",))
            ex.update({"entry_type": "session_meta", "source": p.get("source"),
                       "base_instructions_chars": len(json.dumps(p.get("base_instructions") or ""))})
            S.emit("meta", ts, extra=ex)
        elif rt == "turn_context":
            model = p.get("model") or model
            ex = {"entry_type": "turn_context", "model": p.get("model"), "effort": p.get("effort"),
                  "approval_policy": p.get("approval_policy"),
                  "sandbox": (p.get("sandbox_policy") or {}).get("type") if isinstance(p.get("sandbox_policy"), dict) else p.get("sandbox_policy")}
            S.emit("meta", ts, model=model, extra=ex)
        elif rt == "compacted":
            msg = p.get("message")
            ex = {"entry_type": "compacted", "replacement_history_items": len(p.get("replacement_history") or [])}
            if isinstance(msg, str) and msg.strip():
                S.emit("system", ts, text=msg, extra=ex)
            else:
                S.emit("meta", ts, extra=ex)
        elif rt == "response_item":
            if pt == "message":
                role = p.get("role")
                txt = _codex_items_text(p.get("content"))
                if role == "assistant":
                    S.emit("assistant", ts, text=txt, model=model, extra={"phase": p.get("phase")} if p.get("phase") else None)
                else:
                    items = [(c.get("text") or "").strip() for c in p.get("content") or [] if isinstance(c, dict)]
                    kind = "user" if role == "user" and any(x in human for x in items if x) else "system"
                    stat[f"codex_response_{role}_message_as_{kind}"] += 1
                    S.emit(kind, ts, text=txt, extra={"role": role})
            elif pt == "reasoning":
                n = 0
                for part in (p.get("summary") or []) + (p.get("content") or []):
                    if isinstance(part, dict):
                        n += len(part.get("text") or "")
                S.pending_thinking += n
            elif pt in ("function_call", "custom_tool_call", "tool_search_call"):
                name = p.get("name") if pt != "tool_search_call" else "tool_search"
                tool = tool_norm(name)
                ex = {}
                if pt == "function_call":
                    raw = p.get("arguments")
                    try:
                        a = json.loads(raw) if isinstance(raw, str) else raw
                        args = ir.j(a)
                    except ValueError:
                        a, args = None, raw
                        ex["args_unparsed"] = True
                    if p.get("namespace"):
                        ex["namespace"] = p.get("namespace")
                elif pt == "custom_tool_call":
                    a = {"input": p.get("input")}
                    args = ir.j(a)
                    ex["custom_tool"] = True
                    if p.get("status"):
                        ex["status"] = p.get("status")
                else:
                    a = p.get("arguments")
                    args = ir.j(a)
                cid = p.get("call_id")
                call_tool[cid] = name
                call_args[cid] = a if isinstance(a, dict) else None
                S.emit("call", ts, tool=tool, tool_raw=name, call_id=cid, args=args,
                       command=shell_command(tool, a), model=model, extra=ex or None)
            elif pt in ("function_call_output", "custom_tool_call_output", "tool_search_output"):
                cid = p.get("call_id")
                out = p.get("output") if pt != "tool_search_output" else p.get("tools")
                ex = {}
                if isinstance(out, str):
                    txt = out
                elif isinstance(out, list) and pt != "tool_search_output":
                    txt = _codex_items_text(out)
                    ex["output_list"] = True
                else:
                    txt = ir.j(out)
                native, exit_code, stderr = None, None, None
                e = ends.get(cid, {})
                name = call_tool.get(cid)
                ux_state, ux_val = unified_exec_state(txt) if pt == "function_call_output" else (None, None)
                if "exec_command_end" in e:
                    x = e["exec_command_end"]
                    stat["codex_exec_end_joined_to_own_output"] += 1
                    # file-order diagnostics (attribution itself is decided by the model-visible header, not file order)
                    ep = end_pos.get(cid, -1)
                    order = "end_written_before_output" if ep < i else "end_written_after_output"
                    gap = ep > i and ri_before[ep] - ri_before[i] - 1 > 0  # another response_item between output and end
                    stat[f"codex_exec_order_{ux_state or 'noheader'}_{order}"] += 1
                    if gap:
                        stat[f"codex_exec_order_{ux_state or 'noheader'}_end_after_output_with_response_item_between"] += 1
                    if ux_state == "running":
                        # The model saw 'Process running with session ID N': the process had not ended when this output was
                        # produced (whatever the file order of the end event). The exit goes to the later write_stdin
                        # result that first shows 'Process exited', if any; the end event itself stays a meta event.
                        stat["codex_exec_output_running_exit_deferred"] += 1
                        if str(x.get("process_id")) != ux_val:
                            stat["codex_exec_running_session_id_ne_process_id"] += 1
                        if ux_val in pending_exit:
                            stat["codex_exec_pending_session_id_reused_before_exit_shown"] += 1
                        pending_exit[ux_val] = (cid, x)
                        ex.update({"unified_exec_running": True, "unified_exec_session_id": ux_val,
                                   "exec_end_deferred": True})
                    else:
                        exit_code, native, stderr, f = _exec_end_fields(x)
                        ex.update(f)
                        stat["codex_exec_exit_attached_to_own_output"] += 1
                        if ux_state == "exited":
                            stat["codex_exec_own_output_header_exited"] += 1
                            if ux_val != exit_code:
                                stat["codex_exec_header_exit_ne_end_exit"] += 1
                elif name == "write_stdin" and ux_state is not None:
                    sess = call_args.get(cid) or {}
                    key = str(sess.get("session_id"))
                    if ux_state == "running":
                        stat["codex_write_stdin_output_running"] += 1
                        ex.update({"unified_exec_running": True, "unified_exec_session_id": ux_val})
                    elif key in pending_exit:
                        ocid, x = pending_exit.pop(key)
                        exit_code, native, stderr, f = _exec_end_fields(x)
                        ex.update(f)
                        ex.update({"exec_end_call_id": ocid, "unified_exec_session_id": key})
                        stat["codex_exec_exit_attached_to_write_stdin_output"] += 1
                        if ux_val != exit_code:
                            stat["codex_exec_header_exit_ne_end_exit"] += 1
                    else:
                        stat["codex_write_stdin_output_exited_without_exec_end"] += 1
                if "patch_apply_end" in e:
                    x = e["patch_apply_end"]
                    if isinstance(x.get("success"), bool):
                        native = not x["success"]
                    ex["patch_success"] = x.get("success")
                if "mcp_tool_call_end" in e:
                    x = e["mcp_tool_call_end"]
                    res = x.get("result")
                    if isinstance(res, dict):
                        ok = res.get("Ok")
                        native = ("Err" in res) or (isinstance(ok, dict) and ok.get("isError") is True)
                    ex["duration_s"] = dur_s(x.get("duration"))
                if pt == "custom_tool_call_output" and isinstance(out, str) and out.startswith("{"):
                    try:
                        md = json.loads(out).get("metadata") or {}
                        if "exit_code" in md:
                            ex["output_metadata_exit_code"] = md["exit_code"]
                    except (ValueError, AttributeError):
                        pass
                S.emit("result", ts, tool=tool_norm(name), tool_raw=name, call_id=cid, text=txt, stderr=stderr,
                       native_error=native, exit_code=exit_code, extra=ex or None)
            elif pt == "web_search_call":
                act = p.get("action")
                cid, synth = None, False
                for j_, (k, w) in enumerate(wsend):
                    if abs(k - i) <= 3 and j_ not in used_ws and w.get("action") == act:
                        cid = w.get("call_id")
                        used_ws.add(j_)
                        break
                if not cid:
                    cid, synth = f"synthetic:codex:{len(S.events)}", True
                ex = {"server_tool": True, "status": p.get("status")}
                if synth:
                    ex["synthetic_call_id"] = True
                call_tool[cid] = "web_search"
                S.emit("call", ts, tool=tool_norm("web_search"), tool_raw="web_search_call", call_id=cid,
                       args=ir.j(act), model=model, extra=ex)
            else:
                S.emit("meta", ts, extra={"entry_type": "response_item", "type": pt})
        elif rt == "event_msg":
            if pt == "token_count":
                info = p.get("info") if isinstance(p.get("info"), dict) else None
                last = (info or {}).get("last_token_usage") or {}
                ex = {"entry_type": "event_msg", "type": pt}
                if info:
                    ex.update({"total_token_usage": info.get("total_token_usage"),
                               "reasoning_output_tokens": last.get("reasoning_output_tokens"),
                               "model_context_window": info.get("model_context_window")})
                usage = {"usage_in": last.get("input_tokens"), "usage_out": last.get("output_tokens"),
                         "usage_cache_read": last.get("cached_input_tokens")}
                total = (info or {}).get("total_token_usage")
                mid = None
                if total is not None:
                    tkey = json.dumps(total, sort_keys=True)
                    lkey = json.dumps(last, sort_keys=True)
                    if tkey == prev_total and prev_usage_id is not None:
                        if lkey != prev_last:
                            # seen after compaction / thread rollback: last_token_usage reset, total unchanged
                            stat["codex_token_count_repeat_total_but_last_differs"] += 1
                            if not last.get("input_tokens") and not last.get("output_tokens"):
                                stat["codex_token_count_repeat_total_but_last_differs_last_in_out_zero"] += 1
                        # Same cumulative total as the previous token_count: no new API call. Same api_msg_id as that
                        # row, usage columns nulled, the repeated per-call values kept in extra.
                        stat["codex_token_count_repeat_of_previous_total"] += 1
                        mid = prev_usage_id
                        ex["repeat_of_previous_total"] = True
                        ex["last_token_usage_repeated"] = {k: last.get(k) for k in
                                                           ("input_tokens", "output_tokens", "cached_input_tokens")}
                        usage = {}
                    else:
                        mid = f"synthetic:codex:{sid}:u{len(S.events)}"
                        ex["synthetic_api_msg_id"] = True
                        stat["codex_token_count_new_total"] += 1
                    prev_total, prev_usage_id, prev_last = tkey, mid, lkey
                elif any(v is not None for v in usage.values()):
                    mid = f"synthetic:codex:{sid}:u{len(S.events)}"
                    ex["synthetic_api_msg_id"] = True
                S.emit("meta", ts, model=model, api_msg_id=mid, extra=ex, **usage)
            elif pt in _CODEX_END_TYPES:
                cid = p.get("call_id")
                ex = {"entry_type": "event_msg", "type": pt, "has_call": cid in calls_seen}
                if cid not in calls_seen:
                    stat[f"codex_{pt}_without_call"] += 1
                if pt == "exec_command_end":
                    ex.update({"exit_code": p.get("exit_code"), "duration_s": dur_s(p.get("duration")),
                               "status": p.get("status"), "source": p.get("source"), "process_id": p.get("process_id")})
                elif pt == "mcp_tool_call_end":
                    ex["duration_s"] = dur_s(p.get("duration"))
                    inv = p.get("invocation") or {}
                    ex.update({"server": inv.get("server"), "mcp_tool": inv.get("tool")})
                elif pt == "patch_apply_end":
                    ex["success"] = p.get("success")
                elif pt.startswith("collab_"):
                    ex.update(small_scalars(p, skip=("prompt", "type", "call_id")))
                S.emit("meta", ts, parent_call_id=cid, extra=ex)
            elif pt in _CODEX_ECHO:
                v = p.get(_CODEX_ECHO[pt])
                S.emit("meta", ts, extra={"entry_type": "event_msg", "type": pt, "chars": len(v) if isinstance(v, str) else None})
            else:
                ex = {"entry_type": "event_msg", "type": pt}
                ex.update(small_scalars(p, skip=("type",)))
                S.emit("meta", ts, extra=ex)
        else:
            stat["unknown_record_types"] += 1
            S.emit("meta", ts, extra={"entry_type": rt})
    stat["codex_exec_exit_never_shown_to_model"] += len(pending_exit)
    stat["codex_exec_exit_never_shown_to_model_nonzero"] += sum(
        1 for _, x in pending_exit.values() if x.get("exit_code") not in (0, None))
    return S.events


def _oc_scalar_meta(md):
    return small_scalars(md, limit=120, skip=("output", "preview", "description", "diff"))


def parse_opencode(sid, stratum, text, stat, ctx):
    top, msgs = load_document(text, stat)
    stat["messages"] = len(msgs)
    S = Session(sid, stratum)
    info = top.get("info") if isinstance(top.get("info"), dict) else {}
    own = info.get("id") or sid
    if info.get("parentID"):
        stat["session_subagent"] = True
        S.defaults = {"is_subagent": True, "agent_id": own, "parent_call_id": ctx.get("opencode_task", {}).get(own)}
    for mi_idx, m in enumerate(msgs):
        if not isinstance(m, dict):
            continue
        mi = m.get("info") if isinstance(m.get("info"), dict) else {}
        role = mi.get("role")
        mt = mi.get("time") if isinstance(mi.get("time"), dict) else {}
        created = mt.get("created")
        mid = mi.get("id")
        synth_mid = False
        if mid == "REDACTED" or not mid:
            stat["redacted_message_ids" if mid == "REDACTED" else "missing_message_ids"] += 1
            # one synthetic id per message, shared by its assistant/call/step-finish rows (one API step per message)
            mid, synth_mid = f"synthetic:opencode:{sid}:m{mi_idx}", True
        model = mi.get("modelID")
        for part in m.get("parts") or []:
            if not isinstance(part, dict):
                continue
            t = part.get("type")
            pid = part.get("id")
            ptime = part.get("time") if isinstance(part.get("time"), dict) else {}
            if t == "text":
                ts = ptime.get("start")
                ex = {}
                if ts is None:
                    ts = created
                    ex["ts_src"] = "message_created"
                if part.get("synthetic"):
                    ex["synthetic"] = True
                if role == "assistant":
                    S.emit("assistant", ts, text=part.get("text") or "", model=model, api_msg_id=mid, uuid=pid, extra=ex or None)
                else:
                    S.emit("system" if part.get("synthetic") else "user", ts, text=part.get("text") or "", uuid=pid, extra=ex or None)
            elif t == "reasoning":
                S.pending_thinking += len(part.get("text") or "")
            elif t == "tool":
                st = part.get("state") if isinstance(part.get("state"), dict) else {}
                stt = st.get("time") if isinstance(st.get("time"), dict) else {}
                name = part.get("tool")
                tool = tool_norm(name)
                inp = st.get("input") if isinstance(st.get("input"), dict) else st.get("input")
                cid = part.get("callID")
                md = st.get("metadata") if isinstance(st.get("metadata"), dict) else {}
                cex = {"status": st.get("status")}
                if not cid or cid == "REDACTED":
                    stat["opencode_call_ids_redacted_or_missing"] += 1
                    cex["synthetic_call_id"] = True
                    cex["source_call_id"] = cid
                    cid = f"synthetic:opencode:{len(S.events)}"
                if name == "task" and md.get("sessionId"):
                    cex["child_session_id"] = md.get("sessionId")
                S.emit("call", stt.get("start"), tool=tool, tool_raw=name, call_id=cid, args=ir.j(inp),
                       command=shell_command(tool, inp), model=model, api_msg_id=mid, uuid=pid, extra=cex)
                status = st.get("status")
                if status in ("completed", "error"):
                    rex = {"status": status}
                    rex.update(_oc_scalar_meta(md))
                    if st.get("title") and len(str(st.get("title"))) <= 200:
                        rex["title"] = st.get("title")
                    if "compacted" in stt:
                        rex["compacted_at"] = stt.get("compacted")
                    if st.get("attachments"):
                        rex["attachments"] = len(st.get("attachments"))
                    out = st.get("output") if status == "completed" else st.get("error")
                    if out is not None and not isinstance(out, str):
                        out = ir.j(out)
                    ec = md.get("exit")
                    ec = ec if isinstance(ec, int) and not isinstance(ec, bool) else None
                    native = (status == "error") or (ec is not None and ec != 0)
                    if status != "error" and ec is not None and ec != 0:
                        rex["native_error_from_exit"] = True
                        stat["opencode_results_completed_with_nonzero_exit"] += 1
                    S.emit("result", stt.get("end"), tool=tool, tool_raw=name, call_id=cid, text=out,
                           native_error=native, exit_code=ec, uuid=pid, extra=rex)
            elif t == "step-finish":
                tk = part.get("tokens") if isinstance(part.get("tokens"), dict) else {}
                cache = tk.get("cache") if isinstance(tk.get("cache"), dict) else {}
                sx = {"part_type": t, "reason": part.get("reason"), "cost": part.get("cost"),
                      "reasoning_tokens": tk.get("reasoning")}
                if synth_mid:
                    sx["synthetic_api_msg_id"] = True
                    stat["opencode_step_finish_synthetic_api_msg_id"] += 1
                S.emit("meta", None, usage_in=tk.get("input"), usage_out=tk.get("output"), usage_cache_read=cache.get("read"),
                       usage_cache_create=cache.get("write"), model=model, api_msg_id=mid, uuid=pid, extra=sx)
            elif t == "subtask":
                S.emit("meta", None, uuid=pid, extra={"part_type": t, "agent": part.get("agent"), "command": part.get("command"),
                                                      "description": part.get("description"), "prompt_chars": len(part.get("prompt") or "")})
            elif t == "patch":
                S.emit("meta", None, uuid=pid, extra={"part_type": t, "files": len(part.get("files") or [])})
            elif t == "file":
                S.emit("meta", None, uuid=pid, extra={"part_type": t, "mime": part.get("mime"), "filename": part.get("filename")})
            else:
                S.emit("meta", None, uuid=pid, extra={"part_type": t, **small_scalars(part, limit=80, skip=("id", "sessionID", "messageID", "type", "snapshot"))})
        if isinstance(mi.get("error"), dict):
            err = mi["error"]
            S.emit("meta", mt.get("completed"), api_msg_id=mid, extra={"message_error": err.get("name"),
                                                                     "message_role": role})
    return S.events


def parse_gemini(sid, stratum, text, stat, ctx):
    top, msgs = load_document(text, stat)
    stat["messages"] = len(msgs)
    S = Session(sid, stratum)
    for mi_idx, m in enumerate(msgs):
        if not isinstance(m, dict):
            continue
        t = m.get("type")
        ts = m.get("timestamp")
        c = m.get("content")
        if isinstance(c, list):
            c = "\n".join((x.get("text") or "") if isinstance(x, dict) else str(x) for x in c)
        if t == "user":
            S.emit("user", ts, text=c or "", uuid=m.get("id"))
        elif t == "gemini":
            for th in m.get("thoughts") or []:
                if isinstance(th, dict):
                    S.pending_thinking += len(th.get("description") or "") + len(th.get("subject") or "")
            tk = m.get("tokens") if isinstance(m.get("tokens"), dict) else {}
            gid = m.get("id")
            if not gid and any(tk.get(k) is not None for k in ("input", "output", "cached")):
                gid = f"synthetic:gemini:{sid}:m{mi_idx}"
                stat["gemini_messages_synthetic_api_msg_id"] += 1
            base = {"api_msg_id": gid, "model": m.get("model"), "usage_in": tk.get("input"),
                    "usage_out": tk.get("output"), "usage_cache_read": tk.get("cached")}
            if c:
                S.emit("assistant", ts, text=c, uuid=m.get("id"), **base)
            for tc in m.get("toolCalls") or []:
                if not isinstance(tc, dict):
                    continue
                name = tc.get("name")
                tool = tool_norm(name)
                a = tc.get("args")
                S.emit("call", ts, tool=tool, tool_raw=name, call_id=tc.get("id"), args=ir.j(a),
                       command=shell_command(tool, a), extra={"status": tc.get("status")}, **base)
                if "result" in tc:
                    parts = []
                    for r in tc.get("result") or []:
                        fr = r.get("functionResponse") if isinstance(r, dict) else None
                        resp = (fr or {}).get("response")
                        if isinstance(resp, dict) and ("output" in resp or "error" in resp):
                            v = resp.get("output", resp.get("error"))
                            parts.append(v if isinstance(v, str) else ir.j(v))
                        elif resp is not None:
                            parts.append(ir.j(resp))
                    status = tc.get("status")
                    S.emit("result", tc.get("timestamp"), tool=tool, tool_raw=name, call_id=tc.get("id"),
                           text="\n".join(parts), native_error=(status in ("error", "cancelled")) if status else None,
                           extra={"status": status})
        else:
            S.emit("meta", ts, text=c if isinstance(c, str) else None, uuid=m.get("id"), extra={"message_type": t})
    return S.events


def parse_cursor(sid, stratum, text, stat, ctx):
    S = Session(sid, stratum)
    for o in iter_json_lines(text, stat):
        if not isinstance(o, dict):
            continue
        role = o.get("role")
        msg = o.get("message") if isinstance(o.get("message"), dict) else {}
        content = msg.get("content")
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
        for b in blocks:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text":
                S.emit("assistant" if role == "assistant" else "user", None, text=b.get("text") or "")
            elif b.get("type") == "tool_use":
                name = b.get("name")
                tool = tool_norm(name)
                inp = b.get("input")
                cid = b.get("id") or f"synthetic:cursor:{len(S.events)}"
                S.emit("call", None, tool=tool, tool_raw=name, call_id=cid, args=ir.j(inp), command=shell_command(tool, inp),
                       extra=None if b.get("id") else {"synthetic_call_id": True})
            else:
                S.emit("meta", None, extra={"block_type": b.get("type")})
    return S.events


def parse_copilot(sid, stratum, text, stat, ctx):
    S = Session(sid, stratum)
    model = None
    call_tool = {}
    for li, o in enumerate(iter_json_lines(text, stat)):
        if not isinstance(o, dict):
            continue
        t = o.get("type")
        d = o.get("data") if isinstance(o.get("data"), dict) else {}
        ts = o.get("timestamp")
        ids = {"uuid": o.get("id"), "parent_uuid": o.get("parentId")}
        if t == "session.model_change":
            model = d.get("newModel") or model
        if t == "user.message":
            txt = d.get("transformedContent") if isinstance(d.get("transformedContent"), str) else d.get("content")
            S.emit("user", ts, text=txt or "", extra={"human_chars": len(d.get("content") or "")}, **ids)
        elif t == "assistant.message":
            S.pending_thinking += len(d.get("reasoningText") or "")
            cmid = d.get("messageId")
            if not cmid and d.get("outputTokens") is not None:
                cmid = f"synthetic:copilot:{sid}:l{li}"
                stat["copilot_messages_synthetic_api_msg_id"] += 1
            base = {"api_msg_id": cmid, "usage_out": d.get("outputTokens"), "model": model}
            if d.get("content"):
                S.emit("assistant", ts, text=d.get("content"), **base, **ids)
            for tr in d.get("toolRequests") or []:
                if not isinstance(tr, dict):
                    continue
                name = tr.get("name")
                tool = tool_norm(name)
                a = tr.get("arguments")
                call_tool[tr.get("toolCallId")] = name
                S.emit("call", ts, tool=tool, tool_raw=name, call_id=tr.get("toolCallId"), args=ir.j(a),
                       command=shell_command(tool, a), **base, **ids)
        elif t == "tool.execution_complete":
            cid = d.get("toolCallId")
            name = call_tool.get(cid)
            res = d.get("result") if isinstance(d.get("result"), dict) else {}
            err = d.get("error")
            if "content" in res:
                txt = res.get("content") if isinstance(res.get("content"), str) else ir.j(res.get("content"))
            elif isinstance(err, dict):
                txt = err.get("message") if isinstance(err.get("message"), str) else ir.j(err)
            else:
                txt = ir.j(err) if err is not None else None
            succ = d.get("success")
            S.emit("result", ts, tool=tool_norm(name), tool_raw=name, call_id=cid, text=txt,
                   native_error=(not succ) if isinstance(succ, bool) else None, model=d.get("model"),
                   extra={"error_code": err.get("code")} if isinstance(err, dict) else None, **ids)
        elif t == "tool.execution_start":
            S.emit("meta", ts, parent_call_id=d.get("toolCallId"), extra={"entry_type": t, "tool_name": d.get("toolName")}, **ids)
        elif t == "system.notification":
            k = d.get("kind") if isinstance(d.get("kind"), dict) else {}
            S.emit("system", ts, text=d.get("content"), extra={"entry_type": t, **small_scalars(k)}, **ids)
        elif t == "session.compaction_complete":
            S.emit("system", ts, text=d.get("summaryContent"), extra={"entry_type": t, **small_scalars(d, skip=("summaryContent",))}, **ids)
        else:
            S.emit("meta", ts, extra={"entry_type": t, **small_scalars(d, limit=120, skip=("content", "summary"))}, **ids)
    return S.events


def parse_simple_text(sid, stratum, text, stat, ctx):
    S = Session(sid, stratum)
    for o in iter_json_lines(text, stat):
        if not isinstance(o, dict):
            continue
        t = o.get("type")
        msg = o.get("message")
        S.emit("assistant" if t == "assistant" else ("user" if t == "user" else "meta"), o.get("timestamp"),
               text=msg if isinstance(msg, str) else ir.j(msg), extra=None if t in ("user", "assistant") else {"entry_type": t})
    return S.events


PARSERS = {"claude_code": parse_claude_code, "codex": parse_codex, "opencode": parse_opencode, "gemini": parse_gemini,
           "cursor": parse_cursor, "copilot": parse_copilot, "simple_text": parse_simple_text}

# --------------------------------------------------------------------------------------------------- redaction markers

RED_TYPED = re.compile(r"\[REDACTED:[A-Za-z0-9_]+\]|\[REDACTED_[A-Za-z0-9_]+\]|\[REDACTED\]|<REDACTED>|<TRUFFLEHOG_REDACTED_[A-Za-z0-9_]*>")
RED_WHOLE = re.compile(r'(?<![A-Za-z0-9+/])REDACTED(?![A-Za-z0-9+/_:\]>])')
RED_B64 = re.compile(r"[A-Za-z0-9+/]REDACTED|REDACTED[A-Za-z0-9+/]")


def redaction_counts(s):
    """Approximate classes: typed markers; bare REDACTED adjacent to base64/word chars (redaction inside blobs/ids);
    other bare REDACTED (e.g. a whole JSON value "REDACTED")."""
    if not s or "REDACTED" not in s:
        return None
    c = collections.Counter()
    for m in RED_TYPED.findall(s):
        if m.startswith("<TRUFFLEHOG"):
            c["trufflehog"] += 1
        elif m.startswith("[REDACTED:"):
            c["bracket_typed_colon"] += 1
        elif m.startswith("[REDACTED_"):
            c["bracket_typed_underscore"] += 1
        elif m == "[REDACTED]":
            c["bracket_plain"] += 1
        else:
            c["angle_plain"] += 1
    total = s.count("REDACTED")
    typed = sum(c.values())
    b64 = len(RED_B64.findall(s))
    c["bare_in_blob"] = b64
    c["bare_other"] = max(0, total - typed - b64)
    c["total_substring"] = total
    return c


# ---------------------------------------------------------------------------------------------------- per-session summary

_GEM_EXIT = re.compile(r"^Exit Code: (-?\d+)\s*$", re.M)  # report-only: Gemini shell text line (no structured field)


def summarize(events, fmt, stat):
    """Counts for one session's event list (used for both the full pass and the A+B caches)."""
    kinds = collections.Counter(e["kind"] for e in events)
    call_ids = [e["call_id"] for e in events if e["kind"] == "call"]
    res_ids = [e["call_id"] for e in events if e["kind"] == "result"]
    cset, rset = set(call_ids), set(x for x in res_ids if x is not None)
    sess_sub = bool(stat.get("session_subagent"))
    calls_sub = sum(1 for e in events if e["kind"] == "call" and e["is_subagent"])
    # in-file nesting (CC agent_progress) carries parent_call_id; top-level isSidechain entries do not
    calls_nested = 0 if sess_sub else sum(1 for e in events if e["kind"] == "call" and e["is_subagent"] and e["parent_call_id"])
    calls_sidechain = 0 if sess_sub else calls_sub - calls_nested
    last, back = None, 0
    for e in events:
        if e["ts"]:
            t = ir.parse_ts(e["ts"])
            if t is not None:
                if last is not None and t < last:
                    back += 1
                last = t
    ts_kind = collections.Counter(e["ts_kind"] for e in events)
    frac = collections.Counter(ir.frac_digits(e["ts"]) for e in events if e["ts"])
    ne = collections.Counter("null" if e["native_error"] is None else str(bool(e["native_error"])).lower()
                             for e in events if e["kind"] == "result")
    ec = sum(1 for e in events if e["kind"] == "result" and e["exit_code"] is not None)
    synth = sum(1 for e in events if e["kind"] == "call" and e["extra"] and '"synthetic_call_id":true' in e["extra"])
    red = collections.Counter()
    for e in events:
        for col in ("text", "args", "command", "stderr"):
            r = redaction_counts(e[col])
            if r:
                red.update(r)
    xc_ids = [(e["call_id"], bool(e["extra"] and '"synthetic_call_id":true' in e["extra"])) for e in events
              if e["kind"] == "call" and (sess_sub or not (e["is_subagent"] and e["parent_call_id"]))]
    red_ids = sum(1 for e in events if e["kind"] in ("call", "result") and e["call_id"] and "REDACTED" in e["call_id"])
    # usage rows and the dedupe-on-api_msg_id convention
    urows = [e for e in events if any(e[c] is not None for c in _USAGE_COLS)]
    first_in = {}
    for e in urows:
        if e["api_msg_id"] is not None and e["api_msg_id"] not in first_in:
            first_in[e["api_msg_id"]] = e["usage_in"] or 0
    rep_rows = sum(1 for e in events if e["kind"] == "meta" and e["extra"] and '"repeat_of_previous_total":true' in e["extra"])
    # error flag vs harness exit code (results)
    res = [e for e in events if e["kind"] == "result"]
    nz = [e for e in res if e["exit_code"] is not None and e["exit_code"] != 0]
    shell = [e for e in res if e["tool"] == "shell"]
    gem_txt_nz = [e for e in shell if fmt == "gemini" and _GEM_EXIT.search(e["text"] or "")
                  and _GEM_EXIT.search(e["text"]).group(1) != "0"]
    return {
        "events": len(events), "kinds": dict(kinds), "calls": len(call_ids), "results": len(res_ids),
        "calls_without_result": sum(1 for x in cset if x not in rset),
        "results_without_call": sum(1 for x in res_ids if x is None or x not in cset),
        "duplicate_call_ids": len(call_ids) - len(cset), "synthetic_call_ids": synth,
        "call_or_result_ids_containing_REDACTED": red_ids,
        "calls_subagent": calls_sub, "calls_nested_subagent": calls_nested, "calls_sidechain_toplevel": calls_sidechain,
        "calls_session_subagent": calls_sub if sess_sub else 0,
        "events_subagent": sum(1 for e in events if e["is_subagent"]),
        "ts_kind": dict(ts_kind), "frac_digits": {str(k): v for k, v in frac.items()},
        "ts_backward_steps": back, "events_with_ts": sum(frac.values()),
        "native_error_results": dict(ne), "exit_code_results_nonnull": ec,
        "redaction_ir": dict(red), "xcheck_call_ids": xc_ids,
        "usage_rows": len(urows), "usage_rows_api_msg_id_null": sum(1 for e in urows if e["api_msg_id"] is None),
        "usage_rows_api_msg_id_synthetic": sum(1 for e in urows if (e["api_msg_id"] or "").startswith("synthetic:")),
        "usage_distinct_api_msg_ids": len(first_in), "usage_in_sum_all_rows": sum(e["usage_in"] or 0 for e in urows),
        "usage_in_sum_dedup_api_msg_id": sum(first_in.values()), "usage_repeat_rows_flagged": rep_rows,
        "results_exit_code_nonzero": len(nz), "results_exit_code_nonzero_native_true": sum(1 for e in nz if e["native_error"] is True),
        "results_native_true": sum(1 for e in res if e["native_error"] is True),
        "shell_results": len(shell), "shell_results_native_true": sum(1 for e in shell if e["native_error"] is True),
        "shell_results_exit_code_nonnull": sum(1 for e in shell if e["exit_code"] is not None),
        "gemini_shell_results_text_exit_nonzero": len(gem_txt_nz),
        "gemini_shell_results_text_exit_nonzero_native_true": sum(1 for e in gem_txt_nz if e["native_error"] is True),
        "calls_by_tool": dict(collections.Counter(f"{e['tool_raw']} -> {e['tool']}" for e in events if e["kind"] == "call")),
    }


def _new_stat():
    return collections.defaultdict(int)


def parse_session(sid, fmt, stratum, ctx, path=None):
    """Parse one transcript. Returns (events, stat)."""
    stat = _new_stat()
    stat["format"] = fmt
    path = path or os.path.join(TRANS, sid + ".jsonl")
    text, replaced = read_text(path)
    stat["utf8_replaced"] = int(replaced)
    stat["bytes"] = os.path.getsize(path)
    fn = PARSERS.get(fmt)
    if fn is None:
        return [], stat, text
    try:
        events = fn(sid, stratum, text, stat, ctx)
    except Exception as ex:  # a parser bug must not kill the pass; recorded per session
        stat["exception"] = f"{type(ex).__name__}: {ex}"[:300]
        events = []
    ensure_usage_ids(events, fmt, sid, stat)
    return events, stat, text


_USAGE_COLS = ("usage_in", "usage_out", "usage_cache_read", "usage_cache_create")


def ensure_usage_ids(events, fmt, sid, stat):
    """Safety net for the dedupe-on-api_msg_id convention: any event that carries usage but no api_msg_id gets a
    unique synthetic one (synthetic:<format>:<session>:e<seq>) and extra.synthetic_api_msg_id. The format parsers
    already assign message-level synthetic ids; this catches the rest (e.g. a Claude Code message without id)."""
    for e in events:
        if e["api_msg_id"] is None and any(e[c] is not None for c in _USAGE_COLS):
            e["api_msg_id"] = f"synthetic:{fmt}:{sid}:e{e['seq']}"
            ex = json.loads(e["extra"]) if e["extra"] else {}
            if not isinstance(ex, dict):
                ex = {"extra_raw": ex}
            ex["synthetic_api_msg_id"] = True
            e["extra"] = ir.j(ex)
            stat["usage_events_given_synthetic_api_msg_id_postpass"] += 1


def session_length(fmt, stat, text):
    if fmt in ("opencode", "gemini"):
        return int(stat.get("messages", 0))
    return sum(1 for line in text.split("\n") if line.strip())


# ------------------------------------------------------------------------------------------------------ worker functions

def _child_links(fmt, text):
    """Cross-session subagent links found in a transcript: {child_id: parent_call_id}."""
    links = {}
    if fmt == "opencode" and '"task"' in text:
        for m in re.finditer(r'"callID":\s*"([^"]+)",\s*"tool":\s*"task"', text):
            seg = text[m.end(): m.end() + 200000]
            mm = re.search(r'"sessionId":\s*"(ses_[A-Za-z0-9]+)"', seg)
            nxt = re.search(r'"callID":', seg)
            if mm and (not nxt or mm.start() < nxt.start()):
                links[mm.group(1)] = m.group(1)
    if fmt == "codex" and "collab_agent_spawn_end" in text:
        for line in text.split("\n"):
            if '"collab_agent_spawn_end"' in line:
                try:
                    p = json.loads(line).get("payload") or {}
                except ValueError:
                    continue
                if p.get("new_thread_id") and p.get("call_id"):
                    links[p["new_thread_id"]] = p["call_id"]
    return links


def full_pass_worker(args):
    sid, label, stratum = args
    path = os.path.join(TRANS, sid + ".jsonl")
    fmt = sniff_text(read_head(path))
    t0 = time.time()
    events, stat, text = parse_session(sid, fmt, stratum, {}, path)
    summ = summarize(events, fmt, stat)
    summ.pop("xcheck_call_ids")
    raw_red = redaction_counts(text) or {}
    out = {"session_id": sid, "label": label, "stratum": stratum, "format": fmt,
           "length": session_length(fmt, stat, text), "stat": {k: v for k, v in stat.items()},
           "summary": summ, "redaction_raw": dict(raw_red), "links": _child_links(fmt, text),
           "secs": time.time() - t0}
    return out


def _sanitize_surrogates(df):
    n = 0
    for c, t in ir.COLUMNS.items():
        if t != "str":
            continue
        col = df[c]
        mask = col.notna()
        if not mask.any():
            continue
        vals = col[mask].astype(object)
        bad = [i for i, v in vals.items() if isinstance(v, str) and _has_surrogate(v)]
        for i in bad:
            # round-trip through UTF-16: paired surrogates recombine, lone ones become U+FFFD
            df.at[i, c] = vals[i].encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")
        n += len(bad)
    return n


_SURR = re.compile("[\ud800-\udfff]")


def _has_surrogate(s):
    return bool(_SURR.search(s))


def build_worker(args):
    sid, fmt, stratum, ctx = args
    events, stat, text = parse_session(sid, fmt, stratum, ctx)
    summ = summarize(events, fmt, stat)
    if not events:
        return sid, None, summ, {k: v for k, v in stat.items()}, None
    df = ir.to_frame(events)
    v = ir.validate(df)
    try:
        tbl = pa.Table.from_pandas(df, schema=SCHEMA, preserve_index=False)
        nsur = 0
    except (pa.ArrowInvalid, pa.ArrowTypeError, UnicodeEncodeError):
        nsur = _sanitize_surrogates(df)
        tbl = pa.Table.from_pandas(df, schema=SCHEMA, preserve_index=False)
    st = {k: v2 for k, v2 in stat.items()}
    st["surrogate_cells_replaced"] = nsur
    return sid, tbl, summ, st, v


# --------------------------------------------------------------------------------------------------------- aggregation

def _add(acc, d):
    for k, v in d.items():
        if isinstance(v, dict):
            _add(acc.setdefault(k, {}), v)
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            acc[k] = acc.get(k, 0) + v


def aggregate_by_format(rows):
    """rows: iterable of (format, stat, summary). Returns per-format aggregate dict."""
    agg = {}
    for fmt, stat, summ in rows:
        a = agg.setdefault(fmt, {"files": 0, "parse": {}, "summary": {}})
        a["files"] += 1
        p = a["parse"]
        for k, v in stat.items():  # every numeric/boolean parse counter, summed over files
            if k in ("format", "doc", "exception", "session_subagent") or not isinstance(v, (int, bool)) or not v:
                continue
            p[k] = p.get(k, 0) + int(v)
        if stat.get("bad_lines"):
            p["files_with_bad_lines"] = p.get("files_with_bad_lines", 0) + 1
        if stat.get("doc"):
            p.setdefault("document", {})
            p["document"][stat["doc"]] = p["document"].get(stat["doc"], 0) + 1
        if stat.get("exception"):
            p["parser_exceptions"] = p.get("parser_exceptions", 0) + 1
        if stat.get("session_subagent"):
            p["session_level_subagent_sessions"] = p.get("session_level_subagent_sessions", 0) + 1
        if summ.get("events", 0) == 0:
            p["files_with_zero_events"] = p.get("files_with_zero_events", 0) + 1
        s = {k: v for k, v in summ.items() if k not in ("xcheck_call_ids", "calls_by_tool")}
        _add(a["summary"], s)
        _add(a.setdefault("calls_by_tool", {}), summ.get("calls_by_tool", {}))
    for fmt, a in agg.items():
        tools = a.pop("calls_by_tool", {})
        a["calls_by_tool_top40"] = dict(sorted(tools.items(), key=lambda kv: -kv[1])[:40])
        a["distinct_tool_raw"] = len(tools)
        s = a["summary"]
        ev, calls = s.get("events", 0), s.get("calls", 0)
        s["subagent_share_events"] = (s.get("events_subagent", 0) / ev) if ev else None
        s["subagent_share_calls"] = (s.get("calls_subagent", 0) / calls) if calls else None
        s["nested_subagent_share_calls"] = (s.get("calls_nested_subagent", 0) / calls) if calls else None
    return agg


# ------------------------------------------------------------------------------------------------------ split caches

def write_split_cache(split, ids, fmt_of, strat, ctx, path=None):
    """Parse sessions `ids` (in that order) with build_worker on an N_PROC pool into one zstd parquet IR cache
    (row group flushed at >= 250,000 rows, so a session never spans row groups), then validate the whole file one row
    group at a time with ir.validate. The per-session code path of every split (A/B in main(), E in build_split_e()).
    path: output file (default analysis/cache/swechat_<split>.parquet).
    Returns (cache info dict, [(session_id, format, stat, summary)] in `ids` order)."""
    path = path or os.path.join(CACHE, f"{CORPUS}_{split}.parquet")
    tmp = path + ".tmp"
    writer = pq.ParquetWriter(tmp, SCHEMA, compression="zstd")
    buf, buf_rows, rows, sessions, empty, val, per = [], 0, 0, 0, [], collections.Counter(), []
    jobs = [(sid, fmt_of[sid], strat[sid], ctx) for sid in ids]
    with Pool(N_PROC) as pool:
        for sid, tbl, summ, st, v in pool.imap(build_worker, jobs, chunksize=1):
            per.append((sid, fmt_of[sid], st, summ))
            if tbl is None:
                empty.append(sid)
                continue
            val.update({k: v2 for k, v2 in v.items() if k not in ("sessions",)})
            buf.append(tbl)
            buf_rows += tbl.num_rows
            sessions += 1
            if buf_rows >= 250_000:
                writer.write_table(pa.concat_tables(buf), row_group_size=10**9)
                rows += buf_rows
                buf, buf_rows = [], 0
    if buf:
        writer.write_table(pa.concat_tables(buf), row_group_size=10**9)
        rows += buf_rows
    writer.close()
    os.replace(tmp, path)
    # whole-file validation, one row group at a time (a session never spans row groups)
    pf = pq.ParquetFile(path)
    seen, vrows = set(), 0
    for g in range(pf.num_row_groups):
        df = pf.read_row_group(g).to_pandas(types_mapper={pa.string(): pd.StringDtype(), pa.int64(): pd.Int64Dtype(),
                                                          pa.bool_(): pd.BooleanDtype()}.get)
        df["seq"] = df["seq"].astype("int64")
        ir.validate(df)
        ids_g = set(df.session_id.unique())
        assert not (ids_g & seen), "a session spans row groups"
        seen |= ids_g
        vrows += len(df)
    assert vrows == rows
    info = {"path": f"analysis/cache/{CORPUS}_{split}.parquet", "rows": rows, "sessions": sessions,
            "sessions_in_sample": len(ids), "sessions_with_zero_events": empty,
            "row_groups": pf.num_row_groups, "bytes": os.path.getsize(path),
            "validate_kind_counts": {k: int(v) for k, v in val.items() if k != "rows"}}
    print(f"{split}: {rows} rows, {sessions} sessions", flush=True)
    return info, per


def _links_worker(sid):
    """Format sniff + cross-session subagent links of one transcript, exactly as full_pass_worker computes them."""
    path = os.path.join(TRANS, sid + ".jsonl")
    fmt = sniff_text(read_head(path))
    text, _ = read_text(path)
    return sid, fmt, _child_links(fmt, text)


def build_split_e(rederive=(), scratch=None):
    """E split -> analysis/cache/swechat_E.parquet through write_split_cache (the A/B per-session code path).
    E ids = analysis/cache/samples/swechat_EH.json key "E" (analysis/probes/phase_e_split.py); the "H" key is never used and
    no H transcript is opened. Differences from main(), all forced by that rule or by not rewriting A/B artifacts:
      * no full-population pass: format and stratum come from swechat_population.parquet (written by main's full pass);
        each E transcript's format is re-sniffed and must agree with it.
      * cross-session subagent links (ctx) are collected with the same _child_links over the transcripts of A, B and E
        only. An E child session whose spawning call lives in a transcript outside A+B+E keeps parent_call_id = None
        (main() resolved links against all 5,850 transcripts). ctx only feeds the parent_call_id of session-level
        OpenCode/Codex subagent sessions.
      * the sample files, swechat_population.parquet, the A/B caches and analysis/out/build/swechat_build.json are not
        written. Report: analysis/out/phase_e/swechat_E_build.json.
    rederive: splits from swechat.json (e.g. "A") re-derived through the same path with the same ctx into `scratch`
    (swechat_<split>.rederived.parquet; never analysis/cache) for an equivalence check against the existing caches."""
    t_start = time.time()
    with open(os.path.join(CACHE, "samples", f"{CORPUS}_EH.json"), encoding="utf-8") as f:
        e_ids = list(json.load(f)["E"])
    with open(os.path.join(CACHE, "samples", f"{CORPUS}.json"), encoding="utf-8") as f:
        ab = json.load(f)
    allowed = sorted(set(ab["A"]) | set(ab["B"]) | set(e_ids))
    assert len(set(e_ids) & (set(ab["A"]) | set(ab["B"]))) == 0
    pop = pd.read_parquet(os.path.join(CACHE, "swechat_population.parquet"), filters=[("session_id", "in", allowed)])
    assert set(pop.session_id) == set(allowed), "population table lacks sampled sessions"
    fmt_of = dict(zip(pop.session_id, pop.format))
    strat = dict(zip(pop.session_id, pop.stratum))
    t0 = time.time()
    with Pool(N_PROC) as pool:
        lk = sorted(pool.imap_unordered(_links_worker, allowed, chunksize=4))
    links_secs = time.time() - t0
    fmt_mismatch = [sid for sid, fmt, _ in lk if fmt != fmt_of[sid]]
    assert not fmt_mismatch, f"re-sniffed format differs from the population table: {fmt_mismatch[:5]}"
    links_oc, links_cx = {}, {}
    for sid, fmt, links in lk:  # session_id order, as in main()
        (links_oc if fmt == "opencode" else links_cx if fmt == "codex" else {}).update(links)
    ctx = {"opencode_task": links_oc, "codex_spawn": links_cx}
    t1 = time.time()
    info, per = write_split_cache("E", e_ids, fmt_of, strat, ctx)
    e_secs = time.time() - t1
    report = {"corpus": CORPUS, "snapshot": SNAPSHOT, "loader_version": LOADER_VERSION, "split": "E",
              "entry_point": "python -m analysis.loaders.load_swechat --split E",
              "split_source": "analysis/cache/samples/swechat_EH.json#E",
              "cache": info,
              "ctx": {"transcripts_scanned": len(allowed), "scope": "A + B + E transcripts (H never opened)",
                      "opencode_child_to_task_call": len(links_oc), "codex_thread_to_spawn_call": len(links_cx),
                      "format_resniff_mismatches": len(fmt_mismatch), "wall_seconds": round(links_secs, 1)},
              "per_format_E": aggregate_by_format((fmt, st, summ) for _, fmt, st, summ in per),
              "session_level_subagent_sessions_E": sum(1 for _, _, st, _ in per if st.get("session_subagent")),
              "parser_exceptions_E": [(sid, fmt, st["exception"]) for sid, fmt, st, _ in per if st.get("exception")],
              "wall_seconds_E_cache": round(e_secs, 1)}
    if rederive:
        assert scratch and not os.path.abspath(scratch).startswith(os.path.abspath(CACHE)), "rederive needs a scratch dir outside analysis/cache"
        os.makedirs(scratch, exist_ok=True)
        report["rederived"] = {}
        for sp in rederive:
            p = os.path.join(scratch, f"{CORPUS}_{sp}.rederived.parquet")
            ri, _ = write_split_cache(sp, ab[sp], fmt_of, strat, ctx, path=p)
            ri["path"] = "scratch (throwaway)"
            report["rederived"][sp] = ri
    report["wall_seconds_total"] = round(time.time() - t_start, 1)
    out = os.path.join(HERE, "out", "phase_e")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, f"{CORPUS}_E_build.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, default=lambda o: int(o) if isinstance(o, np.integer) else str(o))
    print(f"E done in {time.time() - t_start:.0f}s")


# ------------------------------------------------------------------------------------------------------------- main

def normalize_label(label):
    if label is None or (isinstance(label, float) and np.isnan(label)):
        return "unknown"
    s = str(label).strip()
    return LABEL_ALIASES.get(s.casefold(), s)


def main():
    t_start = time.time()
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(os.path.join(CACHE, "samples"), exist_ok=True)
    report = {"corpus": CORPUS, "snapshot": SNAPSHOT, "loader_version": LOADER_VERSION,
              "source": {"sessions": "sessions.parquet", "events": "transcripts/<session_id>.jsonl"}}

    # ---- population
    sess = pd.read_parquet(os.path.join(DATA, "sessions.parquet"), columns=["session_id", "agent"])
    files = {f[:-6] for f in os.listdir(TRANS) if f.endswith(".jsonl")}
    sess["norm_label"] = sess["agent"].map(normalize_label)
    counts = sess[sess.session_id.isin(files)]["norm_label"].value_counts()
    small = set(counts[counts < 5].index)
    sess["stratum"] = sess["norm_label"].map(lambda x: "other" if x in small else x)
    has = sess[sess.session_id.isin(files)].sort_values("session_id").reset_index(drop=True)
    missing = sess[~sess.session_id.isin(files)][["session_id", "agent"]].values.tolist()
    report["population"] = {
        "sessions_parquet_rows": int(len(sess)), "sessions_parquet_distinct_ids": int(sess.session_id.nunique()),
        "transcript_files": len(files), "sessions_with_transcript": int(len(has)),
        "sessions_without_transcript": missing, "files_without_session_row": sorted(files - set(sess.session_id)),
        "label_counts_raw": {str(k): int(v) for k, v in sess["agent"].value_counts(dropna=False).items()},
        "label_aliases": LABEL_ALIASES, "labels_folded_to_other": sorted(small),
        "stratum_counts": {k: int(v) for k, v in has["stratum"].value_counts().items()},
    }

    # ---- full-population pass (every file): sniff, parse, summarize, length, redaction, cross-session links
    jobs = list(zip(has.session_id, has.agent, has.stratum))
    sizes = {sid: os.path.getsize(os.path.join(TRANS, sid + ".jsonl")) for sid in has.session_id}
    jobs.sort(key=lambda j_: -sizes[j_[0]])
    t0 = time.time()
    full = []
    with Pool(N_PROC) as pool:
        for i, r in enumerate(pool.imap_unordered(full_pass_worker, jobs, chunksize=2)):
            full.append(r)
            if (i + 1) % 500 == 0:
                print(f"full pass {i + 1}/{len(jobs)} {time.time() - t0:.0f}s", flush=True)
            if time.time() - t0 > FULL_PASS_BUDGET_S:
                raise RuntimeError("full pass exceeded budget; switch to a seeded 1,000-file sample")
    full_secs = time.time() - t0
    full.sort(key=lambda r: r["session_id"])
    fmt_of = {r["session_id"]: r["format"] for r in full}
    pop = pd.DataFrame({"session_id": [r["session_id"] for r in full], "agent": [r["label"] for r in full],
                        "stratum": [r["stratum"] for r in full], "format": [r["format"] for r in full],
                        "length": [int(r["length"]) for r in full], "bytes": [int(r["stat"].get("bytes", 0)) for r in full]})
    pop.to_parquet(os.path.join(CACHE, "swechat_population.parquet"), index=False)

    ct = pd.crosstab(pop["agent"].fillna("None"), pop["format"])
    report["label_x_format"] = {lab: {f: int(n) for f, n in row.items() if n} for lab, row in ct.iterrows()}
    report["format_counts_population"] = {k: int(v) for k, v in pop["format"].value_counts().items()}
    report["stratum_x_format"] = {s: {f: int(n) for f, n in row.items() if n}
                                  for s, row in pd.crosstab(pop["stratum"], pop["format"]).iterrows()}

    agg_full = aggregate_by_format((r["format"], r["stat"], r["summary"]) for r in full)
    red_raw = {}
    for r in full:
        _add(red_raw.setdefault(r["format"], {}), r["redaction_raw"])
    links_oc, links_cx = {}, {}
    for r in full:
        (links_oc if r["format"] == "opencode" else links_cx if r["format"] == "codex" else {}).update(r["links"])
    exceptions = [(r["session_id"], r["format"], r["stat"]["exception"]) for r in full if r["stat"].get("exception")]
    doc_fail = [(r["session_id"], r["format"], r["stat"].get("doc"), r["stat"].get("salvaged_messages"))
                for r in full if r["stat"].get("doc") not in (None, "ok")]
    report["full_population_pass"] = {
        "mode": "all files", "files": len(full), "wall_seconds": round(full_secs, 1), "processes": N_PROC,
        "by_format": {f: {"files": a["files"], "parse": a["parse"],
                          "calls": a["summary"].get("calls", 0), "results": a["summary"].get("results", 0),
                          "events": a["summary"].get("events", 0), "kinds": a["summary"].get("kinds", {}),
                          "calls_subagent": a["summary"].get("calls_subagent", 0),
                          "calls_nested_subagent": a["summary"].get("calls_nested_subagent", 0),
                          "calls_sidechain_toplevel": a["summary"].get("calls_sidechain_toplevel", 0),
                          "calls_session_subagent": a["summary"].get("calls_session_subagent", 0),
                          "results_without_call": a["summary"].get("results_without_call", 0),
                          "calls_without_result": a["summary"].get("calls_without_result", 0),
                          "synthetic_call_ids": a["summary"].get("synthetic_call_ids", 0),
                          "duplicate_call_ids": a["summary"].get("duplicate_call_ids", 0),
                          "ts_backward_steps": a["summary"].get("ts_backward_steps", 0),
                          "events_with_ts": a["summary"].get("events_with_ts", 0),
                          "calls_by_tool_top40": a["calls_by_tool_top40"], "distinct_tool_raw": a["distinct_tool_raw"]}
                      for f, a in sorted(agg_full.items())},
        "totals": {k: int(sum(a["summary"].get(k, 0) for a in agg_full.values()))
                   for k in ("events", "calls", "results", "calls_subagent", "calls_nested_subagent",
                             "calls_sidechain_toplevel", "calls_session_subagent", "results_without_call", "calls_without_result")},
        "parser_exceptions": exceptions, "document_parse_not_ok": doc_fail,
        "cross_session_links": {"opencode_child_to_task_call": len(links_oc), "codex_thread_to_spawn_call": len(links_cx)},
        "length_by_format": {f: {"sum": int(g.sum()), "median": float(g.median()), "max": int(g.max())}
                             for f, g in pop.groupby("format")["length"]},
    }
    report["redaction_markers_raw_files"] = red_raw

    # ---- sample
    smp = sample.draw(pop[["session_id", "stratum", "length"]], CORPUS)
    sample.save(smp, os.path.join(CACHE, "samples", f"{CORPUS}.json"))
    report["sample"] = {"seed": smp["seed"], "population_sessions": smp["population_sessions"], "A": len(smp["A"]),
                        "B": len(smp["B"]), "rule": smp["rule"], "file": "analysis/cache/samples/swechat.json",
                        "A_by_stratum": pop[pop.session_id.isin(smp["A"])]["stratum"].value_counts().to_dict(),
                        "B_by_stratum": pop[pop.session_id.isin(smp["B"])]["stratum"].value_counts().to_dict(),
                        "A_by_format": pop[pop.session_id.isin(smp["A"])]["format"].value_counts().to_dict(),
                        "B_by_format": pop[pop.session_id.isin(smp["B"])]["format"].value_counts().to_dict()}

    # ---- A/B caches
    ctx = {"opencode_task": links_oc, "codex_spawn": links_cx}
    strat = dict(zip(pop.session_id, pop.stratum))
    ab_rows, xcheck_raw, cache_info = [], {}, {}
    for split in ("A", "B"):
        cache_info[split], per = write_split_cache(split, smp[split], fmt_of, strat, ctx)
        for sid, fmt, st, summ in per:
            ab_rows.append((fmt, st, summ))
            xcheck_raw[sid] = summ["xcheck_call_ids"]
    report["caches"] = cache_info

    # ---- per-format stats over A+B caches
    agg_ab = aggregate_by_format(ab_rows)
    report["per_format_AB"] = agg_ab

    # ---- cross-check vs conversations.parquet (sampled sessions)
    report["crosscheck_conversations"] = crosscheck(xcheck_raw, fmt_of)

    # ---- re-measure the reviewer's blocking-issue checks on the written caches
    report["review_fix_checks"] = review_fix_checks(fmt_of)

    # ---- notes: counts that document format quirks
    report["format_notes"] = format_notes(full)
    report["wall_seconds_total"] = round(time.time() - t_start, 1)
    with open(os.path.join(OUT, "swechat_build.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, default=lambda o: int(o) if isinstance(o, np.integer) else str(o))
    print(f"done in {time.time() - t_start:.0f}s")


def review_fix_checks(fmt_of):
    """Recompute, from the written A+B caches, the reviewer's measurements behind the three blocking issues
    (analysis/out/build/swechat_review.json) so the fix is checked on the artifacts probes read."""
    cols = ["session_id", "seq", "kind", "tool", "tool_raw", "call_id", "text", "native_error", "exit_code", "usage_in",
            "api_msg_id", "extra"]
    parts = []
    for split in ("A", "B"):
        pf = pq.ParquetFile(os.path.join(CACHE, f"{CORPUS}_{split}.parquet"))
        for g in range(pf.num_row_groups):
            t = pf.read_row_group(g, columns=cols).to_pandas()
            fm = t.session_id.map(fmt_of)
            keep = (t.kind == "result") | t.usage_in.notna() | ((fm == "codex") & (t.kind == "meta"))
            t = t[keep].copy()
            t["format"] = fm[keep]
            parts.append(t)
    df = pd.concat(parts, ignore_index=True)
    out = {"source": "analysis/cache/swechat_A.parquet + swechat_B.parquet"}
    R = df[df.kind == "result"]
    # 1. Codex: exit attribution vs the unified-exec 'Process running' header
    cx = R[R.format == "codex"]
    run_any = cx.text.str.contains("Process running with session ID", na=False, regex=False)
    run_hdr = cx.text.map(lambda x: unified_exec_state(x)[0] == "running").astype(bool)
    ws = cx[cx.tool_raw == "write_stdin"]
    ws_exit_hdr = ws.text.map(lambda x: unified_exec_state(x)[0] == "exited").astype(bool)
    ws_eq = 0
    for t_, e_ in zip(ws.text, ws.exit_code):
        if not pd.isna(e_) and unified_exec_state(t_) == ("exited", int(e_)):
            ws_eq += 1
    out["codex_running_output_exit_attribution"] = {
        "codex_results": int(len(cx)), "native_true": int((cx.native_error == True).sum()),
        "results_text_contains_process_running": int(run_any.sum()),
        "of_which_exit_code_set": int(cx[run_any].exit_code.notna().sum()),
        "of_which_native_true": int((cx[run_any].native_error == True).sum()),
        "results_header_process_running": int(run_hdr.sum()),
        "of_which_header_running_exit_code_set": int(cx[run_hdr].exit_code.notna().sum()),
        "of_which_header_running_native_nonnull": int(cx[run_hdr].native_error.notna().sum()),
        "write_stdin_results": int(len(ws)),
        "write_stdin_text_contains_process_exited": int(ws.text.str.contains("Process exited with code", na=False, regex=False).sum()),
        "write_stdin_header_exited": int(ws_exit_hdr.sum()),
        "write_stdin_native_nonnull": int(ws.native_error.notna().sum()),
        "write_stdin_native_true": int((ws.native_error == True).sum()),
        "write_stdin_exit_code_set": int(ws.exit_code.notna().sum()),
        "write_stdin_header_exited_exit_code_set": int(ws[ws_exit_hdr].exit_code.notna().sum()),
        "write_stdin_header_exit_eq_exit_code": ws_eq}
    # 2. error flag vs nonzero exit (shell results), same definitions as the review
    err = {}
    for f in ("claude_code", "codex", "opencode"):
        sh = R[(R.format == f) & (R.tool == "shell")]
        d = {"shell_results": int(len(sh)), "native_error_true": int((sh.native_error == True).sum())}
        if f == "claude_code":
            ex_ = sh.text.str.match(r"^Exit code [1-9]", na=False)
            d.update({"text_exit_code_nonzero": int(ex_.sum()), "of_which_native_true": int((sh[ex_].native_error == True).sum())})
        else:
            nz = sh.exit_code.fillna(0) != 0
            d.update({"exit_code_nonzero": int(nz.sum()), "of_which_native_true": int((sh[nz].native_error == True).sum())})
        err[f] = d
    oc = R[R.format == "opencode"]
    oc_nz = oc.exit_code.fillna(0) != 0
    err["opencode_all_results"] = {
        "native_true": int((oc.native_error == True).sum()),
        "native_true_or_exit_nonzero": int(((oc.native_error == True) | oc_nz).sum()),
        "exit_nonzero_native_false": int((oc_nz & (oc.native_error == False)).sum()),
        "sessions_with_exit_nonzero_native_false": int(oc[oc_nz & (oc.native_error == False)].session_id.nunique())}
    out["error_flag_vs_exit"] = err
    # 3. usage rows and api_msg_id
    U = df[df.usage_in.notna()]
    out["usage_rows"] = {f: {"rows": int(len(g)), "api_msg_id_null": int(g.api_msg_id.isna().sum()),
                             "api_msg_id_synthetic": int(g.api_msg_id.str.startswith("synthetic:", na=False).sum()),
                             "usage_in_sum": int(g.usage_in.sum()),
                             "usage_in_sum_null_id": int(g[g.api_msg_id.isna()].usage_in.sum()),
                             "usage_in_sum_dedup_session_and_id": int(g.drop_duplicates(["session_id", "api_msg_id"]).usage_in.sum()),
                             "usage_in_sum_dedup_id_global": int(g.drop_duplicates("api_msg_id").usage_in.sum()),
                             "usage_in_sum_groupby_id_first": int(g.groupby("api_msg_id").usage_in.first().sum())}
                         for f, g in U.groupby("format")}
    tc = df[(df.format == "codex") & (df.kind == "meta") & df.extra.str.contains('"type":"token_count"', na=False)]
    c = collections.Counter()
    for sid, g in tc.groupby("session_id"):
        g = g.sort_values("seq")
        prev = None
        for x, ui, mid in zip(g.extra, g.usage_in, g.api_msg_id):
            e = json.loads(x)
            if e.get("total_token_usage") is None:
                c["rows_without_info"] += 1
                c["rows_without_info_usage_nonnull"] += int(not pd.isna(ui))
                continue
            c["rows_with_info"] += 1
            t_ = json.dumps(e["total_token_usage"], sort_keys=True)
            if t_ == prev:
                c["repeat_of_previous_total"] += 1
                c["repeat_usage_in_nonnull"] += int(not pd.isna(ui))
                c["repeat_usage_in_sum"] += 0 if pd.isna(ui) else int(ui)
                c["repeat_flagged"] += int(bool(e.get("repeat_of_previous_total")))
            else:
                c["new_total_rows"] += 1
                c["new_total_api_msg_id_null"] += int(pd.isna(mid))
            prev = t_
    out["codex_token_count_repeats"] = dict(c)
    return out


def crosscheck(xcheck_raw, fmt_of):
    """tool_use rows per session in conversations.parquet vs raw-parse calls that are not in-file nested subagent calls.
    xcheck_raw: {session_id: [(call_id, is_synthetic), ...]}. Id-set comparisons skip synthetic raw ids and table ids
    that the release redacted to "REDACTED" (both counted)."""
    sids = set(xcheck_raw)
    pf = pq.ParquetFile(os.path.join(DATA, "conversations.parquet"))
    tab_rows, tab_ids, tab_dup = collections.Counter(), collections.defaultdict(set), collections.Counter()
    tab_red = collections.Counter()
    present = set()
    for g in range(pf.num_row_groups):
        t = pf.read_row_group(g, columns=["session_id", "role", "tool_call_id"]).to_pandas()
        t = t[t.session_id.isin(sids)]
        present.update(t.session_id.unique())
        tu = t[t.role == "tool_use"]
        for s, c in zip(tu.session_id.values, tu.tool_call_id.values):
            tab_rows[s] += 1
            if c is None or (isinstance(c, float) and np.isnan(c)):
                continue
            if "REDACTED" in c:
                tab_red[s] += 1
                continue
            if c in tab_ids[s]:
                tab_dup[s] += 1
            tab_ids[s].add(c)
    per_fmt = {}
    out = {"definition": "table = rows with role=='tool_use' in conversations.parquet; raw = IR calls excluding calls "
                         "nested inside another call's progress stream (CC agent_progress: is_subagent with "
                         "parent_call_id). Top-level isSidechain entries and session-level subagent sessions (OpenCode "
                         "child, Codex sub-agent rollout) count, since the table holds them as tool_use rows/sessions.",
           "sampled_sessions": len(sids), "sessions_absent_from_table": sorted(sids - present)}
    for s, pairs in xcheck_raw.items():
        f = fmt_of[s]
        d = per_fmt.setdefault(f, collections.Counter())
        n_raw, n_tab = len(pairs), tab_rows.get(s, 0)
        d["sessions"] += 1
        d["sessions_in_table"] += int(s in present)
        d["table_tool_use_rows"] += n_tab
        d["raw_calls"] += n_raw
        if s not in present:
            continue
        d["table_rows_in_present_sessions"] += n_tab
        d["raw_calls_in_present_sessions"] += n_raw
        d["sessions_equal"] += int(n_raw == n_tab)
        d["sessions_raw_more"] += int(n_raw > n_tab)
        d["sessions_raw_fewer"] += int(n_raw < n_tab)
        if n_raw > n_tab:
            d["raw_minus_table_where_raw_more"] += n_raw - n_tab
        if n_raw < n_tab:
            d["table_minus_raw_where_raw_fewer"] += n_tab - n_raw
        rs = {c for c, syn in pairs if not syn and c}
        d["raw_synthetic_ids_skipped"] += sum(1 for c, syn in pairs if syn)
        d["table_REDACTED_ids_skipped"] += tab_red.get(s, 0)
        d["table_duplicate_id_rows"] += tab_dup.get(s, 0)
        d["table_ids_not_in_raw"] += len(tab_ids.get(s, set()) - rs)
        d["raw_ids_not_in_table"] += len(rs - tab_ids.get(s, set()))
    out["by_format"] = {f: dict(c) for f, c in sorted(per_fmt.items())}
    tot = collections.Counter()
    for c in per_fmt.values():
        tot.update(c)
    out["totals"] = dict(tot)
    return out


def format_notes(full):
    """Aggregate counts about raw-format quirks (computed from the full pass)."""
    notes = collections.Counter()
    for r in full:
        st, s = r["stat"], r["summary"]
        f = r["format"]
        if f == "claude_code" and st.get("cc_fixture_entries"):
            notes["claude_code_files_with_tool_use_or_tool_result_entry_types"] += 1
        if f == "opencode" and st.get("redacted_message_ids"):
            notes["opencode_files_with_message_id_REDACTED"] += 1
            notes["opencode_message_ids_REDACTED"] += st["redacted_message_ids"]
        if st.get("utf8_replaced"):
            notes[f"{f}_files_with_invalid_utf8"] += 1
        if s.get("events", 0) == 0:
            notes[f"{f}_files_with_zero_events"] += 1
    return dict(notes)


if __name__ == "__main__":
    import argparse
    _ap = argparse.ArgumentParser()
    _ap.add_argument("--split", choices=["E"], help="build only this extra split's cache (E); default: full A/B build")
    _ap.add_argument("--rederive", nargs="*", default=[], choices=["A", "B"],
                     help="with --split E: also re-derive these A/B splits into --scratch for an equivalence check")
    _ap.add_argument("--scratch", help="output dir for --rederive (must be outside analysis/cache)")
    _a = _ap.parse_args()
    if _a.split == "E":
        build_split_e(rederive=_a.rederive, scratch=_a.scratch)
    else:
        assert not _a.rederive, "--rederive needs --split E"
        main()
