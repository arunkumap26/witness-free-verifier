"""Phase C lens `outliers`: multi-axis outlier sessions, per corpus, from the Phase B IR caches.

Writes RAW COUNTS ONLY to analysis/out/phase_c/outliers.json (interpretation: analysis/notes/outliers.md).

Method (all choices fixed in PREREG below before any outcome was computed):
  1. For every session of <corpus>_B.parquet compute session features from the IR (common features + a few
     corpus-specific ones). Text is reduced to lengths / flags inside this script; no content leaves it.
  2. Per corpus and feature: transform (log10(1+x) for counts, sizes and durations; log10(x) for ratios; raw for
     shares), then robust z = (x - median) / (1.4826 * MAD); if MAD == 0, (x - median) / (1.253314 * meanAD); if both
     are 0 the feature is constant in that corpus and dropped (recorded). Missing feature values are never extreme.
  3. A session is extreme on a feature when |z| > 3.5; it is a multi-axis outlier when extreme on >= 3 features.
  4. Profile the outliers (strata, model, length tercile, flags for errors / subagents / truncation / redaction /
     timing anomalies, corpus labels), the axis combinations, pairwise co-extremity vs independence, a
     column-permutation null for the >=3-axis count, and sensitivity variants (within-stratum z, no meanAD features).
  5. Pick 10 (swechat, aiv_cu) or 5 (cc_local, aiv_cc, whowhen) outliers and report their numbers.
     cc_local is PRIVATE: picks carry an alias, features and enum attributes only (no session id, no tool names
     outside the normalized built-in set, no text).

Run from the worktree root:
  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_c_outliers [--stage all|features|report]
The features stage writes per-session tables to $OUTLIERS_TMP (default: system temp dir), which can include
session ids of the private corpus, so they are kept out of analysis/out.
"""
import argparse
import json
import math
import os
import re
import tempfile
import time
from collections import Counter, defaultdict
from itertools import combinations

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from analysis.lib import stats
from analysis.lib.ir import error_marker

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
CACHE = os.path.join(ROOT, "cache")
OUT_DIR = os.path.join(ROOT, "out", "phase_c")
OUT_JSON = os.path.join(OUT_DIR, "outliers.json")
DATA = os.environ.get("SWARMS_DATA", "C:/Swarms/data")
INTER_DIR = os.environ.get("OUTLIERS_TMP", os.path.join(tempfile.gettempdir(), "phase_c_outliers"))

CORPORA = ["swechat", "cc_local", "aiv_cc", "aiv_cu", "whowhen"]
SMALL = {"cc_local", "aiv_cc", "whowhen"}

# ---------------------------------------------------------------------------------------------------------------------
# PRE-REGISTRATION (fixed before computing any outcome). Changes after the first run go to POSTHOC with a reason.
# ---------------------------------------------------------------------------------------------------------------------
TRUNC_RX = (r"\.\.\. \[\d+ lines omitted\] \.\.\.|\.\.\. \[TRUNCATED\] \.\.\.|Output too large[ .(]|<persisted-output>|"
            r"\(Results are truncated\.|IMPORTANT: The file content has been truncated\.|--- FILE CONTENT \(truncated\) ---|"
            r"\.\.\.\d+ bytes truncated\.\.\.|\.\.\. \[\d+ characters truncated\] \.\.\.|output was truncated\. Full output saved to")

PREREG = {
    "split": "B (Phase B caches); A is used only to calibrate the truncation regex (phrasings seen in split-A result text)",
    "z_threshold_abs": 3.5,
    "min_extreme_axes": 3,
    "robust_z": "z = (x - median) / (1.4826 * MAD) on the transformed value; if MAD == 0: (x - median) / (1.253314 * meanAD); "
                "if meanAD == 0 too, the feature is constant in that corpus and dropped. NaN values are never extreme.",
    "transforms": {"log1p": "log10(1 + x) for counts, character sizes, token counts and durations in seconds",
                   "logratio": "log10(x) for positive ratios (x <= 0 or undefined -> NaN)",
                   "raw": "shares / fractions in [0, 1]"},
    "picks": {"n_per_corpus": {"swechat": 10, "aiv_cu": 10, "cc_local": 5, "aiv_cc": 5, "whowhen": 5},
              "rank": "n_extreme desc, then sum over extreme axes of min(|z|, 20) desc, then session id (alias order for cc_local)"},
    "length_tercile": "terciles of n_events within the corpus B split (cuts at the 1/3 and 2/3 quantiles)",
    "group_reporting": "every attribute value with >= 5 sessions; smaller values pooled as '<small>'; rate = Wilson 95% (session is the unit)",
    "permutation_null": {"n_perm": 200, "seed": stats.SEED,
                         "rule": "permute each feature's z column independently across sessions (keeps every marginal, breaks "
                                 "cross-feature dependence); count sessions extreme on >= 3 features"},
    "co_extremity": "pairs of features: sessions extreme on both vs n_i * n_j / N under independence; listed when observed >= 5",
    "sensitivity": {"within_stratum": "z computed within stratum (swechat: content format; aiv_cu: stratum; cc_local: stratum; "
                                      "aiv_cc: month stratum; whowhen: split); strata with < 20 sessions get no within-stratum z",
                    "no_meanAD_features": "drop features whose corpus scale fell back to meanAD, recount"},
    "truncation_regex": TRUNC_RX,
    "truncation_rule": "result has extra.truncated == true OR result text matches truncation_regex (harness phrasings only)",
    "redaction_rule": "event text, args or command contains the substring 'REDACTED' (release redaction markers, all classes)",
    "error_marker_rule": "analysis.lib.ir.error_marker(result text) is not None",
    "usage_rule": "ir.py USAGE DEDUPE: rows with usage_in not null, grouped by (session, api_msg_id; a null id = its own response); "
                  "input/cache fields from the first row, output = max over rows. context = input + cache_read + cache_create, "
                  "except aiv_cu Gemini rows where usage_in already includes cached tokens: context = input + cache_create",
    "aiv_cu_sessions_table": "talk_only_share = n_talk_only_turns / n_turns from analysis/cache/aiv_cu_sessions.parquet",
    "swechat_sessions_table": "repo_id, cli_version, created month from data/swe-chat-pinned/sessions.parquet (attributes only)",
    "private": "cc_local outputs: aggregates; picks are aliased, carry numbers and enum attributes only",
}
POSTHOC = [  # changes made after any data was looked at, with reason
    {"id": "P1", "what": "native_err_frac denominator: results with native_error not null -> all results",
     "when": "after the first features pass, before any z score or outlier count was computed",
     "why": "descriptive check of the feature table: Claude Code writes is_error=false on only some results (e.g. cc_local "
            "B results: 25768 false, 1454 true, 9320 null), so the not-null denominator mixed tool families and gave a "
            "per-session median of 1.0 in cc_local; all-results is the uniform definition"},
    {"id": "P2", "what": "permutation null extended to tail counts (sessions with >= k extreme axes, k = 3..12) and the max",
     "when": "after the first report", "why": "observed >=3-axis counts sat at or below the >=3 null in 3 corpora while the "
     "histograms showed sessions with 10-21 extreme axes; the >=3 count alone cannot show concentration"},
    {"id": "P3", "what": "per-feature extreme counts by stratum; stratum breakdown of the top axis combos",
     "when": "after the first report", "why": "pooled outliers were dominated by minority formats/strata"},
    {"id": "P4", "what": "attribute profiles of the within-stratum outlier sets", "when": "after the first report",
     "why": "same reason as P3: separate format effects from within-format structure"},
    {"id": "P5", "what": "corpus followups: cc_local top-tool cluster and zero-thinking sessions; aiv_cu population turn-count "
     "spikes, bootstrap-only sessions, n_models >= 2 model sets; aiv_cc result rows x duration ratio; swechat repo x format and "
     "error-marker names of picks", "when": "after the first report", "why": "surprises seen in the first report's picks/profiles"},
    {"id": "P6", "what": "session descriptors (not z features): last event kind, ends with an unanswered call, the largest "
     "call->result gap with its tool and error-marker name, aiv_cc failed-resume result rows (num_turns 0 and duration_ms 0); "
     "flag_ends_unanswered_call and flag_failed_resume_rows added to the profiles", "when": "after inspecting the IR events of "
     "swechat picks 1, 2, 8 and aiv_cc picks 2, 3", "why": "pick 1/2 were a permission prompt answered by a rejection hours later; "
     "pick 8 ends on a call with no result; aiv_cc picks carry failed-resume result rows days after the run"},
    {"id": "P7", "what": "call->result gap counts in 2-second bins around 120 s and 600 s (all paired calls and shell calls), "
     "pooled per corpus with session counts", "when": "after the P6 run", "why": "3 of 5 cc_local picks had their largest "
     "call->result gap at 600.76-600.96 s; checks whether gaps pile up at fixed harness timeouts"},
]

