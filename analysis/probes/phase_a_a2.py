"""Phase A, question A2: join completeness of call <-> result pairing in the IR caches (split A only).

Per corpus, per SWE-chat transcript format, and split by is_subagent, four join defects:
  orphan_results            result events whose (session_id, call_id) has no call event in the session (or call_id null)
  calls_without_result      call events whose (session_id, call_id) has no result event in the session
  duplicate_call_ids        distinct call keys (session_id, call_id) that occur on more than one call event
  calls_with_multi_results  distinct call keys that have two or more result events
Rates use stats.cluster_rate (per-session numerator and denominator; session-clustered bootstrap CI). The share of sessions
with at least one defect gets a Wilson interval (sessions are independent units). Every defect event is also given a
descriptive reason (fixed rule list below, first match wins) so structural gaps (the source never records results) are
kept apart from losses (the session stopped before the result was written).

Also cited (read from the saved files, never recomputed): the SWE-chat full-population pass and the table-vs-raw
cross-check in analysis/out/build/swechat_build.json, the conversations-table recon in analysis/out/recon/, the Phase C
dropped-tool_use share, and the population / split-A pairing counts of the other build reports (consistency check).

Reads ONLY analysis/cache/<corpus>_A.parquet (+ swechat_population.parquet for the format column). Never the B caches.
cc_local is private: only counts, enum names and generic tool classes leave this script; no ids, text, args or paths.

Writes RAW COUNTS ONLY to analysis/out/phase_a/a2.json. Interpretation: analysis/notes/phase_a_a2.md.
Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_a_a2
"""
import json
import os
import re
from collections import Counter

import numpy as np
import pandas as pd

from analysis.lib import stats

HERE = os.path.dirname(os.path.abspath(__file__))
AN = os.path.dirname(HERE)
CACHE = os.path.join(AN, "cache")
OUT = os.path.join(AN, "out", "phase_a", "a2.json")
BUILD = os.path.join(AN, "out", "build")
RECON = os.path.join(AN, "out", "recon")
PHASE_C = os.path.join(AN, "out", "phase_c")

CORPORA = ["swechat", "cc_local", "aiv_cc", "aiv_cu", "whowhen"]
COLS = ["session_id", "stratum", "seq", "kind", "call_id", "tool", "is_subagent", "parent_call_id", "agent_id", "extra", "text"]
SLICES = {"all": None, "is_subagent_false": False, "is_subagent_true": True}
METRICS = ["orphan_results", "calls_without_result", "duplicate_call_ids", "calls_with_multi_results"]

# ---------------------------------------------------------------------------------------------------------------------
# Pre-declared rules. Fixed before the final numbers were computed; each carries its reason.
# ---------------------------------------------------------------------------------------------------------------------
PREREG = {
    "join_key": {
        "value": "(session_id, call_id), within one session; a result pairs with any call event of the same key, whatever its stream",
        "reason": "the IR contract: call_id joins call<->result; sessions are the resampling unit and cross-session ids are not joins"},
    "slice_assignment": {
        "value": "call-based metrics use the call event's is_subagent; result-based use the result's; key-based (duplicate, multi-result) "
                 "use the is_subagent of the key's first call event",
        "reason": "each defect is attributed to the event that carries it"},
    "denominators": {
        "value": {"orphan_results": "result events", "calls_without_result": "call events",
                  "duplicate_call_ids": "distinct call keys", "calls_with_multi_results": "distinct call keys"},
        "reason": "each rate is over the population that can carry the defect"},
    "verdict_rule": {
        "value": "on the 'all' slice of a corpus or SWE-chat format: 'absent' if it has calls but zero result events; 'usable' if the "
                 "cluster-bootstrap upper bound (hi) of all four rates is <= 0.01; else 'partial'. Second verdict: same rule after "
                 "removing calls whose reason is STRUCTURAL from numerator and denominator of calls_without_result",
        "threshold": 0.01,
        "reason": "a mechanism that conditions on a call->result pair (latency, error flag, claim-vs-output) then loses or mis-pairs at "
                  "most 1 call in 100, which is below any effect size Phase B can resolve with these n; 0.01 is a round, conventional "
                  "cut, not tuned",
        "disclosure": "chosen after schema exploration in which the unpaired-call counts of swechat split A (cursor and one gemini session "
                      "structural; Claude Code tens out of thousands) had been seen; it was not changed after the full computation"},
    "structural_reasons": {
        "value": ["source_has_no_results", "server_side_tool", "never_executed_by_harness", "session_has_no_results"],
        "reason": "the source never records a result for these calls by construction (format, server-side tool, harness never ran it, "
                  "session-level export without results); they are coverage gaps, not lost results"},
    "unpaired_call_reason_rules": {
        "value": [
            "source_has_no_results: swechat format 'cursor' (loader: the source has no tool results)",
            "server_side_tool: extra.server_tool is true (Codex web_search_call; no result in the transcript)",
            "never_executed_by_harness: extra.unexecuted present (Who&When AG: code proposed, terminal never ran it)",
            "session_has_no_results: the session has calls but zero result events",
            "stream_end: no later result, user or assistant event in the same stream (stream = agent_id for subagent events, "
            "else parent_call_id for subagent events, else main)",
            "compaction_before_next_result: a meta event with extra.subtype == 'compact_boundary' in the same stream between the call "
            "and the stream's next result",
            "session_start_hook_before_next_result: a meta event with extra.hookEvent == 'SessionStart' in the same stream between the "
            "call and the stream's next result (process restart/resume)",
            "superseded_by_later_call: whowhen only, a later call in the same stream before the next result (orchestrator moved on)",
            "other"],
        "reason": "first match wins; landmarks are IR fields only (no text), so the rule runs on the private corpus too"},
    "orphan_reason_rules": {
        "value": ["null_call_id", "before_any_call_or_assistant_in_session: no call/assistant event with smaller seq in the session",
                  "call_id_is_call_in_other_session_same_split", "other"],
        "reason": "separates continuations of an earlier session file from losses inside a session"},
    "id_reason_rules": {
        "value": ["redacted_id: call_id contains 'REDACTED'", "synthetic_id: call_id starts with 'synthetic:'", "other"],
        "reason": "the SWE-chat release redacted some ids; the loader replaces some with synthetic ids"},
}

