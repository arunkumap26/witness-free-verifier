"""Phase A1: timestamp granularity and semantics (the latency gate).

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_a_a1
Reads ONLY the Phase A caches analysis/cache/<corpus>_A.parquet (+ swechat_population.parquet for the per-session format).
Never opens *_B.parquet. Writes RAW COUNTS ONLY to analysis/out/phase_a/a1.json; interpretation is in
analysis/notes/phase_a_a1.md.

Pairing: calls and results are joined on (session_id, call_id); the FIRST call and the FIRST result (by seq) per key.
delta = ir.parse_ts(result.ts) - ir.parse_ts(call.ts), kept as an exact integer number of microseconds (delta_us) and
reported in seconds. All thresholds, tool classes and the kill-rule operationalisation are fixed in RULES below, before
any outcome was computed, and are copied verbatim into the JSON.

cc_local is PRIVATE: only aggregates leave this script. Its tool names are passed through PUBLIC_CC_TOOLS (Claude Code
built-ins); MCP tools collapse to 'mcp__*' (precedent: cc_local_build.json) and anything else to 'other_tool'.
Result text is read in memory for ir.error_marker() only; no text, command, path or id is written out.
"""
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from functools import reduce
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.lib import stats
from analysis.lib.ir import error_marker, iso, parse_ts

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "analysis" / "cache"
OUT = ROOT / "analysis" / "out" / "phase_a" / "a1.json"
CORPORA = ["swechat", "cc_local", "aiv_cc", "aiv_cu", "whowhen"]

RULES = {
    "data": "Phase A split only: analysis/cache/<corpus>_A.parquet. *_B.parquet never opened.",
    "pairing": "calls (kind=call) and results (kind=result) joined on (session_id, call_id); first call and first result "
               "by seq per key. Pairs where either stamp is missing are counted (pairs_missing_ts) and excluded from delta stats.",
    "delta": "delta_us = exact integer microseconds of ir.parse_ts(result.ts) - ir.parse_ts(call.ts); delta_s = delta_us/1e6.",
    "stamp_properties": {
        "fractional_digits": "ir.frac_digits semantics: number of digits after '.' in the ts string (0 when absent).",
        "whole_second_stamp": "fractional part absent or all zeros",
        "whole_ms_stamp": "fractional part padded right with zeros to 6 digits has digits 4-6 == '000'",
        "last_digit_native": "the digit at the group's native precision (max fractional digits seen in the group's paired "
                             "stamps, 3 or 6), after right-padding with zeros; chi2 vs uniform over 0-9 (lib.stats.chi2_uniform)",
    },
    "delta_properties": {"zero": "delta_us == 0 (identical parsed stamps)", "whole_second": "delta_us % 1_000_000 == 0 (zero included)",
                         "whole_ms": "delta_us % 1000 == 0 (zero included)", "negative": "delta_us < 0"},
    "kill_rule": {
        "source": "task brief, applied exactly: 'if the stamps are whole-second or shared between a call and its result, "
                  "latency analysis is dead for that corpus/format'",
        "units": "per corpus; for swechat per format (format from swechat_population.parquet)",
        "operationalisation": "KILLED if (a) no pair has both stamps (no timestamps), or (b) whole-second: more than 0.5 of the "
                              "paired stamps (call and result ts pooled) are whole-second stamps, or (c) shared: more than 0.5 "
                              "of pairs with both stamps have delta exactly 0 (identical stamp). Otherwise ALIVE.",
        "threshold_0.5_reason": "the rule is a property of a corpus/format's stamps; a majority is the plain reading. The raw "
                                "shares are reported so any other cut can be re-applied from the JSON.",
        "mixed_flag": "flag 'mixed' when either share is in (0.01, 0.5]: chance level for ms-precision stamps is 0.001 "
                      "(whole-second) and identical stamps should be rare; such a format is ALIVE by the rule but pairs "
                      "with identical/whole-second stamps must be dropped individually.",
        "not_part_of_rule": "semantic validity (row-insert vs event time, human waits) is reported separately and does not "
                            "change the verdict; it is discussed in the notes.",
    },
    "top_tools": "10 most common normalized tools (ir tool column) by number of pairs with both stamps, per group",
    "top_exact_values": 30,
    "quantile_ci": "session-clustered bootstrap, identical draws to lib.stats.cluster_quantile (same SEED, same pick "
                   "sequence); several q are read off each draw. CIs are reported for p1, p5, p50, p95; min/max have none.",
    "rate_ci": "lib.stats.cluster_rate with the session as unit (stamp shares: stamps per session; delta shares: pairs per session)",
    "aiv_cc_batch_threshold_s": 0.001,
    "aiv_cc_batch_reason": "fixed by the task: consecutive rows < 1 ms apart are candidate batch inserts. Rows are events "
                           "(aiv_cc has exactly one IR event per DB row: one uuid per event).",
    "human_wait": {
        "tool_classes": {
            "auto_read": ["read", "glob", "grep", "ls"],
            "shell": ["shell"],
            "file_write": ["edit", "write", "notebookedit"],
            "human_interactive": ["askuserquestion", "exitplanmode", "enterplanmode"],
            "internal_noperm": ["todo", "taskcreate", "taskupdate", "tasklist", "taskget", "toolsearch"],
            "subagent": ["subagent"],
            "other": "everything else (mcp tools, web tools, skills, task output, gui...)",
        },
        "class_reason": "Claude Code default permission mode auto-approves read-only file tools (Read/Glob/Grep/LS) and its "
                        "internal todo/task tools; Bash, Edit and Write prompt unless allow-listed or in acceptEdits/bypass mode; "
                        "AskUserQuestion/plan-mode tools wait for the human by design; subagent latency is a whole sub-run.",
        "slow_thresholds_s": [2.0, 10.0],
        "slow_threshold_reason": "a local file read/edit executes in well under 1 s; above 2 s needs an external cause "
                                 "(human prompt, hook, slow FS); 10 s is above any plausible hook/FS overhead for a local edit.",
        "hook_link": "swechat claude_code hook_progress meta events (extra.type) linked to a call by parent_call_id == call_id "
                     "within the session; cc_local hook attachments linked by extra.toolUseID == call_id.",
        "bash_progress_offset": "for shell calls with linked bash_progress meta events: offset = min over the call's progress "
                                "events of ((progress.ts - call.ts) - elapsedTimeSeconds). elapsedTimeSeconds is an integer, "
                                "so each offset carries up to ~1 s of rounding.",
        "permission_markers": "ir.error_marker(result text): cc_permission_denied, cc_interrupt_reject",
    },
    "aiv_cu_turn": "a turn = one DB row = distinct (session_id, uuid); its stamp is the row's created_at (all events of a row "
                   "share it). Inter-turn gap = ts(turn k+1) - ts(turn k) in ts order within a session. Server-timing residual = "
                   "gap - extra.timing.server_timing_dur_ms/1000 of turn k+1's call event, where present.",
    "privacy_cc_local": "aggregates only; tool names outside PUBLIC_CC_TOOLS collapsed (mcp__* / other_tool).",
    "additions_after_first_run": {
        "note": "no threshold, class or kill-rule operationalisation was changed after the first run; these measurements "
                "were ADDED after reading it (outcome-independent descriptive checks)",
        "multi_call_message_effect": "added because aiv_cc file_write had a slow tail without any permission mode that "
                                     "could cause it; checks whether non-last tool_use blocks of one API message carry "
                                     "later-block generation time",
        "last_digit_native_hist_distinct_stamps": "added because aiv_cu call+result share one stamp, so the paired-stamp "
                                                  "digit test counted each stamp twice",
        "consecutive_rows.by_kind_transition.gap_s": "added to locate the aiv_cc minimum inter-row gap by row kind",
        "sdk_result_duration_vs_run_span duration>0 split": "18 SDK result rows report duration_ms 0, which made the ratio "
                                                            "undefined",
        "codex delta_s_by_tool_raw / results_unified_exec_running": "to separate Codex polling/yield semantics",
        "per-format calls_without_result": "to account for the swechat unpaired calls per format",
        "verdict all_event_whole_second_stamp_share": "for units with stamps but no pairs (simple_text)",
    },
}

