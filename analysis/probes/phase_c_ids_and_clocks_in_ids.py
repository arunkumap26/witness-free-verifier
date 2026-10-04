"""Phase C lens ids_and_clocks_in_ids: identifiers as data.

Writes RAW COUNTS ONLY to analysis/out/phase_c/ids_and_clocks_in_ids.json. Interpretation: analysis/notes/ids_and_clocks_in_ids.md.
Reads only the IR caches (analysis/cache/<corpus>_{B,A}.parquet, swechat_population.parquet). cc_local is private: every
cc_local output is an aggregate count / distribution; no id value, text, path or date from it is written.

Parts
  P1 census     every id-bearing IR column (call_id, api_msg_id, request_id, uuid, parent_uuid, agent_id, parent_call_id,
                session_id, plus provider ids the loaders moved to extra) -> family (FAMILY_RULES, fixed regexes), rows,
                distinct values, sessions, length histogram, alphabet class, positional entropy, UUID version/variant,
                degenerate ids.
  P2 clocks     families whose layout embeds time (decoders below). offset = event ts - embedded time, per family, with
                pre-registered bands; session-clustered CIs. Split B is primary, split A is a holdout for the decode rules.
                P2b order: id-time order vs ts order vs seq order inside a session. P2c bracket: a server-minted id's
                time must sit between the last input event before the response and the response's first event, up to
                one constant client-server skew per stream. P2d per-session offset floor and drift. P2e bit structure of
                the non-time bits. P2f format epochs (id layout by month). P2g counters embedded in ids.
  P3 reuse      ids present in more than one session (with copy consistency of the rows that carry them), within-session
                duplicates and orphans, birthday expectation for random families.
  P4 text       ids that appear inside model-visible text (result text and notifications) and whether they refer to the
                same object later in the session.

DECODE LAYOUTS. They were read off split-B data during exploration (this lens is discovery), which is why split A is run
as a holdout for the time-agreement numbers. They are hypotheses about vendor id formats, not documented facts:
  anthropic_{req,msg,toolu}  '<prefix>_[vrtx_|bdrk_]01' + 22 base58 chars (bitcoin alphabet) = 128-bit integer V;
                             V >> 80 = unix ms when it falls in the plausible window (time-format), else random-format.
  openai_item_hex            '<prefix>_' + 48 hex: unix seconds = int(hex[0:8]); + 50 hex with hex[16]=='0': unix
                             seconds = int(hex[18:26]).
  opencode_id                '<ses|msg|prt|...>_' + 12 hex + 14 base62; 48-bit X = int(12 hex) (bitwise NOT for 'ses');
                             X = (ms * 4096 + counter) mod 2^48, so ms mod 2^36 = X >> 12, counter = X & 0xFFF.
  gemini_cli_call            '<tool>_<13-digit ms>_<k>' or '<tool>-<13-digit ms>-<hex>': unix ms.
  gemini_response_id         base64url, bytes[0:4] little-endian = unix seconds.
  uuid v7 / v1               RFC 9562: v7 top 48 bits = unix ms; v1 60-bit 100 ns ticks since 1582-10-15.
  chatcmpl_ms                'chatcmpl-<13 digits>' = unix ms.
  msg_datetime14             'msg_' + YYYYMMDDhhmmss + hex (seen behind OpenAI-compatible proxies): read as a UTC wall
                             clock; a constant offset in whole hours would be a timezone, not an error.
  Anthropic time-format values are RFC 9562 UUIDv7 (version 7, variant 2) carried in base58; newer tool-use ids are
  UUIDv4 in base58 (P2e/P2f count the fields).
  uuid_dated                 'YYYY-MM-DD-<uuid>' (session file names): UTC day.

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_c_ids_and_clocks_in_ids
"""
import base64
import hashlib
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from analysis.lib import stats

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "analysis" / "cache"
OUT = ROOT / "analysis" / "out" / "phase_c" / "ids_and_clocks_in_ids.json"
EPOCH = pd.Timestamp("1970-01-01", tz="UTC")
CORPORA = ["swechat", "cc_local", "aiv_cc", "aiv_cu", "whowhen"]
PRIVATE = {"cc_local"}

# ---------------------------------------------------------------------------------------------------------------------
# Pre-registration: fixed before any outcome below was computed by this script (decode layouts: see module docstring).
# ---------------------------------------------------------------------------------------------------------------------
PREREG = {
    "split_primary": "B",
    "split_holdout": "A, used only to re-run P2 (time decoding agreement) because the layouts were read off split-B data",
    "time_plausible_window_utc": ["2024-01-01", "2027-01-01"],
    "anthropic_time_format_rule": "decoded V >> 80 inside the plausible window. Chance rate for a uniform random 128-bit "
                                  "value = window_ms / 2^48 (reported as expected_chance_time_plausible)",
    "offset_definition": "offset_ms = event_ts_ms - embedded_ms. Positive = the id was minted before the event that carries it.",
    "offset_bands_ms": [-1e18, -60000, -2000, 0, 1000, 10000, 60000, 600000, 1e18],
    "violation": "offset_ms < -2000 for ms-resolution ids, < -3000 for second-resolution ids (truncation makes the decoded "
                 "time up to 999 ms early, never late). Day-resolution (uuid_dated): first event UTC date != embedded date.",
    "gross_violation": "offset_ms < -60000",
    "far": "offset_ms > 600000",
    "agreement": "-tol <= offset_ms <= 600000",
    "order_inversion": "consecutive distinct ids of one family in one session, ordered by first seq: id-time decrease > tol "
                       "(2000 ms; 3000 ms second-resolution) = id inversion; ts decrease > 2000 ms = ts inversion",
    "bracket": "server-minted ids only. Per response k: lo_k = ts(last input event before the response) - embedded_ms, "
               "hi_k = ts(first event of the response) - embedded_ms. A constant skew s = client - server needs lo_k < s < hi_k "
               "for all k, so per stream L = max lo_k, U = min hi_k; inconsistent if L - U > tol (2000 ms; 3000 ms for "
               "second-resolution ids). Input events: kind result or user (CC formats); for aiv_cu the previous row "
               "(different uuid). Stream: CC = (session, agent_id or main); aiv_cu = session.",
    "floor": "per session with >= 20 decoded server-minted ids: floor = min offset; drift = floor(second half by seq) - "
             "floor(first half); halves need >= 10 ids each",
    "bit_bias": "|P(bit = 1) - 0.5| > 0.05 with n >= 1000 distinct ids",
    "degenerate": "id body (after the family prefix) is one repeated character, or has <= 2 distinct characters with length >= 8",
    "event_ts_for_id": {
        "row-level ids (call_id, api_msg_id, request_id, uuid)": "ts of the first event (min seq) in the session that carries the id; "
            "offset statistics are de-duplicated on the id string across sessions (resumed/forked copies carry identical "
            "ids), keeping the copy in the lexicographically smallest session_id; n_copies_removed is reported",
        "session_id": "min ts over the session",
        "agent_id": "min ts over the events with that agent_id in the session",
    },
    "text_id_patterns": "TEXT_PATTERNS below; regexes fixed before the text pass",
    "min_ids_for_rate": 1,
    "changes_after_dev_run": [
        "Added after the dev run on whowhen + aiv_cc (before any run on swechat, cc_local, aiv_cu): (1) anthropic time-format "
        "ids whose |offset| > 1 day are treated as random-format ids that landed in the plausible window by chance (their "
        "count is compared with expected_chance_time_plausible); the headline block for anthropic families excludes them "
        "and the all-time-format block is kept under including_abs_offset_gt_1day; P2b order and P2c/P2d already used "
        "|offset| <= 1 day for server-minted ids, now P2b does too. (2) Loader-synthetic ids (step:/turn:/synthetic:) are "
        "excluded from the cross-session copy-consistency check (they collide by construction). (3) T1 spill-path "
        "directory uuid is also compared with the uuid part of '<uuid>/rNNN' session ids (aiv_cc runs).",
        "Added after the dev run on aiv_cu + cc_local: P2b order is computed within streams (session x agent_id-or-main) "
        "because concurrent subagents interleave requests; P2e reports RFC 9562 version/variant fields of the decoded "
        "128-bit Anthropic values (biased bits sat exactly at those positions); P2h request/message pairing added.",
        "Added after the dev run on swechat: families msg_datetime14 ('msg_' + YYYYMMDDhhmmss + hex, read as UTC wall "
        "clock) and anthropic_toolu_callwrapped ('call_toolu_...'); openai_item_hex hex50 layout widened from "
        "b[16:18]=='00' to b[16]=='0' (Codex ws_ ids carry '01'); T1 restricted to results that start with "
        "'<persisted-output>' (the result's own spill notice; other mentions are only counted); P2h msg-minus-req "
        "restricted to pairs where both decode as UUIDv7 (version 7, variant 2); P3b copies section added (timestamp "
        "agreement of cross-session copies and request-id clock agreement per copy).",
        "Added after the first full run: T1 spill-file id classes (own call id / REDACTED by the release / 'b'+8 base36 "
        "shell output id / other), because 527 of 730 spill notices did not name the result's own call id; "
        "msg_datetime14 offsets split into a whole-hour component and a residual (all 466 sat near -8 h); "
        "violation_sessions added to offset blocks; bracket_x_copies cross-tab (bracket inconsistencies and upper-bound "
        "violations against sessions that hold re-stamped cross-session copies).",
        "Added after checking the notes against the JSON: release-redacted placeholder ids (value contains 'REDACTED', "
        "one OpenCode uuid shared by 197 sessions) are excluded from the copy checks (P3b and the text-pass copy "
        "consistency); before the fix they produced one spurious 'session pair' and the single non-identical copy."],
}

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
B58I = {c: i for i, c in enumerate(B58)}
B58C = "1-9A-HJ-NP-Za-km-z"
UUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
OAI_PRE = r"(?:fc|msg|cu|rs|resp|ws|ig|ci|ctc|lsh|mcp|mcpl|mcpr|ft|tsc|ts)"