STRUCTURAL = set(PREREG["structural_reasons"]["value"])

PAIRING_MECHANISM = {
    "swechat/claude_code": "id_across_entries (assistant tool_use.id <-> user tool_result.tool_use_id)",
    "swechat/codex": "id_across_entries (function_call.call_id <-> function_call_output.call_id)",
    "swechat/copilot": "id_across_entries (assistant toolRequest id <-> tool.execution_complete)",
    "swechat/opencode": "same_record (a tool part holds the call and its completed/error state; REDACTED callIDs get a shared synthetic id)",
    "swechat/gemini": "same_record (a toolCall holds its result when the export has one)",
    "swechat/cursor": "no_results_in_source",
    "swechat/simple_text": "no_tool_calls",
    "cc_local": "id_across_entries (Claude Code JSONL; subagent files joined by parent_call_id)",
    "aiv_cc": "id_across_entries (Claude Agent SDK stream)",
    "aiv_cu": "same_record_by_construction (one turn row = one executed call + its result; loader emits both with one id)",
    "whowhen": "loader_assigned (AG: call_id = step index, result = next Computer_terminal reply; HC: open-call heuristic)",
}

# generic tool classes that may be printed for the private corpus; anything else is folded
SAFE_TOOLS = {"shell", "read", "write", "edit", "glob", "grep", "ls", "subagent", "webfetch", "websearch", "todo", "gui",
              "taskupdate", "taskcreate", "taskoutput", "tasklist", "taskstop", "toolsearch", "askuserquestion", "skill",
              "exitplanmode", "enterplanmode", "sendmessage", "notebookedit", "workflow", "monitor"}


def jload(e):
    if isinstance(e, str) and e:
        try:
            v = json.loads(e)
            return v if isinstance(v, dict) else {}
        except ValueError:
            return {}
    return {}


def safe_tool(t, private):
    t = t if isinstance(t, str) else "none"
    if not private:
        return t
    if t in SAFE_TOOLS:
        return t
    return "mcp" if t.startswith("mcp") else "other"


def id_reason(cid):
    if not isinstance(cid, str):
        return "null"
    if "REDACTED" in cid:
        return "redacted_id"
    if cid.startswith("synthetic:"):
        return "synthetic_id"
    return "other"


def load(corpus, pop):
    df = pd.read_parquet(os.path.join(CACHE, f"{corpus}_A.parquet"), columns=COLS)
    if corpus == "swechat":
        df = df.merge(pop, on="session_id", how="left")
    else:
        df["format"] = corpus
    df["text_empty"] = df["text"].isna() | (df["text"].str.len() == 0)
    df = df.drop(columns=["text"])
    na_sub = int(df["is_subagent"].isna().sum())
    df["is_subagent"] = df["is_subagent"].fillna(False).astype(bool)
    df["x"] = [jload(e) for e in df["extra"]]
    df = df.drop(columns=["extra"])
    df["is_compact"] = [x.get("subtype") == "compact_boundary" for x in df["x"]]
    df["is_sessionstart"] = [x.get("hookEvent") == "SessionStart" for x in df["x"]]
    df["stream"] = np.where(df["is_subagent"] & df["agent_id"].notna(), "a:" + df["agent_id"].fillna(""),
                            np.where(df["is_subagent"] & df["parent_call_id"].notna(), "p:" + df["parent_call_id"].fillna(""), "main"))
    df = df.sort_values(["session_id", "seq"], kind="stable").reset_index(drop=True)
    return df, na_sub


