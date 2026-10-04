"""Phase E, Track A, item A1 (second pass) for the Probe 1 and Probe 3 candidates.  Item key: a1_p1_p3.

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_a1_p1_p3

Pre-registration (the law): analysis/PREREG_E.md section 1, analysis/prereg_e.json (a1.candidates, artifact_checks,
stratification, survival_rule) and analysis/probes/prereg_e_common.py, committed in 55fc556. check_frozen() runs before
anything else. Every threshold comes from prereg_e.json / prereg.json; nothing is tuned here.

Candidates (prereg_e.json a1.candidates):
  P1/swechat/opencode       Phase B ALIVE        has E   K1-K3, AC4 mandatory
  P1/cc_local               Phase B ALIVE        no E    K1-K3 (B only, unreplicated; PRIVATE: aggregates only)
  P1/swechat/claude_code    Phase B WEAK (floor UNSTABLE)  has E   K1-K3 (+ F2 is a separate item)
  P3zero/swechat/claude_code Phase B ALIVE       has E   K1-K4
For each: the Phase B statistic re-measured on B (reproduction of the committed Phase B numbers), on E (replication
verdict) and on B u E (re-measurement population), artifact checks AC1-AC5 and the four stratification axes on B u E,
the candidate kill tests, and survival_status() applied mechanically.

Code paths reused unchanged (the re-measurement is the same statistic):
  Probe 1: prereg_calibration.p1_qualified (no-human-wait filter) and g_latency, probe_1.nested_bad_set, rate_from_mask,
           auc_ci, a1_recheck, unit_verdict; prereg_common.make_pairs and change_point.
  Probe 3: probe_3.classify_pairs, class_flags, session_table, zero_tail, verdict_zero, wil.
Phase E helpers: prereg_e_common read_cache / split_ids (B and E only; H is never read), truncated_result,
join_clean_mask, audit_sample, dominance, session_cluster_map, session_model_map, length_tercile_map,
post_strat_weights, weighted_cluster_rate, confinement, downgrade, survival_status, rng_for.

Reads: analysis/cache/swechat_{B,E}.parquet, cc_local_B.parquet, swechat_population.parquet (format, AC5 cells),
swe-chat-pinned sessions.parquet (repo_id/user_id for B u E ids only), raw transcripts for the AC1 audit sample only
(swechat public transcripts; cc_local frozen snapshot data/claude-code-local, root file-set of the audited session,
in-process, match counts only). Never reads *_A.parquet, *_EH.json key H, or anything of the local Qwen swarm.
Writes RAW NUMBERS ONLY to analysis/out/phase_e/a1_p1_p3.json. Interpretation: analysis/notes/phase_e_a1_p1_p3.md.
"""
from analysis.probes import prereg_e_common as E

PJ = E.check_frozen()  # first: the module must be the pre-registered one (stops with AssertionError otherwise)

import glob  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from analysis.lib import stats  # noqa: E402
from analysis.lib.ir import error_marker  # noqa: E402
from analysis.probes import prereg_common as pc  # noqa: E402
from analysis.probes import prereg_calibration as cal  # noqa: E402
from analysis.probes import probe_1 as p1  # noqa: E402
from analysis.probes import probe_3 as p3  # noqa: E402
from analysis.probes.phase_a_a1 import frac_of  # noqa: E402

ROOT = E.ROOT
OUT = E.OUT_E / "a1_p1_p3.json"
PR = p1.PR                       # analysis/prereg.json (Phase B)
TH = p1.TH                       # Phase B Probe 1 thresholds (asserted against prereg.json text by p1)
LEVEL = E.LEVEL
CC_LOCAL_ROOT = os.path.join(os.environ.get("SWARMS_DATA", "C:/Swarms/data"), "claude-code-local")

UNITS_P1 = ["swechat/opencode", "cc_local", "swechat/claude_code"]
PHASE_B = {  # prereg_e.json a1.candidates.<c>.phase_b (base label for survival_status)
    "P1/swechat/opencode": "ALIVE", "P1/cc_local": "ALIVE", "P1/swechat/claude_code": "WEAK",
    "P3zero/swechat/claude_code": "ALIVE"}
K1_G_TOOLS = {"subagent", "webfetch", "websearch"}  # a1.candidates.P1/*.kills.K1_control_composition
L3 = PR["resolved"]["probe3"]["long_session"]["swechat/claude_code"]
L75, L90 = int(L3["L75"]), int(L3["L90"])
P3_K = {"K1_min_shell": 10, "K1_down": 0.10, "K1_kill": 0.30, "K2_down": 0.10, "K3_min_long": 20,
        "K3_share": 0.20, "K3_Z": 0.30, "min_long": 20}  # PREREG_E.md 1.3 / prereg_e.json a1.candidates.P3zero
LCOLS = ["session_id", "seq", "kind", "ts", "tool", "tool_raw", "call_id", "text", "extra", "api_msg_id",
         "is_subagent", "agent_id", "parent_call_id", "stratum", "model", "native_error", "exit_code", "stderr"]
KINDS = ["call", "result", "meta", "system", "user"]
FM = pc.swechat_formats()


# ================================================================================================ small helpers
def clean(o):
    return p1.clean(o)


def whole_second(s):
    """A1 definition (phase_a_a1.frac_of): no fractional part, or only zeros."""
    if not isinstance(s, str):
        return False
    f = frac_of(s)
    return f is not None and (f == "" or set(f) <= {"0"})


def lvl(label):
    return LEVEL.get(label)


def lower(a, b):
    if a not in LEVEL:
        return b
    if b not in LEVEL:
        return a
    return a if LEVEL[a] <= LEVEL[b] else b


def norm_clusters(m):
    """Missing metadata (sessions.parquet null repo_id / user_id comes back as float NaN) -> one explicit 'unknown'
    cluster, so that the leave-out and the strata can select it (NaN != NaN)."""
    return {s: (v if isinstance(v, str) and v not in ("", "nan", "None") else "unknown") for s, v in m.items()}


def anon_rank(keys_in_order, prefix):
    """Rank labels for repo / user / session ids; the 'unknown' pseudo-cluster keeps its name."""
    return {k: (k if k == "unknown" else f"{prefix}#{i + 1}") for i, k in enumerate(keys_in_order)}


# ================================================================================================ loading
def unit_ids(unit, split):
    fmt = unit.split("/")[1]
    return [s for s in E.split_ids("swechat", split) if FM.get(s) == fmt]


def load(unit, split):
    if unit == "cc_local":
        df = E.read_cache("cc_local", split, LCOLS, filters=[("kind", "in", KINDS)])
    else:
        df = E.read_cache("swechat", split, LCOLS, filters=[("session_id", "in", unit_ids(unit, split)),
                                                             ("kind", "in", KINDS)])
    df = df.reset_index(drop=True)
    df.loc[df.kind != "result", "text"] = None  # Probe 1 uses result text only (as probe_1.main)
    return df


# ================================================================================================ extraction
def extract(unit, u, split):
    """Per-split compact tables, built with the Phase B code path (probe_1.probe1_unit sections 2 and 6)."""
    P = pc.make_pairs(u[u.kind.isin(["call", "result"])])
    a1 = P[["session_id", "ts", "ts_r", "delta_s"]].copy()
    cid = u[(u.kind == "call") & u.call_id.notna()][["session_id", "call_id"]].drop_duplicates()
    cid = cid[~cid.call_id.astype(str).str.startswith("synthetic:")]
    calls = u[u.kind == "call"].sort_values(["session_id", "seq"])
    ordmap = dict(zip(zip(calls.session_id, calls.call_id.astype(str)), calls.groupby("session_id").cumcount()))
    P = cal.p1_qualified(unit, u, P)
    txt = P.text_r.astype(object)
    P["chars_r"] = [len(t) if isinstance(t, str) else 0 for t in txt]
    P["bytes_r"] = [len(t.encode("utf-8")) if isinstance(t, str) else 0 for t in txt]
    P["trunc"] = [E.truncated_result(t, x) for t, x in zip(txt, P.extra_r.astype(object))]
    P["ws"] = [whole_second(a) or whole_second(b) for a, b in zip(P.ts.astype(object), P.ts_r.astype(object))]
    P["jc0"] = E.join_clean_mask(u, P)
    P["call_id"] = P.call_id.astype(str)
    P["ord"] = [ordmap.get((s, c), -1) for s, c in zip(P.session_id, P.call_id)]
    npairs = P.groupby("session_id").size()
    G90 = PR["resolved"]["probe1"]["generation_rate"][unit]["G90"]
    tpc = TH["tokens_per_char"]
    Qall = P[P.qualified]
    Q = Qall[Qall.delta_s > 0]
    keep = ["session_id", "call_id", "key", "cls", "seq", "ts", "ts_r", "delta_s", "chars_r", "bytes_r", "trunc", "ws",
            "jc0", "ord"]
    Qt = Q[keep].copy()
    Wset = Q[Q.key.isin(cal.W_KEYS[unit])] if unit in cal.W_KEYS else Q[Q.cls == "auto_read"]
    W = Wset[keep].copy()
    W["T"] = W.chars_r.to_numpy(dtype=float) * tpc / G90
    W["elig"] = W["T"] >= TH["T_gen_min_s"]
    W["r"] = W.delta_s.to_numpy(dtype=float) / W["T"].replace(0, np.nan).to_numpy(dtype=float)
    # G: probe_1.probe1_unit section 6, verbatim logic
    nested_bad = p1.nested_bad_set(unit, u)
    rows, gexcl = [], Counter()
    for k, d, x, s, c, mk, ch, by, tr, wsf, jc, q, a, b, o in zip(
            P.key, P.delta_s, P._rx, P.session_id, P.call_id, P.marker, P.chars_r, P.bytes_r, P.trunc, P.ws, P.jc0,
            P.seq, P.ts.astype(object), P.ts_r.astype(object), P.ord):
        if k not in cal.G_TOOLS.get(unit, set()):
            continue
        if mk in ("cc_permission_denied", "cc_interrupt_reject"):
            gexcl["reject_marker"] += 1
            continue
        if (s, c) in nested_bad:
            gexcl["nested_human_marker_or_interactive"] += 1
            continue
        lat = cal.g_latency(unit, k, d, x)
        if lat is None:
            gexcl["no_tool_reported_duration"] += 1
            continue
        if not np.isfinite(lat) or lat <= 0:
            gexcl["nonpositive_or_missing_latency"] += 1
            continue
        rows.append((s, c, k, q, a, b, d, lat, ch, by, tr, wsf, jc, o))
    G = pd.DataFrame(rows, columns=["session_id", "call_id", "key", "seq", "ts", "ts_r", "delta_s", "lat", "chars_r",
                                    "bytes_r", "trunc", "ws", "jc0", "ord"])
    G["T"] = G.chars_r.to_numpy(dtype=float) * tpc / G90
    G["elig"] = G["T"] >= TH["T_gen_min_s"]
    G["r"] = G.lat.to_numpy(dtype=float) / G["T"].replace(0, np.nan).to_numpy(dtype=float)
    out = {"W": W.assign(split=split), "G": G.assign(split=split), "Q": Qt.assign(split=split),
           "a1": a1.assign(split=split), "npairs": npairs, "cid": cid.assign(split=split),
           "model": E.session_model_map(u), "gexcl": dict(gexcl),
           "stratum": u.groupby("session_id").stratum.first().astype(str).to_dict(),
           "counts": {"pairs": int(len(P)), "qualified": int(len(Qall)), "qualified_positive": int(len(Q)),
                      "sessions_with_pairs": int(P.session_id.nunique()), "sessions_in_frame": int(u.session_id.nunique()),
                      "W_all": int(len(W)), "G_usable": int(len(G))}}
    if unit == "swechat/claude_code":
        P3 = p3.classify_pairs(unit, P[["session_id", "seq", "call_id", "tool", "tool_raw", "text_r", "stderr_r",
                                        "native_error_r", "exit_code_r", "stratum", "trunc", "jc0"]].copy())
        flags = p3.class_flags(unit, P3)
        S_ref = p3.session_table(unit, P3, flags)  # Phase B session table (reproduction check)
        out["P3"] = P3[["session_id", "call_id", "err", "ecls", "is_shell", "key", "trunc", "jc0"]].assign(split=split)
        out["P3_session_table_ref"] = S_ref[["n_calls", "n_err", "n_shell"]].copy()
    return out


