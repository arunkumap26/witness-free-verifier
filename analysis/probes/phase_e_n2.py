"""Phase E, Track A, item N2: token accounting as a direct discriminator (prereg_e.json S:n2_token_accounting).

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_n2

What it does, in the order the pre-registration fixes:
  1. check_frozen() (prereg_e_common.py must be the pre-registered module).
  2. GRANULARITY FIRST, per unit x split (B; E where the corpus has one): response_table() + granularity() re-check of
     the A result (resolved.n2). A unit (aiv_cu: a model stratum) that is not GRANULAR is DEAD ("per-turn input/output
     counts absent"); nothing else is computed for it.
  3. For the GRANULAR units / strata: U_k = usage_out_k - tau x chars_out_k (tau from A, resolved.n2), the detector
     (last call's result >= 800 chars and U_k >= 0.5 tau chars(result), prereg_e_common.n2_flags), the honest flag rate
     (response level, session-clustered CI), the synthetic inline-fabrication positive control
     (usage_out += tau' x chars(result), tau' in {tau, 0.8 tau}, atk_inline_fabrication) and the verdict.
  4. For any unit / stratum whose B, E or B u E verdict reaches WEAK or better: AC2-AC5 and the four stratification
     axes on B u E (B for units without E); AC1 when the N6 cell itself is WEAK or better.
Reads: analysis/cache/{swechat,cc_local,aiv_cc,aiv_cu,whowhen}_{B,E}.parquet through prereg_e_common.read_cache (never
       A, never H), swechat_population.parquet, aiv_cu_sessions.parquet and swe-chat-pinned sessions.parquet (metadata
       only, through prereg_e_common helpers). AC1 only: the raw sources of the audited sessions (read-only).
Writes: analysis/out/phase_e/n2.json (raw numbers only). Interpretation: analysis/notes/phase_e_n2_n3.md.
cc_local: aggregates only (no text, command, path, session id or project name is written). aiv_cc: single-agent case
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
from analysis.probes import prereg_common as pc
from analysis.probes import prereg_e_common as pe
from analysis.probes import prereg_e_calibration as pecal  # COLS: the column set the A calibration read

T0 = time.time()
PJ = pe.check_frozen()
SPEC = PJ["n2_token_accounting"]
RES = PJ["resolved"]["n2"]
TERC = PJ["resolved"]["length_terciles_A"]
OUT = pe.OUT_E / "n2.json"

UNITS = ["swechat/claude_code", "swechat/codex", "swechat/opencode", "swechat/gemini", "swechat/copilot",
         "swechat/cursor", "swechat/simple_text", "cc_local", "aiv_cc", "aiv_cu", "whowhen"]  # the 11 N6 columns
CORPUS_OF = {u: ("swechat" if u.startswith("swechat/") else u) for u in UNITS}
RC_MIN = 800              # S:n2_token_accounting.detector: last call's result >= 800 chars
U_FRAC = 0.5              # U_k >= 0.5 tau chars(result)
TAU_PRIME = (1.0, 0.8)    # S:n2_token_accounting.positive_control
FLAG_PT, FLAG_HI, WEAK_FLAG = 0.05, 0.10, 0.20
REC_ALIVE, REC_WEAK = 0.90, 0.50
MIN_RESP, MIN_SESS = 100, 10
LABELS = {
    "cc_local": ["private: aggregates only", "B only, unreplicated (no E split)",
                 "high tau (0.772): hidden output expected as an honest false-positive source (prereg)"],
    "aiv_cc": ["single-agent case study", "B only, unreplicated (no E split)"],
    "whowhen": ["B only, unreplicated (no E split)"],
}
OPENED = []

# ================================================================================================== deviations / choices
DEVIATIONS = [
    {"item": "output file names",
     "prereg_said": "prereg_e.json outputs: 'N1-N5': phase_e_n<k>.py -> n<k>.json",
     "what_you_did": "followed the pre-registration: analysis/probes/phase_e_n2.py -> analysis/out/phase_e/n2.json (and "
                     "phase_e_n3.py -> n3.json); the orchestrator's item key 'n2_n3' names the joint notes file "
                     "analysis/notes/phase_e_n2_n3.md",
     "why": "the pre-registration is the output contract", "effect_on_verdict": "none"},
    {"item": "granularity re-check on B / E",
     "prereg_said": "GRANULAR computed on A (resolved.n2) and re-checked on B and E; not GRANULAR => DEAD",
     "what_you_did": "a unit (aiv_cu: stratum) is DEAD on a split if it is not GRANULAR on A (no A tau exists) or not "
                     "GRANULAR on that split. Every unit's B / E granularity is reported, including the units that "
                     "were not GRANULAR on A",
     "why": "the detector needs the A tau; a split that fails the re-check has no per-turn counts to test",
     "effect_on_verdict": "see granularity blocks"},
    {"item": "which recall the WEAK rule uses",
     "prereg_said": "ALIVE: honest flag rate <= 0.05 (CI hi <= 0.10) and recall >= 0.90 at 0.8 tau; WEAK: honest flag "
                    "rate <= 0.20 and recall >= 0.50",
     "what_you_did": "WEAK uses recall at tau' = 0.8 tau as ALIVE does. Recall at tau' = tau is reported and can only be "
                     ">= the 0.8 tau recall (the injection is larger), so this is the stricter reading",
     "why": "the WEAK clause does not name tau'", "effect_on_verdict": "none unless recall(0.8 tau) < 0.50 <= recall(tau)"},
    {"item": "positive control scope",
     "prereg_said": "synthetic inline fabrication: usage_out_k += tau' x chars(result); recall = flagged share",
     "what_you_did": "every eligible response (its last call's result >= 800 chars, usage_out present) is tampered "
                     "once, independently, with atk_inline_fabrication(row, chars(result), tau'); recall = flagged share "
                     "of tampered responses with a session-clustered CI. No random draw is involved, so no seed is used",
     "why": "the injection is deterministic and per response", "effect_on_verdict": "none"},
    {"item": "zero-numerator rule and CI method",
     "prereg_said": "rates: cluster_rate; zero numerators: verdicts use the per-event Wilson upper bound",
     "what_you_did": "honest flag rate and recall = prereg_e_common.rate_by_session (cluster_rate over sessions); when "
                     "the honest numerator is 0 the verdict's CI hi is the per-event Wilson hi",
     "why": "as written", "effect_on_verdict": "none"},
    {"item": "verdict rule gaps",
     "prereg_said": "ALIVE / WEAK / DEAD rules of S:n2_token_accounting.verdict; min n >= 100 eligible responses from "
                    ">= 10 sessions",
     "what_you_did": "INSUFFICIENT_N below the min n (a GRANULAR unit only); DEAD for a unit that is not GRANULAR. "
                     "aiv_cu strata absent from A have no A tau: NOT_TESTABLE",
     "why": "the rules presuppose the min n", "effect_on_verdict": "see results"},
    {"item": "B u E pooled verdicts and when the artifact checks run",
     "prereg_said": "N6 fill rule: E verdict where E exists and is not INSUFFICIENT_N, else B ('B only'); artifact checks "
                    "on B u E for N cells at WEAK or better",
     "what_you_did": "B, E and B u E are computed; AC2-AC5 and the strata run on B u E (B for units without E) whenever "
                     "B, E or B u E reaches WEAK or better (the N1 script's practice); AC1 when the cell itself is WEAK "
                     "or better. The pooled label is never the cell",
     "why": "smallest faithful reading; reporting more cannot raise a cell", "effect_on_verdict": "none on the cells"},
    {"item": "artifact-check event definitions for a response",
     "prereg_said": "AC2: drop events whose result matches truncated_result(); AC3: join_clean_mask() pairs; AC4: "
                    "denominator events; strata: tool_key, model, repo, length tercile",
     "what_you_did": "the N2 event is an eligible response. AC2 drops it if its last call's result is "
                     "truncated_result(text, extra); AC3 keeps it only if its last call's (call, result) pair passes "
                     "join_clean_mask() (copied call ids over the corpus's B and E caches); AC4 denominator = eligible "
                     "responses per session (aiv_cu repo cluster = agent_id; cc_local = project alias, never written); "
                     "AC5 = weighted_cluster_rate for the flag rate and the recalls (bootstrap hi replaces the CI hi; "
                     "the per-event Wilson hi when the numerator is 0); strata: tool_key of the last call (cc_local "
                     "through private_key), modal model, repo cluster, A length tercile of paired calls; reportable at "
                     ">= 100 eligible responses from >= 10 sessions",
     "why": "smallest faithful reading", "effect_on_verdict": "see artifact_checks"},
    {"item": "thinking characters inside chars_out (observation, not a change)",
     "prereg_said": "chars_out = assistant text + call args + extra.thinking_chars of response k (response_table)",
     "what_you_did": "response_table() was used unchanged. In Claude Code format the IR writes a thinking block's "
                     "characters twice (on the thinking-only meta event and again on the next assistant/call event of "
                     "the same api_msg_id), and response_table() sums both. The A-split tau was computed with the same "
                     "function, so the detector is internally consistent; the thinking share is reported per block "
                     "(thinking_diagnostic) so the reader can see how much of chars_out it is",
     "why": "the frozen function is the definition; editing it is not allowed", "effect_on_verdict": "none (as frozen)"},
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
        for f in ("claude_code", "codex", "opencode", "gemini", "copilot", "cursor", "simple_text"):
            ids = by.get(f, [])
            if not ids:
                yield "swechat", f"swechat/{f}", split, None, 0
                continue
            df = pe.read_cache("swechat", split, pecal.COLS, filters=[("session_id", "in", ids)])
            yield "swechat", f"swechat/{f}", split, df, len(ids)
    for c in ("cc_local", "aiv_cc", "whowhen"):
        OPENED.append(f"analysis/cache/{c}_B.parquet")
        df = pe.read_cache(c, "B", pecal.COLS)
        yield c, c, "B", df, int(df.session_id.nunique())
    for split in ("B", "E"):
        OPENED.append(f"analysis/cache/aiv_cu_{split}.parquet")
        df = pe.read_cache("aiv_cu", split, pecal.COLS)
        yield "aiv_cu", "aiv_cu", split, df, int(df.session_id.nunique())


def copied_call_ids(corpus):
    parts = []
    for split in (("B", "E") if corpus in pe.CORPORA_WITH_E else ("B",)):
        d = pe.read_cache(corpus, split, ["session_id", "kind", "call_id"], filters=[("kind", "==", "call")])
        parts.append(d[d.call_id.notna()][["session_id", "call_id"]].drop_duplicates())
    d = pd.concat(parts, ignore_index=True)
    n = d.groupby("call_id").session_id.nunique()
    return frozenset(str(x) for x in n[n > 1].index)


def _lab(x):
    if x is None or x is pd.NA or (isinstance(x, float) and math.isnan(x)):
        return "nan"
    return str(x)


def _thinking_by_resp(u):
    """Sum of extra.thinking_chars per (session, api_msg_id) over every row (response_table's thinking component)."""
    m = u[u.api_msg_id.notna() & u.extra.astype(object).map(lambda e: isinstance(e, str) and "thinking_chars" in e)]
    out = defaultdict(int)
    for s, a, e in zip(m.session_id, m.api_msg_id.astype(str), m.extra.astype(object)):
        v = pc.jl(e).get("thinking_chars")
        if isinstance(v, (int, float)):
            out[(s, a)] += int(v)
    return out


def per_split(corpus, unit, split, u, copied):
    """Response table with the per-response attributes the statistic and the checks need."""
    u = u.reset_index(drop=True)
    t = time.time()
    resp = pe.response_table(unit, u)
    t_resp = time.time() - t
    gran = pe.granularity(resp)
    st = u.groupby("session_id").stratum.first()
    meta = {"rows": int(len(u)), "sessions": int(u.session_id.nunique()), "responses_with_calls": int(len(resp)),
            "response_table_s": round(t_resp, 1), "granularity": gran}
    if corpus == "aiv_cu" and len(resp):
        resp = resp.assign(_st=resp.session_id.map(st).astype(str))
        meta["granularity_by_stratum"] = {s: pe.granularity(g) for s, g in resp.groupby("_st")}
        meta["sessions_by_stratum"] = {str(k): int(v) for k, v in st.astype(str).value_counts().items()}
    if not len(resp):
        return meta, resp, {}
    P = pc.make_pairs(u[u.kind.isin(["call", "result"])])
    cids = P.call_id.astype(str).to_numpy()
    txt = P.text_r.astype(object).to_numpy()
    rc = {(s, c): len(x) for s, c, x in zip(P.session_id, cids, txt) if isinstance(x, str)}
    jc = pe.join_clean_mask(u, P, copied)
    clean = set(zip(P.session_id.to_numpy()[jc], cids[jc]))
    big = np.array([isinstance(x, str) and len(x) >= RC_MIN for x in txt])
    trunc = {(s, c): pe.truncated_result(x, e) for s, c, x, e, b in
             zip(P.session_id, cids, txt, P.extra_r.astype(object), big) if b}
    keys = {}
    for s, c, tl, tr in zip(P.session_id, cids, P.tool.astype(object), P.tool_raw.astype(object)):
        k = pc.tool_key(unit, tl if isinstance(tl, str) else None, tr if isinstance(tr, str) else None)
        keys[(s, c)] = pc.private_key(k) if unit == "cc_local" else k
    resp = resp.assign(last_call_id=resp.last_call_id.astype(str))
    kk = list(zip(resp.session_id, resp.last_call_id))
    resp["rc"] = [rc.get(k, np.nan) for k in kk]
    resp["trunc"] = [bool(trunc.get(k, False)) for k in kk]
    resp["join_clean"] = [k in clean for k in kk]
    resp["key"] = [keys.get(k, "unknown") for k in kk]
    if unit != "swechat/codex":
        th = _thinking_by_resp(u)
        resp["thinking_chars"] = [th.get((s, r), 0) for s, r in zip(resp.session_id, resp.resp)]
    else:
        resp["thinking_chars"] = 0
    resp["split"] = split
    if "_st" not in resp:
        resp["_st"] = resp.session_id.map(st).astype(str)
    model = pe.session_model_map(u)
    repo = pe.session_cluster_map(corpus, u, kind="repo")
    user = pe.session_cluster_map(corpus, u, kind="user") if corpus == "swechat" else {}
    n_pairs = P.groupby("session_id").size().to_dict()
    terc = pe.length_tercile_map(n_pairs, TERC[unit]["cuts"]) if unit in TERC and TERC[unit].get("cuts") else {}
    sm = {s: {"model": _lab(model.get(s, "unknown")), "repo": _lab(repo.get(s, "unknown")),
              "user": _lab(user.get(s, "n/a")), "length_tercile": terc.get(s, "short"), "split": split}
          for s in set(u.session_id.unique())}
    meta["pairs"] = int(len(P))
    return meta, resp, sm


# ================================================================================================== statistics
def qtiles(v):
    v = np.asarray(v, float)
    v = v[np.isfinite(v)]
    out = {"n": int(len(v))}
    if len(v):
        for qq in (0.0, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 1.0):
            out[f"q{qq:g}"] = float(np.quantile(v, qq))
    return out


def eligible(resp, tau):
    """Eligible responses with honest and tampered flags, all through prereg_e_common.n2_flags."""
    rcm = {(s, c): v for s, c, v in zip(resp.session_id, resp.last_call_id, resp.rc) if np.isfinite(v)}
    base = pe.n2_flags(resp, rcm, tau)
    E = pd.DataFrame(base, columns=["session_id", "resp", "flag"])
    if not len(E):
        return E
    R = resp.set_index(["session_id", "resp"])
    idx = pd.MultiIndex.from_arrays([E.session_id, E.resp])
    for c in ("usage_out", "chars_out", "rc", "trunc", "join_clean", "key", "thinking_chars", "split", "_st",
              "last_call_id"):
        E[c] = R[c].reindex(idx).to_numpy()
    E["U"] = E.usage_out - tau * E.chars_out
    for tp in TAU_PRIME:
        extra = {(s, r): pe.atk_inline_fabrication(None, rc_, tp * tau) for s, r, rc_ in zip(E.session_id, E.resp, E.rc)}
        f = pe.n2_flags(resp[[(s, r) in extra for s, r in zip(resp.session_id, resp.resp)]], rcm, tau, extra_out=extra)
        fm = {(s, r): v for s, r, v in f}
        E[f"flag_pc_{tp:g}"] = [fm[(s, r)] for s, r in zip(E.session_id, E.resp)]
    return E


def rate(flags, sids, w=None):
    flags, sids = np.asarray(flags, bool), np.asarray(sids)
    if not len(flags):
        return {"rate": None, "num": 0, "den": 0, "n_sessions": 0}
    if w is None:
        return pe.rate_by_session(flags, sids)
    num = pd.Series(flags.astype(float)).groupby(sids).sum()
    den = pd.Series(np.ones(len(flags))).groupby(sids).sum()
    r = pe.weighted_cluster_rate(num.to_numpy(), den.to_numpy(), [w.get(s, 0.0) for s in num.index])
    r["num"], r["den"] = float(num.sum()), float(den.sum())
    if r["num"] == 0:
        r["wilson_hi_per_event"] = stats.wilson(0, int(r["den"]))[2]
    return r


def block(E, tau, path, granular=True, gran_note=None, w=None, full=True):
    if not granular:
        return {"verdict": {"label": "DEAD", "rule": "not GRANULAR: per-turn input/output counts absent",
                            "deciding_number": gran_note, "deciding_path": f"{path}.granularity"}}
    e = E if len(E) else pd.DataFrame(columns=["session_id", "flag", "flag_pc_1", "flag_pc_0.8", "U", "rc"])
    out = {"tau_A": tau, "eligible_responses": int(len(e)), "eligible_sessions": int(e.session_id.nunique())}
    out["honest_flag_rate"] = rate(e.flag, e.session_id, w)
    for tp in TAU_PRIME:
        out[f"recall_tau_prime_{tp:g}"] = rate(e[f"flag_pc_{tp:g}"], e.session_id, w)
    if full and len(e):
        z = (e.U / (tau * e.rc)).to_numpy(float)
        out["U_tokens_quantiles"] = qtiles(e.U)
        out["U_over_tau_rc_quantiles"] = qtiles(z)
        out["result_chars_quantiles"] = qtiles(e.rc)
        fs = e.groupby("session_id").flag.any()
        p, lo, hi = stats.wilson(int(fs.sum()), int(len(fs)))
        out["session_level_honest_flag_share"] = {"k": int(fs.sum()), "n": int(len(fs)), "share": p, "lo": lo, "hi": hi,
                                                  "note": "context: a session counts as flagged if >= 1 response is "
                                                          "(N7 session aggregation); not the verdict number"}
        th = e.thinking_chars.astype(float)
        out["thinking_diagnostic"] = {"responses_with_thinking_chars": int((th > 0).sum()),
                                      "thinking_share_of_chars_out_quantiles": qtiles(th / e.chars_out.astype(float))}
        out["flagged_by_last_call_key"] = {str(k): int(v) for k, v in e[e.flag.astype(bool)].key.value_counts().head(10).items()}
    out["verdict"] = verdict(out, path, w is not None)
    return out


def verdict(b, path, weighted=False):
    n, ns = b["eligible_responses"], b["eligible_sessions"]
    if n < MIN_RESP or ns < MIN_SESS:
        return {"label": "INSUFFICIENT_N", "rule": f"min n: >= {MIN_RESP} eligible responses from >= {MIN_SESS} sessions",
                "deciding_number": {"responses": n, "sessions": ns},
                "deciding_path": [f"{path}.eligible_responses", f"{path}.eligible_sessions"]}
    fr = b["honest_flag_rate"]
    r08 = b["recall_tau_prime_0.8"].get("rate")
    hi = fr.get("wilson_hi_per_event") if fr.get("num", 0) == 0 else fr.get("hi")
    hi_path = f"{path}.honest_flag_rate." + ("wilson_hi_per_event" if fr.get("num", 0) == 0 else "hi")
    conds = [("honest flag rate <= 0.05", fr["rate"] <= FLAG_PT, fr["rate"], f"{path}.honest_flag_rate.rate"),
             ("honest flag rate CI hi <= 0.10", hi is not None and hi <= FLAG_HI, hi, hi_path),
             ("recall at 0.8 tau >= 0.90", r08 is not None and r08 >= REC_ALIVE, r08, f"{path}.recall_tau_prime_0.8.rate")]
    rec = [{"condition": c[0], "met": bool(c[1]), "value": c[2], "path": c[3]} for c in conds]
    if all(c[1] for c in conds):
        return {"label": "ALIVE", "rule": "every ALIVE condition met", "conditions": rec,
                "deciding_number": {"flag_rate": fr["rate"], "flag_hi": hi, "recall_0.8tau": r08},
                "deciding_path": [c[3] for c in conds]}
    if fr["rate"] <= WEAK_FLAG and r08 is not None and r08 >= REC_WEAK:
        failing = [c for c in conds if not c[1]]
        return {"label": "WEAK", "rule": "honest flag rate <= 0.20 and recall(0.8 tau) >= 0.50; ALIVE condition(s) "
                                         "failing: " + "; ".join(c[0] for c in failing), "conditions": rec,
                "deciding_number": {c[0]: c[2] for c in failing}, "deciding_path": [c[3] for c in failing]}
    why = []
    if fr["rate"] > WEAK_FLAG:
        why.append(("honest flag rate > 0.20", fr["rate"], f"{path}.honest_flag_rate.rate"))
    if r08 is None or r08 < REC_WEAK:
        why.append(("recall at 0.8 tau < 0.50", r08, f"{path}.recall_tau_prime_0.8.rate"))
    return {"label": "DEAD", "rule": "; ".join(x[0] for x in why), "conditions": rec,
            "deciding_number": {x[0]: x[1] for x in why}, "deciding_path": [x[2] for x in why]}


LVL = {"ALIVE": 2, "WEAK": 1, "DEAD": 0}


def lower(a, b):
    if a in LVL and b in LVL:
        return a if LVL[a] <= LVL[b] else b
    return a


def short(b):
    fr = b.get("honest_flag_rate", {})
    return {"label": b["verdict"]["label"], "eligible_responses": b.get("eligible_responses"),
            "eligible_sessions": b.get("eligible_sessions"),
            "flag_rate": [fr.get("rate"), fr.get("lo"), fr.get("hi")], "flag_num": fr.get("num"),
            "recall_0.8tau": b.get("recall_tau_prime_0.8", {}).get("rate"),
            "recall_tau": b.get("recall_tau_prime_1", {}).get("rate")}


# ================================================================================================== artifact checks
def dominance_check(E, tau, unit, base, sm):
    w = E.groupby("session_id").size().to_dict()
    all_s = set(E.session_id)
    kinds = ["repo", "user", "model"] if CORPUS_OF[unit] == "swechat" else ["repo", "model"]
    out = {"denominator": "eligible responses per session", "kinds": {}}
    leaveouts, dominated = [], False
    for kind in kinds:
        cmap = {s: sm[s][kind] for s in w}
        d = pe.dominance(w, cmap)
        rec = {k: d.get(k) for k in ("top_cluster", "top_share_events", "top_share_sessions", "n_clusters", "dominated")}
        rec["top5"] = [[c if unit != "cc_local" else f"cluster_{i}", a, b] for i, (c, a, b) in
                       enumerate(d.get("top_clusters", []))]
        if unit == "cc_local":
            rec["top_cluster"] = "cluster_0"
        cdom = max(d.get("top_share_events", 0) or 0, d.get("top_share_sessions", 0) or 0) > pe.DOM_SHARE
        rec["cluster_dominated"] = bool(cdom)
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
        b = block(E[E.session_id.isin(keep)], tau, "artifact_checks.AC4_dominance.leaveouts", full=False)
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


def strata_check(E, tau, unit, sm):
    out = {}
    for axis in ("tool_key", "model", "repo", "length_tercile"):
        labels, rec = {}, {}
        if axis == "tool_key":
            groups = {k: E[E.key == k] for k in sorted(E.key.astype(str).unique())}
        else:
            vals = defaultdict(set)
            for s in set(E.session_id):
                vals[sm[s][axis]].add(s)
            groups = {v: E[E.session_id.isin(ss)] for v, ss in vals.items()}
        for i, (k, g) in enumerate(sorted(groups.items(), key=lambda kv: -len(kv[1]))):
            b = block(g, tau, f"stratification.{axis}", full=False)
            name = k if unit != "cc_local" or axis in ("tool_key", "length_tercile") else f"{axis}_{i}"
            rec[name] = short(b)
            labels[name] = b["verdict"]["label"] if b["verdict"]["label"] in LVL else None
        out[axis] = {"strata": rec, "confinement": pe.confinement(labels)}
    out["CONFINED_any_axis"] = any(v["confinement"] == "CONFINED" for v in out.values() if isinstance(v, dict))
    return out


AC1_IMPL = {}  # unit -> callable(E_flagged_sample, tau) -> list of records; filled below where a raw lookup exists


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


def _cc_scan(e, msgs, calls, acc, res, seen):
    """Raw Claude Code entry -> per-message usage / visible chars / thinking chars / tool_use ids, and tool_result text
    for target call ids (agent_progress unwrapped, duplicate uuids skipped: the IR parser's rules)."""
    from analysis.lib.ir import j
    if not isinstance(e, dict):
        return
    uid = e.get("uuid")
    if uid:
        if uid in seen:
            return
        seen.add(uid)
    t = e.get("type")
    if t == "progress":
        d = e.get("data") if isinstance(e.get("data"), dict) else {}
        if d.get("type") == "agent_progress" and isinstance(d.get("message"), dict):
            _cc_scan(d["message"], msgs, calls, acc, res, seen)
        return
    msg = e.get("message") if isinstance(e.get("message"), dict) else {}
    content = msg.get("content")
    if t == "assistant" and msg.get("id") in msgs:
        a = acc[msg["id"]]
        a["entries"] += 1
        u = msg.get("usage") if isinstance(msg.get("usage"), dict) else {}
        if isinstance(u.get("output_tokens"), (int, float)):
            a["usage_out"] = max(a["usage_out"] or 0, u["output_tokens"])
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
        for b in blocks:
            if not isinstance(b, dict):
                continue
            bt = b.get("type")
            if bt in ("thinking", "redacted_thinking"):
                a["thinking"] += len(b.get("thinking") or "")
            elif bt == "text":
                a["visible"] += len(b.get("text") or "")
            elif bt in ("tool_use", "server_tool_use"):
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                a["visible"] += len(j(inp))
                a["tool_ids"].append(b.get("id"))
    elif t == "user" and isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in calls:
                res[b["tool_use_id"]].append(len(_text_of(b.get("content"))))


def ac1_cc_swechat(sub, tau):
    """swechat/claude_code: each audited response is looked up in its raw transcript by api_msg_id; the flag is
    recomputed from raw usage_out, raw text + args + thinking chars (thinking counted once) and the raw result length of
    the response's last tool_use."""
    OPENED.append(f"C:/Swarms/data/swe-chat-pinned/transcripts/<session_id>.jsonl ({sub.session_id.nunique()} audited "
                  "sessions)")

    def entries(sid):
        b = (pe.SWE_TRANSCRIPTS / f"{sid}.jsonl").read_bytes()
        try:
            text = b.decode("utf-8")
        except UnicodeDecodeError:
            text = b.decode("utf-8", errors="replace")
        return list(_iter_lines(text))
    return ac1_cc_entries(sub, tau, entries)


def ac1_cc_local(sub, tau):
    """cc_local (PRIVATE; in-process, only match counts are written): the frozen snapshot data/claude-code-local (the
    loader's ROOT) is searched for the audited responses' message ids; only the files that hold one are parsed (a
    session family's root file, its subagent files or a fork member's file), with the same entry rules as swechat."""
    import glob
    root = "C:/Swarms/data/claude-code-local"
    OPENED.append("C:/Swarms/data/claude-code-local/**/*.jsonl (substring search for the audited message ids; only the "
                  "files holding one were parsed)")
    msg_sid = {str(r_): s_ for s_, r_ in zip(sub.session_id, sub.resp)}
    hold = defaultdict(set)
    for fp in sorted(glob.glob(f"{root}/**/*.jsonl", recursive=True)):
        with open(fp, encoding="utf-8", errors="replace") as fh:
            data = fh.read()
        for t, s_ in msg_sid.items():
            if t in data:
                hold[s_].add(fp)
        del data

    def entries(sid):
        out = []
        for fp in sorted(hold.get(sid, ())):
            with open(fp, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
        return out
    return ac1_cc_entries(sub, tau, entries)


def ac1_cc_entries(sub, tau, entries):
    recs = []
    for sid, g in sub.groupby("session_id"):
        msgs = set(g.resp.astype(str))
        ents = entries(sid)
        acc = defaultdict(lambda: {"entries": 0, "usage_out": None, "visible": 0, "thinking": 0, "tool_ids": []})
        seen = set()
        for ent in ents:
            _cc_scan(ent, msgs, set(), acc, defaultdict(list), seen)
        last_ids = {m: (acc[m]["tool_ids"][-1] if acc[m]["tool_ids"] else None) for m in msgs}
        res = defaultdict(list)
        seen = set()
        for ent in ents:
            _cc_scan(ent, set(), set(x for x in last_ids.values() if x), defaultdict(lambda: {"entries": 0}), res, seen)
        for _, r in g.iterrows():
            a = acc.get(r.resp, {"entries": 0})
            rec = {"found_entries": a["entries"]}
            why = []
            if not a["entries"]:
                why.append("response not found")
            else:
                lid = last_ids.get(r.resp)
                rcr = res.get(lid, [None])[0] if lid else None
                uo, vis, th = a["usage_out"], a["visible"], a["thinking"]
                rec.update({"usage_out_equal": uo == r.usage_out,
                            "visible_chars_equal": vis == (r.chars_out - r.thinking_chars),
                            "thinking_ir_over_raw": (r.thinking_chars / th) if th else None,
                            "last_call_id_equal": lid == r.last_call_id, "result_chars_equal": rcr == r.rc})
                if uo is None or rcr is None:
                    why.append("usage or result missing in raw")
                else:
                    flag_raw = rcr >= RC_MIN and (uo - tau * (vis + th)) >= U_FRAC * tau * rcr
                    rec["flag_raw"] = bool(flag_raw)
                    if not flag_raw:
                        why.append("raw recount does not flag")
                    elif not (rec["usage_out_equal"] and rec["visible_chars_equal"] and rec["result_chars_equal"]):
                        rec["fields_differ_without_flag_change"] = True
            rec["differs"], rec["why"] = bool(why), why
            recs.append(rec)
    return recs


AC1_IMPL["swechat/claude_code"] = ac1_cc_swechat
AC1_IMPL["cc_local"] = ac1_cc_local


def ac1_aiv_cu_multi(allsub, taus):
    """Several strata in one gzip pass: allsub has a column _g (group); returns {group: records}."""
    recs = ac1_aiv_cu(allsub, None, taus=taus)
    out = defaultdict(list)
    for g, r in zip(allsub._g, recs):
        out[g].append(r)
    return out


def ac1_aiv_cu(sub, tau, taus=None):
    """aiv_cu (Anthropic and Gemini strata): the raw computer_use_turns rows of the audited sessions that hold the
    response's provider message id are read from the gzip (streamed; other sessions' lines are not parsed). Recount:
    usage_out = usage.output_tokens (Anthropic) or usageMetadata.candidatesTokenCount (Gemini) of the message; chars =
    the message's visible text (Anthropic text blocks / Gemini non-thought text parts, each distinct text once) + the
    compact JSON of every executed agent_action of those rows (the IR's call args); result chars = output of the last
    executed row by (created_at, row id)."""
    import gzip
    import re
    from analysis.lib.ir import j
    src = "C:/Swarms/data/ai-village/computer_use_turns.jsonl.gz"
    OPENED.append(src + " (streamed; only lines of the audited sessions holding an audited message id were parsed)")
    want = defaultdict(set)
    for s_, r_ in zip(sub.session_id, sub.resp):
        want[str(s_)].add(str(r_))
    rx = re.compile(r'\{"id":"([^"]+)","session_id":"([^"]+)"')
    rows = defaultdict(list)
    with gzip.open(src, "rt", encoding="utf-8") as f:
        for line in f:
            m = rx.match(line)
            sid = m.group(2) if m else None
            if sid is None:
                try:
                    sid = str(json.loads(line).get("session_id"))
                except ValueError:
                    continue
            if sid in want and any(mid in line for mid in want[sid]):
                rows[sid].append(json.loads(line))
    recs = []
    for _, r in sub.iterrows():
        rr = [x for x in rows.get(str(r.session_id), []) if str(r.resp) in json.dumps(x.get("agent_messages"))]
        rr.sort(key=lambda x: (str(x.get("created_at")), str(x.get("id"))))
        rec = {"raw_rows": len(rr)}
        why = []
        if not rr:
            why.append("response not found")
        else:
            am = rr[0].get("agent_messages")
            if isinstance(am, str):
                try:
                    am = json.loads(am)
                except ValueError:
                    am = {}
            am = am if isinstance(am, dict) else {}
            texts, uo = [], None
            if "candidates" in am:
                um = am.get("usageMetadata") or {}
                uo = um.get("candidatesTokenCount")
                for c in am.get("candidates") or []:
                    for p_ in ((c or {}).get("content") or {}).get("parts") or []:
                        if isinstance(p_, dict) and isinstance(p_.get("text"), str) and not p_.get("thought"):
                            texts.append(p_["text"])
            else:
                uo = (am.get("usage") or {}).get("output_tokens")
                for b_ in am.get("content") or []:
                    if isinstance(b_, dict) and b_.get("type") == "text":
                        texts.append(b_.get("text") or "")
            vis = sum(len(t) for t in dict.fromkeys(texts))
            args = 0
            for x in rr:
                a = x.get("agent_action")
                if isinstance(a, str):
                    try:
                        a = json.loads(a)
                    except ValueError:
                        pass
                if a is not None:
                    args += len(j(a))
            out_ = rr[-1].get("output")
            rcr = len(out_) if isinstance(out_, str) else None
            chr_ = vis + args
            rec.update({"usage_out_equal": uo == r.usage_out, "chars_out_equal": chr_ == r.chars_out,
                        "result_chars_equal": rcr == r.rc})
            tau_r = taus[r._g] if taus is not None else tau
            if uo is None or rcr is None:
                why.append("usage or result missing in raw")
            else:
                flag_raw = rcr >= RC_MIN and (uo - tau_r * chr_) >= U_FRAC * tau_r * rcr
                rec["flag_raw"] = bool(flag_raw)
                if not flag_raw:
                    why.append("raw recount does not flag")
                elif not (rec["usage_out_equal"] and rec["chars_out_equal"] and rec["result_chars_equal"]):
                    rec["fields_differ_without_flag_change"] = True
        rec["differs"], rec["why"] = bool(why), why
        recs.append(rec)
    return recs


AC1_IMPL["aiv_cu"] = ac1_aiv_cu


def _read_transcript(sid):
    b = (pe.SWE_TRANSCRIPTS / f"{sid}.jsonl").read_bytes()
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("utf-8", errors="replace")


def _flag_record(r, tau, uo, chr_, rcr, extra=None):
    rec = dict(extra or {})
    why = []
    rec.update({"usage_out_equal": uo == r.usage_out, "chars_out_equal": chr_ == r.chars_out,
                "result_chars_equal": rcr == r.rc})
    if uo is None or rcr is None:
        why.append("usage or result missing in raw")
    else:
        flag_raw = rcr >= RC_MIN and (uo - tau * chr_) >= U_FRAC * tau * rcr
        rec["flag_raw"] = bool(flag_raw)
        if not flag_raw:
            why.append("raw recount does not flag")
        elif not (rec["usage_out_equal"] and rec["chars_out_equal"] and rec["result_chars_equal"]):
            rec["fields_differ_without_flag_change"] = True
    rec["differs"], rec["why"] = bool(why), why
    return rec


def _codex_items_text_raw(content):
    parts = []
    for c in content if isinstance(content, list) else []:
        if isinstance(c, dict) and c.get("type") in ("input_text", "output_text", "text"):
            parts.append(c.get("text") or "")
        elif isinstance(c, dict) and c.get("type") in ("input_image", "image"):
            parts.append("[image]")
    return "\n".join(parts)


def ac1_opencode(sub, tau):
    """swechat/opencode: the session document's message with the response's id (synthetic ids: the message index).
    Recount: usage_out = max step-finish tokens.output; chars = assistant text parts + compact JSON of each tool part's
    input + reasoning text; result chars = the last tool part's output (completed) or error (error)."""
    from analysis.lib.ir import j
    from analysis.loaders.load_swechat import load_document  # the container reader only (JSON document / salvage)
    OPENED.append(f"C:/Swarms/data/swe-chat-pinned/transcripts/<session_id>.jsonl ({sub.session_id.nunique()} audited "
                  "opencode sessions)")
    recs = []
    for sid, g in sub.groupby("session_id"):
        _, msgs = load_document(_read_transcript(sid), Counter())
        byid = {}
        for m in msgs:
            if isinstance(m, dict) and isinstance(m.get("info"), dict):
                byid.setdefault(m["info"].get("id"), m)
        for _, r in g.iterrows():
            rid = str(r.resp)
            m = None
            if rid.startswith("synthetic:opencode:"):
                try:
                    k = int(rid.rsplit(":m", 1)[1])
                    m = msgs[k] if 0 <= k < len(msgs) else None
                except (ValueError, IndexError):
                    m = None
            else:
                m = byid.get(rid)
            if not isinstance(m, dict):
                recs.append({"differs": True, "why": ["response not found"]})
                continue
            uo, vis, th, last_out = None, 0, 0, None
            for part in m.get("parts") or []:
                if not isinstance(part, dict):
                    continue
                t = part.get("type")
                if t == "text":
                    vis += len(part.get("text") or "")
                elif t == "reasoning":
                    th += len(part.get("text") or "")
                elif t == "tool":
                    st_ = part.get("state") if isinstance(part.get("state"), dict) else {}
                    a = j(st_.get("input"))
                    vis += len(a) if isinstance(a, str) else 0
                    out_ = st_.get("output") if st_.get("status") == "completed" else st_.get("error")
                    if out_ is not None and not isinstance(out_, str):
                        out_ = j(out_)
                    last_out = out_ if st_.get("status") in ("completed", "error") else None
                elif t == "step-finish":
                    tk = part.get("tokens") if isinstance(part.get("tokens"), dict) else {}
                    if isinstance(tk.get("output"), (int, float)):
                        uo = max(uo or 0, tk["output"])
            rcr = len(last_out) if isinstance(last_out, str) else None
            recs.append(_flag_record(r, tau, uo, vis + th, rcr, {"thinking_chars_raw": th}))
    return recs


AC1_IMPL["swechat/opencode"] = ac1_opencode


def ac1_codex(sub, tau):
    """swechat/codex: the raw rollout is re-segmented into responses with response_table()'s rule (calls and assistant
    messages accumulate until a token_count with a new cumulative total closes the response; usage_out =
    last_token_usage.output_tokens) and the response whose last call id equals the IR's is recounted."""
    from analysis.lib.ir import j
    OPENED.append(f"C:/Swarms/data/swe-chat-pinned/transcripts/<session_id>.jsonl ({sub.session_id.nunique()} audited "
                  "codex sessions)")
    recs = []
    for sid, g in sub.groupby("session_id"):
        outs, resps = {}, []
        pend, chars, last, prev_total = 0, 0, None, None
        for e in _iter_lines(_read_transcript(sid)):
            if not isinstance(e, dict):
                continue
            p_ = e.get("payload") if isinstance(e.get("payload"), dict) else {}
            rt, pt = e.get("type"), p_.get("type")
            if rt == "response_item":
                if pt == "message" and p_.get("role") == "assistant":
                    chars += len(_codex_items_text_raw(p_.get("content")))
                elif pt in ("function_call", "custom_tool_call", "tool_search_call", "web_search_call"):
                    if pt == "function_call":
                        raw = p_.get("arguments")
                        try:
                            a = j(json.loads(raw) if isinstance(raw, str) else raw)
                        except ValueError:
                            a = raw
                    elif pt == "custom_tool_call":
                        a = j({"input": p_.get("input")})
                    elif pt == "tool_search_call":
                        a = j(p_.get("arguments"))
                    else:
                        a = j(p_.get("action"))
                    pend += 1
                    chars += len(a) if isinstance(a, str) else 0
                    last = p_.get("call_id") if pt != "web_search_call" else None
                elif pt in ("function_call_output", "custom_tool_call_output", "tool_search_output"):
                    cid = p_.get("call_id")
                    if cid not in outs:
                        out_ = p_.get("output") if pt != "tool_search_output" else p_.get("tools")
                        if isinstance(out_, str):
                            outs[cid] = out_
                        elif isinstance(out_, list) and pt != "tool_search_output":
                            outs[cid] = _codex_items_text_raw(out_)
                        else:
                            outs[cid] = j(out_)
            elif rt == "event_msg" and pt == "token_count":
                info = p_.get("info") if isinstance(p_.get("info"), dict) else None
                lastu = (info or {}).get("last_token_usage") or {}
                total = (info or {}).get("total_token_usage")
                uo = None
                if total is not None:
                    tkey = json.dumps(total, sort_keys=True)
                    if tkey != prev_total:
                        uo = lastu.get("output_tokens")
                    prev_total = tkey
                elif any(lastu.get(k) is not None for k in ("input_tokens", "output_tokens", "cached_input_tokens")):
                    uo = lastu.get("output_tokens")
                if uo is not None:
                    if pend:
                        resps.append((last, chars, uo))
                    pend, chars, last = 0, 0, None
        byl = {}
        for lc, ch, uo in resps:
            byl.setdefault(lc, (ch, uo))
        for _, r in g.iterrows():
            hit = byl.get(r.last_call_id)
            if hit is None:
                recs.append({"differs": True, "why": ["response not found"]})
                continue
            ch, uo = hit
            o = outs.get(r.last_call_id)
            recs.append(_flag_record(r, tau, uo, ch, len(o) if isinstance(o, str) else None))
    return recs


AC1_IMPL["swechat/codex"] = ac1_codex


def ac1_sample(E, unit, group):
    """audit_sample() of the flagged eligible responses (the detector's numerator), seed_parts ('N2', 'AC1', group)."""
    f = E[E.flag.astype(bool)].sort_values(["session_id", "resp"])
    keys = list(zip(f.session_id, f.resp))
    pick = set(pe.audit_sample(keys, seed_parts=("N2", "AC1", group)))
    return f[[k in pick for k in keys]], len(keys)


def ac1_audit(unit, E, tau, group, recs=None):
    if unit not in AC1_IMPL:
        return {"label": "NOT_RUN", "reason": f"no raw lookup implemented for {unit}"}
    sub, n_pool = ac1_sample(E, unit, group)
    if recs is None:
        recs = AC1_IMPL[unit](sub, tau)
    nd = sum(1 for x in recs if x["differs"])
    keys = range(n_pool)
    return {"population": "flagged eligible responses (the detector's numerator), B u E or B", "pool_size": len(keys),
            "audited": len(recs), "differing": nd,
            "differing_reasons": dict(Counter(w for x in recs for w in x.get("why", []))),
            "label": "FAIL" if nd >= pe.AUDIT_FAIL else ("PARSER_NOTE" if nd == 1 else "PASS"),
            "note": "vacuous: the detector flagged no response, so there is nothing to audit" if n_pool == 0 else None,
            "rule": "FAIL if >= 2 of 30 differ in a way that changes their contribution; 1 = PARSER_NOTE",
            "seed_parts": ["N2", "AC1", group], "events": recs if unit != "cc_local" else "aggregates only (private)"}


def ac1_aiv_cu_batch(jobs):
    """One streamed pass over the aiv_cu raw turns for every pending stratum: jobs = [(gname, E, tau)]. Returns
    {gname: AC1 record}."""
    subs = {g: ac1_sample(E, "aiv_cu", g)[0] for g, E, _ in jobs}
    allsub = pd.concat(list(subs.values()), ignore_index=True) if subs else pd.DataFrame()
    if not len(allsub):
        return {g: ac1_audit("aiv_cu", E, tau, g, recs=[]) for g, E, tau in jobs}
    out = {}
    taus = {g: tau for g, _, tau in jobs}
    allsub = pd.concat([sb.assign(_g=g) for g, sb in subs.items()], ignore_index=True)
    recs_all = ac1_aiv_cu_multi(allsub, taus)
    for g, E, tau in jobs:
        out[g] = ac1_audit("aiv_cu", E, tau, g, recs=recs_all.get(g, []))
    return out


# ================================================================================================== main
def group_specs(unit, meta_by_split):
    """[(group name, tau or None, granular_on_A, A record)]: one group per unit; aiv_cu one per model stratum."""
    if unit != "aiv_cu":
        a = RES.get(unit, {})
        return [(unit, a.get("tau"), bool(a.get("GRANULAR")), a)]
    strata = set(RES["aiv_cu"].get("by_stratum", {}))
    for m in meta_by_split.values():
        strata |= set(m.get("granularity_by_stratum", {})) | set(m.get("sessions_by_stratum", {}))
    out = []
    for s in sorted(strata):
        a = RES["aiv_cu"].get("by_stratum", {}).get(s)
        out.append((f"aiv_cu/{s}", a.get("tau") if a else None, bool(a and a.get("GRANULAR")), a))
    return out


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
        meta, resp, sm = per_split(corpus, unit, split, df, copied[corpus])
        store[unit][split] = (meta, resp)
        smeta[unit].update(sm)
        del df
        gc.collect()
    print(f"[{time.time() - T0:7.1f}s] statistics", flush=True)
    out = {"item": "n2_token_accounting", "script": "analysis/probes/phase_e_n2.py",
           "prereg_section": "prereg_e.json n2_token_accounting",
           "prereg_e_json_sha256": pe.sha256_file(pe.PREREG_E_JSON),
           "spec_module_sha256": PJ["provenance"]["spec_module_sha256"],
           "spec_module_sha256_lf": pe.sha256_lf(pe.ROOT / "analysis" / "probes" / "prereg_e_common.py"),
           "check_frozen": "passed", "granularity_check_rule": SPEC["granularity_check"], "statistic": SPEC["statistic"],
           "detector": SPEC["detector"], "positive_control": SPEC["positive_control"], "verdict_rule_text": SPEC["verdict"],
           "min_n": SPEC["min_n"], "stated_limit": SPEC["limit"],
           "thresholds_used": {"result_chars_min": RC_MIN, "U_fraction_of_tau_rc": U_FRAC, "tau_prime": list(TAU_PRIME),
                               "alive_flag_rate": FLAG_PT, "alive_flag_hi": FLAG_HI, "weak_flag_rate": WEAK_FLAG,
                               "alive_recall": REC_ALIVE, "weak_recall": REC_WEAK, "min_responses": MIN_RESP,
                               "min_sessions": MIN_SESS, "tau_A": {u: RES.get(u, {}).get("tau") for u in UNITS},
                               "tau_A_aiv_cu_by_stratum": {s: v.get("tau") for s, v in
                                                          RES["aiv_cu"].get("by_stratum", {}).items()}},
           "A_granularity": RES, "cells_computed": 0, "units": {}}
    n_cells = 0
    pending_ac1 = []
    for unit in UNITS:
        splits = [s for s in ("B", "E") if s in store[unit]]
        Uu = {"labels": LABELS.get(unit, []), "sessions_in_split": n_sess_split.get(unit, {}),
              "has_E": CORPUS_OF[unit] in pe.CORPORA_WITH_E,
              "split_meta": {s: store[unit][s][0] for s in splits}, "groups": {}}
        if not splits:
            a = RES.get(unit, {})
            if a and not a.get("GRANULAR"):
                Uu["cell_final"] = {"label": "DEAD", "rule": "not GRANULAR on A (per-turn input/output counts absent); "
                                                             "no B or E session exists to re-check",
                                    "deciding_number": {"G1_share_both_A": a.get("G1_share_both"),
                                                        "G2_median_usage_out_A": a.get("G2_median_usage_out"),
                                                        "responses_A": a.get("responses_A")},
                                    "deciding_path": f"A_granularity.{unit}"}
            else:
                Uu["cell_final"] = {"label": "NOT_TESTABLE(no B or E sessions)"}
            out["units"][unit] = Uu
            continue
        for gname, tau, granA, arec in group_specs(unit, Uu["split_meta"]):
            stratum = gname.split("/", 1)[1] if unit == "aiv_cu" else None
            Gd = {"A": arec, "tau_A": tau, "granular_on_A": granA}
            parts = {}
            gr = {}
            for s in splits:
                meta, resp = store[unit][s]
                if stratum is not None:
                    gs = meta.get("granularity_by_stratum", {}).get(stratum, {"responses": 0, "GRANULAR": False})
                    r = resp[resp._st == stratum] if len(resp) else resp
                else:
                    gs, r = meta["granularity"], resp
                gr[s] = gs
                parts[s] = r
            Gd["granularity"] = gr
            if stratum is not None and arec is None:
                if any((gr[s].get("responses") or 0) > 0 for s in splits):
                    Gd["cell_final"] = {"label": "NOT_TESTABLE(stratum absent from the A calibration: no A tau)"}
                else:
                    Gd["cell_final"] = {"label": "DEAD(not GRANULAR: no API response with a call carries an "
                                                 "identifiable response id on A, B or E)",
                                        "deciding_path": f"units.{unit}.groups.{gname}.granularity"}
                Uu["groups"][gname] = Gd
                continue
            Gd["results"] = {}
            Es = {}
            for s in splits:
                ok = granA and bool(gr[s].get("GRANULAR"))
                note = {"granular_on_A": granA, f"granular_on_{s}": bool(gr[s].get("GRANULAR")),
                        "G1": gr[s].get("G1_share_both"), "G2_median_usage_out": gr[s].get("G2_median_usage_out"),
                        "responses": gr[s].get("responses")}
                if ok:
                    Es[s] = eligible(parts[s], tau)
                    b = block(Es[s], tau, f"units.{unit}.groups.{gname}.results.{s}")
                else:
                    b = block(None, tau, f"units.{unit}.groups.{gname}.results.{s}", granular=False, gran_note=note)
                b["granularity"] = note
                Gd["results"][s] = b
                n_cells += 1
            if len(Es) == 2:
                Es["BE"] = pd.concat([Es["B"], Es["E"]], ignore_index=True)
                b = block(Es["BE"], tau, f"units.{unit}.groups.{gname}.results.BE")
                Gd["results"]["BE"] = b
                n_cells += 1
            lb = Gd["results"].get("B", {}).get("verdict", {}).get("label")
            le = Gd["results"].get("E", {}).get("verdict", {}).get("label")
            if le is not None and le != "INSUFFICIENT_N":
                cell, src = le, f"units.{unit}.groups.{gname}.results.E.verdict.label"
            else:
                cell, src = lb, f"units.{unit}.groups.{gname}.results.B.verdict.label"
            Gd["cell_before_checks"] = {"label": cell, "source_path": src, "B": lb, "E": le,
                                        "suffix": "" if (le is not None and le != "INSUFFICIENT_N") else
                                        (" (B only, unreplicated)" if not Uu["has_E"] else
                                         " (B only; E INSUFFICIENT_N: NOT_REPLICABLE_AT_N)")}
            any_weak = any(Gd["results"][s]["verdict"]["label"] in ("ALIVE", "WEAK") for s in Gd["results"])
            final, checks = cell, []
            if any_weak:
                ACp = "BE" if "BE" in Es else [s for s in splits if s in Es][0]
                Eb = Es[ACp]
                base = Gd["results"][ACp]["verdict"]["label"]
                ac = {"population": "B u E" if ACp == "BE" else ACp, "base_label": base}
                for name, mask in (("AC2_no_truncated", ~Eb.trunc.astype(bool)), ("AC3_join_clean", Eb.join_clean.astype(bool))):
                    b = block(Eb[mask.to_numpy()], tau, f"units.{unit}.groups.{gname}.artifact_checks.{name}", full=False)
                    lab = b["verdict"]["label"]
                    ac[name] = {"responses_dropped": int((~mask).sum()), **short(b), "fail": lab != base,
                                "verdict": b["verdict"]}
                    if lab != base:
                        final = lower(final, lab) if lab in LVL else final
                        checks.append({"name": name, "effect": "lower label to " + str(lab)})
                ac["AC4_dominance"] = dominance_check(Eb, tau, unit, base, smeta[unit])
                if ac["AC4_dominance"]["effect"] == "downgrade":
                    final = pe.downgrade(final)
                    checks.append({"name": "AC4 DOMINATED", "effect": "downgrade"})
                elif ac["AC4_dominance"]["effect"] == "cap_weak" and final == "ALIVE":
                    final = "WEAK"
                    checks.append({"name": "AC4 UNTESTABLE_WITHOUT_DOMINANT", "effect": "cap_weak"})
                if CORPUS_OF[unit] in ("swechat", "aiv_cu"):
                    wts = pe.post_strat_weights(CORPUS_OF[unit], sorted(set(Eb.session_id)))
                    b = block(Eb, tau, f"units.{unit}.groups.{gname}.artifact_checks.AC5_post_stratified", w=wts,
                              full=False)
                    lab = b["verdict"]["label"]
                    ac["AC5_post_stratified"] = {**short(b), "fail": lab != base, "verdict": b["verdict"],
                                                 "weights": "population cell size / analysed sessions in the cell"}
                    if lab != base:
                        final = lower(final, lab) if lab in LVL else final
                        checks.append({"name": "AC5", "effect": "lower label to " + str(lab)})
                    if "B" in Gd["results"] and "E" in Gd["results"] and "honest_flag_rate" in Gd["results"]["E"]:
                        bp = Gd["results"]["B"].get("honest_flag_rate", {}).get("rate")
                        e = Gd["results"]["E"]["honest_flag_rate"]
                        ac["AC5_shift_flag_rate"] = {"B_point": bp, "E_ci": [e.get("lo"), e.get("hi")],
                                                     "SHIFT": bool(bp is not None and e.get("lo") is not None
                                                                   and not (e["lo"] <= bp <= e["hi"])),
                                                     "note": "reported, no verdict effect"}
                else:
                    ac["AC5_post_stratified"] = {"label": "NOT_RUN", "reason": "no population table for this corpus"}
                if cell in ("ALIVE", "WEAK") and unit == "aiv_cu":
                    ac["AC1_parser"] = {"label": "PENDING"}  # one gzip pass for every stratum, after the loop
                    pending_ac1.append((gname, Eb, tau))
                elif cell in ("ALIVE", "WEAK"):
                    ac["AC1_parser"] = ac1_audit(unit, Eb, tau, unit)
                    if ac["AC1_parser"].get("label") == "FAIL":
                        final = pe.downgrade(final)
                        checks.append({"name": "AC1 FAIL", "effect": "downgrade"})
                else:
                    ac["AC1_parser"] = {"label": "NOT_RUN", "reason": f"the N6 cell is {cell}, not WEAK or better"}
                Gd["artifact_checks"] = ac
                st = strata_check(Eb, tau, unit, smeta[unit])
                Gd["stratification"] = st
                if st["CONFINED_any_axis"] and final in LVL:
                    final = pe.downgrade(final)
                    checks.append({"name": "CONFINED", "effect": "downgrade"})
            else:
                Gd["artifact_checks"] = {"status": "not required: no B / E / B u E verdict reached WEAK or better"}
            Gd["cell_final"] = {"label": final, "checks_applied": checks,
                                "suffix": Gd["cell_before_checks"]["suffix"] + "".join(f" [{x}]" for x in Uu["labels"])}
            Uu["groups"][gname] = Gd
        if pending_ac1:
            print(f"[{time.time() - T0:7.1f}s] aiv_cu AC1 (one raw pass for {len(pending_ac1)} strata)", flush=True)
            res_ac1 = ac1_aiv_cu_batch(pending_ac1)
            for g, rec in res_ac1.items():
                Gd = Uu["groups"][g]
                Gd["artifact_checks"]["AC1_parser"] = rec
                if rec.get("label") == "FAIL":  # downgrades commute with the CONFINED downgrade applied above
                    Gd["cell_final"]["label"] = pe.downgrade(Gd["cell_final"]["label"])
                    Gd["cell_final"]["checks_applied"].append({"name": "AC1 FAIL", "effect": "downgrade"})
            pending_ac1.clear()
        if unit != "aiv_cu":
            Uu["cell_final"] = Uu["groups"][unit]["cell_final"]
        else:
            Uu["cell_final"] = {"label": "per stratum (see groups)", "by_stratum": {
                g: v["cell_final"]["label"] for g, v in Uu["groups"].items()},
                "pooled_aiv_cu_granularity": {s: Uu["split_meta"][s]["granularity"] for s in splits}}
        out["units"][unit] = Uu
    out["cells_computed"] = n_cells
    out["deviations"] = DEVIATIONS
    summ = {}
    for unit in UNITS:
        for g, Gd in out["units"][unit].get("groups", {}).items():
            row = {"cell": Gd["cell_final"]["label"], "cell_before_checks": Gd.get("cell_before_checks", {}).get("label"),
                   "suffix": Gd["cell_final"].get("suffix", "")}
            for sp, b in Gd.get("results", {}).items():
                row[sp] = {**short(b), "rule": b["verdict"]["rule"], "path": f"units.{unit}.groups.{g}.results.{sp}"}
            summ[g] = row
    out["summary_raw"] = summ
    out["opened_files"] = sorted(set(OPENED)) + ["analysis/cache/aiv_cu_sessions.parquet (metadata: agent_id)",
                                                 "C:/Swarms/data/swe-chat-pinned/sessions.parquet (metadata: repo_id, user_id)"]
    out["runtime_s"] = round(time.time() - T0, 1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)),
                   encoding="utf-8")
    print(f"[{time.time() - T0:7.1f}s] wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
