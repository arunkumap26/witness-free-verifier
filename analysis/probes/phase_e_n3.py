"""Phase E, Track A, item N3: reaction time to a result (prereg_e.json S:n3_reaction_time).

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_n3

What it does, in the order the pre-registration fixes:
  1. check_frozen() (prereg_e_common.py must be the pre-registered module).
  2. Per unit x split (B; E where the corpus has one; B u E pooled for the artifact checks / strata):
     gaps from prereg_e_common.n3_gaps() (reproduced row by row by gaps_ext(), which carries the batch's row indices
     for the artifact checks and the next response's usage; the (session, gap, bytes) list is asserted identical to
     n3_gaps()), rho_s = Spearman(gap, batch bytes) for every session with >= 20 gaps, the pooled Spearman over those
     sessions' gaps with a session-bootstrap CI, the share of sessions with rho_s <= 0 (Wilson), the secondary
     pooled Spearman of (gap - usage_out(next response) / G50) where usage exists, the positive control (within-session
     permutation of gaps, rng_for('N3pc', session_id, 'gaps')) and the verdict per S:n3_reaction_time.verdict.
  3. For any unit whose B, E or B u E verdict reaches WEAK or better: AC2-AC5 and the four stratification axes on
     B u E (S:artifact_checks, S:stratification); AC1 when the unit's N6 cell itself is WEAK or better.
Reads: analysis/cache/{swechat,cc_local,aiv_cc}_{B,E}.parquet through prereg_e_common.read_cache (never A, never H),
       swechat_population.parquet and swe-chat-pinned sessions.parquet (metadata only, through prereg_e_common helpers),
       analysis/prereg.json (Phase B G50), analysis/out/phase_e/prereg_e_calibration.json (A eligibility counts, context).
       AC1 only: the raw swechat transcripts of the audited sessions (read-only).
Writes: analysis/out/phase_e/n3.json (raw numbers only). Interpretation: analysis/notes/phase_e_n2_n3.md.
cc_local: aggregates only (no command, path, text, session id or project name is written). aiv_cc: single-agent case
study.
"""
import gc
import json
import math
import time
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from analysis.lib import stats
from analysis.lib.ir import parse_ts
from analysis.probes import prereg_common as pc
from analysis.probes import prereg_e_common as pe
from analysis.probes import prereg_e_calibration as pecal  # COLS: the column set the A calibration read

T0 = time.time()
PJ = pe.check_frozen()
SPEC = PJ["n3_reaction_time"]
TERC = PJ["resolved"]["length_terciles_A"]
PRB = json.loads((pe.ROOT / "analysis" / "prereg.json").read_text(encoding="utf-8"))
G50 = {u: v["G50"] for u, v in PRB["resolved"]["probe1"]["generation_rate"].items()}
G50_METHOD = {u: v["method"] for u, v in PRB["resolved"]["probe1"]["generation_rate"].items()}
CALJ = json.loads((pe.OUT_E / "prereg_e_calibration.json").read_text(encoding="utf-8"))

OUT = pe.OUT_E / "n3.json"
UNITS = SPEC["units"]
OTHER_UNITS = {  # the N6 columns that are not in S:n3_reaction_time.units
    "swechat/copilot": "no event stamps usable: 0 copilot sessions in swechat B (prereg.json population_B); not in "
                       "S:n3_reaction_time.units",
    "swechat/cursor": "no results (field gate A: pairs 0)",
    "swechat/simple_text": "no calls or results (field gate A: pairs 0)",
}
MIN_GAPS, MIN_SESS = 20, 20                 # S:n3_reaction_time.per_session / min_n
ALIVE_LO, SHARE_PT, SHARE_HI = 0.30, 0.10, 0.20  # S:n3_reaction_time.verdict (judgment calls fixed at pre-registration)
CORPUS_OF = {u: ("swechat" if u.startswith("swechat/") else u) for u in UNITS}
LABELS = {
    "swechat/claude_code": [],
    "swechat/codex": [],
    "swechat/opencode": [],
    "swechat/gemini": [],
    "cc_local": ["private: aggregates only", "B only, unreplicated (no E split)"],
    "aiv_cc": ["single-agent case study", "B only, unreplicated (no E split)"],
}
STATED_LIMIT = SPEC["note"]
OPENED = []

