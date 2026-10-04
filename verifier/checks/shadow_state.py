"""T3 SHADOW STATE: witness-free filesystem / git state satisfiability over ONE session's own records.

Entry point (stdlib only, no side effects, never reads witness data):

    check_session(turns: list[dict], params: dict | None = None) -> dict[str, dict]
        turns  : one session in SWE-chat turn format (role user/assistant/tool_use/tool_result, content,
                 tool_name, tool_call_id, command, file_path, tool_input_json), in transcript order.
        returns: {tool_call_id: {"verdict": "contradicted"|"supported"|"unconstrained",
                                 "reason": "<prefix>:<rule>", "confidence": float,
                                 "rule": str|None, "conflict_with": [call_id, ...],
                                 "localized": bool}}
                 Every paired tool_call_id gets an entry. `localized=False` on a contradiction means the
                 session's records are jointly unsatisfiable but the rule cannot say WHICH of the cited calls
                 is false (both members get the verdict, confidence 0.5); `localized=True` means the rule
                 blames this call specifically.

    check_call(turns, tool_call_id, claimed_output=None, params=None) -> dict
        Convenience for a single row: optionally splices `claimed_output` into that call's tool_result
        (the tiered/counterfactual view) and returns that call's verdict entry.

Shadow model (DESIGN: Tier 3). Walk the session in order and keep what the session's own records establish:
  files[path]   exists True/False, content (exact bytes from Write/cat, or Read lines), who established it
  dirs[path]    complete child set from an `ls` of that directory (absence knowledge)
  finds         complete match set from a simple `find` (absence knowledge)
  git           last `git status` cleanliness, and successful Edits since
A result that contradicts established state with no intervening mutation is `contradicted`.
HAVOC (forget everything) on: user turns after the first, any Bash command outside the read-only effect model
(python, pytest, make, npm, sh, redirects, background jobs, rm/mv/cp/...), failed or unparsable writes,
middle-truncated or line-truncated outputs (no content knowledge taken from them).
Rules are frozen in analysis/swarmds/frozen_t3_state.json; `params` may only switch rules off.
"""
from __future__ import annotations

import fnmatch
import json
import posixpath
import re
import shlex
from dataclasses import dataclass, field
from typing import Any, Optional

CHECK_NAME = "t3_shadow_state"
CHECK_VERSION = "1.0.0"
DEFAULT_CWD = "/workspace"
NO_OUTPUT = "(no output)"
READ_MAX_LINE = 2000
TRUNC_RX = re.compile(r"\n\n\.\.\. \[\d+ characters truncated\] \.\.\.\n\n")
EXIT_RX = re.compile(r"^Exit code (\d+)\n")
ROW_RX = re.compile(r"^ {0,5}(\d+)\t(.*)$")

# Rules (each can be disabled via params["disabled_rules"]).
RULES = (
    "read_content",        # Read/cat content disagrees with content established by Write/Edit/Read/cat
    "read_absent",         # Read/cat/ls says "does not exist" for a path established as existing
    "presence_after_absence",  # path asserted absent (Read error / listing) is later present, no creation between
    "listing_missing",     # ls/find listing omits a file established as existing in that dir
    "edit_unsatisfiable",  # Edit success whose old_string is absent / ambiguous in established content
    "edit_false_failure",  # Edit "String not found" although established content contains old_string
    "git_status_flip",     # git status cleanliness changes with no Edit/Write/mutation between
    "git_clean_after_edit",  # git status clean after a net-changing Edit of a pre-existing repo file
    "exit_status",         # output that implies a nonzero exit, delivered without the `Exit code N` header
    "rerun_exit",          # same read-only command re-run with no mutation between; exit status differs
    "write_ack_state",     # Write says "created" for a file established as existing, or "updated" for one asserted absent
)

READONLY_HEADS = frozenset("""ls cat head tail wc grep egrep fgrep find sort uniq diff cmp echo printf pwd true false test [
stat file tree du df basename dirname realpath readlink which type nl cut tr md5sum sha256sum sha1sum cksum od xxd hexdump
strings column sleep date whoami id uname hostname env less more cd""".split())
GIT_READONLY = frozenset({"status", "log", "diff", "show", "ls-files", "rev-parse", "blame", "shortlog", "describe"})


