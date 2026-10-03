"""Recon: local Claude Code JSONL. Timestamps, usage fields, toolUseResult timing fields, entry types.
Writes analysis/out/recon/cc_local.txt. Read-only over data/claude-code-local."""
import collections, glob, json, os, re, sys
from datetime import datetime

ROOT = os.environ.get("SWARMS_DATA", "C:/Swarms/data")
OUT = os.path.join(os.path.dirname(__file__), "..", "out", "recon", "cc_local.txt")
files = sorted(glob.glob(f"{ROOT}/claude-code-local/**/*.jsonl", recursive=True))

types = collections.Counter()
ts_frac = collections.Counter()      # number of fractional-second digits in timestamp strings
tur_keys = collections.Counter()     # toolUseResult keys, by tool
dur_fields = collections.Counter()
usage_keys = collections.Counter()
top_keys = collections.Counter()
progress_sub = collections.Counter()
call_ts, res_ts, call_tool = {}, {}, {}
n_lines = 0
for f in files:
    for line in open(f, encoding="utf-8", errors="replace"):
        n_lines += 1
        try:
            e = json.loads(line)
        except Exception:
            types["<unparseable>"] += 1
            continue
        t = e.get("type")
        types[t] += 1
        for k in e:
            top_keys[(t, k)] += 1
        ts = e.get("timestamp")
        if isinstance(ts, str):
            m = re.search(r"\.(\d+)", ts)
            ts_frac[len(m.group(1)) if m else 0] += 1
        if t == "progress":
            d = e.get("data") or {}
            progress_sub[d.get("type") if isinstance(d, dict) else type(d).__name__] += 1
        msg = e.get("message") or {}
        if isinstance(msg, dict):
            u = msg.get("usage")
            if isinstance(u, dict):
                for k in u:
                    usage_keys[k] += 1
            content = msg.get("content")
            if isinstance(content, list):
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_use":
                        call_ts[b["id"]] = ts
                        call_tool[b["id"]] = b.get("name")
                    elif b.get("type") == "tool_result":
                        res_ts[b.get("tool_use_id")] = ts
                        tur = e.get("toolUseResult")
                        tool = call_tool.get(b.get("tool_use_id"), "?")
                        if isinstance(tur, dict):
                            for k in tur:
                                tur_keys[(tool, k)] += 1
                                if re.search(r"(?i)dur|ms$|time", k):
                                    dur_fields[(tool, k)] += 1


def p(dt):
    return datetime.fromisoformat(dt.replace("Z", "+00:00"))


lat = []
same = 0
for cid, ct in call_ts.items():
    rt = res_ts.get(cid)
    if ct and rt:
        d = (p(rt) - p(ct)).total_seconds()
        lat.append(d)
        same += d == 0
lat.sort()
ms_mult = sum(1 for x in lat if abs(x * 1000 - round(x * 1000)) < 1e-6)

with open(OUT, "w", encoding="utf-8") as o:
    w = lambda *a: print(*a, file=o)
    w(f"files {len(files)} lines {n_lines}")
    w("entry types", dict(types.most_common()))
    w("timestamp fractional digits", dict(ts_frac))
    w("progress data.type", dict(progress_sub.most_common(20)))
    w("usage keys", dict(usage_keys.most_common()))
    w(f"paired call/result with both timestamps: {len(lat)}; identical stamps: {same}; ms-multiples: {ms_mult}")
    if lat:
        q = lambda f: lat[min(len(lat) - 1, int(f * len(lat)))]
        w(f"result_ts - call_ts seconds: min {lat[0]} p1 {q(.01)} p5 {q(.05)} p50 {q(.5)} p95 {q(.95)} max {lat[-1]}")
        w(f"negative deltas: {sum(1 for x in lat if x < 0)}")
    w("toolUseResult duration-like fields (tool, key): count")
    for k, v in dur_fields.most_common(40):
        w("  ", k, v)
    w("toolUseResult keys by tool (top 80)")
    for k, v in tur_keys.most_common(80):
        w("  ", k, v)
    w("top-level keys by entry type (top 80)")
    for k, v in top_keys.most_common(80):
        w("  ", k, v)
print(open(OUT, encoding="utf-8").read())
