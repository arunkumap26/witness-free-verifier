"""Phase E item F1 + R1: the request-id clock bracket, its placebo (Step 0), the honest failures, the pre-registered
benign corrections, the effective false-positive rate, and the R1 honest-rate / kill-rule legs.

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_f1_bracket
Writes analysis/out/phase_e/f1_bracket.json (raw numbers and mechanically computed labels only).
Interpretation: analysis/notes/phase_e_f1_bracket.md.

Pre-registration: analysis/PREREG_E.md section 1.4 (R1) and 1.5 (F1), prereg_e.json followups.F1_bracket_failures and
a1.proposal_rules (R1_specific). check_frozen() runs first. Every bracket, placebo, category and injector call is the
pre-registered code in prereg_e_common.py (bracket_responses, bracket_streams, placebo_shift, roll_ids,
piecewise_consistent, bracket_benign_categories, atk_*). Nothing in the prereg files is edited.

Data read: swechat B and E (unit swechat/claude_code) and cc_local B, through read_cache only. Never A, never H.
Raw reads: swechat public transcripts (data/swe-chat-pinned/transcripts) for the B and E sessions holding an inconsistent
stream (raw inspection + AC1 parser audit). No cc_local raw file is opened (privacy; the prereg pins a cc_local raw
source for R4 only), so cc_local AC1 is NOT_RUN. cc_local output is aggregates only: no session ids, no text, no tools
beyond the public Claude Code tool names, strata relabelled by size rank.

Implementation choices fixed here before any run (the prereg leaves them to the implementer):
  1. Unit frames: pc.unit_frames (swechat format = claude_code). text is truncated to its first 200 characters after
     the truncation flag is computed on the full text: bracket_benign_categories reads only t[:200] and startswith().
  2. "Another session of the corpus" (restamped_copy and its dedupe) = another session of the readable corpus:
     swechat B u E (all formats), cc_local B. A is calibration-only and H is never read (logged as a deviation).
  3. Corrections. Per category c, the pre-registered correction is applied to every stream whose gap exceeds 2,000 ms:
       restamped_copy  R rows whose request id is copied and whose session is not the smallest holder are dropped
                       before streams are built (placebo then runs on the deduped table);
       clock_step      not flagged if piecewise_consistent(lo, hi);
       concurrent      abstain if the category is present;
       api_retry / compaction / user_input_binding / long_gap: while inconsistent, a binding response (k_L checked as
                       L-binding, k_U as U-binding, by bracket_benign_categories on a one-binding row) that carries c is
                       dropped and L/U recomputed; fewer than 2 responses left = abstain;
       whole_second / vertex_or_bedrock: tolerance 3,000 ms if c is present on a binding event.
     Abstain counts as not flagged; the denominator stays all streams; abstentions are counted separately.
     Several adopted corrections are applied in the order dedupe -> drops -> clock_step -> tolerance -> abstain.
     Adoption is decided per unit on its B split (swechat/claude_code B; cc_local B, which has no E).
  4. R1 kill rule (Phase D rule adopted in R1_specific) is evaluated on stream-level flagged rates. The back-dating
     leg uses the F1 placebo (placebo_shift, response first event D earlier). The other single-call / single-response
     types are run here at stream level with the N7 injectors (atk_time, atk_id_swap, atk_id_splice,
     atk_delete_response, atk_delete_pair, atk_insert_pair): one tamper per stream, each from the untampered stream,
     target rng_for(attack, param, session, stream), donor rng_for('donor', attack, param, session, stream).
     "Back-dating" types = time_response_early and time_tail_early (both move response first events earlier than
     their ids); every other type counts as "other". The honest bar is the session-clustered CI hi of the same split
     (per-event Wilson hi if the numerator is 0). Pooled B u E is primary for swechat/claude_code; E is reported
     separately. These are R1 kill-rule cells, not N7 cells: the N7 session-level DETECTS / PARTIAL leg of the R1
     verdict is read from N7's output if it exists, otherwise that leg is NOT_RUN and the verdict says so.
  5. Stream-level tampering is evaluated on the frame of the target stream only (bracket_responses depends only on the
     stream's own responses and inputs); the honest per-stream flags on these frames are checked against the
     whole-session computation and the agreement is reported.
  6. R1 honest-leg label: ALIVE-eligible if rate <= 0.05 and CI hi <= 0.10; WEAK-eligible if rate <= 0.20; else DEAD.
     Artifact checks AC2-AC5 and the strata recompute this label (AC1 compares fields with the raw source).
     Stratum label = honest-leg label if the 30 s placebo CI lo > the stratum's honest CI hi, else DEAD; a stratum is
     reportable at >= 30 streams from >= 5 sessions.
"""
import gc
import json
import os
import pickle
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.lib import stats
from analysis.lib.ir import parse_ts
from analysis.probes import prereg_common as pc
from analysis.probes import prereg_e_common as pe

ROOT = pe.ROOT
OUT = pe.OUT_E / "f1_bracket.json"
SCRATCH = Path(os.environ.get("F1_SCRATCH", str(Path(os.environ.get("TEMP", ".")) / "f1_bracket_chunks")))
DEV = os.environ.get("F1_DEV")  # development: limit sessions, write to scratch
TOL = pe.BRACKET_TOL_MS
TOL_CORR = 3000.0
CATS = ["restamped_copy", "clock_step", "concurrent_streams", "api_retry", "compaction", "user_input_binding",
        "long_gap", "whole_second", "vertex_or_bedrock"]
DROP_CATS = {"api_retry", "compaction", "user_input_binding", "long_gap"}
TOL_CATS = {"whole_second", "vertex_or_bedrock"}
BACKDATE_TYPES = {"time_response_early", "time_tail_early"}
PLACEBO = [("back", 5000), ("back", 30000), ("late", 5000), ("late", 30000), ("late", 300000)]
COLS = ["session_id", "stratum", "seq", "kind", "ts", "request_id", "is_subagent", "agent_id", "uuid", "call_id",
        "parent_call_id", "tool", "tool_raw", "model", "text", "extra"]
SLIM = ["session_id", "seq", "kind", "ts", "request_id", "is_subagent", "agent_id", "call_id", "parent_call_id"]
ATTACKS = ([("time_response_early", D) for D in pe.GRID_D] +
           [("time_response_late", D) for D in pe.GRID_D_LATE_CHECK] +
           [("time_result_late", D) for D in pe.GRID_D] +
           [("time_result_early", D) for D in pe.GRID_D] +
           [("time_tail_late", D) for D in pe.GRID_D] +
           [("time_tail_early", D) for D in pe.GRID_D] +
           [("id_swap_adjacent", "-"), ("id_splice_foreign", "random"), ("id_splice_foreign", "nearest"),
            ("delete_response", "-"), ("delete_pair", "-"), ("insert_pair_consistent", "-"),
            ("insert_pair_squeezed", "-")])
UNITS = [("swechat", "B", "swechat/claude_code"), ("swechat", "E", "swechat/claude_code"), ("cc_local", "B", "cc_local")]
PRIVATE = {"cc_local"}
T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:7.1f}s]", *a, flush=True)


# ===================================================================================================== small helpers
def wil(k, n):
    p, lo, hi = stats.wilson(int(k), int(n))
    return {"k": int(k), "n": int(n), "p": p, "lo": lo, "hi": hi}


def crate(flags, sids):
    """Session-clustered rate (pe.rate_by_session) of boolean flags over streams."""
    if len(flags) == 0:
        return {"rate": None, "lo": None, "hi": None, "n_sessions": 0, "num": 0.0, "den": 0.0}
    return pe.rate_by_session(np.asarray(flags, dtype=bool), np.asarray(sids))


def bar_hi(r):
    """Honest upper bound used by the kill rule: cluster CI hi; per-event Wilson hi if the numerator is 0."""
    if r.get("rate") is None:
        return None
    if r["num"] == 0:
        return r.get("wilson_hi_per_event")
    return r["hi"]


def honest_leg(r):
    """R1 honest-rate leg (prereg a1.proposal_rules): ALIVE/WEAK/DEAD eligibility from a session-clustered rate."""
    if r is None or r.get("rate") is None:
        return None
    hi = bar_hi(r)
    if r["rate"] <= 0.05 and hi is not None and hi <= 0.10:
        return "ALIVE"
    if r["rate"] <= 0.20:
        return "WEAK"
    return "DEAD"


