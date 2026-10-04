"""Phase C lens `correlations`: Spearman correlation scan over per-call and per-session features, within each corpus.

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_c_correlations
Reads (read-only): analysis/cache/<corpus>_{B,A}.parquet, analysis/cache/swechat_population.parquet,
                   analysis/cache/aiv_cu_sessions.parquet, analysis/cache/whowhen_labels.json
Writes RAW NUMBERS ONLY to analysis/out/phase_c/correlations.json. Interpretation: analysis/notes/correlations.md.
cc_local is private: only feature-level aggregates (correlations, counts, quantiles) leave this script.

UNITS (one scan each)
  Discovery: <corpus>/B for swechat, cc_local, aiv_cc, aiv_cu, whowhen (Phase B split).
  Replication: <corpus>/A (held-out Phase A split of the same corpus); swechat/B by content format (claude_code, opencode,
  codex: strata of the swechat discovery unit, NOT independent of it); aiv_cu population session table (78k sessions,
  session level only, the few features that table has).

FEATURES (definitions in FEATURE_DEFS, written to the JSON with their raw-column lineage)
  per call   one row per IR `call` event, joined to its first `result` (same session_id + call_id) and to its issuing
             response (same session_id + api_msg_id; aiv_cu: api_msg_id else the turn row uuid).
  per session one row per session_id.
  A feature that is constant or non-null in fewer than MIN_ROWS rows / MIN_SESSIONS sessions within a unit is dropped
  for that unit (listed in units.<u>.<level>.dropped).

STATISTICS
  Spearman rho = Pearson correlation of mid-ranks, computed per pair on the pairwise-complete rows (ranks taken within
  those rows). CIs: session-clustered bootstrap (lib/stats SEED, N_BOOT): sessions of the unit are resampled with
  replacement; for speed the replicate correlation is the Pearson correlation of the pair's FIXED mid-ranks over the
  resampled rows (ranks are not recomputed per replicate). exact_rerank_check reports, for the top pairs, a CI from a
  bootstrap that re-ranks inside every replicate, so the approximation can be judged.
  Call level also reports rho_within: Pearson correlation of the same ranks after subtracting each session's mean rank
  (the within-session part; removes between-session differences such as scaffold, model, task), and rho_within_tool:
  the same after subtracting each normalized tool name's mean rank (removes differences between tools).
  Pairs declared definitional before computing (PREREG.declared_definitional) stay in the raw top lists with a flag;
  the *_excl lists leave them out.
  Session level also reports rho_partial: partial correlation of the ranks given rank(n_events) (session size).
  Every CI is 95% percentile.

PREREG (fixed before any correlation was computed; see PREREG dict, copied to the JSON).
"""
import json, os, time, itertools
from collections import Counter

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pyarrow.compute as pc
from scipy.stats import rankdata

from analysis.lib import stats

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE = os.path.join(ROOT, "analysis", "cache")
OUT = os.path.join(ROOT, "analysis", "out", "phase_c", "correlations.json")
SEED = stats.SEED
N_BOOT = stats.N_BOOT

PREREG = {
    "top_k": {"value": 25, "reason": "task brief"},
    "eligibility_call_pair": {"value": "pairwise-complete rows >= 200 and sessions with such rows >= 10",
                              "reason": "a session-clustered CI needs several clusters; 200 rows keeps rare tool timers out"},
    "eligibility_session_pair": {"value": "pairwise-complete sessions >= 30", "reason": "smallest discovery unit (whowhen B) has 111"},
    "feature_drop": {"value": "dropped in a unit when <2 distinct non-null values, or non-null in <200 rows (calls) / <30 sessions",
                     "reason": "same thresholds as pair eligibility"},
    "replication_rule": {"value": "pair replicates in unit U when U's 95% CI excludes 0, has the discovery sign, and |rho_U| >= 0.1, "
                                  "using the same statistic (pooled / within / session / partial) as the discovery list",
                         "reason": "0.1 = smallest effect worth reporting at these n; fixed before computing"},
    "ranks": {"value": "average ranks (scipy rankdata 'average') on pairwise-complete rows", "reason": "standard Spearman"},
    "bootstrap": {"value": f"{N_BOOT} replicates, seed {SEED}, sessions resampled with replacement, fixed ranks",
                  "reason": "lib/stats conventions"},
    "exact_rerank_check": {"value": "top 10 pooled call pairs and top 10 session pairs per discovery unit, 200 replicates, re-ranked",
                           "reason": "check of the fixed-rank approximation"},
    "tool_classes": {"value": {"t_shell": ["shell", "code_exec", "computerterminal"], "t_read": ["read", "filesurfer"],
                               "t_edit": ["edit", "write"], "t_search": ["grep", "glob", "ls"],
                               "t_web": ["webfetch", "websearch", "websurfer"], "t_subagent": ["subagent"], "t_gui": ["gui"],
                               "t_mcp": "tool startswith 'mcp__'"},
                     "reason": "classes of the normalized IR tool name; Who&When agents folded into the nearest class"},
    "error_flag": {"value": "err = 1 when the call's result has native_error True or a non-null extra.marker (lib/ir.error_marker); "
                            "0 when a result exists otherwise; null when no result",
                   "reason": "union of the two failure signals the IR carries"},
    "declared_definitional": {"value": "two tool-class indicators; pos_idx-pos_rel; err-nerr; err_rate-nerr_rate; n_calls-n_results",
                              "reason": "mutually exclusive indicators or two codings of one quantity; flagged, excluded from *_excl lists"},
    "compaction_events": {"value": "meta extra.entry_type=='system' & subtype=='compact_boundary' (Claude Code, aiv_cc); "
                                   "meta event_msg type 'context_compacted' (Codex); meta part_type 'compaction' (OpenCode)",
                          "reason": "one count per harness compaction record"},
}

POST_HOC = {
    "within_guard": {"rule": "rho_within is null (within_degenerate=true) when the within-session rank variance of x or y is "
                             "<= 1e-9 x its total rank variance",
                     "why_added": "run 1 printed rho_within = +0.000 for whowhen pairs whose x is constant inside every session "
                                  "(float noise instead of 0/0); numerical guard only"},
    "independent_units": {"rule": "n_rep_independent_units counts only the A holdout of the discovery corpus and the B / A units of "
                                  "other corpora (plus the aiv_cu population table when the discovery unit is not aiv_cu/B); the swechat "
                                  "format strata are reported in per_unit but never counted (they are subsets of swechat/B)",
                          "why_added": "run 1-3 counted swechat/B and its format strata as separate replications for non-swechat "
                                       "discovery units, which double-counts one sample"},
    "followups": {"rule": "per discovery unit and swechat formats: (F1) native_error coverage of results by shell / non-shell; "
                          "(F2) share of calls whose issuing response has usage_out <= 10, overall and by is_subagent; "
                          "(F3) share of calls with gap_prev_ms == 0; (F4) arg_len vs gap_prev_ms on calls whose previous event "
                          "(seq-1) belongs to the same response (block streaming time) vs the rest, plus median arg chars per "
                          "second of gap; (F5) lag-1 error autocorrelation over calls with a non-null err, observed vs 20 "
                          "within-session permutations of err; (F6) model family (substring haiku/sonnet/opus of the "
                          "call's model column) of subagent vs main calls; (F7) gap_input recomputed within the call's own stream "
                          "(is_subagent + parent_call_id): negative-gap shares and its correlations with sub, resp_out, resp_think, "
                          "resp_ctx, arg_len, lat_ms",
                  "why_added": "run 1 top lists: nerr_rate|shell_share and t_shell|nerr (F1); resp_out|sub and aiv_cc resp_out "
                               "median 1 (F2); aiv_cu gap_prev_ms|resp_out sign opposite to other units (F3); arg_len|gap_prev_ms "
                               "replicating in 7-8 units (F4); err|prev_err positive pooled but negative within-session in "
                               "whowhen (F5); resp_out|sub, gap_input_ms|sub, resp_think|sub in swechat (F6); swechat gap_input_ms p5 is "
                               "negative in the profile (F7)",
                  "thresholds": {"resp_out_small": 10, "n_permutations": 20, "min_rows": 200}},
}

