"""Phase B, Probe 3: environment pushback (surprise rate).

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.probe_3

Pre-registered in analysis/PREREG.md section 3 and analysis/prereg.json `probe3` (commit 3df8d28). Every definition used
here comes from analysis/probes/prereg_common.py (imported, never edited); every threshold comes from analysis/prereg.json.
The script refuses to run if sha256(prereg_common.py) != prereg.json provenance.spec_module_sha256.

Reads only analysis/cache/<corpus>_B.parquet (call and result rows, needed columns), swechat_population.parquet (format)
and, for the aiv_cc split-overlap count required by prereg.json global.aiv_cc_rule, the session_id column of
aiv_cc_A.parquet. Writes raw numbers only to analysis/out/probe_3.json. Interpretation: analysis/notes/probe_3.md.

What it measures, per unit:
  - per-call primary error rate (prereg error_definitions.<unit>.primary via prereg_common.error_classes), per class and
    per tool_key;
  - the distribution of per-session error rates (quantiles, linear and log histograms) and of calls per session;
  - the zero-error tail: Z = share of long sessions (n_calls >= L75) with zero primary errors, E0, Z/E0, Z at L90,
    Z per error class, and a description of the zero-error long sessions;
  - retry reaction: R_fail, R_ok, effect = R_fail - R_ok (session-resampled CI), and the share of calls that are a retry
    of an immediately preceding failed call;
  - early versus late error rate within sessions with >= 20 calls (descriptive, no verdict);
  - verdicts computed mechanically from prereg.json probe3.verdict.
cc_local is private: only aggregates leave this script, and its tool keys pass through private_key().
"""
import hashlib
import json
import math
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from analysis.lib import stats
from analysis.probes import prereg_common as pc

PREREG_PATH = pc.ROOT / "analysis" / "prereg.json"
SPEC_PATH = pc.ROOT / "analysis" / "probes" / "prereg_common.py"
OUT = pc.ROOT / "analysis" / "out" / "probe_3.json"

LOAD_COLS = ["session_id", "seq", "kind", "tool", "tool_raw", "call_id", "args", "command", "text", "stderr",
             "native_error", "exit_code", "is_subagent", "agent_id", "stratum"]
CC_APART = ("cc_permission_denied", "cc_interrupt_reject")
RATE_BINS = [0.0, 0.005, 0.01, 0.02, 0.05, 0.10, 0.20, 0.50, 1.0]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ============================================================================================================ helpers
def wil(k, n):
    p, lo, hi = stats.wilson(int(k), int(n))
    return {"k": int(k), "n": int(n), "share": p, "lo": lo, "hi": hi}


def rate(num_by_s, den_by_s, min_n=None):
    """cluster_rate plus the pre-registered reportability rule and zero-count Wilson bounds."""
    num = np.asarray(num_by_s, dtype=float)
    den = np.asarray(den_by_s, dtype=float)
    r = stats.cluster_rate(num, den)
    mn = min_n or PRE["global"]["min_n"]["rate_reportable"]
    den_tot, n_s = float(den.sum()), int((den > 0).sum())
    r["reportable"] = bool(den_tot >= mn["den_min"] and n_s >= mn["sessions_min"])
    if not r["reportable"]:
        r = {"num": float(num.sum()), "den": den_tot, "n_sessions": n_s, "reportable": False, "label": "insufficient n"}
        return r
    if num.sum() == 0:
        r["zero_count_wilson_hi_per_event"] = stats.wilson(0, int(den_tot))[2]
        r["zero_count_wilson_hi_per_session"] = stats.wilson(0, n_s)[2]
    return r


def boot_diff(a_num, a_den, b_num, b_den):
    """statistic_ci for (sum a_num / sum a_den) - (sum b_num / sum b_den), sessions resampled together.
    Uses the same draw scheme as stats.cluster_rate (default_rng(SEED).integers(0, n, (N_BOOT, n)))."""
    arrs = [np.asarray(x, dtype=float) for x in (a_num, a_den, b_num, b_den)]
    n = len(arrs[0])
    out = {"n_sessions": int(n), "n_boot": stats.N_BOOT, "seed": stats.SEED}
    if n == 0 or arrs[1].sum() == 0 or arrs[3].sum() == 0:
        out.update({"value": None, "lo": None, "hi": None, "valid_draws": 0, "ci_reported": False})
        return out
    out["value"] = float(arrs[0].sum() / arrs[1].sum() - arrs[2].sum() / arrs[3].sum())
    rng = np.random.default_rng(stats.SEED)
    idx = rng.integers(0, n, size=(stats.N_BOOT, n))
    an, ad, bn, bd = (x[idx].sum(1) for x in arrs)
    ok = (ad > 0) & (bd > 0)
    vals = an[ok] / ad[ok] - bn[ok] / bd[ok]
    out["valid_draws"] = int(ok.sum())
    if ok.sum() >= 900:
        out.update({"lo": float(np.quantile(vals, 0.025)), "hi": float(np.quantile(vals, 0.975)), "ci_reported": True})
    else:
        out.update({"lo": None, "hi": None, "ci_reported": False})
    return out


def q_reportable(n, n_s, q):
    mq = PRE["global"]["min_n"]["quantile_reportable"]
    need = mq["p50"] if q in (0.25, 0.5, 0.75) else mq["p5_p95"] if q in (0.05, 0.10, 0.90, 0.95) else mq["p1_p99"]
    return n >= need[0] and n_s >= need[1]


