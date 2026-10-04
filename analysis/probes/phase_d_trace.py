"""Phase D traceability audit: every numeric token in analysis/FINDINGS.md, searched for in committed output files.

Reads
  analysis/FINDINGS.md                      the report under audit (sha256 recorded in the output)
  PRIMARY search set: every file `git ls-files analysis/out` lists with suffix .json or .txt (committed files only;
    a file modified in the worktree is read from HEAD instead, and the output lists it)
  SECONDARY search set, consulted only for numbers the primary set lacks or matches only at chance level, each file
    labelled committed or not:
    analysis/*.md, analysis/notes/*.md, analysis/prereg.json      committed, but outside analysis/out
    untracked analysis/out/**/*.json except this script's own output   (analysis/out/phase_d/ranking.json, inputs)
Writes
  analysis/out/phase_d/trace.json

Extraction (FINDINGS.md). Every numeric token is extracted except, by rule, and each exclusion is logged under `ignored`:
  heading lines; numbered-list ordinals at line start; the "#" column of a table whose header cell is "#";
  section references (section sign + number); dates (YYYY-MM[-DD]) and times of day; "et al. YEAR"; bet odds "X:Y";
  version strings (a.b.c, a.b.x, "Version 2.1", vN); model names (gemini-2.5-pro, 3.1-pro, sonnet-4-5, AR(1));
  names with an ordinal ("Probe 1", "Rank 2", "Step 0", "rule 4", "item 7", "caveat 3", "RFC 9562");
  tokens where digits touch letters (ids such as O5, TC2, A6-O1, R:A4-3, p50, log10, sha256, commit hashes);
  backtick spans whose content is not a pure number (file names, JSON paths, quoted strings); the "95% CI" convention.
  Kept with a special reading: scientific notation (3.12e-4), a "k" suffix (100k = 100,000), percent (15.1%), a leading
  Unicode or ASCII minus/plus directly before the digits, the lattice formula "516 + 518k" (coefficients 516 and 518).

Matching (tolerant string match, implemented on parsed values). Every number in every searched file is indexed: JSON
numbers, numbers inside JSON strings and JSON keys (thousands separators removed; comma-grouped tokens are also indexed
as their separate parts), and numbers in .txt/.md text. A FINDINGS number with d displayed decimals matches any indexed
value inside [x - 0.5*10^-d, x + 0.5*10^-d] (this covers trailing zeros and rounding to the displayed precision).
`status`, first rule that applies:
  found                match at the displayed scale (for a number written with %, also at x/100)
  found_scaled         match only at x/100 or x*100 (percent <-> fraction), non-integers only
  found_abs            a negative number that matches only in absolute value
  found_kilo_mantissa  a "k"-suffixed number that matches only as its mantissa (e.g. "100" for 100k)
  near_miss            no match, but an indexed value lies within 1.5 units of the last displayed digit (scale 1)
  not_found            none of the above
A match anywhere in 1.3M indexed values is weak evidence for a low-precision number, so two further measurements are
recorded and combined into `trace_class`:
  chance_expected  mean count of indexed values in 20 equal-width windows next to the match window (offsets +-2..+-11
                   widths, at the matched scale): how many values this close turn up by chance
  colocated        the number shares a source record with other numbers from the same FINDINGS item (a table row, or
                   a bullet/paragraph with its wrapped lines), and that combination is unlikely by chance. Record key =
                   the JSON container holding the value (for a value inside a JSON string: that string) and the
                   container one level up; text files: the line and its 4-line block. A key of size n_k holds a text
                   with c_t hits among V values by chance with p = 1 - exp(-n_k c_t / V); a key holding the item texts
                   S has E = C * prod_{t in S} p (C = candidate keys examined for the item). A number is colocated when
                   a key holding it and at least one other item text has E <= COLOC_MAX_E.
  same_text_traced_on_lines   for an untraced number: other FINDINGS lines where the identical text is colocated/specific
  trace_class      colocated > specific (not colocated, chance_expected <= SPECIFIC_MAX_E) > chance_level (found, but
                   neither) > not_found (status near_miss or not_found)
Also per number: hit count, files hit, `in_cited_source` (any hit in a file cited by the line's source tags or its
section; None if nothing is cited), up to 6 example locations (cited files first), and for chance_level / near_miss /
not_found numbers the nearest primary values and the secondary-set hits.

This file is measurement only. Whether an untraced number is arithmetic on traceable numbers is decided by a person
reading the output, not here (rule 4).

Run:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_d_trace
"""
import bisect
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from array import array

import numpy as np

