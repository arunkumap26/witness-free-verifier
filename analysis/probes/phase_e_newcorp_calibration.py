"""Phase E pre-registered extension: A-split calibration of a NEW corpus (analysis/prereg_e.json splits.new_corpora).

Run from the worktree root, after the corpus loader:
  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_newcorp_calibration --corpus pub_cc_hf
  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_newcorp_calibration --corpus pub_trace_commons

Reads ONLY
  analysis/cache/<corpus>_A.parquet          via prereg_e_calibration.load_A (asserts split A, records the path)
  analysis/prereg_e.json                     frozen-module check (prereg_e_common.check_frozen) and the pre-registered
                                             pooled N1 bounds (resolved.n1)
  analysis/out/phase_e/newcorp_build_<corpus>.json   the loader's split hashes (no ids), copied into the extension record
Never opens a B/E/H cache, the sample files or any id list. Every opened path is recorded and checked against
prereg_e_calibration.FORBIDDEN at the end.

Writes
  analysis/out/phase_e/prereg_e_calibration_<corpus>.json   raw A-split calibration counts and threshold inputs
  analysis/out/phase_e/prereg_e_extensions/<corpus>.json    {corpus, calibration sha256, splits sha256, loader, time}
It does not edit analysis/prereg_e.json; the orchestrator appends the change_log entry and commits before any B/E read.

WHAT IS CALLED (nothing re-implemented)
  calibration               = prereg_e_calibration.calibrate_unit(corpus, FORMAT_PROXY_UNIT, u)       PRIMARY
  calibration_literal_unit  = prereg_e_calibration.calibrate_unit(corpus, corpus, u)                  reference
  phase_b_unit_functions    = prereg_calibration.probe1_unit / probe2_unit / probe3_unit(FORMAT_PROXY_UNIT, u): Probe 1
                              floors and G50/G90, Probe 2 extraction and depth inputs, Probe 3 L75. splits.new_corpora.
                              calibration names these thresholds, but calibrate_unit does not compute them.
  dominance_context_cluster_is_stratum = prereg_e_common.dominance(weights, session_cluster_map('cc_local', u)): the
                              cc_local branch of session_cluster_map clusters by the stratum column (= source repo for
                              pub_cc_hf). Informational: calibrate_unit's own dominance context sees one cluster.
  resolved_preview.n1       the N1 bounds rule of prereg_e_calibration.main(): the unit's A 0.5th/99.5th residual
                              percentiles when bounds_ok (>= 500 residuals from >= 5 sessions), else the pre-registered
                              pooled bounds (prereg_e.json resolved.n1, any 'pooled bounds' entry).

WHY A FORMAT PROXY UNIT (decision of this script; the orchestrator can override before any B/E read)
  The pre-registered functions dispatch on the unit NAME. A new corpus name is in none of their lists (n1 LAT units, N5
  units, probe4 testable units, error_definitions, CC_FORMAT_UNITS), so the literal call skips N1, N5 and F3 and has no
  error definition (prereg_common.error_classes returns (None, 'no_definition')). The N1 residual bounds and N5
  truncation constants that splits.new_corpora.calibration requires therefore cannot come from the literal call.
  FORMAT_PROXY_UNIT = 'cc_local': both corpora are raw Claude Code JSONL of the same generation as cc_local
  (attachment entries; hooks recorded as hook_* attachments with toolUseID, which cc_local's qualify rule excludes;
  0 progress entries, so swechat/claude_code's hook_progress rule would never fire). Side effects of the proxy, all
  inherited from cc_local's pre-registered rules: prereg_common.private_key() masks tool keys outside PUBLIC_CC_TOOLS
  to 'other_tool' / 'mcp__*' in the qualify step and in N5 tool labels (no effect on which shell/auto_read pairs
  qualify); G_TOOLS adds 'workflow'; n6 field_gate.raw_structured_counters = True. The corpus argument stays the real
  corpus name, so calibrate_unit's dominance context has a single cluster and r3_git (swechat/cc_local/aiv_cc only) is
  not computed.
"""
import argparse
import json
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.probes import prereg_calibration as pcal
from analysis.probes import prereg_common as pc
from analysis.probes import prereg_e_calibration as pce
from analysis.probes import prereg_e_common as pe

FORMAT_PROXY_UNIT = "cc_local"
LOADERS = {"pub_cc_hf": "analysis/loaders/load_pub_cc_hf.py", "pub_trace_commons": "analysis/loaders/load_pub_trace_commons.py"}
COMMON = "analysis/loaders/pub_cc_common.py"