FAMILY_RULES = [
    ("loader_synthetic", r"^(?:synthetic:|turn:|step:)"),
    ("redacted", r"REDACTED"),
    ("opencode_id", r"^(?:ses|msg|prt|call|per|que|tool|usr|snap|wrk)_[0-9a-f]{12}[0-9A-Za-z]{14}$"),
    ("anthropic_toolu", rf"^toolu_(?:vrtx_|bdrk_)?01[{B58C}]{{22}}$"),
    ("anthropic_srvtoolu", rf"^srvtoolu_(?:vrtx_|bdrk_)?01[{B58C}]{{22}}$"),
    ("anthropic_msg", rf"^msg_(?:vrtx_|bdrk_)?01[{B58C}]{{22}}$"),
    ("anthropic_req", rf"^req_(?:vrtx_|bdrk_)?01[{B58C}]{{22}}$"),
    ("zeroed_provider_id", r"^(?:toolu|msg|req|call|fc|resp)_0+$"),
    ("openai_item_hex", rf"^{OAI_PRE}_(?:[0-9a-f]{{48}}|[0-9a-f]{{50}})$"),
    ("msg_datetime14", r"^msg_20\d{12}[0-9a-f]{12,24}$"),
    ("anthropic_toolu_callwrapped", rf"^call_toolu_(?:vrtx_|bdrk_)?01[{B58C}]{{22}}$"),
    ("hex24_call", r"^call_[0-9a-f]{24}$"),
    ("openai_call", r"^call_[0-9A-Za-z]{24}$"),
    ("chatcmpl_ms", r"^chatcmpl-\d{13}$"),
    ("chatcmpl_other", r"^chatcmpl-"),
    ("gemini_cli_call", r"^[A-Za-z0-9_.]+?[_-]\d{13}[_-][0-9a-z]+$"),
    ("uuid_dated", rf"^\d{{4}}-\d{{2}}-\d{{2}}-{UUID_RE}$"),
    ("sdk_run", rf"^{UUID_RE}/(?:r\d{{3}}|pre)$"),
    ("call_uuid_n", rf"^call-{UUID_RE}-\d+$"),
    ("uuid", rf"^{UUID_RE}$"),
    ("cc_agent_id", r"^a(?:[0-9a-f]{6}|[0-9a-f]{16})$"),
    ("call_decimal", r"^call_\d+$"),
    ("tool_counter", r"^(?:functions\.)?[A-Za-z][A-Za-z_]*[:_.]\d+$"),
    ("gemini_response_id", r"^[A-Za-z0-9_-]{16,24}$"),  # only applied to aiv_cu api_msg_id (see classify)
    ("rand_base36_8", r"^[a-z0-9]{8}$"),
    ("hex32", r"^[0-9a-f]{32}$"),
    ("whowhen_session", r"^(?:Algorithm-Generated|Hand-Crafted)/\d+$"),
    ("capitalized_name", r"^[A-Z][a-z]+$"),
]
FAMILY_RX = [(n, re.compile(p)) for n, p in FAMILY_RULES]
PREREG["family_rules"] = FAMILY_RULES

TEXT_PATTERNS = {
    "cc_bg_issue": r"running in background with ID: ([A-Za-z0-9]+)",
    "cc_agent_id_text": r"agentId: (a[0-9a-f]{6,16})\b",
    "task_id_tag_notification": r"<task-id>([^<\s]+)</task-id>",
    "task_id_tag_output": r"<task_id>([^<\s]+)</task_id>",
    "tool_use_id_tag": r"<tool-use-id>([^<\s]+)</tool-use-id>",
    "output_file_task": r"<output-file>[^<]*/tasks/([^/<\s]+)\.output</output-file>",
    "cc_spill_path": rf"/({UUID_RE})/tool-results/([A-Za-z0-9_]+)\.txt",
    "todo_task_create": r"^Task #(\d+) created successfully",
    "codex_running": r"Process running with session ID (\d+)",
    "codex_exited": r"Process exited with code (-?\d+)",
    "commit_claim": r"(?m)^\[([^\]\s]+)(?: \(root-commit\))? ([0-9a-f]{7,40})\] (.+)$",
    "git_oneline": r"(?m)^(?:\* )?([0-9a-f]{7,12}) (.+)$",
    "req_in_text": rf"\breq_(?:vrtx_|bdrk_)?01[{B58C}]{{22}}\b",
    "uuid_in_text": rf"\b{UUID_RE}\b",
    "api_error_json": r'"type"\s*:\s*"error"',
    "pid_in_text": r"\b(?:PID|pid)[:= ]+(\d{2,7})\b",
}
PREREG["text_patterns"] = TEXT_PATTERNS
TRX = {k: re.compile(v) for k, v in TEXT_PATTERNS.items()}

WIN_LO = (pd.Timestamp(PREREG["time_plausible_window_utc"][0], tz="UTC") - EPOCH) // pd.Timedelta(milliseconds=1)
WIN_HI = (pd.Timestamp(PREREG["time_plausible_window_utc"][1], tz="UTC") - EPOCH) // pd.Timedelta(milliseconds=1)
BANDS = PREREG["offset_bands_ms"]
BAND_NAMES = ["lt_-60s", "-60s_-2s", "-2s_0", "0_1s", "1s_10s", "10s_60s", "60s_10min", "ge_10min"]
TOL = {"ms": 2000.0, "s": 3000.0}


# ---------------------------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------------------------
def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


def to_ms(ts):
    t = pd.to_datetime(ts, utc=True, format="ISO8601", errors="coerce")
    return ((t - EPOCH).dt.total_seconds() * 1000.0).astype(float)


def b58(s):
    v = 0
    for ch in s:
        v = v * 58 + B58I[ch]
    return v


def classify(v, corpus=None, column=None):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    s = str(v)
    for name, rx in FAMILY_RX:
        if name == "gemini_response_id" and not (corpus == "aiv_cu" and column == "api_msg_id"):
            continue
        if rx.search(s) if name in ("loader_synthetic", "redacted") else rx.match(s):
            return name
    return "other"


def id_body(s):
    """Part after the last structural prefix separator (for degeneracy / entropy)."""
    m = re.match(r"^(?:[A-Za-z]+_(?:vrtx_|bdrk_)?(?:01)?|chatcmpl-|call-)(.*)$", s)
    return m.group(1) if m and m.group(1) else s


def is_degenerate(s):
    b = id_body(s).replace("-", "")
    if not b:
        return False
    d = len(set(b))
    return d == 1 or (len(b) >= 8 and d <= 2)


def alphabet_class(values):
    chars = set("".join(values))
    if not chars:
        return "empty"
    if chars <= set("0123456789"):
        return "decimal"
    if chars <= set("0123456789abcdef"):
        return "hex_lower"
    if chars <= set(B58):
        return "base58"
    if chars <= set("0123456789abcdefghijklmnopqrstuvwxyz"):
        return "base36_lower"
    if chars <= set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"):
        return "base62"
    if chars <= set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"):
        return "base64url_or_base62_plus"
    return "mixed"


def positional_entropy(values):
    """values: distinct strings. Uses the modal length. Returns dict (entropy is capped by log2(n) per position)."""
    if not values:
        return {"n": 0}
    lens = Counter(len(v) for v in values)
    L, nL = lens.most_common(1)[0]
    vs = [v for v in values if len(v) == L]
    ent = []
    for i in range(L):
        c = Counter(v[i] for v in vs)
        n = sum(c.values())
        ent.append(-sum((k / n) * math.log2(k / n) for k in c.values()))
    return {"n_distinct_at_modal_length": len(vs), "modal_length": L, "entropy_bits_sum": round(sum(ent), 3),
            "entropy_cap_bits_per_position": round(math.log2(len(vs)), 3) if len(vs) > 1 else 0.0,
            "n_constant_positions": sum(1 for e in ent if e == 0.0),
            "n_positions_below_1bit": sum(1 for e in ent if e < 1.0),
            "alphabet_class_body": alphabet_class([id_body(v) for v in vs]),
            "alphabet_size_body": len(set("".join(id_body(v) for v in vs)))}


def uuid_version(s):
    h = s.replace("-", "")
    if set(h) == {"0"}:
        return "nil", "nil"
    var = "rfc4122" if h[16] in "89ab" else ("ncs" if h[16] in "01234567" else ("microsoft" if h[16] in "cd" else "future"))
    return "v" + h[12], var


def uuid_time_ms(s):
    h = s.replace("-", "")
    ver = h[12]
    if ver == "7":
        return float(int(h[:12], 16)), "ms"
    if ver == "1":
        t = ((int(h[13:16], 16)) << 48) | (int(h[8:12], 16) << 32) | int(h[0:8], 16)
        return (t - 0x01B21DD213814000) / 1e4, "ms"
    return None, None