TOOL_CLASSES = {k: v for k, v in PREREG["tool_classes"]["value"].items() if isinstance(v, list)}

CALL_FEATURES = {
    "t_shell": "1 if tool in tool_classes.t_shell", "t_read": "1 if tool in tool_classes.t_read",
    "t_edit": "1 if tool in tool_classes.t_edit", "t_search": "1 if tool in tool_classes.t_search",
    "t_web": "1 if tool in tool_classes.t_web", "t_subagent": "1 if tool == subagent", "t_gui": "1 if tool == gui",
    "t_mcp": "1 if tool startswith mcp__",
    "lat_ms": "result ts - call ts in ms (ts_kind event/row_insert only; shared_turn and none -> null)",
    "hdur_ms": "harness-reported duration on the result: extra.durationMs | durationSeconds*1000 | totalDurationMs | duration_s*1000",
    "prog_s": "max elapsed seconds over progress meta events with parent_call_id == call_id (bash_progress/mcp_progress)",
    "res_len": "characters of the result text (null when no result)",
    "stderr_len": "characters of the result stderr column (null when the column is null)",
    "arg_len": "characters of the call args JSON string",
    "err": "error_flag (PREREG)",
    "nerr": "native_error of the result as 0/1 (null when native_error is null)",
    "prev_err": "err of the previous call in the session (call order = seq)",
    "same_tool_prev": "1 if tool equals the previous call's tool in the session",
    "pos_idx": "0-based ordinal of the call among the session's calls",
    "pos_rel": "pos_idx / (n_calls - 1) (null when the session has one call)",
    "gap_prev_ms": "call ts - ts of the previous event (seq order) that has a ts",
    "gap_input_ms": "call ts - max ts of earlier events of kind result/user/system (model turnaround)",
    "resp_out": "issuing response's usage_out: max over usage rows with the same (session_id, response key)",
    "resp_ctx": "issuing response's usage_in + usage_cache_read + usage_cache_create (max over its usage rows)",
    "resp_think": "sum of extra.thinking_chars (aiv_cu: extra.reasoning_chars) over assistant/call events of the issuing response; "
                  "the call's own value when it has no response key",
    "resp_ncalls": "number of call events sharing the issuing response key (null when no key)",
    "sub": "is_subagent as 0/1",
    "srv_ms": "aiv_cu only: extra.timing.server_timing_dur_ms of the issuing turn (Gemini server timing)",
}
SESSION_FEATURES = {
    "n_events": "IR rows in the session", "n_calls": "call events", "n_results": "result events",
    "n_user": "user events (human-authored)", "n_asst": "assistant text events",
    "err_rate": "sum(err) / count(err non-null) over the session's calls", "nerr_rate": "same for nerr",
    "n_tools": "distinct normalized tool names among calls",
    "dur_s": "max ts - min ts over events with a ts (seconds)",
    "n_resp": "distinct usage-bearing response keys", "tok_out": "sum of per-response max usage_out",
    "ctx_max": "max per-response context (usage_in + cache_read + cache_create)", "ctx_sum": "sum of per-response context",
    "n_compact": "compaction_events (PREREG)", "sub_share": "subagent calls / calls",
    "think_sum": "sum of thinking/reasoning chars over assistant/call events", "shell_share": "t_shell calls / calls",
    "res_len_med": "median res_len over the session's calls", "arg_len_med": "median arg_len",
    "lat_med": "median lat_ms", "gap_input_med": "median gap_input_ms", "calls_per_resp": "n_calls / distinct response keys of calls",
    "whowhen_is_correct": "Who&When label is_correct as 0/1 (labels file)", "whowhen_mistake_rel": "mistake_step / history_len (labels file)",
}
LINEAGE = {  # raw IR columns each feature reads (fact sheet for the shared-input check in the notes)
    "t_shell": ["tool"], "t_read": ["tool"], "t_edit": ["tool"], "t_search": ["tool"], "t_web": ["tool"], "t_subagent": ["tool"],
    "t_gui": ["tool"], "t_mcp": ["tool"], "lat_ms": ["ts"], "hdur_ms": ["extra"], "prog_s": ["extra", "parent_call_id"],
    "res_len": ["text"], "stderr_len": ["stderr"], "arg_len": ["args"], "err": ["native_error", "extra.marker(text)"],
    "nerr": ["native_error"], "prev_err": ["native_error", "extra.marker(text)"], "same_tool_prev": ["tool"],
    "pos_idx": ["seq"], "pos_rel": ["seq"], "gap_prev_ms": ["ts"], "gap_input_ms": ["ts"],
    "resp_out": ["usage_out", "api_msg_id"], "resp_ctx": ["usage_in", "usage_cache_read", "usage_cache_create", "api_msg_id"],
    "resp_think": ["extra.thinking_chars", "api_msg_id"], "resp_ncalls": ["api_msg_id"], "sub": ["is_subagent"],
    "srv_ms": ["extra.timing"],
    "n_events": ["rows"], "n_calls": ["kind"], "n_results": ["kind"], "n_user": ["kind"], "n_asst": ["kind"],
    "err_rate": ["native_error", "extra.marker", "kind"], "nerr_rate": ["native_error", "kind"], "n_tools": ["tool"],
    "dur_s": ["ts"], "n_resp": ["api_msg_id", "usage_in"], "tok_out": ["usage_out", "api_msg_id"],
    "ctx_max": ["usage_in", "usage_cache_read", "usage_cache_create"], "ctx_sum": ["usage_in", "usage_cache_read", "usage_cache_create", "api_msg_id"],
    "n_compact": ["extra"], "sub_share": ["is_subagent", "kind"], "think_sum": ["extra.thinking_chars"], "shell_share": ["tool", "kind"],
    "res_len_med": ["text"], "arg_len_med": ["args"], "lat_med": ["ts"], "gap_input_med": ["ts"], "calls_per_resp": ["api_msg_id", "kind"],
    "whowhen_is_correct": ["labels"], "whowhen_mistake_rel": ["labels"],
}

