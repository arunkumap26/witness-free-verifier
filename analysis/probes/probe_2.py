"""Phase B, Probe 2: knowledge precedence (pre-registered in analysis/prereg.json `probe2`).

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.probe_2
Debug run on split A (writes to a scratch path only, never to analysis/out):
                               PYTHONIOENCODING=utf-8 python -m analysis.probes.probe_2 --split A --out <path>

Reads analysis/cache/<corpus>_B.parquet (+ swechat_population.parquet for the format; aiv_cc_A.parquet session ids
only, for the aiv_cc overlap count that prereg global.aiv_cc_rule requires). Writes RAW NUMBERS ONLY to
analysis/out/probe_2.json and a byte-identical copy to analysis/out/phase_b/probe_2.json (prereg output_contract).

Question (prereg): in honest logs, how often does an agent use a path, symbol or config key before anything in its
visible record could have told it? Every definition (extraction, normalisation, error classes, depth, workspace root)
is imported from analysis/probes/prereg_common.py, whose sha256 is checked against prereg.json before anything runs.
Every threshold is read from prereg.json. Deviations from the prereg text are listed in DEVIATIONS below and copied
into the JSON. Interpretation lives in analysis/notes/probe_2.md, never here.

cc_local is private: only aggregates leave this script (tool names through pc.private_key, no paths/text/tokens).
"""
import argparse
import gc
import hashlib
import json
import math
import re
import string
import sys
import time
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from analysis.lib import stats
from analysis.probes import prereg_common as pc

ROOT = pc.ROOT
PREREG_PATH = ROOT / "analysis" / "prereg.json"
SPEC_PATH = ROOT / "analysis" / "probes" / "prereg_common.py"
OUT = ROOT / "analysis" / "out" / "probe_2.json"
OUT_COPY = ROOT / "analysis" / "out" / "phase_b" / "probe_2.json"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


PR = json.load(open(PREREG_PATH, encoding="utf-8"))
P2 = PR["probe2"]
FULL = list(P2["units"]["full"])
INCOMPLETE = list(P2["units"]["antecedents_incomplete"])
NOT_TESTABLE = list(P2["units"]["not_testable"])
RUN_UNITS = FULL + INCOMPLETE
D_UNIT = {u: v["D"] for u, v in PR["resolved"]["probe2"]["depth_threshold"].items()
          if isinstance(v, dict) and u not in ("pooled",) and "D" in v}
ACCESS_READ = set(PR["constants"]["ACCESS_READ"])
ACCESS_EDIT = set(PR["constants"]["ACCESS_EDIT"])
MIN_RATE = PR["global"]["min_n"]["rate_reportable"]  # den_min 30, sessions_min 5
QMIN = PR["global"]["min_n"]["quantile_reportable"]

# ---- thresholds parsed from the prereg.json text (never typed here), asserted against the PREREG.md values
_vr = P2["verdict"]["per_unit_main_thread"]
_m = re.search(r"ALIVE if S_deep <= ([\d.]+) and its CI hi <= ([\d.]+); WEAK if S_deep <= ([\d.]+); DEAD if S_deep > ([\d.]+)",
               _vr)
T_ALIVE, T_ALIVE_HI, T_WEAK, T_DEAD = (float(x) for x in _m.groups())
assert (T_ALIVE, T_ALIVE_HI, T_WEAK, T_DEAD) == (0.05, 0.10, 0.20, 0.20)
_mn = re.search(r"S_deep verdict needs >= (\d+) deep first-try accesses from >= (\d+) sessions; S_path_any >= (\d+) "
                r"first mentions from >= (\d+) sessions", P2["statistics"]["min_n"])
MIN_DEEP_N, MIN_DEEP_S, MIN_ANY_N, MIN_ANY_S = (int(x) for x in _mn.groups())
assert (MIN_DEEP_N, MIN_DEEP_S, MIN_ANY_N, MIN_ANY_S) == (100, 20, 200, 20)
_mi = re.search(r"main-thread S_symbol_ref must be <= (\d+\.\d+)", P2["statistics"]["instrument_check"])
T_INSTRUMENT = float(_mi.group(1))
assert T_INSTRUMENT == 0.10
SMALL_N_SESSIONS = 30  # global.min_n.small_n_label: "< 30 B sessions in the verdict population"
assert "< 30 B sessions" in PR["global"]["min_n"]["small_n_label"]

RX_READ_SHELL = re.compile(pc.RX["read_shell"])
RX_ENUM_SHELL = re.compile(pc.RX["enum_shell"])
PATHCHARS = frozenset(string.ascii_letters + string.digits + "_.-")
WORDCHARS = frozenset(string.ascii_letters + string.digits + "_")
ASCII_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)
DRIVE = re.compile(r"^[a-z]:/")
SOURCES = ("result", "user", "system", "parent_prompt", "peer")
REF_CLASSES = ("path", "symbol_ref", "symbol_shell", "symbol_search", "env_var", "cfg_key")
ORDINAL_BINS = [(0, 0, "0"), (1, 4, "1-4"), (5, 19, "5-19"), (20, 99, "20-99"), (100, 499, "100-499"),
                (500, 10 ** 9, "500+")]