# feature name -> (transform, corpora it applies to or 'all', description)
ALL = set(CORPORA)
TIMED = ALL - {"whowhen"}
USAGE = {"swechat", "cc_local", "aiv_cc", "aiv_cu"}
FEATURES = {
    "n_events": ("log1p", ALL, "IR events in the session"),
    "n_calls": ("log1p", ALL, "call events"),
    "n_tools_distinct": ("log1p", ALL, "distinct normalized tool names among calls"),
    "top_tool_share": ("raw", ALL, "share of calls on the most used tool"),
    "shell_share": ("raw", ALL, "share of calls with tool == 'shell'"),
    "unpaired_call_frac": ("raw", ALL, "calls whose call_id has no result in the session"),
    "orphan_result_frac": ("raw", ALL, "results whose call_id is null or matches no call in the session"),
    "native_err_frac": ("raw", ALL, "results with native_error true / results (POSTHOC P1)"),
    "marker_err_frac": ("raw", ALL, "results with an ir.error_marker match / results"),
    "result_chars_median": ("log1p", ALL, "median result text length (chars)"),
    "result_chars_max": ("log1p", ALL, "max result text length (chars)"),
    "assistant_chars_total": ("log1p", ALL, "sum of assistant text length"),
    "args_chars_median": ("log1p", ALL, "median call args JSON length"),
    "user_events": ("log1p", ALL, "kind == user events"),
    "system_share": ("raw", ALL, "kind == system / events"),
    "meta_share": ("raw", ALL, "kind == meta / events"),
    "subagent_share": ("raw", ALL, "is_subagent events / events"),
    "trunc_frac": ("raw", ALL, "results matching the truncation rule / results"),
    "redacted_frac": ("raw", ALL, "events matching the redaction rule / events"),
    "max_identical_call": ("log1p", ALL, "count of the most repeated (tool, args) call"),
    "consec_dup_call_frac": ("raw", ALL, "calls identical in (tool, args) to the previous call / calls"),
    "thinking_chars_total": ("log1p", ALL, "sum of extra.thinking_chars / reasoning_chars"),
    "span_s": ("log1p", TIMED, "max(ts) - min(ts), seconds"),
    "gap_median_s": ("log1p", TIMED, "median non-negative adjacent ts gap in seq order, seconds"),
    "max_gap_share": ("raw", TIMED, "largest adjacent gap / span"),
    "ts_backward_frac": ("raw", TIMED, "adjacent pairs (seq order, both stamped) with ts decreasing / pairs"),
    "ts_tie_frac": ("raw", TIMED, "adjacent stamped pairs with identical ts / pairs"),
    "ts_null_frac": ("raw", TIMED, "events with null ts / events"),
    "call_result_gap_median_s": ("log1p", TIMED, "median of max(0, result ts - call ts) over paired calls, seconds"),
    "neg_call_result_frac": ("raw", TIMED, "paired calls whose result ts < call ts / paired calls"),
    "out_tokens_total": ("log1p", USAGE, "sum of deduped output tokens"),
    "ctx_max": ("log1p", USAGE, "largest deduped context (input + cache_read + cache_create)"),
    "chars_per_out_token": ("logratio", USAGE, "(assistant chars + thinking chars + args chars) / out_tokens_total"),
    "cache_read_share": ("raw", USAGE, "sum cache_read / sum context"),
    "n_models": ("log1p", USAGE, "distinct model values (excluding '<synthetic>')"),
    # corpus-specific
    "compactions": ("log1p", {"swechat", "cc_local", "aiv_cc"}, "compaction boundaries (CC compact/microcompact_boundary, Codex compacted, OpenCode compaction part)"),
    "api_errors": ("log1p", {"swechat", "cc_local", "aiv_cc"}, "meta subtype api_error (+ aiv_cc assistant sdk_error)"),
    "max_progress_elapsed_s": ("log1p", {"swechat"}, "max extra.elapsedTimeSeconds (or elapsedTimeMs/1000) on progress meta"),
    "attachment_share": ("raw", {"cc_local"}, "events with extra.entry_type == attachment / events"),
    "family_members": ("log1p", {"cc_local"}, "distinct extra.family_member values (resume-chain members)"),
    "journal_lines": ("log1p", {"cc_local"}, "workflow journal meta events"),
    "interrupted_frac": ("raw", {"cc_local", "aiv_cc"}, "results with extra.interrupted true / results"),
    "background_tasks": ("log1p", {"cc_local", "swechat"}, "results with extra.backgroundTaskId"),
    "result_rows": ("log1p", {"aiv_cc"}, "SDK result meta rows (extra.entry_type == result)"),
    "sdk_duration_over_span": ("logratio", {"aiv_cc"}, "sum(result duration_ms)/1000 / span"),
    "cost_per_out_token": ("logratio", {"aiv_cc"}, "sum(total_cost_usd) / out_tokens_total"),
    "synthetic_share": ("raw", {"aiv_cu"}, "synthetic bootstrap system events / (calls + synthetic events)"),
    "gui_share": ("raw", {"aiv_cu"}, "calls with tool == gui / calls"),
    "screenshot_redacted_frac": ("raw", {"aiv_cu"}, "results with extra.screenshot_is_redacted true / results"),
    "unexecuted_calls": ("log1p", {"aiv_cu"}, "sum of len(extra.unexecuted_calls)"),
    "call_id_fallback_frac": ("raw", {"aiv_cu"}, "calls with extra.call_id_fallback / calls"),
    "server_timing_median_ms": ("log1p", {"aiv_cu"}, "median extra.timing.server_timing_dur_ms (Gemini only)"),
    "talk_only_share": ("raw", {"aiv_cu"}, "n_talk_only_turns / n_turns (sessions table)"),
    "n_agents": ("log1p", {"whowhen"}, "distinct extra.agent speakers"),
    "unexecuted_call_frac": ("raw", {"whowhen"}, "calls with extra.unexecuted / calls"),
    "log_leak_frac": ("raw", {"whowhen"}, "events with extra.log_leak / events"),
    "terminal_no_code": ("log1p", {"whowhen"}, "system events with harness_note terminal_no_code"),
    "replans": ("log1p", {"whowhen"}, "assistant thought_kind in {replan_notice, new_plan}"),
}
PREREG["features"] = {k: {"transform": v[0], "corpora": sorted(v[1]), "definition": v[2]} for k, v in FEATURES.items()}

COLS = ["session_id", "stratum", "seq", "kind", "ts", "tool", "call_id", "native_error", "usage_in", "usage_out",
        "usage_cache_read", "usage_cache_create", "api_msg_id", "model", "is_subagent", "extra"]
GAP_BINS = [114, 116, 118, 120, 122, 124, 594, 596, 598, 600, 602, 604]  # POSTHOC P7 bin starts (seconds), 2 s wide
CC_PUBLIC_TOOL_NAMES = {"taskoutput", "bashoutput", "killshell", "askuserquestion", "exitplanmode", "notebookedit", "skill",
                        "toolsearch", "workflow"}  # Claude Code built-in tool names (not private); cc_local maps any other name to 'other'
BUILTIN_TOOLS = {"shell", "read", "write", "edit", "glob", "grep", "ls", "subagent", "webfetch", "websearch", "todo", "gui"}