def annotate(df, corpus):
    """Return calls, results, keys tables with pairing counts and reasons."""
    calls = df[df.kind == "call"].copy()
    res = df[df.kind == "result"].copy()
    nres = res.dropna(subset=["call_id"]).groupby(["session_id", "call_id"]).size()
    ncall = calls.groupby(["session_id", "call_id"]).size()
    ck = list(zip(calls.session_id, calls.call_id))
    rk = list(zip(res.session_id, res.call_id))
    calls["n_res"] = [int(nres.get(k, 0)) for k in ck]
    calls["n_calls_key"] = [int(ncall.get(k, 0)) for k in ck]
    res["n_calls"] = [int(ncall.get(k, 0)) if isinstance(k[1], str) else 0 for k in rk]

    # sessions: result counts, first call/assistant seq
    sess_nres = res.groupby("session_id").size()
    first_ca = df[df.kind.isin(["call", "assistant"])].groupby("session_id").seq.min()
    groups = {s: g for s, g in df.groupby("session_id", sort=False)}
    call_sessions = calls.groupby("call_id").session_id.agg(lambda s: set(s))

    reasons = []
    for idx, c in calls[calls.n_res == 0].iterrows():
        x = c.x
        g = groups[c.session_id]
        later = g[(g.seq > c.seq) & (g.stream == c.stream)]
        if corpus == "swechat" and c.format == "cursor":
            r = "source_has_no_results"
        elif x.get("server_tool") is True:
            r = "server_side_tool"
        elif "unexecuted" in x:
            r = "never_executed_by_harness"
        elif int(sess_nres.get(c.session_id, 0)) == 0:
            r = "session_has_no_results"
        elif not later.kind.isin(["result", "user", "assistant"]).any():
            r = "stream_end"
        else:
            nr = later[later.kind == "result"]
            window = later[later.seq < nr.seq.min()] if len(nr) else later
            if window.is_compact.any():
                r = "compaction_before_next_result"
            elif window.is_sessionstart.any():
                r = "session_start_hook_before_next_result"
            elif corpus == "whowhen" and (window.kind == "call").any():
                r = "superseded_by_later_call"
            else:
                r = "other"
        reasons.append((idx, r))
    calls["unpaired_reason"] = None
    for idx, r in reasons:
        calls.at[idx, "unpaired_reason"] = r
    # nested events under an unpaired subagent call (the subagent ran but its parent result is missing)
    sub_parent = set(zip(df.loc[df.is_subagent & df.parent_call_id.notna(), "session_id"],
                         df.loc[df.is_subagent & df.parent_call_id.notna(), "parent_call_id"]))
    calls["has_nested_events"] = [(s, k) in sub_parent for s, k in ck]

    oreasons = []
    for idx, r_ in res[res.n_calls == 0].iterrows():
        if not isinstance(r_.call_id, str):
            r = "null_call_id"
        elif r_.seq < first_ca.get(r_.session_id, np.inf):
            r = "before_any_call_or_assistant_in_session"
        elif len(call_sessions.get(r_.call_id, set()) - {r_.session_id}) > 0:
            r = "call_id_is_call_in_other_session_same_split"
        else:
            r = "other"
        oreasons.append((idx, r))
    res["orphan_reason"] = None
    for idx, r in oreasons:
        res.at[idx, "orphan_reason"] = r

    keys = calls.drop_duplicates(["session_id", "call_id"], keep="first")[
        ["session_id", "call_id", "is_subagent", "format", "stratum", "n_res", "n_calls_key"]].copy()
    return calls, res, keys


def rate_block(sessions, num, den):
    """sessions: index of all sessions in the group; num/den: Series by session (missing -> 0)."""
    n = num.reindex(sessions, fill_value=0).astype(float).values
    d = den.reindex(sessions, fill_value=0).astype(float).values
    cr = stats.cluster_rate(n, d)
    with_den = d > 0
    k_aff = int(((n > 0) & with_den).sum())
    n_s = int(with_den.sum())
    p, lo, hi = stats.wilson(k_aff, n_s)
    cr["sessions_affected"] = {"k": k_aff, "n": n_s, "p": p, "lo": lo, "hi": hi}
    return cr


