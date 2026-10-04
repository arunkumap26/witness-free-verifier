"""B5e field audit on a SAMPLE: one native session file per (dataset, harness class), first <=3 MB via HTTP Range,
pinned to the dataset's commit sha. Sample bytes go to the scratchpad only (never committed, never executed).

Checks, per the B5 download rule: per-event timestamps AND a call/result join; plus provider request-id presence and
(for Anthropic `req_01...` ids) whether the id decodes (base58, top-48-bit ms, UUIDv7 bits; layout per B2a, UNVERIFIED
against vendor docs) to a time that sits in [-2 s, +600 s] before the carrying entry's timestamp (same window as B4).

Usage: python sample_audit.py <hf_files_census.json> <out.json> <sample_dir> [--ids id1,id2] [--licensed-native]
"""
import datetime as dt, json, os, re, statistics, sys, time, urllib.request, urllib.error
from collections import Counter, defaultdict

MAXB = 3_000_000
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"; B58I = {c: i for i, c in enumerate(B58)}
ISO_MS = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
ISO_ANY = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)?$")
IDKEY = re.compile(r"(?i)^(x-)?(request|req|response|resp|trace|span|completion|generation)[-_]?id$")
OKLIC = {"mit", "apache-2.0", "cc-by-4.0", "cc0-1.0", "bsd-3-clause", "agpl-3.0", "cc-by-sa-4.0", "odc-by", "cdla-permissive-2.0"}


def parse_iso(s):
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def anth_ms(rid):
    body = rid.rsplit("_", 1)[-1]
    if body[:2] != "01" or any(c not in B58I for c in body[2:]):
        return None, False
    v = 0
    for c in body[2:]:
        v = v * 58 + B58I[c]
    v7 = ((v >> 76) & 0xF) == 7 and ((v >> 62) & 0x3) == 2
    return (v >> 80), v7


def shape(v):
    if not isinstance(v, str):
        return type(v).__name__
    s = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<uuid>", v)
    m = re.match(r"^([A-Za-z]+[_-]+(?:[A-Za-z]+_)?)(.*)$", s)
    if m and not s.startswith("<uuid>"):
        return f"{m.group(1)}<{len(m.group(2))}>"
    return s if s == "<uuid>" else f"<str{len(v)}>"


def walk_ids(o, path, acc, depth=0):
    if depth > 8:
        return
    if isinstance(o, dict):
        for k, v in o.items():
            p = path + "." + k
            if IDKEY.match(k) and (isinstance(v, (str, int))):
                acc[re.sub(r"\.\d+", ".#", p)][shape(v)] += 1
            if isinstance(v, (dict, list)):
                walk_ids(v, p, acc, depth + 1)
    elif isinstance(o, list):
        for x in o[:200]:
            walk_ids(x, path + ".#", acc, depth + 1)


def fetch(rid, sha, path, dest):
    url = f"https://huggingface.co/datasets/{rid}/resolve/{sha}/{urllib.request.quote(path)}"
    for k in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "research-audit", "Range": f"bytes=0-{MAXB - 1}"})
            r = urllib.request.urlopen(req, timeout=120)
            b = r.read()
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            open(dest, "wb").write(b)
            return b, url
        except urllib.error.HTTPError as ex:
            if ex.code == 429:
                time.sleep(10 * (k + 1)); continue
            raise
    raise RuntimeError("429")


def jsonl_lines(b, truncated):
    txt = b.decode("utf-8", "replace")
    lines = txt.split("\n")
    if truncated and lines:
        lines = lines[:-1]
    out, bad = [], 0
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except Exception:
            bad += 1
    return out, bad