PUBLIC_CC_TOOLS = {"shell", "read", "write", "edit", "glob", "grep", "ls", "todo", "subagent", "webfetch", "websearch",
                   "taskcreate", "taskupdate", "tasklist", "taskget", "taskoutput", "taskstop", "toolsearch",
                   "askuserquestion", "exitplanmode", "enterplanmode", "skill", "sendmessage", "notebookedit", "workflow",
                   "killshell", "bashoutput", "killbash", "monitor", "croncreate", "crondelete", "cronlist", "enterworktree",
                   "exitworktree", "listmcpresourcestool", "readmcpresourcetool", "artifact", "slashcommand", "lsp",
                   "pushnotification", "sendusefile", "senduserfile", "remotetrigger", "listagents"}

CLASS_OF = {}
for _c, _tools in RULES["human_wait"]["tool_classes"].items():
    if isinstance(_tools, list):
        for _t in _tools:
            CLASS_OF[_t] = _c


def tool_class(t):
    return CLASS_OF.get(t, "other")


# ----------------------------------------------------------------------------------------------------------------- utils
FRAC_RX = re.compile(r"T\d\d:\d\d:\d\d(?:\.(\d+))?")


def frac_of(s):
    m = FRAC_RX.search(s)
    if not m:
        return None
    return m.group(1) or ""


def us_between(a, b):
    td = b - a
    return td.days * 86_400_000_000 + td.seconds * 1_000_000 + td.microseconds


def _sobj(series):
    """pandas string column -> list of python str/None."""
    return [x if isinstance(x, str) else None for x in series.astype(object)]


def load(corpus, columns, filters=None):
    path = CACHE / f"{corpus}_A.parquet"
    assert path.name.endswith("_A.parquet")
    return pd.read_parquet(path, columns=columns, filters=filters)


def jl(e):
    if isinstance(e, str):
        try:
            return json.loads(e)
        except ValueError:
            return {}
    return {}


def rate(num_by, den_by):
    """cluster_rate from two {session: count} dicts (den keys define the sessions)."""
    keys = list(den_by)
    r = stats.cluster_rate([num_by.get(k, 0) for k in keys], [den_by[k] for k in keys])
    return {k: (int(v) if k in ("num", "den") and v is not None else v) for k, v in r.items()}


def rate_from_mask(mask, sids):
    mask = np.asarray(mask, dtype=bool)
    sids = np.asarray(sids, dtype=object)
    den = Counter(sids.tolist())
    num = Counter(sids[mask].tolist())
    return rate(num, den)


QS = (0.01, 0.05, 0.5, 0.95)


def qstats(values, sids, qs=QS, n_boot=stats.N_BOOT, seed=stats.SEED, ci=True):
    """min/max plus quantiles with session-clustered bootstrap CI (draws identical to stats.cluster_quantile)."""
    v = np.asarray(values, dtype=float)
    s = np.asarray(sids, dtype=object)
    out = {"n": int(len(v)), "n_sessions": int(len(set(s.tolist())))}
    if len(v) == 0:
        return out
    out["min"] = float(v.min())
    out["max"] = float(v.max())
    pts = np.quantile(v, qs)
    uniq, inv = np.unique(s.astype(str), return_inverse=True)
    boots = None
    if ci and len(uniq) >= 2:
        order = np.argsort(inv, kind="stable")
        bounds = np.searchsorted(inv[order], np.arange(len(uniq) + 1))
        groups = [v[order[bounds[i]:bounds[i + 1]]] for i in range(len(uniq))]
        rng = np.random.default_rng(seed)
        boots = np.empty((n_boot, len(qs)))
        for b in range(n_boot):
            pick = rng.integers(0, len(groups), size=len(groups))
            boots[b] = np.quantile(np.concatenate([groups[i] for i in pick]), qs)
    for i, q in enumerate(qs):
        name = f"p{round(q * 100, 2):g}"
        d = {"value": float(pts[i])}
        if boots is not None:
            d["lo"] = float(np.quantile(boots[:, i], 0.025))
            d["hi"] = float(np.quantile(boots[:, i], 0.975))
        out[name] = d
    return out


def top_exact(delta_us, k=30):
    c = Counter(delta_us.tolist())
    return {"n_distinct": len(c),
            "top": [{"delta_us": int(d), "delta_s": f"{d / 1e6:.6f}", "count": int(n)} for d, n in c.most_common(k)]}


# ------------------------------------------------------------------------------------------------------------- pairing
def make_pairs(df):
    """df: call+result rows of one corpus (session_id, seq, kind, ts, tool, tool_raw, call_id, is_subagent, ...).
    Returns (pairs frame, pairing counts)."""
    calls = df[df.kind == "call"].sort_values(["session_id", "seq"])
    results = df[df.kind == "result"].sort_values(["session_id", "seq"])
    n_calls, n_results = len(calls), len(results)
    dup_c = int(calls.duplicated(["session_id", "call_id"]).sum())
    dup_r = int(results.duplicated(["session_id", "call_id"]).sum())
    res_null_id = int(results.call_id.isna().sum())
    calls = calls.drop_duplicates(["session_id", "call_id"], keep="first")
    results = results[results.call_id.notna()].drop_duplicates(["session_id", "call_id"], keep="first")
    rcols = [c for c in results.columns if c not in ("kind", "tool_raw", "stratum", "fmt")]
    p = calls.merge(results[rcols], on=["session_id", "call_id"], suffixes=("_c", "_r"))
    p["tool"] = p["tool_c"]
    p["session_id"] = p["session_id"].astype(str)
    p["call_id"] = p["call_id"].astype(object).astype(str)
    counts = {"call_events": n_calls, "result_events": n_results, "duplicate_call_ids_dropped": dup_c,
              "duplicate_result_ids_dropped": dup_r, "results_null_call_id": res_null_id, "pairs": len(p),
              "calls_without_result": int(len(calls) - len(p)), "results_without_call": int(len(results) - len(p))}
    if "is_subagent_r" in p.columns:
        counts["is_subagent_call_ne_result"] = int((p.is_subagent_c.astype("boolean") != p.is_subagent_r.astype("boolean")).fillna(False).sum())
        p["is_subagent"] = p["is_subagent_c"].astype("boolean").fillna(False).astype(bool)
    tc, tr = _sobj(p.ts_c), _sobj(p.ts_r)
    dus = []
    for a, b in zip(tc, tr):
        if a and b:
            pa, pb = parse_ts(a), parse_ts(b)
            dus.append(us_between(pa, pb) if (pa is not None and pb is not None) else None)
        else:
            dus.append(None)
    p["ts_c"], p["ts_r"] = tc, tr
    p["delta_us"] = pd.array(dus, dtype="Int64")
    counts["pairs_both_ts"] = int(p.delta_us.notna().sum())
    counts["pairs_missing_ts"] = int(p.delta_us.isna().sum())
    counts["pairs_missing_call_ts"] = int(sum(1 for a in tc if not a))
    counts["pairs_missing_result_ts"] = int(sum(1 for b in tr if not b))
    return p, counts