# ================================================================================================== deviations / choices
DEVIATIONS = [
    {"item": "output file names",
     "prereg_said": "prereg_e.json outputs: 'N1-N5': phase_e_n<k>.py -> n<k>.json",
     "what_you_did": "followed the pre-registration: analysis/probes/phase_e_n3.py -> analysis/out/phase_e/n3.json (and "
                     "phase_e_n2.py -> n2.json); the orchestrator's item key 'n2_n3' names the joint notes file "
                     "analysis/notes/phase_e_n2_n3.md",
     "why": "the pre-registration is the output contract", "effect_on_verdict": "none"},
    {"item": "population of the pooled Spearman",
     "prereg_said": "per session rho_s for sessions with >= 20 gaps; pooled rho with a session-bootstrap CI; min n >= 20 "
                    "sessions with >= 20 gaps",
     "what_you_did": "the verdict's pooled rho is computed over the gaps of the sessions with >= 20 gaps (the same "
                     "sessions as rho_s and the min n). The pooled rho over every gap of every session is reported as "
                     "context (rho_pooled_all_sessions), not used by the verdict",
     "why": "the prereg does not say which gaps enter the pooled rho; the min-n population is the smallest faithful "
            "reading", "effect_on_verdict": "none expected; both are reported"},
    {"item": "sessions with an undefined rho_s",
     "prereg_said": "rho_s = Spearman(gap, bytes) for sessions with >= 20 gaps; share(rho_s <= 0) (Wilson)",
     "what_you_did": "a session with >= 20 gaps whose gaps or batch bytes are all equal has no Spearman "
                     "(prereg_e_common.spearman returns None). It counts towards the min n (it has >= 20 gaps), "
                     "abstains from the share and the positive control, and is counted in rho_s.n_undefined",
     "why": "no rank correlation exists for a constant vector", "effect_on_verdict": "counts reported per block"},
    {"item": "positive-control seed key",
     "prereg_said": "positive controls rng_for('<item>pc', session_id, key)",
     "what_you_did": "rng_for('N3pc', session_id, 'gaps'): one permutation of the session's gap vector (bytes kept in "
                     "place); recall = share of sessions with permuted rho_s <= 0 (Wilson). The pooled permuted rho "
                     "is reported as context (between-session structure survives a within-session permutation)",
     "why": "N3 has one gap vector per session, so the key is constant", "effect_on_verdict": "none (recall is not in "
                                                                                              "the verdict rule)"},
    {"item": "secondary: next response's usage_out",
     "prereg_said": "secondary: gap minus usage_out(next response) / G50 where usage exists",
     "what_you_did": "usage_out of the next model event's response = max usage_out over the session's rows with that "
                     "api_msg_id (prereg_e_common.response_table's rule); Codex (no api_msg_id): the first meta row "
                     "with usage_out after the next model event in the session (the token_count that closes the "
                     "response, response_table's rule). G50 = prereg.json resolved.probe1.generation_rate.<unit>.G50 "
                     "(output tokens per second, Phase B A split). aiv_cc usage_out is a streaming partial (resolved.n2."
                     "aiv_cc G2 median 1.0), so its secondary is computed literally and labelled",
     "why": "the prereg names the quantity, not the join", "effect_on_verdict": "none (secondary, no verdict)"},
    {"item": "verdict rule gaps",
     "prereg_said": "ALIVE / WEAK / DEAD rules of S:n3_reaction_time.verdict",
     "what_you_did": "INSUFFICIENT_N below 20 sessions with >= 20 gaps; INCONCLUSIVE when the pooled CI has < 900 valid "
                     "bootstrap draws (prereg.json global.ci_methods). Rule order: ALIVE, WEAK, DEAD",
     "why": "the rules presuppose a reportable CI", "effect_on_verdict": "see results"},
    {"item": "B u E pooled verdicts and when the artifact checks run",
     "prereg_said": "N6 fill rule: the cell is the E verdict where E exists and is not INSUFFICIENT_N, else the B verdict "
                    "'B only'; artifact checks on B u E for any N cell at WEAK or better",
     "what_you_did": "B, E and B u E are computed. AC2-AC5 and the strata run on B u E (B for units without E) whenever "
                     "B, E or B u E reaches WEAK or better (the N1 script's practice); AC1 runs when the cell itself "
                     "is WEAK or better. The pooled label is never the cell",
     "why": "smallest faithful reading; reporting more cannot raise a cell", "effect_on_verdict": "none on the cells"},
    {"item": "artifact-check event definitions for a gap",
     "prereg_said": "AC2: drop every event whose result text matches truncated_result(); AC3: recompute on "
                    "join_clean_mask() pairs",
     "what_you_did": "an N3 event is a gap whose batch holds one or more results. AC2 drops a gap if any result of its "
                     "batch is truncated_result(text, extra); AC3 drops a gap if any result of its batch is not the "
                     "result side of a join_clean_mask() pair (copied call ids over the corpus's B and E caches). rho_s "
                     "and eligibility are recomputed after the drop",
     "why": "batch bytes are a sum over results, so a partial drop would change the statistic's input",
     "effect_on_verdict": "see artifact_checks"},
    {"item": "AC4 / AC5 / strata details",
     "prereg_said": "AC4 over the statistic's denominator events; AC5 post-stratified recompute; strata on four axes",
     "what_you_did": "AC4 denominator events = gaps of sessions with >= 20 gaps; leave-outs recompute every quantity on "
                     "all sessions outside the left-out cluster; aiv_cc's single agent/model is labelled only. AC5: "
                     "pooled rho as a weighted Spearman (weighted mid-ranks, weighted Pearson; the N1 script's "
                     "implementation, copied) and share(rho_s <= 0) as weighted_cluster_rate (one event per "
                     "session), whose bootstrap hi replaces the Wilson hi. Strata: tool_key of the call answered by the "
                     "batch's last stamped result (cc_local through private_key), modal model, repo cluster, length "
                     "tercile of paired calls per session at the A cuts; a stratum is reportable at >= 20 sessions with "
                     ">= 20 gaps inside the stratum",
     "why": "smallest faithful reading", "effect_on_verdict": "see artifact_checks"},
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
            df = pe.read_cache("swechat", split, pecal.COLS, filters=[("session_id", "in", ids)])
            yield "swechat", f"swechat/{f}", split, df, len(ids)
        for f in ("copilot", "cursor", "simple_text"):
            yield "swechat", f"swechat/{f}", split, None, len(by.get(f, []))
    for c in ("cc_local", "aiv_cc"):
        OPENED.append(f"analysis/cache/{c}_B.parquet")
        df = pe.read_cache(c, "B", pecal.COLS)
        yield c, c, "B", df, int(df.session_id.nunique())


def copied_call_ids(corpus):
    """call_ids that occur in more than one session across the corpus's B and E caches (AC3)."""
    parts = []
    for split in (("B", "E") if corpus in pe.CORPORA_WITH_E else ("B",)):
        d = pe.read_cache(corpus, split, ["session_id", "kind", "call_id"], filters=[("kind", "==", "call")])
        parts.append(d[d.call_id.notna()][["session_id", "call_id"]].drop_duplicates())
    d = pd.concat(parts, ignore_index=True)
    n = d.groupby("call_id").session_id.nunique()
    return frozenset(str(x) for x in n[n > 1].index)


# ================================================================================================== gaps
def gaps_ext(u):
    """prereg_e_common.n3_gaps() reproduced line by line, additionally returning the next model event's row index, the
    row index of the batch's last stamped result and the row indices of every result in the batch."""
    u = u.sort_values(["session_id", "seq"])
    thr = list(zip(u.session_id, u.is_subagent.astype("boolean").fillna(False), u.agent_id.astype(object).fillna("")))
    u = u.assign(_thr=thr)
    rows = []
    for _, g in u.groupby("_thr", sort=False):
        last_t, nbytes, blocked, batch, last_i = None, 0, False, [], None
        sid = g.session_id.iloc[0]
        for ix, kind, ts, txt in zip(g.index, g.kind, g.ts.astype(object), g.text.astype(object)):
            if kind == "result":
                t = parse_ts(ts) if isinstance(ts, str) else None
                if t is not None:
                    last_t, last_i = t, ix
                nbytes += len(txt.encode("utf-8")) if isinstance(txt, str) else 0
                batch.append(ix)
            elif kind in ("user", "system"):
                blocked = True
            elif kind in ("assistant", "call"):
                if last_t is not None and not blocked and isinstance(ts, str):
                    t = parse_ts(ts)
                    if t is not None:
                        gap = (t - last_t).total_seconds()
                        if 0 < gap <= 600:
                            rows.append((sid, gap, nbytes, ix, last_i, tuple(batch)))
                last_t, nbytes, blocked, batch, last_i = None, 0, False, [], None
    return rows


def per_split(corpus, unit, split, u, copied):
    u = u.reset_index(drop=True)
    rows = gaps_ext(u)
    ref = pe.n3_gaps(u)
    same = len(ref) == len(rows) and all(a[0] == b[0] and a[1] == b[1] and a[2] == b[2] for a, b in zip(ref, rows))
    assert same, f"gaps_ext differs from n3_gaps for {unit} {split}"
    P = pc.make_pairs(u[u.kind.isin(["call", "result"])])
    jc = pe.join_clean_mask(u, P, copied)
    clean = set(zip(P.session_id[jc], P.call_id.astype(str)[jc]))
    keys = {(s, str(c)): pc.tool_key(unit, t if isinstance(t, str) else None, tr if isinstance(tr, str) else None)
            for s, c, t, tr in
            zip(P.session_id, P.call_id.astype(object), P.tool.astype(object), P.tool_raw.astype(object))}
    n_pairs = P.groupby("session_id").size().to_dict()
    # next response's usage_out (secondary)
    if unit == "swechat/codex":
        m = u[(u.kind == "meta") & u.usage_out.notna()]
        closers = {s: (g.seq.to_numpy(), g.usage_out.to_numpy(float)) for s, g in m.sort_values("seq").groupby("session_id")}
    else:
        r = u[u.api_msg_id.notna() & u.usage_out.notna()]
        resp_usage = r.groupby(["session_id", "api_msg_id"]).usage_out.max().to_dict()
    sid_col, kind_col = u.session_id.to_numpy(), u.kind.to_numpy()
    text_col, extra_col = u.text.astype(object).to_numpy(), u.extra.astype(object).to_numpy()
    cid_col, seq_col = u.call_id.astype(object).to_numpy(), u.seq.to_numpy()
    msg_col = u.api_msg_id.astype(object).to_numpy()
    tool_col, traw_col = u.tool.astype(object).to_numpy(), u.tool_raw.astype(object).to_numpy()
    out = []
    for s, gap, nb, nx, li, batch in rows:
        trunc = any(pe.truncated_result(text_col[i], extra_col[i]) for i in batch)
        jcl = all((s, str(cid_col[i])) in clean for i in batch) if batch else False
        k = keys.get((s, str(cid_col[li]))) if li is not None else None
        if k is None and li is not None:
            k = pc.tool_key(unit, tool_col[li] if isinstance(tool_col[li], str) else None,
                            traw_col[li] if isinstance(traw_col[li], str) else None)
        if unit == "cc_local" and k is not None:
            k = pc.private_key(k)
        if unit == "swechat/codex":
            sq, uo = closers.get(s, (np.array([]), np.array([])))
            j = int(np.searchsorted(sq, seq_col[nx], side="right"))
            usage = float(uo[j]) if j < len(sq) else np.nan
        else:
            mm = msg_col[nx]
            usage = float(resp_usage.get((s, mm), np.nan)) if isinstance(mm, str) else np.nan
        out.append({"session_id": s, "gap": float(gap), "bytes": int(nb), "n_results": len(batch), "trunc": bool(trunc),
                    "join_clean": bool(jcl), "key": k if k is not None else "unknown", "usage_next": usage,
                    "next_kind": kind_col[nx], "next_seq": int(seq_col[nx]), "last_result_seq": int(seq_col[li]),
                    "last_call_id": str(cid_col[li]) if cid_col[li] is not None else None,
                    "batch_call_ids": tuple(str(cid_col[i]) for i in batch), "split": split})
    G = pd.DataFrame(out)
    model = pe.session_model_map(u)
    repo = pe.session_cluster_map(corpus, u, kind="repo")
    user = pe.session_cluster_map(corpus, u, kind="user") if corpus == "swechat" else {}
    terc = pe.length_tercile_map(n_pairs, TERC[unit]["cuts"])
    sm = {}
    for s in set(u.session_id.unique()):
        sm[s] = {"model": _lab(model.get(s, "unknown")), "repo": _lab(repo.get(s, "unknown")),
                 "user": _lab(user.get(s, "n/a")), "length_tercile": terc.get(s, "short"), "split": split}
    kinds = Counter(kind_col)
    meta = {"rows": int(len(u)), "sessions": int(u.session_id.nunique()), "rows_by_kind": {str(k): int(v) for k, v in kinds.items()},
            "gaps": int(len(G)), "gaps_identical_to_n3_gaps": bool(same),
            "results": int(kinds.get("result", 0)),
            "gaps_with_truncated_result": int(G.trunc.sum()) if len(G) else 0,
            "gaps_not_join_clean": int((~G.join_clean).sum()) if len(G) else 0,
            "gaps_with_usage_next": int(G.usage_next.notna().sum()) if len(G) else 0}
    return meta, G, sm


def _lab(x):
    if x is None or x is pd.NA or (isinstance(x, float) and math.isnan(x)):
        return "nan"
    return str(x)


# ================================================================================================== statistics
def wspearman_fn(gs):
    """Weighted Spearman over (x, y, w) session payloads: weighted mid-ranks, then weighted Pearson (copied from
    analysis/probes/phase_e_n1.py, AC5)."""
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
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) == 0:
        return {"value": None, "n": 0, "n_sessions": 0, "valid_draws": 0, "ci_reported": False}
    if w is None:
        b = pe.session_spearman(x, y, np.asarray(sids))
    else:
        df = pd.DataFrame({"x": x, "y": y, "s": np.asarray(sids)})
        df["w"] = [w.get(s, 0.0) for s in df.s]
        groups = [(g.x.to_numpy(float), g.y.to_numpy(float), g.w.to_numpy(float)) for _, g in df.groupby("s")]
        b = pe.boot_stat(groups, wspearman_fn)
    b["n"] = int(np.isfinite(x).sum())
    return b