def qd(v, sids=None, qs=(0.05, 0.25, 0.5, 0.75, 0.95)):
    v = np.asarray(v, dtype=float)
    ok = np.isfinite(v)
    out = {"n": int(ok.sum())}
    if sids is not None:
        out["n_sessions"] = int(len(set(np.asarray(sids)[ok])))
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
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if not np.isfinite(f) else f
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, set):
        return sorted(clean(v) for v in o)
    return o


# ===================================================================================================== loading
def load_unit(corpus, split, unit, keep_sessions=None):
    df = pe.read_cache(corpus, split, COLS)
    if keep_sessions is not None:
        df = df[df.session_id.isin(keep_sessions)]
    fr = pc.unit_frames(corpus, df)
    u = fr[unit].reset_index(drop=True)
    del df, fr
    gc.collect()
    is_res = (u.kind == "result").to_numpy()
    tr = np.zeros(len(u), dtype=bool)
    txt = u.text.astype(object).to_numpy()
    ex = u.extra.astype(object).to_numpy()
    for i in np.flatnonzero(is_res):
        tr[i] = pe.truncated_result(txt[i], ex[i])
    u["_trunc"] = tr
    u["text"] = [t[:200] if isinstance(t, str) else None for t in txt]
    del txt, ex
    u["_st"] = pe._stream(u.is_subagent, u.agent_id)
    gc.collect()
    return u


def copied_ids(corpus):
    """Request ids present in more than one session of the readable corpus, and the smallest holder session."""
    splits = ("B", "E") if corpus == "swechat" else ("B",)
    parts = []
    for sp in splits:
        d = pe.read_cache(corpus, sp, ["session_id", "request_id"])
        parts.append(d[d.request_id.notna()].drop_duplicates())
    d = pd.concat(parts, ignore_index=True).drop_duplicates()
    ns = d.groupby("request_id").session_id.nunique()
    cop = set(ns[ns > 1].index)
    keep = d[d.request_id.isin(cop)].groupby("request_id").session_id.min().to_dict()
    within = {}
    for sp, p in zip(splits, parts):
        n2 = p.groupby("request_id").session_id.nunique()
        within[sp] = int((n2 > 1).sum())
    return cop, keep, {"copied_ids_readable_corpus": len(cop), "copied_ids_within_split": within,
                       "readable_corpus": "+".join(splits)}


# ===================================================================================================== detector core
def _k(x):
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return int(f) if np.isfinite(f) else None


def recs(S):
    """bracket_streams rows as dicts with integer (or None) binding labels."""
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
    """Status of one stream under the correction set corr: 'flag' | 'ok' | 'abstain'. cats0: full category set."""
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
    """One bracket table (honest or placebo, deduped or not) with streams, full categories of over-tolerance streams."""

    def __init__(self, R, u_by_s, copied, label):
        self.R, self.label = R, label
        self.S = pe.bracket_streams(R)
        self.groups = stream_rows(R)
        self.cats = {}
        over = self.S[np.isfinite(self.S.gap) & (self.S.gap > TOL)]
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
        return np.array(out)


def dedupe(R, keep):
    rid = R.request_id.astype(object)
    holder = rid.map(keep)
    drop = holder.notna() & (R.session_id != holder)
    return R[~drop.to_numpy()]


def summarize_status(st, sids):
    st = np.asarray(st)
    flags = st == "flag"
    r = crate(flags, sids)
    return {"streams": int(len(st)), "flagged": int(flags.sum()), "abstained": int((st == "abstain").sum()),
            "rate_by_session": r, "wilson_per_stream": wil(flags.sum(), len(st))}


# ===================================================================================================== stream-level tamper
def _ev(s, sid, st):
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
    for _ in range(10_000):
        j = int(rng.integers(0, n))
        if sessions[j] != sid:
            return j
    return None


def tamper_stream(sid, st, s, splice, pre):
    """All ATTACKS on one stream frame s (that stream's events only). splice: (sessions, ids, embs) of every decoded
    response of the unit/split; pre: donors pre-selected in the parent with the same donor rng. Returns
    (list of (attack, param, status, extra), honest flag of the stream frame)."""
    out = []
    R0 = pe.bracket_responses(s)
    R0 = R0[R0.stream == st].sort_values("seq")
    if len(R0) < 2:
        return [(a, p, "ineligible", None) for a, p in ATTACKS], None
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
    for attack, param in ATTACKS:
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
                s2 = pe.atk_insert_pair(s, results[i], c, r, mode=mode, donor_gap_s=float(dgap),
                                        donor_lat_s=float(dlat))
                extra = {"shift_s": float(dgap + dlat)} if mode == "consistent" else None
                if s2 is None:
                    out.append((attack, param, "skipped", None))
                    continue
            else:
                raise ValueError(attack)
            out.append((attack, param, _ev(s2, sid, st), extra))
        except Exception as e:  # recorded, never silently dropped
            out.append((attack, param, "error", {"error": repr(e)[:200]}))
    return out, honest


def _worker(path):
    with open(path, "rb") as f:
        pay = pickle.load(f)
    res = []
    for sid, st, s, pre in pay["streams"]:
        rows, honest = tamper_stream(sid, st, s, pay["splice"], pre)
        res.append((sid, st, honest, rows))
    return res


def donor_pool(u):
    """Main-stream call/result pairs of the unit/split with parseable stamps; gap = call - previous event, lat =
    result - call (both >= 0)."""
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
        "pairs": int(len(m)), "sessions": int(m.session_id.nunique()),
        "gap_plus_lat_s": qd((m.gap + m.lat).to_numpy())}


def run_tamper(u, R, S, tag):
    """Stream-level single-call / single-response tamper set on every stream with >= 2 decoded responses."""
    SCRATCH.mkdir(parents=True, exist_ok=True)
    splice_df = R[["session_id", "request_id", "emb"]].sort_values("emb")
    splice = (splice_df.session_id.to_numpy(dtype=object), splice_df.request_id.to_numpy(dtype=object),
              splice_df.emb.to_numpy(dtype=float))
    (dc, dr, dgap, dlat, dsess), dinfo = donor_pool(u)
    keys = list(zip(S.session_id, S.stream))
    v = u[SLIM + ["_st"]].copy()
    # missing stamps are pd.NA in the cache; the injectors' own missing-stamp path expects None (deviation logged)
    v["ts"] = pd.Series([t if isinstance(t, str) else None for t in v.ts.astype(object)], index=v.index, dtype=object)
    by = {k: g for k, g in v.groupby(["session_id", "_st"], sort=False)}
    del v
    frames = []
    for s, st in keys:
        pre = {}
        j = _pick_other(pe.rng_for("donor", "id_splice_foreign", "random", s, st), splice[0], s)
        pre[("splice", "random")] = j
        for att in ("insert_pair_consistent", "insert_pair_squeezed"):
            j = _pick_other(pe.rng_for("donor", att, "-", s, st), dsess, s) if len(dsess) else None
            pre[("insert", att)] = None if j is None else (dc.iloc[j], dr.iloc[j], float(dgap[j]), float(dlat[j]))
        frames.append((s, st, by[(s, st)].drop(columns="_st"), pre))
    sizes = np.array([len(f[2]) for f in frames])
    n_chunks = min(32, max(1, len(frames)))
    order = np.argsort(-sizes)
    buckets, load = [[] for _ in range(n_chunks)], np.zeros(n_chunks)
    for i in order:
        b = int(np.argmin(load))
        buckets[b].append(frames[i])
        load[b] += sizes[i] + 50
    paths = []
    for b, fr in enumerate(buckets):
        p = SCRATCH / f"{tag}_{b}.pkl"
        with open(p, "wb") as f:
            pickle.dump({"streams": fr, "splice": splice}, f, protocol=pickle.HIGHEST_PROTOCOL)
        paths.append(str(p))
    del by, frames, buckets
    gc.collect()
    res = []
    with ProcessPoolExecutor(max_workers=int(os.environ.get("F1_WORKERS", "8"))) as ex:
        for part in ex.map(_worker, paths):
            res.extend(part)
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass
    return res, dinfo


