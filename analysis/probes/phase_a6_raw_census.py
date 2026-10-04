"""Phase A6: raw-field census ("any field in the schema we have not used and probably should").

Run from the worktree root (parts can run concurrently; `merge` assembles the final JSON):
  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_a6_raw_census --part tables|transcripts|cc_local|aiv|small|merge|all

Writes RAW COUNTS ONLY:
  analysis/out/phase_a/a6_parts/<part>.json   one file per part (regenerable)
  analysis/out/phase_a/a6_raw_census.json     merged census + flagged-field index + non-tool entry inventory
Interpretation lives in analysis/notes/raw_census.md, never here.

All rules (depth, record definitions, key normalization, field-class rules, thresholds) are fixed in RULES below
before any outcome was looked at, and are copied verbatim into the output JSON.
data/claude-code-local is PRIVATE: for it this script records key names (normalized, see RULES.dynamic_key_rule +
strict mode), enum-valued group labels, value-type counts and counts only. No values, no file names.
"""
import argparse
import collections
import csv
import glob
import gzip
import io
import json
import os
import random
import re
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from analysis.lib import stats
from analysis.lib.ir import COLUMNS
from analysis.lib.sample import _alloc

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("SWARMS_DATA", "C:/Swarms/data"))
OUT_DIR = ROOT / "analysis" / "out" / "phase_a"
PART_DIR = OUT_DIR / "a6_parts"
OUT_JSON = OUT_DIR / "a6_raw_census.json"
LOADER_DIR = ROOT / "analysis" / "loaders"
SEED = stats.SEED
csv.field_size_limit(2 ** 31 - 1)

LIST_CAP = 1000
JSON_STR_MAX = 1_000_000
RESERVOIR = 400
TYPE_MAJ = 0.5
VALUE_EV = 0.5
WIDE_PARENT = 50


RULES = {
    "depth": "number of dict keys on the path from the record root. List levels ('[]') and decoding of a JSON-in-string "
             "('{json}') do not add depth. A key at max depth is recorded with its value type but not descended into.",
    "depth_by_source": {
        "swechat_transcripts": 4, "cc_local_jsonl": 4, "swechat_table_json_columns": 3, "ai_village": "3; 6 for paths "
        "rooted at agent_messages / content / data (the column key + 5 levels below it)",
        "who_and_when / collusion_wiki / urlquery": 8, "cc_local_sidecar_json": 3},
    "list_cap": f"at most the first {LIST_CAP} elements of any list are walked (truncations counted)",
    "json_in_string": f"a string value under a key in the source's json_keys set that starts with '{{' or '[' and is "
                      f"<= {JSON_STR_MAX} chars is decoded and walked as '<key>{{json}}' (codex: arguments/output/input; "
                      "ai_village: arguments; swechat tables: whole JSON-string columns). Never for cc_local.",
    "dynamic_key_rule": "a key is replaced by '<key>' when: len > 64, or it does not match ^[A-Za-z_$@][A-Za-z0-9_\\-$@]*$ "
                        "(file paths, URLs, spaces, dots, leading digits), or it is a UUID, or it is >= 7 hex chars "
                        "containing a digit, or it is a prefixed id (^[A-Za-z]{2,10}[_-][A-Za-z0-9]{8,}$ with a digit). "
                        "strict mode (cc_local only) also replaces keys longer than 40 chars or containing a run of >= 5 digits.",
    "fill_rate": "n_rec / n_records of the group: fraction of records of that group in which the path occurs at least once. "
                 "CI: lib.stats.cluster_rate with the unit named per source (file/session/repo/page) when units are "
                 "tracked, else lib.stats.wilson over records. CIs are computed only for class-flagged paths.",
    "class_rules": {
        "words": "leaf key split on camelCase / snake / kebab boundaries, lowercased",
        "TIMER": "leaf words intersect TIMER_W and the value is numeric (int/float) in >= 50% of non-null occurrences",
        "CLOCK": "value evidence: >= 50% of non-null occurrences are ISO-8601-like strings (^\\d{4}-\\d{2}-\\d{2}), "
                 "HH:MM:SS strings, or numbers in epoch-ms [1e12, 4.1e12) / epoch-s [1e9, 4.1e9); not if TIMER. "
                 "A leaf name in CLOCK_W without value evidence is reported as name_only CLOCK.",
        "TOKEN": "any path word intersects TOKEN_W and numeric majority; not if TIMER",
        "COUNTER": "leaf words intersect COUNTER_W and numeric majority; not if TIMER, TOKEN or CLOCK (ordinals included)",
        "HASH_ID": "(leaf words intersect HASH_W and scalar majority) or >= 50% of non-null occurrences are UUID / "
                   ">=7-char hex with a digit / prefixed-id strings",
        "STATUS": "leaf words intersect STATUS_W and (scalar majority or leaf words include error/errors/exception)",
    },
    "thresholds": {"type_majority": TYPE_MAJ, "value_evidence": VALUE_EV, "wide_parent_children": WIDE_PARENT,
                   "numeric_reservoir": RESERVOIR,
                   "reason": "fixed before any outcome was seen; a simple majority is the least-assumption cut for "
                             "'this field is of this kind'; 50 distinct child keys flags a parent whose keys are probably data"},
    "captured": {
        "cc_jsonl": "path is read by analysis/lib/cc_jsonl.py (Claude Code records only: swechat claude_code, cc_local, "
                    "ai_village claude_code_messages.content); exact path list in meta.cc_captured_paths",
        "ir_column:<col>": "non-CC IR sources: the leaf key is a field the analysis/lib/ir.py COLUMNS docstrings name "
                           "explicitly for that column (meta.ir_semantic_keys)",
        "not_ir_source": "the source is not ingested into the IR at all (tables, sidecars, collusion-wiki, urlquery, "
                         "ai_village tables other than claude_code_messages / computer_use_turns)",
        "loader_leaf / loader_pair": "informational only, not 'captured': the leaf key (pair: leaf and parent key) appears "
                                     "as a quoted string literal in analysis/loaders/*.py at run time (loaders are being "
                                     "built concurrently; generic names like 'input' match trivially)",
    },
    "uncaptured": "class-flagged path whose captured mark is absent (IR source) or not_ir_source",
    "samples": {
        "swechat_transcripts": "all 5,850 files format-detected by content; 300 files drawn with lib.sample._alloc(format "
                               "sizes, 300, floor=30) from a SEED-permuted list within each format",
        "cc_local_jsonl": "300 of the JSONL files, _alloc({main, subagent}, 300, floor=30) from a SEED permutation",
        "swechat_table_json_columns": "500 rows drawn uniformly (SEED) among rows where the column is non-null",
        "ai_village": "first 20,000 rows of each *.jsonl.gz table (row order checked in the output: order_check)",
        "small corpora": "full census",
    },
}

TIMER_W = {"duration", "elapsed", "latency", "ms", "millis", "milliseconds", "seconds", "secs", "sec", "nanos",
           "nanoseconds", "timeout", "took", "ttft", "runtime", "wall", "dur", "interval", "delay", "waited"}
CLOCK_W = {"timestamp", "time", "date", "datetime", "created", "updated", "started", "ended", "completed", "finished",
           "start", "end", "at", "ts", "expires", "modified", "mtime", "deadline", "until"}
TOKEN_W = {"token", "tokens", "usage", "cost", "usd", "cache", "cached", "credits", "price", "billing"}
COUNTER_W = {"count", "counts", "num", "number", "total", "lines", "line", "bytes", "size", "length", "len", "n",
             "turns", "calls", "additions", "deletions", "files", "changes", "version", "index", "idx", "seq", "step",
             "steps", "attempts", "retries", "depth", "chars", "characters", "words", "items", "results", "matches",
             "entries", "pages", "hits", "children", "rows", "insertions", "removed", "added", "contributors",
             "commits", "checkpoints", "sessions", "prompts", "tools", "agents", "tasks", "phases", "percentage"}
HASH_W = {"id", "ids", "uuid", "uuids", "hash", "sha", "sha1", "sha256", "digest", "checksum", "fingerprint", "etag",
          "pk", "pks", "shas"}
STATUS_W = {"status", "exit", "code", "error", "errors", "err", "interrupted", "success", "successful", "stop", "reason",
            "finish", "truncated", "timed", "killed", "signal", "state", "outcome", "failed", "failure", "denied",
            "denials", "ok", "level", "cancelled", "canceled", "aborted", "rejected", "exception", "warning", "warnings",
            "correct", "corrected"}
RULES["changes_after_test_run"] = [
    "JSON-string column probe: was the first 300 non-null values of the table (biased to the first row groups); now up to "
    "3 non-null values from every k-th row group, k = max(1, row_groups // 100), capped at 300. Reason: early-row bias. "
    "Same >= 50% parse rule.",
    "conversations JSON-string columns other than tool_input_json are grouped by turn_type (tool_input_json by tool_name). "
    "Reason: one table column holds several row types. No word set, threshold or depth was changed."]
RULES["changes_after_test_run"] += [
    "cc_local privacy: added CC_PRIVATE_OPAQUE prefixes / segments and non-builtin tool hiding after the first cc_local "
    "run showed user-defined schema keys (structured outputs, workflow results, MCP structured content) in key names.",
    "ai_village claude_code_messages unit: sdk_session_id -> derived run (see aiv_claude_code_messages_unit) after the "
    "first run showed 9 sdk_session_id values in the 20,000-row head, one holding almost all rows.",
    "identities part added after the census (pre-specified formulas in RULES.identities, run once)."]
RULES["class_rules"]["word_sets"] = {"TIMER_W": sorted(TIMER_W), "CLOCK_W": sorted(CLOCK_W), "TOKEN_W": sorted(TOKEN_W),
                                     "COUNTER_W": sorted(COUNTER_W), "HASH_W": sorted(HASH_W), "STATUS_W": sorted(STATUS_W)}

UUID_RX = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
HEX_RX = re.compile(r"^[0-9a-fA-F]+$")
ISO_RX = re.compile(r"^\d{4}-\d{2}-\d{2}")
HMS_RX = re.compile(r"^\d{2}:\d{2}:\d{2}")
PREFIXED_ID_RX = re.compile(r"^[A-Za-z]{2,10}[_-][A-Za-z0-9]{8,}$")
NUMSTR_RX = re.compile(r"^-?\d+(\.\d+)?$")
KEY_OK = re.compile(r"^[A-Za-z_$@][A-Za-z0-9_\-$@]*$")
DIGIT_RUN = re.compile(r"\d{5,}")
_TYPES = {str: "str", int: "int", float: "float", bool: "bool", type(None): "null", dict: "dict", list: "list"}


def _has_digit(s):
    return any(c.isdigit() for c in s)


