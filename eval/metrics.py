"""Eval metrics (DESIGN.md 5.5): FPR, recall, ADR, localization, coverage, transfer grid, disagreement, gates, labels.

Two halves:
  * `summarize_session()` runs where the verifier ran (a pool worker). It reduces one session's `Verdict` list to a small
    JSON-safe summary: per-check counts and flags, composed counts and flags and, for a tampered copy, the
    localization flags against its `Tamper`. Nothing downstream needs the verdict objects.
  * Everything else aggregates summaries into the report tables. Pure functions; no I/O, no wall clock, no rng except
    the fixed-seed session bootstrap.

Statistics are vendored (DA6: the score path imports nothing from `analysis/`, which the climb loop may edit):
`wilson` and `cluster_rate` are verbatim copies of analysis/lib/stats.py, `n7_cell_label` of
analysis/probes/prereg_e_common.py (`FROZEN_COPIES`; tests/test_eval.py asserts identical source). DESIGN.md puts the
two stats copies in eval/_stats.py; that file is owned by another lane and does not exist yet, so they live here until
it lands (one import line to change).
"""
import hashlib
import json
import math
from collections import Counter
from types import SimpleNamespace

import numpy as np

import attacks

FROZEN_COPIES = {"wilson": "analysis/lib/stats.py", "cluster_rate": "analysis/lib/stats.py",
                 "n7_cell_label": "analysis/probes/prereg_e_common.py"}

SEED = 20261003          # analysis/lib/stats.py SEED: every bootstrap
N_BOOT = 1000            # analysis/lib/stats.py N_BOOT
N7_MIN_SESSIONS = attacks.N7_MIN_SESSIONS
MIN_EVENTS, MIN_SESSIONS = 30, 5    # prereg.json global.min_n: a rate needs >= 30 events from >= 5 sessions
SYNTHETIC_FOOTER = ("Every positive in this report is SYNTHETIC (eval/attacks.py tampers presumed-honest public logs). "
                    "No corpus held has a known fabricated tool result. Honest rates are rates on presumed-honest "
                    "sessions, not on verified-honest ones. A coherent forgery passes every check (DESIGN.md 1.4).")


# ============================================================================================================ frozen
def wilson(k, n, z=1.96):
    """Wilson 95% interval for a proportion k/n. Returns (p, lo, hi); (None, None, None) if n == 0."""
    if n == 0:
        return (None, None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, c - h), min(1.0, c + h))


def cluster_rate(num_by_session, den_by_session, n_boot=N_BOOT, seed=SEED):
    """Ratio estimate sum(num)/sum(den) with a session-clustered bootstrap 95% CI.
    num_by_session, den_by_session: equal-length arrays, one entry per session.
    Returns dict(rate, lo, hi, n_sessions, num, den)."""
    num = np.asarray(num_by_session, dtype=float)
    den = np.asarray(den_by_session, dtype=float)
    keep = den > 0
    num, den = num[keep], den[keep]
    n = len(den)
    if n == 0 or den.sum() == 0:
        return {"rate": None, "lo": None, "hi": None, "n_sessions": int(n), "num": float(num.sum()), "den": float(den.sum())}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    boots = num[idx].sum(1) / np.maximum(den[idx].sum(1), 1e-12)
    return {"rate": float(num.sum() / den.sum()), "lo": float(np.quantile(boots, 0.025)), "hi": float(np.quantile(boots, 0.975)),
            "n_sessions": int(n), "num": float(num.sum()), "den": float(den.sum())}


stats = SimpleNamespace(wilson=wilson)   # n7_cell_label below calls stats.wilson, as at its source


def n7_cell_label(n_tampered, k_tampered, n_honest, k_honest):
    if n_tampered < N7_MIN_SESSIONS:
        return "INSUFFICIENT_N", None
    rec = stats.wilson(k_tampered, n_tampered)
    fpr = stats.wilson(k_honest, n_honest)
    if rec[1] > fpr[2]:
        return ("DETECTS" if rec[0] >= 0.5 else "PARTIAL"), {"recall": rec, "fpr": fpr}
    return "BLIND", {"recall": rec, "fpr": fpr}


def clopper_pearson_hi(k, n):
    """Upper 95% Clopper-Pearson bound (SCOPE.md 8.4), used where a zero count needs a bound computed here."""
    if n == 0:
        return None
    if k >= n:
        return 1.0
    from scipy.stats import beta
    return float(beta.ppf(0.975, k + 1, n - k))