def _try(fn, *a):
    try:
        return fn(*a)
    except Exception as ex:  # recorded, not hidden
        return {"error": f"{type(ex).__name__}: {ex}", "traceback_tail": traceback.format_exc().splitlines()[-3:]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True, choices=sorted(LOADERS))
    args = ap.parse_args(argv)
    corpus = args.corpus
    t0 = time.time()
    pj = pe.check_frozen()
    pce.opened(pe.PREREG_E_JSON)
    df = pce.load_A(corpus, pce.COLS)
    frames = pc.unit_frames(corpus, df)
    assert list(frames) == [corpus], list(frames)
    u = frames[corpus].reset_index(drop=True)
    print(f"[{time.time() - t0:5.1f}s] {corpus} A: {len(u)} rows, {u.session_id.nunique()} sessions", flush=True)

    res, R = pce.calibrate_unit(corpus, FORMAT_PROXY_UNIT, u)
    lit, _ = pce.calibrate_unit(corpus, corpus, u)
    print(f"[{time.time() - t0:5.1f}s] calibrate_unit done", flush=True)

    pb = {"unit_argument": FORMAT_PROXY_UNIT,
          "probe1": _try(pcal.probe1_unit, FORMAT_PROXY_UNIT, u)}
    r2 = _try(pcal.probe2_unit, FORMAT_PROXY_UNIT, u)
    if isinstance(r2, tuple):
        res2, dm, ds = r2
        dmv = np.asarray(dm, dtype=float)
        pb["probe2"] = res2
        pb["probe2_depth_inputs"] = {"n": int(len(dmv)), "sessions": int(len(set(ds))),
                                     "quantiles": {f"q{q:g}": float(np.quantile(dmv, q)) for q in (0.5, 0.75, 0.9)}
                                     if len(dmv) else {},
                                     "note": "raw depth list summary; the D_unit resolution rule of "
                                             "prereg_calibration.main() is not applied here"}
    else:
        pb["probe2"] = r2
    pb["probe3"] = _try(pcal.probe3_unit, FORMAT_PROXY_UNIT, u)
    pb["note"] = ("raw outputs of the Phase B per-unit calibration functions on this corpus's A split (counts and "
                  "threshold inputs; Phase B outcomes are not computed by these functions)")

    P, Q = pce.unit_pairs(FORMAT_PROXY_UNIT, u)
    w = Q.groupby("session_id").size().to_dict()
    dom_stratum = pe.dominance(w, pe.session_cluster_map("cc_local", u)) if w else {}
    dom_stratum["note"] = ("cluster = stratum column (pub_cc_hf: source repo, top 8 + other; pub_trace_commons: modal "
                           "model); weights = paired calls per session (as cal_dominance)")

    pooled = None
    for unit, ent in pj["resolved"]["n1"].items():
        if str(ent.get("source", "")).startswith("pooled"):
            pooled = {"bounds": ent["bounds"], "pooled_n_A": ent.get("pooled_n_A"),
                      "pooled_sessions_A": ent.get("pooled_sessions_A"), "copied_from_unit_entry": unit}
            break
    n1 = res.get("n1", {})
    q = n1.get("residuals", {}).get("quantiles", {})
    if n1.get("bounds_ok"):
        n1b = {"bounds": [q["q0.005"], q["q0.995"]], "source": "unit", "n_A": q["n"], "sessions_A": q.get("n_sessions")}
    else:
        n1b = {"bounds": pooled["bounds"] if pooled else None,
               "source": "pre-registered pooled bounds (unit has < 500 A residuals or < 5 sessions)",
               "n_A": q.get("n", 0), "sessions_A": q.get("n_sessions", 0), "pooled": pooled}

    bad = [p for p in pce.OPENED if pce.FORBIDDEN.search(p)]
    assert not bad, f"forbidden files opened: {bad}"
    out = {
        "corpus": corpus, "unit": corpus, "split": "A only (asserted; B/E/EH/H never opened)",
        "script": "analysis/probes/phase_e_newcorp_calibration.py",
        "prereg_rule": "analysis/prereg_e.json splits.new_corpora.calibration",
        "prereg_e_json_sha256": pe.sha256_file(pe.PREREG_E_JSON),
        "prereg_e_common_frozen_check": "passed (prereg_e_common.check_frozen)",
        "a_cache_sha256": pe.sha256_file(pe.CACHE / f"{corpus}_A.parquet"),
        "sessions_A": int(u.session_id.nunique()), "rows_A": int(len(u)),
        "primary": "calibration",
        "format_proxy_unit": FORMAT_PROXY_UNIT,
        "format_proxy_reason": "see this script's docstring, WHY A FORMAT PROXY UNIT",
        "calibration": res,
        "calibration_literal_unit": lit,
        "phase_b_unit_functions": pb,
        "dominance_context_cluster_is_stratum": dom_stratum,
        "resolved_preview": {"length_terciles_A": res.get("length_terciles"), "n1": n1b,
                             "n2": {"GRANULAR": res.get("n2", {}).get("granularity", {}).get("GRANULAR"),
                                    "tau": res.get("n2", {}).get("tau"), "tau_n_A": res.get("n2", {}).get("tau_n")},
                             "n5_truncation_A": res.get("n5", {}).get("c_truncation_A"),
                             "n6_field_gate_A": res.get("n6_field_gate"),
                             "bracket_A": res.get("bracket"),
                             "note": "copied from `calibration` except n1, which applies prereg_e_calibration.main()'s "
                                     "bounds rule; the pre-registered pooled truncation constants "
                                     "(prereg_e.json resolved.n5.truncation_constants_pooled) are not recomputed"},
        "n1_residual_rows_A": int(len(R)),
        "not_computed": "Phase E outcomes: N1/N3 correlations, detector flag or violation rates, determinism drift, "
                        "round-number shares, recalls, tamper results, bracket verdicts on B/E",
        "opened_files": sorted(set(pce.OPENED)),
        "runtime_s": round(time.time() - t0, 1),
    }
    cal_path = pe.OUT_E / f"prereg_e_calibration_{corpus}.json"
    cal_path.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")

    build = json.loads((pe.OUT_E / f"newcorp_build_{corpus}.json").read_text(encoding="utf-8"))
    sp = build["splits"]
    ext = {
        "corpus": corpus,
        "kind": "pre-registered extension (prereg_e.json splits.new_corpora)",
        "calibration_file": f"analysis/out/phase_e/prereg_e_calibration_{corpus}.json",
        "calibration_sha256": pe.sha256_file(cal_path),
        "calibration_primary_unit_argument": FORMAT_PROXY_UNIT,
        "splits": {"seed": sp["seed"], "N": sp["N"], "sizes": sp["sizes"], "floor_used": sp["floor_used"],
                   "samples_json": sp["files"]["samples_json"], "samples_json_sha256": sp["files"]["samples_json_sha256"],
                   "samples_EH_json": sp["files"]["samples_EH_json"],
                   "samples_EH_json_sha256": sp["files"]["samples_EH_json_sha256"],
                   "sha256_sorted_ids": sp["files"]["sha256_sorted_ids"],
                   "heldout_manifest": sp["heldout_manifest"],
                   "source": f"analysis/out/phase_e/newcorp_build_{corpus}.json (hashes computed by the loader when it "
                             f"wrote the files)"},
        "a_cache_sha256": out["a_cache_sha256"],
        "loader": LOADERS[corpus], "loader_sha256_lf": pe.sha256_lf(pe.ROOT / LOADERS[corpus]),
        "common_module": COMMON, "common_module_sha256_lf": pe.sha256_lf(pe.ROOT / COMMON),
        "calibration_script": "analysis/probes/phase_e_newcorp_calibration.py",
        "calibration_script_sha256_lf": pe.sha256_lf(pe.ROOT / "analysis/probes/phase_e_newcorp_calibration.py"),
        "prereg_e_json_sha256": out["prereg_e_json_sha256"],
        "build_report": f"analysis/out/phase_e/newcorp_build_{corpus}.json",
        "timestamp_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "status": "written before any B or E session of this corpus was parsed; the orchestrator appends this record "
                  "to prereg_e.json change_log and commits before any B/E measurement",
    }
    ext_dir = pe.OUT_E / "prereg_e_extensions"
    ext_dir.mkdir(parents=True, exist_ok=True)
    (ext_dir / f"{corpus}.json").write_text(json.dumps(ext, indent=1), encoding="utf-8")
    print(json.dumps({"corpus": corpus, "calibration_sha256": ext["calibration_sha256"], "n1": n1b,
                      "length_terciles": res.get("length_terciles"), "runtime_s": out["runtime_s"]}, indent=1,
                     default=str))


if __name__ == "__main__":
    main()