DEVIATIONS = [
    {"item": "output path",
     "prereg_said": "data_rules.output_contract: write to analysis/out/phase_b/<probe>.json",
     "what_you_did": "wrote analysis/out/probe_2.json (the path the Phase B task specified) and a byte-identical copy at "
                     "analysis/out/phase_b/probe_2.json",
     "why": "the task brief and the prereg name different paths; both are satisfied",
     "effect_on_verdict": "none"},
    {"item": "drive-letter path keys matched case-insensitively",
     "prereg_said": "extraction.path_normalisation lowercases paths with a drive letter; sourcing.text_normalisation does "
                    "not lowercase antecedent text; path_match is a plain occurrence test",
     "what_you_did": "a path key that came from a drive-letter path (normalised form starts with '[a-z]:/') is matched "
                     "against an ASCII-lowercased copy of the antecedent text (same for its enumeration basename). The "
                     "literal case-sensitive variant is computed too and reported as `*_literal_case` next to every "
                     "statistic it changes",
     "why": "as written, a Windows path containing any uppercase letter (e.g. C:\\Repo\\README.md) can never match its "
            "own antecedent, so the rule would count it unsourced by construction; lowercasing drive paths only makes "
            "sense as case-insensitive matching (Windows paths are case-insensitive)",
     "effect_on_verdict": "computed per unit in units.<unit>.strata.<s>.verdict_sensitivity.literal_case"},
    {"item": "symbol/env/cfg references that contain 'REDACTED'",
     "prereg_said": "only paths containing a redaction marker are excluded ('redacted_path'); antecedent text gets "
                    "REDACTED -> '<R>'",
     "what_you_did": "symbol_ref/symbol_shell/symbol_search/env_var/cfg_key references whose string contains 'REDACTED' "
                     "are counted as 'redacted_ref' and excluded from the rates, mirroring the path rule",
     "why": "after the pre-registered antecedent normalisation, an identifier such as REDACTED_API_KEY can never "
            "match its antecedent ('<R>'), so it would be unsourced by construction; it is a release artefact, not an "
            "agent reference",
     "effect_on_verdict": "none on S_deep/S_path_any (paths only); counts reported in extraction.redacted_ref; the "
                          "instrument check with these references counted as unsourced is reported as "
                          "instrument_check.including_redacted_refs"},
    {"item": "enumeration directory argument (underspecified)",
     "prereg_said": "sourcing.path_enumeration: 'extracted directory argument' of glob/ls/grep or an enum_shell command",
     "what_you_did": "glob/ls/grep tools: every structured PATH_KEYS value of the call (pc.structured_paths); "
                     "enum_shell commands: every token after the matched program word up to the next ; & | (quotes "
                     "stripped, tokens starting with '-' skipped), normalised with pc.normalize_path. A token that "
                     "normalises to the cwd ('.', './') or no token at all counts as 'no directory argument'. Match: "
                     "the path's parent component equals a directory argument's last component, or the path has one "
                     "component and the enumeration has no directory argument; the basename must occur in the "
                     "enumeration's own result text (first result by seq) with path boundaries",
     "why": "the prereg does not say how to extract the directory argument from a shell command",
     "effect_on_verdict": "enumeration-only sourcing counts are reported (sourced_by.enumeration_only); see notes"},
    {"item": "Codex sub-agent nested prompt",
     "prereg_said": "stream: parent_prompt = CC system event with extra.nested_prompt, or OpenCode child session's first "
                    "user/system text; Codex not named",
     "what_you_did": "in Codex sub-agent threads, assistant rows whose text is an inter-agent envelope (JSON object with "
                     "'author' and 'recipient') are the source 'parent_prompt'; Codex user/system rows stay "
                     "'user'/'system'",
     "why": "Codex stores the spawning agent's message (and later agent notifications) as assistant-kind envelope rows; "
            "they are text the sub-agent received, not its own text, so treating them as 'never a source' would "
            "inflate unsourced by construction",
     "effect_on_verdict": "Codex subagent stratum only; see its verdict cell"},
    {"item": "workspace root for child sessions with no main thread",
     "prereg_said": "deep_first_try.depth: root from the absolute access paths of the session's main thread",
     "what_you_did": "OpenCode child sessions and Codex sub-agent rollouts are separate session_ids with no main "
                     "thread; for them the same root rule is applied to the sub-agent thread's own absolute access "
                     "paths",
     "why": "otherwise every absolute access path in those threads is depth_unknown by construction",
     "effect_on_verdict": "subagent strata of swechat/codex and swechat/opencode only"},
    {"item": "deep first-try access population",
     "prereg_said": "deep_first_try.access_call: 'first access in the thread to a path_key by an access tool'; the A "
                    "calibration that set D_unit counted only accesses that were also the key's first mention",
     "what_you_did": "the verdict uses the prereg text (first access by an access tool; sourcing evaluated at that "
                     "access call); the calibration's population (first mention that is an access) is reported as "
                     "variant first_mention_access_only",
     "why": "the JSON text wins over the calibration code (PREREG.md header); both are shown",
     "effect_on_verdict": "computed per unit in verdict_sensitivity.first_mention_access_only"},
    {"item": "first-try success and CC permission/interrupt markers",
     "prereg_said": "first_try_success = result is not an error under error_definitions.<unit>.primary; the CC primary "
                    "excludes cc_permission_denied / cc_interrupt_reject from errors",
     "what_you_did": "applied literally (a denied or interrupted read counts as 'not an error'); the S_deep variant that "
                     "drops those accesses is reported as variant excluding_permission_interrupt",
     "why": "literal rule kept; the variant shows whether it matters",
     "effect_on_verdict": "computed per unit in verdict_sensitivity.excluding_permission_interrupt"},
    {"item": "post-hoc descriptive additions (disclosure, not a rule change)",
     "prereg_said": "nothing (these statistics are not pre-registered)",
     "what_you_did": "after the first Phase B output was seen, added (a) strata.<s>.post_hoc_descriptive: S_path_any "
                     "without creation targets (Write file_path, apply_patch Add File / Move to) and first-mention "
                     "paths by access kind; (b) post_hoc_unsourced_trace / post_hoc_unsourced_deep_trace: among "
                     "unsourced references, the share whose basename alone occurs in an earlier source text and the "
                     "share whose key occurs in the thread's own earlier call args",
     "why": "to show whether the fallback S_path_any is driven by creation targets (unsourced by construction) and "
            "what kind of trace unsourced references leave; neither feeds a verdict",
     "effect_on_verdict": "none (no verdict reads them; verdicts identical before and after the addition)"},
]


DEBUG = None  # debug hook (scratch runs only): list that receives (unit, st, session, cls, key, seq, unsourced)
DEBUG_ACCESS = None  # debug hook (scratch runs only): first-access rows with their path (never for cc_local)


# ====================================================================================================== sources
class Src:
    """Concatenated antecedent text of one source type of one thread, with per-event offsets.

    Events are joined by '\\n', which is a boundary character for both the path and the symbol match, so a match
    never spans two events and the text edge of every event is a boundary (prereg sourcing.path_match)."""
    __slots__ = ("seqs", "starts", "ends", "full", "_low")

    def __init__(self, items):
        items = sorted(items, key=lambda x: x[0])
        self.seqs = [s for s, _ in items]
        self.starts, self.ends = [], []
        pos = 0
        parts = []
        for _, t in items:
            self.starts.append(pos)
            parts.append(t)
            pos += len(t)
            self.ends.append(pos)
            pos += 1
        self.full = "\n".join(parts)
        self._low = None

    def low(self):
        if self._low is None:
            self._low = self.full.translate(ASCII_LOWER)
        return self._low

    def before(self, seq):
        """(end offset of the antecedent prefix, number of events with seq < seq)."""
        k = bisect_left(self.seqs, seq)
        return (self.ends[k - 1] if k else -1), k


def _ok_path(full, i, j):
    return (i == 0 or full[i - 1] == "/" or full[i - 1] not in PATHCHARS) and (j >= len(full) or full[j] not in PATHCHARS)


def _ok_word(full, i, j):
    return (i == 0 or full[i - 1] not in WORDCHARS) and (j >= len(full) or full[j] not in WORDCHARS)


def find_first(full, key, end, okf):
    if end <= 0 or not key:
        return -1
    L = len(key)
    i = full.find(key, 0, end)
    while i != -1:
        if okf(full, i, i + L):
            return i
        i = full.find(key, i + 1, end)
    return -1


def find_last(full, key, end, okf):
    if end <= 0 or not key:
        return -1
    L = len(key)
    i = full.rfind(key, 0, end)
    while i != -1:
        if okf(full, i, i + L):
            return i
        i = full.rfind(key, 0, i + L - 1)
    return -1


def env_obj(e):
    if isinstance(e, str) and e:
        try:
            x = json.loads(e)
            return x if isinstance(x, dict) else {}
        except ValueError:
            return {}
    return {}


def is_envelope(text):
    if not text or not text.startswith('{"author"'):
        return False
    try:
        x = json.loads(text)
    except ValueError:
        return False
    return isinstance(x, dict) and "author" in x and "recipient" in x


def shell_tokens_after(cmd, m):
    """Tokens after an enum_shell match up to the next ; & | (directory-argument extraction, see DEVIATIONS)."""
    rest = cmd[m.end():]
    seg = re.split(r"[;&|\n]", rest, maxsplit=1)[0]
    toks = []
    for t in seg.split():
        t = t.strip("'\"`")
        if not t or t.startswith("-"):
            continue
        toks.append(t)
    return toks


