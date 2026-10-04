"""Phase B Probe 1: latency physics (pre-registered in analysis/PREREG.md section 1, analysis/prereg.json `probe1`).

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.probe_1

Question: are honest, work-bound tool latencies separable from generation time, so that a tool result the model
generated itself (bounded below by output generation time) would stand out?

Order of work, per unit (all fixed by the pre-registration, nothing tuned here):
  0. sha256(prereg_common.py) must equal prereg.json provenance.spec_module_sha256, else the script stops. The
     no-human-wait filter and the generation-bound latency rule are imported from prereg_calibration.py, the code that
     produced the A-split floors; its sha256 must equal provenance.calibration_script_sha256 as well.
  1. Re-apply the A1 kill rule (phase_a.json gate_rules.A1_latency_kill_rule) to the unit's B pairs.
  2. Apply the no-human-wait filter; per tool_key and per tool class: min, p1, p5, p10, p25, p50, p75, p95, p99, max
     with session-clustered CIs (subject to global.min_n), log histograms, Spearman(result bytes, latency).
  3. Near-zero-variance (FLAT) test per tool_key; unit killed if every reportable work-bound tool_key is FLAT.
  4. Floor transfer (share of B pairs below the A-split p5) per tool_key with an A p5.
  5. Mid-session floor step change (prereg_common.change_point) per session x tool_key series.
  6. Separability: generation-time model, fp_share, AUC against the generation-bound set G.
  7. Verdict by the pre-registered rule, stored with its deciding numbers.

Reads only analysis/cache/<corpus>_B.parquet (+ swechat_population.parquet for the format; aiv_cc_A.parquet session ids
only, for the pre-registered aiv_cc split-overlap count). Writes RAW NUMBERS ONLY to analysis/out/probe_1.json (and a
byte-identical copy at the prereg output-contract path analysis/out/phase_b/probe_1.json). Interpretation lives in
analysis/notes/probe_1.md.

cc_local is PRIVATE: only aggregates leave this script; tool names go through prereg_common.private_key() and session
ids are replaced by an index. aiv_cc is one agent: every aiv_cc number is a single-agent case study.
"""
import hashlib
import json
import math
import sys
import time
from collections import Counter, defaultdict

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from analysis.lib import stats
from analysis.lib.ir import error_marker
from analysis.probes import prereg_common as pc
from analysis.probes import prereg_calibration as cal  # frozen A-side implementation of the filter (sha-checked)
from analysis.probes.phase_a_a1 import frac_of  # A1 definition of a stamp's fractional part

ROOT = pc.ROOT
PREREG_PATH = ROOT / "analysis" / "prereg.json"
SPEC_PATH = ROOT / "analysis" / "probes" / "prereg_common.py"
CALIB_PATH = ROOT / "analysis" / "probes" / "prereg_calibration.py"
OUT = ROOT / "analysis" / "out" / "probe_1.json"
OUT_CONTRACT = ROOT / "analysis" / "out" / "phase_b" / "probe_1.json"

COLS = ["session_id", "seq", "kind", "ts", "tool", "tool_raw", "call_id", "text", "extra", "api_msg_id",
        "is_subagent", "agent_id", "parent_call_id", "stratum"]
KINDS = ["call", "result", "meta", "system", "user"]  # assistant rows are not used by Probe 1
QS = (0.01, 0.05, 0.10, 0.25, 0.5, 0.75, 0.95, 0.99)
CI_QS = (0.01, 0.05, 0.10, 0.5, 0.95)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ================================================================================================ pre-registration
PR = json.load(open(PREREG_PATH, encoding="utf-8"))
P1 = PR["probe1"]
RES1 = PR["resolved"]["probe1"]
MIN_N = PR["global"]["min_n"]
SEP = P1["separability"]

# Thresholds whose numeric value lives only in a prereg.json text field. Each is asserted against that text at start-up
# so that a value here cannot drift from the pre-registration.
TH = {
    "tokens_per_char": SEP["generation_time_model"]["tokens_per_char"],
    "T_gen_min_s": 1.0,
    "W_min_pairs": 100, "W_min_sessions": 10,
    "G_min_pairs": 30, "G_min_sessions": 5,
    "fp_alive_point": 0.05, "fp_alive_hi": 0.10, "fp_weak_point": 0.20,
    "auc_alive_point": 0.85, "auc_alive_lo": 0.75, "auc_weak_point": 0.70,
    "flat_min_pairs": 30, "flat_min_sessions": 5, "flat_iqr_res_mult": 2, "flat_iqr_log10": 0.05,
    "stamp_resolution_s": {"ms_units": P1["near_zero_variance_kill"]["stamp_resolution_s"]["ms_units"],
                           "aiv_cc": P1["near_zero_variance_kill"]["stamp_resolution_s"]["aiv_cc"]},
    "transfer_nominal": 0.05, "transfer_band": [0.025, 0.10], "transfer_min_B_n": 100,
    "step_m": 20, "step_n_perm": 199, "step_p": 0.01, "step_D": math.log10(2), "step_share_unstable": 0.10,
    "a1_majority": 0.5, "a1_mixed_lo": 0.01,
    "ci_valid_draws_min": 900,
}
TH_SOURCE = {
    "T_gen_min_s": SEP["generation_time_model"]["eligibility"],
    "W/G min n": SEP["min_n"],
    "fp": SEP["labels"]["fp"],
    "auc": SEP["labels"]["auc"],
    "flat": P1["near_zero_variance_kill"]["definition"],
    "transfer": P1["per_tool_statistics"]["floor_transfer"],
    "step": P1["floor_step_change"]["step"] + " | " + P1["floor_step_change"]["label"] + " | "
            + P1["floor_step_change"]["eligible"],
    "a1": None,  # filled from phase_a.json below
    "ci": PR["global"]["ci_methods"]["statistic_ci"],
    "zero_count": PR["global"]["ci_methods"]["zero_count"],
    "verdict": P1["verdict"],
}


def check_thresholds_against_text():
    s = SEP
    assert "T_gen >= 1.0 s" in s["generation_time_model"]["eligibility"]
    assert "eligible W >= 100 pairs from >= 10 sessions" == s["min_n"]["W"]
    assert "eligible G >= 30 pairs from >= 5 sessions" == s["min_n"]["G"]
    assert "fp_share <= 0.05 and its CI hi <= 0.10" in s["labels"]["fp"] and "fp_share <= 0.20" in s["labels"]["fp"]
    assert "AUC >= 0.85 and CI lo >= 0.75" in s["labels"]["auc"] and "AUC >= 0.70" in s["labels"]["auc"]
    d = P1["near_zero_variance_kill"]["definition"]
    assert ">= 30 qualified pairs from >= 5 sessions" in d and "<= 2 x stamp resolution" in d and "< 0.05" in d
    t = P1["per_tool_statistics"]["floor_transfer"]
    assert "[0.025, 0.10]" in t and "B n >= 100" in t and "Nominal 0.05" in t
    st = P1["floor_step_change"]
    assert "p <= 0.01 AND D* >= log10(2)" in st["step"] and "<= 0.10" in st["label"] and "m = 20" in st["eligible"]
    assert "199 shuffles" in st["test"]
    assert "n_boot draws" in PR["global"]["ci_methods"]["statistic_ci"] and ">= 900 of 1000" in PR["global"]["ci_methods"]["statistic_ci"]
    assert PR["global"]["bootstrap"]["seed"] == stats.SEED and PR["global"]["bootstrap"]["n_boot"] == stats.N_BOOT
    assert abs(TH["tokens_per_char"] - 0.25) < 1e-12


