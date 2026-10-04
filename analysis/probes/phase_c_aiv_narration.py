"""Phase C lens: aiv_narration -- the agent's own narration of a computer-use session vs that session's tool log.

Bridge case for witness-free verification: AI Village agents write free-text narration about their sessions. Which of the
checkable claims in that narration does the session's own tool log constrain, and how does that compare with narration
that is NOT about the session (controls)?

Inputs (read-only)
  data/ai-village/events.jsonl.gz                streamed once. START_USING_COMPUTER (sessionGoal, computerUseSessionId),
                                                 STOP_USING_COMPUTER (summary), CONSOLIDATE (nextSessionGoal,
                                                 computerUseSessionId) for ALL agents (controls need non-sampled rows).
  data/ai-village/computer_use_sessions.jsonl.gz session_goal, has_been_asked_to_stop for the sampled sessions.
  analysis/cache/samples/aiv_cu.json             A and B session lists (A u B used; split recorded per session).
  analysis/cache/aiv_cu_{A,B}.parquet            IR events (call args/command, result text/stderr, assistant text).
  analysis/cache/aiv_cu_sessions.parquet         stratum, model_string, n_turns, first/last created_at.
Output: analysis/out/phase_c/aiv_narration.json (raw counts and CIs only). Interpretation: analysis/notes/aiv_narration.md.

LINKAGE (fixed before outcomes)
  STOP rows carry NO computerUseSessionId (census below). A STOP is linked to a session by agent order: per agentId,
  START/STOP rows sorted by event_index; a STOP whose immediately preceding START/STOP row of the same agent is a START
  inherits that START's computerUseSessionId. Validated against computer_use_turns times (STOP created_at >= session's last
  turn) and agent ids. CONSOLIDATE rows carry computerUseSessionId; it names the session that just ENDED (checked: created
  after its last turn). Channels per sampled session:
    stop_summary       STOP.summary (pre-perma regime, before 2026-03-24)
    consolidate_goal   CONSOLIDATE.nextSessionGoal(s) for the session (perma regime); forward-looking but often carries state
    session_goal       computer_use_sessions.session_goal, written BEFORE the session (baseline: pre-session text)
  Controls (same extraction, evaluated against THIS session's log):
    c1_prev_same_agent  stop: the same agent's previous STOP summary (any session, sampled or not);
                        consolidate: the same agent's previous CONSOLIDATE nextSessionGoal
    c2_other_agent      the narration of the same channel by a DIFFERENT agent nearest in created_at (ties: lower event_index)

Run: PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_c_aiv_narration
Env: AIVN_SCRATCH=<dir> optional: also write the per-claim table (parquet) there for inspection (never under analysis/out).
"""
import gzip, json, os, re, bisect
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from analysis.lib import stats

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.environ.get("AIV_DATA", r"C:\Swarms\data\ai-village")
CACHE = os.path.join(ROOT, "analysis", "cache")
OUT = os.path.join(ROOT, "analysis", "out", "phase_c", "aiv_narration.json")
SCRATCH = os.environ.get("AIVN_SCRATCH")
SEED = stats.SEED

# ======================================================================================================== PREREG (fixed)
CMD_VERBS = ["git", "gh", "glab", "cd", "ls", "cat", "python", "python3", "pip", "pip3", "npm", "npx", "node", "yarn", "pnpm",
             "curl", "wget", "mkdir", "cp", "mv", "rm", "touch", "grep", "find", "echo", "sed", "awk", "chmod", "bash", "sh",
             "sudo", "apt", "apt-get", "docker", "make", "pytest", "head", "tail", "wc", "tar", "unzip", "zip", "ssh", "scp",
             "rsync", "xdg-open", "firefox", "kill", "pkill", "ps", "netlify", "vercel", "wrangler", "jq", "sort", "diff",
             "ln", "export", "source", "tee", "base64", "convert", "ffmpeg", "libreoffice", "soffice", "nano", "vim", "less",
             "pandoc", "sqlite3", "crontab", "systemctl", "uv", "go", "cargo", "ruby", "perl", "php", "java"]
FILE_EXTS = ["html", "htm", "css", "js", "mjs", "ts", "tsx", "jsx", "json", "md", "txt", "csv", "tsv", "py", "sh", "yml", "yaml",
             "toml", "ods", "odt", "odp", "xlsx", "xls", "docx", "doc", "pptx", "pdf", "png", "jpg", "jpeg", "gif", "svg", "webp",
             "zip", "gz", "tar", "xml", "sql", "db", "ipynb", "log", "ini", "cfg", "rb", "go", "rs", "java", "cpp", "php", "mp3",
             "mp4", "wav", "ogg", "webm", "jsonl", "lock", "bak", "patch", "diff"]
ACTIONS = {
    "push": {"claim": r"\bpushed\b|\bgit push(?:ed)?\b", "evidence": r"\bgit\s+push\b",
             "fail": r"\[rejected\]|\[remote rejected\]|failed to push|fatal:|error:|Permission denied|Authentication failed|"
                     r"could not read Username|Could not resolve host|The requested URL returned error",
             "success": r"\s->\s|Everything up-to-date|\[new branch\]|\[new tag\]"},
    "commit": {"claim": r"\bcommitted\b", "evidence": r"\bgit\s+commit\b",
               "fail": r"nothing to commit|no changes added to commit|nothing added to commit|fatal:|error:",
               "success": r"(?m)^\[[^\]\n]+ [0-9a-f]{7,}\]"},
    "pr_open": {"claim": r"\b(?:opened|created|submitted|filed|raised)\s+(?:(?:a|an|the|my|new|draft)\s+){0,2}"
                         r"(?:pull requests?|PRs?|merge requests?|MRs?)\b",
                "evidence": r"\bgh\s+pr\s+create\b|\bglab\s+mr\s+create\b|\bhub\s+pull-request\b|/pulls\b|/merge_requests\b",
                "fail": r"error|failed|fatal|not found|must first push|\b42[2]\b|\b40[13]\b",
                "success": r"https?://\S+/(?:pull|merge_requests)/\d+"},
    "merge": {"claim": r"\bmerged\b", "evidence": r"\bgit\s+merge\b|\bgh\s+pr\s+merge\b|\bglab\s+mr\s+merge\b|/merge\b",
              "fail": r"CONFLICT|Automatic merge failed|not something we can merge|fatal:|error:",
              "success": r"Fast-forward|Merge made by|[Mm]erged"},
    "tests_pass": {"claim": r"\b(?:all\s+)?(?:\d+\s+)?tests?\s+(?:(?:are|were|now|all)\s+)*(?:pass(?:ed|ing|es)?|succeed(?:ed)?|green)\b",
                   "evidence": r"\bpytest\b|\bpy\.test\b|\bnpm\s+(?:run\s+)?test\b|\byarn\s+test\b|\bpnpm\s+test\b|\bjest\b|"
                               r"\bvitest\b|\bmocha\b|\bgo\s+test\b|\bcargo\s+test\b|-m\s+(?:unittest|pytest)\b|"
                               r"\bnode\s+--test\b|\bmake\s+test\b|\btox\b",
                   "fail": r"\bFAILED\b|\b[1-9]\d*\s+(?:failed|failing|errors?)\b|AssertionError|Traceback \(most recent|"
                           r"npm ERR!|Tests?:\s+[1-9]\d*\s+failed",
                   "success": r"\b\d+\s+passed\b|\bOK\b|\bpassing\b|Tests?:\s+\d+\s+passed"},
    "deploy": {"claim": r"\bdeployed\b|\bwent live\b|\bis (?:now )?live\b",
               "evidence": r"\bnetlify\b|\bvercel\b|\bwrangler\b|\bsurge\b|\bfirebase\s+deploy\b|\bgh-pages\b|\bgit\s+push\b",
               "fail": r"error|failed|fatal|unauthorized|\b40[13]\b", "success": None},
}
NONASSERT = (r"\b(?:not|never|no|failed|fail|unable|couldn't|could not|cannot|can't|yet to|need to|needs to|still need|"
             r"will|would|should|plan(?:ned)? to|to be|try(?:ing)? to|tried to|attempt(?:ed|ing)? to|if|before|until|"
             r"pending|waiting|once|haven't|hasn't|didn't|wasn't|isn't|aren't)\b")