LOAD_COLS = ["session_id", "seq", "kind", "ts", "ts_kind", "tool", "call_id", "native_error", "usage_in", "usage_out",
             "usage_cache_read", "usage_cache_create", "api_msg_id", "uuid", "is_subagent", "parent_call_id", "model", "extra"]
EXTRA_KEYS = ("thinking_chars", "reasoning_chars", "marker", "durationMs", "durationSeconds", "totalDurationMs", "duration_s",
              "entry_type", "subtype", "type", "part_type", "elapsedTimeSeconds", "elapsedTimeMs")


# ----------------------------------------------------------------------------------------------------------------- loading
def load_events(corpus, split, sessions=None):
    """IR rows with text/args/stderr replaced by their lengths and needed extra keys pulled out."""
    path = os.path.join(CACHE, f"{corpus}_{split}.parquet")
    pf = pq.ParquetFile(path)
    parts = []
    for i in range(pf.metadata.num_row_groups):
        t = pf.read_row_group(i, columns=LOAD_COLS + ["text", "args", "stderr"])
        lens = {c: pc.utf8_length(t.column(c)) for c in ("text", "args", "stderr")}
        t = t.drop(["text", "args", "stderr"])
        df = t.to_pandas()
        for c, a in lens.items():
            df[c + "_len"] = a.to_pandas().astype("float64")
        parts.append(df)
        del t
    df = pd.concat(parts, ignore_index=True)
    del parts
    if sessions is not None:
        df = df[df.session_id.isin(sessions)].reset_index(drop=True)
    df = df.sort_values(["session_id", "seq"], kind="stable").reset_index(drop=True)
    # extra keys
    vals = {k: [None] * len(df) for k in EXTRA_KEYS}
    srv = [None] * len(df)
    for i, e in enumerate(df["extra"].values):
        if e is None or e is pd.NA:
            continue
        try:
            d = json.loads(e)
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        for k in EXTRA_KEYS:
            if k in d:
                vals[k][i] = d[k]
        tm = d.get("timing")
        if isinstance(tm, dict) and tm.get("server_timing_dur_ms") is not None:
            srv[i] = tm.get("server_timing_dur_ms")
    df = df.drop(columns=["extra"])
    for k in EXTRA_KEYS:
        df["x_" + k] = pd.Series(vals[k], dtype="object")
    df["x_srv"] = pd.to_numeric(pd.Series(srv, dtype="object"), errors="coerce")
    # timestamps
    tsk = df["ts_kind"].astype("object")
    t = pd.to_datetime(df["ts"].astype("object"), utc=True, format="ISO8601", errors="coerce")
    ms = (t - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds() * 1000.0
    df["ms"] = ms.where(tsk.isin(["event", "row_insert", "shared_turn"]))
    df["kind"] = df["kind"].astype("object")
    df["tool"] = df["tool"].astype("object")
    return df


def num(s):
    return pd.to_numeric(s, errors="coerce").astype("float64")


# ------------------------------------------------------------------------------------------------------------ features
def build_features(ev, corpus):
    ev = ev.copy()
    ev["sid"] = pd.factorize(ev["session_id"])[0]
    first = ev["sid"].ne(ev["sid"].shift(1))
    # previous ts in seq order (any event with ts), and max ts of earlier input events
    prev = ev["ms"].shift(1)
    prev[first] = np.nan
    ev["ms_prev"] = prev.groupby(ev["sid"]).ffill()
    inp = ev["ms"].where(ev["kind"].isin(["result", "user", "system"]))
    inp_max = inp.groupby(ev["sid"]).cummax()
    inp_max = inp_max.groupby(ev["sid"]).ffill()
    # on a call row (not an input kind) the forward-filled running max covers exactly the earlier input events
    ev["inp_max"] = inp_max
    # POST_HOC F7: same running max restricted to the event's own stream (main vs each nested subagent stream)
    skey = ev["is_subagent"].astype("object").astype(str) + "|" + ev["parent_call_id"].astype("object").fillna("").astype(str)
    gk = [ev["sid"], skey]
    ev["inp_max_stream"] = inp.groupby(gk).cummax().groupby(gk).ffill()
    # response key
    key = ev["api_msg_id"].astype("object")
    if corpus == "aiv_cu":
        key = key.where(key.notna(), "uuid:" + ev["uuid"].astype("object").fillna(""))
    ev["rkey"] = key
    pk = key.shift(1)
    pk[first] = None
    ev["prev_same_resp"] = (key.notna() & (pk == key) & prev.notna()).astype(bool)  # previous event (seq-1) has a ts and the same response key
    think_col = "x_reasoning_chars" if corpus == "aiv_cu" else "x_thinking_chars"
    ev["think"] = num(ev[think_col]).fillna(0.0)

    calls = ev[ev["kind"] == "call"].copy()
    res = ev[ev["kind"] == "result"].drop_duplicates(["session_id", "call_id"], keep="first")
    res = res[["session_id", "call_id", "ms", "ts_kind", "text_len", "stderr_len", "native_error", "x_marker",
               "x_durationMs", "x_durationSeconds", "x_totalDurationMs", "x_duration_s"]].rename(
        columns={"ms": "r_ms", "ts_kind": "r_tsk", "text_len": "res_len"})
    res["has_res"] = 1.0
    calls = calls.drop(columns=["stderr_len", "native_error", "x_marker", "x_durationMs", "x_durationSeconds",
                                "x_totalDurationMs", "x_duration_s"]).merge(res, on=["session_id", "call_id"], how="left")
    f = pd.DataFrame({"sid": calls["sid"].values, "session_id": calls["session_id"].values})
    tool = calls["tool"].fillna("")
    for cname, members in TOOL_CLASSES.items():
        f[cname] = tool.isin(members).astype("float64").values
    f["t_mcp"] = tool.str.startswith("mcp__").astype("float64").values
    ok_ts = calls["ts_kind"].astype("object").isin(["event", "row_insert"]) & calls["r_tsk"].astype("object").isin(["event", "row_insert"])
    f["lat_ms"] = (calls["r_ms"] - calls["ms"]).where(ok_ts).values
    hd = num(calls["x_durationMs"])
    hd = hd.fillna(num(calls["x_durationSeconds"]) * 1000.0).fillna(num(calls["x_totalDurationMs"])).fillna(num(calls["x_duration_s"]) * 1000.0)
    f["hdur_ms"] = hd.values
    # progress timers
    prog = ev[(ev["kind"] == "meta") & ev["parent_call_id"].notna() & ev["x_entry_type"].eq("progress")]
    if len(prog):
        el = num(prog["x_elapsedTimeSeconds"]).fillna(num(prog["x_elapsedTimeMs"]) / 1000.0)
        pm = pd.DataFrame({"session_id": prog["session_id"].values, "call_id": prog["parent_call_id"].astype("object").values,
                           "el": el.values}).dropna().groupby(["session_id", "call_id"])["el"].max().rename("prog_s").reset_index()
        f["prog_s"] = calls[["session_id", "call_id"]].astype("object").merge(pm, on=["session_id", "call_id"], how="left")["prog_s"].values
    else:
        f["prog_s"] = np.nan
    f["res_len"] = calls["res_len"].values
    f["stderr_len"] = calls["stderr_len"].values
    f["arg_len"] = calls["args_len"].values
    nb = calls["native_error"].astype("boolean")
    has = calls["has_res"].eq(1.0)
    err = (nb.fillna(False).astype(bool) | calls["x_marker"].notna()).astype("float64")
    f["err"] = err.where(has).values
    f["nerr"] = nb.astype("Float64").to_numpy(dtype="float64", na_value=np.nan)
    g = f.groupby("sid", sort=False)
    f["prev_err"] = g["err"].shift(1).values
    prev_tool = tool.groupby(calls["sid"].values).shift(1)
    f["same_tool_prev"] = (tool == prev_tool).astype("float64").where(prev_tool.notna()).values
    f["pos_idx"] = g.cumcount().astype("float64").values
    ncall = g["sid"].transform("size").astype("float64")
    f["pos_rel"] = (f["pos_idx"] / (ncall - 1)).where(ncall > 1).values
    f["gap_prev_ms"] = (calls["ms"] - calls["ms_prev"]).values
    f["gap_input_ms"] = (calls["ms"] - calls["inp_max"]).values
    # issuing response
    u = ev[ev["usage_in"].notna() & ev["rkey"].notna()]
    if len(u):
        ctx = num(u["usage_in"]) + num(u["usage_cache_read"]).fillna(0) + num(u["usage_cache_create"]).fillna(0)
        ru = pd.DataFrame({"session_id": u["session_id"].values, "rkey": u["rkey"].values, "resp_out": num(u["usage_out"]).values,
                           "resp_ctx": ctx.values}).groupby(["session_id", "rkey"]).max().reset_index()
    else:
        ru = pd.DataFrame(columns=["session_id", "rkey", "resp_out", "resp_ctx"])
    ac = ev[ev["kind"].isin(["assistant", "call"]) & ev["rkey"].notna()]
    rt = ac.groupby(["session_id", "rkey"])["think"].sum().rename("resp_think").reset_index()
    rn = ev[(ev["kind"] == "call") & ev["rkey"].notna()].groupby(["session_id", "rkey"]).size().rename("resp_ncalls").reset_index()
    ck = calls[["session_id", "rkey"]].astype("object")
    m = ck.merge(ru, on=["session_id", "rkey"], how="left").merge(rt, on=["session_id", "rkey"], how="left").merge(
        rn, on=["session_id", "rkey"], how="left")
    f["resp_out"] = num(m["resp_out"]).values
    f["resp_ctx"] = num(m["resp_ctx"]).values
    f["resp_think"] = num(m["resp_think"]).fillna(calls["think"].reset_index(drop=True)).values
    f["resp_ncalls"] = num(m["resp_ncalls"]).values
    f["sub"] = calls["is_subagent"].astype("boolean").astype("Float64").to_numpy(dtype="float64", na_value=np.nan)
    if corpus == "aiv_cu":
        # server timing sits on the turn's usage-bearing event (call or first assistant event of the row)
        st = ev[ev["x_srv"].notna()].groupby(["session_id", "rkey"])["x_srv"].max().rename("srv_ms").reset_index()
        f["srv_ms"] = num(ck.merge(st, on=["session_id", "rkey"], how="left")["srv_ms"]).values
    f["_tool"] = tool.values
    f["_prev_same_resp"] = calls["prev_same_resp"].astype(bool).values
    f["_model"] = calls["model"].astype("object").values
    f["_gap_input_stream"] = (calls["ms"] - calls["inp_max_stream"]).values
    f["tcode"] = pd.factorize(tool)[0].astype(np.int64)
    f["_rkey"] = calls["rkey"].values

    # ------------------------------------------------------------------ sessions
    sg = ev.groupby("session_id", sort=True)
    s = pd.DataFrame({"n_events": sg.size().astype("float64")})
    kc = ev.groupby(["session_id", "kind"]).size().unstack(fill_value=0)
    for kname, col in (("call", "n_calls"), ("result", "n_results"), ("user", "n_user"), ("assistant", "n_asst")):
        s[col] = kc[kname].astype("float64") if kname in kc.columns else 0.0
    fg = f.groupby("session_id")
    s["err_rate"] = fg["err"].mean()
    s["nerr_rate"] = fg["nerr"].mean()
    s["n_tools"] = f[f["_tool"] != ""].groupby("session_id")["_tool"].nunique().astype("float64")
    s["n_tools"] = s["n_tools"].where(s["n_calls"] > 0, 0.0)
    s["dur_s"] = (sg["ms"].max() - sg["ms"].min()) / 1000.0
    if len(ru):
        rg = ru.groupby("session_id")
        s["n_resp"] = rg.size().astype("float64")
        s["tok_out"] = rg["resp_out"].sum(min_count=1)
        s["ctx_max"] = rg["resp_ctx"].max()
        s["ctx_sum"] = rg["resp_ctx"].sum(min_count=1)
    else:
        for c in ("n_resp", "tok_out", "ctx_max", "ctx_sum"):
            s[c] = np.nan
    comp = ((ev["kind"] == "meta") & ev["x_entry_type"].eq("system") & ev["x_subtype"].eq("compact_boundary")) | \
           ((ev["kind"] == "meta") & ev["x_entry_type"].eq("event_msg") & (ev["x_type"].eq("context_compacted") | ev["x_subtype"].eq("context_compacted"))) | \
           ((ev["kind"] == "meta") & ev["x_part_type"].eq("compaction"))
    s["n_compact"] = comp.groupby(ev["session_id"]).sum().astype("float64")
    s["sub_share"] = fg["sub"].mean()
    s["think_sum"] = ev[ev["kind"].isin(["assistant", "call"])].groupby("session_id")["think"].sum()
    s["shell_share"] = fg["t_shell"].mean()
    s["res_len_med"] = fg["res_len"].median()
    s["arg_len_med"] = fg["arg_len"].median()
    s["lat_med"] = fg["lat_ms"].median()
    s["gap_input_med"] = fg["gap_input_ms"].median()
    nk = f[f["_rkey"].notna()].groupby("session_id")["_rkey"].nunique()
    s["calls_per_resp"] = (s["n_calls"] / nk).where(nk > 0)
    s = s.reset_index()
    s["sid"] = np.arange(len(s))
    f = f.drop(columns=["_tool", "_rkey"])  # _prev_same_resp stays for the post-hoc followups (not a scanned feature)
    return f, s


def comp_counter(ev):
    """Counts of the compaction record types found (for the JSON)."""
    m = ev["kind"] == "meta"
    return {"compact_boundary": int((m & ev["x_entry_type"].eq("system") & ev["x_subtype"].eq("compact_boundary")).sum()),
            "codex_context_compacted": int((m & ev["x_entry_type"].eq("event_msg") & (ev["x_type"].eq("context_compacted") | ev["x_subtype"].eq("context_compacted"))).sum()),
            "opencode_compaction_part": int((m & ev["x_part_type"].eq("compaction")).sum())}


# ------------------------------------------------------------------------------------------------------------ statistics
def boot_weights(n_sessions, n_boot=N_BOOT, seed=SEED):
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n_sessions, size=(n_boot, n_sessions))
    W = np.zeros((n_boot, n_sessions), dtype=np.float64)
    for b in range(n_boot):
        W[b] = np.bincount(idx[b], minlength=n_sessions)
    return W