# ---------------------------------------------------------------------------------------------------------------------
# Stage 1: per-session features
# ---------------------------------------------------------------------------------------------------------------------
def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def row_extras(corpus, kinds, extras):
    """Parse extra JSON into the few per-row fields the features need. Returns dict of lists."""
    n = len(kinds)
    out = {k: [None] * n for k in ("think", "truncated", "subtype", "entry_type", "interrupted", "family_member",
                                   "elapsed_s", "bg", "compaction", "dur_ms", "cost", "num_turns", "res_is_error",
                                   "sdk_error", "synthetic", "scr_red", "unexec", "fallback", "timing_ms", "agent",
                                   "log_leak", "unexecuted", "harness_note", "thought_kind")}
    for i, (k, e) in enumerate(zip(kinds, extras)):
        if not e:
            continue
        try:
            d = json.loads(e)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        t = d.get("thinking_chars")
        if t is None:
            t = d.get("reasoning_chars")
        out["think"][i] = _f(t)
        out["truncated"][i] = d.get("truncated") is True
        out["subtype"][i] = d.get("subtype") if isinstance(d.get("subtype"), str) else None
        et = d.get("entry_type")
        out["entry_type"][i] = et if isinstance(et, str) else None
        out["interrupted"][i] = d.get("interrupted") is True
        fm = d.get("family_member")
        out["family_member"][i] = fm if isinstance(fm, int) else None
        if "elapsedTimeSeconds" in d:
            out["elapsed_s"][i] = _f(d.get("elapsedTimeSeconds"))
        elif "elapsedTimeMs" in d and _f(d.get("elapsedTimeMs")) is not None:
            out["elapsed_s"][i] = _f(d.get("elapsedTimeMs")) / 1000.0
        out["bg"][i] = "backgroundTaskId" in d
        out["compaction"][i] = (d.get("subtype") in ("compact_boundary", "microcompact_boundary") or et == "compacted"
                                or d.get("part_type") == "compaction")
        if et == "result":
            out["dur_ms"][i] = _f(d.get("duration_ms"))
            out["cost"][i] = _f(d.get("total_cost_usd"))
            out["num_turns"][i] = _f(d.get("num_turns"))
            out["res_is_error"][i] = d.get("is_error") is True
        out["sdk_error"][i] = "sdk_error" in d
        out["synthetic"][i] = "synthetic" in d
        out["scr_red"][i] = d.get("screenshot_is_redacted") is True
        uc = d.get("unexecuted_calls")
        out["unexec"][i] = len(uc) if isinstance(uc, list) else (0 if uc is None else 1)
        out["fallback"][i] = "call_id_fallback" in d
        tm = d.get("timing")
        if isinstance(tm, dict):
            out["timing_ms"][i] = _f(tm.get("server_timing_dur_ms"))
        a = d.get("agent")
        out["agent"][i] = a if isinstance(a, str) else None
        out["log_leak"][i] = bool(d.get("log_leak"))
        out["unexecuted"][i] = bool(d.get("unexecuted"))
        hn = d.get("harness_note")
        out["harness_note"][i] = hn if isinstance(hn, str) else None
        tk = d.get("thought_kind")
        out["thought_kind"][i] = tk if isinstance(tk, str) else None
    return out