def group_metrics(df, calls, res, keys, private, sub_flag=None):
    """Metrics for one group (df etc. already filtered to the group's sessions)."""
    sessions = pd.Index(sorted(df.session_id.unique()))
    if sub_flag is not None:
        calls = calls[calls.is_subagent == sub_flag]
        res = res[res.is_subagent == sub_flag]
        keys = keys[keys.is_subagent == sub_flag]
    out = {"n_sessions_in_group": int(len(sessions)),
           "n_sessions_with_calls": int(calls.session_id.nunique()),
           "n_sessions_with_results": int(res.session_id.nunique()),
           "call_events": int(len(calls)), "result_events": int(len(res)), "distinct_call_keys": int(len(keys)),
           "paired_call_events": int((calls.n_res > 0).sum())}
    m = {}
    m["orphan_results"] = rate_block(sessions, res[res.n_calls == 0].groupby("session_id").size(), res.groupby("session_id").size())
    m["calls_without_result"] = rate_block(sessions, calls[calls.n_res == 0].groupby("session_id").size(), calls.groupby("session_id").size())
    m["duplicate_call_ids"] = rate_block(sessions, keys[keys.n_calls_key > 1].groupby("session_id").size(), keys.groupby("session_id").size())
    m["calls_with_multi_results"] = rate_block(sessions, keys[keys.n_res > 1].groupby("session_id").size(), keys.groupby("session_id").size())
    # structural-excluded variant
    cn = calls[~calls.unpaired_reason.isin(STRUCTURAL)]
    m["calls_without_result_excl_structural"] = rate_block(sessions, cn[cn.n_res == 0].groupby("session_id").size(),
                                                           cn.groupby("session_id").size())
    out["rates"] = m
    out["calls_without_result_distinct_keys"] = int((keys.n_res == 0).sum())
    out["duplicate_extra_call_events"] = int((keys.n_calls_key - 1).clip(lower=0).sum())
    out["multi_result_extra_result_events"] = int((keys.n_res - 1).clip(lower=0).sum())
    u = calls[calls.n_res == 0]
    out["unpaired_call_reasons"] = dict(Counter(u.unpaired_reason).most_common())
    out["unpaired_call_reasons_sessions"] = {r: int(g.session_id.nunique()) for r, g in u.groupby("unpaired_reason")}
    out["unpaired_calls_by_tool_top10"] = dict(Counter(safe_tool(t, private) for t in u.tool).most_common(10))
    out["unpaired_subagent_calls"] = int((u.tool == "subagent").sum())
    out["unpaired_subagent_calls_with_nested_events"] = int(((u.tool == "subagent") & u.has_nested_events).sum())
    o = res[res.n_calls == 0]
    out["orphan_reasons"] = dict(Counter(o.orphan_reason).most_common())
    out["orphan_markers"] = dict(Counter(str(x.get("marker")) for x in o.x).most_common())
    out["orphan_results_by_tool_top10"] = dict(Counter(safe_tool(t, private) for t in o.tool).most_common(10))
    out["duplicate_key_id_reasons"] = dict(Counter(id_reason(c) for c in keys[keys.n_calls_key > 1].call_id).most_common())
    out["multi_result_key_id_reasons"] = dict(Counter(id_reason(c) for c in keys[keys.n_res > 1].call_id).most_common())
    return out


def ordering_and_flags(calls, res):
    """Paired call/result consistency: result before call in seq; is_subagent mismatch."""
    m = calls[["session_id", "call_id", "seq", "is_subagent"]].merge(
        res[["session_id", "call_id", "seq", "is_subagent"]], on=["session_id", "call_id"], suffixes=("_c", "_r"))
    return {"paired_call_result_pairs": int(len(m)),
            "result_seq_before_call_seq": int((m.seq_r < m.seq_c).sum()),
            "is_subagent_mismatch_call_vs_result": int((m.is_subagent_c != m.is_subagent_r).sum())}


def id_provenance(calls, corpus):
    c = Counter()
    for cid, x in zip(calls.call_id, calls.x):
        if x.get("synthetic_call_id") or (isinstance(cid, str) and cid.startswith("synthetic:")):
            c["synthetic_loader_id"] += 1
        elif isinstance(cid, str) and cid.startswith("turn:"):
            c["loader_turn_fallback:" + str(x.get("call_id_fallback"))] += 1
        elif corpus == "whowhen" and isinstance(cid, str) and cid.startswith("step:"):
            c["loader_step_index"] += 1
        elif isinstance(cid, str) and "REDACTED" in cid:
            c["redacted_source_id"] += 1
        else:
            c["source_id"] += 1
    return dict(c.most_common())


def results_text_empty(sessions, res):
    return rate_block(sessions, res[res.text_empty].groupby("session_id").size(), res.groupby("session_id").size())


def linked_meta(df, calls):
    """meta events that carry parent_call_id: does it resolve to a call in the same session?"""
    ck = set(zip(calls.session_id, calls.call_id))
    out = {}
    for name, flag in (("is_subagent_false", False), ("is_subagent_true", True)):
        mt = df[(df.kind == "meta") & df.parent_call_id.notna() & (df.is_subagent == flag)]
        ok = np.array([(s, p) in ck for s, p in zip(mt.session_id, mt.parent_call_id)], dtype=bool)
        hc = Counter(str(x.get("has_call")) for x, o in zip(mt.x, ok) if not o)
        lab = ["|".join(str(x.get(k)) for k in ("entry_type", "type", "hookEvent")) for x in mt.x]  # enum fields only
        out[name] = {"meta_events_with_parent_call_id": int(len(mt)), "resolved_same_session": int(ok.sum()),
                     "unresolved": int((~ok).sum()), "unresolved_by_extra_has_call": dict(hc.most_common()),
                     "resolved_by_entry_type_type_hookEvent": dict(Counter(l for l, o in zip(lab, ok) if o).most_common(15)),
                     "unresolved_by_entry_type_type_hookEvent": dict(Counter(l for l, o in zip(lab, ok) if not o).most_common(15))}
    return out