def dist_block(values, session_ids=None, ci_qs=(0.5, 0.75, 0.90)):
    """describe() + linear bins on [0,1] + log histogram + cluster_quantile CIs where reportable."""
    v = np.asarray(values, dtype=float)
    out = {"describe": stats.describe(v, qs=(0.0, 0.05, 0.10, 0.25, 0.5, 0.75, 0.90, 0.95, 1.0))}
    if len(v) == 0:
        return out
    out["n_exactly_zero"] = int((v == 0).sum())
    bins = []
    for lo, hi in zip(RATE_BINS[:-1], RATE_BINS[1:]):
        bins.append({"lo_excl": lo, "hi_incl": hi, "count": int(((v > lo) & (v <= hi)).sum())})
    out["linear_bins_positive"] = bins
    out["log10_histogram"] = stats.log_histogram(v, per_decade=4)
    if session_ids is not None:
        sid = np.asarray(session_ids)
        n_s = len(set(sid.tolist()))
        cis = {}
        for q in ci_qs:
            if q_reportable(len(v), n_s, q):
                cis[f"p{int(q * 100)}"] = stats.cluster_quantile(v, sid, q)
            else:
                cis[f"p{int(q * 100)}"] = {"label": "insufficient n", "n": int(len(v)), "n_sessions": n_s}
        out["quantile_cis"] = cis
    return out


def count_hist(values):
    v = np.asarray(values, dtype=float)
    return {"describe": stats.describe(v, qs=(0.0, 0.10, 0.25, 0.5, 0.75, 0.90, 0.95, 0.99, 1.0)),
            "log10_histogram": stats.log_histogram(v, per_decade=4)}


def canon_args(a):
    if not isinstance(a, str):
        return None
    try:
        return json.dumps(json.loads(a), sort_keys=True, ensure_ascii=False)
    except ValueError:
        return a


# ============================================================================================================ loading
def load_corpus(corpus):
    df = pc.load_split(corpus, "B", LOAD_COLS, filters=[("kind", "in", ["call", "result"])])
    return df


# ============================================================================================================ per unit
def error_spec(unit):
    if unit.startswith("whowhen"):
        return "whowhen"
    return unit


def classify_pairs(unit, P):
    upc = error_spec(unit)
    raw_keys = [pc.tool_key(upc, t, tr) for t, tr in zip(P.tool.astype(object), P.tool_raw.astype(object))]
    keys = [pc.private_key(k) for k in raw_keys] if unit == "cc_local" else raw_keys
    res = [pc.error_classes(upc, k, tr, t, e, n, x, st) for k, tr, t, e, n, x, st in
           zip(raw_keys, P.tool_raw.astype(object), P.text_r.astype(object), P.stderr_r.astype(object),
               P.native_error_r.astype(object), P.exit_code_r.astype(object), P.stratum.astype(object))]
    P = P.drop(columns=[c for c in ("text_r", "stderr_r", "text", "stderr") if c in P.columns])
    P = P.assign(key=keys, raw_key=raw_keys,
                 err=[bool(r[0]) if r[0] is not None else False for r in res],
                 defined=[r[0] is not None for r in res],
                 ecls=[r[1] for r in res],
                 iclass=[pc.tool_class(t) if isinstance(t, str) else "other" for t in P.tool.astype(object)],
                 is_shell=[t == "shell" for t in P.tool.astype(object)])
    return P


def class_flags(unit, P):
    """{class_name: boolean array} for the class breakdown (primary and apart classes)."""
    e = P.ecls.to_numpy()
    flags = {}
    if unit == "swechat/gemini":
        flags["tool_failure"] = np.isin(e, ["tool_failure", "tool_failure+command_failure"])
        flags["command_failure"] = np.isin(e, ["command_failure", "tool_failure+command_failure"])
        flags["union"] = P.err.to_numpy()
        return flags
    for c in sorted(set(e.tolist()) - {"ok", "no_exit_code", "no_signal", "no_definition"}):
        flags[c] = e == c
    return flags


def session_table(unit, P, flags):
    S = P.groupby("session_id").agg(n_calls=("err", "size"), n_err=("err", "sum"),
                                    n_shell=("is_shell", "sum"), stratum=("stratum", "first"))
    for c, f in flags.items():
        S["c__" + c] = pd.Series(f.astype(int), index=P.index).groupby(P.session_id).sum()
    S["rate"] = S.n_err / S.n_calls
    return S


def zero_tail(S, L, p, col="n_err"):
    long_ = S[S.n_calls >= L]
    n_long = int(len(long_))
    k0 = int((long_[col] == 0).sum())
    out = {"L": int(L), "n_long": n_long, "n_zero": k0, "Z": wil(k0, n_long)}
    if n_long:
        e0_terms = np.power(1.0 - p, long_.n_calls.to_numpy(dtype=float))
        e0 = float(e0_terms.mean())
        out["E0"] = e0
        out["log10_E0"] = float(math.log10(e0)) if e0 > 0 else None
        out["Z_over_E0"] = (k0 / n_long) / e0 if e0 > 0 else None
        out["p_used_for_E0"] = p
    return out


def zero_error_profile(P, S, L):
    """Describes long sessions with zero primary errors against long sessions with >= 1 error (aggregates only)."""
    long_ids = S.index[S.n_calls >= L]
    zero_ids = set(S.index[(S.n_calls >= L) & (S.n_err == 0)])
    err_ids = set(long_ids) - zero_ids
    out = {}
    for name, ids in (("zero_error_long", zero_ids), ("error_long", err_ids)):
        sub = S.loc[sorted(ids)] if ids else S.iloc[0:0]
        pp = P[P.session_id.isin(ids)]
        mix = pp.iclass.value_counts()
        topk = pp.key.value_counts().head(8)
        out[name] = {
            "top_tool_keys_share_of_calls": {k: {"calls": int(v), "share": float(v / max(1, len(pp)))}
                                             for k, v in topk.items()},
            "sessions": int(len(sub)),
            "n_calls": stats.describe(sub.n_calls.to_numpy(dtype=float), qs=(0.0, 0.25, 0.5, 0.75, 0.9, 1.0)),
            "sessions_with_no_shell_call": int((sub.n_shell == 0).sum()) if len(sub) else 0,
            "shell_calls_per_session": stats.describe(sub.n_shell.to_numpy(dtype=float), qs=(0.0, 0.25, 0.5, 0.75, 1.0)),
            "calls_total": int(len(pp)),
            "tool_class_share_of_calls": {k: {"calls": int(v), "share": float(v / max(1, len(pp)))}
                                          for k, v in mix.items()},
        }
    return out


