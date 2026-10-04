"""B5e: population census of the TraceLab v0.0.2 release (one JSON row per LLM round). Counts field coverage needed
by N1/N3/N4 (per-tool emitted_at/result_at, result_chars, wall vs internal latency, is_error, exit codes) by provider.
Usage: python census_tracelab.py <jsonl.gz> <out.json>"""
import gzip, json, re, sys
from collections import Counter, defaultdict
c = defaultdict(Counter); sess = defaultdict(set); models = defaultdict(Counter); ev = defaultdict(Counter); keys = Counter(); tkeys = Counter()
ISO = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
idlike = Counter()
for ln in gzip.open(sys.argv[1], "rt", encoding="utf-8"):
    r = json.loads(ln); p = r.get("provider")
    c[p]["rounds"] += 1; sess[p].add(r.get("session_id")); models[p][r.get("model")] += 1
    for k in r: keys[k] += 1
    for k in r:
        if re.search(r"(?i)request|response_id|req_id", k): idlike[k] += 1
    for e in r.get("timing_events") or []:
        ev[p][e.get("event_type")] += 1
        c[p]["timing_events"] += 1; c[p]["timing_events_iso_ms"] += int(bool(ISO.match(e.get("timestamp") or "")))
    for t in r.get("tools") or []:
        for k in t: tkeys[k] += 1
        c[p]["tools"] += 1
        c[p]["tools_with_call_id"] += int(bool(t.get("tool_call_id")))
        c[p]["tools_emitted_and_result_at"] += int(bool(t.get("emitted_at") and t.get("result_at")))
        c[p]["tools_result_chars"] += int(t.get("result_chars") is not None)
        c[p]["tools_internal_latency"] += int(t.get("tool_internal_latency_ms") is not None)
        c[p]["tools_wall_latency"] += int(t.get("tool_wall_latency_ms") is not None)
        c[p]["tools_is_error_true"] += int(t.get("is_error") is True)
        c[p]["tools_exit_code"] += int(t.get("command_exit_code") is not None)
        c[p]["tools_wall_lt_internal"] += int(t.get("tool_internal_latency_ms") is not None and t.get("tool_wall_latency_ms") is not None and t["tool_wall_latency_ms"] < t["tool_internal_latency_ms"])
out = {"by_provider": {p: dict(c[p], sessions=len(sess[p]), models=dict(models[p].most_common(8)), timing_event_types=dict(ev[p])) for p in c},
       "row_keys": dict(keys), "tool_keys": dict(tkeys), "request_or_response_id_keys": dict(idlike)}
json.dump(out, open(sys.argv[2], "w", encoding="utf-8"), indent=1)
print(json.dumps(out, indent=1)[:4000])
