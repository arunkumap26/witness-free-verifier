"""Phase C lens `two_clocks`: every pair of independent clocks / timers recorded for the same event, and the physical
inequalities between them.

Writes RAW COUNTS ONLY to analysis/out/phase_c/two_clocks.json. Interpretation lives in analysis/notes/two_clocks.md.

Inputs
  analysis/cache/{swechat,cc_local,aiv_cc,aiv_cu}_B.parquet   IR caches, Phase B split (needed columns only)
  analysis/cache/swechat_population.parquet                    session -> transcript format
  data/swe-chat-pinned/transcripts/<sid>.jsonl (READ-ONLY)     raw fields the IR drops, for B sessions only:
      Claude Code: system/api_error retryInMs, stop_hook_summary hookInfos[].durationMs, hook_progress toolUseID,
                   attachment hook_* durationMs, per-entry `version`
      OpenCode:    message info.time.created/completed, part time.start/end, tool state.time.start/end/compacted,
                   ascending ids (msg_/prt_/ses_) that embed a creation time
  cc_local is PRIVATE: only aggregates of it reach the JSON (no ids, no text, no paths).

Every pair is reported as: n, n_sessions, the inequality that must hold, violation counts and session-clustered rates
(lib/stats.cluster_rate) at the pre-registered tolerance, at 0 and at the gross level, the slack distribution
(describe + clustered median CI) and the quantization of each timer. Slack is always defined so that the inequality
holds iff slack >= 0. Violators are characterized (by tool / status / subagent / version) and, for public corpora only,
up to PREREG.max_examples examples are listed.

Run:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_c_two_clocks [section ...]
      (no argument = all sections, writes the JSON; with arguments = only those sections, printed, nothing written)
"""
import json, os, re, sys, math
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from analysis.lib import stats

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE = os.path.join(ROOT, "analysis", "cache")
OUT = os.path.join(ROOT, "analysis", "out", "phase_c", "two_clocks.json")
SWE_TX = os.environ.get("SWE_TX", r"C:\Swarms\data\swe-chat-pinned\transcripts")

# ---------------------------------------------------------------------------------------------------------------------
# PRE-REGISTRATION. Fixed before any outcome of this script was computed. Changes after the first run go to POST_HOC.
# ---------------------------------------------------------------------------------------------------------------------
PREREG = {
    "slack_sign": "slack is defined per pair so that the physical inequality holds iff slack >= 0 (ms)",
    "tol_ms_event_clock": {"value": 2.0, "reason": "ISO timestamps at 1 ms resolution: a difference of two stamps can be "
                                                   "off by <1 ms, an integer-ms timer by <1 ms more"},
    "tol_ms_row_insert_clock": {"value": 1.0, "reason": "AI Village created_at has us resolution; only the integer-ms timer rounds"},
    "gross_ms": {"value": 1000.0, "reason": "a violation larger than 1 s cannot be rounding at any resolution used here "
                                            "except whole-second fields, which get their own rule"},
    "elapsed_seconds_rule": {"any_rounding": "lag_ms >= 1000*(elapsedTimeSeconds - 1) - tol (holds for floor, round or ceil)",
                             "floor": "lag_ms >= 1000*elapsedTimeSeconds - tol (holds only if the timer is floored)",
                             "reason": "elapsedTimeSeconds is an integer; its rounding rule is not documented"},
    "timeout_grace_ms": {"value": 1000.0, "reason": "a harness timer may overrun its own timeout by kill/teardown latency; "
                                                    "1 s is generous for that and smaller than any timeout in the data"},
    "gap_over_timeout_report_ms": {"value": 5000.0, "reason": "call->result gaps include permission/approval waits, so "
                                                              "gap > timeout is descriptive, not a violation; >5 s reported"},
    "http_date_resolution_ms": {"value": 1000.0, "reason": "HTTP Date header is floored to the second"},
    "epoch_seconds_resolution_ms": {"value": 1000.0, "reason": "Codex started_at/completed_at are integer epoch seconds"},
    "apply_patch_duration_seconds_tol_ms": {"value": 52.0, "reason": "metadata.duration_seconds is printed at 0.1 s: half "
                                                                     "a step (50 ms) + event-clock tol"},
    "turn_duration": {"value": "no direction assumed; tested span >= durationMs - tol AND |span - durationMs| <= 1000 ms, "
                               "for two turn-start definitions (last human prompt before the turn_duration event; first "
                               "human prompt after the previous turn_duration)", "reason": "the timer's start point is undocumented"},
    "stop_hooks": {"value": "slack_max = (summary.ts - first hook_progress(Stop, same toolUseID).ts) - max(hookInfos.durationMs) "
                            "must be >= -tol; slack_sum (with sum) reported as a parallel-vs-serial probe, not a violation",
                   "reason": "hooks of one event cannot run longer than the wall time between their start and the summary"},
    "api_error_retry": {"value": "child entry (raw parentUuid == this api_error uuid): child.ts - api_error.ts >= retryInMs - tol",
                        "reason": "the harness sleeps retryInMs before retrying; the child is written after the retry"},
    "uuid7": {"value": "a UUID whose version nibble is 7 carries unix ms in its first 48 bits; residual = event ts - uuid ms",
              "reason": "RFC 9562"},
    "opencode_ids": {"value": "OpenCode ascending ids: hex12 after the prefix = (ms*0x1000 + counter) mod 2^48, so "
                              "ms mod 2^36 = hex12 // 0x1000; descending ids (ses_) are the bitwise NOT. Residual = "
                              "reference ms - decoded ms, unwrapped to the nearest multiple of 2^36",
                     "reason": "hypothesis from the id layout; tested, not assumed (a null is reported if it fails)"},
    "max_examples": {"value": 12, "reason": "violator examples listed per pair, public corpora only"},
    "quantiles_with_ci": [0.05, 0.5, 0.95],
    "corpora_split": "Phase B caches only (2000 swechat, 186 cc_local, 189 aiv_cc, 2000 aiv_cu sessions); raw reads restricted to B sessions",
}
POST_HOC = {  # everything added or changed after a first run of a section had been inspected; keys carry POSTHOC_ where possible
    "time_conversion_fix": "run 0 divided pandas datetime int64 by 1e6 assuming ns, but pandas 3 infers us/ms units from the "
                           "strings; all gaps were off by 1000x. Fixed (unit-agnostic Timedelta division) before any number was "
                           "interpreted; no reported number comes from run 0.",
    "cc_result_timers.gap_exact_0/timer_negative/negative_timer_examples": "added after run 1 showed one Glob with gap 0 and one "
                                                                           "negative durationMs",
    "cc_bash_progress.parent_split": "run 1 pooled progress whose parent is a Task/Agent call (a subagent's Bash reporting under "
                                     "the parent id) with direct Bash progress; split afterwards. any_rounding/floor violations were "
                                     "0 in both versions; tick statistics are now direct-Bash only. tick_gaps_over_1500ms and "
                                     "calls_over_timeout were added after the single elapsed>timeout case was inspected.",
    "cc_turn_duration.POSTHOC_resid_by_calls_in_turn": "added after run 1 showed the residual is not near 0 (|res|<=1 s ~22%)",
    "cc_subagent_containment.POSTHOC_total_vs_result_minus_first_nested / result_before_last_nested": "added after run 1 "
        "(gap - totalDurationMs looked equal to first-nested - call; cc_local containment failed 63/63)",
    "cc_raw.api_error_retry.POSTHOC_child_is_same_loop_next_attempt": "added after inspecting the 5 violators (user interrupts, "
                                                                       "another concurrent retry loop)",
    "cc_raw.api_error_retry.POSTHOC_retryInMs_in_band...": "band 500*2^(a-1)*[1,1.25] capped at 32000 read off retryInMs_by_attempt "
                                                           "in run 1, then counted; it is a description, not a test",
    "cc_raw.hook_attachments.POSTHOC_*_vs_call": "run 1 found 0 attachment<->hook_progress joins (versions writing hook "
                                                 "attachments write no hook_progress); the tool call is used as the start anchor",
    "cc_raw.tool_hook_progress_vs_call_result": "added with the attachment change (ordering of hook start vs call/result)",
    "cc_identical_timestamps": "whole section added after the gap-0 Glob turned out to sit in a block of identically stamped "
                               "entries (v1.0.112) and the negative Glob in a transient backward reading",
    "codex.POSTHOC_running_output_gap_ge_min_yield_30s": "run 1: 9/1682 violations, every violator's header says 'Wall time: "
                                                         "30.0x seconds' with yield_time_ms 120000/1200000; effective cap 30 s",
    "codex.exited_before_yield_duration_le_yield": "run 1 (all results with a yield, incl. write_stdin results carrying a deferred "
                                                   "process duration): 452/2524 violations; restricted to exec_command results with "
                                                   "their own end: 0/1791. The run-1 definition was wrong (compared a whole process "
                                                   "duration with one poll's yield).",
    "codex.wall_time_header": "added after the 'Wall time: X seconds' header was seen in violator texts",
    "codex.POSTHOC_end_ts_minus_started_at_vs_duration_ms / POSTHOC_task_started_event_lag_vs_span_violation":
        "added after run 1: 16/77 end.ts - task_started.ts < duration_ms and 18/89 task_started events logged >1 s after started_at",
    "codex.task_started_ts_vs_started_at.POSTHOC_late_by_first_turn": "added after the 18 late task_started events were seen "
                                                                       "to fall in 18 different sessions",
    "ineq.violator_sessions_tol / wilson_violation_tol": "reporting fields added to every inequality block after run 1 (no "
                                                          "threshold changed)",
    "opencode.part_id_clock role split": "run 1 keyed parts by type only; 'text' mixed user and assistant parts (267/1079 "
                                         "violations, all user); now keyed type|role",
    "opencode.session_updated_ge_last_message extras": "added after run 1 (208/214 violations) to locate what updated tracks",
    "opencode.tool_duration_le_input_timeout.violator_examples": "added after run 1 (1 violator)",
    "cc_local_cost_state.POSTHOC_end_minus_last_event_within_1s_of_900000ms": "the 900 s constant was read off the run-1 "
                                                                               "distribution, then counted",
    "ts_resolution, aiv_cc_reused_from_aiv_accounting": "descriptive context, added after the section runs",
}

TOL = PREREG["tol_ms_event_clock"]["value"]
TOL_RI = PREREG["tol_ms_row_insert_clock"]["value"]
GROSS = PREREG["gross_ms"]["value"]
GRACE = PREREG["timeout_grace_ms"]["value"]
MAXEX = PREREG["max_examples"]["value"]


# ---------------------------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------------------------
def to_ms(s):
    """ISO strings -> float epoch ms (us precision kept). NaN where missing/unparseable."""
    t = pd.to_datetime(pd.Series(s, dtype="object"), utc=True, format="ISO8601", errors="coerce")
    # unit-agnostic (pandas may infer s/ms/us/ns resolution from the strings)
    v = (t - pd.Timestamp("1970-01-01", tz="UTC")) / pd.Timedelta(milliseconds=1)
    return v.astype("float64").values


def jl(x):
    if x is None or (isinstance(x, float) and math.isnan(x)) or x is pd.NA:
        return {}
    try:
        o = json.loads(x)
        return o if isinstance(o, dict) else {}
    except Exception:
        return {}


def crate(sid, flag):
    """session-clustered rate of a boolean flag over pairs."""
    sid = np.asarray(sid)
    flag = np.asarray(flag, dtype=float)
    if len(sid) == 0:
        return {"rate": None, "lo": None, "hi": None, "n_sessions": 0, "num": 0.0, "den": 0.0}
    df = pd.DataFrame({"s": sid, "f": flag})
    g = df.groupby("s")["f"].agg(["sum", "count"])
    return stats.cluster_rate(g["sum"].values, g["count"].values)


def cq(values, sid, q):
    v = np.asarray(values, dtype=float)
    s = np.asarray(sid)
    ok = ~np.isnan(v)
    return stats.cluster_quantile(v[ok], s[ok], q)


def ineq(sid, slack, tol, label, gross=GROSS, with_ci=True):
    """Standard block for one inequality: slack >= 0 must hold."""
    sid = np.asarray(sid)
    slack = np.asarray(slack, dtype=float)
    ok = ~np.isnan(slack)
    sid, slack = sid[ok], slack[ok]
    out = {"inequality": label, "n": int(len(slack)), "n_sessions": int(len(set(sid.tolist()))), "tol_ms": tol,
           "violations_tol": int((slack < -tol).sum()), "violations_0": int((slack < 0).sum()),
           "violations_gross": int((slack < -gross).sum()),
           "violator_sessions_tol": int(len(set(sid[slack < -tol].tolist())))}
    if len(slack) == 0:
        return out
    out["rate_violation_tol"] = crate(sid, slack < -tol)
    out["rate_violation_gross"] = crate(sid, slack < -gross)
    # pair-level Wilson interval (ignores clustering): reported because a clustered bootstrap of 0 events is [0, 0]
    w = stats.wilson(int((slack < -tol).sum()), int(len(slack)))
    out["wilson_violation_tol"] = {"p": w[0], "lo": w[1], "hi": w[2]}
    out["slack_ms_describe"] = stats.describe(slack, qs=(0.0, 0.001, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 0.999, 1.0))
    if with_ci:
        out["slack_ms_quantiles_ci"] = {f"p{int(q * 100)}": cq(slack, sid, q) for q in PREREG["quantiles_with_ci"]}
    v = slack[slack < -tol]
    if len(v):
        out["violator_slack_ms_describe"] = stats.describe(v)
    return out


def quant_int_ms(values):
    """Quantization of a timer stored in ms."""
    v = np.asarray(values, dtype=float)
    v = v[~np.isnan(v)]
    if len(v) == 0:
        return {"n": 0}
    isint = np.isclose(v, np.round(v))
    vi = np.round(v[isint]).astype(np.int64)
    out = {"n": int(len(v)), "integer": int(isint.sum()), "zero": int((v == 0).sum()), "negative": int((v < 0).sum())}
    if len(vi):
        out["last_digit"] = {str(k): int(c) for k, c in sorted(Counter((vi % 10).tolist()).items())}
        out["last_digit_chi2_uniform"] = stats.chi2_uniform([int(((vi % 10) == k).sum()) for k in range(10)])
        out["div_by_10"] = int((vi % 10 == 0).sum())
        out["div_by_100"] = int((vi % 100 == 0).sum())
        out["div_by_1000"] = int((vi % 1000 == 0).sum())
    return out


def decimals_of(raw_values):
    """Count decimal digits of float values as written (repr of the parsed JSON float)."""
    c = Counter()
    for x in raw_values:
        if x is None:
            continue
        r = repr(float(x)) if not isinstance(x, int) else str(x)
        if "e" in r or "E" in r:
            c["sci"] += 1
        elif "." in r:
            d = r.split(".")[1]
            c[str(0 if d == "0" else len(d))] += 1
        else:
            c["0"] += 1
    return dict(sorted(c.items()))