# ------------------------------------------------------------------------------------------------------- group metrics
def stamp_block(stamps, sids, native=None):
    """stamps: list of ts strings (non-null), sids parallel."""
    fr = [frac_of(s) for s in stamps]
    ok = [f is not None for f in fr]
    fd = Counter(len(f) for f in fr if f is not None)
    ws = np.array([f is not None and (f == "" or set(f) <= {"0"}) for f in fr])
    wm = np.array([f is not None and (f + "000000")[:6][3:] == "000" for f in fr])
    out = {"n_stamps": len(stamps), "unparsed_stamp_format": int(len(ok) - sum(ok)),
           "fractional_digits_hist": {str(k): int(v) for k, v in sorted(fd.items())},
           "whole_second_stamps": rate_from_mask(ws, sids), "whole_ms_stamps": rate_from_mask(wm, sids)}
    if native is None:
        native = max(fd) if fd else 0
    out["native_fractional_digits"] = int(native)
    if native > 0:
        ld = Counter((f + "0" * native)[native - 1] for f in fr if f is not None)
        cnts = [ld.get(str(d), 0) for d in range(10)]
        out["last_digit_native_hist"] = cnts
        out["last_digit_native_chi2_uniform"] = stats.chi2_uniform(cnts)
        # distinct (session, stamp): a shared stamp (aiv_cu call+result, several blocks of one row) counts once
        seen = {(str(sid), st) for sid, st, f in zip(sids, stamps, fr) if f is not None}
        ldd = Counter((frac_of(st) + "0" * native)[native - 1] for _, st in seen)
        cd = [ldd.get(str(d), 0) for d in range(10)]
        out["n_distinct_session_stamps"] = len(seen)
        out["last_digit_native_hist_distinct_stamps"] = cd
        out["last_digit_native_chi2_uniform_distinct_stamps"] = stats.chi2_uniform(cd)
    return out


def group_metrics(p, all_stamps=None, all_sids=None, with_tools=True, ci=True):
    """p: pairs frame subset. all_stamps: every event ts in the group (for the all-events digit histogram)."""
    out = {"n_pairs": int(len(p)), "n_sessions": int(p.session_id.nunique())}
    q = p[p.delta_us.notna()]
    out["n_pairs_both_ts"] = int(len(q))
    out["n_sessions_both_ts"] = int(q.session_id.nunique())
    if all_stamps is not None:
        out["all_event_stamps"] = stamp_block(all_stamps, all_sids)
    if len(q) == 0:
        return out
    sids = q.session_id.astype(str).to_numpy()
    stamps = list(q.ts_c) + list(q.ts_r)
    out["paired_stamps"] = stamp_block(stamps, np.concatenate([sids, sids]))
    out["paired_call_stamps_fractional_digits_hist"] = stamp_block(list(q.ts_c), sids)["fractional_digits_hist"]
    out["paired_result_stamps_fractional_digits_hist"] = stamp_block(list(q.ts_r), sids)["fractional_digits_hist"]
    d = q.delta_us.astype("int64").to_numpy()
    ds = d / 1e6
    out["delta_zero"] = rate_from_mask(d == 0, sids)
    out["delta_whole_second"] = rate_from_mask(d % 1_000_000 == 0, sids)
    out["delta_whole_second_nonzero"] = rate_from_mask((d % 1_000_000 == 0) & (d != 0), sids)
    out["delta_whole_ms"] = rate_from_mask(d % 1000 == 0, sids)
    out["delta_negative"] = rate_from_mask(d < 0, sids)
    nz = np.abs(d[d != 0])
    out["min_abs_nonzero_delta_us"] = int(nz.min()) if len(nz) else None
    out["gcd_abs_nonzero_delta_us"] = int(reduce(math.gcd, nz.tolist())) if len(nz) else None
    out["delta_exact_values"] = top_exact(d, RULES["top_exact_values"])
    out["delta_log_histogram_s"] = stats.log_histogram(ds)
    out["delta_s"] = qstats(ds, sids, ci=ci)
    if with_tools:
        tools = q.tool.astype(object).fillna("<none>").to_numpy()
        top = Counter(tools.tolist()).most_common(10)
        per = {}
        for t, n in top:
            m = tools == t
            dd = d[m]
            per[t] = {"delta_s": qstats(dd / 1e6, sids[m], ci=ci), "zero": int((dd == 0).sum()),
                      "negative": int((dd < 0).sum()), "whole_second": int((dd % 1_000_000 == 0).sum())}
        out["top_tools"] = per
    return out


def verdict(gm, has_any_ts):
    n = gm.get("n_pairs_both_ts", 0)
    if not has_any_ts or n == 0:
        v = {"verdict": "KILLED", "reason": ["no_timestamps"] if not has_any_ts else ["no_call_result_pairs_with_both_stamps"],
             "n_pairs": gm.get("n_pairs", 0), "n_pairs_both_ts": n}
        if "all_event_stamps" in gm and gm["all_event_stamps"]["n_stamps"]:
            v["all_event_whole_second_stamp_share"] = gm["all_event_stamps"]["whole_second_stamps"]
        return v
    ws = gm["paired_stamps"]["whole_second_stamps"]["rate"]
    zs = gm["delta_zero"]["rate"]
    reasons = []
    if ws > 0.5:
        reasons.append("whole_second_stamps")
    if zs > 0.5:
        reasons.append("shared_call_result_stamp")
    mixed = [nm for nm, v in (("whole_second_stamps", ws), ("shared_call_result_stamp", zs)) if 0.01 < v <= 0.5]
    return {"verdict": "KILLED" if reasons else "ALIVE", "reason": reasons or None, "mixed_flag": mixed or None,
            "n_pairs_both_ts": n, "n_sessions": gm["n_sessions_both_ts"],
            "whole_second_stamp_share": gm["paired_stamps"]["whole_second_stamps"],
            "identical_stamp_share": gm["delta_zero"],
            "native_fractional_digits": gm["paired_stamps"]["native_fractional_digits"]}


# ----------------------------------------------------------------------------------------------------------- loaders
BASE_COLS = ["session_id", "seq", "kind", "ts", "ts_kind", "tool", "tool_raw", "call_id", "is_subagent", "stratum"]


def load_corpus(corpus):
    df = load(corpus, BASE_COLS + ["uuid", "parent_uuid", "parent_call_id", "extra"])
    if corpus == "swechat":
        pop = pd.read_parquet(CACHE / "swechat_population.parquet", columns=["session_id", "format"])
        df = df.merge(pop.rename(columns={"format": "fmt"}), on="session_id", how="left")
    if corpus == "cc_local":
        df["tool"] = [privatize_tool(t) for t in _sobj(df.tool)]
        df["tool_raw"] = None
    return df


