"""Phase C lens: SWE-chat session- and checkpoint-level tallies as a second, harness-side bookkeeping of the same sessions.

Writes RAW COUNTS ONLY to analysis/out/phase_c/swechat_tables.json (interpretation lives in analysis/notes/swechat_tables.md).

Stages (each writes a file; later stages read earlier outputs):
  tx      stream every raw transcript under data/swe-chat-pinned/transcripts (multiprocessing, one file per task) and
          recompute the harness token / API-call tallies, timestamps, tool calls and edited paths
          -> $SWECHAT_TABLES_TMP/swechat_tables_tx.parquet (default: system temp dir; one row per session)
  conv    stream conversations.parquet (row-group batches, narrow columns) and aggregate per session
          -> $SWECHAT_TABLES_TMP/swechat_tables_conv.parquet
  report  read sessions / checkpoints / session_logs / commits (numeric columns) + the two stage files -> JSON

This lens reads raw SWE-chat tables directly (not the IR cache) because the session/checkpoint tables are not in the IR.
Every threshold and tolerance is declared in PREREG below, before any outcome is computed, with its reason.

Run from the worktree root:  PYTHONIOENCODING=utf-8 python -m analysis.probes.phase_c_swechat_tables [--stage all|tx|conv|report]
"""
import argparse
import json
import math
import os
import re
import sys
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime
from multiprocessing import Pool

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from analysis.lib import stats

ROOT = os.environ.get("SWARMS_DATA", "C:/Swarms/data")
D = f"{ROOT}/swe-chat-pinned"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.normpath(os.path.join(HERE, "..", "out", "phase_c"))
OUT_JSON = os.path.join(OUT_DIR, "swechat_tables.json")
# stage intermediates (per-session recounts, some carrying file paths) are regenerated in seconds and kept OUT of analysis/out
INTER_DIR = os.environ.get("SWECHAT_TABLES_TMP", os.path.join(tempfile.gettempdir(), "phase_c_swechat_tables"))
TX_PARQUET = os.path.join(INTER_DIR, "swechat_tables_tx.parquet")
CONV_PARQUET = os.path.join(INTER_DIR, "swechat_tables_conv.parquet")

# ---------------------------------------------------------------------------------------------------------------------
# Pre-registration. Written before computing any outcome over the full corpus. Formulas F0/X0/O0 were read off ONE
# calibration session each (named below); every other session is out-of-calibration.
# ---------------------------------------------------------------------------------------------------------------------
PREREG = {
    "calibration_sessions": {
        "claude_code_format": "b3342ff7-4bc3-4c55-b570-ff9cc1373790",
        "codex_format": "019d3d40-1cf6-7771-90cd-7b972aaa8f17",
        "opencode_format": "ses_360fbcdadffelFMCArPrxrETEL",
        "gemini_format": "2467a967-8bb3-4074-bc5e-fb1c5c147557",
        "duration_and_builder_columns": "b3342ff7-4bc3-4c55-b570-ff9cc1373790",
    },
    "token_formulas": {
        "F0": "Claude-Code-format JSONL: top-level records with type=='assistant'; distinct message.id in first-occurrence order; "
              "usage of the LAST record carrying that id; api_call_count = number of distinct ids; "
              "tokens (input, cache_creation_input, cache_read_input, output) summed over ids. Primary.",
        "F1": "F0 but excluding records with isSidechain==true.",
        "F2": "F0 plus distinct assistant message ids embedded in progress records (data.message.message), last usage; full-match only.",
        "F3": "F0 but FIRST-occurrence usage per id.",
        "F4": "F0 but excluding ids whose model == '<synthetic>'.",
        "X0": "Codex JSONL: event_msg/token_count events with non-null info, in order; the k-th event's info.total_token_usage gives "
              "input=input_tokens, cache_read=cached_input_tokens, output=output_tokens+reasoning_output_tokens, cache_creation=0, api=k.",
        "X1": "X0 but output=output_tokens only.",
        "X2": "X0 but cumulative sums of info.last_token_usage instead of total_token_usage.",
        "O0": "OpenCode JSON: assistant messages in order; tokens.input, tokens.cache.write->cache_creation, tokens.cache.read, "
              "tokens.output; api = number of assistant messages.",
        "O1": "O0 but output = tokens.output + tokens.reasoning.",
        "G0": "Gemini CLI JSON: messages with type=='gemini' in order; tokens.input, cache_creation=0, tokens.cached->cache_read, "
              "tokens.output; api = number of gemini messages. Added after the first tx pass showed 59 transcripts in this format "
              "(calibrated on gemini_format session below before the full rerun).",
        "G1": "G0 but output = tokens.output + tokens.thoughts.",
    },
    "format_detection": "JSONL whose first non-empty line parses as an object: majority vote over first 50 records "
                        "(codex record types; claude record types or parentUuid/sessionId keys; dotted type = copilot; role+message = cursor). "
                        "Otherwise the whole file is parsed as one JSON document (OpenCode: info+messages; Gemini: sessionId+messages). "
                        "Revision log: first pass read a 64 KiB head to find the first line (mis-sniffed 6 files whose first record is "
                        "longer) and recognised only the 7 listed claude record types (missed 30 newer Claude Code files starting with "
                        "permission-mode/attachment records); both fixed before any outcome in this JSON was computed.",
    "match_classes": {
        "full": "metadata (api, input, cache_creation, cache_read, output) equals the tally over the whole stored transcript, all 5 exactly",
        "prefix": "equals the tally over the first api_call_count messages (stored transcript continued after the snapshot)",
        "window": "equals the tally over some contiguous run of api_call_count messages (any start)",
        "none": "no exact 5-field match under full/prefix/window",
        "reason": "tallies are integer bookkeeping of the same records; a deterministic recount should agree exactly, so tolerance is 0. "
                  "Prefix/window classes exist because a session's metadata is the snapshot at its canonical checkpoint, which can be "
                  "earlier than the stored transcript or computed from a checkpoint start offset.",
    },
    "tolerances": {
        "integer_tallies": "exact (0). Near band reported separately: |diff| <= 1% of max(|a|,|b|).",
        "duration_seconds_vs_timestamps": "exact if |diff| <= 0.001 s (timestamps are ms resolution); near if <= 1 s.",
        "agent_percentage_identity": "|agent_percentage - 100*agent_lines/total_committed| <= 1e-6",
        "files_touched_path_match": "a repo-relative path f matches a tool path p if p == f or p ends with '/' + f (after '\\\\'->'/')",
        "context_md_prompt_count": "number of lines matching ^### Prompt \\d+ in context_md, only when the line '## User Prompts' is present",
    },
    "distribution": {
        "round_numbers": "among values >= 100: share divisible by 10/100/1000 vs 1/k; reported raw with Wilson CI",
        "spike_rule": "integer column, value v >= 10 with count c(v) >= 10 and c(v) >= 5 x mean count per integer over "
                      "[floor(v/1.25), ceil(v*1.25)] excluding v. Reason: a smooth density gives ~equal counts to neighbouring integers.",
        "bimodality": "Sarle's bimodality coefficient on log1p(x) for x>=0 columns; 0.555 is the uniform-distribution value (literature).",
    },
    "correlations": {
        "method": "Spearman on complete cases, Claude Code sessions; bootstrap over sessions (1000) for 95% CI",
        "partial": "residualize each rank vector on rank(n_records of raw transcript) by OLS, then Pearson of residuals",
        "declared_groups": None,  # filled below (same-group pairs are declared mechanically linked before computing)
        "top_k": 30,
    },
    "outliers": {
        "robust_z": "(x - median) / (1.4826 * MAD) on log1p(x) for counts/tokens/duration, log for ratios, raw for percentages; "
                    "if MAD == 0 use 1.2533 * mean absolute deviation; if that is 0 the feature is dropped",
        "threshold": 3.5,
        "threshold_reason": "Iglewicz & Hoaglin (1993) modified z-score cut-off",
        "multi_axis": ">= 3 features with |z| > 3.5 (task specification)",
        "population_primary": "Claude Code sessions (agent label) with a Claude-format transcript",
        "population_secondary": "all sessions, z computed within agent label groups with n >= 200, others excluded",
    },
}

FEATURE_GROUPS = {
    "tokens": ["input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens", "api_call_count"],
    "tools": ["tool_call_count", "unique_tools_count", "research_count", "action_count", "first_write_position"],
    "dialogue": ["turn_count", "prompt_count"],
    "time": ["duration_seconds"],
    "files": ["files_touched_count", "checkpoints_count", "n_checkpoint_ids"],
    "attribution": ["agent_lines", "human_added", "human_modified", "human_removed", "total_committed", "agent_percentage"],
    "annotation": ["session_success"],
    "transcript": ["n_records", "n_sub_msgs", "sidechain_msg_share"],
}
PREREG["correlations"]["declared_groups"] = FEATURE_GROUPS

WRITE_TOOLS_CC = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
WRITE_TOOLS_CONV = {"Write", "Edit", "MultiEdit", "NotebookEdit", "mcp__acp__Edit", "mcp__acp__Write", "write_file", "replace",
                    "edit_file", "write", "edit", "apply_patch", "patch", "multiedit"}
PREREG["write_tools_conv"] = sorted(WRITE_TOOLS_CONV)
CLAUDE_TYPES = {"user", "assistant", "progress", "system", "summary", "file-history-snapshot", "queue-operation"}
CODEX_TYPES = {"session_meta", "event_msg", "response_item", "turn_context", "compacted"}

SESSION_NUMERIC = ["files_touched_count", "checkpoints_count", "input_tokens", "output_tokens", "cache_creation_tokens",
                   "cache_read_tokens", "api_call_count", "agent_lines", "human_added", "human_modified", "human_removed",
                   "total_committed", "agent_percentage", "tool_call_count", "unique_tools_count", "research_count",
                   "action_count", "first_write_position", "duration_seconds", "turn_count", "prompt_count", "session_success"]
CHECKPOINT_NUMERIC = ["session_count", "commit_count", "unique_author_count", "checkpoints_count", "files_touched_count",
                      "cp_input_tokens", "cp_output_tokens", "cp_cache_creation_tokens", "cp_cache_read_tokens",
                      "cp_api_call_count", "total_additions", "total_deletions"]
TOK = ["api", "in", "cc", "cr", "out"]
SESS_TOK = {"api": "api_call_count", "in": "input_tokens", "cc": "cache_creation_tokens", "cr": "cache_read_tokens",
            "out": "output_tokens"}


# ---------------------------------------------------------------------------------------------------------------------
# Stage tx: raw transcripts
# ---------------------------------------------------------------------------------------------------------------------
def _i(x):
    try:
        return int(x or 0)
    except (TypeError, ValueError):
        return 0


def _ts(s):
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _match(seq, meta):
    """seq: (n,4) int array (in, cc, cr, out) per message in order. meta: dict api,in,cc,cr,out.
    Returns (cls, start) with cls in full/prefix/window/none, plus 4-field (no output) variant."""
    n = len(seq)
    api = meta["api"]
    tok = np.array([meta["in"], meta["cc"], meta["cr"], meta["out"]], dtype=np.int64)
    cum = np.vstack([np.zeros((1, 4), dtype=np.int64), np.cumsum(seq, axis=0)]) if n else np.zeros((1, 4), dtype=np.int64)
    res = {}
    for label, cols in (("", [0, 1, 2, 3]), ("_noout", [0, 1, 2])):
        cls, start = "none", None
        if api <= n:
            if api == n and np.array_equal(cum[n, cols], tok[cols]):
                cls, start = "full", 0
            elif np.array_equal(cum[api, cols], tok[cols]):
                cls, start = "prefix", 0
            else:
                w = cum[api:, cols] - cum[: n - api + 1, cols]
                hit = np.where((w == tok[cols]).all(axis=1))[0]
                if len(hit):
                    cls, start = "window", int(hit[0])
        res["cls" + label] = cls
        res["start" + label] = start
    full = cum[n]
    for j, k in enumerate(["in", "cc", "cr", "out"]):
        res[f"tx_{k}"] = int(full[j])
    res["tx_api"] = int(n)
    return res


def _path_match(p, files):
    p = p.replace("\\", "/")
    for f in files:
        f2 = f.replace("\\", "/")
        if p == f2 or p.endswith("/" + f2):
            return True
    return False