def examples(df, cols, n=MAXEX, sort_col=None):
    if df is None or len(df) == 0:
        return []
    d = df.sort_values(sort_col) if sort_col else df
    d = d.head(n)
    out = []
    for r in d[cols].itertuples(index=False):
        row = {}
        for c, v in zip(cols, r):
            if isinstance(v, (np.floating, float)):
                v = None if math.isnan(v) else round(float(v), 3)
            elif isinstance(v, (np.integer,)):
                v = int(v)
            elif v is pd.NA:
                v = None
            row[c] = v
        out.append(row)
    return out


def counts(series):
    return {str(k): int(v) for k, v in Counter(series.tolist() if hasattr(series, "tolist") else series).most_common()}


def load(corpus, columns, filters=None):
    return pd.read_parquet(os.path.join(CACHE, f"{corpus}_B.parquet"), columns=columns, filters=filters)


_POP = None


def swe_format():
    global _POP
    if _POP is None:
        _POP = pd.read_parquet(os.path.join(CACHE, "swechat_population.parquet"), columns=["session_id", "format"])
    return _POP


def swe_sessions(fmt):
    b = pd.read_parquet(os.path.join(CACHE, "swechat_B.parquet"), columns=["session_id"]).session_id.unique()
    p = swe_format()
    return sorted(set(p[p.format == fmt].session_id) & set(b))


# ---------------------------------------------------------------------------------------------------------------------
# Claude Code (swechat CC format, cc_local, aiv_cc): IR loading
# ---------------------------------------------------------------------------------------------------------------------
def load_cc(corpus):
    cols = ["session_id", "seq", "kind", "ts", "tool_raw", "call_id", "parent_call_id", "is_subagent", "extra", "uuid"]
    ev = load(corpus, cols)
    if corpus == "swechat":
        keep = set(swe_sessions("claude_code"))
        ev = ev[ev.session_id.isin(keep)]
    ev = ev.reset_index(drop=True)
    ev["t"] = to_ms(ev.ts)
    ev["is_subagent"] = ev.is_subagent.fillna(False).astype(bool)
    return ev


def cc_calls(ev):
    c = ev[ev.kind == "call"][["session_id", "call_id", "t", "seq", "tool_raw", "is_subagent", "uuid"]]
    dup = int(c.duplicated(["session_id", "call_id"]).sum())
    c = c.drop_duplicates(["session_id", "call_id"], keep="first")
    return c.rename(columns={"t": "t_call", "seq": "seq_call", "uuid": "uuid_call"}), dup


def cc_results(ev):
    r = ev[ev.kind == "result"][["session_id", "call_id", "t", "seq", "tool_raw", "extra", "uuid"]]
    dup = int(r.duplicated(["session_id", "call_id"]).sum())
    r = r.drop_duplicates(["session_id", "call_id"], keep="first")
    return r.rename(columns={"t": "t_res", "seq": "seq_res", "uuid": "uuid_res"}), dup


def load_call_args(corpus, tools):
    a = load(corpus, ["session_id", "call_id", "args"], filters=[("kind", "=", "call"), ("tool_raw", "in", tools)])
    a = a.drop_duplicates(["session_id", "call_id"])
    a["a"] = [jl(x) for x in a.args]
    return a.drop(columns=["args"])


# ---------------------------------------------------------------------------------------------------------------------
# Section 1: tool-reported timers on Claude Code results vs call->result gap
# ---------------------------------------------------------------------------------------------------------------------
TIMER_FIELDS = [("durationMs", 1.0), ("durationSeconds", 1000.0), ("totalDurationMs", 1.0), ("timedOutAfterMs", 1.0)]


def sec_cc_result_timers(corpus, ev, private=False):
    tol = TOL_RI if corpus == "aiv_cc" else TOL
    calls, dupc = cc_calls(ev)
    res, dupr = cc_results(ev)
    m = res.merge(calls.drop(columns=["tool_raw"]), on=["session_id", "call_id"], how="left")
    out = {"tol_ms": tol, "duplicate_call_ids": dupc, "duplicate_result_ids": dupr, "pairs": {}}
    rows = []
    for x, tr, sid, tres, tcall, sub, cid, ur in zip(m.extra, m.tool_raw, m.session_id, m.t_res, m.t_call, m.is_subagent,
                                                     m.call_id, m.uuid_res):
        o = jl(x)
        for f, mult in TIMER_FIELDS:
            if f in o and isinstance(o[f], (int, float)) and not isinstance(o[f], bool):
                rows.append((sid, tr, f, float(o[f]) * mult, o[f], tres, tcall, sub, cid, ur,
                             o.get("backgroundTaskId") is not None, bool(o.get("interrupted"))))
    df = pd.DataFrame(rows, columns=["session_id", "tool_raw", "field", "timer_ms", "raw", "t_res", "t_call", "is_subagent",
                                     "call_id", "uuid_res", "background", "interrupted"])
    out["results_with_timer_no_call"] = int(df.t_call.isna().sum()) if len(df) else 0
    df = df[df.t_call.notna()].copy()
    df["gap"] = df.t_res - df.t_call
    df["slack"] = df.gap - df.timer_ms
    for (tr, f), g in df.groupby(["tool_raw", "field"]):
        key = f"{tr}|{f}"
        blk = ineq(g.session_id.values, g.slack.values, tol, "result.ts - call.ts >= timer")
        blk["by_subagent"] = {str(k): {"n": int(len(gg)), "violations_tol": int((gg.slack < -tol).sum())}
                              for k, gg in g.groupby("is_subagent")}
        blk["timer_quantization"] = quant_int_ms(g.timer_ms.values) if f != "durationSeconds" else {
            "decimals_as_written": decimals_of(g.raw.tolist()), **quant_int_ms(g.timer_ms.values)}
        blk["spearman_gap_vs_timer"] = float(pd.Series(g.gap.values).corr(pd.Series(g.timer_ms.values), method="spearman")) if len(g) > 2 else None
        blk["timer_ms_describe"] = stats.describe(g.timer_ms.values)
        blk["gap_exact_0"] = int((g.gap.round(3) == 0).sum())
        blk["timer_negative"] = int((g.timer_ms < 0).sum())
        if not private and (g.timer_ms < 0).any():
            blk["negative_timer_examples"] = examples(g[g.timer_ms < 0], ["session_id", "call_id", "timer_ms", "gap"], sort_col="timer_ms")
        v = g[g.slack < -tol]
        if len(v):
            blk["violators_background"] = int(v.background.sum())
            blk["violators_interrupted"] = int(v.interrupted.sum())
            if not private:
                blk["violator_examples"] = examples(v, ["session_id", "call_id", "timer_ms", "gap", "slack", "is_subagent"], sort_col="slack")
        out["pairs"][key] = blk
    return out, df


# ---------------------------------------------------------------------------------------------------------------------
# Section 2: Claude Code bash_progress / mcp_progress timers vs ts since the call (swechat only; cc_local/aiv_cc have none)
# ---------------------------------------------------------------------------------------------------------------------
def sec_cc_bash_progress(ev, args):
    calls, _ = cc_calls(ev)
    res, _ = cc_results(ev)
    meta = ev[(ev.kind == "meta") & ev.extra.str.contains('"bash_progress"', na=False)]
    rows = []
    for sid, seq, t, pc, x, sub in zip(meta.session_id, meta.seq, meta.t, meta.parent_call_id, meta.extra, meta.is_subagent):
        o = jl(x)
        rows.append((sid, seq, t, pc, o.get("elapsedTimeSeconds"), o.get("timeoutMs"), o.get("totalLines"), sub))
    bp = pd.DataFrame(rows, columns=["session_id", "seq", "t", "call_id", "elapsed", "timeoutMs", "totalLines", "is_subagent_ev"])
    out = {"n_progress_events": int(len(bp)), "n_sessions_with_progress": int(bp.session_id.nunique()),
           "elapsed_types": counts([type(x).__name__ for x in bp.elapsed])}
    bp = bp.merge(calls[["session_id", "call_id", "t_call", "tool_raw", "is_subagent", "seq_call", "uuid_call"]],
                  on=["session_id", "call_id"], how="left")
    out["progress_without_call_in_session"] = int(bp.t_call.isna().sum())
    out["progress_call_tool_raw"] = counts(bp.tool_raw.fillna("<none>"))
    bp = bp[bp.t_call.notna() & bp.elapsed.notna()].copy()
    bp["elapsed"] = bp.elapsed.astype(float)
    bp["lag"] = bp.t - bp.t_call
    bp["res"] = bp.lag - 1000.0 * bp.elapsed
    # progress whose parent is a Task/Agent call = a subagent's Bash reporting under the parent's id: several nested Bash
    # calls share one parent, so per-call tick structure is only meaningful for direct Bash parents
    nested = bp[bp.tool_raw != "Bash"]
    out["parent_is_task_or_agent"] = {
        "n": int(len(nested)), "n_parents": int(nested.groupby(["session_id", "call_id"]).ngroups),
        "any_rounding": ineq(nested.session_id.values, nested.res.values + 1000.0, TOL, "progress.ts - parent call.ts >= 1000*(elapsed-1)"),
        "floor_rule": ineq(nested.session_id.values, nested.res.values, TOL, "progress.ts - parent call.ts >= 1000*elapsed")}
    bp_all = bp
    bp = bp[bp.tool_raw == "Bash"].copy()
    out["direct_bash_progress_events"] = int(len(bp))
    out["any_rounding"] = ineq(bp.session_id.values, bp.res.values + 1000.0, TOL,
                               "progress.ts - call.ts >= 1000*(elapsedTimeSeconds-1)")
    out["floor_rule"] = ineq(bp.session_id.values, bp.res.values, TOL, "progress.ts - call.ts >= 1000*elapsedTimeSeconds")
    out["elapsed_value_counts_top"] = dict(list(counts(bp.elapsed.astype(int)).items())[:15])
    # per call structure: first tick, tick spacing, offset stability
    bp = bp.sort_values(["session_id", "call_id", "seq"])
    g = bp.groupby(["session_id", "call_id"], sort=False)
    first = g.head(1)
    out["first_tick_elapsed_counts"] = dict(list(counts(first.elapsed.astype(int)).items())[:10])
    out["first_tick_lag_ms_describe"] = stats.describe(first.lag.values)
    bp["d_t"] = g.t.diff()
    bp["d_e"] = g.elapsed.diff()
    tk = bp[bp.d_t.notna()]
    out["tick_delta_elapsed_counts"] = dict(list(counts(tk.d_e.astype(int)).items())[:10])
    tk1 = tk[tk.d_e == 1]
    out["tick_dt_minus_1000_ms_describe_when_d_e_1"] = stats.describe((tk1.d_t - 1000.0).values)
    out["tick_dt_exact_1000_when_d_e_1"] = {"k": int((tk1.d_t.round(3) == 1000.0).sum()), "n": int(len(tk1))}
    out["tick_dt_nonpositive"] = int((tk.d_t <= 0).sum())
    out["tick_d_e_nonpositive"] = int((tk.d_e <= 0).sum())
    # tick gaps: consecutive ticks of one call more than 1.5 s apart (missed ticks). If elapsed is wall-clock based it
    # advances with the gap (|d_t - 1000*d_e| < 1000); a monotonic/paused timer would not.
    gp = tk[tk.d_t > 1500].copy()
    gp["wall_consistent"] = (gp.d_t - 1000.0 * gp.d_e).abs() < 1000.0
    out["tick_gaps_over_1500ms"] = {"n": int(len(gp)), "n_calls": int(gp.groupby(["session_id", "call_id"]).ngroups),
                                    "n_sessions": int(gp.session_id.nunique()), "elapsed_advances_with_wall_clock": int(gp.wall_consistent.sum()),
                                    "gap_ms_describe": stats.describe(gp.d_t.values),
                                    "gap_over_60s": int((gp.d_t > 60000).sum()), "gap_over_600s": int((gp.d_t > 600000).sum())}
    rng = g.res.agg(lambda s: float(s.max() - s.min()))
    out["per_call_residual_range_ms_describe"] = stats.describe(rng.values)
    out["n_calls_with_progress"] = int(len(rng))
    # residual modulo structure (sub-second phase of the first tick relative to the call stamp)
    out["first_tick_residual_ms_describe"] = stats.describe((first.lag - 1000.0 * first.elapsed).values)
    # violators
    v = bp[bp.res + 1000.0 < -TOL]
    vf = bp[bp.res < -TOL]
    out["any_rounding"]["violators_by_subagent"] = counts(v.is_subagent)
    out["any_rounding"]["violator_calls"] = int(v.groupby(["session_id", "call_id"]).ngroups)
    out["any_rounding"]["violator_sessions"] = int(v.session_id.nunique())
    out["any_rounding"]["violator_examples"] = examples(v, ["session_id", "call_id", "elapsed", "lag", "res"], sort_col="res")
    out["floor_rule"]["violators_by_subagent"] = counts(vf.is_subagent)
    out["floor_rule"]["violator_calls"] = int(vf.groupby(["session_id", "call_id"]).ngroups)
    # result after last tick, and gap >= last elapsed
    last = g.tail(1).merge(res[["session_id", "call_id", "t_res", "extra"]], on=["session_id", "call_id"], how="left")
    out["calls_with_progress_without_result"] = int(last.t_res.isna().sum())
    lr = last[last.t_res.notna()]
    out["result_after_last_tick"] = ineq(lr.session_id.values, (lr.t_res - lr.t).values, TOL, "result.ts >= last progress.ts")
    out["result_gap_vs_last_elapsed_any_rounding"] = ineq(lr.session_id.values, (lr.t_res - lr.t_call - 1000.0 * (lr.elapsed - 1)).values, TOL,
                                                          "result.ts - call.ts >= 1000*(last elapsed - 1)")
    lr = lr.assign(interrupted=[bool(jl(x).get("interrupted")) for x in lr.extra],
                   background=[jl(x).get("backgroundTaskId") is not None for x in lr.extra])
    out["result_after_last_tick"]["violators_interrupted"] = int(lr[(lr.t_res - lr.t) < -TOL].interrupted.sum())
    out["result_after_last_tick"]["violators_background"] = int(lr[(lr.t_res - lr.t) < -TOL].background.sum())
    out["result_after_last_tick"]["violator_examples"] = examples(lr[(lr.t_res - lr.t) < -TOL].assign(after=lambda d: d.t_res - d.t),
                                                                  ["session_id", "call_id", "elapsed", "after", "interrupted", "background"], sort_col="after")
    # timeouts: elapsed vs the harness's own timeoutMs (every progress event carries its own timeoutMs: all parents)
    to = bp_all[bp_all.timeoutMs.notna()].copy()
    to["timeoutMs"] = to.timeoutMs.astype(float)
    out["timeout_present"] = {"k": int(len(to)), "n": int(len(bp_all))}
    out["elapsed_vs_timeoutMs"] = ineq(to.session_id.values, (to.timeoutMs + GRACE - 1000.0 * to.elapsed).values, 0.0,
                                       "1000*elapsedTimeSeconds <= timeoutMs + grace")
    vt = to[(to.timeoutMs + GRACE - 1000.0 * to.elapsed) < 0]
    # for each violating call: largest tick gap before the violating tick (sleep / suspended-timer signature)
    gmax = tk.groupby(["session_id", "call_id"]).d_t.max().rename("max_tick_gap_ms").reset_index()
    vt = vt.merge(gmax, on=["session_id", "call_id"], how="left")
    out["elapsed_vs_timeoutMs"]["violator_examples"] = examples(vt.assign(over=lambda d: 1000 * d.elapsed - d.timeoutMs),
                                                                ["session_id", "call_id", "tool_raw", "elapsed", "timeoutMs", "over", "max_tick_gap_ms"], sort_col="over")
    out["elapsed_vs_timeoutMs"]["violator_calls"] = int(vt.groupby(["session_id", "call_id"]).ngroups)
    # calls whose last elapsed exceeds timeout: did a tick gap cover the overrun?
    lastc = bp_all.groupby(["session_id", "call_id"]).agg(last_e=("elapsed", "max"), tmo=("timeoutMs", "max")).reset_index().merge(gmax, on=["session_id", "call_id"], how="left")
    lastc = lastc[lastc.tmo.notna()]
    over = lastc[1000.0 * lastc.last_e > lastc.tmo.astype(float) + GRACE]
    out["calls_over_timeout"] = {"n_calls_with_timeoutMs": int(len(lastc)), "over": int(len(over)),
                                 "over_with_tick_gap_ge_overrun": int((over.max_tick_gap_ms >= (1000.0 * over.last_e - over.tmo.astype(float))).sum())}
    out["timeoutMs_value_counts_top"] = dict(list(counts(to.timeoutMs.astype(int)).items())[:12])
    # args.timeout vs progress timeoutMs (two records of the same setting)
    a = args.copy()
    a["arg_timeout"] = [o.get("timeout") if isinstance(o.get("timeout"), (int, float)) else None for o in a.a]
    a["bg"] = [bool(o.get("run_in_background")) for o in a.a]
    pc = to.groupby(["session_id", "call_id"]).timeoutMs.agg(["min", "max"]).reset_index().merge(
        a[["session_id", "call_id", "arg_timeout", "bg"]], on=["session_id", "call_id"], how="left")
    out["timeoutMs_constant_within_call"] = {"k": int((pc["min"] == pc["max"]).sum()), "n": int(len(pc))}
    w = pc[pc.arg_timeout.notna()]
    out["args_timeout_eq_progress_timeoutMs"] = {"k": int((w.arg_timeout.astype(float) == w["min"]).sum()), "n": int(len(w)),
                                                 "progress_gt_arg": int((w["min"] > w.arg_timeout.astype(float)).sum()),
                                                 "progress_lt_arg": int((w["min"] < w.arg_timeout.astype(float)).sum()),
                                                 "mismatch_pairs_top": dict(list(Counter(
                                                     f"{int(x)}->{int(y)}" for x, y in zip(w.arg_timeout, w["min"]) if float(x) != y).most_common(10)))}
    wn = pc[pc.arg_timeout.isna()]
    out["progress_timeoutMs_when_args_has_no_timeout_top"] = dict(list(counts(wn["min"].astype(int)).items())[:8])
    out["run_in_background_calls_with_progress"] = int(pc.bg.fillna(False).sum())
    return out, bp