def zero_by_ncalls_bin(S, p, col="n_err"):
    """Zero-error session share by log2 bin of n_calls, with the independence expectation per bin."""
    out = []
    mx = int(S.n_calls.max()) if len(S) else 0
    lo = 1
    while lo <= mx:
        hi = lo * 2
        sub = S[(S.n_calls >= lo) & (S.n_calls < hi)]
        if len(sub):
            k0 = int((sub[col] == 0).sum())
            out.append({"n_calls_lo": lo, "n_calls_hi_excl": hi, "sessions": int(len(sub)), "zero_error": wil(k0, len(sub)),
                        "E0_bin": float(np.power(1.0 - p, sub.n_calls.to_numpy(dtype=float)).mean())})
        lo = hi
    return out


def per_tool(unit, P, S_index_count_min=10):
    out = {}
    for k, g in P.groupby("key"):
        bys = g.groupby("session_id").agg(n=("err", "size"), e=("err", "sum"))
        ent = {"calls": int(len(g)), "sessions": int(len(bys)), "errors": int(g.err.sum()),
               "error_rate": rate(bys.e.to_numpy(), bys.n.to_numpy()),
               "class_counts": {c: int(v) for c, v in g.ecls.value_counts().items()}}
        big = bys[bys.n >= S_index_count_min]
        if len(big):
            r = (big.e / big.n).to_numpy(dtype=float)
            ent["per_session_rate_sessions_ge_10_calls"] = {
                "sessions": int(len(big)), "n_exactly_zero": int((r == 0).sum()),
                "describe": stats.describe(r, qs=(0.0, 0.10, 0.25, 0.5, 0.75, 0.90, 1.0))}
        out[k] = ent
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["calls"]))


# ------------------------------------------------------------------------------------------------------------ retry
def tool_stratified_effect(R, sess):
    """POST HOC, not pre-registered, feeds no verdict. Effect within the c_i tool_key: sum_k w_k (R_fail_k - R_ok_k),
    w_k = failed c_i of tool k / failed c_i of tools with >= 1 non-failed c_i. Session bootstrap as statistic_ci."""
    Rs = R[R.st.isin(["fail", "ok"])]
    tools = sorted(set(Rs.key))
    if not len(Rs):
        return None
    sidx = {s: i for i, s in enumerate(sess)}
    tidx = {t: i for i, t in enumerate(tools)}
    FN = np.zeros((len(sess), len(tools)))
    FR, ON, OR = FN.copy(), FN.copy(), FN.copy()
    for s, st, k, rt in zip(Rs.session_id, Rs.st, Rs.key, Rs.retry):
        i, t = sidx[s], tidx[k]
        if st == "fail":
            FN[i, t] += 1
            FR[i, t] += rt
        else:
            ON[i, t] += 1
            OR[i, t] += rt

    def stat(fn, fr, on, or_):
        use = (fn > 0) & (on > 0)
        if not use.any():
            return None
        w = fn[use] / fn[use].sum()
        return float((w * (fr[use] / fn[use] - or_[use] / on[use])).sum())

    v = stat(FN.sum(0), FR.sum(0), ON.sum(0), OR.sum(0))
    rng = np.random.default_rng(stats.SEED)
    idx = rng.integers(0, len(sess), size=(stats.N_BOOT, len(sess)))
    vals = []
    for row in idx:
        x = stat(FN[row].sum(0), FR[row].sum(0), ON[row].sum(0), OR[row].sum(0))
        if x is not None:
            vals.append(x)
    use = (FN.sum(0) > 0) & (ON.sum(0) > 0)
    out = {"label": "POST HOC descriptive; not pre-registered; no verdict", "value": v, "valid_draws": len(vals),
           "tools_used": int(use.sum()), "failed_c_i_covered": int(FN.sum(0)[use].sum()), "failed_c_i_total": int(FN.sum())}
    if len(vals) >= 900:
        out.update({"lo": float(np.quantile(vals, 0.025)), "hi": float(np.quantile(vals, 0.975))})
    return out


def sim_text(tool, key, args, command, unit):
    a = None
    if isinstance(args, str):
        try:
            a = json.loads(args)
        except ValueError:
            a = None
    if tool == "shell":
        cmd = pc.shell_command(unit, key, a if isinstance(a, dict) else None, command)
        if isinstance(cmd, str):
            return cmd
    strs, nums = pc.args_strings(args)
    return " ".join(strs + nums)


