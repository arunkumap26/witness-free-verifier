"""Field audit on a small sample of each candidate HF dataset.
Reads at most RANGE bytes from the start of 1-2 data files (HTTP Range) or the
datasets-server first-rows API for parquet. Nothing is written outside the scratchpad.
"""
import json, re, sys, time, gzip, zlib, io, urllib.request, urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import zstandard
from huggingface_hub import get_token

RANGE = 400_000
TOKEN = get_token()
HDR = {"User-Agent": "b5d-field-audit/1.0"}
if TOKEN:
    HDR["Authorization"] = "Bearer " + TOKEN

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")
TSKEY = re.compile(r"(^|_)(time|timestamp|ts|created|createdat|created_at|start|end|started|ended|completed|starttime|endtime|start_time|end_time|starttimeunixnano|endtimeunixnano|time_unix_nano|date)$", re.I)
REQKEY = re.compile(r"^(requestid|request_id|x-request-id|request-id|req_id)$", re.I)
REQVAL = re.compile(r"\breq_[A-Za-z0-9]{20,}")
DATA_EXT = (".jsonl", ".json", ".jsonl.gz", ".json.gz", ".jsonl.zst", ".parquet", ".ndjson")


def fetch_range(repo, sha, path, n=RANGE):
    url = f"https://huggingface.co/datasets/{repo}/resolve/{sha}/{urllib.parse.quote(path)}"
    req = urllib.request.Request(url, headers={**HDR, "Range": f"bytes=0-{n-1}"})
    for a in range(6):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read(n)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(30 * (a + 1)); continue
            raise
    raise RuntimeError("429 persist")


def first_rows(repo):
    base = "https://datasets-server.huggingface.co"
    q = urllib.parse.urlencode({"dataset": repo})
    with urllib.request.urlopen(urllib.request.Request(f"{base}/splits?{q}", headers=HDR), timeout=60) as r:
        sp = json.load(r)["splits"][0]
    q2 = urllib.parse.urlencode({"dataset": repo, "config": sp["config"], "split": sp["split"]})
    with urllib.request.urlopen(urllib.request.Request(f"{base}/first-rows?{q2}", headers=HDR), timeout=90) as r:
        fr = json.load(r)
    return [row["row"] for row in fr.get("rows", [])][:30], [f["name"] for f in fr.get("features", [])]


def decode(raw, path):
    if path.endswith(".gz"):
        raw = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw)
    elif path.endswith(".zst"):
        d = zstandard.ZstdDecompressor().decompressobj()
        try:
            raw = d.decompress(raw)
        except Exception:
            pass
    return raw.decode("utf-8", "replace")


def parse_records(text, path):
    recs = []
    if path.endswith(".json") or path.endswith(".json.gz"):
        try:
            obj = json.loads(text)
            if isinstance(obj, list):
                return obj[:200], "json_array"
            if isinstance(obj, dict):
                for k in ("messages", "events", "steps", "trajectory", "history", "spans", "resourceSpans", "data", "turns"):
                    if isinstance(obj.get(k), list):
                        return [obj] + obj[k][:200], f"json_obj[{k}]"
                return [obj], "json_obj"
        except Exception:
            pass  # truncated: fall through to line parse
    for line in text.split("\n")[:-1] if not text.endswith("\n") else text.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            recs.append(json.loads(line))
        except Exception:
            continue
    return recs, "jsonl"


def walk(o, depth=0, maxd=6):
    if depth > maxd:
        return
    if isinstance(o, dict):
        for k, v in o.items():
            yield k, v, depth
            yield from walk(v, depth + 1, maxd)
    elif isinstance(o, list):
        for v in o[:400]:
            yield from walk(v, depth + 1, maxd)


def dict_nodes(o, depth=0, maxd=7):
    if depth > maxd:
        return
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from dict_nodes(v, depth + 1, maxd)
    elif isinstance(o, list):
        for v in o[:400]:
            yield from dict_nodes(v, depth + 1, maxd)


def is_ts_value(v):
    if isinstance(v, str):
        return bool(ISO.match(v.strip()))
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return 1.0e9 <= v <= 2.2e9 or 1.0e12 <= v <= 2.2e12 or 1.0e15 <= v <= 2.2e15 or 1.0e18 <= v <= 2.2e18
    return False


def ts_resolution(vals):
    res = Counter()
    for v in vals[:500]:
        if isinstance(v, str):
            m = re.search(r":\d{2}\.(\d+)", v)
            res["iso_" + (f"{len(m.group(1))}dp" if m else "s")] += 1
        elif isinstance(v, float) and v < 2.2e9:
            res["epoch_s_float"] += 1
        elif v < 2.2e9:
            res["epoch_s"] += 1
        elif v < 2.2e12:
            res["epoch_ms"] += 1
        elif v < 2.2e15:
            res["epoch_us"] += 1
        else:
            res["epoch_ns"] += 1
    return dict(res)