def pool(parts):
    T = {}
    for k in ("W", "G", "Q", "a1", "cid"):
        T[k] = pd.concat([p[k] for p in parts], ignore_index=True)
    T["npairs"] = pd.concat([p["npairs"] for p in parts])
    T["model"], T["stratum"] = {}, {}
    for p in parts:
        T["model"].update(p["model"])
        T["stratum"].update(p["stratum"])
    if "P3" in parts[0]:
        T["P3"] = pd.concat([p["P3"] for p in parts], ignore_index=True)
    # join-clean copy rule: a (non-synthetic) call_id that occurs in more than one session of the pooled set
    cnt = T["cid"].groupby("call_id").session_id.nunique()
    copied = set(cnt[cnt > 1].index.astype(str))
    T["copied_call_ids"] = len(copied)
    for k in ("W", "G", "Q") + (("P3",) if "P3" in T else ()):
        T[k]["jc"] = T[k].jc0.to_numpy(dtype=bool) & ~T[k].call_id.astype(str).isin(copied).to_numpy()
    return T


def sel(df, pop):
    return df if pop == "BuE" else df[df.split == pop]


# ================================================================================================ Probe 1 statistic
def sep_eval(W, G, with_detail=False):
    """fp_share and AUC exactly as probe_1 section 6 (W, G = rows with elig flag). Labels by prereg.json probe1."""
    We, Ge = W[W.elig], G[G.elig]
    nW, sW, nG, sG = int(len(We)), int(We.session_id.nunique()), int(len(Ge)), int(Ge.session_id.nunique())
    w_ok = nW >= TH["W_min_pairs"] and sW >= TH["W_min_sessions"]
    g_ok = nG >= TH["G_min_pairs"] and sG >= TH["G_min_sessions"]
    rw, rg = We.r.to_numpy(dtype=float), Ge.r.to_numpy(dtype=float)
    out = {"W_eligible": {"n": nW, "sessions": sW}, "G_eligible": {"n": nG, "sessions": sG},
           "W_meets_min_n": bool(w_ok), "G_meets_min_n": bool(g_ok)}
    if w_ok:
        fp = p1.rate_from_mask(rw >= 1, We.session_id.to_numpy())
        p, hi = fp["rate"], fp["verdict_hi"]
        fpl = ("ALIVE" if p <= TH["fp_alive_point"] and hi <= TH["fp_alive_hi"]
               else "WEAK" if p <= TH["fp_weak_point"] else "DEAD")
    else:
        fp = {"num": int((rw >= 1).sum()), "den": nW, "n_sessions": sW, "label": "INSUFFICIENT_N"}
        fpl = "INSUFFICIENT_N"
    if w_ok and g_ok:
        a = p1.auc_ci(np.log10(rg), Ge.session_id.to_numpy(), np.log10(rw), We.session_id.to_numpy())
        al = ("ALIVE" if a["auc"] >= TH["auc_alive_point"] and a.get("lo") is not None and a["lo"] >= TH["auc_alive_lo"]
              else "WEAK" if a["auc"] >= TH["auc_weak_point"] else "DEAD")
    else:
        a = {"auc_point_unreportable": p1.auc_value(np.log10(rg), np.log10(rw)) if (len(rg) and len(rw)) else None,
             "n_G": nG, "n_W": nW, "label": "INSUFFICIENT_N"}
        al = "INSUFFICIENT_N"
    out.update({"fp_share": fp, "fp_label": fpl, "auc": a, "auc_label": al})
    if fpl == "INSUFFICIENT_N":
        sv = "INSUFFICIENT_N"
    elif fpl == "DEAD" or al == "DEAD":
        sv = "DEAD"
    elif fpl == "ALIVE" and al == "ALIVE":
        sv = "ALIVE"
    else:
        sv = "WEAK"
    out["separability_label"] = sv
    if with_detail and len(rw):
        out["W_eligible_by_tool"] = {k: {"n": int((We.key == k).sum()), "r_ge_1": int(((We.key == k) & (We.r >= 1)).sum())}
                                     for k in sorted(set(We.key))}
        out["G_eligible_by_tool"] = {k: {"n": int((Ge.key == k).sum()),
                                         "median_r": float(np.median(Ge.r[Ge.key == k]))} for k in sorted(set(Ge.key))}
        out["W_log10_r_quantiles"] = {q: float(np.quantile(np.log10(rw), float(q))) for q in ("0.5", "0.95", "0.99")}
        if len(rg):
            out["G_log10_r_quantiles"] = {q: float(np.quantile(np.log10(rg), float(q))) for q in ("0.05", "0.5", "0.95")}
    return out


def flat_block(unit, Q):
    W_KEYS = set(cal.W_KEYS[unit]) if unit in cal.W_KEYS else set(p1.TOOL_CLASSES_AUTO_READ)
    res_s = TH["stamp_resolution_s"]["aiv_cc"] if unit == "aiv_cc" else TH["stamp_resolution_s"]["ms_units"]
    flat = {}
    for k, g in Q.groupby("key"):
        n, ns = int(len(g)), int(g.session_id.nunique())
        if n < TH["flat_min_pairs"] or ns < TH["flat_min_sessions"]:
            flat[k] = {"reportable": False, "n": n, "n_sessions": ns, "in_W": k in W_KEYS}
            continue
        d = g.delta_s.to_numpy(dtype=float)
        iqr_s = float(np.quantile(d, 0.75) - np.quantile(d, 0.25))
        lg = np.log10(d)
        iqr_l = float(np.quantile(lg, 0.75) - np.quantile(lg, 0.25))
        f1, f2 = iqr_s <= TH["flat_iqr_res_mult"] * res_s, iqr_l < TH["flat_iqr_log10"]
        flat[k] = {"reportable": True, "in_W": k in W_KEYS, "iqr_s": iqr_s, "iqr_log10": iqr_l, "FLAT": bool(f1 or f2),
                   "n": n, "n_sessions": ns}
    wrep = [k for k, v in flat.items() if v["in_W"] and v["reportable"]]
    return {"by_tool": flat, "W_reportable": sorted(wrep), "W_reportable_flat": sorted(k for k in wrep if flat[k]["FLAT"]),
            "all_W_flat_kill": bool(len(wrep) > 0 and all(flat[k]["FLAT"] for k in wrep))}


def transfer_block(unit, Q):
    floorsA = PR["resolved"]["probe1"]["floors"].get(unit, {})
    tr = {}
    for k, ent in floorsA.items():
        if "p5" not in ent:
            continue
        g = Q[Q.key == k]
        row = {"A_p5": ent["p5"], "n": int(len(g)), "sessions": int(g.session_id.nunique())}
        if len(g) < TH["transfer_min_B_n"] or row["sessions"] < PR["global"]["min_n"]["rate_reportable"]["sessions_min"]:
            row["label"] = "NOT_TESTED_n"
            tr[k] = row
            continue
        r = p1.rate_from_mask(g.delta_s.to_numpy() < ent["p5"], g.session_id.to_numpy())
        row["share_below_A_p5"] = r
        lo, hi = r["lo"], r["verdict_hi"]
        b0, b1 = TH["transfer_band"]
        row["label"] = "TRANSFERS" if (lo <= b1 and hi >= b0) else "FLOOR_SHIFT"
        if row["label"] == "FLOOR_SHIFT":
            row["direction"] = "lower floor (more pairs below A p5)" if lo > b1 else "higher floor (fewer pairs below A p5)"
        tr[k] = row
    tested = [k for k, v in tr.items() if v["label"] in ("TRANSFERS", "FLOOR_SHIFT")]
    shifted = [k for k in tested if tr[k]["label"] == "FLOOR_SHIFT"]
    return {"by_tool": tr, "tested": sorted(tested), "floor_shift": sorted(shifted),
            "majority_floor_shift": bool(len(tested) > 0 and len(shifted) > len(tested) / 2)}


def floor_block(Q):
    """probe_1 section 5 verbatim: series per (session, tool_key) with n >= 2m, seed SEED + i over eligible series
    in sorted (session_id, tool_key) order of the population passed in."""
    series = []
    Qs = Q.sort_values(["session_id", "seq"])
    for (s, k), g in Qs.groupby(["session_id", "key"], sort=True):
        if len(g) >= 2 * TH["step_m"]:
            series.append((s, k, np.log10(g.delta_s.to_numpy(dtype=float))))
    series.sort(key=lambda x: (x[0], x[1]))
    rows = []
    for i, (s, k, x) in enumerate(series):
        cp = pc.change_point(x, m=TH["step_m"], n_perm=TH["step_n_perm"], seed=stats.SEED + i)
        rows.append({"_sid": s, "tool_key": k, "n": cp["n"], "k_over_n": cp["k"] / cp["n"], "D_log10": cp["D"],
                     "p": cp["p"], "step": cp["step"], "direction": cp["direction"]})
    n_el, n_st = len(rows), int(sum(r["step"] for r in rows))
    sc = {"eligible_series": n_el, "steps": n_st, "eligible_sessions": len({r["_sid"] for r in rows}),
          "sessions_with_step": len({r["_sid"] for r in rows if r["step"]})}
    if n_el:
        sc["step_share_wilson"] = dict(zip(("p", "lo", "hi"), stats.wilson(n_st, n_el)))
        sc["label"] = "STABLE" if n_st / n_el <= TH["step_share_unstable"] else "UNSTABLE"
        sc["steps_by_direction"] = dict(Counter(r["direction"] for r in rows if r["step"]))
        sc["by_tool"] = {k: {"eligible": sum(1 for r in rows if r["tool_key"] == k),
                             "steps": sum(1 for r in rows if r["tool_key"] == k and r["step"])}
                         for k in sorted({r["tool_key"] for r in rows})}
    else:
        sc["label"] = "NO_ELIGIBLE_SERIES"
    sc["K2_testable"] = bool(n_el >= 30 and sc["eligible_sessions"] >= 5)  # K2: < 30 series or < 5 s -> floor untested
    sc["_rows"] = rows
    return sc


def full_verdict(unit, sep, ctx):
    o = {"separability": sep, "a1_recheck_B": ctx["a1"], "flat_test": ctx["flat"], "floor_step_change": ctx["floor"],
         "floor_transfer": ctx["transfer"]}
    return p1.unit_verdict(unit, o)