def norm_key(k, strict=False):
    k = k if isinstance(k, str) else str(k)
    if len(k) > 64 or not KEY_OK.match(k) or UUID_RX.match(k):
        return "<key>"
    if len(k) >= 7 and HEX_RX.match(k) and _has_digit(k):
        return "<key>"
    if PREFIXED_ID_RX.match(k) and _has_digit(k):
        return "<key>"
    if strict and (len(k) > 40 or DIGIT_RUN.search(k)):
        return "<key>"
    return k


def shape_of(v, tv):
    if tv is str:
        if not v:
            return "empty"
        c0 = v[0]
        if c0.isdigit():
            if NUMSTR_RX.match(v):
                return "numstr"
            if ISO_RX.match(v):
                return "iso"
            if HMS_RX.match(v):
                return "hms"
        if len(v) == 36 and UUID_RX.match(v):
            return "uuid"
        if 7 <= len(v) <= 128 and HEX_RX.match(v) and _has_digit(v):
            return "hex"
        if 10 <= len(v) <= 80 and PREFIXED_ID_RX.match(v) and _has_digit(v):
            return "prefixed_id"
        if c0 in "{[":
            return "jsonish"
        return None
    if v != v:
        return "nan"
    if 1e12 <= v < 4.1e12:
        return "epoch_ms"
    if 1e9 <= v < 4.1e9:
        return "epoch_s"
    if v < 0:
        return "neg"
    if v == 0:
        return "zero"
    return None


class Census:
    """Key-path census over records grouped by a label. One instance per source."""

    def __init__(self, maxdepth=4, depth_fn=None, json_keys=frozenset(), strict=False, keep_values=True,
                 track_units=True, opaque=(), opaque_segments=()):
        self.maxdepth, self.depth_fn, self.json_keys = maxdepth, depth_fn, frozenset(json_keys)
        self.opaque, self._opaque_cache, self._all_opaque = tuple(opaque), {}, False
        self.opaque_segments = frozenset(opaque_segments)
        self.strict, self.keep_values, self.track_units = strict, keep_values, track_units
        self.groups = {}
        self.rng = random.Random(SEED)
        self.list_truncations = 0
        self.json_decoded = 0

    def add(self, group, obj, unit=None, opaque_all=False):
        self._all_opaque = opaque_all
        G = self.groups.get(group)
        if G is None:
            G = self.groups[group] = {"n": 0, "units": collections.Counter(), "paths": {}}
        G["n"] += 1
        if self.track_units:
            G["units"][unit] += 1
        seen = set()
        self._touch(G, "$", obj, unit, seen)
        t = type(obj)
        if t is dict or t is list:
            self._walk(G, obj, "", 0, unit, seen)

    def _is_opaque(self, path):
        r = self._opaque_cache.get(path)
        if r is None:
            r = any(_under(path, pre) for pre in self.opaque) or bool(self.opaque_segments and {
                sg.replace("[]", "").replace("{json}", "") for sg in path.split(".")} & self.opaque_segments)
            self._opaque_cache[path] = r
        return r

    def _maxd(self, p):
        return self.depth_fn(p) if self.depth_fn else self.maxdepth

    def _walk(self, G, o, path, depth, unit, seen):
        if type(o) is dict:
            hide = self._all_opaque or ((self.opaque or self.opaque_segments) and self._is_opaque(path))
            for k, v in o.items():
                nk = "<key>" if hide else norm_key(k, self.strict)
                p = path + "." + nk if path else nk
                self._touch(G, p, v, unit, seen)
                d = depth + 1
                if d < self._maxd(p):
                    tv = type(v)
                    if tv is dict or tv is list:
                        self._walk(G, v, p, d, unit, seen)
                    elif tv is str and nk in self.json_keys and v[:1] in ("{", "[") and len(v) <= JSON_STR_MAX:
                        try:
                            pv = json.loads(v)
                        except ValueError:
                            pv = None
                        if type(pv) is dict or type(pv) is list:
                            self.json_decoded += 1
                            pj = p + "{json}"
                            self._touch(G, pj, pv, unit, seen)
                            self._walk(G, pv, pj, d, unit, seen)
        else:  # list
            p = path + "[]"
            for i, x in enumerate(o):
                if i >= LIST_CAP:
                    self.list_truncations += 1
                    break
                self._touch(G, p, x, unit, seen)
                tx = type(x)
                if tx is dict or tx is list:
                    self._walk(G, x, p, depth, unit, seen)

    def _touch(self, G, p, v, unit, seen):
        P = G["paths"].get(p)
        if P is None:
            P = G["paths"][p] = {"r": 0, "o": 0, "u": collections.Counter(), "t": collections.Counter(),
                                 "s": collections.Counter(), "min": None, "max": None, "res": [], "nv": 0}
        P["o"] += 1
        tv = type(v)
        P["t"][_TYPES.get(tv, tv.__name__)] += 1
        if tv is str or tv is int or tv is float:
            sh = shape_of(v, tv)
            if sh:
                P["s"][sh] += 1
            if tv is not str and self.keep_values and v == v:
                if P["min"] is None or v < P["min"]:
                    P["min"] = v
                if P["max"] is None or v > P["max"]:
                    P["max"] = v
                P["nv"] += 1
                if len(P["res"]) < RESERVOIR:
                    P["res"].append(v)
                else:
                    j = self.rng.randrange(P["nv"])
                    if j < RESERVOIR:
                        P["res"][j] = v
        if p not in seen:
            seen.add(p)
            P["r"] += 1
            if self.track_units:
                P["u"][unit] += 1

    def export(self, captured_fn=None, unit_name="file"):
        out = {}
        for g in sorted(self.groups):
            G = self.groups[g]
            units = G["units"]
            fids = list(units.keys()) if self.track_units else []
            den = [units[f] for f in fids]
            gout = {"n_records": G["n"], "unit": unit_name if self.track_units else "record",
                    "n_units": len(units) if self.track_units else None, "paths": {}}
            kids = collections.defaultdict(set)
            for p, P in G["paths"].items():
                par, _, leaf = p.rpartition(".")
                kids[par].add(leaf.split("[")[0].split("{")[0])
                e = {"n_rec": P["r"], "n_occ": P["o"], "types": dict(P["t"])}
                if P["s"]:
                    e["shapes"] = dict(P["s"])
                if self.track_units:
                    e["n_units"] = len(P["u"])
                if P["min"] is not None:
                    e["num_min"], e["num_max"] = P["min"], P["max"]
                    e["num_p50_reservoir"] = float(np.median(P["res"]))
                    e["num_n"] = P["nv"]
                cls = classify(p, P["t"], P["s"])
                if cls["classes"]:
                    e["classes"] = cls["classes"]
                if cls["name_only"]:
                    e["name_only"] = cls["name_only"]
                cap = captured_fn(g, p) if captured_fn else None
                if cap:
                    e["captured"] = cap
                if cls["classes"] and p != "$":
                    if self.track_units and len(fids) > 0:
                        cr = stats.cluster_rate([P["u"].get(f, 0) for f in fids], den)
                        e["fill"] = {"rate": cr["rate"], "lo": cr["lo"], "hi": cr["hi"], "num": cr["num"], "den": cr["den"],
                                     "n_units": cr["n_sessions"], "ci": "cluster_rate/" + unit_name}
                        w = stats.wilson(len(P["u"]), len(fids))
                        e["unit_presence"] = {"k": len(P["u"]), "n": len(fids), "p": w[0], "lo": w[1], "hi": w[2]}
                    else:
                        w = stats.wilson(P["r"], G["n"])
                        e["fill"] = {"rate": w[0], "lo": w[1], "hi": w[2], "num": P["r"], "den": G["n"], "ci": "wilson/record"}
                gout["paths"][p] = e
            wide = {par: len(ch) for par, ch in kids.items() if len(ch) > WIDE_PARENT}
            if wide:
                gout["wide_parents"] = wide
            out[g] = gout
        return {"groups": out, "list_truncations": self.list_truncations, "json_strings_decoded": self.json_decoded}


def words_of(key):
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", key)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    return [w for w in re.split(r"[^A-Za-z0-9]+", s.lower()) if w]


def leaf_of(p):
    seg = p.rsplit(".", 1)[-1]
    seg = seg.replace("{json}", "").replace("[]", "")
    return "" if seg in ("$", "<key>") else seg


def classify(p, types, shapes):
    leaf = leaf_of(p)
    w = set(words_of(leaf))
    pw = set()
    for seg in p.split("."):
        pw.update(words_of(seg.replace("{json}", "").replace("[]", "")))
    nonnull = sum(types.values()) - types.get("null", 0)
    res = {"classes": [], "name_only": []}
    if nonnull <= 0:
        if w & CLOCK_W:
            res["name_only"].append("CLOCK")
        return res
    num = types.get("int", 0) + types.get("float", 0)
    scal = num + types.get("str", 0) + types.get("bool", 0)
    numeric = num / nonnull >= TYPE_MAJ
    scalar = scal / nonnull >= TYPE_MAJ
    clock_ev = (shapes.get("iso", 0) + shapes.get("hms", 0) + shapes.get("epoch_ms", 0) + shapes.get("epoch_s", 0)) / nonnull >= VALUE_EV
    id_ev = (shapes.get("uuid", 0) + shapes.get("hex", 0) + shapes.get("prefixed_id", 0)) / nonnull >= VALUE_EV
    timer = bool(w & TIMER_W) and numeric
    token = bool(pw & TOKEN_W) and numeric and not timer
    clock = clock_ev and not timer
    counter = bool(w & COUNTER_W) and numeric and not (timer or token or clock)
    hashid = (bool(w & HASH_W) and scalar) or id_ev
    status = bool(w & STATUS_W) and (scalar or bool(w & {"error", "errors", "exception"}))
    for name, on in (("TIMER", timer), ("CLOCK", clock), ("TOKEN", token), ("COUNTER", counter), ("HASH_ID", hashid),
                     ("STATUS", status)):
        if on:
            res["classes"].append(name)
    if (w & CLOCK_W) and not clock and not timer:
        res["name_only"].append("CLOCK")
    return res


# ------------------------------------------------------------------------------------------------- captured-by-IR marks

TUR_KEYS = ("durationMs", "durationSeconds", "timedOutAfterMs", "interrupted", "returnCodeInterpretation",
            "persistedOutputSize", "totalDurationMs", "totalTokens", "totalToolUseCount", "bytes", "code",
            "numFiles", "truncated", "backgroundTaskId", "noOutputExpected", "stderr", "usage")
PROGRESS_KEYS = ("type", "elapsedTimeSeconds", "elapsedTimeMs", "totalBytes", "totalLines", "timeoutMs", "status",
                 "serverName", "toolName", "hookEvent", "hookName", "taskId", "agentId", "message")