def qtiles(v, sids=None):
    v = np.asarray(v, float)
    v = v[np.isfinite(v)]
    out = {"n": int(len(v))}
    if sids is not None:
        out["n_sessions"] = int(len(set(sids)))
    if len(v):
        for qq in (0.0, 0.05, 0.25, 0.5, 0.75, 0.95, 1.0):
            out[f"q{qq:g}"] = float(np.quantile(v, qq))
    return out


def per_session_rho(ge, permute=False):
    out = {}
    for s, x in ge.groupby("session_id", sort=True):
        g = x.gap.to_numpy(float)
        if permute:
            g = g[pe.rng_for("N3pc", s, "gaps").permutation(len(g))]
        out[s] = pe.spearman(g, x.bytes.to_numpy(float))
    return out


def block(G, unit, path, sess=None, w=None, full=True):
    """All N3 numbers for one population of gaps; the verdict last. full=False skips context / positive control."""
    g = G if sess is None else (G[G.session_id.isin(sess)] if len(G) else G)
    if not len(g):
        g = pd.DataFrame(columns=["session_id", "gap", "bytes", "usage_next"])
    n_by = g.groupby("session_id").size()
    elig = set(n_by[n_by >= MIN_GAPS].index)
    ge = g[g.session_id.isin(elig)]
    out = {"gaps": int(len(g)), "sessions_with_gaps": int(len(n_by)), "eligible_sessions": int(len(elig)),
           "eligible_gaps": int(len(ge))}
    rs = per_session_rho(ge)
    d = {s: r for s, r in rs.items() if r is not None}
    k = sum(1 for r in d.values() if r <= 0)
    out["rho_s"] = {"n_defined": len(d), "n_undefined": len(rs) - len(d), "quantiles": qtiles(list(d.values()))}
    if w is None:
        p, lo, hi = stats.wilson(k, len(d))
        out["share_rho_s_le_0"] = {"k": int(k), "n": len(d), "share": p, "lo": lo, "hi": hi, "ci": "wilson over sessions"}
    else:
        ks = sorted(d)
        r = pe.weighted_cluster_rate([1.0 if d[s] <= 0 else 0.0 for s in ks], [1.0] * len(ks), [w.get(s, 0.0) for s in ks])
        out["share_rho_s_le_0"] = {"k": int(k), "n": len(d), "share": r.get("rate"), "lo": r.get("lo"), "hi": r.get("hi"),
                                   "ci": "weighted_cluster_rate bootstrap (post-stratified)"}
    out["rho_pooled"] = rho(ge.gap, ge.bytes, ge.session_id, w)
    if full:
        out["gap_s_quantiles"] = qtiles(ge.gap, ge.session_id.tolist())
        out["bytes_quantiles"] = qtiles(ge.bytes)
        out["zero_byte_gaps"] = int((ge.bytes == 0).sum())
        out["rho_pooled_all_sessions"] = rho(g.gap, g.bytes, g.session_id)
        u_ = ge[ge.usage_next.notna()]
        g50 = G50.get(unit)
        adj = (u_.gap - u_.usage_next / g50) if (g50 and len(u_)) else pd.Series(dtype=float)
        out["secondary_usage_adjusted"] = {
            "definition": "Spearman(gap - usage_out(next response) / G50, batch bytes) over eligible-session gaps with usage",
            "G50_tok_per_s": g50, "G50_method_phase_B": G50_METHOD.get(unit), "gaps_with_usage": int(len(u_)),
            "share_of_eligible_gaps": (len(u_) / len(ge)) if len(ge) else None,
            "usage_next_quantiles": qtiles(u_.usage_next if len(u_) else []),
            "adjusted_gap_le_0": int((adj <= 0).sum()) if len(adj) else 0,
            "rho": rho(adj, u_.bytes if len(u_) else [], u_.session_id if len(u_) else [])}
        pr = per_session_rho(ge, permute=True)
        pd_ = {s: r for s, r in pr.items() if r is not None}
        kp = sum(1 for r in pd_.values() if r <= 0)
        p, lo, hi = stats.wilson(kp, len(pd_))
        perm_gap = []
        for s, x in ge.groupby("session_id", sort=True):
            gg = x.gap.to_numpy(float)
            perm_gap.append(pd.DataFrame({"s": s, "gap": gg[pe.rng_for("N3pc", s, "gaps").permutation(len(gg))],
                                          "bytes": x.bytes.to_numpy(float)}))
        PP = pd.concat(perm_gap, ignore_index=True) if perm_gap else pd.DataFrame(columns=["s", "gap", "bytes"])
        out["positive_control_permutation"] = {
            "definition": "within-session permutation of gaps (rng_for('N3pc', session_id, 'gaps')); detector flags a "
                          "session if its permuted rho_s <= 0",
            "recall": {"k": int(kp), "n": len(pd_), "share": p, "lo": lo, "hi": hi},
            "rho_s_quantiles": qtiles(list(pd_.values())),
            "rho_pooled_permuted_context": rho(PP.gap, PP.bytes, PP.s)}
    out["verdict"] = verdict(out, path, weighted=w is not None)
    return out