def privatize_tool(t):
    if t is None:
        return None
    if t.startswith("mcp__"):
        return "mcp__*"
    return t if t in PUBLIC_CC_TOOLS else "other_tool"


def result_markers(corpus):
    """(session_id, call_id) -> error_marker(text) for result events. Text stays in memory only."""
    r = load(corpus, ["session_id", "seq", "kind", "call_id", "text", "extra"], filters=[("kind", "==", "result")])
    r = r.sort_values(["session_id", "seq"]).drop_duplicates(["session_id", "call_id"], keep="first")
    mk = [error_marker(t) if isinstance(t, str) else None for t in r.text.astype(object)]
    ex_mk = [jl(e).get("marker", "<absent>") if isinstance(e, str) else "<absent>" for e in r.extra.astype(object)]
    agree = Counter((a == b) if b != "<absent>" else "extra_marker_absent" for a, b in zip(mk, ex_mk))
    out = pd.DataFrame({"session_id": r.session_id.astype(str).to_numpy(), "call_id": r.call_id.astype(object).to_numpy(),
                        "marker": mk})
    del r
    return out, {str(k): int(v) for k, v in agree.items()}


# ------------------------------------------------------------------------------------------------------------- sections
def corpus_sections(corpus, df, P, res):
    """Per-corpus metrics, per is_subagent, (swechat) per format and per format x is_subagent."""
    ev = df[df.ts.notna()]
    stamps_all, sids_all = _sobj(ev.ts), ev.session_id.astype(str).to_numpy()
    has_ts = len(stamps_all) > 0
    g = {"corpus": group_metrics(P, stamps_all, sids_all)}
    g["corpus"]["ts_kind_counts"] = {str(k): int(v) for k, v in df.ts_kind.value_counts().items()}
    for sub, ps in P.groupby("is_subagent"):
        es = ev[ev.is_subagent.astype("boolean").fillna(False).astype(bool) == bool(sub)]
        g[f"is_subagent={bool(sub)}"] = group_metrics(ps, _sobj(es.ts), es.session_id.astype(str).to_numpy())
    res["groups"][corpus] = g
    res["verdicts"][corpus] = verdict(g["corpus"], has_ts)
    if corpus == "swechat":
        for fmt in sorted(df.fmt.dropna().unique()):
            dfx = df[df.fmt == fmt]
            pf = P[P.fmt == fmt]
            evx = dfx[dfx.ts.notna()]
            gg = {"format": group_metrics(pf, _sobj(evx.ts), evx.session_id.astype(str).to_numpy())}
            gg["format"]["n_sessions_in_A"] = int(dfx.session_id.nunique())
            gg["format"]["events"] = int(len(dfx))
            gg["format"]["ts_kind_counts"] = {str(k): int(v) for k, v in dfx.ts_kind.value_counts().items()}
            gg["format"]["call_events"] = int((dfx.kind == "call").sum())
            gg["format"]["result_events"] = int((dfx.kind == "result").sum())
            cx = dfx[dfx.kind == "call"].drop_duplicates(["session_id", "call_id"])
            paired_keys = set(zip(pf.session_id.astype(str), pf.call_id.astype(str)))
            unp = [(str(s_), t) for s_, c_, t in zip(cx.session_id, cx.call_id.astype(object), _sobj(cx.ts))
                   if (str(s_), str(c_)) not in paired_keys]
            gg["format"]["calls_without_result"] = len(unp)
            gg["format"]["calls_without_result_and_without_ts"] = sum(1 for _, t in unp if not t)
            gg["format"]["sessions_with_calls_without_result"] = len({x for x, _ in unp})
            for sub, ps in pf.groupby("is_subagent"):
                es = evx[evx.is_subagent.astype("boolean").fillna(False).astype(bool) == bool(sub)]
                gg[f"is_subagent={bool(sub)}"] = group_metrics(ps, _sobj(es.ts), es.session_id.astype(str).to_numpy())
            res["groups"][f"swechat/format={fmt}"] = gg
            res["verdicts"][f"swechat/format={fmt}"] = verdict(gg["format"], len(evx) > 0)
    if corpus == "aiv_cu":
        per = {}
        for st, ps in P.groupby("stratum"):
            gm = group_metrics(ps, with_tools=False)
            per[str(st)] = {"n_pairs_both_ts": gm.get("n_pairs_both_ts"), "n_sessions": gm.get("n_sessions_both_ts"),
                            "delta_zero": gm.get("delta_zero"), "whole_second_stamps": gm.get("paired_stamps", {}).get("whole_second_stamps")}
            res["verdicts"][f"aiv_cu/stratum={st}"] = verdict(gm, True)
        res["groups"]["aiv_cu"]["by_stratum"] = per


def consecutive_gaps(df, label):
    """Gaps between consecutive rows in a session (row = distinct (session, uuid) when uuid exists, else event), ts order."""
    d = df[df.ts.notna()][["session_id", "seq", "kind", "ts", "uuid"]].copy()
    d["uuid"] = d.uuid.astype(object)
    d["rowkey"] = [u if isinstance(u, str) else f"seq:{s}" for u, s in zip(d.uuid, d.seq)]
    d = d.sort_values(["session_id", "seq"]).drop_duplicates(["session_id", "rowkey"], keep="first")
    d["t"] = [parse_ts(s) for s in _sobj(d.ts)]
    d = d.sort_values(["session_id", "t", "seq"], kind="stable")
    sids = d.session_id.astype(str).to_numpy()
    kinds = d.kind.astype(str).to_numpy()
    ts = d.t.to_numpy()
    gaps, gs, kp = [], [], Counter()
    by_key = defaultdict(list)
    sub1 = Counter()
    zero = Counter()
    runs = Counter()
    cur = 1
    for i in range(1, len(d)):
        if sids[i] != sids[i - 1]:
            if cur >= 2:
                runs[cur] += 1
            cur = 1
            continue
        g_us = us_between(ts[i - 1], ts[i])
        gaps.append(g_us)
        gs.append(sids[i])
        key = f"{kinds[i - 1]}->{kinds[i]}"
        kp[key] += 1
        by_key[key].append(g_us)
        if g_us < 1000:
            sub1[key] += 1
            cur += 1
        else:
            if cur >= 2:
                runs[cur] += 1
            cur = 1
        if g_us == 0:
            zero[key] += 1
    if cur >= 2:
        runs[cur] += 1
    gaps = np.array(gaps)
    gs = np.array(gs, dtype=object)
    out = {"label": label, "rows": int(len(d)), "sessions": int(len(set(sids.tolist()))), "consecutive_gaps": int(len(gaps)),
           "gap_lt_1ms": rate_from_mask(gaps < 1000, gs), "gap_zero": rate_from_mask(gaps == 0, gs),
           "gap_negative": int((gaps < 0).sum()),
           "runs_of_rows_lt_1ms_apart_length_hist": {str(k): int(v) for k, v in sorted(runs.items())},
           "by_kind_transition": {k: {"n": int(n), "lt_1ms": int(sub1.get(k, 0)), "zero": int(zero.get(k, 0)),
                                      "gap_s": stats.describe(np.array(by_key[k]) / 1e6, qs=(0.0, 0.01, 0.05, 0.5))}
                                  for k, n in kp.most_common()},
           "gap_s": stats.describe(gaps / 1e6)}
    return out