def dir_args_from_paths(paths):
    """(set of last components, no_dir flag) from a list of raw directory arguments."""
    lasts, no_dir = set(), not paths
    for raw in paths:
        p = pc.normalize_path(raw) if raw else None
        comps = pc.path_components(p) if p else []
        if not comps:
            no_dir = True
            continue
        last = comps[-1]
        lasts.add(last)
        if DRIVE.match(p or ""):
            lasts.add(last.translate(ASCII_LOWER))
    return lasts, no_dir


# ====================================================================================================== unit pass
def process_unit(unit, u, A):
    """u: the unit's IR rows (kinds user/system/assistant/call/result), any order. Appends rows to A (accumulators)."""
    u = u.sort_values(["session_id", "seq"], kind="stable").reset_index(drop=True)
    sid = u.session_id.to_numpy(dtype=object)
    seq = u.seq.to_numpy(dtype=np.int64)
    kind = pc.sobj(u.kind)
    tool = pc.sobj(u.tool)
    tool_raw = pc.sobj(u.tool_raw)
    call_id = pc.sobj(u.call_id)
    args = pc.sobj(u.args)
    command = pc.sobj(u.command)
    text = pc.sobj(u.text)
    stderr = pc.sobj(u.stderr) if "stderr" in u else [None] * len(u)
    native = u.native_error.astype(object).tolist()
    exit_code = u.exit_code.astype(object).tolist()
    sub = u.is_subagent.astype("boolean").fillna(False).to_numpy(dtype=bool)
    agent = pc.sobj(u.agent_id)
    extra = pc.sobj(u.extra)
    stratum = pc.sobj(u.stratum) if "stratum" in u else [None] * len(u)
    private = unit == "cc_local"
    is_whowhen = unit == "whowhen"
    is_codex = unit == "swechat/codex"
    is_opencode = unit == "swechat/opencode"

    bounds = np.flatnonzero(np.r_[True, sid[1:] != sid[:-1], True])
    for bi in range(len(bounds) - 1):
        a, b = int(bounds[bi]), int(bounds[bi + 1])
        s = sid[a]
        A["sessions"].add(s)
        # first result by seq per call_id (prereg data_rules.join)
        rmap = {}
        for i in range(a, b):
            if kind[i] == "result" and call_id[i] is not None and call_id[i] not in rmap:
                rmap[call_id[i]] = i
        threads = defaultdict(list)
        for i in range(a, b):
            threads[(bool(sub[i]), agent[i] or "" if sub[i] else "")].append(i)
        has_main_calls = any(kind[i] == "call" for i in threads.get((False, ""), []))
        session_access_rows = []
        root_paths_main, root_paths_thread = [], defaultdict(list)
        for tkey, idx in threads.items():
            is_sub = tkey[0]
            st = "sub" if is_sub else "main"
            if any(kind[i] == "call" for i in idx):
                A["threads"][st].add((s, tkey))
            # ---------------------------------------------------------------- sources of this thread
            items = {k: [] for k in SOURCES}
            whowhen_assist = []  # (seq, speaker, text) for peer sources
            first_us = None
            if is_sub and is_opencode:
                us = [i for i in idx if kind[i] in ("user", "system")]
                first_us = us[0] if us else None
            for i in idx:
                k = kind[i]
                t = text[i]
                if k == "result":
                    tt = (t or "") + ("\n" + stderr[i] if stderr[i] else "")
                    if tt:
                        items["result"].append((int(seq[i]), pc.norm_text(tt)))
                    continue
                if k not in ("user", "system", "assistant"):
                    continue
                ex = env_obj(extra[i]) if (extra[i] and k != "result") else {}
                if is_whowhen:
                    if ex.get("task_prompt") is True and t:
                        items["user"].append((int(seq[i]), pc.norm_text(t)))
                    if k == "assistant" and t:
                        whowhen_assist.append((int(seq[i]), ex.get("agent"), pc.norm_text(t)))
                if not t:
                    continue
                if is_sub and is_opencode and i == first_us:
                    items["parent_prompt"].append((int(seq[i]), pc.norm_text(t)))
                    continue
                if k == "system":
                    if ex.get("nested_prompt") is True:
                        if is_sub:
                            items["parent_prompt"].append((int(seq[i]), pc.norm_text(t)))
                        continue  # never a 'system' source (prereg sourcing.sources.system)
                    items["system"].append((int(seq[i]), pc.norm_text(t)))
                elif k == "user":
                    items["user"].append((int(seq[i]), pc.norm_text(t)))
                elif k == "assistant" and is_codex and is_sub and is_envelope(t):
                    items["parent_prompt"].append((int(seq[i]), pc.norm_text(t)))
            srcs = {k: Src(v) for k, v in items.items() if v}
            own_items = [(int(seq[i]), pc.norm_text(args[i])) for i in idx if kind[i] == "call" and args[i]]
            own_src = Src(own_items) if own_items else None  # POST HOC diagnostic only (own args are never a source)
            peer_cache = {}

            def peer_src(speaker):
                if speaker not in peer_cache:
                    peer_cache[speaker] = Src([(q, t) for q, sp, t in whowhen_assist if sp != speaker]) \
                        if whowhen_assist else None
                return peer_cache[speaker]

            # ---------------------------------------------------------------- enumerations of this thread
            enums = []  # (result_seq, lasts, no_dir, Src-like text)
            calls_idx = [i for i in idx if kind[i] == "call"]
            parsed = {}
            for i in calls_idx:
                try:
                    obj = json.loads(args[i]) if isinstance(args[i], str) else None
                except ValueError:
                    obj = None
                key = pc.tool_key(unit, tool[i], tool_raw[i])
                parsed[i] = (obj, key)
                dirs = None
                if key in ("glob", "ls", "grep"):
                    dirs = [p for p, _ in (pc.structured_paths(obj, tool_raw[i]) if isinstance(obj, dict) else [])]
                    lasts, no_dir = dir_args_from_paths(dirs)
                else:
                    if key == "shell" or key in pc.CODEX_SHELL_RAW or key.endswith("__bash"):
                        sh = pc.shell_command(unit, key, obj, command[i])
                        if sh:
                            ms = list(RX_ENUM_SHELL.finditer(sh))
                            if ms:
                                raw = []
                                for m in ms:
                                    raw += shell_tokens_after(sh, m) or ["."]
                                lasts, no_dir = dir_args_from_paths(raw)
                                dirs = raw
                if dirs is None:
                    continue
                ri = rmap.get(call_id[i])
                if ri is None or not (text[ri] or stderr[ri]):
                    continue
                rt = pc.norm_text((text[ri] or "") + ("\n" + stderr[ri] if stderr[ri] else ""))
                enums.append((int(seq[ri]), lasts, no_dir, rt))
            enums.sort(key=lambda x: x[0])
            enum_seqs = [e[0] for e in enums]
            enum_low = {}

            def enum_hit(p_key, ci, cseq):
                comps = p_key.split("/")
                base = comps[-1]
                parent = comps[-2] if len(comps) >= 2 else None
                k = bisect_left(enum_seqs, cseq)
                for j in range(k):
                    _, lasts, no_dir, rt = enums[j]
                    if parent is not None:
                        if parent not in lasts:
                            continue
                    elif not no_dir:
                        continue
                    if ci:
                        if j not in enum_low:
                            enum_low[j] = rt.translate(ASCII_LOWER)
                        txt = enum_low[j]
                    else:
                        txt = rt
                    if find_first(txt, base, len(txt) + 1, _ok_path) >= 0:
                        return True
                return False

            def sourcing(ref_kind, key_, cseq, speaker, ci):
                """dict source -> bool; plus 'lag' (result events back to the most recent result match) and the
                literal-case unsourced flag for drive-letter keys."""
                okf = _ok_path if ref_kind == "path" else _ok_word
                fl = {}
                lag = -1
                lit_any = False
                for name in SOURCES:
                    src = peer_src(speaker) if (name == "peer" and is_whowhen) else srcs.get(name)
                    if src is None:
                        fl[name] = False
                        continue
                    end, k = src.before(cseq)
                    if end < 0:
                        fl[name] = False
                        continue
                    txt = src.low() if ci else src.full
                    hit = find_first(txt, key_, end, okf) >= 0
                    fl[name] = hit
                    if ci and not lit_any:
                        # literal (case-sensitive) variant: drive keys are lowercase; the literal rule searches raw text
                        lit_any = find_first(src.full, key_, end, okf) >= 0
                    elif not ci and hit:
                        lit_any = True
                    if name == "result" and hit:
                        pos = find_last(txt, key_, end, okf)
                        ev = bisect_right(src.starts, pos) - 1
                        lag = k - ev
                if ref_kind == "path":
                    fl["enumeration"] = enum_hit(key_, ci, cseq) if enums else False
                    lit_enum = enum_hit(key_, False, cseq) if (ci and enums) else fl["enumeration"]
                else:
                    fl["enumeration"] = False
                    lit_enum = False
                uns = not any(fl.values())
                uns_lit = not (lit_any or lit_enum) if ci else uns
                # POST HOC diagnostics for unsourced references (descriptive only, never change `uns`):
                # base_seen = the basename alone occurs in an earlier source text (path refs with >= 2 components);
                # own_args = the key occurs in the thread's own earlier call args.
                base_seen = own = False
                if uns:
                    if ref_kind == "path" and "/" in key_:
                        base = key_.rsplit("/", 1)[1]
                        for name in SOURCES:
                            src = peer_src(speaker) if (name == "peer" and is_whowhen) else srcs.get(name)
                            if src is None:
                                continue
                            end, _ = src.before(cseq)
                            if find_first(src.low() if ci else src.full, base, end, _ok_path) >= 0:
                                base_seen = True
                                break
                    if own_src is not None:
                        end, _ = own_src.before(cseq)
                        own = find_first(own_src.low() if ci else own_src.full, key_, end, okf) >= 0
                fl["_base_seen"], fl["_own_args"] = base_seen, own
                return fl, uns, uns_lit, lag

            # ---------------------------------------------------------------- calls in seq order
            first = defaultdict(set)
            accessed, shell_accessed = set(), set()
            for ordinal, i in enumerate(calls_idx):
                obj, key = parsed[i]
                rkey = pc.private_key(key) if private else key
                cseq = int(seq[i])
                speaker = env_obj(extra[i]).get("agent") if is_whowhen else None
                sp = pc.structured_paths(obj, tool_raw[i]) if isinstance(obj, dict) else []
                refs = []  # (cls, value, field, kind)
                targets = []
                for p, how in sp:
                    if how == "patch_update":
                        kd = "edit"
                    elif how == "patch_add":
                        kd = "create"
                    elif how == "patch_delete":
                        kd = "other"
                    elif key in ACCESS_EDIT:
                        kd = "edit"
                    elif key in ACCESS_READ:
                        kd = "read"
                    elif key == "write":
                        kd = "create"
                    else:
                        kd = "other"
                    refs.append(("path", p, "structured", kd))
                    targets.append(p)
                    # root candidates (exactly the calibration's rule)
                    if pc.is_absolute(p) and (key in ACCESS_READ or key in ACCESS_EDIT or how == "patch_update"):
                        if not is_sub:
                            root_paths_main.append(p)
                        else:
                            root_paths_thread[tkey].append(p)
                shell = None
                if key == "shell" or key in pc.CODEX_SHELL_RAW or key.endswith("__bash"):
                    shell = pc.shell_command(unit, key, obj, command[i])
                free_src = [shell] if shell else []
                if is_whowhen:
                    strs, _ = pc.args_strings(args[i])
                    free_src += strs
                for t in free_src:
                    for p in pc.free_paths(t):
                        refs.append(("path", p, "free", "free"))
                rt = pc.symbol_ref_text(obj)
                for x in pc.symbols(rt):
                    refs.append(("symbol_ref", x, None, None))
                if shell:
                    for x in pc.symbols(shell):
                        refs.append(("symbol_shell", x, None, None))
                if isinstance(obj, dict) and isinstance(obj.get("pattern"), str) and key in ("grep", "grep_search", "glob"):
                    for x in pc.symbols(obj["pattern"]):
                        refs.append(("symbol_search", x, None, None))
                for x in pc.env_vars((shell or "") + "\n" + rt):
                    refs.append(("env_var", x, None, None))
                for x in pc.cfg_keys(rt, targets, shell):
                    refs.append(("cfg_key", x, None, None))
                if refs:
                    A["calls_with_any_reference"][st] += 1
                A["calls"][st] += 1
                seen_cls = set()
                fm_keys_this_call = set()
                cache = {}
                for cls, val, field, kd in refs:
                    seen_cls.add(cls if cls != "path" else "path_" + field)
                    if cls == "path":
                        if "<R>" in val:
                            A["redacted_path"][st] += 1
                            continue
                        k = pc.path_key(val)
                        if not k:
                            continue
                        ci = bool(DRIVE.match(val))
                        fk = ("path",)
                    else:
                        if "REDACTED" in val:
                            A["redacted_ref"][(st, cls)] += 1
                            if val not in first[("redacted", cls)]:
                                first[("redacted", cls)].add(val)
                                A["redacted_ref_first"][(st, cls)] += 1
                            continue
                        k, ci, fk = val, False, (cls,)
                    if k in first[fk]:
                        continue
                    first[fk].add(k)
                    if cls == "path":
                        fm_keys_this_call.add(k)
                    ck = ("path" if cls == "path" else "word", k, ci)
                    if ck not in cache:
                        cache[ck] = sourcing("path" if cls == "path" else "word", k, cseq, speaker, ci)
                    fl, uns, uns_lit, lag = cache[ck]
                    A["refs"].append((st, s, cls, field, rkey, ordinal, fl["result"], fl["user"], fl["system"],
                                      fl["parent_prompt"], fl["peer"], fl["enumeration"], uns, uns_lit, lag, ci, kd,
                                      fl["_base_seen"], fl["_own_args"]))
                    if DEBUG is not None and not private:
                        DEBUG.append((unit, st, s, cls, k, cseq, uns, fl))
                for c in seen_cls:
                    A["calls_with"][(st, c)] += 1
                # ------------------------------------------------------------ first access by an access tool
                for cls, val, field, kd in refs:
                    if cls != "path" or field != "structured" or kd not in ("read", "edit") or "<R>" in val:
                        continue
                    k = pc.path_key(val)
                    if not k or k in accessed:
                        continue
                    accessed.add(k)
                    ci = bool(DRIVE.match(val))
                    ck = ("path", k, ci)
                    if ck not in cache:
                        cache[ck] = sourcing("path", k, cseq, speaker, ci)
                    fl, uns, uns_lit, lag = cache[ck]
                    ri = rmap.get(call_id[i])
                    if ri is None:
                        pair, prim, ecls = False, None, "no_result"
                    else:
                        pair = True
                        prim, ecls = pc.error_classes(unit, key, tool_raw[i], text[ri], stderr[ri], native[ri],
                                                      exit_code[ri], stratum[i])
                    session_access_rows.append({
                        "st": st, "tkey": tkey, "s": s, "tool": rkey, "p": val, "kind": kd,
                        "first_mention": k in fm_keys_this_call, "pair": pair, "success": pair and prim is False,
                        "ecls": ecls, "fl": fl, "uns": uns, "uns_lit": uns_lit, "secondary": False, "cseq": cseq})
                # ------------------------------------------------------------ secondary: read-like shell commands
                if shell and RX_READ_SHELL.search(shell):
                    fps = pc.free_paths(shell)
                    if fps and "<R>" not in fps[0]:
                        p = fps[0]
                        k = pc.path_key(p)
                        if k and k not in shell_accessed:
                            shell_accessed.add(k)
                            ci = bool(DRIVE.match(p))
                            ck = ("path", k, ci)
                            if ck not in cache:
                                cache[ck] = sourcing("path", k, cseq, speaker, ci)
                            fl, uns, uns_lit, lag = cache[ck]
                            ri = rmap.get(call_id[i])
                            if ri is None:
                                pair, prim, ecls = False, None, "no_result"
                            else:
                                pair = True
                                prim, ecls = pc.error_classes(unit, key, tool_raw[i], text[ri], stderr[ri], native[ri],
                                                              exit_code[ri], stratum[i])
                            session_access_rows.append({
                                "st": st, "tkey": tkey, "s": s, "tool": rkey, "p": p, "kind": "read_shell",
                                "first_mention": k in fm_keys_this_call, "pair": pair,
                                "success": pair and prim is False, "ecls": ecls, "fl": fl, "uns": uns,
                                "uns_lit": uns_lit, "secondary": True, "cseq": cseq})
        # ---------------------------------------------------------------- depth (session workspace root)
        root_main = pc.workspace_root(root_paths_main)
        if root_main is not None:
            A["root_status"]["session_root_found"] += 1
        thread_roots = {}
        for r in session_access_rows:
            if r["st"] == "main" or has_main_calls:
                root = root_main
            else:  # child session without a main thread (DEVIATIONS: workspace root for child sessions)
                if r["tkey"] not in thread_roots:
                    thread_roots[r["tkey"]] = pc.workspace_root(root_paths_thread.get(r["tkey"], []))
                root = thread_roots[r["tkey"]]
            d = pc.path_depth(r["p"], root)
            fl = r["fl"]
            if DEBUG_ACCESS is not None and not private:
                DEBUG_ACCESS.append((unit, r["st"], r["s"], r["p"], r["cseq"], d, r["uns"], r["success"],
                                     r["secondary"], r["tool"]))
            A["access"].append((r["st"], r["s"], r["tool"], r["kind"], r["secondary"], r["first_mention"], r["pair"],
                                r["success"], r["ecls"], -1 if d is None else d, r["uns"], r["uns_lit"],
                                fl["result"], fl["user"], fl["system"], fl["parent_prompt"], fl["peer"],
                                fl["enumeration"], fl["_base_seen"], fl["_own_args"]))


