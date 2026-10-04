"""Phase E, new corpora, group `tbench`: corpora tbench2 (Terminal-Bench 2.0 leaderboard submissions) and glm_tb21
(GLM-5.2 self-hosted Terminal-Bench 2.1 traces). Pre-registered extensions (prereg_e.json change_log, commit 669124a,
orchestrator decisions D1-D7). Every mechanism the prereg defines is measured where the N6 field gate and D1 allow it.

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_newcorp_tbench
Writes (raw numbers and mechanically computed labels only):
  analysis/out/phase_e/newcorp_measure_tbench2.json
  analysis/out/phase_e/newcorp_measure_glm_tb21.json
Interpretation: analysis/notes/phase_e_newcorp_tbench.md (never in the JSON).

Inputs, all read through prereg_e_common.read_cache (B and E only; never A, never H):
  analysis/cache/{tbench2,glm_tb21}_{B,E}.parquet, built by this group with the corpora's own loaders
  (`python -m analysis.loaders.load_tbench2 --split B|E`, `python -m analysis.loaders.load_glm_tb21 --split B|E`), with
  the sessions of analysis/out/phase_e/newcorp_exclusions.json removed (D5; it lists none for these two corpora).
Thresholds: prereg_e.json (frozen; check_frozen() first), the corpus calibration
  analysis/out/phase_e/prereg_e_calibration_<corpus>.json (sha256 asserted equal to its change_log entry) and, where the
  prereg names Phase B quantities, analysis/prereg.json. Phase B probe code is imported unchanged (probe_2.process_unit
  and its statistics, probe_4.extract and its verdict functions).
Raw source reads (read-only, B and E sessions only, by the split index's relative paths; no value is printed, only
  counts and comparisons): the AC1 parser audits of R1, N1, N2 and N3 (ATIF trajectory.json, Claude Code JSONL, Gemini
  CLI JSON, hookele JSONL) and the R4 raw side (toolUseResult.file.numLines in tbench2 Claude Code JSONL logs).

Orchestrator decisions applied (prereg_e.json change_log, binding):
  D1 calibration-unit argument = the corpus's own name ('tbench2', 'glm_tb21'). Quantities calibrate_unit did not
     produce take the pre-registered pooled value where one exists (N1 bounds, N5c truncation constants, Probe 2 D),
     else the cell is NOT_TESTABLE.
  D2 AC4 dominance / confinement cluster = the corpus stratum (submitting agent__model for tbench2; one value for
     glm_tb21).
  D5 exclusions: none listed for tbench2 / glm_tb21 (checked and recorded).
  D6 NOT_BLIND: the request-id bracket (R1 and its placebo / tamper cells), latency mechanisms (Probe 1, N1, N4, N5g:
     all built on call->result gaps) and reaction time (N3) carry the label NOT_BLIND.
Secrets: the loaders redact credential-like values on load; this script counts redaction markers only.
Scope: nothing swarm-related is read; no transcript is generated; data are read-only.
"""
import gc
import hashlib
import json
import math
import os
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
from analysis.probes import prereg_e_calibration as pecal

T0 = time.time()
PJ = pe.check_frozen()
from analysis.probes import probe_2 as p2  # noqa: E402  (Phase B code, imported unchanged)
from analysis.probes import probe_4 as p4  # noqa: E402

GROUP = "tbench"
SCRIPT = "analysis/probes/phase_e_newcorp_tbench.py"
NOTES = "analysis/notes/phase_e_newcorp_tbench.md"
CORPORA = [c for c in os.environ.get("NEWCORP_ONLY", "glm_tb21,tbench2").split(",") if c]
SPLITS = ("B", "E")
R1_STRATUM = {"tbench2": "WozCode__Claude-Opus-4.6"}
COLS = list(dict.fromkeys(pecal.COLS + ["uuid", "ts_kind"]))
PRB = json.loads((pe.ROOT / "analysis" / "prereg.json").read_text(encoding="utf-8"))
TOK_PER_CHAR = PRB["probe1"]["separability"]["generation_time_model"]["tokens_per_char"]
assert abs(TOK_PER_CHAR - 0.25) < 1e-12
EXCL = json.loads((pe.OUT_E / "newcorp_exclusions.json").read_text(encoding="utf-8"))
LVL = {"ALIVE": 2, "WEAK": 1, "DEAD": 0}
NOT_BLIND = "NOT_BLIND (D6)"
OPENED = []
SCOPES = ("shell", "auto_read")


def log(*a):
    print(f"[{time.time() - T0:7.1f}s]", *a, flush=True)


# ===================================================================================================== frozen thresholds
def _pooled_n1():
    for u, v in PJ["resolved"]["n1"].items():
        if isinstance(v, dict) and "pooled_n_A" in v:
            return {"bounds": list(v["bounds"]), "path": f"prereg_e.json resolved.n1.{u}.bounds",
                    "pooled_n_A": v["pooled_n_A"], "pooled_sessions_A": v["pooled_sessions_A"],
                    "source": v["source"]}
    raise RuntimeError("no pooled N1 bounds in prereg_e.json")


N1_POOLED = _pooled_n1()
N5C = PJ["resolved"]["n5"]["truncation_constants_pooled"]
P2_D_POOLED = PRB["resolved"]["probe2"]["depth_threshold"]["pooled"]["D"]
N1_RHO_BAND, N1_PC_LO, N1_RR, N1_FLAG_PT, N1_FLAG_HI, N1_MIN = 0.15, 0.30, 0.10, 0.02, 0.05, (200, 20)
N2_FLAG_PT, N2_FLAG_HI, N2_WEAK_FLAG, N2_REC_ALIVE, N2_REC_WEAK, N2_MIN = 0.05, 0.10, 0.20, 0.90, 0.50, (100, 10)
N2_TAU_PRIME = (1.0, 0.8)
N3_MIN_GAPS, N3_MIN_SESS, N3_ALIVE_LO, N3_SHARE_PT, N3_SHARE_HI = 20, 20, 0.30, 0.10, 0.20
N5_MIN = {"a": (100, 20), "b": (100, 20), "c": (50, 10), "d": (100, 20)}
N5_TH = {"a": (0.05, 0.10, 0.20), "b": (0.01, 0.03, 0.05), "d": (0.01, 0.03, 0.05)}
N5E_FAM_MIN, N5E_COMP_MIN = (100, 10), (30, 5)
N5G_MIN, N5G_ALIVE_C, N5G_ALIVE_SHARE = 30, math.log10(1.5), 0.05
R1_RATE_MIN = (30, 5)
GRID_D, GRID_LATE = pe.GRID_D, pe.GRID_D_LATE_CHECK
BACKDATE_TYPES = {"time_response_early", "time_tail_early"}
SINGLE_CALL = set(PJ["n7_attack_battery"]["single_call_types"])
R1_ATTACKS = ([("time_response_early", D) for D in GRID_D] + [("time_response_late", D) for D in GRID_LATE] +
              [("time_result_late", D) for D in GRID_D] + [("time_result_early", D) for D in GRID_D] +
              [("time_tail_late", D) for D in GRID_D] + [("time_tail_early", D) for D in GRID_D] +
              [("id_swap_adjacent", "-"), ("id_splice_foreign", "random"), ("id_splice_foreign", "nearest"),
               ("delete_response", "-"), ("delete_pair", "-"), ("insert_pair_consistent", "-"),
               ("insert_pair_squeezed", "-")])
for _a, _p in R1_ATTACKS:
    assert pe.applicable(_a, "R1_BRACKET"), _a
PLACEBO = [("back", 5000), ("back", 30000), ("late", 5000), ("late", 30000), ("late", 300000)]
F1_CATS = ["restamped_copy", "clock_step", "concurrent_streams", "api_retry", "compaction", "user_input_binding",
           "long_gap", "whole_second", "vertex_or_bedrock"]


# ===================================================================================================== deviations
DEVIATIONS = [
    {"item": "unit argument (D1) and its mechanical consequences",
     "prereg_said": "D1: tbench2 and glm_tb21 calibrate and measure under their own names; quantities calibrate_unit did "
                    "not produce take the pre-registered pooled value where one exists, else NOT_TESTABLE",
     "what_you_did": "every frozen function is called with unit = the corpus name. Consequences, applied mechanically: "
                     "(1) prereg_common.error_classes has no definition for these units (primary None), so Probe 3 "
                     "(3a, 3b) and N5f are NOT_TESTABLE(error signal) and Probe 2's first_try_success is never True "
                     "(its S_deep population is empty, the Phase B rule falls back to S_path_any capped at WEAK); "
                     "(2) the Phase B Probe 1 qualification (prereg.json probe1 allowed_classes), floors, G90 and G set, "
                     "and the N4 W / G populations built on them, exist only for registered units and have no pooled "
                     "value: Probe 1 and N4 are NOT_TESTABLE; (3) N1 detector bounds = the pooled bounds "
                     f"({N1_POOLED['path']}); (4) N5c constants = resolved.n5.truncation_constants_pooled; (5) Probe 2 "
                     f"D = the pooled D {P2_D_POOLED} (prereg.json resolved.probe2.depth_threshold.pooled.D)",
     "why": "D1 is binding", "effect_on_verdict": "decides the NOT_TESTABLE cells listed in cells.*"},
    {"item": "N1 positive control without a calibrated G90",
     "prereg_said": "rho_pc: tampered instance gets delta' = result chars x 0.25 / G90(unit)",
     "what_you_did": "computed with G90 = 1 tok/s as a placeholder and recomputed with G90 = 100 tok/s; both values are "
                     "stored and must be identical: r' = log10(chars) + log10(0.25 / G90) - median(ref), so G90 shifts "
                     "every tampered residual by the same constant and a rank statistic cannot see it. The detector "
                     "recall on tampered instances (which does depend on G90) is not computed",
     "why": "D1 leaves G90 undefined for these units; rho_pc, the only N1 verdict input that uses G90, is invariant to it",
     "effect_on_verdict": "none on rho_pc (checked: n1.*.rho_pc_G90_invariance)"},
    {"item": "R1 population",
     "prereg_said": "R1 runs where decodable request ids exist; N7 sessions = every session with >= 1 eligible target",
     "what_you_did": "tbench2 R1 (honest bracket, placebo, stream-level kill-rule tampers, N7 session cells, strata, "
                     "artifact checks) runs on the sessions of the stratum WozCode__Claude-Opus-4.6, the only stratum "
                     "whose IR carries request ids (checked per split: r1.<split>.request_id_sessions_by_stratum). The "
                     "N7 session set is that stratum's sessions with an eligible target",
     "why": "the orchestrator's task assigns R1 to that stratum; running N7 over all 25 strata would count the 24 "
            "id-less strata as abstentions (not flagged) and measure corpus composition, not the detector",
     "effect_on_verdict": "R1 cells describe one submission (one agent, one model)"},
    {"item": "R1 kill rule and N7 leg (as analysis/probes/phase_e_f1_bracket.py does for swechat)",
     "prereg_said": "a1.proposal_rules R1_specific; F1 placebo; N7 single-call / single-response types",
     "what_you_did": "kill-rule cells are stream-level: one tamper per stream (frame of that stream only), target "
                     "rng_for(attack, param, session, stream), donor rng_for('donor', attack, param, session, stream); "
                     "the back-dating leg is the F1 placebo (placebo_shift 30 s); the honest bar = session-clustered CI "
                     "hi of the honest stream rate (per-event Wilson hi when the numerator is 0). The N7 leg is "
                     "session-level: one tamper per session, target rng_for(attack, param, session), session flagged iff "
                     ">= 1 stream is inconsistent, FPR on the same sessions untampered, n7_cell_label(). E is the "
                     "replication split; B and B u E are reported. insert_pair donors = main-thread pairs (delta > 0, "
                     "call gap >= 0) of other sessions of the R1 population of the same split. rewrite_consistent_k is "
                     "NOT_RUN for R1 (not a single-call type; not an input of the R1 rule)",
     "why": "same construction as the swechat R1 so the cells are comparable", "effect_on_verdict": "none"},
    {"item": "R4 on tbench2 although the A field gate says raw_structured_counters False",
     "prereg_said": "N6 fill rule: NOT_TESTABLE iff a required field is absent (R4: harness structured counters "
                    "toolUseResult numLines in the raw source); a1.proposal_rules R4_specific: NOT_RUN if the raw "
                    "join is not implemented",
     "what_you_did": "the calibration's field gate sets raw_structured_counters by unit name (True only for "
                     "swechat/claude_code and cc_local) and the new-corpus calibration copies False. A structural count "
                     "of the B raw logs finds toolUseResult.file.numLines in the Claude Code JSONL strata "
                     "ClaudeCode__GLM-4.7 and cchuter__minimax-m2.5 (WozCode carries none), so the field is present "
                     "and R4 was run there with the analysis/probes/phase_e_r4_r5.py recount: raw numLines of a "
                     "top-level entry carrying a tool_result block (first occurrence per tool_use_id) against the IR "
                     "text's numbered lines (^\\s*\\d+(U+2192|\\t)); unit flagged iff they differ and "
                     "dual_whitelisted() (swechat class list) is None; session flag = >= 1 flagged unit; honest part = "
                     "Wilson session share (>= 30 decided sessions). N7 R4_DUAL cells: session-level, attack-defined "
                     "targets (phase_e_n7_timing.py TARGET_RULES) inside the sessions of the field-bearing strata, "
                     "donors for substitutions = other real results of tbench2 of the same split and tool key "
                     "(pick_donor, 5 %). glm_tb21 (ATIF only) has no such field: NOT_TESTABLE",
     "why": "a definitional False would hide a testable cell; the prereg's own rule (NOT_RUN only when the join is "
            "missing) points to running it", "effect_on_verdict": "adds the tbench2 R4 cell"},
    {"item": "AC5 sampling check",
     "prereg_said": "post-stratified recompute with population_cells(corpus)",
     "what_you_did": "NOT_RUN: prereg_e_common.population_cells() has no branch for new corpora (it raises), and the "
                     "frozen module may not be edited",
     "why": "frozen code", "effect_on_verdict": "none (a check can only lower a label)"},
    {"item": "multi-checker items (N5b sort, N5c truncation, N5d whitespace)",
     "prereg_said": "statistic and verdict per checker / sub-item; one N6 row per item; no combination rule",
     "what_you_did": "each checker has its own verdict; the item cell is the LOWEST label among checkers whose label is "
                     "ALIVE/WEAK/DEAD (INSUFFICIENT_N if none), the rule analysis/probes/phase_e_n5_battery.py uses",
     "why": "cannot raise a label", "effect_on_verdict": "cell <= best checker"},
    {"item": "verdict-rule gaps and CIs (same readings as the Track A item scripts)",
     "prereg_said": "N1 / N3 / N5 verdict rules",
     "what_you_did": "N1: INCONCLUSIVE when rho_hon < -0.15 without a DEAD condition or a needed CI has < 900 valid "
                     "draws; rule order DEAD, ALIVE, WEAK. N3: pooled rho over the gaps of the sessions with >= 20 gaps; "
                     "positive control = within-session permutation (rng_for('N3pc', session, 'gaps')). N2: WEAK uses "
                     "recall at 0.8 tau. N5 rates: rate_by_session; zero numerator -> per-event Wilson hi in the ALIVE "
                     "rule. N5e: log10(bytes + 1); comparator IQR CI by boot_stat with >= 30 texts from >= 5 sessions. "
                     "N5g: median c by cluster_quantile over sessions, share by Wilson. N5c exactness CI lo = 1 - CI hi "
                     "of the inexact rate",
     "why": "smallest faithful reading; identical to the Track A item scripts", "effect_on_verdict": "none expected"},
    {"item": "N6 cell for B u E",
     "prereg_said": "the cell is the E verdict where E is not INSUFFICIENT_N, else the B verdict 'B only'; artifact "
                    "checks on B u E",
     "what_you_did": "B, E and B u E are all computed and stored; the cell follows the fill rule; B u E is the "
                     "artifact-check population and is reported, it is never the cell",
     "why": "as written", "effect_on_verdict": "none"},
    {"item": "AC1 parser audit for new corpora",
     "prereg_said": "AC1: 30 numerator (or flagged) events looked up in the raw source; the fields the statistic uses "
                    "are compared; FAIL at >= 2 of 30 differing in a way that changes their contribution",
     "what_you_did": "an independent raw reader (RawSession: ATIF trajectory.json, Claude Code JSONL, Gemini CLI JSON, "
                     "hookele JSONL; read-only; no value printed) for the cells at WEAK or better: R1 (30 decoded "
                     "responses + binding events of inconsistent streams: uuid, requestId, stamp), N1 (flagged shell "
                     "calls: both stamps -> delta within 1 ms, n1 command key), N2 (flagged responses: flag recomputed "
                     "from raw usage_out, raw chars of text + compact-JSON args + thinking, raw last-result chars), N3 "
                     "(gaps of flagged sessions: raw stamps of the last result and the next model event, gap within "
                     "1 ms; the row-level walk is asserted equal to n3_gaps). FAIL = one-level downgrade (as the Track "
                     "A item scripts apply it). Naive raw stamps are read as UTC, the loader's stated rule",
     "why": "the loaders are new code never audited on B/E; AC1 is the check that exercises them",
     "effect_on_verdict": "see checks.<item>.AC1_parser"},
    {"item": "D6 blindness scope",
     "prereg_said": "D6: bracket, latency (Probe 1) and reaction time (N3) cells are NOT_BLIND",
     "what_you_did": "NOT_BLIND is also put on N1, N4 and N5g: Track B computed call->result gap quantiles over the full "
                     "corpora, and these three are built on the same gaps",
     "why": "the conservative reading of 'latency'", "effect_on_verdict": "label only"},
]


