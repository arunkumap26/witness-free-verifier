"""Phase E pre-registration: calibration on split A, then write analysis/prereg_e.json.

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.prereg_e_calibration

Reads ONLY:
  analysis/cache/<corpus>_A.parquet (through load_A, which asserts the split), population METADATA tables
  (swechat_population.parquet, aiv_cu_sessions.parquet, swe-chat-pinned sessions.parquet filtered to A ids at read
  time), the A/B sample files (population_by_cell check only), analysis/HELDOUT_MANIFEST.json (counts and hashes, no
  ids), analysis/prereg.json, and committed Phase A-D output JSONs (copied into `references` by explicit JSON path).
Never opens *_B.parquet, *_E.parquet, *_EH.json or any H data: every opened path is recorded and asserted at the end.

Writes:
  analysis/out/phase_e/prereg_e_calibration.json   raw counts and A-split threshold inputs (no interpretation)
  analysis/prereg_e.json                           SPEC_E (prereg_e_common.py) + resolved + references + provenance

What this computes on A, and what it deliberately does NOT compute:
  computed  - length terciles and dominance context per unit; request-id bracket baseline counts and slack quantiles
              (context for the fixed 2 s tolerance; sets no threshold); N1 qualified counts, repeat coverage counts and
              the residual bounds (A 0.5th / 99.5th percentiles: the N1 detector threshold); N2 granularity and tau;
              N3 / N4 / cold-start eligibility counts; N5 eligibility counts per checker and the truncation constants
              (modal harness cut lengths); F3 counts of T_orig integer values excluded as parameters; R2 image-token
              unit per Gemini model string and window counts; R3 commit-claim counts by command class; N6 field gate;
              injector self-tests on a synthetic frame (code checks, no data).
  NOT computed (Phase E outcomes): any Spearman / correlation (N1 rho, N3 rho), any flag or violation rate of a
              detector (N2, N5, R2, R3), any determinism drift, any round-number share, any recall, any tamper result,
              any second-pass statistic.
"""
import gc
import json
import math
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.lib import stats
from analysis.probes import prereg_common as pc
from analysis.probes import prereg_e_common as pe
from analysis.probes import prereg_calibration as pcal

ROOT = pe.ROOT
OUT = pe.OUT_E / "prereg_e_calibration.json"
PREREG_E = pe.PREREG_E_JSON
OPENED = []
COLS = ["session_id", "stratum", "seq", "kind", "ts", "tool", "tool_raw", "call_id", "args", "command", "text",
        "stderr", "native_error", "exit_code", "usage_in", "usage_out", "api_msg_id", "request_id", "model",
        "is_subagent", "agent_id", "parent_call_id", "extra"]
LAT_UNITS = pe.SPEC_E["n1_conditional_duration"]["units"]
N5_UNITS = ["swechat/claude_code", "swechat/codex", "swechat/opencode", "swechat/gemini", "cc_local", "aiv_cc", "aiv_cu"]
FORBIDDEN = re.compile(r"_(?:B|E|H)\.parquet$|_EH\.json$|heldout_ids", re.I)


def opened(path):
    OPENED.append(str(Path(path).as_posix()))
    return path


def load_A(corpus, columns):
    split = "A"
    assert split == "A"
    opened(pe.CACHE / f"{corpus}_{split}.parquet")
    return pe.read_cache(corpus, split, columns, allowed=("A",))


def qd(values, sids=None, qs=(0.005, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 0.995)):
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    out = {"n": int(len(v))}
    if sids is not None:
        out["n_sessions"] = int(len(set(sids)))
    if len(v):
        for q in qs:
            out[f"q{q:g}"] = float(np.quantile(v, q))
    return out


def private_safe(unit, d):
    """cc_local: keep aggregates only (this function is a no-op guard; nothing textual is ever stored)."""
    return d


# ======================================================================================================== per unit
def unit_pairs(unit, u):
    P = pc.make_pairs(u[u.kind.isin(["call", "result"])])
    Q = pe.qualify_pairs(unit, u, P)
    Q["n1"] = [pe.n1_key(unit, k, a, c) for k, a, c in zip(Q.key, Q.args.astype(object), Q.command.astype(object))]
    Q["err"] = [bool(pc.error_classes(unit, k, tr, t, e, n, x, st)[0]) for k, tr, t, e, n, x, st in
                zip(Q.key, Q.tool_raw.astype(object), Q.text_r.astype(object), Q.stderr_r.astype(object),
                    Q.native_error_r.astype(object), Q.exit_code_r.astype(object), Q.stratum.astype(object))]
    return P, Q


def cal_lengths(unit, Q):
    n = Q.groupby("session_id").size()
    if not len(n):
        return {"sessions": 0}
    c1, c2 = np.quantile(n.to_numpy(), [1 / 3, 2 / 3])
    return {"sessions": int(len(n)), "cuts": [float(c1), float(c2)], "rule": "A-split terciles of paired calls/session"}


def cal_dominance(corpus, unit, u, Q):
    w = Q.groupby("session_id").size().to_dict()
    if not w:
        return {}
    out = {}
    kinds = ["repo", "user"] if corpus == "swechat" else ["repo"]
    for kind in kinds:
        if corpus == "swechat":
            opened(pe.SWE_SESSIONS)
        if corpus == "aiv_cu":
            opened(pe.CACHE / "aiv_cu_sessions.parquet")
        cmap = pe.session_cluster_map(corpus, u[u.session_id.isin(list(w))], kind=kind)
        d = pe.dominance(w, cmap)
        out[kind] = {"top_share_events": d.get("top_share_events"), "top_share_sessions": d.get("top_share_sessions"),
                     "top_session_share_events": d.get("top_session_share_events"), "n_clusters": d.get("n_clusters"),
                     "dominated_at_A": d.get("dominated")}
    mm = pe.session_model_map(u[u.session_id.isin(list(w))])
    d = pe.dominance(w, mm)
    out["model"] = {"top_share_events": d.get("top_share_events"), "top_share_sessions": d.get("top_share_sessions"),
                    "n_clusters": d.get("n_clusters"), "dominated_at_A": d.get("dominated")}
    return out


def cal_bracket(unit, u):
    R = pe.bracket_responses(u)
    if not len(R):
        return {"responses_decoded": 0}
    S = pe.bracket_streams(R)
    out = {"responses_decoded": int(len(R)), "sessions": int(R.session_id.nunique()),
           "streams_ge2": int(len(S)), "tol_ms": pe.BRACKET_TOL_MS}
    if len(S):
        out["inconsistent_streams"] = int(S.inconsistent.sum())
        out["inconsistent_rate_by_session"] = pe.rate_by_session(S.inconsistent.to_numpy(), S.session_id.to_numpy())
        cons = S[~S.inconsistent]
        out["slack_U_minus_L_consistent_ms"] = qd((cons.U - cons.L).to_numpy(), cons.session_id.tolist(),
                                                  qs=(0.05, 0.5, 0.95))
        ids = u[u.request_id.notna()].groupby("request_id").session_id.nunique()
        copied = set(ids[ids > 1].index)
        cats = Counter()
        for _, row in S[S.inconsistent].iterrows():
            for c in pe.bracket_benign_categories(u, R, row, copied):
                cats[c] += 1
        out["benign_category_counts_inconsistent_A"] = dict(cats)
        out["request_ids_in_more_than_one_A_session"] = int(len(copied))
    out["note"] = "A-split honest bracket baseline: context for the fixed 2,000 ms tolerance; sets no threshold"
    return out