def subagent_parent_links(df, all_calls_by_id):
    """Non-meta subagent events: does parent_call_id resolve to a call in the same session / another A session?"""
    sub = df[df.is_subagent & (df.kind != "meta")]
    pairs = sub.dropna(subset=["parent_call_id"])[["session_id", "parent_call_id"]].drop_duplicates()
    same = other = none = 0
    for s, p in zip(pairs.session_id, pairs.parent_call_id):
        ss = all_calls_by_id.get(p, set())
        if s in ss:
            same += 1
        elif ss:
            other += 1
        else:
            none += 1
    sess_null = (pd.Series(dtype=bool) if len(sub) == 0 else
                 sub.groupby("session_id").parent_call_id.apply(lambda v: bool(v.isna().all())).astype(bool))
    return {"subagent_nonmeta_events": int(len(sub)), "distinct_session_parent_pairs": int(len(pairs)),
            "parent_is_call_same_session": same, "parent_is_call_other_session_in_split_A": other,
            "parent_not_found_in_split_A": none,
            "sessions_with_subagent_events_all_parent_null": int(sess_null.sum()),
            "sessions_with_subagent_events": int(len(sess_null))}


def verdict(block):
    r = block["rates"]
    thr = PREREG["verdict_rule"]["threshold"]
    def v(cwr_key):
        if block["call_events"] == 0:
            return "no_tool_calls"
        if block["result_events"] == 0 or r[cwr_key]["den"] == 0:
            return "absent"
        his = [r[k]["hi"] for k in ("orphan_results", cwr_key, "duplicate_call_ids", "calls_with_multi_results")]
        return "usable" if all(h is None or h <= thr for h in his) else "partial"
    return {"verdict": v("calls_without_result"), "verdict_excl_structural": v("calls_without_result_excl_structural"),
            "binding_metrics_hi_gt_threshold": [k for k in ("orphan_results", "calls_without_result", "duplicate_call_ids",
                                                            "calls_with_multi_results")
                                                if r[k]["hi"] is not None and r[k]["hi"] > thr]}


def run_group(df, calls, res, keys, private, corpus):
    sessions = pd.Index(sorted(df.session_id.unique()))
    blk = {s: group_metrics(df, calls, res, keys, private, f) for s, f in SLICES.items()}
    blk["verdict"] = verdict(blk["all"])
    blk["ordering_and_flags"] = ordering_and_flags(calls, res)
    blk["call_id_provenance"] = id_provenance(calls, corpus)
    blk["results_text_null_or_empty"] = results_text_empty(sessions, res)
    blk["linked_meta"] = linked_meta(df, calls)
    ncall = calls.groupby("session_id").size()
    nores = ncall[~ncall.index.isin(res.session_id.unique())]
    blk["sessions_with_calls_but_no_results_call_counts"] = {"n_sessions": int(len(nores)),
                                                              "calls_per_session": sorted(int(v) for v in nores.values)}
    return blk


def cross_session_call_ids(calls):
    s = calls.groupby("call_id").session_id.nunique()
    multi = s[s > 1]
    sess = calls[calls.call_id.isin(multi.index)].session_id.nunique()
    return {"distinct_call_ids": int(len(s)), "call_ids_in_more_than_one_session": int(len(multi)),
            "sessions_involved": int(sess),
            "id_reasons": dict(Counter(id_reason(c) for c in multi.index).most_common())}


def aiv_cu_unexecuted(df, calls):
    """Provider calls the model issued that the harness never executed (extra.unexecuted_calls): no IR call event exists."""
    per = Counter()
    for s, x in zip(df.session_id, df.x):
        u = x.get("unexecuted_calls")
        if u:
            per[s] += len(u) if isinstance(u, list) else 1
    sessions = pd.Index(sorted(df.session_id.unique()))
    num = pd.Series(per, dtype=float)
    ncalls = calls.groupby("session_id").size()
    den = ncalls.reindex(sessions, fill_value=0) + num.reindex(sessions, fill_value=0)
    unpaired = calls[calls.n_res == 0].groupby("session_id").size().reindex(sessions, fill_value=0)
    by_stratum = {}
    strat = df.drop_duplicates("session_id").set_index("session_id").stratum
    for st in sorted(strat.unique()):
        ss = strat[strat == st].index
        by_stratum[st] = rate_block(ss, num.reindex(ss, fill_value=0), den.reindex(ss, fill_value=0))
    return {"unexecuted_provider_calls_total": int(sum(per.values())),
            "sessions_with_unexecuted": int(len(per)),
            "rate_over_ir_calls_plus_unexecuted": rate_block(sessions, num, den),
            "calls_without_result_incl_unexecuted_provider_calls": rate_block(sessions, unpaired + num.reindex(sessions, fill_value=0), den),
            "by_stratum": by_stratum}