def retry_analysis(unit, u_calls, P, flags):
    """Consecutive calls of one thread by seq; c_i must have a paired result with a defined error status."""
    upc = error_spec(unit)
    C = u_calls.sort_values(["session_id", "seq"]).drop_duplicates(["session_id", "call_id"])
    C = C.assign(_sub=C.is_subagent.astype("boolean").fillna(False).astype(bool),
                 _ag=C.agent_id.astype(object).where(C.agent_id.notna(), ""))
    raw_keys = [pc.tool_key(upc, t, tr) for t, tr in zip(C.tool.astype(object), C.tool_raw.astype(object))]
    C = C.assign(raw_key=raw_keys, key=[pc.private_key(k) for k in raw_keys] if unit == "cc_local" else raw_keys)
    C = C.sort_values(["session_id", "_sub", "_ag", "seq"]).reset_index(drop=True)
    # status of each paired call
    pinfo = {}
    tf = flags.get("tool_failure")
    cf = flags.get("command_failure")
    for i, (sid, cid, err, ecls, dfn) in enumerate(zip(P.session_id, P.call_id, P.err, P.ecls, P.defined)):
        if not dfn:
            continue
        if err:
            st = "fail"
        elif ecls in CC_APART:
            st = ecls
        else:
            st = "ok"
        pinfo[(sid, cid)] = (st, ecls, bool(tf[i]) if tf is not None else None, bool(cf[i]) if cf is not None else None)
    paired_keys = set(zip(P.session_id, P.call_id))
    sids, subs, ags = C.session_id.to_numpy(), C._sub.to_numpy(), C._ag.to_numpy()
    cids, keys, rkeys = C.call_id.to_numpy(), C.key.to_numpy(), C.raw_key.to_numpy()
    tools, argss, cmds = C.tool.astype(object).to_numpy(), C.args.astype(object).to_numpy(), C.command.astype(object).to_numpy()
    tok_cache, can_cache = {}, {}

    def toks(j):
        if j not in tok_cache:
            tok_cache[j] = pc.sim_tokens(sim_text(tools[j], rkeys[j], argss[j], cmds[j], upc))
        return tok_cache[j]

    def canon(j):
        if j not in can_cache:
            can_cache[j] = canon_args(argss[j])
        return can_cache[j]

    rows = []
    for j in range(len(C) - 1):
        if sids[j] != sids[j + 1] or subs[j] != subs[j + 1] or ags[j] != ags[j + 1]:
            continue
        info = pinfo.get((sids[j], cids[j]))
        if info is None:
            continue
        st, ecls, tfj, cfj = info
        same_raw = rkeys[j] == rkeys[j + 1]
        same = keys[j] == keys[j + 1]
        ident, jac = False, None
        if same:
            ident = canon(j) is not None and canon(j) == canon(j + 1)
            jac = pc.jaccard(toks(j), toks(j + 1))
        retry = bool(same and (ident or (jac is not None and jac >= 0.5)))
        retry_raw = bool(same_raw and (ident or (jac is not None and jac >= 0.5))) if same else False
        if same_raw and not same:  # cannot happen (private_key is a function of the raw key)
            retry_raw = True
        rows.append((sids[j], st, ecls, tfj, cfj, keys[j], same, ident, jac, retry, bool(ident and same), retry_raw,
                     (sids[j + 1], cids[j + 1]) in paired_keys))
    R = pd.DataFrame(rows, columns=["session_id", "st", "ecls", "tf", "cf", "key", "same_tool", "identical", "jaccard",
                                    "retry", "exact", "retry_rawkey", "next_paired"])
    out = {"successor_pairs": int(len(R)), "successor_pairs_next_unpaired": int((~R.next_paired).sum()) if len(R) else 0,
           "c_i_status_counts": {k: int(v) for k, v in R.st.value_counts().items()} if len(R) else {}}
    if not len(R):
        return out, R
    sess = sorted(set(P.session_id))
    G = R.groupby("session_id")

    def per_session(mask, col="retry"):
        m = pd.Series(mask, index=R.index)
        num = R[col].where(m, False).groupby(R.session_id).sum().reindex(sess, fill_value=0)
        den = m.groupby(R.session_id).sum().reindex(sess, fill_value=0)
        return num.to_numpy(dtype=float), den.to_numpy(dtype=float)

    fail = (R.st == "fail").to_numpy()
    ok = (R.st == "ok").to_numpy()
    fr_n, fr_d = per_session(fail)
    or_n, or_d = per_session(ok)
    fe_n, _ = per_session(fail, "exact")
    oe_n, _ = per_session(ok, "exact")
    out["R_fail"] = rate(fr_n, fr_d)
    out["R_ok"] = rate(or_n, or_d)
    out["R_fail_exact"] = rate(fe_n, fr_d)
    out["R_ok_exact"] = rate(oe_n, or_d)
    out["effect"] = boot_diff(fr_n, fr_d, or_n, or_d)
    out["effect_exact"] = boot_diff(fe_n, fr_d, oe_n, or_d)
    out["n_fail_with_successor"] = int(fr_d.sum())
    out["sessions_fail_with_successor"] = int((fr_d > 0).sum())
    out["n_ok_with_successor"] = int(or_d.sum())
    # rows reported apart
    apart = {}
    for st in CC_APART:
        m = (R.st == st).to_numpy()
        if m.any():
            n_, d_ = per_session(m)
            apart[st] = {"R": rate(n_, d_), "n": int(d_.sum()), "sessions": int((d_ > 0).sum())}
    if (R.ecls == "village_bash_proxy").any():
        m = (R.ecls == "village_bash_proxy").to_numpy()
        n_, d_ = per_session(m)
        apart["village_bash_proxy (inside R_ok)"] = {"R": rate(n_, d_), "n": int(d_.sum()), "sessions": int((d_ > 0).sum())}
        m2 = ok & ~m
        n2, d2 = per_session(m2)
        apart["R_ok_excluding_village_bash_proxy"] = {"R": rate(n2, d2), "effect": boot_diff(fr_n, fr_d, n2, d2)}
    if (R.ecls == "no_exit_code").any():
        m = (R.ecls == "no_exit_code").to_numpy()
        n_, d_ = per_session(m)
        apart["no_exit_code (inside R_ok)"] = {"R": rate(n_, d_), "n": int(d_.sum()), "sessions": int((d_ > 0).sum())}
    if unit == "swechat/gemini":
        for cname, col in (("tool_failure", "tf"), ("command_failure", "cf")):
            m = (R[col] == True).to_numpy()  # noqa: E712
            n_, d_ = per_session(m)
            apart[f"R_fail_{cname}"] = {"R": rate(n_, d_), "n": int(d_.sum()), "sessions": int((d_ > 0).sum()),
                                        "effect_vs_R_ok": boot_diff(n_, d_, or_n, or_d)}
    out["rows_apart"] = apart
    # share of calls that are a retry of an immediately preceding failed call
    rf = (R.retry & (R.st == "fail")).groupby(R.session_id).sum().reindex(sess, fill_value=0).to_numpy(dtype=float)
    allsucc = G.size().reindex(sess, fill_value=0).to_numpy(dtype=float)
    ncalls = P.groupby("session_id").size().reindex(sess, fill_value=0).to_numpy(dtype=float)
    out["retry_after_fail_share_of_successor_pairs"] = rate(rf, allsucc)
    out["retry_after_fail_share_of_paired_calls"] = rate(rf, ncalls)
    out["retry_any_share_of_successor_pairs"] = rate(
        R.retry.groupby(R.session_id).sum().reindex(sess, fill_value=0).to_numpy(dtype=float), allsucc)
    # same-tool successors: Jaccard distribution by previous status
    jd = {}
    for st in ("fail", "ok"):
        sub = R[(R.st == st) & R.same_tool]
        jj = sub.jaccard.to_numpy(dtype=float)
        h, _ = np.histogram(jj, bins=np.linspace(0, 1, 11))
        jd[st] = {"same_tool_successors": int(len(sub)), "identical_args": int(sub.identical.sum()),
                  "jaccard_hist_10bins_0_to_1": [int(x) for x in h],
                  "jaccard_ge_0.5": int((jj >= 0.5).sum()),
                  "share_same_tool_of_successors": float(len(sub) / max(1, int((R.st == st).sum())))}
    out["same_tool_successor_jaccard"] = jd
    # per c_i tool_key
    pt = {}
    for k, g in R.groupby("key"):
        nf, no = int((g.st == "fail").sum()), int((g.st == "ok").sum())
        pt[k] = {"fail_n": nf, "fail_retry": int(((g.st == "fail") & g.retry).sum()),
                 "ok_n": no, "ok_retry": int(((g.st == "ok") & g.retry).sum())}
    out["per_tool_key_counts"] = dict(sorted(pt.items(), key=lambda kv: -(kv[1]["fail_n"] + kv[1]["ok_n"])))
    out["post_hoc_tool_stratified_effect"] = tool_stratified_effect(R, sess)
    if unit == "cc_local":
        out["sensitivity_raw_tool_key_comparison"] = {
            "retries_private_key": int(R.retry.sum()), "retries_raw_key": int(R.retry_rawkey.sum()),
            "note": "prereg tool_key rule for cc_local passes keys through private_key() before grouping; the verdict "
                    "uses private keys; this count compares raw keys instead (aggregate only)"}
    return out, R