def detect_format(recs):
    c = Counter()
    for r in recs[:200]:
        if not isinstance(r, dict):
            c["nondict"] += 1; continue
        t = r.get("type")
        if "sessionId" in r and t in ("user", "assistant", "system", "summary", "attachment", "progress") or ("parentUuid" in r and "uuid" in r):
            c["claude_code"] += 1
        elif t in ("session_meta", "response_item", "event_msg", "turn_context", "compacted") and "payload" in r:
            c["codex"] += 1
        elif t == "session" and "harness" in r:
            c["sts_header"] += 1
        elif t == "session" and ("cwd" in r or "version" in r):
            c["pi_header"] += 1
        elif t in ("message", "model_change", "thinking_level_change", "compaction", "custom", "branch_summary") and ("parentId" in r or "id" in r) and "message" in r or t in ("model_change", "thinking_level_change"):
            c["pi_or_sts_message"] += 1
        elif "messages" in r or "conversations" in r:
            c["messages_list"] += 1
        elif any(k in r for k in ("traceId", "spanId", "resourceSpans", "trace_id", "span_id")):
            c["otel_like"] += 1
        elif "info" in r and "parts" in r:
            c["opencode_export"] += 1
        else:
            c["other"] += 1
    return c


def audit_records(recs):
    n = len(recs)
    fmt = detect_format(recs)
    ts_vals, events_with_ts = [], 0
    tskeys = Counter()
    call_ids, result_ids = set(), set()
    reqkeys, reqvals = Counter(), set()
    tokkeys = Counter()
    trunc = 0
    errkeys = Counter()
    topkeys = Counter()
    for r in recs:
        if isinstance(r, dict):
            topkeys.update(r.keys())
        has_ts = False
        for k, v, d in walk(r):
            kl = str(k)
            if TSKEY.search(kl) and is_ts_value(v):
                tskeys[kl] += 1
                ts_vals.append(v)
                if d <= 2:
                    has_ts = True
            if REQKEY.match(kl) and isinstance(v, str) and v:
                reqkeys[kl] += 1
                reqvals.add(v[:40])
            if kl in ("input_tokens", "output_tokens", "prompt_tokens", "completion_tokens", "cache_read_input_tokens", "total_tokens", "inputTokens", "outputTokens", "usage"):
                tokkeys[kl] += 1
            if kl in ("is_error", "isError", "exit_code", "exitCode", "returncode", "error"):
                errkeys[kl] += 1
        for v in dict_nodes(r):
            ty = v.get("type")
            if ty in ("tool_use", "server_tool_use", "mcp_tool_use") and isinstance(v.get("id"), str):
                call_ids.add(v["id"])
            if ty in ("tool_result", "mcp_tool_result") and isinstance(v.get("tool_use_id"), str):
                result_ids.add(v["tool_use_id"])
            if ty in ("function_call", "custom_tool_call", "local_shell_call") and isinstance(v.get("call_id"), str):
                call_ids.add(v["call_id"])
            if ty in ("function_call_output", "custom_tool_call_output", "local_shell_call_output") and isinstance(v.get("call_id"), str):
                result_ids.add(v["call_id"])
            if ty == "toolCall" and isinstance(v.get("id"), str):
                call_ids.add(v["id"])
            if isinstance(v.get("toolCallId"), str):
                result_ids.add(v["toolCallId"])
            if isinstance(v.get("tool_call_id"), str):
                result_ids.add(v["tool_call_id"])
            if isinstance(v.get("function"), dict) and isinstance(v.get("id"), str):
                call_ids.add(v["id"])
            for kk in ("tool_calls", "toolCalls"):
                if isinstance(v.get(kk), list):
                    for tc in v[kk]:
                        if isinstance(tc, dict) and isinstance(tc.get("id"), str):
                            call_ids.add(tc["id"])
        if has_ts:
            events_with_ts += 1
        s = json.dumps(r)[:200000] if not isinstance(r, str) else r
        if re.search(r"truncat", s, re.I):
            trunc += 1
        for m in REQVAL.findall(s):
            reqvals.add(m[:40])
    joined = len(call_ids & result_ids)
    return {
        "n_records": n,
        "format_votes": dict(fmt.most_common(4)),
        "top_keys": [k for k, _ in topkeys.most_common(15)],
        "events_with_ts_depth_le2": events_with_ts,
        "ts_coverage": round(events_with_ts / n, 3) if n else 0,
        "ts_keys": dict(tskeys.most_common(6)),
        "ts_resolution": ts_resolution(ts_vals),
        "n_call_ids": len(call_ids), "n_result_ids": len(result_ids), "n_joined": joined,
        "join_rate_calls": round(joined / len(call_ids), 3) if call_ids else None,
        "request_id_keys": dict(reqkeys), "request_id_examples": sorted(reqvals)[:3], "n_request_id_values": len(reqvals),
        "token_keys": dict(tokkeys), "error_keys": dict(errkeys), "records_mentioning_truncat": trunc,
    }