def tamper_cells(res, honest_by_key, honest_bar, honest_rate, honest_wilson_hi=None):
    """Aggregate stream-level tamper results per attack x param. honest_wilson_hi: per-stream Wilson hi of the honest
    rate, used only for the bar-sensitivity column (the verdict bar is honest_bar)."""
    rows = defaultdict(list)
    agree = Counter()
    for sid, st, h, rr in res:
        if h is not None:
            agree["match" if h == honest_by_key[(sid, st)] else "mismatch"] += 1
        for a, p, status, extra in rr:
            rows[(a, p)].append((sid, st, status, extra))
    cells = {}
    for (a, p), lst in rows.items():
        st_ = np.array([x[2] for x in lst])
        elig = np.isin(st_, ["flag", "ok", "abstain"])
        sids = np.array([x[0] for x in lst])[elig]
        flags = (st_ == "flag")[elig]
        hon = np.array([honest_by_key[(x[0], x[1])] for x in lst])[elig]
        r = crate(flags, sids)
        rh = crate(hon, sids)
        cell = {"attack": a, "param": p, "eligible_streams": int(elig.sum()), "flagged": int(flags.sum()),
                "abstained": int((st_ == "abstain").sum()), "ineligible": int((st_ == "ineligible").sum()),
                "skipped": int((st_ == "skipped").sum()), "errors": int((st_ == "error").sum()),
                "rate_by_session": r, "wilson_per_stream": wil(flags.sum(), elig.sum()),
                "honest_same_streams_rate_by_session": rh,
                "honest_bar_hi": honest_bar, "honest_rate": honest_rate,
                "clears_honest_bar": bool(r.get("lo") is not None and honest_bar is not None and r["lo"] > honest_bar),
                "clears_wilson_bar_sensitivity": (bool(r.get("lo") is not None and r["lo"] > honest_wilson_hi)
                                                  if honest_wilson_hi is not None else None),
                "back_dating_type": a in BACKDATE_TYPES}
        ex = [x[3] for x in lst if x[3]]
        if a == "time_result_early":
            cell["clamped"] = int(sum(1 for e in ex if e.get("clamped")))
        if a == "id_splice_foreign":
            offs = np.array([e["donor_offset_ms"] for e in ex if "donor_offset_ms" in e], dtype=float)
            cell["donor_offset_ms"] = qd(offs)
            cell["donor_offset_abs_gt_1day"] = int((np.abs(offs) > 86_400_000).sum())
            cell["donor_offset_abs_le_tol"] = int((np.abs(offs) <= TOL).sum())
        if a == "insert_pair_consistent":
            cell["inserted_shift_s"] = qd([e["shift_s"] for e in ex if "shift_s" in e])
        errs = [e.get("error") for e in ex if isinstance(e, dict) and "error" in e]
        if errs:
            cell["error_examples"] = sorted(set(errs))[:3]
        cells[f"{a}|{p}"] = cell
    return cells, dict(agree)


# ===================================================================================================== raw inspection
def raw_index(session_id, want):
    """uuid -> raw entry descriptors for the given uuids of one public swechat transcript (top-level and nested)."""
    p = pe.SWE_TRANSCRIPTS / f"{session_id}.jsonl"
    out, n_lines, uuid_lines, versions = {}, 0, Counter(), Counter()
    if not p.exists():
        return None
    with open(p, encoding="utf-8", errors="replace") as f:
        for ln, line in enumerate(f):
            n_lines += 1
            try:
                x = json.loads(line)
            except ValueError:
                continue
            if not isinstance(x, dict):
                continue
            ents = [(x, False, x.get("timestamp"))]
            d = x.get("data") if isinstance(x.get("data"), dict) else {}
            if x.get("type") == "progress" and d.get("type") == "agent_progress" and isinstance(d.get("message"), dict):
                ents.append((d["message"], True, x.get("timestamp")))
            for e, nested, outer in ents:
                uid = e.get("uuid")
                if e.get("version"):
                    versions[str(e.get("version"))] += 1
                if not uid:
                    continue
                uuid_lines[uid] += 1
                if uid in want and uid not in out:
                    msg = e.get("message") if isinstance(e.get("message"), dict) else {}
                    content = msg.get("content")
                    btypes = sorted({b.get("type") for b in content if isinstance(b, dict)}) if isinstance(content, list) else (["str"] if isinstance(content, str) else [])
                    out[uid] = {"line": ln, "nested": nested, "entry_type": e.get("type"),
                                "timestamp": e.get("timestamp") or outer, "outer_timestamp": outer if nested else None,
                                "requestId": e.get("requestId"), "version": e.get("version"),
                                "isSidechain": e.get("isSidechain"), "agentId": e.get("agentId") or d.get("agentId"),
                                "isMeta": e.get("isMeta"), "isCompactSummary": e.get("isCompactSummary"),
                                "userType": e.get("userType"), "has_toolUseResult": "toolUseResult" in e,
                                "content_block_types": btypes, "subtype": e.get("subtype")}
    return {"entries": out, "n_lines": n_lines, "uuids_on_gt1_line": int(sum(1 for v in uuid_lines.values() if v > 1)),
            "versions": dict(versions)}


def ms_of(ts):
    t = parse_ts(ts) if isinstance(ts, str) else None
    return None if t is None else t.timestamp() * 1000.0


def inspect_stream(row, Rg, u_sess, copied, private, raw):
    """Descriptors of one inconsistent stream: binding responses, their inputs, categories, raw agreement."""
    d = {"n_responses": int(row["n"]), "gap_ms": float(row["gap"]), "L_ms": float(row["L"]), "U_ms": float(row["U"]),
         "categories": sorted(cats_full(row, Rg, u_sess, copied)),
         "piecewise_consistent": bool(pe.piecewise_consistent(Rg.lo.to_numpy(), Rg.hi.to_numpy())),
         "stream_is_main": row["stream"] == "main"}
    pos = {k: i for i, k in enumerate(Rg.sort_values("seq").index)}
    d["k_L_position"], d["k_U_position"] = pos.get(row["k_L"]), pos.get(row["k_U"])
    d["k_L_after_k_U"] = bool(d["k_L_position"] is not None and d["k_U_position"] is not None
                              and d["k_L_position"] > d["k_U_position"])
    d["k_L_equals_k_U"] = bool(row["k_L"] == row["k_U"])
    ev = u_sess.set_index("seq", drop=False)
    for name in ("k_L", "k_U"):
        k = row[name]
        if k is None:
            continue
        r = Rg.loc[k]
        fs = _k(r["seq"])
        ps = _k(r.get("prev_seq"))
        first = ev.loc[fs] if fs in ev.index else None
        prev = ev.loc[ps] if ps is not None and ps in ev.index else None
        b = {"lo_ms": float(r["lo"]) if np.isfinite(r["lo"]) else None, "hi_ms": float(r["hi"]),
             "input_to_first_event_ms": float(r["first_ms"] - r["prev_ms"]) if np.isfinite(r["prev_ms"]) else None,
             "prev_kind": r.get("prev_kind") if isinstance(r.get("prev_kind"), str) else None,
             "first_event_kind": first["kind"] if first is not None else None,
             "prev_input_tool": (pc.private_key(prev["tool"] if isinstance(prev["tool"], str) else None) if private
                                 else first_tool(prev)) if prev is not None else None,
             "request_id_prefix": re.match(r"^(req_(?:vrtx_|bdrk_)?)", str(r["request_id"])).group(1)
             if isinstance(r["request_id"], str) else None,
             "first_ts_fraction_digits": len(str(r["ts"]).split(".")[1].rstrip("Z")) if "." in str(r["ts"]) else 0}
        if prev is not None and not private:
            b["prev_input_extra_keys"] = sorted(pc.jl(prev["extra"]).keys()) if isinstance(prev["extra"], str) else []
        if raw is not None and not private:
            for which, evr in (("first", first), ("prev", prev)):
                if evr is None or not isinstance(evr["uuid"], str):
                    continue
                e = raw["entries"].get(evr["uuid"])
                if e is None:
                    b[f"raw_{which}"] = {"found": False}
                    continue
                ir_ms, raw_ms = ms_of(evr["ts"]), ms_of(e["timestamp"])
                rr = {"found": True, "ts_equal": bool(ir_ms is not None and raw_ms is not None and abs(ir_ms - raw_ms) < 0.5),
                      "ir_minus_raw_ms": (ir_ms - raw_ms) if (ir_ms is not None and raw_ms is not None) else None,
                      "nested": e["nested"], "entry_type": e["entry_type"], "version": e["version"],
                      "isSidechain": e["isSidechain"], "isMeta": e["isMeta"], "userType": e["userType"],
                      "has_toolUseResult": e["has_toolUseResult"], "content_block_types": e["content_block_types"],
                      "isCompactSummary": e["isCompactSummary"]}
                if which == "first":
                    rr["requestId_equal"] = bool(e["requestId"] == r["request_id"])
                if e["nested"] and e["outer_timestamp"]:
                    om = ms_of(e["outer_timestamp"])
                    rr["inner_minus_outer_ms"] = (raw_ms - om) if (om is not None and raw_ms is not None) else None
                b[f"raw_{which}"] = rr
        d[name] = b
    if raw is not None and not private:
        d["raw_session"] = {"n_lines": raw["n_lines"], "uuids_on_gt1_line": raw["uuids_on_gt1_line"],
                            "versions": raw["versions"]}
    return d