def p1_population(unit, T, pop):
    W, G, Q, A = sel(T["W"], pop), sel(T["G"], pop), sel(T["Q"], pop), sel(T["a1"], pop)
    a1 = p1.a1_recheck(A)
    ctx = {"a1": a1, "flat": flat_block(unit, Q), "transfer": transfer_block(unit, Q), "floor": floor_block(Q)}
    sep = sep_eval(W, G, with_detail=True)
    v = full_verdict(unit, sep, ctx)
    fl = dict(ctx["floor"])
    rows = fl.pop("_rows")
    if unit != "cc_local":
        fl["series"] = [{k: r[k] for k in r if k != "_sid"} for r in rows]
    return {"sessions": int(pd.concat([W.session_id, G.session_id, Q.session_id]).nunique()),
            "a1_recheck": {k: a1.get(k) for k in ("verdict", "reason", "n_pairs", "n_pairs_both_ts",
                                                   "n_sessions_both_ts", "whole_second_stamp_share",
                                                   "identical_stamp_share", "negative_deltas")},
            "flat_test": ctx["flat"], "floor_transfer": ctx["transfer"], "floor_step_change": fl,
            "separability": sep, "verdict": {k: v[k] for k in ("verdict", "rule_applied", "fp_label", "auc_label",
                                                                 "floor_step_label", "floor_transfer_majority_shift",
                                                                 "kills", "downgrade", "labels")}}, ctx


def label_under(unit, W, G, ctx):
    sep = sep_eval(W, G)
    v = full_verdict(unit, sep, ctx)["verdict"]
    return sep, v


def brief(sep):
    fp, a = sep["fp_share"], sep["auc"]
    return {"W_eligible": sep["W_eligible"], "G_eligible": sep["G_eligible"],
            "fp": {k: fp.get(k) for k in ("num", "den", "n_sessions", "rate", "lo", "hi", "verdict_hi", "label")},
            "auc": {k: a.get(k) for k in ("auc", "lo", "hi", "n_G", "n_W", "valid_draws", "label",
                                           "auc_point_unreportable")},
            "fp_label": sep["fp_label"], "auc_label": sep["auc_label"], "separability_label": sep["separability_label"]}


# ================================================================================================ weighted (AC5)
def weighted_auc_ci(g, gs, w, ws, wt):
    """AUC = sum_ij wg_i ww_j ([g_i > w_j] + 0.5 [g_i == w_j]) / (sum wg sum ww), pair weight = session weight; CI by
    the probe_1.auc_ci session draw (same rng, sessions resampled once per draw, multiplicities as weights)."""
    g, w = np.asarray(g, dtype=float), np.asarray(w, dtype=float)
    gs, ws = np.asarray(gs, dtype=object).astype(str), np.asarray(ws, dtype=object).astype(str)
    sess = sorted(set(gs.tolist()) | set(ws.tolist()))
    sidx = {s: i for i, s in enumerate(sess)}
    gi = np.array([sidx[s] for s in gs], dtype=int)
    wi = np.array([sidx[s] for s in ws], dtype=int)
    sw = np.array([wt.get(s, 0.0) for s in sess], dtype=float)
    order = np.argsort(w, kind="stable")
    w_sorted = w[order]
    wi_sorted = wi[order]
    lo_pos = np.searchsorted(w_sorted, g, side="left")
    hi_pos = np.searchsorted(w_sorted, g, side="right")

    def auc_with(mult):
        sweight = sw * mult
        ww = sweight[wi_sorted]
        cw = np.concatenate([[0.0], np.cumsum(ww)])
        wg = sweight[gi]
        tot_w, tot_g = cw[-1], wg.sum()
        if tot_w <= 0 or tot_g <= 0:
            return None
        below = cw[lo_pos]
        ties = cw[hi_pos] - cw[lo_pos]
        return float((wg * (below + 0.5 * ties)).sum() / (tot_g * tot_w))

    val = auc_with(np.ones(len(sess)))
    rng = np.random.default_rng(stats.SEED)
    boots = []
    for _ in range(stats.N_BOOT):
        pick = rng.integers(0, len(sess), size=len(sess))
        v = auc_with(np.bincount(pick, minlength=len(sess)).astype(float))
        if v is not None:
            boots.append(v)
    out = {"auc": val, "valid_draws": len(boots), "n_G": int(len(g)), "n_W": int(len(w))}
    if len(boots) >= TH["ci_valid_draws_min"]:
        out["lo"], out["hi"] = float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975))
    return out


def weighted_sep(W, G, wt):
    We, Ge = W[W.elig], G[G.elig]
    sids = sorted(set(We.session_id))
    num = We.assign(f=(We.r >= 1).astype(int)).groupby("session_id").f.sum().reindex(sids).to_numpy(dtype=float)
    den = We.groupby("session_id").size().reindex(sids).to_numpy(dtype=float)
    w = np.array([wt.get(s, 0.0) for s in sids], dtype=float)
    fp = E.weighted_cluster_rate(num, den, w)
    fp["num_unweighted"], fp["den_unweighted"] = int(num.sum()), int(den.sum())
    hi = fp["hi"] if num.sum() > 0 else stats.wilson(0, int(den.sum()))[2]  # zero-count rule (prereg.json global)
    fp["verdict_hi"] = hi
    fpl = ("ALIVE" if fp["rate"] <= TH["fp_alive_point"] and hi <= TH["fp_alive_hi"]
           else "WEAK" if fp["rate"] <= TH["fp_weak_point"] else "DEAD")
    g_ok = len(Ge) >= TH["G_min_pairs"] and Ge.session_id.nunique() >= TH["G_min_sessions"]
    if g_ok:
        a = weighted_auc_ci(np.log10(Ge.r.to_numpy(dtype=float)), Ge.session_id.to_numpy(),
                            np.log10(We.r.to_numpy(dtype=float)), We.session_id.to_numpy(), wt)
        al = ("ALIVE" if a["auc"] >= TH["auc_alive_point"] and a.get("lo") is not None and a["lo"] >= TH["auc_alive_lo"]
              else "WEAK" if a["auc"] >= TH["auc_weak_point"] else "DEAD")
    else:
        a, al = {"label": "INSUFFICIENT_N"}, "INSUFFICIENT_N"
    # unweighted control with the same function (all weights 1) -> must equal probe_1.auc_ci
    a1w = weighted_auc_ci(np.log10(Ge.r.to_numpy(dtype=float)), Ge.session_id.to_numpy(),
                          np.log10(We.r.to_numpy(dtype=float)), We.session_id.to_numpy(),
                          {s: 1.0 for s in set(We.session_id) | set(Ge.session_id)}) if g_ok else None
    return fp, fpl, a, al, a1w


# ================================================================================================ dominance (AC4)
def cluster_maps(unit, sids, model_map, corpus):
    frame = pd.DataFrame({"session_id": sorted(sids)})
    maps = {}
    if corpus == "swechat":
        maps["repo"] = norm_clusters(E.session_cluster_map("swechat", frame, "repo"))
        maps["user"] = norm_clusters(E.session_cluster_map("swechat", frame, "user"))
    else:  # cc_local: repo = IR stratum (project alias); no user field
        maps["repo"] = None
    maps["model"] = {s: model_map.get(s, "unknown") for s in frame.session_id}
    return maps


def dom_summary(d, anon):
    return {"top_share_events": d.get("top_share_events"), "top_share_sessions": d.get("top_share_sessions"),
            "top_session_share_events": d.get("top_session_share_events"), "n_clusters": d.get("n_clusters"),
            "top_clusters": [(anon.get(c, c), se, ss) for c, se, ss in d.get("top_clusters", [])],
            "cluster_dominated": bool(d.get("total", 0) > 0 and max(d["top_share_events"], d["top_share_sessions"])
                                      > E.DOM_SHARE),
            "session_dominated": bool(d.get("total", 0) > 0 and d["top_session_share_events"] > E.DOM_SESSION)}


# ================================================================================================ AC1 raw audit
def _parse_line(line):
    try:
        return [json.loads(line)]
    except ValueError:
        dec, out, i, s = json.JSONDecoder(strict=False), [], 0, line.strip()
        while i < len(s):
            try:
                o, j = dec.raw_decode(s, i)
            except ValueError:
                break
            out.append(o)
            i = j
            while i < len(s) and s[i].isspace():
                i += 1
        return out


def _walk(o, ts, calls, results):
    if isinstance(o, dict):
        t = o["timestamp"] if isinstance(o.get("timestamp"), str) else ts
        typ = o.get("type")
        if typ in ("tool_use", "server_tool_use") and isinstance(o.get("id"), str):
            calls.setdefault(o["id"], t)
        elif typ == "tool_result" and isinstance(o.get("tool_use_id"), str):
            results.setdefault(o["tool_use_id"], (t, o.get("is_error"), o.get("content")))
        for k, v in o.items():
            if k == "normalizedMessages":  # duplicates data.message history (lib/cc_jsonl docstring)
                continue
            if isinstance(v, (dict, list)):
                _walk(v, t, calls, results)
    elif isinstance(o, list):
        for v in o:
            if isinstance(v, (dict, list)):
                _walk(v, ts, calls, results)


def raw_cc_index(paths, want=None):
    calls, results, bad = {}, {}, 0
    for p in paths:
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                if want is not None and not any(w in line for w in want):
                    continue
                objs = _parse_line(line)
                if not objs and line.strip():
                    bad += 1
                for x in objs:
                    _walk(x, None, calls, results)
    return calls, results, bad


def raw_text(content):
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    out = []
    for b in content if isinstance(content, list) else [content]:
        if isinstance(b, dict):
            if b.get("type") == "text":
                out.append(b.get("text") or "")
            elif b.get("type") == "image":
                out.append("[image]")
            elif "text" in b:
                out.append(str(b.get("text")))
        else:
            out.append(str(b))
    return "\n".join(out)


def iso_ms(s):
    if isinstance(s, (int, float)):
        return float(s)
    if not isinstance(s, str):
        return None
    m = re.match(r"^(\d{4}-\d\d-\d\d)[T ](\d\d:\d\d:\d\d)(?:\.(\d+))?(Z|[+-]\d\d:?\d\d)?$", s.strip())
    if not m:
        return None
    d, hms, frac, tz = m.groups()
    tz = "+00:00" if tz in (None, "Z") else (tz if ":" in tz else tz[:3] + ":" + tz[3:])
    dt = datetime.fromisoformat(f"{d}T{hms}.{(frac or '')[:6].ljust(6, '0')}{tz}")
    return dt.timestamp() * 1000.0


def cc_local_paths(sid):
    mains = glob.glob(os.path.join(CC_LOCAL_ROOT, "*", f"{sid}.jsonl"))
    subs = []
    for m in mains:
        subs += glob.glob(os.path.join(m[:-6], "**", "*.jsonl"), recursive=True)
    return mains + subs


