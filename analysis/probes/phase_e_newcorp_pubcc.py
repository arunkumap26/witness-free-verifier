"""Phase E new-corpus measurement, group `pubcc`: corpora pub_cc_hf and pub_trace_commons (raw Claude Code JSONL with
Anthropic request ids), registered as pre-registered extensions (prereg_e.json change_log, commit 669124a).

Run from the worktree root (B and E caches must exist; build them with the corpus loaders' --split path first):
    PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_newcorp_pubcc [--corpus pub_cc_hf] [--only R1,P1,...]
Writes analysis/out/phase_e/newcorp_measure_<corpus>.json per corpus: raw numbers and mechanically computed labels only.
Interpretation: analysis/notes/phase_e_newcorp_pubcc.md.

PRE-REGISTRATION READ AND APPLIED
  analysis/PREREG_E.md + analysis/prereg_e.json (incl. change_log: the pub_cc_hf / pub_trace_commons extension records
  and the ORCHESTRATOR DECISIONS D1-D7, binding), analysis/out/phase_e/prereg_e_calibration_<corpus>.json (the corpus's
  own A-split thresholds), analysis/probes/prereg_e_common.py (check_frozen() runs first; every detector, bracket,
  placebo, category, injector and statistic helper is called from it, never re-implemented), analysis/prereg.json +
  analysis/probes/prereg_common.py / prereg_calibration.py (Phase B rules, unchanged).
  D1: the unit argument passed to every unit-dispatching frozen function is 'cc_local' (same Claude Code generation),
      exactly as the calibration script did; the corpus argument stays the real corpus name.
  D2: the AC4 dominance / confinement cluster is the corpus stratum (pub_cc_hf: source repo; pub_trace_commons: modal
      model) = prereg_e_common.session_cluster_map('cc_local', u) (its cc_local branch returns the stratum column).
  D5: analysis/out/phase_e/newcorp_exclusions.json is applied (it lists no session of these two corpora; asserted
      and recorded).
  D6: bracket (R1/F1), latency (Probe 1) and reaction-time (N3) cells are labelled NOT_BLIND.

DATA READ (read-only): analysis/cache/<corpus>_{B,E}.parquet through prereg_e_common.read_cache only (never A, never
  H); the corpus index analysis/cache/<corpus>_index.json (B/E file lists only; H has no entry) and the raw JSONL files
  it names, for the AC1 parser audit of inconsistent bracket streams (only timestamp / requestId / uuid fields are
  compared; no text is read into the output). No secret value is printed or stored: the loaders redacted on load and
  this script stores counts only.

IMPLEMENTATION CHOICES FIXED BEFORE ANY B/E NUMBER WAS SEEN (the prereg leaves them to the implementer)
  R1/F1 (ported from the Track A script analysis/probes/phase_e_f1_bracket.py, which applied the same pre-registered
  rules to swechat/claude_code and cc_local; the functions are copied here, not imported, so this output does not
  depend on an uncommitted file):
   1. text is truncated to 200 characters after the truncation flag is computed on the full text
      (bracket_benign_categories reads only t[:200] and startswith()).
   2. "another session of the corpus" (restamped_copy and its dedupe) = another session of the readable corpus B u E.
   3. corrections per category as phase_e_f1_bracket.py (drop binding responses carrying a drop category and recompute;
      clock_step = piecewise_consistent; concurrent = abstain; whole_second / vertex_or_bedrock = 3,000 ms tolerance);
      abstain counts as not flagged, the denominator stays all streams. Adoption is decided per corpus on its own B and
      the adopted set is applied unchanged to E.
   4. R1 kill rule on stream-level tamper cells (one tamper per stream, N7 injectors, seeds rng_for(attack, param,
      session, stream) / rng_for('donor', ...)); the honest bar is the session-clustered CI hi (per-event Wilson hi if
      the numerator is 0). Back-dating types = time_response_early, time_tail_early.
   5. The N7 leg of the R1 verdict is computed here at session level for the R1_BRACKET detector (n7_cell_label; target
      rng_for(attack, param, session); session flag = any inconsistent stream; abstain = not flagged), on B, E and B u E.
      "single-call or single-response" = prereg_e_common.SPEC_E n7_attack_battery.single_call_types. The leg is
      DETECTS if >= 1 such type DETECTS on E, PARTIAL if >= 1 attack type DETECTS or PARTIAL, BLIND if every cell with
      n >= 30 is BLIND, INSUFFICIENT_N if no cell reaches 30 tampered sessions.
   6. The <synthetic>-model entries that carry a request id are kept (the frozen bracket_responses keeps every id);
      a sensitivity recompute without them is reported (not a verdict).
   7. Minimum n for any R1 rate: >= 30 streams from >= 5 sessions (prereg.json global.min_n.rate_reportable); below it
      the R1 cell is INSUFFICIENT_N with raw k/n. Strata: reportable at >= 30 streams from >= 5 sessions.
   8. AC5 is NOT_RUN: prereg_e_common.population_cells has no population table for new corpora.
   9. Step 0 is defined on swechat/claude_code B only (Track A ran it: REPRODUCED); it is not re-run here.
  Probes 1-4 and N1-N5 implementation choices are listed in the sections below (each before its code).
"""
import argparse
import gc
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.lib import stats
from analysis.lib.ir import parse_ts
from analysis.probes import prereg_common as pc
from analysis.probes import prereg_e_common as pe

GROUP = "pubcc"
CORPORA = ("pub_cc_hf", "pub_trace_commons")
PROXY = "cc_local"  # D1
ROOT = pe.ROOT
SCRIPT = "analysis/probes/phase_e_newcorp_pubcc.py"
COLS = ["session_id", "stratum", "seq", "kind", "ts", "tool", "tool_raw", "call_id", "args", "command", "text",
        "stderr", "native_error", "exit_code", "usage_in", "usage_out", "api_msg_id", "request_id", "model",
        "is_subagent", "agent_id", "parent_call_id", "extra", "uuid", "parent_uuid"]
TOL = pe.BRACKET_TOL_MS
TOL_CORR = 3000.0
CATS = ["restamped_copy", "clock_step", "concurrent_streams", "api_retry", "compaction", "user_input_binding",
        "long_gap", "whole_second", "vertex_or_bedrock"]
DROP_CATS = {"api_retry", "compaction", "user_input_binding", "long_gap"}
TOL_CATS = {"whole_second", "vertex_or_bedrock"}
BACKDATE_TYPES = {"time_response_early", "time_tail_early"}
SINGLE_CALL = set(pe.SPEC_E["n7_attack_battery"]["single_call_types"])
PLACEBO = [("back", 5000), ("back", 30000), ("late", 5000), ("late", 30000), ("late", 300000)]
SLIM = ["session_id", "seq", "kind", "ts", "request_id", "is_subagent", "agent_id", "call_id", "parent_call_id"]
R1_ATTACKS = ([("time_response_early", D) for D in pe.GRID_D] +
              [("time_response_late", D) for D in pe.GRID_D_LATE_CHECK] +
              [("time_result_late", D) for D in pe.GRID_D] +
              [("time_result_early", D) for D in pe.GRID_D] +
              [("time_tail_late", D) for D in pe.GRID_D] +
              [("time_tail_early", D) for D in pe.GRID_D] +
              [("id_swap_adjacent", "-"), ("id_splice_foreign", "random"), ("id_splice_foreign", "nearest"),
               ("delete_response", "-"), ("delete_pair", "-"), ("insert_pair_consistent", "-"),
               ("insert_pair_squeezed", "-")])
MIN_RATE = (30, 5)
NOT_BLIND = "NOT_BLIND (D6: Track B and the builders read request-id deltas / gap quantiles over the full corpora)"
T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:7.1f}s]", *a, flush=True)


# ===================================================================================================== small helpers
def wil(k, n):
    p, lo, hi = stats.wilson(int(k), int(n))
    return {"k": int(k), "n": int(n), "p": p, "lo": lo, "hi": hi}


def crate(flags, sids):
    if len(flags) == 0:
        return {"rate": None, "lo": None, "hi": None, "n_sessions": 0, "num": 0.0, "den": 0.0}
    return pe.rate_by_session(np.asarray(flags, dtype=bool), np.asarray(sids))


def bar_hi(r):
    if r.get("rate") is None:
        return None
    if r["num"] == 0:
        return r.get("wilson_hi_per_event")
    return r["hi"]


def honest_leg(r):
    if r is None or r.get("rate") is None:
        return None
    hi = bar_hi(r)
    if r["rate"] <= 0.05 and hi is not None and hi <= 0.10:
        return "ALIVE"
    if r["rate"] <= 0.20:
        return "WEAK"
    return "DEAD"


def rate_ok(n, ns, mins=MIN_RATE):
    return n >= mins[0] and ns >= mins[1]


def qd(v, sids=None, qs=(0.05, 0.25, 0.5, 0.75, 0.95)):
    v = np.asarray(v, dtype=float)
    ok = np.isfinite(v)
    out = {"n": int(ok.sum())}
    if sids is not None:
        out["n_sessions"] = int(len(set(np.asarray(sids, dtype=object)[ok])))
    if ok.any():
        for q in qs:
            out[f"q{q:g}"] = float(np.quantile(v[ok], q))
        out["min"], out["max"] = float(v[ok].min()), float(v[ok].max())
    return out


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if not np.isfinite(f) else f
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, set):
        return sorted(clean(v) for v in o)
    if o is pd.NA:
        return None
    return o


def cell(label, deciding, n, sessions, ci, path, **kw):
    d = {"label": label, "deciding_number": deciding, "n": n, "sessions": sessions, "ci": ci, "json_path": path}
    d.update(kw)
    return d


# ===================================================================================================== loading
def exclusions(corpus):
    p = pe.OUT_E / "newcorp_exclusions.json"
    ex = json.loads(p.read_text(encoding="utf-8"))
    ent = ex.get(corpus, {})
    return {"B": set(ent.get("B", [])), "E": set(ent.get("E", []))}, pe.sha256_file(p)


def load_split(corpus, split, excl):
    df = pe.read_cache(corpus, split, COLS)
    n0 = df.session_id.nunique()
    if excl[split]:
        df = df[~df.session_id.isin(excl[split])]
    fr = pc.unit_frames(corpus, df)
    assert list(fr) == [corpus], list(fr)
    u = fr[corpus].reset_index(drop=True)
    return u, {"sessions_in_cache": int(n0), "excluded_D5": int(n0 - u.session_id.nunique()),
               "sessions": int(u.session_id.nunique()), "rows": int(len(u))}


def slim_text(u):
    """Bracket working frame: truncation flag on full text, then text cut to 200 chars (choice 1)."""
    v = u[["session_id", "stratum", "seq", "kind", "ts", "tool", "tool_raw", "request_id", "is_subagent", "agent_id",
           "uuid", "call_id", "parent_call_id", "model", "text", "extra"]].copy()
    is_res = (v.kind == "result").to_numpy()
    tr = np.zeros(len(v), dtype=bool)
    txt = v.text.astype(object).to_numpy()
    ex = v.extra.astype(object).to_numpy()
    for i in np.flatnonzero(is_res):
        tr[i] = pe.truncated_result(txt[i], ex[i])
    v["_trunc"] = tr
    v["text"] = [t[:200] if isinstance(t, str) else None for t in txt]
    v["_st"] = pe._stream(v.is_subagent, v.agent_id)
    return v


# ===================================================================================================== R1 detector core
def _k(x):
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return int(f) if np.isfinite(f) else None


def recs(S):
    out = []
    for r in S.to_dict("records"):
        r["k_L"], r["k_U"] = _k(r.get("k_L")), _k(r.get("k_U"))
        out.append(r)
    return out


def stream_rows(R):
    return {(s, st): g for (s, st), g in R.groupby(["session_id", "stream"], sort=False)}


def cats_full(row, Rg, u_sess, copied):
    return set(pe.bracket_benign_categories(u_sess, Rg, row, copied))


def cats_one(row, Rg, u_sess, copied, k, which):
    r = {"session_id": row["session_id"], "stream": row["stream"], "k_L": k if which == "L" else None,
         "k_U": k if which == "U" else None}
    return set(pe.bracket_benign_categories(u_sess, Rg, r, copied))


def stream_status(row, Rg, u_sess, copied, corr, cats0):
    if not (np.isfinite(row["gap"]) and row["gap"] > TOL):
        return "ok"
    cats = cats0
    drop = corr & DROP_CATS
    if drop and (cats & drop):
        Rcur, rcur = Rg, row
        for _ in range(len(Rg)):
            bad = set()
            if rcur["k_L"] is not None and (cats_one(rcur, Rcur, u_sess, copied, rcur["k_L"], "L") & drop):
                bad.add(rcur["k_L"])
            if rcur["k_U"] is not None and (cats_one(rcur, Rcur, u_sess, copied, rcur["k_U"], "U") & drop):
                bad.add(rcur["k_U"])
            if not bad:
                break
            Rcur = Rcur.drop(index=list(bad))
            if len(Rcur) < 2:
                return "abstain"
            rcur = recs(pe.bracket_streams(Rcur))[0]
            if not (np.isfinite(rcur["gap"]) and rcur["gap"] > TOL):
                return "ok"
        if Rcur is not Rg:
            Rg, row = Rcur, rcur
            cats = cats_full(row, Rg, u_sess, copied)
    if "clock_step" in corr and pe.piecewise_consistent(Rg.lo.to_numpy(), Rg.hi.to_numpy()):
        return "ok"
    if corr & cats & TOL_CATS and not row["gap"] > TOL_CORR:
        return "ok"
    if "concurrent_streams" in corr and "concurrent_streams" in cats:
        return "abstain"
    return "flag"


class Variant:
    def __init__(self, R, u_by_s, copied):
        self.R = R
        self.S = pe.bracket_streams(R) if len(R) else pd.DataFrame(columns=["session_id", "stream", "n", "L", "U",
                                                                            "gap", "inconsistent", "k_L", "k_U"])
        self.groups = stream_rows(R) if len(R) else {}
        self.cats = {}
        if len(self.S):
            over = self.S[np.isfinite(self.S.gap.astype(float)) & (self.S.gap.astype(float) > TOL)]
            for row in recs(over):
                key = (row["session_id"], row["stream"])
                self.cats[key] = cats_full(row, self.groups[key], u_by_s[row["session_id"]], copied)

    def status(self, corr, u_by_s, copied):
        out = []
        for row in recs(self.S):
            key = (row["session_id"], row["stream"])
            if key not in self.cats:
                out.append("ok")
            else:
                out.append(stream_status(row, self.groups[key], u_by_s[row["session_id"]], copied, corr,
                                         self.cats[key]))
        return np.array(out, dtype=object)


def dedupe(R, keep):
    rid = R.request_id.astype(object)
    holder = rid.map(keep)
    drop = holder.notna() & (R.session_id != holder)
    return R[~drop.to_numpy()]


def summarize_status(st, sids):
    st = np.asarray(st, dtype=object)
    flags = st == "flag"
    return {"streams": int(len(st)), "flagged": int(flags.sum()), "abstained": int((st == "abstain").sum()),
            "rate_by_session": crate(flags, sids), "wilson_per_stream": wil(flags.sum(), len(st))}


def copied_ids(frames):
    """Request ids present in more than one session of the readable corpus (B u E) and the smallest holder."""
    parts = [f[f.request_id.notna()][["session_id", "request_id"]].drop_duplicates() for f in frames.values()]
    d = pd.concat(parts, ignore_index=True).drop_duplicates()
    ns = d.groupby("request_id").session_id.nunique()
    cop = set(ns[ns > 1].index)
    keep = d[d.request_id.isin(cop)].groupby("request_id").session_id.min().to_dict()
    within = {sp: int((f[f.request_id.notna()].groupby("request_id").session_id.nunique() > 1).sum())
              for sp, f in frames.items()}
    return cop, keep, {"copied_ids_readable_corpus": len(cop), "copied_ids_within_split": within,
                       "readable_corpus": "+".join(frames)}


# ===================================================================================================== R1 tamper (stream level)
def _ev_stream(s, sid, st):
    R2 = pe.bracket_responses(s)
    R2 = R2[R2.stream == st]
    if len(R2) < 2:
        return "abstain"
    S2 = pe.bracket_streams(R2)
    row = S2[(S2.session_id == sid) & (S2.stream == st)]
    if not len(row):
        return "abstain"
    return "flag" if bool(row.inconsistent.iloc[0]) else "ok"


def _pick_other(rng, sessions, sid):
    n = len(sessions)
    if n == 0:
        return None
    for _ in range(10_000):
        j = int(rng.integers(0, n))
        if sessions[j] != sid:
            return j
    return None


def donor_pool(u):
    v = u[SLIM].copy()
    v["_ms"] = pe._ms(v.ts)
    v = v.sort_values(["session_id", "seq"])
    v["_prev_ms"] = v.groupby("session_id")._ms.shift(1)
    main = ~v.is_subagent.astype("boolean").fillna(False).to_numpy()
    c = v[(v.kind == "call").to_numpy() & main & v.call_id.notna().to_numpy()].drop_duplicates(["session_id", "call_id"])
    r = v[(v.kind == "result").to_numpy() & main & v.call_id.notna().to_numpy()].drop_duplicates(["session_id", "call_id"])
    m = c.reset_index().merge(r.reset_index()[["index", "session_id", "call_id", "_ms", "seq"]],
                              on=["session_id", "call_id"], suffixes=("", "_r"))
    m["lat"] = (m["_ms_r"] - m["_ms"]) / 1000.0
    m["gap"] = (m["_ms"] - m["_prev_ms"]) / 1000.0
    m = m[np.isfinite(m.lat) & np.isfinite(m.gap) & (m.lat >= 0) & (m.gap >= 0) & (m.seq_r > m.seq)]
    dc = u.loc[m["index"].to_numpy(), SLIM].reset_index(drop=True)
    dr = u.loc[m["index_r"].to_numpy(), SLIM].reset_index(drop=True)
    return (dc, dr, m.gap.to_numpy(), m.lat.to_numpy(), m.session_id.to_numpy()), {
        "pairs": int(len(m)), "sessions": int(m.session_id.nunique()), "gap_plus_lat_s": qd((m.gap + m.lat).to_numpy())}


