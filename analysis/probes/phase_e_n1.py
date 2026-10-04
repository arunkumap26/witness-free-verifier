"""Phase E, Track A, item N1: conditional duration model (prereg_e.json S:n1_conditional_duration).

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_n1

What it does, in the order the pre-registration fixes:
  1. check_frozen() (prereg_e_common.py must be the pre-registered module).
  2. Per unit x split (B; E where the corpus has one; B u E pooled for artifact checks / strata):
     COVERAGE FIRST: RR = qualified calls in a repeat group / qualified calls (cluster_rate), per scope.
     Then residuals r_i (n1_residuals), rho_hon = Spearman(r_i, log10(bytes+1)) with a session-bootstrap CI, the
     secondary Spearman(r_i, d_log_bytes), the synthetic positive control rho_pc (one tampered instance per repeat group,
     delta' = result chars x 0.25 / G90(unit)), the detector (A-split [0.5, 99.5] percentile bounds, resolved.n1) and
     its call-level honest flag rate, and the verdict per S:n1_conditional_duration.verdict.
  3. For any unit whose N6 cell reaches WEAK or better: AC1-AC5 and the four stratification axes on B u E
     (S:artifact_checks, S:stratification).
Reads: analysis/cache/{swechat,cc_local,aiv_cc}_{B,E}.parquet through prereg_e_common.read_cache (never A, never H),
       swechat_population.parquet and swe-chat-pinned sessions.parquet (metadata only, through prereg_e_common helpers),
       analysis/prereg.json (Phase B G90), analysis/out/probe_1.json (natural control, copied by JSON path).
Writes: analysis/out/phase_e/n1.json (raw numbers only). Interpretation: analysis/notes/phase_e_n1.md.
cc_local: aggregates only (no command, path or text is written). aiv_cc: single-agent case study.
"""
import gc
import json
import math
import sys
import time
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from analysis.lib import stats
from analysis.probes import prereg_common as pc
from analysis.probes import prereg_e_common as pe
from analysis.probes import prereg_e_calibration as pecal  # unit_pairs + COLS: the code path that produced the A bounds

T0 = time.time()
PJ = pe.check_frozen()
SPEC = PJ["n1_conditional_duration"]
RES_N1 = PJ["resolved"]["n1"]
TERC = PJ["resolved"]["length_terciles_A"]
PRB = json.loads((pe.ROOT / "analysis" / "prereg.json").read_text(encoding="utf-8"))
G90 = {u: v["G90"] for u, v in PRB["resolved"]["probe1"]["generation_rate"].items()}
TOK_PER_CHAR = PRB["probe1"]["separability"]["generation_time_model"]["tokens_per_char"]  # 0.25 (Phase B)
P1 = json.loads((pe.ROOT / "analysis" / "out" / "probe_1.json").read_text(encoding="utf-8"))

OUT = pe.OUT_E / "n1.json"
UNITS = SPEC["units"]
SCOPES = ("shell", "auto_read")  # shell primary, auto_read secondary (S:n1_conditional_duration.scope)
PRIMARY = "shell"
KINDS = ["call", "result", "meta", "system", "user"]
LABELS = {
    "swechat/claude_code": ["shell: human-wait contaminated (permissionMode not in the IR)"],
    "cc_local": ["shell: human-wait contaminated (permissionMode not in the IR)", "private: aggregates only",
                 "B only, unreplicated (no E split)"],
    "swechat/opencode": ["shell: permission timing unknown"],
    "swechat/gemini": ["shell: permission timing unknown"],
    "aiv_cc": ["single-agent case study", "B only, unreplicated (no E split)"],
    "swechat/codex": [],
}
# verdict thresholds: S:n1_conditional_duration.verdict (judgment calls fixed at pre-registration)
RHO_BAND, PC_LO_MIN, RR_MIN, FLAG_PT, FLAG_HI = 0.15, 0.30, 0.10, 0.02, 0.05
MIN_RES, MIN_SESS = 200, 20  # S:n1_conditional_duration.min_n
CORPUS_OF = {u: ("swechat" if u.startswith("swechat/") else u) for u in UNITS}
OPENED = []


# ================================================================================================== deviations / choices
# Each entry: where the pre-registration could not be applied literally, the smallest faithful thing done instead.
DEVIATIONS = [
    {"item": "output file names",
     "prereg_said": "prereg_e.json outputs: 'N1-N5': phase_e_n<k>.py -> n<k>.json",
     "what_you_did": "followed the pre-registration: analysis/probes/phase_e_n1.py -> analysis/out/phase_e/n1.json "
                     "(the orchestrator's template would have given phase_e_n1_duration.py / n1_duration.json)",
     "why": "the pre-registration is the output contract", "effect_on_verdict": "none"},
    {"item": "positive-control instance when the drawn instance has no same-status reference",
     "prereg_said": "in each group one instance (rng_for('N1pc', session, key)) gets delta' = T_gen; rho_pc over the "
                    "tampered instances, each against its group's untouched instances",
     "what_you_did": "the instance is drawn uniformly (rng_for('N1pc', session_id, n1_key)) among the group's instances "
                     "that have >= 1 other instance with the same primary-error status, i.e. among those n1_residuals() "
                     "gives a residual; 'key' is read as the n1_key string, which names the group within a session",
     "why": "the residual rule (same error status) leaves an instance without a reference undefined; drawing among "
            "undefined instances would silently drop groups",
     "effect_on_verdict": "none by construction of the rule; every repeat group with >= 1 residual contributes one "
                          "tampered instance"},
    {"item": "positive control on empty results",
     "prereg_said": "delta' = result chars x 0.25 / G90",
     "what_you_did": "a tampered instance with 0 result chars has delta' = 0 and log10 undefined; it is dropped from "
                     "rho_pc (prereg_e_common.spearman drops non-finite values) and counted in "
                     "positive_control.dropped_zero_char_results",
     "why": "log10(0) is undefined", "effect_on_verdict": "none expected (counts reported per block)"},
    {"item": "verdict rule gaps",
     "prereg_said": "ALIVE / WEAK / DEAD rules of S:n1_conditional_duration.verdict",
     "what_you_did": "INCONCLUSIVE when rho_hon point < -0.15 without a DEAD condition (no rule covers it), or when a CI "
                     "the rule needs has < 900 valid bootstrap draws; INSUFFICIENT_N below the min n; rule order DEAD, "
                     "ALIVE, WEAK",
     "why": "the three rules do not partition the space", "effect_on_verdict": "none: no block hit INCONCLUSIVE "
                                                                                "(see results)"},
    {"item": "which scope carries the unit verdict",
     "prereg_said": "scope: shell family primary, auto_read secondary; detector bounds pooled over the unit's scope",
     "what_you_did": "the N6 cell uses the primary (shell) verdict; auto_read gets its own verdict, reported as "
                     "secondary; artifact checks and strata run on the primary scope",
     "why": "the verdict text does not say which scope it is applied to", "effect_on_verdict": "none for the cells "
                                                                                              "(see results.*.auto_read)"},
    {"item": "B u E pooled verdicts",
     "prereg_said": "N6 fill rule: the cell is the E verdict where E exists and is not INSUFFICIENT_N, else the B "
                    "verdict 'B only'; artifact checks run on B u E for any N cell at WEAK or better",
     "what_you_did": "B, E and B u E are all computed and reported; the cell follows the N6 rule. Where only the B u E "
                     "pooled re-measurement reached WEAK (codex, gemini), AC2-AC5 and the strata were also run on it "
                     "for information and AC1 was NOT_RUN; the pooled label is not the cell",
     "why": "the pooled population is the pre-registered artifact-check population; reporting it is informative and "
            "cannot raise a cell", "effect_on_verdict": "none on the cells"},
    {"item": "AC1 sample and effect",
     "prereg_said": "audit_sample() draws 30 numerator (or flagged) events with SEED_E; FAIL at >= 2 of 30 differing",
     "what_you_did": "the 30 events are detector-flagged primary-scope calls (the N1 numerator), sorted by "
                     "(session_id, seq), seed_parts ('N1', 'AC1', 'flagged', unit); fewer than 30 flagged -> all "
                     "audited. A second sample of 30 residual-bearing instances is a diagnostic only. Compared: both "
                     "stamps (delta within 1 ms), result bytes, primary error flag, n1 command key, raw occurrence "
                     "count. AC1 FAIL is applied as a one-level downgrade",
     "why": "the prereg does not name N1's numerator or AC1's label effect", "effect_on_verdict": "none (see AC1)"},
    {"item": "AC4 details",
     "prereg_said": "dominance over the denominator events; aiv_cc is one agent, so it is always dominated, and that "
                    "is only labelled",
     "what_you_did": "denominator events = residuals per session (primary scope); leave-outs recompute every quantity "
                     "on all sessions outside the left-out cluster; aiv_cc single-cluster kinds (agent, model) are "
                     "labelled only, its session dominance is tested; missing swechat user_id forms one cluster ('nan', "
                     "prereg_e_common.session_cluster_map behaviour)",
     "why": "smallest faithful reading", "effect_on_verdict": "aiv_cc: without the label-only reading a leave-out "
                                                              "of its only agent leaves no data and would cap it at WEAK"},
    {"item": "AC5 weighted Spearman",
     "prereg_said": "post-stratified recompute with post_strat_weights",
     "what_you_did": "rho_hon and rho_pc as a weighted Spearman (weighted mid-ranks, weighted Pearson) with a session "
                     "bootstrap; RR and flag rate with prereg_e_common.weighted_cluster_rate. Weights per statistic: "
                     "post_strat_weights over the residual-bearing sessions for rho and the flag rate, over every "
                     "session with qualified primary-scope calls for RR",
     "why": "prereg_e_common has no weighted Spearman", "effect_on_verdict": "none (see AC5)"},
    {"item": "AC3 'call_id not present in another session'",
     "prereg_said": "join_clean_mask(): call_id not present in another session",
     "what_you_did": "copied ids computed over the corpus's B and E caches (B for cc_local and aiv_cc)",
     "why": "the population event table is not loaded", "effect_on_verdict": "none expected"},
    {"item": "natural control",
     "prereg_said": "natural control (reported): Spearman(log latency, log bytes) of the unit's Phase B G set",
     "what_you_did": "copied from analysis/out/probe_1.json units.<unit>.separability.G_spearman_bytes_latency (Phase "
                     "B, split B); not recomputed on E",
     "why": "the prereg names the Phase B G set", "effect_on_verdict": "none (context only)"},
]

