"""pub_codex loader: public native Codex CLI rollouts (data/acquired/cli-codex-hf, 6 pinned HF repos) -> common event IR.

Run from the worktree root:
  PYTHONIOENCODING=utf-8 python -m analysis.loaders.load_pub_codex            census + splits + A cache + A calibration
  PYTHONIOENCODING=utf-8 python -m analysis.loaders.load_pub_codex --split B  (NEXT step only) build pub_codex_B.parquet
  PYTHONIOENCODING=utf-8 python -m analysis.loaders.load_pub_codex --split E  (NEXT step only) build pub_codex_E.parquet
  PYTHONIOENCODING=utf-8 python -m analysis.loaders.load_pub_codex --selftest  rebuild A through the --split code path
                                                                               into scratch and compare with the A cache
main() is idempotent: same inputs -> same population, splits, A cache, calibration (timestamps in the extension
record and runtimes aside).

SOURCE
  data/acquired/cli-codex-hf/<owner>__<repo>@<sha8>/**/rollout-<date>-<uuid>.jsonl (46 files, read-only, bytes as
  pinned). README.md and _b5e_manifest.json are skipped. Licences per repo: CC BY 4.0 / MIT (CORPUS_INVENTORY 2.1).

FIELD AUDIT AND POPULATION (header-only census; no event is parsed before the split)
  For every rollout file only the FIRST line is decoded (the session_meta record) and the non-empty lines are counted.
  A file passes the audit when its first record is type 'session_meta' with a payload.id; the Codex rollout format
  carries per-record ISO ms timestamps and a call_id join (B5e field audit, CORPUS_INVENTORY 5.12).
  session_id = session_meta.payload.id (a UUIDv7). Duplicate ids: the longer file is kept (none found at this revision).
  stratum = session_meta.payload.originator ('Codex Desktop' | 'codex_vscode' | ...): the client harness, the closest
  analogue of swechat's scaffold label. length = non-empty line count (as swechat JSONL formats).
  The uploader folder (one folder = one uploader) and forked_from_id are kept in the population table
  (analysis/cache/pub_codex_population.parquet, metadata only) for dominance checks.

EVENT MAPPING
  analysis.loaders.load_swechat.parse_codex, imported and called unchanged (its docstring is the mapping: response_item
  message/function_call/custom_tool_call/*_output, exec_command_end joins, unified-exec deferral, token_count usage with
  synthetic api_msg_id, turn_context model + approval_policy meta, compacted -> system). Then load_swechat.ensure_usage_ids.
  Local post-processing only:
    corpus column = 'pub_codex'; seq re-numbered 0..n-1 in parser order (identical to the parser's own seq).
    Credential-like substrings in text/args/command/stderr/extra are replaced by '[REDACTED:loader:<type>]'
    (newcorp_common.redact; counts by type and column in the build report; values never printed).
    Codex logs no provider request id or response id: request_id stays None, api_msg_id is synthetic (token_count).
  Cross-session subagent links (load_swechat._child_links reads the PARENT's text) are not resolved: that would open
  sessions outside the split being built. A sub-agent rollout keeps is_subagent=True and agent_id, parent_call_id=None.
  Forked rollouts (session_meta.forked_from_id): Codex copies the parent's history into the fork. The copied records
  are emitted as they appear (no dedupe); the session_meta meta event carries forked_from_id in extra, and the build
  report counts records in forks whose timestamp precedes the fork's own session_meta timestamp.

CALIBRATION
  prereg_e_calibration.calibrate_unit(corpus='pub_codex', unit='swechat/codex', A frame): same parser, so the
  pre-registered swechat/codex rules (tool keys keep Codex raw shell names, exit-header error class, approval_policy ==
  'never' qualification, token_count response table) apply unchanged.
"""
import argparse
import collections
import glob
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd

from analysis.loaders import load_swechat as sw
from analysis.loaders import newcorp_common as nc

CORPUS = "pub_codex"
UNIT_AS = "swechat/codex"
SRC = nc.DATA / "cli-codex-hf"
LOADER = "analysis/loaders/load_pub_codex.py"


