"""agentcap loader: dacorvo/* agentcap releases (data/acquired/agentcap-dacorvo, 9 pinned HF repos, Apache-2.0) ->
common event IR. Native OpenCode and Pi session traces, joined per API call to the HTTP wire captures of the same runs.

Run from the worktree root:
  PYTHONIOENCODING=utf-8 python -m analysis.loaders.load_agentcap             census + splits + A cache + A calibration
  PYTHONIOENCODING=utf-8 python -m analysis.loaders.load_agentcap --split B   (NEXT step only)
  PYTHONIOENCODING=utf-8 python -m analysis.loaders.load_agentcap --split E   (NEXT step only)
  PYTHONIOENCODING=utf-8 python -m analysis.loaders.load_agentcap --selftest  rebuild A via the --split path, compare
main() is idempotent.

SOURCES (read-only; README.md / .gitattributes / .cache skipped)
  traces   dacorvo__<suite>-session-opencode-traces@*/data/<run_id>/ses_*.json   OpenCode export documents
           dacorvo__<suite>-session-pi-traces@*/data/<run_id>/<iso>_<uuid>.jsonl  Pi session JSONL v3
  captures dacorvo__<suite>-session-captures@*/data/*.parquet: one row per /v1/chat/completions call made through the
           agentcap capture proxy: run_id, request_id (proxy-minted UUID), captured_at (epoch s, integer), task_id
           (task_01..task_30), turn (1..4), request (JSON), response (JSON or {"stream": true, "raw": <SSE text>}),
           served_by, served_build_info, served_model, provider, upstream_url, label.
  Suites: hf-hub, transformers-coding, funes-recall. Models are local GGUF models behind a local server, or the HF
  Router (run ids '*-hf-router-*').

FIELD AUDIT AND POPULATION (header-only census; no event parsed before the split)
  OpenCode: only the document's `info` object is decoded (raw_decode from the head of the file); session_id =
  info.id, falling back to the file stem when the info object does not decode inside the first 64 KB.
  0-byte files fail the audit: 2 OpenCode files (they are the 2 'undecodable' OpenCode files of the B5e audit).
  SPLIT INCIDENT (recorded, see analysis/out/phase_e/newcorp_split_incident_agentcap.json): the first build drew the
  split before the 0-byte check existed (N = 806, both empty files in A) and parsed that A into the A cache (since
  overwritten); a second build drew N = 804 correctly. Sessions parsed under the abandoned draw(s) that now sit in
  B / E / H are listed there (B and E ids; H count and sha256 only) so the next step can exclude them. Only aggregate
  counts of those parses were looked at; no per-session value of them was inspected.
  Pi: only the first line is decoded; it must be {type: session, id}; session_id = its id.
  stratum = '<agent>/<route>' from the run folder name: opencode/local, opencode/hf-router, pi/local, pi/hf-router.
  length = file bytes (OpenCode, one JSON document) or non-empty line count (Pi). The population table
  (analysis/cache/agentcap_population.parquet) also keeps run_id, suite, created (header), task rank, source path.

EVENT MAPPING
  OpenCode documents: load_swechat.parse_opencode, imported and called unchanged (mapping in its module docstring:
    text/tool/step-finish parts; call ts = state.time.start, result ts = state.time.end (harness-measured execution
    window, epoch ms); usage on step-finish meta rows keyed by message id).
  Pi JSONL (no parser existed; written here, mapping decisions):
    {type: session}            -> meta (extra: version, cwd basename only).
    {type: message, message: {role: user}}       -> user (text = text blocks joined; images -> "[image]").
    {type: message, message: {role: assistant}}  -> assistant for each non-empty text block, then one call per
        toolCall block (call_id = block.id, tool_raw = block.name, args = block.arguments re-serialized). thinking
        blocks -> extra.thinking_chars of the next assistant/call event. usage (input/output/cacheRead/cacheWrite) goes
        on ONE meta row per assistant message after its blocks (same convention as OpenCode step-finish), with
        api_msg_id = message.responseId (synthetic 'synthetic:pi:<session>:m<entry index>' when absent). model =
        message.model; extra: provider, api, stopReason, responseId.
    {type: message, message: {role: toolResult}} -> result (call_id = toolCallId, text = text blocks joined,
        native_error = isError (bool), extra: small scalar fields of details).
    other entry types (model_change, thinking_level_change, compaction, custom, ...) -> meta with entry_type
        (compaction summary -> system text).
    ts: the entry's ISO timestamp (ms, Z). Pi also stores message.timestamp (epoch ms); it is kept in extra.msg_ts_ms
        when it differs from the entry stamp by more than 1 ms. Every event ts_kind='event'.
    Pi records the assistant message when the response completes, and the tool result when the tool returns: the
    call's ts is therefore the end of the response that issued it (as in Claude Code), not the tool start.
    Pi details.exitCode (when an int) -> exit_code; native_error = toolResult.isError only.
  Capture join (the second witness; per API call). Only capture rows of the tasks of the sessions being built are
  read (pyarrow filter on run_id + task_id); bodies of other tasks are never decoded.
    task mapping  The capture parquet's schema metadata 'tasks' lists {id: task_NN, prompt} per file (file-level
      metadata, not row content). A session maps to (run_id, task_id) when its first user message equals a task
      prompt of a capture file of its run (whitespace-normalised). No match -> no join (counted:
      sessions_no_prompt_match). A (run, task) claimed by two sessions of the split -> no join (counted). The rank
      mapping (sessions ordered by header creation time = task_01..task_NN, only for runs whose session count equals
      the capture task count) is a cross-check only (rank_map_agrees / _disagrees / _unavailable).
      Capture rows of the task whose request's first user message differs from the session's are dropped
      (capture_rows_first_user_mismatch; OpenCode also sends side requests such as session-title generation).
    call mapping  The task's rows are ordered by (turn, captured_at, number of request messages).
      Pi: an assistant message joins the capture whose response id (SSE chunk `id`) equals message.responseId (exact).
      OpenCode (the trace has no response id): a message joins the capture whose streamed tool_calls ids contain the
      message's tool callIDs (exact; a message whose ids span two captures is not joined). Remaining messages join
      positionally only when the session's message count equals the task's capture row count. Counted per method.
    request_id column = the response id from the joined capture body (e.g. 'chatcmpl-...'), set on the joined
      message's assistant/call rows and its usage meta row. extra.capture = {proxy_request_id, captured_at_s,
      resp_created_first_s, resp_created_last_s (integer `created` of the first/last chunk), served_by, provider,
      task_id, turn, join method, server_timings (llama.cpp prompt_n/prompt_ms/predicted_n/predicted_ms/cache_n),
      server_usage, stream}. Nothing else is copied from captures: request bodies, headers and upstream URLs are not
      stored (no credentials).
    These ids are minted by a local llama.cpp-style server or the HF Router, not by a first-party model provider
    (CORPUS_INVENTORY 5.0: 'chatcmpl-' ids from an operator's server are operator-side), they embed no clock, and
    `created` is integer seconds: the witness is coarse (1 s) and operator-side. Pi message.timestamp (epoch ms) is
    the request start (it precedes the entry stamp, which is the response end); kept as extra.request_start_ms.
  Secrets: every IR string passes through newcorp_common.redact (counts in the build report). OpenCode info and Pi
  headers keep no environment, cwd is reduced to its basename.

CALIBRATION
  OpenCode sessions -> calibrate_unit(corpus='agentcap', unit='swechat/opencode'); Pi sessions have no pre-registered
  analogue: calibrate_unit(corpus='agentcap', unit='agentcap/pi') (generic rules: no error definition, not in the
  N1/N5 unit lists). Written as two units in one calibration file.
"""
import argparse
import collections
import glob
import json
import os
import re
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from analysis.lib import ir
from analysis.loaders import load_swechat as sw
from analysis.loaders import newcorp_common as nc