CC_EXACT = {"$", "type", "timestamp", "uuid", "parentUuid", "requestId", "isSidechain", "agentId", "isMeta", "isSynthetic",
            "parentToolUseID", "message", "message.id", "message.model", "message.content", "message.content[]",
            "message.content[].type", "message.content[].text", "message.content[].thinking", "message.content[].id",
            "message.content[].name", "message.content[].input", "message.content[].tool_use_id",
            "message.content[].content", "message.content[].content[]", "message.content[].content[].type",
            "message.content[].content[].text", "message.content[].is_error", "message.usage",
            "message.usage.input_tokens", "message.usage.output_tokens", "message.usage.cache_read_input_tokens",
            "message.usage.cache_creation_input_tokens", "toolUseResult", "tool_use_result",
            # system entries
            "subtype", "level", "durationMs", "compactMetadata", "compact_metadata", "status", "content",
            # Agent SDK result rows
            "is_error", "num_turns", "duration_ms", "duration_api_ms", "total_cost_usd", "stop_reason", "data"}
CC_EXACT |= {f"{r}.{k}" for r in ("toolUseResult", "tool_use_result") for k in TUR_KEYS}
CC_EXACT |= {f"data.{k}" for k in PROGRESS_KEYS}
CC_PREFIX = ("message.content[].input", "toolUseResult.usage", "tool_use_result.usage", "compactMetadata",
             "compact_metadata", "data.message")
TUR_EXACT = {"$"} | set(TUR_KEYS)

IR_SEMANTIC = {"timestamp": "ts", "call_id": "call_id", "callID": "call_id", "tool_use_id": "call_id",
               "tool_call_id": "call_id", "is_error": "native_error", "exit_code": "exit_code", "exitCode": "exit_code",
               "stderr": "stderr", "input_tokens": "usage_in", "output_tokens": "usage_out",
               "cache_read_input_tokens": "usage_cache_read", "cache_creation_input_tokens": "usage_cache_create",
               "model": "model", "requestId": "request_id", "responseId": "api_msg_id", "uuid": "uuid",
               "parentUuid": "parent_uuid", "command": "command"}
IR_SEMANTIC_SUFFIX = {"time.created": "ts", "time.start": "ts", "state.status": "native_error"}
AIV_CU_SEMANTIC = {"created_at": "ts", "error": "stderr", "output": "text", "session_id": "session_id"}


def _under(p, pre):
    return p == pre or p.startswith(pre + ".") or p.startswith(pre + "[") or p.startswith(pre + "{")


def cc_captured(p):
    if p in CC_EXACT:
        return "cc_jsonl"
    for pre in CC_PREFIX:
        if _under(p, pre):
            return "cc_jsonl"
    return None


def tur_captured(p):
    if p in TUR_EXACT or _under(p, "usage"):
        return "cc_jsonl"
    return None


def semantic_captured(p):
    leaf = leaf_of(p)
    if leaf in IR_SEMANTIC:
        return "ir_column:" + IR_SEMANTIC[leaf]
    for suf, col in IR_SEMANTIC_SUFFIX.items():
        if p.endswith(suf):
            return "ir_column:" + col
    return None


_LOADER_LITS = None


def loader_literals():
    """{file_name: set(string literals)} over analysis/loaders/*.py at run time."""
    global _LOADER_LITS
    if _LOADER_LITS is None:
        _LOADER_LITS = {}
        for f in sorted(LOADER_DIR.glob("*.py")):
            try:
                src = f.read_text(encoding="utf-8")
            except OSError:
                continue
            _LOADER_LITS[f.name] = set(re.findall(r"[\"']([A-Za-z_][A-Za-z0-9_\-]*)[\"']", src))
    return _LOADER_LITS


def loader_mark(p):
    leaf = leaf_of(p)
    segs = [leaf_of(s) for s in p.split(".")]
    parent = segs[-2] if len(segs) >= 2 else ""
    hit_leaf, hit_pair = [], []
    for fname, lits in loader_literals().items():
        if leaf and leaf in lits:
            hit_leaf.append(fname)
            if parent and parent in lits:
                hit_pair.append(fname)
    if hit_pair:
        return "loader_pair"
    if hit_leaf:
        return "loader_leaf"
    return None


# ------------------------------------------------------------------------------------------------------ format detection

CODEX_TYPES = {"session_meta", "turn_context", "response_item", "event_msg", "compacted"}
CC_TYPES = {"queue-operation", "file-history-snapshot", "summary", "progress", "system", "user", "assistant",
            "attachment", "last-prompt", "permission-mode", "custom-title", "agent-name", "ai-title", "pr-link",
            "tool_use", "tool_result", "result"}
RULES["format_detection"] = (
    "single JSON document (first non-blank line is '{' alone, or the file is one line that parses to an object with a "
    "'messages' list): opencode if it has an 'info' object and messages carry 'info'/'parts'; gemini if it has "
    "sessionId/projectHash or its messages carry 'type'. Otherwise JSONL: each of the first 50 parseable lines votes: "
    "codex = has 'payload' and type in CODEX_TYPES; copilot = type contains '.' and has 'data'; cursor = has role+message, "
    "no type; simple_text = type user/assistant with a string message; claude_code = has parentUuid/sessionId or type in "
    "CC_TYPES; else unknown. File format = plurality vote (ties -> first in that order).")


def _salvage(line):
    dec = json.JSONDecoder(strict=False)
    objs, pos, n = [], 0, len(line)
    try:
        while pos < n:
            obj, pos = dec.raw_decode(line, pos)
            objs.append(obj)
            while pos < n and line[pos] in " \t\r":
                pos += 1
    except ValueError:
        return None
    return objs or None


def iter_lines(path, stat):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            stat["lines"] += 1
            try:
                yield json.loads(line)
                continue
            except ValueError:
                pass
            objs = _salvage(line)
            if objs is None:
                stat["bad_lines"] += 1
                continue
            stat["salvaged_lines"] += 1
            yield from objs


def line_vote(o):
    if not isinstance(o, dict):
        return "unknown"
    t = o.get("type")
    if "payload" in o and t in CODEX_TYPES:
        return "codex"
    if isinstance(t, str) and "." in t and "data" in o:
        return "copilot"
    if "role" in o and "message" in o and "type" not in o:
        return "cursor"
    if t in ("user", "assistant") and isinstance(o.get("message"), str):
        return "simple_text"
    if "parentUuid" in o or "sessionId" in o or (isinstance(t, str) and t in CC_TYPES):
        return "claude_code"
    return "unknown"


def doc_format(d):
    if not isinstance(d, dict) or not isinstance(d.get("messages"), list):
        return "unknown_doc"
    msgs = d["messages"]
    m0 = next((m for m in msgs if isinstance(m, dict)), None)
    if isinstance(d.get("info"), dict) or (m0 is not None and "parts" in m0 and "info" in m0):
        return "opencode"
    if "sessionId" in d or "projectHash" in d or (m0 is not None and "type" in m0):
        return "gemini"
    return "unknown_doc"


ORDER = ["claude_code", "codex", "opencode", "gemini", "cursor", "copilot", "simple_text", "unknown", "unknown_doc", "empty",
         "doc_parse_failed"]


def detect(path):
    """Returns (format, parsed_doc_or_None)."""
    with open(path, "rb") as f:
        head = f.read(65536)
    st = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    if not st:
        return "empty", None
    first = st.split(b"\n", 1)[0].strip()
    single_line = b"\n" not in st.rstrip()
    if first in (b"{", b"[") or (single_line and re.match(rb'\{\s*"(messages|info|sessionId|projectHash)"', st)):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                d = json.load(f)
        except ValueError:
            return "doc_parse_failed", None
        return doc_format(d), d
    votes = collections.Counter()
    stat = collections.Counter()
    for i, o in enumerate(iter_lines(path, stat)):
        votes[line_vote(o)] += 1
        if i >= 49:
            break
    if not votes:
        return "unknown", None
    best = max(votes.values())
    for f_ in ORDER:
        if votes.get(f_) == best:
            return f_, None
    return "unknown", None


# --------------------------------------------------------------------------------------------- record grouping per format

def cc_group(e):
    if not isinstance(e, dict):
        return "<non-object>"
    t = e.get("type")
    if t == "system":
        return f"system/{e.get('subtype')}"
    if t == "progress":
        d = e.get("data")
        return f"progress/{d.get('type') if isinstance(d, dict) else None}"
    if t == "attachment":
        a = e.get("attachment")
        return f"attachment/{a.get('type') if isinstance(a, dict) else None}"
    if t == "queue-operation":
        return f"queue-operation/{e.get('operation')}"
    if t == "result":
        return f"result/{e.get('subtype')}"
    if t == "user":
        m = e.get("message")
        c = m.get("content") if isinstance(m, dict) else None
        if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
            return "user/tool_result"
        return "user/text"
    return str(t)


def codex_group(e):
    if not isinstance(e, dict):
        return "<non-object>"
    t = e.get("type")
    p = e.get("payload")
    if isinstance(p, dict) and isinstance(p.get("type"), str):
        return f"{t}/{p['type']}"
    return str(t)


def generic_group(e, fmt):
    if not isinstance(e, dict):
        return "<non-object>"
    if fmt == "cursor":
        return f"line/{e.get('role')}"
    return f"line/{e.get('type')}"


TOOL_KIND = {
    "claude_code": (("user/tool_result",), ("assistant", "user/text")),
    "codex": (("response_item/function_call", "response_item/function_call_output", "response_item/custom_tool_call",
               "response_item/custom_tool_call_output", "response_item/local_shell_call", "response_item/web_search_call",
               "response_item/tool_search_call", "response_item/tool_search_output",
               "event_msg/exec_command_begin", "event_msg/exec_command_end", "event_msg/mcp_tool_call_begin",
               "event_msg/mcp_tool_call_end", "event_msg/patch_apply_begin", "event_msg/patch_apply_end",
               "event_msg/web_search_begin", "event_msg/web_search_end", "event_msg/exec_command_output_delta",
               "event_msg/terminal_interaction", "event_msg/view_image_tool_call", "event_msg/collab_agent_spawn_end",
               "event_msg/collab_agent_spawn_begin"),
              ("response_item/message", "response_item/reasoning", "event_msg/agent_message", "event_msg/user_message",
               "event_msg/agent_reasoning", "event_msg/agent_reasoning_raw_content")),
}