def tamper_stream(sid, st, s, splice, pre):
    out = []
    R0 = pe.bracket_responses(s)
    R0 = R0[R0.stream == st].sort_values("seq")
    if len(R0) < 2:
        return [(a, p, "ineligible", None) for a, p in R1_ATTACKS], None
    S0 = pe.bracket_streams(R0)
    honest = bool(S0.inconsistent.iloc[0])
    seq2idx = dict(zip(s.seq.to_numpy(), s.index.to_numpy()))
    first_idx = [seq2idx[q] for q in R0.seq.to_numpy()]
    embs = R0.emb.to_numpy(dtype=float)
    results = list(s.index[(s.kind == "result").to_numpy() & s.ts.notna().to_numpy()])
    res_cids = set(s.loc[s.kind == "result", "call_id"].dropna())
    calls = list(s.index[(s.kind == "call").to_numpy() & s.call_id.isin(res_cids).to_numpy()])
    sp_sess, sp_ids, sp_emb = splice
    other = sp_sess != sid
    is_sub = st != "main"
    for attack, param in R1_ATTACKS:
        rng = pe.rng_for(attack, param, sid, st)
        extra = None
        try:
            if attack.startswith("time_response"):
                i = int(rng.integers(0, len(first_idx)))
                s2, _ = pe.atk_time(s, first_idx[i], float(param), attack[len("time_"):])
            elif attack.startswith("time_result") or attack.startswith("time_tail"):
                if not results:
                    out.append((attack, param, "ineligible", None))
                    continue
                i = int(rng.integers(0, len(results)))
                s2, info = pe.atk_time(s, results[i], float(param), attack[len("time_"):])
                extra = {"clamped": bool(info.get("clamped"))}
            elif attack == "id_swap_adjacent":
                i = int(rng.integers(0, len(first_idx) - 1))
                s2 = pe.atk_id_swap(s, first_idx[i], first_idx[i + 1])
            elif attack == "id_splice_foreign":
                i = int(rng.integers(0, len(first_idx)))
                if param == "random":
                    j = pre.get(("splice", "random"))
                else:
                    drng = pe.rng_for("donor", attack, param, sid, st)
                    d = np.abs(sp_emb - embs[i])
                    d[~other] = np.inf
                    cand = np.flatnonzero(d == d.min()) if np.isfinite(d.min()) else []
                    j = int(cand[int(drng.integers(0, len(cand)))]) if len(cand) else None
                if j is None:
                    out.append((attack, param, "ineligible", None))
                    continue
                extra = {"donor_offset_ms": float(sp_emb[j] - embs[i])}
                s2 = pe.atk_id_splice(s, first_idx[i], sp_ids[j])
            elif attack == "delete_response":
                i = int(rng.integers(0, len(first_idx)))
                s2 = pe.atk_delete_response(s, first_idx[i])
            elif attack == "delete_pair":
                if not calls:
                    out.append((attack, param, "ineligible", None))
                    continue
                i = int(rng.integers(0, len(calls)))
                s2 = pe.atk_delete_pair(s, calls[i])
            elif attack.startswith("insert_pair"):
                if not results:
                    out.append((attack, param, "ineligible", None))
                    continue
                i = int(rng.integers(0, len(results)))
                dn = pre.get(("insert", attack))
                if dn is None:
                    out.append((attack, param, "ineligible", None))
                    continue
                c, r, dgap, dlat = dn[0].copy(), dn[1].copy(), dn[2], dn[3]
                for x in (c, r):
                    x["is_subagent"] = is_sub
                    x["agent_id"] = st if is_sub and st != "?" else None
                mode = "consistent" if attack.endswith("consistent") else "squeezed"
                s2 = pe.atk_insert_pair(s, results[i], c, r, mode=mode, donor_gap_s=float(dgap), donor_lat_s=float(dlat))
                extra = {"shift_s": float(dgap + dlat)} if mode == "consistent" else None
                if s2 is None:
                    out.append((attack, param, "skipped", None))
                    continue
            else:
                raise ValueError(attack)
            out.append((attack, param, _ev_stream(s2, sid, st), extra))
        except Exception as e:  # recorded, never silently dropped
            out.append((attack, param, "error", {"error": repr(e)[:200]}))
    return out, honest


def run_tamper_streams(u, R, S):
    splice_df = R[["session_id", "request_id", "emb"]].sort_values("emb")
    splice = (splice_df.session_id.to_numpy(dtype=object), splice_df.request_id.to_numpy(dtype=object),
              splice_df.emb.to_numpy(dtype=float))
    (dc, dr, dgap, dlat, dsess), dinfo = donor_pool(u)
    v = u[SLIM + ["_st"]].copy()
    v["ts"] = pd.Series([t if isinstance(t, str) else None for t in v.ts.astype(object)], index=v.index, dtype=object)
    by = {k: g for k, g in v.groupby(["session_id", "_st"], sort=False)}
    res = []
    for s, st in zip(S.session_id, S.stream):
        pre = {("splice", "random"): _pick_other(pe.rng_for("donor", "id_splice_foreign", "random", s, st), splice[0], s)}
        for att in ("insert_pair_consistent", "insert_pair_squeezed"):
            j = _pick_other(pe.rng_for("donor", att, "-", s, st), dsess, s) if len(dsess) else None
            pre[("insert", att)] = None if j is None else (dc.iloc[j], dr.iloc[j], float(dgap[j]), float(dlat[j]))
        rows, honest = tamper_stream(s, st, by[(s, st)].drop(columns="_st"), splice, pre)
        res.append((s, st, honest, rows))
    return res, dinfo


def tamper_cells(res, honest_by_key, honest_bar, honest_rate, honest_wilson_hi=None):
    rows = defaultdict(list)
    agree = Counter()
    for sid, st, h, rr in res:
        if h is not None:
            agree["match" if h == honest_by_key[(sid, st)] else "mismatch"] += 1
        for a, p, status, extra in rr:
            rows[(a, p)].append((sid, st, status, extra))
    cells = {}
    for (a, p), lst in rows.items():
        st_ = np.array([x[2] for x in lst], dtype=object)
        elig = np.isin(st_, ["flag", "ok", "abstain"])
        sids = np.array([x[0] for x in lst], dtype=object)[elig]
        flags = (st_ == "flag")[elig]
        hon = np.array([honest_by_key[(x[0], x[1])] for x in lst], dtype=bool)[elig]
        r = crate(flags, sids)
        rh = crate(hon, sids)
        c = {"attack": a, "param": p, "eligible_streams": int(elig.sum()), "eligible_sessions": int(len(set(sids))),
             "flagged": int(flags.sum()), "abstained": int((st_ == "abstain").sum()),
             "ineligible": int((st_ == "ineligible").sum()), "skipped": int((st_ == "skipped").sum()),
             "errors": int((st_ == "error").sum()), "rate_by_session": r, "wilson_per_stream": wil(flags.sum(), elig.sum()),
             "honest_same_streams_rate_by_session": rh, "honest_bar_hi": honest_bar, "honest_rate": honest_rate,
             "clears_honest_bar": bool(r.get("lo") is not None and honest_bar is not None and r["lo"] > honest_bar),
             "clears_wilson_bar_sensitivity": (bool(r.get("lo") is not None and r["lo"] > honest_wilson_hi)
                                               if honest_wilson_hi is not None else None),
             "back_dating_type": a in BACKDATE_TYPES, "single_call_type": a in SINGLE_CALL,
             "min_n_met": rate_ok(int(elig.sum()), int(len(set(sids))))}
        ex = [x[3] for x in lst if x[3]]
        if a == "time_result_early":
            c["clamped"] = int(sum(1 for e in ex if e.get("clamped")))
        if a == "id_splice_foreign":
            offs = np.array([e["donor_offset_ms"] for e in ex if "donor_offset_ms" in e], dtype=float)
            c["donor_offset_ms"] = qd(offs)
            c["donor_offset_abs_gt_1day"] = int((np.abs(offs) > 86_400_000).sum())
            c["donor_offset_abs_le_tol"] = int((np.abs(offs) <= TOL).sum())
        errs = [e.get("error") for e in ex if isinstance(e, dict) and "error" in e]
        if errs:
            c["error_examples"] = sorted(set(errs))[:3]
        cells[f"{a}|{p}"] = c
    return cells, dict(agree)


# ===================================================================================================== R1 N7 (session level)
def session_targets(s, attack, info):
    R = info["responses"]
    if attack in ("time_response_early", "time_response_late", "delete_response"):
        return [int(x) for x in R.idx] if R is not None else []
    if attack == "id_swap_adjacent":
        t = []
        if R is not None:
            d = R[np.isfinite(R.emb.to_numpy())].sort_values("seq")
            for _, g in d.groupby("stream", sort=True):
                ix = g.idx.tolist()
                t += [(int(ix[i]), int(ix[i + 1])) for i in range(len(ix) - 1)]
        return t
    if attack == "id_splice_foreign":
        return [int(x) for x in R.idx[np.isfinite(R.emb.to_numpy())]] if R is not None else []
    P = info["pairs"]
    if P is None:
        return []
    if attack == "time_result_early":
        return [int(x) for x in P.ri[P.qualified.to_numpy()]]
    if attack in ("time_result_late", "time_tail_late", "time_tail_early"):
        return [int(x) for x in P.ri[np.isfinite(P.delta_s.to_numpy())]]
    if attack == "delete_pair":
        return [int(x) for x in P.ci]
    if attack in ("insert_pair_consistent", "insert_pair_squeezed"):
        m = P.main.to_numpy() & np.isfinite(P.res_ms.to_numpy())
        if attack == "insert_pair_squeezed":
            m &= P.has_next.to_numpy() & (np.nan_to_num(P.next_gap_s.to_numpy(), nan=-1) >= 0.002)
        return [int(x) for x in P.ri[m]]
    return []


def session_info(s):
    """Per-session target tables (the n7_timing session_info subset R1 needs; pairs via the D1 proxy unit)."""
    info = {"pairs": None, "responses": None}
    P = pc.make_pairs(s[s.kind.isin(["call", "result"])])
    if len(P):
        Q = pe.qualify_pairs(PROXY, s, P)
        calls = s[s.kind == "call"].sort_values("seq").drop_duplicates("call_id")
        resr = s[(s.kind == "result") & s.call_id.notna()].sort_values("seq").drop_duplicates("call_id")
        cidx = dict(zip(calls.call_id.astype(str), calls.index))
        ridx = dict(zip(resr.call_id.astype(str), resr.index))
        ms = pe._ms(s.ts)
        pos = {ix: i for i, ix in enumerate(s.index)}
        prev_ms = np.full(len(s), np.nan)
        last = np.nan
        for i in range(len(s)):
            prev_ms[i] = last
            if np.isfinite(ms[i]):
                last = ms[i]
        next_ms = np.r_[ms[1:], np.nan]
        cid = Q.call_id.astype(str).to_numpy()
        ci = np.array([cidx.get(c, -1) for c in cid])
        ri = np.array([ridx.get(c, -1) for c in cid])
        isub = Q.is_subagent.astype("boolean").fillna(False).to_numpy(dtype=bool)
        rows = pd.DataFrame({
            "cid": cid, "ci": ci, "ri": ri, "seq": Q.seq.to_numpy(), "delta_s": Q.delta_s.to_numpy(dtype=float),
            "qualified": Q.qualified.to_numpy(dtype=bool), "main": ~isub, "nested": Q.parent_call_id.notna().to_numpy(),
            "res_ms": [ms[pos[x]] if x in pos else np.nan for x in ri],
            "call_gap_s": [(ms[pos[x]] - prev_ms[pos[x]]) / 1000.0 if x in pos else np.nan for x in ci],
            "next_gap_s": [(next_ms[pos[x]] - ms[pos[x]]) / 1000.0 if x in pos else np.nan for x in ri],
            "has_next": [pos[x] + 1 < len(s) if x in pos else False for x in ri]})
        info["pairs"] = rows[(rows.ci >= 0) & (rows.ri >= 0)].sort_values("seq").reset_index(drop=True)
    rid = s[s.request_id.notna()].sort_values("seq").drop_duplicates("request_id")
    if len(rid):
        emb = [pe.decode_req_ms(x) for x in rid.request_id.astype(object)]
        info["responses"] = pd.DataFrame({
            "idx": rid.index.to_numpy(), "seq": rid.seq.to_numpy(), "request_id": rid.request_id.astype(str).to_numpy(),
            "emb": np.array([np.nan if e is None else e for e in emb], dtype=float),
            "stream": pe._stream(rid.is_subagent, rid.agent_id)})
    return info


def r1_session_eval(s):
    """(decided, flagged, n_streams, flagged_streams)."""
    if not s.request_id.notna().any():
        return False, False, 0, set()
    R = pe.bracket_responses(s)
    if not len(R):
        return False, False, 0, set()
    S = pe.bracket_streams(R)
    if not len(S):
        return False, False, 0, set()
    fl = set(S.stream[S.inconsistent.to_numpy()].astype(str))
    return True, bool(fl), int(len(S)), fl


def n7_r1(u, split_label):
    """Session-level N7 cells for R1_BRACKET (choice 5)."""
    v = u[COLS].copy()
    v["ts"] = pd.Series([t if isinstance(t, str) else None for t in v.ts.astype(object)], index=v.index, dtype=object)
    sess = {s: g for s, g in v.groupby("session_id", sort=False)}
    order = list(sess)
    perm = pe.rng_for("N7", "pubcc", split_label).permutation(len(order))
    order = [sorted(order)[i] for i in perm]
    info = {s: session_info(sess[s]) for s in order}
    honest = {s: r1_session_eval(sess[s]) for s in order}
    rp = []
    for s in order:
        R = info[s]["responses"]
        if R is not None:
            rp.append(R.assign(session_id=s))
    rp = pd.concat(rp, ignore_index=True) if rp else pd.DataFrame(columns=["session_id", "request_id", "emb"])
    # insert donors: main, not nested, delta > 0, call gap >= 0 pairs of the split
    don = []
    for s in order:
        P = info[s]["pairs"]
        if P is None:
            continue
        m = (P.main.to_numpy() & ~P.nested.to_numpy() & np.isfinite(P.delta_s.to_numpy()) & (P.delta_s.to_numpy() > 0)
             & (np.nan_to_num(P.call_gap_s.to_numpy(), nan=-1) >= 0))
        don.append(P[m].assign(session_id=s))
    don = pd.concat(don, ignore_index=True) if don else pd.DataFrame()
    cells = {}
    for attack, param in R1_ATTACKS:
        elig = [s for s in order if session_targets(sess[s], attack, info[s])]
        if attack == "id_splice_foreign":
            elig = [s for s in elig if (rp.session_id != s).any()]
        if attack.startswith("insert_pair"):
            elig = [s for s in elig if len(don) and (don.session_id != s).any()]
        sel = elig[:pe.N7_CAP_SESSIONS]
        per, fails = [], Counter()
        for sid in sel:
            tg = session_targets(sess[sid], attack, info[sid])
            rng = pe.rng_for(attack, param, sid)
            target = tg[int(rng.integers(0, len(tg)))]
            drng = pe.rng_for("donor", attack, param, sid)
            s = sess[sid]
            try:
                if attack.startswith("time_"):
                    s2, _ = pe.atk_time(s, target, float(param), attack[len("time_"):])
                elif attack == "id_swap_adjacent":
                    s2 = pe.atk_id_swap(s, target[0], target[1])
                elif attack == "id_splice_foreign":
                    own = set(s.request_id.dropna().astype(str))
                    cand = rp[(rp.session_id != sid) & np.isfinite(rp.emb.to_numpy()) & ~rp.request_id.isin(list(own)).to_numpy()]
                    if not len(cand):
                        fails["no_donor_id"] += 1
                        continue
                    if param == "random":
                        j = int(drng.integers(0, len(cand)))
                    else:
                        te = pe.decode_req_ms(s.at[target, "request_id"])
                        diff = np.abs(cand.emb.to_numpy() - te)
                        best = np.flatnonzero(diff == diff.min())
                        j = int(best[int(drng.integers(0, len(best)))])
                    s2 = pe.atk_id_splice(s, target, cand.request_id.iloc[j])
                elif attack == "delete_response":
                    s2 = pe.atk_delete_response(s, target)
                elif attack == "delete_pair":
                    s2 = pe.atk_delete_pair(s, target)
                else:
                    d0 = don[don.session_id != sid]
                    j = int(drng.integers(0, len(d0)))
                    d = d0.iloc[j]
                    dsess = sess[d.session_id]
                    dc, dr = dsess.loc[int(d.ci)].copy(), dsess.loc[int(d.ri)].copy()
                    mode = "consistent" if attack == "insert_pair_consistent" else "squeezed"
                    s2 = pe.atk_insert_pair(s, target, dc, dr, mode=mode, donor_gap_s=float(d.call_gap_s),
                                            donor_lat_s=float(d.delta_s))
                    if s2 is None:
                        fails["gap_below_2ms_or_unparseable"] += 1
                        continue
            except Exception as ex:
                fails[f"injector_exception:{type(ex).__name__}"] += 1
                continue
            per.append((honest[sid], r1_session_eval(s2)))
        n_t = len(per)
        kt = sum(1 for h, t in per if t[1])
        kh = sum(1 for h, t in per if h[1])
        lab, _ = pe.n7_cell_label(n_t, kt, n_t, kh)
        row = {"attack": attack, "param": str(param), "label": lab, "n_eligible_sessions": len(elig),
               "n_selected": len(sel), "n_tampered": n_t, "injection_failures": dict(fails), "recall": wil(kt, n_t),
               "fpr": wil(kh, n_t), "n_decided_tampered": sum(1 for h, t in per if t[0]),
               "n_decided_honest": sum(1 for h, t in per if h[0]), "single_call_type": attack in SINGLE_CALL}
        if n_t:
            ind = [int(t[1] and not h[1]) for h, t in per]
            row["adr"] = pe.boot_stat(ind, lambda g: float(np.mean(g)) if len(g) else None)
        cells[f"{attack}|{param}"] = row
    return cells, {s: honest[s] for s in order}


