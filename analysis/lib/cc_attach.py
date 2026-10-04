"""Claude Code `attachment` entries -> IR (kind, text, extra). Shared by load_cc_local and cc_jsonl.Parser.

Moved verbatim from analysis/loaders/load_cc_local.py (see its docstring, ENTRY -> IR MAPPING, for the visibility
and text_source rules and the evidence behind the type lists). attachment_event(e, nested, A=None) returns
(kind, text, extra dict, payload text or None); A is an optional Counter of raw checks.
"""
import collections
import re

from . import cc_jsonl

RENDER_MIN_VERSION = (2, 1, 266)
# types seen with a `rendered` list in versions >= RENDER_MIN_VERSION (model-visible there)
ATT_RENDERED_TYPES = frozenset({
    "total_tokens_reminder", "deferred_tools_delta", "skill_listing", "mcp_instructions_delta", "queued_command",
    "remote_session_change", "environment", "edited_text_file", "date", "auto_mode", "instructions", "model",
    "session_context", "agent_listing_delta", "hook_additional_context", "ultra_effort_enter", "file",
    "silent_turn_reminder", "read_truncation_notice", "compact_file_reference", "nested_memory",
    "workflow_keyword_request", "task_status", "inlined_image_paths", "invoked_skills"})
# types that occur only in versions without `rendered`, judged model-visible from their payload
ATT_OLD_ONLY_VISIBLE = frozenset({"batching_reminder_sent", "task_reminder", "date_change", "ultra_effort_exit", "budget_usd"})
# never rendered in versions that record renderings (or, command_permissions, a permission-state record)
ATT_HIDDEN = frozenset({"prompt_snapshot", "structured_output", "deferred_tools_record", "credential_org", "command_permissions"})


def _join(xs):
    xs = [x for x in (xs if isinstance(xs, list) else []) if isinstance(x, str) and x.strip()]
    return "\n".join(xs) if xs else None


def _sub(d, *path):
    for k in path:
        d = d.get(k) if isinstance(d, dict) else None
    return d


# attachment type -> (field label, extractor): the field holding the body text of the rendering
ATT_PAYLOAD = {
    "total_tokens_reminder": ("text", lambda a: a.get("text")),
    "batching_reminder_sent": ("text", lambda a: a.get("text")),
    "silent_turn_reminder": ("text", lambda a: a.get("text")),
    "model": ("text", lambda a: a.get("text")),
    "skill_listing": ("content", lambda a: a.get("content")),
    "queued_command": ("prompt", lambda a: cc_jsonl._text_of(a.get("prompt")) if a.get("prompt") is not None else None),
    "edited_text_file": ("snippet", lambda a: a.get("snippet")),
    "read_truncation_notice": ("banner", lambda a: a.get("banner")),
    "hook_additional_context": ("content", lambda a: _join(a.get("content"))),
    "deferred_tools_delta": ("addedLines", lambda a: _join(a.get("addedLines"))),
    "agent_listing_delta": ("addedLines", lambda a: _join(a.get("addedLines"))),
    "mcp_instructions_delta": ("addedBlocks", lambda a: _join(a.get("addedBlocks"))),
    "remote_session_change": ("commit+pr", lambda a: _join([a.get("commit"), a.get("pr")])),
    "file": ("content.file.content", lambda a: _sub(a, "content", "file", "content")),
    "nested_memory": ("content.content", lambda a: _sub(a, "content", "content")),
    "instructions": ("files[].content", lambda a: _join([f.get("content") for f in a.get("files") or [] if isinstance(f, dict)])),
    "date": ("date", lambda a: a.get("date")),
    "date_change": ("newDate", lambda a: a.get("newDate")),
}
STATUS_RX = re.compile(r"<status>\s*([^<\s]{1,40})\s*</status>")
TASK_NOTE = "<task-notification>"
NOTE_HEADER = "[SYSTEM NOTIFICATION"
OVERLAP_MIN_CHARS = 20


def _norm(s):
    return re.sub(r"\s+", " ", s).strip()


def _version(v):
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(v or ""))
    return tuple(int(x) for x in m.groups()) if m else None


def _statuses(text):
    return STATUS_RX.findall(text) if isinstance(text, str) else []


def attachment_event(e, nested, A=None):
    """One attachment entry -> (kind, text, extra dict, payload text or None). A: raw counters (copies included)."""
    if A is None:
        A = collections.Counter()
    a = e.get("attachment") if isinstance(e.get("attachment"), dict) else {}
    at = a.get("type")
    r = e.get("rendered")
    rtext = None
    if isinstance(r, list):
        parts = [cc_jsonl._text_of(x.get("content")) for x in r if isinstance(x, dict)]
        rtext = "\n".join(x for x in parts if x) or None
    field, fn = ATT_PAYLOAD.get(at, (None, None))
    payload = fn(a) if fn else None
    if not (isinstance(payload, str) and payload.strip()):
        payload = None
    ver = _version(e.get("version"))
    if rtext is not None:
        vis = "rendered"
    elif ver is not None and ver >= RENDER_MIN_VERSION:
        vis = "not_rendered_in_rendering_version"
    elif at in ATT_RENDERED_TYPES:
        vis = "type_rendered_in_newer_versions"
    elif at in ATT_OLD_ONLY_VISIBLE:
        vis = "old_only_type_assumed_visible"
    elif at in ATT_HIDDEN:
        vis = "type_never_rendered"
    else:
        vis = "unknown_type"
    visible = vis in ("rendered", "type_rendered_in_newer_versions", "old_only_type_assumed_visible")
    ex = {"entry_type": "attachment", "attachment_type": at, "visibility": vis}
    for k in ("toolUseID", "hookEvent"):
        if isinstance(a.get(k), str):
            ex[k] = a[k]
    if isinstance(e.get("renderedRole"), str):
        ex["rendered_role"] = e["renderedRole"]
    mode = a.get("commandMode") if at == "queued_command" else None
    if at == "queued_command":
        ex["command_mode"] = mode
        if "renderedInHumanTurn" in e:
            ex["rendered_in_human_turn_variant"] = True
        if mode == "task-notification":
            ex["notification_statuses"] = _statuses(payload or rtext)
    # raw checks (every line, resume-chain copies included)
    A[f"by_type|{at}|{vis}|{'with_rendered' if rtext is not None else 'no_rendered'}"] += 1
    if at in ATT_RENDERED_TYPES and rtext is not None and ver is not None and ver < RENDER_MIN_VERSION:
        A["rendered_below_min_version"] += 1
    if at in ATT_HIDDEN and rtext is not None:
        A["hidden_type_with_rendered"] += 1
    if rtext is not None and field is not None:
        if payload is None:
            res = "payload_empty"
        else:
            nr = _norm(rtext)
            res = ("contained" if _norm(payload) in nr else
                   "all_lines_contained" if all(_norm(x) in nr for x in payload.splitlines() if x.strip()) else "not_contained")
        A[f"payload_vs_rendered|{at}|{field}|{res}"] += 1
    if not visible:
        return "meta", None, ex, None
    if mode == "prompt" and not nested:
        ex["text_source"] = f"payload:{field}" if payload is not None else "unavailable"
        return "user", payload, ex, payload
    if rtext is not None:
        ex["text_source"], text = "rendered", rtext
    elif payload is not None:
        ex["text_source"], text = f"payload:{field}", payload
    else:
        ex["text_source"], text = "unavailable", None
    return "system", text, ex, payload


