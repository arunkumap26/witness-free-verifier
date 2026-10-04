"""Read-only census of HTTP response header KEYS and value SHAPES stored on aiv_cu Gemini rows
(agent_messages.sdkHttpResponse.headers), plus top-level GenerateContentResponse keys.
Values are reduced to shapes (digits->9, letters->a) except for a short whitelist of structural headers.
Stops after MAX_ROWS Gemini rows that carry headers. Output: JSON to stdout."""
import collections, gzip, json, re, sys, time

PATH = r"C:\Swarms\data\ai-village\computer_use_turns.jsonl.gz"
MAX_ROWS = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
t0 = time.time()
hdr_keys = collections.Counter()
top_keys = collections.Counter()
shapes = collections.defaultdict(collections.Counter)
months = collections.Counter()
n_lines = n_gem = n_hdr = 0


def shape(v):
    s = str(v)
    s = re.sub(r"[0-9]", "9", s)
    s = re.sub(r"[A-Za-z]", "a", s)
    return s[:80]


with gzip.open(PATH, "rt", encoding="utf-8") as f:
    for line in f:
        n_lines += 1
        if "responseId" not in line:
            continue
        d = json.loads(line)
        am = d.get("agent_messages")
        if not isinstance(am, dict) or "responseId" not in am:
            continue
        n_gem += 1
        for k in am:
            top_keys[k] += 1
        resp = am.get("sdkHttpResponse")
        hdr = (resp.get("headers") or {}) if isinstance(resp, dict) else {}
        if not hdr:
            continue
        n_hdr += 1
        months[str(d.get("created_at"))[:7]] += 1
        for k, v in hdr.items():
            hdr_keys[k.lower()] += 1
            if len(shapes[k.lower()]) < 8 or shape(v) in shapes[k.lower()]:
                shapes[k.lower()][shape(v)] += 1
        if n_hdr >= MAX_ROWS:
            break
json.dump({"path": PATH, "lines_read": n_lines, "gemini_rows": n_gem, "gemini_rows_with_headers": n_hdr,
           "months_with_headers": dict(sorted(months.items())), "top_level_keys": dict(top_keys.most_common()),
           "header_keys": dict(hdr_keys.most_common()),
           "header_value_shapes": {k: dict(v.most_common(5)) for k, v in shapes.items()},
           "seconds": round(time.time() - t0, 1)}, sys.stdout, indent=1)