CORPUS = "agentcap"
SRC = nc.DATA / "agentcap-dacorvo"
LOADER = "analysis/loaders/load_agentcap.py"
UNITS_AS = {"opencode": "swechat/opencode", "pi": "agentcap/pi"}
_DEC = json.JSONDecoder()


# ------------------------------------------------------------------------------------------------------------ census
def _oc_header(path):
    h = open(path, "rb").read(65536).decode("utf-8", "replace")
    m = re.search(r'"info"\s*:\s*', h)
    if not m:
        return None
    try:
        info, _ = _DEC.raw_decode(h, m.end())
        return info if isinstance(info, dict) else None
    except ValueError:
        return None


def census():
    rows, fails, empty_oc = [], collections.Counter(), []
    for f in sorted(glob.glob(str(SRC / "*-opencode-traces@*" / "data" / "*" / "*.json"))):
        if os.path.getsize(f) == 0:
            fails["opencode_empty_file"] += 1
            empty_oc.append(Path(f).stem)
            continue
        info = _oc_header(f)
        stem = Path(f).stem
        sid = (info or {}).get("id") or stem
        if info is None:
            fails["opencode_info_undecodable_in_head_id_from_filename"] += 1
        tm = (info or {}).get("time") or {}
        rows.append({"session_id": str(sid), "agent": "opencode", "path": f, "created_ms": tm.get("created"),
                     "parent": (info or {}).get("parentID"), "length": os.path.getsize(f), "header_ok": info is not None,
                     "empty_file": False})
    for f in sorted(glob.glob(str(SRC / "*-pi-traces@*" / "data" / "*" / "*.jsonl"))):
        if os.path.getsize(f) == 0:
            fails["pi_empty_file_skipped"] += 1
            continue
        with open(f, "rb") as fh:
            first = fh.readline()
            n = (1 if first.strip() else 0) + sum(1 for line in fh if line.strip())
        try:
            d = json.loads(first)
        except ValueError:
            fails["pi_first_line_not_json"] += 1
            continue
        if not (isinstance(d, dict) and d.get("type") == "session" and d.get("id")):
            fails["pi_first_line_not_session"] += 1
            continue
        t = ir.parse_ts(sw.to_iso(d.get("timestamp")))
        rows.append({"session_id": str(d["id"]), "agent": "pi", "path": f,
                     "created_ms": t.timestamp() * 1000 if t else None, "parent": None, "length": n, "header_ok": True,
                     "empty_file": False})
    pop = pd.DataFrame(rows)
    pop["run_id"] = pop.path.map(lambda p: os.path.basename(os.path.dirname(p)))
    pop["suite"] = pop.path.map(lambda p: Path(p).parts[-4].split("__")[1].split("-session-")[0])
    pop["route"] = pop.run_id.map(lambda r: "hf-router" if "-hf-router-" in r else "local")
    pop["stratum"] = pop.agent + "/" + pop.route
    pop["source"] = pop.path.map(lambda p: Path(p).relative_to(nc.DATA).as_posix())
    dup = int(pop.session_id.duplicated().sum())
    pop = pop.sort_values(["session_id", "length"], ascending=[True, False]).drop_duplicates("session_id")
    # task rank within run by header creation time (metadata only)
    pop = pop.sort_values(["run_id", "created_ms", "session_id"]).reset_index(drop=True)
    pop["task_rank"] = pop.groupby("run_id").cumcount() + 1
    pop = pop.drop(columns=["path"]).sort_values("session_id").reset_index(drop=True)
    return pop, {"files_seen": len(rows) + sum(fails.values()), "fail_reasons": dict(fails),
                 "duplicate_session_ids_dropped": dup, "empty_opencode_file_ids": sorted(empty_oc)}