# ===================================================================================================== small helpers
def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (set, frozenset)):
        return sorted(clean(v) for v in o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if not math.isfinite(f) else f
    if isinstance(o, np.bool_):
        return bool(o)
    if o is pd.NA:
        return None
    return o


def wil(k, n):
    p, lo, hi = stats.wilson(int(k), int(n))
    return {"k": int(k), "n": int(n), "share": p, "lo": lo, "hi": hi}


def crate(flags, sids):
    flags = np.asarray(flags, dtype=bool)
    if len(flags) == 0:
        return {"rate": None, "lo": None, "hi": None, "num": 0.0, "den": 0.0, "n_sessions": 0}
    return pe.rate_by_session(flags, np.asarray(sids))


def hi_used(r):
    """CI hi a verdict uses: cluster CI hi; per-event Wilson hi when the numerator is 0."""
    if r.get("rate") is None:
        return None
    return r.get("wilson_hi_per_event") if r.get("num", 0) == 0 else r.get("hi")


def qtiles(v, sids=None, qs=(0.0, 0.05, 0.25, 0.5, 0.75, 0.95, 1.0)):
    v = np.asarray(v, dtype=float)
    ok = np.isfinite(v)
    out = {"n": int(ok.sum())}
    if sids is not None:
        out["n_sessions"] = int(len(set(np.asarray(sids, dtype=object)[ok].tolist())))
    if ok.any():
        for q in qs:
            out[f"q{q:g}"] = float(np.quantile(v[ok], q))
    return out


def rho(x, y, sids):
    x = np.asarray(x, dtype=float)
    if len(x) == 0:
        return {"value": None, "n": 0, "n_sessions": 0, "valid_draws": 0, "ci_reported": False}
    b = pe.session_spearman(x, np.asarray(y, dtype=float), np.asarray(sids, dtype=object))
    b["n"] = int(np.isfinite(x).sum())
    return b


def lower(a, b):
    if a in LVL and b in LVL:
        return a if LVL[a] <= LVL[b] else b
    return a if a in LVL else b


def lowest(labels):
    lab = [x for x in labels if x in LVL]
    if not lab:
        return None
    return min(lab, key=lambda x: LVL[x])


def is_shell(k):
    return k == "shell" or k in pc.CODEX_SHELL_RAW or str(k).endswith("__bash")


def sha_file(p):
    return pe.sha256_file(p)


def _s(x):
    return x if isinstance(x, str) else None


def three_rate_label(r, th, n_min):
    """N5a/b/d rule: ALIVE rate <= pt with CI hi <= hi; WEAK rate <= weak; DEAD otherwise; INSUFFICIENT_N below min."""
    pt, hi_th, weak = th
    n, ns = int(r.get("den", 0) or 0), int(r.get("n_sessions", 0) or 0)
    if n < n_min[0] or ns < n_min[1]:
        return {"label": "INSUFFICIENT_N", "rule": f"min n: >= {n_min[0]} from >= {n_min[1]} sessions",
                "deciding_number": {"n": n, "sessions": ns}}
    h = hi_used(r)
    if r["rate"] <= pt and h is not None and h <= hi_th:
        return {"label": "ALIVE", "rule": f"rate <= {pt} and CI hi <= {hi_th}",
                "deciding_number": {"rate": r["rate"], "hi_used": h}}
    if r["rate"] <= weak:
        return {"label": "WEAK", "rule": f"rate <= {weak} (ALIVE fails: rate {r['rate']:.4f}, hi {h})",
                "deciding_number": {"rate": r["rate"], "hi_used": h}}
    return {"label": "DEAD", "rule": f"rate > {weak}", "deciding_number": {"rate": r["rate"], "hi_used": h}}


# ===================================================================================================== loading
def load_split(corpus, split):
    p = pe.CACHE / f"{corpus}_{split}.parquet"
    OPENED.append(str(p.relative_to(pe.ROOT).as_posix()))
    u = pe.read_cache(corpus, split, COLS)
    ex = set(EXCL.get(corpus, {}).get(split, []))
    n0 = u.session_id.nunique()
    if ex:
        u = u[~u.session_id.isin(ex)]
    u = u.reset_index(drop=True)
    ids = set(pe.split_ids(corpus, split))
    assert set(u.session_id.unique()) <= ids, "cache holds sessions outside the split id list"
    return u, {"sessions_in_cache": int(n0), "excluded_D5": len(ex), "sessions_used": int(u.session_id.nunique()),
               "split_ids": len(ids), "rows": int(len(u))}


def copied_call_ids(corpus):
    parts = []
    for sp in SPLITS:
        d = pe.read_cache(corpus, sp, ["session_id", "kind", "call_id"], filters=[("kind", "==", "call")])
        parts.append(d[d.call_id.notna()][["session_id", "call_id"]].drop_duplicates())
    d = pd.concat(parts, ignore_index=True)
    n = d.groupby("call_id").session_id.nunique()
    return frozenset(str(x) for x in n[n > 1].index)


def copied_request_ids(corpus):
    parts = []
    for sp in SPLITS:
        d = pe.read_cache(corpus, sp, ["session_id", "request_id"])
        parts.append(d[d.request_id.notna()].drop_duplicates())
    d = pd.concat(parts, ignore_index=True).drop_duplicates()
    ns = d.groupby("request_id").session_id.nunique()
    cop = set(str(x) for x in ns[ns > 1].index)
    keep = d[d.request_id.isin(cop)].groupby("request_id").session_id.min().to_dict()
    return cop, keep


def redaction_counts(u):
    out = Counter()
    for col in ("text", "args", "command", "stderr"):
        v = u[col].astype(object)
        out[f"{col}:rows_with_marker"] = int(v.map(lambda t: isinstance(t, str) and "[REDACTED:credential]" in t).sum())
        out[f"{col}:markers"] = int(v.map(lambda t: t.count("[REDACTED:credential]") if isinstance(t, str) else 0).sum())
    ex = u.extra.astype(object).map(lambda e: pc.jl(e).get("credential_redactions", 0) if isinstance(e, str)
                                     and "credential_redactions" in e else 0)
    out["extra.credential_redactions_sum"] = int(ex.sum())
    return dict(out)


# ===================================================================================================== per-split extraction
def unit_pairs(unit, u, copied):
    P, Q = pecal.unit_pairs(unit, u)
    Q = Q.copy()
    Q["join_clean"] = pe.join_clean_mask(u, Q, copied)
    Q["trunc"] = [pe.truncated_result(t, x) for t, x in zip(pc.sobj(Q.text_r), Q.extra_r.astype(object))]
    Q["call_id"] = Q.call_id.astype(str)
    return P, Q


def session_meta(u, Q, cuts, split):
    st = u.groupby("session_id").stratum.first()
    model = pe.session_model_map(u)
    npairs = Q.groupby("session_id").size().to_dict()
    sids = sorted(u.session_id.unique())
    terc = pe.length_tercile_map({s: npairs.get(s, 0) for s in sids}, cuts)
    return {s: {"stratum": str(st.get(s)), "model": str(model.get(s, "unknown")), "length_tercile": terc[s],
                "split": split, "pairs": int(npairs.get(s, 0))} for s in sids}


def field_gate(unit, u, P):
    resp = pe.response_table(unit, u)
    g = pe.granularity(resp)
    return pecal.field_gate(unit, u, P, {"n2": {"granularity": g}})


# ---------------------------------------------------------------------------------------------------- N1
def n1_extract(Q):
    q = Q[Q.qualified].copy()
    return q[["session_id", "seq", "key", "cls", "n1", "delta_s", "result_bytes", "result_chars", "err", "trunc",
              "join_clean", "call_id"]].reset_index(drop=True)


def n1_pc(q, g90):
    rows = []
    for (s, k, nk), g in q[q.n1.notna()].groupby(["session_id", "key", "n1"], sort=False):
        if len(g) < 2:
            continue
        lg = np.log10(g.delta_s.to_numpy(dtype=float))
        er = g.err.to_numpy()
        ch = g.result_chars.to_numpy(dtype=float)
        by = g.result_bytes.to_numpy(dtype=float)
        elig = [i for i in range(len(g)) if any(er[j] == er[i] for j in range(len(g)) if j != i)]
        if not elig:
            continue
        rng = pe.rng_for("N1pc", s, nk)
        i = elig[int(rng.integers(0, len(elig)))]
        tgen = ch[i] * TOK_PER_CHAR / g90
        ref = [lg[j] for j in range(len(g)) if j != i and er[j] == er[i]]
        r = (math.log10(tgen) - float(np.median(ref))) if tgen > 0 else float("nan")
        rows.append({"session_id": s, "key": k, "cls": g.cls.iloc[i], "seq": int(g.seq.iloc[i]), "residual_pc": r,
                     "log_bytes": math.log10(by[i] + 1)})
    return pd.DataFrame(rows, columns=["session_id", "key", "cls", "seq", "residual_pc", "log_bytes"])


def n1_measure(q, unit, path, cls="shell", full=True):
    q = q if len(q) else q
    R = pe.n1_residuals(q, unit) if len(q) else pd.DataFrame()
    if len(R):
        m = q.set_index(["session_id", "seq"])["cls"]
        R["cls"] = m.reindex(pd.MultiIndex.from_arrays([R.session_id, R.seq])).to_numpy()
        R = R[R.cls == cls]
    else:
        R = pd.DataFrame(columns=["session_id", "seq", "residual", "log_bytes", "d_log_bytes", "cls", "err", "n_ref"])
    qc = q[q.cls == cls]
    # coverage first
    sz = qc.assign(_n1=qc.n1.fillna("<none>")).groupby(["session_id", "key", "_n1"]).seq.transform("size") \
        if len(qc) else pd.Series(dtype=float)
    ing = (qc.n1.notna().to_numpy() & (sz.to_numpy() >= 2)) if len(qc) else np.array([], dtype=bool)
    out = {"coverage_RR": crate(ing, qc.session_id.to_numpy()) if len(qc) else {"rate": None, "num": 0, "den": 0,
                                                                                  "n_sessions": 0},
           "qualified_calls": int(len(qc)), "qualified_sessions": int(qc.session_id.nunique())}
    out["residuals"] = qtiles(R.residual if len(R) else [], R.session_id.tolist() if len(R) else [])
    out["rho_hon"] = rho(R.residual if len(R) else [], R.log_bytes if len(R) else [], R.session_id if len(R) else [])
    if full:
        out["rho_secondary_d_log_bytes"] = rho(R.residual if len(R) else [], R.d_log_bytes if len(R) else [],
                                               R.session_id if len(R) else [])
    pcs = {}
    for g90 in (1.0, 100.0):
        p = n1_pc(qc, g90) if len(qc) else n1_pc(q.iloc[0:0], g90)
        pf = p[np.isfinite(p.residual_pc.to_numpy(dtype=float))] if len(p) else p
        pcs[g90] = (p, pf)
    p, pf = pcs[1.0]
    out["positive_control"] = {"tampered_groups": int(len(p)), "tampered_finite": int(len(pf)),
                               "dropped_zero_char_results": int(len(p) - len(pf)),
                               "G90_placeholder_tok_per_s": 1.0, "tokens_per_char": TOK_PER_CHAR}
    out["rho_pc"] = rho(pf.residual_pc if len(pf) else [], pf.log_bytes if len(pf) else [],
                        pf.session_id if len(pf) else [])
    p100 = pcs[100.0][1]
    v100 = pe.spearman(p100.residual_pc, p100.log_bytes) if len(p100) else None
    v1 = out["rho_pc"].get("value")
    dif = abs(v1 - v100) if (v1 is not None and v100 is not None) else None
    out["rho_pc_G90_invariance"] = {"rho_pc_G90_1": v1, "rho_pc_G90_100": v100, "abs_diff": dif,
                                    "invariant_within_1e-3": bool(dif is not None and dif <= 1e-3),
                                    "note": "exact in arithmetic; floating-point rounding can split or merge ties of "
                                            "r' and move the rank statistic by ~1e-5"}
    lo, hi = N1_POOLED["bounds"]
    if len(R):
        f = (R.residual.to_numpy() < lo) | (R.residual.to_numpy() > hi)
        fr = crate(f, R.session_id.to_numpy())
        fr["flag_low"], fr["flag_high"] = int((R.residual.to_numpy() < lo).sum()), int((R.residual.to_numpy() > hi).sum())
    else:
        fr = {"rate": None, "num": 0, "den": 0, "n_sessions": 0}
    out["detector"] = {"bounds": [lo, hi], "bounds_source": N1_POOLED["path"] + " (pooled; D1)",
                       "honest_flag_rate": fr}
    out["verdict"] = n1_verdict(out, int(len(R)), int(R.session_id.nunique()) if len(R) else 0, path)
    return out


def n1_verdict(b, n_res, n_sess, path):
    if n_res < N1_MIN[0] or n_sess < N1_MIN[1]:
        return {"label": "INSUFFICIENT_N", "rule": f"min n: >= {N1_MIN[0]} residuals from >= {N1_MIN[1]} sessions",
                "deciding_number": {"residuals": n_res, "sessions": n_sess},
                "deciding_path": [f"{path}.residuals.n", f"{path}.residuals.n_sessions"]}
    rh, rp, rr, fl = b["rho_hon"], b["rho_pc"], b["coverage_RR"], b["detector"]["honest_flag_rate"]
    hv, hlo, hhi, plo = rh.get("value"), rh.get("lo"), rh.get("hi"), rp.get("lo")
    if hv is not None and hv > N1_RHO_BAND:
        return {"label": "DEAD", "rule": "rho_hon point > 0.15", "deciding_number": hv,
                "deciding_path": f"{path}.rho_hon.value"}
    if hv is None or not rh.get("ci_reported") or not rp.get("ci_reported") or plo is None:
        return {"label": "INCONCLUSIVE", "rule": "a CI needed by the rule is not reportable",
                "deciding_number": {"rho_hon_valid_draws": rh.get("valid_draws"),
                                    "rho_pc_valid_draws": rp.get("valid_draws")},
                "deciding_path": [f"{path}.rho_hon.valid_draws", f"{path}.rho_pc.valid_draws"]}
    if plo <= hhi:
        return {"label": "DEAD", "rule": "rho_pc CI lo <= rho_hon CI hi",
                "deciding_number": {"rho_pc_lo": plo, "rho_hon_hi": hhi},
                "deciding_path": [f"{path}.rho_pc.lo", f"{path}.rho_hon.hi"]}
    fh = hi_used(fl)
    conds = [("rho_hon CI within [-0.15, 0.15]", hlo >= -N1_RHO_BAND and hhi <= N1_RHO_BAND, [hlo, hhi]),
             ("rho_pc CI lo >= 0.30", plo >= N1_PC_LO, plo),
             ("coverage RR >= 0.10", rr.get("rate") is not None and rr["rate"] >= N1_RR, rr.get("rate")),
             ("honest flag rate <= 0.02", fl.get("rate") is not None and fl["rate"] <= N1_FLAG_PT, fl.get("rate")),
             ("honest flag rate CI hi <= 0.05", fh is not None and fh <= N1_FLAG_HI, fh)]
    failing = [c for c in conds if not c[1]]
    rec = [{"condition": c[0], "met": bool(c[1]), "value": c[2]} for c in conds]
    if not failing:
        return {"label": "ALIVE", "rule": "every ALIVE condition met", "conditions": rec,
                "deciding_number": {c[0]: c[2] for c in conds}, "deciding_path": path}
    if abs(hv) <= N1_RHO_BAND:
        return {"label": "WEAK", "rule": "ALIVE condition(s) failing: " + "; ".join(c[0] for c in failing),
                "conditions": rec, "deciding_number": {c[0]: c[2] for c in failing}, "deciding_path": path}
    return {"label": "INCONCLUSIVE", "rule": "rule gap: rho_hon point < -0.15", "deciding_number": hv,
            "deciding_path": f"{path}.rho_hon.value", "conditions": rec}


# ---------------------------------------------------------------------------------------------------- N2
def n2_extract(unit, u, Q):
    resp = pe.response_table(unit, u)
    gran = pe.granularity(resp)
    if not len(resp):
        return pd.DataFrame(), gran, {"responses": 0}
    rcm = {(s, c): len(t) for s, c, t in zip(Q.session_id, Q.call_id, Q.text_r.astype(object)) if isinstance(t, str)}
    attr = {(s, c): (bool(tr), bool(jc), k) for s, c, tr, jc, k in zip(Q.session_id, Q.call_id, Q.trunc, Q.join_clean,
                                                                       Q.key)}
    resp = resp.copy()
    resp["last_call_id"] = resp.last_call_id.astype(str)
    resp["rc"] = [rcm.get((s, c), np.nan) for s, c in zip(resp.session_id, resp.last_call_id)]
    base = pe.n2_flags(resp, rcm, TAU[unit])
    E = pd.DataFrame(base, columns=["session_id", "resp", "flag"])
    if not len(E):
        return E, gran, {"responses": int(len(resp))}
    R = resp.set_index(["session_id", "resp"])
    idx = pd.MultiIndex.from_arrays([E.session_id, E.resp])
    for c in ("usage_out", "chars_out", "rc", "last_call_id"):
        E[c] = R[c].reindex(idx).to_numpy()
    at = [attr.get((s, c), (False, True, None)) for s, c in zip(E.session_id, E.last_call_id)]
    E["trunc"] = [a[0] for a in at]
    E["join_clean"] = [a[1] for a in at]
    E["key"] = [a[2] for a in at]
    E["U"] = E.usage_out.astype(float) - TAU[unit] * E.chars_out.astype(float)
    for tp in N2_TAU_PRIME:
        extra = {(s, r): pe.atk_inline_fabrication(None, rc_, tp * TAU[unit]) for s, r, rc_ in
                 zip(E.session_id, E.resp, E.rc)}
        sub = resp[[(s, r) in extra for s, r in zip(resp.session_id, resp.resp)]]
        f = pe.n2_flags(sub, rcm, TAU[unit], extra_out=extra)
        fm = {(s, r): v for s, r, v in f}
        E[f"flag_pc_{tp:g}"] = [fm[(s, r)] for s, r in zip(E.session_id, E.resp)]
    return E, gran, {"responses": int(len(resp)), "responses_sessions": int(resp.session_id.nunique())}


def n2_measure(E, unit, gran, path, full=True):
    if not gran.get("GRANULAR"):
        return {"granularity": gran, "verdict": {"label": "DEAD", "rule": "not GRANULAR: per-turn counts absent",
                                                 "deciding_number": gran, "deciding_path": f"{path}.granularity"}}
    e = E if len(E) else pd.DataFrame(columns=["session_id", "flag", "flag_pc_1", "flag_pc_0.8", "U", "rc"])
    out = {"granularity": gran, "tau_A": TAU[unit], "eligible_responses": int(len(e)),
           "eligible_sessions": int(e.session_id.nunique())}
    out["honest_flag_rate"] = crate(e.flag.astype(bool), e.session_id)
    for tp in N2_TAU_PRIME:
        out[f"recall_tau_prime_{tp:g}"] = crate(e[f"flag_pc_{tp:g}"].astype(bool), e.session_id)
    if full and len(e):
        out["U_over_tau_rc_quantiles"] = qtiles((e.U / (TAU[unit] * e.rc.astype(float))).to_numpy(float))
        out["result_chars_quantiles"] = qtiles(e.rc)
        out["flagged_by_last_call_key"] = {str(k): int(v) for k, v in
                                           e[e.flag.astype(bool)].key.value_counts().head(10).items()}
    out["verdict"] = n2_verdict(out, path)
    return out


def n2_verdict(b, path):
    n, ns = b["eligible_responses"], b["eligible_sessions"]
    if n < N2_MIN[0] or ns < N2_MIN[1]:
        return {"label": "INSUFFICIENT_N", "rule": f"min n: >= {N2_MIN[0]} eligible responses from >= {N2_MIN[1]} s",
                "deciding_number": {"responses": n, "sessions": ns},
                "deciding_path": [f"{path}.eligible_responses", f"{path}.eligible_sessions"]}
    fr = b["honest_flag_rate"]
    r08 = b["recall_tau_prime_0.8"].get("rate")
    h = hi_used(fr)
    if fr["rate"] <= N2_FLAG_PT and h is not None and h <= N2_FLAG_HI and r08 is not None and r08 >= N2_REC_ALIVE:
        return {"label": "ALIVE", "rule": "flag <= 0.05, CI hi <= 0.10, recall(0.8 tau) >= 0.90",
                "deciding_number": {"flag_rate": fr["rate"], "flag_hi": h, "recall_0.8tau": r08}, "deciding_path": path}
    if fr["rate"] <= N2_WEAK_FLAG and r08 is not None and r08 >= N2_REC_WEAK:
        return {"label": "WEAK", "rule": "flag <= 0.20 and recall(0.8 tau) >= 0.50; ALIVE fails",
                "deciding_number": {"flag_rate": fr["rate"], "flag_hi": h, "recall_0.8tau": r08}, "deciding_path": path}
    why = []
    if fr["rate"] > N2_WEAK_FLAG:
        why.append("honest flag rate > 0.20")
    if r08 is None or r08 < N2_REC_WEAK:
        why.append("recall at 0.8 tau < 0.50")
    return {"label": "DEAD", "rule": "; ".join(why), "deciding_number": {"flag_rate": fr["rate"], "recall_0.8tau": r08},
            "deciding_path": [f"{path}.honest_flag_rate.rate", f"{path}.recall_tau_prime_0.8.rate"]}


# ---------------------------------------------------------------------------------------------------- N3
def n3_extract(u, Q):
    g = pe.n3_gaps(u)
    G = pd.DataFrame(g, columns=["session_id", "gap", "bytes"])
    is_res = (u.kind == "result").to_numpy()
    tr = np.zeros(len(u), dtype=bool)
    txt, ex = u.text.astype(object).to_numpy(), u.extra.astype(object).to_numpy()
    for i in np.flatnonzero(is_res):
        tr[i] = pe.truncated_result(txt[i], ex[i])
    G2 = pd.DataFrame(pe.n3_gaps(u[~tr]), columns=["session_id", "gap", "bytes"])
    clean_keys = set(zip(Q.session_id[Q.join_clean.to_numpy()], Q.call_id[Q.join_clean.to_numpy()]))
    keep = np.array([(not r) or ((s, str(c)) in clean_keys) for r, s, c in
                     zip(is_res, u.session_id, u.call_id.astype(object))])
    G3 = pd.DataFrame(pe.n3_gaps(u[keep]), columns=["session_id", "gap", "bytes"])
    return {"all": G, "AC2": G2, "AC3": G3}


def per_session_rho(ge, permute=False):
    out = {}
    for s, x in ge.groupby("session_id", sort=True):
        gg = x.gap.to_numpy(float)
        if permute:
            gg = gg[pe.rng_for("N3pc", s, "gaps").permutation(len(gg))]
        out[s] = pe.spearman(gg, x.bytes.to_numpy(float))
    return out


def n3_measure(G, path, full=True):
    g = G if len(G) else pd.DataFrame(columns=["session_id", "gap", "bytes"])
    n_by = g.groupby("session_id").size()
    elig = set(n_by[n_by >= N3_MIN_GAPS].index)
    ge = g[g.session_id.isin(elig)]
    out = {"gaps": int(len(g)), "sessions_with_gaps": int(len(n_by)), "eligible_sessions": int(len(elig)),
           "eligible_gaps": int(len(ge))}
    rs = per_session_rho(ge)
    d = {s: r for s, r in rs.items() if r is not None}
    k = sum(1 for r in d.values() if r <= 0)
    out["rho_s"] = {"n_defined": len(d), "n_undefined": len(rs) - len(d), "quantiles": qtiles(list(d.values()))}
    out["share_rho_s_le_0"] = wil(k, len(d))
    out["rho_pooled"] = rho(ge.gap, ge.bytes, ge.session_id)
    if full:
        out["gap_s_quantiles"] = qtiles(ge.gap, ge.session_id.tolist())
        out["rho_pooled_all_sessions"] = rho(g.gap, g.bytes, g.session_id)
        pr = per_session_rho(ge, permute=True)
        pd_ = {s: r for s, r in pr.items() if r is not None}
        out["positive_control_permutation"] = {"recall": wil(sum(1 for r in pd_.values() if r <= 0), len(pd_)),
                                               "rule": "within-session permutation, rng_for('N3pc', session, 'gaps')"}
        out["secondary_usage_adjusted"] = {"label": "NOT_RUN", "reason": "needs G50 (Phase B generation rate), which "
                                                                        "is not defined for this unit (D1)"}
    out["verdict"] = n3_verdict(out, path)
    return out


def n3_verdict(b, path):
    if b["eligible_sessions"] < N3_MIN_SESS:
        return {"label": "INSUFFICIENT_N", "rule": f"min n: >= {N3_MIN_SESS} sessions with >= {N3_MIN_GAPS} gaps",
                "deciding_number": b["eligible_sessions"], "deciding_path": f"{path}.eligible_sessions"}
    rp = b["rho_pooled"]
    if not rp.get("ci_reported") or rp.get("lo") is None:
        return {"label": "INCONCLUSIVE", "rule": "pooled-rho CI not reportable", "deciding_number": rp.get("valid_draws"),
                "deciding_path": f"{path}.rho_pooled.valid_draws"}
    lo, sh = rp["lo"], b["share_rho_s_le_0"]
    if lo >= N3_ALIVE_LO and sh["share"] is not None and sh["share"] <= N3_SHARE_PT and sh["hi"] <= N3_SHARE_HI:
        return {"label": "ALIVE", "rule": "pooled rho CI lo >= 0.30 and share(rho_s <= 0) <= 0.10 (hi <= 0.20)",
                "deciding_number": {"rho_pooled_lo": lo, "share": sh["share"], "share_hi": sh["hi"]},
                "deciding_path": path}
    if lo > 0:
        return {"label": "WEAK", "rule": "pooled rho CI lo > 0; ALIVE fails",
                "deciding_number": {"rho_pooled_lo": lo, "share": sh["share"], "share_hi": sh["hi"]},
                "deciding_path": f"{path}.rho_pooled.lo"}
    return {"label": "DEAD", "rule": "pooled rho CI lo <= 0", "deciding_number": lo,
            "deciding_path": f"{path}.rho_pooled.lo"}


# ---------------------------------------------------------------------------------------------------- N5
def _one_row(text):
    return pd.DataFrame({"text": [text]}, index=[0])


def n5_extract(unit, u, Q):
    out = {}
    # a determinism
    dp = pe.determinism_pairs(unit, u, Q)
    jc = dict(zip(zip(Q.session_id, Q.seq), Q.join_clean))
    keyof = dict(zip(zip(Q.session_id, Q.seq), Q.key))
    rows = []
    for sid, sa, sb, nk, ta, tb in dp:
        drift = pe.mask_volatile(ta) != pe.mask_volatile(tb)
        tb2, ok = pe.atk_digit(_one_row(tb), 0)
        tb2 = tb2.at[0, "text"]
        rows.append({"session_id": sid, "seq_a": sa, "seq_b": sb, "key": keyof.get((sid, sa)), "drift": bool(drift),
                     "identical": ta == tb, "pc_tamperable": bool(ok),
                     "pc_flag": bool(ok and pe.mask_volatile(ta) != pe.mask_volatile(tb2)),
                     "join_clean": bool(jc.get((sid, sa), True) and jc.get((sid, sb), True)), "trunc": False})
    out["a"] = pd.DataFrame(rows, columns=["session_id", "seq_a", "seq_b", "key", "drift", "identical", "pc_tamperable",
                                           "pc_flag", "join_clean", "trunc"])
    # b sort, d whitespace, c truncation, e size, comparator
    brows, drows, crows, erows = [], [], [], []
    for sid, cid, k, a, cmd, t, tr, jcl, seq in zip(Q.session_id, Q.call_id, Q.key, Q.args.astype(object),
                                                     Q.command.astype(object), Q.text_r.astype(object), Q.trunc,
                                                     Q.join_clean, Q.seq):
        sc = pc.shell_command(unit, k, pc.jl(a) if isinstance(a, str) else {}, cmd) if is_shell(k) else None
        if sc:
            for name, fn in (("ls", pe.ls_order_violation), ("git_log", pe.gitlog_order_violation),
                             ("grep_n", pe.grepn_order_violation)):
                v = fn(sc, t)
                if v is not None:
                    t2, ok = pe.atk_reorder_lines(_one_row(t), 0, pe.rng_for("N5bpc", sid, cid, name))
                    pv = fn(sc, t2.at[0, "text"]) if ok else None
                    brows.append({"session_id": sid, "call_id": cid, "checker": name, "key": k, "violation": bool(v),
                                  "pc_eligible": bool(ok and pv is not None), "pc_flag": bool(pv) if pv is not None
                                  else False, "trunc": bool(tr), "join_clean": bool(jcl)})
            ws = pe.ws_violations(sc, t)
            if ws:
                wsn = pe.ws_violations(sc, pe.normalize_ws(t))
                for name, v in ws.items():
                    drows.append({"session_id": sid, "call_id": cid, "checker": name, "key": k, "violation": bool(v),
                                  "pc_eligible": name in wsn, "pc_flag": bool(wsn.get(name, False)), "trunc": bool(tr),
                                  "join_clean": bool(jcl)})
            progs = pe.command_programs(sc)
            if progs:
                f = progs[0][0]
                if f == "git":
                    m = re.search(r"\bgit\s+(?:-C\s+\S+\s+|--no-pager\s+)*([a-z\-]+)", progs[0][1])
                    f = "git " + (m.group(1) if m else "?")
                b = len(t.encode("utf-8")) if isinstance(t, str) else 0
                erows.append({"session_id": sid, "call_id": cid, "family": f, "bytes": b,
                              "log_b": math.log10(b + 1), "trunc": bool(tr), "join_clean": bool(jcl), "key": k})
        if k == "grep":
            v = pe.grepn_order_violation(a, t, is_grep_tool=True)
            if v is not None:
                t2, ok = pe.atk_reorder_lines(_one_row(t), 0, pe.rng_for("N5bpc", sid, cid, "grep_n"))
                pv = pe.grepn_order_violation(a, t2.at[0, "text"], is_grep_tool=True) if ok else None
                brows.append({"session_id": sid, "call_id": cid, "checker": "grep_n", "key": k, "violation": bool(v),
                              "pc_eligible": bool(ok and pv is not None), "pc_flag": bool(pv) if pv is not None
                              else False, "trunc": bool(tr), "join_clean": bool(jcl)})
        ti = pe.truncation_info(t)
        if ti:
            ex = None
            if ti["item"] == "cc_chars_mid":
                ex = (ti["prefix_u16"] == N5C["cc_chars_mid"]["prefix_u16"]
                      and ti["suffix_u16"] == N5C["cc_chars_mid"]["suffix_u16"])
            elif ti["item"] == "cc_glob_cap":
                ex = ti["lines"] == N5C["cc_glob_cap"]["lines"]
            crows.append({"session_id": sid, "call_id": cid, "item": ti["item"], "key": k, "exact": ex,
                          "join_clean": bool(jcl), "trunc": True})
        elif isinstance(t, str) and not tr:
            # N5c positive control (phase_e_n4_n5cg.py construction): re-truncate long non-truncated results
            L16 = pe.utf16_len(t)
            if L16 >= 10004 and len(t) >= 2:
                rng = pe.rng_for("N5cpc", sid, cid, "cc_chars_mid")
                L = len(t)
                aa = int(rng.integers(0, L + 1))
                bb = int(rng.integers(0, L - aa + 1))
                t2 = t[:aa] + f"\n\n... [{L - aa - bb} characters truncated] ...\n\n" + t[L - bb:]
                ti2 = pe.truncation_info(t2)
                okx = bool(ti2 and ti2["item"] == "cc_chars_mid" and ti2["prefix_u16"] ==
                           N5C["cc_chars_mid"]["prefix_u16"] and ti2["suffix_u16"] == N5C["cc_chars_mid"]["suffix_u16"])
                crows.append({"session_id": sid, "call_id": cid, "item": "pc_cc_chars_mid", "key": k, "exact": okx,
                              "join_clean": bool(jcl), "trunc": False})
    out["b"] = pd.DataFrame(brows, columns=["session_id", "call_id", "checker", "key", "violation", "pc_eligible",
                                            "pc_flag", "trunc", "join_clean"])
    out["d"] = pd.DataFrame(drows, columns=["session_id", "call_id", "checker", "key", "violation", "pc_eligible",
                                            "pc_flag", "trunc", "join_clean"])
    out["c"] = pd.DataFrame(crows, columns=["session_id", "call_id", "item", "key", "exact", "join_clean", "trunc"])
    out["e"] = pd.DataFrame(erows, columns=["session_id", "call_id", "family", "bytes", "log_b", "trunc",
                                            "join_clean", "key"])
    comp = []
    a_ = u[(u.kind == "assistant").to_numpy() & u.text.notna().to_numpy()]
    for s, t in zip(a_.session_id, a_.text.astype(object)):
        if isinstance(t, str):
            b = len(t.encode("utf-8"))
            comp.append({"session_id": s, "source": "assistant", "bytes": b, "log_b": math.log10(b + 1)})
    for s, k, t in zip(Q.session_id, Q.key, Q.text_r.astype(object)):
        if k == "subagent" and isinstance(t, str):
            b = len(t.encode("utf-8"))
            comp.append({"session_id": s, "source": "subagent_result", "bytes": b, "log_b": math.log10(b + 1)})
    out["e_comp"] = pd.DataFrame(comp, columns=["session_id", "source", "bytes", "log_b"])
    # g cold start (+ positive control)
    q = Q[Q.qualified]
    cs = pe.cold_start_values(q)
    grow = []
    for sid, t, c in cs:
        h = q[(q.session_id == sid) & (q.key == t)].sort_values("seq")
        lg = np.log10(h.delta_s.to_numpy(dtype=float))
        j = 1 + int(pe.rng_for("N5gpc", sid, t).integers(0, len(lg) - 1))
        cpc = float(lg[j] - np.median(lg[1:]))
        grow.append({"session_id": sid, "key": t, "c_s": c, "c_pc": cpc,
                     "first_trunc": bool(h.trunc.iloc[0]), "first_join_clean": bool(h.join_clean.iloc[0])})
    out["g"] = pd.DataFrame(grow, columns=["session_id", "key", "c_s", "c_pc", "first_trunc", "first_join_clean"])
    out["g_q"] = q[["session_id", "seq", "key", "delta_s", "trunc", "join_clean", "result_chars"]].reset_index(drop=True)
    return out


def n5a_measure(T, path):
    t = T if len(T) else T
    r = crate(t.drift.astype(bool), t.session_id) if len(t) else {"rate": None, "num": 0, "den": 0, "n_sessions": 0}
    out = {"pairs": int(len(t)), "sessions": int(t.session_id.nunique()) if len(t) else 0, "drift": r,
           "byte_identical_share": wil(int(t.identical.sum()), len(t)) if len(t) else None}
    pt = t[t.pc_tamperable.astype(bool)] if len(t) else t
    out["positive_control_digit"] = crate(pt.pc_flag.astype(bool), pt.session_id) if len(pt) else None
    out["verdict"] = three_rate_label(r, N5_TH["a"], N5_MIN["a"]) if r.get("rate") is not None else \
        {"label": "INSUFFICIENT_N", "rule": "no determinism pairs", "deciding_number": {"n": 0}}
    out["verdict"]["deciding_path"] = f"{path}.drift"
    return out


def n5_checker_measure(T, item, path):
    out = {"per_checker": {}}
    labs = {}
    checkers = ("ls", "git_log", "grep_n") if item == "b" else ("ls_long_alignment", "git_status_tab", "wc_alignment",
                                                                   "pytest_banner")
    for ch in checkers:
        t = T[T.checker == ch] if len(T) else T
        if not len(t):
            out["per_checker"][ch] = {"outputs": 0, "verdict": {"label": "INSUFFICIENT_N", "rule": "no eligible output",
                                                                "deciding_number": {"n": 0},
                                                                "deciding_path": f"{path}.per_checker.{ch}"}}
            labs[ch] = "INSUFFICIENT_N"
            continue
        r = crate(t.violation.astype(bool), t.session_id)
        pe_ = t[t.pc_eligible.astype(bool)]
        b = {"outputs": int(len(t)), "sessions": int(t.session_id.nunique()), "violation": r,
             "positive_control_recall": crate(pe_.pc_flag.astype(bool), pe_.session_id) if len(pe_) else None,
             "by_key": {str(k): int(v) for k, v in t.key.value_counts().items()}}
        b["verdict"] = three_rate_label(r, N5_TH[item], N5_MIN[item])
        b["verdict"]["deciding_path"] = f"{path}.per_checker.{ch}.violation"
        out["per_checker"][ch] = b
        labs[ch] = b["verdict"]["label"]
    low = lowest(labs.values())
    out["verdict"] = {"label": low or "INSUFFICIENT_N", "rule": "lowest checker label among ALIVE/WEAK/DEAD checkers",
                      "per_checker_labels": labs, "deciding_path": f"{path}.per_checker"}
    return out


def n5c_measure(T, path):
    out = {"per_item": {}}
    labs = {}
    for item in ("cc_chars_mid", "cc_glob_cap"):
        t = T[T.item == item] if len(T) else T
        pcn = T[T.item == f"pc_{item}"] if len(T) else T
        if not len(t):
            out["per_item"][item] = {"marked": 0, "verdict": {"label": "INSUFFICIENT_N", "rule": "no marked result",
                                                              "deciding_number": {"n": 0},
                                                              "deciding_path": f"{path}.per_item.{item}"}}
            labs[item] = "INSUFFICIENT_N"
            continue
        inexact = ~t.exact.astype(bool)
        r = crate(inexact, t.session_id)
        n, ns = int(len(t)), int(t.session_id.nunique())
        ex_pt = 1 - r["rate"]
        ex_lo = 1 - (hi_used(r) if hi_used(r) is not None else 1)
        b = {"marked": n, "sessions": ns, "inexact_rate": r, "exactness": ex_pt, "exactness_ci_lo": ex_lo,
             "constant": N5C[item], "positive_control_recall_inexact":
                 crate(~pcn.exact.astype(bool), pcn.session_id) if len(pcn) else None}
        if n < N5_MIN["c"][0] or ns < N5_MIN["c"][1]:
            v = {"label": "INSUFFICIENT_N", "rule": ">= 50 marked results from >= 10 sessions",
                 "deciding_number": {"n": n, "sessions": ns}}
        elif ex_pt >= 0.99 and ex_lo >= 0.95:
            v = {"label": "ALIVE", "rule": "exactness >= 0.99 with CI lo >= 0.95",
                 "deciding_number": {"exactness": ex_pt, "ci_lo": ex_lo}}
        elif ex_pt >= 0.90:
            v = {"label": "WEAK", "rule": "exactness >= 0.90", "deciding_number": {"exactness": ex_pt, "ci_lo": ex_lo}}
        else:
            v = {"label": "DEAD", "rule": "exactness < 0.90", "deciding_number": {"exactness": ex_pt}}
        v["deciding_path"] = f"{path}.per_item.{item}"
        b["verdict"] = v
        out["per_item"][item] = b
        labs[item] = v["label"]
    tail = T[T.item == "cc_lines_tail"] if len(T) else T
    out["per_item"]["cc_lines_tail"] = {"marked": int(len(tail)), "verdict": {
        "label": "NOT_RUN", "rule": "A constant INSUFFICIENT_N (resolved.n5.truncation_constants_pooled.cc_lines_tail)"}}
    low = lowest(labs.values())
    out["verdict"] = {"label": low or "INSUFFICIENT_N", "rule": "lowest sub-item label among ALIVE/WEAK/DEAD sub-items",
                      "per_item_labels": labs, "deciding_path": f"{path}.per_item"}
    return out


def iqr(v):
    v = np.asarray(v, dtype=float)
    return float(np.quantile(v, 0.75) - np.quantile(v, 0.25)) if len(v) else None


def n5e_measure(T, C, path):
    out = {"families": {}}
    comp = C
    cn, cs = int(len(comp)), int(comp.session_id.nunique()) if len(comp) else 0
    groups = [g.log_b.to_numpy(float) for _, g in comp.groupby("session_id")] if len(comp) else []
    cb = pe.boot_stat(groups, lambda gs: iqr(np.concatenate(gs)) if gs else None) if groups else {"value": None}
    out["comparator"] = {"texts": cn, "sessions": cs, "iqr_log10_bytes": cb,
                         "by_source": {str(k): int(v) for k, v in comp.source.value_counts().items()} if cn else {}}
    fams = []
    if len(T):
        for f, g in T.groupby("family"):
            n, ns = int(len(g)), int(g.session_id.nunique())
            if n >= N5E_FAM_MIN[0] and ns >= N5E_FAM_MIN[1]:
                v = iqr(g.log_b)
                fams.append((f, v))
                out["families"][f] = {"results": n, "sessions": ns, "iqr_log10_bytes": v}
    out["qualifying_families"] = len(fams)
    if not fams:
        v = {"label": "INSUFFICIENT_N", "rule": "no family with >= 100 results from >= 10 sessions"}
    elif cn < N5E_COMP_MIN[0] or cs < N5E_COMP_MIN[1] or not cb.get("ci_reported"):
        v = {"label": "INCONCLUSIVE", "rule": "comparator below 30 texts / 5 sessions or CI not reportable",
             "deciding_number": {"texts": cn, "sessions": cs}}
    else:
        above = sum(1 for _, x in fams if x > cb["hi"])
        share = above / len(fams)
        v = {"label": "WEAK" if share >= 0.5 else "DEAD", "rule": ">= 0.5 of families above the comparator CI hi -> "
                                                                  "WEAK (cap), else DEAD",
             "deciding_number": {"families_above": above, "families": len(fams), "share": share,
                                 "comparator_hi": cb["hi"]}}
    v["deciding_path"] = path
    out["verdict"] = v
    return out


def n5g_measure(T, path):
    n = int(len(T))
    out = {"eligible_sessions": n}
    if n:
        cq = stats.cluster_quantile(T.c_s.to_numpy(float), T.session_id.to_numpy(), 0.5)
        k = int((T.c_s <= 0).sum())
        out["median_c"] = cq
        out["share_c_le_0"] = wil(k, n)
        out["positive_control_recall"] = wil(int((T.c_pc <= 0).sum()), n)
        out["c_quantiles"] = qtiles(T.c_s)
    if n < N5G_MIN:
        v = {"label": "INSUFFICIENT_N", "rule": f">= {N5G_MIN} sessions", "deciding_number": n}
    elif out["median_c"]["lo"] >= N5G_ALIVE_C and out["share_c_le_0"]["share"] <= N5G_ALIVE_SHARE:
        v = {"label": "ALIVE", "rule": "median c CI lo >= log10 1.5 and share(c_s <= 0) <= 0.05",
             "deciding_number": {"median_lo": out["median_c"]["lo"], "share": out["share_c_le_0"]["share"]}}
    elif out["median_c"]["lo"] > 0:
        v = {"label": "WEAK", "rule": "median c CI lo > 0",
             "deciding_number": {"median_lo": out["median_c"]["lo"], "share": out["share_c_le_0"]["share"]}}
    else:
        v = {"label": "DEAD", "rule": "median c CI lo <= 0", "deciding_number": out["median_c"]["lo"]}
    v["deciding_path"] = path
    out["verdict"] = v
    return out


# ---------------------------------------------------------------------------------------------------- Probe 2 / 4
def p2_extract(unit, u):
    cols = ["session_id", "seq", "kind", "tool", "tool_raw", "call_id", "args", "command", "text", "stderr",
            "native_error", "exit_code", "is_subagent", "agent_id", "extra", "stratum"]
    uu = u[u.kind.isin(["user", "system", "call", "result"])][cols]
    A = {"sessions": set(), "threads": {"main": set(), "sub": set()}, "refs": [], "access": [],
         "calls": Counter(), "calls_with_any_reference": Counter(), "calls_with": Counter(),
         "redacted_path": Counter(), "redacted_ref": Counter(), "redacted_ref_first": Counter(),
         "root_status": Counter()}
    p2.process_unit(unit, uu, A)
    R, X = p2.ref_frame(A["refs"]), p2.acc_frame(A["access"])
    meta = {"sessions": len(A["sessions"]), "threads_with_calls": {k: len(v) for k, v in A["threads"].items()},
            "calls": dict(A["calls"]), "redacted_path": dict(A["redacted_path"]),
            "sessions_with_workspace_root": A["root_status"].get("session_root_found", 0)}
    return R, X, meta


P2_INSTR = json.loads((pe.ROOT / "analysis" / "out" / "probe_2.json").read_text(encoding="utf-8"))["instrument_check"]


def p2_measure(unit, R, X, path):
    out = {"D_unit": P2_D_POOLED, "D_source": "prereg.json resolved.probe2.depth_threshold.pooled.D (D1)",
           "instrument_check": {"ok": bool(P2_INSTR.get("ok")), "source": "analysis/out/probe_2.json instrument_check "
                                                                          "(Phase B, swechat/claude_code main)"}}
    for st in ("main", "sub"):
        if not len(R) and not len(X):
            z = {"k": 0, "n": 0, "n_sessions": 0}
            out[st] = {"first_mentions": 0, "first_accesses": 0,
                       "verdict": p2.verdict(unit, z, z, bool(P2_INSTR.get("ok")), st)}
            continue
        b, sd, sa = p2.stratum_block(unit, st, R if len(R) else p2.ref_frame([]), X if len(X) else p2.acc_frame([]),
                                     P2_D_POOLED, False)
        v = p2.verdict(unit, sd, sa, bool(P2_INSTR.get("ok")), st)
        keep = {"S_deep": b["deep_first_try"].get("S_deep"),
                "deep_first_try": {k: b["deep_first_try"].get(k) for k in
                                   ("n_first_accesses", "n_sessions", "first_try_success", "n_deep",
                                    "n_deep_success", "error_class_counts", "pair_missing", "depth_unknown")},
                "S_path_any": b["S_path_any"], "S_symbol_ref": b["S_symbol_ref"], "S_env_cfg": b["S_env_cfg"],
                "classes_unsourced": {c: (x.get("unsourced"), x.get("n_first_mentions"))
                                      for c, x in b["classes"].items() if isinstance(x, dict)},
                "post_hoc_descriptive": b.get("post_hoc_descriptive"), "verdict": v}
        out[st] = keep
    return out


def p4_extract(unit, u):
    uu = u[u.kind.isin(p4.KINDS)][p4.COLS]
    acc = p4.extract(unit, uu, False)
    acc.f3 = f3_param_values(u)
    acc.f3["cal_round_counts_check"] = pecal.cal_round(unit, u)
    return acc


def f3_param_values(u):
    """The loop of prereg_e_calibration.cal_round (frozen classify_args_ints), returning the sets: distinct T_orig
    values (args integers not seen earlier in the session's result/stderr/user/system text) and those with >= 1
    parameter occurrence (strict rule) / whose first occurrence is a parameter."""
    u = u.sort_values(["session_id", "seq"])
    first, anyp = {}, defaultdict(bool)
    for sid, g in u.groupby("session_id", sort=False):
        anc = set()
        for kind, txt, err, a in zip(g.kind, g.text.astype(object), g.stderr.astype(object), g.args.astype(object)):
            if kind in ("result", "user", "system"):
                for t in ([txt] + ([err] if kind == "result" else [])):
                    if isinstance(t, str):
                        anc.update(pc.large_ints(t))
            elif kind == "call":
                for v, origin, pk in pe.classify_args_ints(a):
                    if v in anc:
                        continue
                    if v not in first:
                        first[v] = (origin, pk is not None)
                    anyp[v] |= pk is not None
    return {"values": set(first), "strict_param": {v for v in first if anyp[v]},
            "first_param": {v for v, (o, pp) in first.items() if pp}}


def f3_context(acc_ints, f3, path):
    """F3 parameter-exclusion statistic (followups.F3) computed as CONTEXT for the P4b cell: the prereg assigns F3 to
    the A1 candidates only, so this never changes the N6 cell."""
    T = acc_ints["main"]["T_orig"]
    M = acc_ints["main"]["M_all"]
    Tn = {v: x for v, x in T.items() if v not in f3["strict_param"]}
    Tf = {v: x for v, x in T.items() if v not in f3["first_param"]}
    rT, rM, rN, rF = (p4.int_class_row(d, P4_TH) for d in (T, M, Tn, Tf))
    lab_full = p4.round_verdict(rT, rM, P4_TH)
    lab_np = p4.round_verdict(rN, rM, P4_TH)
    pm = rM.get("round", {}).get("last_0", {}).get("rate")
    pt = rT.get("round", {}).get("last_0", {}).get("rate")
    pn = rN.get("round", {}).get("last_0", {}).get("rate")
    g_full = (pt - pm) if (pt is not None and pm is not None) else None
    g = (pn - pm) if (pn is not None and pm is not None) else None
    if lab_np[0] == "INSUFFICIENT_N":
        f3lab = "INSUFFICIENT_N (cap WEAK: parameter-confounded, residual untestable)"
    elif lab_np[0] == "DEAD" or (g is not None and g_full is not None and g <= 0.25 * g_full):
        f3lab = "DEAD (collapse)"
    elif lab_np[0] == "ALIVE" and g is not None and g_full and g >= 0.5 * g_full:
        f3lab = "ALIVE"
    else:
        f3lab = "WEAK"
    return {"note": "CONTEXT ONLY: prereg_e.json followups.F3 rule applied to this cell's data; F3 is pre-registered "
                    "for A1 candidates, not for N6 cells, so the cell keeps the Phase B rule label",
            "T_orig_distinct": len(T), "excluded_strict": len(set(T) & f3["strict_param"]),
            "remaining_strict": len(Tn), "remaining_first_occurrence_rule": len(Tf),
            "p_T_orig_last0": pt, "p_T_noparam_last0": pn, "p_M_all_last0": pm, "g": g, "g_full": g_full,
            "round_rule_on_remaining": {"label": lab_np[0], "reason": lab_np[1]},
            "round_rule_first_occurrence_variant": p4.round_verdict(rF, rM, P4_TH)[0],
            "F3_rule_label": f3lab, "path": path}


P4_PR, P4_TH, P4_PROV = p4.load_prereg()


def p4_measure(hexd, intd, path, labels):
    vals = p4.summarise_values(hexd, intd, P4_TH)
    vb = p4.verdict_block(vals, P4_TH, False, labels)
    keep = {"hex": {c: {k: v for k, v in vals["main"]["hex"][c].items() if k not in ("observed_symbol_counts",
                                                                                      "expected_symbol_counts")}
                    for c in ("T_orig", "T_copy", "M_git", "M_all")},
            "ints": {c: {k: v for k, v in vals["main"]["ints"][c].items() if k in ("distinct_values", "sessions", "round")}
                     for c in ("T_orig", "M_all")},
            "verdicts": vb, "thresholds": {k: P4_TH[k] for k in ("N_min", "instrument_ceiling", "alive_w", "round_margin",
                                                                  "round_min_values", "round_min_sessions")}}
    return keep


# ===================================================================================================== R1
def r1_frames(u, stratum):
    s = u[u.stratum.astype(str) == stratum].copy()
    v = s[["session_id", "seq", "kind", "ts", "request_id", "is_subagent", "agent_id", "call_id", "parent_call_id",
           "text", "extra", "uuid", "tool", "tool_raw", "args", "command", "api_msg_id", "stratum", "native_error",
           "exit_code", "stderr", "model"]].copy()
    v["ts"] = pd.Series([t if isinstance(t, str) else None for t in v.ts.astype(object)], index=v.index, dtype=object)
    v["request_id"] = pd.Series([t if isinstance(t, str) else None for t in v.request_id.astype(object)],
                                index=v.index, dtype=object)
    v["call_id"] = pd.Series([t if isinstance(t, str) else None for t in v.call_id.astype(object)], index=v.index,
                             dtype=object)
    v["_st"] = pe._stream(v.is_subagent, v.agent_id)
    return v


def honest_block(R, S):
    inc = S.inconsistent.to_numpy() if len(S) else np.array([], dtype=bool)
    cons = S[~S.inconsistent] if len(S) else S
    return {"responses_decoded": int(len(R)), "sessions_with_decoded_responses": int(R.session_id.nunique()),
            "streams_ge2": int(len(S)), "streams_main": int((S.stream == "main").sum()) if len(S) else 0,
            "sessions_with_streams": int(S.session_id.nunique()) if len(S) else 0,
            "inconsistent_streams": int(inc.sum()), "rate_by_session": crate(inc, S.session_id.to_numpy() if len(S)
                                                                             else []),
            "wilson_per_stream": wil(int(inc.sum()), len(S)),
            "tolerance_sensitivity_streams_over": {str(t): int((np.isfinite(S.gap) & (S.gap > t)).sum()) if len(S)
                                                   else 0 for t in (0, 1000, 2000, 3000, 5000, 10000, 60000)},
            "slack_U_minus_L_consistent_ms": qtiles((cons.U - cons.L).to_numpy() if len(cons) else [],
                                                    cons.session_id.to_numpy() if len(cons) else None)}


def placebo_block(R):
    out = {}
    for kind, D in PLACEBO:
        SP = pe.bracket_streams(pe.placebo_shift(R, D if kind == "back" else -D))
        f = SP.inconsistent.to_numpy() if len(SP) else np.array([], dtype=bool)
        out[f"{kind}_{D // 1000}s"] = {"streams": int(len(SP)), "flagged": int(f.sum()),
                                       "wilson_per_stream": wil(int(f.sum()), len(SP)),
                                       "rate_by_session": crate(f, SP.session_id.to_numpy() if len(SP) else [])}
    SR = pe.bracket_streams(pe.roll_ids(R))
    f = SR.inconsistent.to_numpy() if len(SR) else np.array([], dtype=bool)
    out["roll_ids_reference"] = {"streams": int(len(SR)), "flagged": int(f.sum()),
                                 "rate_by_session": crate(f, SR.session_id.to_numpy() if len(SR) else [])}
    return out


def categories_block(unit, split, v, R, S, copied):
    inc = S[S.inconsistent] if len(S) else S
    out = {"inconsistent_streams": int(len(inc))}
    if not len(inc):
        out["note"] = "no inconsistent stream: categories, controls and corrections not applicable"
        return out
    u_by = {s: g for s, g in v.groupby("session_id")}
    cons = S[~S.inconsistent].reset_index(drop=True)
    rng = pe.rng_for("F1ctl", unit, split)
    n_ctl = min(5 * len(inc), len(cons))
    ctl = sorted(rng.choice(len(cons), size=n_ctl, replace=False).tolist()) if n_ctl else []

    def cats(row):
        return set(pe.bracket_benign_categories(u_by[row["session_id"]], R, row, copied))
    inc_c = [cats(r) for r in inc.to_dict("records")]
    ctl_c = [cats(cons.iloc[i].to_dict()) for i in ctl]
    tab = {}
    for c in F1_CATS:
        a = sum(c in x for x in inc_c)
        b = sum(c in x for x in ctl_c)
        sa = a / len(inc_c)
        sb = b / len(ctl_c) if ctl_c else None
        tab[c] = {"inconsistent_with": a, "controls_with": b, "controls_n": len(ctl_c), "share_inconsistent": sa,
                  "share_controls": sb, "enrichment": (sa - sb) if sb is not None else None,
                  "shared_benign_cause": bool(sb is not None and sa >= 0.5 and sa - sb >= 0.3)}
    out["categories"] = tab
    out["category_vectors"] = dict(Counter("+".join(sorted(x)) if x else "(none)" for x in inc_c))
    out["streams"] = [{"session_id": r["session_id"], "stream": r["stream"], "n": int(r["n"]), "gap_ms": float(r["gap"]),
                       "categories": sorted(c)} for r, c in zip(inc.to_dict("records"), inc_c)]
    return out


def _ev_stream(s, sid, st):
    R2 = pe.bracket_responses(s)
    R2 = R2[R2.stream == st]
    if len(R2) < 2:
        return "abstain"
    S2 = pe.bracket_streams(R2)
    return "flag" if bool(S2.inconsistent.iloc[0]) else "ok"


def r1_eval_session(s):
    """(n streams decided, set of inconsistent streams) for one session frame."""
    if not s.request_id.notna().any():
        return 0, set()
    R2 = pe.bracket_responses(s)
    if not len(R2):
        return 0, set()
    S2 = pe.bracket_streams(R2)
    if not len(S2):
        return 0, set()
    return int(len(S2)), set(S2.stream[S2.inconsistent.to_numpy()].astype(str))


def r1_donors(v):
    """Main-thread pairs (delta > 0, call gap >= 0) for insert_pair; call gap = call ts - previous event ts."""
    w = v.sort_values(["session_id", "seq"]).copy()
    w["_ms"] = pe._ms(w.ts)
    w["_prev"] = w.groupby("session_id")._ms.shift(1)
    main = ~w.is_subagent.astype("boolean").fillna(False).to_numpy()
    c = w[(w.kind == "call").to_numpy() & main & w.call_id.notna().to_numpy()].drop_duplicates(["session_id", "call_id"])
    r = w[(w.kind == "result").to_numpy() & main & w.call_id.notna().to_numpy()].drop_duplicates(["session_id",
                                                                                                    "call_id"])
    m = c.reset_index().merge(r.reset_index()[["index", "session_id", "call_id", "_ms", "seq"]],
                              on=["session_id", "call_id"], suffixes=("", "_r"))
    m["lat"] = (m["_ms_r"] - m["_ms"]) / 1000.0
    m["gap"] = (m["_ms"] - m["_prev"]) / 1000.0
    nested = set(v.parent_call_id.dropna().astype(str))
    m = m[np.isfinite(m.lat) & np.isfinite(m.gap) & (m.lat > 0) & (m.gap >= 0) & (m.seq_r > m.seq)
          & ~m.call_id.isin(nested)]
    return m[["index", "index_r", "session_id", "lat", "gap"]].reset_index(drop=True)


def _true(x):
    return x is not None and x is not pd.NA and not (isinstance(x, float) and math.isnan(x)) and bool(x)


def r1_targets(v, Q):
    """Per session: target index lists for the R1-applicable attacks (phase_e_n7_timing.py TARGET_RULES)."""
    T = {}
    res = v[(v.kind == "result").to_numpy() & v.call_id.notna().to_numpy()].sort_values("seq").drop_duplicates(
        ["session_id", "call_id"])
    ridx = {(s, c): i for s, c, i in zip(res.session_id, res.call_id, res.index)}
    cl = v[(v.kind == "call").to_numpy() & v.call_id.notna().to_numpy()].sort_values("seq").drop_duplicates(
        ["session_id", "call_id"])
    cidx = {(s, c): i for s, c, i in zip(cl.session_id, cl.call_id, cl.index)}
    q = Q[Q.session_id.isin(set(v.session_id))]
    nested = set(v.parent_call_id.dropna().astype(str))
    for sid, g in v.groupby("session_id", sort=True):
        qs = q[q.session_id == sid]
        pairs = [(c, ridx.get((sid, c)), cidx.get((sid, c))) for c in qs.call_id]
        fin = np.isfinite(qs.delta_s.to_numpy(dtype=float))
        t = {"time_result_early": [r for (c, r, _), ok in zip(pairs, qs.qualified.to_numpy()) if ok and r is not None],
             "time_result_late": [r for (c, r, _), ok in zip(pairs, fin) if ok and r is not None]}
        t["time_tail_late"] = t["time_tail_early"] = t["time_result_late"]
        rq = g[g.request_id.notna()].sort_values("seq").drop_duplicates("request_id")
        t["time_response_early"] = t["time_response_late"] = t["delete_response"] = list(rq.index)
        dec = rq[[pe.decode_req_ms(x) is not None for x in rq.request_id]]
        t["id_splice_foreign"] = list(dec.index)
        sw = []
        for _, gg in dec.groupby("_st", sort=True):
            ix = list(gg.sort_values("seq").index)
            sw += [(ix[i], ix[i + 1]) for i in range(len(ix) - 1)]
        t["id_swap_adjacent"] = sw
        t["delete_pair"] = [ci for (c, r, ci) in pairs if ci is not None and r is not None]
        gs = g.sort_values("seq")
        ms = pe._ms(gs.ts)
        nxt_gap = {}
        idxs = list(gs.index)
        for j, ix in enumerate(idxs[:-1]):
            a, b = ms[j], ms[j + 1]
            nxt_gap[ix] = (b - a) / 1000.0 if (np.isfinite(a) and np.isfinite(b)) else np.nan
        main_res = [r for (c, r, _), ok in zip(pairs, fin) if ok and r is not None and not _true(v.at[r, "is_subagent"])
                    and c not in nested and isinstance(v.at[r, "ts"], str)]
        t["insert_pair_consistent"] = main_res
        t["insert_pair_squeezed"] = [r for r in main_res if np.isfinite(nxt_gap.get(r, np.nan))
                                     and nxt_gap.get(r) >= 0.002]
        T[sid] = t
    return T


def r1_inject(attack, param, sid, s, target, drng, ctx):
    if attack.startswith("time_"):
        s2, info = pe.atk_time(s, target, float(param), attack[len("time_"):])
        return s2, {"clamped": bool(info.get("clamped"))}
    if attack == "id_swap_adjacent":
        return pe.atk_id_swap(s, target[0], target[1]), {}
    if attack == "id_splice_foreign":
        rp = ctx["resp_pool"]
        own = set(s.request_id.dropna().astype(str))
        cand = rp[(rp.session_id != sid).to_numpy() & ~rp.request_id.isin(list(own)).to_numpy()]
        if not len(cand):
            return None, "no_donor_id"
        if param == "random":
            j = int(drng.integers(0, len(cand)))
            ex = {}
        else:
            te = pe.decode_req_ms(s.at[target, "request_id"])
            diff = np.abs(cand.emb.to_numpy() - te)
            best = np.flatnonzero(diff == diff.min())
            j = int(best[int(drng.integers(0, len(best)))])
            ex = {"nearest_abs_ms": float(diff.min())}
        return pe.atk_id_splice(s, target, cand.request_id.iloc[j]), ex
    if attack == "delete_response":
        return pe.atk_delete_response(s, target), {}
    if attack == "delete_pair":
        return pe.atk_delete_pair(s, target), {}
    if attack.startswith("insert_pair"):
        don = ctx["donors"]
        d = don[don.session_id != sid]
        if not len(d):
            return None, "no_donor_pair"
        j = int(drng.integers(0, len(d)))
        row = d.iloc[j]
        dc, dr = ctx["v"].loc[int(row["index"])].copy(), ctx["v"].loc[int(row["index_r"])].copy()
        for x in (dc, dr):
            x["is_subagent"] = False
            x["agent_id"] = None
            x["_st"] = "main"
        mode = "consistent" if attack.endswith("consistent") else "squeezed"
        s2 = pe.atk_insert_pair(s, target, dc, dr, mode=mode, donor_gap_s=float(row["gap"]),
                                donor_lat_s=float(row["lat"]))
        if s2 is None:
            return None, "gap_below_2ms_or_unparseable"
        return s2, {"inserted": True}
    return None, "not_run"


def r1_n7_cells(v, Q, split):
    """Session-level N7 cells for R1_BRACKET (one tamper per session)."""
    T = r1_targets(v, Q)
    by = {s: g for s, g in v.groupby("session_id", sort=True)}
    Rall = pe.bracket_responses(v)
    rp = Rall[["session_id", "request_id", "emb"]].copy()
    ctx = {"resp_pool": rp, "donors": r1_donors(v), "v": v}
    honest = {s: r1_eval_session(by[s]) for s in by}
    order = list(by)
    perm = pe.rng_for("N7", "tbench2/" + R1_STRATUM["tbench2"], split).permutation(len(order))
    order = [order[i] for i in perm]
    cells = {}
    for attack, param in R1_ATTACKS:
        elig = [s for s in order if T[s].get(attack)]
        sel = elig[:pe.N7_CAP_SESSIONS]
        per, fails = [], Counter()
        for sid in sel:
            tg = T[sid][attack]
            rng = pe.rng_for(attack, param, sid)
            target = tg[int(rng.integers(0, len(tg)))]
            drng = pe.rng_for("donor", attack, param, sid)
            try:
                s2, ex = r1_inject(attack, param, sid, by[sid], target, drng, ctx)
            except Exception as e:  # counted, never hidden
                fails[f"exception:{type(e).__name__}"] += 1
                continue
            if s2 is None:
                fails[ex] += 1
                continue
            n_t, f_t = r1_eval_session(s2)
            n_h, f_h = honest[sid]
            if attack in ("delete_pair", "delete_response"):
                ts_ = None
            elif attack.startswith("insert"):
                ts_ = {"main"}
            else:
                idxs = target if isinstance(target, tuple) else (target,)
                ts_ = {by[sid].at[i, "_st"] for i in idxs}
            per.append({"t": (n_t, f_t), "h": (n_h, f_h), "ts": ts_, "clamped": ex.get("clamped", False)
                        if isinstance(ex, dict) else False})
        n = len(per)
        kt = sum(1 for x in per if x["t"][1])
        kh = sum(1 for x in per if x["h"][1])
        lab, ci = pe.n7_cell_label(n, kt, n, kh)
        row = {"attack": attack, "param": str(param), "label": lab, "n_eligible_sessions": len(elig),
               "n_tampered": n, "injection_failures": dict(fails), "recall": wil(kt, n), "fpr": wil(kh, n),
               "single_call_type": attack in SINGLE_CALL, "back_dating_type": attack in BACKDATE_TYPES}
        if n:
            ind = [int(bool(x["t"][1]) and not bool(x["h"][1])) for x in per]
            row["adr"] = pe.boot_stat(ind, lambda g: float(np.mean(g)) if len(g) else None)
            hr = stats.cluster_rate([len(x["h"][1]) for x in per], [x["h"][0] for x in per])
            tr = stats.cluster_rate([len(x["t"][1]) for x in per], [x["t"][0] for x in per])
            if hr.get("num") == 0 and hr.get("den", 0) > 0:
                hr["wilson_hi_per_event"] = stats.wilson(0, int(hr["den"]))[2]
            row["stream_level"] = {"honest_streams": hr, "tampered_streams": tr}
            kf = [x for x in per if x["t"][1]]
            loc = [bool(x["t"][1] & x["ts"]) for x in kf if x["ts"] is not None]
            row["localization"] = {"k_flagged": len(kf), "k_defined": len(loc), "k_localized": int(sum(loc))}
            if attack == "time_result_early":
                row["clamped_draws"] = int(sum(1 for x in per if x["clamped"]))
        cells[f"{attack}|{param}"] = row
    return cells


def tamper_stream(sid, st, s, splice, pre):
    """Stream-level tampers (kill-rule cells): every R1 attack once on the frame of one stream."""
    out = []
    R0 = pe.bracket_responses(s)
    R0 = R0[R0.stream == st].sort_values("seq")
    if len(R0) < 2:
        return [(a, p, "ineligible", None) for a, p in R1_ATTACKS], None
    honest = bool(pe.bracket_streams(R0).inconsistent.iloc[0])
    seq2idx = dict(zip(s.seq.to_numpy(), s.index.to_numpy()))
    first_idx = [seq2idx[q] for q in R0.seq.to_numpy()]
    embs = R0.emb.to_numpy(dtype=float)
    results = list(s.index[(s.kind == "result").to_numpy() & s.ts.notna().to_numpy()])
    res_cids = set(s.loc[s.kind == "result", "call_id"].dropna())
    calls = list(s.index[(s.kind == "call").to_numpy() & s.call_id.isin(res_cids).to_numpy()])
    sp_sess, sp_ids, sp_emb = splice
    other = sp_sess != sid
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
                is_sub = st != "main"
                for x in (c, r):
                    x["is_subagent"] = is_sub
                    x["agent_id"] = st if is_sub and st != "?" else None
                mode = "consistent" if attack.endswith("consistent") else "squeezed"
                s2 = pe.atk_insert_pair(s, results[i], c, r, mode=mode, donor_gap_s=float(dgap),
                                        donor_lat_s=float(dlat))
                if s2 is None:
                    out.append((attack, param, "skipped", None))
                    continue
            else:
                raise ValueError(attack)
            out.append((attack, param, _ev_stream(s2, sid, st), extra))
        except Exception as e:  # recorded, never silently dropped
            out.append((attack, param, "error", {"error": repr(e)[:200]}))
    return out, honest


def r1_stream_tamper(v, R, S):
    splice_df = R[["session_id", "request_id", "emb"]].sort_values("emb")
    splice = (splice_df.session_id.to_numpy(dtype=object), splice_df.request_id.to_numpy(dtype=object),
              splice_df.emb.to_numpy(dtype=float))
    don = r1_donors(v)
    by = {k: g.drop(columns="_st") for k, g in v.groupby(["session_id", "_st"], sort=False)}
    res = []
    for s, st in zip(S.session_id, S.stream):
        pre = {}
        rr = pe.rng_for("donor", "id_splice_foreign", "random", s, st)
        cand = np.flatnonzero(splice[0] != s)
        pre[("splice", "random")] = int(cand[int(rr.integers(0, len(cand)))]) if len(cand) else None
        for att in ("insert_pair_consistent", "insert_pair_squeezed"):
            d = don[don.session_id != s]
            if len(d):
                j = int(pe.rng_for("donor", att, "-", s, st).integers(0, len(d)))
                row = d.iloc[j]
                pre[("insert", att)] = (v.loc[int(row["index"])].drop(labels="_st"),
                                        v.loc[int(row["index_r"])].drop(labels="_st"), float(row["gap"]),
                                        float(row["lat"]))
            else:
                pre[("insert", att)] = None
        rows, h = tamper_stream(s, st, by[(s, st)], splice, pre)
        res.append((s, st, h, rows))
    return res


def tamper_cells(res, honest_by_key, bar):
    rows = defaultdict(list)
    agree = Counter()
    for sid, st, h, rr in res:
        if h is not None:
            agree["match" if h == honest_by_key.get((sid, st)) else "mismatch"] += 1
        for a, p, status, extra in rr:
            rows[(a, p)].append((sid, st, status, extra))
    cells = {}
    for (a, p), lst in rows.items():
        st_ = np.array([x[2] for x in lst])
        elig = np.isin(st_, ["flag", "ok", "abstain"])
        sids = np.array([x[0] for x in lst], dtype=object)[elig]
        flags = (st_ == "flag")[elig]
        r = crate(flags, sids)
        cells[f"{a}|{p}"] = {"attack": a, "param": str(p), "eligible_streams": int(elig.sum()),
                             "flagged": int(flags.sum()), "abstained": int((st_ == "abstain").sum()),
                             "ineligible": int((st_ == "ineligible").sum()), "skipped": int((st_ == "skipped").sum()),
                             "errors": int((st_ == "error").sum()), "rate_by_session": r,
                             "honest_bar_hi": bar,
                             "clears_honest_bar": bool(r.get("lo") is not None and bar is not None and r["lo"] > bar),
                             "back_dating_type": a in BACKDATE_TYPES, "single_call_type": a in SINGLE_CALL}
    return cells, dict(agree)


def honest_leg(r):
    if r is None or r.get("rate") is None:
        return None
    if r.get("den", 0) < R1_RATE_MIN[0] or r.get("n_sessions", 0) < R1_RATE_MIN[1]:
        return "INSUFFICIENT_N"
    h = hi_used(r)
    if r["rate"] <= 0.05 and h is not None and h <= 0.10:
        return "ALIVE"
    if r["rate"] <= 0.20:
        return "WEAK"
    return "DEAD"


def r1_verdict(honest_r, back30, back5, other_cells, n7_cells, has_e=True):
    reasons = []
    hl = honest_leg(honest_r)
    if hl in (None, "INSUFFICIENT_N"):
        return {"label": "INSUFFICIENT_N", "rule": f"honest stream rate needs >= {R1_RATE_MIN[0]} streams from >= "
                                                   f"{R1_RATE_MIN[1]} sessions",
                "deciding_number": {"streams": honest_r.get("den"), "sessions": honest_r.get("n_sessions")}}
    bar = hi_used(honest_r)
    c30 = bool(back30["rate_by_session"].get("lo") is not None and back30["rate_by_session"]["lo"] > bar)
    c5 = bool(back5["rate_by_session"].get("lo") is not None and back5["rate_by_session"]["lo"] > bar)
    others = sorted(k for k, c in other_cells.items() if not c["back_dating_type"] and c["clears_honest_bar"]
                    and c["single_call_type"])
    n7_det = sorted(k for k, c in n7_cells.items() if c["single_call_type"] and c["label"] == "DETECTS")
    n7_par = sorted(k for k, c in n7_cells.items() if c["single_call_type"] and c["label"] in ("DETECTS", "PARTIAL"))
    if not c30:
        label = "DEAD"
        reasons.append("30 s back-dating does not clear the honest bar (Phase D kill rule)")
    elif hl == "DEAD":
        label = "DEAD"
        reasons.append("honest stream flag rate > 0.20")
    else:
        if n7_det and hl == "ALIVE":
            label = "ALIVE"
        elif n7_par:
            label = "WEAK"
        else:
            label = "DEAD"
            reasons.append("no single-call / single-response N7 type DETECTS or PARTIAL")
        if label == "ALIVE" and not others:
            label = "WEAK"
            reasons.append("back-dating only: no other single-call / single-response type clears the honest bar")
    return {"label": label, "honest_leg": hl, "honest_rate": honest_r.get("rate"), "honest_bar_hi": bar,
            "back_30s_rate_lo": back30["rate_by_session"].get("lo"), "back_30s_clears": c30,
            "back_5s_clears": c5, "other_single_types_clearing_bar": others, "n7_single_types_DETECTS": n7_det,
            "n7_single_types_DETECTS_or_PARTIAL": n7_par, "reasons": reasons,
            "rule": "prereg_e.json a1.proposal_rules (ALIVE / WEAK / DEAD) + R1_specific (Phase D kill rule)"}


def r1_split(corpus, split, u, Q, copied_req):
    stratum = R1_STRATUM[corpus]
    rid_by = u[u.request_id.notna()].groupby(u.stratum.astype(str)).session_id.nunique()
    v = r1_frames(u, stratum)
    R = pe.bracket_responses(v)
    S = pe.bracket_streams(R)
    out = {"population": f"sessions of stratum {stratum}", "sessions": int(v.session_id.nunique()),
           "request_id_sessions_by_stratum": {str(k): int(x) for k, x in rid_by.items()},
           "decodable_ids_distinct": int(sum(1 for x in v.request_id.dropna().unique() if pe.decode_req_ms(x) is not None)),
           "request_ids_distinct": int(v.request_id.dropna().nunique())}
    out["honest"] = honest_block(R, S)
    out["placebo"] = placebo_block(R)
    out["categories"] = categories_block(corpus, split, v, R, S, copied_req)
    log(f"  R1 {split}: {len(S)} streams, {int(S.inconsistent.sum()) if len(S) else 0} inconsistent; tampering")
    hb = {(s, st): bool(x) for s, st, x in zip(S.session_id, S.stream, S.inconsistent)} if len(S) else {}
    bar = hi_used(out["honest"]["rate_by_session"])
    res = r1_stream_tamper(v, R, S) if len(S) else []
    out["stream_tamper"], out["stream_tamper_frame_agreement"] = tamper_cells(res, hb, bar)
    out["n7_session_cells"] = r1_n7_cells(v, Q, split)
    tables = {"v": v, "R": R, "S": S}
    return out, tables


# ===================================================================================================== artifact checks
def leave_outs(T, smeta, measure, base, key="stratum", unit_col="session_id", min_check=None):
    """AC4 with cluster = stratum (D2): dominance over the decision units; leave-outs of the dominant cluster and of the
    5 largest clusters one at a time; recompute the verdict with `measure`."""
    w = T.groupby(unit_col).size().to_dict()
    cmap = {s: smeta.get(s, {}).get(key, "unknown") for s in w}
    d = pe.dominance(w, cmap)
    rec = {"dominated": d.get("dominated"), "top_cluster": d.get("top_cluster"),
           "top_share_events": d.get("top_share_events"), "top_share_sessions": d.get("top_share_sessions"),
           "top_session_share_events": d.get("top_session_share_events"), "n_clusters": d.get("n_clusters")}
    effect = "pass"
    if d.get("dominated"):
        lv = []
        if d.get("n_clusters", 0) <= 1:
            rec["note"] = "single-cluster population: dominated by construction, labelled only (as aiv_cc)"
            # single-session leg still tested
            if d.get("top_session_share_events", 0) > pe.DOM_SESSION:
                top = max(w.items(), key=lambda kv: kv[1])[0]
                lab = measure(T[T[unit_col] != top])["verdict"]["label"]
                lv.append({"left_out": "top session", "label": lab})
                if lab in LVL and LVL[lab] < LVL.get(base, 0):
                    effect = "downgrade"
                elif lab == "INSUFFICIENT_N":
                    effect = "cap_weak"
        else:
            for c, _, _ in d["top_clusters"]:
                sub = T[[cmap.get(s) != c for s in T[unit_col]]]
                lab = measure(sub)["verdict"]["label"]
                lv.append({"left_out_cluster": c, "label": lab, "units": int(len(sub))})
                if lab in LVL and LVL[lab] < LVL.get(base, 0):
                    effect = "downgrade"
                elif lab not in LVL and effect == "pass":
                    effect = "cap_weak"
        rec["leave_outs"] = lv
    rec["effect"] = effect
    return rec


def strata_check(T, smeta, measure, axes=("key", "model", "stratum", "length_tercile")):
    out = {}
    for ax in axes:
        if ax == "key":
            if "key" not in T.columns:
                out[ax] = {"confinement": "UNTESTABLE", "reason": "no tool key on the decision unit"}
                continue
            labs_src = T.key.astype(str)
        else:
            labs_src = T.session_id.map(lambda s: smeta.get(s, {}).get(ax, "unknown"))
        labels, rec = {}, {}
        for val in sorted(set(labs_src)):
            sub = T[(labs_src == val).to_numpy()]
            lab = measure(sub)["verdict"]["label"]
            labels[val] = lab if lab in LVL else None
            rec[val] = {"units": int(len(sub)), "sessions": int(sub.session_id.nunique()), "label": lab}
        out[ax] = {"strata": rec, "confinement": pe.confinement(labels)}
    return out


def checks_for(name, T, smeta, measure, base, ac2=None, ac3=None, ac1=None):
    """AC2 / AC3 / AC4 / AC5 / strata for one N cell at WEAK or better (population B u E)."""
    out = {"base_label": base}

    def res(lab, n_units):
        if lab == base:
            r = "PASS"
        elif lab in LVL and base in LVL:
            r = "FAIL" if LVL[lab] < LVL[base] else "PASS (label higher; no rescue, no effect)"
        else:
            r = f"NO_EFFECT (recompute label {lab} is not a level)"
        return {"label": lab, "units": int(n_units), "result": r}
    if ac2 is not None:
        out["AC2_truncation"] = res(measure(ac2)["verdict"]["label"], len(ac2))
    elif "trunc" in T.columns:
        t2 = T[~T.trunc.astype(bool)]
        out["AC2_truncation"] = res(measure(t2)["verdict"]["label"], len(t2))
    if ac3 is not None:
        out["AC3_join"] = res(measure(ac3)["verdict"]["label"], len(ac3))
    elif "join_clean" in T.columns:
        t3 = T[T.join_clean.astype(bool)]
        out["AC3_join"] = res(measure(t3)["verdict"]["label"], len(t3))
    out["units_total"] = int(len(T))
    out["AC4_dominance"] = leave_outs(T, smeta, measure, base)
    out["AC5_post_strat"] = {"result": "NOT_RUN", "reason": "population_cells() has no new-corpus branch (frozen)"}
    if ac1 is not None:
        try:
            out["AC1_parser"] = ac1()
        except Exception as e:  # an audit crash is recorded, never hidden
            out["AC1_parser"] = {"result": "NOT_RUN", "reason": f"audit error {type(e).__name__}: {str(e)[:200]}"}
    else:
        out["AC1_parser"] = {"result": "NOT_RUN", "reason": "no raw audit for this item (no raw reader written for it)"}
    out["strata"] = strata_check(T, smeta, measure)
    eff = []
    for k in ("AC2_truncation", "AC3_join"):
        if out.get(k, {}).get("result") == "FAIL":
            eff.append((k, "lower", out[k]["label"]))
    if out["AC4_dominance"]["effect"] in ("downgrade", "cap_weak"):
        eff.append(("AC4_dominance", out["AC4_dominance"]["effect"], None))
    if out["AC1_parser"].get("result") == "FAIL":
        eff.append(("AC1_parser", "downgrade", None))
    conf = [ax for ax, x in out["strata"].items() if x.get("confinement") == "CONFINED"]
    lab = base
    for k, e, l2 in eff:
        if e == "lower":
            lab = lower(lab, l2) if l2 in LVL else lab
        elif e == "downgrade":
            lab = pe.downgrade(lab)
        elif e == "cap_weak" and lab == "ALIVE":
            lab = "WEAK"
    if conf:
        lab = pe.downgrade(lab)
    out["effects"] = [list(x) for x in eff] + ([["CONFINED", ",".join(conf)]] if conf else [])
    out["label_after_checks"] = lab
    return out


# ===================================================================================================== R1 raw audit (AC1)
def ac1_r1(corpus, split_rows, sample_rows):
    """Look up sampled decoded responses (and every inconsistent stream's binding events) in the raw WozCode JSONL:
    the entry with the IR uuid must exist, carry the same requestId and the same timestamp (ms)."""
    idx = pd.read_parquet(pe.CACHE / f"{corpus}_split_index.parquet")
    OPENED.append(f"analysis/cache/{corpus}_split_index.parquet")
    from analysis.loaders import load_tbench2 as LT
    files = {r.session_id: (r.submission, r.job, r.trial, json.loads(r.files)) for r in idx.itertuples()}
    by_s = defaultdict(list)
    for r in sample_rows:
        by_s[r["session_id"]].append(r)
    res = Counter()
    diffs = []
    for sid, rows in by_s.items():
        sub, job, trial, fl = files[sid]
        tdir = os.path.join(LT.DATA_ROOT, sub, job, trial)
        want = {r["uuid"]: r for r in rows if isinstance(r.get("uuid"), str)}
        found = {}
        for rel in fl:
            p = os.path.join(tdir, rel)
            with open(p, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if not want or not any(w in line for w in want if w not in found):
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(e, dict) and e.get("uuid") in want:
                        found[e["uuid"]] = e
        for uid, r in want.items():
            e = found.get(uid)
            if e is None:
                res["not_found"] += 1
                diffs.append("not_found")
                continue
            ok_id = e.get("requestId") == r["request_id"]
            t_raw, t_ir = parse_ts(e.get("timestamp")), parse_ts(r["ts"])
            ok_ts = (t_raw is not None and t_ir is not None and abs((t_raw - t_ir).total_seconds()) <= 0.001)
            res["match" if (ok_id and ok_ts) else "differ"] += 1
            if not (ok_id and ok_ts):
                diffs.append(("request_id" if not ok_id else "") + ("ts" if not ok_ts else ""))
    n = sum(res.values())
    nd = res["differ"] + res["not_found"]
    return {"audited": n, "match": res["match"], "differ": res["differ"], "not_found": res["not_found"],
            "diff_kinds": dict(Counter(diffs)), "result": ("FAIL" if nd >= pe.AUDIT_FAIL else "PARSER_NOTE" if nd == 1
                                                         else "PASS"),
            "fields": "uuid lookup in the raw Claude Code JSONL; requestId equal; timestamp within 1 ms"}


# ===================================================================================================== AC1 raw readers
def _raw_ms(x):
    if not isinstance(x, str) or not x:
        return None
    try:
        t = pd.Timestamp(x)
    except (ValueError, TypeError):
        return None
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")  # naive stamps read as UTC (loader rule)
    return t.value / 1e6


def _join_text(content):
    if content is None:
        return None
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


def _jl_obj(a):
    if isinstance(a, str):
        try:
            return json.loads(a)
        except ValueError:
            return a
    return a


def _cj(o):
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))