def _corr_from_sums(n, sx, sy, sxx, syy, sxy):
    with np.errstate(invalid="ignore", divide="ignore"):
        cov = sxy / n - (sx / n) * (sy / n)
        vx = sxx / n - (sx / n) ** 2
        vy = syy / n - (sy / n) ** 2
        return cov / np.sqrt(vx * vy)


def _ci(a):
    a = np.asarray(a, dtype=float)
    ok = a[np.isfinite(a)]
    if len(ok) < 0.9 * len(a) or len(ok) == 0:
        return [None, None, int(len(a) - len(ok))]
    return [float(np.quantile(ok, 0.025)), float(np.quantile(ok, 0.975)), int(len(a) - len(ok))]


WITHIN_GUARD = 1e-9  # POST_HOC.within_guard


def pair_stats(x, y, g, n_sess, W, within=False, z=None, grp=None):
    """x, y: values (pairwise complete); g: session codes 0..n_sess-1. Returns dict with rho, CI, optional within/partial."""
    rx = rankdata(x) - (len(x) + 1) / 2.0  # centred mid-ranks (numerical stability; correlations unchanged)
    ry = rankdata(y) - (len(y) + 1) / 2.0
    one = np.ones_like(rx)
    S = np.vstack([np.bincount(g, weights=w, minlength=n_sess) for w in (one, rx, ry, rx * rx, ry * ry, rx * ry)]).T
    tot = S.sum(0)
    rho = float(_corr_from_sums(*tot))
    B = W @ S
    boots = _corr_from_sums(*B.T)
    out = {"n": int(len(x)), "n_sess": int((S[:, 0] > 0).sum()), "rho": rho, "ci": _ci(boots)}
    if within:
        n = S[:, 0]
        with np.errstate(invalid="ignore", divide="ignore"):
            cxx = np.where(n > 0, S[:, 3] - S[:, 1] ** 2 / np.maximum(n, 1), 0.0)
            cyy = np.where(n > 0, S[:, 4] - S[:, 2] ** 2 / np.maximum(n, 1), 0.0)
            cxy = np.where(n > 0, S[:, 5] - S[:, 1] * S[:, 2] / np.maximum(n, 1), 0.0)
            C = np.vstack([cxx, cyy, cxy]).T
            ct = C.sum(0)
            vx_tot, vy_tot = tot[3] - tot[1] ** 2 / tot[0], tot[4] - tot[2] ** 2 / tot[0]
            if ct[0] > WITHIN_GUARD * vx_tot and ct[1] > WITHIN_GUARD * vy_tot:
                out["rho_within"] = float(ct[2] / np.sqrt(ct[0] * ct[1]))
                CB = W @ C
                out["ci_within"] = _ci(CB[:, 2] / np.sqrt(CB[:, 0] * CB[:, 1]))
            else:
                out["rho_within"] = None
                out["within_degenerate"] = True
    if grp is not None:
        cnt = np.bincount(grp)
        with np.errstate(invalid="ignore", divide="ignore"):
            mx = np.bincount(grp, weights=rx) / np.maximum(cnt, 1)
            my = np.bincount(grp, weights=ry) / np.maximum(cnt, 1)
        tx, ty = rx - mx[grp], ry - my[grp]
        St = np.vstack([np.bincount(g, weights=w, minlength=n_sess) for w in (one, tx, ty, tx * tx, ty * ty, tx * ty)]).T
        out["rho_within_tool"] = float(_corr_from_sums(*St.sum(0)))
        out["ci_within_tool"] = _ci(_corr_from_sums(*(W @ St).T))
    if z is not None:
        rz = rankdata(z) - (len(z) + 1) / 2.0
        S2 = np.vstack([np.bincount(g, weights=w, minlength=n_sess) for w in (one, rx, ry, rz, rx * rx, ry * ry, rz * rz, rx * ry, rx * rz, ry * rz)]).T

        def partial(T):
            n, sx, sy, sz, sxx, syy, szz, sxy, sxz, syz = T
            rxy = _corr_from_sums(n, sx, sy, sxx, syy, sxy)
            rxz = _corr_from_sums(n, sx, sz, sxx, szz, sxz)
            ryz = _corr_from_sums(n, sy, sz, syy, szz, syz)
            with np.errstate(invalid="ignore", divide="ignore"):
                return (rxy - rxz * ryz) / np.sqrt((1 - rxz ** 2) * (1 - ryz ** 2))
        out["rho_partial"] = float(partial(S2.sum(0)))
        out["ci_partial"] = _ci(partial((W @ S2).T))
    return out


