"""Phase C lens `sequences`: structural regularities in agent tool-call sequences, across corpora, scaffolds and models.

Writes RAW COUNTS ONLY to analysis/out/phase_c/sequences.json (interpretation: analysis/notes/sequences.md).
Reads only the IR caches (analysis/cache/<corpus>_<split>.parquet) plus swechat_population / aiv_cu_sessions /
whowhen_labels. cc_local is private: only aggregates leave this script (tool names are folded, mcp tools collapse to
'mcp', shell words outside a fixed public allowlist become 'other'; no paths, args, commands or session ids are written).

What is measured (all definitions, windows and thresholds are in PREREG, fixed before any outcome on the B split):
  ngrams       tool unigram / bigram / trigram shares per group, self-loop share, identical-consecutive-call share,
               conditional entropy H(next tool | tool) with a session bootstrap, longest same-tool run, first call
  shell        first-word ("lead word") distribution, cd-prefix share, consecutive-shell-call lead-word bigrams,
               intra-command segment bigrams (cmd1 && cmd2, cmd1 | cmd2)
  retry        after a result with a failure marker: is one of the next K calls (issued after the failure was visible)
               the same tool with near-identical arguments? Same quantity after a non-failed result (control).
  regularities read-before-edit, exploration before first (deep) file access, test/verify after the last mutation,
               git status/diff before git commit, re-read after edit, harness "file not read" refusals
  rules        mined "always precedes" / "never precedes" / "always followed by" rules among each group's top tools
  integrity    call/result pairing and ordering per group (parser surprises)
  aiv_cu       per-model comparison (models with >= MIN_SESSIONS sessions; others listed as insufficient n)
  whowhen      retry after failed code execution, and where the labelled mistake step sits relative to failures

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_c_sequences [--split B|A]
(--split A was used only to debug the code before the B run; the reported JSON is the B split.)
"""
import argparse
import difflib
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from analysis.lib import stats
from analysis.lib.ir import error_marker

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.normpath(os.path.join(HERE, "..", "cache"))
OUT_DIR = os.path.normpath(os.path.join(HERE, "..", "out", "phase_c"))

# ---------------------------------------------------------------------------------------------------------------------
# PRE-REGISTRATION. Written before any outcome of this lens was computed on the B split. Before writing it I looked only
# at vocabulary/schema: tool names and kind counts per corpus, args key names per tool and format, 20 Codex commands of
# the A split, and the first lines of aiv_cu stderr values (to define the aiv_cu failure markers). The code was debugged
# on the A split (`--split A`); B outcomes were first computed by the final run. Any later change goes to REVISIONS.
# ---------------------------------------------------------------------------------------------------------------------
PREREG = {
    "unit": "session = resampling unit for every CI (stats.cluster_rate, 1000 boots, SEED 20261003). A rate whose "
            "denominator is a call or a stream is a ratio over sessions (num/den summed per session).",
    "min_sessions_for_rate": 30,
    "min_sessions_rule": "a group with fewer than 30 sessions in the denominator gets counts only (no rate, no CI) and "
                         "is listed under insufficient_n. Applied to every group (scaffold, model, stratum), not only aiv_cu.",
    "split": "Phase B split (analysis/cache/<corpus>_B.parquet) for every corpus.",
    "streams": "calls are ordered by IR seq within a STREAM. stream = (session, main agent) or (session, one subagent): "
                "is_subagent True -> key agent_id, else parent_call_id, else 'sub'. Corpora without subagents have one "
                "stream per session. An OpenCode child session / Codex sub-agent rollout is a subagent stream.",
    "groups": {
        "swechat": "transcript format from swechat_population.format (claude_code, opencode, codex, gemini, cursor); "
                   "plus <format>/main and <format>/sub stream subsets for formats that have subagent streams",
        "cc_local": "all, main, sub (sub = Task/Agent subagents and workflow agents)",
        "aiv_cc": "all (one Opus 4.5 agent; session = run)",
        "aiv_cu": "all; stratum:<stratum>; model:<aiv_cu_sessions.model_string>",
        "whowhen": "Algorithm-Generated, Hand-Crafted",
    },
    "token": "sequence token per call = IR tool, except: Codex write_stdin (tool_raw) -> 'shell_poll'; aiv_cu gui -> "
             "'gui:<extra.action>'; aiv_cu bash restart -> 'shell_restart'; cc_local tool names starting 'mcp__' -> 'mcp' "
             "(privacy); public corpora keep full lowercased mcp tool names.",
    "failure": {
        "cc_like": "swechat, cc_local, aiv_cc, whowhen: ir.error_marker(result text) in {cc_interrupt_reject, "
                   "cc_permission_denied} -> 'reject'; else native_error True or exit_code (structured) not in {null, 0} or "
                   "any other error_marker -> 'fail'; else 'ok'. A call with no result -> 'none'.",
        "aiv_cu": "no native flag exists and stderr is a channel, not a failure flag. 'fail' iff stderr matches one of "
                  "AIVCU_FAIL_RX (harness timeout, 'bash has exited with returncode N>0', coordinate service unavailable, "
                  "GUI argument validation, python traceback, 'command not found'); else 'ok'. stderr present but no "
                  "marker (git progress, curl meters) counts as 'ok'.",
    },
    "retry": {
        "K": 3,
        "K_immediate": 1,
        "window": "the first K calls of the same stream whose seq is greater than the anchor's RESULT seq (calls issued "
                  "after the failure was visible; parallel siblings issued before the result are excluded)",
        "anchor": "a call whose result class is 'fail' (failure anchor) or 'ok' (control anchor). 'reject' and 'none' "
                  "anchors are counted but not classified.",
        "signature": "shell: the command string; every other tool (incl. Codex polls): the args VALUES in key-sorted "
                     "order joined by U+001F (JSON keys dropped). File tools (read/edit/write) with paths on both calls: "
                     "different path sets -> same_tool_diff regardless of similarity.",
        "similarity": "difflib.SequenceMatcher(None, a[:500], b[:500], autojunk=False).ratio(), pruned by "
                      "real_quick_ratio/quick_ratio < 0.8",
        "classes": "exact (same token, identical full signature) > near (same token, similarity >= 0.8) > same_tool_diff "
                   "(same token, < 0.8) > no_same_tool (window has calls, none with the same token) > stream_end (no call "
                   "after the result). The best class over the window is taken. retry = exact or near.",
        "near_threshold": 0.8,
        "loop": "retry loop = a failure anchor that is not itself a retry of an earlier failure, followed through its first "
                "retry (exact/near) while that retry also fails; loop length = number of failed attempts in the chain.",
    },
    "regularities": {
        "paths": "file path of read/edit/write calls: args keys file_path, filePath, path, absolute_path, notebook_path, "
                 "target_file; apply_patch input/patchText lines '*** (Update|Add|Delete) File: <p>'. Normalized: '\\' -> "
                 "'/', strip leading './', collapse '//'. Two paths match if equal or one ends with '/' + the other.",
        "R1_read_before_edit": "den: calls with token 'edit' and >= 1 path. strict: every path was the path of an earlier "
                               "'read' call in the same stream. strict_rw: earlier read OR write of that path. broad: every "
                               "path's basename occurs in the args/command of some earlier call (any tool) of the stream. "
                               "session_strict: earlier read in any stream of the session (session seq order).",
        "R1b_not_read_refusal": "edit/write result text (lowercased) contains any of NOT_READ_PHRASES; crossed with strict.",
        "R2_explore_first": "per stream with >= 1 read/edit/write path call: an exploration call (token glob/grep/ls, or a "
                            "shell segment whose word is in EXPLORE_WORDS) occurs before the first such call. deep variant: "
                            "root = longest common directory prefix of all file paths of the stream (streams with >= 2 distinct "
                            "paths); deep call = first file call whose path has >= 2 directory components below root.",
        "R3_verify_after_mutation": "per stream with >= 1 mutation call (token edit or write): test run (TEST_RX on the "
                                    "quote-stripped shell command) after the first mutation; after the last mutation; "
                                    "verify (TEST_RX or BUILD_RX) after the last mutation; any test anywhere. per mutation call: "
                                    "a test run among the next 10 calls. last_test_failed: among streams with a test after the "
                                    "last mutation, the last test call of the stream has result class 'fail'.",
        "R4_git_commit": "den: shell calls with a segment 'git commit'. status_or_diff_before: a 'git status' or 'git diff' "
                         "segment earlier in the same command or in any shell call since the previous commit call of the "
                         "stream (or stream start). add_before: same window with 'git add' or the commit segment has -a/--all "
                         "(incl. -am). log_after: 'git log'/'git show' within the next 5 calls. push_after: 'git push' anywhere "
                         "later in the stream (or later in the same command). commit_failed: result class 'fail'.",
        "R5_reread_after_edit": "per edit call with a path: a 'read' of the same path among the next 5 calls of the stream.",
    },
    "rules_mining": {
        "tools": "the 12 most frequent tokens of the group",
        "precedes": "for each call of token X at index i: Y precedes iff some call of token Y has index < i (Y != X)",
        "follows": "Y follows iff some call of token Y has index > i",
        "always": "rate >= 0.95 and session-clustered lower CI >= 0.90",
        "never": "rate <= 0.05 and session-clustered upper CI <= 0.10",
        "min_support": "X calls >= 200 and >= 30 sessions with an X call",
    },
    "ngram_report_top": {"unigram": 12, "bigram": 15, "trigram": 10, "first_call": 8, "shell_word": 20,
                         "shell_bigram": 20, "segment_bigram": 20, "per_model_bigram": 5},
    "entropy": "H(next | current) = H(bigram) - H(first element), bits, pooled over the group's bigrams; session "
               "bootstrap (1000) for the CI.",
    "shell_parse": "heredoc bodies removed; backslash-newline continuations joined; single- and double-quoted strings "
                   "emptied (may span lines); '#' comments removed; split into segments on &&, ||, ;, "
                   "|, newline (naive: no subshell/escape handling). Segment word: skip VAR=val assignments and the "
                   "prefixes in PREFIX_SKIP (and 'timeout N'); basename of the first token, lowercased; python[0-9.]* -> "
                   "python, pip3 -> pip. Words in SUBCMD_WORDS get their first non-option argument appended ('git commit', "
                   "'npm run'; python -> 'python -m <mod>' / 'python -c' / 'python <script>'); an argument not matching "
                   "[a-z0-9][a-z0-9:._-]* becomes '<arg>'. lead word of a call = first segment word not in NAV_WORDS "
                   "(cd, pushd, export, source, set, ...), else the first segment word. cd_prefix = first segment word "
                   "is 'cd'. cc_local: words not in PUBLIC_WORDS (the base word must be in the allowlist) -> 'other'.",
    "whowhen": "Algorithm-Generated failures = code_exec results with exitcode != 0. mistake co-location: the labelled "
               "mistake_step equals the step of a call whose result failed (call step) or of the failed result itself; "
               "expected under a uniform-step null = (number of such steps) / history_len, summed over sessions.",
}