class RawSession:
    """Independent read of one session's raw log (read-only) for the AC1 parser audit. Keeps per call / result /
    response / record the fields the audited statistics use; no value leaves this object except as a comparison."""

    def __init__(self, corpus, row):
        self.fmt = row["format"]
        files = json.loads(row["files"])
        if corpus == "tbench2":
            from analysis.loaders import load_tbench2 as L
            tdir = os.path.join(L.DATA_ROOT, row["submission"], row["job"], row["trial"])
        else:
            from analysis.loaders import load_glm_tb21 as L
            tdir = os.path.join(L.DATA_ROOT, row["trial"])
        self.sid = row["session_id"]
        self.calls, self.results, self.resp, self.step_ts, self.uuid_ts, self.iter_ts = {}, {}, {}, {}, {}, {}
        getattr(self, "_" + self.fmt)(tdir, files)

    @staticmethod
    def _read(path):
        with open(path, "rb") as fh:
            return fh.read().decode("utf-8", errors="replace")

    def _atif(self, tdir, files):
        d = json.loads(self._read(os.path.join(tdir, files[0])))
        steps = [x for x in (d.get("steps") or []) if isinstance(x, dict)]
        st_ms = [_raw_ms(x.get("timestamp")) for x in steps if x.get("timestamp")]
        st_ms = [x for x in st_ms if x is not None]
        collapsed = len(st_ms) >= 3 and (max(st_ms) - min(st_ms)) < 1000.0
        for st in steps:
            k = st.get("step_id")
            ts = None if collapsed else _raw_ms(st.get("timestamp"))
            self.step_ts[k] = ts
            calls = [c for c in (st.get("tool_calls") or []) if isinstance(c, dict)]
            obs = st.get("observation") if isinstance(st.get("observation"), dict) else {}
            res = [r for r in (obs.get("results") or []) if isinstance(r, dict)]
            for c in calls:
                self.calls[c.get("tool_call_id")] = {"ts": ts, "args": _jl_obj(c.get("arguments"))}
            for r in res:
                cid = r.get("source_call_id") or (calls[0].get("tool_call_id") if len(calls) == 1 and len(res) == 1
                                                  else None)
                if cid:
                    self.results[cid] = {"ts": ts, "text": _join_text(r.get("content"))}
            m = st.get("metrics") if isinstance(st.get("metrics"), dict) else {}
            sx = st.get("extra") if isinstance(st.get("extra"), dict) else {}
            api = sx.get("response_id") if isinstance(sx.get("response_id"), str) and sx.get("response_id") else \
                f"synthetic:atif:{self.sid}:s{k}"
            msg = st.get("message")
            msg = _join_text(msg) if isinstance(msg, list) else msg
            tl = len(msg) if (st.get("source") == "agent" and isinstance(msg, str) and msg.strip()) else 0
            th = st.get("reasoning_content")
            self.resp[api] = {"usage_out": m.get("completion_tokens"), "text_len": tl,
                              "args_len": sum(len(_cj(_jl_obj(c.get("arguments")))) for c in calls
                                              if c.get("arguments") is not None),
                              "think": len(th) if isinstance(th, str) else 0,
                              "last_call": calls[-1].get("tool_call_id") if calls else None}

    def _cc_jsonl(self, tdir, files):
        for rel in files:
            for line in self._read(os.path.join(tdir, rel)).split("\n"):
                if not line.strip():
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(e, dict):
                    continue
                ts = _raw_ms(e.get("timestamp"))
                if e.get("uuid"):
                    self.uuid_ts.setdefault(e["uuid"], ts)
                msg = e.get("message") if isinstance(e.get("message"), dict) else {}
                cont = msg.get("content") if isinstance(msg.get("content"), list) else []
                mid = msg.get("id") if e.get("type") == "assistant" else None
                if mid:
                    r = self.resp.setdefault(mid, {"usage_out": None, "text_len": 0, "args_len": 0, "think": 0,
                                                   "last_call": None})
                    us = msg.get("usage") if isinstance(msg.get("usage"), dict) else {}
                    uo = us.get("output_tokens")
                    if isinstance(uo, (int, float)):
                        r["usage_out"] = max(uo, r["usage_out"] or 0)
                for b in cont:
                    if not isinstance(b, dict):
                        continue
                    bt = b.get("type")
                    if bt in ("tool_use", "server_tool_use") and b.get("id"):
                        self.calls.setdefault(b["id"], {"ts": ts, "args": b.get("input")})
                        if mid:
                            self.resp[mid]["args_len"] += len(_cj(b.get("input")))
                            self.resp[mid]["last_call"] = b["id"]
                    elif bt == "tool_result" and b.get("tool_use_id"):
                        self.results.setdefault(b["tool_use_id"], {"ts": ts, "text": _join_text(b.get("content"))})
                    elif bt == "text" and mid:
                        self.resp[mid]["text_len"] += len(b.get("text") or "")
                    elif bt in ("thinking", "redacted_thinking") and mid:
                        self.resp[mid]["think"] += len(b.get("thinking") or "")

    def _gemini_cli(self, tdir, files):
        d = json.loads(self._read(os.path.join(tdir, files[0])))
        for m in ((d.get("messages") or []) if isinstance(d, dict) else []):
            if not isinstance(m, dict):
                continue
            ts = _raw_ms(m.get("timestamp"))
            if m.get("id"):
                self.uuid_ts.setdefault(m["id"], ts)
            if m.get("type") != "gemini":
                continue
            c = m.get("content")
            if isinstance(c, list):
                c = "\n".join((x.get("text") or "") if isinstance(x, dict) else str(x) for x in c)
            tk = m.get("tokens") if isinstance(m.get("tokens"), dict) else {}
            th = sum(len(x.get("description") or "") + len(x.get("subject") or "") for x in (m.get("thoughts") or [])
                     if isinstance(x, dict))
            tcs = [x for x in (m.get("toolCalls") or []) if isinstance(x, dict)]
            if m.get("id"):
                self.resp[m["id"]] = {"usage_out": tk.get("output"), "text_len": len(c) if isinstance(c, str) else 0,
                                      "args_len": sum(len(_cj(x.get("args"))) for x in tcs), "think": th,
                                      "last_call": tcs[-1].get("id") if tcs else None}
            for tc in tcs:
                self.calls[tc.get("id")] = {"ts": ts, "args": tc.get("args")}
                if "result" in tc:
                    parts = []
                    for r in tc.get("result") or []:
                        fr = r.get("functionResponse") if isinstance(r, dict) else None
                        resp = (fr or {}).get("response")
                        if isinstance(resp, dict) and ("output" in resp or "error" in resp):
                            v = resp.get("output", resp.get("error"))
                            parts.append(v if isinstance(v, str) else _cj(v))
                        elif resp is not None:
                            parts.append(_cj(resp))
                    self.results[tc.get("id")] = {"ts": _raw_ms(tc.get("timestamp")), "text": "\n".join(parts)}

    def _hookele(self, tdir, files):
        rid = {}
        for line in self._read(os.path.join(tdir, files[0])).split("\n"):
            if not line.strip():
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if not isinstance(o, dict):
                continue
            t, ts, it = o.get("type"), _raw_ms(o.get("ts")), o.get("iteration")
            if t == "stream_summary" and isinstance(o.get("response_id"), str):
                rid[it] = o["response_id"]
            elif t == "raw_response":
                self.iter_ts[it] = ts
                us = o.get("usage") if isinstance(o.get("usage"), dict) else {}
                api = rid.get(it) or f"synthetic:hookele:{self.sid}:i{it}"
                tcs = [x for x in (o.get("tool_calls") or []) if isinstance(x, dict)]
                c = o.get("content")
                self.resp[api] = {"usage_out": us.get("output_tokens"),
                                  "text_len": len(c) if isinstance(c, str) and c.strip() else 0,
                                  "args_len": sum(len(_cj(_jl_obj(x.get("arguments")))) for x in tcs
                                                  if x.get("arguments") is not None),
                                  "think": 0, "last_call": tcs[-1].get("call_id") if tcs else None}
                for x in tcs:
                    self.calls[x.get("call_id")] = {"ts": ts, "args": _jl_obj(x.get("arguments"))}
            elif t == "tool_execution":
                out = o.get("output")
                self.results[o.get("call_id")] = {"ts": ts, "text": out if isinstance(out, str) else (
                    _cj(out) if out is not None else None)}

    def event_ms(self, kind, call_id, uuid, extra):
        """Raw stamp (ms) of one IR event, located by the identifiers the IR carries for its format."""
        x = pc.jl(extra) if isinstance(extra, str) else {}
        if self.fmt == "atif":
            return self.step_ts.get(x.get("atif_step_id")), "atif_step_id"
        if self.fmt == "cc_jsonl":
            return self.uuid_ts.get(uuid), "uuid"
        if kind == "result":
            return (self.results.get(call_id) or {}).get("ts"), "result call_id"
        if kind == "call":
            return (self.calls.get(call_id) or {}).get("ts"), "call call_id"
        if self.fmt == "gemini_cli":
            return self.uuid_ts.get(uuid), "message id"
        return self.iter_ts.get(x.get("iteration")), "hookele iteration"