def exact_rerank_ci(x, y, g, n_sess, reps=200, seed=SEED):
    rng = np.random.default_rng(seed + 1)
    order = np.argsort(g, kind="stable")
    gs = g[order]
    bounds = np.searchsorted(gs, np.arange(n_sess + 1))
    xs, ys = x[order], y[order]
    vals = []
    for _ in range(reps):
        pick = rng.integers(0, n_sess, size=n_sess)
        idx = np.concatenate([np.arange(bounds[p], bounds[p + 1]) for p in pick])
        if len(idx) < 3:
            vals.append(np.nan)
            continue
        a, b = rankdata(xs[idx]), rankdata(ys[idx])
        with np.errstate(invalid="ignore", divide="ignore"):
            vals.append(np.corrcoef(a, b)[0, 1])
    return _ci(vals)


def profile(df, feats):
    out = {}
    for c in feats:
        v = df[c].astype("float64")
        nn = v.dropna()
        out[c] = {"non_null": int(len(nn)), "distinct": int(nn.nunique()), "sessions_non_null": int(df.loc[v.notna(), "sid"].nunique()),
                  **({k: round(val, 6) if isinstance(val, float) else val for k, val in stats.describe(nn.values, qs=(0.0, 0.05, 0.5, 0.95, 1.0)).items()} if len(nn) else {})}
    return out