def audit_claude_code(rows):
    m = {"format": "claude_code_jsonl", "n_entries": len(rows)}
    m["entry_types"] = dict(Counter(str(r.get("type")) for r in rows))
    ts = [r.get("timestamp") for r in rows if isinstance(r, dict) and r.get("type") in ("user", "assistant")]
    m["user_assistant_entries"] = len(ts)
    m["ua_with_timestamp"] = sum(1 for t in ts if t)
    m["ts_iso_ms_z"] = sum(1 for t in ts if isinstance(t, str) and ISO_MS.match(t))
    m["ts_example"] = next((t for t in ts if t), None)
    calls, results, res_err = {}, [], 0
    req_ids, msg_ids, models, versions, has_tur, usage = Counter(), Counter(), Counter(), Counter(), 0, 0
    dec = {"n": 0, "decoded": 0, "v7": 0, "agree_m2_p600": 0, "deltas_ms": []}
    for r in rows:
        if not isinstance(r, dict):
            continue
        if r.get("version"):
            versions[str(r["version"])] += 1
        msg = r.get("message") if isinstance(r.get("message"), dict) else {}
        cont = msg.get("content") if isinstance(msg.get("content"), list) else []
        if r.get("type") == "assistant":
            rid = r.get("requestId")
            req_ids[shape(rid) if rid else "<missing>"] += 1
            msg_ids[shape(msg.get("id")) if msg.get("id") else "<missing>"] += 1
            models[str(msg.get("model"))] += 1
            if msg.get("usage"):
                usage += 1
            if isinstance(rid, str) and rid.startswith("req_"):
                dec["n"] += 1
                ms, v7 = anth_ms(rid)
                if ms is not None:
                    dec["decoded"] += 1; dec["v7"] += int(v7)
                    et = parse_iso(r.get("timestamp") or "")
                    if et is not None and v7:
                        d = et * 1000 - ms
                        dec["deltas_ms"].append(d)
                        if -2000 <= d <= 600000:
                            dec["agree_m2_p600"] += 1
            for c in cont:
                if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("id"):
                    calls[c["id"]] = r.get("timestamp")
        if r.get("type") == "user":
            if r.get("toolUseResult") is not None:
                has_tur += 1
            for c in cont:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    results.append((c.get("tool_use_id"), r.get("timestamp")))
                    if c.get("is_error"):
                        res_err += 1
    joined = [x for x in results if x[0] in calls]
    m.update(tool_use_blocks=len(calls), tool_result_blocks=len(results), results_joined_to_call=len(joined),
             calls_with_result=len({x[0] for x in joined}), results_is_error_true=res_err, user_entries_with_toolUseResult=has_tur,
             assistant_with_usage=usage, requestId_shapes=dict(req_ids.most_common(6)), message_id_shapes=dict(msg_ids.most_common(4)),
             models=dict(models.most_common(6)), cc_versions=dict(versions.most_common(4)))
    gaps = []
    for cid, rts in joined:
        a, b = parse_iso(calls[cid] or ""), parse_iso(rts or "")
        if a is not None and b is not None:
            gaps.append(b - a)
    if gaps:
        m["call_to_result_gap_s"] = {"n": len(gaps), "p50": round(statistics.median(gaps), 3), "min": round(min(gaps), 3), "max": round(max(gaps), 3)}
    dl = dec.pop("deltas_ms")
    if dl:
        dec["delta_ms_p50"] = round(statistics.median(dl)); dec["delta_ms_min"] = round(min(dl)); dec["delta_ms_max"] = round(max(dl))
    m["anthropic_request_id_decode"] = dec
    return m


def audit_codex(rows):
    m = {"format": "codex_rollout_jsonl", "n_lines": len(rows)}
    m["with_timestamp"] = sum(1 for r in rows if isinstance(r, dict) and r.get("timestamp"))
    m["ts_iso_ms_z"] = sum(1 for r in rows if isinstance(r, dict) and isinstance(r.get("timestamp"), str) and ISO_MS.match(r["timestamp"]))
    m["ts_example"] = next((r.get("timestamp") for r in rows if isinstance(r, dict) and r.get("timestamp")), None)
    pt = Counter()
    calls, outs, item_ids, exec_end, exec_dur, exit_codes, tokc = {}, [], Counter(), 0, 0, 0, 0
    meta = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        p = r.get("payload") if isinstance(r.get("payload"), dict) else {}
        t = f"{r.get('type')}/{p.get('type')}"
        pt[t] += 1
        if r.get("type") == "session_meta":
            meta = {k: p.get(k) for k in ("cli_version", "originator", "model_provider", "source") if k in p}
        if p.get("type") in ("function_call", "custom_tool_call", "local_shell_call") and p.get("call_id"):
            calls[p["call_id"]] = r.get("timestamp")
            item_ids[shape(p.get("id")) if p.get("id") else "<missing>"] += 1
        if p.get("type") in ("function_call_output", "custom_tool_call_output") and p.get("call_id"):
            outs.append((p["call_id"], r.get("timestamp")))
        if p.get("type") == "exec_command_end":
            exec_end += 1
            if p.get("duration") is not None:
                exec_dur += 1
            if p.get("exit_code") is not None:
                exit_codes += 1
        if p.get("type") == "token_count":
            tokc += 1
    joined = [o for o in outs if o[0] in calls]
    gaps = [parse_iso(b) - parse_iso(calls[c]) for c, b in joined if parse_iso(b or "") is not None and parse_iso(calls[c] or "") is not None]
    m.update(payload_types=dict(pt.most_common(25)), session_meta=meta, tool_calls=len(calls), tool_outputs=len(outs),
             outputs_joined_to_call=len(joined), call_item_id_shapes=dict(item_ids.most_common(5)),
             exec_command_end=exec_end, exec_end_with_duration=exec_dur, exec_end_with_exit_code=exit_codes, token_count_events=tokc)
    if gaps:
        m["call_to_output_gap_s"] = {"n": len(gaps), "p50": round(statistics.median(gaps), 3), "min": round(min(gaps), 3), "max": round(max(gaps), 3)}
    return m


