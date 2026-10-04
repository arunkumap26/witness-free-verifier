"""Phase C lens: internal accounting identities in the AI Village Claude Agent SDK stream.

Reads data/ai-village/claude_code_messages.jsonl.gz and claude_code_sessions.jsonl.gz directly (streamed; the probe
does not read analysis/cache). Writes RAW COUNTS ONLY to analysis/out/phase_c/aiv_accounting.json.
Interpretation lives in analysis/notes/aiv_accounting.md.

Unit of analysis = RUN, defined exactly as the aiv_cc loader does (analysis/loaders/load_aiv_cc.py docstring):
rows of one sdk_session_id sorted by (created_at microseconds, init-first, row id), split at every system/init row.
run_id = "<sdk_session_id>/r<NNN>". All CIs resample runs (lib/stats.py); pair-level rates are summed per run first.

Sections of the JSON:
  m1_durations      duration_ms / duration_api_ms vs created_at spans and call->result gaps
  m2_counts_usage   num_turns vs counted rows; result.usage / modelUsage vs per-response usage; hidden calls; cost identities
  m3_created_at     created_at semantics: gaps by transition, ties, ordering, tool-reported durations, sessions table
  m4_context        context-token growth between consecutive API responses vs chars appended ("token conservation")
PREREG holds tolerances / categories fixed before outcomes were inspected. POST_HOC holds rules added after the first
run of this script (each reported next to the un-ruled version).

Run:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_c_aiv_accounting
Env:  AIV_ACC_CACHE=<path.pkl>  optional pickle of the extracted compact rows (scratch speed-up; never under data/).
"""
import gzip, json, os, pickle, hashlib, bisect
from collections import Counter, defaultdict
from datetime import datetime, timezone

import numpy as np

from analysis.lib import stats

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.environ.get("AIV_DATA", r"C:\Swarms\data\ai-village")
OUT = os.path.join(ROOT, "analysis", "out", "phase_c", "aiv_accounting.json")
SEED = stats.SEED

PREREG = {
    "cost_abs_tol_usd": {"value": 1e-6, "reason": "costUSD values carry <=8 decimals; 1e-6 USD absorbs float summation error only"},
    "cost_fit_tol": {"value": "max(1e-6 USD, 1e-6 * cost)", "reason": "implied-price reproduction: float error only, not model error"},
    "duration_inequalities": {"value": "tested exactly (tolerance 0 ms)", "reason": "slack distributions are reported instead of a tolerance"},
    "gap_bins_ms": {"value": [1, 10, 100, 1000], "reason": "decade bins chosen as descriptive edges, not tuned"},
    "context_pair_categories": {"value": "compact = compact_boundary row between the two responses; image = >=1 image block appended; "
                                         "clean = neither", "reason": "images were stripped from the export ([IMAGE_REMOVED]) so their "
                                                                      "tokens have no chars; compaction replaces context"},
    "context_measure": {"value": "input_tokens + cache_read_input_tokens + cache_creation_input_tokens of the response's first row",
                        "reason": "these three fields are constant across rows of one response (checked in m2); output_tokens is not"},
    "thinking_variants": {"value": ["with_thinking_chars", "without_thinking_chars"],
                          "reason": "whether earlier thinking stays in context is not stated in the data; both variants reported"},
    "tool_use_chars": {"value": "len(name) + len(json.dumps(input, ensure_ascii=False, separators=(',',':')))",
                       "reason": "fixed char measure for tool_use blocks; serialization the API uses is unknown"},
    "price_fit": {"value": "per model, least squares costUSD ~ inputTokens + outputTokens + cacheReadInputTokens + "
                           "cacheCreationInputTokens (+ webSearchRequests if nonzero), no intercept, all result rows listing the model",
                  "reason": "prices are not recorded in the data; implied coefficients are estimated from the data itself, no outside prices"},
    "min_pairs_per_tool": {"value": 30, "reason": "per-tool breakdowns only where a median with a CI is meaningful"},
}
POST_HOC = {
    "attributable_result": {
        "rule": "a result row is attributed to the run it falls in unless subtype == error_during_execution and num_turns == 0 "
                "and duration_ms == 0 (failed resume: 'No conversation found ...', zero cost)",
        "why_added": "first run showed 3 runs whose only result row was such a failed-resume result appended after a long run "
                     "that had no result of its own; it produced duration-vs-span slack of -7e6..-1.2e7 ms",
        "reporting": "m1 reports the key inequalities under both the raw rule and this rule"},
    "zero_usage_responses": {
        "rule": "API responses whose first-row input+cache_read+cache_creation == 0 are excluded from context pairs and counted",
        "why_added": "first run showed clean pairs with context dropping to exactly 0 (synthetic/error responses)"},
    "extended_linear_fit": {
        "rule": "context delta ~ user_chars + assistant_visible_chars + thinking_chars + n_tool_use + intercept",
        "why_added": "the pre-planned 3-term fit had a ~237-token intercept; a per-tool-call overhead term was added after seeing it "
                     "(n_tool_results was dropped: it equals n_tool_use in almost every clean pair, making the two collinear)"},
    "unaccounted_response_match": {
        "rule": "for runs whose result.usage (input, cache_read, cache_creation) is below the stream sum and not all zero, test whether "
                "exactly one logged response's usage equals the deficit in all three fields",
        "why_added": "first run showed result.usage < stream sum in 15 runs"},
}


# ----------------------------------------------------------------------------------------------------------------- utils
def ts_us(s):
    s = str(s).strip().replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1]
    if "+" in s[10:]:
        s = s[: 10 + s[10:].index("+")]
    if "." in s:
        a, b = s.split(".", 1)
        s = a + "." + (b + "000000")[:6]
    dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    return int(dt.timestamp()) * 1_000_000 + dt.microsecond


def jchars(x):
    return len(json.dumps(x, ensure_ascii=False, separators=(",", ":")))


def wil(k, n):
    p, lo, hi = stats.wilson(k, n)
    return {"k": int(k), "n": int(n), "p": p, "lo": lo, "hi": hi}


def run_rate(num, den, sids):
    """Pooled ratio of per-item values, clustered by run: sum per run first, then lib.stats.cluster_rate."""
    a, b = defaultdict(float), defaultdict(float)
    for x, y, s in zip(num, den, sids):
        a[s] += float(x); b[s] += float(y)
    keys = sorted(b)
    return stats.cluster_rate([a[k] for k in keys], [b[k] for k in keys])


def per_run_rate(num, den):
    """Already one entry per run."""
    return stats.cluster_rate(num, den)


def cq(values, sids, q):
    return stats.cluster_quantile(values, sids, q)


def desc(values):
    return stats.describe(values)


def qset(values, sids, qs=(0.05, 0.25, 0.5, 0.75, 0.95)):
    if len(values) == 0:
        return {}
    return {f"p{int(q * 100)}": cq(values, sids, q) for q in qs}


def cluster_corr(x, y, sids, method="spearman", n_boot=stats.N_BOOT, seed=SEED):
    """Correlation with a run-clustered bootstrap 95% CI."""
    from scipy.stats import spearmanr, pearsonr
    x = np.asarray(x, float); y = np.asarray(y, float); s = np.asarray(sids)
    if len(x) < 4 or len(set(x)) < 2 or len(set(y)) < 2:
        return {"method": method, "r": None, "lo": None, "hi": None, "n": int(len(x)), "n_sessions": int(len(set(s)))}
    f = (lambda a, b: spearmanr(a, b).statistic) if method == "spearman" else (lambda a, b: pearsonr(a, b).statistic)
    r = float(f(x, y))
    uniq, inv = np.unique(s, return_inverse=True)
    idx_by = [np.where(inv == i)[0] for i in range(len(uniq))]
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(n_boot):
        pick = rng.integers(0, len(uniq), size=len(uniq))
        ii = np.concatenate([idx_by[i] for i in pick])
        if len(set(x[ii])) > 1 and len(set(y[ii])) > 1:
            boots.append(f(x[ii], y[ii]))
    return {"method": method, "r": r, "lo": float(np.quantile(boots, 0.025)) if boots else None,
            "hi": float(np.quantile(boots, 0.975)) if boots else None, "n": int(len(x)), "n_sessions": int(len(uniq))}


def binned(values, edges):
    v = np.asarray(values, float)
    out = {"n": int(len(v))}
    for e in edges:
        out[f"lt_{e}"] = int((v < e).sum())
    out[f"ge_{edges[-1]}"] = int((v >= edges[-1]).sum())
    return out


def hash_half(s):
    return int(hashlib.sha1(s.encode()).hexdigest(), 16) % 2 == 0


