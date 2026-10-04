"""Phase E, Track A, item A1 (second pass) for the Probe 2 WEAK candidates and the Probe 4 round-number candidates, with
follow-up F3 (round numbers without model-chosen parameters).  Item key: a1_p2_p4_f3.

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_a1_p2_p4_f3
Debug run (unit subset, output to a scratch path):  A1_DEBUG_OUT=<path> python -m ... <part> ...   (part in p2, p4)

Pre-registration (the law): analysis/PREREG_E.md sections 1.1-1.3 and 1.7, analysis/prereg_e.json (a1.candidates, a1.P2_common,
followups.F3_round_numbers, artifact_checks, stratification, survival_rule) and analysis/probes/prereg_e_common.py,
committed in 55fc556. check_frozen() runs before anything else. Every threshold comes from prereg_e.json / prereg.json;
nothing is tuned here.

Candidates (prereg_e.json a1.candidates):
  P4round/swechat/claude_code      Phase B ALIVE  has E   kill test F3 (parameter exclusion)
  P4round/cc_local                 Phase B ALIVE  no E    F3 (B only, unreplicated; PRIVATE: aggregates only)
  P4round/swechat/* (pooled)       Phase B ALIVE  has E   F3, label 'pooled' (claude_code supplies most sessions)
  P2/swechat/claude_code/main      Phase B WEAK   has E   P2 K1 (strict root rule), K2 (no compaction/resume/clear)
  P2/swechat/claude_code/subagent  Phase B WEAK   has E   K1, K2
  P2/swechat/opencode/subagent     Phase B WEAK   has E   K1 (its Phase B number rests on the logged root-rule deviation), K2
  P2/swechat/codex/subagent        Phase B WEAK   has E   K1, K2 (S_path_any fallback)
  P2/aiv_cc/main                   Phase B WEAK   no E    K1, K2 (S_path_any fallback; single-agent case study)
For each: the Phase B statistic re-measured on B (reproduction of the committed Phase B numbers), on E (replication
verdict) and on B u E (re-measurement population); the kill tests first (a fired kill stops that line: the remaining
checks are recorded as NOT_RUN); then artifact checks AC1-AC5 and the four stratification axes on B u E; then
survival_status() applied mechanically.

Code paths reused unchanged (the re-measurement is the same statistic):
  Probe 2: probe_2.process_unit (extraction, sourcing, first access, depth), crate, verdict, stratum_block, ref_frame,
           acc_frame, find_first/_ok_path (path match). The probe_2 DEBUG / DEBUG_ACCESS hooks are used in memory only to
           recover each decision event's (session, call seq, path key) for K1 and the artifact checks; no path or text
           from them is written for cc_local (cc_local is not a Probe 2 candidate).
  Probe 4: probe_4.load_prereg (thresholds), rate_cell, by_session, round_verdict, apply_redaction_cap. The large-integer
           walk below mirrors probe_4.extract / prereg_e_calibration.cal_round (antecedents = large ints of earlier
           result/user/system events; T_orig = call-arg large ints without antecedent; M_all = result large ints); it is
           checked against the committed probe_4.json numbers on B (reproduction_B_vs_phase_b).
  Phase E: prereg_e_common read_cache / split_ids (B and E only; H is never read), classify_args_ints, truncated_result,
           join_clean_mask, audit_sample, dominance, session_cluster_map, session_model_map, length_tercile_map,
           post_strat_weights, weighted_cluster_rate, confinement, downgrade, survival_status, raw_cc_entries, rng_for.

Reads: analysis/cache/swechat_{B,E}.parquet, cc_local_B.parquet, aiv_cc_B.parquet, swechat_population.parquet,
swe-chat-pinned sessions.parquet (repo_id/user_id for B u E ids only), raw transcripts for the AC1 audit samples and the
P2-K2 resume test (swechat public transcripts; cc_local frozen snapshot data/claude-code-local, in-process, match counts
only; data/ai-village/claude_code_messages.jsonl.gz for the aiv_cc audit). Never reads *_A.parquet, *_EH.json key H, or
anything of the local Qwen swarm.
Writes RAW NUMBERS ONLY to analysis/out/phase_e/a1_p2_p4_f3.json and the F3 section alone to
analysis/out/phase_e/f3_round.json (the path prereg_e.json outputs.F3 names). Interpretation:
analysis/notes/phase_e_a1_p2_p4_f3.md.
"""
from analysis.probes import prereg_e_common as E

PJ = E.check_frozen()  # first: the module must be the pre-registered one (stops with AssertionError otherwise)

import glob  # noqa: E402
import gzip  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from analysis.probes import prereg_common as pc  # noqa: E402
from analysis.probes import probe_2 as p2  # noqa: E402
from analysis.probes import probe_4 as p4  # noqa: E402

ROOT = E.ROOT
OUT = E.OUT_E / "a1_p2_p4_f3.json"
OUT_F3 = E.OUT_E / "f3_round.json"
LEVEL = E.LEVEL
FM = pc.swechat_formats()
CC_LOCAL_ROOT = os.path.join(os.environ.get("SWARMS_DATA", "C:/Swarms/data"), "claude-code-local")
AIV_CC_RAW = os.path.join(os.environ.get("SWARMS_DATA", "C:/Swarms/data"), "ai-village", "claude_code_messages.jsonl.gz")

PR4, TH4, PROV4 = p4.load_prereg()   # Phase B prereg.json + Probe 4 thresholds (sha-checked by probe_4.load_prereg)
PR2 = p2.PR
F3 = PJ["followups"]["F3_round_numbers"]
F3_COLLAPSE = 0.25   # followups.F3_round_numbers.verdict: 'g <= 0.25 x g_full'
F3_KEEP_ALIVE = 0.5  # 'ALIVE is kept only if the rule gives ALIVE AND g >= 0.5 x g_full'
assert "g <= 0.25 x g_full" in F3["verdict"] and "g >= 0.5 x g_full" in F3["verdict"]
assert TH4["round_margin"] == 0.05 and TH4["round_min_values"] == 100 and TH4["round_min_sessions"] == 10

P4_POOL_MEMBERS = json.load(open(ROOT / "analysis" / "out" / "probe_4.json", encoding="utf-8"))["pooled"]["swechat/*"]["members"]
P4_CANDS = {"P4round/swechat/claude_code": ["swechat/claude_code"], "P4round/cc_local": ["cc_local"],
            "P4round/swechat/* (pooled)": list(P4_POOL_MEMBERS)}
P2_CANDS = {"P2/swechat/claude_code/main": ("swechat/claude_code", "main"),
            "P2/swechat/claude_code/subagent": ("swechat/claude_code", "sub"),
            "P2/swechat/opencode/subagent": ("swechat/opencode", "sub"),
            "P2/swechat/codex/subagent": ("swechat/codex", "sub"),
            "P2/aiv_cc/main": ("aiv_cc", "main")}
PHASE_B = {k: "ALIVE" for k in P4_CANDS} | {k: "WEAK" for k in P2_CANDS}
P2_REF = {"P2/swechat/claude_code/main": ("swechat/claude_code", "main"),
          "P2/swechat/claude_code/subagent": ("swechat/claude_code", "sub"),
          "P2/swechat/opencode/subagent": ("swechat/opencode", "sub"),
          "P2/swechat/codex/subagent": ("swechat/codex", "sub"), "P2/aiv_cc/main": ("aiv_cc", "main")}
COLS = ["session_id", "seq", "kind", "ts", "tool", "tool_raw", "call_id", "args", "command", "text", "stderr",
        "native_error", "exit_code", "is_subagent", "agent_id", "extra", "stratum", "uuid"]
KINDS = ["user", "system", "call", "result", "meta"]
K2_TYPES = ("compaction", "context_clear", "resume")


# ================================================================================================ small helpers
def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if not math.isfinite(f) else f
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if o is pd.NA:
        return None
    return o


def lower(a, b):
    if a not in LEVEL:
        return b
    if b not in LEVEL:
        return a
    return a if LEVEL[a] <= LEVEL[b] else b


def norm_clusters(m):
    return {s: (v if isinstance(v, str) and v not in ("", "nan", "None") else "unknown") for s, v in m.items()}


def anon_rank(keys_in_order, prefix):
    return {k: (k if k == "unknown" else f"{prefix}#{i + 1}") for i, k in enumerate(keys_in_order)}


def min_check(name, ref_label, check_label, running):
    """'take the lower label' semantics (AC2, AC3, AC5): FAIL if the label under the check is lower than the reference
    label (a higher one is ignored: no rescue); the candidate then takes the lower of its running label and the check
    label. Returns (check dict for survival_status, new running label)."""
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


def combine_min_checks(name, pairs, running):
    """pairs: [(stat_name, ref_label, check_label)]. The check FAILs if any statistic's label drops; the candidate takes
    the lowest failing check label (DEVIATIONS: P4 checks on both the candidate statistic and the F3 statistic)."""
    per = {}
    worst = None
    for stat, ref, chk in pairs:
        c, _ = min_check(f"{name}[{stat}]", ref, chk, running)
        per[stat] = {"ref": ref, "check": chk, "result": c["result"]}
        if c["result"] == "FAIL":
            worst = chk if worst is None else lower(worst, chk)
    if worst is None:
        res = "PASS" if any(v["result"].startswith("PASS") for v in per.values()) else "UNTESTABLE"
        return {"name": name, "effect": "pass", "result": res, "per_statistic": per}, running
    tgt = lower(running, worst)
    eff = "pass" if tgt == running else ("kill" if tgt == "DEAD" or LEVEL[running] - LEVEL[tgt] > 1 else "downgrade")
    return {"name": name, "effect": eff, "result": "FAIL", "per_statistic": per, "candidate_label_before": running,
            "candidate_label_after": tgt}, tgt


def alt_order(phase_b, e_label, checks_min, checks_other, has_e):
    _, lab, _ = E.survival_status(phase_b, e_label, checks_other, has_e=has_e)
    for c in checks_min:
        if c.get("result") == "FAIL":
            lab = lower(lab, c.get("candidate_label_after", lab))
    return lab


def kill_label(results):
    """Kill-test population rule (DEVIATIONS 'kill tests: B u E decides, E applies too'): results = {pop: label};
    the label used is the lowest testable one among B u E and E (B for units without E)."""
    labs = [v for v in results.values() if v in LEVEL]
    if not labs:
        return None
    out = labs[0]
    for v in labs[1:]:
        out = lower(out, v)
    return out


# ================================================================================================ loading
def unit_ids(unit, split):
    fmt = unit.split("/")[1]
    return [s for s in E.split_ids("swechat", split) if FM.get(s) == fmt]


def load(unit, split, with_assistant=False):
    kinds = KINDS + (["assistant"] if with_assistant else [])
    if unit.startswith("swechat/"):
        df = E.read_cache("swechat", split, COLS, filters=[("session_id", "in", unit_ids(unit, split)), ("kind", "in", kinds)])
    else:
        df = E.read_cache(unit, split, COLS, filters=[("kind", "in", kinds)])
    return df.sort_values(["session_id", "seq"], kind="stable").reset_index(drop=True)


def model_map(unit, split):
    if unit.startswith("swechat/"):
        m = E.read_cache("swechat", split, ["session_id", "kind", "model"],
                         filters=[("session_id", "in", unit_ids(unit, split)), ("model", "!=", "")])
    else:
        m = E.read_cache(unit, split, ["session_id", "kind", "model"], filters=[("model", "!=", "")])
    return E.session_model_map(m)


def copied_call_ids(unit, splits):
    """call ids (not loader-made 'synthetic:' ids) that occur in more than one session of the unit's pooled splits."""
    seen = defaultdict(set)
    for sp in splits:
        if unit.startswith("swechat/"):
            c = E.read_cache("swechat", sp, ["session_id", "call_id"], filters=[("session_id", "in", unit_ids(unit, sp)),
                                                                                ("kind", "==", "call")])
        else:
            c = E.read_cache(unit, sp, ["session_id", "call_id"], filters=[("kind", "==", "call")])
        for s, ci in zip(c.session_id, c.call_id.astype(object)):
            if isinstance(ci, str) and not ci.startswith("synthetic:"):
                seen[ci].add(s)
    return frozenset(k for k, v in seen.items() if len(v) > 1)


def pair_info(u, copied):
    """Join-clean (AC3) keys, first-result truncation flag per call (AC2), paired calls per session (length tercile)."""
    uc = u[u.kind.isin(["call", "result"])][["session_id", "seq", "kind", "call_id", "ts"]]
    P = pc.make_pairs(uc)
    ok = E.join_clean_mask(uc, P, copied) if len(P) else np.zeros(0, dtype=bool)
    clean_keys = set(zip(P.session_id[ok], P.call_id.astype(str)[ok]))
    npairs = P.groupby("session_id").size()
    res = u[(u.kind == "result") & u.call_id.notna()].sort_values(["session_id", "seq"]).drop_duplicates(["session_id", "call_id"])
    trunc_call = {(s, str(c)): bool(E.truncated_result(t, x)) for s, c, t, x in
                  zip(res.session_id, res.call_id.astype(object), res.text.astype(object), res.extra.astype(object))}
    first_res_seq = dict(zip(zip(res.session_id, res.call_id.astype(str)), res.seq))
    return {"clean": clean_keys, "npairs": npairs, "trunc_call": trunc_call, "first_res_seq": first_res_seq,
            "n_pairs": int(len(P)), "n_clean": int(ok.sum())}


# ================================================================================================ Probe 4 walk
T_COLS = ["v", "sid", "seq", "idx", "origin", "pk", "src_all", "src_clean", "red", "trunc", "clean", "tool", "call_id"]


def p4_walk(unit, u, info, private):
    """Large-integer walk (mirrors probe_4.extract main/noredact/noredact_strict for T and M_all, and
    prereg_e_calibration.cal_round for the parameter classification). Returns occurrence table T (every call-arg large
    integer, sourced or not) and M rows (session, value, flags: 1 any result, 2 non-REDACTED result, 4 non-truncated
    result, 8 join-clean result)."""
    u = u[u.kind.isin(["user", "system", "call", "result"])]
    sids = u.session_id.to_numpy()
    seqs = u.seq.to_numpy()
    kinds = u.kind.astype(object).tolist()
    tools = u.tool.astype(object).tolist()
    traws = u.tool_raw.astype(object).tolist()
    cids = u.call_id.astype(object).tolist()
    argsl = u.args.astype(object).tolist()
    texts = u.text.astype(object).tolist()
    errs = u.stderr.astype(object).tolist()
    extras = u.extra.astype(object).tolist()
    n = len(u)
    T, M = [], []
    if n == 0:
        return pd.DataFrame(T, columns=T_COLS), pd.DataFrame(M, columns=["sid", "v", "flags"])
    starts = np.flatnonzero(np.r_[True, sids[1:] != sids[:-1]])
    ends = np.r_[starts[1:], n]
    for s0, e0 in zip(starts, ends):
        sid = sids[s0]
        anc_all, anc_clean = set(), set()
        mflags = defaultdict(int)
        for i in range(s0, e0):
            k = kinds[i]
            if k in ("result", "user", "system"):
                txt = texts[i] if isinstance(texts[i], str) else None
                pieces = [txt] + ([errs[i] if isinstance(errs[i], str) else None] if k == "result" else [])
                pieces = [p_ for p_ in pieces if p_]
                red = any("REDACTED" in p_ for p_ in pieces)
                vals = set()
                for t in pieces:
                    vals.update(pc.large_ints(t))
                anc_all |= vals
                if not red:
                    anc_clean |= vals
                if k == "result" and vals:
                    ci = cids[i] if isinstance(cids[i], str) else None
                    f = 1 | (0 if red else 2)
                    if not E.truncated_result(txt, extras[i]):
                        f |= 4
                    if ci is not None and (sid, ci) in info["clean"] and info["first_res_seq"].get((sid, ci)) == seqs[i]:
                        f |= 8
                    for v in vals:
                        mflags[v] |= f
            elif k == "call":
                a = argsl[i]
                if not isinstance(a, str):
                    continue
                occ = E.classify_args_ints(a)
                if not occ:
                    continue
                red = "REDACTED" in a
                tk = pc.tool_key(unit, tools[i] if isinstance(tools[i], str) else None,
                                 traws[i] if isinstance(traws[i], str) else None)
                if private:
                    tk = pc.private_key(tk)
                ci = cids[i] if isinstance(cids[i], str) else None
                tr = bool(info["trunc_call"].get((sid, ci), False)) if ci else False
                cl = bool(ci is not None and (sid, ci) in info["clean"])
                for idx, (v, origin, pk) in enumerate(occ):
                    T.append((v, sid, int(seqs[i]), idx, origin, pk, v in anc_all, v in anc_clean, red, tr, cl, tk, ci))
        for v, f in mflags.items():
            M.append((sid, v, f))
    return pd.DataFrame(T, columns=T_COLS), pd.DataFrame(M, columns=["sid", "v", "flags"])