def decode(fam, s):
    """-> (embedded_ms or None, resolution 'ms'|'s'|'day'|'mod36', info dict)."""
    if fam in ("anthropic_req", "anthropic_msg", "anthropic_toolu", "anthropic_srvtoolu", "anthropic_toolu_callwrapped"):
        body = s.rsplit("_", 1)[1]
        v = b58(body[2:])
        top = v >> 80
        tp = WIN_LO <= top < WIN_HI
        return (float(top) if tp else None), "ms", {"time_format": tp, "v": v}
    if fam == "openai_item_hex":
        b = s.split("_", 1)[1]
        if len(b) == 48:
            return float(int(b[:8], 16)) * 1000.0, "s", {"layout": "hex48_time_first"}
        if len(b) == 50 and b[16] == "0":
            return float(int(b[18:26], 16)) * 1000.0, "s", {"layout": f"hex50_prefix16_{b[16:18]}_time"}
        return None, "s", {"layout": "hex50_other"}
    if fam == "msg_datetime14":
        try:
            t = pd.Timestamp(f"{s[4:8]}-{s[8:10]}-{s[10:12]}T{s[12:14]}:{s[14:16]}:{s[16:18]}", tz="UTC")
        except ValueError:
            return None, "s", {}
        return float((t - EPOCH) // pd.Timedelta(milliseconds=1)), "s", {"read_as": "UTC wall clock"}
    if fam == "opencode_id":
        pre, rest = s.split("_", 1)
        x = int(rest[:12], 16)
        if pre == "ses":
            x = (~x) & ((1 << 48) - 1)
        return float(x >> 12), "mod36", {"counter": x & 0xFFF, "prefix": pre}
    if fam == "gemini_cli_call":
        m = re.search(r"[_-](\d{13})[_-]([0-9a-z]+)$", s)
        return float(m.group(1)), "ms", {"suffix": m.group(2)}
    if fam == "gemini_response_id":
        try:
            b = base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
        except Exception:
            return None, "s", {}
        if len(b) < 4:
            return None, "s", {}
        return float(int.from_bytes(b[:4], "little")) * 1000.0, "s", {"nbytes": len(b), "bytes": b}
    if fam == "chatcmpl_ms":
        return float(s[9:]), "ms", {}
    if fam == "uuid":
        t, r = uuid_time_ms(s)
        return t, r, {}
    if fam == "uuid_dated":
        return float((pd.Timestamp(s[:10], tz="UTC") - EPOCH) // pd.Timedelta(milliseconds=1)), "day", {}
    return None, None, {}


def wrapdiff36(a_ms, b_mod):
    mod = 1 << 36
    d = (int(round(a_ms)) - int(b_mod)) % mod
    return float(d if d < mod // 2 else d - mod)


def band_counts(off):
    off = np.asarray(off, dtype=float)
    c, _ = np.histogram(off, bins=BANDS)
    return dict(zip(BAND_NAMES, [int(x) for x in c]))


def dist(x):
    return stats.describe(np.asarray(x, dtype=float), qs=(0.0, 0.001, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 0.999, 1.0))


def rate_by_session(flag, sess):
    df = pd.DataFrame({"f": np.asarray(flag, dtype=float), "s": np.asarray(sess)})
    g = df.groupby("s")["f"]
    return stats.cluster_rate(g.sum().values, g.size().values)


def offset_block(off, sess, res, private=False, quantile_ci=True):
    off = np.asarray(off, dtype=float)
    sess = np.asarray(sess)
    ok = ~np.isnan(off)
    off, sess = off[ok], sess[ok]
    tol = TOL.get(res, 2000.0)
    out = {"n": int(len(off)), "n_sessions": int(len(set(sess))), "resolution": res, "tol_ms": tol}
    if len(off) == 0:
        return out
    out["bands"] = band_counts(off)
    out["describe_ms"] = dist(off)
    out["violation_count"] = int((off < -tol).sum())
    out["violation_sessions"] = int(len(set(sess[off < -tol])))
    out["gross_violation_count"] = int((off < -60000).sum())
    out["far_count"] = int((off > 600000).sum())
    out["agreement_count"] = int(((off >= -tol) & (off <= 600000)).sum())
    out["violation_rate"] = rate_by_session(off < -tol, sess)
    out["agreement_rate"] = rate_by_session((off >= -tol) & (off <= 600000), sess)
    if quantile_ci and len(off) >= 5:
        sub = np.arange(len(off))
        if len(off) > 60000:  # bootstrap cost: the CI is computed on a fixed-seed subsample of whole sessions
            rng = np.random.default_rng(stats.SEED)
            us = np.unique(sess)
            keep = set(rng.choice(us, size=max(1, int(len(us) * 60000 / len(off))), replace=False))
            sub = np.array([i for i in range(len(off)) if sess[i] in keep])
            out["median_ci_on_session_subsample"] = int(len(sub))
        out["median_ms"] = stats.cluster_quantile(off[sub], sess[sub], 0.5)
    return out


# ---------------------------------------------------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------------------------------------------------
ID_COLS = ["call_id", "api_msg_id", "request_id", "uuid", "parent_uuid", "agent_id", "parent_call_id"]
BASE_COLS = ["session_id", "seq", "kind", "ts", "stratum", "is_subagent", "tool_raw", "model"]


def load_ids(corpus, split):
    path = CACHE / f"{corpus}_{split}.parquet"
    cols = BASE_COLS + ID_COLS + ["extra"]
    pf = pq.ParquetFile(path)
    parts = []
    for i in range(pf.num_row_groups):
        t = pf.read_row_group(i, columns=cols).to_pandas()
        ex = t["extra"].fillna("")
        t["x_provider_call_id"] = ex.str.extract(r'"provider_call_id":"([^"]*)"')[0]
        t["x_source_call_id"] = ex.str.extract(r'"source_call_id":"([^"]*)"')[0]
        t["x_synthetic"] = ex.str.extract(r'"synthetic":"([^"]*)"')[0]
        t = t.drop(columns=["extra"])
        parts.append(t)
    df = pd.concat(parts, ignore_index=True)
    if corpus == "swechat":
        pop = pd.read_parquet(CACHE / "swechat_population.parquet", columns=["session_id", "format"])
        df = df.merge(pop, on="session_id", how="left")
        df["sub"] = df["format"].fillna("unknown")
    elif corpus == "aiv_cu":
        df["sub"] = df["stratum"]
    else:
        df["sub"] = corpus
    df["ms"] = to_ms(df["ts"])
    return df


# ---------------------------------------------------------------------------------------------------------------------
# P1 census
# ---------------------------------------------------------------------------------------------------------------------
CENSUS_COLS = ID_COLS + ["session_id", "x_provider_call_id", "x_source_call_id"]


def census(df, corpus):
    out = {}
    fam_cache = {}
    for col in CENSUS_COLS:
        if col not in df:
            continue
        sub = df[df[col].notna()][list(dict.fromkeys([col, "session_id", "sub"]))]
        if len(sub) == 0:
            continue
        uniq = pd.unique(sub[col])
        fmap = {u: classify(u, corpus, col) for u in uniq}
        fam_cache[col] = fmap
        sub = sub.assign(fam=sub[col].map(fmap))
        colout = {}
        for (sg, fam), g in sub.groupby(["sub", "fam"]):
            vals = list(pd.unique(g[col]))
            lens = Counter(len(v) for v in vals)
            rec = {"rows": int(len(g)), "distinct": int(len(vals)), "sessions": int(g.session_id.nunique()),
                   "length_hist_top": [[int(k), int(c)] for k, c in lens.most_common(6)],
                   "n_degenerate_distinct": int(sum(is_degenerate(v) for v in vals))}
            if fam not in ("loader_synthetic", "redacted"):
                rec["positional_entropy"] = positional_entropy(vals)
            if fam in ("uuid", "uuid_dated", "sdk_run", "call_uuid_n"):
                vc, varc = Counter(), Counter()
                for v in vals:
                    m = re.search(UUID_RE, v)
                    ver, var = uuid_version(m.group(0))
                    vc[ver] += 1
                    varc[var] += 1
                rec["uuid_versions"] = dict(vc)
                rec["uuid_variants"] = dict(varc)
            if fam in ("anthropic_toolu", "anthropic_msg", "anthropic_req", "anthropic_srvtoolu"):
                pc = Counter(re.match(r"^([a-z]+_(?:vrtx_|bdrk_)?)", v).group(1) for v in vals)
                rec["prefix_counts"] = dict(pc)
            if fam == "openai_item_hex":
                rec["prefix_counts"] = dict(Counter(v.split("_", 1)[0] + "|" + str(len(v.split("_", 1)[1])) for v in vals))
            if fam == "opencode_id":
                rec["prefix_counts"] = dict(Counter(v.split("_", 1)[0] for v in vals))
            if fam == "zeroed_provider_id":
                rec["prefix_counts"] = dict(Counter(v.split("_", 1)[0] for v in vals))
            colout.setdefault(sg, {})[fam] = rec
        out[col] = colout
    return out, fam_cache


# ---------------------------------------------------------------------------------------------------------------------
# P2 embedded clocks
# ---------------------------------------------------------------------------------------------------------------------
DECODABLE = {"anthropic_req", "anthropic_msg", "anthropic_toolu", "anthropic_srvtoolu", "anthropic_toolu_callwrapped",
             "openai_item_hex", "opencode_id", "gemini_cli_call", "gemini_response_id", "chatcmpl_ms", "uuid", "uuid_dated",
             "msg_datetime14"}
SERVER_MINTED = {"anthropic_req", "anthropic_msg", "openai_item_hex", "gemini_response_id"}


def id_events(df, corpus, fam_cache):
    """One row per (column, session, id value) for decodable families: first seq, event ms, embedded ms, resolution."""
    rows = []
    sess_first = df.groupby("session_id")["ms"].min()
    for col in ["call_id", "api_msg_id", "request_id", "uuid", "agent_id", "session_id"]:
        fmap = fam_cache.get(col, {})
        dec_vals = {v for v, f in fmap.items() if f in DECODABLE}
        if not dec_vals:
            continue
        sub = df[df[col].isin(dec_vals)]
        if col == "session_id":
            g = sub.groupby("session_id").agg(seq=("seq", "min"), ms=("ms", "min"), sub=("sub", "first"),
                                              is_subagent=("is_subagent", "first"), kind=("kind", "first"))
            g = g.reset_index()
            g["value"] = g["session_id"]
        elif col == "agent_id":
            g = sub.groupby(["session_id", col]).agg(seq=("seq", "min"), ms=("ms", "min"), sub=("sub", "first"),
                                                     is_subagent=("is_subagent", "first"), kind=("kind", "first")).reset_index()
            g = g.rename(columns={col: "value"})
        else:
            s2 = sub.sort_values(["session_id", "seq"]).drop_duplicates(["session_id", col])
            keep = ["session_id", col, "seq", "ms", "sub", "is_subagent", "kind"] + [c for c in ("agent_id", "uuid") if c != col]
            g = s2[keep].rename(columns={col: "value"})
            if col == "uuid":
                g["uuid"] = g["value"]
        g = g.assign(column=col, fam=g["value"].map(fmap))
        dec = [decode(f, v) for f, v in zip(g["fam"], g["value"])]
        g["emb_ms"] = [d[0] for d in dec]
        g["res"] = [d[1] for d in dec]
        g["info"] = [d[2] for d in dec]
        rows.append(g)
    if not rows:
        return pd.DataFrame()
    E = pd.concat(rows, ignore_index=True)
    E["opencode_prefix"] = [i.get("prefix") if isinstance(i, dict) else None for i in E["info"]]
    off = []
    for fam, res, ms, emb in zip(E["fam"], E["res"], E["ms"], E["emb_ms"]):
        if emb is None or (isinstance(emb, float) and math.isnan(emb)) or ms is None or math.isnan(ms):
            off.append(np.nan)
        elif res == "mod36":
            off.append(wrapdiff36(ms, emb))
        else:
            off.append(ms - emb)
    E["off"] = off
    return E


def p2_offsets(E, corpus):
    out = {}
    if E.empty:
        return out
    E = E.copy()
    E["key"] = E["column"] + "|" + E["fam"] + E["opencode_prefix"].fillna("").map(lambda p: ":" + p if p else "")
    for (key, sg), g in E.groupby(["key", "sub"]):
        fam = g["fam"].iloc[0]
        rec = {"n_ids": int(len(g))}
        if fam in ("anthropic_req", "anthropic_msg", "anthropic_toolu", "anthropic_srvtoolu", "anthropic_toolu_callwrapped"):
            tf = np.array([i.get("time_format", False) for i in g["info"]])
            rec["n_time_format"] = int(tf.sum())
            rec["n_random_format"] = int((~tf).sum())
            rec["expected_chance_time_plausible"] = float(len(g) * (WIN_HI - WIN_LO) / 2 ** 48)
            g = g[tf]
            # time-format ids whose offset is far beyond any latency: consistent with a random-format id landing in the window
            rec["n_time_format_abs_offset_gt_1day"] = int((g["off"].abs() > 86400000).sum())
            if len(g):
                gi = g.sort_values(["value", "session_id"]).drop_duplicates("value")
                rec["including_abs_offset_gt_1day"] = offset_block(gi["off"].values, gi["session_id"].values, "ms", quantile_ci=False)
            g = g[g["off"].abs() <= 86400000]
        if fam == "uuid":
            vc = Counter(uuid_version(v)[0] for v in g["value"])
            rec["uuid_versions"] = dict(vc)
            g = g[g["emb_ms"].notna()]
        if fam == "openai_item_hex":
            rec["layouts"] = dict(Counter(i.get("layout") for i in g["info"]))
        if g.empty or g["off"].notna().sum() == 0:
            out.setdefault(key, {})[sg] = rec
            continue
        # global de-dup on id value (copies across sessions)
        gd = g.sort_values(["value", "session_id"]).drop_duplicates("value")
        rec["n_copies_removed"] = int(len(g) - len(gd))
        res = gd["res"].iloc[0]
        if res == "day":
            d = (gd["off"] / 86400000.0)
            rec["day_offset_counts"] = {str(k): int(v) for k, v in Counter(np.floor(d).astype(int)).most_common(10)}
            rec["n_day_mismatch"] = int((np.floor(d) != 0).sum())
            rec["n"] = int(len(gd))
        else:
            rec.update(offset_block(gd["off"].values, gd["session_id"].values, "ms" if res == "mod36" else res))
            if fam == "msg_datetime14":
                # wall-clock ids: split the offset into whole hours (timezone) and the residual
                hrs = np.round(gd["off"].values / 3600000.0)
                rec["whole_hour_component_counts"] = {str(int(k)): int(v) for k, v in Counter(hrs).items()}
                resid = gd["off"].values - hrs * 3600000.0
                rec["residual_after_whole_hours"] = offset_block(resid, gd["session_id"].values, "s")
            if "kind" in gd:
                rec["first_event_kind_counts"] = dict(Counter(gd["kind"].fillna("none")))
            if gd["is_subagent"].notna().any():
                for flag, gg in gd.groupby(gd["is_subagent"].fillna(False).astype(bool)):
                    rec.setdefault("by_is_subagent", {})[str(flag)] = offset_block(gg["off"].values, gg["session_id"].values,
                                                                                  "ms" if res == "mod36" else res, quantile_ci=False)
        out.setdefault(key, {})[sg] = rec
    return out


def p2b_order(E):
    out = {}
    if E.empty:
        return out
    E = E[E["off"].notna() & E["column"].isin(["call_id", "api_msg_id", "request_id", "uuid"])].copy()
    anth = E["fam"].str.startswith("anthropic_")
    E = E[~anth | (E["off"].abs() <= 86400000)]
    if E.empty:
        return out
    E["key"] = E["column"] + "|" + E["fam"] + E["opencode_prefix"].fillna("").map(lambda p: ":" + p if p else "")
    for (key, sg), g in E.groupby(["key", "sub"]):
        res = g["res"].iloc[0]
        tol = TOL.get(res, 2000.0)
        id_ms = (g["ms"] - g["off"]).values  # embedded time on the event's own scale (handles mod36)
        stream = np.where(g["is_subagent"].fillna(False).astype(bool), g["agent_id"].fillna("?").astype(str), "main")             if "agent_id" in g else np.array(["main"] * len(g))
        g = g.assign(id_ms=id_ms, stream=stream).sort_values(["session_id", "stream", "seq"])
        same = (g["session_id"].values[1:] == g["session_id"].values[:-1]) & (g["stream"].values[1:] == g["stream"].values[:-1])
        did = np.diff(g["id_ms"].values)[same]
        dts = np.diff(g["ms"].values)[same]
        ok = ~np.isnan(did) & ~np.isnan(dts)
        did, dts = did[ok], dts[ok]
        idinv = did < -tol
        tsinv = dts < -2000
        out.setdefault(key, {})[sg] = {"unit": "consecutive ids within one stream (session x agent_id-or-main)",
                                       "n_pairs": int(len(did)), "id_inversions": int(idinv.sum()),
                                       "ts_inversions": int(tsinv.sum()), "both": int((idinv & tsinv).sum()),
                                       "id_only": int((idinv & ~tsinv).sum()), "ts_only": int((~idinv & tsinv).sum()),
                                       "id_strict_decrease_any": int((did < 0).sum()), "tol_ms": tol}
    return out


def p2c_bracket(df, E, corpus):
    """Skew bracket for server-minted ids (CC request ids; aiv_cu provider message ids)."""
    out = {}
    if E.empty:
        return out
    if corpus in ("swechat", "cc_local", "aiv_cc"):
        R = E[(E["column"] == "request_id") & (E["fam"] == "anthropic_req") & E["emb_ms"].notna()].copy()
        if R.empty:
            return out
        R = R[(R["off"].abs() <= 86400000)]
        inp = df[df["kind"].isin(["result", "user"]) & df["ms"].notna()][["session_id", "seq", "ms", "agent_id", "is_subagent", "sub"]].copy()
        inp["stream"] = np.where(inp["is_subagent"].fillna(False).astype(bool), inp["agent_id"].fillna("?"), "main")
        R["stream"] = np.where(R["is_subagent"].fillna(False).astype(bool), R["agent_id"].fillna("?"), "main")
        R = R.sort_values("seq")
        inp = inp.sort_values("seq")
        M = pd.merge_asof(R, inp[["session_id", "stream", "seq", "ms"]].rename(columns={"ms": "prev_ms", "seq": "prev_seq"}),
                          left_on="seq", right_on="prev_seq", by=["session_id", "stream"], direction="backward",
                          allow_exact_matches=False)
        M["lo"] = M["prev_ms"] - M["emb_ms"]
        M["hi"] = M["ms"] - M["emb_ms"]
        tol = TOL["ms"]
    elif corpus == "aiv_cu":
        R = E[(E["column"] == "api_msg_id") & E["fam"].isin(SERVER_MINTED) & E["emb_ms"].notna()].copy()
        if R.empty:
            return out
        R = R[(R["off"].abs() <= 86400000)]
        rows = df[df["ms"].notna()].groupby(["session_id", "uuid"]).agg(rseq=("seq", "min"), rms=("ms", "max")).reset_index()
        # key each response on the first seq of its OWN row, so the previous row is a different row (uuid = row id)
        R = R.merge(rows[["session_id", "uuid", "rseq"]].rename(columns={"rseq": "own_rseq"}), on=["session_id", "uuid"], how="left")
        R = R[R["own_rseq"].notna()].copy()
        R["own_rseq"] = R["own_rseq"].astype("int64")
        rows = rows.sort_values("rseq")
        R = R.sort_values("own_rseq")
        M = pd.merge_asof(R, rows[["session_id", "rseq", "rms"]].rename(columns={"rms": "prev_ms"}), left_on="own_rseq",
                          right_on="rseq", by="session_id", direction="backward", allow_exact_matches=False)
        M["stream"] = "main"
        M["lo"] = M["prev_ms"] - M["emb_ms"]
        M["hi"] = M["ms"] - M["emb_ms"]
        tol = None
    else:
        return out
    for (sg, fam), g in M.groupby(["sub", "fam"]):
        res = g["res"].iloc[0]
        t = tol if tol is not None else TOL[res]
        rec = {"n_responses": int(len(g)), "n_with_prev_input": int(g["prev_ms"].notna().sum()), "tol_ms": t,
               "hi_lt_-tol": int((g["hi"] < -t).sum()), "lo_gt_hi_plus_tol_single_response": int((g["lo"] > g["hi"] + t).sum()),
               "lo_describe_ms": dist(g["lo"].dropna()), "hi_describe_ms": dist(g["hi"].dropna())}
        st = g.groupby(["session_id", "stream"]).agg(L=("lo", "max"), U=("hi", "min"), n=("hi", "size"),
                                                     main=("stream", lambda s: s.iloc[0] == "main"))
        st = st[st["n"] >= 2]
        gap = (st["L"] - st["U"]).dropna()
        rec["streams_ge2_responses"] = int(len(st))
        rec["streams_inconsistent"] = int((gap > t).sum())
        rec["streams_inconsistent_main"] = int((gap[st.loc[gap.index, "main"]] > t).sum())
        rec["streams_main"] = int(st["main"].sum())
        rec["L_minus_U_describe_ms"] = dist(gap)
        ss = gap.reset_index()
        rec["inconsistent_rate_by_session"] = rate_by_session((ss[0] > t).values, ss["session_id"].values) if len(ss) else None
        # implied skew interval width for consistent streams
        rec["U_minus_L_consistent_describe_ms"] = dist((-gap[gap <= t]))
        rec["_inconsistent_sessions"] = sorted(set(ss.loc[ss[0] > t, "session_id"])) if len(ss) else []
        rec["_hi_violation_sessions"] = sorted(set(g.loc[g["hi"] < -t, "session_id"]))
        out.setdefault(fam, {})[sg] = rec
    return out


def p2d_floor(E):
    out = {}
    S = E[E["fam"].isin(SERVER_MINTED) & E["off"].notna() & (E["off"].abs() <= 86400000)
          & E["column"].isin(["request_id", "api_msg_id"])]
    for (fam, sg), g in S.groupby(["fam", "sub"]):
        floors, drifts, n_ok = [], [], 0
        sess_floor = []
        for sid, gs in g.groupby("session_id"):
            if len(gs) < 20:
                continue
            gs = gs.sort_values("seq")
            floors.append(float(gs["off"].min()))
            sess_floor.append(sid)
            h = len(gs) // 2
            a, b = gs["off"].values[:h], gs["off"].values[h:]
            if len(a) >= 10 and len(b) >= 10:
                drifts.append(float(b.min() - a.min()))
        floors = np.array(floors)
        drifts = np.array(drifts)
        res = g["res"].iloc[0]
        t = TOL[res]
        out.setdefault(fam, {})[sg] = {
            "n_sessions_ge20": int(len(floors)), "floor_describe_ms": dist(floors) if len(floors) else None,
            "sessions_floor_lt_-tol": int((floors < -t).sum()), "sessions_floor_lt_0": int((floors < 0).sum()),
            "n_sessions_drift": int(len(drifts)), "drift_describe_ms": dist(drifts) if len(drifts) else None,
            "drift_abs_gt_tol": int((np.abs(drifts) > t).sum()), "drift_abs_gt_10s": int((np.abs(drifts) > 10000).sum()),
            "tol_ms": t}
    return out


def p2e_bits(E):
    out = {}
    for fam in ["anthropic_req", "anthropic_msg", "anthropic_toolu"]:
        g = E[E["fam"] == fam].drop_duplicates("value")
        if g.empty:
            continue
        for tf_name, sel in [("time_format", True), ("random_format", False)]:
            gg = g[[bool(i.get("time_format")) == sel for i in g["info"]]]
            n = len(gg)
            if n < 1000:
                out.setdefault(fam, {})[tf_name] = {"n": n}
                continue
            vs = [i["v"] for i in gg["info"]]
            nb = 80 if sel else 128
            p1 = [sum((v >> b) & 1 for v in vs) / n for b in range(nb)]
            biased = [b for b, p in enumerate(p1) if abs(p - 0.5) > 0.05]
            # RFC 9562 field positions inside a 128-bit value (lsb0): version = bits 76-79, variant = bits 62-63
            vv = Counter(((v >> 76) & 0xF, (v >> 62) & 0x3) for v in vs)
            uu = {"version_variant_top": [[f"v{a}|var{b}", int(c)] for (a, b), c in vv.most_common(6)],
                  "n_version4_variant2": int(vv.get((4, 2), 0)), "n_version7_variant2": int(vv.get((7, 2), 0)),
                  "expected_each_if_uniform": n / 64.0}
            if sel:
                ra = Counter(((v >> 64) & 0xFFF) >> 8 for v in vs)  # top 4 bits of the 12-bit rand_a field
                uu["rand_a_top4_hist"] = {str(k): int(c) for k, c in sorted(ra.items())}
            out.setdefault(fam, {})[tf_name] = {"n": n, "n_low_bits_tested": nb, "n_biased_bits": len(biased),
                                                "biased_bit_positions_lsb0": biased[:40],
                                                "biased_bit_p1": [round(p1[b], 4) for b in biased[:40]],
                                                "uuid_fields": uu,
                                                "p1_min": round(min(p1), 4), "p1_max": round(max(p1), 4),
                                                "bit_length_hist_top": [[int(k), int(c)] for k, c in Counter(v.bit_length() for v in vs).most_common(4)]}
    g = E[E["fam"] == "gemini_response_id"].drop_duplicates("value")
    if len(g):
        bs = [i.get("bytes") for i in g["info"] if i.get("bytes") is not None]
        L = Counter(len(b) for b in bs)
        Lm = L.most_common(1)[0][0]
        bs = [b for b in bs if len(b) == Lm]
        per = []
        for k in range(Lm):
            c = Counter(b[k] for b in bs)
            n = len(bs)
            per.append({"byte": k, "distinct": len(c), "entropy_bits": round(-sum((x / n) * math.log2(x / n) for x in c.values()), 3)})
        out["gemini_response_id_bytes"] = {"n": len(bs), "length_hist": dict(L), "per_byte": per}
    g = E[E["fam"] == "openai_item_hex"].drop_duplicates("value")
    if len(g):
        rec = {}
        for lay, gg in g.groupby(g["info"].map(lambda i: i.get("layout"))):
            bodies = [v.split("_", 1)[1] for v in gg["value"]]
            if lay == "hex48_time_first":
                seg = Counter(b[32:48] for b in bodies)
                seg_s = gg.assign(seg=[b[32:48] for b in bodies]).groupby("session_id")["seg"].nunique()
                rec[lay] = {"n": len(bodies), "distinct_last16hex": len(seg), "top_last16hex_share": round(seg.most_common(1)[0][1] / len(bodies), 4),
                            "sessions": int(gg.session_id.nunique()), "sessions_with_1_last16hex": int((seg_s == 1).sum())}
            elif lay == "hex50_prefix16_00_time":
                seg = Counter(b[:16] for b in bodies)
                seg_s = gg.assign(seg=[b[:16] for b in bodies]).groupby("session_id")["seg"].nunique()
                sess_per_seg = gg.assign(seg=[b[:16] for b in bodies]).groupby("seg")["session_id"].nunique()
                rec[lay] = {"n": len(bodies), "distinct_first16hex": len(seg), "sessions": int(gg.session_id.nunique()),
                            "first16hex_per_session_describe": stats.describe(seg_s.values),
                            "sessions_per_first16hex_describe": stats.describe(sess_per_seg.values),
                            "first16hex_in_gt1_session": int((sess_per_seg > 1).sum())}
        out["openai_item_hex_segments"] = rec
    return out


def anth_struct(i):
    """Structure label of a decoded Anthropic id: uuid7 = time-format with version 7 / variant 2; uuid4 = version 4 /
    variant 2 (1/64 of uniform random values carry it by chance); other = neither."""
    v = i.get("v")
    if v is None:
        return "undecoded"
    ver, var = (v >> 76) & 0xF, (v >> 62) & 0x3
    if i.get("time_format") and ver == 7 and var == 2:
        return "uuid7_time"
    if ver == 4 and var == 2:
        return "uuid4_shape"
    return "time_plausible_other" if i.get("time_format") else "other"


def p2f_epochs(E, corpus):
    out = {}
    if corpus in PRIVATE:
        # aggregate only: no months
        for fam in ["anthropic_msg", "anthropic_req", "anthropic_toolu"]:
            g = E[E["fam"] == fam].drop_duplicates("value")
            if len(g):
                out[fam] = {"n": int(len(g)), **{k: int(v) for k, v in Counter(g["info"].map(anth_struct)).items()}}
        return out
    for fam in ["anthropic_msg", "anthropic_req", "anthropic_toolu", "openai_item_hex"]:
        g = E[E["fam"] == fam].drop_duplicates("value")
        if g.empty:
            continue
        month = pd.to_datetime(g["ms"], unit="ms", utc=True).dt.strftime("%Y-%m")
        if fam == "openai_item_hex":
            lab = g["info"].map(lambda i: i.get("layout"))
        else:
            lab = g["info"].map(anth_struct)
        ct = pd.crosstab(month, lab)
        out[fam] = {m: {k: int(v) for k, v in row.items()} for m, row in ct.iterrows()}
        if fam in ("anthropic_msg", "anthropic_toolu", "anthropic_req"):
            st = g["info"].map(anth_struct)
            tf = g[st.values == ("uuid4_shape" if fam == "anthropic_toolu" else "uuid7_time")]
            rf = g[st.values == "other"]
            out[fam + "_switch"] = {
                "new_structure": "uuid4_shape" if fam == "anthropic_toolu" else "uuid7_time",
                "first_new_structure_event_utc": str(pd.to_datetime(tf["ms"].min(), unit="ms", utc=True)) if len(tf) else None,
                "last_other_structure_event_utc": str(pd.to_datetime(rf["ms"].max(), unit="ms", utc=True)) if len(rf) else None,
                "new_structure_events_before_last_other": int((tf["ms"] < rf["ms"].max()).sum()) if len(tf) and len(rf) else 0,
                "other_structure_events_after_first_new": int((rf["ms"] > tf["ms"].min()).sum()) if len(tf) and len(rf) else 0}
    return out


def p2g_counters(df, E, corpus, fam_cache):
    out = {}
    # OpenCode counter (low 12 bits) and Gemini CLI suffix
    if not E.empty:
        oc = E[E["fam"] == "opencode_id"]
        if len(oc):
            for pre, g in oc.groupby("opencode_prefix"):
                out.setdefault("opencode_counter_low12", {})[pre] = dict(Counter(int(i["counter"]) for i in g["info"]).most_common(8))
        gc = E[E["fam"] == "gemini_cli_call"]
        if len(gc):
            out["gemini_cli_call_suffix"] = dict(Counter(i["suffix"] if len(i["suffix"]) < 4 else "hex" for i in gc["info"]).most_common(8))
    # integer-suffixed provider call ids: sequence behaviour within a session (calls in seq order)
    fmap = fam_cache.get("call_id", {})
    calls = df[(df["kind"] == "call") & df["call_id"].notna()]
    calls = calls.assign(fam=calls["call_id"].map(fmap))
    for fam in ["tool_counter", "call_decimal", "call_uuid_n"]:
        g = calls[calls["fam"] == fam].sort_values(["session_id", "seq"])
        if g.empty:
            continue
        n = g["call_id"].str.extract(r"(\d+)$")[0].astype(float)
        g = g.assign(n=n.values)
        same = g["session_id"].values[1:] == g["session_id"].values[:-1]
        d = np.diff(g["n"].values)[same]
        sg_counts = dict(Counter(g["sub"]))
        rec = {"n_calls": int(len(g)), "n_sessions": int(g.session_id.nunique()), "by_sub": sg_counts,
               "consecutive_pairs": int(len(d)), "step_plus1": int((d == 1).sum()), "step_0": int((d == 0).sum()),
               "step_gt1": int((d > 1).sum()), "step_negative": int((d < 0).sum()),
               "value_describe": stats.describe(g["n"].values)}
        # ordinal agreement: the integer vs the call's 0-based ordinal among calls of the session
        ordn = g.groupby("session_id").cumcount().values
        rec["eq_ordinal"] = int((g["n"].values == ordn).sum())
        rec["eq_ordinal_plus1"] = int((g["n"].values == ordn + 1).sum())
        sp = []
        for sid, gs in g.groupby("session_id"):
            if len(gs) >= 5 and gs["n"].nunique() > 1:
                sp.append(pd.Series(gs["n"].values).corr(pd.Series(np.arange(len(gs))), method="spearman"))
        rec["spearman_n_vs_order_per_session"] = stats.describe(np.array(sp)) if sp else None
        out[fam] = rec
    return out


def p2h_req_msg(df, corpus):
    """CC formats: request_id <-> api_msg_id pairing on the same events, and server-side gap msg_time - req_time."""
    x = df[df["request_id"].notna() & df["api_msg_id"].notna()][["session_id", "request_id", "api_msg_id", "sub", "ms"]]
    if x.empty:
        return {}
    out = {}
    for sg, g in x.groupby("sub"):
        pr = g.drop_duplicates(["session_id", "request_id", "api_msg_id"])
        a = pr.groupby(["session_id", "request_id"])["api_msg_id"].nunique()
        b = pr.groupby(["session_id", "api_msg_id"])["request_id"].nunique()
        rec = {"pairs": int(len(pr)), "requests": int(len(a)), "requests_with_gt1_msg_id": int((a > 1).sum()),
               "msg_ids": int(len(b)), "msg_ids_with_gt1_request_id": int((b > 1).sum())}
        fr = pr["request_id"].map(lambda v: classify(v))
        fm = pr["api_msg_id"].map(lambda v: classify(v))
        both = pr[(fr == "anthropic_req") & (fm == "anthropic_msg")]
        d, sess = [], []
        rec["pairs_by_structure"] = {}
        for r_, m_, sid in zip(both["request_id"], both["api_msg_id"], both["session_id"]):
            tr, _, ir = decode("anthropic_req", r_)
            tm, _, im = decode("anthropic_msg", m_)
            k = anth_struct(ir) + "|" + anth_struct(im)
            rec["pairs_by_structure"][k] = rec["pairs_by_structure"].get(k, 0) + 1
            if anth_struct(ir) == "uuid7_time" and anth_struct(im) == "uuid7_time":
                d.append(tm - tr)
                sess.append(sid)
        if d:
            d = np.array(d)
            rec["msg_minus_req_ms"] = {"n": int(len(d)), "n_sessions": int(len(set(sess))), "describe": dist(d),
                                       "negative": int((d < 0).sum()), "zero": int((d == 0).sum()),
                                       "median": stats.cluster_quantile(d, np.array(sess), 0.5)}
        out[sg] = rec
    return out


# ---------------------------------------------------------------------------------------------------------------------
# P3 reuse / collisions
# ---------------------------------------------------------------------------------------------------------------------
def p3_reuse(df, corpus, fam_cache):
    out = {}
    for col in ["call_id", "api_msg_id", "request_id", "uuid", "agent_id", "x_provider_call_id"]:
        if col not in df:
            continue
        sub = df[df[col].notna()][[col, "session_id", "sub"]]
        if sub.empty:
            continue
        fmap = fam_cache.get(col) or {u: classify(u, corpus, col) for u in pd.unique(sub[col])}
        sub = sub.assign(fam=sub[col].map(fmap))
        sub = sub[~sub["fam"].isin(["loader_synthetic"])]
        ps = sub.drop_duplicates([col, "session_id"])
        nsess = ps.groupby(col)["session_id"].size()
        rec = {}
        for (sg, fam), g in ps.groupby(["sub", "fam"]):
            ns = nsess.loc[pd.unique(g[col])]
            n_pairs = int(len(g))
            H = positional_entropy(list(pd.unique(g[col]))).get("entropy_bits_sum", 0.0)
            rec.setdefault(sg, {})[fam] = {
                "distinct": int(len(ns)), "session_value_pairs": n_pairs, "values_in_gt1_session": int((ns > 1).sum()),
                "max_sessions_per_value": int(ns.max()) if len(ns) else 0,
                "positional_entropy_bits": H,
                "birthday_expected_collisions_if_random": float(n_pairs * (n_pairs - 1) / 2 / (2 ** H)) if H and H < 1000 else None}
        out[col] = rec
    return out


def p3b_copies(df, corpus):
    """Entry uuids present in more than one session (resumed/forked copies): timestamp agreement between copies, and
    for request ids present in more than one session, which copy agrees with the server-minted request-id clock."""
    out = {}
    u = df[df["uuid"].notna() & ~df["uuid"].astype(str).str.match(r"^(?:synthetic:|turn:|step:)")
           & ~df["uuid"].astype(str).str.contains("REDACTED", regex=False)]
    u = u.sort_values("seq").drop_duplicates(["uuid", "session_id"])
    vc = u["uuid"].value_counts()
    sh = u[u["uuid"].isin(set(vc[vc > 1].index))].sort_values(["uuid", "session_id"])
    if sh.empty:
        out["shared_uuids"] = 0
    else:
        g = sh.groupby("uuid").agg(s1=("session_id", "first"), s2=("session_id", "last"), t1=("ms", "first"),
                                   t2=("ms", "last"), n=("session_id", "size"))
        g["d"] = g["t2"] - g["t1"]
        pairs = g.groupby(["s1", "s2"]).agg(n=("d", "size"), n_ts_diff=("d", lambda x: int((x != 0).sum())),
                                            n_distinct_diff=("d", "nunique"), dmin=("d", "min"), dmax=("d", "max"))
        out["shared_uuids"] = int(len(g))
        out["shared_uuids_in_gt2_sessions"] = int((g["n"] > 2).sum())
        out["shared_uuids_ts_equal"] = int((g["d"] == 0).sum())
        out["shared_uuids_ts_differ"] = int((g["d"] != 0).sum())
        out["ts_diff_describe_ms_nonzero"] = dist(g.loc[g["d"] != 0, "d"].abs())
        out["session_pairs"] = int(len(pairs))
        out["session_pairs_with_any_ts_diff"] = int((pairs["n_ts_diff"] > 0).sum())
        out["_restamped_sessions"] = sorted(set(pairs.index[pairs["n_ts_diff"] > 0].get_level_values(0)) |
                                            set(pairs.index[pairs["n_ts_diff"] > 0].get_level_values(1)))
        if corpus not in PRIVATE:
            out["session_pairs_detail"] = [{"n_shared_uuids": int(r.n), "n_ts_diff": int(r.n_ts_diff),
                                            "n_distinct_diff_values": int(r.n_distinct_diff),
                                            "diff_min_ms": float(r.dmin), "diff_max_ms": float(r.dmax)}
                                           for r in pairs.itertuples()]
    r = df[df["request_id"].notna()].sort_values("seq").drop_duplicates(["request_id", "session_id"])
    vc = r["request_id"].value_counts()
    y = r[r["request_id"].isin(set(vc[vc > 1].index))].copy()
    if len(y):
        y["fam"] = y["request_id"].map(lambda v: classify(v))
        y = y[y["fam"] == "anthropic_req"].copy()
        y["emb"] = [decode("anthropic_req", v)[0] for v in y["request_id"]]
        y["off"] = y["ms"] - y["emb"]
        y["ok"] = y["off"].between(-TOL["ms"], 600000)
        z = y.groupby("request_id").agg(n_ok=("ok", "sum"), n=("ok", "size"))
        cls = np.where(z["n_ok"] == z["n"], "all_copies_agree",
                       np.where(z["n_ok"] == 0, "no_copy_agrees", "some_copies_agree"))
        out["shared_request_ids"] = int(len(z))
        out["shared_request_ids_by_clock_agreement"] = dict(Counter(cls))
        # in the split case: is the disagreeing copy's ts later than the agreeing copy's?
        sp = y[y["request_id"].isin(set(z.index[cls == "some_copies_agree"]))]
        later = 0
        for rid, gg in sp.groupby("request_id"):
            later += int(gg.loc[~gg["ok"], "ms"].min() > gg.loc[gg["ok"], "ms"].max())
        out["split_cases_disagreeing_copy_ts_later"] = int(later)
        out["split_cases_disagreeing_copy_offset_describe_ms"] = dist(sp.loc[~sp["ok"], "off"]) if len(sp) else None
        out["split_cases_agreeing_copy_offset_describe_ms"] = dist(sp.loc[sp["ok"], "off"]) if len(sp) else None
    return out


def p3_within(df, corpus):
    out = {}
    calls = df[(df["kind"] == "call") & df["call_id"].notna()]
    res = df[(df["kind"] == "result") & df["call_id"].notna()]
    for sg in sorted(set(df["sub"])):
        c = calls[calls["sub"] == sg]
        r = res[res["sub"] == sg]
        if c.empty and r.empty:
            continue
        cc = c.groupby(["session_id", "call_id"]).size()
        rc = r.groupby(["session_id", "call_id"]).size()
        ck = set(cc.index)
        rk = set(rc.index)
        sess_c = pd.Series([k[0] for k in cc.index])
        # session-clustered rates
        dup_by_s = pd.Series((cc > 1).values, index=[k[0] for k in cc.index]).groupby(level=0).agg(["sum", "size"])
        nores = pd.Series([k not in rk for k in cc.index], index=[k[0] for k in cc.index]).groupby(level=0).agg(["sum", "size"])
        orph = pd.Series([k not in ck for k in rc.index], index=[k[0] for k in rc.index]).groupby(level=0).agg(["sum", "size"]) if len(rc) else None
        out[sg] = {"distinct_call_keys": int(len(cc)), "call_ids_with_gt1_call_event": int((cc > 1).sum()),
                   "call_ids_with_gt1_result_event": int((rc > 1).sum()), "calls_without_result": int(len(ck - rk)),
                   "results_without_call": int(len(rk - ck)),
                   "dup_call_rate": stats.cluster_rate(dup_by_s["sum"].values, dup_by_s["size"].values),
                   "no_result_rate": stats.cluster_rate(nores["sum"].values, nores["size"].values),
                   "orphan_result_rate": stats.cluster_rate(orph["sum"].values, orph["size"].values) if orph is not None else None}
    return out


# ---------------------------------------------------------------------------------------------------------------------
# P4 text pass (+ P3 copy consistency of cross-session shared uuids / call ids)
# ---------------------------------------------------------------------------------------------------------------------
def nz(x):
    try:
        return None if x is None or pd.isna(x) else x
    except (TypeError, ValueError):
        return x


def md5(s):
    s = nz(s)
    return None if s is None else hashlib.md5(str(s).encode("utf-8", "replace")).hexdigest()[:16]


class TextAcc:
    def __init__(self, corpus):
        self.corpus = corpus
        self.c = Counter()
        self.t6_off = []   # (session, offset, ctx)
        self.t7 = Counter()
        self.t7_off = []   # (session, offset, version)
        self.copy = defaultdict(lambda: defaultdict(list))  # col -> value -> list of (session, tuple)
        self.commit_sub_per_sha = Counter()
        self.pid = Counter()

    def to_json(self):
        j = {"counts": dict(sorted(self.c.items()))}
        if self.t6_off:
            d = pd.DataFrame(self.t6_off, columns=["s", "off", "ctx"])
            j["req_in_text_offsets"] = {ctx: offset_block(g["off"].values, g["s"].values, "ms", quantile_ci=False) for ctx, g in d.groupby("ctx")}
        j["uuid_in_text_versions"] = dict(self.t7)
        if self.t7_off:
            d = pd.DataFrame(self.t7_off, columns=["s", "off", "ver"])
            j["uuid_in_text_time_offsets"] = {v: offset_block(g["off"].values, g["s"].values, "ms", quantile_ci=False) for v, g in d.groupby("ver")}
        return j


def text_pass_chunk(t, acc, shared, all_sessions):
    """t: DataFrame of whole sessions with columns session_id, seq, kind, ts, ms, tool_raw, call_id, args, text, agent_id,
    parent_call_id, is_subagent, uuid, sub."""
    c = acc.c
    # --- P3 copy consistency for shared ids
    for col in ["uuid", "call_id"]:
        S = shared.get(col)
        if not S:
            continue
        sub = t[t[col].isin(S)]
        for (v, sid), g in sub.groupby([col, "session_id"]):
            g = g.sort_values("seq")
            tup = tuple((nz(k), nz(ts), md5(a), md5(x)) for k, ts, a, x in zip(g["kind"], g["ts"], g["args"], g["text"]))
            acc.copy[col][v].append((sid, tup))
    has_text = t["text"].notna()
    res = t[(t["kind"] == "result") & has_text]
    anytext = t[has_text]
    # --- nested agent ids per parent call
    nested = t[t["is_subagent"].fillna(False).astype(bool) & t["parent_call_id"].notna() & t["agent_id"].notna()]
    nest_map = nested.groupby(["session_id", "parent_call_id"])["agent_id"].agg(lambda s: set(s))
    nest_first = nested.groupby(["session_id", "agent_id"])["seq"].min()
    # --- issuance maps: earliest seq at which an id is shown/created in the session; issuer_call keeps the call whose
    # result text announced it (bg task id, agentId), when there is one
    issued = defaultdict(dict)  # session -> id -> (seq, call_id, how)
    issuer_call = defaultdict(dict)

    def issue(sid, x, seq, call_id, how):
        cur = issued[sid].get(x)
        if cur is None or seq < cur[0]:
            issued[sid][x] = (seq, call_id, how)
        if call_id is not None:
            issuer_call[sid].setdefault(x, call_id)
    # T2 agentId in results
    m = res["text"].str.contains(r"agentId: a[0-9a-f]", regex=True, na=False)
    seen_agent = defaultdict(Counter)
    for row in res[m].itertuples():
        for aid in TRX["cc_agent_id_text"].findall(row.text):
            task_tool = row.tool_raw in ("Task", "Agent")
            key = "task_or_agent_tool" if task_tool else "other_tool"
            c[f"T2_agentId_mentions|{key}"] += 1
            if not task_tool:
                continue
            seen_agent[row.session_id][aid] += 1
            ns = nest_map.get((row.session_id, row.call_id))
            if ns is None:
                c["T2_agentId|no_nested_events_for_call"] += 1
            elif aid in ns:
                c["T2_agentId|match" + ("" if len(ns) == 1 else "_multi_agent_ids")] += 1
            else:
                c["T2_agentId|mismatch"] += 1
                # is it the nested id of ANOTHER call in the session?
                other = [k for k, s in nest_map.items() if k[0] == row.session_id and aid in s]
                c["T2_agentId|mismatch_but_nested_under_other_call"] += int(bool(other))
            issue(row.session_id, aid, row.seq, row.call_id, "agentId_text")
    for sid, cnt in seen_agent.items():
        c["T2_agentId_distinct"] += len(cnt)
        c["T2_agentId_reported_by_gt1_result"] += sum(1 for v in cnt.values() if v > 1)
    for (sid, aid), sq in nest_first.items():
        issue(sid, aid, sq, None, "nested_agent_id")
    # T3 background ids
    m = res["text"].str.contains("running in background with ID", regex=False, na=False)
    for row in res[m].itertuples():
        for x in TRX["cc_bg_issue"].findall(row.text):
            c["T3_bg_issued"] += 1
            if x in issuer_call[row.session_id]:
                c["T3_bg_issued_duplicate_in_session"] += 1
            issue(row.session_id, x, row.seq, row.call_id, "bg")
            c[f"T3_bg_id_len|{len(x)}"] += 1
    # T3 todo task ids (TaskCreate)
    todo = defaultdict(dict)
    m = res["tool_raw"].eq("TaskCreate")
    for row in res[m].itertuples():
        mm = TRX["todo_task_create"].match(row.text)
        if mm:
            c["T3b_todo_created"] += 1
            if mm.group(1) in todo[row.session_id]:
                c["T3b_todo_id_reissued_in_session"] += 1
            todo[row.session_id].setdefault(mm.group(1), row.seq)
    # references: call args
    calls = t[(t["kind"] == "call") & t["args"].notna()]
    m = calls["args"].str.contains(r'"(?:task_id|bash_id|shell_id|taskId)"', regex=True, na=False)
    for row in calls[m].itertuples():
        try:
            a = json.loads(row.args)
        except Exception:
            continue
        if not isinstance(a, dict):
            continue
        for k in ("task_id", "bash_id", "shell_id"):
            if k in a and a[k] is not None:
                ref = str(a[k])
                iss = issued[row.session_id].get(ref)
                cls = "never_issued" if iss is None else ("issued_before" if iss[0] < row.seq else "issued_after")
                c[f"T3_ref_call_args|{row.tool_raw}|{cls}"] += 1
        if "taskId" in a and row.tool_raw in ("TaskUpdate", "TaskGet"):
            ref = str(a["taskId"])
            sq = todo[row.session_id].get(ref)
            cls = "never_created" if sq is None else ("created_before" if sq < row.seq else "created_after")
            c[f"T3b_todo_ref|{cls}"] += 1
    # references: notifications / TaskOutput tags
    m = anytext["text"].str.contains("<task-id>|<task_id>", regex=True, na=False)
    for row in anytext[m].itertuples():
        for tag in ("task_id_tag_notification", "task_id_tag_output"):
            for x in TRX[tag].findall(row.text):
                iss = issued[row.session_id].get(x)
                cls = "never_issued" if iss is None else ("issued_before" if iss[0] < row.seq else ("same_event" if iss[0] == row.seq else "issued_after"))
                c[f"T3_ref_{tag}|{row.kind}|{cls}"] += 1
        if "<task-notification>" in row.text:
            for blk in row.text.split("<task-notification>")[1:]:
                tid = TRX["task_id_tag_notification"].search(blk)
                tu = TRX["tool_use_id_tag"].search(blk)
                of = TRX["output_file_task"].search(blk)
                if tid and of:
                    c["T3_notif_outputfile_taskid|" + ("eq" if of.group(1) == tid.group(1) else "ne")] += 1
                if tid and tu:
                    tuv = tu.group(1)
                    if "REDACTED" in tuv:
                        c["T3_notif_tool_use_id|redacted"] += 1
                        continue
                    icall = issuer_call[row.session_id].get(tid.group(1))
                    if icall is None:
                        # agent ids issued only by nesting: compare with the nesting parent call
                        pcs = [k[1] for k, s in nest_map.items() if k[0] == row.session_id and tid.group(1) in s]
                        if pcs:
                            c["T3_notif_tool_use_id_vs_nesting_parent|" + ("eq" if tuv in pcs else "ne")] += 1
                        else:
                            c["T3_notif_tool_use_id|issuer_unknown"] += 1
                    else:
                        c["T3_notif_tool_use_id_vs_issuing_call|" + ("eq" if icall == tuv else "ne")] += 1
    # T1 spill path
    m = res["text"].str.contains("/tool-results/", regex=False, na=False)
    own = res["text"].str.startswith("<persisted-output>", na=False)
    c["T1_spill_path_mentions_in_results_not_starting_with_persisted_output"] += int((m & ~own).sum())
    for row in res[m & own].itertuples():
        for u, tid in TRX["cc_spill_path"].findall(row.text[:2000]):
            c["T1_spill_paths"] += 1
            if tid == row.call_id:
                k = "eq_own_call_id"
            elif tid == "REDACTED":
                k = "redacted_by_release"
            elif re.fullmatch(r"b[0-9a-z]{8}", tid):
                k = "shell_output_id_b+8_base36|" + ("issued_as_bg_id_in_session" if tid in issuer_call[row.session_id] else "not_issued_as_bg_id")
            elif tid in set(t.loc[t.session_id == row.session_id, "call_id"].dropna()):
                k = "other_call_in_session"
            else:
                k = "other"
            c["T1_spill_file_id|" + k + "|" + str(row.tool_raw)] += 1
            c["T1_spill_dir_uuid|" + ("eq_session_id" if u == row.session_id else ("eq_session_uuid_part" if u == str(row.session_id).split("/")[0] else ("other_session_in_swechat_population" if u in all_sessions else "unknown_uuid")))] += 1
    # T4 Codex unified exec session ids
    if acc.corpus == "swechat":
        cx = t[t["sub"] == "codex"]
        if len(cx):
            for sid, g in cx.groupby("session_id"):
                g = g.sort_values("seq")
                running, exited = {}, set()
                callargs = {}
                for row in g.itertuples():
                    if row.kind == "call" and row.tool_raw == "write_stdin":
                        try:
                            a = json.loads(row.args)
                            n = str(a.get("session_id"))
                        except Exception:
                            n = None
                        callargs[row.call_id] = n
                        if n is not None:
                            cls = "never_issued" if n not in running else ("after_exit" if n in exited else "live")
                            c[f"T4_write_stdin_ref|{cls}"] += 1
                    elif row.kind == "result" and isinstance(row.text, str):
                        head = row.text[:600]
                        mr = TRX["codex_running"].search(head)
                        me = TRX["codex_exited"].search(head)
                        if mr:
                            n = mr.group(1)
                            if row.tool_raw == "write_stdin":
                                ref = callargs.get(row.call_id)
                                c["T4_running_header_on_write_stdin|" + ("same_session_id" if ref == n else "different_session_id")] += 1
                            else:
                                c["T4_issued"] += 1
                                if n in running:
                                    c["T4_issued_id_already_seen_in_session"] += 1
                                running.setdefault(n, row.seq)
                        if me and row.tool_raw == "write_stdin":
                            ref = callargs.get(row.call_id)
                            if ref is not None:
                                exited.add(ref)
                                c["T4_exit_seen_for_ref"] += 1
    # T5 commit claims and git log lines
    m = res["text"].str.contains(r"(?m)^\[[^\]\s]+ (?:\(root-commit\) )?[0-9a-f]{7,40}\] ", regex=True, na=False)
    claims = defaultdict(lambda: defaultdict(set))  # session -> sha7 -> set(subject)
    claim_seq = defaultdict(dict)
    for row in res[m].itertuples():
        for br, sha, subj in TRX["commit_claim"].findall(row.text):
            c["T5_commit_claims"] += 1
            claims[row.session_id][sha[:7]].add(subj.strip())
            claim_seq[row.session_id].setdefault(sha[:7], row.seq)
    for sid, d in claims.items():
        for sha, subs in d.items():
            c["T5_distinct_sha7"] += 1
            c["T5_sha7_with_gt1_subject"] += int(len(subs) > 1)
    # git log --oneline outputs: call command contains 'git log'
    callcmd = t[(t["kind"] == "call") & t["args"].str.contains("git log", regex=False, na=False)][["session_id", "call_id"]]
    gl_keys = set(zip(callcmd["session_id"], callcmd["call_id"]))
    if gl_keys:
        rr = res[[k in gl_keys for k in zip(res["session_id"], res["call_id"])]]
        for row in rr.itertuples():
            d = claims.get(row.session_id)
            if not d:
                continue
            for sha, subj in TRX["git_oneline"].findall(row.text):
                s7 = sha[:7]
                if s7 in d:
                    subj = re.sub(r"^\([^)]*\) ", "", subj.strip())  # strip --decorate refs
                    ok = subj in d[s7]
                    when = "after_claim" if claim_seq[row.session_id][s7] < row.seq else "before_claim"
                    c[f"T5_gitlog_vs_claim|{when}|" + ("subject_eq" if ok else "subject_ne")] += 1
    # T6 request ids in text
    m = anytext["text"].str.contains(r"req_(?:vrtx_|bdrk_)?011", regex=True, na=False)
    for row in anytext[m].itertuples():
        ctx = "api_error_json" if TRX["api_error_json"].search(row.text) else "other"
        for r_ in TRX["req_in_text"].findall(row.text):
            body = r_.rsplit("_", 1)[1]
            v = b58(body[2:]) >> 80
            c[f"T6_req_in_text|{row.kind}|{ctx}"] += 1
            if WIN_LO <= v < WIN_HI and not math.isnan(row.ms):
                acc.t6_off.append((row.session_id, row.ms - v, f"{row.kind}|{ctx}"))
    # T7 uuids in result text
    m = res["text"].str.contains(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", regex=True, na=False)
    for row in res[m].itertuples():
        own = {row.session_id}
        for u in set(TRX["uuid_in_text"].findall(row.text)):
            ver, var = uuid_version(u)
            acc.t7[f"{ver}|{var}|" + ("eq_own_session_id" if u in own else ("eq_other_population_session" if u in all_sessions else "other"))] += 1
            tm, _ = uuid_time_ms(u)
            if tm is not None and not math.isnan(row.ms):
                acc.t7_off.append((row.session_id, row.ms - tm, ver))
    # PID census only
    m = res["text"].str.contains(r"\b(?:PID|pid)[:= ]+\d", regex=True, na=False)
    c["T8_results_with_pid_pattern"] += int(m.sum())


def copy_consistency(acc):
    out = {}
    for col, d in acc.copy.items():
        r = Counter()
        for v, lst in d.items():
            if len(lst) < 2:
                continue
            r["values"] += 1
            tups = [x[1] for x in lst]
            r["all_copies_identical_rows"] += int(all(tp == tups[0] for tp in tups))
            # ts-only and content-only agreement (on the first row of each copy)
            r["first_row_ts_equal"] += int(all(tp[0][1] == tups[0][0][1] for tp in tups))
            r["first_row_args_text_equal"] += int(all(tp[0][2:] == tups[0][0][2:] for tp in tups))
            r["row_count_equal"] += int(all(len(tp) == len(tups[0]) for tp in tups))
        out[col] = dict(r)
    return out


def run_text(corpus, split, shared, all_sessions):
    path = CACHE / f"{corpus}_{split}.parquet"
    pf = pq.ParquetFile(path)
    acc = TextAcc(corpus)
    cols = ["session_id", "seq", "kind", "ts", "tool_raw", "call_id", "args", "text", "agent_id", "parent_call_id", "is_subagent", "uuid"]
    pop = pd.read_parquet(CACHE / "swechat_population.parquet", columns=["session_id", "format"]) if corpus == "swechat" else None
    for i in range(pf.num_row_groups):
        t = pf.read_row_group(i, columns=cols).to_pandas()
        if pop is not None:
            t = t.merge(pop, on="session_id", how="left")
            t["sub"] = t["format"].fillna("unknown")
        else:
            t["sub"] = corpus
        t["ms"] = to_ms(t["ts"])
        text_pass_chunk(t, acc, shared, all_sessions)
        log(corpus, "text row group", i + 1, "/", pf.num_row_groups)
        del t
    j = acc.to_json()
    j["copy_consistency_of_cross_session_ids"] = copy_consistency(acc)
    return j


# ---------------------------------------------------------------------------------------------------------------------
def scrub_private(o):
    """cc_local: drop any per-value detail (there is none by construction); keep a hook for safety."""
    return o


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if (isinstance(o, float) and math.isnan(o)) or (isinstance(o, np.floating) and np.isnan(o)) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def main():
    global CORPORA, OUT
    args = [a for a in sys.argv[1:]]
    if args:  # development: subset of corpora, output to a scratch path given by env or next to the real one
        CORPORA = [a for a in args if a in CORPORA]
        OUT = Path(__import__("os").environ.get("IDS_DEV_OUT", str(OUT.with_suffix(".dev.json"))))
    t0 = time.time()
    PREREG["decode_layouts"] = __doc__[__doc__.index("DECODE LAYOUTS"):__doc__.index("Run from the worktree root")].strip()
    J = {"probe": "phase_c_ids_and_clocks_in_ids", "prereg": PREREG, "inputs": {}, "census": {}, "clocks": {},
         "clocks_holdout_A": {}, "order": {}, "bracket": {}, "floor": {}, "bits": {}, "epochs": {}, "counters": {},
         "req_msg_pairing": {}, "reuse": {}, "within_session": {}, "copies": {}, "bracket_x_copies": {}, "text": {}}
    pop_sessions = set(pd.read_parquet(CACHE / "swechat_population.parquet", columns=["session_id"])["session_id"])
    for corpus in CORPORA:
        log("load", corpus, "B")
        df = load_ids(corpus, "B")
        J["inputs"][corpus] = {"split": "B", "rows": int(len(df)), "sessions": int(df.session_id.nunique()),
                               "rows_by_sub": {k: int(v) for k, v in df["sub"].value_counts().items()}}
        J["census"][corpus], fam_cache = census(df, corpus)
        log("census done", corpus)
        E = id_events(df, corpus, fam_cache)
        J["clocks"][corpus] = p2_offsets(E, corpus)
        J["order"][corpus] = p2b_order(E)
        J["bracket"][corpus] = p2c_bracket(df, E, corpus)
        J["floor"][corpus] = p2d_floor(E) if not E.empty else {}
        J["bits"][corpus] = p2e_bits(E) if not E.empty else {}
        J["epochs"][corpus] = p2f_epochs(E, corpus) if not E.empty else {}
        J["counters"][corpus] = p2g_counters(df, E, corpus, fam_cache)
        J["req_msg_pairing"][corpus] = p2h_req_msg(df, corpus)
        log("clocks done", corpus)
        J["reuse"][corpus] = p3_reuse(df, corpus, fam_cache)
        J["within_session"][corpus] = p3_within(df, corpus)
        J["copies"][corpus] = p3b_copies(df, corpus)
        # attribution: bracket inconsistencies / upper-bound violations vs sessions holding re-stamped copies (ids not written)
        rs = set(J["copies"][corpus].pop("_restamped_sessions", []))
        xb = {}
        for fam, bysub in J["bracket"][corpus].items():
            for sg, rec in bysub.items():
                inc = set(rec.pop("_inconsistent_sessions", []))
                hv = set(rec.pop("_hi_violation_sessions", []))
                xb[f"{fam}|{sg}"] = {"sessions_with_inconsistent_stream": len(inc),
                                     "of_which_hold_restamped_copies": len(inc & rs),
                                     "sessions_with_hi_lt_-tol": len(hv), "of_which_hold_restamped_copies_hi": len(hv & rs),
                                     "sessions_holding_restamped_copies": len(rs)}
        J["bracket_x_copies"][corpus] = xb
        # shared ids for copy consistency (uuid, call_id values in > 1 session)
        shared = {}
        for col in ["uuid", "call_id"]:
            s = df[df[col].notna() & ~df[col].astype(str).str.match(r"^(?:synthetic:|turn:|step:)")
                   & ~df[col].astype(str).str.contains("REDACTED", regex=False)].drop_duplicates([col, "session_id"])
            vc = s[col].value_counts()
            shared[col] = set(vc[vc > 1].index)
        J["inputs"][corpus]["shared_values_for_copy_check"] = {k: len(v) for k, v in shared.items()}
        del df, E
        log("text pass", corpus)
        J["text"][corpus] = run_text(corpus, "B", shared, pop_sessions)
        # holdout A: decoding agreement only
        log("holdout A", corpus)
        dfa = load_ids(corpus, "A")
        _, fca = census(dfa, corpus)
        Ea = id_events(dfa, corpus, fca)
        J["clocks_holdout_A"][corpus] = p2_offsets(Ea, corpus)
        J["inputs"][corpus]["holdout_A"] = {"rows": int(len(dfa)), "sessions": int(dfa.session_id.nunique())}
        del dfa, Ea
    J["runtime_s"] = round(time.time() - t0, 1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(clean(J), fh, indent=1, default=str)
    log("wrote", OUT, "in", J["runtime_s"], "s")


if __name__ == "__main__":
    main()