def frame_for_rowgroup(corpus, pf, rg):
    t = pf.read_row_group(rg, columns=COLS + ["text", "args", "command"])
    text, args, cmd = t.column("text"), t.column("args"), t.column("command")
    kinds = t.column("kind").to_pylist()
    text_len = pc.fill_null(pc.utf8_length(text), 0).to_numpy(zero_copy_only=False)
    args_len = np.array([np.nan if v is None else v for v in pc.utf8_length(args).to_pylist()], dtype=float)
    red = (pc.fill_null(pc.match_substring(text, "REDACTED"), False).to_numpy(zero_copy_only=False)
           | pc.fill_null(pc.match_substring(args, "REDACTED"), False).to_numpy(zero_copy_only=False)
           | pc.fill_null(pc.match_substring(cmd, "REDACTED"), False).to_numpy(zero_copy_only=False))
    trunc_text = pc.fill_null(pc.match_substring_regex(text, TRUNC_RX), False).to_numpy(zero_copy_only=False)
    is_res = np.array([k == "result" for k in kinds])
    is_call = np.array([k == "call" for k in kinds])
    marker = np.zeros(len(kinds), dtype=bool)
    marker_name = np.full(len(kinds), None, dtype=object)
    res_idx = np.nonzero(is_res)[0]
    if len(res_idx):
        rt = pc.take(text, pa.array(res_idx)).to_pylist()
        names = [error_marker(x) for x in rt]
        marker_name[res_idx] = names
        marker[res_idx] = [x is not None for x in names]
    sig = np.full(len(kinds), None, dtype=object)
    call_idx = np.nonzero(is_call)[0]
    if len(call_idx):
        ta = pc.take(t.column("tool"), pa.array(call_idx)).to_pylist()
        aa = pc.take(args, pa.array(call_idx)).to_pylist()
        sig[call_idx] = [f"{a}\x00{b}" for a, b in zip(ta, aa)]
    extras = t.column("extra").to_pylist()
    df = t.select(COLS[:-1]).to_pandas()
    del t, text, args, cmd
    df["text_len"] = text_len
    df["args_len"] = args_len
    df["red"] = red
    df["trunc_text"] = trunc_text
    df["marker"] = marker
    df["marker_name"] = marker_name
    df["sig"] = sig
    ex = row_extras(corpus, kinds, extras)
    for k, v in ex.items():
        df["x_" + k] = v
    df["tsec"] = (pd.to_datetime(df["ts"], utc=True, format="ISO8601", errors="coerce")
                  - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds()
    return df


def safe_div(a, b):
    return float(a) / float(b) if b else np.nan


def session_features(corpus, g):
    g = g.sort_values("seq")
    kind = g["kind"].to_numpy(object)
    n = len(g)
    is_call, is_res = kind == "call", kind == "result"
    calls, res = g[is_call], g[is_res]
    f = {"session_id": g["session_id"].iat[0], "stratum": g["stratum"].iat[0]}
    f["n_events"] = n
    f["n_calls"] = int(is_call.sum())
    tools = calls["tool"].dropna()
    vc = tools.value_counts()
    f["n_tools_distinct"] = int(len(vc))
    f["top_tool_share"] = safe_div(vc.iloc[0], len(calls)) if len(vc) else np.nan
    f["top_tool"] = vc.index[0] if len(vc) else None
    f["shell_share"] = safe_div((calls["tool"] == "shell").sum(), len(calls))
    call_ids = set(calls["call_id"].dropna())
    res_ids = set(res["call_id"].dropna())
    f["unpaired_call_frac"] = safe_div(sum(1 for c in calls["call_id"] if c not in res_ids), len(calls))
    f["orphan_result_frac"] = safe_div(sum(1 for c in res["call_id"] if (c is None or c is pd.NA or c not in call_ids)), len(res))
    ne = res["native_error"].dropna()
    f["native_err_frac"] = safe_div(int(ne.astype(bool).sum()), len(res))  # POSTHOC P1: denominator = all results
    f["marker_err_frac"] = safe_div(int(res["marker"].sum()), len(res))
    f["result_chars_median"] = float(res["text_len"].median()) if len(res) else np.nan
    f["result_chars_max"] = float(res["text_len"].max()) if len(res) else np.nan
    asst = g[kind == "assistant"]
    f["assistant_chars_total"] = float(asst["text_len"].sum())
    f["args_chars_median"] = float(calls["args_len"].median()) if len(calls) and calls["args_len"].notna().any() else np.nan
    f["user_events"] = int((kind == "user").sum())
    f["system_share"] = safe_div((kind == "system").sum(), n)
    f["meta_share"] = safe_div((kind == "meta").sum(), n)
    sub = g["is_subagent"].fillna(False).astype(bool)
    f["subagent_share"] = safe_div(int(sub.sum()), n)
    trunc = res["trunc_text"].to_numpy(bool) | res["x_truncated"].fillna(False).astype(bool).to_numpy()
    f["trunc_frac"] = safe_div(int(trunc.sum()), len(res))
    f["redacted_frac"] = safe_div(int(g["red"].sum()), n)
    sigs = calls["sig"].tolist()
    if sigs:
        f["max_identical_call"] = int(Counter(sigs).most_common(1)[0][1])
        f["consec_dup_call_frac"] = safe_div(sum(1 for a, b in zip(sigs, sigs[1:]) if a == b), len(sigs))
    else:
        f["max_identical_call"] = 0
        f["consec_dup_call_frac"] = np.nan
    think = pd.to_numeric(g["x_think"], errors="coerce").fillna(0)
    f["thinking_chars_total"] = float(think.sum())
    # timing
    tsec = g["tsec"].to_numpy(float)
    has = ~np.isnan(tsec)
    f["ts_null_frac"] = safe_div(int((~has).sum()), n)
    if corpus != "whowhen" and has.sum() >= 2:
        tv = tsec[has]
        d = np.diff(tv)
        span = float(tv.max() - tv.min())
        f["span_s"] = span
        nn = d[d >= 0]
        f["gap_median_s"] = float(np.median(nn)) if len(nn) else np.nan
        f["max_gap_share"] = safe_div(float(d.max()), span) if span > 0 else np.nan
        f["ts_backward_frac"] = safe_div(int((d < 0).sum()), len(d))
        f["ts_tie_frac"] = safe_div(int((d == 0).sum()), len(d))
    else:
        for k in ("span_s", "gap_median_s", "max_gap_share", "ts_backward_frac", "ts_tie_frac"):
            f[k] = np.nan
    if corpus == "whowhen":
        f["ts_null_frac"] = np.nan
    ct = calls.dropna(subset=["call_id"]).drop_duplicates("call_id")[["call_id", "tsec"]]
    rt = res.dropna(subset=["call_id"]).drop_duplicates("call_id")[["call_id", "tsec"]]
    pr = ct.merge(rt, on="call_id", suffixes=("_c", "_r")).dropna()
    if corpus != "whowhen" and len(pr):
        dd = (pr["tsec_r"] - pr["tsec_c"]).to_numpy(float)
        f["call_result_gap_median_s"] = float(np.median(np.maximum(dd, 0)))
        f["neg_call_result_frac"] = safe_div(int((dd < 0).sum()), len(dd))
    else:
        f["call_result_gap_median_s"] = np.nan
        f["neg_call_result_frac"] = np.nan
    # usage
    u = g[g["usage_in"].notna()]
    if corpus in USAGE and len(u):
        u = u.copy()
        u["mid"] = u["api_msg_id"].astype(object).where(u["api_msg_id"].notna(), None)
        u["mid"] = [m if m is not None else f"__row{s}" for m, s in zip(u["mid"], u["seq"])]
        agg = u.groupby("mid", sort=False).agg(i=("usage_in", "first"), o=("usage_out", "max"),
                                               cr=("usage_cache_read", "first"), cc=("usage_cache_create", "first"),
                                               model=("model", "first"))
        i_ = agg["i"].astype(float).fillna(0)
        cr = agg["cr"].astype(float).fillna(0)
        cc = agg["cc"].astype(float).fillna(0)
        o = agg["o"].astype(float).fillna(0)
        gem = agg["model"].astype(str).str.contains("gemini", case=False) if corpus == "aiv_cu" else pd.Series(False, index=agg.index)
        ctx = np.where(gem, i_ + cc, i_ + cr + cc)
        f["out_tokens_total"] = float(o.sum())
        f["ctx_max"] = float(np.max(ctx))
        f["cache_read_share"] = safe_div(float(cr.sum()), float(ctx.sum()))
        text_chars = float(asst["text_len"].sum()) + float(think.sum()) + float(calls["args_len"].fillna(0).sum())
        f["chars_per_out_token"] = text_chars / f["out_tokens_total"] if f["out_tokens_total"] > 0 else np.nan
        f["n_usage_responses"] = int(len(agg))
    else:
        for k in ("out_tokens_total", "ctx_max", "cache_read_share", "chars_per_out_token"):
            f[k] = np.nan
        f["n_usage_responses"] = 0
    models = g["model"].dropna()
    models = models[models != "<synthetic>"]
    f["n_models"] = int(models.nunique()) if corpus in USAGE else np.nan
    f["model_top"] = models.value_counts().index[0] if len(models) else None
    f["models_set"] = "|".join(sorted(set(g["model"].dropna().astype(str))))  # POSTHOC P5 (artifact check)
    f["marker_names"] = json.dumps(dict(Counter(x for x in res["marker_name"] if isinstance(x, str))), sort_keys=True)  # POSTHOC P5
    # corpus-specific
    f["compactions"] = int(g["x_compaction"].fillna(False).astype(bool).sum())
    st = g["x_subtype"]
    f["api_errors"] = int((st == "api_error").sum()) + (int(g["x_sdk_error"].fillna(False).astype(bool).sum()) if corpus == "aiv_cc" else 0)
    el = pd.to_numeric(g["x_elapsed_s"], errors="coerce").dropna()
    f["max_progress_elapsed_s"] = float(el.max()) if len(el) else 0.0
    et = g["x_entry_type"]
    f["attachment_share"] = safe_div(int((et == "attachment").sum()), n)
    fm = g["x_family_member"].dropna()
    f["family_members"] = int(fm.nunique()) if len(fm) else 1
    f["journal_lines"] = int((et == "workflow_journal").sum())
    f["interrupted_frac"] = safe_div(int(res["x_interrupted"].fillna(False).astype(bool).sum()), len(res))
    f["background_tasks"] = int(res["x_bg"].fillna(False).astype(bool).sum())
    rr = g[et == "result"]
    f["result_rows"] = int(len(rr))
    dms = pd.to_numeric(rr["x_dur_ms"], errors="coerce").dropna()
    f["sdk_duration_over_span"] = (float(dms.sum()) / 1000.0 / f["span_s"]) if (len(dms) and f.get("span_s") and f["span_s"] > 0) else np.nan
    cost = pd.to_numeric(rr["x_cost"], errors="coerce").dropna()
    f["cost_per_out_token"] = (float(cost.sum()) / f["out_tokens_total"]) if (len(cost) and f["out_tokens_total"] and f["out_tokens_total"] > 0) else np.nan
    f["result_is_error_any"] = bool(rr["x_res_is_error"].fillna(False).astype(bool).any()) if len(rr) else False
    syn = int(((kind == "system") & g["x_synthetic"].fillna(False).astype(bool).to_numpy()).sum())
    f["synthetic_share"] = safe_div(syn, f["n_calls"] + syn)
    f["gui_share"] = safe_div(int((calls["tool"] == "gui").sum()), len(calls))
    f["screenshot_redacted_frac"] = safe_div(int(res["x_scr_red"].fillna(False).astype(bool).sum()), len(res))
    f["unexecuted_calls"] = int(pd.to_numeric(g["x_unexec"], errors="coerce").fillna(0).sum())
    f["call_id_fallback_frac"] = safe_div(int(calls["x_fallback"].fillna(False).astype(bool).sum()), len(calls))
    tm = pd.to_numeric(g["x_timing_ms"], errors="coerce").dropna()
    f["server_timing_median_ms"] = float(tm.median()) if len(tm) else np.nan
    ag = g["x_agent"].dropna()
    f["n_agents"] = int(ag.nunique())
    f["unexecuted_call_frac"] = safe_div(int(calls["x_unexecuted"].fillna(False).astype(bool).sum()), len(calls))
    f["log_leak_frac"] = safe_div(int(g["x_log_leak"].fillna(False).astype(bool).sum()), n)
    f["terminal_no_code"] = int((g["x_harness_note"] == "terminal_no_code").sum())
    f["replans"] = int(g["x_thought_kind"].isin(["replan_notice", "new_plan"]).sum())
    # flags for profiling (not features)
    # POSTHOC P6 descriptors
    f["last_kind"] = kind[-1] if n else None
    lastcall = calls["call_id"].dropna()
    f["flag_ends_unanswered_call"] = bool(len(lastcall) and lastcall.iloc[-1] not in res_ids)  # last call (seq order) has no result
    f["max_cr_gap_s"], f["max_cr_gap_tool"], f["max_cr_gap_marker"] = np.nan, None, None
    if corpus != "whowhen" and len(pr):
        dd = (pr["tsec_r"] - pr["tsec_c"]).to_numpy(float)
        j = int(np.argmax(dd))
        cid = pr["call_id"].iat[j]
        f["max_cr_gap_s"] = float(dd[j])
        tl = calls.loc[calls["call_id"] == cid, "tool"]
        f["max_cr_gap_tool"] = str(tl.iat[0]) if len(tl) and tl.iat[0] is not None and tl.iat[0] is not pd.NA else None
        mk = res.loc[res["call_id"] == cid, "marker_name"]
        f["max_cr_gap_marker"] = mk.iat[0] if len(mk) and isinstance(mk.iat[0], str) else None
        # POSTHOC P7: gap bins around fixed timeouts (2 s wide)
        tool_of = dict(zip(calls["call_id"], calls["tool"]))
        is_sh = np.array([tool_of.get(c) == "shell" for c in pr["call_id"]])
        for lo in GAP_BINS:
            m = (dd >= lo) & (dd < lo + 2)
            f[f"gap_bin_{lo}"] = int(m.sum())
            f[f"gap_bin_shell_{lo}"] = int((m & is_sh).sum())
        f["n_paired_calls"] = int(len(dd))
        for lo in (120, 600):
            m = (dd >= lo) & (dd < lo + 2)
            f[f"gap_bin_tools_{lo}"] = json.dumps(dict(Counter(str(tool_of.get(c)) for c in pr["call_id"][m])), sort_keys=True)
    nt = pd.to_numeric(rr["x_num_turns"], errors="coerce") if "x_num_turns" in rr else pd.Series(dtype=float)
    f["failed_resume_rows"] = int(((nt == 0) & (pd.to_numeric(rr["x_dur_ms"], errors="coerce") == 0)).sum())
    f["flag_failed_resume_rows"] = f["failed_resume_rows"] > 0
    f["flag_native_error"] = bool(ne.astype(bool).any()) if len(ne) else False
    f["flag_marker_error"] = bool(res["marker"].any())
    f["flag_subagent"] = bool(sub.any())
    f["flag_truncation"] = bool(trunc.any())
    f["flag_redaction"] = bool(g["red"].any())
    f["flag_ts_backward"] = bool(f.get("ts_backward_frac", 0) and f["ts_backward_frac"] > 0)
    f["flag_ts_null_any"] = bool((~has).any()) if corpus != "whowhen" else False
    f["flag_neg_call_result"] = bool(f.get("neg_call_result_frac") and f["neg_call_result_frac"] > 0)
    f["flag_compaction"] = f["compactions"] > 0
    f["flag_no_calls"] = f["n_calls"] == 0
    f["top_tool_class"] = (f["top_tool"] if f["top_tool"] in BUILTIN_TOOLS else ("mcp_or_other" if f["top_tool"] else None))
    return f


def build_features(corpus):
    path = os.path.join(CACHE, f"{corpus}_B.parquet")
    pf = pq.ParquetFile(path)
    rows, seen = [], set()
    for rg in range(pf.num_row_groups):
        t0 = time.time()
        df = frame_for_rowgroup(corpus, pf, rg)
        sids = set(df["session_id"].unique())
        assert not (sids & seen), f"{corpus}: a session straddles row groups"
        seen |= sids
        for _, g in df.groupby("session_id", sort=False):
            rows.append(session_features(corpus, g))
        print(f"  {corpus} rg {rg}: {len(df)} rows, {len(sids)} sessions, {time.time() - t0:.1f}s", flush=True)
        del df
    F = pd.DataFrame(rows)
    if corpus == "aiv_cu":
        s = pd.read_parquet(os.path.join(CACHE, "aiv_cu_sessions.parquet"),
                            columns=["session_id", "n_turns", "n_talk_only_turns", "model_string", "shape", "agent_name"])
        F = F.merge(s, on="session_id", how="left")
        F["talk_only_share"] = F["n_talk_only_turns"] / F["n_turns"].replace(0, np.nan)
    if corpus == "swechat":
        pop = pd.read_parquet(os.path.join(CACHE, "swechat_population.parquet"), columns=["session_id", "format", "length"])
        F = F.merge(pop, on="session_id", how="left")
        ss = pd.read_parquet(f"{DATA}/swe-chat-pinned/sessions.parquet", columns=["session_id", "repo_id", "cli_version", "created_at"])
        ss["created_month"] = ss["created_at"].dt.strftime("%Y-%m")
        F = F.merge(ss[["session_id", "repo_id", "cli_version", "created_month"]], on="session_id", how="left")
    if corpus == "whowhen":
        lab = json.load(open(os.path.join(CACHE, "whowhen_labels.json"), encoding="utf-8"))
        F["is_correct"] = F["session_id"].map(lambda s: lab.get(s, {}).get("is_correct"))
        F["agent_vs_speaker"] = F["session_id"].map(lambda s: lab.get(s, {}).get("agent_vs_speaker"))
        F["level"] = F["session_id"].map(lambda s: str(lab.get(s, {}).get("level")))
        F["history_len"] = F["session_id"].map(lambda s: lab.get(s, {}).get("history_len"))
        F["mistake_step"] = F["session_id"].map(lambda s: lab.get(s, {}).get("mistake_step"))
        F["mistake_rel"] = F["mistake_step"].astype(float) / F["history_len"].astype(float)
        F["mistake_agent"] = F["session_id"].map(lambda s: lab.get(s, {}).get("mistake_agent"))
    return F


# ---------------------------------------------------------------------------------------------------------------------
# Stage 2: robust z, outliers, profiles
# ---------------------------------------------------------------------------------------------------------------------
def transform(x, kind):
    x = pd.to_numeric(x, errors="coerce").astype(float)
    if kind == "log1p":
        return np.log10(1 + x.clip(lower=0))
    if kind == "logratio":
        return np.log10(x.where(x > 0))
    return x


def robust_z(F, feats):
    """Returns (Z dataframe, info dict per feature, dropped list)."""
    Z, info, dropped = {}, {}, []
    for k in feats:
        x = transform(F[k], FEATURES[k][0])
        v = x.dropna()
        if len(v) < 3:
            dropped.append({"feature": k, "reason": f"non-null n {len(v)} < 3"})
            continue
        med = float(v.median())
        mad = float((v - med).abs().median())
        if mad > 0:
            scale, sk = 1.4826 * mad, "MAD"
        else:
            mead = float((v - med).abs().mean())
            if mead == 0:
                dropped.append({"feature": k, "reason": "constant (MAD 0, meanAD 0)", "n_nonnull": int(len(v))})
                continue
            scale, sk = 1.253314 * mead, "meanAD"
        z = (x - med) / scale
        Z[k] = z
        info[k] = {"n_nonnull": int(len(v)), "median_transformed": med, "scale": scale, "scale_kind": sk,
                   "transform": FEATURES[k][0]}
    return pd.DataFrame(Z, index=F.index), info, dropped


def wl(k, n):
    p, lo, hi = stats.wilson(int(k), int(n))
    return {"k": int(k), "n": int(n), "rate": p, "lo": lo, "hi": hi}


def outlier_table(Z, thr, min_axes):
    ext = Z.abs() > thr
    n_ext = ext.sum(axis=1)
    return ext, n_ext, n_ext >= min_axes


def permutation_null(Z, thr, min_axes, n_perm, seed):
    rng = np.random.default_rng(seed)
    E = (Z.abs() > thr).to_numpy()
    counts = []
    for _ in range(n_perm):
        P = np.column_stack([rng.permutation(E[:, j]) for j in range(E.shape[1])])
        counts.append(int((P.sum(1) >= min_axes).sum()))
    c = np.array(counts)
    return {"n_perm": n_perm, "mean": float(c.mean()), "p2.5": float(np.quantile(c, 0.025)),
            "p97.5": float(np.quantile(c, 0.975)), "max": int(c.max())}


def permutation_null_tail(Z, thr, ks, n_perm, seed):
    """POSTHOC P2: observed vs column-permutation null for the number of sessions with >= k extreme axes, and the max."""
    rng = np.random.default_rng(seed)
    E = (Z.abs() > thr).to_numpy()
    obs_n = E.sum(1)
    null = {k: [] for k in ks}
    mx = []
    for _ in range(n_perm):
        P = np.column_stack([rng.permutation(E[:, j]) for j in range(E.shape[1])])
        nn = P.sum(1)
        for k in ks:
            null[k].append(int((nn >= k).sum()))
        mx.append(int(nn.max()))
    out = {}
    for k in ks:
        c = np.array(null[k])
        o = int((obs_n >= k).sum())
        out[f">={k}"] = {"observed": o, "null_mean": float(c.mean()), "null_p2.5": float(np.quantile(c, 0.025)),
                         "null_p97.5": float(np.quantile(c, 0.975)), "n_perm_null_ge_observed": int((c >= o).sum())}
    mx = np.array(mx)
    out["max_axes"] = {"observed": int(obs_n.max()), "null_mean": float(mx.mean()), "null_max": int(mx.max()),
                       "n_perm_null_ge_observed": int((mx >= obs_n.max()).sum())}
    out["n_perm"] = n_perm
    return out


def group_profile(F, is_out, col):
    vals = F[col].astype(object).where(F[col].notna(), "<null>").astype(str)
    vc = vals.value_counts()
    small = set(vc[vc < 5].index)
    vals = vals.where(~vals.isin(small), "<small>")
    out = []
    tot_out = int(is_out.sum())
    for v, nv in vals.value_counts().items():
        m = vals == v
        k = int((m & is_out).sum())
        out.append({"value": v, "n_group": int(nv), "k_outliers": k, "outlier_rate": wl(k, int(nv)),
                    "share_of_outliers": (k / tot_out) if tot_out else None,
                    "share_of_population": int(nv) / len(F)})
    out.sort(key=lambda r: -r["n_group"])
    return {"n_small_values_pooled": len(small), "groups": out}


def followups(corpus, F, is_out, within):
    """POSTHOC P5: descriptive follow-ups of surprises seen in the first report. Aggregates only for cc_local."""
    out = {}
    if corpus == "cc_local":
        gt = F["top_tool"] == "glob"
        G = F[gt]
        out["top_tool_glob_cluster"] = {
            "n_sessions": int(gt.sum()), "n_sessions_total": int(len(F)), "n_outliers_in_cluster": int((gt & is_out).sum()),
            "n_outliers_outside_cluster": int((~gt & is_out).sum()), "n_outside_cluster": int((~gt).sum()),
            "model_top_counts": {str(k): int(v) for k, v in G["model_top"].value_counts().items()},
            "stratum_counts": {str(k): int(v) for k, v in G["stratum"].value_counts().items()},
            "user_events_eq_1": int((G["user_events"] == 1).sum()),
            "flag_native_error": int(G["flag_native_error"].sum()),
            "flag_native_error_outside_cluster": int(F.loc[~gt, "flag_native_error"].sum()),
            "n_events": stats.describe(G["n_events"].to_numpy(float)),
            "n_calls": stats.describe(G["n_calls"].to_numpy(float)),
            "n_tools_distinct": stats.describe(G["n_tools_distinct"].to_numpy(float)),
            "span_s": stats.describe(G["span_s"].dropna().to_numpy(float)),
            "n_events_outside_cluster": stats.describe(F.loc[~gt, "n_events"].to_numpy(float)),
        }
        z0 = F["thinking_chars_total"] == 0
        out["thinking_chars_zero_by_model_top"] = {str(m): {"zero": int((z0 & (F["model_top"] == m)).sum()),
                                                           "n": int((F["model_top"] == m).sum())} for m in F["model_top"].dropna().unique()}
    if corpus == "aiv_cu":
        S = pd.read_parquet(os.path.join(CACHE, "aiv_cu_sessions.parquet"),
                            columns=["session_id", "n_turns", "n_synthetic_turns", "n_talk_only_turns", "model_string"])
        vc = S["n_turns"].value_counts()
        out["population_n_sessions"] = int(len(S))
        out["population_n_turns_top10"] = [{"n_turns": int(k), "sessions": int(v)} for k, v in vc.head(10).items()]
        out["population_n_turns_35_to_45"] = {str(k): int(vc.get(k, 0)) for k in range(35, 46)}
        b2 = (S["n_turns"] == 2) & (S["n_synthetic_turns"] == 1) & (S["n_talk_only_turns"] == 1)
        g = S.assign(b2=b2).groupby("model_string")["b2"].agg(["sum", "count"]).sort_values("sum", ascending=False)
        out["population_bootstrap_plus_one_talk_turn"] = {
            "rule": "n_turns == 2 and n_synthetic_turns == 1 and n_talk_only_turns == 1", "n": int(b2.sum()),
            "by_model_string_top": [{"model_string": str(k), "k": int(r["sum"]), "n": int(r["count"]), "rate": wl(int(r["sum"]), int(r["count"]))}
                                    for k, r in g.head(6).iterrows()]}
        m2 = F[F["n_models"] >= 2]
        out["n_models_ge2_model_sets"] = {str(k): int(v) for k, v in m2["models_set"].value_counts().items()}
        out["B_n_turns_eq_41"] = int((F["n_turns"] == 41).sum())
        out["B_outliers_by_n_turns_eq_41"] = {"eq41": int((is_out & (F["n_turns"] == 41)).sum()),
                                              "ne41": int((is_out & (F["n_turns"] != 41)).sum()),
                                              "n_ne41": int((F["n_turns"] != 41).sum())}
    if corpus == "aiv_cc":
        bins = [-1, 0, 0.9, 0.999, 1.001, 1.1, 1e9]
        lab = ["<=0", "(0,0.9]", "(0.9,0.999]", "(0.999,1.001]", "(1.001,1.1]", ">1.1"]
        cut = pd.cut(F["sdk_duration_over_span"], bins, labels=lab).astype(str)
        out["result_rows_x_duration_over_span"] = {str(rr): {str(k): int(v) for k, v in cut[F["result_rows"] == rr].value_counts().items()}
                                                   for rr in sorted(F["result_rows"].unique())}
        out["result_rows_counts"] = {str(k): int(v) for k, v in F["result_rows"].value_counts().items()}
        z = F[F["result_rows"] == 0]
        out["result_rows_0_describe"] = {"n_events": stats.describe(z["n_events"].to_numpy(float)),
                                         "n_outliers": int((is_out & (F["result_rows"] == 0)).sum())}
    if corpus == "swechat":
        nim = F["repo_id"] == "dayhaysoos/nimbus"
        out["repo_dayhaysoos_nimbus_by_format"] = {str(k): int(v) for k, v in F.loc[nim, "format"].value_counts().items()}
        out["format_counts_B"] = {str(k): int(v) for k, v in F["format"].value_counts().items()}
        cc = F["format"] == "claude_code"
        out["claude_code_format_outliers"] = {"pooled": int((is_out & cc).sum()), "within_format": int(((within == 1) & cc).sum()),
                                              "both": int((is_out & (within == 1) & cc).sum()), "n": int(cc.sum())}
        mk = Counter()
        for x in F.loc[is_out, "marker_names"]:
            mk.update(json.loads(x))
        mk_all = Counter()
        for x in F["marker_names"]:
            mk_all.update(json.loads(x))
        out["error_marker_names_in_outliers"] = dict(mk)
        out["error_marker_names_all"] = dict(mk_all)
    if corpus == "whowhen":
        for sv in F["stratum"].unique():
            m = F["stratum"] == sv
            out[f"mistake_rel_tercile_by_outlier_{sv}"] = {
                "outliers": {str(k): int(v) for k, v in F.loc[m & is_out, "mistake_rel_tercile"].value_counts().items()},
                "rest": {str(k): int(v) for k, v in F.loc[m & ~is_out, "mistake_rel_tercile"].value_counts().items()}}
    return out


def pick_rank(Z, ext, n_ext, is_out, F, corpus):
    cap = Z.abs().clip(upper=20).where(ext, 0).sum(axis=1)
    d = pd.DataFrame({"n_ext": n_ext, "zsum": cap, "sid": F["session_id"]})[is_out]
    return d.sort_values(["n_ext", "zsum", "sid"], ascending=[False, False, True])


def fmt(v):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def analyse(corpus, F):
    thr, mina = PREREG["z_threshold_abs"], PREREG["min_extreme_axes"]
    feats = [k for k, v in FEATURES.items() if corpus in v[1]]
    F = F.reset_index(drop=True)
    Z, info, dropped = robust_z(F, feats)
    used = list(Z.columns)
    ext, n_ext, is_out = outlier_table(Z, thr, mina)
    N = len(F)
    R = {"n_sessions": N, "features_considered": feats, "n_features_considered": len(feats), "features_used": used,
         "n_features_used": len(used), "features_dropped": dropped, "feature_scale": info}
    R["n_outliers"] = int(is_out.sum())
    R["outlier_rate"] = wl(int(is_out.sum()), N)
    R["n_extreme_axes_hist"] = {str(k): int(v) for k, v in n_ext.value_counts().sort_index().items()}
    # per feature extremes
    pf = {}
    for k in used:
        z = Z[k]
        pf[k] = {"n_extreme_high": int((z > thr).sum()), "n_extreme_low": int((z < -thr).sum()),
                 "n_extreme_in_outliers": int(((z.abs() > thr) & is_out).sum()), "scale_kind": info[k]["scale_kind"],
                 "raw_describe_all": stats.describe(pd.to_numeric(F[k], errors="coerce").dropna().to_numpy(float)),
                 "raw_median_outliers": fmt(pd.to_numeric(F.loc[is_out, k], errors="coerce").median()) if is_out.any() else None,
                 "raw_median_rest": fmt(pd.to_numeric(F.loc[~is_out, k], errors="coerce").median())}
    R["per_feature"] = pf
    # combos among outliers
    combos = Counter()
    for i in np.nonzero(is_out.to_numpy())[0]:
        row = Z.iloc[i]
        tags = sorted(f"{k}{'+' if row[k] > 0 else '-'}" for k in used if abs(row[k]) > thr)
        combos[" & ".join(tags)] += 1
    R["top_axis_combos"] = [{"combo": c, "n": v} for c, v in combos.most_common(20)]
    R["n_distinct_axis_combos"] = len(combos)
    # axis tag counts among outliers (signed)
    tagc = Counter()
    for i in np.nonzero(is_out.to_numpy())[0]:
        row = Z.iloc[i]
        for k in used:
            if abs(row[k]) > thr:
                tagc[f"{k}{'+' if row[k] > 0 else '-'}"] += 1
    R["signed_axis_counts_in_outliers"] = dict(tagc.most_common())
    # co-extremity
    E = ext.to_numpy()
    nk = E.sum(0)
    pairs = []
    for a, b in combinations(range(len(used)), 2):
        o = int((E[:, a] & E[:, b]).sum())
        if o >= 5:
            e = nk[a] * nk[b] / N
            pairs.append({"a": used[a], "b": used[b], "observed": o, "expected_indep": float(e),
                          "ratio": (o / e) if e > 0 else None})
    pairs.sort(key=lambda r: -r["observed"])
    R["co_extreme_pairs_top_by_count"] = pairs[:25]
    R["co_extreme_pairs_top_by_ratio"] = sorted([p for p in pairs if p["ratio"]], key=lambda r: -r["ratio"])[:15]
    R["permutation_null_n_outliers"] = permutation_null(Z, thr, mina, PREREG["permutation_null"]["n_perm"], PREREG["permutation_null"]["seed"])
    # length terciles and profiles
    q1, q2 = F["n_events"].quantile([1 / 3, 2 / 3])
    F["length_tercile"] = np.where(F["n_events"] <= q1, "T1_short", np.where(F["n_events"] <= q2, "T2_mid", "T3_long"))
    R["length_tercile_cuts_n_events"] = [float(q1), float(q2)]
    prof_cols = ["stratum", "length_tercile", "model_top", "top_tool_class", "flag_native_error", "flag_marker_error",
                 "flag_subagent", "flag_truncation", "flag_redaction", "flag_ts_backward", "flag_ts_null_any",
                 "flag_neg_call_result", "flag_compaction", "flag_no_calls", "flag_ends_unanswered_call", "last_kind"]
    extra_cols = {"swechat": ["format", "repo_id", "cli_version", "created_month"],
                  "aiv_cu": ["model_string", "shape"], "aiv_cc": ["result_is_error_any", "flag_failed_resume_rows"],
                  "whowhen": ["is_correct", "agent_vs_speaker", "level"], "cc_local": []}[corpus]
    if corpus == "whowhen":
        F["mistake_rel_tercile"] = pd.cut(F["mistake_rel"], [-0.001, 1 / 3, 2 / 3, 1.0], labels=["early", "mid", "late"]).astype(str)
        extra_cols = extra_cols + ["mistake_rel_tercile"]
        prof_cols = [c for c in prof_cols if not c.startswith("flag_ts") and c != "flag_neg_call_result" and c != "model_top"]
    if corpus == "cc_local":
        F["multi_member_family"] = F["family_members"] > 1
        F["has_workflow_journal"] = F["journal_lines"] > 0
        extra_cols = ["multi_member_family", "has_workflow_journal"]
    R["profiles"] = {c: group_profile(F, is_out, c) for c in prof_cols + extra_cols}
    if corpus == "cc_local":  # model ids are fine; nothing else identifying in these profiles
        pass
    # numeric contrasts outliers vs rest
    cont = {}
    for c in ["n_events", "n_calls", "span_s", "out_tokens_total", "marker_err_frac", "native_err_frac", "subagent_share"]:
        if c in F.columns:
            a = pd.to_numeric(F.loc[is_out, c], errors="coerce").dropna()
            b = pd.to_numeric(F.loc[~is_out, c], errors="coerce").dropna()
            cont[c] = {"outliers": stats.describe(a.to_numpy(float), qs=(0.25, 0.5, 0.75)) if len(a) else {"n": 0},
                       "rest": stats.describe(b.to_numpy(float), qs=(0.25, 0.5, 0.75)) if len(b) else {"n": 0}}
    R["numeric_contrast"] = cont
    if corpus == "whowhen":
        a = F.loc[is_out, "mistake_rel"].dropna()
        b = F.loc[~is_out, "mistake_rel"].dropna()
        R["mistake_rel_position"] = {"outliers": stats.describe(a.to_numpy(float), qs=(0.25, 0.5, 0.75)),
                                     "rest": stats.describe(b.to_numpy(float), qs=(0.25, 0.5, 0.75))}
    if corpus == "swechat":
        try:
            sw = json.load(open(os.path.join(OUT_DIR, "swechat_tables.json"), encoding="utf-8"))
            um = sw["followup"]["unmatched_tally_sessions"]
            ids = set(x["session_id"] if isinstance(x, dict) else x for x in um) if isinstance(um, list) else set(um)
        except Exception as e:  # noqa: BLE001
            ids = None
            R["swechat_tables_unmatched_join_error"] = repr(e)
        if ids is not None:
            m = F["session_id"].isin(ids)
            R["swechat_tables_unmatched_tally"] = {"n_unmatched_in_B": int(m.sum()), "n_unmatched_outliers": int((m & is_out).sum())}
    # sensitivity: no meanAD features
    keep = [k for k in used if info[k]["scale_kind"] == "MAD"]
    e2 = (Z[keep].abs() > thr).sum(axis=1) >= mina
    R["sensitivity_no_meanAD_features"] = {"n_features": len(keep), "dropped_features": [k for k in used if k not in keep],
                                           "n_outliers": int(e2.sum()), "rate": wl(int(e2.sum()), N),
                                           "overlap_with_primary": int((e2 & is_out).sum())}
    # sensitivity: within stratum
    scol = {"swechat": "format", "aiv_cu": "stratum", "cc_local": "stratum", "aiv_cc": "stratum", "whowhen": "stratum"}[corpus]
    within = pd.Series(np.nan, index=F.index)
    per_s = []
    for sv, idx in F.groupby(scol).groups.items():
        if len(idx) < 20:
            per_s.append({"stratum": str(sv), "n": int(len(idx)), "n_outliers": None, "note": "< 20 sessions, no within-stratum z"})
            continue
        Zs, infs, drs = robust_z(F.loc[idx], feats)
        es = ((Zs.abs() > thr).sum(axis=1) >= mina)
        within.loc[idx] = es.astype(float)
        per_s.append({"stratum": str(sv), "n": int(len(idx)), "n_features_used": len(Zs.columns), "n_outliers": int(es.sum()),
                      "rate": wl(int(es.sum()), int(len(idx))), "primary_outliers_in_stratum": int(is_out.loc[idx].sum()),
                      "overlap_with_primary": int((es & is_out.loc[idx]).sum())})
    cov = within.notna()
    R["sensitivity_within_stratum"] = {"stratum_column": scol, "per_stratum": per_s, "n_sessions_covered": int(cov.sum()),
                                       "n_outliers_within": int((within == 1).sum()),
                                       "n_primary_outliers_covered": int((is_out & cov).sum()),
                                       "overlap": int(((within == 1) & is_out).sum())}
    # POSTHOC P2
    R["POSTHOC_P2_permutation_null_tail"] = permutation_null_tail(Z, thr, list(range(3, 13)), PREREG["permutation_null"]["n_perm"],
                                                                 PREREG["permutation_null"]["seed"])
    # POSTHOC P3
    svals = F[scol].astype(str)
    R["POSTHOC_P3_stratum_sizes"] = {str(k): int(v) for k, v in svals.value_counts().items()}
    R["POSTHOC_P3_extremes_by_stratum"] = {k: {str(sv): int(((Z[k].abs() > thr) & (svals == sv)).sum())
                                               for sv in svals.unique() if ((Z[k].abs() > thr) & (svals == sv)).any()} for k in used}
    R["POSTHOC_P3_outliers_by_stratum"] = {str(sv): int((is_out & (svals == sv)).sum()) for sv in svals.unique()}
    cb = []
    for crow in R["top_axis_combos"][:10]:
        members = Counter()
        for i in np.nonzero(is_out.to_numpy())[0]:
            row = Z.iloc[i]
            tags = sorted(f"{k}{'+' if row[k] > 0 else '-'}" for k in used if abs(row[k]) > thr)
            if " & ".join(tags) == crow["combo"]:
                members[svals.iat[i]] += 1
        cb.append({"combo": crow["combo"], "n": crow["n"], "by_stratum": dict(members)})
    R["POSTHOC_P3_top_combos_by_stratum"] = cb
    # POSTHOC P4: profiles of within-stratum outliers (covered sessions only)
    if cov.any():
        Fc = F[cov].copy()
        wo = (within[cov] == 1)
        R["POSTHOC_P4_within_stratum_profiles"] = {c: group_profile(Fc, wo, c) for c in prof_cols + extra_cols}
    # POSTHOC P5
    R["POSTHOC_P5_followups"] = followups(corpus, F, is_out, within)
    # POSTHOC P7
    if f"gap_bin_{GAP_BINS[0]}" in F.columns and corpus != "whowhen":
        gb = {}
        for lo in GAP_BINS:
            c_all = pd.to_numeric(F[f"gap_bin_{lo}"], errors="coerce").fillna(0)
            c_sh = pd.to_numeric(F[f"gap_bin_shell_{lo}"], errors="coerce").fillna(0)
            gb[f"[{lo},{lo + 2})"] = {"gaps": int(c_all.sum()), "sessions": int((c_all > 0).sum()),
                                      "shell_gaps": int(c_sh.sum()), "shell_sessions": int((c_sh > 0).sum()),
                                      "gaps_in_outliers": int(c_all[is_out].sum())}
        tools_by_bin = {}
        for lo in (120, 600):
            cn = Counter()
            for x in F[f"gap_bin_tools_{lo}"].dropna():
                for k, v in json.loads(x).items():
                    if corpus == "cc_local" and k not in BUILTIN_TOOLS | CC_PUBLIC_TOOL_NAMES:
                        k = "other"
                    cn[k] += v
            tools_by_bin[f"[{lo},{lo + 2})"] = dict(cn.most_common())
        R["POSTHOC_P7_timeout_gap_bins"] = {"n_paired_calls": int(pd.to_numeric(F.get("n_paired_calls"), errors="coerce").fillna(0).sum()),
                                            "bins": gb, "normalized_tool_by_bin": tools_by_bin}
    # picks
    rank = pick_rank(Z, ext, n_ext, is_out, F, corpus)
    npk = PREREG["picks"]["n_per_corpus"][corpus]
    picks = []
    attr_cols = {"swechat": ["stratum", "format", "repo_id", "cli_version", "created_month", "model_top", "top_tool"],
                 "aiv_cu": ["stratum", "model_string", "shape", "model_top", "top_tool", "n_turns"],
                 "aiv_cc": ["stratum", "model_top", "top_tool_class"],
                 "cc_local": ["stratum", "model_top", "top_tool_class"],
                 "whowhen": ["stratum", "is_correct", "level", "history_len", "mistake_step", "agent_vs_speaker", "top_tool"]}[corpus]
    show = ["n_events", "n_calls", "n_tools_distinct", "span_s", "out_tokens_total", "native_err_frac", "marker_err_frac",
            "trunc_frac", "redacted_frac", "subagent_share", "ts_backward_frac", "ts_tie_frac", "unpaired_call_frac",
            "orphan_result_frac", "max_identical_call", "compactions", "length_tercile", "last_kind",
            "flag_ends_unanswered_call", "max_cr_gap_s", "max_cr_gap_marker", "failed_resume_rows"]
    for j, (i, r) in enumerate(rank.head(npk).iterrows()):
        row = Z.loc[i]
        axes = sorted([{"feature": k, "z": float(row[k]), "value": fmt(F.at[i, k])} for k in used if abs(row[k]) > thr],
                      key=lambda a: -abs(a["z"]))
        pk = {"rank": j + 1, "n_extreme": int(r["n_ext"]), "zsum_capped": float(r["zsum"]), "extreme_axes": axes,
              "numbers": {c: fmt(F.at[i, c]) for c in show if c in F.columns},
              "attributes": {c: fmt(F.at[i, c]) for c in attr_cols if c in F.columns},
              "POSTHOC_P5_error_marker_names": json.loads(F.at[i, "marker_names"]) if "marker_names" in F.columns else None}
        if corpus == "cc_local":
            pk["alias"] = f"cc_local_pick_{j + 1}"
        else:
            pk["session_id"] = F.at[i, "session_id"]
        picks.append(pk)
    R["picks"] = picks
    R["n_picks"] = len(picks)
    R["picks_summary"] = {
        "length_tercile": dict(Counter(p["numbers"].get("length_tercile") for p in picks)),
        "stratum": dict(Counter(str(p["attributes"].get("stratum")) for p in picks)),
        "n_events_le_10": sum(1 for p in picks if (p["numbers"].get("n_events") or 0) <= 10),
        "n_extreme_range": [min(p["n_extreme"] for p in picks), max(p["n_extreme"] for p in picks)] if picks else None}
    return R


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, set):
        return [clean(v) for v in sorted(o)]
    if o is pd.NA or o is pd.NaT:
        return None
    return fmt(o)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all", choices=["all", "features", "report"])
    ap.add_argument("--corpora", default=",".join(CORPORA))
    a = ap.parse_args()
    os.makedirs(INTER_DIR, exist_ok=True)
    corp = a.corpora.split(",")
    if a.stage in ("all", "features"):
        for c in corp:
            t0 = time.time()
            F = build_features(c)
            F.to_parquet(os.path.join(INTER_DIR, f"{c}_features.parquet"), index=False)
            print(f"{c}: {len(F)} sessions, {time.time() - t0:.1f}s", flush=True)
    if a.stage in ("all", "report"):
        J = {"lens": "outliers", "script": "analysis/probes/phase_c_outliers.py", "prereg": PREREG, "posthoc": POSTHOC,
             "corpora": {}}
        for c in CORPORA:
            p = os.path.join(INTER_DIR, f"{c}_features.parquet")
            if not os.path.exists(p):
                continue
            F = pd.read_parquet(p)
            J["corpora"][c] = analyse(c, F)
            print(f"{c}: outliers {J['corpora'][c]['n_outliers']}/{J['corpora'][c]['n_sessions']}", flush=True)
        J["summary"] = {c: {"n_sessions": R["n_sessions"], "n_features_used": R["n_features_used"], "n_outliers": R["n_outliers"],
                            "outlier_rate": R["outlier_rate"], "null_ge3": R["permutation_null_n_outliers"],
                            "within_stratum_outliers": R["sensitivity_within_stratum"]["n_outliers_within"],
                            "within_stratum_sessions_covered": R["sensitivity_within_stratum"]["n_sessions_covered"],
                            "no_meanAD_outliers": R["sensitivity_no_meanAD_features"]["n_outliers"]}
                        for c, R in J["corpora"].items()}
        try:  # context: the swechat_tables lens ran the same rule on sessions-table features (copied, not recomputed)
            sw = json.load(open(os.path.join(OUT_DIR, "swechat_tables.json"), encoding="utf-8"))["part4_outliers"]["claude_code"]
            J["context_swechat_tables_part4_claude_code"] = {k: sw[k] for k in ("n", "n_features_used", "n_outliers", "outlier_rate")}
        except Exception as e:  # noqa: BLE001
            J["context_swechat_tables_part4_claude_code"] = {"error": repr(e)}
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(OUT_JSON, "w", encoding="utf-8") as fh:
            json.dump(clean(J), fh, indent=1, allow_nan=False)
        print("wrote", OUT_JSON)


if __name__ == "__main__":
    main()