# ------------------------------------------------------------------------------------------------------------ extraction
def u_tuple(u):
    u = u or {}
    cc = u.get("cache_creation") or {}
    return (u.get("input_tokens"), u.get("output_tokens"), u.get("cache_read_input_tokens"), u.get("cache_creation_input_tokens"),
            cc.get("ephemeral_5m_input_tokens"), cc.get("ephemeral_1h_input_tokens"))


def extract_row(r):
    c = r.get("content") or {}
    mt, sub = r["message_type"], r.get("message_subtype")
    rec = {"sdk": r["sdk_session_id"], "ts": ts_us(r["created_at"]), "rid": r["id"], "mt": mt, "sub": sub,
           "csid": c.get("session_id"), "uuid": c.get("uuid"), "ptu": c.get("parent_tool_use_id"),
           "has_parent_uuid": ("parentUuid" in c) or ("parent_uuid" in c), "muuid": r.get("message_uuid")}
    if mt == "assistant":
        m = c.get("message") or {}
        rec["mid"] = m.get("id"); rec["model"] = m.get("model"); rec["u"] = u_tuple(m.get("usage"))
        rec["stop"] = m.get("stop_reason"); rec["err"] = c.get("error")
        blocks = []
        for b in m.get("content") or []:
            t = b.get("type")
            if t == "text":
                blocks.append(("text", len(b.get("text") or ""), None, None))
            elif t == "thinking":
                blocks.append(("thinking", len(b.get("thinking") or ""), None, None))
            elif t == "tool_use":
                blocks.append(("tool_use", len(b.get("name") or "") + jchars(b.get("input")), b.get("id"), b.get("name")))
            else:
                blocks.append((str(t), jchars(b), None, None))
        rec["blocks"] = blocks
    elif mt == "user":
        m = c.get("message") or {}
        cont = m.get("content")
        trs, txt, nimg = [], 0, 0
        if isinstance(cont, str):
            txt += len(cont)
        else:
            for b in cont or []:
                t = b.get("type")
                if t == "tool_result":
                    cc = b.get("content")
                    ch, ni = 0, 0
                    if isinstance(cc, str):
                        ch = len(cc)
                    else:
                        for x in cc or []:
                            if x.get("type") == "text":
                                ch += len(x.get("text") or "")
                            elif x.get("type") == "image":
                                ni += 1
                            else:
                                ch += jchars(x)
                    trs.append((b.get("tool_use_id"), ch, ni, bool(b.get("is_error"))))
                elif t == "text":
                    txt += len(b.get("text") or "")
                elif t == "image":
                    nimg += 1
                else:
                    txt += jchars(b)
        rec["trs"] = trs; rec["txt"] = txt; rec["nimg"] = nimg; rec["synth"] = bool(c.get("isSynthetic"))
        tur = c.get("tool_use_result")
        dur = None; durkind = None
        if isinstance(tur, dict):
            if isinstance(tur.get("durationMs"), (int, float)):
                dur, durkind = float(tur["durationMs"]), "durationMs"
            elif isinstance(tur.get("durationSeconds"), (int, float)):
                dur, durkind = float(tur["durationSeconds"]) * 1000.0, "durationSeconds"
        rec["tdur"] = dur; rec["tdurk"] = durkind
    elif mt == "system":
        rec["status"] = c.get("status")
        cm = c.get("compact_metadata") or {}
        rec["pre_tokens"] = cm.get("pre_tokens"); rec["trigger"] = cm.get("trigger")
        if sub == "init":
            rec["model"] = c.get("model"); rec["version"] = c.get("claude_code_version"); rec["perm"] = c.get("permissionMode")
            rec["ntools"] = len(c.get("tools") or [])
    elif mt == "result":
        for k in ("duration_ms", "duration_api_ms", "num_turns", "total_cost_usd", "is_error", "subtype", "stop_reason"):
            rec[k] = c.get(k)
        u = c.get("usage") or {}
        rec["u"] = u_tuple(u)
        stu = u.get("server_tool_use") or {}
        rec["u_web_search"] = stu.get("web_search_requests"); rec["u_web_fetch"] = stu.get("web_fetch_requests")
        rec["modelUsage"] = c.get("modelUsage") or {}
        rec["n_denials"] = len(c.get("permission_denials") or [])
        rec["errors"] = [str(e)[:120] for e in (c.get("errors") or [])]
    return rec


def load_rows():
    cache = os.environ.get("AIV_ACC_CACHE")
    if cache and os.path.exists(cache):
        with open(cache, "rb") as fh:
            return pickle.load(fh)
    rows = []
    with gzip.open(os.path.join(DATA, "claude_code_messages.jsonl.gz"), "rt", encoding="utf-8") as fh:
        for line in fh:
            rows.append(extract_row(json.loads(line)))
    sess = []
    with gzip.open(os.path.join(DATA, "claude_code_sessions.jsonl.gz"), "rt", encoding="utf-8") as fh:
        for line in fh:
            s = json.loads(line)
            sess.append({"sdk": s["sdk_session_id"], "ts": ts_us(s["created_at"]), "upd": ts_us(s["updated_at"]) if s.get("updated_at") else None})
    out = (rows, sess)
    if cache:
        with open(cache, "wb") as fh:
            pickle.dump(out, fh, protocol=pickle.HIGHEST_PROTOCOL)
    return out


def is_init(r):
    return r["mt"] == "system" and r["sub"] == "init"


def segment(rows):
    by = defaultdict(list)
    for r in rows:
        by[r["sdk"]].append(r)
    runs = []
    for sdk, lst in by.items():
        lst.sort(key=lambda r: (r["ts"], 0 if is_init(r) else 1, r["rid"]))
        cur, idx = None, -1
        for r in lst:
            if is_init(r):
                idx += 1
                cur = {"run_id": f"{sdk}/r{idx:03d}", "sdk": sdk, "idx": idx, "rows": []}
                runs.append(cur)
            if cur is None:
                cur = {"run_id": f"{sdk}/pre", "sdk": sdk, "idx": -1, "rows": []}
                runs.append(cur)
            cur["rows"].append(r)
    return runs


def derive(run):
    rows = run["rows"]
    resp, order, call_ts, res_ts, call_name = {}, [], {}, {}, {}
    for i, r in enumerate(rows):
        if r["mt"] == "assistant":
            mid = r["mid"]
            if mid not in resp:
                resp[mid] = {"mid": mid, "first_i": i, "last_i": i, "first_ts": r["ts"], "last_ts": r["ts"], "us": [], "rows": [],
                             "model": r["model"], "text": 0, "thinking": 0, "tool_use": 0, "other": 0, "n_tool_use": 0,
                             "tool_ids": [], "tool_names": []}
                order.append(mid)
            d = resp[mid]
            d["last_i"] = i; d["last_ts"] = r["ts"]; d["us"].append(r["u"]); d["rows"].append(i)
            for (t, ch, tid, name) in r["blocks"]:
                d[t if t in ("text", "thinking", "tool_use") else "other"] += ch
                if t == "tool_use":
                    d["n_tool_use"] += 1; d["tool_ids"].append(tid); d["tool_names"].append(name)
                    call_ts[tid] = r["ts"]; call_name[tid] = name
        elif r["mt"] == "user":
            for (tid, ch, ni, ie) in r["trs"]:
                res_ts[tid] = r["ts"]
    run.update(resp=resp, order=order, call_ts=call_ts, res_ts=res_ts, call_name=call_name,
               results=[r for r in rows if r["mt"] == "result"], init=rows[0] if rows and is_init(rows[0]) else None)
    return run


def attributable(x):
    return not (x["subtype"] == "error_during_execution" and (x["num_turns"] or 0) == 0 and (x["duration_ms"] or 0) == 0)


def single_result_runs(runs, rule):
    """Runs whose result rows (under rule) are exactly one, it is the run's last such row, and the run has >=1 API response."""
    out = []
    for r in runs:
        res = r["results"] if rule == "raw" else [x for x in r["results"] if attributable(x)]
        if len(res) == 1 and r["order"]:
            if rule == "raw" and r["rows"][-1]["mt"] != "result":
                continue
            out.append((r, res[0]))
    return out


def union_ms(intervals):
    if not intervals:
        return 0.0
    iv = sorted(intervals)
    tot, (s, e) = 0, iv[0]
    for a, b in iv[1:]:
        if a > e:
            tot += e - s; s, e = a, b
        else:
            e = max(e, b)
    tot += e - s
    return tot / 1000.0


def ctx_of(u):
    return (u[0] or 0) + (u[2] or 0) + (u[3] or 0)