PREREG = {
    "unit": "session (computer_use_sessions.id); A u B samples of aiv_cu (2,200); every CI resamples sessions (lib/stats.py) or is Wilson over sessions",
    "linkage": "STOP -> session by per-agent event_index order (STOP inherits the immediately preceding same-agent START's computerUseSessionId); "
               "CONSOLIDATE -> session by computerUseSessionId (= session that ended)",
    "channels": ["stop_summary", "consolidate_goal", "session_goal"],
    "controls": {"c1_prev_same_agent": "same agent's previous narration of the same channel (by event_index)",
                 "c2_other_agent": "same-channel narration of a different agent nearest in created_at (tie: lower event_index)"},
    "claim_dedupe": "unique (session, channel/control, type, normalized value)",
    "extraction_order": "URLs -> UUIDs removed -> paths -> filenames -> hex ids -> dates/times/versions removed -> numbers; "
                        "commands, quoted strings and action statements from the original text",
    "url": {"rx": "https?://[^\\s<>\"'`)\\]}\u201d\u2019|]+ minus trailing .,;:!?*", "norm": "lowercase, scheme and leading www. removed, trailing / removed",
            "support_exact": "norm URL is a substring of the lowercased log", "support_host": "host (no www.) is a substring of the lowercased log"},
    "path": {"rx": "(~|.|..)?/seg(/seg)+ or ~/seg; segments [\\w.@%+-]+; >=2 segments unless ~/; >=1 segment has a letter; not preceded by [\\w.~/:-]",
             "support_exact": "exact substring of log", "support_basename": "exact path OR last segment (len>=4) substring of log"},
    "filename": {"rx": "[\\w][\\w.-]*\\.(ext) with ext in FILE_EXTS (case-insensitive), not inside a URL/path, not followed by [\\w/-]",
                 "support": "exact (case-sensitive) substring of log"},
    "command": {"source": "inline `...` spans and lines of ``` fenced blocks whose first token (after optional '$ ') is in CMD_VERBS",
                "norm": "whitespace collapsed", "support_exact": "substring of the whitespace-collapsed call-side log (shell commands + all call-arg strings)",
                "support_prefix2": "first two tokens equal the first two tokens of some command segment (split on && || ; | newline) in the call-side log"},
    "quoted": {"rx": "\"...\" or \u201c...\u201d spans of 8-200 chars, single line, not a bare URL/path",
               "support": "case-insensitive, whitespace-collapsed substring of log"},
    "hex_id": {"rx": "[0-9a-f]{7,40} standalone, >=1 digit and >=1 letter, UUIDs removed first, not inside a URL",
               "support_result": "a hex token in result text/stderr equals it, or one is a prefix of the other (both >=7)",
               "commit_context": "within 40 chars of commit|sha|hash|HEAD|push|merged (case-insensitive)"},
    "number": {"rx": "optional $; 1-3 digit groups with commas or plain digits; optional .decimals; optional %",
               "keep": ">=3 digits total; not a 4-digit integer 1900-2099; not preceded by 'Day '; not preceded by [\\w.#/\\\\-]; "
                       "dates YYYY-MM-DD, times HH:MM(:SS), versions x.y.z removed first",
               "support_result": "same normalized value (commas, $ and % dropped) occurs as a number token in result text/stderr",
               "also_reported": "occurs as a number token in call args"},
    "action": {"defs": ACTIONS, "nonassertive": "NONASSERT regex in the clause prefix (from last [.!?;\\n] or up to 80 chars before the match)",
               "evidence_unit": "a call whose shell command or call-arg strings match `evidence`; its outcome from its result text+stderr: "
                                "fail = fail rx and not success rx; success = success rx; else unknown",
               "status": {"supported": ">=1 evidence call not failed", "contradicted_failed": ">=1 evidence call and all failed",
                          "contradicted_absent": "no evidence call and the session has >=1 shell call",
                          "unconstrained": "no evidence call and no shell call (could have been done via GUI)"}},
    "entity_status": "log_result (in result text/stderr) > log_call (in call args/commands only) > assistant_only (only in the session's "
                     "assistant text) > goal_only (only in session_goal) > none. supported = log_result|log_call for url/path/filename/"
                     "command/quoted; supported = log_result for hex_id/number",
    "error_only": "path/url/filename found in results only on lines matching ERROR_LINE (contradiction candidate)",
    "gui_share_bins": "share of the session's calls with tool == 'gui': [0], (0,0.5], (0.5,1]",
    "min_sessions_per_model_row": 20,
    "provenance": {"summary_in_stop_output": "first 100 alphanumeric chars of the summary occur in the alphanumeric-only STOP output",
                   "chars_per_output_token_impossible": "summary chars > 8 x STOP outputTokens"},
}
POST_HOC = {
    "action_claim_conditioned_evidence": {
        "rule": "per channel and action, over sessions of that channel with >=1 shell call: P(log has >=1 evidence call | own narration has an "
                "assertive claim of the action) vs P(log has >=1 evidence call | own narration has no match of the action at all); difference with a "
                "session bootstrap CI. Recall: among sessions of the channel whose log has >=1 evidence call with outcome success, the share whose own "
                "narration has an assertive claim.",
        "why_added": "first run: the pre-registered own-vs-control paired difference for actions is identically 0 with CI [0,0] by construction, "
                     "because an action claim's status depends only on the action type and the session log, never on the claim text"},
    "action_claim_context": {
        "rule": "each action match is tagged: in_code (inside a ``` fence or `inline` span), third_party (clause prefix names another model/agent: "
                "NAME_RX_SRC), else plain. A deduped (session, source, action, assertive) row is plain if any of its occurrences is plain. Status "
                "counts are reported for assertive plain rows.",
        "why_added": "spot-check of 7 STOP push claims with status contradicted_absent: the matches were other agents' pushes, earlier sessions, "
                     "or command blocks written as plans; the pre-registered rule has no subject or code-block attribution"},
    "carryover_split": {
        "rule": "own-channel entity claims split by whether the same (type, normalized value) is also extracted from the c1 control narration of the "
                "same session (stop: the agent's previous STOP summary; consolidate: the agent's previous CONSOLIDATE nextSessionGoal). Support "
                "rates for carried vs novel claims, overall and by gui_bin.",
        "why_added": "first run: c1 controls were supported at about half the own rate, and a spot-check showed STOP summaries that are full memory "
                     "dumps (one: 53 URLs from long-term memory after a 14-turn GUI session)"},
    "placeholder_summaries": {
        "rule": "a STOP summary is a placeholder if its stripped text exactly equals a summary string that occurs >= 100 times among all STOP rows; "
                "substantive coverage = sessions with a non-placeholder STOP summary or a CONSOLIDATE",
        "why_added": "the descriptive duplicate-string count showed three platform placeholder texts covering thousands of STOP rows"},
    "chain_equality": {
        "rule": "for sampled sessions with a CONSOLIDATE and a previous CONSOLIDATE of the same agent: is that previous nextSessionGoal exactly "
                "equal to this session's computer_use_sessions.session_goal?",
        "why_added": "first run: consolidate c1 support rates equalled session_goal rates to 3 decimals"},
}
NAME_RX_SRC = r"\b(?:Claude|Opus|Sonnet|Haiku|Fable|Gemini|GPT|o3|o4|DeepSeek|Kimi|Grok|GLM|Qwen|Muse|Llama|Mistral)\b"

# ===================================================================================================== regexes (compiled)
URL_RX = re.compile(r"https?://[^\s<>\"'`)\]}\u201d\u2019|]+")
UUID_RX = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
PATH_RX = re.compile(r"(?<![\w.~/:\-])((?:~|\.{1,2})?/(?:[\w.@%+\-]+/)*[\w.@%+\-]+/?)")
FILE_RX = re.compile(r"(?<![\w/.\-])([\w][\w.\-]*\.(?:" + "|".join(FILE_EXTS) + r"))(?![\w/\-])", re.I)
HEX_RX = re.compile(r"(?<![0-9A-Za-z])([0-9a-f]{7,40})(?![0-9A-Za-z])")
DATE_RX = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
TIME_RX = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
VER_RX = re.compile(r"\bv?\d+(?:\.\d+){2,}\b")
NUM_RX = re.compile(r"(?<![\w.#/\\\-])\$?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?%?(?![\w/\\\-]|\.\d)")
NUM_TOKEN_RX = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)(?![\d]|\.\d)")
HEX_TOKEN_RX = re.compile(r"(?<![0-9A-Za-z])([0-9a-f]{7,40})(?![0-9A-Za-z])")
INLINE_CODE_RX = re.compile(r"`([^`\n]+)`")
FENCE_RX = re.compile(r"```[^\n]*\n(.*?)```", re.S)
QUOTE_RX = re.compile(r"\"([^\"\n]{8,200})\"|\u201c([^\u201d\n]{8,200})\u201d")
SEG_SPLIT_RX = re.compile(r"&&|\|\||;|\||\n")
COMMIT_CTX_RX = re.compile(r"commit|sha|hash|HEAD|push|merged", re.I)
ERROR_LINE_RX = re.compile(r"no such file|not found|does not exist|cannot access|cannot open|permission denied|could not resolve|"
                           r"failed to connect|fatal:|\b404\b|curl: \(|traceback|error:", re.I)