def cal_n1(unit, Q):
    q = Q[Q.qualified]
    out = {"qualified_by_class": {k: int(v) for k, v in q.cls.value_counts().items()},
           "qualified_sessions": int(q.session_id.nunique())}
    R = pe.n1_residuals(q, unit)
    in_grp = q[q.n1.notna()].groupby(["session_id", "key", "n1"]).seq.transform("size") >= 2
    q2 = q[q.n1.notna()].assign(_g=in_grp)
    cov = {}
    for cls, g in q2.groupby("cls"):
        num = g.groupby("session_id")._g.sum()
        den = q[q.cls == cls].groupby("session_id").size()
        cov[cls] = {"calls_in_repeat_groups": int(num.sum()), "qualified_calls": int(den.sum()),
                    "sessions": int(len(den)),
                    "note": "feasibility count (coverage bound); the B/E RR with CI is a Phase E outcome"}
    out["repeat_coverage_counts_A"] = cov
    if len(R):
        out["residuals"] = {"n": int(len(R)), "n_sessions": int(R.session_id.nunique()),
                            "by_class": {c: int(v) for c, v in
                                         Counter(q.set_index(["session_id", "seq"]).loc[
                                             list(zip(R.session_id, R.seq))].cls).items()},
                            "quantiles": qd(R.residual.to_numpy(), R.session_id.tolist())}
        out["bounds_ok"] = bool(len(R) >= 500 and R.session_id.nunique() >= 5)
    else:
        out["residuals"] = {"n": 0}
        out["bounds_ok"] = False
    return out, R


def cal_latency_counts(unit, u, P):
    """N3 / N4 / cold-start eligibility counts (no statistic)."""
    out = {}
    gaps = pe.n3_gaps(u)
    gs = Counter(s for s, _, _ in gaps)
    out["n3"] = {"gaps": len(gaps), "sessions_with_gaps": len(gs), "sessions_ge_20_gaps": sum(1 for v in gs.values()
                                                                                              if v >= 20)}
    PB = pcal.p1_qualified(unit, u, P)
    W = PB[PB.qualified & (PB.delta_s > 0)]
    if unit in pcal.W_KEYS:
        W = W[W.key.isin(pcal.W_KEYS[unit])]
    else:
        W = W[W.cls == "auto_read"]
    kw = pe.inflight_counts(W) if len(W) else np.array([])
    G = PB[PB.key.isin(pcal.G_TOOLS.get(unit, set())) & ~PB.marker.isin(["cc_permission_denied", "cc_interrupt_reject"])]
    glat = [pcal.g_latency(unit, k, d, x) for k, d, x in zip(G.key, G.delta_s, G._rx)]
    G = G.assign(_glat=glat)
    G = G[[x is not None and np.isfinite(x) and x > 0 for x in G._glat]]
    kg = pe.inflight_counts(G) if len(G) else np.array([])
    out["n4"] = {"W_pairs": int(len(W)), "W_k_ge_2": int((kw >= 2).sum()) if len(kw) else 0,
                 "W_k_ge_2_sessions": int(W[kw >= 2].session_id.nunique()) if len(kw) else 0,
                 "W_k_ge_4": int((kw >= 4).sum()) if len(kw) else 0,
                 "G_pairs": int(len(G)), "G_k_ge_2": int((kg >= 2).sum()) if len(kg) else 0,
                 "G_k_ge_2_sessions": int(G[kg >= 2].session_id.nunique()) if len(kg) else 0,
                 "k_hist_W": {str(k): int(v) for k, v in sorted(Counter(kw.tolist()).items())} if len(kw) else {},
                 "note": "eligibility counts; G here omits the Phase B nested-human-marker exclusion (count only)"}
    return out


def cal_n2(unit, u, P):
    resp = pe.response_table(unit, u)
    g = pe.granularity(resp)
    out = {"granularity": g}
    if unit == "aiv_cu" and len(resp):
        st = u.groupby("session_id").stratum.first()
        resp = resp.assign(_st=resp.session_id.map(st))
        out["granularity_by_stratum"] = {}
        for s, gg in resp.groupby("_st"):
            gs = pe.granularity(gg)
            ent = {"granularity": gs}
            if gs.get("GRANULAR"):
                e = gg[(gg.usage_out >= 50) & (gg.chars_out >= 200)]
                ratio = (e.usage_out / e.chars_out).to_numpy()
                ent["tau"] = float(np.median(ratio)) if len(ratio) else None
                ent["tau_n"] = int(len(ratio))
            out["granularity_by_stratum"][str(s)] = ent
    if g.get("GRANULAR"):
        e = resp[(resp.usage_out >= 50) & (resp.chars_out >= 200)]
        ratio = (e.usage_out / e.chars_out).to_numpy()
        out["tau"] = float(np.median(ratio)) if len(ratio) else None
        out["tau_n"] = int(len(ratio))
        out["tau_sessions"] = int(e.session_id.nunique())
        rc = {(s, c): len(t) for s, c, t in zip(P.session_id, P.call_id.astype(str), P.text_r.astype(object))
              if isinstance(t, str)}
        el = [(s, r) for s, r, c in zip(resp.session_id, resp.resp, resp.last_call_id.astype(str))
              if rc.get((s, c), 0) >= 800]
        out["eligible_responses"] = len(el)
        out["eligible_sessions"] = len({s for s, _ in el})
    out["note"] = "granularity and tau only; the honest flag rate and recall are Phase E outcomes"
    return out


