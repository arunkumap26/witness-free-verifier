"""Phase E traceability audit: every numeric token in the three Phase E write-ups, searched for in analysis/out/**/*.json.

Extends analysis/probes/phase_d_trace.py (same extraction, matching, chance and co-location rules; that script runs at
import, so its functions are re-stated here rather than imported) to three documents and to Phase E outputs, which are
not committed yet.

Reads
  analysis/SECOND_PASS.md                          whole file
  analysis/TRANSFER_MATRIX.md                      whole file
  analysis/DECISION_TABLE.md                       only the section from '## Phase E update' to the end of the file
  PRIMARY search set: every analysis/out/**/*.json on disk (worktree copy), each file labelled committed / modified /
    untracked, EXCEPT
      analysis/out/phase_d/trace.json, analysis/out/phase_d/audit_log.json   (audit outputs: copies of report numbers)
      analysis/out/phase_e/trace.json, analysis/out/phase_e/audit_log.json   (this audit's own outputs)
      analysis/out/phase_e/track_b/**                                        (Track B evidence; another workflow writes it)
    and, inside every JSON, the subtrees under keys that are copies of write-up text (circular: a number found there
    proves nothing): md_number_check, and any key starting with "interpretation". Values skipped this way are counted.
  SECONDARY search set, consulted only for numbers the primary set lacks or matches only at chance level:
    analysis/prereg_e.json, analysis/prereg.json (thresholds), analysis/PREREG_E.md, analysis/notes/phase_e_*.md,
    analysis/out/phase_e/track_b/**/*.json.
Writes
  analysis/out/phase_e/trace.json

Extraction. As phase_d_trace.py, with three changes: (1) heading lines ARE extracted (Phase E headings carry claims such
as "the 10 honest request-id failures"), except the leading section number ("2.1", "4."); (2) the model-name rule is
case-insensitive and also covers gpt-/glm-/minimax- names ("Claude-Opus-4.6", "gpt-5.3-codex"); (3) inline list
ordinals ("... rates). 2. Under ...") are ignored. Every exclusion is logged under `ignored`.

Matching. Identical to phase_d_trace.py: a number with d displayed decimals matches any indexed value within
+-0.5*10^-d (percent also at x/100; non-integers also at x/100 and x*100 as `found_scaled`; negatives also as |x|; "k"
suffix also as the mantissa). chance_expected and co-location (E = C * prod_t (1 - exp(-n_k c_t / V)) <= COLOC_MAX_E)
are computed exactly as there; trace_class = colocated > specific > chance_level > not_found.

Citation (new). Each document names its sources by file and JSON path, e.g. "`a1_p1_p3.json candidates['P1/cc_local']`"
or a bare "`units.*.benign`" under a section whose Source line names f1_bracket.json. Every backtick span or bare token
that names a .json file (brace sets {B,E} expanded; a directory such as n7_content_shards/ means every JSON in it) is
resolved to a primary file; a following path (or a bare path in a section that names files) is resolved inside that
file (segments: .key, ['key'], ["key"], [n], [*], .*, glob characters * and the ellipsis inside keys; a first segment
that is not a top-level key is searched for at any depth). For each number:
  cited_files     = files named on its line, in its lowest section (any line) and that section's parent intro, and the
                    document default (SECOND_PASS: second_pass.json; TRANSFER_MATRIX and the DECISION_TABLE section:
                    n6_grid.json, which their generator names as the only source)
  in_cited_file   = a match in any cited file
  cited_paths     = the resolved paths on its line if the line names any, else those of its section. In the two
                    generated documents (TRANSFER_MATRIX.md, DECISION_TABLE Phase E section), which cite n6_grid.json as
                    a whole, a table row's path is inferred from its own first cells (mechanism name -> row key via
                    n6_grid.json row_names; corpus -> column): cells.<row>['<col>'], transfer.primary.per_row.<row>,
                    per_column['<col>']; summary and interpretation lines -> transfer.<reading>.totals and the n_* counts
  in_cited_path   = a match inside the union of those subtrees (None if no path was cited or none resolved)
Extra mechanical checks (new):
  fraction_pairs  every "k/n": k and n sit in one JSON record (same container, its parent, or one string) of the
                  primary set; also whether that record is in a cited file
  rate_arith      every "k/n = r": |k/n - r| <= half a unit of r's last displayed digit (a transcription check)
  ci_order        every "r [lo, hi]" (also W[...]): lo <= r <= hi at displayed precision
  input hashes    second_pass.json and n6_grid.json record the sha256 of their inputs; each is compared with the file
                  on disk now (a changed input would mean the generated text is stale)

Measurement only. Whether an untraced number is arithmetic on traced numbers is decided by a person reading the
output (rule 4); that review is logged in analysis/out/phase_e/audit_log.json.

Run:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_trace
"""
import bisect
import fnmatch
import glob
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from array import array

import numpy as np

T0 = time.time()
sys.setrecursionlimit(20000)
ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT_REL = "analysis/out/phase_e/trace.json"
OUT = os.path.join(ROOT, *OUT_REL.split("/"))
DOCS = [
    {"name": "SECOND_PASS", "path": "analysis/SECOND_PASS.md", "start": None,
     "default_files": ["analysis/out/phase_e/second_pass.json"]},
    {"name": "TRANSFER_MATRIX", "path": "analysis/TRANSFER_MATRIX.md", "start": None,
     "default_files": ["analysis/out/phase_e/n6_grid.json"]},
    {"name": "DECISION_TABLE_phase_e", "path": "analysis/DECISION_TABLE.md", "start": "## Phase E update",
     "default_files": ["analysis/out/phase_e/n6_grid.json"]},
]
EXCLUDE_FILES = {"analysis/out/phase_d/trace.json", "analysis/out/phase_d/audit_log.json",
                 "analysis/out/phase_e/trace.json", "analysis/out/phase_e/audit_log.json"}