sys.setrecursionlimit(20000)
ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
FINDINGS = os.path.join(ROOT, "analysis", "FINDINGS.md")
OUT_REL = "analysis/out/phase_d/trace.json"
OUT = os.path.join(ROOT, *OUT_REL.split("/"))
N_WHERE = 6
CHANCE_OFFSETS = [k for k in range(-11, 12) if abs(k) >= 2]
COLOC_MAX_E = 0.001
SPECIFIC_MAX_E = 0.05
HIT_CAP = 400000
ANCHOR_MAX_K = 20000


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8")


# ---------------------------------------------------------------------------------------------- file sets
tracked_out = [p for p in git("ls-files", "analysis/out").splitlines() if p.endswith((".json", ".txt"))]
modified_out = set(git("diff", "--name-only", "HEAD", "--", "analysis/out").splitlines())
tracked_analysis = git("ls-files", "analysis").splitlines()
secondary_committed = sorted(p for p in tracked_analysis
                             if re.fullmatch(r"analysis/[^/]+\.md|analysis/notes/[^/]+\.md|analysis/prereg\.json", p))
untracked_out = sorted(p for p in git("ls-files", "--others", "--exclude-standard", "analysis/out").splitlines()
                       if p.endswith(".json") and p != OUT_REL)


def read_bytes(rel, from_head=False):
    if from_head:
        return subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=ROOT, capture_output=True, check=True).stdout
    with open(os.path.join(ROOT, *rel.split("/")), "rb") as f:
        return f.read()


# ---------------------------------------------------------------------------------------------- corpus indexing
CNUM = re.compile(r"(?<![\w.])([−+\-]?)((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)(?:[eE]([−+\-]?\d+))?")


def parse_num(body, exp=None, sign=""):
    v = float(body.replace(",", ""))
    if exp:
        v *= 10.0 ** int(exp.replace("−", "-"))
    if sign in ("-", "−"):
        v = -v
    return v


def text_numbers(s):
    """Yield (value, start, end) for every number in s; comma-grouped tokens also yield their parts."""
    for m in CNUM.finditer(s):
        sign, body, exp = m.group(1), m.group(2), m.group(3)
        try:
            v = parse_num(body, exp, sign)
        except (ValueError, OverflowError):
            continue
        if not math.isfinite(v):
            continue
        yield v, m.start(), m.end()
        if "," in body:
            for part in body.split(","):
                if part:
                    yield float(part), m.start(), m.end()