def group_kind(fmt, g):
    base = g[len("nested:"):] if g.startswith("nested:") else g
    if fmt in TOOL_KIND:
        tool, msg = TOOL_KIND[fmt]
        if base in tool:
            return "tool"
        if base in msg:
            return "message"
        return "other"
    if fmt == "opencode":
        if base.startswith("part/tool"):
            return "tool"
        if base in ("part/text", "part/reasoning") or base.startswith("message_info/"):
            return "message"
        return "other"
    if fmt == "gemini":
        if base.startswith("toolCall/"):
            return "tool"
        if base.startswith("message/"):
            return "message"
        return "other"
    if fmt in ("cursor", "simple_text"):
        return "message"
    if fmt == "copilot":
        return "tool" if base.startswith("line/tool.") else ("message" if ".message" in base else "other")
    return "other"


def doc_records(fmt, d):
    """Yield (group, record) for single-document formats."""
    if fmt == "opencode":
        yield "session", {k: v for k, v in d.items() if k != "messages"}
        for m in d.get("messages") or []:
            if not isinstance(m, dict):
                continue
            info = m.get("info") if isinstance(m.get("info"), dict) else {}
            yield f"message_info/{info.get('role')}", {k: v for k, v in m.items() if k != "parts"}
            for p in m.get("parts") or []:
                if not isinstance(p, dict):
                    continue
                pt = p.get("type")
                yield (f"part/tool/{p.get('tool')}" if pt == "tool" else f"part/{pt}"), p
    elif fmt == "gemini":
        yield "session", {k: v for k, v in d.items() if k != "messages"}
        for m in d.get("messages") or []:
            if not isinstance(m, dict):
                continue
            yield f"message/{m.get('type')}", m
            for tc in m.get("toolCalls") or []:
                if isinstance(tc, dict):
                    yield f"toolCall/{tc.get('name')}", tc


def tool_name_clean(name, private):
    if name is None:
        return "unresolved"
    name = str(name)
    if private and name.startswith("mcp__"):
        return "mcp__*"
    return name if KEY_OK.match(name) and len(name) <= 64 else "<tool>"


CC_BUILTIN_TOOLS = {"Agent", "Task", "Artifact", "ArtifactComments", "ArtifactData", "AskUserQuestion", "Bash",
                    "BashOutput", "KillShell", "Edit", "MultiEdit", "NotebookEdit", "Glob", "Grep", "Monitor", "Read",
                    "Write", "SendUserFile", "Skill", "TaskOutput", "TaskStop", "TaskCreate", "TaskUpdate", "TaskList",
                    "TaskGet", "ToolSearch", "WebFetch", "WebSearch", "Workflow", "TodoWrite", "ExitPlanMode",
                    "EnterPlanMode", "SendMessage", "ListAgents", "LS", "NotebookRead"}
CC_PRIVATE_OPAQUE = ("attachment.data", "result", "args", "toolUseResult.result", "toolUseResult.data",
                     "toolUseResult.structured_output", "message.content[].input.args")
CC_PRIVATE_OPAQUE_SEGMENTS = ("wireToolInputs", "mcpMeta", "structuredContent", "toolInputCopies", "structured_output",
                              "input_schema", "properties", "parameters")
RULES["private_cc_local"] = (
    "cc_local only: keys below these record-relative prefixes are all replaced by '<key>' (user-defined schemas): "
    + ", ".join(CC_PRIVATE_OPAQUE) + "; and below any key named " + ", ".join(CC_PRIVATE_OPAQUE_SEGMENTS)
    + " wherever it occurs. Inputs of tool_use blocks and toolUseResult values of tools outside "
    "CC_BUILTIN_TOOLS (MCP, StructuredOutput, ...) are replaced by {'<key>': null} before the walk; their per-tool "
    "toolUseResult records are walked with every key hidden. Sidecar workflow JSON: result/args/logs/phases/"
    "workflowProgress hidden the same way. MCP tool names are folded to 'mcp__*'.")


def _privatize(e, call_tool):
    """Shallow copy of a CC entry with non-builtin tool inputs / results hidden (cc_local only)."""
    if not isinstance(e, dict):
        return e
    e2 = dict(e)
    msg = e.get("message")
    if isinstance(msg, dict) and isinstance(msg.get("content"), list):
        blocks = []
        for b in msg["content"]:
            if isinstance(b, dict) and b.get("type") in ("tool_use", "server_tool_use") and b.get("name") not in CC_BUILTIN_TOOLS:
                b = dict(b)
                b["input"] = {"<key>": None}
            blocks.append(b)
        e2["message"] = dict(msg, content=blocks)
    for tk in ("toolUseResult", "tool_use_result"):
        if tk in e and isinstance(msg, dict) and isinstance(msg.get("content"), list):
            cid = next((b.get("tool_use_id") for b in msg["content"] if isinstance(b, dict) and b.get("type") == "tool_result"), None)
            if call_tool.get(cid) not in CC_BUILTIN_TOOLS:
                e2[tk] = {"<key>": None}
    return e2


def cc_records(entries, private=False):
    """Yield (group, record, kind) for a stream of Claude Code entries. kind in entry|nested|tur|tur_opaque.
    toolUseResult is additionally yielded as its own record grouped per tool name."""
    call_tool = {}

    def one(e, nested):
        if private and isinstance(e, dict):
            m = e.get("message")
            if e.get("type") == "assistant" and isinstance(m, dict) and isinstance(m.get("content"), list):
                for b in m["content"]:
                    if isinstance(b, dict) and b.get("type") in ("tool_use", "server_tool_use"):
                        call_tool[b.get("id")] = b.get("name")
            raw, e = e, _privatize(e, call_tool)
        else:
            raw = e
        g = cc_group(e)
        yield ("nested:" + g if nested else g), e, ("nested" if nested else "entry")
        if not isinstance(e, dict):
            return
        msg = e.get("message") if isinstance(e.get("message"), dict) else {}
        content = msg.get("content")
        if e.get("type") == "assistant" and isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") in ("tool_use", "server_tool_use"):
                    call_tool[b.get("id")] = b.get("name")
        tur_key = "toolUseResult" if "toolUseResult" in e else ("tool_use_result" if "tool_use_result" in e else None)
        if tur_key is not None:
            cid = None
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        cid = b.get("tool_use_id")
                        break
            tn = tool_name_clean(call_tool.get(cid), private)
            opaque = private and call_tool.get(cid) not in CC_BUILTIN_TOOLS
            yield ("nested:" if nested else "") + f"toolUseResult/{tn}", (raw[tur_key] if not opaque else raw[tur_key]),                 ("tur_opaque" if opaque else "tur")
        if e.get("type") == "progress":
            d = e.get("data")
            if isinstance(d, dict) and d.get("type") == "agent_progress" and isinstance(d.get("message"), dict):
                yield from one(d["message"], True)

    for e in entries:
        yield from one(e, False)


def cc_captured_fn(g, p):
    base = g[len("nested:"):] if g.startswith("nested:") else g
    if base.startswith("toolUseResult/"):
        return tur_captured(p)
    return cc_captured(p)


# ------------------------------------------------------------------------------------------------ part: swechat transcripts

TRANS = DATA / "swe-chat-pinned" / "transcripts"


def _inv_worker(path):
    """Full-population entry-type inventory for one transcript file."""
    fmt, doc = detect(path)
    groups = collections.Counter()
    stat = collections.Counter()
    if doc is not None:
        for g, _ in doc_records(fmt, doc):
            groups[g] += 1
    elif fmt in ("claude_code", "codex", "cursor", "copilot", "simple_text", "unknown"):
        it = iter_lines(path, stat)
        if fmt == "claude_code":
            for g, _, kind in cc_records(it):
                if not kind.startswith("tur"):
                    groups[g] += 1
        elif fmt == "codex":
            for e in it:
                groups[codex_group(e)] += 1
        else:
            for e in it:
                groups[generic_group(e, fmt)] += 1
    return os.path.basename(path), fmt, dict(groups), dict(stat)


def census_transcript(path, fmt, doc, census, unit, stat):
    if doc is not None:
        for g, rec in doc_records(fmt, doc):
            census[fmt].add(g, rec, unit)
        return
    it = iter_lines(path, stat)
    if fmt == "claude_code":
        for g, rec, _ in cc_records(it):
            census[fmt].add(g, rec, unit)
    elif fmt == "codex":
        for e in it:
            census[fmt].add(codex_group(e), e, unit)
    else:
        for e in it:
            census[fmt].add(generic_group(e, fmt), e, unit)


def part_transcripts(args):
    t0 = time.time()
    files = sorted(glob.glob(str(TRANS / "*.jsonl")))
    if args.limit:
        files = files[: args.limit]
    inv = []
    with Pool(args.workers) as pool:
        for r in pool.imap_unordered(_inv_worker, files, chunksize=4):
            inv.append(r)
    inv.sort()
    fmt_of = {name: fmt for name, fmt, _, _ in inv}
    # cross-tab with the dataset's own agent label (label is never used for detection)
    import pyarrow.parquet as pq
    sess = pq.read_table(DATA / "swe-chat-pinned" / "sessions.parquet", columns=["session_id", "agent"]).to_pylist()
    agent_of = {r["session_id"]: r["agent"] for r in sess}
    xtab = collections.Counter()
    for name, fmt in fmt_of.items():
        xtab[(fmt, str(agent_of.get(name[:-6], "<no sessions row>")))] += 1
    # full-population inventory
    fmt_files = collections.Counter(fmt_of.values())
    inv_out = {}
    for fmt in fmt_files:
        recs, nfiles = collections.Counter(), collections.Counter()
        bad = collections.Counter()
        for name, f_, groups, st in inv:
            if f_ != fmt:
                continue
            for g, c in groups.items():
                recs[g] += c
                nfiles[g] += 1
            bad.update(st)
        n = fmt_files[fmt]
        inv_out[fmt] = {"n_files": n, "line_stats": dict(bad), "groups": {
            g: {"records": recs[g], "files_with": nfiles[g], "files_with_wilson": list(stats.wilson(nfiles[g], n)),
                "kind": group_kind(fmt, g)} for g in sorted(recs)}}
    # stratified sample of 300 files
    by_fmt = collections.defaultdict(list)
    for name in sorted(fmt_of):
        by_fmt[fmt_of[name]].append(name)
    eligible = {f: v for f, v in by_fmt.items() if f not in ("empty", "doc_parse_failed")}
    alloc = _alloc({f: len(v) for f, v in eligible.items()}, min(300, sum(len(v) for v in eligible.values())), floor=30)
    rng = np.random.default_rng(SEED)
    sample = {}
    for f in sorted(alloc):
        names = eligible[f]
        perm = [names[i] for i in rng.permutation(len(names))]
        sample[f] = sorted(perm[: alloc[f]])
    census = {f: Census(maxdepth=4, json_keys={"arguments", "output", "input"} if f == "codex" else set(),
                        keep_values=True, track_units=True) for f in sample}
    stat = collections.Counter()
    for f in sorted(sample):
        for i, name in enumerate(sample[f]):
            path = str(TRANS / name)
            fmt, doc = detect(path)
            assert fmt == f, (name, fmt, f)
            census_transcript(path, fmt, doc, census, i, stat)
            doc = None

    def cap_for(fmt):
        if fmt == "claude_code":
            return cc_captured_fn
        return lambda g, p: semantic_captured(p)

    out = {"part": "transcripts", "source": "data/swe-chat-pinned/transcripts", "ir_source": True,
           "n_files": len(files), "format_counts": dict(fmt_files),
           "format_by_agent_label": [{"format": a, "agent": b, "files": c} for (a, b), c in sorted(xtab.items())],
           "inventory_full_population": inv_out,
           "sample": {"alloc": alloc, "n_files": sum(len(v) for v in sample.values()), "line_stats": dict(stat),
                      "files": sample},
           "census": {f: census[f].export(cap_for(f), "file") for f in sorted(census)},
           "elapsed_s": round(time.time() - t0, 1)}
    return out


