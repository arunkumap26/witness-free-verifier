"""Loader: AI Village claude_code_messages (Claude Agent SDK stream) -> IR caches for corpus `aiv_cc`.

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.loaders.load_aiv_cc
Writes (idempotent, rebuilt from scratch every run):
  analysis/cache/samples/aiv_cc.json, analysis/cache/aiv_cc_A.parquet, analysis/cache/aiv_cc_B.parquet,
  analysis/out/build/aiv_cc_build.json

SOURCE
  data/ai-village/claude_code_messages.jsonl.gz: one DB row per SDK message. Columns: id (random uuid; the file is
  ordered by it, so file order carries no time information), agent_id, sdk_session_id, message_type,
  message_subtype, message_uuid (undocumented; null on every row), content (one Claude Agent SDK entry, no
  `timestamp`), created_at (DB row-insert time, UTC, microseconds with trailing zeros stripped, no tz suffix).

SESSION UNIT (deviation from the task text; see SESSION_UNIT)
  The task said session = sdk_session_id (~303). The data has 53 distinct sdk_session_id values and one of them
  holds 244,709 of 244,820 rows: the agent resumed the same SDK session 260 times. The ~303 figure is the row count
  of claude_code_sessions (one row per SDK invocation). So the default unit is the RUN: the rows of one
  sdk_session_id between consecutive system/init rows, in created_at order (every invocation starts with exactly
  one init row). session_id = "<sdk_session_id>/r<NNN>" (NNN = 0-based run index within the sdk session), so the
  SDK session stays recoverable by splitting on '/'. Rows before the first init of an sdk session (none in the
  current data) would form "<sdk_session_id>/pre". SESSION_UNIT = "sdk_session" reproduces the literal task rule.
  Runs of one sdk session are resumes of one continuing conversation by one agent (the whole table is one agent),
  so runs are disjoint in events but not independent in content.
  stratum = calendar month (YYYY-MM, UTC) of the session's first created_at. length = rows in the session.

ORDERING
  Rows are grouped by sdk_session_id and sorted by (created_at as a microsecond timestamp, init-first rank, row id).
  Ties (identical created_at within an sdk session) are counted in the build report; the rank puts an init row first
  in a tie so it opens the new run, and the random row id makes any remaining tie order deterministic but carries no
  meaning. seq is the Parser's emission order over the sorted rows (one event per content block).

ENTRY -> IR MAPPING
  Each row's content is fed to analysis.lib.cc_jsonl.Parser(corpus, session_id, stratum, ts_kind='row_insert') with
  ts = created_at (normalized by ir.iso to ISO-8601 'Z', all source fractional digits kept):
    assistant (one block per row) -> assistant (text) / call (tool_use); thinking -> extra.thinking_chars
    user with tool_result blocks  -> result; snake_case tool_use_result timers/stderr -> extra/stderr;
                                     tool_result.is_error -> native_error (null when the key is absent)
    user text                     -> user, or system when isSynthetic (compaction summaries) or harness-prefixed
    system (init/status/compact_boundary) -> meta, extra {entry_type:'system', subtype, status, compact_metadata}
    result (success/error_during_execution) -> meta, extra {entry_type:'result', subtype, is_error, num_turns,
                                     duration_ms, duration_api_ms, total_cost_usd, stop_reason}
  Loader additions on top of the Parser (extra only): init rows add {model, claude_code_version, permissionMode,
  n_tools}; assistant rows with an SDK `error` field add {sdk_error}; every row's message_type/message_subtype is
  checked against content.type/subtype (mismatches counted).
  parent_tool_use_id (subagent traffic): when non-null the entry gets _nested=True and _parent_call_id, so
  is_subagent=True and parent_call_id is set. It is null on every row in the current data.
"""
import gzip
import json
import os
from collections import Counter, defaultdict

import pandas as pd

from analysis.lib import cc_jsonl, ir, sample
from analysis.loaders.cc_build_stats import build_stats

CORPUS = "aiv_cc"
D = os.path.join(os.environ.get("SWARMS_DATA", "C:/Swarms/data"), "ai-village")
SRC = os.path.join(D, "claude_code_messages.jsonl.gz")
ANALYSIS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ANALYSIS, "cache")
OUT = os.path.join(ANALYSIS, "out", "build")
SESSION_UNIT = "run"   # "run" (default) | "sdk_session" (literal task rule; one session would hold 99.95% of rows)