# ================================================================================================== loading
def frames():
    """Yields (corpus, unit, split, frame, n_sessions_in_split_for_unit). One unit x split at a time (RAM)."""
    fm = pc.swechat_formats()
    OPENED.append("analysis/cache/swechat_population.parquet")
    for split in ("B", "E"):
        OPENED.append(f"analysis/cache/swechat_{split}.parquet")
        sids = pe.read_cache("swechat", split, ["session_id"]).session_id.unique()
        by = defaultdict(list)
        for s in sids:
            by[fm.get(s, "?")].append(s)
        for f in ("claude_code", "codex", "opencode", "gemini"):
            ids = by.get(f, [])
            if not ids:
                continue
            df = pe.read_cache("swechat", split, pecal.COLS, filters=[("session_id", "in", ids), ("kind", "in", KINDS)])
            yield "swechat", f"swechat/{f}", split, df, len(ids)
        yield "swechat", "swechat/cursor", split, None, len(by.get("cursor", []))
    for c in ("cc_local", "aiv_cc"):
        OPENED.append(f"analysis/cache/{c}_B.parquet")
        df = pe.read_cache(c, "B", pecal.COLS, filters=[("kind", "in", KINDS)])
        yield c, c, "B", df, int(df.session_id.nunique())


def copied_call_ids(corpus):
    """call_ids that occur in more than one session across the corpus's B and E caches (AC3 'call_id not present in
    another session')."""
    parts = []
    for split in (("B", "E") if corpus in pe.CORPORA_WITH_E else ("B",)):
        d = pe.read_cache(corpus, split, ["session_id", "kind", "call_id"], filters=[("kind", "==", "call")])
        parts.append(d[d.call_id.notna()][["session_id", "call_id"]].drop_duplicates())
    d = pd.concat(parts, ignore_index=True)
    n = d.groupby("call_id").session_id.nunique()
    return frozenset(str(x) for x in n[n > 1].index)


# ================================================================================================== per split
def coverage_table(q):
    """Per session x class x tool_key: qualified calls (den), calls in repeat groups (num) and repeat groups. Same
    rule as cal_n1 (repeat group = (session, tool_key, n1_key) with >= 2 qualified instances)."""
    qq = q.assign(_n1=q.n1.fillna("<none>"))
    sz = qq.groupby(["session_id", "key", "_n1"]).seq.transform("size")
    qq = qq.assign(_g=(qq.n1.notna() & (sz >= 2)).to_numpy())
    t = qq.groupby(["session_id", "cls", "key"]).agg(den=("seq", "size"), num=("_g", "sum")).reset_index()
    g = qq[qq._g].groupby(["session_id", "cls", "key"])._n1.nunique()
    t["groups"] = [int(g.get((a, b, c), 0)) for a, b, c in zip(t.session_id, t.cls, t.key)]
    return t


def pc_tamper(q, unit):
    """Positive control (S:n1_conditional_duration.positive_control). In each repeat group one instance, drawn with
    rng_for('N1pc', session_id, n1_key) among the instances that have >= 1 same-error-status reference, gets
    delta' = result chars x 0.25 / G90(unit); its residual is recomputed against the group's untouched same-status
    instances. One row per repeat group."""
    g90 = G90[unit]
    rows = []
    for (s, k, nk), g in q[q.n1.notna()].groupby(["session_id", "key", "n1"], sort=False):
        if len(g) < 2:
            continue
        lg = np.log10(g.delta_s.to_numpy())
        er = g.err.to_numpy()
        ch = g.result_chars.to_numpy()
        by = g.result_bytes.to_numpy()
        elig = [i for i in range(len(g)) if any(er[j] == er[i] for j in range(len(g)) if j != i)]
        if not elig:
            continue
        rng = pe.rng_for("N1pc", s, nk)
        i = elig[int(rng.integers(0, len(elig)))]
        tgen = ch[i] * TOK_PER_CHAR / g90
        ref = [lg[j] for j in range(len(g)) if j != i and er[j] == er[i]]
        r = (math.log10(tgen) - float(np.median(ref))) if tgen > 0 else float("nan")
        rows.append({"session_id": s, "key": k, "n1": nk, "seq": int(g.seq.iloc[i]), "residual_pc": r,
                     "log_bytes": math.log10(by[i] + 1), "t_gen_s": tgen, "delta_orig_s": float(g.delta_s.iloc[i]),
                     "residual_orig": float(lg[i] - np.median(ref)), "err": bool(er[i]), "group_size": int(len(g))})
    return pd.DataFrame(rows)