def verdict(b, path, weighted=False):
    if b["eligible_sessions"] < MIN_SESS:
        return {"label": "INSUFFICIENT_N", "rule": f"min n: >= {MIN_SESS} sessions with >= {MIN_GAPS} gaps",
                "deciding_number": b["eligible_sessions"], "deciding_path": f"{path}.eligible_sessions"}
    rp = b["rho_pooled"]
    if not rp.get("ci_reported") or rp.get("lo") is None:
        return {"label": "INCONCLUSIVE", "rule": "pooled-rho CI not reportable (< 900 valid draws)",
                "deciding_number": rp.get("valid_draws"), "deciding_path": f"{path}.rho_pooled.valid_draws"}
    lo = rp["lo"]
    sh = b["share_rho_s_le_0"]
    conds = [("pooled rho CI lo >= 0.30", lo >= ALIVE_LO, lo, f"{path}.rho_pooled.lo"),
             ("share(rho_s <= 0) <= 0.10", sh["share"] is not None and sh["share"] <= SHARE_PT, sh["share"],
              f"{path}.share_rho_s_le_0.share"),
             ("share(rho_s <= 0) " + ("bootstrap" if weighted else "Wilson") + " hi <= 0.20",
              sh["hi"] is not None and sh["hi"] <= SHARE_HI, sh["hi"], f"{path}.share_rho_s_le_0.hi")]
    rec = [{"condition": c[0], "met": bool(c[1]), "value": c[2], "path": c[3]} for c in conds]
    if all(c[1] for c in conds):
        return {"label": "ALIVE", "rule": "every ALIVE condition met", "conditions": rec,
                "deciding_number": {"rho_pooled_lo": lo, "share": sh["share"], "share_hi": sh["hi"]},
                "deciding_path": [c[3] for c in conds]}
    if lo > 0:
        failing = [c for c in conds if not c[1]]
        return {"label": "WEAK", "rule": "pooled rho CI lo > 0; ALIVE condition(s) failing: " + "; ".join(c[0] for c in failing),
                "conditions": rec, "deciding_number": {"rho_pooled_lo": lo, **{c[0]: c[2] for c in failing}},
                "deciding_path": [f"{path}.rho_pooled.lo"] + [c[3] for c in failing]}
    return {"label": "DEAD", "rule": "pooled rho CI lo <= 0", "conditions": rec, "deciding_number": lo,
            "deciding_path": f"{path}.rho_pooled.lo"}