# ---------------------------------------------------------------------------------------------------------------------
# Cited numbers (read from saved files; not recomputed)
# ---------------------------------------------------------------------------------------------------------------------
def cited():
    J = {}
    sb = json.load(open(os.path.join(BUILD, "swechat_build.json"), encoding="utf-8"))
    fp = sb["full_population_pass"]
    keep = ["files", "calls", "results", "results_without_call", "calls_without_result", "duplicate_call_ids",
            "synthetic_call_ids", "calls_subagent", "calls_nested_subagent", "calls_sidechain_toplevel", "calls_session_subagent"]
    J["swechat_full_population_pass"] = {
        "source": "analysis/out/build/swechat_build.json :: full_population_pass",
        "mode": fp["mode"], "files": fp["files"],
        "by_format": {f: {k: v.get(k) for k in keep} for f, v in fp["by_format"].items()},
        "totals": fp["totals"], "parser_exceptions": len(fp["parser_exceptions"]),
        "document_parse_not_ok": fp["document_parse_not_ok"], "cross_session_links": fp["cross_session_links"],
        "codex_end_records_without_call": {k: v for k, v in fp["by_format"]["codex"]["parse"].items() if k.endswith("_without_call")},
        "codex_exec_exit_never_shown_to_model": fp["by_format"]["codex"]["parse"].get("codex_exec_exit_never_shown_to_model"),
        "opencode_call_ids_redacted_or_missing": fp["by_format"]["opencode"]["parse"].get("opencode_call_ids_redacted_or_missing"),
    }
    cx = sb["crosscheck_conversations"]
    J["swechat_table_vs_raw_crosscheck"] = {
        "source": "analysis/out/build/swechat_build.json :: crosscheck_conversations",
        "definition": cx["definition"], "sampled_sessions": cx["sampled_sessions"],
        "sessions_absent_from_table": len(cx["sessions_absent_from_table"]),
        "by_format": cx["by_format"], "totals": cx["totals"]}
    sp = json.load(open(os.path.join(RECON, "swechat_scan_pinned.json"), encoding="utf-8"))
    J["swechat_table_recon_pinned"] = {
        "source": "analysis/out/recon/swechat_scan_pinned.json",
        **{k: sp[k] for k in ["rows", "sessions", "tool_use_distinct", "tool_result_distinct", "calls_with_result", "orphaned_results",
                              "hidden_subagent_tool_use", "hidden_subagent_tool_result", "hidden_paired",
                              "hidden_ids_also_in_tool_use_table", "orphans_matching_hidden_use"]},
        "roles_tool_use_rows": sp["roles"]["tool_use"], "roles_tool_result_rows": sp["roles"]["tool_result"],
        "tool_use_rows_by_agent": sp["tool_use_by_agent"]}
    txt = open(os.path.join(RECON, "swechat_compare.txt"), encoding="utf-8").read()
    m = re.search(r"orphan check, seeded sample of (\d+) sessions with orphans \((\d+) such sessions in total\)\s*\n\s*"
                  r"sessions without transcript file: (\d+); orphan ids checked: (\d+); found as a tool_use id in the raw file: (\d+); "
                  r"where: \{'top-level assistant': (\d+), 'inside progress/other': (\d+)\}", txt)
    assert m, "orphan-check line not found in swechat_compare.txt"
    J["swechat_table_orphans_in_raw_check"] = {
        "source": "analysis/out/recon/swechat_compare.txt (orphan check against pinned raw transcripts)",
        "sessions_sampled": int(m.group(1)), "table_sessions_with_orphans": int(m.group(2)),
        "sampled_sessions_without_transcript_file": int(m.group(3)), "orphan_ids_checked": int(m.group(4)),
        "found_as_tool_use_id_in_raw": int(m.group(5)), "found_in_top_level_assistant": int(m.group(6)),
        "found_inside_progress_or_other": int(m.group(7))}
    ht = open(os.path.join(RECON, "swechat_hidden.txt"), encoding="utf-8").read()
    m1 = re.search(r"orphaned results whose tool_use is found inside a metadata row of the same session: (\d+) / (\d+)", ht)
    m2 = re.search(r"orphaned results whose id also appears as a tool_result inside metadata rows: (\d+)", ht)
    assert m1 and m2
    J["swechat_table_orphans_vs_hidden_metadata"] = {
        "source": "analysis/out/recon/swechat_hidden.txt (run on the mirror; scan_pinned shows identical counts for pinned)",
        "orphans_whose_tool_use_is_in_metadata_row_same_session": int(m1.group(1)), "orphans_total": int(m1.group(2)),
        "orphans_whose_id_is_also_a_tool_result_inside_metadata": int(m2.group(1))}
    pc = json.load(open(os.path.join(PHASE_C, "swechat_tables.json"), encoding="utf-8"))
    J["swechat_table_dropped_tool_use_share_phase_c"] = {
        "source": "analysis/out/phase_c/swechat_tables.json :: followup.tool_call_count_vs_raw.pooled_dropped_share",
        **pc["followup"]["tool_call_count_vs_raw"]["pooled_dropped_share"]}
    # other corpora: population-level and split-A pairing counts from the build reports (consistency check only)
    for c in ("cc_local", "aiv_cc"):
        b = json.load(open(os.path.join(BUILD, f"{c}_build.json"), encoding="utf-8"))
        J[f"{c}_build_pairing"] = {"source": f"analysis/out/build/{c}_build.json :: full_corpus_ir.pairing, splits.A.pairing",
                                   "full_corpus": b["full_corpus_ir"]["pairing"], "split_A": b["splits"]["A"]["pairing"]}
    b = json.load(open(os.path.join(BUILD, "aiv_cu_build.json"), encoding="utf-8"))
    a = b["splits"]["A"]
    J["aiv_cu_build_split_A"] = {"source": "analysis/out/build/aiv_cu_build.json :: splits.A",
                                 **{k: a.get(k) for k in ["calls_without_result", "results_without_call", "call_ids_duplicated_within_session",
                                                          "call_id_source", "unexecuted_calls", "unexecuted_calls_by_shape",
                                                          "unexecuted_calls_on_talk_only_turns", "unexecuted_calls_on_action_turns",
                                                          "dup_message_rows"]}}
    b = json.load(open(os.path.join(BUILD, "whowhen_build.json"), encoding="utf-8"))
    J["whowhen_build_population"] = {"source": "analysis/out/build/whowhen_build.json :: per_split (population, 184 tasks)",
                                     **{s: {k: v.get(k) for k in ["sessions", "calls", "results", "calls_paired", "unpaired_calls",
                                                                  "unpaired_results", "duplicate_call_ids", "results_sharing_a_call_id"]}
                                        for s, v in b["per_split"].items()},
                                     "ag_call_unexecuted": {k: v for k, v in b["per_split"]["Algorithm-Generated"]["observations"].items()
                                                            if k.startswith("ag_call_unexecuted")}}
    return J