# ====================================================================================================== statistics
def crate(flags, sids, min_den=None, min_sess=None):
    """Event rate with session-clustered CI (stats.cluster_rate) under global.min_n.rate_reportable; zero-count rule."""
    min_den = MIN_RATE["den_min"] if min_den is None else min_den
    min_sess = MIN_RATE["sessions_min"] if min_sess is None else min_sess
    flags = np.asarray(flags, dtype=float)
    sids = np.asarray(sids, dtype=object)
    n = int(len(flags))
    k = int(flags.sum()) if n else 0
    ns = int(len(set(sids.tolist()))) if n else 0
    out = {"k": k, "n": n, "n_sessions": ns}
    if n < min_den or ns < min_sess:
        out["label"] = "insufficient n"
        return out
    g = pd.DataFrame({"s": sids, "f": flags}).groupby("s", sort=True)["f"]
    r = stats.cluster_rate(g.sum().to_numpy(), g.size().to_numpy())
    out.update({"rate": r["rate"], "lo": r["lo"], "hi": r["hi"]})
    if k == 0:
        out["wilson_hi_event"] = stats.wilson(0, n)[2]
        out["wilson_hi_session"] = stats.wilson(0, ns)[2]
    return out


def qblock(values, sids, qs=(0.1, 0.25, 0.5, 0.75, 0.9)):
    """Quantiles with cluster_quantile CIs, each subject to global.min_n.quantile_reportable."""
    v = np.asarray(values, dtype=float)
    s = np.asarray(sids, dtype=object).astype(str)
    out = {"n": int(len(v)), "n_sessions": int(len(set(s.tolist())))}
    if len(v) == 0:
        return out
    out["min"], out["max"], out["mean"] = float(v.min()), float(v.max()), float(v.mean())
    for q in qs:
        need = QMIN["p50"] if 0.25 <= q <= 0.75 else QMIN["p5_p95"] if 0.05 <= q <= 0.95 else QMIN["p1_p99"]
        name = f"p{round(q * 100, 2):g}"
        if out["n"] >= need[0] and out["n_sessions"] >= need[1]:
            r = stats.cluster_quantile(v, s, q)
            out[name] = {"value": r["value"], "lo": r["lo"], "hi": r["hi"]}
        else:
            out[name] = {"label": "insufficient n"}
    return out