LVL = {"ALIVE": 2, "WEAK": 1, "DEAD": 0}


def lower(a, b):
    if a in LVL and b in LVL:
        return a if LVL[a] <= LVL[b] else b
    return a


def short(b):
    return {"label": b["verdict"]["label"], "eligible_sessions": b["eligible_sessions"], "eligible_gaps": b["eligible_gaps"],
            "rho_pooled": [b["rho_pooled"].get("value"), b["rho_pooled"].get("lo"), b["rho_pooled"].get("hi")],
            "share_rho_s_le_0": [b["share_rho_s_le_0"].get("share"), b["share_rho_s_le_0"].get("lo"),
                                 b["share_rho_s_le_0"].get("hi")], "n_defined": b["rho_s"]["n_defined"]}


# ================================================================================================== artifact checks
def dominance_check(G, unit, base, sm):
    n_by = G.groupby("session_id").size()
    w = n_by[n_by >= MIN_GAPS].to_dict()
    all_s = set(G.session_id)
    kinds = ["repo", "user", "model"] if CORPUS_OF[unit] == "swechat" else ["repo", "model"]
    out = {"denominator": "gaps of sessions with >= 20 gaps", "kinds": {}}
    leaveouts, dominated = [], False
    for kind in kinds:
        cmap = {s: sm[s][kind] for s in w}
        d = pe.dominance(w, cmap) if w else {"dominated": False}
        rec = {k: d.get(k) for k in ("top_cluster", "top_share_events", "top_share_sessions", "n_clusters", "dominated")}
        rec["top5"] = [[c if unit != "cc_local" else f"cluster_{i}", a, b] for i, (c, a, b) in
                       enumerate(d.get("top_clusters", []))]
        if unit == "cc_local":
            rec["top_cluster"] = "cluster_0"
        cdom = max(d.get("top_share_events", 0) or 0, d.get("top_share_sessions", 0) or 0) > pe.DOM_SHARE
        rec["cluster_dominated"] = bool(cdom)
        if cdom and unit == "aiv_cc" and d.get("n_clusters") == 1:
            rec["label_only"] = "aiv_cc is one agent (one model): always dominated, labelled only (PREREG_E 1.1)"
            out["kinds"][kind] = rec
            continue
        out["kinds"][kind] = rec
        if cdom:
            dominated = True
            top5 = [c for c, _, _ in d["top_clusters"]]
            for i, c in enumerate(top5):
                leaveouts.append((kind, c if unit != "cc_local" else f"cluster_{i}", {s for s in all_s if sm[s][kind] != c}))
    tot = sum(w.values())
    top = max(w.items(), key=lambda kv: kv[1]) if w else (None, 0)
    out["top_session_share_events"] = (top[1] / tot) if tot else None
    if tot and top[1] / tot > pe.DOM_SESSION:
        dominated = True
        for rank, (s, _) in enumerate(sorted(w.items(), key=lambda kv: -kv[1])[:5]):
            leaveouts.append(("session", f"largest_session_rank_{rank + 1}", all_s - {s}))
    out["dominated"] = dominated
    res, effect = [], "pass"
    for kind, c, keep in leaveouts:
        b = block(G, unit, "artifact_checks.AC4_dominance.leaveouts", sess=keep, full=False)
        lab = b["verdict"]["label"]
        res.append({"kind": kind, "left_out": c, **short(b)})
        if lab == "INSUFFICIENT_N":
            if effect == "pass":
                effect = "cap_weak"
        elif lab in LVL and base in LVL and LVL[lab] < LVL[base]:
            effect = "downgrade"
    out["leaveouts"] = res
    out["effect"] = effect if dominated else "pass"
    out["status"] = ("DOMINATED" if out["effect"] == "downgrade" else "UNTESTABLE_WITHOUT_DOMINANT"
                     if out["effect"] == "cap_weak" else "dominated, label stable" if dominated else "not dominated")
    return out


def strata_check(G, unit, sm):
    out = {}
    for axis in ("tool_key", "model", "repo", "length_tercile"):
        labels, rec = {}, {}
        if axis == "tool_key":
            groups = {k: G[G.key == k] for k in sorted(G.key.unique())}
        else:
            vals = defaultdict(set)
            for s in set(G.session_id):
                vals[sm[s][axis]].add(s)
            groups = {v: G[G.session_id.isin(ss)] for v, ss in vals.items()}
        for i, (k, gg) in enumerate(sorted(groups.items(), key=lambda kv: -kv[1].session_id.nunique())):
            b = block(gg, unit, f"stratification.{axis}", full=False)
            name = k if unit != "cc_local" or axis in ("tool_key", "length_tercile") else f"{axis}_{i}"
            rec[name] = short(b)
            labels[name] = b["verdict"]["label"] if b["verdict"]["label"] in LVL else None
        out[axis] = {"strata": rec, "confinement": pe.confinement(labels)}
    out["CONFINED_any_axis"] = any(v["confinement"] == "CONFINED" for v in out.values() if isinstance(v, dict))
    return out


# ---------------------------------------------------------------------------------------------- AC1 (raw lookups)
def _iter_lines(text):
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