def first_tool(ev):
    if ev is None:
        return None
    t = ev.get("tool_raw") if isinstance(ev.get("tool_raw"), str) else ev.get("tool")
    return t if isinstance(t, str) else None


def ac1_audit(inc_rows, Gs, u_by_s, unit):
    """AC1: every inconsistent stream (<= 30, audit_sample) checked against the raw transcript: binding stamps and
    request ids. A differing field that changes the stream's contribution counts as a parser difference."""
    keys = [(r["session_id"], r["stream"]) for r in inc_rows]
    pick = set(pe.audit_sample(keys, seed_parts=("audit", "R1", unit)))
    n, diff, notes = 0, 0, Counter()
    for r in inc_rows:
        if (r["session_id"], r["stream"]) not in pick:
            continue
        n += 1
        g = Gs[(r["session_id"], r["stream"])]
        u_sess = u_by_s[r["session_id"]]
        want = set(u_sess.uuid.dropna().astype(str))
        raw = raw_index(r["session_id"], want)
        if raw is None:
            diff += 1
            notes["raw_file_missing"] += 1
            continue
        ev = u_sess.set_index("seq", drop=False)
        bad = False
        for name in ("k_L", "k_U"):
            k = r[name]
            if k is None:
                continue
            rr = g.loc[k]
            for seqv, which in ((_k(rr["seq"]), "first"), (_k(rr.get("prev_seq")), "prev")):
                if seqv is None or seqv not in ev.index:
                    continue
                e = ev.loc[seqv]
                ent = raw["entries"].get(e["uuid"]) if isinstance(e["uuid"], str) else None
                if ent is None:
                    notes[f"{which}_uuid_not_found"] += 1
                    continue
                a, b = ms_of(e["ts"]), ms_of(ent["timestamp"])
                if a is None or b is None or abs(a - b) >= 1.0:
                    bad = True
                    notes[f"{which}_ts_differs"] += 1
                if which == "first" and ent["requestId"] != rr["request_id"]:
                    bad = True
                    notes["request_id_differs"] += 1
        diff += int(bad)
    res = "FAIL" if diff >= pe.AUDIT_FAIL else ("PARSER_NOTE" if diff == 1 else "PASS")
    return {"audited_streams": n, "streams_with_differences": diff, "notes": dict(notes), "result": res,
            "fields": "binding response first-event stamp + request id, binding input stamp, vs raw entry by uuid"}


# ===================================================================================================== per unit/split
def honest_block(R, S):
    inc = S.inconsistent.to_numpy()
    cons = S[~S.inconsistent]
    out = {"responses_decoded": int(len(R)), "sessions_with_decoded_responses": int(R.session_id.nunique()),
           "streams_ge2": int(len(S)), "streams_main": int((S.stream == "main").sum()),
           "sessions_with_streams": int(S.session_id.nunique()), "inconsistent_streams": int(inc.sum()),
           "inconsistent_streams_main": int((inc & (S.stream == "main").to_numpy()).sum()),
           "rate_by_session": crate(inc, S.session_id.to_numpy()),
           "wilson_per_stream": wil(inc.sum(), len(S)),
           "sessions_with_inconsistent_stream": int(S[S.inconsistent].session_id.nunique()),
           "tolerance_sensitivity_streams_over": {f"{t}": int((np.isfinite(S.gap) & (S.gap > t)).sum())
                                                  for t in (0, 1000, 2000, 3000, 5000, 10000, 60000)},
           "slack_U_minus_L_consistent_ms": qd((cons.U - cons.L).to_numpy(), cons.session_id.to_numpy()),
           "slack_p50_cluster": stats.cluster_quantile((cons.U - cons.L).to_numpy(), cons.session_id.to_numpy(), 0.5)
           if len(cons) else None,
           "streams_with_nan_L": int((~np.isfinite(S.L)).sum())}
    return out


def placebo_block(R, S_h, u_by_s, copied):
    out = {}
    for kind, D in PLACEBO:
        RP = pe.placebo_shift(R, D if kind == "back" else -D)
        SP = pe.bracket_streams(RP)
        f = SP.inconsistent.to_numpy()
        out[f"{kind}_{D // 1000}s"] = {"streams": int(len(SP)), "flagged": int(f.sum()),
                                       "share": float(f.mean()) if len(f) else None,
                                       "wilson_per_stream": wil(f.sum(), len(SP)),
                                       "rate_by_session": crate(f, SP.session_id.to_numpy())}
    RR = pe.roll_ids(R)
    SR = pe.bracket_streams(RR)
    f = SR.inconsistent.to_numpy()
    out["roll_ids_reference"] = {"streams": int(len(SR)), "flagged": int(f.sum()), "wilson_per_stream": wil(f.sum(), len(SR)),
                                 "rate_by_session": crate(f, SR.session_id.to_numpy())}
    return out


def categories_block(unit, split, V, u_by_s, copied, private, do_raw):
    S = V.S
    inc = S[S.inconsistent]
    cons_recs = recs(S[~S.inconsistent].reset_index(drop=True))
    rng = pe.rng_for("F1ctl", unit, split)
    n_ctl = min(5 * len(inc), len(cons_recs))
    ctl_idx = sorted(rng.choice(len(cons_recs), size=n_ctl, replace=False).tolist()) if n_ctl else []
    inc_recs = recs(inc)
    inc_c = [V.cats[(r["session_id"], r["stream"])] for r in inc_recs]
    ctl_c = []
    for i in ctl_idx:
        r = cons_recs[i]
        ctl_c.append(cats_full(r, V.groups[(r["session_id"], r["stream"])], u_by_s[r["session_id"]], copied))
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
    out = {"control_rule": "5 consistent streams per inconsistent stream, rng_for('F1ctl', unit, split)",
           "categories": tab, "category_vectors_inconsistent": dict(vec),
           "unexplained_streams_no_category": int(sum(1 for x in inc_c if not x))}
    streams = []
    for r, cset in zip(inc_recs, inc_c):
        raw = raw_index(r["session_id"], set(u_by_s[r["session_id"]].uuid.dropna().astype(str))) if do_raw else None
        d = inspect_stream(r, V.groups[(r["session_id"], r["stream"])], u_by_s[r["session_id"]], copied, private, raw)
        if not private:
            d["session_id"], d["stream"] = r["session_id"], r["stream"]
        streams.append(d)
    out["inconsistent_streams"] = streams
    return out


def corrections_block(V_h, V_h_dd, V_p, V_p_dd, u_by_s, copied):
    """Per category: honest count and 5 s / 30 s placebo power under that single correction (B: adoption)."""
    base = {"honest": int((V_h.status(set(), u_by_s, copied) == "flag").sum()),
            "back_5s": float((V_p[5000].status(set(), u_by_s, copied) == "flag").mean()),
            "back_30s": float((V_p[30000].status(set(), u_by_s, copied) == "flag").mean())}
    out = {"uncorrected": base, "per_category": {}}
    adopted = []
    for c in CATS:
        corr = {c}
        if c == "restamped_copy":
            vh, v5, v30 = V_h_dd, V_p_dd[5000], V_p_dd[30000]
        else:
            vh, v5, v30 = V_h, V_p[5000], V_p[30000]
        sh = vh.status(corr, u_by_s, copied)
        s5 = v5.status(corr, u_by_s, copied)
        s30 = v30.status(corr, u_by_s, copied)
        rec = {"honest_flagged": int((sh == "flag").sum()), "honest_abstained": int((sh == "abstain").sum()),
               "streams": int(len(sh)), "back_5s_power": float((s5 == "flag").mean()),
               "back_30s_power": float((s30 == "flag").mean()),
               "back_5s_streams": int(len(s5)), "back_30s_streams": int(len(s30))}
        rec["lowers_honest"] = rec["honest_flagged"] < base["honest"]
        rec["keeps_30s_power"] = rec["back_30s_power"] >= 0.90
        rec["keeps_5s_power"] = abs(rec["back_5s_power"] - base["back_5s"]) <= 0.05
        rec["ADOPTED"] = bool(rec["lowers_honest"] and rec["keeps_30s_power"] and rec["keeps_5s_power"])
        if rec["ADOPTED"]:
            adopted.append(c)
        out["per_category"][c] = rec
    out["adopted"] = adopted
    return out