def n7_leg(cells_E):
    single_det = sorted({c["attack"] for c in cells_E.values() if c["label"] == "DETECTS" and c["single_call_type"]})
    any_dp = sorted({c["attack"] for c in cells_E.values() if c["label"] in ("DETECTS", "PARTIAL")})
    tested = [c for c in cells_E.values() if c["label"] != "INSUFFICIENT_N"]
    if single_det:
        leg = "DETECTS"
    elif any_dp:
        leg = "PARTIAL"
    elif tested:
        leg = "BLIND"
    else:
        leg = "INSUFFICIENT_N"
    return {"leg": leg, "single_call_types_detecting": single_det, "attack_types_detects_or_partial": any_dp,
            "cells_tested": len(tested), "cells_total": len(cells_E)}


# ===================================================================================================== R1 blocks
def honest_block(R, S):
    if not len(S):
        return {"responses_decoded": int(len(R)), "streams_ge2": 0, "inconsistent_streams": 0}
    inc = S.inconsistent.to_numpy(dtype=bool)
    cons = S[~inc]
    return {"responses_decoded": int(len(R)), "sessions_with_decoded_responses": int(R.session_id.nunique()),
            "streams_ge2": int(len(S)), "streams_main": int((S.stream == "main").sum()),
            "sessions_with_streams": int(S.session_id.nunique()), "inconsistent_streams": int(inc.sum()),
            "inconsistent_streams_main": int((inc & (S.stream == "main").to_numpy()).sum()),
            "rate_by_session": crate(inc, S.session_id.to_numpy()), "wilson_per_stream": wil(inc.sum(), len(S)),
            "min_n_met": rate_ok(len(S), S.session_id.nunique()),
            "sessions_with_inconsistent_stream": int(S[inc].session_id.nunique()),
            "tolerance_sensitivity_streams_over": {f"{t}": int((np.isfinite(S.gap.astype(float)) & (S.gap.astype(float) > t)).sum())
                                                   for t in (0, 1000, 2000, 3000, 5000, 10000, 60000)},
            "gap_L_minus_U_ms_all_streams": qd(S.gap.to_numpy(dtype=float), S.session_id.to_numpy()),
            "slack_U_minus_L_consistent_ms": qd((cons.U - cons.L).to_numpy(dtype=float), cons.session_id.to_numpy()),
            "slack_p50_cluster": (stats.cluster_quantile((cons.U - cons.L).to_numpy(dtype=float),
                                                         cons.session_id.to_numpy(), 0.5) if len(cons) else None),
            "streams_with_nan_L": int((~np.isfinite(S.L.astype(float))).sum())}


def placebo_block(R):
    out = {}
    for kind, D in PLACEBO:
        SP = pe.bracket_streams(pe.placebo_shift(R, D if kind == "back" else -D))
        f = SP.inconsistent.to_numpy(dtype=bool) if len(SP) else np.array([], dtype=bool)
        out[f"{kind}_{D // 1000}s"] = {"streams": int(len(SP)), "flagged": int(f.sum()),
                                       "share": float(f.mean()) if len(f) else None,
                                       "wilson_per_stream": wil(f.sum(), len(SP)),
                                       "rate_by_session": crate(f, SP.session_id.to_numpy() if len(SP) else [])}
    SR = pe.bracket_streams(pe.roll_ids(R))
    f = SR.inconsistent.to_numpy(dtype=bool) if len(SR) else np.array([], dtype=bool)
    out["roll_ids_reference"] = {"streams": int(len(SR)), "flagged": int(f.sum()), "wilson_per_stream": wil(f.sum(), len(SR)),
                                 "rate_by_session": crate(f, SR.session_id.to_numpy() if len(SR) else [])}
    return out


# ----------------------------------------------------------------------------------------------------- AC1 raw audit
def corpus_index(corpus):
    p = pe.CACHE / f"{corpus}_index.json"
    return json.loads(p.read_text(encoding="utf-8")), pe.sha256_file(p)


def raw_entries(corpus, idx, session_id, want):
    """uuid -> list of (timestamp, requestId) over the session's raw files (B/E index entries only)."""
    ent = idx["sessions"].get(session_id)
    if ent is None:
        return None
    assert ent["split"] in ("B", "E"), "AC1 reads B/E raw files only"
    root = Path(idx["corpus_root"])
    out = defaultdict(list)
    for role, rel, member in ent["files"]:
        p = root / rel
        if not p.exists():
            continue
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    x = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(x, dict):
                    continue
                uid = x.get("uuid")
                if uid in want:
                    out[uid].append((x.get("timestamp"), x.get("requestId")))
    return out


def ms_of(ts):
    t = parse_ts(ts) if isinstance(ts, str) else None
    return None if t is None else t.timestamp() * 1000.0


def ac1_audit(corpus, idx, inc_rows, groups, u_by_s):
    keys = [(r["session_id"], r["stream"]) for r in inc_rows]
    pick = set(pe.audit_sample(keys, seed_parts=("audit", "R1", corpus)))
    n, diff, notes = 0, 0, Counter()
    for r in inc_rows:
        if (r["session_id"], r["stream"]) not in pick:
            continue
        n += 1
        g = groups[(r["session_id"], r["stream"])]
        ev = u_by_s[r["session_id"]].set_index("seq", drop=False)
        want, binds = set(), []
        for name in ("k_L", "k_U"):
            k = r[name]
            if k is None:
                continue
            rr = g.loc[k]
            for seqv, which in ((_k(rr["seq"]), "first"), (_k(rr.get("prev_seq")), "prev")):
                if seqv is None or seqv not in ev.index:
                    continue
                e = ev.loc[seqv]
                if isinstance(e["uuid"], str):
                    want.add(e["uuid"])
                    binds.append((which, e, rr))
        raw = raw_entries(corpus, idx, r["session_id"], want)
        if raw is None:
            diff += 1
            notes["raw_session_missing"] += 1
            continue
        bad = False
        for which, e, rr in binds:
            occ = raw.get(e["uuid"], [])
            if not occ:
                notes[f"{which}_uuid_not_found"] += 1
                continue
            if len({o[0] for o in occ}) > 1:
                notes[f"{which}_uuid_with_several_raw_stamps"] += 1
            a = ms_of(e["ts"])
            if not any(ms_of(o[0]) is not None and a is not None and abs(ms_of(o[0]) - a) < 1.0 for o in occ):
                bad = True
                notes[f"{which}_ts_differs"] += 1
            if which == "first" and not any(o[1] == rr["request_id"] for o in occ):
                bad = True
                notes["request_id_differs"] += 1
        diff += int(bad)
    res = "FAIL" if diff >= pe.AUDIT_FAIL else ("PARSER_NOTE" if diff == 1 else ("PASS" if n else "NOT_RUN"))
    return {"audited_streams": n, "streams_with_differences": diff, "notes": dict(notes), "result": res,
            "fields": "binding response first-event stamp + request id, binding input stamp, vs raw entries by uuid "
                      "(any raw occurrence of the uuid may match: resume/copy duplicates are deduplicated by the loader)"}


def inspect_stream(row, Rg, u_sess, copied):
    d = {"session_id": row["session_id"], "stream": row["stream"], "n_responses": int(row["n"]),
         "gap_ms": float(row["gap"]), "categories": sorted(cats_full(row, Rg, u_sess, copied)),
         "piecewise_consistent": bool(pe.piecewise_consistent(Rg.lo.to_numpy(), Rg.hi.to_numpy())),
         "stream_is_main": row["stream"] == "main", "stratum": str(u_sess.stratum.iloc[0])}
    pos = {k: i for i, k in enumerate(Rg.sort_values("seq").index)}
    d["k_L_position"], d["k_U_position"] = pos.get(row["k_L"]), pos.get(row["k_U"])
    ev = u_sess.set_index("seq", drop=False)
    for name in ("k_L", "k_U"):
        k = row[name]
        if k is None:
            continue
        r = Rg.loc[k]
        fs, ps = _k(r["seq"]), _k(r.get("prev_seq"))
        first = ev.loc[fs] if fs in ev.index else None
        prev = ev.loc[ps] if ps is not None and ps in ev.index else None
        d[name] = {"lo_ms": float(r["lo"]) if np.isfinite(r["lo"]) else None, "hi_ms": float(r["hi"]),
                   "input_to_first_event_ms": float(r["first_ms"] - r["prev_ms"]) if np.isfinite(r["prev_ms"]) else None,
                   "prev_kind": r.get("prev_kind") if isinstance(r.get("prev_kind"), str) else None,
                   "first_event_kind": first["kind"] if first is not None else None,
                   "prev_input_tool": (prev["tool"] if isinstance(prev["tool"], str) else None) if prev is not None else None,
                   "first_ts_fraction_digits": len(str(r["ts"]).split(".")[1].rstrip("Z")) if "." in str(r["ts"]) else 0,
                   "model": (first["model"] if first is not None and isinstance(first["model"], str) else None)}
    return d


def categories_block(corpus, split, V, u_by_s, copied):
    S = V.S
    inc = S[S.inconsistent.astype(bool)]
    cons_recs = recs(S[~S.inconsistent.astype(bool)].reset_index(drop=True))
    rng = pe.rng_for("F1ctl", corpus, split)
    n_ctl = min(5 * len(inc), len(cons_recs))
    ctl_idx = sorted(rng.choice(len(cons_recs), size=n_ctl, replace=False).tolist()) if n_ctl else []
    inc_recs = recs(inc)
    inc_c = [V.cats[(r["session_id"], r["stream"])] for r in inc_recs]
    ctl_c = [cats_full(cons_recs[i], V.groups[(cons_recs[i]["session_id"], cons_recs[i]["stream"])],
                       u_by_s[cons_recs[i]["session_id"]], copied) for i in ctl_idx]
    tab = {}
    for c in CATS:
        a = sum(c in x for x in inc_c)
        b = sum(c in x for x in ctl_c)
        sa = a / len(inc_c) if inc_c else None
        sb = b / len(ctl_c) if ctl_c else None
        tab[c] = {"inconsistent_with": int(a), "inconsistent_n": len(inc_c), "share_inconsistent": sa,
                  "controls_with": int(b), "controls_n": len(ctl_c), "share_controls": sb,
                  "enrichment": (sa - sb) if (sa is not None and sb is not None) else None,
                  "shared_benign_cause": bool(sa is not None and sb is not None and sa >= 0.5 and (sa - sb) >= 0.3)}
    vec = Counter("+".join(sorted(x)) if x else "(none)" for x in inc_c)
    return {"control_rule": "5 consistent streams per inconsistent stream, rng_for('F1ctl', corpus, split)",
            "categories": tab, "category_vectors_inconsistent": dict(vec),
            "unexplained_streams_no_category": int(sum(1 for x in inc_c if not x)),
            "shared_benign_causes": sorted(c for c, t in tab.items() if t["shared_benign_cause"]),
            "inconsistent_streams": [inspect_stream(r, V.groups[(r["session_id"], r["stream"])],
                                                    u_by_s[r["session_id"]], copied) for r in inc_recs]}


def corrections_block(V_h, V_h_dd, V_p, V_p_dd, u_by_s, copied):
    base = {"honest": int((V_h.status(set(), u_by_s, copied) == "flag").sum()),
            "back_5s": float((V_p[5000].status(set(), u_by_s, copied) == "flag").mean()) if len(V_p[5000].S) else None,
            "back_30s": float((V_p[30000].status(set(), u_by_s, copied) == "flag").mean()) if len(V_p[30000].S) else None}
    out = {"uncorrected": base, "per_category": {}}
    adopted = []
    for c in CATS:
        corr = {c}
        vh, v5, v30 = (V_h_dd, V_p_dd[5000], V_p_dd[30000]) if c == "restamped_copy" else (V_h, V_p[5000], V_p[30000])
        sh, s5, s30 = (x.status(corr, u_by_s, copied) for x in (vh, v5, v30))
        rec = {"honest_flagged": int((sh == "flag").sum()), "honest_abstained": int((sh == "abstain").sum()),
               "streams": int(len(sh)), "back_5s_power": float((s5 == "flag").mean()) if len(s5) else None,
               "back_30s_power": float((s30 == "flag").mean()) if len(s30) else None}
        rec["lowers_honest"] = rec["honest_flagged"] < base["honest"]
        rec["keeps_30s_power"] = rec["back_30s_power"] is not None and rec["back_30s_power"] >= 0.90
        rec["keeps_5s_power"] = (rec["back_5s_power"] is not None and base["back_5s"] is not None
                                 and abs(rec["back_5s_power"] - base["back_5s"]) <= 0.05)
        rec["ADOPTED"] = bool(rec["lowers_honest"] and rec["keeps_30s_power"] and rec["keeps_5s_power"])
        if rec["ADOPTED"]:
            adopted.append(c)
        out["per_category"][c] = rec
    out["adopted"] = adopted
    return out


def corrected_eval(V_h, V_p, u_by_s, copied, adopted):
    corr = set(adopted)
    out = {"adopted": sorted(corr), "honest": summarize_status(V_h.status(corr, u_by_s, copied), V_h.S.session_id.to_numpy())}
    for D in (5000, 30000):
        out[f"back_{D // 1000}s"] = summarize_status(V_p[D].status(corr, u_by_s, copied), V_p[D].S.session_id.to_numpy())
    return out


def call_seq_map(u):
    c = u[(u.kind == "call").to_numpy() & u.call_id.notna().to_numpy()]
    c = c.sort_values("seq").drop_duplicates(["session_id", "call_id"])
    return {(s, ci): (int(q), rid if isinstance(rid, str) else None)
            for s, ci, q, rid in zip(c.session_id, c.call_id.astype(object), c.seq, c.request_id.astype(object))}


POSTHOC_ORDER = ["restamped_copy", "out_of_order_result", "input_after_response", "client_behind_server",
                 "user_input_binding", "other"]


def posthoc_mechanisms(u, V, cmap):
    """POST HOC, NOT A VERDICT: the descriptor rule Track A wrote after inspecting swechat failures, applied unchanged."""
    rows, counts = [], Counter()
    S = V.S
    for r in recs(S[S.inconsistent.astype(bool)]):
        g = V.groups[(r["session_id"], r["stream"])]
        cats = V.cats[(r["session_id"], r["stream"])]
        u_s = u[u.session_id == r["session_id"]].set_index("seq", drop=False)
        d = {"restamped_copy": "restamped_copy" in cats, "user_input_binding": "user_input_binding" in cats}
        kL, kU = (g.loc[r["k_L"]] if r["k_L"] is not None else None), g.loc[r["k_U"]]
        d["U_hi_ms"] = float(kU["hi"])
        d["client_behind_server"] = bool(kU["hi"] < -TOL)
        d["L_input_after_response"], d["L_input_result_call"] = False, None
        if kL is not None and np.isfinite(kL["prev_ms"]):
            d["L_input_after_response"] = bool(kL["first_ms"] < kL["prev_ms"])
            ps = _k(kL["prev_seq"])
            if kL.get("prev_kind") == "result" and ps in u_s.index:
                ci = u_s.loc[ps, "call_id"]
                cm = cmap.get((r["session_id"], ci)) if isinstance(ci, str) else None
                if cm is None:
                    d["L_input_result_call"] = "call_not_in_session"
                elif cm[0] > ps:
                    d["L_input_result_call"] = ("call_later_same_response" if cm[1] == kL["request_id"]
                                                else "call_later_other_response")
                else:
                    d["L_input_result_call"] = "call_earlier"
        d["out_of_order_result"] = d["L_input_result_call"] in ("call_later_same_response", "call_later_other_response")
        mech = "other"
        for m in POSTHOC_ORDER[:-1]:
            if d.get({"input_after_response": "L_input_after_response"}.get(m, m)):
                mech = m
                break
        d["mechanism"] = mech
        counts[mech] += 1
        d["session_id"], d["stream"] = r["session_id"], r["stream"]
        rows.append(d)
    return {"note": "POST HOC, NOT A VERDICT: Track A's descriptor rule (phase_e_f1_bracket.posthoc_mechanisms), unchanged",
            "counts": dict(counts), "streams": rows}


def posthoc_ordered_inputs(u, cmap):
    """POST HOC, NOT A VERDICT: Track A's 'ordered inputs' recompute (not pre-registered, cannot be adopted)."""
    is_res = (u.kind == "result").to_numpy()
    seqs, sids, cids = u.seq.to_numpy(), u.session_id.to_numpy(), u.call_id.astype(object).to_numpy()
    drop = np.zeros(len(u), dtype=bool)
    for i in np.flatnonzero(is_res):
        cm = cmap.get((sids[i], cids[i])) if isinstance(cids[i], str) else None
        drop[i] = cm is not None and cm[0] > seqs[i]
    R = pe.bracket_responses(u[~drop])
    S = pe.bracket_streams(R)
    out = {"note": "POST HOC, NOT A VERDICT", "results_dropped": int(drop.sum()), "results": int(is_res.sum()),
           "honest": {"streams": int(len(S)), "inconsistent": int(S.inconsistent.sum()) if len(S) else 0,
                      "rate_by_session": crate(S.inconsistent.to_numpy(dtype=bool), S.session_id.to_numpy()) if len(S) else None}}
    for D in (5000, 30000):
        SP = pe.bracket_streams(pe.placebo_shift(R, D))
        out[f"back_{D // 1000}s"] = {"streams": int(len(SP)), "flagged": int(SP.inconsistent.sum()) if len(SP) else 0}
    return out