def sec_cc_mcp_progress(ev):
    calls, _ = cc_calls(ev)
    res, _ = cc_results(ev)
    meta = ev[(ev.kind == "meta") & ev.extra.str.contains('"mcp_progress"', na=False)]
    rows = [(sid, seq, t, pc, jl(x)) for sid, seq, t, pc, x in zip(meta.session_id, meta.seq, meta.t, meta.parent_call_id, meta.extra)]
    mp = pd.DataFrame([(a, b, c, d, o.get("status"), o.get("elapsedTimeMs"), o.get("serverName")) for a, b, c, d, o in rows],
                      columns=["session_id", "seq", "t", "call_id", "status", "elapsed_ms", "server"])
    out = {"n_events": int(len(mp)), "status_counts": counts(mp.status.fillna("<none>")),
           "elapsed_present_by_status": {str(k): int(g.elapsed_ms.notna().sum()) for k, g in mp.groupby(mp.status.fillna("<none>"))}}
    st = mp[mp.status == "started"].drop_duplicates(["session_id", "call_id"]).rename(columns={"t": "t_start"})
    en = mp[mp.status.isin(["completed", "failed"]) & mp.elapsed_ms.notna()].drop_duplicates(["session_id", "call_id"])
    j = en.merge(st[["session_id", "call_id", "t_start"]], on=["session_id", "call_id"], how="left") \
          .merge(calls[["session_id", "call_id", "t_call"]], on=["session_id", "call_id"], how="left") \
          .merge(res[["session_id", "call_id", "t_res"]], on=["session_id", "call_id"], how="left")
    j["elapsed_ms"] = j.elapsed_ms.astype(float)
    out["end_events_with_start"] = int(j.t_start.notna().sum())
    out["end_events_with_call"] = int(j.t_call.notna().sum())
    a = j[j.t_start.notna()]
    out["end_minus_start_ge_elapsed"] = ineq(a.session_id.values, (a.t - a.t_start - a.elapsed_ms).values, TOL,
                                             "end_progress.ts - start_progress.ts >= elapsedTimeMs")
    out["end_minus_start_minus_elapsed_exact_0"] = int(((a.t - a.t_start - a.elapsed_ms).round(3) == 0).sum())
    b = j[j.t_call.notna()]
    out["end_minus_call_ge_elapsed"] = ineq(b.session_id.values, (b.t - b.t_call - b.elapsed_ms).values, TOL,
                                            "end_progress.ts - call.ts >= elapsedTimeMs")
    s2 = st.merge(calls[["session_id", "call_id", "t_call"]], on=["session_id", "call_id"], how="inner")
    out["start_after_call"] = ineq(s2.session_id.values, (s2.t_start - s2.t_call).values, TOL, "start_progress.ts >= call.ts")
    c = j[j.t_res.notna()]
    out["result_after_end"] = ineq(c.session_id.values, (c.t_res - c.t).values, TOL, "result.ts >= end_progress.ts")
    out["elapsed_quantization"] = quant_int_ms(j.elapsed_ms.values)
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Section 3: Claude Code turn_duration durationMs vs human-prompt -> turn_duration span (swechat)
# ---------------------------------------------------------------------------------------------------------------------
def sec_cc_turn_duration(ev):
    main = ev[~ev.is_subagent].sort_values(["session_id", "seq"])
    td_mask = (main.kind == "meta") & main.extra.str.contains('"turn_duration"', na=False)
    rows = []
    for sid, g in main.groupby("session_id", sort=False):
        kinds, ts, ex, seqs = g.kind.values, g.t.values, g.extra.values, g.seq.values
        is_td = td_mask.loc[g.index].values
        last_user, first_user_since_td, prev_td_t, prev_td_seen = np.nan, np.nan, np.nan, False
        for k, t, x, td, sq in zip(kinds, ts, ex, is_td, seqs):
            if k == "user":
                last_user = t
                if np.isnan(first_user_since_td):
                    first_user_since_td = t
            if td:
                d = jl(x).get("durationMs")
                rows.append((sid, sq, t, float(d) if isinstance(d, (int, float)) else np.nan, last_user, first_user_since_td,
                             prev_td_t))
                prev_td_t, first_user_since_td = t, np.nan
    df = pd.DataFrame(rows, columns=["session_id", "seq", "t_td", "dur", "t_last_user", "t_first_user", "t_prev_td"])
    out = {"n_turn_duration": int(len(df)), "n_sessions": int(df.session_id.nunique()),
           "dur_missing": int(df.dur.isna().sum()), "no_user_before": int(df.t_last_user.isna().sum()),
           "no_user_since_previous_turn_duration": int(df.t_first_user.isna().sum()),
           "dur_quantization": quant_int_ms(df.dur.values)}
    for name, col in (("last_user_before", "t_last_user"), ("first_user_since_prev_td", "t_first_user")):
        d = df[df[col].notna() & df.dur.notna()]
        span = d.t_td - d[col]
        resid = span - d.dur
        blk = ineq(d.session_id.values, resid.values, TOL, f"turn_duration.ts - {name}.ts >= durationMs")
        blk["abs_resid_le_1000"] = crate(d.session_id.values, (resid.abs() <= 1000.0).values)
        blk["abs_resid_le_100"] = crate(d.session_id.values, (resid.abs() <= 100.0).values)
        blk["resid_exact_0"] = int((resid.round(3) == 0).sum())
        blk["resid_bins"] = {"lt_-60s": int((resid < -60000).sum()), "-60s..-1s": int(((resid >= -60000) & (resid < -1000)).sum()),
                             "-1s..-2ms": int(((resid >= -1000) & (resid < -TOL)).sum()), "-2..+2ms": int(((resid >= -TOL) & (resid <= TOL)).sum()),
                             "2ms..1s": int(((resid > TOL) & (resid <= 1000)).sum()), "1s..60s": int(((resid > 1000) & (resid <= 60000)).sum()),
                             "gt_60s": int((resid > 60000).sum())}
        blk["violator_examples"] = examples(d.assign(resid=resid.values, span=span.values)[resid.values < -TOL],
                                            ["session_id", "seq", "dur", "span", "resid"], sort_col="resid")
        out[name] = blk
    # previous-turn_duration based span (turn start = previous turn end): an upper bound for any turn start
    d = df[df.t_prev_td.notna() & df.dur.notna()]
    out["prev_turn_duration_to_this"] = ineq(d.session_id.values, (d.t_td - d.t_prev_td - d.dur).values, TOL,
                                             "turn_duration.ts - previous turn_duration.ts >= durationMs")
    # POST-HOC (added after run 1): residual (last-user variant) split by the main-thread tool calls inside the turn
    calls = main[main.kind == "call"][["session_id", "call_id", "t", "tool_raw"]]
    res = main[main.kind == "result"][["session_id", "call_id", "t"]].rename(columns={"t": "tr"})
    cr = calls.merge(res, on=["session_id", "call_id"])
    cr["gap"] = cr.tr - cr.t
    crg = {s: g for s, g in cr.groupby("session_id")}
    d = df[df.t_last_user.notna() & df.dur.notna()].copy()
    agg = []
    for r in d.itertuples():
        g = crg.get(r.session_id)
        if g is None:
            agg.append((0, 0.0))
            continue
        m = g[(g.t >= r.t_last_user) & (g.t <= r.t_td)]
        agg.append((len(m), float(m.gap.sum())))
    d[["ncalls", "sumgap"]] = agg
    d["resid"] = d.t_td - d.t_last_user - d.dur
    z, nz = d[d.ncalls == 0], d[d.ncalls > 0]
    out["POSTHOC_resid_by_calls_in_turn"] = {
        "no_calls": {"n": int(len(z)), "resid_ms_describe": stats.describe(z.resid.values),
                     "median_ci": cq(z.resid.values, z.session_id.values, 0.5) if len(z) else None},
        "with_calls": {"n": int(len(nz)), "resid_ms_describe": stats.describe(nz.resid.values),
                       "median_ci": cq(nz.resid.values, nz.session_id.values, 0.5)},
        "spearman_resid_vs_sum_call_gaps": clustered_spearman(nz.resid.values, nz.sumgap.values, nz.session_id.values)}
    return out


def clustered_spearman(x, y, sid, n_boot=200):
    """Spearman with a session-clustered bootstrap 95% CI (200 resamples to bound runtime)."""
    x, y, sid = np.asarray(x, float), np.asarray(y, float), np.asarray(sid)
    ok = ~(np.isnan(x) | np.isnan(y))
    x, y, sid = x[ok], y[ok], sid[ok]
    if len(x) < 3:
        return {"r": None, "n": int(len(x))}
    r0 = float(pd.Series(x).corr(pd.Series(y), method="spearman"))
    uniq, inv = np.unique(sid, return_inverse=True)
    groups = [np.where(inv == i)[0] for i in range(len(uniq))]
    rng = np.random.default_rng(stats.SEED)
    bs = []
    for _ in range(n_boot):
        idx = np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))])
        bs.append(pd.Series(x[idx]).corr(pd.Series(y[idx]), method="spearman"))
    return {"r": r0, "lo": float(np.nanquantile(bs, 0.025)), "hi": float(np.nanquantile(bs, 0.975)), "n": int(len(x)),
            "n_sessions": int(len(uniq)), "n_boot": n_boot}