def corrected_eval(V_h, V_p, u_by_s, copied, adopted):
    corr = set(adopted)
    st = V_h.status(corr, u_by_s, copied)
    out = {"adopted": sorted(corr), "honest": summarize_status(st, V_h.S.session_id.to_numpy())}
    for D in (5000, 30000):
        sp = V_p[D].status(corr, u_by_s, copied)
        out[f"back_{D // 1000}s"] = summarize_status(sp, V_p[D].S.session_id.to_numpy())
    return out


def strata_block(unit, corpus, u, S, SP30, private):
    """Honest rate and 30 s placebo per stratum (model, repo, length tercile) -> stratum label, confinement."""
    sess = sorted(S.session_id.unique())
    mm = pe.session_model_map(u[u.session_id.isin(sess)])
    rep = pe.session_cluster_map(corpus, u[u.session_id.isin(sess)], kind="repo")
    cuts = pe.check_frozen()["resolved"]["length_terciles_A"][unit]["cuts"]
    P = pc.make_pairs(u[u.kind.isin(["call", "result"])][["session_id", "seq", "kind", "call_id", "ts"]])
    npairs = P.groupby("session_id").size().to_dict()
    lt = pe.length_tercile_map({s: npairs.get(s, 0) for s in sess}, cuts)
    axes = {"model": mm, "repo": rep, "length_tercile": lt}
    out = {}
    s_sid, p_sid = S.session_id.to_numpy(), SP30.session_id.to_numpy()
    s_inc, p_inc = S.inconsistent.to_numpy(), SP30.inconsistent.to_numpy()
    for ax, mp in axes.items():
        labels, rec = {}, {}
        s_lab = np.array([str(mp.get(s, "unknown")) for s in s_sid], dtype=object)
        p_lab = np.array([str(mp.get(s, "unknown")) for s in p_sid], dtype=object)
        sz = Counter(s_lab)
        rename = {k: f"cluster_{i + 1}" for i, (k, _) in enumerate(sz.most_common())} if (private and ax != "length_tercile") else {}
        for k in sz:
            m, mp_ = s_lab == k, p_lab == k
            n, ns = int(m.sum()), int(len(set(s_sid[m])))
            if n < 30 or ns < 5:
                labels[rename.get(k, k)] = None
                continue
            rh = crate(s_inc[m], s_sid[m])
            rp = crate(p_inc[mp_], p_sid[mp_])
            clears = rp.get("lo") is not None and bar_hi(rh) is not None and rp["lo"] > bar_hi(rh)
            lab = honest_leg(rh) if clears else "DEAD"
            labels[rename.get(k, k)] = lab
            rec[rename.get(k, k)] = {"streams": n, "sessions": ns, "honest": rh, "back_30s": rp, "label": lab}
        out[ax] = {"reportable": rec, "n_strata": len(sz), "n_reportable": len(rec),
                   "confinement": pe.confinement(labels)}
    out["tool_key"] = {"confinement": "NOT_APPLICABLE",
                       "reason": "the decision unit is a stream of responses, which mixes tools; no per-tool stream exists"}
    return out


def artifact_checks(unit, corpus, u, R, S, copied_call, private):
    """AC2-AC5 on the honest-leg label (AC1 separately, raw)."""
    base = honest_leg(crate(S.inconsistent.to_numpy(), S.session_id.to_numpy()))
    out = {"base_label": base}
    # AC2 truncation: truncated results removed from the inputs
    u2 = u[~u._trunc.to_numpy()]
    S2 = pe.bracket_streams(pe.bracket_responses(u2))
    r2 = crate(S2.inconsistent.to_numpy(), S2.session_id.to_numpy())
    out["AC2_truncation"] = {"results_removed": int(u._trunc.sum()), "rate_by_session": r2,
                             "inconsistent": int(S2.inconsistent.sum()), "streams": int(len(S2)),
                             "label": honest_leg(r2), "result": "PASS" if honest_leg(r2) == base else "FAIL"}
    # AC3 join: only clean-joined results as inputs (user events kept)
    cr = u[u.kind.isin(["call", "result"])][["session_id", "seq", "kind", "call_id", "ts"]]
    P = pc.make_pairs(cr)
    ok = pe.join_clean_mask(cr, P, copied_call)
    clean_keys = set(zip(P.session_id[ok], P.call_id[ok].astype(str)))
    is_res = (u.kind == "result").to_numpy()
    keep_res = np.array([(s, str(c)) in clean_keys for s, c in zip(u.session_id, u.call_id)])
    u3 = u[~is_res | keep_res]
    S3 = pe.bracket_streams(pe.bracket_responses(u3))
    r3 = crate(S3.inconsistent.to_numpy(), S3.session_id.to_numpy())
    out["AC3_join"] = {"results_removed": int((is_res & ~keep_res).sum()), "rate_by_session": r3,
                       "inconsistent": int(S3.inconsistent.sum()), "streams": int(len(S3)),
                       "label": honest_leg(r3), "result": "PASS" if honest_leg(r3) == base else "FAIL"}
    # AC4 dominance (denominator = streams per session)
    w = S.groupby("session_id").size().to_dict()
    clmaps = {"model": pe.session_model_map(u[u.session_id.isin(list(w))])}
    if corpus == "swechat":
        clmaps["repo"] = pe.session_cluster_map(corpus, u[u.session_id.isin(list(w))], kind="repo")
        clmaps["user"] = pe.session_cluster_map(corpus, u[u.session_id.isin(list(w))], kind="user")
    else:
        clmaps["repo"] = pe.session_cluster_map(corpus, u[u.session_id.isin(list(w))], kind="repo")
    clmaps["session"] = {s: s for s in w}  # the single-session leg of the dominance rule (> 0.10 of the streams)
    ac4 = {}
    effect = "pass"
    for name, mp in clmaps.items():
        d = pe.dominance(w, mp)
        if name == "session":
            d["dominated"] = d["top_share_events"] > pe.DOM_SESSION
        rec = {"dominated": d["dominated"], "top_share_streams": d["top_share_events"],
               "top_share_sessions": d["top_share_sessions"], "top_session_share_streams": d["top_session_share_events"],
               "n_clusters": d["n_clusters"]}
        if d["dominated"]:
            leave = []
            for c, _, _ in d["top_clusters"]:
                m = S.session_id.map(lambda s: mp.get(s, "unknown")).to_numpy() != c
                n, ns = int(m.sum()), int(S.session_id[m].nunique())
                if n < 30 or ns < 5:
                    leave.append({"label": None, "below_min_n": True, "streams": n})
                    effect = "cap_weak" if effect == "pass" else effect
                    continue
                rr = crate(S.inconsistent.to_numpy()[m], S.session_id.to_numpy()[m])
                lab = honest_leg(rr)
                leave.append({"label": lab, "streams": n, "sessions": ns, "rate_by_session": rr})
                if pe.LEVEL.get(lab, 0) < pe.LEVEL.get(base, 0):
                    effect = "downgrade"
            rec["leave_outs"] = leave
        ac4[name] = rec
    ws = max(w.values()) / sum(w.values())
    ac4["single_session_top_share_streams"] = ws
    out["AC4_dominance"] = {"by_cluster": ac4, "effect": effect}
    if private:
        for name in ac4:
            if isinstance(ac4[name], dict):
                ac4[name].pop("top_cluster", None)
    # AC5 post-stratification
    if corpus == "swechat":
        g = S.groupby("session_id").inconsistent.agg(["sum", "size"])
        wts = pe.post_strat_weights(corpus, list(g.index))
        wr = pe.weighted_cluster_rate(g["sum"].to_numpy(), g["size"].to_numpy(), [wts[s] for s in g.index])
        lab = honest_leg({"rate": wr["rate"], "hi": wr["hi"], "num": float(g["sum"].sum()),
                          "wilson_hi_per_event": stats.wilson(0, int(g["size"].sum()))[2]})
        out["AC5_post_strat"] = {"weighted": wr, "label": lab, "result": "PASS" if lab == base else "FAIL"}
    else:
        out["AC5_post_strat"] = {"result": "NOT_RUN", "reason": "no population table for this corpus"}
    return out