def census():
    rows, fails = [], collections.Counter()
    for f in sorted(glob.glob(str(SRC / "**" / "*.jsonl"), recursive=True)):
        if "/.cache/" in f.replace("\\", "/"):
            continue
        with open(f, "rb") as fh:
            first = fh.readline()
            n = (1 if first.strip() else 0) + sum(1 for line in fh if line.strip())
        try:
            d = json.loads(first)
        except ValueError:
            fails["first_line_not_json"] += 1
            continue
        p = d.get("payload") if isinstance(d, dict) and isinstance(d.get("payload"), dict) else {}
        if d.get("type") != "session_meta" or not p.get("id"):
            fails["first_record_not_session_meta_with_id"] += 1
            continue
        rel = Path(f).relative_to(nc.DATA).as_posix()
        src = p.get("source")
        rows.append({"session_id": str(p["id"]), "stratum": str(p.get("originator") or "unknown"), "length": n,
                     "source": rel, "uploader": rel.split("/")[1].split("@")[0], "bytes": os.path.getsize(f),
                     "forked_from_id": p.get("forked_from_id"), "cli_version": p.get("cli_version"),
                     "model_provider": p.get("model_provider"),
                     "meta_source": src if isinstance(src, str) else json.dumps(src)[:80],
                     "subagent": isinstance(src, dict) and "subagent" in src})
    pop = pd.DataFrame(rows)
    dup = int(pop.session_id.duplicated().sum())
    pop = pop.sort_values(["session_id", "length"], ascending=[True, False]).drop_duplicates("session_id")
    return pop.reset_index(drop=True), {"files_seen": len(rows) + sum(fails.values()), "fail_reasons": dict(fails),
                                        "duplicate_session_ids_dropped": dup}


def parse_one(row, red):
    stat = sw._new_stat()
    path = nc.DATA / row["source"]
    text, replaced = sw.read_text(str(path))
    events = sw.parse_codex(row["session_id"], row["stratum"], text, stat, {})
    sw.ensure_usage_ids(events, "codex", row["session_id"], stat)
    if isinstance(row.get("forked_from_id"), str):
        for e in events:
            if e["kind"] == "meta" and e["extra"] and '"entry_type":"session_meta"' in e["extra"]:
                ex = json.loads(e["extra"])
                ex["forked_from_id"] = row["forked_from_id"]
                e["extra"] = sw.ir.j(ex)
                break
    nc.redact_events(events, red)
    stat["utf8_replaced"] = int(replaced)
    return events, stat


def build_split(split, out_path=None):
    """Parse the sessions of one split (A, B or E; never H) into an IR cache. Used for A by main() and for B/E by
    --split in the next step."""
    ids = nc.split_ids(CORPUS, split)
    pop = pd.read_parquet(nc.CACHE / f"{CORPUS}_population.parquet")
    pop = pop.set_index("session_id")
    red, stats, frames, nsur, fork_pre = collections.Counter(), collections.Counter(), [], 0, 0
    for sid in sorted(ids):
        row = dict(pop.loc[sid])
        row["session_id"] = sid
        events, stat = parse_one(row, red)
        for k, v in stat.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                stats[k] += v
        if isinstance(row.get("forked_from_id"), str):
            sm = next((e["ts"] for e in events if e["ts"]), None)
            fork_pre += sum(1 for e in events if e["ts"] and sm and e["ts"] < sm)
        df, ns = nc.session_frame(events, CORPUS)
        nsur += ns
        frames.append(df)
    out_path = out_path or (nc.CACHE / f"{CORPUS}_{split}.parquet")
    info = nc.write_cache(frames, out_path)
    info.update({"split": split, "sessions_in_split": len(ids), "parser_stats": dict(stats),
                 "secret_redactions": dict(red), "surrogate_cells_replaced": nsur,
                 "fork_records_before_fork_meta_ts": fork_pre})
    return info


def selftest():
    """Unit test of the --split code path on A only: rebuild A into scratch, compare with the A cache."""
    scratch = Path(os.environ.get("NEWCORP_SCRATCH", tempfile.gettempdir()))
    p = scratch / f"_selftest_{CORPUS}_A.parquet"
    build_split("A", out_path=p)
    a = pd.read_parquet(nc.CACHE / f"{CORPUS}_A.parquet")
    b = pd.read_parquet(p)
    same = a.equals(b)
    os.remove(p)
    try:
        nc.split_ids(CORPUS, "H")
        refused = False
    except AssertionError:
        refused = True
    return {"A_rebuild_identical": bool(same), "H_refused": refused}