def aiv_cc_section(df, P, swe_P, ccl_P, res):
    s = {}
    s["parent_uuid_nonnull_events"] = int(df.parent_uuid.notna().sum())
    s["events"] = int(len(df))
    s["parent_uuid_check"] = ("not measurable: parent_uuid is null on every aiv_cc IR row (the SDK stream rows carry no "
                              "parentUuid); causal proxy = result row stamped before its call row (delta_negative)")
    q = P[P.delta_us.notna()]
    s["result_before_call_rows"] = int((q.delta_us < 0).sum())
    s["result_same_stamp_as_call_rows"] = int((q.delta_us == 0).sum())
    s["consecutive_rows"] = consecutive_gaps(df, "aiv_cc rows (1 event per row), created_at order")
    # ingestion floor: per-tool low quantiles vs event-time Claude Code corpora
    floor = {}
    for name, PP in (("aiv_cc", P), ("swechat_claude_code", swe_P), ("cc_local", ccl_P)):
        qq = PP[PP.delta_us.notna()]
        tools = qq.tool.astype(object).fillna("<none>").to_numpy()
        d = qq.delta_us.astype("int64").to_numpy() / 1e6
        sids = qq.session_id.astype(str).to_numpy()
        per = {}
        for t in ["todo", "read", "glob", "grep", "edit", "write", "shell", "webfetch", "websearch", "gui",
                  "mcp__village__get_events", "mcp__village__chat_message", "mcp__village__edit_memory"]:
            m = tools == t
            if m.sum() == 0:
                continue
            per[t] = qstats(d[m], sids[m], qs=(0.01, 0.05, 0.25, 0.5))
        floor[name] = per
    s["per_tool_low_quantiles"] = floor
    # tool-reported durations vs insert-stamp delta
    s["reported_duration_vs_delta"] = reported_duration_check(q, "aiv_cc")
    # SDK result rows: duration_ms vs the run's stamp span
    meta = df[(df.kind == "meta") & df.extra.notna()]
    first = {}
    for sid, ts in zip(df.session_id.astype(str), _sobj(df.ts)):
        if ts:
            t = parse_ts(ts)
            if sid not in first or t < first[sid]:
                first[sid] = t
    rows = []
    for sid, e, ts in zip(meta.session_id.astype(str), meta.extra.astype(object), _sobj(meta.ts)):
        x = jl(e)
        if x.get("entry_type") == "result" and isinstance(x.get("duration_ms"), (int, float)) and sid in first and ts:
            span_us = us_between(first[sid], parse_ts(ts))
            rows.append((sid, x["duration_ms"] / 1000.0, span_us / 1e6, x.get("duration_api_ms")))
    if rows:
        arr = np.array([(a, b) for _, a, b, _ in rows])
        diff = arr[:, 1] - arr[:, 0]
        pos = arr[:, 0] > 0
        s["sdk_result_duration_vs_run_span"] = {
            "n_result_rows_with_duration": len(rows), "n_sessions": len({r[0] for r in rows}),
            "n_duration_ms_zero": int((~pos).sum()),
            "span_minus_duration_s": stats.describe(diff),
            "span_minus_duration_s_duration_gt0": stats.describe(diff[pos]),
            "span_over_duration_ratio_duration_gt0": stats.describe(arr[pos, 1] / arr[pos, 0]),
            "definition": "span = result-row ts minus first row ts of the run (session); duration = result.duration_ms/1000"}
    perm = Counter()
    for e in meta.extra.astype(object):
        x = jl(e)
        if x.get("subtype") == "init":
            perm[str(x.get("permissionMode"))] += 1
    s["init_permissionMode_counts"] = dict(perm)
    res["aiv_cc_insert_time"] = s


def reported_duration_check(q, label):
    """Results whose extra carries a tool-reported duration: compare with the stamp delta."""
    out = {}
    if "extra_r" not in q.columns:
        return out
    acc = defaultdict(lambda: {"d": [], "s": []})
    for t, e, du, sid in zip(q.tool.astype(object), q.extra_r.astype(object), q.delta_us.astype("int64"), q.session_id.astype(str)):
        x = jl(e)
        for key, scale in (("durationMs", 1e-3), ("durationSeconds", 1.0), ("duration_s", 1.0)):
            v = x.get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                acc[(key, str(t))]["d"].append(du / 1e6 - v * scale)
                acc[(key, str(t))]["s"].append(sid)
    for (key, t), v in sorted(acc.items()):
        d = np.array(v["d"])
        out[f"{key}|{t}"] = {"delta_minus_reported_s": qstats(d, v["s"], qs=(0.05, 0.5, 0.95)),
                             "delta_ge_reported": int((d >= 0).sum()), "n": int(len(d))}
    return out


