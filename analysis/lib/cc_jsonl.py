"""Parse Claude Code JSONL entries into IR events (see ir.py).

Used by three corpora:
  - claude-code-local: files on disk, one entry per line, entry has `timestamp`.
  - SWE-chat raw transcripts (Claude Code sessions): same format; subagent traffic is nested inside
    `progress` entries with data.type == 'agent_progress' and data.message = a full entry.
  - AI Village claude_code_messages: Claude Agent SDK stream; each DB row's `content` is one entry without
    `timestamp`; the caller passes the row's created_at as ts with ts_kind='row_insert'.

Design rules
  - One IR event per content block: text -> assistant, tool_use -> call, tool_result -> result.
    Thinking blocks are not emitted; their character count goes to extra.thinking_chars on the next assistant/call event.
  - Usage is attached to every block-event of an assistant entry (blocks of one API response share api_msg_id).
    Consumers that need one usage per API call must dedupe on api_msg_id.
  - progress entries: agent_progress -> unwrap data.message (is_subagent=True, parent_call_id=parentToolUseID).
    bash_progress / mcp_progress / hook_progress -> one `meta` event with the timers in extra.
    normalizedMessages is ignored (it duplicates data.message history).
  - Duplicate entries (same uuid) are emitted once.
"""
import json
from .ir import iso, j, normalize_tool, error_marker

USER_SYSTEM_PREFIXES = ("<local-command", "<command-name>", "<command-message>", "<system-reminder>", "Caveat:",
                        "<task-notification>", "This session is being continued")