def first_T(T, variant="main", mask=None):
    """First (sid, seq, idx) unsourced occurrence per value: probe_4's put() order. T must be sorted by (sid, seq, idx)."""
    m = np.ones(len(T), dtype=bool) if mask is None else np.asarray(mask, dtype=bool).copy()
    if variant == "main":
        m &= ~T.src_all.to_numpy(dtype=bool)
    elif variant == "noredact":
        m &= ~T.src_all.to_numpy(dtype=bool) & ~T.red.to_numpy(dtype=bool)
    elif variant == "noredact_strict":
        m &= ~T.src_clean.to_numpy(dtype=bool) & ~T.red.to_numpy(dtype=bool)
    return T[m].drop_duplicates("v", keep="first")


def first_M(M, bit=1, mask=None):
    m = (M["flags"].to_numpy() & bit) == bit
    if mask is not None:
        m &= np.asarray(mask, dtype=bool)
    return M[m].drop_duplicates("v", keep="first")


def rrow(F, sid_col="sid"):
    vals = F.v.tolist()
    sids = F[sid_col].tolist()
    row = {"distinct_values": len(vals), "sessions": len(set(sids))}
    if vals:
        row["round"] = {"last_0": p4.rate_cell(*p4.by_session([v.endswith("0") for v in vals], sids), TH4),
                        "last_000": p4.rate_cell(*p4.by_session([v.endswith("000") for v in vals], sids), TH4)}
    return row


def p_last0(row):
    return (row.get("round") or {}).get("last_0", {}).get("rate")


def rule(Trow, Mrow):
    lab, reason, dec = p4.round_verdict(Trow, Mrow, TH4)
    return {"label": lab, "reason": reason, "deciding": dec}


def f3_label(rule_lab, g, g_full):
    """followups.F3_round_numbers.verdict, applied mechanically."""
    if rule_lab == "INSUFFICIENT_N":
        return "INSUFFICIENT_N", "fewer than 100 distinct values from 10 sessions after exclusion: candidate capped at WEAK"
    if rule_lab == "DEAD":
        return "DEAD", "COLLAPSE: the round-number rule gives DEAD on T_orig_noparam"
    if g is None or g_full is None:
        return "INSUFFICIENT_N", "gap not computable"
    if g <= F3_COLLAPSE * g_full:
        return "DEAD", f"COLLAPSE: g {g:.4f} <= 0.25 x g_full {g_full:.4f} = {F3_COLLAPSE * g_full:.4f}"
    if rule_lab == "ALIVE" and g >= F3_KEEP_ALIVE * g_full:
        return "ALIVE", f"rule ALIVE and g {g:.4f} >= 0.5 x g_full {F3_KEEP_ALIVE * g_full:.4f}"
    return "WEAK", (f"rule {rule_lab}; g {g:.4f} vs 0.5 x g_full {F3_KEEP_ALIVE * g_full:.4f}: ALIVE not kept")


def exclusion_sets(T):
    """F3 exclusion sets over the occurrence table of the analysed population."""
    pk = T.pk.notna().to_numpy()
    lit = set(T.v[pk])                                              # any call-arg occurrence is a parameter
    cal = set(T.v[pk & ~T.src_all.to_numpy(dtype=bool)])            # any UNSOURCED occurrence (calibration code)
    return {"strict": lit, "strict_calibration_code": cal}


def round_block(T, M, swechat_cap, with_f3=True, t_mask=None, m_mask_bit=1, m_mask=None, detail=True):
    """Full statistic (T_orig vs M_all, Phase B rule, redaction cap for swechat units) and the F3 statistic on one
    population. T, M already restricted to the population's sessions."""
    Fm = first_T(T, "main", t_mask)
    Mf = first_M(M, m_mask_bit, m_mask)
    Trow, Mrow = rrow(Fm), rrow(Mf)
    full = rule(Trow, Mrow)
    out = {"T_orig": Trow, "M_all": Mrow, "full": full}
    pM = p_last0(Mrow)
    p_full = p_last0(Trow)
    g_full = (p_full - pM) if (p_full is not None and pM is not None) else None
    if swechat_cap and detail:
        Fn = first_T(T, "noredact", t_mask)
        Mn = first_M(M, 2 if m_mask_bit == 1 else (m_mask_bit | 2), m_mask)
        rr = rule(rrow(Fn), rrow(Mn))
        capped, note = p4.apply_redaction_cap(full["label"], rr["label"])
        out["full"]["redaction_rerun_noredact"] = {"label": rr["label"], "T_orig": rr["deciding"].get("T_orig_last0_k_n"),
                                                   "M_all": rr["deciding"].get("M_all_last0_k_n")}
        out["full"]["label_capped"] = capped
        out["full"]["redaction_cap"] = note
    else:
        out["full"]["label_capped"] = full["label"]
    out["g_full"] = g_full
    if not with_f3:
        return out
    ex = exclusion_sets(T)  # parameter status is a property of the analysed sessions' call args, not of the check filter
    variants = {"strict": ex["strict"], "strict_calibration_code": ex["strict_calibration_code"],
                "first_occurrence": set(Fm.v[Fm.pk.notna().to_numpy()])}
    f3 = {}
    for name, X in variants.items():
        keep = ~Fm.v.isin(X).to_numpy()
        Fr = Fm[keep]
        Rrow = rrow(Fr)
        rr = rule(Rrow, Mrow)
        p_np = p_last0(Rrow)
        g = (p_np - pM) if (p_np is not None and pM is not None) else None
        ent = {"excluded_values": int((~keep).sum()), "remaining": Rrow, "rule": rr, "g": g, "g_full": g_full,
               "g_over_g_full": (g / g_full) if (g is not None and g_full) else None,
               "collapse_threshold_0.25_g_full": (F3_COLLAPSE * g_full) if g_full is not None else None,
               "keep_alive_threshold_0.5_g_full": (F3_KEEP_ALIVE * g_full) if g_full is not None else None}
        lab_for_f3 = rr["label"]
        if swechat_cap and detail:
            Fn = first_T(T, "noredact", t_mask)
            Fn = Fn[~Fn.v.isin(X).to_numpy()]
            Mn = first_M(M, 2 if m_mask_bit == 1 else (m_mask_bit | 2), m_mask)
            rn = rule(rrow(Fn), rrow(Mn))
            capped, note = p4.apply_redaction_cap(rr["label"], rn["label"])
            ent["rule"]["redaction_rerun_noredact"] = {"label": rn["label"]}
            ent["rule"]["label_capped"] = capped
            ent["rule"]["redaction_cap"] = note
            lab_for_f3 = capped
        lab, why = f3_label(lab_for_f3, g, g_full)
        ent["f3_label"], ent["f3_reason"] = lab, why
        if detail and name == "strict":
            ent["excluded_by_param_kind"] = dict(Counter(
                str(k) for k in T[T.v.isin(set(Fm.v[~keep])) & T.pk.notna()].drop_duplicates(["v", "pk"]).pk))
            ent["excluded_by_origin_first_occurrence"] = dict(Counter(Fm[~keep].origin))
            ent["excluded_last0"] = {"k": int(Fm[~keep].v.str.endswith("0").sum()), "n": int((~keep).sum())}
        f3[name] = ent
    out["F3"] = f3
    out["F3_label"] = f3["strict"]["f3_label"]
    return out


# ================================================================================================ raw readers (AC1)
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


class CCIndex:
    """Raw Claude Code entries (also Claude Agent SDK content dicts): tool_use id -> (name, input, pos); tool_result id ->
    (is_error, text, pos); uuid -> (type, model-visible text, pos). First occurrence wins (resume copies). Nested
    agent_progress messages are visited (their own uuid)."""

    def __init__(self):
        self.uses, self.results, self.uu = {}, {}, {}
        self.received = []  # (pos, type, text) of every user/system/attachment entry (superset context)
        self.bad = 0

    def visit(self, e, pos):
        if not isinstance(e, dict):
            return
        typ = e.get("type")
        if typ == "progress":
            d = e.get("data") if isinstance(e.get("data"), dict) else {}
            if isinstance(d.get("message"), dict):
                self.visit(d["message"], pos)
            return
        uid = e.get("uuid") if isinstance(e.get("uuid"), str) else None
        msg = e.get("message") if isinstance(e.get("message"), dict) else {}
        content = msg.get("content") if msg else e.get("content")
        if typ == "assistant":
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") in ("tool_use", "server_tool_use") and isinstance(b.get("id"), str):
                        self.uses.setdefault(b["id"], (b.get("name"), b.get("input"), pos))
            if uid:
                self.uu.setdefault(uid, ("assistant", "", pos))
        elif typ == "user":
            parts = []
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_result":
                        t = raw_text(b.get("content"))
                        if isinstance(b.get("tool_use_id"), str):
                            self.results.setdefault(b["tool_use_id"], (b.get("is_error"), t, pos))
                        parts.append(t)
                    elif b.get("type") == "text":
                        parts.append(b.get("text") or "")
            txt = "\n".join(parts)
            if uid:
                self.uu.setdefault(uid, ("user", txt, pos))
            self.received.append((pos, "user", txt))
        elif typ == "system":
            txt = e.get("content") if isinstance(e.get("content"), str) else ""
            if uid:
                self.uu.setdefault(uid, ("system", txt, pos))
            self.received.append((pos, "system", txt))
        elif typ == "attachment":
            txt = json.dumps(e.get("attachment"), ensure_ascii=False) if e.get("attachment") is not None else ""
            if uid:
                self.uu.setdefault(uid, ("attachment", txt, pos))
            self.received.append((pos, "attachment", txt))

    @classmethod
    def from_files(cls, paths):
        ix = cls()
        pos = 0
        for p in paths:
            with open(p, encoding="utf-8", errors="replace") as f:
                for line in f:
                    objs = _parse_line(line)
                    if not objs and line.strip():
                        ix.bad += 1
                    for x in objs:
                        ix.visit(x, pos)
                    pos += 1
        return ix


def cc_local_paths(sid, agent_ids=()):
    """The session's root file-set (root main file + every JSONL under its directory) plus, for the given subagent ids,
    the agent-<id>.jsonl files of the same project directory found by FILE NAME (subagents of other family members
    live under the member's directory; agent ids are unique, so no other session's file is opened). Main files of
    other family members are not located (their names are not in the IR)."""
    mains = glob.glob(os.path.join(CC_LOCAL_ROOT, "*", f"{sid}.jsonl"))
    subs = []
    for m in mains:
        subs += glob.glob(os.path.join(m[:-6], "**", "*.jsonl"), recursive=True)
        proj = os.path.dirname(m)
        for aid in agent_ids:
            if isinstance(aid, str) and aid and all(ch.isalnum() or ch in "-_" for ch in aid):
                subs += glob.glob(os.path.join(proj, "**", f"agent-{aid}.jsonl"), recursive=True)
    return list(dict.fromkeys(mains + subs))


def aiv_cc_index(sdk_ids, want_ids):
    """One pass over the AI Village DB dump: rows of the given sdk sessions whose content carries a wanted uuid or
    tool id. pos = created_at order is not reconstructed here (lookups are by id only)."""
    ix = CCIndex()
    with gzip.open(AIV_CC_RAW, "rt", encoding="utf-8") as f:
        for line in f:
            if not any(s in line for s in sdk_ids):
                continue
            try:
                row = json.loads(line)
            except ValueError:
                ix.bad += 1
                continue
            if row.get("sdk_session_id") not in sdk_ids:
                continue
            c = row.get("content")
            if isinstance(c, str):
                try:
                    c = json.loads(c)
                except ValueError:
                    continue
            if not isinstance(c, dict):
                continue
            ids = {c.get("uuid")}
            msg = c.get("message") if isinstance(c.get("message"), dict) else {}
            cont = msg.get("content")
            if isinstance(cont, list):
                for b in cont:
                    if isinstance(b, dict):
                        ids.add(b.get("id"))
                        ids.add(b.get("tool_use_id"))
            if ids & want_ids:
                ix.visit(c, 0)
    return ix


def codex_raw(sid):
    """Codex rollout: calls {call_id: (args_text, pos)}, outputs {call_id: (text, pos)}, received [(pos, text)]."""
    calls, outs, rec = {}, {}, []
    p = E.SWE_TRANSCRIPTS / f"{sid}.jsonl"
    with open(p, encoding="utf-8", errors="replace") as f:
        for pos, line in enumerate(f):
            for x in _parse_line(line):
                if not isinstance(x, dict):
                    continue
                typ = x.get("type")
                pl = x.get("payload") if isinstance(x.get("payload"), dict) else {}
                if typ == "session_meta":
                    bi = pl.get("base_instructions")
                    t = bi.get("text") if isinstance(bi, dict) else (bi if isinstance(bi, str) else None)
                    if t:
                        rec.append((pos, t))
                elif typ == "compacted":
                    t = pl.get("message")
                    if isinstance(t, str):
                        rec.append((pos, t))
                elif typ == "response_item":
                    pt = pl.get("type")
                    if pt == "message":
                        txt = "\n".join(c.get("text") or "" for c in (pl.get("content") or []) if isinstance(c, dict))
                        if pl.get("role") in ("user", "developer", "system") or txt.startswith('{"author"'):
                            rec.append((pos, txt))
                    elif pt in ("function_call", "custom_tool_call"):
                        a = pl.get("arguments") if pt == "function_call" else pl.get("input")
                        calls.setdefault(pl.get("call_id"), (a if isinstance(a, str) else json.dumps(a), pos))
                    elif pt in ("function_call_output", "custom_tool_call_output"):
                        o = pl.get("output")
                        if isinstance(o, dict):
                            o = o.get("content") if isinstance(o.get("content"), str) else json.dumps(o)
                        elif isinstance(o, list):
                            o = raw_text(o)
                        o = o if isinstance(o, str) else ""
                        outs.setdefault(pl.get("call_id"), (o, pos))
                        rec.append((pos, o))
    return calls, outs, rec


