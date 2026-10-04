"""Phase C lens `changepoints`: within-session regime shifts in per-call / per-response series.

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_c_changepoints
Writes RAW COUNTS ONLY to analysis/out/phase_c/changepoints.json. Interpretation: analysis/notes/changepoints.md.

Inputs: analysis/cache/{swechat,cc_local,aiv_cc,aiv_cu,whowhen}_B.parquet (Phase B split), swechat_population.parquet
(format per session). Read-only raw scans (no content copied out): swechat Claude Code transcripts (per-entry `version`,
`sessionId`, `permissionMode`, keyed by entry uuid) and cc_local main files (same fields; PRIVATE: aggregates only).

METHOD (fixed in PREREG before any outcome was computed; changes go to REVISIONS with before/after/reason)
  Session eligibility: >= 40 main-thread calls (is_subagent False; a session whose calls are all subagent calls, e.g. an
  OpenCode child session, uses all its calls). Series eligibility: >= 40 non-missing points.
  Series (main thread only):
    per call (index = main-thread call order):
      latency     result.ts - call.ts (ms) for ts_kind event/row_insert; aiv_cu (shared_turn): Gemini server-timing dur ms
      gap         call.ts - previous call.ts (ms)
      result_len  chars of the paired result text
      err         1 if paired result has native_error True or ir.error_marker(text) (extra.marker where the parser set it)
      tool        normalized tool class; categories = the session's top 7 tools + 'other'
      thinking    thinking/reasoning chars on main-thread assistant/call events after the previous call up to this call
    per API response (usage rows deduped on (session, api_msg_id), max usage_out; ordered by first seq):
      ctx         context size: usage_in + cache_read + cache_create (Anthropic-style, OpenCode); usage_in alone where the
                  provider's input count includes cached tokens (Codex, Gemini CLI, aiv_cu gemini-*)
      usage_in    raw usage_in
      usage_out   max usage_out over the response's rows
  Detector (one method for all series): binary segmentation, penalized likelihood, minimum segment 10 points.
    continuous series: x = log1p(value); Gaussian mean shift with known sigma, sigma = sd(diff(x), ddof=1)/sqrt(2);
                       cost = RSS/sigma^2; penalty per change 2*ln(n)
    err:               Bernoulli rate shift; cost = -2 loglik; penalty per change 2*ln(n)
    tool:              multinomial shift; cost = -2 loglik; penalty per change C*ln(n) (C categories: C-1 probabilities + location)
    A split is accepted when the cost reduction exceeds the penalty; segments shorter than 2*10 points are not split.
  Shuffle control: the same detector on one random within-series permutation of every eligible series.
  Co-occurrence: a change point at point index k (first post-change point) has window = seq range
    [anchor(k-3), anchor(k+2)] (3 points either side) and tight window = (anchor(k-1), anchor(k)]. A harness event
    co-occurs if its seq lies in the window. Chance expectation per change point = fraction of admissible positions
    j in [10, n-10] whose window contains such an event (same session, same series); obs/exp ratio with a
    session-clustered bootstrap CI (stats.cluster_rate).
  Harness events (main thread): see HARNESS_TYPES. 'other_system' (unclassified harness-injected text) is reported but kept
  out of the primary 'any harness event' set; the broad set adds it.
"""
import glob
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from analysis.lib import stats
from analysis.lib.ir import error_marker

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE = os.path.join(ROOT, "analysis", "cache")
OUT = os.path.join(ROOT, "analysis", "out", "phase_c", "changepoints.json")
SWE_TX = r"C:\Swarms\data\swe-chat-pinned\transcripts"
CC_LOCAL_RAW = r"C:\Swarms\data\claude-code-local"
SEED = stats.SEED

PREREG = {
    "fixed_before_outcomes": "all entries below were written before the first run that computed any change point",
    "split": "Phase B caches only (analysis/cache/<corpus>_B.parquet)",
    "min_calls_per_session": 40,
    "min_points_per_series": 40,
    "min_segment_points": 10,
    "detector": "binary segmentation, penalized likelihood; split accepted iff cost reduction > penalty",
    "gaussian": {"transform": "log1p(value) (values >= 0)", "sigma": "sd(diff(x), ddof=1)/sqrt(2)",
                 "cost": "RSS/sigma^2", "penalty_per_change": "2*ln(n)", "degenerate": "sigma == 0 (constant series)"},
    "bernoulli": {"series": ["err"], "cost": "-2 loglik", "penalty_per_change": "2*ln(n)", "degenerate": "all 0 or all 1"},
    "multinomial": {"series": ["tool"], "categories": "session's top 7 tool classes by count (ties by name) + 'other'",
                    "cost": "-2 loglik", "penalty_per_change": "C*ln(n)", "degenerate": "one category"},
    "series_call_indexed": ["latency", "gap", "result_len", "err", "tool", "thinking"],
    "series_response_indexed": ["ctx", "usage_in", "usage_out"],
    "latency_definition": {"default": "result.ts - call.ts in ms (paired by call_id); negative -> missing",
                           "aiv_cu": "extra.timing server-timing dur ms on the call event (Gemini only; model latency, not tool latency)"},
    "gap_definition": "call.ts - previous main-thread call.ts in ms; negative -> missing",
    "ctx_definition": {"usage_in+cache_read+cache_create": ["swechat/claude_code", "swechat/opencode", "cc_local", "aiv_cc",
                                                             "aiv_cu/anthropic-*"],
                       "usage_in": ["swechat/codex", "swechat/gemini", "aiv_cu/gemini-*"]},
    "usage_dedupe": "rows with usage_in not null, main thread; key (session_id, api_msg_id) (row seq when api_msg_id null); "
                    "usage_in/cache from the first row, usage_out = max over rows",
    "thinking_definition": "sum of extra.thinking_chars (aiv_cu: extra.reasoning_chars) over main-thread assistant/call "
                           "events with seq in (previous call seq, this call seq]",
    "window_points_each_side": 3,
    "tight_window": "(anchor(k-1), anchor(k)]",
    "chance_positions": "j in [10, n-10]",
    "idle_gap_s": 300,
    "idle_definition": "ts(anchor k) - ts(anchor k-1) >= 300 s at the change point (descriptor, not a harness event)",
    "cross_series_tolerance_calls": 3,
    "shuffle_control": "one permutation per eligible series, rng = default_rng([SEED, corpus_index, session_index, series_index])",
    "block_shuffle_control": "one permutation of consecutive blocks of 10 points (last block may be shorter) per eligible series, "
                             "rng = default_rng([SEED, corpus_index, session_index, series_index, 1]); keeps short-range "
                             "dependence, destroys order beyond 10 points",
    "synthetic_calibration": "detector false-positive rate on Gaussian AR(1) series, rho in {0, 0.1, 0.2, 0.3, 0.5, 0.7}, "
                             "n in {50, 200, 1000}, 300 replicates each, rng = default_rng([SEED, 99])",
    "seed": SEED,
    "n_boot": stats.N_BOOT,
    "examples_per_corpus": "largest |delta in sigma units| no-harness change points, public corpora only (not cc_local), 12 per corpus",
}
REVISIONS = [  # {"id", "what", "before", "after", "reason", "seen_before_change"}
    {"id": "r1", "what": "err series: result marker test",
     "before": "marker counted when `is not None` (pandas turned missing markers into NaN, so every result counted as an error)",
     "after": "marker counted only when it is a string",
     "reason": "bug: run 1 had every err series degenerate (all 1)",
     "seen_before_change": "run-1 counts of eligible/degenerate err series only (no err change points existed)"},
    {"id": "r2", "what": "model_switch: compare normalized model names (norm_model)",
     "before": "raw model strings",
     "after": "lowercase, strip 'models/' and 'claude-code::' prefixes, trailing -YYYYMMDD and -preview(-MM-DD)",
     "reason": "run-1 inventory: aiv_cu events alternate between the session model_string and the row's provider model "
               "version ('gemini-2.5-pro' vs 'gemini-2.5-pro-preview-06-05', 'claude-code::claude-opus-4-5-20251101' vs "
               "'claude-opus-4-5-20251101'), which are naming differences, not switches",
     "seen_before_change": "run-1 per-series sessions-with-change-point counts and harness event inventory; model_switch "
                           "co-occurrence results were not read"},
    {"id": "r3", "what": "timestamp unit",
     "before": "datetime64 -> int64 / 1e6, which gives seconds (not ms) because pandas 3 parses ISO strings at microsecond "
               "resolution; latency/gap series were log1p(seconds) and the 300 s idle test compared seconds with 300000",
     "after": "(ts - epoch) / 1 ms, so latency and gap are in ms as pre-registered",
     "reason": "bug: run 2 idle_at_cp had expected count 0.0 in every series",
     "seen_before_change": "run-2 results for all series (the bug made latency/gap deviate from the pre-registered definition)"},
    {"id": "P1", "what": "POSTHOC additions (no change to detection or co-occurrence): per change point the immediate step "
                         "x[k]-x[k-1] and the smallest one-step change within the +-3 window (continuous series), and for "
                         "call-indexed series the tool-mix total-variation distance between the two adjacent segments and "
                         "the tool class whose share rose most; summarized as posthoc_* keys",
     "reason": "run-4 showed latency up-shifts and result_len down-shifts are mostly without harness events and coincide "
               "with tool-mix change points (cross_series); this asks which tool classes move",
     "seen_before_change": "run-4 full output"},
    {"id": "P3", "what": "POSTHOC event type synthetic_msg (main-thread events whose model is '<synthetic>', i.e. harness-written "
                         "assistant messages with zero usage); co-occurrence is reported like other types but it is NOT added "
                         "to the primary or broad harness sets, so no_harness_* counts are unchanged",
     "reason": "run-5: the two sharp no-harness ctx drops in swechat sit on runs of '<synthetic>' zero-usage responses",
     "seen_before_change": "run-5 posthoc_ctx_down_no_harness rows"},
    {"id": "P4", "what": "POSTHOC count of change points at k == 10 or k == n-10 (minimum-segment edge) per series and in the "
                         "ctx-drop list",
     "reason": "run-5: most no-harness ctx down-shifts have no sharp step in their window and sit at k=10 or n-10, i.e. the "
               "detector placed the boundary at the segment-length limit while the real drop lies closer to the series end",
     "seen_before_change": "run-5 posthoc_ctx_down_no_harness rows"},
    {"id": "P5", "what": "POSTHOC inventory: relative position (seq / last seq of the session) of each harness event type in "
                         "eligible sessions (inventory.posthoc_event_pos_rel_in_session)",
     "reason": "run-6: context_clear has zero chance expectation in every series, i.e. /clear markers never fall inside a "
               "change-point window",
     "seen_before_change": "run-6 full output"},
    {"id": "P2", "what": "POSTHOC list of ctx down-shifts with no primary harness event (posthoc_ctx_down_no_harness)",
     "reason": "run-4 by_direction: ctx down-shifts are almost all compaction, the remainder is a candidate for unlogged "
               "context edits (cf. aiv_accounting m4_context negative clean deltas)",
     "seen_before_change": "run-4 full output"},
]