def wil(k, n):
    p, lo, hi = wilson(k, n)
    return {"k": int(k), "n": int(n), "p": p, "lo": lo, "hi": hi}


# ============================================================================================================ per session
def _status(reason: str) -> str:
    if reason.startswith("ok:") or reason.startswith("violation:"):
        return "decided"
    if reason == "abstain:below_threshold":
        return "screened"
    if reason.startswith("error:"):
        return "error"
    return "unconstrained"


def blame_seq(cvs) -> int | None:
    """compose.blame_seq's rule (DESIGN.md 4.6) over a set of contradicting CallVerdicts: the most-cited seq among
    refs with role subject or conflict; ties -> the later seq."""
    c = Counter(r.seq for cv in cvs for r in (cv.evidence or ()) if getattr(r, "role", None) in ("subject", "conflict"))
    if not c:
        return None
    return max(c, key=lambda s: (c[s], s))


def _loc_hit(call_id, cvs, tamper) -> bool:
    """flag_loc for one call (DESIGN.md 5.5): its call_id is a target, or the blame of its contradicting checks is a
    tampered event, or a stream-level (non-localized) contradiction sits on a target stream."""
    if call_id in tamper.target_call_ids:
        return True
    b = blame_seq(cvs)
    if b is not None and b in tamper.tampered_seqs:
        return True
    return any((not cv.localized) and cv.unit_kind == "stream" and cv.unit_id in tamper.target_streams for cv in cvs)


def summarize_session(verdicts, *, tamper=None, credited=(), keep_contradictions=False) -> dict:
    """Reduce one session's Verdict list to a JSON-safe summary (the only thing a worker returns)."""
    credited = set(credited)
    out = {"n_calls": len(verdicts), "version": verdicts[0].version if verdicts else None,
           "comp": {"supported": 0, "contra_loc": 0, "contra_unit": 0, "unconstrained": 0, "covered": 0,
                    "flag": False, "flag_loc": False, "cred_flag": False, "cred_flag_loc": False},
           "comp_reasons": Counter(), "checks": {}, "disagree": Counter(), "errors": 0, "contradictions": []}
    comp = out["comp"]
    for v in verdicts:
        cvs = list(v.checks or ())
        screened = False
        contra_cvs, supp_names = [], []
        for cv in cvs:
            st = _status(cv.reason)
            d = out["checks"].setdefault(cv.check, {
                "calls": 0, "decided": 0, "screened": 0, "contra": 0, "supported": 0, "error": 0, "contra_loc": 0,
                "contra_unit": 0, "by_strength": Counter(), "reasons": Counter(), "streams": {}, "flag": False,
                "flag_loc": False})
            d["calls"] += 1
            d["reasons"][cv.reason] += 1
            if st == "decided":
                d["decided"] += 1
                d["by_strength"][cv.strength] += 1
            elif st == "screened":
                d["screened"] += 1
                screened = True
            elif st == "error":
                d["error"] += 1
                out["errors"] += 1
            if st in ("decided", "screened") and cv.unit_kind == "stream" and cv.unit_id is not None:
                d["streams"][str(cv.unit_id)] = d["streams"].get(str(cv.unit_id), False) or cv.verdict == "contradicted"
            if cv.verdict == "contradicted":
                d["contra"] += 1
                d["contra_loc" if cv.localized else "contra_unit"] += 1
                d["flag"] = True
                contra_cvs.append(cv)
                if tamper is not None and not d["flag_loc"] and _loc_hit(v.call_id, [cv], tamper):
                    d["flag_loc"] = True
                if keep_contradictions:
                    out["contradictions"].append([v.call_id, cv.check, cv.reason])
            elif cv.verdict == "supported":
                d["supported"] += 1
                supp_names.append(cv.check)
        for x in contra_cvs:
            for y in supp_names:
                out["disagree"][f"{x.check}|{y}"] += 1
        if v.verdict == "contradicted":
            comp["contra_loc" if v.localized else "contra_unit"] += 1
            comp["flag"] = True
            if tamper is not None and not comp["flag_loc"]:
                hit = v.call_id in tamper.target_call_ids or (v.blame_seq is not None and v.blame_seq in tamper.tampered_seqs)
                hit = hit or any((not cv.localized) and cv.unit_kind == "stream" and cv.unit_id in tamper.target_streams
                                 for cv in contra_cvs)
                comp["flag_loc"] = bool(hit)
        elif v.verdict == "supported":
            comp["supported"] += 1
        else:
            comp["unconstrained"] += 1
            out["comp_reasons"][v.reason] += 1
        if v.verdict in ("supported", "contradicted") or screened:
            comp["covered"] += 1
        cred = [cv for cv in contra_cvs if cv.check in credited]
        if cred:
            comp["cred_flag"] = True
            if tamper is not None and not comp["cred_flag_loc"] and _loc_hit(v.call_id, cred, tamper):
                comp["cred_flag_loc"] = True
    for d in out["checks"].values():
        d["by_strength"] = dict(d["by_strength"])
        d["reasons"] = dict(d["reasons"])
    out["comp_reasons"] = dict(out["comp_reasons"])
    out["disagree"] = dict(out["disagree"])
    return out