# ------------------------------------------------------------------------------------------------------- part: cc_local

CCL = DATA / "claude-code-local"


def _ccl_inv_worker(path):
    stat = collections.Counter()
    groups = collections.Counter()
    for g, _, kind in cc_records(iter_lines(path, stat), private=True):
        if not kind.startswith("tur"):
            groups[g] += 1
    return dict(groups), dict(stat)


def ccl_strata():
    files = sorted(str(p) for p in CCL.rglob("*.jsonl"))
    strata = {"main": [], "subagent": []}
    for f in files:
        rel = os.path.relpath(f, CCL).replace(os.sep, "/")
        strata["subagent" if "/subagents/" in rel else "main"].append(f)
    return strata


def ccl_sample(strata):
    alloc = _alloc({k: len(v) for k, v in strata.items()}, min(300, sum(len(v) for v in strata.values())), floor=30)
    rng = np.random.default_rng(SEED)
    picked = {}
    for k in sorted(alloc):
        names = strata[k]
        picked[k] = sorted([names[i] for i in rng.permutation(len(names))][: alloc[k]])
    return alloc, picked


def part_cc_local(args):
    t0 = time.time()
    strata = ccl_strata()
    if args.limit:
        strata = {k: v[: args.limit] for k, v in strata.items()}
    allf = strata["main"] + strata["subagent"]
    with Pool(max(1, min(args.workers, 6))) as pool:
        inv = pool.map(_ccl_inv_worker, allf, chunksize=4)
    inv_out = {}
    for k in strata:
        idx = [i for i, f in enumerate(allf) if f in set(strata[k])]
        recs, nfiles, st = collections.Counter(), collections.Counter(), collections.Counter()
        for i in idx:
            g, s = inv[i]
            for gg, c in g.items():
                recs[gg] += c
                nfiles[gg] += 1
            st.update(s)
        n = len(idx)
        inv_out[k] = {"n_files": n, "line_stats": dict(st), "groups": {
            g: {"records": recs[g], "files_with": nfiles[g], "files_with_wilson": list(stats.wilson(nfiles[g], n)),
                "kind": group_kind("claude_code", g)} for g in sorted(recs)}}
    alloc, picked = ccl_sample(strata)
    cen = Census(maxdepth=4, strict=True, keep_values=False, track_units=True, opaque=CC_PRIVATE_OPAQUE,
                 opaque_segments=CC_PRIVATE_OPAQUE_SEGMENTS)
    stat = collections.Counter()
    unit = 0
    for k in sorted(alloc):
        for f in picked[k]:
            for g, rec, kind in cc_records(iter_lines(f, stat), private=True):
                cen.add(k + ":" + g, rec, unit, opaque_all=(kind == "tur_opaque"))
            unit += 1
    # sidecar JSON files: *.meta.json and workflows/*.json (key names + type counts only)
    side = Census(maxdepth=3, strict=True, keep_values=False, track_units=False,
                  opaque=("result", "args", "logs", "phases", "workflowProgress"))
    nside = collections.Counter()
    for p in sorted(CCL.rglob("*.json")):
        rel = os.path.relpath(p, CCL).replace(os.sep, "/")
        kind = "meta.json" if rel.endswith(".meta.json") else ("workflow.json" if "/workflows/" in rel else "other.json")
        nside[kind] += 1
        try:
            with open(p, "r", encoding="utf-8") as fh:
                o = json.load(fh)
        except ValueError:
            nside[kind + ":parse_error"] += 1
            continue
        side.add(kind, o)
    spill = list(CCL.rglob("tool-results/*.txt"))

    def cap(g, p):
        return cc_captured_fn(g.split(":", 1)[1], p)

    return {"part": "cc_local", "source": "data/claude-code-local (PRIVATE: aggregates only)", "ir_source": True,
            "n_jsonl_files": {k: len(v) for k, v in strata.items()},
            "inventory_full_population": inv_out,
            "sample": {"alloc": alloc, "n_files": unit, "line_stats": dict(stat)},
            "census": {"claude_code": cen.export(cap, "file")},
            "sidecar_json": {"n_files": dict(nside),
                             "census": side.export(lambda g, p: "not_ir_source", "record")},
            "tool_results_spill_files": {"n_files": len(spill), "total_bytes": int(sum(os.path.getsize(s) for s in spill))},
            "elapsed_s": round(time.time() - t0, 1)}


# ---------------------------------------------------------------------------------------------------------- part: aiv

AIV = DATA / "ai-village"
AIV_HEAD = 20000
AIV_DEEP = {"agent_messages", "content", "data"}
AIV_CLUSTER = {"claude_code_messages": "run"}
RULES["aiv_claude_code_messages_unit"] = (
    "unit = run: rows of one sdk_session_id split at its system/init rows (created_at order), the run index of a head "
    "row = number of init rows of its sdk_session_id with created_at <= its created_at, minus 1 ('pre' if none). "
    "sdk_session_id itself is not usable as the unit (full-table distribution recorded in sdk_session_full_scan).")