def _codex_text(out, pt="function_call_output"):
    """Result text as the swechat loader builds it (load_swechat.parse_codex): a string output as is, a list of items
    joined (text items, '[image]' markers), anything else as compact JSON."""
    from analysis.lib.ir import j
    if isinstance(out, str):
        return out
    if isinstance(out, list) and pt != "tool_search_output":
        parts = []
        for c in out:
            if not isinstance(c, dict):
                continue
            if c.get("type") in ("input_text", "output_text", "text"):
                parts.append(c.get("text") or "")
            elif c.get("type") in ("input_image", "image"):
                parts.append("[image]")
        return "\n".join(parts)
    return j(out)


def raw_codex_batch_bytes(sid, call_ids):
    """UTF-8 bytes of the raw outputs of the given call ids (first output per call id), summed; None if one is missing."""
    path = pe.SWE_TRANSCRIPTS / f"{sid}.jsonl"
    b = path.read_bytes()
    try:
        text = b.decode("utf-8")
    except UnicodeDecodeError:
        text = b.decode("utf-8", errors="replace")
    got = {}
    for e in _iter_lines(text):
        if not isinstance(e, dict) or e.get("type") != "response_item":
            continue
        p = e.get("payload") if isinstance(e.get("payload"), dict) else {}
        pt = p.get("type")
        if pt in ("function_call_output", "custom_tool_call_output", "tool_search_output") and p.get("call_id") in call_ids                 and p.get("call_id") not in got:
            got[p["call_id"]] = len(_codex_text(p.get("output") if pt != "tool_search_output" else p.get("tools"),
                                                pt).encode("utf-8"))
    if any(c not in got for c in call_ids):
        return None
    return sum(got.values())


def raw_codex_lookup(sid, call_id):
    """Raw Codex rollout (read independently of the IR build): timestamp and output text of the result with this
    call_id, and the timestamp of the next response_item that the IR emits as a model event (assistant message or a
    function / custom / tool-search call; reasoning items are not events in the IR)."""
    from analysis.lib.ir import iso
    path = pe.SWE_TRANSCRIPTS / f"{sid}.jsonl"
    b = path.read_bytes()
    try:
        text = b.decode("utf-8")
    except UnicodeDecodeError:
        text = b.decode("utf-8", errors="replace")
    ents = [e for e in _iter_lines(text) if isinstance(e, dict)]
    found, res_ts, res_txt, nxt = 0, None, None, None
    for i, e in enumerate(ents):
        p = e.get("payload") if isinstance(e.get("payload"), dict) else {}
        pt = p.get("type")
        if e.get("type") == "response_item" and pt in ("function_call_output", "custom_tool_call_output",
                                                         "tool_search_output") and p.get("call_id") == call_id:
            found += 1
            if found == 1:
                res_ts = iso(e.get("timestamp"))
                res_txt = _codex_text(p.get("output") if pt != "tool_search_output" else p.get("tools"), pt)
                for e2 in ents[i + 1:]:
                    p2 = e2.get("payload") if isinstance(e2.get("payload"), dict) else {}
                    if e2.get("type") == "response_item" and (
                            p2.get("type") in ("function_call", "custom_tool_call", "tool_search_call")
                            or (p2.get("type") == "message" and p2.get("role") == "assistant")):
                        nxt = iso(e2.get("timestamp"))
                        break
    return found, res_ts, res_txt, nxt


def _text_of(content):
    """lib/cc_jsonl._text_of (copied so the raw side is read independently of the IR build)."""
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