def opencode_raw(sid):
    """OpenCode session doc: tool parts in order [(callID, tool, input, output_text, status, pos)], received [(pos, text)]."""
    doc = json.load(open(E.SWE_TRANSCRIPTS / f"{sid}.jsonl", encoding="utf-8"))
    tools, rec = [], []
    pos = 0
    for msg in doc.get("messages", []):
        info = msg.get("info") if isinstance(msg.get("info"), dict) else {}
        role = info.get("role")
        for pt in msg.get("parts") or []:
            if not isinstance(pt, dict):
                continue
            if pt.get("type") == "tool":
                st = pt.get("state") or {}
                o = st.get("output") if isinstance(st.get("output"), str) else (st.get("error") if isinstance(st.get("error"), str) else "")
                tools.append((pt.get("callID"), pt.get("tool"), st.get("input"), o, st.get("status"), pos))
                rec.append((pos + 0.5, o))  # output arrives after its own call
            elif pt.get("type") == "text" and role == "user":
                rec.append((pos, pt.get("text") or ""))
            pos += 1
    return tools, rec


def strings_of(obj):
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except ValueError:
            return [obj]
    strs, _ = pc.args_strings(json.dumps(obj))
    return strs


def key_in(text, key, ci):
    t = pc.norm_text(text or "")
    if ci:
        t = t.translate(p2.ASCII_LOWER)
    return p2.find_first(t, key, len(t) + 1, p2._ok_path) >= 0


# ================================================================================================ Probe 2 extraction
def p2_extract(unit, u, split):
    """probe_2.process_unit on one split, with the decision events' (session, call seq, path, key) recovered through the
    probe_2 debug hooks (in memory only). Also the session facts used by K1/K2 and the call lookup used by AC1-AC3."""
    kinds = ["user", "system", "call", "result"] + (["assistant"] if unit == "swechat/codex" else [])
    uu = u[u.kind.isin(kinds)]
    A = {"sessions": set(), "threads": {"main": set(), "sub": set()}, "refs": [], "access": [], "calls": Counter(),
         "calls_with_any_reference": Counter(), "calls_with": Counter(), "redacted_path": Counter(),
         "redacted_ref": Counter(), "redacted_ref_first": Counter(), "root_status": Counter()}
    p2.DEBUG, p2.DEBUG_ACCESS = [], []
    p2.process_unit(unit, uu, A)
    dbg, dba = p2.DEBUG, p2.DEBUG_ACCESS
    p2.DEBUG, p2.DEBUG_ACCESS = None, None
    R = p2.ref_frame(A["refs"])
    X = p2.acc_frame(A["access"])
    assert len(dbg) == len(R) and len(dba) == len(X), "debug hook misaligned"
    if len(R):
        assert all(d[2] == s and d[1] == st for d, s, st in zip(dbg, R.s, R.st))
        R["key"] = [d[4] for d in dbg]
        R["cseq"] = [int(d[5]) for d in dbg]
    if len(X):
        assert all(d[2] == s and d[1] == st and d[5] == (dd if dd >= 0 else None) for d, s, st, dd in
                   zip(dba, X.s, X.st, X.depth)), "access debug misaligned"
        X["p"] = [d[3] for d in dba]
        X["cseq"] = [int(d[4]) for d in dba]
    R["split"] = split
    X["split"] = split
    sub = u.is_subagent.astype("boolean").fillna(False).to_numpy(dtype=bool)
    calls = u[u.kind == "call"]
    csub = calls.is_subagent.astype("boolean").fillna(False).to_numpy(dtype=bool)
    has_main = set(calls.session_id[~csub])
    # call lookup: (session, seq) -> (call_id, tool_raw, agent_id, is_sub)
    cl = {(s, int(q)): (c if isinstance(c, str) else None, tr if isinstance(tr, str) else None,
                        ag if isinstance(ag, str) else None, bool(sb))
          for s, q, c, tr, ag, sb in zip(calls.session_id, calls.seq, calls.call_id.astype(object),
                                         calls.tool_raw.astype(object), calls.agent_id.astype(object), csub)}
    return {"R": R, "X": X, "has_main": has_main, "calls": cl, "sessions": set(u.session_id.unique()),
            "extraction": {"calls": dict(A["calls"]), "first_mentions": int(len(R)), "first_accesses": int(len(X)),
                           "sessions": len(A["sessions"]), "threads_with_calls": {k: len(v) for k, v in A["threads"].items()}},
            "_sub": sub}


def k2_events(unit, u):
    """K2 'record incomplete' sessions: compaction, context_clear, resume (Phase C HARNESS_DEFS subset, IR side;
    swechat Claude Code resume from the raw sessionId sequence; aiv_cc runs after the first of their SDK session)."""
    ev = defaultdict(set)
    sy = u[u.kind == "system"]
    for s, t, x in zip(sy.session_id, sy.text.astype(object), sy.extra.astype(object)):
        p_ = t.lstrip() if isinstance(t, str) else ""
        if p_.startswith("This session is being continued") or p_.startswith("<command-name>/compact"):
            ev[s].add("compaction")
        if "<command-name>/clear" in p_:
            ev[s].add("context_clear")
        if unit == "swechat/codex" and "role" not in pc.jl(x):
            ev[s].add("compaction")
    me = u[u.kind == "meta"]
    n_meta_sm = Counter()
    for s, x in zip(me.session_id, me.extra.astype(object)):
        xd = pc.jl(x)
        et, st, ty = xd.get("entry_type"), xd.get("subtype"), xd.get("type")
        if et == "system" and st in ("compact_boundary", "microcompact_boundary"):
            ev[s].add("compaction")
        if unit == "aiv_cc" and et == "system" and st == "status":
            ev[s].add("compaction")
        if unit == "swechat/codex":
            if et == "compacted" or ty == "context_compacted":
                ev[s].add("compaction")
            if et == "session_meta":
                n_meta_sm[s] += 1
        if unit == "swechat/opencode" and xd.get("part_type") == "compaction":
            ev[s].add("compaction")
    for s, c in n_meta_sm.items():
        if c > 1:
            ev[s].add("resume")
    if unit == "aiv_cc":
        for s in u.session_id.unique():
            if not s.endswith("/r000"):
                ev[s].add("resume")
    return ev


def raw_resume_cc(sids):
    """swechat Claude Code: a session whose raw entries carry more than one sessionId is a resume (HARNESS_DEFS
    'raw CC sessionId change'); read with prereg_e_common.raw_cc_entries."""
    out = set()
    for s in sids:
        seen = []
        for e in E.raw_cc_entries(s):
            if e[2] and (not seen or seen[-1] != e[2]):
                seen.append(e[2])
        if len(seen) > 1:
            out.add(s)
    return out


# ================================================================================================ Probe 2 statistics
def p2_frames(R, X, st):
    Xs = X[(X.st == st) & ~X.secondary]
    known = Xs[Xs.depth >= 0]
    succ = known[known.success]
    return R[(R.st == st) & (R.cls == "path")], succ


def p2_eval(unit, st, R, X, D, inst_ok):
    """S_deep and S_path_any exactly as probe_2.deep_block / stratum_block, verdict by probe_2.verdict."""
    P, succ = p2_frames(R, X, st)
    deep = succ[succ.depth >= D]
    sd = p2.crate(deep.uns, deep.s, min_den=1, min_sess=1) if len(deep) else {"k": 0, "n": 0, "n_sessions": 0}
    sa = p2.crate(P.uns, P.s, min_den=1, min_sess=1) if len(P) else {"k": 0, "n": 0, "n_sessions": 0}
    v = p2.verdict(unit, sd, sa, inst_ok, st)
    return {"S_deep": sd, "S_path_any": sa, "verdict": v, "label": v["verdict"], "deep": deep, "P": P}


def brief2(ev):
    v = ev["verdict"]
    return {"label": v["verdict"], "deciding_statistic": v.get("deciding_statistic"), "value": v.get("value"),
            "ci": v.get("ci"), "hi_used": v.get("hi_used"), "k": v.get("k"), "n": v.get("n"),
            "n_sessions": v.get("n_sessions"), "caps_applied": v.get("caps_applied"),
            "S_deep_k_n_s": [ev["S_deep"].get("k"), ev["S_deep"].get("n"), ev["S_deep"].get("n_sessions")],
            "S_path_any_k_n_s": [ev["S_path_any"].get("k"), ev["S_path_any"].get("n"), ev["S_path_any"].get("n_sessions")]}


def instrument(R, sids=None):
    S = R[(R.st == "main") & (R.cls == "symbol_ref")]
    if sids is not None:
        S = S[S.s.isin(sids)]
    r = p2.crate(S.uns, S.s)
    return {"S_symbol_ref": r, "ok": bool(r.get("rate") is not None and r["rate"] <= p2.T_INSTRUMENT)}


def deciding_frame(ev, stat):
    """Decision events of the deciding statistic: (frame, flag column)."""
    return (ev["deep"], "uns") if stat == "S_deep" else (ev["P"], "uns")


def p2_min_n(stat):
    return (p2.MIN_DEEP_N, p2.MIN_DEEP_S) if stat == "S_deep" else (p2.MIN_ANY_N, p2.MIN_ANY_S)


def label_simple(stat, D_):
    """Label of one decision-event frame under the deciding statistic only (strata): None if below min n."""
    mn, ms = p2_min_n(stat)
    if len(D_) < mn or D_.s.nunique() < ms:
        return None, {"k": int(D_.uns.sum()) if len(D_) else 0, "n": int(len(D_)), "n_sessions": int(D_.s.nunique()) if len(D_) else 0}
    r = p2.crate(D_.uns, D_.s, min_den=1, min_sess=1)
    rate, hi = p2.s_rate_with_hi(r)
    lab = p2.label_from(rate, hi)
    if stat == "S_path_any" and lab == "ALIVE":
        lab = "WEAK"
    return lab, {k: r.get(k) for k in ("k", "n", "n_sessions", "rate", "lo", "hi")}


# ================================================================================================ AC1 audits
def audit_p2(cand, unit, st, stat, ev, T2, ir_sessions):
    """AC1 for Probe 2. Numerator events = decision events flagged unsourced (S_deep: knowledge_from_nowhere deep first
    accesses; S_path_any: unsourced first-mention paths), B u E. Each is looked up in the raw source by call id; fields
    compared: the path in the raw call input, the raw result's error flag (S_deep only: first-try success), and the
    raw text of every earlier antecedent event of the same thread (results by call id, user/system by uuid) for the
    path key under the probe_2 match rule. Contribution changes if the raw call is missing or lacks the path, the raw
    result is missing or an error (S_deep), or the key occurs in a raw antecedent text."""
    D_, _ = deciding_frame(ev, stat)
    D_ = D_[D_.st == st]
    kcol = "key" if stat == "S_path_any" else "p"
    num = D_[D_.uns].sort_values(["split", "s", "cseq", kcol])
    if stat == "S_path_any":
        cis = num.ci.astype(bool).tolist()
    else:
        cis = [bool(p2.DRIVE.match(x)) for x in num.p]
    keys = list(zip(num.split, num.s, num.cseq, num[kcol], cis))
    sample = E.audit_sample(keys, seed_parts=("audit", "a1_p2_p4_f3", cand))
    rows = []
    by_s = defaultdict(list)
    for split, s, cseq, kv, ci_ in sample:
        by_s[(split, s)].append((cseq, kv, ci_))
    aiv_ix = None
    if unit == "aiv_cc":
        want, sdk = set(), set()
        for (split, s), lst in by_s.items():
            sdk.add(s.rsplit("/", 1)[0])
            g = ir_sessions[(split, s)]
            for cseq, _, _ in lst:
                cid, _, ag, sb = T2[split]["calls"][(s, cseq)]
                want.add(cid)
                thr = g[(g.seq < cseq) & g.kind.isin(["result", "user", "system"])]
                want |= set(x for x in thr.call_id.astype(object) if isinstance(x, str))
                want |= set(x for x in thr.uuid.astype(object) if isinstance(x, str))
        aiv_ix = aiv_cc_index(sdk, want)
    for (split, s), lst in by_s.items():
        g = ir_sessions[(split, s)]
        if unit in ("swechat/claude_code", "aiv_cc"):
            ix = aiv_ix if unit == "aiv_cc" else CCIndex.from_files([str(E.SWE_TRANSCRIPTS / f"{s}.jsonl")])
        for cseq, kv, ci in lst:
            cid, traw, ag, sb = T2[split]["calls"][(s, cseq)]
            key = pc.path_key(kv) if stat == "S_deep" else kv
            row = {"split": split, "session": s, "call_seq": cseq, "key": key, "stat": stat}
            gsub = g.is_subagent.astype("boolean").fillna(False).to_numpy(dtype=bool)
            gag = g.agent_id.astype(object).to_numpy()
            if sb:
                thr_mask = gsub & np.array([a == ag for a in gag])
            else:
                thr_mask = ~gsub
            ante = g[thr_mask & (g.seq.to_numpy() < cseq) & g.kind.isin(["result", "user", "system"]).to_numpy()]
            if unit in ("swechat/claude_code", "aiv_cc"):
                use = ix.uses.get(cid)
                row["call_found"] = use is not None
                row["path_in_raw_input"] = bool(use is not None and any(key_in(t, key, ci) for t in strings_of(use[1])))
                res = ix.results.get(cid)
                row["result_found"] = res is not None
                raw_err = None
                if res is not None:
                    raw_err = bool(pc.error_classes(unit, pc.tool_key(unit, None, traw), traw, res[1], None, res[0], None)[0])
                row["raw_error"] = raw_err
                hit, located, missing, txt_diff = [], 0, 0, 0
                for kd, ci_, uid, t_ir in zip(ante.kind, ante.call_id.astype(object), ante.uuid.astype(object),
                                              ante.text.astype(object)):
                    if kd == "result":
                        r_ = ix.results.get(ci_) if isinstance(ci_, str) else None
                        rt = r_[1] if r_ else None
                    else:
                        r_ = ix.uu.get(uid) if isinstance(uid, str) else None
                        rt = r_[1] if r_ else None
                    if rt is None:
                        missing += 1
                        continue
                    located += 1
                    if len(pc.norm_text(rt)) != len(pc.norm_text(t_ir if isinstance(t_ir, str) else "")):
                        txt_diff += 1
                    if key_in(rt, key, ci):
                        hit.append(kd)
                row.update({"antecedents_ir": int(len(ante)), "antecedents_located": located,
                            "antecedents_not_located": missing, "antecedent_text_length_differs": txt_diff,
                            "key_in_raw_antecedent": bool(hit), "key_in_raw_antecedent_kinds": dict(Counter(hit))})
                if unit == "swechat/claude_code" and use is not None:
                    cpos = use[2]
                    row["context_key_in_any_raw_received_text_before_call_any_thread"] = bool(
                        any(key_in(t, key, ci) for p_, _, t in ix.received if p_ < cpos))
            elif unit == "swechat/codex":
                calls, outs, rec = codex_raw(s)
                c = calls.get(cid)
                row["call_found"] = c is not None
                row["path_in_raw_input"] = bool(c is not None and any(key_in(t, key, ci) for t in strings_of(c[0])))
                o = outs.get(cid)
                row["result_found"] = o is not None
                row["raw_error"] = None
                if o is not None and stat == "S_deep":
                    row["raw_error"] = bool(pc.error_classes(unit, pc.tool_key(unit, None, traw), traw, o[0], None, None, None)[0])
                cpos = c[1] if c else None
                hit = [1 for p_, t in rec if cpos is not None and p_ < cpos and key_in(t, key, ci)]
                row.update({"antecedents_raw": sum(1 for p_, _ in rec if cpos is not None and p_ < cpos),
                            "key_in_raw_antecedent": bool(hit), "thread_is_whole_file": s not in T2[split]["has_main"]})
            elif unit == "swechat/opencode":
                tools, rec = opencode_raw(s)
                calls_s = g[g.kind == "call"].sort_values("seq")
                ordn = int((calls_s.seq < cseq).sum())
                idx = None
                if cid and not cid.startswith("synthetic:"):
                    idx = next((i for i, t in enumerate(tools) if t[0] == cid), None)
                elif 0 <= ordn < len(tools):
                    idx = ordn
                row["call_found"] = idx is not None
                if idx is not None:
                    tcall = tools[idx]
                    row["located_by"] = "callID" if (cid and not cid.startswith("synthetic:")) else "ordinal"
                    row["path_in_raw_input"] = bool(any(key_in(t, key, ci) for t in strings_of(tcall[2])))
                    row["result_found"] = True
                    row["raw_error"] = (tcall[4] == "error") if stat == "S_deep" else None
                    cpos = tcall[5]
                    hit = [1 for p_, t in rec if p_ < cpos and key_in(t, key, ci)]
                    row.update({"antecedents_raw": sum(1 for p_, _ in rec if p_ < cpos), "key_in_raw_antecedent": bool(hit),
                                "thread_is_whole_file": s not in T2[split]["has_main"]})
                else:
                    row.update({"path_in_raw_input": False, "result_found": False, "raw_error": None,
                                "key_in_raw_antecedent": False})
            chg = (not row.get("call_found")) or (not row.get("path_in_raw_input")) or row.get("key_in_raw_antecedent", False)
            if stat == "S_deep":
                chg = chg or (not row.get("result_found")) or bool(row.get("raw_error"))
            row["field_differs"] = bool(chg or row.get("antecedent_text_length_differs", 0) > 0)
            row["contribution_changed"] = bool(chg)
            rows.append(row)
    n_diff = sum(1 for r in rows if r["contribution_changed"])
    out = {"numerator_events": int(len(num)), "audited": len(rows), "seed_parts": ["audit", "a1_p2_p4_f3", cand],
           "call_found": sum(1 for r in rows if r.get("call_found")),
           "path_in_raw_input": sum(1 for r in rows if r.get("path_in_raw_input")),
           "raw_error": sum(1 for r in rows if r.get("raw_error")),
           "key_in_raw_antecedent": sum(1 for r in rows if r.get("key_in_raw_antecedent")),
           "field_differs": sum(1 for r in rows if r["field_differs"]), "contribution_changed": n_diff,
           "result": "FAIL" if n_diff >= E.AUDIT_FAIL else "PARSER_NOTE" if n_diff == 1 else "PASS", "rows": rows}
    if unit == "swechat/claude_code":
        out["context_key_in_any_raw_received_text_before_call_any_thread"] = sum(
            1 for r in rows if r.get("context_key_in_any_raw_received_text_before_call_any_thread"))
    if aiv_ix is not None:
        out["raw_bad_lines"] = aiv_ix.bad
    return out