def audit_p1(unit, W):
    """AC1 for Probe 1: numerator events = eligible W pairs with r >= 1 (B u E). Fields compared: call stamp, result
    stamp, result text length (T_gen), call/result join. A difference changes the contribution if the raw values give
    T_gen < 1 s or r < 1, or the pair is not found."""
    G90 = PR["resolved"]["probe1"]["generation_rate"][unit]["G90"]
    num = W[W.elig & (W.r >= 1)].sort_values(["split", "session_id", "call_id"])
    keys = list(zip(num.split, num.session_id, num.call_id))
    sample = set(E.audit_sample(keys, seed_parts=("audit", "a1_p1_p3", unit)))
    rows = num[[k in sample for k in keys]]
    res = []
    by_s = defaultdict(list)
    for r in rows.itertuples():
        by_s[r.session_id].append(r)
    for sid, rs in by_s.items():
        want = [r.call_id for r in rs]
        if unit == "swechat/opencode":
            raw = {}
            try:
                doc = json.load(open(E.SWE_TRANSCRIPTS / f"{sid}.jsonl", encoding="utf-8"))
                parts = [pt for msg in doc.get("messages", []) for pt in (msg.get("parts") or [])
                         if isinstance(pt, dict) and pt.get("type") == "tool"]
            except (ValueError, OSError):
                parts = None
            for r in rs:
                ent = {"found": False}
                if parts is not None:
                    idx = None
                    if not r.call_id.startswith("synthetic:"):
                        idx = next((i for i, pt in enumerate(parts) if pt.get("callID") == r.call_id), None)
                    else:
                        idx = r.ord if 0 <= r.ord < len(parts) else None
                    if idx is not None:
                        st = parts[idx].get("state") or {}
                        tm = st.get("time") or {}
                        txt = st.get("output") or st.get("error")
                        ent = {"found": True, "by": "callID" if not r.call_id.startswith("synthetic:") else "ordinal",
                               "ord_matches": idx == r.ord, "call_ms": iso_ms(tm.get("start")),
                               "result_ms": iso_ms(tm.get("end")), "chars": len(txt) if isinstance(txt, str) else 0}
                raw[r.call_id] = ent
        else:
            paths = ([str(E.SWE_TRANSCRIPTS / f"{sid}.jsonl")] if unit != "cc_local" else cc_local_paths(sid))
            calls, results, _ = raw_cc_index([p for p in paths if os.path.exists(p)], want)
            raw = {}
            for c in want:
                if c in calls and c in results:
                    t, _, content = results[c]
                    raw[c] = {"found": True, "by": "tool_use_id", "call_ms": iso_ms(calls[c]), "result_ms": iso_ms(t),
                              "chars": len(raw_text(content))}
                else:
                    raw[c] = {"found": False, "call_found": c in calls, "result_found": c in results}
        for r in rs:
            ent = raw.get(r.call_id, {"found": False})
            row = {"split": r.split, "found": ent["found"], "by": ent.get("by")}
            if ent["found"] and ent.get("call_ms") is not None and ent.get("result_ms") is not None:
                d_raw = (ent["result_ms"] - ent["call_ms"]) / 1000.0
                T_raw = ent["chars"] * TH["tokens_per_char"] / G90
                r_raw = d_raw / T_raw if T_raw > 0 else float("nan")
                row.update({"abs_delta_diff_s": abs(d_raw - float(r.delta_s)), "chars_diff": int(ent["chars"] - r.chars_r),
                            "ord_matches": ent.get("ord_matches"),
                            "contribution_changed": bool(not (T_raw >= TH["T_gen_min_s"] and r_raw >= 1)),
                            "field_differs": bool(abs(d_raw - float(r.delta_s)) > 0.0015 or ent["chars"] != r.chars_r)})
            elif unit == "cc_local":  # search restricted to the session's root file-set (prereg 1.4 scope rule)
                row.update({"contribution_changed": False, "field_differs": False, "not_located_in_root_fileset": True})
            else:
                row.update({"contribution_changed": True, "field_differs": True})
            res.append(row)
    n_diff = sum(1 for x in res if x["contribution_changed"])
    out = {"numerator_events": int(len(num)), "audited": len(res), "seed_parts": ["audit", "a1_p1_p3", unit],
           "found": sum(1 for x in res if x["found"]),
           "field_differs": sum(1 for x in res if x["field_differs"]),
           "contribution_changed": n_diff,
           "max_abs_delta_diff_s": max([x["abs_delta_diff_s"] for x in res if "abs_delta_diff_s" in x], default=None),
           "chars_diff_nonzero": sum(1 for x in res if x.get("chars_diff", 0) != 0),
           "located_by": dict(Counter(x["by"] for x in res if x["found"])),
           "not_located_in_root_fileset": sum(1 for x in res if x.get("not_located_in_root_fileset")),
           "result": "FAIL" if n_diff >= E.AUDIT_FAIL else "PARSER_NOTE" if n_diff == 1 else "PASS"}
    if unit != "cc_local":
        out["rows"] = res
    return out


def audit_p3(S_zero_long, T):
    """AC1 for Probe 3: numerator events = long sessions with zero primary errors (B u E). Fields compared, per
    session from the raw transcript: number of paired calls (tool_use with a tool_result) and primary errors
    (is_error true and no permission/interrupt marker). Contribution changes if raw n_calls < L75 or raw errors > 0."""
    keys = sorted(S_zero_long)
    sample = E.audit_sample(keys, seed_parts=("audit", "a1_p1_p3", "P3zero"))
    rows = []
    for split, sid in sample:
        calls, results, bad = raw_cc_index([str(E.SWE_TRANSCRIPTS / f"{sid}.jsonl")])
        paired = [c for c in calls if c in results]
        n_err = 0
        for c in paired:
            _, is_err, content = results[c]
            if is_err is True and error_marker(raw_text(content)) not in ("cc_permission_denied", "cc_interrupt_reject"):
                n_err += 1
        ir_n = int(S_zero_long[(split, sid)])
        rows.append({"split": split, "session": sid, "ir_n_calls": ir_n, "raw_n_calls": len(paired), "raw_errors": n_err,
                     "bad_lines": bad, "field_differs": bool(len(paired) != ir_n or n_err > 0),
                     "contribution_changed": bool(len(paired) < L75 or n_err > 0)})
    n_diff = sum(1 for r in rows if r["contribution_changed"])
    return {"numerator_events": len(keys), "audited": len(rows), "seed_parts": ["audit", "a1_p1_p3", "P3zero"],
            "field_differs": sum(1 for r in rows if r["field_differs"]), "contribution_changed": n_diff,
            "result": "FAIL" if n_diff >= E.AUDIT_FAIL else "PARSER_NOTE" if n_diff == 1 else "PASS", "rows": rows}


# ================================================================================================ survival helpers
def min_check(name, ref_label, check_label, running):
    """AC2 / AC3 / AC5 / P1-K3 semantics: FAIL if the label changes (only a lower label counts: no rescue); the
    candidate then takes the lower label. Returns (check dict for survival_status, new running label)."""
    if check_label not in LEVEL or ref_label not in LEVEL:
        return {"name": name, "effect": "pass", "result": "UNTESTABLE", "ref": ref_label, "check": check_label}, running
    if LEVEL[check_label] >= LEVEL[ref_label]:
        res = "PASS" if check_label == ref_label else "PASS (higher label ignored: no rescue)"
        return {"name": name, "effect": "pass", "result": res, "ref": ref_label, "check": check_label}, running
    tgt = lower(running, check_label)
    if tgt == running:
        eff = "pass"
    elif tgt == "DEAD":
        eff = "kill"
    else:
        eff = "downgrade" if LEVEL[running] - LEVEL[tgt] == 1 else "kill"
    return {"name": name, "effect": eff, "result": "FAIL", "ref": ref_label, "check": check_label,
            "candidate_label_before": running, "candidate_label_after": tgt}, tgt


def alt_order(phase_b, e_label, checks_min, checks_other, has_e):
    """Final label if downgrades/caps are applied first and the min-type FAILs ('take the lower label') after."""
    _, lab, _ = E.survival_status(phase_b, e_label, checks_other, has_e=has_e)
    for c in checks_min:
        if c.get("result") == "FAIL":
            lab = lower(lab, c["check"])
    return lab


