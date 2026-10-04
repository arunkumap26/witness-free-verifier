"""Synthetic attack battery for the eval: a frozen port of prereg_e.json `n7_attack_battery` on IR DataFrames.

DESIGN.md section 5.4 (plan of record). What this module is:
  * The pre-registered injectors (`atk_*` in analysis/probes/prereg_e_common.py) and every helper they and their target
    rules need, copied VERBATIM into the "frozen copies" section below. `FROZEN_COPIES` names the source of each copy;
    tests/test_eval.py asserts that each copy's source text is identical to the original, so the eval runs the
    pre-registered code without importing `analysis` at score time (DA6: the climb loop may edit `analysis/`, never
    `eval/`, so the attacks it is judged by must live here).
  * Target rules and donor rules ported from the two N7 probe halves: `analysis/probes/phase_e_n7_timing.py`
    (`UnitCtx.targets`, `inject`, `target_units`) for the timing / request-id attacks and the insertions, and the tamper
    path of `analysis/probes/phase_e_n7_content.py` (`run_job.targets`, `run_job.tamper`) for the content, accounting,
    deletion and reordering attacks. `ATTACKS[name].source` records which half each attack follows; the rng parts are
    the probes' (`rng_for(attack, param, session_id)` for the target, `rng_for('donor', attack, param, session_id)` for
    donors), shifted by the eval seed (`rng_for_seed`; seed 0 equals the pre-registered draw).
  * A plan/apply split (DESIGN.md 5.3): `plan()` resolves every random choice (target, donor text and latency, spliced
    id, inserted pair, line pair, added tokens) at pack-build time into a JSON-safe `PlanRow`; `apply()` replays it on
    the honest session frame with no rng and no donor pool, and returns the tampered frame plus a `Tamper` record.

What it is not: no new attack, no new parameter, no new eligibility rule. Imports neither `verifier` nor `analysis`.
Deviations the eval needs that the probes did not (each one is required for a valid IR frame; none changes which
event is tampered): see `EVAL_DEVIATIONS`.
"""
import hashlib
import json
import math
import re
import zlib
from bisect import bisect_left
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

ATTACKS_SHA = hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()

# ============================================================================================================ constants
# prereg_e_common.py SEED_E = stats.SEED + 2 (PREREG_E.md section 0): tamper draws, donor picks, N7 session subsamples.
SEED_E = 20261005
# prereg_e_common.py N7 grid constants (copied; tests/test_eval.py asserts equality)
GRID_D = [0.5, 1, 2, 5, 10, 30, 60, 300]
GRID_D_LATE_CHECK = [5, 30, 300]
REWRITE_K = [2, 5]
MATCHED_BYTES_TOL = 0.05
N7_CAP_SESSIONS = 500
N7_MIN_SESSIONS = 30

# prereg_e_common.ATTACK_FIELDS (copied; asserted equal to prereg_e.json n7_attack_battery.attack_fields)
ATTACK_FIELDS = {
    "time_result_early": {"ts"}, "time_result_late": {"ts", "order"}, "time_tail_late": {"ts"},
    "time_tail_early": {"ts"}, "time_response_early": {"ts"}, "time_response_late": {"ts"},
    "id_swap_adjacent": {"request_id"}, "id_splice_foreign": {"request_id"},
    "sub_single_flip_error": {"text", "error"}, "sub_single_digit": {"text"}, "sub_matched_bytes": {"text", "error"},
    "rewrite_consistent_k": {"text", "error", "ts"}, "reorder_adjacent_pairs": {"text", "args", "error", "order"},
    "reorder_lines": {"text"}, "delete_pair": {"text", "args", "events", "ts"},
    "delete_response": {"text", "args", "events", "request_id", "ts"},
    "insert_pair_consistent": {"text", "args", "events", "ts"}, "insert_pair_squeezed": {"text", "args", "events", "ts"},
    "inline_fabrication": {"usage"}, "image_relabel_gui": {"tool"}, "image_insert_screenshot": {"tool", "events"},
}
# prereg_e.json n7_attack_battery.single_call_types (copied; asserted equal)
SINGLE_CALL_TYPES = ("time_result_early", "time_result_late", "time_response_early", "id_swap_adjacent",
                     "id_splice_foreign", "sub_single_flip_error", "sub_single_digit", "sub_matched_bytes",
                     "reorder_adjacent_pairs", "reorder_lines", "delete_pair", "delete_response",
                     "insert_pair_consistent", "insert_pair_squeezed", "inline_fabrication", "image_relabel_gui",
                     "image_insert_screenshot")

_D = [f"{d:g}" for d in GRID_D]


@dataclass(frozen=True)
class AttackSpec:
    params: tuple            # parameter strings exactly as the probes passed them to rng_for (str(param))
    fields: frozenset        # prereg ATTACK_FIELDS
    cls: str                 # 'exec' (execution path, in scope) | 'edit' (record editing); DESIGN.md 5.4 class table
    source: str              # 'timing' | 'content': which N7 probe half the target + injection rule is ported from
    ported: bool             # False: listed, never planned (no target rule in this port)
    aiv_cu_only: bool = False


_EXEC = {"sub_single_flip_error", "sub_single_digit", "sub_matched_bytes", "rewrite_consistent_k", "reorder_lines",
         "inline_fabrication"}
_TIMING_HALF = {"time_result_early", "time_result_late", "time_tail_late", "time_tail_early", "time_response_early",
                "time_response_late", "id_swap_adjacent", "id_splice_foreign", "insert_pair_consistent",
                "insert_pair_squeezed"}
_PARAMS = {
    "time_result_early": _D, "time_result_late": _D, "time_tail_late": _D, "time_tail_early": _D,
    "time_response_early": _D, "time_response_late": [f"{d:g}" for d in GRID_D_LATE_CHECK],
    "id_swap_adjacent": ["-"], "id_splice_foreign": ["random", "nearest"], "sub_single_flip_error": ["-"],
    "sub_single_digit": ["-"], "sub_matched_bytes": ["any", "samecmd"],
    "rewrite_consistent_k": [str(k) for k in REWRITE_K], "reorder_adjacent_pairs": ["-"], "reorder_lines": ["-"],
    "delete_pair": ["-"], "delete_response": ["-"], "insert_pair_consistent": ["-"], "insert_pair_squeezed": ["-"],
    "inline_fabrication": ["tau"], "image_relabel_gui": ["-"], "image_insert_screenshot": ["-"],
}
ATTACKS = {a: AttackSpec(params=tuple(_PARAMS[a]), fields=frozenset(ATTACK_FIELDS[a]),
                         cls="exec" if a in _EXEC else "edit",
                         source="timing" if a in _TIMING_HALF else "content",
                         ported=a != "image_insert_screenshot",
                         aiv_cu_only=a.startswith("image_"))
           for a in ATTACK_FIELDS}

# N2 tau per calibration unit (inline_fabrication adds round(tau x chars) output tokens). Frozen copies; the lookup
# order is DESIGN.md DA19 (the unit's own split-A calibration first). tests/test_eval.py asserts each value against
# its source key. aiv_cu is keyed by stratum, GRANULAR strata only (phase_e_n7_content.Ctx.tau).
TAU = {
    "swechat/claude_code": 0.4088050314465409,
    "swechat/codex": 0.49228374464870306,
    "swechat/opencode": 0.3676106673737005,
    "cc_local": 0.7717569786535303,
    "aiv_cu/anthropic-fable": 0.7087628865979382,
    "aiv_cu/anthropic-haiku": 0.8654836464857342,
    "aiv_cu/anthropic-opus": 0.7780996214406612,
    "aiv_cu/anthropic-sonnet": 0.6726906318082788,
    "aiv_cu/gemini-flash": 0.29767441860465116,
    "aiv_cu/gemini-pro": 0.2714285714285714,
    "tbench2": 0.34443053859951844,
    "glm_tb21": 0.28948438463736237,
    "pub_cc_hf": 0.6675977653631284,
    "pub_trace_commons": 0.6029394240317776,
    "pub_codex": 0.3622926662713174,
    "agentcap/opencode": 0.2604166666666667,
    "agentcap/pi": 0.26009083043872283,
}
TAU_SOURCE = {
    **{u: f"analysis/prereg_e.json#resolved.n2.{u}.tau" for u in
       ("swechat/claude_code", "swechat/codex", "swechat/opencode", "cc_local")},
    **{f"aiv_cu/{s}": f"analysis/prereg_e.json#resolved.n2.aiv_cu.by_stratum.{s}.tau" for s in
       ("anthropic-fable", "anthropic-haiku", "anthropic-opus", "anthropic-sonnet", "gemini-flash", "gemini-pro")},
    "tbench2": "analysis/out/phase_e/prereg_e_calibration_tbench2.json#units.tbench2.n2.tau",
    "glm_tb21": "analysis/out/phase_e/prereg_e_calibration_glm_tb21.json#units.glm_tb21.n2.tau",
    "pub_cc_hf": "analysis/out/phase_e/prereg_e_calibration_pub_cc_hf.json#calibration.n2.tau",
    "pub_trace_commons": "analysis/out/phase_e/prereg_e_calibration_pub_trace_commons.json#calibration.n2.tau",
    "pub_codex": "analysis/out/phase_e/prereg_e_calibration_pub_codex.json#units.pub_codex.resolved.n2.tau",
    "agentcap/opencode": "analysis/out/phase_e/prereg_e_calibration_agentcap.json#units.agentcap/opencode.resolved.n2.tau",
    "agentcap/pi": "analysis/out/phase_e/prereg_e_calibration_agentcap.json#units.agentcap/pi.resolved.n2.tau",
}

EVAL_DEVIATIONS = [
    {"what": "every tampered frame is re-typed to the IR schema (coerce_ir) and, after a deletion, renumbered seq 0..n-1",
     "why": "verify_session takes exactly analysis/lib/ir.py COLUMNS with seq 0..n-1 (ir.validate); the probes scored "
            "raw frames"},
    {"what": "inserted donor rows get the target session's corpus, usage_cache_read/usage_cache_create null and keep "
             "the donor's ts_kind",
     "why": "the probes' frames did not carry these columns (timing COLS, content LOAD_COLS), so the inserted rows had "
            "them null; corpus/ts_kind must be valid IR values"},
    {"what": "inline_fabrication writes its footprint into the frame: usage_out += round(tau x chars) on every row of "
             "the response with a usage_out (Codex: the closing token_count row)",
     "why": "the content probe passed the addition to N2 as a side channel (usage_add, float); the verifier only sees "
            "the frame, and usage_out is Int64. max(usage_out) per response grows by exactly the rounded addition"},
    {"what": "id_splice_foreign target_call_ids are the calls of the spliced response (found by position)",
     "why": "phase_e_n7_timing.target_units looked them up by the ORIGINAL id in the tampered frame, which no longer "
            "holds it (empty set; R1 localized by stream, so the probe did not need it)"},
    {"what": "missing stamps are passed to every injector as None (object dtype)",
     "why": "as phase_e_n7_content.run_job.tamper; the frozen injectors call parse_ts(), which accepts None only. The "
            "timing half passed pd.NA, which never reaches parse_ts on its targets (both stamps of a target pair parse)"},
]