def ints_of_input(inp):
    a = inp if isinstance(inp, str) else json.dumps(inp)
    return {v for v, _, _ in E.classify_args_ints(a)}


def audit_p4(cand, F_last0, ir_get, private):
    """AC1 for Probe 4. Numerator events = distinct T_orig values ending in 0 (first unsourced occurrence), B u E. Each
    is looked up in the raw source by call id; fields compared: the value among the raw call input's large integers,
    and its absence from the large integers of every earlier antecedent event of the session (results by call id,
    user/system by uuid). Contribution changes if the raw call is missing, lacks the value, or an antecedent carries
    it (the value would then be T_copy)."""
    keys = sorted(zip(F_last0.split, F_last0.unit, F_last0.sid, F_last0.seq, F_last0.call_id.astype(object), F_last0.v))
    sample = E.audit_sample(keys, seed_parts=("audit", "a1_p2_p4_f3", cand))
    rows = []
    by_s = defaultdict(list)
    for split, unit, sid, seq, cid, v in sample:
        by_s[(split, unit, sid)].append((seq, cid, v))
    for (split, unit, sid), lst in by_s.items():
        g = ir_get(split, unit, sid)
        if unit in ("swechat/claude_code", "cc_local"):
            if unit == "cc_local":
                aids = set(g.agent_id[g.seq.isin([q for q, _, _ in lst])].dropna().astype(str))
                paths = cc_local_paths(sid, sorted(aids))
            else:
                paths = [str(E.SWE_TRANSCRIPTS / f"{sid}.jsonl")]
            ix = CCIndex.from_files([p_ for p_ in paths if os.path.exists(p_)])
        for seq, cid, v in lst:
            row = {"split": split, "unit": unit}
            if not private:
                row.update({"session": sid, "call_seq": int(seq), "value": v})
            ante = g[(g.seq < seq) & g.kind.isin(["result", "user", "system"])]
            if unit in ("swechat/claude_code", "cc_local"):
                use = ix.uses.get(cid) if isinstance(cid, str) else None
                row["call_found"] = use is not None
                row["value_in_raw_input"] = bool(use is not None and v in ints_of_input(use[1]))
                hit, located, missing = [], 0, 0
                for kd, ci_, uid in zip(ante.kind, ante.call_id.astype(object), ante.uuid.astype(object)):
                    if kd == "result":
                        r_ = ix.results.get(ci_) if isinstance(ci_, str) else None
                    else:
                        r_ = ix.uu.get(uid) if isinstance(uid, str) else None
                    if r_ is None:
                        missing += 1
                        continue
                    located += 1
                    if v in set(pc.large_ints(r_[1])):
                        hit.append(kd)
                row.update({"antecedents_ir": int(len(ante)), "antecedents_located": located,
                            "antecedents_not_located": missing, "value_in_raw_antecedent": bool(hit)})
                if use is not None:
                    row["context_value_in_any_raw_received_text_before_call"] = bool(
                        any(v in set(pc.large_ints(t)) for p_, _, t in ix.received if p_ < use[2]))
            elif unit == "swechat/codex":
                calls, outs, rec = codex_raw(sid)
                c = calls.get(cid)
                row["call_found"] = c is not None
                row["value_in_raw_input"] = bool(c is not None and v in ints_of_input(c[0]))
                cpos = c[1] if c else -1
                row["value_in_raw_antecedent"] = bool(any(v in set(pc.large_ints(t)) for p_, t in rec if p_ < cpos))
            elif unit == "swechat/opencode":
                tools, rec = opencode_raw(sid)
                idx = None
                if cid and not str(cid).startswith("synthetic:"):
                    idx = next((i for i, t in enumerate(tools) if t[0] == cid), None)
                else:
                    calls_s = g[g.kind == "call"].sort_values("seq")
                    o_ = int((calls_s.seq < seq).sum())
                    idx = o_ if 0 <= o_ < len(tools) else None
                row["call_found"] = idx is not None
                row["value_in_raw_input"] = bool(idx is not None and v in ints_of_input(tools[idx][2]))
                cpos = tools[idx][5] if idx is not None else -1
                row["value_in_raw_antecedent"] = bool(any(v in set(pc.large_ints(t)) for p_, t in rec if p_ < cpos))
            else:
                row["format_not_implemented"] = True
            if row.get("format_not_implemented"):
                row["contribution_changed"] = None
            elif unit == "cc_local" and not row.get("call_found"):
                row["not_located_in_reachable_fileset"] = True  # another family member's main file (see cc_local_paths)
                row["contribution_changed"] = None
            else:
                row["contribution_changed"] = bool((not row.get("call_found")) or (not row.get("value_in_raw_input"))
                                                   or row.get("value_in_raw_antecedent"))
            rows.append(row)
    n_diff = sum(1 for r in rows if r["contribution_changed"])
    out = {"numerator_events": int(len(F_last0)), "audited": len(rows), "seed_parts": ["audit", "a1_p2_p4_f3", cand],
           "audited_by_unit": dict(Counter(r["unit"] for r in rows)),
           "format_not_implemented": sum(1 for r in rows if r.get("format_not_implemented")),
           "not_located_in_reachable_fileset": sum(1 for r in rows if r.get("not_located_in_reachable_fileset")),
           "audited_and_located": sum(1 for r in rows if r["contribution_changed"] is not None),
           "call_found": sum(1 for r in rows if r.get("call_found")),
           "value_in_raw_input": sum(1 for r in rows if r.get("value_in_raw_input")),
           "value_in_raw_antecedent": sum(1 for r in rows if r.get("value_in_raw_antecedent")),
           "context_value_in_any_raw_received_text_before_call": sum(
               1 for r in rows if r.get("context_value_in_any_raw_received_text_before_call")),
           "contribution_changed": n_diff,
           "result": "FAIL" if n_diff >= E.AUDIT_FAIL else "PARSER_NOTE" if n_diff == 1 else "PASS"}
    if not private:
        out["rows"] = rows
    return out


# ================================================================================================ AC4 helpers
def dom_summary(d, anon):
    return {"top_share_events": d.get("top_share_events"), "top_share_sessions": d.get("top_share_sessions"),
            "top_session_share_events": d.get("top_session_share_events"), "n_clusters": d.get("n_clusters"),
            "top_clusters": [(anon.get(c, c), se, ss) for c, se, ss in d.get("top_clusters", [])],
            "cluster_dominated": bool(d.get("total", 0) > 0 and max(d["top_share_events"], d["top_share_sessions"]) > E.DOM_SHARE),
            "session_dominated": bool(d.get("total", 0) > 0 and d["top_session_share_events"] > E.DOM_SESSION)}


def run_dominance(kinds, weights, recompute, ref_labels, anon_kinds, below_fn):
    """kinds: {kind: {session: cluster}}; weights: {name: {session: denominator events}}; recompute(drop_set) -> dict of
    labels per statistic; ref_labels: {stat: label}. Leave-out of the dominant cluster and the 5 largest clusters of a
    dominated kind (prereg_e.json artifact_checks.AC4_dominance)."""
    dom, leave = {}, []
    for kind, cmap in kinds.items():
        ent, top_lists = {}, []
        tot = Counter()
        for nm, wmap in weights.items():
            for s_, n_ in wmap.items():
                tot[cmap.get(s_, "unknown")] += n_
        allc = sorted(tot, key=lambda c_: (-tot[c_], str(c_)))
        anon = anon_rank(allc, kind) if kind in anon_kinds else {}
        for nm, wmap in weights.items():
            if not wmap:
                continue
            d = E.dominance(wmap, cmap)
            ent[nm] = dom_summary(d, anon)
            isdom = ent[nm]["session_dominated"] if kind == "session" else ent[nm]["cluster_dominated"]
            ent[nm]["dominated_on_this_kind"] = bool(isdom)
            if isdom:
                top_lists.append((nm, [c for c, _, _ in d["top_clusters"]], anon))
        ent["dominated"] = bool(top_lists)
        seen = set()
        for nm, order, anon in top_lists:
            for c in order[:5]:
                if c in seen:
                    continue
                seen.add(c)
                drop = {s for s, cc in cmap.items() if cc == c}
                labs = recompute(drop)
                below = below_fn(labs)
                drops = {st: bool(labs.get(st) in LEVEL and ref_labels.get(st) in LEVEL and LEVEL[labs[st]] < LEVEL[ref_labels[st]])
                         for st in ref_labels}
                leave.append({"kind": kind, "cluster": anon.get(c, c), "ranked_in": nm, "sessions_dropped": len(drop),
                              "labels": {k: v for k, v in labs.items() if not k.startswith("_")},
                              "detail": labs.get("_detail"), "below_min_n": bool(below),
                              "label_drop": bool(any(drops.values())), "label_drop_by_statistic": drops})
        dom[kind] = ent
    dominated_any = any(v["dominated"] for v in dom.values())
    drop_any = any(x["label_drop"] and not x["below_min_n"] for x in leave)
    below_any = any(x["below_min_n"] for x in leave)
    checks = []
    if drop_any:
        checks.append({"name": "AC4_DOMINATED", "effect": "downgrade"})
    if below_any:
        checks.append({"name": "AC4_UNTESTABLE_WITHOUT_DOMINANT", "effect": "cap_weak"})
    res = ("DOMINATED" if drop_any else "") + ((" + " if drop_any and below_any else "") +
                                               "UNTESTABLE_WITHOUT_DOMINANT" if below_any else "")
    res = res or ("PASS" if dominated_any else "NOT_DOMINATED")
    return {"kinds": dom, "dominated": dominated_any, "leave_outs": leave, "reference_labels": ref_labels,
            "DOMINATED": bool(drop_any), "UNTESTABLE_WITHOUT_DOMINANT": bool(below_any), "result": res}, checks


# ================================================================================================ P4 / F3 candidate
def p4_population(T, M, pops):
    return T[T.split.isin(pops)], M[M.split.isin(pops)]