def synthetic_sensitivity(u):
    """Choice 6: recompute without events whose model is '<synthetic>' (sensitivity, not a verdict)."""
    syn = (u.model.astype(object) == "<synthetic>").to_numpy()
    rid_syn = u[syn & u.request_id.notna().to_numpy()]
    R = pe.bracket_responses(u[~syn])
    S = pe.bracket_streams(R)
    return {"synthetic_events_with_request_id": int(len(rid_syn)),
            "synthetic_request_ids_distinct": int(rid_syn.request_id.nunique()),
            "streams": int(len(S)), "inconsistent": int(S.inconsistent.sum()) if len(S) else 0,
            "rate_by_session": crate(S.inconsistent.to_numpy(dtype=bool), S.session_id.to_numpy()) if len(S) else None}


def strata_block(u, S, SP30, cuts):
    sess = sorted(S.session_id.unique())
    us = u[u.session_id.isin(sess)]
    mm = pe.session_model_map(us)
    rep = pe.session_cluster_map(PROXY, us, kind="repo")  # D2: stratum
    P = pc.make_pairs(us[us.kind.isin(["call", "result"])][["session_id", "seq", "kind", "call_id", "ts"]])
    npairs = P.groupby("session_id").size().to_dict()
    lt = pe.length_tercile_map({s: npairs.get(s, 0) for s in sess}, cuts)
    out = {}
    s_sid, p_sid = S.session_id.to_numpy(), SP30.session_id.to_numpy()
    s_inc, p_inc = S.inconsistent.to_numpy(dtype=bool), SP30.inconsistent.to_numpy(dtype=bool)
    for ax, mp in (("model", mm), ("stratum_D2", rep), ("length_tercile", lt)):
        labels, rec = {}, {}
        s_lab = np.array([str(mp.get(s, "unknown")) for s in s_sid], dtype=object)
        p_lab = np.array([str(mp.get(s, "unknown")) for s in p_sid], dtype=object)
        sz = Counter(s_lab)
        for k in sz:
            m, mp_ = s_lab == k, p_lab == k
            n, ns = int(m.sum()), int(len(set(s_sid[m])))
            if not rate_ok(n, ns):
                labels[k] = None
                rec[k] = {"streams": n, "sessions": ns, "reportable": False, "inconsistent": int(s_inc[m].sum())}
                continue
            rh = crate(s_inc[m], s_sid[m])
            rp = crate(p_inc[mp_], p_sid[mp_])
            clears = rp.get("lo") is not None and bar_hi(rh) is not None and rp["lo"] > bar_hi(rh)
            lab = honest_leg(rh) if clears else "DEAD"
            labels[k] = lab
            rec[k] = {"streams": n, "sessions": ns, "reportable": True, "honest": rh, "back_30s": rp, "label": lab}
        out[ax] = {"strata": rec, "n_strata": len(sz), "n_reportable": sum(1 for v in labels.values() if v),
                   "confinement": pe.confinement(labels)}
    out["tool_key"] = {"confinement": "NOT_APPLICABLE", "reason": "a stream of responses mixes tools"}
    return out


def artifact_checks(u, S, copied_call, base):
    out = {"base_label": base}
    u2 = u[~u._trunc.to_numpy()]
    S2 = pe.bracket_streams(pe.bracket_responses(u2))
    r2 = crate(S2.inconsistent.to_numpy(dtype=bool), S2.session_id.to_numpy())
    out["AC2_truncation"] = {"results_removed": int(u._trunc.sum()), "rate_by_session": r2,
                             "inconsistent": int(S2.inconsistent.sum()), "streams": int(len(S2)),
                             "label": honest_leg(r2), "result": "PASS" if honest_leg(r2) == base else "FAIL"}
    cr = u[u.kind.isin(["call", "result"])][["session_id", "seq", "kind", "call_id", "ts"]]
    P = pc.make_pairs(cr)
    ok = pe.join_clean_mask(cr, P, copied_call)
    clean_keys = set(zip(P.session_id[ok], P.call_id[ok].astype(str)))
    is_res = (u.kind == "result").to_numpy()
    keep_res = np.array([(s, str(c)) in clean_keys for s, c in zip(u.session_id, u.call_id)])
    u3 = u[~is_res | keep_res]
    S3 = pe.bracket_streams(pe.bracket_responses(u3))
    r3 = crate(S3.inconsistent.to_numpy(dtype=bool), S3.session_id.to_numpy())
    out["AC3_join"] = {"results_removed": int((is_res & ~keep_res).sum()), "rate_by_session": r3,
                       "inconsistent": int(S3.inconsistent.sum()), "streams": int(len(S3)),
                       "label": honest_leg(r3), "result": "PASS" if honest_leg(r3) == base else "FAIL"}
    w = S.groupby("session_id").size().to_dict()
    us = u[u.session_id.isin(list(w))]
    clmaps = {"stratum_D2": pe.session_cluster_map(PROXY, us, kind="repo"), "model": pe.session_model_map(us),
              "session": {s: s for s in w}}
    ac4, effect = {}, "pass"
    for name, mp in clmaps.items():
        d = pe.dominance(w, mp)
        if name == "session":
            d["dominated"] = d["top_share_events"] > pe.DOM_SESSION
        rec = {"dominated": d["dominated"], "top_share_streams": d["top_share_events"],
               "top_share_sessions": d["top_share_sessions"], "top_session_share_streams": d["top_session_share_events"],
               "n_clusters": d["n_clusters"], "top_cluster": str(d["top_cluster"]) if name != "session" else None}
        if d["dominated"]:
            leave = []
            for c, _, _ in d["top_clusters"]:
                m = S.session_id.map(lambda s: mp.get(s, "unknown")).to_numpy() != c
                n, ns = int(m.sum()), int(S.session_id[m].nunique())
                if not rate_ok(n, ns):
                    leave.append({"left_out": str(c) if name != "session" else "top session", "label": None,
                                  "below_min_n": True, "streams": n, "sessions": ns})
                    effect = "cap_weak" if effect == "pass" else effect
                    continue
                rr = crate(S.inconsistent.to_numpy(dtype=bool)[m], S.session_id.to_numpy()[m])
                lab = honest_leg(rr)
                leave.append({"left_out": str(c) if name != "session" else "a top session", "label": lab, "streams": n,
                              "sessions": ns, "rate_by_session": rr})
                if pe.LEVEL.get(lab, 0) < pe.LEVEL.get(base, 0):
                    effect = "downgrade"
            rec["leave_outs"] = leave
        ac4[name] = rec
    out["AC4_dominance"] = {"by_cluster": ac4, "effect": effect, "cluster_rule": "D2: stratum; plus model and session"}
    out["AC5_post_strat"] = {"result": "NOT_RUN", "reason": "prereg_e_common.population_cells has no table for new corpora"}
    return out


def r1_verdict(honest_r, back30, back5, other_cells, leg, checks_effects, confined):
    """R1 verdict (prereg a1.proposal_rules + R1_specific), mechanical. leg: n7_leg() dict or None."""
    reasons = []
    if honest_r.get("rate") is None or not rate_ok(int(honest_r.get("den", 0)), int(honest_r.get("n_sessions", 0))):
        return {"label": "INSUFFICIENT_N", "reasons": ["honest streams below 30 from 5 sessions"],
                "honest_streams": int(honest_r.get("den", 0) or 0), "honest_sessions": int(honest_r.get("n_sessions", 0) or 0)}
    hl = honest_leg(honest_r)
    bar = bar_hi(honest_r)
    clears30 = bool(back30["rate_by_session"]["lo"] is not None and bar is not None and back30["rate_by_session"]["lo"] > bar)
    clears5 = bool(back5["rate_by_session"]["lo"] is not None and bar is not None and back5["rate_by_session"]["lo"] > bar)
    others = sorted(k for k, c in other_cells.items() if not c["back_dating_type"] and c["clears_honest_bar"])
    ceiling = "DEAD" if (not clears30 or hl == "DEAD") else ("WEAK" if (not others or hl == "WEAK") else "ALIVE")
    if not clears30:
        reasons.append("30 s back-dating does not clear the honest bar (kill rule)")
    if hl == "DEAD":
        reasons.append("honest flag rate > 0.20")
    if ceiling != "DEAD" and not others:
        reasons.append("back-dating only: no other single-call/single-response type clears the honest bar")
    lg = leg["leg"] if leg else None
    if ceiling == "DEAD":
        label = "DEAD"
    elif lg is None:
        label = "PENDING_N7"
    elif lg == "INSUFFICIENT_N":
        label = "INSUFFICIENT_N"
        reasons.append("N7 leg: no R1 cell reaches 30 tampered sessions")
    elif lg == "DETECTS" and ceiling == "ALIVE" and hl == "ALIVE":
        label = "ALIVE"
    elif lg in ("DETECTS", "PARTIAL"):
        label = "WEAK"
    else:
        label = "DEAD"
        reasons.append("no N7 attack type DETECTS or PARTIAL")
    if label in pe.LEVEL:
        for eff in checks_effects:
            if eff == "downgrade" and label != "DEAD":
                label = pe.downgrade(label)
                reasons.append("artifact check downgrade")
            elif eff == "cap_weak" and label == "ALIVE":
                label = "WEAK"
                reasons.append("artifact check cap at WEAK")
        if confined and label != "DEAD":
            label = pe.downgrade(label)
            reasons.append("CONFINED to one stratum")
    return {"label": label, "honest_leg": hl, "honest_bar_hi": bar, "back_30s_clears": clears30,
            "back_5s_clears": clears5, "other_types_clearing": others, "ceiling_before_n7": ceiling,
            "n7_leg": lg, "reasons": reasons}


def run_r1(corpus, frames, cal, idx):
    """R1 + F1 for one corpus. frames: {'B': u, 'E': u} (full IR frames). Returns (block, cell)."""
    cuts = cal["calibration"]["length_terciles"]["cuts"]
    V = {sp: slim_text(f) for sp, f in frames.items()}
    copied, keep_sess, cinfo = copied_ids(V)
    out = {"copied_ids": cinfo, "references": {"calibration_bracket_A": cal["calibration"].get("bracket"),
                                               "swechat_cc_E_FP_eff_track_A": "analysis/out/phase_e/f1_bracket.json "
                                                                              "f1_effective_fp"},
           "step0": "NOT_APPLICABLE: Step 0 is defined on swechat/claude_code B (Track A: REPRODUCED)",
           "blindness": NOT_BLIND, "splits": {}}
    keep = {}
    for sp, u in V.items():
        log(corpus, sp, "bracket")
        u_by_s = {s: g for s, g in u.groupby("session_id", sort=False)}
        R = pe.bracket_responses(u)
        S = pe.bracket_streams(R) if len(R) else pd.DataFrame(columns=["session_id", "stream", "inconsistent"])
        blk = {"sessions_in_split": int(u.session_id.nunique()), "honest": honest_block(R, S)}
        blk["synthetic_sensitivity"] = synthetic_sensitivity(u)
        if len(S):
            blk["placebo"] = placebo_block(R)
            V_h = Variant(R, u_by_s, copied)
            Rdd = dedupe(R, keep_sess)
            V_h_dd = Variant(Rdd, u_by_s, copied)
            V_p = {D: Variant(pe.placebo_shift(R, D), u_by_s, copied) for D in (5000, 30000)}
            V_p_dd = {D: Variant(pe.placebo_shift(Rdd, D), u_by_s, copied) for D in (5000, 30000)}
            blk["benign"] = categories_block(corpus, sp, V_h, u_by_s, copied)
            cmap = call_seq_map(u)
            blk["posthoc_mechanisms"] = posthoc_mechanisms(u, V_h, cmap)
            blk["posthoc_ordered_inputs"] = posthoc_ordered_inputs(u, cmap)
            blk["corrections_single"] = corrections_block(V_h, V_h_dd, V_p, V_p_dd, u_by_s, copied)
            inc_rows = recs(S[S.inconsistent.astype(bool)])
            blk["AC1_parser"] = ac1_audit(corpus, idx, inc_rows, V_h.groups, u_by_s)
            # extension (not a pre-registered check, no verdict effect): with no numerator events, the same raw
            # comparison on up to 30 denominator streams (binding events of consistent streams)
            all_rows = recs(S)
            pick = set(pe.audit_sample([(r["session_id"], r["stream"]) for r in all_rows],
                                       seed_parts=("audit", "R1", corpus, sp, "denominator")))
            blk["AC1_denominator_extension"] = ac1_audit(
                corpus, idx, [r for r in all_rows if (r["session_id"], r["stream"]) in pick], V_h.groups, u_by_s)
            blk["AC1_denominator_extension"]["note"] = ("extension, not pre-registered: binding events of up to 30 "
                                                        "streams drawn from all streams; no verdict effect")
            log(corpus, sp, "stream tamper", len(S), "streams")
            res, dinfo = run_tamper_streams(u, R, S)
            hk = {(a, b): bool(c) for a, b, c in zip(S.session_id, S.stream, S.inconsistent)}
            hr = blk["honest"]["rate_by_session"]
            cells, agree = tamper_cells(res, hk, bar_hi(hr), hr["rate"], blk["honest"]["wilson_per_stream"]["hi"])
            blk["tamper_stream_level"] = {"cells": cells, "honest_flag_agreement_stream_frame_vs_session": agree,
                                          "donor_pool_insert": dinfo, "n_cells": len(cells)}
            keep[sp] = {"u": u, "R": R, "S": S, "V": (V_h, V_h_dd, V_p, V_p_dd), "u_by_s": u_by_s, "res": res,
                        "SP30": pe.bracket_streams(pe.placebo_shift(R, 30000))}
        log(corpus, sp, "N7 R1 session cells")
        blk["n7_r1_session_level"], hon = n7_r1(frames[sp], sp)
        keep.setdefault(sp, {})["n7_honest"] = hon
        out["splits"][sp] = blk
    # ------------------------------------------------------------------ F1 adopted corrections (B), applied to E
    f1 = {}
    if "B" in keep and "V" in keep["B"]:
        adopted = out["splits"]["B"]["corrections_single"]["adopted"]
        use_dd = "restamped_copy" in adopted
        f1["adopted_on_B"] = adopted
        for sp in ("B", "E"):
            if "V" not in keep.get(sp, {}):
                continue
            V_h, V_h_dd, V_p, V_p_dd = keep[sp]["V"]
            Vh, Vp = (V_h_dd, V_p_dd) if use_dd else (V_h, V_p)
            f1[sp] = corrected_eval(Vh, Vp, keep[sp]["u_by_s"], copied, adopted)
            st = Vh.status(set(adopted), keep[sp]["u_by_s"], copied)
            vec = Counter()
            for row, s_ in zip(recs(Vh.S), st):
                if s_ == "flag":
                    vec["+".join(sorted(Vh.cats.get((row["session_id"], row["stream"]), set()))) or "(none)"] += 1
            f1[f"still_flagged_by_category_vector_{sp}"] = dict(vec)
    out["f1_effective_fp"] = f1
    # ------------------------------------------------------------------ pooled B u E + verdicts
    parts = [sp for sp in ("B", "E") if "S" in keep.get(sp, {})]
    pooled = {"splits": parts}
    if parts:
        Sx = pd.concat([keep[sp]["S"] for sp in parts], ignore_index=True)
        SPx = pd.concat([keep[sp]["SP30"] for sp in parts], ignore_index=True)
        ux = pd.concat([keep[sp]["u"] for sp in parts], ignore_index=True)
        hr = crate(Sx.inconsistent.to_numpy(dtype=bool), Sx.session_id.to_numpy())
        pooled["honest"] = {"streams": int(len(Sx)), "inconsistent": int(Sx.inconsistent.sum()),
                            "sessions": int(Sx.session_id.nunique()), "rate_by_session": hr,
                            "wilson_per_stream": wil(Sx.inconsistent.sum(), len(Sx)),
                            "min_n_met": rate_ok(len(Sx), Sx.session_id.nunique())}
        plc = {}
        for k in ("back_5s", "back_30s", "late_5s", "late_30s", "late_300s"):
            kind, D = k.split("_")
            Dm = int(D[:-1]) * 1000
            SPs = pd.concat([pe.bracket_streams(pe.placebo_shift(keep[sp]["R"], Dm if kind == "back" else -Dm))
                             for sp in parts], ignore_index=True)
            f = SPs.inconsistent.to_numpy(dtype=bool)
            plc[k] = {"streams": int(len(SPs)), "flagged": int(f.sum()), "rate_by_session": crate(f, SPs.session_id.to_numpy()),
                      "wilson_per_stream": wil(f.sum(), len(SPs))}
            plc[k]["clears_honest_bar"] = bool(plc[k]["rate_by_session"]["lo"] is not None and bar_hi(hr) is not None
                                               and plc[k]["rate_by_session"]["lo"] > bar_hi(hr))
        RRx = pd.concat([pe.bracket_streams(pe.roll_ids(keep[sp]["R"])) for sp in parts], ignore_index=True)
        plc["roll_ids_reference"] = {"streams": int(len(RRx)), "flagged": int(RRx.inconsistent.sum()),
                                     "rate_by_session": crate(RRx.inconsistent.to_numpy(dtype=bool), RRx.session_id.to_numpy())}
        pooled["placebo"] = plc
        res = sum((keep[sp]["res"] for sp in parts), [])
        hk = {(a, b_): bool(c) for a, b_, c in zip(Sx.session_id, Sx.stream, Sx.inconsistent)}
        cells, agree = tamper_cells(res, hk, bar_hi(hr), hr["rate"], pooled["honest"]["wilson_per_stream"]["hi"])
        pooled["tamper_stream_level"] = {"cells": cells, "honest_flag_agreement_stream_frame_vs_session": agree}
        grid = {}
        for att in ("time_response_early", "time_result_late", "time_tail_late", "time_tail_early"):
            pts = sorted((float(c["param"]), c["rate_by_session"]["rate"]) for c in cells.values() if c["attack"] == att)
            grid[att] = {"points": pts,
                         "smallest_D_rate_ge_0.5": next((D for D, p in pts if p is not None and p >= 0.5), None),
                         "smallest_D_rate_ge_0.9": next((D for D, p in pts if p is not None and p >= 0.9), None)}
        pooled["d_grid_summary"] = grid
        pooled["strata"] = strata_block(ux, Sx, SPx, cuts)
        cc = pd.concat([f[(f.kind == "call") & f.call_id.notna()][["session_id", "call_id"]].drop_duplicates()
                        for f in frames.values()]).drop_duplicates()
        n_ = cc.groupby("call_id").session_id.nunique()
        copied_call = set(n_[n_ > 1].index.astype(str))
        base = honest_leg(hr)
        pooled["artifact_checks"] = artifact_checks(ux, Sx, copied_call, base)
        pooled["artifact_checks"]["AC1_parser"] = {sp: out["splits"][sp].get("AC1_parser") for sp in parts}
        ac = pooled["artifact_checks"]
        effects = []
        for name in ("AC2_truncation", "AC3_join"):
            if ac[name].get("result") == "FAIL":
                effects.append("downgrade" if pe.LEVEL.get(ac[name].get("label"), 0) < pe.LEVEL.get(base, 0) else "pass")
        effects.append(ac["AC4_dominance"]["effect"])
        if any((a or {}).get("result") == "FAIL" for a in ac["AC1_parser"].values()):
            effects.append("downgrade")
        confined = any(pooled["strata"][ax].get("confinement") == "CONFINED" for ax in pooled["strata"])
        # N7 leg: pooled B u E session-level cells (reference) + per split
        legs = {sp: n7_leg(out["splits"][sp]["n7_r1_session_level"]) for sp in ("B", "E")}
        out["n7_legs"] = legs
        pooled["verdict"] = r1_verdict(hr, plc["back_30s"], plc["back_5s"], cells, legs["E"], effects, confined)
        pooled["verdict"]["checks_effects"] = effects
        pooled["verdict"]["confined"] = confined
        per = {}
        for sp in parts:
            b = out["splits"][sp]
            per[sp] = r1_verdict(b["honest"]["rate_by_session"], b["placebo"]["back_30s"], b["placebo"]["back_5s"],
                                 b["tamper_stream_level"]["cells"], legs[sp], [], False)
        pooled["verdict_per_split"] = per
        pooled["verdict_note"] = ("pooled verdict uses the E N7 leg (prereg: N7 on E); per-split verdicts use their own "
                                  "split's N7 leg and no artifact checks / strata")
    out["pooled_BuE"] = pooled
    # ------------------------------------------------------------------ cell
    cell_ = r1_cell(out)
    return out, cell_