AIVCU_FAIL_RX = [
    ("timeout", re.compile(r"^timed out:")),
    ("nonzero_returncode", re.compile(r"bash has exited with returncode [1-9]\d*")),
    ("coords_unavailable", re.compile(r"^Unable to get coordinates")),
    ("gui_validation", re.compile(r"(must be a non-negative int|is not accepted for|is required for|^Invalid action|"
                                  r"is too long\.|No such key name|Invalid key sequence|^Session has not started)")),
    ("python_traceback", re.compile(r"(?m)^Traceback \(most recent call last\)")),
    ("command_not_found", re.compile(r"command not found")),
]
NOT_READ_PHRASES = ("has not been read yet", "read it first", "must read", "before editing", "before overwriting")
EXPLORE_WORDS = {"ls", "find", "tree", "fd", "fdfind", "rg", "grep", "egrep", "ag", "git ls-files", "git grep", "du",
                 "locate", "dir"}
NAV_WORDS = {"cd", "pushd", "popd", "export", "source", ".", "set", "unset", "alias", "true", ":", "shopt", "ulimit"}
PREFIX_SKIP = {"sudo", "time", "nohup", "env", "exec", "command", "builtin", "then", "do", "else", "if", "!", "{", "(",
               "while", "until", "elif"}
SUBCMD_WORDS = {"git", "gh", "npm", "pnpm", "yarn", "bun", "cargo", "go", "docker", "uv", "pip", "kubectl", "poetry",
                "npx", "bunx", "dotnet", "make", "deno", "brew", "apt", "apt-get", "conda", "mvn", "gradle", "python",
                "node", "pytest", "rails", "bundle", "composer", "terraform", "helm", "flutter", "swift", "mix", "just",
                "systemctl", "pm2", "aws", "gcloud", "az", "vercel", "supabase", "firebase", "wrangler", "docker-compose"}
PUBLIC_WORDS = {  # cc_local allowlist: generic command names only; anything else is reported as 'other'
    "ls", "cd", "cat", "head", "tail", "grep", "rg", "find", "sed", "awk", "echo", "printf", "pwd", "mkdir", "rm", "cp",
    "mv", "touch", "chmod", "wc", "sort", "uniq", "cut", "tr", "xargs", "tee", "diff", "curl", "wget", "tar", "unzip",
    "zip", "which", "where", "whoami", "date", "sleep", "kill", "ps", "env", "export", "source", "test", "[", "true",
    "false", "exit", "for", "while", "if", "case", "set", "jq", "python", "pip", "node", "npm", "npx", "pnpm", "yarn",
    "bun", "git", "gh", "make", "cargo", "go", "docker", "uv", "pytest", "tsc", "eslint", "ruff", "mypy", "black",
    "prettier", "powershell", "pwsh", "cmd", "bash", "sh", "wsl", "nvidia-smi", "tasklist", "taskkill", "powercfg",
    "stat", "file", "du", "df", "tree", "ln", "basename", "dirname", "realpath", "readlink", "nl", "less", "more",
    "column", "base64", "md5sum", "sha256sum", "openssl", "ssh", "scp", "rsync", "timeout", "wait", "read", "local",
    "return", "function", "trap", "nproc", "free", "uname", "hostname", "type", "fd", "fdfind", "rmdir", "clear",
    "start", "explorer", "code", "conda", "java", "javac", "dotnet", "rustc", "gcc", "g++", "clang", "cmake", "ffmpeg",
    "sqlite3", "psql", "redis-cli", "kubectl", "terraform", "aws", "gcloud", "az", "brew", "apt", "apt-get", "choco",
    "winget", "scoop", "icacls", "attrib", "robocopy", "xcopy", "copy", "del", "move", "type", "set", "setx", "reg",
    "netstat", "ping", "ipconfig", "tasklist", "wmic", "sc", "schtasks", "certutil", "findstr", "more", "fc", "comp",
}
TEST_RX = re.compile(
    r"(\b(pytest|py\.test|nosetests|tox|nox)\b|python[0-9.]*\s+-m\s+(pytest|unittest)|\b(npm|pnpm|yarn|bun)\s+(run\s+)?"
    r"test|\b(jest|vitest|mocha|karma|ava)\b|playwright\s+test|cypress\s+run|\bgo\s+test\b|\bcargo\s+(test|nextest)\b|"
    r"\b(mvn|mvnw|gradle|gradlew)\b[^\n]*\btest\b|\bdotnet\s+test\b|\b(rspec|phpunit)\b|\bmake\s+(test|check)\b|\bctest\b|"
    r"\bdeno\s+test\b|\bswift\s+test\b|\bmix\s+test\b|\bflutter\s+test\b|\bbazel\s+test\b|\bjust\s+test\b)")
BUILD_RX = re.compile(
    r"(\b(tsc|eslint|ruff|mypy|pyright|flake8|pylint|biome|golangci-lint)\b|black\s+--check|prettier\s+--check|"
    r"\bgo\s+(vet|build)\b|\bcargo\s+(build|check|clippy)\b|\b(npm|pnpm|yarn|bun)\s+(run\s+)?(build|lint|typecheck|"
    r"type-check|check)\b|\bmake\b|\b(gradle|gradlew)\b[^\n]*\bbuild\b|\b(mvn|mvnw)\b[^\n]*\b(compile|package|verify)\b|"
    r"\bdotnet\s+build\b|\bswift\s+build\b)")