def run_p4(cand, units, T, M, meta, t0):
    private = cand == "P4round/cc_local"
    has_e = not private
    swechat_cap = not private
    out = {"candidate": cand, "units": units if not private else ["cc_local"], "phase_b_label": PHASE_B[cand],
           "has_E": has_e, "labels": (["private (aggregates only)", "B only, unreplicated"] if private else
                                      (["pooled", "swechat/claude_code supplies most sessions: not independent evidence"]
                                       if "pooled" in cand else []))}
    pops = {"B": ["B"], "E": ["E"], "BuE": ["B", "E"]} if has_e else {"B": ["B"]}
    res = {}
    for name, sp in pops.items():
        Tp, Mp = p4_population(T, M, sp)
        res[name] = round_block(Tp, Mp, swechat_cap)
        res[name]["sessions_in_population"] = int(sum(len(meta["sessions"][x]) for x in sp))
        r = res[name]
        print(f"[{time.time() - t0:7.1f}s] {cand} {name}: full {r['full']['label_capped']} "
              f"T {r['T_orig']['round']['last_0'].get('k') if 'round' in r['T_orig'] else None}/"
              f"{r['T_orig']['distinct_values']} M {r['M_all']['round']['last_0'].get('rate') if 'round' in r['M_all'] else None} "
              f"F3 {r['F3_label']} remain {r['F3']['strict']['remaining']['distinct_values']}", flush=True)
    if not has_e:
        res["BuE"] = res["B"]
    out["populations"] = {k: v for k, v in res.items() if not (k == "BuE" and not has_e)}
    # ---- reproduction against the committed Phase B probe_4.json (B split)
    pb = json.load(open(ROOT / "analysis" / "out" / "probe_4.json", encoding="utf-8"))
    pbu = pb["pooled"]["swechat/*"] if "pooled" in cand else pb["units"][units[0]]
    rB = res["B"]

    def kn(row):
        c = (row.get("round") or {}).get("last_0", {})
        return [c.get("k"), c.get("n"), row.get("distinct_values"), row.get("sessions")]

    def kn_pb(row):
        c = row["round"]["last_0"]
        return [c.get("k"), c.get("n"), row.get("distinct_values"), row.get("sessions")]
    rep = {"T_orig_last0_k_n_distinct_sessions": [kn(rB["T_orig"]), kn_pb(pbu["ints"]["main"]["T_orig"])],
           "M_all_last0_k_n_distinct_sessions": [kn(rB["M_all"]), kn_pb(pbu["ints"]["main"]["M_all"])],
           "verdict": [rB["full"]["label_capped"], pbu["verdicts"]["round_numbers_secondary"]["verdict"]]}
    if swechat_cap:
        rep["T_orig_noredact_k_n"] = [rB["full"]["redaction_rerun_noredact"]["T_orig"],
                                      [pbu["ints"]["noredact"]["T_orig"]["round"]["last_0"]["k"],
                                       pbu["ints"]["noredact"]["T_orig"]["round"]["last_0"]["n"]]]
    if "pooled" not in cand:
        rep["T_orig_last0_ci"] = [[rB["T_orig"]["round"]["last_0"].get("lo"), rB["T_orig"]["round"]["last_0"].get("hi")],
                                  [pbu["ints"]["main"]["T_orig"]["round"]["last_0"].get("lo"),
                                   pbu["ints"]["main"]["T_orig"]["round"]["last_0"].get("hi")]]
    rep["all_match"] = bool(all(a == b for a, b in [rep["T_orig_last0_k_n_distinct_sessions"], rep["M_all_last0_k_n_distinct_sessions"],
                                                    rep["verdict"]] + ([rep["T_orig_noredact_k_n"]] if swechat_cap else [])))
    out["reproduction_B_vs_phase_b"] = rep
    # ---- replication label (Phase B statistic on E) and the F3 kill test
    e_label = res["E"]["full"]["label_capped"] if has_e else None
    running = e_label if (has_e and e_label in LEVEL) else PHASE_B[cand]
    f3_by_pop = {p: res[p]["F3_label"] for p in (["BuE", "E"] if has_e else ["B"])}
    f3_used = kill_label(f3_by_pop)
    f3_testable = [p for p, v in f3_by_pop.items() if v in LEVEL]
    k_checks = []
    if f3_used is None:
        k_checks.append({"name": "F3_INSUFFICIENT_N (parameter-confounded, residual untestable)", "effect": "cap_weak"})
        f3_result = "CAP_WEAK (INSUFFICIENT_N after exclusion)"
    elif f3_used == "DEAD":
        k_checks.append({"name": "F3_COLLAPSE (DEAD)", "effect": "kill"})
        f3_result = "KILL (gap collapses)"
    elif f3_used == "WEAK":
        k_checks.append({"name": "F3_ALIVE_not_kept (WEAK)", "effect": "cap_weak"})
        f3_result = "CAP_WEAK"
    else:
        f3_result = "PASS (ALIVE kept)"
    out["kill_tests"] = {"F3_parameter_exclusion": {
        "by_population": {p: {"f3_label": res[p]["F3_label"], "f3_reason": res[p]["F3"]["strict"]["f3_reason"],
                              "g": res[p]["F3"]["strict"]["g"], "g_full": res[p]["F3"]["strict"]["g_full"],
                              "remaining_distinct": res[p]["F3"]["strict"]["remaining"]["distinct_values"],
                              "remaining_sessions": res[p]["F3"]["strict"]["remaining"]["sessions"],
                              "excluded": res[p]["F3"]["strict"]["excluded_values"]} for p in f3_by_pop},
        "testable_populations": f3_testable, "label_used": f3_used, "result": f3_result,
        "variants_reported_not_deciding": {p: {v: res[p]["F3"][v]["f3_label"] for v in ("strict_calibration_code", "first_occurrence")}
                                           for p in f3_by_pop}}}
    killed = f3_used == "DEAD"
    ref_full = res["BuE"]["full"]["label"]
    ref_f3 = res["BuE"]["F3_label"]
    checks_min, other = [], list(k_checks)
    ac, strata = {}, {}
    if killed:
        out["line_stopped"] = "F3 kill test fired: the remaining checks were not run (brief: stop that line for that unit)"
        for k_ in ("AC1_parser", "AC2_truncation", "AC3_join", "AC4_dominance", "AC5_sampling"):
            ac[k_] = {"result": "NOT_RUN", "reason": "line stopped after the F3 kill"}
        strata = {"result": "NOT_RUN", "reason": "line stopped after the F3 kill"}
    else:
        Tb, Mb = p4_population(T, M, pops.get("BuE", ["B"]))
        Tb = Tb.reset_index(drop=True)
        Mb = Mb.reset_index(drop=True)
        # AC2 truncation: decision events from truncated results (M) / calls whose own result is truncated (T) dropped
        r2 = round_block(Tb, Mb, False, t_mask=~Tb.trunc.to_numpy(dtype=bool), m_mask_bit=4, detail=False)
        c, running = combine_min_checks("AC2_truncation", [("full", ref_full, r2["full"]["label"]), ("F3", ref_f3, r2["F3_label"])], running)
        ac["AC2_truncation"] = {"T_occurrences_dropped": int(Tb.trunc.sum()), "full": brief4(r2), "F3_label": r2["F3_label"],
                                "F3_g": r2["F3"]["strict"]["g"], "F3_g_full": r2["F3"]["strict"]["g_full"], **c}
        checks_min.append(c)
        # AC3 join
        r3 = round_block(Tb, Mb, False, t_mask=Tb.clean.to_numpy(dtype=bool), m_mask_bit=8, detail=False)
        c, running = combine_min_checks("AC3_join", [("full", ref_full, r3["full"]["label"]), ("F3", ref_f3, r3["F3_label"])], running)
        ac["AC3_join"] = {"T_occurrences_dropped": int((~Tb.clean).sum()), "full": brief4(r3), "F3_label": r3["F3_label"],
                          "F3_g": r3["F3"]["strict"]["g"], "F3_g_full": r3["F3"]["strict"]["g_full"],
                          **c}
        checks_min.append(c)
        print(f"[{time.time() - t0:7.1f}s] {cand}: AC2 {ac['AC2_truncation']['result']} AC3 {ac['AC3_join']['result']}", flush=True)
        # AC5 sampling
        Fm = first_T(Tb, "main")
        Mf = first_M(Mb, 1)
        if not private:
            sids_all = sorted(set().union(*[meta["sessions"][x] for x in pops.get("BuE", ["B"])]))
            wt = E.post_strat_weights("swechat", sids_all)
            w5 = weighted_round(Fm, Mf, wt, Tb)
            l5_full, l5_f3 = w5["full_label"], w5["F3_label"]
            c, running = combine_min_checks("AC5_sampling", [("full", ref_full, l5_full), ("F3", ref_f3, l5_f3)], running)
            wv = np.array([wt[s] for s in sids_all])
            ac["AC5_sampling"] = {"weights": {"sessions": len(sids_all), "min": float(wv.min()), "max": float(wv.max())}, **w5, **c}
            checks_min.append(c)
            # SHIFT: B point outside E CI (no verdict effect)
            tE = res["E"]["T_orig"].get("round", {}).get("last_0", {})
            tB = res["B"]["T_orig"].get("round", {}).get("last_0", {})
            ac["AC5_sampling"]["SHIFT_B_vs_E"] = {"T_orig_last0_B_point": tB.get("rate"), "E_ci": [tE.get("lo"), tE.get("hi")],
                                                  "SHIFT": bool(tE.get("lo") is not None and tB.get("rate") is not None and
                                                                not (tE["lo"] <= tB["rate"] <= tE["hi"]))}
        else:
            ac["AC5_sampling"] = {"result": "NOT_RUN", "reason": "no population table for cc_local (artifact_checks.AC5_sampling)"}
        # AC4 dominance
        sids = sorted(set(Tb.sid) | set(Mb.sid))
        kinds = p4_cluster_kinds(cand, units, sids, meta, private)
        weights = {"T_orig": Fm.groupby("sid").size().to_dict(), "M_all": Mf.groupby("sid").size().to_dict()}

        def recompute(drop):
            Tl = Tb[~Tb.sid.isin(drop)]
            Ml = Mb[~Mb.sid.isin(drop)]
            r = round_block(Tl, Ml, False, detail=False)
            return {"full": r["full"]["label"], "F3": r["F3_label"],
                    "_detail": {"T_orig": [r["T_orig"].get("distinct_values"), r["T_orig"].get("sessions"), p_last0(r["T_orig"])],
                                "M_all_last0": p_last0(r["M_all"]), "F3_remaining": r["F3"]["strict"]["remaining"]["distinct_values"],
                                "g": r["F3"]["strict"]["g"], "g_full": r["F3"]["strict"]["g_full"],
                                "collapse_threshold_0.25_g_full": r["F3"]["strict"]["collapse_threshold_0.25_g_full"],
                                "F3_reason": r["F3"]["strict"]["f3_reason"]}}
        ac4, ac4_checks = run_dominance(kinds, weights, recompute, {"full": ref_full, "F3": ref_f3},
                                        anon_kinds=("session", "repo", "user"),
                                        below_fn=lambda labs: any(labs.get(st_) == "INSUFFICIENT_N" and ref_ in LEVEL
                                                                  for st_, ref_ in (("full", ref_full), ("F3", ref_f3))))
        ac["AC4_dominance"] = {"denominator": "distinct T_orig values (first-occurrence session) and distinct M_all values, "
                                              "each tested; a leave-out removes the cluster's sessions from both", **ac4}
        other += ac4_checks
        print(f"[{time.time() - t0:7.1f}s] {cand}: AC4 {ac4['result']} ({len(ac4['leave_outs'])} leave-outs)", flush=True)
        # AC1 parser
        F_last0 = Fm[Fm.v.str.endswith("0")]
        ac["AC1_parser"] = audit_p4(cand, F_last0, meta["ir_get"], private)
        if ac["AC1_parser"]["result"] == "FAIL":
            other.append({"name": "AC1_parser_FAIL", "effect": "downgrade"})
        print(f"[{time.time() - t0:7.1f}s] {cand}: AC1 {ac['AC1_parser']['result']} "
              f"({ac['AC1_parser']['contribution_changed']}/{ac['AC1_parser']['audited']})", flush=True)
        # stratification
        strata = p4_strata(cand, units, Tb, Mb, kinds, meta, private)
        if strata["confined_axes_any"]:
            other.append({"name": "CONFINED on " + ", ".join(strata["confined_axes_any"]), "effect": "downgrade"})
        print(f"[{time.time() - t0:7.1f}s] {cand}: strata {strata['confinement']}", flush=True)
    checks = checks_min + other
    status, final, reasons = E.survival_status(PHASE_B[cand], e_label, checks, has_e=has_e)
    out["artifact_checks"] = ac
    out["stratification"] = strata
    out["survival"] = {"phase_b_label": PHASE_B[cand], "E_label": e_label, "BuE_label_full_statistic": ref_full,
                       "BuE_F3_label": ref_f3, "checks_in_order": checks, "status": status, "final_label": final,
                       "reasons": reasons, "final_label_other_order": alt_order(PHASE_B[cand], e_label, checks_min, other, has_e)}
    return out


def brief4(r):
    t = (r["T_orig"].get("round") or {}).get("last_0", {})
    m = (r["M_all"].get("round") or {}).get("last_0", {})
    return {"label": r["full"]["label"], "T_orig_last0": [t.get("k"), t.get("n"), t.get("rate"), t.get("lo"), t.get("hi")],
            "T_orig_sessions": r["T_orig"].get("sessions"),
            "M_all_last0": [m.get("k"), m.get("n"), m.get("rate"), m.get("lo"), m.get("hi")], "g_full": r.get("g_full")}


def weighted_round(Fm, Mf, wt, Tb):
    """AC5 for the round-number statistic: post-stratified ratio estimator per class (weighted_cluster_rate), the Phase B
    rule on the weighted rates/CIs (min n from the unweighted counts), and the F3 rule on the weighted gap."""
    def wrate(F):
        g = F.assign(l0=F.v.str.endswith("0")).groupby("sid").agg(n=("v", "size"), k=("l0", "sum"))
        return E.weighted_cluster_rate(g.k.to_numpy(), g.n.to_numpy(), np.array([wt.get(s, 0.0) for s in g.index]))
    tw, mw = wrate(Fm), wrate(Mf)
    X = exclusion_sets(Tb)["strict"]
    Fr = Fm[~Fm.v.isin(X)]
    rw = wrate(Fr) if len(Fr) else {"rate": None}

    def lab(trow_w, n_vals, n_sess):
        if n_vals < TH4["round_min_values"] or n_sess < TH4["round_min_sessions"] or trow_w.get("rate") is None:
            return "INSUFFICIENT_N"
        if trow_w["lo"] > mw["hi"] + TH4["round_margin"]:
            return "ALIVE"
        if trow_w["rate"] > mw["hi"]:
            return "WEAK"
        return "DEAD"
    lf = lab(tw, len(Fm), Fm.sid.nunique())
    lr = lab(rw, len(Fr), Fr.sid.nunique() if len(Fr) else 0)
    g_full = (tw["rate"] - mw["rate"]) if tw.get("rate") is not None else None
    g = (rw["rate"] - mw["rate"]) if rw.get("rate") is not None else None
    f3l, why = f3_label(lr, g, g_full)
    return {"weighted_T_orig_last0": tw, "weighted_M_all_last0": mw, "weighted_T_noparam_last0": rw,
            "full_label": lf, "F3_rule_label": lr, "F3_label": f3l, "F3_reason": why, "g": g, "g_full": g_full}


def p4_cluster_kinds(cand, units, sids, meta, private):
    kinds = {}
    if private:
        kinds["repo"] = norm_clusters({s: meta["stratum"].get(s, "unknown") for s in sids})
    else:
        fr = pd.DataFrame({"session_id": sids})
        kinds["repo"] = norm_clusters(E.session_cluster_map("swechat", fr, "repo"))
        kinds["user"] = norm_clusters(E.session_cluster_map("swechat", fr, "user"))
    kinds["model"] = {s: meta["model"].get(s, "unknown") for s in sids}
    kinds["session"] = {s: s for s in sids}
    return kinds


def p4_strata(cand, units, Tb, Mb, kinds, meta, private):
    """Four axes (prereg_e.json stratification). Tool: T restricted to call occurrences of one tool_key (first
    occurrence within it), M_all whole. Model / repo / length: T and M restricted to the stratum's sessions. A stratum is
    reportable if T and M meet the round-number min n (100 distinct values from 10 sessions). Labels: the Phase B rule
    (candidate statistic) and the F3 label."""
    axes = {}
    tools = Tb[~Tb.src_all].tool.value_counts()
    ax = {}
    for k in tools.index:
        r = round_block(Tb, Mb, False, t_mask=(Tb.tool == k).to_numpy(), detail=False)
        rep = r["full"]["label"] != "INSUFFICIENT_N"
        ax[str(k)] = {"T_orig": [r["T_orig"].get("distinct_values"), r["T_orig"].get("sessions"), p_last0(r["T_orig"])],
                      "label_full": r["full"]["label"] if rep else None, "label_F3": r["F3_label"] if rep and r["F3_label"] in LEVEL else None,
                      "F3_remaining": r["F3"]["strict"]["remaining"]["distinct_values"]}
    axes["tool"] = ax
    terc = {}
    for u_ in units:
        cuts = PJ["resolved"]["length_terciles_A"][u_]["cuts"] if "cuts" in PJ["resolved"]["length_terciles_A"].get(u_, {}) else None
        if cuts is None:
            continue
        terc.update(E.length_tercile_map({s: n for s, n in meta["npairs"].items() if meta["unit_of"].get(s) == u_}, cuts))
    for axis, cmap in (("model", kinds["model"]), ("repo", kinds["repo"]), ("length", terc)):
        groups = defaultdict(set)
        for s, cv in cmap.items():
            groups[cv].add(s)
        ordered = sorted(groups, key=lambda c: -len(groups[c]))
        anon = anon_rank(ordered, axis) if (axis == "repo" or (private and axis == "repo")) else {}
        ax = {}
        for cv in ordered:
            ss = groups[cv]
            r = round_block(Tb[Tb.sid.isin(ss)], Mb[Mb.sid.isin(ss)], False, detail=False)
            rep = r["full"]["label"] != "INSUFFICIENT_N"
            ax[anon.get(cv, cv)] = {"sessions": len(ss), "T_orig": [r["T_orig"].get("distinct_values"), r["T_orig"].get("sessions"),
                                                                     p_last0(r["T_orig"])],
                                    "label_full": r["full"]["label"] if rep else None,
                                    "label_F3": r["F3_label"] if rep and r["F3_label"] in LEVEL else None,
                                    "F3_remaining": r["F3"]["strict"]["remaining"]["distinct_values"]}
        axes[axis] = ax
    conf = {}
    confined_any = []
    for axis, ax in axes.items():
        cf = E.confinement({k: v["label_full"] for k, v in ax.items()})
        c3 = E.confinement({k: v["label_F3"] for k, v in ax.items()})
        conf[axis] = {"full": cf, "F3": c3,
                      "reportable_full": sum(1 for v in ax.values() if v["label_full"] in LEVEL),
                      "reportable_F3": sum(1 for v in ax.values() if v["label_F3"] in LEVEL)}
        if "CONFINED" in (cf, c3):
            confined_any.append(axis)
    return {"axes": axes, "confinement": conf, "confined_axes_any": confined_any,
            "reportable_rule": "T_orig and M_all >= 100 distinct values from >= 10 sessions in the stratum (round-number "
                               "min n); F3 label reportable only where the remaining values also meet it"}