# ---------------------------------------------------------------------------------------------------------------------
# Section 4: Task/Agent totalDurationMs and nested-event containment (swechat); subagent containment (cc_local, aggregates)
# ---------------------------------------------------------------------------------------------------------------------
def sec_cc_subagent_containment(corpus, ev, private=False):
    calls, _ = cc_calls(ev)
    res, _ = cc_results(ev)
    parents = calls[calls.tool_raw.isin(["Task", "Agent", "Workflow"])]
    nest = ev[ev.is_subagent & ev.parent_call_id.notna() & ev.t.notna()]
    agg = nest.groupby(["session_id", "parent_call_id"]).t.agg(["min", "max", "count"]).reset_index() \
              .rename(columns={"parent_call_id": "call_id", "min": "t_first", "max": "t_last", "count": "n_nested"})
    j = parents.merge(agg, on=["session_id", "call_id"], how="inner").merge(res[["session_id", "call_id", "t_res", "extra"]],
                                                                             on=["session_id", "call_id"], how="left")
    j["total"] = [jl(x).get("totalDurationMs") if isinstance(x, str) else None for x in j.extra]
    j["total"] = pd.to_numeric(j.total, errors="coerce")
    out = {"parent_calls": int(len(parents)), "parents_with_nested_events": int(len(j)),
           "parents_with_nested_by_tool": counts(j.tool_raw), "parents_with_result": int(j.t_res.notna().sum()),
           "parents_with_totalDurationMs": int(j.total.notna().sum())}
    out["first_nested_after_call"] = ineq(j.session_id.values, (j.t_first - j.t_call).values, TOL, "first nested event.ts >= parent call.ts")
    r = j[j.t_res.notna()]
    out["last_nested_before_result"] = ineq(r.session_id.values, (r.t_res - r.t_last).values, TOL, "parent result.ts >= last nested event.ts")
    out["last_nested_before_result"]["by_tool"] = {str(k): {"n": int(len(g)), "violations_tol": int(((g.t_res - g.t_last) < -TOL).sum())}
                                                   for k, g in r.groupby("tool_raw")}
    t = r[r.total.notna()]
    out["nested_span_le_totalDurationMs"] = ineq(t.session_id.values, (t.total - (t.t_last - t.t_first)).values, TOL,
                                                 "totalDurationMs >= last nested.ts - first nested.ts")
    out["gap_ge_totalDurationMs"] = ineq(t.session_id.values, ((t.t_res - t.t_call) - t.total).values, TOL,
                                         "parent result.ts - call.ts >= totalDurationMs")
    out["gap_minus_total_ms_describe"] = stats.describe(((t.t_res - t.t_call) - t.total).values)
    out["first_nested_minus_call_ms_describe"] = stats.describe((j.t_first - j.t_call).values)
    # POST-HOC (added after run 1): is totalDurationMs = result.ts - first nested event.ts?
    idr = (t.t_res - t.t_first) - t.total
    out["POSTHOC_total_vs_result_minus_first_nested"] = {"n": int(len(t)), "resid_ms_describe": stats.describe(idr.values),
                                                         "abs_resid_le_2": int((idr.abs() <= 2).sum()), "abs_resid_le_100": int((idr.abs() <= 100).sum()),
                                                         "abs_resid_le_1000": int((idr.abs() <= 1000).sum())}
    # result before the subagent finished: async launch signature (result arrives shortly after call, nested continues)
    rr = r.assign(res_before_first=(r.t_res < r.t_first), gap=(r.t_res - r.t_call), after=(r.t_res - r.t_last))
    out["result_before_last_nested"] = {"n": int((rr.after < -TOL).sum()), "of_which_result_before_first_nested": int((rr.res_before_first & (rr.after < -TOL)).sum()),
                                        "gap_ms_describe_when_violating": stats.describe(rr[rr.after < -TOL].gap.values)}
    if not private:
        v = r[(r.t_res - r.t_last) < -TOL]
        out["last_nested_before_result"]["violator_examples"] = examples(
            v.assign(after=lambda d: d.t_res - d.t_last, gap=lambda d: d.t_res - d.t_call),
            ["session_id", "call_id", "tool_raw", "n_nested", "gap", "after", "total"], sort_col="after")
        v = j[(j.t_first - j.t_call) < -TOL]
        out["first_nested_after_call"]["violator_examples"] = examples(v.assign(before=lambda d: d.t_first - d.t_call),
                                                                       ["session_id", "call_id", "tool_raw", "n_nested", "before"], sort_col="before")
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Section 5: Bash timeout settings vs observed gaps (all CC corpora; descriptive) and cc_local timedOutAfterMs
# ---------------------------------------------------------------------------------------------------------------------
def sec_cc_bash_timeouts(corpus, ev, args, private=False):
    calls, _ = cc_calls(ev)
    res, _ = cc_results(ev)
    a = args.copy()
    a["arg_timeout"] = [o.get("timeout") if isinstance(o.get("timeout"), (int, float)) and not isinstance(o.get("timeout"), bool) else None for o in a.a]
    a["bg"] = [bool(o.get("run_in_background")) for o in a.a]
    j = calls[calls.tool_raw == "Bash"].merge(a[["session_id", "call_id", "arg_timeout", "bg"]], on=["session_id", "call_id"], how="left") \
        .merge(res[["session_id", "call_id", "t_res", "extra"]], on=["session_id", "call_id"], how="inner")
    j["gap"] = j.t_res - j.t_call
    ex = [jl(x) for x in j.extra]
    j["timed_out_after"] = [o.get("timedOutAfterMs") for o in ex]
    j["interrupted"] = [bool(o.get("interrupted")) for o in ex]
    j["background_task"] = [o.get("backgroundTaskId") is not None for o in ex]
    out = {"bash_pairs": int(len(j)), "with_arg_timeout": int(j.arg_timeout.notna().sum()), "run_in_background": int(j.bg.fillna(False).sum()),
           "result_has_backgroundTaskId": int(j.background_task.sum()), "interrupted": int(j.interrupted.sum()),
           "with_timedOutAfterMs": int(pd.notna(j.timed_out_after).sum())}
    fg = j[(~j.bg.fillna(False)) & (~j.background_task) & j.arg_timeout.notna()]
    over = fg.gap - fg.arg_timeout.astype(float)
    out["foreground_gap_minus_arg_timeout_ms_describe"] = stats.describe(over.values)
    out["foreground_gap_over_arg_timeout_plus_5s"] = {"k": int((over > PREREG["gap_over_timeout_report_ms"]["value"]).sum()), "n": int(len(fg)),
                                                      "rate": crate(fg.session_id.values, (over > PREREG["gap_over_timeout_report_ms"]["value"]).values)}
    t = j[pd.notna(j.timed_out_after)].copy()
    if len(t):
        t["tmo"] = t.timed_out_after.astype(float)
        out["timedOutAfterMs"] = ineq(t.session_id.values, (t.gap - t.tmo).values, TOL, "result.ts - call.ts >= timedOutAfterMs")
        tt = t[t.arg_timeout.notna()]
        out["timedOutAfterMs"]["eq_arg_timeout"] = {"k": int((tt.arg_timeout.astype(float) == tt.tmo).sum()), "n": int(len(tt)),
                                                    "pairs_arg_to_timedOut": dict(Counter(f"{int(a)}->{int(b)}" for a, b in zip(tt.arg_timeout, tt.tmo)).most_common())}
        out["timedOutAfterMs"]["arg_timeout_absent"] = int(t.arg_timeout.isna().sum())
        out["timedOutAfterMs"]["value_counts"] = dict(list(counts(t.tmo.astype(int)).items())[:10])
        out["timedOutAfterMs"]["result_has_backgroundTaskId"] = int(t.background_task.sum())
        out["timedOutAfterMs"]["gap_minus_timeout_ms_describe"] = stats.describe((t.gap - t.tmo).values)
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Section 6: raw Claude Code fields (swechat B): api_error retry timers, hook timers, versions
# ---------------------------------------------------------------------------------------------------------------------
def _scan_cc_file(sid):
    path = os.path.join(SWE_TX, f"{sid}.jsonl")
    out = {"sid": sid, "versions": Counter(), "api_errors": [], "stop_summaries": [], "hook_prog": [], "hook_att": [],
           "children": {}, "bad": 0, "lines": 0}
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        out["missing"] = True
        return out
    api_uuids = set()
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        out["lines"] += 1
        i = ln.rfind('"version": "')
        if i >= 0:
            j2 = ln.find('"', i + 12)
            out["versions"][ln[i + 12:j2]] += 1
        if "api_error" in ln or "stop_hook_summary" in ln or "hook_progress" in ln or ('"attachment"' in ln and "durationMs" in ln):
            try:
                e = json.loads(ln)
            except Exception:
                out["bad"] += 1
                continue
            t, st = e.get("type"), e.get("subtype")
            if t == "system" and st == "api_error":
                out["api_errors"].append({"uuid": e.get("uuid"), "parent": e.get("parentUuid"), "ts": e.get("timestamp"),
                                          "retryInMs": e.get("retryInMs"), "attempt": e.get("retryAttempt"),
                                          "max": e.get("maxRetries"), "version": e.get("version"),
                                          "status": (e.get("error") or {}).get("status") if isinstance(e.get("error"), dict) else None})
                api_uuids.add(e.get("uuid"))
            elif t == "system" and st == "stop_hook_summary":
                hi = e.get("hookInfos") if isinstance(e.get("hookInfos"), list) else []
                out["stop_summaries"].append({"ts": e.get("timestamp"), "tuid": e.get("toolUseID"), "version": e.get("version"),
                                              "durs": [h.get("durationMs") for h in hi if isinstance(h, dict)],
                                              "hookCount": e.get("hookCount"),
                                              "n_errors": len(e.get("hookErrors") or []), "prevented": e.get("preventedContinuation")})
            elif t == "progress" and isinstance(e.get("data"), dict) and e["data"].get("type") == "hook_progress":
                d = e["data"]
                out["hook_prog"].append({"ts": e.get("timestamp"), "tuid": e.get("toolUseID"), "ptuid": e.get("parentToolUseID"),
                                         "event": d.get("hookEvent"), "name": d.get("hookName")})
            elif t == "attachment" and isinstance(e.get("attachment"), dict) and "durationMs" in e["attachment"]:
                a = e["attachment"]
                out["hook_att"].append({"ts": e.get("timestamp"), "tuid": a.get("toolUseID"), "event": a.get("hookEvent"),
                                        "name": a.get("hookName"), "type": a.get("type"), "durationMs": a.get("durationMs"),
                                        "version": e.get("version")})
    if api_uuids:
        for ln in lines:
            if ln.startswith('{"parentUuid": "'):
                p = ln[16:52]
                if p in api_uuids and p not in out["children"]:
                    try:
                        e = json.loads(ln)
                    except Exception:
                        continue
                    out["children"][p] = {"ts": e.get("timestamp"), "type": e.get("type"), "subtype": e.get("subtype"),
                                          "attempt": e.get("retryAttempt")}
    return out


def raw_cc_scan(sids):
    with ProcessPoolExecutor(max_workers=4) as ex:
        return list(ex.map(_scan_cc_file, sids, chunksize=8))