RAWKEYS = ["\"timestamp\"", "\"startTimeUnixNano\"", "\"start_time\"", "\"created_at\"", "\"tool_call_id\"", "\"tool_use_id\"", "\"call_id\"", "\"toolCallId\"", "\"requestId\"", "\"request_id\"", "\"traceId\"", "\"spanId\"", "\"input_tokens\"", "\"prompt_tokens\"", "\"is_error\"", "\"exit_code\""]


def raw_scan(text):
    d = {k.strip('"'): text.count(k) for k in RAWKEYS}
    d = {k: v for k, v in d.items() if v}
    d["req_values"] = len(set(REQVAL.findall(text)))
    return d


def parquet_probe(repo, sha, path):
    import pyarrow.parquet as pq
    from huggingface_hub import HfFileSystem
    fs = HfFileSystem()
    f = fs.open(f"datasets/{repo}@{sha}/{path}", "rb", block_size=2_000_000)
    pf = pq.ParquetFile(f)
    md = pf.metadata
    out = {"num_rows": md.num_rows, "num_row_groups": md.num_row_groups, "schema": str(pf.schema_arrow)[:3000]}
    rg0 = md.row_group(0)
    out["rg0_bytes"] = rg0.total_byte_size
    if rg0.total_byte_size < 40_000_000:
        batch = next(pf.iter_batches(batch_size=20))
        out["rows"] = batch.to_pylist()
    return out


def pick_files(sib):
    files = [s for s in sib if s["path"].lower().endswith(DATA_EXT) and not s["path"].lower().endswith(("dataset_infos.json", "dataset_info.json", "state.json", "package.json", "config.json", "tokenizer.json"))]
    if not files:
        return []
    files.sort(key=lambda s: s["path"])
    picks = [files[0]]
    if len(files) > 2:
        picks.append(files[len(files) // 2])
    return picks


def audit(meta):
    rid = meta["id"]
    out = {"id": rid, "sha": meta.get("sha")}
    sib = meta.get("siblings", [])
    picks = pick_files(sib)
    out["n_data_files"] = sum(1 for s in sib if s["path"].lower().endswith(DATA_EXT))
    if not picks:
        out["status"] = "no_data_files"; out["exts"] = Counter(s["path"].rsplit(".", 1)[-1] for s in sib).most_common(5)
        return out
    res = []
    for p in picks:
        r = {"path": p["path"], "size": p["size"]}
        try:
            if p["path"].endswith(".parquet"):
                try:
                    rows, feats = first_rows(rid)
                    r["via"] = "datasets-server first-rows"; r["features"] = feats
                except Exception as e1:
                    pp = parquet_probe(rid, meta["sha"], p["path"])
                    rows = pp.pop("rows", [])
                    r["via"] = "parquet footer + first batch"; r["parquet"] = pp
                recs = []
                for row in rows:
                    for k, v in list(row.items()):
                        if isinstance(v, str) and v[:1] in "[{":
                            try:
                                row[k] = json.loads(v)
                            except Exception:
                                pass
                    recs.append(row)
                r["audit"] = audit_records(recs)
                res.append(r); break
            raw = fetch_range(rid, meta["sha"], p["path"])
            r["bytes_read"] = len(raw)
            text = decode(raw, p["path"])
            recs, how = parse_records(text, p["path"])
            r["parse"] = how
            r["audit"] = audit_records(recs)
            r["raw_scan"] = raw_scan(text)
        except Exception as e:
            r["error"] = repr(e)[:200]
        res.append(r)
    out["samples"] = res
    out["status"] = "ok"
    return out


if __name__ == "__main__":
    metas = json.load(open("meta.json"))
    only = set(sys.argv[1:])
    if only:
        metas = [m for m in metas if m["id"] in only]
    with ThreadPoolExecutor(2) as ex:
        results = list(ex.map(audit, metas))
    json.dump(results, open("audit.json" if not only else "audit_subset.json", "w"), indent=1)
    print(len(results), Counter(r["status"] for r in results))