def resp_chars(d, thinking=True):
    return d["text"] + d["tool_use"] + d["other"] + (d["thinking"] if thinking else 0)


# ------------------------------------------------------------------------------------------------------------------ M1
def run_timing(r, x):
    init_ts = r["rows"][0]["ts"]
    rows = [y for y in r["rows"] if y["ts"] <= x["ts"]]
    iv = [(r["call_ts"][t], r["res_ts"][t]) for t in r["call_ts"] if t in r["res_ts"] and r["res_ts"][t] <= x["ts"]]
    e_api = 0.0
    for mid in r["order"]:
        d = r["resp"][mid]
        if d["last_ts"] > x["ts"]:
            continue
        fi = d["first_i"]
        prev_ts = r["rows"][fi - 1]["ts"] if fi > 0 else init_ts
        e_api += (d["last_ts"] - prev_ts) / 1000.0
    main = r["init"]["model"] if r["init"] else None
    return {"sid": r["run_id"], "dur": float(x["duration_ms"] or 0), "api": float(x["duration_api_ms"] or 0),
            "span": (x["ts"] - init_ts) / 1000.0, "tool_u": union_ms(iv), "tool_sum": sum(b - a for a, b in iv) / 1000.0,
            "est_api": e_api, "nonmain": any(k != main for k in x["modelUsage"]), "n_rows": len(rows)}


def m1(runs):
    out = {}
    n_res_hist = Counter(len(r["results"]) for r in runs)
    out["population"] = {
        "runs": len(runs), "result_rows_per_run": {str(k): v for k, v in sorted(n_res_hist.items())},
        "result_rows_total": sum(len(r["results"]) for r in runs),
        "result_rows_not_attributable": sum(1 for r in runs for x in r["results"] if not attributable(x)),
        "runs_whose_only_rows_are_init_plus_unattributable_result": sum(1 for r in runs if not r["order"] and r["results"]
                                                                         and not any(attributable(x) for x in r["results"])),
        "runs_with_no_attributable_result": sum(1 for r in runs if not any(attributable(x) for x in r["results"])),
        "runs_with_no_attributable_result_but_responses": sum(1 for r in runs if r["order"] and not any(attributable(x) for x in r["results"])),
    }
    defs = {
        "duration_ms_ge_span_init_to_result": ("duration_ms >= created_at(result) - created_at(init)", lambda t: t["dur"] >= t["span"]),
        "duration_api_ms_le_duration_ms": ("duration_api_ms <= duration_ms", lambda t: t["api"] <= t["dur"]),
        "duration_ms_ge_tool_interval_union": ("duration_ms >= union of [created_at(call), created_at(result)] intervals",
                                               lambda t: t["dur"] >= t["tool_u"]),
        "duration_ms_ge_tool_gap_sum": ("duration_ms >= sum of call->result created_at gaps", lambda t: t["dur"] >= t["tool_sum"]),
        "duration_minus_api_ge_tool_union": ("duration_ms - duration_api_ms >= tool interval union",
                                             lambda t: t["dur"] - t["api"] >= t["tool_u"]),
        "duration_api_ms_ge_createdat_api_estimate": ("duration_api_ms >= sum over responses of (last row created_at - created_at of the "
                                                      "row before the response's first row)", lambda t: t["api"] >= t["est_api"]),
    }
    out["by_rule"] = {}
    T_by = {}
    for rule in ("raw", "attributable"):
        T = [run_timing(r, x) for r, x in single_result_runs(runs, rule)]
        T_by[rule] = T
        e = {"n_runs": len(T)}
        for k, (txt, f) in defs.items():
            e[k] = {"definition": txt, **wil(sum(1 for t in T if f(t)), len(T))}
        e["duration_minus_span_ms_describe"] = desc([t["dur"] - t["span"] for t in T])
        out["by_rule"][rule] = e
    T = T_by["attributable"]
    sid = [t["sid"] for t in T]
    A = {k: np.asarray([t[k] for t in T], float) for k in ("dur", "api", "span", "tool_u", "tool_sum", "est_api")}
    nonmain = np.asarray([t["nonmain"] for t in T])
    split = {}
    for flag, lab in ((True, "runs_with_nonmain_models_in_modelUsage"), (False, "runs_main_model_only")):
        m = nonmain == flag
        s_ = list(np.asarray(sid)[m])
        with np.errstate(divide="ignore", invalid="ignore"):
            r_api_dur = A["api"][m] / A["dur"][m]
            r_api_est = A["api"][m] / A["est_api"][m]
        split[lab] = {"n_runs": int(m.sum()),
                      "duration_api_ms_le_duration_ms": wil(int((A["api"][m] <= A["dur"][m]).sum()), int(m.sum())),
                      "api_over_duration": {"describe": desc(r_api_dur[np.isfinite(r_api_dur)])},
                      "api_over_createdat_api_estimate": {"describe": desc(r_api_est[np.isfinite(r_api_est)]),
                                                          **qset(r_api_est[np.isfinite(r_api_est)], list(np.asarray(s_)[np.isfinite(r_api_est)]),
                                                                 (0.25, 0.5, 0.75))},
                      "pooled_api_over_createdat_api_estimate": per_run_rate(A["api"][m], A["est_api"][m]),
                      "pooled_api_over_duration": per_run_rate(A["api"][m], A["dur"][m])}
    out["split_by_nonmain_models"] = split
    with np.errstate(divide="ignore", invalid="ignore"):
        rds = A["dur"] / A["span"]
    out["slack_ms"] = {
        "duration_minus_span": {"describe": desc(A["dur"] - A["span"]), **qset(A["dur"] - A["span"], sid)},
        "abs_duration_minus_span": {"describe": desc(np.abs(A["dur"] - A["span"])), **qset(np.abs(A["dur"] - A["span"]), sid, (0.5, 0.9, 0.99))},
        "duration_minus_tool_union": {"describe": desc(A["dur"] - A["tool_u"])},
        "span_minus_tool_union_minus_createdat_api_estimate": {"describe": desc(A["span"] - A["tool_u"] - A["est_api"])},
    }
    out["ratios"] = {"duration_over_span": {"describe": desc(rds[np.isfinite(rds)]), **qset(rds[np.isfinite(rds)], list(np.asarray(sid)[np.isfinite(rds)]))}}
    out["correlations"] = {"duration_vs_span_pearson": cluster_corr(A["dur"], A["span"], sid, "pearson"),
                           "duration_vs_span_spearman": cluster_corr(A["dur"], A["span"], sid, "spearman"),
                           "api_vs_createdat_api_estimate_spearman": cluster_corr(A["api"], A["est_api"], sid, "spearman")}
    out["raw_totals_ms"] = {k: float(v.sum()) for k, v in A.items()}
    top = sorted(T, key=lambda t: -abs(t["dur"] - t["span"]))[:5]
    out["largest_abs_duration_minus_span"] = [{"run_id": t["sid"], "duration_ms": t["dur"], "span_ms": t["span"], "rows": t["n_rows"]} for t in top]
    out["multi_result_runs_raw"] = [{"run_id": r["run_id"], "n_responses": len(r["order"]),
                                     "results": [{"subtype": x["subtype"], "duration_ms": x["duration_ms"], "duration_api_ms": x["duration_api_ms"],
                                                  "num_turns": x["num_turns"], "span_from_init_ms": (x["ts"] - r["rows"][0]["ts"]) / 1000.0,
                                                  "attributable": attributable(x)} for x in r["results"]]}
                                    for r in runs if len(r["results"]) > 1]
    return out