# ============================================================================================================ honest tables
def unit_table(S: list) -> dict:
    """Composed-verifier honest numbers for one unit (DESIGN.md 5.5 fpr_session_any, coverage_any, shares)."""
    n = len(S)
    calls = sum(s["n_calls"] for s in S)
    k = sum(1 for s in S if s["comp"]["flag"])
    cov = sum(s["comp"]["covered"] for s in S)
    sup = sum(s["comp"]["supported"] for s in S)
    cl = sum(s["comp"]["contra_loc"] for s in S)
    cu = sum(s["comp"]["contra_unit"] for s in S)
    reasons = Counter()
    for s in S:
        reasons.update(s["comp_reasons"])
    return {"n_sessions": n, "n_calls": calls, "fpr_session_any": wil(k, n) if n else None,
            "coverage_any": (cov / calls) if calls else None, "supported_share": (sup / calls) if calls else None,
            "contradicted_share": ((cl + cu) / calls) if calls else None, "contradicted_localized": cl,
            "contradicted_unit": cu, "covered_calls": cov,
            "unconstrained_reasons_top": dict(sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))[:8])}


def check_unit_table(S: list, check: str) -> dict:
    """One check on one unit's honest pack (DESIGN.md 5.5 fpr_session, fpr_call, coverage, decision-unit rate)."""
    rows = [s["checks"].get(check) for s in S]
    present = [r for r in rows if r is not None]
    calls = sum(s["n_calls"] for s in S)
    dec_s = [r for r in present if r["decided"] + r["screened"] > 0]
    k = sum(1 for r in dec_s if r["contra"] > 0)
    reasons = Counter()
    strength = Counter()
    for r in present:
        reasons.update(r["reasons"])
        strength.update(r["by_strength"])
    decided = sum(r["decided"] for r in present)
    screened = sum(r["screened"] for r in present)
    streams_n = [len(r["streams"]) for r in present]
    streams_k = [sum(1 for f in r["streams"].values() if f) for r in present]
    out = {
        "n_sessions": len(S), "sessions_ran": len(present), "decided_or_screened_sessions": len(dec_s),
        "abstain_sessions": len(S) - len(dec_s),
        "fpr_session": wil(k, len(dec_s)) if dec_s else None,
        "fpr_session_insufficient_n": len(dec_s) < N7_MIN_SESSIONS,
        "fpr_call": cluster_rate([r["contra"] for r in present], [r["decided"] + r["screened"] for r in present])
        if present else None,
        "coverage": ((decided + screened) / calls) if calls else None, "decided_calls": decided,
        "screened_calls": screened, "coverage_by_strength": {k_: v / calls for k_, v in sorted(strength.items())}
        if calls else {},
        "contradicted_calls": sum(r["contra"] for r in present),
        "contradicted_localized": sum(r["contra_loc"] for r in present),
        "contradicted_unit": sum(r["contra_unit"] for r in present),
        "errors": sum(r["error"] for r in present),
        "reasons_top": dict(sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))[:10]),
    }
    if sum(streams_n):
        out["stream_level"] = {"units": int(sum(streams_n)), "flagged": int(sum(streams_k)),
                               "rate": cluster_rate(streams_k, streams_n),
                               "wilson_per_unit": wil(int(sum(streams_k)), int(sum(streams_n)))}
    out["all_calls_reason"] = _uniform_reason(reasons)
    return out


def _uniform_reason(reasons: Counter):
    """The reason every call carried, when there is exactly one (NOT_TESTABLE / NOT_RUN detection), else None."""
    return next(iter(reasons)) if len(reasons) == 1 else None