EXCLUDE_DIR_PREFIX = ("analysis/out/phase_e/track_b/",)
CIRCULAR_KEY = re.compile(r"^(?:md_number_check|interpretation.*)$")
N_WHERE = 4
CHANCE_OFFSETS = [k for k in range(-11, 12) if abs(k) >= 2]
COLOC_MAX_E = 0.001
SPECIFIC_MAX_E = 0.05
HIT_CAP = 400000
ANCHOR_MAX_K = 20000


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8")


def rel_of(p):
    return os.path.relpath(p, ROOT).replace(os.sep, "/")


# ---------------------------------------------------------------------------------------------- file sets
tracked = set(git("ls-files", "analysis").splitlines())
modified = set(git("diff", "--name-only", "HEAD", "--", "analysis").splitlines())
all_out_json = sorted(rel_of(p) for p in glob.glob(os.path.join(ROOT, "analysis", "out", "**", "*.json"), recursive=True))
primary_rel = [p for p in all_out_json if p not in EXCLUDE_FILES and not p.startswith(EXCLUDE_DIR_PREFIX)]
secondary_rel = (["analysis/prereg_e.json", "analysis/prereg.json", "analysis/PREREG_E.md"]
                 + sorted(rel_of(p) for p in glob.glob(os.path.join(ROOT, "analysis", "notes", "phase_e_*.md")))
                 + [p for p in all_out_json if p.startswith(EXCLUDE_DIR_PREFIX)])


def commit_status(rel):
    if rel not in tracked:
        return "untracked"
    return "modified" if rel in modified else "committed"


def read_text(rel):
    with open(os.path.join(ROOT, *rel.split("/")), "rb") as f:
        return f.read().decode("utf-8", errors="replace")


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


def json_values(o, out):
    """All numeric values in a JSON subtree (numbers, numbers inside strings and keys); circular subtrees skipped."""
    if isinstance(o, dict):
        for k, v in o.items():
            if CIRCULAR_KEY.match(str(k)):
                continue
            for x, _, _ in text_numbers(str(k)):
                out.append(x)
            json_values(v, out)
    elif isinstance(o, list):
        for v in o:
            json_values(v, out)
    elif isinstance(o, bool) or o is None:
        return
    elif isinstance(o, (int, float)):
        if math.isfinite(o):
            out.append(float(o))
    elif isinstance(o, str):
        for x, _, _ in text_numbers(o):
            out.append(x)