def _scan_claude(lines_iter, meta, out):
    order, first, last, side, synth, msg_rec, pos = [], {}, {}, {}, {}, [], {}
    last_tools, first_tools = {}, {}
    sub_last = {}
    reqs = set()
    tool_ids, tr_ids = set(), set()
    write_paths = []  # (msg_index, path)
    types = Counter()
    sess_ids, versions, cwds = set(), set(), set()
    ts_min = ts_max = tsm_min = tsm_max = None
    n_rec = n_err = n_side_rec = 0
    start_uuid = meta.get("start_uuid") or None
    uuid_rec = uuid_msg = None
    no_id = 0
    for idx, line in enumerate(lines_iter):
        try:
            d = json.loads(line)
        except ValueError:
            n_err += 1
            continue
        if not isinstance(d, dict):
            n_err += 1
            continue
        n_rec += 1
        t = d.get("type")
        types[t if t in CLAUDE_TYPES else "other"] += 1
        sid = d.get("sessionId")
        if sid:
            sess_ids.add(sid)
        v = d.get("version")
        if v:
            versions.add(v)
        c = d.get("cwd")
        if c:
            cwds.add(c)
        if d.get("isSidechain"):
            n_side_rec += 1
        ts = _ts(d.get("timestamp"))
        if ts is not None:
            ts_min = ts if ts_min is None or ts < ts_min else ts_min
            ts_max = ts if ts_max is None or ts > ts_max else ts_max
            if t in ("user", "assistant"):
                tsm_min = ts if tsm_min is None or ts < tsm_min else tsm_min
                tsm_max = ts if tsm_max is None or ts > tsm_max else tsm_max
        if start_uuid and uuid_rec is None and d.get("uuid") == start_uuid:
            uuid_rec, uuid_msg = n_rec - 1, len(order)
        if t == "assistant":
            m = d.get("message") or {}
            if not isinstance(m, dict):
                continue
            mid = m.get("id")
            if not mid:
                no_id += 1
                mid = f"__noid_{idx}"
            u = m.get("usage") or {}
            tup = (_i(u.get("input_tokens")), _i(u.get("cache_creation_input_tokens")), _i(u.get("cache_read_input_tokens")),
                   _i(u.get("output_tokens")))
            if mid not in first:
                pos[mid] = len(order)
                order.append(mid)
                first[mid] = tup
                side[mid] = bool(d.get("isSidechain"))
                synth[mid] = m.get("model") == "<synthetic>"
                msg_rec.append(n_rec - 1)
            last[mid] = tup
            rq = d.get("requestId")
            if rq:
                reqs.add(rq)
            mi = pos[mid]
            rec_tools = []
            for blk in m.get("content") or []:
                if isinstance(blk, dict) and blk.get("type") == "tool_use":
                    tool_ids.add(blk.get("id"))
                    rec_tools.append(blk.get("id"))
                    if blk.get("name") in WRITE_TOOLS_CC:
                        inp = blk.get("input") or {}
                        p = inp.get("file_path") or inp.get("notebook_path") if isinstance(inp, dict) else None
                        if p:
                            write_paths.append((mi, p))
            last_tools[mid] = rec_tools
            if mid not in first_tools:
                first_tools[mid] = rec_tools
        elif t == "user":
            m = d.get("message") or {}
            cont = m.get("content") if isinstance(m, dict) else None
            if isinstance(cont, list):
                for blk in cont:
                    if isinstance(blk, dict) and blk.get("type") == "tool_result":
                        tr_ids.add(blk.get("tool_use_id"))
        elif t == "progress":
            data = d.get("data")
            if isinstance(data, dict):
                msg = data.get("message")
                if isinstance(msg, dict) and msg.get("type") == "assistant":
                    mm = msg.get("message") or {}
                    if isinstance(mm, dict) and mm.get("id"):
                        u = mm.get("usage") or {}
                        sub_last[mm["id"]] = (_i(u.get("input_tokens")), _i(u.get("cache_creation_input_tokens")),
                                              _i(u.get("cache_read_input_tokens")), _i(u.get("output_tokens")))
    out.update({"n_records": n_rec, "n_parse_err": n_err, "n_side_records": n_side_rec, "n_assistant_no_id": no_id,
                "n_msgs": len(order), "n_req_ids": len(reqs), "n_sidechain_msgs": int(sum(side.values())),
                "n_synthetic_msgs": int(sum(synth.values())), "n_sub_msgs": len(sub_last),
                "n_tool_use_ids": len(tool_ids), "n_tool_result_ids": len(tr_ids),
                "n_tool_use_ids_lastrec": len({t for v in last_tools.values() for t in v}),
                "n_tool_use_ids_firstrec": len({t for v in first_tools.values() for t in v}),
                "n_msgs_multi_record": int(sum(1 for m_ in order if last_tools.get(m_) is not first_tools.get(m_))),
                "n_distinct_sessionId": len(sess_ids), "file_sessionId_present": out["session_id"] in sess_ids,
                "n_versions": len(versions), "cc_version_max": max(versions) if versions else None, "n_cwds": len(cwds),
                "ts_min": ts_min, "ts_max": ts_max, "tsm_min": tsm_min, "tsm_max": tsm_max,
                "start_uuid_rec": uuid_rec, "start_uuid_msg": uuid_msg,
                "n_types_user": types["user"], "n_types_assistant": types["assistant"], "n_types_progress": types["progress"],
                "n_types_system": types["system"], "n_types_other": types["other"]})
    for k, v in zip(["in", "cc", "cr", "out"], np.array(list(sub_last.values()), dtype=np.int64).sum(0) if sub_last else [0] * 4):
        out[f"sub_{k}"] = int(v)
    if meta.get("api") is None:
        return
    seq_last = np.array([last[m] for m in order], dtype=np.int64).reshape(-1, 4)
    seq_first = np.array([first[m] for m in order], dtype=np.int64).reshape(-1, 4)
    keep_ns = np.array([not side[m] for m in order], dtype=bool)
    keep_nsyn = np.array([not synth[m] for m in order], dtype=bool)
    variants = {"F0": seq_last, "F1": seq_last[keep_ns], "F3": seq_first, "F4": seq_last[keep_nsyn]}
    for name, seq in variants.items():
        r = _match(seq, meta)
        for k, v in r.items():
            out[f"{name}_{k}"] = v
    # F2: F0 + progress-embedded subagent messages, full-match only
    sub = np.array(list(sub_last.values()), dtype=np.int64).reshape(-1, 4)
    tot = seq_last.sum(0) + sub.sum(0)
    out["F2_full"] = bool(len(order) + len(sub_last) == meta["api"] and np.array_equal(tot, [meta["in"], meta["cc"], meta["cr"], meta["out"]]))
    # declared-start windows: tally from a known start to the end (suffix) and of length api from that start
    starts = {"uuid": uuid_msg}
    for key in ("ctx_start", "lines_at_start"):
        L = meta.get(key)
        if L is not None:
            starts[key] = int(np.searchsorted(np.array(msg_rec, dtype=np.int64), int(L), side="left")) if msg_rec else 0
        else:
            starts[key] = None
    tokv = np.array([meta["in"], meta["cc"], meta["cr"], meta["out"]], dtype=np.int64)
    for key, s0 in starts.items():
        if s0 is None:
            out[f"F0_declstart_{key}"] = None
            continue
        suf = seq_last[s0:]
        cls = "none"
        if len(suf) == meta["api"] and np.array_equal(suf.sum(0), tokv):
            cls = "suffix"
        elif meta["api"] <= len(suf) and np.array_equal(suf[: meta["api"]].sum(0), tokv):
            cls = "from_start_len_api"
        out[f"F0_declstart_{key}"] = cls
        out[f"F0_declstart_{key}_msg"] = int(s0)
    # edited paths vs files_touched (all paths; paths inside the F0-matched span)
    files = meta.get("files") or []
    paths_all = {p for _, p in write_paths}
    out["n_write_paths"] = len(paths_all)
    out["n_write_paths_in_ft"] = sum(_path_match(p, files) for p in paths_all)
    out["n_ft"] = len(files)
    out["n_ft_covered_all"] = sum(any(_path_match(p, [f]) for p in paths_all) for f in files)
    cw = [c.replace("\\", "/").rstrip("/") + "/" for c in cwds]
    inside = {p for p in paths_all if any(p.replace("\\", "/").startswith(c) for c in cw)}
    out["n_write_paths_in_cwd"] = len(inside)
    rel = set()
    for p_ in inside:
        q = p_.replace("\\", "/")
        c_best = max((c for c in cw if q.startswith(c)), key=len)
        rel.add(q[len(c_best):])
    out["write_paths_rel_json"] = json.dumps(sorted(rel))
    out["n_write_paths_in_cwd_in_ft"] = sum(_path_match(p, files) for p in inside)
    out["n_ft_covered_by_in_cwd"] = sum(any(_path_match(p, [f]) for p in inside) for f in files)
    cls, st = out.get("F0_cls"), out.get("F0_start")
    if cls in ("full", "prefix", "window") and st is not None:
        span = {p for mi, p in write_paths if st <= mi < st + meta["api"]}
        out["n_write_paths_span"] = len(span)
        out["n_write_paths_span_in_ft"] = sum(_path_match(p, files) for p in span)
        out["n_ft_covered_span"] = sum(any(_path_match(p, [f]) for p in span) for f in files)


def _scan_codex(records, meta, out):
    tot, lst = [], []
    n_fc = 0
    ts_min = ts_max = None
    for d in records:
        ts = _ts(d.get("timestamp"))
        if ts is not None:
            ts_min = ts if ts_min is None or ts < ts_min else ts_min
            ts_max = ts if ts_max is None or ts > ts_max else ts_max
        p = d.get("payload") or {}
        if not isinstance(p, dict):
            continue
        pt = p.get("type")
        if d.get("type") == "response_item" and pt in ("function_call", "custom_tool_call", "local_shell_call"):
            n_fc += 1
        if d.get("type") == "event_msg" and pt == "token_count":
            info = p.get("info")
            if isinstance(info, dict):
                t = info.get("total_token_usage") or {}
                l = info.get("last_token_usage") or {}
                tot.append((_i(t.get("input_tokens")), _i(t.get("cached_input_tokens")), _i(t.get("output_tokens")),
                            _i(t.get("reasoning_output_tokens"))))
                lst.append((_i(l.get("input_tokens")), _i(l.get("cached_input_tokens")), _i(l.get("output_tokens")),
                            _i(l.get("reasoning_output_tokens"))))
    out.update({"ts_min": ts_min, "ts_max": ts_max, "n_msgs": len(tot), "n_tool_use_ids": n_fc})
    if meta.get("api") is None:
        return
    T = np.array(tot, dtype=np.int64).reshape(-1, 4)
    Lc = np.cumsum(np.array(lst, dtype=np.int64).reshape(-1, 4), axis=0)
    tokv = np.array([meta["in"], meta["cc"], meta["cr"], meta["out"]], dtype=np.int64)
    for name, A, out_fn in (("X0", T, lambda a: a[:, 2] + a[:, 3]), ("X1", T, lambda a: a[:, 2]), ("X2", Lc, lambda a: a[:, 2] + a[:, 3])):
        n = len(A)
        if n:
            cand = np.stack([A[:, 0], np.zeros(n, dtype=np.int64), A[:, 1], out_fn(A)], axis=1)
            hit = np.where((cand == tokv).all(axis=1))[0]
        else:
            hit = np.array([], dtype=int)
        api = meta["api"]
        cls = "none"
        if n and api == n and len(hit) and hit[-1] == n - 1:
            cls = "full"
        elif len(hit) and (hit + 1 == api).any():
            cls = "prefix"
        elif len(hit):
            cls = "tokens_at_other_k"
        elif api == 0 and not tokv.any():
            cls = "full" if n == 0 else "none"
        out[f"{name}_cls"] = cls
        if n:
            out[f"{name}_tx_in"], out[f"{name}_tx_cr"], out[f"{name}_tx_out"] = int(cand[-1, 0]), int(cand[-1, 2]), int(cand[-1, 3])
    out["tx_api"] = len(tot)


def _scan_opencode(doc, meta, out):
    msgs = doc.get("messages") or []
    seq0, seq1 = [], []
    n_tool = 0
    times = []
    for m in msgs:
        info = m.get("info") or {}
        tm = info.get("time") or {}
        for k in ("created", "completed"):
            if isinstance(tm.get(k), (int, float)):
                times.append(tm[k] / 1000.0)
        for p in m.get("parts") or []:
            if isinstance(p, dict) and p.get("type") == "tool":
                n_tool += 1
        if info.get("role") == "assistant":
            t = info.get("tokens") or {}
            c = t.get("cache") or {}
            seq0.append((_i(t.get("input")), _i(c.get("write")), _i(c.get("read")), _i(t.get("output"))))
            seq1.append((_i(t.get("input")), _i(c.get("write")), _i(c.get("read")), _i(t.get("output")) + _i(t.get("reasoning"))))
    out.update({"n_records": len(msgs), "n_msgs": len(seq0), "n_tool_use_ids": n_tool,
                "ts_min": min(times) if times else None, "ts_max": max(times) if times else None})
    if meta.get("api") is None:
        return
    for name, seq in (("O0", seq0), ("O1", seq1)):
        r = _match(np.array(seq, dtype=np.int64).reshape(-1, 4), meta)
        for k, v in r.items():
            out[f"{name}_{k}"] = v


def _scan_gemini(doc, meta, out):
    msgs = doc.get("messages") or []
    seq0, seq1 = [], []
    n_tool = 0
    times = []
    for m in msgs:
        ts = _ts(m.get("timestamp"))
        if ts is not None:
            times.append(ts)
        if m.get("type") == "gemini":
            n_tool += len(m.get("toolCalls") or [])
            t = m.get("tokens") or {}
            seq0.append((_i(t.get("input")), 0, _i(t.get("cached")), _i(t.get("output"))))
            seq1.append((_i(t.get("input")), 0, _i(t.get("cached")), _i(t.get("output")) + _i(t.get("thoughts"))))
    out.update({"n_records": len(msgs), "n_msgs": len(seq0), "n_tool_use_ids": n_tool,
                "ts_min": min(times) if times else None, "ts_max": max(times) if times else None})
    if meta.get("api") is None:
        return
    for name, seq in (("G0", seq0), ("G1", seq1)):
        r = _match(np.array(seq, dtype=np.int64).reshape(-1, 4), meta)
        for k, v in r.items():
            out[f"{name}_{k}"] = v