# ------------------------------------------------------------------------------------------- parsing helpers
@dataclass
class Call:
    cid: str
    tool: str
    inp: dict
    command: Optional[str]
    res_idx: int
    content: str


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


def _norm(p: str, cwd: Optional[str]) -> Optional[str]:
    if not isinstance(p, str) or not p:
        return None
    if p.startswith("~") or "$" in p or "*" in p or "?" in p or "[" in p:
        return None
    if not p.startswith("/"):
        if cwd is None:
            return None
        p = posixpath.join(cwd, p)
    p = posixpath.normpath(p)
    # Only state the session exclusively owns is modelled: its private working tree. Paths elsewhere (e.g. the
    # swarm's /shared directory, written concurrently by other agents) carry no knowledge.
    return p if (p == DEFAULT_CWD or p.startswith(DEFAULT_CWD + "/")) else None


_FOREIGN_ABS = re.compile(r"""(?:^|[\s='"(:])/(?!workspace(?:/|\s|$|['"]))[A-Za-z]""")


def _foreign_paths(cmd: str) -> bool:
    return bool(_FOREIGN_ABS.search(re.sub(r"/dev/null", "", cmd)))


def _split_cd(cmd: str) -> tuple[Optional[str], str]:
    m = re.match(r"^\s*cd\s+(\S+)\s*&&\s*(.*)$", cmd, re.S)
    return (m.group(1), m.group(2).strip()) if m else (None, cmd.strip())


def _lex(cmd: str) -> Optional[list[str]]:
    try:
        lx = shlex.shlex(cmd, posix=True, punctuation_chars=";&|<>()")
        lx.whitespace_split = True
        lx.commenters = ""
        return list(lx)
    except ValueError:
        return None


_SAFE_REDIRECT = re.compile(r"\s\d?>\s*/dev/null|\s2>&1|\s\d?>&\d")


def _segments(cmd: str) -> Optional[list[list[str]]]:
    """Split a command into simple-command word lists. None when it holds constructs outside the model
    (subshells, redirects to files, here-docs, background jobs, command substitution, loops)."""
    if "`" in cmd or "$(" in cmd or "<<" in cmd or "\n" in cmd.strip():
        return None
    cleaned = _SAFE_REDIRECT.sub(" ", " " + cmd)
    toks = _lex(cleaned)
    if toks is None:
        return None
    segs: list[list[str]] = [[]]
    for t in toks:
        if t in ("&&", "||", ";", "|"):
            segs.append([])
        elif t and set(t) <= set(";&|<>()"):
            return None  # '&', '>', '<', '(', ')' ... : background, file redirect, subshell
        else:
            segs[-1].append(t)
    if any(not s for s in segs):
        return None
    for s in segs:
        if s[0] in ("for", "while", "if", "do", "done", "then", "fi", "case", "function") or "=" in s[0]:
            return None
    return segs


def _readonly(cmd: str) -> bool:
    segs = _segments(cmd)
    if segs is None:
        return False
    for s in segs:
        h = s[0]
        if h == "git":
            sub = [w for w in s[1:] if not w.startswith("-")]
            if not sub or sub[0] not in GIT_READONLY:
                return False
            if sub[0] in ("diff",) and "--output" in " ".join(s):
                return False
            continue
        if h not in READONLY_HEADS:
            return False
        if h == "find" and any(w in ("-exec", "-execdir", "-delete", "-ok", "-okdir", "-fprint", "-fprintf", "-fls")
                               for w in s):
            return False
        if h == "sort" and any(w == "-o" or w.startswith("--output") for w in s):
            return False
    return True


def _simple(cmd: str) -> Optional[tuple[Optional[str], list[str]]]:
    """(cd_dir, words) if the command is ONE simple command (optionally `cd X && `-prefixed) whose exit
    status is that program's own; None otherwise."""
    cd, rest = _split_cd(cmd)
    segs = _segments(rest)
    if segs is None or len(segs) != 1:
        return None
    return cd, segs[0]


def _strip_exit(content: str) -> tuple[Optional[int], str]:
    m = EXIT_RX.match(content)
    if m:
        return int(m.group(1)), content[m.end():]
    if re.fullmatch(r"Exit code \d+", content.strip()):
        return int(content.strip().split()[-1]), ""
    return None, content