# ================================================================================================ P2 candidate
def run_p2(cand, unit, st, T2, t0):
    has_e = unit != "aiv_cc"
    D = p2.D_UNIT[unit]
    splits = ["B", "E"] if has_e else ["B"]
    R = pd.concat([T2[sp]["R"] for sp in splits], ignore_index=True)
    X = pd.concat([T2[sp]["X"] for sp in splits], ignore_index=True)
    out = {"candidate": cand, "unit": unit, "stratum": st, "phase_b_label": PHASE_B[cand], "has_E": has_e, "D_unit": D,
           "labels": (["single-agent case study", "B only, unreplicated", "antecedents incomplete (prereg probe2.units)"]
                      if unit == "aiv_cc" else [])}
    pops = {"B": ["B"], "E": ["E"], "BuE": ["B", "E"]} if has_e else {"B": ["B"]}
    inst_cc = T2.get("_instrument", {})
    res = {}
    for name, sp in pops.items():
        Rp, Xp = R[R.split.isin(sp)], X[X.split.isin(sp)]
        ok = inst_cc.get(name, {}).get("ok", True)
        ev = p2_eval(unit, st, Rp, Xp, D, ok)
        res[name] = ev
        print(f"[{time.time() - t0:7.1f}s] {cand} {name}: {brief2(ev)['label']} {brief2(ev)['deciding_statistic']} "
              f"{brief2(ev)['k']}/{brief2(ev)['n']} s{brief2(ev)['n_sessions']}", flush=True)
    if not has_e:
        res["BuE"] = res["B"]
    out["populations"] = {k: brief2(v) for k, v in res.items() if not (k == "BuE" and not has_e)}
    # full Phase B stratum block for B u E and E (context: per-class sourcing, depth, sensitivity variants)
    for name in (["BuE", "E"] if has_e else ["B"]):
        sp = pops[name]
        b, _, _ = p2.stratum_block(unit, st, R[R.split.isin(sp)].drop(columns=["key", "cseq", "split"], errors="ignore"),
                                   X[X.split.isin(sp)].drop(columns=["p", "cseq", "split"], errors="ignore"), D, False)
        b.pop("_sd", None)
        b.pop("_sa", None)
        out.setdefault("stratum_block", {})[name] = b
    # reproduction vs the committed probe_2.json (B)
    pb = json.load(open(ROOT / "analysis" / "out" / "probe_2.json", encoding="utf-8"))["verdicts"][unit][st]
    mine = brief2(res["B"])
    out["reproduction_B_vs_phase_b"] = {"label": [mine["label"], pb["verdict"]],
                                        "deciding_statistic": [mine["deciding_statistic"], pb.get("deciding_statistic")],
                                        "k_n_sessions": [[mine["k"], mine["n"], mine["n_sessions"]], [pb.get("k"), pb.get("n"), pb.get("n_sessions")]],
                                        "ci": [mine["ci"], pb.get("ci")]}
    rp = out["reproduction_B_vs_phase_b"]
    rp["all_match"] = bool(rp["label"][0] == rp["label"][1] and rp["k_n_sessions"][0] == rp["k_n_sessions"][1]
                           and rp["deciding_statistic"][0] == rp["deciding_statistic"][1])
    e_label = res["E"]["label"] if has_e else None
    stat = res["BuE"]["verdict"].get("deciding_statistic")
    ref = res["BuE"]["label"]
    running = e_label if (has_e and e_label in LEVEL) else PHASE_B[cand]
    checks_min, other = [], []
    ac, kills, strata = {}, {}, {}
    stop = None
    if has_e and e_label == "DEAD":
        stop = "E verdict DEAD (KILLED by the survival rule)"
    # ---------------------------------------------------------------- K1 strict root rule
    if stop is None:
        k1 = {"rule": "deep_first_try.depth with the pre-registered root rule only: a sub-agent thread in a session with no "
                      "main-thread calls takes the (absent) main-thread root, so its absolute access paths are depth_unknown"}
        aff = (X.st == "sub") & ~X.s.isin(set().union(*[T2[sp]["has_main"] for sp in splits])) & \
            np.array([pc.is_absolute(p_) if isinstance(p_, str) else False for p_ in X.p])
        Xs = X.copy()
        Xs.loc[aff.to_numpy(), "depth"] = -1
        k1["access_rows_affected"] = int(aff.sum())
        k1["access_rows_affected_this_stratum"] = int((aff & (X.st == st)).sum())
        labs = {}
        for name, sp in pops.items():
            ok = inst_cc.get(name, {}).get("ok", True)
            ev = p2_eval(unit, st, R[R.split.isin(sp)], Xs[Xs.split.isin(sp)], D, ok)
            k1[name] = brief2(ev)
            labs[name] = ev["label"]
        used = kill_label({k: v for k, v in labs.items() if k in (["BuE", "E"] if has_e else ["B"])})
        k1["label_used"] = used
        if used == "DEAD":
            k1["result"] = "KILL (rule-sensitive)"
            other.append({"name": "P2_K1_root_rule (rule-sensitive)", "effect": "kill"})
            stop = "K1 kill test fired"
        else:
            k1["result"] = "PASS"
        kills["K1_root_rule"] = k1
        print(f"[{time.time() - t0:7.1f}s] {cand}: K1 {k1['result']} affected {k1['access_rows_affected_this_stratum']}", flush=True)
    # ---------------------------------------------------------------- K2 complete records (reported only)
    if stop is None:
        ev_s = T2["_k2"]
        flagged = {s for s, v in ev_s.items() if v & set(K2_TYPES)}
        k2 = {"note": "reported only (a1.P2_common.kills.K2_context_loss: no_rescue)",
              "sessions_flagged_by_type": dict(Counter(t for v in ev_s.values() for t in v if t in K2_TYPES))}
        for name, sp in pops.items():
            Rp, Xp = R[R.split.isin(sp)], X[X.split.isin(sp)]
            ok = inst_cc.get(name, {}).get("ok", True)
            ev = p2_eval(unit, st, Rp[~Rp.s.isin(flagged)], Xp[~Xp.s.isin(flagged)], D, ok)
            D_, _ = deciding_frame(res[name], stat)
            k2[name] = {"recomputed": brief2(ev), "decision_sessions": int(D_.s.nunique()) if len(D_) else 0,
                        "decision_sessions_flagged": int(D_.s.isin(flagged).groupby(D_.s).first().sum()) if len(D_) else 0}
        kills["K2_context_loss"] = k2
    # ---------------------------------------------------------------- artifact checks
    if stop is None:
        sp_bue = pops.get("BuE", ["B"])
        Rb, Xb = R[R.split.isin(sp_bue)].reset_index(drop=True), X[X.split.isin(sp_bue)].reset_index(drop=True)
        ok_b = inst_cc.get("BuE", {}).get("ok", True)

        def ev_with(Rx, Xx):
            return p2_eval(unit, st, Rx, Xx, D, ok_b)
        # call-level flags for AC2 / AC3
        def flags(df, col):
            return np.array([T2[sp]["call_flags"].get((s, int(q)), {}).get(col, False) for sp, s, q in zip(df.split, df.s, df.cseq)],
                            dtype=bool)
        tr_R, tr_X = flags(Rb, "trunc"), flags(Xb, "trunc")
        cl_R, cl_X = flags(Rb, "clean"), flags(Xb, "clean")
        e2 = ev_with(Rb[~tr_R], Xb[~tr_X])
        c, running = min_check("AC2_truncation", ref, e2["label"], running)
        D0, _ = deciding_frame(res["BuE"], stat)
        ac["AC2_truncation"] = {"decision_events_dropped": int(flags(D0, "trunc").sum()), "recomputed": brief2(e2), **c}
        checks_min.append(c)
        e3 = ev_with(Rb[cl_R], Xb[cl_X])
        c, running = min_check("AC3_join", ref, e3["label"], running)
        ac["AC3_join"] = {"copied_call_ids_in_pool": T2["_copied_n"], "decision_events_dropped": int((~flags(D0, "clean")).sum()),
                          "recomputed": brief2(e3), **c}
        checks_min.append(c)
        # AC5
        D_, _ = deciding_frame(res["BuE"], stat)
        if unit.startswith("swechat/"):
            sids_all = sorted(set().union(*[T2[sp]["sessions"] for sp in sp_bue]))
            wt = E.post_strat_weights("swechat", sids_all)
            g = D_.groupby("s").agg(n=("uns", "size"), k=("uns", "sum"))
            wr = E.weighted_cluster_rate(g.k.to_numpy(), g.n.to_numpy(), np.array([wt.get(s, 0.0) for s in g.index]))
            mn, ms = p2_min_n(stat)
            if len(D_) < mn or D_.s.nunique() < ms or wr.get("rate") is None:
                l5 = "INSUFFICIENT_N"
            else:
                l5 = p2.label_from(wr["rate"], wr["hi"])
                if stat == "S_path_any" and l5 == "ALIVE":
                    l5 = "WEAK"
            c, running = min_check("AC5_sampling", ref, l5, running)
            ac["AC5_sampling"] = {"weighted": wr, "label": l5, "weights_sessions": len(sids_all), **c}
            checks_min.append(c)
            eE, eB = res["E"]["verdict"], res["B"]["verdict"]
            if eE.get("ci") and eE["ci"][0] is not None and eB.get("value") is not None and eE.get("deciding_statistic") == eB.get("deciding_statistic"):
                ac["AC5_sampling"]["SHIFT_B_vs_E"] = {"B_point": eB["value"], "E_ci": eE["ci"],
                                                      "SHIFT": bool(not (eE["ci"][0] <= eB["value"] <= eE["ci"][1]))}
        else:
            ac["AC5_sampling"] = {"result": "NOT_RUN", "reason": "no population table for aiv_cc (artifact_checks.AC5_sampling)"}
        print(f"[{time.time() - t0:7.1f}s] {cand}: AC2 {ac['AC2_truncation']['result']} AC3 {ac['AC3_join']['result']} "
              f"AC5 {ac['AC5_sampling'].get('result')}", flush=True)
        # AC4
        sids = sorted(set(D_.s))
        kinds = {}
        if unit.startswith("swechat/"):
            fr = pd.DataFrame({"session_id": sids})
            kinds["repo"] = norm_clusters(E.session_cluster_map("swechat", fr, "repo"))
            kinds["user"] = norm_clusters(E.session_cluster_map("swechat", fr, "user"))
        kinds["model"] = {s: T2["_model"].get(s, "unknown") for s in sids}
        kinds["session"] = {s: s for s in sids}
        weights = {stat: D_.groupby("s").size().to_dict()}

        def recompute(drop):
            ev = ev_with(Rb[~Rb.s.isin(drop)], Xb[~Xb.s.isin(drop)])
            b = brief2(ev)
            lab = ev["label"]
            if lab == "INCONCLUSIVE":  # antecedents-incomplete cap; the drop test reads the label before the cap
                lab = ev["verdict"].get("label_before_caps")
            return {stat: lab, "_detail": {"deciding": b["deciding_statistic"], "k": b["k"], "n": b["n"],
                                           "n_sessions": b["n_sessions"], "value": b["value"], "label_after_caps": ev["label"]},
                    "_below": ev["label"] == "INSUFFICIENT_N" or b["deciding_statistic"] != stat}
        ac4, ac4_checks = run_dominance(kinds, weights, recompute, {stat: ref}, anon_kinds=("session", "repo", "user"),
                                        below_fn=lambda labs: labs.get("_below", False))
        for x in ac4["leave_outs"]:
            x["labels"].pop("_below", None)
        if unit == "aiv_cc":
            ac4["aiv_cc_note"] = "one agent: the repo/agent cluster is always dominated (label only, artifact_checks.AC4_dominance)"
        ac4["result_if_INCONCLUSIVE_leave_outs_not_counted"] = (
            "DOMINATED" if any(x["label_drop"] and not x["below_min_n"] and (x.get("detail") or {}).get("label_after_caps") != "INCONCLUSIVE"
                               for x in ac4["leave_outs"]) else ("UNTESTABLE_WITHOUT_DOMINANT" if ac4["UNTESTABLE_WITHOUT_DOMINANT"] else
                                                                 ("PASS" if ac4["dominated"] else "NOT_DOMINATED")))
        ac["AC4_dominance"] = {"denominator": f"{stat} decision events of the stratum", **ac4}
        other += ac4_checks
        print(f"[{time.time() - t0:7.1f}s] {cand}: AC4 {ac4['result']} ({len(ac4['leave_outs'])} leave-outs)", flush=True)
        # AC1
        ac["AC1_parser"] = audit_p2(cand, unit, st, stat, res["BuE"], T2, T2["_ir_sessions"])
        if ac["AC1_parser"]["result"] == "FAIL":
            other.append({"name": "AC1_parser_FAIL", "effect": "downgrade"})
        print(f"[{time.time() - t0:7.1f}s] {cand}: AC1 {ac['AC1_parser']['result']} "
              f"({ac['AC1_parser']['contribution_changed']}/{ac['AC1_parser']['audited']})", flush=True)
        # stratification
        axes = {}
        if stat == "S_deep":
            tool_frames = {t: g for t, g in D_.groupby("tool")}
        else:
            tool_frames = {t: g for t, g in D_.groupby("tool")}
        axes["tool"] = {}
        for t, g in tool_frames.items():
            lab, r = label_simple(stat, g)
            axes["tool"][str(t)] = {"label": lab, **r}
        terc = E.length_tercile_map(T2["_npairs"], PJ["resolved"]["length_terciles_A"][unit]["cuts"])
        for axis, cmap in (("model", kinds["model"]), ("repo", kinds.get("repo")), ("length", terc)):
            if cmap is None:
                axes[axis] = {"_untestable": "no repo field (aiv_cc: one agent)"}
                continue
            groups = defaultdict(set)
            for s in sids:
                groups[cmap.get(s, "unknown")].add(s)
            ordered = sorted(groups, key=lambda c_: -int(D_.s.isin(groups[c_]).sum()))
            anon = anon_rank(ordered, axis) if axis == "repo" else {}
            axes[axis] = {}
            for cv in ordered:
                lab, r = label_simple(stat, D_[D_.s.isin(groups[cv])])
                axes[axis][anon.get(cv, cv)] = {"label": lab, **r}
        conf = {}
        conf_axes = []
        for axis, ax in axes.items():
            labs = {k: v.get("label") for k, v in ax.items() if not k.startswith("_")}
            cf = E.confinement(labs) if labs else "UNTESTABLE"
            conf[axis] = {"status": cf, "reportable": sum(1 for v in labs.values() if v in LEVEL),
                          "signal_bearing": sum(1 for v in labs.values() if v in LEVEL and LEVEL[v] >= 1)}
            if cf == "CONFINED":
                conf_axes.append(axis)
        if conf_axes:
            other.append({"name": "CONFINED on " + ", ".join(conf_axes), "effect": "downgrade"})
        strata = {"axes": axes, "confinement": conf, "confined_axes": conf_axes,
                  "reportable_rule": f"{stat} decision events in the stratum meet the {stat} min n "
                                     f"({p2_min_n(stat)[0]} from {p2_min_n(stat)[1]} sessions); label = the probe2 rule on "
                                     f"{stat} (S_path_any capped at WEAK), before the antecedents-incomplete cap (a DEAD "
                                     f"stratum of aiv_cc would read INCONCLUSIVE: it is reportable and not signal-bearing)"}
        print(f"[{time.time() - t0:7.1f}s] {cand}: strata {conf}", flush=True)
    if stop is not None:
        out["line_stopped"] = stop + ": the remaining checks were not run (brief: stop that line for that unit)"
        for k_ in ("AC1_parser", "AC2_truncation", "AC3_join", "AC4_dominance", "AC5_sampling"):
            ac.setdefault(k_, {"result": "NOT_RUN", "reason": stop})
        if not strata:
            strata = {"result": "NOT_RUN", "reason": stop}
    out["instrument_check"] = {k: {"S_symbol_ref": {kk: v["S_symbol_ref"].get(kk) for kk in ("k", "n", "n_sessions", "rate", "lo", "hi")},
                                   "ok": v["ok"]} for k, v in inst_cc.items()}
    out["kill_tests"] = kills
    out["artifact_checks"] = ac
    out["stratification"] = strata
    checks = checks_min + other
    status, final, reasons = E.survival_status(PHASE_B[cand], e_label, checks, has_e=has_e)
    out["survival"] = {"phase_b_label": PHASE_B[cand], "E_label": e_label, "BuE_label": ref, "deciding_statistic_BuE": stat,
                       "checks_in_order": checks, "status": status, "final_label": final, "reasons": reasons,
                       "final_label_other_order": alt_order(PHASE_B[cand], e_label, checks_min, other, has_e)}
    if unit in p2.INCOMPLETE and final == "DEAD":
        out["survival"]["final_label_after_unit_caps"] = "INCONCLUSIVE (antecedents_incomplete: DEAD -> INCONCLUSIVE)"
    return out