_IDX = {}


def split_index(corpus):
    if corpus not in _IDX:
        idx = pd.read_parquet(pe.CACHE / f"{corpus}_split_index.parquet")
        OPENED.append(f"analysis/cache/{corpus}_split_index.parquet")
        _IDX[corpus] = {r["session_id"]: r for r in idx.to_dict("records")}
    return _IDX[corpus]


def ac1_result(n_diff, n):
    return "FAIL" if n_diff >= pe.AUDIT_FAIL else ("PARSER_NOTE" if n_diff == 1 else "PASS")


def ac1_n1(corpus, unit, q, flagged_keys):
    keys = sorted(flagged_keys)
    samp = pe.audit_sample(keys, seed_parts=("N1", "AC1", "flagged", unit))
    qi = q.drop_duplicates(["session_id", "call_id"]).set_index(["session_id", "call_id"])
    cnt, kinds, fmts = Counter(), Counter(), Counter()
    raws = {}
    for sid, cid in samp:
        row = split_index(corpus)[sid]
        fmts[row["format"]] += 1
        if sid not in raws:
            raws[sid] = RawSession(corpus, row)
        raw = raws[sid]
        ir_ = qi.loc[(sid, cid)]
        c, r = raw.calls.get(cid), raw.results.get(cid)
        if c is None or r is None or c.get("ts") is None or r.get("ts") is None:
            cnt["differ"] += 1
            kinds["not_found_or_unstamped"] += 1
            continue
        d_raw = (r["ts"] - c["ts"]) / 1000.0
        bad = abs(d_raw - float(ir_["delta_s"])) > 0.001
        if bad:
            kinds["delta"] += 1
        a = c.get("args") if isinstance(c.get("args"), dict) else {}
        n1_raw = pe.n1_key(unit, ir_["key"], _cj(a), None)
        if "[REDACTED" in str(ir_["n1"]):
            kinds["n1_key_redacted_not_compared"] += 1
        elif n1_raw != ir_["n1"]:
            bad = True
            kinds["n1_key"] += 1
        tl = len(r["text"]) if isinstance(r.get("text"), str) else None
        kinds["result_chars_equal" if tl == int(ir_["result_chars"]) else "result_chars_differ_no_flag_effect"] += 1
        cnt["differ" if bad else "match"] += 1
    n = sum(cnt.values())
    return {"audited": n, "match": cnt["match"], "differ": cnt["differ"], "detail": dict(kinds),
            "formats": dict(fmts), "result": ac1_result(cnt["differ"], n),
            "fields": "call and result stamps (delta within 1 ms) and the n1 command key (group membership) decide "
                      "the flag; result chars are compared and reported (they enter rho, not the flag)",
            "sample": "audit_sample of detector-flagged shell calls, B u E, seed ('N1','AC1','flagged',unit)"}