def _read_rows(content: str) -> Optional[list[tuple[int, str]]]:
    rows = []
    for ln in content.split("\n"):
        m = ROW_RX.match(ln)
        if not m:
            return None
        rows.append((int(m.group(1)), m.group(2)))
    return rows or None


def _lines_of(text: str) -> list[str]:
    ls = text.split("\n")
    if ls and ls[-1] == "":
        ls.pop()
    return ls


# ------------------------------------------------------------------------------------------- state
@dataclass
class FileK:
    exists: bool
    src: str                       # call_id that established this knowledge
    content: Optional[str] = None  # file text; exact if `exact`, else the Read-joined lines (trailing \n unknown)
    exact: bool = False
    content_src: Optional[str] = None
    written: bool = False          # created/overwritten by Write in this session
    orig: Optional[str] = None     # content first observed before any Edit (for net-change), lines-joined


@dataclass
class DirK:
    children: set
    hidden: bool                   # listing included dotfiles
    src: str


@dataclass
class FindK:
    root: str
    name: Optional[str]
    iname: bool
    maxdepth: Optional[int]
    ftype: Optional[str]
    paths: set
    src: str


@dataclass
class State:
    files: dict = field(default_factory=dict)
    dirs: dict = field(default_factory=dict)
    finds: list = field(default_factory=list)
    git_status: Optional[tuple[str, str]] = None   # (clean|dirty, call_id)
    edits_since_status: list = field(default_factory=list)
    net_edits: dict = field(default_factory=dict)  # path -> call_id of a net-changing Edit since last status
    last_ro: dict = field(default_factory=dict)    # (cwd, command) -> (exit_status_nonzero, call_id)

    def havoc(self) -> None:
        self.files.clear(); self.dirs.clear(); self.finds.clear()
        self.git_status = None; self.edits_since_status = []; self.net_edits = {}
        self.last_ro.clear()


class Out:
    def __init__(self, calls: list[Call], disabled: set):
        self.v: dict[str, dict] = {c.cid: {"verdict": "unconstrained", "reason": "abstain:no_constraint",
                                           "confidence": 0.0, "rule": None, "conflict_with": [], "localized": True}
                                   for c in calls}
        self.disabled = disabled

    def contra(self, cid: str, rule: str, others: list[str], localized: bool, conf: float) -> None:
        if rule in self.disabled:
            return
        cur = self.v.get(cid)
        if cur is None:
            return
        if cur["verdict"] == "contradicted" and cur["confidence"] >= conf:
            return
        self.v[cid] = {"verdict": "contradicted", "reason": f"violation:{rule}", "confidence": conf,
                       "rule": rule, "conflict_with": [o for o in others if o and o != cid],
                       "localized": localized}

    def pair(self, a: str, b: str, rule: str) -> None:
        """Jointly unsatisfiable, blame not localizable: both members, confidence 0.5."""
        self.contra(a, rule, [b], False, 0.5)
        self.contra(b, rule, [a], False, 0.5)

    def support(self, cid: str, rule: str, others: list[str]) -> None:
        cur = self.v.get(cid)
        if cur is None or cur["verdict"] != "unconstrained" or rule in self.disabled:
            return
        self.v[cid] = {"verdict": "supported", "reason": f"ok:{rule}", "confidence": 0.9, "rule": rule,
                       "conflict_with": [o for o in others if o and o != cid], "localized": True}


# ------------------------------------------------------------------------------------------- the walk
def _pair_calls(turns: list[dict]) -> tuple[list[Call], list[tuple[str, Any]]]:
    """Calls in result order and the event stream [('user', None) | ('call', Call)]."""
    pend: dict[str, list[tuple[dict, str, Optional[str]]]] = {}
    calls: list[Call] = []
    events: list[tuple[str, Any]] = []
    seen_user = False
    for i, t in enumerate(turns):
        role, cid = t.get("role"), t.get("tool_call_id")
        if role == "user":
            if seen_user:
                events.append(("user", None))
            seen_user = True
        elif role == "tool_use" and isinstance(cid, str):
            inp = _parse_input(t)
            cmd = t.get("command") if isinstance(t.get("command"), str) else inp.get("command")
            pend.setdefault(cid, []).append((inp, t.get("tool_name") or "", cmd if isinstance(cmd, str) else None))
        elif role == "tool_result" and isinstance(cid, str):
            if not pend.get(cid):
                events.append(("orphan", cid))
                continue
            inp, tool, cmd = pend[cid].pop()
            c = t.get("content")
            call = Call(cid, tool, inp, cmd, i, c if isinstance(c, str) else "")
            calls.append(call)
            events.append(("call", call))
    return calls, events