PATH_KEYS = ("file_path", "filePath", "path", "absolute_path", "notebook_path", "target_file")
PATCH_RX = re.compile(r"(?m)^\*\*\* (?:Update|Add|Delete) File: (.+?)\s*$")
HEREDOC_RX = re.compile(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?[^\n]*\n.*?\n\s*\1\s*(?=\n|$)", re.S)
SQ_RX = re.compile(r"'[^']*'")  # quoted strings may span lines (python -c "...", multi-line messages)
DQ_RX = re.compile(r'"(?:[^"\\]|\\.)*"')
CONT_RX = re.compile(r"\\\r?\n")  # backslash line continuation
COMMENT_RX = re.compile(r"(?m)(^|\s)#[^\n]*")  # shell comments (after quotes are emptied)
SEG_RX = re.compile(r"\s*(?:&&|\|\||;|\||\n)\s*")
ARG_OK = re.compile(r"^[a-z0-9][a-z0-9:._-]*$")
ENV_RX = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

REVISIONS = [  # before/after/reason for every definition change; 'debug-A' = found on the A split before any B run
    {"stage": "debug-A", "what": "shell parse",
     "before": "quoted strings could not span lines; no comment or line-continuation handling",
     "after": "backslash-newline continuations joined; single/double-quoted strings may span lines; '#' comments "
              "(at line start or after whitespace, after quotes are emptied) removed",
     "reason": "A-split debug output showed '#', '--env_vars', 'print(f', 'import' as segment words"},
    {"stage": "after-B-run-1", "what": "R1 session_strict",
     "before": "pre-registered in PREREG.regularities.R1_read_before_edit but not implemented in run 1",
     "after": "implemented exactly as pre-registered (session_read_before_edit); no definition changed",
     "reason": "omission noticed while writing the notes"},
    {"stage": "debug-A", "what": "retry signature",
     "before": "non-shell signature = full args JSON string; near = char similarity >= 0.8, no path condition",
     "after": "non-shell signature = args values only (keys dropped); for file tools a different path set is never a retry",
     "reason": "A-split control (after successful calls) had 'near' = 0.27 of anchors, driven by shared JSON key names and "
               "shared path prefixes (reading c.py then d.py in one directory counted as a near-identical retry)"},
]

POSTHOC = [  # added after the first B run was read; everything here is exploratory and needs a holdout
    "rules.posthoc_conditional_rules, rules.posthoc_n_never_rules*, rules.rules[].posthoc_x_calls_in_streams_with_y: "
    "most unconditional 'never' rules "
    "were tools absent from the stream, so the same thresholds are applied conditional on Y occurring in the stream",
    "integrity.<corpus>.all.results_before_their_call_detail: 57 swechat results preceded their call in file order; "
    "timestamps, seq gap and tools of those cases",
    "aiv_cu_models.posthoc_session_month_range_per_model: model is confounded with calendar period",
    "integrity.<corpus>.all.n_sessions_in_split / n_sessions_with_calls (descriptive)",
    "retry.posthoc_edit_read_gate: exact retry of failed edits was much higher than for other tools; split by the "
    "harness 'not read' refusal and whether a read of the same path sits between failure and retry",
]

MIN_S = PREREG["min_sessions_for_rate"]
K = PREREG["retry"]["K"]
NEAR = PREREG["retry"]["near_threshold"]
TOP = PREREG["ngram_report_top"]
MUTATION_TOKS = {"edit", "write", "notebookedit"}
FILE_TOKS = {"read", "edit", "write", "notebookedit"}
EXPLORE_TOKS = {"glob", "grep", "ls"}


# ------------------------------------------------------------------------------------------------ small helpers
def cr(num, den):
    """cluster_rate rounded; None-rate when too few sessions."""
    num = np.asarray(num, float)
    den = np.asarray(den, float)
    n_s = int((den > 0).sum())
    if n_s < MIN_S:
        return {"rate": None, "lo": None, "hi": None, "n_sessions": n_s, "num": float(num[den > 0].sum()),
                "den": float(den.sum()), "insufficient_n": True}
    r = stats.cluster_rate(num, den)
    return {k: (round(v, 5) if isinstance(v, float) and k in ("rate", "lo", "hi") else v) for k, v in r.items()}


def wil(k, n):
    p, lo, hi = stats.wilson(k, n)
    if p is None:
        return {"k": k, "n": n, "rate": None}
    return {"k": int(k), "n": int(n), "rate": round(p, 5), "lo": round(lo, 5), "hi": round(hi, 5)}


def cluster_diff(num_a, den_a, num_b, den_b, n_boot=stats.N_BOOT, seed=stats.SEED):
    """rate_a - rate_b with a joint session bootstrap (both measured on the same sessions)."""
    na, da, nb, db = (np.asarray(x, float) for x in (num_a, den_a, num_b, den_b))
    keep = (da > 0) & (db > 0)
    na, da, nb, db = na[keep], da[keep], nb[keep], db[keep]
    n = len(da)
    if n < MIN_S:
        return {"diff": None, "n_sessions": int(n), "insufficient_n": True}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    b = na[idx].sum(1) / da[idx].sum(1) - nb[idx].sum(1) / db[idx].sum(1)
    return {"diff": round(float(na.sum() / da.sum() - nb.sum() / db.sum()), 5), "lo": round(float(np.quantile(b, .025)), 5),
            "hi": round(float(np.quantile(b, .975)), 5), "n_sessions": int(n)}


def norm_path(p):
    if not isinstance(p, str) or not p.strip():
        return None
    p = p.strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    p = re.sub(r"/{2,}", "/", p)
    return p.rstrip("/") or None


def path_match(a, b):
    return a == b or a.endswith("/" + b) or b.endswith("/" + a)


def call_paths(tok, args_str):
    if tok not in FILE_TOKS or not isinstance(args_str, str):
        return []
    try:
        d = json.loads(args_str)
    except Exception:
        return []
    out = []
    if isinstance(d, dict):
        for k in PATH_KEYS:
            v = d.get(k)
            if isinstance(v, str):
                q = norm_path(v)
                if q:
                    out.append(q)
                break
        if not out:
            for k in ("input", "patchText", "patch"):
                v = d.get(k)
                if isinstance(v, str):
                    out = [q for q in (norm_path(m) for m in PATCH_RX.findall(v)) if q]
                    if out:
                        break
    return list(dict.fromkeys(out))


def strip_quotes(cmd):
    s = HEREDOC_RX.sub(" ", cmd)
    s = CONT_RX.sub(" ", s)
    s = SQ_RX.sub("''", s)
    s = DQ_RX.sub('""', s)
    s = COMMENT_RX.sub(" ", s)
    return s


def seg_word(seg):
    toks = seg.strip().split()
    i = 0
    while i < len(toks):
        t = toks[i].strip("'\"()`{}")
        if not t or ENV_RX.match(t) or t in PREFIX_SKIP:
            i += 1
            continue
        if t == "timeout" and i + 1 < len(toks) and re.match(r"^-?\d", toks[i + 1]):
            i += 2
            continue
        break
    if i >= len(toks):
        return None, []
    w = toks[i].strip("'\"()`{}").replace("\\", "/").rsplit("/", 1)[-1].lower()
    w = re.sub(r"\.exe$", "", w)
    if re.match(r"^python[0-9.]*$", w):
        w = "python"
    elif w == "pip3":
        w = "pip"
    rest = toks[i + 1:]
    if not w:
        return None, rest
    if w in SUBCMD_WORDS:
        if w == "python":
            if rest and rest[0] == "-m" and len(rest) > 1:
                m = rest[1].lower()
                return "python -m " + (m if ARG_OK.match(m) else "<arg>"), rest
            if rest and rest[0] == "-c":
                return "python -c", rest
            if rest and rest[0] in ("-", "<<", "-u"):
                return "python", rest
            return ("python <script>" if rest else "python"), rest
        j = 0
        while j < len(rest):
            a = rest[j]
            if w == "git" and a in ("-C", "-c", "--git-dir", "--work-tree") and j + 1 < len(rest):
                j += 2
                continue
            if a.startswith("-"):
                j += 1
                continue
            break
        if j < len(rest):
            sub = rest[j].strip("'\"").lower()
            return w + " " + (sub if ARG_OK.match(sub) else "<arg>"), rest[j + 1:]
    return w, rest


def parse_shell(cmd):
    """-> (segments [(word, rest_tokens)], quote-stripped string)."""
    if not isinstance(cmd, str) or not cmd.strip():
        return [], ""
    s = strip_quotes(cmd)
    segs = []
    for part in SEG_RX.split(s):
        if not part.strip():
            continue
        w, rest = seg_word(part)
        if w:
            segs.append((w, rest))
    return segs, s


def lead_word(segs):
    for w, _ in segs:
        if w not in NAV_WORDS:
            return w
    return segs[0][0] if segs else None


def private_word(w):
    if w is None:
        return None
    base = w.split(" ", 1)[0]
    if base not in PUBLIC_WORDS:
        return "other"
    if " " in w:
        sub = w.split(" ", 1)[1]
        if base == "python":
            return w if sub in ("-c", "<script>") or sub.startswith("-m ") and sub[3:] in {"pytest", "pip", "venv", "http.server", "json.tool", "unittest"} else "python -m other"
        if base == "git" or base in ("npm", "pnpm", "yarn", "uv", "pip", "cargo", "go", "docker", "gh"):
            return w if re.match(r"^[a-z-]{2,15}$", sub) else base + " other"
        return base
    return w


def make_sig(tok, cmd, args):
    """Retry signature: shell -> command string; else the args VALUES in key-sorted order joined by U+001F (keys dropped,
    so shared JSON key names do not count as similarity). Unparseable args -> the raw string."""
    if tok == "shell" and isinstance(cmd, str):
        return cmd
    if not isinstance(args, str):
        return ""
    try:
        d = json.loads(args)
    except Exception:
        return args
    if isinstance(d, dict):
        return "".join(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, sort_keys=True)
                            for _, v in sorted(d.items(), key=lambda kv: str(kv[0])))
    return args


def similarity(a, b):
    a, b = a[:500], b[:500]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    if sm.real_quick_ratio() < NEAR or sm.quick_ratio() < NEAR:
        return 0.0
    return sm.ratio()


def entropy_bits(counts):
    c = np.asarray(counts, float)
    c = c[c > 0]
    if c.sum() == 0:
        return 0.0
    p = c / c.sum()
    return float(-(p * np.log2(p)).sum())


# ------------------------------------------------------------------------------------------------ loading
def classify_cc(native_error, exit_code, text):
    m = error_marker(text) if isinstance(text, str) else None
    if m in ("cc_interrupt_reject", "cc_permission_denied"):
        return "reject", m
    ne = bool(native_error) if native_error is not None and not pd.isna(native_error) else False
    ec = None if exit_code is None or pd.isna(exit_code) else int(exit_code)
    if ne or (ec is not None and ec != 0) or m is not None:
        return "fail", m
    return "ok", m


def classify_aivcu(stderr):
    if not isinstance(stderr, str) or not stderr:
        return "ok", None
    for name, rx in AIVCU_FAIL_RX:
        if rx.search(stderr):
            return "fail", name
    return "ok", None