# ================================================================================================ P1 candidate
def run_p1(unit, T, t0):
    cand = f"P1/{unit}"
    has_e = unit != "cc_local"
    corpus = "cc_local" if unit == "cc_local" else "swechat"
    out = {"candidate": cand, "unit": unit, "phase_b_label": PHASE_B[cand], "has_E": has_e,
           "labels": (["private (aggregates only)", "B only, unreplicated"] if unit == "cc_local" else []),
           "copied_call_ids_in_pool": T["copied_call_ids"]}
    pops = ["B", "E", "BuE"] if has_e else ["B"]
    res, ctxs = {}, {}
    for pop in pops:
        res[pop], ctxs[pop] = p1_population(unit, T, pop)
        print(f"[{time.time() - t0:7.1f}s] {cand} {pop}: verdict {res[pop]['verdict']['verdict']} "
              f"fp {res[pop]['separability']['fp_share'].get('num')}/{res[pop]['separability']['fp_share'].get('den')} "
              f"auc {res[pop]['separability']['auc'].get('auc')}", flush=True)
    if not has_e:
        res["BuE"], ctxs["BuE"] = res["B"], ctxs["B"]
    out["populations"] = {k: v for k, v in res.items() if not (k == "BuE" and not has_e)}
    if not has_e:
        out["populations_note"] = "no E split (prereg_e.json splits.no_E.cc_local): B u E = B"
    # ---- reproduction of the committed Phase B numbers (same statistic, same code path)
    pb = json.load(open(ROOT / "analysis" / "out" / "probe_1.json", encoding="utf-8"))["units"][unit]
    sB = res["B"]["separability"]
    out["reproduction_B_vs_phase_b"] = {
        "fp_num": [sB["fp_share"]["num"], pb["separability"]["fp_share"]["num"]],
        "fp_den": [sB["fp_share"]["den"], pb["separability"]["fp_share"]["den"]],
        "auc": [sB["auc"].get("auc"), pb["separability"]["auc"].get("auc")],
        "G_eligible": [sB["G_eligible"]["n"], pb["separability"]["G_eligible"]["n"]],
        "floor_steps": [[res["B"]["floor_step_change"]["steps"], res["B"]["floor_step_change"]["eligible_series"]],
                        [pb["floor_step_change"]["steps"], pb["floor_step_change"]["eligible_series"]]],
        "transfer_shift": [res["B"]["floor_transfer"]["floor_shift"], pb["floor_transfer"]["floor_shift"]],
        "verdict": [res["B"]["verdict"]["verdict"], pb["verdict"]["verdict"]]}
    rp = out["reproduction_B_vs_phase_b"]
    rp["all_match"] = bool(rp["fp_num"][0] == rp["fp_num"][1] and rp["fp_den"][0] == rp["fp_den"][1]
                           and abs((rp["auc"][0] or 0) - (rp["auc"][1] or 0)) < 1e-12
                           and rp["G_eligible"][0] == rp["G_eligible"][1] and rp["floor_steps"][0] == rp["floor_steps"][1]
                           and rp["transfer_shift"][0] == rp["transfer_shift"][1] and rp["verdict"][0] == rp["verdict"][1])
    ctx = ctxs["BuE"]
    W, G = T["W"], T["G"]
    ref_full = res["BuE"]["verdict"]["verdict"]
    e_label = res["E"]["verdict"]["verdict"] if has_e else None
    running = e_label if (has_e and e_label in LEVEL) else PHASE_B[cand]
    checks_min = []
    ac = {}
    # ---------------------------------------------------------------- AC2 truncation
    sep2, l2 = label_under(unit, W[~W.trunc], G[~G.trunc], ctx)
    ac["AC2_truncation"] = {"dropped_W_eligible": int((W.elig & W.trunc).sum()), "dropped_G_eligible": int((G.elig & G.trunc).sum()),
                            "recomputed": brief(sep2), "label": l2, "reference_label": ref_full}
    c, running = min_check("AC2_truncation", ref_full, l2, running)
    ac["AC2_truncation"].update({"result": c["result"]})
    checks_min.append(c)
    # ---------------------------------------------------------------- AC3 join
    sep3, l3 = label_under(unit, W[W.jc], G[G.jc], ctx)
    ac["AC3_join"] = {"dropped_W_eligible": int((W.elig & ~W.jc).sum()), "dropped_G_eligible": int((G.elig & ~G.jc).sum()),
                      "copied_call_ids_in_pool": T["copied_call_ids"], "recomputed": brief(sep3), "label": l3,
                      "reference_label": ref_full}
    c, running = min_check("AC3_join", ref_full, l3, running)
    ac["AC3_join"].update({"result": c["result"]})
    checks_min.append(c)
    print(f"[{time.time() - t0:7.1f}s] {cand}: AC2 {l2} AC3 {l3}", flush=True)
    # ---------------------------------------------------------------- K3 stamp quality (min semantics)
    sepk3, lk3 = label_under(unit, W[~W.ws], G[~G.ws], ctx)
    k3 = {"dropped_W_eligible": int((W.elig & W.ws).sum()), "dropped_G_eligible": int((G.elig & G.ws).sum()),
          "recomputed": brief(sepk3), "label": lk3, "reference_label": ref_full}
    c, running = min_check("K3_stamp_quality", ref_full, lk3, running)
    k3["result"] = c["result"]
    checks_min.append(c)
    # ---------------------------------------------------------------- AC5 sampling
    if corpus == "swechat":
        sids_all = sorted(set(T["npairs"].index.astype(str)))
        wt = E.post_strat_weights("swechat", sids_all)
        fpw, fplw, aw, alw, a_ctrl = weighted_sep(W, G, wt)
        sep_w = {"fp_share": {**fpw, "label": fplw}, "fp_label": fplw, "auc": aw, "auc_label": alw,
                 "W_eligible": res["BuE"]["separability"]["W_eligible"], "G_eligible": res["BuE"]["separability"]["G_eligible"]}
        sv = ("DEAD" if "DEAD" in (fplw, alw) else "ALIVE" if (fplw == "ALIVE" and alw == "ALIVE") else "WEAK")
        sep_w["separability_label"] = sv
        l5 = full_verdict(unit, sep_w, ctx)["verdict"]
        wvals = np.array([wt[s] for s in sids_all])
        ac["AC5_sampling"] = {"weights": {"sessions": len(sids_all), "min": float(wvals.min()), "max": float(wvals.max()),
                                          "cells": len(set(E.population_cells("swechat").get(s, "unknown") for s in sids_all))},
                              "weighted_fp": fpw, "weighted_fp_label": fplw, "weighted_auc": aw, "weighted_auc_label": alw,
                              "unweighted_control_same_function": {"auc": a_ctrl.get("auc") if a_ctrl else None,
                                                                   "lo": a_ctrl.get("lo") if a_ctrl else None,
                                                                   "hi": a_ctrl.get("hi") if a_ctrl else None},
                              "label": l5, "reference_label": ref_full}
        c, running = min_check("AC5_sampling", ref_full, l5, running)
        ac["AC5_sampling"]["result"] = c["result"]
        checks_min.append(c)
        # SHIFT: B point outside E CI (no verdict effect)
        sB, sE = res["B"]["separability"], res["E"]["separability"]
        sh = {}
        if sE["fp_label"] != "INSUFFICIENT_N":
            lo, hi = sE["fp_share"]["lo"], sE["fp_share"]["verdict_hi"]
            sh["fp"] = {"B_point": sB["fp_share"]["rate"], "E_ci": [lo, hi],
                        "SHIFT": bool(not (lo <= sB["fp_share"]["rate"] <= hi))}
        if sE["auc_label"] != "INSUFFICIENT_N" and sE["auc"].get("lo") is not None and sB["auc"].get("auc") is not None:
            sh["auc"] = {"B_point": sB["auc"]["auc"], "E_ci": [sE["auc"]["lo"], sE["auc"]["hi"]],
                         "SHIFT": bool(not (sE["auc"]["lo"] <= sB["auc"]["auc"] <= sE["auc"]["hi"]))}
        ac["AC5_sampling"]["SHIFT_B_vs_E"] = sh
    else:
        ac["AC5_sampling"] = {"result": "NOT_RUN", "reason": "no population table for cc_local (prereg_e.json "
                                                             "artifact_checks.AC5_sampling)"}
    print(f"[{time.time() - t0:7.1f}s] {cand}: K3 {lk3} AC5 {ac['AC5_sampling'].get('label')}", flush=True)
    # ---------------------------------------------------------------- AC4 dominance
    sids = sorted(set(W.session_id) | set(G.session_id))
    maps = cluster_maps(unit, sids, T["model"], corpus)
    if corpus == "cc_local":  # repo cluster = IR stratum (project alias), via session_cluster_map
        fr = pd.DataFrame({"session_id": sids, "stratum": [T["stratum"].get(s, "unknown") for s in sids]})
        maps["repo"] = norm_clusters(E.session_cluster_map("cc_local", fr, "repo"))
    kinds = {k: v for k, v in maps.items() if v is not None}
    kinds["session"] = {s: s for s in sids}
    We, Ge = W[W.elig], G[G.elig]
    wW = We.groupby("session_id").size().to_dict()
    wG = Ge.groupby("session_id").size().to_dict()
    dom = {}
    leave = []
    for kind, cmap in kinds.items():
        ent = {}
        top_lists = []
        cw, cg = Counter(), Counter()  # one anonymised ranking per kind: eligible W pairs, then eligible G pairs
        for s_, n_ in wW.items():
            cw[cmap.get(s_, "unknown")] += n_
        for s_, n_ in wG.items():
            cg[cmap.get(s_, "unknown")] += n_
        allc = sorted(set(cw) | set(cg), key=lambda c_: (-cw[c_], -cg[c_], str(c_)))
        anon = anon_rank(allc, kind) if (kind == "session" or (corpus == "swechat" and kind in ("repo", "user"))) else {}
        for nm, wmap in (("W", wW), ("G", wG)):
            if not wmap:
                continue
            d = E.dominance(wmap, cmap)
            order = [c for c, _, _ in d["top_clusters"]]
            ent[nm] = dom_summary(d, anon)
            isdom = ent[nm]["session_dominated"] if kind == "session" else ent[nm]["cluster_dominated"]
            ent[nm]["dominated_on_this_kind"] = bool(isdom)
            if isdom:
                top_lists.append((nm, order, anon))
        ent["dominated"] = bool(top_lists)
        seen = set()
        for nm, order, anon in top_lists:
            for c in order[:5]:
                if c in seen:
                    continue
                seen.add(c)
                drop = {s for s, cc in cmap.items() if cc == c}
                Wl, Gl = W[~W.session_id.isin(drop)], G[~G.session_id.isin(drop)]
                sepl, ll = label_under(unit, Wl, Gl, ctx)
                below = not (sepl["W_meets_min_n"] and sepl["G_meets_min_n"])
                leave.append({"kind": kind, "cluster": anon.get(c, c), "ranked_in": nm, "sessions_dropped": len(drop),
                              "recomputed": brief(sepl), "label": ll, "below_min_n": bool(below),
                              "label_drop": bool(lvl(ll) is not None and lvl(ref_full) is not None and lvl(ll) < lvl(ref_full))})
        dom[kind] = ent
    dominated_any = any(v["dominated"] for v in dom.values())
    drop_any = any(x["label_drop"] and not x["below_min_n"] for x in leave)
    below_any = any(x["below_min_n"] for x in leave)
    ac["AC4_dominance"] = {"denominator": "eligible W pairs (fp_share denominator) and eligible G pairs (AUC control), "
                                          "each tested; a kind is dominated if either is",
                           "kinds": dom, "dominated": dominated_any, "leave_outs": leave, "reference_label": ref_full,
                           "DOMINATED": bool(drop_any), "UNTESTABLE_WITHOUT_DOMINANT": bool(below_any)}
    ac4_checks = []
    if drop_any:
        ac4_checks.append({"name": "AC4_DOMINATED", "effect": "downgrade"})
    if below_any:
        ac4_checks.append({"name": "AC4_UNTESTABLE_WITHOUT_DOMINANT", "effect": "cap_weak"})
    ac["AC4_dominance"]["result"] = ("DOMINATED" if drop_any else "") + (
        (" + " if drop_any and below_any else "") + "UNTESTABLE_WITHOUT_DOMINANT" if below_any else "") or (
        "PASS" if dominated_any else "NOT_DOMINATED")
    print(f"[{time.time() - t0:7.1f}s] {cand}: AC4 {ac['AC4_dominance']['result']} ({len(leave)} leave-outs)", flush=True)
    # ---------------------------------------------------------------- AC1 parser
    ac["AC1_parser"] = audit_p1(unit, W)
    ac1_checks = [{"name": "AC1_parser_FAIL", "effect": "downgrade"}] if ac["AC1_parser"]["result"] == "FAIL" else []
    print(f"[{time.time() - t0:7.1f}s] {cand}: AC1 {ac['AC1_parser']['result']} "
          f"({ac['AC1_parser']['contribution_changed']}/{ac['AC1_parser']['audited']})", flush=True)
    # ---------------------------------------------------------------- K1 control composition
    Gr = G[G.key.isin(K1_G_TOOLS)]
    sepa, la = label_under(unit, W, Gr, ctx)
    Gre = Gr[Gr.elig]
    top = Gre.groupby("session_id").size().sort_values(ascending=False)
    topsid = top.index[0] if len(top) else None
    sepb, lb = label_under(unit, W[W.session_id != topsid], Gr[Gr.session_id != topsid], ctx)
    k1 = {"G_tools_kept": sorted(K1_G_TOOLS), "G_eligible_by_tool_before": dict(Counter(G[G.elig].key)),
          "step1_restricted": {"recomputed": brief(sepa), "label": la},
          "step2_minus_top_G_session": {"top_session_G_eligible_pairs": int(top.iloc[0]) if len(top) else 0,
                                        "top_session_share_of_G": float(top.iloc[0] / top.sum()) if len(top) else None,
                                        "recomputed": brief(sepb), "label": lb}}
    auc_dead = "DEAD" in (sepa["auc_label"], sepb["auc_label"])
    g_low = not (sepa["G_meets_min_n"] and sepb["G_meets_min_n"])
    k1["AUC_DEAD"], k1["G_below_min_n"] = bool(auc_dead), bool(g_low)
    k1_checks = []
    if auc_dead:
        k1_checks.append({"name": "K1_control_composition_AUC_DEAD", "effect": "kill"})
    if g_low:
        k1_checks.append({"name": "K1_control_too_concentrated", "effect": "cap_weak"})
    k1["result"] = "KILL" if auc_dead else "CAP_WEAK (control too concentrated)" if g_low else "PASS"
    # ---------------------------------------------------------------- K2 floor stability
    fl_bue = res["BuE"]["floor_step_change"]
    fl_e = res["E"]["floor_step_change"] if has_e else None
    k2 = {"BuE": {k: fl_bue.get(k) for k in ("eligible_series", "steps", "eligible_sessions", "step_share_wilson", "label",
                                              "K2_testable")}}
    if has_e:
        k2["E"] = {k: fl_e.get(k) for k in ("eligible_series", "steps", "eligible_sessions", "step_share_wilson", "label",
                                            "K2_testable")}
    unstable = [p for p, f in (("BuE", fl_bue), ("E", fl_e)) if f is not None and f["K2_testable"] and f["label"] == "UNSTABLE"]
    untested = [p for p, f in (("BuE", fl_bue), ("E", fl_e)) if f is not None and not f["K2_testable"]]
    basis = res["E"]["verdict"] if has_e else res["B"]["verdict"]
    already = bool(basis.get("downgrade") and "floor UNSTABLE" in basis["downgrade"])
    k2_checks = []
    if unstable and not already and basis["verdict"] == "ALIVE":
        k2_checks.append({"name": "K2_floor_UNSTABLE", "effect": "downgrade"})
        k2["result"] = "DOWNGRADE (UNSTABLE on " + ", ".join(unstable) + ")"
    elif unstable and already:
        k2["result"] = ("UNSTABLE on " + ", ".join(unstable) + "; the Phase B floor rule already lowered the "
                        + ("E" if has_e else "B") + " verdict ALIVE -> WEAK (not applied twice)")
    elif unstable:
        k2["result"] = "UNSTABLE on " + ", ".join(unstable) + "; Phase B floor rule acts on ALIVE only, label is " + basis["verdict"]
    else:
        k2["result"] = "PASS"
    if untested:
        k2["floor_untested"] = untested
    print(f"[{time.time() - t0:7.1f}s] {cand}: K1 {k1['result']} K2 {k2['result']}", flush=True)
    # ---------------------------------------------------------------- stratification
    strata = {}
    rep = lambda s: s["W_meets_min_n"]  # noqa: E731  reportable = not INSUFFICIENT_N under the Probe 1 rule
    axes = {}
    tool_lab = {}
    for k in sorted(set(W[W.elig].key)):
        s_, l_ = label_under(unit, W[W.key == k], G, ctx)
        tool_lab[k] = {"recomputed": brief(s_), "label": l_ if rep(s_) else None, "label_raw": l_}
    axes["tool"] = tool_lab
    model_map = kinds["model"]
    repo_map = kinds["repo"]
    terc = E.length_tercile_map(T["npairs"].to_dict(), PJ["resolved"]["length_terciles_A"][unit]["cuts"])
    for axis, cmap in (("model", model_map), ("repo", repo_map), ("length", terc)):
        lab = {}
        groups = defaultdict(set)
        for s, cval in cmap.items():
            groups[cval].add(s)
        ordered = sorted(groups, key=lambda c: -int(W[W.elig & W.session_id.isin(groups[c])].shape[0]))
        anon = anon_rank(ordered, axis) if (axis in ("repo",) and corpus == "swechat") else {}
        for cval in ordered:
            ss = groups[cval]
            Ws = W[W.session_id.isin(ss)]
            if int((Ws.elig).sum()) < TH["W_min_pairs"] or Ws[Ws.elig].session_id.nunique() < TH["W_min_sessions"]:
                lab[anon.get(cval, cval)] = {"W_eligible": int(Ws.elig.sum()), "sessions": int(Ws[Ws.elig].session_id.nunique()),
                                            "label": None}
                continue
            s_, l_ = label_under(unit, Ws, G[G.session_id.isin(ss)], ctx)
            lab[anon.get(cval, cval)] = {"recomputed": brief(s_), "label": l_}
        axes[axis] = lab
    conf = {}
    conf_checks = []
    for axis, lab in axes.items():
        c_ = E.confinement({k: v["label"] for k, v in lab.items()})
        conf[axis] = {"status": c_, "reportable": sum(1 for v in lab.values() if v["label"] in LEVEL),
                      "signal_bearing": sum(1 for v in lab.values() if v["label"] in LEVEL and LEVEL[v["label"]] >= 1)}
    confined_axes = [a for a, v in conf.items() if v["status"] == "CONFINED"]
    if confined_axes:
        conf_checks.append({"name": "CONFINED on " + ", ".join(confined_axes), "effect": "downgrade"})
    strata = {"axes": axes, "confinement": conf, "confined_axes": confined_axes,
              "reportable_rule": "stratum W eligible >= 100 pairs from >= 10 sessions (Probe 1 min n); tool axis: W "
                                 "restricted to the tool_key, G whole; other axes: W and G restricted to the stratum"}
    print(f"[{time.time() - t0:7.1f}s] {cand}: strata {conf}", flush=True)
    # ---------------------------------------------------------------- survival
    checks = checks_min + ac1_checks + ac4_checks + k1_checks + k2_checks + conf_checks
    status, final, reasons = E.survival_status(PHASE_B[cand], e_label, checks, has_e=has_e)
    # order sensitivity (min-type checks first is the order used; report the other order)
    alt = alt_order(PHASE_B[cand], e_label, checks_min, ac1_checks + ac4_checks + k1_checks + k2_checks + conf_checks,
                    has_e)
    out["artifact_checks"] = ac
    out["kill_tests"] = {"K1_control_composition": k1, "K2_floor_stability": k2, "K3_stamp_quality": k3}
    out["stratification"] = strata
    out["survival"] = {"phase_b_label": PHASE_B[cand], "E_label": e_label, "BuE_label": ref_full,
                       "checks_in_order": checks, "status": status, "final_label": final, "reasons": reasons,
                       "order_note": "min-type checks (AC2, AC3, AC5, K3: 'take the lower label') are applied first, "
                                     "then one-level downgrades and caps",
                       "final_label_other_order": alt}
    return out