NONASSERT_RX = re.compile(NONASSERT, re.I)
NAME_RX = re.compile(NAME_RX_SRC)
ACT_RX = {k: {kk: (re.compile(v, re.I) if (v and kk in ("claim",)) else (re.compile(v) if v else None))
              for kk, v in d.items()} for k, d in ACTIONS.items()}
VERBS = set(CMD_VERBS)
WS_RX = re.compile(r"\s+")
COMMA_RX = re.compile(r"(?<=\d),(?=\d{3}\b)")
ALNUM_RX = re.compile(r"[^0-9A-Za-z]+")


# ================================================================================================================ utils
def wil(k, n):
    p, lo, hi = stats.wilson(k, n)
    return {"k": int(k), "n": int(n), "p": p, "lo": lo, "hi": hi}


def ts_s(s):
    """'YYYY-MM-DD HH:MM:SS.ffffff' or ISO with Z -> epoch seconds (float)."""
    if s is None:
        return None
    s = str(s).strip().replace(" ", "T").rstrip("Z")
    return pd.Timestamp(s, tz="UTC").value / 1e9


def to_int(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def crate(num, den):
    return stats.cluster_rate(num, den)


def paired_diff(num_a, den_a, num_b, den_b, n_boot=stats.N_BOOT, seed=SEED):
    """Rate(a) - rate(b) over sessions with den_a>0 and den_b>0; session-clustered bootstrap CI."""
    na, da, nb, db = (np.asarray(x, float) for x in (num_a, den_a, num_b, den_b))
    keep = (da > 0) & (db > 0)
    na, da, nb, db = na[keep], da[keep], nb[keep], db[keep]
    n = len(da)
    if n == 0:
        return {"diff": None, "lo": None, "hi": None, "n_sessions": 0}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    boots = na[idx].sum(1) / da[idx].sum(1) - nb[idx].sum(1) / db[idx].sum(1)
    return {"diff": float(na.sum() / da.sum() - nb.sum() / db.sum()), "lo": float(np.quantile(boots, 0.025)),
            "hi": float(np.quantile(boots, 0.975)), "n_sessions": int(n),
            "rate_a": float(na.sum() / da.sum()), "rate_b": float(nb.sum() / db.sum())}


def spearman_ci(x, y, n_boot=stats.N_BOOT, seed=SEED):
    from scipy.stats import spearmanr
    x = np.asarray(x, float); y = np.asarray(y, float)
    if len(x) < 4:
        return {"r": None, "n": int(len(x))}
    r = float(spearmanr(x, y).statistic)
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(n_boot):
        i = rng.integers(0, len(x), size=len(x))
        if len(set(x[i])) > 1 and len(set(y[i])) > 1:
            boots.append(spearmanr(x[i], y[i]).statistic)
    return {"r": r, "lo": float(np.quantile(boots, 0.025)), "hi": float(np.quantile(boots, 0.975)), "n": int(len(x))}


# ============================================================================================================ extraction
def norm_url(u):
    u = u.rstrip(".,;:!?*")
    low = u.lower()
    low = re.sub(r"^https?://", "", low)
    if low.startswith("www."):
        low = low[4:]
    return low.rstrip("/")


def extract(text):
    """Fixed extraction rules (PREREG). Returns list of (type, value, extra) with value normalized; duplicates kept here."""
    out = []
    if not text:
        return out
    t = str(text)
    # URLs
    spans = []
    for m in URL_RX.finditer(t):
        raw = m.group(0).rstrip(".,;:!?*")
        nu = norm_url(raw)
        if nu and "." in nu.split("/")[0]:
            out.append(("url", nu, {"redacted": "[redacted]" in nu}))
        spans.append(m.span())
    s = list(t)
    for a, b in spans:
        s[a:b] = [" "] * (b - a)
    t2 = "".join(s)
    t2 = UUID_RX.sub(lambda m: " " * len(m.group(0)), t2)
    # paths
    pspans = []
    for m in PATH_RX.finditer(t2):
        p = m.group(1).rstrip(".")
        segs = [x for x in p.split("/") if x and x not in ("~", ".", "..")]
        if not segs or not any(re.search(r"[A-Za-z]", x) for x in segs):
            continue
        if len(segs) < 2 and not p.startswith("~/"):
            continue
        out.append(("path", p.rstrip("/"), {}))
        pspans.append(m.span(1))
    s = list(t2)
    for a, b in pspans:
        s[a:b] = [" "] * (b - a)
    t3 = "".join(s)
    # filenames
    fspans = []
    for m in FILE_RX.finditer(t3):
        out.append(("filename", m.group(1), {}))
        fspans.append(m.span(1))
    s = list(t3)
    for a, b in fspans:
        s[a:b] = [" "] * (b - a)
    t4 = "".join(s)
    # hex ids
    hspans = []
    for m in HEX_RX.finditer(t4):
        h = m.group(1)
        if re.search(r"\d", h) and re.search(r"[a-f]", h):
            ctx = t4[max(0, m.start() - 40): m.end() + 40]
            out.append(("hex_id", h, {"commit_context": bool(COMMIT_CTX_RX.search(ctx))}))
            hspans.append(m.span(1))
    s = list(t4)
    for a, b in hspans:
        s[a:b] = [" "] * (b - a)
    t5 = "".join(s)
    for rx in (DATE_RX, TIME_RX, VER_RX):
        t5 = rx.sub(lambda m: " " * len(m.group(0)), t5)
    # numbers
    for m in NUM_RX.finditer(t5):
        ip, dp = m.group(1), m.group(2)
        digits = len(ip.replace(",", "")) + (len(dp) if dp else 0)
        if digits < 3:
            continue
        if not dp and "," not in ip and len(ip) == 4 and 1900 <= int(ip) <= 2099:
            continue
        if t5[max(0, m.start() - 4): m.start()].lower() == "day ":
            continue
        v = ip.replace(",", "") + ("." + dp if dp else "")
        out.append(("number", v, {}))
    # commands
    cands = [m.group(1) for m in INLINE_CODE_RX.finditer(re.sub(r"```.*?```", " ", t, flags=re.S))]
    for m in FENCE_RX.finditer(t):
        cands.extend(m.group(1).split("\n"))
    for c in cands:
        c = c.strip()
        if c.startswith("$ "):
            c = c[2:].strip()
        toks = c.split()
        if toks and toks[0] in VERBS and len(c) >= 4:
            out.append(("command", WS_RX.sub(" ", c), {}))
    # quoted strings
    for m in QUOTE_RX.finditer(t):
        q = (m.group(1) or m.group(2)).strip()
        if len(q) < 8 or URL_RX.fullmatch(q) or PATH_RX.fullmatch(q):
            continue
        out.append(("quoted", WS_RX.sub(" ", q).lower(), {}))
    return out


def extract_actions(text):
    """Action statements: (action, assertive: bool)."""
    out = []
    if not text:
        return out
    t = str(text)
    code_spans = [m.span() for m in re.finditer(r"```.*?```", t, flags=re.S)]
    code_spans += [m.span() for m in INLINE_CODE_RX.finditer(t)]
    for a, rx in ACT_RX.items():
        for m in rx["claim"].finditer(t):
            st = m.start()
            pre = t[max(0, st - 80): st]
            cut = max(pre.rfind("."), pre.rfind("!"), pre.rfind("?"), pre.rfind(";"), pre.rfind("\n"))
            clause = pre[cut + 1:] if cut >= 0 else pre
            ctx = ("in_code" if any(a0 <= st < b0 for a0, b0 in code_spans) else
                   "third_party" if NAME_RX.search(clause) else "plain")
            out.append((a, not bool(NONASSERT_RX.search(clause)), ctx))
    return out


# ============================================================================================================ session log
def json_strings(x, acc):
    if isinstance(x, str):
        acc.append(x)
    elif isinstance(x, dict):
        for v in x.values():
            json_strings(v, acc)
    elif isinstance(x, list):
        for v in x:
            json_strings(v, acc)


class Log:
    __slots__ = ("call", "call_low", "call_ws", "result", "result_low", "result_ws_low", "call_ws_low", "asst", "asst_low",
                 "asst_ws_low", "result_nums", "call_nums", "result_hex", "call_hex", "segs2", "acts", "n_calls", "n_shell",
                 "n_gui", "result_lines_err", "asst_nums")

    def __init__(self, g):
        calls = g[g.kind == "call"]
        res = g[g.kind == "result"]
        asst = g[g.kind == "assistant"]
        call_strs, cmd_strs = [], []
        per_call = {}
        for r in calls.itertuples(index=False):
            acc = []
            if r.args is not None and not pd.isna(r.args):
                try:
                    json_strings(json.loads(r.args), acc)
                except (ValueError, TypeError):
                    acc.append(str(r.args))
            if r.command is not None and not pd.isna(r.command):
                acc.append(str(r.command))
            call_strs.extend(acc)
            per_call[r.call_id] = "\n".join(acc)
        res_by_call = {}
        res_strs = []
        for r in res.itertuples(index=False):
            parts = [str(x) for x in (r.text, r.stderr) if x is not None and not pd.isna(x)]
            res_by_call[r.call_id] = "\n".join(parts)
            res_strs.extend(parts)
        self.call = "\n".join(call_strs)
        self.result = "\n".join(res_strs)
        self.asst = "\n".join(str(x) for x in asst.text if x is not None and not pd.isna(x))
        self.call_low = self.call.lower()
        self.result_low = self.result.lower()
        self.asst_low = self.asst.lower()
        self.call_ws = WS_RX.sub(" ", self.call)
        self.call_ws_low = self.call_ws.lower()
        self.result_ws_low = WS_RX.sub(" ", self.result_low)
        self.asst_ws_low = WS_RX.sub(" ", self.asst_low)
        self.result_nums = num_tokens(self.result)
        self.call_nums = num_tokens(self.call)
        self.asst_nums = num_tokens(self.asst)
        self.result_hex = set(m.group(1) for m in HEX_TOKEN_RX.finditer(self.result_low))
        self.call_hex = set(m.group(1) for m in HEX_TOKEN_RX.finditer(self.call_low))
        segs2 = set()
        for c in call_strs:
            for seg in SEG_SPLIT_RX.split(c):
                tk = seg.split()
                if len(tk) >= 2:
                    segs2.add((tk[0], tk[1]))
        self.segs2 = segs2
        # action evidence: per call (string, outcome text)
        self.acts = [(per_call[cid], res_by_call.get(cid, "")) for cid in per_call]
        self.n_calls = len(calls)
        self.n_shell = int((calls.tool == "shell").sum())
        self.n_gui = int((calls.tool == "gui").sum())
        self.result_lines_err = None


def hex_in(h, toks):
    if h in toks:
        return True
    p = h[:7]
    for t in toks:
        if t[:7] == p and (t.startswith(h) or h.startswith(t)):
            return True
    return False


def err_only(value, log, low=False):
    """value found in results, and every result line containing it matches ERROR_LINE_RX."""
    hay = log.result_low if low else log.result
    if value not in hay:
        return False
    for line in hay.split("\n"):
        if value in line and not ERROR_LINE_RX.search(line):
            return False
    return True


def num_tokens(text):
    return set(m.group(1) for m in NUM_TOKEN_RX.finditer(COMMA_RX.sub("", text or "")))


def eval_entity(typ, val, ex, log, goal_low, goal_raw, goal_nums):
    """Return dict of booleans + status."""
    r = {}
    if typ == "url":
        host = val.split("/")[0]
        if host.startswith("www."):
            host = host[4:]
        in_res, in_call = val in log.result_low, val in log.call_low
        r["host_in_log"] = host in log.result_low or host in log.call_low
        in_asst, in_goal = val in log.asst_low, val in goal_low
        r["error_only"] = bool(in_res and not in_call and err_only(val, log, low=True))
    elif typ in ("path", "filename"):
        in_res, in_call = val in log.result, val in log.call
        in_asst, in_goal = val in log.asst, val in goal_raw
        if typ == "path":
            base = val.rstrip("/").split("/")[-1]
            r["basename_in_log"] = in_res or in_call or (len(base) >= 4 and (base in log.result or base in log.call))
        r["error_only"] = bool(in_res and not in_call and err_only(val, log))
    elif typ == "command":
        in_call = val in log.call_ws
        tk = val.split()
        r["prefix2"] = in_call or (len(tk) >= 2 and (tk[0], tk[1]) in log.segs2)
        in_res = val.lower() in log.result_ws_low
        in_asst, in_goal = val.lower() in log.asst_ws_low, val.lower() in WS_RX.sub(" ", goal_low)
    elif typ == "quoted":
        in_res, in_call = val in log.result_ws_low, val in log.call_ws_low
        in_asst, in_goal = val in log.asst_ws_low, val in WS_RX.sub(" ", goal_low)
    elif typ == "hex_id":
        in_res, in_call = hex_in(val, log.result_hex), hex_in(val, log.call_hex)
        in_asst, in_goal = val in log.asst_low, val in goal_low
        r["commit_context"] = ex.get("commit_context", False)
    elif typ == "number":
        in_res, in_call = val in log.result_nums, val in log.call_nums
        in_asst, in_goal = val in log.asst_nums, val in goal_nums
    else:
        raise ValueError(typ)
    status = ("log_result" if in_res else "log_call" if in_call else "assistant_only" if in_asst else
              "goal_only" if in_goal else "none")
    if typ in ("hex_id", "number"):
        supported = bool(in_res)
    else:
        supported = bool(in_res or in_call)
    r.update({"in_result": bool(in_res), "in_call": bool(in_call), "status": status, "supported": supported})
    return r


def eval_action(a, assertive, log):
    rx = ACT_RX[a]
    ev = [(s, o) for s, o in log.acts if rx["evidence"].search(s)]
    outs = []
    for _, o in ev:
        f = bool(rx["fail"].search(o)) if o else False
        sc = bool(rx["success"].search(o)) if (o and rx["success"] is not None) else False
        outs.append("fail" if (f and not sc) else "success" if sc else "unknown")
    if ev:
        status = "contradicted_failed" if all(x == "fail" for x in outs) else "supported"
    else:
        status = "contradicted_absent" if log.n_shell > 0 else "unconstrained"
    return {"status": status, "n_evidence": len(ev), "n_success": outs.count("success"), "n_fail": outs.count("fail"),
            "n_unknown": outs.count("unknown")}


# ============================================================================================================ loading
def stream_events():
    census = {"rows": 0, "action_types": Counter(), "keys": defaultdict(Counter)}
    starts, stops, cons = [], [], []
    path = os.path.join(DATA, "events.jsonl.gz")
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            census["rows"] += 1
            d = json.loads(line)
            da = d.get("data") or {}
            at = da.get("actionType")
            census["action_types"][at] += 1
            if at not in ("START_USING_COMPUTER", "STOP_USING_COMPUTER", "CONSOLIDATE"):
                continue
            for k in da:
                census["keys"][at][k] += 1
            out_s = da.get("output")
            out_s = "" if out_s is None else (out_s if isinstance(out_s, str) else json.dumps(out_s, ensure_ascii=False))
            base = {"eid": d["id"], "event_index": int(d["event_index"]), "created_at": d["created_at"], "agentId": da.get("agentId"),
                    "inputTokens": to_int(da.get("inputTokens")), "outputTokens": to_int(da.get("outputTokens")),
                    "output_len": len(out_s), "sid": da.get("computerUseSessionId")}
            if at == "START_USING_COMPUTER":
                base["goal"] = da.get("sessionGoal")
                starts.append(base)
            elif at == "STOP_USING_COMPUTER":
                sm = da.get("summary") or ""
                base["text"] = sm
                head = ALNUM_RX.sub("", sm)[:100]
                base["summary_head_in_output"] = bool(head) and head in ALNUM_RX.sub("", out_s)
                base["output_present"] = bool(out_s)
                stops.append(base)
            else:
                base["text"] = da.get("nextSessionGoal") or ""
                cons.append(base)
    census["action_types"] = dict(census["action_types"].most_common())
    census["keys"] = {k: dict(v) for k, v in census["keys"].items()}
    return census, starts, stops, cons


def pair_stops(starts, stops):
    rows = [("START", r) for r in starts] + [("STOP", r) for r in stops]
    by_agent = defaultdict(list)
    for kind, r in rows:
        by_agent[r["agentId"]].append((r["event_index"], kind, r))
    pairs, st = {}, Counter()
    for ag, lst in by_agent.items():
        lst.sort(key=lambda x: x[0])
        prev = None
        for ei, kind, r in lst:
            if kind == "STOP":
                if prev is None:
                    st["stop_without_prior_row"] += 1
                elif prev[1] == "START":
                    st["stop_after_start"] += 1
                    pairs[prev[2]["sid"]] = r
                    r["sid"] = prev[2]["sid"]
                else:
                    st["stop_after_stop"] += 1
            prev = (ei, kind, r)
    st["start_rows"] = len(starts)
    st["start_without_stop"] = len(starts) - st["stop_after_start"]
    return pairs, dict(st)


def load_ir(paths):
    cols = ["session_id", "kind", "tool", "call_id", "args", "command", "text", "stderr"]
    parts = [pd.read_parquet(p, columns=cols) for p in paths]
    df = pd.concat(parts, ignore_index=True)
    df = df[df.kind.isin(["call", "result", "assistant"])]
    for c in ("args", "command", "text", "stderr", "call_id", "tool", "kind", "session_id"):
        df[c] = df[c].astype(object).where(df[c].notna(), None)
    return df


# ============================================================================================================ aggregation
ENTITY_TYPES = ["url", "path", "filename", "command", "quoted", "hex_id", "number"]


def rates_by_session(cl, sessions, num_mask, den_mask):
    g_num = cl[num_mask].groupby("session_id").size()
    g_den = cl[den_mask].groupby("session_id").size()
    num = [int(g_num.get(s, 0)) for s in sessions]
    den = [int(g_den.get(s, 0)) for s in sessions]
    return num, den


def entity_block(cl, sessions):
    """cl: claim rows of one channel/source. Returns per type counts and clustered rates."""
    out = {}
    for typ in ENTITY_TYPES:
        c = cl[cl.type == typ]
        b = {"n_claims": int(len(c)), "n_sessions_with": int(c.session_id.nunique()),
             "status_counts": {k: int(v) for k, v in c.status.value_counts().items()}}
        if len(c):
            sess = sorted(c.session_id.unique())
            for name, mask in (("supported", c.supported), ("in_result", c.in_result), ("in_call", c.in_call),
                               ("in_log_any", c.in_result | c.in_call),
                               ("assistant_only", c.status == "assistant_only"), ("goal_only", c.status == "goal_only"),
                               ("none", c.status == "none")):
                num, den = rates_by_session(c, sess, mask, np.ones(len(c), bool))
                b[name] = crate(num, den)
            if typ == "url":
                num, den = rates_by_session(c, sess, c.host_in_log.eq(True), np.ones(len(c), bool))
                b["host_in_log"] = crate(num, den)
                b["redacted_claims"] = int(c.redacted.eq(True).sum())
            if typ == "path":
                num, den = rates_by_session(c, sess, c.basename_in_log.eq(True), np.ones(len(c), bool))
                b["basename_or_exact_in_log"] = crate(num, den)
            if typ in ("url", "path", "filename"):
                b["error_only_claims"] = int(c.error_only.eq(True).sum())
            if typ == "command":
                num, den = rates_by_session(c, sess, c.prefix2.eq(True), np.ones(len(c), bool))
                b["prefix2_in_call_log"] = crate(num, den)
            if typ == "hex_id":
                cc = c[c.commit_context.eq(True)]
                b["commit_context_claims"] = int(len(cc))
                if len(cc):
                    s2 = sorted(cc.session_id.unique())
                    num, den = rates_by_session(cc, s2, cc.supported, np.ones(len(cc), bool))
                    b["commit_context_supported"] = crate(num, den)
        out[typ] = b
    return out


def action_block(ac):
    out = {}
    for a in ACTIONS:
        c = ac[ac.action == a]
        ca = c[c.assertive]
        b = {"n_matches": int(len(c)), "n_assertive": int(len(ca)), "n_nonassertive": int((~c.assertive).sum()),
             "n_sessions_assertive": int(ca.session_id.nunique()),
             "status_counts_assertive": {k: int(v) for k, v in ca.status.value_counts().items()}}
        if len(ca):
            sess = sorted(ca.session_id.unique())
            for st in ("supported", "contradicted_failed", "contradicted_absent", "unconstrained"):
                num, den = rates_by_session(ca, sess, ca.status == st, np.ones(len(ca), bool))
                b[st] = crate(num, den)
            b["evidence_outcomes_assertive"] = {"success": int(ca.n_success.sum()), "fail": int(ca.n_fail.sum()),
                                                "unknown": int(ca.n_unknown.sum())}
        out[a] = b
    return out


def main():
    smp = json.load(open(os.path.join(CACHE, "samples", "aiv_cu.json")))
    split = {s: "A" for s in smp["A"]}
    split.update({s: "B" for s in smp["B"]})
    sampled = set(split)
    ss = pd.read_parquet(os.path.join(CACHE, "aiv_cu_sessions.parquet"),
                         columns=["session_id", "n_turns", "first_created_at", "last_created_at", "agent_id", "model_string",
                                  "stratum", "n_bash_turns", "n_gui_turns", "n_synthetic_turns"]).set_index("session_id")
    syn = ss["n_synthetic_turns"].to_dict()

    census, starts, stops, cons = stream_events()
    pairs, pair_stats = pair_stops(starts, stops)

    # ---------------------------------------------------------------- linkage validation (all linked sessions in the table)
    lv = Counter()
    for sid, r in pairs.items():
        if sid not in ss.index:
            lv["stop_session_not_in_turns"] += 1
            continue
        lv["stop_linked_in_turns"] += 1
        t = ts_s(r["created_at"])
        lv["stop_after_last_turn"] += int(t >= ts_s(ss.at[sid, "last_created_at"]))
        lv["stop_agent_eq_session_agent"] += int(r["agentId"] == ss.at[sid, "agent_id"])
    cons_by_sid = defaultdict(list)
    for r in cons:
        cons_by_sid[r["sid"]].append(r)
    for sid, lst in cons_by_sid.items():
        if sid not in ss.index:
            lv["consolidate_session_not_in_turns"] += len(lst)
            continue
        for r in lst:
            lv["consolidate_linked_in_turns"] += 1
            t = ts_s(r["created_at"])
            lv["consolidate_after_last_turn"] += int(t >= ts_s(ss.at[sid, "last_created_at"]))
            lv["consolidate_before_first_turn"] += int(t < ts_s(ss.at[sid, "first_created_at"]))
            lv["consolidate_agent_eq_session_agent"] += int(r["agentId"] == ss.at[sid, "agent_id"])
    lv["sessions_with_multiple_consolidate"] = sum(1 for v in cons_by_sid.values() if len(v) > 1)

    # ---------------------------------------------------------------- session goals for sampled sessions
    goals, asked = {}, Counter()
    with gzip.open(os.path.join(DATA, "computer_use_sessions.jsonl.gz"), "rt", encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            if d["id"] in sampled:
                goals[d["id"]] = d.get("session_goal") or ""
                asked[bool(d.get("has_been_asked_to_stop"))] += 1
    start_goal_eq = Counter()
    for r in starts:
        if r["sid"] in goals:
            start_goal_eq[(r.get("goal") or "") == goals[r["sid"]]] += 1

    # ---------------------------------------------------------------- controls
    def prev_same_agent(rows):
        by = defaultdict(list)
        for r in rows:
            by[r["agentId"]].append(r)
        prev = {}
        for ag, lst in by.items():
            lst.sort(key=lambda x: x["event_index"])
            for i in range(1, len(lst)):
                prev[lst[i]["eid"]] = lst[i - 1]
        return prev

    def nearest_other_agent(rows):
        srt = sorted(rows, key=lambda x: (ts_s(x["created_at"]), x["event_index"]))
        tt = [ts_s(x["created_at"]) for x in srt]
        def f(r):
            t = ts_s(r["created_at"])
            i = bisect.bisect_left(tt, t)
            best, bd = None, None
            lo, hi = i - 1, i
            while lo >= 0 or hi < len(srt):
                for j in (lo, hi):
                    if 0 <= j < len(srt) and srt[j]["agentId"] != r["agentId"]:
                        d = abs(tt[j] - t)
                        if bd is None or d < bd or (d == bd and srt[j]["event_index"] < best["event_index"]):
                            best, bd = srt[j], d
                if best is not None and (lo < 0 or t - tt[lo] > bd) and (hi >= len(srt) or tt[hi] - t > bd):
                    break
                lo -= 1; hi += 1
            return best
        return f

    stop_prev = prev_same_agent([r for r in stops if r.get("sid")])
    cons_prev = prev_same_agent(cons)
    stop_near = nearest_other_agent([r for r in stops if r.get("sid")])
    cons_near = nearest_other_agent(cons)

    # narrations per sampled session: list of (source, text)
    narr = defaultdict(list)
    chain_eq = Counter()
    for sid in sorted(sampled):
        if sid in pairs:
            r = pairs[sid]
            narr[sid].append(("stop_summary", r["text"]))
            p = stop_prev.get(r["eid"])
            if p is not None:
                narr[sid].append(("stop_c1_prev_same_agent", p["text"]))
            o = stop_near(r)
            if o is not None:
                narr[sid].append(("stop_c2_other_agent", o["text"]))
        if sid in cons_by_sid:
            lst = sorted(cons_by_sid[sid], key=lambda x: x["event_index"])
            narr[sid].append(("consolidate_goal", "\n".join(x["text"] for x in lst)))
            p = cons_prev.get(lst[0]["eid"])
            if p is not None:
                narr[sid].append(("consolidate_c1_prev_same_agent", p["text"]))
                chain_eq[(p["text"] or "") == goals.get(sid, "")] += 1  # post hoc: chain_equality
            else:
                chain_eq["no_previous_consolidate"] += 1
            o = cons_near(lst[0])
            if o is not None:
                narr[sid].append(("consolidate_c2_other_agent", o["text"]))
        narr[sid].append(("session_goal", goals.get(sid, "")))

    # ---------------------------------------------------------------- evaluate per session
    ir = load_ir([os.path.join(CACHE, "aiv_cu_A.parquet"), os.path.join(CACHE, "aiv_cu_B.parquet")])
    ir_sessions = set(ir.session_id.unique())
    ent_rows, act_rows, sess_rows = [], [], []
    for sid, g in ir.groupby("session_id", sort=True):
        if sid not in sampled:
            continue
        log = Log(g)
        goal_raw = goals.get(sid, "")
        goal_low = goal_raw.lower()
        goal_nums = num_tokens(goal_raw)
        srow = {"session_id": sid, "split": split[sid], "stratum": ss.at[sid, "stratum"], "model_string": ss.at[sid, "model_string"],
                "n_turns": int(ss.at[sid, "n_turns"]), "n_calls": log.n_calls, "n_shell": log.n_shell, "n_gui": log.n_gui,
                "has_stop": sid in pairs, "has_consolidate": sid in cons_by_sid,
                "result_chars": len(log.result), "call_chars": len(log.call)}
        for a in ACTIONS:  # post hoc (action_claim_conditioned_evidence): evidence in the log regardless of any claim
            ea = eval_action(a, True, log)
            srow["ev_" + a] = ea["n_evidence"]
            srow["evs_" + a] = ea["n_success"]
        sess_rows.append(srow)
        for src, text in narr.get(sid, []):
            seen = set()
            for typ, val, ex in extract(text):
                key = (typ, val)
                if key in seen:
                    continue
                seen.add(key)
                e = eval_entity(typ, val, ex, log, goal_low, goal_raw, goal_nums)
                ent_rows.append({"session_id": sid, "source": src, "type": typ, "value": val,
                                 "redacted": ex.get("redacted"), **e})
            actx = defaultdict(set)
            for a, assertive, ctx in extract_actions(text):
                actx[(a, assertive)].add(ctx)
            for (a, assertive), ctxs in actx.items():
                act_rows.append({"session_id": sid, "source": src, "action": a, "assertive": assertive,
                                 "ctx_plain": "plain" in ctxs, "ctx_code": "in_code" in ctxs, "ctx_third": "third_party" in ctxs,
                                 **eval_action(a, assertive, log)})
    del ir
    S = pd.DataFrame(sess_rows).set_index("session_id")
    E = pd.DataFrame(ent_rows)
    for c in ("host_in_log", "basename_in_log", "prefix2", "commit_context", "error_only", "redacted"):
        if c not in E:
            E[c] = None
    A = pd.DataFrame(act_rows)
    if SCRATCH:
        os.makedirs(SCRATCH, exist_ok=True)
        E.to_parquet(os.path.join(SCRATCH, "aivn_entities.parquet"))
        A.to_parquet(os.path.join(SCRATCH, "aivn_actions.parquet"))
        S.to_parquet(os.path.join(SCRATCH, "aivn_sessions.parquet"))

    S["gui_bin"] = np.where(S.n_calls == 0, "no_calls",
                            np.where(S.n_gui == 0, "gui_0", np.where(S.n_gui / S.n_calls.clip(lower=1) <= 0.5, "gui_le_half", "gui_gt_half")))

    res = {"probe": "phase_c_aiv_narration",
           "source": {"files": ["data/ai-village/events.jsonl.gz", "data/ai-village/computer_use_sessions.jsonl.gz",
                                "analysis/cache/aiv_cu_A.parquet", "analysis/cache/aiv_cu_B.parquet",
                                "analysis/cache/aiv_cu_sessions.parquet", "analysis/cache/samples/aiv_cu.json"]},
           "prereg": PREREG, "post_hoc_rules": POST_HOC}

    # ---------------------------------------------------------------- census + linkage
    res["events_census"] = {"rows": census["rows"], "action_types": census["action_types"], "boundary_keys": census["keys"]}
    res["linkage"] = {"stop_pairing": pair_stats, "validation": dict(lv),
                      "sampled_has_been_asked_to_stop": {str(k): v for k, v in asked.items()},
                      "start_sessionGoal_eq_session_goal": {str(k): v for k, v in start_goal_eq.items()},
                      "sampled_sessions": len(sampled), "sampled_sessions_in_ir": len(sampled & ir_sessions),
                      "sampled_not_in_ir": {"n": len(sampled - ir_sessions),
                                            "n_turns": stats.describe(ss.loc[sorted(sampled - ir_sessions), "n_turns"].values),
                                            "n_synthetic_turns_eq_n_turns": int(sum(
                                                1 for s in sampled - ir_sessions
                                                if s in syn and syn[s] == ss.at[s, "n_turns"]))}}

    # ---------------------------------------------------------------- coverage
    cov = {}
    n = len(S)
    cov["all"] = {"n_sessions": n, "has_stop_summary": wil(int(S.has_stop.sum()), n),
                  "has_consolidate": wil(int(S.has_consolidate.sum()), n),
                  "has_both": int((S.has_stop & S.has_consolidate).sum()),
                  "has_neither": wil(int((~S.has_stop & ~S.has_consolidate).sum()), n),
                  "stop_summary_nonempty": int(sum(1 for s in S.index[S.has_stop] if (pairs[s]["text"] or "").strip()))}
    for k, g in S.groupby("split"):
        cov["split_" + k] = {"n_sessions": len(g), "has_stop_summary": wil(int(g.has_stop.sum()), len(g)),
                             "has_consolidate": wil(int(g.has_consolidate.sum()), len(g)),
                             "has_neither": wil(int((~g.has_stop & ~g.has_consolidate).sum()), len(g))}
    cov["by_stratum"] = {k: {"n_sessions": len(g), "has_stop_summary": int(g.has_stop.sum()),
                             "has_consolidate": int(g.has_consolidate.sum()),
                             "has_neither": int((~g.has_stop & ~g.has_consolidate).sum())}
                         for k, g in S.groupby("stratum")}
    neither = S[~S.has_stop & ~S.has_consolidate]
    cov["neither_profile"] = {"n": len(neither), "n_turns": stats.describe(neither.n_turns.values),
                              "by_stratum": {k: int(v) for k, v in neither.stratum.value_counts().items()},
                              "first_month": {k: int(v) for k, v in
                                              ss.loc[neither.index, "first_created_at"].str[:7].value_counts().sort_index().items()}}
    res["coverage"] = cov

    # ---------------------------------------------------------------- summary profile / provenance (sampled STOP)
    st_rows = []
    for sid in S.index[S.has_stop]:
        r = pairs[sid]
        last = ts_s(ss.at[sid, "last_created_at"])
        st_rows.append({"sid": sid, "stratum": S.at[sid, "stratum"], "chars": len(r["text"] or ""), "out_tok": r["outputTokens"],
                        "in_tok": r["inputTokens"], "head_in_out": r["summary_head_in_output"], "out_present": r["output_present"],
                        "lat_s": ts_s(r["created_at"]) - last, "n_turns": S.at[sid, "n_turns"]})
    P = pd.DataFrame(st_rows)
    P["out_tok"] = pd.to_numeric(P.out_tok, errors="coerce")
    prof = {"n": len(P), "summary_chars": stats.describe(P.chars.values), "latency_s_stop_minus_last_turn": stats.describe(P.lat_s.values),
            "spearman_chars_vs_n_turns": spearman_ci(P.chars.values, P.n_turns.values),
            "spearman_chars_vs_latency": spearman_ci(P.chars.values, P.lat_s.values),
            "stop_output_present": wil(int(P.out_present.sum()), len(P)),
            "summary_head_in_stop_output": wil(int(P.head_in_out.sum()), len(P)),
            "output_tokens": stats.describe(P.out_tok.dropna().values)}
    pp = P[P.out_tok.notna() & (P.out_tok > 0)]
    prof["chars_per_output_token"] = stats.describe((pp.chars / pp.out_tok).values)
    prof["summary_chars_gt_8x_output_tokens"] = wil(int((pp.chars > 8 * pp.out_tok).sum()), len(pp))
    prof["output_tokens_zero_or_missing"] = int(len(P) - len(pp))
    prof["by_stratum"] = {k: {"n": len(g), "chars_median": float(g.chars.median()), "head_in_output": int(g.head_in_out.sum()),
                              "output_present": int(g.out_present.sum()),
                              "chars_gt_8x_out_tok": int(((g.out_tok > 0) & (g.chars > 8 * g.out_tok)).sum()),
                              "latency_s_median": float(g.lat_s.median())}
                          for k, g in P.groupby("stratum")}
    # population (all STOP rows, not only sampled) for the provenance fields
    allP = pd.DataFrame([{"chars": len(r["text"] or ""), "out_tok": r["outputTokens"], "head_in": r["summary_head_in_output"],
                          "out_present": r["output_present"]} for r in stops])
    allP["out_tok"] = pd.to_numeric(allP.out_tok, errors="coerce")
    ap = allP[allP.out_tok.notna() & (allP.out_tok > 0)]
    prof["population_all_stop_rows"] = {"n": len(allP), "output_present": wil(int(allP.out_present.sum()), len(allP)),
                                        "summary_head_in_stop_output": wil(int(allP.head_in.sum()), len(allP)),
                                        "summary_chars_gt_8x_output_tokens": wil(int((ap.chars > 8 * ap.out_tok).sum()), len(ap)),
                                        "chars_per_output_token": stats.describe((ap.chars / ap.out_tok).values)}
    # exact-duplicate summary strings (population of all STOP rows; descriptive)
    dup = Counter((r["text"] or "").strip() for r in stops)
    top = [(t, c) for t, c in dup.most_common(5) if c >= 2]
    samp_text = Counter((pairs[s]["text"] or "").strip() for s in S.index[S.has_stop])
    prof["duplicate_summary_strings"] = {
        "population_rows_with_a_duplicated_string": int(sum(c for c in dup.values() if c >= 2)),
        "population_distinct_duplicated_strings": int(sum(1 for c in dup.values() if c >= 2)),
        "top5": [{"text_head": t[:100], "population_count": int(c), "sampled_count": int(samp_text.get(t, 0))} for t, c in top]}
    cP = pd.DataFrame([{"chars": len(r["text"] or ""), "out_tok": r["outputTokens"]} for r in cons])
    res["summary_profile"] = prof
    res["consolidate_profile"] = {"n_all_rows": len(cP), "next_goal_chars_all": stats.describe(cP.chars.values),
                                  "next_goal_chars_sampled": stats.describe(np.array([len(t) for sid in S.index[S.has_consolidate]
                                                                                      for src, t in narr[sid] if src == "consolidate_goal"]))}

    # ---------------------------------------------------------------- claims: per source
    sources = ["stop_summary", "stop_c1_prev_same_agent", "stop_c2_other_agent", "consolidate_goal",
               "consolidate_c1_prev_same_agent", "consolidate_c2_other_agent", "session_goal"]
    claims = {}
    for src in sources:
        c = E[E.source == src]
        a = A[A.source == src] if len(A) else A
        n_s = sum(1 for sid in S.index for s2, _ in narr.get(sid, []) if s2 == src)
        blk = {"n_sessions_with_narration": int(n_s), "n_entity_claims": int(len(c)),
               "entities": entity_block(c, None), "actions": action_block(a) if len(a) else {}}
        aa = a[a.assertive] if len(a) else a
        blk["totals"] = {"assertive_action_claims": int(len(aa)),
                         "assertive_action_status_counts": {k: int(v) for k, v in aa.status.value_counts().items()} if len(aa) else {},
                         "entity_error_only_claims": int(c.error_only.eq(True).sum()),
                         "entity_status_counts_all_types": {k: int(v) for k, v in c.status.value_counts().items()}}
        claims[src] = blk
    res["claims"] = claims

    # claims per 1k chars, own channels
    dens = {}
    for src, chan in (("stop_summary", "stop_summary"), ("consolidate_goal", "consolidate_goal"), ("session_goal", "session_goal")):
        chars = {sid: sum(len(t or "") for s2, t in narr.get(sid, []) if s2 == src) for sid in S.index}
        cnt = E[E.source == src].groupby(["session_id", "type"]).size()
        dd = {}
        sess = [s for s in S.index if chars[s] > 0]
        for typ in ENTITY_TYPES:
            num = [int(cnt.get((s, typ), 0)) for s in sess]
            den = [chars[s] / 1000.0 for s in sess]
            dd[typ] = crate(num, den)
        dens[chan] = dd
    res["claims_per_1k_chars"] = dens

    # ---------------------------------------------------------------- own vs control paired differences (supported rate)
    def per_session_counts(src, typ, field="supported"):
        c = E[(E.source == src) & (E.type == typ)]
        num = c[c[field].astype(bool)].groupby("session_id").size()
        den = c.groupby("session_id").size()
        return num, den

    ctrl = {}
    for chan, c1, c2 in (("stop_summary", "stop_c1_prev_same_agent", "stop_c2_other_agent"),
                         ("consolidate_goal", "consolidate_c1_prev_same_agent", "consolidate_c2_other_agent")):
        blk = {}
        for typ in ENTITY_TYPES:
            no, do = per_session_counts(chan, typ)
            tb = {}
            for cname in (c1, c2, "session_goal"):
                nc, dc = per_session_counts(cname, typ)
                sess = sorted(set(do.index) | set(dc.index))
                tb["own_minus_" + cname] = paired_diff([no.get(s, 0) for s in sess], [do.get(s, 0) for s in sess],
                                                       [nc.get(s, 0) for s in sess], [dc.get(s, 0) for s in sess])
            blk[typ] = tb
        # actions: share of assertive claims "supported", own vs c2
        ab = {}
        for a in ACTIONS:
            tb = {}
            for cname in (c1, c2):
                o = A[(A.source == chan) & (A.action == a) & A.assertive] if len(A) else A
                k = A[(A.source == cname) & (A.action == a) & A.assertive] if len(A) else A
                if len(o) == 0 or len(k) == 0:
                    tb["own_minus_" + cname] = {"diff": None, "n_own": int(len(o)), "n_ctrl": int(len(k))}
                    continue
                no = o[o.status == "supported"].groupby("session_id").size(); do = o.groupby("session_id").size()
                nc = k[k.status == "supported"].groupby("session_id").size(); dc = k.groupby("session_id").size()
                sess = sorted(set(do.index) | set(dc.index))
                tb["own_minus_" + cname] = paired_diff([no.get(s, 0) for s in sess], [do.get(s, 0) for s in sess],
                                                       [nc.get(s, 0) for s in sess], [dc.get(s, 0) for s in sess])
            ab[a] = tb
        blk["actions_supported"] = ab
        ctrl[chan] = blk
    res["own_vs_control"] = ctrl

    # ---------------------------------------------------------------- by model family (stratum), by gui bin, by model_string
    def by_group(col, src, min_sessions=0):
        out = {}
        c_all = E[E.source == src].merge(S[[col]], left_on="session_id", right_index=True)
        a_all = A[A.source == src].merge(S[[col]], left_on="session_id", right_index=True) if len(A) else A
        for k, g in c_all.groupby(col):
            if g.session_id.nunique() < min_sessions:
                continue
            row = {"n_sessions_with_claims": int(g.session_id.nunique()), "n_claims": int(len(g))}
            for typ in ENTITY_TYPES:
                c = g[g.type == typ]
                if len(c) == 0:
                    row[typ] = {"n_claims": 0}
                    continue
                sess = sorted(c.session_id.unique())
                num, den = rates_by_session(c, sess, c.supported, np.ones(len(c), bool))
                row[typ] = {"n_claims": int(len(c)), "supported": crate(num, den)}
            # pooled "string entity" support: url+path+filename+command+quoted
            c = g[g.type.isin(["url", "path", "filename", "command", "quoted"])]
            if len(c):
                sess = sorted(c.session_id.unique())
                num, den = rates_by_session(c, sess, c.supported, np.ones(len(c), bool))
                row["string_entities_pooled"] = crate(num, den)
            if len(a_all):
                aa = a_all[(a_all[col] == k) & a_all.assertive]
                row["actions_assertive"] = {"n": int(len(aa)), "status_counts": {x: int(v) for x, v in aa.status.value_counts().items()}}
            out[str(k)] = row
        return out

    res["by_stratum"] = {src: by_group("stratum", src) for src in ("stop_summary", "consolidate_goal", "stop_c2_other_agent",
                                                                    "consolidate_c2_other_agent")}
    res["by_gui_bin"] = {src: by_group("gui_bin", src) for src in ("stop_summary", "consolidate_goal", "stop_c2_other_agent",
                                                                    "consolidate_c2_other_agent")}
    res["by_model_string_min20"] = {src: by_group("model_string", src, PREREG["min_sessions_per_model_row"])
                                    for src in ("stop_summary", "consolidate_goal")}
    res["gui_bin_session_counts"] = {k: int(v) for k, v in S.gui_bin.value_counts().items()}
    res["gui_bin_by_channel"] = {"has_stop": {k: int(v) for k, v in S[S.has_stop].gui_bin.value_counts().items()},
                                 "has_consolidate": {k: int(v) for k, v in S[S.has_consolidate].gui_bin.value_counts().items()}}

    # ================================================================================================= POST HOC (see POST_HOC)
    ph = {"chain_equality": {str(k): int(v) for k, v in chain_eq.items()}}

    ace = {}
    for chan, flag in (("stop_summary", "has_stop"), ("consolidate_goal", "has_consolidate")):
        base = S[S[flag] & (S.n_shell > 0)]
        own = A[A.source == chan]
        blk = {"n_sessions_channel_with_shell": int(len(base))}
        for a in ACTIONS:
            o = own[own.action == a]
            s_assert = set(o[o.assertive].session_id)
            s_plain = set(o[o.assertive & o.ctx_plain].session_id)
            s_any = set(o.session_id)
            ev = (base["ev_" + a] > 0).values
            g1 = base.index.isin(s_assert)
            g1p = base.index.isin(s_plain)
            g0 = ~base.index.isin(s_any)
            row = {"evidence_given_assertive_claim": wil(int(ev[g1].sum()), int(g1.sum())),
                   "evidence_given_assertive_plain_claim": wil(int(ev[g1p].sum()), int(g1p.sum())),
                   "evidence_given_no_match": wil(int(ev[g0].sum()), int(g0.sum())),
                   "diff_assertive_minus_no_match": prop_diff(ev[g1], ev[g0]),
                   "diff_plain_minus_no_match": prop_diff(ev[g1p], ev[g0])}
            succ = S[S[flag] & (S["evs_" + a] > 0)]
            row["recall_assertive_among_success_evidence_sessions"] = wil(int(succ.index.isin(s_assert).sum()), int(len(succ)))
            row["recall_any_match_among_success_evidence_sessions"] = wil(int(succ.index.isin(s_any).sum()), int(len(succ)))
            blk[a] = row
        ace[chan] = blk
    ph["action_claim_conditioned_evidence"] = ace

    acx = {}
    for chan in ("stop_summary", "consolidate_goal", "stop_c2_other_agent", "consolidate_c2_other_agent"):
        o = A[(A.source == chan) & A.assertive]
        blk = {}
        for a in ACTIONS:
            x = o[o.action == a]
            blk[a] = {"n_assertive": int(len(x)), "n_plain": int(x.ctx_plain.sum()), "n_in_code": int(x.ctx_code.sum()),
                      "n_third_party": int(x.ctx_third.sum()),
                      "status_counts_plain": {k: int(v) for k, v in x[x.ctx_plain].status.value_counts().items()},
                      "status_counts_not_plain": {k: int(v) for k, v in x[~x.ctx_plain].status.value_counts().items()}}
        acx[chan] = blk
    ph["action_claim_context"] = acx

    cos = {}
    for chan, c1 in (("stop_summary", "stop_c1_prev_same_agent"), ("consolidate_goal", "consolidate_c1_prev_same_agent")):
        with_c1 = {sid for sid in S.index if any(s2 == c1 for s2, _ in narr.get(sid, []))}
        k1 = E[E.source == c1]
        keys = set(zip(k1.session_id, k1.type, k1.value))
        own = E[(E.source == chan) & E.session_id.isin(with_c1)].copy()
        own["carried"] = [(s, t, v) in keys for s, t, v in zip(own.session_id, own.type, own.value)]
        own = own.merge(S[["gui_bin"]], left_on="session_id", right_index=True)
        blk = {"n_sessions_with_c1": len(with_c1), "n_sessions_with_claims": int(own.session_id.nunique()), "by_type": {}, "by_gui_bin": {}}

        def split_rates(c):
            if len(c) == 0:
                return {"n_claims": 0}
            sess = sorted(c.session_id.unique())
            num, den = rates_by_session(c, sess, c.carried, np.ones(len(c), bool))
            out = {"n_claims": int(len(c)), "n_carried": int(c.carried.sum()), "carried_share": crate(num, den)}
            for nm, sub in (("carried", c[c.carried]), ("novel", c[~c.carried])):
                if len(sub):
                    ss2 = sorted(sub.session_id.unique())
                    num, den = rates_by_session(sub, ss2, sub.supported, np.ones(len(sub), bool))
                    out["supported_" + nm] = crate(num, den)
            nn, dn = per_s(c[~c.carried]); nc, dc = per_s(c[c.carried])
            sess = sorted(set(dn.index) | set(dc.index))
            out["novel_minus_carried_paired"] = paired_diff([nn.get(s, 0) for s in sess], [dn.get(s, 0) for s in sess],
                                                            [nc.get(s, 0) for s in sess], [dc.get(s, 0) for s in sess])
            return out

        for typ in ENTITY_TYPES:
            blk["by_type"][typ] = split_rates(own[own.type == typ])
        strs = own[own.type.isin(["url", "path", "filename", "command", "quoted"])]
        blk["by_type"]["string_entities_pooled"] = split_rates(strs)
        blk["by_type"]["all_types_pooled"] = split_rates(own)
        for gb, g in strs.groupby("gui_bin"):
            blk["by_gui_bin"][str(gb)] = {"string_entities_pooled": split_rates(g)}
        cos[chan] = blk
    ph["carryover_split"] = cos

    # placeholder summaries (post hoc): exact strings duplicated >= 100 times in the STOP population
    dup = Counter((r["text"] or "").strip() for r in stops)
    ph_strings = {t for t, c in dup.items() if c >= 100}
    rows_ph = [r for r in stops if (r["text"] or "").strip() in ph_strings]
    by_str = {}
    for t in sorted(ph_strings, key=lambda x: -dup[x]):
        ds = sorted(r["created_at"][:10] for r in rows_ph if (r["text"] or "").strip() == t)
        by_str[t[:100]] = {"population_count": int(dup[t]), "first_date": ds[0], "last_date": ds[-1]}
    samp_ph = [s for s in S.index[S.has_stop] if (pairs[s]["text"] or "").strip() in ph_strings]
    n_all = len(S)
    ph["placeholder_summaries"] = {
        "strings": by_str, "population_rows": int(len(rows_ph)), "population_stop_rows": int(len(stops)),
        "sampled_sessions_with_placeholder": int(len(samp_ph)),
        "sampled_entity_claims_from_placeholder_sessions": int(E[(E.source == "stop_summary") & E.session_id.isin(samp_ph)].shape[0]),
        "substantive_stop_summary_coverage": wil(int(S.has_stop.sum()) - len(samp_ph), n_all),
        "any_substantive_narration_coverage": wil(n_all - len(samp_ph), n_all),
        "placeholder_by_stratum": {k: int(v) for k, v in S.loc[samp_ph, "stratum"].value_counts().items()}}
    res["post_hoc"] = ph

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print("wrote", OUT)


def per_s(c):
    """(supported count, claim count) per session for a claim frame."""
    return c[c.supported].groupby("session_id").size(), c.groupby("session_id").size()


def prop_diff(x1, x0, n_boot=stats.N_BOOT, seed=SEED):
    """p(x1) - p(x0) for two disjoint sets of sessions (one 0/1 value per session); independent session bootstrap CI."""
    x1 = np.asarray(x1, float); x0 = np.asarray(x0, float)
    if len(x1) == 0 or len(x0) == 0:
        return {"diff": None, "lo": None, "hi": None, "n1": int(len(x1)), "n0": int(len(x0))}
    rng = np.random.default_rng(seed)
    b1 = x1[rng.integers(0, len(x1), size=(n_boot, len(x1)))].mean(1)
    b0 = x0[rng.integers(0, len(x0), size=(n_boot, len(x0)))].mean(1)
    d = b1 - b0
    return {"diff": float(x1.mean() - x0.mean()), "lo": float(np.quantile(d, 0.025)), "hi": float(np.quantile(d, 0.975)),
            "n1": int(len(x1)), "n0": int(len(x0))}


if __name__ == "__main__":
    main()