# ------------------------------------------------------------------------------------------------------------ early/late
def early_late(P, flags, unit, min_calls):
    if unit == "swechat/gemini":
        P = P.assign(_tf=flags["tool_failure"], _cf=flags["command_failure"])
    P = P.sort_values(["session_id", "seq"])
    cols = {"primary": P.err.to_numpy()}
    if unit == "swechat/gemini":
        cols = {"union": P.err.to_numpy(), "tool_failure": P._tf.to_numpy(), "command_failure": P._cf.to_numpy()}
    pos = P.groupby("session_id").cumcount().to_numpy()
    n = P.groupby("session_id").session_id.transform("size").to_numpy()
    elig = n >= min_calls
    half = n // 2
    early = pos < half
    sids = P.session_id.to_numpy()
    out = {"eligible_sessions": int(len(set(sids[elig].tolist()))), "min_calls": int(min_calls)}
    if not elig.any():
        return out
    df = pd.DataFrame({"sid": sids[elig], "early": early[elig], "pos": pos[elig], "n": n[elig]})
    for name, e in cols.items():
        d = df.assign(e=np.asarray(e)[elig].astype(int))
        agg = d.groupby(["sid", "early"]).agg(e=("e", "sum"), c=("e", "size")).unstack("early", fill_value=0)
        e_early, c_early = agg[("e", True)].to_numpy(float), agg[("c", True)].to_numpy(float)
        e_late, c_late = agg[("e", False)].to_numpy(float), agg[("c", False)].to_numpy(float)
        ns = len(e_early)
        blk = {"early_rate": rate(e_early, c_early), "late_rate": rate(e_late, c_late),
               "late_minus_early": boot_diff(e_late, c_late, e_early, c_early)}
        diff = blk["late_minus_early"]
        if diff.get("ci_reported"):
            blk["label"] = "stable" if diff["lo"] <= 0 <= diff["hi"] else ("rises" if diff["lo"] > 0 else "falls")
        else:
            blk["label"] = "insufficient draws"
        blk["sessions_errors_early_none_late"] = wil(int(((e_early > 0) & (e_late == 0)).sum()), ns)
        blk["sessions_errors_late_none_early"] = wil(int(((e_late > 0) & (e_early == 0)).sum()), ns)
        blk["sessions_errors_both_halves"] = wil(int(((e_late > 0) & (e_early > 0)).sum()), ns)
        blk["sessions_no_errors"] = wil(int(((e_late == 0) & (e_early == 0)).sum()), ns)
        per_s = e_late / c_late - e_early / c_early
        blk["per_session_late_minus_early"] = stats.describe(per_s, qs=(0.0, 0.10, 0.25, 0.5, 0.75, 0.90, 1.0))
        # error rate by within-session position decile (pooled over eligible sessions; cluster CI)
        dec = np.minimum((d.pos.to_numpy() * 10) // d.n.to_numpy(), 9)
        d2 = d.assign(dec=dec)
        decs = []
        sess = sorted(set(d2.sid))
        for k in range(10):
            sub = d2[d2.dec == k]
            num = sub.groupby("sid").e.sum().reindex(sess, fill_value=0).to_numpy(float)
            den = sub.groupby("sid").e.size().reindex(sess, fill_value=0).to_numpy(float)
            r = rate(num, den)
            decs.append({"decile": k, **{kk: r.get(kk) for kk in ("rate", "lo", "hi", "num", "den", "n_sessions",
                                                                    "reportable")}})
        blk["by_position_decile"] = decs
        out[name] = blk
    return out


# ------------------------------------------------------------------------------------------------------------ verdicts
def verdict_zero(z, n_long, cap_weak=False):
    mn = 20
    if n_long < mn:
        v, why = "INSUFFICIENT_N", f"n_long {n_long} < {mn}"
    else:
        Z, hi = z["share"], z["hi"]
        if Z <= 0.10 and hi <= 0.20 and n_long >= 30:
            v, why = "ALIVE", f"Z {Z:.4f} <= 0.10, Wilson hi {hi:.4f} <= 0.20, n_long {n_long} >= 30"
        elif Z <= 0.30:
            v, why = "WEAK", f"Z {Z:.4f} <= 0.30 (ALIVE needs Z <= 0.10, Wilson hi <= 0.20, n_long >= 30; hi {hi:.4f}, n_long {n_long})"
        else:
            v, why = "DEAD", f"Z {Z:.4f} > 0.30"
    capped = False
    if cap_weak and v == "ALIVE":
        v, capped = "WEAK", True
    return v, why, capped


def verdict_reaction(ret, cap_weak=False):
    nf, sf, no = ret.get("n_fail_with_successor", 0), ret.get("sessions_fail_with_successor", 0), ret.get("n_ok_with_successor", 0)
    if nf < 30 or sf < 10 or no < 30:
        return "INSUFFICIENT_N", f"failed c_i with successor {nf} from {sf} sessions, non-failed {no} (need >= 30 from >= 10, and >= 30)", False
    eff = ret["effect"]
    if not eff.get("ci_reported"):
        return "INSUFFICIENT_N", f"effect CI not reported (valid draws {eff.get('valid_draws')} < 900)", False
    lo = eff["lo"]
    if lo >= 0.10:
        v, why = "ALIVE", f"effect {eff['value']:.4f}, CI lo {lo:.4f} >= 0.10"
    elif lo > 0:
        v, why = "WEAK", f"effect {eff['value']:.4f}, CI lo {lo:.4f} in (0, 0.10)"
    else:
        v, why = "DEAD", f"effect {eff['value']:.4f}, CI lo {lo:.4f} <= 0"
    capped = False
    if cap_weak and v == "ALIVE":
        v, capped = "WEAK", True
    return v, why, capped


# ============================================================================================================ main unit
def analyse_unit(unit, u):
    t0 = time.time()
    L = PRE["resolved"]["probe3"]["long_session"]["whowhen" if unit.startswith("whowhen") else unit]
    calls = u[u.kind == "call"]
    P = pc.make_pairs(u[u.kind.isin(["call", "result"])])
    res_rows = u[u.kind == "result"]
    if unit == "whowhen/Algorithm-Generated":
        P = P[(P.stratum == "Algorithm-Generated") & (P.tool == "code_exec")]
    P = classify_pairs(unit, P)
    flags = class_flags(unit, P)
    out = {"B_sessions_with_call_or_result_rows": int(u.session_id.nunique()),
           "calls": int(len(calls)), "results": int(len(res_rows)),
           "paired_calls": int(len(P)), "sessions_with_paired_calls": int(P.session_id.nunique()),
           "error_status_defined_pairs": int(P.defined.sum()),
           "L75": int(L["L75"]), "L90": int(L["L90"]), "L_source": "prereg.json resolved.probe3.long_session"}
    if unit == "whowhen/Algorithm-Generated":
        out["paired_calls_filter"] = "stratum Algorithm-Generated AND IR tool == 'code_exec' (as in the calibration)"
    S = session_table(unit, P, flags)
    p = float(S.n_err.sum() / S.n_calls.sum()) if len(S) else None
    # ---- error rates
    er = {"primary": rate(S.n_err.to_numpy(), S.n_calls.to_numpy()),
          "primary_label": "union of two classes (session indicator; never a pooled rate per prereg)" if unit == "swechat/gemini" else "primary",
          "class_counts": {c: int(v) for c, v in P.ecls.value_counts().items()},
          "per_class": {c: dict(rate(S["c__" + c].to_numpy(), S.n_calls.to_numpy()), sessions_with_class=int((S["c__" + c] > 0).sum()))
                        for c in flags}}
    out["error_rate_per_call"] = er
    out["sessions_with_any_primary_error"] = wil(int((S.n_err > 0).sum()), len(S))
    out["per_tool_key"] = per_tool(unit, P)
    # ---- distributions
    out["calls_per_session"] = count_hist(S.n_calls.to_numpy())
    out["per_session_error_rate"] = {
        "all_sessions": dist_block(S.rate.to_numpy(), S.index.to_numpy()),
        "sessions_ge_20_calls": dist_block(S.rate[S.n_calls >= 20].to_numpy(), S.index[S.n_calls >= 20].to_numpy()),
        "long_sessions_L75": dist_block(S.rate[S.n_calls >= L["L75"]].to_numpy(), S.index[S.n_calls >= L["L75"]].to_numpy()),
    }
    if unit == "swechat/gemini":
        for c in ("tool_failure", "command_failure"):
            out["per_session_error_rate"][f"all_sessions_{c}"] = dist_block((S["c__" + c] / S.n_calls).to_numpy())
    out["errors_per_session"] = {"all_sessions": count_hist(S.n_err.to_numpy()),
                                 "long_sessions_L75": count_hist(S.n_err[S.n_calls >= L["L75"]].to_numpy())}
    # ---- zero-error tail
    zt = {"pooled_per_call_rate_p": p, "L75": zero_tail(S, L["L75"], p), "L90": zero_tail(S, L["L90"], p)}
    zt["per_class_L75"] = {}
    for c in flags:
        pc_ = float(S["c__" + c].sum() / S.n_calls.sum())
        zt["per_class_L75"][c] = zero_tail(S, L["L75"], pc_, col="c__" + c)
    if unit in pc.CC_FORMAT_UNITS:
        S2 = S.assign(any_native=sum(S["c__" + c] for c in flags if c != "village_bash_proxy"))
        p2 = float(S2.any_native.sum() / S2.n_calls.sum())
        zt["any_native_flag_incl_permission_interrupt_L75"] = zero_tail(S2, L["L75"], p2, col="any_native")
    long_shell = S[(S.n_calls >= L["L75"]) & (S.n_shell > 0)]
    zt["descriptive_long_sessions_with_ge1_shell_call"] = {"n_long": int(len(long_shell)),
                                                           "Z": wil(int((long_shell.n_err == 0).sum()), len(long_shell))}
    zt["zero_error_share_by_ncalls_log2_bin"] = zero_by_ncalls_bin(S, p)
    zt["zero_error_long_profile"] = zero_error_profile(P, S, L["L75"])
    if unit == "aiv_cu":
        ps = {}
        for st, g in S.groupby("stratum"):
            pg = P[P.session_id.isin(g.index)]
            ps[st] = {"sessions": int(len(g)), "paired_calls": int(g.n_calls.sum()), "errors": int(g.n_err.sum()),
                      "error_rate": rate(g.n_err.to_numpy(), g.n_calls.to_numpy()),
                      "L75_pooled_unit_threshold": zero_tail(g, L["L75"], p),
                      "calls_per_session": stats.describe(g.n_calls.to_numpy(dtype=float), qs=(0.0, 0.25, 0.5, 0.75, 1.0)),
                      "shell_calls": int(pg.is_shell.sum())}
        zt["aiv_cu_per_stratum"] = ps
    out["zero_error_tail"] = zt
    # ---- retry
    if unit == "whowhen/Algorithm-Generated":
        calls = calls[calls.stratum == "Algorithm-Generated"]
    ret, _ = retry_analysis(unit, calls, P, flags)
    out["retry"] = ret
    # ---- early/late
    out["early_late"] = early_late(P, flags, unit, 20)
    # ---- verdicts
    cap = unit == "aiv_cu"
    zrow = zt["L75"]
    vz, why_z, cz = verdict_zero(zrow["Z"], zrow["n_long"], cap)
    vr, why_r, cr = verdict_reaction(ret, cap)
    labels = []
    if unit == "aiv_cc":
        labels.append("single-agent case study")
    if unit == "aiv_cu":
        labels.append("proxy-based error definition (unvalidated); capped at WEAK")
    if unit == "swechat/gemini":
        labels.append("union of two unvalidated-together classes")
    if out["sessions_with_paired_calls"] < 30:
        labels.append("small n")
    out["verdict"] = {
        "zero_error_tail": {"verdict": vz, "deciding_number": {"Z": zrow["Z"], "n_long": zrow["n_long"]}, "rule_applied": why_z,
                            "capped_from_ALIVE": cz},
        "reaction": {"verdict": vr, "deciding_number": {"effect": ret.get("effect"), "n_fail_with_successor": ret.get("n_fail_with_successor"),
                                                        "sessions_fail_with_successor": ret.get("sessions_fail_with_successor"),
                                                        "n_ok_with_successor": ret.get("n_ok_with_successor")},
                     "rule_applied": why_r, "capped_from_ALIVE": cr},
        "labels": labels,
    }
    out["seconds"] = round(time.time() - t0, 1)
    return out


# ============================================================================================================ main
def main():
    global PRE
    t0 = time.time()
    PRE = json.load(open(PREREG_PATH, encoding="utf-8"))
    want = PRE["provenance"]["spec_module_sha256"]
    have = sha256(SPEC_PATH)
    if want != have:
        raise SystemExit(f"prereg_common.py sha256 {have} != prereg.json provenance.spec_module_sha256 {want}; stop")
    result = {
        "probe": "probe_3 pushback (environment friction / surprise rate)",
        "script": "analysis/probes/probe_3.py",
        "run_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "split": "B",
        "prereg_json_sha256": sha256(PREREG_PATH),
        "spec_module_sha256": {"expected_from_prereg_json": want, "on_disk": have, "match": want == have},
        "inputs_sha256": {},
        "thresholds_used": {"long_session": PRE["resolved"]["probe3"]["long_session"], "verdict": PRE["probe3"]["verdict"],
                            "min_n": PRE["probe3"]["min_n"], "early_late": PRE["probe3"]["early_late"],
                            "retry": PRE["probe3"]["retry"],
                            "feasibility_projection_probe3_copied_from_prereg": {
                                u: {k: v for k, v in c.items() if k.startswith("p3_")}
                                for u, c in PRE["resolved"]["feasibility_projection"]["cells"].items()
                                if any(k.startswith("p3_") for k in c)}},
        "bootstrap": {"n_boot": stats.N_BOOT, "seed": stats.SEED},
        "units": {},
        "not_run": {},
    }
    testable = PRE["probe3"]["units"]["testable"]
    for corpus in ("swechat", "cc_local", "aiv_cc", "aiv_cu", "whowhen"):
        f = pc.CACHE / f"{corpus}_B.parquet"
        result["inputs_sha256"][f"analysis/cache/{corpus}_B.parquet"] = sha256(f)
        df = load_corpus(corpus)
        print(f"[{time.time() - t0:6.1f}s] loaded {corpus}: {len(df)} call/result rows", flush=True)
        alls = pc.load_split(corpus, "B", ["session_id", "stratum"]).drop_duplicates("session_id")
        if corpus == "whowhen":
            frames = {"whowhen/Algorithm-Generated": df[df.stratum == "Algorithm-Generated"],
                      "whowhen/Hand-Crafted": df[df.stratum == "Hand-Crafted"]}
            n_all = {f"whowhen/{k}": int(v) for k, v in alls.stratum.value_counts().items()}
        else:
            frames = pc.unit_frames(corpus, df)
            n_all = {k: len(g) for k, g in pc.unit_frames(corpus, alls).items()}
        for unit, u in frames.items():
            u = u.reset_index(drop=True)
            if unit in testable:
                print(f"[{time.time() - t0:6.1f}s] {unit}: {len(u)} rows", flush=True)
                r = analyse_unit(unit, u)
                r = {"B_sessions_in_cache_all_rows": n_all.get(unit, 0),
                     "B_sessions_population_prereg": PRE["population_B"]["sessions"].get(unit), **r}
                result["units"][unit] = r
            else:
                P = pc.make_pairs(u)
                result["not_run"][unit] = {"B_sessions_in_cache_all_rows": n_all.get(unit, 0),
                                           "B_sessions_with_call_or_result_rows": int(u.session_id.nunique()),
                                           "calls": int((u.kind == "call").sum()), "results": int((u.kind == "result").sum()),
                                           "paired_calls": int(len(P))}
        del df
    # population-only units without rows in B
    for unit, why in {**PRE["probe3"]["units"]["dead"], **PRE["probe3"]["units"]["not_testable"]}.items():
        ent = result["not_run"].setdefault(unit, {"B_sessions_in_cache_all_rows": 0, "calls": 0, "results": 0,
                                                  "paired_calls": 0})
        ent["prereg_status"] = "DEAD" if unit in PRE["probe3"]["units"]["dead"] else "NOT_TESTABLE"
        ent["prereg_reason"] = why
    # aiv_cc split overlap (global.aiv_cc_rule)
    a_ids = set(pc.load_split("aiv_cc", "A", ["session_id"]).session_id.unique().tolist())
    b_ids = set(pc.load_split("aiv_cc", "B", ["session_id"]).session_id.unique().tolist())
    a_sdk = {s.split("/")[0] for s in a_ids}
    b_sdk = {s.split("/")[0] for s in b_ids}
    result["aiv_cc_split_overlap"] = {"B_runs": len(b_ids), "B_distinct_sdk_session_id": len(b_sdk),
                                      "A_distinct_sdk_session_id": len(a_sdk),
                                      "B_runs_sharing_sdk_session_id_with_an_A_run": sum(1 for s in b_ids if s.split("/")[0] in a_sdk)}
    # verdict table
    vt = {}
    n_cells = 0
    for unit, r in result["units"].items():
        vt[unit] = {"zero_error_tail": r["verdict"]["zero_error_tail"]["verdict"],
                    "reaction": r["verdict"]["reaction"]["verdict"], "labels": r["verdict"]["labels"]}
        n_cells += 2
    for unit, r in result["not_run"].items():
        if "prereg_status" in r:
            vt[unit] = {"zero_error_tail": r["prereg_status"], "reaction": r["prereg_status"], "labels": [r["prereg_reason"]]}
    result["verdicts"] = vt
    result["verdict_cells_computed"] = n_cells
    result["deviations"] = DEVIATIONS
    result["seconds"] = round(time.time() - t0, 1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1, ensure_ascii=False, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print(f"[{time.time() - t0:6.1f}s] wrote {OUT}")
    for unit, v in vt.items():
        print(f"  {unit:32s} zero_error_tail={v['zero_error_tail']:15s} reaction={v['reaction']}")


DEVIATIONS = [
    {"item": "output path",
     "prereg_said": "data_rules.output_contract: write to analysis/out/phase_b/<probe>.json",
     "what_you_did": "wrote analysis/out/probe_3.json",
     "why": "the Phase B task specification for this probe names analysis/out/probe_3.json; the content contract "
            "(raw counts, prereg.json sha256 copied in, verdicts under `verdicts`) is kept",
     "effect_on_verdict": "none"},
    {"item": "Gemini per-call error rate vs E0",
     "prereg_said": "error_definitions.swechat/gemini: two classes never pooled into one rate, union used only as a session "
                    "indicator; probe3.zero_error_tail: E0 uses p = the unit's pooled B per-call primary error rate",
     "what_you_did": "per-call rates reported per class; the union per-call rate is reported once, labelled, and used only "
                     "as p in E0 (and in the early/late union row, labelled)",
     "why": "E0 needs a per-call p for the indicator that decides the verdict (union); no other way to apply both clauses",
     "effect_on_verdict": "none (E0 is reported, not part of the verdict rule)"},
    {"item": "swechat/simple_text status",
     "prereg_said": "probe3.units.dead lists swechat/simple_text ('no calls'); PREREG.md section 0 says 0 B sessions -> "
                    "NOT_TESTABLE in every probe",
     "what_you_did": "recorded DEAD as listed in prereg.json probe3.units.dead (JSON wins), with 0 B sessions noted",
     "why": "prereg.json is authoritative where the two differ",
     "effect_on_verdict": "label only; no number computed"},
    {"item": "retry successor set",
     "prereg_said": "consecutive calls (c_i, c_{i+1}) of the same thread by seq, where c_i has a paired result",
     "what_you_did": "c_{i+1} ranges over all calls of the thread (deduplicated on (session_id, call_id), first by seq), "
                     "paired or not; the A-split feasibility count in prereg_calibration.py used paired calls only. The "
                     "number of pairs whose successor is unpaired is reported (retry.successor_pairs_next_unpaired)",
     "why": "literal reading of the SPEC text; the calibration count was a feasibility count, not a definition",
     "effect_on_verdict": "none expected (unpaired calls are a fraction of a percent; the count is reported)"},
]

PRE = None

if __name__ == "__main__":
    main()