def capture_index():
    """Metadata columns of every capture row (no request/response bodies)."""
    out = []
    for f in sorted(glob.glob(str(SRC / "*-captures@*" / "data" / "*.parquet"))):
        t = pq.read_table(f, columns=["run_id", "task_id", "turn", "captured_at", "request_id"]).to_pandas()
        t["file"] = Path(f).relative_to(nc.DATA).as_posix()
        t["row"] = np.arange(len(t))
        out.append(t)
    return pd.concat(out, ignore_index=True)


def task_map(pop, cidx):
    """{session_id: (run_id, task_id)} for runs whose session count equals their capture task count."""
    tasks = cidx.groupby("run_id").task_id.nunique().to_dict()
    nses = pop.groupby("run_id").size().to_dict()
    ok_runs = {r for r in nses if tasks.get(r) == nses[r]}
    m = {}
    for sid, r, k in zip(pop.session_id, pop.run_id, pop.task_rank):
        if r in ok_runs:
            m[sid] = (r, f"task_{int(k):02d}")
    return m, {"runs": len(nses), "runs_session_count_eq_task_count": len(ok_runs),
               "runs_mismatched": {r: {"sessions": nses[r], "tasks": tasks.get(r)} for r in nses if r not in ok_runs}}


# ------------------------------------------------------------------------------------------------------------ captures
def _sse_fields(resp_text):
    """Response body -> {resp_id, created_first, created_last, tool_call_ids, timings, usage, n_chunks, stream}.
    Only ids, integer clocks, server timers and usage are extracted; content is not kept."""
    out = {"resp_id": None, "created_first": None, "created_last": None, "tool_call_ids": [], "timings": None,
           "usage": None, "n_chunks": 0, "stream": False}
    try:
        r = json.loads(resp_text)
    except (ValueError, TypeError):
        return out
    objs = []
    if isinstance(r, dict) and r.get("stream") and isinstance(r.get("raw"), str):
        out["stream"] = True
        for line in r["raw"].split("\n"):
            line = line.strip()
            if line.startswith("data:"):
                body = line[5:].strip()
                if body and body != "[DONE]":
                    try:
                        objs.append(json.loads(body))
                    except ValueError:
                        pass
    elif isinstance(r, dict):
        objs = [r]
    out["n_chunks"] = len(objs)
    for o in objs:
        if not isinstance(o, dict):
            continue
        if o.get("id") and out["resp_id"] is None:
            out["resp_id"] = str(o["id"])
        if isinstance(o.get("created"), (int, float)):
            out["created_first"] = o["created"] if out["created_first"] is None else out["created_first"]
            out["created_last"] = o["created"]
        if isinstance(o.get("timings"), dict):
            out["timings"] = {k: o["timings"].get(k) for k in ("prompt_n", "prompt_ms", "predicted_n", "predicted_ms",
                                                              "cache_n") if k in o["timings"]}
        if isinstance(o.get("usage"), dict):
            out["usage"] = {k: o["usage"].get(k) for k in ("prompt_tokens", "completion_tokens")}
        for ch in o.get("choices") or []:
            if not isinstance(ch, dict):
                continue
            msg = ch.get("delta") or ch.get("message") or {}
            for tc in (msg.get("tool_calls") or []) if isinstance(msg, dict) else []:
                if isinstance(tc, dict) and tc.get("id") and tc["id"] not in out["tool_call_ids"]:
                    out["tool_call_ids"].append(str(tc["id"]))
    return out


