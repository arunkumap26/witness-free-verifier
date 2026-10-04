"""B5e population census over every file this task downloaded (reads C:/Swarms/data/acquired/<corpus>/...; never executes
anything there). Produces the per-corpus schema notes and field coverage counts that go into B5e_cli_traces.json.

Per native format:
  claude_code : entries, user/assistant entries with ISO-ms timestamps, tool_use/tool_result join on tool_use_id,
                is_error, toolUseResult copies, requestId presence + Anthropic req_ decode (B2a layout, UNVERIFIED) and
                agreement window [-2 s, +600 s] (carrying entry ts minus id ms, same window as B4), models, CC versions.
  codex       : lines with ISO-ms timestamps, function/custom tool call<->output join on call_id, payload types,
                exec_command_end duration/exit_code, token_count events, any provider ids.
  pi          : entries with timestamps, toolCall<->toolResult join on toolCallId, isError, provider/model,
                assistant responseId families and decode agreement (OpenAI resp_ hex50 seconds, OpenRouter gen-<secs>).
  opencode    : messages with time.created, tool parts with callID+output and state.time.start/end (tool exec clock).
  captures    : agentcap parquet rows, run_id join to trace folders, captured_at resolution, SSE id/created/sla_metrics.
Usage: python census_downloaded.py <download_manifest.json> <out.json>
"""
import glob, json, os, re, statistics, sys
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(__file__))
from sample_audit import anth_ms, shape, parse_iso, sniff, ISO_MS  # noqa: E402


def q(xs):
    xs = sorted(xs)
    if not xs:
        return None
    pick = lambda p: xs[min(len(xs) - 1, int(p * (len(xs) - 1) + 0.5))]
    return {"n": len(xs), "min": round(xs[0], 3), "p05": round(pick(.05), 3), "p50": round(pick(.5), 3), "p95": round(pick(.95), 3), "max": round(xs[-1], 3)}


def pi_dec(rid):
    if rid.startswith("resp_"):
        b = rid[5:]
        try:
            if len(b) == 50 and b[16] == "0":
                return "openai_resp_hex50", int(b[18:26], 16) * 1000
        except ValueError:
            pass
        return "openai_resp_other", None
    m = re.match(r"^gen-(\d{10})-", rid)
    if m:
        return "openrouter_gen_secs", int(m.group(1)) * 1000
    if rid.startswith("gen-"):
        return "gen_other", None
    if rid.startswith("chatcmpl-"):
        return "chatcmpl", None
    if rid.startswith("msg_"):
        return "anthropic_msg", None
    if re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-", rid):
        return "uuid", None
    return "other", None


class Agg:
    def __init__(self):
        self.c = Counter(); self.lists = defaultdict(list); self.ctr = defaultdict(Counter)


def do_claude(rows, A):
    A.c["sessions"] += 1
    calls, res = {}, []
    for r in rows:
        if not isinstance(r, dict):
            continue
        A.ctr["entry_type"][str(r.get("type"))] += 1
        for k in r.keys():
            A.ctr["top_keys"][k] += 1
        if r.get("type") in ("user", "assistant"):
            A.c["ua_entries"] += 1
            t = r.get("timestamp")
            if t:
                A.c["ua_with_ts"] += 1
            if isinstance(t, str) and ISO_MS.match(t):
                A.c["ua_ts_iso_ms_z"] += 1
        if r.get("version"):
            A.ctr["cc_version"][str(r["version"])] += 1
        msg = r.get("message") if isinstance(r.get("message"), dict) else {}
        cont = msg.get("content") if isinstance(msg.get("content"), list) else []
        if r.get("type") == "assistant":
            A.c["assistant_entries"] += 1
            A.ctr["model"][str(msg.get("model"))] += 1
            rid = r.get("requestId")
            A.ctr["requestId_shape"][shape(rid) if rid else "<missing>"] += 1
            if msg.get("usage"):
                A.c["assistant_with_usage"] += 1
            if isinstance(rid, str) and rid.startswith("req_"):
                A.c["req_ids"] += 1
                ms, v7 = anth_ms(rid)
                if ms is not None and v7:
                    A.c["req_v7"] += 1
                    et = parse_iso(r.get("timestamp") or "")
                    if et is not None:
                        d = et * 1000 - ms
                        A.lists["req_delta_ms"].append(d)
                        A.c["req_agree"] += int(-2000 <= d <= 600000)
            for c in cont:
                if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("id"):
                    calls[c["id"]] = (r.get("timestamp"), r.get("requestId"))
                    A.ctr["tool_name"][str(c.get("name"))] += 1
        if r.get("type") == "user":
            if r.get("toolUseResult") is not None:
                A.c["toolUseResult_copies"] += 1
            for c in cont:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    res.append((c.get("tool_use_id"), r.get("timestamp")))
                    if c.get("is_error"):
                        A.c["results_is_error"] += 1
    A.c["tool_calls"] += len(calls); A.c["tool_results"] += len(res)
    j = [x for x in res if x[0] in calls]
    A.c["results_joined"] += len(j); A.c["calls_with_result"] += len({x[0] for x in j})
    A.c["calls_with_requestId"] += sum(1 for v in calls.values() if v[1])
    for cid, rts in j:
        a, b = parse_iso(calls[cid][0] or ""), parse_iso(rts or "")
        if a is not None and b is not None:
            A.lists["call_result_gap_s"].append(b - a)