def cal_n5(unit, u, P):
    P = P.copy()
    P["key"] = [pc.tool_key(unit, t, tr) for t, tr in zip(P.tool.astype(object), P.tool_raw.astype(object))]
    if unit == "cc_local":
        P["key"] = [pc.private_key(k) for k in P.key]
    P["n1"] = [pe.n1_key(unit, k, a, c) for k, a, c in zip(P.key, P.args.astype(object), P.command.astype(object))]
    P["err"] = [bool(pc.error_classes(unit, k, tr, t, e, n, x, st)[0]) for k, tr, t, e, n, x, st in
                zip(P.key, P.tool_raw.astype(object), P.text_r.astype(object), P.stderr_r.astype(object),
                    P.native_error_r.astype(object), P.exit_code_r.astype(object), P.stratum.astype(object))]
    out = {}
    dp = pe.determinism_pairs(unit, u, P)
    out["a_determinism_pairs"] = {"pairs": len(dp), "sessions": len({x[0] for x in dp})}
    sort_c, ws_c = Counter(), Counter()
    sort_s, ws_s = defaultdict(set), defaultdict(set)
    trunc = defaultdict(list)
    fam = defaultdict(lambda: [0, set()])
    for sid, k, a, cmd, t in zip(P.session_id, P.key, P.args.astype(object), P.command.astype(object),
                                 P.text_r.astype(object)):
        shellish = k == "shell" or k in pc.CODEX_SHELL_RAW or str(k).endswith("__bash")
        sc = pc.shell_command(unit, k, pc.jl(a) if isinstance(a, str) else {}, cmd) if shellish else None
        if sc:
            for name, fn in (("ls", pe.ls_order_violation), ("git_log", pe.gitlog_order_violation),
                             ("grep_n", pe.grepn_order_violation)):
                if fn(sc, t) is not None:
                    sort_c[name] += 1
                    sort_s[name].add(sid)
            for name in pe.ws_violations(sc, t):
                ws_c[name] += 1
                ws_s[name].add(sid)
            progs = pe.command_programs(sc)
            if progs:
                f = progs[0][0]
                if f == "git":
                    m = re.search(r"\bgit\s+(?:-C\s+\S+\s+|--no-pager\s+)*([a-z\-]+)", progs[0][1])
                    f = "git " + (m.group(1) if m else "?")
                fam[f][0] += 1
                fam[f][1].add(sid)
        if k == "grep" and pe.grepn_order_violation(a, t, is_grep_tool=True) is not None:
            sort_c["grep_n"] += 1
            sort_s["grep_n"].add(sid)
        ti = pe.truncation_info(t)
        if ti:
            ti["tool"] = k if unit != "cc_local" else pc.private_key(k)
            trunc[ti["item"]].append((sid, ti))
    out["b_sort_eligible"] = {k: {"outputs": v, "sessions": len(sort_s[k])} for k, v in sort_c.items()}
    out["d_whitespace_eligible"] = {k: {"outputs": v, "sessions": len(ws_s[k])} for k, v in ws_c.items()}
    tc = {}
    for item, lst in trunc.items():
        ent = {"n": len(lst), "sessions": len({s for s, _ in lst})}
        if item == "cc_chars_mid":
            ent["prefix_u16_mode"] = Counter(x["prefix_u16"] for _, x in lst).most_common(3)
            ent["suffix_u16_mode"] = Counter(x["suffix_u16"] for _, x in lst).most_common(3)
            # diagnostic only (pre-audit definition; not a threshold): newline-stripped lengths
            ent["prefix_u16_stripped_mode"] = Counter(x["prefix_u16_stripped"] for _, x in lst).most_common(3)
            ent["suffix_u16_stripped_mode"] = Counter(x["suffix_u16_stripped"] for _, x in lst).most_common(3)
        elif item == "cc_lines_tail":
            by = defaultdict(list)
            for _, x in lst:
                by[x["tool"]].append(x["prefix_raw"])
            ent["prefix_raw_mode_by_tool"] = {t: Counter(v).most_common(3) for t, v in by.items()}
        elif item == "cc_glob_cap":
            ent["lines_mode"] = Counter(x["lines"] for _, x in lst).most_common(3)
        tc[item] = ent
    out["c_truncation_A"] = tc
    out["e_size_families_A"] = {"families_ge_100_results_ge_10_sessions": sum(1 for v in fam.values()
                                                                              if v[0] >= 100 and len(v[1]) >= 10),
                                "families_total": len(fam)}
    ef = pe.error_fidelity_checks(unit, u, P)
    out["f_error_fidelity_checkable"] = {"frames": len(ef), "sessions": len({x[0] for x in ef}),
                                         "error_results": int(P.err.sum())}
    return out


def cal_cold(unit, Q):
    cs = pe.cold_start_values(Q[Q.qualified])
    return {"eligible_sessions": len(cs)}


def cal_round(unit, u):
    """F3 counts on A: distinct T_orig integer values and how many the parameter exclusion removes (no shares)."""
    u = u.sort_values(["session_id", "seq"])
    torig_first = {}
    torig_any_param = defaultdict(bool)
    for sid, g in u.groupby("session_id", sort=False):
        anc = set()
        for kind, txt, err, a in zip(g.kind, g.text.astype(object), g.stderr.astype(object), g.args.astype(object)):
            if kind in ("result", "user", "system"):
                for t in ([txt] + ([err] if kind == "result" else [])):
                    if isinstance(t, str):
                        anc.update(pc.large_ints(t))
            elif kind == "call":
                for v, origin, pk in pe.classify_args_ints(a):
                    if v in anc:
                        continue
                    if v not in torig_first:
                        torig_first[v] = (origin, pk is not None)
                    torig_any_param[v] |= pk is not None
    n = len(torig_first)
    strict = sum(1 for v in torig_first if torig_any_param[v])
    first = sum(1 for v, (o, p) in torig_first.items() if p)
    json_first = sum(1 for v, (o, p) in torig_first.items() if o == "json_number")
    return {"T_orig_distinct_values": n, "excluded_strict_any_occurrence": strict,
            "excluded_first_occurrence": first, "first_occurrence_json_number": json_first,
            "remaining_strict": n - strict, "remaining_first": n - first,
            "note": "counts only; no round-number share was computed on A"}


def cal_image(u):
    W = pe.image_windows(u)
    if not len(W):
        return {"windows": 0}
    out = {"windows": int(len(W)), "sessions": int(W.session_id.nunique()), "by_model": {}}
    for m, g in W.groupby("model"):
        pos = g[g.d_image > 0].d_image
        mode = Counter(pos.tolist()).most_common(3)
        out["by_model"][str(m)] = {"windows": int(len(g)), "gui_windows": int((g.n_gui >= 1).sum()),
                                   "non_gui_windows": int((g.n_gui == 0).sum()),
                                   "positive_d_image_mode": mode, "unit": float(mode[0][0]) if mode else None,
                                   "sessions": int(g.session_id.nunique())}
    out["note"] = "lattice unit per model string and window counts only; violation rates are Phase E outcomes"
    return out


def cal_git(unit, P):
    cnt = Counter()
    ses = defaultdict(set)
    for sid, k, a, cmd, t in zip(P.session_id, P.key, P.args.astype(object), P.command.astype(object),
                                 P.text_r.astype(object)):
        shellish = k == "shell" or k in pc.CODEX_SHELL_RAW or str(k).endswith("__bash")
        if not shellish or not isinstance(t, str):
            continue
        cl = pe.commit_claims(t)
        if not cl:
            continue
        sc = pc.shell_command(unit, k, pc.jl(a) if isinstance(a, str) else {}, cmd)
        c = pe.git_cmd_class(sc)
        cnt[c] += len(cl)
        ses[c].add(sid)
    return {"claims_by_class": dict(cnt), "sessions_by_class": {k: len(v) for k, v in ses.items()},
            "results": int(len(P)), "note": "counts only; resolution and window checks are Phase E outcomes"}


def field_gate(unit, u, P, res):
    """N6 field gate on A: which required fields exist for the unit."""
    d = P.delta_s.to_numpy() if "delta_s" in P else np.array([])
    stamped = int(np.isfinite(d).sum()) if len(d) else 0
    distinct = int((np.isfinite(d) & (d != 0)).sum()) if len(d) else 0
    req = int(u.request_id.notna().sum())
    dec = int(sum(1 for x in u.request_id.dropna().unique() if pe.decode_req_ms(x) is not None))
    img = int(u.extra.astype(object).map(lambda e: isinstance(e, str) and '"IMAGE"' in e).sum())
    gran = bool(res.get("n2", {}).get("granularity", {}).get("GRANULAR"))
    err_def = unit in pc.SPEC["error_definitions"] and pc.SPEC["error_definitions"][unit].get("primary") is not None
    commits = sum(res.get("r3_git", {}).get("claims_by_class", {}).values()) if res.get("r3_git") else 0
    corpus = unit.split("/")[0]
    return {"pairs": int(len(P)), "pairs_stamped": stamped, "pairs_distinct_stamps": distinct,
            "request_ids": req, "request_ids_decodable": dec, "image_usage_rows": img, "usage_granular": gran,
            "error_definition": bool(err_def), "results_with_text": int(P.text_r.notna().sum()) if len(P) else 0,
            "commit_claims": int(commits), "external_commit_table": corpus == "swechat",
            "raw_structured_counters": unit in ("swechat/claude_code", "cc_local"),
            "external_usage_tally": corpus == "swechat"}