def _first_user_text_of_request(req_text):
    try:
        req = json.loads(req_text)
    except (ValueError, TypeError):
        return None, 0
    msgs = req.get("messages") or []
    for m in msgs:
        if isinstance(m, dict) and m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, list):
                c = "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
            return c, len(msgs)
    return None, len(msgs)


def file_tasks(cidx):
    """{capture file: {task_id: prompt}} from parquet schema metadata (file-level, not row content)."""
    out = {}
    for f in sorted(cidx.file.unique()):
        md = pq.ParquetFile(nc.DATA / f).schema_arrow.metadata or {}
        try:
            out[f] = {t["id"]: t.get("prompt") for t in json.loads(md.get(b"tasks", b"[]"))}
        except ValueError:
            out[f] = {}
    return out


def load_captures(cidx, wanted):
    """wanted: {(run_id, task_id)} -> capture rows of exactly those tasks, with extracted id/clock fields."""
    rows = []
    sub = cidx[[(r, t) in wanted for r, t in zip(cidx.run_id, cidx.task_id)]]
    for f, g in sub.groupby("file"):
        runs = sorted(g.run_id.unique())
        tasks = sorted(g.task_id.unique())
        t = pq.read_table(nc.DATA / f, columns=["run_id", "task_id", "turn", "captured_at", "request_id", "request",
                                                "response", "served_by", "provider"],
                          filters=[("run_id", "in", runs), ("task_id", "in", tasks)]).to_pandas()
        t = t[[(r, k) in wanted for r, k in zip(t.run_id, t.task_id)]]
        for r in t.itertuples(index=False):
            fu, nmsg = _first_user_text_of_request(r.request)
            x = _sse_fields(r.response)
            rows.append({"run_id": r.run_id, "task_id": r.task_id, "turn": int(r.turn) if r.turn == r.turn else None,
                         "captured_at": int(r.captured_at), "proxy_request_id": r.request_id,
                         "served_by": r.served_by, "provider": r.provider, "n_req_msgs": nmsg,
                         "first_user": fu, **x})
    df = pd.DataFrame(rows)
    if len(df):
        df = df.sort_values(["run_id", "task_id", "turn", "captured_at", "n_req_msgs"]).reset_index(drop=True)
    return df


# ------------------------------------------------------------------------------------------------------------ Pi parser
def _pi_text(content):
    out = []
    items = content if isinstance(content, list) else ([{"type": "text", "text": content}] if isinstance(content, str) else [])
    for c in items:
        if isinstance(c, dict):
            if c.get("type") == "text":
                out.append(c.get("text") or "")
            elif c.get("type") == "image":
                out.append("[image]")
    return "\n".join(out)


