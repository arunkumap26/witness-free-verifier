"""Loader: GLM-5.2 NF3-hybrid Terminal-Bench 2.1 traces -> IR caches for corpus `glm_tb21` (Phase E new corpus).

Run from the worktree root:
  PYTHONIOENCODING=utf-8 python -m analysis.loaders.load_glm_tb21             # audit + splits + A cache + calibration
  PYTHONIOENCODING=utf-8 python -m analysis.loaders.load_glm_tb21 --split B   # NEXT step only (B or E; never H)
  PYTHONIOENCODING=utf-8 python -m analysis.loaders.load_glm_tb21 --selftest  # A-only test of the split builder
`main()` is idempotent (seeded splits; outputs overwritten).

SOURCE (read-only): C:/Swarms/data/acquired/glm52-nf3-tb21-traces/hf_repo/traces/<task>__<trial>/ (HF
  0xSero/glm-5.2-nf3-hybrid-terminal-bench-2.1-traces @6020a41c, MIT card; CORPUS_INVENTORY.md 5.2). Same Harbor
  layout as tbench2: agent/trajectory.json (ATIF v1.7, Terminus-2), result.json, config.json, agent/recording.cast,
  agent/terminus_2.pane, verifier/*. hf_repo/.git, hf_repo/_acquisition, the job-level files directly under traces/
  (config.json, job.log, lock.json, result.json) and every name starting with '.' are never read.
  Self-hosted vLLM serving: there are no provider request ids or provider response ids in this corpus.

EVERYTHING ELSE IS THE tbench2 LOADER (analysis/loaders/load_tbench2.py), imported, not copied:
  field audit (`audit_counts('atif', ...)`, structural counts only), pass rule, length = tool calls with an id,
  split rule (`draw_splits`, prereg_e.json splits.new_corpora, seed SEED_NEW_CORPUS = 20261006), ATIF -> IR mapping
  (`parse_atif`: Terminus family -> ts_semantics 'host_after_exec', ts_kind 'shared_turn' on call+result steps,
  observation join by source_call_id / step_single / step_multi, call-less observations -> system), result.json
  whitelist (`trial_result_extra`; `config` with agent kwargs - api_base, model_info - is never read; the README says
  the endpoint and API key were redacted upstream; `agent_result.metadata.all_messages`, a second copy of the chat, is
  not read), credential redaction (`redact_events`), build/calibration/extension/report helpers.
  Differences from tbench2:
    session_id = the trial directory name (<task>__<trial>); there is one submission and one job.
    stratum = '<agent.name>__<agent.model_name>' read from the trajectory's top-level `agent` during the field audit
      (one value in this corpus), so stratification is by length tercile only (3 cells; floor 5 fits every draw).
    recording.cast and terminus_2.pane (a second terminal record) are not loaded.
    Pre-split reads: format discovery read 3 trajectories, 3 result.json and 2 config.json files for key names, value
    types and enum values only (no content); no session content was viewed before the split.
  N = trials passing the audit; A = min(200, floor(0.2 N)); B = E = min(2000, floor((N - A)/3)); H = the rest.

Outputs of main(): cache/samples/glm_tb21.json, cache/samples/glm_tb21_EH.json, cache/glm_tb21_population.parquet,
  cache/glm_tb21_split_index.parquet, cache/glm_tb21_A.parquet, out/phase_e/heldout_manifest_glm_tb21.json,
  out/phase_e/prereg_e_calibration_glm_tb21.json, out/phase_e/prereg_e_extensions/glm_tb21.json,
  out/phase_e/newcorp_build_glm_tb21.json.
"""
import argparse
import json
import os
import time

import pandas as pd

from analysis.loaders import load_tbench2 as T

CORPUS = "glm_tb21"
LOADER = "analysis/loaders/load_glm_tb21.py"
DATA_ROOT = os.path.join(os.environ.get("SWARMS_DATA", "C:/Swarms/data"), "acquired", "glm52-nf3-tb21-traces",
                         "hf_repo", "traces")


def discover(root=DATA_ROOT):
    out = []
    for trial in sorted(os.listdir(root)):
        pt = os.path.join(root, trial)
        if trial.startswith(".") or not os.path.isdir(pt):
            continue
        out.append({"session_id": trial, "submission": None, "job": None, "trial": trial, "dir": pt})
    return out