def do_codex(rows, A):
    A.c["sessions"] += 1
    calls, outs = {}, []
    for r in rows:
        if not isinstance(r, dict):
            continue
        A.c["lines"] += 1
        if r.get("timestamp"):
            A.c["lines_with_ts"] += 1
        if isinstance(r.get("timestamp"), str) and ISO_MS.match(r["timestamp"]):
            A.c["lines_ts_iso_ms_z"] += 1
        p = r.get("payload") if isinstance(r.get("payload"), dict) else {}
        A.ctr["payload_type"][f"{r.get('type')}/{p.get('type')}"] += 1
        if r.get("type") == "session_meta":
            A.ctr["cli_version"][str(p.get("cli_version"))] += 1; A.ctr["originator"][str(p.get("originator"))] += 1
            A.ctr["model_provider"][str(p.get("model_provider"))] += 1
        if r.get("type") == "turn_context":
            A.ctr["model"][str(p.get("model"))] += 1
        for k in p.keys():
            A.ctr["payload_keys"][k] += 1
        if p.get("type") in ("function_call", "custom_tool_call", "local_shell_call") and p.get("call_id"):
            calls[p["call_id"]] = r.get("timestamp"); A.ctr["tool_name"][str(p.get("name"))] += 1
        if p.get("type") in ("function_call_output", "custom_tool_call_output") and p.get("call_id"):
            outs.append((p["call_id"], r.get("timestamp")))
        if p.get("type") == "exec_command_end":
            A.c["exec_command_end"] += 1
            A.c["exec_end_duration"] += int(p.get("duration") is not None); A.c["exec_end_exit_code"] += int(p.get("exit_code") is not None)
        if p.get("type") == "token_count":
            A.c["token_count_events"] += 1
    A.c["tool_calls"] += len(calls); A.c["tool_outputs"] += len(outs)
    j = [o for o in outs if o[0] in calls]
    A.c["outputs_joined"] += len(j)
    for cid, b in j:
        x, y = parse_iso(calls[cid] or ""), parse_iso(b or "")
        if x is not None and y is not None:
            A.lists["call_output_gap_s"].append(y - x)


def do_pi(rows, A):
    A.c["sessions"] += 1
    calls, res = {}, []
    for r in rows:
        if not isinstance(r, dict):
            continue
        A.c["entries"] += 1
        A.ctr["entry_type"][str(r.get("type"))] += 1
        if r.get("timestamp"):
            A.c["entries_with_ts"] += 1
        if r.get("type") == "session":
            A.ctr["session_version"][str(r.get("version"))] += 1
        m = r.get("message") if r.get("type") == "message" and isinstance(r.get("message"), dict) else None
        if not m:
            continue
        if isinstance(m.get("timestamp"), (int, float)):
            A.c["messages_with_epoch_ms"] += 1
        if m.get("role") == "assistant":
            A.c["assistant_messages"] += 1
            A.ctr["provider"][str(m.get("provider"))] += 1; A.ctr["model"][str(m.get("model"))] += 1
            rid = m.get("responseId")
            if rid:
                fam, ms = pi_dec(rid)
                A.ctr["responseId_family"][fam] += 1
                if ms is not None and isinstance(m.get("timestamp"), (int, float)):
                    d = m["timestamp"] - ms
                    A.lists[f"respid_delta_ms::{fam}"].append(d)
                    A.c[f"respid_within_5s::{fam}"] += int(abs(d) <= 5000)
            else:
                A.ctr["responseId_family"]["<missing>"] += 1
            for c in m.get("content") or []:
                if isinstance(c, dict) and c.get("type") == "toolCall" and c.get("id"):
                    calls[c["id"]] = m.get("timestamp"); A.ctr["tool_name"][str(c.get("name"))] += 1
        if m.get("role") == "toolResult":
            res.append((m.get("toolCallId"), m.get("timestamp")))
            if m.get("isError"):
                A.c["results_isError_true"] += 1
    A.c["tool_calls"] += len(calls); A.c["tool_results"] += len(res)
    j = [x for x in res if x[0] in calls]
    A.c["results_joined"] += len(j)
    for cid, b in j:
        if isinstance(b, (int, float)) and isinstance(calls[cid], (int, float)):
            A.lists["call_result_gap_s"].append((b - calls[cid]) / 1000)