def parse_pi(sid, stratum, text, stat):
    S = sw.Session(sid, stratum)
    model = None
    for i, d in enumerate(sw.iter_json_lines(text, stat)):
        if not isinstance(d, dict):
            continue
        typ = d.get("type")
        ts = d.get("timestamp")
        if typ == "session":
            S.emit("meta", ts, uuid=d.get("id"), extra={"entry_type": "session", "version": d.get("version"),
                                                        "cwd_basename": os.path.basename(str(d.get("cwd") or ""))})
            continue
        if typ != "message":
            ex = {"entry_type": typ}
            ex.update(sw.small_scalars(d, limit=120, skip=("type", "id", "parentId", "timestamp", "summary")))
            if typ == "model_change":
                model = d.get("modelId") or model
            if typ == "compaction" and isinstance(d.get("summary"), str):
                S.emit("system", ts, text=d["summary"], uuid=d.get("id"), parent_uuid=d.get("parentId"), extra=ex)
            else:
                S.emit("meta", ts, uuid=d.get("id"), parent_uuid=d.get("parentId"), extra=ex)
            continue
        m = d.get("message") if isinstance(d.get("message"), dict) else {}
        role = m.get("role")
        mts = m.get("timestamp")
        ent = ir.parse_ts(sw.to_iso(ts))
        dev = None
        if isinstance(mts, (int, float)) and ent is not None:
            dev = mts - ent.timestamp() * 1000
        base = {"uuid": d.get("id"), "parent_uuid": d.get("parentId")}
        if role == "user":
            ex = {"msg_ts_ms": mts} if dev is not None and abs(dev) > 1 else None
            S.emit("user", ts, text=_pi_text(m.get("content")), extra=ex, **base)
        elif role == "assistant":
            model = m.get("model") or model
            rid = m.get("responseId") if isinstance(m.get("responseId"), str) else None
            mid = rid or f"synthetic:pi:{sid}:m{i}"
            common = {"responseId": rid, "request_start_ms": mts, "provider": m.get("provider"), "api": m.get("api"),
                      "stopReason": m.get("stopReason")}
            for c in m.get("content") or []:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "thinking":
                    S.pending_thinking += len(c.get("thinking") or "")
                elif c.get("type") == "text" and (c.get("text") or "").strip():
                    S.emit("assistant", ts, text=c.get("text"), model=model, api_msg_id=mid, extra=dict(common), **base)
                elif c.get("type") == "toolCall":
                    a = c.get("arguments")
                    tool = sw.tool_norm(c.get("name"))
                    cid = c.get("id")
                    ex = dict(common)
                    if not cid:
                        cid = f"synthetic:pi:{len(S.events)}"
                        ex["synthetic_call_id"] = True
                    S.emit("call", ts, tool=tool, tool_raw=c.get("name"), call_id=cid, args=ir.j(a),
                           command=sw.shell_command(tool, a), model=model, api_msg_id=mid, extra=ex, **base)
            u = m.get("usage") if isinstance(m.get("usage"), dict) else {}
            ex = dict(common)
            ex["entry_type"] = "assistant_usage"
            if not rid:
                ex["synthetic_api_msg_id"] = True
            if isinstance(m.get("errorMessage"), str):
                ex["error_message_chars"] = len(m["errorMessage"])
            S.emit("meta", ts, usage_in=u.get("input"), usage_out=u.get("output"), usage_cache_read=u.get("cacheRead"),
                   usage_cache_create=u.get("cacheWrite"), model=model, api_msg_id=mid, extra=ex, **base)
        elif role == "toolResult":
            det = m.get("details") if isinstance(m.get("details"), dict) else {}
            ex = sw.small_scalars(det, limit=120, skip=("output", "diff", "content"))
            if dev is not None and abs(dev) > 1:
                ex["msg_ts_ms"] = mts
            ie = m.get("isError")
            xc = det.get("exitCode")
            ec = xc if isinstance(xc, int) and not isinstance(xc, bool) else None
            S.emit("result", ts, tool=sw.tool_norm(m.get("toolName")), tool_raw=m.get("toolName"),
                   call_id=m.get("toolCallId"), text=_pi_text(m.get("content")),
                   native_error=ie if isinstance(ie, bool) else None, exit_code=ec, extra=ex or None, **base)
        else:
            S.emit("meta", ts, extra={"entry_type": "message", "role": role}, **base)
    return S.events


# ------------------------------------------------------------------------------------------------------------ join
def _first_user(events):
    for e in events:
        if e["kind"] == "user" and isinstance(e["text"], str):
            return e["text"].strip()
    return None


def _messages(events, agent):
    """Ordered list of (api_msg_id, [event indexes]) for assistant API responses of the trace."""
    order, idx = [], {}
    for k, e in enumerate(events):
        mid = e["api_msg_id"]
        if mid is None or e["kind"] not in ("assistant", "call", "meta"):
            continue
        if agent == "opencode" and e["kind"] == "meta" and not (e["extra"] and '"part_type":"step-finish"' in e["extra"]):
            continue
        if mid not in idx:
            idx[mid] = len(order)
            order.append((mid, []))
        order[idx[mid]][1].append(k)
    return order


def join_session(events, agent, caps, jstat):
    """Attach capture ids to the trace's API responses. caps: capture rows of this session's task (ordered)."""
    msgs = _messages(events, agent)
    jstat["trace_responses"] += len(msgs)
    jstat["capture_rows"] += len(caps)
    if not len(caps) or not msgs:
        return
    by_id = {r.resp_id: r for r in caps.itertuples(index=False) if r.resp_id}
    by_tc = {}
    for r in caps.itertuples(index=False):
        for t in r.tool_call_ids:
            by_tc[t] = r
    matched = {}
    for mid, ks in msgs:
        r = None
        how = None
        if agent == "pi" and mid in by_id:
            r, how = by_id[mid], "response_id"
        elif agent == "opencode":
            cids = [events[k]["call_id"] for k in ks if events[k]["kind"] == "call"]
            hits = {id(by_tc[c]): by_tc[c] for c in cids if c in by_tc}
            if len(hits) == 1:
                r, how = next(iter(hits.values())), "tool_call_id"
            elif len(hits) > 1:
                jstat["opencode_message_tool_ids_span_captures"] += 1
        if r is not None:
            matched[mid] = (r, how)
    if agent == "opencode" and len(msgs) == len(caps):
        # positional fallback for messages without tool calls, only when every count agrees
        for (mid, ks), r in zip(msgs, caps.itertuples(index=False)):
            if mid not in matched:
                matched[mid] = (r, "positional")
            elif matched[mid][0].proxy_request_id != r.proxy_request_id:
                jstat["opencode_positional_disagrees_with_tool_id"] += 1
    used = collections.Counter(r.proxy_request_id for r, _ in matched.values())
    jstat["capture_rows_matched_more_than_once"] += sum(1 for v in used.values() if v > 1)
    for mid, ks in msgs:
        if mid not in matched:
            jstat["trace_responses_unjoined"] += 1
            continue
        r, how = matched[mid]
        jstat[f"joined_by_{how}"] += 1
        cap = {"proxy_request_id": r.proxy_request_id, "captured_at_s": r.captured_at, "resp_created_first_s":
               r.created_first, "resp_created_last_s": r.created_last, "served_by": r.served_by,
               "provider": r.provider, "task_id": r.task_id, "turn": r.turn, "join": how,
               "server_timings": r.timings, "server_usage": r.usage, "stream": r.stream}
        for k in ks:
            e = events[k]
            e["request_id"] = r.resp_id
            ex = json.loads(e["extra"]) if e["extra"] else {}
            ex["capture"] = cap
            e["extra"] = ir.j(ex)