def disagreement(H: dict) -> dict:
    tot = Counter()
    for S in H.values():
        for s in S:
            tot.update(s["disagree"])
    out = {}
    for key, n in sorted(tot.items()):
        x, y = key.split("|", 1)
        out.setdefault(x, {})[y] = n
    return out


# ============================================================================================================ attack cells
def cell_table(copies: list, honest: dict, checks: list, cls: str, seeds: list, check_reads: dict | None = None,
               attack: str | None = None, credited=()) -> dict:
    """One (unit, attack, param) cell. copies: tampered-copy summaries with 'seed' and 'sid'; honest: sid -> honest
    summary. Composed ADR uses flag_loc on edit cells and the EXEC_CREDIT-restricted flag on exec cells (DA13); exec
    cells also name the uncredited checks behind edit_artifact_adr (ADR > 0 on that seed)."""
    out = {"cls": cls, "per_seed": {}, "per_check": {}}
    for s in seeds:
        C = [c for c in copies if c["seed"] == s]
        n = len(C)
        hf = [bool(honest[c["sid"]]["comp"]["flag"]) for c in C]
        hcf = [bool(honest[c["sid"]]["comp"]["cred_flag"]) for c in C]
        adr_ind = [int(c["comp"]["flag_loc"] and not h) for c, h in zip(C, hf)]
        cred_ind = [int(c["comp"]["cred_flag_loc"] and not h) for c, h in zip(C, hcf)]
        adr = float(np.mean(adr_ind)) if n else 0.0
        adr_c = float(np.mean(cred_ind)) if n else 0.0
        row = {"n_copies": n,
               "recall": wil(sum(1 for c in C if c["comp"]["flag"]), n) if n else None,
               "recall_loc": wil(sum(1 for c in C if c["comp"]["flag_loc"]), n) if n else None,
               "adr": adr, "adr_ci": cluster_rate(adr_ind, [1] * n) if n else None}
        if cls == "exec":
            row["adr_credited"] = adr_c
            row["edit_artifact_adr"] = adr - adr_c
        row["adr_headline"] = adr_c if cls == "exec" else adr
        out["per_seed"][str(s)] = row
    for chk in checks:
        pc_ = {}
        for s in seeds:
            C = [c for c in copies if c["seed"] == s]
            n = len(C)
            fl = [bool((c["checks"].get(chk) or {}).get("flag")) for c in C]
            fll = [bool((c["checks"].get(chk) or {}).get("flag_loc")) for c in C]
            hfl = [bool((honest[c["sid"]]["checks"].get(chk) or {}).get("flag")) for c in C]
            ind = [int(a and not h) for a, h in zip(fll, hfl)]
            r = {"n": n, "recall": wil(sum(fl), n) if n else None, "recall_loc": wil(sum(fll), n) if n else None,
                 "adr": float(np.mean(ind)) if n else 0.0,
                 "localization": {"k_loc": int(sum(fll)), "k_flag": int(sum(fl)),
                                  "share": (sum(fll) / sum(fl)) if sum(fl) else None}}
            if s == seeds[0]:
                reads = (check_reads or {}).get(chk)
                if reads is not None and attack is not None and not (set(reads) & attacks.ATTACK_FIELDS[attack]):
                    r["cell_label"] = "NA_BLIND_BY_CONSTRUCTION"
                else:
                    lab, ci = n7_cell_label(n, int(sum(fl)), n, int(sum(hfl)))
                    r["cell_label"] = lab
                    r["cell_label_basis"] = {"recall": wil(int(sum(fl)), n) if n else None,
                                             "fpr_same_sessions": wil(int(sum(hfl)), n) if n else None,
                                             "rule": "prereg_e.json n7_cell_label on the first seed"}
            pc_[str(s)] = r
        out["per_check"][chk] = pc_
    if cls == "exec":
        for s in seeds:
            out["per_seed"][str(s)]["edit_artifact_checks"] = sorted(
                c for c in checks if c not in set(credited) and out["per_check"][c][str(s)]["adr"] > 0)
    return out