def aiv_cu_section(df, P, res):
    s = {}
    q = P[P.delta_us.notna()]
    s["call_result_identical_stamp"] = rate_from_mask(q.delta_us.to_numpy(dtype="int64") == 0, q.session_id.astype(str).to_numpy())
    # turns
    d = df[df.ts.notna()][["session_id", "seq", "kind", "ts", "uuid", "extra", "stratum"]]
    turns = d.sort_values(["session_id", "seq"]).drop_duplicates(["session_id", "uuid"], keep="first")[["session_id", "uuid", "ts", "stratum"]]
    s["turn_rows"] = int(len(turns))
    s["turn_rows_distinct_ts_per_uuid_gt1"] = int((d.groupby(["session_id", "uuid"]).ts.nunique() > 1).sum())
    timing = {}
    for sid, u, e in zip(d.session_id.astype(str), d.uuid.astype(str), d.extra.astype(object)):
        x = jl(e)
        tm = x.get("timing")
        if isinstance(tm, dict) and isinstance(tm.get("server_timing_dur_ms"), (int, float)):
            timing[(sid, u)] = tm
    s["turns_with_server_timing"] = len(timing)
    turns["t"] = [parse_ts(x) for x in _sobj(turns.ts)]
    turns = turns.sort_values(["session_id", "t"], kind="stable")
    sids = turns.session_id.astype(str).to_numpy()
    uu = turns.uuid.astype(str).to_numpy()
    tt = turns.t.to_numpy()
    strat = turns.stratum.astype(str).to_numpy()
    gaps, gsid, gstrat, resid, rsid, rstrat, dur = [], [], [], [], [], [], []
    httpd, hsid = [], []
    for i in range(len(turns)):
        tm = timing.get((sids[i], uu[i]))
        if tm and tm.get("http_date"):
            hd = parse_ts(iso(tm["http_date"]))
            if hd is not None:
                httpd.append(us_between(hd, tt[i]) / 1e6)
                hsid.append(sids[i])
        if i == 0 or sids[i] != sids[i - 1]:
            continue
        g = us_between(tt[i - 1], tt[i]) / 1e6
        gaps.append(g)
        gsid.append(sids[i])
        gstrat.append(strat[i])
        if tm:
            resid.append(g - tm["server_timing_dur_ms"] / 1000.0)
            dur.append(tm["server_timing_dur_ms"] / 1000.0)
            rsid.append(sids[i])
            rstrat.append(strat[i])
    gaps, resid = np.array(gaps), np.array(resid)
    s["inter_turn_gap_s"] = qstats(gaps, gsid)
    s["inter_turn_gap_zero"] = rate_from_mask(gaps == 0, gsid)
    s["inter_turn_gap_log_histogram_s"] = stats.log_histogram(gaps)
    s["inter_turn_gap_by_stratum_s"] = {st: stats.describe(gaps[np.array(gstrat) == st]) for st in sorted(set(gstrat))}
    s["server_timing"] = {"n_gaps_with_timing": int(len(resid)), "strata": dict(Counter(rstrat)),
                          "server_timing_dur_s": qstats(dur, rsid) if dur else None,
                          "gap_minus_server_timing_s": qstats(resid, rsid) if len(resid) else None,
                          "gap_minus_server_timing_negative": rate_from_mask(resid < 0, rsid) if len(resid) else None,
                          "gap_minus_server_timing_log_histogram_s": stats.log_histogram(resid) if len(resid) else None}
    hd = np.array(httpd)
    s["created_at_minus_http_date"] = {"n": int(len(hd)), "diff_s": qstats(hd, hsid, qs=(0.05, 0.5, 0.95)) if len(hd) else None,
                                       "created_before_http_date": int((hd < 0).sum()),
                                       "note": "http_date has 1 s resolution (truncated), so diff in [0,1) is within resolution"}
    # updated_at vs created_at on result rows
    r = df[(df.kind == "result")]
    ud, usid = [], []
    for sid, ts, e in zip(r.session_id.astype(str), _sobj(r.ts), r.extra.astype(object)):
        x = jl(e)
        ua = x.get("updated_at")
        if ua and ts:
            a, b = parse_ts(ts), parse_ts(iso(ua))
            if a is not None and b is not None:
                ud.append(us_between(a, b) / 1e6)
                usid.append(sid)
    ud = np.array(ud)
    s["updated_at_minus_created_at_s"] = {"n": int(len(ud)), "q": qstats(ud, usid, qs=(0.05, 0.5, 0.95)) if len(ud) else None,
                                          "zero": int((ud == 0).sum()), "negative": int((ud < 0).sum()),
                                          "lt_1ms": int(((ud >= 0) & (ud < 0.001)).sum()), "ge_1s": int((ud >= 1).sum())}
    res["aiv_cu_shared_turn"] = s


def multi_call_effect(name, corpus, P, keep_sessions=None):
    """Calls that are not the last tool_use block of their API message (same session, api_msg_id): their call stamp
    precedes the later blocks' generation. Compare delta for last vs not-last blocks, and measure not-last results
    from the last block's stamp. api_msg_id is used in memory only."""
    c = load(corpus, ["session_id", "seq", "kind", "call_id", "api_msg_id", "ts"], filters=[("kind", "==", "call")])
    c["session_id"] = c.session_id.astype(str)
    if keep_sessions is not None:
        c = c[c.session_id.isin(keep_sessions)]
    c = c.sort_values(["session_id", "seq"]).drop_duplicates(["session_id", "call_id"], keep="first")
    c["call_id"] = c.call_id.astype(object).astype(str)
    c["msg"] = [a if isinstance(a, str) else f"__solo__{cid}" for a, cid in zip(c.api_msg_id.astype(object), c.call_id)]
    c["last_in_msg"] = ~c.duplicated(["session_id", "msg"], keep="last")
    c["n_in_msg"] = c.groupby(["session_id", "msg"]).call_id.transform("size")
    last_ts = {(s_, m): t for s_, m, t, l in zip(c.session_id, c.msg, _sobj(c.ts), c.last_in_msg) if l}
    c["last_ts"] = [last_ts.get((s_, m)) for s_, m in zip(c.session_id, c.msg)]
    q = P[P.delta_us.notna()][["session_id", "call_id", "tool", "ts_r", "delta_us", "is_subagent"]].merge(
        c[["session_id", "call_id", "last_in_msg", "n_in_msg", "last_ts", "api_msg_id"]], on=["session_id", "call_id"], how="left")
    out = {"pairs": int(len(q)), "pairs_without_call_row_match": int(q.last_in_msg.isna().sum()),
           "pairs_api_msg_id_null": int(q.api_msg_id.isna().sum()),
           "pairs_in_multi_call_messages": rate_from_mask((q.n_in_msg > 1).to_numpy(), q.session_id.to_numpy()),
           "pairs_not_last_block": rate_from_mask((q.last_in_msg == False).to_numpy(), q.session_id.to_numpy())}
    q = q[q.last_in_msg.notna()].copy()
    q["d"] = q.delta_us.astype("int64") / 1e6
    q["cls"] = [tool_class(t) for t in q.tool.astype(object)]
    dl = []
    for lt, tr, l in zip(q.last_ts, q.ts_r, q.last_in_msg):
        dl.append(None if (l or not lt) else us_between(parse_ts(lt), parse_ts(tr)) / 1e6)
    q["d_from_last"] = dl
    tab = {}
    for cls, g in q.groupby("cls"):
        row = {}
        for flag, gg in ((True, g[g.last_in_msg == True]), (False, g[g.last_in_msg == False])):
            key = "last_block" if flag else "not_last_block"
            row[key] = {"delta_s": qstats(gg.d.to_numpy(), gg.session_id.to_numpy(), qs=(0.5, 0.9, 0.95)) if len(gg) else {"n": 0}}
            if len(gg):
                row[key]["share_gt_2s"] = rate_from_mask((gg.d > 2).to_numpy(), gg.session_id.to_numpy())
        nl = g[(g.last_in_msg == False) & g.d_from_last.notna()]
        if len(nl):
            v = nl.d_from_last.astype(float).to_numpy()
            row["not_last_block_result_minus_last_block_stamp_s"] = qstats(v, nl.session_id.to_numpy(), qs=(0.05, 0.5, 0.95))
            row["not_last_block_result_before_last_block_stamp"] = rate_from_mask(v < 0, nl.session_id.to_numpy())
        tab[cls] = row
    out["by_class"] = tab
    return out


