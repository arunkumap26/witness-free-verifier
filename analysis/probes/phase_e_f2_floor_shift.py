"""Phase E, Track A, follow-up F2: the swechat/claude_code latency-floor shifts.  Item key: f2_floor_shift.

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_f2_floor_shift

Pre-registration (the law): analysis/PREREG_E.md section 1.6, analysis/prereg_e.json `followups.F2_floor_shift` and
`covariate_definitions`, analysis/probes/prereg_e_common.py (raw_cc_entries, js_distance, compromise_signature, rng_for,
read_cache, split_ids), committed in 55fc556. check_frozen() runs before anything else. Every F2 threshold is asserted
against the prereg_e.json text at start-up; nothing is tuned here.

Order of work
  1. Step series (Phase B rule, code path of probe_1.probe1_unit section 5, reused verbatim): qualified pairs of the
     no-human-wait filter (prereg_calibration.p1_qualified) with delta > 0, per session x tool_key in seq order, n >= 40,
     x = log10(delta_s), prereg_common.change_point(m=20, n_perm=199, seed=SEED + i) with i the index of the series in
     sorted (session_id, tool_key) order of the population passed in; step = p <= 0.01 and D* >= log10 2.
       - B alone: must reproduce Phase B (21 of 156 series, 18 of 114 sessions; references.floor_steps_B).
       - E alone: the replication, labelled STABLE / UNSTABLE by the Phase B 0.10 rule.
       - F2 population (B u E) = B steps + E steps, each from its own run (see DEVIATIONS: seed indexing).
       - Sensitivity: the same rule on the pooled B u E series list (pooled index i), as phase_e_a1_p1_p3 K2 ran it.
  2. Controls: every non-step eligible series gets one split point k uniform on [20, n - 20]
     (rng_for('F2', session_id, tool_key)).
  3. Covariates at k* (step series) and at k (controls). The window is W = 5 series calls on each side of the split
     (Phase C changepoints window_bounds convention): seq range [anchor(k - 5), anchor(k + 4)], anchors = the series'
     call seqs; the pre-step half is [anchor(k - 5), anchor(k)), the post-step half [anchor(k), anchor(k + 4)].
     Calls = all tool calls of the session (main and subagent threads), deduplicated as prereg_common.make_pairs.
       harness_events        any of the 15 covariate_definitions.harness_types (phase_c_changepoints.harness_events on
                             the main thread, raw uuid scan as Phase C) with seq in the window; per type reported too
       version_change        raw entry `version` (raw_cc_entries) changes value inside the window's time span
       cwd_or_branch_change  raw entry cwd or gitBranch changes value inside the window's time span
       permission_mode_change raw entry permissionMode changes value inside the window's time span
       idle_gap              a wall-clock gap >= 300 s between consecutive events (all IR rows) in the window
       hook_rate_change      |share of calls with a linked hook_progress event, post half - pre half| >= 0.5
       tool_mix_shift        js_distance(tool_key counts of the 20 calls before the step call, of the step call and
                             the 19 after) >= 0.3
       parallelism_change    |share of calls that are not the last call of their API message, post - pre| >= 0.3
       result_size_shift     |log10(median result bytes of the 5 series points after / the 5 before)| >= log10 2
       subagent_in_flight    a subagent|workflow call (paired) has call ts <= step-call ts <= result ts
       workspace_change      prereg_common.workspace_root of the absolute read paths (ACCESS_READ keys) of the pre and
                             of the post half are both found and differ
  4. Credited covariate: rate at k* - control rate >= 0.25 and present in >= 3 step series (per population).
     Compromise signature: prereg_e_common.compromise_signature(latency, result chars, k*, G90) with G90 of
     swechat/claude_code from prereg.json resolved.probe1.generation_rate.
     Classes: BENIGN (>= 1 credited covariate present), COMPROMISE_LIKE (signature met, no credited covariate),
     UNEXPLAINED (neither). Outcome: DISMISSIBLE_AS_BENIGN if BENIGN >= 0.8 of step series and COMPROMISE_LIKE = 0,
     else OPEN. No verdict moves either way (no_rescue).
  5. Minimum n (prereg_e.json global.min_n -> prereg.json global.min_n): every rate needs a denominator >= 30 from
     >= 5 sessions, every quantile its quantile_reportable minimum. Below that: raw k/n (or n) and the label
     'insufficient n'; no rate, no CI, no verdict. A population whose step side (or control side) is below the rate
     minimum gets no credit test, no own classes and the outcome INSUFFICIENT_N (B: 21 step series; E: 10). The
     earlier, ungated values are kept under `corrections` (before / after / reason).

Populations reported separately: B, E (replication) and B u E (the prereg population, primary), plus the pooled-index
sensitivity. Post-hoc descriptive blocks are labelled "post hoc, not a verdict".

Reads: analysis/cache/swechat_{B,E}.parquet through prereg_e_common.read_cache (claude_code sessions of B and E only),
analysis/cache/swechat_population.parquet (format), swe-chat-pinned transcripts (raw entry fields, read-only) for the
eligible-series sessions of B and E only. Never reads *_A.parquet, the H ids, or anything of the local Qwen swarm.
Writes RAW NUMBERS ONLY to analysis/out/phase_e/f2_floor_shift.json. Interpretation: analysis/notes/phase_e_f2_floor_shift.md.
"""
from analysis.probes import prereg_e_common as E

PJ = E.check_frozen()  # first: the module must be the pre-registered one (stops with AssertionError otherwise)

import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pyarrow as pa  # noqa: E402

from analysis.lib import stats  # noqa: E402
from analysis.probes import phase_c_changepoints as cp  # noqa: E402
from analysis.probes import prereg_calibration as cal  # noqa: E402
from analysis.probes import prereg_common as pc  # noqa: E402
from analysis.probes import probe_1 as p1  # noqa: E402

ROOT = E.ROOT
OUT = E.OUT_E / "f2_floor_shift.json"
UNIT = "swechat/claude_code"
PR = p1.PR                       # analysis/prereg.json (Phase B)
TH = p1.TH                       # Phase B Probe 1 thresholds (asserted against prereg.json text by probe_1)
F2 = PJ["followups"]["F2_floor_shift"]
COV = F2["covariates"]
G90 = float(PR["resolved"]["probe1"]["generation_rate"][UNIT]["G90"])
FM = pc.swechat_formats()

# F2 thresholds. Each is asserted against the prereg_e.json text in check_f2_text() so that a value here cannot drift.
T2 = {"W": 5, "idle_gap_s": 300.0, "hook_share": 0.5, "js_calls": 20, "js_distance": 0.3, "parallel_share": 0.3,
      "size_log10": math.log10(2), "ctrl_lo": 20, "credit_diff": 0.25, "credit_min_series": 3,
      "sig_post_rho": 0.5, "sig_pre_rho": 0.2, "sig_n_post": 20, "sig_post_r": 0.1, "benign_share": 0.8,
      "tokens_per_char": 0.25}
COVARIATES = ["harness_events", "version_change", "cwd_or_branch_change", "permission_mode_change", "idle_gap",
              "hook_rate_change", "tool_mix_shift", "parallelism_change", "result_size_shift", "subagent_in_flight",
              "workspace_change"]
SUBAGENT_KEYS = {"subagent", "workflow"}  # covariate_definitions / Phase C subagent_start: tool subagent|workflow
LCOLS = ["session_id", "seq", "kind", "ts", "tool", "tool_raw", "call_id", "text", "extra", "api_msg_id",
         "is_subagent", "agent_id", "parent_call_id", "stratum"]
KINDS = ["call", "result", "meta", "system", "user"]  # as probe_1 / phase_e_a1_p1_p3 (reproduces the Phase B pairs)
P2COLS = sorted(set(cp.BASE_COLS + ["text", "args", "tool_raw", "parent_call_id"]))
MINN = PR["global"]["min_n"]["rate_reportable"]  # den >= 30 from >= 5 sessions (prereg_e.json global.min_n)
INSUFF = "insufficient n"