def attach(R, q, cols):
    if not len(R):
        for c in cols:
            R[c] = pd.Series(dtype=object)
        return R
    m = q.set_index(["session_id", "seq"])[cols]
    idx = pd.MultiIndex.from_arrays([R.session_id, R.seq])
    for c in cols:
        R[c] = m[c].reindex(idx).to_numpy()
    return R


def variant_frames(q, unit):
    """Residuals, positive-control rows and the coverage table for one set of qualified pairs."""
    R = pe.n1_residuals(q, unit)
    R = attach(R, q, ["cls", "trunc", "join_clean", "call_id", "ts", "ts_r", "delta_s", "result_bytes"])
    PCF = pc_tamper(q, unit)
    PCF = attach(PCF, q, ["cls"])
    C = coverage_table(q)
    return R, PCF, C


def _lab(x):
    """Cluster label as a string. A missing metadata value (None / NaN / NA) becomes the one cluster 'nan': NaN never
    equals itself, so left as a float it would break the AC4 leave-out (nothing would be left out)."""
    if x is None or x is pd.NA or (isinstance(x, float) and math.isnan(x)):
        return "nan"
    return str(x)


def per_split(corpus, unit, split, u, copied):
    u = u.reset_index(drop=True)
    P, Q = pecal.unit_pairs(unit, u)
    jc = pe.join_clean_mask(u, Q, copied)
    Q["join_clean"] = jc
    q = Q[Q.qualified].copy()
    q["trunc"] = [pe.truncated_result(t, x) for t, x in zip(pc.sobj(q.text_r), q.extra_r.astype(object))]
    n_pairs = Q.groupby("session_id").size().to_dict()  # paired calls per session (length tercile basis, as cal_lengths)
    meta = {"pairs": int(len(Q)), "pairs_sessions": int(Q.session_id.nunique()),
            "qualified": int(Q.qualified.sum()),
            "qualified_by_class": {k: int(v) for k, v in q.cls.value_counts().items()},
            "qualified_in_scope_by_class": {c: int((q.cls == c).sum()) for c in SCOPES},
            "pairs_in_scope_by_class_before_qualification": {c: int((Q.cls == c).sum()) for c in SCOPES},
            "excluded_background": int((Q.background & Q.cls.isin(list(SCOPES))).sum()),
            "nonpositive_or_missing_delta_in_scope": int((Q.cls.isin(list(SCOPES))
                                                         & ~(np.isfinite(Q.delta_s.to_numpy())
                                                             & (Q.delta_s.to_numpy() > 0))).sum()),
            "n1_key_missing_qualified": int(q.n1.isna().sum()),
            "truncated_qualified": int(q.trunc.sum()), "join_unclean_qualified": int((~q.join_clean).sum())}
    q = q[["session_id", "seq", "key", "cls", "n1", "delta_s", "result_bytes", "result_chars", "err", "trunc",
           "join_clean", "call_id", "ts", "ts_r"]].copy()
    allp = Q[Q.cls.isin(list(SCOPES))].groupby(["session_id", "cls"]).size().rename("den_all").reset_index()
    out = {"all": variant_frames(q, unit), "allpairs": allp,
           "AC2_no_truncated": variant_frames(q[~q.trunc], unit),
           "AC3_join_clean": variant_frames(q[q.join_clean], unit)}
    # session metadata for strata / dominance / AC5
    sm = {}
    model = pe.session_model_map(u)
    repo = pe.session_cluster_map(corpus, u, kind="repo")
    user = pe.session_cluster_map(corpus, u, kind="user") if corpus == "swechat" else {}
    cuts = TERC[unit]["cuts"]
    terc = pe.length_tercile_map(n_pairs, cuts)
    for s in set(u.session_id.unique()):
        sm[s] = {"model": _lab(model.get(s, "unknown")), "repo": _lab(repo.get(s, "unknown")),
                 "user": _lab(user.get(s, "n/a")), "length_tercile": terc.get(s, "short"), "split": split}
    del P, Q
    return meta, out, sm, q


# ================================================================================================== statistics
def rr_stat(C, cls, w=None):
    t = C[C.cls == cls].groupby("session_id").agg(num=("num", "sum"), den=("den", "sum"),
                                                  groups=("groups", "sum")).reset_index() if len(C) else C
    if not len(t):
        return {"rate": None, "num": 0, "den": 0, "n_sessions": 0, "repeat_groups": 0}
    if w is not None:
        r = pe.weighted_cluster_rate(t.num.to_numpy(), t.den.to_numpy(), [w.get(s, 0.0) for s in t.session_id])
        return r
    r = stats.cluster_rate(t.num.to_numpy(), t.den.to_numpy())
    r["repeat_groups"] = int(t.groups.sum())
    return r


def wspearman_fn(gs):
    """Weighted Spearman over (x, y, w) session payloads: weighted mid-ranks, then weighted Pearson (AC5)."""
    if not gs:
        return None
    x = np.concatenate([a for a, _, _ in gs])
    y = np.concatenate([b for _, b, _ in gs])
    w = np.concatenate([c for _, _, c in gs])
    ok = np.isfinite(x) & np.isfinite(y) & (w > 0)
    x, y, w = x[ok], y[ok], w[ok]
    if len(x) < 3 or np.all(x == x[0]) or np.all(y == y[0]):
        return None

    def wrank(v):
        o = np.argsort(v, kind="mergesort")
        vs, ws = v[o], w[o]
        cw = np.cumsum(ws)
        r = np.empty(len(v))
        i = 0
        while i < len(vs):
            j = i
            while j + 1 < len(vs) and vs[j + 1] == vs[i]:
                j += 1
            lo = cw[i - 1] if i > 0 else 0.0
            r[o[i:j + 1]] = lo + (cw[j] - lo) / 2.0
            i = j + 1
        return r
    rx, ry = wrank(x), wrank(y)
    mx, my = np.average(rx, weights=w), np.average(ry, weights=w)
    cov = np.average((rx - mx) * (ry - my), weights=w)
    vx, vy = np.average((rx - mx) ** 2, weights=w), np.average((ry - my) ** 2, weights=w)
    if vx <= 0 or vy <= 0:
        return None
    return float(cov / math.sqrt(vx * vy))


def rho(x, y, sids, w=None):
    if len(x) == 0:
        return {"value": None, "n": 0, "n_sessions": 0, "valid_draws": 0, "ci_reported": False}
    if w is None:
        b = pe.session_spearman(np.asarray(x, float), np.asarray(y, float), np.asarray(sids))
    else:
        df = pd.DataFrame({"x": x, "y": y, "s": sids})
        df["w"] = [w.get(s, 0.0) for s in df.s]
        groups = [(g.x.to_numpy(float), g.y.to_numpy(float), g.w.to_numpy(float)) for _, g in df.groupby("s")]
        b = pe.boot_stat(groups, wspearman_fn)
    b["n"] = int(np.isfinite(np.asarray(x, float)).sum())
    return b


