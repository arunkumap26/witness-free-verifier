"""Aggregate-only build statistics over an IR frame, shared by load_cc_local and load_aiv_cc.

Everything returned here is a count, a rate, a field name or a distribution. No text, args, commands
or paths from event content are ever copied into the output (cc_local is private).
"""
import json
import re
from collections import Counter, defaultdict

import pandas as pd

from analysis.lib import ir, stats

# keys in `extra` that carry a duration / timer. Matched on the key name, value must be numeric.
TIMER_RX = re.compile(r"(?i)(duration|elapsed|timeout|timedout|retryin|latency|seconds$|ms$)")


def _extra_dicts(df):
    out = []
    for s in df["extra"].tolist():
        if s is None or s is pd.NA:
            out.append(None)
            continue
        try:
            out.append(json.loads(s))
        except (TypeError, ValueError):
            out.append(None)
    return out


def _flatten(d, prefix=""):
    """One level of nesting is flattened (compactMetadata.durationMs, subagent_usage.*)."""
    flat = {}
    if not isinstance(d, dict):
        return flat
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict) and not prefix:
            flat.update(_flatten(v, key + "."))
        else:
            flat[key] = v
    return flat


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def tool_bucket(t, private=False):
    """Tool label for reports. private=True collapses every MCP tool to 'mcp__*' (server and function names of a
    private corpus can reveal what the user works on); otherwise names pass through."""
    if t is None or t is pd.NA:
        return None
    t = str(t)
    if private and t.startswith("mcp__"):
        return "mcp__*"
    return t


def pairing(df):
    """Call/result pairing within session, on call_id."""
    calls = df[df.kind == "call"][["session_id", "call_id", "ts"]]
    res = df[df.kind == "result"][["session_id", "call_id", "ts"]]
    out = {"call_events": int(len(calls)), "result_events": int(len(res)),
           "call_ids_unique": int(calls.drop_duplicates(["session_id", "call_id"]).shape[0]),
           "result_ids_unique": int(res.drop_duplicates(["session_id", "call_id"]).shape[0]),
           "duplicate_call_events_same_session_id": int(calls.duplicated(["session_id", "call_id"]).sum()),
           "duplicate_result_events_same_session_id": int(res.duplicated(["session_id", "call_id"]).sum()),
           "result_events_null_call_id": int(res.call_id.isna().sum())}
    c1 = calls.drop_duplicates(["session_id", "call_id"], keep="first")
    r1 = res.dropna(subset=["call_id"]).drop_duplicates(["session_id", "call_id"], keep="first")
    m = c1.merge(r1, on=["session_id", "call_id"], how="outer", suffixes=("_c", "_r"), indicator=True)
    out["paired"] = int((m["_merge"] == "both").sum())
    cs = df[df.kind == "call"].drop_duplicates(["session_id", "call_id"])[["session_id", "call_id", "seq"]]
    rs = df[df.kind == "result"].drop_duplicates(["session_id", "call_id"])[["session_id", "call_id", "seq"]]
    ms = cs.merge(rs, on=["session_id", "call_id"], suffixes=("_c", "_r"))
    out["paired_result_seq_before_call_seq"] = int((ms.seq_r < ms.seq_c).sum())
    out["calls_without_result"] = int((m["_merge"] == "left_only").sum())
    out["results_without_call_in_session"] = int((m["_merge"] == "right_only").sum())
    # results whose call_id exists in another session of the same frame (cross-session split)
    orphan = m[m["_merge"] == "right_only"]
    all_call_ids = set(calls.call_id.dropna().tolist())
    out["results_without_call_but_call_id_elsewhere_in_frame"] = int(orphan.call_id.isin(all_call_ids).sum())
    b = m[(m["_merge"] == "both") & m.ts_c.notna() & m.ts_r.notna()]
    tc = pd.to_datetime(b.ts_c, utc=True, format="ISO8601")
    tr = pd.to_datetime(b.ts_r, utc=True, format="ISO8601")
    d = (tr - tc).dt.total_seconds().to_numpy()
    out["paired_both_ts"] = int(len(d))
    out["paired_identical_ts"] = int((d == 0).sum())
    out["paired_negative_delta"] = int((d < 0).sum())
    out["delta_seconds"] = stats.describe(d) if len(d) else {"n": 0}
    return out