def ac1_n2(corpus, unit, E_, tau):
    fl = E_[E_.flag.astype(bool)]
    keys = sorted(zip(fl.session_id, fl.resp))
    samp = pe.audit_sample(keys, seed_parts=("N2", "AC1", "flagged", unit))
    ei = E_.drop_duplicates(["session_id", "resp"]).set_index(["session_id", "resp"])
    cnt, kinds, fmts = Counter(), Counter(), Counter()
    raws = {}
    for sid, rid in samp:
        row = split_index(corpus)[sid]
        fmts[row["format"]] += 1
        if sid not in raws:
            raws[sid] = RawSession(corpus, row)
        raw = raws[sid]
        ir_ = ei.loc[(sid, rid)]
        rr = raw.resp.get(rid)
        if rr is None or rr.get("usage_out") is None:
            cnt["differ"] += 1
            kinds["response_not_found"] += 1
            continue
        res = raw.results.get(rr.get("last_call")) or {}
        rc_raw = len(res["text"]) if isinstance(res.get("text"), str) else None
        ch_raw = rr["text_len"] + rr["args_len"] + rr["think"]
        uo_raw = float(rr["usage_out"])
        kinds["usage_out_equal" if uo_raw == float(ir_["usage_out"]) else "usage_out_differ"] += 1
        kinds["rc_equal" if rc_raw == int(ir_["rc"]) else "rc_differ"] += 1
        chi = float(ir_["chars_out"])
        kinds["chars_out_within_1pct" if abs(ch_raw - chi) <= 0.01 * max(1.0, chi) else "chars_out_differ"] += 1
        flag_raw = bool(rc_raw is not None and rc_raw >= 800 and uo_raw - tau * ch_raw >= 0.5 * tau * rc_raw)
        cnt["match" if flag_raw else "differ"] += 1
        if not flag_raw:
            kinds["flag_not_set_on_raw_values"] += 1
    n = sum(cnt.values())
    return {"audited": n, "match": cnt["match"], "differ": cnt["differ"], "detail": dict(kinds),
            "formats": dict(fmts), "result": ac1_result(cnt["differ"], n),
            "fields": "usage_out, chars of assistant text + call args (compact JSON) + thinking, and the last call's "
                      "result chars, read from the raw log; an event differs if the flag recomputed from the raw "
                      "values is not set",
            "sample": "audit_sample of flagged responses, B u E, seed ('N2','AC1','flagged',unit)"}