def check_f2_text():
    assert list(COV) == COVARIATES, list(COV)
    assert COV["harness_events"].startswith("events of phase_c_changepoints.HARNESS_TYPES") and "W = 5 calls" in COV["harness_events"]
    assert ">= 300 s" in COV["idle_gap"]
    assert ">= 0.5" in COV["hook_rate_change"] and "hook_progress" in COV["hook_rate_change"]
    assert ">= 0.3" in COV["tool_mix_shift"] and "20 calls before and after k*" in COV["tool_mix_shift"]
    assert ">= 0.3" in COV["parallelism_change"]
    assert ">= log10 2" in COV["result_size_shift"]
    assert "in flight at the step call's stamp" in COV["subagent_in_flight"]
    assert "pc.workspace_root" in COV["workspace_change"]
    assert "[20, n-20]" in F2["control"] and "rng_for('F2', session, tool_key)" in F2["control"]
    assert ">= 0.25" in F2["credited_covariate"] and ">= 3 step series" in F2["credited_covariate"]
    s = F2["compromise_signature"]
    assert ">= 0.5" in s and "n_post >= 20" in s and "<= 0.2" in s and ">= 0.1" in s and "G90" in s
    assert "BENIGN share >= 0.8" in F2["outcome_rule"] and "COMPROMISE_LIKE = 0" in F2["outcome_rule"]
    assert "p <= 0.01 and D* >= log10 2" in F2["replication"] and "0.10 rule" in F2["replication"]
    assert PJ["covariate_definitions"]["harness_types"] == cp.HARNESS_TYPES
    assert TH["step_m"] == 20 and TH["step_n_perm"] == 199 and TH["step_share_unstable"] == 0.10
    assert abs(TH["tokens_per_char"] - T2["tokens_per_char"]) < 1e-12
    assert PJ["global"]["min_n"].startswith("as prereg.json global.min_n (rate >= 30 from >= 5 sessions")
    assert MINN["den_min"] == 30 and MINN["sessions_min"] == 5
    assert PR["global"]["min_n"]["below_min"].startswith("report raw k/n (or n) and the label 'insufficient n'")


def clean(o):
    return p1.clean(o)


def wil(k, n):
    p, lo, hi = stats.wilson(int(k), int(n))
    return {"k": int(k), "n": int(n), "p": p, "lo": lo, "hi": hi}


def rate_ok(n, ns):
    """global.min_n.rate_reportable: denominator >= 30 from >= 5 sessions."""
    return int(n) >= MINN["den_min"] and int(ns) >= MINN["sessions_min"]


def rate_cell(k, n, ns):
    """Wilson share when reportable; otherwise raw k/n with the label 'insufficient n' (no rate, no CI)."""
    if rate_ok(n, ns):
        return {**wil(k, n), "sessions": int(ns)}
    return {"k": int(k), "n": int(n), "sessions": int(ns), "label": INSUFF}


def describe_gated(values, ns):
    """stats.describe with each quantile withheld below global.min_n.quantile_reportable (probe_1.reportable; min, max
    and mean always reported, as probe_1 does)."""
    d = stats.describe(values)
    for q in ("p1", "p5", "p25", "p50", "p75", "p95", "p99"):
        if q in d and not p1.reportable(d["n"], int(ns), q):
            d[q] = {"label": INSUFF}
    d["sessions"] = int(ns)
    return d


# ================================================================================================ 1. step series
def unit_ids(split):
    return [s for s in E.split_ids("swechat", split) if FM.get(s) == "claude_code"]


def load_pass1(split):
    ids = unit_ids(split)
    df = E.read_cache("swechat", split, LCOLS, filters=[("session_id", "in", ids), ("kind", "in", KINDS)])
    df = df.reset_index(drop=True)
    df.loc[df.kind != "result", "text"] = None  # Probe 1 uses result text only (as probe_1.main)
    return df


def qualified_pairs(u):
    """probe_1.probe1_unit sections 2 and 5 inputs: qualified pairs with positive delta (Q), Phase B code path."""
    P = pc.make_pairs(u[u.kind.isin(["call", "result"])])
    P = cal.p1_qualified(UNIT, u, P)
    txt = P.text_r.astype(object)
    P["chars_r"] = [len(t) if isinstance(t, str) else 0 for t in txt]
    P["bytes_r"] = [len(t.encode("utf-8")) if isinstance(t, str) else 0 for t in txt]
    Qall = P[P.qualified]
    Q = Qall[Qall.delta_s > 0]
    Q = Q[["session_id", "call_id", "key", "seq", "ts", "ts_r", "delta_s", "chars_r", "bytes_r", "is_subagent"]].copy()
    Q["call_id"] = Q.call_id.astype(str)
    return Q, {"pairs": int(len(P)), "qualified": int(len(Qall)), "qualified_positive": int(len(Q)),
               "sessions_in_frame": int(u.session_id.nunique())}


def build_series(Q, split_of):
    """probe_1 section 5, verbatim selection and order: series per (session, tool_key) with n >= 2m, sorted."""
    series = []
    Qs = Q.sort_values(["session_id", "seq"])
    for (s, k), g in Qs.groupby(["session_id", "key"], sort=True):
        if len(g) >= 2 * TH["step_m"]:
            series.append({"session_id": s, "tool_key": k, "split": split_of[s],
                           "seq": g.seq.to_numpy(dtype=np.int64), "call_id": g.call_id.to_numpy(dtype=object),
                           "ts": g.ts.astype(object).to_numpy(), "delta": g.delta_s.to_numpy(dtype=float),
                           "chars": g.chars_r.to_numpy(dtype=float), "bytes": g.bytes_r.to_numpy(dtype=float),
                           "is_sub": g.is_subagent.fillna(False).astype(bool).to_numpy()})
    series.sort(key=lambda r: (r["session_id"], r["tool_key"]))
    return series


def run_change_points(series):
    """prereg_common.change_point with seed SEED + i over the list as passed (sorted (session, tool_key))."""
    out = []
    for i, r in enumerate(series):
        x = np.log10(r["delta"])
        c = pc.change_point(x, m=TH["step_m"], n_perm=TH["step_n_perm"], seed=stats.SEED + i)
        left, right = float(np.quantile(x[:c["k"]], 0.10)), float(np.quantile(x[c["k"]:], 0.10))
        out.append({"n": c["n"], "k": c["k"], "D_log10": c["D"], "factor": 10 ** c["D"], "p": c["p"], "step": c["step"],
                    "direction": c["direction"], "Q10_left_s": 10 ** left, "Q10_right_s": 10 ** right})
    return out


def step_summary(series, cps):
    n_el = len(series)
    n_st = int(sum(c["step"] for c in cps))
    sess = {r["session_id"] for r in series}
    sc = {"eligible_series": n_el, "steps": n_st, "eligible_sessions": len(sess),
          "sessions_with_step": len({r["session_id"] for r, c in zip(series, cps) if c["step"]})}
    if n_el and not rate_ok(n_el, len(sess)):
        # global.min_n (and A1 K2: < 30 series or < 5 sessions -> 'floor untested'): raw k/n only
        sc["step_share_wilson"] = rate_cell(n_st, n_el, len(sess))
        sc["label"] = "INSUFFICIENT_N"
        sc["steps_by_direction"] = dict(Counter(c["direction"] for c in cps if c["step"]))
    elif n_el:
        sc["step_share_wilson"] = wil(n_st, n_el)
        num, den = Counter(), Counter()
        for r, c in zip(series, cps):
            den[r["session_id"]] += 1
            num[r["session_id"]] += int(c["step"])
        ks = sorted(den)
        sc["step_share_cluster_rate_over_sessions"] = stats.cluster_rate([num[x] for x in ks], [den[x] for x in ks])
        sc["label"] = "STABLE" if n_st / n_el <= TH["step_share_unstable"] else "UNSTABLE"
        sc["steps_by_direction"] = dict(Counter(c["direction"] for c in cps if c["step"]))
        sc["by_tool"] = {k: {"eligible": sum(1 for r in series if r["tool_key"] == k),
                             "steps": sum(1 for r, c in zip(series, cps) if r["tool_key"] == k and c["step"])}
                         for k in sorted({r["tool_key"] for r in series})}
    else:
        sc["label"] = "NO_ELIGIBLE_SERIES"
    return sc


# ================================================================================================ 2. session context
def load_pass2(split, sids):
    df = E.read_cache("swechat", split, P2COLS, filters=[("session_id", "in", sorted(sids))])
    return df.reset_index(drop=True)