HARNESS_TYPES = ["compaction", "context_clear", "slash_command", "skill_injection", "model_switch", "setting_change",
                 "subagent_start", "user_turn", "resume", "version_change", "api_error", "interrupt", "tool_timeout",
                 "task_notification", "rollback"]
BROAD_EXTRA = ["other_system"]
POSTHOC_TYPES = ["synthetic_msg"]  # P3: tracked for description only; never part of the primary or broad harness sets
ALL_TYPES = HARNESS_TYPES + BROAD_EXTRA + POSTHOC_TYPES
HARNESS_DEFS = {
    "compaction": "CC/aiv_cc/cc_local meta system subtype compact_boundary|microcompact_boundary; aiv_cc system status rows; "
                  "system text starting 'This session is being continued' or '<command-name>/compact'; Codex compacted / "
                  "context_compacted; OpenCode compaction part; cc_local attachment compact_file_reference",
    "context_clear": "system text containing '<command-name>/clear'",
    "slash_command": "other system text starting '<command-name>', '<command-message>', '<local-command'; CC meta system subtype local_command",
    "skill_injection": "system text starting 'Base directory for this skill'",
    "model_switch": "model column changes between consecutive main-thread model-bearing events (ignoring '<synthetic>')",
    "setting_change": "'<command-name>/model'; Codex turn_context (model, effort, approval_policy, sandbox) change; raw CC "
                      "permissionMode change between user entries; cc_local attachments ultra_effort_enter/exit, model",
    "subagent_start": "main-thread call with tool subagent|workflow; system text starting 'Spawning agent'; Codex "
                      "collab_agent_spawn_end; OpenCode subtask part",
    "user_turn": "kind == 'user' (human prompt)",
    "resume": "raw CC sessionId change between consecutive main-thread entries; cc_local extra.family_member change; "
              "Codex session_meta after the first; aiv_cu synthetic bootstrap turn after seq 2",
    "version_change": "raw CC entry `version` change between consecutive main-thread entries (swechat claude_code, cc_local); "
                      "Codex session_meta cli_version change",
    "api_error": "CC meta system subtype api_error; Codex event_msg error; OpenCode message_error; Gemini CLI meta "
                 "message_type error; aiv_cc extra.sdk_error",
    "interrupt": "result marker cc_interrupt_reject; Codex turn_aborted; Gemini CLI info 'Request cancelled.'",
    "tool_timeout": "result extra.timedOutAfterMs (CC); aiv_cu result stderr starting 'timed out'",
    "task_notification": "system text starting '<task-notification>' or '[SYSTEM NOTIFICATION'; cc_local attachment with notification_statuses",
    "rollback": "Codex thread_rolled_back",
    "other_system": "any other main-thread kind=='system' event (harness-injected text); Gemini CLI other info/warning meta",
}

CONT_SERIES = ["latency", "gap", "result_len", "thinking", "ctx", "usage_in", "usage_out"]
CALL_SERIES = ["latency", "gap", "result_len", "err", "tool", "thinking"]
RESP_SERIES = ["ctx", "usage_in", "usage_out"]
SERIES = CALL_SERIES + RESP_SERIES
MS = PREREG["min_segment_points"]
W = PREREG["window_points_each_side"]


# ----------------------------------------------------------------------------------------------------------- detector
def _best_split(kind, S, a, b):
    ks = np.arange(a + MS, b - MS + 1)
    if len(ks) == 0:
        return None, -np.inf
    if kind == "gauss":
        tot = S[b] - S[a]
        L = S[ks] - S[a]
        R = S[b] - S[ks]
        gain = L ** 2 / (ks - a) + R ** 2 / (b - ks) - tot ** 2 / (b - a)
    elif kind == "bern":
        def c(k1, m):
            k1 = np.asarray(k1, float); m = np.asarray(m, float)
            k0 = m - k1
            with np.errstate(divide="ignore", invalid="ignore"):
                t1 = np.where(k1 > 0, k1 * np.log(np.where(k1 > 0, k1, 1) / m), 0.0)
                t0 = np.where(k0 > 0, k0 * np.log(np.where(k0 > 0, k0, 1) / m), 0.0)
            return -2 * (t1 + t0)
        gain = c(S[b] - S[a], b - a) - c(S[ks] - S[a], ks - a) - c(S[b] - S[ks], b - ks)
    else:  # multinomial, S is (n+1, C)
        def c(cnt):
            m = cnt.sum(-1)
            with np.errstate(divide="ignore", invalid="ignore"):
                t = np.where(cnt > 0, cnt * np.log(np.where(cnt > 0, cnt, 1) / np.maximum(m, 1)[..., None]), 0.0)
            return -2 * t.sum(-1)
        gain = c(S[b] - S[a]) - c(S[ks] - S[a]) - c(S[b] - S[ks])
    i = int(np.argmax(gain))
    return int(ks[i]), float(gain[i])


def binseg(kind, x, ncat=None):
    """x: 1-d float array (gauss: already z-scaled; bern: 0/1) or int codes (multi). Returns list of (k, gain, depth)."""
    n = len(x)
    if kind == "gauss":
        S = np.concatenate([[0.0], np.cumsum(x)])
        pen = 2 * math.log(n)
    elif kind == "bern":
        S = np.concatenate([[0.0], np.cumsum(x)])
        pen = 2 * math.log(n)
    else:
        oh = np.zeros((n, ncat))
        oh[np.arange(n), x] = 1
        S = np.vstack([np.zeros((1, ncat)), np.cumsum(oh, 0)])
        pen = ncat * math.log(n)
    out, stack = [], [(0, n, 0)]
    while stack:
        a, b, d = stack.pop()
        if b - a < 2 * MS:
            continue
        k, g = _best_split(kind, S, a, b)
        if k is not None and g > pen:
            out.append((k, g, d))
            stack.append((a, k, d + 1))
            stack.append((k, b, d + 1))
    return sorted(out)