def _ls_parse(words: list[str], cwd: Optional[str], body: str) -> Optional[tuple[str, set, bool]]:
    """`ls [-flags] [DIR]` -> (dir, children, hidden_included). None if not a complete listing we trust."""
    flags = "".join(w[1:] for w in words[1:] if w.startswith("-") and not w.startswith("--"))
    if any(w.startswith("--") for w in words[1:]):
        return None
    args = [w for w in words[1:] if not w.startswith("-")]
    if len(args) > 1 or re.search(r"[RdIBwT]", flags):
        return None
    base = _norm(args[0] if args else ".", cwd)
    if base is None:
        return None
    hidden = bool(re.search(r"[aA]", flags))
    long_fmt = bool(re.search(r"[lgno]", flags))
    lines = body.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    kids: set = set()
    if body == NO_OUTPUT:
        return base, kids, hidden
    if long_fmt:
        if not lines or not lines[0].startswith("total "):
            return None
        for ln in lines[1:]:
            parts = ln.split(None, 8)
            if len(parts) != 9:
                return None
            kids.add(parts[8].split(" -> ")[0])
    else:
        if re.search(r"[1CxmpFQ]", flags) and "1" not in flags:
            return None
        for ln in lines:
            if not ln or ln.startswith("ls:"):
                return None
            kids.add(ln)
    kids.discard("."); kids.discard("..")
    return base, kids, hidden


def _find_parse(words: list[str], cwd: Optional[str]) -> Optional[FindK]:
    """`find DIR [-maxdepth N] [-type f|d] [-name P|-iname P]` (any order of those) else None."""
    if len(words) < 2 or words[1].startswith("-"):
        return None
    root_raw = words[1]
    root = _norm(root_raw, cwd)
    if root is None:
        return None
    name = None; iname = False; maxdepth = None; ftype = None
    i = 2
    while i < len(words):
        w = words[i]
        if w in ("-name", "-iname") and i + 1 < len(words):
            if name is not None:
                return None
            name, iname = words[i + 1], (w == "-iname"); i += 2
        elif w == "-maxdepth" and i + 1 < len(words) and words[i + 1].isdigit():
            maxdepth = int(words[i + 1]); i += 2
        elif w == "-type" and i + 1 < len(words) and words[i + 1] in ("f", "d"):
            ftype = words[i + 1]; i += 2
        else:
            return None
    return FindK(root, name, iname, maxdepth, ftype, set(), "")


def _find_matches(fk: FindK, path: str) -> bool:
    """Would `find` list this (known regular) file?"""
    if fk.ftype == "d":
        return False
    if not path.startswith(fk.root.rstrip("/") + "/"):
        return False
    rel = path[len(fk.root.rstrip("/")) + 1:]
    if fk.maxdepth is not None and rel.count("/") + 1 > fk.maxdepth:
        return False
    if fk.name is not None:
        b = posixpath.basename(path)
        if not (fnmatch.fnmatchcase(b.lower(), fk.name.lower()) if fk.iname else fnmatch.fnmatchcase(b, fk.name)):
            return False
    return True


def _hidden(path: str, root: str) -> bool:
    rel = path[len(root.rstrip("/")) + 1:] if path.startswith(root.rstrip("/") + "/") else path
    return any(p.startswith(".") for p in rel.split("/"))