# ======================================================================================================== self-tests
def _enc_req(ms, low=12345):
    v = (int(ms) << 80) | low
    s = ""
    for _ in range(22):
        v, r = divmod(v, 58)
        s = pe._B58[r] + s
    return "req_01" + s


def _synthetic_session():
    t0 = pd.Timestamp("2026-06-01T10:00:00Z")
    rows = []

    def ts(sec):
        return (t0 + pd.Timedelta(seconds=sec)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    seq = 0
    clock = 0.0
    rows.append(dict(session_id="S", seq=seq, kind="user", ts=ts(clock), text="go"))
    for k in range(4):
        seq += 1
        clock += 3.0
        rid = _enc_req((t0 + pd.Timedelta(seconds=clock - 1.0)).value // 1_000_000, low=1000 + k)
        rows.append(dict(session_id="S", seq=seq, kind="call", ts=ts(clock), tool="shell", tool_raw="Bash",
                         call_id=f"c{k}", args=json.dumps({"command": f"ls -1 dir{k}"}), command=f"ls -1 dir{k}",
                         request_id=rid,
                         api_msg_id=f"m{k}"))
        seq += 1
        clock += 0.05
        rows.append(dict(session_id="S", seq=seq, kind="result", ts=ts(clock), call_id=f"c{k}",
                         text="a\nb\nc\nd 42", native_error=False))
    df = pd.DataFrame(rows)
    for c in COLS:
        if c not in df.columns:
            df[c] = None
    df["is_subagent"] = False
    return df[COLS]


def self_tests():
    out = {}
    s = _synthetic_session()
    R = pe.bracket_responses(s)
    S = pe.bracket_streams(R)
    out["honest_stream_consistent"] = bool(len(S) == 1 and not S.inconsistent.iloc[0])
    first_call = s.index[(s.kind == "call")][1]
    s2, _ = pe.atk_time(s, first_call, 30, "response_early")
    out["response_early_30s_detected"] = bool(pe.bracket_streams(pe.bracket_responses(s2)).inconsistent.iloc[0])
    s3, _ = pe.atk_time(s, first_call, 30, "response_late")
    out["response_late_30s_not_detected"] = bool(not pe.bracket_streams(pe.bracket_responses(s3)).inconsistent.iloc[0])
    res1 = s.index[(s.kind == "result")][1]
    s4, _ = pe.atk_time(s, res1, 30, "tail_late")
    out["tail_late_30s_detected"] = bool(pe.bracket_streams(pe.bracket_responses(s4)).inconsistent.iloc[0])
    c0, c2 = s.index[(s.kind == "call")][0], s.index[(s.kind == "call")][2]
    s5 = pe.atk_id_swap(s, c0, c2)
    out["id_swap_detected"] = bool(pe.bracket_streams(pe.bracket_responses(s5)).inconsistent.iloc[0])
    RP = pe.placebo_shift(R, 30_000)
    out["placebo_table_30s_detected"] = bool(pe.bracket_streams(RP).inconsistent.iloc[0])
    out["roll_ids_detected"] = bool(pe.bracket_streams(pe.roll_ids(R)).inconsistent.iloc[0])
    s6, ok = pe.atk_digit(s, res1)
    out["digit_edit_changes_text"] = bool(ok and s6.at[res1, "text"] != s.at[res1, "text"])
    s7, ok = pe.atk_reorder_lines(s, res1, pe.rng_for("selftest"))
    out["reorder_lines_violates_ls_order"] = bool(ok and pe.ls_order_violation("ls -1", s7.at[res1, "text"]))
    s8 = pe.atk_delete_pair(s, c2)
    out["delete_pair_removes_two_rows"] = bool(len(s8) == len(s) - 2)
    donor_c = s.loc[c0].copy()
    donor_r = s.loc[s.index[(s.kind == "result")][0]].copy()
    s9 = pe.atk_insert_pair(s, res1, donor_c, donor_r, mode="consistent", donor_gap_s=1.0, donor_lat_s=0.2)
    out["insert_consistent_adds_two_rows"] = bool(s9 is not None and len(s9) == len(s) + 2)
    s10 = pe.atk_insert_pair(s, res1, donor_c, donor_r, mode="squeezed")
    out["insert_squeezed_adds_two_rows"] = bool(s10 is not None and len(s10) == len(s) + 2)
    s11 = pe.atk_substitute(s, res1, "zzz", donor_error=True)
    out["substitute_sets_text_and_error"] = bool(s11.at[res1, "text"] == "zzz" and s11.at[res1, "native_error"] is True)
    s12 = pe.atk_reorder_pairs(s, c0, c2)
    out["reorder_pairs_swaps_call_ids_content"] = bool(s12.at[c0, "args"] == s.at[c2, "args"])
    # ---- N5 / R2 / R3 helpers on hand-made inputs
    t0 = "2026-06-01T10:00:00.000Z"
    ef_rows = [
        dict(session_id="F", seq=0, kind="call", ts=t0, tool="read", tool_raw="Read", call_id="r1",
             args=json.dumps({"file_path": "/w/pkg/a.py"})),
        dict(session_id="F", seq=1, kind="result", ts=t0, call_id="r1",
             text="     1→import os\n     2→x = 1/0\n"),
        dict(session_id="F", seq=2, kind="call", ts=t0, tool="shell", tool_raw="Bash", call_id="b1",
             args=json.dumps({"command": "python pkg/a.py"}), command="python pkg/a.py"),
        dict(session_id="F", seq=3, kind="result", ts=t0, call_id="b1", native_error=True,
             text="Exit code 1\nTraceback (most recent call last):\n  File \"/w/pkg/a.py\", line 2, in <module>\n"
                  "    x = 1/0\nZeroDivisionError: division by zero"),
    ]
    f = pd.DataFrame(ef_rows)
    for c in COLS:
        if c not in f.columns:
            f[c] = None
    f["is_subagent"] = False
    f = f[COLS]
    PF = pc.make_pairs(f[f.kind.isin(["call", "result"])])
    PF["key"] = ["read", "shell"]
    PF["err"] = [False, True]
    ef = pe.error_fidelity_checks("swechat/claude_code", f, PF)
    out["error_fidelity_faithful_frame"] = bool(len(ef) == 1 and ef[0][4] is True)
    PF2 = PF.copy()
    PF2.loc[PF2.index[1], "text_r"] = PF2.loc[PF2.index[1], "text_r"].replace("line 2", "line 1")
    ef2 = pe.error_fidelity_checks("swechat/claude_code", f, PF2)
    out["error_fidelity_shifted_line_flagged"] = bool(len(ef2) == 1 and ef2[0][4] is False)
    gl = "commit a\nDate:   Mon Jun 1 10:00:00 2026 +0000\n\ncommit b\nDate:   Sun May 31 10:00:00 2026 +0000\n\n" \
         "commit c\nDate:   Sat May 30 10:00:00 2026 +0000\n"
    out["gitlog_ordered_ok"] = pe.gitlog_order_violation("git log -3", gl) is False
    gl_bad = gl.replace("Sun May 31", "Tue Jun 2")
    out["gitlog_violation_flagged"] = pe.gitlog_order_violation("git log -3", gl_bad) is True
    lsl = ("total 8\n-rw-r--r--  1 u  staff    120 Jun  1 10:00 a\n-rw-r--r--  1 u  staff  12000 Jun  1 10:00 b\n"
           "-rw-r--r--  1 u  staff      9 Jun  1 10:00 c\n")
    out["ls_long_aligned_ok"] = pe.ws_violations("ls -la", lsl).get("ls_long_alignment") is False
    out["ls_long_normalized_flagged"] = pe.ws_violations("ls -la", pe.normalize_ws(lsl)).get("ls_long_alignment") is True
    out["image_rule"] = (not pe.image_window_violation(258, 1, 258) and pe.image_window_violation(0, 1, 258)
                         and pe.image_window_violation(258, 0, 258) and pe.image_window_violation(300, 1, 258))
    out["git_window"] = (pe.git_window_ok("2026-06-01T10:00:00.000Z", "2026-06-01T10:00:01.000Z",
                                          "2026-06-01T10:00:00.500Z") is True
                         and pe.git_window_ok("2026-06-01T10:00:00.000Z", "2026-06-01T10:00:01.000Z",
                                              "2026-06-01T09:59:00Z") is False)
    out["git_cmd_classes"] = (pe.git_cmd_class("git add -A && git commit -m x") == "generator"
                              and pe.git_cmd_class("cat out.txt") == "rereader"
                              and pe.git_cmd_class("GIT_COMMITTER_DATE=1 git commit --amend") == "generator_explicit_date")
    det_rows = [
        dict(session_id="D", seq=0, kind="call", ts="2026-06-01T10:00:00.000Z", tool="shell", tool_raw="Bash",
             call_id="d1", args=json.dumps({"command": "git status"}), command="git status"),
        dict(session_id="D", seq=1, kind="result", ts="2026-06-01T10:00:00.100Z", call_id="d1", text="clean"),
        dict(session_id="D", seq=2, kind="call", ts="2026-06-01T10:00:05.000Z", tool="shell", tool_raw="Bash",
             call_id="d2", args=json.dumps({"command": "git status"}), command="git status"),
        dict(session_id="D", seq=3, kind="result", ts="2026-06-01T10:00:05.100Z", call_id="d2", text="clean"),
    ]
    d = pd.DataFrame(det_rows)
    for c in COLS:
        if c not in d.columns:
            d[c] = None
    d["is_subagent"] = False
    d = d[COLS]
    PD = pc.make_pairs(d[d.kind.isin(["call", "result"])])
    PD["key"] = "shell"
    PD["n1"] = [pe.n1_key("swechat/claude_code", "shell", a, c) for a, c in zip(PD.args, PD.command)]
    dp = pe.determinism_pairs("swechat/claude_code", d, PD)
    out["determinism_pair_found"] = bool(len(dp) == 1)
    out["readonly_rejects_writing_find_sort"] = (not pe.readonly_command("find . -name '*.pyc' -delete")
                                                 and not pe.readonly_command("find . -exec rm {} +")
                                                 and not pe.readonly_command("sort -o out.txt in.txt")
                                                 and pe.readonly_command("find . -name '*.py'")
                                                 and pe.readonly_command("sort -n in.txt"))
    _ti = pe.truncation_info("x\n" * 3 + "\n\n... [9 characters truncated] ...\n\n" + "\ny")
    out["truncation_raw_lengths"] = bool(_ti and _ti["prefix_u16"] == 8 and _ti["suffix_u16"] == 4
                                         and _ti["prefix_u16_stripped"] == 5 and _ti["suffix_u16_stripped"] == 1)
    out["applicable_N4_none"] = not any(pe.applicable(a, "N4") for a in pe.ATTACK_FIELDS)
    out["applicable_bracket_ids"] = pe.applicable("id_swap_adjacent", "R1_BRACKET")
    out["n7_label_example"] = pe.n7_cell_label(100, 90, 100, 2)[0] == "DETECTS"
    out["all_passed"] = all(v for k, v in out.items() if isinstance(v, bool))
    return out


# ======================================================================================================== references
def jget(obj, path):
    cur = obj
    for p in path:
        if isinstance(cur, dict):
            cur = cur.get(p)
        elif isinstance(cur, list) and isinstance(p, int) and p < len(cur):
            cur = cur[p]
        else:
            return None
    return cur


def references():
    """Numbers quoted by PREREG_E.md that come from committed earlier outputs, copied by explicit JSON path."""
    ref = {}

    def load(rel):
        p = ROOT / rel
        opened(p)
        return json.loads(p.read_text(encoding="utf-8"))
    p1 = load("analysis/out/probe_1.json")
    for u in ("swechat/claude_code", "swechat/opencode", "cc_local"):
        v = p1["verdicts"].get(u, {})
        ref[f"P1_verdict/{u}"] = {"source": f"analysis/out/probe_1.json verdicts.{u}", "verdict": v.get("verdict"),
                                  "fp_share": jget(v, ["deciding", "fp_share"]), "auc": jget(v, ["deciding", "auc"]),
                                  "G_eligible": jget(v, ["deciding", "G_eligible"]),
                                  "G_eligible_sessions": jget(v, ["deciding", "G_eligible_sessions"]),
                                  "floor_step_label": v.get("floor_step_label")}
    fs = p1["units"]["swechat/claude_code"]["floor_step_change"]
    ref["floor_steps_B"] = {"source": "analysis/out/probe_1.json units.swechat/claude_code.floor_step_change",
                            "eligible_series": fs["eligible_series"], "steps": fs["steps"],
                            "eligible_sessions": fs["eligible_sessions"], "sessions_with_step": fs["sessions_with_step"],
                            "step_share_wilson": fs["step_share_wilson"], "steps_by_direction": fs["steps_by_direction"],
                            "label": fs["label"]}
    ref["cc_local_G_bimodal"] = {"source": "analysis/out/probe_1.json units.cc_local.separability.G_r_log_histogram",
                                 "G_r_log_histogram": jget(p1, ["units", "cc_local", "separability",
                                                                "G_r_log_histogram"])}
    p3 = load("analysis/out/probe_3.json")
    ref["P3_zero_error_B"] = {"source": "analysis/out/probe_3.json units.swechat/claude_code.zero_error_tail.L75",
                              **{k: p3["units"]["swechat/claude_code"]["zero_error_tail"]["L75"][k]
                                 for k in ("L", "n_long", "n_zero", "Z", "E0", "Z_over_E0")},
                              "verdict": jget(p3, ["units", "swechat/claude_code", "verdict", "zero_error_tail",
                                                   "verdict"])}
    p4 = load("analysis/out/probe_4.json")
    for u in ("swechat/claude_code", "cc_local"):
        ref[f"P4_round_B/{u}"] = {
            "source": f"analysis/out/probe_4.json units.{u}.ints.main.<class>.round.last_0",
            "T_orig_last_0": jget(p4, ["units", u, "ints", "main", "T_orig", "round", "last_0"]),
            "M_all_last_0": jget(p4, ["units", u, "ints", "main", "M_all", "round", "last_0"]),
            "T_by_origin_post_hoc": jget(p4, ["units", u, "post_hoc_descriptive", "ints_T_by_origin", "T_orig"]),
            "verdict": jget(p4, ["units", u, "verdicts", "round_numbers_secondary", "verdict"])
                       or jget(p4, ["units", u, "verdicts", "round_numbers_secondary", "verdict_uncapped"])}
    p2 = load("analysis/out/probe_2.json")
    for u, st in (("swechat/claude_code", "main"), ("swechat/claude_code", "sub"), ("swechat/opencode", "sub"),
                  ("swechat/codex", "sub"), ("aiv_cc", "main")):
        v = jget(p2, ["verdicts", u, st]) or {}
        ref[f"P2_verdict/{u}/{st}"] = {"source": f"analysis/out/probe_2.json verdicts.{u}.{st}",
                                       **{k: v.get(k) for k in ("verdict", "deciding_statistic", "value", "ci", "k",
                                                                "n", "n_sessions")}}
    ic = load("analysis/out/phase_c/ids_and_clocks_in_ids.json")
    b = jget(ic, ["bracket", "swechat", "anthropic_req", "claude_code"]) or {}
    ref["bracket_B_committed_lens"] = {
        "source": "analysis/out/phase_c/ids_and_clocks_in_ids.json bracket.swechat.anthropic_req.claude_code",
        **{k: b.get(k) for k in ("n_responses", "streams_ge2_responses", "streams_inconsistent", "tol_ms",
                                 "inconsistent_rate_by_session", "U_minus_L_consistent_describe_ms")}}
    ref["bracket_x_copies_swechat"] = {"source": "analysis/out/phase_c/ids_and_clocks_in_ids.json "
                                                 "bracket_x_copies.swechat",
                                       "value": jget(ic, ["bracket_x_copies", "swechat"])}
    cb = jget(ic, ["bracket", "cc_local", "anthropic_req", "cc_local"]) or {}
    ref["bracket_cc_local_committed_lens"] = {"source": "analysis/out/phase_c/ids_and_clocks_in_ids.json "
                                                        "bracket.cc_local.anthropic_req.cc_local",
                                              **{k: cb.get(k) for k in ("streams_ge2_responses",
                                                                        "streams_inconsistent")}}
    rk = load("analysis/out/phase_d/ranking.json")
    obs = {r["key"]: r["observation"] for r in rk["final_ranking"]}
    t = obs.get("bracket", "")

    def grab(rx, text, cast=int):
        m = re.search(rx, text)
        return [cast(x.replace(",", "")) for x in m.groups()] if m else None
    ref["placebo_skeptic_text"] = {
        "source": "analysis/out/phase_d/ranking.json final_ranking[key=bracket].observation (text; the counts came from "
                  "the skeptic's uncommitted scratch scripts o5.py/o5b.py/o5c.py: provenance [S])",
        "honest": grab(r"all but (\d+) of ([\d,]+) swechat Claude Code streams", t),
        "back_5s": grab(r"5 s earlier flags ([\d,]+)/([\d,]+)", t),
        "back_30s": grab(r"30 s earlier flags ([\d,]+)/([\d,]+)", t),
        "roll_all": grab(r"Rolling every response's id by one flags ([\d,]+)", t),
        "cc_local_honest": grab(r"cc_local: (\d+)/(\d+)", t)}
    g = obs.get("git", "")
    ref["git_nonresolution"] = {"source": "ranking.json final_ranking[key=git].observation (text)",
                                "non_resolving": grab(r"([\d,]+)/([\d,]+) = 0\.358", g),
                                "out_of_window": grab(r"Out of window: (\d+)/([\d,]+)", g),
                                "reread_explained": grab(r"as (\d+) cat/tail/head/grep re-reads", g)}
    ld = obs.get("ledger", "")
    ref["ledger_unmatched"] = {"source": "ranking.json final_ranking[key=ledger].observation (text)",
                               "unmatched": grab(r"unmatched ([\d,]+)/([\d,]+)", ld)}
    im = obs.get("image", "")
    ref["image_B"] = {"source": "ranking.json final_ranking[key=image].observation (text)",
                      "gui_misses": grab(r"misses (\d+)/([\d,]+)", im),
                      "non_gui_increments": grab(r"in 0 of ([\d,]+) non-GUI windows", im)}
    du = obs.get("dual", "")
    ref["dual_population"] = {"source": "ranking.json final_ranking[key=dual].observation (text)",
                              "numlines_agree": grab(r"in ([\d,]+)/([\d,]+) = 0\.9954", du),
                              "mismatch_formats": grab(r"all (\d+) mismatches \((\d+) files\)", du)}
    ix = load("analysis/out/phase_c/_index.json")
    txt = json.dumps(ix)
    m = re.search(r"its B sessions are (\d+) opencode and (\d+) codex", txt)
    ref["opencode_one_repo"] = {"source": "analysis/out/phase_c/_index.json (outliers text: one repo's B sessions, [S]); "
                                          "denominator = prereg.json population_B.sessions.swechat/opencode",
                                "one_repo_B_opencode_sessions": int(m.group(1)) if m else None,
                                "one_repo_B_codex_sessions": int(m.group(2)) if m else None}
    man = load("analysis/HELDOUT_MANIFEST.json")
    ref["heldout_manifest_counts"] = {"source": "analysis/HELDOUT_MANIFEST.json corpora.<c>.n_E/n_H (no ids read)",
                                      **{c: {"n_E": v["n_E"], "n_H": v["n_H"]} for c, v in man["corpora"].items()}}
    pj = load("analysis/prereg.json")
    ref["population_B"] = {"source": "analysis/prereg.json population_B.sessions", **pj["population_B"]["sessions"]}
    return ref, pj


def e_projection(ref):
    """Projected E sessions per unit = n_E(corpus) x B_unit / B_corpus (a projection from counts, not a measurement)."""
    pb = {k: v for k, v in ref["population_B"].items() if k != "source"}
    out = {}
    for corpus in ("swechat", "aiv_cu"):
        nE = ref["heldout_manifest_counts"][corpus]["n_E"]
        units = {k: v for k, v in pb.items() if k == corpus or k.startswith(corpus + "/")}
        tot = sum(v for v in units.values() if isinstance(v, (int, float)))
        for u, v in units.items():
            if isinstance(v, (int, float)) and tot:
                out[u] = round(nE * v / tot, 1)
    out["rule"] = "n_E(corpus) x B_unit / B_corpus_total; projection only"
    return out


# ======================================================================================================== main
def calibrate_unit(corpus, unit, u):
    """All A-split calibration for one unit (also used for any new corpus's A split)."""
    res = {"sessions_A": int(u.session_id.nunique())}
    P, Q = unit_pairs(unit, u)
    res["length_terciles"] = cal_lengths(unit, Q)
    res["dominance_context"] = cal_dominance(corpus, unit, u, Q)
    if u.request_id.notna().any():
        res["bracket"] = cal_bracket(unit, u)
    R = pd.DataFrame()
    if unit in LAT_UNITS:
        res["n1"], R = cal_n1(unit, Q)
        res["latency_counts"] = cal_latency_counts(unit, u, P)
        res["cold_start"] = cal_cold(unit, Q)
    res["n2"] = cal_n2(unit, u, P)
    if unit in N5_UNITS:
        res["n5"] = cal_n5(unit, u, P)
    if unit in pc.SPEC["probe4"]["units"]["testable"]:
        res["f3_round"] = cal_round(unit, u)
    if corpus == "aiv_cu":
        res["r2_image"] = cal_image(u[u.stratum.astype(str).str.startswith("gemini")])
    if corpus in ("swechat", "cc_local", "aiv_cc"):
        Pk = P.assign(key=[pc.tool_key(unit, t, tr) for t, tr in zip(P.tool.astype(object), P.tool_raw.astype(object))])
        res["r3_git"] = cal_git(unit, Pk)
    res["n6_field_gate"] = field_gate(unit, u, P, res)
    return res, R


def main():
    t0 = time.time()
    pe.OUT_E.mkdir(parents=True, exist_ok=True)
    cal = {"script": "analysis/probes/prereg_e_calibration.py", "split": "A only (asserted; B/E/EH/H never opened)",
           "not_computed": "Phase E outcomes: N1/N3 correlations, detector flag or violation rates (N2, N5, R2, R3), "
                           "determinism drift, round-number shares, recalls, tamper results, second-pass statistics",
           "units": {}}
    resid_pool = []
    for corpus in ("swechat", "cc_local", "aiv_cc", "aiv_cu", "whowhen"):
        df = load_A(corpus, COLS)
        if corpus == "swechat":
            opened(pe.CACHE / "swechat_population.parquet")
        for unit, u in pc.unit_frames(corpus, df).items():
            u = u.reset_index(drop=True)
            print(f"[{time.time() - t0:6.1f}s] {unit}: {len(u)} rows", flush=True)
            res, R = calibrate_unit(corpus, unit, u)
            cal["units"][unit] = private_safe(unit, res)
            if len(R):
                resid_pool.append(R.assign(unit=unit))
        del df
        gc.collect()
    # ------------------------------------------------------------------------------------------ population cells check
    pcheck = {}
    for corpus in ("swechat", "aiv_cu"):
        opened(pe.SAMPLES / f"{corpus}.json")
        a = json.loads((pe.SAMPLES / f"{corpus}.json").read_text(encoding="utf-8"))
        if corpus == "aiv_cu":
            opened(pe.CACHE / "aiv_cu_sessions.parquet")
        cells = pe.population_cells(corpus)
        mine = Counter(cells.values())
        ref_cells = a.get("population_by_cell", {})
        pcheck[corpus] = {"cells_match_sample_file": dict(mine) == {k: int(v) for k, v in ref_cells.items()},
                          "n_cells": len(mine), "n_population": len(cells)}
        del a
    cal["ac5_population_cells_check"] = pcheck
    cal["self_tests"] = self_tests()
    ref, pj = references()
    cal["references_preview_keys"] = sorted(ref)
    # ------------------------------------------------------------------------------------------ resolved
    resolved = {"length_terciles_A": {}, "dominance_context_A": {}, "n1": {}, "n2": {}, "n5": {"truncation_constants": {}},
                "image_units_A": {}, "n7": {"floor_thresholds": {}}, "n6_field_gate_A": {}, "bracket_A": {},
                "f3_counts_A": {}, "e_projection": e_projection(ref)}
    pooled = pd.concat(resid_pool, ignore_index=True) if resid_pool else pd.DataFrame()
    pooled_bounds = None
    if len(pooled):
        pooled_bounds = [float(np.quantile(pooled.residual, 0.005)), float(np.quantile(pooled.residual, 0.995))]
    for unit, r in cal["units"].items():
        resolved["length_terciles_A"][unit] = r["length_terciles"]
        resolved["dominance_context_A"][unit] = r["dominance_context"]
        resolved["n6_field_gate_A"][unit] = r["n6_field_gate"]
        if "bracket" in r:
            resolved["bracket_A"][unit] = r["bracket"]
        if "f3_round" in r:
            resolved["f3_counts_A"][unit] = r["f3_round"]
        if "n1" in r:
            q = r["n1"]["residuals"].get("quantiles", {})
            if r["n1"]["bounds_ok"]:
                b = {"bounds": [q["q0.005"], q["q0.995"]], "source": "unit", "n_A": q["n"],
                     "sessions_A": q.get("n_sessions")}
            else:
                b = {"bounds": pooled_bounds, "source": "pooled bounds (unit has < 500 A residuals or < 5 sessions)",
                     "n_A": q.get("n", 0), "sessions_A": q.get("n_sessions", 0),
                     "pooled_n_A": int(len(pooled)), "pooled_sessions_A": int(pooled.session_id.nunique())}
            resolved["n1"][unit] = b
        n2 = r.get("n2", {})
        resolved["n2"][unit] = {"GRANULAR": n2.get("granularity", {}).get("GRANULAR"),
                                "G1_share_both": n2.get("granularity", {}).get("G1_share_both"),
                                "G2_median_usage_out": n2.get("granularity", {}).get("G2_median_usage_out"),
                                "responses_A": n2.get("granularity", {}).get("responses"),
                                "tau": n2.get("tau"), "tau_n_A": n2.get("tau_n")}
        if "granularity_by_stratum" in n2:
            resolved["n2"][unit]["by_stratum"] = {
                s: {"GRANULAR": e["granularity"].get("GRANULAR"), "G1_share_both": e["granularity"].get("G1_share_both"),
                    "G2_median_usage_out": e["granularity"].get("G2_median_usage_out"),
                    "responses_A": e["granularity"].get("responses"), "tau": e.get("tau"), "tau_n_A": e.get("tau_n")}
                for s, e in n2["granularity_by_stratum"].items()}
        tc = r.get("n5", {}).get("c_truncation_A", {})
        for item, ent in tc.items():
            d = resolved["n5"]["truncation_constants"].setdefault(item, {})
            d[unit] = ent
        if "r2_image" in r:
            for m, ent in r["r2_image"].get("by_model", {}).items():
                resolved["image_units_A"][m] = {"unit": ent["unit"], "windows_A": ent["windows"],
                                                "sessions_A": ent["sessions"], "mode_A": ent["positive_d_image_mode"]}
    # truncation constants: pooled modes over CC-format units (one harness)
    tcc = {}
    for item, per in resolved["n5"]["truncation_constants"].items():
        if item == "cc_chars_mid":
            pre = Counter()
            suf = Counter()
            n = 0
            for unit, ent in per.items():
                n += ent["n"]
                for v, c in ent["prefix_u16_mode"]:
                    pre[v] += c
                for v, c in ent["suffix_u16_mode"]:
                    suf[v] += c
            tcc[item] = {"prefix_u16": pre.most_common(1)[0][0] if pre else None,
                         "suffix_u16": suf.most_common(1)[0][0] if suf else None, "n_A": n,
                         "status": "OK" if n >= 5 else "INSUFFICIENT_N (item NOT_RUN)"}
        elif item == "cc_glob_cap":
            ln = Counter()
            n = 0
            for unit, ent in per.items():
                n += ent["n"]
                for v, c in ent["lines_mode"]:
                    ln[v] += c
            tcc[item] = {"lines": ln.most_common(1)[0][0] if ln else None, "n_A": n,
                         "status": "OK" if n >= 5 else "INSUFFICIENT_N (item NOT_RUN)"}
        elif item == "cc_lines_tail":
            by = defaultdict(Counter)
            n = 0
            for unit, ent in per.items():
                n += ent["n"]
                for tool, lst in ent["prefix_raw_mode_by_tool"].items():
                    for v, c in lst:
                        by[tool][v] += c
            tcc[item] = {"prefix_raw_by_tool": {t: c.most_common(1)[0][0] for t, c in by.items()}, "n_A": n,
                         "status": "OK" if n >= 5 else "INSUFFICIENT_N (item NOT_RUN)"}
    resolved["n5"]["truncation_constants_pooled"] = tcc
    floors = pj["resolved"]["probe1"]["floors"]
    for unit, tools in floors.items():
        for tool, ent in tools.items():
            if "p1" in ent:
                resolved["n7"]["floor_thresholds"].setdefault(unit, {})[tool] = {"threshold_s": ent["p1"], "from": "p1"}
            elif "p5" in ent:
                resolved["n7"]["floor_thresholds"].setdefault(unit, {})[tool] = {"threshold_s": ent["p5"] / 2,
                                                                                 "from": "p5/2"}
    resolved["n7"]["floor_source"] = "analysis/prereg.json resolved.probe1.floors (Phase B, split A)"
    resolved["n7"]["generation_rate_source"] = "analysis/prereg.json resolved.probe1.generation_rate (Phase B, split A)"
    resolved["n7"]["long_session_source"] = "analysis/prereg.json resolved.probe3.long_session (Phase B, split A)"
    resolved["n7"]["depth_threshold_source"] = "analysis/prereg.json resolved.probe2.depth_threshold (Phase B, split A)"
    # R2 unit rule (SPEC_E a1.proposal_rules.R2_specific)
    by_model = {}
    for unit, r in cal["units"].items():
        for m, ent in r.get("r2_image", {}).get("by_model", {}).items():
            by_model[m] = ent
    fam_counts = defaultdict(Counter)
    for m, ent in by_model.items():
        fam = "gemini-2.5" if m.startswith("gemini-2.5") else "gemini-3" if m.startswith("gemini-3") else m
        for v, c in ent["positive_d_image_mode"]:
            fam_counts[fam][v] += c
    fam_unit = {f: (c.most_common(1)[0][0] if c else None) for f, c in fam_counts.items()}
    rule = {}
    for m, ent in by_model.items():
        fam = "gemini-2.5" if m.startswith("gemini-2.5") else "gemini-3" if m.startswith("gemini-3") else m
        npos = sum(c for _, c in ent["positive_d_image_mode"])
        if ent["gui_windows"] >= 10 and npos == 0:
            rule[m] = {"unit": None, "status": "NOT_TESTABLE (>= 10 GUI windows, no positive increment on A)",
                       "gui_windows_A": ent["gui_windows"]}
        elif npos >= 20:
            rule[m] = {"unit": ent["unit"], "status": "model unit", "positive_windows_A": npos}
        else:
            rule[m] = {"unit": fam_unit.get(fam), "status": f"family unit ({fam})", "positive_windows_A": npos,
                       "gui_windows_A": ent["gui_windows"]}
    resolved["image_units_A"]["rule"] = {"family_units": fam_unit, "per_model": rule,
                                         "absent_from_A": "family unit; a family absent from A is NOT_TESTABLE"}
    cal["resolved_preview"] = resolved
    cal["runtime_s"] = round(time.time() - t0, 1)
    # ------------------------------------------------------------------------------------------ guard
    bad = [p for p in OPENED if FORBIDDEN.search(p)]
    assert not bad, f"forbidden files opened: {bad}"
    cal["opened_files"] = sorted(set(OPENED))
    OUT.write_text(json.dumps(cal, indent=1, default=str), encoding="utf-8")
    # ------------------------------------------------------------------------------------------ prereg_e.json
    spec = json.loads(json.dumps(pe.SPEC_E))
    spec["regexes"] = pe.RX_E
    spec["param_context"] = pe.PARAM_CONTEXT
    spec["constants"] = {"GRID_D": pe.GRID_D, "GRID_D_LATE_CHECK": pe.GRID_D_LATE_CHECK, "REWRITE_K": pe.REWRITE_K,
                         "MATCHED_BYTES_TOL": pe.MATCHED_BYTES_TOL, "N7_CAP_SESSIONS": pe.N7_CAP_SESSIONS,
                         "N7_MIN_SESSIONS": pe.N7_MIN_SESSIONS, "DOM_SHARE": pe.DOM_SHARE,
                         "DOM_SESSION": pe.DOM_SESSION, "AUDIT_K": pe.AUDIT_K, "AUDIT_FAIL": pe.AUDIT_FAIL,
                         "BRACKET_TOL_MS": pe.BRACKET_TOL_MS, "READONLY_PROGRAMS": sorted(pe.READONLY_PROGRAMS),
                         "GIT_READONLY_SUB": sorted(pe.GIT_READONLY_SUB), "TIME_DEPENDENT_RX": pe.TIME_DEPENDENT_RX.pattern,
                         "N1_VOLATILE_ARG_KEYS": list(pe.N1_VOLATILE_ARG_KEYS), "SEED": pe.SEED, "SEED_E": pe.SEED_E,
                         "SEED_NEW_CORPUS": pe.SEED_NEW_CORPUS}
    spec["resolved"] = resolved
    spec["references"] = ref
    inputs = {}
    for p in sorted(set(OPENED)):
        pp = Path(p)
        if pp.exists() and pp.is_file() and pp.stat().st_size < 3_000_000_000:
            try:
                rel = pp.resolve().relative_to(ROOT).as_posix()
            except ValueError:
                rel = pp.as_posix()
            inputs[rel] = pe.sha256_file(pp)
    spec["provenance"] = {
        "generated_by": "analysis/probes/prereg_e_calibration.py",
        "spec_module": "analysis/probes/prereg_e_common.py",
        "spec_module_sha256": pe.sha256_file(ROOT / "analysis" / "probes" / "prereg_e_common.py"),
        "spec_module_sha256_lf": pe.sha256_lf(ROOT / "analysis" / "probes" / "prereg_e_common.py"),
        "calibration_script_sha256_lf": pe.sha256_lf(ROOT / "analysis" / "probes" / "prereg_e_calibration.py"),
        "calibration_script_sha256": pe.sha256_file(ROOT / "analysis" / "probes" / "prereg_e_calibration.py"),
        "calibration_json": "analysis/out/phase_e/prereg_e_calibration.json",
        "calibration_json_sha256": pe.sha256_file(OUT),
        "phase_b_prereg_json_sha256": pe.sha256_file(ROOT / "analysis" / "prereg.json"),
        "phase_b_spec_module_sha256": pe.sha256_file(ROOT / "analysis" / "probes" / "prereg_common.py"),
        "phase_b_spec_module_matches_prereg_json": pe.sha256_file(ROOT / "analysis" / "probes" / "prereg_common.py")
        == pj["provenance"]["spec_module_sha256"],
        "inputs_sha256": inputs,
        "phase_e_must": "call prereg_e_common.check_frozen() (asserts the LF-normalised sha256 of prereg_e_common.py == "
                        "provenance.spec_module_sha256_lf) before any measurement; copy prereg_e.json's sha256 into every "
                        "output",
    }
    PREREG_E.write_text(json.dumps(spec, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"done in {time.time() - t0:.1f}s -> {OUT} and {PREREG_E}")


if __name__ == "__main__":
    main()