# ================================================================================================ deviations
DEVIATIONS = [
    {"item": "output files",
     "prereg_said": "outputs: F3 -> phase_e_f3_round.py / f3_round.json; A1 -> phase_e_a1_<candidate>.py / a1_<candidate>.json",
     "what_you_did": "one script phase_e_a1_p2_p4_f3.py (item key given by the orchestrator) writing a1_p2_p4_f3.json; the "
                     "F3 section of the same run is also written alone to f3_round.json",
     "why": "the orchestrator assigned P2, P4 and F3 to one item; the prereg-named F3 path is kept", "effect_on_verdict": "none"},
    {"item": "F3 strict exclusion: which occurrences count",
     "prereg_said": "value_level_rule_primary: a distinct T_orig value is EXCLUDED if ANY of its occurrences in call args in the "
                    "unit is a parameter occurrence; prereg_e_calibration.cal_round (which produced R:f3_counts_A) counted only "
                    "the value's UNSOURCED occurrences",
     "what_you_did": "primary = the JSON text (every call-arg occurrence of the value in the analysed population, sourced or "
                     "not); the calibration-code reading is reported as F3.strict_calibration_code, and the first-occurrence "
                     "rule as F3.first_occurrence; neither variant decides",
     "why": "PREREG_E.md header: where the file and the JSON differ the JSON wins; probe_2 set the same precedent (JSON text "
            "over calibration code)",
     "effect_on_verdict": "see kill_tests.F3_parameter_exclusion.variants_reported_not_deciding per candidate"},
    {"item": "F3 effect on the candidate label",
     "prereg_said": "COLLAPSE = DEAD; ALIVE kept only if rule ALIVE and g >= 0.5 g_full, otherwise WEAK; below min n -> "
                    "INSUFFICIENT_N and capped at WEAK",
     "what_you_did": "F3 DEAD -> kill (KILLED); F3 WEAK -> cap_weak; F3 INSUFFICIENT_N -> cap_weak; F3 ALIVE -> pass",
     "why": "mechanical mapping of the rule onto survival_status effects", "effect_on_verdict": "as stated"},
    {"item": "kill tests: which population decides",
     "prereg_said": "every second-pass statistic runs on B u E; the replication verdict uses E alone; F3 'on B u E and on E'",
     "what_you_did": "every kill test (F3, P2-K1) is decided on B u E; its E result is computed too and, where it is testable "
                     "and lower, it is the one used (lowest testable label of B u E and E). Units without E: B",
     "why": "fixed before any number: a kill on the fresh replication split is a kill; taking the lower label is conservative",
     "effect_on_verdict": "see kill_tests.*.label_used and by_population"},
    {"item": "redaction cap in F3",
     "prereg_said": "F3 applies 'the Phase B round-number rule'; prereg.json probe4.verdict.caps: swechat verdict stands only "
                    "if the redaction sensitivity run gives the same label, else WEAK",
     "what_you_did": "for swechat candidates the cap is applied to the full statistic and to T_orig_noparam (the noredact "
                     "rerun with the same exclusion set) before the F3 collapse rule; AC/strata recomputations use the "
                     "uncapped rule against the uncapped B u E reference",
     "why": "the cap is part of the Phase B rule for swechat; it can only lower ALIVE to WEAK",
     "effect_on_verdict": "can only lower; see populations.*.full.redaction_cap and F3.strict.rule.redaction_cap"},
    {"item": "P4 artifact checks: which statistic",
     "prereg_said": "artifact checks recompute 'the statistic' of the candidate (P4round: prereg.json probe4 round numbers)",
     "what_you_did": "each AC (and each stratum) is computed for the candidate statistic (T_orig vs M_all, Phase B rule) AND "
                     "for the F3 statistic (strict exclusion, F3 rule, recomputed inside the filtered data); a check FAILs if "
                     "either label drops and the candidate takes the lowest failing label; CONFINED on either -> one-level "
                     "downgrade (once per axis set); an AC4 leave-out that leaves either statistic below its min n (while its "
                     "B u E reference was testable) is UNTESTABLE_WITHOUT_DOMINANT (cap WEAK)",
     "why": "after F3 the residual (parameter-free) gap is what remains of the candidate; testing both can only lower",
     "effect_on_verdict": "conservative; see artifact_checks.*.per_statistic"},
    {"item": "AC2 / AC3 decision events (P2 and P4)",
     "prereg_said": "AC2: recompute after dropping every event whose result text matches truncated_result(); AC3: recompute "
                    "on join_clean_mask() pairs",
     "what_you_did": "the dropped events are the decision events: P4 M_all values from truncated (AC2) or not join-clean (AC3) "
                     "results, and T_orig occurrences in calls whose own first result is truncated / whose pair is not "
                     "join-clean; P2 first accesses / first mentions whose call's first result is truncated / whose pair is "
                     "not join-clean. Antecedent text is left as recorded (the agent saw the truncated text)",
     "why": "the statistic's events are calls and results; the record the agent saw is not changed by the check",
     "effect_on_verdict": "see artifact_checks.AC2_truncation / AC3_join"},
    {"item": "AC3 copy rule",
     "prereg_said": "join_clean_mask: the call_id does not occur in another session",
     "what_you_did": "'another session' = the pooled B u E sessions of the unit (B only for cc_local / aiv_cc); loader-made "
                     "'synthetic:' ids are excluded from the copy test (as a1_p1_p3)",
     "why": "H and A may not be read; synthetic ids are unique only within a session",
     "effect_on_verdict": "copies shared with A or H are not detected (limitation)"},
    {"item": "P2 K1 implementation",
     "prereg_said": "K1: recompute with the strict pre-registered workspace-root rule (no Phase B deviation)",
     "what_you_did": "probe_2.py is not edited: the probe_2 DEBUG_ACCESS hook (in memory) gives each first access's path; "
                     "rows of sub-agent threads in sessions without main-thread calls get the root of the (absent) main "
                     "thread, pc.workspace_root([]) = None, so their absolute paths become depth_unknown (relative paths keep "
                     "their component depth, which does not use the root)",
     "why": "this is exactly the deviation Phase B logged ('workspace root for child sessions with no main thread') undone",
     "effect_on_verdict": "see kill_tests.K1_root_rule (access_rows_affected_this_stratum)"},
    {"item": "P2 K2 event definitions",
     "prereg_said": "K2: S_deep on sessions without compaction, resume or /clear events (record complete); reported only",
     "what_you_did": "Phase C HARNESS_DEFS (covariate_definitions) for compaction, context_clear and resume, on the IR: system "
                     "text 'This session is being continued' / '<command-name>/compact' / '<command-name>/clear', meta "
                     "compact_boundary / microcompact_boundary (aiv_cc also status), Codex compacted / context_compacted / "
                     "role-less system rows / session_meta after the first, OpenCode compaction parts; swechat Claude Code "
                     "resume = more than one raw sessionId in the transcript (raw_cc_entries); aiv_cc resume = every run after "
                     "r000 of its SDK session (the loader documents that runs are resumes of one conversation)",
     "why": "the prereg names the event classes, the frozen covariate definitions name the rules",
     "effect_on_verdict": "none (reported only)"},
    {"item": "P2 AC1 raw audit scope",
     "prereg_said": "AC1: look up each audited event in the raw source by (session_id, uuid or call_id) and compare the fields "
                    "the statistic uses",
     "what_you_did": "Claude Code / Agent SDK: the call by tool_use id (path in its raw input), its tool_result (error flag, "
                     "S_deep only) and every earlier IR antecedent of the same thread by call id (results) or uuid "
                     "(user/system), searching the raw text for the key with probe_2's boundary rule. Codex and OpenCode "
                     "sub-agent sessions are whole-file threads: every earlier raw received text (tool outputs, user / "
                     "developer / system messages, base instructions, compaction text, inter-agent envelopes) is searched. "
                     "The enumeration source (basename in an enumeration result) is not re-derived from raw",
     "why": "these are the fields S_deep / S_path_any use; a raw antecedent the IR lost would make the reference sourced",
     "effect_on_verdict": "AC1 FAIL (>= 2 of 30 contributions change) -> one-level downgrade"},
    {"item": "P4 AC1 raw audit scope",
     "prereg_said": "as above",
     "what_you_did": "numerator events = distinct T_orig values ending in 0; the call by id (value among the raw input's large "
                     "integers) and every earlier IR antecedent of the session (any thread, as the Probe 4 rule) looked up by "
                     "call id / uuid; OpenCode / Codex positional as for P2; formats without a raw reader here (Gemini, "
                     "Cursor) are counted as format_not_implemented and do not count as changed. cc_local: frozen snapshot, "
                     "in-process, counts only; the reachable file-set is the root file-set plus the agent-<id>.jsonl files of "
                     "the audited calls' subagents found by file name in the same project directory; a call in another "
                     "family member's main file (name not in the IR) is counted as not_located_in_reachable_fileset and "
                     "does not count as changed (AC1 then judges the located events; a1_p1_p3 did the same for cc_local)",
     "why": "the T_orig decision is 'no antecedent large integer equal to the value'", "effect_on_verdict": "as AC1"},
    {"item": "strata",
     "prereg_said": "stratify by tool_key, modal model, repo, session-length tercile; reportable = meets the candidate's min n",
     "what_you_did": "P4 tool axis: T_orig restricted to occurrences in calls of one tool_key, M_all (results, other tools by "
                     "construction) kept whole; other axes restrict T and M to the stratum's sessions. P2 tool axis: the "
                     "access / mention tool of the decision event. Length terciles use each unit's A cuts (pooled candidate: "
                     "per member unit)",
     "why": "M_all has no call tool", "effect_on_verdict": "none unless CONFINED"},
    {"item": "missing repo_id / user_id",
     "prereg_said": "clusters: sessions.parquet repo_id / user_id",
     "what_you_did": "null values form one 'unknown' cluster, ranked and left out like any other (as a1_p1_p3)",
     "why": "leaving them unassigned would hide a pseudo-cluster", "effect_on_verdict": "see AC4 leave_outs"},
    {"item": "order of 'take the lower label' checks and one-level downgrades",
     "prereg_said": "order not stated",
     "what_you_did": "min-type checks (AC2, AC3, AC5) first, then kill tests, AC1, AC4, confinement, passed to "
                     "survival_status() in that order; final_label_other_order is reported (as a1_p1_p3)",
     "why": "conservative", "effect_on_verdict": "none unless a min-type check FAILs"},
    {"item": "AC1 FAIL effect", "prereg_said": "FAIL if >= 2 of 30 differ", "what_you_did": "one-level downgrade (as a1_p1_p3)",
     "why": "the prereg names no other effect", "effect_on_verdict": "none unless AC1 FAILs"},
    {"item": "a fired kill stops the line",
     "prereg_said": "survival rule lists KILLED; the brief: 'When a kill test fires, record it and stop that line for that unit'",
     "what_you_did": "after a kill (F3 COLLAPSE, P2-K1 DEAD, or an E verdict of DEAD) the remaining artifact checks and strata "
                     "for that candidate are recorded as NOT_RUN",
     "why": "the brief", "effect_on_verdict": "none (KILLED is final)"},
    {"item": "pooled swechat/* reproduction",
     "prereg_said": "same statistic as Phase B",
     "what_you_did": "the pooled B reproduction compares k, n, distinct values and sessions; its CI can differ from "
                     "probe_4.json because probe_4.pool() inserts values unit by unit (dict order), which changes the session "
                     "order fed to the bootstrap; here sessions are in session-id order",
     "why": "bootstrap draws depend on session order", "effect_on_verdict": "none on point estimates and k/n"},
    {"item": "antecedents-incomplete cap in strata and AC4 (aiv_cc)",
     "prereg_said": "stratification: reportable = meets the candidate's min n; signal-bearing = label >= WEAK under the "
                    "candidate's rule; probe2 caps: antecedents_incomplete units DEAD -> INCONCLUSIVE; AC4: DOMINATED if a "
                    "leave-out drops the label by >= 1 level",
     "what_you_did": "strata: a stratum meeting min n is reportable whatever its label; E.confinement() is given the label "
                     "before the cap (it treats a non-level label such as INCONCLUSIVE as not reportable, which would "
                     "contradict the text). AC4: a leave-out whose capped label is INCONCLUSIVE is compared with its label "
                     "before the cap (DEAD). DISCLOSURE: the AC4 reading was added after the first debug run showed aiv_cc "
                     "leave-outs labelled INCONCLUSIVE that the code did not count; the JSON reports "
                     "AC4_dominance.result_if_INCONCLUSIVE_leave_outs_not_counted next to the result",
     "why": "the cap exists because missing antecedents can only inflate 'unsourced'; it does not make a label that "
            "crosses the DEAD boundary without one session robust",
     "effect_on_verdict": "aiv_cc only; see its artifact_checks.AC4_dominance and stratification"},
    {"item": "changes made between debug runs (disclosure; all before the official run)",
     "prereg_said": "thresholds are never tuned after a result; any change is logged with before/after",
     "what_you_did": "no threshold changed. Implementation changes after a debug output was seen: (1) cc_local P4 AC1: the "
                     "first debug run searched only the root file-set and counted unfound calls as changed (22 of 30 "
                     "changed -> FAIL; 23 of the 30 audited calls were subagent calls, 5 sat in other family members' main "
                     "files); now subagent files are located by name and unlocated calls are not counted (see "
                     "AC1_parser.audited_and_located); (2) P4 AC4: the below-min-n test was coded for the candidate statistic "
                     "only, against this file's own declared rule (either statistic); fixed; on the debug data this changed "
                     "swechat/claude_code AC4 from PASS to UNTESTABLE_WITHOUT_DOMINANT (cap WEAK, no label change); (3) the "
                     "aiv_cc AC4 INCONCLUSIVE reading above; (4) crash fixes (empty pair table for swechat/cursor, a "
                     "'flags' column name clash, object-typed boolean columns after concatenation)",
     "why": "honest record of the analysis path", "effect_on_verdict": "as listed"},
    {"item": "AC5 for the round-number statistic",
     "prereg_said": "post-stratified ratio estimator with the session bootstrap; FAIL if the weighted label differs",
     "what_you_did": "weighted_cluster_rate for T_orig last-0, M_all last-0 and T_orig_noparam last-0; Phase B rule on the "
                     "weighted rates and CIs (min n from unweighted counts); F3 rule on the weighted gaps",
     "why": "the prereg states the estimator for rates; the rule compares two rates", "effect_on_verdict": "see AC5_sampling"},
]