def detect(name, x, cats=None):
    """Returns dict(degenerate, cps=[{k, gain, depth, delta, delta_sigma, tv, top_gain_cat}], sigma, lag1) for one series."""
    n = len(x)
    if name == "err":
        if x.min() == x.max():
            return {"degenerate": True}
        cps = binseg("bern", x)
        sig, xs = None, x
    elif name == "tool":
        ncat = int(x.max()) + 1
        if ncat < 2 or len(np.unique(x)) < 2:
            return {"degenerate": True}
        cps = binseg("multi", x, ncat)
        sig, xs = None, x
    else:
        d = np.diff(x)
        sig = float(np.std(d, ddof=1) / math.sqrt(2)) if n > 2 else 0.0
        if sig <= 0:
            return {"degenerate": True}
        cps = binseg("gauss", x / sig)
        xs = x
    bounds = [0] + [c[0] for c in cps] + [n]
    res = []
    for t, (k, g, dep) in enumerate(cps):
        L, R = xs[bounds[t]:k], xs[k:bounds[t + 2]]
        r = {"k": k, "gain": g, "depth": dep}
        if name == "tool":
            ncat = int(x.max()) + 1
            pL = np.bincount(L, minlength=ncat) / len(L)
            pR = np.bincount(R, minlength=ncat) / len(R)
            r["tv"] = float(0.5 * np.abs(pR - pL).sum())
            r["top_gain_cat"] = cats[int(np.argmax(pR - pL))] if cats is not None else None
            r["delta"] = r["tv"]
        else:
            r["delta"] = float(R.mean() - L.mean())
            if sig:
                r["delta_sigma"] = r["delta"] / sig
        res.append(r)
    lag1 = None
    if name != "tool" and n > 3 and np.std(x[:-1]) > 0 and np.std(x[1:]) > 0:
        lag1 = float(np.corrcoef(x[:-1], x[1:])[0, 1])
    return {"degenerate": False, "cps": res, "sigma": sig, "lag1": lag1}


# ----------------------------------------------------------------------------------------------------------- loading
def _to_ms(ts):
    dt = pd.to_datetime(ts, utc=True, format="ISO8601", errors="coerce")
    v = (dt - pd.Timestamp(0, tz="UTC")) / pd.Timedelta(1, "ms")  # resolution-independent (pandas 3 parses to us)
    return v.to_numpy(dtype="float64", na_value=np.nan)


BASE_COLS = ["session_id", "stratum", "seq", "kind", "ts", "ts_kind", "tool", "call_id", "native_error", "usage_in",
             "usage_out", "usage_cache_read", "usage_cache_create", "api_msg_id", "model", "is_subagent", "uuid", "extra"]


def prepare(tbl, corpus, fmt_map):
    """pyarrow table with BASE_COLS + text (+ stderr) -> light pandas frame with derived text columns (text dropped)."""
    kind = tbl.column("kind")
    text = tbl.column("text")
    is_res = pc.equal(kind, "result")
    tlen = pc.utf8_length(text)
    pre = pc.utf8_slice_codeunits(text, 0, 120)
    keep_pre = pc.is_in(kind, value_set=pa.array(["system", "user", "meta"]))
    pre = pc.if_else(keep_pre, pre, pa.scalar(None, pa.string()))
    df = tbl.select(BASE_COLS).to_pandas()
    for c in ["usage_in", "usage_out", "usage_cache_read", "usage_cache_create"]:
        df[c] = df[c].astype("float64")
    df["native_error"] = df["native_error"].astype("object")
    df["is_subagent"] = df["is_subagent"].fillna(False).astype(bool)
    df["text_len"] = tlen.to_pandas().astype("float64")
    df["prefix"] = pre.to_pandas()
    df["tms"] = _to_ms(df["ts"])
    df["xd"] = [json.loads(e) if isinstance(e, str) else {} for e in df["extra"]]
    df.drop(columns=["extra", "ts"], inplace=True)
    # error marker: parser-set extra.marker when the key exists, else ir.error_marker on the full text (results only)
    res_idx = np.flatnonzero(is_res.to_numpy(zero_copy_only=False))
    need = [i for i in res_idx if "marker" not in df["xd"].iat[i]]
    marker = np.array([None] * len(df), dtype=object)
    for i in res_idx:
        marker[i] = df["xd"].iat[i].get("marker")
    if need:
        tx = text.take(pa.array(need)).to_pylist()
        for i, t in zip(need, tx):
            marker[i] = error_marker(t)
    df["marker"] = marker
    if "stderr" in tbl.column_names:
        st = pc.utf8_slice_codeunits(tbl.column("stderr"), 0, 40).to_pandas()
        df["stderr_pre"] = st
    else:
        df["stderr_pre"] = None
    df["corpus"] = corpus
    df["group"] = df["session_id"].map(fmt_map) if fmt_map is not None else df["stratum"]
    return df


# ----------------------------------------------------------------------------------------------------------- raw scans
def scan_cc_file(path):
    """Raw Claude Code JSONL -> {uuid: (version, sessionId, permissionMode)} for top-level entries. Content is not kept."""
    out = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if not isinstance(d, dict):
                    continue
                u = d.get("uuid")
                if u:
                    out[u] = (d.get("version"), d.get("sessionId"), d.get("permissionMode"), d.get("timestamp"))
    except OSError:
        return None
    return out


def scan_cc_local_mains():
    """uuid -> (version, sessionId, permissionMode) over all cc_local main files; when a uuid occurs in several files the
    copy from the file with the earliest first timestamp wins (the loader's root-first dedup)."""
    best = {}
    files = [p for p in glob.glob(os.path.join(CC_LOCAL_RAW, "*", "*.jsonl"))]
    n_conflict = 0
    for p in files:
        m = scan_cc_file(p)
        if not m:
            continue
        first_ts = min((v[3] for v in m.values() if v[3]), default="9999")
        for u, v in m.items():
            if u in best:
                if best[u][0] != v[:3]:
                    n_conflict += 1
                if first_ts < best[u][1]:
                    best[u] = (v[:3], first_ts)
            else:
                best[u] = (v[:3], first_ts)
    return {u: v[0] for u, v in best.items()}, {"main_files": len(files), "uuid_value_conflicts_across_copies": n_conflict}


# ----------------------------------------------------------------------------------------------------------- per session
def classify_system(prefix):
    p = prefix.lstrip() if isinstance(prefix, str) else ""
    if p.startswith("This session is being continued") or p.startswith("<command-name>/compact"):
        return "compaction"
    if "<command-name>/clear" in p:
        return "context_clear"
    if p.startswith("<command-name>/model"):
        return "setting_change"
    if p.startswith("<command-name>") or p.startswith("<command-message>") or p.startswith("<local-command"):
        return "slash_command"
    if p.startswith("Base directory for this skill"):
        return "skill_injection"
    if p.startswith("<task-notification>") or p.startswith("[SYSTEM NOTIFICATION"):
        return "task_notification"
    if p.startswith("Spawning agent"):
        return "subagent_start"
    return "other_system"


MODEL_PAIRS = defaultdict(Counter)  # corpus -> (from, to) normalized model switch counts (all sessions in B)


def norm_model(m):
    """Model name for switch detection (REVISIONS r2): lowercase; drop 'models/' and 'claude-code::' prefixes, a trailing
    -YYYYMMDD date and a trailing -preview / -preview-MM-DD tag. None for missing or '<synthetic>'."""
    if not isinstance(m, str) or not m or m == "<synthetic>":
        return None
    x = m.strip().lower()
    for pre in ("models/", "claude-code::"):
        if x.startswith(pre):
            x = x[len(pre):]
    x = re.sub(r"-\d{8}$", "", x)
    x = re.sub(r"-preview(-\d\d-\d\d)?$", "", x)
    return x