def derived(Jc):
    """Ratios and differences of cited counts. Census quantities (whole population or whole table): no sampling CI."""
    D = {}
    t = Jc["swechat_table_recon_pinned"]
    fp = Jc["swechat_full_population_pass"]["totals"]
    D["table_orphan_share_of_distinct_results"] = {"formula": "orphaned_results / tool_result_distinct",
                                                   "num": t["orphaned_results"], "den": t["tool_result_distinct"],
                                                   "value": t["orphaned_results"] / t["tool_result_distinct"], "kind": "census (whole table)"}
    D["raw_full_pass_results_without_call_share"] = {"formula": "results_without_call / results", "num": fp["results_without_call"],
                                                     "den": fp["results"], "value": fp["results_without_call"] / fp["results"],
                                                     "kind": "census (all 5,850 transcript files)"}
    D["raw_full_pass_calls_without_result_share"] = {"formula": "calls_without_result / calls", "num": fp["calls_without_result"],
                                                     "den": fp["calls"], "value": fp["calls_without_result"] / fp["calls"],
                                                     "kind": "census (all 5,850 transcript files)"}
    D["raw_full_pass_by_format"] = {}
    for f, v in Jc["swechat_full_population_pass"]["by_format"].items():
        D["raw_full_pass_by_format"][f] = {
            "calls_without_result_share": (v["calls_without_result"] / v["calls"]) if v["calls"] else None,
            "results_without_call_share": (v["results_without_call"] / v["results"]) if v["results"] else None,
            "calls": v["calls"], "results": v["results"]}
    D["table_vs_raw_calls_nonnested"] = {
        "formula": "raw top-level calls (calls - calls_nested_subagent) vs table tool_use_distinct; and raw nested calls vs table hidden ids",
        "raw_calls_total": fp["calls"], "raw_calls_nested_subagent": fp["calls_nested_subagent"],
        "raw_calls_not_nested": fp["calls"] - fp["calls_nested_subagent"],
        "table_tool_use_distinct": t["tool_use_distinct"], "table_hidden_subagent_tool_use_in_progress_rows": t["hidden_subagent_tool_use"],
        "note": "different session sets (table 5,825 sessions vs 5,850 files) and different nesting definitions; counts, not a matched comparison"}
    cx = Jc["swechat_table_vs_raw_crosscheck"]["totals"]
    D["crosscheck_sample_raw_minus_table_calls"] = {
        "formula": "raw_calls_in_present_sessions - table_rows_in_present_sessions (2200-session A+B sample, sessions present in table)",
        "value": cx["raw_calls_in_present_sessions"] - cx["table_rows_in_present_sessions"],
        "raw_calls_in_present_sessions": cx["raw_calls_in_present_sessions"],
        "table_rows_in_present_sessions": cx["table_rows_in_present_sessions"], "kind": "count in a sample; no ratio given"}
    return D


