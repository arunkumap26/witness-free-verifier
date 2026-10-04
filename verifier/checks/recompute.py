"""T1 recomputation / in-call consistency check (witness-free, transcript only).

A tool result is `contradicted` when it cannot be the output of the call that produced it, given only
(a) the call's own arguments and (b) content the transcript had already shown. It is `supported` when a rule
recomputed the exact expected output and the result matches it. Everything else is `unconstrained` (an abstention).

INTEGRATOR ENTRYPOINT
    check_session(turns: list[dict], rules: tuple[str, ...] | None = None) -> dict[str, dict]
        turns: one session in SWE-chat turn format (role user/assistant/tool_use/tool_result, content,
               tool_name, tool_call_id, tool_input_json, command, ...), in transcript order.
        returns {tool_call_id: {"verdict": "contradicted"|"supported"|"unconstrained",
                                "reason":  "<prefix>:<rule>" (violation:/ok:/abstain:),
                                "confidence": float | None,
                                "rule": str | None, "detail": dict | None}}
        One entry per tool_result turn that has a tool_call_id. Pure: no I/O, no subprocess, stdlib only.
    check_claim(row, turns=None) -> dict
        T1 decides tool outputs only. Every claim row is returned `unconstrained` ("abstain:claim_unit").

RULES (each was kept only if it fires on 0 honest real calls; see analysis/swarmds/dev_t1_recompute.json)
    ack_path        Edit/Write success ack must restate the call's own file_path verbatim
                    ("The file P has been updated." / "File created successfully at: P").
    ack_id          Submit ack must restate the call's problem_id ("Submitted ID.").
    write_ack_state Write ack kind (created vs updated) must agree with the file's existence as the transcript
                    last established it (a successful Read/Write/Edit of the same path, no possible mutation since).
    pure_bash       echo / echo $((arith)) / printf / seq / basename / dirname / pwd / expr, recomputed exactly.
    known_file      cat / cat -n / wc -l|-c|-w / head / tail / sha256sum / sha1sum / md5sum / literal grep /
                    Read, of a file whose full content the transcript already showed (Write content, a complete
                    Read, or an Edit applied to a known content), with no possible mutation since.
    read_numbering  Read output is `{i:6d}\\t<line>` with i sequential from the call's offset. A pass is
                    format-only, so it is reported `unconstrained` ("abstain:format_held_read_numbering").
    exit_code       the harness prefixes 'Exit code N' iff N != 0; an output whose own text proves a non-zero
                    exit (pytest 'N failed', ls/cat/grep 'No such file', git 'fatal:', python uncaught
                    traceback, 'command not found', harness timeout, grep with no lines) must carry it, and
                    'Exit code 0' never appears.
    pytest_counts   pytest summary counts equal the enumerated per-test lines, and `[ NN%]` progress equals
                    floor(done*100/collected).
    pytest_replay   two pytest invocations with the same test selection (display-only flags removed) in the same
                    cwd, with no possible file mutation between them, cannot disagree on pass/fail; the run reporting
                    success is the one flagged (it may be the earlier one).
    File-state knowledge is kept only for paths under the session's own working directory (/shared etc. are
    written by other agents), is dropped by any Bash command not provably read-only, and is disabled for the rest
    of the session once a background job (&, nohup, setsid, disown) is started.

Rules and constants are frozen in analysis/swarmds/frozen_t1_recompute.json (RULES_VERSION below).
"""
from __future__ import annotations

import hashlib
import json
import posixpath
import re
import shlex
from typing import Any, Optional

RULES_VERSION = "t1_recompute/1.0.0"
CHECK_NAME = "recompute"

# Harness constants (swarm/tools.py, swarm/schemas.py; read-only facts about the environment)
MAX_LINE_CHARS = 2000
DEFAULT_READ_LIMIT = 2000
MAX_DELIVERED_CHARS = 3000
NO_OUTPUT = "(no output)"
EMPTY_READ = "<system-reminder>Warning: the file exists but the contents are empty.</system-reminder>"
TRUNC_RX = re.compile(r"\n\n\.\.\. \[\d+ characters truncated\] \.\.\.\n\n")
EXIT_RX = re.compile(r"^Exit code (-?\d+)\n")

# Confidence per rule: how directly the rule's premise is a harness/tool invariant (judgment, frozen).
CONFIDENCE = {
    "ack_path": 0.99, "ack_id": 0.99, "write_ack_state": 0.9, "pure_bash": 0.98, "known_file": 0.95,
    "read_numbering": 0.97, "exit_code": 0.95, "pytest_counts": 0.95, "pytest_replay": 0.85,
}

ENABLED_RULES = tuple(CONFIDENCE)  # overwritten by frozen JSON if present (see load_frozen)


# ----------------------------------------------------------------------------------------------- helpers
def _parse_input(t: dict) -> dict:
    for raw in (t.get("tool_input_json"), t.get("content")):
        if isinstance(raw, str):
            try:
                v = json.loads(raw)
            except ValueError:
                continue
            if isinstance(v, dict):
                return v
    return {}


def _resolve(path: str, cwd: Optional[str]) -> Optional[str]:
    if not isinstance(path, str) or not path or "~" in path or "$" in path:
        return None
    if path.startswith("/"):
        return posixpath.normpath(path)
    if cwd is None:
        return None
    return posixpath.normpath(posixpath.join(cwd, path))


def _scan(cmd: str) -> set:
    """Characters/constructs that appear OUTSIDE quotes (and a few that matter anywhere)."""
    out = set()
    q = None
    i = 0
    while i < len(cmd):
        ch = cmd[i]
        if q == "'":
            if ch == "'":
                q = None
        elif q == '"':
            if ch == '"':
                q = None
            elif ch in "$`\\":
                out.add(ch)
        else:
            if ch in "'\"":
                q = ch
            elif ch in "\n$`\\*?[]~{}()<>|;&#!":
                out.add(ch)
        i += 1
    if q is not None:
        out.add("unbalanced")
    return out