def main():
    t0 = time.time()
    pop, audit = census()
    pop.to_parquet(nc.CACHE / f"{CORPUS}_population.parquet", index=False)
    sp = nc.split_population(pop[["session_id", "stratum", "length"]])
    sinfo = nc.write_splits(CORPUS, sp, LOADER)
    idx = nc.write_index(CORPUS, sp, pop)
    a_info = build_split("A")
    a = pd.read_parquet(nc.CACHE / f"{CORPUS}_A.parquet")
    rep = nc.cache_report(a)
    # Codex-specific fill: wall time / exit header inside the output text wrapper, approval policy
    res = a[a.kind == "result"]
    txt = res.text.astype(object)
    rep["codex_text_wrappers"] = {
        "results_with_wall_time_line": int(txt.map(lambda t: isinstance(t, str) and "Wall time:" in t[:400]).sum()),
        "results_with_exit_header": int(txt.map(lambda t: isinstance(t, str) and (
            "Process exited with code" in t[:400] or "Exit code:" in t[:400])).sum())}
    pol = collections.Counter()
    for e in a[(a.kind == "meta") & a.extra.notna()].extra.astype(str):
        if '"approval_policy"' in e:
            pol[str(json.loads(e).get("approval_policy"))] += 1
    rep["turn_context_approval_policy"] = dict(pol)
    rep["uploader_dominance_A"] = nc.cluster_dominance(a, dict(zip(pop.session_id, pop.uploader)))
    doc, ext = nc.calibrate(CORPUS, [(CORPUS, UNIT_AS, None)], LOADER, sinfo)
    r = doc["units"][CORPUS]["resolved"]
    st = selftest()
    out = {"corpus": CORPUS, "loader": LOADER, "source": "data/acquired/cli-codex-hf",
           "population": {"N": int(len(pop)), "by_stratum": pop.stratum.value_counts().to_dict(),
                          "by_uploader": pop.uploader.value_counts().to_dict(),
                          "forked_sessions": int(pop.forked_from_id.notna().sum()),
                          "subagent_sessions": int(pop.subagent.sum()),
                          "cli_versions": pop.cli_version.value_counts().to_dict(),
                          "length_lines": {"min": int(pop.length.min()), "median": float(pop.length.median()),
                                           "max": int(pop.length.max())}},
           "field_audit": {**audit, "passed": int(len(pop)),
                           "rule": "first record is session_meta with payload.id (header-only census)"},
           "splits": {**nc.split_sizes_by_stratum(sp), "floor_used": sp["floor_used"], "files": sinfo, "index": idx},
           "A_cache": a_info, "A_report": rep,
           "calibration": {"file": f"analysis/out/phase_e/prereg_e_calibration_{CORPUS}.json",
                           "calibrated_as_unit": UNIT_AS, "extension": f"analysis/out/phase_e/prereg_e_extensions/{CORPUS}.json",
                           "resolved": r},
           "selftest_split_code_path": st,
           "provider_request_id": "absent: Codex rollouts log no provider request id or response id (token_count only)",
           "runtime_s": round(time.time() - t0, 1)}
    (nc.OUT_E / f"newcorp_build_{CORPUS}.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps({"N": out["population"]["N"], "A": len(sp["A"]), "B": len(sp["B"]), "E": len(sp["E"]),
                      "H": len(sp["H"]), "A_rows": a_info["rows"], "selftest": st, "runtime_s": out["runtime_s"]}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["B", "E"])
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.split:
        info = build_split(a.split)
        (nc.OUT_E / f"newcorp_build_{CORPUS}_{a.split}.json").write_text(json.dumps(info, indent=1, default=str),
                                                                         encoding="utf-8")
        print(json.dumps({k: info[k] for k in ("rows", "sessions")}))
    elif a.selftest:
        print(json.dumps(selftest()))
    else:
        main()