def r1_cell(out):
    p = out["pooled_BuE"]
    sp = out["splits"]
    by = {}
    for k in ("B", "E"):
        h = sp.get(k, {}).get("honest", {})
        v = p.get("verdict_per_split", {}).get(k, {"label": "INSUFFICIENT_N" if not h.get("min_n_met") else None})
        by[k] = {"label": v.get("label"), "inconsistent": h.get("inconsistent_streams"), "streams": h.get("streams_ge2"),
                 "sessions": h.get("sessions_with_streams"), "rate_by_session": h.get("rate_by_session")}
    e_ok = by["E"]["label"] not in (None, "INSUFFICIENT_N")
    shown0 = by["E"]["label"] if e_ok else by["B"]["label"]
    suffix = "" if (e_ok or shown0 in (None, "INSUFFICIENT_N")) else " (B only)"
    shown = shown0
    v = p.get("verdict", {})
    if shown in pe.LEVEL:  # the pooled B u E artifact checks lower the shown split label (a check only lowers)
        for eff in v.get("checks_effects", []):
            if eff == "downgrade" and shown != "DEAD":
                shown = pe.downgrade(shown)
                suffix += " (DOMINATED: AC4 leave-out on B u E)"
            elif eff == "cap_weak" and shown == "ALIVE":
                shown = "WEAK"
                suffix += " (AC4 cap on B u E)"
        if v.get("confined") and shown != "DEAD":
            shown = pe.downgrade(shown)
            suffix += " (CONFINED)"
    if not p.get("honest"):
        return cell("NOT_TESTABLE(no stream with >= 2 decoded responses)", None, 0, 0, None, "r1")
    h = p["honest"]
    return cell(f"{shown}{suffix}", {"honest_inconsistent_streams_BuE": h["inconsistent"], "streams_BuE": h["streams"],
                                     "rate_by_session_BuE": h["rate_by_session"]["rate"],
                                     "back_30s_flagged_BuE": p["placebo"]["back_30s"]["flagged"],
                                     "back_5s_flagged_BuE": p["placebo"]["back_5s"]["flagged"]},
                h["streams"], h["sessions"], [h["rate_by_session"].get("lo"), h["rate_by_session"].get("hi")],
                "r1.pooled_BuE", blind=NOT_BLIND, by_split=by, verdict_BuE=p["verdict"]["label"],
                verdict_BuE_reasons=p["verdict"]["reasons"], split_label_before_checks=shown0)


# ===================================================================================================== PART 2
# Implementation choices for the non-R1 mechanisms, fixed before any B/E number of these corpora was seen:
#  T1. Unit thresholds come from the corpus's own A (prereg_e_calibration_<corpus>.json), resolved with the Phase B
#      rules of prereg_calibration.main(): floors per tool_key (p1/p5/p10/p50 where pcal.reportable), G50/G90, L75/L90,
#      D_unit = max(3, ceil(A p75 depth)) if >= 50 A depths from >= 5 sessions, else the pooled D (prereg.json
#      resolved.probe2.depth_threshold.pooled.D). N1 bounds, N2 tau and N5 truncation constants: resolved_preview of the
#      calibration file (N1 pooled bounds), calibration.n2.tau, and prereg_e.json resolved.n5.truncation_constants_pooled.
#  T2. Probes 1-4 run the committed Phase B code (probe_1.probe1_unit + unit_verdict; probe_2.process_unit +
#      stratum_block + verdict; probe_3.analyse_unit; probe_4.extract + unit_summary) with unit argument 'cc_local'
#      (D1). The Phase B modules read their thresholds from module-level copies of prereg.json; for the duration of
#      the call the 'cc_local' entries of those copies are swapped for this corpus's A values (T1) and restored after
#      (no file is edited). probe_2's instrument check is re-run on this corpus's own main-thread S_symbol_ref (the
#      Phase B rule, threshold T_INSTRUMENT). probe_4 runs with private=True (no token or integer value is written).
#  T3. Each mechanism runs on B, on E and on B u E (pooled frame). The N6 cell shows E where E is not INSUFFICIENT_N,
#      else B with 'B only'; B u E is stored beside it.
#  T4. N-cell artifact checks (AC2 truncation, AC3 join, AC4 dominance on stratum / model / session with leave-outs,
#      strata confinement) run on B u E only for a cell reaching WEAK or better; AC1 (raw) and AC5 are NOT_RUN for
#      non-R1 cells (AC5: no population table; AC1: not implemented for these mechanisms here, stated per cell).
#  T5. R2 NOT_TESTABLE (no prompt IMAGE usage), R3 NOT_TESTABLE (no external commit table linked by repo), R5
#      NOT_TESTABLE (no external usage tally): the N6 field gate on A, re-checked on B. R4 honest leg: raw
#      toolUseResult.file.numLines read from the B/E raw files named by the corpus index, joined on tool_use_id, the
#      Track A visible-count rule (lines matching ^\s*\d+(U+2192|\t)), dual_whitelisted(text, 'cc_local') (D1: same
#      Claude Code generation, so the empty-file class applies; its count is reported). The R4 N7 leg is NOT_RUN
#      (no R4 tamper set here), so R4's label is at most the honest-leg label with 'N7 leg NOT_RUN'.
import copy  # noqa: E402

from analysis.probes import prereg_calibration as pcal  # noqa: E402
from analysis.probes import prereg_e_calibration as pce  # noqa: E402

PRB = json.loads((ROOT / "analysis" / "prereg.json").read_text(encoding="utf-8"))
LINE_PREFIX = re.compile("^\\s*\\d+(→|\\t)")


def thresholds(cal, pj):
    pb = cal["phase_b_unit_functions"]
    p1 = pb["probe1"]
    floors, iqr = {}, {}
    for k, row in p1["qualified_by_tool"].items():
        ent = {"n_A": row["n"], "sessions_A": row["n_sessions"]}
        for q in ("p1", "p5", "p10", "p50"):
            if pcal.reportable(row["n"], row["n_sessions"], q):
                ent[q] = row[q]["value"]
        floors[k] = ent
        iqr[k] = {"iqr_log10": row.get("iqr_log10"), "iqr_s": row.get("iqr_s"), "n_A": row["n"]}
    g = p1["generation_rate"]
    gen = {"method": g["method"], "G50": g["G50"], "G90": g["G90"], "n_rates_A": g["n_rates"],
           "sessions_A": g["n_sessions"], "unit": "output tokens per second"}
    dep = pb["probe2_depth_inputs"]
    if dep["n"] >= 50 and dep["sessions"] >= 5:
        D = {"D": int(max(3, math.ceil(dep["quantiles"]["q0.75"]))), "p75_A": dep["quantiles"]["q0.75"],
             "n_A": dep["n"], "sessions_A": dep["sessions"], "source": "unit"}
    else:
        D = {"D": PRB["resolved"]["probe2"]["depth_threshold"]["pooled"]["D"], "n_A": dep["n"],
             "sessions_A": dep["sessions"], "source": "pooled fallback (< 50 depths or < 5 sessions)"}
    p3 = pb["probe3"]
    rp = cal["resolved_preview"]
    trunc = pj["resolved"]["n5"]["truncation_constants_pooled"]
    return {"floors": floors, "iqr_log10": iqr, "generation_rate": gen, "D_unit": D,
            "long_session": {"L75": p3["L75"], "L90": p3["L90"], "sessions_A": p3["sessions_with_paired_calls"]},
            "n1_bounds": rp["n1"]["bounds"], "n1_bounds_source": rp["n1"]["source"],
            "n2_tau": cal["calibration"]["n2"].get("tau"), "n2_granular_A": cal["calibration"]["n2"]["granularity"]["GRANULAR"],
            "length_terciles": cal["calibration"]["length_terciles"]["cuts"], "n5_truncation_pooled": trunc,
            "source": "prereg_e_calibration_<corpus>.json (A only), resolved with prereg_calibration.main() rules"}


def frames_with_pooled(frames):
    out = dict(frames)
    out["BuE"] = pd.concat([frames["B"], frames["E"]], ignore_index=True)
    return out


def show_label(by):
    """N6 fill rule: E where E is not INSUFFICIENT_N, else B with 'B only'."""
    e, b = by.get("E"), by.get("B")
    if e not in (None, "INSUFFICIENT_N", "NOT_RUN"):
        return e
    if b in (None, "INSUFFICIENT_N", "NOT_RUN"):
        return b if e in (None, "NOT_RUN") or b == "INSUFFICIENT_N" else e
    return f"{b} (B only)"


# ----------------------------------------------------------------------------------------------------- field gate
def field_gate_B(uB):
    P = pc.make_pairs(uB[uB.kind.isin(["call", "result"])])
    resp = pe.response_table(PROXY, uB)
    Pk = P.assign(key=[pc.tool_key(PROXY, t, tr) for t, tr in zip(P.tool.astype(object), P.tool_raw.astype(object))])
    res = {"n2": {"granularity": pe.granularity(resp)}, "r3_git": pce.cal_git(PROXY, Pk)}
    fg = pce.field_gate(PROXY, uB, P, res)
    fg["granularity_B"] = res["n2"]["granularity"]
    fg["r3_git_claims_B"] = res["r3_git"]
    fg["note"] = ("prereg_e_calibration.field_gate(unit='cc_local' (D1), B frame): raw_structured_counters / "
                  "external_commit_table / external_usage_tally are properties of the unit argument and the corpus "
                  "(no commit table or usage tally ships with these corpora)")
    return fg


# ----------------------------------------------------------------------------------------------------- Probe 1
class _Swap:
    """Temporarily replace the 'cc_local' entries of a Phase B module's threshold dicts (T2); restored on exit."""

    def __init__(self, pairs):
        self.pairs = pairs  # [(dict, key, new_value)]
        self.saved = []

    def __enter__(self):
        for d, k, v in self.pairs:
            self.saved.append((d, k, d.get(k, _MISSING)))
            d[k] = v
        return self

    def __exit__(self, *a):
        for d, k, v in reversed(self.saved):
            if v is _MISSING:
                d.pop(k, None)
            else:
                d[k] = v


_MISSING = object()


def run_p1(fr, th):
    from analysis.probes import probe_1 as p1
    out = {}
    for sp, u in fr.items():
        uu = u[u.kind.isin(["call", "result", "meta", "system", "user"])][p1.COLS].reset_index(drop=True)
        with _Swap([(p1.RES1["floors"], PROXY, th["floors"]), (p1.RES1["generation_rate"], PROXY, th["generation_rate"])]):
            o = p1.probe1_unit(PROXY, uu, T0)
            v = p1.unit_verdict(PROXY, o)
        v["labels"] = [x for x in v["labels"] if x != "small n"] + (["small n"] if uu.session_id.nunique() < 30 else [])
        sep = o["separability"]
        out[sp] = {"verdict": v, "fp_share": sep.get("fp_share"), "auc": sep.get("auc"),
                   "W_eligible": sep["W_eligible"], "G_eligible": sep["G_eligible"], "G_usable": sep["G_usable"],
                   "a1_recheck": o["a1_recheck_B"], "floor_transfer": {k: o["floor_transfer"][k] for k in
                                                                       ("tested", "floor_shift", "majority_floor_shift",
                                                                        "sensitivity_excluding_A_p5_at_stamp_resolution")},
                   "floor_transfer_by_tool": o["floor_transfer"]["by_tool"],
                   "floor_step_change": {k: o["floor_step_change"].get(k) for k in ("eligible_series", "steps", "label")},
                   "flat_test": {k: o["flat_test"][k] for k in ("W_reportable", "W_reportable_flat", "all_W_flat_kill")},
                   "qualified_pairs": o["qualified_pairs"], "qualified_sessions": o["qualified_sessions"],
                   "sessions": int(uu.session_id.nunique())}
    by = {sp: out[sp]["verdict"]["verdict"] for sp in out}
    lab = show_label(by)
    sh = "E" if by["E"] not in ("INSUFFICIENT_N",) else "B"
    d = out[sh]
    return out, cell(lab, {"fp_share": (d["fp_share"] or {}).get("rate") if isinstance(d["fp_share"], dict) else None,
                           "auc": (d["auc"] or {}).get("auc") if isinstance(d["auc"], dict) else None,
                           "W_eligible": d["W_eligible"]["n"], "G_eligible": d["G_eligible"]["n"]},
                     d["W_eligible"]["n"], d["W_eligible"]["sessions"],
                     {"fp": [(d["fp_share"] or {}).get("lo"), (d["fp_share"] or {}).get("verdict_hi")] if isinstance(d["fp_share"], dict) else None,
                      "auc": [(d["auc"] or {}).get("lo"), (d["auc"] or {}).get("hi")] if isinstance(d["auc"], dict) else None},
                     f"p1.{sh}", blind=NOT_BLIND, by_split=by, rule="probe_1.unit_verdict (Phase B code, A thresholds of this corpus)")


# ----------------------------------------------------------------------------------------------------- Probe 2
def run_p2(fr, th):
    from analysis.probes import probe_2 as p2
    out = {}
    for sp, u in fr.items():
        uu = u[u.kind.isin(["user", "system", "call", "result"])].reset_index(drop=True)
        A = {"sessions": set(), "threads": {"main": set(), "sub": set()}, "refs": [], "access": [],
             "calls": Counter(), "calls_with_any_reference": Counter(), "calls_with": Counter(),
             "redacted_path": Counter(), "redacted_ref": Counter(), "redacted_ref_first": Counter(),
             "root_status": Counter()}
        D = th["D_unit"]["D"]
        with _Swap([(p2.D_UNIT, PROXY, D)]):
            p2.process_unit(PROXY, uu, A)
            R = p2.ref_frame(A["refs"])
            X = p2.acc_frame(A["access"])
            blk = {}
            for st in ("main", "sub"):
                if not len(R) and not len(X):
                    b, sd, sa = {"classes": {}}, {"k": 0, "n": 0, "n_sessions": 0}, {"k": 0, "n": 0, "n_sessions": 0}
                else:
                    b, sd, sa = p2.stratum_block(PROXY, st, R if len(R) else p2.ref_frame([]),
                                                 X if len(X) else p2.acc_frame([]), D, True)
                blk[st] = (b, sd, sa)
            rsym = blk["main"][0].get("S_symbol_ref", {})
            inst_ok = bool(rsym.get("rate") is not None and rsym["rate"] <= p2.T_INSTRUMENT)
            ver = {st: p2.verdict(PROXY, sd, sa, inst_ok, st) for st, (b, sd, sa) in blk.items()}
        for st in ver:
            ver[st]["labels"] = [x for x in ver[st].get("labels", []) if x != "small n"] + (
                ["small n"] if ver[st].get("n_sessions", 0) and ver[st]["n_sessions"] < 30 else [])
        out[sp] = {"D_unit": th["D_unit"], "instrument_check": {"S_symbol_ref_main": rsym, "ok": inst_ok,
                                                                "threshold": p2.T_INSTRUMENT},
                   "verdict": {st: {k: v for k, v in ver[st].items()} for st in ver},
                   "S_deep": {st: blk[st][1] for st in blk}, "S_path_any": {st: blk[st][2] for st in blk},
                   "context_main": {"deep_first_try_n": (blk["main"][0].get("deep_first_try") or {}).get("n_first_accesses"),
                                    "classes_unsourced": {c: (v.get("unsourced") if isinstance(v, dict) else None)
                                                          for c, v in blk["main"][0].get("classes", {}).items()},
                                    "post_hoc_descriptive_phase_b": blk["main"][0].get("post_hoc_descriptive")},
                   "threads_with_calls": {k: len(v) for k, v in A["threads"].items()}, "sessions": len(A["sessions"])}
    cells_ = {}
    for st in ("main", "sub"):
        by = {sp: out[sp]["verdict"][st]["verdict"] for sp in out}
        sh = "E" if by["E"] not in ("INSUFFICIENT_N",) else "B"
        v = out[sh]["verdict"][st]
        cells_[st] = cell(show_label(by), {"statistic": v.get("deciding_statistic"), "value": v.get("value"),
                                           "hi_used": v.get("hi_used"), "k": v.get("k")},
                          v.get("n", v.get("S_deep_n")), v.get("n_sessions", v.get("S_deep_sessions")), v.get("ci"),
                          f"p2.{sh}.verdict.{st}", by_split=by, stratum=st,
                          rule="probe_2.verdict (Phase B code; D_unit from this corpus's A)")
    return out, cells_