def _tokens(cmd: str) -> Optional[list]:
    try:
        s = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        s.whitespace_split = True
        return list(s)
    except ValueError:
        return None


OPS = {"&&", "||", "|", ";", "&", ";;", "(", ")", "|&"}
REDIR = {">", ">>", "<", ">&", "<&", "&>", ">|", "<<", "<<<", "&>>"}


def _chain(cmd: str) -> Optional[list]:
    """Split a command into &&-joined simple elements (list of argv lists, redirections dropped).
    None if any other control operator, unquoted newline, heredoc, subshell or substitution is present."""
    sc = _scan(cmd)
    if sc & {"\n", "`", "unbalanced", "(", ")", "#"}:
        return None
    if "$" in sc and "$(" in cmd:
        return None
    toks = _tokens(cmd)
    if toks is None:
        return None
    elems, cur = [], []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t == "&&":
            if not cur:
                return None
            elems.append(cur)
            cur = []
        elif t in OPS:
            return None
        elif t in REDIR:
            if t in ("<<", "<<<"):
                return None
            if cur and re.fullmatch(r"\d", cur[-1] or ""):
                cur.pop()
            i += 1  # skip target
        else:
            cur.append(t)
        i += 1
    if not cur:
        return None
    elems.append(cur)
    out = []
    for e in elems:
        while e and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", e[0]):
            e = e[1:]
        if not e:
            return None
        out.append(e)
    return out


def _has_redirect_out(cmd: str) -> bool:
    toks = _tokens(cmd) or []
    for i, t in enumerate(toks):
        if t in (">", ">>", ">|", "&>", "&>>"):
            tgt = toks[i + 1] if i + 1 < len(toks) else ""
            if tgt != "/dev/null":
                return True
    return False


# -------------------------------------------------------------------------------- mutation model (conservative)
READONLY = {"ls", "cat", "head", "tail", "wc", "grep", "egrep", "fgrep", "echo", "printf", "pwd", "cd", "basename",
            "dirname", "seq", "expr", "sha256sum", "sha1sum", "md5sum", "stat", "file", "which", "type", "nl",
            "cut", "tr", "tree", "du", "df", "date", "env", "printenv", "true", "false", "test", "[", "diff", "cmp",
            "comm", "whoami", "id", "uname", "hostname", "realpath", "readlink", "column", "rev", "od", "hexdump",
            "xxd", "strings", "less", "more", "sleep"}
GIT_READONLY = {"status", "log", "diff", "show", "ls-files", "rev-parse", "blame", "shortlog", "describe", "cat-file",
                "ls-tree", "grep", "reflog"}
FIND_WRITE = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"}


def _readonly_bash(cmd: str) -> bool:
    """True only when the command provably cannot change any file under the workspace."""
    sc = _scan(cmd)
    if sc & {"`", "unbalanced"} or "$(" in cmd or "<(" in cmd or ">(" in cmd:
        return False
    if _has_redirect_out(cmd):
        return False
    toks = _tokens(cmd)
    if toks is None:
        return False
    elems, cur = [], []
    for t in toks:
        if t in OPS:
            if t == "&":
                return False
            if cur:
                elems.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        elems.append(cur)
    if "\n" in sc:  # newline-separated statements: tokens already split on whitespace; treat words as argv heads
        return False
    for e in elems:
        e = [w for w in e if w not in REDIR]
        while e and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", e[0]):
            e = e[1:]
        if not e:
            continue
        a0 = posixpath.basename(e[0])
        if a0 == "git":
            sub = next((w for w in e[1:] if not w.startswith("-")), None)
            if sub not in GIT_READONLY:
                return False
            if sub == "diff" and any(w.startswith("--output") for w in e):
                return False
        elif a0 == "find":
            if any(w in FIND_WRITE for w in e):
                return False
        elif a0 == "sort":
            if any(w == "-o" or w.startswith("--output") for w in e):
                return False
        elif a0 not in READONLY:
            return False
    return True


# ----------------------------------------------------------------------------------------- pure bash recompute
def _render_bash(out: str, code: int = 0) -> str:
    if code != 0:
        return f"Exit code {code}\n{out}"
    return out if out.strip() else NO_OUTPUT


def _c_div(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def _arith(expr: str) -> Optional[int]:
    import ast
    if not re.fullmatch(r"[0-9+\-*/% ()]+", expr):
        return None

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and type(n.value) is int:
            return n.value
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            v = ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.BinOp):
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Add):
                return a + b
            if isinstance(n.op, ast.Sub):
                return a - b
            if isinstance(n.op, ast.Mult):
                return a * b
            if isinstance(n.op, (ast.Div, ast.FloorDiv)) and b != 0:
                return _c_div(a, b)
            if isinstance(n.op, ast.Mod) and b != 0:
                return a - b * _c_div(a, b)
        raise ValueError
    try:
        if "//" in expr or "**" in expr:
            return None
        v = ev(ast.parse(expr.strip(), mode="eval"))
        return v if abs(v) < 2 ** 62 else None
    except (ValueError, SyntaxError, RecursionError):
        return None