# ============================================================================================================ regexes
# Subsets of prereg_common.RX and prereg_e_common.RX_E that the frozen copies below use. Values copied verbatim;
# tests/test_eval.py asserts each one equals the pre-registered string.
RX = {
    "redaction_typed": r"\[REDACTED:[A-Za-z0-9_]+\]|\[REDACTED_[A-Za-z0-9_]+\]|\[REDACTED\]|<REDACTED>|<TRUFFLEHOG_REDACTED_[A-Za-z0-9_]*>",
    "path_line_suffix": r"(?::\d+(?::\d+)?|#L\d+(?:-L?\d+)?)$",
    "codex_exit_header": r"(?m)^Exit code: (-?\d+)",
    "codex_process_exited": r"Process exited with code (-?\d+)",
    "aiv_bash_returncode_nonzero": r"bash has exited with returncode (?!0\b)-?\d+",
    "harness_timeout": r"(?m)^(?:timed out: |sandbox error: command timed out)",
    "census_task_families": {
        "py_traceback": r"Traceback \(most recent call last\)",
        "command_not_found": r"command not found",
        "permission_denied": r"Permission denied",
        "no_such_file": r"No such file or directory",
        "exit_status_N": r"\bexit status (?!0\b)-?\d+",
        "exited_with_code_N": r"\bexited with code (?!0\b)-?\d+",
        "returned_nonzero_exit_status": r"returned non-zero exit status",
        "error_line": r"(?m)^(?:Error|error):",
        "git_fatal": r"(?m)^fatal:",
        "npm_err": r"npm ERR!",
        "http_4xx_5xx": r"(?m)^(?:< )?HTTP/\d(?:\.\d)? [45]\d\d\b|curl: \(\d+\) The requested URL returned error:? [45]\d\d\b",
    },
}
_C = {k: re.compile(v) for k, v in RX.items() if isinstance(v, str)}
_CENSUS = {k: re.compile(v) for k, v in RX["census_task_families"].items()}

RX_E = {
    "anthropic_req": r"^req_(?:vrtx_|bdrk_)?01[1-9A-HJ-NP-Za-km-z]{22}$",
    "background_result": r"(?i)^(?:Command running in background|Command was manually backgrounded|Process running with session ID)",
}
_R = {k: re.compile(v) for k, v in RX_E.items()}

# ============================================================ frozen copies (verbatim) from analysis/lib/ir.py
SHELL_TOOLS = {"bash", "shell", "run_shell_command", "exec_command", "local_shell", "terminal", "mcp__village__bash",
               "write_stdin", "shell_command"}

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


# ============================================================ frozen copies (verbatim) from analysis/probes/prereg_common.py
CC_FORMAT_UNITS = ("swechat/claude_code", "cc_local", "aiv_cc")

TOOL_CLASSES = {
    "auto_read": ["read", "glob", "grep", "ls"],
    "shell": ["shell"],
    "file_write": ["edit", "write", "notebookedit"],
    "human_interactive": ["askuserquestion", "exitplanmode", "enterplanmode", "ask_user", "enter_plan_mode",
                          "exit_plan_mode"],
    "internal_noperm": ["todo", "taskcreate", "taskupdate", "tasklist", "taskget", "toolsearch", "update_plan"],
    "subagent": ["subagent"],
}

CLASS_OF = {t: c for c, ts in TOOL_CLASSES.items() for t in ts}

CODEX_SHELL_RAW = {"shell", "shell_command", "exec_command", "write_stdin", "local_shell", "container.exec"}

PUBLIC_CC_TOOLS = {"shell", "read", "write", "edit", "glob", "grep", "ls", "todo", "subagent", "webfetch", "websearch",
                   "taskcreate", "taskupdate", "tasklist", "taskget", "taskoutput", "taskstop", "toolsearch",
                   "askuserquestion", "exitplanmode", "enterplanmode", "skill", "sendmessage", "notebookedit", "workflow",
                   "killshell", "bashoutput", "killbash", "monitor", "structuredoutput"}

PATH_KEYS = ("file_path", "filePath", "path", "absolute_path", "notebook_path", "dir_path", "relative_path",
             "target_directory", "paths", "file")

def sobj(series):
    return [x if isinstance(x, str) else None for x in series.astype(object)]


def jl(e):
    if isinstance(e, str):
        try:
            x = json.loads(e)
            return x if isinstance(x, dict) else {}
        except ValueError:
            return {}
    return {}


def tool_key(unit, tool, tool_raw):
    tr = (tool_raw or "").lower()
    if tr.startswith("mcp__"):
        return tr
    if unit == "swechat/codex" and (tr in CODEX_SHELL_RAW or tr == "apply_patch"):
        return tr
    return tool if isinstance(tool, str) else (normalize_tool(tool_raw) or "unknown")


def tool_class(key):
    return CLASS_OF.get(key, "other")


def private_key(key):
    if key in PUBLIC_CC_TOOLS:
        return key
    return "mcp__*" if str(key).startswith("mcp__") else "other_tool"


def make_pairs(df):
    """Calls joined to results on (session_id, call_id), first by seq each. Adds delta_s (float, NaN if a stamp is
    missing). Columns of the result side get suffix _r."""
    calls = df[df.kind == "call"].sort_values(["session_id", "seq"]).drop_duplicates(["session_id", "call_id"])
    res = df[(df.kind == "result") & df.call_id.notna()].sort_values(["session_id", "seq"]).drop_duplicates(
        ["session_id", "call_id"])
    keep_r = [c for c in res.columns if c not in ("kind",)]
    p = calls.merge(res[keep_r], on=["session_id", "call_id"], suffixes=("", "_r"))
    d = []
    for a, b in zip(sobj(p.ts) if "ts" in p else [], sobj(p.ts_r) if "ts_r" in p else []):
        if a and b:
            pa, pb = parse_ts(a), parse_ts(b)
            if pa is not None and pb is not None:
                td = pb - pa
                d.append((td.days * 86_400_000_000 + td.seconds * 1_000_000 + td.microseconds) / 1e6)
                continue
        d.append(np.nan)
    if "ts" in p:
        p["delta_s"] = np.array(d, dtype=float)
    return p


def _census_any(s):
    return bool(s) and any(rx.search(s) for rx in _CENSUS.values())


def error_classes(unit, tool_key_, tool_raw, text, stderr, native, exit_code, stratum=None):
    """Returns (primary: bool|None, cls: str). primary None = unit has no error definition for this result."""
    text = text if isinstance(text, str) else ""
    stderr = stderr if isinstance(stderr, str) else ""
    nat = None if native is None or (isinstance(native, float) and math.isnan(native)) or native is pd.NA else bool(native)
    if unit in CC_FORMAT_UNITS:
        m = error_marker(text)
        if nat is True:
            if m in ("cc_permission_denied", "cc_interrupt_reject"):
                return False, m
            return True, m or "unmarked"
        if unit == "aiv_cc" and (tool_raw or "").lower() == "mcp__village__bash":
            try:
                x = json.loads(text)
            except ValueError:
                x = None
            if isinstance(x, dict):
                err = x.get("error") or ""
                if isinstance(err, str) and (_C["aiv_bash_returncode_nonzero"].search(err) or _C["harness_timeout"].search(err)
                                             or _census_any(err)):
                    return False, "village_bash_proxy"
        return False, "ok"
    if unit == "swechat/codex":
        if nat is True:
            return True, "native"
        if nat is None and (tool_key_ in CODEX_SHELL_RAW):
            head = text[:600]
            for rx in (_C["codex_exit_header"], _C["codex_process_exited"]):
                m = rx.search(head)
                if m and int(m.group(1)) != 0:
                    return True, "exit_header"
        return False, "ok"
    if unit == "swechat/opencode":
        return (nat is True), ("native" if nat is True else "ok")
    if unit == "swechat/gemini":
        tf = nat is True
        cf = error_marker(text) == "gemini_exit_code_nonzero"
        cls = "tool_failure+command_failure" if (tf and cf) else "tool_failure" if tf else "command_failure" if cf else "ok"
        return (tf or cf), cls
    if unit == "swechat/copilot":
        return (nat is True), ("native" if nat is True else "ok")
    if unit == "aiv_cu":
        hit = bool(_C["aiv_bash_returncode_nonzero"].search(stderr) or _C["harness_timeout"].search(stderr)
                   or _census_any(stderr))
        return hit, ("proxy" if hit else "ok")
    if unit == "whowhen":
        if stratum == "Algorithm-Generated" and tool_key_ == "code_exec":
            if exit_code is not None and not (isinstance(exit_code, float) and math.isnan(exit_code)) and exit_code is not pd.NA:
                return int(exit_code) != 0, ("exit_nonzero" if int(exit_code) != 0 else "ok")
            return False, "no_exit_code"
        return None, "no_signal"
    return None, "no_definition"


def mask_redaction(s):
    if not s or "REDACTED" not in s:
        return s
    s = _C["redaction_typed"].sub("<R>", s)
    return s.replace("REDACTED", "<R>")


_TRAIL = ".,;:)]}>'\"`"

def normalize_path(p):
    if not p:
        return None
    p = p.strip().strip("'\"`")
    while p and p[-1] in _TRAIL:
        p = p[:-1]
    p = _C["path_line_suffix"].sub("", p)
    p = mask_redaction(p).replace("\\", "/")
    p = re.sub(r"/{2,}", "/", p)
    while p.startswith("./"):
        p = p[2:]
    p = p.rstrip("/")
    if re.match(r"^[A-Za-z]:/", p):
        p = p.lower()
    return p or None


def shell_command(unit, tool_key_, args_obj, command):
    if isinstance(command, str) and command:
        return command
    if isinstance(args_obj, dict):
        for k in ("command", "cmd"):
            v = args_obj.get(k)
            if isinstance(v, str):
                return v
            if isinstance(v, list):
                return " ".join(str(x) for x in v)
    return None


# ============================================================ frozen copies (verbatim) from analysis/probes/prereg_e_common.py
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

_B58I = {c: i for i, c in enumerate(_B58)}