# ----------------------------------------------------------------------------------------------------- Probe 3
def run_p3(fr, th):
    from analysis.probes import probe_3 as p3
    pre = copy.deepcopy(PRB)
    pre["resolved"]["probe3"]["long_session"][PROXY] = {"L75": th["long_session"]["L75"], "L90": th["long_session"]["L90"]}
    out = {}
    old = getattr(p3, "PRE", None)
    p3.PRE = pre
    try:
        for sp, u in fr.items():
            uu = u[u.kind.isin(["call", "result"])][p3.LOAD_COLS].reset_index(drop=True)
            o = p3.analyse_unit(PROXY, uu)
            o["verdict"]["labels"] = [x for x in o["verdict"]["labels"]]
            out[sp] = {"verdict": o["verdict"], "zero_error_tail_L75": o["zero_error_tail"]["L75"],
                       "zero_error_tail_L90": o["zero_error_tail"]["L90"], "retry": o["retry"],
                       "error_rate_per_call": o["error_rate_per_call"]["primary"],
                       "error_class_counts": o["error_rate_per_call"]["class_counts"],
                       "sessions_with_paired_calls": o["sessions_with_paired_calls"], "paired_calls": o["paired_calls"],
                       "early_late": o["early_late"], "L75": o["L75"], "L90": o["L90"]}
    finally:
        p3.PRE = old
    cz, cr = {}, {}
    byz = {sp: out[sp]["verdict"]["zero_error_tail"]["verdict"] for sp in out}
    byr = {sp: out[sp]["verdict"]["reaction"]["verdict"] for sp in out}
    shz = "E" if byz["E"] != "INSUFFICIENT_N" else "B"
    shr = "E" if byr["E"] != "INSUFFICIENT_N" else "B"
    z = out[shz]["zero_error_tail_L75"]
    cz = cell(show_label(byz), {"Z": z["Z"]["share"], "n_zero": z["n_zero"], "n_long": z["n_long"], "L75": z["L"]},
              z["n_long"], z["n_long"], [z["Z"]["lo"], z["Z"]["hi"]], f"p3.{shz}.zero_error_tail_L75", by_split=byz,
              rule="probe_3.verdict_zero (Phase B code; L75 from this corpus's A)")
    r = out[shr]["retry"]
    eff = r.get("effect", {})
    cr = cell(show_label(byr), {"effect": eff.get("value"), "n_fail_with_successor": r.get("n_fail_with_successor"),
                                "sessions_fail_with_successor": r.get("sessions_fail_with_successor"),
                                "n_ok_with_successor": r.get("n_ok_with_successor")},
              r.get("n_fail_with_successor"), r.get("sessions_fail_with_successor"), [eff.get("lo"), eff.get("hi")],
              f"p3.{shr}.retry", by_split=byr, rule="probe_3.verdict_reaction (Phase B code)")
    return out, cz, cr


# ----------------------------------------------------------------------------------------------------- Probe 4
def run_p4(fr):
    from analysis.probes import probe_4 as p4
    _, th4, prov = p4.load_prereg()
    out = {}
    for sp, u in fr.items():
        uu = u[u.kind.isin(p4.KINDS)][p4.COLS].reset_index(drop=True)
        acc = p4.extract(PROXY, uu, True)
        labels = ["small n"] if uu.session_id.nunique() < 30 else []
        s = p4.unit_summary(acc, th4, labels, False)
        vh, vr = s["verdicts"]["hex_primary"], s["verdicts"]["round_numbers_secondary"]
        out[sp] = {"hex": {"verdict": vh["verdict"], "reason": vh["reason"], "deciding": vh["deciding"]},
                   "round": {"verdict": vr["verdict"], "reason": vr["reason"], "deciding": vr["deciding"]},
                   "sessions": s["sessions"], "counts": s["counts"]}
    cells_ = {}
    for name, key in (("P4a_hex", "hex"), ("P4b_round", "round")):
        by = {sp: out[sp][key]["verdict"] for sp in out}
        sh = "E" if by["E"] != "INSUFFICIENT_N" else "B"
        d = out[sh][key]["deciding"]
        if key == "hex":
            dn = {"T_orig_symbols": d.get("T_orig_symbols"), "N_min": d.get("N_min"), "T_orig_w_adj": d.get("T_orig_w_adj"),
                  "control": d.get("control"), "control_w_adj_hi": d.get("control_w_adj_hi")}
            n, ns, ci = d.get("T_orig_symbols"), d.get("T_orig_sessions"), [d.get("T_orig_w_adj_lo"), d.get("T_orig_w_adj_hi")]
        else:
            dn = {"T_orig_last0": d.get("T_orig_last0"), "M_all_last0": d.get("M_all_last0"),
                  "T_orig_distinct": d.get("T_orig_distinct"), "M_all_hi_used": d.get("M_all_hi_used")}
            n, ns, ci = d.get("T_orig_distinct"), d.get("T_orig_sessions"), [d.get("T_orig_last0_lo"), d.get("T_orig_last0_hi")]
        cells_[name] = cell(show_label(by), dn, n, ns, ci, f"p4.{sh}.{key}", by_split=by,
                            rule=f"probe_4.{'hex_verdict' if key == 'hex' else 'round_verdict'} (Phase B code, N_min global)")
    return out, cells_, prov


# ----------------------------------------------------------------------------------------------------- generic ACs (T4)
def ac_suite(units, label_fn, cluster_maps, label):
    """units: DataFrame with session_id, trunc, join_clean (bool) + whatever label_fn reads. label_fn(df) -> label."""
    out = {"base_label": label}
    if "trunc" in units:
        l2 = label_fn(units[~units.trunc.astype(bool)])
        out["AC2_truncation"] = {"removed": int(units.trunc.sum()), "label": l2,
                                 "result": "PASS" if l2 == label else "FAIL"}
    else:
        out["AC2_truncation"] = {"result": "NOT_RUN", "reason": "decision units carry no per-result truncation flag here"}
    if "join_clean" in units:
        l3 = label_fn(units[units.join_clean.astype(bool)])
        out["AC3_join"] = {"removed": int((~units.join_clean.astype(bool)).sum()), "label": l3,
                           "result": "PASS" if l3 == label else "FAIL"}
    else:
        out["AC3_join"] = {"result": "NOT_RUN", "reason": "decision units carry no call/result join key here"}
    w = units.groupby("session_id").size().to_dict()
    eff = "pass"
    ac4 = {}
    for name, mp in cluster_maps.items():
        d = pe.dominance(w, mp)
        if name == "session":
            d["dominated"] = d["top_share_events"] > pe.DOM_SESSION
        rec = {"dominated": d["dominated"], "top_share_events": d["top_share_events"],
               "top_share_sessions": d["top_share_sessions"], "n_clusters": d["n_clusters"]}
        if d["dominated"]:
            lv = []
            for c, _, _ in d["top_clusters"]:
                sub = units[units.session_id.map(lambda s: mp.get(s, "unknown")) != c]
                lab = label_fn(sub)
                lv.append({"left_out": str(c) if name != "session" else "a top session", "label": lab, "units": int(len(sub))})
                if lab == "INSUFFICIENT_N":
                    eff = "cap_weak" if eff == "pass" else eff
                elif pe.LEVEL.get(lab, 0) < pe.LEVEL.get(label, 0):
                    eff = "downgrade"
            rec["leave_outs"] = lv
        ac4[name] = rec
    out["AC4_dominance"] = {"by_cluster": ac4, "effect": eff}
    out["AC5_post_strat"] = {"result": "NOT_RUN", "reason": "no population table for new corpora"}
    out["AC1_parser"] = {"result": "NOT_RUN", "reason": "raw re-parse not implemented for this mechanism (T4)"}
    strata = {}
    conf = False
    for name, mp in cluster_maps.items():
        if name == "session":
            continue
        labs = {}
        for c in sorted({mp.get(s, "unknown") for s in units.session_id.unique()}):
            sub = units[units.session_id.map(lambda s: mp.get(s, "unknown")) == c]
            lab = label_fn(sub)
            labs[str(c)] = lab if lab in pe.LEVEL else None
        cf = pe.confinement(labs)
        strata[name] = {"labels": labs, "confinement": cf}
        conf |= cf == "CONFINED"
    out["strata"] = strata
    final = label
    for chk in ("AC2_truncation", "AC3_join"):
        if out[chk].get("result") == "FAIL" and pe.LEVEL.get(out[chk]["label"], -1) < pe.LEVEL.get(final, -1):
            final = out[chk]["label"]
    if eff == "downgrade":
        final = pe.downgrade(final)
    elif eff == "cap_weak" and final == "ALIVE":
        final = "WEAK"
    if conf:
        final = pe.downgrade(final)
    out["label_after_checks"] = final
    out["effects"] = {"AC2_AC3_lower_to": [out[c]["label"] for c in ("AC2_truncation", "AC3_join")
                                           if out[c].get("result") == "FAIL"],
                      "AC4": eff, "confined": conf}
    return out


def apply_checks(label, ac):
    """Lower a shown split label by the B u E check effects (a check can only lower a label)."""
    if ac is None or label not in pe.LEVEL:
        return label
    lab = label
    for l2 in ac["effects"]["AC2_AC3_lower_to"]:
        if l2 in pe.LEVEL and pe.LEVEL[l2] < pe.LEVEL[lab]:
            lab = l2
    if ac["effects"]["AC4"] == "downgrade":
        lab = pe.downgrade(lab)
    elif ac["effects"]["AC4"] == "cap_weak" and lab == "ALIVE":
        lab = "WEAK"
    if ac["effects"]["confined"]:
        lab = pe.downgrade(lab)
    return lab


def cluster_maps(u):
    return {"stratum_D2": pe.session_cluster_map(PROXY, u, kind="repo"), "model": pe.session_model_map(u),
            "session": {s: s for s in u.session_id.unique()}}


# ----------------------------------------------------------------------------------------------------- N1
def run_n1(fr, th):
    out = {}
    G90 = th["generation_rate"]["G90"]
    lo_b, hi_b = th["n1_bounds"]
    for sp, u in fr.items():
        P, Q = pce.unit_pairs(PROXY, u)
        q = Q[Q.qualified]
        blk = {"bounds": th["n1_bounds"], "bounds_source": th["n1_bounds_source"]}
        for cls in ("shell", "auto_read"):
            qc = q[q.cls == cls]
            ing = (qc[qc.n1.notna()].groupby(["session_id", "key", "n1"]).seq.transform("size") >= 2)
            k_rep = int(ing.sum())
            blk_c = {"qualified_calls": int(len(qc)), "qualified_sessions": int(qc.session_id.nunique()),
                     "calls_in_repeat_groups": k_rep,
                     "RR": wil(k_rep, len(qc)) if len(qc) else None}
            R = pe.n1_residuals(qc, PROXY)
            blk_c["residuals"] = int(len(R))
            blk_c["residual_sessions"] = int(R.session_id.nunique()) if len(R) else 0
            ok = len(R) >= 200 and blk_c["residual_sessions"] >= 20
            blk_c["min_n_met"] = bool(ok)
            if len(R):
                fl = (R.residual.to_numpy() < lo_b) | (R.residual.to_numpy() > hi_b)
                blk_c["flag_rate"] = crate(fl, R.session_id.to_numpy())
                blk_c["rho_hon"] = pe.session_spearman(R.residual.to_numpy(), R.log_bytes.to_numpy(), R.session_id.to_numpy())
                # positive control: one instance per group gets delta' = result chars x 0.25 / G90
                rows = []
                qg = qc[qc.n1.notna()]
                for (s, k, nk), g in qg.groupby(["session_id", "key", "n1"], sort=False):
                    if len(g) < 2:
                        continue
                    rng = pe.rng_for("N1pc", s, nk)
                    i = int(rng.integers(0, len(g)))
                    er = g.err.to_numpy()
                    ref = [math.log10(d) for j, d in enumerate(g.delta_s.to_numpy()) if j != i and er[j] == er[i]]
                    if not ref:
                        continue
                    tg = max(g.result_chars.iloc[i] * 0.25 / G90, 1e-6)
                    rows.append((s, math.log10(tg) - float(np.median(ref)), math.log10(g.result_bytes.iloc[i] + 1)))
                if rows:
                    pcdf = pd.DataFrame(rows, columns=["s", "r", "lb"])
                    blk_c["rho_pc"] = pe.session_spearman(pcdf.r.to_numpy(), pcdf.lb.to_numpy(), pcdf.s.to_numpy())
                    blk_c["rho_pc_n"] = int(len(pcdf))
            if ok:
                rh, rpc, fr_ = blk_c["rho_hon"], blk_c.get("rho_pc", {}), blk_c["flag_rate"]
                rr = k_rep / len(qc) if len(qc) else 0
                hon_ci = rh.get("ci_reported") and rh.get("lo") is not None
                fhi = fr_.get("wilson_hi_per_event") if fr_.get("num") == 0 else fr_.get("hi")
                if rh["value"] is None or (rh["value"] > 0.15) or not hon_ci or rpc.get("lo") is None or rpc["lo"] <= rh["hi"]:
                    lab = "DEAD" if rh["value"] is not None and hon_ci else "INCONCLUSIVE"
                elif (rh["lo"] >= -0.15 and rh["hi"] <= 0.15 and rpc["lo"] >= 0.30 and rr >= 0.10 and fr_["rate"] <= 0.02
                      and fhi is not None and fhi <= 0.05):
                    lab = "ALIVE"
                elif abs(rh["value"]) <= 0.15:
                    lab = "WEAK"
                else:
                    lab = "DEAD"
            else:
                lab = "INSUFFICIENT_N"
            blk_c["label"] = lab
            blk[cls] = blk_c
        out[sp] = blk
    by = {sp: out[sp]["shell"]["label"] for sp in out}
    sh = "E" if by["E"] != "INSUFFICIENT_N" else "B"
    d = out[sh]["shell"]
    return out, cell(show_label(by), {"residuals": d["residuals"], "residual_sessions": d["residual_sessions"],
                                      "RR": (d["RR"] or {}).get("p"), "rho_hon": (d.get("rho_hon") or {}).get("value")},
                     d["residuals"], d["residual_sessions"], [(d.get("rho_hon") or {}).get("lo"), (d.get("rho_hon") or {}).get("hi")],
                     f"n1.{sh}.shell", by_split=by, label_note="human-wait contaminated (permissionMode not in the IR)",
                     min_n="200 residuals from 20 sessions")


# ----------------------------------------------------------------------------------------------------- N2
def n2_units(u, tau):
    resp = pe.response_table(PROXY, u)
    gran = pe.granularity(resp)
    if not len(resp):
        return gran, pd.DataFrame()
    P = pc.make_pairs(u[u.kind.isin(["call", "result"])])
    cids = P.call_id.astype(str).to_numpy()
    txt = P.text_r.astype(object).to_numpy()
    rc = {(s, c): len(x) for s, c, x in zip(P.session_id, cids, txt) if isinstance(x, str)}
    jc = pe.join_clean_mask(u, P, frozenset())
    clean = set(zip(P.session_id.to_numpy()[jc], cids[jc]))
    trunc = {(s, c): pe.truncated_result(x, e) for s, c, x, e in zip(P.session_id, cids, txt, P.extra_r.astype(object))
             if isinstance(x, str) and len(x) >= 800}
    resp = resp.assign(last_call_id=resp.last_call_id.astype(str))
    base = pe.n2_flags(resp, rc, tau)
    E_ = pd.DataFrame(base, columns=["session_id", "resp", "flag"])
    if not len(E_):
        return gran, E_
    R = resp.set_index(["session_id", "resp"])
    idx = pd.MultiIndex.from_arrays([E_.session_id, E_.resp])
    for c in ("usage_out", "chars_out", "last_call_id"):
        E_[c] = R[c].reindex(idx).to_numpy()
    E_["rc"] = [rc.get((s, c)) for s, c in zip(E_.session_id, E_.last_call_id)]
    E_["trunc"] = [bool(trunc.get((s, c), False)) for s, c in zip(E_.session_id, E_.last_call_id)]
    E_["join_clean"] = [(s, c) in clean for s, c in zip(E_.session_id, E_.last_call_id)]
    E_["U"] = E_.usage_out - tau * E_.chars_out
    for tp in (1.0, 0.8):
        extra = {(s, r): pe.atk_inline_fabrication(None, rc_, tp * tau) for s, r, rc_ in zip(E_.session_id, E_.resp, E_.rc)}
        sub = resp[[(s, r) in extra for s, r in zip(resp.session_id, resp.resp)]]
        f = {(s, r): v for s, r, v in pe.n2_flags(sub, rc, tau, extra_out=extra)}
        E_[f"flag_pc_{tp:g}"] = [f[(s, r)] for s, r in zip(E_.session_id, E_.resp)]
    return gran, E_