# ===================================================================================================== post hoc (not a verdict)
POSTHOC_ORDER = ["restamped_copy", "out_of_order_result", "input_after_response", "client_behind_server",
                 "user_input_binding", "other"]


def call_seq_map(u):
    c = u[(u.kind == "call").to_numpy() & u.call_id.notna().to_numpy()]
    c = c.sort_values("seq").drop_duplicates(["session_id", "call_id"])
    return {(s, ci): (int(q), rid if isinstance(rid, str) else None)
            for s, ci, q, rid in zip(c.session_id, c.call_id.astype(object), c.seq, c.request_id.astype(object))}


def posthoc_mechanisms(u, V, copied, cmap, private):
    """POST HOC, NOT A VERDICT. Mechanical descriptors of each honest inconsistent stream, written after the binding
    events were inspected. out_of_order_result = the L-binding input is a tool result whose own call appears LATER in
    the file (seq) and belongs to the L-binding response itself or a later one; input_after_response = the L-binding
    input is stamped after the response's first event; client_behind_server = the U-binding response's first event is
    stamped more than 2 s before its id time (hi < -2,000 ms)."""
    rows, counts = [], Counter()
    S = V.S
    for r in recs(S[S.inconsistent]):
        g = V.groups[(r["session_id"], r["stream"])]
        cats = V.cats[(r["session_id"], r["stream"])]
        u_s = u[u.session_id == r["session_id"]].set_index("seq", drop=False)
        d = {"restamped_copy": "restamped_copy" in cats, "user_input_binding": "user_input_binding" in cats}
        kL, kU = g.loc[r["k_L"]] if r["k_L"] is not None else None, g.loc[r["k_U"]]
        d["U_hi_ms"] = float(kU["hi"])
        d["client_behind_server"] = bool(kU["hi"] < -TOL)
        d["L_input_after_response"] = False
        d["L_input_result_call"] = None
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
            key = {"input_after_response": "L_input_after_response"}.get(m, m)
            if d.get(key):
                mech = m
                break
        d["mechanism"] = mech
        counts[mech] += 1
        for k in ("restamped_copy", "user_input_binding", "client_behind_server", "L_input_after_response",
                  "out_of_order_result"):
            counts[f"flag:{k}"] += int(bool(d[k]))
        counts[f"L_input_result_call:{d['L_input_result_call']}"] += 1
        if not private:
            d["session_id"], d["stream"] = r["session_id"], r["stream"]
            rows.append(d)
    return {"note": "POST HOC, NOT A VERDICT: descriptors chosen after inspecting the binding events",
            "mechanism_order": POSTHOC_ORDER, "counts": dict(counts), "streams": rows}


def posthoc_ordered_inputs(u, cmap):
    """POST HOC, NOT A VERDICT: drop result inputs whose own call appears later in the file, then recompute the honest
    bracket and the 5 s / 30 s placebo. Not a pre-registered correction, so it cannot be adopted."""
    is_res = (u.kind == "result").to_numpy()
    seqs, sids, cids = u.seq.to_numpy(), u.session_id.to_numpy(), u.call_id.astype(object).to_numpy()
    drop = np.zeros(len(u), dtype=bool)
    for i in np.flatnonzero(is_res):
        cm = cmap.get((sids[i], cids[i])) if isinstance(cids[i], str) else None
        drop[i] = cm is not None and cm[0] > seqs[i]
    R = pe.bracket_responses(u[~drop])
    S = pe.bracket_streams(R)
    out = {"note": "POST HOC, NOT A VERDICT", "results_dropped": int(drop.sum()), "results": int(is_res.sum()),
           "honest": {"streams": int(len(S)), "inconsistent": int(S.inconsistent.sum()),
                      "rate_by_session": crate(S.inconsistent.to_numpy(), S.session_id.to_numpy())}}
    for D in (5000, 30000):
        SP = pe.bracket_streams(pe.placebo_shift(R, D))
        out[f"back_{D // 1000}s"] = {"streams": int(len(SP)), "flagged": int(SP.inconsistent.sum()),
                                     "share": float(SP.inconsistent.mean())}
    return out


def r1_verdict(honest_r, back30, back5, other_cells, n7_leg, step0, checks_effects, confined, has_e):
    """Mechanical R1 verdict (prereg a1.proposal_rules R1_specific). Returns dict with label, deciding numbers."""
    reasons = []
    hl = honest_leg(honest_r)
    bar = bar_hi(honest_r)
    clears30 = bool(back30["rate_by_session"]["lo"] is not None and bar is not None and back30["rate_by_session"]["lo"] > bar)
    clears5 = bool(back5["rate_by_session"]["lo"] is not None and bar is not None and back5["rate_by_session"]["lo"] > bar)
    others = sorted(k for k, c in other_cells.items() if not c["back_dating_type"] and c["clears_honest_bar"])
    if not clears30:
        label = "DEAD"
        reasons.append("30 s back-dating does not clear the honest bar (kill rule)")
    elif hl == "DEAD":
        label = "DEAD"
        reasons.append("honest flag rate > 0.20")
    else:
        cap = "WEAK" if not others else "ALIVE"
        if not others:
            reasons.append("back-dating only: no other single-call/single-response type clears the honest bar")
        if n7_leg is None:
            label = "PENDING_N7"
            reasons.append("N7 DETECTS/PARTIAL leg not available (n7 output absent): ALIVE/WEAK cannot be assigned")
        else:
            if n7_leg == "DETECTS" and hl == "ALIVE" and cap == "ALIVE":
                label = "ALIVE"
            elif n7_leg in ("DETECTS", "PARTIAL"):
                label = "WEAK"
            else:
                label = "DEAD"
                reasons.append("no N7 attack type DETECTS or PARTIAL")
        if label not in ("DEAD",):
            for eff in checks_effects:
                if eff == "downgrade":
                    label = pe.downgrade(label) if label in pe.LEVEL else label
                    reasons.append("artifact check downgrade")
                elif eff == "cap_weak" and label == "ALIVE":
                    label = "WEAK"
                    reasons.append("artifact check cap at WEAK")
            if confined and label in pe.LEVEL:
                label = pe.downgrade(label)
                reasons.append("CONFINED to one stratum")
    ceiling = "DEAD" if not clears30 or hl == "DEAD" else ("WEAK" if (not others or hl == "WEAK") else "ALIVE")
    ceil2 = ceiling
    for eff in checks_effects:
        if eff == "downgrade":
            ceil2 = pe.downgrade(ceil2)
        elif eff == "cap_weak" and ceil2 == "ALIVE":
            ceil2 = "WEAK"
    if confined:
        ceil2 = pe.downgrade(ceil2)
    suffix = "" if has_e else " (B only, unreplicated)"
    if step0 == "NOT_REPRODUCED":
        suffix += " (Step 0 NOT_REPRODUCED)"
    return {"label": label, "suffix": suffix, "ceiling_before_n7": ceiling, "ceiling_after_checks": ceil2,
            "ceiling_rule": "the best label the N7 leg could still allow: kill rule, back-dating-only cap and honest leg, "
                            "then artifact-check effects and confinement",
            "honest_leg": hl, "honest_bar_hi": bar,
            "back_30s_clears": clears30, "back_5s_clears": clears5, "other_types_clearing": others,
            "reasons": reasons}