def build_stats(df, private=False):
    """Aggregate stats over an IR frame (one split or the full corpus). private=True: see tool_bucket."""
    if len(df) == 0:
        return {"rows": 0}
    out = {"rows": int(len(df)), "sessions": int(df.session_id.nunique()),
           "events_by_kind": {k: int(v) for k, v in df.kind.value_counts().items()},
           "ts_kind": {k: int(v) for k, v in df.ts_kind.value_counts().items()}}
    ts = df.ts.dropna()
    out["ts_fill"] = {"with_ts": int(len(ts)), "without_ts": int(df.ts.isna().sum())}
    out["ts_fractional_digits"] = {str(k): int(v) for k, v in sorted(Counter(ir.frac_digits(s) for s in ts.tolist()).items())}
    # ties: events whose (session, ts) is shared with at least one other event
    t = df[df.ts.notna()]
    grp = t.groupby(["session_id", "ts"]).size()
    out["ts_ties"] = {"tie_groups": int((grp > 1).sum()), "events_in_tie_groups": int(grp[grp > 1].sum()),
                      "largest_tie_group": int(grp.max()) if len(grp) else 0}
    # order check: seq order vs ts order (should be 0 after the loader's sort)
    inv = 0
    for _, g in t.sort_values(["session_id", "seq"]).groupby("session_id"):
        tt = pd.to_datetime(g.ts, utc=True, format="ISO8601").to_numpy()
        inv += int((tt[1:] < tt[:-1]).sum())
    out["adjacent_ts_inversions_in_seq_order"] = inv
    out["pairing"] = pairing(df)
    res = df[df.kind == "result"]
    ne = res.native_error
    out["native_error"] = {"results": int(len(res)), "filled": int(ne.notna().sum()),
                           "true": int((ne == True).sum()), "false": int((ne == False).sum()),  # noqa: E712
                           "fill_rate": float(ne.notna().mean()) if len(res) else None}
    out["exit_code_filled"] = int(df.exit_code.notna().sum())
    out["stderr_filled_results"] = int(res.stderr.notna().sum())
    # usage fill on model-output events
    um = {}
    for kind in ("assistant", "call"):
        sub = df[df.kind == kind]
        um[kind] = {"n": int(len(sub)), **{c: float(sub[c].notna().mean()) if len(sub) else None
                                           for c in ("usage_in", "usage_out", "usage_cache_read", "usage_cache_create",
                                                     "api_msg_id", "request_id", "model")}}
        um[kind]["api_msg_ids_unique"] = int(sub.api_msg_id.nunique())
    out["usage_fill"] = um
    # extra: markers, entry types, timers
    ex = _extra_dicts(df)
    kinds = df.kind.tolist()
    tools = [tool_bucket(x, private) for x in df.tool.tolist()]
    marker = Counter()
    entry_types = Counter()
    timer_by_kind = defaultdict(Counter)
    timer_by_tool = defaultdict(Counter)
    for e, k, tl in zip(ex, kinds, tools):
        if not isinstance(e, dict):
            continue
        if k == "result":
            marker[str(e.get("marker"))] += 1
        if k == "meta":
            sub = e.get("attachment_type") or e.get("subtype") or e.get("journal_type") or e.get("type")
            entry_types[f"{e.get('entry_type')}:{sub}"] += 1
        for key, v in _flatten(e).items():
            if TIMER_RX.search(key.split(".")[-1]) and _num(v):
                timer_by_kind[k][key] += 1
                if k == "result" and tl:
                    timer_by_tool[tl][key] += 1
    kind_n = df.kind.value_counts().to_dict()
    res_tool_n = Counter(tool_bucket(x, private) for x in res.tool.tolist())
    out["result_error_marker"] = dict(marker.most_common())
    keys_by_kind = defaultdict(Counter)
    for e, k in zip(ex, kinds):
        if isinstance(e, dict):
            keys_by_kind[k].update(e.keys())
    out["extra_key_fill_by_kind"] = {k: {key: {"present": int(n), "fill_rate": n / kind_n[k]} for key, n in c.most_common(40)}
                                     for k, c in keys_by_kind.items()}
    out["meta_entry_types"] = dict(entry_types.most_common())
    out["timer_keys_in_extra"] = {
        k: {key: {"present": int(n), "of": int(kind_n.get(k, 0)), "fill_rate": n / kind_n[k]} for key, n in c.most_common()}
        for k, c in timer_by_kind.items()}
    out["timer_keys_by_result_tool"] = {
        tl: {key: {"present": int(n), "of": int(res_tool_n.get(tl, 0)), "fill_rate": n / res_tool_n[tl] if res_tool_n.get(tl) else None}
             for key, n in c.most_common()}
        for tl, c in sorted(timer_by_tool.items(), key=lambda kv: -sum(kv[1].values()))}
    # subagent share
    sa = df.is_subagent.fillna(False).astype(bool)
    calls = df.kind == "call"
    # subagent events vs their parent call (same session): before the call / after the call's result
    sub = df[sa & df.parent_call_id.notna()]
    pcall = df[calls].drop_duplicates(["session_id", "call_id"]).set_index(["session_id", "call_id"]).ts
    pres = df[df.kind == "result"].drop_duplicates(["session_id", "call_id"]).set_index(["session_id", "call_id"]).ts
    keys = pd.MultiIndex.from_arrays([sub.session_id, sub.parent_call_id])
    ct = pd.to_datetime(pcall.reindex(keys).to_numpy(), utc=True, format="ISO8601")
    rt = pd.to_datetime(pres.reindex(keys).to_numpy(), utc=True, format="ISO8601")
    et = pd.to_datetime(sub.ts.to_numpy(), utc=True, format="ISO8601")
    has_ts = ~pd.isna(et)
    timing = {"subagent_events_with_parent_call_id": int(len(sub)), "with_ts": int(has_ts.sum()),
              "parent_call_in_same_session": int((~pd.isna(ct)).sum()),
              "parent_result_in_same_session": int((~pd.isna(rt)).sum()),
              "ts_before_parent_call": int((has_ts & (et < ct)).sum()),
              "ts_after_parent_result": int((has_ts & (et > rt)).sum())}
    ptool = df[calls].drop_duplicates(["session_id", "call_id"]).set_index(["session_id", "call_id"]).tool_raw
    pt = pd.Series(ptool.reindex(keys).to_numpy()).fillna("<none>").map(lambda t: tool_bucket(t, private)).to_numpy()
    timing["by_parent_tool"] = {str(t): {"events_with_ts": int((has_ts & (pt == t)).sum()),
                                         "ts_after_parent_result": int((has_ts & (pt == t) & (et > rt)).sum())}
                                for t in sorted(set(pt.tolist()))}
    out["subagent"] = {"timing_vs_parent": timing, "events": int(sa.sum()), "event_share": float(sa.mean()),
                       "calls": int((sa & calls).sum()), "call_share": float((sa & calls).sum() / max(1, calls.sum())),
                       "sessions_with_subagent_events": int(df[sa].session_id.nunique()),
                       "subagent_events_parent_call_id_filled": int(df[sa].parent_call_id.notna().sum()),
                       "subagent_events_agent_id_filled": int(df[sa].agent_id.notna().sum()),
                       "distinct_agent_ids": int(df[sa].agent_id.nunique())}
    # result tool distribution (privacy-safe buckets)
    out["results_by_tool_top"] = dict(Counter(res_tool_n).most_common(25))
    out["events_per_session"] = stats.describe(df.groupby("session_id").size().to_numpy())
    return out