def _text_of(content):
    """tool_result.content or message.content -> plain text. Lists of blocks are joined; images become a marker."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    out = []
    for b in content if isinstance(content, list) else [content]:
        if isinstance(b, dict):
            if b.get("type") == "text":
                out.append(b.get("text") or "")
            elif b.get("type") == "image":
                out.append("[image]")
            elif "text" in b:
                out.append(str(b.get("text")))
        else:
            out.append(str(b))
    return "\n".join(out)


def _usage(msg):
    u = msg.get("usage") if isinstance(msg, dict) else None
    if not isinstance(u, dict):
        return {}
    return {"usage_in": u.get("input_tokens"), "usage_out": u.get("output_tokens"),
            "usage_cache_read": u.get("cache_read_input_tokens"), "usage_cache_create": u.get("cache_creation_input_tokens")}


class Parser:
    """Stateful per-session parser. Feed entries in file/stream order with feed(); collect .events."""

    def __init__(self, corpus, session_id, stratum, ts_kind="event"):
        self.corpus, self.session_id, self.stratum, self.ts_kind = corpus, session_id, stratum, ts_kind
        self.events, self.seen_uuid, self.call_tool = [], set(), {}
        self.pending_thinking = 0

    def _emit(self, entry, ts, **kw):
        ev = {"corpus": self.corpus, "session_id": self.session_id, "stratum": self.stratum, "seq": len(self.events),
              "ts": iso(ts), "ts_kind": self.ts_kind if ts else "none", "tool": None, "tool_raw": None, "call_id": None,
              "args": None, "command": None, "text": None, "stderr": None, "native_error": None, "exit_code": None,
              "usage_in": None, "usage_out": None, "usage_cache_read": None, "usage_cache_create": None,
              "api_msg_id": None, "request_id": entry.get("requestId"), "model": None,
              "is_subagent": bool(entry.get("isSidechain")) or bool(entry.get("_nested")),
              "parent_call_id": entry.get("_parent_call_id"), "agent_id": entry.get("agentId") or entry.get("_agent_id"),
              "uuid": entry.get("uuid"), "parent_uuid": entry.get("parentUuid"), "extra": None}
        ev.update(kw)
        self.events.append(ev)
        return ev

    def feed(self, entry, ts=None):
        """entry: one parsed JSONL object. ts: override timestamp (AI Village row created_at)."""
        if not isinstance(entry, dict):
            return
        uid = entry.get("uuid")
        if uid:
            if uid in self.seen_uuid:
                return
            self.seen_uuid.add(uid)
        ts = ts if ts is not None else entry.get("timestamp")
        t = entry.get("type")
        if t == "progress":
            self._progress(entry, ts)
        elif t in ("assistant", "user"):
            self._message(entry, ts)
        elif t == "system":
            sub = entry.get("subtype")
            extra = {k: entry.get(k) for k in ("subtype", "level", "durationMs", "compactMetadata", "compact_metadata", "status") if k in entry}
            self._emit(entry, ts, kind="meta", text=entry.get("content") if isinstance(entry.get("content"), str) else None,
                       extra=j({"entry_type": "system", **extra}) if sub or extra else j({"entry_type": "system"}))
        elif t == "result":  # Agent SDK end-of-run row
            keep = {k: entry.get(k) for k in ("subtype", "is_error", "num_turns", "duration_ms", "duration_api_ms", "total_cost_usd", "stop_reason")}
            self._emit(entry, ts, kind="meta", extra=j({"entry_type": "result", **keep}))
        # other entry types (file-history-snapshot, queue-operation, attachment, summary, titles...) are not model-visible
        # tool traffic; they are skipped here and inventoried separately by Phase A6.

    def _progress(self, entry, ts):
        d = entry.get("data") if isinstance(entry.get("data"), dict) else {}
        dt = d.get("type")
        if dt == "agent_progress" and isinstance(d.get("message"), dict):
            inner = dict(d["message"])
            inner["_nested"] = True
            inner["_parent_call_id"] = entry.get("parentToolUseID")
            inner["_agent_id"] = d.get("agentId")
            if "uuid" not in inner and isinstance(inner.get("message"), dict):
                inner["uuid"] = None
            self.feed(inner, inner.get("timestamp") or ts)
        else:
            keep = {k: d.get(k) for k in ("type", "elapsedTimeSeconds", "elapsedTimeMs", "totalBytes", "totalLines",
                                          "timeoutMs", "status", "serverName", "toolName", "hookEvent", "hookName", "taskId")
                    if k in d}
            self._emit(entry, ts, kind="meta", parent_call_id=entry.get("parentToolUseID") or entry.get("_parent_call_id"),
                       extra=j({"entry_type": "progress", **keep}))

    def _message(self, entry, ts):
        msg = entry.get("message") if isinstance(entry.get("message"), dict) else {}
        content = msg.get("content")
        role = entry.get("type")
        if role == "assistant":
            base = {"api_msg_id": msg.get("id"), "model": msg.get("model"), **_usage(msg)}
            blocks = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                if bt in ("thinking", "redacted_thinking"):
                    self.pending_thinking += len(b.get("thinking") or "")
                elif bt == "text":
                    ex = {"thinking_chars": self.pending_thinking} if self.pending_thinking else None
                    self.pending_thinking = 0
                    self._emit(entry, ts, kind="assistant", text=b.get("text") or "", extra=j(ex), **base)
                elif bt in ("tool_use", "server_tool_use"):
                    name = b.get("name")
                    inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                    self.call_tool[b.get("id")] = name
                    ex = {"thinking_chars": self.pending_thinking} if self.pending_thinking else {}
                    if bt == "server_tool_use":
                        ex["server_tool"] = True
                    self.pending_thinking = 0
                    tool = normalize_tool(name)
                    self._emit(entry, ts, kind="call", tool=tool, tool_raw=name, call_id=b.get("id"), args=j(inp),
                               command=inp.get("command") if tool == "shell" else None, extra=j(ex or None), **base)
        else:  # user entry: tool results, human prompt, or harness-injected text
            tur = entry.get("toolUseResult", entry.get("tool_use_result"))
            if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                for b in content:
                    if not isinstance(b, dict) or b.get("type") != "tool_result":
                        continue
                    cid = b.get("tool_use_id")
                    name = self.call_tool.get(cid)
                    text = _text_of(b.get("content"))
                    ex, stderr, exit_code = {}, None, None
                    if isinstance(tur, dict):
                        for k in ("durationMs", "durationSeconds", "timedOutAfterMs", "interrupted", "returnCodeInterpretation",
                                  "persistedOutputSize", "totalDurationMs", "totalTokens", "totalToolUseCount", "bytes", "code",
                                  "numFiles", "truncated", "backgroundTaskId", "noOutputExpected"):
                            if k in tur:
                                ex[k] = tur[k]
                        if isinstance(tur.get("stderr"), str):
                            stderr = tur["stderr"]
                        if isinstance(tur.get("usage"), dict):
                            ex["subagent_usage"] = tur["usage"]
                    ex["marker"] = error_marker(text)
                    self._emit(entry, ts, kind="result", tool=normalize_tool(name), tool_raw=name, call_id=cid, text=text,
                               stderr=stderr, native_error=b.get("is_error") if "is_error" in b else None,
                               exit_code=exit_code, extra=j(ex))
            else:
                text = _text_of(content)
                is_sys = bool(entry.get("isMeta")) or bool(entry.get("isSynthetic")) or text.lstrip().startswith(USER_SYSTEM_PREFIXES) \
                    or bool(entry.get("_nested"))  # a subagent's 'user' turn is the parent's prompt, not a human
                self._emit(entry, ts, kind="system" if is_sys else "user", text=text,
                           extra=j({"nested_prompt": True}) if entry.get("_nested") else None)


def parse_lines(lines, corpus, session_id, stratum):
    """Parse an iterable of JSONL text lines. Returns (events, n_bad_lines)."""
    p = Parser(corpus, session_id, stratum)
    bad = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            p.feed(json.loads(line))
        except json.JSONDecodeError:
            bad += 1
    return p.events, bad