def do_opencode(obj, A):
    A.c["sessions"] += 1
    for k in obj.keys():
        A.ctr["top_keys"][k] += 1
    for mm in obj.get("messages") or []:
        mi = mm.get("info") or {}
        A.c["messages"] += 1
        if (mi.get("time") or {}).get("created"):
            A.c["messages_with_time_created"] += 1
        if mi.get("role") == "assistant":
            A.ctr["model"][f"{mi.get('providerID')}/{mi.get('modelID')}"] += 1
            if mi.get("tokens"):
                A.c["assistant_with_tokens"] += 1
        for p in mm.get("parts") or []:
            A.ctr["part_type"][str(p.get("type"))] += 1
            if p.get("type") != "tool":
                continue
            A.c["tool_parts"] += 1
            st = p.get("state") or {}
            A.ctr["tool_status"][str(st.get("status"))] += 1; A.ctr["tool_name"][str(p.get("tool"))] += 1
            if p.get("callID") and "output" in st:
                A.c["tool_parts_callID_output"] += 1
            if st.get("status") == "error" and "error" in st:
                A.c["tool_parts_error_field"] += 1
            t = st.get("time") or {}
            if t.get("start") and t.get("end"):
                A.c["tool_parts_time_start_end"] += 1
                A.lists["tool_exec_s"].append((t["end"] - t["start"]) / 1000)


def do_capture(path, A, trace_runs):
    import pyarrow.parquet as pq
    t = pq.read_table(path)
    A.c["capture_files"] += 1; A.c["capture_rows"] += t.num_rows
    cols = t.column_names
    for c in cols:
        A.ctr["capture_columns"][c] += 1
    runs = Counter(t.column("run_id").to_pylist())
    for r, n in runs.items():
        A.ctr["capture_run_ids"][r] += n
        A.c["capture_rows_run_in_traces"] += n if r in trace_runs else 0
    prov = Counter(t.column("provider").to_pylist())
    for k, v in prov.items():
        A.ctr["capture_provider"][str(k)] += v
    resp = t.column("response").to_pylist()
    for s in resp:
        try:
            o = json.loads(s)
        except Exception:
            A.c["capture_resp_unparsed"] += 1; continue
        raw = o.get("raw") if isinstance(o, dict) else None
        if isinstance(raw, str):
            first = next((ln[6:] for ln in raw.split("\n") if ln.startswith("data: {")), None)
            try:
                ch = json.loads(first) if first else {}
            except Exception:
                ch = {}
        else:
            ch = o if isinstance(o, dict) else {}
        A.ctr["sse_id_shape"][shape(ch.get("id")) if ch.get("id") else "<missing>"] += 1
        A.c["sse_with_created"] += int(ch.get("created") is not None)
        A.c["sse_with_sla_ts_us"] += int(isinstance(ch.get("sla_metrics"), dict) and "ts_us" in ch["sla_metrics"])


def main():
    G = json.load(open(sys.argv[1], encoding="utf-8"))
    out = {}
    for rec in G["repos"]:
        if rec.get("status") != "DOWNLOADED":
            continue
        root = rec["dest"]; key = f"{rec['corpus']}::{rec['repo']}"
        aggs = defaultdict(Agg); unknown = Counter()
        trace_runs = set()
        for p in glob.glob(os.path.join(root, "data", "*")):
            if os.path.isdir(p):
                trace_runs.add(os.path.basename(p))
        for dp, dn, fn in os.walk(root):
            for f in fn:
                p = os.path.join(dp, f)
                if f.startswith("_b5e_") or f.endswith((".md", ".png", ".jpg", ".gitattributes", ".js", ".txt", ".yaml")):
                    continue
                try:
                    if f.endswith(".jsonl"):
                        rows = []
                        with open(p, encoding="utf-8", errors="replace") as fh:
                            for ln in fh:
                                ln = ln.strip()
                                if ln:
                                    try:
                                        rows.append(json.loads(ln))
                                    except Exception:
                                        aggs["_bad"].c["bad_lines"] += 1
                        k = sniff(rows)
                        {"claude_code": do_claude, "codex": do_codex, "pi": do_pi}.get(k, lambda r, A: unknown.update([k]))(rows, aggs[k])
                    elif f.endswith(".json"):
                        obj = json.load(open(p, encoding="utf-8", errors="replace"))
                        if isinstance(obj, dict) and "messages" in obj and "info" in obj:
                            do_opencode(obj, aggs["opencode"])
                        else:
                            unknown["json_other"] += 1
                    elif f.endswith(".parquet") and "captures" in rec["repo"]:
                        do_capture(p, aggs["captures"], set())
                    else:
                        unknown[os.path.splitext(f)[1] or "noext"] += 1
                except Exception as ex:
                    unknown["error:" + type(ex).__name__] += 1
        res = {"licence": rec.get("licence"), "sha": rec["sha"], "dest": root, "bytes": rec.get("bytes"), "unparsed_files": dict(unknown)}
        for k, A in aggs.items():
            d = dict(A.c)
            for name, ctr in A.ctr.items():
                d[name] = dict(ctr.most_common(25))
            for name, xs in A.lists.items():
                d[name] = q(xs)
            res[k] = d
        out[key] = res
        print(key, {k: (v.get("sessions") or v.get("capture_rows")) for k, v in res.items() if isinstance(v, dict) and k not in ("unparsed_files",)}, dict(unknown), flush=True)
    json.dump(out, open(sys.argv[2], "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