def session_contexts(df):
    """Per session: harness events, call table, all-row stamps, raw-field timelines. df = all rows of the sessions."""
    tbl = pa.Table.from_pandas(df, preserve_index=False)
    pdf = cp.prepare(tbl, "swechat", FM)  # Phase C frame: tms, xd, prefix, marker (+ BASE_COLS without ts / extra)
    pdf["args"] = df["args"].to_numpy(dtype=object)
    pdf["tool_raw"] = df["tool_raw"].to_numpy(dtype=object)
    pdf["parent_call_id"] = df["parent_call_id"].to_numpy(dtype=object)
    del tbl
    ctx, scan = {}, Counter()
    for sid, g_all in pdf.groupby("session_id", sort=True):
        g_all = g_all.sort_values("seq")
        # ---- harness events: Phase C build_session main-thread rule + harness_events with the raw uuid scan
        calls_all = g_all["kind"].to_numpy() == "call"
        main_mask = ~g_all["is_subagent"].to_numpy()
        if (calls_all & main_mask).sum() == 0 and calls_all.sum() > 0:
            main_mask = np.ones(len(g_all), bool)
        m = cp.scan_cc_file(str(E.SWE_TRANSCRIPTS / f"{sid}.jsonl"))
        if m is None:
            scan["transcript_missing"] += 1
            raw_uuid = None
        else:
            scan["transcript_scanned"] += 1
            raw_uuid = {k: v[:3] for k, v in m.items()}
        ev = cp.harness_events(g_all[main_mask], "swechat", "claude_code", raw_uuid)
        ev = [(s, t) for s, t in ev if t in cp.HARNESS_TYPES]
        # ---- call table (make_pairs dedup: first row per call_id by seq)
        calls = g_all[g_all.kind == "call"].drop_duplicates(["call_id"], keep="first")
        res = g_all[(g_all.kind == "result") & g_all.call_id.notna()].drop_duplicates(["call_id"], keep="first")
        rtms = dict(zip(res.call_id.astype(str), res.tms))
        keys = [pc.tool_key(UNIT, t, tr) for t, tr in zip(calls.tool.astype(object), calls.tool_raw.astype(object))]
        msg = [a if isinstance(a, str) else f"__solo__{c}" for a, c in zip(calls.api_msg_id.astype(object),
                                                                           calls.call_id.astype(str))]
        last = ~pd.Series(msg).duplicated(keep="last").to_numpy()  # cal.p1_qualified rule 3 (per session)
        meta = g_all[(g_all.kind == "meta") & g_all.parent_call_id.notna()]
        hooked = {str(p) for p, x in zip(meta.parent_call_id.astype(object), meta.xd) if x.get("type") == "hook_progress"}
        cid = calls.call_id.astype(str).to_numpy()
        paths = []
        for k, a, tr in zip(keys, calls.args.astype(object), calls.tool_raw.astype(object)):
            if k in cal.ACCESS_READ:
                obj = pc.jl(a) if isinstance(a, str) else {}
                paths.append([p for p, _ in pc.structured_paths(obj, tr) if pc.is_absolute(p)])
            else:
                paths.append([])
        ct = pd.DataFrame({"seq": calls.seq.to_numpy(dtype=np.int64), "tms": calls.tms.to_numpy(dtype=float),
                           "call_id": cid, "key": keys, "last": last, "hooked": [c in hooked for c in cid],
                           "rtms": [rtms.get(c, np.nan) for c in cid], "paths": paths}).sort_values("seq")
        ct = ct.reset_index(drop=True)
        # ---- raw field timelines (raw_cc_entries: timestamp, version, sessionId, cwd, gitBranch, permissionMode, type)
        ents = E.raw_cc_entries(sid)
        if ents:
            tms = cp._to_ms(pd.Series([e[0] for e in ents], dtype=object))
            order = np.argsort(np.where(np.isfinite(tms), tms, np.inf), kind="stable")
            tl = {}
            for name, idx in (("version", 1), ("cwd", 3), ("gitBranch", 4), ("permissionMode", 5)):
                vals = [(tms[i], ents[i][idx]) for i in order if np.isfinite(tms[i]) and isinstance(ents[i][idx], str)
                        and ents[i][idx]]
                tl[name] = vals
            scan["raw_entries_sessions"] += 1
        else:
            tl = None
            scan["raw_entries_missing"] += 1
        ev_seq = defaultdict(list)
        for s, t in ev:
            ev_seq[t].append(int(s))
        ctx[sid] = {"events": {t: np.array(sorted(v), dtype=np.int64) for t, v in ev_seq.items()},
                    "calls": ct, "row_seq": g_all.seq.to_numpy(dtype=np.int64), "row_tms": g_all.tms.to_numpy(dtype=float),
                    "timelines": tl}
    return ctx, dict(scan)


# ================================================================================================ 3. covariates
def changes_in_span(tl, t_lo, t_hi):
    """True if the value in effect changes at an entry stamped in (t_lo, t_hi] (consecutive non-null values differ);
    None if the field never appears."""
    if not tl:
        return None
    prev = None
    for t, v in tl:
        if prev is not None and v != prev and t_lo < t <= t_hi:
            return True
        prev = v
    return False


def covariates_at(c, r, k):
    """Covariate vector of series r at split index k (k = first post-split point). c = session context."""
    a = r["seq"]
    n = len(a)
    W = T2["W"]
    lo_s, st_s, hi_s = int(a[max(0, k - W)]), int(a[k]), int(a[min(n - 1, k + W - 1)])
    ct = c["calls"]
    cseq = ct.seq.to_numpy()
    ctms = ct.tms.to_numpy()
    pos = {int(s): i for i, s in enumerate(cseq)}
    i_lo, i_st, i_hi = pos[lo_s], pos[st_s], pos[hi_s]
    t_lo, t_st, t_hi = ctms[i_lo], ctms[i_st], ctms[i_hi]
    pre = ct.iloc[i_lo:i_st]
    post = ct.iloc[i_st:i_hi + 1]
    out, aux = {}, {}
    # harness events in the seq window [lo, hi]
    per_type = {}
    for t in cp.HARNESS_TYPES:
        e = c["events"].get(t)
        per_type[t] = bool(e is not None and len(e) and
                           (np.searchsorted(e, hi_s, "right") - np.searchsorted(e, lo_s, "left")) > 0)
    out["harness_events"] = any(per_type.values())
    aux["harness_by_type"] = per_type
    # raw-field changes inside the window's time span
    tl = c["timelines"]
    if tl is None:
        out["version_change"] = out["cwd_or_branch_change"] = out["permission_mode_change"] = False
        aux["raw_fields_evaluable"] = False
    else:
        v = changes_in_span(tl["version"], t_lo, t_hi)
        cw = changes_in_span(tl["cwd"], t_lo, t_hi)
        gb = changes_in_span(tl["gitBranch"], t_lo, t_hi)
        pm = changes_in_span(tl["permissionMode"], t_lo, t_hi)
        out["version_change"] = bool(v)
        out["cwd_or_branch_change"] = bool(cw) or bool(gb)
        out["permission_mode_change"] = bool(pm)
        aux["raw_fields_evaluable"] = True
        aux["raw_field_present"] = {"version": v is not None, "cwd": cw is not None, "gitBranch": gb is not None,
                                    "permissionMode": pm is not None}
        aux["cwd_change"], aux["branch_change"] = bool(cw), bool(gb)
    # idle gap: all IR rows in the seq window, consecutive stamps (time-sorted)
    rs, rt = c["row_seq"], c["row_tms"]
    w = rt[(rs >= lo_s) & (rs <= hi_s)]
    w = np.sort(w[np.isfinite(w)])
    mg = float(np.max(np.diff(w)) / 1000.0) if len(w) >= 2 else 0.0
    out["idle_gap"] = bool(mg >= T2["idle_gap_s"])
    aux["max_gap_s"] = mg
    # post hoc, not a verdict: the same idle-gap rule with W = 5 SESSION calls each side (seq range
    # [call(i - 5), call(i + 4)] around the split call i), the alternative reading of 'calls' raised by the re-derivation
    j_lo, j_hi = int(cseq[max(0, i_st - W)]), int(cseq[min(len(cseq) - 1, i_st + W - 1)])
    w2 = rt[(rs >= j_lo) & (rs <= j_hi)]
    w2 = np.sort(w2[np.isfinite(w2)])
    mg2 = float(np.max(np.diff(w2)) / 1000.0) if len(w2) >= 2 else 0.0
    aux["idle_gap_session_call_window"] = bool(mg2 >= T2["idle_gap_s"])
    aux["max_gap_s_session_call_window"] = mg2
    # hook share and parallelism: session calls in the two halves
    hp, hq = float(pre.hooked.mean()), float(post.hooked.mean())
    out["hook_rate_change"] = bool(abs(hq - hp) >= T2["hook_share"])
    np_pre, np_post = float((~pre["last"]).mean()), float((~post["last"]).mean())
    out["parallelism_change"] = bool(abs(np_post - np_pre) >= T2["parallel_share"])
    aux.update({"hook_share_pre": hp, "hook_share_post": hq, "not_last_share_pre": np_pre, "not_last_share_post": np_post,
                "calls_pre_half": int(len(pre)), "calls_post_half": int(len(post))})
    # tool mix: 20 session calls before the step call vs the step call and the 19 after
    J = T2["js_calls"]
    keys = ct.key.to_numpy()
    kb, ka = Counter(keys[max(0, i_st - J):i_st]), Counter(keys[i_st:i_st + J])
    jd = E.js_distance(kb, ka)
    out["tool_mix_shift"] = bool(jd >= T2["js_distance"])
    aux["js_distance"] = jd
    aux["tool_mix_calls"] = [int(sum(kb.values())), int(sum(ka.values()))]
    # result size: the series' own results, 5 points either side
    b = r["bytes"]
    mb, ma = float(np.median(b[max(0, k - W):k])), float(np.median(b[k:k + W]))
    lr = math.log10(max(ma, 1.0) / max(mb, 1.0))
    out["result_size_shift"] = bool(abs(lr) >= T2["size_log10"])
    aux["result_bytes_median_pre5"], aux["result_bytes_median_post5"], aux["result_size_log10_ratio"] = mb, ma, lr
    # subagent in flight at the step call's stamp (paired subagent|workflow calls, not the step call itself)
    sa = ct[ct.key.isin(SUBAGENT_KEYS) & (ct.seq != st_s)]
    inflight = bool(((sa.tms.to_numpy() <= t_st) & (sa.rtms.to_numpy() >= t_st)).any()) if len(sa) else False
    out["subagent_in_flight"] = inflight
    # workspace root of the read paths of each half
    rp = pc.workspace_root([p for ps in pre.paths for p in ps])
    rq = pc.workspace_root([p for ps in post.paths for p in ps])
    out["workspace_change"] = bool(rp is not None and rq is not None and rp != rq)
    aux["workspace_evaluable"] = bool(rp is not None and rq is not None)
    aux["window"] = {"k": int(k), "points_pre": int(min(W, k)), "points_post": int(min(W, n - k)),
                     "span_s": float((t_hi - t_lo) / 1000.0) if np.isfinite(t_hi - t_lo) else None,
                     "session_calls_in_window": int(i_hi - i_lo + 1)}
    return out, aux