def sec_cc_raw(scan, ev):
    out = {"files": len(scan), "missing": sum(1 for s in scan if s.get("missing")), "lines": sum(s["lines"] for s in scan),
           "undecodable_selected_lines": sum(s["bad"] for s in scan)}
    # api_error retry
    rows = []
    for s in scan:
        for a in s["api_errors"]:
            ch = s["children"].get(a["uuid"])
            rows.append((s["sid"], a["ts"], a["retryInMs"], a["attempt"], a["max"], a["version"], a["status"],
                         ch["ts"] if ch else None, (ch or {}).get("type"), (ch or {}).get("subtype"), (ch or {}).get("attempt")))
    df = pd.DataFrame(rows, columns=["session_id", "ts", "retryInMs", "attempt", "max", "version", "status", "child_ts",
                                     "child_type", "child_subtype", "child_attempt"])
    blk = {"n_api_error": int(len(df)), "n_sessions": int(df.session_id.nunique()) if len(df) else 0}
    if len(df):
        df["t"] = to_ms(df.ts)
        df["tc"] = to_ms(df.child_ts)
        df["retryInMs"] = pd.to_numeric(df.retryInMs, errors="coerce")
        blk["retryInMs_present"] = int(df.retryInMs.notna().sum())
        blk["with_child"] = int(df.tc.notna().sum())
        blk["child_type_counts"] = counts((df.child_type.fillna("<none>") + "/" + df.child_subtype.fillna("")).values)
        d = df[df.retryInMs.notna() & df.tc.notna()]
        blk["child_after_retry_wait"] = ineq(d.session_id.values, (d.tc - d.t - d.retryInMs).values, TOL,
                                             "child.ts - api_error.ts >= retryInMs")
        dd = d[d.child_subtype == "api_error"]
        blk["child_is_next_api_error"] = ineq(dd.session_id.values, (dd.tc - dd.t - dd.retryInMs).values, TOL,
                                              "next api_error.ts - api_error.ts >= retryInMs")
        blk["child_is_next_api_error"]["attempt_plus_1"] = {"k": int((dd.child_attempt == dd.attempt + 1).sum()), "n": int(len(dd))}
        # POST-HOC (after run 1): children that are not the same retry loop's next attempt (another concurrent loop's
        # api_error, or a '[Request interrupted by user]' user entry) are not bound by this loop's wait
        da = dd[dd.child_attempt == dd.attempt + 1]
        blk["POSTHOC_child_is_same_loop_next_attempt"] = ineq(da.session_id.values, (da.tc - da.t - da.retryInMs).values, TOL,
                                                              "next attempt (attempt+1) api_error.ts - api_error.ts >= retryInMs")
        vv = d[(d.tc - d.t - d.retryInMs) < -TOL]
        blk["child_after_retry_wait"]["violators_child_kind"] = counts(
            ["api_error_not_attempt_plus_1" if (s == "api_error" and ca != a + 1) else ("api_error_attempt_plus_1" if s == "api_error" else str(ty))
             for s, ca, a, ty in zip(vv.child_subtype, vv.child_attempt, vv.attempt, vv.child_type)])
        # POST-HOC (after run 1): retryInMs vs attempt follows a capped exponential band base*2^(a-1)*[1, 1.25], cap 32 s
        d3 = df[df.retryInMs.notna() & pd.to_numeric(df.attempt, errors="coerce").notna()].copy()
        base = np.minimum(500.0 * 2.0 ** (d3.attempt.astype(float) - 1), 32000.0)
        inb = (d3.retryInMs >= base - 1e-6) & (d3.retryInMs <= 1.25 * base + 1e-6)
        blk["POSTHOC_retryInMs_in_band_500x2^(a-1)_cap32000_jitter_0_25"] = {"k": int(inb.sum()), "n": int(len(d3)),
                                                                             "rate": crate(d3.session_id.values, inb.values)}
        v = d[(d.tc - d.t - d.retryInMs) < -TOL]
        blk["child_after_retry_wait"]["violator_examples"] = examples(
            v.assign(slack=lambda x: x.tc - x.t - x.retryInMs), ["session_id", "attempt", "retryInMs", "slack", "child_type", "child_subtype", "version"], sort_col="slack")
        # backoff structure: retryInMs / 2^(attempt-1) (exponential-backoff base) per attempt
        d2 = df[df.retryInMs.notna() & pd.to_numeric(df.attempt, errors="coerce").notna()]
        blk["retryInMs_by_attempt"] = {str(int(k)): stats.describe(g.retryInMs.values) for k, g in d2.groupby(d2.attempt.astype(int)) if k <= 10}
        blk["retryInMs_quantization"] = {"decimals_as_written": decimals_of(df.retryInMs.dropna().tolist())}
        blk["status_counts"] = counts(df.status.fillna("<none>"))
    out["api_error_retry"] = blk
    # stop hooks: summary vs first Stop hook_progress (same toolUseID)
    hp = pd.DataFrame([(s["sid"], h["ts"], h["tuid"], h["ptuid"], h["event"], h["name"]) for s in scan for h in s["hook_prog"]],
                      columns=["session_id", "ts", "tuid", "ptuid", "event", "name"])
    hp["t"] = to_ms(hp.ts)
    out["hook_progress_n"] = int(len(hp))
    out["hook_progress_tuid_eq_parent"] = {"k": int((hp.tuid == hp.ptuid).sum()), "n": int(len(hp))}
    out["hook_progress_event_counts"] = counts(hp.event.fillna("<none>"))
    ss = pd.DataFrame([(s["sid"], x["ts"], x["tuid"], x["durs"], x["hookCount"], x["n_errors"], x["prevented"], x["version"])
                       for s in scan for x in s["stop_summaries"]],
                      columns=["session_id", "ts", "tuid", "durs", "hookCount", "n_errors", "prevented", "version"])
    blk = {"n_stop_hook_summary": int(len(ss)), "n_sessions": int(ss.session_id.nunique()) if len(ss) else 0}
    if len(ss):
        ss["t"] = to_ms(ss.ts)
        ss["nd"] = [len([d for d in x if isinstance(d, (int, float))]) for x in ss.durs]
        ss["dmax"] = [max([d for d in x if isinstance(d, (int, float))], default=np.nan) for x in ss.durs]
        ss["dsum"] = [sum([d for d in x if isinstance(d, (int, float))]) if any(isinstance(d, (int, float)) for d in x) else np.nan for x in ss.durs]
        blk["with_durations"] = int(ss.dmax.notna().sum())
        blk["hookCount_eq_len_hookInfos"] = {"k": int(sum(1 for c, d in zip(ss.hookCount, ss.durs) if c == len(d))), "n": int(len(ss))}
        hs = hp[hp.event == "Stop"].groupby(["session_id", "tuid"]).agg(t_hp=("t", "min"), n_hp=("t", "size"), t_hp_max=("t", "max")).reset_index()
        j = ss.merge(hs, on=["session_id", "tuid"], how="left")
        blk["with_matching_hook_progress"] = int(j.t_hp.notna().sum())
        blk["hook_progress_count_eq_hookCount"] = {"k": int((j.n_hp == j.hookCount).sum()), "n": int(j.t_hp.notna().sum())}
        d = j[j.t_hp.notna() & j.dmax.notna()]
        span = d.t - d.t_hp
        blk["span_ge_max_duration"] = ineq(d.session_id.values, (span - d.dmax).values, TOL,
                                           "summary.ts - first Stop hook_progress.ts >= max(hookInfos.durationMs)")
        blk["span_minus_max_exact_0_or_1"] = int(((span - d.dmax).round(3).isin([0.0, 1.0])).sum())
        blk["span_minus_max_abs_le_2"] = int(((span - d.dmax).abs() <= 2).sum())
        dm = d[d.nd >= 2]
        blk["multi_hook_span_ge_sum"] = ineq(dm.session_id.values, (dm.t - dm.t_hp - dm.dsum).values, TOL,
                                             "summary.ts - first hook_progress.ts >= sum(durationMs) [serial-execution probe]")
        blk["durations_quantization"] = quant_int_ms([x for l in ss.durs for x in l if isinstance(x, (int, float))])
        v = d[(span - d.dmax) < -TOL]
        blk["span_ge_max_duration"]["violator_examples"] = examples(
            v.assign(span=(v.t - v.t_hp), slack=(v.t - v.t_hp - v.dmax)), ["session_id", "tuid", "dmax", "span", "slack", "nd", "version"], sort_col="slack")
        blk["span_ge_max_duration"]["violators_by_version"] = counts(v.version.fillna("<none>"))
    out["stop_hooks"] = blk
    # hook attachments with durationMs (hook_success etc.) vs hook_progress of the same (toolUseID, event, name)
    ha = pd.DataFrame([(s["sid"], x["ts"], x["tuid"], x["event"], x["name"], x["type"], x["durationMs"], x["version"])
                       for s in scan for x in s["hook_att"]],
                      columns=["session_id", "ts", "tuid", "event", "name", "type", "dur", "version"])
    blk = {"n": int(len(ha)), "n_sessions": int(ha.session_id.nunique()) if len(ha) else 0}
    if len(ha):
        ha["t"] = to_ms(ha.ts)
        ha["dur"] = pd.to_numeric(ha.dur, errors="coerce")
        blk["type_counts"] = counts(ha.type.fillna("<none>"))
        blk["event_counts"] = counts(ha.event.fillna("<none>"))
        hpk = hp.groupby(["session_id", "tuid", "event", "name"]).t.min().reset_index().rename(columns={"t": "t_hp"})
        j = ha.merge(hpk, on=["session_id", "tuid", "event", "name"], how="left")
        blk["with_matching_hook_progress"] = int(j.t_hp.notna().sum())
        d = j[j.t_hp.notna() & j.dur.notna()]
        blk["attachment_minus_progress_ge_duration"] = ineq(d.session_id.values, (d.t - d.t_hp - d.dur).values, TOL,
                                                            "hook attachment.ts - hook_progress.ts >= attachment.durationMs")
        blk["attachment_minus_progress_ge_duration"]["by_event"] = {
            str(k): {"n": int(len(g)), "violations_tol": int(((g.t - g.t_hp - g.dur) < -TOL).sum())} for k, g in d.groupby("event")}
        v = d[(d.t - d.t_hp - d.dur) < -TOL]
        blk["attachment_minus_progress_ge_duration"]["violator_examples"] = examples(
            v.assign(slack=(v.t - v.t_hp - v.dur)), ["session_id", "event", "name", "type", "dur", "slack", "version"], sort_col="slack")
        blk["duration_quantization"] = quant_int_ms(ha.dur.values)
        # POST-HOC (after run 1: versions that write hook attachments write no hook_progress, so the join above is empty):
        # tool hooks run after the tool_use entry is written -> attachment.ts - call.ts >= durationMs
        calls, _ = cc_calls(ev)
        res, _ = cc_results(ev)
        jt = ha[ha.event.isin(["PreToolUse", "PostToolUse", "PostToolUseFailure"])].merge(
            calls[["session_id", "call_id", "t_call"]].rename(columns={"call_id": "tuid"}), on=["session_id", "tuid"], how="left") \
            .merge(res[["session_id", "call_id", "t_res"]].rename(columns={"call_id": "tuid"}), on=["session_id", "tuid"], how="left")
        blk["POSTHOC_tool_hook_with_call"] = int(jt.t_call.notna().sum())
        for evn, g in jt[jt.t_call.notna() & jt.dur.notna()].groupby("event"):
            b = ineq(g.session_id.values, (g.t - g.t_call - g.dur).values, TOL, f"{evn} hook attachment.ts - call.ts >= durationMs")
            gr = g[g.t_res.notna()]
            b["attachment_minus_result_ms_describe"] = stats.describe((gr.t - gr.t_res).values)
            b["attachment_before_result"] = {"k": int((gr.t < gr.t_res - TOL).sum()), "n": int(len(gr))}
            v = g[(g.t - g.t_call - g.dur) < -TOL]
            b["violator_examples"] = examples(v.assign(slack=(v.t - v.t_call - v.dur)), ["session_id", "tuid", "name", "dur", "slack", "version"], sort_col="slack")
            blk[f"POSTHOC_{evn}_vs_call"] = b
    out["hook_attachments"] = blk
    # hook_progress (hook start) vs the tool call / result it belongs to (parentToolUseID = tool_use id)
    calls, _ = cc_calls(ev)
    res, _ = cc_results(ev)
    hq = hp[hp.event.isin(["PreToolUse", "PostToolUse", "PostToolUseFailure"])].groupby(["session_id", "tuid", "event"]).t.min().reset_index() \
        .merge(calls[["session_id", "call_id", "t_call"]].rename(columns={"call_id": "tuid"}), on=["session_id", "tuid"], how="inner") \
        .merge(res[["session_id", "call_id", "t_res"]].rename(columns={"call_id": "tuid"}), on=["session_id", "tuid"], how="left")
    hb = {}
    for evn, g in hq.groupby("event"):
        b = {"n": int(len(g)), "start_after_call": ineq(g.session_id.values, (g.t - g.t_call).values, TOL, f"{evn} hook_progress.ts >= call.ts")}
        gr = g[g.t_res.notna()]
        b["result_minus_hook_start_ms_describe"] = stats.describe((gr.t_res - gr.t).values)
        b["result_before_hook_start"] = {"k": int((gr.t_res < gr.t - TOL).sum()), "n": int(len(gr))}
        hb[evn] = b
    out["tool_hook_progress_vs_call_result"] = hb
    # versions per session (for characterization)
    sv = {s["sid"]: (s["versions"].most_common(1)[0][0] if s["versions"] else None) for s in scan}
    out["sessions_by_modal_version_major_minor"] = counts([".".join(v.split(".")[:2]) if v else "<none>" for v in sv.values()])
    out["sessions_with_multiple_versions"] = int(sum(1 for s in scan if len(s["versions"]) > 1))
    return out, sv


# ---------------------------------------------------------------------------------------------------------------------
# Section 6b: cc_local cost-state ledger (raw; PRIVATE: aggregates only). cost-state lines carry no timestamp/uuid and are
# dropped by the loader; they are compared with the timestamps of the SAME main file. Only main files whose stem is a
# Phase-B session id (family root) are used; member files of a family are not attributed (counted).
# ---------------------------------------------------------------------------------------------------------------------
CCL_ROOT = os.path.join(os.environ.get("SWARMS_DATA", "C:/Swarms/data"), "claude-code-local")


def _ccl_cost_file(path):
    cs, tss, calls, results = [], [], {}, {}
    try:
        f = open(path, encoding="utf-8")
    except Exception:
        return None
    with f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                e = json.loads(ln)
            except Exception:
                continue
            if not isinstance(e, dict):
                continue
            if e.get("type") == "cost-state":
                cs.append({k: e.get(k) for k in ("totalAPIDuration", "totalAPIDurationWithoutRetries", "totalToolDuration",
                                                 "totalDuration", "startTime")})
                continue
            ts = e.get("timestamp")
            if not ts:
                continue
            tss.append(ts)
            msg = e.get("message") if isinstance(e.get("message"), dict) else {}
            cont = msg.get("content") if isinstance(msg.get("content"), list) else []
            for b in cont:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id") not in calls:
                    calls[b.get("id")] = ts
                elif isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") not in results:
                    results[b.get("tool_use_id")] = ts
    return {"cs": cs, "tss": tss, "pairs": [(calls[k], results[k]) for k in calls if k in results]}