def harness_events(g, corpus, group, raw):
    """g: one session's main-thread rows (sorted by seq). Returns list of (seq, type) and counters."""
    ev = []
    seqs = g["seq"].to_numpy()
    kinds = g["kind"].to_numpy()
    xds = g["xd"].to_numpy()
    pres = g["prefix"].to_numpy()
    tools = g["tool"].to_numpy()
    markers = g["marker"].to_numpy()
    models = g["model"].to_numpy()
    stderrs = g["stderr_pre"].to_numpy()
    prev_tc, n_session_meta, prev_cli = None, 0, None
    prev_model, prev_fam = None, None
    for i in range(len(g)):
        s, k, xd = int(seqs[i]), kinds[i], xds[i]
        if isinstance(models[i], str) and models[i] == "<synthetic>":
            ev.append((s, "synthetic_msg"))
        m = norm_model(models[i])
        if m:
            if prev_model is not None and m != prev_model:
                ev.append((s, "model_switch"))
                MODEL_PAIRS[corpus][(prev_model, m)] += 1
            prev_model = m
        fam = xd.get("family_member")
        if fam is not None:
            if prev_fam is not None and fam != prev_fam:
                ev.append((s, "resume"))
            prev_fam = fam
        if k == "user":
            ev.append((s, "user_turn"))
        elif k == "system":
            if corpus == "cc_local" and xd.get("entry_type") == "attachment":
                at = xd.get("attachment_type")
                if at == "compact_file_reference":
                    ev.append((s, "compaction"))
                elif at in ("ultra_effort_enter", "ultra_effort_exit", "model"):
                    ev.append((s, "setting_change"))
                elif xd.get("notification_statuses"):
                    ev.append((s, "task_notification"))
                else:
                    ev.append((s, "other_system"))
            elif corpus == "aiv_cu":
                if s > 2 and xd.get("synthetic"):
                    ev.append((s, "resume"))
            elif group == "codex" and "role" not in xd:
                ev.append((s, "compaction"))  # codex `compacted` with a message -> system without role
            else:
                ev.append((s, classify_system(pres[i])))
        elif k == "meta":
            et, st = xd.get("entry_type"), xd.get("subtype")
            ty = xd.get("type")
            if et == "system" and st in ("compact_boundary", "microcompact_boundary", "status"):
                ev.append((s, "compaction"))
            elif et == "system" and st == "api_error":
                ev.append((s, "api_error"))
            elif et == "system" and st == "local_command":
                ev.append((s, "slash_command"))
            elif group == "codex":
                if et == "compacted" or ty == "context_compacted":
                    ev.append((s, "compaction"))
                elif ty == "turn_aborted":
                    ev.append((s, "interrupt"))
                elif ty == "thread_rolled_back":
                    ev.append((s, "rollback"))
                elif ty == "error":
                    ev.append((s, "api_error"))
                elif ty == "collab_agent_spawn_end":
                    ev.append((s, "subagent_start"))
                elif et == "turn_context":
                    tc = tuple(xd.get(q) for q in ("model", "effort", "approval_policy", "sandbox"))
                    if prev_tc is not None and tc != prev_tc:
                        ev.append((s, "setting_change"))
                    prev_tc = tc
                elif et == "session_meta":
                    n_session_meta += 1
                    if n_session_meta > 1:
                        ev.append((s, "resume"))
                    cv = xd.get("cli_version")
                    if prev_cli is not None and cv != prev_cli:
                        ev.append((s, "version_change"))
                    prev_cli = cv
            elif group == "opencode":
                pt = xd.get("part_type")
                if pt == "compaction":
                    ev.append((s, "compaction"))
                elif pt == "subtask":
                    ev.append((s, "subagent_start"))
                elif "message_error" in xd:
                    ev.append((s, "api_error"))
            elif group == "gemini":
                mt = xd.get("message_type")
                if mt == "error":
                    ev.append((s, "api_error"))
                elif isinstance(pres[i], str) and pres[i].startswith("Request cancelled"):
                    ev.append((s, "interrupt"))
                else:
                    ev.append((s, "other_system"))
        elif k == "call":
            if tools[i] in ("subagent", "workflow"):
                ev.append((s, "subagent_start"))
            if corpus == "aiv_cc" and xd.get("sdk_error"):
                ev.append((s, "api_error"))
        elif k == "assistant":
            if corpus == "aiv_cc" and xd.get("sdk_error"):
                ev.append((s, "api_error"))
        elif k == "result":
            if markers[i] == "cc_interrupt_reject":
                ev.append((s, "interrupt"))
            if "timedOutAfterMs" in xd:
                ev.append((s, "tool_timeout"))
            if corpus == "aiv_cu" and isinstance(stderrs[i], str) and stderrs[i].startswith("timed out"):
                ev.append((s, "tool_timeout"))
    # raw-derived (Claude Code entries): version / sessionId / permissionMode along main-thread entries in seq order
    if raw:
        pv, ps, pp = None, None, None
        for s, u in zip(seqs, g["uuid"].to_numpy()):
            v = raw.get(u) if isinstance(u, str) else None
            if not v:
                continue
            ver, sid, pm = v
            if ver:
                if pv is not None and ver != pv:
                    ev.append((int(s), "version_change"))
                pv = ver
            if sid:
                if ps is not None and sid != ps:
                    ev.append((int(s), "resume"))
                ps = sid
            if pm:
                if pp is not None and pm != pp:
                    ev.append((int(s), "setting_change"))
                pp = pm
    return sorted(set(ev))


def ctx_rule(corpus, group):
    if corpus == "swechat" and group in ("codex", "gemini"):
        return "usage_in"
    if corpus == "aiv_cu" and str(group).startswith("gemini"):
        return "usage_in"
    return "sum"