def share_hist(values, nbins=10):
    v = np.asarray(values, dtype=float)
    edges = np.linspace(0, 1, nbins + 1)
    c, _ = np.histogram(v, bins=edges)
    return [{"lo": float(edges[i]), "hi": float(edges[i + 1]), "count": int(c[i])} for i in range(nbins)]


def ordinal_bin(o):
    for lo, hi, name in ORDINAL_BINS:
        if lo <= o <= hi:
            return name
    return "?"


SRC_COLS = ["result", "user", "system", "parent_prompt", "peer", "enumeration"]


def ref_frame(refs):
    cols = ["st", "s", "cls", "field", "tool", "ordinal"] + SRC_COLS + ["uns", "uns_lit", "lag", "ci", "kind",
                                                                        "base_seen", "own_args"]
    return pd.DataFrame(refs, columns=cols)


def acc_frame(acc):
    cols = ["st", "s", "tool", "kind", "secondary", "first_mention", "pair", "success", "ecls", "depth", "uns",
            "uns_lit"] + SRC_COLS + ["base_seen", "own_args"]
    return pd.DataFrame(acc, columns=cols)


def class_block(R, private):
    """Unsourced and per-source shares for one stratum x class frame R (first mentions)."""
    out = {"n_first_mentions": int(len(R)), "n_sessions": int(R.s.nunique()) if len(R) else 0}
    if not len(R):
        return out
    out["unsourced"] = crate(R.uns, R.s)
    if R.ci.any():
        out["n_drive_letter_keys"] = int(R.ci.sum())
        out["unsourced_literal_case"] = crate(R.uns_lit, R.s)
    out["sourced_by"] = {c: crate(R[c], R.s) for c in SRC_COLS}
    others = [c for c in SRC_COLS if c != "enumeration"]
    out["sourced_by"]["enumeration_only"] = crate(R.enumeration & ~R[others].any(axis=1), R.s)
    out["sourced_by"]["result_only"] = crate(R.result & ~R[[c for c in SRC_COLS if c != "result"]].any(axis=1), R.s)
    if R.field.notna().any():
        out["by_field"] = {f: crate(g.uns, g.s) for f, g in R.groupby("field")}
    out["by_tool"] = {t: crate(g.uns, g.s) for t, g in R.groupby("tool")}
    U = R[R.uns]
    if len(U):
        out["post_hoc_unsourced_trace"] = {
            "note": "POST HOC, descriptive only (see deep_first_try.post_hoc_unsourced_deep_trace)",
            "basename_seen_earlier": crate(U.base_seen, U.s), "key_in_own_earlier_args": crate(U.own_args, U.s),
            "neither": crate(~(U.base_seen | U.own_args), U.s)}
    out["by_call_ordinal"] = {}
    ob = R.ordinal.map(ordinal_bin)
    for _, _, name in ORDINAL_BINS:
        g = R[ob == name]
        if len(g):
            out["by_call_ordinal"][name] = crate(g.uns, g.s)
    # per-session unsourced share (sessions with >= 10 first mentions of this class)
    per = R.groupby("s").agg(n=("uns", "size"), k=("uns", "sum"))
    per = per[per.n >= 10]
    sh = (per.k / per.n).to_numpy()
    out["per_session_unsourced_share"] = {"min_first_mentions_per_session": 10, "n_sessions": int(len(per)),
                                          "hist": share_hist(sh) if len(sh) else [],
                                          "quantiles": qblock(sh, per.index.to_numpy())}
    # lag (result events back to the most recent matching result) for result-sourced first mentions
    L = R[R.lag > 0]
    out["result_source_lag_events"] = {"quantiles": qblock(L.lag, L.s, qs=(0.25, 0.5, 0.75, 0.9, 0.95)),
                                       "log_hist": stats.log_histogram(L.lag.to_numpy(dtype=float), per_decade=4),
                                       "share_lag_1": crate(R.lag == 1, R.s) if len(R) else None}
    return out