def sec_ccl_cost_state():
    b = json.load(open(os.path.join(CACHE, "samples", "cc_local.json"), encoding="utf-8"))["B"]
    bset = set(b)
    paths = []
    for d in os.listdir(CCL_ROOT):
        pd_ = os.path.join(CCL_ROOT, d)
        if not os.path.isdir(pd_):
            continue
        for fn in os.listdir(pd_):
            if fn.endswith(".jsonl") and fn[:-6] in bset:
                paths.append((fn[:-6], os.path.join(pd_, fn)))
    rows = []
    n_files_cs = 0
    for sid, p in paths:
        r = _ccl_cost_file(p)
        if not r or not r["cs"]:
            continue
        n_files_cs += 1
        t = to_ms(r["tss"])
        t = t[~np.isnan(t)]
        pr = r["pairs"]
        tc, trr = to_ms([a for a, _ in pr]), to_ms([b_ for _, b_ in pr])
        for c in r["cs"]:
            st = c.get("startTime")
            if not isinstance(st, (int, float)):
                continue
            end = st + (c.get("totalDuration") or 0)
            inwin = (tc >= st - TOL) & (trr <= end + TOL)
            rows.append((sid, float(st), c.get("totalDuration"), c.get("totalAPIDuration"), c.get("totalAPIDurationWithoutRetries"),
                         c.get("totalToolDuration"), float(t.min()) if len(t) else np.nan, float(t.max()) if len(t) else np.nan,
                         float(np.nansum((trr - tc)[inwin])), int(inwin.sum()),
                         float(t[(t >= st - TOL)].min()) if (t >= st - TOL).any() else np.nan,
                         float(t[(t <= end + TOL)].max()) if (t <= end + TOL).any() else np.nan))
    df = pd.DataFrame(rows, columns=["session_id", "start", "total", "api", "api_nr", "tool", "f_first", "f_last", "sum_tool_gaps",
                                     "n_tool_pairs", "first_after_start", "last_before_end"])
    for c in ("total", "api", "api_nr", "tool"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    out = {"b_root_files_found": len(paths), "b_root_files_with_cost_state": n_files_cs, "cost_state_records": int(len(df)),
           "note": "aggregates only (private corpus)"}
    if not len(df):
        return out
    out["api_ge_api_without_retries"] = ineq(df.session_id.values, (df.api - df.api_nr).values, 0.0, "totalAPIDuration >= totalAPIDurationWithoutRetries", with_ci=False)
    out["startTime_vs_file_first_event"] = {"start_le_first_event": int((df.start <= df.f_first + TOL).sum()), "n": int(len(df)),
                                            "first_event_minus_start_ms_describe": stats.describe((df.f_first - df.start).values)}
    out["end_vs_file_last_event"] = ineq(df.session_id.values, (df.start + df.total - df.f_last).values, TOL,
                                         "startTime + totalDuration >= last event ts of the file", with_ci=False)
    out["end_minus_last_event_in_window_ms_describe"] = stats.describe((df.start + df.total - df.last_before_end).values)
    idle = (df.start + df.total - df.last_before_end)
    out["POSTHOC_end_minus_last_event_within_1s_of_900000ms"] = {"k": int(((idle - 900000.0).abs() <= 1000.0).sum()), "n": int(len(df)),
                                                                 "rate": crate(df.session_id.values, ((idle - 900000.0).abs() <= 1000.0).values)}
    out["first_event_in_window_minus_start_ms_describe"] = stats.describe((df.first_after_start - df.start).values)
    out["tool_vs_sum_of_tool_gaps_in_window"] = {"n": int(len(df)), "ratio_describe": stats.describe((df.tool / df.sum_tool_gaps.replace(0, np.nan)).values),
                                                 "tool_le_sum_gaps": int((df.tool <= df.sum_tool_gaps + TOL).sum()),
                                                 "n_tool_pairs_describe": stats.describe(df.n_tool_pairs.values)}
    out["total_ge_api"] = {"k": int((df.total >= df.api).sum()), "n": int(len(df))}
    out["total_ge_tool"] = {"k": int((df.total >= df.tool).sum()), "n": int(len(df))}
    out["api_plus_tool_over_total_describe"] = stats.describe(((df.api + df.tool) / df.total.replace(0, np.nan)).values)
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Section 7: Codex (swechat B)
# ---------------------------------------------------------------------------------------------------------------------
def uuid7_ms(u):
    if not isinstance(u, str):
        return None
    h = u.replace("-", "")
    if len(h) != 32 or not re.fullmatch(r"[0-9a-fA-F]{32}", h) or h[12] != "7":
        return None
    return float(int(h[:12], 16))


def sec_codex():
    sids = set(swe_sessions("codex"))
    ev = load("swechat", ["session_id", "seq", "kind", "ts", "tool_raw", "call_id", "parent_call_id", "extra", "is_subagent"])
    ev = ev[ev.session_id.isin(sids)].reset_index(drop=True)
    ev["t"] = to_ms(ev.ts)
    out = {"n_sessions": int(ev.session_id.nunique()), "n_events": int(len(ev))}
    calls = ev[ev.kind == "call"].drop_duplicates(["session_id", "call_id"])[["session_id", "call_id", "t", "tool_raw"]].rename(columns={"t": "t_call"})
    args = load_call_args("swechat", ["exec_command", "shell_command", "shell", "write_stdin", "exec"])
    args = args[args.session_id.isin(sids)]
    calls = calls.merge(args, on=["session_id", "call_id"], how="left")
    calls["a"] = [x if isinstance(x, dict) else {} for x in calls.a]
    meta = ev[ev.kind == "meta"]
    mx = [jl(x) for x in meta.extra]
    meta = meta.assign(etype=[o.get("type") or o.get("entry_type") for o in mx], ex=mx)
    # C1 exec_command_end / mcp_tool_call_end: end.ts - call.ts >= duration
    for et in ("exec_command_end", "mcp_tool_call_end"):
        e = meta[meta.etype == et]
        e = e.assign(dur_s=[o.get("duration_s") for o in e.ex], status=[o.get("status") for o in e.ex],
                     has_call=[o.get("has_call") for o in e.ex])
        j = e.merge(calls[["session_id", "call_id", "t_call", "tool_raw", "a"]].rename(columns={"call_id": "parent_call_id", "tool_raw": "call_tool"}),
                    on="session_id parent_call_id".split(), how="left")
        j = j[j.t_call.notna() & j.dur_s.notna()].copy()
        j["dur_ms"] = j.dur_s.astype(float) * 1000.0
        j["slack"] = j.t - j.t_call - j.dur_ms
        blk = ineq(j.session_id.values, j.slack.values, TOL, f"{et}.ts - call.ts >= duration")
        blk["n_end_events"] = int(len(e))
        blk["end_without_call"] = int(len(e) - len(j))
        blk["by_status"] = {str(k): {"n": int(len(g)), "violations_tol": int((g.slack < -TOL).sum()),
                                     "violations_gross": int((g.slack < -GROSS).sum())} for k, g in j.groupby(j.status.fillna("<none>"))}
        blk["by_call_tool"] = {str(k): {"n": int(len(g)), "violations_tol": int((g.slack < -TOL).sum()),
                                        "violations_gross": int((g.slack < -GROSS).sum())} for k, g in j.groupby(j.call_tool.fillna("<none>"))}
        blk["duration_s_decimals"] = decimals_of(j.dur_s.tolist())
        blk["duration_zero"] = int((j.dur_ms == 0).sum())
        blk["violator_examples"] = examples(j[j.slack < -TOL], ["session_id", "parent_call_id", "call_tool", "status", "dur_ms", "slack"], sort_col="slack")
        if et == "exec_command_end":
            # timeout_ms (shell_command) vs duration
            j["timeout_ms"] = [o.get("timeout_ms") if isinstance(o.get("timeout_ms"), (int, float)) else None for o in j.a]
            tt = j[j.timeout_ms.notna()]
            blk["duration_le_timeout_ms"] = ineq(tt.session_id.values, (tt.timeout_ms.astype(float) + GRACE - tt.dur_ms).values, 0.0,
                                                 "duration <= args.timeout_ms + grace")
            blk["timeout_ms_value_counts"] = dict(list(counts(tt.timeout_ms.astype(int)).items())[:8])
        out[et] = blk
    # C2 results: function_call_output.ts - call.ts vs duration (non-deferred), and yield_time_ms for 'running' outputs
    res = ev[ev.kind == "result"]
    rx = [jl(x) for x in res.extra]
    res = res.assign(dur_s=[o.get("duration_s") for o in rx], running=[bool(o.get("unified_exec_running")) for o in rx],
                     deferred=[bool(o.get("exec_end_deferred")) for o in rx], end_call=[o.get("exec_end_call_id") for o in rx])
    j = res.merge(calls[["session_id", "call_id", "t_call", "a"]], on=["session_id", "call_id"], how="left")
    j = j[j.t_call.notna()].copy()
    j["gap"] = j.t - j.t_call
    nd = j[j.dur_s.notna() & ~j.deferred & j.end_call.isna()]
    out["result_gap_ge_duration_own_result"] = ineq(nd.session_id.values, (nd.gap - nd.dur_s.astype(float) * 1000.0).values, TOL,
                                                    "function_call_output.ts - call.ts >= exec duration")
    out["result_gap_ge_duration_own_result"]["by_tool"] = {
        str(k): {"n": int(len(g)), "violations_tol": int(((g.gap - g.dur_s.astype(float) * 1000) < -TOL).sum())} for k, g in nd.groupby("tool_raw")}
    j["yield"] = [o.get("yield_time_ms") if isinstance(o.get("yield_time_ms"), (int, float)) else None for o in j.a]
    rn = j[j.running & j["yield"].notna()]
    out["running_output_gap_ge_yield_time_ms"] = ineq(rn.session_id.values, (rn.gap - rn["yield"].astype(float)).values, TOL,
                                                      "output says 'running' => output.ts - call.ts >= yield_time_ms")
    out["running_output_gap_ge_yield_time_ms"]["by_tool"] = {
        str(k): {"n": int(len(g)), "violations_tol": int(((g.gap - g["yield"].astype(float)) < -TOL).sum())} for k, g in rn.groupby("tool_raw")}
    out["running_output_gap_minus_yield_ms_describe"] = stats.describe((rn.gap - rn["yield"].astype(float)).values)
    out["running_output_gap_ge_yield_time_ms"]["violator_yield_values"] = counts(rn[(rn.gap - rn["yield"].astype(float)) < -TOL]["yield"].astype(int))
    # POST-HOC (after run 1): the harness caps the effective yield at 30 s ("Wall time: 30.0x seconds" in every violator)
    eff = np.minimum(rn["yield"].astype(float), 30000.0)
    out["POSTHOC_running_output_gap_ge_min_yield_30s"] = ineq(rn.session_id.values, (rn.gap - eff).values, TOL,
                                                              "output says 'running' => output.ts - call.ts >= min(yield_time_ms, 30000)")
    # run 1 mixed write_stdin results that carry the whole process's deferred duration; restricted (post hoc) to
    # exec_command results that carry their own end
    ex_ = j[j.dur_s.notna() & j["yield"].notna() & ~j.running & ~j.deferred & j.end_call.isna() & (j.tool_raw == "exec_command")]
    out["exited_before_yield_duration_le_yield"] = ineq(ex_.session_id.values, (ex_["yield"].astype(float) + GRACE - ex_.dur_s.astype(float) * 1000).values, 0.0,
                                                        "exec_command output not 'running' (own end) => duration <= yield_time_ms + grace")
    # C2b third timer: 'Wall time: X seconds' header written by the harness into the model-visible output
    wt = load("swechat", ["session_id", "call_id", "text"], filters=[("kind", "=", "result"), ("tool_raw", "in", ["exec_command", "write_stdin"])])
    wt = wt[wt.session_id.isin(sids)].drop_duplicates(["session_id", "call_id"])
    rx_w = re.compile(r"^Wall time: ([0-9]+(?:\.[0-9]+)?) seconds", re.M)
    wt["wall_s"] = [float(m.group(1)) if isinstance(tx, str) and (m := rx_w.search(tx[:300])) else None for tx in wt.text]
    wt = wt.drop(columns=["text"]).merge(j[["session_id", "call_id", "gap", "dur_s", "running", "deferred", "end_call", "tool_raw"]],
                                         on=["session_id", "call_id"], how="inner")
    w = wt[wt.wall_s.notna()].copy()
    w["wall_ms"] = w.wall_s.astype(float) * 1000.0
    out["wall_time_header"] = {"outputs": int(len(wt)), "with_header": int(len(w)),
                               "gap_ge_wall_time": ineq(w.session_id.values, (w.gap - w.wall_ms).values, TOL, "output.ts - call.ts >= 'Wall time' header"),
                               "decimals_as_written": decimals_of(w.wall_s.tolist())}
    out["wall_time_header"]["gap_ge_wall_time"]["by_tool"] = {
        str(k): {"n": int(len(g)), "violations_tol": int(((g.gap - g.wall_ms) < -TOL).sum()),
                 "violations_gross": int(((g.gap - g.wall_ms) < -GROSS).sum())} for k, g in w.groupby("tool_raw")}
    ww = w[(w.tool_raw == "exec_command") & w.dur_s.notna() & w.end_call.isna() & ~w.running]
    dd_ = ww.wall_ms - ww.dur_s.astype(float) * 1000.0
    out["wall_time_header"]["exec_own_end_wall_minus_duration_ms"] = {"n": int(len(ww)), "describe": stats.describe(dd_.values),
                                                                      "abs_le_100": int((dd_.abs() <= 100).sum()), "abs_le_1000": int((dd_.abs() <= 1000).sum())}
    vw = w[(w.gap - w.wall_ms) < -TOL]
    out["wall_time_header"]["gap_ge_wall_time"]["violator_examples"] = examples(vw.assign(slack=vw.gap - vw.wall_ms),
                                                                                ["session_id", "call_id", "tool_raw", "wall_ms", "gap", "slack"], sort_col="slack")
    # C3 apply_patch custom tool output metadata.duration_seconds (text JSON)
    ap = load("swechat", ["session_id", "call_id", "ts", "text"], filters=[("kind", "=", "result"), ("tool_raw", "=", "apply_patch")])
    ap = ap[ap.session_id.isin(sids)].drop_duplicates(["session_id", "call_id"])
    durs = []
    for tx in ap.text:
        o = jl(tx)
        md = o.get("metadata") if isinstance(o.get("metadata"), dict) else {}
        durs.append(md.get("duration_seconds") if isinstance(md.get("duration_seconds"), (int, float)) else None)
    ap = ap.assign(dsec=durs, t=to_ms(ap.ts)).merge(calls[["session_id", "call_id", "t_call"]], on=["session_id", "call_id"], how="left")
    ap = ap[ap.dsec.notna() & ap.t_call.notna()]
    tolap = PREREG["apply_patch_duration_seconds_tol_ms"]["value"]
    out["apply_patch_metadata_duration"] = ineq(ap.session_id.values, (ap.t - ap.t_call - ap.dsec.astype(float) * 1000).values, tolap,
                                                "output.ts - call.ts >= metadata.duration_seconds")
    out["apply_patch_metadata_duration"]["decimals_as_written"] = decimals_of(ap.dsec.tolist())
    # C4 turn timers: task_started.started_at / task_complete.completed_at / duration_ms vs event ts; uuid7 turn ids
    ts_ = meta[meta.etype == "task_started"].assign(turn=lambda d: [o.get("turn_id") for o in d.ex],
                                                     started_at=lambda d: [o.get("started_at") for o in d.ex])
    tc = meta[meta.etype.isin(["task_complete", "turn_aborted"])].assign(turn=lambda d: [o.get("turn_id") for o in d.ex],
                                                                         completed_at=lambda d: [o.get("completed_at") for o in d.ex],
                                                                         duration_ms=lambda d: [o.get("duration_ms") for o in d.ex])
    s = ts_[ts_.started_at.notna()]
    r_s = s.t - s.started_at.astype(float) * 1000
    out["task_started_ts_vs_started_at"] = {
        "floor_consistent": ineq(s.session_id.values, r_s.values, TOL, "task_started.ts >= started_at (epoch s, floored)"),
        "within_1s": ineq(s.session_id.values, (1000.0 + TOL - r_s).values, 0.0, "task_started.ts - started_at*1000 < 1000"),
        "n_with_started_at": int(len(s)), "n_task_started": int(len(ts_))}
    # POST-HOC (after seeing 18 violators in 18 sessions): is the late-logged task_started the session's first turn?
    first_seq = ts_.groupby("session_id").seq.min().rename("first_seq")
    s2 = s.merge(first_seq, left_on="session_id", right_index=True)
    is_first = (s2.seq == s2.first_seq).values
    late = (r_s.values > 1000.0 + TOL)
    out["task_started_ts_vs_started_at"]["POSTHOC_late_by_first_turn"] = {
        "late_and_first": int((late & is_first).sum()), "late_not_first": int((late & ~is_first).sum()),
        "first_turns": int(is_first.sum()), "later_turns": int((~is_first).sum()),
        "event_lag_ms_describe_first_turns": stats.describe(r_s.values[is_first]),
        "event_lag_ms_describe_later_turns": stats.describe(r_s.values[~is_first])}
    c = tc[tc.completed_at.notna()]
    r_c = c.t - c.completed_at.astype(float) * 1000
    out["task_complete_ts_vs_completed_at"] = {
        "floor_consistent": ineq(c.session_id.values, r_c.values, TOL, "task_complete.ts >= completed_at (epoch s, floored)"),
        "within_1s": ineq(c.session_id.values, (1000.0 + TOL - r_c).values, 0.0, "task_complete.ts - completed_at*1000 < 1000"),
        "n_with_completed_at": int(len(c)), "n_end_events": int(len(tc)), "by_type": counts(c.etype)}
    jt = tc[tc.duration_ms.notna()].merge(ts_[["session_id", "turn", "t", "started_at"]].rename(columns={"t": "t_start"}),
                                          on=["session_id", "turn"], how="left")
    jt["duration_ms"] = jt.duration_ms.astype(float)
    a = jt[jt.t_start.notna()]
    out["turn_duration_ms_vs_event_span"] = ineq(a.session_id.values, ((a.t - a.t_start) - a.duration_ms).values, TOL,
                                                 "end.ts - task_started.ts >= duration_ms")
    out["turn_duration_ms_vs_event_span"]["abs_le_1000"] = int((((a.t - a.t_start) - a.duration_ms).abs() <= 1000).sum())
    # POST-HOC (after run 1): span from the started_at epoch second instead of the task_started event stamp
    a2 = jt[jt.started_at.notna()]
    r2 = (a2.t - a2.started_at.astype(float) * 1000.0) - a2.duration_ms
    out["POSTHOC_end_ts_minus_started_at_vs_duration_ms"] = {
        "floor_consistent": ineq(a2.session_id.values, (r2 + 1000.0).values, TOL, "end.ts - started_at*1000 >= duration_ms - 1000 (started_at floored)"),
        "resid_ms_describe": stats.describe(r2.values)}
    tl = a.merge(ts_[["session_id", "turn", "started_at"]].rename(columns={"started_at": "sa2"}), on=["session_id", "turn"], how="left")
    tl = tl[tl.sa2.notna()]
    out["POSTHOC_task_started_event_lag_vs_span_violation"] = {
        "n": int(len(tl)), "spearman_event_lag_vs_span_resid": clustered_spearman((tl.t_start - tl.sa2.astype(float) * 1000).values,
                                                                                   ((tl.t - tl.t_start) - tl.duration_ms).values, tl.session_id.values)}
    b = jt[jt.started_at.notna() & jt.completed_at.notna()]
    d_epoch = (b.completed_at.astype(float) - b.started_at.astype(float)) * 1000 - b.duration_ms
    out["turn_duration_ms_vs_epoch_seconds"] = {"n": int(len(b)), "abs_diff_le_1000_plus_tol": int((d_epoch.abs() <= 1000 + TOL).sum()),
                                                "diff_ms_describe": stats.describe(d_epoch.values)}
    # uuid7 clocks
    u = ts_.assign(um=[uuid7_ms(x) for x in ts_.turn])
    uu = u[u.um.notna()]
    out["uuid7_turn_id_vs_task_started_ts"] = {"n_turn_ids": int(len(u)), "n_uuid7": int(len(uu)),
                                               **ineq(uu.session_id.values, (uu.t - uu.um).values, TOL, "task_started.ts >= uuid7(turn_id) ms")}
    sm = meta[meta.etype == "session_meta"]
    smid = [(sid, t, uuid7_ms(o.get("id")), o.get("timestamp"), o.get("source")) for sid, t, o in zip(sm.session_id, sm.t, sm.ex)]
    smd = pd.DataFrame(smid, columns=["session_id", "t", "um", "pts", "source"])
    smd["tp"] = to_ms(smd.pts)
    sv = smd[smd.um.notna()]
    out["uuid7_session_id"] = {"n_session_meta": int(len(smd)), "n_uuid7": int(len(sv)),
                               "payload_timestamp_ge_uuid": ineq(sv.session_id.values, (sv.tp - sv.um).values, TOL, "session_meta.payload.timestamp >= uuid7(id) ms"),
                               "event_ts_ge_payload_timestamp": ineq(sv.session_id.values, (sv.t - sv.tp).values, TOL, "session_meta.ts >= payload.timestamp")}
    sp = meta[meta.etype == "collab_agent_spawn_end"]
    spd = pd.DataFrame([(sid, t, uuid7_ms(o.get("new_thread_id"))) for sid, t, o in zip(sp.session_id, sp.t, sp.ex)], columns=["session_id", "t", "um"])
    spd = spd[spd.um.notna()]
    out["uuid7_new_thread_id_vs_spawn_end_ts"] = ineq(spd.session_id.values, (spd.t - spd.um).values, TOL, "collab_agent_spawn_end.ts >= uuid7(new_thread_id) ms")
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Section 8: OpenCode raw (swechat B): message / part / tool clocks and id-embedded clocks
# ---------------------------------------------------------------------------------------------------------------------
M48, M36 = 2 ** 48, 2 ** 36


def oc_id_ms(i, ref_ms):
    """Decode an OpenCode ascending/descending id against a reference ms; returns decoded ms (unwrapped) or None."""
    if not isinstance(i, str) or "_" not in i or ref_ms is None:
        return None
    pre, rest = i.split("_", 1)
    h = rest[:12]
    if not re.fullmatch(r"[0-9a-f]{12}", h):
        return None
    v = int(h, 16)
    if pre == "ses":
        v = (~v) & (M48 - 1)
    low = (v // 0x1000) % M36
    k = round((ref_ms - low) / M36)
    return float(low + k * M36)


def _scan_oc_file(sid):
    path = os.path.join(SWE_TX, f"{sid}.jsonl")
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except Exception:
        return {"sid": sid, "failed": True}
    info = doc.get("info") if isinstance(doc.get("info"), dict) else {}
    it = info.get("time") if isinstance(info.get("time"), dict) else {}
    msgs = []
    for m in doc.get("messages") or []:
        if not isinstance(m, dict):
            continue
        mi = m.get("info") if isinstance(m.get("info"), dict) else {}
        mt = mi.get("time") if isinstance(mi.get("time"), dict) else {}
        parts = []
        for p in m.get("parts") or []:
            if not isinstance(p, dict):
                continue
            pt = p.get("time") if isinstance(p.get("time"), dict) else {}
            st = p.get("state") if isinstance(p.get("state"), dict) else {}
            stt = st.get("time") if isinstance(st.get("time"), dict) else {}
            inp = st.get("input") if isinstance(st.get("input"), dict) else {}
            md = st.get("metadata") if isinstance(st.get("metadata"), dict) else {}
            parts.append({"type": p.get("type"), "id": p.get("id"), "tool": p.get("tool"), "status": st.get("status"),
                          "p_start": pt.get("start"), "p_end": pt.get("end"), "s_start": stt.get("start"), "s_end": stt.get("end"),
                          "compacted": stt.get("compacted"), "timeout": inp.get("timeout") if isinstance(inp.get("timeout"), (int, float)) else None,
                          "exit": md.get("exit") if isinstance(md.get("exit"), int) else None})
        msgs.append({"id": mi.get("id"), "role": mi.get("role"), "created": mt.get("created"), "completed": mt.get("completed"),
                     "error": bool(mi.get("error")), "parent": mi.get("parentID"), "parts": parts})
    return {"sid": sid, "id": info.get("id"), "created": it.get("created"), "updated": it.get("updated"),
            "parentID": info.get("parentID"), "version": info.get("version"), "msgs": msgs}


def sec_opencode():
    sids = swe_sessions("opencode")
    with ProcessPoolExecutor(max_workers=4) as ex:
        docs = list(ex.map(_scan_oc_file, sids, chunksize=4))
    out = {"n_sessions": len(sids), "parse_failed": sum(1 for d in docs if d.get("failed"))}
    docs = [d for d in docs if not d.get("failed")]
    tools, parts, msgs = [], [], []
    sess = []
    for d in docs:
        sid = d["sid"]
        sess.append((sid, d["id"], d["created"], d["updated"], d["version"],
                     min([m["created"] for m in d["msgs"] if isinstance(m["created"], (int, float))], default=None),
                     max([m["completed"] or m["created"] for m in d["msgs"] if isinstance(m["created"], (int, float))], default=None)))
        prev_end = None
        for k, m in enumerate(d["msgs"]):
            msgs.append((sid, k, m["id"], m["role"], m["created"], m["completed"], m["error"], prev_end))
            if m["role"] == "assistant":
                prev_end = m["completed"] if m["completed"] is not None else prev_end
            for p in m["parts"]:
                if p["type"] == "tool":
                    tools.append((sid, k, m["role"], m["created"], m["completed"], p["id"], p["tool"], p["status"], p["s_start"],
                                  p["s_end"], p["compacted"], p["timeout"], p["exit"]))
                elif p["type"] in ("text", "reasoning"):
                    parts.append((sid, k, m["role"], m["created"], m["completed"], p["id"], p["type"], p["p_start"], p["p_end"]))
                else:
                    parts.append((sid, k, m["role"], m["created"], m["completed"], p["id"], p["type"], None, None))
    T = pd.DataFrame(tools, columns=["session_id", "k", "role", "m_created", "m_completed", "pid", "tool", "status", "start", "end",
                                     "compacted", "timeout", "exit"])
    P = pd.DataFrame(parts, columns=["session_id", "k", "role", "m_created", "m_completed", "pid", "ptype", "start", "end"])
    M = pd.DataFrame(msgs, columns=["session_id", "k", "mid", "role", "created", "completed", "error", "prev_asst_completed"])
    S = pd.DataFrame(sess, columns=["session_id", "sesid", "created", "updated", "version", "first_msg", "last_msg"])
    for df in (T, P, M, S):
        for c in df.columns:
            if c in ("m_created", "m_completed", "start", "end", "compacted", "created", "completed", "prev_asst_completed",
                     "updated", "first_msg", "last_msg", "timeout"):
                df[c] = pd.to_numeric(df[c], errors="coerce")
    out["n_tool_parts"] = int(len(T))
    out["tool_status_counts"] = counts(T.status.fillna("<none>"))
    t = T[T.start.notna() & T.end.notna()]
    out["tool_end_ge_start"] = ineq(t.session_id.values, (t.end - t.start).values, TOL, "state.time.end >= state.time.start")
    t = T[T.start.notna() & T.m_created.notna()]
    out["tool_start_ge_message_created"] = ineq(t.session_id.values, (t.start - t.m_created).values, TOL, "tool start >= message created")
    t = T[T.end.notna() & T.m_completed.notna()]
    out["tool_end_le_message_completed"] = ineq(t.session_id.values, (t.m_completed - t.end).values, TOL, "message completed >= tool end")
    out["tool_end_le_message_completed"]["by_tool"] = {str(k): {"n": int(len(g)), "violations_tol": int(((g.m_completed - g.end) < -TOL).sum()),
                                                               "violations_gross": int(((g.m_completed - g.end) < -GROSS).sum())}
                                                      for k, g in t.groupby(t.tool.fillna("<none>"))}
    out["tool_end_le_message_completed"]["violator_examples"] = examples(
        t.assign(slack=t.m_completed - t.end, dur=t.end - t.start)[(t.m_completed - t.end) < -TOL],
        ["session_id", "k", "tool", "status", "dur", "slack"], sort_col="slack")
    out["tool_parts_message_completed_missing"] = int((T.m_completed.isna() & T.end.notna()).sum())
    t = T[T.compacted.notna() & T.end.notna()]
    out["compacted_ge_end"] = ineq(t.session_id.values, (t.compacted - t.end).values, TOL, "state.time.compacted >= state.time.end")
    t = T[T.timeout.notna() & T.start.notna() & T.end.notna()]
    out["tool_duration_le_input_timeout"] = ineq(t.session_id.values, (t.timeout + GRACE - (t.end - t.start)).values, 0.0,
                                                 "end - start <= input.timeout + grace")
    out["tool_duration_le_input_timeout"]["by_tool"] = counts(t.tool.fillna("<none>"))
    vt = t[(t.timeout + GRACE - (t.end - t.start)) < 0]
    out["tool_duration_le_input_timeout"]["violator_examples"] = examples(
        vt.assign(dur=vt.end - vt.start, over=(vt.end - vt.start) - vt.timeout), ["session_id", "k", "tool", "status", "timeout", "dur", "over", "exit"], sort_col="over")
    for pt in ("text", "reasoning"):
        p = P[(P.ptype == pt) & P.start.notna()]
        blk = {"n_with_time": int(len(p)), "n_parts": int((P.ptype == pt).sum())}
        q = p[p.end.notna()]
        blk["end_ge_start"] = ineq(q.session_id.values, (q.end - q.start).values, TOL, f"{pt} end >= start")
        q = p[p.m_created.notna()]
        blk["start_ge_message_created"] = ineq(q.session_id.values, (q.start - q.m_created).values, TOL, f"{pt} start >= message created")
        q = p[p.end.notna() & p.m_completed.notna()]
        blk["end_le_message_completed"] = ineq(q.session_id.values, (q.m_completed - q.end).values, TOL, f"message completed >= {pt} end")
        out[f"{pt}_parts"] = blk
    m = M[M.created.notna() & M.completed.notna()]
    out["message_completed_ge_created"] = ineq(m.session_id.values, (m.completed - m.created).values, TOL, "message completed >= created")
    m = M[M.created.notna() & M.prev_asst_completed.notna()]
    out["message_created_ge_previous_assistant_completed"] = ineq(m.session_id.values, (m.created - m.prev_asst_completed).values, TOL,
                                                                  "message.created >= previous assistant message.completed")
    out["message_created_ge_previous_assistant_completed"]["by_role"] = {
        str(k): {"n": int(len(g)), "violations_tol": int(((g.created - g.prev_asst_completed) < -TOL).sum()),
                 "violations_gross": int(((g.created - g.prev_asst_completed) < -GROSS).sum())} for k, g in m.groupby("role")}
    out["message_completed_missing_by_role"] = {str(k): {"missing": int(g.completed.isna().sum()), "n": int(len(g))} for k, g in M.groupby("role")}
    out["message_error_flag"] = int(M.error.sum())
    s = S[S.created.notna() & S.first_msg.notna()]
    out["session_created_le_first_message"] = ineq(s.session_id.values, (s.first_msg - s.created).values, TOL, "first message created >= session created")
    s = S[S.updated.notna() & S.last_msg.notna()]
    out["session_updated_ge_last_message"] = ineq(s.session_id.values, (s.updated - s.last_msg).values, TOL, "session updated >= last message completed")
    out["session_updated_ge_last_message"]["updated_minus_first_message_ms_describe"] = stats.describe((s.updated - s.first_msg).values)
    m_ = M[M.created.notna()].sort_values(["session_id", "k"])
    mlast = m_.groupby("session_id").agg(last_created=("created", "max"))
    s2 = s.merge(mlast, left_on="session_id", right_index=True, how="left")
    out["session_updated_ge_last_message"]["updated_ge_last_message_created"] = {"k": int((s2.updated >= s2.last_created - TOL).sum()), "n": int(len(s2))}
    out["version_counts"] = counts(S.version.fillna("<none>"))
    # id-embedded clocks
    mm = M[M.created.notna()].copy()
    mm["dec"] = [oc_id_ms(i, c) for i, c in zip(mm.mid, mm.created)]
    mv = mm[mm.dec.notna()]
    out["message_id_clock"] = {"n_messages": int(len(M)), "n_decodable": int(len(mv)),
                               "redacted_or_other": counts(["REDACTED" if i == "REDACTED" else ("none" if not isinstance(i, str) else "undecodable")
                                                            for i, dd in zip(mm.mid, mm.dec) if dd is None]),
                               **ineq(mv.session_id.values, (mv.created - mv.dec).values, TOL, "message created >= id-embedded ms")}
    out["message_id_clock"]["abs_resid_le_2"] = int(((mv.created - mv.dec).abs() <= 2).sum())
    pp = pd.concat([T[["session_id", "pid", "start", "m_created", "role"]].rename(columns={"start": "ref"}).assign(kind="tool"),
                    P[["session_id", "pid", "start", "m_created", "ptype", "role"]].rename(columns={"start": "ref"}).assign(
                        kind=lambda d: d.ptype + "|" + d.role.fillna("<none>")).drop(columns=["ptype"])])
    pp["ref2"] = pp.ref.fillna(pp.m_created)
    pp = pp[pp.ref2.notna()].copy()
    pp["dec"] = [oc_id_ms(i, r) for i, r in zip(pp.pid, pp.ref2)]
    pv = pp[pp.dec.notna()]
    out["part_id_clock"] = {"n_parts": int(len(pp)), "n_decodable": int(len(pv))}
    for k, g in pv.groupby("kind"):
        gg = g[g.ref.notna()]
        blk = ineq(gg.session_id.values, (gg.ref - gg.dec).values, TOL, f"{k} part time.start >= part id ms") if len(gg) else {"n": 0}
        g2 = g.copy()
        blk["id_ms_minus_message_created"] = ineq(g2.session_id.values, (g2.dec - g2.m_created).values, TOL, "part id ms >= message created") if g2.m_created.notna().any() else {"n": 0}
        out["part_id_clock"][str(k)] = blk
    sx = S[S.created.notna()].copy()
    sx["dec"] = [oc_id_ms(i, c) for i, c in zip(sx.sesid, sx.created)]
    sxv = sx[sx.dec.notna()]
    out["session_id_clock"] = {"n": int(len(sx)), "n_decodable": int(len(sxv)),
                               **ineq(sxv.session_id.values, (sxv.created - sxv.dec).values, TOL, "session created >= id-embedded ms (descending id)")}
    out["session_id_clock"]["abs_resid_le_2"] = int(((sxv.created - sxv.dec).abs() <= 2).sum())
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Section 9: Gemini CLI (swechat B, IR): message timestamp (call) vs toolCall.timestamp (result)
# ---------------------------------------------------------------------------------------------------------------------
def sec_gemini_cli():
    sids = set(swe_sessions("gemini"))
    ev = load("swechat", ["session_id", "seq", "kind", "ts", "tool_raw", "call_id", "extra"], filters=[("kind", "in", ["call", "result"])])
    ev = ev[ev.session_id.isin(sids)]
    ev["t"] = to_ms(ev.ts)
    c = ev[ev.kind == "call"].drop_duplicates(["session_id", "call_id"])[["session_id", "call_id", "t"]].rename(columns={"t": "t_call"})
    r = ev[ev.kind == "result"].drop_duplicates(["session_id", "call_id"]).merge(c, on=["session_id", "call_id"], how="inner")
    blk = ineq(r.session_id.values, (r.t - r.t_call).values, TOL, "toolCall.timestamp >= message.timestamp")
    blk["by_status"] = {str(k): {"n": int(len(g)), "violations_tol": int(((g.t - g.t_call) < -TOL).sum())}
                        for k, g in r.groupby([jl(x).get("status") for x in r.extra])}
    blk["exact_equal"] = int(((r.t - r.t_call).round(3) == 0).sum())
    blk["n_sessions_total"] = len(sids)
    return {"call_result": blk}


# ---------------------------------------------------------------------------------------------------------------------
# Section 10: AI Village computer use (aiv_cu B): Gemini server-timing / HTTP date vs created_at; updated_at vs created_at
# ---------------------------------------------------------------------------------------------------------------------
def sec_aiv_cu():
    ev = load("aiv_cu", ["session_id", "seq", "kind", "ts", "extra", "uuid", "stratum", "model"])
    ev["t"] = to_ms(ev.ts)
    rows = ev.sort_values(["session_id", "seq"]).drop_duplicates(["session_id", "uuid"])[["session_id", "uuid", "seq", "t", "stratum"]]
    rows["t_prev"] = rows.groupby("session_id").t.shift(1)
    rows["row_idx"] = rows.groupby("session_id").cumcount()
    tm = ev[ev.extra.str.contains('"timing"', na=False)]
    tx = [jl(x).get("timing") or {} for x in tm.extra]
    tm = tm.assign(dur=[x.get("server_timing_dur_ms") for x in tx], hdate=[x.get("http_date") for x in tx])
    tm = tm[["session_id", "uuid", "kind", "t", "dur", "hdate", "stratum", "model"]].merge(rows[["session_id", "uuid", "t_prev", "row_idx"]],
                                                                                           on=["session_id", "uuid"], how="left")
    tm["th"] = to_ms(tm.hdate)
    tm["dur"] = pd.to_numeric(tm.dur, errors="coerce")
    out = {"n_timing_events": int(len(tm)), "n_sessions": int(tm.session_id.nunique()), "by_stratum": counts(tm.stratum),
           "dur_quantization": quant_int_ms(tm.dur.values), "first_row_of_session": int(tm.t_prev.isna().sum())}
    a = tm[tm.th.notna()]
    out["created_ge_http_date"] = ineq(a.session_id.values, (a.t - a.th).values, TOL_RI, "created_at >= http_date (floored s)")
    out["created_minus_http_date_ms_quantiles_by_stratum"] = {str(k): stats.describe((g.t - g.th).values) for k, g in a.groupby("stratum")}
    b = tm[tm.t_prev.notna() & tm.dur.notna()]
    out["gap_ge_server_dur"] = ineq(b.session_id.values, (b.t - b.t_prev - b.dur).values, TOL_RI,
                                    "created_at - previous row created_at >= server_timing dur")
    c = b[b.th.notna()]
    out["http_date_ceiling_minus_prev_ge_dur"] = ineq(c.session_id.values, (c.th + PREREG["http_date_resolution_ms"]["value"] - c.t_prev - c.dur).values,
                                                      TOL_RI, "(http_date + 1 s) - previous row created_at >= server_timing dur")
    v = c[(c.th + 1000.0 - c.t_prev - c.dur) < -TOL_RI]
    out["http_date_ceiling_minus_prev_ge_dur"]["violator_examples"] = examples(
        v.assign(slack=(v.th + 1000.0 - v.t_prev - v.dur), gap=(v.t - v.t_prev)), ["session_id", "row_idx", "dur", "gap", "slack", "stratum"], sort_col="slack")
    out["http_date_ceiling_minus_prev_ge_dur"]["violator_gap_minus_dur_describe"] = stats.describe((v.t - v.t_prev - v.dur).values)
    out["prev_row_to_http_date_ms_describe"] = stats.describe((c.th - c.t_prev).values)
    w = b[(b.t - b.t_prev - b.dur) < -TOL_RI]
    out["gap_ge_server_dur"]["violator_examples"] = examples(w.assign(slack=(w.t - w.t_prev - w.dur), gap=(w.t - w.t_prev)),
                                                             ["session_id", "row_idx", "dur", "gap", "slack", "stratum"], sort_col="slack")
    out["gap_minus_dur_quantiles_ci"] = {f"p{int(q * 100)}": cq((b.t - b.t_prev - b.dur).values, b.session_id.values, q) for q in (0.05, 0.5, 0.95)}
    # updated_at vs created_at on result rows (B sample)
    rs = ev[ev.kind == "result"]
    ua = [jl(x).get("updated_at") for x in rs.extra]
    rs = rs.assign(tu=to_ms(ua))
    rs = rs[rs.tu.notna()]
    out["updated_ge_created"] = ineq(rs.session_id.values, (rs.tu - rs.t).values, 0.0, "updated_at >= created_at", with_ci=False)
    out["updated_minus_created_over_1s"] = {"k": int(((rs.tu - rs.t) > 1000).sum()), "n": int(len(rs))}
    out["updated_minus_created_us_counts_top"] = dict(list(counts(np.round((rs.tu - rs.t) * 1000).astype(int)).items())[:8])
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Section 10b: identical-timestamp blocks and zero / negative call->result gaps (Claude Code corpora). POST-HOC: added
# after run 1 showed a Glob pair with gap 0 inside a block of identically stamped entries (v1.0.x) and one negative pair.
# ---------------------------------------------------------------------------------------------------------------------
def sec_cc_ties(corpus, ev, versions=None, private=False):
    e = ev[ev.kind.isin(["call", "result", "assistant", "user"]) & ev.t.notna() & ~ev.is_subagent].sort_values(["session_id", "seq"])
    tv, sv = e.t.values, e.session_id.values
    same = (tv[1:] == tv[:-1]) & (sv[1:] == sv[:-1])
    runs, run_sid, cur = [], [], 1
    for i, x in enumerate(same):
        if x:
            cur += 1
        else:
            if cur > 1:
                runs.append(cur)
                run_sid.append(sv[i])
            cur = 1
    if cur > 1:
        runs.append(cur)
        run_sid.append(sv[-1])
    runs = np.array(runs)
    c = e[e.kind == "call"][["session_id", "call_id", "t", "tool_raw"]]
    r = e[e.kind == "result"][["session_id", "call_id", "t"]].rename(columns={"t": "tr"})
    m = c.merge(r, on=["session_id", "call_id"])
    m["gap"] = m.tr - m.t
    z = m[m.gap == 0]
    out = {"main_thread_events": int(len(e)), "tie_runs": int(len(runs)), "tie_runs_ge_5": int((runs >= 5).sum()),
           "tie_runs_ge_20": int((runs >= 20).sum()), "tie_run_max": int(runs.max()) if len(runs) else 0,
           "sessions_with_tie_run_ge_5": int(len(set(np.array(run_sid)[runs >= 5].tolist()))) if len(runs) else 0,
           "call_result_pairs": int(len(m)), "gap_exact_0": int(len(z)), "gap_exact_0_sessions": int(z.session_id.nunique()),
           "gap_exact_0_rate": crate(m.session_id.values, (m.gap == 0).values),
           "gap_negative": int((m.gap < 0).sum()), "gap_0_by_tool_top": dict(list(counts(z.tool_raw.fillna("<none>")).items())[:10])}
    if versions is not None:
        vmm = {k: (".".join(v.split(".")[:2]) if v else "<none>") for k, v in versions.items()}
        out["gap_0_pairs_by_session_major_minor"] = counts([vmm.get(x, "<none>") for x in z.session_id])
        big = set(np.array(run_sid)[runs >= 5].tolist()) if len(runs) else set()
        out["tie_run_ge_5_sessions_by_version"] = counts([versions.get(x) or "<none>" for x in big])
        allv = Counter(vmm.get(x, "<none>") for x in m.session_id)
        zv = Counter(vmm.get(x, "<none>") for x in z.session_id)
        out["gap_0_rate_by_major_minor"] = {k: {"k": int(zv.get(k, 0)), "n": int(n)} for k, n in allv.items()}
    if not private:
        out["gap_negative_examples"] = examples(m[m.gap < 0], ["session_id", "call_id", "tool_raw", "gap"], sort_col="gap")
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Section 11: timestamp resolution per corpus / format (fractional digits as written in the IR ts string)
# ---------------------------------------------------------------------------------------------------------------------
def sec_ts_resolution():
    out = {}
    for corpus in ("swechat", "cc_local", "aiv_cc", "aiv_cu"):
        d = load(corpus, ["session_id", "ts"])
        d = d[d.ts.notna()]
        if corpus == "swechat":
            d = d.merge(swe_format(), on="session_id", how="left")
            groups = d.groupby("format")
        else:
            groups = [(corpus, d)]
        for k, g in groups:
            fd = g.ts.str.extract(r"\.(\d+)")[0].str.len().fillna(0).astype(int)
            out[f"{corpus}|{k}"] = {"n": int(len(g)), "frac_digits": {str(a): int(b) for a, b in sorted(Counter(fd.tolist()).items())}}
    return out


def reuse_aiv_accounting():
    """Copy (not recompute) the aiv_accounting lens numbers this lens builds on, with their JSON paths."""
    p = os.path.join(ROOT, "analysis", "out", "phase_c", "aiv_accounting.json")
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        return {"missing": p}
    m1 = d.get("m1_durations", {})
    return {"source": "analysis/out/phase_c/aiv_accounting.json (all 314 runs, raw stream; not the B split)",
            "m1_durations.by_rule.attributable": m1.get("by_rule", {}).get("attributable"),
            "m1_durations.slack_ms.abs_duration_minus_span.describe": (m1.get("slack_ms", {}).get("abs_duration_minus_span") or {}).get("describe"),
            "m3_created_at.tool_reported_duration_vs_gap": {k: {"gap_ge_reported": v.get("gap_ge_reported"),
                                                                "slack_ms_min": (v.get("slack_ms_describe") or {}).get("min")}
                                                            for k, v in (d.get("m3_created_at", {}).get("tool_reported_duration_vs_gap") or {}).items()}}


# ---------------------------------------------------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------------------------------------------------
def run(sections):
    res = {}
    swe_cc = None
    if any(s in sections for s in ("cc_timers", "cc_progress", "cc_turn", "cc_subagent", "cc_raw", "cc_timeouts", "cc_ties")):
        swe_cc = load_cc("swechat")
    if "cc_timers" in sections:
        res["cc_result_timers"] = {}
        for corpus in ("swechat", "cc_local", "aiv_cc"):
            ev = swe_cc if corpus == "swechat" else load_cc(corpus)
            res["cc_result_timers"][corpus], _ = sec_cc_result_timers(corpus, ev, private=(corpus == "cc_local"))
            if corpus != "swechat":
                del ev
    if "cc_progress" in sections:
        args = load_call_args("swechat", ["Bash"])
        res["cc_bash_progress"], _ = sec_cc_bash_progress(swe_cc, args)
        res["cc_mcp_progress"] = sec_cc_mcp_progress(swe_cc)
    if "cc_turn" in sections:
        res["cc_turn_duration"] = sec_cc_turn_duration(swe_cc)
    if "cc_subagent" in sections:
        res["cc_subagent_containment"] = {"swechat": sec_cc_subagent_containment("swechat", swe_cc)}
        evl = load_cc("cc_local")
        res["cc_subagent_containment"]["cc_local"] = sec_cc_subagent_containment("cc_local", evl, private=True)
        del evl
    if "cc_timeouts" in sections:
        res["cc_bash_timeouts"] = {}
        for corpus in ("swechat", "cc_local", "aiv_cc"):
            ev = swe_cc if corpus == "swechat" else load_cc(corpus)
            a = load_call_args(corpus, ["Bash"])
            res["cc_bash_timeouts"][corpus] = sec_cc_bash_timeouts(corpus, ev, a, private=(corpus == "cc_local"))
    sv = None
    if "cc_raw" in sections:
        sids = sorted(swe_cc.session_id.unique())
        scan = raw_cc_scan(sids)
        res["cc_raw"], sv = sec_cc_raw(scan, swe_cc)
        del scan
    if "cc_ties" in sections:
        res["cc_identical_timestamps"] = {"swechat": sec_cc_ties("swechat", swe_cc, sv)}
        for corpus in ("cc_local", "aiv_cc"):
            evx = load_cc(corpus)
            res["cc_identical_timestamps"][corpus] = sec_cc_ties(corpus, evx, None, private=(corpus == "cc_local"))
            del evx
    if "ccl_cost" in sections:
        res["cc_local_cost_state"] = sec_ccl_cost_state()
    if "codex" in sections:
        res["codex"] = sec_codex()
    if "opencode" in sections:
        res["opencode"] = sec_opencode()
    if "gemini_cli" in sections:
        res["gemini_cli"] = sec_gemini_cli()
    if "aiv_cu" in sections:
        res["aiv_cu"] = sec_aiv_cu()
    if "ts_resolution" in sections:
        res["ts_resolution"] = sec_ts_resolution()
    if "reuse" in sections:
        res["aiv_cc_reused_from_aiv_accounting"] = reuse_aiv_accounting()
    return res


ALL = ["cc_timers", "cc_progress", "cc_turn", "cc_subagent", "cc_timeouts", "cc_raw", "cc_ties", "ccl_cost", "codex", "opencode", "gemini_cli", "aiv_cu", "ts_resolution", "reuse"]


def main():
    secs = sys.argv[1:] or ALL
    res = run(secs)
    if sys.argv[1:]:
        print(json.dumps(res, indent=1, default=str)[:200000])
        return
    out = {"probe": "phase_c_two_clocks", "split": "B", "prereg": PREREG, "post_hoc": POST_HOC, **res}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, default=str)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