_WIN = (int(pd.Timestamp("2024-01-01", tz="UTC").value // 1_000_000), int(pd.Timestamp("2027-01-01", tz="UTC").value // 1_000_000))

def decode_req_ms(s):
    """Anthropic request id -> embedded ms (top 48 bits of the base58 body after '01'), or None."""
    if not isinstance(s, str) or not _R["anthropic_req"].match(s):
        return None
    body = s.rsplit("_", 1)[1][2:]
    v = 0
    for ch in body:
        v = v * 58 + _B58I[ch]
    top = v >> 80
    return float(top) if _WIN[0] <= top < _WIN[1] else None


def _ms(ts_series):
    t = pd.to_datetime(ts_series, utc=True, format="ISO8601", errors="coerce")
    return ((t - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds() * 1000.0).astype(float).to_numpy()


def _stream(is_sub, agent):
    return [(a if isinstance(a, str) and a else "?") if bool(b) else "main"
            for b, a in zip(pd.Series(is_sub).astype("boolean").fillna(False), pd.Series(agent).astype(object))]


def qualify_pairs(unit, u, P, classes=("shell", "auto_read")):
    """Phase B no-human-wait filter with rule 2 replaced by `classes`; adds key, cls, marker, qualified, background.
    P = pc.make_pairs(u[kind in (call, result)])."""
    P = P.copy()
    P["key"] = [pc.tool_key(unit, t, tr) for t, tr in zip(P.tool.astype(object), P.tool_raw.astype(object))]
    if unit == "cc_local":
        P["key"] = [pc.private_key(k) for k in P.key]
    P["cls"] = [("shell" if (k == "shell" or (k in pc.CODEX_SHELL_RAW and k != "write_stdin") or k.endswith("__bash"))
                 else pc.tool_class(k)) for k in P.key]
    txt = pc.sobj(P.text_r)
    P["marker"] = [error_marker(t) for t in txt]
    rx = [pc.jl(e) for e in P.extra_r.astype(object)]
    ok = np.isfinite(P.delta_s.to_numpy()) & (P.delta_s.to_numpy() > 0)
    cls_ok = P.cls.isin(list(classes)).to_numpy() & ~P.key.isin(["write_stdin"]).to_numpy()
    if unit in pc.CC_FORMAT_UNITS or unit == "swechat/gemini":
        calls = u[u.kind == "call"].sort_values(["session_id", "seq"]).drop_duplicates(["session_id", "call_id"])
        cm = [a if isinstance(a, str) else f"__solo__{c}" for a, c in zip(calls.api_msg_id.astype(object),
                                                                         calls.call_id.astype(str))]
        calls = calls.assign(_msg=cm)
        last = ~calls.duplicated(["session_id", "_msg"], keep="last")
        nin = calls.groupby(["session_id", "_msg"]).call_id.transform("size")
        lk = dict(zip(zip(calls.session_id, calls.call_id.astype(str)), last))
        nk = dict(zip(zip(calls.session_id, calls.call_id.astype(str)), nin))
        keys = list(zip(P.session_id, P.call_id.astype(str)))
        msg_ok = (np.array([nk.get(k, 1) == 1 for k in keys]) if unit == "swechat/gemini"
                  else np.array([bool(lk.get(k, True)) for k in keys]))
        P["last_in_msg"] = np.array([bool(lk.get(k, True)) for k in keys])
    else:
        msg_ok = np.ones(len(P), dtype=bool)
        P["last_in_msg"] = True
    mk_ok = ~P.marker.isin(["cc_permission_denied", "cc_interrupt_reject"]).to_numpy()
    if unit == "swechat/codex":
        mk_ok &= np.array([x.get("exec_status") != "declined" and not x.get("unified_exec_running") for x in rx])
    if unit == "swechat/gemini":
        mk_ok &= np.array([x.get("status") != "cancelled" for x in rx])
    hook_ok = np.ones(len(P), dtype=bool)
    if unit == "swechat/claude_code":
        m = u[(u.kind == "meta") & u.parent_call_id.notna()]
        hooked = {(s, str(p)) for s, p, e in zip(m.session_id, m.parent_call_id.astype(object), m.extra.astype(object))
                  if pc.jl(e).get("type") == "hook_progress"}
        hook_ok = np.array([k not in hooked for k in zip(P.session_id, P.call_id.astype(str))])
    elif unit == "cc_local":
        a = u[u.extra.notna() & u.kind.isin(["system", "meta", "user"])]
        hooked = set()
        for s, e in zip(a.session_id, a.extra.astype(object)):
            x = pc.jl(e)
            at = x.get("attachment_type")
            if at and str(at).startswith("hook") and x.get("toolUseID"):
                hooked.add((s, str(x["toolUseID"])))
        hook_ok = np.array([k not in hooked for k in zip(P.session_id, P.call_id.astype(str))])
    pol_ok = np.ones(len(P), dtype=bool)
    if unit == "swechat/codex":
        m = u[(u.kind == "meta") & u.extra.notna()]
        pol = defaultdict(list)
        for s, q, e in zip(m.session_id, m.seq, m.extra.astype(object)):
            x = pc.jl(e)
            if "approval_policy" in x:
                pol[s].append((int(q), x.get("approval_policy")))
        for s in pol:
            pol[s].sort()
        res = []
        for s, q in zip(P.session_id, P.seq):
            lst = pol.get(s, [])
            i = bisect_left([a for a, _ in lst], int(q)) - 1
            res.append(i >= 0 and lst[i][1] == "never")
        pol_ok = np.array(res)
    bg = []
    for a, t, x in zip(P.args.astype(object), txt, rx):
        o = pc.jl(a) if isinstance(a, str) else {}
        bg.append(bool(o.get("run_in_background")) or "backgroundTaskId" in x
                  or bool(t and _R["background_result"].search(t)))
    P["background"] = np.array(bg, dtype=bool)
    P["qualified"] = ok & cls_ok & msg_ok & mk_ok & hook_ok & pol_ok & ~P.background.to_numpy()
    P["result_bytes"] = [len(t.encode("utf-8")) if t else 0 for t in txt]
    P["result_chars"] = [len(t) if t else 0 for t in txt]
    return P


_CD_PREFIX = re.compile(r"^\s*cd\s+(?:\"[^\"]*\"|'[^']*'|\S+)\s*(?:&&|;)\s*")

_TRAIL_REDIR = re.compile(r"\s*2>&1\s*$")

N1_VOLATILE_ARG_KEYS = ("description", "timeout", "timeout_ms", "yield_time_ms", "max_output_tokens", "justification",
                        "sandbox_permissions", "with_escalated_permissions")

def normalize_command(cmd):
    if not isinstance(cmd, str):
        return None
    c = cmd.strip()
    prev = None
    while prev != c:
        prev = c
        c = _CD_PREFIX.sub("", c)
    c = _TRAIL_REDIR.sub("", c)
    c = re.sub(r"\s+", " ", c).strip()
    return c or None


def n1_key(unit, key, args_json, command):
    o = pc.jl(args_json) if isinstance(args_json, str) else {}
    shellish = key == "shell" or key in pc.CODEX_SHELL_RAW or str(key).endswith("__bash")
    if shellish:
        c = normalize_command(pc.shell_command(unit, key, o, command))
        if c is None:
            return None
        wd = o.get("workdir")
        return f"{key}|{c}|{wd}" if isinstance(wd, str) else f"{key}|{c}"
    if key == "read":
        p = None
        for k in pc.PATH_KEYS:
            if isinstance(o.get(k), str):
                p = pc.normalize_path(o[k])
                break
        return f"read|{p}|{o.get('offset')}|{o.get('limit')}" if p else None
    oo = {k: v for k, v in o.items() if k not in N1_VOLATILE_ARG_KEYS}
    return f"{key}|" + json.dumps(oo, sort_keys=True, ensure_ascii=False)


def response_table(unit, u):
    """One row per API response (CC formats, opencode, gemini, aiv_cu: api_msg_id; codex: token_count close).
    Columns: session_id, resp, usage_in, usage_out, chars_out (text + args + thinking), last_call_id, n_calls."""
    rows = []
    if unit == "swechat/codex":
        for sid, g in u.sort_values(["session_id", "seq"]).groupby("session_id", sort=False):
            pend, chars, last = 0, 0, None
            for kind, txt, a, uo, ui, cid, ex in zip(g.kind, g.text.astype(object), g.args.astype(object), g.usage_out,
                                                    g.usage_in, g.call_id.astype(object), g.extra.astype(object)):
                if kind == "call":
                    pend += 1
                    chars += len(a) if isinstance(a, str) else 0
                    last = cid
                elif kind == "assistant" and isinstance(txt, str):
                    chars += len(txt)
                elif kind == "meta" and not pd.isna(uo):
                    if pend:
                        rows.append({"session_id": sid, "resp": f"tc{len(rows)}", "usage_in": ui, "usage_out": uo,
                                     "chars_out": chars, "last_call_id": last, "n_calls": pend})
                    pend, chars, last = 0, 0, None
        return pd.DataFrame(rows)
    r = u[u.api_msg_id.notna()]
    for (sid, a), g in r.groupby(["session_id", "api_msg_id"], sort=False):
        calls = g[g.kind == "call"]
        if not len(calls):
            continue
        uo = g.usage_out.dropna()
        ui = g.usage_in.dropna()
        ch = sum(len(t) for t in g[g.kind == "assistant"].text.astype(object) if isinstance(t, str))
        ch += sum(len(t) for t in calls.args.astype(object) if isinstance(t, str))
        for e in g.extra.astype(object):
            if isinstance(e, str) and "thinking_chars" in e:
                v = pc.jl(e).get("thinking_chars")
                if isinstance(v, (int, float)):
                    ch += int(v)
        rows.append({"session_id": sid, "resp": str(a), "usage_in": float(ui.max()) if len(ui) else np.nan,
                     "usage_out": float(uo.max()) if len(uo) else np.nan, "chars_out": ch,
                     "last_call_id": calls.sort_values("seq").call_id.iloc[-1], "n_calls": int(len(calls))})
    return pd.DataFrame(rows)


def pick_donor(pool, target_bytes, rng, exclude_session=None, tol=MATCHED_BYTES_TOL):
    """pool: DataFrame with session_id, text, bytes (same unit, split and tool_key). Nearest byte length from another
    session, ties broken by rng. Returns (row index, relative byte difference) or (None, None)."""
    cand = pool[pool.session_id != exclude_session]
    if not len(cand) or target_bytes <= 0:
        return None, None
    diff = (cand.bytes - target_bytes).abs()
    best = diff.min()
    idx = cand.index[diff == best].to_numpy()
    i = idx[int(rng.integers(0, len(idx)))]
    rel = float(best / target_bytes)
    return (i, rel) if rel <= tol else (None, rel)


def _shift_ts(ts, seconds):
    t = parse_ts(ts) if isinstance(ts, str) else None
    if t is None:
        return ts
    t2 = t + pd.Timedelta(seconds=seconds).to_pytimedelta()
    return t2.astimezone(t.tzinfo).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def atk_time(s, target_idx, D, mode):
    """s: one session's IR rows (copy is returned). target_idx: index label of the target event (a result, or a
    response's first event). mode in result_early|result_late|tail_late|tail_early|response_early|response_late."""
    s = s.copy()
    sign = -1 if mode.endswith("early") else 1
    if mode.startswith("tail"):
        q = s.at[target_idx, "seq"]
        idx = s.index[s.seq >= q]
        s.loc[idx, "ts"] = [_shift_ts(t, sign * D) for t in s.loc[idx, "ts"]]
        return s, {"clamped": False}
    clamped = False
    new = _shift_ts(s.at[target_idx, "ts"], sign * D)
    if mode == "result_early":
        cid = s.at[target_idx, "call_id"]
        c = s[(s.kind == "call") & (s.call_id == cid)]
        if len(c):
            ct = parse_ts(c.ts.iloc[0])
            nt = parse_ts(new)
            if ct is not None and nt is not None and nt <= ct:
                new = _shift_ts(c.ts.iloc[0], 0.001)
                clamped = True
    s.at[target_idx, "ts"] = new
    return s, {"clamped": clamped}


def atk_id_swap(s, idx_a, idx_b):
    """Swap the request ids of two responses (all events carrying each id)."""
    s = s.copy()
    a, b = s.at[idx_a, "request_id"], s.at[idx_b, "request_id"]
    ma, mb = s.request_id == a, s.request_id == b
    s.loc[ma, "request_id"] = b
    s.loc[mb, "request_id"] = a
    return s


def atk_id_splice(s, idx, donor_id):
    s = s.copy()
    a = s.at[idx, "request_id"]
    s.loc[s.request_id == a, "request_id"] = donor_id
    return s


def atk_substitute(s, result_idx, donor_text, donor_error=None):
    s = s.copy()
    s.at[result_idx, "text"] = donor_text
    if donor_error is not None:
        s.at[result_idx, "native_error"] = donor_error
    if "stderr" in s.columns:
        s.at[result_idx, "stderr"] = None
    return s


def atk_digit(s, result_idx):
    s = s.copy()
    t = s.at[result_idx, "text"]
    if not isinstance(t, str):
        return s, False
    ms = list(re.finditer(r"\d+", t))
    if not ms:
        return s, False
    m = ms[-1]
    d = int(t[m.end() - 1])
    s.at[result_idx, "text"] = t[:m.end() - 1] + str((d + 1) % 10) + t[m.end():]
    return s, True


def atk_rewrite_consistent(s, result_idxs, donor_texts, donor_latencies):
    """Replace k results; set each pair's latency to its donor latency; shift later events to keep order."""
    s = s.copy()
    for ri, txt, lat in zip(result_idxs, donor_texts, donor_latencies):
        cid = s.at[ri, "call_id"]
        c = s[(s.kind == "call") & (s.call_id == cid)]
        if not len(c):
            continue
        ct, rt = parse_ts(c.ts.iloc[0]), parse_ts(s.at[ri, "ts"])
        if ct is None or rt is None:
            continue
        shift = (ct + pd.Timedelta(seconds=lat).to_pytimedelta() - rt).total_seconds()
        q = s.at[ri, "seq"]
        idx = s.index[s.seq >= q]
        s.loc[idx, "ts"] = [_shift_ts(t, shift) for t in s.loc[idx, "ts"]]
        s.at[ri, "text"] = txt
    return s


def atk_reorder_pairs(s, call_a, call_b):
    """Exchange contents of two call/result pairs (by call index labels); stamps, ids, seq stay."""
    s = s.copy()
    cols_c = [c for c in ("tool", "tool_raw", "args", "command") if c in s.columns]
    cols_r = [c for c in ("text", "stderr", "native_error", "exit_code", "extra") if c in s.columns]
    ra = s.index[(s.kind == "result") & (s.call_id == s.at[call_a, "call_id"])]
    rb = s.index[(s.kind == "result") & (s.call_id == s.at[call_b, "call_id"])]
    va, vb = s.loc[call_a, cols_c].copy(), s.loc[call_b, cols_c].copy()
    s.loc[call_a, cols_c], s.loc[call_b, cols_c] = vb.values, va.values
    if len(ra) and len(rb):
        xa, xb = s.loc[ra[0], cols_r].copy(), s.loc[rb[0], cols_r].copy()
        s.loc[ra[0], cols_r], s.loc[rb[0], cols_r] = xb.values, xa.values
    return s


def atk_reorder_lines(s, result_idx, rng):
    s = s.copy()
    t = s.at[result_idx, "text"]
    lines = t.split("\n") if isinstance(t, str) else []
    cand = [i for i in range(len(lines) - 1) if lines[i] != lines[i + 1]]
    if len(lines) < 3 or not cand:
        return s, False
    i = cand[int(rng.integers(0, len(cand)))]
    lines[i], lines[i + 1] = lines[i + 1], lines[i]
    s.at[result_idx, "text"] = "\n".join(lines)
    return s, True


def atk_delete_pair(s, call_idx):
    cid = s.at[call_idx, "call_id"]
    drop = (s.call_id == cid) | (s.parent_call_id == cid)
    s = s[~drop.fillna(False).to_numpy()].copy()
    return s


def atk_delete_response(s, any_idx):
    rid = s.at[any_idx, "request_id"]
    s = s[~(s.request_id == rid).fillna(False).to_numpy()].copy()
    return s


def atk_insert_pair(s, after_idx, donor_call, donor_result, mode="consistent", donor_gap_s=None, donor_lat_s=None):
    """Insert donor call/result rows (pd.Series, from another session) after event after_idx. Seq is renumbered by
    +0.25/+0.5 then re-ranked. mode consistent: later events shifted by gap + latency; squeezed: placed inside the gap."""
    s = s.copy()
    q = s.at[after_idx, "seq"]
    t0 = parse_ts(s.at[after_idx, "ts"])
    nxt = s[s.seq > q].sort_values("seq")
    c, r = donor_call.copy(), donor_result.copy()
    new_cid = f"inserted:{c.get('call_id')}"
    c["call_id"], r["call_id"] = new_cid, new_cid
    c["session_id"] = r["session_id"] = s.session_id.iloc[0]
    if mode == "consistent":
        gap = donor_gap_s if donor_gap_s is not None else 1.0
        lat = donor_lat_s if donor_lat_s is not None else 0.1
        c["ts"] = _shift_ts(s.at[after_idx, "ts"], gap)
        r["ts"] = _shift_ts(s.at[after_idx, "ts"], gap + lat)
        idx = s.index[s.seq > q]
        s.loc[idx, "ts"] = [_shift_ts(t, gap + lat) for t in s.loc[idx, "ts"]]
    else:
        if not len(nxt) or t0 is None:
            return None
        t1 = parse_ts(nxt.ts.iloc[0])
        if t1 is None or (t1 - t0).total_seconds() < 0.002:
            return None
        g = (t1 - t0).total_seconds()
        c["ts"] = _shift_ts(s.at[after_idx, "ts"], 0.25 * g)
        r["ts"] = _shift_ts(s.at[after_idx, "ts"], 0.75 * g)
    c["seq"], r["seq"] = q + 0.25, q + 0.5
    for x in (c, r):
        for col in ("request_id", "api_msg_id", "uuid", "parent_uuid", "usage_in", "usage_out"):
            if col in x.index:
                x[col] = None
    s = pd.concat([s, pd.DataFrame([c, r])], ignore_index=False)
    s = s.sort_values("seq")
    s["seq"] = np.arange(len(s))
    return s.reset_index(drop=True)


def atk_inline_fabrication(resp_row, result_chars, tau):
    """Return the output-token addition for one response (N2 attack footprint)."""
    return float(tau * result_chars)


def atk_image_relabel(s, call_idx):
    s = s.copy()
    s.at[call_idx, "tool"] = "shell"
    s.at[call_idx, "tool_raw"] = "bash"
    return s


# ============================================================ frozen copies (verbatim) from analysis/probes/phase_e_n7_timing.py
def thread_of(is_sub, agent):
    sub = bool(is_sub) if (is_sub is not None and not (isinstance(is_sub, float) and math.isnan(is_sub))
                          and is_sub is not pd.NA) else False
    return (sub, agent if isinstance(agent, str) else "")


def stream_of(is_sub, agent):
    return pe._stream([is_sub], [agent])[0]


def is_true(x):
    """True for a primary-error value that is True (python or numpy bool); False for False/None/NaN/NA."""
    if x is None or x is pd.NA or (isinstance(x, float) and math.isnan(x)):
        return False
    return bool(x)


def is_false(x):
    if x is None or x is pd.NA or (isinstance(x, float) and math.isnan(x)):
        return False
    return not bool(x)


# ============================================================ frozen copies (verbatim) from analysis/probes/phase_e_n7_content.py
def thread_key(is_sub, agent):
    b = False if (is_sub is None or is_sub is pd.NA or (isinstance(is_sub, float) and math.isnan(is_sub))) else bool(is_sub)
    return (b, (agent if isinstance(agent, str) else "") if b else "")


def native_val(x):
    if x is None or x is pd.NA or (isinstance(x, float) and math.isnan(x)):
        return pd.NA
    return bool(x)


def key_of(unit, tool, tool_raw):
    k = pc.tool_key(unit, tool if isinstance(tool, str) else None, tool_raw if isinstance(tool_raw, str) else None)
    return pc.private_key(k) if unit == "cc_local" else k


def enrich_pairs(unit, P):
    """key, n1, err (primary), bytes/chars of the result text."""
    if not len(P):
        for c in ("key", "n1", "err", "bytes", "chars"):
            P[c] = pd.Series(dtype=object)
        return P
    keys = [key_of(unit, t, tr) for t, tr in zip(P.tool.astype(object), P.tool_raw.astype(object))]
    raw_keys = [pc.tool_key(unit, t if isinstance(t, str) else None, tr if isinstance(tr, str) else None)
                for t, tr in zip(P.tool.astype(object), P.tool_raw.astype(object))]
    txt = pc.sobj(P.text_r)
    P = P.assign(key=keys)
    P["n1"] = [pe.n1_key(unit, k, a, c) for k, a, c in zip(keys, P.args.astype(object), P.command.astype(object))]
    err = []
    for k, tr, t, e, n, x, st in zip(raw_keys, P.tool_raw.astype(object), txt, P.stderr_r.astype(object),
                                     P.native_error_r.astype(object), P.exit_code_r.astype(object),
                                     P.stratum.astype(object)):
        r = pc.error_classes(unit, k, tr if isinstance(tr, str) else None, t, e if isinstance(e, str) else None,
                             None if n is pd.NA else n, None if x is pd.NA else x, st if isinstance(st, str) else None)
        err.append(bool(r[0]) if r[0] is not None else False)
    P["err"] = err
    P["bytes"] = [len(t.encode("utf-8")) if t else 0 for t in txt]
    P["chars"] = [len(t) if t else 0 for t in txt]
    return P


class DonorIndex:
    """Matched-bytes donor lookups over the unit x split pairs (pool = other REAL results, same tool_key)."""

    def __init__(self, Pall, mask, group_cols):
        self.group_cols = group_cols
        pool = Pall[mask & (Pall.bytes.to_numpy() > 0)]
        self.pool = pool
        self.arr, self.own, self.rows = {}, {}, {}
        for k, g in pool.groupby(group_cols, sort=False):
            k = k if isinstance(k, tuple) else (k,)
            o = np.argsort(g.bytes.to_numpy(), kind="stable")
            self.arr[k] = g.bytes.to_numpy()[o]
            self.rows[k] = g.iloc[o]
            for s, gs in g.groupby("session_id", sort=False):
                self.own[k + (s,)] = np.sort(gs.bytes.to_numpy())

    def exists(self, k, sid, b):
        if b <= 0 or k not in self.arr:
            return False
        tol = b // 20
        a = self.arr[k]
        n = np.searchsorted(a, b + tol, "right") - np.searchsorted(a, b - tol, "left")
        o = self.own.get(k + (sid,))
        if o is not None:
            n -= np.searchsorted(o, b + tol, "right") - np.searchsorted(o, b - tol, "left")
        return n > 0

    def pick(self, k, sid, b, rng):
        a = self.arr[k]
        tol = b // 20
        lo, hi = np.searchsorted(a, b - tol, "left"), np.searchsorted(a, b + tol, "right")
        sub = self.rows[k].iloc[lo:hi]
        return pe.pick_donor(sub, b, rng, exclude_session=sid)


# ============================================================================================================ namespaces
# The copies above call each other through the module aliases they had at their source (`pc.tool_key`,
# `pe._stream`, ...). These namespaces bind those aliases to the copies, so the copied text runs unmodified.
pc = SimpleNamespace(
    RX=RX, CC_FORMAT_UNITS=CC_FORMAT_UNITS, TOOL_CLASSES=TOOL_CLASSES, CLASS_OF=CLASS_OF,
    CODEX_SHELL_RAW=CODEX_SHELL_RAW, PUBLIC_CC_TOOLS=PUBLIC_CC_TOOLS, PATH_KEYS=PATH_KEYS,
    sobj=sobj, jl=jl, tool_key=tool_key, tool_class=tool_class, private_key=private_key, make_pairs=make_pairs,
    error_classes=error_classes, mask_redaction=mask_redaction, normalize_path=normalize_path,
    shell_command=shell_command)
pe = SimpleNamespace(
    RX_E=RX_E, _R=_R, MATCHED_BYTES_TOL=MATCHED_BYTES_TOL, decode_req_ms=decode_req_ms, _ms=_ms, _stream=_stream,
    qualify_pairs=qualify_pairs, normalize_command=normalize_command, n1_key=n1_key, response_table=response_table,
    pick_donor=pick_donor, _shift_ts=_shift_ts, atk_time=atk_time, atk_id_swap=atk_id_swap,
    atk_id_splice=atk_id_splice, atk_substitute=atk_substitute, atk_digit=atk_digit,
    atk_rewrite_consistent=atk_rewrite_consistent, atk_reorder_pairs=atk_reorder_pairs,
    atk_reorder_lines=atk_reorder_lines, atk_delete_pair=atk_delete_pair, atk_delete_response=atk_delete_response,
    atk_insert_pair=atk_insert_pair, atk_inline_fabrication=atk_inline_fabrication,
    atk_image_relabel=atk_image_relabel)

# Every verbatim copy and its source (tests/test_eval.py: source text identical, constants equal).
_IR, _PC, _PE = "analysis/lib/ir.py", "analysis/probes/prereg_common.py", "analysis/probes/prereg_e_common.py"
_N7T, _N7C = "analysis/probes/phase_e_n7_timing.py", "analysis/probes/phase_e_n7_content.py"
FROZEN_COPIES = {
    **{n: _IR for n in ("SHELL_TOOLS", "normalize_tool", "parse_ts", "ERROR_MARKERS", "SEARCH_MARKERS",
                        "error_marker")},
    **{n: _PC for n in ("CC_FORMAT_UNITS", "TOOL_CLASSES", "CLASS_OF", "CODEX_SHELL_RAW", "PUBLIC_CC_TOOLS",
                        "PATH_KEYS", "sobj", "jl", "tool_key", "tool_class", "private_key", "make_pairs",
                        "_census_any", "error_classes", "mask_redaction", "_TRAIL", "normalize_path",
                        "shell_command")},
    **{n: _PE for n in ("_B58", "_B58I", "_WIN", "decode_req_ms", "_ms", "_stream", "qualify_pairs", "_CD_PREFIX",
                        "_TRAIL_REDIR", "N1_VOLATILE_ARG_KEYS", "normalize_command", "n1_key", "response_table",
                        "pick_donor", "_shift_ts", "atk_time", "atk_id_swap", "atk_id_splice", "atk_substitute",
                        "atk_digit", "atk_rewrite_consistent", "atk_reorder_pairs", "atk_reorder_lines",
                        "atk_delete_pair", "atk_delete_response", "atk_insert_pair", "atk_inline_fabrication",
                        "atk_image_relabel")},
    **{n: _N7T for n in ("thread_of", "stream_of", "is_true", "is_false")},
    **{n: _N7C for n in ("thread_key", "native_val", "key_of", "enrich_pairs", "DonorIndex")},
}

# analysis/lib/ir.py COLUMNS (names and dtype tags; asserted equal)
IR_COLUMNS = {
    "corpus": "str", "session_id": "str", "stratum": "str", "seq": "int64", "kind": "str", "ts": "str",
    "ts_kind": "str", "tool": "str", "tool_raw": "str", "call_id": "str", "args": "str", "command": "str",
    "text": "str", "stderr": "str", "native_error": "boolean", "exit_code": "Int64", "usage_in": "Int64",
    "usage_out": "Int64", "usage_cache_read": "Int64", "usage_cache_create": "Int64", "api_msg_id": "str",
    "request_id": "str", "model": "str", "is_subagent": "boolean", "parent_call_id": "str", "agent_id": "str",
    "uuid": "str", "parent_uuid": "str", "extra": "str",
}


# ============================================================================================================ types
@dataclass(frozen=True)
class Tamper:
    """One tampered copy (DESIGN.md 5.4). Seqs and call ids refer to the TAMPERED frame."""
    attack: str
    param: str
    seed: int
    session_id: str
    tampered_seqs: tuple = ()
    target_call_ids: tuple = ()
    target_streams: tuple = ()
    donor_session_id: str | None = None
    byte_delta: int | None = None
    clamped: bool = False


@dataclass(frozen=True)
class PlanRow:
    """Every random choice of one tamper, resolved at pack-build time (DESIGN.md 5.3). JSON-safe."""
    seed: int
    attack: str
    param: str
    unit: str
    session_id: str
    target: object                       # seq, [seq, seq], [seq, ...] or [resp, call_id], in the HONEST frame
    payload: dict = field(default_factory=dict)   # donors, draws, added tokens; {'fail': reason} when unresolvable

    def to_record(self) -> dict:
        return {"seed": int(self.seed), "attack": self.attack, "param": self.param, "unit": self.unit,
                "session_id": self.session_id, "target_json": json.dumps(self.target),
                "payload_json": json.dumps(self.payload, sort_keys=True, ensure_ascii=False)}

    @classmethod
    def from_record(cls, r: dict) -> "PlanRow":
        return cls(seed=int(r["seed"]), attack=str(r["attack"]), param=str(r["param"]), unit=str(r["unit"]),
                   session_id=str(r["session_id"]), target=json.loads(r["target_json"]),
                   payload=json.loads(r["payload_json"]))


class InjectFailed(Exception):
    """The plan row cannot produce a tampered copy (counted per cell as an injection failure, never hidden)."""


try:  # DESIGN.md 3.4: LabeledCall lives in eval/labeled.py (not built yet); identical fallback until it lands
    from labeled import LabeledCall  # type: ignore
except ImportError:  # pragma: no cover - exercised until eval/labeled.py exists
    @dataclass(frozen=True)
    class LabeledCall:
        set: str
        corpus: str
        session_id: str
        call_id: str | None
        seq: int | None
        label: str
        cls: str | None
        provenance: str
        label_version: str
        ir_sha: str | None = None
        tampered_seqs: tuple = ()


# ============================================================================================================ rng
def rng_for_seed(s, *parts):
    """DESIGN.md 5.3: default_rng(SEED_E + s + crc32('|'.join(parts))). s = 0 equals prereg_e_common.rng_for(*parts)."""
    return np.random.default_rng(SEED_E + int(s) + zlib.crc32("|".join(str(p) for p in parts).encode("utf-8")))


class _RecordingRng:
    """Wraps a Generator and records every integers() draw (plan time), so apply() can replay them without an rng."""

    def __init__(self, rng):
        self.rng, self.draws = rng, []

    def integers(self, lo, hi=None):
        v = self.rng.integers(lo, hi)
        self.draws.append(int(v))
        return v


class _ReplayRng:
    def __init__(self, draws):
        self.draws = list(draws)

    def integers(self, lo, hi=None):
        return self.draws.pop(0)


# ============================================================================================================ frames
def coerce_ir(df: pd.DataFrame, renumber: bool = True) -> pd.DataFrame:
    """Re-type a (tampered) frame to the IR schema: COLUMNS order and dtypes (as ir.to_frame), sorted by seq, index
    reset; renumber=True rewrites seq to 0..n-1 (after a deletion). A 'unit' column is kept last when present."""
    out = df.copy()
    for c in IR_COLUMNS:
        if c not in out.columns:
            out[c] = None
    out = out.sort_values("seq", kind="mergesort").reset_index(drop=True)
    if renumber:
        out["seq"] = np.arange(len(out), dtype="int64")
    for c, t in IR_COLUMNS.items():
        if str(out[c].dtype) == _DTYPE_NAME[t] and (t != "str" or out[c].dtype.na_value is pd.NA):
            continue                       # already the IR dtype (untouched by the injector)
        if t == "int64":
            out[c] = out[c].astype("int64")
        elif t == "Int64":
            out[c] = pd.to_numeric(pd.Series([None if _isna(x) else x for x in out[c].astype(object)],
                                             index=out.index, dtype=object), errors="coerce").astype("Int64")
        elif t == "boolean":
            out[c] = pd.Series([None if _isna(x) else bool(x) for x in out[c].astype(object)], index=out.index,
                               dtype=object).astype("boolean")
        else:
            out[c] = pd.Series([None if _isna(x) else str(x) for x in out[c].astype(object)], index=out.index,
                               dtype=object).astype("string")
    cols = list(IR_COLUMNS) + (["unit"] if "unit" in out.columns else [])
    return out[cols]


_DTYPE_NAME = {"int64": "int64", "Int64": "Int64", "boolean": "boolean", "str": "string"}


def _isna(x):
    return x is None or x is pd.NA or (isinstance(x, float) and math.isnan(x)) or x is pd.NaT


def _view(frame: pd.DataFrame) -> pd.DataFrame:
    """One session's rows sorted by seq with index == seq; missing stamps as None (EVAL_DEVIATIONS 5)."""
    f = frame.sort_values("seq", kind="mergesort").reset_index(drop=True)
    if not (f.seq.to_numpy() == np.arange(len(f))).all():
        raise ValueError("session frame must have seq 0..n-1")
    if f.session_id.nunique() != 1:
        raise ValueError("one session per frame")
    f["ts"] = pd.Series([x if isinstance(x, str) else None for x in f.ts.astype(object)], index=f.index, dtype=object)
    return f


def _jsonable(v):
    if _isna(v):
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return None if not np.isfinite(v) else float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def _row_dict(row: pd.Series) -> dict:
    return {c: _jsonable(row[c]) for c in IR_COLUMNS if c in row.index}


def _na_or_bool(v):
    """native_val() result (pd.NA or bool) as JSON: None means pd.NA."""
    return None if v is pd.NA else bool(v)


def _from_na_or_bool(v):
    return pd.NA if v is None else bool(v)


def tau_for(unit: str, stratum) -> float | None:
    """phase_e_n7_content.Ctx.tau with DESIGN.md DA19's lookup order; None = the unit has no granular N2 tau."""
    if unit == "aiv_cu":
        return TAU.get(f"aiv_cu/{stratum}") if isinstance(stratum, str) else None
    return TAU.get(unit)


# ============================================================================================================ pools
def build_donor_index(Pall: pd.DataFrame, mask, group_cols) -> "DonorIndex":
    """A DonorIndex (the frozen class: exists() and pick() run verbatim) whose tables are built with numpy instead of
    its constructor's nested groupby (minutes on a full swechat unit). The tables are the same: `arr[k]` = the group's
    bytes sorted ascending (stable), `rows[k]` = the group's pool rows in that order (session_id, bytes; Pall labels),
    `own[k + (sid,)]` = that session's sorted bytes. Rows with a null group key are dropped, as groupby(dropna=True)
    does. tests/test_eval.py asserts equality with DonorIndex.__init__ on real pairs."""
    di = DonorIndex.__new__(DonorIndex)
    di.group_cols = group_cols
    keep = np.asarray(mask, dtype=bool) & (Pall.bytes.to_numpy() > 0)
    pool = pd.DataFrame({"session_id": pd.Series(Pall.session_id.astype(str).to_numpy(dtype=object)[keep],
                                                 dtype=object, index=Pall.index[keep]),
                         "bytes": pd.Series(Pall.bytes.to_numpy(dtype=np.int64)[keep], index=Pall.index[keep])})
    di.pool = pool
    di.arr, di.own, di.rows = {}, {}, {}
    if not len(pool):
        return di
    cols = [Pall[c].to_numpy(dtype=object)[keep] for c in group_cols]
    keys = list(zip(*cols))
    ok = np.array([not any(_isna(x) for x in k) for k in keys], dtype=bool)
    gmap, smap = {}, {}
    gcode = np.array([gmap.setdefault(k, len(gmap)) if o else -1 for k, o in zip(keys, ok)], dtype=np.int64)
    sids = pool.session_id.to_numpy(dtype=object)
    scode = np.array([smap.setdefault(s, len(smap)) for s in sids], dtype=np.int64)
    b = pool.bytes.to_numpy(dtype=np.int64)
    pos = np.arange(len(pool))
    glist = list(gmap)
    slist = list(smap)
    o1 = np.lexsort((pos, b, gcode))
    o1 = o1[gcode[o1] >= 0]
    cut = np.flatnonzero(np.r_[True, gcode[o1][1:] != gcode[o1][:-1], True])
    for a, z in zip(cut[:-1], cut[1:]):
        idx = o1[a:z]
        k = glist[gcode[idx[0]]]
        di.arr[k] = b[idx]
        di.rows[k] = pool.iloc[idx]
    o2 = np.lexsort((b, scode, gcode))
    o2 = o2[gcode[o2] >= 0]
    g2, s2 = gcode[o2], scode[o2]
    cut2 = np.flatnonzero(np.r_[True, (g2[1:] != g2[:-1]) | (s2[1:] != s2[:-1]), True])
    for a, z in zip(cut2[:-1], cut2[1:]):
        i0 = o2[a]
        di.own[glist[gcode[i0]] + (slist[scode[i0]],)] = b[o2[a:z]]
    return di


class UnitPools:
    """The DonorSource of DESIGN.md 5.4: the probes' unit-wide tables, built from EVERY session of one unit x split
    ('donors only from other real results of the same unit and split'). `frame`: all IR rows of the unit x split."""

    def __init__(self, unit: str, frame: pd.DataFrame):
        cols = [c for c in IR_COLUMNS if c in frame.columns]
        u = frame[cols].sort_values(["session_id", "seq"], kind="stable").reset_index(drop=True)
        u["session_id"] = u["session_id"].astype(str)
        self.unit, self.u = unit, u
        self.sids = sorted(set(u.session_id))
        self._content = None
        self._timing = None

    # ---- content half: phase_e_n7_content.run_job ("unit-level pairs and donor indexes")
    def content(self):
        if self._content is None:
            u = self.u
            Pall = enrich_pairs(self.unit, pc.make_pairs(u.assign(_ix=u.index)))
            Pall = Pall.reset_index(drop=True)
            if len(Pall):
                Pall["thread"] = [thread_key(a, b) for a, b in zip(Pall.is_subagent.astype(object),
                                                                   Pall.agent_id.astype(object))]
                Pall["delta_ok"] = (np.isfinite(Pall.delta_s.to_numpy(dtype=float))
                                    & (Pall.delta_s.to_numpy(dtype=float) >= 0))
                keep = ["session_id", "call_id", "seq", "seq_r", "tool", "key", "n1", "err", "bytes", "chars",
                        "delta_s", "_ix", "_ix_r", "is_subagent", "agent_id", "thread", "delta_ok"]
                Pall = Pall[keep]
                ns = SimpleNamespace(
                    Pall=Pall,
                    any=build_donor_index(Pall, np.ones(len(Pall), bool), ["key"]),
                    ok=build_donor_index(Pall, ~Pall.err.to_numpy(dtype=bool), ["key"]),
                    cmd=build_donor_index(Pall, Pall.n1.notna().to_numpy(), ["key", "n1"]),
                    rw=build_donor_index(Pall, Pall.delta_ok.to_numpy(), ["key"]))
            else:
                ns = SimpleNamespace(Pall=Pall, any=None, ok=None, cmd=None, rw=None)
            ns.by_session = {s: g for s, g in Pall.groupby("session_id", sort=False)} if len(Pall) else {}
            self._content = ns
        return self._content

    # ---- timing half: phase_e_n7_timing.UnitCtx (resp_pool, resp_sessions, insert_donors)
    def timing(self):
        if self._timing is None:
            u = self.u
            R = u[u.request_id.notna()].sort_values(["session_id", "seq"], kind="stable").drop_duplicates(
                ["session_id", "request_id"])
            emb = [pe.decode_req_ms(x) for x in R.request_id.astype(object)]
            resp_pool = pd.DataFrame({"session_id": R.session_id.astype(str).to_numpy(),
                                      "request_id": R.request_id.astype(str).to_numpy(),
                                      "emb": np.array([np.nan if e is None else e for e in emb], dtype=float)})
            resp_sessions = set(resp_pool.session_id[np.isfinite(resp_pool.emb.to_numpy())]) if len(resp_pool) \
                else set()
            # insert donors: session_info pairs over every session, main thread, not nested, latency > 0, call gap >= 0
            ms = pe._ms(u.ts)
            prev_ms = (pd.Series(ms).groupby(u.session_id.to_numpy(), sort=False).shift(1)
                       .groupby(u.session_id.to_numpy(), sort=False).ffill().to_numpy(dtype=float))
            cr = u[u.kind.isin(["call", "result"])]
            P = pc.make_pairs(cr.assign(_ix=cr.index))
            if len(P):
                main = np.array([not thread_of(a, b)[0] for a, b in zip(P.is_subagent.astype(object),
                                                                        P.agent_id.astype(object))], dtype=bool)
                ci = P["_ix"].to_numpy(dtype=int)
                call_gap = (ms[ci] - prev_ms[ci]) / 1000.0
                d = P.delta_s.to_numpy(dtype=float)
                m = (main & ~P.parent_call_id.notna().to_numpy() & np.isfinite(d) & (np.nan_to_num(d, nan=-1) > 0)
                     & np.isfinite(call_gap) & (np.nan_to_num(call_gap, nan=-1) >= 0))
                ins = pd.DataFrame({"session_id": P.session_id.astype(str).to_numpy(), "seq": P.seq.to_numpy(),
                                    "ci": ci, "ri": P["_ix_r"].to_numpy(dtype=int), "delta_s": d,
                                    "call_gap_s": call_gap, "call_id": P.call_id.astype(str).to_numpy()})[m]
                ins = ins.sort_values(["session_id", "seq"]).reset_index(drop=True)
            else:
                ins = pd.DataFrame(columns=["session_id", "seq", "ci", "ri", "delta_s", "call_gap_s", "call_id"])
            self._timing = SimpleNamespace(resp_pool=resp_pool, resp_sessions=resp_sessions, ins=ins)
        return self._timing

    def insert_donors(self, exclude=None):
        d = self.timing().ins
        return d[d.session_id != exclude] if exclude is not None and len(d) else d


# ============================================================================================================ targets
def timing_tables(unit: str, s: pd.DataFrame) -> dict:
    """phase_e_n7_timing.session_info, ported to a session view whose index is seq. The error class, n1 key and text
    columns are not computed (no timing-half target this port runs reads them)."""
    calls = s[s.kind == "call"].sort_values("seq").drop_duplicates("call_id")
    resr = s[(s.kind == "result") & s.call_id.notna()].sort_values("seq").drop_duplicates("call_id")
    cidx = dict(zip(calls.call_id.astype(str), calls.index))
    ridx = dict(zip(resr.call_id.astype(str), resr.index))
    P = pc.make_pairs(s[s.kind.isin(["call", "result"])])
    info = {"pairs": None, "responses": None}
    if len(P):
        Q = pe.qualify_pairs(unit, s, P)
        cid = Q.call_id.astype(str).to_numpy()
        thr = [thread_of(a, b) for a, b in zip(Q.is_subagent.astype(object), Q.agent_id.astype(object))]
        ms = pe._ms(s.ts)
        pos = {ix: i for i, ix in enumerate(s.index)}
        prev_ms = np.full(len(s), np.nan)
        last = np.nan
        for i in range(len(s)):
            prev_ms[i] = last
            if np.isfinite(ms[i]):
                last = ms[i]
        next_ms = np.r_[ms[1:], np.nan]
        ci = np.array([cidx.get(c, -1) for c in cid])
        ri = np.array([ridx.get(c, -1) for c in cid])
        rows = pd.DataFrame({
            "cid": cid, "ci": ci, "ri": ri, "key": Q.key.to_numpy(), "seq": Q.seq.to_numpy(),
            "seq_r": Q.seq_r.to_numpy(), "delta_s": Q.delta_s.to_numpy(dtype=float),
            "qualified": Q.qualified.to_numpy(), "main": [not t[0] for t in thr],
            "res_ms": [ms[pos[x]] if x in pos else np.nan for x in ri],
            "next_gap_s": [(next_ms[pos[x]] - ms[pos[x]]) / 1000.0 if x in pos else np.nan for x in ri],
            "has_next": [pos[x] + 1 < len(s) if x in pos else False for x in ri],
        })
        rows = rows[(rows.ci >= 0) & (rows.ri >= 0)].sort_values("seq").reset_index(drop=True)
        info["pairs"] = rows
    rid = s[s.request_id.notna()].sort_values("seq").drop_duplicates("request_id")
    if len(rid):
        emb = [pe.decode_req_ms(x) for x in rid.request_id.astype(object)]
        info["responses"] = pd.DataFrame({
            "idx": rid.index.to_numpy(), "seq": rid.seq.to_numpy(), "request_id": rid.request_id.astype(str).to_numpy(),
            "emb": np.array([np.nan if e is None else e for e in emb], dtype=float),
            "stream": pe._stream(rid.is_subagent, rid.agent_id)})
    return info


class _Ctx:
    """Per-session lazily computed tables shared by targets() and plan()."""

    def __init__(self, unit, f, pools):
        self.unit, self.f, self.pools = unit, f, pools
        self.sid = str(f.session_id.iloc[0])
        self._tt = None
        self._ps = None
        self._has = {}

    def tt(self):
        if self._tt is None:
            self._tt = timing_tables(self.unit, self.f)
        return self._tt

    def Ps(self):
        if self._ps is None:
            self._ps = self.pools.content().by_session.get(self.sid)
        return self._ps

    def has(self, name):
        """phase_e_n7_content Pall['has_any' | 'has_ok' | 'has_cmd' | 'has_rw'] for this session's pairs."""
        if name not in self._has:
            Ps, C = self.Ps(), self.pools.content()
            if Ps is None:
                self._has[name] = np.zeros(0, dtype=bool)
            elif name == "cmd":
                self._has[name] = np.array([n is not None and C.cmd.exists((k, n), s, b)
                                            for k, n, s, b in zip(Ps.key, Ps.n1, Ps.session_id, Ps.bytes)], dtype=bool)
            else:
                ix = getattr(C, name)
                self._has[name] = np.array([ix.exists((k,), s, b) for k, s, b in zip(Ps.key, Ps.session_id, Ps.bytes)],
                                           dtype=bool)
        return self._has[name]


_DIGIT = re.compile(r"\d")


def _targets(attack: str, param: str, c: _Ctx) -> list:
    if not ATTACKS[attack].ported:
        return []
    f, sid = c.f, c.sid
    if ATTACKS[attack].source == "timing":
        # phase_e_n7_timing.UnitCtx.targets
        inf = c.tt()
        P, R = inf["pairs"], inf["responses"]
        t = []
        if attack == "time_result_early":
            if P is not None:
                t = [int(x) for x in P.ri[P.qualified.to_numpy()]]
        elif attack in ("time_result_late", "time_tail_late", "time_tail_early"):
            if P is not None:
                t = [int(x) for x in P.ri[np.isfinite(P.delta_s.to_numpy())]]
        elif attack in ("time_response_early", "time_response_late"):
            if R is not None:
                t = [int(x) for x in R.idx]
        elif attack == "id_swap_adjacent":
            if R is not None:
                d = R[np.isfinite(R.emb.to_numpy())].sort_values("seq")
                for _, g in d.groupby("stream", sort=True):
                    ix = g.idx.tolist()
                    t += [(int(ix[i]), int(ix[i + 1])) for i in range(len(ix) - 1)]
        elif attack == "id_splice_foreign":
            if R is not None and (c.pools.timing().resp_sessions - {sid}):
                t = [int(x) for x in R.idx[np.isfinite(R.emb.to_numpy())]]
        elif attack in ("insert_pair_consistent", "insert_pair_squeezed"):
            if P is not None and len(c.pools.insert_donors(exclude=sid)):
                m = P.main.to_numpy() & np.isfinite(P.res_ms.to_numpy())
                if attack == "insert_pair_squeezed":
                    m &= P.has_next.to_numpy() & (np.nan_to_num(P.next_gap_s.to_numpy(), nan=-1) >= 0.002)
                t = [int(x) for x in P.ri[m]]
        return t
    # phase_e_n7_content.run_job.targets (candidates are Pall labels or session-view labels == seq)
    Ps = c.Ps()
    if attack == "sub_single_flip_error":
        return [] if Ps is None else list(Ps.index[Ps.err.to_numpy(dtype=bool) & c.has("ok")])
    if attack == "sub_matched_bytes":
        return [] if Ps is None else list(Ps.index[c.has("any" if param == "any" else "cmd")])
    if attack == "sub_single_digit":
        r = f[f.kind == "result"]
        return [int(ix) for ix, t in zip(r.index, r.text.astype(object)) if isinstance(t, str) and _DIGIT.search(t)]
    if attack == "reorder_lines":
        r = f[f.kind == "result"]
        out = []
        for ix, t in zip(r.index, r.text.astype(object)):
            if isinstance(t, str):
                ls = t.split("\n")
                if len(ls) >= 3 and any(ls[i] != ls[i + 1] for i in range(len(ls) - 1)):
                    out.append(int(ix))
        return out
    if attack == "rewrite_consistent_k":
        if Ps is None:
            return []
        k = int(param)
        out = []
        P2 = Ps.assign(_ok=c.has("rw"))
        for _, g in P2.sort_values("seq").groupby("thread", sort=False):
            ok = g._ok.to_numpy()
            ixs = list(g.index)
            for i in range(len(g) - k + 1):
                if ok[i:i + k].all():
                    out.append(tuple(ixs[i:i + k]))
        return out
    if attack == "reorder_adjacent_pairs":
        if Ps is None:
            return []
        # chash = (tool, args, result text) of the pair; the probe compared hash() values, this compares the tuples
        txt = {int(q): x for q, x in zip(f.seq, f.text.astype(object))}
        arg = {int(q): x for q, x in zip(f.seq, f.args.astype(object))}
        ch = {ix: (tl if isinstance(tl, str) else None, arg.get(int(q)) if isinstance(arg.get(int(q)), str) else None,
                   txt.get(int(qr)) if isinstance(txt.get(int(qr)), str) else None)
              for ix, tl, q, qr in zip(Ps.index, Ps.tool.astype(object), Ps.seq, Ps.seq_r)}
        out = []
        for _, g in Ps.sort_values("seq").groupby("thread", sort=False):
            rows = [(ix, ch[ix]) for ix in g.index]
            for a, b in zip(rows, rows[1:]):
                if a[1] != b[1]:
                    out.append((a[0], b[0]))
        return out
    if attack == "delete_pair":
        return [] if Ps is None else list(Ps.index)
    if attack == "delete_response":
        seen, out = set(), []
        for ix, r in zip(f.index, f.request_id.astype(object)):
            if isinstance(r, str) and r not in seen:
                seen.add(r)
                out.append(int(ix))
        return out
    if attack == "inline_fabrication":
        tau = tau_for(c.unit, _stratum(f))
        if tau is None or Ps is None:
            return []
        R = pe.response_table(c.unit, f)
        if not len(R):
            return []
        rc = dict(zip(Ps.call_id.astype(str), Ps.chars))
        return [(str(r), str(cc)) for r, cc in zip(R.resp.astype(str), R.last_call_id.astype(str)) if rc.get(cc, 0) >= 1]
    if attack == "image_relabel_gui":
        cc = f[(f.kind == "call") & (f.tool.astype(object) == "gui")]
        return [int(x) for x in cc.index]
    return []


def targets(attack: str, param, frame: pd.DataFrame, donors: UnitPools | None = None, unit: str | None = None) -> list:
    """Candidate targets of `attack` in one session, in the probe's order (eligible iff non-empty). `donors` is the
    session's UnitPools (needed by every rule that consults another session); `unit` defaults to donors.unit."""
    unit = unit or (donors.unit if donors is not None else None) or str(frame["unit"].iloc[0])
    return _targets(attack, str(param), _Ctx(unit, _view(frame), donors))


# ============================================================================================================ plan
def plan(attack: str, param, seed: int, unit: str, frame: pd.DataFrame, split_frames: UnitPools) -> PlanRow | None:
    """Resolve one tamper of one session (build time). None = the session has no eligible target. A PlanRow whose
    payload holds 'fail' is an injection failure the probe would also have counted (no donor in tolerance, ...)."""
    return _plan(attack, str(param), seed, unit, _Ctx(unit, _view(frame), split_frames))


def session_context(unit: str, frame: pd.DataFrame, pools: UnitPools) -> "_Ctx":
    """Per-session tables for targets()/plan() reused across cells (the pack builder plans 16 cells per session)."""
    return _Ctx(unit, _view(frame), pools)


def targets_ctx(attack: str, param, c: "_Ctx") -> list:
    return _targets(attack, str(param), c)


def plan_ctx(attack: str, param, seed: int, c: "_Ctx") -> PlanRow | None:
    return _plan(attack, str(param), seed, c.unit, c)


def _plan(attack, param, seed, unit, c):
    split_frames = c.pools
    cands = _targets(attack, param, c)
    if not cands:
        return None
    sid, f = c.sid, c.f
    rng = rng_for_seed(seed, attack, param, sid)
    t = cands[int(rng.integers(0, len(cands)))]
    drng = rng_for_seed(seed, "donor", attack, param, sid)
    pay = {}
    row = lambda tgt, p: PlanRow(seed=int(seed), attack=attack, param=param, unit=unit, session_id=sid,  # noqa: E731
                                 target=tgt, payload=p)
    if attack.startswith("time_"):
        return row(int(t), {"D": float(param)})
    if attack == "id_swap_adjacent":
        return row([int(t[0]), int(t[1])], {})
    if attack == "id_splice_foreign":
        rp = split_frames.timing().resp_pool
        own = set(f.request_id.dropna().astype(str))
        cand = rp[(rp.session_id != sid) & np.isfinite(rp.emb.to_numpy()) & ~rp.request_id.isin(list(own)).to_numpy()]
        if not len(cand):
            return row(int(t), {"fail": "no_donor_id"})
        if param == "random":
            j = int(drng.integers(0, len(cand)))
        else:
            te = pe.decode_req_ms(f.at[t, "request_id"])
            diff = (cand.emb.to_numpy() - te).__abs__()
            best = np.flatnonzero(diff == diff.min())
            j = int(best[int(drng.integers(0, len(best)))])
            pay["nearest_abs_ms"] = float(diff.min())
        pay.update(donor_id=str(cand.request_id.iloc[j]), donor_session_id=str(cand.session_id.iloc[j]))
        return row(int(t), pay)
    C = split_frames.content() if ATTACKS[attack].source == "content" else None
    u = split_frames.u
    if attack in ("sub_single_flip_error", "sub_matched_bytes"):
        r = C.Pall.loc[t]
        if attack == "sub_single_flip_error":
            i, rel = C.ok.pick((r.key,), sid, int(r.bytes), drng)
        elif param == "any":
            i, rel = C.any.pick((r.key,), sid, int(r.bytes), drng)
        else:
            i, rel = C.cmd.pick((r.key, r.n1), sid, int(r.bytes), drng)
        if i is None:
            return row(int(r.seq_r), {"fail": "no_donor", "call_id": str(r.call_id)})
        d = C.Pall.loc[i]
        de = False if attack == "sub_single_flip_error" else _na_or_bool(native_val(u.at[int(d._ix_r), "native_error"]))
        text = u.at[int(d._ix_r), "text"]
        return row(int(r.seq_r), {"call_id": str(r.call_id), "donor_text": text if isinstance(text, str) else None,
                                  "donor_error": de, "donor_session_id": str(d.session_id), "rel": rel,
                                  "byte_delta": int(d.bytes) - int(r.bytes)})
    if attack == "sub_single_digit":
        return row(int(t), {"call_id": _s(f.at[t, "call_id"])})
    if attack == "reorder_lines":
        rec = _RecordingRng(rng)
        _, ok = pe.atk_reorder_lines(f, t, rec)
        return row(int(t), {"draws": rec.draws, "call_id": _s(f.at[t, "call_id"])} if ok else {"fail": "inject_failed"})
    if attack == "rewrite_consistent_k":
        rows = [C.Pall.loc[i] for i in t]
        texts, lats, natives, rels, dss, bd = [], [], [], [], [], 0
        for r in rows:
            i, rl = C.rw.pick((r.key,), sid, int(r.bytes), drng)
            if i is None:
                return row([int(x.seq_r) for x in rows], {"fail": "no_donor"})
            d = C.Pall.loc[i]
            tx = u.at[int(d._ix_r), "text"]
            texts.append(tx if isinstance(tx, str) else None)
            lats.append(float(d.delta_s))
            natives.append(_na_or_bool(native_val(u.at[int(d._ix_r), "native_error"])))
            rels.append(rl)
            dss.append(str(d.session_id))
            bd += int(d.bytes) - int(r.bytes)
        return row([int(x.seq_r) for x in rows], {"call_ids": [str(x.call_id) for x in rows], "texts": texts,
                                                  "lats": lats, "natives": natives, "rels": rels,
                                                  "donor_session_ids": dss, "byte_delta": bd})
    if attack == "reorder_adjacent_pairs":
        ra, rb = C.Pall.loc[t[0]], C.Pall.loc[t[1]]
        return row([int(ra.seq), int(rb.seq)], {"call_ids": [str(ra.call_id), str(rb.call_id)]})
    if attack == "delete_pair":
        r = C.Pall.loc[t]
        return row(int(r.seq), {"call_id": str(r.call_id)})
    if attack == "delete_response":
        return row(int(t), {})
    if attack in ("insert_pair_consistent", "insert_pair_squeezed"):
        don = split_frames.insert_donors(exclude=sid)
        if not len(don):
            return row(int(t), {"fail": "no_donor_pair"})
        j = int(drng.integers(0, len(don)))
        d = don.iloc[j]
        return row(int(t), {"donor_call": _row_dict(u.loc[int(d.ci)]), "donor_result": _row_dict(u.loc[int(d.ri)]),
                            "gap": float(d.call_gap_s), "lat": float(d.delta_s), "donor_session_id": str(d.session_id),
                            "mode": "consistent" if attack == "insert_pair_consistent" else "squeezed"})
    if attack == "inline_fabrication":
        resp, cid = t
        Ps = c.Ps()
        ch = int(Ps[Ps.call_id.astype(str) == cid].chars.iloc[0])
        tau = tau_for(unit, _stratum(f))
        add = pe.atk_inline_fabrication(None, ch, tau)
        seqs = _response_usage_seqs(unit, f, resp)
        if not seqs:
            return row([resp, cid], {"fail": "no_usage_row"})
        return row([resp, cid], {"chars": ch, "tau": tau, "add_float": add, "add_tokens": int(round(add)),
                                 "usage_seqs": seqs, "tau_source": TAU_SOURCE.get(
                                     f"aiv_cu/{_stratum(f)}" if unit == "aiv_cu" else unit)})
    if attack == "image_relabel_gui":
        return row(int(t), {"call_id": _s(f.at[t, "call_id"])})
    return None


def _s(x):
    return x if isinstance(x, str) else None


def _stratum(f):
    """The session's stratum as phase_e_n7_content reads it (groupby(session_id).stratum.first(): first non-null)."""
    s = f.stratum.dropna()
    return str(s.iloc[0]) if len(s) else None


def _response_usage_seqs(unit, f, resp):
    """Rows whose usage_out carries the response's output tokens (pe.response_table's response key `resp`)."""
    if unit == "swechat/codex":
        # the same walk as response_table's codex branch: the k-th emitted row closes on a token_count meta row
        k = int(resp[2:]) if resp.startswith("tc") else -1
        n, pend = 0, 0
        for q, kind, uo in zip(f.seq, f.kind, f.usage_out):
            if kind == "call":
                pend += 1
            elif kind == "meta" and not pd.isna(uo):
                if pend:
                    if n == k:
                        return [int(q)]
                    n += 1
                pend = 0
        return []
    m = (f.api_msg_id.astype(object) == resp).to_numpy() & f.usage_out.notna().to_numpy()
    return [int(q) for q in f.seq[m]]


# ============================================================================================================ apply
def apply(row: PlanRow, frame: pd.DataFrame) -> tuple[pd.DataFrame, Tamper]:
    """Replay one PlanRow on the honest session frame. Deterministic, no rng, no donor pool. Returns the tampered frame
    (IR schema, seq 0..n-1) and its Tamper; raises InjectFailed when the plan cannot produce a tampered copy."""
    if "fail" in row.payload:
        raise InjectFailed(row.payload["fail"])
    a, p, t, pay = row.attack, row.param, row.target, row.payload
    f = _view(frame)
    if str(f.session_id.iloc[0]) != row.session_id:
        raise ValueError("plan row and frame are different sessions")
    st = lambda ix: pe._stream([f.at[ix, "is_subagent"]], [f.at[ix, "agent_id"]])[0]  # noqa: E731
    base = dict(attack=a, param=p, seed=row.seed, session_id=row.session_id)
    clamped, donor, bdelta = False, pay.get("donor_session_id"), pay.get("byte_delta")
    renumber = False
    if a.startswith("time_"):
        mode = a[len("time_"):]
        s2, info = pe.atk_time(f, t, float(pay["D"]), mode)
        clamped = bool(info.get("clamped"))
        if mode.startswith("response"):
            rid = f.at[t, "request_id"]
            calls = _calls_where(f, (f.request_id.astype(object) == rid).to_numpy())
        else:
            calls = (_s(f.at[t, "call_id"]),)
        seqs, streams = (t,), (st(t),)
    elif a == "id_swap_adjacent":
        ia, ib = t
        s2 = pe.atk_id_swap(f, ia, ib)
        rids = [f.at[ia, "request_id"], f.at[ib, "request_id"]]
        calls = _calls_where(f, f.request_id.astype(object).isin(rids).to_numpy())
        seqs, streams = (ia, ib), tuple(sorted({st(ia), st(ib)}))
    elif a == "id_splice_foreign":
        rid = f.at[t, "request_id"]
        s2 = pe.atk_id_splice(f, t, pay["donor_id"])
        calls = _calls_where(f, (f.request_id.astype(object) == rid).to_numpy())
        seqs, streams = (t,), (st(t),)
    elif a in ("sub_single_flip_error", "sub_matched_bytes"):
        s2 = pe.atk_substitute(f, t, pay["donor_text"], donor_error=_from_na_or_bool(pay["donor_error"]))
        calls, seqs, streams = (pay["call_id"],), (t,), (st(t),)
    elif a == "sub_single_digit":
        s2, ok = pe.atk_digit(f, t)
        if not ok:
            raise InjectFailed("inject_failed")
        calls, seqs, streams = (_s(f.at[t, "call_id"]),), (t,), (st(t),)
    elif a == "reorder_lines":
        s2, ok = pe.atk_reorder_lines(f, t, _ReplayRng(pay["draws"]))
        if not ok:
            raise InjectFailed("inject_failed")
        calls, seqs, streams = (_s(f.at[t, "call_id"]),), (t,), (st(t),)
    elif a == "rewrite_consistent_k":
        ridx = [int(x) for x in t]
        s2 = pe.atk_rewrite_consistent(f, ridx, pay["texts"], pay["lats"])
        if sum(1 for ri, tx in zip(ridx, pay["texts"]) if s2.at[ri, "text"] == tx) < len(ridx):
            raise InjectFailed("inject_failed")
        for ri, nv in zip(ridx, pay["natives"]):           # phase_e_n7_content DEVIATIONS: rewrite error fields
            s2.at[ri, "native_error"] = _from_na_or_bool(nv)
            s2.at[ri, "stderr"] = None
        calls, seqs = tuple(pay["call_ids"]), tuple(ridx)
        streams = tuple(sorted({st(ri) for ri in ridx}))
        donor = pay["donor_session_ids"][0] if pay.get("donor_session_ids") else None
    elif a == "reorder_adjacent_pairs":
        ca, cb = int(t[0]), int(t[1])
        s2 = pe.atk_reorder_pairs(f, ca, cb)
        calls = tuple(pay["call_ids"])
        res = [_first_result(f, cid) for cid in calls]
        seqs = tuple(sorted({ca, cb} | {x for x in res if x is not None}))
        streams = tuple(sorted({st(ca), st(cb)}))
    elif a in ("delete_pair", "delete_response"):
        s2 = pe.atk_delete_pair(f, t) if a == "delete_pair" else pe.atk_delete_response(f, t)
        removed = sorted(set(int(x) for x in f.seq) - set(int(x) for x in s2.seq))
        calls, seqs = _deletion_neighbors(f, removed)
        streams = ()
        renumber = True
    elif a in ("insert_pair_consistent", "insert_pair_squeezed"):
        dc, dr = _donor_series(pay["donor_call"], f), _donor_series(pay["donor_result"], f)
        s2 = pe.atk_insert_pair(f, t, dc, dr, mode=pay["mode"], donor_gap_s=pay["gap"], donor_lat_s=pay["lat"])
        if s2 is None:
            raise InjectFailed("gap_below_2ms_or_unparseable")
        new_cid = f"inserted:{pay['donor_call'].get('call_id')}"
        calls = (new_cid,)
        seqs = tuple(int(x) for x in s2.seq[(s2.call_id.astype(object) == new_cid).to_numpy()])
        streams = ("main",)
    elif a == "inline_fabrication":
        s2 = f.copy()
        add = int(pay["add_tokens"])
        for q in pay["usage_seqs"]:
            s2.at[q, "usage_out"] = s2.at[q, "usage_out"] + add
        cid = t[1]
        calls, seqs = (cid,), tuple(int(q) for q in pay["usage_seqs"])
        cs = f.index[(f.kind == "call").to_numpy() & (f.call_id.astype(object) == cid).to_numpy()]
        streams = (st(cs[0]),) if len(cs) else ()
    elif a == "image_relabel_gui":
        s2 = pe.atk_image_relabel(f, t)
        calls, seqs, streams = (_s(f.at[t, "call_id"]),), (t,), (st(t),)
    else:
        raise InjectFailed("attack_not_ported")
    out = coerce_ir(s2, renumber=renumber)
    tam = Tamper(**base, tampered_seqs=tuple(int(x) for x in seqs), target_call_ids=tuple(c for c in calls if c),
                 target_streams=tuple(streams), donor_session_id=donor,
                 byte_delta=None if bdelta is None else int(bdelta), clamped=clamped)
    return out, tam


def _calls_where(f, mask) -> tuple:
    m = np.asarray(mask, dtype=bool) & (f.kind == "call").to_numpy()
    return tuple(str(x) for x in f.call_id[m] if isinstance(x, str))


def _first_result(f, cid):
    r = f.index[(f.kind == "result").to_numpy() & (f.call_id.astype(object) == cid).to_numpy()]
    return int(r[0]) if len(r) else None


def _deletion_neighbors(f, removed):
    """DESIGN.md 5.4: the nearest surviving call before and after the removed span in the same thread (<= 2), as
    (call_ids, seqs in the tampered frame after renumbering)."""
    if not removed:
        return (), ()
    first = removed[0]
    thr = thread_key(f.at[first, "is_subagent"], f.at[first, "agent_id"])
    rem = set(removed)
    surv = [int(q) for q in f.seq if int(q) not in rem]
    calls = f[(f.kind == "call").to_numpy()]
    same = [int(q) for q, a, b in zip(calls.seq, calls.is_subagent.astype(object), calls.agent_id.astype(object))
            if int(q) not in rem and thread_key(a, b) == thr]
    before = [q for q in same if q < first]
    after = [q for q in same if q > first]
    picks = ([before[-1]] if before else []) + ([after[0]] if after else [])
    new_seq = {q: i for i, q in enumerate(surv)}
    return tuple(str(f.at[q, "call_id"]) for q in picks), tuple(new_seq[q] for q in picks)


def _donor_series(d: dict, f) -> pd.Series:
    """A donor row (plan payload) as the injector expects it (pd.Series over the frame's columns); EVAL_DEVIATIONS 2."""
    s = pd.Series({c: d.get(c) for c in f.columns}, dtype=object)
    for c in ("corpus", "unit"):
        if c in f.columns:
            s[c] = f[c].iloc[0]
    for c in ("usage_cache_read", "usage_cache_create"):
        if c in f.columns:
            s[c] = None
    return s


# ============================================================================================================ labels
def to_labels(t: Tamper, tampered_frame: pd.DataFrame, corpus: str | None = None) -> list:
    """DESIGN.md 3.4: one positive LabeledCall per target call of a tampered copy."""
    import metrics  # eval-local module; imported here so attacks stays importable on its own
    corpus = corpus or str(tampered_frame.corpus.iloc[0])
    sha = metrics.session_ir_sha(tampered_frame)
    seq_of = {str(c): int(q) for c, q, k in zip(tampered_frame.call_id.astype(object), tampered_frame.seq,
                                                tampered_frame.kind) if k == "call" and isinstance(c, str)}
    name = f"attack:{t.attack}:{t.param}:seed{t.seed}"
    return [LabeledCall(set=name, corpus=corpus, session_id=t.session_id, call_id=c, seq=seq_of.get(c), label="pos",
                        cls=t.attack, provenance=f"eval/attacks.py@{ATTACKS_SHA[:12]}:{t.attack}:{t.param}:seed{t.seed}",
                        label_version=f"attacks@{ATTACKS_SHA[:12]}", ir_sha=sha, tampered_seqs=t.tampered_seqs)
            for c in t.target_call_ids]


def honest_labels(frame: pd.DataFrame, set_name: str) -> list:
    """The untampered copy: label 'neg' on every call, cls 'presumed_honest' (a convention, not ground truth)."""
    import metrics
    sha = metrics.session_ir_sha(frame)
    calls = frame[frame.kind == "call"]
    return [LabeledCall(set=set_name, corpus=str(frame.corpus.iloc[0]), session_id=str(frame.session_id.iloc[0]),
                        call_id=str(c), seq=int(q), label="neg", cls="presumed_honest",
                        provenance=f"eval/attacks.py@{ATTACKS_SHA[:12]}:honest", label_version=f"attacks@{ATTACKS_SHA[:12]}",
                        ir_sha=sha) for c, q in zip(calls.call_id.astype(object), calls.seq)]


def labeled_call_dict(lc) -> dict:
    d = asdict(lc)
    d["class"] = d.pop("cls")
    d["tampered_seqs"] = list(d.get("tampered_seqs") or ())
    return d