def signature(r, k):
    return E.compromise_signature(r["delta"], r["chars"], k, G90, tokens_per_char=T2["tokens_per_char"])


# ================================================================================================ 4. credit / classes
def boot_diff(rows, cov):
    """Session-bootstrap CI of rate(step) - rate(control) for one covariate (rows: dicts with sid, is_step, cov)."""
    by = defaultdict(list)
    for x in rows:
        by[x["sid"]].append((x["is_step"], bool(x["cov"][cov])))
    groups = list(by.values())

    def fn(gs):
        s = [f for g in gs for st, f in g if st]
        c = [f for g in gs for st, f in g if not st]
        if not s or not c:
            return None
        return float(np.mean(s) - np.mean(c))
    return E.boot_stat(groups, fn)


def population(rows, label):
    """rows: one dict per series with sid, is_step, cov (covariate vector at k* or control k), sig, aux, meta.
    global.min_n: the credit test (a difference of two rates), the classes (which need the credit test) and the outcome
    are computed only when the step side and the control side are each >= 30 series from >= 5 sessions; otherwise raw
    k/n, the label 'insufficient n' and the outcome INSUFFICIENT_N."""
    st = [x for x in rows if x["is_step"]]
    ctl = [x for x in rows if not x["is_step"]]
    ns_st, ns_ctl = len({x["sid"] for x in st}), len({x["sid"] for x in ctl})
    step_ok, ctl_ok = rate_ok(len(st), ns_st), rate_ok(len(ctl), ns_ctl)
    testable = bool(st) and step_ok and ctl_ok
    out = {"population": label, "step_series": len(st), "step_sessions": ns_st,
           "control_series": len(ctl), "control_sessions": ns_ctl,
           "min_n": {"rate_reportable": MINN, "step_side_reportable": step_ok, "control_side_reportable": ctl_ok,
                     "credit_test_and_outcome_computed": testable,
                     "rule": "prereg_e.json global.min_n -> prereg.json global.min_n: " + PR["global"]["min_n"]["below_min"]}}
    cov_tab, credited = {}, []
    for cv in COVARIATES:
        ks = sum(bool(x["cov"][cv]) for x in st)
        kc = sum(bool(x["cov"][cv]) for x in ctl)
        row = {"step": rate_cell(ks, len(st), ns_st), "control": rate_cell(kc, len(ctl), ns_ctl),
               "present_in_step_series": int(ks)}
        if testable:
            d = ks / len(st) - kc / len(ctl)
            cr = bool(d >= T2["credit_diff"] - 1e-12 and ks >= T2["credit_min_series"])
            row.update({"diff": d, "diff_session_bootstrap": boot_diff(rows, cv), "credited": cr})
            if cr:
                credited.append(cv)
        else:
            row.update({"diff": None, "diff_session_bootstrap": None, "credited": None,
                        "credit_test": "not computed: " + INSUFF + " (global.min_n)"})
        cov_tab[cv] = row
    out["covariates"] = cov_tab
    out["credited_covariates"] = credited
    # harness per type (descriptive counts; the credited unit is `harness_events`)
    out["harness_by_type_descriptive"] = {
        t: {"step": int(sum(x["aux"]["harness_by_type"][t] for x in st)),
            "control": int(sum(x["aux"]["harness_by_type"][t] for x in ctl))} for t in cp.HARNESS_TYPES}
    n = len(st)
    if testable:
        cls = Counter()
        for x in st:
            benign = any(x["cov"][cv] for cv in credited)
            if benign:
                c = "BENIGN"
            elif x["sig"]["met"]:
                c = "COMPROMISE_LIKE"
            else:
                c = "UNEXPLAINED"
            x["class"] = c
            cls[c] += 1
        out["classes"] = {c: rate_cell(cls.get(c, 0), n, ns_st) for c in ("BENIGN", "COMPROMISE_LIKE", "UNEXPLAINED")}
        out["classes_by_direction"] = {d: dict(Counter(x["class"] for x in st if x["meta"]["direction"] == d))
                                       for d in sorted({x["meta"]["direction"] for x in st})}
        benign_share = cls.get("BENIGN", 0) / n
        out["outcome"] = ("DISMISSIBLE_AS_BENIGN" if benign_share >= T2["benign_share"] - 1e-12
                          and cls.get("COMPROMISE_LIKE", 0) == 0 else "OPEN")
        out["outcome_deciding"] = {"BENIGN": int(cls.get("BENIGN", 0)),
                                   "COMPROMISE_LIKE": int(cls.get("COMPROMISE_LIKE", 0)),
                                   "UNEXPLAINED": int(cls.get("UNEXPLAINED", 0)), "n_step_series": n,
                                   "step_sessions": ns_st, "benign_share": benign_share, "rule": F2["outcome_rule"]}
        out["compromise_like_series"] = [x["listing_index"] for x in st if x["class"] == "COMPROMISE_LIKE"]
    else:
        out["classes"] = None
        out["classes_note"] = ("not computed: own-population classes need the credit test, which is below min n; the "
                               "split breakdown of the primary B u E classes is under classes_of_primary_BuE_raw")
        out["outcome"] = "INSUFFICIENT_N" if n else "NO_STEP_SERIES"
        out["outcome_deciding"] = {"n_step_series": n, "step_sessions": ns_st, "control_series": len(ctl),
                                   "control_sessions": ns_ctl, "min_n": MINN, "label": INSUFF,
                                   "rule": PR["global"]["min_n"]["below_min"]}
    # signature legs on steps and (descriptive) on controls at their random split; raw counts always, share if reportable
    def legs(xs, ns):
        return {"met": int(sum(x["sig"]["met"] for x in xs)), "leg_rho": int(sum(x["sig"]["leg_rho"] for x in xs)),
                "leg_r": int(sum(x["sig"]["leg_r"] for x in xs)), "n": len(xs),
                "met_wilson": rate_cell(sum(x["sig"]["met"] for x in xs), len(xs), ns) if xs else None}
    out["signature_step"] = legs(st, ns_st)
    out["signature_control_descriptive"] = legs(ctl, ns_ctl)
    out["signature_control_note"] = "post hoc, not a verdict: the signature evaluated at each control's random split"
    return out