def s_rate_with_hi(r):
    """(rate, hi used by the verdict): per-event Wilson hi in place of the bootstrap hi when num == 0."""
    if r.get("rate") is None:
        return None, None
    hi = r["wilson_hi_event"] if r["k"] == 0 else r["hi"]
    return r["rate"], hi


def label_from(rate, hi):
    if rate <= T_ALIVE and hi <= T_ALIVE_HI:
        return "ALIVE"
    if rate <= T_WEAK:
        return "WEAK"
    return "DEAD"


def verdict(unit, s_deep, s_path_any, instrument_ok, stratum):
    """Mechanical prereg verdict (probe2.verdict). s_deep / s_path_any: crate dicts computed without min-n gating."""
    caps, labels = [], []
    dn, ds = s_deep["n"], s_deep["n_sessions"]
    an, as_ = s_path_any["n"], s_path_any["n_sessions"]
    if dn >= MIN_DEEP_N and ds >= MIN_DEEP_S:
        stat, r = "S_deep", s_deep
        rate, hi = s_rate_with_hi(r)
        lab = label_from(rate, hi)
        pop_sessions = ds
    elif an >= MIN_ANY_N and as_ >= MIN_ANY_S:
        stat, r = "S_path_any", s_path_any
        rate, hi = s_rate_with_hi(r)
        lab = label_from(rate, hi)
        pop_sessions = as_
        if lab == "ALIVE":
            lab = "WEAK"
            caps.append("S_deep INSUFFICIENT_N -> S_path_any capped at WEAK")
        else:
            caps.append("S_deep INSUFFICIENT_N -> S_path_any (cap WEAK; not binding)")
    else:
        return {"verdict": "INSUFFICIENT_N", "deciding_statistic": None,
                "S_deep_n": dn, "S_deep_sessions": ds, "S_path_any_n": an, "S_path_any_sessions": as_,
                "min_n": {"S_deep": [MIN_DEEP_N, MIN_DEEP_S], "S_path_any": [MIN_ANY_N, MIN_ANY_S]},
                "labels": (["single-agent case study"] if unit == "aiv_cc" else []), "caps_applied": []}
    raw = lab
    if unit == "aiv_cu" and lab == "ALIVE":
        lab = "WEAK"
        caps.append("aiv_cu proxy success -> cap WEAK")
    if not instrument_ok and lab == "ALIVE":
        lab = "WEAK"
        caps.append("instrument_check failed -> cap WEAK (matching instrument suspect)")
    if unit in INCOMPLETE and lab == "DEAD":
        lab = "INCONCLUSIVE"
        caps.append("antecedents_incomplete: DEAD -> INCONCLUSIVE")
    if unit == "aiv_cc":
        labels.append("single-agent case study")
    if unit == "aiv_cu":
        labels.append("proxy-based first-try success")
    if not instrument_ok:
        labels.append("matching instrument suspect")
    if pop_sessions < SMALL_N_SESSIONS:
        labels.append("small n")
    return {"verdict": lab, "label_before_caps": raw, "deciding_statistic": stat, "value": r["rate"],
            "ci": [r["lo"], r["hi"]], "hi_used": hi, "k": r["k"], "n": r["n"], "n_sessions": r["n_sessions"],
            "zero_count_rule_applied": r["k"] == 0, "caps_applied": caps, "labels": labels}


def deep_block(X, D):
    """S_deep and its context for one stratum's first-access rows X (non-secondary or secondary)."""
    out = {"D_unit": D, "n_first_accesses": int(len(X)), "n_sessions": int(X.s.nunique()) if len(X) else 0}
    if not len(X):
        return out, {"k": 0, "n": 0, "n_sessions": 0}, None
    out["by_kind"] = {k: int(v) for k, v in X.kind.value_counts().items()}
    out["pair_missing"] = int((~X.pair).sum())
    out["error_class_counts"] = {str(k): int(v) for k, v in X.ecls.value_counts().items()}
    known = X[X.depth >= 0]
    out["depth_unknown"] = int((X.depth < 0).sum())
    out["depth_hist"] = {str(int(k)): int(v) for k, v in sorted(known.depth.value_counts().items())}
    out["depth_quantiles"] = qblock(known.depth, known.s, qs=(0.25, 0.5, 0.75, 0.9))
    out["depth_hist_by_tool"] = {t: {str(int(k)): int(v) for k, v in sorted(g.depth.value_counts().items())}
                                 for t, g in known.groupby("tool")}
    succ = known[known.success]
    out["first_try_success"] = crate(known.success, known.s)
    out["unsourced_all_depths_success"] = crate(succ.uns, succ.s)
    deep = succ[succ.depth >= D]
    out["n_deep"] = int((known.depth >= D).sum())
    out["n_deep_success"] = int(len(deep))
    out["n_deep_success_sessions"] = int(deep.s.nunique()) if len(deep) else 0
    sd = crate(deep.uns, deep.s, min_den=1, min_sess=1) if len(deep) else {"k": 0, "n": 0, "n_sessions": 0}
    out["S_deep"] = sd
    if len(deep):
        per = deep.groupby("s").uns.any()
        k, n = int(per.sum()), int(len(per))
        w = stats.wilson(k, n)
        out["S_deep_session_share"] = {"k": k, "n": n, "share": w[0], "lo": w[1], "hi": w[2]}
        out["S_deep_literal_case"] = crate(deep.uns_lit, deep.s, min_den=1, min_sess=1)
        out["deep_sourced_by"] = {c: crate(deep[c], deep.s) for c in SRC_COLS}
        out["S_deep_by_tool"] = {t: crate(g.uns, g.s) for t, g in deep.groupby("tool")}
        U = deep[deep.uns]
        if len(U):
            out["post_hoc_unsourced_deep_trace"] = {
                "note": "POST HOC, descriptive only: among knowledge_from_nowhere accesses, the share whose basename "
                        "alone occurs in an earlier source text, and the share whose key occurs in the thread's own "
                        "earlier call args (never a source under the prereg)",
                "basename_seen_earlier": crate(U.base_seen, U.s, min_den=1, min_sess=1),
                "key_in_own_earlier_args": crate(U.own_args, U.s, min_den=1, min_sess=1),
                "neither": crate(~(U.base_seen | U.own_args), U.s, min_den=1, min_sess=1)}
    out["unsourced_by_depth"] = {str(int(d)): crate(g.uns, g.s) for d, g in succ.groupby("depth")}
    return out, sd, deep