class Index:
    """Parsed numeric values of a file set: value, file id, sequence number in file, record id, parent-record id."""

    def __init__(self, files, keep_json=False):
        self.files = files
        self.vals, self.fid, self.seq = array("d"), array("I"), array("I")
        self.rec, self.prec = array("I"), array("I")
        self.raw_text, self.json = {}, {}
        self.skipped_circular = {}
        self._next = [1]
        for i, rel in enumerate(files):
            txt = read_text(rel)
            self.raw_text[rel] = txt
            obj = self._walk_file(i, rel, txt, None)
            if keep_json and obj is not None:
                self.json[rel] = obj
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
                        if CIRCULAR_KEY.match(str(k)):
                            if want is None:
                                tmp = []
                                json_values(v, tmp)
                                self.skipped_circular[rel] = self.skipped_circular.get(rel, 0) + len(tmp)
                            continue
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
            return obj
        line_starts = [0] + [m.end() for m in re.finditer("\n", txt)]
        base = self._new_id()
        line_ids, block_ids = {}, {}
        for x, a, b in text_numbers(txt):
            ln = bisect.bisect_right(line_starts, a)
            lid = line_ids.setdefault(ln, self._new_id())
            bid = block_ids.setdefault(ln // 4, self._new_id())
            emit(x, lid, bid if bid else base, lambda a=a, b=b, ln=ln: {"line": ln, "text": txt[max(0, a - 50):b + 50].replace("\n", " ")})
        return None

    def locate(self, pairs):
        by_file = {}
        for fi, s in pairs:
            by_file.setdefault(fi, {})[s] = None
        out = {}
        for fi, want in by_file.items():
            rel = self.files[fi]
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


PRI = Index(primary_rel, keep_json=True)
SEC = Index(secondary_rel)
pri_file_id = {rel: i for i, rel in enumerate(PRI.files)}
print(f"indexed primary {len(PRI.v)} values in {len(PRI.files)} files, secondary {len(SEC.v)} "
      f"({time.time() - T0:.0f}s)", flush=True)

# ---------------------------------------------------------------------------------------------- citation resolution
PATH_SEG = re.compile(r"\[(?:'([^']*)'|\"([^\"]*)\"|(\d+)|(\*))\]|\.?([^.\[\]\s]+)")


def parse_path(p):
    segs = []
    for m in PATH_SEG.finditer(p):
        if m.group(1) is not None:
            segs.append(("key", m.group(1)))
        elif m.group(2) is not None:
            segs.append(("key", m.group(2)))
        elif m.group(3) is not None:
            segs.append(("idx", int(m.group(3))))
        elif m.group(4) is not None:
            segs.append(("any", None))
        else:
            k = m.group(5)
            segs.append(("any", None) if k == "*" else ("key", k))
    return segs


def step(nodes, seg):
    kind, k = seg
    out = []
    for n in nodes:
        if kind == "idx":
            if isinstance(n, list) and k < len(n):
                out.append(n[k])
            elif isinstance(n, dict) and str(k) in n:
                out.append(n[str(k)])
        elif kind == "any":
            out += list(n.values()) if isinstance(n, dict) else (list(n) if isinstance(n, list) else [])
        else:
            if not isinstance(n, dict):
                continue
            pat = k.replace("…", "*")
            if k in n:
                out.append(n[k])
            elif any(c in pat for c in "*?["):
                out += [v for kk, v in n.items() if fnmatch.fnmatchcase(str(kk), pat)]
    return out


def find_key_anywhere(o, key, limit=50):
    found, stack = [], [o]
    while stack and len(found) < limit:
        n = stack.pop()
        if isinstance(n, dict):
            for k, v in n.items():
                if k == key:
                    found.append(v)
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(n, list):
            stack += [v for v in n if isinstance(v, (dict, list))]
    return found


def resolve(rel, path):
    obj = PRI.json.get(rel)
    if obj is None:
        return []
    segs = parse_path(path)
    if not segs:
        return [obj]
    nodes = step([obj], segs[0])
    if not nodes and segs[0][0] == "key":
        nodes = find_key_anywhere(obj, segs[0][1])
    for s in segs[1:]:
        nodes = step(nodes, s)
        if not nodes:
            break
    return nodes


_subtree_cache = {}


def subtree_values(rel, path):
    key = (rel, path)
    if key not in _subtree_cache:
        vals = []
        for n in resolve(rel, path):
            json_values(n, vals)
        _subtree_cache[key] = np.sort(np.array(vals, dtype=np.float64))
    return _subtree_cache[key]


JSON_NAME = re.compile(r"(?<![\w/])((?:analysis/out/)?(?:[\w\-]+/)*[\w\-{},*]*\.json|n7_content_shards/?)(?![\w])")


def expand_braces(s):
    m = re.search(r"\{([^{}]*)\}", s)
    if not m:
        return [s]
    return [x for alt in m.group(1).split(",") for x in expand_braces(s[:m.start()] + alt + s[m.end():])]


def files_for_name(name):
    out = []
    for nm in expand_braces(name):
        nm = nm.rstrip("/")
        if nm.endswith("n7_content_shards"):
            out += [p for p in PRI.files if p.startswith("analysis/out/phase_e/n7_content_shards/")]
            continue
        cands = [nm] if nm.startswith("analysis/") else [f"analysis/out/phase_e/{nm}", f"analysis/out/{nm}"]
        hit = [c for c in cands if c in pri_file_id]
        if not hit and "*" in nm:
            hit = [p for p in PRI.files if any(fnmatch.fnmatchcase(p, c) for c in cands)]
        if not hit:
            base = nm.split("/")[-1]
            hit = [p for p in PRI.files if p.split("/")[-1] == base][:3]
        out += hit
    return out


BARE_PATH = re.compile(r"^[A-Za-z_][\w]*(?:\[[^\]]*\]|\.[\w*…\-]+|\[\*\])+$|^[A-Za-z_]\w*_\w+$")


def line_refs(raw):
    """[(file, path or None)] named on a line; bare paths returned separately."""
    refs, bare, unresolved = [], [], []
    spans = [m.group(1) for m in re.finditer(r"`([^`\n]*)`", raw)]
    for sp in spans:
        m = JSON_NAME.search(sp)
        if m:
            files = files_for_name(m.group(1))
            rest = sp[m.end():].strip()
            if not files:
                if not sp.strip().startswith(("analysis/prereg", "prereg")):
                    unresolved.append(sp)
                continue
            for f in files:
                refs.append((f, rest or None))
        elif BARE_PATH.match(sp.strip()) and not sp.strip().endswith((".md", ".py")):
            bare.append(sp.strip())
    outside = re.sub(r"`[^`\n]*`", " ", raw)
    for m in JSON_NAME.finditer(outside):
        for f in files_for_name(m.group(1)):
            refs.append((f, None))
    return refs, bare, unresolved


# Generated documents (TRANSFER_MATRIX.md and the DECISION_TABLE Phase E section) cite n6_grid.json as a whole. Their
# table rows and summary lines map one-to-one onto n6_grid.json paths, inferred here from the row's own text.
N6 = "analysis/out/phase_e/n6_grid.json"
_n6 = PRI.json.get(N6, {})
ROW_BY_NAME = {v: k for k, v in _n6.get("row_names", {}).items()}
COLUMNS = list(_n6.get("columns_loaded", [])) + list(_n6.get("columns_not_loaded", []))
SENS_KEYS = [("Phase B units only", "phase_b_units_only"), ("Labels before artifact checks", "precheck_labels"),
             ("best stratum", "n2_aiv_cu_best_stratum"), ("worst stratum", "n2_aiv_cu_worst_stratum"),
             ("Probe 2 subagent stratum", "p2_subagent_stratum")]


def clean_corpus(c):
    c = re.split(r"\s+[\(\[]", c.strip(), maxsplit=1)[0]
    return c.strip("* ")


def infer_n6_paths(raw, section_title, header_cells):
    """[(N6, path)] for one line of a generated document, or []."""
    s = raw.strip()
    out = []
    if s.startswith("|"):
        cells = [c.strip() for c in s.strip("|").split("|")]
        first = cells[0].strip("* ") if cells else ""
        if first not in ROW_BY_NAME:
            first = clean_corpus(first)
        second = clean_corpus(cells[1]) if len(cells) > 1 else ""
        h1 = header_cells[1] if len(header_cells) > 1 else ""
        if first in ROW_BY_NAME:
            rk = ROW_BY_NAME[first]
            if second in COLUMNS and h1 == "Corpus":
                out.append((N6, f"cells.{rk}['{second}']"))
            elif h1 == "testable":
                out.append((N6, f"transfer.primary.per_row.{rk}"))
            else:
                out.append((N6, f"cells.{rk}"))
        elif first in COLUMNS:
            out.append((N6, f"per_column['{first}']"))
        return out
    for phrase, key in SENS_KEYS:
        if phrase in s:
            return [(N6, f"transfer.{key}.totals")]
    if "update kind" in s:
        return [(N6, "update_kind_counts")]
    if s.startswith(("**Totals over the grid**", "- Mechanisms", "- 26 loaded", "- Loaded columns")) or \
            "INTERPRETATION" in section_title or "strongest finding" in section_title:
        return [(N6, "transfer.primary.totals"), (N6, "n_cells_not_loaded"), (N6, "n_cells_loaded"),
                (N6, "n_rows"), (N6, "n_columns_loaded"), (N6, "n_columns_not_loaded")]
    return out


# ---------------------------------------------------------------------------------------------- doc extraction
NUMPAT =r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
PATTERNS = [
    ("backtick", r"`[^`\n]*`"),
    ("date", r"(?<!\d)(?:19|20)\d{2}-\d{2}(?:-\d{2})?(?!\d)"),
    ("time_of_day", r"(?<!\d)\d{1,2}:\d{2}:\d{2}(?!\d)"),
    ("bet_odds", r"(?<![\d.,])\d+:\d+(?![\d.])"),
    ("citation_year", r"et al\.\s+\d{4}"),
    ("section_ref", r"§\s?\d+(?:\.\d+)*"),
    ("model_name", r"\b(?i:gemini|sonnet|opus|haiku|claude|gpt|glm|minimax|qwen|llama|deepseek)[\w]*-[\w.\-*]*"),
    ("model_name", r"(?<![\w.])\d+(?:\.\d+)?-(?:pro|flash)\b"),
    ("model_name", r"\bAR\(\d+\)"),
    ("version", r"(?<![\w.])\d+(?:\.\d+)*\.x\b"),
    ("version", r"\b[Vv]ersion\s+\d+(?:\.\d+)*"),
    ("version", r"(?<![\w.])\d+\.\d+\.\d+(?!\d)"),
    ("name_ordinal", r"\b(?:[Pp]robes?|[Rr]anks?|[Ss]teps?|[Rr]ules?|[Ii]tems?|[Cc]aveats?|RFC|[Ss]ections?|[Pp]hases?)\s+\d+(?:\.\d+)*"
                     r"(?:\s*(?:,|and|–|to)\s*\d+(?:\.\d+)*)*(?![\w/])"),
    ("inline_ordinal", r"(?<=[.)] )\d{1,2}\.(?= [A-Z])"),
    ("ci_level", r"95%\s*CI|W\[95%\]|\[95%\]"),
    ("formula", r"(?<![\w.])\d+ \+ \d+k\b"),
    ("kilo", r"(?<![\w.])\d+k(?=\b|-)"),
    ("sci", r"(?<![\w.])\d+(?:\.\d+)?e[−+\-]?\d+\b"),
    ("alnum_id", r"[A-Za-z_#]+[0-9][\w.\-]*|(?<![\w.])[0-9][0-9.,]*[A-Za-z_][\w\-]*"),
    ("number", r"(?<![\w.])" + NUMPAT + r"|(?<![\w.\d])\.\d+"),
]
MASTER = re.compile("|".join(f"(?P<g{i}>{p})" for i, (_, p) in enumerate(PATTERNS)))
GNAME = {f"g{i}": name for i, (name, _) in enumerate(PATTERNS)}


def decimals_of(body):
    return len(body.split(".", 1)[1]) if "." in body else 0


def sig_digits(body):
    b = body.replace(",", "").lstrip("0").lstrip(".").lstrip("0")
    if "." in body:
        return len(b.replace(".", ""))
    return len(b.rstrip("0")) or 1


numbers, ignored, docs_meta, ref_log = [], [], [], []
item = 0
for doc in DOCS:
    text = read_text(doc["path"])
    all_lines = text.split("\n")
    start = 0
    if doc["start"]:
        start = next(i for i, l in enumerate(all_lines) if l.startswith(doc["start"]))
    lines = all_lines[start:]
    seg_text = "\n".join(lines)
    docs_meta.append({"name": doc["name"], "path": doc["path"], "first_line": start + 1, "last_line": len(all_lines),
                      "n_lines_audited": len(lines), "sha256_of_audited_text": hashlib.sha256(seg_text.encode("utf-8")).hexdigest(),
                      "sha256_file": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                      "commit_status": commit_status(doc["path"]), "default_cited_files": doc["default_files"]})
    # sections: (level, title); refs gathered per section first
    sec_of_line, sec_titles, sec_level, sec_parent = [], [], [], []
    stack = []
    for raw in lines:
        hm = re.match(r"^(#{1,6})\s+(.*)$", raw)
        if hm:
            lvl = len(hm.group(1))
            while stack and sec_level[stack[-1]] >= lvl:
                stack.pop()
            sec_parent.append(stack[-1] if stack else None)
            sec_titles.append(hm.group(2).strip())
            sec_level.append(lvl)
            stack.append(len(sec_titles) - 1)
        sec_of_line.append(stack[-1] if stack else None)
    per_line = [line_refs(raw) for raw in lines]
    sec_refs, sec_bare = {}, {}
    for li, (refs, bare, unres) in enumerate(per_line):
        s = sec_of_line[li]
        sec_refs.setdefault(s, []).extend(refs)
        sec_bare.setdefault(s, []).extend(bare)
        for u in unres:
            ref_log.append({"doc": doc["name"], "line": start + li + 1, "reference": u, "resolved": False,
                            "reason": "no primary file of that name"})
    # intro refs of a section = refs on lines of that section before its first child heading
    intro_refs = {}
    for li, raw in enumerate(lines):
        s = sec_of_line[li]
        intro_refs.setdefault(s, [])
    for s in set(sec_of_line):
        lines_s = [li for li, x in enumerate(sec_of_line) if x == s]
        intro_refs[s] = [r for li in lines_s for r in per_line[li][0]]

    def section_chain(s):
        out = []
        while s is not None:
            out.append(s)
            s = sec_parent[s]
        return out

    def resolve_refs(refs, bare, files_ctx):
        """resolved (file, path) list from explicit refs plus bare paths applied to the context files"""
        out = []
        for f, p in refs:
            if p:
                n = len(resolve(f, p))
                ref_log.append({"doc": doc["name"], "file": f, "path": p, "n_nodes": n, "resolved": n > 0})
                if n:
                    out.append((f, p))
        for p in bare:
            got = False
            for f in sorted(set(files_ctx)):
                if f.endswith("second_pass.json") and len(set(files_ctx)) > 1:
                    continue
                if resolve(f, p):
                    out.append((f, p))
                    got = True
            ref_log.append({"doc": doc["name"], "bare_path": p, "context_files": sorted(set(files_ctx))[:8],
                            "resolved": got})
        return out

    sec_paths_cache = {}
    in_table, table_hash_col, prev_kind, header_cells = False, False, "blank", []
    for li, raw in enumerate(lines):
        ln = start + li + 1
        s = raw
        sec = sec_of_line[li]
        chain = section_chain(sec)
        hm = re.match(r"^(#{1,6})\s+(.*)$", s)
        is_heading = bool(hm)
        if is_heading:
            pm = re.match(r"^(#{1,6}\s+)(\d+(?:\.\d+)*\.?)(\s)", s)
            if pm:
                ignored.append({"doc": doc["name"], "line": ln, "text": pm.group(2), "reason": "heading_section_number"})
                s = s[:pm.start(2)] + " " * len(pm.group(2)) + s[pm.end(2):]
            in_table, prev_kind = False, "heading"
            item += 1
        stripped = s.strip()
        is_row = stripped.startswith("|")
        if not is_heading:
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
                header_cells = [c.strip() for c in s.strip().strip("|").split("|")]
            elif table_hash_col and len(cells) > 1:
                first = cells[1]
                for m in re.finditer(r"\d+", first):
                    ignored.append({"doc": doc["name"], "line": ln, "text": m.group(0), "reason": "table_row_ordinal"})
                pos = s.index("|") + 1
                s = s[:pos] + " " * len(first) + s[pos + len(first):]
        elif not is_heading:
            in_table = False
        om = re.match(r"^(\s*)(\d+)\.\s", s)
        if om:
            ignored.append({"doc": doc["name"], "line": ln, "text": om.group(2), "reason": "list_ordinal"})
            s = s[:om.start(2)] + " " * len(om.group(2)) + s[om.end(2):]
        # citations
        lrefs, lbare, _ = per_line[li]
        cited = set(doc["default_files"])
        for c in chain:
            cited |= {f for f, _ in sec_refs.get(c, [])}
        cited |= {f for f, _ in lrefs}
        line_ctx = {f for f, _ in lrefs} or {f for f, _ in sec_refs.get(sec, [])} or set(doc["default_files"])
        lpaths = resolve_refs(lrefs, lbare, line_ctx) if (any(p for _, p in lrefs) or lbare) else []
        if not lpaths and N6 in doc["default_files"]:
            ip = infer_n6_paths(raw, sec_titles[sec] if sec is not None else "", header_cells if is_row else [])
            lpaths = [(f, p) for f, p in ip if resolve(f, p)]
            for f, p in ip:
                ref_log.append({"doc": doc["name"], "line": ln, "file": f, "path": p, "inferred_from_row_text": True,
                                "resolved": bool(resolve(f, p))})
        if lpaths:
            cpaths = lpaths
        else:
            if sec not in sec_paths_cache:
                srefs = sec_refs.get(sec, [])
                sctx = {f for f, _ in srefs} or set(doc["default_files"])
                sec_paths_cache[sec] = resolve_refs(srefs, sec_bare.get(sec, []), sctx)
            cpaths = sec_paths_cache[sec]
        section_title = sec_titles[sec] if sec is not None else ""
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
                        ignored.append({"doc": doc["name"], "line": ln, "text": tok, "reason": "backtick_non_numeric"})
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
                    ignored.append({"doc": doc["name"], "line": ln, "text": tok, "reason": kind})
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
                numbers.append({"id": len(numbers), "doc": doc["name"], "line": ln, "item": item,
                                "section": section_title[:90], "heading": is_heading,
                                "text": signed + (tok if ikind == "kilo" else s[ia:ib]) + ("%" if pct else ""),
                                "kind": ikind, "value": value, "decimals": d, "sig_digits": sd, "half_width": half,
                                "percent": pct, "context": raw[max(0, ia - 80):ib + 60].strip(),
                                "cited_files": sorted(cited), "_cpaths": cpaths, "_span": (ia, ib), "_line_text": s})

print(f"extracted {len(numbers)} numbers ({time.time() - T0:.0f}s)", flush=True)


# ---------------------------------------------------------------------------------------------- matching
def interval(x, half, widen=1.0):
    h = half * widen * (1 + 1e-9) + 1e-12 * max(1.0, abs(x))
    return x - h, x + h


def tries_for(rec):
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
    return tries


def match(idx, rec):
    """Return (status, scale, centre, half, hit_indices) for one number against one index."""
    for status, scale, v, h in tries_for(rec):
        lo, hi = interval(v, h)
        hs = idx.hits(lo, hi)
        if len(hs):
            return status, scale, v, h, hs
    x, half = rec["value"], rec["half_width"]
    v0 = x / 100 if rec["percent"] else x
    h0 = half / 100 if rec["percent"] else half
    lo, hi = interval(v0, h0, widen=3.0)
    hs = idx.hits(lo, hi)
    if len(hs):
        return "near_miss", "within 1.5 last-digit units", v0, h0, hs
    return "not_found", None, v0, h0, np.array([], dtype=np.int64)


def in_sorted(arr, rec):
    for status, scale, v, h in tries_for(rec):
        lo, hi = interval(v, h)
        if np.searchsorted(arr, hi, side="right") > np.searchsorted(arr, lo, side="left"):
            return True
    return False


def chance_expected(idx, v, h):
    w = 2 * h
    return sum(idx.count(v + k * w - h, v + k * w + h) for k in CHANCE_OFFSETS) / len(CHANCE_OFFSETS)


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
    rec["in_cited_file"] = None if len(cited_ids) == 0 else bool(in_c.any())
    cp = rec.pop("_cpaths")
    rec["cited_paths"] = [f"{f.split('/')[-1]} {p}" for f, p in cp][:8]
    if cp and status.startswith("found"):
        rec["in_cited_path"] = any(in_sorted(subtree_values(f, p), rec) for f, p in cp)
    else:
        rec["in_cited_path"] = None if not cp else False
    files_hit = sorted({PRI.files[int(i)] for i in np.unique(fids)}) if len(fids) else []
    rec["hit_commit_status"] = sorted({commit_status(f) for f in files_hit})
    sub = hs[:HIT_CAP]
    hitsets[rec["id"]] = (np.unique(np.concatenate([PRI.r[sub], PRI.pr[sub]])) if len(sub) else np.array([], np.uint32),
                          sub, in_c[:HIT_CAP])
print(f"matched ({time.time() - T0:.0f}s)", flush=True)

# co-location within a document item (phase_d_trace.py rule, unchanged)
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
print(f"colocation done ({time.time() - T0:.0f}s)", flush=True)

traced_lines = {}
for rec in numbers:
    if rec["trace_class"] in ("colocated", "specific") or rec["in_cited_path"]:
        traced_lines.setdefault(rec["text"].lstrip("+"), []).append(f"{rec['doc']}:{rec['line']}")
for rec in numbers:
    rec["same_text_traced_on_lines"] = sorted(set(traced_lines.get(rec["text"].lstrip("+"), []))
                                              - {f"{rec['doc']}:{rec['line']}"})[:8]

# ---------------------------------------------------------------------------------------------- extra checks
FRAC = re.compile(r"(?<![\w.,/])(\d{1,3}(?:,\d{3})+|\d+)/(\d{1,3}(?:,\d{3})+|\d+)(?![\d/])")
RATE = re.compile(r"(?<![\w.,/])(\d{1,3}(?:,\d{3})+|\d+)/(\d{1,3}(?:,\d{3})+|\d+)\s*=\s*\**\s*([0-9]*\.[0-9]+|\d+)(?!\d)")
CI = re.compile(r"(?<![\w./,])(−?-?\+?[0-9]*\.?[0-9]+)\**,?\s*(?:W\s*)?\[(−?-?\+?[0-9]*\.?[0-9]+),\s*(−?-?\+?[0-9]*\.?[0-9]+)\]")


def fnum(t):
    return float(t.replace(",", "").replace("−", "-").replace("+", ""))


def keys_of(x):
    lo, hi = interval(x, 0.5e-9 * max(1, abs(x)))
    hs = PRI.hits(lo, hi)[:HIT_CAP]
    return hs


line_index = {}
for rec in numbers:
    line_index.setdefault((rec["doc"], rec["line"]), rec)
fraction_pairs, rate_arith, ci_order = [], [], []
seen_lines = set()
for rec in numbers:
    key = (rec["doc"], rec["line"])
    if key in seen_lines:
        continue
    seen_lines.add(key)
    s = rec["_line_text"]
    cited_ids = np.array([pri_file_id[c] for c in rec["cited_files"] if c in pri_file_id], dtype=np.uint32)
    for m in FRAC.finditer(s):
        k, n = fnum(m.group(1)), fnum(m.group(2))
        if n == 0:
            continue
        hk, hn = keys_of(k), keys_of(n)
        kk = np.unique(np.concatenate([PRI.r[hk], PRI.pr[hk]])) if len(hk) else np.array([], np.uint32)
        nn = np.unique(np.concatenate([PRI.r[hn], PRI.pr[hn]])) if len(hn) else np.array([], np.uint32)
        both = np.intersect1d(kk, nn, assume_unique=True)
        in_cited = False
        if len(both) and len(cited_ids):
            ck = np.concatenate([hk[np.isin(PRI.r[hk], both) | np.isin(PRI.pr[hk], both)]])
            in_cited = bool(np.isin(PRI.f[ck], cited_ids).any())
        fraction_pairs.append({"doc": rec["doc"], "line": rec["line"], "text": m.group(0), "k": k, "n": n,
                               "k_found": bool(len(hk)), "n_found": bool(len(hn)),
                               "pair_in_one_record": bool(len(both)), "pair_record_in_cited_file": in_cited,
                               "context": s[max(0, m.start() - 60):m.end() + 40].strip()})
    for m in RATE.finditer(s):
        k, n, r = fnum(m.group(1)), fnum(m.group(2)), m.group(3)
        if n == 0:
            continue
        d = decimals_of(r)
        half = 0.5 * 10.0 ** (-d)
        ok = abs(k / n - float(r)) <= half * (1 + 1e-9) + 1e-12
        rate_arith.append({"doc": rec["doc"], "line": rec["line"], "text": m.group(0), "k_over_n": k / n,
                           "printed": float(r), "consistent": bool(ok)})
    for m in CI.finditer(s):
        try:
            r, lo, hi = fnum(m.group(1)), fnum(m.group(2)), fnum(m.group(3))
        except ValueError:
            continue
        tol = 0.5 * 10.0 ** (-max(decimals_of(m.group(1)), decimals_of(m.group(2)), decimals_of(m.group(3))))
        ok = (lo - tol <= r <= hi + tol) and lo <= hi + tol
        ci_order.append({"doc": rec["doc"], "line": rec["line"], "text": m.group(0), "point": r, "lo": lo, "hi": hi,
                         "consistent": bool(ok)})

# ---------------------------------------------------------------------------------------------- locations
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
    review = (rec["trace_class"] in ("chance_level", "not_found")) and not rec["in_cited_path"]
    rec["for_review"] = bool(review)
    if review:
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
        rec["_sec"] = sch[:4]
        need_sec += [(int(SEC.f[j]), int(SEC.seq[j])) for j in rec["_sec"]]

loc_pri = PRI.locate(need_pri)
loc_sec = SEC.locate(need_sec)


def loc_entry(idx, locs, j, with_status=True):
    fi, sq = int(idx.f[j]), int(idx.seq[j])
    e = {"file": idx.files[fi], "value": float(idx.v[j])}
    if with_status:
        e["commit_status"] = commit_status(e["file"])
    e.update(locs.get((fi, sq)) or {})
    if len(e.get("path", "")) > 220:
        e["path"] = e["path"][:100] + " ... " + e["path"][-110:]
    return e


for rec in numbers:
    rec["where"] = [loc_entry(PRI, loc_pri, j) for j in rec.pop("_where")]
    if "_near" in rec:
        rec["nearest_primary_values"] = [loc_entry(PRI, loc_pri, j) for j in rec.pop("_near")]
        rec["secondary_hits"] = [loc_entry(SEC, loc_sec, j) for j in rec.pop("_sec")]
    rec.pop("half_width")
    rec.pop("_span")
    rec.pop("_line_text")
    rec["n_cited_files"] = len(rec["cited_files"])
    if len(rec["cited_files"]) > 12:
        rec["cited_files"] = rec["cited_files"][:12] + [f"... {len(rec['cited_files']) - 12} more"]


def tally(key, recs):
    out = {}
    for r in recs:
        k = r.get(key)
        k = str(k) if not isinstance(k, str) else k
        out[k] = out.get(k, 0) + 1
    return out


per_doc = {}
for d in DOCS:
    recs = [r for r in numbers if r["doc"] == d["name"]]
    rv = [r for r in recs if r["for_review"]]
    per_doc[d["name"]] = {
        "n_numbers": len(recs), "by_status": tally("status", recs), "by_trace_class": tally("trace_class", recs),
        "in_cited_file": tally("in_cited_file", recs), "in_cited_path": tally("in_cited_path", recs),
        "n_for_review": len(rv), "review_by_secondary_status": tally("secondary_status", rv),
        "review_with_same_text_traced_elsewhere": sum(1 for r in rv if r["same_text_traced_on_lines"]),
        "n_found_not_in_cited_file": sum(1 for r in recs if r["status"].startswith("found") and r["in_cited_file"] is False),
        "fraction_pairs": {"n": sum(1 for f in fraction_pairs if f["doc"] == d["name"]),
                           "pair_in_one_record": sum(1 for f in fraction_pairs if f["doc"] == d["name"] and f["pair_in_one_record"]),
                           "pair_record_in_cited_file": sum(1 for f in fraction_pairs if f["doc"] == d["name"] and f["pair_record_in_cited_file"])},
        "rate_arith": {"n": sum(1 for f in rate_arith if f["doc"] == d["name"]),
                       "inconsistent": sum(1 for f in rate_arith if f["doc"] == d["name"] and not f["consistent"])},
        "ci_order": {"n": sum(1 for f in ci_order if f["doc"] == d["name"]),
                     "inconsistent": sum(1 for f in ci_order if f["doc"] == d["name"] and not f["consistent"])},
    }

review = [r for r in numbers if r["for_review"]]

# input consistency: the generators recorded the sha256 of every input; a changed input means a stale document
input_consistency = []
for gen in ("analysis/out/phase_e/second_pass.json", "analysis/out/phase_e/n6_grid.json"):
    rec = PRI.json.get(gen, {}).get("inputs_sha256", {})
    for f, h in rec.items():
        path = f if f.startswith("analysis") else f"analysis/out/phase_e/{f}{'' if f.endswith('.json') else '.json'}"
        path = path.replace(" (sha256_lf)", "")
        full = os.path.join(ROOT, *path.split("/"))
        if not os.path.exists(full):
            input_consistency.append({"generator": gen, "input": path, "status": "missing"})
            continue
        b = open(full, "rb").read()
        now = hashlib.sha256(b).hexdigest()
        now_lf = hashlib.sha256(b.replace(b"\r\n", b"\n")).hexdigest()
        input_consistency.append({"generator": gen, "input": path,
                                  "status": "same" if h in (now, now_lf) else "CHANGED"})

out = {
    "script": "analysis/probes/phase_e_trace.py",
    "extends": "analysis/probes/phase_d_trace.py (same extraction, matching, chance and co-location rules)",
    "head": git("rev-parse", "HEAD").strip(),
    "docs": docs_meta,
    "primary_set": {"description": "analysis/out/**/*.json on disk, minus audit outputs and phase_e/track_b",
                    "n_files": len(PRI.files), "n_indexed_values": int(len(PRI.v)),
                    "excluded_files": sorted(EXCLUDE_FILES), "excluded_dirs": list(EXCLUDE_DIR_PREFIX),
                    "circular_key_rule": CIRCULAR_KEY.pattern,
                    "values_skipped_as_circular_by_file": PRI.skipped_circular,
                    "files_by_commit_status": tally("s", [{"s": commit_status(f)} for f in PRI.files]),
                    "files": [{"file": f, "commit_status": commit_status(f)} for f in PRI.files]},
    "secondary_set": {"files": [{"file": f, "commit_status": commit_status(f)} for f in SEC.files],
                      "n_indexed_values": int(len(SEC.v))},
    "parameters": {"chance_offsets_in_window_widths": CHANCE_OFFSETS, "coloc_max_E": COLOC_MAX_E,
                   "specific_max_chance_expected": SPECIFIC_MAX_E, "hit_cap_for_colocation": HIT_CAP,
                   "anchor_max_keys": ANCHOR_MAX_K, "n_where": N_WHERE},
    "parameter_log": [
        {"what": "all parameters", "before": "phase_d_trace.py values", "after": "unchanged",
         "reason": "same rule as the Phase D audit; changed only by the additions listed in the docstring"}],
    "summary": {
        "n_numbers": len(numbers),
        "by_status": tally("status", numbers),
        "by_trace_class": tally("trace_class", numbers),
        "in_cited_path": tally("in_cited_path", numbers),
        "per_doc": per_doc,
        "n_ignored_by_reason": tally("reason", ignored),
        "n_for_review": len(review),
        "for_review_rule": "trace_class chance_level or not_found, and not found inside a cited JSON path",
        "fraction_pairs_not_in_one_record": [f for f in fraction_pairs if not f["pair_in_one_record"]],
        "rate_arith_inconsistent": [f for f in rate_arith if not f["consistent"]],
        "ci_order_inconsistent": [f for f in ci_order if not f["consistent"]],
        "unresolved_references": [r for r in ref_log if not r.get("resolved")],
        "generator_inputs_changed_since_generation": [r for r in input_consistency if r["status"] != "same"],
        "generator_inputs_checked": len(input_consistency),
        "found_but_not_in_cited_path": [
            {"id": r["id"], "doc": r["doc"], "line": r["line"], "text": r["text"], "trace_class": r["trace_class"],
             "cited_paths": r["cited_paths"], "where": [f"{w['file'].split('/')[-1]} {w.get('path', '')}" for w in r["where"][:2]],
             "context": r["context"]} for r in numbers if r["in_cited_path"] is False],
    },
    "for_review": [{"id": r["id"], "doc": r["doc"], "line": r["line"], "section": r["section"], "text": r["text"],
                    "status": r["status"], "trace_class": r["trace_class"], "chance_expected": r["chance_expected"],
                    "in_cited_file": r["in_cited_file"], "secondary_status": r["secondary_status"],
                    "same_text_traced_on_lines": r["same_text_traced_on_lines"],
                    "secondary_files": sorted({h["file"] for h in r["secondary_hits"]}),
                    "context": r["context"]} for r in review],
    "fraction_pairs": fraction_pairs,
    "rate_arith": rate_arith,
    "ci_order": ci_order,
    "references": ref_log,
    "numbers": numbers,
    "ignored": ignored,
    "runtime_s": None,
}
out["runtime_s"] = round(time.time() - T0, 1)
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, indent=None, ensure_ascii=False, separators=(",", ":"))
print(f"{len(numbers)} numbers; status {out['summary']['by_status']}; trace_class {out['summary']['by_trace_class']}; "
      f"in_cited_path {out['summary']['in_cited_path']}; for review {len(review)}; "
      f"pairs not co-located {len(out['summary']['fraction_pairs_not_in_one_record'])}; "
      f"rate arith bad {len(out['summary']['rate_arith_inconsistent'])}; CI bad {len(out['summary']['ci_order_inconsistent'])}; "
      f"unresolved refs {len(out['summary']['unresolved_references'])} -> {OUT_REL} ({out['runtime_s']}s)")