def load_results(corpus, split):
    """Stream the result rows (text read batch by batch, never all at once) -> small frame with failure class."""
    pf = pq.ParquetFile(os.path.join(CACHE, f"{corpus}_{split}.parquet"))
    cols = ["session_id", "seq", "kind", "call_id", "native_error", "exit_code", "text", "stderr", "tool", "ts"]
    out = []
    for b in pf.iter_batches(batch_size=20000, columns=cols):
        d = b.to_pandas()
        d = d[d["kind"] == "result"]
        if d.empty:
            continue
        cls, mk, nr = [], [], []
        if corpus == "aiv_cu":
            for s in d["stderr"]:
                c, m = classify_aivcu(s)
                cls.append(c)
                mk.append(m)
                nr.append(False)
        else:
            for ne, ec, tx in zip(d["native_error"], d["exit_code"], d["text"]):
                c, m = classify_cc(ne, ec, tx)
                cls.append(c)
                mk.append(m)
                low = tx[:400].lower() if isinstance(tx, str) else ""
                nr.append(any(p in low for p in NOT_READ_PHRASES))
        out.append(pd.DataFrame({"session_id": d["session_id"].astype(str).values, "res_seq": d["seq"].values,
                                 "call_id": d["call_id"].astype("string").values, "res_class": cls, "res_marker": mk,
                                 "not_read": nr, "res_stderr_present": d["stderr"].notna().values,
                                 "res_ts": d["ts"].astype("string").values}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def load_corpus(corpus, split):
    cols = ["session_id", "stratum", "seq", "kind", "tool", "tool_raw", "call_id", "args", "command", "is_subagent",
            "agent_id", "parent_call_id", "api_msg_id", "extra", "ts"]
    calls = pd.read_parquet(os.path.join(CACHE, f"{corpus}_{split}.parquet"), columns=cols,
                            filters=[("kind", "==", "call")])
    calls["session_id"] = calls["session_id"].astype(str)
    res = load_results(corpus, split)
    n_results = len(res)
    # integrity: results per call id
    dup_call_ids = int(calls.duplicated(["session_id", "call_id"]).sum())
    first_res = res.sort_values("res_seq").drop_duplicates(["session_id", "call_id"], keep="first")
    multi_res = int(res.duplicated(["session_id", "call_id"]).sum())
    calls = calls.merge(first_res, on=["session_id", "call_id"], how="left")
    orphan_results = int(len(first_res) - first_res.merge(calls[["session_id", "call_id"]].drop_duplicates(),
                                                          on=["session_id", "call_id"]).shape[0])
    calls["res_class"] = calls["res_class"].fillna("none")
    calls["not_read"] = calls["not_read"].fillna(False).astype(bool)
    # tokens
    tool = calls["tool"].astype("string").fillna("unknown").astype(str)
    raw = calls["tool_raw"].astype("string").fillna("").astype(str)
    tok = tool.copy()
    if corpus == "swechat":
        tok = tok.where(raw != "write_stdin", "shell_poll")
    if corpus == "cc_local":
        tok = tok.where(~tok.str.startswith("mcp__"), "mcp")
    if corpus == "aiv_cu":
        acts = [json.loads(e).get("action") if isinstance(e, str) else None for e in calls["extra"]]
        calls["action"] = acts
        tok = pd.Series([("gui:" + str(a)) if t == "gui" else ("shell_restart" if t == "shell" and a == "restart" else t)
                         for t, a in zip(tok, acts)], index=calls.index)
    calls["tok"] = tok.values
    # stream
    sub = calls["is_subagent"].fillna(False).astype(bool)
    key = calls["agent_id"].astype("string").fillna(calls["parent_call_id"].astype("string")).fillna("sub").astype(str)
    calls["is_main"] = ~sub
    calls["stream"] = np.where(sub, calls["session_id"] + "|S|" + key, calls["session_id"] + "|M")
    calls["res_after_call"] = calls["res_seq"].isna() | (calls["res_seq"] > calls["seq"])
    inv = calls[~calls["res_after_call"]]
    tc_ = pd.to_datetime(inv["ts"], utc=True, errors="coerce", format="ISO8601")
    tr_ = pd.to_datetime(inv["res_ts"], utc=True, errors="coerce", format="ISO8601")
    inv_detail = {"POSTHOC": "added after the first B run showed results_before_their_call > 0",
                  "n": int(len(inv)), "n_sessions": int(inv["session_id"].nunique()),
                  "main_stream": int(inv["is_main"].sum()),
                  "result_ts_ge_call_ts": int((tr_ >= tc_).sum()), "ts_missing": int((tc_.isna() | tr_.isna()).sum()),
                  "result_minus_call_ms": stats.describe(((tr_ - tc_).dt.total_seconds() * 1000).dropna().values),
                  "seq_gap_call_minus_result": stats.describe((inv["seq"] - inv["res_seq"]).astype(float).values),
                  "by_tool": {k: int(v) for k, v in inv["tok"].value_counts().items()}} if len(inv) else {"n": 0}
    n_split_sessions = int(pd.read_parquet(os.path.join(CACHE, f"{corpus}_{split}.parquet"), columns=["session_id"])
                           ["session_id"].nunique())
    integ = {"n_sessions_in_split": n_split_sessions, "n_sessions_with_calls": int(calls["session_id"].nunique()),
             "n_calls": int(len(calls)), "n_results": int(n_results), "duplicate_call_ids_in_session": dup_call_ids,
             "results_before_their_call_detail": inv_detail,
             "results_sharing_a_call_id_beyond_first": multi_res, "results_without_call": orphan_results,
             "calls_without_result": int((calls["res_class"] == "none").sum()),
             "results_before_their_call": int((~calls["res_after_call"]).sum())}
    calls = calls.drop(columns=["extra"])
    return calls, integ


def session_read_before_edit(calls):
    """PREREG R1 session_strict: for each edit call with a path, every path was read by a 'read' call of ANY stream of the
    session with a smaller seq (session seq order). Returns a boolean array aligned with calls (False for non-edits)."""
    flag = np.zeros(len(calls), dtype=bool)
    sub = calls[calls["tok"].isin(["read", "edit"])]
    for sid, g in sub.sort_values(["session_id", "seq"]).groupby("session_id", sort=False):
        reads = []
        for idx, t, a in zip(g.index, g["tok"], g["args"]):
            ps = call_paths(t, a)
            if t == "read":
                reads.extend(ps)
            elif ps:
                flag[idx] = all(any(path_match(p, q) for q in reads) for p in ps)
    return flag


# ------------------------------------------------------------------------------------------------ per-stream analysis
def analyse_stream(st, corpus, private):
    """st: calls of one stream sorted by seq. Returns dict of per-stream features (counters and tallies)."""
    toks = st["tok"].tolist()
    n = len(toks)
    seqs = st["seq"].to_numpy()
    res_seq = pd.to_numeric(st["res_seq"], errors="coerce").astype("float64").to_numpy()
    rcls = st["res_class"].tolist()
    cmds = st["command"].tolist()
    argss = st["args"].tolist()
    f = {"n": n}
    f["uni"] = Counter(toks)
    f["bi"] = Counter(zip(toks, toks[1:]))
    f["tri"] = Counter(zip(toks, toks[1:], toks[2:]))
    f["first"] = toks[0] if n else None
    # signatures (values only, see PREREG retry.signature) and file targets
    paths = [call_paths(t, a) for t, a in zip(toks, argss)]
    sigs = [make_sig(t, c, a) for t, c, a in zip(toks, cmds, argss)]

    def is_retry(i, j):
        """-> 'exact' | 'near' | 'same_tool_diff' for two calls with the same token."""
        if sigs[j] == sigs[i]:
            return "exact"
        if paths[i] and paths[j] and not (all(any(path_match(p, q) for q in paths[j]) for p in paths[i])
                                          and all(any(path_match(p, q) for q in paths[i]) for p in paths[j])):
            return "same_tool_diff"
        return "near" if similarity(sigs[i], sigs[j]) >= NEAR else "same_tool_diff"
    f["ident_consec"] = sum(1 for i in range(1, n) if toks[i] == toks[i - 1] and sigs[i] == sigs[i - 1])
    f["pairs"] = max(n - 1, 0)
    # longest run
    mr, cur = (1 if n else 0), 1
    for i in range(1, n):
        cur = cur + 1 if toks[i] == toks[i - 1] else 1
        mr = max(mr, cur)
    f["max_run"] = mr
    # ---- shell parsing
    shell_idx = [i for i, t in enumerate(toks) if t == "shell" and isinstance(cmds[i], str)]
    segs_by_i, lw_by_i, stripped_by_i = {}, {}, {}
    for i in shell_idx:
        segs, s = parse_shell(cmds[i])
        if private:
            segs = [(private_word(w), r) for w, r in segs]
        segs_by_i[i] = segs
        stripped_by_i[i] = s.lower()
        lw_by_i[i] = lead_word(segs)
    f["shell_n"] = len(shell_idx)
    f["shell_parsed"] = sum(1 for i in shell_idx if segs_by_i[i])
    f["cd_prefix"] = sum(1 for i in shell_idx if segs_by_i[i] and segs_by_i[i][0][0] == "cd")
    f["multi_seg"] = sum(1 for i in shell_idx if len(segs_by_i[i]) > 1)
    f["lead"] = Counter(lw_by_i[i] for i in shell_idx if lw_by_i[i])
    lws = [lw_by_i[i] for i in shell_idx if lw_by_i[i]]
    f["lead_bi"] = Counter(zip(lws, lws[1:]))
    f["seg_bi"] = Counter()
    for i in shell_idx:
        ws = [w for w, _ in segs_by_i[i]]
        f["seg_bi"].update(zip(ws, ws[1:]))
    is_test = {i: bool(TEST_RX.search(stripped_by_i[i])) for i in shell_idx}
    is_build = {i: bool(BUILD_RX.search(stripped_by_i[i])) for i in shell_idx}
    # ---- retry
    rt = Counter()
    retry_of = {}  # anchor index -> index of first retry
    for i in range(n):
        c = rcls[i]
        rt["anchor_" + c] += 1
        if c not in ("fail", "ok"):
            continue
        rs = res_seq[i]
        win = [j for j in range(i + 1, n) if seqs[j] > rs][:K]
        if not win:
            cls = "stream_end"
            imm = "stream_end"
        else:
            best = "no_same_tool"
            first_retry = None
            for j in win:
                if toks[j] != toks[i]:
                    continue
                b = is_retry(i, j)
                if b in ("exact", "near") and first_retry is None:
                    first_retry = j
                order = ["exact", "near", "same_tool_diff", "no_same_tool"]
                if order.index(b) < order.index(best):
                    best = b
            cls = best
            j0 = win[0]
            if toks[j0] == toks[i] and is_retry(i, j0) in ("exact", "near"):
                imm = "retry"
            else:
                imm = "other"
            if first_retry is not None:
                retry_of[i] = first_retry
        rt[f"{c}_{cls}"] += 1
        rt[f"{c}_imm_{imm}"] += 1
        if len(win) < K and win:
            rt[f"{c}_window_truncated"] += 1
        if c == "fail" and cls in ("exact", "near"):
            j = retry_of[i]
            rt["fail_retry_result_" + rcls[j]] += 1
            rt[f"fail_retry_{cls}_tok:{toks[i]}"] += 1
        if c == "fail":
            rt[f"fail_tok:{toks[i]}"] += 1
        if c == "fail" and toks[i] == "edit":  # POSTHOC: the read-gate path (edit refused -> read -> same edit)
            nr = bool(st["not_read"].iat[i])
            rt[f"edit_fail_notread{int(nr)}"] += 1
            if cls in ("exact", "near"):
                j = retry_of[i]
                rt[f"edit_fail_notread{int(nr)}_retry"] += 1
                between = [k for k in range(i + 1, j) if toks[k] == "read" and paths[k] and paths[i]
                           and any(path_match(a, b) for a in paths[i] for b in paths[k])]
                rt[f"edit_fail_notread{int(nr)}_retry_read_between"] += bool(between)
    # retry loops
    retried_targets = set(retry_of.values())
    loops = []
    for i in range(n):
        if rcls[i] != "fail" or i in retried_targets:
            continue
        length, j = 1, i
        while j in retry_of and rcls[retry_of[j]] == "fail":
            j = retry_of[j]
            length += 1
        ended = "retry_ok" if (j in retry_of and rcls[retry_of[j]] == "ok") else ("retry_other" if j in retry_of else "no_retry")
        loops.append((length, ended))
    f["retry"] = rt
    f["loops"] = loops
    # ---- regularities
    reg = Counter()
    read_paths, written_paths = [], []
    blobs = [(a if isinstance(a, str) else "") + " " + (c if isinstance(c, str) else "") for a, c in zip(argss, cmds)]
    first_seen = {}  # basename -> first call index whose args/command contains it (broad rule)
    for b in {os.path.basename(p) for i in range(n) if toks[i] == "edit" for p in paths[i]}:
        first_seen[b] = next((i for i in range(n) if b and b in blobs[i]), n)
    for i in range(n):
        t = toks[i]
        if t == "edit" and paths[i]:
            reg["edit_den"] += 1
            strict = all(any(path_match(p, q) for q in read_paths) for p in paths[i])
            rw = all(any(path_match(p, q) for q in read_paths + written_paths) for p in paths[i])
            broad = all(bool(os.path.basename(p)) and first_seen.get(os.path.basename(p), n) < i for p in paths[i])
            reg["edit_strict"] += strict
            reg["edit_session_strict"] += bool(st["sess_read_before"].iat[i])
            reg["edit_strict_rw"] += rw
            reg["edit_broad"] += broad
            reg[f"edit_notread_flag_strict{int(strict)}"] += int(st["not_read"].iat[i])
            reg[f"edit_n_strict{int(strict)}"] += 1
            reg[f"edit_res_{rcls[i]}_strict{int(strict)}"] += 1
            # re-read after edit
            nxt = [j for j in range(i + 1, min(n, i + 6)) if toks[j] == "read" and paths[j]
                   and any(path_match(p, q) for p in paths[i] for q in paths[j])]
            reg["edit_reread5"] += bool(nxt)
        if t == "write" and paths[i]:
            reg["write_den"] += 1
            reg["write_notread_flag"] += int(st["not_read"].iat[i])
        if t == "read":
            read_paths.extend(paths[i])
        if t in ("write",):
            written_paths.extend(paths[i])
    # R2 explore-first
    file_idx = [i for i in range(n) if toks[i] in FILE_TOKS and paths[i]]

    def is_explore(i):
        if toks[i] in EXPLORE_TOKS:
            return True
        if i in segs_by_i:
            return any(w in EXPLORE_WORDS for w, _ in segs_by_i[i])
        return False
    explore_idx = [i for i in range(n) if is_explore(i)]
    if file_idx:
        reg["r2_streams"] += 1
        reg["r2_explore_before_first_file"] += bool(explore_idx and explore_idx[0] < file_idx[0])
        reg["r2_first_file_is_call0"] += file_idx[0] == 0
        allp = list(dict.fromkeys(p for i in file_idx for p in paths[i]))
        if len(allp) >= 2:
            dirs = [p.split("/")[:-1] for p in allp]
            root = []
            for parts in zip(*dirs):
                if len(set(parts)) == 1:
                    root.append(parts[0])
                else:
                    break
            deep = [i for i in file_idx if any(len(p.split("/")) - 1 - len(root) >= 2 for p in paths[i])]
            if deep:
                reg["r2_deep_streams"] += 1
                reg["r2_explore_before_first_deep"] += bool(explore_idx and explore_idx[0] < deep[0])
                reg["r2_file_before_first_deep"] += file_idx[0] < deep[0]
    # R3 verification after mutation
    mut_idx = [i for i in range(n) if toks[i] in MUTATION_TOKS]
    test_idx = [i for i in shell_idx if is_test[i]]
    ver_idx = [i for i in shell_idx if is_test[i] or is_build[i]]
    reg["r3_any_test_stream"] += bool(test_idx)
    reg["r3_test_calls"] += len(test_idx)
    reg["r3_test_calls_failed"] += sum(1 for i in test_idx if rcls[i] == "fail")
    if mut_idx:
        reg["r3_streams"] += 1
        reg["r3_test_after_first_mut"] += any(i > mut_idx[0] for i in test_idx)
        after_last = [i for i in test_idx if i > mut_idx[-1]]
        reg["r3_test_after_last_mut"] += bool(after_last)
        reg["r3_verify_after_last_mut"] += any(i > mut_idx[-1] for i in ver_idx)
        reg["r3_any_test_in_mut_stream"] += bool(test_idx)
        if after_last:
            reg["r3_last_test_failed"] += rcls[after_last[-1]] == "fail"
            reg["r3_last_test_none"] += rcls[after_last[-1]] == "none"
        reg["r3_mut_calls"] += len(mut_idx)
        reg["r3_mut_test_within10"] += sum(1 for m in mut_idx if any(m < i <= m + 10 for i in test_idx))
        reg["r3_calls_after_last_mut"] += n - 1 - mut_idx[-1]
    # R4 git commit
    prev_commit = -1
    for i in shell_idx:
        segs = segs_by_i[i]
        words = [w for w, _ in segs]
        if "git commit" not in words:
            continue
        reg["r4_commits"] += 1
        k = words.index("git commit")
        window_words = set(words[:k])
        for j in shell_idx:
            if prev_commit < j < i:
                window_words.update(w for w, _ in segs_by_i[j])
        reg["r4_status_or_diff_before"] += bool(window_words & {"git status", "git diff"})
        reg["r4_status_before"] += "git status" in window_words
        rest = segs[k][1]
        all_flag = any(re.match(r"^-[a-zA-Z]*a[a-zA-Z]*$", a) and not a.startswith("--") for a in rest) or "--all" in rest
        reg["r4_add_before"] += ("git add" in window_words) or all_flag
        later_words = set(words[k + 1:])
        nxt5 = [j for j in shell_idx if i < j <= i + 5]
        log_after = any(w in ("git log", "git show") for j in nxt5 for w, _ in segs_by_i[j]) or bool(later_words & {"git log", "git show"})
        reg["r4_log_after"] += log_after
        push_after = ("git push" in later_words) or any(w == "git push" for j in shell_idx if j > i for w, _ in segs_by_i[j])
        reg["r4_push_after"] += push_after
        reg["r4_commit_failed"] += rcls[i] == "fail"
        reg["r4_commit_none"] += rcls[i] == "none"
        prev_commit = i
    f["reg"] = reg
    # positions for rule mining (token -> sorted indices)
    pos = defaultdict(list)
    for i, t in enumerate(toks):
        pos[t].append(i)
    f["pos"] = pos
    return f


# ------------------------------------------------------------------------------------------------ aggregation
def by_session(streams, getter):
    acc = defaultdict(float)
    for s in streams:
        acc[s["session"]] += getter(s)
    return acc


def agg_group(streams, sessions):
    """streams: list of per-stream dicts (with 'session'); sessions: ordered list of session ids in the group."""
    out = {"n_sessions": len(sessions), "n_streams": len(streams), "n_calls": int(sum(s["n"] for s in streams))}
    sidx = {s: i for i, s in enumerate(sessions)}

    def vec(getter):
        v = np.zeros(len(sessions))
        for s in streams:
            v[sidx[s["session"]]] += getter(s)
        return v
    # unigram / bigram / trigram
    for key, top in (("uni", TOP["unigram"]), ("bi", TOP["bigram"]), ("tri", TOP["trigram"])):
        tot = Counter()
        for s in streams:
            tot.update(s[key])
        den = vec(lambda s: sum(s[key].values()))
        rows = []
        for g, c in tot.most_common(top):
            num = vec(lambda s, g=g: s[key].get(g, 0))
            prev = int(((num > 0)).sum())
            rows.append({"gram": list(g) if isinstance(g, tuple) else g, "count": int(c), "share": cr(num, den),
                         "session_prevalence": wil(prev, int((den > 0).sum()))})
        out[key] = {"total": int(sum(tot.values())), "distinct": len(tot), "top": rows}
    # self loop, identical consecutive
    den = vec(lambda s: s["pairs"])
    out["self_loop_share"] = cr(vec(lambda s: sum(c for (a, b), c in s["bi"].items() if a == b)), den)
    out["identical_consecutive_call_share"] = cr(vec(lambda s: s["ident_consec"]), den)
    # conditional entropy with session bootstrap
    bis = sorted({g for s in streams for g in s["bi"]})
    if bis and len(sessions) >= MIN_S:
        bidx = {g: i for i, g in enumerate(bis)}
        firsts = sorted({g[0] for g in bis})
        fidx = {t: i for i, t in enumerate(firsts)}
        M = np.zeros((len(sessions), len(bis)))
        for s in streams:
            for g, c in s["bi"].items():
                M[sidx[s["session"]], bidx[g]] += c
        F = np.zeros((len(bis), len(firsts)))
        for g, i in bidx.items():
            F[i, fidx[g[0]]] = 1

        def hcond(counts):
            return entropy_bits(counts) - entropy_bits(counts @ F)
        tot = M.sum(0)
        rng = np.random.default_rng(stats.SEED)
        boots = []
        keep = np.where(M.sum(1) > 0)[0]
        for _ in range(stats.N_BOOT):
            w = np.bincount(rng.choice(keep, size=len(keep)), minlength=len(sessions))
            boots.append(hcond(w @ M))
        out["cond_entropy_next_given_cur_bits"] = {"value": round(hcond(tot), 4), "lo": round(float(np.quantile(boots, .025)), 4),
                                                   "hi": round(float(np.quantile(boots, .975)), 4),
                                                   "unigram_entropy_bits": round(entropy_bits(np.array(list(Counter(
                                                       t for s in streams for t in s["uni"].elements()).values()))), 4),
                                                   "n_sessions": int(len(keep)), "n_bigrams": int(tot.sum())}
    else:
        out["cond_entropy_next_given_cur_bits"] = {"value": None, "n_sessions": len(sessions), "insufficient_n": True}
    out["max_same_token_run_per_stream"] = stats.describe([s["max_run"] for s in streams if s["n"]])
    out["share_of_streams_with_run_ge_10"] = cr(vec(lambda s: s["max_run"] >= 10), vec(lambda s: s["n"] > 0))
    fc = Counter(s["first"] for s in streams if s["first"] and s["is_main"])
    nmain = vec(lambda s: s["is_main"] and s["n"] > 0)
    out["first_call_main_streams"] = {"n_streams": int(sum(fc.values())), "top": [
        {"tok": t, "count": int(c), "share": cr(vec(lambda s, t=t: s["is_main"] and s["first"] == t), nmain)}
        for t, c in fc.most_common(TOP["first_call"])]}
    return out, vec


def agg_shell(streams, sessions, vec):
    out = {}
    den_calls = vec(lambda s: s["shell_n"])
    out["n_shell_calls"] = int(den_calls.sum())
    out["parsed_share"] = cr(vec(lambda s: s["shell_parsed"]), den_calls)
    out["cd_prefix_share"] = cr(vec(lambda s: s["cd_prefix"]), den_calls)
    out["multi_segment_share"] = cr(vec(lambda s: s["multi_seg"]), den_calls)
    for key, top in (("lead", TOP["shell_word"]), ("lead_bi", TOP["shell_bigram"]), ("seg_bi", TOP["segment_bigram"])):
        tot = Counter()
        for s in streams:
            tot.update(s[key])
        den = vec(lambda s: sum(s[key].values()))
        rows = []
        for g, c in tot.most_common(top):
            num = vec(lambda s, g=g: s[key].get(g, 0))
            rows.append({"gram": list(g) if isinstance(g, tuple) else g, "count": int(c), "share": cr(num, den),
                         "session_prevalence": wil(int((num > 0).sum()), int((den > 0).sum()))})
        out[key] = {"total": int(sum(tot.values())), "distinct": len(tot), "top": rows}
    return out


def agg_retry(streams, vec):
    R = lambda k: vec(lambda s: s["retry"].get(k, 0))  # noqa: E731
    out = {"anchors": {c: int(R("anchor_" + c).sum()) for c in ("ok", "fail", "reject", "none")}}
    den_f = R("anchor_fail")
    den_o = R("anchor_ok")
    out["fail_rate_per_call"] = cr(den_f, den_f + den_o + R("anchor_reject") + R("anchor_none"))
    cls = ["exact", "near", "same_tool_diff", "no_same_tool", "stream_end"]
    for c, den in (("fail", den_f), ("ok", den_o)):
        out[c] = {k: cr(R(f"{c}_{k}"), den) for k in cls}
        out[c]["retry_exact_or_near"] = cr(R(f"{c}_exact") + R(f"{c}_near"), den)
        out[c]["immediate_retry"] = cr(R(f"{c}_imm_retry"), den)
        out[c]["window_truncated"] = int(R(f"{c}_window_truncated").sum())
    out["retry_lift_fail_minus_ok"] = cluster_diff(R("fail_exact") + R("fail_near"), den_f, R("ok_exact") + R("ok_near"), den_o)
    out["exact_lift_fail_minus_ok"] = cluster_diff(R("fail_exact"), den_f, R("ok_exact"), den_o)
    rr = R("fail_exact") + R("fail_near")
    out["retry_result_after_failure"] = {k: cr(R("fail_retry_result_" + k), rr) for k in ("ok", "fail", "reject", "none")}
    # by tool (pooled counts, top failing tokens)
    fails = Counter()
    for s in streams:
        for k, v in s["retry"].items():
            if k.startswith("fail_tok:"):
                fails[k[9:]] += v
    out["posthoc_edit_read_gate"] = {
        "POSTHOC": "added after the first B run showed exact retry of failed edits >> other tools",
        "failed_edits_not_read_refusal": int(R("edit_fail_notread1").sum()),
        "failed_edits_other": int(R("edit_fail_notread0").sum()),
        "retry_given_not_read_refusal": cr(R("edit_fail_notread1_retry"), R("edit_fail_notread1")),
        "retry_given_other_edit_failure": cr(R("edit_fail_notread0_retry"), R("edit_fail_notread0")),
        "read_same_path_between_given_retry_after_not_read": cr(R("edit_fail_notread1_retry_read_between"), R("edit_fail_notread1_retry")),
        "read_same_path_between_given_retry_after_other": cr(R("edit_fail_notread0_retry_read_between"), R("edit_fail_notread0_retry"))}
    out["by_tool"] = []
    for t, c in fails.most_common(8):
        num = R(f"fail_retry_exact_tok:{t}") + R(f"fail_retry_near_tok:{t}")
        d = R(f"fail_tok:{t}")
        out["by_tool"].append({"tok": t, "fail_anchors": int(c), "retry_exact_or_near": cr(num, d),
                               "exact": cr(R(f"fail_retry_exact_tok:{t}"), d)})
    loops = [L for s in streams for L in s["loops"]]
    out["loops"] = {"n": len(loops), "length": stats.describe([L for L, _ in loops]),
                    "length_counts": dict(sorted(Counter(min(L, 6) for L, _ in loops).items())),
                    "end": dict(Counter(e for _, e in loops)),
                    "loops_ge3_share": cr(vec(lambda s: sum(1 for L, _ in s["loops"] if L >= 3)), vec(lambda s: len(s["loops"])))}
    return out


def agg_reg(vec):
    G = lambda k: vec(lambda s: s["reg"].get(k, 0))  # noqa: E731
    o = {}
    d = G("edit_den")
    o["R1_read_before_edit"] = {"n_edit_calls_with_path": int(d.sum()), "strict": cr(G("edit_strict"), d),
                                "strict_or_written": cr(G("edit_strict_rw"), d), "broad_basename_seen": cr(G("edit_broad"), d),
                                "session_strict": cr(G("edit_session_strict"), d),
                                "not_read_refusal_given_no_prior_read": cr(G("edit_notread_flag_strict0"), G("edit_n_strict0")),
                                "not_read_refusal_given_prior_read": cr(G("edit_notread_flag_strict1"), G("edit_n_strict1")),
                                "edit_result_fail_given_no_prior_read": cr(G("edit_res_fail_strict0"), G("edit_n_strict0")),
                                "edit_result_fail_given_prior_read": cr(G("edit_res_fail_strict1"), G("edit_n_strict1")),
                                "write_not_read_refusal": cr(G("write_notread_flag"), G("write_den"))}
    o["R5_reread_after_edit_within5"] = cr(G("edit_reread5"), d)
    d2 = G("r2_streams")
    o["R2_explore_first"] = {"n_streams": int(d2.sum()), "explore_before_first_file_call": cr(G("r2_explore_before_first_file"), d2),
                             "first_call_is_file_call": cr(G("r2_first_file_is_call0"), d2),
                             "n_deep_streams": int(G("r2_deep_streams").sum()),
                             "explore_before_first_deep_call": cr(G("r2_explore_before_first_deep"), G("r2_deep_streams")),
                             "shallow_file_call_before_first_deep": cr(G("r2_file_before_first_deep"), G("r2_deep_streams"))}
    d3 = G("r3_streams")
    o["R3_verify_after_mutation"] = {
        "n_mutation_streams": int(d3.sum()), "test_after_first_mutation": cr(G("r3_test_after_first_mut"), d3),
        "test_after_last_mutation": cr(G("r3_test_after_last_mut"), d3),
        "verify_after_last_mutation": cr(G("r3_verify_after_last_mut"), d3),
        "any_test_in_mutation_stream": cr(G("r3_any_test_in_mut_stream"), d3),
        "last_test_failed_given_test_after_last_mutation": cr(G("r3_last_test_failed"), G("r3_test_after_last_mut")),
        "last_test_no_result_given_test_after_last_mutation": cr(G("r3_last_test_none"), G("r3_test_after_last_mut")),
        "per_mutation_test_within_10_calls": cr(G("r3_mut_test_within10"), G("r3_mut_calls")),
        "test_call_fail_rate": cr(G("r3_test_calls_failed"), G("r3_test_calls")),
        "n_test_calls": int(G("r3_test_calls").sum()),
        "calls_after_last_mutation_per_stream": {"sum": float(G("r3_calls_after_last_mut").sum()), "streams": int(d3.sum())}}
    d4 = G("r4_commits")
    o["R4_git_commit"] = {"n_commit_calls": int(d4.sum()), "status_or_diff_before": cr(G("r4_status_or_diff_before"), d4),
                          "status_before": cr(G("r4_status_before"), d4), "add_or_all_flag_before": cr(G("r4_add_before"), d4),
                          "log_or_show_within_5_after": cr(G("r4_log_after"), d4), "push_later": cr(G("r4_push_after"), d4),
                          "commit_result_failed": cr(G("r4_commit_failed"), d4), "commit_no_result": cr(G("r4_commit_none"), d4)}
    return o


def mine_rules(streams, sessions, uni_top):
    sidx = {s: i for i, s in enumerate(sessions)}
    toks = [g["gram"] for g in uni_top][:12]
    T = len(toks)
    if T < 2:
        return {"tools": toks, "rules": []}
    S = len(sessions)
    den = np.zeros((S, T))
    pre = np.zeros((S, T, T))
    fol = np.zeros((S, T, T))
    cooc = np.zeros((S, T, T))  # POSTHOC: X calls in streams where Y occurs at all
    for s in streams:
        si = sidx[s["session"]]
        firsts = np.array([s["pos"][t][0] if t in s["pos"] else 10 ** 9 for t in toks])
        lasts = np.array([s["pos"][t][-1] if t in s["pos"] else -1 for t in toks])
        present = np.array([t in s["pos"] for t in toks], dtype=float)
        for x, t in enumerate(toks):
            p = s["pos"].get(t)
            if not p:
                continue
            p = np.asarray(p)
            den[si, x] += len(p)
            pre[si, x] += (p[:, None] > firsts[None, :]).sum(0)
            fol[si, x] += (p[:, None] < lasts[None, :]).sum(0)
            cooc[si, x] += len(p) * present
    rules = []
    for x in range(T):
        dx = den[:, x]
        if dx.sum() < 200 or (dx > 0).sum() < MIN_S:
            continue
        for y in range(T):
            if y == x:
                continue
            for kind, arr in (("precedes", pre), ("follows", fol)):
                num = arr[:, x, y]
                p = num.sum() / dx.sum()
                if p >= 0.95 or p <= 0.05:
                    r = cr(num, dx)
                    if r["rate"] is None:
                        continue
                    if r["rate"] >= 0.95 and r["lo"] >= 0.90:
                        rules.append({"x": toks[x], "y": toks[y], "relation": f"{toks[y]} always {kind} {toks[x]}", **r})
                    elif r["rate"] <= 0.05 and r["hi"] <= 0.10:
                        rules.append({"x": toks[x], "y": toks[y], "relation": f"{toks[y]} never {kind} {toks[x]}", **r})
    # POSTHOC (added after reading the first B output, where most 'never' rules were tools absent from the stream):
    # the same thresholds on the rate conditional on Y occurring somewhere in the X call's stream.
    cond = []
    for x in range(T):
        for y in range(T):
            if y == x:
                continue
            dxy = cooc[:, x, y]
            if dxy.sum() < 200 or (dxy > 0).sum() < MIN_S:
                continue
            for kind, arr in (("precedes", pre), ("follows", fol)):
                num = arr[:, x, y]
                p = num.sum() / dxy.sum()
                if p >= 0.95 or p <= 0.05:
                    r = cr(num, dxy)
                    if r["rate"] is None:
                        continue
                    if r["rate"] >= 0.95 and r["lo"] >= 0.90:
                        cond.append({"x": toks[x], "y": toks[y], "relation": f"{toks[y]} always {kind} {toks[x]} (when both in stream)", **r})
                    elif r["rate"] <= 0.05 and r["hi"] <= 0.10:
                        cond.append({"x": toks[x], "y": toks[y], "relation": f"{toks[y]} never {kind} {toks[x]} (when both in stream)", **r})
    # co-occurrence of each pair at stream level (X calls whose stream also has Y) for the unconditional 'never' rules
    for rr in rules:
        x, y = toks.index(rr["x"]), toks.index(rr["y"])
        rr["posthoc_x_calls_in_streams_with_y"] = float(cooc[:, x, y].sum())
    nev = [rr for rr in rules if " never " in rr["relation"]]
    return {"tools": toks, "n_rules": len(rules), "rules": rules, "posthoc_conditional_n_rules": len(cond),
            "posthoc_conditional_rules": cond,
            "posthoc_n_never_rules": len(nev),
            "posthoc_n_never_rules_y_absent_in_majority": sum(
                1 for rr in nev if rr["posthoc_x_calls_in_streams_with_y"] < 0.5 * rr["den"]),
            "posthoc_n_conditional_never_rules": sum(1 for rr in cond if " never " in rr["relation"])}


# ------------------------------------------------------------------------------------------------ whowhen extras
def whowhen_extras(calls, split):
    lab = json.load(open(os.path.join(CACHE, "whowhen_labels.json"), encoding="utf-8"))
    ext = pd.read_parquet(os.path.join(CACHE, f"whowhen_{split}.parquet"), columns=["session_id", "kind", "call_id", "extra"])
    ext = ext[ext.kind.isin(["call", "result"])]
    step = {}
    for sid, k, cid, e in zip(ext.session_id, ext.kind, ext.call_id, ext.extra):
        d = json.loads(e) if isinstance(e, str) else {}
        step[(str(sid), k, str(cid))] = d.get("step")
    out = {}
    for strat in ("Algorithm-Generated", "Hand-Crafted"):
        c = calls[calls.stratum == strat]
        sess = sorted(c.session_id.unique())
        obs, exp, n_with_fail, before, at, after, n_lab = 0, 0.0, 0, 0, 0, 0, 0
        no_fail_sessions = 0
        for sid in sess:
            L = lab.get(sid)
            if not L or L.get("mistake_step") is None:
                continue
            n_lab += 1
            ms = int(L["mistake_step"])
            g = c[(c.session_id == sid) & (c.res_class == "fail")]
            fsteps = set()
            for cid in g.call_id:
                a = step.get((sid, "call", str(cid)))
                b = step.get((sid, "result", str(cid)))
                if a is not None:
                    fsteps.add(int(a))
                if b is not None:
                    fsteps.add(int(b))
            hl = int(L.get("history_len") or 0)
            if not fsteps:
                no_fail_sessions += 1
                continue
            n_with_fail += 1
            obs += ms in fsteps
            exp += len(fsteps) / hl if hl else 0
            first = min(fsteps)
            before += ms < first
            at += ms == first
            after += ms > first
        out[strat] = {"n_labelled_sessions": n_lab, "sessions_without_failed_exec": no_fail_sessions,
                      "sessions_with_failed_exec": n_with_fail,
                      "mistake_step_on_failed_call_or_result_step": wil(obs, n_with_fail),
                      "expected_under_uniform_step_null_sum": round(exp, 3),
                      "mistake_step_vs_first_failure": {"before": before, "at": at, "after": after}}
    return out


# ------------------------------------------------------------------------------------------------ main
def run(split):
    t0 = time.time()
    pop = pd.read_parquet(os.path.join(CACHE, "swechat_population.parquet"))
    fmt = dict(zip(pop.session_id.astype(str), pop.format))
    aivs = pd.read_parquet(os.path.join(CACHE, "aiv_cu_sessions.parquet"),
                           columns=["session_id", "model_string", "stratum", "first_created_at"])
    aiv_model = dict(zip(aivs.session_id.astype(str), aivs.model_string))
    aiv_month = dict(zip(aivs.session_id.astype(str), aivs.first_created_at.astype(str).str[:7]))
    result = {"meta": {"lens": "sequences", "split": split, "prereg": PREREG, "revisions": REVISIONS,
                       "aivcu_fail_rx": [[n, r.pattern] for n, r in AIVCU_FAIL_RX], "test_rx": TEST_RX.pattern,
                       "build_rx": BUILD_RX.pattern, "explore_words": sorted(EXPLORE_WORDS), "nav_words": sorted(NAV_WORDS),
                       "not_read_phrases": list(NOT_READ_PHRASES)},
              "integrity": {}, "groups": {}, "aiv_cu_models": {}, "whowhen": {}, "insufficient_n": []}
    result["meta"]["posthoc_additions"] = POSTHOC
    for corpus in ("swechat", "cc_local", "aiv_cc", "aiv_cu", "whowhen"):
        tc = time.time()
        calls, integ = load_corpus(corpus, split)
        private = corpus == "cc_local"
        # group labels per stream
        calls = calls.sort_values(["session_id", "stream", "seq"]).reset_index(drop=True)
        calls["sess_read_before"] = session_read_before_edit(calls)
        streams = []
        for (sid, stream), st in calls.groupby(["session_id", "stream"], sort=False):
            f = analyse_stream(st, corpus, private)
            is_main = bool(st["is_main"].iat[0])
            f["session"] = sid
            f["is_main"] = is_main
            if corpus == "swechat":
                fm = fmt.get(sid, "unknown")
                f["groups"] = [fm, f"{fm}/{'main' if is_main else 'sub'}"]
            elif corpus == "cc_local":
                f["groups"] = ["all", "main" if is_main else "sub"]
            elif corpus == "aiv_cu":
                f["groups"] = ["all", "stratum:" + str(st["stratum"].iat[0]), "model:" + str(aiv_model.get(sid))]
            elif corpus == "whowhen":
                f["groups"] = [str(st["stratum"].iat[0])]
            else:
                f["groups"] = ["all"]
            streams.append(f)
        # integrity by group
        result["integrity"][corpus] = {"all": integ}
        gnames = sorted({g for s in streams for g in s["groups"]})
        result["groups"][corpus] = {}
        for g in gnames:
            gs = [s for s in streams if g in s["groups"]]
            sessions = sorted({s["session"] for s in gs})
            ng, vec = agg_group(gs, sessions)
            if len(sessions) < MIN_S:
                result["insufficient_n"].append({"corpus": corpus, "group": g, "n_sessions": len(sessions),
                                                 "n_calls": ng["n_calls"]})
            entry = {"ngrams": ng}
            if corpus == "aiv_cu" and g.startswith("model:"):
                entry = {"ngrams": {k: ng[k] for k in ("n_sessions", "n_streams", "n_calls", "self_loop_share",
                                                        "identical_consecutive_call_share", "cond_entropy_next_given_cur_bits",
                                                        "share_of_streams_with_run_ge_10")},
                         "bigram_top": ng["bi"]["top"][:TOP["per_model_bigram"]],
                         "unigram_top": ng["uni"]["top"][:8]}
            entry["shell"] = agg_shell(gs, sessions, vec)
            if corpus == "aiv_cu" and g.startswith("model:"):
                entry["shell"] = {k: entry["shell"][k] for k in ("n_shell_calls", "cd_prefix_share", "multi_segment_share")}
            entry["retry"] = agg_retry(gs, vec)
            entry["regularities"] = agg_reg(vec)
            if not (corpus == "aiv_cu" and g.startswith("model:")):
                entry["rules"] = mine_rules(gs, sessions, ng["uni"]["top"])
            if corpus == "aiv_cu":
                entry["aiv_cu_specific"] = aivcu_specific(calls, sessions)
            result["groups"][corpus][g] = entry
        if corpus == "whowhen":
            result["whowhen"] = whowhen_extras(calls, split)
        if corpus == "aiv_cu":
            ms = Counter(aiv_model.get(s) for s in calls.session_id.unique())
            per = defaultdict(list)
            for sid in calls.session_id.unique():
                per[aiv_model.get(sid)].append(aiv_month.get(sid))
            periods = {m: {"first_month": min(v), "median_month": sorted(v)[len(v) // 2], "last_month": max(v)}
                       for m, v in per.items() if m is not None}
            result["aiv_cu_models"] = {"posthoc_session_month_range_per_model": periods,
                                       "sessions_per_model": dict(ms.most_common()),
                                       "models_with_ge_min_sessions": sorted(m for m, c in ms.items() if c >= MIN_S),
                                       "models_insufficient_n": sorted(m for m, c in ms.items() if c < MIN_S)}
        result["integrity"][corpus]["by_group"] = integrity_by_group(calls, streams, corpus, fmt, aiv_model)
        result["integrity"][corpus]["seconds"] = round(time.time() - tc, 1)
        print(f"{corpus}: {len(calls)} calls, {len(streams)} streams, {time.time() - tc:.0f}s", flush=True)
        del calls, streams
    result["meta"]["seconds_total"] = round(time.time() - t0, 1)
    return result


def aivcu_specific(calls, sessions):
    c = calls[calls.session_id.isin(set(sessions))].sort_values(["session_id", "seq"])
    sidx = {s: i for i, s in enumerate(sessions)}
    keys = ["clicks", "clicks_after_pixel", "gui", "gui_screenshot", "calls", "shell", "timeouts", "timeout_then_restart",
            "coords_fail", "coords_fail_then_coords", "pixel", "pixel_then_click", "send_msg", "fail"]
    V = {k: np.zeros(len(sessions)) for k in keys}
    for sid, g in c.groupby("session_id", sort=False):
        i = sidx[sid]
        toks = g["tok"].tolist()
        mk = g["res_marker"].tolist()
        rc = g["res_class"].tolist()
        n = len(toks)
        V["calls"][i] += n
        V["fail"][i] += sum(1 for x in rc if x == "fail")
        for j, t in enumerate(toks):
            nxt = toks[j + 1] if j + 1 < n else None
            prv = toks[j - 1] if j else None
            if t.startswith("gui:"):
                V["gui"][i] += 1
                V["gui_screenshot"][i] += t == "gui:screenshot"
                if t in ("gui:left_click", "gui:double_click", "gui:right_click", "gui:triple_click"):
                    V["clicks"][i] += 1
                    V["clicks_after_pixel"][i] += prv == "get_pixel_coords_of_element"
            if t in ("shell", "shell_restart"):
                V["shell"][i] += 1
            if t == "get_pixel_coords_of_element":
                V["pixel"][i] += 1
                V["pixel_then_click"][i] += bool(nxt and nxt in ("gui:left_click", "gui:double_click", "gui:right_click",
                                                                  "gui:triple_click", "gui:left_click_drag"))
                if mk[j] == "coords_unavailable":
                    V["coords_fail"][i] += 1
                    V["coords_fail_then_coords"][i] += nxt == "get_pixel_coords_of_element"
            if mk[j] == "timeout":
                V["timeouts"][i] += 1
                V["timeout_then_restart"][i] += nxt == "shell_restart"
            if t == "send_message_back_to_chat":
                V["send_msg"][i] += 1
    return {"shell_share_of_calls": cr(V["shell"], V["calls"]),
            "explicit_screenshot_share_of_gui_calls": cr(V["gui_screenshot"], V["gui"]),
            "click_preceded_by_get_pixel_coords": cr(V["clicks_after_pixel"], V["clicks"]),
            "get_pixel_coords_followed_by_click": cr(V["pixel_then_click"], V["pixel"]),
            "coords_unavailable_then_get_pixel_coords_again": cr(V["coords_fail_then_coords"], V["coords_fail"]),
            "timeout_then_restart_next": cr(V["timeout_then_restart"], V["timeouts"]),
            "send_message_share_of_calls": cr(V["send_msg"], V["calls"]),
            "fail_marker_share_of_calls": cr(V["fail"], V["calls"])}


def integrity_by_group(calls, streams, corpus, fmt, aiv_model):
    if corpus == "swechat":
        lab = calls.session_id.map(lambda s: fmt.get(s, "unknown"))
    elif corpus == "aiv_cu":
        lab = calls["stratum"].astype(str)
    elif corpus == "whowhen":
        lab = calls["stratum"].astype(str)
    else:
        lab = pd.Series(np.where(calls["is_main"], "main", "sub"), index=calls.index)
    out = {}
    for g, d in calls.groupby(lab.values):
        sess = sorted(d.session_id.unique())
        none = d.groupby("session_id").apply(lambda x: (x.res_class == "none").sum()).reindex(sess).values
        tot = d.groupby("session_id").size().reindex(sess).values
        bad = d.groupby("session_id").apply(lambda x: (~x.res_after_call).sum()).reindex(sess).values
        top_none = Counter(d.loc[d.res_class == "none", "tok"]).most_common(5)
        out[g] = {"n_sessions": len(sess), "calls_without_result_share": cr(none, tot),
                  "results_before_call_share": cr(bad, tot),
                  "calls_without_result_top_tokens": [[t, int(c)] for t, c in top_none],
                  "res_class_counts": {k: int(v) for k, v in d.res_class.value_counts().items()}}
        if corpus != "aiv_cu":
            mk = Counter(m for m in d.res_marker if isinstance(m, str))
            out[g]["marker_counts"] = dict(mk)
        else:
            out[g]["marker_counts"] = dict(Counter(m for m in d.res_marker if isinstance(m, str)))
            out[g]["stderr_present_share_of_calls"] = cr(d.groupby("session_id").res_stderr_present.sum().reindex(sess).fillna(0).values, tot)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="B", choices=["A", "B"])
    a = ap.parse_args()
    res = run(a.split)
    os.makedirs(OUT_DIR, exist_ok=True)
    # the A-split debug output never goes to analysis/out (set SEQ_DEBUG_DIR to a scratch directory)
    path = os.path.join(OUT_DIR, "sequences.json") if a.split == "B" else os.path.join(
        os.environ.get("SEQ_DEBUG_DIR", "."), "_sequences_debug_A.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1, ensure_ascii=False, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print("wrote", path, f"{res['meta']['seconds_total']}s")


if __name__ == "__main__":
    main()
