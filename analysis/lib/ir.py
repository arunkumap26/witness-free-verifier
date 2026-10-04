"""Common event IR for the signal feasibility probe.

Every corpus loader emits rows with exactly these columns (see COLUMNS). One row = one event.
Probes read only the IR caches (analysis/cache/<corpus>_<split>.parquet), never raw data.

kind values
  user       human-authored prompt text the model saw
  system     harness/system-injected text the model saw (reminders, command stdout, compaction summaries)
  assistant  model-generated text (text blocks; thinking goes to extra.thinking_chars only)
  call       a tool invocation (one per tool_use / function_call block)
  result     a tool result (one per tool_result / function_call_output block)
  meta       not shown to the model but carries timing/state (progress events, hooks, token_count, result rows)

ts_kind values
  event        timestamp written by the agent harness when the event happened (Claude Code `timestamp`, Codex `timestamp`, OpenCode `time`)
  row_insert   database row-insert time (AI Village `created_at`); may lag the event
  shared_turn  one stamp shared by a call and its result (AI Village computer_use_turns)
  none         no timestamp available (Who&When)
"""
import json, re
from datetime import datetime, timezone

COLUMNS = {
    "corpus": "str",            # swechat | cc_local | aiv_cc | aiv_cu | whowhen
    "session_id": "str",        # unit of sampling and resampling
    "stratum": "str",           # scaffold / provider-model family used for stratified sampling
    "seq": "int64",             # order within session, 0..n-1, file/stream order
    "kind": "str",              # see module docstring
    "ts": "str",                # ISO-8601 UTC with all fractional digits present in the source, or None
    "ts_kind": "str",           # see module docstring
    "tool": "str",              # normalized tool name (see normalize_tool), None for non-tool events
    "tool_raw": "str",          # tool name as written in the source
    "call_id": "str",           # id joining call<->result, None otherwise
    "args": "str",              # call input as a JSON string (calls only)
    "command": "str",           # shell command string for shell calls, else None
    "text": "str",              # model-visible text: result content, assistant text, user/system text
    "stderr": "str",            # separate stderr channel when the source has one (aiv_cu `error`, toolUseResult.stderr)
    "native_error": "boolean",  # harness-recorded error flag (is_error, OpenCode status=error, nonzero exit), None if absent
    "exit_code": "Int64",       # harness-recorded exit code when the source has a field for it (not parsed from text)
    "usage_in": "Int64",        # API usage on assistant/call events: input_tokens
    "usage_out": "Int64",       # output_tokens (beware streaming partial values; keep raw)
    # USAGE DEDUPE: several events of one API response share api_msg_id and carry copies of its usage (some formats put
    # usage on one row only). To get one usage per API call: keep rows with usage_in not null, then dedupe on
    # (session_id, api_msg_id) - NOT on api_msg_id alone: resumed/forked Claude Code sessions copy history, so one id can
    # appear in several sessions. Take max(usage_out) across the response's rows (streaming partials are smaller).
    "usage_cache_read": "Int64",
    "usage_cache_create": "Int64",
    "api_msg_id": "str",        # provider message id (msg_..., resp_..., Gemini responseId); blocks of one API response share it
    "request_id": "str",
    "model": "str",
    "is_subagent": "boolean",   # event belongs to a subagent / sidechain
    "parent_call_id": "str",    # for subagent events: the parent's Task/Agent call_id when known
    "agent_id": "str",          # subagent id when known
    "uuid": "str",
    "parent_uuid": "str",
    "extra": "str",             # JSON object with corpus-specific fields (durationMs, elapsed timers, server-timing, ...)
}

SHELL_TOOLS = {"bash", "shell", "run_shell_command", "exec_command", "local_shell", "terminal", "mcp__village__bash",
               "write_stdin", "shell_command"}  # write_stdin: Codex unified-exec poll; deferred exits land on it (tool_raw keeps it apart)


def normalize_tool(name):
    """Lowercase and fold scaffold-specific names into shared classes. Unknown names pass through lowercased."""
    if name is None:
        return None
    n = str(name).strip()
    low = n.lower()
    if low in SHELL_TOOLS or low.endswith("__bash"):
        return "shell"
    table = {"read": "read", "read_file": "read", "view": "read", "write": "write", "write_file": "write",
             "edit": "edit", "multiedit": "edit", "replace": "edit", "apply_patch": "edit", "str_replace_based_edit_tool": "edit",
             "glob": "glob", "grep": "grep", "search_file_content": "grep", "list_directory": "ls", "ls": "ls",
             "task": "subagent", "agent": "subagent", "webfetch": "webfetch", "web_fetch": "webfetch",
             "websearch": "websearch", "web_search": "websearch", "google_web_search": "websearch",
             "todowrite": "todo", "computer": "gui", "use_computer": "gui", "mcp__village__computer_use": "gui"}
    return table.get(low, low)