def build_session(g_all, corpus, group, raw):
    """One session's rows (sorted by seq). Returns dict with series, anchors, ts, harness events; None if ineligible."""
    calls_all = g_all["kind"].to_numpy() == "call"
    main_mask = ~g_all["is_subagent"].to_numpy()
    session_level_sub = False
    if (calls_all & main_mask).sum() == 0 and calls_all.sum() > 0:
        main_mask = np.ones(len(g_all), bool)
        session_level_sub = True
    g = g_all[main_mask]
    kinds = g["kind"].to_numpy()
    ci = np.flatnonzero(kinds == "call")
    n_calls = len(ci)
    info = {"n_calls": n_calls, "session_level_subagent": session_level_sub}
    if n_calls < PREREG["min_calls_per_session"]:
        return info, None
    seq = g["seq"].to_numpy()
    tms = g["tms"].to_numpy()
    # results by call_id over the whole session (results of main calls are main-thread rows)
    rk = g_all[g_all["kind"] == "result"]
    rmap = {}
    for cid, i in zip(rk["call_id"].to_numpy(), range(len(rk))):
        if isinstance(cid, str) and cid not in rmap:
            rmap[cid] = i
    r_tms = rk["tms"].to_numpy(); r_len = rk["text_len"].to_numpy(); r_ne = rk["native_error"].to_numpy(); r_mk = rk["marker"].to_numpy()
    cids = g["call_id"].to_numpy()[ci]
    cseq = seq[ci].astype(np.int64)
    cts = tms[ci]
    xds = g["xd"].to_numpy()
    lat = np.full(n_calls, np.nan); rlen = np.full(n_calls, np.nan); err = np.full(n_calls, np.nan)
    neg_lat = 0
    for j, cid in enumerate(cids):
        r = rmap.get(cid)
        if corpus == "aiv_cu":
            tm = xds[ci[j]].get("timing")
            if isinstance(tm, dict):
                for key in ("server_timing_dur_ms", "dur_ms", "server_timing_dur"):
                    if tm.get(key) is not None:
                        try:
                            lat[j] = float(tm[key])
                        except (TypeError, ValueError):
                            pass
                        break
        if r is None:
            continue
        if corpus != "aiv_cu" and not np.isnan(cts[j]) and not np.isnan(r_tms[r]):
            d = r_tms[r] - cts[j]
            if d >= 0:
                lat[j] = d
            else:
                neg_lat += 1
        rlen[j] = r_len[r] if not pd.isna(r_len[r]) else 0.0
        ne = r_ne[r]
        err[j] = 1.0 if (ne is True or (ne is not None and not pd.isna(ne) and bool(ne)) or isinstance(r_mk[r], str)) else 0.0
    gap = np.full(n_calls, np.nan)
    d = np.diff(cts)
    neg_gap = int(np.nansum(d < 0))
    d[d < 0] = np.nan
    gap[1:] = d
    # thinking chars: main-thread assistant/call events, attributed to the next call
    th = np.array([float(x.get("thinking_chars") or x.get("reasoning_chars") or 0) if k in ("assistant", "call") else 0.0
                   for x, k in zip(xds, kinds)])
    cum = np.cumsum(th)
    cc = cum[ci]
    thinking = np.diff(np.concatenate([[0.0], cc]))
    # tool categories
    tools = g["tool"].to_numpy()[ci]
    tools = np.array([t if isinstance(t, str) else "none" for t in tools], dtype=object)
    cnt = Counter(tools)
    top = [t for t, _ in sorted(cnt.items(), key=lambda x: (-x[1], x[0]))[:7]]
    cats = top + (["other"] if len(cnt) > 7 else [])
    code = np.array([top.index(t) if t in top else len(top) for t in tools], dtype=np.int64)
    series = {}
    for name, arr in (("latency", lat), ("gap", gap), ("result_len", rlen), ("thinking", thinking)):
        ok = ~np.isnan(arr)
        series[name] = (np.log1p(arr[ok]), cseq[ok], cts[ok], np.flatnonzero(ok))
    ok = ~np.isnan(err)
    series["err"] = (err[ok], cseq[ok], cts[ok], np.flatnonzero(ok))
    series["tool"] = (code, cseq, cts, np.arange(n_calls))
    # usage per API response (main thread)
    u = g[g["usage_in"].notna()]
    if len(u):
        key = np.where(u["api_msg_id"].notna().to_numpy(), u["api_msg_id"].astype(object).to_numpy(),
                       ["row%d" % s for s in u["seq"].to_numpy()])
        uu = pd.DataFrame({"key": key, "seq": u["seq"].to_numpy(), "tms": u["tms"].to_numpy(),
                           "ui": u["usage_in"].to_numpy(), "uo": u["usage_out"].to_numpy(),
                           "cr": u["usage_cache_read"].fillna(0).to_numpy(), "cw": u["usage_cache_create"].fillna(0).to_numpy()})
        agg = uu.groupby("key", sort=False).agg(seq=("seq", "min"), tms=("tms", "first"), ui=("ui", "first"), uo=("uo", "max"),
                                                 cr=("cr", "first"), cw=("cw", "first")).sort_values("seq")
        rseq = agg["seq"].to_numpy().astype(np.int64); rts = agg["tms"].to_numpy()
        ctx = agg["ui"].to_numpy() + ((agg["cr"].to_numpy() + agg["cw"].to_numpy()) if ctx_rule(corpus, group) == "sum" else 0)
        for name, arr in (("ctx", ctx), ("usage_in", agg["ui"].to_numpy()), ("usage_out", agg["uo"].to_numpy())):
            arr = arr.astype(float)
            ok = ~np.isnan(arr) & (arr >= 0)
            series[name] = (np.log1p(arr[ok]), rseq[ok], rts[ok], None)
    ev = harness_events(g, corpus, group, raw)
    info.update({"neg_latency": neg_lat, "neg_gap": neg_gap, "n_usage_responses": int(len(series.get("ctx", ([],))[0]))})
    return info, {"series": series, "cats": cats, "events": ev, "n_calls": n_calls, "call_seq": cseq, "tool_codes": code}


# ----------------------------------------------------------------------------------------------------------- analysis
def window_bounds(anchors, j):
    n = len(anchors)
    return anchors[max(0, j - W)], anchors[min(n - 1, j + W - 1)]


def contains(ev_sorted, lo, hi, tight=False):
    if len(ev_sorted) == 0:
        return np.zeros(np.shape(lo), bool)
    if tight:  # (lo, hi]
        return (np.searchsorted(ev_sorted, hi, "right") - np.searchsorted(ev_sorted, lo, "right")) > 0
    return (np.searchsorted(ev_sorted, hi, "right") - np.searchsorted(ev_sorted, lo, "left")) > 0


def analyse_session(sess, corpus_i, sess_i):
    """Run the detector (and shuffle control) on every eligible series; annotate change points with co-occurrence."""
    out = {}
    ev = sess["events"]
    ev_by = defaultdict(list)
    for s, t in ev:
        ev_by[t].append(s)
    ev_by = {t: np.array(sorted(v), dtype=np.int64) for t, v in ev_by.items()}
    harness_all = np.array(sorted(s for s, t in ev if t in HARNESS_TYPES), dtype=np.int64)
    broad_all = np.array(sorted(s for s, t in ev if t not in POSTHOC_TYPES), dtype=np.int64)
    for si, name in enumerate(SERIES):
        if name not in sess["series"]:
            continue
        x, anchors, tts, call_idx = sess["series"][name]
        n = len(x)
        if n < PREREG["min_points_per_series"]:
            out[name] = {"eligible": False}
            continue
        det = detect(name, x, sess["cats"] if name == "tool" else None)
        rng = np.random.default_rng([SEED, corpus_i, sess_i, si])
        xs = x[rng.permutation(n)]
        det_sh = detect(name, xs, None)
        rng2 = np.random.default_rng([SEED, corpus_i, sess_i, si, 1])
        blocks = [np.arange(b0, min(b0 + MS, n)) for b0 in range(0, n, MS)]
        xb = x[np.concatenate([blocks[i] for i in rng2.permutation(len(blocks))])]
        det_bl = detect(name, xb, None)
        rec = {"eligible": True, "n": n, "degenerate": det["degenerate"], "shuffle_degenerate": det_sh["degenerate"],
               "shuffle_ncp": 0 if det_sh["degenerate"] else len(det_sh["cps"]),
               "block_ncp": 0 if det_bl["degenerate"] else len(det_bl["cps"])}
        if det["degenerate"]:
            out[name] = rec
            continue
        rec["sigma"] = det["sigma"]; rec["lag1"] = det["lag1"]
        # chance positions
        js = np.arange(MS, n - MS + 1)
        lo = anchors[np.maximum(0, js - W)]; hi = anchors[np.minimum(n - 1, js + W - 1)]
        tlo = anchors[js - 1]; thi = anchors[np.minimum(js, n - 1)]
        chance = {}
        for t in ALL_TYPES:
            e = ev_by.get(t, np.array([], np.int64))
            chance[t] = (float(contains(e, lo, hi).mean()) if len(js) else 0.0, float(contains(e, tlo, thi, True).mean()) if len(js) else 0.0)
        ch_none = float((~contains(harness_all, lo, hi)).mean()) if len(js) else 0.0
        ch_none_b = float((~contains(broad_all, lo, hi)).mean()) if len(js) else 0.0
        ch_none_t = float((~contains(harness_all, tlo, thi, True)).mean()) if len(js) else 0.0
        idle_pos = (tts[js] - tts[js - 1]) >= PREREG["idle_gap_s"] * 1000 if len(js) else np.array([], bool)
        ch_idle = float(np.nanmean(idle_pos)) if len(js) else 0.0
        cps = []
        for c in det["cps"]:
            k = c["k"]
            wlo, whi = window_bounds(anchors, k)
            c2 = dict(c)
            c2["pos_rel"] = k / n
            c2["in_window"] = {t: bool(contains(ev_by.get(t, np.array([], np.int64)), wlo, whi)) for t in ALL_TYPES}
            c2["in_tight"] = {t: bool(contains(ev_by.get(t, np.array([], np.int64)), anchors[k - 1], anchors[k], True)) for t in ALL_TYPES}
            c2["none"] = not bool(contains(harness_all, wlo, whi))
            c2["none_broad"] = not bool(contains(broad_all, wlo, whi))
            c2["none_tight"] = not bool(contains(harness_all, anchors[k - 1], anchors[k], True))
            dt = tts[k] - tts[k - 1]
            c2["idle"] = bool(dt >= PREREG["idle_gap_s"] * 1000) if not np.isnan(dt) else False
            c2["call_index"] = int(call_idx[k]) if call_idx is not None else None
            # POSTHOC P1: immediate step at the change point and the tool mix of the two adjacent segments
            if name in CONT_SERIES:
                c2["step_log"] = float(x[k] - x[k - 1])
                c2["min_step_log_window"] = float(np.min(np.diff(x[max(0, k - W):min(n, k + W)])))
            if call_idx is not None and name != "tool":
                ks_all = [cc["k"] for cc in det["cps"]]
                t_ = ks_all.index(k)
                b_lo = ks_all[t_ - 1] if t_ > 0 else 0
                b_hi = ks_all[t_ + 1] if t_ + 1 < len(ks_all) else n
                codes = sess["tool_codes"]
                L = codes[call_idx[b_lo:k]]; R = codes[call_idx[k:b_hi]]
                nc = len(sess["cats"])
                pL = np.bincount(L, minlength=nc) / max(len(L), 1); pR = np.bincount(R, minlength=nc) / max(len(R), 1)
                c2["tool_tv"] = float(0.5 * np.abs(pR - pL).sum())
                c2["tool_gain_cat"] = sess["cats"][int(np.argmax(pR - pL))]
            cps.append(c2)
        rec.update({"cps": cps, "chance": chance, "chance_none": ch_none, "chance_none_broad": ch_none_b,
                    "chance_none_tight": ch_none_t, "chance_idle": ch_idle})
        out[name] = rec
    return out