def human_wait_section(name, df, P, markers, res, hooks_mode):
    """Claude Code-format corpora: latency by tool class, markers, hooks, bash_progress offsets."""
    out = {}
    q = P[P.delta_us.notna()].copy()
    markers = markers.assign(session_id=markers.session_id.astype(str), call_id=markers.call_id.astype(object).astype(str))
    q = q.merge(markers, on=["session_id", "call_id"], how="left")
    q["cls"] = [tool_class(t) for t in q.tool.astype(object)]
    q["d"] = q.delta_us.astype("int64") / 1e6
    q["sid"] = q.session_id.astype(str)
    thr = RULES["human_wait"]["slow_thresholds_s"]
    for sub_name, qq in (("all", q), ("is_subagent=False", q[~q.is_subagent]), ("is_subagent=True", q[q.is_subagent])):
        tab = {}
        for c, g in qq.groupby("cls"):
            row = {"delta_s": qstats(g.d.to_numpy(), g.sid.to_numpy(), qs=(0.5, 0.9, 0.95, 0.99))}
            for t in thr:
                row[f"share_gt_{t:g}s"] = rate_from_mask(g.d.to_numpy() > t, g.sid.to_numpy())
            tab[c] = row
        out[f"latency_by_class/{sub_name}"] = tab
    # markers
    mk = q.marker.astype(object)
    out["result_markers_on_pairs"] = {str(k): int(v) for k, v in Counter(mk.fillna("none")).items()}
    n_sess = q.sid.nunique()
    for m in ("cc_permission_denied", "cc_interrupt_reject"):
        sel = q[mk == m]
        k = sel.sid.nunique()
        p_, lo, hi = stats.wilson(k, n_sess)
        out[f"sessions_with_{m}"] = {"k": int(k), "n_sessions": int(n_sess), "rate": p_, "lo": lo, "hi": hi}
        out[f"latency_of_{m}_s"] = qstats(sel.d.to_numpy(), sel.sid.to_numpy(), qs=(0.05, 0.5, 0.95)) if len(sel) else {"n": 0}
        out[f"{m}_by_class"] = {str(k2): int(v) for k2, v in Counter(sel.cls).items()}
    # hooks
    if hooks_mode == "progress":
        meta = df[(df.kind == "meta") & df.parent_call_id.notna()][["session_id", "ts", "parent_call_id", "extra"]]
        pre, post, prog = defaultdict(list), defaultdict(list), defaultdict(list)
        for sid, ts, pc, e in zip(meta.session_id.astype(str), _sobj(meta.ts), meta.parent_call_id.astype(str), meta.extra.astype(object)):
            x = jl(e)
            ty = x.get("type")
            if ty == "hook_progress" and ts:
                he = x.get("hookEvent")
                if he == "PreToolUse":
                    pre[(sid, pc)].append(ts)
                elif he in ("PostToolUse", "PostToolUseFailure"):
                    post[(sid, pc)].append(ts)
            elif ty == "bash_progress" and ts and isinstance(x.get("elapsedTimeSeconds"), (int, float)):
                prog[(sid, pc)].append((ts, x["elapsedTimeSeconds"]))
        keys = list(zip(q.sid, q.call_id.astype(str)))
        q["has_pre"] = [k in pre for k in keys]
        q["has_post"] = [k in post for k in keys]
        hk = {}
        for c, g in q.groupby("cls"):
            row = {"n": int(len(g)), "with_pretooluse_hook": rate_from_mask(g.has_pre.to_numpy(), g.sid.to_numpy()),
                   "with_posttooluse_hook": rate_from_mask(g.has_post.to_numpy(), g.sid.to_numpy())}
            for flag in (True, False):
                gg = g[g.has_pre == flag]
                row[f"delta_s_pre_hook={flag}"] = qstats(gg.d.to_numpy(), gg.sid.to_numpy(), qs=(0.5, 0.95)) if len(gg) else {"n": 0}
            hk[c] = row
        out["hooks_by_class"] = hk
        out["sessions_with_any_tool_hook"] = int(q[q.has_pre | q.has_post].sid.nunique())
        # hook stamps relative to the call/result stamps
        pre_off, post_off_r, post_sid, pre_sid, in_window = [], [], [], [], 0
        tsc = dict(zip(keys, q.ts_c))
        tsr = dict(zip(keys, q.ts_r))
        for k, lst in pre.items():
            if k not in tsc:
                continue
            c0, r0 = parse_ts(tsc[k]), parse_ts(tsr[k])
            for ts in lst:
                t = parse_ts(ts)
                pre_off.append(us_between(c0, t) / 1e6)
                pre_sid.append(k[0])
                in_window += int(c0 <= t <= r0)
        n_post_before_result = 0
        for k, lst in post.items():
            if k not in tsr:
                continue
            r0 = parse_ts(tsr[k])
            for ts in lst:
                o = us_between(r0, parse_ts(ts)) / 1e6
                post_off_r.append(o)
                post_sid.append(k[0])
                n_post_before_result += int(o < 0)
        out["pretooluse_hook_stamp_minus_call_stamp_s"] = qstats(pre_off, pre_sid, qs=(0.05, 0.5, 0.95)) if pre_off else {"n": 0}
        out["pretooluse_hook_stamp_within_call_result_window"] = int(in_window)
        out["posttooluse_hook_stamp_minus_result_stamp_s"] = qstats(post_off_r, post_sid, qs=(0.05, 0.5, 0.95)) if post_off_r else {"n": 0}
        out["posttooluse_hook_stamp_before_result_stamp"] = int(n_post_before_result)
        # bash_progress pre-exec offset
        offs, osid, ocls = [], [], []
        for k, lst in prog.items():
            if k not in tsc:
                continue
            c0 = parse_ts(tsc[k])
            o = min(us_between(c0, parse_ts(ts)) / 1e6 - el for ts, el in lst)
            offs.append(o)
            osid.append(k[0])
        offs = np.array(offs)
        out["bash_progress_pre_exec_offset_s"] = {
            "n_calls": int(len(offs)), "q": qstats(offs, osid, qs=(0.05, 0.5, 0.9, 0.95)) if len(offs) else None,
            **({f"share_gt_{t:g}s": rate_from_mask(offs > t, osid) for t in thr} if len(offs) else {}),
            "negative_lt_minus_1s": int((offs < -1).sum()) if len(offs) else 0}
    elif hooks_mode == "attachment":
        att = df[df.extra.notna() & df.kind.isin(["system", "meta", "user"])][["session_id", "kind", "extra"]]
        linked, types, auto_sess, stop_hook = set(), Counter(), set(), 0
        for sid, e in zip(att.session_id.astype(str), att.extra.astype(object)):
            x = jl(e)
            at = x.get("attachment_type")
            if at and str(at).startswith("hook") and x.get("toolUseID"):
                linked.add((sid, str(x["toolUseID"])))
                types[str(at)] += 1
            if at == "auto_mode":
                auto_sess.add(sid)
            if x.get("subtype") == "stop_hook_summary":
                stop_hook += 1
        keys = list(zip(q.sid, q.call_id.astype(str)))
        q["has_hook"] = [k in linked for k in keys]
        out["hook_attachments_linked_by_toolUseID"] = {"by_type": dict(types), "calls_with_hook_attachment": int(q.has_hook.sum()),
                                                       "calls": int(len(q)),
                                                       "by_class": {c: int(g.has_hook.sum()) for c, g in q.groupby("cls")}}
        out["stop_hook_summary_events"] = int(stop_hook)
        out["sessions_with_auto_mode_attachment"] = {"k": len(auto_sess), "n_sessions": int(df.session_id.nunique())}
        out["hook_progress_events"] = 0
        out["permissionMode_in_IR"] = "absent (cc_local IR does not carry permissionMode)"
    res["claude_code_human_wait"][name] = out