# ------------------------------------------------------------------------------------------------------------ build
def _norm_prompt(s):
    return re.sub(r"\s+", " ", s).strip() if isinstance(s, str) else None


def build_split(split, out_path=None):
    """Parse the sessions of one split (A, B or E; never H) into an IR cache, joined to their own tasks' captures."""
    ids = sorted(nc.split_ids(CORPUS, split))
    pop = pd.read_parquet(nc.CACHE / f"{CORPUS}_population.parquet").set_index("session_id")
    cidx = capture_index()
    ftasks = file_tasks(cidx)
    run_files = cidx.groupby("run_id").file.unique().to_dict()
    red, stats, jstat = collections.Counter(), collections.Counter(), collections.Counter()
    parsed = {}
    for sid in ids:
        row = pop.loc[sid]
        stat = sw._new_stat()
        text, replaced = sw.read_text(str(nc.DATA / row["source"]))
        if row["agent"] == "opencode":
            ev = sw.parse_opencode(sid, row["stratum"], text, stat, {})
        else:
            ev = parse_pi(sid, row["stratum"], text, stat)
        sw.ensure_usage_ids(ev, row["agent"], sid, stat)
        stat["utf8_replaced"] = int(replaced)
        for k, v in stat.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                stats[f"{row['agent']}:{k}"] += v
            elif k == "doc":
                stats[f"{row['agent']}:doc_{v}"] += 1
        parsed[sid] = ev
    # task mapping by prompt (capture file metadata) -> (run, task); rank mapping kept as a cross-check only
    tmap, tm_info = task_map(pop.reset_index(), cidx)
    by_task = collections.defaultdict(list)
    for sid in ids:
        r = pop.loc[sid, "run_id"]
        fu = _norm_prompt(_first_user(parsed[sid]))
        hit = None
        for f in run_files.get(r, []):
            for tid, pr in ftasks.get(f, {}).items():
                if fu and _norm_prompt(pr) == fu:
                    hit = (r, tid)
        if hit is None:
            jstat["sessions_no_prompt_match"] += 1
            if r not in run_files:
                jstat["sessions_run_without_captures"] += 1
            continue
        by_task[hit].append(sid)
        rk = tmap.get(sid)
        jstat["rank_map_agrees" if rk == hit else ("rank_map_disagrees" if rk else "rank_map_unavailable")] += 1
    wanted = {k for k, v in by_task.items() if len(v) == 1}
    jstat["tasks_claimed_by_more_than_one_session"] = sum(1 for v in by_task.values() if len(v) > 1)
    caps = load_captures(cidx, wanted)
    jstat["capture_rows_loaded"] = int(len(caps))
    frames, nsur = [], 0
    for sid in ids:
        ev = parsed[sid]
        task = next((k for k in wanted if sid in by_task[k]), None)
        if task is not None:
            c = caps[(caps.run_id == task[0]) & (caps.task_id == task[1])]
            fu = _norm_prompt(_first_user(ev))
            ok = c.first_user.map(lambda x: _norm_prompt(x) == fu)
            jstat["capture_rows_first_user_mismatch"] += int((~ok).sum())
            jstat["sessions_joined_to_task"] += 1
            join_session(ev, pop.loc[sid, "agent"], c[ok].reset_index(drop=True), jstat)
        nc.redact_events(ev, red)
        df, ns = nc.session_frame(ev, CORPUS)
        nsur += ns
        frames.append(df)
    out_path = out_path or (nc.CACHE / f"{CORPUS}_{split}.parquet")
    info = nc.write_cache(frames, out_path)
    info.update({"split": split, "sessions_in_split": len(ids), "parser_stats": dict(stats), "join": dict(jstat),
                 "task_rank_map_runs": tm_info, "secret_redactions": dict(red), "surrogate_cells_replaced": nsur})
    return info


