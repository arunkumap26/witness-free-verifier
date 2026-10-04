"""Phase E (WA1): build the E-split IR caches for swechat and aiv_cu, the only corpora with an E split, and record what
was built. Counts only; no interpretation is written to the JSON.

The E split (analysis/cache/samples/<corpus>_EH.json key "E", drawn by analysis/probes/phase_e_split.py) is parsed by
each loader's own per-session code path through its `--split E` entry point (load_swechat.build_split_e,
load_aiv_cu.build_split_e). H is never built, opened or read: this script reads only the "E" key of the EH files, the
A/B sample lists, the E caches it builds, the A and B caches (equivalence check) and the cross-session link counts of
analysis/out/build/swechat_build.json (read-only).

Steps
  1. Guarded files: sha256, size and mtime of the A/B caches, the sample files, the population/session/turn tables, the
     A/B build reports and HELDOUT_MANIFEST.json. No <corpus>_H.parquet may exist (asserted before and after).
  2. Run `python -m analysis.loaders.<loader> --split E --rederive A B --scratch <dir>` for each corpus, timed.
  3. Read each analysis/cache/<corpus>_E.parquet back one row group at a time: ir.validate per row group, no session
     spans row groups, built session ids are a subset of the E list (sessions with zero events are listed), disjoint from
     A and B. Counts: sessions, rows, events by kind, sessions and events by stratum (swechat also by transcript format),
     calls without a result, results without a call, null ts.
  4. Code-path equivalence: the A and B splits re-derived through the same `--split E` entry point (scratch dir,
     never analysis/cache) are compared cell by cell with the existing analysis/cache/<corpus>_{A,B}.parquet.
  5. swechat session-level subagent link resolution, measured identically on A, B and E (LINK RULE below), because the
     E build resolves cross-session links against A+B+E transcripts only (the A/B build used all 5,850).
  6. Guarded files re-hashed: before == after per file, and equal to the pre-edit snapshot
     analysis/out/phase_e/e_cache_hashes_pre.json (taken with --hash-only before the loaders were edited) when present.

LINK RULE (swechat). A session-level subagent session is an OpenCode/Codex session (population `format`) whose events are
all is_subagent = True. It is "resolved" when some non-meta event carries a parent_call_id (the only parent_call_id a
non-meta event of these formats can carry is the session-level link; Codex meta events carry their own call id).

Writes analysis/out/phase_e/e_cache_build.json.
Run:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_cache_build [--scratch DIR]
      PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_e_cache_build --hash-only   (writes e_cache_hashes_pre.json)
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from analysis.lib import ir

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AN = os.path.join(ROOT, "analysis")
CACHE = os.path.join(AN, "cache")
SAMP = os.path.join(CACHE, "samples")
OUTD = os.path.join(AN, "out", "phase_e")
OUT = os.path.join(OUTD, "e_cache_build.json")
PRE = os.path.join(OUTD, "e_cache_hashes_pre.json")
CORPORA = {"swechat": "analysis.loaders.load_swechat", "aiv_cu": "analysis.loaders.load_aiv_cu"}
LOADER_REPORT = {c: os.path.join(OUTD, f"{c}_E_build.json") for c in CORPORA}

GUARDED = [
    "analysis/cache/swechat_A.parquet", "analysis/cache/swechat_B.parquet",
    "analysis/cache/aiv_cu_A.parquet", "analysis/cache/aiv_cu_B.parquet",
    "analysis/cache/samples/swechat.json", "analysis/cache/samples/aiv_cu.json",
    "analysis/cache/samples/swechat_EH.json", "analysis/cache/samples/aiv_cu_EH.json",
    "analysis/cache/swechat_population.parquet", "analysis/cache/aiv_cu_sessions.parquet",
    "analysis/cache/aiv_cu_turns.parquet",
    "analysis/out/build/swechat_build.json", "analysis/out/build/aiv_cu_build.json",
    "analysis/out/build/aiv_cu_pass1_stats.json",
    "analysis/HELDOUT_MANIFEST.json",
]
REQUIRED_AB = [g for g in GUARDED if g.endswith(("_A.parquet", "_B.parquet"))]
H_CACHES = [f"analysis/cache/{c}_H.parquet" for c in CORPORA]
TYPES = {pa.string(): pd.StringDtype(), pa.int64(): pd.Int64Dtype(), pa.bool_(): pd.BooleanDtype()}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot():
    snap = {}
    for rel in GUARDED:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            snap[rel] = {"exists": False}
            continue
        st = os.stat(p)
        snap[rel] = {"exists": True, "sha256": sha256(p), "bytes": st.st_size, "mtime_ns": st.st_mtime_ns}
    snap["_h_caches_present"] = [h for h in H_CACHES if os.path.exists(os.path.join(ROOT, h))]
    return snap


def e_ids(corpus):
    with open(os.path.join(SAMP, f"{corpus}_EH.json"), encoding="utf-8") as f:
        return list(json.load(f)["E"])  # only the E key is used


def e_alloc_by_stratum(corpus):
    with open(os.path.join(SAMP, f"{corpus}_EH.json"), encoding="utf-8") as f:
        alloc = json.load(f)["alloc_E"]
    out = {}
    for cell, k in alloc.items():
        s = cell.rsplit("|", 1)[0]
        out[s] = out.get(s, 0) + int(k)
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def ab_ids(corpus):
    with open(os.path.join(SAMP, f"{corpus}.json"), encoding="utf-8") as f:
        d = json.load(f)
    return set(d["A"]), set(d["B"])


def vc(s):
    return {str(k): int(v) for k, v in s.value_counts(dropna=False).items()}


def read_back(corpus, ids_e):
    """Validate analysis/cache/<corpus>_E.parquet one row group at a time and count it."""
    path = os.path.join(CACHE, f"{corpus}_E.parquet")
    pf = pq.ParquetFile(path)
    seen, val_rows, val_kinds, spans = set(), 0, {}, 0
    for g in range(pf.num_row_groups):
        df = pf.read_row_group(g).to_pandas(types_mapper=TYPES.get)
        df["seq"] = df["seq"].astype("int64")
        v = ir.validate(df)
        val_rows += v["rows"]
        for k, x in v.items():
            if k not in ("rows", "sessions"):
                val_kinds[k] = val_kinds.get(k, 0) + int(x)
        ids = set(df["session_id"].unique())
        spans += len(ids & seen)
        seen |= ids
        del df
    cols = ["session_id", "stratum", "kind", "call_id", "ts", "ts_kind", "corpus"]
    t = pq.read_table(path, columns=cols).to_pandas(types_mapper=TYPES.get)
    a_ids, b_ids = ab_ids(corpus)
    want = set(ids_e)
    built = set(t["session_id"].unique())
    calls = t[t.kind == "call"][["session_id", "call_id"]].drop_duplicates()
    res = t[t.kind == "result"][["session_id", "call_id"]]
    c_keys = set(map(tuple, calls.astype(object).values))
    r_keys = set(map(tuple, res.dropna().drop_duplicates().astype(object).values))
    first = t.drop_duplicates("session_id")
    out = {
        "path": f"analysis/cache/{corpus}_E.parquet", "bytes": os.path.getsize(path), "row_groups": pf.num_row_groups,
        "sha256": sha256(path),
        "validate": {"ir_validate_passed_every_row_group": True, "rows": int(val_rows), "kind_counts": val_kinds,
                     "sessions_spanning_row_groups": int(spans)},
        "sessions_requested_E": len(want), "sessions_built": len(built),
        "sessions_with_zero_events": sorted(want - built),
        "built_sessions_not_in_E_list": len(built - want),
        "built_sessions_in_A": len(built & a_ids), "built_sessions_in_B": len(built & b_ids),
        "rows": int(len(t)), "corpus_column_values": vc(t["corpus"]),
        "events_by_kind": vc(t["kind"]),
        "sessions_by_stratum": vc(first["stratum"]),
        "sessions_requested_by_stratum_alloc_E": e_alloc_by_stratum(corpus),
        "events_by_stratum": vc(t["stratum"]),
        "events_by_stratum_and_kind": {str(s): vc(g["kind"]) for s, g in t.groupby("stratum")},
        "events_by_ts_kind": vc(t["ts_kind"]),
        "ts_null": int(t["ts"].isna().sum()),
        "calls": int((t.kind == "call").sum()), "results": int((t.kind == "result").sum()),
        "distinct_calls_without_result": len(c_keys - r_keys),
        "results_without_call": int(len(res) - sum(1 for k in map(tuple, res.astype(object).values) if k in c_keys)),
    }
    if corpus == "swechat":
        pop = pd.read_parquet(os.path.join(CACHE, "swechat_population.parquet"), columns=["session_id", "format"],
                              filters=[("session_id", "in", sorted(built))])
        fmt = dict(zip(pop.session_id, pop.format))
        out["sessions_by_format"] = vc(first["session_id"].map(fmt))
        out["events_by_format"] = vc(t["session_id"].map(fmt))
    return out


def _obj(s):
    return s.astype(object).where(s.notna(), None).to_numpy()


def compare_rederived(corpus, split, scratch):
    """Cell-by-cell comparison of split A or B re-derived via `--split E --rederive A B` with the existing cache, one row
    group at a time when both files have the same row-group layout (they do when the code path is the same)."""
    cache = os.path.join(CACHE, f"{corpus}_{split}.parquet")
    red = os.path.join(scratch, f"{corpus}_{split}.rederived.parquet")
    pa_, pb_ = pq.ParquetFile(cache), pq.ParquetFile(red)
    ga = [pa_.metadata.row_group(i).num_rows for i in range(pa_.num_row_groups)]
    gb = [pb_.metadata.row_group(i).num_rows for i in range(pb_.num_row_groups)]
    out = {"cache": f"analysis/cache/{corpus}_{split}.parquet", "rederived_file": "scratch (throwaway, not kept)",
           "rows_cache": int(sum(ga)), "rows_rederived": int(sum(gb)), "row_groups_cache": len(ga),
           "row_groups_rederived": len(gb), "columns_equal": pa_.schema_arrow.names == pb_.schema_arrow.names}
    if ga != gb or not out["columns_equal"]:
        sa = pq.read_table(cache, columns=["session_id"]).to_pandas()["session_id"].value_counts()
        sb = pq.read_table(red, columns=["session_id"]).to_pandas()["session_id"].value_counts()
        j = pd.concat([sa.rename("cache"), sb.rename("rederived")], axis=1)
        out["sessions_with_row_count_difference"] = int((j["cache"] != j["rederived"]).sum())
        out["identical"] = False
        return out
    mism, rows_diff, key_same = {}, 0, True
    sess_cache, sess_diff, sess_non_pc = set(), set(), set()
    pc_set_to_null, pc_other = 0, 0
    for g in range(len(ga)):
        a, b = pa_.read_row_group(g).to_pandas(), pb_.read_row_group(g).to_pandas()
        sess_cache |= set(a.session_id)
        key_same &= bool((_obj(a.session_id) == _obj(b.session_id)).all() and (a.seq.to_numpy() == b.seq.to_numpy()).all())
        any_diff = np.zeros(len(a), dtype=bool)
        non_pc = np.zeros(len(a), dtype=bool)
        for c in a.columns:
            d = np.asarray(_obj(a[c]) != _obj(b[c]), dtype=bool)
            if d.any():
                mism[c] = mism.get(c, 0) + int(d.sum())
                any_diff |= d
                if c != "parent_call_id":
                    non_pc |= d
                else:
                    s2n = int((d & a[c].notna().to_numpy() & b[c].isna().to_numpy()).sum())
                    pc_set_to_null += s2n
                    pc_other += int(d.sum()) - s2n
        rows_diff += int(any_diff.sum())
        sess_diff |= set(a.session_id[any_diff])
        sess_non_pc |= set(a.session_id[non_pc])
        del a, b
    out.update({"sessions_cache": len(sess_cache), "row_keys_session_seq_identical": key_same,
                "cells_differing_by_column": mism, "rows_differing": rows_diff, "sessions_differing": len(sess_diff),
                "sessions_differing_only_in_parent_call_id": len(sess_diff - sess_non_pc),
                "parent_call_id_cache_set_rederived_null": pc_set_to_null,
                "parent_call_id_other_differences": pc_other,
                "identical": (not mism) and key_same})
    return out


def link_resolution(split_path, fmt):
    """LINK RULE (module docstring) on one swechat cache file."""
    t = pq.read_table(split_path, columns=["session_id", "kind", "is_subagent", "parent_call_id"]).to_pandas(
        types_mapper=TYPES.get)
    t["format"] = t["session_id"].map(fmt)
    t = t[t["format"].isin(["opencode", "codex"])]
    out = {}
    for f, g in t.groupby("format"):
        allsub = g.groupby("session_id")["is_subagent"].all()
        subs = set(allsub[allsub.fillna(False).astype(bool)].index)
        nm = g[(g.kind != "meta") & g.session_id.isin(subs)]
        res = set(nm.loc[nm["parent_call_id"].notna(), "session_id"])
        out[f] = {"sessions_of_format": int(g.session_id.nunique()), "session_level_subagent_sessions": len(subs),
                  "resolved": len(res), "unresolved": len(subs) - len(res)}
    return out


def run_loader(corpus, scratch):
    cmd = [sys.executable, "-m", CORPORA[corpus], "--split", "E", "--rederive", "A", "B", "--scratch", scratch]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    t0 = time.perf_counter()
    rc = subprocess.run(cmd, cwd=ROOT, env=env).returncode
    wall = time.perf_counter() - t0
    if rc != 0:
        raise SystemExit(f"{corpus} loader failed with exit code {rc}")
    return {"command": " ".join(["python", "-m", CORPORA[corpus], "--split", "E", "--rederive", "A", "B", "--scratch", "<scratch>"]),
            "exit_code": rc, "wall_s": round(wall, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hash-only", action="store_true")
    ap.add_argument("--scratch", default=os.environ.get("PHASE_E_SCRATCH") or os.path.join(tempfile.gettempdir(), "phase_e_cache_build"))
    args = ap.parse_args()
    os.makedirs(OUTD, exist_ok=True)
    if args.hash_only:
        snap = snapshot()
        assert not snap["_h_caches_present"], snap["_h_caches_present"]
        with open(PRE, "w", encoding="utf-8") as f:
            json.dump({"taken_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "note_files": GUARDED, "snapshot": snap}, f, indent=1)
        print("wrote", PRE)
        return
    scratch = os.path.abspath(args.scratch)
    assert not scratch.startswith(os.path.abspath(CACHE)), "scratch must not be inside analysis/cache"
    os.makedirs(scratch, exist_ok=True)
    t_start = time.perf_counter()
    before = snapshot()
    assert not before["_h_caches_present"], before["_h_caches_present"]
    prev_e = {c: (sha256(os.path.join(CACHE, f"{c}_E.parquet")) if os.path.exists(os.path.join(CACHE, f"{c}_E.parquet")) else None)
              for c in CORPORA}  # an earlier E build, if any: determinism check
    runs = {c: run_loader(c, scratch) for c in CORPORA}
    after = snapshot()
    report = {"probe": "analysis/probes/phase_e_cache_build.py", "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "split_source": {c: f"analysis/cache/samples/{c}_EH.json#E" for c in CORPORA},
              "corpora_without_E": {"cc_local": "no E split (all sessions used by A+B)", "aiv_cc": "no E split",
                                    "whowhen": "no E split"},
              "runs": runs, "corpora": {}}
    for c in CORPORA:
        ids = e_ids(c)
        r = read_back(c, ids)
        r["sha256_previous_E_build"] = prev_e[c]
        r["identical_to_previous_E_build"] = None if prev_e[c] is None else prev_e[c] == r["sha256"]
        r["loader_wall_s"] = runs[c]["wall_s"]
        with open(LOADER_REPORT[c], encoding="utf-8") as f:
            lr = json.load(f)
        r["loader_report"] = {"path": os.path.relpath(LOADER_REPORT[c], ROOT).replace("\\", "/"), "sha256": sha256(LOADER_REPORT[c])}
        r["loader_report_cache_info"] = lr.get("cache")
        for sp in ("A", "B"):
            r[f"{sp}_rederived_vs_{sp}_cache"] = compare_rederived(c, sp, scratch)
        report["corpora"][c] = r
    # swechat link resolution (LINK RULE), A / B / E measured the same way
    sw = report["corpora"]["swechat"]
    with open(LOADER_REPORT["swechat"], encoding="utf-8") as f:
        lr = json.load(f)
    allowed = set().union(*ab_ids("swechat")) | set(e_ids("swechat"))
    pop = pd.read_parquet(os.path.join(CACHE, "swechat_population.parquet"), columns=["session_id", "format"],
                          filters=[("session_id", "in", sorted(allowed))])
    fmt = dict(zip(pop.session_id, pop.format))
    with open(os.path.join(AN, "out", "build", "swechat_build.json"), encoding="utf-8") as f:
        full_links = json.load(f)["full_population_pass"]["cross_session_links"]
    ctx_e = lr.get("ctx") or {}
    lost = {k: int(full_links[k]) - int(ctx_e.get(k, 0)) for k in ("opencode_child_to_task_call", "codex_thread_to_spawn_call")}
    b_lost = sw["B_rederived_vs_B_cache"].get("sessions_differing_only_in_parent_call_id", 0) if sw["B_rederived_vs_B_cache"]["identical"] is False else 0
    a_lost = sw["A_rederived_vs_A_cache"].get("sessions_differing_only_in_parent_call_id", 0) if sw["A_rederived_vs_A_cache"]["identical"] is False else 0
    sw["session_level_subagent_link_resolution"] = {
        "rule": "LINK RULE in the probe docstring",
        "ctx_source_E_build": ctx_e,
        "ctx_full_population_A_B_build": {"source": "analysis/out/build/swechat_build.json full_population_pass.cross_session_links",
                                          **full_links},
        "child_links_only_in_transcripts_outside_A_B_E": lost,
        "of_which_land_on_A_sessions": a_lost, "of_which_land_on_B_sessions": b_lost,
        "upper_bound_E_sessions_missing_a_link_vs_full_population_ctx": sum(lost.values()) - a_lost - b_lost,
        "bound_note": "each lost child link targets one child id: an A, B, E or H session or a thread with no transcript; "
                      "A and B effects are measured by the re-derivations, so the rest bounds E from above",
        "A_cache_full_population_ctx": link_resolution(os.path.join(CACHE, "swechat_A.parquet"), fmt),
        "B_cache_full_population_ctx": link_resolution(os.path.join(CACHE, "swechat_B.parquet"), fmt),
        "E_cache_A_B_E_ctx": link_resolution(os.path.join(CACHE, "swechat_E.parquet"), fmt),
    }
    if "aiv_cu" in report["corpora"]:
        with open(LOADER_REPORT["aiv_cu"], encoding="utf-8") as f:
            la = json.load(f)
        report["corpora"]["aiv_cu"]["loader_checks"] = {k: la.get("split_E", {}).get(k) for k in
                                                        ("call_events_vs_pass1_index", "anthropic_sdk_raw_check")}
        report["corpora"]["aiv_cu"]["pass2_scan"] = la.get("pass2")
    # hash checks
    pre = None
    if os.path.exists(PRE):
        with open(PRE, encoding="utf-8") as f:
            pre = json.load(f)["snapshot"]
    checks = {}
    for rel in GUARDED:
        b, a = before[rel], after[rel]
        row = {"sha256_before": b.get("sha256"), "sha256_after": a.get("sha256"), "bytes": a.get("bytes"),
               "unchanged_during_build": b == a}
        if pre is not None:
            row["sha256_pre_edit_snapshot"] = pre.get(rel, {}).get("sha256")
            row["unchanged_since_pre_edit_snapshot"] = pre.get(rel) == a
        checks[rel] = row
    report["guarded_file_checks"] = checks
    report["A_B_cache_hash_checks_all_pass"] = all(checks[r]["unchanged_during_build"] and
                                                   checks[r].get("unchanged_since_pre_edit_snapshot", True) for r in REQUIRED_AB)
    report["all_guarded_files_unchanged"] = all(v["unchanged_during_build"] and v.get("unchanged_since_pre_edit_snapshot", True)
                                                for v in checks.values())
    report["pre_edit_snapshot"] = {"path": os.path.relpath(PRE, ROOT).replace("\\", "/") if pre else None}
    report["h_caches_present_before"] = before["_h_caches_present"]
    report["h_caches_present_after"] = after["_h_caches_present"]
    report["runtime_s_total"] = round(time.perf_counter() - t_start, 1)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, default=lambda o: int(o) if isinstance(o, np.integer) else str(o))
    print("wrote", OUT, "A/B hash checks pass:", report["A_B_cache_hash_checks_all_pass"])


if __name__ == "__main__":
    main()