def n2_label(E_):
    n, ns = len(E_), E_.session_id.nunique() if len(E_) else 0
    if n < 100 or ns < 10:
        return "INSUFFICIENT_N"
    fr_ = crate(E_.flag.to_numpy(dtype=bool), E_.session_id.to_numpy())
    r08 = crate(E_["flag_pc_0.8"].to_numpy(dtype=bool), E_.session_id.to_numpy())["rate"]
    hi = fr_.get("wilson_hi_per_event") if fr_.get("num") == 0 else fr_.get("hi")
    if fr_["rate"] <= 0.05 and hi is not None and hi <= 0.10 and r08 >= 0.90:
        return "ALIVE"
    if fr_["rate"] <= 0.20 and r08 >= 0.50:
        return "WEAK"
    return "DEAD"


def run_n2(fr, th):
    out, keep = {}, {}
    tau = th["n2_tau"]
    for sp, u in fr.items():
        gran, E_ = n2_units(u, tau)
        blk = {"tau_A": tau, "granularity": gran}
        if not gran.get("GRANULAR"):
            blk["label"] = "DEAD"
            blk["rule"] = "not GRANULAR on this split"
        else:
            blk["eligible_responses"] = int(len(E_))
            blk["eligible_sessions"] = int(E_.session_id.nunique()) if len(E_) else 0
            if len(E_):
                blk["honest_flag_rate"] = crate(E_.flag.to_numpy(dtype=bool), E_.session_id.to_numpy())
                for tp in (1.0, 0.8):
                    blk[f"recall_tau_prime_{tp:g}"] = crate(E_[f"flag_pc_{tp:g}"].to_numpy(dtype=bool), E_.session_id.to_numpy())
                blk["U_over_tau_rc"] = qd((E_.U / (tau * E_.rc.astype(float))).to_numpy(dtype=float))
            blk["label"] = n2_label(E_) if len(E_) else "INSUFFICIENT_N"
        out[sp] = blk
        keep[sp] = (u, E_)
    if pe.LEVEL.get(out["BuE"]["label"], -1) >= 1 or pe.LEVEL.get(out["E"]["label"], -1) >= 1 or pe.LEVEL.get(out["B"]["label"], -1) >= 1:
        u, E_ = keep["BuE"]
        out["artifact_checks_BuE"] = ac_suite(E_, n2_label, cluster_maps(u), out["BuE"]["label"])
    by = {sp: out[sp]["label"] for sp in ("B", "E", "BuE")}
    sh = "E" if by["E"] != "INSUFFICIENT_N" else "B"
    d = out[sh]
    fr_ = d.get("honest_flag_rate", {})
    lab0 = show_label(by)
    ac = out.get("artifact_checks_BuE")
    base = lab0.replace(" (B only)", "")
    lab = apply_checks(base, ac) + (" (B only)" if lab0.endswith("(B only)") else "")
    return out, cell(lab, {"honest_flag_rate": fr_.get("rate"), "recall_0.8tau": (d.get("recall_tau_prime_0.8") or {}).get("rate"),
                           "tau_A": tau}, d.get("eligible_responses"), d.get("eligible_sessions"),
                     [fr_.get("lo"), fr_.get("hi")], f"n2.{sh}", by_split=by, min_n="100 eligible responses from 10 sessions",
                     label_before_checks=lab0, BuE_label_after_checks=(ac or {}).get("label_after_checks"))


# ----------------------------------------------------------------------------------------------------- N3
def n3_label(G):
    n_by = G.groupby("session_id").size() if len(G) else pd.Series(dtype=int)
    elig = set(n_by[n_by >= 20].index)
    if len(elig) < 20:
        return "INSUFFICIENT_N", None
    ge = G[G.session_id.isin(elig)]
    rs = {s: pe.spearman(x.gap.to_numpy(float), x.bytes.to_numpy(float)) for s, x in ge.groupby("session_id")}
    d = {s: r for s, r in rs.items() if r is not None}
    k = sum(1 for r in d.values() if r <= 0)
    p, lo_, hi_ = stats.wilson(k, len(d))
    rp = pe.session_spearman(ge.gap.to_numpy(float), ge.bytes.to_numpy(float), ge.session_id.to_numpy())
    info = {"eligible_sessions": len(elig), "share_rho_s_le_0": {"k": k, "n": len(d), "p": p, "lo": lo_, "hi": hi_},
            "rho_pooled": rp}
    if not rp.get("ci_reported"):
        return "INCONCLUSIVE", info
    if rp["lo"] >= 0.30 and p <= 0.10 and hi_ <= 0.20:
        return "ALIVE", info
    if rp["lo"] > 0:
        return "WEAK", info
    return "DEAD", info


def run_n3(fr):
    out, keep = {}, {}
    for sp, u in fr.items():
        G = pd.DataFrame(pe.n3_gaps(u), columns=["session_id", "gap", "bytes"])
        keep[sp] = (u, G)
        n_by = G.groupby("session_id").size() if len(G) else pd.Series(dtype=int)
        lab, info = n3_label(G)
        blk = {"gaps": int(len(G)), "sessions_with_gaps": int(len(n_by)),
               "sessions_ge_20_gaps": int((n_by >= 20).sum()), "label": lab, "stat": info,
               "gap_s": qd(G.gap.to_numpy(float)) if len(G) else None}
        if info is not None:
            ge = G[G.session_id.isin(set(n_by[n_by >= 20].index))]
            pr = {}
            for s, x in ge.groupby("session_id", sort=True):
                g = x.gap.to_numpy(float)
                g = g[pe.rng_for("N3pc", s, "gaps").permutation(len(g))]
                pr[s] = pe.spearman(g, x.bytes.to_numpy(float))
            pd_ = [r for r in pr.values() if r is not None]
            blk["positive_control_permutation_recall"] = wil(sum(1 for r in pd_ if r <= 0), len(pd_))
        out[sp] = blk
    by = {sp: out[sp]["label"] for sp in ("B", "E", "BuE")}
    ac = None
    if any(pe.LEVEL.get(v, -1) >= 1 for v in by.values()):
        u, G = keep["BuE"]
        ac = ac_suite(G, lambda df: n3_label(df)[0], cluster_maps(u), by["BuE"])
        out["artifact_checks_BuE"] = ac
    sh = "E" if by["E"] != "INSUFFICIENT_N" else "B"
    d = out[sh]
    st = d["stat"] or {}
    lab0 = show_label(by)
    lab = apply_checks(lab0.replace(" (B only)", ""), ac) + (" (B only)" if lab0.endswith("(B only)") else "")
    return out, cell(lab, {"sessions_ge_20_gaps": d["sessions_ge_20_gaps"],
                                      "rho_pooled": (st.get("rho_pooled") or {}).get("value")},
                     d["gaps"], d["sessions_ge_20_gaps"], [(st.get("rho_pooled") or {}).get("lo"), (st.get("rho_pooled") or {}).get("hi")],
                     f"n3.{sh}", by_split=by, blind=NOT_BLIND, min_n="20 sessions with >= 20 gaps",
                     label_before_checks=lab0, BuE_label_after_checks=(ac or {}).get("label_after_checks"))


# ----------------------------------------------------------------------------------------------------- N4
def run_n4(fr):
    out = {}
    for sp, u in fr.items():
        P = pc.make_pairs(u[u.kind.isin(["call", "result"])])
        PB = pcal.p1_qualified(PROXY, u, P)
        W = PB[PB.qualified & (PB.delta_s > 0)]
        W = W[W.cls == "auto_read"]
        kw = pe.inflight_counts(W) if len(W) else np.array([])
        G = PB[PB.key.isin(pcal.G_TOOLS.get(PROXY, set())) & ~PB.marker.isin(["cc_permission_denied", "cc_interrupt_reject"])]
        glat = [pcal.g_latency(PROXY, k, d, x) for k, d, x in zip(G.key, G.delta_s, G._rx)]
        G = G.assign(_glat=glat)
        G = G[[x is not None and np.isfinite(x) and x > 0 for x in G._glat]]
        kg = pe.inflight_counts(G) if len(G) else np.array([])
        blk = {"W_pairs": int(len(W)), "W_k_ge_2": int((kw >= 2).sum()) if len(kw) else 0,
               "W_k_ge_2_sessions": int(W[kw >= 2].session_id.nunique()) if len(kw) else 0,
               "W_k_ge_4": int((kw >= 4).sum()) if len(kw) else 0,
               "G_pairs": int(len(G)), "G_k_ge_2": int((kg >= 2).sum()) if len(kg) else 0,
               "G_k_ge_2_sessions": int(G[kg >= 2].session_id.nunique()) if len(kg) else 0,
               "share_k_ge_4_W": (float((kw >= 4).mean()) if len(kw) else None)}
        ok = (blk["W_k_ge_2"] >= 100 and blk["W_k_ge_2_sessions"] >= 10 and blk["G_k_ge_2"] >= 100
              and blk["G_k_ge_2_sessions"] >= 10)
        blk["label"] = "INSUFFICIENT_N" if not ok else "NOT_RUN"
        if ok:
            blk["note"] = "min n met but the delta statistic is not implemented in this group script"
        out[sp] = blk
    by = {sp: out[sp]["label"] for sp in out}
    d = out["E"] if by["E"] != "INSUFFICIENT_N" else out["B"]
    return out, cell(show_label(by), {"W_k_ge_2": d["W_k_ge_2"], "G_k_ge_2": d["G_k_ge_2"]}, d["W_k_ge_2"],
                     d["W_k_ge_2_sessions"], None, "n4", by_split=by,
                     min_n=">= 100 pairs at k >= 2 from >= 10 sessions in each of W and G")


# ----------------------------------------------------------------------------------------------------- N5
def rate_label(k, n, ns, alive, alive_hi, weak, flags=None, sids=None, min_n=(100, 20)):
    if n < min_n[0] or ns < min_n[1]:
        return "INSUFFICIENT_N", None
    r = crate(flags, sids)
    hi = r.get("wilson_hi_per_event") if r.get("num") == 0 else r.get("hi")
    if r["rate"] <= alive and hi is not None and hi <= alive_hi:
        return "ALIVE", r
    if r["rate"] <= weak:
        return "WEAK", r
    return "DEAD", r


def _iqr_of(gs):
    v = np.concatenate([np.asarray(g, float) for g in gs]) if gs else np.array([])
    return float(np.quantile(v, 0.75) - np.quantile(v, 0.25)) if len(v) else None


def _boot_iqr(df):
    by_s = {s: g.logb.to_numpy(float) for s, g in df.groupby("session_id", sort=True)}
    return pe.boot_stat([by_s[k] for k in sorted(by_s)], _iqr_of)


def n5e_eval(EDF):
    """N5e on one population of rows (kind 'fam' = shell-family results, 'comp' = model-generated comparator texts).
    Track A convention (phase_e_n5_battery): comparator IQR CI by session bootstrap; comparator needs >= 30 texts from
    >= 5 sessions; a family qualifies at >= 100 results from >= 10 sessions; 'above' = family IQR point > comparator
    CI hi; WEAK if >= 0.5 of qualifying families are above (capped at WEAK), else DEAD."""
    F = EDF[EDF.kind == "fam"]
    C = EDF[EDF.kind == "comp"]
    q = F.groupby("family").agg(n=("logb", "size"), s=("session_id", "nunique"))
    qual = sorted(q[(q.n >= 100) & (q.s >= 10)].index)
    cb = _boot_iqr(C) if len(C) else {"value": None}
    out = {"families_ge_100_from_10_sessions": len(qual),
           "comparator": {"n": int(len(C)), "sessions": int(C.session_id.nunique()), "iqr": cb,
                          "definition": "log10(bytes + 1) of assistant text events and subagent results"},
           "families": {}}
    above = 0
    for f in qual:
        fb = _boot_iqr(F[F.family == f])
        ab = bool(fb.get("value") is not None and cb.get("hi") is not None and fb["value"] > cb["hi"])
        above += int(ab)
        out["families"][f] = {"n": int(q.loc[f, "n"]), "sessions": int(q.loc[f, "s"]), "iqr": fb, "above_comparator_ci_hi": ab}
    if not qual:
        out["label"] = "INSUFFICIENT_N"
    elif len(C) < 30 or C.session_id.nunique() < 5 or not cb.get("ci_reported"):
        out["label"] = "INCONCLUSIVE"
    else:
        out["share_above"] = above / len(qual)
        out["label"] = "WEAK" if above / len(qual) >= 0.5 else "DEAD"
    return out