def _pure_expected(rest: str, cwd: Optional[str]) -> Optional[str]:
    """Expected delivered string for a single pure command, or None if not recomputable."""
    m = re.fullmatch(r"echo\s+\$\(\(([^()]*(?:\([^()]*\)[^()]*)*)\)\)", rest.strip())
    if m:
        v = _arith(m.group(1))
        return None if v is None else _render_bash(f"{v}\n")
    sc = _scan(rest)
    if sc & {"$", "`", "\\", "*", "?", "[", "]", "~", "{", "}", "(", ")", "<", ">", "|", ";", "&", "#", "!", "\n",
             "unbalanced"}:
        return None
    if "\\" in rest or "$" in rest:
        return None
    toks = _tokens(rest)
    if not toks:
        return None
    cmd, args = toks[0], toks[1:]
    if cmd == "echo":
        nonl = False
        while args and args[0] in ("-n",):
            nonl = True
            args = args[1:]
        if args and re.fullmatch(r"-[neE]+", args[0]):
            return None
        return _render_bash(" ".join(args) + ("" if nonl else "\n"))
    if cmd == "printf":
        if len(args) != 1 or "%" in args[0]:
            return None
        return _render_bash(args[0])
    if cmd == "seq":
        if not (1 <= len(args) <= 3) or not all(re.fullmatch(r"-?\d+", a) for a in args):
            return None
        n = [int(a) for a in args]
        lo, st, hi = (1, 1, n[0]) if len(n) == 1 else ((n[0], 1, n[1]) if len(n) == 2 else tuple(n))
        if st == 0 or abs(hi - lo) > 100000:
            return None
        vals = list(range(lo, hi + (1 if st > 0 else -1), st)) if (hi - lo) * st >= 0 else []
        if not vals:
            return _render_bash("")
        return _render_bash("".join(f"{v}\n" for v in vals))
    if cmd == "basename":
        if not (1 <= len(args) <= 2) or any(a.startswith("-") for a in args) or not args[0]:
            return None
        p = args[0].rstrip("/") or "/"
        b = posixpath.basename(p) if p != "/" else "/"
        if len(args) == 2 and b.endswith(args[1]) and b != args[1]:
            b = b[: -len(args[1])]
        return _render_bash(b + "\n")
    if cmd == "dirname":
        if len(args) != 1 or args[0].startswith("-") or not args[0]:
            return None
        p = args[0]
        s = p.rstrip("/")
        if not s:
            d = "/"
        elif "/" not in s:
            d = "."
        else:
            d = s[: s.rfind("/")].rstrip("/") or "/"
        return _render_bash(d + "\n")
    if cmd == "pwd":
        if args or cwd is None:
            return None
        return _render_bash(cwd + "\n")
    if cmd == "expr":
        if len(args) != 3 or args[1] not in ("+", "-", "*", "/", "%") \
           or not all(re.fullmatch(r"-?\d+", a) for a in (args[0], args[2])):
            return None
        a, b = int(args[0]), int(args[2])
        if args[1] in "/%" and b == 0:
            return None
        v = {"+": a + b, "-": a - b, "*": a * b}.get(args[1])
        if v is None:
            v = _c_div(a, b) if args[1] == "/" else a - b * _c_div(a, b)
        return _render_bash(f"{v}\n", 1 if v == 0 else 0)
    return None


# ----------------------------------------------------------------------------------------- known-file recompute
def _read_render(text: str, offset: int = 1, limit: int = DEFAULT_READ_LIMIT) -> Optional[str]:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines:
        return EMPTY_READ
    if offset > len(lines):
        return None  # tool_use_error path; not modelled
    chosen = lines[offset - 1: offset - 1 + limit]
    return "\n".join(f"{i:6d}\t{ln[:MAX_LINE_CHARS]}" for i, ln in enumerate(chosen, start=offset))


def _parse_read(res: str) -> Optional[list]:
    """[(n, text)] for a numbered Read output, or None."""
    rows = []
    for ln in res.split("\n"):
        m = re.match(r"^( *)(\d+)\t(.*)$", ln, re.S)
        if not m or len(m.group(1)) + len(m.group(2)) != max(6, len(m.group(2))):
            return None
        rows.append((int(m.group(2)), m.group(3)))
    return rows


def _head_tail(text: str, n: int, head: bool, plus: bool = False) -> str:
    parts = text.split("\n")
    # keep line terminators
    lines = [p + "\n" for p in parts[:-1]] + ([parts[-1]] if parts[-1] != "" else [])
    if head:
        return "".join(lines[:n])
    if plus:
        return "".join(lines[max(n - 1, 0):])
    return "".join(lines[-n:]) if n > 0 else ""