def wilson_d(k, n):
    p, lo, hi = stats.wilson(k, n)
    return {"k": int(k), "n": int(n), "rate": p, "lo": lo, "hi": hi}


def summarize(corpus, sessions, results, public=True):
    """Aggregate per series for one corpus (or a group subset)."""
    S = {}
    for name in SERIES:
        recs = [(sid, r[name]) for sid, r in results.items() if name in r and r[name].get("eligible")]
        nondeg = [(sid, r) for sid, r in recs if not r["degenerate"]]
        n_el = len(recs)
        n_cp = sum(1 for _, r in nondeg if r["cps"])
        n_sh = sum(1 for _, r in recs if r["shuffle_ncp"] > 0)
        n_bl = sum(1 for _, r in recs if r["block_ncp"] > 0)
        d = {"n_series_eligible": n_el, "n_degenerate": n_el - len(nondeg),
             "sessions_with_cp": wilson_d(n_cp, n_el),
             "sessions_with_cp_among_nondegenerate": wilson_d(n_cp, len(nondeg)),
             "shuffle_control_sessions_with_cp": wilson_d(n_sh, n_el),
             "block_shuffle_control_sessions_with_cp": wilson_d(n_bl, n_el)}
        if not nondeg:
            S[name] = d
            continue
        ncps = [len(r["cps"]) for _, r in nondeg]
        d["n_cp_per_series"] = stats.describe(ncps)
        d["n_cp_total"] = int(sum(ncps))
        # P4: change points pinned to the minimum-segment edge (k == 10 or k == n - 10)
        d["posthoc_n_cp_at_min_segment_edge"] = int(sum(1 for _, r in nondeg for c in r["cps"] if c["k"] in (MS, r["n"] - MS)))
        d["n_cp_hist"] = {str(k): v for k, v in sorted(Counter(min(c, 10) for c in ncps).items())}
        d["shuffle_n_cp_total"] = int(sum(r["shuffle_ncp"] for _, r in recs))
        d["block_shuffle_n_cp_total"] = int(sum(r["block_ncp"] for _, r in recs))
        lag = [r["lag1"] for _, r in nondeg if r.get("lag1") is not None]
        d["lag1_autocorr"] = stats.describe(lag) if lag else {"n": 0}
        allc = [(sid, r, c) for sid, r in nondeg for c in r["cps"]]
        if not allc:
            S[name] = d
            continue
        deltas = np.array([c["delta"] for _, _, c in allc])
        d["delta_abs"] = stats.describe(np.abs(deltas))
        d["n_up"] = int((deltas > 0).sum()); d["n_down"] = int((deltas < 0).sum())
        if name in CONT_SERIES:
            d["delta_sigma_abs"] = stats.describe([abs(c["delta_sigma"]) for _, _, c in allc])
            d["factor_exp_abs_delta"] = stats.describe(np.exp(np.abs(deltas)))
        if name == "tool" and public:
            d["top_gain_category"] = dict(Counter(c["top_gain_cat"] for _, _, c in allc).most_common(12))
        d["pos_rel"] = stats.describe([c["pos_rel"] for _, _, c in allc])
        prim = [min(r["cps"], key=lambda c: c["depth"]) for _, r in nondeg if r["cps"]]
        d["primary_cp_delta_abs"] = stats.describe([abs(c["delta"]) for c in prim])
        d["primary_cp_pos_rel"] = stats.describe([c["pos_rel"] for c in prim])
        # co-occurrence, session-clustered
        by_sess = defaultdict(list)
        for sid, r, c in allc:
            by_sess[sid].append((r, c))
        sids = list(by_sess)
        co = {}
        for t in ALL_TYPES:
            obs = [sum(c["in_window"][t] for r, c in by_sess[s]) for s in sids]
            exp = [sum(r["chance"][t][0] for r, c in by_sess[s]) for s in sids]
            obs_t = [sum(c["in_tight"][t] for r, c in by_sess[s]) for s in sids]
            exp_t = [sum(r["chance"][t][1] for r, c in by_sess[s]) for s in sids]
            ncp = [len(by_sess[s]) for s in sids]
            if sum(obs) == 0 and sum(exp) == 0:
                co[t] = {"obs": 0, "exp": 0.0}
                continue
            co[t] = {"obs": int(sum(obs)), "exp": float(sum(exp)), "n_cp": int(sum(ncp)),
                     "rate": stats.cluster_rate(obs, ncp), "obs_over_exp": stats.cluster_rate(obs, exp),
                     "tight_obs": int(sum(obs_t)), "tight_exp": float(sum(exp_t)),
                     "tight_obs_over_exp": stats.cluster_rate(obs_t, exp_t)}
        d["cooccur"] = co
        ncp = [len(by_sess[s]) for s in sids]
        for key, chk in (("none", "chance_none"), ("none_broad", "chance_none_broad"), ("none_tight", "chance_none_tight")):
            obs = [sum(c[key] for r, c in by_sess[s]) for s in sids]
            exp = [sum(r[chk] for r, c in by_sess[s]) for s in sids]
            d["no_harness_" + key.replace("none_", "").replace("none", "window")] = {
                "obs": int(sum(obs)), "exp": float(sum(exp)), "n_cp": int(sum(ncp)),
                "rate": stats.cluster_rate(obs, ncp), "obs_over_exp": stats.cluster_rate(obs, exp)}
        obs = [sum(c["idle"] for r, c in by_sess[s]) for s in sids]
        exp = [sum(r["chance_idle"] for r, c in by_sess[s]) for s in sids]
        d["idle_at_cp"] = {"obs": int(sum(obs)), "exp": float(sum(exp)), "rate": stats.cluster_rate(obs, ncp),
                           "obs_over_exp": stats.cluster_rate(obs, exp)}
        # no-harness subset sizes vs harness subset
        nh = [c for _, _, c in allc if c["none"]]
        hh = [c for _, _, c in allc if not c["none"]]
        for lab, sub in (("no_harness_cps", nh), ("harness_cps", hh)):
            if sub:
                dd = np.array([c["delta"] for c in sub])
                e = {"n": len(sub), "delta_abs": stats.describe(np.abs(dd)), "n_up": int((dd > 0).sum()),
                     "n_down": int((dd < 0).sum()), "idle": int(sum(c["idle"] for c in sub)),
                     "sessions": len({sid for sid, _, c in allc if (c["none"] if lab == "no_harness_cps" else not c["none"]) })}
                if name in CONT_SERIES:
                    e["delta_sigma_abs"] = stats.describe([abs(c["delta_sigma"]) for c in sub])
                d[lab] = e
        # by direction (up = post-change mean larger): co-occurrence for a few types, no-harness, idle
        bydir = {}
        for lab, sel in (("up", lambda c: c["delta"] > 0), ("down", lambda c: c["delta"] < 0)):
            bs = defaultdict(list)
            for sid, r, c in allc:
                if sel(c):
                    bs[sid].append((r, c))
            if not bs:
                continue
            ss = list(bs)
            nc = [len(bs[s]) for s in ss]
            e = {"n_cp": int(sum(nc)), "n_sessions": len(ss)}
            for t in ["compaction", "context_clear", "user_turn", "model_switch", "subagent_start", "resume", "version_change",
                      "api_error", "interrupt", "tool_timeout", "slash_command", "synthetic_msg"]:
                o = [sum(c["in_window"][t] for r, c in bs[s]) for s in ss]
                x = [sum(r["chance"][t][0] for r, c in bs[s]) for s in ss]
                if sum(o) or sum(x):
                    e[t] = {"obs": int(sum(o)), "exp": float(sum(x)), "obs_over_exp": stats.cluster_rate(o, x)}
            o = [sum(c["none"] for r, c in bs[s]) for s in ss]
            x = [sum(r["chance_none"] for r, c in bs[s]) for s in ss]
            e["no_harness_window"] = {"obs": int(sum(o)), "exp": float(sum(x)), "rate": stats.cluster_rate(o, nc),
                                      "obs_over_exp": stats.cluster_rate(o, x)}
            o = [sum(c["idle"] for r, c in bs[s]) for s in ss]
            x = [sum(r["chance_idle"] for r, c in bs[s]) for s in ss]
            e["idle"] = {"obs": int(sum(o)), "exp": float(sum(x)), "obs_over_exp": stats.cluster_rate(o, x)}
            if name in CONT_SERIES:
                e["delta_sigma_abs"] = stats.describe([abs(c["delta_sigma"]) for s in ss for r, c in bs[s]])
            bydir[lab] = e
        d["by_direction"] = bydir
        # POSTHOC P1: tool-mix shift across call-series change points, by direction x harness
        if name in CALL_SERIES and name != "tool":
            ph = {}
            for dl, dsel in (("up", lambda c: c["delta"] > 0), ("down", lambda c: c["delta"] < 0)):
                for hl, hsel in (("no_harness", lambda c: c["none"]), ("harness", lambda c: not c["none"])):
                    sub = [c for _, _, c in allc if dsel(c) and hsel(c) and "tool_tv" in c]
                    if not sub:
                        continue
                    e = {"n": len(sub), "tool_tv": stats.describe([c["tool_tv"] for c in sub])}
                    if public:
                        e["tool_gain_cat"] = dict(Counter(c["tool_gain_cat"] for c in sub).most_common(8))
                    ph[f"{dl}_{hl}"] = e
            d["posthoc_tool_mix_at_cp"] = ph
        if name in CONT_SERIES:
            d["posthoc_step_log_at_cp"] = {
                lab: stats.describe([c["step_log"] for _, _, c in allc if sel(c)])
                for lab, sel in (("up_no_harness", lambda c: c["delta"] > 0 and c["none"]),
                                 ("up_harness", lambda c: c["delta"] > 0 and not c["none"]),
                                 ("down_no_harness", lambda c: c["delta"] < 0 and c["none"]),
                                 ("down_harness", lambda c: c["delta"] < 0 and not c["none"]))}
        # sessions whose every change point has no harness event
        d["sessions_all_cps_no_harness"] = int(sum(1 for s in sids if all(c["none"] for r, c in by_sess[s])))
        d["n_sessions_with_cp"] = len(sids)
        S[name] = d
    return S