def audit_pi(rows):
    m = {"format": "pi_session_jsonl", "n_entries": len(rows)}
    m["entry_types"] = dict(Counter(str(r.get("type")) for r in rows if isinstance(r, dict)))
    msgs = [r for r in rows if isinstance(r, dict) and r.get("type") == "message" and isinstance(r.get("message"), dict)]
    m["message_entries"] = len(msgs)
    m["entries_with_timestamp"] = sum(1 for r in rows if isinstance(r, dict) and r.get("timestamp"))
    m["ts_example"] = next((r.get("timestamp") for r in rows if isinstance(r, dict) and r.get("timestamp")), None)
    m["message_ts_epoch_ms"] = sum(1 for r in msgs if isinstance(r["message"].get("timestamp"), (int, float)))
    roles = Counter(r["message"].get("role") for r in msgs)
    calls, res, models, prov, resp_ids, usage = {}, [], Counter(), Counter(), Counter(), 0
    for r in msgs:
        mm = r["message"]
        if mm.get("role") == "assistant":
            models[str(mm.get("model"))] += 1; prov[str(mm.get("provider"))] += 1
            resp_ids[shape(mm.get("responseId")) if mm.get("responseId") else "<missing>"] += 1
            if mm.get("usage"):
                usage += 1
            for c in mm.get("content") or []:
                if isinstance(c, dict) and c.get("type") == "toolCall" and c.get("id"):
                    calls[c["id"]] = mm.get("timestamp")
        if mm.get("role") == "toolResult":
            res.append((mm.get("toolCallId"), mm.get("timestamp"), mm.get("isError")))
    joined = [x for x in res if x[0] in calls]
    gaps = [(b - calls[c]) / 1000 for c, b, _ in joined if isinstance(b, (int, float)) and isinstance(calls[c], (int, float))]
    m.update(roles=dict(roles), tool_calls=len(calls), tool_results=len(res), results_joined_to_call=len(joined),
             results_with_isError_field=sum(1 for x in res if x[2] is not None), models=dict(models.most_common(5)),
             providers=dict(prov.most_common(5)), assistant_responseId_shapes=dict(resp_ids.most_common(5)), assistant_with_usage=usage)
    if gaps:
        m["call_to_result_gap_s"] = {"n": len(gaps), "p50": round(statistics.median(gaps), 3), "min": round(min(gaps), 3), "max": round(max(gaps), 3)}
    return m


def audit_opencode(obj):
    m = {"format": "opencode_export_json"}
    msgs = obj.get("messages") or []
    m["n_messages"] = len(msgs)
    info = obj.get("info") or {}
    m["session_time_keys"] = sorted((info.get("time") or {}).keys())
    tparts, joined_inline, with_tstart, with_tend, models, ids, msg_time = 0, 0, 0, 0, Counter(), Counter(), 0
    status = Counter(); durs = []
    for mm in msgs:
        mi = mm.get("info") or {}
        if (mi.get("time") or {}).get("created"):
            msg_time += 1
        if mi.get("role") == "assistant":
            models[f"{mi.get('providerID')}/{mi.get('modelID')}"] += 1
        for p in mm.get("parts") or []:
            if p.get("type") == "tool":
                tparts += 1
                st = p.get("state") or {}
                status[str(st.get("status"))] += 1
                if p.get("callID") and "output" in st:
                    joined_inline += 1
                ids[shape(p.get("callID"))] += 1
                t = st.get("time") or {}
                if t.get("start"):
                    with_tstart += 1
                if t.get("end"):
                    with_tend += 1
                if t.get("start") and t.get("end"):
                    durs.append((t["end"] - t["start"]) / 1000)
    m.update(messages_with_time_created=msg_time, tool_parts=tparts, tool_parts_with_callID_and_output=joined_inline,
             tool_state_time_start=with_tstart, tool_state_time_end=with_tend, tool_status=dict(status), callID_shapes=dict(ids.most_common(4)),
             models=dict(models.most_common(5)))
    if durs:
        m["tool_exec_duration_s"] = {"n": len(durs), "p50": round(statistics.median(durs), 3), "min": round(min(durs), 3), "max": round(max(durs), 3)}
    return m