# exit-status signatures: (program, regex over the body) -> a nonzero exit is certain for that program
def _implied_nonzero(words: list[str], body: str) -> Optional[str]:
    h = words[0]
    first = body.split("\n", 1)[0]
    if re.match(rf"^(/bin/sh|sh|bash)(: line \d+)?: \d*:? ?{re.escape(h)}: (command )?not found", first):
        return "command_not_found"
    if h == "ls" and re.match(r"^ls: cannot access ", first):
        return "ls_cannot_access"
    if h in ("cat", "head", "tail", "wc") and re.match(rf"^{h}: .*(No such file or directory|cannot open)", first):
        return f"{h}_missing_file"
    if h == "grep" and body == NO_OUTPUT and not any(w in ("-q", "--quiet", "--silent") or
                                                     (w.startswith("-") and not w.startswith("--") and "q" in w)
                                                     for w in words[1:]):
        return "grep_no_match"
    if h == "git" and re.match(r"^fatal: ", first):
        return "git_fatal"
    if h == "diff" and body != NO_OUTPUT and re.match(r"^(\d+(,\d+)?[acd]\d+|--- |Only in |Binary files |Files .* differ$)", first):
        return "diff_differs"
    pyt = h == "pytest" or (h in ("python", "python3") and words[1:3] == ["-m", "pytest"])
    if pyt:
        tail = body.rstrip().rsplit("\n", 1)[-1]
        if re.match(r"^=+ .*\b\d+ (failed|errors?)\b.* in [\d.]+s.*=+$", tail):
            return "pytest_failed_summary"
        if re.match(r"^=+ no tests ran in [\d.]+s =+$", tail):
            return "pytest_no_tests"
    return None