def _known_file_expected(rest: str, cwd: Optional[str], files: dict) -> Optional[tuple]:
    """(set_of_acceptable_delivered, path) for a single read of a known file, else None."""
    sc = _scan(rest)
    if sc & {"$", "`", "*", "?", "[", "]", "~", "{", "}", "(", ")", ">", "|", ";", "&", "#", "!", "\n",
             "unbalanced"}:
        return None
    toks = _tokens(rest)
    if not toks:
        return None
    redirect_in = False
    if "<" in toks:
        i = toks.index("<")
        if i != len(toks) - 2 or toks.count("<") != 1:
            return None
        toks = toks[:i] + [toks[i + 1]]
        redirect_in = True
    cmd, args = toks[0], toks[1:]
    if not args:
        return None
    path = _resolve(args[-1], cwd)
    if path is None or path not in files:
        return None
    variants = files[path]
    fname = args[-1]
    outs = set()
    for text in variants:
        if "\x00" in text:
            return None
        o = None
        if cmd == "cat" and len(args) == 1 and not redirect_in:
            o = _render_bash(text)
        elif cmd == "cat" and len(args) == 2 and args[0] == "-n" and not redirect_in:
            parts = text.split("\n")
            lines = parts[:-1] + ([parts[-1]] if parts[-1] != "" else [])
            body = "".join(f"{i:6d}\t{ln}\n" for i, ln in enumerate(lines, 1))
            if lines and parts[-1] != "":
                body = body[:-1]
            o = _render_bash(body)
        elif cmd == "wc" and len(args) == 2 and args[0] in ("-l", "-c", "-w"):
            n = {"-l": text.count("\n"), "-c": len(text.encode("utf-8")), "-w": len(text.split())}[args[0]]
            o = _render_bash(f"{n}\n" if redirect_in else f"{n} {fname}\n")
        elif cmd in ("head", "tail") and not redirect_in:
            a = args[:-1]
            n, plus = 10, False
            if a == []:
                pass
            elif len(a) == 2 and a[0] == "-n" and re.fullmatch(r"\+?\d+", a[1]):
                plus = a[1].startswith("+")
                n = int(a[1].lstrip("+"))
            elif len(a) == 1 and re.fullmatch(r"-\d+", a[0]):
                n = int(a[0][1:])
            elif len(a) == 1 and re.fullmatch(r"-n\+?\d+", a[0]):
                plus = a[0][2:].startswith("+")
                n = int(a[0][2:].lstrip("+"))
            else:
                return None
            if plus and cmd == "head":
                return None
            o = _render_bash(_head_tail(text, n, cmd == "head", plus))
        elif cmd in ("sha256sum", "sha1sum", "md5sum") and len(args) == 1 and not redirect_in:
            h = {"sha256sum": hashlib.sha256, "sha1sum": hashlib.sha1, "md5sum": hashlib.md5}[cmd]
            if "\\" in fname or "\n" in fname:
                return None
            o = _render_bash(f"{h(text.encode('utf-8')).hexdigest()}  {fname}\n")
        elif cmd == "grep" and not redirect_in:
            flags, pat = [], None
            for a in args[:-1]:
                if a.startswith("-") and pat is None:
                    flags.append(a)
                elif pat is None:
                    pat = a
                else:
                    return None
            fl = set("".join(f[1:] for f in flags))
            if pat is None or any(f.startswith("--") for f in flags) or not fl <= {"n", "i", "c", "F"}:
                return None
            if not pat or not pat.isascii() or not text.isascii():
                return None
            if "F" not in fl and re.search(r"[.\[\]*^$\\+?(){}|]", pat):
                return None
            parts = text.split("\n")
            lines = parts[:-1] + ([parts[-1]] if parts[-1] != "" else [])
            key = pat.lower() if "i" in fl else pat
            hits = [(k, ln) for k, ln in enumerate(lines, 1) if key in (ln.lower() if "i" in fl else ln)]
            code = 0 if hits else 1
            if "c" in fl:
                body = f"{len(hits)}\n"
            elif "n" in fl:
                body = "".join(f"{k}:{ln}\n" for k, ln in hits)
            else:
                body = "".join(f"{ln}\n" for _, ln in hits)
            o = _render_bash(body, code)
        if o is None:
            return None
        outs.add(o)
    return (outs, path) if outs else None


# ------------------------------------------------------------------------------------------------ exit code
PY_EXC_LAST = re.compile(r"^[A-Za-z_][\w.]*(Error|Exception|Interrupt|Exit|Warning)(: .*)?$|^[A-Za-z_][\w.]*Error$")
PYTEST_SUMMARY = re.compile(r"^=+ (.+?) in [\d.]+s(?: \([\d:.]+\))? =+$")
QUIET_ELEMS = {"cd", "rm", "mkdir", "touch", "export", "true", "chmod", "cp", "mv", "ln", "sleep"}


def _argv0(e: list) -> str:
    return posixpath.basename(e[0]) if e else ""


def _is_pytest(e: list) -> bool:
    a0 = _argv0(e)
    if a0 in ("pytest", "py.test"):
        return True
    return bool(re.fullmatch(r"python(\d(\.\d+)?)?", a0)) and len(e) >= 3 and e[1] == "-m" and e[2] == "pytest"


def _is_python_script(e: list) -> bool:
    a0 = _argv0(e)
    return bool(re.fullmatch(r"python(\d(\.\d+)?)?", a0)) and len(e) >= 2 and e[1] != "-m"


def _pytest_summary(body: str) -> Optional[dict]:
    lines = [ln for ln in body.rstrip("\n").split("\n")]
    for ln in reversed(lines[-3:]):
        m = PYTEST_SUMMARY.match(ln.strip())
        if m:
            counts = {}
            for n, k in re.findall(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?|"
                                   r"rerun)", m.group(1)):
                k = {"errors": "error", "warnings": "warning"}.get(k, k)
                counts[k] = int(n)
            counts["_no_tests"] = "no tests ran" in m.group(1)
            return counts
    return None