def read_matched(rows):
    """post hoc, not a verdict: covariate rates on read-key series only (step vs control), tool_key-matched view."""
    st = [x for x in rows if x["is_step"] and x["meta"]["tool_key"] == "read"]
    ctl = [x for x in rows if not x["is_step"] and x["meta"]["tool_key"] == "read"]
    ns_st, ns_ctl = len({x["sid"] for x in st}), len({x["sid"] for x in ctl})
    return {"note": "post hoc, not a verdict: tool_key = read only", "step_series": len(st), "step_sessions": ns_st,
            "control_series": len(ctl), "control_sessions": ns_ctl,
            "covariates": {cv: {"step": rate_cell(sum(bool(x["cov"][cv]) for x in st), len(st), ns_st),
                                "control": rate_cell(sum(bool(x["cov"][cv]) for x in ctl), len(ctl), ns_ctl)}
                           for cv in COVARIATES}}


def idle_gap_window_sensitivity(rows):
    """post hoc, not a verdict: idle_gap under the pre-registered-window reading used here (5 series calls each side)
    and under the session-call reading (5 session calls each side), step vs control, min-n gated."""
    st = [x for x in rows if x["is_step"]]
    ctl = [x for x in rows if not x["is_step"]]
    ns_st, ns_ctl = len({x["sid"] for x in st}), len({x["sid"] for x in ctl})
    ok = bool(st) and rate_ok(len(st), ns_st) and rate_ok(len(ctl), ns_ctl)
    out = {}
    for name, get in (("series_call_window_as_run", lambda x: bool(x["cov"]["idle_gap"])),
                      ("session_call_window", lambda x: bool(x["aux"]["idle_gap_session_call_window"]))):
        ks, kc = sum(get(x) for x in st), sum(get(x) for x in ctl)
        out[name] = {"step": rate_cell(ks, len(st), ns_st), "control": rate_cell(kc, len(ctl), ns_ctl),
                     "diff": (ks / len(st) - kc / len(ctl)) if ok else None}
    return out


# ================================================================================================ main
DEVIATIONS = [
    {"item": "F2 population: seed indexing of the change-point permutation test",
     "prereg_said": "population = Phase B floor_step_change series on swechat/claude_code B u E; replication = the Phase B "
                    "step rule on E alone; prereg.json probe1.floor_step_change seeds the permutation test with SEED + i, "
                    "i = index of the series in sorted (session_id, tool_key) order",
     "what_you_did": "the primary F2 step set is the union of the Phase B run on B (index within B; reproduces the 21 of "
                     "156 the prereg names) and the replication run on E (index within E). The run on the pooled B u E "
                     "list (pooled index, as phase_e_a1_p1_p3 K2 ran it) is reported as `sensitivity_pooled_index` with "
                     "its own controls, credits, classes and outcome, and the series whose step flag differs are listed",
     "why": "the permutation p of a series depends on its index in the population passed in; the pooled run re-indexes "
            "every series and flips series whose p sits near 0.01, so 'the Phase B series on B u E' has two readings",
     "effect_on_verdict": "none on any mechanism verdict (F2 moves no verdict); the F2 outcome under both readings is "
                          "in the JSON"},
    {"item": "window and segments of the change covariates",
     "prereg_said": "covariates in a window of W = 5 calls on each side of k*; version / cwd / permission / hook rate "
                    "'differ between the pre- and post-step segments'; parallelism and result size 'differ by'; tool mix "
                    "over the 20 calls before and after k*",
     "what_you_did": "window = seq range [anchor(k* - 5), anchor(k* + 4)] with anchors = the series' call seqs (the "
                     "Phase C changepoints window_bounds convention whose harness definitions F2 copies); the 'segments' "
                     "of every change covariate are the two halves of this window, [anchor(k* - 5), anchor(k*)) and "
                     "[anchor(k*), anchor(k* + 4)]; hook share and parallelism are computed over all session calls in "
                     "each half (series calls are qualified pairs, which by the filter are never hooked and always last "
                     "in their message); result size over the series' own 5 points either side; tool mix over the 20 "
                     "session calls before the step call and the step call plus the 19 after; raw-field covariates fire "
                     "when the value in effect changes at an entry stamped inside the window's time span "
                     "(anchor(k* - 5) call ts, anchor(k* + 4) call ts]. Exactly the same code runs at the control split",
     "why": "the prereg does not say whether 'calls' are series points or session calls, nor what a 'segment' is; this "
            "is the reading under which every listed covariate is computable and localised at the step",
     "effect_on_verdict": "none (no verdict moves); the whole-segment result-size ratio is reported post hoc per series"},
    {"item": "subagent in flight",
     "prereg_said": "a subagent call is in flight at the step call's stamp",
     "what_you_did": "a call with tool_key subagent or workflow (the Phase C subagent_start definition), other than the "
                     "step call, whose call ts <= step-call ts <= its result ts; calls without a result are not counted",
     "why": "an unpaired subagent call has no end stamp",
     "effect_on_verdict": "can only lower that covariate's rate, equally at steps and controls"},
    {"item": "result-size log ratio with empty results",
     "prereg_said": "|log10(median result bytes after / before)| >= log10 2",
     "what_you_did": "medians floored at 1 byte before the ratio",
     "why": "log10 of 0 is undefined",
     "effect_on_verdict": "none unless a median is 0 bytes"},
    {"item": "minimum n on the B-alone and E-alone F2 populations (fix; the first run did not apply it and did not log it)",
     "prereg_said": "prereg_e.json global.min_n: 'as prereg.json global.min_n (rate >= 30 from >= 5 sessions ...). "
                    "Item-specific minima below are additional, never weaker'; prereg.json global.min_n.below_min: "
                    "'report raw k/n (or n) and the label insufficient n; no rate, no CI, no verdict'",
     "what_you_did": "the rule is applied as written to every population rate in this file. B (21 step series) and E "
                     "(10 step series) are below 30 on the step side, so their step-side covariate rates, the "
                     "step-minus-control differences and their bootstrap CIs, the credit test, the own-population "
                     "classes and the F2 outcome are withheld (raw k/n, label 'insufficient n', outcome INSUFFICIENT_N). "
                     "B u E (31 from 28 sessions) and the pooled-index sensitivity (35 from 30) are above it and "
                     "unchanged. The smallest faithful substitute for the withheld B / E classes is the split breakdown "
                     "of the primary B u E classes as raw counts (classes_of_primary_BuE_raw). The post hoc read-only "
                     "step side (25 series) is gated the same way; population quantiles in post_hoc are gated by "
                     "quantile_reportable (min, max, mean kept, as probe_1). Per-series inputs of the pre-registered "
                     "per-series covariates and signature (5-point medians, series medians in the human-review listing) "
                     "are single-series quantities, not population rates, and are not gated",
     "why": "an independent re-derivation found that the first run reported rates, CIs, a credit and an outcome on 21 "
            "and 10 step series; the global minimum forbids that and item minima can only be stricter",
     "effect_on_verdict": "F2 outcome B: OPEN -> INSUFFICIENT_N; F2 outcome E: OPEN -> INSUFFICIENT_N and the E-alone "
                          "idle_gap credit (7/10 vs 38/113) is withdrawn; B u E primary outcome OPEN unchanged; no "
                          "mechanism verdict moves (F2 moves none). Earlier values are kept under `corrections`"},
]