def audit_trial(t):
    row = {"session_id": t["session_id"], "stratum": None, "submission": None, "job": None, "trial": t["trial"],
           "formats_present": "", "also_has_atif": False, "format": None, "files": None,
           "has_result_json": os.path.isfile(os.path.join(t["dir"], "result.json")), "parse_ok": False,
           "native_parse_fallback_to_atif": False, "records": 0, "calls": 0, "calls_with_id": 0, "results": 0,
           "ts_records": 0, "bad_lines": 0, "agent_name": None, "agent_model": None, "schema": None,
           "audit_pass": False, "fail_reason": None}
    files = ["agent/trajectory.json"]
    if not os.path.isfile(os.path.join(t["dir"], files[0])):
        row["fail_reason"] = "no_structured_log"
        return row
    row["formats_present"] = "atif"
    try:
        c, meta = T.audit_counts("atif", t["dir"], files)
    except Exception as ex:  # noqa: BLE001
        row["fail_reason"] = f"parse_error:atif:{type(ex).__name__}"
        return row
    row.update({"format": "atif", "files": json.dumps(files), "parse_ok": True, "records": int(c["records"]),
                "calls": int(c["calls"]), "calls_with_id": int(c["calls_with_id"]), "results": int(c["results"]),
                "ts_records": int(c["ts"]), **meta})
    row["stratum"] = f"{meta.get('agent_name')}__{meta.get('agent_model')}"
    if row["calls_with_id"] < 1:
        row["fail_reason"] = "no_tool_call"
    elif row["results"] < 1:
        row["fail_reason"] = "no_tool_result"
    elif row["ts_records"] < 1:
        row["fail_reason"] = "no_timestamp"
    else:
        row["audit_pass"] = True
    return row


def population():
    rows = [audit_trial(t) for t in discover()]
    pop = pd.DataFrame(rows).sort_values("session_id").reset_index(drop=True)
    pop["length"] = pop["calls_with_id"].astype(int)
    return pop


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["B", "E"], help="NEXT step only: build cache/<corpus>_<split>.parquet")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    from analysis.probes import prereg_e_common as pe
    if a.split:
        ids = T.ids_for_split(CORPUS, a.split)
        df, cnt, errs, basic = T.build_split_cache(CORPUS, a.split, ids,
                                                   os.path.join(T.CACHE, f"{CORPUS}_{a.split}.parquet"), DATA_ROOT, procs=1)
        print(json.dumps({"split": a.split, "sessions": len(ids), "errors": len(errs), **basic}, indent=1))
        return
    if a.selftest:
        print(json.dumps(T.selftest(CORPUS, DATA_ROOT), indent=1))
        return
    t0 = time.time()
    pop = population()
    ab, eh, idx, man = T.write_splits(pop, CORPUS, pe.SEED_NEW_CORPUS, loader=LOADER)
    t_audit = time.time() - t0
    print(f"[{t_audit:.0f}s] audit: {len(pop)} candidates, N={ab['population_sessions']} A={len(ab['A'])} "
          f"B={len(ab['B'])} E={len(eh['E'])} H={len(eh['H'])}", flush=True)
    dfA, cnt, errs, basic = T.build_split_cache(CORPUS, "A", ab["A"], os.path.join(T.CACHE, f"{CORPUS}_A.parquet"),
                                                DATA_ROOT, procs=1)
    t_a = time.time() - t0
    print(f"[{t_a:.0f}s] A cache: {basic}", flush=True)
    cal, cal_path = T.calibrate(CORPUS, dfA, loader=LOADER)
    ext = T.write_extension(CORPUS, cal_path, loader=LOADER)
    st = T.selftest(CORPUS, DATA_ROOT)
    rep = {"corpus": CORPUS, "loader": LOADER, "source": "C:/Swarms/data/acquired/glm52-nf3-tb21-traces/hf_repo/traces "
                                                          "(HF 0xSero/glm-5.2-nf3-hybrid-terminal-bench-2.1-traces @6020a41c)",
           "population": T.audit_summary(pop), "splits": T.split_sizes(ab, eh, pop),
           "heldout_manifest": {"n_H": man["n_H"], "sha256_sorted_H_ids": man["sha256_sorted_H_ids"]},
           "A_cache": {"path": f"analysis/cache/{CORPUS}_A.parquet", "validate": {k: int(v) for k, v in basic.items()},
                       "parse_errors": errs, "loader_counters": dict(sorted(cnt.items())), **T.frame_report(dfA)},
           "calibration": {"path": os.path.relpath(cal_path, os.path.dirname(T.AN)).replace("\\", "/"),
                           "sha256": ext["calibration_sha256"]},
           "A_checks": T.a_checks(dfA), "extension": ext, "selftest_split_builder_on_A": st,
           "runtime_s": {"audit_and_splits": round(t_audit, 1), "A_cache": round(t_a - t_audit, 1),
                         "total": round(time.time() - t0, 1)}}
    with open(os.path.join(T.OUT_E, f"newcorp_build_{CORPUS}.json"), "w", encoding="utf-8") as f:
        json.dump(T._jsonable(rep), f, indent=1, default=str)
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