# ================================================================================================ P3 candidate
def session_stats(P3, err_col="err"):
    g = P3.groupby("session_id")
    S = pd.DataFrame({"n_calls": g.size(), "n_err": g[err_col].sum(), "n_shell": g.is_shell.sum(),
                      "split": g.split.first()})
    return S


def z_eval(S, L=L75):
    long_ = S[S.n_calls >= L]
    n_long = int(len(long_))
    k0 = int((long_.n_err == 0).sum())
    z = p3.wil(k0, n_long)
    if n_long == 0:
        return {"L": L, "n_long": 0, "n_zero": 0, "Z": z, "verdict": "INSUFFICIENT_N", "rule_applied": "n_long 0"}
    v, why, _ = p3.verdict_zero(z, n_long)
    return {"L": int(L), "n_long": n_long, "n_zero": k0, "Z": z, "verdict": v, "rule_applied": why}


def run_p3(T, t0):
    cand = "P3zero/swechat/claude_code"
    P3 = T["P3"]
    out = {"candidate": cand, "unit": "swechat/claude_code", "phase_b_label": PHASE_B[cand], "has_E": True,
           "L75": L75, "L90": L90, "L_source": "prereg.json resolved.probe3.long_session.swechat/claude_code"}
    S_all = session_stats(P3)
    pops = {}
    for pop in ("B", "E", "BuE"):
        S = S_all if pop == "BuE" else S_all[S_all.split == pop]
        z = z_eval(S)
        p = float(S.n_err.sum() / S.n_calls.sum())
        zt = p3.zero_tail(S, L75, p)
        pops[pop] = {"sessions_with_paired_calls": int(len(S)), "paired_calls": int(S.n_calls.sum()),
                     "errors": int(S.n_err.sum()), "pooled_per_call_rate_p": p, "zero_tail_L75": z,
                     "E0": zt.get("E0"), "Z_over_E0": zt.get("Z_over_E0"),
                     "class_counts": {c: int(v) for c, v in sel(P3, pop).ecls.value_counts().items()}}
    out["populations"] = pops
    pb = json.load(open(ROOT / "analysis" / "out" / "probe_3.json", encoding="utf-8"))["units"]["swechat/claude_code"]
    out["reproduction_B_vs_phase_b"] = {
        "n_long": [pops["B"]["zero_tail_L75"]["n_long"], pb["zero_error_tail"]["L75"]["n_long"]],
        "n_zero": [pops["B"]["zero_tail_L75"]["n_zero"], pb["zero_error_tail"]["L75"]["n_zero"]],
        "paired_calls": [pops["B"]["paired_calls"], pb["paired_calls"]],
        "verdict": [pops["B"]["zero_tail_L75"]["verdict"], pb["verdict"]["zero_error_tail"]["verdict"]]}
    rp = out["reproduction_B_vs_phase_b"]
    rp["all_match"] = all(a == b for a, b in rp.values() if isinstance(a, (int, str)))
    print(f"[{time.time() - t0:7.1f}s] {cand}: B {pops['B']['zero_tail_L75']['n_zero']}/{pops['B']['zero_tail_L75']['n_long']} "
          f"E {pops['E']['zero_tail_L75']['n_zero']}/{pops['E']['zero_tail_L75']['n_long']} "
          f"BuE {pops['BuE']['zero_tail_L75']['n_zero']}/{pops['BuE']['zero_tail_L75']['n_long']}", flush=True)
    ref = pops["BuE"]["zero_tail_L75"]["verdict"]
    e_label = pops["E"]["zero_tail_L75"]["verdict"]
    running = e_label if e_label in LEVEL else PHASE_B[cand]
    checks_min, other = [], []
    ac = {}
    # AC2 truncation
    S2 = session_stats(P3[~P3.trunc])
    z2 = z_eval(S2)
    ac["AC2_truncation"] = {"dropped_pairs": int(P3.trunc.sum()), "zero_tail_L75": z2, "label": z2["verdict"],
                            "reference_label": ref}
    c, running = min_check("AC2_truncation", ref, z2["verdict"], running)
    ac["AC2_truncation"]["result"] = c["result"]
    checks_min.append(c)
    # AC3 join
    S3 = session_stats(P3[P3.jc])
    z3 = z_eval(S3)
    ac["AC3_join"] = {"dropped_pairs": int((~P3.jc).sum()), "copied_call_ids_in_pool": T["copied_call_ids"],
                      "zero_tail_L75": z3, "label": z3["verdict"], "reference_label": ref}
    c, running = min_check("AC3_join", ref, z3["verdict"], running)
    ac["AC3_join"]["result"] = c["result"]
    checks_min.append(c)
    # AC5 sampling
    sids_all = sorted(S_all.index.astype(str))
    wt = E.post_strat_weights("swechat", sids_all)
    long_ = S_all[S_all.n_calls >= L75]
    w = np.array([wt[s] for s in long_.index], dtype=float)
    zr = E.weighted_cluster_rate((long_.n_err == 0).astype(float).to_numpy(), np.ones(len(long_)), w)
    Zw, hiw = zr["rate"], zr["hi"]
    n_long = len(long_)
    l5 = ("ALIVE" if Zw <= 0.10 and hiw <= 0.20 and n_long >= 30 else "WEAK" if Zw <= 0.30 else "DEAD") \
        if n_long >= P3_K["min_long"] else "INSUFFICIENT_N"
    ac["AC5_sampling"] = {"weighted_Z": zr, "n_long": n_long, "label": l5, "reference_label": ref,
                          "rule": "probe3 verdict rule with the weighted share and its session-bootstrap hi in place of "
                                  "the Wilson hi"}
    c, running = min_check("AC5_sampling", ref, l5, running)
    ac["AC5_sampling"]["result"] = c["result"]
    checks_min.append(c)
    zB, zE = pops["B"]["zero_tail_L75"]["Z"], pops["E"]["zero_tail_L75"]["Z"]
    ac["AC5_sampling"]["SHIFT_B_vs_E"] = {"B_point": zB["share"], "E_wilson": [zE["lo"], zE["hi"]],
                                          "SHIFT": bool(not (zE["lo"] <= zB["share"] <= zE["hi"]))}
    # AC4 dominance over long sessions
    model_map = T["model"]
    frame = pd.DataFrame({"session_id": sorted(long_.index.astype(str))})
    maps = {"repo": norm_clusters(E.session_cluster_map("swechat", frame, "repo")),
            "user": norm_clusters(E.session_cluster_map("swechat", frame, "user")),
            "model": {s: model_map.get(s, "unknown") for s in frame.session_id},
            "session": {s: s for s in frame.session_id}}
    wmap = {s: 1 for s in frame.session_id}
    dom, leave = {}, []
    for kind, cmap in maps.items():
        d = E.dominance(wmap, cmap)
        order = [c for c, _, _ in d["top_clusters"]]
        anon = anon_rank(order, kind) if kind in ("repo", "user", "session") else {}
        ds = dom_summary(d, anon)
        isdom = ds["session_dominated"] if kind == "session" else ds["cluster_dominated"]
        ds["dominated_on_this_kind"] = bool(isdom)
        dom[kind] = ds
        if isdom:
            for c in order[:5]:
                drop = {s for s, cc in cmap.items() if cc == c}
                Sl = S_all[~S_all.index.isin(drop)]
                zl = z_eval(Sl)
                below = zl["n_long"] < P3_K["min_long"]
                leave.append({"kind": kind, "cluster": anon.get(c, c), "long_sessions_dropped": len(drop),
                              "zero_tail_L75": zl, "label": zl["verdict"], "below_min_n": bool(below),
                              "label_drop": bool(lvl(zl["verdict"]) is not None and lvl(zl["verdict"]) < lvl(ref))})
    drop_any = any(x["label_drop"] and not x["below_min_n"] for x in leave)
    below_any = any(x["below_min_n"] for x in leave)
    ac["AC4_dominance"] = {"denominator": "long sessions (n_calls >= L75), one event per session", "kinds": dom,
                           "dominated": any(v["dominated_on_this_kind"] for v in dom.values()), "leave_outs": leave,
                           "DOMINATED": bool(drop_any), "UNTESTABLE_WITHOUT_DOMINANT": bool(below_any),
                           "reference_label": ref}
    if drop_any:
        other.append({"name": "AC4_DOMINATED", "effect": "downgrade"})
    if below_any:
        other.append({"name": "AC4_UNTESTABLE_WITHOUT_DOMINANT", "effect": "cap_weak"})
    ac["AC4_dominance"]["result"] = ("DOMINATED" if drop_any else "UNTESTABLE_WITHOUT_DOMINANT" if below_any else
                                     "PASS" if ac["AC4_dominance"]["dominated"] else "NOT_DOMINATED")
    # AC1 parser: zero-error long sessions
    zl_ = S_all[(S_all.n_calls >= L75) & (S_all.n_err == 0)]
    ac["AC1_parser"] = audit_p3({(r.split, s): int(r.n_calls) for s, r in zl_.iterrows()}, T)
    if ac["AC1_parser"]["result"] == "FAIL":
        other.append({"name": "AC1_parser_FAIL", "effect": "downgrade"})
    print(f"[{time.time() - t0:7.1f}s] {cand}: AC1 {ac['AC1_parser']['result']} AC2 {z2['verdict']} AC3 {z3['verdict']} "
          f"AC4 {ac['AC4_dominance']['result']} AC5 {l5}", flush=True)
    # ---- kill tests (on B u E; E reported alongside)
    kt = {}
    k1 = {}
    for pop in ("BuE", "E"):
        S = S_all if pop == "BuE" else S_all[S_all.split == pop]
        Sk = S[S.n_shell >= P3_K["K1_min_shell"]]
        k1[pop] = z_eval(Sk)
    zk1 = k1["BuE"]["Z"]["share"]
    k1["result"] = ("KILL" if zk1 is not None and zk1 > P3_K["K1_kill"] else
                    "DOWNGRADE" if zk1 is not None and zk1 > P3_K["K1_down"] else "PASS")
    k1["decided_on"] = "BuE"
    if k1["result"] == "KILL":
        other.append({"name": "K1_error_capable_Z_gt_0.30", "effect": "kill"})
    elif k1["result"] == "DOWNGRADE":
        other.append({"name": "K1_error_capable_Z_gt_0.10", "effect": "downgrade"})
    kt["K1_error_capable"] = k1
    P3b = P3.assign(err2=P3.err.to_numpy(dtype=bool) & P3.ecls.isin(["cc_exit_code", "unmarked"]).to_numpy())
    k2 = {"primary_error_classes": {c: int(v) for c, v in P3[P3.err].ecls.value_counts().items()}}
    for pop in ("BuE", "E"):
        S = session_stats(sel(P3b, pop), err_col="err2")
        k2[pop] = z_eval(S)
    zk2 = k2["BuE"]["Z"]["share"]
    k2["result"] = "DOWNGRADE (friction is harness-validation-driven)" if zk2 is not None and zk2 > P3_K["K2_down"] else "PASS"
    k2["decided_on"] = "BuE"
    if zk2 is not None and zk2 > P3_K["K2_down"]:
        other.append({"name": "K2_harness_validation_Z_gt_0.10", "effect": "downgrade"})
    kt["K2_harness_validation"] = k2
    k3 = {}
    fired = []
    for axis in ("model", "repo"):
        cmap = maps[axis]
        groups = defaultdict(list)
        for s in frame.session_id:
            groups[cmap.get(s, "unknown")].append(s)
        ordered = sorted(groups, key=lambda c: -len(groups[c]))
        anon = anon_rank(ordered, axis) if axis == "repo" else {}
        rows = {}
        for cval in ordered:
            ss = set(groups[cval])
            S = S_all[S_all.index.isin(ss)]
            z = z_eval(S)
            share = len(ss) / len(frame)
            reportable = z["n_long"] >= P3_K["K3_min_long"]
            fires = bool(reportable and share >= P3_K["K3_share"] and z["Z"]["share"] > P3_K["K3_Z"])
            rows[anon.get(cval, cval)] = {"n_long": z["n_long"], "share_of_long": share, "Z": z["Z"],
                                          "reportable": bool(reportable), "fires": fires}
            if fires:
                fired.append(f"{axis}:{anon.get(cval, cval)}")
        k3[axis] = rows
    k3["fired"] = fired
    k3["result"] = "DOWNGRADE" if fired else "PASS"
    if fired:
        other.append({"name": "K3_strata " + ", ".join(fired), "effect": "downgrade"})
    kt["K3_strata"] = k3
    kt["K4_length_L90"] = {pop: z_eval(S_all if pop == "BuE" else S_all[S_all.split == pop], L=L90)
                           for pop in ("B", "E", "BuE")}
    kt["K4_length_L90"]["note"] = "reported only, no verdict effect; Phase B 0/224"
    print(f"[{time.time() - t0:7.1f}s] {cand}: K1 {k1['result']} K2 {k2['result']} K3 {k3['result']}", flush=True)
    # ---- stratification (model, repo; tool and length axes)
    axes = {}
    for axis in ("model", "repo"):
        lab = {}
        for name, row in k3[axis].items():
            lab[name] = {"n_long": row["n_long"], "Z": row["Z"],
                         "label": (p3.verdict_zero(row["Z"], row["n_long"])[0] if row["reportable"] else None)}
        axes[axis] = lab
    terc = E.length_tercile_map(S_all.n_calls.to_dict(), PJ["resolved"]["length_terciles_A"]["swechat/claude_code"]["cuts"])
    tl = Counter(terc[s] for s in long_.index)
    axes["length"] = {k: {"n_long": int(v), "label": None} for k, v in tl.items()}
    conf = {}
    for axis in ("model", "repo", "length"):
        c_ = E.confinement({k: v["label"] for k, v in axes[axis].items()})
        conf[axis] = {"status": c_, "reportable": sum(1 for v in axes[axis].values() if v["label"] in LEVEL)}
    conf["length"]["note"] = (f"every long session (n_calls >= L75 = {L75}) lies above the A upper tercile cut, so only "
                              "the 'long' stratum holds long sessions: axis UNTESTABLE by construction")
    conf["tool"] = {"status": "NOT_APPLICABLE", "note": "session-level statistic (zero errors over all of a session's "
                                                        "calls); a per-tool_key Z would be a different statistic"}
    confined = [a for a, v in conf.items() if v["status"] == "CONFINED"]
    if confined:
        other.append({"name": "CONFINED on " + ", ".join(confined), "effect": "downgrade"})
    checks = checks_min + other
    status, final, reasons = E.survival_status(PHASE_B[cand], e_label, checks, has_e=True)
    alt = alt_order(PHASE_B[cand], e_label, checks_min, other, True)
    out["artifact_checks"] = ac
    out["kill_tests"] = kt
    out["stratification"] = {"axes": axes, "confinement": conf, "confined_axes": confined,
                             "reportable_rule": f"stratum n_long >= {P3_K['min_long']} (probe3 min n)"}
    out["survival"] = {"phase_b_label": PHASE_B[cand], "E_label": e_label, "BuE_label": ref,
                       "checks_in_order": checks, "status": status, "final_label": final, "reasons": reasons,
                       "final_label_other_order": alt}
    return out