def stratum_block(unit, st, R, X_all, D, private):
    Rs = R[R.st == st]
    out = {"classes": {}}
    for cls in REF_CLASSES:
        out["classes"][cls] = class_block(Rs[Rs.cls == cls], private)
    E = Rs[Rs.cls.isin(["env_var", "cfg_key"])]
    out["classes"]["env_cfg_pooled"] = {"n_first_mentions": int(len(E)), "unsourced": crate(E.uns, E.s)}
    Xs = X_all[(X_all.st == st)]
    prim = Xs[~Xs.secondary]
    db, sd, deep = deep_block(prim, D)
    out["deep_first_try"] = db
    sec_block, _, _ = deep_block(Xs[Xs.secondary], D)
    out["deep_first_try_secondary_read_shell"] = sec_block
    P = Rs[Rs.cls == "path"]
    s_any = crate(P.uns, P.s, min_den=1, min_sess=1) if len(P) else {"k": 0, "n": 0, "n_sessions": 0}
    out["S_path_any"] = s_any
    S = Rs[Rs.cls == "symbol_ref"]
    out["S_symbol_ref"] = crate(S.uns, S.s)
    out["S_env_cfg"] = out["classes"]["env_cfg_pooled"]["unsourced"]
    # sensitivity variants (reported, never the verdict)
    var = {}
    if len(prim):
        known = prim[prim.depth >= 0]
        succ = known[known.success]
        deep = succ[succ.depth >= D]
        fm = deep[deep.first_mention]
        var["first_mention_access_only"] = crate(fm.uns, fm.s, min_den=1, min_sess=1) if len(fm) else {"n": 0}
        nopi = deep[~deep.ecls.isin(["cc_permission_denied", "cc_interrupt_reject"])]
        var["excluding_permission_interrupt"] = crate(nopi.uns, nopi.s, min_den=1, min_sess=1) if len(nopi) else {"n": 0}
        var["literal_case"] = crate(deep.uns_lit, deep.s, min_den=1, min_sess=1) if len(deep) else {"n": 0}
    if len(P):
        var["S_path_any_literal_case"] = crate(P.uns_lit, P.s, min_den=1, min_sess=1)
        # POST HOC (added after the first B run; descriptive only, never a verdict input): S_path_any counts creation
        # targets (Write file_path, apply_patch Add File/Move to), which have no antecedent by construction.
        P2_ = P[P.kind != "create"]
        out["post_hoc_descriptive"] = {
            "note": "added after seeing the first Phase B output; not pre-registered; no verdict is derived from it",
            "S_path_any_excluding_creation_targets": crate(P2_.uns, P2_.s, min_den=1, min_sess=1) if len(P2_)
            else {"n": 0},
            "first_mention_paths_by_access_kind": {k: crate(g.uns, g.s) for k, g in P.groupby("kind")}}
    out["variants"] = var
    return out, sd, s_any


def variant_verdicts(unit, block, instrument_ok, base):
    """Re-run the mechanical verdict with each sensitivity variant in place of S_deep (reporting only)."""
    res = {}
    v = block["variants"]
    for name in ("first_mention_access_only", "excluding_permission_interrupt", "literal_case"):
        sd = v.get(name)
        if not sd or "n" not in sd or sd.get("n", 0) == 0:
            continue
        spa = v.get("S_path_any_literal_case", block["S_path_any"]) if name == "literal_case" else block["S_path_any"]
        vv = verdict(unit, sd, spa, instrument_ok, None)
        res[name] = {"verdict": vv["verdict"], "deciding_statistic": vv.get("deciding_statistic"),
                     "value": vv.get("value"), "same_as_primary": vv["verdict"] == base["verdict"]}
    return res


# ====================================================================================================== main
def load_corpus(corpus, split):
    cols = ["session_id", "seq", "kind", "tool", "tool_raw", "call_id", "args", "command", "text", "stderr",
            "native_error", "exit_code", "is_subagent", "agent_id", "extra", "stratum"]
    kinds = ["user", "system", "call", "result"] + (["assistant"] if corpus in ("swechat", "whowhen") else [])
    return pc.load_split(corpus, split, cols, filters=[("kind", "in", kinds)])