def run_n5(fr, th):
    out, keep_e = {}, {}
    trunc_c = th["n5_truncation_pooled"]
    for sp, u in fr.items():
        P = pc.make_pairs(u[u.kind.isin(["call", "result"])])
        P = P.assign(key=[pc.private_key(pc.tool_key(PROXY, t, tr)) for t, tr in zip(P.tool.astype(object), P.tool_raw.astype(object))])
        P["n1"] = [pe.n1_key(PROXY, k, a, c) for k, a, c in zip(P.key, P.args.astype(object), P.command.astype(object))]
        P["err"] = [bool(pc.error_classes(PROXY, k, tr, t, e, n, x, st)[0]) for k, tr, t, e, n, x, st in
                    zip(P.key, P.tool_raw.astype(object), P.text_r.astype(object), P.stderr_r.astype(object),
                        P.native_error_r.astype(object), P.exit_code_r.astype(object), P.stratum.astype(object))]
        blk = {}
        # a determinism
        dp = pe.determinism_pairs(PROXY, u, P)
        drift = [pe.mask_volatile(a) != pe.mask_volatile(b) for (_, _, _, _, a, b) in dp]
        sids = [x[0] for x in dp]
        lab, r = rate_label(sum(drift), len(dp), len(set(sids)), 0.05, 0.10, 0.20, drift, sids, (100, 20))
        blk["a_determinism"] = {"pairs": len(dp), "sessions": len(set(sids)), "drift": int(sum(drift)), "label": lab, "rate": r}
        # b sort order, d whitespace, e size families
        sort_v, ws_v = defaultdict(list), defaultdict(list)
        fam = defaultdict(list)
        erows = []
        jcm = pe.join_clean_mask(u, P, frozenset())
        for sid, k, a, cmd, t, exr, jc_ in zip(P.session_id, P.key, P.args.astype(object), P.command.astype(object),
                                              P.text_r.astype(object), P.extra_r.astype(object), jcm):
            shellish = k == "shell" or str(k).endswith("__bash")
            sc = pc.shell_command(PROXY, k, pc.jl(a) if isinstance(a, str) else {}, cmd) if shellish else None
            if sc:
                for name, fn in (("ls", pe.ls_order_violation), ("git_log", pe.gitlog_order_violation),
                                 ("grep_n", pe.grepn_order_violation)):
                    v = fn(sc, t)
                    if v is not None:
                        sort_v[name].append((sid, bool(v)))
                for name, v in pe.ws_violations(sc, t).items():
                    ws_v[name].append((sid, bool(v)))
                progs = pe.command_programs(sc)
                if progs:
                    f = progs[0][0]
                    if f == "git":
                        m = re.search(r"\bgit\s+(?:-C\s+\S+\s+|--no-pager\s+)*([a-z\-]+)", progs[0][1])
                        f = "git " + (m.group(1) if m else "?")
                    lb = math.log10((len(t.encode("utf-8")) if isinstance(t, str) else 0) + 1)
                    fam[f].append((sid, lb))
                    erows.append({"session_id": sid, "kind": "fam", "family": f, "logb": lb,
                                  "trunc": bool(pe.truncated_result(t, exr if isinstance(exr, str) else None)),
                                  "join_clean": bool(jc_)})
            if k == "grep":
                v = pe.grepn_order_violation(a, t, is_grep_tool=True)
                if v is not None:
                    sort_v["grep_n"].append((sid, bool(v)))
        blk["b_sort"] = {}
        for name in ("ls", "git_log", "grep_n"):
            lst = sort_v.get(name, [])
            fl = [x[1] for x in lst]
            ss = [x[0] for x in lst]
            lab, r = rate_label(sum(fl), len(lst), len(set(ss)), 0.01, 0.03, 0.05, fl, ss, (100, 20))
            blk["b_sort"][name] = {"outputs": len(lst), "sessions": len(set(ss)), "violations": int(sum(fl)), "label": lab, "rate": r}
        blk["d_whitespace"] = {}
        for name in ("ls_long_alignment", "git_status_tab", "wc_alignment", "pytest_banner"):
            lst = ws_v.get(name, [])
            fl = [x[1] for x in lst]
            ss = [x[0] for x in lst]
            lab, r = rate_label(sum(fl), len(lst), len(set(ss)), 0.01, 0.03, 0.05, fl, ss, (100, 20))
            blk["d_whitespace"][name] = {"outputs": len(lst), "sessions": len(set(ss)), "violations": int(sum(fl)), "label": lab, "rate": r}
        # c truncation boundary
        tr = defaultdict(list)
        for sid, t in zip(P.session_id, P.text_r.astype(object)):
            ti = pe.truncation_info(t)
            if ti:
                tr[ti["item"]].append((sid, ti))
        blk["c_truncation"] = {"constants_pooled": trunc_c}
        for item, lst in tr.items():
            ss = [x[0] for x in lst]
            if item == "cc_chars_mid":
                c = trunc_c.get("cc_chars_mid", {})
                ex = [x["prefix_u16"] == c.get("prefix_u16") and x["suffix_u16"] == c.get("suffix_u16") for _, x in lst]
            elif item == "cc_glob_cap":
                c = trunc_c.get("cc_glob_cap", {})
                ex = [x["lines"] == c.get("lines") for _, x in lst]
            else:
                blk["c_truncation"][item] = {"n": len(lst), "label": "NOT_RUN", "reason": "tail cut NOT_RUN (prereg: < 5 A instances)"}
                continue
            n, ns = len(lst), len(set(ss))
            if n < 50 or ns < 10:
                lab = "INSUFFICIENT_N"
            else:
                p, lo_, hi_ = stats.wilson(sum(ex), n)
                lab = "ALIVE" if (p >= 0.99 and lo_ >= 0.95) else ("WEAK" if p >= 0.90 else "DEAD")
            blk["c_truncation"][item] = {"n": n, "sessions": ns, "exact": int(sum(ex)), "label": lab}
        # e size distribution (capped at WEAK)
        for sid, t in zip(u.session_id[u.kind == "assistant"], u.text[u.kind == "assistant"].astype(object)):
            if isinstance(t, str):
                erows.append({"session_id": sid, "kind": "comp", "family": "assistant_text",
                              "logb": math.log10(len(t.encode("utf-8")) + 1), "trunc": False, "join_clean": True})
        for sid, k, t in zip(P.session_id, P.key, P.text_r.astype(object)):
            if k == "subagent" and isinstance(t, str):
                erows.append({"session_id": sid, "kind": "comp", "family": "subagent_result",
                              "logb": math.log10(len(t.encode("utf-8")) + 1), "trunc": False, "join_clean": True})
        EDF = pd.DataFrame(erows, columns=["session_id", "kind", "family", "logb", "trunc", "join_clean"])
        e_blk = n5e_eval(EDF)
        e_blk["families_total"] = len(fam)
        blk["e_size"] = e_blk
        keep_e[sp] = (u, EDF)
        # f error fidelity
        ef = pe.error_fidelity_checks(PROXY, u, P)
        fl = [not x[4] for x in ef]
        ss = [x[0] for x in ef]
        lab, r = rate_label(sum(fl), len(ef), len(set(ss)), 0.02, 0.05, 0.10, fl, ss, (100, 20))
        blk["f_error_fidelity"] = {"frames": len(ef), "sessions": len(set(ss)), "infidelity": int(sum(fl)),
                                   "error_results": int(P.err.sum()), "label": lab}
        # g cold start
        Pq, Q = pce.unit_pairs(PROXY, u)
        cs = pe.cold_start_values(Q[Q.qualified])
        n = len(cs)
        if n < 30:
            lab, gi = "INSUFFICIENT_N", None
        else:
            cv = np.array([x[2] for x in cs])
            med = pe.boot_stat([[v] for v in cv], lambda g: float(np.median([x[0] for x in g])) if g else None)
            k = int((cv <= 0).sum())
            sh = stats.wilson(k, n)
            lab = ("ALIVE" if med.get("lo") is not None and med["lo"] >= math.log10(1.5) and sh[0] <= 0.05
                   else "WEAK" if med.get("lo") is not None and med["lo"] > 0 else "DEAD")
            gi = {"median_c": med, "share_c_le_0": {"k": k, "n": n, "p": sh[0], "lo": sh[1], "hi": sh[2]}}
        blk["g_cold_start"] = {"eligible_sessions": n, "label": lab, "stat": gi}
        out[sp] = blk
    cells_ = {}

    def mk(name, get, n_get, path):
        by = {sp: get(out[sp]) for sp in out}
        sh = "E" if by["E"] != "INSUFFICIENT_N" else "B"
        n, ns = n_get(out[sh])
        cells_[name] = cell(show_label(by), {"n": n, "sessions": ns}, n, ns, None, f"n5.{sh}.{path}", by_split=by)
    mk("N5a_determinism", lambda b: b["a_determinism"]["label"], lambda b: (b["a_determinism"]["pairs"], b["a_determinism"]["sessions"]), "a_determinism")
    # N5b / N5d: a cell per checker is stored; the N6 cell = best-n checker label set
    for nm, key in (("N5b_sort", "b_sort"), ("N5d_whitespace", "d_whitespace")):
        by = {sp: {c: v["label"] for c, v in out[sp][key].items()} for sp in out}
        labs = {sp: sorted(set(v.values())) for sp, v in by.items()}
        e_any = [l for l in by["E"].values() if l != "INSUFFICIENT_N"]
        b_any = [l for l in by["B"].values() if l != "INSUFFICIENT_N"]
        lab = ("/".join(sorted(set(e_any))) if e_any else (("/".join(sorted(set(b_any))) + " (B only)") if b_any else "INSUFFICIENT_N"))
        sh = "E" if e_any else "B"
        nmax = max(((v["outputs"], v["sessions"]) for v in out[sh][key].values()), default=(0, 0))
        cells_[nm] = cell(lab, {c: (v["outputs"], v["sessions"], v["violations"]) for c, v in out[sh][key].items()},
                          nmax[0], nmax[1], None, f"n5.{sh}.{key}", by_split=by, per_checker_labels=labs,
                          min_n="100 outputs from 20 sessions per checker")
    by = {sp: {k: v.get("label") for k, v in out[sp]["c_truncation"].items() if k != "constants_pooled"} for sp in out}
    e_any = [l for l in by["E"].values() if l not in ("INSUFFICIENT_N", "NOT_RUN")]
    b_any = [l for l in by["B"].values() if l not in ("INSUFFICIENT_N", "NOT_RUN")]
    cells_["N5c_truncation"] = cell("/".join(e_any) if e_any else (("/".join(b_any) + " (B only)") if b_any else "INSUFFICIENT_N"),
                                    {sp: {k: v.get("n") for k, v in out[sp]["c_truncation"].items() if k != "constants_pooled"}
                                     for sp in out}, None, None, None, "n5.*.c_truncation", by_split=by,
                                    min_n="50 from 10 sessions per item")
    mk("N5e_size", lambda b: b["e_size"]["label"], lambda b: (b["e_size"]["families_ge_100_from_10_sessions"], None), "e_size")
    by_e = {sp: out[sp]["e_size"]["label"] for sp in ("B", "E", "BuE")}
    e_ac = {}
    if any(pe.LEVEL.get(v, -1) >= 1 for v in by_e.values()):
        u_, EDF = keep_e["BuE"]
        ac = ac_suite(EDF, lambda d: n5e_eval(d)["label"], cluster_maps(u_), by_e["BuE"])
        e_ac["BuE"] = ac
        lab0 = cells_["N5e_size"]["label"]
        cells_["N5e_size"]["label"] = (apply_checks(lab0.replace(" (B only)", ""), ac)
                                       + (" (B only)" if lab0.endswith("(B only)") else ""))
        cells_["N5e_size"]["label_before_checks"] = lab0
        cells_["N5e_size"]["BuE_label_after_checks"] = ac["label_after_checks"]
    sh_e = "E" if by_e["E"] not in ("INSUFFICIENT_N",) else "B"
    e_ = out[sh_e]["e_size"]
    cells_["N5e_size"]["deciding_number"] = {"share_above": e_.get("share_above"),
                                             "families_qualifying": e_["families_ge_100_from_10_sessions"],
                                             "comparator_iqr_hi": e_["comparator"]["iqr"].get("hi")}
    mk("N5f_error_fidelity", lambda b: b["f_error_fidelity"]["label"], lambda b: (b["f_error_fidelity"]["frames"], b["f_error_fidelity"]["sessions"]), "f_error_fidelity")
    mk("N5g_cold_start", lambda b: b["g_cold_start"]["label"], lambda b: (b["g_cold_start"]["eligible_sessions"], b["g_cold_start"]["eligible_sessions"]), "g_cold_start")
    if e_ac:
        out["e_artifact_checks_BuE"] = e_ac["BuE"]
    return out, cells_


# ----------------------------------------------------------------------------------------------------- R4
def r4_raw(corpus, idx, sids):
    root = Path(idx["corpus_root"])
    res, info = {}, Counter()
    for s in sids:
        ent = idx["sessions"].get(s)
        if ent is None:
            info["session_not_in_index"] += 1
            continue
        assert ent["split"] in ("B", "E")
        nl = {}
        for role, rel, member in ent["files"]:
            p = root / rel
            if not p.exists():
                info["file_missing"] += 1
                continue
            with open(p, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"numLines"' not in line:
                        continue
                    try:
                        d = json.loads(line)
                    except ValueError:
                        info["bad_json"] += 1
                        continue
                    if not isinstance(d, dict):
                        continue
                    tur = d.get("toolUseResult")
                    msg = d.get("message") if isinstance(d.get("message"), dict) else {}
                    blocks = msg.get("content") if isinstance(msg.get("content"), list) else []
                    tr = next((b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_result"), None)
                    if not isinstance(tur, dict) or tr is None:
                        continue
                    f = tur.get("file")
                    if isinstance(f, dict) and type(f.get("numLines")) is int and tr.get("tool_use_id"):
                        cid = str(tr["tool_use_id"])
                        if cid in nl:
                            info["duplicate_tool_use_id"] += 1
                            continue
                        nl[cid] = int(f["numLines"])
        res[s] = nl
    return res, dict(info)


def run_r4(corpus, idx, fr):
    out = {}
    for sp in ("B", "E", "BuE"):
        u = fr[sp]
        raw, info = r4_raw(corpus, idx, sorted(u.session_id.unique()))
        rs = u[(u.kind == "result") & u.call_id.notna()].sort_values(["session_id", "seq"]).drop_duplicates(["session_id", "call_id"])
        rows = []
        for s, c, t, ex in zip(rs.session_id, rs.call_id.astype(str), rs.text.astype(object), rs.extra.astype(object)):
            nlv = raw.get(s, {}).get(c)
            if nlv is None:
                continue
            t = t if isinstance(t, str) else ""
            L = sum(1 for ln in t.split("\n") if LINE_PREFIX.match(ln))
            wl = pe.dual_whitelisted(t, PROXY)
            wl_sw = pe.dual_whitelisted(t, "swechat")
            rows.append({"session_id": s, "mismatch": L != nlv, "flag": (L != nlv) and wl is None,
                         "flag_without_empty_file_class": (L != nlv) and wl_sw is None, "wl": wl,
                         "trunc": bool(pe.truncated_result(t, ex if isinstance(ex, str) else None))})
        U = pd.DataFrame(rows, columns=["session_id", "mismatch", "flag", "flag_without_empty_file_class", "wl", "trunc"])
        fs = U.groupby("session_id").flag.any() if len(U) else pd.Series(dtype=bool)
        n, k = int(len(fs)), int(fs.sum())
        p, lo_, hi_ = stats.wilson(k, n) if n else (None, None, None)
        if n < 30:
            hl = "INSUFFICIENT_N"
        elif p <= 0.05 and hi_ <= 0.10:
            hl = "ALIVE"
        elif p <= 0.20:
            hl = "WEAK"
        else:
            hl = "DEAD"
        out[sp] = {"raw_join": info, "units": int(len(U)), "mismatches": int(U.mismatch.sum()) if len(U) else 0,
                   "mismatch_by_whitelist_class": dict(Counter(U[U.mismatch].wl.fillna("UNEXPLAINED"))) if len(U) else {},
                   "units_flagged": int(U.flag.sum()) if len(U) else 0,
                   "units_flagged_without_empty_file_class": int(U.flag_without_empty_file_class.sum()) if len(U) else 0,
                   "sessions_decided": n, "sessions_flagged": k, "session_rate": {"k": k, "n": n, "p": p, "lo": lo_, "hi": hi_},
                   "honest_leg": hl, "n7_leg": "NOT_RUN (no R4 tamper set in this group script)",
                   "label": hl if hl in ("INSUFFICIENT_N", "DEAD") else "NOT_RUN"}
    by = {sp: out[sp]["label"] for sp in out}
    sh = "E" if by["E"] not in ("INSUFFICIENT_N",) else "B"
    d = out[sh]
    lab = show_label(by)
    if lab == "NOT_RUN":
        lab = f"NOT_RUN(N7 leg not run; honest leg {out['E']['honest_leg']} on E)"
    return out, cell(lab, {"sessions_flagged": d["sessions_flagged"], "sessions_decided": d["sessions_decided"],
                           "units_flagged": d["units_flagged"], "units": d["units"]},
                     d["units"], d["sessions_decided"], [d["session_rate"]["lo"], d["session_rate"]["hi"]],
                     f"r4.{sh}", by_split=by, honest_leg_by_split={sp: out[sp]["honest_leg"] for sp in out})


# ===================================================================================================== main
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", choices=CORPORA)
    ap.add_argument("--only", default="")
    args = ap.parse_args(argv)
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    pj = pe.check_frozen()
    for corpus in ([args.corpus] if args.corpus else CORPORA):
        calp = pe.OUT_E / f"prereg_e_calibration_{corpus}.json"
        cal = json.loads(calp.read_text(encoding="utf-8"))
        ext = [e for e in pj["change_log"] if e.get("corpus") == corpus]
        assert ext and ext[0]["calibration_sha256"] == pe.sha256_file(calp), "calibration file differs from the registered one"
        excl, excl_sha = exclusions(corpus)
        frames, finfo = {}, {}
        for sp in ("B", "E"):
            frames[sp], finfo[sp] = load_split(corpus, sp, excl)
        idx, idx_sha = corpus_index(corpus)
        J = {"item": f"newcorp_measure_{corpus}", "group": GROUP, "corpus": corpus, "script": SCRIPT,
             "unit_argument_D1": PROXY,
             "prereg": {"prereg_e_json_sha256": pe.sha256_file(pe.PREREG_E_JSON),
                        "spec_module_sha256_lf": pj["provenance"]["spec_module_sha256_lf"],
                        "extension_record": ext[0], "decisions": "prereg_e.json change_log[-1] D1-D7"},
             "calibration_file": str(calp.relative_to(ROOT)).replace("\\", "/"),
             "calibration_sha256": pe.sha256_file(calp),
             "inputs_sha256": {f"analysis/cache/{corpus}_{sp}.parquet": pe.sha256_file(pe.CACHE / f"{corpus}_{sp}.parquet")
                               for sp in ("B", "E")},
             "index_sha256": idx_sha, "exclusions_D5": {"file_sha256": excl_sha, "B": len(excl["B"]), "E": len(excl["E"])},
             "splits": finfo, "cells": {}, "n_cells_computed": 0}
        th = thresholds(cal, pj)
        J["thresholds_from_A"] = th
        J["field_gate_B"] = field_gate_B(frames["B"])
        fg = J["field_gate_B"]
        if not only or "R1" in only:
            r1, c = run_r1(corpus, frames, cal, idx)
            J["r1"] = r1
            J["cells"]["R1_bracket"] = c
        fr3 = frames_with_pooled(frames)
        steps = [("P1", lambda: run_p1(fr3, th)), ("P2", lambda: run_p2(fr3, th)), ("P3", lambda: run_p3(fr3, th)),
                 ("P4", lambda: run_p4(fr3)), ("N1", lambda: run_n1(fr3, th)), ("N2", lambda: run_n2(fr3, th)),
                 ("N3", lambda: run_n3(fr3)), ("N4", lambda: run_n4(fr3)), ("N5", lambda: run_n5(fr3, th)),
                 ("R4", lambda: run_r4(corpus, idx, fr3))]
        for name, fn in steps:
            if only and name not in only:
                continue
            log(corpus, name)
            try:
                res = fn()
            except Exception as ex:  # recorded as NOT_RUN with the error, never hidden
                import traceback
                J[name.lower()] = {"error": f"{type(ex).__name__}: {ex}", "traceback_tail": traceback.format_exc().splitlines()[-4:]}
                J["cells"][name] = cell(f"NOT_RUN(error: {type(ex).__name__})", None, None, None, None, name.lower())
                log(corpus, name, "ERROR", type(ex).__name__, ex)
                continue
            if name == "P1":
                J["p1"], J["cells"]["P1_latency"] = res
            elif name == "P2":
                J["p2"], cs = res
                J["cells"]["P2_knowledge"] = cs["main"]
                J["cells"]["P2_knowledge_subagent"] = cs["sub"]
            elif name == "P3":
                J["p3"], J["cells"]["P3a_zero_error"], J["cells"]["P3b_reaction"] = res
            elif name == "P4":
                J["p4"], cs, J["p4_provenance"] = res
                J["cells"].update(cs)
            elif name == "N5":
                J["n5"], cs = res
                J["cells"].update(cs)
            else:
                key = {"N1": "N1", "N2": "N2", "N3": "N3", "N4": "N4", "R4": "R4_dual"}[name]
                J[name.lower()], J["cells"][key] = res
        J["cells"]["R2_image"] = cell("NOT_TESTABLE(per-response prompt IMAGE token counts + GUI actions)", None,
                                      fg["image_usage_rows"], None, None, "field_gate_B.image_usage_rows")
        J["cells"]["R3_git"] = cell("NOT_TESTABLE(external commit table linked by repo)", None, fg["commit_claims"],
                                    None, None, "field_gate_B.external_commit_table",
                                    note="commit claims printed by shell results are counted in field_gate_B.r3_git_claims_B")
        J["cells"]["R5_ledger"] = cell("NOT_TESTABLE(external usage tally)", None, None, None, None,
                                       "field_gate_B.external_usage_tally")
        J["n_cells_computed"] = len(J["cells"])
        J["runtime_s"] = round(time.time() - T0, 1)
        out = pe.OUT_E / f"newcorp_measure_{corpus}.json"
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(clean(J), fh, indent=1, default=str)
        log("wrote", out)
        del frames
        gc.collect()


if __name__ == "__main__":
    main(sys.argv[1:])