# ------------------------------------------------------------------------------------------------------------------ M2
def m2(runs):
    out = {}
    SX = single_result_runs(runs, "attributable")
    out["n_runs"] = len(SX)
    sid = [r["run_id"] for r, _ in SX]
    # ---- num_turns
    nt = np.asarray([x["num_turns"] for _, x in SX], float)
    nresp = np.asarray([len(r["order"]) for r, _ in SX], float)
    nuser = np.asarray([sum(1 for y in r["rows"] if y["mt"] == "user" and y["sub"] is None and y["ts"] <= x["ts"]) for r, x in SX], float)
    nprompt = np.asarray([sum(1 for y in r["rows"] if y["mt"] == "user" and y["sub"] == "prompt") for r, _ in SX], float)
    out["num_turns"] = {
        "eq_n_api_responses": wil(int((nt == nresp).sum()), len(SX)),
        "eq_n_user_rows_plus_1": {"definition": "num_turns == (user rows with message_subtype null, i.e. tool-result and "
                                                "compaction-summary rows) + 1", **wil(int((nt == nuser + 1).sum()), len(SX))},
        "diff_num_turns_minus_n_user_rows_plus_1_hist": {str(int(k)): v for k, v in sorted(Counter((nt - nuser - 1).tolist()).items())},
        "diff_num_turns_minus_n_api_responses_hist_top": {str(int(k)): v for k, v in Counter((nt - nresp).tolist()).most_common(8)},
        "runs_with_user_prompt_row": int((nprompt > 0).sum()),
        "mismatch_run_ids": [s for s, a, b in zip(sid, nt, nuser) if a != b + 1],
    }
    # ---- per-response usage constancy
    multi, varies, outpat = 0, Counter(), Counter()
    for r in runs:
        for mid in r["order"]:
            us = r["resp"][mid]["us"]
            if len(us) > 1:
                multi += 1
                for j, f in ((0, "input"), (1, "output"), (2, "cache_read"), (3, "cache_creation")):
                    if len({u[j] for u in us}) > 1:
                        varies[f] += 1
                outs = [u[1] or 0 for u in us]
                outpat["last_row_is_max" if outs[-1] == max(outs) else "last_row_lt_max"] += 1
    out["per_response_usage_constancy"] = {"responses_with_multiple_rows": multi, "responses_where_field_varies_across_rows": dict(varies),
                                           "output_tokens_pattern": dict(outpat)}
    # ---- result.usage vs sum of per-response usage
    flds = [("input", 0), ("output", 1), ("cache_read", 2), ("cache_creation", 3), ("cc_5m", 4), ("cc_1h", 5)]
    ucmp = {}
    res_zero = [all((v or 0) == 0 for v in x["u"][:4]) for _, x in SX]
    for f, j in flds:
        a = np.asarray([x["u"][j] or 0 for _, x in SX], float)
        if f == "output":
            b = np.asarray([sum(r["resp"][m]["us"][-1][1] or 0 for m in r["order"]) for r, _ in SX], float)
        else:
            b = np.asarray([sum(r["resp"][m]["us"][0][j] or 0 for m in r["order"]) for r, _ in SX], float)
        neq = a != b
        ucmp[f] = {"eq": wil(int((~neq).sum()), len(a)), "result_gt_sum": int((a > b).sum()), "result_lt_sum": int((a < b).sum()),
                   "mismatch_with_result_usage_all_zero": int(sum(1 for z, q in zip(res_zero, neq) if z and q)),
                   "total_result": float(a.sum()), "total_sum_of_rows": float(b.sum())}
    ucmp["note"] = "output: per-row output_tokens of the response's last row (streaming snapshot); others: response first row"
    out["result_usage_vs_per_response_sum"] = ucmp
    # ---- responses present in the stream but not in result.usage
    def has_stop(r, d):
        return any(r["rows"][q]["stop"] is not None for q in d["rows"])
    nonsyn = [(r, r["resp"][m]) for r in runs for m in r["order"] if r["resp"][m]["model"] != "<synthetic>"]
    base_stop = sum(1 for r, d in nonsyn if has_stop(r, d))
    deficit_runs, single_match, single_match_stop = [], 0, 0
    for r, x in SX:
        if all((v or 0) == 0 for v in x["u"][:4]):
            continue
        dfc = [sum(r["resp"][m]["us"][0][j] or 0 for m in r["order"]) - (x["u"][j] or 0) for j in (0, 2, 3)]
        if dfc == [0, 0, 0]:
            continue
        hits = [r["resp"][m] for m in r["order"] if [r["resp"][m]["us"][0][j] or 0 for j in (0, 2, 3)] == dfc]
        e = {"run_id": r["run_id"], "deficit_input_cacheRead_cacheCreation": dfc, "single_response_exact_match": len(hits) == 1,
             "n_responses_with_nonnull_stop_reason": sum(1 for m in r["order"] if has_stop(r, r["resp"][m]))}
        if len(hits) == 1:
            single_match += 1; single_match_stop += has_stop(r, hits[0])
            e["matched_response_has_nonnull_stop_reason"] = has_stop(r, hits[0])
        deficit_runs.append(e)
    zero_runs = [(r, x) for r, x in SX if all((v or 0) == 0 for v in x["u"][:4]) and any(r["resp"][m]["model"] != "<synthetic>" for m in r["order"])]
    out["responses_in_stream_not_in_result_usage"] = {
        "runs_result_usage_below_stream_sum_nonzero": len(deficit_runs),
        "runs_with_single_response_exact_match": single_match,
        "single_matched_responses_with_nonnull_stop_reason": single_match_stop,
        "runs": deficit_runs,
        "runs_result_usage_all_zero_with_real_responses": len(zero_runs),
        "those_runs_responses_all_with_nonnull_stop_reason": sum(1 for r, x in zero_runs if all(has_stop(r, r["resp"][m]) for m in r["order"])),
        "base_rate_nonnull_stop_reason_among_nonsynthetic_responses": wil(base_stop, len(nonsyn)),
        "runs_result_usage_eq_stream_sum_excluding_nonnull_stop_responses": wil(
            sum(1 for r, x in SX if all(sum(r["resp"][m]["us"][0][j] or 0 for m in r["order"] if not has_stop(r, r["resp"][m])
                                            and r["resp"][m]["model"] != "<synthetic>") == (x["u"][j] or 0) for j in (0, 2, 3))), len(SX)),
        "runs_result_usage_eq_stream_sum_all_responses": wil(
            sum(1 for r, x in SX if all(sum(r["resp"][m]["us"][0][j] or 0 for m in r["order"]) == (x["u"][j] or 0) for j in (0, 2, 3))), len(SX))}
    # ---- output tokens (result) vs logged assistant chars
    oc = {}
    for lab, th in (("with_thinking_chars", True), ("without_thinking_chars", False)):
        ch = np.asarray([sum(resp_chars(r["resp"][m], th) for m in r["order"]) for r, _ in SX], float)
        ot = np.asarray([x["u"][1] or 0 for _, x in SX], float)
        ok = ot > 0
        oc[lab] = {"pooled_chars_per_output_token": per_run_rate(ch[ok], ot[ok]),
                   "per_run_chars_per_output_token": {"describe": desc(ch[ok] / ot[ok]), **qset(ch[ok] / ot[ok], list(np.asarray(sid)[ok]))},
                   "spearman_chars_vs_output_tokens": cluster_corr(ch[ok], ot[ok], list(np.asarray(sid)[ok]), "spearman"),
                   "pearson_chars_vs_output_tokens": cluster_corr(ch[ok], ot[ok], list(np.asarray(sid)[ok]), "pearson"),
                   "n_runs_output_gt_0": int(ok.sum())}
    out["result_output_tokens_vs_logged_assistant_chars"] = oc
    # ---- modelUsage[main] vs result.usage, and hidden calls
    mus = {"inputTokens": 0, "outputTokens": 1, "cacheReadInputTokens": 2, "cacheCreationInputTokens": 3}
    H = []
    missing_main_with_main_responses = []
    for r, x in SX:
        main = r["init"]["model"]
        mm = x["modelUsage"].get(main)
        n_main_resp = sum(1 for m in r["order"] if r["resp"][m]["model"] == main)
        if mm is None:
            if n_main_resp:
                missing_main_with_main_responses.append({"run_id": r["run_id"], "main_model_responses_in_stream": n_main_resp,
                                                         "result_usage_all_zero": all((v or 0) == 0 for v in x["u"][:4]),
                                                         "total_cost_usd": x["total_cost_usd"], "models_listed": sorted(x["modelUsage"])})
            continue
        comps = [y for y in r["rows"] if y["mt"] == "system" and y["sub"] == "compact_boundary" and y["ts"] <= x["ts"]]
        summ = sum(y["txt"] for y in r["rows"] if y["mt"] == "user" and y["synth"] and y["ts"] <= x["ts"])
        H.append({"sid": r["run_id"], "version": r["init"]["version"], "ncomp": len(comps),
                  "pre_sum": sum(c["pre_tokens"] or 0 for c in comps), "summary_chars": summ,
                  **{f"d_{k}": (mm.get(k) or 0) - (x["u"][j] or 0) for k, j in mus.items()}})
    hid = {"runs_with_main_in_modelUsage": len(H),
           "fields_eq": {k: wil(sum(1 for h in H if h[f"d_{k}"] == 0), len(H)) for k in mus},
           "runs_main_model_missing_from_modelUsage_but_main_responses_in_stream": missing_main_with_main_responses,
           "runs_main_model_missing_from_modelUsage_total": sum(1 for r, x in SX if r["init"]["model"] not in x["modelUsage"])}
    H0 = [h for h in H if h["ncomp"] == 0]; H1 = [h for h in H if h["ncomp"] > 0]
    hid["runs_without_compaction"] = {"n": len(H0), "all_four_fields_eq": wil(sum(1 for h in H0 if all(h[f"d_{k}"] == 0 for k in mus)), len(H0))}
    hid["runs_with_compaction"] = {
        "n": len(H1), "compactions": sum(h["ncomp"] for h in H1),
        "d_cacheRead_eq_0": wil(sum(1 for h in H1 if h["d_cacheReadInputTokens"] == 0), len(H1)),
        "d_input_per_compaction_by_version": {f"{v}|{q}": c for (v, q), c in Counter((h["version"], h["d_inputTokens"] / h["ncomp"]) for h in H1).items()},
        "d_input_eq_k_times_ncomp": {"definition": "d_input == k * n_compactions with k = most common per-compaction value within the version",
                                     **_k_identity(H1)},
        "d_output_vs_summary_chars": {"spearman": cluster_corr([h["summary_chars"] for h in H1], [h["d_outputTokens"] for h in H1],
                                                               [h["sid"] for h in H1], "spearman"),
                                      "pooled_summary_chars_per_hidden_output_token": per_run_rate([h["summary_chars"] for h in H1],
                                                                                                  [h["d_outputTokens"] for h in H1]),
                                      "per_run_describe": desc([h["summary_chars"] / h["d_outputTokens"] for h in H1 if h["d_outputTokens"] > 0])},
        "d_cacheCreation_over_pre_tokens_sum": {"pooled": per_run_rate([h["d_cacheCreationInputTokens"] for h in H1], [h["pre_sum"] for h in H1]),
                                                "per_run_describe": desc([h["d_cacheCreationInputTokens"] / h["pre_sum"] for h in H1 if h["pre_sum"] > 0]),
                                                "spearman": cluster_corr([h["pre_sum"] for h in H1], [h["d_cacheCreationInputTokens"] for h in H1],
                                                                         [h["sid"] for h in H1], "spearman")},
        "d_output_per_compaction_describe": desc([h["d_outputTokens"] / h["ncomp"] for h in H1]),
        "any_field_negative": sum(1 for h in H1 if any(h[f"d_{k}"] < 0 for k in mus)),
    }
    out["modelUsage_main_minus_result_usage"] = hid
    # ---- modelUsage composition (non-main models: API usage with no responses in the stream)
    mods = Counter(); runs_nonmain = 0; tok = Counter(); cost_other, cost_total = [], []
    for r, x in SX:
        main = r["init"]["model"]
        oc_ = 0.0
        for k, v in x["modelUsage"].items():
            mods[k] += 1
            tok["main" if k == main else "nonmain"] += sum(float(v.get(f, 0) or 0) for f in mus)
            if k != main:
                oc_ += float(v.get("costUSD", 0) or 0)
        runs_nonmain += any(k != main for k in x["modelUsage"])
        cost_other.append(oc_); cost_total.append(sum(float(v.get("costUSD", 0) or 0) for v in x["modelUsage"].values()))
    out["modelUsage_composition"] = {
        "runs_listing_model": dict(mods), "init_models": dict(Counter(r["init"]["model"] for r, _ in SX)),
        "runs_with_nonmain_model": wil(runs_nonmain, len(SX)), "tokens_main": tok["main"], "tokens_nonmain": tok["nonmain"],
        "nonmain_cost_share_pooled": per_run_rate(cost_other, cost_total),
        "assistant_rows_by_model_in_stream": dict(Counter(y["model"] for r in runs for y in r["rows"] if y["mt"] == "assistant")),
        "nonmain_cacheRead_per_run_describe": {k: desc([float(x["modelUsage"][k].get("cacheReadInputTokens") or 0) for _, x in SX if k in x["modelUsage"]])
                                               for k in mods if k not in {r["init"]["model"] for r, _ in SX}}}
    # ---- cost identities
    tol = PREREG["cost_abs_tol_usd"]["value"]
    allx = [x for r in runs for x in r["results"]]
    diffs = np.asarray([(x["total_cost_usd"] or 0) - sum(float(v.get("costUSD", 0) or 0) for v in x["modelUsage"].values()) for x in allx])
    out["cost_total_vs_modelUsage_sum"] = {"abs_diff_le_tol": wil(int((np.abs(diffs) <= tol).sum()), len(diffs)),
                                           "abs_diff_describe": desc(np.abs(diffs))}
    rowsby = defaultdict(list)
    for x in allx:
        for k, v in x["modelUsage"].items():
            rowsby[k].append(v)
    feats = ["inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens", "webSearchRequests"]
    fits = {}
    for k, lst in rowsby.items():
        X = np.asarray([[float(v.get(f, 0) or 0) for f in feats] for v in lst])
        y = np.asarray([float(v.get("costUSD", 0) or 0) for v in lst])
        use = [j for j in range(len(feats)) if X[:, j].any()]
        if len(lst) < len(use) + 2 or not use:
            fits[k] = {"n": len(lst), "fit": None}
            continue
        coef, *_ = np.linalg.lstsq(X[:, use], y, rcond=None)
        resid = y - X[:, use] @ coef
        tolv = np.maximum(1e-6, 1e-6 * np.abs(y))
        fits[k] = {"n": len(lst), "features": [feats[j] for j in use],
                   "implied_usd_per_million_units": {feats[j]: float(c) * 1e6 for j, c in zip(use, coef)},
                   "abs_resid_usd_describe": desc(np.abs(resid)),
                   "reproduced_within_tol": wil(int((np.abs(resid) <= tolv).sum()), len(lst)),
                   "contextWindow_values": dict(Counter(str(v.get("contextWindow")) for v in lst))}
    out["implied_price_fit"] = fits
    out["cache_creation_1h_tokens_total_in_result_usage"] = float(sum(x["u"][5] or 0 for x in allx))
    out["result_flags"] = {"subtype|is_error": dict(Counter(f"{x['subtype']}|{x['is_error']}" for x in allx)),
                           "permission_denials_total": int(sum(x["n_denials"] for x in allx)), "result_rows": len(allx),
                           "error_message_prefixes": dict(Counter(e[:30] for x in allx for e in x["errors"])),
                           "init_permission_modes": dict(Counter(str(r["init"]["perm"]) for r in runs if r["init"])),
                           "init_versions": dict(Counter(str(r["init"]["version"]) for r in runs if r["init"]))}
    return out