def aiv_cc_overlap(split):
    other = "A" if split == "B" else "B"
    b = pc.load_split("aiv_cc", split, ["session_id"]).session_id.drop_duplicates()
    a = pc.load_split("aiv_cc", other, ["session_id"]).session_id.drop_duplicates()
    sdk_b = b.str.rsplit("/", n=1).str[0]
    sdk_a = set(a.str.rsplit("/", n=1).str[0])
    return {"runs_in_split": int(len(b)), "distinct_sdk_session_id": int(sdk_b.nunique()),
            "runs_sharing_sdk_session_with_other_split": int(sdk_b.isin(sdk_a).sum()),
            "other_split": other}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="B", choices=["A", "B"])
    ap.add_argument("--out", default=None)
    ap.add_argument("--units", default=None, help="comma-separated subset (debug)")
    arg = ap.parse_args()
    t0 = time.time()
    # ---------------------------------------------------------------- pre-registration provenance check
    spec_sha = sha256(SPEC_PATH)
    expected = PR["provenance"]["spec_module_sha256"]
    if spec_sha != expected:
        print(f"STOP: prereg_common.py sha256 {spec_sha} != prereg.json provenance.spec_module_sha256 {expected}")
        sys.exit(2)
    if arg.split == "A" or arg.units:
        from pathlib import Path as _P
        assert arg.out and not str(_P(arg.out).resolve()).startswith(str((ROOT / "analysis" / "out").resolve())), \
            "debug runs (split A or a unit subset) must write outside analysis/out"
    out_path = OUT if arg.out is None else arg.out
    only = set(arg.units.split(",")) if arg.units else None
    res = {
        "probe": "probe2_knowledge_precedence",
        "script": "analysis/probes/probe_2.py",
        "split": arg.split,
        "prereg_json_sha256": sha256(PREREG_PATH),
        "spec_module_sha256": spec_sha,
        "spec_module_sha256_expected": expected,
        "spec_module_sha256_ok": spec_sha == expected,
        "inputs_sha256": {},
        "thresholds_from_prereg": {"ALIVE": [T_ALIVE, T_ALIVE_HI], "WEAK": T_WEAK, "DEAD_above": T_DEAD,
                                   "min_n_S_deep": [MIN_DEEP_N, MIN_DEEP_S], "min_n_S_path_any": [MIN_ANY_N, MIN_ANY_S],
                                   "instrument_S_symbol_ref_max": T_INSTRUMENT, "D_unit": D_UNIT,
                                   "rate_reportable": MIN_RATE},
        "deviations": DEVIATIONS,
        "note": "raw numbers only; rates are stats.cluster_rate (session-clustered bootstrap, 1000 draws, seed "
                "20261003) with global.min_n gating ('insufficient n' = k/n only); interpretation in "
                "analysis/notes/probe_2.md",
        "units": {},
    }
    for corpus in ("swechat", "cc_local", "aiv_cc", "aiv_cu", "whowhen"):
        f = pc.CACHE / f"{corpus}_{arg.split}.parquet"
        res["inputs_sha256"][f"analysis/cache/{corpus}_{arg.split}.parquet"] = sha256(f)
    res["inputs_sha256"]["analysis/cache/swechat_population.parquet"] = sha256(pc.CACHE / "swechat_population.parquet")

    unit_results = {}
    for corpus in ("swechat", "cc_local", "aiv_cc", "aiv_cu", "whowhen"):
        df = load_corpus(corpus, arg.split)
        frames = pc.unit_frames(corpus, df)
        del df
        gc.collect()
        for unit in list(frames):
            u = frames.pop(unit)
            if unit not in RUN_UNITS or (only and unit not in only):
                del u
                continue
            if unit != "swechat/codex" and corpus == "swechat":
                u = u[u.kind != "assistant"]
            print(f"[{time.time() - t0:7.1f}s] {unit}: {len(u)} rows, {u.session_id.nunique()} sessions", flush=True)
            A = {"sessions": set(), "threads": {"main": set(), "sub": set()}, "refs": [], "access": [],
                 "calls": Counter(), "calls_with_any_reference": Counter(), "calls_with": Counter(),
                 "redacted_path": Counter(), "redacted_ref": Counter(), "redacted_ref_first": Counter(),
                 "root_status": Counter()}
            process_unit(unit, u, A)
            del u
            gc.collect()
            unit_results[unit] = A
            print(f"[{time.time() - t0:7.1f}s] {unit}: {len(A['refs'])} first mentions, {len(A['access'])} "
                  f"first accesses", flush=True)

    # ---------------------------------------------------------------- statistics per unit x stratum
    blocks = {}
    for unit, A in unit_results.items():
        private = unit == "cc_local"
        R = ref_frame(A["refs"])
        X = acc_frame(A["access"])
        D = D_UNIT[unit]
        ub = {"status": "full" if unit in FULL else "antecedents_incomplete",
              "antecedents_incomplete_reason": P2["units"]["antecedents_incomplete"].get(unit),
              "sessions": len(A["sessions"]),
              "sessions_population_B": PR["population_B"]["sessions"].get(unit),
              "threads_with_calls": {k: len(v) for k, v in A["threads"].items()},
              "extraction": {
                  "calls": dict(A["calls"]), "calls_with_any_reference": dict(A["calls_with_any_reference"]),
                  "calls_with": {f"{st}/{c}": v for (st, c), v in sorted(A["calls_with"].items())},
                  "redacted_path": dict(A["redacted_path"]),
                  "redacted_ref": {f"{st}/{c}": v for (st, c), v in sorted(A["redacted_ref"].items())},
                  "redacted_ref_distinct_per_thread": {f"{st}/{c}": v for (st, c), v in
                                                       sorted(A["redacted_ref_first"].items())},
                  "note_redacted": "redacted_path / redacted_ref count occurrences (as the A calibration did); "
                                   "redacted_ref_distinct_per_thread counts first mentions excluded by the "
                                   "redaction deviation",
                  "first_mentions": {f"{st}/{c}": int(v) for (st, c), v in R.groupby(["st", "cls"]).size().items()}
                  if len(R) else {},
                  "sessions_with_workspace_root": A["root_status"].get("session_root_found", 0)},
              "strata": {}}
        if unit == "aiv_cc":
            ub["aiv_cc_rule"] = aiv_cc_overlap(arg.split)
            ub["labels"] = ["single-agent case study"]
        for st in ("main", "sub"):
            if not len(R) and not len(X):
                b, sd, sa = {"classes": {}}, {"k": 0, "n": 0, "n_sessions": 0}, {"k": 0, "n": 0, "n_sessions": 0}
            else:
                b, sd, sa = stratum_block(unit, st, R if len(R) else ref_frame([]), X if len(X) else acc_frame([]),
                                          D, private)
            b["_sd"], b["_sa"] = sd, sa
            ub["strata"][st] = b
        blocks[unit] = ub

    # ---------------------------------------------------------------- instrument check (swechat CC main S_symbol_ref)
    inst = {"rule": P2["statistics"]["instrument_check"], "threshold": T_INSTRUMENT}
    cc = blocks.get("swechat/claude_code")
    if cc is not None:
        r = cc["strata"]["main"]["S_symbol_ref"]
        inst["S_symbol_ref"] = r
        inst["ok"] = r.get("rate") is not None and r["rate"] <= T_INSTRUMENT
        red = unit_results["swechat/claude_code"]["redacted_ref_first"].get(("main", "symbol_ref"), 0)
        if r.get("n"):
            inst["including_redacted_refs"] = {"k": r["k"] + red, "n": r["n"] + red,
                                               "rate": (r["k"] + red) / (r["n"] + red),
                                               "ok": (r["k"] + red) / (r["n"] + red) <= T_INSTRUMENT}
    else:
        inst["ok"] = None
    res["instrument_check"] = inst
    instrument_ok = bool(inst.get("ok"))

    # ---------------------------------------------------------------- verdicts
    verdicts = {}
    n_cells = 0
    for unit in list(pc.UNITS):
        if unit in NOT_TESTABLE:
            verdicts[unit] = {st: {"verdict": "NOT_TESTABLE", "reason": P2["units"]["not_testable"][unit]}
                              for st in ("main", "sub")}
            n_cells += 2
            continue
        if unit not in blocks:
            continue
        verdicts[unit] = {}
        for st in ("main", "sub"):
            b = blocks[unit]["strata"][st]
            sd, sa = b.pop("_sd"), b.pop("_sa")
            v = verdict(unit, sd, sa, instrument_ok, st)
            if st == "sub" and blocks[unit]["threads_with_calls"].get("sub", 0) == 0:
                v["note"] = "no subagent threads with calls in this unit"
            if "classes" in b and b.get("variants") is not None:
                v["sensitivity"] = variant_verdicts(unit, b, instrument_ok, v)
            b["verdict"] = v
            verdicts[unit][st] = {k: v[k] for k in ("verdict", "deciding_statistic") if k in v}
            verdicts[unit][st].update({k: v[k] for k in ("value", "ci", "hi_used", "k", "n", "n_sessions",
                                                          "caps_applied", "labels") if k in v})
            n_cells += 1
    res["units"] = blocks
    res["verdicts"] = verdicts
    res["n_verdict_cells"] = n_cells
    res["runtime_s"] = round(time.time() - t0, 1)
    txt = json.dumps(res, indent=1, ensure_ascii=False, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    from pathlib import Path
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(txt)
    if arg.split == "B" and arg.out is None and only is None:
        OUT_COPY.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT_COPY, "w", encoding="utf-8") as fh:
            fh.write(txt)
    print(f"[{time.time() - t0:7.1f}s] wrote {out_path}")
    for unit, v in verdicts.items():
        print(unit, {st: x.get("verdict") for st, x in v.items()})


if __name__ == "__main__":
    main()