def scan(df, feats, level, W, n_sess, min_rows, min_sess, size_col=None):
    keep, dropped = [], {}
    for c in feats:
        if c not in df.columns:
            continue
        v = df[c]
        nn = v.notna()
        if nn.sum() < min_rows or df.loc[nn, "sid"].nunique() < min_sess:
            dropped[c] = f"non_null {int(nn.sum())} rows / {int(df.loc[nn, 'sid'].nunique())} sessions"
            continue
        if v.dropna().nunique() < 2:
            dropped[c] = "constant"
            continue
        keep.append(c)
    g_all = df["sid"].values.astype(np.int64)
    pairs = {}
    for a, b in itertools.combinations(keep, 2):
        m = df[a].notna().values & df[b].notna().values
        zc = None
        if size_col and a != size_col and b != size_col:
            m = m & df[size_col].notna().values
        if m.sum() < min_rows:
            continue
        g = g_all[m]
        if len(np.unique(g)) < min_sess:
            continue
        x, y = df[a].values[m].astype(float), df[b].values[m].astype(float)
        if np.unique(x).size < 2 or np.unique(y).size < 2:
            continue
        if size_col and a != size_col and b != size_col:
            zc = df[size_col].values[m].astype(float)
        grp = df["tcode"].values[m] if level == "call" else None
        r = pair_stats(x, y, g, n_sess, W, within=(level == "call"), z=zc, grp=grp)
        r["declared"] = declared(a, b)
        pairs[f"{a}|{b}"] = r
    return keep, dropped, pairs


TOOL_IND = {"t_shell", "t_read", "t_edit", "t_search", "t_web", "t_subagent", "t_gui", "t_mcp"}
DECL = [{"pos_idx", "pos_rel"}, {"err", "nerr"}, {"err_rate", "nerr_rate"}, {"n_calls", "n_results"}]


def declared(a, b):
    return bool((a in TOOL_IND and b in TOOL_IND) or {a, b} in DECL)


def top(pairs, stat, k, excl=False):
    items = [(p, v) for p, v in pairs.items() if v.get(stat) is not None and np.isfinite(v.get(stat)) and not (excl and v.get("declared"))]
    items.sort(key=lambda t: -abs(t[1][stat]))
    return [p for p, _ in items[:k]]


def rnd(o, nd=4):
    if isinstance(o, float):
        return round(o, nd) if np.isfinite(o) else None
    if isinstance(o, dict):
        return {k: rnd(v, nd) for k, v in o.items()}
    if isinstance(o, list):
        return [rnd(v, nd) for v in o]
    return o


# ------------------------------------------------------------------------------------------------------------ main
CALL_FEATS = list(CALL_FEATURES)
SESS_FEATS = [c for c in SESSION_FEATURES]


def followups(f, n_sess, W):
    out = {}
    g = f["sid"].values.astype(np.int64)

    def crate(num_mask, den_mask):
        num_ = np.bincount(g, weights=num_mask.astype(float), minlength=n_sess)
        den_ = np.bincount(g, weights=den_mask.astype(float), minlength=n_sess)
        return stats.cluster_rate(num_, den_)
    has = f["res_len"].notna().values
    sh = f["t_shell"].values == 1
    ne = f["nerr"].values.astype(float)
    cov = {}
    for nm, m in (("shell", has & sh), ("non_shell", has & ~sh)):
        cov[nm] = {"results": int(m.sum()), "native_null": int((m & np.isnan(ne)).sum()), "native_true": int((m & (ne == 1)).sum()),
                   "native_false": int((m & (ne == 0)).sum()), "share_non_null": crate(m & ~np.isnan(ne), m)}
    out["F1_native_error_coverage"] = cov
    ro = f["resp_out"].values.astype(float)
    d = ~np.isnan(ro)
    small = d & (ro <= 10)
    sub = f["sub"].values.astype(float)
    out["F2_resp_out_le_10"] = {"all": crate(small, d), "subagent_calls": crate(small & (sub == 1), d & (sub == 1)),
                                "main_calls": crate(small & (sub == 0), d & (sub == 0))}
    gp = f["gap_prev_ms"].values.astype(float)
    dg = ~np.isnan(gp)
    out["F3_gap_prev_zero"] = crate(dg & (gp == 0), dg)
    ps = f["_prev_same_resp"].values.astype(bool)
    al = f["arg_len"].values.astype(float)
    out["F4_prev_event_same_response_share"] = crate(ps & dg, dg)
    f4 = {}
    for label, m in (("prev_same_response", ps & dg & (gp > 0) & ~np.isnan(al)), ("prev_other", ~ps & dg & (gp > 0) & ~np.isnan(al))):
        if m.sum() < 200 or len(np.unique(g[m])) < 10:
            f4[label] = {"n": int(m.sum()), "skipped": "fewer than 200 rows or 10 sessions"}
            continue
        r = pair_stats(al[m], gp[m], g[m], n_sess, W, within=True, grp=f["tcode"].values[m])
        rate = al[m] / (gp[m] / 1000.0)
        f4[label] = {**r, "arg_chars_per_s_median": stats.cluster_quantile(rate, g[m], 0.5, n_boot=200),
                     "gap_ms": stats.describe(gp[m], qs=(0.05, 0.5, 0.95))}
    out["F4_arg_len_vs_gap_prev"] = f4
    fam = pd.Series(f["_model"]).astype("object").fillna("").str.lower()
    famc = np.select([fam.str.contains("haiku"), fam.str.contains("sonnet"), fam.str.contains("opus"), fam == ""],
                     ["haiku", "sonnet", "opus", "none"], "other")
    f6 = {}
    for nm, m in (("subagent_calls", sub == 1), ("main_calls", sub == 0)):
        cnt = Counter(famc[m])
        f6[nm] = {"calls": int(m.sum()), "by_family": dict(sorted(cnt.items())),
                  "haiku_share": crate((famc == "haiku") & m, m) if m.sum() else None}
    out["F6_model_family_by_subagent"] = f6
    gi = f["gap_input_ms"].values.astype(float)
    gs = f["_gap_input_stream"].values.astype(float)
    f7 = {}
    for nm, m in (("subagent_calls", sub == 1), ("main_calls", sub == 0)):
        f7[nm] = {"gap_input_negative": crate(m & (gi < 0), m & ~np.isnan(gi)),
                  "gap_input_stream_negative": crate(m & (gs < 0), m & ~np.isnan(gs))}
    for other in ("sub", "resp_out", "resp_think", "resp_ctx", "arg_len", "lat_ms"):
        ov = f[other].values.astype(float)
        m = ~np.isnan(gs) & ~np.isnan(ov)
        if m.sum() >= 200 and len(np.unique(g[m])) >= 10 and np.unique(ov[m]).size > 1 and np.unique(gs[m]).size > 1:
            f7["gap_input_stream|" + other] = pair_stats(gs[m], ov[m], g[m], n_sess, W, within=True, grp=f["tcode"].values[m])
    out["F7_gap_input_stream"] = f7
    e = f[["sid", "err"]][f["err"].notna()]
    if len(e) >= 200 and e["err"].nunique() == 2:
        sidv = e["sid"].values.astype(np.int64)
        errv = e["err"].values.astype(float)

        def lag(v):
            prev = pd.Series(v).groupby(sidv).shift(1).values
            mm = ~np.isnan(prev)
            return pair_stats(v[mm], prev[mm], sidv[mm], n_sess, W, within=True)
        obs = lag(errv)
        rng = np.random.default_rng(SEED + 2)
        nul_p, nul_w = [], []
        for _ in range(N_PERM):
            order = np.lexsort((rng.random(len(errv)), sidv))
            r = lag(errv[order])
            nul_p.append(r["rho"])
            nul_w.append(r.get("rho_within") if r.get("rho_within") is not None else np.nan)
        out["F5_error_lag1"] = {"observed": {k: obs.get(k) for k in ("n", "n_sess", "rho", "ci", "rho_within", "ci_within")},
                                "perm_null_pooled": {"mean": float(np.nanmean(nul_p)), "min": float(np.nanmin(nul_p)), "max": float(np.nanmax(nul_p))},
                                "perm_null_within": {"mean": float(np.nanmean(nul_w)), "min": float(np.nanmin(nul_w)), "max": float(np.nanmax(nul_w))},
                                "n_permutations": N_PERM}
    return out