# Values of the first run (run_utc 2026-10-04T08:30:10Z), kept visible; `after` is filled from this run.
CORRECTIONS = [
    {"path": "populations.E.outcome", "before": "OPEN",
     "before_deciding": {"BENIGN": 7, "COMPROMISE_LIKE": 0, "UNEXPLAINED": 3, "n_step_series": 10, "benign_share": 0.7},
     "reason": "10 step series in 10 sessions < 30 (global.min_n): no verdict"},
    {"path": "populations.E.credited_covariates", "before": ["idle_gap"],
     "before_detail": {"idle_gap": {"step": "7/10 = 0.700 W[0.397, 0.892]", "control": "38/113 = 0.336",
                                    "diff": 0.36371681415929197,
                                    "diff_session_bootstrap": [0.032103414991346, 0.6413864942528735],
                                    "credited": True}},
     "reason": "the credit test is a difference of rates; the step-side rate is below min n, so it is not computed"},
    {"path": "populations.E.classes", "before": {"BENIGN": "7/10", "COMPROMISE_LIKE": "0/10", "UNEXPLAINED": "3/10"},
     "reason": "own-population classes need the E credit test (withheld); see populations.E.classes_of_primary_BuE_raw"},
    {"path": "populations.B.outcome", "before": "OPEN",
     "before_deciding": {"BENIGN": 0, "COMPROMISE_LIKE": 3, "UNEXPLAINED": 18, "n_step_series": 21, "benign_share": 0.0},
     "reason": "21 step series in 18 sessions < 30 (global.min_n): no verdict"},
    {"path": "populations.B.credited_covariates", "before": [],
     "before_detail": {"closest": "idle_gap 11/21 = 0.524 vs 47/135 = 0.348, diff 0.17566137566137568, "
                                  "bootstrap [-0.0630433006535948, 0.3923508470965499], not credited"},
     "reason": "credit test not computed below min n (value unchanged, meaning changed: 'not tested' instead of "
               "'none credited')"},
    {"path": "populations.B.classes", "before": {"BENIGN": "0/21", "COMPROMISE_LIKE": "3/21", "UNEXPLAINED": "18/21"},
     "reason": "own-population classes need the B credit test (withheld); the same raw counts are the B breakdown of "
               "the primary B u E classes (populations.B.classes_of_primary_BuE_raw)"},
    {"path": "populations.{B,E}.covariates.*.step / .diff / .diff_session_bootstrap / .credited",
     "before": "Wilson share with CI, difference, session-bootstrap CI and credited flag on 21 (B) and 10 (E) step series",
     "reason": "below min n: raw k/n with the label 'insufficient n' (step side); control side stays reportable"},
    {"path": "populations.{B,E}.signature_step.met_wilson", "before": {"B": "3/21 W[0.050, 0.346]", "E": "0/10 W[0, 0.278]"},
     "reason": "below min n: raw k/n only"},
    {"path": "step_series_listing[*].class_own_split",
     "before": "E listing 21, 23, 24, 27, 28, 29, 30 BENIGN (via the E-alone idle_gap credit), E 22, 25, 26 UNEXPLAINED; "
               "B as class_BuE",
     "reason": "own-split classes are withheld for B and E (credit test below min n); class_BuE (primary) is unchanged"},
    {"path": "post_hoc.read_only_matched_BuE.covariates.*.step",
     "before": "Wilson shares on 25 read step series", "reason": "25 < 30 (global.min_n): raw k/n only"},
    {"path": "post_hoc.*_quantiles / *_window_session_calls",
     "before": "all quantiles of stats.describe reported",
     "reason": "global.min_n.quantile_reportable: p5/p95 need 100, p1/p99 500 (from >= 5 sessions); withheld below"},
]