def selftest():
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


def witness_report(a):
    """Second-witness fill on A: joined responses and the clock relation between trace and capture (counts and
    quantiles only; no threshold, no detector)."""
    x = a[a.extra.notna() & a.extra.astype(str).str.contains('"capture":')]
    rows = []
    for sid, kind, ts, e in zip(x.session_id, x.kind, x.ts.astype(object), x.extra.astype(str)):
        ex = json.loads(e)
        cap = ex["capture"]
        t = ir.parse_ts(ts) if isinstance(ts, str) else None
        rows.append({"session_id": sid, "kind": kind, "join": cap.get("join"), "rid": cap.get("proxy_request_id"),
                     "end_s": t.timestamp() if t else None, "start_ms": ex.get("request_start_ms"),
                     "c_first": cap.get("resp_created_first_s"), "c_last": cap.get("resp_created_last_s"),
                     "captured_at": cap.get("captured_at_s"), "timings": cap.get("server_timings") is not None})
    W = pd.DataFrame(rows)
    out = {"rows_with_capture": int(len(x)), "sessions_with_capture": int(x.session_id.nunique()),
           "sessions_A": int(a.session_id.nunique())}
    if not len(W):
        return out
    r = W.drop_duplicates(["session_id", "rid"])
    out["joined_responses"] = int(len(r))
    out["joined_by"] = {k: int(v) for k, v in r["join"].value_counts().items()}
    out["responses_with_server_timings"] = int(r.timings.sum())
    out["request_id_rows_nonnull"] = int(a.request_id.notna().sum())
    d_end = (r.end_s - r.c_last).dropna()
    out["trace_end_minus_resp_created_last_s"] = {"n": int(len(d_end)), **{f"q{q}": float(np.quantile(d_end, q))
                                                                           for q in (0.01, 0.5, 0.99)}} if len(d_end) else {"n": 0}
    s = r.dropna(subset=["start_ms", "c_first"])
    d_st = s.c_first - s.start_ms / 1000.0
    out["resp_created_first_minus_request_start_s"] = {"n": int(len(d_st)), **{f"q{q}": float(np.quantile(d_st, q))
                                                                               for q in (0.01, 0.5, 0.99)}} if len(d_st) else {"n": 0}
    d_c = (r.captured_at - r.end_s).dropna()
    out["captured_at_minus_trace_end_s"] = {"n": int(len(d_c)), **{f"q{q}": float(np.quantile(d_c, q))
                                                                   for q in (0.01, 0.5, 0.99)}} if len(d_c) else {"n": 0}
    out["note"] = ("created is integer seconds from the serving process (llama.cpp-style server or HF Router); "
                   "captured_at is integer seconds from the capture proxy. Descriptive only, no threshold set here.")
    return out


def split_incident(pop, sp, empty_ids):
    """Sessions parsed into the A cache of the two earlier builds of this session's work that are not in the final A:
    build 1 drew with the 2 empty OpenCode files in the population (N = 806); build 2 is the final rule (N = 804) but
    a later build 3 re-drew with N = 806 again before the final one. Both earlier A draws are recomputed here exactly
    (same function, same seed) so the list is reproducible."""
    base = pop[["session_id", "stratum", "length"]]
    extra = pd.DataFrame([{"session_id": e, "stratum": None, "length": 0} for e in empty_ids])
    if len(extra):
        st = {e: ("opencode/hf-router" if "hf-router" in r else "opencode/local") for e, r in
              zip(empty_ids, [next((x for x in glob.glob(str(SRC / "*-opencode-traces@*" / "data" / "*" / (e + ".json")))), "")
                              for e in empty_ids])}
        extra["stratum"] = extra.session_id.map(st)
    s806 = nc.split_population(pd.concat([base, extra], ignore_index=True))
    seen = (set(s806["A"]) - set(empty_ids)) - set(sp["A"])
    B = sorted(seen & set(sp["B"]))
    E = sorted(seen & set(sp["E"]))
    H = sorted(seen & set(sp["H"]))
    doc = {"corpus": CORPUS, "what": "sessions parsed into an abandoned A cache (draw with N=806 incl. 2 empty files) "
                                     "that are in B/E/H of the final draw (N=804)",
           "abandoned_draw_A": len(s806["A"]), "final_A": len(sp["A"]),
           "seen_outside_final_A": len(seen), "B_ids": B, "E_ids": E, "n_H": len(H), "sha256_sorted_H_ids": nc.sha_ids(H),
           "exposure": "loader parse + aggregate counts in the abandoned build report and calibration (overwritten); "
                       "no per-session value inspected",
           "recommendation": "exclude B_ids/E_ids from B/E measurement or label results 'A-adjacent'; Track C should "
                             "drop these H sessions (match by the hash) or note them"}
    (nc.OUT_E / f"newcorp_split_incident_{CORPUS}.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return {k: doc[k] for k in ("abandoned_draw_A", "seen_outside_final_A", "n_H")} | {"n_B": len(B), "n_E": len(E),
                                                                                       "file": f"analysis/out/phase_e/newcorp_split_incident_{CORPUS}.json"}