N_PERM = 20


def run_unit(name, ev, corpus, extra_sess=None, exact=False, follow=False):
    t0 = time.time()
    f, s = build_features(ev, corpus)
    if extra_sess is not None:
        s = s.merge(extra_sess, on="session_id", how="left")
    n_sess = int(s["sid"].max() + 1)
    # map call-level sid to session table sid
    sid_map = dict(zip(s["session_id"], s["sid"]))
    f["sid"] = f["session_id"].map(sid_map).astype(np.int64)
    W = boot_weights(n_sess)
    ck, cd, cp = scan(f, CALL_FEATS, "call", W, n_sess, 200, 10)
    sk, sd, sp = scan(s, SESS_FEATS, "session", W, n_sess, 30, 30, size_col="n_events")
    unit = {"n_sessions": n_sess, "n_calls": int(len(f)), "n_events": int(len(ev)),
            "call": {"features": ck, "dropped": cd, "profile": profile(f, ck), "n_pairs": len(cp)},
            "session": {"features": sk, "dropped": sd, "profile": profile(s, sk), "n_pairs": len(sp)},
            "compaction_records": comp_counter(ev)}
    pairs = {"call": cp, "session": sp}
    if exact:
        chk = {}
        for p in top(cp, "rho", 10):
            a, b = p.split("|")
            m = f[a].notna().values & f[b].notna().values
            chk["call:" + p] = {"approx_ci": cp[p]["ci"], "exact_ci": exact_rerank_ci(f[a].values[m].astype(float), f[b].values[m].astype(float),
                                                                                      f["sid"].values[m].astype(np.int64), n_sess)}
        for p in top(sp, "rho", 10):
            a, b = p.split("|")
            m = s[a].notna().values & s[b].notna().values
            chk["session:" + p] = {"approx_ci": sp[p]["ci"], "exact_ci": exact_rerank_ci(s[a].values[m].astype(float), s[b].values[m].astype(float),
                                                                                         s["sid"].values[m].astype(np.int64), n_sess)}
        unit["exact_rerank_check"] = chk
        dif = [max(abs(v["approx_ci"][0] - v["exact_ci"][0]), abs(v["approx_ci"][1] - v["exact_ci"][1])) for v in chk.values()
               if v["approx_ci"][0] is not None and v["exact_ci"][0] is not None]
        unit["exact_rerank_check_summary"] = {"n_pairs": len(chk), "n_compared": len(dif),
                                              "max_abs_bound_diff": float(max(dif)) if dif else None,
                                              "median_abs_bound_diff": float(np.median(dif)) if dif else None}
    if follow:
        unit["post_hoc_followups"] = followups(f, n_sess, W)
    unit["seconds"] = round(time.time() - t0, 1)
    print(f"  unit {name}: sessions {n_sess} calls {len(f)} call-pairs {len(cp)} session-pairs {len(sp)} ({unit['seconds']} s)", flush=True)
    return unit, pairs


def whowhen_labels(sessions):
    lab = json.load(open(os.path.join(CACHE, "whowhen_labels.json"), encoding="utf-8"))
    rows = []
    for sid in sessions:
        L = lab.get(sid)
        if not L:
            continue
        ic = {"True": 1.0, "False": 0.0}.get(str(L.get("is_correct")))
        try:
            ms = float(L.get("mistake_step")) / float(L.get("history_len"))
        except (TypeError, ValueError, ZeroDivisionError):
            ms = None
        rows.append({"session_id": sid, "whowhen_is_correct": ic, "whowhen_mistake_rel": ms})
    return pd.DataFrame(rows)


def aiv_cu_population_unit():
    s = pd.read_parquet(os.path.join(CACHE, "aiv_cu_sessions.parquet"),
                        columns=["session_id", "n_turns", "first_created_at", "last_created_at", "n_bash_turns", "n_gui_turns",
                                 "n_talk_only_turns", "n_synthetic_turns", "stratum"])
    t1 = pd.to_datetime(s["first_created_at"], utc=True, format="ISO8601", errors="coerce")
    t2 = pd.to_datetime(s["last_created_at"], utc=True, format="ISO8601", errors="coerce")
    d = pd.DataFrame({"session_id": s["session_id"], "n_events": s["n_turns"].astype(float),
                      "dur_s": (t2 - t1).dt.total_seconds(),
                      "n_calls": (s["n_bash_turns"] + s["n_gui_turns"]).astype(float)})
    nonsyn = (s["n_turns"] - s["n_synthetic_turns"]).astype(float)
    d["shell_share"] = (s["n_bash_turns"] / (s["n_bash_turns"] + s["n_gui_turns"])).where((s["n_bash_turns"] + s["n_gui_turns"]) > 0)
    d["talk_share"] = (s["n_talk_only_turns"] / nonsyn).where(nonsyn > 0)
    d["n_synthetic"] = s["n_synthetic_turns"].astype(float)
    d["sid"] = np.arange(len(d))
    feats = ["n_events", "dur_s", "n_calls", "shell_share", "talk_share", "n_synthetic"]
    W = boot_weights(len(d))
    k, dr, p = scan(d, feats, "session", W, len(d), 30, 30, size_col="n_events")
    defs = {"n_events": "n_turns (all turns incl. synthetic)", "dur_s": "last_created_at - first_created_at",
            "n_calls": "n_bash_turns + n_gui_turns", "shell_share": "bash / (bash + gui) turns",
            "talk_share": "talk-only turns / non-synthetic turns", "n_synthetic": "synthetic (harness bootstrap) turns"}
    unit = {"n_sessions": int(len(d)), "session": {"features": k, "dropped": dr, "profile": profile(d, k), "n_pairs": len(p)},
            "feature_defs": defs, "note": "turn-level population table; features differ in definition from the IR-based units"}
    return unit, {"session": p}