def iso(ts):
    """Normalize a timestamp to ISO-8601 UTC string keeping the source's fractional digits.
    Accepts ISO strings (with Z or offset, or naive=UTC), epoch ms ints. Returns None on failure."""
    if ts is None or ts == "":
        return None
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    s = str(ts).strip().replace(" ", "T")
    if s.endswith("+00:00"):
        s = s[:-6] + "Z"
    if not s.endswith("Z") and not re.search(r"[+-]\d\d:\d\d$", s):
        s += "Z"
    return s


def parse_ts(s):
    """ISO string -> timezone-aware datetime (microsecond precision). None-safe."""
    if not s:
        return None
    s2 = s.replace("Z", "+00:00")
    m = re.match(r"(.*\.\d{1,6})\d*(\+.*|-.*)?$", s2)  # trim >6 fractional digits
    if m:
        s2 = m.group(1) + (m.group(2) or "")
    try:
        return datetime.fromisoformat(s2)
    except ValueError:
        return None


def frac_digits(s):
    m = re.search(r"\.(\d+)", s or "")
    return len(m.group(1)) if m else 0


# Claude Code text conventions for failure, applied to result text only. Order matters (first match wins).
ERROR_MARKERS = [
    ("cc_exit_code", re.compile(r"^Exit code (\d+)")),
    ("cc_tool_use_error", re.compile(r"^<tool_use_error>")),
    ("cc_permission_denied", re.compile(r"^(Permission to use \S+ (?:with command .* )?has been denied|.*requested permissions to .* but you haven't granted it)", re.S)),
    ("cc_interrupt_reject", re.compile(r"^\[Request interrupted|^The user doesn't want to proceed with this tool use|^User rejected")),
    ("whowhen_exitcode_nonzero", re.compile(r"^exitcode: (?!0\b)(\d+)")),
    # the two below are searched anywhere in the text (harness templates that are not at the start)
    ("gemini_exit_code_nonzero", re.compile(r"(?m)^Exit Code: (?!0\b)(\d+)")),
    ("magentic_exit_code_nonzero", re.compile(r"exited with Unix exit code: (?!0\b)(\d+)")),
]
SEARCH_MARKERS = {"gemini_exit_code_nonzero", "magentic_exit_code_nonzero"}


def error_marker(text):
    """Return the name of the first failure marker matched at the start of result text, else None."""
    if not text:
        return None
    for name, rx in ERROR_MARKERS:
        if (rx.search(text) if name in SEARCH_MARKERS else rx.match(text)):
            return name
    return None


def j(obj):
    """Compact JSON string, None-safe."""
    return None if obj is None else json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def to_frame(events):
    """List of IR dicts -> pandas DataFrame with exactly COLUMNS, typed."""
    import pandas as pd
    df = pd.DataFrame(events, columns=list(COLUMNS))
    for c, t in COLUMNS.items():
        if t == "int64":
            df[c] = df[c].astype("int64")
        elif t == "Int64":
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
        elif t == "boolean":
            df[c] = df[c].astype("boolean")
        else:
            df[c] = df[c].astype("string")
    return df


def validate(df):
    """Raise AssertionError on spec violations. Returns a dict of basic counts."""
    assert list(df.columns) == list(COLUMNS), f"columns differ: {list(df.columns)}"
    assert df["kind"].isin(["user", "system", "assistant", "call", "result", "meta"]).all(), df["kind"].unique()
    assert df["ts_kind"].isin(["event", "row_insert", "shared_turn", "none"]).all(), df["ts_kind"].unique()
    g = df.groupby("session_id")["seq"]
    assert (g.min() == 0).all() and (g.max() + 1 == g.size()).all(), "seq must be 0..n-1 per session"
    calls = df[df.kind == "call"]
    assert calls["call_id"].notna().all(), "every call needs a call_id"
    return {"rows": len(df), "sessions": df.session_id.nunique(), **df.kind.value_counts().to_dict()}