def n3_gap_rows(u):
    """pe.n3_gaps() with the row labels of the batch's last stamped result and of the model event (same loop)."""
    out = []
    u = u.sort_values(["session_id", "seq"])
    thr = list(zip(u.session_id, u.is_subagent.astype("boolean").fillna(False), u.agent_id.astype(object).fillna("")))
    u = u.assign(_thr=thr)
    for _, g in u.groupby("_thr", sort=False):
        last_t, last_i, nbytes, blocked = None, None, 0, False
        for i, kind, ts, txt in zip(g.index, g.kind, g.ts.astype(object), g.text.astype(object)):
            if kind == "result":
                t = parse_ts(ts) if isinstance(ts, str) else None
                if t is not None:
                    last_t, last_i = t, i
                nbytes += len(txt.encode("utf-8")) if isinstance(txt, str) else 0
            elif kind in ("user", "system"):
                blocked = True
            elif kind in ("assistant", "call"):
                if last_t is not None and not blocked and isinstance(ts, str):
                    t = parse_ts(ts)
                    if t is not None:
                        gap = (t - last_t).total_seconds()
                        if 0 < gap <= 600:
                            out.append((g.session_id.iloc[0], gap, nbytes, last_i, i))
                last_t, last_i, nbytes, blocked = None, None, 0, False
    return out


def ac1_n3(corpus, unit, G):
    n_by = G.groupby("session_id").size()
    elig = set(n_by[n_by >= N3_MIN_GAPS].index)
    rs = per_session_rho(G[G.session_id.isin(elig)])
    flagged = sorted(s for s, r in rs.items() if r is not None and r <= 0)
    rows = []
    for sp in SPLITS:
        spl = set(pe.split_ids(corpus, sp))
        ids = [s for s in flagged if s in spl]
        if not ids:
            continue
        u = pe.read_cache(corpus, sp, ["session_id", "seq", "kind", "ts", "text", "is_subagent", "agent_id", "call_id",
                                       "uuid", "extra"], filters=[("session_id", "in", ids)])
        gr = n3_gap_rows(u)
        ref = pe.n3_gaps(u)
        assert [(a, b, c) for a, b, c, _, _ in gr] == list(ref), "row-level gap walk differs from n3_gaps"
        for sid, gap, b, ri, mi in gr:
            rows.append({"session_id": sid, "gap": gap, "r": u.loc[ri], "m": u.loc[mi]})
    keys = sorted((r["session_id"], int(r["r"]["seq"]), int(r["m"]["seq"])) for r in rows)
    samp = set(pe.audit_sample(keys, seed_parts=("N3", "AC1", "flagged", unit)))
    cnt, kinds, fmts = Counter(), Counter(), Counter()
    raws = {}
    for r in rows:
        k = (r["session_id"], int(r["r"]["seq"]), int(r["m"]["seq"]))
        if k not in samp:
            continue
        row = split_index(corpus)[r["session_id"]]
        fmts[row["format"]] += 1
        if r["session_id"] not in raws:
            raws[r["session_id"]] = RawSession(corpus, row)
        raw = raws[r["session_id"]]
        a, how_a = raw.event_ms("result", _s(r["r"]["call_id"]), _s(r["r"]["uuid"]), r["r"]["extra"])
        b, how_b = raw.event_ms(r["m"]["kind"], _s(r["m"]["call_id"]), _s(r["m"]["uuid"]), r["m"]["extra"])
        kinds[f"lookup:{how_a}|{how_b}"] += 1
        if a is None or b is None:
            cnt["differ"] += 1
            kinds["not_found"] += 1
            continue
        same = abs((b - a) / 1000.0 - r["gap"]) <= 0.001
        cnt["match" if same else "differ"] += 1
        if not same:
            kinds["gap_differs"] += 1
    n = sum(cnt.values())
    return {"flagged_sessions": len(flagged), "audited": n, "match": cnt["match"], "differ": cnt["differ"],
            "detail": dict(kinds), "formats": dict(fmts), "result": ac1_result(cnt["differ"], n),
            "fields": "raw stamps of the batch's last result and of the next model event (gap within 1 ms)",
            "sample": "audit_sample of the gaps of flagged sessions (rho_s <= 0), B u E, seed ('N3','AC1','flagged',"
                      "unit)"}


# ===================================================================================================== R4 dual-rendering recount
R4_LINE = re.compile("^\\s*\\d+(→|\\t)")  # the A6-O1 recount rule used by analysis/probes/phase_e_r4_r5.py
R4_ATTACKS = [("sub_single_flip_error", "-"), ("sub_single_digit", "-"), ("sub_matched_bytes", "base"),
              ("sub_matched_bytes", "samecmd"), ("reorder_adjacent_pairs", "-"), ("reorder_lines", "-"),
              ("delete_pair", "-"), ("delete_response", "-"), ("insert_pair_consistent", "-"),
              ("insert_pair_squeezed", "-")]
for _a, _p in R4_ATTACKS:
    assert pe.applicable(_a, "R4_DUAL"), _a


def _r4_text_lines(content):
    if isinstance(content, str):
        return content.split("\n")
    out = []
    for b in content if isinstance(content, list) else []:
        if isinstance(b, dict) and b.get("type") == "text":
            out += (b.get("text") or "").split("\n")
    return out