def headline(cells: dict, seeds: list) -> dict:
    """DA12: per seed, mean ADR over exec headline cells and over edit headline cells, 0.5 / 0.5 (one class alone if
    the other has no headline cell); headline = mean over seeds, stdev = pstdev (as eval/core.py)."""
    per = {}
    for s in seeds:
        ex = [c["per_seed"][str(s)]["adr_headline"] for c in cells.values() if c["cls"] == "exec"]
        ed = [c["per_seed"][str(s)]["adr_headline"] for c in cells.values() if c["cls"] == "edit"]
        ea = [c["per_seed"][str(s)].get("edit_artifact_adr", 0.0) for c in cells.values() if c["cls"] == "exec"]
        mx = float(np.mean(ex)) if ex else None
        md = float(np.mean(ed)) if ed else None
        h = (0.5 * mx + 0.5 * md) if (mx is not None and md is not None) else (mx if mx is not None else (md or 0.0))
        per[str(s)] = {"headline": h, "adr_loc_macro_exec": mx, "adr_loc_macro_edit": md,
                       "edit_artifact_adr_exec": float(np.mean(ea)) if ea else None,
                       "n_exec_cells": len(ex), "n_edit_cells": len(ed)}
    hs = [per[str(s)]["headline"] for s in seeds]
    mean = lambda xs: float(np.mean([x for x in xs if x is not None])) if any(x is not None for x in xs) else None  # noqa: E731
    return {"per_seed": per, "headline": float(np.mean(hs)) if hs else 0.0,
            "stdev": float(np.std(hs)) if hs else 0.0,
            "adr_loc_macro_exec": mean([per[str(s)]["adr_loc_macro_exec"] for s in seeds]),
            "adr_loc_macro_edit": mean([per[str(s)]["adr_loc_macro_edit"] for s in seeds]),
            "edit_artifact_adr_exec": mean([per[str(s)]["edit_artifact_adr_exec"] for s in seeds])}


# ============================================================================================================ transfer
def transfer_cell(ct: dict | None, labels: dict) -> dict:
    """prereg_e.json a1.proposal_rules on the verifier's own outputs (DESIGN.md 5.5 transfer). ct: check_unit_table;
    labels: attack|param -> seed-0 cell_label of this check in this unit."""
    if ct is None or ct["sessions_ran"] == 0:
        return {"label": "NOT_RUN(not_run)"}
    r = ct.get("all_calls_reason")
    if r and r.startswith("missing:"):
        return {"label": f"NOT_TESTABLE({r.split(':', 1)[1]})"}
    if r in ("abstain:uncalibrated_unit", "abstain:unit_not_enabled"):
        return {"label": f"NOT_RUN({r.split(':', 1)[1]})"}
    if ct["decided_or_screened_sessions"] < N7_MIN_SESSIONS:
        return {"label": "INSUFFICIENT_N", "n": ct["decided_or_screened_sessions"]}
    if "stream_level" in ct:
        w = ct["stream_level"]["wilson_per_unit"]
        level = "stream"
    else:
        w = ct["fpr_session"]
        level = "session"
    single = {k: v for k, v in labels.items() if k.split("|", 1)[0] in attacks.SINGLE_CALL_TYPES}
    if w["p"] <= 0.05 and w["hi"] <= 0.10 and any(v == "DETECTS" for v in single.values()):
        lab = "ALIVE"
    elif w["p"] <= 0.20 and any(v in ("DETECTS", "PARTIAL") for v in labels.values()):
        lab = "WEAK"
    else:
        lab = "DEAD"
    return {"label": lab, "honest": w, "honest_level": level, "cell_labels": dict(sorted(labels.items()))}


# ============================================================================================================ gates
def gates(per_check: dict, pooled_any: dict, config: dict) -> str | None:
    """DESIGN.md 5.5 gates 2 and 3 (gate 1, ok:false, is decided by the caller). fpr_cap may be {check: cap} or
    {check: {unit: cap}}; both caps are written by day from the freeze baseline run and are absent until then."""
    caps = config.get("fpr_cap") or {}
    for chk in sorted(per_check):
        cap_c = caps.get(chk)
        if cap_c is None:
            continue
        for unit in sorted(per_check[chk]):
            ct = per_check[chk][unit]
            if ct["fpr_session"] is None or ct["decided_or_screened_sessions"] < N7_MIN_SESSIONS:
                continue
            cap = cap_c.get(unit) if isinstance(cap_c, dict) else cap_c
            if cap is not None and ct["fpr_session"]["hi"] > cap:
                return f"fpr_cap:{chk}:{unit}"
    clean = config.get("CLEAN_CAP")
    if clean is not None and pooled_any and pooled_any.get("hi") is not None and pooled_any["hi"] > clean:
        return "clean_cap"
    return None