def _k_identity(H1):
    byv = defaultdict(Counter)
    for h in H1:
        byv[h["version"]][h["d_inputTokens"] / h["ncomp"]] += 1
    kv = {v: c.most_common(1)[0][0] for v, c in byv.items()}
    ok = sum(1 for h in H1 if h["d_inputTokens"] == kv[h["version"]] * h["ncomp"])
    return {"k_by_version": {v: float(k) for v, k in kv.items()}, **wil(ok, len(H1))}


# ------------------------------------------------------------------------------------------------------------------ M3
def m3(runs, rows, sess):
    out = {}
    gaps, gsid = defaultdict(list), defaultdict(list)
    ties = n_adj = 0
    for r in runs:
        rr = r["rows"]
        for a, b in zip(rr, rr[1:]):
            n_adj += 1
            g = (b["ts"] - a["ts"]) / 1000.0
            ties += g == 0
            if a["mt"] == "assistant" and b["mt"] == "assistant":
                k = "asst_to_asst_same_msg" if a["mid"] == b["mid"] else "asst_to_asst_new_msg"
            elif a["mt"] in ("assistant", "user") and b["mt"] in ("assistant", "user") and a["sub"] is None and b["sub"] is None:
                k = f"{a['mt']}_to_{b['mt']}"
            else:
                k = f"{a['mt']}:{a['sub']}_to_{b['mt']}:{b['sub']}"
            gaps[k].append(g); gsid[k].append(r["run_id"])
    out["adjacent_pairs_within_runs"] = n_adj
    out["identical_created_at_adjacent_pairs"] = int(ties)
    out["gaps_ms_by_transition"] = {}
    for k in sorted(gaps, key=lambda k: -len(gaps[k])):
        v = gaps[k]
        e = {"n": len(v), "binned": binned(v, PREREG["gap_bins_ms"]["value"]), "describe": desc(v)}
        if len(v) >= 30:
            e["median"] = cq(v, gsid[k], 0.5)
        out["gaps_ms_by_transition"][k] = e
    allg = [g for v in gaps.values() for g in v]
    out["gaps_ms_all"] = {"binned": binned(allg, PREREG["gap_bins_ms"]["value"]), "log_hist": stats.log_histogram(allg)}
    # global (all rows, all sdk sessions) created_at ties
    allts = Counter(r["ts"] for r in rows)
    out["global_identical_created_at_groups"] = sum(1 for v in allts.values() if v > 1)
    # within-message block gaps vs chars of the later block
    xs, ys, ss, kinds = [], [], [], []
    for r in runs:
        rr = r["rows"]
        for a, b in zip(rr, rr[1:]):
            if a["mt"] == "assistant" and b["mt"] == "assistant" and a["mid"] == b["mid"]:
                xs.append(sum(x[1] for x in b["blocks"])); ys.append((b["ts"] - a["ts"]) / 1000.0); ss.append(r["run_id"])
                kinds.append("+".join(x[0] for x in b["blocks"]))
    xs = np.asarray(xs, float); ys = np.asarray(ys, float)
    w = {"n": len(xs), "later_block_kinds": dict(Counter(kinds)),
         "spearman": cluster_corr(xs, ys, ss, "spearman"), "pearson": cluster_corr(xs, ys, ss, "pearson"),
         "chars_per_second_describe": desc(xs[ys > 0] / (ys[ys > 0] / 1000.0)),
         "chars_per_second_median": cq(xs[ys > 0] / (ys[ys > 0] / 1000.0), list(np.asarray(ss)[ys > 0]), 0.5)}
    for kind in ("tool_use", "text"):
        m = np.asarray([k == kind for k in kinds])
        if m.sum() >= 30:
            w[f"spearman_only_{kind}"] = cluster_corr(xs[m], ys[m], list(np.asarray(ss)[m]), "spearman")
    out["within_message_gap_vs_next_block_chars"] = w
    # tool-reported durations vs created_at call->result gap
    td = defaultdict(lambda: {"gap": [], "dur": [], "sid": []})
    for r in runs:
        for y in r["rows"]:
            if y["mt"] == "user" and y["tdur"] is not None and len(y["trs"]) == 1:
                tid = y["trs"][0][0]
                if tid in r["call_ts"]:
                    k = f"{r['call_name'].get(tid)}|{y['tdurk']}"
                    td[k]["gap"].append((y["ts"] - r["call_ts"][tid]) / 1000.0); td[k]["dur"].append(y["tdur"]); td[k]["sid"].append(r["run_id"])
    out["tool_reported_duration_vs_gap"] = {}
    for k, d in td.items():
        g = np.asarray(d["gap"]); du = np.asarray(d["dur"])
        out["tool_reported_duration_vs_gap"][k] = {
            "gap_ge_reported": wil(int((g >= du).sum()), len(g)), "slack_ms_describe": desc(g - du),
            "slack_ms_median": cq(g - du, d["sid"], 0.5) if len(g) >= 10 else None,
            "spearman_gap_vs_reported": cluster_corr(g, du, d["sid"], "spearman") if len(g) >= 10 else None, "n_runs": len(set(d["sid"]))}
    # ordering checks
    viol, checked, res_before_call, inter, inv_order, multi = 0, 0, 0, 0, 0, 0
    rows_after_last_result = 0
    for r in runs:
        rr = r["rows"]
        for t, cts in r["call_ts"].items():
            if t in r["res_ts"] and r["res_ts"][t] < cts:
                res_before_call += 1
        res_row_i = {}
        for i, y in enumerate(rr):
            if y["mt"] == "user":
                for tr in y["trs"]:
                    res_row_i[tr[0]] = i
        for a, b in zip(r["order"], r["order"][1:]):
            ris = [res_row_i[t] for t in r["resp"][a]["tool_ids"] if t in res_row_i]
            if ris:
                checked += 1
                viol += max(ris) > r["resp"][b]["first_i"]
        rank = {"thinking": 0, "text": 1, "tool_use": 2}
        for mid in r["order"]:
            d = r["resp"][mid]
            if len(d["rows"]) > 1:
                multi += 1
                inter += d["rows"][-1] - d["rows"][0] + 1 != len(d["rows"])
                seq = [rank.get(rr[i]["blocks"][0][0], 3) for i in d["rows"] if rr[i]["blocks"]]
                inv_order += any(q < p for p, q in zip(seq, seq[1:]))
        if r["results"]:
            rows_after_last_result += len(rr) - 1 - max(i for i, y in enumerate(rr) if y["mt"] == "result")
    # tool results arriving between blocks of the still-streaming response that called them
    early = sum(1 for r in runs for mid in r["order"] for t in r["resp"][mid]["tool_ids"]
                if t in r["res_ts"] and r["res_ts"][t] < r["resp"][mid]["last_ts"])
    out["ordering"] = {"tool_result_created_before_its_call": res_before_call,
                       "next_response_first_row_before_all_prior_results": {"violations": int(viol), "pairs_checked": checked},
                       "multi_row_responses": multi, "multi_row_responses_interleaved_with_other_rows": int(inter),
                       "tool_results_created_before_the_calling_response_last_row": early,
                       "multi_row_responses_block_type_order_inversions": int(inv_order),
                       "rows_after_last_result_row_in_run": rows_after_last_result}
    out["linkage_fields"] = {"rows": len(rows),
                             "parent_tool_use_id_nonnull": sum(1 for x in rows if x["ptu"] is not None),
                             "parentUuid_key_present": sum(1 for x in rows if x["has_parent_uuid"]),
                             "message_uuid_column_nonnull": sum(1 for x in rows if x["muuid"] is not None),
                             "content_uuid_present": sum(1 for x in rows if x["uuid"]),
                             "content_uuid_distinct": len({x["uuid"] for x in rows if x["uuid"]}),
                             "content_session_id_ne_sdk_session_id_by_type": dict(Counter(f"{x['mt']}|{x['sub']}" for x in rows if x["csid"] != x["sdk"]))}
    # sessions table rows vs the messages stream: the row immediately before each sessions row in global created_at order
    allr = sorted(rows, key=lambda r: r["ts"])
    ts = [r["ts"] for r in allr]
    prev_type, lag_prev, lag_next, same_sdk, lsid = Counter(), [], [], 0, []
    for s in sess:
        i = bisect.bisect_left(ts, s["ts"])
        if i > 0:
            p = allr[i - 1]
            prev_type[f"{p['mt']}|{p['sub']}"] += 1
            if is_init(p):
                lag_prev.append((s["ts"] - p["ts"]) / 1000.0); lsid.append(s["sdk"] + str(i)); same_sdk += p["sdk"] == s["sdk"]
        if i < len(allr):
            lag_next.append((allr[i]["ts"] - s["ts"]) / 1000.0)
    sdk_with_init = Counter(r["sdk"] for r in runs if r["init"]); sdk_sess = Counter(s["sdk"] for s in sess)
    out["sessions_table"] = {
        "sessions_rows": len(sess), "init_rows": sum(1 for r in runs if r["init"]),
        "row_immediately_before_sessions_row_type": dict(prev_type),
        "preceding_init_same_sdk_session": same_sdk,
        "lag_ms_sessions_row_minus_preceding_init": {"describe": desc(lag_prev), "median": cq(lag_prev, lsid, 0.5) if lag_prev else None},
        "lag_ms_next_messages_row_minus_sessions_row": desc(lag_next),
        "sdk_sessions_in_messages": len(sdk_with_init), "sdk_sessions_in_sessions_table": len(sdk_sess),
        "sdk_sessions_with_init_but_no_sessions_row": sum(1 for k in sdk_with_init if k not in sdk_sess),
        "sdk_sessions_init_count_ne_sessions_row_count": sum(1 for k in sdk_with_init if sdk_with_init[k] != sdk_sess.get(k, 0)),
        "sessions_rows_created_at_eq_updated_at_within_1ms": sum(1 for s in sess if s["upd"] is not None and abs(s["upd"] - s["ts"]) < 1000)}
    return out