def flag_stat(R, bounds, w=None):
    if not len(R):
        return {"rate": None, "num": 0, "den": 0, "n_sessions": 0}
    lo, hi = bounds
    f = (R.residual.to_numpy() < lo) | (R.residual.to_numpy() > hi)
    if w is not None:
        num = pd.Series(f.astype(int)).groupby(R.session_id.to_numpy()).sum()
        den = pd.Series(np.ones(len(f))).groupby(R.session_id.to_numpy()).sum()
        return pe.weighted_cluster_rate(num.to_numpy(), den.to_numpy(), [w.get(s, 0.0) for s in num.index])
    r = pe.rate_by_session(f, R.session_id.to_numpy())
    r["flag_low"] = int((R.residual.to_numpy() < lo).sum())
    r["flag_high"] = int((R.residual.to_numpy() > hi).sum())
    return r


def qtiles(v, sids=None):
    v = np.asarray(v, float)
    v = v[np.isfinite(v)]
    out = {"n": int(len(v))}
    if sids is not None:
        out["n_sessions"] = int(len(set(sids)))
    if len(v):
        for qq in (0.0, 0.005, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 0.995, 1.0):
            out[f"q{qq:g}"] = float(np.quantile(v, qq))
    return out


def verdict(rr, rh, rp, fl, n_res, n_sess, path):
    """S:n1_conditional_duration.verdict, applied mechanically. path: JSON path prefix of this block."""
    conds = []
    if n_res < MIN_RES or n_sess < MIN_SESS:
        return {"label": "INSUFFICIENT_N", "rule": f"min n: >= {MIN_RES} residuals from >= {MIN_SESS} sessions",
                "deciding_number": {"residuals": n_res, "sessions": n_sess},
                "deciding_path": [f"{path}.residuals.n", f"{path}.residuals.n_sessions"]}
    hv, hlo, hhi = rh.get("value"), rh.get("lo"), rh.get("hi")
    plo = rp.get("lo")
    if hv is not None and hv > RHO_BAND:
        return {"label": "DEAD", "rule": "rho_hon point > 0.15", "deciding_number": hv,
                "deciding_path": f"{path}.rho_hon.value"}
    if hv is None or not rh.get("ci_reported") or not rp.get("ci_reported") or plo is None:
        return {"label": "INCONCLUSIVE", "rule": "a CI needed by the rule is not reportable (< 900 valid draws or no value)",
                "deciding_number": {"rho_hon_valid_draws": rh.get("valid_draws"), "rho_pc_valid_draws": rp.get("valid_draws")},
                "deciding_path": [f"{path}.rho_hon.valid_draws", f"{path}.rho_pc.valid_draws"]}
    if plo <= hhi:
        return {"label": "DEAD", "rule": "rho_pc CI lo <= rho_hon CI hi", "deciding_number": {"rho_pc_lo": plo, "rho_hon_hi": hhi},
                "deciding_path": [f"{path}.rho_pc.lo", f"{path}.rho_hon.hi"]}
    rr_v = rr.get("rate")
    conds = [
        ("rho_hon CI within [-0.15, 0.15]", hlo >= -RHO_BAND and hhi <= RHO_BAND, {"lo": hlo, "hi": hhi},
         [f"{path}.rho_hon.lo", f"{path}.rho_hon.hi"]),
        ("rho_pc CI lo >= 0.30", plo >= PC_LO_MIN, plo, f"{path}.rho_pc.lo"),
        ("coverage RR >= 0.10", rr_v is not None and rr_v >= RR_MIN, rr_v, f"{path}.coverage_RR.rate"),
        ("honest flag rate <= 0.02", fl.get("rate") is not None and fl["rate"] <= FLAG_PT, fl.get("rate"),
         f"{path}.detector.honest_flag_rate.rate"),
        ("honest flag rate CI hi <= 0.05", fl.get("hi") is not None and fl["hi"] <= FLAG_HI, fl.get("hi"),
         f"{path}.detector.honest_flag_rate.hi"),
    ]
    failing = [c for c in conds if not c[1]]
    cond_rec = [{"condition": c[0], "met": bool(c[1]), "value": c[2], "path": c[3]} for c in conds]
    if not failing:
        return {"label": "ALIVE", "rule": "every ALIVE condition met", "conditions": cond_rec,
                "deciding_number": {"rho_hon_ci": [hlo, hhi], "rho_pc_lo": plo, "RR": rr_v, "flag_rate": fl.get("rate"),
                                    "flag_hi": fl.get("hi")},
                "deciding_path": [c[3] for c in conds]}
    if abs(hv) <= RHO_BAND:
        return {"label": "WEAK", "rule": "rho_hon point within +-0.15 and rho_pc CI lo > rho_hon CI hi; ALIVE condition(s) "
                                         "failing: " + "; ".join(c[0] for c in failing),
                "failing": [c[0] for c in failing], "conditions": cond_rec,
                "deciding_number": {c[0]: c[2] for c in failing}, "deciding_path": [c[3] for c in failing]}
    return {"label": "INCONCLUSIVE", "rule": "rule gap: rho_hon point < -0.15 (not DEAD, not within +-0.15 for WEAK)",
            "deciding_number": hv, "deciding_path": f"{path}.rho_hon.value", "conditions": cond_rec}


def block(R, PCF, C, cls, unit, path, w=None, sess_filter=None, w_rr=None):
    """All N1 numbers for one scope (class) on one population; the verdict last."""
    r = R[R.cls == cls] if len(R) else R
    p = PCF[PCF.cls == cls] if len(PCF) else PCF
    c = C
    if sess_filter is not None:
        r = r[r.session_id.isin(sess_filter)] if len(r) else r
        p = p[p.session_id.isin(sess_filter)] if len(p) else p
        c = C[C.session_id.isin(sess_filter)]
    bounds = RES_N1[unit]["bounds"]
    out = {"coverage_RR": rr_stat(c, cls, w_rr if w_rr is not None else w)}
    out["residuals"] = qtiles(r.residual if len(r) else [], r.session_id.tolist() if len(r) else [])
    out["residuals"]["abs_r_quantiles"] = qtiles(np.abs(r.residual) if len(r) else [])
    out["residuals"]["log_bytes_quantiles"] = qtiles(r.log_bytes if len(r) else [])
    out["residuals"]["n_err_instances"] = int(r.err.sum()) if len(r) else 0
    out["residuals"]["n_ref_median"] = float(np.median(r.n_ref)) if len(r) else None
    out["rho_hon"] = rho(r.residual if len(r) else [], r.log_bytes if len(r) else [],
                         r.session_id if len(r) else [], w)
    if w is None:
        out["rho_secondary_d_log_bytes"] = rho(r.residual if len(r) else [], r.d_log_bytes if len(r) else [],
                                               r.session_id if len(r) else [])
    pf = p[np.isfinite(p.residual_pc.to_numpy(float))] if len(p) else p
    out["positive_control"] = {"tampered_groups": int(len(p)), "tampered_finite": int(len(pf)),
                               "dropped_zero_char_results": int(len(p) - len(pf)),
                               "sessions": int(p.session_id.nunique()) if len(p) else 0,
                               "G90_tok_per_s": G90[unit], "tokens_per_char": TOK_PER_CHAR}
    if w is None:
        out["positive_control"]["t_gen_s_quantiles"] = qtiles(p.t_gen_s if len(p) else [])
        out["positive_control"]["residual_pc_quantiles"] = qtiles(pf.residual_pc if len(pf) else [])
        out["positive_control"]["detector_flag_on_tampered_diagnostic"] = (
            flag_stat(pf.rename(columns={"residual_pc": "residual"}), bounds) if len(pf) else None)
    out["rho_pc"] = rho(pf.residual_pc if len(pf) else [], pf.log_bytes if len(pf) else [],
                        pf.session_id if len(pf) else [], w)
    out["detector"] = {"bounds_A": bounds, "bounds_source": RES_N1[unit]["source"],
                       "honest_flag_rate": flag_stat(r, bounds, w)}
    n_res = int(len(r))
    n_sess = int(r.session_id.nunique()) if len(r) else 0
    out["verdict"] = verdict(out["coverage_RR"], out["rho_hon"], out["rho_pc"], out["detector"]["honest_flag_rate"],
                             n_res, n_sess, path)
    return out