def aiv_cc_raw_index(sdk_ids):
    """Light index of the raw aiv_cc rows (data/ai-village/claude_code_messages.jsonl.gz, read-only) of the given SDK
    sessions, sorted as the loader sorts them (created_at, init row first, row id): per row the stamp, whether the IR
    emits a model event for it (an assistant entry with a text or tool_use block; thinking-only entries are meta) and
    the UTF-8 bytes of each tool_result block by tool_use_id."""
    import gzip
    from analysis.lib.ir import iso
    src = "C:/Swarms/data/ai-village/claude_code_messages.jsonl.gz"
    OPENED.append(src + " (light index of the audited SDK sessions' rows)")
    rows = []
    with gzip.open(src, "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("sdk_session_id") not in sdk_ids:
                continue
            c = r.get("content")
            if isinstance(c, str):
                try:
                    c = json.loads(c)
                except ValueError:
                    c = {}
            c = c if isinstance(c, dict) else {}
            t = c.get("type")
            msg = c.get("message") if isinstance(c.get("message"), dict) else {}
            content = msg.get("content")
            model_ev, results = False, {}
            if t == "assistant":
                blocks = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
                model_ev = any(isinstance(b, dict) and b.get("type") in ("text", "tool_use", "server_tool_use")
                               for b in blocks)
            elif t == "user" and isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") not in results:
                        results[b.get("tool_use_id")] = len(_text_of(b.get("content")).encode("utf-8"))
            ts = iso(r.get("created_at"))
            init = t == "system" and c.get("subtype") == "init"
            rows.append((parse_ts(ts), 0 if init else 1, str(r.get("id")), ts, model_ev, results))
    rows.sort(key=lambda x: (x[0], x[1], x[2]))
    return rows


def ac1_aiv_cc(sub):
    recs = []
    idx = aiv_cc_raw_index({str(s).split("/")[0] for s in sub.session_id})
    where = {}
    for i, row in enumerate(idx):
        for cid in row[5]:
            where.setdefault(cid, i)
    for _, r in sub.iterrows():
        rec = {"n_results_in_batch": int(r.n_results)}
        why = []
        i = where.get(r.last_call_id)
        if i is None:
            why.append("not found")
        else:
            j = next((k for k in range(i + 1, len(idx)) if idx[k][4]), None)
            if j is None:
                why.append("not found")
            else:
                gap_raw = (idx[j][0] - idx[i][0]).total_seconds()
                rec["gap_ir_s"], rec["gap_raw_s"] = float(r.gap), float(gap_raw)
                if abs(gap_raw - r.gap) > 0.001:
                    why.append("gap")
                b = [idx[where[c]][5][c] if c in where else None for c in r.batch_call_ids]
                rec["bytes_ir"], rec["bytes_raw"] = int(r["bytes"]), (sum(b) if all(x is not None for x in b) else None)
                if rec["bytes_raw"] != rec["bytes_ir"]:
                    why.append("bytes")
        rec["differs"], rec["why"] = bool(why), why
        recs.append(rec)
    return recs


def ac1_codex(sub):
    OPENED.append(f"C:/Swarms/data/swe-chat-pinned/transcripts/<session_id>.jsonl ({sub.session_id.nunique()} audited "
                  "sessions)")
    recs = []
    for _, r in sub.iterrows():
        found, rts, rtxt, nts = raw_codex_lookup(r.session_id, r.last_call_id)
        rec = {"found": found, "n_results_in_batch": int(r.n_results)}
        why = []
        if not found or rts is None or nts is None:
            why.append("not found")
        else:
            gap_raw = (parse_ts(nts) - parse_ts(rts)).total_seconds()
            rec["gap_ir_s"], rec["gap_raw_s"] = float(r.gap), float(gap_raw)
            if abs(gap_raw - r.gap) > 0.001:
                why.append("gap")
            rec["bytes_ir"] = int(r["bytes"])
            rec["bytes_raw"] = (len((rtxt or "").encode("utf-8")) if int(r.n_results) == 1
                                else raw_codex_batch_bytes(r.session_id, set(r.batch_call_ids)))
            if rec["bytes_raw"] != rec["bytes_ir"]:
                why.append("bytes")
        rec["differs"], rec["why"] = bool(why), why
        recs.append(rec)
    return recs


AC1_IMPL = {"swechat/codex": ac1_codex, "aiv_cc": ac1_aiv_cc}


def ac1_audit(unit, G):
    """AC1: audit_sample() of 30 gaps of the pooled statistic (sessions with >= 20 gaps), each looked up in the raw
    source. Compared: the gap (last stamped result -> next model event, 1 ms tolerance) and the batch's UTF-8 bytes."""
    if unit not in AC1_IMPL:
        return {"label": "NOT_RUN", "reason": f"no raw lookup implemented for {unit}"}
    n_by = G.groupby("session_id").size()
    ge = G[G.session_id.isin(set(n_by[n_by >= MIN_GAPS].index))].sort_values(["session_id", "next_seq"])
    keys = list(zip(ge.session_id, ge.next_seq))
    pick = set(pe.audit_sample(keys, seed_parts=("N3", "AC1", unit)))
    sub = ge[[k in pick for k in keys]]
    recs = AC1_IMPL[unit](sub)
    nd = sum(1 for x in recs if x["differs"])
    return {"population": "gaps of sessions with >= 20 gaps (the pooled statistic's events)", "pool_size": len(keys),
            "audited": len(recs), "differing": nd, "differing_reasons": dict(Counter(w for x in recs for w in x["why"])),
            "label": "FAIL" if nd >= pe.AUDIT_FAIL else ("PARSER_NOTE" if nd == 1 else "PASS"),
            "rule": "FAIL if >= 2 of 30 differ in a way that changes their contribution; 1 = PARSER_NOTE",
            "seed_parts": ["N3", "AC1", unit], "events": recs}


# ================================================================================================== main
def main():
    store = defaultdict(dict)
    smeta = defaultdict(dict)
    n_sess_split = defaultdict(dict)
    copied = {}
    for corpus, unit, split, df, nss in frames():
        n_sess_split[unit][split] = nss
        if df is None:
            continue
        if corpus not in copied:
            copied[corpus] = copied_call_ids(corpus)
        print(f"[{time.time() - T0:7.1f}s] {unit} {split}: {len(df)} rows, {nss} sessions", flush=True)
        meta, G, sm = per_split(corpus, unit, split, df, copied[corpus])
        store[unit][split] = (meta, G)
        smeta[unit].update(sm)
        del df
        gc.collect()
    print(f"[{time.time() - T0:7.1f}s] statistics", flush=True)
    out = {"item": "n3_reaction_time", "script": "analysis/probes/phase_e_n3.py",
           "prereg_section": "prereg_e.json n3_reaction_time",
           "prereg_e_json_sha256": pe.sha256_file(pe.PREREG_E_JSON),
           "spec_module_sha256": PJ["provenance"]["spec_module_sha256"],
           "spec_module_sha256_lf": pe.sha256_lf(pe.ROOT / "analysis" / "probes" / "prereg_e_common.py"),
           "check_frozen": "passed", "verdict_rule_text": SPEC["verdict"], "min_n": SPEC["min_n"],
           "detector": SPEC["detector"], "gap_definition": SPEC["gap"], "stated_limit": STATED_LIMIT,
           "thresholds_used": {"min_gaps_per_session": MIN_GAPS, "min_sessions": MIN_SESS, "alive_rho_lo": ALIVE_LO,
                               "alive_share": SHARE_PT, "alive_share_hi": SHARE_HI, "G50_tok_per_s": G50},
           "seeds": {"bootstrap": pe.SEED, "positive_control": f"rng_for('N3pc', session_id, 'gaps') with SEED_E={pe.SEED_E}"},
           "A_context_sessions_ge_20_gaps": {u: CALJ["units"].get(u, {}).get("latency_counts", {}).get("n3") for u in UNITS},
           "A_context_source": "analysis/out/phase_e/prereg_e_calibration.json units.<unit>.latency_counts.n3",
           "cells_computed": 0, "units": {}}
    n_cells = 0
    for unit in UNITS:
        U = {"labels": LABELS.get(unit, []), "sessions_in_split": n_sess_split.get(unit, {}),
             "has_E": CORPUS_OF[unit] in pe.CORPORA_WITH_E}
        splits = [s for s in ("B", "E") if s in store[unit]]
        pops = {s: store[unit][s][1] for s in splits}
        if len(splits) == 2:
            pops["BE"] = pd.concat([pops["B"], pops["E"]], ignore_index=True)
        U["split_meta"] = {s: store[unit][s][0] for s in splits}
        U["results"] = {}
        for s, G in pops.items():
            print(f"[{time.time() - T0:7.1f}s] {unit} {s}: block", flush=True)
            U["results"][s] = block(G, unit, f"units.{unit}.results.{s}")
            n_cells += 1
        lb = U["results"].get("B", {}).get("verdict", {}).get("label")
        le = U["results"].get("E", {}).get("verdict", {}).get("label")
        if le is not None and le != "INSUFFICIENT_N":
            cell, src = le, f"units.{unit}.results.E.verdict.label"
        else:
            cell, src = lb, f"units.{unit}.results.B.verdict.label"
        U["cell_before_checks"] = {"label": cell, "source_path": src, "B": lb, "E": le,
                                   "suffix": "" if (le is not None and le != "INSUFFICIENT_N") else
                                   (" (B only, unreplicated)" if not U["has_E"] else
                                    " (B only; E INSUFFICIENT_N: NOT_REPLICABLE_AT_N)")}
        any_weak = any(U["results"][s]["verdict"]["label"] in ("ALIVE", "WEAK") for s in U["results"])
        final, checks = cell, []
        if any_weak:
            ACp = "BE" if "BE" in pops else splits[0]
            Gb = pops[ACp]
            base = U["results"][ACp]["verdict"]["label"]
            ac = {"population": "B u E" if ACp == "BE" else "B", "base_label": base}
            for name, mask in (("AC2_no_truncated", ~Gb.trunc), ("AC3_join_clean", Gb.join_clean)):
                print(f"[{time.time() - T0:7.1f}s] {unit} {name}", flush=True)
                b = block(Gb[mask.to_numpy()], unit, f"units.{unit}.artifact_checks.{name}", full=False)
                lab = b["verdict"]["label"]
                ac[name] = {"gaps_dropped": int((~mask).sum()), **short(b), "fail": lab != base, "verdict": b["verdict"]}
                if lab != base:
                    final = lower(final, lab) if lab in LVL else final
                    checks.append({"name": name, "effect": "lower label to " + str(lab)})
            print(f"[{time.time() - T0:7.1f}s] {unit} AC4", flush=True)
            ac["AC4_dominance"] = dominance_check(Gb, unit, base, smeta[unit])
            if ac["AC4_dominance"]["effect"] == "downgrade":
                final = pe.downgrade(final)
                checks.append({"name": "AC4 DOMINATED", "effect": "downgrade"})
            elif ac["AC4_dominance"]["effect"] == "cap_weak" and final == "ALIVE":
                final = "WEAK"
                checks.append({"name": "AC4 UNTESTABLE_WITHOUT_DOMINANT", "effect": "cap_weak"})
            if CORPUS_OF[unit] in ("swechat", "aiv_cu"):
                n_by = Gb.groupby("session_id").size()
                es = sorted(n_by[n_by >= MIN_GAPS].index)
                wts = pe.post_strat_weights(CORPUS_OF[unit], es)
                b = block(Gb, unit, f"units.{unit}.artifact_checks.AC5_post_stratified", w=wts, full=False)
                lab = b["verdict"]["label"]
                ac["AC5_post_stratified"] = {**short(b), "fail": lab != base, "verdict": b["verdict"],
                                             "weights": "population cell size / analysed sessions in the cell "
                                                        "(post_strat_weights over sessions with >= 20 gaps)"}
                if lab != base:
                    final = lower(final, lab) if lab in LVL else final
                    checks.append({"name": "AC5", "effect": "lower label to " + str(lab)})
                if "B" in U["results"] and "E" in U["results"]:
                    bp = U["results"]["B"]["rho_pooled"].get("value")
                    e = U["results"]["E"]["rho_pooled"]
                    ac["AC5_shift_rho_pooled"] = {"B_point": bp, "E_ci": [e.get("lo"), e.get("hi")],
                                                  "SHIFT": bool(bp is not None and e.get("lo") is not None
                                                                and not (e["lo"] <= bp <= e["hi"])),
                                                  "note": "reported, no verdict effect"}
            else:
                ac["AC5_post_stratified"] = {"label": "NOT_RUN", "reason": "no population table for this corpus"}
            if U["cell_before_checks"]["label"] in ("ALIVE", "WEAK"):
                print(f"[{time.time() - T0:7.1f}s] {unit} AC1", flush=True)
                ac["AC1_parser"] = ac1_audit(unit, Gb)
                if ac["AC1_parser"].get("label") == "FAIL":
                    final = pe.downgrade(final)
                    checks.append({"name": "AC1 FAIL", "effect": "downgrade"})
            else:
                ac["AC1_parser"] = {"label": "NOT_RUN", "reason": "the unit's N6 cell is not WEAK or better (cell "
                                    f"{U['cell_before_checks']['label']}); AC1 is required for N cells at WEAK or better"}
            U["artifact_checks"] = ac
            print(f"[{time.time() - T0:7.1f}s] {unit} strata", flush=True)
            st = strata_check(Gb, unit, smeta[unit])
            U["stratification"] = st
            if st["CONFINED_any_axis"] and final in LVL:
                final = pe.downgrade(final)
                checks.append({"name": "CONFINED", "effect": "downgrade"})
        else:
            U["artifact_checks"] = {"status": "not required: no B / E / B u E verdict reached WEAK or better "
                                              "(S:artifact_checks applies to N cells at WEAK or better)"}
        U["cell_final"] = {"label": final, "checks_applied": checks,
                           "suffix": U["cell_before_checks"]["suffix"] + "".join(f" [{x}]" for x in U["labels"])}
        out["units"][unit] = U
    for u_, why in OTHER_UNITS.items():
        out["units"][u_] = {"cell_final": {"label": f"NOT_TESTABLE({why})"},
                            "sessions_in_split": n_sess_split.get(u_, {})}
    for u_, why in SPEC["not_testable"].items():
        out["units"][u_] = {"cell_final": {"label": f"NOT_TESTABLE({why})"}}
    out["cells_computed"] = n_cells
    out["deviations"] = DEVIATIONS
    summ = {}
    for unit in UNITS:
        U = out["units"][unit]
        row = {"cell": U["cell_final"]["label"], "cell_before_checks": U["cell_before_checks"]["label"],
               "suffix": U["cell_final"]["suffix"]}
        for sp, b in U["results"].items():
            row[sp] = {**short(b), "rule": b["verdict"]["rule"],
                       "recall_permutation": b["positive_control_permutation"]["recall"]["share"],
                       "rho_secondary_usage_adjusted": b["secondary_usage_adjusted"]["rho"].get("value"),
                       "path": f"units.{unit}.results.{sp}"}
        summ[unit] = row
    out["summary_raw"] = summ
    out["opened_files"] = sorted(set(OPENED)) + ["analysis/prereg.json", "analysis/out/phase_e/prereg_e_calibration.json",
                                                 "C:/Swarms/data/swe-chat-pinned/sessions.parquet (metadata: repo_id, user_id)"]
    out["runtime_s"] = round(time.time() - T0, 1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)),
                   encoding="utf-8")
    print(f"[{time.time() - T0:7.1f}s] wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