# ------------------------------------------------------------------------------------------------------------------ M4
def _cat(p):
    if p["zero"]:
        return "zero_usage"
    return "compact" if p["compact"] else ("image" if p["n_img"] else "clean")


def m4(runs):
    out = {}
    P = []
    zero_resp = 0
    for r in runs:
        rr = r["rows"]
        order = r["order"]
        zero_resp += sum(1 for m in order if ctx_of(r["resp"][m]["us"][0]) == 0)
        for a, b in zip(order, order[1:]):
            da, db = r["resp"][a], r["resp"][b]
            ua, ub = da["us"][0], db["us"][0]
            u_chars = n_img = n_tr = 0
            compact = status = False
            for y in rr[da["first_i"]: db["first_i"]]:
                if y["mt"] == "user":
                    u_chars += sum(t[1] for t in y["trs"]) + y["txt"]; n_img += sum(t[2] for t in y["trs"]) + y["nimg"]; n_tr += len(y["trs"])
                elif y["mt"] == "system":
                    compact |= y["sub"] == "compact_boundary"; status |= y["sub"] == "status"
            tool = da["tool_names"][0] if da["n_tool_use"] == 1 and n_tr == 1 else None
            P.append({"sid": r["run_id"], "ctx_a": ctx_of(ua), "ctx_b": ctx_of(ub), "delta": ctx_of(ub) - ctx_of(ua),
                      "zero": ctx_of(ua) == 0 or ctx_of(ub) == 0,
                      "a_vis": resp_chars(da, False), "a_think": da["thinking"], "u_chars": u_chars, "n_img": n_img, "n_tr": n_tr,
                      "n_tu": da["n_tool_use"], "compact": compact, "status": status, "tool": tool,
                      "cr_a": ua[2] or 0, "cc_a": ua[3] or 0, "in_a": ua[0] or 0, "cr_b": ub[2] or 0, "cc_b": ub[3] or 0, "in_b": ub[0] or 0,
                      "gap_ms": (db["first_ts"] - da["last_ts"]) / 1000.0, "version": r["init"]["version"] if r["init"] else None})
    out["api_responses_total"] = sum(len(r["order"]) for r in runs)
    out["api_responses_zero_context_usage"] = zero_resp
    out["pairs_total"] = len(P)
    out["runs_with_pairs"] = len({p["sid"] for p in P})
    out["pair_categories"] = dict(Counter(_cat(p) for p in P))
    sidsP = [p["sid"] for p in P]
    neg = [p for p in P if p["delta"] < 0]
    out["negative_delta"] = {
        "share_all_pairs": run_rate([p["delta"] < 0 for p in P], [1] * len(P), sidsP),
        "by_category": {k: {"negative": sum(1 for p in neg if _cat(p) == k), "n": sum(1 for p in P if _cat(p) == k)}
                        for k in ("clean", "image", "compact", "zero_usage")},
        "negative_nonzero_noncompact_with_cache_read_reset": {
            "definition": "cache_read(k+1) < cache_read(k) for a negative-delta pair that is neither compact nor zero_usage",
            "n": sum(1 for p in neg if _cat(p) in ("clean", "image") and p["cr_b"] < p["cr_a"]),
            "cache_read_after_describe": desc([p["cr_b"] for p in neg if _cat(p) in ("clean", "image")]),
            "delta_describe": desc([p["delta"] for p in neg if _cat(p) in ("clean", "image")]),
            "by_version": dict(Counter(str(p["version"]) for p in neg if _cat(p) in ("clean", "image")))},
        "zero_delta_pairs_nonzero_usage": sum(1 for p in P if p["delta"] == 0 and not p["zero"])}
    # ---- cache chain identity
    cc_eq = [p["cr_b"] == p["cr_a"] + p["cc_a"] for p in P]
    out["cache_chain"] = {"definition": "cache_read(k+1) == cache_read(k) + cache_creation(k), consecutive responses in a run"}
    for k in ("clean", "image", "compact", "zero_usage"):
        idx = [i for i, p in enumerate(P) if _cat(p) == k]
        if not idx:
            continue
        diff = np.asarray([P[i]["cr_b"] - P[i]["cr_a"] - P[i]["cc_a"] for i in idx], float)
        out["cache_chain"][k] = {"eq_count": int(sum(cc_eq[i] for i in idx)), "n": len(idx),
                                 "eq_rate": run_rate([cc_eq[i] for i in idx], [1] * len(idx), [P[i]["sid"] for i in idx]),
                                 "diff_lt_0": int((diff < 0).sum()), "diff_gt_0": int((diff > 0).sum()),
                                 "diff_describe_nonzero": desc(diff[diff != 0])}
    C = [p for p in P if _cat(p) == "clean"]
    out["cache_chain"]["clean_uncached_input_tokens_next_describe"] = desc([p["in_b"] for p in C])
    out["cache_chain"]["clean_breaks_by_gap"] = {
        "gap_lt_300s": {"breaks": sum(1 for p in C if p["gap_ms"] < 3e5 and p["cr_b"] != p["cr_a"] + p["cc_a"]), "n": sum(1 for p in C if p["gap_ms"] < 3e5)},
        "gap_ge_300s": {"breaks": sum(1 for p in C if p["gap_ms"] >= 3e5 and p["cr_b"] != p["cr_a"] + p["cc_a"]), "n": sum(1 for p in C if p["gap_ms"] >= 3e5)}}
    # ---- token conservation on clean pairs
    sid = [p["sid"] for p in C]
    d = np.asarray([p["delta"] for p in C], float)
    out["clean"] = {"n_pairs": len(C), "n_runs": len(set(sid)), "delta_describe": desc(d),
                    "pairs_with_thinking_in_previous_response": sum(1 for p in C if p["a_think"] > 0)}
    for lab, th in (("without_thinking_chars", False), ("with_thinking_chars", True)):
        ch = np.asarray([p["a_vis"] + p["u_chars"] + (p["a_think"] if th else 0) for p in C], float)
        pos = (d > 0) & (ch > 0)
        cpt = ch[pos] / d[pos]
        sp = list(np.asarray(sid)[pos])
        out["clean"][lab] = {"pearson_delta_vs_chars": cluster_corr(ch, d, sid, "pearson"),
                             "spearman_delta_vs_chars": cluster_corr(ch, d, sid, "spearman"),
                             "pooled_chars_per_token": run_rate(ch[pos], d[pos], sp),
                             "chars_per_token_quantiles": qset(cpt, sp), "chars_per_token_describe": desc(cpt), "n_pos": int(pos.sum())}
    uch = np.asarray([p["u_chars"] for p in C], float); av = np.asarray([p["a_vis"] for p in C], float)
    at = np.asarray([p["a_think"] for p in C], float); ntr = np.asarray([p["n_tr"] for p in C], float)
    ntu = np.asarray([p["n_tu"] for p in C], float); one = np.ones(len(C))
    h = np.asarray([hash_half(s) for s in sid])
    fits = {}
    out["clean"]["n_tool_results_eq_n_tool_use_pairs"] = int((ntr == ntu).sum())
    for name, X, terms in (("prereg_3term", np.column_stack([uch, av, at, one]), ["user_chars", "assistant_visible_chars", "thinking_chars", "intercept"]),
                           ("posthoc_extended", np.column_stack([uch, av, at, ntu, one]),
                            ["user_chars", "assistant_visible_chars", "thinking_chars", "n_tool_use", "intercept"])):
        coef, *_ = np.linalg.lstsq(X, d, rcond=None)
        res = d - X @ coef
        cf, *_ = np.linalg.lstsq(X[h], d[h], rcond=None)
        rr = d[~h] - X[~h] @ cf
        fits[name] = {"terms": terms, "coef_tokens_per_unit": [float(c) for c in coef],
                      "r2": float(1 - (res ** 2).sum() / ((d - d.mean()) ** 2).sum()),
                      "abs_resid_quantiles": qset(np.abs(res), sid, (0.5, 0.9, 0.99)),
                      "abs_resid_describe": desc(np.abs(res)),
                      "holdout": {"fit_half_pairs": int(h.sum()), "eval_half_pairs": int((~h).sum()), "coef_fit_half": [float(c) for c in cf],
                                  "eval_abs_resid_describe": desc(np.abs(rr)),
                                  "eval_abs_resid_quantiles": qset(np.abs(rr), list(np.asarray(sid)[~h]), (0.5, 0.9, 0.99)),
                                  "eval_r2": float(1 - (rr ** 2).sum() / ((d[~h] - d[~h].mean()) ** 2).sum())}}
        if name == "posthoc_extended":
            ext_coef, ext_res = coef, res
    out["clean"]["linear_fits"] = fits
    # residual vs relative size: |resid| / delta
    rel = np.abs(ext_res[d > 0]) / d[d > 0]
    out["clean"]["posthoc_extended_abs_resid_over_delta"] = {"describe": desc(rel), **qset(rel, list(np.asarray(sid)[d > 0]), (0.5, 0.9, 0.99))}
    # per tool (single tool_use answered by a single tool result, clean)
    per_tool = {}
    tools = Counter(p["tool"] for p in C if p["tool"])
    for t, n in tools.most_common():
        if n < PREREG["min_pairs_per_tool"]["value"]:
            continue
        idx = [i for i, p in enumerate(C) if p["tool"] == t]
        ch = np.asarray([C[i]["a_vis"] + C[i]["a_think"] + C[i]["u_chars"] for i in idx], float)
        dd = d[idx]; ss = [C[i]["sid"] for i in idx]
        ok = (dd > 0) & (ch > 0)
        per_tool[t] = {"n_pairs": n, "n_runs": len(set(ss)),
                       "chars_per_token_with_thinking_median": cq(ch[ok] / dd[ok], list(np.asarray(ss)[ok]), 0.5) if ok.sum() >= 10 else None,
                       "result_chars_median": float(np.median([C[i]["u_chars"] for i in idx])),
                       "abs_resid_posthoc_extended": {"p50": float(np.quantile(np.abs(ext_res[idx]), 0.5)),
                                                      "p90": float(np.quantile(np.abs(ext_res[idx]), 0.9)),
                                                      "p99": float(np.quantile(np.abs(ext_res[idx]), 0.99))},
                       "mean_resid_posthoc_extended": float(np.mean(ext_res[idx]))}
    out["clean"]["per_tool_single_call_pairs"] = per_tool
    # ---- image pairs: tokens per stripped image after removing the char-explained part (extended fit)
    I = [p for p in P if _cat(p) == "image" and p["delta"] > 0]
    if I:
        Xi = np.column_stack([[p["u_chars"] for p in I], [p["a_vis"] for p in I], [p["a_think"] for p in I],
                              [p["n_tu"] for p in I], np.ones(len(I))]).astype(float)
        di = np.asarray([p["delta"] for p in I], float)
        per_img = (di - Xi @ ext_coef) / np.asarray([p["n_img"] for p in I], float)
        si = [p["sid"] for p in I]
        out["image_pairs_positive_delta"] = {"n_pairs": len(I), "n_runs": len(set(si)), "images_per_pair": dict(Counter(str(p["n_img"]) for p in I)),
                                             "residual_tokens_per_image": {"describe": desc(per_img), **qset(per_img, si)},
                                             "residual_tokens_per_image_log_hist": stats.log_histogram(per_img)}
    # ---- compaction boundaries
    comp = []
    for r in runs:
        rr = r["rows"]
        last_mid = None; pending = None
        for i, y in enumerate(rr):
            if y["mt"] == "assistant":
                if pending is not None:
                    pending["post_ctx"] = ctx_of(y["u"]); comp.append(pending); pending = None
                last_mid = y["mid"]
            elif y["mt"] == "system" and y["sub"] == "compact_boundary":
                if last_mid is None:
                    pending = {"sid": r["run_id"], "pre": y["pre_tokens"], "last_ctx": None, "app": None, "summary": 0, "post_ctx": None}
                    continue
                dl = r["resp"][last_mid]
                app = resp_chars(dl, True) + sum(sum(t[1] for t in z["trs"]) + z["txt"] for z in rr[dl["first_i"]: i] if z["mt"] == "user")
                nimg = sum(sum(t[2] for t in z["trs"]) + z["nimg"] for z in rr[dl["first_i"]: i] if z["mt"] == "user")
                pending = {"sid": r["run_id"], "pre": y["pre_tokens"], "last_ctx": ctx_of(dl["us"][0]), "app": app, "nimg": nimg,
                           "summary": 0, "post_ctx": None}
            elif y["mt"] == "user" and pending is not None and y["synth"]:
                pending["summary"] += y["txt"]
        if pending is not None:
            comp.append(pending)
    hv = [c for c in comp if c["last_ctx"] is not None and c["pre"] is not None]
    hv0 = [c for c in hv if c["nimg"] == 0]
    dd = np.asarray([c["pre"] - c["last_ctx"] for c in hv0], float); ap = np.asarray([c["app"] for c in hv0], float)
    ok = dd > 0
    out["compaction"] = {
        "boundaries": len(comp), "with_prior_response_in_run": len(hv), "with_prior_response_no_image_appended": len(hv0),
        "pre_tokens_eq_last_ctx": wil(int(sum(1 for c in hv if c["pre"] == c["last_ctx"])), len(hv)),
        "pre_tokens_lt_last_ctx": int(sum(1 for c in hv if c["pre"] < c["last_ctx"])),
        "pre_minus_last_ctx_describe": desc(dd),
        "pre_minus_last_ctx_vs_appended_chars_spearman": cluster_corr(ap, dd, [c["sid"] for c in hv0], "spearman"),
        "appended_chars_per_token": {"pooled": run_rate(ap[ok], dd[ok], list(np.asarray([c["sid"] for c in hv0])[ok])),
                                     **qset(ap[ok] / dd[ok], list(np.asarray([c["sid"] for c in hv0])[ok]), (0.25, 0.5, 0.75))},
        "post_ctx_describe": desc([c["post_ctx"] for c in comp if c["post_ctx"] is not None]),
        "summary_chars_describe": desc([c["summary"] for c in comp]),
        "post_ctx_vs_summary_chars_spearman": cluster_corr([c["summary"] for c in comp if c["post_ctx"]], [c["post_ctx"] for c in comp if c["post_ctx"]],
                                                           [c["sid"] for c in comp if c["post_ctx"]], "spearman"),
        "post_ctx_minus_summary_chars_over_2_5_describe": desc([c["post_ctx"] - c["summary"] / 2.5 for c in comp if c["post_ctx"]]),
        "note": "2.5 chars/token in the last field is the pooled clean-pair rate rounded (descriptive only)"}
    # ---- cross-run continuity (resume)
    bysdk = defaultdict(list)
    for r in runs:
        bysdk[r["sdk"]].append(r)
    xr = []
    for sdk, lst in bysdk.items():
        lst.sort(key=lambda r: r["idx"])
        prev = None
        for r in lst:
            order = [m for m in r["order"] if ctx_of(r["resp"][m]["us"][0]) > 0]
            if not order:
                continue
            if prev is not None:
                pr, pord = prev
                la, fb = pr["resp"][pord[-1]], r["resp"][order[0]]
                ca, cb = ctx_of(la["us"][0]), ctx_of(fb["us"][0])
                comp_between = any(y["mt"] == "system" and y["sub"] == "compact_boundary" for y in pr["rows"][la["last_i"]:]) or \
                    any(y["mt"] == "system" and y["sub"] == "compact_boundary" for y in r["rows"][: fb["first_i"]])
                xr.append({"sid": r["run_id"], "delta": cb - ca, "compact": comp_between, "cr_b": fb["us"][0][2] or 0,
                           "cr_a": la["us"][0][2] or 0, "cc_a": la["us"][0][3] or 0, "gap_s": (fb["first_ts"] - la["last_ts"]) / 1e6,
                           "same_version": (pr["init"] or {}).get("version") == (r["init"] or {}).get("version")})
            prev = (r, order)
    xc = [x for x in xr if not x["compact"]]
    out["cross_run_resume"] = {"pairs": len(xr), "pairs_without_compaction": len(xc),
                               "delta_describe": desc([x["delta"] for x in xc]),
                               "negative_delta": wil(sum(1 for x in xc if x["delta"] < 0), len(xc)),
                               "cache_chain_eq": wil(sum(1 for x in xc if x["cr_b"] == x["cr_a"] + x["cc_a"]), len(xc)),
                               "first_response_cache_read_zero": wil(sum(1 for x in xc if x["cr_b"] == 0), len(xc)),
                               "gap_s_describe": desc([x["gap_s"] for x in xc]),
                               "version_change_pairs": sum(1 for x in xc if not x["same_version"])}
    return out


# ----------------------------------------------------------------------------------------------------------------- main
def main():
    rows, sess = load_rows()
    runs = [derive(r) for r in segment(rows)]
    res = {"probe": "phase_c_aiv_accounting",
           "source": {"messages_rows": len(rows), "sessions_rows": len(sess),
                      "files": ["data/ai-village/claude_code_messages.jsonl.gz", "data/ai-village/claude_code_sessions.jsonl.gz"]},
           "unit": "run (sdk_session_id split at system/init, loader rule); CIs resample runs; all 314 runs used (no A/B split)",
           "prereg": PREREG, "post_hoc_rules": POST_HOC,
           "runs": len(runs), "sdk_sessions": len({r["sdk"] for r in runs}),
           "runs_without_init": sum(1 for r in runs if not r["init"])}
    res["m1_durations"] = m1(runs)
    res["m2_counts_usage"] = m2(runs)
    res["m3_created_at"] = m3(runs, rows, sess)
    res["m4_context"] = m4(runs)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