def cross_series(results):
    """For call-indexed series pairs: fraction of A's change points within +-3 calls of a B change point vs chance."""
    tol = PREREG["cross_series_tolerance_calls"]
    out = {}
    for a in CALL_SERIES:
        for b in CALL_SERIES:
            if a == b:
                continue
            obs, exp, ncp = [], [], []
            for sid, r in results.items():
                ra, rb = r.get(a), r.get(b)
                if not (ra and rb and ra.get("eligible") and rb.get("eligible")) or ra["degenerate"] or rb["degenerate"]:
                    continue
                if not ra["cps"]:
                    continue
                n_calls = r["_n_calls"]
                bc = np.array(sorted(c["call_index"] for c in rb["cps"]), dtype=np.int64)
                ac = np.array([c["call_index"] for c in ra["cps"]], dtype=np.int64)
                if len(bc):
                    o = int(sum(np.any(np.abs(bc - x) <= tol) for x in ac))
                    pos = np.arange(MS, n_calls - MS + 1)
                    near = (np.searchsorted(bc, pos + tol, "right") - np.searchsorted(bc, pos - tol, "left")) > 0
                    e = float(near.mean()) * len(ac) if len(pos) else 0.0
                else:
                    o, e = 0, 0.0
                obs.append(o); exp.append(e); ncp.append(len(ac))
            if not ncp:
                continue
            out[f"{a}->{b}"] = {"n_sessions": len(ncp), "n_cp_a": int(sum(ncp)), "obs": int(sum(obs)), "exp": float(sum(exp)),
                                "rate": stats.cluster_rate(obs, ncp), "obs_over_exp": stats.cluster_rate(obs, exp)}
    return out


def ctx_down_no_harness(results, groups, public):
    """POSTHOC P2: every ctx down-shift with no primary harness event in the window."""
    rows = []
    for sid, r in results.items():
        rr = r.get("ctx")
        if not rr or not rr.get("eligible") or rr["degenerate"]:
            continue
        for c in rr["cps"]:
            if c["delta"] < 0 and c["none"]:
                rows.append({"_sid": sid, "session_id": sid if public else None, "group": groups.get(sid) if public else None,
                             "k": c["k"], "n": rr["n"], "pos_rel": c["pos_rel"], "delta_log": c["delta"],
                             "step_log": c["step_log"], "min_step_log_window": c["min_step_log_window"],
                             "idle": c["idle"], "other_system_in_window": c["in_window"]["other_system"],
                             "synthetic_msg_in_window": c["in_window"]["synthetic_msg"],
                             "at_min_segment_edge": c["k"] in (MS, rr["n"] - MS)})
    n_sess = len({x["_sid"] for x in rows})
    for x in rows:
        x.pop("_sid")
        if not public:
            x.pop("session_id"); x.pop("group")
    out = {"n": len(rows), "n_sessions": n_sess,
           "delta_log": stats.describe([x["delta_log"] for x in rows]) if rows else {"n": 0},
           "min_step_log_window": stats.describe([x["min_step_log_window"] for x in rows]) if rows else {"n": 0},
           "n_min_step_below_log_half": int(sum(x["min_step_log_window"] < math.log(0.5) for x in rows)),
           "n_other_system_in_window": int(sum(x["other_system_in_window"] for x in rows)),
           "n_synthetic_msg_in_window": int(sum(x["synthetic_msg_in_window"] for x in rows)),
           "n_at_min_segment_edge": int(sum(x["at_min_segment_edge"] for x in rows)),
           "n_sharp_and_not_edge_and_no_synthetic": int(sum(x["min_step_log_window"] < math.log(0.5) and not x["at_min_segment_edge"]
                                                            and not x["synthetic_msg_in_window"] for x in rows))}
    if public:
        out["rows"] = sorted(rows, key=lambda x: x["min_step_log_window"])
    return out


def examples(corpus, results, groups, k=12):
    rows = []
    for sid, r in results.items():
        for name in CONT_SERIES + ["err", "tool"]:
            rr = r.get(name)
            if not rr or not rr.get("eligible") or rr["degenerate"]:
                continue
            for c in rr["cps"]:
                if c["none"]:
                    size = abs(c.get("delta_sigma", c["delta"])) if name in CONT_SERIES else abs(c["delta"])
                    rows.append({"session_id": sid, "group": groups.get(sid), "series": name, "k": c["k"], "n": rr["n"],
                                 "delta": c["delta"], "delta_sigma": c.get("delta_sigma"), "idle": c["idle"],
                                 "pos_rel": c["pos_rel"], "top_gain_cat": c.get("top_gain_cat"), "_size": size})
    out = {}
    for name in CONT_SERIES + ["err", "tool"]:
        sub = sorted([x for x in rows if x["series"] == name], key=lambda x: -x["_size"])[:k]
        for x in sub:
            x.pop("_size")
        out[name] = sub
    return out