def other_semantics(swe, Pswe, res):
    s = {}
    for fmt in ("codex", "opencode", "gemini", "copilot", "claude_code"):
        q = Pswe[(Pswe.fmt == fmt) & Pswe.delta_us.notna()]
        x = {"reported_duration_vs_delta": reported_duration_check(q, fmt)}
        if fmt == "codex":
            x["by_tool_raw"] = {str(t): int(n) for t, n in Counter(q.tool_raw.astype(object)).most_common(8)}
            # exec_command only (write_stdin durations are the whole process's, per loader doc)
            qe = q[q.tool_raw.astype(object) == "exec_command"]
            x["reported_duration_vs_delta_exec_command_only"] = reported_duration_check(qe, fmt)
            traw = q.tool_raw.astype(object).fillna("<none>").to_numpy()
            dd = q.delta_us.astype("int64").to_numpy() / 1e6
            ss = q.session_id.astype(str).to_numpy()
            x["delta_s_by_tool_raw"] = {t: qstats(dd[traw == t], ss[traw == t], qs=(0.05, 0.5, 0.95))
                                        for t, _ in Counter(traw.tolist()).most_common(6)}
            run = np.array([bool(jl(e).get("unified_exec_running")) for e in q.extra_r.astype(object)])
            x["results_unified_exec_running"] = {"n": int(run.sum()), "of": int(len(run)),
                                                 "delta_s": qstats(dd[run], ss[run], qs=(0.05, 0.5, 0.95)) if run.any() else None}
        if fmt in ("gemini", "copilot"):
            # calls sharing the call stamp with another call of the same session (one model message, several tool calls)
            c = swe[(swe.fmt == fmt) & (swe.kind == "call") & swe.ts.notna()]
            dup = c.duplicated(["session_id", "ts"], keep=False)
            x["calls_sharing_call_stamp_with_another_call"] = rate_from_mask(dup.to_numpy(), c.session_id.astype(str).to_numpy())
        if fmt == "copilot":
            m = swe[(swe.fmt == fmt) & (swe.kind == "meta") & swe.parent_call_id.notna()]
            st = {}
            for sid, pc, ts, e in zip(m.session_id.astype(str), m.parent_call_id.astype(str), _sobj(m.ts), m.extra.astype(object)):
                if jl(e).get("entry_type") == "tool.execution_start" and ts:
                    st.setdefault((sid, pc), ts)
            a, b, ss = [], [], []
            for sid, cid, tc, tr in zip(q.session_id.astype(str), q.call_id.astype(str), q.ts_c, q.ts_r):
                t0 = st.get((sid, cid))
                if t0:
                    a.append(us_between(parse_ts(tc), parse_ts(t0)) / 1e6)
                    b.append(us_between(parse_ts(t0), parse_ts(tr)) / 1e6)
                    ss.append(sid)
            x["execution_start_minus_call_s"] = qstats(a, ss, qs=(0.05, 0.5, 0.95)) if a else {"n": 0}
            x["result_minus_execution_start_s"] = qstats(b, ss, qs=(0.05, 0.5, 0.95)) if b else {"n": 0}
        s[fmt] = x
    res["format_semantics_checks"] = s


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if hasattr(o, "item") and not isinstance(o, (str, bytes)):
        o = o.item()
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    return o


# ----------------------------------------------------------------------------------------------------------------- main
def main():
    t0 = time.time()
    res = {"question": "A1 timestamp granularity and semantics (latency gate)", "rules": RULES, "inputs": {},
           "pairing": {}, "groups": {}, "verdicts": {}, "claude_code_human_wait": {}}
    pairs = {}
    frames = {}
    for corpus in CORPORA:
        df = load_corpus(corpus)
        res["inputs"][corpus] = {"path": f"analysis/cache/{corpus}_A.parquet", "rows": int(len(df)),
                                 "sessions": int(df.session_id.nunique())}
        cr = df[df.kind.isin(["call", "result"])].copy()
        cr["extra"] = cr["extra"].astype(object)
        keep = ["session_id", "seq", "kind", "ts", "tool", "tool_raw", "call_id", "is_subagent", "stratum", "extra"] + (["fmt"] if corpus == "swechat" else [])
        P, cnt = make_pairs(cr[keep])
        res["pairing"][corpus] = cnt
        corpus_sections(corpus, df, P, res)
        pairs[corpus] = P
        frames[corpus] = df if corpus in ("swechat", "cc_local", "aiv_cc", "aiv_cu") else None
        print(f"[a1] {corpus}: rows={len(df)} pairs={len(P)} t={time.time() - t0:.1f}s", flush=True)

    # CI implementation check against lib.stats.cluster_quantile (one group)
    q = pairs["cc_local"][pairs["cc_local"].delta_us.notna()]
    v, s = q.delta_us.astype("int64").to_numpy() / 1e6, q.session_id.astype(str).to_numpy()
    lib = stats.cluster_quantile(v, s, 0.5)
    mine = qstats(v, s)["p50"]
    res["ci_impl_check"] = {"group": "cc_local all pairs, p50", "lib": lib, "probe": mine,
                            "equal": bool(abs(lib["lo"] - mine["lo"]) < 1e-12 and abs(lib["hi"] - mine["hi"]) < 1e-12)}

    Pswe = pairs["swechat"]
    swe_cc = Pswe[Pswe.fmt == "claude_code"]
    aiv_cc_section(frames["aiv_cc"], pairs["aiv_cc"], swe_cc, pairs["cc_local"], res)
    print(f"[a1] aiv_cc section t={time.time() - t0:.1f}s", flush=True)
    aiv_cu_section(frames["aiv_cu"], pairs["aiv_cu"], res)
    print(f"[a1] aiv_cu section t={time.time() - t0:.1f}s", flush=True)

    # event-time references for the consecutive-row statistic
    res["consecutive_rows_reference"] = {
        "cc_local": consecutive_gaps(frames["cc_local"], "cc_local entries (distinct uuid), event-time order"),
        "swechat_claude_code": consecutive_gaps(frames["swechat"][frames["swechat"].fmt == "claude_code"],
                                                "swechat claude_code entries (distinct uuid), event-time order")}

    # Claude Code-format human-wait evidence
    for name, corpus, P, hooks in (("swechat_claude_code", "swechat", swe_cc, "progress"),
                                    ("cc_local", "cc_local", pairs["cc_local"], "attachment"),
                                    ("aiv_cc", "aiv_cc", pairs["aiv_cc"], None)):
        mk, agree = result_markers(corpus)
        df = frames[corpus]
        if corpus == "swechat":
            df = df[df.fmt == "claude_code"]
            mk = mk[mk.session_id.isin(set(df.session_id.astype(str)))]
        human_wait_section(name, df, P, mk, res, hooks)
        res["claude_code_human_wait"][name]["marker_vs_extra_marker_agreement"] = agree
        res["claude_code_human_wait"][name]["multi_call_message_effect"] = multi_call_effect(
            name, corpus, P, set(df.session_id.astype(str)) if corpus == "swechat" else None)
        print(f"[a1] human-wait {name} t={time.time() - t0:.1f}s", flush=True)
    res["claude_code_human_wait"]["aiv_cc"]["init_permissionMode_counts"] = res["aiv_cc_insert_time"]["init_permissionMode_counts"]

    other_semantics(frames["swechat"], Pswe, res)
    res["cc_local_reported_duration_vs_delta"] = reported_duration_check(pairs["cc_local"][pairs["cc_local"].delta_us.notna()], "cc_local")
    res["runtime_s"] = round(time.time() - t0, 1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(clean(res), indent=1, allow_nan=False), encoding="utf-8")
    print(f"[a1] wrote {OUT} in {res['runtime_s']}s")


if __name__ == "__main__":
    sys.exit(main())