# ================================================================================================== artifact checks
LVL = {"ALIVE": 2, "WEAK": 1, "DEAD": 0}


def lower(a, b):
    if a in LVL and b in LVL:
        return a if LVL[a] <= LVL[b] else b
    return a


def dominance_check(R, PCF, C, unit, base_label, sm):
    """AC4 on the primary scope, B u E. Denominator events = residuals per session."""
    r = R[R.cls == PRIMARY]
    w = r.groupby("session_id").size().to_dict()
    all_s = set(C[C.cls == PRIMARY].session_id) | set(w)
    kinds = ["repo", "user", "model"] if CORPUS_OF[unit] == "swechat" else ["repo", "model"]
    out = {"denominator": "residuals per session (primary scope)", "kinds": {}}
    leaveouts = []
    dominated_any = False
    for kind in kinds:
        cmap = {s: sm[s][kind] for s in w}
        d = pe.dominance(w, cmap)
        rec = {k: d.get(k) for k in ("top_cluster", "top_share_events", "top_share_sessions", "n_clusters", "dominated")}
        rec["top5"] = [[c if unit != "cc_local" else f"cluster_{i}", a, b] for i, (c, a, b) in enumerate(d.get("top_clusters", []))]
        if unit == "cc_local":
            rec["top_cluster"] = "cluster_0"
        cluster_dom = max(d.get("top_share_events", 0) or 0, d.get("top_share_sessions", 0) or 0) > pe.DOM_SHARE
        rec["cluster_dominated"] = bool(cluster_dom)
        out["kinds"][kind] = rec
        if cluster_dom and unit == "aiv_cc" and d.get("n_clusters") == 1:
            rec["label_only"] = ("aiv_cc is one agent (one model), so it is always dominated; that is only labelled "
                                 "(PREREG_E 1.1). A single-cluster leave-out leaves no data.")
            out["kinds"][kind] = rec
            continue
        if cluster_dom:
            dominated_any = True
            top5 = [c for c, _, _ in d["top_clusters"]]
            for c in top5:
                keep = {s for s in all_s if sm[s][kind] != c}  # every session of the population, not only those with residuals
                leaveouts.append((kind, c if unit != "cc_local" else f"cluster_{top5.index(c)}", keep))
    top_sess = max(w.items(), key=lambda kv: kv[1]) if w else (None, 0)
    sess_share = top_sess[1] / max(sum(w.values()), 1)
    out["top_session_share_events"] = sess_share
    if sess_share > pe.DOM_SESSION:
        dominated_any = True
        for rank, (s, _) in enumerate(sorted(w.items(), key=lambda kv: -kv[1])[:5]):
            leaveouts.append(("session", f"largest_session_rank_{rank + 1}", all_s - {s}))
    out["dominated"] = dominated_any
    res = []
    effect = "pass"
    for kind, c, keep in leaveouts:
        b = block(R, PCF, C, PRIMARY, unit, f"artifact_checks.AC4.leaveouts", sess_filter=keep)
        lab = b["verdict"]["label"]
        res.append({"kind": kind, "left_out": c, "label": lab, "residuals": b["residuals"]["n"],
                    "sessions": b["residuals"].get("n_sessions", 0), "rho_hon": b["rho_hon"].get("value"),
                    "rho_hon_ci": [b["rho_hon"].get("lo"), b["rho_hon"].get("hi")], "rho_pc_lo": b["rho_pc"].get("lo"),
                    "RR": b["coverage_RR"].get("rate"), "flag_rate": b["detector"]["honest_flag_rate"].get("rate")})
        if lab == "INSUFFICIENT_N":
            if effect == "pass":
                effect = "cap_weak"
        elif lab in LVL and base_label in LVL and LVL[lab] < LVL[base_label]:
            effect = "downgrade"
    out["leaveouts"] = res
    out["effect"] = effect if dominated_any else "pass"
    out["status"] = ("DOMINATED" if out["effect"] == "downgrade" else "UNTESTABLE_WITHOUT_DOMINANT"
                     if out["effect"] == "cap_weak" else "dominated, label stable" if dominated_any else "not dominated")
    return out


def strata_check(R, PCF, C, unit, sm):
    """Four axes (S:stratification) on the primary scope, B u E. Reportable = meets min n."""
    r = R[R.cls == PRIMARY]
    out = {}
    for axis in ("tool_key", "model", "repo", "length_tercile"):
        if axis == "tool_key":
            keys = sorted(r.key.unique())
            groups = {k: set(r[r.key == k].session_id) for k in keys}
            filt = {k: ("key", k) for k in keys}
        else:
            all_s = set(C[C.cls == PRIMARY].session_id) | set(r.session_id)
            vals = Counter(sm[s][axis] for s in all_s)
            groups = {v: {s for s in all_s if sm[s][axis] == v} for v in vals}
            filt = {v: ("sess", v) for v in vals}
        labels, rec = {}, {}
        for i, (k, sess) in enumerate(sorted(groups.items(), key=lambda kv: -len(kv[1]))):
            if filt[k][0] == "key":
                b = block(R[R.key == k] if len(R) else R, PCF[PCF.key == k] if len(PCF) else PCF,
                      C[C.key == k] if len(C) else C, PRIMARY, unit, f"stratification.{axis}")
            else:
                b = block(R, PCF, C, PRIMARY, unit, f"stratification.{axis}", sess_filter=sess)
            lab = b["verdict"]["label"]
            name = k if unit != "cc_local" or axis in ("tool_key", "length_tercile") else f"{axis}_{i}"
            rec[name] = {"label": lab, "residuals": b["residuals"]["n"], "sessions": b["residuals"].get("n_sessions", 0),
                         "rho_hon": b["rho_hon"].get("value"), "rho_hon_ci": [b["rho_hon"].get("lo"), b["rho_hon"].get("hi")],
                         "rho_pc_lo": b["rho_pc"].get("lo"), "flag_rate": b["detector"]["honest_flag_rate"].get("rate")}
            labels[name] = lab if lab in LVL else None
        out[axis] = {"strata": rec, "confinement": pe.confinement(labels)}
    out["CONFINED_any_axis"] = any(v["confinement"] == "CONFINED" for v in out.values() if isinstance(v, dict))
    return out


# ================================================================================================== AC1 parser audit
CC_REJECT = ("cc_permission_denied", "cc_interrupt_reject")


def _raw_text(content):
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