# ===================================================================================================== main
def main():
    pj = pe.check_frozen()
    pe.OUT_E.mkdir(parents=True, exist_ok=True)
    J = {"item": "f1_bracket", "script": "analysis/probes/phase_e_f1_bracket.py",
         "prereg": {"prereg_e_json_sha256": pe.sha256_file(pe.PREREG_E_JSON),
                    "spec_module_sha256_lf": pj["provenance"]["spec_module_sha256_lf"],
                    "sections": ["followups.F1_bracket_failures", "a1.proposal_rules.R1_specific"]},
         "references": {**{k: pj["references"][k] for k in ("bracket_B_committed_lens", "placebo_skeptic_text",
                                                            "bracket_x_copies_swechat")},
                        "resolved_bracket_A": pj["resolved"]["bracket_A"]},
         "inputs_sha256": {}, "units": {}, "dev": bool(DEV),
         "implementation_notes": [
             "restamped_copy 'another session of the corpus' = another session of the readable corpus (swechat B u E, "
             "cc_local B); A is calibration-only and H is never read",
             "R1 numbers live in this file (item f1_bracket) rather than a separate a1_R1.json",
             "R1 kill-rule tamper cells are stream-level: one tamper per stream, target rng_for(attack, param, session, "
             "stream), donor rng_for('donor', attack, param, session, stream); they are not N7 session-level cells",
             "missing stamps (pd.NA in the cache) are passed to the injectors as None so atk_insert_pair's own "
             "missing-stamp path (skip) is taken instead of raising",
             "text is truncated to 200 characters after the truncation flag is computed on the full text; "
             "bracket_benign_categories reads only t[:200] and startswith()",
             "cc_local AC1 (raw parser audit) NOT_RUN: no cc_local raw file is opened by this item",
             "abstain counts as not flagged; the denominator stays all streams; abstentions are reported",
             "AC4 adds an explicit single-session axis (dominated if one session holds > 0.10 of the streams) with its "
             "own leave-outs; the cluster axes use pe.dominance() unchanged",
             "posthoc_mechanisms and posthoc_ordered_inputs were added after inspecting the binding events of the "
             "honest failures: POST HOC, NOT A VERDICT, never adoptable as a correction",
             "clears_wilson_bar_sensitivity: the kill-rule bar recomputed with the per-stream Wilson hi (Phase D used "
             "Wilson for cc_local); a sensitivity column only, the verdict bar is the session-clustered hi"]}
    dev_keep = {}
    copied_cache = {}
    for corpus, split, unit in UNITS:
        key = f"{unit}|{split}"
        log("load", key)
        J["inputs_sha256"][f"analysis/cache/{corpus}_{split}.parquet"] = pe.sha256_file(pe.CACHE / f"{corpus}_{split}.parquet")
        keep = None
        if DEV:
            ids = pe.split_ids(corpus, split) if corpus == "swechat" else None
            keep = set(sorted(ids)[:150]) if ids else None
        u = load_unit(corpus, split, unit, keep)
        if corpus not in copied_cache:
            copied_cache[corpus] = copied_ids(corpus)
        copied, keep_sess, cinfo = copied_cache[corpus]
        private = corpus in PRIVATE
        u_by_s = {s: g for s, g in u.groupby("session_id", sort=False)}
        R = pe.bracket_responses(u)
        S = pe.bracket_streams(R)
        log(key, "responses", len(R), "streams", len(S))
        blk = {"corpus": corpus, "split": split, "unit": unit, "private": private,
               "label": ("private: aggregates only" if private else None),
               "sessions_in_unit": int(u.session_id.nunique()), "copied_ids": cinfo}
        blk["honest"] = honest_block(R, S)
        blk["placebo"] = placebo_block(R, S, u_by_s, copied)
        # variants for categories and corrections
        V_h = Variant(R, u_by_s, copied, "honest")
        Rdd = dedupe(R, keep_sess)
        V_h_dd = Variant(Rdd, u_by_s, copied, "honest_dedup")
        V_p = {D: Variant(pe.placebo_shift(R, D), u_by_s, copied, f"back{D}") for D in (5000, 30000)}
        V_p_dd = {D: Variant(pe.placebo_shift(Rdd, D), u_by_s, copied, f"back{D}_dd") for D in (5000, 30000)}
        log(key, "variants built")
        blk["benign"] = categories_block(unit, split, V_h, u_by_s, copied, private, do_raw=(corpus == "swechat"))
        cmap = call_seq_map(u)
        blk["posthoc_mechanisms"] = posthoc_mechanisms(u, V_h, copied, cmap, private)
        blk["posthoc_ordered_inputs"] = posthoc_ordered_inputs(u, cmap)
        del cmap
        blk["corrections_single"] = corrections_block(V_h, V_h_dd, V_p, V_p_dd, u_by_s, copied)
        blk["_V"] = (V_h, V_h_dd, V_p, V_p_dd)
        log(key, "categories + corrections done")
        # AC1 (raw) for swechat
        inc_rows = recs(S[S.inconsistent])
        if corpus == "swechat":
            blk["AC1_parser"] = ac1_audit(inc_rows, V_h.groups, u_by_s, unit)
        else:
            blk["AC1_parser"] = {"result": "NOT_RUN", "reason": "no cc_local raw file is opened by this item (privacy; "
                                                                "the prereg pins a cc_local raw source for R4 only)"}
        # stream-level tamper set (R1 kill-rule cells)
        log(key, "tamper set start")
        res, dinfo = run_tamper(u, R, S, f"{corpus}_{split}")
        hk = {(a, b): bool(c) for a, b, c in zip(S.session_id, S.stream, S.inconsistent)}
        hr = blk["honest"]["rate_by_session"]
        cells, agree = tamper_cells(res, hk, bar_hi(hr), hr["rate"], blk["honest"]["wilson_per_stream"]["hi"])
        blk["tamper_stream_level"] = {"cells": cells, "honest_flag_agreement_stream_frame_vs_session": agree,
                                      "donor_pool_insert": dinfo, "n_cells": len(cells)}
        blk["_tamper_raw"] = res
        log(key, "tamper set done")
        # strata + artifact checks inputs kept for the pooled pass
        blk["_u"], blk["_R"], blk["_S"] = u, R, S
        blk["_SP30"] = pe.bracket_streams(pe.placebo_shift(R, 30000))
        J["units"][key] = blk
        gc.collect()

    # ---------------------------------------------------------------------------------------- Step 0 (swechat CC B)
    b = J["units"]["swechat/claude_code|B"]
    ref = pj["references"]["placebo_skeptic_text"]
    n_own = b["honest"]["streams_ge2"]
    hon = b["honest"]["inconsistent_streams"]
    p5 = b["placebo"]["back_5s"]
    p30 = b["placebo"]["back_30s"]
    s5_ref, s30_ref = ref["back_5s"][0] / ref["back_5s"][1], ref["back_30s"][0] / ref["back_30s"][1]
    cond_a = abs(hon - 10) <= 3
    cond_b5 = abs(p5["flagged"] / p5["streams"] - s5_ref) <= 0.03
    cond_b30 = abs(p30["flagged"] / p30["streams"] - s30_ref) <= 0.01
    later = {k: b["placebo"][k]["flagged"] for k in ("late_5s", "late_30s", "late_300s")}
    cond_c = all(abs(v - hon) <= 3 for v in later.values())
    step0 = "REPRODUCED" if (cond_a and cond_b5 and cond_b30 and cond_c) else "NOT_REPRODUCED"
    J["step0"] = {"unit": "swechat/claude_code", "split": "B", "streams_own": n_own,
                  "streams_committed_lens": pj["references"]["bracket_B_committed_lens"]["streams_ge2_responses"],
                  "streams_skeptic_placebo": ref["back_5s"][1], "streams_brief": ref["honest"][1],
                  "honest_inconsistent": hon, "honest_reference": 10,
                  "back_5s": {"flagged": p5["flagged"], "streams": p5["streams"], "share": p5["flagged"] / p5["streams"],
                              "reference_share": s5_ref, "abs_diff": abs(p5["flagged"] / p5["streams"] - s5_ref),
                              "tolerance": 0.03},
                  "back_30s": {"flagged": p30["flagged"], "streams": p30["streams"],
                               "share": p30["flagged"] / p30["streams"], "reference_share": s30_ref,
                               "abs_diff": abs(p30["flagged"] / p30["streams"] - s30_ref), "tolerance": 0.01},
                  "later_flagged": later, "roll_ids_flagged": b["placebo"]["roll_ids_reference"]["flagged"],
                  "roll_ids_reference": ref["roll_all"][0],
                  "conditions": {"a_honest_10pm3": cond_a, "b_5s_within_0.03": cond_b5, "b_30s_within_0.01": cond_b30,
                                 "c_later_within_honest_pm3": cond_c},
                  "result": step0}
    log("Step 0:", step0)

    # ---------------------------------------------------------------------------------------- F1 adopted corrections
    f1 = {}
    for unit_key, e_key in (("swechat/claude_code|B", "swechat/claude_code|E"), ("cc_local|B", None)):
        bb = J["units"][unit_key]
        adopted = bb["corrections_single"]["adopted"]
        V_h, V_h_dd, V_p, V_p_dd = bb["_V"]
        u_by_s = {s: g for s, g in bb["_u"].groupby("session_id", sort=False)}
        corpus = bb["corpus"]
        copied = copied_cache[corpus][0]
        rec = {"adopted_on_B": adopted}
        use_dd = "restamped_copy" in adopted
        rec["B"] = corrected_eval(V_h_dd if use_dd else V_h, V_p_dd if use_dd else V_p, u_by_s, copied, adopted)
        if e_key:
            ee = J["units"][e_key]
            Vh, Vhd, Vp, Vpd = ee["_V"]
            u_by_e = {s: g for s, g in ee["_u"].groupby("session_id", sort=False)}
            rec["E"] = corrected_eval(Vhd if use_dd else Vh, Vpd if use_dd else Vp, u_by_e, copied, adopted)
        # unexplained = still flagged under the adopted set, listed by category vector
        todo = [("B", V_h_dd if use_dd else V_h, u_by_s)]
        if e_key:
            todo.append(("E", Vhd if use_dd else Vh, u_by_e))
        for sp, VV, ub in todo:
            st = VV.status(set(adopted), ub, copied)
            vec = Counter()
            for row, s_ in zip(recs(VV.S), st):
                if s_ == "flag":
                    vec["+".join(sorted(VV.cats.get((row["session_id"], row["stream"]), set()))) or "(none)"] += 1
            rec[f"still_flagged_by_category_vector_{sp}"] = dict(vec)
        f1[bb["unit"]] = rec
    J["f1_effective_fp"] = f1

    # ---------------------------------------------------------------------------------------- R1 pooled + verdicts
    n7_paths = sorted(str(p.relative_to(ROOT)) for p in pe.OUT_E.glob("n7_attacks*.json"))
    J["n7_outputs_present"] = n7_paths
    r1 = {}
    for unit, parts, has_e in (("swechat/claude_code", ["swechat/claude_code|B", "swechat/claude_code|E"], True),
                               ("cc_local", ["cc_local|B"], False)):
        blks = [J["units"][k] for k in parts]
        Sx = pd.concat([x["_S"] for x in blks], ignore_index=True)
        SPx = pd.concat([x["_SP30"] for x in blks], ignore_index=True)
        ux = pd.concat([x["_u"] for x in blks], ignore_index=True) if len(blks) > 1 else blks[0]["_u"]
        Rx = pd.concat([x["_R"] for x in blks], ignore_index=True) if len(blks) > 1 else blks[0]["_R"]
        corpus = blks[0]["corpus"]
        private = corpus in PRIVATE
        pooled = {"splits": [x["split"] for x in blks]}
        hr = crate(Sx.inconsistent.to_numpy(), Sx.session_id.to_numpy())
        pooled["honest"] = {"streams": int(len(Sx)), "inconsistent": int(Sx.inconsistent.sum()),
                            "sessions": int(Sx.session_id.nunique()), "rate_by_session": hr,
                            "wilson_per_stream": wil(Sx.inconsistent.sum(), len(Sx))}
        # placebo pooled
        plc = {}
        for k in ("back_5s", "back_30s", "late_5s", "late_30s", "late_300s"):
            kind, D = k.split("_")
            Dm = int(D[:-1]) * 1000
            SPs = pd.concat([pe.bracket_streams(pe.placebo_shift(x["_R"], Dm if kind == "back" else -Dm)) for x in blks],
                            ignore_index=True)
            f = SPs.inconsistent.to_numpy()
            plc[k] = {"streams": int(len(SPs)), "flagged": int(f.sum()), "rate_by_session": crate(f, SPs.session_id.to_numpy()),
                      "wilson_per_stream": wil(f.sum(), len(SPs))}
            plc[k]["clears_honest_bar"] = bool(plc[k]["rate_by_session"]["lo"] is not None and
                                               plc[k]["rate_by_session"]["lo"] > bar_hi(hr))
        pooled["placebo"] = plc
        # tamper cells pooled
        res = sum((x["_tamper_raw"] for x in blks), [])
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
        # strata and artifact checks
        log("strata/checks", unit)
        pooled["strata"] = strata_block(unit, corpus, ux, Sx, SPx, private)
        cc = set()
        if corpus == "swechat":
            parts_c = []
            for sp in ("B", "E"):
                d = pe.read_cache("swechat", sp, ["session_id", "call_id", "kind"])
                parts_c.append(d[(d.kind == "call") & d.call_id.notna()][["session_id", "call_id"]].drop_duplicates())
            d = pd.concat(parts_c).drop_duplicates()
            n_ = d.groupby("call_id").session_id.nunique()
            cc = set(n_[n_ > 1].index.astype(str))
        else:
            d = pe.read_cache("cc_local", "B", ["session_id", "call_id", "kind"])
            d = d[(d.kind == "call") & d.call_id.notna()][["session_id", "call_id"]].drop_duplicates()
            n_ = d.groupby("call_id").session_id.nunique()
            cc = set(n_[n_ > 1].index.astype(str))
        pooled["artifact_checks"] = artifact_checks(unit, corpus, ux, Rx, Sx, cc, private)
        ac1 = [J["units"][k]["AC1_parser"] for k in parts]
        pooled["artifact_checks"]["AC1_parser"] = ac1
        effects = []
        ac = pooled["artifact_checks"]
        for name in ("AC2_truncation", "AC3_join", "AC5_post_strat"):
            if ac[name].get("result") == "FAIL":
                effects.append("downgrade" if pe.LEVEL.get(ac[name].get("label"), 0) < pe.LEVEL.get(ac["base_label"], 0)
                               else "pass")
        effects.append(ac["AC4_dominance"]["effect"])
        if any(a.get("result") == "FAIL" for a in ac1):
            effects.append("downgrade")
        confined = any(pooled["strata"][ax].get("confinement") == "CONFINED" for ax in pooled["strata"])
        n7_leg = None  # filled only from an N7 output; none is consumed here unless present (see n7_outputs_present)
        # verdicts: pooled (primary), and per split
        other = {k: c for k, c in cells.items()}
        pooled["verdict"] = r1_verdict(hr, plc["back_30s"], plc["back_5s"], other, n7_leg, step0, effects, confined, has_e)
        pooled["verdict"]["checks_effects"] = effects
        pooled["verdict"]["confined"] = confined
        per_split = {}
        for x in blks:
            hrs = x["honest"]["rate_by_session"]
            pls = {k: dict(x["placebo"][k]) for k in ("back_5s", "back_30s")}
            per_split[x["split"]] = r1_verdict(hrs, pls["back_30s"], pls["back_5s"], x["tamper_stream_level"]["cells"],
                                               n7_leg, step0, [], False, has_e)
        pooled["verdict_per_split"] = per_split
        pooled["verdict_per_split_note"] = ("per-split verdicts apply the kill rule and honest leg of that split only; "
                                            "artifact checks and strata are computed on the pooled splits")
        r1[unit] = pooled
    J["r1"] = r1
    # strip internals
    for k, blk in J["units"].items():
        for kk in [x for x in blk if x.startswith("_")]:
            blk.pop(kk)
    J["n_verdict_cells"] = {"step0": 1, "corrections_adoption": 2 * len(CATS),
                            "r1_verdicts": sum(1 + len(v["verdict_per_split"]) for v in r1.values()),
                            "tamper_cells": sum(len(blk["tamper_stream_level"]["cells"]) for blk in J["units"].values())
                            + sum(len(v["tamper_stream_level"]["cells"]) for v in r1.values())}
    J["runtime_s"] = round(time.time() - T0, 1)
    out = OUT if not DEV else SCRATCH / "f1_bracket.dev.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(clean(J), fh, indent=1, default=str)
    log("wrote", out)


if __name__ == "__main__":
    main()