# ----------------------------------------------------------------------------------------------------------- driver
def run_corpus(corpus, corpus_i, fmt_map=None, raw_fn=None, public=True):
    path = os.path.join(CACHE, f"{corpus}_B.parquet")
    pf = pq.ParquetFile(path)
    cols = BASE_COLS + ["text"] + (["stderr"] if corpus == "aiv_cu" else [])
    infos, results, groups = {}, {}, {}
    ev_sessions = Counter(); ev_counts_eligible = Counter(); ev_pos = defaultdict(list)
    sess_i = 0
    seen = set()
    t0 = time.time()
    for rg in range(pf.num_row_groups):
        tbl = pf.read_row_group(rg, columns=cols)
        df = prepare(tbl, corpus, fmt_map)
        del tbl
        for sid, g in df.groupby("session_id", sort=True):
            assert sid not in seen, "session spans row groups"
            seen.add(sid)
            g = g.sort_values("seq")
            grp = g["group"].iat[0]
            groups[sid] = grp
            raw = None
            calls_main = int(((g["kind"] == "call") & (~g["is_subagent"])).sum())
            if raw_fn is not None and calls_main >= PREREG["min_calls_per_session"]:
                raw = raw_fn(sid, grp)
            info, sess = build_session(g, corpus, grp, raw)
            info["group"] = grp
            info["raw_scanned"] = raw is not None
            infos[sid] = info
            if sess is None:
                continue
            for _, t in sess["events"]:
                ev_counts_eligible[t] += 1
            for t in {t for _, t in sess["events"]}:
                ev_sessions[t] += 1
            smax = max(int(g["seq"].max()), 1)
            for sq, t in sess["events"]:
                ev_pos[t].append(sq / smax)
            r = analyse_session(sess, corpus_i, sess_i)
            r["_n_calls"] = sess["n_calls"]
            results[sid] = r
            sess_i += 1
        del df
        print(f"  {corpus} rg {rg + 1}/{pf.num_row_groups} sessions {len(infos)} eligible {len(results)} "
              f"{time.time() - t0:.0f}s", flush=True)
    return infos, results, groups, ev_counts_eligible, ev_sessions, ev_pos


def synthetic_calibration():
    rng = np.random.default_rng([SEED, 99])
    out = {}
    for rho in (0.0, 0.1, 0.2, 0.3, 0.5, 0.7):
        for n in (50, 200, 1000):
            k = 0
            for _ in range(300):
                e = rng.normal(size=n)
                x = np.empty(n)
                x[0] = e[0] / math.sqrt(max(1e-9, 1 - rho * rho))
                for t in range(1, n):
                    x[t] = rho * x[t - 1] + e[t]
                r = detect("gap", x)
                k += (not r["degenerate"]) and len(r["cps"]) > 0
            out[f"rho={rho},n={n}"] = wilson_d(k, 300)
    return out


def main():
    t_start = time.time()
    pop = pd.read_parquet(os.path.join(CACHE, "swechat_population.parquet"), columns=["session_id", "format"])
    fmt_map = dict(zip(pop.session_id, pop.format))
    out = {"meta": {"script": "analysis/probes/phase_c_changepoints.py", "prereg": PREREG, "revisions": REVISIONS,
                    "harness_types_primary": HARNESS_TYPES, "harness_types_broad_extra": BROAD_EXTRA,
                    "harness_definitions": HARNESS_DEFS},
           "corpora": {}}

    # raw lookups ---------------------------------------------------------------------------------------------------
    raw_stats = {"swechat_files_scanned": 0, "swechat_files_missing": 0}

    def swe_raw(sid, grp):
        if grp != "claude_code":
            return None
        m = scan_cc_file(os.path.join(SWE_TX, f"{sid}.jsonl"))
        if m is None:
            raw_stats["swechat_files_missing"] += 1
            return None
        raw_stats["swechat_files_scanned"] += 1
        return {u: v[:3] for u, v in m.items()}

    print("scanning cc_local main files", flush=True)
    ccl_map, ccl_scan = scan_cc_local_mains()
    raw_stats["cc_local"] = ccl_scan

    def ccl_raw(sid, grp):
        return ccl_map

    plan = [("swechat", fmt_map, swe_raw, True), ("cc_local", None, ccl_raw, False), ("aiv_cc", None, None, True),
            ("aiv_cu", None, None, True)]
    all_results = {}
    for ci_, (corpus, fm, rf, public) in enumerate(plan):
        print(f"corpus {corpus}", flush=True)
        infos, results, groups, evc, evs, evp = run_corpus(corpus, ci_, fm, rf, public)
        all_results[corpus] = (infos, results, groups)
        inv = {"sessions_in_B": len(infos),
               "sessions_eligible": len(results),
               "main_calls_per_session": stats.describe([v["n_calls"] for v in infos.values()]),
               "session_level_subagent_sessions_eligible": int(sum(1 for s, v in infos.items() if s in results and v["session_level_subagent"])),
               "harness_event_counts_in_eligible_sessions": dict(evc),
               "eligible_sessions_with_event_type": dict(evs),
               "posthoc_event_pos_rel_in_session": {t: stats.describe(v, qs=(0.0, 0.05, 0.25, 0.5, 0.75, 0.95, 1.0))
                                                    for t, v in sorted(evp.items())},
               "neg_latency_dropped": int(sum(v.get("neg_latency", 0) for v in infos.values())),
               "neg_gap_dropped": int(sum(v.get("neg_gap", 0) for v in infos.values())),
               "raw_scanned_sessions": int(sum(1 for v in infos.values() if v["raw_scanned"]))}
        by_group = Counter(v["group"] for s, v in infos.items() if s in results)
        inv["eligible_by_group"] = dict(by_group) if public else {"n_groups": len(by_group)}
        inv["sessions_by_group"] = dict(Counter(v["group"] for v in infos.values())) if public else {"n_groups": len(set(v["group"] for v in infos.values()))}
        cdict = {"inventory": inv, "series": summarize(corpus, None, results, public)}
        if corpus == "swechat":
            cdict["by_format"] = {}
            for grp in sorted(set(groups[s] for s in results)):
                sub = {s: r for s, r in results.items() if groups[s] == grp}
                if len(sub) >= 5:
                    cdict["by_format"][grp] = summarize(corpus, None, sub, public)
        if public:
            cdict["inventory"]["model_switch_pairs_eligible_sessions"] = [
                {"from": a, "to": b, "count": c} for (a, b), c in MODEL_PAIRS[corpus].most_common(30)]
        else:
            cdict["inventory"]["model_switch_pairs_eligible_sessions"] = {"n_distinct_pairs": len(MODEL_PAIRS[corpus]),
                                                                         "n_switches": int(sum(MODEL_PAIRS[corpus].values()))}
        if corpus == "aiv_cu":
            st = pd.read_parquet(os.path.join(CACHE, "aiv_cu_sessions.parquet"), columns=["n_turns", "n_synthetic_turns"])
            vc = st["n_turns"].value_counts()
            cdict["inventory"]["all_sessions_turn_count"] = {
                "n_sessions": int(len(st)), "describe": stats.describe(st["n_turns"].to_numpy()),
                "top_values": {str(int(k)): int(v) for k, v in vc.head(10).items()},
                "n_turns_40_to_43": int(st["n_turns"].between(40, 43).sum()),
                "n_turns_gt_43": int((st["n_turns"] > 43).sum())}
            cdict["by_stratum"] = {}
            for grp in sorted(set(groups[s] for s in results)):
                sub = {s: r for s, r in results.items() if groups[s] == grp}
                if len(sub) >= 5:
                    cdict["by_stratum"][grp] = summarize(corpus, None, sub, public)
        cdict["cross_series"] = cross_series(results)
        if public:
            cdict["examples_no_harness_largest"] = examples(corpus, results, groups)
        cdict["posthoc_ctx_down_no_harness"] = ctx_down_no_harness(results, groups, public)
        # per-session sessions-with-event-type (eligible) for context of chance rates
        out["corpora"][corpus] = cdict
        print(f"  done {corpus} {time.time() - t_start:.0f}s", flush=True)

    # whowhen: eligibility only (no timestamps; call counts)
    w = pq.read_table(os.path.join(CACHE, "whowhen_B.parquet"), columns=["session_id", "kind"]).to_pandas()
    nc = w[w.kind == "call"].groupby("session_id").size()
    out["corpora"]["whowhen"] = {"inventory": {"sessions_in_B": int(w.session_id.nunique()),
                                               "calls_per_session": stats.describe(nc.to_numpy()),
                                               "sessions_eligible": int((nc >= PREREG["min_calls_per_session"]).sum())}}
    out["meta"]["raw_scans"] = raw_stats
    out["synthetic_calibration_ar1"] = synthetic_calibration()
    out["meta"]["runtime_s"] = round(time.time() - t_start, 1)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print("wrote", OUT, f"{time.time() - t_start:.0f}s")


if __name__ == "__main__":
    main()