def _scan_entry(e, ts, targets, calls, results, seen):
    """Collect tool_use / tool_result blocks for target call ids from one CC-format entry (nested agent_progress
    messages unwrapped, duplicate uuids skipped: the IR parser's rules)."""
    if not isinstance(e, dict):
        return
    uid = e.get("uuid")
    if uid:
        if uid in seen:
            return
        seen.add(uid)
    t = e.get("type")
    if t in ("tool_use", "tool_result"):  # fixture-style top-level entries
        e = dict(e)
        t = e["type"] = "assistant" if t == "tool_use" else "user"
    if t == "progress":
        d = e.get("data") if isinstance(e.get("data"), dict) else {}
        if d.get("type") == "agent_progress" and isinstance(d.get("message"), dict):
            inner = d["message"]
            _scan_entry(inner, inner.get("timestamp") or ts, targets, calls, results, seen)
        return
    if t not in ("assistant", "user"):
        return
    msg = e.get("message") if isinstance(e.get("message"), dict) else {}
    content = msg.get("content")
    if not isinstance(content, list):
        return
    for b in content:
        if not isinstance(b, dict):
            continue
        if t == "assistant" and b.get("type") in ("tool_use", "server_tool_use") and b.get("id") in targets:
            calls[b["id"]].append({"ts": ts, "input": b.get("input") if isinstance(b.get("input"), dict) else {},
                                   "name": b.get("name")})
        elif t == "user" and b.get("type") == "tool_result" and b.get("tool_use_id") in targets:
            results[b["tool_use_id"]].append({"ts": ts, "text": _raw_text(b.get("content")),
                                              "is_error": b.get("is_error") if "is_error" in b else None})


def _iter_lines_salvage(text):
    dec = json.JSONDecoder(strict=False)
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
            continue
        except ValueError:
            pass
        pos, n = 0, len(line)
        try:
            while pos < n:
                obj, pos = dec.raw_decode(line, pos)
                yield obj
                while pos < n and line[pos] in " \t\r":
                    pos += 1
        except ValueError:
            continue


def raw_lookup(unit, events):
    """events: list of dicts with session_id, call_id. Returns {call_id: (calls, results)} from the raw source
    (read-only)."""
    from analysis.lib.ir import iso
    targets = {e["call_id"] for e in events}
    calls, results = defaultdict(list), defaultdict(list)
    if unit == "swechat/claude_code":
        sids = sorted({e["session_id"] for e in events})
        OPENED.append(f"C:/Swarms/data/swe-chat-pinned/transcripts/<session_id>.jsonl ({len(sids)} audited sessions)")
        for sid in sids:
            b = (pe.SWE_TRANSCRIPTS / f"{sid}.jsonl").read_bytes()
            try:
                text = b.decode("utf-8")
            except UnicodeDecodeError:
                text = b.decode("utf-8", errors="replace")
            seen = set()
            for ent in _iter_lines_salvage(text):
                _scan_entry(ent, ent.get("timestamp") if isinstance(ent, dict) else None, targets, calls, results, seen)
    elif unit == "aiv_cc":
        import gzip
        src = "C:/Swarms/data/ai-village/claude_code_messages.jsonl.gz"
        OPENED.append(src)
        rows = []
        with gzip.open(src, "rt", encoding="utf-8") as f:
            for line in f:
                if not any(t in line for t in targets):
                    continue
                rows.append(json.loads(line))
        rows.sort(key=lambda r: (r.get("created_at") or "", r.get("id") or ""))
        seen = set()
        for r in rows:
            _scan_entry(r.get("content"), iso(r.get("created_at")), targets, calls, results, seen)
    else:
        raise ValueError(unit)
    return {t: (calls.get(t, []), results.get(t, [])) for t in targets}


def ac1_compare(unit, ev, raw):
    from analysis.lib.ir import error_marker, iso, parse_ts
    cl, rs = raw
    rec = {"call_found": len(cl), "result_found": len(rs)}
    if not cl or not rs:
        rec["differs"] = True
        rec["why"] = ["call or result not found in raw source"]
        return rec
    c, r = cl[0], rs[0]
    ca, ra = parse_ts(iso(c["ts"])), parse_ts(iso(r["ts"]))
    ia, ib = parse_ts(ev["ts"]), parse_ts(ev["ts_r"])
    raw_delta = (ra - ca).total_seconds() if (ca and ra) else None
    rec["delta_ir_s"] = float(ev["delta_s"])
    rec["delta_raw_s"] = raw_delta
    rec["stamps_equal"] = bool(ca == ia and ra == ib)
    rec["bytes_ir"] = int(ev["result_bytes"])
    rec["bytes_raw"] = len(r["text"].encode("utf-8"))
    raw_err = bool(r["is_error"] is True and error_marker(r["text"]) not in CC_REJECT)
    rec["err_ir"], rec["err_raw"] = bool(ev["err"]), raw_err
    inp = c["input"]
    cmd = inp.get("command") if isinstance(inp.get("command"), str) else inp.get("cmd")
    if isinstance(cmd, list):
        cmd = " ".join(str(x) for x in cmd)
    nc = pe.normalize_command(cmd) if isinstance(cmd, str) else None
    wd = inp.get("workdir")
    raw_n1 = None if nc is None else (f"{ev['key']}|{nc}|{wd}" if isinstance(wd, str) else f"{ev['key']}|{nc}")
    rec["n1_equal"] = raw_n1 == ev["n1"]
    rec["multiple_raw_occurrences"] = bool(len(cl) > 1 or len(rs) > 1)
    why = []
    if raw_delta is None or abs(raw_delta - rec["delta_ir_s"]) > 0.001:
        why.append("delta")
    if rec["bytes_raw"] != rec["bytes_ir"]:
        why.append("result bytes")
    if raw_err != rec["err_ir"]:
        why.append("error flag")
    if not rec["n1_equal"]:
        why.append("command key")
    rec["differs"] = bool(why)
    rec["why"] = why
    return rec


def ac1_audit(unit, R, kind):
    """AC1: audit_sample() of 30 flagged (detector numerator) primary-scope events, each looked up in the raw source.
    kind 'flagged' is the check; kind 'residual' (30 residual-bearing instances) is a diagnostic only."""
    r = R[R.cls == PRIMARY]
    lo, hi = RES_N1[unit]["bounds"]
    if kind == "flagged":
        r = r[(r.residual < lo) | (r.residual > hi)]
    r = r.sort_values(["session_id", "seq"])
    keys = list(zip(r.session_id, r.seq))
    pick = set(pe.audit_sample(keys, seed_parts=("N1", "AC1", kind, unit)))
    sub = r[[k in pick for k in keys]]
    evs = sub[["session_id", "call_id", "ts", "ts_r", "delta_s", "result_bytes", "err", "key", "n1"]].to_dict("records")
    raw = raw_lookup(unit, evs)
    recs = [ac1_compare(unit, e, raw[e["call_id"]]) for e in evs]
    nd = sum(1 for x in recs if x["differs"])
    out = {"population": f"{kind} primary-scope events, " + ("B u E" if CORPUS_OF[unit] in pe.CORPORA_WITH_E else "B"),
           "pool_size": int(len(keys)), "audited": int(len(recs)), "differing": int(nd),
           "differing_reasons": dict(Counter(w for x in recs for w in x.get("why", []))),
           "not_found": int(sum(1 for x in recs if x.get("call_found", 0) == 0 or x.get("result_found", 0) == 0)),
           "multiple_raw_occurrences": int(sum(1 for x in recs if x.get("multiple_raw_occurrences"))),
           "stamps_equal": int(sum(1 for x in recs if x.get("stamps_equal"))),
           "seed_parts": ["N1", "AC1", kind, unit]}
    if kind == "flagged":
        out["label"] = "FAIL" if nd >= pe.AUDIT_FAIL else ("PARSER_NOTE" if nd == 1 else "PASS")
        out["rule"] = "FAIL if >= 2 of 30 differ in a way that changes their contribution; 1 = PARSER_NOTE"
    else:
        out["label"] = "diagnostic only (post hoc, not a verdict)"
    out["events"] = recs  # numbers and booleans only (no text, no command)
    return out