# ================================================================================================ main
DEVIATIONS = [
    {"item": "one script and one JSON for the four P1/P3 candidates",
     "prereg_said": "outputs.A1: phase_e_a1_<candidate>.py -> a1_<candidate>.json (P1, P2, P3zero, ...)",
     "what_you_did": "analysis/probes/phase_e_a1_p1_p3.py -> analysis/out/phase_e/a1_p1_p3.json, one block per candidate",
     "why": "the orchestrating task names the item key a1_p1_p3; the per-candidate content is unchanged",
     "effect_on_verdict": "none"},
    {"item": "artifact checks and strata recompute the separability statistic, not the change-point floor",
     "prereg_said": "AC2/AC3/AC5/AC4/strata: recompute the statistic and apply the candidate's rule; the Probe 1 rule "
                    "includes the floor-step and floor-transfer downgrades",
     "what_you_did": "each check recomputes fp_share and AUC on its population and applies the Probe 1 verdict rule "
                     "(probe_1.unit_verdict) with the A1 recheck, FLAT, floor-step and floor-transfer components carried "
                     "from the B u E computation; floor stability itself is tested by K2 on B u E and on E",
     "why": "the change-point permutation test per subset (up to ~60 subsets) is the expensive part and the checks "
            "target the separability statistic; K2 is the pre-registered floor test",
     "effect_on_verdict": "none on the direction of any check: a carried UNSTABLE floor can only hold a check label at "
                          "or below WEAK, identically for the reference and the check"},
    {"item": "K2 applied as the Phase B floor rule, never twice",
     "prereg_said": "K2: Phase B change-point rule on B u E and on E; UNSTABLE -> one-level downgrade (Phase B rule)",
     "what_you_did": "the E verdict is the unchanged Probe 1 rule on E, which already turns ALIVE into WEAK when E's floor "
                     "is UNSTABLE. K2 adds a downgrade only when B u E or E is UNSTABLE (>= 30 series from >= 5 s), the "
                     "verdict being judged is ALIVE and that downgrade has not already been applied",
     "why": "'(Phase B rule)' is the ALIVE -> WEAK floor rule; applying it again to a label it already lowered would "
            "count the same evidence twice",
     "effect_on_verdict": "see kill_tests.K2_floor_stability.result per candidate; under a literal double application a "
                          "candidate whose E verdict was already floor-downgraded would drop one more level"},
    {"item": "order of 'take the lower label' checks and one-level downgrades",
     "prereg_said": "AC2, AC3, AC5, P1-K3: FAIL -> take the lower label; AC4, confinement, kill tests: one-level "
                    "downgrade or cap; order not stated",
     "what_you_did": "min-type checks first (relative to the E label), then downgrades and caps, passed to "
                     "survival_status() in that order; survival.final_label_other_order gives the label with the "
                     "downgrades first",
     "why": "this order gives the lower (conservative) label when both kinds fire",
     "effect_on_verdict": "none unless a min-type check FAILs (see survival.checks_in_order)"},
    {"item": "AC3 copy rule",
     "prereg_said": "join_clean_mask: the call_id does not occur in another session (re-stamped resume/fork copies)",
     "what_you_did": "the 'another session' set is the pooled B u E sessions of the unit (B only for cc_local); "
                     "synthetic call ids (loader-made 'synthetic:<format>:<seq>', unique only within a session) are "
                     "excluded from the copy test",
     "why": "H may not be read and A is not allowed here; a synthetic id is not a call id and would mark every OpenCode "
            "pair with a redacted id as a copy",
     "effect_on_verdict": "copies shared with A or H sessions are not detected (limitation)"},
    {"item": "AC4 denominator for Probe 1",
     "prereg_said": "dominated if one cluster holds > 0.25 of the statistic's denominator events (or contributing "
                    "sessions), or one session > 0.10",
     "what_you_did": "tested on the eligible W pairs (fp_share denominator) and separately on the eligible G pairs "
                     "(AUC control); a kind is dominated if either is; each leave-out removes the cluster's sessions from "
                     "both W and G. A leave-out with W or G below the Probe 1 min n is UNTESTABLE_WITHOUT_DOMINANT",
     "why": "the Probe 1 statistic has two populations; testing both can only add checks",
     "effect_on_verdict": "conservative; see artifact_checks.AC4_dominance"},
    {"item": "missing repo_id / user_id in AC4 and the strata",
     "prereg_said": "clusters: repo (sessions.parquet repo_id), user (sessions.parquet user_id)",
     "what_you_did": "sessions whose repo_id / user_id is null form one cluster labelled 'unknown' (E.dominance already "
                     "grouped them together); it is ranked, tested and left out like any other cluster",
     "why": "651 of the 2,000 B sessions have a null user_id; leaving them unassigned would hide a dominant pseudo-cluster",
     "effect_on_verdict": "see artifact_checks.AC4_dominance.leave_outs (the 'unknown' user cluster is a pseudo-cluster, "
                          "not one person)"},
    {"item": "AC5 for the AUC",
     "prereg_said": "post-stratified ratio estimator sum(w num)/sum(w den) with the session bootstrap",
     "what_you_did": "fp_share: weighted_cluster_rate as written; AUC: pair weights = product of session weights, the "
                     "same session draws as probe_1.auc_ci (multiplicities); the unweighted control of the same function "
                     "is reported next to it",
     "why": "the prereg states the estimator for rates only; this is the AUC analogue",
     "effect_on_verdict": "none expected; see artifact_checks.AC5_sampling"},
    {"item": "AC1 lookup for OpenCode pairs with redacted call ids",
     "prereg_said": "each event is looked up in the raw source by (session_id, uuid or call_id)",
     "what_you_did": "pairs whose raw callID was redacted ('REDACTED', IR id synthetic:opencode:<seq>) are located by "
                     "their ordinal among the session's tool parts (the loader emits one call per tool part in order); "
                     "located_by counts both kinds",
     "why": "the release redacted those ids; no other key exists",
     "effect_on_verdict": "none if every audited pair is found (see AC1_parser.found)"},
    {"item": "K1 step 2 session drop",
     "prereg_said": "recompute AUC ... after dropping the single session with most G pairs",
     "what_you_did": "step 1 restricts G to subagent/webfetch/websearch; step 2 additionally removes the session with the "
                     "most eligible restricted-G pairs from both W and G; AUC DEAD at either step -> kill, G below "
                     "30 pairs from 5 s at either step -> cap WEAK",
     "why": "'Then drop the session' (PREREG_E.md 1.3) reads as sequential; a session is dropped whole",
     "effect_on_verdict": "see kill_tests.K1_control_composition"},
    {"item": "AC1 FAIL effect",
     "prereg_said": "FAIL if >= 2 of 30 differ; survival: SURVIVES needs every artifact check to pass",
     "what_you_did": "an AC1 FAIL is a one-level downgrade",
     "why": "the prereg names no other effect for AC1",
     "effect_on_verdict": "none unless AC1 FAILs"},
    {"item": "P1 stratification, tool axis",
     "prereg_said": "stratify by tool_key",
     "what_you_did": "W restricted to one tool_key per stratum, G (the generation-bound control, other tools by "
                     "construction) kept whole",
     "why": "G has no tool_key in common with W",
     "effect_on_verdict": "none unless CONFINED on the tool axis"},
    {"item": "P3 stratification, tool and length axes",
     "prereg_said": "stratify by tool, model, repo, length tercile",
     "what_you_did": "model and repo axes computed; tool axis NOT_APPLICABLE (session-level statistic); length axis "
                     "UNTESTABLE (all long sessions sit in the top A tercile by construction)",
     "why": "see stratification.confinement",
     "effect_on_verdict": "none"},
    {"item": "P3 kill tests population",
     "prereg_said": "K1-K3 thresholds; every second-pass statistic runs on B u E",
     "what_you_did": "K1-K3 decided on B u E; K1/K2 on E reported alongside",
     "why": "splits.re_measurement_population",
     "effect_on_verdict": "none unless the E value would cross a threshold that B u E does not (see kill_tests)"},
    {"item": "P3 AC5 interval",
     "prereg_said": "probe3 verdict: Wilson hi <= 0.20 for ALIVE",
     "what_you_did": "the weighted share uses the session-bootstrap hi of weighted_cluster_rate in place of the Wilson hi",
     "why": "a Wilson interval has no weighted form here",
     "effect_on_verdict": "none unless the weighted hi crosses 0.20"},
]