# ================================================================================================ small helpers
def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if hasattr(o, "item") and not isinstance(o, (str, bytes)):
        o = o.item()
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    return o


def reportable(n, ns, q):
    key = {"p1": "p1_p99", "p99": "p1_p99", "p5": "p5_p95", "p95": "p5_p95", "p10": "p5_p95",
           "p25": "p50", "p50": "p50", "p75": "p50"}[q]
    need = MIN_N["quantile_reportable"][key]
    return n >= need[0] and ns >= need[1]


def rate_from_mask(mask, sids):
    """cluster_rate with the global min-n and zero-count rules applied."""
    mask = np.asarray(mask, dtype=bool)
    sids = np.asarray(sids, dtype=object).astype(str)
    den, num = Counter(sids.tolist()), Counter(sids[mask].tolist())
    keys = list(den)
    k, n, ns = int(mask.sum()), int(len(mask)), len(keys)
    out = {"num": k, "den": n, "n_sessions": ns}
    rr = MIN_N["rate_reportable"]
    if n < rr["den_min"] or ns < rr["sessions_min"]:
        out["label"] = "INSUFFICIENT_N"
        return out
    r = stats.cluster_rate([num[s] for s in keys], [den[s] for s in keys])
    out.update({"rate": r["rate"], "lo": r["lo"], "hi": r["hi"]})
    if k == 0:
        out["wilson_hi_per_event"] = stats.wilson(0, n)[2]
        out["wilson_hi_per_session"] = stats.wilson(0, ns)[2]
        out["verdict_hi"] = out["wilson_hi_per_event"]
    else:
        out["verdict_hi"] = r["hi"]
    return out


def session_groups(sids):
    s = np.asarray(sids, dtype=object).astype(str)
    uniq, inv = np.unique(s, return_inverse=True)
    order = np.argsort(inv, kind="stable")
    bounds = np.searchsorted(inv[order], np.arange(len(uniq) + 1))
    return uniq, [order[bounds[i]:bounds[i + 1]] for i in range(len(uniq))]


def _spearman(x, y):
    if len(x) < 3 or np.ptp(x) == 0 or np.ptp(y) == 0:
        return None
    rx, ry = rankdata(x), rankdata(y)
    c = np.corrcoef(rx, ry)[0, 1]
    return None if not np.isfinite(c) else float(c)