class Index:
    """Parsed numeric values of a file set: value, file id, sequence number in file, record id, parent-record id."""

    def __init__(self, files):
        self.files = files
        self.vals, self.fid, self.seq = array("d"), array("I"), array("I")
        self.rec, self.prec = array("I"), array("I")
        self.raw_text = {}
        self._next = [1]
        for i, (rel, from_head) in enumerate(files):
            txt = read_bytes(rel, from_head).decode("utf-8", errors="replace")
            self.raw_text[rel] = txt
            self._walk_file(i, rel, txt, None)
        self.v = np.frombuffer(self.vals, dtype=np.float64)
        self.f = np.frombuffer(self.fid, dtype=np.uint32)
        self.r = np.frombuffer(self.rec, dtype=np.uint32)
        self.pr = np.frombuffer(self.prec, dtype=np.uint32)
        self.order = np.argsort(self.v, kind="stable")
        self.sv = self.v[self.order]

    def _new_id(self):
        self._next[0] += 1
        return self._next[0]

    def _walk_file(self, i, rel, txt, want):
        """want None: index values. want = {seq: None}: fill in location dicts for those seqs (ids are not stored)."""
        counter = [0]

        def emit(v, rec_id, prec_id, loc_fn):
            s = counter[0]
            counter[0] += 1
            if want is None:
                self.vals.append(v)
                self.fid.append(i)
                self.seq.append(s)
                self.rec.append(rec_id)
                self.prec.append(prec_id)
            elif s in want:
                want[s] = loc_fn()

        obj = None
        if rel.endswith(".json"):
            try:
                obj = json.loads(txt)
            except json.JSONDecodeError:
                obj = None
        if obj is not None:
            stack = []

            def path():
                out = ""
                for k in stack:
                    out += f"[{k}]" if isinstance(k, int) else (("." if out else "") + str(k))
                return out

            def walk(o, parent, grand):
                if isinstance(o, dict):
                    c = self._new_id()
                    for k, v in o.items():
                        for x, a, b in text_numbers(str(k)):
                            emit(x, c, parent, lambda k=k: {"path": path(), "key": str(k)})
                        stack.append(k)
                        walk(v, c, parent)
                        stack.pop()
                elif isinstance(o, list):
                    c = self._new_id()
                    for j, v in enumerate(o):
                        stack.append(j)
                        walk(v, c, parent)
                        stack.pop()
                elif isinstance(o, bool) or o is None:
                    return
                elif isinstance(o, (int, float)):
                    if math.isfinite(o):
                        emit(float(o), parent, grand, lambda o=o: {"path": path(), "json_value": o})
                elif isinstance(o, str):
                    sid = self._new_id()
                    for x, a, b in text_numbers(o):
                        emit(x, sid, parent, lambda a=a, b=b, o=o: {"path": path(), "in_string": o[max(0, a - 50):b + 50]})

            walk(obj, self._new_id(), 0)
            return
        line_starts = [0] + [m.end() for m in re.finditer("\n", txt)]
        base = self._new_id()
        line_ids, block_ids = {}, {}
        for x, a, b in text_numbers(txt):
            ln = bisect.bisect_right(line_starts, a)
            lid = line_ids.setdefault(ln, self._new_id())
            bid = block_ids.setdefault(ln // 4, self._new_id())
            emit(x, lid, bid if bid else base, lambda a=a, b=b, ln=ln: {"line": ln, "text": txt[max(0, a - 50):b + 50].replace("\n", " ")})

    def locate(self, pairs):
        by_file = {}
        for fi, s in pairs:
            by_file.setdefault(fi, {})[s] = None
        out = {}
        for fi, want in by_file.items():
            rel, _ = self.files[fi]
            self._walk_file(fi, rel, self.raw_text[rel], want)
            for s, loc in want.items():
                out[(fi, s)] = loc
        return out

    def count(self, lo, hi):
        return int(np.searchsorted(self.sv, hi, side="right") - np.searchsorted(self.sv, lo, side="left"))

    def hits(self, lo, hi):
        a = np.searchsorted(self.sv, lo, side="left")
        b = np.searchsorted(self.sv, hi, side="right")
        return self.order[a:b]

    def nearest(self, x, k=2):
        p = int(np.searchsorted(self.sv, x))
        return [int(self.order[j]) for j in range(max(0, p - k), min(len(self.sv), p + k))]


primary_files = [(p, p in modified_out) for p in tracked_out]
secondary_files = [(p, False) for p in secondary_committed] + [(p, False) for p in untracked_out]
PRI = Index(primary_files)
SEC = Index(secondary_files)
SEC_COMMITTED = set(secondary_committed)

# ---------------------------------------------------------------------------------------------- FINDINGS extraction
NUMPAT = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
PATTERNS = [
    ("backtick", r"`[^`\n]*`"),
    ("date", r"(?<!\d)(?:19|20)\d{2}-\d{2}(?:-\d{2})?(?!\d)"),
    ("time_of_day", r"(?<!\d)\d{1,2}:\d{2}:\d{2}(?!\d)"),
    ("bet_odds", r"(?<![\d.,])\d+:\d+(?![\d.])"),
    ("citation_year", r"et al\.\s+\d{4}"),
    ("section_ref", r"§\s?\d+(?:\.\d+)*"),
    ("model_name", r"\b(?:gemini|sonnet|opus|haiku|claude)-[\w.\-*]*"),
    ("model_name", r"(?<![\w.])\d+(?:\.\d+)?-(?:pro|flash)\b"),
    ("model_name", r"\bAR\(\d+\)"),
    ("version", r"(?<![\w.])\d+(?:\.\d+)*\.x\b"),
    ("version", r"\b[Vv]ersion\s+\d+(?:\.\d+)*"),
    ("version", r"(?<![\w.])\d+\.\d+\.\d+(?!\d)"),
    ("name_ordinal", r"\b(?:[Pp]robes?|[Rr]anks?|[Ss]teps?|[Rr]ules?|[Ii]tems?|[Cc]aveats?|RFC)\s+\d+"
                     r"(?:\s*(?:,|and|–|to)\s*\d+)*(?![\w/])"),
    ("ci_level", r"95%\s*CI"),
    ("formula", r"(?<![\w.])\d+ \+ \d+k\b"),
    ("kilo", r"(?<![\w.])\d+k(?=\b|-)"),
    ("sci", r"(?<![\w.])\d+(?:\.\d+)?e[−+\-]?\d+\b"),
    ("alnum_id", r"[A-Za-z_#]+[0-9][\w.\-]*|(?<![\w.])[0-9][0-9.,]*[A-Za-z_][\w\-]*"),
    ("number", r"(?<![\w.])" + NUMPAT + r"|(?<![\w.\d])\.\d+"),
]
MASTER = re.compile("|".join(f"(?P<g{i}>{p})" for i, (_, p) in enumerate(PATTERNS)))
GNAME = {f"g{i}": name for i, (name, _) in enumerate(PATTERNS)}

phase_a_files = [p for p in tracked_out if p == "analysis/out/phase_a.json" or p.startswith("analysis/out/phase_a/")]
LENSES = ["ids_and_clocks_in_ids", "two_clocks", "token_conservation", "distributions", "sequences", "commit_witness",
          "ext_witness", "aiv_narration", "aiv_accounting", "swechat_tables", "correlations", "changepoints",
          "outliers", "raw_census"]
IX_FILES = ["analysis/out/phase_c/_index.json", "analysis/out/phase_c/_verification_early.json",
            "analysis/out/phase_c/_verification_ir.json"]
TAG_FILES = {
    "PA": phase_a_files, "R": phase_a_files, "A5": ["analysis/out/phase_a/a5.json"],
    "P1": ["analysis/out/probe_1.json", "analysis/out/phase_b/probe_1.json"],
    "P2": ["analysis/out/probe_2.json", "analysis/out/phase_b/probe_2.json"],
    "P3": ["analysis/out/probe_3.json"],
    "P4": ["analysis/out/probe_4.json", "analysis/out/phase_b/probe_4.json"],
    "PV": ["analysis/out/phase_b_verification.json"],
    "IX": IX_FILES,
    "PG": ["analysis/out/phase_c/_proposals_grounded.json"] + [p for p in tracked_out if "/phase_c/proposals_" in p],
    "RK": ["analysis/out/phase_d/ranking.json"],
    "PR": ["analysis/prereg.json"],
    "recon": [p for p in tracked_out if "/recon/" in p],
    "build": [p for p in tracked_out if "/build/" in p],
}
for L in LENSES:
    TAG_FILES[L] = [f"analysis/out/phase_c/{L}.json"] + IX_FILES
TAG_FILES["raw_census"] = ["analysis/out/phase_a/a6_raw_census.json"] + IX_FILES
SECTION_TAGS = {
    "0": ["P1", "P2", "P3", "P4", "PV", "IX", "PA", "recon"],
    "1": ["P1", "P2", "P3", "P4", "PV", "PR"], "1.2": ["P1", "PV"], "1.3": ["P2", "PV"], "1.4": ["P3", "PV"],
    "1.5": ["P4", "PV", "PR"], "1.6": ["IX"],
    "2": ["PA", "R", "A5", "PV"],
    "3": ["PV", "PR"], "3.1": ["P1", "PV"], "3.2": ["P2", "PV"], "3.3": ["P3", "PV"], "3.4": ["P4", "PV", "PR"],
    "4": ["IX", "PG"], "4.3": ["IX", "PG", "RK", "A5"], "4.4": ["RK", "IX"],
    "5": ["PA", "PV", "IX", "PR", "build"], "6": ["P1", "P2", "P3", "P4", "PA", "IX", "PV", "RK"],
}
TAG_RES = [
    ("P1", r"\bP1\b"), ("P2", r"\bP2\b"), ("P3", r"\bP3\b"), ("P4", r"\bP4\b"), ("PA", r"\bPA\b"),
    ("R", r"\bR:A\d"), ("A5", r"\bA5\b"), ("PV", r"\bPV\b"), ("IX", r"\bIX\b"), ("PG", r"\bPG\b"),
    ("RK", r"\bRK\b|\[D\]"), ("PR", r"\bPR\b|prereg"), ("recon", r"out/recon"), ("build", r"out/build"),
    ("ids_and_clocks_in_ids", r"\bids(?:_and_clocks_in_ids)?/"), ("token_conservation", r"\bTC\d+|token_conservation"),
    ("distributions", r"\bD\d+\b|distributions"), ("sequences", r"\bS\d+\b|sequences/"),
    ("aiv_narration", r"\bN\d+\b|aiv_narration"), ("swechat_tables", r"\bT\d+\b|swechat_tables"),
    ("raw_census", r"A6-O\d+|raw_census"), ("two_clocks", r"two_clocks"), ("commit_witness", r"commit_witness"),
    ("ext_witness", r"ext_witness"), ("aiv_accounting", r"aiv_accounting"), ("correlations", r"correlations/"),
    ("changepoints", r"changepoints"), ("outliers", r"outliers/"),
]
LC_RE = re.compile(r"LC:(\w+)")


def line_tags(s):
    tags = {t for t, p in TAG_RES if re.search(p, s)}
    for m in LC_RE.finditer(s):
        if m.group(1) in LENSES:
            tags.add(m.group(1))
    return tags


def section_default_tags(sec):
    best, out = "", []
    for k, v in SECTION_TAGS.items():
        if (sec == k or sec.startswith(k + ".")) and len(k) >= len(best):
            best, out = k, v
    return set(out)


def decimals_of(body):
    return len(body.split(".", 1)[1]) if "." in body else 0


def sig_digits(body):
    b = body.replace(",", "").lstrip("0").lstrip(".").lstrip("0")
    if "." in body:
        return len(b.replace(".", ""))
    return len(b.rstrip("0")) or 1


text = open(FINDINGS, encoding="utf-8").read()
lines = text.split("\n")
numbers, ignored = [], []
section, in_table, table_hash_col, table_header_tags = "0", False, False, set()
item, prev_kind = 0, "blank"
for ln, raw in enumerate(lines, start=1):
    s = raw
    hm = re.match(r"^(#{1,6})\s+(.*)$", s)
    if hm:
        sm = re.match(r"(\d+(?:\.\d+)*)\.?\s", hm.group(2) + " ")
        if sm:
            section = sm.group(1)
        elif hm.group(2).strip().lower().startswith("read this first"):
            section = "0"
        for m in re.finditer(r"\d+(?:\.\d+)*", s):
            ignored.append({"line": ln, "text": m.group(0), "reason": "heading"})
        in_table, prev_kind = False, "heading"
        continue
    stripped = s.strip()
    is_row = stripped.startswith("|")
    # logical item: a table row, or a bullet / paragraph together with its wrapped continuation lines
    if not stripped:
        prev_kind = "blank"
    elif is_row or re.match(r"^\s*(?:[-*]\s|\d+\.\s|\*\*)", s) or prev_kind in ("blank", "heading", "row"):
        item += 1
        prev_kind = "row" if is_row else "text"
    if is_row:
        if re.fullmatch(r"\s*\|[\s\-:|]+\|?\s*", s):
            continue
        cells = s.split("|")
        if not in_table:
            in_table = True
            table_hash_col = len(cells) > 1 and cells[1].strip() == "#"
            table_header_tags = line_tags(s)
        elif table_hash_col and len(cells) > 1:
            first = cells[1]
            for m in re.finditer(r"\d+", first):
                ignored.append({"line": ln, "text": m.group(0), "reason": "table_row_ordinal"})
            pos = s.index("|") + 1
            s = s[:pos] + " " * len(first) + s[pos + len(first):]
    else:
        in_table = False
    om = re.match(r"^(\s*)(\d+)\.\s", s)
    if om:
        ignored.append({"line": ln, "text": om.group(2), "reason": "list_ordinal"})
        s = s[:om.start(2)] + " " * len(om.group(2)) + s[om.end(2):]
    tags = line_tags(raw) | (table_header_tags if is_row else set()) | section_default_tags(section)
    cited = sorted({f for t in tags for f in TAG_FILES.get(t, [])})
    for m in MASTER.finditer(s):
        kind = GNAME[m.lastgroup]
        tok, a, b = m.group(0), m.start(), m.end()
        items = []
        if kind == "backtick":
            inner = tok[1:-1].strip()
            if re.fullmatch(NUMPAT, inner):
                items.append(("plain", inner, a + 1, b - 1, 1.0))
            else:
                if re.search(r"\d", inner):
                    ignored.append({"line": ln, "text": tok, "reason": "backtick_non_numeric"})
                continue
        elif kind == "number":
            items.append(("plain", tok, a, b, 1.0))
        elif kind == "sci":
            items.append(("sci", tok, a, b, 1.0))
        elif kind == "kilo":
            items.append(("kilo", tok[:-1], a, b, 1000.0))
        elif kind == "formula":
            for mm in re.finditer(r"\d+", tok):
                items.append(("formula_coefficient", mm.group(0), a + mm.start(), a + mm.end(), 1.0))
        else:
            if re.search(r"\d", tok):
                ignored.append({"line": ln, "text": tok, "reason": kind})
            continue
        for ikind, body, ia, ib, mult in items:
            if ikind == "sci":
                mant, exp = body.split("e", 1)
                value = parse_num(mant, exp)
                d, sd = decimals_of(mant), sig_digits(mant)
                half = 0.5 * 10.0 ** (-d) * 10.0 ** int(exp.replace("−", "-"))
            else:
                value = parse_num(body) * mult
                d, sd = decimals_of(body), sig_digits(body)
                half = 0.5 * 10.0 ** (-d) * mult
            signed = ""
            if ia >= 1 and s[ia - 1] in "−-+" and (ia < 2 or s[ia - 2] in " \t[(=,;:/|"):
                signed = s[ia - 1]
                if signed in "−-":
                    value = -value
            pct = s[ib:ib + 1] == "%" or s[ib:ib + 2] == " %"
            numbers.append({"id": len(numbers), "line": ln, "item": item, "section": section,
                            "text": signed + (tok if ikind == "kilo" else s[ia:ib]) + ("%" if pct else ""),
                            "kind": ikind, "value": value, "decimals": d, "sig_digits": sd, "half_width": half,
                            "percent": pct, "context": raw[max(0, ia - 80):ib + 60].strip(),
                            "tags": sorted(tags), "cited_files": cited})


# ---------------------------------------------------------------------------------------------- matching
def interval(x, half, widen=1.0):
    h = half * widen * (1 + 1e-9) + 1e-12 * max(1.0, abs(x))
    return x - h, x + h


def match(idx, rec):
    """Return (status, scale, centre, half, hit_indices) for one FINDINGS number against one index."""
    x, half = rec["value"], rec["half_width"]
    tries = []
    if rec["percent"]:
        tries += [("found", "x/100", x / 100, half / 100), ("found", "x", x, half)]
    else:
        tries += [("found", "x", x, half)]
    if rec["kind"] in ("plain", "sci") and not rec["percent"] and rec["decimals"] > 0:
        tries += [("found_scaled", "x/100", x / 100, half / 100), ("found_scaled", "x*100", x * 100, half * 100)]
    if x < 0:
        tries += [("found_abs", "|x|", -x, half)]
        if rec["percent"]:
            tries += [("found_abs", "|x|/100", -x / 100, half / 100)]
    if rec["kind"] == "kilo":
        tries += [("found_kilo_mantissa", "x/1000", x / 1000, 0.5)]
    for status, scale, v, h in tries:
        lo, hi = interval(v, h)
        hs = idx.hits(lo, hi)
        if len(hs):
            return status, scale, v, h, hs
    v0 = x / 100 if rec["percent"] else x
    h0 = half / 100 if rec["percent"] else half
    lo, hi = interval(v0, h0, widen=3.0)
    hs = idx.hits(lo, hi)
    if len(hs):
        return "near_miss", "within 1.5 last-digit units", v0, h0, hs
    return "not_found", None, v0, h0, np.array([], dtype=np.int64)


def chance_expected(idx, v, h):
    w = 2 * h
    return sum(idx.count(v + k * w - h, v + k * w + h) for k in CHANCE_OFFSETS) / len(CHANCE_OFFSETS)


pri_file_id = {rel: i for i, (rel, _) in enumerate(PRI.files)}
hitsets = {}
for rec in numbers:
    status, scale, v, h, hs = match(PRI, rec)
    rec["status"], rec["scale"] = status, scale
    rec["n_hits"] = int(len(hs))
    rec["chance_expected"] = round(chance_expected(PRI, v, h), 4)
    fids = PRI.f[hs] if len(hs) else np.array([], dtype=np.uint32)
    rec["n_files_hit"] = int(len(np.unique(fids)))
    cited_ids = np.array([pri_file_id[c] for c in rec["cited_files"] if c in pri_file_id], dtype=np.uint32)
    in_c = np.isin(fids, cited_ids) if len(cited_ids) else np.zeros(len(hs), dtype=bool)
    rec["in_cited_source"] = None if len(cited_ids) == 0 else bool(in_c.any())
    rec["cited_files_outside_primary"] = [c for c in rec["cited_files"] if c not in pri_file_id]
    sub = hs[:HIT_CAP]
    hitsets[rec["id"]] = (np.unique(np.concatenate([PRI.r[sub], PRI.pr[sub]])) if len(sub) else np.array([], np.uint32),
                          sub, in_c[:HIT_CAP])

# co-location within a FINDINGS item. Record keys k have size n_k (indexed values whose record or parent record is k).
# A number text t with c_t hits among V indexed values lands in a random key of size n_k with probability
# p = 1 - exp(-n_k c_t / V). For a key holding the item texts S (|S| >= 2), E = C * prod_{t in S} p, with C the number of
# candidate keys examined for the item, is the chance expectation of finding such a key. A number is colocated when a
# key holding it has E <= COLOC_MAX_E. Candidate keys are those of the item's numbers with at most ANCHOR_MAX_K keys;
# more frequent numbers are tested only as members.
V = len(PRI.v)
KEY_SIZE = np.bincount(np.concatenate([PRI.r, PRI.pr]).astype(np.int64))
by_item = {}
for rec in numbers:
    by_item.setdefault(rec["item"], []).append(rec)
for it, recs in by_item.items():
    for rec in recs:
        rec["colocated"], rec["colocated_in_cited"], rec["colocation"] = False, False, None
        rec["_coloc_keys"] = np.array([], dtype=np.uint32)
    usable = [r for r in recs if 0 < r["n_hits"] <= HIT_CAP]
    texts = sorted({r["text"] for r in usable})
    if len(texts) < 2:
        continue
    tkeys, tcount = {}, {}
    for r in usable:
        tkeys.setdefault(r["text"], hitsets[r["id"]][0])
        tcount.setdefault(r["text"], r["n_hits"])
    anchors = [t for t in texts if len(tkeys[t]) <= ANCHOR_MAX_K]
    if not anchors:
        continue
    cand = np.unique(np.concatenate([tkeys[t] for t in anchors]))
    M = np.stack([np.isin(cand, tkeys[t], assume_unique=True) for t in texts])
    nk = KEY_SIZE[cand.astype(np.int64)].astype(np.float64)
    lam = np.array([tcount[t] for t in texts], dtype=np.float64)[:, None] * nk[None, :] / V
    logp = np.log(-np.expm1(-lam))
    present = M.sum(0)
    logE = math.log(len(cand)) + np.where(M, logp, 0.0).sum(0)
    sig = (present >= 2) & (logE <= math.log(COLOC_MAX_E))
    for ti, t in enumerate(texts):
        ks = sig & M[ti]
        if not ks.any():
            continue
        best = int(np.argmin(np.where(ks, logE, np.inf)))
        info = {"E": float(f"{math.exp(logE[best]):.3g}"), "record_size": int(nk[best]),
                "n_item_texts_in_record": int(present[best]),
                "item_texts_in_record": [texts[q] for q in np.flatnonzero(M[:, best])][:12],
                "n_significant_records": int(ks.sum())}
        for r in usable:
            if r["text"] != t:
                continue
            r["colocated"], r["colocation"], r["_coloc_keys"] = True, info, cand[ks]
            keys_i, sub_i, inc_i = hitsets[r["id"]]
            if inc_i.any():
                ci = sub_i[inc_i]
                r["colocated_in_cited"] = bool(np.isin(PRI.r[ci], cand[ks]).any() or np.isin(PRI.pr[ci], cand[ks]).any())
for rec in numbers:
    if rec["status"] in ("near_miss", "not_found"):
        rec["trace_class"] = "not_found"
    elif rec["colocated"]:
        rec["trace_class"] = "colocated"
    elif rec["chance_expected"] <= SPECIFIC_MAX_E:
        rec["trace_class"] = "specific"
    else:
        rec["trace_class"] = "chance_level"

# restatements: an untraced number whose identical text is colocated on another FINDINGS line
traced_lines = {}
for rec in numbers:
    if rec["trace_class"] in ("colocated", "specific"):
        traced_lines.setdefault(rec["text"].lstrip("+"), []).append(rec["line"])
for rec in numbers:
    if rec["trace_class"] in ("chance_level", "not_found"):
        rec["same_text_traced_on_lines"] = sorted(set(traced_lines.get(rec["text"].lstrip("+"), [])) - {rec["line"]})[:10]

# example locations, nearest values, secondary hits
need_pri, need_sec = [], []
for rec in numbers:
    keys_i, sub, in_c = hitsets.pop(rec["id"])
    ck = rec.pop("_coloc_keys")
    in_k = (np.isin(PRI.r[sub], ck) | np.isin(PRI.pr[sub], ck)) if len(ck) else np.zeros(len(sub), dtype=bool)
    chosen, seen = [], set()
    for pool in (sub[in_k & in_c], sub[in_k & ~in_c], sub[in_c], sub[~in_c]):
        for j in pool[:5000]:
            fi = int(PRI.f[j])
            if fi in seen:
                continue
            seen.add(fi)
            chosen.append(int(j))
            if len(chosen) >= N_WHERE:
                break
        if len(chosen) >= N_WHERE:
            break
    rec["_where"] = chosen
    need_pri += [(int(PRI.f[j]), int(PRI.seq[j])) for j in chosen]
    if rec["trace_class"] in ("chance_level", "not_found"):
        near = PRI.nearest(rec["value"] / 100 if rec["percent"] else rec["value"], k=2)
        rec["_near"] = near
        need_pri += [(int(PRI.f[j]), int(PRI.seq[j])) for j in near]
        sstatus, sscale, sv, sh, shs = match(SEC, rec)
        rec["secondary_status"], rec["secondary_scale"] = sstatus, sscale
        sch, sf = [], set()
        for j in shs[:5000]:
            fi = int(SEC.f[j])
            if fi not in sf:
                sf.add(fi)
                sch.append(int(j))
        rec["_sec"] = sch[:6]
        need_sec += [(int(SEC.f[j]), int(SEC.seq[j])) for j in rec["_sec"]]

loc_pri = PRI.locate(need_pri)
loc_sec = SEC.locate(need_sec)


def loc_entry(idx, locs, j, committed_set=None):
    fi, sq = int(idx.f[j]), int(idx.seq[j])
    e = {"file": idx.files[fi][0], "value": float(idx.v[j])}
    if committed_set is not None:
        e["committed"] = e["file"] in committed_set
    e.update(locs.get((fi, sq)) or {})
    if len(e.get("path", "")) > 220:
        e["path"] = e["path"][:100] + " ... " + e["path"][-110:]
    return e


for rec in numbers:
    rec["where"] = [loc_entry(PRI, loc_pri, j) for j in rec.pop("_where")]
    if "_near" in rec:
        rec["nearest_primary_values"] = [loc_entry(PRI, loc_pri, j) for j in rec.pop("_near")]
        rec["secondary_hits"] = [loc_entry(SEC, loc_sec, j, SEC_COMMITTED) for j in rec.pop("_sec")]
    rec.pop("half_width")
    rec["n_cited_files"] = len(rec.pop("cited_files"))

date_checks = []
for ig in ignored:
    if ig["reason"] in ("date", "time_of_day"):
        files = [rel for rel, t in PRI.raw_text.items() if ig["text"] in t]
        date_checks.append({"line": ig["line"], "text": ig["text"], "n_primary_files_containing": len(files),
                            "files": files[:5]})


def tally(key, recs):
    out = {}
    for r in recs:
        out[r[key]] = out.get(r[key], 0) + 1
    return out


by_sec = {}
for rec in numbers:
    top = rec["section"].split(".")[0]
    by_sec.setdefault(top, {}).setdefault(rec["trace_class"], 0)
    by_sec[top][rec["trace_class"]] += 1
review = [r for r in numbers if r["trace_class"] in ("chance_level", "not_found")]
out = {
    "script": "analysis/probes/phase_d_trace.py",
    "findings": {"path": "analysis/FINDINGS.md", "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                 "n_lines": len(lines), "committed": "analysis/FINDINGS.md" in tracked_analysis},
    "head": git("rev-parse", "HEAD").strip(),
    "tag_files": {"note": "a number's cited files = union of tag_files over its `tags`", **TAG_FILES},
    "primary_set": {"description": "git ls-files analysis/out, suffix .json or .txt", "n_files": len(PRI.files),
                    "n_indexed_values": int(len(PRI.v)),
                    "files_modified_in_worktree_read_from_HEAD": sorted(modified_out & set(tracked_out)),
                    "files": [r for r, _ in PRI.files]},
    "secondary_set": {"committed": secondary_committed, "uncommitted": untracked_out,
                      "n_indexed_values": int(len(SEC.v))},
    "parameters": {"chance_offsets_in_window_widths": CHANCE_OFFSETS, "coloc_max_E": COLOC_MAX_E,
                   "specific_max_chance_expected": SPECIFIC_MAX_E, "hit_cap_for_colocation": HIT_CAP,
                   "anchor_max_keys": ANCHOR_MAX_K,
                   "n_indexed_values": V, "n_where": N_WHERE},
    "parameter_log": [
        {"what": "co-location chance model", "before": "pairwise E = |K_i||K_j|/N_keys",
         "after": "record-size-aware E = C * prod_t (1 - exp(-n_k c_t / V)) over all item texts in one record",
         "reason": "the pairwise model ignored record size: large parent records (e.g. a dict of every tool) "
                   "matched almost any combination of numbers"},
        {"what": "COLOC_MAX_E", "before": 0.01, "after": COLOC_MAX_E,
         "reason": "at 0.01, manual inspection found chance co-locations near the threshold (0.00462 with 33 in "
                   "distributions.json at E 0.00468; 0.0119 with 320 in changepoints.json at E 0.00418). Tightening "
                   "only moves numbers from colocated into the manual-review set"},
        {"what": "name_ordinal pattern", "before": "(?!\\w) after the ordinal number",
         "after": "(?![\\w/]) after the ordinal number",
         "reason": "'rule 0/112,677' and 'floor step 21/156' dropped a measured count as an ordinal"},
    ],
    "summary": {
        "n_numbers": len(numbers),
        "by_status": tally("status", numbers),
        "by_trace_class": tally("trace_class", numbers),
        "by_trace_class_and_top_section": by_sec,
        "n_found_not_in_cited_source": sum(1 for r in numbers if r["status"].startswith("found")
                                           and r["in_cited_source"] is False),
        "n_ignored_by_reason": tally("reason", ignored),
        "n_for_review": len(review),
        "review_by_secondary_status": tally("secondary_status", review),
        "review_with_same_text_traced_elsewhere": sum(1 for r in review if r["same_text_traced_on_lines"]),
    },
    "for_review": [{"id": r["id"], "line": r["line"], "section": r["section"], "text": r["text"],
                    "status": r["status"], "trace_class": r["trace_class"], "chance_expected": r["chance_expected"],
                    "secondary_status": r["secondary_status"],
                    "same_text_traced_on_lines": r["same_text_traced_on_lines"],
                    "secondary_files": sorted({h["file"] for h in r["secondary_hits"]}),
                    "context": r["context"]} for r in review],
    "numbers": numbers,
    "ignored": ignored,
    "date_checks": date_checks,
}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, indent=None, ensure_ascii=False, separators=(",", ":"))
print(f"{len(numbers)} numbers; status {out['summary']['by_status']}; trace_class {out['summary']['by_trace_class']}; "
      f"ignored {out['summary']['n_ignored_by_reason']}; primary values {len(PRI.v)} in {len(PRI.files)} files; "
      f"for review {len(review)} {out['summary']['review_by_secondary_status']} -> {OUT_REL}")