def _implied_nonzero(cmd: str, body: str) -> Optional[str]:
    """Name of the signature proving a non-zero exit, or None. `body` is the output without any Exit code line."""
    if body.rstrip("\n").endswith("\nCommand timed out") or body.strip() == "Command timed out":
        return "harness_timeout"
    ch = _chain(cmd)
    if ch is None:
        return None
    targets = [e for e in ch if _argv0(e) not in QUIET_ELEMS]
    if len(targets) != 1:
        return None
    e = targets[0]
    a0 = _argv0(e)
    lines = body.split("\n")
    # command not found for this element
    if any(re.fullmatch(rf"(/bin/sh|sh|bash): (\d+: )?{re.escape(e[0])}: (command )?not found", ln) for ln in lines):
        return "command_not_found"
    if a0 == "false" and len(e) == 1:
        return "false"
    if _is_pytest(e):
        if any(w in ("--lf", "--last-failed", "--ff", "--sw", "--stepwise") or w.startswith("--cov-fail") for w in e):
            return None
        s = _pytest_summary(body)
        if s and (s.get("failed", 0) > 0 or s.get("error", 0) > 0):
            return "pytest_failed"
        if s and s.get("_no_tests") and not any(s.get(k, 0) for k in ("passed", "skipped", "xfailed", "xpassed")) \
           and not s.get("deselected"):
            return "pytest_no_tests"
        return None
    if a0 == "ls" and any(re.match(r"^ls: cannot access '.*': No such file or directory$", ln) for ln in lines):
        return "ls_missing"
    if a0 in ("cat", "head", "tail", "wc", "nl", "sha256sum", "md5sum", "sha1sum", "sort") and \
       any(re.match(rf"^{a0}: .+: No such file or directory$", ln) for ln in lines):
        return f"{a0}_missing"
    if a0 == "grep":
        fl = [w for w in e[1:] if w.startswith("-")]
        if any(w in ("-q", "--quiet", "--silent", "-L", "--files-without-match") or re.fullmatch(r"-[A-Za-z]*q[A-Za-z]*", w)
               or re.fullmatch(r"-[A-Za-z]*L[A-Za-z]*", w) or w.startswith("-m") or w.startswith("--max-count")
               for w in fl):
            return None
        if any(re.match(r"^grep: .+: No such file or directory$", ln) for ln in lines) and \
           not any(re.fullmatch(r"-[A-Za-z]*s[A-Za-z]*", w) for w in fl):
            return "grep_missing"
        if body.strip() == "" or body == NO_OUTPUT:
            return "grep_no_lines"
        return None
    if a0 == "find" and any(re.match(r"^find: .+: No such file or directory$", ln) for ln in lines):
        return "find_missing"
    if a0 == "git":
        if any(ln.startswith("fatal: ") for ln in lines) and not any(w in ("--no-pager",) for w in e[1:2]):
            return "git_fatal"
        return None
    if _is_python_script(e):
        tail = [ln for ln in body.rstrip("\n").split("\n") if ln.strip()]
        if not tail:
            return None
        last = tail[-1]
        if "Traceback (most recent call last):" in body and PY_EXC_LAST.match(last) and \
           not re.match(r"^\w*Warning", last):
            # the traceback must be the final block: the last 'Traceback' header precedes only frame lines
            idx = max(i for i, ln in enumerate(tail) if ln.startswith("Traceback (most recent call last):"))
            block = tail[idx + 1:-1]
            if block and all(ln.startswith("  ") or ln.startswith("    ") or re.match(r"^\s*\^+\s*$", ln) or
                             ln.startswith("During handling") or ln.startswith("The above exception") or
                             ln.startswith("Traceback") or PY_EXC_LAST.match(ln) or ln.strip() == ""
                             for ln in block):
                return "python_uncaught"
        if re.match(r"^(SyntaxError|IndentationError|TabError): ", last) and len(tail) >= 2 and \
           any(re.match(r'^  File ".*", line \d+', ln) for ln in tail[-5:]):
            return "python_syntax"
        return None
    if a0 in ("pip", "pip3") or (re.fullmatch(r"python(\d(\.\d+)?)?", a0) and e[1:3] == ["-m", "pip"]):
        if any(re.match(r"^ERROR: (Could not find a version that satisfies|No matching distribution found)", ln)
               for ln in lines):
            return "pip_error"
        return None
    if a0 in ("apt-get", "apt") and any(re.match(r"^E: ", ln) for ln in lines):
        return "apt_error"
    return None


# ------------------------------------------------------------------------------------------------- pytest
PCT_RX = re.compile(r"\[ *(\d+)%\]\s*$")
V_LINE = re.compile(r"^(\S+::\S.*?) (PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)(?: \(.*\))?\s+\[ *(\d+)%\]\s*$")
D_LINE = re.compile(r"^(\S+\.py) ([.FEsxX]+)\s+\[ *(\d+)%\]\s*$")