def spearman_ci(x, y, sids):
    """Spearman rho with the pre-registered statistic_ci (session resampling, n_boot draws, >= 900 valid)."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    uniq, groups = session_groups(sids)
    out = {"n": int(len(x)), "n_sessions": int(len(uniq))}
    if len(x) < 30 or len(uniq) < 5:
        out["label"] = "INSUFFICIENT_N"
        return out
    out["rho"] = _spearman(x, y)
    rng = np.random.default_rng(stats.SEED)
    boots, invalid = [], 0
    for _ in range(stats.N_BOOT):
        pick = rng.integers(0, len(groups), size=len(groups))
        idx = np.concatenate([groups[i] for i in pick])
        v = _spearman(x[idx], y[idx])
        if v is None:
            invalid += 1
        else:
            boots.append(v)
    out["valid_draws"] = len(boots)
    if len(boots) >= TH["ci_valid_draws_min"]:
        out["lo"], out["hi"] = float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975))
    return out


def auc_value(g, w):
    """P(g > w) + 0.5 P(g == w) via Mann-Whitney ranks."""
    if len(g) == 0 or len(w) == 0:
        return None
    r = rankdata(np.concatenate([g, w]))
    U = r[:len(g)].sum() - len(g) * (len(g) + 1) / 2
    return float(U / (len(g) * len(w)))


def auc_ci(g, gs, w, ws):
    """AUC with statistic_ci: sessions resampled once per draw, both groups taken from the same draw."""
    g, w = np.asarray(g, dtype=float), np.asarray(w, dtype=float)
    gs, ws = np.asarray(gs, dtype=object).astype(str), np.asarray(ws, dtype=object).astype(str)
    sess = sorted(set(gs.tolist()) | set(ws.tolist()))
    gi, wi = defaultdict(list), defaultdict(list)
    for i, s in enumerate(gs):
        gi[s].append(i)
    for i, s in enumerate(ws):
        wi[s].append(i)
    gi = [np.array(gi.get(s, []), dtype=int) for s in sess]
    wi = [np.array(wi.get(s, []), dtype=int) for s in sess]
    out = {"auc": auc_value(g, w), "n_G": int(len(g)), "n_W": int(len(w)), "sessions_union": len(sess)}
    rng = np.random.default_rng(stats.SEED)
    boots, invalid = [], 0
    for _ in range(stats.N_BOOT):
        pick = rng.integers(0, len(sess), size=len(sess))
        gg = np.concatenate([gi[i] for i in pick])
        ww = np.concatenate([wi[i] for i in pick])
        if len(gg) == 0 or len(ww) == 0:
            invalid += 1
            continue
        boots.append(auc_value(g[gg], w[ww]))
    out["valid_draws"] = len(boots)
    if len(boots) >= TH["ci_valid_draws_min"]:
        out["lo"], out["hi"] = float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975))
    return out


def dist_block(d, s, full=None, res_s=None):
    """Distribution of positive deltas d (seconds) with session ids s: min/max, quantiles with cluster CIs (subject to
    global.min_n), IQRs, log histogram. `full` = all finite deltas of the group (zero/negative counted apart)."""
    d = np.asarray(d, dtype=float)
    out = {"n": int(len(d)), "n_sessions": int(len(set(np.asarray(s, dtype=object).astype(str).tolist())))}
    if full is not None:
        f = np.asarray(full, dtype=float)
        out["n_zero"] = int((f == 0).sum())
        out["n_negative"] = int((f < 0).sum())
    if len(d) == 0:
        return out
    q = cal.qstats(d, s, qs=QS, ci_qs=CI_QS)
    out["min"], out["max"] = q["min"], q["max"]
    for qq in QS:
        name = f"p{round(qq * 100, 2):g}"
        if reportable(out["n"], out["n_sessions"], name):
            out[name] = q[name]
        else:
            out[name] = {"label": "INSUFFICIENT_N"}
    lg = np.log10(d)
    if reportable(out["n"], out["n_sessions"], "p25"):
        out["iqr_s"] = float(np.quantile(d, 0.75) - np.quantile(d, 0.25))
        out["iqr_log10"] = float(np.quantile(lg, 0.75) - np.quantile(lg, 0.25))
    else:
        out["iqr_s"] = out["iqr_log10"] = None
    out["below_0.1s"] = int((d < 0.1).sum())
    out["below_0.01s"] = int((d < 0.01).sum())
    out["log_histogram_s"] = stats.log_histogram(d if full is None else np.asarray(full, dtype=float))
    return out


# ================================================================================================ A1 recheck
A1_RULE = json.load(open(ROOT / "analysis" / "out" / "phase_a.json", encoding="utf-8"))["gate_rules"]["A1_latency_kill_rule"]
TH_SOURCE["a1"] = A1_RULE["rule"]


def a1_recheck(P):
    """The A1 kill rule, applied to B pairs exactly as worded in gate_rules.A1_latency_kill_rule."""
    ts_c, ts_r = pc.sobj(P.ts) if "ts" in P else [], pc.sobj(P.ts_r) if "ts_r" in P else []
    d = P.delta_s.to_numpy(dtype=float) if "delta_s" in P else np.full(len(P), np.nan)
    both = np.isfinite(d)
    sid = P.session_id.astype(str).to_numpy()
    out = {"n_pairs": int(len(P)), "n_pairs_both_ts": int(both.sum()),
           "n_sessions_both_ts": int(len(set(sid[both].tolist()))),
           "n_pairs_missing_ts": int((~both).sum())}
    has_any_ts = any(bool(x) for x in ts_c) or any(bool(x) for x in ts_r)
    if both.sum() == 0:
        out.update({"verdict": "KILLED", "reason": ["no_timestamps"] if not has_any_ts else
                    ["no_call_result_pairs_with_both_stamps"]})
        return out
    stamps = [a for a, ok in zip(ts_c, both) if ok] + [b for b, ok in zip(ts_r, both) if ok]
    ssid = np.concatenate([sid[both], sid[both]])
    fr = [frac_of(x) for x in stamps]
    ws = np.array([f is not None and (f == "" or set(f) <= {"0"}) for f in fr])
    dd = d[both]
    dus = np.rint(dd * 1e6).astype(np.int64)
    ws_r = rate_from_mask(ws, ssid)
    zs_r = rate_from_mask(dus == 0, sid[both])
    ws_p, zs_p = float(ws.mean()), float((dus == 0).mean())
    reasons = []
    if ws_p > TH["a1_majority"]:
        reasons.append("whole_second_stamps")
    if zs_p > TH["a1_majority"]:
        reasons.append("shared_call_result_stamp")
    mixed = [nm for nm, v in (("whole_second_stamps", ws_p), ("shared_call_result_stamp", zs_p))
             if TH["a1_mixed_lo"] < v <= TH["a1_majority"]]
    nz = np.abs(dus[dus != 0])
    out.update({"verdict": "KILLED" if reasons else "ALIVE", "reason": reasons or None, "mixed_flag": mixed or None,
                "whole_second_stamp_share": ws_r, "identical_stamp_share": zs_r,
                "negative_deltas": int((dus < 0).sum()),
                "unparsed_stamp_fraction": int(sum(1 for f in fr if f is None)),
                "gcd_abs_nonzero_delta_us": int(np.gcd.reduce(nz)) if len(nz) else None,
                "min_abs_nonzero_delta_us": int(nz.min()) if len(nz) else None})
    return out


# ================================================================================================ unit analysis
def anon_sessions(sids, private):
    if not private:
        return {s: s for s in sids}
    return {s: f"s{i:03d}" for i, s in enumerate(sorted(set(sids)))}


def nested_bad_set(unit, u):
    """Subagent pairs excluded from G (prereg_calibration.probe1_unit, verbatim logic)."""
    nested_bad = set()
    if unit in ("swechat/claude_code", "cc_local"):
        nn = u[u.parent_call_id.notna() & u.kind.isin(["result", "call"])]
        for s, pcid, kind, txt, tl in zip(nn.session_id, nn.parent_call_id.astype(str), nn.kind, nn.text.astype(object),
                                          nn.tool.astype(object)):
            if kind == "result" and error_marker(txt if isinstance(txt, str) else "") in ("cc_permission_denied",
                                                                                          "cc_interrupt_reject"):
                nested_bad.add((s, pcid))
            if kind == "call" and pc.tool_class(tl if isinstance(tl, str) else "") == "human_interactive":
                nested_bad.add((s, pcid))
    return nested_bad


def probe1_unit(unit, u, t0):
    private = unit == "cc_local"
    res_s = TH["stamp_resolution_s"]["aiv_cc"] if unit == "aiv_cc" else TH["stamp_resolution_s"]["ms_units"]
    out = {"B_sessions_in_cache": int(u.session_id.nunique()),
           "B_sessions_prereg": PR["population_B"]["sessions"].get(unit)}
    P = pc.make_pairs(u[u.kind.isin(["call", "result"])])
    out["pairs"] = int(len(P))
    out["pairs_sessions"] = int(P.session_id.nunique())
    # ---------------------------------------------------------------- 1. A1 kill rule on B
    out["a1_recheck_B"] = a1_recheck(P)
    print(f"[{time.time() - t0:6.1f}s] {unit}: pairs={len(P)} A1={out['a1_recheck_B']['verdict']}", flush=True)
    # ---------------------------------------------------------------- 2. no-human-wait filter (frozen A-side code)
    P = cal.p1_qualified(unit, u, P)
    P["chars_r"] = [len(t) if isinstance(t, str) else 0 for t in P.text_r.astype(object)]
    P["bytes_r"] = [len(t.encode("utf-8")) if isinstance(t, str) else 0 for t in P.text_r.astype(object)]
    out["filter_outcome"] = dict(Counter(P._rule_fail))
    out["qualified_by_class"] = {c: int(g.qualified.sum()) for c, g in P.groupby("cls")}
    out["all_by_class"] = {c: int(len(g)) for c, g in P.groupby("cls")}
    fin = np.isfinite(P.delta_s.to_numpy(dtype=float))
    out["negative_deltas_all_pairs"] = int((P.delta_s < 0).sum())
    Qall = P[P.qualified]  # qualified (finite delta by rule 1)
    Q = Qall[Qall.delta_s > 0]
    out["qualified_pairs"] = int(len(Qall))
    out["qualified_pairs_positive_delta"] = int(len(Q))
    out["qualified_sessions"] = int(Qall.session_id.nunique())

    allowed = P1["no_human_wait_filter"]["allowed_classes"][unit]

    def contaminated(cls, key):
        if unit == "aiv_cc":
            return cls in ("human_interactive", "subagent")
        if unit == "swechat/codex":
            return key in ("spawn_agent", "wait_agent", "close_agent", "list_agents", "write_stdin")
        return cls not in allowed

    # per tool_key, qualified
    tools = {}
    for k, g in Q.groupby("key"):
        full = Qall[Qall.key == k].delta_s.to_numpy(dtype=float)
        row = dist_block(g.delta_s.to_numpy(), g.session_id.to_numpy(), full=full, res_s=res_s)
        row["class"] = pc.tool_class(k)
        row["spearman_bytes_latency"] = spearman_ci(g.bytes_r.to_numpy(), g.delta_s.to_numpy(), g.session_id.to_numpy())
        row["result_bytes"] = {"p50": float(np.median(g.bytes_r)), "max": int(g.bytes_r.max())}
        tools[k] = row
    out["qualified_by_tool"] = tools
    # per tool class, qualified
    classes = {}
    for c, g in Q.groupby("cls"):
        full = Qall[Qall.cls == c].delta_s.to_numpy(dtype=float)
        row = dist_block(g.delta_s.to_numpy(), g.session_id.to_numpy(), full=full)
        row["tool_keys"] = sorted(set(g.key))
        row["spearman_bytes_latency"] = spearman_ci(g.bytes_r.to_numpy(), g.delta_s.to_numpy(), g.session_id.to_numpy())
        classes[c] = row
    out["qualified_by_class_dist"] = classes
    print(f"[{time.time() - t0:6.1f}s] {unit}: per-tool qualified stats done", flush=True)
    # all pairs (unfiltered) for reference
    A = P[fin & (P.delta_s > 0)]
    allt = {}
    for k, g in A.groupby("key"):
        full = P[fin & (P.key == k)].delta_s.to_numpy(dtype=float)
        row = dist_block(g.delta_s.to_numpy(), g.session_id.to_numpy(), full=full)
        row["class"] = pc.tool_class(k)
        row["human_wait_contaminated"] = bool(contaminated(pc.tool_class(k), k))
        allt[k] = row
    out["all_pairs_by_tool"] = allt
    allc = {}
    for c, g in A.groupby("cls"):
        full = P[fin & (P.cls == c)].delta_s.to_numpy(dtype=float)
        row = dist_block(g.delta_s.to_numpy(), g.session_id.to_numpy(), full=full)
        row["human_wait_contaminated_tool_keys"] = sorted({k for k in set(g.key) if contaminated(c, k)})
        row["spearman_bytes_latency"] = spearman_ci(g.bytes_r.to_numpy(), g.delta_s.to_numpy(), g.session_id.to_numpy())
        allc[c] = row
    out["all_pairs_by_class"] = allc
    print(f"[{time.time() - t0:6.1f}s] {unit}: all-pairs stats done", flush=True)

    # ---------------------------------------------------------------- 3. FLAT (near-zero variance)
    W_KEYS = set(cal.W_KEYS[unit]) if unit in cal.W_KEYS else set(TOOL_CLASSES_AUTO_READ)
    flat = {}
    for k, row in tools.items():
        if row["n"] < TH["flat_min_pairs"] or row["n_sessions"] < TH["flat_min_sessions"]:
            flat[k] = {"reportable": False, "n": row["n"], "n_sessions": row["n_sessions"], "in_W": k in W_KEYS}
            continue
        f1 = row["iqr_s"] <= TH["flat_iqr_res_mult"] * res_s
        f2 = row["iqr_log10"] < TH["flat_iqr_log10"]
        flat[k] = {"reportable": True, "in_W": k in W_KEYS, "iqr_s": row["iqr_s"], "iqr_log10": row["iqr_log10"],
                   "flat_by_iqr_s": bool(f1), "flat_by_iqr_log10": bool(f2), "FLAT": bool(f1 or f2),
                   "n": row["n"], "n_sessions": row["n_sessions"]}
    wrep = [k for k, v in flat.items() if v["in_W"] and v["reportable"]]
    out["flat_test"] = {"stamp_resolution_s": res_s, "by_tool": flat, "W_reportable": sorted(wrep),
                        "W_reportable_flat": sorted(k for k in wrep if flat[k]["FLAT"]),
                        "all_W_flat_kill": bool(len(wrep) > 0 and all(flat[k]["FLAT"] for k in wrep))}

    # ---------------------------------------------------------------- 4. floor transfer
    floorsA = RES1["floors"].get(unit, {})
    tr = {}
    for k, ent in floorsA.items():
        if "p5" not in ent:
            continue
        g = Q[Q.key == k]
        row = {"A_p5": ent["p5"], "A_n": ent["n_A"], "A_sessions": ent["sessions_A"], "B_n": int(len(g)),
               "B_sessions": int(g.session_id.nunique()),
               "A_p5_le_stamp_resolution": bool(ent["p5"] <= res_s + 1e-12)}
        if len(g) < TH["transfer_min_B_n"] or row["B_sessions"] < MIN_N["rate_reportable"]["sessions_min"]:
            row["label"] = "NOT_TESTED_B_n"
            row["untested_only_by_session_rule"] = bool(len(g) >= TH["transfer_min_B_n"])
            tr[k] = row
            continue
        r = rate_from_mask(g.delta_s.to_numpy() < ent["p5"], g.session_id.to_numpy())
        row["share_below_A_p5"] = r
        # with zero / negative qualified deltas included (they are below any floor)
        gq = Qall[Qall.key == k]
        row["share_below_A_p5_incl_zero_neg"] = rate_from_mask(gq.delta_s.to_numpy() < ent["p5"], gq.session_id.to_numpy())
        lo, hi = r["lo"], r["verdict_hi"]
        b0, b1 = TH["transfer_band"]
        if lo <= b1 and hi >= b0:
            row["label"] = "TRANSFERS"
        else:
            row["label"] = "FLOOR_SHIFT"
            row["direction"] = "B_floor_lower (more pairs below A p5)" if lo > b1 else "B_floor_higher (fewer pairs below A p5)"
        tr[k] = row
    tested = [k for k, v in tr.items() if v["label"] in ("TRANSFERS", "FLOOR_SHIFT")]
    shifted = [k for k in tested if tr[k]["label"] == "FLOOR_SHIFT"]
    tq = [k for k in tested if not tr[k]["A_p5_le_stamp_resolution"]]
    sq = [k for k in tq if tr[k]["label"] == "FLOOR_SHIFT"]
    out["floor_transfer"] = {"by_tool": tr, "tested": sorted(tested), "floor_shift": sorted(shifted),
                             "majority_floor_shift": bool(len(tested) > 0 and len(shifted) > len(tested) / 2),
                             "untested_only_by_session_rule": sorted(k for k, v in tr.items()
                                                                     if v.get("untested_only_by_session_rule")),
                             "sensitivity_excluding_A_p5_at_stamp_resolution": {
                                 "tested": sorted(tq), "floor_shift": sorted(sq),
                                 "majority_floor_shift": bool(len(tq) > 0 and len(sq) > len(tq) / 2),
                                 "note": "descriptive; the verdict uses the pre-registered set above"}}

    # ---------------------------------------------------------------- 5. floor step change
    amap = anon_sessions(Q.session_id.unique().tolist(), private)
    series = []
    Qs = Q.sort_values(["session_id", "seq"])
    for (s, k), g in Qs.groupby(["session_id", "key"], sort=True):
        if len(g) >= 2 * TH["step_m"]:
            series.append((s, k, np.log10(g.delta_s.to_numpy(dtype=float))))
    series.sort(key=lambda x: (x[0], x[1]))
    rows = []
    for i, (s, k, x) in enumerate(series):
        cp = pc.change_point(x, m=TH["step_m"], n_perm=TH["step_n_perm"], seed=stats.SEED + i)
        left, right = float(np.quantile(x[:cp["k"]], 0.10)), float(np.quantile(x[cp["k"]:], 0.10))
        rows.append({"session": amap[s], "tool_key": k, "n": cp["n"], "k": cp["k"], "k_over_n": cp["k"] / cp["n"],
                     "D_log10": cp["D"], "factor": 10 ** cp["D"], "p": cp["p"], "step": cp["step"],
                     "direction": cp["direction"], "Q10_left_s": 10 ** left, "Q10_right_s": 10 ** right,
                     "_sid": s})
    print(f"[{time.time() - t0:6.1f}s] {unit}: change points on {len(rows)} series done", flush=True)
    n_el, n_st = len(rows), sum(r["step"] for r in rows)
    sc = {"eligible_series": n_el, "steps": int(n_st),
          "eligible_sessions": len({r["_sid"] for r in rows}),
          "sessions_with_step": len({r["_sid"] for r in rows if r["step"]})}
    if n_el:
        sc["step_share_wilson"] = dict(zip(("p", "lo", "hi"), stats.wilson(int(n_st), n_el)))
        num, den = Counter(), Counter()
        for r in rows:
            den[r["_sid"]] += 1
            num[r["_sid"]] += int(r["step"])
        ks = list(den)
        sc["step_share_cluster_rate_over_sessions"] = stats.cluster_rate([num[x] for x in ks], [den[x] for x in ks])
        sc["label"] = "STABLE" if n_st / n_el <= TH["step_share_unstable"] else "UNSTABLE"
        sc["by_tool"] = {k: {"eligible": sum(1 for r in rows if r["tool_key"] == k),
                             "steps": sum(1 for r in rows if r["tool_key"] == k and r["step"])}
                         for k in sorted({r["tool_key"] for r in rows})}
        Ds = np.array([r["D_log10"] for r in rows])
        sc["D_log10_all_series"] = {"p50": float(np.median(Ds)), "p90": float(np.quantile(Ds, 0.9)), "max": float(Ds.max())}
        sc["p_le_0.01_any_D"] = int(sum(1 for r in rows if r["p"] <= TH["step_p"]))
        stp = [r for r in rows if r["step"]]
        sc["steps_by_direction"] = dict(Counter(r["direction"] for r in stp))
        sc["step_factor_quantiles"] = ({"min": float(min(r["factor"] for r in stp)),
                                        "p50": float(np.median([r["factor"] for r in stp])),
                                        "max": float(max(r["factor"] for r in stp)),
                                        "n_factor_ge_10": int(sum(1 for r in stp if r["factor"] >= 10))}
                                       if stp else None)
        p_min = 1 / (TH["step_n_perm"] + 1)
        n_b = int(sum(1 for r in rows if r["step"] and r["p"] > p_min + 1e-12))
        sc["sensitivity_steps_at_p_boundary"] = {
            "steps_with_p_above_minimum": n_b, "minimum_p": p_min,
            "step_share_without_them": (n_st - n_b) / n_el,
            "label_without_them": "STABLE" if (n_st - n_b) / n_el <= TH["step_share_unstable"] else "UNSTABLE",
            "note": "descriptive: steps whose permutation p is above the minimum attainable 1/200 could flip under "
                    "another seed convention; the verdict uses the pre-registered label above"}
        sc["D_ge_log10_2_any_p"] = int(sum(1 for r in rows if r["D_log10"] >= TH["step_D"]))
    else:
        sc["label"] = "NO_ELIGIBLE_SERIES"
    for r in rows:
        r.pop("_sid")
    sc["series"] = rows
    out["floor_step_change"] = sc

    # ---------------------------------------------------------------- 6. separability
    G90 = RES1["generation_rate"][unit]["G90"]
    tpc = TH["tokens_per_char"]
    W = Q[Q.key.isin(W_KEYS)] if unit in cal.W_KEYS else Q[Q.cls == "auto_read"]
    nested_bad = nested_bad_set(unit, u)
    nested_check = None
    if "subagent" in cal.G_TOOLS.get(unit, set()) and unit not in ("swechat/claude_code", "cc_local"):
        subr = u[u.is_subagent.astype("boolean").fillna(False).astype(bool) & u.kind.isin(["call", "result"])]
        nested_check = {
            "note": "prereg_calibration applies the nested human-marker exclusion only in swechat CC and cc_local "
                    "(same-session parent_call_id link). Here: counts over ALL subagent-thread rows of the unit "
                    "(any session), an upper bound on what a cross-session exclusion could remove.",
            "subagent_thread_rows": int(len(subr)),
            "reject_markers_in_subagent_results": int(sum(
                1 for t in subr[subr.kind == "result"].text.astype(object)
                if error_marker(t if isinstance(t, str) else "") in ("cc_permission_denied", "cc_interrupt_reject"))),
            "human_interactive_calls_in_subagent_threads": int(sum(
                1 for t in subr[subr.kind == "call"].tool.astype(object)
                if pc.tool_class(t if isinstance(t, str) else "") == "human_interactive"))}
    gl, gsid, gch, gby, gkey = [], [], [], [], []
    gexcl = Counter()
    for k, d, x, s, cid, mk, ch, by in zip(P.key, P.delta_s, P._rx, P.session_id, P.call_id.astype(str), P.marker,
                                           P.chars_r, P.bytes_r):
        if k not in cal.G_TOOLS.get(unit, set()):
            continue
        if mk in ("cc_permission_denied", "cc_interrupt_reject"):
            gexcl["reject_marker"] += 1
            continue
        if (s, cid) in nested_bad:
            gexcl["nested_human_marker_or_interactive"] += 1
            continue
        lat = cal.g_latency(unit, k, d, x)
        if lat is None:
            gexcl["no_tool_reported_duration"] += 1
            continue
        if not np.isfinite(lat) or lat <= 0:
            gexcl["nonpositive_or_missing_latency"] += 1
            continue
        gl.append(lat), gsid.append(s), gch.append(ch), gby.append(by), gkey.append(k)
    gl, gch, gby = np.array(gl, dtype=float), np.array(gch, dtype=float), np.array(gby, dtype=float)
    gsid, gkey = np.array(gsid, dtype=object), np.array(gkey, dtype=object)
    Tw = W.chars_r.to_numpy(dtype=float) * tpc / G90
    Tg = gch * tpc / G90
    ew = Tw >= TH["T_gen_min_s"]
    eg = Tg >= TH["T_gen_min_s"]
    rw = W.delta_s.to_numpy(dtype=float)[ew] / Tw[ew]
    rg = gl[eg] / Tg[eg] if len(gl) else np.array([])
    sw = W.session_id.to_numpy()[ew]
    sg = gsid[eg] if len(gl) else np.array([], dtype=object)
    sep = {"G90_tok_per_s_from_A": G90, "G90_method_A": RES1["generation_rate"][unit]["method"],
           "G50_tok_per_s_from_A": RES1["generation_rate"][unit]["G50"],
           "G_rates_n_A": RES1["generation_rate"][unit]["n_rates_A"],
           "G_rates_sessions_A": RES1["generation_rate"][unit]["sessions_A"],
           "tokens_per_char": tpc, "T_gen_min_s": TH["T_gen_min_s"],
           "result_chars_for_T_gen_1s": G90 * TH["T_gen_min_s"] / tpc,
           "W_definition": sorted(W_KEYS) if unit in cal.W_KEYS else "class auto_read",
           "W_all": {"n": int(len(W)), "sessions": int(W.session_id.nunique()),
                     "by_tool": dict(Counter(W.key))},
           "W_eligible": {"n": int(ew.sum()), "sessions": int(len(set(sw.tolist()))),
                          "by_tool": dict(Counter(W.key.to_numpy()[ew].tolist()))},
           "G_tools": sorted(cal.G_TOOLS.get(unit, set())),
           "G_usable": {"n": int(len(gl)), "sessions": int(len(set(gsid.tolist()))), "by_tool": dict(Counter(gkey.tolist())),
                        "excluded": dict(gexcl)},
           "G_nested_exclusion_crosscheck": nested_check,
           "G_eligible": {"n": int(eg.sum()), "sessions": int(len(set(sg.tolist()))),
                          "by_tool": dict(Counter(gkey[eg].tolist())) if len(gl) else {}}}
    w_ok = sep["W_eligible"]["n"] >= TH["W_min_pairs"] and sep["W_eligible"]["sessions"] >= TH["W_min_sessions"]
    g_ok = sep["G_eligible"]["n"] >= TH["G_min_pairs"] and sep["G_eligible"]["sessions"] >= TH["G_min_sessions"]
    sep["W_meets_min_n"], sep["G_meets_min_n"] = bool(w_ok), bool(g_ok)
    # distributions of r (descriptive; reported regardless of min n with n attached)
    if len(rw):
        lrw = np.log10(rw)
        sep["W_log10_r"] = dist_like(lrw, sw)
        sep["W_r_log_histogram"] = stats.log_histogram(rw)
        sep["W_r_quantiles"] = {f"p{round(q * 100, 2):g}": float(np.quantile(rw, q)) for q in (0.5, 0.9, 0.95, 0.99)}
        sep["W_r_quantiles"]["max"] = float(rw.max())
        sep["W_spearman_bytes_latency"] = spearman_ci(W.bytes_r.to_numpy(dtype=float)[ew], W.delta_s.to_numpy(dtype=float)[ew], sw)
        fpk = {}
        wk = W.key.to_numpy()[ew]
        for k in sorted(set(wk.tolist())):
            m = wk == k
            fpk[k] = {"n": int(m.sum()), "r_ge_1": int((rw[m] >= 1).sum()),
                      "sessions": int(len(set(sw[m].tolist())))}
        sep["W_eligible_r_ge_1_by_tool"] = fpk
    if len(rg):
        lrg = np.log10(rg)
        sep["G_log10_r"] = dist_like(lrg, sg)
        sep["G_r_log_histogram"] = stats.log_histogram(rg)
        sep["G_spearman_bytes_latency"] = spearman_ci(gby[eg], gl[eg], sg)
        gk = gkey[eg]
        sep["G_eligible_by_tool"] = {k: {"n": int((gk == k).sum()), "r_ge_1": int((rg[gk == k] >= 1).sum()),
                                         "median_r": float(np.median(rg[gk == k]))} for k in sorted(set(gk.tolist()))}
        sep["G_latency_s"] = {"p50": float(np.median(gl[eg])), "min": float(gl[eg].min()), "max": float(gl[eg].max())}
    # fp_share
    if w_ok:
        fp = rate_from_mask(rw >= 1, sw)
        sep["fp_share"] = fp
        p, hi = fp["rate"], fp["verdict_hi"]
        if p <= TH["fp_alive_point"] and hi <= TH["fp_alive_hi"]:
            fpl = "ALIVE"
        elif p <= TH["fp_weak_point"]:
            fpl = "WEAK"
        else:
            fpl = "DEAD"
    else:
        sep["fp_share"] = {"num": int((rw >= 1).sum()), "den": int(len(rw)), "n_sessions": int(len(set(sw.tolist()))),
                           "label": "INSUFFICIENT_N"}
        fpl = "INSUFFICIENT_N"
    sep["fp_label"] = fpl
    # AUC
    if w_ok and g_ok:
        a = auc_ci(np.log10(rg), sg, np.log10(rw), sw)
        sep["auc"] = a
        if a["auc"] >= TH["auc_alive_point"] and a.get("lo") is not None and a["lo"] >= TH["auc_alive_lo"]:
            al = "ALIVE"
        elif a["auc"] >= TH["auc_weak_point"]:
            al = "WEAK"
        else:
            al = "DEAD"
    else:
        sep["auc"] = {"auc_point_unreportable": auc_value(np.log10(rg), np.log10(rw)) if (len(rg) and len(rw)) else None,
                      "n_G": int(len(rg)), "n_W": int(len(rw)), "label": "INSUFFICIENT_N"}
        al = "INSUFFICIENT_N"
    sep["auc_label"] = al
    out["separability"] = sep
    print(f"[{time.time() - t0:6.1f}s] {unit}: separability fp={fpl} auc={al}", flush=True)

    # ---------------------------------------------------------------- 7. verdict
    out["verdict"] = unit_verdict(unit, out)
    return out


def dist_like(v, s):
    """Quantiles (with cluster CIs, min-n applied) of an arbitrary-sign variable, e.g. log10 r."""
    v = np.asarray(v, dtype=float)
    n, ns = len(v), len(set(np.asarray(s, dtype=object).astype(str).tolist()))
    out = {"n": int(n), "n_sessions": int(ns)}
    if n == 0:
        return out
    q = cal.qstats(v, s, qs=(0.05, 0.5, 0.95), ci_qs=(0.05, 0.5, 0.95))
    out["min"], out["max"] = q["min"], q["max"]
    for name in ("p5", "p50", "p95"):
        out[name] = q[name] if reportable(n, ns, name) else {"label": "INSUFFICIENT_N"}
    return out


TOOL_CLASSES_AUTO_READ = tuple(pc.TOOL_CLASSES["auto_read"])


def unit_verdict(unit, o):
    sep = o["separability"]
    kills = []
    if o["a1_recheck_B"]["verdict"] != "ALIVE":
        kills.append("A1_kill_rule_failed_on_B")
    if o["flat_test"]["all_W_flat_kill"]:
        kills.append("every_reportable_W_tool_FLAT")
    fpl, al = sep["fp_label"], sep["auc_label"]
    floor_label = o["floor_step_change"]["label"]
    maj_shift = o["floor_transfer"]["majority_floor_shift"]
    deciding = {"fp_share": sep["fp_share"], "auc": sep["auc"],
                "W_eligible": sep["W_eligible"]["n"], "W_eligible_sessions": sep["W_eligible"]["sessions"],
                "G_eligible": sep["G_eligible"]["n"], "G_eligible_sessions": sep["G_eligible"]["sessions"],
                "a1": {"verdict": o["a1_recheck_B"]["verdict"],
                       "identical_stamp_share": o["a1_recheck_B"].get("identical_stamp_share", {}).get("rate"),
                       "whole_second_stamp_share": o["a1_recheck_B"].get("whole_second_stamp_share", {}).get("rate")},
                "W_reportable_flat": o["flat_test"]["W_reportable_flat"], "W_reportable": o["flat_test"]["W_reportable"],
                "floor_step_label": floor_label,
                "step_share": (o["floor_step_change"]["steps"], o["floor_step_change"]["eligible_series"]),
                "floor_transfer_shift": (len(o["floor_transfer"]["floor_shift"]), len(o["floor_transfer"]["tested"]))}
    if kills:
        v, why = "DEAD", "kill: " + ", ".join(kills)
    elif fpl == "INSUFFICIENT_N":
        v, why = "INSUFFICIENT_N", "eligible W below min n"
    elif fpl == "DEAD" or al == "DEAD":
        v, why = "DEAD", f"fp label {fpl}, auc label {al}"
    elif fpl == "ALIVE" and al == "ALIVE":
        v, why = "ALIVE", "fp ALIVE and auc ALIVE"
    else:
        v, why = "WEAK", f"fp label {fpl}, auc label {al}"
    downgraded = None
    if v == "ALIVE" and (floor_label == "UNSTABLE" or maj_shift):
        downgraded = [x for x, c in (("floor UNSTABLE", floor_label == "UNSTABLE"),
                                     ("FLOOR_SHIFT in a majority of transfer-tested tool_keys", maj_shift)) if c]
        v, why = "WEAK", why + "; downgraded: " + ", ".join(downgraded)
    labels = []
    if unit == "aiv_cc":
        labels.append("single-agent case study")
    if (PR["population_B"]["sessions"].get(unit) or 0) < 30:
        labels.append("small n")
    return {"verdict": v, "rule_applied": why, "fp_label": fpl, "auc_label": al, "floor_step_label": floor_label,
            "floor_transfer_majority_shift": maj_shift, "kills": kills, "downgrade": downgraded, "labels": labels,
            "deciding": deciding}


# ================================================================================================ loading
def load_unit_frames(only=None):
    """Yields (unit, frame) for the Probe 1 units, one swechat format at a time (RAM). `only`: debug subset."""
    fm = pc.swechat_formats()
    sb = pd.read_parquet(pc.CACHE / "swechat_B.parquet", columns=["session_id"]).session_id.astype(str).unique()
    by_fmt = defaultdict(list)
    for s in sb:
        by_fmt[fm.get(s, "?")].append(s)
    for f in ("gemini", "codex", "opencode", "claude_code", "cursor"):
        ids = by_fmt.get(f, [])
        if not ids or (only and f"swechat/{f}" not in only):
            continue
        df = pc.load_split("swechat", "B", COLS, filters=[("session_id", "in", ids), ("kind", "in", KINDS)])
        yield f"swechat/{f}", df
    for c in ("cc_local", "aiv_cc", "aiv_cu", "whowhen"):
        if only and c not in only:
            continue
        yield c, pc.load_split(c, "B", COLS, filters=[("kind", "in", KINDS)])


def aiv_cc_overlap():
    a = pd.read_parquet(pc.CACHE / "aiv_cc_A.parquet", columns=["session_id"]).session_id.astype(str).unique()
    b = pd.read_parquet(pc.CACHE / "aiv_cc_B.parquet", columns=["session_id"]).session_id.astype(str).unique()
    sdk = lambda s: s.split("/")[0]
    a_sdk = {sdk(s) for s in a}
    b_sdk = Counter(sdk(s) for s in b)
    return {"B_runs": int(len(b)), "B_distinct_sdk_session_id": int(len(b_sdk)),
            "B_runs_sharing_sdk_session_with_an_A_run": int(sum(1 for s in b if sdk(s) in a_sdk)),
            "A_runs": int(len(a)), "A_distinct_sdk_session_id": int(len(a_sdk)),
            "B_runs_per_sdk_session_top5": sorted(b_sdk.values(), reverse=True)[:5]}


# ================================================================================================ main
DEVIATIONS = [
    {"item": "output path",
     "prereg_said": "data_rules.output_contract: analysis/out/phase_b/<probe>.json",
     "what_you_did": "wrote analysis/out/probe_1.json (the path the task names) and a byte-identical copy at "
                     "analysis/out/phase_b/probe_1.json",
     "why": "the orchestrating task names analysis/out/probe_1.json; the copy keeps the prereg contract",
     "effect_on_verdict": "none"},
    {"item": "zero deltas in per-tool statistics",
     "prereg_said": "pair: negative deltas kept in counts and excluded from log-scale statistics; silent on zero "
                    "deltas for the linear quantiles, IQR, FLAT, floor transfer, step change and W",
     "what_you_did": "all per-tool statistics, FLAT, transfer, step change and the W set use qualified pairs with "
                     "delta_s > 0, exactly as the A-split floors were computed (prereg_calibration.probe1_unit: "
                     "Q = qualified & delta_s > 0); zero/negative counts are reported per tool (n_zero, n_negative), "
                     "and the transfer share is also reported with them included",
     "why": "the transfer test compares B against the A p5, which excluded zeros; another population would not be "
            "like-for-like",
     "effect_on_verdict": "none found: non-positive qualified deltas = qualified_pairs - "
                          "qualified_pairs_positive_delta per unit. A zero delta has r = 0 < 1, so including them "
                          "could only lower fp_share"},
    {"item": "change-point seed index",
     "prereg_said": "np.random.default_rng(SEED + i), i = 0-based index of the series in sorted (session_id, "
                    "tool_key) order",
     "what_you_did": "i indexes the ELIGIBLE series (n >= 40) in sorted (session_id, tool_key) order",
     "why": "the text does not say whether ineligible series are counted; only eligible series are tested",
     "effect_on_verdict": "only steps with p above the minimum attainable 1/200 could flip under another "
                          "convention; floor_step_change.sensitivity_steps_at_p_boundary gives the label without "
                          "them"},
    {"item": "floor transfer minimum sessions",
     "prereg_said": "floor transfer only for unit x tool_key with an A p5 and B n >= 100",
     "what_you_did": "also required >= 5 B sessions (global.min_n.rate_reportable applies to every rate)",
     "why": "global min-n rule for rates",
     "effect_on_verdict": "none if floor_transfer.untested_only_by_session_rule is empty (see JSON)"},
    {"item": "FLAT kill with no reportable W tool_key",
     "prereg_said": "the unit is DEAD if every reportable W tool_key is FLAT",
     "what_you_did": "the kill requires at least one reportable W tool_key (no vacuous truth)",
     "why": "with none reportable, W is also below the separability min n, which the rule maps to INSUFFICIENT_N",
     "effect_on_verdict": "none if every testable unit has >= 1 reportable W tool_key (flat_test.W_reportable)"},
    {"item": "nested human-marker exclusion for G subagent pairs outside CC formats",
     "prereg_said": "exclude subagent pairs whose nested events (parent_call_id == call_id) contain a rejection "
                    "marker or a human_interactive call",
     "what_you_did": "applied in swechat CC and cc_local only, as prereg_calibration did on A (same-session link); "
                     "for OpenCode, whose subagents are separate session_ids, an upper-bound cross-check is reported "
                     "(separability.G_nested_exclusion_crosscheck)",
     "why": "the A-side G counts were built with that code; OpenCode child threads do not share the parent "
            "session_id",
     "effect_on_verdict": "none if the cross-check counts are 0 (see JSON)"},
]


def main(argv=()):
    """argv: optional unit names for a debug run; the output then goes to the path in env PROBE1_DEBUG_OUT and the
    official outputs are not touched."""
    only = set(argv) or None
    t0 = time.time()
    spec_sha = sha256(SPEC_PATH)
    calib_sha = sha256(CALIB_PATH)
    prov = PR["provenance"]
    pre = {"prereg_json_sha256": sha256(PREREG_PATH),
           "spec_module_sha256_disk": spec_sha, "spec_module_sha256_prereg": prov["spec_module_sha256"],
           "spec_module_sha_ok": spec_sha == prov["spec_module_sha256"],
           "calibration_script_sha256_disk": calib_sha,
           "calibration_script_sha256_prereg": prov["calibration_script_sha256"],
           "calibration_script_sha_ok": calib_sha == prov["calibration_script_sha256"]}
    if not (pre["spec_module_sha_ok"] and pre["calibration_script_sha_ok"]):
        print("PREREG SHA MISMATCH: stopping", json.dumps(pre, indent=1))
        return 2
    check_thresholds_against_text()
    res = {"probe": "probe1_latency_physics", "script": "analysis/probes/probe_1.py", "split": "B",
           "prereg": pre, "thresholds_used": TH, "threshold_sources": TH_SOURCE,
           "implementation_notes": {
               "filter": "prereg_calibration.p1_qualified (the code that produced the A-split floors), imported unchanged",
               "G_latency": "prereg_calibration.g_latency, imported unchanged; G exclusions mirror prereg_calibration.probe1_unit",
               "pairs": "prereg_common.make_pairs (first call / first result by seq per (session_id, call_id))",
               "per_tool_quantiles": "qualified pairs with delta_s > 0 (as the A-split floors in resolved.probe1.floors); "
                                     "zero and negative qualified deltas are counted per tool (n_zero, n_negative) and "
                                     "the log histogram counts them under zero_or_negative",
               "quantile_ci": "prereg_calibration.qstats (draws identical to lib.stats.cluster_quantile)",
               "min_n": "quantiles below global.min_n.quantile_reportable are withheld (label INSUFFICIENT_N); min/max "
                        "and the log histogram are always reported"},
           "deviations": DEVIATIONS,
           "units": {}, "not_testable": {}, "verdicts": {}}
    for unit, df in load_unit_frames(only):
        df = df.reset_index(drop=True)
        if unit in P1["units_alive_after_A1"]:
            df.loc[df.kind != "result", "text"] = None  # only result text is used
            res["units"][unit] = probe1_unit(unit, df, t0)
            res["verdicts"][unit] = res["units"][unit]["verdict"]
        else:
            P = pc.make_pairs(df[df.kind.isin(["call", "result"])])
            corpus = "swechat" if unit.startswith("swechat/") else unit
            allsid = pd.read_parquet(pc.CACHE / f"{corpus}_B.parquet", columns=["session_id"]).session_id.astype(str)
            if corpus == "swechat":
                fm = pc.swechat_formats()
                allsid = allsid[allsid.map(fm) == unit.split("/")[1]]
            res["not_testable"][unit] = {"reason_prereg": P1["units_not_testable"].get(unit),
                                         "B_sessions": int(allsid.nunique()),
                                         "B_sessions_with_call_result_meta_system_user_rows": int(df.session_id.nunique()),
                                         "a1_recheck_B_descriptive": a1_recheck(P)}
            res["verdicts"][unit] = {"verdict": "NOT_TESTABLE", "rule_applied": P1["units_not_testable"].get(unit),
                                     "deciding": {"a1_recheck_B": res["not_testable"][unit]["a1_recheck_B_descriptive"]["verdict"]}}
            print(f"[{time.time() - t0:6.1f}s] {unit}: NOT_TESTABLE (A1 on B: "
                  f"{res['not_testable'][unit]['a1_recheck_B_descriptive']['verdict']})", flush=True)
        del df
    for unit in ("swechat/copilot", "swechat/simple_text"):
        res["not_testable"][unit] = {"reason_prereg": P1["units_not_testable"][unit], "B_sessions": 0}
        res["verdicts"][unit] = {"verdict": "NOT_TESTABLE", "rule_applied": P1["units_not_testable"][unit],
                                 "deciding": {"B_sessions": 0}}
    res["aiv_cc_split_overlap"] = aiv_cc_overlap()
    res["verdict_cells"] = {"unit_verdicts": len(res["verdicts"]),
                            "computed_testable": sum(1 for u in res["units"]),
                            "not_testable": len(res["not_testable"]),
                            "fp_labels_computed": sum(1 for u in res["units"].values()
                                                      if u["separability"]["fp_label"] != "INSUFFICIENT_N"),
                            "auc_labels_computed": sum(1 for u in res["units"].values()
                                                       if u["separability"]["auc_label"] != "INSUFFICIENT_N"),
                            "multiplicity": PR["global"]["multiplicity"]}
    res["runtime_s"] = round(time.time() - t0, 1)
    txt = json.dumps(clean(res), indent=1, allow_nan=False)
    if only:
        import os
        dbg = os.environ["PROBE1_DEBUG_OUT"]
        open(dbg, "w", encoding="utf-8").write(txt)
        print(f"debug run ({sorted(only)}) -> {dbg}")
        return 0
    OUT.write_text(txt, encoding="utf-8")
    OUT_CONTRACT.parent.mkdir(parents=True, exist_ok=True)
    OUT_CONTRACT.write_text(txt, encoding="utf-8")
    print(f"done in {res['runtime_s']}s -> {OUT}")
    for u, v in res["verdicts"].items():
        print(f"  {u:22s} {v['verdict']:15s} {v.get('rule_applied')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