def main(argv=()):
    """argv: optional unit subset for a debug run; output then goes to env A1_DEBUG_OUT, official output untouched."""
    only = set(argv) or None
    t0 = time.time()
    pr_b_sha = p1.sha256(p1.PREREG_PATH)
    pre = {"prereg_e_json_sha256": E.sha256_file(E.PREREG_E_JSON),
           "spec_module_sha256_lf": E.sha256_lf(ROOT / "analysis" / "probes" / "prereg_e_common.py"),
           "spec_module_sha256_lf_prereg": PJ["provenance"]["spec_module_sha256_lf"],
           "check_frozen": "passed",
           "phase_b_prereg_json_sha256": pr_b_sha,
           "phase_b_spec_module_sha_ok": p1.sha256(p1.SPEC_PATH) == PR["provenance"]["spec_module_sha256"],
           "phase_b_calibration_sha_ok": p1.sha256(p1.CALIB_PATH) == PR["provenance"]["calibration_script_sha256"]}
    if not (pre["phase_b_spec_module_sha_ok"] and pre["phase_b_calibration_sha_ok"]):
        raise SystemExit("Phase B module sha mismatch: stop")
    p1.check_thresholds_against_text()
    p3.PRE = json.load(open(p1.PREREG_PATH, encoding="utf-8"))
    result = {"item": "a1_p1_p3", "script": "analysis/probes/phase_e_a1_p1_p3.py",
              "run_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "prereg": pre,
              "population_rule": "B u E pooled for every second-pass statistic and check; E alone for the replication "
                                 "verdict; cc_local B only (UNREPLICATED)",
              "thresholds_used": {"probe1": TH, "probe3": {"L75": L75, "L90": L90, **P3_K},
                                  "dominance": {"cluster_share": E.DOM_SHARE, "session_share": E.DOM_SESSION},
                                  "audit": {"k": E.AUDIT_K, "fail_at": E.AUDIT_FAIL},
                                  "length_terciles_A": {u: PJ["resolved"]["length_terciles_A"][u]["cuts"]
                                                        for u in UNITS_P1}},
              "inputs_sha256": {}, "candidates": {}, "deviations": DEVIATIONS}
    for f in ("swechat_B", "swechat_E", "cc_local_B", "swechat_population"):
        result["inputs_sha256"][f"analysis/cache/{f}.parquet"] = E.sha256_file(E.CACHE / f"{f}.parquet")
    for unit in UNITS_P1:
        if only and unit not in only:
            continue
        parts = []
        splits = ["B"] if unit == "cc_local" else ["B", "E"]
        for sp in splits:
            u = load(unit, sp)
            print(f"[{time.time() - t0:7.1f}s] loaded {unit} {sp}: {len(u)} rows, {u.session_id.nunique()} sessions",
                  flush=True)
            parts.append(extract(unit, u, sp))
            del u
        T = pool(parts)
        extraction = {sp: p["counts"] | {"G_excluded": p["gexcl"]} for sp, p in zip(splits, parts)}
        r = run_p1(unit, T, t0)
        r["extraction"] = extraction
        result["candidates"][f"P1/{unit}"] = r
        if unit == "swechat/claude_code":
            # P3 session-table reproduction against probe_3.session_table on B
            refB = parts[0]["P3_session_table_ref"]
            mine = session_stats(T["P3"][T["P3"].split == "B"])
            same = bool((refB.n_calls.sort_index().to_numpy() == mine.n_calls.sort_index().to_numpy()).all()
                        and (refB.n_err.sort_index().to_numpy() == mine.n_err.sort_index().to_numpy()).all())
            r3 = run_p3(T, t0)
            r3["session_table_matches_probe_3_session_table_B"] = same
            result["candidates"]["P3zero/swechat/claude_code"] = r3
        del parts, T
    verdicts, cells = {}, 0
    for cname, c in result["candidates"].items():
        s = c["survival"]
        if cname.startswith("P1/"):
            pop = "E" if c["has_E"] else "B"
            sp = c["populations"][pop]["separability"]
            dn = {"E_or_B_verdict": c["populations"][pop]["verdict"]["verdict"],
                  "fp_share": {k: sp["fp_share"].get(k) for k in ("num", "den", "rate", "lo", "verdict_hi", "n_sessions")},
                  "auc": {k: sp["auc"].get(k) for k in ("auc", "lo", "hi", "n_G", "n_W")},
                  "G_eligible": sp["G_eligible"]}
            path = f"candidates['{cname}'].populations.{pop}.separability; .survival"
        else:
            dn = {"E_verdict": c["populations"]["E"]["zero_tail_L75"]["verdict"],
                  "Z_E": c["populations"]["E"]["zero_tail_L75"]["Z"],
                  "Z_BuE": c["populations"]["BuE"]["zero_tail_L75"]["Z"]}
            path = f"candidates['{cname}'].populations.E.zero_tail_L75; .survival"
        verdicts[cname] = {"status": s["status"], "final_label": s["final_label"], "phase_b": s["phase_b_label"],
                           "E_label": s["E_label"], "BuE_label": s["BuE_label"], "reasons": s["reasons"],
                           "deciding": dn, "json_path": path}
        cells += 1
    result["verdicts"] = verdicts
    result["verdict_cells_computed"] = {"survival_statuses": cells, "multiplicity": PJ["global"]["multiplicity"]}
    result["runtime_s"] = round(time.time() - t0, 1)
    txt = json.dumps(clean(result), indent=1, allow_nan=False, ensure_ascii=False)
    out_path = OUT
    if only:
        out_path = Path(os.environ["A1_DEBUG_OUT"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(txt, encoding="utf-8")
    print(f"done in {result['runtime_s']}s -> {out_path}")
    for k, v in verdicts.items():
        print(f"  {k:30s} {v['status']:40s} final {v['final_label']}  reasons {v['reasons']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