def scan_one(task):
    sid, path, meta = task
    out = {"session_id": sid, "fmt": "missing"}
    if not os.path.exists(path):
        return out
    out["file_bytes"] = os.path.getsize(path)
    try:
        first_line = ""
        with open(path, encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                if ln.strip():
                    first_line = ln
                    break
        try:
            d0 = json.loads(first_line)
            line_json = isinstance(d0, dict)
        except ValueError:
            line_json = False
        if not line_json:
            with open(path, encoding="utf-8", errors="replace") as fh:
                doc = json.load(fh)
            if isinstance(doc, dict) and "messages" in doc and "info" in doc:
                out["fmt"] = "opencode"
                _scan_opencode(doc, meta, out)
            elif isinstance(doc, dict) and isinstance(doc.get("messages"), list) and "sessionId" in doc:
                out["fmt"] = "gemini"
                _scan_gemini(doc, meta, out)
            else:
                out["fmt"] = "other_json"
            return out
        # sniff format from first 50 records
        tcount = Counter()
        with open(path, encoding="utf-8", errors="replace") as fh:
            k = 0
            for ln in fh:
                if not ln.strip():
                    continue
                try:
                    d = json.loads(ln)
                except ValueError:
                    continue
                t = d.get("type") if isinstance(d, dict) else None
                if t in CODEX_TYPES:
                    tcount["codex"] += 1
                elif t in CLAUDE_TYPES or (isinstance(d, dict) and ("parentUuid" in d or "sessionId" in d)):
                    tcount["claude"] += 1
                elif isinstance(t, str) and "." in t:
                    tcount["copilot"] += 1
                elif isinstance(d, dict) and "role" in d and "message" in d:
                    tcount["cursor"] += 1
                else:
                    tcount["other"] += 1
                k += 1
                if k >= 50:
                    break
        fmt = tcount.most_common(1)[0][0] if tcount else "empty"
        out["fmt"] = fmt
        if fmt == "claude":
            with open(path, encoding="utf-8", errors="replace") as fh:
                _scan_claude((ln for ln in fh if ln.strip()), meta, out)
        elif fmt == "codex":
            with open(path, encoding="utf-8", errors="replace") as fh:
                recs = (json.loads(ln) for ln in fh if ln.strip())
                _scan_codex((r for r in recs if isinstance(r, dict)), meta, out)
        else:
            n = 0
            with open(path, encoding="utf-8", errors="replace") as fh:
                for ln in fh:
                    n += bool(ln.strip())
            out["n_records"] = n
    except Exception as e:  # recorded, not hidden
        out["scan_error"] = f"{type(e).__name__}: {str(e)[:200]}"
    return out


def _meta_for_tx(s, logs):
    m = {}
    md = logs.set_index("session_id").session_metadata_raw.to_dict()
    for r in s.itertuples(index=False):
        raw = {}
        try:
            raw = json.loads(md.get(r.session_id) or "{}")
        except ValueError:
            pass
        tu = raw.get("token_usage")
        meta = {}
        if isinstance(tu, dict):
            meta = {"api": _i(r.api_call_count), "in": _i(r.input_tokens), "cc": _i(r.cache_creation_tokens),
                    "cr": _i(r.cache_read_tokens), "out": _i(r.output_tokens)}
        meta["start_uuid"] = raw.get("transcript_identifier_at_start") or None
        meta["ctx_start"] = raw.get("checkpoint_transcript_start")
        meta["lines_at_start"] = raw.get("transcript_lines_at_start")
        try:
            meta["files"] = json.loads(r.files_touched) if r.files_touched else []
        except ValueError:
            meta["files"] = []
        m[r.session_id] = meta
    return m


def stage_tx(workers, limit=None):
    s = pd.read_parquet(f"{D}/sessions.parquet", columns=["session_id", "files_touched", "input_tokens", "output_tokens",
                                                            "cache_creation_tokens", "cache_read_tokens", "api_call_count"])
    logs = pd.read_parquet(f"{D}/session_logs.parquet", columns=["session_id", "session_metadata_raw"])
    metas = _meta_for_tx(s, logs)
    tasks = [(sid, f"{D}/transcripts/{sid}.jsonl", metas[sid]) for sid in s.session_id]
    # largest files first so the pool tail is short
    tasks.sort(key=lambda t: -(os.path.getsize(t[1]) if os.path.exists(t[1]) else 0))
    if limit:
        tasks = tasks[-limit:]
    t0 = time.time()
    rows = []
    with Pool(workers) as pool:
        for i, r in enumerate(pool.imap_unordered(scan_one, tasks, chunksize=1)):
            rows.append(r)
            if (i + 1) % 500 == 0:
                print(f"tx {i + 1}/{len(tasks)} {time.time() - t0:.0f}s", flush=True)
    df = pd.DataFrame(rows)
    os.makedirs(INTER_DIR, exist_ok=True)
    df.to_parquet(TX_PARQUET, index=False)
    print(f"tx done {len(df)} rows {time.time() - t0:.0f}s -> {TX_PARQUET}", flush=True)


# ---------------------------------------------------------------------------------------------------------------------
# Stage conv: conversations.parquet aggregates
# ---------------------------------------------------------------------------------------------------------------------
def stage_conv():
    cols = ["session_id", "turn_number", "role", "turn_type", "is_conversational", "is_continuation", "timestamp",
            "input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "tool_name",
            "category", "file_path"]
    pf = pq.ParquetFile(f"{D}/conversations.parquet")
    parts, tools = [], []
    t0 = time.time()
    for bi, b in enumerate(pf.iter_batches(columns=cols, batch_size=100_000)):
        df = b.to_pandas()
        df["is_tool_use"] = df.role == "tool_use"
        df["is_assistant"] = df.role == "assistant"
        df["is_user_prompt"] = df.turn_type == "user_prompt"
        df["is_user_prompt_noncont"] = df.is_user_prompt & ~df.is_continuation.fillna(False)
        df["is_assistant_resp"] = df.turn_type == "assistant_response"
        df["tok_rows"] = df.is_assistant & (df.input_tokens.fillna(0) + df.output_tokens.fillna(0) + df.cache_read_input_tokens.fillna(0)
                                            + df.cache_creation_input_tokens.fillna(0) > 0)
        df["ts"] = (df.timestamp - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds()
        g = df.groupby("session_id", sort=False)
        agg = pd.DataFrame({
            "c_rows": g.size(),
            "c_tool_use": g.is_tool_use.sum(),
            "c_conversational": g.is_conversational.sum(),
            "c_user_prompt": g.is_user_prompt.sum(),
            "c_user_prompt_noncont": g.is_user_prompt_noncont.sum(),
            "c_assistant_resp": g.is_assistant_resp.sum(),
            "c_assistant_rows": g.is_assistant.sum(),
            "c_tok_rows": g.tok_rows.sum(),
            "c_in": g.input_tokens.sum(), "c_out": g.output_tokens.sum(),
            "c_cc": g.cache_creation_input_tokens.sum(), "c_cr": g.cache_read_input_tokens.sum(),
            "c_ts_min": g.ts.min(), "c_ts_max": g.ts.max(), "c_ts_null": g.ts.apply(lambda x: int(x.isna().sum())),
        })
        parts.append(agg)
        tu = df.loc[df.is_tool_use, ["session_id", "turn_number", "tool_name", "category", "file_path"]]
        tools.append(tu)
        if (bi + 1) % 5 == 0:
            print(f"conv batch {bi + 1} {time.time() - t0:.0f}s", flush=True)
    a = pd.concat(parts)
    g = a.groupby(level=0)
    sums = g[[c for c in a.columns if c not in ("c_ts_min", "c_ts_max")]].sum()
    sums["c_ts_min"] = g.c_ts_min.min()
    sums["c_ts_max"] = g.c_ts_max.max()
    T = pd.concat(tools, ignore_index=True).sort_values(["session_id", "turn_number"], kind="stable")
    T["pos"] = T.groupby("session_id").cumcount()
    gt = T.groupby("session_id")
    sums["c_unique_tools"] = gt.tool_name.nunique()
    sums["c_research"] = gt.category.apply(lambda x: int((x == "Research").sum()))
    sums["c_action"] = gt.category.apply(lambda x: int((x == "Action").sum()))
    w = T[T.tool_name.isin(WRITE_TOOLS_CONV)]
    sums["c_first_write_pos0"] = w.groupby("session_id").pos.min()
    out = sums.reset_index().rename(columns={"index": "session_id"})
    os.makedirs(INTER_DIR, exist_ok=True)
    out.to_parquet(CONV_PARQUET, index=False)
    print(f"conv done {len(out)} sessions, {len(T)} tool_use rows, {time.time() - t0:.0f}s", flush=True)


# ---------------------------------------------------------------------------------------------------------------------
# Stage report helpers
# ---------------------------------------------------------------------------------------------------------------------
def W(k, n):
    p, lo, hi = stats.wilson(int(k), int(n))
    return {"k": int(k), "n": int(n), "rate": p, "lo": lo, "hi": hi}


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(o, np.bool_):
        return bool(o)
    if o is pd.NaT:
        return None
    return o


def repo_cluster(flag, repo):
    """Agreement rate with a repo-clustered bootstrap CI (extra, more conservative than the session-level Wilson)."""
    df = pd.DataFrame({"f": np.asarray(flag, dtype=float), "r": np.asarray(repo)})
    g = df.groupby("r").f.agg(["sum", "count"])
    r = stats.cluster_rate(g["sum"].values, g["count"].values)
    r["n_clusters"] = r.pop("n_sessions")
    return r


def diff_shape(a, b, sids):
    """Shape of disagreement between two tallies a (harness) and b (recount)."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    d = a - b
    nz = d != 0
    out = {"n": int(len(d)), "n_exact": int((~nz).sum()), "n_a_gt_b": int((d > 0).sum()), "n_a_lt_b": int((d < 0).sum())}
    if nz.any():
        out["diff_describe"] = stats.describe(d[nz])
        ratio = np.where(b[nz] != 0, a[nz] / np.where(b[nz] == 0, 1, b[nz]), np.nan)
        out["ratio_describe_nonexact"] = stats.describe(ratio[~np.isnan(ratio)])
        out["n_nonexact_b_zero"] = int((b[nz] == 0).sum())
        vc = Counter(d[nz].astype(np.int64).tolist()) if np.all(np.mod(d[nz], 1) == 0) else Counter()
        out["top_offsets"] = [[k, v] for k, v in vc.most_common(10)]
        rel = np.abs(d) / np.maximum(np.maximum(np.abs(a), np.abs(b)), 1)
        out["n_near_1pct"] = int((rel <= 0.01).sum())
        out["abs_diff_median_ci"] = stats.cluster_quantile(np.abs(d[nz]), np.asarray(sids)[nz], 0.5)
    return out


def sarle_b(x):
    from scipy.stats import skew, kurtosis
    n = len(x)
    if n < 4 or np.std(x) == 0:
        return None
    g = skew(x)
    k = kurtosis(x)  # excess
    return float((g * g + 1) / (k + 3 * (n - 1) ** 2 / ((n - 2) * (n - 3))))


def sarle_ci(x, n_boot=stats.N_BOOT, seed=stats.SEED):
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n < 10 or np.std(x) == 0:
        return {"b": sarle_b(x), "lo": None, "hi": None, "n": int(n)}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    X = x[idx]
    m = X.mean(1, keepdims=True)
    c = X - m
    m2 = (c ** 2).mean(1)
    m3 = (c ** 3).mean(1)
    m4 = (c ** 4).mean(1)
    ok = m2 > 0
    g = np.where(ok, m3 / np.where(ok, m2, 1) ** 1.5, np.nan)
    k = np.where(ok, m4 / np.where(ok, m2, 1) ** 2 - 3, np.nan)
    b = (g * g + 1) / (k + 3 * (n - 1) ** 2 / ((n - 2) * (n - 3)))
    b = b[~np.isnan(b)]
    return {"b": sarle_b(x), "lo": float(np.quantile(b, 0.025)), "hi": float(np.quantile(b, 0.975)), "n": int(n)}


def dist_profile(v, integer):
    v = pd.to_numeric(pd.Series(v), errors="coerce")
    n_null = int(v.isna().sum())
    x = v.dropna().values.astype(float)
    out = {"n": int(len(v)), "n_null": n_null, "n_nonnull": int(len(x))}
    if len(x) == 0:
        return out
    out["n_zero"] = int((x == 0).sum())
    out["n_negative"] = int((x < 0).sum())
    out["describe"] = stats.describe(x)
    out["log_hist"] = stats.log_histogram(x, per_decade=4)
    vc = Counter(x.tolist())
    out["top_values"] = [[k, c] for k, c in vc.most_common(10)]
    out["n_distinct"] = len(vc)
    big = x[x >= 100]
    if integer and len(big):
        r = {}
        for k in (10, 100, 1000):
            r[f"div{k}"] = {**W(int((np.mod(big, k) == 0).sum()), len(big)), "expected": 1.0 / k}
        out["round_numbers_ge100"] = r
    if not integer:
        out["n_integer_valued"] = int((np.mod(x, 1) == 0).sum())
    if integer:
        spikes = []
        xs = np.sort(x)
        for val, c in vc.items():
            if val < 10 or c < 10:
                continue
            lo, hi = math.floor(val / 1.25), math.ceil(val * 1.25)
            nb = int(np.searchsorted(xs, hi, side="right") - np.searchsorted(xs, lo, side="left")) - c
            width = hi - lo  # number of integers in the window excluding v
            exp = nb / width if width > 0 else None
            if exp is not None and c >= 5 * max(exp, 1e-9):
                spikes.append({"value": val, "count": c, "local_mean_per_int": exp})
        spikes.sort(key=lambda r: -r["count"])
        out["spikes"] = spikes[:15]
        out["n_spikes"] = len(spikes)
    if (x >= 0).all():
        out["sarle_b_log1p"] = sarle_ci(np.log1p(x))
    return out


def classify_rows(df, prefix):
    return df[f"{prefix}_cls"].value_counts(dropna=False).to_dict() if f"{prefix}_cls" in df else {}


# ---------------------------------------------------------------------------------------------------------------------
# Stage report
# ---------------------------------------------------------------------------------------------------------------------
def stage_report():
    t0 = time.time()
    S = pd.read_parquet(f"{D}/sessions.parquet")
    C = pd.read_parquet(f"{D}/checkpoints.parquet")
    L = pd.read_parquet(f"{D}/session_logs.parquet")
    K = pq.read_table(f"{D}/commits.parquet", columns=["commit_sha", "checkpoint_pk", "total_additions", "total_deletions",
                                                         "files_changed_count", "commit_date"]).to_pandas()
    TX = pd.read_parquet(TX_PARQUET)
    CV = pd.read_parquet(CONV_PARQUET)
    S["session_success"] = pd.to_numeric(S.session_success, errors="coerce")
    S["n_checkpoint_ids"] = S.checkpoint_ids.map(lambda x: len(json.loads(x)) if x else 0)
    S["agent_grp"] = S.agent.where(S.agent.isin(["Claude Code", "OpenCode", "Codex", "Gemini CLI"]), "other")
    raw = L.set_index("session_id").session_metadata_raw.map(json.loads)
    S["raw"] = S.session_id.map(raw)
    J = {"meta": {"script": "analysis/probes/phase_c_swechat_tables.py", "data": D,
                  "inputs": {"sessions_rows": len(S), "checkpoints_rows": len(C), "session_logs_rows": len(L),
                             "commits_rows": len(K), "tx_rows": len(TX), "conv_sessions": len(CV)},
                  "note_source": "reads raw SWE-chat tables, not the IR cache",
                  "prereg": PREREG, "seed": stats.SEED, "n_boot": stats.N_BOOT},
         "inventory": {}}
    J["inventory"]["agent_label_counts"] = S.agent.value_counts().to_dict()
    J["inventory"]["agent_group_counts"] = S.agent_grp.value_counts().to_dict()
    M = S.merge(TX, on="session_id", how="left").merge(CV, on="session_id", how="left")
    for c in ("c_unique_tools", "c_research", "c_action"):
        M[c] = M[c].where(M[c].notna() | M.c_rows.isna(), 0)
    EPOCH = pd.Timestamp("1970-01-01", tz="UTC")
    M["created_s"] = (M.created_at - EPOCH).dt.total_seconds()
    J["inventory"]["tx_format_by_agent_label"] = {f"{a}|{f}": int(n) for (a, f), n in M.groupby(["agent", "fmt"], dropna=False).size().items()}
    J["inventory"]["tx_scan_errors"] = int(M.get("scan_error", pd.Series(dtype=object)).notna().sum())
    J["inventory"]["sessions_without_conv_rows"] = int(M.c_rows.isna().sum())
    J["inventory"]["raw_metadata_key_presence"] = dict(Counter(k for d in S.raw for k in d))
    J["inventory"]["sessions_with_token_usage_in_raw"] = int(S.raw.map(lambda d: isinstance(d.get("token_usage"), dict)).sum())
    J["inventory"]["sessions_api_zero_by_agent"] = S[S.api_call_count == 0].agent.value_counts().to_dict()
    J["inventory"]["builder_columns_null_by_agent"] = {c: S[S[c].isna()].agent.value_counts().to_dict()
                                                       for c in ["tool_call_count", "duration_seconds", "turn_count", "first_write_position"]}

    # ---------------- Part 1: distributions ----------------
    P1 = {}
    INTEGER = set(SESSION_NUMERIC) - {"agent_percentage", "duration_seconds", "session_success"}
    for grp, sub in [("all", S)] + [(g, S[S.agent_grp == g]) for g in ["Claude Code", "OpenCode", "Codex", "Gemini CLI", "other"]]:
        P1[grp] = {"n_sessions": len(sub)}
        for c in SESSION_NUMERIC:
            P1[grp][c] = dist_profile(sub[c], c in INTEGER)
    P1["checkpoints"] = {"n_checkpoints": len(C)}
    for c in CHECKPOINT_NUMERIC:
        P1["checkpoints"][c] = dist_profile(C[c], c != "unique_author_count")
    # timestamp digit / sub-second structure
    ca = S.created_at.dropna()
    P1["created_at_second_of_minute_chi2"] = stats.chi2_uniform(np.bincount(ca.dt.second.values, minlength=60))
    P1["created_at_hour_utc_counts"] = np.bincount(ca.dt.hour.values, minlength=24).tolist()
    P1["created_at_month_counts"] = ca.dt.strftime("%Y-%m").value_counts().sort_index().to_dict()
    ds = S.duration_seconds.dropna().values
    P1["duration_seconds_ms_digit_chi2"] = stats.chi2_uniform(np.bincount((np.round(ds * 1000) % 10).astype(int), minlength=10))
    # identical non-zero token 5-tuples across distinct session ids
    tk = S[S.output_tokens > 0]
    grp5 = tk.groupby(["input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens", "api_call_count"])
    sizes = grp5.size()
    dup = sizes[sizes > 1]
    dup_sids = tk.set_index(["input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens", "api_call_count"]).loc[dup.index]
    same_hash = dup_sids.groupby(level=[0, 1, 2, 3, 4]).content_hash.nunique()
    same_repo = dup_sids.groupby(level=[0, 1, 2, 3, 4]).repo_id.nunique()
    P1["duplicate_token_tuples"] = {"n_sessions_output_gt0": len(tk), "n_groups": int(len(dup)), "n_sessions_in_groups": int(dup.sum()),
                                    "group_size_counts": Counter(dup.tolist()), "groups_single_content_hash": int((same_hash == 1).sum()),
                                    "groups_single_repo": int((same_repo == 1).sum())}
    ch = S.content_hash.value_counts()
    P1["duplicate_content_hash"] = {"n_hashes_shared": int((ch > 1).sum()), "n_sessions_sharing": int(ch[ch > 1].sum())}
    J["part1_distributions"] = P1
    print(f"part1 {time.time() - t0:.0f}s", flush=True)

    # ---------------- Part 2: consistency ----------------
    P2 = {}
    # 2a raw metadata copy check (pipeline): sessions columns vs session_metadata_raw
    copy = {}
    has_tu = S.raw.map(lambda d: isinstance(d.get("token_usage"), dict))
    for k, col in SESS_TOK.items():
        rk = {"api": "api_call_count", "in": "input_tokens", "cc": "cache_creation_tokens", "cr": "cache_read_tokens", "out": "output_tokens"}[k]
        rv = S.raw.map(lambda d: _i((d.get("token_usage") or {}).get(rk)))
        copy[col] = W(int(((rv == S[col]) & has_tu).sum()), int(has_tu.sum()))
    copy["no_token_usage_in_raw_and_all_tokens_zero"] = W(int(((~has_tu) & (S[list(SESS_TOK.values())].sum(axis=1) == 0)).sum()), int((~has_tu).sum()))
    ft_raw = S.raw.map(lambda d: json.dumps(d.get("files_touched") or [], sort_keys=True))
    ft_tab = S.files_touched.map(lambda x: json.dumps(json.loads(x) if x else [], sort_keys=True))
    copy["files_touched"] = W(int((ft_raw == ft_tab).sum()), len(S))
    copy["files_touched_count_eq_len"] = W(int((S.files_touched.map(lambda x: len(json.loads(x)) if x else 0) == S.files_touched_count).sum()), len(S))
    cc_raw = S.raw.map(lambda d: d.get("checkpoints_count"))
    copy["checkpoints_count"] = W(int((cc_raw.fillna(-1).astype(int) == S.checkpoints_count).sum()), int(cc_raw.notna().sum()))
    P2["a_session_vs_raw_metadata_copy"] = copy

    # 2b harness tallies vs raw-transcript recount
    b = {}
    has_meta = M.raw.map(lambda d: isinstance(d.get("token_usage"), dict))
    cl = M[(M.fmt == "claude") & has_meta]
    cl_pos = cl[cl.api_call_count > 0]
    b["claude_format"] = {"n_with_token_usage": len(cl), "n_api_zero": int((cl.api_call_count == 0).sum()), "n_api_pos": len(cl_pos)}
    for F in ["F0", "F1", "F3", "F4"]:
        vc = cl_pos[f"{F}_cls"].value_counts().to_dict()
        b["claude_format"][F] = {c: W(vc.get(c, 0), len(cl_pos)) for c in ["full", "prefix", "window", "none"]}
        vc2 = cl_pos[f"{F}_cls_noout"].value_counts().to_dict()
        b["claude_format"][F + "_noout"] = {c: W(vc2.get(c, 0), len(cl_pos)) for c in ["full", "prefix", "window", "none"]}
    b["claude_format"]["F2_full"] = W(int(cl_pos.F2_full.fillna(False).sum()), len(cl_pos))
    anyF = cl_pos[[f"{F}_cls" for F in ["F0", "F1", "F3", "F4"]]].isin(["full", "prefix", "window"]).any(axis=1) | cl_pos.F2_full.fillna(False)
    b["claude_format"]["any_formula_any_class"] = W(int(anyF.sum()), len(cl_pos))
    b["claude_format"]["F0_full_repo_clustered"] = repo_cluster(cl_pos.F0_cls == "full", cl_pos.repo_id)
    b["claude_format"]["F0_matched_repo_clustered"] = repo_cluster(cl_pos.F0_cls.isin(["full", "prefix", "window"]), cl_pos.repo_id)
    # F0 full-transcript field-wise shape
    shape = {}
    for k in TOK:
        shape[SESS_TOK[k]] = diff_shape(cl_pos[SESS_TOK[k]], cl_pos[f"F0_tx_{k}"], cl_pos.session_id)
    b["claude_format"]["F0_full_transcript_fieldwise"] = shape
    # declared starts
    ds_ = {}
    for key in ("uuid", "ctx_start", "lines_at_start"):
        col = f"F0_declstart_{key}"
        if col in cl_pos:
            sub = cl_pos[cl_pos[col].notna()]
            ds_[key] = {"n_with_declared_start": len(sub), **{c: int((sub[col] == c).sum()) for c in ["suffix", "from_start_len_api", "none"]},
                        "matched_class_crosstab": {f"{a}|{c}": int(n) for (a, c), n in sub.groupby([col, "F0_cls"]).size().items()}}
            if key == "uuid":
                ds_[key]["n_start_uuid_declared"] = int(cl_pos.raw.map(lambda d: bool(d.get("transcript_identifier_at_start"))).sum())
                ds_[key]["n_start_uuid_found_in_transcript"] = int(cl_pos.start_uuid_rec.notna().sum())
                w = cl_pos[(cl_pos.F0_cls == "window") & cl_pos.start_uuid_msg.notna()]
                ds_[key]["window_start_eq_uuid_msg"] = W(int((w.F0_start == w.start_uuid_msg).sum()), len(w))
        b["claude_format"]["F0_declared_start"] = ds_
    if "F0_declstart_ctx_start" in cl_pos:
        wnd = cl_pos[cl_pos.F0_cls == "window"]
        b["claude_format"]["window_sessions"] = {"n": len(wnd), "n_ctx_start_declared": int(wnd.F0_declstart_ctx_start.notna().sum()),
                                                 "n_matched_at_declared_ctx_start": int(wnd.F0_declstart_ctx_start.isin(["suffix", "from_start_len_api"]).sum())}
    # F0 class by cli_version and by n_checkpoint_ids and created_at vs transcript end
    b["claude_format"]["F0_cls_by_cli_version"] = {f"{v}|{c}": int(n) for (v, c), n in cl_pos.groupby(["cli_version", "F0_cls"]).size().items()}
    b["claude_format"]["F0_cls_by_multi_checkpoint"] = {f"{v}|{c}": int(n) for (v, c), n in cl_pos.groupby([cl_pos.n_checkpoint_ids > 1, "F0_cls"]).size().items()}
    cl_pos = cl_pos.assign(created_minus_txend=cl_pos.created_s - cl_pos.ts_max)
    b["claude_format"]["created_minus_tx_end_by_cls"] = {c: {**stats.describe(g.created_minus_txend.dropna().values),
                                                             "n_negative": int((g.created_minus_txend < 0).sum())}
                                                         for c, g in cl_pos.groupby("F0_cls")}
    b["claude_format"]["msgs_after_snapshot_prefix"] = stats.describe((cl_pos.n_msgs - cl_pos.api_call_count)[cl_pos.F0_cls == "prefix"].values)
    b["claude_format"]["n_msgs_lt_api_in_none"] = int(((cl_pos.F0_cls == "none") & (cl_pos.n_msgs < cl_pos.api_call_count)).sum())
    b["claude_format"]["n_msgs_ge_api_in_none"] = int(((cl_pos.F0_cls == "none") & (cl_pos.n_msgs >= cl_pos.api_call_count)).sum())
    b["claude_format"]["req_ids_eq_msg_ids"] = W(int((cl.n_req_ids == cl.n_msgs).sum()), len(cl))
    b["claude_format"]["file_sessionId_present"] = W(int(cl.file_sessionId_present.fillna(False).sum()), len(cl))
    b["claude_format"]["n_distinct_sessionId_describe"] = stats.describe(cl.n_distinct_sessionId.values)
    b["claude_format"]["sessions_with_sidechain_msgs"] = int((cl.n_sidechain_msgs > 0).sum())
    b["claude_format"]["sessions_with_sub_msgs"] = int((cl.n_sub_msgs > 0).sum())
    b["claude_format"]["sessions_with_synthetic_msgs"] = int((cl.n_synthetic_msgs > 0).sum())
    b["claude_format"]["subagent_tokens_key_present"] = int(cl.raw.map(lambda d: "subagent_tokens" in (d.get("token_usage") or {})).sum())
    # api==0 with transcript activity
    z = M[(M.fmt == "claude") & (M.api_call_count == 0)]
    b["claude_format_api_zero"] = {"n": len(z), "n_with_msgs_gt0": int((z.n_msgs > 0).sum()), "agent_labels": z.agent.value_counts().to_dict(),
                                   "has_token_usage_key": int(z.raw.map(lambda d: isinstance(d.get("token_usage"), dict)).sum())}
    # codex
    cx = M[(M.fmt == "codex") & has_meta]
    b["codex_format"] = {"n": len(cx)}
    for F in ["X0", "X1", "X2"]:
        if f"{F}_cls" in cx:
            b["codex_format"][F] = cx[f"{F}_cls"].value_counts().to_dict()
    if "X0_cls" in cx:
        b["codex_format"]["X0_full_or_prefix"] = W(int(cx.X0_cls.isin(["full", "prefix"]).sum()), len(cx))
        b["codex_format"]["api_minus_tx_events"] = diff_shape(cx.api_call_count, cx.tx_api, cx.session_id)
    oc = M[(M.fmt == "opencode") & has_meta]
    b["opencode_format"] = {"n": len(oc)}
    for F in ["O0", "O1"]:
        if f"{F}_cls" in oc:
            vc = oc[f"{F}_cls"].value_counts().to_dict()
            b["opencode_format"][F] = {c: W(vc.get(c, 0), len(oc)) for c in ["full", "prefix", "window", "none"]}
    if "O0_cls" in oc:
        b["opencode_format"]["O0_fieldwise"] = {SESS_TOK[k]: diff_shape(oc[SESS_TOK[k]], oc[f"O0_tx_{k}"], oc.session_id) for k in TOK}
    gm = M[(M.fmt == "gemini") & has_meta]
    b["gemini_format"] = {"n": len(gm)}
    for F in ["G0", "G1"]:
        if f"{F}_cls" in gm:
            vc = gm[f"{F}_cls"].value_counts().to_dict()
            b["gemini_format"][F] = {c: W(vc.get(c, 0), len(gm)) for c in ["full", "prefix", "window", "none"]}
    if "G0_cls" in gm:
        gp = gm[gm.api_call_count > 0]
        b["gemini_format"]["n_api_pos"] = len(gp)
        b["gemini_format"]["G0_api_pos"] = gp.G0_cls.value_counts().to_dict()
    b["other_formats"] = {f"{f_}|{a_}": int(n_) for (f_, a_), n_ in M[~M.fmt.isin(["claude", "codex", "opencode", "gemini"])].groupby(["fmt", "agent"]).size().items()}
    P2["b_harness_tally_vs_transcript_recount"] = b
    print(f"part2b {time.time() - t0:.0f}s", flush=True)

    # 2c builder-derived columns vs conversations.parquet (pipeline consistency)
    c2 = {}
    pairs = [("tool_call_count", "c_tool_use"), ("unique_tools_count", "c_unique_tools"), ("research_count", "c_research"),
             ("action_count", "c_action"), ("turn_count", "c_conversational"), ("prompt_count", "c_user_prompt_noncont")]
    for a, bcol in pairs:
        sub = M[M[a].notna() & M[bcol].notna()]
        c2[f"{a}__vs__{bcol}"] = {"by_agent": {g: W(int((x[a] == x[bcol]).sum()), len(x)) for g, x in sub.groupby("agent_grp")},
                                  "all": W(int((sub[a] == sub[bcol]).sum()), len(sub)), "shape": diff_shape(sub[a], sub[bcol], sub.session_id),
                                  "n_left_null": int(M[a].isna().sum()), "n_right_null": int(M[bcol].isna().sum())}
    sub = M[M.first_write_position.notna()]
    c2["first_write_position_vs_conv_pos0"] = W(int((sub.first_write_position == sub.c_first_write_pos0).sum()), len(sub))
    c2["first_write_position_vs_conv_pos1"] = W(int((sub.first_write_position == sub.c_first_write_pos0 + 1).sum()), len(sub))
    c2["first_write_position_null_but_conv_has_write"] = int((M.first_write_position.isna() & M.c_first_write_pos0.notna()).sum())
    sub = M[M.duration_seconds.notna() & M.c_ts_min.notna()]
    d = (sub.duration_seconds - (sub.c_ts_max - sub.c_ts_min)).abs()
    c2["duration_vs_conv_ts_span"] = {"exact_1ms": W(int((d <= 0.001).sum()), len(sub)), "near_1s": W(int((d <= 1).sum()), len(sub)),
                                      "shape": diff_shape(sub.duration_seconds, sub.c_ts_max - sub.c_ts_min, sub.session_id)}
    sub = M[M.duration_seconds.notna() & M.ts_min.notna()]
    d = (sub.duration_seconds - (sub.ts_max - sub.ts_min)).abs()
    c2["duration_vs_raw_tx_ts_span"] = {"exact_1ms": W(int((d <= 0.001).sum()), len(sub)), "near_1s": W(int((d <= 1).sum()), len(sub)),
                                        "shape": diff_shape(sub.duration_seconds, sub.ts_max - sub.ts_min, sub.session_id)}
    sub = M[(M.fmt == "claude") & M.tool_call_count.notna()]
    c2["tool_call_count_vs_raw_tx_tool_use_ids"] = {"all": W(int((sub.tool_call_count == sub.n_tool_use_ids).sum()), len(sub)),
                                                    "shape": diff_shape(sub.tool_call_count, sub.n_tool_use_ids, sub.session_id)}
    # conversations per-turn tokens vs harness tallies
    tk = {}
    sub = M[(M.output_tokens > 0) & M.c_rows.notna()]
    for k, col in (("in", "input_tokens"), ("out", "output_tokens"), ("cc", "cache_creation_tokens"), ("cr", "cache_read_tokens")):
        r = stats.cluster_rate(sub[f"c_{k}"].values, sub[col].values)
        tk[col] = {"pooled_ratio_conv_over_session": r, "n_exact": int((sub[f"c_{k}"] == sub[col]).sum()), "n": len(sub),
                   "per_session_ratio": stats.describe((sub[f"c_{k}"] / sub[col].replace(0, np.nan)).dropna().values)}
    tk["assistant_rows_with_tokens_over_api_calls"] = stats.cluster_rate(sub.c_tok_rows.values, sub.api_call_count.values)
    c2["conv_per_turn_tokens_vs_session_tokens"] = tk
    # session_metrics.turn_count and context_md prompt count (harness-side) vs builder columns
    smt = M.raw.map(lambda d: (d.get("session_metrics") or {}).get("turn_count"))
    sub = M[smt.notna()].assign(smt=smt[smt.notna()].astype(float))
    c2["raw_session_metrics_turn_count"] = {"n": len(sub),
                                            "eq_prompt_count": W(int((sub.smt == sub.prompt_count).sum()), len(sub)),
                                            "eq_turn_count": W(int((sub.smt == sub.turn_count).sum()), len(sub)),
                                            "eq_conv_user_prompt": W(int((sub.smt == sub.c_user_prompt).sum()), len(sub)),
                                            "shape_vs_prompt_count": diff_shape(sub.smt, sub.prompt_count, sub.session_id)}
    has_up = L.context_md.str.contains(r"(?m)^## User Prompts\s*$", regex=True)
    npm = L.context_md.str.count(r"(?m)^### Prompt \d+\s*$")
    ctx = pd.DataFrame({"session_id": L.session_id, "has_up": has_up, "ctx_prompts": npm}).merge(M[["session_id", "prompt_count", "c_user_prompt", "agent_grp", "n_checkpoint_ids"]], on="session_id")
    sub = ctx[ctx.has_up]
    c2["context_md_prompt_count"] = {"n_with_user_prompts_section": len(sub), "n_without": int((~ctx.has_up).sum()),
                                     "eq_prompt_count": W(int((sub.ctx_prompts == sub.prompt_count).sum()), len(sub)),
                                     "eq_conv_user_prompt": W(int((sub.ctx_prompts == sub.c_user_prompt).sum()), len(sub)),
                                     "shape_vs_prompt_count": diff_shape(sub.ctx_prompts, sub.prompt_count, sub.session_id),
                                     "ctx_lt_prompt_count_multi_checkpoint": W(int(((sub.ctx_prompts < sub.prompt_count) & (sub.n_checkpoint_ids > 1)).sum()), int((sub.n_checkpoint_ids > 1).sum())),
                                     "ctx_lt_prompt_count_single_checkpoint": W(int(((sub.ctx_prompts < sub.prompt_count) & (sub.n_checkpoint_ids <= 1)).sum()), int((sub.n_checkpoint_ids <= 1).sum())),
                                     "offset_minus7": {"n": int(((sub.ctx_prompts - sub.prompt_count) == -7).sum()),
                                                       "top_repos": M.set_index("session_id").loc[sub.loc[(sub.ctx_prompts - sub.prompt_count) == -7].session_id].repo_id.value_counts().head(5).to_dict(),
                                                       "n_distinct_repos": int(M.set_index("session_id").loc[sub.loc[(sub.ctx_prompts - sub.prompt_count) == -7].session_id].repo_id.nunique())}}
    P2["c_builder_and_auxiliary_vs_conversations"] = c2
    print(f"part2c {time.time() - t0:.0f}s", flush=True)

    # 2d files_touched vs tool paths
    f2 = {}
    sub = M[(M.fmt == "claude") & (M.n_ft.notna())]
    for lab, x in (("all", sub), ("api_pos", sub[sub.api_call_count > 0])):
        has_both = x[(x.n_ft > 0) & (x.n_write_paths > 0)]
        f2[lab] = {"n": len(x), "n_ft_zero": int((x.n_ft == 0).sum()), "n_write_paths_zero": int((x.n_write_paths == 0).sum()),
                   "n_ft_zero_but_write_paths": int(((x.n_ft == 0) & (x.n_write_paths > 0)).sum()),
                   "n_ft_pos_but_no_write_paths": int(((x.n_ft > 0) & (x.n_write_paths == 0)).sum()),
                   "both_nonempty": len(has_both),
                   "all_ft_covered_by_write_paths": W(int((has_both.n_ft_covered_all == has_both.n_ft).sum()), len(has_both)),
                   "all_write_paths_in_ft": W(int((has_both.n_write_paths_in_ft == has_both.n_write_paths).sum()), len(has_both)),
                   "set_equal": W(int(((has_both.n_ft_covered_all == has_both.n_ft) & (has_both.n_write_paths_in_ft == has_both.n_write_paths)).sum()), len(has_both)),
                   "pooled_ft_covered": stats.cluster_rate(has_both.n_ft_covered_all.values, has_both.n_ft.values),
                   "pooled_write_paths_in_ft": stats.cluster_rate(has_both.n_write_paths_in_ft.values, has_both.n_write_paths.values)}
    sp = sub[sub.n_write_paths_span.notna() & (sub.n_ft > 0) & (sub.n_write_paths_span > 0)]
    f2["within_F0_matched_span"] = {"n": len(sp),
                                    "all_ft_covered": W(int((sp.n_ft_covered_span == sp.n_ft).sum()), len(sp)),
                                    "all_span_paths_in_ft": W(int((sp.n_write_paths_span_in_ft == sp.n_write_paths_span).sum()), len(sp)),
                                    "pooled_ft_covered": stats.cluster_rate(sp.n_ft_covered_span.values, sp.n_ft.values),
                                    "pooled_span_paths_in_ft": stats.cluster_rate(sp.n_write_paths_span_in_ft.values, sp.n_write_paths_span.values)}
    P2["d_files_touched_vs_write_tool_paths"] = f2

    # 2e checkpoint-level: cp_* vs sums over its sessions; link symmetry; commits
    e = {}
    sess_idx = S.set_index("session_id")
    canon = sess_idx.canonical_checkpoint_pk.to_dict()
    sess_cps = sess_idx.checkpoint_ids.map(lambda x: set(json.loads(x)) if x else set()).to_dict()
    tokcols = {"api": "api_call_count", "in": "input_tokens", "cc": "cache_creation_tokens", "cr": "cache_read_tokens", "out": "output_tokens"}
    cpcols = {"api": "cp_api_call_count", "in": "cp_input_tokens", "cc": "cp_cache_creation_tokens", "cr": "cp_cache_read_tokens", "out": "cp_output_tokens"}
    tokmat = sess_idx[list(tokcols.values())]
    rows = []
    n_link, n_link_sym = 0, 0
    for r in C.itertuples(index=False):
        pks = json.loads(r.session_pks) if r.session_pks else []
        md = json.loads(r.checkpoint_metadata_raw)
        res = [p for p in pks if p in canon]
        for p in res:
            n_link += 1
            n_link_sym += r.checkpoint_pk in sess_cps[p]
        all_res = len(res) == len(pks) and len(pks) > 0
        all_can = all_res and all(canon[p] == r.checkpoint_pk for p in pks)
        sums = tokmat.loc[res].sum() if res else pd.Series(0, index=tokmat.columns)
        mx = tokmat.loc[res].max() if res else pd.Series(0, index=tokmat.columns)
        row = {"checkpoint_pk": r.checkpoint_pk, "n_pks": len(pks), "n_res": len(res), "all_res": all_res, "all_canon": all_can,
               "has_tu": isinstance(md.get("token_usage"), dict), "n_md_sessions": len(md.get("sessions") or []),
               "session_count": r.session_count, "commit_count": r.commit_count,
               "n_commit_shas": len(json.loads(r.commit_shas)) if r.commit_shas else 0, "repo_id": r.repo_id}
        for k in TOK:
            row[f"cp_{k}"] = getattr(r, cpcols[k])
            row[f"sum_{k}"] = int(sums[tokcols[k]])
            row[f"max_{k}"] = int(mx[tokcols[k]])
        if all_can and len(pks) == 1:
            s1 = sess_idx.loc[pks[0]]
            row["single_ft_eq"] = json.dumps(sorted(json.loads(r.files_touched or "[]"))) == json.dumps(sorted(json.loads(s1.files_touched or "[]")))
            row["single_cc_eq"] = int(r.checkpoints_count) == int(s1.checkpoints_count)
        elif all_can:
            u = set()
            for p in pks:
                u |= set(json.loads(sess_idx.at[p, "files_touched"] or "[]"))
            row["multi_ft_eq_union"] = set(json.loads(r.files_touched or "[]")) == u
        rows.append(row)
    CR = pd.DataFrame(rows)
    e["link_symmetry_checkpoint_to_session"] = W(n_link_sym, n_link)
    n_sl, n_sl_sym = 0, 0
    cp_pks = {r.checkpoint_pk: set(json.loads(r.session_pks) if r.session_pks else []) for r in C.itertuples(index=False)}
    for sid, cps in sess_cps.items():
        for cp in cps:
            if cp in cp_pks:
                n_sl += 1
                n_sl_sym += sid in cp_pks[cp]
    e["link_symmetry_session_to_checkpoint"] = W(n_sl_sym, n_sl)
    e["session_checkpoint_ids_not_in_checkpoints_table"] = int(sum(cp not in cp_pks for cps in sess_cps.values() for cp in cps))
    e["canonical_in_own_checkpoint_ids"] = W(int(sum(canon[s] in sess_cps[s] for s in canon)), len(canon))
    e["session_count_eq_len_session_pks"] = W(int((CR.session_count == CR.n_pks).sum()), len(CR))
    e["session_count_eq_metadata_sessions_len"] = W(int((CR.session_count == CR.n_md_sessions).sum()), len(CR))
    e["commit_count_eq_len_commit_shas"] = W(int((CR.commit_count == CR.n_commit_shas).sum()), len(CR))
    e["session_pks_resolution"] = {"n_pks": int(CR.n_pks.sum()), "n_resolved": int(CR.n_res.sum()),
                                   "n_unresolved": int(CR.n_pks.sum() - CR.n_res.sum()),
                                   "checkpoints_all_resolved": int(CR.all_res.sum()), "checkpoints_all_canonical": int(CR.all_canon.sum())}
    elig = CR[CR.all_canon & CR.has_tu]
    e["cp_vs_sum_sessions_all_canonical"] = {"n": len(elig)}
    for k in TOK:
        e["cp_vs_sum_sessions_all_canonical"][cpcols[k]] = {"eq_sum": W(int((elig[f"cp_{k}"] == elig[f"sum_{k}"]).sum()), len(elig)),
                                                            "shape": diff_shape(elig[f"cp_{k}"], elig[f"sum_{k}"], elig.checkpoint_pk)}
    allf = np.logical_and.reduce([elig[f"cp_{k}"] == elig[f"sum_{k}"] for k in TOK]) if len(elig) else np.array([])
    e["cp_vs_sum_sessions_all_canonical"]["all5_eq_sum"] = W(int(allf.sum()), len(elig))
    for nm, x in (("single_session", elig[elig.n_pks == 1]), ("multi_session", elig[elig.n_pks > 1])):
        a5 = np.logical_and.reduce([x[f"cp_{k}"] == x[f"sum_{k}"] for k in TOK]) if len(x) else np.array([])
        m5 = np.logical_and.reduce([x[f"cp_{k}"] == x[f"max_{k}"] for k in TOK]) if len(x) else np.array([])
        e["cp_vs_sum_sessions_all_canonical"][nm] = {"all5_eq_sum": W(int(a5.sum()), len(x)), "all5_eq_max": W(int(m5.sum()), len(x))}
    nonc = CR[CR.all_res & ~CR.all_canon & CR.has_tu]
    e["cp_vs_sum_sessions_some_canonical_elsewhere"] = {"n": len(nonc),
                                                       "all5_eq_sum": W(int(np.logical_and.reduce([nonc[f"cp_{k}"] == nonc[f"sum_{k}"] for k in TOK]).sum()), len(nonc)) if len(nonc) else None,
                                                       "out_cp_gt_sum": int((nonc.cp_out > nonc.sum_out).sum()), "out_cp_lt_sum": int((nonc.cp_out < nonc.sum_out).sum()),
                                                       "out_ratio_cp_over_sum": stats.describe((nonc.cp_out / nonc.sum_out.replace(0, np.nan)).dropna().values)}
    x = CR[CR.single_ft_eq.notna()] if "single_ft_eq" in CR else CR.iloc[:0]
    e["single_session_checkpoint_files_touched_eq_session"] = W(int(x.single_ft_eq.astype(bool).sum()), len(x))
    e["single_session_checkpoint_checkpoints_count_eq_session"] = W(int(x.single_cc_eq.astype(bool).sum()), len(x))
    x = CR[CR.multi_ft_eq_union.notna()] if "multi_ft_eq_union" in CR else CR.iloc[:0]
    e["multi_session_checkpoint_files_touched_eq_union"] = W(int(x.multi_ft_eq_union.astype(bool).sum()), len(x))
    # commits
    kc = K.groupby("checkpoint_pk").agg(n_rows=("commit_sha", "size"), add_sum=("total_additions", "sum"), del_sum=("total_deletions", "sum"))
    cj = C.set_index("checkpoint_pk")[["commit_count", "total_additions", "total_deletions"]].join(kc, how="left")
    e["commits_rows_per_checkpoint_eq_commit_count"] = W(int((cj.n_rows.fillna(0) == cj.commit_count).sum()), len(cj))
    e["checkpoint_additions_eq_sum_commit_additions"] = W(int((cj.add_sum.fillna(0) == cj.total_additions).sum()), len(cj))
    e["checkpoint_deletions_eq_sum_commit_deletions"] = W(int((cj.del_sum.fillna(0) == cj.total_deletions).sum()), len(cj))
    P2["e_checkpoint_level"] = e
    print(f"part2e {time.time() - t0:.0f}s", flush=True)

    # 2f attribution identities and timestamps
    f = {}
    at = S[S.total_committed.notna()]
    f["n_with_attribution"] = len(at)
    f["total_eq_agent_plus_human_added"] = W(int((at.total_committed == at.agent_lines + at.human_added).sum()), len(at))
    f["total_eq_agent_plus_human_added_modified"] = W(int((at.total_committed == at.agent_lines + at.human_added + at.human_modified).sum()), len(at))
    atp = at[at.total_committed > 0]
    pct = 100 * atp.agent_lines / atp.total_committed
    f["agent_percentage_identity"] = W(int(((atp.agent_percentage - pct).abs() <= 1e-6).sum()), len(atp))
    f["agent_percentage_identity_shape"] = diff_shape(atp.agent_percentage, pct, atp.session_id)
    f["total_committed_zero"] = {"n": int((at.total_committed == 0).sum()), "agent_percentage_values": Counter(at[at.total_committed == 0].agent_percentage.round(6).tolist()).most_common(5)}
    f["agent_lines_gt_total_committed"] = int((at.agent_lines > at.total_committed).sum())
    f["agent_percentage_gt_100"] = int((at.agent_percentage > 100).sum())
    f["negative_values"] = {c: int((at[c] < 0).sum()) for c in ["agent_lines", "human_added", "human_modified", "human_removed", "total_committed"]}
    gap = (S.created_at - S.attribution_calculated_at).dt.total_seconds().dropna()
    f["created_minus_attribution_calculated_s"] = {**stats.describe(gap.values), "n_negative": int((gap < 0).sum()), "n_gt_60s": int((gap > 60).sum())}
    ce = (M.created_s - M.ts_max).where(M.ts_max.notna() & M.created_at.notna()).dropna()
    f["created_minus_tx_last_ts_s"] = {**stats.describe(ce.values), "n_negative": int((ce < 0).sum()), "n_lt_minus_3600": int((ce < -3600).sum())}
    cs = (M.created_s - M.ts_min).where(M.ts_min.notna() & M.created_at.notna()).dropna()
    f["created_minus_tx_first_ts_s"] = {**stats.describe(cs.values), "n_negative": int((cs < 0).sum())}
    P2["f_attribution_and_timestamps"] = f
    J["part2_consistency"] = P2
    print(f"part2 {time.time() - t0:.0f}s", flush=True)

    # ---------------- Part 3: correlations ----------------
    from scipy.stats import rankdata
    M["sidechain_msg_share"] = M.n_sidechain_msgs / M.n_msgs.replace(0, np.nan)
    feats = [c for grp in FEATURE_GROUPS.values() for c in grp]
    grp_of = {c: g for g, cs in FEATURE_GROUPS.items() for c in cs}
    P3 = {}
    for popname, pop in (("claude_code", M[(M.agent == "Claude Code") & (M.fmt == "claude")]), ("all_claude_format", M[M.fmt == "claude"])):
        use = [c for c in feats if pop[c].notna().mean() >= 0.8 and pop[c].nunique() > 2]
        X = pop[use + ["n_records"]].dropna() if "n_records" not in use else pop[use].dropna()
        A = X[use].values.astype(float)
        n = len(A)
        R = np.column_stack([rankdata(A[:, j]) for j in range(A.shape[1])])
        rho = np.corrcoef(R, rowvar=False)
        size_r = rankdata(X["n_records"].values.astype(float))
        Z = np.column_stack([np.ones(n), size_r])
        beta = np.linalg.lstsq(Z, R, rcond=None)[0]
        RES = R - Z @ beta
        prho = np.corrcoef(RES, rowvar=False)
        rng = np.random.default_rng(stats.SEED)
        boots, pboots = [], []
        for _ in range(stats.N_BOOT):
            ii = rng.integers(0, n, n)
            Rb = np.column_stack([rankdata(A[ii, j]) for j in range(A.shape[1])])
            boots.append(np.corrcoef(Rb, rowvar=False))
            sb = rankdata(X["n_records"].values[ii].astype(float))
            Zb = np.column_stack([np.ones(n), sb])
            RESb = Rb - Zb @ np.linalg.lstsq(Zb, Rb, rcond=None)[0]
            pboots.append(np.corrcoef(RESb, rowvar=False))
        boots, pboots = np.array(boots), np.array(pboots)
        pairs_out = {}
        for nm, mat, bt in (("spearman", rho, boots), ("partial_spearman_given_n_records", prho, pboots)):
            lst = []
            p = len(use)
            for i in range(p):
                for j in range(i + 1, p):
                    if nm.startswith("partial") and ("n_records" in (use[i], use[j])):
                        continue
                    v = mat[i, j]
                    if np.isnan(v):
                        continue
                    lst.append({"a": use[i], "b": use[j], "rho": float(v), "lo": float(np.nanquantile(bt[:, i, j], 0.025)),
                                "hi": float(np.nanquantile(bt[:, i, j], 0.975)), "same_declared_group": grp_of[use[i]] == grp_of[use[j]],
                                "groups": [grp_of[use[i]], grp_of[use[j]]]})
            lst.sort(key=lambda r: -abs(r["rho"]))
            cross = [r for r in lst if not r["same_declared_group"]]
            pairs_out[nm] = {"top_all": lst[:PREREG["correlations"]["top_k"]], "top_cross_group": cross[:PREREG["correlations"]["top_k"]],
                             "n_pairs": len(lst), "n_abs_ge_0_5": int(sum(abs(r["rho"]) >= 0.5 for r in lst)),
                             "n_cross_abs_ge_0_5": int(sum(abs(r["rho"]) >= 0.5 for r in cross))}
        P3[popname] = {"n_complete_cases": int(n), "n_population": len(pop), "features": use, **pairs_out}
    J["part3_correlations"] = P3
    print(f"part3 {time.time() - t0:.0f}s", flush=True)

    # ---------------- Part 4: multi-axis outliers ----------------
    M["out_per_api"] = M.output_tokens / M.api_call_count.replace(0, np.nan)
    M["cr_per_api"] = M.cache_read_tokens / M.api_call_count.replace(0, np.nan)
    M["tools_per_api"] = M.tool_call_count / M.api_call_count.replace(0, np.nan)
    M["sec_per_api"] = M.duration_seconds / M.api_call_count.replace(0, np.nan)
    M["research_share"] = M.research_count / M.tool_call_count.replace(0, np.nan)
    LOG1P = ["input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens", "api_call_count", "tool_call_count",
             "unique_tools_count", "research_count", "action_count", "duration_seconds", "turn_count", "prompt_count",
             "files_touched_count", "checkpoints_count", "agent_lines", "total_committed"]
    LOG = ["out_per_api", "cr_per_api", "tools_per_api", "sec_per_api"]
    RAWF = ["agent_percentage", "research_share"]
    OF = LOG1P + LOG + RAWF
    PREREG["outliers"]["features"] = {"log1p": LOG1P, "log": LOG, "raw": RAWF}

    def robust_z(df):
        Z = pd.DataFrame(index=df.index)
        used, dropped = [], []
        for c in OF:
            x = df[c].astype(float)
            if c in LOG1P:
                x = np.log1p(x.clip(lower=0))
            elif c in LOG:
                x = np.log(x.where(x > 0))
            med = x.median()
            mad = (x - med).abs().median()
            scale = 1.4826 * mad
            if not scale or np.isnan(scale):
                scale = 1.2533 * (x - x.mean()).abs().mean()
            if not scale or np.isnan(scale):
                dropped.append(c)
                continue
            Z[c] = (x - med) / scale
            used.append(c)
        return Z, used, dropped

    P4 = {}
    thr = PREREG["outliers"]["threshold"]
    pops = {"claude_code": M[(M.agent == "Claude Code") & (M.fmt == "claude")]}
    big = [g for g, n in M.agent.value_counts().items() if n >= 200]
    pops["all_within_agent_groups"] = M[M.agent.isin(big)]
    for pname, pop in pops.items():
        if pname == "claude_code":
            Zs, used, dropped = robust_z(pop)
        else:
            parts_, used, dropped = [], set(), set()
            for g, x in pop.groupby("agent"):
                z_, u_, d_ = robust_z(x)
                parts_.append(z_)
                used |= set(u_)
                dropped |= {f"{g}:{c}" for c in d_}
            Zs = pd.concat(parts_).reindex(pop.index)
            used, dropped = sorted(used), sorted(dropped)
        ext = (Zs.abs() > thr)
        n_ext = ext.sum(axis=1)
        isout = n_ext >= 3
        O, R = pop[isout], pop[~isout]
        res = {"n": len(pop), "features_used": used, "n_features_used": len(used), "features_dropped": dropped, "n_outliers": int(isout.sum()),
               "outlier_rate": W(int(isout.sum()), len(pop)),
               "n_extreme_features_hist": n_ext.value_counts().sort_index().to_dict(),
               "feature_extreme_counts_all": ext.sum().to_dict(),
               "feature_extreme_counts_in_outliers": {c: {"high": int(((Zs.loc[isout, c]) > thr).sum()), "low": int(((Zs.loc[isout, c]) < -thr).sum())} for c in Zs.columns}}
        combos = Counter(tuple(sorted(f"{c}{'+' if Zs.at[i, c] > 0 else '-'}" for c in Zs.columns if ext.at[i, c])) for i in O.index)
        res["top_extreme_feature_combos"] = [[list(k), v] for k, v in combos.most_common(15)]

        def share_cmp(col, min_k=5):
            vo = O[col].astype(str).value_counts()
            va = pop[col].astype(str).value_counts()
            outl = []
            for val, k in vo.items():
                if k < min_k:
                    continue
                outl.append({"value": val, "in_outliers": W(k, len(O)), "in_population": W(int(va.get(val, 0)), len(pop))})
            return outl[:15]

        pop = pop.assign(created_month=pop.created_at.dt.strftime("%Y-%m"), multi_cp=pop.n_checkpoint_ids > 1,
                         api_zero=pop.api_call_count == 0, F0=pop.get("F0_cls"))
        O = pop[isout]
        res["common"] = {c: share_cmp(c) for c in ["repo_id", "user_id", "cli_version", "created_month", "user_persona", "multi_cp",
                                                   "api_zero", "F0", "agent", "strategy"]}
        res["n_distinct_repos_outliers"] = int(O.repo_id.nunique())
        res["n_distinct_repos_population"] = int(pop.repo_id.nunique())
        res["session_success_outliers"] = stats.describe(O.session_success.dropna().values)
        res["session_success_rest"] = stats.describe(R.session_success.dropna().values)
        res["n_records_outliers"] = stats.describe(O.n_records.dropna().values) if "n_records" in O else None
        res["n_records_rest"] = stats.describe(R.n_records.dropna().values) if "n_records" in R else None
        P4[pname] = res
    J["part4_outliers"] = P4
    extra_sections(J, S, C, L, M, P4, robust_z, thr)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(clean(J), fh, indent=1, default=str)
    print(f"report done {time.time() - t0:.0f}s -> {OUT_JSON}", flush=True)


def extra_sections(J, S, C, L, M, P4, robust_z, thr):
    """Follow-up measurements added after reading the first report (stored under 'followup' in the JSON). Each is a recount
    or a characterisation of a set already defined above; none introduces a new threshold."""
    X = {"note": "added after the first report pass; post hoc characterisation, not pre-registered"}
    cl = M[(M.fmt == "claude") & M.raw.map(lambda d: isinstance(d.get("token_usage"), dict)) & (M.api_call_count > 0)]
    X["F2_full_and_F0_not_full"] = int((cl.F2_full.fillna(False).astype(bool) & (cl.F0_cls != "full")).sum())
    X["F2_full_and_F0_none"] = int((cl.F2_full.fillna(False).astype(bool) & (cl.F0_cls == "none")).sum())
    X["F2_full_and_n_sub_msgs_gt0"] = int((cl.F2_full.fillna(False).astype(bool) & (cl.n_sub_msgs > 0)).sum())
    # cross-session lookup of unmatched tallies against every session's whole-transcript recount
    full_tuple = {}
    for pre in ("F0", "O0", "G0"):
        cols = [f"{pre}_tx_api", f"{pre}_tx_in", f"{pre}_tx_cc", f"{pre}_tx_cr", f"{pre}_tx_out"]
        if not all(c in M for c in cols):
            continue
        sub = M[M[cols[1]].notna()]
        for sid, *vals in sub[["session_id"] + cols].itertuples(index=False):
            full_tuple.setdefault(tuple(int(v) for v in vals), []).append(sid)
    if "X0_tx_in" in M:
        sub = M[M.X0_tx_in.notna()]
        for sid, a, i, cr, o in sub[["session_id", "tx_api", "X0_tx_in", "X0_tx_cr", "X0_tx_out"]].itertuples(index=False):
            full_tuple.setdefault((int(a), int(i), 0, int(cr), int(o)), []).append(sid)
    none_rows = []
    for fmt, pre in (("claude", "F0"), ("codex", "X0"), ("opencode", "O0"), ("gemini", "G0")):
        col = f"{pre}_cls"
        if col not in M:
            continue
        sub = M[(M.fmt == fmt) & (M[col].isin(["none", "tokens_at_other_k"])) & (M.api_call_count > 0)]
        for r in sub.itertuples(index=False):
            key = (int(r.api_call_count), int(r.input_tokens), int(r.cache_creation_tokens), int(r.cache_read_tokens), int(r.output_tokens))
            raw_tu = r.raw.get("token_usage") or {}
            row = {"session_id": r.session_id, "agent": r.agent, "fmt": fmt, "cls": getattr(r, col), "cli_version": r.cli_version,
                   "repo_id": r.repo_id, "api_meta": int(r.api_call_count), "tx_msgs": None if pd.isna(r.n_msgs) else int(r.n_msgs),
                   "n_checkpoint_ids": int(r.n_checkpoint_ids),
                   "created_minus_tx_end_s": None if pd.isna(r.ts_max) else float(r.created_s - r.ts_max),
                   "raw_meta_eq_table": all(_i(raw_tu.get(k)) == int(getattr(r, k)) for k in
                                            ("api_call_count", "input_tokens", "cache_creation_tokens", "cache_read_tokens", "output_tokens")),
                   "other_sessions_with_this_full_tally": [x for x in full_tuple.get(key, []) if x != r.session_id]}
            if fmt == "claude":
                for k in TOK:
                    row[f"meta_minus_tx_{k}"] = int(getattr(r, SESS_TOK[k])) - int(getattr(r, f"F0_tx_{k}"))
                row.update({"F0_cls_noout": r.F0_cls_noout, "F2_full": bool(r.F2_full), "n_sub_msgs": int(r.n_sub_msgs),
                            "file_sessionId_present": bool(r.file_sessionId_present), "n_distinct_sessionId": int(r.n_distinct_sessionId),
                            "has_ctx_start": r.raw.get("checkpoint_transcript_start") is not None})
            elif fmt in ("opencode", "gemini"):
                row[f"{pre}_cls_noout"] = getattr(r, f"{pre}_cls_noout")
            none_rows.append(row)
    X["unmatched_tally_sessions"] = none_rows
    X["unmatched_by_fmt"] = dict(Counter(r["fmt"] for r in none_rows))
    X["unmatched_with_other_session_full_tally"] = int(sum(bool(r["other_sessions_with_this_full_tally"]) for r in none_rows))
    X["unmatched_claude_tx_msgs_lt_api"] = int(sum(1 for r in none_rows if r["fmt"] == "claude" and r["tx_msgs"] is not None and r["tx_msgs"] < r["api_meta"]))
    X["unmatched_claude_file_sessionId_absent"] = int(sum(1 for r in none_rows if r["fmt"] == "claude" and not r["file_sessionId_present"]))
    X["unmatched_raw_meta_ne_table"] = int(sum(1 for r in none_rows if not r["raw_meta_eq_table"]))
    X["unmatched_by_cli_version"] = dict(Counter(r["cli_version"] for r in none_rows))
    X["unmatched_by_repo_top"] = Counter(r["repo_id"] for r in none_rows).most_common(10)
    X["unmatched_n_distinct_repos"] = len({r["repo_id"] for r in none_rows})
    # own sessionId absent from the records of its transcript file
    clf = M[M.fmt == "claude"]
    absent = ~clf.file_sessionId_present.fillna(True).astype(bool)
    X["claude_file_sessionId_absent_total"] = int(absent.sum())
    X["claude_file_sessionId_absent_by_F0"] = clf[absent].F0_cls.value_counts(dropna=False).to_dict()
    X["claude_file_sessionId_absent_by_agent"] = clf[absent].agent.value_counts().to_dict()
    # sessions table vs raw metadata mismatch: shape and rescan with the raw values
    mm = []
    for r in M.itertuples(index=False):
        tu = r.raw.get("token_usage")
        if not isinstance(tu, dict):
            continue
        raw5 = {"api": _i(tu.get("api_call_count")), "in": _i(tu.get("input_tokens")), "cc": _i(tu.get("cache_creation_tokens")),
                "cr": _i(tu.get("cache_read_tokens")), "out": _i(tu.get("output_tokens"))}
        tab5 = {k: int(getattr(r, SESS_TOK[k])) for k in TOK}
        if raw5 != tab5:
            mm.append((r, raw5, tab5))
    rescans = []
    for r, raw5, tab5 in mm:
        meta = dict(raw5)
        meta["files"] = []
        o = scan_one((r.session_id, f"{D}/transcripts/{r.session_id}.jsonl", meta))
        pre = {"claude": "F0", "codex": "X0", "opencode": "O0", "gemini": "G0"}.get(o.get("fmt"))
        rescans.append({"session_id": r.session_id, "agent": r.agent, "fmt": o.get("fmt"),
                        "table_cls": getattr(r, f"{pre}_cls", None) if pre else None, "raw_cls": o.get(f"{pre}_cls") if pre else None,
                        "out_table_minus_raw": tab5["out"] - raw5["out"], "api_table_minus_raw": tab5["api"] - raw5["api"],
                        "raw_api_zero": raw5["api"] == 0, "n_checkpoint_ids": int(r.n_checkpoint_ids)})
    X["table_vs_raw_metadata_mismatch"] = {"n": len(mm), "rows": rescans,
                                           "n_table_out_gt_raw": int(sum(x["out_table_minus_raw"] > 0 for x in rescans)),
                                           "n_table_out_lt_raw": int(sum(x["out_table_minus_raw"] < 0 for x in rescans)),
                                           "n_multi_checkpoint": int(sum(x["n_checkpoint_ids"] > 1 for x in rescans)),
                                           "raw_cls_counts": dict(Counter(str(x["raw_cls"]) for x in rescans)),
                                           "table_cls_counts": dict(Counter(str(x["table_cls"]) for x in rescans))}
    # duration_seconds alternatives
    d = {}
    for lab, a, b_ in (("all_records_span", "ts_min", "ts_max"), ("user_assistant_records_span", "tsm_min", "tsm_max")):
        sub = M[M.duration_seconds.notna() & M[a].notna()]
        span = sub[b_] - sub[a]
        diff = (sub.duration_seconds - span).abs()
        d[lab] = {"exact_1ms": W(int((diff <= 0.001).sum()), len(sub)), "near_1s": W(int((diff <= 1).sum()), len(sub)),
                  "duration_lt_span": int((sub.duration_seconds < span - 0.001).sum()),
                  "duration_gt_span": int((sub.duration_seconds > span + 0.001).sum()),
                  "ratio_duration_over_span": stats.describe((sub.duration_seconds / span.replace(0, np.nan)).dropna().values)}
    X["duration_alternatives"] = d
    # builder tool_call_count vs last-record-per-message hypothesis
    sub = M[(M.fmt == "claude") & M.tool_call_count.notna() & M.n_tool_use_ids_lastrec.notna()]
    X["tool_call_count_vs_raw"] = {"n": len(sub),
                                   "eq_all_distinct_tool_use_ids": W(int((sub.tool_call_count == sub.n_tool_use_ids).sum()), len(sub)),
                                   "eq_tool_ids_in_last_record_per_message": W(int((sub.tool_call_count == sub.n_tool_use_ids_lastrec).sum()), len(sub)),
                                   "eq_tool_ids_in_first_record_per_message": W(int((sub.tool_call_count == sub.n_tool_use_ids_firstrec).sum()), len(sub)),
                                   "pooled_dropped_share": stats.cluster_rate((sub.n_tool_use_ids - sub.tool_call_count).clip(lower=0).values, sub.n_tool_use_ids.values),
                                   "shape_vs_lastrec": diff_shape(sub.tool_call_count, sub.n_tool_use_ids_lastrec, sub.session_id)}
    # write paths inside the session cwd vs files_touched
    sub = M[(M.fmt == "claude") & M.n_write_paths_in_cwd.notna() & (M.n_ft > 0) & (M.n_write_paths_in_cwd > 0)]
    X["files_touched_vs_in_cwd_write_paths"] = {"n": len(sub),
                                                "all_in_cwd_paths_in_ft": W(int((sub.n_write_paths_in_cwd_in_ft == sub.n_write_paths_in_cwd).sum()), len(sub)),
                                                "all_ft_covered_by_in_cwd_paths": W(int((sub.n_ft_covered_by_in_cwd == sub.n_ft).sum()), len(sub)),
                                                "pooled_in_cwd_paths_in_ft": stats.cluster_rate(sub.n_write_paths_in_cwd_in_ft.values, sub.n_write_paths_in_cwd.values),
                                                "pooled_out_of_cwd_share_of_write_paths": stats.cluster_rate((sub.n_write_paths - sub.n_write_paths_in_cwd).values, sub.n_write_paths.values)}
    # spikes: are the repeated values shared within one checkpoint / repo?
    sp = {}
    P1 = J["part1_distributions"]
    for grp in ["Claude Code", "OpenCode", "Codex", "Gemini CLI", "other"]:
        sub = S[S.agent_grp == grp]
        for c in SESSION_NUMERIC:
            prof = P1.get(grp, {}).get(c, {})
            for spk in (prof.get("spikes") or [])[:5]:
                x = sub[sub[c] == spk["value"]]
                sp[f"{grp}|{c}|{spk['value']:g}"] = {"n": len(x), "n_canonical_checkpoints": int(x.canonical_checkpoint_pk.nunique()),
                                                     "n_repos": int(x.repo_id.nunique()), "n_users": int(x.user_id.nunique()),
                                                     "n_distinct_attribution_calculated_at": int(x.attribution_calculated_at.nunique())}
    X["spike_membership"] = sp
    # codex turn_count == 12 cluster
    cx12 = S[(S.agent == "Codex") & (S.turn_count == 12)]
    X["codex_turn_count_12"] = {"n": len(cx12), "n_repos": int(cx12.repo_id.nunique()), "n_users": int(cx12.user_id.nunique()),
                                "n_canonical_checkpoints": int(cx12.canonical_checkpoint_pk.nunique()),
                                "n_distinct_output_tokens": int(cx12.output_tokens.nunique())}
    # duplicate checkpoint token tuples
    cpk = ["cp_api_call_count", "cp_input_tokens", "cp_cache_creation_tokens", "cp_cache_read_tokens", "cp_output_tokens"]
    cc_ = C[C.cp_output_tokens > 0]
    g = cc_.groupby(cpk)
    sz = g.size()
    dupk = sz[sz > 1]
    same_pks = g.session_pks.nunique().loc[dupk.index]
    same_repo = g.repo_id.nunique().loc[dupk.index]
    X["checkpoint_duplicate_token_tuples"] = {"n_checkpoints_output_gt0": len(cc_), "n_groups": int(len(dupk)), "n_checkpoints_in_groups": int(dupk.sum()),
                                              "largest_group_sizes": sorted(dupk.tolist(), reverse=True)[:10],
                                              "groups_identical_session_pks": int((same_pks == 1).sum()), "groups_single_repo": int((same_repo == 1).sum())}
    same_cpid = g.checkpoint_id.nunique().loc[dupk.index]
    X["checkpoint_duplicate_token_tuples"]["groups_single_checkpoint_id"] = int((same_cpid == 1).sum())
    X["checkpoint_duplicate_token_tuples"]["groups_multi_checkpoint_id_identical_session_pks"] = int(((same_cpid > 1) & (same_pks == 1)).sum())
    rid = C.groupby("checkpoint_id").repo_id.nunique()
    multi = rid[rid > 1]
    pairs = Counter(tuple(sorted(C[C.checkpoint_id == cid].repo_id.unique())) for cid in multi.index)
    X["checkpoint_id_in_multiple_repos"] = {"n_checkpoint_ids": int(C.checkpoint_id.nunique()), "n_in_multiple_repos": int(len(multi)),
                                            "n_checkpoint_rows_involved": int(C.checkpoint_id.isin(multi.index).sum()),
                                            "share_of_checkpoint_rows": W(int(C.checkpoint_id.isin(multi.index).sum()), len(C)),
                                            "repo_sets": [[list(k), v] for k, v in pairs.most_common(10)],
                                            "n_repo_sets": len(pairs)}
    if len(dupk):
        key = dupk.sort_values(ascending=False).index[0]
        grpdf = cc_.set_index(cpk).loc[[key]]
        pk_sets = [set(json.loads(x)) for x in grpdf.session_pks]
        inter = set.intersection(*pk_sets) if pk_sets else set()
        canon_here = S[S.session_id.isin(inter) & S.canonical_checkpoint_pk.isin(set(grpdf.checkpoint_pk))]
        X["checkpoint_duplicate_largest_group"] = {"size": len(grpdf), "n_sessions_common_to_all": len(inter),
                                                   "commit_count_values": Counter(grpdf.commit_count.tolist()).most_common(5),
                                                   "session_count_values": Counter(grpdf.session_count.tolist()).most_common(5),
                                                   "n_common_sessions_canonical_in_group": len(canon_here),
                                                   "n_repos": int(grpdf.repo_id.nunique())}
    # shared content hash
    ch = S.content_hash.value_counts()
    X["shared_content_hash"] = [{"hash_prefix": h[:24], "n": int(n), "agents": S[S.content_hash == h].agent.value_counts().to_dict(),
                                 "api_zero": int((S[S.content_hash == h].api_call_count == 0).sum()),
                                 "n_repos": int(S[S.content_hash == h].repo_id.nunique())} for h, n in ch[ch > 1].items()]
    # duplicate session token tuple detail
    tk = S[S.output_tokens > 0]
    grp5 = tk.groupby(["input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens", "api_call_count"]).session_id.apply(list)
    Mi = M.set_index("session_id")
    X["session_duplicate_token_tuple_detail"] = [{"session_ids": v, "fmt": [Mi.at[x, "fmt"] for x in v], "F0_cls": [Mi.at[x, "F0_cls"] for x in v],
                                                  "canonical_checkpoints": [Mi.at[x, "canonical_checkpoint_pk"] for x in v],
                                                  "n_msgs": [Mi.at[x, "n_msgs"] for x in v]} for v in grp5 if len(v) > 1]
    # sessions whose harness tally is zero
    z = M[M.api_call_count == 0]
    X["api_zero"] = {"n": len(z), "has_token_usage_key": int(z.raw.map(lambda d: isinstance(d.get("token_usage"), dict)).sum()),
                     "by_cli_version": z.cli_version.value_counts().head(10).to_dict(), "by_fmt": z.fmt.value_counts(dropna=False).to_dict(),
                     "tx_msgs_gt0": int((z.n_msgs > 0).sum()),
                     "created_month": z.created_at.dt.strftime("%Y-%m").value_counts().to_dict()}
    # outlier sensitivity: Claude Code population without the sessions whose harness tally is absent (api == 0)
    pop = M[(M.agent == "Claude Code") & (M.fmt == "claude") & (M.api_call_count > 0)]
    Zs, used, dropped = robust_z(pop)
    ext = Zs.abs() > thr
    n_ext = ext.sum(axis=1)
    isout = n_ext >= 3
    O = pop[isout]
    combos = Counter(tuple(sorted(f"{c}{'+' if Zs.at[i, c] > 0 else '-'}" for c in Zs.columns if ext.at[i, c])) for i in O.index)
    X["outliers_claude_code_api_pos"] = {"n": len(pop), "features_used": used, "n_features_used": len(used), "n_outliers": int(isout.sum()), "outlier_rate": W(int(isout.sum()), len(pop)),
                                         "n_extreme_features_hist": n_ext.value_counts().sort_index().to_dict(),
                                         "feature_extreme_counts_in_outliers": {c: {"high": int((Zs.loc[isout, c] > thr).sum()), "low": int((Zs.loc[isout, c] < -thr).sum())} for c in Zs.columns},
                                         "top_combos": [[list(k), v] for k, v in combos.most_common(12)],
                                         "F0_in_outliers": O.F0_cls.value_counts().to_dict(), "F0_in_population": pop.F0_cls.value_counts().to_dict(),
                                         "repo_top_outliers": O.repo_id.value_counts().head(8).to_dict(),
                                         "repo_share_population": {k: W(int((pop.repo_id == k).sum()), len(pop)) for k in O.repo_id.value_counts().head(5).index},
                                         "repo_share_outliers": {k: W(int((O.repo_id == k).sum()), len(O)) for k in O.repo_id.value_counts().head(5).index},
                                         "n_distinct_repos_outliers": int(O.repo_id.nunique()),
                                         "cli_version_outliers": O.cli_version.value_counts().head(8).to_dict(),
                                         "created_month_outliers": O.created_at.dt.strftime("%Y-%m").value_counts().to_dict(),
                                         "created_month_population": pop.created_at.dt.strftime("%Y-%m").value_counts().to_dict(),
                                         "user_persona_outliers": O.user_persona.value_counts().to_dict(),
                                         "user_persona_population": pop.user_persona.value_counts().to_dict(),
                                         "session_success_outliers": stats.describe(O.session_success.dropna().values),
                                         "session_success_population": stats.describe(pop.session_success.dropna().values),
                                         "n_records_outliers": stats.describe(O.n_records.values), "n_records_population": stats.describe(pop.n_records.values),
                                         "n_unmatched_tally_in_outliers": int((O.F0_cls == "none").sum()),
                                         "n_unmatched_tally_in_population": int((pop.F0_cls == "none").sum())}
    mism_ids = {x["session_id"] for x in rescans}
    un = pop.F0_cls == "none"
    X["outliers_claude_code_api_pos"]["outlier_rate_among_unmatched"] = W(int((isout & un).sum()), int(un.sum()))
    X["outliers_claude_code_api_pos"]["outlier_rate_among_matched"] = W(int((isout & ~un).sum()), int((~un).sum()))
    X["outliers_claude_code_api_pos"]["unmatched_outliers_with_table_ne_raw"] = int((isout & un & pop.session_id.isin(mism_ids)).sum())
    tnr = pop.session_id.isin(mism_ids)
    X["outliers_claude_code_api_pos"]["outlier_rate_among_table_ne_raw"] = W(int((isout & tnr).sum()), int(tnr.sum()))
    # classes after substituting the raw-metadata rescan for sessions whose sessions-table tally differs from session_logs metadata
    raw_cls = {x["session_id"]: x["raw_cls"] for x in rescans}
    corr = {}
    for fmt, pre, base in (("claude", "F0", ["full", "prefix", "window", "none"]), ("codex", "X0", ["full", "prefix", "none", "tokens_at_other_k"]),
                           ("opencode", "O0", ["full", "prefix", "window", "none"]), ("gemini", "G0", ["full", "prefix", "window", "none"])):
        sub = M[(M.fmt == fmt) & M.raw.map(lambda d: isinstance(d.get("token_usage"), dict)) & (M.api_call_count > 0) & M[f"{pre}_cls"].notna()]
        cls = sub.apply(lambda r: raw_cls.get(r.session_id, r[f"{pre}_cls"]), axis=1)
        vc = cls.value_counts().to_dict()
        corr[fmt] = {"n": len(sub), **{c: W(vc.get(c, 0), len(sub)) for c in base},
                     "matched_any": W(int(cls.isin(["full", "prefix", "window"]).sum()), len(sub)),
                     "n_substituted": int(sub.session_id.isin(raw_cls).sum())}
    tot_n = sum(v["n"] for v in corr.values())
    tot_m = sum(v["matched_any"]["k"] for v in corr.values())
    corr["all_formats"] = {"matched_any": W(tot_m, tot_n), "unmatched": W(tot_n - tot_m, tot_n)}
    X["classes_using_session_logs_metadata"] = corr
    resid = [r for r in none_rows if r["raw_meta_eq_table"]]
    X["residual_unmatched"] = {"n": len(resid), "by_fmt": dict(Counter(r["fmt"] for r in resid)),
                               "claude_noout_class": dict(Counter(r.get("F0_cls_noout") for r in resid if r["fmt"] == "claude")),
                               "opencode_noout_class": dict(Counter(r.get("O0_cls_noout") for r in resid if r["fmt"] == "opencode")),
                               "gemini_noout_class": dict(Counter(r.get("G0_cls_noout") for r in resid if r["fmt"] == "gemini")),
                               "tx_msgs_gt_api": int(sum(1 for r in resid if r["tx_msgs"] is not None and r["tx_msgs"] > r["api_meta"])),
                               "tx_msgs_lt_api": int(sum(1 for r in resid if r["tx_msgs"] is not None and r["tx_msgs"] < r["api_meta"])),
                               "tx_msgs_eq_api": int(sum(1 for r in resid if r["tx_msgs"] is not None and r["tx_msgs"] == r["api_meta"])),
                               "n_repos": len({r["repo_id"] for r in resid}),
                               "top_repos": Counter(r["repo_id"] for r in resid).most_common(5)}
    # files_touched vs (tool-edited in-cwd paths) x (files changed in the canonical checkpoint's commits)
    import pyarrow.parquet as _pq
    kc = _pq.read_table(f"{D}/commits.parquet", columns=["checkpoint_pk", "files_changed"]).to_pandas()
    cfiles = {}
    for cp_, fc in zip(kc.checkpoint_pk, kc.files_changed):
        st = cfiles.setdefault(cp_, set())
        if isinstance(fc, str):
            for ln in fc.splitlines():
                st.update(x for x in ln.split("\t")[1:] if x)
    tab = Counter()
    ft_tab = Counter()
    n_sess = n_sub = 0
    per = []  # per session: (edited paths agreeing with "in ft iff committed", edited paths, ft entries edited, ft entries)
    sub = M[(M.fmt == "claude") & M.write_paths_rel_json.notna()]
    for r in sub.itertuples(index=False):
        com = cfiles.get(r.canonical_checkpoint_pk)
        if not com:
            continue
        ft = set(json.loads(r.files_touched or "[]"))
        n_sess += 1
        n_sub += ft <= com
        for pth in json.loads(r.write_paths_rel_json):
            tab[(pth in ft, pth in com)] += 1
        ed = set(json.loads(r.write_paths_rel_json))
        for f_ in ft:
            ft_tab[(f_ in ed, f_ in com)] += 1
        per.append((sum((q in ft) == (q in com) for q in ed), len(ed), sum(f_ in ed for f_ in ft), len(ft)))
    X["files_touched_vs_edits_and_commits"] = {
        "hypothesis_declared_before_computing": "files_touched = tool-edited paths that were also committed in the canonical checkpoint",
        "n_sessions_with_commit_files": n_sess, "files_touched_subset_of_commit_files": W(n_sub, n_sess),
        "edited_paths_2x2": {"in_ft_and_committed": tab[(True, True)], "in_ft_not_committed": tab[(True, False)],
                             "not_in_ft_committed": tab[(False, True)], "not_in_ft_not_committed": tab[(False, False)]},
        "ft_entries_2x2": {"edited_and_committed": ft_tab[(True, True)], "edited_not_committed": ft_tab[(True, False)],
                           "not_edited_committed": ft_tab[(False, True)], "not_edited_not_committed": ft_tab[(False, False)]}}
    e2 = X["files_touched_vs_edits_and_commits"]["edited_paths_2x2"]
    X["files_touched_vs_edits_and_commits"]["edited_path_in_ft_iff_committed_pooled_paths"] = W(e2["in_ft_and_committed"] + e2["not_in_ft_not_committed"], sum(e2.values()))
    pa = np.array(per, dtype=float).reshape(-1, 4)
    X["files_touched_vs_edits_and_commits"]["edited_path_in_ft_iff_committed_session_clustered"] = stats.cluster_rate(pa[:, 0], pa[:, 1])
    X["files_touched_vs_edits_and_commits"]["ft_entry_was_tool_edited_session_clustered"] = stats.cluster_rate(pa[:, 2], pa[:, 3])
    # provider cache granularity as an explanation for round-number excess in cache_read tokens (post hoc)
    gran = {}
    for grp in ["Claude Code", "OpenCode", "Codex", "Gemini CLI"]:
        v = S.loc[(S.agent_grp == grp) & (S.cache_read_tokens >= 100), "cache_read_tokens"].values
        gran[grp] = {f"div{k}": {**W(int((v % k == 0).sum()), len(v)), "expected_if_uniform": 1.0 / k} for k in (10, 64, 128)}
    X["cache_read_tokens_granularity"] = gran
    X["files_touched_vs_edits_and_commits"]["sessions_all_edited_paths_agree"] = W(int(((pa[:, 0] == pa[:, 1]) & (pa[:, 1] > 0)).sum()), int((pa[:, 1] > 0).sum()))
    J["followup"] = X


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all", choices=["all", "tx", "conv", "report"])
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=None, help="tx only: scan the N smallest transcripts (smoke test)")
    a = ap.parse_args()
    if a.stage in ("all", "tx"):
        stage_tx(a.workers, a.limit)
    if a.stage in ("all", "conv"):
        stage_conv()
    if a.stage in ("all", "report"):
        stage_report()


if __name__ == "__main__":
    main()