def main():
    t0 = time.time()
    check_f2_text()
    p1.check_thresholds_against_text()
    pre = {"prereg_e_json_sha256": E.sha256_file(E.PREREG_E_JSON),
           "spec_module_sha256_lf": E.sha256_lf(ROOT / "analysis" / "probes" / "prereg_e_common.py"),
           "spec_module_sha256_lf_prereg": PJ["provenance"]["spec_module_sha256_lf"], "check_frozen": "passed",
           "phase_b_prereg_json_sha256": p1.sha256(p1.PREREG_PATH),
           "phase_b_spec_module_sha_ok": p1.sha256(p1.SPEC_PATH) == PR["provenance"]["spec_module_sha256"],
           "phase_b_calibration_sha_ok": p1.sha256(p1.CALIB_PATH) == PR["provenance"]["calibration_script_sha256"]}
    if not (pre["phase_b_spec_module_sha_ok"] and pre["phase_b_calibration_sha_ok"]):
        raise SystemExit("Phase B module sha mismatch: stop")
    ids_B, ids_E = set(unit_ids("B")), set(unit_ids("E"))
    assert not (ids_B & ids_E)
    split_of = {s: "B" for s in ids_B} | {s: "E" for s in ids_E}

    # ---------------------------------------------------------------- 1. step series per split
    series, cps, extraction = {}, {}, {}
    for sp in ("B", "E"):
        u = load_pass1(sp)
        print(f"[{time.time() - t0:7.1f}s] loaded {sp}: {len(u)} rows, {u.session_id.nunique()} sessions", flush=True)
        Q, extraction[sp] = qualified_pairs(u)
        del u
        series[sp] = build_series(Q, split_of)
        del Q
        cps[sp] = run_change_points(series[sp])
        print(f"[{time.time() - t0:7.1f}s] {sp}: {len(series[sp])} eligible series, "
              f"{sum(c['step'] for c in cps[sp])} steps", flush=True)
    pooled = sorted(series["B"] + series["E"], key=lambda r: (r["session_id"], r["tool_key"]))
    cps_pooled = run_change_points(pooled)
    print(f"[{time.time() - t0:7.1f}s] pooled: {len(pooled)} series, {sum(c['step'] for c in cps_pooled)} steps", flush=True)
    steps = {"B": step_summary(series["B"], cps["B"]), "E": step_summary(series["E"], cps["E"]),
             "BuE_union_of_split_runs": step_summary(series["B"] + series["E"], cps["B"] + cps["E"]),
             "BuE_pooled_index": step_summary(pooled, cps_pooled)}
    ref = PJ["references"]["floor_steps_B"]
    steps["B_reproduces_phase_b"] = {
        "phase_b": [ref["steps"], ref["eligible_series"], ref["sessions_with_step"], ref["eligible_sessions"]],
        "here": [steps["B"]["steps"], steps["B"]["eligible_series"], steps["B"]["sessions_with_step"],
                 steps["B"]["eligible_sessions"]]}
    steps["B_reproduces_phase_b"]["match"] = steps["B_reproduces_phase_b"]["phase_b"] == steps["B_reproduces_phase_b"]["here"]
    # series-level match with the committed Phase B listing (probe_1.json)
    pb = json.load(open(ROOT / "analysis" / "out" / "probe_1.json", encoding="utf-8"))["units"][UNIT]["floor_step_change"]["series"]
    pb_keys = {(x["session"], x["tool_key"]): (x["k"], x["step"], round(x["p"], 6)) for x in pb}
    mine = {(r["session_id"], r["tool_key"]): (c["k"], c["step"], round(c["p"], 6)) for r, c in zip(series["B"], cps["B"])}
    steps["B_reproduces_phase_b"]["series_level_match"] = bool(pb_keys == mine)
    a1 = json.load(open(E.OUT_E / "a1_p1_p3.json", encoding="utf-8"))["candidates"]["P1/" + UNIT]["populations"]
    steps["cross_check_a1_p1_p3"] = {
        pop: {"a1": [a1[pop]["floor_step_change"]["steps"], a1[pop]["floor_step_change"]["eligible_series"]],
              "here": [steps[key]["steps"], steps[key]["eligible_series"]]}
        for pop, key in (("B", "B"), ("E", "E"), ("BuE", "BuE_pooled_index"))}
    steps["replication_E"] = {"label": steps["E"]["label"], "step_share": steps["E"].get("step_share_wilson"),
                              "rule": F2["replication"]}
    flip = []
    union_flag = {(r["session_id"], r["tool_key"]): c for r, c in zip(series["B"] + series["E"], cps["B"] + cps["E"])}
    for r, c in zip(pooled, cps_pooled):
        u0 = union_flag[(r["session_id"], r["tool_key"])]
        if u0["step"] != c["step"]:
            flip.append({"session": r["session_id"], "split": r["split"], "tool_key": r["tool_key"], "n": c["n"],
                         "p_split_run": u0["p"], "p_pooled_run": c["p"], "D_log10_split_run": u0["D_log10"],
                         "D_log10_pooled_run": c["D_log10"], "step_split_run": u0["step"], "step_pooled_run": c["step"]})
    steps["pooled_vs_union_step_flag_differs"] = flip

    # ---------------------------------------------------------------- 2-3. contexts, controls, covariates
    eligible_sids = {sp: sorted({r["session_id"] for r in series[sp]}) for sp in ("B", "E")}
    ctx, scan = {}, Counter()
    for sp in ("B", "E"):
        assert set(eligible_sids[sp]) <= (ids_B if sp == "B" else ids_E)
        df = load_pass2(sp, eligible_sids[sp])
        c, s = session_contexts(df)
        del df
        ctx.update(c)
        scan.update(s)
        print(f"[{time.time() - t0:7.1f}s] contexts {sp}: {len(c)} sessions", flush=True)

    ctrl_k = {}
    for r in pooled:
        n = len(r["delta"])
        ctrl_k[(r["session_id"], r["tool_key"])] = int(E.rng_for("F2", r["session_id"], r["tool_key"])
                                                       .integers(T2["ctrl_lo"], n - T2["ctrl_lo"] + 1))

    def eval_rows(sers, cplist):
        rows = []
        for r, c in zip(sers, cplist):
            key = (r["session_id"], r["tool_key"])
            k = c["k"] if c["step"] else ctrl_k[key]
            cov, aux = covariates_at(ctx[r["session_id"]], r, k)
            sig = signature(r, k)
            meta = {"session": r["session_id"], "split": r["split"], "tool_key": r["tool_key"], "n": c["n"], "k": k,
                    "k_over_n": k / c["n"], "D_log10": c["D_log10"], "factor": c["factor"], "p": c["p"],
                    "direction": c["direction"], "Q10_left_s": c["Q10_left_s"], "Q10_right_s": c["Q10_right_s"]}
            rows.append({"sid": r["session_id"], "is_step": bool(c["step"]), "cov": cov, "aux": aux, "sig": sig,
                         "meta": meta, "r": r, "k": k})
        return rows

    rows_union = eval_rows(series["B"] + series["E"], cps["B"] + cps["E"])
    rows_pooled = eval_rows(pooled, cps_pooled)
    # listing index: step series of the union population, in (split, session, tool_key) order
    st_union = sorted([x for x in rows_union if x["is_step"]], key=lambda x: (x["meta"]["split"], x["sid"],
                                                                               x["meta"]["tool_key"]))
    for i, x in enumerate(st_union):
        x["listing_index"] = i
    idx_of = {(x["sid"], x["meta"]["tool_key"]): x["listing_index"] for x in st_union}
    for x in rows_pooled:
        x["listing_index"] = idx_of.get((x["sid"], x["meta"]["tool_key"]), f"pooled_only:{x['sid']}|{x['meta']['tool_key']}")
    pops = {"B": population([x for x in rows_union if x["meta"]["split"] == "B"], "B"),
            "E": population([x for x in rows_union if x["meta"]["split"] == "E"], "E"),
            "BuE": population(rows_union, "BuE (union of the B and E runs; primary)")}
    # classes under the BuE credits are what the listing shows (only the BuE run sets x['class']: B and E are below
    # min n and get no own classes)
    assert pops["BuE"]["min_n"]["credit_test_and_outcome_computed"]
    listing_classes = {x["listing_index"]: x["class"] for x in st_union}
    sens = population(rows_pooled, "BuE pooled-index run (sensitivity)")
    # split breakdown of the primary B u E classes, raw counts (no rate, no CI): the faithful view of B and E alone
    for sp in ("B", "E"):
        xs = [x for x in st_union if x["meta"]["split"] == sp]
        cnt = Counter(x["class"] for x in xs)
        pops[sp]["classes_of_primary_BuE_raw"] = {
            "note": "the step series of this split classified under the primary B u E credits (none credited); raw "
                    "k/n, no rate, no CI" + ("" if pops[sp]["min_n"]["credit_test_and_outcome_computed"]
                                             else " (" + INSUFF + ")"),
            **{c: {"k": int(cnt.get(c, 0)), "n": len(xs)} for c in ("BENIGN", "COMPROMISE_LIKE", "UNEXPLAINED")},
            "compromise_like_series": [x["listing_index"] for x in xs if x["class"] == "COMPROMISE_LIKE"],
            "by_direction": {d: dict(Counter(x["class"] for x in xs if x["meta"]["direction"] == d))
                             for d in sorted({x["meta"]["direction"] for x in xs})}}

    # ---------------------------------------------------------------- listing of every step series (union)
    step_sess = Counter(x["sid"] for x in st_union)
    listing = []
    for x in st_union:
        r, k = x["r"], x["k"]
        b = r["bytes"]
        others = [y for y in st_union if y["sid"] == x["sid"] and y is not x]
        t_step = cp._to_ms(pd.Series([r["ts"][k]], dtype=object))[0]
        co = []
        for y in others:
            ty = cp._to_ms(pd.Series([y["r"]["ts"][y["k"]]], dtype=object))[0]
            co.append({"listing_index": y["listing_index"], "tool_key": y["meta"]["tool_key"],
                       "direction": y["meta"]["direction"], "step_time_diff_s": float(abs(ty - t_step) / 1000.0)})
        listing.append({
            "listing_index": x["listing_index"], **x["meta"], "class_BuE": listing_classes[x["listing_index"]],
            "class_own_split": x.get("class"),
            "covariates": x["cov"], "signature": x["sig"],
            "window": x["aux"]["window"], "max_gap_s": x["aux"]["max_gap_s"], "js_distance": x["aux"]["js_distance"],
            "hook_share_pre_post": [x["aux"]["hook_share_pre"], x["aux"]["hook_share_post"]],
            "not_last_share_pre_post": [x["aux"]["not_last_share_pre"], x["aux"]["not_last_share_post"]],
            "result_bytes_median_pre5_post5": [x["aux"]["result_bytes_median_pre5"], x["aux"]["result_bytes_median_post5"]],
            "harness_types_in_window": sorted(t for t, v in x["aux"]["harness_by_type"].items() if v),
            "post_hoc_not_a_verdict": {
                "result_bytes_median_whole_segments": [float(np.median(b[:k])), float(np.median(b[k:]))],
                "subagent_share_of_series_points_pre_post": [float(r["is_sub"][:k].mean()), float(r["is_sub"][k:].mean())],
                "other_step_series_same_session": co,
                "latency_median_s_pre_post": [float(np.median(r["delta"][:k])), float(np.median(r["delta"][k:]))]}})
    # class_own_split: the class under the own split's credits, only where that split's credit test is computed
    own = {}
    for sp in ("B", "E"):
        cred = pops[sp]["credited_covariates"]
        ok = pops[sp]["min_n"]["credit_test_and_outcome_computed"]
        for y in st_union:
            if y["meta"]["split"] != sp:
                continue
            if not ok:
                own[y["listing_index"]] = "INSUFFICIENT_N"
                continue
            benign = any(y["cov"][cv] for cv in cred)
            own[y["listing_index"]] = "BENIGN" if benign else ("COMPROMISE_LIKE" if y["sig"]["met"] else "UNEXPLAINED")
    for x, y in zip(listing, st_union):
        assert x["listing_index"] == y["listing_index"]
        x["class_own_split"] = own[x["listing_index"]]
        x["idle_gap_session_call_window_post_hoc"] = {"idle_gap": y["aux"]["idle_gap_session_call_window"],
                                                      "max_gap_s": y["aux"]["max_gap_s_session_call_window"]}

    # ---------------------------------------------------------------- post hoc descriptive blocks
    post_hoc = {
        "note": "post hoc, not a verdict",
        "read_only_matched_BuE": read_matched(rows_union),
        "sessions_with_more_than_one_step_series": int(sum(1 for v in step_sess.values() if v > 1)),
        "step_series_in_those_sessions": int(sum(v for v in step_sess.values() if v > 1)),
        "control_window_session_calls": describe_gated([x["aux"]["window"]["session_calls_in_window"]
                                                        for x in rows_union if not x["is_step"]],
                                                       pops["BuE"]["control_sessions"]),
        "step_window_session_calls": describe_gated([x["aux"]["window"]["session_calls_in_window"]
                                                     for x in rows_union if x["is_step"]],
                                                    pops["BuE"]["step_sessions"]),
        "workspace_evaluable": {"step": int(sum(x["aux"]["workspace_evaluable"] for x in rows_union if x["is_step"])),
                                "control": int(sum(x["aux"]["workspace_evaluable"] for x in rows_union if not x["is_step"]))},
        "raw_fields_present_any": {
            f: {"step": int(sum(x["aux"].get("raw_field_present", {}).get(f, False) for x in rows_union if x["is_step"])),
                "control": int(sum(x["aux"].get("raw_field_present", {}).get(f, False) for x in rows_union
                                   if not x["is_step"]))}
            for f in ("version", "cwd", "gitBranch", "permissionMode")},
        "cwd_vs_branch_split": {
            "step": {"cwd": int(sum(x["aux"].get("cwd_change", False) for x in rows_union if x["is_step"])),
                     "branch": int(sum(x["aux"].get("branch_change", False) for x in rows_union if x["is_step"]))},
            "control": {"cwd": int(sum(x["aux"].get("cwd_change", False) for x in rows_union if not x["is_step"])),
                        "branch": int(sum(x["aux"].get("branch_change", False) for x in rows_union if not x["is_step"]))}},
        "step_Q10_left_s_quantiles": describe_gated([x["meta"]["Q10_left_s"] for x in st_union],
                                                    pops["BuE"]["step_sessions"]),
        "step_Q10_right_s_quantiles": describe_gated([x["meta"]["Q10_right_s"] for x in st_union],
                                                     pops["BuE"]["step_sessions"]),
        "idle_gap_window_reading_sensitivity": {
            "note": "post hoc, not a verdict: idle_gap (>= 300 s) with the window read as 5 SERIES calls each side "
                    "(as run, the covariate above) and as 5 SESSION calls each side (seq range [call(i - 5), "
                    "call(i + 4)] around the split call i); min-n gated; raised by the independent re-derivation",
            "BuE": idle_gap_window_sensitivity(rows_union),
            "B": idle_gap_window_sensitivity([x for x in rows_union if x["meta"]["split"] == "B"]),
            "E": idle_gap_window_sensitivity([x for x in rows_union if x["meta"]["split"] == "E"]),
            "pooled_index": idle_gap_window_sensitivity(rows_pooled)},
        "steps_with_both_Q10_below_10ms": int(sum(1 for x in st_union if max(x["meta"]["Q10_left_s"],
                                                                               x["meta"]["Q10_right_s"]) < 0.010)),
    }

    result = {
        "item": "f2_floor_shift", "script": "analysis/probes/phase_e_f2_floor_shift.py",
        "run_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "prereg": pre,
        "prereg_section": "followups.F2_floor_shift (PREREG_E.md 1.6)", "unit": UNIT,
        "population_rule": "step series of the Phase B rule on B (index within B) and on E (index within E); primary "
                           "population B u E = their union; B and E reported separately; pooled-index run = sensitivity",
        "thresholds_used": {"F2": T2, "probe1_step": {k: TH[k] for k in ("step_m", "step_n_perm", "step_p", "step_D",
                                                                          "step_share_unstable")},
                            "G90_tokens_per_s": G90, "covariate_text": COV, "control": F2["control"],
                            "credited_covariate": F2["credited_covariate"],
                            "compromise_signature": F2["compromise_signature"], "classes": F2["classes"],
                            "outcome_rule": F2["outcome_rule"]},
        "inputs_sha256": {f"analysis/cache/{f}.parquet": E.sha256_file(E.CACHE / f"{f}.parquet")
                          for f in ("swechat_B", "swechat_E", "swechat_population")},
        "extraction": extraction, "raw_scan": dict(scan),
        "steps": steps,
        "populations": pops,
        "sensitivity_pooled_index": sens,
        "step_series_listing": listing,
        "post_hoc": post_hoc,
        "deviations": DEVIATIONS,
        "corrections": None,
        "verdict_effect": "none: F2 moves no mechanism verdict (prereg_e.json followups.F2_floor_shift.outcome_rule, "
                          "no_rescue)",
        "verdicts": {
            "F2_outcome_BuE": {"outcome": pops["BuE"]["outcome"], "deciding": pops["BuE"]["outcome_deciding"],
                               "json_path": "populations.BuE.outcome; populations.BuE.outcome_deciding"},
            "F2_outcome_B": {"outcome": pops["B"]["outcome"], "deciding": pops["B"]["outcome_deciding"],
                             "json_path": "populations.B.outcome; populations.B.outcome_deciding"},
            "F2_outcome_E": {"outcome": pops["E"]["outcome"], "deciding": pops["E"]["outcome_deciding"],
                             "json_path": "populations.E.outcome; populations.E.outcome_deciding"},
            "F2_outcome_pooled_index_sensitivity": {"outcome": sens["outcome"], "deciding": sens["outcome_deciding"],
                                                    "json_path": "sensitivity_pooled_index.outcome"},
            "E_replication_floor_label": {"label": steps["E"]["label"], "deciding": steps["E"].get("step_share_wilson"),
                                          "json_path": "steps.E.label; steps.E.step_share_wilson"}},
        "verdict_cells_computed": {
            "F2_outcomes": 4,
            "F2_outcomes_decided": int(sum(P["outcome"] in ("OPEN", "DISMISSIBLE_AS_BENIGN")
                                           for P in (pops["B"], pops["E"], pops["BuE"], sens))),
            "F2_outcomes_insufficient_n": int(sum(P["outcome"] == "INSUFFICIENT_N"
                                                  for P in (pops["B"], pops["E"], pops["BuE"], sens))),
            "replication_labels": 1,
            "credit_tests": int(sum(len(COVARIATES) for P in (pops["B"], pops["E"], pops["BuE"], sens)
                                    if P["min_n"]["credit_test_and_outcome_computed"])),
            "credit_tests_withheld_insufficient_n": int(sum(len(COVARIATES)
                                                            for P in (pops["B"], pops["E"], pops["BuE"], sens)
                                                            if not P["min_n"]["credit_test_and_outcome_computed"])),
            "multiplicity": PJ["global"]["multiplicity"]},
    }
    # corrections: earlier values (first run) beside this run's values at the same path
    after = {
        "populations.E.outcome": {"outcome": pops["E"]["outcome"], "deciding": pops["E"]["outcome_deciding"]},
        "populations.E.credited_covariates": {"credited_covariates": pops["E"]["credited_covariates"],
                                              "idle_gap": pops["E"]["covariates"]["idle_gap"]},
        "populations.E.classes": {"classes": pops["E"]["classes"],
                                  "classes_of_primary_BuE_raw": pops["E"]["classes_of_primary_BuE_raw"]},
        "populations.B.outcome": {"outcome": pops["B"]["outcome"], "deciding": pops["B"]["outcome_deciding"]},
        "populations.B.credited_covariates": {"credited_covariates": pops["B"]["credited_covariates"],
                                              "idle_gap": pops["B"]["covariates"]["idle_gap"]},
        "populations.B.classes": {"classes": pops["B"]["classes"],
                                  "classes_of_primary_BuE_raw": pops["B"]["classes_of_primary_BuE_raw"]},
        "populations.{B,E}.covariates.*.step / .diff / .diff_session_bootstrap / .credited":
            {sp: {cv: pops[sp]["covariates"][cv]["step"] for cv in COVARIATES} for sp in ("B", "E")},
        "populations.{B,E}.signature_step.met_wilson": {sp: pops[sp]["signature_step"]["met_wilson"] for sp in ("B", "E")},
        "step_series_listing[*].class_own_split": {str(x["listing_index"]): x["class_own_split"] for x in listing},
        "post_hoc.read_only_matched_BuE.covariates.*.step":
            {cv: post_hoc["read_only_matched_BuE"]["covariates"][cv]["step"] for cv in COVARIATES},
        "post_hoc.*_quantiles / *_window_session_calls":
            {k: post_hoc[k] for k in ("step_window_session_calls", "control_window_session_calls",
                                      "step_Q10_left_s_quantiles", "step_Q10_right_s_quantiles")},
    }
    result["corrections"] = [{**c, "after": after[c["path"]], "previous_run_utc": "2026-10-04T08:30:10Z",
                              "found_by": "independent re-deriver (blocking: min-n gating not applied, not logged)"}
                             for c in CORRECTIONS]
    result["runtime_s"] = round(time.time() - t0, 1)
    txt = json.dumps(clean(result), indent=1, allow_nan=False, ensure_ascii=False)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(txt, encoding="utf-8")
    print(f"done in {result['runtime_s']}s -> {OUT}")
    for k, v in result["verdicts"].items():
        print(f"  {k:40s} {v.get('outcome', v.get('label'))}  {v['deciding']}")
    for p in ("B", "E", "BuE"):
        print(p, "credited:", pops[p]["credited_covariates"], "outcome:", pops[p]["outcome"])
    print("idle gap window sensitivity:", json.dumps(clean(post_hoc["idle_gap_window_reading_sensitivity"]))[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