def r4_raw_numlines(corpus, sids):
    """{session: {tool_use_id: (numLines, raw visible count, raw whitelist class)}} from top-level entries carrying
    toolUseResult.file.numLines (int) and a tool_result block (first occurrence), Claude Code JSONL sessions only."""
    out, cnt = {}, Counter()
    idx = split_index(corpus)
    for sid in sids:
        row = idx[sid]
        if row["format"] != "cc_jsonl":
            continue
        from analysis.loaders import load_tbench2 as L
        tdir = os.path.join(L.DATA_ROOT, row["submission"], row["job"], row["trial"])
        nl = {}
        for rel in json.loads(row["files"]):
            with open(os.path.join(tdir, rel), encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"numLines"' not in line:
                        continue
                    cnt["lines_with_numLines_token"] += 1
                    try:
                        d = json.loads(line)
                    except ValueError:
                        cnt["bad_json"] += 1
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
                            cnt["duplicate_tool_use_ids"] += 1
                            continue
                        lines = _r4_text_lines(tr.get("content"))
                        txt = "\n".join(lines)
                        nl[cid] = (int(f["numLines"]), sum(1 for ln in lines if R4_LINE.match(ln)),
                                   pe.dual_whitelisted(txt))
        if nl:
            out[sid] = nl
    return out, dict(cnt)


def r4_eval_session(s, nl_s):
    """(units decided, flagged call ids) of one session frame: first result per call_id carrying a raw numLines."""
    if not nl_s:
        return 0, set()
    r = s[(s.kind == "result").to_numpy() & s.call_id.notna().to_numpy()]
    r = r.sort_values("seq").drop_duplicates("call_id")
    n, fl = 0, set()
    for c, t in zip(r.call_id.astype(str), r.text.astype(object)):
        if c not in nl_s:
            continue
        n += 1
        t = t if isinstance(t, str) else ""
        L_ir = sum(1 for ln in t.split("\n") if R4_LINE.match(ln))
        if L_ir != nl_s[c][0] and pe.dual_whitelisted(t) is None:
            fl.add(c)
    return n, fl


def r4_units(v, nl, Q):
    rows = []
    jc = dict(zip(zip(Q.session_id, Q.call_id), Q.join_clean))
    keyof = dict(zip(zip(Q.session_id, Q.call_id), Q.key))
    r = v[(v.kind == "result").to_numpy() & v.call_id.notna().to_numpy()].sort_values(["session_id", "seq"])
    r = r.drop_duplicates(["session_id", "call_id"])
    for s, c, t, ex in zip(r.session_id, r.call_id.astype(str), r.text.astype(object), r.extra.astype(object)):
        if c not in nl.get(s, {}):
            continue
        t = t if isinstance(t, str) else ""
        num, L_raw, wl_raw = nl[s][c]
        L_ir = sum(1 for ln in t.split("\n") if R4_LINE.match(ln))
        wl = pe.dual_whitelisted(t)
        rows.append({"session_id": s, "call_id": c, "numLines": num, "L_ir": L_ir, "wl_ir": wl,
                     "flag": (L_ir != num) and wl is None, "L_raw": L_raw, "wl_raw": wl_raw,
                     "flag_raw": (L_raw != num) and wl_raw is None,
                     "trunc": bool(pe.truncated_result(t, ex if isinstance(ex, str) else None)),
                     "join_clean": bool(jc.get((s, c), False)), "key": keyof.get((s, c))})
    return pd.DataFrame(rows, columns=["session_id", "call_id", "numLines", "L_ir", "wl_ir", "flag", "L_raw", "wl_raw",
                                       "flag_raw", "trunc", "join_clean", "key"])


def r4_targets(v, Q, pool, sid_set):
    """Attack-defined targets (phase_e_n7_timing.py TARGET_RULES) per session of the R4 population."""
    T = {}
    res = v[(v.kind == "result").to_numpy() & v.call_id.notna().to_numpy()].sort_values("seq").drop_duplicates(
        ["session_id", "call_id"])
    ridx = {(s, c): i for s, c, i in zip(res.session_id, res.call_id.astype(str), res.index)}
    cl = v[(v.kind == "call").to_numpy() & v.call_id.notna().to_numpy()].sort_values("seq").drop_duplicates(
        ["session_id", "call_id"])
    cidx = {(s, c): i for s, c, i in zip(cl.session_id, cl.call_id.astype(str), cl.index)}
    q = Q[Q.session_id.isin(sid_set)]
    nested = set(v.parent_call_id.dropna().astype(str))
    pk = {k: g for k, g in pool.groupby("key")}
    for sid, g in v.groupby("session_id", sort=True):
        qs = q[q.session_id == sid].sort_values("seq")
        t = defaultdict(list)
        thr = defaultdict(list)
        for c, k, n1, tx, err, d, seqr in zip(qs.call_id, qs.key, qs.n1, qs.text_r.astype(object), qs.err,
                                              qs.delta_s, qs.seq_r):
            ri, ci = ridx.get((sid, c)), cidx.get((sid, c))
            if ri is None or ci is None:
                continue
            tx = tx if isinstance(tx, str) else ""
            b = len(tx.encode("utf-8"))
            thr[(_true(v.at[ci, "is_subagent"]), _s(v.at[ci, "agent_id"]) or "")].append(ci)
            t["delete_pair"].append(ci)
            if re.search(r"\d", tx):
                t["sub_single_digit"].append(ri)
            ls = tx.split("\n")
            if len(ls) >= 3 and any(ls[i] != ls[i + 1] for i in range(len(ls) - 1)):
                t["reorder_lines"].append(ri)
            if b > 0 and k in pk:
                cand = pk[k]
                cand = cand[cand.session_id != sid]
                if len(cand) and (np.abs(cand.bytes.to_numpy() - b) <= pe.MATCHED_BYTES_TOL * b).any():
                    t["sub_matched_bytes|base"].append(ri)
                    if n1 is not None and ((cand.n1 == n1).to_numpy() &
                                           (np.abs(cand.bytes.to_numpy() - b) <= pe.MATCHED_BYTES_TOL * b)).any():
                        t["sub_matched_bytes|samecmd"].append(ri)
            if bool(err):
                t["sub_single_flip_error"].append(ri)
            if (not _true(v.at[ri, "is_subagent"])) and c not in nested and isinstance(v.at[ri, "ts"], str):
                t["insert_pair_consistent"].append(ri)
        for _, lst in sorted(thr.items()):
            t["reorder_adjacent_pairs"] += [(lst[i], lst[i + 1]) for i in range(len(lst) - 1)]
        rq = g[g.request_id.notna()].sort_values("seq").drop_duplicates("request_id")
        t["delete_response"] = list(rq.index)
        gs = g.sort_values("seq")
        ms = pe._ms(gs.ts)
        nxt = {}
        idxs = list(gs.index)
        for j, ix in enumerate(idxs[:-1]):
            a, b2 = ms[j], ms[j + 1]
            nxt[ix] = (b2 - a) / 1000.0 if (np.isfinite(a) and np.isfinite(b2)) else np.nan
        t["insert_pair_squeezed"] = [r for r in t["insert_pair_consistent"] if np.isfinite(nxt.get(r, np.nan))
                                     and nxt.get(r) >= 0.002]
        T[sid] = t
    return T


def r4_n7_cells(v, Q, pool, nl, split, corpus):
    sids = sorted(v.session_id.unique())
    T = r4_targets(v, Q, pool, set(sids))
    by = {s: g for s, g in v.groupby("session_id", sort=True)}
    honest = {s: r4_eval_session(by[s], nl.get(s, {})) for s in sids}
    perm = pe.rng_for("N7", f"{corpus}/R4", split).permutation(len(sids))
    order = [sids[i] for i in perm]
    don = r1_donors(v)
    ctx = {"donors": don, "v": v}
    pk = {k: g for k, g in pool.groupby("key")}
    cells = {}
    for attack, param in R4_ATTACKS:
        tk = f"{attack}|{param}" if attack == "sub_matched_bytes" else attack
        elig = [s for s in order if T[s].get(tk)]
        sel = elig[:pe.N7_CAP_SESSIONS]
        per, fails, rels = [], Counter(), []
        for sid in sel:
            tg = T[sid][tk]
            rng = pe.rng_for(attack, param, sid)
            target = tg[int(rng.integers(0, len(tg)))]
            drng = pe.rng_for("donor", attack, param, sid)
            s = by[sid]
            try:
                if attack in ("sub_single_flip_error", "sub_matched_bytes"):
                    q1 = Q[(Q.session_id == sid)]
                    cid = str(v.at[target, "call_id"])
                    row = q1[q1.call_id == cid].iloc[0]
                    cand = pk.get(row["key"])
                    if cand is None:
                        fails["no_pool"] += 1
                        continue
                    if param == "samecmd":
                        cand = cand[cand.n1 == row["n1"]]
                    if attack == "sub_single_flip_error":
                        cand = cand[~cand.err.astype(bool)]
                    tb = len((row["text_r"] if isinstance(row["text_r"], str) else "").encode("utf-8"))
                    i, rel = pe.pick_donor(cand, tb, drng, exclude_session=sid)
                    if i is None:
                        fails["donor_out_of_tolerance"] += 1
                        continue
                    rels.append(rel)
                    s2 = pe.atk_substitute(s, target, cand.at[i, "text"],
                                           donor_error=False if attack == "sub_single_flip_error" else None)
                elif attack == "sub_single_digit":
                    s2, ok = pe.atk_digit(s, target)
                    if not ok:
                        fails["no_digit"] += 1
                        continue
                elif attack == "reorder_adjacent_pairs":
                    s2 = pe.atk_reorder_pairs(s, target[0], target[1])
                elif attack == "reorder_lines":
                    s2, ok = pe.atk_reorder_lines(s, target, rng)
                    if not ok:
                        fails["no_line_pair"] += 1
                        continue
                elif attack == "delete_pair":
                    s2 = pe.atk_delete_pair(s, target)
                elif attack == "delete_response":
                    s2 = pe.atk_delete_response(s, target)
                else:
                    s2, ex = r1_inject(attack, param, sid, s, target, drng, ctx)
                    if s2 is None:
                        fails[ex] += 1
                        continue
            except Exception as e:  # counted, never hidden
                fails[f"exception:{type(e).__name__}"] += 1
                continue
            per.append((r4_eval_session(s2, nl.get(sid, {})), honest[sid]))
        n = len(per)
        kt = sum(1 for t_, h_ in per if t_[1])
        kh = sum(1 for t_, h_ in per if h_[1])
        lab, _ = pe.n7_cell_label(n, kt, n, kh)
        row = {"attack": attack, "param": str(param), "label": lab, "n_eligible_sessions": len(elig), "n_tampered": n,
               "injection_failures": dict(fails), "recall": wil(kt, n), "fpr": wil(kh, n),
               "n_decided_tampered": sum(1 for t_, h_ in per if t_[0] > 0),
               "single_call_type": attack in SINGLE_CALL}
        if rels:
            row["donor_rel_byte_diff"] = {"n": len(rels), "p50": float(np.median(rels)), "max": float(np.max(rels))}
        if n:
            ind = [int(bool(t_[1]) and not bool(h_[1])) for t_, h_ in per]
            row["adr"] = pe.boot_stat(ind, lambda gg: float(np.mean(gg)) if len(gg) else None)
        cells[f"{attack}|{param}"] = row
    cells["rewrite_consistent_k|2"] = {"attack": "rewrite_consistent_k", "param": "2", "label": "NOT_RUN",
                                       "reason": "not a single-call type; not an input of the R4 rule"}
    cells["rewrite_consistent_k|5"] = dict(cells["rewrite_consistent_k|2"], param="5")
    return cells


def r4_honest_part(U):
    f = U.groupby("session_id").flag.any() if len(U) else pd.Series(dtype=bool)
    n, k = int(len(f)), int(f.sum())
    w = wil(k, n)
    if n < R1_RATE_MIN[0]:
        hp = "INSUFFICIENT_N"
    elif w["share"] <= 0.05 and w["hi"] <= 0.10:
        hp = "ALIVE"
    elif w["share"] <= 0.20:
        hp = "WEAK"
    else:
        hp = "DEAD"
    out = {"sessions_decided": n, "sessions_flagged": k, "session_rate": w, "honest_part": hp,
           "units_decided": int(len(U)), "units_flagged": int(U.flag.sum()) if len(U) else 0}
    if len(U):
        g = U.groupby("session_id").flag.agg(["sum", "size"])
        out["unit_rate_clustered"] = stats.cluster_rate(g["sum"].to_numpy(), g["size"].to_numpy())
        out["raw_side_flag_units"] = int(U.flag_raw.sum())
        out["whitelist_classes_ir"] = {str(k_): int(v_) for k_, v_ in U.wl_ir.fillna("none").value_counts().items()}
    return out


def r4_n7_part(cells):
    det = sorted(k for k, c in cells.items() if c.get("single_call_type") and c["label"] == "DETECTS")
    dp = sorted(k for k, c in cells.items() if c["label"] in ("DETECTS", "PARTIAL"))
    return ("ALIVE" if det else "WEAK" if dp else "DEAD"), det, dp


def r4_verdict(hon, cells):
    hp = hon["honest_part"]
    n7p, det, dp = r4_n7_part(cells)
    if hp == "INSUFFICIENT_N":
        lab = "INSUFFICIENT_N"
    elif hp == "DEAD":
        lab = "DEAD"
    else:
        lab = lower(hp, n7p)
    return {"label": lab, "honest_part": hp, "n7_part": n7p, "n7_single_DETECTS": det, "n7_DETECTS_or_PARTIAL": dp,
            "rule": "a1.proposal_rules: session-level honest flag rate <= 0.05 (Wilson hi <= 0.10) and >= 1 "
                    "single-call / single-response type DETECTS in N7 -> ALIVE; <= 0.20 and >= 1 DETECTS/PARTIAL -> "
                    "WEAK; else DEAD (N7 leg read from the same split; B u E reads E)"}


def r4_split(corpus, split, u, Q):
    cc = u[u.session_id.isin([s for s, r in split_index(corpus).items() if r["format"] == "cc_jsonl"
                              and r["split"] == split])]
    cc_sids = sorted(cc.session_id.unique())
    nl, cnt = r4_raw_numlines(corpus, cc_sids)
    st_of = cc.groupby("session_id").stratum.first().astype(str)
    strata = sorted({st_of[s] for s in nl})
    pop = u[u.stratum.astype(str).isin(strata)]
    v = r1_frames_any(pop)
    U = r4_units(v, nl, Q)
    keys = set(Q[Q.session_id.isin(set(v.session_id))].key)
    pool = Q[Q.key.isin(keys)][["session_id", "call_id", "key", "n1", "err", "native_error_r", "text_r"]].copy()
    pool = pool.rename(columns={"text_r": "text", "native_error_r": "native_error"})
    pool["bytes"] = [len(t.encode("utf-8")) if isinstance(t, str) else 0 for t in pool.text.astype(object)]
    pool = pool.reset_index(drop=True)
    out = {"population": f"Claude Code JSONL strata whose raw logs carry toolUseResult.file.numLines in this split: "
                         f"{strata}", "raw_counts": cnt,
           "sessions_with_raw_numlines": len(nl), "population_sessions": int(v.session_id.nunique()),
           "units_by_stratum": {str(k): int(x) for k, x in U.session_id.map(st_of).value_counts().items()} if len(U)
           else {}}
    out["honest"] = r4_honest_part(U)
    log(f"  R4 {split}: {len(U)} units in {U.session_id.nunique() if len(U) else 0} sessions; tampering")
    out["n7_session_cells"] = r4_n7_cells(v, Q, pool, nl, split, corpus)
    out["verdict"] = r4_verdict(out["honest"], out["n7_session_cells"])
    return out, {"U": U, "nl": nl, "st_of": st_of.to_dict()}


def r1_frames_any(u):
    v = u[["session_id", "seq", "kind", "ts", "request_id", "is_subagent", "agent_id", "call_id", "parent_call_id",
           "text", "extra", "uuid", "tool", "tool_raw", "args", "command", "api_msg_id", "stratum", "native_error",
           "exit_code", "stderr", "model"]].copy()
    for c in ("ts", "request_id", "call_id"):
        v[c] = pd.Series([t if isinstance(t, str) else None for t in v[c].astype(object)], index=v.index, dtype=object)
    v["_st"] = pe._stream(v.is_subagent, v.agent_id)
    return v


def r4_checks(corpus, tabs, base, smeta):
    U = pd.concat([tabs["B"]["U"], tabs["E"]["U"]], ignore_index=True)
    n7p = {"B": None, "E": None}

    def lab_of(Ux):
        h = r4_honest_part(Ux)
        return h["honest_part"]
    base_h = lab_of(U)
    out = {"population": "B u E R4 units", "base_honest_part": base_h}
    out["AC2_truncation"] = {"label": lab_of(U[~U.trunc]), "units": int((~U.trunc).sum())}
    out["AC2_truncation"]["result"] = _ac_res(out["AC2_truncation"]["label"], base_h)
    out["AC3_join"] = {"label": lab_of(U[U.join_clean]), "units": int(U.join_clean.sum())}
    out["AC3_join"]["result"] = _ac_res(out["AC3_join"]["label"], base_h)
    T = U.assign(_one=1)
    out["AC4_dominance"] = leave_outs(T, smeta, lambda t: {"verdict": {"label": lab_of(t)}}, base_h)
    out["AC5_post_strat"] = {"result": "NOT_RUN", "reason": "population_cells() has no new-corpus branch (frozen)"}
    fl = U[U.flag]
    keys = sorted(zip(fl.session_id, fl.call_id))
    samp = set(pe.audit_sample(keys, seed_parts=("R4", "AC1", "flagged", corpus)))
    au = U[[(s, c) in samp for s, c in zip(U.session_id, U.call_id)]]
    nd = int((au.flag_raw != au.flag).sum())
    out["AC1_parser"] = {"audited": int(len(au)), "differ": nd, "result": ac1_result(nd, len(au)),
                         "fields": "numbered-line count and whitelist class of the raw tool_result content vs the IR "
                                   "text (flag recomputed on the raw side)"}
    out["strata"] = strata_check(T, smeta, lambda t: {"verdict": {"label": lab_of(t)}})
    eff = []
    lab = base
    for k in ("AC2_truncation", "AC3_join"):
        if out[k]["result"] == "FAIL":
            eff.append(k)
            lab = lower(lab, out[k]["label"])
    if out["AC4_dominance"]["effect"] == "downgrade":
        eff.append("AC4_dominance")
        lab = pe.downgrade(lab)
    elif out["AC4_dominance"]["effect"] == "cap_weak" and lab == "ALIVE":
        eff.append("AC4_dominance cap")
        lab = "WEAK"
    if out["AC1_parser"]["result"] == "FAIL":
        eff.append("AC1_parser")
        lab = pe.downgrade(lab)
    conf = [ax for ax, x in out["strata"].items() if x.get("confinement") == "CONFINED"]
    if conf:
        eff.append("CONFINED " + ",".join(conf))
        lab = pe.downgrade(lab)
    out["effects"] = eff
    out["label_after_checks"] = lab
    return out


# ===================================================================================================== main per corpus
TAU = {}


def measure_corpus(corpus):
    unit = corpus
    log(f"=== {corpus} (unit argument '{unit}', D1)")
    cal_p = pe.OUT_E / f"prereg_e_calibration_{corpus}.json"
    cal_sha = sha_file(cal_p)
    entry = [c for c in PJ["change_log"] if c.get("corpus") == corpus]
    assert entry and entry[0]["calibration_sha256"] == cal_sha, "calibration file differs from its change_log entry"
    cal = json.loads(cal_p.read_text(encoding="utf-8"))
    cu = cal["units"][corpus]
    cuts = cu["length_terciles"]["cuts"]
    TAU[unit] = cu["n2"]["tau"]
    fgA = cu["n6_field_gate"]
    copied = copied_call_ids(corpus)
    copied_req, keep_req = (copied_request_ids(corpus) if corpus in R1_STRATUM else (set(), {}))
    X = {sp: {} for sp in SPLITS}
    smeta = {}
    load_info, fg, red = {}, {}, {}
    r1, r4 = {}, {}
    r1_tabs, r4_tabs = {}, {}
    for sp in SPLITS:
        u, info = load_split(corpus, sp)
        load_info[sp] = info
        log(f"{corpus} {sp}: {info}")
        red[sp] = redaction_counts(u)
        P, Q = unit_pairs(unit, u, copied)
        fg[sp] = field_gate(unit, u, P)
        smeta.update(session_meta(u, Q, cuts, sp))
        X[sp]["q"] = n1_extract(Q)
        X[sp]["n2"] = n2_extract(unit, u, Q)
        X[sp]["n3"] = n3_extract(u, Q)
        log(f"  N1/N2/N3 extracted")
        X[sp]["n5"] = n5_extract(unit, u, Q)
        log(f"  N5 extracted")
        X[sp]["p2"] = p2_extract(unit, u)
        log(f"  P2 extracted")
        X[sp]["p4"] = p4_extract(unit, u)
        log(f"  P4 extracted")
        X[sp]["native_error"] = {"results": int((u.kind == "result").sum()),
                                 "native_error_nonnull": int(u[u.kind == "result"].native_error.notna().sum()),
                                 "native_error_true": int((u[u.kind == "result"].native_error == True).sum()),  # noqa
                                 "exit_code_nonnull": int(u[u.kind == "result"].exit_code.notna().sum())}
        if corpus in R1_STRATUM:
            r1[sp], r1_tabs[sp] = r1_split(corpus, sp, u, Q, copied_req)
            r4[sp], r4_tabs[sp] = r4_split(corpus, sp, u, Q)
        del u, P, Q
        gc.collect()
    doc = {"corpus": corpus, "group": GROUP, "script": SCRIPT, "notes": NOTES,
           "unit_argument": unit, "decisions_applied": ["D1", "D2", "D5", "D6"],
           "prereg_e_json_sha256": sha_file(pe.PREREG_E_JSON),
           "spec_module_sha256_lf": pe.sha256_lf(Path(pe.__file__)),
           "spec_module_matches_prereg": pe.sha256_lf(Path(pe.__file__)) == PJ["provenance"]["spec_module_sha256_lf"],
           "calibration": {"path": str(cal_p.relative_to(pe.ROOT).as_posix()), "sha256": cal_sha,
                           "matches_change_log": True, "change_log_entry": entry[0]},
           "phase_b_code": {"probe_2.py": pe.sha256_lf(pe.ROOT / "analysis/probes/probe_2.py"),
                            "probe_4.py": pe.sha256_lf(pe.ROOT / "analysis/probes/probe_4.py"),
                            "probe_4_prereg_provenance": P4_PROV},
           "exclusions_D5": {"file": "analysis/out/phase_e/newcorp_exclusions.json",
                             "listed_for_corpus": {k: len(v) for k, v in EXCL.get(corpus, {}).items()
                                                   if isinstance(v, list)}},
           "caches": {sp: dict(load_info[sp], path=f"analysis/cache/{corpus}_{sp}.parquet",
                               sha256=sha_file(pe.CACHE / f"{corpus}_{sp}.parquet")) for sp in SPLITS},
           "credential_redaction_counts": red,
           "blindness_D6": "NOT_BLIND: R1 bracket / placebo / tamper cells, Probe 1, N1, N3, N4, N5g (Track B computed "
                           "request-id decode deltas and call->result gap quantiles over the full corpus)",
           "field_gate": {"A": fgA, "A_path": f"{cal_p.relative_to(pe.ROOT).as_posix()}#units.{corpus}.n6_field_gate",
                          "B": fg["B"], "E": fg["E"]},
           "error_signal_context": {sp: X[sp]["native_error"] for sp in SPLITS},
           "detail": {}, "cells": {}}
    detail = doc["detail"]
    BE = "BuE"

    def pooled(get):
        return pd.concat([get(X["B"]), get(X["E"])], ignore_index=True)

    pops = {"B": lambda f: f(X["B"]), "E": lambda f: f(X["E"]), BE: lambda f: pooled(f)}
    distinct = sum(fg[sp]["pairs_distinct_stamps"] for sp in SPLITS) + fgA["pairs_distinct_stamps"]
    # ------------------------------------------------------------------ N1
    if distinct == 0:
        detail["N1"] = {"label": "NOT_TESTABLE", "reason": "no call/result pair with distinct stamps (A, B, E)"}
    else:
        detail["N1"] = {}
        for k, get in pops.items():
            q = get(lambda x: x["q"])
            detail["N1"][k] = {"shell": n1_measure(q, unit, f"detail.N1.{k}.shell", "shell"),
                               "auto_read": n1_measure(q, unit, f"detail.N1.{k}.auto_read", "auto_read")}
        log("N1 done")
    # ------------------------------------------------------------------ N2
    detail["N2"] = {}
    for k, sp_list in (("B", ["B"]), ("E", ["E"]), (BE, ["B", "E"])):
        E_ = pd.concat([X[s]["n2"][0] for s in sp_list], ignore_index=True)
        gran = X[sp_list[0]]["n2"][1] if len(sp_list) == 1 else {
            "GRANULAR": all(X[s]["n2"][1].get("GRANULAR") for s in sp_list),
            "per_split": {s: X[s]["n2"][1] for s in sp_list}}
        detail["N2"][k] = n2_measure(E_, unit, gran, f"detail.N2.{k}")
    log("N2 done")
    # ------------------------------------------------------------------ N3
    detail["N3"] = {}
    for k, get in pops.items():
        detail["N3"][k] = n3_measure(get(lambda x: x["n3"]["all"]), f"detail.N3.{k}")
    log("N3 done")
    # ------------------------------------------------------------------ N5
    detail["N5a"], detail["N5b"], detail["N5c"], detail["N5d"], detail["N5e"], detail["N5g"] = {}, {}, {}, {}, {}, {}
    for k, get in pops.items():
        detail["N5a"][k] = n5a_measure(get(lambda x: x["n5"]["a"]), f"detail.N5a.{k}")
        detail["N5b"][k] = n5_checker_measure(get(lambda x: x["n5"]["b"]), "b", f"detail.N5b.{k}")
        detail["N5c"][k] = n5c_measure(get(lambda x: x["n5"]["c"]), f"detail.N5c.{k}")
        detail["N5d"][k] = n5_checker_measure(get(lambda x: x["n5"]["d"]), "d", f"detail.N5d.{k}")
        detail["N5e"][k] = n5e_measure(get(lambda x: x["n5"]["e"]), get(lambda x: x["n5"]["e_comp"]),
                                       f"detail.N5e.{k}")
        if distinct:
            detail["N5g"][k] = n5g_measure(get(lambda x: x["n5"]["g"]), f"detail.N5g.{k}")
    if not distinct:
        detail["N5g"] = {"label": "NOT_TESTABLE", "reason": "no call/result pair with distinct stamps (A, B, E)"}
    log("N5 done")
    # ------------------------------------------------------------------ P2
    detail["P2"] = {}
    for k, sp_list in (("B", ["B"]), ("E", ["E"]), (BE, ["B", "E"])):
        Rr = pd.concat([X[s]["p2"][0] for s in sp_list], ignore_index=True)
        Xx = pd.concat([X[s]["p2"][1] for s in sp_list], ignore_index=True)
        detail["P2"][k] = p2_measure(unit, Rr, Xx, f"detail.P2.{k}")
        detail["P2"][k]["extraction"] = {s: X[s]["p2"][2] for s in sp_list}
    log("P2 done")
    # ------------------------------------------------------------------ P4
    detail["P4"] = {}
    for k in ("B", "E"):
        a = X[k]["p4"]
        detail["P4"][k] = p4_measure(a.hex, a.ints, f"detail.P4.{k}", [])
        detail["P4"][k]["F3_context"] = f3_context(a.ints, a.f3, f"detail.P4.{k}.F3_context")
        detail["P4"][k]["F3_context"]["cal_round_counts_check"] = a.f3["cal_round_counts_check"]
        detail["P4"][k]["F3_context"]["own_loop_counts"] = {"T_orig_distinct_values": len(a.f3["values"]),
                                                            "excluded_strict_any_occurrence": len(a.f3["strict_param"]),
                                                            "excluded_first_occurrence": len(a.f3["first_param"])}
    hexd, intd = p4.pool({"B": X["B"]["p4"], "E": X["E"]["p4"]}, ["B", "E"])
    detail["P4"][BE] = p4_measure(hexd, intd, f"detail.P4.{BE}", ["pooled B u E"])
    f3be = {"strict_param": X["B"]["p4"].f3["strict_param"] | X["E"]["p4"].f3["strict_param"],
            "first_param": X["B"]["p4"].f3["first_param"] | X["E"]["p4"].f3["first_param"]}
    detail["P4"][BE]["F3_context"] = f3_context(intd, f3be, f"detail.P4.{BE}.F3_context")
    log("P4 done")
    # ------------------------------------------------------------------ R1
    if corpus in R1_STRATUM:
        detail["R1"] = {"B": r1["B"], "E": r1["E"]}
        S_be = pd.concat([r1_tabs["B"]["S"], r1_tabs["E"]["S"]], ignore_index=True)
        R_be = pd.concat([r1_tabs["B"]["R"], r1_tabs["E"]["R"]], ignore_index=True)
        detail["R1"][BE] = {"honest": honest_block(R_be, S_be), "placebo": placebo_block(R_be)}
        for k in ("B", "E", BE):
            d = detail["R1"][k]
            if k == BE:
                hon = d["honest"]["rate_by_session"]
                bar = hi_used(hon)
                st_cells = {}
                for key in detail["R1"]["B"]["stream_tamper"]:
                    cb, ce = detail["R1"]["B"]["stream_tamper"][key], detail["R1"]["E"]["stream_tamper"][key]
                    st_cells[key] = {"back_dating_type": cb["back_dating_type"], "single_call_type": cb["single_call_type"],
                                     "clears_honest_bar": None, "note": "pooled stream cells not recomputed; see B, E"}
                n7 = detail["R1"]["E"]["n7_session_cells"]
                v = r1_verdict(hon, d["placebo"]["back_30s"], d["placebo"]["back_5s"],
                               detail["R1"]["E"]["stream_tamper"], n7)
                v["note"] = ("B u E honest rate and placebo pooled; kill-rule 'other types' leg and N7 leg read from E "
                             "(prereg: N7 on E)")
                d["verdict"] = v
            else:
                v = r1_verdict(d["honest"]["rate_by_session"], d["placebo"]["back_30s"], d["placebo"]["back_5s"],
                               d["stream_tamper"], d["n7_session_cells"])
                d["verdict"] = v
        log("R1 done")
        U_be = pd.concat([r4_tabs["B"]["U"], r4_tabs["E"]["U"]], ignore_index=True)
        hon = r4_honest_part(U_be)
        detail["R4"] = {"B": r4["B"], "E": r4["E"],
                        BE: {"honest": hon, "verdict": dict(r4_verdict(hon, r4["E"]["n7_session_cells"]),
                                                            note="B u E honest part; N7 leg read from E")}}
    # ------------------------------------------------------------------ checks for N cells at WEAK or better
    doc["checks"] = run_cell_checks(corpus, unit, X, smeta, detail, distinct, r1_tabs)
    if "R4" in detail and any(detail["R4"][sp]["verdict"]["label"] in ("ALIVE", "WEAK") for sp in SPLITS):
        doc["checks"]["R4"] = r4_checks(corpus, r4_tabs, detail["R4"]["BuE"]["verdict"]["label"], smeta)
    # ------------------------------------------------------------------ cells
    doc["cells"] = build_cells(corpus, detail, fgA, fg, distinct, doc["checks"])
    doc["n_verdict_cells"] = {"cells": len(doc["cells"]),
                              "split_labels_computed": sum(1 for c in doc["cells"].values() for k in
                                                           ("label_B", "label_E", "label_BuE") if c.get(k) in
                                                           ("ALIVE", "WEAK", "DEAD", "INSUFFICIENT_N", "INCONCLUSIVE"))}
    doc["session_meta_summary"] = {"strata": dict(Counter(m["stratum"] for m in smeta.values())),
                                   "models": dict(Counter(m["model"] for m in smeta.values()).most_common(30)),
                                   "length_tercile_cuts_A": cuts}
    return doc


def _ac_res(lab, base):
    if lab == base:
        return "PASS"
    if lab in LVL and base in LVL:
        return "FAIL" if LVL[lab] < LVL[base] else "PASS (label higher; no rescue, no effect)"
    return f"NO_EFFECT (recompute label {lab} is not a level)"


def r1_checks(corpus, r1_tabs, base, smeta):
    """AC2-AC4 + strata + AC1 for R1 on B u E (honest-leg label)."""
    v = pd.concat([r1_tabs["B"]["v"], r1_tabs["E"]["v"]])
    S = pd.concat([r1_tabs["B"]["S"], r1_tabs["E"]["S"]], ignore_index=True)
    R = pd.concat([r1_tabs["B"]["R"], r1_tabs["E"]["R"]], ignore_index=True)
    out = {"population": "B u E, R1 stratum", "base_honest_leg": honest_leg(crate(S.inconsistent, S.session_id))}
    is_res = (v.kind == "result").to_numpy()
    tr = np.array([pe.truncated_result(t, x) if r else False for r, t, x in
                   zip(is_res, v.text.astype(object), v.extra.astype(object))])
    S2 = pe.bracket_streams(pe.bracket_responses(v[~tr]))
    l2 = honest_leg(crate(S2.inconsistent, S2.session_id))
    out["AC2_truncation"] = {"results_removed": int(tr.sum()), "label": l2, "result": _ac_res(l2, out["base_honest_leg"])}
    cr = v[v.kind.isin(["call", "result"])][["session_id", "seq", "kind", "call_id", "ts"]]
    P = pc.make_pairs(cr)
    ok = pe.join_clean_mask(cr, P, copied_call_ids(corpus))
    ck = set(zip(P.session_id[ok], P.call_id[ok].astype(str)))
    keep = np.array([(not r) or ((s, str(c)) in ck) for r, s, c in zip(is_res, v.session_id, v.call_id.astype(object))])
    S3 = pe.bracket_streams(pe.bracket_responses(v[keep]))
    l3 = honest_leg(crate(S3.inconsistent, S3.session_id))
    out["AC3_join"] = {"results_removed": int((is_res & ~keep).sum()), "label": l3,
                       "result": _ac_res(l3, out["base_honest_leg"])}
    w = S.groupby("session_id").size().to_dict()
    d = pe.dominance(w, {s: smeta[s]["stratum"] for s in w})
    top = max(w.items(), key=lambda kv: kv[1])
    ac4 = {"stratum_clusters": d.get("n_clusters"), "note": "one stratum by construction (R1 population): labelled only",
           "top_session_share_streams": top[1] / sum(w.values())}
    eff = "pass"
    if top[1] / sum(w.values()) > pe.DOM_SESSION:
        m = S.session_id != top[0]
        lab = honest_leg(crate(S.inconsistent[m], S.session_id[m]))
        ac4["leave_out_top_session"] = lab
        if lab in LVL and LVL[lab] < LVL.get(out["base_honest_leg"], 0):
            eff = "downgrade"
    ac4["effect"] = eff
    out["AC4_dominance"] = ac4
    out["AC5_post_strat"] = {"result": "NOT_RUN", "reason": "population_cells() has no new-corpus branch (frozen)"}
    # strata: length tercile (model and stratum are single-valued in the R1 population)
    SP30 = pe.bracket_streams(pe.placebo_shift(R, 30000))
    labs, rec = {}, {}
    lt = S.session_id.map(lambda s: smeta[s]["length_tercile"])
    lp = SP30.session_id.map(lambda s: smeta[s]["length_tercile"])
    for val in sorted(set(lt)):
        m, mp = (lt == val).to_numpy(), (lp == val).to_numpy()
        n, ns = int(m.sum()), int(S.session_id[m].nunique())
        if n < 30 or ns < 5:
            labs[val] = None
            rec[val] = {"streams": n, "sessions": ns, "label": None}
            continue
        rh = crate(S.inconsistent.to_numpy()[m], S.session_id.to_numpy()[m])
        rp = crate(SP30.inconsistent.to_numpy()[mp], SP30.session_id.to_numpy()[mp])
        clears = rp.get("lo") is not None and hi_used(rh) is not None and rp["lo"] > hi_used(rh)
        lab = honest_leg(rh) if clears else "DEAD"
        labs[val] = lab if lab in LVL else None
        rec[val] = {"streams": n, "sessions": ns, "honest": rh, "back_30s": rp, "label": lab}
    out["strata"] = {"length_tercile": {"strata": rec, "confinement": pe.confinement(labs)},
                     "model": {"confinement": "UNTESTABLE", "reason": "one model in the R1 population"},
                     "stratum": {"confinement": "UNTESTABLE", "reason": "one stratum (the R1 population)"},
                     "tool_key": {"confinement": "NOT_APPLICABLE", "reason": "a stream mixes tools"}}
    # AC1: every binding event of inconsistent streams + a seeded sample of 30 decoded responses
    inc_rows = []
    for (s, st), g in R.groupby(["session_id", "stream"]):
        row = S[(S.session_id == s) & (S.stream == st)]
        if len(row) and bool(row.inconsistent.iloc[0]):
            for k in ("k_L", "k_U"):
                kk = row[k].iloc[0]
                if kk is not None and np.isfinite(kk) and int(kk) in R.index:
                    inc_rows.append(int(kk))
    keys = list(R.index)
    samp = pe.audit_sample(keys, seed_parts=("R1", "AC1", corpus))
    pick = sorted(set(samp) | set(inc_rows))
    vi = v.set_index(["session_id", "seq"])
    rows = []
    for i in pick:
        r = R.loc[i]
        uu = vi.loc[(r["session_id"], r["seq"])]
        rows.append({"session_id": r["session_id"], "uuid": uu["uuid"] if isinstance(uu["uuid"], str) else None,
                     "request_id": r["request_id"], "ts": r["ts"]})
    out["AC1_parser"] = ac1_r1(corpus, None, rows)
    out["AC1_parser"]["sample"] = f"{len(samp)} seeded decoded responses + {len(inc_rows)} binding events of " \
                                  f"inconsistent streams"
    effs = []
    for k in ("AC2_truncation", "AC3_join"):
        if out[k]["result"] == "FAIL":
            effs.append(k)
    if out["AC1_parser"]["result"] == "FAIL":
        effs.append("AC1_parser")
    if eff == "downgrade":
        effs.append("AC4_dominance")
    lab = base
    for k in effs:
        if k in ("AC2_truncation", "AC3_join"):
            lab = lower(lab, out[k]["label"]) if out[k]["label"] in LVL else lab
        else:
            lab = pe.downgrade(lab)
    if out["strata"]["length_tercile"]["confinement"] == "CONFINED":
        lab = pe.downgrade(lab)
        effs.append("CONFINED length_tercile")
    out["effects"] = effs
    out["label_after_checks"] = lab
    return out


def run_cell_checks(corpus, unit, X, smeta, detail, distinct, r1_tabs):
    out = {}
    BE = "BuE"

    def wants(name, getter):
        labs = [getter(sp) for sp in ("B", "E")]
        return any(lab in ("ALIVE", "WEAK") for lab in labs)

    def pooled(f):
        return pd.concat([f(X["B"]), f(X["E"])], ignore_index=True)
    # N1 (shell)
    if distinct and wants("N1", lambda sp: detail["N1"][sp]["shell"]["verdict"]["label"]):
        q = pooled(lambda x: x["q"])
        base = detail["N1"][BE]["shell"]["verdict"]["label"]
        lo_, hi_ = N1_POOLED["bounds"]
        Rb = pe.n1_residuals(q[q.cls == "shell"], unit)
        fk = set()
        if len(Rb):
            m = q.set_index(["session_id", "seq"])["call_id"]
            fl = Rb[(Rb.residual < lo_) | (Rb.residual > hi_)]
            fk = {(s_, m.loc[(s_, int(x))]) for s_, x in zip(fl.session_id, fl.seq)}
        out["N1"] = checks_for("N1", q, smeta, lambda t: n1_measure(t, unit, "check", "shell", full=False), base,
                               ac1=lambda: ac1_n1(corpus, unit, q, fk))
    if wants("N2", lambda sp: detail["N2"][sp]["verdict"]["label"]):
        E_ = pooled(lambda x: x["n2"][0])
        gran = {"GRANULAR": True}
        base = detail["N2"][BE]["verdict"]["label"]
        out["N2"] = checks_for("N2", E_, smeta, lambda t: n2_measure(t, unit, gran, "check", full=False), base,
                               ac1=lambda: ac1_n2(corpus, unit, E_, TAU[unit]))
    if wants("N3", lambda sp: detail["N3"][sp]["verdict"]["label"]):
        G = pooled(lambda x: x["n3"]["all"])
        base = detail["N3"][BE]["verdict"]["label"]
        out["N3"] = checks_for("N3", G, smeta, lambda t: n3_measure(t, "check", full=False), base,
                               ac2=pooled(lambda x: x["n3"]["AC2"]), ac3=pooled(lambda x: x["n3"]["AC3"]),
                               ac1=lambda: ac1_n3(corpus, unit, G))
    if wants("N5a", lambda sp: detail["N5a"][sp]["verdict"]["label"]):
        T = pooled(lambda x: x["n5"]["a"])
        out["N5a"] = checks_for("N5a", T, smeta, lambda t: n5a_measure(t, "check"), detail["N5a"][BE]["verdict"]["label"])
    for it, fn in (("N5b", lambda t: n5_checker_measure(t, "b", "check")),
                   ("N5d", lambda t: n5_checker_measure(t, "d", "check"))):
        if wants(it, lambda sp: detail[it][sp]["verdict"]["label"]):
            T = pooled(lambda x: x["n5"][it[-1]])
            out[it] = checks_for(it, T, smeta, fn, detail[it][BE]["verdict"]["label"])
    if wants("N5c", lambda sp: detail["N5c"][sp]["verdict"]["label"]):
        T = pooled(lambda x: x["n5"]["c"])
        T = T[~T["item"].astype(str).str.startswith("pc_")]
        out["N5c"] = checks_for("N5c", T.drop(columns=["trunc"]), smeta, lambda t: n5c_measure(t, "check"),
                                detail["N5c"][BE]["verdict"]["label"])
        out["N5c"]["AC2_truncation"] = {"result": "NOT_RUN", "reason": "every marked result is truncated by definition"}
    if wants("N5e", lambda sp: detail["N5e"][sp]["verdict"]["label"]):
        T = pooled(lambda x: x["n5"]["e"])
        C = pooled(lambda x: x["n5"]["e_comp"])
        out["N5e"] = checks_for("N5e", T, smeta, lambda t: n5e_measure(t, C, "check"),
                                detail["N5e"][BE]["verdict"]["label"])
    if distinct and wants("N5g", lambda sp: detail["N5g"][sp]["verdict"]["label"]):
        T = pooled(lambda x: x["n5"]["g"]).rename(columns={"first_trunc": "trunc", "first_join_clean": "join_clean"})
        out["N5g"] = checks_for("N5g", T, smeta, lambda t: n5g_measure(t, "check"), detail["N5g"][BE]["verdict"]["label"])
    if corpus in R1_STRATUM:
        labs = [detail["R1"][sp]["verdict"]["label"] for sp in ("B", "E")]
        if any(lab in ("ALIVE", "WEAK") for lab in labs):
            out["R1"] = r1_checks(corpus, r1_tabs, detail["R1"][BE]["verdict"]["label"], smeta)
    return out


# ===================================================================================================== cells
def cell_from(row, lb, le, lbe, deciding, n, sessions, ci, path, flags=(), checks=None, extra=None):
    has_e = le is not None
    if le in ("ALIVE", "WEAK", "DEAD", "INCONCLUSIVE"):
        lab = le
        src = "E verdict"
    elif lb is not None:
        lab = lb
        src = "B only" + (" (E INSUFFICIENT_N)" if le == "INSUFFICIENT_N" else "")
    else:
        lab, src = "NOT_RUN", "no label"
    if checks and checks.get("label_after_checks") and lab in LVL:
        after = checks["label_after_checks"]
        if after in LVL and LVL[after] < LVL[lab]:
            lab = after
            src += " -> lowered by artifact checks/confinement on B u E"
    c = {"label": lab, "label_source": src, "label_B": lb, "label_E": le, "label_BuE": lbe,
         "deciding_number": deciding, "n": n, "sessions": sessions, "ci": ci, "json_path": path,
         "flags": list(flags)}
    if checks is not None:
        c["artifact_checks_path"] = f"checks.{row}"
        c["label_after_checks_BuE"] = checks.get("label_after_checks")
    if extra:
        c.update(extra)
    return c


def nt(reason, path=None, flags=()):
    return {"label": f"NOT_TESTABLE({reason})", "label_B": None, "label_E": None, "label_BuE": None,
            "deciding_number": None, "n": None, "sessions": None, "ci": None, "json_path": path, "flags": list(flags)}


def build_cells(corpus, d, fgA, fg, distinct, checks):
    C = {}
    BE = "BuE"
    nb = [NOT_BLIND]
    # Probe 1
    C["P1_latency"] = nt("Phase B Probe 1 qualification (allowed classes), floors, G90 and G set exist only for "
                         "registered units; no pooled value (D1)" if distinct else "distinct call/result stamps",
                         flags=nb)
    # Probe 2
    def p2lab(k):
        v = d["P2"][k]["main"]["verdict"]
        return v.get("verdict"), v
    lb, vb = p2lab("B")
    le, ve = p2lab("E")
    lbe, vbe = p2lab(BE)
    p2src = "E" if le not in ("INSUFFICIENT_N", None) else "B"
    ve_ = ve if p2src == "E" else vb
    C["P2_knowledge"] = cell_from("P2", lb, le, lbe,
                                  {"statistic": ve_.get("deciding_statistic"), "value": ve_.get("value"),
                                   "caps": ve_.get("caps_applied"), "S_deep_n": ve_.get("S_deep_n"),
                                   "S_path_any_n": ve_.get("S_path_any_n")},
                                  ve_.get("n") if ve_.get("n") is not None else ve_.get("S_path_any_n"),
                                  ve_.get("n_sessions") if ve_.get("n_sessions") is not None
                                  else ve_.get("S_path_any_sessions"), ve_.get("ci"),
                                  f"detail.P2.{p2src}.main.verdict", extra={"subagent_stratum": {
                                      k: d["P2"][k]["sub"]["verdict"].get("verdict") for k in ("B", "E", BE)}})
    # Probe 3
    C["P3a_zero_error"] = nt("error signal: no error definition for this unit (prereg_common.error_classes, D1)")
    C["P3b_reaction"] = nt("error signal: no error definition for this unit (prereg_common.error_classes, D1)")
    # Probe 4
    for row, key, stat in (("P4a_hex", "hex_primary", "T_orig w_adj vs control hi"),
                           ("P4b_round", "round_numbers_secondary", "T_orig last-0 vs M_all")):
        labs = {k: d["P4"][k]["verdicts"][key]["verdict"] for k in ("B", "E", BE)}
        src_k = "E" if labs["E"] not in ("INSUFFICIENT_N",) else "B"
        dec = d["P4"][src_k]["verdicts"][key]["deciding"]
        if key == "hex_primary":
            n_, s_ = dec.get("T_orig_symbols"), dec.get("T_orig_sessions")
            ci_ = [dec.get("T_orig_w_adj_lo"), dec.get("T_orig_w_adj_hi")]
        else:
            n_, s_ = dec.get("T_orig_distinct"), dec.get("T_orig_sessions")
            ci_ = [dec.get("T_orig_last0_lo"), dec.get("T_orig_last0_hi")]
        extra_ = {"F3_context_label": d["P4"][src_k].get("F3_context", {}).get("F3_rule_label"),
                  "F3_context_path": f"detail.P4.{src_k}.F3_context"} if key == "round_numbers_secondary" else None
        C[row] = cell_from(row, labs["B"], labs["E"], labs[BE], {"statistic": stat, **dec}, n_, s_, ci_,
                           f"detail.P4.{src_k}.verdicts.{key}", extra=extra_)
    # R1
    if "R1" in d:
        vb_, ve_, vbe_ = (d["R1"][k]["verdict"] for k in ("B", "E", BE))
        h = d["R1"]["E"]["honest"]["rate_by_session"]
        C["R1_bracket"] = cell_from("R1", vb_["label"], ve_["label"], vbe_["label"],
                                    {"honest_stream_rate": ve_.get("honest_rate"), "honest_bar_hi": ve_.get(
                                        "honest_bar_hi"), "back_30s_lo": ve_.get("back_30s_rate_lo"),
                                     "n7_single_types_DETECTS": ve_.get("n7_single_types_DETECTS"),
                                     "other_types_clearing": ve_.get("other_single_types_clearing_bar")},
                                    int(h.get("den") or 0), int(h.get("n_sessions") or 0), [h.get("lo"), h.get("hi")],
                                    "detail.R1.E.verdict", flags=nb + [f"population: stratum {R1_STRATUM[corpus]}"],
                                    checks=checks.get("R1"))
    else:
        C["R1_bracket"] = nt("provider request ids decodable to ms: 0 on A, B, E", flags=nb)
    C["R2_image"] = nt("per-response prompt IMAGE token counts (field gate image_usage_rows = 0)")
    C["R3_git"] = nt("external commit table linked by repo (field gate external_commit_table False)")
    if "R4" in d:
        vb4, ve4, vbe4 = (d["R4"][k]["verdict"] for k in ("B", "E", BE))
        h4 = d["R4"]["E"]["honest"]
        C["R4_dual"] = cell_from("R4", vb4["label"], ve4["label"], vbe4["label"],
                                 {"session_flag_share": h4["session_rate"]["share"],
                                  "session_flag_hi": h4["session_rate"]["hi"], "honest_part": ve4["honest_part"],
                                  "n7_part": ve4["n7_part"], "n7_single_DETECTS": ve4["n7_single_DETECTS"]},
                                 h4["units_decided"], h4["sessions_decided"],
                                 [h4["session_rate"]["lo"], h4["session_rate"]["hi"]], "detail.R4.E.verdict",
                                 flags=[f"population: {d['R4']['E']['population']}",
                                        "field gate A said raw_structured_counters False (unit-name rule); the raw "
                                        "field is present in the Claude Code JSONL strata, so R4 was run"],
                                 checks=checks.get("R4"))
    else:
        C["R4_dual"] = nt("harness structured counters (toolUseResult numLines) in the raw source (field gate "
                          "raw_structured_counters False; ATIF has no such field)")
    C["R5_ledger"] = nt("external usage tally (field gate external_usage_tally False)")
    # N1
    if not distinct:
        C["N1"] = nt("distinct call/result stamps (pairs_distinct_stamps 0 on A, B, E)", flags=nb)
    else:
        v = {k: d["N1"][k]["shell"]["verdict"] for k in ("B", "E", BE)}
        src = "E" if v["E"]["label"] in ("ALIVE", "WEAK", "DEAD", "INCONCLUSIVE") else "B"
        b = d["N1"][src]["shell"]
        C["N1"] = cell_from("N1", v["B"]["label"], v["E"]["label"], v[BE]["label"], v[src].get("deciding_number"),
                            b["residuals"]["n"], b["residuals"].get("n_sessions"),
                            {"rho_hon": [b["rho_hon"].get("lo"), b["rho_hon"].get("hi")],
                             "rho_pc": [b["rho_pc"].get("lo"), b["rho_pc"].get("hi")]},
                            f"detail.N1.{src}.shell.verdict", flags=nb + ["pooled bounds (D1)"],
                            checks=checks.get("N1"),
                            extra={"auto_read_secondary": {k: d["N1"][k]["auto_read"]["verdict"]["label"]
                                                           for k in ("B", "E", BE)}})
    # N2
    v = {k: d["N2"][k]["verdict"] for k in ("B", "E", BE)}
    src = "E" if v["E"]["label"] in ("ALIVE", "WEAK", "DEAD", "INCONCLUSIVE") else "B"
    b = d["N2"][src]
    fr = b.get("honest_flag_rate", {})
    C["N2"] = cell_from("N2", v["B"]["label"], v["E"]["label"], v[BE]["label"], v[src].get("deciding_number"),
                        b.get("eligible_responses"), b.get("eligible_sessions"), [fr.get("lo"), fr.get("hi")],
                        f"detail.N2.{src}.verdict", checks=checks.get("N2"))
    # N3
    v = {k: d["N3"][k]["verdict"] for k in ("B", "E", BE)}
    src = "E" if v["E"]["label"] in ("ALIVE", "WEAK", "DEAD", "INCONCLUSIVE") else "B"
    b = d["N3"][src]
    C["N3"] = cell_from("N3", v["B"]["label"], v["E"]["label"], v[BE]["label"], v[src].get("deciding_number"),
                        b.get("eligible_gaps"), b.get("eligible_sessions"),
                        [b["rho_pooled"].get("lo"), b["rho_pooled"].get("hi")], f"detail.N3.{src}.verdict", flags=nb,
                        checks=checks.get("N3"))
    # N4
    C["N4"] = nt("Phase B W / G pair populations (probe1 allowed classes, W_KEYS, G_TOOLS) exist only for registered "
                 "units; no pooled definition (D1)" if distinct else "distinct call/result stamps", flags=nb)
    # N5
    for row, key in (("N5a_determinism", "N5a"), ("N5b_sort", "N5b"), ("N5c_truncation", "N5c"),
                     ("N5d_whitespace", "N5d"), ("N5e_size", "N5e")):
        v = {k: d[key][k]["verdict"] for k in ("B", "E", BE)}
        src = "E" if v["E"]["label"] in ("ALIVE", "WEAK", "DEAD", "INCONCLUSIVE") else "B"
        b = d[key][src]
        n = b.get("pairs") or b.get("qualifying_families")
        ss = b.get("sessions")
        ci_ = None
        if key in ("N5b", "N5d"):
            n = {ch: x.get("outputs") for ch, x in b["per_checker"].items()}
            ss = {ch: x.get("sessions") for ch, x in b["per_checker"].items()}
            ci_ = {ch: [x.get("violation", {}).get("lo"), x.get("violation", {}).get("hi")] for ch, x in
                   b["per_checker"].items() if x.get("violation")}
        if key == "N5c":
            n = {it: x.get("marked") for it, x in b["per_item"].items()}
            ss = {it: x.get("sessions") for it, x in b["per_item"].items()}
        if key == "N5a" and b.get("drift"):
            ci_ = [b["drift"].get("lo"), b["drift"].get("hi")]
        if key == "N5e":
            ss = b.get("comparator", {}).get("sessions")
        C[row] = cell_from(key, v["B"]["label"], v["E"]["label"], v[BE]["label"],
                           v[src].get("deciding_number") or v[src].get("per_checker_labels") or v[src].get(
                               "per_item_labels"), n, ss, ci_, f"detail.{key}.{src}.verdict",
                           flags=(["pooled constants (D1)"] if key == "N5c" else []), checks=checks.get(key))
    C["N5f_error_fidelity"] = nt("error signal: no error definition for this unit (prereg_common.error_classes, D1)")
    if not distinct:
        C["N5g_cold_start"] = nt("distinct call/result stamps (pairs_distinct_stamps 0 on A, B, E)", flags=nb)
    else:
        v = {k: d["N5g"][k]["verdict"] for k in ("B", "E", BE)}
        src = "E" if v["E"]["label"] in ("ALIVE", "WEAK", "DEAD", "INCONCLUSIVE") else "B"
        b = d["N5g"][src]
        mc = b.get("median_c", {})
        C["N5g_cold_start"] = cell_from("N5g", v["B"]["label"], v["E"]["label"], v[BE]["label"],
                                        v[src].get("deciding_number"), b.get("eligible_sessions"),
                                        b.get("eligible_sessions"), [mc.get("lo"), mc.get("hi")],
                                        f"detail.N5g.{src}.verdict", flags=nb, checks=checks.get("N5g"))
    return C


def main():
    pe.OUT_E.mkdir(parents=True, exist_ok=True)
    f1 = pe.OUT_E / "f1_bracket.json"
    step0 = None
    if f1.exists():
        j = json.loads(f1.read_text(encoding="utf-8"))
        step0 = {"result": j.get("step0", {}).get("result"), "path": "analysis/out/phase_e/f1_bracket.json#step0.result",
                 "sha256_read": sha_file(f1), "note": "Track A output (uncommitted when read); context only"}
    for corpus in CORPORA:
        t1 = time.time()
        OPENED.clear()
        doc = measure_corpus(corpus)
        doc["f1_step0_context"] = step0
        doc["deviations"] = DEVIATIONS
        doc["thresholds"] = {"N1_bounds": N1_POOLED, "N5c_constants": N5C, "P2_D": P2_D_POOLED, "N2_tau_A": TAU[corpus],
                             "N1": [N1_RHO_BAND, N1_PC_LO, N1_RR, N1_FLAG_PT, N1_FLAG_HI, N1_MIN],
                             "N2": [N2_FLAG_PT, N2_FLAG_HI, N2_WEAK_FLAG, N2_REC_ALIVE, N2_REC_WEAK, N2_MIN],
                             "N3": [N3_MIN_GAPS, N3_MIN_SESS, N3_ALIVE_LO, N3_SHARE_PT, N3_SHARE_HI],
                             "N5": {"min": N5_MIN, "th": N5_TH, "e": [N5E_FAM_MIN, N5E_COMP_MIN],
                                    "g": [N5G_MIN, N5G_ALIVE_C, N5G_ALIVE_SHARE]},
                             "R1": {"tol_ms": pe.BRACKET_TOL_MS, "rate_min": R1_RATE_MIN}}
        doc["opened_files"] = sorted(set(OPENED))
        doc["runtime_s"] = round(time.time() - t1, 1)
        out = pe.OUT_E / f"newcorp_measure_{corpus}.json"
        out.write_text(json.dumps(clean(doc), indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        log(f"wrote {out.relative_to(pe.ROOT).as_posix()}")
        for k, c in doc["cells"].items():
            print(f"   {k:20s} {c['label']}  (B {c.get('label_B')}, E {c.get('label_E')}, BuE {c.get('label_BuE')})")
        gc.collect()


if __name__ == "__main__":
    main()