def main():
    pop = pd.read_parquet(os.path.join(CACHE, "swechat_population.parquet"), columns=["session_id", "format"])
    J = {"question": "A2 join completeness: orphan results, calls without result, duplicate call_ids, calls with >1 result; "
                     "per corpus, per swechat format, split by is_subagent; Phase A split only",
         "script": "analysis/probes/phase_a_a2.py",
         "inputs": {c: f"analysis/cache/{c}_A.parquet" for c in CORPORA},
         "columns_read": COLS, "prereg": PREREG, "pairing_mechanism": PAIRING_MECHANISM,
         "stats": {"seed": stats.SEED, "n_boot": stats.N_BOOT, "rate_ci": "stats.cluster_rate (session bootstrap, 95%)",
                   "sessions_affected_ci": "stats.wilson (95%)"},
         "by_corpus": {}, "swechat_by_format": {}, "by_stratum": {}, "cross_session_call_ids": {}, "subagent_parent_links": {},
         "load_notes": {}}
    for corpus in CORPORA:
        df, na_sub = load(corpus, pop)
        private = corpus == "cc_local"
        calls, res, keys = annotate(df, corpus)
        J["load_notes"][corpus] = {"rows": int(len(df)), "sessions": int(df.session_id.nunique()), "is_subagent_na_filled_false": na_sub,
                                   "kinds": {k: int(v) for k, v in df.kind.value_counts().items()}}
        J["by_corpus"][corpus] = run_group(df, calls, res, keys, private, corpus)
        J["cross_session_call_ids"][corpus] = cross_session_call_ids(calls)
        all_calls_by_id = calls.groupby("call_id").session_id.agg(lambda s: set(s)).to_dict()
        J["subagent_parent_links"][corpus] = subagent_parent_links(df, all_calls_by_id)
        J["by_stratum"][corpus] = {}
        for st, ss in df.groupby("stratum").session_id.unique().items():
            ss = set(ss)
            sel = lambda t: t[t.session_id.isin(ss)]
            g = group_metrics(sel(df), sel(calls), sel(res), sel(keys), private)
            J["by_stratum"][corpus][st] = {k: g[k] for k in ["n_sessions_in_group", "call_events", "result_events", "distinct_call_keys",
                                                             "rates", "unpaired_call_reasons", "orphan_reasons"]}
        if corpus == "swechat":
            for fmt, ss in df.groupby("format").session_id.unique().items():
                ss = set(ss)
                sel = lambda t: t[t.session_id.isin(ss)]
                blk = run_group(sel(df), sel(calls), sel(res), sel(keys), private, corpus)
                blk["subagent_parent_links"] = subagent_parent_links(sel(df), all_calls_by_id)
                nores = sel(calls).groupby("session_id").size().index.difference(sel(res).session_id.unique())
                blk["sessions_with_calls_but_no_results"] = {"n": int(len(nores)), "session_ids": sorted(nores.tolist())}
                J["swechat_by_format"][fmt] = blk
        if corpus == "aiv_cu":
            J["aiv_cu_unexecuted_provider_calls"] = aiv_cu_unexecuted(df, calls)
        del df, calls, res, keys
    J["cited"] = cited()
    J["derived_from_cited"] = derived(J["cited"])
    # consistency: this script's split-A counts vs the build reports' split-A counts
    cons = {}
    for c in ("cc_local", "aiv_cc"):
        a = J["cited"][f"{c}_build_pairing"]["split_A"]
        mine = J["by_corpus"][c]["all"]
        cons[c] = {"calls": [mine["call_events"], a["call_events"]], "results": [mine["result_events"], a["result_events"]],
                   "calls_without_result": [mine["rates"]["calls_without_result"]["num"], a["calls_without_result"]],
                   "results_without_call": [mine["rates"]["orphan_results"]["num"], a["results_without_call_in_session"]],
                   "duplicate_calls": [mine["duplicate_extra_call_events"], a["duplicate_call_events_same_session_id"]]}
    a = J["cited"]["aiv_cu_build_split_A"]
    mine = J["by_corpus"]["aiv_cu"]["all"]
    cons["aiv_cu"] = {"calls_without_result": [mine["rates"]["calls_without_result"]["num"], a["calls_without_result"]],
                      "results_without_call": [mine["rates"]["orphan_results"]["num"], a["results_without_call"]],
                      "unexecuted_provider_calls": [J["aiv_cu_unexecuted_provider_calls"]["unexecuted_provider_calls_total"], a["unexecuted_calls"]]}
    cons["_format"] = "[this script, build report]"
    J["consistency_with_build_reports_split_A"] = cons
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(J, fh, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print("wrote", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