def _aiv_cc_runs():
    """Full scan of claude_code_messages: init times per sdk_session_id and the sdk_session_id size distribution."""
    import bisect  # noqa: F401
    inits, sizes, csz = collections.defaultdict(list), collections.Counter(), collections.Counter()
    with gzip.open(AIV / "claude_code_messages.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            o = json.loads(line)
            sizes[o.get("sdk_session_id")] += 1
            c = o.get("content") if isinstance(o.get("content"), dict) else {}
            csz[c.get("session_id")] += 1
            if o.get("message_type") == "system" and o.get("message_subtype") == "init":
                inits[o.get("sdk_session_id")].append(o.get("created_at"))
    for k in inits:
        inits[k].sort()
    v = sorted(sizes.values(), reverse=True)
    cv = sorted(csz.values(), reverse=True)
    scan = {"rows": sum(v), "distinct_sdk_session_id": len(v), "largest_sdk_session_rows": v[0] if v else 0,
            "top5_sdk_session_rows": v[:5], "distinct_content_session_id": len(cv), "top5_content_session_rows": cv[:5],
            "init_rows": sum(len(x) for x in inits.values())}
    return inits, scan
AIV_IR = {"claude_code_messages", "computer_use_turns"}


def _aiv_depth(p):
    root = p.split(".", 1)[0].split("[", 1)[0].split("{", 1)[0]
    return 6 if root in AIV_DEEP else 3


def part_aiv(args):
    t0 = time.time()
    out = {"part": "aiv", "source": "data/ai-village", "head_rows": AIV_HEAD, "tables": {}}
    for f in sorted(AIV.glob("*.jsonl.gz")):
        table = f.name[: -len(".jsonl.gz")]
        ckey = AIV_CLUSTER.get(table)
        runs, scan = (_aiv_cc_runs() if table == "claude_code_messages" else (None, None))
        cen = Census(depth_fn=_aiv_depth, json_keys={"arguments"}, keep_values=True, track_units=ckey is not None)
        ids, created, clusters = [], [], set()
        n = 0
        call_tool = {}
        cc_entries = []
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                if n >= (args.limit or AIV_HEAD):
                    break
                line = line.strip()
                if not line:
                    continue
                o = json.loads(line)
                n += 1
                if table == "claude_code_messages":
                    import bisect
                    sdk = o.get("sdk_session_id")
                    ix = bisect.bisect_right(runs.get(sdk, []), o.get("created_at")) - 1
                    unit = f"{sdk}/{'pre' if ix < 0 else 'r%03d' % ix}"
                    clusters.add(("run", unit))
                else:
                    unit = o.get(ckey) if ckey else None
                cen.add(table, o, unit)
                ids.append(str(o.get("id")))
                created.append(o.get("created_at"))
                for k in ("session_id", "sdk_session_id", "agent_id", "room_id"):
                    if k in o:
                        clusters.add((k, o.get(k)))
                if table == "claude_code_messages" and isinstance(o.get("content"), dict):
                    cc_entries.append((unit, o["content"]))
        # Claude Agent SDK entries: per-entry-type census + toolUseResult per tool (same CC grouping as other corpora)
        extra = {}
        if cc_entries:
            cc = Census(maxdepth=5, keep_values=True, track_units=True)
            for unit, e in cc_entries:
                c = e.get("message", {}).get("content") if isinstance(e.get("message"), dict) else None
                if e.get("type") == "assistant" and isinstance(c, list):
                    for b in c:
                        if isinstance(b, dict) and b.get("type") == "tool_use":
                            call_tool[b.get("id")] = b.get("name")
            for unit, e in cc_entries:
                for g, rec, _ in cc_records([e]):
                    if g.startswith("toolUseResult/unresolved"):
                        msg = e.get("message") if isinstance(e.get("message"), dict) else {}
                        cid = next((b.get("tool_use_id") for b in (msg.get("content") or []) if isinstance(b, dict)
                                    and b.get("type") == "tool_result"), None)
                        g = "toolUseResult/" + tool_name_clean(call_tool.get(cid), False)
                    cc.add(g, rec, unit)
            extra["content_as_cc_entries"] = cc.export(cc_captured_fn, "run")
            extra["sdk_session_full_scan"] = scan
        # order check (does head order look like id order?)
        asc_id = sum(1 for a, b in zip(ids, ids[1:]) if a < b)
        cr = [c for c in created if isinstance(c, str)]
        asc_ct = sum(1 for a, b in zip(cr, cr[1:]) if a < b)
        if table in AIV_IR:
            if table == "claude_code_messages":
                def cap(g, p):
                    if p == "created_at":
                        return "ir_column:ts"
                    if p.startswith("content."):
                        return cc_captured(p[len("content."):])
                    if p == "content":
                        return "cc_jsonl"
                    return None
            else:
                def cap(g, p):
                    if p in AIV_CU_SEMANTIC:
                        return "ir_column:" + AIV_CU_SEMANTIC[p]
                    return semantic_captured(p)
        else:
            def cap(g, p):
                return "not_ir_source"
        out["tables"][table] = {
            "rows_read": n, "ir_source": table in AIV_IR, "cluster_key": ckey,
            "distinct_cluster_keys_in_head": {k: len({v for kk, v in clusters if kk == k})
                                              for k in sorted({kk for kk, _ in clusters})},
            "order_check": {"adjacent_pairs": max(0, len(ids) - 1), "id_ascending_pairs": asc_id,
                            "created_at_ascending_pairs": asc_ct, "created_at_min": min(cr) if cr else None,
                            "created_at_max": max(cr) if cr else None},
            "census": cen.export(cap, ckey or "record"), **extra}
    out["not_censused"] = ["village-transcript.json (single 362 MB JSON document; rendering of events + chat_messages)"]
    out["elapsed_s"] = round(time.time() - t0, 1)
    return out


# -------------------------------------------------------------------------------------------------------- part: tables

SWT = DATA / "swe-chat-pinned"
TABLES = ["conversations", "sessions", "session_logs", "checkpoints", "commits", "repositories"]
TABLE_CLUSTER = {"conversations": "session_id", "checkpoints": "repo_id", "commits": "repo_id"}


def part_tables(args):
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    import pandas as pd
    t0 = time.time()
    out = {"part": "tables", "source": "data/swe-chat-pinned/*.parquet", "ir_source": False, "tables": {}}
    for table in TABLES:
        pf = pq.ParquetFile(SWT / f"{table}.parquet")
        schema = pf.schema_arrow
        cols = [f.name for f in schema]
        ckey = TABLE_CLUSTER.get(table)
        nrg = pf.metadata.num_row_groups if not args.limit else min(pf.metadata.num_row_groups, 3)
        probe_stride = max(1, nrg // 100)
        st = {c: {"non_null": 0, "non_empty": 0, "min": None, "max": None, "hashes": [], "rg_nonnull": [],
                  "json_probe": [0, 0]} for c in cols}
        sess_index, sess_nonnull, sess_rows = {}, {c: np.zeros(0) for c in cols}, np.zeros(0)
        rows = 0
        for rg in range(nrg):
            for c in cols:
                arr = pf.read_row_group(rg, columns=[c]).column(0).combine_chunks()
                s = st[c]
                valid = arr.is_valid().to_numpy(zero_copy_only=False)
                nn = int(valid.sum())
                s["non_null"] += nn
                s["rg_nonnull"].append(nn)
                typ = arr.type
                if nn:
                    nonnull = arr.drop_null()
                    if pa.types.is_string(typ) or pa.types.is_large_string(typ):
                        s["non_empty"] += int(pc.sum(pc.greater(pc.utf8_length(nonnull), 0)).as_py() or 0)
                        vals = nonnull.to_numpy(zero_copy_only=False)
                        s["hashes"].append(pd.util.hash_array(vals.astype(object)))
                        if rg % probe_stride == 0 and s["json_probe"][0] < 300:
                            for v in vals[: min(3, 300 - s["json_probe"][0])]:
                                s["json_probe"][0] += 1
                                if v[:1] in ("{", "["):
                                    try:
                                        if isinstance(json.loads(v), (dict, list)):
                                            s["json_probe"][1] += 1
                                    except ValueError:
                                        pass
                    elif pa.types.is_boolean(typ):
                        s["non_empty"] += nn
                        s["hashes"].append(np.unique(nonnull.to_numpy(zero_copy_only=False).astype(np.int64)))
                    else:
                        s["non_empty"] += nn
                        mm = pc.min_max(nonnull)
                        lo, hi = mm["min"].as_py(), mm["max"].as_py()
                        lo, hi = (str(lo), str(hi)) if pa.types.is_timestamp(typ) else (lo, hi)
                        s["min"] = lo if s["min"] is None or lo < s["min"] else s["min"]
                        s["max"] = hi if s["max"] is None or hi > s["max"] else s["max"]
                        v = nonnull.to_numpy(zero_copy_only=False)
                        if pa.types.is_timestamp(typ):
                            v = v.astype("datetime64[ns]").astype(np.int64)
                        s["hashes"].append(np.unique(v))
                if ckey and c == ckey:
                    keys = arr.to_pylist()
                    codes = np.empty(len(keys), dtype=np.int64)
                    for i, k in enumerate(keys):
                        codes[i] = sess_index.setdefault(k, len(sess_index))
                    st["__codes__"] = codes
                if ckey:
                    st.setdefault("__valid__", {})[c] = valid
                if len(s["hashes"]) > 64:
                    s["hashes"] = [np.unique(np.concatenate(s["hashes"]))]
            rows += pf.metadata.row_group(rg).num_rows
            if ckey:
                codes = st.pop("__codes__")
                m = len(sess_index)
                if len(sess_rows) < m:
                    sess_rows = np.concatenate([sess_rows, np.zeros(m - len(sess_rows))])
                    for c in cols:
                        sess_nonnull[c] = np.concatenate([sess_nonnull[c], np.zeros(m - len(sess_nonnull[c]))])
                sess_rows += np.bincount(codes, minlength=m)
                for c, valid in st.pop("__valid__").items():
                    sess_nonnull[c] += np.bincount(codes, weights=valid.astype(float), minlength=m)
        tout = {"rows": rows, "row_groups_read": nrg, "cluster_key": ckey,
                "n_clusters": len(sess_index) if ckey else None, "columns": {}}
        for f_ in schema:
            c = f_.name
            s = st[c]
            distinct = int(np.unique(np.concatenate(s["hashes"])).size) if s["hashes"] else 0
            e = {"type": str(f_.type), "non_null": s["non_null"], "non_empty": s["non_empty"], "distinct": distinct,
                 "distinct_method": "64-bit hash of value (pandas.util.hash_array) for strings; exact for others"}
            if s["min"] is not None:
                e["min"], e["max"] = s["min"], s["max"]
            jp = s["json_probe"]
            if jp[0]:
                e["json_probe_first300_nonnull"] = {"probed": jp[0], "parsed_json_container": jp[1]}
            tps = collections.Counter()
            if pa.types.is_string(f_.type) or pa.types.is_large_string(f_.type):
                tps["str"] = s["non_null"]
            elif pa.types.is_boolean(f_.type):
                tps["bool"] = s["non_null"]
            elif pa.types.is_integer(f_.type):
                tps["int"] = s["non_null"]
            elif pa.types.is_floating(f_.type):
                tps["float"] = s["non_null"]
            else:
                tps["str"] = s["non_null"]  # timestamps: treated as clock strings below
            tps["null"] = rows - s["non_null"]
            shapes = {"iso": s["non_null"]} if pa.types.is_timestamp(f_.type) else {}
            if pa.types.is_integer(f_.type) and s["min"] is not None:
                if 1e12 <= s["min"] and s["max"] < 4.1e12:
                    shapes = {"epoch_ms": s["non_null"]}
            cls = classify(c, tps, shapes)
            if cls["classes"]:
                e["classes"] = cls["classes"]
            if cls["name_only"]:
                e["name_only"] = cls["name_only"]
            e["captured"] = "not_ir_source"
            if ckey:
                cr = stats.cluster_rate(sess_nonnull[c], sess_rows)
                e["fill"] = {"rate": cr["rate"], "lo": cr["lo"], "hi": cr["hi"], "num": cr["num"], "den": cr["den"],
                             "n_units": cr["n_sessions"], "ci": "cluster_rate/" + ckey, "scope": "full table"}
            else:
                w = stats.wilson(s["non_null"], rows)
                e["fill"] = {"rate": w[0], "lo": w[1], "hi": w[2], "num": s["non_null"], "den": rows,
                             "ci": "wilson/row", "scope": "full table"}
            tout["columns"][c] = e
        # JSON-string columns: >= 50% of the probed non-null values (spread over row groups) parse to a JSON object/array
        jcols = [c for c in cols if st[c]["json_probe"][0] and st[c]["json_probe"][1] / st[c]["json_probe"][0] >= 0.5]
        tout["json_columns"] = {}
        rng = np.random.default_rng(SEED)
        for c in jcols:
            counts = np.array(st[c]["rg_nonnull"], dtype=np.int64)
            total = int(counts.sum())
            k = min(500, total)
            ranks = np.sort(rng.choice(total, size=k, replace=False))
            cum = np.concatenate([[0], np.cumsum(counts)])
            need = collections.defaultdict(list)
            for r in ranks:
                g = int(np.searchsorted(cum, r, side="right") - 1)
                need[g].append(int(r - cum[g]))
            sub = "tool_name" if c == "tool_input_json" else ("turn_type" if table == "conversations" else None)
            extra_cols = [x for x in ([ckey] if ckey else []) + ([sub] if sub else []) if x]
            cen = Census(maxdepth=3, json_keys=set(), keep_values=True, track_units=bool(ckey))
            parsed = 0
            for g, ks in sorted(need.items()):
                tb = pf.read_row_group(g, columns=[c] + extra_cols)
                vals = tb.column(c).to_pylist()
                others = {x: tb.column(x).to_pylist() for x in extra_cols}
                nn_idx = [i for i, v in enumerate(vals) if v is not None]
                for kk in ks:
                    i = nn_idx[kk]
                    try:
                        o = json.loads(vals[i])
                    except ValueError:
                        o = None
                    if o is None:
                        continue
                    parsed += 1
                    grp = f"{table}.{c}" + (f"/{others[sub][i]}" if sub else "")
                    cen.add(grp, o, others[ckey][i] if ckey else None)
            tout["json_columns"][c] = {"population_non_null": total, "sample_n": k, "parsed": parsed, "grouped_by": sub,
                                       "census": cen.export(lambda g, p: "not_ir_source", ckey or "row")}
        out["tables"][table] = tout
        del st
    out["elapsed_s"] = round(time.time() - t0, 1)
    return out


# ---------------------------------------------------------------------------------------------------------- part: small

def _read_jsonl(path):
    op = gzip.open if str(path).endswith(".gz") else open
    with op(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def _csv_census(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        rd = csv.DictReader(fh)
        cols = rd.fieldnames or []
        n = 0
        nonempty = collections.Counter()
        distinct = {c: set() for c in cols}
        tps = {c: collections.Counter() for c in cols}
        shapes = {c: collections.Counter() for c in cols}
        for row in rd:
            n += 1
            for c in cols:
                v = row.get(c)
                if v not in (None, ""):
                    nonempty[c] += 1
                    if len(distinct[c]) < 200000:
                        distinct[c].add(v)
                    if NUMSTR_RX.match(v):
                        x = float(v)
                        tps[c]["int" if "." not in v else "float"] += 1
                        sh = shape_of(x, float)
                    else:
                        tps[c]["str"] += 1
                        sh = shape_of(v, str)
                    if sh:
                        shapes[c][sh] += 1
                else:
                    tps[c]["null"] += 1
    res = {"rows": n, "columns": {}}
    for c in cols:
        cls = classify(c, tps[c], shapes[c])
        w = stats.wilson(nonempty[c], n)
        e = {"non_empty": nonempty[c], "distinct": len(distinct[c]), "types": dict(tps[c]), "shapes": dict(shapes[c]),
             "captured": "not_ir_source"}
        if cls["classes"]:
            e["classes"] = cls["classes"]
            e["fill"] = {"rate": w[0], "lo": w[1], "hi": w[2], "num": nonempty[c], "den": n, "ci": "wilson/row"}
        if cls["name_only"]:
            e["name_only"] = cls["name_only"]
        res["columns"][c] = e
    return res


def part_small(args):
    import pyarrow.parquet as pq
    t0 = time.time()
    out = {"part": "small", "sources": {}}
    # Who&When (IR source 'whowhen'; the loader reads the JSON files)
    ww = Census(maxdepth=8, keep_values=True, track_units=False)
    for sub in ("Algorithm-Generated", "Hand-Crafted"):
        for p in sorted((DATA / "who-and-when" / "Who&When" / sub).glob("*.json")):
            with open(p, "r", encoding="utf-8") as fh:
                ww.add(f"json/{sub}", json.load(fh))
        tb = pq.read_table(DATA / "who-and-when" / f"{sub}.parquet").to_pylist()
        for r in tb:
            ww.add(f"parquet/{sub}", r)
    out["sources"]["who_and_when"] = {"ir_source": True, "census": ww.export(lambda g, p: semantic_captured(p), "record")}
    # collusion-wiki
    cw = DATA / "collusion-wiki"
    cwo = {"ir_source": False, "jsonl": {}, "json": {}, "csv": {}}
    page_key = {"events.jsonl": "page_key", "revisions.jsonl": "page_key", "labels.jsonl": "page_key"}
    for p in sorted((cw / "full-wiki-logs").glob("*.jsonl")) + [cw / "records.jsonl.gz", cw / "links.jsonl.gz"]:
        pk = page_key.get(p.name)
        cen = Census(maxdepth=8, keep_values=True, track_units=pk is not None)
        n = 0
        for o in _read_jsonl(p):
            n += 1
            cen.add(p.name, o, (o.get(pk) if isinstance(o, dict) else None) if pk else None)
        cwo["jsonl"][p.name] = {"rows": n, "cluster_key": pk, "census": cen.export(lambda g, q: "not_ir_source", pk or "record")}
    for p in [cw / "full-wiki-logs" / "manifest.json", cw / "other-wikis.json.gz", cw / "shortener-logs.json.gz"]:
        op = gzip.open if p.name.endswith(".gz") else open
        with op(p, "rt", encoding="utf-8") as fh:
            d = json.load(fh)
        cen = Census(maxdepth=8, keep_values=True, track_units=False)
        if isinstance(d, list):
            for o in d:
                cen.add(p.name + "[]", o)
        else:
            cen.add(p.name, d)
        cwo["json"][p.name] = {"top_type": type(d).__name__, "census": cen.export(lambda g, q: "not_ir_source", "record")}
    for p in sorted(cw.glob("*.csv")):
        cwo["csv"][p.name] = _csv_census(p)
    out["sources"]["collusion_wiki"] = cwo
    # urlquery
    uq = DATA / "urlquery-agent-activity" / "urlquery-agent-activity-2026-09-22-v5"
    uqo = {"ir_source": False, "csv": {}, "json": {}, "txt": {}}
    for p in sorted(uq.iterdir()):
        if p.suffix == ".csv":
            uqo["csv"][p.name] = _csv_census(p)
        elif p.suffix == ".json":
            with open(p, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            cen = Census(maxdepth=8, keep_values=True, track_units=False)
            if isinstance(d, list):
                for o in d:
                    cen.add(p.name + "[]", o)
            else:
                cen.add(p.name, d)
            uqo["json"][p.name] = {"top_type": type(d).__name__, "census": cen.export(lambda g, q: "not_ir_source", "record")}
        elif p.suffix == ".txt":
            with open(p, "r", encoding="utf-8") as fh:
                uqo["txt"][p.name] = {"lines": sum(1 for _ in fh)}
    out["sources"]["urlquery"] = uqo
    out["elapsed_s"] = round(time.time() - t0, 1)
    return out


# ---------------------------------------------------------------------------------------------------------------- merge

def _flag_rows(source, census_export, extra_ctx=None):
    rows = []
    for g, G in census_export["groups"].items():
        for p, e in G["paths"].items():
            if "classes" not in e or p == "$":
                continue
            r = {"source": source, "group": g, "path": p, "classes": e["classes"], "n_rec": e["n_rec"],
                 "n_records": G["n_records"], "unit": G["unit"], "captured": e.get("captured"),
                 "loader": loader_mark(p) if e.get("captured") in (None, "not_ir_source") else None,
                 "fill": e.get("fill"), "types": e["types"]}
            if "unit_presence" in e:
                r["unit_presence"] = e["unit_presence"]
            if extra_ctx:
                r.update(extra_ctx)
            rows.append(r)
    return rows


def _table_rows(tables_part):
    rows = []
    for t, T in tables_part["tables"].items():
        for c, e in T["columns"].items():
            if "classes" in e:
                rows.append({"source": "swechat_tables", "group": t, "path": c, "classes": e["classes"], "n_rec": e["non_null"],
                             "n_records": T["rows"], "unit": T["cluster_key"] or "row", "captured": "not_ir_source",
                             "loader": loader_mark(c), "fill": e["fill"], "types": {"type": e["type"]}})
        for c, J in T["json_columns"].items():
            rows += _flag_rows("swechat_tables_json", J["census"])
    return rows


def merge(args):
    parts = {}
    for name in ("tables", "transcripts", "cc_local", "aiv", "small", "identities"):
        p = PART_DIR / f"{name}.json"
        if p.exists():
            with open(p, "r", encoding="utf-8") as fh:
                parts[name] = json.load(fh)
    flagged = []
    if "tables" in parts:
        flagged += _table_rows(parts["tables"])
    if "transcripts" in parts:
        for fmt, C in parts["transcripts"]["census"].items():
            flagged += _flag_rows(f"swechat_transcripts/{fmt}", C)
    if "cc_local" in parts:
        flagged += _flag_rows("cc_local/claude_code", parts["cc_local"]["census"]["claude_code"])
        flagged += _flag_rows("cc_local/sidecar_json", parts["cc_local"]["sidecar_json"]["census"])
    if "aiv" in parts:
        for t, T in parts["aiv"]["tables"].items():
            flagged += _flag_rows(f"ai_village/{t}", T["census"])
            if "content_as_cc_entries" in T:
                flagged += _flag_rows(f"ai_village/{t}/content_as_cc", T["content_as_cc_entries"])
    if "small" in parts:
        S = parts["small"]["sources"]
        flagged += _flag_rows("who_and_when", S["who_and_when"]["census"])
        for kind in ("jsonl", "json"):
            for fn, X in S["collusion_wiki"][kind].items():
                flagged += _flag_rows(f"collusion_wiki/{fn}", X["census"])
            for fn, X in S["urlquery"].get(kind, {}).items():
                flagged += _flag_rows(f"urlquery/{fn}", X["census"])
        for src in ("collusion_wiki", "urlquery"):
            for fn, X in S[src]["csv"].items():
                for c, e in X["columns"].items():
                    if "classes" in e:
                        flagged.append({"source": f"{src}/{fn}", "group": fn, "path": c, "classes": e["classes"],
                                        "n_rec": e["non_empty"], "n_records": X["rows"], "unit": "row",
                                        "captured": "not_ir_source", "loader": loader_mark(c), "fill": e.get("fill"),
                                        "types": e["types"]})
    uncaptured = [r for r in flagged if r["captured"] in (None, "not_ir_source")]
    by_class = collections.Counter()
    by_class_unc = collections.Counter()
    for r in flagged:
        for c in r["classes"]:
            by_class[c] += 1
    for r in uncaptured:
        for c in r["classes"]:
            by_class_unc[c] += 1
    inventory = {}
    if "transcripts" in parts:
        inventory["swechat_transcripts"] = parts["transcripts"]["inventory_full_population"]
    if "cc_local" in parts:
        inventory["cc_local"] = parts["cc_local"]["inventory_full_population"]
    if "aiv" in parts and "claude_code_messages" in parts["aiv"]["tables"]:
        T = parts["aiv"]["tables"]["claude_code_messages"]
        if "content_as_cc_entries" in T:
            inventory["ai_village_claude_code_messages_head"] = {
                g: {"records": G["n_records"], "kind": group_kind("claude_code", g)}
                for g, G in T["content_as_cc_entries"]["groups"].items() if not g.startswith("toolUseResult/")}
    if "tables" in parts:
        inventory["swechat_conversations_table"] = "see parts.tables.tables.conversations.columns (turn_type / role / " \
                                                   "queue_op_subtype distinct counts); per-value counts in conversations_value_counts"
        inventory["swechat_conversations_value_counts"] = parts["tables"].get("conversations_value_counts")
    meta = {"script": "analysis/probes/phase_a6_raw_census.py", "seed": SEED, "rules": RULES,
            "cc_captured_paths": sorted(CC_EXACT), "cc_captured_prefixes": list(CC_PREFIX),
            "tur_captured_keys": sorted(TUR_EXACT), "ir_semantic_keys": IR_SEMANTIC,
            "ir_semantic_suffixes": IR_SEMANTIC_SUFFIX, "aiv_cu_semantic": AIV_CU_SEMANTIC,
            "ir_columns": list(COLUMNS), "loader_files_scanned": sorted(loader_literals()),
            "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    final = {"meta": meta, "flagged_counts": {"flagged_paths": len(flagged), "uncaptured_paths": len(uncaptured),
                                              "by_class": dict(by_class), "uncaptured_by_class": dict(by_class_unc)},
             "flagged": flagged, "non_tool_entry_inventory": inventory, "parts": parts}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(final, fh, ensure_ascii=False, separators=(",", ":"), default=_default)
    print("wrote", OUT_JSON, "flagged", len(flagged), "uncaptured", len(uncaptured))


def _default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, set):
        return sorted(o)
    return str(o)


def conv_value_counts():
    """Exact per-value counts of the conversations table's categorical row-type columns (non-tool entry inventory)."""
    import pyarrow.parquet as pq
    cols = ["role", "turn_type", "queue_op_subtype", "agent", "category"]
    pf = pq.ParquetFile(SWT / "conversations.parquet")
    cnt = {c: collections.Counter() for c in cols}
    pair = collections.Counter()
    for rg in range(pf.metadata.num_row_groups):
        tb = pf.read_row_group(rg, columns=cols).to_pydict()
        for c in cols:
            cnt[c].update(tb[c])
        pair.update(zip(tb["role"], tb["turn_type"]))
    return {"columns": {c: {str(k): v for k, v in cnt[c].most_common()} for c in cols},
            "role_x_turn_type": [{"role": a, "turn_type": b, "rows": v} for (a, b), v in pair.most_common()]}


# ----------------------------------------------------------------------------------- part: identities (redundancy checks)

RULES["identities"] = {
    "purpose": "does a harness-written counter agree with another record of the same quantity? Pre-specified exact "
               "equalities (no tolerance), evaluated on the same 300-file swechat sample and the same cc_local sample.",
    "I1a_codex_last_total": "event_msg/token_count: last_token_usage.total_tokens == input_tokens + output_tokens",
    "I1b_codex_cumulative": "consecutive token_count events with info in file order: total_token_usage(n).X == "
                            "total_token_usage(n-1).X + last_token_usage(n).X for X in input/output/total_tokens (all three)",
    "I2_gemini_total": "message type gemini with integer tokens: F1 total == input+output+thoughts+tool; "
                       "F2 total == input+output+thoughts; F3 total == input+output (each reported)",
    "I3_opencode_total": "step-finish parts and assistant message infos with integer tokens: F1 total == "
                         "input+output+reasoning+cache.read+cache.write; F2 total == input+output+reasoning (each reported)",
    "I4_cc_read_numlines": "user entry whose toolUseResult.file has integer numLines and a tool_result block: L = number of "
                           "lines of the model-visible tool_result text matching ^\\s*\\d+(U+2192|\\t); match if L == numLines; "
                           "also numLines == line count of toolUseResult.file.content (str.splitlines)",
    "I5_cc_agent_toolcount": "swechat claude_code only: toolUseResult.totalToolUseCount == number of distinct nested "
                             "tool_use ids in progress/agent_progress entries whose parentToolUseID is that call's id",
    "ci": "wilson over checks and cluster_rate with the file as unit",
}
_LINE_PREFIX = re.compile("^\\s*\\d+(\u2192|\\t)")


class Tally:
    def __init__(self):
        self.k, self.n, self.by_file, self.diffs = 0, 0, collections.defaultdict(lambda: [0, 0]), []

    def add(self, ok, unit, diff=None):
        self.n += 1
        self.k += bool(ok)
        bf = self.by_file[unit]
        bf[0] += bool(ok)
        bf[1] += 1
        if not ok and diff is not None and len(self.diffs) < 5000:
            self.diffs.append(diff)

    def out(self):
        if self.n == 0:
            return {"n": 0}
        w = stats.wilson(self.k, self.n)
        units = list(self.by_file)
        cr = stats.cluster_rate([self.by_file[u][0] for u in units], [self.by_file[u][1] for u in units])
        o = {"match": self.k, "n": self.n, "rate": w[0], "wilson_lo": w[1], "wilson_hi": w[2],
             "cluster": {"rate": cr["rate"], "lo": cr["lo"], "hi": cr["hi"], "n_files": cr["n_sessions"]},
             "files_with_any_mismatch": sum(1 for u in units if self.by_file[u][0] < self.by_file[u][1])}
        if self.diffs:
            o["mismatch_diff"] = stats.describe(self.diffs)
        return o


def _ints(d, *ks):
    return isinstance(d, dict) and all(type(d.get(k)) is int for k in ks)


def _text_lines(content):
    if isinstance(content, str):
        return content.split("\n")
    out = []
    for b in content if isinstance(content, list) else []:
        if isinstance(b, dict) and b.get("type") == "text":
            out += (b.get("text") or "").split("\n")
    return out


def _cc_identities(entries, unit, T, private=False):
    nested_ids = collections.defaultdict(set)
    agent_counts = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        if e.get("type") == "progress":
            d = e.get("data") if isinstance(e.get("data"), dict) else {}
            if d.get("type") == "agent_progress" and isinstance(d.get("message"), dict):
                m = d["message"].get("message") if isinstance(d["message"].get("message"), dict) else {}
                c = m.get("content") if isinstance(m.get("content"), list) else []
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        nested_ids[e.get("parentToolUseID")].add(b.get("id"))
            continue
        tur = e.get("toolUseResult")
        msg = e.get("message") if isinstance(e.get("message"), dict) else {}
        blocks = msg.get("content") if isinstance(msg.get("content"), list) else []
        tr = next((b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_result"), None)
        if not isinstance(tur, dict) or tr is None:
            continue
        f = tur.get("file")
        if isinstance(f, dict) and type(f.get("numLines")) is int:
            L = sum(1 for ln in _text_lines(tr.get("content")) if _LINE_PREFIX.match(ln))
            T["I4_cc_read_numlines_vs_text"].add(L == f["numLines"], unit, L - f["numLines"])
            if isinstance(f.get("content"), str):
                C = len(f["content"].splitlines())
                T["I4_cc_read_numlines_vs_file_content"].add(C == f["numLines"], unit, C - f["numLines"])
        if not private and type(tur.get("totalToolUseCount")) is int:
            agent_counts.append((tr.get("tool_use_id"), tur["totalToolUseCount"]))
    for cid, cnt in agent_counts:
        if cid in nested_ids:
            n = len(nested_ids[cid])
            T["I5_cc_agent_toolcount"].add(n == cnt, unit, n - cnt)
        else:
            T["I5_cc_agent_toolcount_no_nested_traffic"].add(True, unit)


def part_identities(args):
    t0 = time.time()
    with open(PART_DIR / "transcripts.json", "r", encoding="utf-8") as fh:
        sample = json.load(fh)["sample"]["files"]
    T = collections.defaultdict(Tally)
    stat = collections.Counter()
    keys = ("input_tokens", "output_tokens", "total_tokens")
    for fmt in sorted(sample):
        for i, name in enumerate(sample[fmt]):
            unit = f"{fmt}:{i}"
            path = str(TRANS / name)
            f_, doc = detect(path)
            if fmt == "codex":
                prev = None
                for e in iter_lines(path, stat):
                    if codex_group(e) != "event_msg/token_count":
                        continue
                    info = (e.get("payload") or {}).get("info")
                    if not isinstance(info, dict):
                        continue
                    last, tot = info.get("last_token_usage"), info.get("total_token_usage")
                    if _ints(last, *keys):
                        d = last["total_tokens"] - last["input_tokens"] - last["output_tokens"]
                        T["I1a_codex_last_total"].add(d == 0, unit, d)
                    if prev is not None and _ints(tot, *keys) and _ints(last, *keys):
                        ok = all(tot[k] == prev[k] + last[k] for k in keys)
                        T["I1b_codex_cumulative"].add(ok, unit, tot["total_tokens"] - prev["total_tokens"] - last["total_tokens"])
                    if _ints(tot, *keys):
                        prev = tot
            elif fmt == "gemini" and doc is not None:
                for m in doc.get("messages") or []:
                    tk = m.get("tokens") if isinstance(m, dict) else None
                    if isinstance(m, dict) and m.get("type") == "gemini" and _ints(tk, "input", "output", "total"):
                        th, tl = tk.get("thoughts") or 0, tk.get("tool") or 0
                        d1 = tk["total"] - tk["input"] - tk["output"] - th - tl
                        T["I2_gemini_F1_in_out_thoughts_tool"].add(d1 == 0, unit, d1)
                        T["I2_gemini_F2_in_out_thoughts"].add(tk["total"] == tk["input"] + tk["output"] + th, unit)
                        T["I2_gemini_F3_in_out"].add(tk["total"] == tk["input"] + tk["output"], unit)
            elif fmt == "opencode" and doc is not None:
                for g, rec in doc_records(fmt, doc):
                    if g == "part/step-finish":
                        tk, lab = rec.get("tokens"), "step_finish"
                    elif g == "message_info/assistant":
                        tk, lab = (rec.get("info") or {}).get("tokens"), "message_info"
                    else:
                        continue
                    if _ints(tk, "input", "output", "total"):
                        c = tk.get("cache") if isinstance(tk.get("cache"), dict) else {}
                        r_ = tk.get("reasoning") or 0
                        d1 = tk["total"] - (tk["input"] + tk["output"] + r_ + (c.get("read") or 0) + (c.get("write") or 0))
                        T[f"I3_opencode_{lab}_F1_all"].add(d1 == 0, unit, d1)
                        T[f"I3_opencode_{lab}_F2_in_out_reasoning"].add(tk["total"] == tk["input"] + tk["output"] + r_, unit)
            elif fmt == "claude_code":
                _cc_identities(iter_lines(path, stat), unit, T)
            doc = None
    TL = collections.defaultdict(Tally)
    _, picked = ccl_sample(ccl_strata())
    for k in sorted(picked):
        for i, f in enumerate(picked[k]):
            _cc_identities(iter_lines(f, stat), f"{k}:{i}", TL, private=True)
    return {"part": "identities", "swechat_sample": {k: T[k].out() for k in sorted(T)},
            "cc_local_sample": {k: TL[k].out() for k in sorted(TL)}, "line_stats": dict(stat),
            "elapsed_s": round(time.time() - t0, 1)}


PARTS = {"tables": part_tables, "transcripts": part_transcripts, "cc_local": part_cc_local, "aiv": part_aiv,
         "small": part_small, "identities": part_identities}


def run_part(name, args):
    res = PARTS[name](args)
    if name == "tables" and not args.limit:
        res["conversations_value_counts"] = conv_value_counts()
    PART_DIR.mkdir(parents=True, exist_ok=True)
    dest = PART_DIR / (f"{name}.json" if not args.limit else f"{name}.limit{args.limit}.json")
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, separators=(",", ":"), default=_default)
    print("wrote", dest, "elapsed", res.get("elapsed_s"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", required=True, choices=list(PARTS) + ["merge", "all"])
    ap.add_argument("--limit", type=int, default=0, help="debug: limit files/rows (writes *.limitN.json, never merged)")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    if args.part == "merge":
        merge(args)
    elif args.part == "all":
        for name in PARTS:
            run_part(name, args)
        merge(args)
    else:
        run_part(args.part, args)


if __name__ == "__main__":
    main()