# ================================================================================================ main
def main(argv=()):
    parts = set(argv) & {"p2", "p4"} or {"p2", "p4"}
    t0 = time.time()
    pre = {"prereg_e_json_sha256": E.sha256_file(E.PREREG_E_JSON),
           "spec_module_sha256_lf": E.sha256_lf(ROOT / "analysis" / "probes" / "prereg_e_common.py"),
           "spec_module_sha256_lf_prereg": PJ["provenance"]["spec_module_sha256_lf"], "check_frozen": "passed",
           "phase_b_prereg_json_sha256": PROV4["prereg_json_sha256"],
           "phase_b_spec_module_sha_ok": bool(PROV4["spec_sha_ok"] and p2.sha256(p2.SPEC_PATH) == PR2["provenance"]["spec_module_sha256"]),
           "phase_b_calibration_sha_ok": bool(PROV4["calibration_sha_ok"])}
    if not (pre["phase_b_spec_module_sha_ok"] and pre["phase_b_calibration_sha_ok"]):
        raise SystemExit("Phase B module sha mismatch: stop")
    result = {"item": "a1_p2_p4_f3", "script": "analysis/probes/phase_e_a1_p2_p4_f3.py",
              "run_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "prereg": pre,
              "population_rule": "B u E pooled for every second-pass statistic and check; E alone for the replication "
                                 "verdict; cc_local and aiv_cc B only (UNREPLICATED)",
              "thresholds_used": {
                  "probe4_round": {k: TH4[k] for k in ("round_margin", "round_min_values", "round_min_sessions", "rate_den_min",
                                                       "rate_sessions_min")},
                  "F3": {"collapse_g_over_g_full": F3_COLLAPSE, "keep_alive_g_over_g_full": F3_KEEP_ALIVE,
                         "param_context": E.PARAM_CONTEXT, "context_chars": 48},
                  "probe2": {"ALIVE": [p2.T_ALIVE, p2.T_ALIVE_HI], "WEAK": p2.T_WEAK, "min_n_S_deep": [p2.MIN_DEEP_N, p2.MIN_DEEP_S],
                             "min_n_S_path_any": [p2.MIN_ANY_N, p2.MIN_ANY_S], "instrument_max": p2.T_INSTRUMENT,
                             "D_unit": {u: p2.D_UNIT[u] for u in ("swechat/claude_code", "swechat/opencode", "swechat/codex", "aiv_cc")}},
                  "dominance": {"cluster_share": E.DOM_SHARE, "session_share": E.DOM_SESSION},
                  "audit": {"k": E.AUDIT_K, "fail_at": E.AUDIT_FAIL},
                  "length_terciles_A": {u: PJ["resolved"]["length_terciles_A"][u].get("cuts") for u in
                                        ("swechat/claude_code", "swechat/opencode", "swechat/codex", "swechat/gemini", "cc_local", "aiv_cc")}},
              "inputs_sha256": {}, "candidates": {}, "deviations": DEVIATIONS}
    for f in ("swechat_B", "swechat_E", "cc_local_B", "aiv_cc_B", "swechat_population"):
        result["inputs_sha256"][f"analysis/cache/{f}.parquet"] = E.sha256_file(E.CACHE / f"{f}.parquet")

    # ------------------------------------------------------------------------------ extraction pass (unit x split)
    dbg_cache = os.environ.get("A1_DEBUG_CACHE")  # debug runs only: pickle of the extraction pass in a scratch dir
    if dbg_cache:
        assert os.environ.get("A1_DEBUG_OUT"), "the extraction cache is for debug runs only"
    if dbg_cache and os.path.exists(dbg_cache):
        import pickle
        with open(dbg_cache, "rb") as fh:
            P4T, P4M, meta4, T2, ir_keep, extraction = pickle.load(fh)
        plan_done = True
    else:
        plan_done = False
    if not plan_done:
        P4T, P4M = defaultdict(list), defaultdict(list)
        meta4 = {"sessions": defaultdict(set), "npairs": {}, "unit_of": {}, "model": {}, "stratum": {}}
        T2 = {}
        sw_units = ["swechat/claude_code", "swechat/opencode", "swechat/codex", "swechat/gemini", "swechat/cursor"]
        plan = [(u_, ["B", "E"]) for u_ in sw_units] + [("cc_local", ["B"]), ("aiv_cc", ["B"])]
        p2_units = {"swechat/claude_code", "swechat/opencode", "swechat/codex", "aiv_cc"}
        ir_keep = {}
        extraction = {}
        for unit, splits in plan:
            do4 = "p4" in parts and (unit in P4_POOL_MEMBERS or unit == "cc_local")
            do2 = "p2" in parts and unit in p2_units
            if not (do4 or do2):
                continue
            copied = copied_call_ids(unit, splits)
            T2u = {"_copied_n": len(copied)}
            for sp in splits:
                u = load(unit, sp, with_assistant=(unit == "swechat/codex" and do2))
                print(f"[{time.time() - t0:7.1f}s] loaded {unit} {sp}: {len(u)} rows, {u.session_id.nunique()} sessions", flush=True)
                info = pair_info(u, copied)
                mm = model_map(unit, sp)
                ex = {"rows": int(len(u)), "sessions": int(u.session_id.nunique()), "pairs": info["n_pairs"],
                      "join_clean_pairs": info["n_clean"], "copied_call_ids_in_pool": len(copied)}
                if do4:
                    Tt, Mt = p4_walk(unit, u, info, unit == "cc_local")
                    Tt["split"], Tt["unit"] = sp, unit
                    Mt["split"] = sp
                    P4T[unit].append(Tt)
                    P4M[unit].append(Mt)
                    ex["p4_call_int_occurrences"] = int(len(Tt))
                    ex["p4_result_session_values"] = int(len(Mt))
                    meta4["sessions"][(unit, sp)] = set(u.session_id.unique())
                    meta4["npairs"].update(info["npairs"].to_dict())
                    meta4["unit_of"].update({s: unit for s in u.session_id.unique()})
                    meta4["model"].update(mm)
                    if unit == "cc_local":
                        meta4["stratum"].update(u.groupby("session_id").stratum.first().astype(str).to_dict())
                if do2:
                    X2 = p2_extract(unit, u, sp)
                    X2.pop("_sub", None)
                    calls = u[u.kind == "call"]
                    fl = {}
                    for s, q, ci in zip(calls.session_id, calls.seq, calls.call_id.astype(object)):
                        ci = ci if isinstance(ci, str) else None
                        fl[(s, int(q))] = {"trunc": bool(info["trunc_call"].get((s, ci), False)) if ci else False,
                                           "clean": bool(ci is not None and (s, ci) in info["clean"])}
                    X2["call_flags"] = fl
                    T2u[sp] = X2
                    T2u.setdefault("_k2", {}).update(k2_events(unit, u))
                    T2u.setdefault("_model", {}).update(mm)
                    T2u.setdefault("_npairs", {}).update(info["npairs"].to_dict())
                    ex["p2"] = X2["extraction"]
                    # IR rows kept for the AC1 audits (decision-event sessions only; compact columns)
                    keep_s = set(X2["X"].s[X2["X"].uns]) | set(X2["R"].s[X2["R"].uns & (X2["R"].cls == "path")])
                    g = u[u.session_id.isin(keep_s) & u.kind.isin(["call", "result", "user", "system"])][
                        ["session_id", "seq", "kind", "call_id", "uuid", "text", "is_subagent", "agent_id"]]
                    for s, gg in g.groupby("session_id"):
                        ir_keep[(unit, sp, s)] = gg.reset_index(drop=True)
                if do4:
                    # IR rows for the P4 AC1 audit: sessions holding a T_orig occurrence ending in 0 (compact columns)
                    Tt = P4T[unit][-1]
                    cand_s = set(Tt.sid[~Tt.src_all & Tt.v.str.endswith("0")])
                    g = u[u.session_id.isin(cand_s) & u.kind.isin(["call", "result", "user", "system"])][
                        ["session_id", "seq", "kind", "call_id", "uuid", "text", "is_subagent", "agent_id"]]
                    for s, gg in g.groupby("session_id"):
                        ir_keep.setdefault((unit, sp, s), gg.reset_index(drop=True))
                extraction[f"{unit}/{sp}"] = ex
                del u
            if do2:
                if unit == "swechat/claude_code":
                    # K2 raw resume test for sessions holding decision events
                    ds = set()
                    for sp in splits:
                        ds |= set(T2u[sp]["X"].s) | set(T2u[sp]["R"].s[T2u[sp]["R"].cls == "path"])
                    rr = raw_resume_cc(sorted(ds))
                    for s in rr:
                        T2u["_k2"].setdefault(s, set()).add("resume")
                    T2u["_k2_raw_resume_sessions_checked"] = len(ds)
                T2u["_ir_sessions"] = {(sp, s): g for (uu_, sp, s), g in ir_keep.items() if uu_ == unit}
                T2[unit] = T2u
        if dbg_cache:
            import pickle
            with open(dbg_cache, "wb") as fh:
                pickle.dump((P4T, P4M, meta4, T2, ir_keep, extraction), fh)
    result["extraction"] = extraction

    # ------------------------------------------------------------------------------ instrument check (swechat CC main)
    if "p2" in parts:
        cc = T2["swechat/claude_code"]
        inst = {}
        for name, sp in {"B": ["B"], "E": ["E"], "BuE": ["B", "E"]}.items():
            R = pd.concat([cc[x]["R"] for x in sp], ignore_index=True)
            inst[name] = instrument(R)
        for u_ in T2:
            T2[u_]["_instrument"] = inst if u_ != "aiv_cc" else {"B": inst["B"], "BuE": inst["B"]}
        result["instrument_check"] = {"rule": PR2["probe2"]["statistics"]["instrument_check"],
                                      "by_population": {k: {"S_symbol_ref": v["S_symbol_ref"], "ok": v["ok"]} for k, v in inst.items()},
                                      "note": "aiv_cc (B only) uses the B check, as Phase B"}
        for cand, (unit, st) in P2_CANDS.items():
            result["candidates"][cand] = run_p2(cand, unit, st, T2[unit], t0)

    # ------------------------------------------------------------------------------ P4 / F3
    if "p4" in parts:
        def ir_get(split, unit, sid):
            return ir_keep[(unit, split, sid)]
        for cand, units in P4_CANDS.items():
            T = pd.concat([x for u_ in units for x in P4T[u_]], ignore_index=True)
            M = pd.concat([x for u_ in units for x in P4M[u_]], ignore_index=True)
            for col in ("src_all", "src_clean", "red", "trunc", "clean"):
                T[col] = T[col].astype(bool)
            T = T.sort_values(["sid", "seq", "idx"], kind="stable").reset_index(drop=True)
            M = M.sort_values(["sid"], kind="stable").reset_index(drop=True)
            meta = {"sessions": {sp: set().union(*[meta4["sessions"].get((u_, sp), set()) for u_ in units]) for sp in ("B", "E")},
                    "npairs": meta4["npairs"], "unit_of": meta4["unit_of"], "model": meta4["model"], "stratum": meta4["stratum"],
                    "copied": None, "ir_get": ir_get}
            result["candidates"][cand] = run_p4(cand, units, T, M, meta, t0)
            del T, M

    # ------------------------------------------------------------------------------ verdict summary
    verdicts = {}
    for cname, c in result["candidates"].items():
        s = c["survival"]
        if cname.startswith("P4"):
            pop = "E" if c["has_E"] else "B"
            fpop = "BuE" if c["has_E"] else "B"
            r = c["populations"][fpop]
            dn = {"F3_label_BuE": r["F3_label"], "g_BuE": r["F3"]["strict"]["g"], "g_full_BuE": r["F3"]["strict"]["g_full"],
                  "T_noparam_remaining_BuE": [r["F3"]["strict"]["remaining"].get("distinct_values"),
                                              r["F3"]["strict"]["remaining"].get("sessions")],
                  "E_full_label": c["populations"][pop]["full"]["label_capped"],
                  "F3_label_E": c["populations"]["E"]["F3_label"] if c["has_E"] else None}
            path = f"candidates['{cname}'].populations.{fpop}.F3.strict; .kill_tests.F3_parameter_exclusion; .survival"
        else:
            pop = "E" if c["has_E"] else "B"
            dn = {"E_or_B": c["populations"][pop], "BuE": c["populations"].get("BuE", c["populations"]["B"])}
            path = f"candidates['{cname}'].populations.{pop}; .kill_tests; .survival"
        verdicts[cname] = {"status": s["status"], "final_label": s["final_label"], "phase_b": s["phase_b_label"],
                           "E_label": s["E_label"], "reasons": s["reasons"], "deciding": dn, "json_path": path}
    result["verdicts"] = verdicts
    result["verdict_cells_computed"] = {"survival_statuses": len(verdicts), "multiplicity": PJ["global"]["multiplicity"]}
    result["runtime_s"] = round(time.time() - t0, 1)
    txt = json.dumps(clean(result), indent=1, allow_nan=False, ensure_ascii=False, default=str)
    debug = os.environ.get("A1_DEBUG_OUT")
    out_path = Path(debug) if debug else OUT
    if not debug:
        assert set(argv) <= {"p2", "p4"} and parts == {"p2", "p4"}, "official runs compute every part"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(txt, encoding="utf-8")
    if "p4" in parts:
        f3 = {"item": "F3 (followups.F3_round_numbers), written by analysis/probes/phase_e_a1_p2_p4_f3.py",
              "source": f"{out_path.name} candidates['P4round/*'] (same run)", "prereg": pre, "run_utc": result["run_utc"],
              "rule": F3, "candidates": {k: {"populations": {p: {"full": v["populations"][p]["full"], "T_orig": v["populations"][p]["T_orig"],
                                                                 "M_all": v["populations"][p]["M_all"], "g_full": v["populations"][p]["g_full"],
                                                                 "F3": v["populations"][p]["F3"], "F3_label": v["populations"][p]["F3_label"]}
                                                             for p in v["populations"]},
                                              "kill_test": v["kill_tests"]["F3_parameter_exclusion"],
                                              "survival": v["survival"]}
                                          for k, v in result["candidates"].items() if k.startswith("P4")},
              "deviations": [d for d in DEVIATIONS if "F3" in d["item"] or "redaction" in d["item"] or "kill tests" in d["item"]]}
        f3_path = out_path.with_name("f3_round.json") if debug else OUT_F3
        f3_path.write_text(json.dumps(clean(f3), indent=1, allow_nan=False, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"done in {result['runtime_s']}s -> {out_path}")
    for k, v in verdicts.items():
        print(f"  {k:36s} {v['status']:45s} final {v['final_label']}  reasons {v['reasons']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
