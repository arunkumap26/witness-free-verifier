"""Shared classifier (copied verbatim from hf_files_census.py)."""
import re
PAT = [
    ("codex", re.compile(r"(^|/)rollout-\d{4}-\d\d-\d\dT\d\d-\d\d-\d\d-[0-9a-f-]{36}\.jsonl$")),
    ("pi", re.compile(r"(^|/)\d{4}-\d\d-\d\dT\d\d-\d\d-\d\d(-\d{3})?Z?_[0-9a-f-]{36}\.jsonl$")),
    ("claude_code_subagent", re.compile(r"(^|/)agent-[0-9a-f]{6,}\.jsonl$")),
    ("claude_code", re.compile(r"(^|/)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.jsonl$")),
    ("opencode", re.compile(r"(^|/)ses_[A-Za-z0-9]+\.json$")),
    ("cline_roo_ui", re.compile(r"(^|/)(ui_messages|api_conversation_history)\.json$")),
    ("atif", re.compile(r"(^|/)trajectory\.json$")),
    ("parquet", re.compile(r"\.parquet$")),
    ("jsonl_other", re.compile(r"\.jsonl$")),
    ("json_other", re.compile(r"\.json$")),
]

def classify(p):
    for name, rx in PAT:
        if rx.search(p):
            return name
    return "other"