def main():
    t0 = time.time()
    pop = pd.read_parquet(os.path.join(CACHE, "swechat_population.parquet"), columns=["session_id", "format"])
    units, allpairs = {}, {}
    for corpus in ("whowhen", "aiv_cc", "cc_local", "aiv_cu", "swechat"):
        for split in ("B", "A"):
            print(f"{corpus}/{split} loading", flush=True)
            ev = load_events(corpus, split)
            extra = whowhen_labels(ev["session_id"].unique()) if corpus == "whowhen" else None
            name = f"{corpus}/{split}"
            u, p = run_unit(name, ev, corpus, extra, exact=(split == "B"), follow=(split == "B"))
            units[name], allpairs[name] = u, p
            if corpus == "swechat" and split == "B":
                fmt = pop.set_index("session_id")["format"]
                ev_fmt = ev["session_id"].map(fmt)
                for fm in ("claude_code", "opencode", "codex"):
                    sub = ev[ev_fmt.values == fm].reset_index(drop=True)
                    name2 = f"swechat/B:{fm}"
                    u, p = run_unit(name2, sub, corpus, follow=True)
                    units[name2], allpairs[name2] = u, p
                    del sub
            del ev
    print("aiv_cu population", flush=True)
    u, p = aiv_cu_population_unit()
    units["aiv_cu/population"], allpairs["aiv_cu/population"] = u, p

    discovery = [f"{c}/B" for c in ("swechat", "cc_local", "aiv_cc", "aiv_cu", "whowhen")]
    lists = {}
    for d in discovery:
        lists[d] = {"call_pooled": top(allpairs[d]["call"], "rho", PREREG["top_k"]["value"]),
                    "call_within": top(allpairs[d]["call"], "rho_within", PREREG["top_k"]["value"]),
                    "call_within_tool": top(allpairs[d]["call"], "rho_within_tool", PREREG["top_k"]["value"]),
                    "call_pooled_excl": top(allpairs[d]["call"], "rho", PREREG["top_k"]["value"], excl=True),
                    "call_within_excl": top(allpairs[d]["call"], "rho_within", PREREG["top_k"]["value"], excl=True),
                    "call_within_tool_excl": top(allpairs[d]["call"], "rho_within_tool", PREREG["top_k"]["value"], excl=True),
                    "session_excl": top(allpairs[d]["session"], "rho", PREREG["top_k"]["value"], excl=True),
                    "session_partial_excl": top(allpairs[d]["session"], "rho_partial", PREREG["top_k"]["value"], excl=True),
                    "session": top(allpairs[d]["session"], "rho", PREREG["top_k"]["value"]),
                    "session_partial": top(allpairs[d]["session"], "rho_partial", PREREG["top_k"]["value"])}
    stat_of = {"call_pooled": ("call", "rho", "ci"), "call_within": ("call", "rho_within", "ci_within"),
               "call_within_tool": ("call", "rho_within_tool", "ci_within_tool"),
               "call_pooled_excl": ("call", "rho", "ci"), "call_within_excl": ("call", "rho_within", "ci_within"),
               "call_within_tool_excl": ("call", "rho_within_tool", "ci_within_tool"),
               "session_excl": ("session", "rho", "ci"), "session_partial_excl": ("session", "rho_partial", "ci_partial"),
               "session": ("session", "rho", "ci"), "session_partial": ("session", "rho_partial", "ci_partial")}

    def verdict(v, sign, stat, cikey):
        if v is None or v.get(stat) is None or v.get(cikey) is None or v[cikey][0] is None:
            return "na"
        lo, hi = v[cikey][0], v[cikey][1]
        r = v[stat]
        if sign > 0 and lo > 0 and r >= 0.1:
            return "rep"
        if sign < 0 and hi < 0 and r <= -0.1:
            return "rep"
        if (sign > 0 and hi < 0) or (sign < 0 and lo > 0):
            return "opposite"
        return "not_rep"

    replication = {}
    for d in discovery:
        replication[d] = {}
        for lname, plist in lists[d].items():
            level, stat, cikey = stat_of[lname]
            rows = []
            for p in plist:
                v0 = allpairs[d][level][p]
                sign = np.sign(v0[stat])
                per = {}
                for u in allpairs:
                    if u == d or level not in allpairs[u]:
                        continue
                    v = allpairs[u][level].get(p)
                    if v is None:
                        a, b = p.split("|")
                        v = allpairs[u][level].get(f"{b}|{a}")
                    vd = verdict(v, sign, stat, cikey)
                    per[u] = {"v": vd, **({"rho": v.get(stat), "ci": v.get(cikey), "n": v["n"], "n_sess": v["n_sess"]} if v else {})}
                indep = [u for u in per if ":" not in u and not u.startswith(d.split("/")[0] + "/B") and not (d == "aiv_cu/B" and u == "aiv_cu/population")]
                rows.append({"pair": p, "rho": v0[stat], "ci": v0[cikey], "n": v0["n"], "n_sess": v0["n_sess"],
                             "rho_pooled": v0.get("rho"), "rho_within": v0.get("rho_within"), "rho_partial": v0.get("rho_partial"),
                             "rho_within_tool": v0.get("rho_within_tool"), "declared": v0.get("declared"),
                             "n_rep_units": sum(1 for u in per if per[u]["v"] == "rep"),
                             "n_rep_independent_units": sum(1 for u in indep if per[u]["v"] == "rep"),
                             "n_opposite_units": sum(1 for u in per if per[u]["v"] == "opposite"),
                             "n_units_with_pair": sum(1 for u in per if per[u]["v"] != "na"),
                             "n_independent_units_with_pair": sum(1 for u in indep if per[u]["v"] != "na"),
                             "independent_units": indep,
                             "holdout_A": per.get(d.replace("/B", "/A"), {}).get("v"), "per_unit": per})
            replication[d][lname] = rows

    out = {
        "lens": "correlations",
        "script": "analysis/probes/phase_c_correlations.py",
        "prereg": PREREG,
        "post_hoc": POST_HOC,
        "feature_defs": {"call": CALL_FEATURES, "session": SESSION_FEATURES},
        "feature_lineage": LINEAGE,
        "units": units,
        "top_lists": {d: {l: [{"pair": p, **allpairs[d][stat_of[l][0]][p]} for p in plist] for l, plist in lists[d].items()} for d in discovery},
        "replication": replication,
        "all_pairs": {u: {lvl: {p: [v["n"], v["n_sess"], v.get("rho"), *(v.get("ci") or [None, None, None])[:2],
                                    v.get("rho_within", v.get("rho_partial")),
                                    *((v.get("ci_within") or v.get("ci_partial") or [None, None, None])[:2]),
                                    v.get("rho_within_tool"), *((v.get("ci_within_tool") or [None, None, None])[:2]),
                                    int(bool(v.get("declared")))]
                                for p, v in pr.items()} for lvl, pr in allpairs[u].items()} for u in allpairs},
        "all_pairs_columns": ["n_rows", "n_sessions", "rho", "ci_lo", "ci_hi",
                              "rho_within (call) | rho_partial (session)", "ci_lo", "ci_hi",
                              "rho_within_tool (call)", "ci_lo", "ci_hi", "declared_definitional"],
        "seconds_total": round(time.time() - t0, 1),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(rnd(out), fh, ensure_ascii=False, indent=1)
    print("wrote", OUT, round(time.time() - t0, 1), "s")


if __name__ == "__main__":
    main()