def _is_init(r):
    return r["message_type"] == "system" and r.get("message_subtype") == "init"


def _sort_key(r):
    return (ir.parse_ts(ir.iso(r["created_at"])), 0 if _is_init(r) else 1, r["id"])


def _add_extra(ev, d):
    ex = json.loads(ev["extra"]) if ev.get("extra") else {}
    ex.update(d)
    ev["extra"] = ir.j(ex)


def load_rows():
    with gzip.open(SRC, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def segment(rows, C):
    """sdk_session_id groups -> ordered list of (session_id, [rows])."""
    by = defaultdict(list)
    for r in rows:
        by[r["sdk_session_id"]].append(r)
    out = []
    for sdk in sorted(by):
        lst = sorted(by[sdk], key=_sort_key)
        ts = Counter(r["created_at"] for r in lst)
        C["sdk_session_tie_groups"] += sum(1 for v in ts.values() if v > 1)
        C["sdk_session_rows_in_ties"] += sum(v for v in ts.values() if v > 1)
        C["sdk_session_tie_groups_with_init"] += sum(1 for r in lst if _is_init(r) and ts[r["created_at"]] > 1)
        if SESSION_UNIT == "sdk_session":
            out.append((sdk, lst))
            continue
        cur, k = None, -1
        for r in lst:
            if _is_init(r):
                k += 1
                cur = []
                out.append((f"{sdk}/r{k:03d}", cur))
            elif cur is None:
                cur = []
                out.append((f"{sdk}/pre", cur))
                C["rows_before_first_init"] += 1
            cur.append(r)
    return out


def raw_scan(rows):
    """Recon-equivalent counts (method of recon/recon_ai_village.py: dicts keyed by block id) plus block counts."""
    calls, results = {}, {}
    nb_use = nb_res = 0
    for r in rows:
        c = r["content"] if isinstance(r["content"], dict) else {}
        msg = c.get("message") if isinstance(c.get("message"), dict) else {}
        for b in msg.get("content") if isinstance(msg.get("content"), list) else []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                nb_use += 1
                calls[b.get("id")] = r["created_at"]
            elif b.get("type") == "tool_result":
                nb_res += 1
                results[b.get("tool_use_id")] = r["created_at"]
    return {"rows": len(rows), "tool_use_blocks": nb_use, "tool_result_blocks": nb_res, "tool_use": len(calls),
            "tool_result": len(results), "results_without_call": len(set(results) - set(calls)),
            "calls_without_result": len(set(calls) - set(results))}


def parse_session(sid, stratum, lst, C):
    p = cc_jsonl.Parser(CORPUS, sid, stratum, ts_kind="row_insert")
    for r in lst:
        c = r["content"]
        if not isinstance(c, dict):
            C["non_object_content"] += 1
            continue
        if c.get("type") != r["message_type"]:
            C["message_type_mismatch"] += 1
        if c.get("subtype") is not None and c.get("subtype") != r.get("message_subtype"):
            C["message_subtype_mismatch"] += 1
        if c.get("parent_tool_use_id"):
            c = dict(c, _nested=True, _parent_call_id=c["parent_tool_use_id"])
            C["rows_with_parent_tool_use_id"] += 1
        before = len(p.events)
        p.feed(c, ts=r["created_at"])
        new = p.events[before:]
        C[f"events_from:{r['message_type']}:{r.get('message_subtype')}"] += len(new)
        if not new:
            C[f"rows_without_event:{r['message_type']}:{r.get('message_subtype')}"] += 1
        if _is_init(r):
            for ev in new:
                _add_extra(ev, {"model": c.get("model"), "claude_code_version": c.get("claude_code_version"),
                                "permissionMode": c.get("permissionMode"),
                                "n_tools": len(c["tools"]) if isinstance(c.get("tools"), list) else None})
        if isinstance(c.get("error"), str):
            for ev in new:
                _add_extra(ev, {"sdk_error": c["error"]})
            C["assistant_rows_with_sdk_error"] += 1
            C[f"sdk_error_value:{c['error'][:40]}"] += 1
    return p.events


def main():
    os.makedirs(os.path.join(CACHE, "samples"), exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    rows = load_rows()
    C = Counter()
    raw = raw_scan(rows)
    sessions = segment(rows, C)
    by_sid, pop = {}, []
    for sid, lst in sessions:
        stratum = lst[0]["created_at"][:7]
        by_sid[sid] = parse_session(sid, stratum, lst, C)
        pop.append({"session_id": sid, "stratum": stratum, "length": len(lst)})
    pop = pd.DataFrame(pop)
    smp = sample.draw(pop, CORPUS)
    smp["session_unit"] = SESSION_UNIT
    sample.save(smp, os.path.join(CACHE, "samples", f"{CORPUS}.json"))
    frames, report_splits = {}, {}
    for split in ("A", "B"):
        df = ir.to_frame([ev for sid in smp[split] for ev in by_sid[sid]])
        basic = ir.validate(df)
        df.to_parquet(os.path.join(CACHE, f"{CORPUS}_{split}.parquet"), index=False)
        frames[split] = df
        report_splits[split] = {"sessions_in_sample": len(smp[split]),
                                "sessions_with_zero_events": sum(1 for sid in smp[split] if not by_sid[sid]),
                                "validate": {k: int(v) for k, v in basic.items()}, **build_stats(df)}
    full = ir.to_frame([ev for sid, _ in sessions for ev in by_sid[sid]])
    # within-session ties on the IR ts (identical created_at inside one session)
    sdk_ids = Counter(r["sdk_session_id"] for r in rows)
    tab = []
    try:
        with gzip.open(os.path.join(D, "claude_code_sessions.jsonl.gz"), "rt", encoding="utf-8") as fh:
            tab = [json.loads(x) for x in fh]
    except OSError:
        pass
    in_sample = set(smp["A"]) | set(smp["B"])
    report = {
        "corpus": CORPUS,
        "session_unit": SESSION_UNIT,
        "sdk_sessions": {"distinct_sdk_session_id": len(sdk_ids),
                         "rows_per_sdk_session": {k: float(v) for k, v in pd.Series(list(sdk_ids.values())).describe().items()},
                         "largest_sdk_session_rows": max(sdk_ids.values()),
                         "largest_sdk_session_share": max(sdk_ids.values()) / len(rows),
                         "init_rows": sum(1 for r in rows if _is_init(r)),
                         "result_rows": sum(1 for r in rows if r["message_type"] == "result"),
                         "claude_code_sessions_table_rows": len(tab),
                         "claude_code_sessions_table_distinct_sdk_session_id": len({t.get("sdk_session_id") for t in tab}),
                         "distinct_content_session_id": len({(r["content"] or {}).get("session_id") for r in rows}),
                         "rows_content_session_id_differs": sum(1 for r in rows if (r["content"] or {}).get("session_id") != r["sdk_session_id"]),
                         "message_uuid_null_rows": sum(1 for r in rows if r.get("message_uuid") is None)},
        "population": {"sessions": len(sessions), "sessions_by_stratum": dict(Counter(pop.stratum).most_common()),
                       "sessions_in_A_or_B": len(in_sample), "sessions_not_sampled": len(sessions) - len(in_sample),
                       "length_rows": {k: float(v) for k, v in pop.length.describe().items()},
                       "results_rows_per_session": dict(Counter(sum(1 for r in lst if r["message_type"] == "result")
                                                                for _, lst in sessions).most_common())},
        "recon_reproduction": {"recon_file": "analysis/out/recon/ai_village.txt",
                               "expected": {"rows": 244820, "tool_use": 72225, "tool_result": 72213,
                                            "results_without_call": 0, "calls_without_result": 12},
                               "raw_scan": raw},
        "ordering": {"tie_rule": "(created_at, init first, row id)", **{k: v for k, v in C.items() if k.startswith("sdk_session_")}},
        "loader_counters": dict(sorted((k, v) for k, v in C.items() if not k.startswith("sdk_session_"))),
        "full_corpus_ir": build_stats(full),
        "splits": report_splits,
        "cache_rows": {k: int(len(v)) for k, v in frames.items()},
    }
    with open(os.path.join(OUT, f"{CORPUS}_build.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, default=str)
    print(json.dumps({"sessions": len(sessions), "A": len(smp["A"]), "B": len(smp["B"]), "rows": report["cache_rows"],
                      "raw": raw, "ordering": report["ordering"]}, indent=1))


if __name__ == "__main__":
    main()