def check_session(turns: list[dict], params: Optional[dict] = None) -> dict[str, dict]:
    params = params or {}
    disabled = set(params.get("disabled_rules", ()))
    calls, events = _pair_calls(turns)
    out = Out(calls, disabled)
    st = State()
    cwd: Optional[str] = DEFAULT_CWD

    def fk(path: str) -> Optional[FileK]:
        return st.files.get(path)

    def absent_witness(path: str) -> Optional[str]:
        """call_id of a still-valid assertion that `path` does not exist, else None."""
        k = fk(path)
        if k is not None and not k.exists:
            return k.src
        d = st.dirs.get(posixpath.dirname(path))
        b = posixpath.basename(path)
        if d is not None and b not in d.children and (d.hidden or not b.startswith(".")):
            return d.src
        for f in st.finds:
            if _find_matches(f, path) and path not in f.paths and not _hidden(path, f.root):
                return f.src
        return None

    def observe_present(c: Call, path: str) -> None:
        w = absent_witness(path)
        if w is not None and w != c.cid:
            k = fk(path)
            if k is not None and not k.exists and k.src == w:
                out.pair(c.cid, w, "presence_after_absence")
            else:  # a complete listing omitted it: blame the listing (an omission is the claim that fails)
                out.contra(w, "presence_after_absence", [c.cid], True, 0.8)
        k = fk(path)
        if k is None or not k.exists:
            st.files[path] = FileK(True, c.cid)
        add_child(path)

    def add_child(path: str) -> None:
        d = st.dirs.get(posixpath.dirname(path))
        if d is not None:
            d.children.add(posixpath.basename(path))
        for f in st.finds:
            if _find_matches(f, path):
                f.paths.add(path)

    def observe_absent(c: Call, path: str) -> None:
        k = fk(path)
        if k is not None and k.exists:
            out.contra(c.cid, "read_absent", [k.src], True, 0.9)
            return
        st.files[path] = FileK(False, c.cid)

    def check_content(c: Call, path: str, text: str, exact: bool) -> None:
        """`text` is the file content shown by this call (exact bytes for cat, joined lines for Read)."""
        k = fk(path)
        if k is not None and k.exists and k.content is not None:
            a, b = k.content, text
            if k.exact and exact:
                ok = a == b
            else:
                ok = a.rstrip("\n") == b.rstrip("\n") if (k.exact or exact) else a == b
            if ok:
                out.support(c.cid, "read_content", [k.content_src])
            else:
                # blame: content from the agent's own Write/Edit is established by the write itself, so the
                # reader is the false one; read-vs-read cannot be localized.
                if k.content_src and k.written:
                    out.contra(c.cid, "read_content", [k.content_src], True, 0.9)
                else:
                    out.pair(c.cid, k.content_src, "read_content")
                st.files[path] = FileK(True, c.cid, None)
                return
        orig = k.orig if (k is not None and k.exists and k.content is not None) else text.rstrip("\n")
        written = bool(k.written) if k is not None and k.exists and k.content is not None else False
        st.files[path] = FileK(True, k.src if k is not None and k.exists else c.cid, text, exact, c.cid,
                               written, orig)

    for kind, c in events:
        if kind == "user":
            st.havoc(); cwd = DEFAULT_CWD if cwd is None else cwd
            continue
        if kind == "orphan":
            continue
        res = c.content
        tool = c.tool
        if tool == "Read":
            path = _norm(c.inp.get("file_path"), cwd)
            if path is None:
                continue
            if res.startswith("<tool_use_error>"):
                if "File does not exist." in res:
                    observe_absent(c, path)
                continue
            observe_present(c, path)
            if res.startswith("<system-reminder>Warning: the file exists but the contents are empty."):
                check_content(c, path, "", False)
                continue
            if TRUNC_RX.search(res):
                st.files[path] = FileK(True, c.cid)  # no content knowledge from truncated output
                continue
            rows = _read_rows(res)
            try:
                off = int(c.inp.get("offset") or 1); lim = int(c.inp.get("limit") or 2000)
            except (TypeError, ValueError):
                continue
            off = max(off, 1)
            if rows is None or [n for n, _ in rows] != list(range(off, off + len(rows))):
                st.files[path] = FileK(True, c.cid)
                continue
            linetrunc = any(len(t) >= READ_MAX_LINE for _, t in rows)
            k = fk(path)
            if off == 1 and len(rows) < lim and not linetrunc:
                check_content(c, path, "\n".join(t for _, t in rows), False)
            elif k is not None and k.exists and k.content is not None and not linetrunc:
                want = _lines_of(k.content)[off - 1: off - 1 + lim]
                if want == [t for _, t in rows]:
                    out.support(c.cid, "read_content", [k.content_src])
                else:
                    if k.written:
                        out.contra(c.cid, "read_content", [k.content_src], True, 0.9)
                    else:
                        out.pair(c.cid, k.content_src, "read_content")
                    st.files[path] = FileK(True, c.cid)
            continue

        if tool == "Write":
            path = _norm(c.inp.get("file_path"), cwd)
            content = c.inp.get("content")
            if path is None or not isinstance(content, str):
                st.havoc(); continue
            st.last_ro.clear()
            k = fk(path)
            if res.startswith("File created successfully at: "):
                if k is not None and k.exists:   # the real tool says "has been updated" for an existing file
                    if k.written:
                        out.contra(c.cid, "write_ack_state", [k.src], True, 0.9)
                    else:
                        out.pair(c.cid, k.src, "write_ack_state")
                st.files[path] = FileK(True, c.cid, content, True, c.cid, True, None)
                add_child(path)
                st.edits_since_status.append(c.cid)
            elif res.startswith("The file ") and res.endswith(" has been updated."):
                w = absent_witness(path)
                if w is not None:   # "updated" means the file existed; an absence assertion is still in force
                    out.pair(c.cid, w, "write_ack_state")
                st.files[path] = FileK(True, c.cid, content, True, c.cid, True, None)
                add_child(path)
                st.edits_since_status.append(c.cid)
            else:
                st.havoc()
            continue

        if tool == "Edit":
            path = _norm(c.inp.get("file_path"), cwd)
            old, new = c.inp.get("old_string"), c.inp.get("new_string")
            ra = bool(c.inp.get("replace_all"))
            if path is None or not isinstance(old, str) or not isinstance(new, str):
                st.havoc(); continue
            k = fk(path)
            st.last_ro.clear()
            if res.startswith("The file ") and res.endswith(" has been updated."):
                w = absent_witness(path)
                if w is not None:
                    kk = fk(path)
                    if kk is not None and not kk.exists:
                        out.pair(c.cid, w, "presence_after_absence")
                    else:
                        out.contra(w, "presence_after_absence", [c.cid], True, 0.8)
                if k is not None and k.exists and k.content is not None and old:
                    variants = [k.content] if k.exact else [k.content, k.content + "\n"]
                    counts = [v.count(old) for v in variants]
                    if max(counts) == 0:
                        if k.written:
                            out.contra(c.cid, "edit_unsatisfiable", [k.content_src], True, 0.9)
                        else:
                            out.pair(c.cid, k.content_src, "edit_unsatisfiable")
                        st.files[path] = FileK(True, c.cid)
                        st.edits_since_status.append(c.cid)
                        continue
                    if not ra and min(counts) > 1:
                        if k.written:
                            out.contra(c.cid, "edit_unsatisfiable", [k.content_src], True, 0.9)
                        else:
                            out.pair(c.cid, k.content_src, "edit_unsatisfiable")
                        st.files[path] = FileK(True, c.cid)
                        st.edits_since_status.append(c.cid)
                        continue
                    out.support(c.cid, "edit_unsatisfiable", [k.content_src])
                    vi = counts.index(max(counts)) if not k.exact else 0
                    base = variants[vi]
                    upd = base.replace(old, new) if ra else base.replace(old, new, 1)
                    if not k.exact and vi == 1:
                        upd = upd[:-1] if upd.endswith("\n") else upd
                    st.files[path] = FileK(True, k.src, upd, k.exact, c.cid, k.written, k.orig)
                    if not k.written and k.orig is not None and path.startswith(DEFAULT_CWD + "/"):
                        if upd.rstrip("\n") != k.orig.rstrip("\n"):
                            st.net_edits[path] = c.cid
                        else:
                            st.net_edits.pop(path, None)
                else:
                    st.files[path] = FileK(True, c.cid)
                    add_child(path)
                st.edits_since_status.append(c.cid)
            elif "String to replace not found in file." in res:
                if k is not None and k.exists and k.content is not None and old and \
                        old in k.content and (k.exact or True):
                    out.pair(c.cid, k.content_src, "edit_false_failure")
            elif "File does not exist." in res:
                observe_absent(c, path)
            elif res.startswith("<tool_use_error>") and ("Found " in res or "No changes to make" in res
                                                         or "InputValidationError" in res):
                pass
            else:
                st.havoc()
            continue

        if tool != "Bash" or not c.command:
            continue   # Board*/Submit and other host-side tools do not touch the filesystem
        cmd = c.command
        code, body = _strip_exit(res)
        trunc = bool(TRUNC_RX.search(body))
        cd, rest = _split_cd(cmd)
        run_cwd = _norm(cd, cwd) if cd else cwd
        if cd and run_cwd is None:
            run_cwd = None
        simple = _simple(cmd)

        # --- exit_status: an output that a nonzero exit always accompanies, delivered as success
        stdout_redirected = ">" in re.sub(r"2>&1|2>\s*/dev/null", "", cmd)
        if code is None and simple is not None and not trunc and not stdout_redirected:
            why = _implied_nonzero(simple[1], body)
            if why:
                out.contra(c.cid, "exit_status", [], True, 0.95)

        ro = _readonly(rest)
        # --- rerun_exit: same read-only command, same cwd, nothing between -> same exit status
        if ro and run_cwd is not None and code != 124 and "Command timed out" not in body                 and not _foreign_paths(rest):
            key = (run_cwd, rest)
            prev = st.last_ro.get(key)
            if prev is not None and prev[0] != (code is not None):
                fail_cid, ok_cid = (prev[1], c.cid) if prev[0] else (c.cid, prev[1])
                out.contra(ok_cid, "rerun_exit", [fail_cid], True, 0.8)
            st.last_ro[key] = (code is not None, c.cid)

        if not ro:
            st.havoc()
            # cwd after a non-modelled command: known only for a successful `cd X && ...` with no other cd
            if "cd" in (_lex(rest) or ["cd"]):
                cwd = None
            elif cd:
                cwd = run_cwd if code is None else None
            continue
        segs_ro = _segments(rest) or []
        if any(sg[0] == "cd" for sg in segs_ro):
            if len(segs_ro) == 1 and len(segs_ro[0]) == 2 and code is None and run_cwd is not None:
                cwd = _norm(segs_ro[0][1], run_cwd)
            else:
                cwd = None
            continue
        if cd:
            cwd = run_cwd if code is None else None
        if run_cwd is None or trunc:
            continue
        if simple is None and len(segs_ro) == 2 and segs_ro[1] == ["sort"] and segs_ro[0][0] == "find":
            simple = (cd, segs_ro[0])
        if simple is None:
            continue
        words = simple[1]
        h = words[0]
        if h == "ls":
            args = [w for w in words[1:] if not w.startswith("-")]
            if code is not None:
                for m in re.finditer(r"^ls: cannot access '?([^':\n]+?)'?: No such file or directory$", body, re.M):
                    p = _norm(m.group(1), run_cwd)
                    if p is not None:
                        observe_absent(c, p)
                continue
            parsed = _ls_parse(words, run_cwd, body)
            if parsed is None:
                continue
            base, kids, hidden = parsed
            if len(args) == 1:
                tgt = _norm(args[0], run_cwd)
                k = fk(tgt) if tgt else None
                if k is not None and k.exists and k.content is not None:
                    continue  # `ls FILE`, not a directory listing
            # listing_missing: a file established as existing in `base` must be listed
            missing = []
            for p, k in st.files.items():
                if k.exists and posixpath.dirname(p) == base and (hidden or not posixpath.basename(p).startswith(".")):
                    if posixpath.basename(p) not in kids:
                        missing.append(k.src)
            if missing:
                out.contra(c.cid, "listing_missing", missing[:6], True, 0.9)
            for kid in kids:
                pp = posixpath.join(base, kid)
                kk = fk(pp)
                if kk is not None and not kk.exists:
                    out.pair(c.cid, kk.src, "presence_after_absence")
                if kk is None or not kk.exists:
                    st.files[pp] = FileK(True, c.cid)
            st.dirs[base] = DirK(set(kids), hidden, c.cid)
            continue
        if h == "find" and code is None:
            f = _find_parse(words, run_cwd)
            if f is None:
                continue
            f.src = c.cid
            lines = [] if body == NO_OUTPUT else _lines_of(body)
            if any(ln.startswith("find:") for ln in lines):
                continue
            for ln in lines:
                p = _norm(ln, run_cwd)
                if p is not None:
                    f.paths.add(p)
            missing = [k.src for p, k in st.files.items()
                       if k.exists and k.content is not None and _find_matches(f, p) and p not in f.paths
                       and not _hidden(p, f.root)]
            if missing:
                out.contra(c.cid, "listing_missing", missing[:6], True, 0.9)
            st.finds.append(f)
            continue
        if h == "cat" and len(words) == 2 and not words[1].startswith("-"):
            p = _norm(words[1], run_cwd)
            if p is None:
                continue
            if code is not None:
                if re.match(r"^cat: .*No such file or directory$", body.strip()):
                    observe_absent(c, p)
                continue
            observe_present(c, p)
            text = "" if body == NO_OUTPUT else body
            if body == NO_OUTPUT:
                k = fk(p)
                if k is not None and k.content is not None and k.content.strip() == "":
                    out.support(c.cid, "read_content", [k.content_src])
                elif k is not None and k.content is not None and k.content.strip():
                    if k.written:
                        out.contra(c.cid, "read_content", [k.content_src], True, 0.9)
                    else:
                        out.pair(c.cid, k.content_src, "read_content")
                continue
            check_content(c, p, text, True)
            continue
        if h == "git" and [w for w in words[1:] if not w.startswith("-")][:1] == ["status"] and code is None:
            if len(words) != 2:
                continue
            if "nothing to commit, working tree clean" in body:
                state = "clean"
            elif body.startswith("On branch") and ("Changes not staged" in body or "Changes to be committed" in body
                                                   or "Untracked files" in body):
                state = "dirty"
            else:
                continue
            prev = st.git_status
            if prev is not None and not st.edits_since_status and prev[0] != state:
                blame, other = (c.cid, prev[1]) if state == "clean" else (prev[1], c.cid)
                out.contra(blame, "git_status_flip", [other], True, 0.8)
            if state == "clean" and st.net_edits:
                srcs = list(st.net_edits.values())
                out.contra(c.cid, "git_clean_after_edit", srcs[:6], True, 0.8)
            st.git_status = (state, c.cid)
            st.edits_since_status = []
            st.net_edits = {}
            continue
    return out.v


def check_call(turns: list[dict], tool_call_id: str, claimed_output: Optional[str] = None,
               params: Optional[dict] = None) -> dict:
    """Verdict for one call; with `claimed_output`, that call's tool_result content is replaced first."""
    if claimed_output is not None:
        turns = [dict(t, content=claimed_output) if (t.get("role") == "tool_result"
                                                     and t.get("tool_call_id") == tool_call_id) else t
                 for t in turns]
    return check_session(turns, params).get(tool_call_id, {"verdict": "unconstrained",
                                                           "reason": "missing:call_not_in_session",
                                                           "confidence": 0.0, "rule": None,
                                                           "conflict_with": [], "localized": True})


__all__ = ["check_session", "check_call", "RULES", "CHECK_NAME", "CHECK_VERSION"]
