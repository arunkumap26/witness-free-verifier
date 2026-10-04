"""Literal values of structural (non-identifying) Gemini response headers, first N header-bearing rows; durations stripped."""
import collections, gzip, json, re, sys
PATH = r"C:\Swarms\data\ai-village\computer_use_turns.jsonl.gz"
WL = ("server", "x-gemini-service-tier", "vary", "content-type")
c = collections.defaultdict(collections.Counter); n = 0; st_names = collections.Counter(); models = collections.Counter()
rid_len = collections.Counter()
with gzip.open(PATH, "rt", encoding="utf-8") as f:
    for line in f:
        if "sdkHttpResponse" not in line:
            continue
        am = json.loads(line).get("agent_messages")
        if not isinstance(am, dict) or not isinstance(am.get("sdkHttpResponse"), dict):
            continue
        h = am["sdkHttpResponse"].get("headers") or {}
        n += 1
        for k in WL:
            if k in h: c[k][h[k]] += 1
        if "server-timing" in h:
            st_names[re.sub(r"\d+", "N", h["server-timing"])] += 1
        models[am.get("modelVersion")] += 1
        rid_len[len(am.get("responseId") or "")] += 1
        if n >= int(sys.argv[1]): break
print(json.dumps({"rows": n, "literals": {k: dict(v) for k, v in c.items()}, "server_timing_templates": dict(st_names),
                  "modelVersion": dict(models), "responseId_len": dict(rid_len)}, indent=1))