def main():
    t0 = time.time()
    pop, audit = census()
    pop.to_parquet(nc.CACHE / f"{CORPUS}_population.parquet", index=False)
    sp = nc.split_population(pop[["session_id", "stratum", "length"]])
    sinfo = nc.write_splits(CORPUS, sp, LOADER)
    idx = nc.write_index(CORPUS, sp, pop)
    incident = split_incident(pop, sp, audit["empty_opencode_file_ids"])
    cidx = capture_index()
    a_info = build_split("A")
    a = pd.read_parquet(nc.CACHE / f"{CORPUS}_A.parquet")
    rep = nc.cache_report(a)
    agent_of = dict(zip(pop.session_id, pop.agent))
    rep["by_agent"] = {}
    for ag in ("opencode", "pi"):
        sub = a[a.session_id.map(agent_of) == ag]
        if len(sub):
            rep["by_agent"][ag] = nc.cache_report(sub)
    rep["second_witness"] = witness_report(a)
    rep["run_dominance_A"] = nc.cluster_dominance(a, dict(zip(pop.session_id, pop.run_id)))
    rep["suite_dominance_A"] = nc.cluster_dominance(a, dict(zip(pop.session_id, pop.suite)))
    a_sids = set(sp["A"])
    units = [(f"{CORPUS}/{ag}", UNITS_AS[ag], sorted(s for s in a_sids if agent_of[s] == ag)) for ag in ("opencode", "pi")]
    doc, ext = nc.calibrate(CORPUS, units, LOADER, sinfo)
    st = selftest()
    out = {"corpus": CORPUS, "loader": LOADER, "source": "data/acquired/agentcap-dacorvo",
           "population": {"N": int(len(pop)), "by_stratum": pop.stratum.value_counts().to_dict(),
                          "by_suite": pop.suite.value_counts().to_dict(), "runs": int(pop.run_id.nunique()),
                          "opencode_child_sessions": int(pop.parent.notna().sum()),
                          "header_ok": int(pop.header_ok.sum())},
           "split_incident": incident,
           "field_audit": {**audit, "passed": int(len(pop)),
                           "rule": "OpenCode: info object decodes (else id from file stem); Pi: first line {type: session, id}"},
           "captures_index": {"rows": int(len(cidx)), "runs": int(cidx.run_id.nunique()),
                              "files": int(cidx.file.nunique()),
                              "runs_matching_trace_folders": int(len(set(cidx.run_id) & set(pop.run_id))),
                              "note": "metadata columns only (run_id, task_id, turn, captured_at, proxy request_id); bodies read only for A tasks"},
           "splits": {**nc.split_sizes_by_stratum(sp), "floor_used": sp["floor_used"], "files": sinfo, "index": idx},
           "A_cache": a_info, "A_report": rep,
           "calibration": {"file": f"analysis/out/phase_e/prereg_e_calibration_{CORPUS}.json",
                           "extension": f"analysis/out/phase_e/prereg_e_extensions/{CORPUS}.json",
                           "units": {k: {"calibrated_as_unit": v["calibrated_as_unit"], "sessions_A": v["sessions_A"],
                                         "resolved": v["resolved"]} for k, v in doc["units"].items()}},
           "selftest_split_code_path": st,
           "provider_request_id": ("request_id = response id from the joined capture body (SSE 'id'); minted by the "
                                   "serving process (local llama.cpp-style server or HF Router), not a first-party "
                                   "provider; Pi traces carry the same value as message.responseId. Not decodable "
                                   "to a clock (no embedded time); the clock is the body's integer 'created'."),
           "runtime_s": round(time.time() - t0, 1)}
    (nc.OUT_E / f"newcorp_build_{CORPUS}.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps({"N": out["population"]["N"], "A": len(sp["A"]), "B": len(sp["B"]), "E": len(sp["E"]),
                      "H": len(sp["H"]), "A_rows": a_info["rows"], "join": a_info["join"], "selftest": st,
                      "runtime_s": out["runtime_s"]}, default=str))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["B", "E"])
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.split:
        info = build_split(args.split)
        (nc.OUT_E / f"newcorp_build_{CORPUS}_{args.split}.json").write_text(json.dumps(info, indent=1, default=str),
                                                                            encoding="utf-8")
        print(json.dumps({k: info[k] for k in ("rows", "sessions")}))
    elif args.selftest:
        print(json.dumps(selftest()))
    else:
        main()