def _pytest_counts_violation(body: str) -> Optional[dict]:
    """Return a violation detail if summary counts / progress percentages disagree with the enumerated lines.
    None = consistent or not decidable."""
    if TRUNC_RX.search(body) or len(body) >= MAX_DELIVERED_CHARS - 50:
        return None
    lines = body.split("\n")
    hi = [i for i, ln in enumerate(lines) if re.match(r"^(collecting \.\.\. )?collected (\d+) items?\s*$", ln)]
    if len(hi) != 1:
        return None
    total = int(re.search(r"collected (\d+)", lines[hi[0]]).group(1))
    s = _pytest_summary(body)
    if s is None or s.get("deselected") or s.get("rerun") or s.get("error"):
        return None
    j = hi[0] + 1
    body_lines = []
    while j < len(lines) and not lines[j].startswith("="):
        body_lines.append(lines[j])
        j += 1
    counts = {"passed": 0, "failed": 0, "skipped": 0, "xfailed": 0, "xpassed": 0, "error": 0}
    done = 0
    pcts = []
    n_lines = 0
    for ln in body_lines:
        if not ln.strip():
            continue
        m, d = V_LINE.match(ln), D_LINE.match(ln)
        if m:
            st = {"PASSED": "passed", "FAILED": "failed", "ERROR": "error", "SKIPPED": "skipped", "XFAIL": "xfailed",
                  "XPASS": "xpassed"}[m.group(2)]
            counts[st] += 1
            if st != "error":
                done += 1
            pcts.append((done, int(m.group(3))))
            n_lines += 1
        elif d:
            for ch in d.group(2):
                counts[{".": "passed", "F": "failed", "E": "error", "s": "skipped", "x": "xfailed",
                        "X": "xpassed"}[ch]] += 1
            done += len(d.group(2))
            pcts.append((done, int(d.group(3))))
            n_lines += 1
        else:
            return None  # an unparsed line in the progress section (captured output, warnings): abstain
    if n_lines == 0 or counts["error"]:
        return None
    viol = {}
    for k in ("passed", "failed", "skipped", "xfailed", "xpassed"):
        if counts[k] != s.get(k, 0):
            viol[k] = {"enumerated": counts[k], "summary": s.get(k, 0)}
    if total and sum(counts.values()) == total:
        bad = [(dn, p) for dn, p in pcts if p != (dn * 100) // total]
        if bad:
            viol["progress_pct"] = {"first": list(bad[0]), "collected": total}
    elif total and sum(counts.values()) != total and not viol:
        viol["collected"] = {"collected": total, "enumerated": sum(counts.values())}
    return viol or None


def _pytest_outcome(body: str) -> Optional[str]:
    s = _pytest_summary(body)
    if not s:
        return None
    if s.get("failed", 0) or s.get("error", 0):
        return "fail"
    if s.get("passed", 0) and not s.get("_no_tests"):
        return "pass"
    return None


PYTEST_NEUTRAL = re.compile(r"^(-v+|-q+|-s|-x|-l|-rA|-ra|-rf|-rs|-rx|-rE|-rN|--verbose|--quiet|--exitfirst|"
                            r"--no-header|--no-summary|--showlocals|--tb=\w+|--color=\w+|--capture=\w+|"
                            r"--disable-warnings|-W\S*|--durations=\d+|-vv|-vvv|-qq)$")


def _pytest_key(e: list) -> Optional[tuple]:
    """Test selection of a pytest invocation with outcome-neutral display flags removed; None if unparseable."""
    words = e[3:] if _argv0(e).startswith("python") else e[1:]
    sel = []
    i = 0
    while i < len(words):
        w = words[i]
        if PYTEST_NEUTRAL.match(w):
            i += 1
            continue
        if w in ("--tb", "--color", "--capture", "--durations", "-W"):
            i += 2
            continue
        if w in ("-k", "-m"):
            if i + 1 >= len(words):
                return None
            sel.append((w, words[i + 1]))
            i += 2
            continue
        if w.startswith("-"):
            sel.append((w, None))
        else:
            sel.append(("arg", w.rstrip("/") or w))
        i += 1
    return tuple(sorted(sel))


# --------------------------------------------------------------------------------------------- session walk
def _verdict(v: str, reason: str, rule: Optional[str], detail: Optional[dict] = None) -> dict:
    conf = CONFIDENCE.get(rule) if v != "unconstrained" and rule else None
    return {"verdict": v, "reason": reason, "confidence": conf, "rule": rule, "detail": detail}


def _initial_cwd(turns: list) -> Optional[str]:
    for t in turns:
        if t.get("role") == "user" and isinstance(t.get("content"), str):
            m = re.search(r"working directory is (/[^\s.,;`'\"]*)", t["content"])
            if m:
                return posixpath.normpath(m.group(1))
            return None
    return None


def check_session(turns: list, rules: Optional[tuple] = None) -> dict:
    """See module docstring. `rules` restricts which rules may decide (default: ENABLED_RULES)."""
    rules = set(rules or ENABLED_RULES)
    out: dict = {}
    uses: dict = {}
    cwd = _initial_cwd(turns)
    root = cwd                # only the session's own workspace is private; /shared etc. change under other agents

    def private(pth):
        return pth is not None and root is not None and (pth == root or pth.startswith(root.rstrip("/") + "/"))

    files: dict = {}          # resolved path -> frozenset of possible exact texts
    exists: dict = {}         # resolved path -> True/False as last established
    async_jobs = False
    pytest_runs: dict = {}    # (cwd, cmd) -> (outcome, call_id)

    def clear_state():
        files.clear()
        exists.clear()
        pytest_runs.clear()

    for t in turns:
        role = t.get("role")
        cid = t.get("tool_call_id")
        if role == "tool_use" and isinstance(cid, str):
            uses[cid] = t
            continue
        if role != "tool_result" or not isinstance(cid, str):
            continue
        res = t.get("content") if isinstance(t.get("content"), str) else ""
        u = uses.pop(cid, None)
        if u is None:
            out[cid] = _verdict("unconstrained", "abstain:no_tool_use", None)
            continue
        tool = u.get("tool_name") or ""
        inp = _parse_input(u)
        decided = None
        truncated = bool(TRUNC_RX.search(res))

        if tool in ("Edit", "Write"):
            fp = inp.get("file_path")
            ack_upd = re.fullmatch(r"The file (.*) has been updated\.", res, re.S)
            ack_new = re.fullmatch(r"File created successfully at: (.*)", res, re.S)
            ok = bool(ack_upd or ack_new)
            if ok and isinstance(fp, str) and "ack_path" in rules:
                named = (ack_upd or ack_new).group(1)
                if tool == "Edit" and ack_new:
                    decided = _verdict("contradicted", "violation:ack_path", "ack_path",
                                       {"why": "Edit never emits a create acknowledgement"})
                elif named != fp:
                    decided = _verdict("contradicted", "violation:ack_path", "ack_path",
                                       {"call_path": fp[:200], "ack_path": named[:200]})
                else:
                    decided = _verdict("supported", "ok:ack_path", "ack_path")
            path = _resolve(fp, cwd) if isinstance(fp, str) else None
            if path is not None and not private(path):
                path = None
            if tool == "Write" and ok and path is not None and decided and decided["verdict"] == "supported" \
               and "write_ack_state" in rules and not async_jobs and path in exists:
                if exists[path] and ack_new:
                    decided = _verdict("contradicted", "violation:write_ack_state", "write_ack_state",
                                       {"path": path[:200], "known": "exists", "ack": "created"})
                elif exists[path] is False and ack_upd:
                    decided = _verdict("contradicted", "violation:write_ack_state", "write_ack_state",
                                       {"path": path[:200], "known": "absent", "ack": "updated"})
            if tool == "Edit" and ok and path is not None and path in files and "known_file" in rules \
               and not async_jobs and decided and decided["verdict"] == "supported":
                old, new = inp.get("old_string"), inp.get("new_string")
                ra = bool(inp.get("replace_all", False))
                if isinstance(old, str) and isinstance(new, str) and old and old != new:
                    ns = [v.count(old) for v in files[path]]
                    if all(n == 0 for n in ns):
                        decided = _verdict("contradicted", "violation:known_file", "known_file",
                                           {"path": path[:200], "why": "edit reported success but old_string is "
                                                                       "absent from the content last shown"})
                    elif not ra and all(n > 1 for n in ns):
                        decided = _verdict("contradicted", "violation:known_file", "known_file",
                                           {"path": path[:200], "why": "edit reported success but old_string is "
                                                                       "not unique and replace_all is false"})
            # state update
            if ok:
                pytest_runs.clear()  # any successful write can change a test outcome
            if ok and path is not None:
                if tool == "Write" and isinstance(inp.get("content"), str):
                    files[path] = frozenset([inp["content"]])
                    exists[path] = True
                elif tool == "Edit":
                    old, new = inp.get("old_string"), inp.get("new_string")
                    ra = bool(inp.get("replace_all", False))
                    if path in files and isinstance(old, str) and isinstance(new, str) and old:
                        nv = set()
                        for v in files[path]:
                            n = v.count(old)
                            if n == 1 or (n > 1 and ra):
                                nv.add(v.replace(old, new) if ra else v.replace(old, new, 1))
                        if nv:
                            files[path] = frozenset(nv)
                        else:
                            files.pop(path, None)
                    else:
                        files.pop(path, None)
                    exists[path] = True
                else:
                    files.pop(path, None)
                    exists[path] = True
            elif ok and path is None:
                rp = _resolve(fp, cwd) if isinstance(fp, str) else None
                if rp is None:
                    clear_state()
            elif not ok and path is not None:
                pass  # failed write/edit: harness wrote nothing (Edit errors happen before the write)
        elif tool == "Submit":
            pid = inp.get("problem_id")
            m = re.fullmatch(r"Submitted (.*)\.", res, re.S)
            if m and isinstance(pid, str) and "ack_id" in rules:
                if m.group(1) != pid:
                    decided = _verdict("contradicted", "violation:ack_id", "ack_id",
                                       {"call_id": pid[:200], "ack_id": m.group(1)[:200]})
                else:
                    decided = _verdict("supported", "ok:ack_id", "ack_id")
        elif tool == "Read":
            fp = inp.get("file_path")
            path = _resolve(fp, cwd) if isinstance(fp, str) else None
            if path is not None and not private(path):
                path = None
            try:
                offset = max(int(inp.get("offset") or 1), 1)
                limit = int(inp.get("limit") or DEFAULT_READ_LIMIT)
            except (TypeError, ValueError):
                offset, limit = None, None
            is_err = res.startswith("<tool_use_error>")
            numbered = None
            if offset is not None and not is_err and res != EMPTY_READ and not truncated:
                numbered = _parse_read(res)
                if "read_numbering" in rules:
                    if numbered is None:
                        decided = _verdict("contradicted", "violation:read_numbering", "read_numbering",
                                           {"why": "Read output line without the `{i:6d}\\t` prefix"})
                    else:
                        exp = list(range(offset, offset + len(numbered)))
                        got = [n for n, _ in numbered]
                        if got != exp or len(numbered) > limit or any(len(x) > MAX_LINE_CHARS for _, x in numbered):
                            k = next((i for i, (a, b) in enumerate(zip(got, exp)) if a != b), None)
                            decided = _verdict("contradicted", "violation:read_numbering", "read_numbering",
                                               {"offset": offset, "first_bad_index": k,
                                                "got": got[k] if k is not None else None,
                                                "expected": exp[k] if k is not None else None})
                        else:
                            # format held: not evidence that the content is genuine -> abstain, not supported
                            decided = _verdict("unconstrained", "abstain:format_held_read_numbering", None)
            # known content recompute
            if path is not None and path in files and offset is not None and not async_jobs \
               and "known_file" in rules and not truncated and (decided is None or decided["verdict"] != "contradicted"):
                exps = set()
                for v in files[path]:
                    r = _read_render(v, offset, limit)
                    if r is not None:
                        exps.add(r)
                if exps and len(exps) == 1:
                    e = next(iter(exps))
                    if res == e:
                        decided = _verdict("supported", "ok:known_file", "known_file")
                    elif not is_err:
                        decided = _verdict("contradicted", "violation:known_file", "known_file",
                                           {"path": path[:200], "tool": "Read"})
            # state update
            if path is not None:
                if is_err and "File does not exist." in res:
                    exists[path] = False
                    files.pop(path, None)
                elif not is_err:
                    exists[path] = True
                    if res == EMPTY_READ:
                        files[path] = frozenset([""])
                    elif numbered and offset == 1 and len(numbered) < limit and not truncated \
                            and [n for n, _ in numbered] == list(range(1, len(numbered) + 1)) \
                            and all(len(x) < MAX_LINE_CHARS for _, x in numbered):
                        if path not in files or decided is None or decided["verdict"] != "contradicted":
                            body = "\n".join(x for _, x in numbered)
                            files[path] = frozenset([body, body + "\n"])
        elif tool == "Bash":
            cmd = inp.get("command") if isinstance(inp.get("command"), str) else u.get("command")
            if not isinstance(cmd, str):
                cmd = ""
            mexit = EXIT_RX.match(res)
            body = res[mexit.end():] if mexit else res
            code = int(mexit.group(1)) if mexit else 0
            # effective cwd for this command (leading `cd X &&`)
            ecwd = cwd
            rest = cmd.strip()
            mcd = re.match(r"^cd\s+(\S+)\s*&&\s*(.*)$", rest, re.S)
            if mcd:
                tgt = mcd.group(1).strip("'\"")
                ecwd = _resolve(tgt, cwd) if not re.search(r"[$`~*?]", tgt) and tgt != "-" else None
                rest = mcd.group(2).strip()
            # 1) exit code grammar
            if "exit_code" in rules and not truncated:
                if mexit and code == 0:
                    decided = _verdict("contradicted", "violation:exit_code", "exit_code",
                                       {"why": "harness never prints 'Exit code 0'"})
                elif not mexit:
                    sig = _implied_nonzero(cmd, body if body != NO_OUTPUT else "")
                    if sig:
                        decided = _verdict("contradicted", "violation:exit_code", "exit_code",
                                           {"signature": sig, "why": "output proves a non-zero exit but carries no "
                                                                     "'Exit code N' line"})
            # 2) pure recompute
            if decided is None and "pure_bash" in rules and not truncated and "cd " not in rest \
               and not rest.startswith("cd"):
                exp = _pure_expected(rest, ecwd)
                if exp is not None:
                    if res == exp:
                        decided = _verdict("supported", "ok:pure_bash", "pure_bash")
                    else:
                        decided = _verdict("contradicted", "violation:pure_bash", "pure_bash",
                                           {"expected": exp[:200], "command": rest[:200]})
            # 3) known-file recompute
            if decided is None and "known_file" in rules and not truncated and not async_jobs and files:
                ke = _known_file_expected(rest, ecwd, files)
                if ke is not None:
                    exps, kpath = ke
                    if res in exps:
                        decided = _verdict("supported", "ok:known_file", "known_file")
                    else:
                        decided = _verdict("contradicted", "violation:known_file", "known_file",
                                           {"path": kpath[:200], "command": rest[:200]})
            # 4) pytest counts
            ch = _chain(cmd)
            single_pytest = ch is not None and len([e for e in ch if _argv0(e) not in QUIET_ELEMS]) == 1 and \
                any(_is_pytest(e) for e in ch)
            if decided is None and "pytest_counts" in rules and single_pytest and not truncated:
                v = _pytest_counts_violation(body)
                if v:
                    decided = _verdict("contradicted", "violation:pytest_counts", "pytest_counts", v)
            # 5) pytest replay
            if single_pytest and not truncated and not async_jobs:
                pyel = next(e for e in ch if _is_pytest(e))
                stable = not any(w in ("--lf", "--last-failed", "--ff", "--failed-first", "--sw", "--stepwise",
                                       "-p", "--randomly-seed") or w.startswith("--count") for w in pyel)                     and not any(_argv0(e) not in ("cd", "rm") and not _is_pytest(e) for e in ch)
                oc = _pytest_outcome(body)
                key = (ecwd, _pytest_key(pyel))
                if stable and oc and ecwd is not None and key[1] is not None:
                    prev = pytest_runs.get(key)
                    if prev and prev[0] != oc and "pytest_replay" in rules:
                        pass_cid, fail_cid = (cid, prev[1]) if oc == "pass" else (prev[1], cid)
                        v = _verdict("contradicted", "violation:pytest_replay", "pytest_replay",
                                     {"partner_call_id": fail_cid, "partner_outcome": "fail", "outcome": "pass",
                                      "why": "identical test selection, same cwd, no possible file change between"})
                        if pass_cid == cid:
                            if decided is None or decided["verdict"] != "contradicted":
                                decided = v
                        elif pass_cid in out and out[pass_cid]["verdict"] != "contradicted":
                            out[pass_cid] = v
                    else:
                        pytest_runs[key] = (oc, cid)
            # state update
            if re.search(r"(^|[^&>])&(?![&>])", cmd.replace("&&", "").replace(">&", "").replace("&>", "")) or \
               re.search(r"\b(nohup|setsid|disown)\b", cmd):
                async_jobs = True
            if not _readonly_bash(cmd):
                files.clear()
                exists.clear()
                if not single_pytest:
                    pytest_runs.clear()
            # cwd update (persists across calls in this harness)
            if re.search(r"(^|[\s;&|(])(cd|pushd|popd)(\s|$|;)", cmd):
                mbare = re.fullmatch(r"\s*cd\s+(\S+)\s*", cmd)
                if mbare and not mexit:
                    tgt = mbare.group(1).strip("'\"")
                    cwd = _resolve(tgt, cwd) if not re.search(r"[$`~*?]", tgt) and tgt != "-" else None
                elif mcd and not mexit and not re.search(r"(^|[\s;&|(])(cd|pushd|popd)(\s|$|;)", rest) \
                        and not re.search(r"\bexit\b", rest):
                    cwd = ecwd
                else:
                    cwd = None
        else:
            # unknown/host tools: board/session tools do not touch the workspace; anything else might
            if tool not in ("BoardRead", "BoardPost", "SessionToken", "Inspect"):
                clear_state()
        out[cid] = decided or _verdict("unconstrained", "abstain:no_rule", None)
    return out


def check_claim(row: Any, turns: Optional[list] = None) -> dict:
    """T1 decides tool outputs only; claim rows are always abstentions."""
    return {"verdict": "unconstrained", "reason": "abstain:claim_unit", "confidence": None, "rule": None,
            "detail": None}


def load_frozen(path: str) -> dict:
    """Load the frozen rule file and set ENABLED_RULES/CONFIDENCE from it. Returns the parsed JSON."""
    global ENABLED_RULES
    with open(path, encoding="utf-8") as f:
        fz = json.load(f)
    if fz.get("rules_version") != RULES_VERSION:
        raise ValueError(f"frozen rules_version {fz.get('rules_version')!r} != code {RULES_VERSION!r}")
    ENABLED_RULES = tuple(fz["enabled_rules"])
    CONFIDENCE.update(fz.get("confidence", {}))
    return fz


__all__ = ["check_session", "check_claim", "load_frozen", "RULES_VERSION", "ENABLED_RULES", "CONFIDENCE"]