# ============================================================================================================ labels
def session_ir_sha(events) -> str:
    """DESIGN.md 3.4: sha256 over the session's IR rows, columns in COLUMNS order, rows in seq order, NA as empty,
    fields joined with \\x1f and rows with \\x1e."""
    df = events.sort_values("seq", kind="mergesort")
    cols = list(attacks.IR_COLUMNS)
    vals = [df[c].astype(object).tolist() for c in cols]
    rows = []
    for i in range(len(df)):
        rows.append("\x1f".join("" if attacks._isna(v[i]) else str(v[i]) for v in vals))
    return hashlib.sha256("\x1e".join(rows).encode("utf-8")).hexdigest()


def join_labels(verdicts, labels):
    """DESIGN.md 3.4 join rules. verdicts: DataFrame (session_id, call_id, seq, contradicted, ir_sha) one row per call;
    labels: DataFrame of LabeledCall fields. Returns labels with join_status and the joined 'contradicted'."""
    import pandas as pd
    by_cid, by_seq, sha = {}, {}, {}
    for sid, cid, q, f, h in zip(verdicts.session_id, verdicts.call_id, verdicts.seq, verdicts.contradicted,
                                 verdicts.ir_sha):
        by_cid.setdefault((str(sid), str(cid)), []).append(bool(f))
        by_seq[(str(sid), int(q))] = bool(f)
        sha[str(sid)] = h
    st, fl = [], []
    for sid, cid, q, h in zip(labels.session_id, labels.call_id, labels.seq, labels.ir_sha):
        sid = str(sid)
        if sid not in sha:
            st.append("orphan_label")
            fl.append(None)
        elif isinstance(cid, str) and cid:
            m = by_cid.get((sid, cid), [])
            st.append("ok" if len(m) == 1 else ("ambiguous" if len(m) > 1 else "orphan_label"))
            fl.append(m[0] if len(m) == 1 else None)
        elif q is not None and not (isinstance(q, float) and math.isnan(q)) and h == sha[sid] and (sid, int(q)) in by_seq:
            st.append("ok")
            fl.append(by_seq[(sid, int(q))])
        else:
            st.append("seq_mismatch")
            fl.append(None)
    out = labels.copy()
    out["join_status"] = st
    out["contradicted"] = pd.Series(fl, index=out.index, dtype=object)
    return out


def labeled_metrics(joined) -> dict:
    """DESIGN.md 5.5 labeled.*: per class, recall on pos and FPR on neg (session-clustered CIs), precision; unknown
    excluded but counted; join_status counts. Call-level: a call is flagged when its composed verdict contradicts."""
    js = Counter(joined.join_status)
    ok = joined[joined.join_status == "ok"]
    out = {"join_status": dict(js), "join_ok_share": (js.get("ok", 0) / len(joined)) if len(joined) else None,
           "unknown_labels": int((joined.label == "unknown").sum()), "classes": {}}
    for cls, g in ok[ok.label != "unknown"].groupby(ok["class"].astype(str) if "class" in ok else ok["cls"].astype(str)):
        pos, neg = g[g.label == "pos"], g[g.label == "neg"]
        def rate(d):
            if not len(d):
                return None
            per = d.groupby("session_id").contradicted.agg(lambda x: int(sum(bool(v) for v in x)))
            n = d.groupby("session_id").size()
            return cluster_rate(per.to_numpy(), n.reindex(per.index).to_numpy())
        tp = int(sum(bool(v) for v in pos.contradicted))
        fp = int(sum(bool(v) for v in neg.contradicted))
        out["classes"][cls] = {"n_pos": int(len(pos)), "n_neg": int(len(neg)), "recall": rate(pos), "fpr": rate(neg),
                               "precision": (tp / (tp + fp)) if (tp + fp) else None}
    rec = [c["recall"]["rate"] for c in out["classes"].values() if c["recall"] and c["recall"]["rate"] is not None]
    out["labeled_recall_macro"] = float(np.mean(rec)) if rec else None
    return out


# ============================================================================================================ report utils
def round_floats(o, nd=6):
    if isinstance(o, dict):
        return {str(k): round_floats(v, nd) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [round_floats(v, nd) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if not math.isfinite(f) else round(f, nd)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (set, frozenset)):
        return sorted(round_floats(v, nd) for v in o)
    return o


def content_sha(report: dict, exclude=("timing", "content_sha256")) -> str:
    """sha256 of the report without its wall-clock fields (DESIGN.md 5.6: runtime never enters the content hash)."""
    body = {k: v for k, v in report.items() if k not in exclude}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