# ================================================================================================== main
def main():
    store = defaultdict(dict)        # unit -> split -> (meta, frames)
    smeta = defaultdict(dict)        # unit -> session -> meta
    n_sess_split = defaultdict(dict)
    copied = {}
    for corpus, unit, split, df, nss in frames():
        n_sess_split[unit][split] = nss
        if df is None:
            continue
        if corpus not in copied:
            copied[corpus] = copied_call_ids(corpus)
        print(f"[{time.time() - T0:7.1f}s] {unit} {split}: {len(df)} rows, {nss} sessions", flush=True)
        meta, fr, sm, _ = per_split(corpus, unit, split, df, copied[corpus])
        store[unit][split] = (meta, fr)
        smeta[unit].update(sm)
        del df
        gc.collect()
    print(f"[{time.time() - T0:7.1f}s] statistics", flush=True)

    out = {"item": "n1_conditional_duration", "script": "analysis/probes/phase_e_n1.py",
           "prereg_section": "prereg_e.json n1_conditional_duration",
           "prereg_e_json_sha256": pe.sha256_file(pe.PREREG_E_JSON),
           "spec_module_sha256": PJ["provenance"]["spec_module_sha256"],
           "spec_module_sha256_lf": pe.sha256_lf(pe.ROOT / "analysis" / "probes" / "prereg_e_common.py"),
           "check_frozen": "passed",
           "verdict_rule_text": SPEC["verdict"], "min_n": SPEC["min_n"], "scope": SPEC["scope"],
           "thresholds_used": {"rho_band": RHO_BAND, "rho_pc_lo_min": PC_LO_MIN, "RR_min": RR_MIN, "flag_rate_max": FLAG_PT,
                               "flag_rate_hi_max": FLAG_HI, "min_residuals": MIN_RES, "min_sessions": MIN_SESS,
                               "detector_bounds": {u: RES_N1[u] for u in UNITS}, "G90_tok_per_s": {u: G90[u] for u in UNITS},
                               "tokens_per_char": TOK_PER_CHAR},
           "seeds": {"bootstrap": pe.SEED, "positive_control": "rng_for('N1pc', session_id, n1_key) with SEED_E=%d" % pe.SEED_E},
           "not_testable": SPEC["not_testable"],
           "units_not_in_prereg_list": {"swechat/copilot": "no copilot session in swechat B or E (not in S:n1 units)",
                                        "swechat/simple_text": "no pairs (field gate A: pairs 0)"},
           "cells_computed": 0, "units": {}}
    n_cells = 0
    for unit in UNITS:
        U = {"labels": LABELS.get(unit, []), "sessions_in_split": n_sess_split.get(unit, {}),
             "has_E": CORPUS_OF[unit] in pe.CORPORA_WITH_E}
        splits = [s for s in ("B", "E") if s in store[unit]]
        # pooled B u E frames
        pooled = {}
        for var in ("all", "AC2_no_truncated", "AC3_join_clean"):
            Rs, Ps, Cs = [], [], []
            for s in splits:
                R, PCF, C = store[unit][s][1][var]
                Rs.append(R)
                Ps.append(PCF)
                Cs.append(C)
            pooled[var] = (pd.concat(Rs, ignore_index=True) if Rs else pd.DataFrame(),
                           pd.concat(Ps, ignore_index=True) if Ps else pd.DataFrame(),
                           pd.concat(Cs, ignore_index=True) if Cs else pd.DataFrame())
        pops = {s: store[unit][s][1]["all"] for s in splits}
        if len(splits) == 2:
            pops["BE"] = pooled["all"]
        # ---- COVERAGE FIRST
        U["coverage_first"] = {}
        for s, (R, PCF, C) in pops.items():
            U["coverage_first"][s] = {cls: rr_stat(C, cls) for cls in SCOPES}
            A_ = (pd.concat([store[unit][x][1]["allpairs"] for x in splits], ignore_index=True) if s == "BE"
                  else store[unit][s][1]["allpairs"])
            ctx = {}
            for cls in SCOPES:
                nm = C[C.cls == cls].groupby("session_id").num.sum() if len(C) else pd.Series(dtype=float)
                dn = A_[A_.cls == cls].set_index("session_id").den_all
                ctx[cls] = stats.cluster_rate([float(nm.get(x, 0)) for x in dn.index], dn.to_numpy(float))
            U["coverage_first"][s]["context_calls_in_repeat_groups_over_all_scope_pairs"] = {
                "note": "context, not a verdict input: denominator = every call/result pair of the class before the "
                        "no-human-wait qualification", **ctx}
            U["coverage_first"][s]["residual_bearing_share_of_qualified"] = {
                cls: {"residuals": int((R.cls == cls).sum()) if len(R) else 0,
                      "qualified": int(C[C.cls == cls].den.sum()) if len(C) else 0} for cls in SCOPES}
        U["split_meta"] = {s: store[unit][s][0] for s in splits}
        # ---- per split x scope numbers and verdicts
        U["results"] = {}
        for s, (R, PCF, C) in pops.items():
            U["results"][s] = {}
            for cls in SCOPES:
                U["results"][s][cls] = block(R, PCF, C, cls, unit, f"units.{unit}.results.{s}.{cls}")
                n_cells += 1
        # ---- natural control (Phase B G set, copied)
        sep = P1["units"].get(unit, {}).get("separability", {})
        U["natural_control_phase_B_G_set"] = {"value": sep.get("G_spearman_bytes_latency", "no G set in Phase B"),
                                              "source": f"analysis/out/probe_1.json units.{unit}.separability.G_spearman_bytes_latency",
                                              "G_tools": sep.get("G_tools")}
        # ---- the N6 cell (primary scope): E verdict where E exists and is not INSUFFICIENT_N, else B ('B only')
        lb = U["results"].get("B", {}).get(PRIMARY, {}).get("verdict", {}).get("label")
        le = U["results"].get("E", {}).get(PRIMARY, {}).get("verdict", {}).get("label")
        if le is not None and le != "INSUFFICIENT_N":
            cell, src = le, f"units.{unit}.results.E.{PRIMARY}.verdict.label"
        else:
            cell, src = lb, f"units.{unit}.results.B.{PRIMARY}.verdict.label"
        U["cell_before_checks"] = {"label": cell, "source_path": src, "B": lb, "E": le,
                                   "suffix": "" if (le is not None and le != "INSUFFICIENT_N") else
                                   (" (B only, unreplicated)" if not U["has_E"] else " (B only; E INSUFFICIENT_N: NOT_REPLICABLE_AT_N)")}
        # ---- artifact checks + strata if the cell (or B / B u E) reaches WEAK or better
        any_weak = any(U["results"][s][PRIMARY]["verdict"]["label"] in ("ALIVE", "WEAK") for s in U["results"])
        final = cell
        checks = []
        if any_weak:
            ACp = "BE" if "BE" in pops else splits[0]
            Rb, Pb, Cb = pops[ACp]
            base = U["results"][ACp][PRIMARY]["verdict"]["label"]
            ac = {"population": "B u E" if ACp == "BE" else "B", "base_label": base}
            for var in ("AC2_no_truncated", "AC3_join_clean"):
                Rv, Pv, Cv = pooled[var] if ACp == "BE" else store[unit][splits[0]][1][var]
                b = block(Rv, Pv, Cv, PRIMARY, unit, f"units.{unit}.artifact_checks.{var}")
                lab = b["verdict"]["label"]
                ac[var] = {"label": lab, "fail": lab != base, "verdict": b["verdict"], "residuals": b["residuals"]["n"],
                           "rho_hon": b["rho_hon"], "rho_pc": b["rho_pc"], "RR": b["coverage_RR"],
                           "flag": b["detector"]["honest_flag_rate"]}
                if lab != base:
                    final = lower(final, lab) if lab in LVL else final
                    checks.append({"name": var, "effect": "lower label to " + str(lab)})
            ac["AC4_dominance"] = dominance_check(Rb, Pb, Cb, unit, base, smeta[unit])
            if ac["AC4_dominance"]["effect"] == "downgrade":
                final = pe.downgrade(final)
                checks.append({"name": "AC4 DOMINATED", "effect": "downgrade"})
            elif ac["AC4_dominance"]["effect"] == "cap_weak" and final == "ALIVE":
                final = "WEAK"
                checks.append({"name": "AC4 UNTESTABLE_WITHOUT_DOMINANT", "effect": "cap_weak"})
            if CORPUS_OF[unit] in ("swechat", "aiv_cu"):
                # weights per statistic: residual-bearing sessions for rho / flag rate, every session with qualified
                # primary-scope calls for RR (population cell size / analysed sessions of that statistic in the cell)
                rs_ = sorted(set(Rb[Rb.cls == PRIMARY].session_id)) if len(Rb) else []
                cs_ = sorted(set(Cb[Cb.cls == PRIMARY].session_id)) if len(Cb) else []
                wts = pe.post_strat_weights(CORPUS_OF[unit], rs_)
                wrr = pe.post_strat_weights(CORPUS_OF[unit], cs_)
                b = block(Rb, Pb, Cb, PRIMARY, unit, f"units.{unit}.artifact_checks.AC5_post_stratified", w=wts,
                          w_rr=wrr)
                lab = b["verdict"]["label"]
                ac["AC5_post_stratified"] = {"label": lab, "fail": lab != base, "verdict": b["verdict"],
                                             "rho_hon": b["rho_hon"], "rho_pc": b["rho_pc"], "RR": b["coverage_RR"],
                                             "flag": b["detector"]["honest_flag_rate"],
                                             "weights": "population cell size / analysed sessions in the cell (post_strat_weights)"}
                if lab != base:
                    final = lower(final, lab) if lab in LVL else final
                    checks.append({"name": "AC5", "effect": "lower label to " + str(lab)})
                if "B" in U["results"] and "E" in U["results"]:
                    bp = U["results"]["B"][PRIMARY]["rho_hon"].get("value")
                    e = U["results"]["E"][PRIMARY]["rho_hon"]
                    ac["AC5_shift_rho_hon"] = {"B_point": bp, "E_ci": [e.get("lo"), e.get("hi")],
                                               "SHIFT": (bp is not None and e.get("lo") is not None
                                                         and not (e["lo"] <= bp <= e["hi"])),
                                               "note": "reported, no verdict effect"}
            else:
                ac["AC5_post_stratified"] = {"label": "NOT_RUN", "reason": "no population table for this corpus"}
            if unit in ("swechat/claude_code", "aiv_cc") and U["cell_before_checks"]["label"] in ("ALIVE", "WEAK"):
                ac["AC1_parser"] = ac1_audit(unit, Rb, "flagged")
                ac["AC1_parser_diagnostic_residual_instances"] = ac1_audit(unit, Rb, "residual")
                if ac["AC1_parser"]["label"] == "FAIL":
                    final = pe.downgrade(final)
                    checks.append({"name": "AC1 FAIL", "effect": "downgrade"})
            else:
                ac["AC1_parser"] = {"label": "NOT_RUN", "reason": "the unit's N6 cell is not WEAK or better (cell "
                                    f"{U['cell_before_checks']['label']}); only the B u E pooled re-measurement reached "
                                    "WEAK, and AC1 is required for N cells (S:artifact_checks)"}
            U["artifact_checks"] = ac
            st = strata_check(Rb, Pb, Cb, unit, smeta[unit])
            U["stratification"] = st
            if st["CONFINED_any_axis"]:
                final = pe.downgrade(final)
                checks.append({"name": "CONFINED", "effect": "downgrade"})
        else:
            U["artifact_checks"] = {"status": "not required: no B / E / B u E primary verdict reached WEAK or better "
                                              "(S:artifact_checks applies to N cells at WEAK or better)"}
        U["cell_final"] = {"label": final, "checks_applied": checks,
                           "suffix": U["cell_before_checks"]["suffix"] + "".join(f" [{x}]" for x in U["labels"])}
        out["units"][unit] = U
    out["units"]["swechat/cursor"] = {"cell_final": {"label": "NOT_TESTABLE(no results)"},
                                      "sessions_in_split": n_sess_split.get("swechat/cursor", {})}
    for u_, why in SPEC["not_testable"].items():
        if u_ not in out["units"]:
            out["units"][u_] = {"cell_final": {"label": f"NOT_TESTABLE({why})"}}
    out["cells_computed"] = n_cells
    out["deviations"] = DEVIATIONS
    summ = {}
    for unit in UNITS:
        U = out["units"][unit]
        row = {"cell": U["cell_final"]["label"], "cell_before_checks": U["cell_before_checks"]["label"],
               "suffix": U["cell_final"]["suffix"]}
        for sp, bl in U["results"].items():
            for cls in SCOPES:
                b = bl[cls]
                row[f"{sp}.{cls}"] = {"RR": b["coverage_RR"].get("rate"), "residuals": b["residuals"]["n"],
                                     "sessions": b["residuals"].get("n_sessions", 0),
                                     "rho_hon": [b["rho_hon"].get("value"), b["rho_hon"].get("lo"), b["rho_hon"].get("hi")],
                                     "rho_pc": [b["rho_pc"].get("value"), b["rho_pc"].get("lo"), b["rho_pc"].get("hi")],
                                     "flag_rate": [b["detector"]["honest_flag_rate"].get("rate"),
                                                   b["detector"]["honest_flag_rate"].get("lo"),
                                                   b["detector"]["honest_flag_rate"].get("hi")],
                                     "label": b["verdict"]["label"], "rule": b["verdict"]["rule"],
                                     "path": f"units.{unit}.results.{sp}.{cls}"}
        summ[unit] = row
    out["summary_raw"] = summ
    out["opened_files"] = sorted(set(OPENED)) + ["analysis/prereg.json", "analysis/out/probe_1.json",
                                                 "C:/Swarms/data/swe-chat-pinned/sessions.parquet (metadata: repo_id, user_id)"]
    out["runtime_s"] = round(time.time() - T0, 1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)),
                   encoding="utf-8")
    print(f"[{time.time() - T0:7.1f}s] wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