def sniff(rows):
    if not rows:
        return "empty"
    r0 = [r for r in rows[:20] if isinstance(r, dict)]
    if any(r.get("type") in ("session_meta", "response_item", "event_msg", "turn_context") and "payload" in r for r in r0):
        return "codex"
    if any(r.get("type") == "session" and "cwd" in r for r in r0) or any(r.get("type") == "message" and isinstance(r.get("message"), dict) and "role" in r["message"] and "parentId" in r for r in r0):
        return "pi"
    if any("sessionId" in r and r.get("type") in ("user", "assistant", "summary", "system", "progress", "attachment", "queue-operation", "file-history-snapshot", "custom-title", "last-prompt", "permission-mode") for r in r0) or any(r.get("type") in ("user", "assistant") and "uuid" in r for r in r0):
        return "claude_code"
    return "unknown"


def pick(files, cls):
    fs = [f for f in files if f["cls"] == cls and (f["size"] or 0) > 0]
    if not fs:
        return None
    if cls == "opencode":
        fs2 = [f for f in fs if f["size"] <= MAXB] or fs
    else:
        fs2 = fs
    sizes = sorted(f["size"] for f in fs2)
    target = min(sizes[len(sizes) // 2], MAXB)
    big = [f for f in fs2 if f["size"] >= 20000] or fs2
    return min(big, key=lambda f: abs(f["size"] - target))


def main():
    cen = json.load(open(sys.argv[1], encoding="utf-8"))["datasets"]
    out, sdir = sys.argv[2], sys.argv[3]
    ids = None
    if "--ids" in sys.argv:
        ids = sys.argv[sys.argv.index("--ids") + 1].split(",")
    try:
        res = json.load(open(out, encoding="utf-8"))
    except Exception:
        res = {}
    todo = []
    for rid, e in cen.items():
        if "error" in e or e.get("gated"):
            continue
        if ids is not None and rid not in ids:
            continue
        lic = (e.get("license_tags") or ["license:none"])[0].split(":", 1)[1]
        if ids is None and lic not in OKLIC:
            continue
        for cls in ("claude_code", "claude_code_subagent", "codex", "pi", "opencode"):
            if (e.get("class_counts") or {}).get(cls):
                todo.append((rid, e, cls, lic))
    for rid, e, cls, lic in todo:
        key = f"{rid}::{cls}"
        if key in res and "error" not in res[key]:
            continue
        f = pick(e["files"], cls)
        rec = {"dataset": rid, "class": cls, "licence": lic, "sha": e["sha"], "sample_path": f["path"], "sample_file_size": f["size"],
               "sample_lfs_sha256": f.get("lfs_sha256")}
        try:
            dest = os.path.join(sdir, rid.replace("/", "__"), f["path"].replace("/", "__"))
            b, url = fetch(rid, e["sha"], f["path"], dest)
            rec["url"] = url; rec["bytes_read"] = len(b); rec["truncated"] = len(b) < (f["size"] or 0)
            if cls == "opencode":
                obj = json.loads(b.decode("utf-8", "replace"))
                rec["metrics"] = audit_opencode(obj)
                acc = defaultdict(Counter); walk_ids(obj, "", acc)
            else:
                rows, bad = jsonl_lines(b, rec["truncated"])
                rec["bad_lines"] = bad
                kind = sniff(rows)
                rec["sniffed"] = kind
                rec["metrics"] = {"claude_code": audit_claude_code, "codex": audit_codex, "pi": audit_pi}.get(kind, lambda r: {"format": kind, "n": len(r)})(rows)
                acc = defaultdict(Counter)
                for r in rows[:5000]:
                    walk_ids(r, "", acc)
            rec["id_like_keys"] = {k: dict(v.most_common(3)) for k, v in sorted(acc.items(), key=lambda kv: -sum(kv[1].values()))[:15]}
        except Exception as ex:
            rec["error"] = repr(ex)
        res[key] = rec
        mm = rec.get("metrics", {})
        print(key, lic, rec.get("sniffed", cls), "|", {k: mm.get(k) for k in ("ua_with_timestamp", "with_timestamp", "entries_with_timestamp", "tool_use_blocks", "tool_calls", "tool_parts", "results_joined_to_call", "outputs_joined_to_call", "tool_parts_with_callID_and_output", "requestId_shapes") if k in mm}, rec.get("error", ""), flush=True)
        json.dump(res, open(out, "w", encoding="utf-8"), indent=1)
        time.sleep(0.5)


if __name__ == "__main__":
    main()
